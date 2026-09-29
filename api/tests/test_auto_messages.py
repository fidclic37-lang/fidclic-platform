"""
Messages automatiques — welcome at sign-up, Google review after a scan,
"récompense proche" two visits from the reward, and nothing sent twice.

Run: cd api && /usr/local/bin/python3 tests/test_auto_messages.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import auto_messages as AM

    db = server.db
    AM.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class OWNER:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    delivered = []
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: (
        delivered.append({"cid": cust["id"], "kind": kind, "title": title, "body": body, "url": url}) or {"sent": True})

    def kinds(cid, kind):
        return [d for d in delivered if d["cid"] == cid and d["kind"] == kind]

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Petit Café",
                           "google_review_url": "https://g.page/r/petit-cafe/review", "google_reviews_enabled": True})

    # ---- Bienvenue -----------------------------------------------------------------
    print("\nBienvenue, at sign-up")
    db.earn_rules.insert_one({"tenant_id": "t1", "enabled": True, "welcome_bonus_points": 50,
                              "welcome_bonus_message": "Bienvenue {first_name} ! {points} points offerts."})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Marie Dupont", "barcode_id": "FT-C1",
                             "points": 0, "visits": 0})
    w = AM.welcome("t1", db.customers.find_one({"id": "c1"}))
    check("the shop's message, personalised", w["message"] == "Bienvenue Marie ! 50 points offerts.")
    check("its points credited", db.customers.find_one({"id": "c1"})["points"] == 50)
    check("sent and kept in the card's feed", kinds("c1", "welcome")
          and db.push_notifications.find_one({"customer_id": "c1", "type": "welcome"}))
    AM.welcome("t1", db.customers.find_one({"id": "c1"}))
    check("points never credited twice", db.customers.find_one({"id": "c1"})["points"] == 50)
    db.earn_rules.update_one({"tenant_id": "t1"}, {"$set": {"enabled": False}})
    check("switched off on the card page: nothing", AM.welcome("t1", {"id": "cx", "name": "X"}) is None)
    db.earn_rules.update_one({"tenant_id": "t1"}, {"$set": {"enabled": True}})

    # ---- Avis Google -------------------------------------------------------------------
    print("\nAvis Google, after a scan, at the shop's pace")
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now)
    first = kinds("c1", "google_review")
    check("sent after the first scan, the link leading to the counted redirect",
          len(first) == 1 and first[0]["url"].endswith("/api/avis/FT-C1"))
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now + dt.timedelta(days=3))
    check("default: not again inside 30 days", len(kinds("c1", "google_review")) == 1)
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now + dt.timedelta(days=31))
    check("… and again after", len(kinds("c1", "google_review")) == 2)
    AM.put_auto_messages(AM.AutoMessagesIn(google_review=AM.GoogleReviewIn(frequency="every_scan")), token_data=OWNER())
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now + dt.timedelta(days=32))
    check("'à chaque scan': every scan", len(kinds("c1", "google_review")) == 3)
    AM.put_auto_messages(AM.AutoMessagesIn(google_review=AM.GoogleReviewIn(frequency="once")), token_data=OWNER())
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now + dt.timedelta(days=90))
    check("'une seule fois': never again", len(kinds("c1", "google_review")) == 3)
    AM.put_auto_messages(AM.AutoMessagesIn(google_review=AM.GoogleReviewIn(frequency="every_scan")), token_data=OWNER())
    r = AM.review_link("FT-C1")
    check("the link counts the click and leads to Google",
          r.headers["location"] == "https://g.page/r/petit-cafe/review"
          and db.google_review_clicks.count_documents({"customer_id": "c1"}) == 1)
    AM.google_review("t1", db.customers.find_one({"id": "c1"}), now + dt.timedelta(days=91))
    check("once followed, never asked again (the shop's default)", len(kinds("c1", "google_review")) == 3)
    try:
        AM.put_auto_messages(AM.AutoMessagesIn(google_review=AM.GoogleReviewIn(frequency="hourly")), token_data=OWNER())
        bad = True
    except HTTPException:
        bad = False
    check("an unknown frequency is refused", bad is False)
    db.tenants.update_one({"id": "t1"}, {"$set": {"google_reviews_enabled": False}})
    db.customers.insert_one({"id": "c9", "tenant_id": "t1", "name": "Léo", "barcode_id": "FT-C9", "visits": 1})
    check("no Google link set: nothing", AM.google_review("t1", db.customers.find_one({"id": "c9"})) is False)
    db.tenants.update_one({"id": "t1"}, {"$set": {"google_reviews_enabled": True}})

    # ---- Récompense proche — stamps -------------------------------------------------------
    print("\nRécompense proche, two visits from the reward")
    tpl = {"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10, "visits_per_stamp": 1,
           "reward_description": "Un café offert"}
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "name": "Paul", "barcode_id": "FT-C2",
                             "visits": 7, "visits_at_last_redemption": 0})
    check("three visits away: not yet", AM.near_reward("t1", db.customers.find_one({"id": "c2"}), tpl, None) is False)
    db.customers.update_one({"id": "c2"}, {"$set": {"visits": 8}})
    check("two visits away: sent", AM.near_reward("t1", db.customers.find_one({"id": "c2"}), tpl, None) is True)
    check("… naming the reward", "Un café offert" in kinds("c2", "near_reward")[0]["body"]
          and "2 visites" in kinds("c2", "near_reward")[0]["body"])
    check("once per card cycle", AM.near_reward("t1", db.customers.find_one({"id": "c2"}), tpl, None) is False)
    db.customers.update_one({"id": "c2"}, {"$set": {"visits": 18, "visits_at_last_redemption": 10}})
    redeemed_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)   # after the first nudge
    check("the next card, after a reward, starts again",
          AM.near_reward("t1", db.customers.find_one({"id": "c2"}), tpl, redeemed_at) is True)
    AM.put_auto_messages(AM.AutoMessagesIn(near_reward=AM.NearRewardIn(visits_left=3)), token_data=OWNER())
    db.customers.insert_one({"id": "c3", "tenant_id": "t1", "name": "Zoé", "barcode_id": "FT-C3", "visits": 7})
    check("the shop may choose another distance", AM.near_reward("t1", db.customers.find_one({"id": "c3"}), tpl, None) is True)
    AM.put_auto_messages(AM.AutoMessagesIn(near_reward=AM.NearRewardIn(visits_left=2)), token_data=OWNER())

    # ---- Récompense proche — points ---------------------------------------------------------
    print("\n… on a points card, at the client's own pace")
    ptpl = {"tenant_id": "t1", "programme": "points_euro", "points_mode": "per_euro", "reward_points": 100}
    db.customers.insert_one({"id": "c4", "tenant_id": "t1", "name": "Inès", "barcode_id": "FT-C4", "points": 70, "visits": 3})
    for i, p in enumerate((15, 15, 15)):
        db.visits.insert_one({"id": f"v4{i}", "tenant_id": "t1", "customer_id": "c4", "points_awarded": p,
                              "visit_time": now - dt.timedelta(days=i)})
    check("30 points missing at 15 a visit = two visits", AM.visits_to_reward("t1", db.customers.find_one({"id": "c4"}), ptpl) == 2)
    check("sent", AM.near_reward("t1", db.customers.find_one({"id": "c4"}), ptpl, None) is True)
    check("cashback has no such step", AM.visits_to_reward("t1", {"id": "c4", "points": 1}, {"programme": "cashback"}) is None)

    # ---- settings -------------------------------------------------------------------------
    print("\nSettings")
    v = AM.get_auto_messages(token_data=OWNER())
    check("the page reads all four: welcome, birthday, Google, near reward",
          {"welcome", "birthday", "google_review", "near_reward"} <= set(v) and v["google_link"]["on"] is True)
    try:
        AM.put_auto_messages(AM.AutoMessagesIn(near_reward=AM.NearRewardIn(title="  ")), token_data=OWNER())
        empty = True
    except HTTPException:
        empty = False
    check("an empty title is refused", empty is False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
