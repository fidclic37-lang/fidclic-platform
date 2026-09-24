"""
The loyalty card restarts by itself.

A paper card fills, the customer claims the free coffee, and the next purchase
starts a fresh card. This checks ours does the same: the meter never sticks at
10/10, nothing earned is lost, and a redemption keeps the stamps of the card
already under way.

    cd api && python3 tests/test_reward_cycle.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from auth import create_access_token

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    db.tenants.insert_one({"id": "t1", "name": "Café", "plan": "gold", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 3, "visits_per_stamp": 1,
                                  "reward_description": "Un café offert", "points_per_visit": 10})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-CYCLE01", "name": "Marie",
                             "visits": 0, "points": 0, "tier": "bronze",
                             "created_at": dt.datetime.now(dt.timezone.utc)})

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    def scan():
        return server.scan_visit(server.ScanRequest(barcode_id="FT-CYCLE01", amount_paid=5.0), TD())

    r1, r2, r3 = scan(), scan(), scan()
    check("card fills 1 → 2 → 3", [r["stamps_in_cycle"] for r in (r1, r2, r3)] == [1, 2, 3])
    check("full card is flagged as unlocked", r3["reward_unlocked"] is True and r3["rewards_pending"] == 0)

    r4 = scan()
    check("next visit restarts the card at 1 (no more stuck 3/3)", r4["stamps_in_cycle"] == 1)
    check("the completed card is banked, not lost", r4["rewards_pending"] == 1 and r4["cycle_restarted"] is True)
    check("lifetime visits keep counting", r4["visits"] == 4)

    r5, r6 = scan(), scan()
    check("second card fills normally", [r5["stamps_in_cycle"], r6["stamps_in_cycle"]] == [2, 3])
    r7 = scan()
    check("two cards banked after the second restart", r7["rewards_pending"] == 2 and r7["stamps_in_cycle"] == 1)

    # ---- redeeming a banked card keeps the stamps already earned ----------
    server.redeem_reward(server.RedeemRewardRequest(barcode_id="FT-CYCLE01", reward_name="Un café offert"), TD())
    cust = db.customers.find_one({"id": "c1"})
    check("redemption consumes one banked card", db.rewards_earned.count_documents({"status": "pending"}) == 1)
    check("redemption does NOT wipe the card in progress",
          cust["visits"] - cust["visits_at_last_redemption"] == 1)
    check("redemption is logged", db.rewards_redeemed.count_documents({"customer_id": "c1"}) == 1)

    # ---- redeeming with nothing banked moves one full card only ------------
    db.rewards_earned.delete_many({})
    db.customers.update_one({"id": "c1"}, {"$set": {"visits": 20, "visits_at_last_redemption": 14}})
    server.redeem_reward(server.RedeemRewardRequest(barcode_id="FT-CYCLE01", reward_name="Un café offert"), TD())
    cust = db.customers.find_one({"id": "c1"})
    check("one card consumed, the extra stamps stay", cust["visits_at_last_redemption"] == 17
          and cust["visits"] - cust["visits_at_last_redemption"] == 3)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
