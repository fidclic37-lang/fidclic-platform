"""
Super admin › Dashboard — the whole platform at a glance. Built to the
approved « Dashboard » mockup; every figure is counted, nothing invented.

    GET /api/admin/dashboard?from=&to=&months=6

Figures compare the chosen period with the one just before it (same
length). Statuses come from features/admin_commerces (new cards a day).
« Opportunités IA » are rules, not a language model: each one names the
businesses it found.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from auth import require_role, TokenData
from features.platform_access import require_admin
from features import admin_commerces as AC

router = APIRouter(tags=["admin"])
_db = None
ADMIN = ["super_admin"]


def init(db):
    global _db
    _db = db
    # The dashboard counts the whole platform by date: without these, every
    # figure would scan the collection (the existing indexes start with tenant_id).
    for coll, field in (("visits", "visit_time"), ("customers", "created_at"), ("campaigns", "sent_at"),
                        ("delivery_log", "timestamp"), ("tenants", "created_at"), ("audit_logs", "ts")):
        try:
            db[coll].create_index([(field, -1)])
        except Exception:
            pass


_cache: Dict[Any, Any] = {}
CACHE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


_aware, _iso, _delta = AC._aware, AC._iso, AC._delta
LIVE = AC.LIVE


def _period(date_from: Optional[str], date_to: Optional[str]):
    end = _aware(date_to) + timedelta(days=1) if _aware(date_to) else _now()
    start = _aware(date_from) or end - timedelta(days=30)
    if start >= end:
        start = end - timedelta(days=30)
    return start, end


def _buckets(start: datetime, end: datetime, n: int = 8):
    step = (end - start) / n
    return [(start + step * i, start + step * (i + 1)) for i in range(n)]


def _subscription(t: Dict[str, Any]) -> str:
    """« essai » (trial / onboarding, as the Commerces page shows it),
    « abonne » (signed: a paid subscription that is running — the MRR's
    base) or « autre » (cancelled, unpaid, suspended, never subscribed)."""
    status = (t.get("subscription_status") or "").lower()
    if status in ("trialing", "onboarding") or (not status and t.get("trial_ends_at")):
        return "essai"
    if status == "active" and not t.get("suspended_at"):
        return "abonne"
    return "autre"


def _kpis(tenants, start, end) -> List[Dict[str, Any]]:
    """The Dashboard's figures (user, 2026-10-01): Commerces — with how many
    are in trial and how many have signed —, new businesses this month,
    clients finaux, cartes actives, chiffre d'affaires total, MRR."""
    import server as core
    from features import admin_analytics as AN
    now = _now()
    prev = start - (end - start)
    B = _buckets(start, end)
    live_t = {"is_active": {"$ne": False}}

    def cum(coll, match, field="created_at"):
        at = lambda t: _db[coll].count_documents({**match, field: {"$lt": t}})       # noqa: E731
        return at(end), at(start), [at(b) for _, b in B]

    out = []
    cur, old, series = cum("tenants", live_t)
    split = defaultdict(int)
    for t in tenants:
        split[_subscription(t)] += 1
    out.append({"key": "commerces", "value": cur, "delta": _delta(cur, old), "series": series,
                "breakdown": {"essai": split["essai"], "abonne": split["abonne"], "autre": split["autre"]}})

    # New businesses this calendar month, against the same days of last month.
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    p0 = (m0 - timedelta(days=1)).replace(day=1)
    p_end = min(p0 + (now - m0), m0)
    created = [d for d in (_aware(t.get("created_at")) for t in tenants) if d]
    months = AC.month_windows(now, 8)
    out.append({"key": "nouveaux", "value": sum(1 for d in created if d >= m0), "delta": _delta(sum(1 for d in created if d >= m0),
                                                                                                   sum(1 for d in created if p0 <= d < p_end)),
                "series": [sum(1 for d in created if a <= d < b) for a, b in months]})

    for key, (cur, old, series) in (("clients", cum("customers", LIVE)), ("cartes", cum("customers", {**LIVE, "pass_issued": True}))):
        out.append({"key": key, "value": cur, "delta": _delta(cur, old), "series": series})

    # Chiffre d'affaires total: what the businesses' customers spent (their
    # visits) — the same figure as Analytics.
    amounts = [(_aware(v.get("visit_time")), float(v.get("amount_paid") or 0))
               for v in _db.visits.find({"visit_time": {"$gte": prev, "$lt": end}}, {"_id": 0, "visit_time": 1, "amount_paid": 1})]
    ca = lambda a, b: round(sum(x for at, x in amounts if at and a <= at < b), 2)     # noqa: E731
    out.append({"key": "ca", "value": ca(start, end), "delta": _delta(ca(start, end), ca(prev, start)), "series": [ca(a, b) for a, b in B]})

    paying = [t for t in tenants if (t.get("subscription_status") or "") == "active" and not t.get("suspended_at")]
    mrr = round(sum(core.tenant_price(t) for t in paying))
    mrr_at = lambda at: round(sum(core.tenant_price(t) for t in paying if (_aware(t.get("created_at")) or at) < at))   # noqa: E731
    out.append({"key": "mrr", "value": mrr, "delta": _delta(mrr, mrr_at(start)), "series": [mrr_at(b) for _, b in B]})
    return out


