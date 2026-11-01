"""
The same card scanned several times at once — a double tap, two tills
(user, 2026-11-01: « race condition waala fix kr do »). Every scan counts,
nothing twice:

    · visits, points, points earned and the amount spent add up exactly
    · a full card is banked once — never by two scans at the same time
    · the card's meter ends where the same scans one after the other leave it

Before: each scan read the client, added in Python and wrote the totals back
($set), so two scans at once lost one; and both banked the same full card.

Run: cd api && python3 tests/test_scan_concurrency.py
"""
import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-scan-concurrency")
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
    import features.wallet_passes as WP
    import features.push_subscriptions as PS

    db = server.db
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    WP.notify_tenant = lambda *a, **k: {"sent": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "salon", "name": "Salon", "is_active": True, "plan": "vip",
                           "subscription_status": "active", "sector": "salon", "activity_key": "coiffure_mixte"})
    db.users.insert_one({"email": "s@x.fr", "role": "staff", "tenant_id": "t1"})
    STAFF = {"Authorization": "Bearer " + auth.create_access_token({"sub": "s@x.fr", "role": "staff", "tenant_id": "t1"})}

    def template(**kw):
        db.card_templates.delete_many({"tenant_id": "t1"})
        db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 3,
                                      "visits_per_stamp": 1, "points_per_visit": 10, **kw})

    n = [0]

    def new_customer():
        n[0] += 1
        r = http("POST", "/api/join/salon", json={"name": f"Client {n[0]}", "phone": f"06555{n[0]:05d}",
                                                  "postal_code": "37000", "birthday": "1990-01-02", "consent": True})
        assert r.status_code == 200, r.text
        bc = r.json()["barcode_id"]
        return bc, db.customers.find_one({"barcode_id": bc})["id"]

    def burst(bc, k, **body):
        codes = []
        def go():
            r = http("POST", "/api/owner/scan", headers=STAFF, json={"barcode_id": bc, "amount_paid": 5.5, **body})
            codes.append(r.status_code)
        ts = [threading.Thread(target=go) for _ in range(k)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        return codes

    def state(cid, threshold):
        c = db.customers.find_one({"id": cid})
        meter = int(c["visits"]) - int(c.get("visits_at_last_redemption") or 0)
        banked = list(db.rewards_earned.find({"customer_id": cid}))
        return c, meter, banked

    print("\n10 scans of one card at once — tampons card of 3")
    template()
    for run in range(3):
        bc, cid = new_customer()
        codes = burst(bc, 10)
        c, meter, banked = state(cid, 3)
        check(f"run {run}: every scan answered 200", codes.count(200) == 10, codes)
        check(f"run {run}: 10 visits, none lost", c["visits"] == 10, c["visits"])
        check(f"run {run}: 3 full cards banked + 1 on the card = the 10 visits",
              len(banked) == 3 and meter == 1, (len(banked), meter))
        marks = [b.get("visits_at_completion") for b in banked]
        check(f"run {run}: each banked card is a different card", len(set(marks)) == len(marks), marks)
        check(f"run {run}: amount spent 10 × 5,50 = 55,00", round(float(c["total_amount_paid"]), 2) == 55.0,
              c["total_amount_paid"])
        check(f"run {run}: 10 visit rows", db.visits.count_documents({"customer_id": cid}) == 10)

    print("\n10 scans at once, « Plusieurs personnes » × 3 — card of 10")
    template(reward_threshold_stamps=10)
    for run in range(3):
        bc, cid = new_customer()
        burst(bc, 10, persons=3)
        c, meter, banked = state(cid, 10)
        check(f"run {run}: 10 visits", c["visits"] == 10, c["visits"])
        check(f"run {run}: 30 tampons = 2 cards banked + a full card (10)", len(banked) == 2 and meter == 10,
              (len(banked), meter))

    print("\n10 scans at once — points par visite")
    template(programme="points_visit", points_mode="per_visit")
    for run in range(3):
        bc, cid = new_customer()
        burst(bc, 10)
        c, _, _ = state(cid, 3)
        check(f"run {run}: 10 × 10 points, earned and balance", c["points"] == 100 and c["points_lifetime"] == 100,
              (c["points"], c.get("points_lifetime")))
        check(f"run {run}: palier from the real totals", c["visits"] == 10 and c.get("tier"))

    print("\nOne scan at a time is unchanged")
    template()
    bc, cid = new_customer()
    seen = []
    for _ in range(4):
        d = http("POST", "/api/owner/scan", headers=STAFF, json={"barcode_id": bc, "amount_paid": 5}).json()
        seen.append((d["stamps_on_card"], d["reward_unlocked"], d["rewards_pending"], d["visits"]))
    check("1, 2, 3 (unlocked), then the full card banked and 1 on the new one",
          seen == [(1, False, 0, 1), (2, False, 0, 2), (3, True, 0, 3), (1, False, 1, 4)], seen)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
