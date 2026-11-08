"""
The warehouse (user, 2026-11-04): a full copy of each shop's history in a
PRIVATE Vercel Blob store, so the weekly AI jobs stop reading two years of
visits from the M0 cluster. Copied every night, a month per file; « Produits
qui font revenir » reads it first and the cluster only for what came after
the copy — the old reading stays as the fallback for anything not sure.

The Blob below is a fake in memory: the real store answers the same REST
calls (services/blob_private.py).

Run: cd api && /usr/local/bin/python3 tests/test_warehouse.py
"""
import datetime as dt
import gzip
import json
import os
import random
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"
os.environ.pop("WAREHOUSE_BLOB_READ_WRITE_TOKEN", None)

UTC = dt.timezone.utc
TOKEN = "vercel_blob_rw_StOrE123abc_secretpart"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from services import blob_private as BP
    from features import warehouse as WH
    from features import product_return as PR
    from features import ai_jobs as JOBS

    db = server.db
    WH.init(db)
    PR.init(db)
    JOBS.init(db)
    passed = failed = 0

    def check(label, cond, show=None):
        global passed, failed
        cond = bool(cond)
        passed += cond
        failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or show is None else f"  → {show}"))

    # ------------------------------------------------------------------
    # the fake Blob: the REST calls the real store answers
    # ------------------------------------------------------------------
    class FakeBlob:
        def __init__(self):
            self.files, self.calls, self.fail_put, self.fail_get, self.corrupt = {}, [], set(), set(), set()

        def __call__(self, method, url, headers, body=None, timeout=None):
            self.calls.append((method, url, dict(headers)))
            if headers.get("authorization") != f"Bearer {TOKEN}":
                return 403, b"forbidden"
            from urllib.parse import urlparse, parse_qs, unquote
            u = urlparse(url)
            if method == "PUT" and u.netloc == "vercel.com" and u.path == "/api/blob/":
                path = parse_qs(u.query)["pathname"][0]
                if any(path.startswith(p) for p in self.fail_put):
                    return 500, b"boom"
                if path in self.files and headers.get("x-allow-overwrite") != "1":
                    return 409, b"exists"
                self.files[path] = bytes(body)
                return 200, json.dumps({"pathname": path,
                                        "url": f"https://store123abc.private.blob.vercel-storage.com/{path}"}).encode()
            if method == "GET" and u.netloc == "store123abc.private.blob.vercel-storage.com":
                path = unquote(u.path.lstrip("/"))
                if any(path.startswith(p) for p in self.fail_get):
                    return 502, b"bad gateway"
                if path not in self.files:
                    return 404, b"not found"
                if path in self.corrupt:
                    return 200, b"not gzip at all"
                return 200, self.files[path]
            if method == "POST" and u.netloc == "vercel.com" and u.path == "/api/blob/delete":
                for x in json.loads(body)["urls"]:
                    p = urlparse(x).path.lstrip("/") if x.startswith("https://") else x
                    self.files.pop(unquote(p), None)
                return 200, b"{}"
            return 400, b"unknown call"

    def fresh_blob():
        fb = FakeBlob()
        BP._http = fb
        return fb

    real_http = BP._http

    # ------------------------------------------------------------------
    print("\nThe private Blob client")
    # ------------------------------------------------------------------
    fb = fresh_blob()
    check("no token: not configured", not BP.configured())
    check("no token: a put is refused, nothing sent", BP.put("wh/x.txt", b"a") is False and not fb.calls)
    try:
        BP.get("wh/x.txt")
        check("no token: a get raises (never « not there »)", False)
    except BP.BlobError:
        check("no token: a get raises (never « not there »)", True)
    os.environ["WAREHOUSE_BLOB_READ_WRITE_TOKEN"] = "nonsense"
    check("a token without a store id: not configured", not BP.configured())
    os.environ["WAREHOUSE_BLOB_READ_WRITE_TOKEN"] = TOKEN
    check("a good token: configured, store id read from it", BP.configured() and BP.store_id() == "store123abc")
    check("put: ok", BP.put("wh/v1/t1/a.jsonl.gz", b"abc", "application/gzip") is True)
    m, url, h = fb.calls[-1]
    check("put: PUT on the Blob API with the path", m == "PUT" and url.startswith("https://vercel.com/api/blob/?pathname=wh%2Fv1%2Ft1%2Fa.jsonl.gz"), url)
    check("put: private access, fixed name, overwrite allowed, content type",
          h.get("x-vercel-blob-access") == "private" and h.get("x-add-random-suffix") == "0"
          and h.get("x-allow-overwrite") == "1" and h.get("x-content-type") == "application/gzip", h)
    check("put: the store id is sent", h.get("x-vercel-blob-store-id") == "store123abc", h)
    check("get: the bytes back from the private host", BP.get("wh/v1/t1/a.jsonl.gz") == b"abc")
    m, url, h = fb.calls[-1]
    check("get: GET on <store>.private.blob.vercel-storage.com with the bearer",
          m == "GET" and url == "https://store123abc.private.blob.vercel-storage.com/wh/v1/t1/a.jsonl.gz"
          and h.get("authorization") == f"Bearer {TOKEN}", url)
    check("get: a file not there → None", BP.get("wh/v1/t1/none.gz") is None)
    fb.fail_get.add("wh/v1/t1/a")
    try:
        BP.get("wh/v1/t1/a.jsonl.gz")
        check("get: a 502 raises (never read as « not there »)", False)
    except BP.BlobError:
        check("get: a 502 raises (never read as « not there »)", True)
    fb.fail_get.clear()
    fb.fail_put.add("wh/bad")
    check("put: a 500 → False", BP.put("wh/bad/x", b"a") is False)
    check("delete: the files go", BP.delete(["wh/v1/t1/a.jsonl.gz"]) is True and not fb.files)
    for bad in ("../etc/passwd", "/wh/x", "wh/../x", "wh//x", "wh/x y", "", "wh/x?y", "wh/x#y", "a" * 600):
        try:
            BP.put(bad, b"a")
            ok = False
        except ValueError:
            ok = True
        check(f"a path like {bad[:20]!r} is refused before any call", ok)

    def raising(*a, **k):
        raise OSError("network down")
    BP._http = raising
    check("put: the network down → False, no crash", BP.put("wh/x", b"a") is False)
    try:
        BP.get("wh/x")
        check("get: the network down raises BlobError", False)
    except BP.BlobError:
        check("get: the network down raises BlobError", True)

    # ------------------------------------------------------------------
    print("\nThe file format")
    # ------------------------------------------------------------------
    rows = [{"id": "v1", "visit_time": dt.datetime(2026, 3, 29, 1, 30, 0, 123000), "amount_paid": 12.5,
             "items": [{"item_id": "p1", "name": "Café crème", "qty": 2}], "branch_id": None,
             "nested": {"at": dt.datetime(2025, 12, 31, 23, 59)}},
            {"id": "v2", "visit_time": dt.datetime(2026, 3, 29, 2, 30, tzinfo=UTC), "note": "« é » 😀"}]
    back = WH.decode_rows(WH.encode_rows(rows))
    check("a row comes back the same (dates, lists, None, accents)", back[0] == rows[0], back[0])
    check("an aware date comes back as Mongo hands it: naive UTC",
          back[1]["visit_time"] == dt.datetime(2026, 3, 29, 2, 30) and back[1]["note"] == "« é » 😀", back[1])
    check("the file is gzipped JSON lines", gzip.decompress(WH.encode_rows(rows)).count(b"\n") == 2)
    check("no rows → an empty file that reads back as no rows", WH.decode_rows(WH.encode_rows([])) == [])
    check("a month key is the UTC month", WH.month_key(dt.datetime(2026, 10, 31, 23, 30, tzinfo=UTC)) == "2026-10"
          and WH.month_key(dt.datetime(2026, 11, 1, 0, 0)) == "2026-11")
    s, e = WH.month_bounds("2026-12")
    check("December's bounds run into January", s == dt.datetime(2026, 12, 1, tzinfo=UTC)
          and e == dt.datetime(2027, 1, 1, tzinfo=UTC))
    try:
        WH.encode_rows([{"x": object()}])
        check("a value JSON cannot hold is refused (never written as text)", False)
    except TypeError:
        check("a value JSON cannot hold is refused (never written as text)", True)

    # ------------------------------------------------------------------
    print("\nThe nightly copy")
    # ------------------------------------------------------------------
    fb = fresh_blob()
    NIGHT = dt.datetime(2026, 11, 8, 2, 0, tzinfo=UTC)        # 03:00 Paris

    def visit(vid, tid, at, cid="c1", **kw):
        return {"id": vid, "tenant_id": tid, "customer_id": cid, "visit_time": at, "amount_paid": 10.0,
                "items": [{"item_id": "p1", "name": "Café"}], **kw}

    db.tenants.insert_many([{"id": "ta", "name": "A"}, {"id": "tb", "name": "B"}, {"id": "bad/id", "name": "X"}])
    va = [visit(f"a{i}", "ta", dt.datetime(2026, 8, 1, tzinfo=UTC) + dt.timedelta(hours=37 * i)) for i in range(60)]
    vb = [visit(f"b{i}", "tb", dt.datetime(2026, 9, 3, tzinfo=UTC) + dt.timedelta(days=i), cid="cb") for i in range(30)]
    db.visits.insert_many(va + vb + [visit("nodate", "ta", "pas une date")])
    db.offer_uses.insert_many([{"id": "o1", "tenant_id": "ta", "customer_id": "c1",
                                "used_at": dt.datetime(2026, 9, 10, tzinfo=UTC)}])

    os.environ.pop("WAREHOUSE_BLOB_READ_WRITE_TOKEN")
    check("no store: the night does nothing", WH.due(NIGHT).get("skipped") == "no_store" and not fb.files)
    os.environ["WAREHOUSE_BLOB_READ_WRITE_TOKEN"] = TOKEN
    check("in the afternoon nothing is copied (the cluster is busy)",
          WH.due(dt.datetime(2026, 11, 8, 13, 0, tzinfo=UTC)).get("skipped") == "daytime" and not fb.files)
    out = WH.due(NIGHT)
    st = db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})
    check("at night the shop is copied and ready", st and st.get("ready") and not st.get("dirty"), st)
    months = sorted(st["months"])
    check("one file per month that has visits", months == ["2026-08", "2026-09", "2026-10", "2026-11"][:len(months)]
          and months[0] == "2026-08", months)
    total = sum(m["n"] for m in st["months"].values())
    check("every dated visit is in it, the undated one is not", total == 60, total)
    files_a = [p for p in fb.files if p.startswith("wh/v1/ta/visits/")]
    check("files under wh/v1/<shop>/visits/<month>.v<n>.jsonl.gz",
          all(p.endswith(".jsonl.gz") and ".v" in p for p in files_a) and len(files_a) == len(months), files_a)
    rows_a = [r for p in files_a for r in WH.decode_rows(fb.files[p])]
    check("the copy is whole: personal fields kept (decision 2026-11-04)",
          {r["id"] for r in rows_a} == {v["id"] for v in va} and all(r.get("customer_id") == "c1" for r in rows_a))
    check("another shop's visits are never in this shop's files", not any(r["id"].startswith("b") for r in rows_a))
    check("the other shop has its own copy", db.warehouse_state.find_one({"tenant_id": "tb", "stream": "visits"})["ready"])
    check("offer uses are copied too", db.warehouse_state.find_one({"tenant_id": "ta", "stream": "offer_uses"})["ready"])
    check("a shop id that is not a path is skipped", not any("bad" in p for p in fb.files)
          and not db.warehouse_state.find_one({"tenant_id": "bad/id"}))
    check("a shop with no rewards gets an empty, ready copy",
          (db.warehouse_state.find_one({"tenant_id": "ta", "stream": "rewards_redeemed"}) or {}).get("ready")
          and db.warehouse_state.find_one({"tenant_id": "ta", "stream": "rewards_redeemed"})["months"] == {})
    n_calls = len(fb.calls)
    WH.due(NIGHT + dt.timedelta(minutes=15))
    check("the next tick the same night copies nothing again", len(fb.calls) == n_calls, len(fb.calls) - n_calls)

    # next night: new visits, a backdated one, a deleted one
    NIGHT2 = NIGHT + dt.timedelta(days=1)
    db.visits.insert_one(visit("new1", "ta", NIGHT + dt.timedelta(hours=10)))
    db.visits.insert_one(visit("late", "ta", dt.datetime(2026, 8, 15, tzinfo=UTC)))     # paper stamps, backdated
    db.visits.delete_one({"id": "a25"})                                                  # a September visit
    old_aug, old_sep = st["months"]["2026-08"], st["months"]["2026-09"]
    WH.due(NIGHT2)
    st2 = db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})
    aug = [r for p in fb.files if p.startswith("wh/v1/ta/visits/2026-08") for r in WH.decode_rows(fb.files[p])]
    sep = [r for p in fb.files if p.startswith("wh/v1/ta/visits/2026-09") for r in WH.decode_rows(fb.files[p])]
    check("a backdated visit: its month is copied again",
          st2["months"]["2026-08"]["v"] > old_aug["v"] and "late" in {r["id"] for r in aug}, st2["months"]["2026-08"])
    check("a deleted visit: its month is copied again without it",
          st2["months"]["2026-09"]["v"] > old_sep["v"] and "a25" not in {r["id"] for r in sep}
          and len(sep) == old_sep["n"] - 1, st2["months"]["2026-09"])
    check("the old version of the month is deleted", len([p for p in fb.files if p.startswith("wh/v1/ta/visits/2026-08")]) == 1)
    nov = [r for p in fb.files if p.startswith("wh/v1/ta/visits/2026-11") for r in WH.decode_rows(fb.files[p])]
    check("tonight's month has yesterday's visit", "new1" in {r["id"] for r in nov})
    check("the copy now reaches tonight", WH._aware(st2["cut"]) == NIGHT2)
    check("a month that did not change keeps its file",
          st2["months"]["2026-10"]["v"] == st["months"]["2026-10"]["v"])
    # an edit that keeps the count (one in, one out the same month) waits for the 30-day refresh
    db.visits.insert_one(visit("swap-in", "ta", dt.datetime(2026, 10, 10, tzinfo=UTC)))
    db.visits.delete_one({"id": "a45"})
    db.warehouse_state.update_one({"tenant_id": "ta", "stream": "visits"},
                                  {"$set": {"months.2026-10.at": NIGHT2 - dt.timedelta(days=31), "synced_on": "2026-11-08"}})
    WH.due(NIGHT2 + dt.timedelta(minutes=5))
    oct_ = [r for p in fb.files if p.startswith("wh/v1/ta/visits/2026-10") for r in WH.decode_rows(fb.files[p])]
    check("an edit that keeps the count is caught by the 30-day refresh", "swap-in" in {r["id"] for r in oct_}
          and "a45" not in {r["id"] for r in oct_})

    # the privacy rules: the retention unlink and a store tagging mark the shop dirty
    WH.mark_dirty("ta", "retention")
    check("a privacy change: the copy is not used until rebuilt",
          not db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})["ready"])
    db.visits.update_many({"tenant_id": "ta", "visit_time": {"$lt": dt.datetime(2026, 9, 1, tzinfo=UTC)}},
                          {"$set": {"customer_id": None}})
    WH.due(NIGHT2 + dt.timedelta(minutes=15))
    st3 = db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})
    aug = [r for p in fb.files if p.startswith("wh/v1/ta/visits/2026-08") for r in WH.decode_rows(fb.files[p])]
    check("rebuilt the same night: an unlinked visit has no client in the copy either",
          st3["ready"] and aug and all(r.get("customer_id") is None for r in aug))
    check("no file of the old build is left", all(
        p.split("/")[-1].split(".v")[0] in st3["months"] and
        int(p.split(".v")[1].split(".")[0]) == st3["months"][p.split("/")[-1].split(".v")[0]]["v"]
        for p in fb.files if p.startswith("wh/v1/ta/visits/")))

    # a store failing in the middle
    fb.fail_put.add("wh/v1/tb/visits/2026-10")
    WH.mark_dirty("tb", "test")
    WH.due(NIGHT2 + dt.timedelta(minutes=30))
    stb = db.warehouse_state.find_one({"tenant_id": "tb", "stream": "visits"})
    check("Blob refuses a month: the copy stays not ready, the error is kept", not stb["ready"] and stb.get("error"), stb.get("error"))
    fb.fail_put.clear()
    WH.due(NIGHT2 + dt.timedelta(minutes=45))
    check("the next tick finishes it", db.warehouse_state.find_one({"tenant_id": "tb", "stream": "visits"})["ready"])

    # the time budget
    for i in range(6):
        db.tenants.insert_one({"id": f"tz{i}", "name": f"Z{i}"})
        db.visits.insert_many([visit(f"z{i}-{k}", f"tz{i}", dt.datetime(2025, 1, 1, tzinfo=UTC) + dt.timedelta(days=13 * k))
                               for k in range(50)])
    clock = {"t": 0.0}
    real_clock = WH._clock
    WH._clock = lambda: clock.__setitem__("t", clock["t"] + 1.0) or clock["t"]
    r = WH.due(NIGHT2 + dt.timedelta(hours=1), budget_s=5)
    WH._clock = real_clock
    ready_z = db.warehouse_state.count_documents({"tenant_id": {"$regex": "^tz"}, "stream": "visits", "ready": True})
    check("a tick stops at its time budget", ready_z < 6 and r.get("stopped") == "budget", (ready_z, r))
    for k in range(10):
        WH.due(NIGHT2 + dt.timedelta(hours=1, minutes=15 * (k + 1)))
    check("the following ticks finish the others",
          db.warehouse_state.count_documents({"tenant_id": {"$regex": "^tz"}, "stream": "visits", "ready": True}) == 6)

    # a shop deleted (account deleted, or the super admin): its copy goes the next night
    gone = [p for p in fb.files if p.startswith("wh/v1/tz0/")]
    db.tenants.delete_one({"id": "tz0"})
    db.visits.delete_many({"tenant_id": "tz0"})
    db.warehouse_state.update_many({}, {"$set": {"synced_on": "2026-11-08"}})
    WH.due(NIGHT2 + dt.timedelta(hours=3, minutes=40))                                  # 05:40 Paris
    check("a deleted shop: every file of its copy is deleted",
          gone and not any(p.startswith("wh/v1/tz0/") for p in fb.files), len(gone))
    check("a deleted shop: its state is gone too", not db.warehouse_state.find_one({"tenant_id": "tz0"}))
    check("the other shops' files are untouched", any(p.startswith("wh/v1/tz1/") for p in fb.files))

    # ------------------------------------------------------------------
    print("\nReading the copy")
    # ------------------------------------------------------------------
    NOW = NIGHT2 + dt.timedelta(hours=8)
    db.visits.insert_one(visit("today", "ta", NOW - dt.timedelta(hours=1)))       # after the copy
    proj = {"_id": 0, "id": 1, "customer_id": 1, "visit_time": 1, "items": 1}

    def mongo_ids(tid, cond):
        return sorted(v["id"] for v in db.visits.find({"tenant_id": tid, "visit_time": cond}, {"_id": 0, "id": 1}))

    for label, cond in (("two years to now", {"$gte": NOW - dt.timedelta(days=730), "$lte": NOW}),
                        ("from the middle of a month", {"$gte": dt.datetime(2026, 8, 17, 5, tzinfo=UTC), "$lte": NOW}),
                        ("a range ending before the copy", {"$gte": dt.datetime(2026, 8, 1, tzinfo=UTC),
                                                            "$lt": dt.datetime(2026, 9, 2, 12, tzinfo=UTC)}),
                        ("only a start", {"$gte": dt.datetime(2026, 10, 1, tzinfo=UTC)}),
                        ("naive bounds", {"$gte": dt.datetime(2026, 8, 20), "$lte": NOW.replace(tzinfo=None)})):
        got = WH.rows("visits", "ta", "visit_time", cond, proj, now=NOW)
        check(f"the copy + the cluster after it = the cluster alone ({label})",
              got is not None and sorted(r["id"] for r in got) == mongo_ids("ta", cond),
              None if got is None else (len(got), len(mongo_ids("ta", cond))))
    got = WH.rows("visits", "ta", "visit_time", {"$gte": NOW - dt.timedelta(days=730)}, proj, now=NOW)
    check("the projection is kept (no amount, no _id)", got and all(set(r) <= {"id", "customer_id", "visit_time", "items"} for r in got))
    check("tonight's visit after the copy comes from the cluster", "today" in {r["id"] for r in got})

    # spy: the cluster is only asked for what came after the copy
    seen = []
    real_find = db.visits.find

    def spy(q=None, *a, **k):
        seen.append(q)
        return real_find(q, *a, **k)
    db.visits.find = spy
    WH.rows("visits", "ta", "visit_time", {"$gte": NOW - dt.timedelta(days=730), "$lte": NOW}, proj, now=NOW)
    db.visits.find = real_find
    cut = WH._aware(db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})["cut"])
    check("the cluster is asked only for the visits after the copy",
          len(seen) == 1 and WH._aware(seen[0]["visit_time"]["$gte"]) == cut, seen)

    def none_when(label, prep, undo):
        prep()
        got = WH.rows("visits", "ta", "visit_time", {"$gte": NOW - dt.timedelta(days=730)}, proj, now=NOW)
        undo()
        check(f"{label} → no copy (the old reading answers)", got is None)

    st = db.warehouse_state.find_one({"tenant_id": "ta", "stream": "visits"})
    some = sorted(st["months"])[0]
    path = f"wh/v1/ta/visits/{some}.v{st['months'][some]['v']}.jsonl.gz"
    keep = fb.files[path]
    none_when("a month file missing", lambda: fb.files.pop(path), lambda: fb.files.__setitem__(path, keep))
    none_when("a month file corrupt", lambda: fb.corrupt.add(path), lambda: fb.corrupt.discard(path))
    none_when("Blob down", lambda: fb.fail_get.add("wh/"), lambda: fb.fail_get.clear())
    none_when("a file with fewer rows than counted",
              lambda: fb.files.__setitem__(path, WH.encode_rows(WH.decode_rows(keep)[:-1])),
              lambda: fb.files.__setitem__(path, keep))
    none_when("the copy older than 3 days",
              lambda: db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"cut": NOW - dt.timedelta(days=4)}}),
              lambda: db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"cut": st["cut"]}}))
    none_when("a privacy change waiting for its rebuild",
              lambda: db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"dirty": True}}),
              lambda: db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"dirty": False}}))
    none_when("no store configured", lambda: os.environ.pop("WAREHOUSE_BLOB_READ_WRITE_TOKEN"),
              lambda: os.environ.__setitem__("WAREHOUSE_BLOB_READ_WRITE_TOKEN", TOKEN))
    check("a shop never copied → no copy", WH.rows("visits", "nobody", "visit_time", {"$gte": NOW}, proj, now=NOW) is None)
    check("find() falls back to the cluster when there is no copy",
          sorted(v["id"] for v in WH.find("visits", "nobody-too", "visit_time", {"$gte": NOW}, proj, now=NOW)) == [])
    db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"dirty": True}})
    fb_rows = list(WH.find("visits", "ta", "visit_time", {"$gte": NOW - dt.timedelta(days=730)}, proj, now=NOW))
    db.warehouse_state.update_one({"_id": st["_id"]}, {"$set": {"dirty": False}})
    check("find() with the copy out = the cluster's rows",
          sorted(r["id"] for r in fb_rows) == mongo_ids("ta", {"$gte": NOW - dt.timedelta(days=730)}))
    check("offer uses read from the copy",
          [r["id"] for r in (WH.rows("offer_uses", "ta", "used_at", {"$gte": NOW - dt.timedelta(days=730)},
                                     {"_id": 0, "id": 1}, now=NOW) or [])] == ["o1"])

    # ------------------------------------------------------------------
    print("\n« Produits qui font revenir » on the copy")
    # ------------------------------------------------------------------
    rnd = random.Random(5)
    db.tenants.insert_one({"id": "tp", "name": "Le Barbier", "plan": "vip", "product_return_window_days": 30})
    CAT = [("p-coupe", "Coupe"), ("p-barbe", "Barbe"), ("p-gel", "Gel"), ("p-colo", "Coloration")]
    db.tenant_catalog.insert_one({"tenant_id": "tp", "items": [{"id": i, "name": n, "price": 10} for i, n in CAT]})
    PNOW = NIGHT2 + dt.timedelta(hours=6)
    vs, cs = [], []
    for k in range(400):
        cid = f"pc{k}"
        t = PNOW - dt.timedelta(days=rnd.randint(60, 600))
        cs.append({"id": cid, "tenant_id": "tp", "name": f"Client {k}", "created_at": t - dt.timedelta(days=1)})
        for j in range(rnd.randint(1, 6)):
            items = [{"item_id": i, "name": n, "qty": 1, "price": 10} for i, n in CAT if rnd.random() < .4]
            vs.append(visit(f"pv{k}-{j}", "tp", t, cid=cid, items=items, branch_id=None))
            t += dt.timedelta(days=rnd.randint(5, 70))
            if t > PNOW:
                break
    db.customers.insert_many(cs)
    db.visits.insert_many(vs)
    db.offer_uses.insert_one({"id": "po", "tenant_id": "tp", "customer_id": "pc1", "used_at": PNOW - dt.timedelta(days=90)})
    PR.compute("tp", PNOW)
    plain = db.product_return.find_one({"tenant_id": "tp", "store": "all"}, {"_id": 0, "built_at": 0})
    WH.due(NIGHT2 + dt.timedelta(hours=3))
    check("the shop is copied", db.warehouse_state.find_one({"tenant_id": "tp", "stream": "visits"})["ready"])
    db.visits.insert_one(visit("pv-after", "tp", PNOW - dt.timedelta(hours=2), cid="pc2",
                               items=[{"item_id": "p-gel", "name": "Gel"}]))
    db.visits.delete_one({"id": "pv-after"})       # keep the two runs on the same data
    calls = []
    real = WH.rows

    def counting(*a, **k):
        r = real(*a, **k)
        calls.append((a[0], r is not None))
        return r
    WH.rows = counting
    seen.clear()
    db.visits.find = spy
    PR.compute("tp", PNOW)
    db.visits.find = real_find
    WH.rows = real
    from_copy = db.product_return.find_one({"tenant_id": "tp", "store": "all"}, {"_id": 0, "built_at": 0})
    check("the figures read the copy", ("visits", True) in calls, calls)
    check("the same figures as the cluster alone", from_copy == plain)
    big = [q for q in seen if isinstance(q, dict) and isinstance(q.get("visit_time"), dict)
           and "$gte" in q["visit_time"] and WH._aware(q["visit_time"]["$gte"]) < PNOW - dt.timedelta(days=30)
           and q.get("tenant_id") == "tp"]
    check("the two years of visits are no longer read from the cluster by the figures", not big, big[:2])
    fb.fail_get.add("wh/v1/tp/")
    PR.compute("tp", PNOW)
    fb.fail_get.clear()
    check("Blob down: the same figures from the cluster",
          db.product_return.find_one({"tenant_id": "tp", "store": "all"}, {"_id": 0, "built_at": 0}) == plain)

    # ------------------------------------------------------------------
    print("\nThe hooks that change old visits")
    # ------------------------------------------------------------------
    from features import privacy_page as PP
    PP.init(db) if hasattr(PP, "init") else None
    db.tenants.update_one({"id": "tp"}, {"$set": {"privacy": {"retention": {"saved_at": PNOW, "inactive_years": 10,
                                                                             "transactions_years": 1}}}})
    PP.apply_retention(PNOW)
    check("the retention unlinks old visits → the copy is rebuilt before use",
          db.warehouse_state.find_one({"tenant_id": "tp", "stream": "visits"})["dirty"])
    WH.due(NIGHT2 + dt.timedelta(hours=3, minutes=15))
    check("rebuilt: ready again", db.warehouse_state.find_one({"tenant_id": "tp", "stream": "visits"})["ready"])
    PP.apply_retention(PNOW)
    check("a retention pass that changes nothing leaves the copy alone",
          not db.warehouse_state.find_one({"tenant_id": "tp", "stream": "visits"})["dirty"])

    # ------------------------------------------------------------------
    print("\nThe super admin's check")
    # ------------------------------------------------------------------
    import asyncio
    import httpx

    def call(method, url, role, tid=None):
        h = {"Authorization": "Bearer " + auth.create_access_token({"sub": f"{role}@x.fr", "role": role, "tenant_id": tid})}

        async def go():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.request(method, url, headers=h)
        return asyncio.get_event_loop().run_until_complete(go())

    db.users.insert_many([{"email": "super_admin@x.fr", "role": "super_admin"},
                          {"email": "business_owner@x.fr", "role": "business_owner", "tenant_id": "ta"}])
    r = call("GET", "/api/admin/warehouse", "super_admin")
    body = r.json() if r.status_code == 200 else {}
    check("the super admin sees the copy's state", r.status_code == 200 and body.get("configured") is True
          and body.get("streams", {}).get("visits", {}).get("ready", 0) >= 3, (r.status_code, body))
    check("the page never shows the token or the store id", TOKEN not in r.text and "store123abc" not in r.text)
    check("an owner is refused", call("GET", "/api/admin/warehouse", "business_owner", "ta").status_code == 403)
    check("an owner cannot run the check", call("POST", "/api/admin/warehouse/check", "business_owner", "ta").status_code == 403)
    r = call("POST", "/api/admin/warehouse/check", "super_admin")
    check("the check writes, reads back and deletes a test file",
          r.status_code == 200 and r.json().get("ok") is True and not any(p.startswith("wh/check/") for p in fb.files), r.text)
    fb.fail_put.add("wh/check/")
    r = call("POST", "/api/admin/warehouse/check", "super_admin")
    check("a store refusing writes: the check says which step", r.status_code == 200 and r.json().get("ok") is False
          and r.json().get("step") == "write", r.text)
    fb.fail_put.clear()

    # ------------------------------------------------------------------
    print("\nThe tick")
    # ------------------------------------------------------------------
    real_due = WH.due
    WH.due = lambda now=None, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    out = server.tick_pass(NIGHT2 + dt.timedelta(hours=4))
    WH.due = real_due
    check("a warehouse failure never stops the tick", any(f.get("step") == "warehouse" for f in out["failures"])
          and "product_return" in out, out.get("failures"))
    out = server.tick_pass(NIGHT2 + dt.timedelta(hours=4, minutes=15))
    check("the tick runs the copy", "warehouse" in out, list(out))

    BP._http = real_http
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
