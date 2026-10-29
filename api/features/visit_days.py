"""
« Roz ka hisaab » — each finished day's visits, summed once (user, 2026-10-28).

WHY
    The Tableau de bord read every visit of its period — and of the period
    before, and of the month — then rebuilt a client brain per visit to set
    « attendus » apart: 2.9 s for a 2 000-client shop, locally, far more on
    Atlas. A day that is over does not change by itself, so it is summed once.

WHAT A DAY HOLDS (`visit_days`, one row per shop and Paris day)
    Per establishment (`branch_id`; none = « ~none »): the visits and the
    money, both per hour of the shop's clock; the products (quantity, money);
    what FidClic brought, per source (features/fidclic_impact.classify); the
    visits « attendus » set apart; how many could have been (`cand`). Money is
    counted in millionths of a euro, so a sum is the same whatever the order
    the days are added in.

WHAT IS LIVE
    Today, and the cut ends of a period that starts or stops in the middle of
    a day, are read from the visits as before. `span_many` sums the rest from
    the register — the figures are exactly the ones the visits give
    (tests/test_visit_days.py compares every period both ways).

WHEN A DAY IS SUMMED AGAIN (user: « usi din ka register turant sudhre »)
    Every write to the rows that decide a past day's figures is heard
    (services/doc_cache WRITE HOOKS), wherever it comes from:
        visits                  the day of the visit, before and after the
                                change — and the later days of the same
                                clients, whose « attendus » read their history
        push_notifications,     the 15 days a message can credit
        push_wallet_log,
        campaigns
        referral_redemptions    every day the filleul came
    A heard day gets its stamp raised (`visit_days_stamps`); a row summed
    under an older stamp is summed again on the next read. The stamp is read
    BEFORE the visits and raised AFTER the write, so a write landing during a
    sum never leaves a stale day: at worst the day is summed twice.
    A write that changes no figure (a message opened, a click counted) and
    anything dated today (a scan, a send) raise nothing.

A NEW BRAIN (user: « naya brain aaye to history peeche dobara gine »)
    « Attendus » follow the brain in service and its learned rhythm; each row
    keeps the version it was summed with (`bv`). When it changes, the page
    keeps reading the register and a job (features/ai_jobs, kind
    « visit_days ») sums again, in the tick's slices, only the days that had a
    visit « attendus » could claim (`cand`).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from features import period as P

_db = None
ENABLED = True                 # False: every figure from the visits (the tests' reference)
SCHEMA = 1                     # a row summed by another layout is summed again
MICRO = 1_000_000
NONE = "~none"                 # the establishment of a visit with no branch_id
COLL, STAMPS = "visit_days", "visit_days_stamps"
BV_TTL_S = 600
WINDOW = timedelta(days=15)    # features/fidclic_impact.WINDOW_DAYS
VISIT_FIELDS = {"tenant_id", "customer_id", "amount_paid", "visit_time", "items", "branch_id"}
MSG_FIELDS = {"tenant_id", "customer_id", "type", "sent_at", "campaign_id", "temoin"}
CAMPAIGN_FIELDS = {"tenant_id", "id", "sent_at", "recipient_ids", "holdout_ids"}
REFERRAL_FIELDS = {"tenant_id", "referee_customer_id"}
_bv_cache: Dict[str, Tuple[float, str]] = {}


def init(db):
    global _db
    _db = db
    try:
        db[COLL].create_index([("tenant_id", 1), ("day", 1)], unique=True)
        db[COLL].create_index([("tenant_id", 1), ("cand", 1), ("bv", 1)])
        db[STAMPS].create_index([("tenant_id", 1), ("day", 1)], unique=True)
    except Exception:
        pass
    from services import doc_cache
    doc_cache.on_write("visits", _hear_visits)
    doc_cache.on_write("push_notifications", _hear_messages)
    doc_cache.on_write("push_wallet_log", _hear_messages)
    doc_cache.on_write("campaigns", _hear_campaigns)
    doc_cache.on_write("referral_redemptions", _hear_referrals)
    from features import ai_jobs
    ai_jobs.register("visit_days", _job)


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


def _micro(x: float) -> int:
    return int(round(float(x) * MICRO))


def day_of(t: datetime) -> str:
    return P.local(t).date().isoformat()


def day_start(day: str) -> datetime:
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, tzinfo=P.PARIS).astimezone(timezone.utc)


def _next(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def store_of(branch_id: Any) -> str:
    return NONE if branch_id is None else str(branch_id)


def scope_keys(scope) -> Optional[Set[str]]:
    """The establishments a scope reads, as the register names them — the
    same rows store_scope.visit_filter matches."""
    if scope is None or scope.is_all:
        return None
    from features import store_scope as S
    return {store_of(v) for v in S._branch_values(scope)}


# ---------------------------------------------------------------------------
# summing
# ---------------------------------------------------------------------------
def _blank() -> Dict[str, Any]:
    return {"n": 0, "r": 0, "h": {}, "p": {}, "src": {}, "att": [0, 0], "cand": 0}


def _add(agg: Dict[str, Any], v: Dict[str, Any], t: datetime, cls: Tuple[Optional[str], bool, bool]) -> None:
    r = _micro(v.get("amount_paid") or 0)
    agg["n"] += 1
    agg["r"] += r
    h = agg["h"].setdefault(P.local(t).hour, [0, 0])
    h[0] += 1
    h[1] += r
    for item in (v.get("items") or []):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        # The Scan page writes `qty`; older imports wrote `quantity`.
        qty = int(item.get("qty") or item.get("quantity") or 1)
        p = agg["p"].setdefault(name, [0, 0])
        p[0] += qty
        p[1] += _micro(float(item.get("price") or 0) * qty)
    src, cand, anyway = cls
    if cand:
        agg["cand"] += 1
    if not src:
        return
    if anyway:
        agg["att"][0] += 1
        agg["att"][1] += r
    else:
        s = agg["src"].setdefault(src, [0, 0])
        s[0] += 1
        s[1] += r


def fold(tid: str, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """{day: {establishment: sums}} for these visits."""
    from features import fidclic_impact as FI
    rows = [v for v in rows if _aware(v.get("visit_time"))]
    out: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for v, cls in zip(rows, FI.classify(tid, rows) if rows else []):
        t = _aware(v["visit_time"])
        agg = out.setdefault(day_of(t), {}).setdefault(store_of(v.get("branch_id")), _blank())
        _add(agg, v, t, cls)
    return out


def _pack(stores: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Lists, not maps: a product named « Thé.vert » or « $pécial » is no field name."""
    return [{"s": s, "n": a["n"], "r": a["r"], "h": [[k, *v] for k, v in sorted(a["h"].items())],
             "p": [[k, *v] for k, v in a["p"].items()], "src": [[k, *v] for k, v in a["src"].items()],
             "att": a["att"], "cand": a["cand"]} for s, a in stores.items()]


