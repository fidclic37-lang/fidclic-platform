"""
Super admin › Analytics › « Analyses avancées » (user, 2026-10-01). Each
section has its own endpoint so the page fills in as they arrive.

- Cohortes de rétention: businesses grouped by the month they signed up;
  for each later month, the share still a client — en essai or abonné (the
  user's choice: not résilié, not a trial that ended unconverted, not
  impayé). Past months are rebuilt from the dates we keep (sign-up,
  résiliation, end of trial, suspension); the current month uses today's
  standing.
- Benchmarks par secteur: per sector, the MEDIAN business over the last 90
  days — panier moyen, visites par client, taux de retour, cartes and scans
  a week — with how many businesses it rests on (fewer than 3: « échantillon
  faible »). Only businesses at least 30 days old with some activity count.
- Adoption des fonctionnalités par plan: share of each plan's businesses that
  really use wallet, campagnes, automatisations, géolocalisation, FIDCLIC AI,
  parrainage, segments, API — and whether the plan includes it.
- Upgrades / downgrades: plan changes over the period (by the team or paid
  online), with the € / month they moved.
- Top / bottom croissance (user's choice: a combined score): for each
  business old enough to have both periods and with enough activity, the
  growth of scans, new cards and chiffre d'affaires, period vs the one
  before (each capped −100 % … +300 %), averaged.
- Carte des commerces: every business on a map — its own position when it
  set one, else the centre of its postal code, else of its town.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from auth import TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC
from features import admin_dashboard as AD

router = APIRouter(tags=["admin"])
_db = None
LIVE = AC.LIVE
MIN_AGE_DAYS = 30
MIN_ACTIVITY = 20             # scans or cards over both periods, for « croissance »
CAP = (-100.0, 300.0)
GEO_FETCH_PER_CALL = 25       # new places looked up per call; the rest on the next one


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


_aware, _iso, _delta = AC._aware, AC._iso, AC._delta


def _period(date_from, date_to):
    return AD._period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)


def _tenants() -> List[Dict[str, Any]]:
    return list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))


def _plan(t: Dict[str, Any]) -> str:
    import server as core
    return core._canonical_plan(t.get("plan"))


# ---------------------------------------------------------------------------
# Cohortes de rétention
# ---------------------------------------------------------------------------
def _add_months(d: datetime, n: int) -> datetime:
    m = d.month - 1 + n
    return d.replace(year=d.year + m // 12, month=m % 12 + 1, day=1)


@router.get("/api/admin/analytics/deep/cohorts")
def cohorts(months: int = 12, token_data: TokenData = Depends(require_admin("analytics"))):
    now = _now()
    months = max(3, min(24, int(months)))
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first = _add_months(m0, -(months - 1))
    tenants = _tenants()
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in tenants:
        c = _aware(t.get("created_at"))
        if c and c >= first:
            groups[c.strftime("%Y-%m")].append(t)
    rows = []
    for i in range(months):
        start = _add_months(first, i)
        key = start.strftime("%Y-%m")
        members = groups.get(key, [])
        cells = []
        for k in range(0, months - i):
            at = min(_add_months(start, k + 1), now)
            current = at >= now - timedelta(minutes=5)
            if current:                                     # this month: today's standing
                kept = sum(1 for t in members if AC.standing_of(t, now) in ("essai", "abonne"))
            else:                                           # earlier months: rebuilt from the dates
                kept = sum(1 for t in members if AD._in_portfolio_at(t, at, now))
            cells.append({"month": k, "kept": kept, "pct": round(kept / len(members) * 100) if members else None})
        rows.append({"cohort": key, "size": len(members), "cells": cells})
    return {"rows": rows, "months": months}


# ---------------------------------------------------------------------------
# Benchmarks par secteur
# ---------------------------------------------------------------------------
@router.get("/api/admin/analytics/deep/benchmarks")
def benchmarks(token_data: TokenData = Depends(require_admin("analytics"))):
    now = _now()
    since = now - timedelta(days=90)
    weeks = 90 / 7
    tenants = [t for t in _tenants() if AC.standing_of(t, now) in ("essai", "abonne", "impaye")
               and (_aware(t.get("created_at")) or now) <= now - timedelta(days=MIN_AGE_DAYS)]
    ids = {t["id"] for t in tenants}
    visits: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in _db.visits.find({"visit_time": {"$gte": since}}, {"_id": 0, "tenant_id": 1, "customer_id": 1, "amount_paid": 1}):
        if v.get("tenant_id") in ids:
            visits[v["tenant_id"]].append(v)
    cards = AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": since}})
    per: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for t in tenants:
        vs = visits.get(t["id"], [])
        if not vs and not cards.get(t["id"]):
            continue                                      # no activity at all: not a benchmark
        sector = AC._sector(t.get("sector")) or "Autres"
        paid = [float(v.get("amount_paid") or 0) for v in vs if float(v.get("amount_paid") or 0) > 0]
        by_c: Dict[str, int] = defaultdict(int)
        for v in vs:
            by_c[v.get("customer_id")] += 1
        m = {"panier": sum(paid) / len(paid) if paid else None,
             "visites_client": len(vs) / len(by_c) if by_c else None,
             "retour": sum(1 for n in by_c.values() if n >= 2) / len(by_c) * 100 if by_c else None,
             "cartes_semaine": cards.get(t["id"], 0) / weeks, "scans_semaine": len(vs) / weeks}
        for bucket in (sector, "__all__"):
            for k, val in m.items():
                if val is not None:
                    per[bucket][k].append(val)
            per[bucket]["n"].append(1)
    out = []
    for sector, vals in per.items():
        n = len(vals["n"])
        med = {k: round(median(vals[k]), 1) if vals.get(k) else None for k in ("panier", "visites_client", "retour", "cartes_semaine", "scans_semaine")}
        out.append({"sector": "Toute la plateforme" if sector == "__all__" else sector, "n": n, "low_sample": n < 3, **med,
                    "panier_n": len(vals.get("panier", []))})
    out.sort(key=lambda r: (r["sector"] != "Toute la plateforme", -r["n"], r["sector"]))
    return {"rows": out, "window_days": 90, "min_age_days": MIN_AGE_DAYS}


# ---------------------------------------------------------------------------
# Adoption des fonctionnalités par plan
# ---------------------------------------------------------------------------
FEATURES = [("wallet", "Wallet", "wallet"), ("campagnes", "Campagnes", "campaigns"), ("automatisations", "Automatisations", "automations"),
            ("geo", "Géolocalisation", "geo_proximity"), ("ia", "FIDCLIC AI", "ai_level"), ("parrainage", "Parrainage", "referral"),
            ("segments", "Segments", "segmentation"), ("api", "API", "api_access")]


@router.get("/api/admin/analytics/deep/adoption")
def adoption(token_data: TokenData = Depends(require_admin("analytics"))):
    import server as core
    now = _now()
    m30 = now - timedelta(days=30)
    tenants = [t for t in _tenants() if AC.standing_of(t, now) in ("essai", "abonne", "impaye")]
    used = {
        "wallet": set(_db.customers.distinct("tenant_id", {**LIVE, "pass_issued": True})),
        "campagnes": set(_db.campaigns.distinct("tenant_id", {"sent_at": {"$gte": m30}})),
        "automatisations": set(_db.auto_campaign_log.distinct("tenant_id", {"sent_at": {"$gte": m30}})),
        "geo": {t["id"] for t in tenants if t.get("geo_enabled")},
        "ia": set(_db.ai_queries.distinct("tenant_id", {"created_at": {"$gte": m30}})),
        "parrainage": set(_db.referral_config.distinct("tenant_id", {"enabled": True})),
        "segments": set(_db.saved_segments.distinct("tenant_id", {})),
        "api": set(_db.api_keys.distinct("tenant_id", {"revoked_at": None})),
    }
    by_plan: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in tenants:
        by_plan[_plan(t)].append(t)
    order = {"silver": 0, "gold": 1, "vip": 2, "franchise": 3}
    rows = []
    for plan in sorted(by_plan, key=lambda p: (order.get(p, 9), p)):
        group = by_plan[plan]
        f = core.get_plan_features(plan)
        cells = []
        for key, label, flag in FEATURES:
            included = (f.get(flag) or "none") != "none" if flag == "ai_level" else bool(f.get(flag))
            n = sum(1 for t in group if t["id"] in used[key])
            cells.append({"key": key, "label": label, "included": included, "count": n, "pct": round(n / len(group) * 100) if group else 0})
        rows.append({"plan": plan, "label": core.plan_label(plan), "count": len(group), "cells": cells})
    return {"rows": rows, "features": [{"key": k, "label": l} for k, l, _ in FEATURES],
            "definitions": {"wallet": "au moins une carte ajoutée à un Wallet", "campagnes": "une campagne envoyée sur 30 jours",
                            "automatisations": "un envoi automatique sur 30 jours", "geo": "géolocalisation activée",
                            "ia": "une question à l'IA sur 30 jours", "parrainage": "programme de parrainage activé",
                            "segments": "au moins un segment enregistré", "api": "une clé API active"}}


# ---------------------------------------------------------------------------
# Upgrades / downgrades
# ---------------------------------------------------------------------------
def _rank(plan: Optional[str]) -> float:
    import server as core
    if not plan:
        return 0
    return {"silver": 1, "gold": 2, "vip": 3, "franchise": 4}.get(plan) or 1 + float(core.get_plan_features(plan).get("price") or 0) / 1000


@router.get("/api/admin/analytics/deep/plan-moves")
def plan_moves(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
               token_data: TokenData = Depends(require_admin("analytics"))):
    import server as core
    start, end = _period(date_from, date_to)
    names = {t["id"]: t.get("name") for t in _tenants()}
    rows = []
    for a in _db.audit_logs.find({"action": {"$in": ["admin.plan_change", "billing.plan_activated"]}, "ts": {"$gte": start, "$lt": end}},
                                 {"_id": 0}).sort("ts", -1):
        m = a.get("meta") or {}
        frm, to = m.get("from"), m.get("to")
        tid = a.get("tenant_id") or a.get("target")
        if not to or frm == to:
            continue
        diff = _rank(to) - _rank(frm)
        kind = "upgrade" if diff > 0 else "downgrade" if diff < 0 else "change"
        if not frm:
            kind = "activation"
        price = lambda p: float(core.get_plan_features(p).get("price") or 0) if p else 0.0      # noqa: E731
        rows.append({"at": _iso(a.get("ts")), "tenant_id": tid, "name": names.get(tid) or "—", "from": core.plan_label(frm) if frm else None,
                     "to": core.plan_label(to), "kind": kind, "by": "Paiement en ligne" if a["action"] == "billing.plan_activated" else a.get("actor"),
                     "mrr_change": round(price(to) - price(frm), 2)})
    count = lambda k: sum(1 for r in rows if r["kind"] == k)                           # noqa: E731
    return {"rows": rows, "upgrades": count("upgrade"), "downgrades": count("downgrade"), "activations": count("activation"),
            "mrr_change": round(sum(r["mrr_change"] for r in rows), 2)}


# ---------------------------------------------------------------------------
# Top / bottom croissance
# ---------------------------------------------------------------------------
def _growth(cur: float, prev: float) -> Optional[float]:
    if not cur and not prev:
        return None
    g = 100.0 if not prev else (cur - prev) / prev * 100
    return max(CAP[0], min(CAP[1], g))


@router.get("/api/admin/analytics/deep/growth")
def growth(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"), top: int = 5,
           token_data: TokenData = Depends(require_admin("analytics"))):
    start, end = _period(date_from, date_to)
    prev = start - (end - start)
    tenants = _tenants()
    now = _now()
    scans_c, scans_p = defaultdict(int), defaultdict(int)
    ca_c, ca_p = defaultdict(float), defaultdict(float)
    for v in _db.visits.find({"visit_time": {"$gte": prev, "$lt": end}}, {"_id": 0, "tenant_id": 1, "visit_time": 1, "amount_paid": 1}):
        at = _aware(v.get("visit_time"))
        if not at:
            continue
        cur = at >= start
        (scans_c if cur else scans_p)[v.get("tenant_id")] += 1
        (ca_c if cur else ca_p)[v.get("tenant_id")] += float(v.get("amount_paid") or 0)
    cards_c = AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": start, "$lt": end}})
    cards_p = AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": prev, "$lt": start}})
    scored, young, quiet = [], 0, 0
    for t in tenants:
        tid = t["id"]
        if AC.standing_of(t, now) in ("resilie", "non_converti"):
            continue
        if (_aware(t.get("created_at")) or now) > prev:
            young += 1
            continue
        if scans_c[tid] + scans_p[tid] < MIN_ACTIVITY and cards_c.get(tid, 0) + cards_p.get(tid, 0) < MIN_ACTIVITY:
            quiet += 1
            continue
        parts = {"scans": _growth(scans_c[tid], scans_p[tid]), "cartes": _growth(cards_c.get(tid, 0), cards_p.get(tid, 0)),
                 "ca": _growth(ca_c[tid], ca_p[tid])}
        vals = [v for v in parts.values() if v is not None]
        if not vals:
            quiet += 1
            continue
        scored.append({"id": tid, "name": t.get("name") or "—", "city": t.get("city") or "", "score": round(sum(vals) / len(vals)),
                       "parts": {k: (round(v) if v is not None else None) for k, v in parts.items()},
                       "values": {"scans": [scans_p[tid], scans_c[tid]], "cartes": [cards_p.get(tid, 0), cards_c.get(tid, 0)],
                                  "ca": [round(ca_p[tid], 2), round(ca_c[tid], 2)]}})
    scored.sort(key=lambda r: -r["score"])
    top = max(1, min(20, int(top)))
    # Few businesses ranked: split them in two halves, so « bottom » is never
    # empty and no business is in both lists.
    k = min(top, (len(scored) + 1) // 2)
    best = scored[:k]
    worst = list(reversed(scored[k:]))[:top]
    return {"top": best, "bottom": worst, "eligible": len(scored), "too_young": young, "too_quiet": quiet,
            "rules": {"min_age_days": (end - start).days * 2, "min_activity": MIN_ACTIVITY, "cap": list(CAP)},
            "period": {"from": _iso(start), "to": _iso(end), "previous_from": _iso(prev)}}


# ---------------------------------------------------------------------------
# Carte des commerces
# ---------------------------------------------------------------------------
@router.get("/api/admin/analytics/deep/map")
def commerces_map(token_data: TokenData = Depends(require_admin("analytics"))):
    from services import communes
    now = _now()
    snap = {r["id"]: r for r in AC.snapshot(now)}
    points, missing = [], []
    budget = GEO_FETCH_PER_CALL
    for t in _tenants():
        r = snap.get(t["id"], {})
        lat, lng = t.get("lat", t.get("latitude")), t.get("lng", t.get("longitude"))
        source = "adresse"
        if lat is None or lng is None:
            pos = communes.position_for(t.get("postal_code"), t.get("city"), fetch=False)
            if not pos and budget > 0 and (t.get("postal_code") or t.get("city")):
                budget -= 1
                pos = communes.position_for(t.get("postal_code"), t.get("city"), fetch=True)
            if pos:
                lat, lng = pos
                source = "code postal" if t.get("postal_code") else "ville"
        standing = AC.standing_of(t, now)
        row = {"id": t["id"], "name": t.get("name") or "—", "city": t.get("city") or "", "postal_code": t.get("postal_code") or "",
               "standing": standing, "standing_label": AC.STANDING_LABELS[standing], "status": r.get("status"),
               "status_label": r.get("status_label"), "plan": r.get("plan"), "clients": r.get("clients", 0)}
        if lat is None or lng is None:
            missing.append(row)
        else:
            points.append({**row, "lat": float(lat), "lng": float(lng), "source": source})
    return {"points": points, "missing": missing}
