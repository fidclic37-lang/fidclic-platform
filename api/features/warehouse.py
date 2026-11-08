"""
The warehouse — each shop's full history, copied at night to the PRIVATE
Vercel Blob store (user, 2026-11-04: « haan rakho taaki ek structured and
complete data mile »; services/blob_private).

WHY
    The weekly AI jobs read two years of visits per shop from the M0 cluster
    (100 ops/s, 10 GB a week — atlas-m0-load-findings). The copy moves those
    reads to Blob. First reader: « Produits qui font revenir ».

WHAT IS COPIED
    The shop's event logs, whole (personal fields kept — the decision):
    visits, offer uses, rewards redeemed. One gzipped JSON-lines file per
    shop, log and UTC month:  wh/v1/<shop>/<log>/<YYYY-MM>.v<n>.jsonl.gz
    A month file is never overwritten: a new copy gets the next version and
    the old one is deleted once `warehouse_state` points at the new one.

THE NIGHT (the tick, 01:00–07:00 Paris, a time budget per tick)
    first time, or after a change of old data (mark_dirty): every month is
        copied up to the start of the build; the copy is used only once all
        are in.
    every other night, per log:
        · the months from the last copy to now are copied again;
        · every month's count on the cluster (one aggregate) is compared to
          its file: a backdated visit or a deleted one gets its month copied
          again;
        · the month copied longest ago (over 30 days) is copied again — the
          safety net for an edit that keeps the count.
    The retention unlink (privacy_page) and the store tagging of old visits
    (server.py) call mark_dirty: the copy is not read until rebuilt, so a
    client the rules unlinked never comes back from it.

READING (rows / find)
    The copy for what is before its cut + the cluster for what came after
    = exactly the cluster's answer. Anything not sure — no store, not ready,
    a pending rebuild, a copy older than 3 days, a file missing, corrupt or
    with another count, Blob down — returns None and find() asks the
    cluster as before. A read never mixes a half copy.
"""
from __future__ import annotations

import gzip
import json
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from auth import TokenData
from features.platform_access import require_admin
from services import blob_private as BP

router = APIRouter(tags=["warehouse"])
_db = None

PARIS = ZoneInfo("Europe/Paris")
STREAMS = {"visits": "visit_time", "offer_uses": "used_at", "rewards_redeemed": "redeemed_at"}
PREFIX = "wh/v1"
NIGHT_FROM, NIGHT_TO = 1, 7          # Paris hours, [from, to)
TICK_BUDGET_S = 20.0
STALE = timedelta(days=3)
REFRESH_EVERY = timedelta(days=30)
_TID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_RANGE = {"$gte", "$gt", "$lte", "$lt"}
FETCH_WORKERS = 32             # every month of two years at once: one Blob wait, not eight
_clock = time.monotonic


def init(db):
    global _db
    _db = db
    try:
        db.warehouse_state.create_index([("tenant_id", 1), ("stream", 1)], unique=True)
    except Exception:
        pass


def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# the file format
# ---------------------------------------------------------------------------
def _enc(o: Any) -> Any:
    if isinstance(o, datetime):
        a = _aware(o).astimezone(timezone.utc).replace(tzinfo=None)
        return {"$d": a.isoformat()}
    raise TypeError(f"not JSON: {type(o).__name__}")


def _dec(d: Dict[str, Any]) -> Any:
    if len(d) == 1 and "$d" in d and isinstance(d["$d"], str):
        return datetime.fromisoformat(d["$d"])
    return d


def encode_rows(rows: Iterable[Dict[str, Any]]) -> bytes:
    lines = [json.dumps(r, default=_enc, ensure_ascii=False, separators=(",", ":")) for r in rows]
    return gzip.compress("".join(x + "\n" for x in lines).encode("utf-8"), compresslevel=6)


