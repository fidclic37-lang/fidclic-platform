"""
One reward is handed over once. Two tills pressing at the same moment, a double
tap, the public API retrying: the first gets it, the others are refused — on a
stamp card, on a points card, on a banked card. There is NO minimum time between
two visits (user, 2026-11-04: a client can really come several times a day), so
this is held by the writes themselves, never by a clock.

`between` runs the other till exactly where it hurts: after this call has read
the client, before it writes.

Run: cd api && /usr/local/bin/python3 tests/test_reward_once.py
"""
import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-reward-once")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


class Db:
    """server.db with some collections swapped, to make a write fail."""
    def __init__(self, real, **swap):
        self._real, self._swap = real, swap

    def __getattr__(self, name):
        return self._swap.get(name) or getattr(self._real, name)


class Coll:
    def __init__(self, real, **swap):
        self._real, self._swap = real, swap

    def __getattr__(self, name):
        return self._swap.get(name) or getattr(self._real, name)


def main():
    import server
    import auth
    import httpx
    from fastapi import HTTPException
    import features.wallet_passes as WP
    import features.push_subscriptions as PS

    db = server.db
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    real_set_for = server._SC.set_for_customer

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for t in ("t1", "t2"):
        db.tenants.insert_one({"id": t, "slug": t, "name": "Le Café", "is_active": True,
                               "plan": "vip", "subscription_status": "active"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "p@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10,
                                  "visits_per_stamp": 1, "reward_description": "Café offert"})
    db.card_templates.insert_one({"tenant_id": "t2", "programme": "points_visit", "points_per_visit": 20,
                                  "reward_points": 100, "reward_description": "Café offert"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    T1 = SimpleNamespace(tenant_id="t1", email="o@x.fr", role="business_owner", sub="o@x.fr")
    T2 = SimpleNamespace(tenant_id="t2", email="p@x.fr", role="business_owner", sub="p@x.fr")

    n = [0]

    def customer(tid="t1", **kw):
        n[0] += 1
        cid = f"c{n[0]}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": f"FT-ONE{n[0]:03d}", "name": "Léa",
                                 "visits": 0, "points": 0, "visits_at_last_redemption": 0, **kw})
        return cid, f"FT-ONE{n[0]:03d}"

    def bank(cid, tid="t1", **kw):
        db.rewards_earned.insert_one({"id": f"r-{cid}-{db.rewards_earned.count_documents({})}", "tenant_id": tid,
                                      "customer_id": cid, "status": "pending", "threshold": 10,
                                      "earned_at": server.datetime.now(server.timezone.utc), **kw})

    def take(cid, token=T1):
        return server.redeem_reward(server.RedeemRewardRequest(customer_id=cid, reward_name="Café"), token)

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return e
        return None

    def between(cid, token=T1):
        """This call reads the client, the other till hands the reward over,
        then this call goes on with what it read."""
        fired = []

        def hook(c):
            real_set_for(c)
            if not fired:
                fired.append(True)
                take(cid, token)
        server._SC.set_for_customer = hook
        try:
            return refused(lambda: take(cid, token))
        finally:
            server._SC.set_for_customer = real_set_for

    def given(cid):
        return db.rewards_redeemed.count_documents({"customer_id": cid})

    print("\nStamp card, full: the other till got in between")
    cid, _ = customer(visits=10)
    e = between(cid)
    check(f"the second is refused ({e and e.status_code})", e is not None and e.status_code == 400)
    check("one reward in the history", given(cid) == 1)
    c = db.customers.find_one({"id": cid})
    check("one card taken off, not two", c["visits_at_last_redemption"] == 10)
    check("counted once", c["rewards_redeemed_count"] == 1)

    print("\nStamp card holding two full cards: both really are there")
    cid, _ = customer(visits=20)
    check("the second one goes through", between(cid) is None)
    check("two rewards, two cards", given(cid) == 2 and db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 20)
    check("a third is refused", refused(lambda: take(cid)) is not None and given(cid) == 2)

    print("\nA client with no marker yet (older cards)")
    cid, _ = customer(visits=10)
    db.customers.update_one({"id": cid}, {"$unset": {"visits_at_last_redemption": ""}})
    e = between(cid)
    check("the second is refused", e is not None and given(cid) == 1)
    check("the marker is one card", db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 10)

    print("\nPoints card: the balance pays once")
    cid, _ = customer("t2", points=100)
    e = between(cid, T2)
    check("the second is refused", e is not None and e.status_code == 400 and "points" in str(e.detail))
    c = db.customers.find_one({"id": cid})
    check("one reward", given(cid) == 1)
    check("the balance paid once and never goes below 0", c["points"] == 0)
    cid, _ = customer("t2", points=250)
    check("a balance worth two: both go through", between(cid, T2) is None)
    check("and it paid for both", db.customers.find_one({"id": cid})["points"] == 50 and given(cid) == 2)
    cid, _ = customer("t2", points=99)
    check("one point short: refused", refused(lambda: take(cid, T2)) is not None and given(cid) == 0)
    cid, _ = customer("t2", points=100)
    check("points_spent is the price", take(cid, T2).get("points_spent") == 100)

    print("\nA banked card: the row is taken once")
    cid, _ = customer(visits=11, visits_at_last_redemption=10)
    bank(cid)
    e = between(cid)
    check("the second is refused", e is not None and given(cid) == 1)
    check("the row is redeemed", db.rewards_earned.find_one({"customer_id": cid})["status"] == "redeemed")
    check("the new card keeps its stamp", db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 10)
    cid, _ = customer(visits=11, visits_at_last_redemption=10)
    bank(cid)
    bank(cid)
    check("two banked: both go through", between(cid) is None and given(cid) == 2)
    check("none left", db.rewards_earned.count_documents({"customer_id": cid, "status": "pending"}) == 0)

    print("\nA scan banking a card while a redeem is under way must not be undone")
    cid, bc = customer(visits=11, visits_at_last_redemption=10)
    bank(cid)
    fired = []

    def scan_in_between(c):
        real_set_for(c)
        if not fired:
            fired.append(True)
            db.customers.update_one({"id": cid}, {"$set": {"visits_at_last_redemption": 20, "visits": 21}})
    server._SC.set_for_customer = scan_in_between
    try:
        take(cid)
    finally:
        server._SC.set_for_customer = real_set_for
    check("the marker the scan moved stays", db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 20)

    print("\nNext-visit rule still holds, with no gap between visits")
    cid, bc = customer(visits=9)
    d = server.scan_visit(server.ScanRequest(barcode_id=bc, amount_paid=5, apply="card"), T1)
    check("the scan that fills: refused", d["applied"]["ok"] is False and "prochaine visite" in d["applied"]["error"])
    d = server.scan_visit(server.ScanRequest(barcode_id=bc, amount_paid=5, apply="card"), T1)
    check("the very next scan, seconds later: handed over", d["applied"]["ok"] is True and given(cid) == 1)

    print("\nTwo tills scan the same 9/10 card at once, both ask for the reward")
    for attempt in range(5):
        cid, bc = customer(visits=9)
        both_in, both_read = threading.Barrier(2, timeout=20), threading.Barrier(2, timeout=20)
        in_redeem = threading.local()
        real_apply = server._apply_to_visit

        def apply_after_both(*a, **k):
            both_in.wait()                    # both visits are written
            in_redeem.on = True
            return real_apply(*a, **k)

        def read_together(c):
            real_set_for(c)
            if getattr(in_redeem, "on", False):
                in_redeem.on = False
                both_read.wait()              # both have read 11 visits, nothing taken

        server._apply_to_visit = apply_after_both
        server._SC.set_for_customer = read_together
        try:
            with ThreadPoolExecutor(2) as p:
                res = list(p.map(lambda _: server.scan_visit(
                    server.ScanRequest(barcode_id=bc, amount_paid=5, apply="card"), T1), range(2)))
        finally:
            server._apply_to_visit = real_apply
            server._SC.set_for_customer = real_set_for
        check(f"run {attempt + 1}: one till gets it, the other is told",
              sorted(bool(r["applied"]["ok"]) for r in res) == [False, True])
        check(f"run {attempt + 1}: one reward, both visits counted",
              given(cid) == 1 and db.customers.find_one({"id": cid})["visits"] == 11)
        check(f"run {attempt + 1}: nothing left waiting, one stamp on the new card",
              db.rewards_earned.count_documents({"customer_id": cid, "status": "pending"}) == 0
              and db.customers.find_one({"id": cid})["visits_at_last_redemption"] == 10)

    print("\n20 calls at once")
    for label, kw, tok, expected in (("full card", {"visits": 10}, T1, 1), ("two full cards", {"visits": 20}, T1, 2)):
        cid, _ = customer(**kw)
        go = threading.Barrier(20, timeout=20)

        def one(_):
            go.wait()
            return refused(lambda: take(cid, tok))
        with ThreadPoolExecutor(20) as p:
            errs = list(p.map(one, range(20)))
        check(f"{label}: exactly {expected} given", given(cid) == expected and errs.count(None) == expected)

    print("\nIf the history cannot be written, the client loses nothing")
    def boom(*a, **k):
        raise RuntimeError("database down")
    real_db = server.db
    broken = Db(real_db, rewards_redeemed=Coll(real_db.rewards_redeemed, insert_one=boom))

    def with_broken_history(fn):
        server.db = broken
        try:
            return fn()
        except RuntimeError:
            return "raised"
        finally:
            server.db = real_db

    cid, _ = customer(visits=10)
    check("stamp card: the error surfaces", with_broken_history(lambda: take(cid)) == "raised")
    c = db.customers.find_one({"id": cid})
    check("stamp card: the card is still full", c["visits_at_last_redemption"] == 0 and int(c.get("rewards_redeemed_count") or 0) == 0)
    check("…and can be handed over afterwards", take(cid) and given(cid) == 1)
    cid, _ = customer("t2", points=100)
    check("points card: the error surfaces", with_broken_history(lambda: take(cid, T2)) == "raised")
    c = db.customers.find_one({"id": cid})
    check("points card: the balance is back", c["points"] == 100 and int(c.get("rewards_redeemed_count") or 0) == 0)
    cid, _ = customer(visits=11, visits_at_last_redemption=10)
    bank(cid)
    check("banked: the error surfaces", with_broken_history(lambda: take(cid)) == "raised")
    check("banked: the row waits again", db.rewards_earned.find_one({"customer_id": cid})["status"] == "pending")
    c = db.customers.find_one({"id": cid})
    check("banked: nothing counted", int(c.get("rewards_redeemed_count") or 0) == 0)

    print("\nA client that keeps moving: told to retry, nothing given")
    cid, _ = customer(visits=10)
    never = Coll(real_db.customers, update_one=lambda *a, **k: SimpleNamespace(modified_count=0))
    server.db = Db(real_db, customers=never)
    try:
        e = refused(lambda: take(cid))
    finally:
        server.db = real_db
    check(f"409 ({e and e.status_code})", e is not None and e.status_code == 409)
    check("no history row", given(cid) == 0)

    print("\nThrough HTTP and the public API")
    cid, _ = customer(visits=10)
    r1 = http("POST", "/api/owner/rewards/redeem", headers=H, json={"customer_id": cid})
    r2 = http("POST", "/api/owner/rewards/redeem", headers=H, json={"customer_id": cid})
    check(f"first 200, second 400 ({r1.status_code}, {r2.status_code})", r1.status_code == 200 and r2.status_code == 400)
    import features.merchant_api as MA
    caller = MA.ApiCaller(tenant_id="t1", key_id="k", key_name="Caisse", scopes=["write"])
    cid, _ = customer(visits=10)
    fired = []

    def api_between(c):
        real_set_for(c)
        if not fired:
            fired.append(True)
            take(cid)
    server._SC.set_for_customer = api_between
    try:
        e = refused(lambda: MA.redeem(MA.RedeemIn(customer=cid, reward_name="Café"), caller))
    finally:
        server._SC.set_for_customer = real_set_for
    check(f"public API, lost the race: 409 no_reward ({e and e.status_code})",
          e is not None and e.status_code == 409 and e.detail["code"] == "no_reward")
    check("one reward", given(cid) == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