def _unpack(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {x["s"]: {"n": x["n"], "r": x["r"], "h": {k: [n, r] for k, n, r in x["h"]},
                     "p": {k: [q, r] for k, q, r in x["p"]}, "src": {k: [n, r] for k, n, r in x["src"]},
                     "att": list(x["att"]), "cand": x.get("cand", 0)} for x in rows or []}


class Totals:
    """A period's figures, added up day by day and establishment by establishment."""

    def __init__(self):
        self.n = 0
        self.r = 0
        self.hours: Dict[Tuple[str, int], List[int]] = {}
        self.products: Dict[str, List[int]] = {}
        self.src: Dict[str, List[int]] = {}
        self.att = [0, 0]

    def add(self, day: str, agg: Dict[str, Any]) -> None:
        self.n += agg["n"]
        self.r += agg["r"]
        for h, (n, r) in agg["h"].items():
            x = self.hours.setdefault((day, int(h)), [0, 0])
            x[0] += n
            x[1] += r
        for k, (q, r) in agg["p"].items():
            x = self.products.setdefault(k, [0, 0])
            x[0] += q
            x[1] += r
        for k, (n, r) in agg["src"].items():
            x = self.src.setdefault(k, [0, 0])
            x[0] += n
            x[1] += r
        self.att[0] += agg["att"][0]
        self.att[1] += agg["att"][1]

    @property
    def revenue(self) -> float:
        return self.r / MICRO

    def impact(self) -> Dict[str, Any]:
        """features/fidclic_impact.impact's answer."""
        from features import fidclic_impact as FI
        by = {k: self.src.get(k, [0, 0]) for k, _, _ in FI.SOURCES}
        return {"revenue": round(sum(r for _, r in by.values()) / MICRO, 2),
                "visits": sum(n for n, _ in by.values()),
                "sources": {k: {"revenue": round(r / MICRO, 2), "visits": n} for k, (n, r) in by.items()},
                "attendus": {"revenue": round(self.att[1] / MICRO, 2), "visits": self.att[0]}}

    def top_products(self, k: int) -> List[Dict[str, Any]]:
        # the most sold; at equal sales the one that brought more, then by name
        # (before, a tie fell in whatever order the database returned the rows)
        best = sorted(self.products.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))[:k]
        return [{"name": n, "sales": int(q), "revenue": round(r / MICRO, 2)} for n, (q, r) in best]


