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

import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query

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
                        ("delivery_log", "timestamp"), ("tenants", "created_at"), ("audit_logs", "ts"),
                        # « Activité du jour » reads one day of these, all businesses at once
                        ("automation_log", "sent_at"), ("referral_redemptions", "created_at")):
        try:
            db[coll].create_index([(field, -1)])
        except Exception:
            pass


_cache: Dict[Any, Any] = {}
CACHE_SECONDS = 60
# One build at a time per process: the page can ask twice at once, and without
# this both misses start their own build (the cache is only written at the end)
# — the work was done twice and the two calls queued behind each other.
_build_lock = threading.Lock()
# The cache above lives inside one process. On Vercel every cold function has
# its own empty one, so an admin opening the page nearly always paid for a full
# rebuild. This keeps the same single entry in Mongo, where the next function
# finds it. Never fatal: any failure here just means building again.
SHARED_DOC = "admin_dashboard"


def _key_text(key) -> str:
    """Mongo has no date-only type: the key travels as text."""
    return "|".join(str(p) for p in key)


def _shared_get(key, now):
    try:
        doc = _db.cache_entries.find_one({"_id": SHARED_DOC})
    except Exception:
        return None
    if not doc or doc.get("key") != _key_text(key):
        return None
    at = _aware(doc.get("expires_at"))
    return doc.get("payload") if at and at > now else None


def invalidate() -> None:
    """Forget both layers — for a caller that has just changed the data and
    wants the next answer rebuilt instead of waiting out the 60 seconds."""
    _cache.clear()
    try:
        _db.cache_entries.delete_one({"_id": SHARED_DOC})
    except Exception:
        pass


def _shared_put(key, payload, now):
    try:
        _db.cache_entries.replace_one(
            {"_id": SHARED_DOC},
            {"_id": SHARED_DOC, "key": _key_text(key), "payload": payload,
             "expires_at": now + timedelta(seconds=CACHE_SECONDS)},
            upsert=True)
    except Exception:
        pass            # a cache that cannot be written is not an error


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


def _impact_by_tenant(ranges: List[Tuple[datetime, datetime]], at: datetime) -> Dict[str, List[Dict[str, Any]]]:
    """Impact FidClic (user, 2026-11-11): each shop's CA FidClic over each
    [a, b) — read from the shop's daily register exactly as its owner reads
    it (features/visit_days.span_many). Every shop with a visit in the span,
    deleted, suspended or résiliée too: the figure is what FidClic brought."""
    from features import visit_days as VD
    if not ranges:
        return {}
    lo, hi = min(a for a, _ in ranges), max(b for _, b in ranges)
    tids = sorted(t for t in _db.visits.distinct("tenant_id", {"visit_time": {"$gte": lo, "$lt": hi}}) if t)
    closed = [(a, b - timedelta(microseconds=1)) for a, b in ranges]      # [a, b) — the register's spans end inclusive
    out: Dict[str, List[Dict[str, Any]]] = {}
    for tid in tids:
        try:
            out[tid] = [t.impact() for t in VD.span_many(tid, None, closed, at=at)]
        except Exception:                                   # noqa: BLE001 — one shop never breaks the page
            out[tid] = [{"revenue": 0.0, "visits": 0} for _ in ranges]
    return out


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
        """The running total at each point of the curve.

        It used to ask Mongo to count from scratch for every point — one
        count_documents per bucket, ten round trips per figure, and the two
        figures below made twenty. Now: one count for what came before the
        period, then the dates inside it, and the curve is added up here.
        Two queries, the same numbers."""
        base = _db[coll].count_documents({**match, field: {"$lt": start}})
        inside = sorted(d for d in (_aware(x.get(field)) for x in _db[coll].find(
            {**match, field: {"$gte": start, "$lt": end}}, {"_id": 0, field: 1})) if d)
        series, i, running = [], 0, base
        for _, b in B:
            while i < len(inside) and inside[i] < b:
                i += 1
                running += 1
            series.append(running)
        # the last bucket ends at `end`, so its total is the period's own
        return (series[-1] if series else base), base, series

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
                "series": series, "breakdown": {"essai": essai, "abonne": abonne},
                # « N actifs sur M inscrits » (user, 2026-11-09): M = every
                # registered business, the donut's total.
                "registered": len(tenants)})

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

    # Impact FidClic (user, 2026-11-11): what FidClic brought, every shop —
    # the same CA FidClic each owner reads, added up.
    per = _impact_by_tenant([(start, end), (prev, start)] + list(B), now)
    tot = lambda i: round(sum(v[i]["revenue"] for v in per.values()), 2)      # noqa: E731
    out.append({"key": "impact", "value": tot(0), "delta": _delta(tot(0), tot(1)), "series": [tot(2 + i) for i in range(len(B))]})

    paying = [t for t in tenants if (t.get("subscription_status") or "") == "active" and not t.get("suspended_at") and not t.get("resiliated_at")]
    mrr = round(sum(core.tenant_price(t) for t in paying))
    mrr_at = lambda at: round(sum(core.tenant_price(t) for t in paying if (_aware(t.get("created_at")) or at) < at))   # noqa: E731
    out.append({"key": "mrr", "value": mrr, "delta": _delta(mrr, mrr_at(start)), "series": [mrr_at(b) for _, b in B]})
    return out


