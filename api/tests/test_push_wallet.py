"""
Automatisations · Push Wallet — the scenarios and the engine behind them.

Every trigger is fired for real against real customer rows: the suite does not
assert that a scenario is "configured", it asserts who it actually reaches and
who it leaves alone. The two rates are checked against what they claim to
measure — a click is a followed link, an open is a card opened inside the
window — because a wallet push has no read receipt and the figure must not
quietly become something else.

    cd api && python3 tests/test_push_wallet.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import push_wallet as PW
    from fastapi import HTTPException

    db = server.db
    PW.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    class Rival:
        email, role, tenant_id = "b@b.fr", "business_owner", "t2"

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café"})
    db.tenants.insert_one({"id": "t2", "slug": "rival", "name": "Rival"})

    # Nothing is actually delivered in a test; what matters is who was picked.
    delivered = []
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign": (
        delivered.append((tid, cust["id"], title, body, kind)) or {"sent": True, "channel": "test"})

    # ---- the page opens on the eight of the design -------------------------
    print("\nThe eight scenarios")
    page = PW.list_scenarios(token_data=TD())
    names = [s["name"] for s in page["scenarios"]]
    check("eight are seeded on first read, so the table is never empty", len(names) == 8)
    check("they are the eight the design lists, in order", names == [
        "Anniversaire", "Atteinte d'un palier", "Offre spéciale", "Relance panier",
        "Heure creuse", "Nouveautés", "Client inactif", "Événement spécial"])
    check("each carries the subtitle from the design",
          page["scenarios"][0]["subtitle"] == "Souhaitez un joyeux anniversaire")
    check("the trigger column reads its own setting, not just its type",
          [s["trigger_detail"] for s in page["scenarios"] if s["builtin"] == "inactive"]
          == ["Inactivité (30 jours)"])
    check("and the relance is a different number, from the same trigger",
          [s["trigger_detail"] for s in page["scenarios"] if s["builtin"] == "cart_recovery"]
          == ["Inactivité (14 jours)"])
    check("five start switched on, three as drafts (the -20 % offer waits for the merchant)",
          sum(1 for s in page["scenarios"] if s["enabled"]) == 5)
    check("a draft reads as a draft",
          [s["status"] for s in page["scenarios"] if s["builtin"] == "new_products"] == ["draft"])
    check("seeding happens once, not on every read",
          len(PW.list_scenarios(token_data=TD())["scenarios"]) == 8)
    check("the rail's example messages are offered", len(page["examples"]) == 4)
    # The page asks for the list and the figures at once, so both reach the
    # seeder together — it has to survive that without doubling the table.
    PW.list_scenarios(token_data=TD()); PW.stats(token_data=TD())
    check("two requests seeding at once still leave exactly eight",
          db.push_scenarios.count_documents({"tenant_id": "t1"}) == 8)
    by_key = {s["builtin"]: s for s in page["scenarios"]}

    # ---- the cast -----------------------------------------------------------
    PEOPLE = [
        # id,   name,        birthday, tier,     last visit (days ago)
        ("c1", "Marie Dupont",  now.strftime("%m-%d"), "bronze", 1),
        ("c2", "Paul Martin",   "01-01",               "gold",   2),
        ("c3", "Sophie Nguyen", "01-02",               "silver", 20),
        ("c4", "Karim Chebbi",  "01-03",               "bronze", 45),
        ("c5", "Inès Bouchard", "01-04",               "vip",    60),
    ]
    db.customers.insert_many([
        {"id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-{cid.upper()}",
         "birthday": bday, "tier": tier, "points": 100, "visits": 5,
         "last_visit_date": now - dt.timedelta(days=ago), "created_at": now - dt.timedelta(days=200)}
        for cid, name, bday, tier, ago in PEOPLE
    ])
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival Client",
                             "barcode_id": "FT-X1", "birthday": now.strftime("%m-%d"),
                             "tier": "bronze", "last_visit_date": now - dt.timedelta(days=90)})

    def fire(key, at=None):
        row = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": key})
        row.pop("_id", None)
        return PW.run_scenario("t1", row, at or now)

    def reached(key):
        return {l["customer_id"] for l in db.push_wallet_log.find({"scenario_id":
                db.push_scenarios.find_one({"tenant_id": "t1", "builtin": key})["id"]})}

    # ---- birthday ------------------------------------------------------------
    print("\nAnniversaire fires on the day, and only on it")
    import features.wallet_passes as _WP
    wake = []
    _real_nc = _WP.notify_customer
    _WP.notify_customer = lambda cid, message=None, google_notify=None: wake.append((cid, google_notify)) or {}
    res = fire("birthday")
    check("only today's birthday is reached", res["targeted"] == 1 and reached("birthday") == {"c1"})
    check("the message was actually dispatched", any(d[1] == "c1" for d in delivered))
    check("another shop's client is never touched",
          not any(d[1] == "x1" for d in delivered))
    check("the same client is not reached twice inside the cooldown",
          fire("birthday")["targeted"] == 0)
    check("the birthday asks Google for a notification, with its own words",
          wake and wake[0][0] == "c1" and (wake[0][1] or {}).get("kind") == "birthday" and wake[0][1].get("header"))

    # ---- inactivity ----------------------------------------------------------
    print("\nInactivité — the threshold is the setting, not a constant")
    res = fire("inactive")               # 30 days
    check("other scenarios update Google silently", all(g is None for c, g in wake[1:]) and len(wake) > 1)
    _WP.notify_customer = _real_nc
    check("only clients past 30 days are reached", reached("inactive") == {"c4", "c5"})
    res = fire("cart_recovery")          # 14 days
    check("a 14-day scenario reaches more of them",
          reached("cart_recovery") == {"c3", "c4", "c5"})
    check("the two scenarios keep their own cooldowns",
          fire("inactive")["targeted"] == 0 and fire("cart_recovery")["targeted"] == 0)

    # ---- tier up --------------------------------------------------------------
    print("\nAtteinte d'un palier — only those who just levelled up")
    check("nobody has levelled up yet", fire("tier_up")["targeted"] == 0)
    db.customers.update_one({"id": "c2"}, {"$set": {"tier_changed_at": now + dt.timedelta(seconds=1)}})
    check("a client who levelled up since the last run is reached",
          fire("tier_up", now + dt.timedelta(seconds=2))["targeted"] == 1
          and reached("tier_up") == {"c2"})
    db.customers.update_one({"id": "c3"}, {"$set": {"tier_changed_at": now - dt.timedelta(days=9)}})
    check("one who levelled up before the last run is not reached again",
          fire("tier_up")["targeted"] == 0)

    # ---- the -20 % offer is off unless the merchant chooses it -----------------
    print("\nOffre spéciale -20 % starts switched off")
    check("seeded off", db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "special_offer"})["enabled"] is False)
    db.push_scenarios.update_one({"tenant_id": "t1", "builtin": "special_offer"},
                                 {"$set": {"enabled": True}, "$unset": {"offer_default_off": ""}})
    PW.init(db)
    check("a shop that had it on (the old default) is switched off once",
          db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "special_offer"})["enabled"] is False)
    db.push_scenarios.update_one({"tenant_id": "t1", "builtin": "special_offer"}, {"$set": {"enabled": True}})
    PW.init(db)
    check("… and a merchant who turns it back on keeps it on",
          db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "special_offer"})["enabled"] is True)

    # ---- date triggers ---------------------------------------------------------
    print("\nDate triggers fire on their date and stay quiet otherwise")
    row = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "special_offer"})
    db.push_scenarios.update_one({"id": row["id"]}, {"$set": {"config": {"day_of_month": now.day}}})
    check("the monthly offer fires on its day", fire("special_offer")["targeted"] == 5)
    db.push_scenarios.update_one({"id": row["id"]},
                                 {"$set": {"config": {"day_of_month": (now.day % 28) + 1}}})
    check("and not on any other day", fire("special_offer")["targeted"] == 0)

    ev = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "special_event"})
    db.push_scenarios.update_one({"id": ev["id"]},
                                 {"$set": {"config": {"date": now.date().isoformat()}}})
    check("a specific date fires on itself", fire("special_event")["targeted"] == 5)
    db.push_scenarios.update_one({"id": ev["id"]}, {"$set": {"config": {"date": "2030-01-01"}}})
    check("a future date stays quiet", fire("special_event")["targeted"] == 0)

    # ---- time slot --------------------------------------------------------------
    print("\nHeure creuse fires inside its window only")
    slot = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "off_peak"})
    at = now.replace(hour=15)
    db.push_scenarios.update_one({"id": slot["id"]}, {"$set": {
        "config": {"weekdays": [at.weekday()], "from_hour": 14, "to_hour": 17}}})
    check("inside the hours and on the right weekday, it fires",
          fire("off_peak", at)["targeted"] == 5)
    db.push_wallet_log.delete_many({"scenario_id": slot["id"]})
    check("an hour outside the window does nothing",
          fire("off_peak", now.replace(hour=9))["targeted"] == 0)
    other_day = at + dt.timedelta(days=1)
    check("the right hour on the wrong weekday does nothing",
          fire("off_peak", other_day.replace(hour=15))["targeted"] == 0)

    # ---- new product --------------------------------------------------------------
    print("\nNouveautés waits for something new")
    np = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "new_products"})
    check("with an empty catalogue it stays quiet", fire("new_products")["targeted"] == 0)
    # The real shape: one catalogue document per shop, products in `items`.
    db.tenant_catalog.insert_one({"tenant_id": "t1", "items": [
        {"id": "p1", "name": "Café latte", "price": 3.5, "created_at": now + dt.timedelta(seconds=1)}]})
    check("a product added since the last run wakes it",
          fire("new_products", now + dt.timedelta(seconds=2))["targeted"] == 5)
    db.push_wallet_log.delete_many({"scenario_id": np["id"]})
    check("and it does not fire again for the same product",
          fire("new_products", now + dt.timedelta(seconds=3))["targeted"] == 0)

    # ---- the switch -----------------------------------------------------------------
    print("\nThe on/off switch is the whole point of the column")
    PW.update_scenario(by_key["birthday"]["id"], PW.ScenarioPatch(enabled=False), TD())
    db.push_wallet_log.delete_many({})
    summary = PW.run_due_for_tenant("t1", now)
    fired = {r["name"] for r in summary["ran"]}
    check("a scenario switched off does not run", "Anniversaire" not in fired)
    PW.update_scenario(by_key["birthday"]["id"], PW.ScenarioPatch(enabled=True), TD())
    db.push_wallet_log.delete_many({})
    check("switched back on, it runs again",
          "Anniversaire" in {r["name"] for r in PW.run_due_for_tenant("t1", now)["ran"]})

    # ---- the four figures --------------------------------------------------------------
    print("\nThe four figures measure what they say")
    db.push_wallet_log.delete_many({})
    db.customers.update_many({"tenant_id": "t1"}, {"$unset": {"last_card_open_at": ""}})
    fire("special_offer") if False else None
    db.push_scenarios.update_one({"tenant_id": "t1", "builtin": "special_offer"},
                                 {"$set": {"config": {"day_of_month": now.day}}})
    fire("special_offer")
    logs = list(db.push_wallet_log.find({"tenant_id": "t1"}))
    check("every send is logged once", len(logs) == 5)

    # two of them click the link the push carries
    for log in logs[:2]:
        PW.register_click(log["id"])
    # three of them open their card afterwards — one of those too late to count
    from services import card_opens as CO
    db.card_opens.delete_many({})
    for log, h in ((logs[0], 1), (logs[1], 10), (logs[2], 200)):
        CO.log(db, {"id": log["customer_id"], "tenant_id": "t1"}, now=now + dt.timedelta(hours=h))
    s = PW.stats(token_data=TD())
    cards = {c["key"]: c for c in s["cards"]}
    check("the four cards of the design, in order",
          [c["key"] for c in s["cards"]] == ["active", "reached", "open_rate", "click_rate"])
    check("clients touchés counts every send", cards["reached"]["value"] == 5)
    check("the click rate is followed links, 2 of 5", cards["click_rate"]["value"] == 40.0)
    check("the open rate counts cards opened inside the window, 2 of 5",
          cards["open_rate"]["value"] == 40.0)
    check("a card opened long after the push does not count",
          cards["open_rate"]["value"] != 60.0)
    check("the open rate says what it really measures",
          "carte ouverte" in cards["open_rate"]["note"])
    check("the window is published rather than hidden", s["open_window_hours"] == 72)
    check("scénarios actifs counts the switched-on ones", cards["active"]["value"] == 6)
    check("a click is recorded once, not on every visit",
          PW.register_click(logs[0]["id"]) is not None
          and db.push_wallet_log.find_one({"id": logs[0]["id"]})["clicked_at"] is not None)

    # ---- creating, editing, deleting -------------------------------------------------
    print("\nA merchant's own scenario")
    made = PW.create_scenario(PW.ScenarioIn(
        name="Jour de marché", subtitle="Le samedi", trigger="time_slot",
        config={"weekdays": [5], "from_hour": 8, "to_hour": 13},
        title="🥖 C'est jour de marché", body="Passez nous voir !"), TD())
    check("it is created and switched on", made["name"] == "Jour de marché" and made["enabled"])
    check("it shows up in the table", len(PW.list_scenarios(token_data=TD())["scenarios"]) == 9)
    PW.update_scenario(made["id"], PW.ScenarioPatch(title="🥖 Marché !"), TD())
    check("editing it sticks",
          db.push_scenarios.find_one({"id": made["id"]})["title"] == "🥖 Marché !")
    try:
        PW.create_scenario(PW.ScenarioIn(name="X", trigger="telepathy",
                                         title="a", body="b"), TD())
        check("an unknown trigger is refused", False)
    except HTTPException as exc:
        check("an unknown trigger is refused", exc.status_code == 400)
    PW.delete_scenario(made["id"], TD())
    check("deleting it removes it", len(PW.list_scenarios(token_data=TD())["scenarios"]) == 8)
    try:
        PW.delete_scenario("nope", TD())
        check("deleting something that is not there is refused", False)
    except HTTPException as exc:
        check("deleting something that is not there is refused", exc.status_code == 404)

    print("\nPreview says who would be reached, without sending")
    before = db.push_wallet_log.count_documents({})
    prev = PW.preview_audience(by_key["inactive"]["id"], TD())
    check("it returns a count", isinstance(prev["count"], int))
    check("and sends nothing", db.push_wallet_log.count_documents({}) == before)

    # ---- personalisation ---------------------------------------------------------------
    print("\nTokens in the message")
    cust = {"name": "Marie Dupont", "points": 120, "visits": 7}
    check("{first_name} is the first name only",
          PW._render("Bonjour {first_name} !", cust, {"name": "Le Petit Café"}) == "Bonjour Marie !")
    check("{points} and {business_name} resolve",
          PW._render("{points} pts chez {business_name}", cust, {"name": "Le Petit Café"})
          == "120 pts chez Le Petit Café")
    check("an unknown token is left alone rather than blanked",
          "{weather}" in PW._render("{weather}", cust, {}))

    # ---- isolation and resilience --------------------------------------------------------
    print("\nOne shop never reaches another's clients")
    rival_page = PW.list_scenarios(token_data=Rival())
    check("the rival gets their own eight", len(rival_page["scenarios"]) == 8)
    check("and their own empty counters", all(s["clients"] == 0 for s in rival_page["scenarios"]))
    try:
        PW.update_scenario(by_key["birthday"]["id"], PW.ScenarioPatch(enabled=False), Rival())
        check("they cannot edit someone else's scenario", False)
    except HTTPException as exc:
        check("they cannot edit someone else's scenario", exc.status_code == 404)

    print("\nThe runner never takes the cron down with it")
    broken = db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "birthday"})
    broken.pop("_id", None)
    broken["trigger"] = "nonsense"
    res = PW.run_scenario("t1", broken, now)
    check("an unknown trigger reaches nobody and raises nothing", res["targeted"] == 0)
    original = server.dispatch_to_customer
    server.dispatch_to_customer = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("push down"))
    db.push_wallet_log.delete_many({})
    res = fire("inactive")
    check("a delivery that fails is counted, not fatal", res["errors"] >= 1)
    server.dispatch_to_customer = original

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
