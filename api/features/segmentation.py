"""
Segmentation — the segments, what they are worth, and the builder behind them.

Built to the approved mockups. One request fills the page; one endpoint counts
a segment while the merchant is still typing it.

WHAT A SEGMENT IS
    A name and a list of conditions. Nothing is materialised: a segment is
    re-evaluated every time it is read, so a client who came in this morning
    has already left "Clients inactifs" by the time the page loads. That is
    also why a segment can be handed straight to a campaign — the list is
    never stale.

"POTENTIEL DE CA" — THE ONE FIGURE THAT IS AN ESTIMATE
    Not a count, and not last month's takings. It is what this segment could
    plausibly bring in if the merchant ran one campaign at it:

        CA_potentiel(S) = Σ_client ( AOV_client × P_conversion(recency) )

    · AOV_client is that client's OWN average basket, not the shop's flat
      average — otherwise a VIP segment is under-valued and a dormant one
      over-valued. A client who has never bought has no basket of their own,
      so the shop average stands in for them; it is the only honest estimate
      available and it is stated on the page.
    · P_conversion comes from recency, because that is what actually predicts
      whether a push is answered:

          seen within 30 days   30 %
          30 – 60 days          18 %
          60 – 90 days          12 %
          over 90, or never      8 %

    The badge is RELATIVE to the shop, never a hardcoded euro amount — a
    bakery and a boutique cannot share a threshold. Measured against the
    merchant's own average weekly revenue:

          < 5 %        Faible
          5 – 15 %     Moyen
          15 – 30 %    Élevé
          ≥ 30 %       Très élevé

    A shop too young to have a weekly average falls back to comparing its
    segments against each other (top 20 % → Très élevé, and so on down).

    Every one of those numbers is printed on the page. An estimate that does
    not say how it was reached is just a colour.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role
from models import TokenData
from features import store_scope as S

# Segmentation is read and used by the owner, administrateurs and managers —
# each counting the clients of the establishments it may see. Segments are
# shared definitions; each account edits or removes its own (the owner any).
READERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["segmentation"])
_db = None

NAME_MAX = 50
MAX_RULES = 10

# Conversion probability by days since the last visit. The bands, and the
# numbers in them, are the merchant's own assumptions — they live here, named,
# rather than being buried in an expression.
P_BANDS: List[Tuple[Optional[int], float]] = [
    (30, 0.30),      # seen this month
    (60, 0.18),      # cooling
    (90, 0.12),      # at risk
    (None, 0.08),    # dormant, or never came
]

# Potential as a share of one average week of revenue.
BADGES: List[Tuple[float, str, str]] = [
    (0.30, "tres_eleve", "Très élevé"),
    (0.15, "eleve", "Élevé"),
    (0.05, "moyen", "Moyen"),
    (0.0, "faible", "Faible"),
]

TIER_CHOICES = [
    {"key": "non_membre", "label": "Non membre"},
    {"key": "bronze", "label": "Bronze"},
    {"key": "silver", "label": "Argent"},
    {"key": "gold", "label": "Or"},
    {"key": "vip", "label": "VIP"},
]

# The builder's vocabulary. Each field carries its own operators because
# French does not let one list serve them all: a *distance* is "inférieure",
# a *montant* is "inférieur". `short` is the wording of the summary panel,
# which reads as a sentence rather than as a form.
FIELDS: List[Dict[str, Any]] = [
    {
        "key": "last_visit", "label": "Dernière visite", "icon": "calendar",
        "type": "days", "unit": "jours",
        "ops": [{"key": "gt", "label": "il y a plus de", "short": "il y a plus de"},
                {"key": "lt", "label": "il y a moins de", "short": "il y a moins de"}],
    },
    {
        "key": "visits", "label": "Nombre d'achats", "icon": "cart",
        "type": "number", "unit": "",
        "ops": [{"key": "eq", "label": "est égal à", "short": "égal à"},
                {"key": "gt", "label": "est supérieur à", "short": "supérieur à"},
                {"key": "lt", "label": "est inférieur à", "short": "inférieur à"}],
    },
    # Two money criteria (QA R5 F24, 2026-10-09): « Montant dépensé » used to
    # compute the average basket, so « > 1 000 € » found nobody while two
    # customers had spent 2 775 €. `spend` keeps its meaning (saved segments
    # and the « Gros / Petits paniers » models use it) under its true name.
    {
        "key": "total_spend", "label": "Total dépensé", "icon": "coins",
        "type": "number", "unit": "€",
        "note": "Tout ce que le client a dépensé depuis son inscription (0 € s'il n'a jamais acheté).",
        "ops": [{"key": "gt", "label": "est supérieur à", "short": "supérieur à"},
                {"key": "lt", "label": "est inférieur à", "short": "inférieur à"},
                {"key": "eq", "label": "est égal à", "short": "égal à"}],
    },
    {
        "key": "spend", "label": "Panier moyen", "icon": "coins",
        "type": "number", "unit": "€",
        "note": "Montant moyen par visite, depuis l'inscription. Seuls les clients qui ont déjà acheté sont comptés.",
        "ops": [{"key": "lt", "label": "est inférieur à", "short": "inférieur à"},
                {"key": "gt", "label": "est supérieur à", "short": "supérieur à"},
                {"key": "eq", "label": "est égal à", "short": "égal à"}],
    },
    {
        "key": "distance", "label": "Distance du magasin", "icon": "pin",
        "type": "number", "unit": "km",
        "ops": [{"key": "lt", "label": "est inférieure à", "short": "moins de"},
                {"key": "gt", "label": "est supérieure à", "short": "plus de"}],
    },
    {
        "key": "tier", "label": "Statut fidélité", "icon": "star",
        "type": "choice", "unit": "", "choices": TIER_CHOICES,
        "ops": [{"key": "eq", "label": "est égal à", "short": ""}],
    },
    {
        "key": "joined", "label": "Date d'inscription", "icon": "users",
        "type": "days", "unit": "jours",
        "ops": [{"key": "gt", "label": "il y a plus de", "short": "il y a plus de"},
                {"key": "lt", "label": "il y a moins de", "short": "il y a moins de"}],
    },
]
FIELD_BY_KEY = {f["key"]: f for f in FIELDS}

# The five ready-made segments of the design. Each is a real rule set, so
# "Utiliser ce segment" creates something the merchant can then edit — not a
# special case the builder cannot express.
MODELS: List[Dict[str, Any]] = [
    {"key": "inactifs", "name": "Clients inactifs", "icon": "star", "tone": "violet",
     "description": "N'ont pas acheté depuis 30 jours.",
     "rules": [{"field": "last_visit", "op": "gt", "value": 30}]},
    {"key": "fideles", "name": "Clients fidèles", "icon": "users", "tone": "green",
     "description": "Plus de 5 achats au cours des 3 derniers mois.",
     "rules": [{"field": "visits", "op": "gt", "value": 5},
               {"field": "last_visit", "op": "lt", "value": 90}]},
    {"key": "nouveaux", "name": "Nouveaux clients", "icon": "gift", "tone": "rose",
     "description": "Inscrits depuis moins de 30 jours.",
     "rules": [{"field": "joined", "op": "lt", "value": 30}]},
    {"key": "gros_paniers", "name": "Gros paniers", "icon": "cart", "tone": "amber",
     "description": "Panier moyen supérieur à 20 €.",
     "rules": [{"field": "spend", "op": "gt", "value": 20}]},
    {"key": "locaux", "name": "Clients locaux", "icon": "pin", "tone": "blue",
     "description": "À moins de 5 km de votre commerce.",
     "rules": [{"field": "distance", "op": "lt", "value": 5}]},
    # Behind the first five: what takes a model's place once it is in use.
    {"key": "vip", "name": "Palier VIP", "icon": "star", "tone": "amber",
     "description": "Ont atteint le palier VIP de votre carte.",
     "rules": [{"field": "tier", "op": "eq", "value": "vip"}]},
    {"key": "anciens_fideles", "name": "Anciens fidèles", "icon": "users", "tone": "rose",
     "description": "Plus de 5 achats, mais absents depuis 60 jours.",
     "rules": [{"field": "visits", "op": "gt", "value": 5},
               {"field": "last_visit", "op": "gt", "value": 60}]},
    {"key": "sans_achat", "name": "Inscrits sans achat", "icon": "gift", "tone": "violet",
     "description": "Ont créé leur carte mais ne sont jamais venus.",
     "rules": [{"field": "tier", "op": "eq", "value": "non_membre"}]},
    {"key": "habitues", "name": "Habitués du mois", "icon": "star", "tone": "green",
     "description": "Plus de 3 achats et venus ce mois-ci.",
     "rules": [{"field": "visits", "op": "gt", "value": 3},
               {"field": "last_visit", "op": "lt", "value": 30}]},
    {"key": "petits_paniers", "name": "Petits paniers", "icon": "cart", "tone": "slate",
     "description": "Panier moyen inférieur à 8 €.",
     "rules": [{"field": "spend", "op": "lt", "value": 8}]},
]
def _models(tid: Optional[str]) -> List[Dict[str, Any]]:
    """The models for this shop: « Clients inactifs » follows the shop's own
    « Client actif » window (Règles clients), as the Clients page, the
    Dashboard and Campagnes do — one definition of inactive everywhere."""
    try:
        from features import customer_rules as R
        days = R.active_days(R.load(tid)) if tid else 30
    except Exception:
        days = 30
    out = []
    for m in MODELS:
        if m["key"] == "inactifs":
            m = {**m, "description": f"Ne sont pas venus depuis plus de {days} jours.",
                 "rules": [{"field": "last_visit", "op": "gt", "value": days}]}
        out.append(m)
    return out


# The five the table always shows, as in the design.
TABLE_MODELS = ("inactifs", "fideles", "nouveaux", "gros_paniers", "locaux")
SHOWN_MODELS = 5


def init(db):
    global _db
    _db = db
    try:
        db.saved_segments.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Time and shapes
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _days_since(value: Any, at: datetime) -> Optional[float]:
    d = _aware(value)
    return None if not d else (at - d).total_seconds() / 86400.0


def _eur(n: float) -> str:
    """145,33 € — a French amount (QA: the chip read « 145.33 € »)."""
    n = round(float(n or 0) + 1e-9, 2)
    s = f"{n:,.0f}" if n == int(n) else f"{n:,.2f}"
    return s.replace(",", " ").replace(".", ",") + " €"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _pct(part: float, whole: float) -> int:
    return round(part / whole * 100) if whole else 0


def _avg_basket(cust: Dict[str, Any]) -> Optional[float]:
    """This client's own average basket, or None when they have never bought."""
    visits = int(_num(cust.get("visits")))
    if visits <= 0:
        return None
    return _num(cust.get("total_amount_paid")) / visits