def decode_rows(raw: bytes) -> List[Dict[str, Any]]:
    text = gzip.decompress(raw).decode("utf-8")
    return [json.loads(x, object_hook=_dec) for x in text.split("\n") if x]


def month_key(d: datetime) -> str:
    a = _aware(d).astimezone(timezone.utc)
    return f"{a.year:04d}-{a.month:02d}"


def month_bounds(m: str) -> Tuple[datetime, datetime]:
    y, mo = int(m[:4]), int(m[5:7])
    start = datetime(y, mo, 1, tzinfo=timezone.utc)
    end = datetime(y + (mo == 12), 1 if mo == 12 else mo + 1, 1, tzinfo=timezone.utc)
    return start, end


def _path(tid: str, stream: str, m: str, v: int) -> str:
    return f"{PREFIX}/{tid}/{stream}/{m}.v{v}.jsonl.gz"


# ---------------------------------------------------------------------------
# the copy
# ---------------------------------------------------------------------------
def _counts(tid: str, stream: str, field: str, upto: datetime) -> Dict[str, Tuple[int, Optional[datetime]]]:
    """Each UTC month's row count and latest date on the cluster, in one aggregate."""
    out: Dict[str, Tuple[int, Optional[datetime]]] = {}
    for g in _db[stream].aggregate([
            {"$match": {"tenant_id": tid, field: {"$type": "date", "$lt": upto}}},
            {"$group": {"_id": {"y": {"$year": "$" + field}, "m": {"$month": "$" + field}},
                        "n": {"$sum": 1}, "max": {"$max": "$" + field}}}]):
        out[f"{int(g['_id']['y']):04d}-{int(g['_id']['m']):02d}"] = (int(g["n"]), _aware(g.get("max")))
    return out


def _same(info: Optional[Dict[str, Any]], count: Tuple[int, Optional[datetime]]) -> bool:
    """The file still matches the cluster's month: same count, same latest
    date (a new visit always moves the latest date, even if one was deleted)."""
    return bool(info) and int(info.get("n", -1)) == count[0] and _aware(info.get("max")) == count[1]


def _export(tid: str, stream: str, field: str, m: str, upto: datetime, v: int, now: datetime) -> Optional[Dict[str, Any]]:
    s, e = month_bounds(m)
    rows = list(_db[stream].find({"tenant_id": tid, field: {"$gte": s, "$lt": min(e, upto)}}, {"_id": 0}))
    data = encode_rows(rows)
    if not BP.put(_path(tid, stream, m, v), data, "application/gzip"):
        return None
    latest = max((_aware(r.get(field)) for r in rows if _aware(r.get(field))), default=None)
    return {"n": len(rows), "v": v, "at": now, "bytes": len(data), "max": latest}


def _drop(tid: str, stream: str, files: List[Tuple[str, int]]) -> None:
    if files:
        BP.delete([_path(tid, stream, m, v) for m, v in files])


def _today(now: datetime) -> str:
    return now.astimezone(PARIS).date().isoformat()


def _build(key: Dict[str, str], st: Dict[str, Any], field: str, now: datetime, deadline: float) -> bool:
    tid, stream = key["tenant_id"], key["stream"]
    b = st.get("build")
    if not b:
        b = {"cut": now, "todo": sorted(_counts(tid, stream, field, now)), "started": uuid.uuid4().hex}
        _db.warehouse_state.update_one(key, {"$set": {"build": b, "build_months": {}, "ready": False,
                                                      "dirty": False, "error": None},
                                             "$setOnInsert": {"months": {}}}, upsert=True)
        st = {**st, "build": b, "build_months": {}, "months": st.get("months") or {}}
    old = st.get("months") or {}
    done = dict(st.get("build_months") or {})
    cut = _aware(b["cut"])
    for m in list(b["todo"]):
        if _clock() >= deadline:
            return False
        v = max(int((old.get(m) or {}).get("v", 0)), int((done.get(m) or {}).get("v", 0))) + 1
        res = _export(tid, stream, field, m, cut, v, now)
        if res is None:
            _db.warehouse_state.update_one(key, {"$set": {"error": f"{m}: Blob refused the file", "error_at": now}})
            return False
        done[m] = res
        _db.warehouse_state.update_one({**key, "build.started": b["started"]},
                                       {"$set": {f"build_months.{m}": res}, "$pull": {"build.todo": m}})
    r = _db.warehouse_state.update_one(
        {**key, "build.started": b["started"]},
        {"$set": {"months": done, "ready": True, "cut": cut, "synced_on": _today(now), "error": None},
         "$unset": {"build": "", "build_months": ""}})
    if r.matched_count:
        _drop(tid, stream, [(m, int(i["v"])) for m, i in old.items()
                            if m not in done or int(done[m]["v"]) != int(i["v"])])
    return bool(r.matched_count)


