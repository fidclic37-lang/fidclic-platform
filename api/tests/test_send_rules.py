"""
Limites d'envoi — each business's own limits, what is never held, and the
held messages going out the next day in order.

Run: cd api && /usr/local/bin/python3 tests/test_send_rules.py
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
    from features import send_rules as SR

    db = server.db
    SR.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class OWNER:
        email, role, tenant_id = "o@x.fr", "business_owner", "t1"

    # What actually leaves: the web-push fan-out, observed.
    out = []
    import features.push_subscriptions as PS
    PS.fan_out_to_customer = lambda tid, cid, title, body, url=None: (out.append((cid, title)) or {"sent": 1})

    db.tenants.insert_one({"id": "t1", "name": "Café", "plan": "gold"})
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "t1", "name": f"Client {i}"} for i in range(1, 5)])
    c1 = db.customers.find_one({"id": "c1"})

    print("\nPer client, the business's own limit")
    SR.put_rules(SR.RulesIn(per_client_day=1, per_client_week=3), token_data=OWNER())
    r1 = server.dispatch_to_customer("t1", c1, "Campagne A", "…", kind="campaign")
    r2 = server.dispatch_to_customer("t1", c1, "Campagne B", "…", kind="campaign")
    check("the first goes", r1.get("sent") is True)
    check("the second waits for tomorrow, not lost",
          r2.get("deferred") is True and db.deferred_messages.count_documents({"status": "waiting"}) == 1)
    check("only one reached the client today", [t for c, t in out if c == "c1"] == ["Campagne A"])
    for kind in ("welcome", "reward_unlocked", "google_review"):
        server.dispatch_to_customer("t1", c1, kind, "…", kind=kind)
    check("what follows the client's own action is never held",
          {"welcome", "reward_unlocked", "google_review"} <= {t for c, t in out if c == "c1"})
    check("… nor counted", db.send_counter.count_documents({"customer_id": "c1"}) == 1)
    rn = server.dispatch_to_customer("t1", c1, "near_reward", "…", kind="near_reward")
    check("« Récompense proche » counts (user, 2026-10-09): over the limit it waits for tomorrow",
          rn.get("deferred") is True and "near_reward" not in {t for c, t in out if c == "c1"})
    db.deferred_messages.delete_many({"kind": "near_reward"})

    print("\nThe next day, most important first")
    server.dispatch_to_customer("t1", c1, "IA", "…", kind="copilot")
    server.dispatch_to_customer("t1", c1, "Anniversaire", "…", kind="birthday")
    out.clear()
    tomorrow = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1, hours=1)
    db.send_counter.delete_many({})               # a new day: yesterday's count is behind us
    res = SR.drain(tomorrow)
    check("the birthday goes first, the others wait one more day",
          [t for c, t in out] == ["Anniversaire"] and res["waiting"] == 2)

    print("\nA week later, stale offers are dropped")
    res = SR.drain(tomorrow + dt.timedelta(days=8))
    check("nothing older than 7 days is sent", res["dropped"] == 2 and res["sent"] == 0)

    print("\nWhole shop")
    db.send_counter.delete_many({}); db.deferred_messages.delete_many({})
    SR.put_rules(SR.RulesIn(per_client_day=0, per_client_week=0, shop_day=2, shop_week=0), token_data=OWNER())
    res = [server.dispatch_to_customer("t1", db.customers.find_one({"id": f"c{i}"}), "Promo", "…", kind="campaign")
           for i in range(1, 5)]
    check("two go, two wait", sum(1 for r in res if r.get("sent")) == 2 and sum(1 for r in res if r.get("deferred")) == 2)
    SR.put_rules(SR.RulesIn(shop_day=0), token_data=OWNER())
    check("0 = no limit", SR.over_limit("t1", "c1") is None)

    print("\nSettings")
    try:
        SR.put_rules(SR.RulesIn(per_client_day=5, per_client_week=2), token_data=OWNER()); bad = True
    except HTTPException:
        bad = False
    check("a week below the day is refused", bad is False)
    v = SR.overview(token_data=OWNER())
    check("the page reads usage, the plan, the rules and the automatic messages",
          {"usage", "plan", "rules", "automatic", "preview", "consent"} <= set(v)
          # one line per Automatisations scenario (redesign 2026-10-11: eight)
          and [a["key"] for a in v["automatic"]] == ["birthday", "tier_up", "welcome", "near_reward", "referral", "geo",
                                                     "google_review", "inactive"])
    check("usage counts what really went out this month", v["usage"]["sent"] >= 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
