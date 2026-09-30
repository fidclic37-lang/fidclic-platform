"""
Super admin › Insights — built to the approved mockup (« Insights »).

Every business on FidClic is checked, day by day, against four rules. The
card texts of the mockup say what each one means; the numbers are the
defaults, and the super admin can change them (platform_settings,
key « insight_rules »):

    Opportunité        new cards this month ≥ opportunity_min % of the plan's
                       monthly card limit (60 %) — « approchent de leur limite
                       de cartes »
    Upgrade potentiel  cards OR push notifications this month ≥ upgrade_min %
                       of the plan's limit (80 %) — « utilisent plus de 80 %
                       de leur quota ». Takes over from Opportunité.
    À surveiller       no notification delivered for watch_days days (30),
                       for a business at least that old — « sans notification
                       depuis 30 jours »
    Risque             visits over the last 30 days down by risk_drop % (30)
                       or more against the 30 days before, when those had at
                       least risk_min_visits visits (10) — « ont fortement
                       diminué leur activité »

The quotas are the ones FidClic enforces (calendar month, plans_public), so
the figures match what the merchant sees on his own usage page.
Growth (En croissance / Stables / En baisse) compares the same two 30-day
windows, ± growth_band % (10).

Because every rule is computed from dated facts (visits, cards, deliveries),
the trend chart and the « vs période précédente » deltas re-run the rules on
past days — no snapshot table to keep.
"""
from __future__ import annotations

import csv
import io
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC

router = APIRouter(tags=["admin"])
_db = None

RULES_KEY = "insight_rules"
DEFAULT_RULES = {"opportunity_min": 60, "upgrade_min": 80, "risk_drop": 30, "risk_min_visits": 10,
                 "watch_days": 30, "growth_band": 10}
TYPES = [("opportunite", "Opportunité", "Opportunités", "commerces approchent de leur limite de cartes"),
         ("surveiller", "À surveiller", "À surveiller", "commerces sans notification depuis {watch} jours"),
         ("risque", "Risque", "Risque", "commerces ont fortement diminué leur activité"),
         ("upgrade", "Upgrade potentiel", "Upgrade potentiel", "commerces utilisent plus de {upgrade} % de leur quota")]
TYPE_LABEL = {k: l for k, l, _, _ in TYPES}
PRIORITY_LABEL = {"haute": "Haute", "moyenne": "Moyenne"}
MAX_DAYS = 366
CACHE_SECONDS = 60
_cache: Dict[Any, Any] = {}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def rules() -> Dict[str, Any]:
    doc = (_db.platform_settings.find_one({"key": RULES_KEY}, {"_id": 0}) or {}).get("value") or {}
    return {**DEFAULT_RULES, **{k: v for k, v in doc.items() if k in DEFAULT_RULES}}


def _day(v: Any) -> Optional[date]:
    d = AC._aware(v)
    return d.date() if d else None


def _daily(coll: str, field: str, match: Dict[str, Any], start: datetime, end: datetime) -> Dict[str, Dict[date, int]]:
    """Count documents per business and per day between start and end."""
    m = {**match, field: {"$gte": start, "$lt": end}}
    out: Dict[str, Dict[date, int]] = defaultdict(lambda: defaultdict(int))
    try:
        for r in _db[coll].aggregate([{"$match": m}, {"$group": {
                "_id": {"t": "$tenant_id", "d": {"$dateToString": {"format": "%Y-%m-%d", "date": f"${field}"}}}, "n": {"$sum": 1}}}]):
            out[r["_id"]["t"]][date.fromisoformat(r["_id"]["d"])] += r["n"]
    except Exception:                     # a store without $dateToString: count in Python
        out.clear()
        for r in _db[coll].find(m, {"_id": 0, "tenant_id": 1, field: 1}):
            d = _day(r.get(field))
            if d:
                out[r.get("tenant_id")][d] += 1
    return out


def _period(date_from: Optional[str], date_to: Optional[str]):
    today = _now().date()
    end = _day(date_to) or today
    end = min(end, today)
    start = _day(date_from) or end - timedelta(days=29)
    if start > end:
        start = end - timedelta(days=29)
    if (end - start).days >= MAX_DAYS:
        start = end - timedelta(days=MAX_DAYS - 1)
    return start, end