def _evolution(months: int) -> List[Dict[str, Any]]:
    """« Évolution de la plateforme »: per calendar month, how many businesses
    and clients existed by its end and how many visits it saw.

    It used to count each of those from scratch, month by month — three
    count_documents per month, thirty-six round trips over a year, and this is
    what made /api/admin/analytics/global take 2,3 s. Mongo now returns each
    month's own count in one pass per collection; the running totals are added
    up here. Five queries instead of thirty-six, the same numbers.
    """
    wins = AC.month_windows(_now(), months)
    if not wins:
        return []
    first, last = wins[0][0], wins[-1][1]

    def per_month(coll: str, match: Dict[str, Any], field: str) -> List[int]:
        sums = {f"m{i}": {"$sum": {"$cond": [{"$and": [{"$gte": [f"${field}", a]},
                                                       {"$lt": [f"${field}", b]}]}, 1, 0]}}
                for i, (a, b) in enumerate(wins)}
        rows = list(_db[coll].aggregate([{"$match": {**match, field: {"$gte": first, "$lt": last}}},
                                         {"$group": {"_id": None, **sums}}]))
        row = rows[0] if rows else {}
        return [int(row.get(f"m{i}") or 0) for i in range(len(wins))]

    def running(coll: str, match: Dict[str, Any], field: str = "created_at") -> List[int]:
        """The total at the end of each month: what already existed before the
        first one, plus every month since. The months are contiguous, so this
        lands on the same figure as counting `field < end` each time."""
        total = _db[coll].count_documents({**match, field: {"$lt": first}})
        out = []
        for n in per_month(coll, match, field):
            total += n
            out.append(total)
        return out

    commerces = running("tenants", {"is_active": {"$ne": False}})
    clients = running("customers", LIVE)
    visites = per_month("visits", {}, "visit_time")
    return [{"month": a.strftime("%Y-%m"), "commerces": commerces[i],
             "clients": clients[i], "visites": visites[i]}
            for i, (a, _) in enumerate(wins)]


def _share(counter: Dict[str, int], labels: Optional[Dict[str, str]] = None, top: int = 7) -> List[Dict[str, Any]]:
    """The biggest `top` groups, then one « Autres » holding the rest and
    anything without a group — never two « Autres »."""
    rest = counter.get("Autres", 0)
    ranked = sorted(((k, v) for k, v in counter.items() if k != "Autres"), key=lambda kv: -kv[1])
    rest += sum(v for _, v in ranked[top:])
    items = ranked[:top] + ([("Autres", rest)] if rest else [])
    tot = sum(v for _, v in items) or 1
    return [{"key": k, "label": (labels or {}).get(k, k), "count": v, "pct": round(v / tot * 100)} for k, v in items if v]


def _window_counts(coll: str, match: Dict[str, Any], field: str,
                   ranges: List[Any]) -> Dict[str, List[int]]:
    """For each business, how many rows fall inside each (after, up_to] window.

    Mongo counts them. This used to read every customer and every visit of the
    last three months into this process — tens of thousands of documents — to
    end up with these few numbers. The windows are the exact same instants, so
    the counts are the same to the millisecond.

    The boundaries keep their timezone: the driver converts them to UTC on the
    way out, and the dates they are compared against were written the same way.
    """
    sums = {f"w{i}": {"$sum": {"$cond": [{"$and": [{"$gt": [f"${field}", a]},
                                                   {"$lte": [f"${field}", b]}]}, 1, 0]}}
            for i, (a, b) in enumerate(ranges)}
    earliest = min(a for a, _ in ranges)
    rows = _db[coll].aggregate([{"$match": {**match, field: {"$gt": earliest}}},
                                {"$group": {"_id": "$tenant_id", **sums}}])
    return {r["_id"]: [int(r.get(f"w{i}") or 0) for i in range(len(ranges))] for r in rows}


