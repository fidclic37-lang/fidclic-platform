"""
Précision, always live and fast (audit 2026-10-26: the page and the CSV read
the whole journal on every view — 16 s and 63 s for 110 000 rows, worse as it
grows). User, 2026-10-26: « hamesha live, pehle se jode hue ».

    · every prediction, the moment it is written or judged, adds itself to a
      small tally (features/journal_stats): counts, the errors' histograms
      (they are rounded to 0.1 day, so the medians stay exact), calibration
    · the page reads the tallies, never the journal — the same figures, to
      the digit, as reading every row
    · a backtest or a brain-v2 run swaps its tallies in when it ends (the
      old run's out, the new one's in)
    · the tallies of a journal written before are built once by a background
      job (and again each week, as a check); until then the page reads the
      rows as before
    · the CSV streams: no 4.5 MB response cap, no whole journal in memory

Run: cd api && /usr/local/bin/python3 tests/test_precision_stats.py
"""
import asyncio
import datetime as dt
import json
import os
import random
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-precision-stats")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:600]}"))


def main():
    import server
    import auth
    import httpx
    from features import ai_jobs as JOBS
    from features import brain_journal as BJ
    from features import brain_v2 as V2
    from features import client_brain as CB
    from features import journal_stats as JS

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC).replace(microsecond=0)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    rnd = random.Random(21)
    shops = {"cafe1": ("cafe", 5, 25), "cafe2": ("cafe", 9, 20), "sal": ("salon", 30, 18), "bk": ("boulangerie", 3, 25)}
    for tid, (sector, gap, n) in shops.items():
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.upper(), "sector": sector, "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        for c in range(n):
            cid = f"{tid}-c{c:02d}"
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"C{c}", "deleted_at": None,
                                     "created_at": now - dt.timedelta(days=500)})
            t = now - dt.timedelta(days=500)
            stop = now - dt.timedelta(days=rnd.choice([1, gap, 200]))
            while t < stop:
                db.visits.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid, "visit_time": t,
                                      "amount_paid": rnd.choice([0, 4.0, 12.5])})
                t += dt.timedelta(days=max(0.7, rnd.gauss(gap, gap / 2)))
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin"})
    BOSS = {"Authorization": "Bearer " + auth.create_access_token({"sub": "boss@fidclic.com", "role": "super_admin",
                                                                     "tenant_id": None})}

    def clean(d):
        d = dict(d)
        for k in ("jobs", "learned", "source_of_figures"):
            d.pop(k, None)
        for x in d.get("runs") or []:
            x.pop("at", None)
        return json.loads(json.dumps(d, sort_keys=True, default=str))

    FILTERS = [dict(source=s, sector=se, model=m) for s in ("all", "live", "backtest") for se in ("", "cafe", "salon")
               for m in ("", "brain-v1", "brain-v2")]

    def same_everywhere(label):
        bad = []
        for f in FILTERS:
            got = http("GET", "/api/admin/ai/precision", headers=BOSS, params=f).json()
            ref = BJ._rows_page(f["source"], f["sector"], "", f["model"])
            if clean(got) != clean(ref):
                bad.append((f, {k: (ref.get(k), got.get(k)) for k in ref if clean(ref).get(k) != clean(got).get(k)}))
        check(f"{label}: the same figures as reading every row, for all {len(FILTERS)} filters", not bad, bad[:1])

    # ── 1. the journal, by every way it is written ─────────────────────────────
    print("Le journal")
    for tid in shops:
        BJ.backtest(tid, now)
    V2.learn(now)
    custs = [c["id"] for c in db.customers.find({}, {"_id": 0, "id": 1})]
    for cid in custs[:40]:                                     # live: a scan opens a guess …
        tid = cid.split("-")[0]
        BJ.record_visit(tid, cid, CB.refresh(tid, cid))
    for cid in custs[:25]:                                     # … the next visit judges it
        tid = cid.split("-")[0]
        db.visits.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid,
                              "visit_time": now + dt.timedelta(days=rnd.choice([1, 3, 9])), "amount_paid": 4.0})
        BJ.record_visit(tid, cid, CB.refresh(tid, cid))
    BJ.record_visit("cafe1", custs[0], CB.refresh("cafe1", custs[0]))      # a second scan the same day
    db.brain_predictions.update_many({"source": "live", "status": "open", "tenant_id": "sal"},
                                     {"$set": {"expires_at": now - dt.timedelta(days=1)}})
    st = JS.status()
    check("the tallies are ready from the start on a new journal", st.get("ready") is True, st)
    BJ.expire_due()                                            # « non revenu »
    n_rows = db.brain_predictions.count_documents({})
    check(f"a varied journal ({n_rows} rows: live and backtest, both brains, open / judged / not returned)",
          n_rows > 1000 and db.brain_predictions.count_documents({"source": "live", "status": "resolved"})
          and db.brain_predictions.count_documents({"source": "live", "status": "expired"})
          and db.brain_predictions.count_documents({"source": "live", "status": "open"}))
    same_everywhere("after live scans, judgements, a same-day rescan, expiries")

    # ── 2. the page reads the tallies, never the journal ───────────────────────
    print("Lecture")
    reads = {"n": 0}
    orig_find = mongomock.collection.Collection.find

    def counting(self, *a, **k):
        if self.name == "brain_predictions":
            reads["n"] += 1
        return orig_find(self, *a, **k)
    mongomock.collection.Collection.find = counting
    d = http("GET", "/api/admin/ai/precision", headers=BOSS).json()
    mongomock.collection.Collection.find = orig_find
    check(f"no read of the journal ({reads['n']})", reads["n"] == 0)
    check("the page says where its figures come from", d.get("source_of_figures") == "tallies", d.get("source_of_figures"))
    check(f"a handful of tallies, not the journal ({db.brain_journal_stats.count_documents({})} vs {n_rows} rows)",
          db.brain_journal_stats.count_documents({}) < n_rows / 5)
    check("one shop asked for (API only): read from the rows, as before",
          clean(http("GET", "/api/admin/ai/precision", headers=BOSS, params={"tenant": "sal"}).json())
          == clean(BJ._rows_page("all", "", "sal", "")))

    # ── 3. reruns swap their tallies ──────────────────────────────────────────
    print("Relances")
    db.visits.insert_many([{"id": str(uuid.uuid4()), "tenant_id": "cafe2", "customer_id": f"cafe2-c{c:02d}",
                            "visit_time": now - dt.timedelta(days=d), "amount_paid": 3.0}
                           for c in range(5) for d in (40, 33, 26)])
    before = clean(http("GET", "/api/admin/ai/precision", headers=BOSS).json())
    http("POST", "/api/admin/ai/precision/backtest", headers=BOSS, json={"tenant_id": "cafe2"})
    JOBS.CHUNK = 6
    JOBS.run(budget_s=0, slices=1)
    check("half-way through a rerun: the page has not moved", clean(http("GET", "/api/admin/ai/precision", headers=BOSS).json()) == before)
    while db.ai_jobs.count_documents({"status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
    same_everywhere("after a shop's backtest rerun (its old tallies out, the new in)")
    http("POST", "/api/admin/ai/precision/learn", headers=BOSS)
    while db.ai_jobs.count_documents({"status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
    same_everywhere("after brain-v2 relearned")
    BJ.backtest("bk", now)                                     # the one-go path too
    same_everywhere("after a backtest in one go")

    # ── 4. a journal written before: built once, in the background ─────────────
    print("Un journal d'avant")
    db.brain_journal_stats.delete_many({})
    db.brain_journal_stats_side.delete_many({})
    db.platform_settings.delete_one({"key": "brain_journal_stats"})
    d = http("GET", "/api/admin/ai/precision", headers=BOSS).json()
    check("no tallies yet: the page reads the rows, still right", d.get("source_of_figures") == "rows"
          and clean(d) == clean(BJ._rows_page("all", "", "", "")))
    JS.SLICE = 400
    JOBS.BUDGET_S = 0                                          # the tick does one slice
    out = server.tick_pass()["brain_journal"]
    JOBS.BUDGET_S = 90
    check("the tick starts the build", db.ai_jobs.find_one({"kind": "journal_stats"}) is not None, out)
    # live events while it builds: rows before and after its cursor
    k = 0
    while db.ai_jobs.count_documents({"kind": "journal_stats", "status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
        k += 1
        cid = custs[40 + (k % 30)]
        tid = cid.split("-")[0]
        db.visits.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid,
                              "visit_time": now + dt.timedelta(days=k + 20), "amount_paid": 4.0})
        BJ.record_visit(tid, cid, CB.refresh(tid, cid))
        if k == 3:
            http("POST", "/api/admin/ai/precision/backtest", headers=BOSS, json={"tenant_id": "sal"})
        if k > 400:
            break
    while db.ai_jobs.count_documents({"status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
    check(f"built in {k} slices, scans and a backtest landing meanwhile", JS.status().get("ready") is True and 2 < k < 400)
    same_everywhere("after the build")
    db.platform_settings.update_one({"key": "brain_journal_stats"},
                                    {"$set": {"built_at": now - dt.timedelta(days=8)}})
    server.tick_pass()
    check("each week the tick rebuilds them, as a check",
          db.ai_jobs.count_documents({"kind": "journal_stats"}) == 2)
    while db.ai_jobs.count_documents({"status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
    same_everywhere("after the weekly rebuild")

    # ── 5. the CSV streams ─────────────────────────────────────────────────────
    print("CSV")
    from fastapi.responses import StreamingResponse
    resp = BJ.export(token_data=None)
    check("a streamed response (no 4.5 MB cap, no whole journal in memory)", isinstance(resp, StreamingResponse))
    r = http("GET", "/api/admin/ai/precision/export.csv", headers=BOSS)
    body = r.content.decode("utf-8-sig")
    lines = [ln for ln in body.split("\r\n") if ln]
    check(f"one line per judged guess ({len(lines) - 1})",
          len(lines) - 1 == db.brain_predictions.count_documents({"status": {"$in": ["resolved", "expired"]},
                                                                   "run": {"$exists": False}}))
    check("the same header", lines[0].split(";")[:14] == BJ.CSV_COLUMNS and lines[0].split(";")[14] == "f_visits_n")

    # ── 6. the figures from the tallies, edge cases ────────────────────────────
    print("Cas limites")
    rows = [{"status": "resolved", "pred": {"confidence": c}, "outcome": {"in_window": w, "error_days": e,
                                                                          "error_mean": m, "error_rule": ru}}
            for c, w, e, m, ru in ((55, True, 2.4, None, -21.4), (90, False, -2.5, 0.0, 3.1), (10, True, 0.0, 7.0, -7.0),
                                   (100, True, 12.3, -7.1, 0.1), (0, False, None, None, None))] + \
           [{"status": "expired"}, {"status": "open"}]
    tally = JS.add({}, *[JS.contribution(r) for r in rows])
    check("medians of an even count, negatives, None and 0, the ±7 days edge, 100 % confidence: as from the rows",
          JS.summarise(tally) == BJ.summarise(rows), (JS.summarise(tally), BJ.summarise(rows)))
    check("nothing at all: as from no rows", JS.summarise({}) == BJ.summarise([]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
