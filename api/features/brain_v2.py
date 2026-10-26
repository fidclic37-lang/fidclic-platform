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
   what FidClic learned from every shop of the same ACTIVITY (Barbier, CBD,
   Opticien… — services/activities) — the median rhythm of their regulars —
   and, until 30 such regulars exist, the activity's researched figure
   (a barber 21 days, a « coiffure femme » 56, a tabac 2, an opticien 180).

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
    from features import ai_jobs as JOBS
    JOBS.register("learn", _learn_step)
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


def _keys(tenant: Dict[str, Any]) -> Tuple[str, str, bool]:
    """(activity key, sector key, whether the activity is precise — chosen
    by the owner or named by the sector — or only the sector's default)."""
    from services import activities as A
    act = A.of(tenant)
    sector = str(tenant.get("sector") or "").strip().lower()
    precise = (str(tenant.get("activity_key") or "") in A.BY_KEY) or sector in A.ALIASES
    return act["key"], CB.sector_key(sector), precise


def sector_prior(tenant: Any, priors: Optional[Dict[str, Any]] = None) -> Tuple[float, str]:
    """The usual rhythm a shop starts from (services/activities, user
    2026-10-25: one per trade, researched):
        a precise activity (Barbier, CBD, Opticien…): what the network learned
        for that activity (PRIOR_MIN_CLIENTS regulars), else its researched figure;
        only a sector: what the network learned for the sector, else the
        researched figure of the sector's most common trade."""
    from services import activities as A
    tenant = tenant if isinstance(tenant, dict) else {"sector": tenant}
    act, sec, precise = _keys(tenant)
    if priors is None:
        doc = _doc()
        priors = (doc or {}).get("priors") or {}
    for key in ((f"a:{act}",) if precise else (f"s:{sec}",)):
        p = priors.get(key)
        if p and int(p.get("clients") or 0) >= PRIOR_MIN_CLIENTS:
            return float(p["gap"]), "reseau"
    return float(A.BY_KEY[act]["gap"]), "secteur"


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------
def _histories() -> Dict[str, Dict[str, Any]]:
    """Every shop's visits, grouped by client and sorted, with its sector and
    rule. One read of the visits."""
    out: Dict[str, Dict[str, Any]] = {}
    tenants = {t["id"]: t for t in _db.tenants.find({}, {"_id": 0, "id": 1, "sector": 1, "activity_key": 1})}
    for v in _db.visits.find({"customer_id": {"$ne": None}}, CB._VISIT_FIELDS | {"tenant_id": 1}):
        t = CB._aware(v.get("visit_time"))
        if not t or not v.get("tenant_id"):
            continue
        t_doc = tenants.get(v["tenant_id"]) or {}
        shop = out.setdefault(v["tenant_id"], {"sector": t_doc.get("sector"), "tenant": t_doc,
                                               "clients": defaultdict(list)})
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


# what the journal rows need of a replayed brain (the rest is in its features)
_B_KEYS = ("last", "gap_days", "spread_days", "visits_n", "n_gaps", "confidence", "cv", "model")


def _shop_clients(tid: str) -> Dict[str, List[Dict[str, Any]]]:
    """One shop's visits, by client, sorted (aware times)."""
    by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for v in _db.visits.find({"tenant_id": tid, "customer_id": {"$ne": None}}, CB._VISIT_FIELDS | {"tenant_id": 1}):
        t = CB._aware(v.get("visit_time"))
        if t:
            by[v["customer_id"]].append({**v, "visit_time": t})
    for vs in by.values():
        vs.sort(key=lambda x: x["visit_time"])
    return by


def _tenant(tid: str) -> Dict[str, Any]:
    return _db.tenants.find_one({"id": tid}, {"_id": 0, "id": 1, "sector": 1, "activity_key": 1}) or {}


def _rhythms(run: str) -> Dict[str, Dict[str, List[float]]]:
    rhythms: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    for d in _db.brain_v2_stage.find({"run": run, "kind": "rhythm"}, {"_id": 0}):
        rhythms[f"a:{d['act']}"][d["tid"]].extend(d["gaps"])        # per trade …
        rhythms[f"s:{d['sec']}"][d["tid"]].extend(d["gaps"])        # … and per sector
    return rhythms


