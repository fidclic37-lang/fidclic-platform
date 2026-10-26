"""
« Relancer le backtest » and « Réapprendre brain-v2 » in the background
(audit 2026-10-26: one request did the whole work and Vercel cut it; the
tick backtested a whole shop at once and a big shop never finished).
User, 2026-10-26:
    1A  the button answers at once (« lancé »); the work runs in slices in
        the 15-minute tick, its progress on the Précision page
    2A  the old figures stay until the new run is complete, then swap at once
    3A  « Réapprendre brain-v2 » the same way
    4   vercel.json maxDuration 360 s (the automations' run lease outlives it)

Edge cases: a slice killed half-way (its rows are cleaned, never doubled),
two ticks at once, a second click while it runs, a shop without visits, an
unknown shop, a failing job stops after 3 tries, slices give the same result
as one go — to the figure.

Run: cd api && /usr/local/bin/python3 tests/test_ai_jobs.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-ai-jobs")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))


def main():
    import server
    import auth
    import httpx
    from features import ai_jobs as JOBS
    from features import automations as AU
    from features import brain_journal as BJ
    from features import brain_v2 as V2

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC).replace(microsecond=0)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    shops = {"bk1": ("boulangerie", 3, 30), "bk2": ("boulangerie", 4, 25), "sal": ("salon", 30, 20),
             "cafe": ("cafe", 7, 40)}
    rnd = random.Random(11)
    for tid, (sector, gap, n) in shops.items():
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.upper(), "sector": sector, "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        for c in range(n):
            cid = f"{tid}-c{c:03d}"
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"C{c}", "deleted_at": None,
                                     "created_at": now - dt.timedelta(days=300)})
            t = now - dt.timedelta(days=300)
            stop = now - dt.timedelta(days=150 if c % 6 == 0 else 1)
            while t < stop:
                db.visits.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid, "visit_time": t,
                                      "amount_paid": rnd.choice([0, 3.0, 9.5])})
                t += dt.timedelta(days=max(0.8, rnd.gauss(gap, gap / 3)))
    db.tenants.insert_one({"id": "empty", "slug": "empty", "name": "EMPTY", "sector": "cafe"})
    db.users.insert_many([{"email": "boss@fidclic.com", "role": "super_admin"},
                          {"email": "o@x.fr", "role": "business_owner", "tenant_id": "cafe", "active": True},
                          {"email": "s@fidclic.com", "role": "commercial"}])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    BOSS, OWNER, SALES = tok("boss@fidclic.com", "super_admin"), tok("o@x.fr", "business_owner", "cafe"), \
        tok("s@fidclic.com", "commercial")

    def page(**params):
        d = http("GET", "/api/admin/ai/precision", headers=BOSS, params=params).json()
        d.pop("jobs", None)
        d.pop("learned", None)
        for x in d.get("runs") or []:
            x.pop("at", None)
        return d

    def journal(model="brain-v1"):
        return sorted(json.dumps({k: v for k, v in BJ.unpack(x).items() if k not in ("_id",)}, default=str, sort_keys=True)
                      for x in db.brain_predictions.find({"model": model, "source": "backtest"}))

    # ── 0. the settings ─────────────────────────────────────────────────────────
    print("Réglages")
    vj = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "vercel.json")))
    md = vj["functions"]["api/index.py"]["maxDuration"]
    check(f"a function may run 360 s (vercel.json: {md})", md == 360)
    check(f"the automations' run lease outlives it ({AU.RUN_LEASE})", AU.RUN_LEASE.total_seconds() > md)
    check(f"so does a job's ({JOBS.JOB_LEASE})", JOBS.JOB_LEASE.total_seconds() > md)

    # ── 1. one go (the reference) ──────────────────────────────────────────────
    print("En une fois (référence)")
    for tid in shops:
        BJ.backtest(tid, now)
    ref_v1 = journal()
    check(f"the backtest in one go wrote rows ({len(ref_v1)})", len(ref_v1) > 300)
    ref_page = page()
    V2.learn(now)
    ref_v2 = journal("brain-v2")
    ref_model = {k: v for k, v in db.brain_models.find_one({"model": "brain-v2"}, {"_id": 0}).items() if k != "learned_at"}
    check(f"brain-v2 learned in one go ({len(ref_v2)} rows)", len(ref_v2) > 300 and ref_model["calib"])

    # ── 2. the button answers at once ──────────────────────────────────────────
    print("Le bouton répond tout de suite")
    ref_page = page()                                   # what the page shows before the rerun
    before = db.brain_predictions.count_documents({})
    r = http("POST", "/api/admin/ai/precision/backtest", headers=BOSS, json={})
    body = r.json()
    check(f"« Relancer le backtest »: 200 at once ({r.status_code})", r.status_code == 200 and body.get("started"), body)
    check("…every shop with visits is queued, the empty one is not",
          sorted(body["started"]) == sorted(shops) and "empty" not in body["started"], body)
    check("…nothing computed yet: the journal is untouched", db.brain_predictions.count_documents({}) == before)
    again = http("POST", "/api/admin/ai/precision/backtest", headers=BOSS, json={}).json()
    check("a second click while it waits: no second job", not again.get("started") and sorted(again.get("running") or []) == sorted(shops), again)
    check("one job per shop", db.ai_jobs.count_documents({"kind": "backtest", "status": {"$in": ["queued", "running"]}}) == len(shops))
    d = http("GET", "/api/admin/ai/precision", headers=BOSS).json()
    jobs = d.get("jobs") or []
    check("the page shows them, waiting for the tick", len(jobs) == len(shops)
          and all(j["kind"] == "backtest" and j["done"] == 0 and j["label"] for j in jobs), jobs)
    check("an unknown shop: 404", http("POST", "/api/admin/ai/precision/backtest", headers=BOSS,
                                       json={"tenant_id": "nope"}).status_code == 404)

    # ── 3. slices: the old figures stay until the end ──────────────────────────
    print("Par tranches")
    JOBS.CHUNK = 7                                          # small slices for the test
    slices = 0
    while db.ai_jobs.count_documents({"kind": "backtest", "status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)                       # one slice per call
        slices += 1
        if slices == 3:
            mid = http("GET", "/api/admin/ai/precision", headers=BOSS).json()
            check("half-way: progress shown (some clients done)",
                  any(0 < j["done"] < j["total"] for j in mid.get("jobs") or []), mid.get("jobs"))
            check("half-way: the page still shows the old figures, to the digit", page() == ref_page)
            check("half-way: the new rows wait aside", db.brain_predictions.count_documents({"run": {"$exists": True}}) > 0)
        if slices > 500:
            break
    check(f"done in {slices} slices", 3 < slices < 500)
    check("then the new run took the old one's place: the same journal as one go", journal() == ref_v1)
    check("nothing left aside", db.brain_predictions.count_documents({"run": {"$exists": True}}) == 0)
    check("the page: the same figures", page() == ref_page)
    check("jobs marked done, the page shows none running",
          not [j for j in http("GET", "/api/admin/ai/precision", headers=BOSS).json().get("jobs") or []
               if j["status"] in ("queued", "running")])

    # ── 4. a slice killed half-way ─────────────────────────────────────────────
    print("Une tranche tuée en route")
    JOBS.start("backtest", "sal", by="test", now=now)

    class Killed(BaseException):
        pass
    real = BJ._insert_rows
    calls = {"n": 0}

    def dying(rows):
        calls["n"] += 1
        real(rows[: len(rows) // 2])               # half written, then the function is gone
        if calls["n"] == 2:
            raise Killed()
        real(rows[len(rows) // 2:])
    BJ._insert_rows = dying
    try:
        JOBS.run(budget_s=0, slices=5)
    except Killed:
        pass
    BJ._insert_rows = real
    job = db.ai_jobs.find_one({"kind": "backtest", "tenant_id": "sal"}, sort=[("created_at", -1)])
    check("the dead slice left its lease", job and job.get("lease") and job["status"] == "running", job and
          {k: job.get(k) for k in ("status", "lease", "done", "total", "errors")})
    check("a tick 4 minutes later leaves it alone (still leased)",
          JOBS.run(budget_s=0, slices=1, at=dt.datetime.now(UTC) + dt.timedelta(minutes=4)) == [])
    while db.ai_jobs.count_documents({"kind": "backtest", "status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1, at=dt.datetime.now(UTC) + dt.timedelta(minutes=11))
    check("after the lease, the next tick cleans the half-written slice and ends: no row twice", journal() == ref_v1)

    # ── 5. two ticks at once ───────────────────────────────────────────────────
    print("Deux passages en même temps")
    JOBS.start("backtest", "bk1", by="test", now=now)
    real_step = JOBS._HANDLERS["backtest"]

    def nested(job, deadline):
        JOBS.run(budget_s=0, slices=3)               # a second tick lands mid-slice
        return real_step(job, deadline)
    JOBS._HANDLERS["backtest"] = nested
    JOBS.run(budget_s=0, slices=1)
    JOBS._HANDLERS["backtest"] = real_step
    while db.ai_jobs.count_documents({"kind": "backtest", "status": {"$in": ["queued", "running"]}}):
        JOBS.run(budget_s=0, slices=1)
    check("the second tick does not touch a job in progress: no row twice", journal() == ref_v1)

    # ── 6. « Réapprendre brain-v2 » ────────────────────────────────────────────
    print("Réapprendre brain-v2")
    cal_before = (V2._doc(fresh=True) or {}).get("calib")
    r = http("POST", "/api/admin/ai/precision/learn", headers=BOSS)
    check(f"answers at once, « lancé » ({r.status_code})", r.status_code == 200 and r.json().get("started"), r.text[:200])
    check("a second click: the same job", not http("POST", "/api/admin/ai/precision/learn", headers=BOSS).json().get("started"))
    n = 0
    while db.ai_jobs.count_documents({"kind": "learn", "status": {"$in": ["queued", "running"]}}) and n < 2000:
        JOBS.run(budget_s=0, slices=1)
        n += 1
        if n == 4:
            check("half-way: brain-v2 still serves its old tables", (V2._doc(fresh=True) or {}).get("calib") == cal_before)
            check("half-way: its old backtest rows are still the ones shown", journal("brain-v2") == ref_v2)
    model = {k: v for k, v in db.brain_models.find_one({"model": "brain-v2"}, {"_id": 0}).items() if k != "learned_at"}
    check(f"learned in {n} slices: the same tables as in one go", n > 4 and model == ref_model,
          {k: (ref_model.get(k), model.get(k)) for k in set(model) | set(ref_model) if model.get(k) != ref_model.get(k)})
    check("…and the same backtest rows", journal("brain-v2") == ref_v2)
    check("its working notes are cleared", db.brain_v2_stage.count_documents({}) == 0)

    # ── 7. the tick ────────────────────────────────────────────────────────────
    print("Le tick")
    db.platform_settings.delete_many({"key": {"$regex": "^brain_backtest:"}})
    JOBS.CHUNK = 200
    out = server.tick_pass()["brain_journal"]
    check("a shop never backtested is queued and run by the tick", sorted(out.get("backtest") or {}) == sorted(shops),
          out)
    check("…then nothing left", not server.tick_pass()["brain_journal"].get("backtest"))
    db.brain_models.update_one({"model": "brain-v2"}, {"$set": {"learned_at": now - dt.timedelta(days=2)}})
    V2._cache[:] = [0.0, None]
    out = server.tick_pass()["brain_journal"]
    check("brain-v2's daily learning runs through a job too", out.get("v2") and out["v2"].get("started"), out.get("v2"))

    # ── 8. a job that keeps failing ────────────────────────────────────────────
    print("Un job qui échoue")
    JOBS.start("backtest", "cafe", by="test", now=now)
    real_step = JOBS._HANDLERS["backtest"]
    JOBS._HANDLERS["backtest"] = lambda job, deadline: 1 / 0
    for _ in range(5):
        JOBS.run(budget_s=0, slices=1)
    JOBS._HANDLERS["backtest"] = real_step
    j = db.ai_jobs.find_one({"kind": "backtest", "tenant_id": "cafe"}, sort=[("created_at", -1)])
    check(f"stopped after 3 tries, marked failed ({j.get('status')}, {j.get('errors')})", j["status"] == "failed" and j["errors"] == 3)
    jobs = http("GET", "/api/admin/ai/precision", headers=BOSS).json().get("jobs") or []
    check("the page says so", any(x["status"] == "failed" and x.get("error") for x in jobs), jobs)
    check("a new click starts it again", http("POST", "/api/admin/ai/precision/backtest", headers=BOSS,
                                              json={"tenant_id": "cafe"}).json().get("started") == ["cafe"])

    # ── 9. who may ─────────────────────────────────────────────────────────────
    print("Accès")
    for who, h in (("merchant", OWNER), ("commercial", SALES)):
        a = http("POST", "/api/admin/ai/precision/backtest", headers=h, json={}).status_code
        b = http("POST", "/api/admin/ai/precision/learn", headers=h).status_code
        check(f"{who}: refused ({a}, {b})", {a, b} <= {401, 403})

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