# ---------------------------------------------------------------------------
# Distance — reused from the map, so "à moins de 5 km" means the same thing
# on both pages.
# ---------------------------------------------------------------------------
def _distances(tid: str, rows: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Kilometres from the shop, per client — the map's own arithmetic, so
    "à moins de 5 km" means the same thing on both pages."""
    try:
        from features import geolocation as geo
        tenant = _db.tenants.find_one({"id": tid}) or {}
        s_lat, s_lng, _ = geo._shop_position(tenant)
        if s_lat is None or s_lng is None:
            return {}
        out: Dict[str, Optional[float]] = {}
        for c in rows:
            c_lat, c_lng, _src = geo._client_position(c)
            out[c["id"]] = (geo._haversine_km(s_lat, s_lng, c_lat, c_lng)
                            if c_lat is not None and c_lng is not None else None)
        return out
    except Exception as exc:      # a missing map must not cost the page
        print(f"segmentation: distances unavailable (non-fatal): {exc}")
        return {}


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
def _clean_rules(raw: Any) -> List[Dict[str, Any]]:
    """Keep only rules the builder can actually express.

    Anything unknown is dropped rather than ignored at match time: a segment
    whose stored rule silently does nothing would show a count the merchant
    cannot explain.
    """
    out: List[Dict[str, Any]] = []
    for r in (raw or [])[:MAX_RULES]:
        if not isinstance(r, dict):
            continue
        field = FIELD_BY_KEY.get(str(r.get("field") or ""))
        if not field:
            continue
        op = str(r.get("op") or "")
        if op not in {o["key"] for o in field["ops"]}:
            continue
        value = r.get("value")
        if field["type"] == "choice":
            if str(value) not in {c["key"] for c in field["choices"]}:
                continue
            value = str(value)
        else:
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
            if value < 0:
                continue
        out.append({"field": field["key"], "op": op, "value": value})
    return out


def _matches(cust: Dict[str, Any], rule: Dict[str, Any], at: datetime,
             distance: Optional[float]) -> bool:
    field, op, value = rule["field"], rule["op"], rule["value"]

    if field in ("last_visit", "joined"):
        if field == "last_visit" and op == "gt":
            # « Pas venu depuis plus de N jours » counts like every other page
            # (QA F04, 2026-10-08: Segmentation said 98 inactive, Clients 0):
            # a client who never came is aged from their sign-up, so someone
            # who joined today is not « inactive » (clients_page.last_contact).
            from features.clients_page import last_contact
            source = last_contact(cust)
        else:
            source = cust.get("last_visit_date") if field == "last_visit" else cust.get("created_at")
        days = _days_since(source, at)
        if days is None:
            # No date at all: « more than N days » is true of someone with no
            # trace; « less than N » (a recent visit, a recent sign-up) cannot be.
            return op == "gt"
        # whole days, as the Clients page counts them (30.5 days is « 30 »)
        whole = math.floor(days)
        return whole > value if op == "gt" else whole < value

    if field == "visits":
        n = _num(cust.get("visits"))
        return n == value if op == "eq" else (n > value if op == "gt" else n < value)

    if field == "total_spend":
        # lifetime total; someone who never bought has spent 0 €
        total = _num(cust.get("total_amount_paid"))
        return abs(total - value) < 0.005 if op == "eq" else (total > value if op == "gt" else total < value)

    if field == "spend":
        # « Panier moyen » — the average basket, not the lifetime total.
        basket = _avg_basket(cust)
        if basket is None:
            # Never bought: no basket at all, small or big (QA, 2026-10-08:
            # « Petits paniers (< 8 €) » held all 100 clients who never came).
            return False
        return basket == value if op == "eq" else (basket > value if op == "gt" else basket < value)

    if field == "distance":
        if distance is None:
            return False               # unknown address is not "within 5 km"
        return distance < value if op == "lt" else distance > value

    if field == "tier":
        if value == "non_membre":
            return int(_num(cust.get("visits"))) <= 0
        return str(cust.get("tier") or "bronze").lower() == value

    return False


def evaluate(tid: str, rules: List[Dict[str, Any]],
             rows: Optional[List[Dict[str, Any]]] = None,
             at: Optional[datetime] = None,
             distances: Optional[Dict[str, Optional[float]]] = None) -> List[Dict[str, Any]]:
    """The clients a rule set names, right now. Rules are ANDed.

    An empty rule set is the whole client base — that is what the builder
    shows before the merchant has added a condition, and it is honest: no
    condition excludes nobody.
    """
    at = at or _now()
    rows = rows if rows is not None else list(_db.customers.find({"tenant_id": tid, "deleted_at": None}, {"_id": 0}))
    if not rules:
        return list(rows)
    need_distance = any(r["field"] == "distance" for r in rules)
    if need_distance and distances is None:
        distances = _distances(tid, rows)
    distances = distances or {}
    return [c for c in rows
            if all(_matches(c, r, at, distances.get(c["id"])) for r in rules)]


def describe(rules: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The "Résumé des critères" panel — one plain sentence per condition."""
    out = []
    for r in rules:
        field = FIELD_BY_KEY[r["field"]]
        op = next(o for o in field["ops"] if o["key"] == r["op"])
        if field["type"] == "choice":
            label = next(c["label"] for c in field["choices"] if c["key"] == r["value"])
            text = f"{field['label']} : {label}"
        else:
            n = int(r["value"]) if float(r["value"]).is_integer() else r["value"]
            unit = f" {field['unit']}" if field["unit"] else ""
            text = f"{field['label']} : {op['short']} {n}{unit}".replace("  ", " ")
        out.append({"icon": field["icon"], "text": text})
    return out


# ---------------------------------------------------------------------------
# Potentiel de CA
# ---------------------------------------------------------------------------
def _p_conversion(cust: Dict[str, Any], at: datetime) -> float:
    days = _days_since(cust.get("last_visit_date"), at)
    if days is None:
        return P_BANDS[-1][1]
    for limit, p in P_BANDS:
        if limit is None or days < limit:
            return p
    return P_BANDS[-1][1]


def _weekly_revenue(tid: str, at: datetime, scope: Optional["S.Scope"] = None) -> float:
    """One average week of takings, over the last twelve.

    Twelve weeks rather than one, because a single quiet week would make every
    segment look extraordinary.
    """
    since = at - timedelta(weeks=12)
    rows = _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": since},
                            **(S.visit_filter(scope) if scope else {})},
                           {"_id": 0, "amount_paid": 1})
    return sum(_num(r.get("amount_paid")) for r in rows) / 12.0


