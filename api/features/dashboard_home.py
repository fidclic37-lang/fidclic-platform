"""
Tableau de bord — everything the home page shows, in one payload.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/home/overview     → the whole page
    GET /api/owner/home/goal         → the monthly revenue target
    PUT /api/owner/home/goal         → the merchant sets it (Paramètres)

WHY ONE PAYLOAD
    The page draws eleven panels off the same month of visits. Asking for it
    eleven times would read the same rows eleven times; this reads them once and
    hands back what each panel needs.

WHAT IS COUNTED, AND FROM WHERE
    Every figure comes from `visits`, `customers`, `campaigns` and
    `push_wallet_log` — the rows the rest of the platform already writes. There
    is no demo data: a shop that opened yesterday reads zero and the page says
    so rather than painting a plausible month.

    Two of them are worth spelling out because they could be read as more than
    they are:

    Impact FidClic  revenue from visits the platform can attribute to something
                    it did — a campaign the customer was sent inside the
                    attribution window, or a Push Wallet scenario they received.
                    It is a floor, not a claim about everything the programme
                    caused.
    Objectif        the merchant's own number, set in Paramètres. Until they set
                    one the card asks for it instead of inventing a target.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["dashboard"])
_db = None

ATTRIBUTION_DAYS = 15       # a visit this soon after a send is attributed to it
LOYAL_VISITS = 5
INACTIVE_DAYS = 30
NEW_DAYS = 30

HOURS = [(8, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 20)]
WEEKDAYS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


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


def _money(n: float) -> float:
    return round(float(n or 0), 2)


# ---------------------------------------------------------------------------
# the monthly goal
# ---------------------------------------------------------------------------
class Goal(BaseModel):
    monthly_revenue_goal: float = Field(0, ge=0, le=10_000_000)


@router.get("/api/owner/home/goal")
def get_goal(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    return {"monthly_revenue_goal": float(tenant.get("monthly_revenue_goal") or 0)}


@router.put("/api/owner/home/goal")
def set_goal(body: Goal, token_data: TokenData = Depends(require_role(["business_owner"]))):
    _db.tenants.update_one({"id": token_data.tenant_id},
                           {"$set": {"monthly_revenue_goal": float(body.monthly_revenue_goal)}})
    return {"monthly_revenue_goal": float(body.monthly_revenue_goal)}


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
def _visits(tid: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return list(_db.visits.find(
        {"tenant_id": tid, "visit_time": {"$gte": start, "$lte": end}},
        {"_id": 0, "customer_id": 1, "amount_paid": 1, "visit_time": 1, "items": 1}))


def _revenue(rows: List[Dict[str, Any]]) -> float:
    return sum(float(v.get("amount_paid") or 0) for v in rows)


def _attributed_ids(tid: str, start: datetime, end: datetime) -> set:
    """Customers the platform reached shortly before they came in — by campaign
    or by a Push Wallet scenario. Their visits are what "Impact FidClic" counts."""
    reached: set = set()
    since = start - timedelta(days=ATTRIBUTION_DAYS)
    try:
        for c in _db.campaigns.find(
                {"tenant_id": tid, "sent_at": {"$gte": since, "$lte": end}},
                {"_id": 0, "recipient_ids": 1}):
            reached.update(c.get("recipient_ids") or [])
    except Exception:
        pass
    try:
        reached.update(_db.push_wallet_log.distinct(
            "customer_id", {"tenant_id": tid, "sent_at": {"$gte": since, "$lte": end}}))
    except Exception:
        pass
    return reached


@router.get("/api/owner/home/overview")
def overview(days: int = Query(30, ge=1, le=365),
             token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    tid = token_data.tenant_id
    at = _now()
    start, end = _window(days)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    tenant = _db.tenants.find_one({"id": tid}) or {}
    rows = _visits(tid, start, end)
    prev_rows = _visits(tid, prev_start, prev_end)
    customers = list(_db.customers.find(
        {"tenant_id": tid},
        {"_id": 0, "id": 1, "name": 1, "visits": 1, "created_at": 1, "last_visit_date": 1}))

    revenue, prev_revenue = _revenue(rows), _revenue(prev_rows)
    total_clients = len(customers)
    prev_clients = sum(1 for c in customers if (_aware(c.get("created_at")) or at) < start)
    loyal = sum(1 for c in customers if int(c.get("visits") or 0) >= LOYAL_VISITS)
    prev_loyal = sum(1 for c in customers
                     if int(c.get("visits") or 0) >= LOYAL_VISITS
                     and (_aware(c.get("created_at")) or at) < start)
    basket = (revenue / len(rows)) if rows else 0.0
    prev_basket = (prev_revenue / len(prev_rows)) if prev_rows else 0.0

    # ---- the four figures --------------------------------------------------
    cards = [
        {"key": "revenue", "label": "Chiffre d'affaires", "icon": "chart", "tone": "blue",
         "value": _money(revenue), "unit": "€", "badge": "FidClic",
         "delta_pct": _delta(revenue, prev_revenue)},
        {"key": "clients", "label": "Clients totaux", "icon": "users", "tone": "green",
         "value": total_clients, "delta_pct": _delta(total_clients, prev_clients)},
        {"key": "loyal", "label": "Clients fidélisés", "icon": "crown", "tone": "amber",
         "value": loyal, "delta_pct": _delta(loyal, prev_loyal)},
        {"key": "basket", "label": "Panier moyen", "icon": "bag", "tone": "violet",
         "value": _money(basket), "unit": "€", "delta_pct": _delta(basket, prev_basket)},
    ]

    # ---- the month's goal ---------------------------------------------------
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_revenue = _revenue(_visits(tid, month_start, at))
    goal_amount = float(tenant.get("monthly_revenue_goal") or 0)
    goal = {
        "target": _money(goal_amount),
        "reached": _money(month_revenue),
        "remaining": _money(max(0.0, goal_amount - month_revenue)),
        "pct": round(min(100, month_revenue / goal_amount * 100)) if goal_amount else None,
        "is_set": goal_amount > 0,
    }

    # ---- impact --------------------------------------------------------------
    reached_ids = _attributed_ids(tid, start, end)
    impact_rows = [v for v in rows if v.get("customer_id") in reached_ids]
    prev_reached = _attributed_ids(tid, prev_start, prev_end)
    prev_impact = _revenue([v for v in prev_rows if v.get("customer_id") in prev_reached])
    impact_value = _revenue(impact_rows)
    impact = {
        "value": _money(impact_value), "delta_pct": _delta(impact_value, prev_impact),
        "note": "CA généré par vos campagnes et actions suivies",
        "window_days": ATTRIBUTION_DAYS,
    }

    # ---- the two charts --------------------------------------------------------
    per_day_rev = {(start.date() + timedelta(days=i)).isoformat(): 0.0
                   for i in range((end.date() - start.date()).days + 1)}
    for v in rows:
        t = _aware(v.get("visit_time"))
        if t and t.date().isoformat() in per_day_rev:
            per_day_rev[t.date().isoformat()] += float(v.get("amount_paid") or 0)
    revenue_series = [{"date": d, "value": _money(per_day_rev[d])} for d in sorted(per_day_rev)]

    per_day_new = {d: 0 for d in per_day_rev}
    for c in customers:
        t = _aware(c.get("created_at"))
        if t and t.date().isoformat() in per_day_new:
            per_day_new[t.date().isoformat()] += 1
    new_series = [{"date": d, "value": per_day_new[d]} for d in sorted(per_day_new)]
    new_count = sum(per_day_new.values())
    prev_new = sum(1 for c in customers
                   if prev_start <= (_aware(c.get("created_at")) or at) <= prev_end)

    # ---- campaigns -------------------------------------------------------------
    sent = list(_db.campaigns.find(
        {"tenant_id": tid, "sent_at": {"$gte": start, "$lte": end}},
        {"_id": 0, "id": 1, "name": 1, "content": 1, "image_url": 1, "status": 1,
         "recipient_ids": 1, "clicks": 1, "opens": 1, "attributed_visit_customer_ids": 1}))
    touched = sum(len(c.get("recipient_ids") or []) for c in sent)
    clicks = sum(int(c.get("clicks") or 0) for c in sent)
    attributed = sum(len(c.get("attributed_visit_customer_ids") or []) for c in sent)
    best = None
    for c in sent:
        reach = len(c.get("recipient_ids") or []) or 1
        rate = len(c.get("attributed_visit_customer_ids") or []) / reach
        if best is None or rate > best["_rate"]:
            best = {"_rate": rate, "name": c.get("name") or "Campagne",
                    "image_url": c.get("image_url"), "status": c.get("status") or "sent",
                    "touched": len(c.get("recipient_ids") or []),
                    "clicks": int(c.get("clicks") or 0),
                    "sales": len(c.get("attributed_visit_customer_ids") or []),
                    "conversion": round(rate * 100, 1)}
    if best:
        best.pop("_rate", None)
    campaigns = {"sent": len(sent), "touched": touched, "clicks": clicks,
                 "sales": attributed, "best": best}

    # ---- products ----------------------------------------------------------------
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
    products = [{"name": n, "sales": int(a["sales"]), "revenue": _money(a["revenue"])}
                for n, a in sorted(tally.items(), key=lambda kv: -kv[1]["sales"])[:5]]

    # ---- when people come ------------------------------------------------------
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
            # The design's grid runs 8h–20h, but a bar or a bakery trades
            # outside it. Those visits are counted and reported rather than
            # silently dropped, so the page can say the grid is not the whole
            # story instead of showing a shop its quietest hours as its only
            # hours.
            outside += 1
    peak = max((n for row in grid for n in row), default=0)
    hours = {"weekdays": WEEKDAYS, "slots": [f"{a}h – {b}h" for a, b in HOURS],
             "grid": grid, "peak": peak, "outside": outside,
             "covers": f"{HOURS[0][0]}h – {HOURS[-1][1]}h"}

    # ---- who the clients are ------------------------------------------------------
    buckets = {"loyal": 0, "new": 0, "occasional": 0, "inactive": 0}
    for c in customers:
        last = _aware(c.get("last_visit_date"))
        created = _aware(c.get("created_at"))
        if not last or (at - last).days >= INACTIVE_DAYS:
            buckets["inactive"] += 1
        elif int(c.get("visits") or 0) >= LOYAL_VISITS:
            buckets["loyal"] += 1
        elif created and (at - created).days <= NEW_DAYS:
            buckets["new"] += 1
        else:
            buckets["occasional"] += 1
    total_b = sum(buckets.values()) or 1
    status_mix = {
        "total": sum(buckets.values()),
        "slices": [
            {"key": "loyal", "label": "Clients fidélisés", "tone": "green",
             "count": buckets["loyal"], "pct": round(buckets["loyal"] / total_b * 100)},
            {"key": "new", "label": "Nouveaux clients", "tone": "blue",
             "count": buckets["new"], "pct": round(buckets["new"] / total_b * 100)},
            {"key": "occasional", "label": "Clients occasionnels", "tone": "amber",
             "count": buckets["occasional"], "pct": round(buckets["occasional"] / total_b * 100)},
            {"key": "inactive", "label": "Clients inactifs", "tone": "slate",
             "count": buckets["inactive"], "pct": round(buckets["inactive"] / total_b * 100)},
        ],
    }

    return {
        "from": start.isoformat(), "to": end.isoformat(), "days": days,
        "shop": {"name": tenant.get("name") or "votre commerce", "city": tenant.get("city") or ""},
        "cards": cards, "goal": goal, "impact": impact,
        "revenue_series": revenue_series,
        "revenue_total": _money(revenue), "revenue_delta": _delta(revenue, prev_revenue),
        "new_series": new_series, "new_total": new_count,
        "new_delta": _delta(new_count, prev_new),
        "campaigns": campaigns, "products": products, "hours": hours,
        "status_mix": status_mix,
        "recommendations": _recommendations(buckets, campaigns, products, goal),
    }


def _recommendations(buckets: Dict[str, int], campaigns: Dict[str, Any],
                     products: List[Dict[str, Any]], goal: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Only advice the figures support. A shop with nobody to win back is not
    told to win people back."""
    out: List[Dict[str, Any]] = []
    if buckets["inactive"]:
        out.append({
            "key": "reactivate", "icon": "users", "tone": "blue",
            "title": "Réactivez vos clients inactifs",
            "body": f"{buckets['inactive']} client{'s' if buckets['inactive'] > 1 else ''} "
                    f"ne sont pas venus depuis plus de {INACTIVE_DAYS} jours. "
                    "Envoyez-leur une offre personnalisée.",
            "cta": "Relancer ces clients", "to": "/dashboard/campaigns"})
    if not campaigns["sent"]:
        out.append({
            "key": "first_campaign", "icon": "chart", "tone": "green",
            "title": "Lancez votre première campagne",
            "body": "Aucune campagne sur la période. Une offre bien ciblée est le moyen "
                    "le plus direct de faire revenir vos clients.",
            "cta": "Créer la campagne", "to": "/dashboard/campaigns"})
    if not goal["is_set"]:
        out.append({
            "key": "set_goal", "icon": "target", "tone": "violet",
            "title": "Fixez votre objectif du mois",
            "body": "Donnez-vous un objectif de chiffre d'affaires : le tableau de bord "
                    "suivra votre progression tout au long du mois.",
            "cta": "Définir un objectif", "to": "/dashboard/settings#settings-goal"})
    if products:
        out.append({
            "key": "promote", "icon": "star", "tone": "amber",
            "title": f"Mettez « {products[0]['name']} » en avant",
            "body": f"C'est votre produit le plus vendu ({products[0]['sales']} ventes). "
                    "Une offre autour de lui convertit plus facilement.",
            "cta": "Créer une offre", "to": "/dashboard/card"})
    return out[:3]
