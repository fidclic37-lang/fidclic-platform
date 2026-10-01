"""
Super admin › Analytics — « Utilisation des plans », taken from the
« Gestion des abonnements » mockup (2026-09-30). The user asked for only
these parts of it, added to Analytics:
- three figures: cartes actives, notifications envoyées, géolocalisation
  activée;
- three tabs: « Utilisation par commerce », « Répartition par plan »,
  « Renouvellements », with the filters, the CSV export and the pages.

What each number is (the same definitions as the rest of FidClic):
- Carte active: a customer card that came at least once in the last 12 months
  (or joined within them) — what the plans count (« Cartes clients (clients
  actifs) », server.count_active_customers). The table shows it against the
  plan's limit, as the business's own page does.
- Notification envoyée: a push that really left the server (delivery_log,
  web_push, sent > 0) — what the plans count. The table shows this month's
  against the monthly limit.
- Géolocalisation activée: the business's plan includes it AND the business
  switched it on (tenant.geo_enabled). In the table, « inclus, non activé »
  is told apart from « pas dans le plan ».
- IA / Wallet / Multi-sites: what the business's plan gives it.
- Statut: the Commerces page's (actif / inactif / à risque / suspendu).
- Prochain renouvellement: the end of the current billing period, or of the
  trial (plan_limits.next_cycle).
"""
from __future__ import annotations

import csv
import io
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from auth import TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC
from features import admin_dashboard as AD

router = APIRouter(tags=["admin"])
_db = None
CACHE_SECONDS = 60
_cache: Dict[str, Any] = {}
PLAN_COLORS = {"silver": "#F59E0B", "gold": "#2F6BFF", "vip": "#DB2777", "franchise": "#8B5CF6"}
RENEW_KIND = {"renouvellement": "Renouvellement", "fin_essai": "Fin d'essai", "fin_abonnement": "Fin d'abonnement",
              "retard": "Paiement en retard"}
PER_PAGE = (10, 25, 50, 100)


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _plan_color(key: str) -> str:
    import server as core
    return (core.custom_plans().get(key) or {}).get("color") or PLAN_COLORS.get(key, "#0EA5E9")


def _plan_order(key: str) -> int:
    return {"silver": 0, "gold": 1, "vip": 2, "franchise": 3}.get(key, 4)


# ---------------------------------------------------------------------------
# Active cards
# ---------------------------------------------------------------------------
def _cards() -> List[Dict[str, Any]]:
    return list(_db.customers.find(AC.LIVE, {"_id": 0, "id": 1, "tenant_id": 1, "created_at": 1, "last_visit_date": 1}))


def _active_now(c: Dict[str, Any], since: datetime) -> bool:
    """server.count_active_customers, for one card: dormant only when a date
    proves it."""
    lv, cr = AC._aware(c.get("last_visit_date")), AC._aware(c.get("created_at"))
    if lv:
        return lv >= since
    return cr is None or cr >= since


def active_cards_at(cards: List[Dict[str, Any]], tenants: set, at: datetime, now: datetime) -> int:
    """Cards active at `at`. Today it reads the cards' last visit; for a date
    in the past it reads the visits of the year before that date."""
    import models
    since = at - timedelta(days=models.ACTIVE_WINDOW_DAYS)
    if at >= now - timedelta(minutes=1):
        return sum(1 for c in cards if c.get("tenant_id") in tenants and _active_now(c, since))
    seen = {v.get("customer_id") for v in _db.visits.find({"visit_time": {"$gte": since, "$lt": at}}, {"_id": 0, "customer_id": 1})}
    n = 0
    for c in cards:
        if c.get("tenant_id") not in tenants:
            continue
        cr, lv = AC._aware(c.get("created_at")), AC._aware(c.get("last_visit_date"))
        if cr and cr >= at:
            continue                                   # not there yet
        if cr is None and lv is None:
            n += 1                                     # no date at all: counted, as today
        elif (cr and cr >= since) or c.get("id") in seen:
            n += 1
    return n


def _push(match: Dict[str, Any]) -> Dict[str, Any]:
    return {"channel": "web_push", "result.sent": {"$gt": 0}, **match}


