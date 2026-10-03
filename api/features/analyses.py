"""
Analyses — eight tabs, one window of data.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/analyses?tab=...&days=...   → one tab's panels
    GET /api/owner/analyses/export             → the overview as CSV

THE TABS (six on screen)
    vue          Vue d'ensemble   the headline strip and the panels beneath it
    campagnes    Campagnes        every campaign, and what it brought back
    fidelisation Fidélisation     retention, the tier ladder, the card cycle
    avis         Avis clients     ratings, their trend, what they talk about
    moments      Moments de visite  when people come — drawn in the Vue d'ensemble, no tab
    produits     Produits         what sells, and what it brings in
    acquisition  Acquisition      where new clients come from, and what they cost
    comportement Comportement     basket, lifetime — drawn in the Vue d'ensemble, no tab

    A tab is asked for one at a time. They share the same window and the same
    reader, but the page only ever pays for the one on screen.

NOTHING IS PAINTED IN
    Every panel counts real rows. Where a shop has nothing to show — no reviews,
    no catalogue, no campaigns — the panel says so instead of drawing a
    plausible chart. Two panels carry their own caveat where the figure could be
    read as more than it is; see `revenue_attributed` and `retention`.
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth import require_role, TokenData
from features import store_scope as S
from features import period as P, fidclic_impact as FI

# Analyses are read by the owner, administrateurs and managers — each on the
# establishments it may see (features/store_scope.py).
READERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["analyses"])
_db = None

LOYAL_VISITS = 5
INACTIVE_DAYS = 30
NEW_DAYS = 30
ATTRIBUTION_DAYS = 15

HOURS = [(8, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 20)]
# Whole day names: the browser's translator turned the short ones into
# nonsense (« Mer » → Sea, « Jeu » → Game, « Mar » → March — user, 2026-10-03).
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]

# « Moments de visite » and « Comportement » live in the Vue d'ensemble now
# (user, 2026-10-02): their builders stay, their tabs do not.
TABS = [
    {"key": "vue",          "label": "Vue d'ensemble"},
    {"key": "campagnes",    "label": "Campagnes"},
    {"key": "fidelisation", "label": "Fidélisation"},
    {"key": "avis",         "label": "Avis clients"},
    {"key": "produits",     "label": "Produits"},
    {"key": "acquisition",  "label": "Acquisition"},
]

SOURCE_LABELS = {
    "qr_store": "Passage en magasin", "instagram": "Réseaux sociaux",
    "facebook": "Réseaux sociaux", "tiktok": "Réseaux sociaux",
    "website": "Site web", "google": "Google", "referral": "Parrainage",
    "import": "Import de fichier",
}
TIER_LABELS = {"bronze": "Bronze", "silver": "Argent", "gold": "Or", "vip": "VIP"}


def init(db):
    global _db
    _db = db
    FI.init(db)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            p = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _window(days: int) -> Tuple[datetime, datetime]:
    return P.window(days, _now())


def _delta(now_value: float, was_value: float) -> Optional[int]:
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


def _money(n: Any) -> float:
    return round(float(n or 0), 2)


def _pct(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


def _days(value: Any, fallback: int = 30) -> int:
    """FastAPI hands this an int; anything else calling in — a test, a report,
    the cron — may hand over the Query default object instead. Coerce rather
    than fail on a page that is only ever read."""
    return P.clamp_days(value, fallback)


class Reader:
    """One trip to the database per request, shared by whichever tab asked."""

    def __init__(self, tid: str, days: int, scope: Optional["S.Scope"] = None):
        days = _days(days)
        self.tid, self.days, self.at = tid, days, _now()
        self.scope = scope
        self.mine = S.customer_ids(scope) if scope else None
        self.start, self.end = _window(days)
        span = self.end - self.start
        self.prev_end = self.start - timedelta(microseconds=1)
        self.prev_start = self.prev_end - span

    def visits(self, start=None, end=None) -> List[Dict[str, Any]]:
        return list(_db.visits.find(
            {"tenant_id": self.tid,
             "visit_time": {"$gte": start or self.start, "$lte": end or self.end},
             **(S.visit_filter(self.scope) if self.scope else {})},
            {"_id": 0, "customer_id": 1, "amount_paid": 1, "visit_time": 1, "items": 1}))

    def customers(self) -> List[Dict[str, Any]]:
        from features import clients_page as CP
        # The Clients page's columns too: the shop's Règles clients may read any of them.
        return list(_db.customers.find(
            S.customer_filter(self.scope) if self.scope else {"tenant_id": self.tid},
            {**CP.FIELDS, "acquisition_source": 1, "visits_at_last_redemption": 1}))

    def rules(self):
        from features import customer_rules as R
        return R.load(self.tid)

    def campaigns(self) -> List[Dict[str, Any]]:
        rows = list(_db.campaigns.find(
            {"tenant_id": self.tid, "sent_at": {"$gte": self.start, "$lte": self.end}},
            {"_id": 0, "id": 1, "name": 1, "status": 1, "sent_at": 1, "recipient_ids": 1,
             "opens": 1, "clicks": 1, "attributed_visit_customer_ids": 1}))
        if self.mine is None:
            return rows
        # A campaign counts for the clients of these establishments only.
        out = []
        for c in rows:
            ids = [i for i in c.get("recipient_ids") or [] if i in self.mine]
            if ids:
                out.append({**c, "recipient_ids": ids,
                            "attributed_visit_customer_ids": [i for i in c.get("attributed_visit_customer_ids") or []
                                                              if i in self.mine]})
        return out

    def reviews(self) -> List[Dict[str, Any]]:
        try:
            q: Dict[str, Any] = {"tenant_id": self.tid}
            if self.mine is not None:
                q["customer_id"] = {"$in": list(self.mine)}
            return list(_db.reviews.find(
                q, {"_id": 0, "rating": 1, "text": 1, "topics": 1,
                    "sentiment": 1, "created_at": 1}))
        except Exception:
            return []


def _revenue(rows) -> float:
    return sum(float(v.get("amount_paid") or 0) for v in rows)


def _empty(label: str) -> Dict[str, Any]:
    return {"empty": True, "message": label}


# ---------------------------------------------------------------------------
# the tabs
# ---------------------------------------------------------------------------
def _tab_vue(r: Reader) -> Dict[str, Any]:
    from features import clients_page as CP
    rows, prev = r.visits(), r.visits(r.prev_start, r.prev_end)
    people, rules = r.customers(), r.rules()
    revenue, prev_revenue = _revenue(rows), _revenue(prev)
    # « Clients fidélisés » / « Clients inactifs »: the Clients page's own
    # (the shop's Règles clients) — the same figures as the Tableau de bord.
    loyal = sum(1 for c in people if CP.is_loyal(c, r.at, rules))
    inactive = sum(1 for c in people if CP.is_inactive(c, r.at, rules))
    new_in_window = sum(1 for c in people
                        if r.start <= (_aware(c.get("created_at")) or r.at) <= r.end)
    prev_new = sum(1 for c in people
                   if r.prev_start <= (_aware(c.get("created_at")) or r.at) <= r.prev_end)

    # CA FidClic: the visits a FidClic feature brought in (features/fidclic_impact.py).
    imp, prev_imp = FI.impact(r.tid, rows), FI.impact(r.tid, prev)
    src, prev_src = imp["sources"], prev_imp["sources"]
    referral, prev_referral = src["parrainage"]["revenue"], prev_src["parrainage"]["revenue"]
    campaign_visits = src["campagnes"]["visits"] + src["automatisations"]["visits"]
    prev_campaign_visits = prev_src["campagnes"]["visits"] + prev_src["automatisations"]["visits"]

    # Money first, then activity, then the clients (user, 2026-10-02).
    strip = [
        {"key": "revenue", "label": "Chiffre d'affaires", "unit": "€", "value": _money(revenue),
         "icon": "chart", "delta_pct": _delta(revenue, prev_revenue), "row": 1},
        {"key": "fidclic", "label": "CA FidClic", "unit": "€", "value": imp["revenue"],
         "icon": "sparkles", "delta_pct": _delta(imp["revenue"], prev_imp["revenue"]),
         "highlight": True, "hint": "Clients revenus grâce à FidClic", "anchor": "impact", "row": 1},
        {"key": "referral", "label": "CA Parrainage", "unit": "€", "value": _money(referral),
         "icon": "gift", "delta_pct": _delta(referral, prev_referral),
         "hint": "Clients venus par parrainage", "anchor": "impact", "row": 1},
        {"key": "basket", "label": "Panier moyen", "unit": "€",
         "value": _money(revenue / len(rows)) if rows else 0, "icon": "bag",
         "delta_pct": _delta(revenue / len(rows) if rows else 0,
                             prev_revenue / len(prev) if prev else 0), "row": 1},
        # Opens « Visites par jour de la semaine », highlighted (user, 2026-10-03).
        {"key": "visits", "label": "Visites total", "value": len(rows), "icon": "activity",
         "delta_pct": _delta(len(rows), len(prev)), "anchor": "weekdays", "row": 2},
        {"key": "campaign_visits", "label": "Visites avec campagnes", "value": campaign_visits,
         "icon": "send", "delta_pct": _delta(campaign_visits, prev_campaign_visits),
         "hint": f"Venus dans les {FI.WINDOW_DAYS} jours suivant une campagne", "tab": "campagnes", "row": 2},
        {"key": "clients", "label": "Clients totaux", "value": len(people), "icon": "users",
         "delta_pct": _delta(len(people), len(people) - new_in_window),
         "to": "/dashboard/customers", "row": 2},
        {"key": "loyal", "label": "Clients fidélisés", "value": loyal, "icon": "crown",
         "delta_pct": None, "to": "/dashboard/customers?segment=loyal", "row": 2},
        {"key": "inactive", "label": "Clients inactifs", "value": inactive, "icon": "alert",
         "delta_pct": None, "lower_is_better": True,
         "to": "/dashboard/customers?segment=inactive", "row": 2},
    ]
    # The clients' whole history (« Comportement » before, user 2026-10-02).
    life = _lifetime(people)
    period_visits = round(len(rows) / len(people), 1) if people else 0.0
    strip += [
        {"key": "ltv", "label": "LTV moyenne", "unit": "€", "value": life["ltv"], "icon": "chart",
         "delta_pct": None, "hint": "Dépense moyenne d'un client depuis son inscription",
         "to": "/dashboard/customers?sort=spend", "row": 3},
        {"key": "ltv_total", "label": "LTV totale", "unit": "€", "value": life["ltv_total"],
         "icon": "bag", "delta_pct": None, "hint": "Dépense de tous vos clients depuis leur inscription",
         "to": "/dashboard/customers?sort=spend", "row": 3},
        {"key": "life", "label": "Durée moyenne", "unit": " mois", "value": life["avg_life"],
         "icon": "activity", "delta_pct": None,
         "hint": "De l'inscription à la dernière visite", "row": 3},
        {"key": "avg_visits", "label": "Visites par client", "value": life["avg_visits"],
         "icon": "repeat", "delta_pct": None,
         "hint": f"Depuis l'inscription · {str(period_visits).replace('.', ',')} sur la période",
         "to": "/dashboard/customers?sort=visits", "row": 3},
    ]
    sources = [{"key": k, "label": l, "tone": t, "revenue": src[k]["revenue"], "visits": src[k]["visits"],
                "pct": _pct(src[k]["revenue"], imp["revenue"]) if imp["revenue"] else 0}
               for k, l, t in FI.SOURCES]
    impact = {
        "revenue": imp["revenue"], "visits": imp["visits"],
        "delta_pct": _delta(imp["revenue"], prev_imp["revenue"]),
        "share_pct": round(imp["revenue"] / revenue * 100) if revenue else 0,
        "revenue_total": _money(revenue),
        "sources": sources, "window_days": FI.WINDOW_DAYS,
        "note": (f"Compté : les visites dans les {FI.WINDOW_DAYS} jours suivant une campagne, "
                 "une notification de géolocalisation, une offre ou une automatisation, et toutes "
                 "les visites des clients venus par parrainage. Un simple passage en caisse "
                 "n'est pas compté."),
    }
    return {
        "strip": strip,
        "impact": impact,
        "revenue_series": _series(rows, r, money=True),
        "new_series": _new_series(people, r),
        "new_total": new_in_window, "new_delta": _delta(new_in_window, prev_new),
        "revenue_total": _money(revenue), "revenue_delta": _delta(revenue, prev_revenue),
        "hours": _hours_grid(rows),
        "moments": _moments(rows),
        "products": _top_products(rows),
        "status_mix": CP.status_mix(people, r.at, rules),
        "avg_visits": {"lifetime": life["avg_visits"], "period": period_visits},
        "basket_bands": _basket_bands(people),
    }


# One point per Paris day — or per hour for « Aujourd'hui » (features/period.py).
def _series(rows, r: Reader, money: bool = False) -> List[Dict[str, Any]]:
    slots = P.slots(r.start, r.end, r.days)
    per_day = {x["date"]: 0.0 for x in slots}
    for v in rows:
        t = _aware(v.get("visit_time"))
        key = P.key_of(t, r.days) if t else None
        if key in per_day:
            per_day[key] += float(v.get("amount_paid") or 0) if money else 1
    return [{**x, "value": _money(per_day[x["date"]]) if money else int(per_day[x["date"]])}
            for x in slots]


def _new_series(people, r: Reader) -> List[Dict[str, Any]]:
    slots = P.slots(r.start, r.end, r.days)
    per_day = {x["date"]: 0 for x in slots}
    for c in people:
        t = _aware(c.get("created_at"))
        key = P.key_of(t, r.days) if t else None
        if key in per_day:
            per_day[key] += 1
    return [{**x, "value": per_day[x["date"]]} for x in slots]


def _hours_grid(rows) -> Dict[str, Any]:
    grid = [[0 for _ in HOURS] for _ in WEEKDAYS]
    outside = 0
    for v in rows:
        t = _aware(v.get("visit_time"))
        if not t:
            continue
        t = P.local(t)          # the hour on the shop's clock
        for hi, (lo, hi_h) in enumerate(HOURS):
            if lo <= t.hour < hi_h:
                grid[t.weekday()][hi] += 1
                break
        else:
            outside += 1
    return {"weekdays": WEEKDAYS, "slots": [f"{a}h-{b}h" for a, b in HOURS], "grid": grid,
            "peak": max((n for row in grid for n in row), default=0),
            "outside": outside, "covers": f"{HOURS[0][0]}h – {HOURS[-1][1]}h"}


def _top_products(rows, limit: int = 5) -> List[Dict[str, Any]]:
    tally: Dict[str, Dict[str, float]] = {}
    for v in rows:
        for item in (v.get("items") or []):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            acc = tally.setdefault(name, {"sales": 0, "revenue": 0.0})
            # The Scan page writes `qty`; older imports wrote `quantity`.
            qty = int(item.get("qty") or item.get("quantity") or 1)
            acc["sales"] += qty
            acc["revenue"] += float(item.get("price") or 0) * qty
    return [{"name": n, "sales": int(a["sales"]), "revenue": _money(a["revenue"])}
            for n, a in sorted(tally.items(), key=lambda kv: -kv[1]["sales"])[:limit]]


def _tab_campagnes(r: Reader) -> Dict[str, Any]:
    rows = r.campaigns()
    if not rows:
        return {"empty": True, "message": "Aucune campagne envoyée sur cette période.",
                "strip": [], "table": []}
    visits = {v["customer_id"]: float(v.get("amount_paid") or 0) for v in r.visits()}
    table = []
    for c in rows:
        reach = len(c.get("recipient_ids") or [])
        attributed = c.get("attributed_visit_customer_ids") or []
        revenue = sum(visits.get(cid, 0.0) for cid in attributed)
        table.append({
            "id": c.get("id"), "name": c.get("name") or "Campagne",
            "status": c.get("status") or "sent",
            "sent_at": (_aware(c.get("sent_at")) or r.at).isoformat(),
            "reach": reach, "opens": int(c.get("opens") or 0),
            "clicks": int(c.get("clicks") or 0), "sales": len(attributed),
            "revenue": _money(revenue),
            "conversion": round(len(attributed) / reach * 100, 1) if reach else 0.0,
        })
    table.sort(key=lambda t: -t["revenue"])
    totals = {k: sum(t[k] for t in table) for k in ("reach", "opens", "clicks", "sales")}
    return {
        "strip": [
            {"key": "sent", "label": "Campagnes envoyées", "value": len(table), "icon": "send"},
            {"key": "reach", "label": "Clients touchés", "value": totals["reach"], "icon": "users"},
            {"key": "clicks", "label": "Clics", "value": totals["clicks"], "icon": "click"},
            {"key": "sales", "label": "Ventes attribuées", "value": totals["sales"], "icon": "cart"},
        ],
        "table": table,
        "revenue_attributed": _money(sum(t["revenue"] for t in table)),
        "note": f"Une visite compte pour une campagne si elle a lieu dans les "
                f"{ATTRIBUTION_DAYS} jours suivant l'envoi.",
    }


def _tab_fidelisation(r: Reader) -> Dict[str, Any]:
    people = r.customers()
    if not people:
        return {"empty": True, "message": "Aucun client pour l'instant."}
    from features import clients_page as CP
    rules = r.rules()
    loyal = sum(1 for c in people if CP.is_loyal(c, r.at, rules))
    returning = sum(1 for c in people if int(c.get("visits") or 0) >= 2)
    tiers: Dict[str, int] = defaultdict(int)
    for c in people:
        tiers[(c.get("tier") or "bronze").lower()] += 1
    redeemed = 0
    try:
        redeemed = _db.rewards_redeemed.count_documents(
            {"tenant_id": r.tid, "redeemed_at": {"$gte": r.start, "$lte": r.end},
             **(S.visit_filter(r.scope) if r.scope else {})})
    except Exception:
        pass
    return {
        "strip": [
            {"key": "loyal", "label": "Clients fidélisés", "value": loyal, "icon": "crown"},
            {"key": "returning", "label": "Clients revenus", "value": returning, "icon": "repeat"},
            {"key": "retention", "label": "Taux de retour", "unit": "%",
             "value": _pct(returning, len(people)), "icon": "activity"},
            {"key": "rewards", "label": "Récompenses utilisées", "value": redeemed, "icon": "gift"},
        ],
        "retention_note": "Le taux de retour est la part de vos clients venus au moins deux "
                          "fois depuis leur inscription — pas une cohorte mensuelle.",
        "tiers": [{"key": k, "label": TIER_LABELS.get(k, k.title()),
                   "count": tiers.get(k, 0), "pct": _pct(tiers.get(k, 0), len(people))}
                  for k in ("bronze", "silver", "gold", "vip")],
        "status_mix": CP.status_mix(people, r.at, rules),
    }


def _tab_avis(r: Reader) -> Dict[str, Any]:
    rows = r.reviews()
    if not rows:
        return {"empty": True,
                "message": "Aucun avis pour l'instant. Activez la demande d'avis pour "
                           "commencer à en recevoir."}
    ratings = [float(x.get("rating") or 0) for x in rows if x.get("rating")]
    avg = round(sum(ratings) / len(ratings), 1) if ratings else 0.0
    in_window = [x for x in rows
                 if r.start <= (_aware(x.get("created_at")) or r.at) <= r.end]
    prev = [x for x in rows
            if r.prev_start <= (_aware(x.get("created_at")) or r.at) <= r.prev_end]
    prev_avg = (sum(float(x.get("rating") or 0) for x in prev) / len(prev)) if prev else 0
    # Ratings are on /10 in the data and shown out of 5 on the page, as the
    # design does — halved once, here, so the two cannot drift apart.
    buckets = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
    for x in ratings:
        star = max(1, min(5, round(x / 2)))
        buckets[star] += 1
    topics: Dict[str, int] = defaultdict(int)
    for x in rows:
        for t in (x.get("topics") or []):
            topics[str(t)] += 1
    return {
        "strip": [
            {"key": "avg", "label": "Note moyenne", "unit": "/5", "value": round(avg / 2, 1),
             "icon": "star", "delta_pct": _delta(avg, prev_avg)},
            {"key": "count", "label": "Avis reçus", "value": len(rows), "icon": "message"},
            {"key": "window", "label": "Sur la période", "value": len(in_window), "icon": "activity"},
        ],
        "histogram": [{"stars": s, "count": buckets[s], "pct": _pct(buckets[s], len(ratings))}
                      for s in (5, 4, 3, 2, 1)],
        "topics": [{"name": n, "count": c} for n, c in
                   sorted(topics.items(), key=lambda kv: -kv[1])[:6]],
        "recent": [{"rating": round(float(x.get("rating") or 0) / 2, 1),
                    "text": (x.get("text") or "")[:200],
                    "at": (_aware(x.get("created_at")) or r.at).isoformat()}
                   for x in sorted(rows, key=lambda x: _aware(x.get("created_at")) or r.at,
                                   reverse=True)[:5]],
    }


def _tab_moments(r: Reader) -> Dict[str, Any]:
    rows = r.visits()
    if not rows:
        return {"empty": True, "message": "Aucune visite sur cette période."}
    return _moments(rows)


def _moments(rows) -> Dict[str, Any]:
    """The hours grid, the weekdays, and the busiest of each — on the shop's clock."""
    per_weekday = [0] * 7
    for v in rows:
        t = _aware(v.get("visit_time"))
        if t:
            per_weekday[P.local(t).weekday()] += 1
    best_day = max(range(7), key=lambda i: per_weekday[i])
    grid = _hours_grid(rows)
    flat = [(d, h, grid["grid"][d][h]) for d in range(7) for h in range(len(HOURS))]
    best = max(flat, key=lambda t: t[2])
    return {
        "hours": grid,
        "weekday_bars": [{"label": WEEKDAYS[i], "value": per_weekday[i]} for i in range(7)],
        "best_day": {"label": WEEKDAYS[best_day], "visits": per_weekday[best_day]},
        "best_slot": {"label": f"{WEEKDAYS[best[0]]} {grid['slots'][best[1]]}",
                      "visits": best[2]} if best[2] else None,
        "total": len(rows),
    }


