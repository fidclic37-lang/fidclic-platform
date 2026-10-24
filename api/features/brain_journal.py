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
    two baselines a shop or a simple tool would use — the plain mean of the
    client's gaps, and the fixed « 30 jours » rule — so every figure on the
    page says « better or worse than what exists ».

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
"""
from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from auth import TokenData
from features import client_brain as CB
from features.platform_access import require_admin

MODEL = f"brain-v{CB.VERSION}"
FIXED_RULE_DAYS = 30          # « inactif après 30 jours », the rule most tools ship with
EXPIRE_FACTOR = 3             # no visit by 3 × the rhythm …
EXPIRE_MIN_DAYS = 60          # … and at least 60 days after the window: « non revenu »
NEAR_DAYS = 7                 # « à ±7 jours », the same yardstick for the brain and the baselines
CONF_BUCKETS = [(0, 40), (40, 60), (60, 80), (80, 101)]

router = APIRouter(tags=["brain-journal"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.brain_predictions.create_index([("tenant_id", 1), ("customer_id", 1), ("status", 1)])
        db.brain_predictions.create_index([("status", 1), ("expires_at", 1)])
        db.brain_predictions.create_index([("source", 1), ("model", 1), ("tenant_id", 1)])
    except Exception:
        pass


def _paris_day(d: Optional[datetime]):
    d = CB._aware(d)
    return d.astimezone(CB.PARIS).date() if d else None


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


def make(tid: str, sector: str, b: Dict[str, Any], gaps: List[float], made_at: datetime,
         source: str, customer_id: Optional[str]) -> Optional[Dict[str, Any]]:
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
        "id": str(uuid.uuid4()), "kind": "next_visit", "model": MODEL, "source": source,
        "tenant_id": tid, "sector": sector, "customer_id": customer_id,
        "made_at": made_at, "basis_last": last,
        "pred": {"centre": centre, "from": r["next_from"], "to": r["next_to"],
                 "gap_days": gap, "confidence": b.get("confidence")},
        "baselines": {
            "mean": (last + timedelta(days=mean_gap)) if mean_gap else None,
            "fixed30": last + timedelta(days=FIXED_RULE_DAYS),
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
                        "error_mean": err(base.get("mean")), "error_fixed30": err(base.get("fixed30"))}}


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
        for row in _db.brain_predictions.find({"tenant_id": tid, "customer_id": cid, "status": "open"}, {"_id": 0}):
            if _paris_day(row.get("basis_last")) == _paris_day(last):
                # a second scan the same day: the guess is remade, not judged
                _db.brain_predictions.delete_one({"id": row["id"]})
            else:
                _db.brain_predictions.update_one({"id": row["id"]}, {"$set": _resolve(row, last)})
        visits = _db.visits.find({"tenant_id": tid, "customer_id": cid}, {"_id": 0, "visit_time": 1})
        row = make(tid, _sector(tid), b, _gaps_of(b, visits), datetime.now(timezone.utc), "live", cid)
        if row:
            _db.brain_predictions.insert_one(row)
    except Exception as exc:
        print(f"brain_journal.record_visit failed (non-fatal): {exc}")


def expire_due(now: Optional[datetime] = None) -> int:
    """The tick: open rows whose client never came back become « non revenu »."""
    now = now or datetime.now(timezone.utc)
    n = 0
    for row in _db.brain_predictions.find({"status": "open", "expires_at": {"$lt": now}}, {"_id": 0}).limit(5000):
        _db.brain_predictions.update_one({"id": row["id"], "status": "open"}, {"$set": _expire(row, now)})
        n += 1
    return n


# ---------------------------------------------------------------------------
# backtest: replay the past
# ---------------------------------------------------------------------------
def backtest(tid: str, now: Optional[datetime] = None) -> Dict[str, int]:
    """Replay every client's history for one shop. Writes this journal only."""
    now = now or datetime.now(timezone.utc)
    sector = _sector(tid)
    prior = CB.sector_gap(sector)
    _db.brain_predictions.delete_many({"tenant_id": tid, "source": "backtest"})
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$ne": None}}, CB._VISIT_FIELDS):
        if CB._aware(v.get("visit_time")):
            by[v["customer_id"]].append(v)
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
            row = make(tid, sector, b, _gaps_of(b, past), at, "backtest", None)
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
    for i in range(0, len(rows), 1000):
        _db.brain_predictions.insert_many(rows[i:i + 1000])
    _db.platform_settings.update_one(
        {"key": f"brain_backtest:{tid}"},
        {"$set": {"key": f"brain_backtest:{tid}", "model": MODEL, "at": now, **counts}}, upsert=True)
    return counts


def seed_open(tid: str) -> int:
    """Clients who already have a rhythm get their open live row (the journal
    starts today for them, without waiting for their next scan)."""
    have = set(_db.brain_predictions.distinct("customer_id", {"tenant_id": tid, "status": "open"}))
    sector = _sector(tid)
    n = 0
    for c in _db.customers.find({"tenant_id": tid, "deleted_at": None, "brain.v": CB.VERSION,
                                 "brain.n_gaps": {"$gte": CB.RHYTHM_MIN_VISITS - 1}},
                                {"_id": 0, "id": 1, "brain": 1}):
        if c["id"] in have:
            continue
        visits = _db.visits.find({"tenant_id": tid, "customer_id": c["id"]}, {"_id": 0, "visit_time": 1})
        row = make(tid, sector, c["brain"], _gaps_of(c["brain"], visits), datetime.now(timezone.utc), "live", c["id"])
        if row:
            _db.brain_predictions.insert_one(row)
            n += 1
    return n


