"""
Super admin › Analytics global — built to the approved mockup.

One call for the whole page, for a period (« 1 sept. 2026 - 30 sept. 2026 »)
and a step (« Jour / Semaine / Mois ») that sets the points of the curves:
- five figures: commerces, clients finaux, visites, MRR, chiffre d'affaires
  total (what the businesses' customers spent, from their visits), each
  against the previous period of the same length;
- croissance des commerces, MRR and clients finaux: the total at the end of
  every step, with the change over the period;
- répartition des abonnements (businesses per plan), par secteur, par ville;
- répartition du chiffre d'affaires per plan (amounts only — the user asked
  for no percentages there: « Répartition des abonnements » already has them);
- sources d'acquisition of the customers who joined in the period;
- activité récente: commerces, abonnements, avis, campagnes, paiements,
  mises à jour.
The figures shared with the Dashboard come from the same helpers
(admin_dashboard), so both pages always agree.
"""
from __future__ import annotations

import time
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from auth import TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC
from features import admin_dashboard as AD

router = APIRouter(tags=["admin"])
_db = None
LIVE = AC.LIVE
GRAINS = ("day", "week", "month")
MAX_POINTS = {"day": 120, "week": 104}
CACHE_SECONDS = 60
_cache: Dict[Any, Any] = {}
from services.sources import SOURCES as _ALL_SOURCES, UNKNOWN_LABEL as _UNKNOWN  # one list (services/sources)
SOURCES = dict(_ALL_SOURCES)
PLAN_COLORS = {"silver": "#2F6BFF", "gold": "#10B981", "vip": "#8B5CF6", "franchise": "#F59E0B"}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _steps(start: datetime, end: datetime, grain: str):
    """(from, to) of every step of the period — calendar days, weeks from
    Monday, calendar months — clipped to the period. A step too fine for a
    long period moves up (day → week → month)."""
    if grain == "day" and (end - start).days > MAX_POINTS["day"]:
        grain = "week"
    if grain == "week" and (end - start).days / 7 > MAX_POINTS["week"]:
        grain = "month"
    out = []
    d = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "week":
        d -= timedelta(days=d.weekday())
    elif grain == "month":
        d = d.replace(day=1)
    while d < end:
        if grain == "day":
            n = d + timedelta(days=1)
        elif grain == "week":
            n = d + timedelta(days=7)
        else:
            n = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)
        out.append((max(d, start), min(n, end)))
        d = n
    return out, grain


def _plan_key(t: Dict[str, Any]) -> str:
    import server as core
    return core._canonical_plan(t.get("plan"))


def _plan_info(key: str) -> Dict[str, Any]:
    import server as core
    c = core.custom_plans().get(key) or {}
    return {"key": key, "label": core.plan_label(key), "color": c.get("color") or PLAN_COLORS.get(key, "#0EA5E9")}


def _plan_order(key: str) -> int:
    return {"silver": 0, "gold": 1, "vip": 2, "franchise": 3}.get(key, 4)