def _status_history(tenants, weeks: int = 12) -> Dict[str, List[int]]:
    """Each of the last `weeks` weeks: how many businesses were actif,
    à risque, inactif at its end (weekly cards AND scans, the weaker
    decides), how many signed up, were résiliés, and whose trial ended
    without a subscription during it."""
    r = AC.rules()
    now = _now()
    win = timedelta(days=int(r["window_days"]))
    spans = [(now - timedelta(weeks=k + 1), now - timedelta(weeks=k)) for k in range(weeks - 1, -1, -1)]
    # What each week's status is read from: the rolling window ending that week.
    ranges = [(w_end - win, w_end) for _, w_end in spans]
    cards = _window_counts("customers", LIVE, "created_at", ranges)
    scans = _window_counts("visits", {}, "visit_time", ranges)
    none = [0] * len(ranges)
    stand = {t["id"]: AC.standing_of(t, now) for t in tenants}
    out = {"actif": [], "inactif": [], "a_risque": [], "nouveaux": [], "resilie": [], "non_converti": []}
    for i, (w_start, w_end) in enumerate(spans):
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
            n_c = cards.get(t["id"], none)[i]
            n_s = scans.get(t["id"], none)[i]
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
    for t in _db.tenants.find({"created_at": {"$gte": since}, "onboarding_status": {"$nin": ["verify", "company", "plan"]}, "deleted_at": None},
                              {"_id": 0, "id": 1, "name": 1, "created_at": 1}):
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
    shared = _shared_get(key, now)       # built by another function, still fresh
    if shared is not None:
        _cache.clear()                   # one entry is enough: the page asks for one period at a time
        _cache[key] = (now + timedelta(seconds=CACHE_SECONDS), shared)
        return shared
    with _build_lock:
        # Whoever held the lock may have just built exactly this.
        again = _cache.get(key)
        if again and again[0] > _now():
            return again[1]
        out = _build(start, end, key[2], now)
        done = _now()
        _cache.clear()
        _cache[key] = (done + timedelta(seconds=CACHE_SECONDS), out)
        _shared_put(key, out, done)
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


# Where each registered business stands, in the order of its life with FidClic
# (user, 2026-11-09, option 3): the « Répartition » donut sums to the same total
# as the tile's « sur M inscrits », and each slice opens its businesses.
STANDINGS = [("essai", "Essai en cours", "essai"), ("abonne", "Abonné", "abonne"), ("impaye", "Impayé", "impaye"),
             ("non_converti", "Non converti", "tous_non_converti"), ("resilie", "Résilié", "tous_resilie")]


