"""
Analyses — eight tabs, one window of data.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/analyses?tab=...&days=...   → one tab's panels
    GET /api/owner/analyses/export             → the overview as CSV

THE EIGHT TABS
    vue          Vue d'ensemble   the headline strip and the panels beneath it
    campagnes    Campagnes        every campaign, and what it brought back
    fidelisation Fidélisation     retention, the tier ladder, the card cycle
    avis         Avis clients     ratings, their trend, what they talk about
    moments      Moments de visite  when people come, by day and by hour
    produits     Produits         what sells, and what it brings in
    acquisition  Acquisition      where new clients come from, and what they cost
    comportement Comportement     frequency, basket, lifetime, RFM

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
WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

TABS = [
    {"key": "vue",          "label": "Vue d'ensemble"},
    {"key": "campagnes",    "label": "Campagnes"},
    {"key": "fidelisation", "label": "Fidélisation"},
    {"key": "avis",         "label": "Avis clients"},
    {"key": "moments",      "label": "Moments de visite"},
    {"key": "produits",     "label": "Produits"},
    {"key": "acquisition",  "label": "Acquisition"},
    {"key": "comportement", "label": "Comportement"},
]

SOURCE_LABELS = {
    "qr_store": "Passage en magasin", "instagram": "Réseaux sociaux",
    "facebook": "Réseaux sociaux", "tiktok": "Réseaux sociaux",
    "website": "Site web", "google": "Google", "referral": "Parrainage",
}
TIER_LABELS = {"bronze": "Bronze", "silver": "Argent", "gold": "Or", "vip": "VIP"}


def init(db):
    global _db
    _db = db


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
    end = _now()
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, end


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
    try:
        return max(1, min(365, int(value)))
    except (TypeError, ValueError):
        return fallback


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
        return list(_db.customers.find(
            S.customer_filter(self.scope) if self.scope else {"tenant_id": self.tid},
            {"_id": 0, "id": 1, "name": 1, "visits": 1, "points": 1, "tier": 1,
             "total_amount_paid": 1, "created_at": 1, "last_visit_date": 1,
             "acquisition_source": 1, "city": 1, "postal_code": 1,
             "visits_at_last_redemption": 1}))

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
    rows, prev = r.visits(), r.visits(r.prev_start, r.prev_end)
    people = r.customers()
    revenue, prev_revenue = _revenue(rows), _revenue(prev)
    loyal = sum(1 for c in people if int(c.get("visits") or 0) >= LOYAL_VISITS)
    inactive = sum(1 for c in people
                   if not _aware(c.get("last_visit_date"))
                   or (r.at - _aware(c.get("last_visit_date"))).days >= INACTIVE_DAYS)
    campaign_visitors = set()
    for c in r.campaigns():
        campaign_visitors.update(c.get("attributed_visit_customer_ids") or [])
    new_in_window = sum(1 for c in people
                        if r.start <= (_aware(c.get("created_at")) or r.at) <= r.end)
    prev_new = sum(1 for c in people
                   if r.prev_start <= (_aware(c.get("created_at")) or r.at) <= r.prev_end)

    strip = [
        {"key": "clients", "label": "Clients totaux", "value": len(people), "icon": "users",
         "delta_pct": _delta(len(people), len(people) - new_in_window)},
        {"key": "visits", "label": "Visites total", "value": len(rows), "icon": "activity",
         "delta_pct": _delta(len(rows), len(prev))},
        {"key": "campaign_visits", "label": "Visites avec campagnes",
         "value": len(campaign_visitors), "icon": "send", "delta_pct": None},
        {"key": "loyal", "label": "Clients fidélisés", "value": loyal, "icon": "crown",
         "delta_pct": None},
        {"key": "inactive", "label": "Clients inactifs", "value": inactive, "icon": "alert",
         "delta_pct": None, "lower_is_better": True},
        {"key": "basket", "label": "Panier moyen", "unit": "€",
         "value": _money(revenue / len(rows)) if rows else 0, "icon": "bag",
         "delta_pct": _delta(revenue / len(rows) if rows else 0,
                             prev_revenue / len(prev) if prev else 0)},
        {"key": "revenue", "label": "Chiffre d'affaires", "unit": "€", "value": _money(revenue),
         "icon": "chart", "delta_pct": _delta(revenue, prev_revenue)},
    ]
    return {
        "strip": strip,
        "revenue_series": _series(rows, r, money=True),
        "new_series": _new_series(people, r),
        "new_total": new_in_window, "new_delta": _delta(new_in_window, prev_new),
        "revenue_total": _money(revenue), "revenue_delta": _delta(revenue, prev_revenue),
        "hours": _hours_grid(rows),
        "products": _top_products(rows),
        "status_mix": _status_mix(people, r.at),
    }


def _series(rows, r: Reader, money: bool = False) -> List[Dict[str, Any]]:
    per_day = {(r.start.date() + timedelta(days=i)).isoformat(): 0.0
               for i in range((r.end.date() - r.start.date()).days + 1)}
    for v in rows:
        t = _aware(v.get("visit_time"))
        key = t.date().isoformat() if t else None
        if key in per_day:
            per_day[key] += float(v.get("amount_paid") or 0) if money else 1
    return [{"date": d, "value": _money(per_day[d]) if money else int(per_day[d])}
            for d in sorted(per_day)]


def _new_series(people, r: Reader) -> List[Dict[str, Any]]:
    per_day = {(r.start.date() + timedelta(days=i)).isoformat(): 0
               for i in range((r.end.date() - r.start.date()).days + 1)}
    for c in people:
        t = _aware(c.get("created_at"))
        key = t.date().isoformat() if t else None
        if key in per_day:
            per_day[key] += 1
    return [{"date": d, "value": per_day[d]} for d in sorted(per_day)]


def _hours_grid(rows) -> Dict[str, Any]:
    grid = [[0 for _ in HOURS] for _ in WEEKDAYS]
    outside = 0
    for v in rows:
        t = _aware(v.get("visit_time"))
        if not t:
            continue
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


def _status_mix(people, at: datetime) -> Dict[str, Any]:
    b = {"loyal": 0, "new": 0, "occasional": 0, "inactive": 0}
    for c in people:
        last, created = _aware(c.get("last_visit_date")), _aware(c.get("created_at"))
        if not last or (at - last).days >= INACTIVE_DAYS:
            b["inactive"] += 1
        elif int(c.get("visits") or 0) >= LOYAL_VISITS:
            b["loyal"] += 1
        elif created and (at - created).days <= NEW_DAYS:
            b["new"] += 1
        else:
            b["occasional"] += 1
    total = sum(b.values())
    labels = [("loyal", "Clients fidélisés", "green"), ("new", "Nouveaux clients", "blue"),
              ("occasional", "Clients occasionnels", "amber"), ("inactive", "Clients inactifs", "slate")]
    return {"total": total,
            "slices": [{"key": k, "label": l, "tone": t, "count": b[k], "pct": _pct(b[k], total)}
                       for k, l, t in labels]}


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
    loyal = sum(1 for c in people if int(c.get("visits") or 0) >= LOYAL_VISITS)
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
        "status_mix": _status_mix(people, r.at),
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
    per_weekday = [0] * 7
    for v in rows:
        t = _aware(v.get("visit_time"))
        if t:
            per_weekday[t.weekday()] += 1
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


def _tab_comportement(r: Reader) -> Dict[str, Any]:
    people = r.customers()
    if not people:
        return {"empty": True, "message": "Aucun client pour l'instant."}
    spend = [float(c.get("total_amount_paid") or 0) for c in people]
    visits = [int(c.get("visits") or 0) for c in people]
    ltv = round(sum(spend) / len(people), 2)
    avg_visits = round(sum(visits) / len(people), 1)
    lifespans = []
    for c in people:
        created, last = _aware(c.get("created_at")), _aware(c.get("last_visit_date"))
        if created and last and last > created:
            lifespans.append((last - created).days)
    avg_life = round(sum(lifespans) / len(lifespans) / 30.0, 1) if lifespans else 0.0

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
def analyses(request: Request = None, tab: str = "vue", days: int = Query(30, ge=1, le=365),
             token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    key = tab if tab in BUILDERS else "vue"
    r = Reader(token_data.tenant_id, days, S.resolve(token_data, request))
    return {"tab": key, "days": r.days, "tabs": TABS,
            "from": r.start.isoformat(), "to": r.end.isoformat(),
            "data": BUILDERS[key](r), "scope": r.scope.describe()}


@router.get("/api/owner/analyses/export")
def export_analyses(request: Request = None, days: int = Query(30, ge=1, le=365),
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