def _activity(start: datetime, end: datetime, limit: int) -> List[Dict[str, Any]]:
    import server as core
    names = {t["id"]: (t.get("name") or "—", t.get("city") or "") for t in _db.tenants.find({}, {"_id": 0, "id": 1, "name": 1, "city": 1})}
    who = lambda tid: (lambda n: f"{n[0]} ({n[1]})" if n[1] else n[0])(names.get(tid, ("—", "")))   # noqa: E731
    span = {"$gte": start, "$lte": end}
    ev: List[Dict[str, Any]] = []
    for t in _db.tenants.find({"created_at": span, "onboarding_status": {"$nin": ["verify", "company", "plan"]}},
                              {"_id": 0, "id": 1, "created_at": 1}):
        ev.append({"kind": "commerce", "text": f"Nouveau commerce ajouté : {who(t['id'])}", "at": t["created_at"], "tenant_id": t["id"]})
    for a in _db.audit_logs.find({"action": {"$in": ["billing.plan_activated", "admin.plan_change"]}, "ts": span}, {"_id": 0}):
        tid = a.get("tenant_id") or a.get("target")
        to = (a.get("meta") or {}).get("to")
        ev.append({"kind": "abonnement", "text": f"Abonnement {core.plan_label(to) if to else ''} activé : {who(tid)}".replace("  ", " "),
                   "at": a["ts"], "tenant_id": tid})
    for r in _db.reviews.find({"created_at": span}, {"_id": 0, "tenant_id": 1, "rating": 1, "created_at": 1}):
        ev.append({"kind": "avis", "text": f"Avis client reçu : {names.get(r.get('tenant_id'), ('—', ''))[0]} ({r.get('rating')}/10)",
                   "at": r["created_at"], "tenant_id": r.get("tenant_id")})
    for c in _db.campaigns.find({"sent_at": span}, {"_id": 0, "tenant_id": 1, "sent_at": 1, "name": 1, "title": 1}):
        label = c.get("name") or c.get("title") or "sans titre"
        ev.append({"kind": "marketing", "text": f"Campagne envoyée : {label} — {names.get(c.get('tenant_id'), ('—', ''))[0]}",
                   "at": c["sent_at"], "tenant_id": c.get("tenant_id")})
    for i in _db.fidclic_invoices.find({"paid_at": span}, {"_id": 0, "tenant_id": 1, "paid_at": 1, "amount_paid": 1, "total_ttc": 1, "plan": 1}):
        amount = float(i.get("amount_paid") or i.get("total_ttc") or 0)
        money = f"€{amount:,.2f}".replace(",", " ").replace(".", ",")
        plan = f" ({core.plan_label(i['plan'])})" if i.get("plan") else ""
        ev.append({"kind": "paiement", "text": f"Paiement reçu : {money}{plan} - {names.get(i.get('tenant_id'), ('—', ''))[0]}",
                   "at": i["paid_at"], "tenant_id": i.get("tenant_id")})
    for a in _db.audit_logs.find({"action": {"$in": ["etablissement.updated", "admin.commerce_edit"]}, "ts": span}, {"_id": 0}):
        tid = a.get("tenant_id") or a.get("target")
        ev.append({"kind": "maj", "text": f"Mise à jour : {names.get(tid, ('—', ''))[0]} (informations magasin)", "at": a["ts"], "tenant_id": tid})
    ev.sort(key=lambda e: AC._aware(e["at"]) or start, reverse=True)
    return [{**e, "at": AC._iso(e["at"])} for e in ev[:limit]]