def potential(people: List[Dict[str, Any]], shop_avg_basket: float,
              at: datetime) -> Dict[str, Any]:
    """What one campaign at this segment could plausibly bring in."""
    amount = 0.0
    p_sum = 0.0
    for c in people:
        basket = _avg_basket(c)
        if basket is None:
            basket = shop_avg_basket          # never bought — the shop average stands in
        p = _p_conversion(c, at)
        amount += basket * p
        p_sum += p
    n = len(people)
    return {
        "amount": _money(amount),
        "clients": n,
        "avg_basket": _money(sum(_avg_basket(c) or shop_avg_basket for c in people) / n) if n else 0.0,
        "avg_conversion": round(p_sum / n * 100) if n else 0,
    }


def _badge(amount: float, weekly: float, ranked: Optional[List[float]] = None) -> Dict[str, str]:
    """Faible → Très élevé, against the shop's own week.

    Falling back to a comparison between the shop's own segments when there is
    no week to measure against is the only alternative that still says
    something true: it stops claiming an absolute and states a ranking.
    """
    if weekly > 0:
        share = amount / weekly
        for threshold, key, label in BADGES:
            if share >= threshold:
                return {"key": key, "label": label,
                        "basis": f"{round(share * 100)} % d'une semaine de chiffre d'affaires"}
    if ranked:
        ordered = sorted(ranked)
        rank = sum(1 for x in ordered if x < amount) / len(ordered)
        for threshold, key, label in ((0.8, "tres_eleve", "Très élevé"), (0.5, "eleve", "Élevé"),
                                      (0.2, "moyen", "Moyen"), (0.0, "faible", "Faible")):
            if rank >= threshold:
                return {"key": key, "label": label,
                        "basis": "comparé à vos autres segments"}
    return {"key": "faible", "label": "Faible", "basis": "pas encore assez d'historique"}