def _statuses(tenants, rows, now: datetime) -> List[Dict[str, Any]]:
    ids = {r["id"] for r in rows}
    count = defaultdict(int)
    for t in tenants:
        if t["id"] in ids:
            count[AC.standing_of(t, now)] += 1
    total = sum(count.values())
    return [{"key": k, "label": label, "count": count[k], "pct": round(count[k] / total * 100) if total else 0, "list": lst}
            for k, label, lst in STANDINGS if count.get(k)]


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
        "total": total, "plans": plan_rows, "statuses": _statuses(tenants, rows, now),
        "cities": AN.cities(tenants), # every shop's visits, deleted ones too: the donut = the CA figure (2026-11-11)
        "revenue": AN.revenue_by_plan(list(_db.tenants.find({}, {"_id": 0})), start, end), "sources": AN.sources(start, end),
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
    "impact": "Impact FidClic par commerce",
    "essai_7j": "Essais qui se terminent sous 7 jours", "limite": "Commerces à 90 % de leur limite",
    # the tile's « sur M inscrits » and the standing donut's slices (2026-11-09):
    # every business today, whenever its trial ended or it left
    "inscrits": "Tous les commerces inscrits", "tous_non_converti": "Essais non convertis (tous)",
    "tous_resilie": "Commerces résiliés (tous)",
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
    # CA and Impact FidClic count every shop's visits: their lists show every
    # shop — deleted, suspended, résiliée, trial over (user, 2026-11-11)
    every = key in ("ca", "impact")
    tenants = {t["id"]: t for t in _db.tenants.find({} if every else {"is_active": {"$ne": False}}, {"_id": 0})}
    snap = {r["id"]: r for r in AC.snapshot(now)}
    owners = {u["tenant_id"]: u for u in _db.users.find({"role": "business_owner", "tenant_id": {"$in": list(tenants)}},
                                                        {"_id": 0, "tenant_id": 1, "email": 1, "first_name": 1, "last_name": 1, "phone": 1})}
    stand = {tid: AC.standing_of(t, now) for tid, t in tenants.items()}
    month0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    metric: Dict[str, Any] = {}
    extra: Dict[str, Any] = {}
    metric_label = None
    if key == "commerces":
        ids = [i for i, v in stand.items() if v in ("essai", "abonne")]
    elif key == "inscrits":
        ids = [i for i in tenants if i in snap]
    elif key in ("tous_non_converti", "tous_resilie"):
        ids = [i for i, v in stand.items() if v == key[5:] and i in snap]
    elif key in ("essai", "abonne", "impaye"):
        ids = [i for i, v in stand.items() if v == key]
    elif key == "essai_7j":
        ids = [i for i, t in tenants.items() if stand[i] == "essai" and _aware(t.get("trial_ends_at"))
               and now <= _aware(t["trial_ends_at"]) <= now + timedelta(days=7)]
    elif key == "limite":
        from features import analytics_usage as U
        near = {r["id"]: r["near"] for r in U.rows(now) if (r.get("near") or 0) >= 90}
        ids = [i for i in near if i in tenants]
        metric, metric_label = near, "Limite utilisée (%)"
    elif key == "nouveaux":
        ids = [i for i, t in tenants.items() if (_aware(t.get("created_at")) or now) >= month0]
    elif key in ("actif", "inactif", "a_risque"):
        ids = [i for i, r in snap.items() if r["status"] == key and i in tenants]
    elif key == "resilie":
        ids = [i for i, t in tenants.items() if _aware(t.get("resiliated_at")) and start <= _aware(t["resiliated_at"]) < end]
    elif key == "non_converti":
        ids = [i for i, t in tenants.items() if stand[i] == "non_converti" and _aware(t.get("trial_ends_at"))
               and start <= _aware(t["trial_ends_at"]) < end]
    elif every:
        ids = list(tenants)
        if key == "ca":
            per: Dict[str, float] = defaultdict(float)
            for v in _db.visits.find({"visit_time": {"$gte": start, "$lt": end}}, {"_id": 0, "tenant_id": 1, "amount_paid": 1}):
                per[v.get("tenant_id")] += float(v.get("amount_paid") or 0)
            metric, metric_label = {i: round(per.get(i, 0), 2) for i in ids}, "Chiffre d'affaires"
        else:
            imp = _impact_by_tenant([(start, end)], now)
            metric = {i: (imp.get(i) or [{"revenue": 0.0}])[0]["revenue"] for i in ids}
            extra = {i: (imp.get(i) or [{"visits": 0}])[0].get("visits", 0) for i in ids}
            metric_label = "CA FidClic"
    else:
        ids = [i for i in tenants if stand[i] not in ("resilie", "non_converti")]
        if key == "clients":
            metric, metric_label = {i: snap.get(i, {}).get("clients", 0) for i in ids}, "Clients"
        elif key == "cartes":
            metric = AC._count_by_tenant("customers", {**LIVE, "pass_issued": True})
            metric_label = "Cartes actives"
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
            "deleted": t.get("is_active") is False,
            **({"visits": extra.get(i, 0)} if key == "impact" else {}),
        })
    if metric_label:
        rows.sort(key=lambda x: -(x["metric"] or 0))
    elif key in ("resilie",):
        rows.sort(key=lambda x: x["resiliated_at"] or "", reverse=True)
    elif key in ("essai", "non_converti", "essai_7j"):
        rows.sort(key=lambda x: x["trial_ends_at"] or "")
    elif key in ("actif", "inactif", "a_risque"):
        rows.sort(key=lambda x: min(x["cards_week"] or 0, x["scans_week"] or 0))
    else:
        rows.sort(key=lambda x: x["name"].lower())
    return {"key": key, "title": LISTS[key], "rows": rows, "metric_label": metric_label,
            "period": {"from": start.date().isoformat(), "to": (end - timedelta(seconds=1)).date().isoformat()}}


# ---------------------------------------------------------------------------
# « À suivre aujourd'hui » (user, 2026-10-01): a section of its own, under
# the figures — À faire aujourd'hui, Encaissements, Support, CRM. Each block
# only for a member who may open that module.
# ---------------------------------------------------------------------------
def _can(token_data: TokenData, module: str) -> bool:
    if token_data.role == "super_admin":
        return True
    from features import platform_access as PA
    return bool(((PA.perms_for(token_data.email) or {}).get(module) or {}).get("view"))


