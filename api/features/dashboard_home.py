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

    Impact FidClic  revenue from visits a FidClic feature brought in — a
                    campaign, proximity push, offer or automation received in
                    the 15 days before, or a filleul's visit. A plain scan is
                    not counted (features/fidclic_impact.py). It is a floor,
                    not a claim about everything the programme caused.
    Objectif        the merchant's own number, set in Paramètres. Until they set
                    one the card asks for it instead of inventing a target.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S
from features import period as P, fidclic_impact as FI

router = APIRouter(tags=["dashboard"])
_db = None

ATTRIBUTION_DAYS = FI.WINDOW_DAYS   # a visit this soon after a send is attributed to it
LOYAL_VISITS = 5
INACTIVE_DAYS = 30
NEW_DAYS = 30

HOURS = [(8, 10), (10, 12), (12, 14), (14, 16), (16, 18), (18, 20)]
# Whole day names: the browser's translator turned the short ones into
# nonsense (« Mer » → Sea, « Jeu » → Game, « Mar » → March — user, 2026-10-03).
WEEKDAYS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


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


def _money(n: float) -> float:
    return round(float(n or 0), 2)


# ---------------------------------------------------------------------------
# the monthly goal
# ---------------------------------------------------------------------------
class Goal(BaseModel):
    monthly_revenue_goal: float = Field(0, ge=0, le=10_000_000)


# The Tableau de bord is open to every role that reads data; what it shows is
# limited to the establishments the caller may see (features/store_scope.py).
READERS = ["business_owner", "administrateur", "manager"]


def goal_target(tenant: Dict[str, Any], scope: "S.Scope") -> float:
    """The shop's goal on "all"; one establishment's own goal when one is
    chosen; the sum of theirs for an administrateur's set."""
    if scope.is_all:
        return float(tenant.get("monthly_revenue_goal") or 0)
    per_store = tenant.get("store_goals") or {}
    return float(sum(float(per_store.get(i) or 0) for i in scope.ids))


def goal_editable(token: TokenData, scope: "S.Scope") -> bool:
    if token.role == "business_owner":
        return scope.is_all or scope.single is not None
    if token.role == "administrateur":
        return scope.single is not None and scope.single in scope.allowed
    return False


