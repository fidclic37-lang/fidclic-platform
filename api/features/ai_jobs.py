"""
Long FidClic IA work in the background, a slice at a time.

User, 2026-10-26 (audit: « Relancer le backtest » did the whole work in one
request and Vercel cut it; the tick backtested a whole shop at once, so a
big shop never finished and was started again every 15 minutes):

    · the button answers at once (« lancé »); the work runs in the tick,
      in slices, and the Précision page shows how far it got
    · the old figures stay until the new run is complete (each kind writes
      its new rows aside, marked with its run, and swaps them in at the end)
    · « Réapprendre brain-v2 » the same way

A job is one row of `ai_jobs`. The tick gives the jobs BUDGET_S seconds;
each handler does at least one slice, saves where it stopped, and returns
True once finished. A job being worked holds a lease (JOB_LEASE, longer than
a function may live): a second tick leaves it alone, and a slice killed
half-way is taken up after the lease — the handler first deletes what that
slice had half-written. Three failures in a row and the job stops (« échec »
on the page) until someone starts it again.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

JOB_LEASE = timedelta(minutes=10)      # > vercel.json maxDuration (360 s), < the 15-minute tick
BUDGET_S = 90                          # the tick's time for these jobs
CHUNK = 200                            # clients per slice
MAX_ERRORS = 3
ACTIVE = ["queued", "running"]
LABELS = {"backtest": "Backtest", "learn": "Réapprentissage de brain-v2"}

_db = None
_HANDLERS: Dict[str, Callable[[Dict[str, Any], float], bool]] = {}


def init(db):
    global _db
    _db = db
    try:
        db.ai_jobs.create_index([("status", 1), ("created_at", 1)])
        db.ai_jobs.create_index([("kind", 1), ("tenant_id", 1), ("status", 1)])
    except Exception:
        pass


def register(kind: str, handler: Callable[[Dict[str, Any], float], bool]) -> None:
    _HANDLERS[kind] = handler


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start(kind: str, tenant_id: Optional[str] = None, by: Optional[str] = None,
          now: Optional[datetime] = None) -> Tuple[Dict[str, Any], bool]:
    """Queue a job — or give back the one already queued or running."""
    q = {"kind": kind, "tenant_id": tenant_id, "status": {"$in": ACTIVE}}
    have = _db.ai_jobs.find_one(q, {"_id": 0})
    if have:
        return have, False
    at = _now()
    job = {"id": str(uuid.uuid4()), "kind": kind, "tenant_id": tenant_id, "status": "queued",
           "run": str(uuid.uuid4()), "now": now or at, "created_at": at, "by": by,
           "done": 0, "total": None, "phase": None, "state": {}, "lease": None, "errors": 0}
    _db.ai_jobs.insert_one(dict(job))
    return job, True


def save(job: Dict[str, Any], **fields: Any) -> None:
    """A handler's progress (the job dict follows)."""
    job.update(fields)
    _db.ai_jobs.update_one({"id": job["id"]}, {"$set": fields})


def _claim(at: datetime, job_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    q: Dict[str, Any] = {"status": {"$in": ACTIVE},
                         "$or": [{"lease": None}, {"lease": {"$lt": at - JOB_LEASE}}]}
    if job_id:
        q["id"] = job_id
    from pymongo import ReturnDocument
    job = _db.ai_jobs.find_one_and_update(q, {"$set": {"lease": at, "status": "running"}},
                                          sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
    if job:
        job.pop("_id", None)
    return job


def _work(job: Dict[str, Any], deadline: float) -> bool:
    """One handler call on a claimed job. True: the job is finished."""
    try:
        done = _HANDLERS[job["kind"]](job, deadline)
    except Exception as exc:
        errors = int(job.get("errors") or 0) + 1
        save(job, errors=errors, error=str(exc)[:200], lease=None,
             status="failed" if errors >= MAX_ERRORS else "running")
        print(f"ai_jobs: {job['kind']} {job.get('tenant_id')} failed ({exc})")
        return False
    if done:
        save(job, status="done", finished_at=_now(), lease=None, errors=0, error=None)
    else:
        save(job, lease=None, errors=0, error=None)
    return bool(done)


def run(budget_s: float = BUDGET_S, slices: Optional[int] = None,
        at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The tick: work the queue for budget_s seconds (at least one slice).
    Returns the jobs it finished."""
    at = at or _now()
    end = time.monotonic() + budget_s
    finished: List[Dict[str, Any]] = []
    n = 0
    while slices is None or n < slices:
        if slices is None and n and time.monotonic() >= end:
            break                                  # (a count of slices, when given, decides instead)
        job = _claim(at)
        if not job:
            break
        n += 1
        if _work(job, end):
            finished.append(job)
    return finished


def run_now(kind: str, tenant_id: Optional[str], now: datetime, by: str = "direct") -> Dict[str, Any]:
    """The whole work in one go (tests, scripts): any job of this kind for
    this shop is dropped, a new one runs to its end."""
    for old in _db.ai_jobs.find({"kind": kind, "tenant_id": tenant_id, "status": {"$in": ACTIVE}}, {"_id": 0}):
        _db.ai_jobs.update_one({"id": old["id"]}, {"$set": {"status": "cancelled", "lease": None}})
        _db.brain_predictions.delete_many({"run": old["run"]})
        _db.brain_v2_stage.delete_many({"run": old["run"]})
    job, _ = start(kind, tenant_id, by=by, now=now)
    while True:
        claimed = _claim(_now(), job["id"])
        if not claimed:
            raise RuntimeError(f"ai_jobs: {kind} {tenant_id} could not be claimed")
        if _work(claimed, float("inf")):
            return claimed
        if claimed.get("status") == "failed":
            raise RuntimeError(claimed.get("error") or "failed")


def progress(names: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """For the Précision page: what runs, what failed, what just ended."""
    names = names or {}
    recent = _now() - timedelta(minutes=30)
    out: List[Dict[str, Any]] = []
    seen = set()
    for j in _db.ai_jobs.find({"by": {"$ne": "direct"}}, {"_id": 0, "state": 0}).sort("created_at", -1).limit(200):
        key = (j["kind"], j.get("tenant_id"))
        if key in seen:
            continue                                  # the latest job of each shop / kind only
        seen.add(key)
        fin = j.get("finished_at")
        if fin and fin.tzinfo is None:
            fin = fin.replace(tzinfo=timezone.utc)
        if j["status"] in ("done", "cancelled") and not (fin and fin >= recent and j["status"] == "done"):
            continue
        shop = names.get(j.get("tenant_id") or "", j.get("tenant_id"))
        out.append({"id": j["id"], "kind": j["kind"], "tenant_id": j.get("tenant_id"),
                    "label": LABELS.get(j["kind"], j["kind"]) + (f" · {shop}" if shop else ""),
                    "status": j["status"], "phase": j.get("phase"), "done": int(j.get("done") or 0),
                    "total": j.get("total"), "error": j.get("error"),
                    "started_at": _iso(j.get("created_at")), "finished_at": _iso(fin)})
    return out


def _iso(d: Any) -> Optional[str]:
    if not d:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()