def _todo(now: datetime, tenants: List[Dict[str, Any]], token_data: TokenData) -> List[Dict[str, Any]]:
    stand = {t["id"]: AC.standing_of(t, now) for t in tenants}
    week = now + timedelta(days=7)
    items = []
    ending = [t for t in tenants if stand[t["id"]] == "essai" and _aware(t.get("trial_ends_at")) and now <= _aware(t["trial_ends_at"]) <= week]
    items.append({"key": "essai_7j", "label": "Essais qui se terminent sous 7 jours", "count": len(ending), "icon": "clock", "tone": "violet",
                  "action": {"list": "essai_7j"}})
    late = sum(1 for v in stand.values() if v == "impaye")
    items.append({"key": "impaye", "label": "Paiements en retard (impayés)", "count": late, "icon": "alert", "tone": "rose", "action": {"list": "impaye"}})
    rows = AC.snapshot(now)
    risk = sum(1 for r in rows if r["status"] == "a_risque")
    items.append({"key": "a_risque", "label": "Commerces à risque", "count": risk, "icon": "trending-down", "tone": "amber", "action": {"list": "a_risque"}})
    try:
        from features import analytics_usage as U
        near = sum(1 for r in U.rows(now) if (r.get("near") or 0) >= 90 and r.get("subscription_status") != "canceled")
    except Exception:                       # noqa: BLE001
        near = 0
    items.append({"key": "limite", "label": "Commerces à 90 % de leur limite (à faire évoluer)", "count": near, "icon": "gauge", "tone": "blue",
                  "action": {"list": "limite"}})
    if _can(token_data, "support"):
        urgent = _db.support_tickets.count_documents({"status": "urgent"})
        unread = _db.support_tickets.count_documents({"unread_team": {"$gt": 0}})
        items.append({"key": "support", "label": "Tickets support urgents ou non lus", "count": urgent + unread, "icon": "headset", "tone": "rose",
                      "detail": f"{urgent} urgent{'s' if urgent != 1 else ''} · {unread} non lu{'s' if unread != 1 else ''}",
                      "action": {"href": "/admin/support"}})
    if _can(token_data, "crm"):
        overdue = sum(1 for t in _db.crm_tasks.find({"status": {"$ne": "terminee"}}, {"_id": 0, "due_at": 1})
                      if _aware(t.get("due_at")) and _aware(t["due_at"]) < now)
        # today in Paris, not in UTC (2026-10-24: from midnight to 2 a.m. the
        # « rendez-vous du jour » were yesterday's)
        day0, day1 = _paris_day(now)
        rdv = sum(1 for t in _db.crm_tasks.find({"type": "rdv", "status": {"$ne": "terminee"}}, {"_id": 0, "due_at": 1})
                  if _aware(t.get("due_at")) and day0 <= _aware(t["due_at"]) < day1)
        items.append({"key": "crm_retard", "label": "Tâches CRM en retard", "count": overdue, "icon": "list", "tone": "amber", "action": {"href": "/admin/crm/taches"}})
        items.append({"key": "crm_rdv", "label": "Rendez-vous prospects aujourd'hui", "count": rdv, "icon": "calendar", "tone": "blue", "action": {"href": "/admin/crm/calendrier"}})
    return items


def _encaissements(now: datetime, tenants: List[Dict[str, Any]]) -> Dict[str, Any]:
    import server as core
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    p0 = (m0 - timedelta(days=1)).replace(day=1)
    p_end = min(p0 + (now - m0), m0)
    paid = lambda a, b: [i for i in _db.fidclic_invoices.find({"paid_at": {"$gte": a, "$lt": b}}, {"_id": 0, "amount_paid": 1, "total_ttc": 1})]   # noqa: E731
    cur, prev = paid(m0, now + timedelta(seconds=1)), paid(p0, p_end)
    amount = lambda rows: round(sum(float(i.get("amount_paid") or i.get("total_ttc") or 0) for i in rows), 2)                           # noqa: E731
    stand = {t["id"]: AC.standing_of(t, now) for t in tenants}
    late = [t for t in tenants if stand[t["id"]] == "impaye"]
    upcoming = 0.0
    n_up = 0
    try:
        from features import analytics_usage as U
        for r in U.rows(now):
            rn = r.get("renewal") or {}
            if r.get("subscription_status") == "active" and rn.get("kind") == "renouvellement" and rn.get("days", 99) <= 30:
                upcoming += float(r.get("price") or 0)
                n_up += 1
    except Exception:                       # noqa: BLE001
        pass
    return {"month": amount(cur), "month_invoices": len(cur), "delta": _delta(amount(cur), amount(prev)),
            "upcoming_30": round(upcoming, 2), "upcoming_count": n_up,
            "late": round(sum(core.tenant_price(t) for t in late), 2), "late_count": len(late)}


