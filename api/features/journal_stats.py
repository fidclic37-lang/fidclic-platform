"""
The prediction journal's tallies — what the Précision page reads.

User, 2026-10-26 (« hamesha live, pehle se jode hue »; audit: the page and the
CSV read the whole journal on every view): like a shop's till, each prediction
adds itself to a small tally the moment it is written or judged, and the page
reads the tallies, never the journal.

A tally is one document per (model, source, sector, Paris month) with flat
counters: checked / gone (« non revenu ») / open, in the window, the errors'
histograms (eb_ brain, em_ plain mean, er_ the shop's rule — the errors are
rounded to 0.1 day, so a histogram in tenths keeps every median exact), the
calibration buckets and, per shop, how many rows it has (tn_). Added up, the
tallies give the very figures summarise() gives from the rows.

    · live rows: each change is applied at once (apply: the row before out,
      the row after in)
    · a backtest or brain-v2 run keeps its own tallies aside (_side, by
      « owner »: one shop's backtest, or brain-v2's) and swaps them in when
      it ends — the old run's out, the new one's in
    · a journal written before has none: a background job builds them, a
      slice at a time (and again each week, as a check); live changes landing
      meanwhile are applied to the build too when the build has already read
      that row; backtest and brain-v2 runs wait for it to end
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

STATS = "brain_journal_stats"
SIDE = "brain_journal_stats_side"
KEY = "brain_journal_stats"
SLICE = 5000                         # rows read per slice of the build
REBUILD_EVERY = timedelta(days=7)
_KEYS = ("model", "source", "sector", "month")
_COUNTERS = ("checked", "gone", "open", "inwin")

_db = None


def init(db):
    global _db
    _db = db
    from features import ai_jobs as JOBS
    JOBS.register("journal_stats", _build_step)
    try:
        db[STATS].create_index([("build", 1), ("model", 1), ("source", 1), ("sector", 1)])
        db[SIDE].create_index([("owner", 1), ("current", 1)])
        db[SIDE].create_index([("run", 1), ("chunk", 1)])
        # a journal that starts now is tallied from its first row
        if not db.platform_settings.find_one({"key": KEY}) and not db.brain_predictions.find_one({}, {"_id": 1}):
            db.platform_settings.update_one({"key": KEY}, {"$set": {"key": KEY, "ready": True,
                                                                    "built_at": datetime.now(timezone.utc)}},
                                            upsert=True)
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# one row → its share of a tally
# ---------------------------------------------------------------------------
def _t(v: float) -> str:
    return str(int(round(float(v) * 10)))


def contribution(r: Dict[str, Any]) -> Dict[str, float]:
    """What one (full) row adds to its tally."""
    from features import brain_journal as BJ
    st = r.get("status")
    if st == "open":
        return {"open": 1}
    if st == "expired":
        return {"gone": 1}
    if st != "resolved":
        return {}
    o = r.get("outcome") or {}
    w = 1 if o.get("in_window") else 0
    out: Dict[str, float] = {"checked": 1, "inwin": w}
    for code, field in (("eb", "error_days"), ("em", "error_mean"), ("er", "error_rule")):
        if o.get(field) is not None:
            out[f"{code}_{_t(o[field])}"] = 1
    conf = int((r.get("pred") or {}).get("confidence") or 0)
    for i, (lo, hi) in enumerate(BJ.CONF_BUCKETS):
        if lo <= conf < hi:
            out[f"cb{i}n"], out[f"cb{i}s"], out[f"cb{i}w"] = 1, conf, w
    return out


def key_of(r: Dict[str, Any]) -> Dict[str, Any]:
    from features import brain_journal as BJ
    from features import client_brain as CB
    made = CB._aware(r.get("made_at"))
    return {"model": r.get("model") or BJ.MODEL, "source": r.get("source"), "sector": r.get("sector"),
            "month": made.astimezone(CB.PARIS).strftime("%Y-%m") if made else ""}


def add(tally: Dict[str, float], *more: Dict[str, float]) -> Dict[str, float]:
    out = dict(tally)
    for m in more:
        for k, v in m.items():
            out[k] = out.get(k, 0) + v
    return out


def _flat(doc: Dict[str, Any]) -> Dict[str, float]:
    return {k: v for k, v in doc.items() if k in _COUNTERS or k[:3] in ("eb_", "em_", "er_", "tn_")
            or (k[:2] == "cb" and k[2:-1].isdigit())}


# ---------------------------------------------------------------------------
# a tally → the figures (the same as brain_journal.summarise on the rows)
# ---------------------------------------------------------------------------
def _hist(t: Dict[str, float], code: str) -> List[Tuple[float, int]]:
    return sorted((int(k[3:]) / 10, int(n)) for k, n in t.items() if k.startswith(code + "_") and n > 0)


def _median_abs(h: List[Tuple[float, int]]) -> Optional[float]:
    vals: Dict[float, int] = defaultdict(int)
    for v, n in h:
        vals[abs(v)] += n
    total = sum(vals.values())
    if not total:
        return None
    seq = sorted(vals.items())

    def nth(i: int) -> float:
        for v, n in seq:
            if i < n:
                return v
            i -= n
        return seq[-1][0]
    mid = total // 2
    m = nth(mid) if total % 2 else (nth(mid - 1) + nth(mid)) / 2
    return round(m, 1)


def _near(h: List[Tuple[float, int]]) -> Optional[int]:
    from features import brain_journal as BJ
    total = sum(n for _, n in h)
    return BJ._pct(sum(n for v, n in h if abs(v) <= BJ.NEAR_DAYS), total)


def summarise(t: Dict[str, float]) -> Dict[str, Any]:
    from features import brain_journal as BJ
    checked = int(t.get("checked") or 0)
    eb, em, er = _hist(t, "eb"), _hist(t, "em"), _hist(t, "er")
    calib = []
    for i, (lo, hi) in enumerate(BJ.CONF_BUCKETS):
        n = int(t.get(f"cb{i}n") or 0)
        if n:
            calib.append({"label": f"{lo}–{min(hi, 100)} %", "said": round(int(t.get(f"cb{i}s") or 0) / n),
                          "real": BJ._pct(int(t.get(f"cb{i}w") or 0), n), "n": n})
    late = sum(n for v, n in eb if v > 0)
    return {
        "checked": checked, "not_returned": int(t.get("gone") or 0), "open": int(t.get("open") or 0),
        "in_window": BJ._pct(int(t.get("inwin") or 0), checked),
        "brain": {"median_error": _median_abs(eb), "near": _near(eb)},
        "mean": {"median_error": _median_abs(em), "near": _near(em)},
        "rule": {"median_error": _median_abs(er), "near": _near(er)},
        "came_late": BJ._pct(late, sum(n for _, n in eb)),
        "calibration": calib,
    }


def tenants(t: Dict[str, float]) -> List[str]:
    return [k[3:] for k, n in t.items() if k.startswith("tn_") and n > 0]


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def status() -> Dict[str, Any]:
    return _db.platform_settings.find_one({"key": KEY}, {"_id": 0}) or {}


def ready() -> bool:
    return bool(status().get("ready"))


def cells(source: str = "all", sector: str = "") -> List[Tuple[Dict[str, Any], Dict[str, float]]]:
    q: Dict[str, Any] = {"build": None}
    if source in ("live", "backtest"):
        q["source"] = source
    if sector:
        q["sector"] = sector
    return [({k: d.get(k) for k in _KEYS}, _flat(d)) for d in _db[STATS].find(q, {"_id": 0})]


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def _with_tenant(r: Dict[str, Any], inc: Dict[str, float]) -> Dict[str, float]:
    return {**inc, f"tn_{r.get('tenant_id')}": 1} if inc and r.get("tenant_id") else inc


def _bump(coll: str, filt: Dict[str, Any], inc: Dict[str, float], sign: int = 1) -> None:
    if inc:
        _db[coll].update_one(filt, {"$inc": {k: v * sign for k, v in inc.items()}}, upsert=True)


def _building() -> Optional[Dict[str, Any]]:
    b = status().get("building")
    return b if b and b.get("run") else None


def apply(before: Optional[Dict[str, Any]], after: Optional[Dict[str, Any]], row_id: Any = None) -> None:
    """A live row changed (written, judged, closed, deleted): its tally
    follows. Never raises."""
    try:
        b = _building()
        for r, sign in ((before, -1), (after, 1)):
            if not r or r.get("run") or r.get("kind", "next_visit") != "next_visit":
                continue
            inc = _with_tenant(r, contribution(r))
            _bump(STATS, {**key_of(r), "build": None}, inc, sign)
            # the build would miss this change: a row it has read already, or
            # one written after it started (it reads up to where the journal was)
            if b and (row_id is None or (b.get("max") is not None and row_id > b["max"])
                      or (b.get("cursor") is not None and row_id <= b["cursor"])):
                _bump(STATS, {**key_of(r), "build": b["run"], "chunk": -1}, inc, sign)
    except Exception as exc:
        print(f"journal_stats.apply failed (non-fatal): {exc}")


def stage(rows: Iterable[Dict[str, Any]], run: str, owner: str, chunk: int) -> None:
    """A backtest / brain-v2 slice's rows, tallied aside until the run ends."""
    agg: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for r in rows:
        k = tuple(key_of(r)[x] for x in _KEYS)
        agg[k] = add(agg[k], _with_tenant(r, contribution(r)))
    docs = [{"run": run, "owner": owner, "chunk": chunk, **dict(zip(_KEYS, k)), **t} for k, t in agg.items()]
    if docs:
        _db[SIDE].insert_many(docs)


