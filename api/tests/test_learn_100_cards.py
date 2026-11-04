"""
The shop's usual rhythm learns sooner (user, 2026-11-04: « 100 cards created ke
baad se start kr do… same time pr activity ke network se bhi seekhna shuru »).

    researched figure → network (from its first client, by weight) → the shop's
    own clients (from 100 cards, by weight; or 10 regulars as before)

No wall any more: one client who came back moves the figure a little, fifty move
it nearly all the way. A client who came back once counts, not only « regulars »:
a shop's clients may never fit that definition.

Run: cd api && /usr/local/bin/python3 tests/test_learn_100_cards.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-learn-100")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra != "" and not cond else ""))


def main():
    import server
    import auth
    import httpx
    from features import brain_v2 as V2, client_brain as CB

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    BARBER = {"sector": "salon", "activity_key": "barbier"}       # researched: 21 days

    print("\nThe network, from its first client")
    pri = lambda g, c: {"a:barbier": {"gap": g, "clients": c}}    # noqa: E731
    sp = lambda p: V2.sector_prior(BARBER, p)                     # noqa: E731
    check("no network → the researched figure", sp({}) == (21.0, "secteur"), sp({}))
    check("0 clients → the researched figure", sp(pri(40, 0)) == (21.0, "secteur"), sp(pri(40, 0)))
    one = sp(pri(40, 1))
    check(f"1 client: moves a little, says network ({one})", one[1] == "reseau" and 21 < one[0] < 24, one)
    ten = sp(pri(40, V2.NET_WEIGHT))
    check(f"as many clients as the research weighs: half-way ({ten})", abs(ten[0] - 30.5) < 0.1, ten)
    big = sp(pri(40, 1000))
    check(f"1000 clients: nearly all network ({big})", 39 < big[0] <= 40, big)
    check("a bad row never breaks it", sp({"a:barbier": {"gap": None, "clients": "x"}}) == (21.0, "secteur"))
    check("a zero gap is no figure", sp({"a:barbier": {"gap": 0, "clients": 50}}) == (21.0, "secteur"))
    check("another trade's figure is not read", sp({"a:cbd": {"gap": 5, "clients": 500}}) == (21.0, "secteur"))
    v = [{"visit_time": now - dt.timedelta(days=30)}, {"visit_time": now}]
    check("a client who came back once counts for the network", V2._own_gap(v) == 30)
    check("a client who never came back does not", V2._own_gap(v[:1]) is None)
    check("two scans on one day are not a rhythm", V2._own_gap([v[1], {"visit_time": now}]) is None)

    print("\nThe shop's own clients")

    def shop(tid, cards, one_gap=0, regulars=0, gap=40.0, deleted=0):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid, "plan": "vip", "subscription_status": "active",
                               "is_active": True, **BARBER})
        rows = []
        for i in range(cards + deleted):
            b = {}
            if i < one_gap:
                b = {"brain": {"n_gaps": 1, "own_gap": gap}}
            elif i < one_gap + regulars:
                b = {"brain": {"n_gaps": 4, "own_gap": gap}}
            rows.append({"id": f"{tid}-{i}", "tenant_id": tid, "name": "x", "created_at": now,
                         **({"deleted_at": now} if i >= cards else {}), **b})
        if rows:
            db.customers.insert_many(rows)
        return CB.usual_gap(tid, fresh=True)

    check("no card → where it starts", shop("s0", 0) == (21.0, "secteur"))
    check("99 cards, 20 came back → not yet", shop("s99", 99, one_gap=20) == (21.0, "secteur"))
    check("100 cards, none came back → nothing to learn", shop("s100z", 100) == (21.0, "secteur"))
    r = shop("s100o", 100, one_gap=1)
    check(f"100 cards, 1 came back: moves a little ({r})", r[1] == "boutique" and 21 < r[0] < 26, r)
    r = shop("s100m", 100, one_gap=50)
    check(f"100 cards, 50 who came back once, no « regular »: nearly theirs ({r})", r[1] == "boutique" and 37 < r[0] <= 40, r)
    r = shop("s500", 500, one_gap=400)
    check(f"400 came back: theirs ({r})", 39.5 < r[0] <= 40, r)
    r = shop("s30r", 30, regulars=12)
    check(f"30 cards but 12 regulars: already learning, as before ({r})", r[1] == "boutique", r)
    check("9 regulars and 50 cards: not yet", shop("s50r", 50, regulars=9) == (21.0, "secteur"))
    check("deleted cards do not count", shop("sdel", 99, one_gap=20, deleted=5) == (21.0, "secteur"))
    db.customers.insert_many([{"id": f"x{i}", "tenant_id": "other", "name": "x", "created_at": now} for i in range(200)])
    check("another shop's cards do not count", shop("s99b", 99, one_gap=20) == (21.0, "secteur"))
    check("both brains start from the same place", CB.prior_for("s100m", 1) == CB.prior_for("s100m", 2))

    print("\nOn the network too, when the shop has not started")
    db.brain_models.replace_one({"model": V2.MODEL}, {"model": V2.MODEL, "priors": pri(40, 500)}, upsert=True)
    V2._cache[:] = [0.0, None]
    r = CB.usual_gap("s0", fresh=True)
    check(f"a new shop starts from the network ({r})", r[1] == "reseau" and 38 < r[0] <= 40, r)
    check("and brain-v1 too (it never read the network)", CB.prior_for("s0", 1)[1] == "reseau")
    db.customers.delete_many({"tenant_id": "s100o"})
    db.customers.insert_many([{"id": f"so{i}", "tenant_id": "s100o", "name": "x", "created_at": now,
                               **({"brain": {"n_gaps": 1, "own_gap": 10.0}} if i == 0 else {})} for i in range(100)])
    r = CB.usual_gap("s100o", fresh=True)
    check(f"1 client at 10 days hardly moves a network figure of 40 ({r})", 33 < r[0] < 40, r)

    print("\nThrough a client's page")
    db.users.insert_one({"email": "o@s.fr", "role": "business_owner", "tenant_id": "s100m"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@s.fr", "role": "business_owner", "tenant_id": "s100m"})}
    db.customers.insert_one({"id": "new1", "tenant_id": "s100m", "name": "Neuf", "barcode_id": "FT-NEW1", "created_at": now - dt.timedelta(days=60),
                             "visits": 3, "last_visit_date": now - dt.timedelta(days=5)})
    db.visits.insert_many([{"id": f"v{i}", "tenant_id": "s100m", "customer_id": "new1", "visit_time": now - dt.timedelta(days=d)}
                           for i, d in enumerate((65, 35, 5))])
    CB._usual_cache.clear()
    b = CB.refresh("s100m", "new1")
    check("a client's rhythm is pulled to the shop's new figure", b.get("prior_source") == "boutique" and 37 < b["prior_gap"] <= 40, b.get("prior_gap"))

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
            return await ac.get("/api/owner/clients/new1/profil", headers=H)
    r = asyncio.get_event_loop().run_until_complete(go())
    check(f"the profile says it comes from the shop's clients ({r.status_code})",
          r.status_code == 200 and r.json()["rhythm"]["usual_source"] == "boutique", r.text[:200])


main()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
