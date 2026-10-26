"""
Prediction journal — what FidClic IA said, and what really happened.

User, 2026-10-25 (« prediction journal pehle bana do »): before any trained
model, every guess the client brain makes is written down with its real
outcome. Three uses:

    · accuracy, measured, for the super admin (Super admin › FIDCLIC AI ›
      Précision) — never shown to merchants (user's choice)
    · the training set of the models to come (BG/NBD, LightGBM, bandit): each
      row holds the features the brain had and what followed
    · Bpifrance's experiment journal: each model version against the same
      baselines, on the same rows

WHAT IS LOGGED (kind « next_visit »)
    When a scan leaves a client with a known rhythm (client_brain.known), the
    brain's window for the next visit: centre, from, to, confidence. Beside it,
    two baselines — the plain mean of the client's gaps, and the shop's OWN
    rule (Règles clients › « Client actif », 30 days when never set; user,
    2026-10-25: « dukaan ka apna rule use karo ») — so every figure on the
    page says « better or worse than what the shop already uses ».

THE OUTCOME
    · the client's next visit on another Paris day resolves it: real date,
      error in days (brain and baselines), inside the window or not
    · another scan the same day replaces it (a second scan is not a return)
    · no visit by EXPIRE_FACTOR × rhythm (at least EXPIRE_MIN_DAYS after the
      window) closes it as « non revenu » (the tick) — the label a churn
      model learns from

PRIVACY (user, 2026-10-25: « nateeja aate hi anonymous »)
    customer_id is kept only while the row waits for its outcome; it is
    removed the moment the row is resolved or expired. What stays — the
    shop, its sector, the features and the outcome — names nobody.

BACKTEST (user, 2026-10-25: all shops, live ones included)
    Each client's history is replayed: after every visit day from the third
    on, what the brain would have said, then when they really came back.
    Only this journal is written; no client, card or message is touched. The
    backtest uses the SECTOR's usual rhythm, never today's shop median, so it
    cannot peek at the future. Rerun with « Relancer le backtest »; the tick
    runs it once per shop and model version, one shop per tick.

STORAGE (audit 2026-10-26: ~1 000 bytes a row, about one row per visit;
user: « chhota karo », keep everything, the whole history replayed)
    A row is stored compact — pack() / unpack(): the features in one short
    string, the window, the baselines and the outcome as numbers from the day
    of the last visit (the dates are rebuilt from it), Mongo's _id as its id.
    The fields queries use keep their names. Readers always get the full row
    back, so the figures do not change. Rows written before are converted by
    the tick (compact_due), a batch at a time, and read as they are until then.
"""
from __future__ import annotations

import csv
import io
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from auth import TokenData
from features import client_brain as CB
from features.platform_access import require_admin

MODEL = "brain-v1"            # the brain as #368 shipped it; brain-v2 lives in features/brain_v2
SWITCH_MIN_ROWS = 200         # « Passer à brain-v2 » needs at least this many checked v2 guesses
EXPIRE_FACTOR = 3             # no visit by 3 × the rhythm …
EXPIRE_MIN_DAYS = 60          # … and at least 60 days after the window: « non revenu »
NEAR_DAYS = 7                 # « à ±7 jours », the same yardstick for the brain and the baselines
CONF_BUCKETS = [(0, 40), (40, 60), (60, 80), (80, 101)]

router = APIRouter(tags=["brain-journal"])
_db = None


def init(db):
    global _db
    _db = db
    from features import ai_jobs as JOBS
    JOBS.register("backtest", _backtest_step)
    try:
        db.brain_predictions.create_index([("tenant_id", 1), ("customer_id", 1), ("status", 1)])
        db.brain_predictions.create_index([("status", 1), ("expires_at", 1)])
        db.brain_predictions.create_index([("source", 1), ("model", 1), ("tenant_id", 1)])
    except Exception:
        pass


# the storage order of the features: append new ones at the end, never reorder
FEATURE_KEYS = ("visits_n", "n_gaps", "own_gap", "gap_days", "spread_days", "cv", "confidence", "trend",
                "recent_gap", "earlier_gap", "per_month", "basket", "paid_visits", "prior_gap", "prior_source",
                "weekday", "weekday_share", "slot", "slot_share", "top_item_share", "items_known", "store_share",
                "tenure_days", "month", "last_weekday")
_US = timedelta(microseconds=1)
_TOP = ("kind", "model", "source", "tenant_id", "sector", "made_at", "basis_last", "status")


