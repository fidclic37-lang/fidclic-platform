"""
Historique: points AND tampons (user, 2026-10-15: on a tampons card every scan
showed « 0 » points). A visit records the tampons it gave, a reward what it
cost; the column opens on the shop's own programme; the CSV carries both.

Run: cd api && /usr/local/bin/python3 tests/test_history_stamps.py
"""
import contextlib
import datetime as dt
import io
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "test-secret-history-stamps")
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from features import activity_history as AH

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    now = dt.datetime.now(dt.timezone.utc)
    for tid, card in (("ts", {"programme": "stamps", "reward_threshold_stamps": 3, "visits_per_stamp": 1}),
                      ("tp", {"programme": "points_visit", "points_per_visit": 10, "reward_points": 20,
                              "reward_threshold_stamps": 10})):
        db.tenants.insert_one({"id": tid, "name": tid, "plan": "gold", "is_active": True})
        db.card_templates.insert_one({"tenant_id": tid, **card})
        db.customers.insert_one({"id": f"c-{tid}", "tenant_id": tid, "barcode_id": f"FT-{tid.upper()}000001", "name": "Léa",
                                 "visits": 0, "points": 0, "tier": "bronze", "created_at": now})

    def TD(tid):
        class T:
            email, role, tenant_id = "owner@x.fr", "business_owner", tid
        return T()

    def scan(tid):
        return server.scan_visit(server.ScanRequest(barcode_id=f"FT-{tid.upper()}000001", amount_paid=5.0), TD(tid))

    def feed(tid):
        with contextlib.redirect_stdout(io.StringIO()):
            return AH.activity(None, None, "all", None, None, 1, 50, None, TD(tid))

    print("1. A tampons card")
    for _ in range(3):
        scan("ts")
    server.redeem_reward(server.RedeemRewardRequest(barcode_id="FT-TS000001", reward_name="Un café offert"), TD("ts"))
    f = feed("ts")
    scans = [r for r in f["rows"] if r["action"] == "scan"]
    reward = next(r for r in f["rows"] if r["action"] == "reward")
    check(f"the column opens on tampons ({f['unit']})", f["unit"] == "stamps" and AH.filters(TD("ts"))["unit"] == "stamps")
    check(f"each scan: +1 tampon, 0 point ({[(r['stamps'], r['points']) for r in scans]})",
          len(scans) == 3 and all(r["stamps"] == 1 and r["points"] == 0 for r in scans))
    check(f"the reward: -3 tampons, no points ({reward['stamps']}, {reward['points']})", reward["stamps"] == -3 and reward["points"] is None)
    check("signup: 0 tampon", all(r["stamps"] == 0 for r in f["rows"] if r["action"] == "signup"))

    print("\n2. A points card")
    for _ in range(2):
        scan("tp")
    server.redeem_reward(server.RedeemRewardRequest(barcode_id="FT-TP000001", reward_name="Un café offert"), TD("tp"))
    f = feed("tp")
    scans = [r for r in f["rows"] if r["action"] == "scan"]
    reward = next(r for r in f["rows"] if r["action"] == "reward")
    check(f"the column opens on points ({f['unit']})", f["unit"] == "points")
    check(f"each scan: +10 points ({[r['points'] for r in scans]})", [r["points"] for r in scans] == [10, 10])
    check(f"the reward: -20 points, as the balance paid ({reward['points']})", reward["points"] == -20 and reward["stamps"] is None)
    check("…and the balance really went down", db.customers.find_one({"id": "c-tp"})["points"] == 0)

    print("\n3. Rows from before (no tampons recorded): from the card's rule")
    db.visits.insert_one({"id": "old", "tenant_id": "ts", "customer_id": "c-ts", "points_awarded": 0,
                          "amount_paid": 4, "visit_time": now - dt.timedelta(days=2)})
    db.rewards_redeemed.insert_one({"id": "oldr", "tenant_id": "ts", "customer_id": "c-ts", "reward_name": "Café",
                                    "redeemed_at": now - dt.timedelta(days=2)})
    rows = {r["id"]: r for r in feed("ts")["rows"]}
    old_scan = next(r for r in rows.values() if r["action"] == "scan" and r["at"] < (now - dt.timedelta(days=1)).isoformat())
    old_rew = next(r for r in rows.values() if r["action"] == "reward" and r["at"] < (now - dt.timedelta(days=1)).isoformat())
    check(f"an old scan: +1 tampon ({old_scan['stamps']})", old_scan["stamps"] == 1)
    check(f"an old reward: one full card, -3 ({old_rew['stamps']})", old_rew["stamps"] == -3)

    print("\n4. The CSV carries both")
    with contextlib.redirect_stdout(io.StringIO()):
        csv = AH.export_csv(None, None, "all", None, None, None, TD("ts")).body.decode("utf-8-sig")
    head = csv.splitlines()[0].split(";")
    check(f"Points and Tampons columns ({head})", "Points" in head and "Tampons" in head)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