class _Board:
    """Evaluates the rules for every business on any day of the window."""

    def __init__(self, start: date, end: date):
        import server as core
        self.r = rules()
        span = (end - start).days + 1
        # The previous period (for the deltas) and 60 days of visits before it.
        self.base = start - timedelta(days=span + 61)
        self.end = end
        t0 = datetime.combine(self.base, datetime.min.time(), tzinfo=timezone.utc)
        t1 = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
        self.tenants = [t for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}) if not t.get("suspended_at")]
        self.limits = {t["id"]: core.features_for(t) for t in self.tenants}
        self.next_plan = {t["id"]: core.NEXT_PLAN.get(core._canonical_plan(t.get("plan"))) for t in self.tenants}
        self.plan_labels = core.PLAN_LABELS
        n = (end - self.base).days + 1
        self.n = n
        series = {
            "visits": _daily("visits", "visit_time", {}, t0, t1),
            "cards": _daily("customers", "created_at", {}, t0, t1),
            "push": _daily("delivery_log", "timestamp", {"channel": "web_push", "result.sent": {"$gt": 0}}, t0, t1),
            "notif": _daily("delivery_log", "timestamp", {"result.sent": {"$gt": 0}}, t0, t1),
        }
        self.prefix: Dict[str, Dict[str, List[int]]] = {}
        for key, per in series.items():
            self.prefix[key] = {}
            for tid, days in per.items():
                acc, p = 0, [0] * (n + 1)
                for i in range(n):
                    acc += days.get(self.base + timedelta(days=i), 0)
                    p[i + 1] = acc
                self.prefix[key][tid] = p
        self.last_notif = {r["_id"]: r["at"] for r in _db.delivery_log.aggregate([
            {"$match": {"result.sent": {"$gt": 0}}}, {"$group": {"_id": "$tenant_id", "at": {"$max": "$timestamp"}}}])}

    def _sum(self, key: str, tid: str, a: int, b: int) -> int:
        """Total of days a..b (indexes, inclusive), clipped to the window."""
        p = self.prefix[key].get(tid)
        if not p:
            return 0
        a, b = max(0, a), min(self.n - 1, b)
        return p[b + 1] - p[a] if b >= a else 0

    def evaluate(self, t: Dict[str, Any], d: date) -> Optional[Dict[str, Any]]:
        created = _day(t.get("created_at")) or self.base
        if created > d:
            return None
        tid, r, i = t["id"], self.r, (d - self.base).days
        ms = (d.replace(day=1) - self.base).days
        lim = self.limits[tid]
        lc, lp = int(lim.get("new_cards_per_month") or 0), int(lim.get("push_per_month") or 0)
        cards, push = self._sum("cards", tid, ms, i), self._sum("push", tid, ms, i)
        pc = cards / lc * 100 if lc else None
        pp = push / lp * 100 if lp else None
        v30, vprev = self._sum("visits", tid, i - 29, i), self._sum("visits", tid, i - 59, i - 30)
        change = (v30 - vprev) / vprev * 100 if vprev else (100.0 if v30 else 0.0)
        wd = int(r["watch_days"])
        quiet = (d - created).days >= wd and self._sum("notif", tid, i - wd + 1, i) == 0
        found = []
        use = max(x for x in (pc, pp, -1) if x is not None)
        if use >= r["upgrade_min"]:
            found.append("upgrade")
        elif pc is not None and pc >= r["opportunity_min"]:
            found.append("opportunite")
        if vprev >= r["risk_min_visits"] and change <= -r["risk_drop"]:
            found.append("risque")
        if quiet:
            found.append("surveiller")
        growth = "croissance" if change >= r["growth_band"] else "baisse" if change <= -r["growth_band"] else "stable"
        return {"types": found, "growth": growth, "cards": cards, "cards_limit": lc, "cards_pct": pc, "push": push,
                "push_limit": lp, "push_pct": pp, "change": change, "v30": v30}

    def day(self, d: date) -> Dict[str, Dict[str, Any]]:
        out = {}
        for t in self.tenants:
            e = self.evaluate(t, d)
            if e is not None:
                out[t["id"]] = e
        return out


def _pct(x: float) -> str:
    return f"{round(x)} %"