def _tab_produits(r: Reader) -> Dict[str, Any]:
    rows = r.visits()
    products = _top_products(rows, limit=20)
    if not products:
        return {"empty": True,
                "message": "Aucun produit enregistré. Les ventes apparaissent quand vos "
                           "scans enregistrent les articles."}
    total_sales = sum(p["sales"] for p in products)
    total_revenue = sum(p["revenue"] for p in products)
    return {
        "strip": [
            {"key": "refs", "label": "Références vendues", "value": len(products), "icon": "bag"},
            {"key": "units", "label": "Articles vendus", "value": total_sales, "icon": "cart"},
            {"key": "revenue", "label": "CA produits", "unit": "€",
             "value": _money(total_revenue), "icon": "chart"},
        ],
        "products": [{**p, "share": _pct(p["sales"], total_sales)} for p in products],
    }


def _place_of(cust) -> Tuple[str, str]:
    """The name a client's postal code stands for, and the code itself.

    The same resolution the map uses: a curated district first, then an
    arrondissement, then the commune, and only then the bare code. The client's
    own `city`, where an old signup left one, is the fallback rather than the
    lead — it says "Tours" where the code says "Tours Nord".
    """
    postal = str(cust.get("postal_code") or "").strip()
    if postal:
        try:
            from services import communes
            label = communes.label_for(postal)
            if label:
                return label, postal
        except Exception:
            pass        # a missing name must never cost the merchant the page
    city = str(cust.get("city") or "").strip()
    if city:
        return city, postal
    return (postal or "Non renseigné"), postal