def _learn_step(job: Dict[str, Any], deadline: float) -> bool:
    """brain-v2's learning in slices (features/ai_jobs), the same four steps
    as in one go — working notes in brain_v2_stage, the new tables and rows
    swapped in at the end (the old ones serve meanwhile):
        rythmes  each shop's regulars' rhythm
        rejeu    every past guess, with the sector rhythm learned without the shop
        tables   the windows and the confidence, each shop judged without itself
        lignes   the journal's brain-v2 backtest rows"""
    import json
    import time
    from features import ai_jobs as JOBS
    from features import brain_journal as BJ
    from features import journal_stats as JS
    run = job["run"]
    now = CB._aware(job["now"])
    st = dict(job.get("state") or {})
    stage = _db.brain_v2_stage
    if not st.get("step"):
        shops = sorted(t for t in _db.visits.distinct("tenant_id", {"customer_id": {"$ne": None}}) if t)
        st = {"step": "rythmes", "shops": shops, "i": 0, "cursor": None, "chunk": 0}
        JOBS.save(job, state=st, phase="rythmes", done=0, total=len(shops))
    while True:
        shops = st["shops"]
        if st["step"] == "rythmes":
            if st["i"] >= len(shops):
                total = sum(len(_clients) for _clients in (_db.visits.distinct("customer_id", {"tenant_id": t})
                                                             for t in shops))
                st = {**st, "step": "rejeu", "i": 0, "cursor": None}
                JOBS.save(job, state=st, phase="rejeu", done=0, total=total)
                continue
            tid = shops[st["i"]]
            t_doc = _tenant(tid)
            act, sec, _ = _keys(t_doc or {"sector": t_doc.get("sector")})
            gaps = [g for vs in _shop_clients(tid).values() if (g := _own_gap(vs))]
            stage.replace_one({"run": run, "kind": "rhythm", "tid": tid},
                              {"run": run, "kind": "rhythm", "tid": tid, "act": act, "sec": sec, "gaps": gaps},
                              upsert=True)
            st = {**st, "i": st["i"] + 1}
            JOBS.save(job, state=st, done=st["i"])
        elif st["step"] == "rejeu":
            stage.delete_many({"run": run, "kind": "pt", "chunk": {"$gte": st["chunk"]}})   # a slice that died
            if st["i"] >= len(shops):
                st = {**st, "step": "tables"}
                JOBS.save(job, state=st, phase="tables")
                continue
            tid = shops[st["i"]]
            ids = sorted(c for c in _db.visits.distinct("customer_id", {"tenant_id": tid}) if c)
            todo = [c for c in ids if st["cursor"] is None or c > st["cursor"]][:JOBS.CHUNK]
            if not todo:
                st = {**st, "i": st["i"] + 1, "cursor": None}
                JOBS.save(job, state=st)
                continue
            t_doc = _tenant(tid)
            prior = sector_prior(t_doc or {"sector": t_doc.get("sector")}, _priors(_rhythms(run), skip=tid))
            rule = BJ.rule_days(tid)
            clients = _shop_clients(tid)
            pts: List[Dict[str, Any]] = []
            for cid in todo:
                vs = clients.get(cid) or []
                ends = _day_ends(vs)
                for k, end in enumerate(ends):
                    past = vs[:end + 1]
                    at = past[-1]["visit_time"]
                    b = CB.build(past, prior[0], prior[1], at, model=2)
                    if not CB.known(b) or not b.get("gap_days"):
                        continue
                    nxt = vs[ends[k] + 1]["visit_time"] if k + 1 < len(ends) else None
                    pts.append({"run": run, "kind": "pt", "chunk": st["chunk"], "tid": tid,
                                "sector": t_doc.get("sector"), "rule": rule, "at": at, "next": nxt,
                                "key": bucket(int(b["n_gaps"]), b.get("cv")),
                                "ratio": (CB._days(at, nxt) / float(b["gap_days"])) if nxt else None,
                                "n_gaps": int(b["n_gaps"]), "cv": b.get("cv"),
                                "mean": BJ._baseline_mean(BJ._gaps_of(b, past)),
                                "b": {k2: b.get(k2) for k2 in _B_KEYS},
                                "f": BJ.pack_features(BJ.features(b, at))})
            for i in range(0, len(pts), 1000):
                stage.insert_many(pts[i:i + 1000])
            st = {**st, "cursor": todo[-1], "chunk": st["chunk"] + 1}
            JOBS.save(job, state=st, done=int(job.get("done") or 0) + len(todo))
        elif st["step"] == "tables":
            pts = list(stage.find({"run": run, "kind": "pt"}, {"_id": 0, "tid": 1, "key": 1, "ratio": 1,
                                                               "n_gaps": 1, "cv": 1}))

            def ratios(skip: Optional[str] = None) -> Dict[str, List[float]]:
                out: Dict[str, List[float]] = defaultdict(list)
                for p in pts:
                    if p["ratio"] is not None and p["tid"] != skip:
                        out[p["key"]].append(p["ratio"])
                return out

            # each shop judged with windows learned without it
            loso = {tid: table(ratios(skip=tid)) for tid in shops}
            hits: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
            for p in pts:
                w = window_for(loso[p["tid"]], int(p["n_gaps"]), p.get("cv"))
                if w and p["ratio"] is not None:
                    # counted under the group whose window was used — what the profile shows
                    inside = int(w["lo"] <= p["ratio"] <= w["hi"])
                    for where in {w["bucket"], "tous"}:
                        hits[p["tid"]][where][0] += inside
                        hits[p["tid"]][where][1] += 1

            def coverage(skip: Optional[str] = None) -> Dict[str, int]:
                """Share of returns inside their window, per group — other
                shops than `skip`, so a shop's « confiance » is never measured
                on itself."""
                tot: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
                for tid, groups in hits.items():
                    if tid == skip:
                        continue
                    for k, (h, n) in groups.items():
                        tot[k][0] += h
                        tot[k][1] += n
                return {k: round(100 * h / n) for k, (h, n) in tot.items() if n}

            st = {**st, "step": "lignes", "cursor": None, "rchunk": 0, "rows": 0,
                  "loso": json.dumps(loso), "cov": json.dumps({tid: coverage(skip=tid) for tid in shops}),
                  "calib": json.dumps({**table(ratios()), "coverage": coverage()}),
                  "points": len(pts), "returns": sum(1 for p in pts if p["ratio"] is not None)}
            JOBS.save(job, state=st, phase="lignes", done=0, total=len(pts))
        elif st["step"] == "lignes":
            _db.brain_predictions.delete_many({"run": run, "chunk": {"$gte": st["rchunk"]}})   # a slice that died
            JS.unstage(run, st["rchunk"])
            q: Dict[str, Any] = {"run": run, "kind": "pt"}
            if st["cursor"] is not None:
                q["_id"] = {"$gt": st["cursor"]}
            batch = list(stage.find(q).sort("_id", 1).limit(JOBS.CHUNK * 20))
            if not batch:
                if JS.wait_for_build():              # the Précision tallies are being rebuilt: swap after
                    JOBS.defer(job, 120)
                    return False
                _finish_learn(run, now, st)
                return True
            loso, cov_loso = json.loads(st["loso"]), json.loads(st["cov"])
            rows: List[Dict[str, Any]] = []
            full: List[Dict[str, Any]] = []
            for p in batch:
                b = {k: p["b"].get(k) for k in _B_KEYS}
                b["last"] = CB._aware(b.get("last"))
                w = window_for(loso.get(p["tid"]), int(p["n_gaps"]), p.get("cv"))
                if w:
                    b["win"] = {"lo": w["lo"], "mid": w["mid"], "hi": w["hi"], "bucket": w["bucket"]}
                    cov = (cov_loso.get(p["tid"]) or {}).get(w["bucket"])
                    if cov is not None:
                        b["confidence"] = cov
                at = CB._aware(p["at"])
                row = BJ.make(p["tid"], p.get("sector") or "other", b, [p["mean"]] if p.get("mean") is not None else [],
                              at, "backtest", None, p["rule"], model=MODEL)
                if not row:
                    continue
                row["features"] = {**BJ.unpack_features(p["f"]), "confidence": b.get("confidence")}
                nxt = CB._aware(p.get("next"))
                if nxt is not None:
                    row.update(BJ._resolve(row, nxt))
                elif row["expires_at"] < now:
                    row.update(BJ._expire(row, now))
                else:
                    continue
                row["customer_id"] = None
                full.append(row)
                rows.append({**BJ.pack(row), "run": run, "chunk": st["rchunk"]})
            for i in range(0, len(rows), 1000):
                _db.brain_predictions.insert_many(rows[i:i + 1000])
            JS.stage(full, run, "v2", st["rchunk"])
            st = {**st, "cursor": batch[-1]["_id"], "rchunk": st["rchunk"] + 1, "rows": st["rows"] + len(rows)}
            JOBS.save(job, state=st, done=int(job.get("done") or 0) + len(batch))
        if time.monotonic() >= deadline:
            return False