@router.get("/api/owner/home/goal")
def get_goal(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    scope = S.resolve(token_data, request)
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    return {"monthly_revenue_goal": goal_target(tenant, scope), "can_edit": goal_editable(token_data, scope)}


@router.put("/api/owner/home/goal")
def set_goal(body: Goal, request: Request = None,
             token_data: TokenData = Depends(require_role(["business_owner", "administrateur"], partial_ok=True))):
    scope = S.resolve(token_data, request)
    if not goal_editable(token_data, scope):
        raise HTTPException(status_code=403, detail="Choisissez un de vos établissements pour fixer son objectif.")
    amount = float(body.monthly_revenue_goal)
    field = "monthly_revenue_goal" if scope.is_all else f"store_goals.{scope.single}"
    _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {field: amount}})
    return {"monthly_revenue_goal": amount, "can_edit": True}


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
def _visits(tid: str, start: datetime, end: datetime, scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    return list(_db.visits.find(
        {"tenant_id": tid, "visit_time": {"$gte": start, "$lte": end},
         **(S.visit_filter(scope) if scope else {})},
        {"_id": 0, "customer_id": 1, "amount_paid": 1, "visit_time": 1, "items": 1}))


def _revenue(rows: List[Dict[str, Any]]) -> float:
    return sum(float(v.get("amount_paid") or 0) for v in rows)


@router.get("/api/owner/home/overview")
def overview(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
             token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    at = _now()
    days = P.clamp_days(days)
    start, end = _window(days)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    tenant = _db.tenants.find_one({"id": tid}) or {}
    rows = _visits(tid, start, end, scope)
    prev_rows = _visits(tid, prev_start, prev_end, scope)
    from features import clients_page as CP
    # The Clients page's columns: the shop's rules may read any of them.
    customers = list(_db.customers.find(S.customer_filter(scope), CP.FIELDS))

    revenue, prev_revenue = _revenue(rows), _revenue(prev_rows)
    # « Clients fidélisés » and « Clients inactifs » are the Clients page's own
    # (the shop's Règles clients, features/clients_page.py): a click on a card
    # opens a list with exactly that many people (user, 2026-10-02).
    from features import clients_page as CP, customer_rules as R
    rules = R.load(tid)
    total_clients = len(customers)
    before = [c for c in customers if (_aware(c.get("created_at")) or at) < start]
    prev_clients = len(before)
    loyal = sum(1 for c in customers if CP.is_loyal(c, at, rules))
    prev_loyal = sum(1 for c in before if CP.is_loyal(c, start, rules))
    inactive = sum(1 for c in customers if CP.is_inactive(c, at, rules))
    prev_inactive = sum(1 for c in before if CP.is_inactive(c, start, rules))

    # ---- the four figures (« Panier moyen » gave its place to « Clients inactifs », user 2026-10-02)
    cards = [
        {"key": "revenue", "label": "Chiffre d'affaires", "icon": "chart", "tone": "blue",
         "value": _money(revenue), "unit": "€", "badge": "FidClic",
         "delta_pct": _delta(revenue, prev_revenue), "to": "/dashboard/analytics?focus=revenue"},
        {"key": "clients", "label": "Clients totaux", "icon": "users", "tone": "green",
         "value": total_clients, "delta_pct": _delta(total_clients, prev_clients), "to": "/dashboard/customers"},
        {"key": "loyal", "label": "Clients fidélisés", "icon": "crown", "tone": "amber",
         "value": loyal, "delta_pct": _delta(loyal, prev_loyal), "to": "/dashboard/customers?segment=loyal"},
        {"key": "inactive", "label": "Clients inactifs", "icon": "moon", "tone": "rose",
         "value": inactive, "delta_pct": _delta(inactive, prev_inactive), "lower_is_better": True,
         "to": "/dashboard/customers?segment=inactive"},
    ]

    # ---- the month's goal ---------------------------------------------------
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_revenue = _revenue(_visits(tid, month_start, at, scope))
    goal_amount = goal_target(tenant, scope)
    goal = {
        "target": _money(goal_amount),
        "reached": _money(month_revenue),
        "remaining": _money(max(0.0, goal_amount - month_revenue)),
        "pct": round(min(100, month_revenue / goal_amount * 100)) if goal_amount else None,
        "is_set": goal_amount > 0,
        "can_edit": goal_editable(token_data, scope),
    }

    # ---- impact --------------------------------------------------------------
    # CA FidClic: only the visits a FidClic feature brought in — a campaign, a
    # proximity push, an offer, an automation received in the 15 days before,
    # or a filleul's (features/fidclic_impact.py). A plain scan is not counted.
    impact_now = FI.impact(tid, rows)
    impact_value, prev_impact = impact_now["revenue"], FI.impact(tid, prev_rows)["revenue"]
    impact = {
        "value": _money(impact_value), "delta_pct": _delta(impact_value, prev_impact),
        "note": "CA des clients revenus grâce à FidClic : campagnes, géolocalisation, offres, automatisations, parrainage",
        "window_days": FI.WINDOW_DAYS,
    }

    # ---- the two charts --------------------------------------------------------
    per_day_rev = {s["date"]: 0.0 for s in P.slots(start, end, days)}
    labels = {s["date"]: s.get("label") for s in P.slots(start, end, days)}
    for v in rows:
        t = _aware(v.get("visit_time"))
        k = P.key_of(t, days) if t else None
        if k in per_day_rev:
            per_day_rev[k] += float(v.get("amount_paid") or 0)
    revenue_series = [{"date": d, "label": labels[d], "value": _money(per_day_rev[d])} for d in sorted(per_day_rev)]

    per_day_new = {d: 0 for d in per_day_rev}
    for c in customers:
        t = _aware(c.get("created_at"))
        k = P.key_of(t, days) if t else None
        if k in per_day_new:
            per_day_new[k] += 1
    new_series = [{"date": d, "label": labels[d], "value": per_day_new[d]} for d in sorted(per_day_new)]
    new_count = sum(per_day_new.values())
    prev_new = sum(1 for c in customers
                   if prev_start <= (_aware(c.get("created_at")) or at) <= prev_end)

    # ---- campaigns -------------------------------------------------------------
    sent = list(_db.campaigns.find(
        {"tenant_id": tid, "sent_at": {"$gte": start, "$lte": end}},
        {"_id": 0, "id": 1, "name": 1, "content": 1, "image_url": 1, "status": 1,
         "recipient_ids": 1, "clicks": 1, "opens": 1, "attributed_visit_customer_ids": 1}))
    if not scope.is_all:
        # A campaign counts here for the clients of these establishments only.
        mine = {c["id"] for c in customers}
        kept = []
        for c in sent:
            r = [i for i in c.get("recipient_ids") or [] if i in mine]
            if r:
                c["recipient_ids"] = r
                c["attributed_visit_customer_ids"] = [i for i in c.get("attributed_visit_customer_ids") or [] if i in mine]
                kept.append(c)
        sent = kept
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
        t = P.local(t)          # the hour on the shop's clock
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
    # One slice per client, the Clients page's definitions in this order:
    # inactif, then fidèle, then nouveau, else occasionnel — each slice opens
    # the same people on the Clients page (segments *_active / occasional).
    status_mix = CP.status_mix(customers, at, rules)

    return {
        "from": start.isoformat(), "to": end.isoformat(), "days": days,
        "scope": scope.describe(),
        "shop": {"name": tenant.get("name") or "votre commerce", "city": tenant.get("city") or ""},
        "cards": cards, "goal": goal, "impact": impact,
        "revenue_series": revenue_series,
        "revenue_total": _money(revenue), "revenue_delta": _delta(revenue, prev_revenue),
        "new_series": new_series, "new_total": new_count,
        "new_delta": _delta(new_count, prev_new),
        "campaigns": campaigns, "products": products, "hours": hours,
        "status_mix": status_mix,
        # « Choisissez votre récompense » until the merchant saved one.
        "reward_setup": _reward_setup(tid, token_data),
        "recommendations": _recommendations({x["key"]: x["count"] for x in status_mix["slices"]},
                                            campaigns, products, goal),
    }


def _reward_setup(tid: str, token_data: TokenData) -> Optional[Dict[str, Any]]:
    if getattr(token_data, "role", None) != "business_owner":
        return None                     # only the owner can change the card
    try:
        from services import sector_rewards
        return sector_rewards.needs_choice(_db, tid)
    except Exception:
        return None


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
                    "ne sont plus venus depuis un moment (règle « Client actif »). "
                    "Envoyez-leur une offre personnalisée.",
            "cta": "Voir et relancer ces clients", "to": "/dashboard/customers?segment=inactive"})
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