def _refresh(key: Dict[str, str], st: Dict[str, Any], field: str, now: datetime, deadline: float) -> bool:
    tid, stream = key["tenant_id"], key["stream"]
    months: Dict[str, Any] = dict(st.get("months") or {})
    cut = _aware(st["cut"])
    counts = _counts(tid, stream, field, now)
    todo = {m for m, c in counts.items() if not _same(months.get(m), c)}
    todo |= {m for m in months if m not in counts}
    stale = sorted((m for m in months if m not in todo and now - (_aware(months[m].get("at")) or now) > REFRESH_EVERY),
                   key=lambda m: _aware(months[m]["at"]))
    todo |= set(stale[:1])
    for m in sorted(todo):
        if _clock() >= deadline:
            return False
        old_v = int((months.get(m) or {}).get("v", 0))
        if m not in counts:
            _db.warehouse_state.update_one(key, {"$unset": {f"months.{m}": ""}})
            _drop(tid, stream, [(m, old_v)] if old_v else [])
            months.pop(m, None)
            continue
        res = _export(tid, stream, field, m, now, old_v + 1, now)
        if res is None:
            _db.warehouse_state.update_one(key, {"$set": {"error": f"{m}: Blob refused the file", "error_at": now}})
            return False
        _db.warehouse_state.update_one(key, {"$set": {f"months.{m}": res}})
        if old_v:
            _drop(tid, stream, [(m, old_v)])
        months[m] = res
    return True                  # the new cut is written by sync_tenant, one write for the shop


def sync_tenant(tid: str, now: datetime, deadline: float) -> bool:
    ok, refreshed = True, []
    states = {s.get("stream"): s for s in _db.warehouse_state.find({"tenant_id": tid})}
    for stream, field in STREAMS.items():
        key = {"tenant_id": tid, "stream": stream}
        st = states.get(stream) or {}
        if st.get("ready") and not st.get("dirty") and st.get("synced_on") == _today(now):
            continue
        if _clock() >= deadline:
            ok = False
            break
        rebuild = not st.get("ready") or st.get("dirty")
        try:
            done = (_build if rebuild else _refresh)(key, st, field, now, deadline)
        except Exception as exc:
            _db.warehouse_state.update_one(key, {"$set": {"error": f"{type(exc).__name__}: {str(exc)[:120]}",
                                                          "error_at": now}}, upsert=True)
            done = False
        if done and not rebuild:
            refreshed.append(stream)
        ok = ok and done
    if refreshed:
        _db.warehouse_state.update_many({"tenant_id": tid, "stream": {"$in": refreshed}, "ready": True},
                                        {"$set": {"cut": now, "synced_on": _today(now), "error": None}})
    return ok


