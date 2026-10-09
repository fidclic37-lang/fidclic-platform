"""
Clients — the page's own API: four figures, eight quick segments, one table.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/clients/overview  → the four figures and the segment counts
    GET /api/owner/clients/list      → the table: filtered, sorted, paginated
    GET /api/owner/clients/export    → the same rows as CSV

WHY A SECOND ENDPOINT NEXT TO /api/owner/customers
    That one answers "give me the customers matching these filters" and hands
    back a plain array — no total, no page, no segment counts. Four pages and a
    dozen features read it, so it is left exactly as it is; this module adds
    what the Clients page needs on top and nothing else changes.

THE VOCABULARY, DEFINED ONCE
    The page shows a status and a segment against every client, and both have
    to mean the same thing in the figures, the chips and the rows. They are
    computed in one place — `classify` — from real columns:

      Statut    the shop's own Règles clients (features/customer_rules.py):
                dormant, bientôt perdu, the owner's rules, VIP, fidèle,
                régulier, nouveau, actif — first that holds wins. The
                figures "Clients fidèles" / "Clients inactifs" and their
                chips read the same rules ("Client fidèle", and the
                "Client actif" window).

      Segments  the eight chips, each a plain predicate over the same row.
                "Clients locaux" is the only one that needs more than the
                customer document: it asks services.communes / the catchment
                radius how far away they live.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth import require_role, TokenData
from features import customer_rules as R
from features import store_scope as S

router = APIRouter(tags=["clients"])
_db = None

LOYAL_VISITS = 5            # this many visits or more → fidèle
NEW_DAYS = 30               # joined inside this → nouveau
BIG_BASKET_FACTOR = 1.5     # average ticket this many times the shop's → gros panier
LOCAL_KM = 5.0              # inside the catchment's first ring → client local
MAX_PER_PAGE = 100


SEGMENTS: List[Dict[str, str]] = [
    {"key": "all",       "label": "Tous les clients",     "icon": "users",  "tone": "blue"},
    {"key": "loyal",     "label": "Clients fidèles",      "icon": "crown",  "tone": "amber"},
    {"key": "inactive",  "label": "Clients inactifs",     "icon": "send",   "tone": "rose"},
    {"key": "new",       "label": "Nouveaux clients",     "icon": "userplus", "tone": "violet"},
    {"key": "big",       "label": "Gros paniers",         "icon": "bag",    "tone": "orange"},
    {"key": "local",     "label": "Clients locaux",       "icon": "pin",    "tone": "blue"},
    {"key": "birthday",  "label": "Anniversaires du mois", "icon": "gift",  "tone": "violet"},
    {"key": "vip",       "label": "VIP",                  "icon": "star",   "tone": "amber"},
]


def init(db):
    global _db
    _db = db
    try:
        _db.customers.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------
def status_of(cust: Dict[str, Any], at: datetime,
              rules: Optional[List[Dict[str, Any]]] = None) -> str:
    """The Statut column: the one kind the shop's Règles clients give this
    client. Losing a client is said before anything else — a client with forty
    visits who has not been in for three months is a problem, not a success."""
    return R.status_key(R.primary(cust, at, rules if rules is not None else R.defaults()))


def _status_meta(rules: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    return {s["key"]: s for s in R.statuses(rules)}


def is_loyal(cust: Dict[str, Any], at: datetime,
             rules: Optional[List[Dict[str, Any]]] = None) -> bool:
    """"Client fidèle" as the shop defined it; the old visit count only while
    that rule is switched off or deleted."""
    rule = R.rule(rules if rules is not None else R.defaults(), "fidele")
    if rule and rule.get("enabled", True):
        return R.matches(rule, cust, at)
    return int(cust.get("visits") or 0) >= LOYAL_VISITS


def last_contact(cust: Dict[str, Any]) -> Optional[datetime]:
    """The last time the client was with the shop: their last visit, or their
    sign-up when they haven't visited since — whichever is later."""
    dates = [d for d in (_aware(cust.get("last_visit_date")), _aware(cust.get("created_at")),
                         _aware(cust.get("join_date"))) if d]
    return max(dates) if dates else None