def unstage(run: str, from_chunk: int = 0) -> None:
    """What a slice killed half-way (or a cancelled run) had tallied."""
    _db[SIDE].delete_many({"run": run, "chunk": {"$gte": from_chunk}})


def _collapse(docs: Iterable[Dict[str, Any]]) -> Dict[Tuple, Dict[str, float]]:
    agg: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for d in docs:
        agg[tuple(d.get(x) for x in _KEYS)] = add(agg[tuple(d.get(x) for x in _KEYS)], _flat(d))
    return agg


def swap(owner: str, run: str) -> None:
    """A run ended: the old run's tallies out, the new one's in."""
    old = _collapse(_db[SIDE].find({"owner": owner, "current": True}, {"_id": 0}))
    new = _collapse(_db[SIDE].find({"owner": owner, "run": run, "current": {"$ne": True}}, {"_id": 0}))
    for k in set(old) | set(new):
        delta = add(new.get(k, {}), {f: -v for f, v in old.get(k, {}).items()})
        delta = {f: v for f, v in delta.items() if v}
        _bump(STATS, {**dict(zip(_KEYS, k)), "build": None}, delta)
    _db[SIDE].delete_many({"owner": owner, "$or": [{"current": True}, {"run": run}]})
    docs = [{"run": run, "owner": owner, "current": True, **dict(zip(_KEYS, k)), **t} for k, t in new.items()]
    if docs:
        _db[SIDE].insert_many(docs)