def _support_health(now: datetime) -> Dict[str, Any]:
    since = now - timedelta(days=30)
    tickets = list(_db.support_tickets.find({}, {"_id": 0, "status": 1, "unread_team": 1, "created_at": 1, "first_response_at": 1,
                                                 "resolved_at": 1, "rating": 1, "last_from": 1}))
    first = [(_aware(t.get("first_response_at")) - _aware(t.get("created_at"))).total_seconds() / 3600 for t in tickets
             if _aware(t.get("first_response_at")) and _aware(t.get("created_at")) and _aware(t["created_at"]) >= since]
    rated = [t["rating"]["stars"] for t in tickets if (t.get("rating") or {}).get("stars") and _aware(t["rating"].get("at")) and _aware(t["rating"]["at"]) >= since]
    return {"open": sum(1 for t in tickets if t.get("status") != "resolu"), "unread": sum(1 for t in tickets if (t.get("unread_team") or 0) > 0),
            "urgent": sum(1 for t in tickets if t.get("status") == "urgent"),
            "waiting_us": sum(1 for t in tickets if t.get("status") != "resolu" and t.get("last_from") == "merchant"),
            "first_response_hours": round(sum(first) / len(first), 1) if first else None,
            "satisfaction": round(sum(rated) / len(rated), 1) if rated else None, "ratings": len(rated),
            "resolved_30": sum(1 for t in tickets if _aware(t.get("resolved_at")) and _aware(t["resolved_at"]) >= since)}


def _crm_summary(now: datetime) -> Dict[str, Any]:
    from features import crm_pilotage as P
    active = _db.crm_prospects.count_documents({"stage": {"$in": P.ACTIVE}})
    proposals = _db.crm_prospects.count_documents({"stage": "proposition"})
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    signed = _db.crm_activities.count_documents({"type": "stage", "meta.to": "signe", "at": {"$gte": m0}})
    try:
        forecast = P._health(now - timedelta(days=30), now, now).get("forecast")
    except Exception:                       # noqa: BLE001
        forecast = None
    week_end = now + timedelta(days=7)
    rdv = sum(1 for t in _db.crm_tasks.find({"type": "rdv", "status": {"$ne": "terminee"}}, {"_id": 0, "due_at": 1})
              if _aware(t.get("due_at")) and now <= _aware(t["due_at"]) <= week_end)
    overdue = sum(1 for t in _db.crm_tasks.find({"status": {"$ne": "terminee"}}, {"_id": 0, "due_at": 1})
                  if _aware(t.get("due_at")) and _aware(t["due_at"]) < now)
    return {"active": active, "proposals": proposals, "signed_month": signed, "forecast": forecast, "rdv_7j": rdv, "overdue": overdue}


def _paris_day(at: datetime) -> Tuple[datetime, datetime]:
    """[start, end) of this day in Paris, as UTC instants (a DST day is 23 or 25 h)."""
    from zoneinfo import ZoneInfo
    paris = ZoneInfo("Europe/Paris")
    d = at.astimezone(paris).date()
    start = datetime(d.year, d.month, d.day, tzinfo=paris)
    end = datetime.fromordinal(d.toordinal() + 1).replace(tzinfo=paris)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/api/admin/dashboard/today")
def dashboard_today(token_data: TokenData = Depends(require_admin("dashboard"))):
    now = _now()
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    return {"todo": _todo(now, tenants, token_data),
            "encaissements": _encaissements(now, tenants) if _can(token_data, "facturation") else None,
            "support": _support_health(now) if _can(token_data, "support") else None,
            "crm": _crm_summary(now) if _can(token_data, "crm") else None}