def _row(b: _Board, t: Dict[str, Any], snap: Dict[str, Any], e: Dict[str, Any], kind: str, today: date) -> Dict[str, Any]:
    nf = lambda n: f"{n:,}".replace(",", " ")          # noqa: E731
    if kind in ("upgrade", "opportunite"):
        use_push = kind == "upgrade" and (e["push_pct"] or -1) > (e["cards_pct"] or -1)
        details = (f"Notifications : {nf(e['push'])} / {nf(e['push_limit'])} ({_pct(e['push_pct'])})" if use_push
                   else f"Cartes : {nf(e['cards'])} / {nf(e['cards_limit'])} ({_pct(e['cards_pct'])})")
        level = max(x for x in (e["cards_pct"], e["push_pct"], 0) if x is not None)
        if kind == "upgrade":
            nxt = b.next_plan.get(t["id"])
            reco = f"Proposer l'offre {b.plan_labels.get(nxt, nxt)}" if nxt else "Revoir les conditions de la franchise"
            prio = "haute"
        else:
            reco, prio = "Proposer un upgrade", "moyenne"
        severity = level
    elif kind == "risque":
        details = f"{round(e['change'])} % de visites (30 derniers jours)"
        reco, prio, severity = "Contacter le commerce", "haute", -e["change"]
    else:
        last = _day(b.last_notif.get(t["id"]))
        days = (today - last).days if last else None
        details = f"Aucune notification depuis {days} jours" if days is not None else "Aucune notification envoyée"
        reco = "Relancer une campagne"
        prio = "haute" if days is None or days >= 2 * int(b.r["watch_days"]) else "moyenne"
        severity = days if days is not None else 10 ** 6
    return {"id": f"{t['id']}:{kind}", "tenant_id": t["id"], "name": snap.get("name") or t.get("name") or "—",
            "logo": snap.get("logo"), "sector": snap.get("sector") or "", "city": snap.get("city") or "",
            "plan": snap.get("plan"), "type": kind, "type_label": TYPE_LABEL[kind], "details": details,
            "recommendation": reco, "priority": prio, "priority_label": PRIORITY_LABEL[prio], "severity": severity}


