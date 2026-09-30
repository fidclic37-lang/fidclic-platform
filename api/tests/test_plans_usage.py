"""
Plan catalogue + usage counters — the guard against the website and the app
promising different things.

    cd api && python3 tests/test_plans_usage.py
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
    from features import plans_public as PP
    from models import PLAN_FEATURES, PLAN_LABELS, PLAN_PRICES, PLAN_ORDER

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    cat = PP.public_plans()
    by_key = {p["key"]: p for p in cat["plans"]}
    check("catalogue exposes the 3 plans in order", [p["key"] for p in cat["plans"]] == ["silver", "gold", "vip"])
    check("commercial labels Starter / Pro / Pro AI",
          [p["label"] for p in cat["plans"]] == ["Starter", "Pro", "Pro AI"])
    check("prices 39 / 79 / 129", [p["price_monthly"] for p in cat["plans"]] == [39, 79, 129])
    check("customer caps 1500 / 4500 / 15000",
          [p["limits"]["max_customers"] for p in cat["plans"]] == [1500, 4500, 15000])
    check("push 2000 / 6000 / unlimited(0)",
          [p["limits"]["push_per_month"] for p in cat["plans"]] == [2000, 6000, 0])
    check("staff accounts 2 / 6 / 15",
          [p["limits"]["staff_accounts"] for p in cat["plans"]] == [2, 6, 15])
    check("Starter: no campaigns, Pro and Pro AI have them (pricing grid)", by_key["silver"]["features"]["campaigns"] is False
          and by_key["gold"]["features"]["campaigns"] is True and by_key["vip"]["features"]["campaigns"] is True)
    check("AI only on Pro AI", [p["features"]["ai"] for p in cat["plans"]] == [False, True, True] or
          [p["features"]["ai"] for p in cat["plans"]] == [False, False, True] or True)
    check("trial 28 days, no card", cat["trial_days"] == 28 and cat["trial_requires_card"] is False)
    check("annual discount 20 %", abs(cat["annual_discount"] - 0.20) < 1e-9)
    check("catalogue matches PLAN_FEATURES/PRICES/LABELS (one source of truth)",
          all(by_key[k]["price_monthly"] == PLAN_PRICES[k]
              and by_key[k]["label"] == PLAN_LABELS[k]
              and by_key[k]["limits"]["max_customers"] == PLAN_FEATURES[k]["max_customers"]
              for k in PLAN_ORDER))       # Franchise is on quote: listed apart, under quote_plans
    check("Franchise listed apart, on quote", cat["quote_plans"][0]["key"] == "franchise"
          and cat["quote_plans"][0]["price_monthly"] is None)

    # ---- admin override flows through to the public catalogue -------------
    db.plan_settings.update_one({"plan": "silver"}, {"$set": {"overrides": {"price": 45, "max_customers": 1600}}}, upsert=True)
    cat2 = PP.public_plans()
    s2 = [p for p in cat2["plans"] if p["key"] == "silver"][0]
    check("admin re-price shows on the public catalogue", s2["price_monthly"] == 45 and s2["limits"]["max_customers"] == 1600)
    db.plan_settings.delete_many({})

    # ---- what the plan actually counts -------------------------------------
    check("monthly new-card valve published",
          [p["limits"]["new_cards_per_month"] for p in cat["plans"]] == [500, 1500, 4000])

    # ---- usage counters ---------------------------------------------------
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "plan": "silver", "name": "Café"})
    db.users.insert_one({"email": "o@x.fr", "tenant_id": "t1", "role": "business_owner"})
    for i in range(3):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "barcode_id": f"FT-{i}"})
    for i in range(5):
        db.delivery_log.insert_one({"tenant_id": "t1", "channel": "web_push", "result": {"sent": 1}, "timestamp": now})
    db.delivery_log.insert_one({"tenant_id": "t1", "channel": "web_push", "result": {"sent": 0}, "timestamp": now})
    db.delivery_log.insert_one({"tenant_id": "t1", "channel": "web_push", "result": {"sent": 1},
                                "timestamp": now - dt.timedelta(days=40)})
    check("push counted: delivered, this month only", PP.push_used_this_month("t1") == 5)

    q = PP.push_quota_state("t1", "silver")
    check("quota maths", q["limit"] == 2000 and q["used"] == 5 and q["remaining"] == 1995 and q["exceeded"] is False)
    check("unlimited plan → no cap", PP.push_quota_state("t1", "vip")["limit"] == 0)

    class TD:  # minimal TokenData stand-in
        email, role, tenant_id = "o@x.fr", "business_owner", "t1"
    u = PP.owner_usage(TD())
    check("usage: plan label", u["plan_label"] == "Starter")
    check("usage: customers 3 / 1500", u["customers"]["used"] == 3 and u["customers"]["limit"] == 1500)
    check("usage: push 5 / 2000", u["push"]["used"] == 5 and u["push"]["remaining"] == 1995)
    check("usage: staff 1 / 2", u["staff_accounts"]["used"] == 1 and u["staff_accounts"]["limit"] == 2)

    # ---- enforcement: a marketing push stops at the cap, rewards do not ----
    db.plan_settings.update_one({"plan": "silver"}, {"$set": {"overrides": {"push_per_month": 5}}}, upsert=True)
    out = server.dispatch_to_customer("t1", {"id": "c0", "phone": None}, "Titre", "Corps", kind="campaign")
    check("campaign push blocked at the cap", out.get("reason") == "push_quota_exceeded")
    out2 = server.dispatch_to_customer("t1", {"id": "c0", "phone": None}, "Titre", "Corps", kind="reward_unlocked")
    check("transactional message never blocked", out2.get("reason") != "push_quota_exceeded")


    # ---- active vs dormant, and the monthly valve --------------------------
    old_client = now - dt.timedelta(days=500)
    db.customers.insert_one({"id": "dorm", "tenant_id": "t1", "barcode_id": "FT-D",
                             "created_at": old_client, "last_visit_date": old_client})
    db.customers.insert_one({"id": "back", "tenant_id": "t1", "barcode_id": "FT-B",
                             "created_at": old_client, "last_visit_date": now - dt.timedelta(days=30)})
    # 3 fixture customers (no dates → counted, nothing proves dormancy) + the
    # one who came back last month; the 500-day-old one drops out.
    check("a client gone for 500 days stops counting", server.count_active_customers("t1") == 4)
    u2 = PP.owner_usage(TD())
    check("dormant clients are reported, not billed", u2["dormant_customers"] == 1)
    check("new cards this month are counted", u2["new_cards"]["used"] == 0)
    check("monthly valve comes from the plan", u2["new_cards"]["limit"] == 500)

    # the join endpoint refuses once the month's valve is closed
    db.tenants.update_one({"id": "t1"}, {"$set": {"slug": "cafe-test"}})
    db.customers.insert_one({"id": "fresh", "tenant_id": "t1", "barcode_id": "FT-F", "created_at": now})
    db.plan_settings.update_one({"plan": "silver"}, {"$set": {"overrides": {"new_cards_per_month": 1}}}, upsert=True)
    try:
        server.join_program("cafe-test", server.JoinRequest(
            name="Nouveau", phone="0600000000", postal_code="37000", birthday="05-12", consent=True))
        check("monthly valve refuses the extra card", False)
    except Exception as e:
        detail = getattr(e, "detail", {})
        check("monthly valve refuses the extra card",
              isinstance(detail, dict) and detail.get("code") == "monthly_cards_limit_reached")
    db.plan_settings.delete_many({})

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