def backtest_due(budget: int = 1) -> Dict[str, Any]:
    """The tick: each shop is replayed once per model version, one per tick."""
    done: Dict[str, Any] = {}
    for tid in _db.tenants.distinct("id"):
        if len(done) >= budget:
            break
        mark = _db.platform_settings.find_one({"key": f"brain_backtest:{tid}"}, {"_id": 0, "model": 1})
        if mark and mark.get("model") == MODEL:
            continue
        if not _db.visits.find_one({"tenant_id": tid}, {"_id": 1}):
            _db.platform_settings.update_one({"key": f"brain_backtest:{tid}"},
                                             {"$set": {"key": f"brain_backtest:{tid}", "model": MODEL,
                                                       "at": datetime.now(timezone.utc), "clients": 0}},
                                             upsert=True)
            continue
        done[tid] = {**backtest(tid), "open": seed_open(tid)}
    return done


def tick() -> Dict[str, Any]:
    return {"expired": expire_due(), "backtest": backtest_due()}


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
        "fixed30": {"median_error": _mae([(r.get("outcome") or {}).get("error_fixed30") for r in done]),
                    "near": _near([(r.get("outcome") or {}).get("error_fixed30") for r in done])},
        "came_late": _pct(len(late), len([e for e in errs if e is not None])),
        "calibration": calib,
    }


_FIELDS = {"_id": 0, "status": 1, "pred.confidence": 1, "outcome": 1, "sector": 1, "tenant_id": 1,
           "source": 1, "model": 1, "made_at": 1}


@router.get("/api/admin/ai/precision")
def precision(source: str = Query("all"), sector: str = Query(""), tenant: str = Query(""),
              token_data: TokenData = Depends(require_admin("ai"))):
    q: Dict[str, Any] = {"kind": "next_visit"}
    if source in ("live", "backtest"):
        q["source"] = source
    if sector:
        q["sector"] = sector
    if tenant:
        q["tenant_id"] = tenant
    rows = list(_db.brain_predictions.find(q, _FIELDS))
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
    return {
        "model": MODEL,
        "summary": summarise(rows),
        "sectors": sorted(({"sector": k, **summarise(v)} for k, v in by_sector.items()),
                          key=lambda x: -x["checked"]),
        "months": [{"month": k, **summarise(v)} for k, v in sorted(by_month.items())][-12:],
        "tenants": sorted(({"id": t, "name": names.get(t, t)} for t in {r.get("tenant_id") for r in rows} if t),
                          key=lambda x: str(x["name"]).lower()),
        "runs": sorted(runs, key=lambda x: x["tenant"].lower()),
        "rules": {"near_days": NEAR_DAYS, "fixed_days": FIXED_RULE_DAYS,
                  "expire": f"{EXPIRE_FACTOR} × son rythme, au moins {EXPIRE_MIN_DAYS} jours après la fourchette"},
    }


class BacktestIn(BaseModel):
    tenant_id: Optional[str] = None


@router.post("/api/admin/ai/precision/backtest")
def run_backtest(body: BacktestIn, token_data: TokenData = Depends(require_admin("ai"))):
    """« Relancer le backtest »: one shop, or every shop that has visits."""
    tids = [body.tenant_id] if body.tenant_id else _db.visits.distinct("tenant_id")
    out = {}
    for tid in tids:
        if tid:
            out[tid] = {**backtest(tid), "open": seed_open(tid)}
    return {"done": out}


@router.get("/api/admin/ai/precision/export.csv")
def export(token_data: TokenData = Depends(require_admin("ai"))):
    """Every checked row, anonymous: the training set, and the journal's proof."""
    cols = ["model", "source", "sector", "made_at", "status", "returned", "in_window", "actual_gap",
            "pred_gap", "confidence", "error_days", "error_mean", "error_fixed30"]
    fcols: List[str] = list(features({}, datetime.now(timezone.utc)).keys())
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols + [f"f_{c}" for c in fcols])
    for r in _db.brain_predictions.find({"kind": "next_visit", "status": {"$in": ["resolved", "expired"]}},
                                        {"_id": 0, "customer_id": 0, "tenant_id": 0}):
        o, p, f = r.get("outcome") or {}, r.get("pred") or {}, r.get("features") or {}
        made = CB._aware(r.get("made_at"))
        w.writerow([r.get("model"), r.get("source"), r.get("sector"), made.date().isoformat() if made else "",
                    r.get("status"), o.get("returned"), o.get("in_window"), o.get("actual_gap"),
                    p.get("gap_days"), p.get("confidence"), o.get("error_days"), o.get("error_mean"),
                    o.get("error_fixed30")] + [f.get(c) for c in fcols])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="fidclic-ia-journal.csv"'})