# ---------------------------------------------------------------------------
# « Activité du jour » (user, 2026-11-10: the old « Activité récente » was
# « ekdm ghatiya »). Three sections — Parrainage, Campagnes + automatisations,
# Nouveaux clients — with every business's activity of ONE Paris day, live
# today, any past day on request. One line per business, per store for a
# franchise. A client is « Prénom N. »: never a phone or an e-mail.
# ---------------------------------------------------------------------------
ACTIVITY_SECTIONS = [("parrainage", "Parrainage"), ("campagnes", "Campagnes + automatisations"),
                     ("nouveaux_clients", "Nouveaux clients")]
ITEMS_PER_LINE = 50


def _short(name: Optional[str]) -> str:
    parts = (name or "").split()
    if not parts:
        return "—"
    return parts[0] + (f" {parts[1][0].upper()}." if len(parts) > 1 and parts[1] else "")


def _day_bounds(day: Optional[str], now: datetime):
    """The Paris day asked for (default: today) as [start, end) UTC, its date,
    and whether it is today. A future day or a wrong date is a 400."""
    from datetime import date as _date
    today_start, _ = _paris_day(now)
    from zoneinfo import ZoneInfo
    today = now.astimezone(ZoneInfo("Europe/Paris")).date()
    if day:
        try:
            d = _date.fromisoformat(str(day).strip())
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide (AAAA-MM-JJ).")
        if d > today:
            raise HTTPException(status_code=400, detail="Ce jour n'est pas encore arrivé.")
    else:
        d = today
    paris = ZoneInfo("Europe/Paris")
    noon = datetime(d.year, d.month, d.day, 12, tzinfo=paris)
    start, end = _paris_day(noon)
    return start, end, d, d == today


def _store_maps(tids) -> Dict[str, Dict[str, Any]]:
    """Per business: its name, whether it has several stores, the store
    names and its main store — closed stores still named (a past day)."""
    out = {}
    for t in _db.tenants.find({"id": {"$in": list(tids)}}, {"_id": 0, "id": 1, "name": 1, "branches": 1}):
        br = [b for b in t.get("branches") or [] if b.get("id")]
        open_ = [b for b in br if b.get("status") != "closed"]
        main = next((b["id"] for b in br if b.get("is_main")), None) or \
            ("main" if any(b["id"] == "main" for b in br) else (open_[0]["id"] if open_ else None))
        out[t["id"]] = {"name": t.get("name") or "—", "multi": len(open_) > 1, "main": main,
                        "names": {b["id"]: b.get("name") or b["id"] for b in br}}
    return out


