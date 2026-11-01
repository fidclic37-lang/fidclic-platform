"""
Analyses for one establishment was slow (user, 2026-11-01: ~5 s for 90 days,
« Tous » 0.6 s). One request worked out the establishment's clients three
times — each a read of every visit of the shop, all time — and the visits had
no index for « this store's clients » nor « this client's visits ».

  • a Scope (one request) works out its clients once, its home clients once;
  • a new request (a new Scope) sees new data — nothing kept between requests;
  • the caller may change the set it gets back without changing the next one;
  • the two indexes exist;
  • the figures are the same.

Run: cd api && /usr/local/bin/python3 tests/test_store_scope_speed.py
"""
import asyncio
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-scope-speed")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    from features import store_scope as S
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "R", "plan": "vip", "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIB", "is_main": True}, {"id": "mon", "name": "MON"}]})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    for i in range(6):
        db.customers.insert_one({"id": f"m{i}", "tenant_id": "t1", "name": f"M{i}", "branch_id": "mon",
                                 "created_at": now - dt.timedelta(days=100), "deleted_at": None, "total_amount_paid": 10})
        db.customers.insert_one({"id": f"l{i}", "tenant_id": "t1", "name": f"L{i}", "branch_id": "main",
                                 "created_at": now - dt.timedelta(days=100), "deleted_at": None, "total_amount_paid": 10})
    db.visits.insert_many([{"id": f"vm{i}", "tenant_id": "t1", "customer_id": f"m{i}", "branch_id": "mon",
                            "amount_paid": 10, "visit_time": now - dt.timedelta(days=i + 1)} for i in range(6)])
    db.visits.insert_one({"id": "vx", "tenant_id": "t1", "customer_id": "l0", "branch_id": "mon",   # a Liberté client at PL-Monstre
                          "amount_paid": 5, "visit_time": now - dt.timedelta(days=2)})

    class T:
        tenant_id, role, email = "t1", "business_owner", "o@x.fr"

    calls = collections.Counter()
    for coll in ("visits", "customers"):
        c = db[coll]
        orig = c.distinct

        def wrap(*a, _o=orig, _k=coll, **k):
            calls[_k] += 1
            return _o(*a, **k)
        c.distinct = wrap

    print("\nOne request works out its clients once")
    sc = S.resolve(T, requested="mon")
    calls.clear()
    a = S.customer_ids(sc)
    b = S.customer_ids(sc)
    check("the same clients both times (6 of PL-Monstre + the Liberté client who came)",
          a == b == {f"m{i}" for i in range(6)} | {"l0"})
    check("one read of the visits, not two", calls["visits"] == 1)
    a.add("intrus")
    check("changing the set handed back does not change the next one", "intrus" not in S.customer_ids(sc))
    check("customer_filter reuses it too", calls["visits"] == 1 and "l0" in S.customer_filter(sc)["id"]["$in"])
    calls.clear()
    h1, h2 = S.home_customer_ids(sc), S.home_customer_ids(sc)
    check("home clients: the 6 of PL-Monstre, read once", h1 == h2 == {f"m{i}" for i in range(6)} and calls["customers"] <= 2)
    calls.clear()
    S.home_customer_ids(sc)
    check("…and not read again", calls["customers"] == 0)
    check("all establishments: None, no read", S.customer_ids(S.resolve(T, requested="all")) is None)

    print("\nNothing kept between requests")
    db.visits.insert_one({"id": "vy", "tenant_id": "t1", "customer_id": "l1", "branch_id": "mon",
                          "amount_paid": 5, "visit_time": now})
    check("the old request still answers what it read", "l1" not in S.customer_ids(sc))
    check("a new request sees the new visit", "l1" in S.customer_ids(S.resolve(T, requested="mon")))
    check("another establishment is another answer", "m0" not in S.customer_ids(S.resolve(T, requested="main")))

    print("\nThe indexes")
    vi = [tuple(k for k, _ in v["key"]) for v in db.visits.index_information().values()]
    check("visits (tenant_id, branch_id, customer_id) — « this store's clients »",
          ("tenant_id", "branch_id", "customer_id") in vi)
    check("visits (tenant_id, customer_id, visit_time) — « this client's visits »",
          ("tenant_id", "customer_id", "visit_time") in vi)

    print("\nA client's visits: through the new index when the clients are few")
    from features import referral_stores as RS
    seen = []
    orig_find = db.visits.find

    def spy(q=None, *a, **k):
        seen.append(q or {})
        return orig_find(q, *a, **k)
    db.visits.find = spy
    lo = now - dt.timedelta(days=30)
    few = RS.visits_by_store("t1", ["m0", "m1"], lo, now)
    check("a few clients over a period: asked by client and period (index)",
          "customer_id" in seen[-1] and "visit_time" in seen[-1])
    check("…same answer: m0 10 € and m1 10 € at PL-Monstre",
          few == {"m0": {"mon": {"visits": 1, "revenue": 10.0}}, "m1": {"mon": {"visits": 1, "revenue": 10.0}}})
    many = [f"m{i}" for i in range(6)] + [f"x{i}" for i in range(RS.FEW_IDS)]
    got = RS.visits_by_store("t1", many, lo, now)
    check("many clients over a period: read by period, kept by client (no huge $in)",
          "customer_id" not in seen[-1] and "visit_time" in seen[-1])
    check("…same answer for them", got == RS.visits_by_store("t1", [f"m{i}" for i in range(6)], lo, now))
    RS.visits_by_store("t1", ["m0"])
    check("all time: by client", "customer_id" in seen[-1] and "visit_time" not in seen[-1])
    db.visits.find = orig_find

    print("\nAnalyses › Vue for PL-Monstre — fewer reads, same figures")

    def get(store):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get("/api/owner/analyses?tab=vue&days=30", headers={**H, "X-FidClic-Store": store})
        return asyncio.get_event_loop().run_until_complete(run()).json()

    calls.clear()
    d = get("mon")["data"]
    check("the clients of PL-Monstre worked out once per request (was 3)", calls["visits"] == 1)
    strip = {x["key"]: x["value"] for x in d["strip"]}
    check("Clients totaux = 8 (6 + l0 + l1 who visited)", strip["clients"] == 8)
    check("Chiffre d'affaires = the 8 visits scanned here (70 €)", strip["revenue"] == 70)
    check("Visites total = 8", strip["visits"] == 8)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
