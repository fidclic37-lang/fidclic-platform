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


def _in_portfolio_at(t: Dict[str, Any], at: datetime, now: datetime) -> bool:
    """Was the business « en essai » or « abonné » at that date? Rebuilt from
    the dates we keep: sign-up, résiliation, end of an unconverted trial,
    suspension."""
    created = _aware(t.get("created_at")) or now
    if created >= at:
        return False
    res = _aware(t.get("resiliated_at"))
    if res and res < at:
        return False
    if AC.standing_of(t, now) == "non_converti":
        end = _aware(t.get("trial_ends_at"))
        if end and end < at:
            return False
    sus = _aware(t.get("suspended_at"))
    return not (sus and sus < at)


def _kpis(tenants, start, end) -> List[Dict[str, Any]]:
    """The Dashboard's figures (user, 2026-10-01): Commerces = en essai +
    abonnés only (a trial that ends without a subscription leaves it),
    Impayé (stopped paying or suspended), clients finaux, cartes actives,
    chiffre d'affaires total, MRR."""
    import server as core
    now = _now()
    prev = start - (end - start)
    B = _buckets(start, end)
    stand = {t["id"]: AC.standing_of(t, now) for t in tenants}

    def cum(coll, match, field="created_at"):
        at = lambda t: _db[coll].count_documents({**match, field: {"$lt": t}})       # noqa: E731
        return at(end), at(start), [at(b) for _, b in B]

    out = []
    essai = sum(1 for v in stand.values() if v == "essai")
    abonne = sum(1 for v in stand.values() if v == "abonne")
    value = essai + abonne
    then = lambda at: sum(1 for t in tenants if _in_portfolio_at(t, at, now))      # noqa: E731
    live = end >= now - timedelta(minutes=5)          # the period ends today: its last point is today's figure
    series = [then(min(b, now)) for _, b in B]
    if series and live:
        series[-1] = value
    out.append({"key": "commerces", "value": value, "delta": _delta(value if live else then(end), then(start)),
                "series": series, "breakdown": {"essai": essai, "abonne": abonne}})

    impayes = [t for t in tenants if stand[t["id"]] == "impaye"]
    out.append({"key": "impaye", "value": len(impayes), "delta": None, "series": [],
                "suspendus": sum(1 for t in impayes if t.get("suspended_at")),
                "mrr_at_stake": round(sum(core.tenant_price(t) for t in impayes))})

    for key, (cur, old, series) in (("clients", cum("customers", LIVE)), ("cartes", cum("customers", {**LIVE, "pass_issued": True}))):
        out.append({"key": key, "value": cur, "delta": _delta(cur, old), "series": series})

    # Chiffre d'affaires total: what the businesses' customers spent (their
    # visits) — the same figure as Analytics.
    amounts = [(_aware(v.get("visit_time")), float(v.get("amount_paid") or 0))
               for v in _db.visits.find({"visit_time": {"$gte": prev, "$lt": end}}, {"_id": 0, "visit_time": 1, "amount_paid": 1})]
    ca = lambda a, b: round(sum(x for at, x in amounts if at and a <= at < b), 2)     # noqa: E731
    out.append({"key": "ca", "value": ca(start, end), "delta": _delta(ca(start, end), ca(prev, start)), "series": [ca(a, b) for a, b in B]})

    paying = [t for t in tenants if (t.get("subscription_status") or "") == "active" and not t.get("suspended_at") and not t.get("resiliated_at")]
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
    à risque, inactif at its end (weekly cards AND scans, the weaker
    decides), how many signed up, were résiliés, and whose trial ended
    without a subscription during it."""
    r = AC.rules()
    now = _now()
    win = timedelta(days=int(r["window_days"]))
    since = now - timedelta(weeks=weeks) - win
    cards, scans = defaultdict(list), defaultdict(list)
    for c in _db.customers.find({**LIVE, "created_at": {"$gte": since}}, {"_id": 0, "tenant_id": 1, "created_at": 1}):
        d = _aware(c.get("created_at"))
        if d:
            cards[c["tenant_id"]].append(d)
    for v in _db.visits.find({"visit_time": {"$gte": since}}, {"_id": 0, "tenant_id": 1, "visit_time": 1}):
        d = _aware(v.get("visit_time"))
        if d:
            scans[v.get("tenant_id")].append(d)
    stand = {t["id"]: AC.standing_of(t, now) for t in tenants}
    out = {"actif": [], "inactif": [], "a_risque": [], "nouveaux": [], "resilie": [], "non_converti": []}
    for k in range(weeks - 1, -1, -1):
        w_end = now - timedelta(weeks=k)
        w_start = w_end - timedelta(weeks=1)
        counts = {"actif": 0, "inactif": 0, "a_risque": 0}
        for t in tenants:
            created = _aware(t.get("created_at")) or now
            if created > w_end:
                continue
            res = _aware(t.get("resiliated_at"))
            if (res and res <= w_end) or (_aware(t.get("suspended_at")) and _aware(t["suspended_at"]) <= w_end):
                continue
            if stand[t["id"]] == "non_converti" and (_aware(t.get("trial_ends_at")) or now) <= w_end:
                continue
            n_c = sum(1 for d in cards.get(t["id"], []) if w_end - win < d <= w_end)
            n_s = sum(1 for d in scans.get(t["id"], []) if w_end - win < d <= w_end)
            key = AC.status_of({"created_at": created}, n_c, r, w_end, n_s)["key"]
            if key in counts:
                counts[key] += 1
        for key in counts:
            out[key].append(counts[key])
        out["nouveaux"].append(sum(1 for t in tenants if w_start < (_aware(t.get("created_at")) or now) <= w_end))
        out["resilie"].append(sum(1 for t in tenants if _aware(t.get("resiliated_at")) and w_start < _aware(t["resiliated_at"]) <= w_end))
        out["non_converti"].append(sum(1 for t in tenants if stand[t["id"]] == "non_converti"
                                       and _aware(t.get("trial_ends_at")) and w_start < _aware(t["trial_ends_at"]) <= w_end))
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


def _status_cards(tenants, rows, hist, start, end, now, new_now, new_prev) -> List[Dict[str, Any]]:
    """Nouveaux, Actifs, Inactifs, À risque (the businesses still with us —
    en essai, abonnés, impayés not suspended), Résilié and Essais non
    convertis over the chosen period (user, 2026-10-01)."""
    usage = {k: sum(1 for r in rows if r["status"] == k) for k in ("actif", "inactif", "a_risque")}
    base = sum(usage.values())
    pct = lambda n: round(n / base * 100) if base else 0                   # noqa: E731
    four_weeks = lambda k: hist[k][-5] if len(hist[k]) >= 5 else 0          # noqa: E731
    prev = start - (end - start)
    res = [_aware(t.get("resiliated_at")) for t in tenants if t.get("resiliated_at")]
    res_in = sum(1 for d in res if d and start <= d < end)
    res_before = sum(1 for d in res if d and prev <= d < start)
    ended = []                      # trials that ended in the period: converted or not
    for t in tenants:
        te = _aware(t.get("trial_ends_at"))
        if te and start <= te < end:
            ended.append(AC.standing_of(t, now))
    lost = sum(1 for x in ended if x == "non_converti")
    won = sum(1 for x in ended if x in ("abonne", "impaye"))
    lost_before = sum(1 for t in tenants if AC.standing_of(t, now) == "non_converti" and _aware(t.get("trial_ends_at"))
                      and prev <= _aware(t["trial_ends_at"]) < start)
    return [
        {"key": "nouveaux", "value": new_now, "delta": _delta(new_now, new_prev), "bars": hist["nouveaux"]},
        {"key": "actif", "value": usage["actif"], "pct": pct(usage["actif"]), "delta": _delta(usage["actif"], four_weeks("actif")), "bars": hist["actif"]},
        {"key": "inactif", "value": usage["inactif"], "pct": pct(usage["inactif"]), "delta": _delta(usage["inactif"], four_weeks("inactif")), "bars": hist["inactif"]},
        {"key": "a_risque", "value": usage["a_risque"], "pct": pct(usage["a_risque"]), "delta": _delta(usage["a_risque"], four_weeks("a_risque")), "bars": hist["a_risque"]},
        {"key": "resilie", "value": res_in, "total": len(res), "delta": _delta(res_in, res_before), "bars": hist["resilie"]},
        {"key": "non_converti", "value": lost, "ended": len(ended), "converted": won,
         "conversion": round(won / (won + lost) * 100) if (won + lost) else None, "delta": _delta(lost, lost_before), "bars": hist["non_converti"]},
    ]


def _build(start: datetime, end: datetime, months: int, now: datetime) -> Dict[str, Any]:
    import server as core
    import models
    from features import admin_analytics as AN
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    rows = AC.snapshot(now)
    names = {t["id"]: t.get("name") for t in tenants}
    total = len(rows)
    hist = _status_history(tenants)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month = (month_start - timedelta(days=1)).replace(day=1)
    new_now = sum(1 for t in tenants if (_aware(t.get("created_at")) or now) >= month_start)
    new_prev = sum(1 for t in tenants if prev_month <= (_aware(t.get("created_at")) or now) < month_start)
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
        "status_cards": _status_cards(tenants, rows, hist, start, end, now, new_now, new_prev),
        "opportunities": _opportunities(tenants, rows),
        "top": [{"id": r["id"], "name": r["name"], "logo": r["logo"], "sector": r["sector"], "city": r["city"], "clients": r["clients"],
                 "visits": r["visits"], "plan": r["plan"]} for r in top],
        "activity": _activity(names),
    }


# ---------------------------------------------------------------------------
# Every figure opens the businesses behind it, with what is needed to call or
# write to them (user, 2026-10-01).
# ---------------------------------------------------------------------------
LISTS = {
    "commerces": "Commerces — en essai et abonnés", "essai": "Commerces en essai", "abonne": "Commerces abonnés",
    "impaye": "Commerces impayés", "nouveaux": "Nouveaux commerces ce mois-ci", "actif": "Commerces actifs",
    "inactif": "Commerces inactifs", "a_risque": "Commerces à risque", "resilie": "Commerces résiliés",
    "non_converti": "Essais non convertis", "clients": "Clients finaux par commerce", "cartes": "Cartes actives par commerce",
    "ca": "Chiffre d'affaires par commerce", "mrr": "MRR par commerce",
}


@router.get("/api/admin/dashboard/list/{key}")
def dashboard_list(key: str, date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
                   token_data: TokenData = Depends(require_admin("dashboard"))):
    import server as core
    from fastapi import HTTPException
    if key not in LISTS:
        raise HTTPException(status_code=404, detail="Liste inconnue.")
    start, end = _period(date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None)
    now = _now()
    tenants = {t["id"]: t for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0})}
    snap = {r["id"]: r for r in AC.snapshot(now)}
    owners = {u["tenant_id"]: u for u in _db.users.find({"role": "business_owner", "tenant_id": {"$in": list(tenants)}},
                                                        {"_id": 0, "tenant_id": 1, "email": 1, "first_name": 1, "last_name": 1, "phone": 1})}
    stand = {tid: AC.standing_of(t, now) for tid, t in tenants.items()}
    month0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    metric: Dict[str, Any] = {}
    metric_label = None
    if key == "commerces":
        ids = [i for i, v in stand.items() if v in ("essai", "abonne")]
    elif key in ("essai", "abonne", "impaye"):
        ids = [i for i, v in stand.items() if v == key]
    elif key == "nouveaux":
        ids = [i for i, t in tenants.items() if (_aware(t.get("created_at")) or now) >= month0]
    elif key in ("actif", "inactif", "a_risque"):
        ids = [i for i, r in snap.items() if r["status"] == key and i in tenants]
    elif key == "resilie":
        ids = [i for i, t in tenants.items() if _aware(t.get("resiliated_at")) and start <= _aware(t["resiliated_at"]) < end]
    elif key == "non_converti":
        ids = [i for i, t in tenants.items() if stand[i] == "non_converti" and _aware(t.get("trial_ends_at"))
               and start <= _aware(t["trial_ends_at"]) < end]
    else:
        ids = [i for i in tenants if stand[i] not in ("resilie", "non_converti")]
        if key == "clients":
            metric, metric_label = {i: snap.get(i, {}).get("clients", 0) for i in ids}, "Clients"
        elif key == "cartes":
            metric = AC._count_by_tenant("customers", {**LIVE, "pass_issued": True})
            metric_label = "Cartes actives"
        elif key == "ca":
            per: Dict[str, float] = defaultdict(float)
            for v in _db.visits.find({"visit_time": {"$gte": start, "$lt": end}}, {"_id": 0, "tenant_id": 1, "amount_paid": 1}):
                per[v.get("tenant_id")] += float(v.get("amount_paid") or 0)
            metric, metric_label = {i: round(per.get(i, 0), 2) for i in ids}, "Chiffre d'affaires"
        elif key == "mrr":
            ids = [i for i in ids if (tenants[i].get("subscription_status") or "") == "active" and not tenants[i].get("suspended_at")]
            metric, metric_label = {i: core.tenant_price(tenants[i]) for i in ids}, "€ / mois"
    rows = []
    for i in ids:
        t, r, o = tenants[i], snap.get(i, {}), owners.get(i, {})
        rows.append({
            "id": i, "name": t.get("name") or "—", "logo": r.get("logo"), "sector": r.get("sector") or AC._sector(t.get("sector")),
            "city": t.get("city") or "", "plan": r.get("plan") or {"key": core._canonical_plan(t.get("plan")), "label": core.plan_label(t.get("plan"))},
            "status": r.get("status"), "status_label": r.get("status_label"), "standing": stand[i], "standing_label": AC.STANDING_LABELS[stand[i]],
            "owner": " ".join(x for x in (o.get("first_name"), o.get("last_name")) if x), "email": o.get("email") or t.get("email") or "",
            "phone": t.get("phone") or o.get("phone") or "", "clients": r.get("clients", 0),
            "cards_week": r.get("cards_week"), "scans_week": r.get("scans_week"), "created_at": _iso(t.get("created_at")),
            "trial_ends_at": _iso(t.get("trial_ends_at")), "price": core.tenant_price(t),
            "suspended_at": _iso(t.get("suspended_at")), "suspended_reason": t.get("suspended_reason"),
            "resiliated_at": _iso(t.get("resiliated_at")), "resiliation_reason": t.get("resiliation_reason"),
            "metric": metric.get(i, 0) if metric_label else None,
        })
    if metric_label:
        rows.sort(key=lambda x: -(x["metric"] or 0))
    elif key in ("resilie",):
        rows.sort(key=lambda x: x["resiliated_at"] or "", reverse=True)
    elif key in ("essai", "non_converti"):
        rows.sort(key=lambda x: x["trial_ends_at"] or "")
    elif key in ("actif", "inactif", "a_risque"):
        rows.sort(key=lambda x: min(x["cards_week"] or 0, x["scans_week"] or 0))
    else:
        rows.sort(key=lambda x: x["name"].lower())
    return {"key": key, "title": LISTS[key], "rows": rows, "metric_label": metric_label,
            "period": {"from": start.date().isoformat(), "to": (end - timedelta(seconds=1)).date().isoformat()}}
