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
    hands back what each panel needs. The finished days come from the register
    of past days (features/visit_days, 2026-10-28) — only today and the cut
    ends of a period are read from the visits.

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

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S
from features import period as P, fidclic_impact as FI
from services import playbooks as PB

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
def _cards_lost(tid: str, scope, at: datetime) -> Dict[str, Any]:
    from features import card_status as CS
    try:
        return CS.dashboard_count(tid, at, S.customer_ids(scope))
    except Exception:
        return {"count": 0, "hours": CS.ALERT_HOURS, "href": "/dashboard/customers?card=recent"}


def _sent_in(tid: str, start: datetime, end: datetime, scope: "S.Scope", mine: Optional[set]) -> List[Dict[str, Any]]:
    """The campaigns SENT in the period, for this establishment, counted as on
    Campagnes and Analyses (services/campaign_figures, QA F32)."""
    from features import campaigns_page as CPG
    return CPG._limit(list(_db.campaigns.find(
        {"tenant_id": tid, "status": "sent", "sent_at": {"$gte": start, "$lte": end}}, {"_id": 0})), mine, scope)


@router.get("/api/owner/home/campaigns")
def campaign_lists(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                   token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The four cards of « Performance des campagnes », opened (user,
    2026-10-23: a click opened the Campagnes page instead of what the card
    counts): the campaigns, the clients they reached, who clicked, and the
    visits credited to them — same period, same establishment, same rules."""
    from services import campaign_figures as CF
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    start, end = _window(P.clamp_days(days))
    mine = None if scope.is_all else S.customer_ids(scope)
    sent = sorted(_sent_in(tid, start, end, scope, mine), key=lambda c: _aware(c.get("sent_at")) or start, reverse=True)
    att = CF.attribution(_db, tid, sent, S.visit_filter(scope), detail=True)
    ids = set()
    for c in sent:
        ids.update(c.get("recipient_ids") or [])
    people = {p["id"]: p for p in _db.customers.find({"tenant_id": tid, "id": {"$in": list(ids)}},
                                                    {"_id": 0, "id": 1, "name": 1, "barcode_id": 1})}

    def who(cid):
        p = people.get(cid) or {}
        return {"customer_id": cid, "name": p.get("name") or "Client supprimé", "barcode_id": p.get("barcode_id")}

    campaigns, touched, clicked, sales = [], {}, [], []
    for c in sent:
        a = att.get(c["id"]) or {}
        name = c.get("name") or "Campagne"
        at = _aware(c.get("sent_at"))
        campaigns.append({"id": c["id"], "name": name, "sent_at": at.isoformat() if at else None,
                          "recipients": len(c.get("recipient_ids") or []), "clicks": CF.clicks(c),
                          "sales": a.get("sales", 0), "revenue": a.get("revenue", 0.0)})
        for cid in c.get("recipient_ids") or []:
            row = touched.setdefault(cid, {**who(cid), "campaigns": []})
            row["campaigns"].append(name)
        for cid in c.get("click_customer_ids") or []:
            if mine is None or cid in mine:
                clicked.append({**who(cid), "campaign": name, "campaign_id": c["id"]})
        for v in a.get("visits") or []:
            t = _aware(v["visit_time"])
            sales.append({**who(v["customer_id"]), "campaign": name, "campaign_id": c["id"],
                          "visit_time": t.isoformat() if t else None, "amount": v["amount"]})
    sales.sort(key=lambda x: x["visit_time"] or "", reverse=True)
    return {"window_days": ATTRIBUTION_DAYS, "campaigns": campaigns,
            "touched": sorted(touched.values(), key=lambda x: x["name"].lower()),
            "clicks": {"total": sum(CF.clicks(c) for c in sent), "people": clicked},
            "sales": sales}


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
    # The period, the one before and the month: finished days from the
    # register of past days, today and the cut ends from the visits — the
    # same figures, without reading every visit (features/visit_days).
    from features import visit_days as VD
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    tot, prev_tot, month_tot = VD.span_many(
        tid, scope, [(start, end), (prev_start, prev_end), (month_start, at)], at)
    from features import clients_page as CP
    # The Clients page's columns: the shop's rules may read any of them.
    customers = list(_db.customers.find(S.customer_filter(scope), CP.FIELDS))

    revenue, prev_revenue = tot.revenue, prev_tot.revenue
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
    month_revenue = month_tot.revenue
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
    impact_now = tot.impact()
    impact_value, prev_impact = impact_now["revenue"], prev_tot.impact()["revenue"]
    impact = {
        "value": _money(impact_value), "delta_pct": _delta(impact_value, prev_impact),
        "note": "CA des clients revenus grâce à FidClic : campagnes, géolocalisation, offres, automatisations, parrainage",
        "window_days": FI.WINDOW_DAYS,
    }

    # ---- the two charts --------------------------------------------------------
    per_day_rev = {s["date"]: 0.0 for s in P.slots(start, end, days)}
    labels = {s["date"]: s.get("label") for s in P.slots(start, end, days)}
    per_day_visits = {d: 0 for d in per_day_rev}
    for (day, hour), (n, money) in tot.hours.items():
        k = f"{day}T{hour:02d}:00" if P.hourly(days) else day
        if k in per_day_rev:
            per_day_rev[k] += money
            per_day_visits[k] += n
    per_day_rev = {k: x / VD.MICRO for k, x in per_day_rev.items()}
    # « visits » is what the point's card shows under the figure — the visits
    # behind that day's revenue, and with them the basket (user, 2026-10-16).
    revenue_series = [{"date": d, "label": labels[d], "value": _money(per_day_rev[d]),
                       "visits": per_day_visits[d]} for d in sorted(per_day_rev)]

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
    # the campaigns SENT in the period, for this establishment, counted as on
    # Campagnes and Analyses (services/campaign_figures, QA F32)
    from services import campaign_figures as CF
    sent = _sent_in(tid, start, end, scope, None if scope.is_all else {c["id"] for c in customers})
    att = CF.attribution(_db, tid, sent, S.visit_filter(scope))
    touched = sum(len(c.get("recipient_ids") or []) for c in sent)
    clicks = sum(CF.clicks(c) for c in sent)
    attributed = sum((att.get(c["id"]) or {}).get("sales", 0) for c in sent)
    best = None
    for c in sent:
        a = att.get(c["id"]) or {"sales": 0, "buyers": 0}
        reach = len(c.get("recipient_ids") or []) or 1
        rate = a["buyers"] / reach
        if best is None or rate > best["_rate"]:
            best = {"_rate": rate, "id": c.get("id"), "name": c.get("name") or "Campagne",
                    "image_url": c.get("image_url"), "status": c.get("status") or "sent",
                    "touched": len(c.get("recipient_ids") or []),
                    "clicks": CF.clicks(c),
                    "sales": a["sales"],
                    "conversion": round(rate * 100, 1)}
    if best:
        best.pop("_rate", None)
    campaigns = {"sent": len(sent), "touched": touched, "clicks": clicks,
                 "sales": attributed, "best": best}

    # ---- products ----------------------------------------------------------------
    products = tot.top_products(5)

    # ---- when people come ------------------------------------------------------
    grid = [[0 for _ in HOURS] for _ in WEEKDAYS]
    outside = 0
    for (day, hour), (n, _) in tot.hours.items():     # the hour on the shop's clock
        wd = date.fromisoformat(day).weekday()
        for hi, (lo, hi_h) in enumerate(HOURS):
            if lo <= hour < hi_h:
                grid[wd][hi] += n
                break
        else:
            # The design's grid runs 8h–20h, but a bar or a bakery trades
            # outside it. Those visits are counted and reported rather than
            # silently dropped, so the page can say the grid is not the whole
            # story instead of showing a shop its quietest hours as its only
            # hours.
            outside += n
    peak = max((n for row in grid for n in row), default=0)
    hours = {"weekdays": WEEKDAYS, "slots": [f"{a}h – {b}h" for a, b in HOURS],
             "grid": grid, "peak": peak, "outside": outside,
             "covers": f"{HOURS[0][0]}h – {HOURS[-1][1]}h"}

    # ---- who the clients are ------------------------------------------------------
    # One slice per client, the Clients page's definitions in this order:
    # inactif, then fidèle, then nouveau, else occasionnel — each slice opens
    # the same people on the Clients page (segments *_active / occasional).
    status_mix = CP.status_mix(customers, at, rules)

    recos = _recommendations({x["key"]: x["count"] for x in status_mix["slices"]},
                             campaigns, products, goal, PB.of(tenant), limit=None)
    # the ranking that learns (2026-10-30): the figures' order × what was learned, then three
    from features import reco_ranking as RR
    recos = RR.rank(tid, recos, lambda r, n: float(len(recos) - n), by=getattr(token_data, "email", None))[:3]
    # the journal of ideas (2026-10-29): shown, and what each brought last time
    from features import reco_journal as RJ
    RJ.shown(tid, "dashboard", recos, scope.key)
    RJ.attach(tid, recos)
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
        # cards deleted in the last 30 days — a loss the owner must see (2026-10-09)
        "cards_lost": _cards_lost(tid, scope, at),
        "recommendations": recos,
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
                     products: List[Dict[str, Any]], goal: Dict[str, Any],
                     play: Optional[Dict[str, Any]] = None, at: Optional[datetime] = None,
                     limit: Optional[int] = 3) -> List[Dict[str, Any]]:
    """Only advice the figures support. A shop with nobody to win back is not
    told to win people back. The shop's playbook (services/playbooks.py) adds
    its trade's top advice in season, and its own words."""
    play = play or PB.of(None)
    month = (at or datetime.now(timezone.utc)).month
    out: List[Dict[str, Any]] = []
    if buckets["inactive"]:
        out.append({
            "key": "reactivate", "icon": "users", "tone": "blue",
            "title": "Réactivez vos clients inactifs",
            "body": f"{buckets['inactive']} client{'s' if buckets['inactive'] > 1 else ''} "
                    "ne sont plus venus depuis un moment (règle « Client actif »). "
                    "Envoyez-leur une offre personnalisée.",
            "cta": "Relancer ces clients", "to": "/dashboard/campaigns?template=relance_inactifs"})
    if not campaigns["sent"]:
        out.append({
            "key": "first_campaign", "icon": "chart", "tone": "green",
            "title": "Lancez votre première campagne",
            "body": "Aucune campagne sur la période. Une offre bien ciblée est le moyen "
                    "le plus direct de faire revenir vos clients.",
            "cta": "Créer la campagne", "to": "/dashboard/campaigns?nouveau=offre"})
    if not goal["is_set"]:
        out.append({
            "key": "set_goal", "icon": "target", "tone": "violet",
            "title": "Fixez votre objectif du mois",
            "body": "Donnez-vous un objectif de chiffre d'affaires : le tableau de bord "
                    "suivra votre progression tout au long du mois.",
            "cta": "Définir un objectif", "to": "/dashboard/settings#settings-goal"})
    # the trade's advice comes second, so it is always among the three shown
    lever = next((lv for shelf in ("idee", "opportunite") for lv in play["levers"]
                  if lv["shelf"] == shelf and PB.in_season(lv, month)), None)
    if lever:
        to = lever.get("to") or f"/dashboard/campaigns?template={quote(lever['template']['key'], safe='')}"
        out.insert(min(1, len(out)), {
            "key": f"pb_{lever['key']}", "icon": "star", "tone": "violet", "title": lever["title"],
            "body": lever["body"], "cta": lever["label"], "to": to})
    if products:
        one = play["items"][0]
        best = ("votre produit le plus vendu" if one == "produit" else
                f"votre {one} la plus demandée" if one in ("prestation", "séance") else f"votre {one} le plus demandé")
        out.append({
            "key": "promote", "icon": "star", "tone": "amber",
            "title": f"Mettez « {products[0]['name']} » en avant",
            "body": f"C'est {best} ({products[0]['sales']} ventes). "
                    "Une offre dessus convertit plus facilement.",
            # the composer opens on that offer (user, 2026-10-23: it opened the card page)
            "cta": "Créer une offre", "to": f"/dashboard/campaigns?template=produit:{quote(products[0]['name'], safe='')}"})
    return out[:limit] if limit else out