def _enc(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v)                 # always reads back as the same float
    return str(v).replace(";", ",")


def _dec(v: str) -> Any:
    if v == "":
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _off(last: datetime, d: Any) -> Optional[int]:
    d = CB._aware(d)
    return (d - last) // _US if d else None


def _at(last: datetime, us: Optional[int]) -> Optional[datetime]:
    return last + timedelta(microseconds=us) if us is not None else None


def _expiry(pred: Dict[str, Any]) -> datetime:
    gap = float(pred["gap_days"])
    return CB._aware(pred["to"]) + timedelta(days=max(EXPIRE_MIN_DAYS, (EXPIRE_FACTOR - 1) * gap))


def pack_features(f: Dict[str, Any]) -> str:
    return ";".join(_enc(f.get(k)) for k in FEATURE_KEYS)


def unpack_features(s: Any) -> Dict[str, Any]:
    vals = str(s or "").split(";")
    return {k: _dec(vals[i]) if i < len(vals) else None for i, k in enumerate(FEATURE_KEYS)}


def pack(row: Dict[str, Any]) -> Dict[str, Any]:
    """A full row → what is stored."""
    last = CB._aware(row["basis_last"])
    p, base, o = row.get("pred") or {}, row.get("baselines") or {}, row.get("outcome")
    doc: Dict[str, Any] = {k: row[k] for k in _TOP if k in row}
    if "_id" in row:
        doc["_id"] = row["_id"]
    if row.get("status") == "open":            # the client and the expiry, only while it waits
        doc["customer_id"] = row.get("customer_id")
        doc["expires_at"] = row.get("expires_at")
    doc["p"] = [p.get("gap_days"), p.get("confidence"), _off(last, p.get("from")), _off(last, p.get("to"))]
    doc["b"] = [_off(last, base.get("mean")), base.get("rule_days")]
    doc["f"] = pack_features(row.get("features") or {})
    if o:
        doc["o"] = ([True, o.get("in_window"), o.get("actual_gap"), o.get("error_days"), o.get("error_mean"),
                     o.get("error_rule"), _off(last, o.get("actual"))] if o.get("returned")
                    else [False, bool(o.get("in_window"))])
    return doc


def unpack(doc: Dict[str, Any]) -> Dict[str, Any]:
    """What is stored (compact, or written before) → the full row."""
    if "p" not in doc and "o" not in doc and "f" not in doc:
        row = dict(doc)                         # written before compaction: as it is
        row.setdefault("customer_id", None)
        return row
    row = {k: v for k, v in doc.items() if k not in ("p", "b", "f", "o")}
    row.setdefault("customer_id", None)
    last = CB._aware(doc.get("basis_last"))
    if "p" in doc and last:
        gap, conf, frm, to = (list(doc["p"]) + [None] * 4)[:4]
        row["pred"] = {"centre": last + timedelta(days=gap) if gap is not None else None,
                       "from": _at(last, frm), "to": _at(last, to), "gap_days": gap, "confidence": conf}
        if "expires_at" not in row and row["pred"]["to"] and gap is not None:
            row["expires_at"] = _expiry(row["pred"])
    elif "p" in doc:
        row["pred"] = {"gap_days": doc["p"][0], "confidence": doc["p"][1]}
    if "b" in doc and last:
        mean_us, rule = (list(doc["b"]) + [None] * 2)[:2]
        row["baselines"] = {"mean": _at(last, mean_us),
                            "rule": last + timedelta(days=rule) if rule is not None else None, "rule_days": rule}
    if "f" in doc:
        row["features"] = unpack_features(doc["f"])
    if "o" in doc:
        o = list(doc["o"])
        if o and o[0]:
            o = (o + [None] * 7)[:7]
            row["outcome"] = {"returned": True, "actual": _at(last, o[6]) if last else None, "actual_gap": o[2],
                              "in_window": o[1], "error_days": o[3], "error_mean": o[4], "error_rule": o[5]}
        else:
            row["outcome"] = {"returned": False, "in_window": bool(o[1]) if len(o) > 1 else False}
    return row


def legacy(row: Dict[str, Any]) -> Dict[str, Any]:
    """A full row in the shape written before compaction (tests, figures
    compared before / after)."""
    out = dict(row)
    out.setdefault("id", str(uuid.uuid4()))
    if out.get("status") != "open":
        o = out.get("outcome") or {}
        out["resolved_at"] = o.get("actual") or out.get("expires_at")
        out["customer_id"] = None
    return out