def _activity_day(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    from services.sources import SOURCES as SRC, UNKNOWN_LABEL
    from features import automations as AU
    rng = {"$gte": start, "$lt": end}
    src_labels = dict(SRC)
    lines: Dict[str, Dict[Any, Dict[str, Any]]] = {k: {} for k, _ in ACTIVITY_SECTIONS}
    items: Dict[str, Dict[Any, List[Dict[str, Any]]]] = {k: {} for k, _ in ACTIVITY_SECTIONS}

    new = list(_db.customers.find({**LIVE, "created_at": rng}, {"_id": 0, "id": 1, "tenant_id": 1, "name": 1, "branch_id": 1,
                                                                 "created_at": 1, "acquisition_source": 1}))
    refs = list(_db.referral_redemptions.find({"created_at": rng}, {"_id": 0}))
    camps = [c for c in _db.campaigns.find({"sent_at": rng}, {"_id": 0, "id": 1, "tenant_id": 1, "name": 1, "sent_at": 1, "status": 1,
                                                              "store_ids": 1, "targeted_count": 1, "delivered_count": 1,
                                                              "recipient_ids": 1})
             if c.get("status") in (None, "sent")]
    logs = list(_db.automation_log.find({"sent_at": rng, "status": "sent"},
                                        {"_id": 0, "tenant_id": 1, "customer_id": 1, "scenario": 1, "sent_at": 1}))
    # who is who: the clients these rows name (their name and home store)
    ids = {r.get("referrer_customer_id") for r in refs} | {r.get("referee_customer_id") for r in refs} | {l.get("customer_id") for l in logs}
    ids.discard(None)
    people = {c["id"]: c for c in _db.customers.find({"id": {"$in": sorted(ids)}}, {"_id": 0, "id": 1, "name": 1, "branch_id": 1})} if ids else {}
    for c in new:
        people.setdefault(c["id"], c)
    tids = {c.get("tenant_id") for c in new} | {r.get("tenant_id") for r in refs} | {c.get("tenant_id") for c in camps} | {l.get("tenant_id") for l in logs}
    tids.discard(None)
    shops = _store_maps(tids)

    def store_of(tid, branch):
        s = shops.get(tid)
        if not s or not s["multi"]:
            return None
        return branch if branch and branch in s["names"] else s["main"]

    def add(sec, tid, store, at, item, **inc):
        s = shops.get(tid)
        if not s:
            return
        key = (tid, store)
        ln = lines[sec].setdefault(key, {"tenant_id": tid, "tenant_name": s["name"], "store_id": store,
                                         "store_name": s["names"].get(store) if store else None,
                                         "count": 0, "last_at": None})
        for k, v in inc.items():
            ln[k] = ln.get(k, 0) + v
        t = _aware(at)
        if t and (ln["last_at"] is None or t > ln["last_at"]):
            ln["last_at"] = t
        if item is not None:
            items[sec].setdefault(key, []).append(item)

    for c in new:
        tid = c.get("tenant_id")
        src = c.get("acquisition_source")
        add("nouveaux_clients", tid, store_of(tid, c.get("branch_id")), c.get("created_at"),
            {"at": _aware(c.get("created_at")), "name": _short(c.get("name")),
             "source": src_labels.get(src, UNKNOWN_LABEL) if src else UNKNOWN_LABEL}, count=1)
    for r in refs:
        tid = r.get("tenant_id")
        fil = people.get(r.get("referee_customer_id")) or {}
        par = people.get(r.get("referrer_customer_id")) or {}
        add("parrainage", tid, store_of(tid, fil.get("branch_id")), r.get("created_at"),
            {"at": _aware(r.get("created_at")), "parrain": _short(par.get("name")), "filleul": _short(fil.get("name")),
             "status": "En attente" if r.get("referrer_pending") else "Validé"}, count=1)
    for c in camps:
        tid = c.get("tenant_id")
        sids = c.get("store_ids") or []
        store = store_of(tid, sids[0]) if len(sids) == 1 else None
        n = int(c.get("targeted_count") or c.get("delivered_count") or len(c.get("recipient_ids") or []))
        add("campagnes", tid, store, c.get("sent_at"),
            {"at": _aware(c.get("sent_at")), "kind": "campagne", "name": c.get("name") or "Campagne", "messages": n},
            count=1, campaigns=1, messages=n)
    autos: Dict[tuple, Dict[str, Any]] = {}
    for l in logs:
        tid = l.get("tenant_id")
        store = store_of(tid, (people.get(l.get("customer_id")) or {}).get("branch_id"))
        scen = l.get("scenario") or "custom"
        label = (AU.SCENARIOS.get(scen) or {}).get("label") or scen
        g = autos.setdefault((tid, store, label), {"at": None, "kind": "automatisation", "name": label, "messages": 0})
        g["messages"] += 1
        t = _aware(l.get("sent_at"))
        g["at"] = max(g["at"], t) if g["at"] and t else (t or g["at"])
        add("campagnes", tid, store, l.get("sent_at"), None, count=1, automations=1, messages=1)
    for (tid, store, _), g in autos.items():
        items["campagnes"].setdefault((tid, store), []).append(g)

    out = []
    for key, title in ACTIVITY_SECTIONS:
        rows = []
        for k, ln in lines[key].items():
            its = sorted(items[key].get(k) or [], key=lambda i: i.get("at") or start, reverse=True)
            row = {**ln, "last_at": _iso(ln["last_at"]), "items": [{**i, "at": _iso(i.get("at"))} for i in its[:ITEMS_PER_LINE]],
                   "more": max(0, len(its) - ITEMS_PER_LINE)}
            if key == "campagnes":
                row.setdefault("campaigns", 0)
                row.setdefault("automations", 0)
                row.setdefault("messages", 0)
            rows.append(row)
        rows.sort(key=lambda r: (-r["count"], r["tenant_name"] or "", r.get("store_name") or ""))
        out.append({"key": key, "title": title, "total": sum(r["count"] for r in rows), "rows": rows})
    return out


@router.get("/api/admin/dashboard/activity")
def dashboard_activity(day: Optional[str] = None, token_data: TokenData = Depends(require_admin("dashboard"))):
    now = _now()
    start, end, d, today = _day_bounds(day, now)
    from datetime import timedelta as _td
    prev = (d - _td(days=1)).isoformat()
    nxt = None if today else (d + _td(days=1)).isoformat()
    _, _, today_d, _ = _day_bounds(None, now)
    return {"day": d.isoformat(), "today": today, "today_day": today_d.isoformat(), "from": _iso(start), "to": _iso(end),
            "prev": prev, "next": nxt,
            "sections": _activity_day(start, end)}