# ---------------------------------------------------------------------------
# Stored segments
# ---------------------------------------------------------------------------
def _stored(tid: str) -> List[Dict[str, Any]]:
    return list(_db.saved_segments.find({"tenant_id": tid}, {"_id": 0}))


def _rules_of(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A stored segment's rules.

    Segments saved from the Clients page carry a `filters` blob instead; they
    are shown, counted and reported like any other, they simply cannot be
    edited in the builder. `rules` wins where both exist.
    """
    return _clean_rules(doc.get("rules") or [])


def _adopted(tid: str) -> set:
    """Model keys the merchant has already saved as their own segment — by the
    key recorded since, or by name for segments saved before it was."""
    names = {m["name"]: m["key"] for m in MODELS}
    out = set()
    for d in _stored(tid):
        if d.get("model"):
            out.add(d["model"])
        elif d.get("name") in names:
            out.add(names[d["name"]])
    return out


def _model_rows(tid: str) -> List[Dict[str, Any]]:
    """The design's five models, as rows — minus any the merchant saved, whose
    own row stands in for it. A merchant who has created nothing still has a
    page that counts their real clients rather than an empty table."""
    adopted = _adopted(tid)
    return [{"id": f"model:{m['key']}", "name": m["name"], "description": m["description"],
             "icon": m["icon"], "tone": m["tone"], "rules": m["rules"],
             "builtin": True, "created_at": None, "last_used_at": None}
            for m in _models(tid) if m["key"] in TABLE_MODELS and m["key"] not in adopted]


def _segment_rows(tid: str, at: datetime) -> List[Dict[str, Any]]:
    rows = _model_rows(tid)
    for doc in sorted(_stored(tid), key=lambda d: _aware(d.get("created_at")) or at, reverse=True):
        rules = _rules_of(doc)
        rows.append({
            "id": doc.get("id"), "name": doc.get("name") or "Segment",
            "description": doc.get("description") or (
                f"{len(rules)} critère{'s' if len(rules) > 1 else ''}" if rules else "Tous vos clients"),
            "icon": doc.get("icon") or "target", "tone": doc.get("tone") or "blue",
            "rules": rules, "builtin": False, "created_by": doc.get("created_by"),
            "created_at": doc.get("created_at"), "last_used_at": doc.get("last_used_at"),
        })
    return rows


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
@router.get("/api/owner/segmentation/page")
def page(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    at = _now()
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    people = list(_db.customers.find(S.customer_filter(scope), {"_id": 0}))
    total = len(people)
    baskets = [b for b in (_avg_basket(c) for c in people) if b is not None]
    shop_avg = sum(baskets) / len(baskets) if baskets else 0.0
    weekly = _weekly_revenue(tid, at, scope)
    distances = _distances(tid, people)

    rows = _segment_rows(tid, at)
    sized = []
    for row in rows:
        matched = evaluate(tid, row["rules"], people, at, distances)
        pot = potential(matched, shop_avg, at)
        sized.append({**row, "count": len(matched), "share": _pct(len(matched), total),
                      "potential": pot,
                      "summary": describe(row["rules"])})
    amounts = [s["potential"]["amount"] for s in sized]
    for s in sized:
        s["potential"]["badge"] = _badge(s["potential"]["amount"], weekly, amounts)

    # Campagnes ciblées — sent to a chosen audience rather than to everybody.
    month = at - timedelta(days=30)
    prev = at - timedelta(days=60)
    def _targeted(start, end):
        out = []
        for c in _db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}):
            sent = _aware(c.get("sent_at"))
            if sent and start <= sent <= end and (c.get("segment") or "all") != "all":
                if mine is not None:
                    ids = [i for i in c.get("recipient_ids") or [] if i in mine]
                    if not ids:
                        continue
                    c = {**c, "recipient_ids": ids}
                out.append(c)
        return out
    now_camp, prev_camp = _targeted(month, at), _targeted(prev, month)

    def _revenue(camps):
        gained = 0.0
        for c in camps:
            ids = list(c.get("recipient_ids") or [])
            sent = _aware(c.get("sent_at"))
            if not ids or not sent:
                continue
            for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": ids},
                                      "visit_time": {"$gte": sent,
                                                     "$lte": sent + timedelta(days=15)},
                                      **S.visit_filter(scope)},
                                     {"_id": 0, "amount_paid": 1}):
                gained += _num(v.get("amount_paid"))
        return gained

    new_month = [c for c in people if (d := _days_since(c.get("created_at"), at)) is not None and d <= 30]
    prev_month = [c for c in people if (d := _days_since(c.get("created_at"), at)) is not None and 30 < d <= 60]
    best = max(sized, key=lambda s: s["potential"]["amount"], default=None)

    strip = [
        {"key": "clients", "label": "Clients total", "icon": "users", "value": total,
         "delta_pct": _pct(len(new_month), len(prev_month)) - 100 if prev_month else None,
         "hint": "vs mois précédent"},
        {"key": "segments", "label": "Segments actifs", "icon": "segments",
         "value": len([s for s in sized if s["count"] > 0]),
         "hint": f"sur {len(sized)} créés"},
        {"key": "campaigns", "label": "Campagnes ciblées", "icon": "send",
         "value": len(now_camp),
         "delta_pct": _pct(_revenue(now_camp), _revenue(prev_camp)) - 100 if _revenue(prev_camp) else None,
         "hint": "de CA sur ces campagnes"},
        {"key": "best", "label": "Meilleur segment", "icon": "target",
         "text": best["name"] if best else "—",
         "chip": f"{_eur(best['potential']['amount'])} de potentiel" if best else "—",
         "hint": "ce mois-ci"},
    ]

    return {
        "strip": strip,
        "models": _recommended_models(tid, people, at, distances),
        "segments": sized,
        "fields": FIELDS,
        "tips": _tips(sized, total, tid, at, scope),
        "goal": _goal(tid, at, scope),
        "scope": scope.describe(),
        "total_clients": total,
        "potential_note": (
            "Le potentiel de CA est une estimation : pour chaque client, son panier moyen "
            "multiplié par sa probabilité de revenir (30 % vu ce mois-ci, 18 % entre 30 et "
            "60 jours, 12 % entre 60 et 90, 8 % au-delà). Le badge compare ce montant à une "
            "semaine moyenne de votre chiffre d'affaires."),
        "empty": total == 0,
    }


def _recommended_models(tid, people, at, distances) -> List[Dict[str, Any]]:
    """Five ready-made segments the merchant has not made their own yet.

    Once one is used, it leaves this row and the next model takes its place.
    Models that would hold nobody in THIS shop are passed over — recommending
    an empty segment is not a recommendation.
    """
    adopted = _adopted(tid)
    out = []
    for m in _models(tid):
        if m["key"] in adopted:
            continue
        n = len(evaluate(tid, m["rules"], people, at, distances))
        if n == 0 and people:
            continue
        out.append({**m, "count": n})
        if len(out) >= SHOWN_MODELS:
            break
    return out


def _goal(tid: str, at: datetime, scope: Optional["S.Scope"] = None) -> Dict[str, Any]:
    """The month's goal — the SAME one the Tableau de bord tracks.

    It lives on the tenant (`monthly_revenue_goal`), set in Paramètres. Two
    pages reading one field is the point: a merchant who moves the target on
    one page must not find the old one still standing on the other.
    """
    tenant = _db.tenants.find_one({"id": tid}) or {}
    if scope is not None and not scope.is_all:
        from features import dashboard_home as DH
        target = DH.goal_target(tenant, scope)
    else:
        target = _num(tenant.get("monthly_revenue_goal"))
    start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    made = sum(_num(v.get("amount_paid")) for v in
               _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": start},
                                **(S.visit_filter(scope) if scope else {})},
                               {"_id": 0, "amount_paid": 1}))
    return {"target": _money(target), "reached": _money(made),
            "remaining": _money(max(0.0, target - made)),
            "pct": round(min(100, made / target * 100)) if target else None,
            "is_set": target > 0}


TIP_TEMPLATES = {"Clients inactifs": "relance_inactifs", "Clients fidèles": "fideles_merci",
                 "Clients locaux": "offre_locale"}


def _tips(sized: List[Dict[str, Any]], total: int, tid: Optional[str] = None,
          at: Optional[datetime] = None, scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    """Three suggestions, each pointing at a segment that really exists and a
    campaign ready to send to it.

    A tip whose campaign went out in the last two weeks gives its place to the
    next one — the page never keeps asking for what was just done.
    """
    from features import insights_page as E
    used = E.used_templates(tid, at or _now(), scope=scope) if tid else {}
    by_key = {s["name"]: s for s in sized}
    candidates = []
    dormant = by_key.get("Clients inactifs")
    if dormant and dormant["count"]:
        candidates.append({"title": "Réactivez vos clients inactifs", "segment_id": dormant["id"],
                           "template": TIP_TEMPLATES["Clients inactifs"],
                           "body": f"{dormant['count']} clients n'ont pas acheté depuis 30 jours. "
                                   f"Une campagne pourrait rapporter environ "
                                   f"{round(dormant['potential']['amount'])} €."})
    loyal = by_key.get("Clients fidèles")
    if loyal and loyal["count"]:
        candidates.append({"title": "Valorisez vos clients fidèles", "segment_id": loyal["id"],
                           "template": TIP_TEMPLATES["Clients fidèles"],
                           "body": f"{loyal['count']} clients, soit {loyal['share']} % de votre base, "
                                   f"reviennent régulièrement. Proposez-leur un avantage exclusif."})
    local = by_key.get("Clients locaux")
    if local and local["count"]:
        candidates.append({"title": "Attirez plus de clients locaux", "segment_id": local["id"],
                           "template": TIP_TEMPLATES["Clients locaux"],
                           "body": f"{local['count']} clients habitent à moins de 5 km. "
                                   f"Communiquez sur vos offres de proximité."})
    for s in sorted(sized, key=lambda s: -s["potential"]["amount"]):
        if s["count"] and not any(c["segment_id"] == s["id"] for c in candidates):
            candidates.append({"title": f"Ciblez « {s['name']} »", "segment_id": s["id"],
                               "template": f"seg:{s['id']}",
                               "body": f"{s['count']} clients, potentiel estimé "
                                       f"{round(s['potential']['amount'])} €."})
    return [c for c in candidates if c["template"] not in used][:3]


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------
class Preview(BaseModel):
    rules: List[Dict[str, Any]] = []


@router.post("/api/owner/segmentation/preview")
def preview(req: Preview, request: Request = None,
            token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The count under the builder, while the merchant is still typing.

    Same evaluator as everything else on the page, so the number they approve
    is the number the segment will hold.
    """
    tid = token_data.tenant_id
    at = _now()
    rules = _clean_rules(req.rules)
    people = list(_db.customers.find(S.customer_filter(S.resolve(token_data, request)), {"_id": 0}))
    matched = evaluate(tid, rules, people, at)
    return {"count": len(matched), "total": len(people),
            "share": _pct(len(matched), len(people)),
            "summary": describe(rules),
            "dropped": len(req.rules or []) - len(rules)}


class SegmentIn(BaseModel):
    name: str
    rules: List[Dict[str, Any]] = []
    description: Optional[str] = None
    icon: Optional[str] = None
    tone: Optional[str] = None
    model: Optional[str] = None      # "Utiliser ce segment" on one of the five


@router.post("/api/owner/segmentation/segments")
def create(req: SegmentIn, request: Request = None,
           token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    rules, name = _clean_rules(req.rules), (req.name or "").strip()[:NAME_MAX]
    icon, tone, description = req.icon, req.tone, req.description

    if req.model:
        model = next((m for m in _models(tid) if m["key"] == req.model), None)
        if not model:
            raise HTTPException(status_code=404, detail="Modèle inconnu")
        rules = rules or _clean_rules(model["rules"])
        name = name or model["name"]
        icon, tone = icon or model["icon"], tone or model["tone"]
        description = description or model["description"]

    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom à ce segment.")
    if _db.saved_segments.find_one({"tenant_id": tid, "name": name}):
        raise HTTPException(status_code=409, detail=f"Un segment « {name} » existe déjà.")

    doc = {"id": str(uuid.uuid4()), "tenant_id": tid, "name": name,
           "description": (description or "").strip()[:200],
           "icon": icon or "target", "tone": tone or "blue",
           "rules": rules, "filters": {}, "segment": None,
           "model": req.model or None,
           "created_at": _now(), "last_used_at": None,
           "created_by": getattr(token_data, "email", None)}
    _db.saved_segments.insert_one(dict(doc))
    at = _now()
    people = list(_db.customers.find(S.customer_filter(S.resolve(token_data, request)), {"_id": 0}))
    matched = evaluate(tid, rules, people, at=at)
    return {**doc, "count": len(matched), "summary": describe(rules)}


def _owned(doc: Dict[str, Any], token_data: TokenData) -> bool:
    return token_data.role == "business_owner" or doc.get("created_by") == getattr(token_data, "email", None)


@router.put("/api/owner/segmentation/segments/{segment_id}")
def update(segment_id: str, req: SegmentIn, request: Request = None,
           token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    doc = _db.saved_segments.find_one({"id": segment_id, "tenant_id": tid})
    if not doc:
        raise HTTPException(status_code=404, detail="Segment introuvable")
    if not _owned(doc, token_data):
        raise HTTPException(status_code=403, detail="Seul son auteur (ou le propriétaire) peut le modifier.")
    patch: Dict[str, Any] = {}
    if (req.name or "").strip():
        patch["name"] = req.name.strip()[:NAME_MAX]
    if req.rules is not None:
        patch["rules"] = _clean_rules(req.rules)
    if req.description is not None:
        patch["description"] = req.description.strip()[:200]
    _db.saved_segments.update_one({"id": segment_id}, {"$set": patch})
    fresh = _db.saved_segments.find_one({"id": segment_id}, {"_id": 0})
    people = list(_db.customers.find(S.customer_filter(S.resolve(token_data, request)), {"_id": 0}))
    return {**fresh, "count": len(evaluate(tid, _rules_of(fresh), people))}


@router.delete("/api/owner/segmentation/segments/{segment_id}")
def remove(segment_id: str,
           token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    doc = _db.saved_segments.find_one({"id": segment_id, "tenant_id": token_data.tenant_id})
    if doc and not _owned(doc, token_data):
        raise HTTPException(status_code=403, detail="Seul son auteur (ou le propriétaire) peut le supprimer.")
    res = _db.saved_segments.delete_one({"id": segment_id, "tenant_id": token_data.tenant_id})
    if not getattr(res, "deleted_count", 0):
        raise HTTPException(status_code=404, detail="Segment introuvable")
    return {"deleted": True}


@router.get("/api/owner/segmentation/segments/{segment_id}/clients")
def members(segment_id: str, request: Request = None,
            token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """Who is in it, right now — for "Voir" and for handing to a campaign."""
    tid = token_data.tenant_id
    at = _now()
    if segment_id.startswith("model:"):
        model = next((m for m in _models(tid) if m["key"] == segment_id.split(":", 1)[1]), None)
        if not model:
            raise HTTPException(status_code=404, detail="Segment introuvable")
        name, rules = model["name"], _clean_rules(model["rules"])
    else:
        doc = _db.saved_segments.find_one({"id": segment_id, "tenant_id": tid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=404, detail="Segment introuvable")
        name, rules = doc.get("name") or "Segment", _rules_of(doc)
        _db.saved_segments.update_one({"id": segment_id}, {"$set": {"last_used_at": at}})

    # Only the clients of the establishments the caller may see.
    people = list(_db.customers.find(S.customer_filter(S.resolve(token_data, request)), {"_id": 0}))
    matched = evaluate(tid, rules, people, at=at)
    return {
        "id": segment_id, "name": name, "summary": describe(rules),
        "count": len(matched),
        "ids": [c["id"] for c in matched],
        "clients": [{"id": c["id"], "name": c.get("name") or "Client",
                     "tier": (c.get("tier") or "bronze").lower(),
                     "visits": int(_num(c.get("visits"))),
                     "spend": _money(_num(c.get("total_amount_paid"))),
                     "last_visit": (_aware(c.get("last_visit_date")) or None)
                     and _aware(c.get("last_visit_date")).isoformat()}
                    for c in sorted(matched, key=lambda c: -_num(c.get("total_amount_paid")))[:200]],
    }