def compact_due(batch: int = 3000, force: bool = False) -> Dict[str, Any]:
    """The tick: rows written before compaction, a batch at a time. Once none
    is left, a mark stops the search (no scan of the journal every tick)."""
    from pymongo import ReplaceOne
    key = "brain_journal_compact"
    mark = _db.platform_settings.find_one({"key": key}, {"_id": 0, "done": 1}) or {}
    if mark.get("done") and not force:
        return {"converted": 0, "done": True}
    docs = list(_db.brain_predictions.find({"features": {"$exists": True}}).limit(batch))
    if docs:
        # the row as read: a scan or the tick that closed it meanwhile wins
        _db.brain_predictions.bulk_write([ReplaceOne({"_id": d["_id"], "status": d.get("status"),
                                                      "features": {"$exists": True}}, pack(unpack(d)))
                                          for d in docs], ordered=False)
    done = len(docs) < batch
    if done:
        _db.platform_settings.update_one({"key": key}, {"$set": {"key": key, "done": True,
                                                                 "at": datetime.now(timezone.utc)}}, upsert=True)
    return {"converted": len(docs), "done": done}


def _paris_day(d: Optional[datetime]):
    d = CB._aware(d)
    return d.astimezone(CB.PARIS).date() if d else None


def rule_days(tid: str) -> int:
    """The shop's own « Client actif » window (features/customer_rules)."""
    try:
        from features import customer_rules as R
        return int(R.active_days(R.load(tid)))
    except Exception:
        return 30


def _sector(tid: str) -> str:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1}) or {}
    return str(t.get("sector") or "other").strip().lower() or "other"


# ---------------------------------------------------------------------------
# one prediction
# ---------------------------------------------------------------------------
def features(b: Dict[str, Any], at: datetime) -> Dict[str, Any]:
    """What the brain knew — the columns a model will learn from. Numbers and
    categories only: no name, no product."""
    first = CB._aware(b.get("first"))
    last = CB._aware(b.get("last"))
    top = (b.get("top_items") or [{}])[0]
    return {
        "visits_n": b.get("visits_n"), "n_gaps": b.get("n_gaps"), "own_gap": b.get("own_gap"),
        "gap_days": b.get("gap_days"), "spread_days": b.get("spread_days"), "cv": b.get("cv"),
        "confidence": b.get("confidence"), "trend": b.get("trend"), "recent_gap": b.get("recent_gap"),
        "earlier_gap": b.get("earlier_gap"), "per_month": b.get("per_month"),
        "basket": b.get("basket"), "paid_visits": b.get("paid_visits"),
        "prior_gap": b.get("prior_gap"), "prior_source": b.get("prior_source"),
        "weekday": (b.get("weekday") or {}).get("key"), "weekday_share": (b.get("weekday") or {}).get("share"),
        "slot": (b.get("slot") or {}).get("key"), "slot_share": (b.get("slot") or {}).get("share"),
        "top_item_share": top.get("share"), "items_known": len(b.get("items_all") or []),
        "store_share": (b.get("store") or {}).get("share"),
        "tenure_days": round(CB._days(first, last), 1) if first and last else None,
        "month": last.astimezone(CB.PARIS).month if last else None,
        "last_weekday": last.astimezone(CB.PARIS).weekday() if last else None,
    }


def _baseline_mean(gaps: List[float]) -> Optional[float]:
    return round(mean(gaps), 1) if gaps else None


def _gaps_of(b: Dict[str, Any], visits: Iterable[Dict[str, Any]]) -> List[float]:
    """The client's gaps between distinct Paris days (as the brain counts them)."""
    days: List[datetime] = []
    for v in sorted((CB._aware(v.get("visit_time")) for v in visits if CB._aware(v.get("visit_time")))):
        if not days or _paris_day(v) != _paris_day(days[-1]):
            days.append(v)
    return [CB._days(days[i - 1], days[i]) for i in range(1, len(days))]


def model_name(b: Dict[str, Any]) -> str:
    return f"brain-v{int(b.get('model') or 1)}"