def wait_for_build() -> bool:
    """Runs swap their tallies only when no build is under way."""
    return _building() is not None


# ---------------------------------------------------------------------------
# the build (a journal written before; each week as a check)
# ---------------------------------------------------------------------------
def due() -> Optional[str]:
    """The tick: start a build when there are no tallies yet, or each week."""
    from features import ai_jobs as JOBS
    st = status()
    built = st.get("built_at")
    if built and built.tzinfo is None:
        built = built.replace(tzinfo=timezone.utc)
    if st.get("ready") and built and _now() - built < REBUILD_EVERY:
        return None
    job, created = JOBS.start("journal_stats", None, by="tick")
    return job["id"] if created else None


def _owner(r: Dict[str, Any]) -> Optional[str]:
    from features import brain_journal as BJ
    if r.get("source") != "backtest":
        return None
    model = r.get("model") or BJ.MODEL
    return "v2" if model == "brain-v2" else f"bt:{r.get('tenant_id')}:{model}"


def _build_step(job: Dict[str, Any], deadline: float) -> bool:
    from features import ai_jobs as JOBS
    from features import brain_journal as BJ
    run = job["run"]
    st = dict(job.get("state") or {})
    if "chunk" not in st:
        # the journal as it stands now; rows written after reach the build as live changes —
        # a busy network never keeps it from ending
        last = list(_db.brain_predictions.find({}, {"_id": 1}).sort("_id", -1).limit(1))
        st = {"cursor": None, "chunk": 0, "max": last[0]["_id"] if last else None}
        total = _db.brain_predictions.count_documents({"run": {"$exists": False}})
        JOBS.save(job, state=st, total=total, done=0, phase="lignes")
        _db.platform_settings.update_one({"key": KEY}, {"$set": {"key": KEY, "building": {
            "run": run, "cursor": None, "max": st["max"]}}}, upsert=True)
    while True:
        _db[STATS].delete_many({"build": run, "chunk": {"$gte": st["chunk"]}})      # a slice that died
        _db[SIDE].delete_many({"build": run, "chunk": {"$gte": st["chunk"]}})
        q: Dict[str, Any] = {"run": {"$exists": False}}
        ids: Dict[str, Any] = {}
        if st["cursor"] is not None:
            ids["$gt"] = st["cursor"]
        if st.get("max") is not None:
            ids["$lte"] = st["max"]
        if ids:
            q["_id"] = ids
        docs = list(_db.brain_predictions.find(q).sort("_id", 1).limit(SLICE)) if st.get("max") is not None else []
        if not docs:
            _finish_build(run)
            return True
        cells_: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
        side: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
        for d in docs:
            r = BJ.unpack(d)
            if r.get("kind", "next_visit") != "next_visit":
                continue
            inc = _with_tenant(r, contribution(r))
            k = tuple(key_of(r)[x] for x in _KEYS)
            cells_[k] = add(cells_[k], inc)
            owner = _owner(r)
            if owner:
                side[(owner,) + k] = add(side[(owner,) + k], inc)
        rows = [{"build": run, "chunk": st["chunk"], **dict(zip(_KEYS, k)), **t} for k, t in cells_.items()]
        if rows:
            _db[STATS].insert_many(rows)
        srows = [{"build": run, "chunk": st["chunk"], "owner": k[0], **dict(zip(_KEYS, k[1:])), **t}
                 for k, t in side.items()]
        if srows:
            _db[SIDE].insert_many(srows)
        st = {**st, "cursor": docs[-1]["_id"], "chunk": st["chunk"] + 1}
        JOBS.save(job, state=st, done=int(job.get("done") or 0) + len(docs))
        _db.platform_settings.update_one({"key": KEY}, {"$set": {"building.cursor": st["cursor"]}})
        if time.monotonic() >= deadline:
            return False