def _push_count(start: datetime, end: datetime, tenants: set) -> int:
    return sum(1 for d in _db.delivery_log.find(_push({"timestamp": {"$gte": start, "$lt": end}}), {"_id": 0, "tenant_id": 1})
               if d.get("tenant_id") in tenants)


def _geo_on(t: Dict[str, Any], f: Dict[str, Any]) -> str:
    if not f.get("geo_proximity"):
        return "none"
    return "on" if t.get("geo_enabled") else "off"


# ---------------------------------------------------------------------------
# One row per business
# ---------------------------------------------------------------------------
def _renewal(t: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    from features import plan_limits as PL
    status = (t.get("subscription_status") or "").lower()
    if t.get("suspended_at") or t.get("resiliated_at") or status in ("canceled", "cancelled", "incomplete_expired"):
        return None
    trial = status in ("trialing", "onboarding") or (not status and t.get("trial_ends_at"))
    at = PL.next_cycle(t, now)
    if trial:
        kind = "fin_essai"
    elif status in ("past_due", "unpaid"):
        kind = "retard"
    elif t.get("subscription_cancel_at_period_end"):
        kind = "fin_abonnement"
    else:
        kind = "renouvellement"
    return {"at": AC._iso(at), "days": (at.date() - now.date()).days, "kind": kind, "kind_label": RENEW_KIND[kind]}


def _use(used: int, limit: Any) -> Dict[str, Any]:
    lim = int(limit or 0)
    return {"used": used, "limit": lim or None, "pct": round(used / lim * 100) if lim > 0 else None}


def rows(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Every business with its usage — kept a minute, the list and its
    exports read the same rows."""
    now = now or _now()
    hit = _cache.get("rows")
    if hit and hit[0] > time.time():
        return hit[1]
    import server as core
    import models
    snap = {r["id"]: r for r in AC.snapshot(now)}
    tenants = {t["id"]: t for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0})}
    since = now - timedelta(days=models.ACTIVE_WINDOW_DAYS)
    active: Dict[str, int] = defaultdict(int)
    for c in _cards():
        if _active_now(c, since):
            active[c.get("tenant_id")] += 1
    push: Dict[str, int] = defaultdict(int)
    for d in _db.delivery_log.find(_push({"timestamp": {"$gte": _month_start(now)}}), {"_id": 0, "tenant_id": 1}):
        push[d.get("tenant_id")] += 1
    out = []
    for tid, t in tenants.items():
        s = snap.get(tid) or {}
        f = core.features_for(t)
        key = core._canonical_plan(t.get("plan"))
        status = (t.get("subscription_status") or "").lower()
        cards, pushes = _use(active[tid], f.get("max_customers")), _use(push[tid], f.get("push_per_month"))
        near = max([u["pct"] for u in (cards, pushes) if u["pct"] is not None] or [0])
        out.append({
            "id": tid, "name": t.get("name") or "—", "sector": s.get("sector") or AC._sector(t.get("sector")), "city": t.get("city") or "",
            "logo": s.get("logo"), "plan": {"key": key, "label": core.plan_label(key), "color": _plan_color(key)},
            "trial": status in ("trialing", "onboarding") or (not status and bool(t.get("trial_ends_at"))),
            "subscription_status": status or None,
            "status": s.get("status") or "a_risque", "status_label": s.get("status_label") or AC.STATUS_LABELS["a_risque"],
            "cards": cards, "push": pushes, "near": near,
            "ai": (f.get("ai_level") or "none") != "none", "ai_level": f.get("ai_level") or "none",
            "geo": _geo_on(t, f), "wallet": bool(f.get("wallet")), "multi": bool(f.get("multi_branch")),
            "renewal": _renewal(t, now), "price": core.tenant_price(t),
            "payment": (t.get("payment_method_cache") or {}).get("card"),
        })
    out.sort(key=lambda r: r["name"].lower())
    _cache["rows"] = (time.time() + CACHE_SECONDS, out)
    return out


def _yes(v: str) -> Optional[bool]:
    return {"oui": True, "non": False}.get((v or "").lower())


def _filter(rs: List[Dict[str, Any]], q="", plan="", sector="", city="", status="", ia="", geo="", wallet="", multi="",
            usage="", renew="", sub="") -> List[Dict[str, Any]]:
    from features import plan_limits as PL
    out = rs
    if q:
        f = q.strip().lower()
        out = [r for r in out if f in r["name"].lower() or f in r["city"].lower() or f in r["sector"].lower()]
    if plan:
        out = [r for r in out if r["plan"]["key"] == plan]
    if sector:
        out = [r for r in out if r["sector"] == sector]
    if city:
        out = [r for r in out if r["city"] == city]
    if status:
        out = [r for r in out if r["status"] == status]
    for k, v in (("ai", ia), ("wallet", wallet), ("multi", multi)):
        want = _yes(v)
        if want is not None:
            out = [r for r in out if r[k] == want]
    if geo in ("on", "off", "none"):
        out = [r for r in out if r["geo"] == geo]
    if usage == "alerte":
        seuil = int(PL.settings().get("alert_threshold") or 80)
        out = [r for r in out if r["near"] >= seuil]
    elif usage == "atteinte":
        out = [r for r in out if r["near"] >= 100]
    if renew.isdigit():
        out = [r for r in out if r["renewal"] and r["renewal"]["days"] <= int(renew)]
    if sub == "payant":
        out = [r for r in out if r["subscription_status"] == "active"]
    elif sub == "essai":
        out = [r for r in out if r["trial"]]
    return out


def _options(rs: List[Dict[str, Any]]) -> Dict[str, Any]:
    plans = sorted({r["plan"]["key"]: r["plan"] for r in rs}.values(), key=lambda p: (_plan_order(p["key"]), p["label"]))
    return {"plans": [{"key": p["key"], "label": p["label"]} for p in plans],
            "sectors": sorted({r["sector"] for r in rs if r["sector"]}), "cities": sorted({r["city"] for r in rs if r["city"]}),
            "statuses": [{"key": k, "label": v} for k, v in AC.STATUS_LABELS.items()]}


SORTS = {
    "name": lambda r: r["name"].lower(), "plan": lambda r: (_plan_order(r["plan"]["key"]), r["name"].lower()),
    "cards": lambda r: r["cards"]["pct"] if r["cards"]["pct"] is not None else -1,
    "push": lambda r: r["push"]["pct"] if r["push"]["pct"] is not None else -1,
    "renewal": lambda r: r["renewal"]["at"] if r["renewal"] else "9999",
}


# ---------------------------------------------------------------------------
# The figures
# ---------------------------------------------------------------------------
def figures(start: datetime, end: datetime) -> Dict[str, Any]:
    import server as core
    now = _now()
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    ids = {t["id"] for t in tenants}
    cards = _cards()
    at = min(end, now)
    cur, old = active_cards_at(cards, ids, at, now), active_cards_at(cards, ids, start, now)
    prev = start - (end - start)
    sent, sent_before = _push_count(start, end, ids), _push_count(prev, start, ids)
    geo = sum(1 for t in tenants if _geo_on(t, core.features_for(t)) == "on")
    days = (end - start).days
    return {"cards": {"value": cur, "delta": AC._delta(cur, old)},
            "push": {"value": sent, "delta": AC._delta(sent, sent_before), "month": 27 <= days <= 31},
            "geo": {"value": geo, "pct": round(geo / len(tenants) * 100) if tenants else 0, "total": len(tenants)}}


@router.get("/api/admin/analytics/usage")
def usage_figures(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                  token_data: TokenData = Depends(require_admin("analytics"))):
    start, end = AD._period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    return figures(start, end)


# ---------------------------------------------------------------------------
# Tab 1 — Utilisation par commerce
# ---------------------------------------------------------------------------
@router.get("/api/admin/analytics/usage/commerces")
def usage_commerces(q: str = "", plan: str = "", sector: str = "", city: str = "", status: str = "", ia: str = "", geo: str = "",
                    wallet: str = "", multi: str = "", usage: str = "", renew: str = "", sub: str = "", sort: str = "name",
                    page: int = 1, per_page: int = 10, token_data: TokenData = Depends(require_admin("analytics"))):
    rs = rows()
    out = _filter(rs, q, plan, sector, city, status, ia, geo, wallet, multi, usage, renew, sub)
    out = sorted(out, key=SORTS.get(sort.lstrip("-"), SORTS["name"]), reverse=sort.startswith("-"))
    per_page = per_page if per_page in PER_PAGE else 10
    pages = max(1, -(-len(out) // per_page))
    page = max(1, min(int(page), pages))
    return {"rows": out[(page - 1) * per_page: page * per_page], "total": len(out), "all": len(rs), "page": page,
            "per_page": per_page, "pages": pages, "options": _options(rs)}


# ---------------------------------------------------------------------------
# Tab 2 — Répartition par plan
# ---------------------------------------------------------------------------
def plan_split() -> Dict[str, Any]:
    import server as core
    from features import plan_limits as PL
    rs = rows()
    seuil = int(PL.settings().get("alert_threshold") or 80)
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rs:
        by[r["plan"]["key"]].append(r)
    total = len(rs)
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else None      # noqa: E731
    out = []
    for key in sorted(by, key=lambda k: (_plan_order(k), k)):
        g = by[key]
        f = core.get_plan_features(key)
        paying = [r for r in g if r["subscription_status"] == "active"]
        out.append({"key": key, "label": core.plan_label(key), "color": _plan_color(key), "price": f.get("price"),
                    "on_quote": key == "franchise", "count": len(g), "pct": round(len(g) / total * 100) if total else 0,
                    "paying": len(paying), "trials": sum(1 for r in g if r["trial"]), "mrr": round(sum(r["price"] for r in paying), 2),
                    "cards": sum(r["cards"]["used"] for r in g), "cards_limit": f.get("max_customers") or None,
                    "cards_pct": avg([r["cards"]["pct"] for r in g if r["cards"]["pct"] is not None]),
                    "push": sum(r["push"]["used"] for r in g), "push_limit": f.get("push_per_month") or None,
                    "push_pct": avg([r["push"]["pct"] for r in g if r["push"]["pct"] is not None]),
                    "near": sum(1 for r in g if r["near"] >= seuil),
                    "ai_level": f.get("ai_level") or "none", "geo": bool(f.get("geo_proximity")), "wallet": bool(f.get("wallet")),
                    "multi": bool(f.get("multi_branch")), "geo_on": sum(1 for r in g if r["geo"] == "on")})
    return {"rows": out, "total": total, "threshold": seuil, "mrr": round(sum(p["mrr"] for p in out), 2)}


@router.get("/api/admin/analytics/usage/plans")
def usage_plans(token_data: TokenData = Depends(require_admin("analytics"))):
    return plan_split()


# ---------------------------------------------------------------------------
# Tab 3 — Renouvellements
# ---------------------------------------------------------------------------
def _renewals(rs: List[Dict[str, Any]], within: str = "30", kind: str = "") -> List[Dict[str, Any]]:
    out = [r for r in rs if r["renewal"]]
    if within.isdigit():
        out = [r for r in out if r["renewal"]["days"] <= int(within)]
    if kind in RENEW_KIND:
        out = [r for r in out if r["renewal"]["kind"] == kind]
    return sorted(out, key=lambda r: r["renewal"]["at"])


@router.get("/api/admin/analytics/usage/renewals")
def usage_renewals(within: str = "30", kind: str = "", q: str = "", plan: str = "", sector: str = "", city: str = "", status: str = "",
                   page: int = 1, per_page: int = 10, token_data: TokenData = Depends(require_admin("analytics"))):
    rs = rows()
    base = [r for r in rs if r["renewal"]]
    out = _renewals(_filter(rs, q, plan, sector, city, status), within, kind)
    week = [r for r in base if r["renewal"]["days"] <= 7]
    month = [r for r in base if r["renewal"]["days"] <= 30]
    # The amounts are what paying subscriptions will bill — the same base as the MRR.
    due = lambda rs: round(sum(r["price"] for r in rs if r["renewal"]["kind"] == "renouvellement" and r["subscription_status"] == "active"), 2)   # noqa: E731
    summary = {"week": len(week), "week_amount": due(week), "month": len(month), "month_amount": due(month),
               "trials": sum(1 for r in base if r["renewal"]["kind"] == "fin_essai" and r["renewal"]["days"] <= 7),
               "late": sum(1 for r in base if r["renewal"]["kind"] == "retard"),
               "ending": sum(1 for r in base if r["renewal"]["kind"] == "fin_abonnement")}
    per_page = per_page if per_page in PER_PAGE else 10
    pages = max(1, -(-len(out) // per_page))
    page = max(1, min(int(page), pages))
    return {"rows": out[(page - 1) * per_page: page * per_page], "total": len(out), "page": page, "per_page": per_page, "pages": pages,
            "summary": summary, "kinds": [{"key": k, "label": v} for k, v in RENEW_KIND.items()], "options": _options(rs)}


# ---------------------------------------------------------------------------
# Export (CSV) — the tab on screen, with its filters, or the rows ticked
# ---------------------------------------------------------------------------
def _fr(d: Optional[str]) -> str:
    x = AC._aware(d)
    return x.strftime("%d/%m/%Y") if x else ""


def _lim(u: Dict[str, Any]) -> str:
    return str(u["limit"]) if u["limit"] else "illimité"


@router.get("/api/admin/analytics/usage/export")
def usage_export(tab: str = "commerces", ids: str = "", q: str = "", plan: str = "", sector: str = "", city: str = "", status: str = "",
                 ia: str = "", geo: str = "", wallet: str = "", multi: str = "", usage: str = "", renew: str = "", sub: str = "",
                 within: str = "30", kind: str = "", token_data: TokenData = Depends(require_admin("analytics"))):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    yn = lambda v: "Oui" if v else "Non"                             # noqa: E731
    geo_txt = {"on": "Activée", "off": "Incluse, non activée", "none": "Non incluse"}
    if tab == "plans":
        p = plan_split()
        w.writerow(["Plan", "Prix (€/mois)", "Commerces", "% du total", "Payants", "En essai", "MRR (€)", "Cartes actives",
                    "Utilisation moyenne des cartes (%)", "Notifications du mois", "Utilisation moyenne des notifications (%)",
                    f"Proches de la limite (≥ {p['threshold']} %)", "IA", "Géolocalisation", "Wallet", "Multi-sites"])
        for r in p["rows"]:
            w.writerow([r["label"], "sur devis" if r["on_quote"] else r["price"], r["count"], r["pct"], r["paying"], r["trials"], r["mrr"],
                        r["cards"], r["cards_pct"] if r["cards_pct"] is not None else "", r["push"],
                        r["push_pct"] if r["push_pct"] is not None else "", r["near"],
                        {"none": "Non", "basic": "Analyses de base", "advanced": "Analyses avancées"}.get(r["ai_level"], r["ai_level"]),
                        yn(r["geo"]), yn(r["wallet"]), yn(r["multi"])])
        name = "repartition-par-plan"
    else:
        rs = rows()
        if ids:
            keep = set(ids.split(","))
            out = [r for r in rs if r["id"] in keep]
        else:
            out = _filter(rs, q, plan, sector, city, status, ia, geo, wallet, multi, usage, renew, sub)
        if tab == "renewals":
            out = _renewals(out, within, kind) if not ids else [r for r in out if r["renewal"]]
            w.writerow(["Commerce", "Secteur", "Ville", "Plan", "Type", "Date", "Dans (jours)", "Montant (€/mois)", "Statut"])
            for r in out:
                w.writerow([r["name"], r["sector"], r["city"], r["plan"]["label"], r["renewal"]["kind_label"], _fr(r["renewal"]["at"]),
                            r["renewal"]["days"], r["price"], r["status_label"]])
            name = "renouvellements"
        else:
            w.writerow(["Commerce", "Secteur", "Ville", "Plan", "Statut", "Cartes actives", "Limite cartes", "Cartes (%)",
                        "Notifications du mois", "Limite notifications", "Notifications (%)", "IA", "Géolocalisation", "Wallet",
                        "Multi-sites", "Prochain renouvellement"])
            for r in out:
                w.writerow([r["name"], r["sector"], r["city"], r["plan"]["label"] + (" (essai)" if r["trial"] else ""), r["status_label"],
                            r["cards"]["used"], _lim(r["cards"]), r["cards"]["pct"] if r["cards"]["pct"] is not None else "",
                            r["push"]["used"], _lim(r["push"]), r["push"]["pct"] if r["push"]["pct"] is not None else "",
                            yn(r["ai"]), geo_txt[r["geo"]], yn(r["wallet"]), yn(r["multi"]),
                            _fr(r["renewal"]["at"]) if r["renewal"] else ""])
            name = "utilisation-par-commerce"
    day = _now().strftime("%Y-%m-%d")
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fidclic-{name}-{day}.csv"'})