def cities(tenants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """« Répartition par ville » — shared with the Dashboard."""
    c: Dict[str, int] = defaultdict(int)
    for t in tenants:
        c[(t.get("city") or "").strip() or "Autres"] += 1
    return AD._share(c, top=7)


def revenue_by_plan(tenants: List[Dict[str, Any]], start: datetime, end: datetime) -> Dict[str, Any]:
    """« Répartition du chiffre d'affaires »: what the businesses' customers
    spent (their visits) over the period, per plan — amounts only (the user
    asked for no percentages there). Shared with the Dashboard."""
    plan_of = {t["id"]: _plan_key(t) for t in tenants}
    per: Dict[str, float] = defaultdict(float)
    for v in _db.visits.find({"visit_time": {"$gte": start, "$lt": end}}, {"_id": 0, "amount_paid": 1, "tenant_id": 1}):
        if v.get("tenant_id") in plan_of:
            per[plan_of[v["tenant_id"]]] += float(v.get("amount_paid") or 0)
    rows = [{**_plan_info(k), "amount": round(a, 2)} for k, a in sorted(per.items(), key=lambda kv: (_plan_order(kv[0]), kv[0])) if a > 0]
    return {"rows": rows, "total": round(sum(r["amount"] for r in rows), 2)}


def sources(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    """« Sources d'acquisition clients » of the customers who joined in the
    period. Shared with the Dashboard."""
    src: Dict[str, int] = defaultdict(int)
    for c in _db.customers.find({**LIVE, "created_at": {"$gte": start, "$lt": end}}, {"_id": 0, "acquisition_source": 1}):
        from services.sources import key_of
        k = key_of(c)
        src[SOURCES.get(k, _UNKNOWN)] += 1
    order = list(SOURCES.values()) + [_UNKNOWN]
    return sorted(({"label": k, "count": v} for k, v in src.items() if v), key=lambda r: (-r["count"], order.index(r["label"])))


def _build(start: datetime, end: datetime, grain: str, months: int = 6) -> Dict[str, Any]:
    import server as core
    now = _now()
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    steps, grain = _steps(start, end, grain)
    ends = [min(b, now) for _, b in steps]
    prev = start - (end - start)

    # One read per collection, then counted in memory at every date — the
    # same definitions as the Dashboard (admin_dashboard._kpis).
    B = AD._buckets(start, end)
    t_dates = sorted(AC._aware(t.get("created_at")) or now for t in tenants)
    c_dates = sorted(d for d in (AC._aware(c.get("created_at")) for c in _db.customers.find(LIVE, {"_id": 0, "created_at": 1})) if d)
    before = lambda dates, at: bisect_left(dates, at)                   # noqa: E731
    visits = [(AC._aware(v.get("visit_time")), float(v.get("amount_paid") or 0), v.get("tenant_id"))
              for v in _db.visits.find({"visit_time": {"$gte": prev, "$lt": end}}, {"_id": 0, "visit_time": 1, "amount_paid": 1, "tenant_id": 1})]
    visits = [v for v in visits if v[0]]
    n_in = lambda a, b: sum(1 for v in visits if a <= v[0] < b)          # noqa: E731
    ca_in = lambda a, b: sum(v[1] for v in visits if a <= v[0] < b)      # noqa: E731
    paying = [t for t in tenants if (t.get("subscription_status") or "") == "active" and not t.get("suspended_at")]
    price = {t["id"]: core.tenant_price(t) for t in paying}
    mrr_at = lambda at: round(sum(price[t["id"]] for t in paying if (AC._aware(t.get("created_at")) or at) < at))   # noqa: E731

    def figure(key, cur, old, series):
        return {"key": key, "value": cur, "delta": AC._delta(cur, old), "series": series}
    kpis = [figure("commerces", before(t_dates, end), before(t_dates, start), [before(t_dates, b) for _, b in B]),
            figure("clients", before(c_dates, end), before(c_dates, start), [before(c_dates, b) for _, b in B]),
            figure("visites", n_in(start, end), n_in(prev, start), [n_in(a, b) for a, b in B]),
            figure("mrr", mrr_at(end if end < now else now), mrr_at(start), [mrr_at(b) for _, b in B])]
    kpis[3]["value"] = round(sum(price.values()))                        # today's MRR, as on the Dashboard
    kpis[3]["delta"] = AC._delta(kpis[3]["value"], mrr_at(start))
    kpis.append(figure("ca", round(ca_in(start, end), 2), ca_in(prev, start), [round(ca_in(a, b), 2) for a, b in B]))
    base = {k["key"]: k for k in kpis}

    growth = [{"at": AC._iso(a), "value": before(t_dates, e)} for (a, _), e in zip(steps, ends)]
    clients = [{"at": AC._iso(a), "value": before(c_dates, e)} for (a, _), e in zip(steps, ends)]
    mrr = [{"at": AC._iso(a), "value": mrr_at(e)} for (a, _), e in zip(steps, ends)]

    per_plan: Dict[str, int] = defaultdict(int)
    for t in tenants:
        per_plan[_plan_key(t)] += 1
    total = sum(per_plan.values())
    plans = [{**_plan_info(k), "count": n, "pct": round(n / total * 100) if total else 0}
             for k, n in sorted(per_plan.items(), key=lambda kv: (_plan_order(kv[0]), kv[0])) if n]

    sectors: Dict[str, int] = defaultdict(int)
    for t in tenants:
        sectors[AC._sector(t.get("sector")) or "Autres"] += 1

    def change(series):
        return AC._delta(series[-1]["value"], series[0]["value"]) if series else None

    return {"period": {"from": AC._iso(start), "to": AC._iso(end)}, "grain": grain, "kpis": kpis,
            "growth": {"points": growth, "delta": base["commerces"]["delta"]},
            "mrr": {"points": mrr, "delta": base["mrr"]["delta"]},
            "clients": {"points": clients, "delta": base["clients"]["delta"]},
            "plans": {"rows": plans, "total": total}, "sectors": AD._share(sectors, top=6), "cities": cities(tenants),
            "revenue": revenue_by_plan(tenants, start, end), "sources": sources(start, end), "activity": _activity(start, end, 6),
            # Moved here from the Dashboard (user, 2026-10-01): its sector donut and « Évolution de la plateforme ».
            "sectors_donut": AD._share(sectors), "evolution": AD._evolution(months), "curve_change": {"growth": change(growth), "mrr": change(mrr), "clients": change(clients)}}


@router.get("/api/admin/analytics/global")
def analytics(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
              grain: str = "day", months: int = 6, token_data: TokenData = Depends(require_admin("analytics"))):
    start, end = AD._period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    grain = grain if grain in GRAINS else "day"
    months = 12 if int(months or 6) >= 12 else 6
    key = (start.isoformat(), end.isoformat(), grain, months)
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    out = _build(start, end, grain, months)
    _cache.clear()
    _cache[key] = (time.time() + CACHE_SECONDS, out)
    return out


@router.get("/api/admin/analytics/activity")
def activity(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
             limit: int = 100, token_data: TokenData = Depends(require_admin("analytics"))):
    start, end = AD._period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    return {"rows": _activity(start, end, max(1, min(300, int(limit))))}