def _finish_build(run: str) -> None:
    """The new tallies replace the old ones, at once."""
    agg = _collapse(_db[STATS].find({"build": run}, {"_id": 0}))
    final = f"final:{run}"
    docs = [{"build": final, **dict(zip(_KEYS, k)), **t} for k, t in agg.items()]
    if docs:
        _db[STATS].insert_many(docs)
    _db[STATS].delete_many({"build": {"$in": [None, run]}})
    _db[STATS].update_many({"build": final}, {"$set": {"build": None}})
    # each run's own tallies, for its next swap
    side: Dict[Tuple, Dict[str, float]] = defaultdict(dict)
    for d in _db[SIDE].find({"build": run}, {"_id": 0}):
        k = (d["owner"],) + tuple(d.get(x) for x in _KEYS)
        side[k] = add(side[k], _flat(d))
    _db[SIDE].delete_many({"$or": [{"current": True}, {"build": run}]})
    sdocs = [{"owner": k[0], "current": True, "run": None, **dict(zip(_KEYS, k[1:])), **t} for k, t in side.items()]
    if sdocs:
        _db[SIDE].insert_many(sdocs)
    _db.platform_settings.update_one({"key": KEY}, {"$set": {"ready": True, "built_at": _now()},
                                                    "$unset": {"building": ""}})