def due(now: Optional[datetime] = None, budget_s: float = TICK_BUDGET_S) -> Dict[str, Any]:
    """The tick: at night, the shops not copied yet today, within the budget."""
    if not BP.configured():
        return {"skipped": "no_store"}
    now = _aware(now) or datetime.now(timezone.utc)
    if not (NIGHT_FROM <= now.astimezone(PARIS).hour < NIGHT_TO):
        return {"skipped": "daytime"}
    t0 = _clock()
    deadline = t0 + budget_s
    today = _today(now)
    finished: Dict[str, int] = {}
    for s in _db.warehouse_state.find({"synced_on": today, "ready": True, "dirty": {"$ne": True}},
                                      {"_id": 0, "tenant_id": 1}):
        finished[s["tenant_id"]] = finished.get(s["tenant_id"], 0) + 1
    live = [t.get("id") for t in _db.tenants.find({}, {"_id": 0, "id": 1})]
    gone = [g for g in _db.warehouse_state.distinct("tenant_id") if g not in set(live)]
    purged = [g for g in gone if forget(g)]
    copied: List[str] = []
    for tid in live:
        if not isinstance(tid, str) or not _TID.match(tid) or finished.get(tid, 0) >= len(STREAMS):
            continue
        if _clock() >= deadline:
            return {"copied": copied, "purged": purged, "stopped": "budget"}
        if sync_tenant(tid, now, deadline):
            copied.append(tid)
    return {"copied": copied, "purged": purged}


def forget(tid: str) -> bool:
    """A shop deleted from the platform: its copy goes too (every file, then
    its state). Kept for the next night if Blob did not delete."""
    files = []
    for st in _db.warehouse_state.find({"tenant_id": tid}):
        for part in ("months", "build_months"):
            files += [_path(tid, st["stream"], m, int(i["v"])) for m, i in (st.get(part) or {}).items()]
    if files and not BP.delete(sorted(set(files))):
        return False
    _db.warehouse_state.delete_many({"tenant_id": tid})
    return True


def mark_dirty(tid: str, why: str) -> None:
    """Old rows changed (a privacy rule, a store tagging): rebuild before any read."""
    if _db is None or not tid:
        return
    _db.warehouse_state.update_many({"tenant_id": tid},
                                    {"$set": {"dirty": True, "ready": False, "dirty_why": why},
                                     "$unset": {"build": "", "build_months": ""}})


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def _within(t: datetime, cond: Dict[str, Any]) -> bool:
    for op, bound in cond.items():
        b = _aware(bound)
        if (op == "$gte" and not t >= b) or (op == "$gt" and not t > b) or \
           (op == "$lte" and not t <= b) or (op == "$lt" and not t < b):
            return False
    return True


def rows(stream: str, tid: str, field: str, cond: Dict[str, Any], projection: Optional[Dict[str, int]] = None,
         now: Optional[datetime] = None) -> Optional[List[Dict[str, Any]]]:
    """The rows of `tid` whose `field` meets `cond` ($gte/$gt/$lte/$lt on
    dates), as the cluster would hand them; None when the copy cannot be
    trusted for this read."""
    if _db is None or stream not in STREAMS or STREAMS[stream] != field or not BP.configured():
        return None
    if not isinstance(tid, str) or not _TID.match(tid) or not cond or set(cond) - _RANGE \
            or any(_aware(b) is None for b in cond.values()):
        return None
    st = _db.warehouse_state.find_one({"tenant_id": tid, "stream": stream})
    if not st or not st.get("ready") or st.get("dirty") or not _aware(st.get("cut")):
        return None
    now = _aware(now) or datetime.now(timezone.utc)
    cut = _aware(st["cut"])
    if now - cut > STALE:
        return None
    lo = max([_aware(cond[k]) for k in ("$gte", "$gt") if k in cond], default=None)
    hi = min([_aware(cond[k]) for k in ("$lte", "$lt") if k in cond], default=None)
    keep = [k for k, on in (projection or {}).items() if on and k != "_id"]
    need = [(m, info) for m, info in sorted((st.get("months") or {}).items())
            if not (month_bounds(m)[0] >= cut or (lo and month_bounds(m)[1] <= lo) or (hi and month_bounds(m)[0] > hi))]

    def load(item):
        m, info = item
        try:
            raw = BP.get(_path(tid, stream, m, int(info["v"])))
            got = decode_rows(raw) if raw is not None else None
        except Exception as exc:
            print(f"warehouse: {tid}/{stream}/{m} unreadable ({type(exc).__name__})")
            return None
        return got if got is not None and len(got) == int(info.get("n", -1)) else None

    if len(need) > 1:            # Blob answers in ~0.1 s a file: two years one by one would wait ~3 s
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(need))) as pool:
            files = list(pool.map(load, need))
    else:
        files = [load(x) for x in need]
    if any(f is None for f in files):
        return None
    out: List[Dict[str, Any]] = []
    for got in files:
        for r in got:
            t = _aware(r.get(field))
            if t is None or t >= cut or not _within(t, cond):
                continue
            out.append({k: r[k] for k in keep if k in r} if keep else r)
    if hi is None or hi >= cut:
        tail = dict(cond)
        if lo is None or lo < cut:
            tail["$gte"] = cut
        out.extend(_db[stream].find({"tenant_id": tid, field: tail}, projection or {"_id": 0}))
    return out