# ---------------------------------------------------------------------------
# reading a period
# ---------------------------------------------------------------------------
def _raw(tid: str, lo: datetime, hi: datetime, hi_inclusive: bool, vfilter: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The visits of [lo, hi] (or [lo, hi)) — the reads the register spares."""
    return list(_db.visits.find(
        {"tenant_id": tid, "visit_time": {"$gte": lo, ("$lte" if hi_inclusive else "$lt"): hi}, **vfilter},
        {"_id": 0, "customer_id": 1, "amount_paid": 1, "visit_time": 1, "items": 1, "branch_id": 1}))


def _cut(a: datetime, b: datetime, today: str) -> Tuple[List[str], List[Tuple[datetime, datetime, bool]]]:
    """The finished days wholly inside [a, b], and the pieces left around them."""
    full: List[str] = []
    d = day_of(a)
    if day_start(d) < a:
        d = _next(d)
    while d < today:
        nxt = _next(d)
        if day_start(nxt) > b + timedelta(microseconds=1):
            break
        full.append(d)
        d = nxt
    if not full:
        return [], [(a, b, True)]
    pieces = []
    if a < day_start(full[0]):
        pieces.append((a, day_start(full[0]), False))
    end = day_start(_next(full[-1]))
    if end <= b:
        pieces.append((end, b, True))
    return full, pieces


def brain_version(tid: str) -> str:
    """What « attendus » were judged with: the brain in service and its args."""
    import time
    hit = _bv_cache.get(tid)
    if hit and time.time() - hit[0] < BV_TTL_S:
        return hit[1]
    from features import client_brain as CB
    try:
        args = CB.model_args(tid, CB.champion())
    except Exception:
        args = {}
    v = hashlib.sha1(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:12]
    _bv_cache[tid] = (time.time(), v)
    return v


# A shop's register is « open » from its first read on. Before that, nothing
# hears its writes — its first read sums every day from the visits anyway, and
# an import of old visits must not pay a hearing per row. The mark is written
# before that first read reads a stamp, and a write checks it after it lands:
# a write that saw no mark is in the visits that read sums.
OPEN = "~open"
_open_seen: Set[str] = set()      # only « open » is kept: it never closes


def _open(tid: str) -> None:
    if tid in _open_seen:
        return
    _db[STAMPS].update_one({"tenant_id": tid, "day": OPEN}, {"$setOnInsert": {"n": 0}}, upsert=True)
    _open_seen.add(tid)


def _is_open(tid: Optional[str]) -> bool:
    if not tid:
        return False
    if tid in _open_seen:
        return True
    if _db[STAMPS].find_one({"tenant_id": tid, "day": OPEN}, {"_id": 1}):
        _open_seen.add(tid)
        return True
    return False


def _stamps(tid: str, days: Iterable[str]) -> Dict[str, int]:
    days = sorted(days)
    if not days:
        return {}
    return {d["day"]: int(d.get("n") or 0) for d in _db[STAMPS].find(
        {"tenant_id": tid, "day": {"$gte": days[0], "$lte": days[-1]}}, {"_id": 0, "day": 1, "n": 1})}


def _runs(days: List[str]) -> List[List[str]]:
    out: List[List[str]] = []
    for d in sorted(days):
        if out and _next(out[-1][-1]) == d:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def _build(tid: str, days: List[str], stamps: Dict[str, int], bv: str) -> Dict[str, Dict[str, Any]]:
    """Sum these days from the visits and keep them; returns {day: row}."""
    from pymongo import ReplaceOne
    out: Dict[str, Dict[str, Any]] = {}
    built = datetime.now(timezone.utc)
    for run in _runs(days):
        sums = fold(tid, _raw(tid, day_start(run[0]), day_start(_next(run[-1])), False, {}))
        for d in run:
            stores = sums.get(d) or {}
            out[d] = {"tenant_id": tid, "day": d, "v": SCHEMA, "stamp": stamps.get(d, 0), "bv": bv,
                      "cand": sum(a["cand"] for a in stores.values()), "built_at": built, "stores": _pack(stores)}
    # one round trip, not one per day: two years cold were ~1 500 writes
    ops = [ReplaceOne({"tenant_id": tid, "day": d}, row, upsert=True) for d, row in out.items()]
    for i in range(0, len(ops), 1000):
        try:
            _db[COLL].bulk_write(ops[i:i + 1000], ordered=False)
        except Exception:
            pass                         # two reads summing the same day: either row is right
    return out


def _register(tid: str, days: List[str]) -> Dict[str, Dict[str, Any]]:
    """{day: row} for these finished days, each one current."""
    if not days:
        return {}
    _open(tid)
    stamps = _stamps(tid, days)
    have = {r["day"]: r for r in _db[COLL].find(
        {"tenant_id": tid, "day": {"$gte": min(days), "$lte": max(days)}}, {"_id": 0})}
    rows, missing = {}, []
    for d in days:
        r = have.get(d)
        if r and r.get("v") == SCHEMA and int(r.get("stamp") or 0) == stamps.get(d, 0):
            rows[d] = r
        else:
            missing.append(d)
    bv = brain_version(tid)
    if missing:
        rows.update(_build(tid, missing, stamps, bv))
    if any(r.get("cand") and r.get("bv") != bv for r in rows.values()):
        try:
            from features import ai_jobs
            ai_jobs.start("visit_days", tid, by="brain")
        except Exception:
            pass
    return rows


def span_many(tid: str, scope, ranges: List[Tuple[datetime, datetime]], at: Optional[datetime] = None) -> List[Totals]:
    """Each [a, b] period's Totals, for this shop and establishment(s)."""
    from features import store_scope as S
    at = at or _now()
    keys = scope_keys(scope)
    vfilter = S.visit_filter(scope) if scope is not None else {}
    today = day_of(at)
    plans = []
    for a, b in ranges:
        plans.append(_cut(a, b, today) if ENABLED else ([], [(a, b, True)]))
    days = sorted({d for full, _ in plans for d in full})
    reg = {d: _unpack(r["stores"]) for d, r in _register(tid, days).items()}
    # each live piece read and judged once (today is the same piece for the
    # period and the month)
    live = {p: fold(tid, _raw(tid, p[0], p[1], p[2], vfilter)) for _, ps in plans for p in ps}
    out = []
    for full, ps in plans:
        tot = Totals()
        for d in full:
            for s, agg in reg[d].items():
                if keys is None or s in keys:
                    tot.add(d, agg)
        for p in ps:
            for d, stores in live[p].items():
                for agg in stores.values():
                    tot.add(d, agg)
        out.append(tot)
    return out


# ---------------------------------------------------------------------------
# hearing the writes
# ---------------------------------------------------------------------------
def _touches(update: Any, fields: Set[str]) -> bool:
    """Whether an update (or a replacement) may change one of these fields."""
    if not isinstance(update, dict):
        return True                                   # a pipeline: assume it does
    ops = [k for k in update if k.startswith("$")]
    if not ops:
        return True                                   # a replacement
    for op in ops:
        body = update[op]
        if not isinstance(body, dict):
            return True
        if any(str(k).split(".")[0] in fields for k in body):
            return True
    return False


def _before(coll, method: str, a: tuple, k: dict, proj: Dict[str, int]) -> List[Dict[str, Any]]:
    flt = a[0] if a else k.get("filter", {})
    cur = coll.find(flt or {}, {"_id": 0, **proj})
    if method.endswith("_one") or method.startswith("find_one"):
        if k.get("sort"):
            cur = cur.sort(k["sort"])
        cur = cur.limit(1)
    return list(cur)


def _update_of(method: str, a: tuple, k: dict) -> Any:
    if method in ("update_one", "update_many", "find_one_and_update"):
        return a[1] if len(a) > 1 else k.get("update")
    if method in ("replace_one", "find_one_and_replace"):
        return a[1] if len(a) > 1 else k.get("replacement")
    return None


def _set_values(update: Any) -> Dict[str, Any]:
    if not isinstance(update, dict):
        return {}
    if not any(k.startswith("$") for k in update):
        return update                                 # a replacement
    out = dict(update.get("$set") or {})
    out.update(update.get("$setOnInsert") or {})
    return out


def _mark(marks: Dict[str, Set[str]]) -> None:
    """Raise the stamp of these past days."""
    today = day_of(_now())
    for tid, days in marks.items():
        if not _is_open(tid):
            continue
        for d in sorted(days):
            if d >= today:
                continue
            _db[STAMPS].update_one({"tenant_id": tid, "day": d}, {"$inc": {"n": 1}}, upsert=True)


def _later_days(tid: str, cids: Set[str], since: datetime) -> Set[str]:
    """The days these clients came from `since` — their « attendus » read the
    visits before them."""
    cids = {c for c in cids if c}
    if not cids:
        return set()
    return {day_of(t) for t in (_aware(v.get("visit_time")) for v in _db.visits.find(
        {"tenant_id": tid, "customer_id": {"$in": sorted(cids)}, "visit_time": {"$gte": since}},
        {"_id": 0, "visit_time": 1})) if t}


def _write_kind(method: str) -> str:
    if method.startswith("insert"):
        return "insert"
    if method == "bulk_write":
        return "bulk"
    return "change"


def _hear_visits(coll, method: str, a: tuple, k: dict):
    kind = _write_kind(method)
    today = day_of(_now())
    if kind == "insert":
        docs = (a[0] if a else k.get("documents" if method == "insert_many" else "document")) or []
        docs = [docs] if method == "insert_one" else list(docs)
        past = [(d.get("tenant_id"), _aware(d.get("visit_time")), d.get("customer_id")) for d in docs]
        past = [(tid, t, c) for tid, t, c in past if t and day_of(t) < today]
        if not past:
            return None                               # a scan today: nothing to hear
        return lambda: _visits_changed(past)
    if kind == "bulk":
        return lambda: None
    update = _update_of(method, a, k)
    if update is not None and not _touches(update, VISIT_FIELDS):
        return None
    old = _before(coll, method, a, k, {"tenant_id": 1, "visit_time": 1, "customer_id": 1})
    new = _set_values(update)
    flt = a[0] if a else k.get("filter", {})

    def after():
        rows = [(o.get("tenant_id"), _aware(o.get("visit_time")), o.get("customer_id")) for o in old]
        if new:
            for o in old or [flt if isinstance(flt, dict) else {}]:
                rows.append((new.get("tenant_id", o.get("tenant_id")),
                             _aware(new.get("visit_time", o.get("visit_time"))),
                             new.get("customer_id", o.get("customer_id"))))
        _visits_changed([(tid, t, c) for tid, t, c in rows if t])
    return after


def _visits_changed(rows: List[Tuple[str, datetime, Optional[str]]]) -> None:
    marks: Dict[str, Set[str]] = {}
    first: Dict[str, datetime] = {}
    cids: Dict[str, Set[str]] = {}
    for tid, t, c in rows:
        if not _is_open(tid):
            continue
        marks.setdefault(tid, set()).add(day_of(t))
        first[tid] = min(first.get(tid, t), t)
        if c:
            cids.setdefault(tid, set()).add(c)
    for tid, ids in cids.items():
        marks[tid] |= _later_days(tid, ids, day_start(day_of(first[tid])))
    _mark(marks)


def _window_days(t: datetime) -> Set[str]:
    out, d, last = set(), day_of(t), day_of(t + WINDOW)
    while d <= last:
        out.add(d)
        d = _next(d)
    return out


def _sent_changed(rows: List[Dict[str, Any]], extra: Dict[str, Any], flt: Any) -> None:
    marks: Dict[str, Set[str]] = {}
    for o in rows + ([{**(o if isinstance(o, dict) else {}), **extra} for o in (rows or [flt])] if extra else []):
        t, tid = _aware(o.get("sent_at")), o.get("tenant_id")
        if t and tid:
            marks.setdefault(tid, set()).update(_window_days(t))
    _mark(marks)


def _hear_sent(coll, method: str, a: tuple, k: dict, fields: Set[str]):
    kind = _write_kind(method)
    today = day_of(_now())
    if kind == "insert":
        docs = (a[0] if a else k.get("documents" if method == "insert_many" else "document")) or []
        docs = [docs] if method == "insert_one" else list(docs)
        past = [d for d in docs if _aware(d.get("sent_at")) and day_of(_aware(d["sent_at"])) < today]
        return (lambda: _sent_changed(past, {}, None)) if past else None
    if kind == "bulk":
        return None
    update = _update_of(method, a, k)
    if update is not None and not _touches(update, fields):
        return None
    old = _before(coll, method, a, k, {"tenant_id": 1, "sent_at": 1})
    new = {f: v for f, v in _set_values(update).items() if f in ("tenant_id", "sent_at")}
    flt = a[0] if a else k.get("filter", {})
    return lambda: _sent_changed(old, new, flt)


def _hear_messages(coll, method, a, k):
    return _hear_sent(coll, method, a, k, MSG_FIELDS)


def _hear_campaigns(coll, method, a, k):
    after = _hear_sent(coll, method, a, k, CAMPAIGN_FIELDS)
    if after is None or method.startswith("insert"):
        return after
    # its messages read whether a témoin measured it (fidclic_impact._messages)
    camps = [c for c in _before(coll, method, a, k, {"tenant_id": 1, "id": 1}) if c.get("id")]

    def both():
        after()
        ids = [c["id"] for c in camps if _is_open(c.get("tenant_id"))]
        if ids:
            _sent_changed(list(_db.push_notifications.find({"campaign_id": {"$in": ids}},
                                                           {"_id": 0, "tenant_id": 1, "sent_at": 1})), {}, None)
    return both


def _hear_referrals(coll, method: str, a: tuple, k: dict):
    kind = _write_kind(method)
    if kind == "bulk":
        return None
    if kind == "insert":
        docs = (a[0] if a else k.get("documents" if method == "insert_many" else "document")) or []
        rows = [docs] if method == "insert_one" else list(docs)
    else:
        update = _update_of(method, a, k)
        if update is not None and not _touches(update, REFERRAL_FIELDS):
            return None
        rows = _before(coll, method, a, k, {"tenant_id": 1, "referee_customer_id": 1})
        new = _set_values(update)
        if new.get("referee_customer_id"):
            rows = rows + [{**r, **new} for r in rows]

    def after():
        marks: Dict[str, Set[str]] = {}
        for r in rows:
            tid, cid = r.get("tenant_id"), r.get("referee_customer_id")
            if cid and _is_open(tid):
                marks.setdefault(tid, set()).update(
                    _later_days(tid, {cid}, datetime(1970, 1, 1, tzinfo=timezone.utc)))
        _mark(marks)
    return after


# ---------------------------------------------------------------------------
# a new brain: the job
# ---------------------------------------------------------------------------
CHUNK_DAYS = 31


def _job(job: Dict[str, Any], deadline: float) -> bool:
    """Sum again the days « attendus » could claim, judged by an older brain."""
    import time
    tid = job.get("tenant_id")
    _bv_cache.pop(tid, None)
    bv = brain_version(tid)
    while time.monotonic() < deadline:
        stale = [r["day"] for r in _db[COLL].find(
            {"tenant_id": tid, "cand": {"$gt": 0}, "bv": {"$ne": bv}}, {"_id": 0, "day": 1}).sort("day", 1).limit(CHUNK_DAYS)]
        if not stale:
            return True
        _build(tid, stale, _stamps(tid, stale), bv)
    return False
