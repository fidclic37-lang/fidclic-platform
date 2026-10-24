"""
brain-v2 — the client brain that learns from the whole network (user,
2026-10-25: « brain-v2 shuru karo »).

The journal (features/brain_journal) showed v1's two weaknesses: its window
was too narrow (3 returns in 10 inside it) and its « confiance » was a
formula, not a measure (84 % said, 9 % true). v2 changes three things and
nothing else, so the journal can tell which one helped:

1. THE USUAL RHYTHM COMES FROM THE NETWORK
   A client with few visits is still pulled to a usual rhythm (v1's
   shrinkage), but before the shop has 10 regulars of its own, that rhythm is
   what FidClic learned from every shop of the same sector — the median
   rhythm of their regulars — instead of a fixed figure per sector. Sector
   names are read through client_brain.SECTOR_ALIASES (« boulangerie » is a
   bakery: v1 gave it 21 days, its clients come every 4).

2. THE WINDOW IS LEARNED, NOT ASSUMED (user: « 10 mein 7 baar sahi »)
   For every past prediction, how far the real return fell from the rhythm,
   as a ratio (came back after 12 days on a rhythm of 10 → 1.2). Clients are
   grouped by how much the brain knows of them (number of gaps) and how
   regular they are (cv). In each group the window runs from the 15th to the
   85th percentile of those ratios — 7 returns in 10 inside — and the centre
   is their median, which also corrects a rhythm that runs early or late.

3. « CONFIANCE » IS A MEASURE
   Shown for a client: the share of clients like them, in shops the model
   did not learn from, who came back inside their window.

LEAVE-ONE-SHOP-OUT
   The backtest of v2 never lets a shop see itself: its windows and its
   sector rhythm are learned from the OTHER shops only — exactly the
   situation of a new shop joining FidClic, and the Bpifrance verrou (« one
   shop's data is too small, the network's is not »). Live, the tables are
   learned from every shop.

   Honest limits: the other shops' rhythms are read on their whole history
   (cross-shop knowledge, never the same client's future); clients who never
   came back are kept out of the window's percentiles (the journal counts
   them apart, « non revenus »).

Learned once a day by the tick (and by « Réapprendre » on Précision); the
tables live in brain_models, the backtest rows in the journal as brain-v2.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

from features import client_brain as CB

MODEL = "brain-v2"
LOW_Q, MID_Q, HIGH_Q = 0.15, 0.50, 0.85      # 7 returns in 10 between LOW and HIGH
BUCKET_MIN_ROWS = 40                         # fewer: the coarser group answers
PRIOR_MIN_CLIENTS = 30                       # a sector's network rhythm needs this many regulars
LEARN_EVERY = timedelta(hours=24)
CACHE_TTL_S = 600

_db = None
_cache: List[Any] = [0.0, None]


def init(db):
    global _db
    _db = db
    try:
        db.brain_models.create_index("model", unique=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# groups of clients like one another
# ---------------------------------------------------------------------------
def band_n(n: int) -> str:
    return "2" if n <= 2 else ("3-4" if n <= 4 else ("5-9" if n <= 9 else "10+"))


def band_cv(n: int, cv: Optional[float]) -> str:
    """How regular — only measured from 4 gaps on (under that v1 assumes it)."""
    if n < 4 or cv is None:
        return "?"
    cv = float(cv)
    return "a" if cv < 0.2 else ("b" if cv < 0.4 else ("c" if cv < 0.7 else "d"))


def bucket(n: int, cv: Optional[float]) -> str:
    return f"{band_n(n)}|{band_cv(n, cv)}"


def _q(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 1.0
    i = (len(sorted_vals) - 1) * p
    lo = int(i)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def _window(ratios: List[float]) -> Dict[str, Any]:
    s = sorted(ratios)
    return {"lo": round(_q(s, LOW_Q), 3), "mid": round(_q(s, MID_Q), 3), "hi": round(_q(s, HIGH_Q), 3),
            "rows": len(s)}


def table(ratios_by_bucket: Dict[str, List[float]]) -> Dict[str, Any]:
    """Windows per group, per number-of-gaps band, and for everyone."""
    buckets = {k: _window(v) for k, v in ratios_by_bucket.items() if len(v) >= BUCKET_MIN_ROWS}
    by_n: Dict[str, List[float]] = defaultdict(list)
    every: List[float] = []
    for k, v in ratios_by_bucket.items():
        by_n[k.split("|")[0]].extend(v)
        every.extend(v)
    return {"buckets": buckets,
            "nbands": {k: _window(v) for k, v in by_n.items() if len(v) >= BUCKET_MIN_ROWS},
            "global": _window(every) if len(every) >= BUCKET_MIN_ROWS else None}


def window_for(calib: Optional[Dict[str, Any]], n: int, cv: Optional[float]) -> Optional[Dict[str, Any]]:
    """The learned window for a client like this one, from the finest group
    that has enough rows. None: nothing learned yet (v1's window stands)."""
    if not calib:
        return None
    key = bucket(n, cv)
    for found, where in ((calib.get("buckets") or {}).get(key), key), \
                         ((calib.get("nbands") or {}).get(band_n(n)), band_n(n)), \
                         (calib.get("global"), "tous"):
        if found:
            cov = (calib.get("coverage") or {}).get(where)
            return {**found, "bucket": where, "coverage": cov}
    return None


# ---------------------------------------------------------------------------
# what is in service
# ---------------------------------------------------------------------------
def _doc(fresh: bool = False) -> Optional[Dict[str, Any]]:
    now = datetime.now(timezone.utc).timestamp()
    if not fresh and now - _cache[0] < CACHE_TTL_S:
        return _cache[1]
    try:
        doc = _db.brain_models.find_one({"model": MODEL}, {"_id": 0})
    except Exception:
        doc = None
    _cache[:] = [now, doc]
    return doc


def calibration() -> Optional[Dict[str, Any]]:
    doc = _doc()
    return doc.get("calib") if doc else None


def sector_prior(sector: Optional[str], priors: Optional[Dict[str, Any]] = None) -> Tuple[float, str]:
    """The sector's usual rhythm as the network learned it; the fixed figure
    until PRIOR_MIN_CLIENTS regulars of that sector exist."""
    key = CB.sector_key(sector)
    if priors is None:
        doc = _doc()
        priors = (doc or {}).get("priors") or {}
    p = priors.get(key)
    if p and int(p.get("clients") or 0) >= PRIOR_MIN_CLIENTS:
        return float(p["gap"]), "reseau"
    return CB.sector_gap(key), "secteur"


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------
def _histories() -> Dict[str, Dict[str, Any]]:
    """Every shop's visits, grouped by client and sorted, with its sector and
    rule. One read of the visits."""
    out: Dict[str, Dict[str, Any]] = {}
    sectors = {t["id"]: t.get("sector") for t in _db.tenants.find({}, {"_id": 0, "id": 1, "sector": 1})}
    for v in _db.visits.find({"customer_id": {"$ne": None}}, CB._VISIT_FIELDS | {"tenant_id": 1}):
        t = CB._aware(v.get("visit_time"))
        if not t or not v.get("tenant_id"):
            continue
        shop = out.setdefault(v["tenant_id"], {"sector": sectors.get(v["tenant_id"]), "clients": defaultdict(list)})
        shop["clients"][v["customer_id"]].append({**v, "visit_time": t})
    for shop in out.values():
        for vs in shop["clients"].values():
            vs.sort(key=lambda x: x["visit_time"])
    return out


def _day_ends(visits: List[Dict[str, Any]]) -> List[int]:
    ends: List[int] = []
    for i, v in enumerate(visits):
        d = v["visit_time"].astimezone(CB.PARIS).date()
        if ends and visits[ends[-1]]["visit_time"].astimezone(CB.PARIS).date() == d:
            ends[-1] = i
        else:
            ends.append(i)
    return ends


def _own_gap(visits: List[Dict[str, Any]]) -> Optional[float]:
    ends = _day_ends(visits)
    if len(ends) < CB.RHYTHM_MIN_VISITS:
        return None
    days = [visits[i]["visit_time"] for i in ends]
    gaps = [CB._days(days[i - 1], days[i]) for i in range(1, len(days))][-CB.RECENT_GAPS:]
    return median(gaps)


def _priors(rhythms: Dict[str, Dict[str, List[float]]], skip: Optional[str] = None) -> Dict[str, Any]:
    """Per sector: the median rhythm of its regulars, other shops than `skip`."""
    out: Dict[str, Any] = {}
    for key, shops in rhythms.items():
        vals = [g for tid, gs in shops.items() if tid != skip for g in gs]
        if vals:
            out[key] = {"gap": round(median(vals), 1), "clients": len(vals)}
    return out


def learn(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Learn v2's tables from every shop, and backtest v2 shop by shop with
    tables learned from the other shops. Writes brain_models and the journal
    (brain-v2 backtest rows) only."""
    from features import brain_journal as BJ
    now = now or datetime.now(timezone.utc)
    shops = _histories()

    # 1. the network's usual rhythm, per sector and per shop
    rhythms: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for tid, shop in shops.items():
        key = CB.sector_key(shop["sector"])
        for vs in shop["clients"].values():
            g = _own_gap(vs)
            if g:
                rhythms[key][tid].append(g)

    # 2. replay: every past guess (raw rhythm, the shop's sector rhythm learned
    #    from the other shops), and how far the real return fell from it
    points: List[Dict[str, Any]] = []
    for tid, shop in shops.items():
        prior = sector_prior(shop["sector"], _priors(rhythms, skip=tid))
        rule = BJ.rule_days(tid)
        for vs in shop["clients"].values():
            ends = _day_ends(vs)
            for k, end in enumerate(ends):
                past = vs[:end + 1]
                at = past[-1]["visit_time"]
                b = CB.build(past, prior[0], prior[1], at, model=2)
                if not CB.known(b) or not b.get("gap_days"):
                    continue
                nxt = vs[ends[k] + 1]["visit_time"] if k + 1 < len(ends) else None
                points.append({"tid": tid, "sector": shop["sector"], "rule": rule, "b": b, "at": at,
                               "past": past, "next": nxt, "key": bucket(int(b["n_gaps"]), b.get("cv")),
                               "ratio": (CB._days(at, nxt) / float(b["gap_days"])) if nxt else None})

    def ratios(skip: Optional[str] = None) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = defaultdict(list)
        for p in points:
            if p["ratio"] is not None and p["tid"] != skip:
                out[p["key"]].append(p["ratio"])
        return out

    # 3. each shop judged with windows learned without it
    loso: Dict[str, Dict[str, Any]] = {tid: table(ratios(skip=tid)) for tid in shops}
    hits: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # shop → group → [in, n]
    for p in points:
        w = window_for(loso[p["tid"]], int(p["b"]["n_gaps"]), p["b"].get("cv"))
        p["w"] = w
        if w and p["next"] is not None:
            # counted under the group whose window was used — what the profile shows
            inside = int(w["lo"] <= p["ratio"] <= w["hi"])
            for where in {w["bucket"], "tous"}:
                hits[p["tid"]][where][0] += inside
                hits[p["tid"]][where][1] += 1

    def coverage(skip: Optional[str] = None) -> Dict[str, int]:
        """Share of returns inside their window, per group — other shops than
        `skip`, so a shop's « confiance » is never measured on itself."""
        tot: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
        for tid, groups in hits.items():
            if tid == skip:
                continue
            for k, (h, n) in groups.items():
                tot[k][0] += h
                tot[k][1] += n
        return {k: round(100 * h / n) for k, (h, n) in tot.items() if n}

    # 4. the journal's brain-v2 backtest rows
    rows: List[Dict[str, Any]] = []
    cov_loso = {tid: coverage(skip=tid) for tid in shops}
    for p in points:
        b = dict(p["b"])
        if p["w"]:
            b["win"] = {"lo": p["w"]["lo"], "mid": p["w"]["mid"], "hi": p["w"]["hi"], "bucket": p["w"]["bucket"]}
            cov = cov_loso[p["tid"]].get(p["w"]["bucket"])
            if cov is not None:
                b["confidence"] = cov
        row = BJ.make(p["tid"], p["sector"] or "other", b, BJ._gaps_of(b, p["past"]), p["at"], "backtest",
                      None, p["rule"], model=MODEL)
        if not row:
            continue
        if p["next"] is not None:
            row.update(BJ._resolve(row, p["next"]))
        elif row["expires_at"] < now:
            row.update(BJ._expire(row, now))
        else:
            continue
        row["customer_id"] = None
        rows.append(row)
    _db.brain_predictions.delete_many({"source": "backtest", "model": MODEL})
    for i in range(0, len(rows), 1000):
        _db.brain_predictions.insert_many(rows[i:i + 1000])

    calib = {**table(ratios()), "coverage": coverage()}
    doc = {"model": MODEL, "learned_at": now, "calib": calib, "priors": _priors(rhythms),
           "shops": len(shops), "points": len(points), "backtest_rows": len(rows),
           "returns": sum(1 for p in points if p["ratio"] is not None)}
    _db.brain_models.replace_one({"model": MODEL}, doc, upsert=True)
    _cache[:] = [0.0, None]
    return {k: doc[k] for k in ("shops", "points", "backtest_rows", "returns")}


def learn_due(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The tick: once a day."""
    now = now or datetime.now(timezone.utc)
    doc = _doc(fresh=True)
    last = CB._aware((doc or {}).get("learned_at"))
    if last and now - last < LEARN_EVERY:
        return None
    if not _db.visits.find_one({}, {"_id": 1}):
        return None
    return learn(now)