def is_inactive(cust: Dict[str, Any], at: datetime,
                rules: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Nothing for the whole "Client actif" window (30 days by default, the
    shop's Règles clients) since the last visit — or since the sign-up for a
    client who hasn't come yet. A client who signed up today is not inactive
    (user, 2026-10-04: it was, from the first second)."""
    days = R.active_days(rules if rules is not None else R.defaults())
    last = last_contact(cust)
    return not last or (at - last).total_seconds() / 86400.0 >= days + 1


# « Clients qui décrochent » (the bell, Insights' « Clients à risque », user
# 2026-10-03: « Habitués ka rhythm »): a regular — this many visits or more —
# whose silence is longer than AT_RISK_SILENT_DAYS AND more than twice their
# own usual gap. A monthly client silent for 45 days is not a weekly one.
AT_RISK_MIN_VISITS = 4
AT_RISK_SILENT_DAYS = 45
ONE_TIMER_DAYS = 30          # « 1 seule visite »: joined inside this, came once
TOP_SILENT_DAYS = 30         # « Meilleur client silencieux »


def is_at_risk(cust: Dict[str, Any], at: datetime) -> bool:
    visits = int(cust.get("visits") or 0)
    first, last = _aware(cust.get("created_at")), _aware(cust.get("last_visit_date"))
    if visits < AT_RISK_MIN_VISITS or not first or not last or last <= first:
        return False
    gap = (last - first).days / max(1, visits - 1)
    silent = (at - last).days
    return silent > AT_RISK_SILENT_DAYS and silent > 2 * gap


def is_one_timer(cust: Dict[str, Any], at: datetime) -> bool:
    created = _aware(cust.get("created_at"))
    return int(cust.get("visits") or 0) == 1 and bool(created) and (at - created).days <= ONE_TIMER_DAYS


def top_silent(rows: List[Dict[str, Any]], at: datetime) -> Optional[Dict[str, Any]]:
    """The client who has spent the most, when they have not been back for
    TOP_SILENT_DAYS. None when the best client is still coming."""
    paying = [c for c in rows if float(c.get("total_amount_paid") or 0) > 0]
    if not paying:
        return None
    top = max(paying, key=lambda c: float(c.get("total_amount_paid") or 0))
    last = _aware(top.get("last_visit_date"))
    return top if last and (at - last).days >= TOP_SILENT_DAYS else None


def _avg_ticket(cust: Dict[str, Any]) -> float:
    visits = int(cust.get("visits") or 0)
    if visits <= 0:
        return 0.0
    return float(cust.get("total_amount_paid") or 0) / visits


def segment_of(cust: Dict[str, Any], at: datetime, shop_avg: float,
               local_ids: Optional[set] = None,
               rules: Optional[List[Dict[str, Any]]] = None) -> str:
    """The one chip a client is shown under in the table. Most specific first,
    so a VIP reads VIP rather than "fidèle like everybody else"."""
    if (cust.get("tier") or "").lower() == "vip":
        return "vip"
    created = _aware(cust.get("created_at"))
    if created and (at - created).days <= NEW_DAYS:
        return "new"
    if shop_avg and _avg_ticket(cust) >= shop_avg * BIG_BASKET_FACTOR:
        return "big"
    if is_loyal(cust, at, rules):
        return "loyal"
    if local_ids is not None and cust.get("id") in local_ids:
        return "local"
    return "active"


# The Tableau de bord's « Statut des clients » slices — one per client, in
# this order — open the Clients page on these (not shown as chips).
HOME_SEGMENTS = {"loyal_active": "Clients fidélisés (actifs)", "new_active": "Nouveaux clients (actifs)",
                 "occasional": "Clients occasionnels"}


# Segments a figure of the Tableau de bord — or an alert of the bell — opens,
# on every plan. « client:<id> » is one client (the bell's best client).
DRILL_DOWN = {"loyal", "inactive", "new", "loyal_active", "new_active", "occasional", "at_risk", "one_timers"}
ALERT_SEGMENTS = {"at_risk": "Clients qui décrochent", "one_timers": "Venus une seule fois"}


def drill_down(key: str) -> bool:
    return key in DRILL_DOWN or str(key).startswith("client:")


def home_bucket(cust: Dict[str, Any], at: datetime, rules: Optional[List[Dict[str, Any]]] = None) -> str:
    if is_inactive(cust, at, rules):
        return "inactive"
    if is_loyal(cust, at, rules):
        return "loyal"
    created = _aware(cust.get("created_at"))
    if created and (at - created).days <= NEW_DAYS:
        return "new"
    return "occasional"


def _matches_segment(key: str, cust: Dict[str, Any], at: datetime,
                     shop_avg: float, local_ids: set,
                     rules: Optional[List[Dict[str, Any]]] = None) -> bool:
    """A chip's own predicate. Deliberately NOT `segment_of(...) == key`: the
    chips overlap on purpose — a VIP is also a fidèle, and clicking "Clients
    fidèles" should show them."""
    if key == "all":
        return True
    if key == "loyal":
        return is_loyal(cust, at, rules)
    if key == "inactive":
        return is_inactive(cust, at, rules)
    if key == "new":
        created = _aware(cust.get("created_at"))
        return bool(created and (at - created).days <= NEW_DAYS)
    if key == "big":
        return bool(shop_avg) and _avg_ticket(cust) >= shop_avg * BIG_BASKET_FACTOR
    if key == "local":
        return cust.get("id") in local_ids
    if key == "birthday":
        return str(cust.get("birthday") or "")[:2] == at.strftime("%m")
    if key == "vip":
        return (cust.get("tier") or "").lower() == "vip"
    if key == "at_risk":
        return is_at_risk(cust, at)
    if key == "one_timers":
        return is_one_timer(cust, at)
    if key.startswith("client:"):
        return cust.get("id") == key[7:]
    if key in HOME_SEGMENTS:
        return home_bucket(cust, at, rules) == {"loyal_active": "loyal", "new_active": "new", "occasional": "occasional"}[key]
    return True


# ---------------------------------------------------------------------------
# the shop's own numbers, needed before any client can be classified
# ---------------------------------------------------------------------------
def _shop_average_ticket(rows: List[Dict[str, Any]]) -> float:
    spend = sum(float(c.get("total_amount_paid") or 0) for c in rows)
    visits = sum(int(c.get("visits") or 0) for c in rows)
    return (spend / visits) if visits else 0.0


def _local_ids(tid: str, rows: List[Dict[str, Any]]) -> set:
    """Who lives inside the first catchment ring. Reuses the Géolocalisation
    machinery rather than inventing a second idea of "near"."""
    try:
        from features import geolocation as geo
    except Exception:
        return set()
    tenant = (_db.tenants.find_one({"id": tid}) or {})
    lat, lng, _src = geo._shop_position(tenant)
    if lat is None:
        return set()
    near = set()
    for c in rows:
        clat, clng, _how = geo._client_position(c)
        if clat is None:
            continue
        if geo._haversine_km(lat, lng, clat, clng) <= LOCAL_KM:
            near.add(c["id"])
    return near


def status_mix(customers, at: datetime, rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """« Statut des clients »: one slice per client, `home_bucket`'s order —
    inactif, then fidèle, then nouveau, else occasionnel. Each slice opens the
    same people on the Clients page (segments *_active / occasional / inactive).
    The Tableau de bord and Analyses draw the same donut from this."""
    buckets = {"loyal": 0, "new": 0, "occasional": 0, "inactive": 0}
    for c in customers:
        buckets[home_bucket(c, at, rules)] += 1
    total = sum(buckets.values())
    whole = total or 1
    labels = [("loyal", "Clients fidélisés (actifs)", "green", "loyal_active"),
              ("new", "Nouveaux clients (actifs)", "blue", "new_active"),
              ("occasional", "Clients occasionnels", "amber", "occasional"),
              ("inactive", "Clients inactifs", "slate", "inactive")]
    return {"total": total,
            "slices": [{"key": k, "label": l, "tone": t, "segment": seg, "count": buckets[k],
                        "pct": round(buckets[k] / whole * 100)} for k, l, t, seg in labels]}


FIELDS = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "tier": 1, "visits": 1,
          "points": 1, "total_amount_paid": 1, "created_at": 1, "last_visit_date": 1,
          "birthday": 1, "postal_code": 1, "city": 1, "barcode_id": 1,
          "latitude": 1, "longitude": 1, "is_student": 1, "acquisition_source": 1}


# Owner, administrateur and manager read the Clients page; each sees the
# clients of the establishments it may see (features/store_scope.py).
READERS = ["business_owner", "administrateur", "manager"]


def _load(tid: str, scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    return list(_db.customers.find(S.customer_filter(scope) if scope else {"tenant_id": tid}, FIELDS))


def _scope(token_data: TokenData, request: Optional[Request]) -> "S.Scope":
    return S.resolve(token_data, request)


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("-", " ").split() if p]
    if not parts:
        return "?"
    return (parts[0][:2] if len(parts) == 1 else parts[0][0] + parts[-1][0]).upper()


def _public(cust: Dict[str, Any], at: datetime, shop_avg: float, local_ids: set,
            rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    rules = rules if rules is not None else R.defaults()
    st = status_of(cust, at, rules)
    meta = _status_meta(rules).get(st) or {"label": st, "tone": "blue"}
    seg = segment_of(cust, at, shop_avg, local_ids, rules)
    last = _aware(cust.get("last_visit_date"))
    joined = _aware(cust.get("created_at"))
    return {
        "id": cust["id"], "name": cust.get("name") or "Client",
        "initials": _initials(cust.get("name") or ""),
        "email": cust.get("email") or "", "phone": cust.get("phone") or "",
        "barcode_id": cust.get("barcode_id"),
        "tier": (cust.get("tier") or "bronze").lower(),
        "status": st, "status_label": meta["label"], "status_tone": meta["tone"],
        "segment": seg,
        "segment_label": next((s["label"] for s in SEGMENTS if s["key"] == seg), "Actif"),
        "visits": int(cust.get("visits") or 0),
        "spent": round(float(cust.get("total_amount_paid") or 0), 2),
        "last_visit": last.isoformat() if last else None,
        "joined": joined.isoformat() if joined else None,
        "city": cust.get("city") or "",
        "source": _source_key(cust), "source_label": _source_label(cust),
    }


def _source_key(cust: Dict[str, Any]) -> str:
    from services import sources as SRC
    return SRC.key_of(cust)


def _source_label(cust: Dict[str, Any]) -> str:
    from services import sources as SRC
    return SRC.label(SRC.key_of(cust))


SORTS: Dict[str, Tuple[Callable[[Dict[str, Any]], Any], bool]] = {
    "recent":  (lambda c: _aware(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), True),
    "oldest":  (lambda c: _aware(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), False),
    "name":    (lambda c: (c.get("name") or "").lower(), False),
    "spend":   (lambda c: float(c.get("total_amount_paid") or 0), True),
    "visits":  (lambda c: int(c.get("visits") or 0), True),
    "last":    (lambda c: _aware(c.get("last_visit_date")) or datetime.min.replace(tzinfo=timezone.utc), True),
}
SORT_LABELS = [
    {"key": "recent", "label": "Date d'inscription (plus récent)"},
    {"key": "oldest", "label": "Date d'inscription (plus ancien)"},
    {"key": "name",   "label": "Nom (A → Z)"},
    {"key": "spend",  "label": "Total dépensé (plus élevé)"},
    {"key": "visits", "label": "Visites (plus nombreuses)"},
    {"key": "last",   "label": "Dernière visite (plus récente)"},
]

SPEND_BANDS = {
    "lt50":   (0.0, 50.0), "50_150": (50.0, 150.0),
    "150_500": (150.0, 500.0), "gt500": (500.0, None),
}
JOINED_BANDS = {"30d": 30, "90d": 90, "1y": 365}


# « Plus de filtres » (user, 2026-10-08: the old Clients page's filters,
# back in the new design): palier, visits, total spent, average basket,
# postal code, notifications.
EXTRA_KEYS = ("tier", "visits_min", "visits_max", "spent_min", "spent_max", "basket_min", "postal", "notif")


def _num_or_none(v: Any) -> Optional[float]:
    try:
        s = str(v).strip().replace(",", ".")
        return float(s) if s != "" else None
    except (TypeError, ValueError):
        return None


def _extra(tier: str = "", visits_min: str = "", visits_max: str = "", spent_min: str = "", spent_max: str = "",
           basket_min: str = "", postal: str = "", notif: str = "") -> Dict[str, Any]:
    return {"tier": (tier or "").strip().lower(), "visits_min": _num_or_none(visits_min),
            "visits_max": _num_or_none(visits_max), "spent_min": _num_or_none(spent_min),
            "spent_max": _num_or_none(spent_max), "basket_min": _num_or_none(basket_min),
            "postal": "".join(ch for ch in (postal or "") if ch.isdigit())[:5], "notif": (notif or "").strip()}


def _extra_if_allowed(tid: str, *args) -> Optional[Dict[str, Any]]:
    """« Plus de filtres » is CRM avancé, like the other refinements."""
    try:
        from features import plan_limits
        if not plan_limits.allows_tenant(tid, "crm_advanced"):
            return None
    except Exception:
        pass
    x = _extra(*args)
    if not any(v not in (None, "") for v in x.values()):
        return None
    if x.get("notif") in ("oui", "non"):
        x["_subscribed"] = _subscribed_ids(tid)
    return x


def _subscribed_ids(tid: str) -> set:
    try:
        return {s.get("customer_id") for s in _db.push_subscriptions.find({"tenant_id": tid}, {"_id": 0, "customer_id": 1})}
    except Exception:
        return set()


def _filtered(rows: List[Dict[str, Any]], at: datetime, shop_avg: float, local_ids: set,
              segment: str, status: str, spend: str, joined: str, search: str,
              rules: Optional[List[Dict[str, Any]]] = None, source: str = "",
              extra: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rules = rules if rules is not None else R.defaults()
    out = []
    x = extra or {}
    subscribed = x.get("_subscribed") if x.get("notif") in ("oui", "non") else None
    needle = (search or "").strip().lower()
    # « Source » (services/sources): the clients who came by one channel —
    # Analyses and the Tableau de bord open their bars here.
    from services import sources as SRC
    want_source = source if source in SRC.SOURCES or source == SRC.UNKNOWN else ""
    for c in rows:
        if want_source and SRC.key_of(c) != want_source:
            continue
        if segment and segment != "all" and not _matches_segment(segment, c, at, shop_avg, local_ids, rules):
            continue
        if status and status_of(c, at, rules) != status:
            continue
        if spend in SPEND_BANDS:
            low, high = SPEND_BANDS[spend]
            total = float(c.get("total_amount_paid") or 0)
            if total < low or (high is not None and total >= high):
                continue
        if joined in JOINED_BANDS:
            created = _aware(c.get("created_at"))
            if not created or (at - created).days > JOINED_BANDS[joined]:
                continue
        if needle:
            hay = f"{c.get('name') or ''} {c.get('email') or ''} {c.get('phone') or ''} {c.get('barcode_id') or ''}".lower()
            if needle not in hay:
                continue
        if x:
            visits = int(c.get("visits") or 0)
            spent = float(c.get("total_amount_paid") or 0)
            if x.get("tier") and (c.get("tier") or "bronze").lower() != x["tier"]:
                continue
            if x.get("visits_min") is not None and visits < x["visits_min"]:
                continue
            if x.get("visits_max") is not None and visits > x["visits_max"]:
                continue
            if x.get("spent_min") is not None and spent < x["spent_min"]:
                continue
            if x.get("spent_max") is not None and spent > x["spent_max"]:
                continue
            if x.get("basket_min") is not None and (not visits or spent / visits < x["basket_min"]):
                continue
            if x.get("postal") and not str(c.get("postal_code") or "").startswith(x["postal"]):
                continue
            if subscribed is not None and ((c.get("id") in subscribed) != (x["notif"] == "oui")):
                continue
        out.append(c)
    return out


def _delta(now_value: float, was_value: float) -> Optional[int]:
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
def _sources_of(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from services import sources as SRC
    counts: Dict[str, int] = {}
    for c in rows:
        k = SRC.key_of(c)
        counts[k] = counts.get(k, 0) + 1
    return SRC.ordered(counts)


@router.get("/api/owner/clients/overview")
def overview(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    at = _now()
    rows = _load(tid, _scope(token_data, request))
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)
    rules = R.load(tid)

    total = len(rows)
    loyal = sum(1 for c in rows if is_loyal(c, at, rules))
    inactive = sum(1 for c in rows if is_inactive(c, at, rules))
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # « Nouveaux clients » is the segment of the same name — joined in the last
    # NEW_DAYS days — so the card and the segment chip never disagree (the card
    # used to read the calendar month: 0 on the 1st while the segment said 17).
    new_recent = sum(1 for c in rows if _matches_segment("new", c, at, shop_avg, local, rules))
    # The NEW_DAYS before that, for the comparison.
    was = at - timedelta(days=NEW_DAYS + 1)
    prev_new_recent = sum(1 for c in rows
                          if (_aware(c.get("created_at")) or at) <= was
                          and _matches_segment("new", c, was, shop_avg, local, rules))

    # The month before, for the comparison the design puts under each figure.
    prev_end = month_start - timedelta(microseconds=1)
    prev_start = prev_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    before = [c for c in rows if (_aware(c.get("created_at")) or at) < month_start]
    prev_loyal = sum(1 for c in before if is_loyal(c, prev_end, rules))
    prev_inactive = sum(1 for c in before if is_inactive(c, prev_end, rules))

    return {
        "cards": [
            {"key": "total", "label": "Clients total", "icon": "users", "tone": "blue",
             "value": total, "delta_pct": _delta(total, len(before)), "note": "vs mois précédent"},
            {"key": "loyal", "label": "Clients fidèles", "icon": "crown", "tone": "amber",
             "value": loyal, "delta_pct": _delta(loyal, prev_loyal), "note": "vs mois précédent"},
            {"key": "inactive", "label": "Clients inactifs", "icon": "send", "tone": "rose",
             "value": inactive, "delta_pct": _delta(inactive, prev_inactive),
             "note": "vs mois précédent", "lower_is_better": True},
            {"key": "new", "label": "Nouveaux clients", "icon": "userplus", "tone": "violet",
             "value": new_recent, "delta_pct": _delta(new_recent, prev_new_recent),
             "note": f"{NEW_DAYS} derniers jours"},
        ],
        "segments": [{**s, "count": sum(1 for c in rows
                                        if _matches_segment(s["key"], c, at, shop_avg, local, rules))}
                     for s in SEGMENTS],
        "sorts": SORT_LABELS,
        # the filter « Source » — every channel this shop's clients came by
        "sources": _sources_of(rows),
        "home_segments": [{"key": k, "label": v} for k, v in HOME_SEGMENTS.items()],
        "statuses": R.statuses(rules),
        "shop_average_ticket": round(shop_avg, 2),
        "definitions": {
            "loyal_visits": LOYAL_VISITS, "inactive_days": R.active_days(rules),
            "new_days": NEW_DAYS, "big_basket_factor": BIG_BASKET_FACTOR, "local_km": LOCAL_KM,
        },
    }


@router.get("/api/owner/clients/ids")
def list_ids(
    segment: str = "all",
    status: str = "",
    spend: str = "",
    joined: str = "",
    search: str = "",
    source: str = "",
    tier: str = "", visits_min: str = "", visits_max: str = "", spent_min: str = "", spent_max: str = "",
    basket_min: str = "", postal: str = "", notif: str = "",
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """Every client the current filter matches — ids only, no page.

    The table is paginated; messaging is not. Without this the merchant would
    write to the ten people on screen and believe they had written to the
    hundred the filter found. Same filter code as /list, so the number here and
    the number above the table can never disagree.
    """
    tid = token_data.tenant_id
    at = _now()
    rows = _load(tid, _scope(token_data, request))
    rows = _filtered(rows, at, _shop_average_ticket(rows), _local_ids(tid, rows),
                     segment, status, spend, joined, search, R.load(tid), source=source,
                     extra=_extra_if_allowed(tid, tier, visits_min, visits_max, spent_min, spent_max, basket_min, postal, notif))
    return {"ids": [c["id"] for c in rows], "total": len(rows)}


@router.get("/api/owner/clients/list")
def list_page(
    segment: str = "all",
    status: str = "",
    spend: str = "",
    joined: str = "",
    search: str = "",
    source: str = "",
    tier: str = "", visits_min: str = "", visits_max: str = "", spent_min: str = "", spent_max: str = "",
    basket_min: str = "", postal: str = "", notif: str = "",
    sort: str = "recent",
    page: int = 1,
    per_page: int = 10,
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    # « CRM avancé » not in the plan: the simple list — search, statut, sort.
    # The Tableau de bord's own figures still open their clients (the list
    # behind a number every plan shows is not segmentation).
    from features import plan_limits
    if not plan_limits.allows_tenant(token_data.tenant_id, "crm_advanced"):
        segment = segment if drill_down(segment) else "all"
        spend, joined = "", ""
    tid = token_data.tenant_id
    at = _now()
    per_page = max(1, min(MAX_PER_PAGE, int(per_page or 10)))
    page = max(1, int(page or 1))

    rows = _load(tid, _scope(token_data, request))
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)
    rules = R.load(tid)
    rows = _filtered(rows, at, shop_avg, local, segment, status, spend, joined, search, rules, source=source,
                     extra=_extra_if_allowed(tid, tier, visits_min, visits_max, spent_min, spent_max, basket_min, postal, notif))

    key, reverse = SORTS.get(sort, SORTS["recent"])
    rows.sort(key=key, reverse=reverse)

    total = len(rows)
    window = rows[(page - 1) * per_page: page * per_page]
    return {
        "rows": [_public(c, at, shop_avg, local, rules) for c in window],
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, math.ceil(total / per_page)),
    }


def _paris_day(iso: Optional[str]) -> str:
    """The day in France, as Excel reads it (QA F13: the UTC date was cut off,
    so a 00:30 visit showed the day before)."""
    if not iso:
        return ""
    try:
        from zoneinfo import ZoneInfo
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d.astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)[:10]


@router.get("/api/owner/clients/export")
def export_clients(
    segment: str = "all", status: str = "", spend: str = "", joined: str = "",
    search: str = "", sort: str = "recent", source: str = "",
    tier: str = "", visits_min: str = "", visits_max: str = "", spent_min: str = "", spent_max: str = "",
    basket_min: str = "", postal: str = "", notif: str = "",
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """Every client the filters select — the table without its page limit."""
    tid = token_data.tenant_id
    at = _now()
    rows = _load(tid, _scope(token_data, request))
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)
    rules = R.load(tid)
    rows = _filtered(rows, at, shop_avg, local, segment, status, spend, joined, search, rules, source=source,
                     extra=_extra_if_allowed(tid, tier, visits_min, visits_max, spent_min, spent_max, basket_min, postal, notif))
    key, reverse = SORTS.get(sort, SORTS["recent"])
    rows.sort(key=key, reverse=reverse)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Client", "Email", "Téléphone", "Statut", "Segment", "Source", "Visites",
                "Total dépensé (€)", "Dernière visite", "Inscription", "Ville"])
    for c in rows:
        p = _public(c, at, shop_avg, local, rules)
        w.writerow([p["name"], p["email"], p["phone"], p["status_label"], p["segment_label"],
                    p["source_label"], p["visits"], f"{p['spent']:.2f}".replace(".", ","),
                    _paris_day(p["last_visit"]), _paris_day(p["joined"]), p["city"]])
    data = "﻿" + buf.getvalue()
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="fidclic-clients-{at:%Y%m%d}.csv"'})
