"""
Parrainage rewards, the owner's rules only (user, 2026-10-20, QA R7 F41):
- nothing by default — 0 for both sides until the owner saves an amount;
- what the owner saves (points or tampons, each side) is what is kept,
  shown again and given;
- nothing at signup, for either side: rewards are given at the filleul's
  visit only, and « Points offerts » counts only what was really given.

Run: cd api && /usr/local/bin/python3 tests/test_referral_saved_rules.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401
    from features import referrals as R
    from features import automations as AU

    db = server.db
    R.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café"})

    print("\nNothing by default")
    cfg = R.get_config(token_data=TD())
    check("a new programme gives 0 points to each side", cfg["referrer_reward_points"] == 0 and cfg["referee_reward_points"] == 0)
    check("…and 0 tampons", cfg["referrer_reward_stamps"] == 0 and cfg["referee_reward_stamps"] == 0)
    check("the editor reads 0 too", AU.referral_page("t1")["referrer_reward_points"] == 0
          and AU.referral_page("t1")["referee_reward_points"] == 0)

    print("\nWhat the owner saves is what is kept")
    R.update_config(R.ReferralConfig(enabled=True, referrer_reward_kind="stamps", referrer_reward_stamps=3,
                                     referee_reward_kind="points", referee_reward_points=40), TD())
    page = R.overview(token_data=TD())["config"]
    check(f"the settings page re-opens on the parrain's 3 tampons ({page.get('referrer_reward_kind')}, {page.get('referrer_reward_stamps')})",
          page.get("referrer_reward_kind") == "stamps" and page.get("referrer_reward_stamps") == 3)
    check("…and the filleul's 40 points", page.get("referee_reward_kind") == "points" and page.get("referee_reward_points") == 40)
    R.update_config(R.ReferralConfig(**{k: v for k, v in page.items() if k in R.ReferralConfig.model_fields}, enabled=True), TD())
    again = R.overview(token_data=TD())["config"]
    check("saving the page back unchanged keeps every value",
          all(again.get(k) == page.get(k) for k in ("referrer_reward_kind", "referrer_reward_stamps",
                                                     "referee_reward_kind", "referee_reward_points")))

    print("\nNothing at signup, everything at the filleul's visit")
    db.customers.insert_one({"id": "p1", "tenant_id": "t1", "name": "Parrain", "barcode_id": "FT-P1",
                             "visits": 3, "points": 0, "stamps_bonus": 0})
    db.customers.insert_one({"id": "f1", "tenant_id": "t1", "name": "Filleul", "barcode_id": "FT-F1",
                             "visits": 0, "points": 0})
    row = R.record("t1", "FT-P1", db.customers.find_one({"id": "f1"}))
    check("the parrainage is recorded", bool(row))
    p1, f1 = db.customers.find_one({"id": "p1"}), db.customers.find_one({"id": "f1"})
    check("signup: the parrain got nothing", int(p1.get("points") or 0) == 0)
    check("signup: the filleul got nothing", int(f1.get("points") or 0) == 0)
    stored = db.referral_redemptions.find_one({"referee_customer_id": "f1"})
    check("signup: nothing written as given", stored["referrer_points"] == 0 and stored["referee_points"] == 0)
    check("signup: « Points offerts » stays 0",
          next(c for c in R.overview(token_data=TD())["cards"] if c["key"] == "points")["value"] == 0)
    check("no visit, nothing to settle", R.settle("t1", "f1") is None)

    db.customers.update_one({"id": "f1"}, {"$set": {"visits": 1}})
    got = R.settle("t1", "f1")
    check(f"the filleul's visit pays both ({got and got.get('referrer_reward')} / {got and got.get('referee_reward')})",
          got and got["referrer_reward"] == "3 tampons" and got["referee_reward"] == "40 points")
    check("the filleul now has his 40 points", int(db.customers.find_one({"id": "f1"}).get("points") or 0) == 40)
    check("the parrain got tampons, no points", int(db.customers.find_one({"id": "p1"}).get("points") or 0) == 0)
    card = next(c for c in R.overview(token_data=TD())["cards"] if c["key"] == "points")
    check(f"the card speaks the parrain's tampons, the filleul's 40 points beneath ({card})",
          card["label"] == "Tampons offerts" and card["value"] == 3 and card.get("also") == "+ 40 points")

    print("\nA 0 saved stays 0")
    R.update_config(R.ReferralConfig(enabled=True, referrer_reward_points=0, referee_reward_points=0), TD())
    page = R.overview(token_data=TD())["config"]
    check("0 / 0 saved → the page shows 0 / 0, not 50 / 25",
          page["referrer_reward_points"] == 0 and page["referee_reward_points"] == 0)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