def _evolution(months: int) -> List[Dict[str, Any]]:
    rows = []
    for a, b in AC.month_windows(_now(), months):
        rows.append({"month": a.strftime("%Y-%m"),
                     "commerces": _db.tenants.count_documents({"is_active": {"$ne": False}, "created_at": {"$lt": b}}),
                     "clients": _db.customers.count_documents({**LIVE, "created_at": {"$lt": b}}),
                     "visites": _db.visits.count_documents({"visit_time": {"$gte": a, "$lt": b}})})
    return rows


def _share(counter: Dict[str, int], labels: Optional[Dict[str, str]] = None, top: int = 7) -> List[Dict[str, Any]]:
    """The biggest `top` groups, then one « Autres » holding the rest and
    anything without a group — never two « Autres »."""
    rest = counter.get("Autres", 0)
    ranked = sorted(((k, v) for k, v in counter.items() if k != "Autres"), key=lambda kv: -kv[1])
    rest += sum(v for _, v in ranked[top:])
    items = ranked[:top] + ([("Autres", rest)] if rest else [])
    tot = sum(v for _, v in items) or 1
    return [{"key": k, "label": (labels or {}).get(k, k), "count": v, "pct": round(v / tot * 100)} for k, v in items if v]


def _status_history(tenants, weeks: int = 12) -> Dict[str, List[int]]:
    """Each of the last `weeks` weeks: how many businesses were actif,
    inactif, à risque at its end, and how many signed up during it."""
    r = AC.rules()
    now = _now()
    win = timedelta(days=int(r["window_days"]))
    since = now - timedelta(weeks=weeks) - win
    per = defaultdict(list)
    for c in _db.customers.find({**LIVE, "created_at": {"$gte": since}}, {"_id": 0, "tenant_id": 1, "created_at": 1}):
        d = _aware(c.get("created_at"))
        if d:
            per[c["tenant_id"]].append(d)
    out = {"actif": [], "inactif": [], "a_risque": [], "nouveaux": []}
    for k in range(weeks - 1, -1, -1):
        w_end = now - timedelta(weeks=k)
        counts = {"actif": 0, "inactif": 0, "a_risque": 0}
        for t in tenants:
            created = _aware(t.get("created_at")) or now
            if created > w_end or t.get("suspended_at"):
                continue
            n = sum(1 for d in per.get(t["id"], []) if w_end - win < d <= w_end)
            counts[AC.status_of({"created_at": created}, n, r, w_end)["key"]] += 1
        for key in counts:
            out[key].append(counts[key])
        out["nouveaux"].append(sum(1 for t in tenants if w_end - timedelta(weeks=1) < (_aware(t.get("created_at")) or now) <= w_end))
    return out


def _active_by_tenant(now: datetime) -> Dict[str, int]:
    """server.count_active_customers for every business in one pass: a
    customer is dormant only when a date proves it — last visit older than
    the window, or never came and joined before it."""
    import models
    since = now - timedelta(days=models.ACTIVE_WINDOW_DAYS)
    out: Dict[str, int] = defaultdict(int)
    for c in _db.customers.find(LIVE, {"_id": 0, "tenant_id": 1, "last_visit_date": 1, "created_at": 1}):
        lv, cr = _aware(c.get("last_visit_date")), _aware(c.get("created_at"))
        if (lv and lv < since) or (not lv and cr and cr < since):
            continue
        out[c.get("tenant_id")] += 1
    return out