def make(tid: str, sector: str, b: Dict[str, Any], gaps: List[float], made_at: datetime,
         source: str, customer_id: Optional[str], rule: int = 30,
         model: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """A journal row for the brain's next-visit window, or None when the brain
    has no rhythm to stand on."""
    if not CB.known(b) or not b.get("gap_days"):
        return None
    last = CB._aware(b.get("last"))
    r = CB.rythme(b, last)                      # the window, read the day of the last visit
    gap = float(b["gap_days"])
    centre = last + timedelta(days=gap)
    mean_gap = _baseline_mean(gaps)
    expires = (r["next_to"] + timedelta(days=max(EXPIRE_MIN_DAYS, (EXPIRE_FACTOR - 1) * gap)))
    return {
        "kind": "next_visit", "model": model or model_name(b), "source": source,
        "tenant_id": tid, "sector": sector, "customer_id": customer_id,
        "made_at": made_at, "basis_last": last,
        "pred": {"centre": centre, "from": r["next_from"], "to": r["next_to"],
                 "gap_days": gap, "confidence": b.get("confidence")},
        "baselines": {
            "mean": (last + timedelta(days=mean_gap)) if mean_gap else None,
            "rule": last + timedelta(days=rule), "rule_days": rule,
        },
        "features": features(b, made_at),
        "status": "open", "expires_at": expires,
    }


def _resolve(row: Dict[str, Any], actual: datetime) -> Dict[str, Any]:
    """The client came back: how far was each guess? customer_id leaves."""
    p = row["pred"]
    err = lambda c: round(CB._days(CB._aware(c), actual), 1) if c else None  # noqa: E731 — + late, − early
    base = row.get("baselines") or {}
    return {"status": "resolved", "customer_id": None, "resolved_at": datetime.now(timezone.utc),
            "outcome": {"returned": True, "actual": actual,
                        "actual_gap": round(CB._days(CB._aware(row["basis_last"]), actual), 1),
                        "in_window": CB._aware(p["from"]) <= actual <= CB._aware(p["to"]),
                        "error_days": err(p["centre"]),
                        "error_mean": err(base.get("mean")), "error_rule": err(base.get("rule"))}}


def _expire(row: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    return {"status": "expired", "customer_id": None, "resolved_at": now,
            "outcome": {"returned": False, "in_window": False}}


# ---------------------------------------------------------------------------
# live: every scan
# ---------------------------------------------------------------------------
def record_visit(tid: str, cid: str, brain: Optional[Dict[str, Any]]) -> None:
    """After a scan (server._scan_visit_impl). Never raises."""
    try:
        b = brain or {}
        last = CB._aware(b.get("last"))
        if not last:
            return
        for doc in _db.brain_predictions.find({"tenant_id": tid, "customer_id": cid, "status": "open"}):
            row = unpack(doc)
            if _paris_day(row.get("basis_last")) == _paris_day(last):
                # a second scan the same day: the guess is remade, not judged
                _db.brain_predictions.delete_one({"_id": doc["_id"]})
            else:
                _db.brain_predictions.replace_one({"_id": doc["_id"], "status": "open"},
                                                  pack({**row, **_resolve(row, last)}))
        visits = list(_db.visits.find({"tenant_id": tid, "customer_id": cid}, CB._VISIT_FIELDS))
        sector, rule, now = _sector(tid), rule_days(tid), datetime.now(timezone.utc)
        # the brain in service, and the other one in shadow (user, 2026-10-25):
        # both guess every visit, the journal judges both
        for guess in (b, challenger(tid, b, visits)):
            row = make(tid, sector, guess, _gaps_of(guess, visits), now, "live", cid, rule) if guess else None
            if row:
                _db.brain_predictions.insert_one(pack(row))
    except Exception as exc:
        print(f"brain_journal.record_visit failed (non-fatal): {exc}")


def challenger(tid: str, served: Dict[str, Any], visits: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The other brain's guess for the same client — v2 only once it has
    learned its tables."""
    other = 1 if int(served.get("model") or 1) == 2 else 2
    if other == 2:
        from features import brain_v2 as V2
        if not V2.calibration():
            return None
    args = CB.model_args(tid, other)
    return CB.build(visits, **args)


def expire_due(now: Optional[datetime] = None) -> int:
    """The tick: open rows whose client never came back become « non revenu »."""
    now = now or datetime.now(timezone.utc)
    n = 0
    for doc in _db.brain_predictions.find({"status": "open", "expires_at": {"$lt": now}}).limit(5000):
        row = unpack(doc)
        _db.brain_predictions.replace_one({"_id": doc["_id"], "status": "open"}, pack({**row, **_expire(row, now)}))
        n += 1
    return n


# ---------------------------------------------------------------------------
# backtest: replay the past
# ---------------------------------------------------------------------------
def _replay(tid: str, sector: str, prior: float, rule: int, by: Dict[str, List[Dict[str, Any]]],
            now: datetime) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """The guesses the brain would have made for these clients, judged."""
    rows: List[Dict[str, Any]] = []
    counts = {"clients": 0, "resolved": 0, "expired": 0}
    for cid, visits in by.items():
        visits.sort(key=lambda v: CB._aware(v["visit_time"]))
        # the index of the last visit of each distinct Paris day
        ends: List[int] = []
        for i, v in enumerate(visits):
            if ends and _paris_day(visits[ends[-1]]["visit_time"]) == _paris_day(v["visit_time"]):
                ends[-1] = i
            else:
                ends.append(i)
        made = 0
        for k, end in enumerate(ends):
            past = visits[:end + 1]
            at = CB._aware(past[-1]["visit_time"])
            b = CB.build(past, prior, "secteur", at)
            row = make(tid, sector, b, _gaps_of(b, past), at, "backtest", None, rule, model=MODEL)
            if not row:
                continue
            if k + 1 < len(ends):
                row.update(_resolve(row, CB._aware(visits[ends[k] + 1]["visit_time"])))
                counts["resolved"] += 1
            elif row["expires_at"] < now:
                row.update(_expire(row, now))
                counts["expired"] += 1
            else:
                continue                 # still waiting: the live row covers it
            row["customer_id"] = None
            rows.append(row)
            made += 1
        counts["clients"] += 1 if made else 0
    return rows, counts


def _insert_rows(docs: List[Dict[str, Any]]) -> None:
    for i in range(0, len(docs), 1000):
        _db.brain_predictions.insert_many(docs[i:i + 1000])


def _clients(tid: str) -> List[str]:
    return sorted(c for c in _db.visits.distinct("customer_id", {"tenant_id": tid}) if c)


def _backtest_step(job: Dict[str, Any], deadline: float) -> bool:
    """One shop's backtest, CHUNK clients a slice (features/ai_jobs). The new
    rows wait aside (« run ») until the last slice swaps them in."""
    from features import ai_jobs as JOBS
    tid, run = job["tenant_id"], job["run"]
    now = CB._aware(job["now"])
    st = dict(job.get("state") or {})
    if "sector" not in st:
        sector = _sector(tid)
        st = {"sector": sector, "prior": CB.sector_gap(sector), "rule": rule_days(tid), "cursor": None, "chunk": 0,
              "counts": {"clients": 0, "resolved": 0, "expired": 0}}
        JOBS.save(job, state=st, total=len(_clients(tid)), done=0, phase="clients")
    while True:
        # what a slice killed half-way had written
        _db.brain_predictions.delete_many({"run": run, "chunk": {"$gte": st["chunk"]}})
        todo = [c for c in _clients(tid) if st["cursor"] is None or c > st["cursor"]][:JOBS.CHUNK]
        if not todo:
            _finish_backtest(tid, run, now, st["counts"])
            return True
        by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": todo}}, CB._VISIT_FIELDS):
            if CB._aware(v.get("visit_time")):
                by[v["customer_id"]].append(v)
        rows, counts = _replay(tid, st["sector"], float(st["prior"]), int(st["rule"]), by, now)
        _insert_rows([{**pack(r), "run": run, "chunk": st["chunk"]} for r in rows])
        st = {**st, "cursor": todo[-1], "chunk": st["chunk"] + 1,
              "counts": {k: st["counts"][k] + counts[k] for k in counts}}
        JOBS.save(job, state=st, done=int(job.get("done") or 0) + len(todo))
        if time.monotonic() >= deadline:
            return False


def _finish_backtest(tid: str, run: str, now: datetime, counts: Dict[str, int]) -> None:
    """The new run takes the old one's place, at once."""
    _db.brain_predictions.delete_many({"tenant_id": tid, "source": "backtest", "model": MODEL,
                                       "run": {"$exists": False}})
    _db.brain_predictions.update_many({"run": run}, {"$unset": {"run": "", "chunk": ""}})
    _db.platform_settings.update_one(
        {"key": f"brain_backtest:{tid}"},
        {"$set": {"key": f"brain_backtest:{tid}", "model": MODEL, "at": now, **counts}}, upsert=True)
    seed_open(tid)


def backtest(tid: str, now: Optional[datetime] = None) -> Dict[str, int]:
    """Replay every client's history for one shop, in one go (scripts,
    tests). Writes this journal only."""
    from features import ai_jobs as JOBS
    job = JOBS.run_now("backtest", tid, now or datetime.now(timezone.utc))
    return dict((job.get("state") or {}).get("counts") or {"clients": 0, "resolved": 0, "expired": 0})


def seed_open(tid: str) -> int:
    """Clients who already have a rhythm get their open live row (the journal
    starts today for them, without waiting for their next scan)."""
    have = set(_db.brain_predictions.distinct("customer_id", {"tenant_id": tid, "status": "open",
                                                              "model": f"brain-v{CB.champion()}"}))
    sector = _sector(tid)
    rule = rule_days(tid)
    n = 0
    for c in _db.customers.find({"tenant_id": tid, "deleted_at": None, "brain.v": CB.VERSION,
                                 "brain.n_gaps": {"$gte": CB.RHYTHM_MIN_VISITS - 1}},
                                {"_id": 0, "id": 1, "brain": 1}):
        if c["id"] in have:
            continue
        visits = _db.visits.find({"tenant_id": tid, "customer_id": c["id"]}, {"_id": 0, "visit_time": 1})
        row = make(tid, sector, c["brain"], _gaps_of(c["brain"], visits), datetime.now(timezone.utc), "live",
                   c["id"], rule)
        if row:
            _db.brain_predictions.insert_one(pack(row))
            n += 1
    return n


def backtest_due() -> List[str]:
    """The tick: a shop never replayed by this model version gets its job."""
    from features import ai_jobs as JOBS
    queued: List[str] = []
    for tid in _db.tenants.distinct("id"):
        mark = _db.platform_settings.find_one({"key": f"brain_backtest:{tid}"}, {"_id": 0, "model": 1})
        if mark and mark.get("model") == MODEL:
            continue
        if not _db.visits.find_one({"tenant_id": tid}, {"_id": 1}):
            _db.platform_settings.update_one({"key": f"brain_backtest:{tid}"},
                                             {"$set": {"key": f"brain_backtest:{tid}", "model": MODEL,
                                                       "at": datetime.now(timezone.utc), "clients": 0}},
                                             upsert=True)
            continue
        job, created = JOBS.start("backtest", tid, by="tick")
        if created:
            queued.append(tid)
    return queued


def tick() -> Dict[str, Any]:
    from features import ai_jobs as JOBS
    from features import brain_v2 as V2
    out: Dict[str, Any] = {"expired": expire_due(), "queued": backtest_due()}
    try:
        out["compact"] = compact_due()
    except Exception as exc:
        out["compact_error"] = str(exc)[:120]
    try:                              # brain-v2 learns its tables once a day
        out["v2"] = V2.learn_due()
    except Exception as exc:
        out["v2_error"] = str(exc)[:120]
    # the long work: backtests and brain-v2's learning, a slice at a time
    finished = JOBS.run()
    out["backtest"] = {j["tenant_id"]: (j.get("state") or {}).get("counts") for j in finished if j["kind"] == "backtest"}
    out["learned"] = [j["run"] for j in finished if j["kind"] == "learn"]
    return out


# ---------------------------------------------------------------------------
# the figures
# ---------------------------------------------------------------------------
def _pct(n: int, d: int) -> Optional[int]:
    return round(100 * n / d) if d else None


def _mae(vals: List[Optional[float]]) -> Optional[float]:
    v = [abs(x) for x in vals if x is not None]
    return round(median(v), 1) if v else None


def _near(vals: List[Optional[float]]) -> Optional[int]:
    v = [x for x in vals if x is not None]
    return _pct(sum(1 for x in v if abs(x) <= NEAR_DAYS), len(v))


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [r for r in rows if r.get("status") == "resolved"]
    gone = [r for r in rows if r.get("status") == "expired"]
    errs = [(r.get("outcome") or {}).get("error_days") for r in done]
    calib = []
    for lo, hi in CONF_BUCKETS:
        b = [r for r in done if lo <= int((r.get("pred") or {}).get("confidence") or 0) < hi]
        if b:
            calib.append({"label": f"{lo}–{min(hi, 100)} %", "said": round(mean(
                int(r["pred"]["confidence"] or 0) for r in b)),
                "real": _pct(sum(1 for r in b if r["outcome"]["in_window"]), len(b)), "n": len(b)})
    late = [e for e in errs if e is not None and e > 0]
    return {
        "checked": len(done), "not_returned": len(gone),
        "open": sum(1 for r in rows if r.get("status") == "open"),
        "in_window": _pct(sum(1 for r in done if r["outcome"]["in_window"]), len(done)),
        "brain": {"median_error": _mae(errs), "near": _near(errs)},
        "mean": {"median_error": _mae([(r.get("outcome") or {}).get("error_mean") for r in done]),
                 "near": _near([(r.get("outcome") or {}).get("error_mean") for r in done])},
        "rule": {"median_error": _mae([(r.get("outcome") or {}).get("error_rule") for r in done]),
                 "near": _near([(r.get("outcome") or {}).get("error_rule") for r in done])},
        "came_late": _pct(len(late), len([e for e in errs if e is not None])),
        "calibration": calib,
    }


# what the figures read (compact rows: p, o, from basis_last; rows written before: pred, outcome)
_FIELDS = {"_id": 0, "status": 1, "pred.confidence": 1, "outcome": 1, "p": 1, "o": 1, "basis_last": 1,
           "sector": 1, "tenant_id": 1, "source": 1, "model": 1, "made_at": 1}


def compare(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """v1 and v2 side by side, with the two baselines (from v1's rows), and
    whether v2 has earned the switch: more checked guesses than
    SWITCH_MIN_ROWS and a smaller median error than BOTH v1 and the plain
    mean (user, 2026-10-24: « v2 tabhi live jab dono ko harayega »)."""
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r.get("model") or MODEL].append(r)
    v1, v2 = summarise(by.get("brain-v1", [])), summarise(by.get("brain-v2", []))
    e1, e2, em = v1["brain"]["median_error"], v2["brain"]["median_error"], v1["mean"]["median_error"]
    reasons = []
    if v2["checked"] < SWITCH_MIN_ROWS:
        reasons.append(f"brain-v2 n'a que {v2['checked']} prédictions vérifiées (il en faut {SWITCH_MIN_ROWS}).")
    if e2 is None or e1 is None or e2 >= e1:
        reasons.append("brain-v2 ne se trompe pas moins que brain-v1.")
    if e2 is None or em is None or e2 >= em:
        reasons.append("brain-v2 ne se trompe pas moins que la moyenne simple.")
    return {"v1": v1, "v2": v2, "can_switch": not reasons, "why_not": reasons}


@router.get("/api/admin/ai/precision")
def precision(source: str = Query("all"), sector: str = Query(""), tenant: str = Query(""),
              model: str = Query(""), token_data: TokenData = Depends(require_admin("ai"))):
    from features import ai_jobs as JOBS
    from features import brain_v2 as V2
    champ = f"brain-v{CB.champion(fresh=True)}"
    model = model if model in ("brain-v1", "brain-v2") else champ
    q: Dict[str, Any] = {"kind": "next_visit", "run": {"$exists": False}}     # a run being written waits aside
    if source in ("live", "backtest"):
        q["source"] = source
    if sector:
        q["sector"] = sector
    if tenant:
        q["tenant_id"] = tenant
    every = [unpack(d) for d in _db.brain_predictions.find(q, _FIELDS)]
    rows = [r for r in every if (r.get("model") or MODEL) == model]
    by_sector: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_month: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sector[r.get("sector") or "other"].append(r)
        made = CB._aware(r.get("made_at"))
        if made:
            by_month[made.astimezone(CB.PARIS).strftime("%Y-%m")].append(r)
    names = {t["id"]: t.get("name") or t["id"] for t in _db.tenants.find({}, {"_id": 0, "id": 1, "name": 1})}
    runs = [{"tenant": names.get(m["key"].split(":", 1)[1], m["key"]), "model": m.get("model"),
             "at": CB._aware(m.get("at")).isoformat() if CB._aware(m.get("at")) else None,
             "clients": m.get("clients", 0), "resolved": m.get("resolved", 0), "expired": m.get("expired", 0)}
            for m in _db.platform_settings.find({"key": {"$regex": "^brain_backtest:"}}, {"_id": 0})]
    learned = V2._doc(fresh=True) or {}
    return {
        "model": model, "champion": champ,
        "compare": compare(every),
        "learned": ({"at": CB._aware(learned.get("learned_at")).isoformat(), "shops": learned.get("shops"),
                     "returns": learned.get("returns"), "groups": len((learned.get("calib") or {}).get("buckets") or {})}
                    if learned.get("learned_at") else None),
        "summary": summarise(rows),
        "sectors": sorted(({"sector": k, **summarise(v)} for k, v in by_sector.items()),
                          key=lambda x: -x["checked"]),
        "months": [{"month": k, **summarise(v)} for k, v in sorted(by_month.items())][-12:],
        "tenants": sorted(({"id": t, "name": names.get(t, t)} for t in {r.get("tenant_id") for r in rows} if t),
                          key=lambda x: str(x["name"]).lower()),
        "runs": sorted(runs, key=lambda x: x["tenant"].lower()),
        "jobs": JOBS.progress(names),
        "rules": {"near_days": NEAR_DAYS,
                  "expire": f"{EXPIRE_FACTOR} × son rythme, au moins {EXPIRE_MIN_DAYS} jours après la fourchette"},
    }


class BacktestIn(BaseModel):
    tenant_id: Optional[str] = None


class ChampionIn(BaseModel):
    model: str


@router.post("/api/admin/ai/precision/champion")
def set_champion(body: ChampionIn, token_data: TokenData = Depends(require_admin("ai"))):
    """« Passer à brain-v2 » / « Revenir à brain-v1 ». v2 only once it has
    beaten v1 and the plain mean on the journal; back to v1 at any time.
    Every client is then re-learned by the new brain (the tick, a few
    thousand at a time; a profile opened before that is re-learned at once)."""
    from fastapi import HTTPException
    if body.model not in ("brain-v1", "brain-v2"):
        raise HTTPException(status_code=400, detail="Modèle inconnu.")
    if body.model == "brain-v2":
        c = compare([unpack(d) for d in _db.brain_predictions.find({"kind": "next_visit", "run": {"$exists": False}},
                                                                   _FIELDS)])
        if not c["can_switch"]:
            raise HTTPException(status_code=409, detail=" ".join(c["why_not"]))
    value = 2 if body.model == "brain-v2" else 1
    _db.platform_settings.update_one({"key": "brain_champion"}, {"$set": {
        "key": "brain_champion", "value": value, "at": datetime.now(timezone.utc),
        "by": getattr(token_data, "email", None)}}, upsert=True)
    CB.champion(fresh=True)
    return {"champion": body.model}


@router.post("/api/admin/ai/precision/learn")
def relearn(token_data: TokenData = Depends(require_admin("ai"))):
    """« Réapprendre brain-v2 »: queued at once, learned in the tick's slices
    (user, 2026-10-26); its old tables serve until the new ones are done."""
    from features import ai_jobs as JOBS
    job, created = JOBS.start("learn", None, by=getattr(token_data, "email", None))
    return {"started": created, "job": job["id"]}


@router.post("/api/admin/ai/precision/backtest")
def run_backtest(body: BacktestIn, token_data: TokenData = Depends(require_admin("ai"))):
    """« Relancer le backtest »: one shop, or every shop that has visits —
    queued at once, replayed in the tick's slices (user, 2026-10-26); the
    figures shown stay those of the last complete run until it ends."""
    from fastapi import HTTPException
    from features import ai_jobs as JOBS
    if body.tenant_id and not _db.tenants.find_one({"id": body.tenant_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Boutique inconnue.")
    tids = [body.tenant_id] if body.tenant_id else sorted(t for t in _db.visits.distinct("tenant_id") if t)
    started, running = [], []
    for tid in tids:
        job, created = JOBS.start("backtest", tid, by=getattr(token_data, "email", None))
        (started if created else running).append(tid)
    return {"started": started, "running": running}


CSV_COLUMNS = ["model", "source", "sector", "made_at", "status", "returned", "in_window", "actual_gap",
               "pred_gap", "confidence", "error_days", "error_mean", "error_rule", "rule_days"]


@router.get("/api/admin/ai/precision/export.csv")
def export(token_data: TokenData = Depends(require_admin("ai"))):
    """Every checked row, anonymous: the training set, and the journal's proof."""
    cols = CSV_COLUMNS
    fcols: List[str] = list(features({}, datetime.now(timezone.utc)).keys())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols + [f"f_{c}" for c in fcols])
    for d in _db.brain_predictions.find({"kind": "next_visit", "status": {"$in": ["resolved", "expired"]},
                                         "run": {"$exists": False}},
                                        {"_id": 0, "customer_id": 0, "tenant_id": 0}):
        r = unpack(d)
        o, p, f = r.get("outcome") or {}, r.get("pred") or {}, r.get("features") or {}
        made = CB._aware(r.get("made_at"))
        w.writerow([r.get("model"), r.get("source"), r.get("sector"), made.date().isoformat() if made else "",
                    r.get("status"), o.get("returned"), o.get("in_window"), o.get("actual_gap"),
                    p.get("gap_days"), p.get("confidence"), o.get("error_days"), o.get("error_mean"),
                    o.get("error_rule"), (r.get("baselines") or {}).get("rule_days")] + [f.get(c) for c in fcols])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="fidclic-ia-journal.csv"'})