def _finish_learn(run: str, now: datetime, st: Dict[str, Any]) -> None:
    """The new tables and rows take the old ones' place, at once."""
    import json
    _db.brain_predictions.delete_many({"source": "backtest", "model": MODEL, "run": {"$exists": False}})
    _db.brain_predictions.update_many({"run": run}, {"$unset": {"run": "", "chunk": ""}})
    from features import journal_stats as JS
    JS.swap("v2", run)
    doc = {"model": MODEL, "learned_at": now, "calib": json.loads(st["calib"]), "priors": _priors(_rhythms(run)),
           "shops": len(st["shops"]), "points": st["points"], "backtest_rows": st["rows"],
           "returns": st["returns"]}
    _db.brain_models.replace_one({"model": MODEL}, doc, upsert=True)
    _cache[:] = [0.0, None]
    _db.brain_v2_stage.delete_many({"run": run})


def learn(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Learn v2's tables from every shop, and backtest v2 shop by shop with
    tables learned from the other shops — in one go (scripts, tests; the
    page and the tick use the job). Writes brain_models and the journal
    (brain-v2 backtest rows) only."""
    from features import ai_jobs as JOBS
    JOBS.run_now("learn", None, now or datetime.now(timezone.utc))
    doc = _doc(fresh=True) or {}
    return {k: doc.get(k) for k in ("shops", "points", "backtest_rows", "returns")}


def learn_due(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The tick: once a day."""
    now = now or datetime.now(timezone.utc)
    doc = _doc(fresh=True)
    last = CB._aware((doc or {}).get("learned_at"))
    if last and now - last < LEARN_EVERY:
        return None
    if not _db.visits.find_one({}, {"_id": 1}):
        return None
    from features import ai_jobs as JOBS
    job, created = JOBS.start("learn", None, by="tick", now=now)
    return {"started": created, "job": job["id"]}