def _opportunities(tenants, rows) -> List[Dict[str, Any]]:
    import server as core
    now = _now()
    by_id = {t["id"]: t for t in tenants}
    live = [t for t in tenants if not t.get("suspended_at")]
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    active_clients = _active_by_tenant(now)
    camps_month = AC._count_by_tenant("campaigns", {"sent_at": {"$gte": month_start}})
    near, upgrade = [], []
    for t in live:
        f = core.features_for(t)
        cap = int(f.get("max_customers") or 0)
        ratio = active_clients[t["id"]] / cap if cap else 0
        if ratio >= 0.8:
            near.append(t)
        camp_cap = int(f.get("campaigns_per_month") or 0)
        if core._canonical_plan(t.get("plan")) != "franchise" and (ratio >= 0.8 or (camp_cap and camps_month.get(t["id"], 0) >= 0.8 * camp_cap)):
            upgrade.append(t)
    recent = set(_db.campaigns.distinct("tenant_id", {"sent_at": {"$gte": now - timedelta(days=30)}}))
    silent = [t for t in live if t["id"] not in recent and (_aware(t.get("created_at")) or now) < now - timedelta(days=30)]
    cur = AC._count_by_tenant("visits", {"visit_time": {"$gte": now - timedelta(days=30)}})
    old = AC._count_by_tenant("visits", {"visit_time": {"$gte": now - timedelta(days=60), "$lt": now - timedelta(days=30)}})
    falling = [t for t in live if old.get(t["id"], 0) >= 10 and cur.get(t["id"], 0) < 0.7 * old[t["id"]]]
    ending = [t for t in live if (t.get("subscription_status") or "") == "trialing" and _aware(t.get("trial_ends_at"))
              and now <= _aware(t["trial_ends_at"]) <= now + timedelta(days=3)]
    asks = [by_id[r["tenant_id"]] for r in _db.upgrade_requests.find({"requested_plan": "franchise", "status": "pending"}, {"tenant_id": 1})
            if r.get("tenant_id") in by_id]
    items = [
        ("near_limit", f"commerce{'s' if len(near) != 1 else ''} approche{'nt' if len(near) != 1 else ''} de leur limite de cartes", near, "limit"),
        ("no_campaign", f"commerce{'s' if len(silent) != 1 else ''} sans campagne depuis 30 jours", silent, "campaign"),
        ("falling", f"commerce{'s' if len(falling) != 1 else ''} en baisse d'activité", falling, "falling"),
        ("upgrade", f"commerce{'s' if len(upgrade) != 1 else ''} peu{'vent' if len(upgrade) != 1 else 't'} passer au plan supérieur", upgrade, "upgrade"),
        ("trial_ending", f"essai{'s' if len(ending) != 1 else ''} se termine{'nt' if len(ending) != 1 else ''} dans 3 jours", ending, "trial"),
        ("franchise", f"demande{'s' if len(asks) != 1 else ''} d'offre Franchise en attente", asks, "franchise"),
    ]
    return [{"key": k, "label": f"{len(ts)} {label}", "count": len(ts), "icon": icon,
             "tenants": [{"id": t["id"], "name": t.get("name")} for t in ts[:50]]}
            for k, label, ts, icon in items if ts or k in ("near_limit", "no_campaign", "falling", "upgrade")]


def _activity(names: Dict[str, str], limit: int = 30) -> List[Dict[str, Any]]:
    now = _now()
    since = now - timedelta(days=30)
    ev = []
    for t in _db.tenants.find({"created_at": {"$gte": since}}, {"_id": 0, "id": 1, "name": 1, "created_at": 1}):
        ev.append({"kind": "signup", "title": "Nouveau commerce inscrit", "sub": t.get("name"), "at": t["created_at"], "tenant_id": t["id"]})
    for c in _db.campaigns.find({"sent_at": {"$gte": since}}, {"_id": 0, "tenant_id": 1, "sent_at": 1, "name": 1}).sort("sent_at", -1).limit(40):
        ev.append({"kind": "campaign", "title": "Campagne envoyée", "sub": names.get(c.get("tenant_id"), "—"), "at": c["sent_at"],
                   "tenant_id": c.get("tenant_id"), "detail": c.get("name")})
    words = {"admin.plan_change": ("plan", "Plan mis à jour"), "admin.franchise_terms": ("plan", "Offre Franchise appliquée"),
             "admin.commerce_suspend": ("suspend", "Suspension temporaire"), "admin.commerce_reactivate": ("reactivate", "Commerce réactivé"),
             "admin.commerce_create": ("signup", "Commerce ajouté par FidClic")}
    import models
    for a in _db.audit_logs.find({"action": {"$in": list(words)}, "ts": {"$gte": since}}, {"_id": 0}).sort("ts", -1).limit(40):
        kind, title = words[a["action"]]
        tid = a.get("target") or a.get("tenant_id")
        sub = names.get(tid, "—")
        if a["action"] == "admin.plan_change":
            m = a.get("meta") or {}
            sub = f"{sub} → {models.PLAN_LABELS.get(m.get('to'), m.get('to'))}"
        ev.append({"kind": kind, "title": title, "sub": sub, "at": a["ts"], "tenant_id": tid})
    for r in _db.upgrade_requests.find({"requested_plan": "franchise", "created_at": {"$gte": since}}, {"_id": 0}):
        ev.append({"kind": "request", "title": "Demande d'offre Franchise", "sub": r.get("tenant_name"), "at": r["created_at"],
                   "tenant_id": r.get("tenant_id")})
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in (day0, day0 - timedelta(days=1)):
        for tid, n in AC._count_by_tenant("customers", {**LIVE, "created_at": {"$gte": d, "$lt": d + timedelta(days=1)}}).items():
            if n >= 3:
                ev.append({"kind": "clients", "title": "Nouveaux clients", "sub": f"{n} nouveaux clients — {names.get(tid, '—')}",
                           "at": min(d + timedelta(days=1), now), "tenant_id": tid})
    ev.sort(key=lambda e: _aware(e["at"]) or now, reverse=True)
    return [{**e, "at": _iso(e["at"])} for e in ev[:limit]]