def _compute(start: date, end: date) -> Dict[str, Any]:
    key = (start, end, tuple(sorted(rules().items())))
    now = time.time()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    b = _Board(start, end)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    cur, prev = b.day(end), b.day(prev_end)
    snaps = {s["id"]: s for s in AC.snapshot()}
    by_id = {t["id"]: t for t in b.tenants}
    rows = [_row(b, by_id[tid], snaps.get(tid, {}), e, k, end) for tid, e in cur.items() for k in e["types"]]
    rows.sort(key=lambda r: (r["priority"] != "haute", -r["severity"], r["name"].lower()))

    def count(ev, k):
        return sum(1 for e in ev.values() if k in e["types"])

    # Trend: every day of the window (a point every few days on long windows).
    step = max(1, span // 45)
    trend = []
    for off in list(range(0, span, step)) + ([span - 1] if (span - 1) % step else []):
        d = start + timedelta(days=off)
        ev = cur if d == end else b.day(d)
        trend.append({"day": d.isoformat(), **{k: count(ev, k) for k, _, _, _ in TYPES}})

    def growth(ev, g):
        return sum(1 for e in ev.values() if e["growth"] == g)

    def delta(a, bb):
        return AC._delta(a, bb)

    upg_cur = sum(1 for e in cur.values() if {"upgrade", "opportunite"} & set(e["types"]))
    upg_prev = sum(1 for e in prev.values() if {"upgrade", "opportunite"} & set(e["types"]))
    kpis = [
        {"key": "analyses", "label": "Commerces analysés", "value": len(cur), "delta": delta(len(cur), len(prev))},
        {"key": "croissance", "label": "En croissance", "value": growth(cur, "croissance"), "delta": delta(growth(cur, "croissance"), growth(prev, "croissance"))},
        {"key": "stable", "label": "Stables", "value": growth(cur, "stable"), "delta": delta(growth(cur, "stable"), growth(prev, "stable"))},
        {"key": "baisse", "label": "En baisse", "value": growth(cur, "baisse"), "delta": delta(growth(cur, "baisse"), growth(prev, "baisse"))},
        {"key": "upgrade", "label": "Opportunités d'upgrade", "value": upg_cur, "delta": delta(upg_cur, upg_prev)},
    ]
    counts = {k: count(cur, k) for k, _, _, _ in TYPES}
    total = sum(counts.values())
    r = b.r
    cards = [{"key": k, "label": plural, "count": counts[k],
              "sub": sub.format(watch=int(r["watch_days"]), upgrade=round(r["upgrade_min"]))} for k, _, plural, sub in TYPES]
    distribution = [{"key": k, "label": plural if k != "upgrade" else l, "count": counts[k],
                     "pct": round(counts[k] / total * 100) if total else 0} for k, l, plural, _ in TYPES]
    per_sector: Dict[str, int] = defaultdict(int)
    for row in rows:
        per_sector[row["sector"]] += 1
    unnamed = per_sector.pop("", 0) + per_sector.pop("Autres", 0)
    top = sorted(per_sector.items(), key=lambda kv: (-kv[1], kv[0]))
    sectors = [{"label": s, "count": n} for s, n in top[:6]]
    rest = unnamed + sum(n for _, n in top[6:])          # sector not given, or beyond the top 6: one « Autres »
    if rest:
        sectors.append({"label": "Autres", "count": rest})
    for s in sectors:
        s["pct"] = round(s["count"] / len(rows) * 100) if rows else 0
    out = {"period": {"from": start.isoformat(), "to": end.isoformat()}, "rules": r, "cards": cards,
           "kpis": kpis,
           "distribution": distribution, "total": total, "trend": trend, "sectors": sectors, "counts": counts,
           "rows": rows, "sector_options": sorted({row["sector"] for row in rows if row["sector"]})}
    _cache.clear()
    _cache[key] = (now + CACHE_SECONDS, out)
    return out


def _pick(rows: List[Dict[str, Any]], kind: str, sector: str, ids: str = "") -> List[Dict[str, Any]]:
    if ids.strip():
        wanted = {i for i in ids.split(",") if i}
        return [r for r in rows if r["id"] in wanted]
    return [r for r in rows if (not kind or r["type"] == kind) and (not sector or r["sector"] == sector)]


@router.get("/api/admin/insights/board")
def board(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
          type: str = "opportunite", sector: str = "", page: int = 1, per_page: int = 10,
          token_data: TokenData = Depends(require_admin("insights"))):
    start, end = _period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    data = _compute(start, end)
    kind = type if type in TYPE_LABEL else "opportunite"
    rows = _pick(data["rows"], kind, sector)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    total = len(rows)
    return {**{k: v for k, v in data.items() if k != "rows"}, "type": kind,
            "rows": rows[(page - 1) * per_page: page * per_page], "rows_total": total, "page": page,
            "pages": max(1, -(-total // per_page)), "per_page": per_page}


@router.get("/api/admin/insights/export")
def export(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
           type: str = "", sector: str = "", ids: str = "", token_data: TokenData = Depends(require_admin("insights"))):
    start, end = _period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    rows = _pick(_compute(start, end)["rows"], type if type in TYPE_LABEL else "", sector, ids)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Commerce", "Secteur", "Ville", "Plan", "Insight", "Détails", "Recommandation", "Priorité"])
    for r in rows:
        w.writerow([r["name"], r["sector"], r["city"], (r["plan"] or {}).get("label", ""), r["type_label"], r["details"],
                    r["recommendation"], r["priority_label"]])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="insights.csv"'})


class RulesIn(BaseModel):
    opportunity_min: float = Field(..., gt=0, le=100)
    upgrade_min: float = Field(..., gt=0, le=100)
    risk_drop: float = Field(..., gt=0, le=100)
    risk_min_visits: int = Field(10, ge=0, le=100000)
    watch_days: int = Field(30, ge=1, le=365)
    growth_band: float = Field(10, ge=0, le=100)


@router.get("/api/admin/insights/rules")
def get_rules(token_data: TokenData = Depends(require_admin("insights"))):
    return rules()


@router.put("/api/admin/insights/rules")
def put_rules(body: RulesIn, token_data: TokenData = Depends(require_admin("insights"))):
    if body.opportunity_min >= body.upgrade_min:
        raise HTTPException(status_code=400, detail="Le seuil « Opportunité » doit être plus petit que le seuil « Upgrade potentiel ».")
    _db.platform_settings.update_one({"key": RULES_KEY}, {"$set": {"key": RULES_KEY, "value": body.dict(), "updated_at": _now(),
                                                                   "updated_by": token_data.email}}, upsert=True)
    _cache.clear()
    return rules()