def find(stream: str, tid: str, field: str, cond: Dict[str, Any], projection: Dict[str, int],
         now: Optional[datetime] = None) -> Iterable[Dict[str, Any]]:
    """rows() when the copy is sure, else the cluster as before."""
    got = rows(stream, tid, field, cond, projection, now=now)
    if got is not None:
        return got
    return _db[stream].find({"tenant_id": tid, field: cond}, projection)


# ---------------------------------------------------------------------------
# Super admin: its state, and a write/read/delete check of the store
# ---------------------------------------------------------------------------
@router.get("/api/admin/warehouse")
def status(token_data: TokenData = Depends(require_admin("ai"))):
    streams: Dict[str, Dict[str, Any]] = {s: {"ready": 0, "waiting": 0, "errors": 0, "rows": 0, "bytes": 0,
                                              "last_cut": None} for s in STREAMS}
    for st in _db.warehouse_state.find({}, {"_id": 0}):
        row = streams.get(st.get("stream"))
        if row is None:
            continue
        good = st.get("ready") and not st.get("dirty")
        row["ready" if good else "waiting"] += 1
        row["errors"] += bool(st.get("error"))
        for info in (st.get("months") or {}).values():
            row["rows"] += int(info.get("n") or 0)
            row["bytes"] += int(info.get("bytes") or 0)
        cut = _aware(st.get("cut"))
        if cut and (row["last_cut"] is None or cut > row["last_cut"]):
            row["last_cut"] = cut
    return {"configured": BP.configured(), "streams": streams,
            "night": f"{NIGHT_FROM:02d}:00–{NIGHT_TO:02d}:00 (Paris)"}


@router.post("/api/admin/warehouse/check")
def check(token_data: TokenData = Depends(require_admin("ai"))):
    if token_data.role != "super_admin":
        raise HTTPException(status_code=403, detail="Seul le super admin peut tester l'entrepôt.")
    if not BP.configured():
        return {"ok": False, "step": "config", "detail": "Aucun entrepôt relié (WAREHOUSE_BLOB_READ_WRITE_TOKEN)."}
    path, body = f"wh/check/{uuid.uuid4().hex}.txt", uuid.uuid4().hex.encode()
    t0 = time.monotonic()
    if not BP.put(path, body, "text/plain"):
        return {"ok": False, "step": "write"}
    try:
        back = BP.get(path)
    except BP.BlobError as exc:
        BP.delete([path])
        return {"ok": False, "step": "read", "detail": str(exc)[:120]}
    if back != body:
        BP.delete([path])
        return {"ok": False, "step": "read", "detail": "contenu différent"}
    if not BP.delete([path]):
        return {"ok": False, "step": "delete"}
    return {"ok": True, "ms": round((time.monotonic() - t0) * 1000)}