@router.get("/api/admin/dashboard")
def dashboard(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
              months: int = 6, token_data: TokenData = Depends(require_admin("dashboard"))):
    import server as core
    import models
    if not isinstance(date_from, (str, type(None))):
        date_from = None
    if not isinstance(date_to, (str, type(None))):
        date_to = None
    start, end = _period(date_from, date_to)
    now = _now()
    key = (start.date(), end.date(), 12 if int(months or 6) >= 12 else 6)
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    out = _build(start, end, key[2], now)
    _cache.clear()                       # one entry is enough: the page asks for one period at a time
    _cache[key] = (now + timedelta(seconds=CACHE_SECONDS), out)
    return out


def _build(start: datetime, end: datetime, months: int, now: datetime) -> Dict[str, Any]:
    import server as core
    import models
    from features import admin_analytics as AN
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    rows = AC.snapshot(now)
    names = {t["id"]: t.get("name") for t in tenants}
    total = len(rows)
    by_status = {k: sum(1 for r in rows if r["status"] == k) for k in ("actif", "inactif", "a_risque", "suspendu")}
    hist = _status_history(tenants)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month = (month_start - timedelta(days=1)).replace(day=1)
    new_now = sum(1 for t in tenants if (_aware(t.get("created_at")) or now) >= month_start)
    new_prev = sum(1 for t in tenants if prev_month <= (_aware(t.get("created_at")) or now) < month_start)
    four_weeks = lambda k: hist[k][-5] if len(hist[k]) >= 5 else 0          # noqa: E731
    plans = defaultdict(int)
    for r in rows:
        plans[r["plan"]["key"]] += 1
    plan_labels = {**{k: v for k, v in models.PLAN_LABELS.items()}, "essai": "Essai gratuit"}
    order = ["silver", "gold", "vip", "franchise", "essai"]
    plan_rows = [{"key": k, "label": plan_labels.get(k, k), "count": plans.get(k, 0),
                  "pct": round(plans.get(k, 0) / total * 100) if total else 0} for k in order if plans.get(k)]
    top = sorted(rows, key=lambda r: -r["clients"])[:5]
    return {
        "period": {"from": start.date().isoformat(), "to": (end - timedelta(seconds=1)).date().isoformat()},
        "kpis": _kpis(tenants, start, end),
        # « Évolution de la plateforme » and the sector donut moved to Analytics;
        # three of Analytics' sections are shown here too (user, 2026-10-01).
        "total": total, "plans": plan_rows,
        "cities": AN.cities(tenants), "revenue": AN.revenue_by_plan(tenants, start, end), "sources": AN.sources(start, end),
        "status_cards": [
            {"key": "nouveaux", "value": new_now, "delta": _delta(new_now, new_prev), "bars": hist["nouveaux"]},
            {"key": "actif", "value": by_status["actif"], "pct": round(by_status["actif"] / total * 100) if total else 0,
             "delta": _delta(by_status["actif"], four_weeks("actif")), "bars": hist["actif"]},
            {"key": "inactif", "value": by_status["inactif"], "pct": round(by_status["inactif"] / total * 100) if total else 0,
             "delta": _delta(by_status["inactif"], four_weeks("inactif")), "bars": hist["inactif"]},
            {"key": "a_risque", "value": by_status["a_risque"], "pct": round(by_status["a_risque"] / total * 100) if total else 0,
             "delta": _delta(by_status["a_risque"], four_weeks("a_risque")), "bars": hist["a_risque"]},
        ],
        "opportunities": _opportunities(tenants, rows),
        "top": [{"id": r["id"], "name": r["name"], "logo": r["logo"], "sector": r["sector"], "city": r["city"], "clients": r["clients"],
                 "visits": r["visits"], "plan": r["plan"]} for r in top],
        "activity": _activity(names),
    }