def _by_place(people) -> Dict[str, int]:
    """Clients per commune, with two codes of one commune kept apart.

    "Tours" would otherwise silently merge 37000 and 37100. Where a name covers
    more than one code and no district name is known for certain, the code is
    appended — "Tours (37100)" — and only where it is needed, so a commune with
    a single code stays plain.
    """
    tally: Dict[Tuple[str, str], int] = defaultdict(int)
    seen: Dict[str, set] = defaultdict(set)
    for c in people:
        label, code = _place_of(c)
        tally[(label, code)] += 1
        seen[label].add(code)
    out: Dict[str, int] = defaultdict(int)
    for (label, code), n in tally.items():
        name = f"{label} ({code})" if code and len(seen[label]) > 1 else label
        out[name] += n
    return out


def _tab_acquisition(r: Reader) -> Dict[str, Any]:
    people = r.customers()
    in_window = [c for c in people
                 if r.start <= (_aware(c.get("created_at")) or r.at) <= r.end]
    if not people:
        return {"empty": True, "message": "Aucun client pour l'instant."}
    by_source: Dict[str, int] = defaultdict(int)
    for c in in_window or people:
        raw = (c.get("acquisition_source") or "").lower()
        by_source[SOURCE_LABELS.get(raw, "Autres" if raw else "Non renseigné")] += 1
    base = len(in_window or people)
    by_place = _by_place(people)
    return {
        "strip": [
            {"key": "new", "label": "Nouveaux clients", "value": len(in_window), "icon": "userplus"},
            {"key": "total", "label": "Clients au total", "value": len(people), "icon": "users"},
        ],
        "new_series": _new_series(people, r),
        "sources": [{"name": n, "count": c, "pct": _pct(c, base)}
                    for n, c in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "places": [{"name": n, "count": c, "pct": _pct(c, len(people))}
                   for n, c in sorted(by_place.items(), key=lambda kv: -kv[1])[:8]],
        "window_note": "Répartition des clients inscrits sur la période."
                       if in_window else "Aucune inscription sur la période : "
                                         "répartition de toute votre base.",
    }


def _lifetime(people) -> Dict[str, float]:
    """Each client's whole history, since they joined: what they spent, how
    often they came, and how long they have been coming."""
    if not people:
        return {"ltv": 0.0, "ltv_total": 0.0, "avg_visits": 0.0, "avg_life": 0.0}
    spend = [float(c.get("total_amount_paid") or 0) for c in people]
    visits = [int(c.get("visits") or 0) for c in people]
    lifespans = []
    for c in people:
        created, last = _aware(c.get("created_at")), _aware(c.get("last_visit_date"))
        if created and last and last > created:
            lifespans.append((last - created).days)
    return {"ltv": round(sum(spend) / len(people), 2), "ltv_total": _money(sum(spend)),
            "avg_visits": round(sum(visits) / len(people), 1),
            "avg_life": round(sum(lifespans) / len(lifespans) / 30.0, 1) if lifespans else 0.0}


def _tab_comportement(r: Reader) -> Dict[str, Any]:
    people = r.customers()
    if not people:
        return {"empty": True, "message": "Aucun client pour l'instant."}
    life = _lifetime(people)
    spend = [float(c.get("total_amount_paid") or 0) for c in people]
    ltv, avg_visits, avg_life = life["ltv"], life["avg_visits"], life["avg_life"]

    # Frequency buckets, as the design's "segmentation comportementale" shows.
    buckets = {"reguliers": 0, "occasionnels": 0, "nouveaux": 0, "inactifs": 0}
    for c in people:
        last, created = _aware(c.get("last_visit_date")), _aware(c.get("created_at"))
        if not last or (r.at - last).days >= INACTIVE_DAYS * 3:
            buckets["inactifs"] += 1
        elif created and (r.at - created).days <= NEW_DAYS:
            buckets["nouveaux"] += 1
        elif int(c.get("visits") or 0) >= LOYAL_VISITS:
            buckets["reguliers"] += 1
        else:
            buckets["occasionnels"] += 1
    return {
        "strip": [
            {"key": "clients", "label": "Clients", "value": len(people), "icon": "users"},
            {"key": "ltv", "label": "LTV moyenne", "unit": "€", "value": ltv, "icon": "chart"},
            {"key": "ltv_total", "label": "LTV totale", "unit": "€",
             "value": _money(sum(spend)), "icon": "bag"},
            {"key": "life", "label": "Durée moyenne", "unit": " mois", "value": avg_life,
             "icon": "activity"},
        ],
        "frequency": [
            {"key": "reguliers", "label": "Clients réguliers", "hint": "5 visites ou plus",
             "count": buckets["reguliers"], "tone": "green"},
            {"key": "occasionnels", "label": "Occasionnels", "hint": "1 à 4 visites",
             "count": buckets["occasionnels"], "tone": "amber"},
            {"key": "nouveaux", "label": "Nouveaux", "hint": f"< {NEW_DAYS} jours",
             "count": buckets["nouveaux"], "tone": "blue"},
            {"key": "inactifs", "label": "Inactifs", "hint": f"> {INACTIVE_DAYS * 3} jours",
             "count": buckets["inactifs"], "tone": "slate"},
        ],
        "avg_visits": avg_visits,
        "basket_bands": _basket_bands(people),
    }


def _basket_bands(people) -> List[Dict[str, Any]]:
    bands = [("< 10 €", 0, 10), ("10 – 25 €", 10, 25), ("25 – 50 €", 25, 50),
             ("50 – 100 €", 50, 100), ("100 € et +", 100, None)]
    out = []
    counted = [c for c in people if int(c.get("visits") or 0) > 0]
    for label, lo, hi in bands:
        n = 0
        for c in counted:
            avg = float(c.get("total_amount_paid") or 0) / max(1, int(c.get("visits") or 1))
            if avg >= lo and (hi is None or avg < hi):
                n += 1
        out.append({"label": label, "count": n, "pct": _pct(n, len(counted))})
    return out


BUILDERS = {
    "vue": _tab_vue, "campagnes": _tab_campagnes, "fidelisation": _tab_fidelisation,
    "avis": _tab_avis, "moments": _tab_moments, "produits": _tab_produits,
    "acquisition": _tab_acquisition, "comportement": _tab_comportement,
}


@router.get("/api/owner/analyses")
def analyses(request: Request = None, tab: str = "vue", days: int = Query(30, ge=1, le=P.MAX_DAYS),
             token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    key = tab if tab in BUILDERS else "vue"
    r = Reader(token_data.tenant_id, days, S.resolve(token_data, request))
    return {"tab": key, "days": r.days, "tabs": TABS,
            "from": r.start.isoformat(), "to": r.end.isoformat(),
            "data": BUILDERS[key](r), "scope": r.scope.describe()}


@router.get("/api/owner/analyses/export")
def export_analyses(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                    token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The overview's figures, day by day, as a CSV."""
    r = Reader(token_data.tenant_id, days, S.resolve(token_data, request))
    vue = _tab_vue(r)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Indicateur", "Valeur"])
    for s in vue["strip"]:
        w.writerow([s["label"], f"{s['value']}".replace(".", ",")])
    w.writerow([])
    w.writerow(["Date", "Chiffre d'affaires (€)", "Nouveaux clients"])
    news = {p["date"]: p["value"] for p in vue["new_series"]}
    for p in vue["revenue_series"]:
        w.writerow([p["date"], f"{p['value']:.2f}".replace(".", ","), news.get(p["date"], 0)])
    data = "﻿" + buf.getvalue()
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="fidclic-analyses-{r.at:%Y%m%d}.csv"'})
