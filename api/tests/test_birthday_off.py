"""
« Business ne off kr rakha hai, fir bhi jaa rha hai » (user, 2026-11-05): an
automation the business switched off, or never switched on, sends nothing,
from any path: the Carte's « Notification anniversaire » switch, the old
defaults at the first scan, the daily run and its catch-up, a run under way,
the queue, the messages a limit held back.

Run: cd api && python3 tests/test_birthday_off.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-birthday-off")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    from features import temoin as _T
    _T.enabled = lambda tid: False
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU, send_rules as SR, insights_page as IP, auto_messages as AM

    db = server.db
    pushed = []
    real_dispatch = server.dispatch_to_customer

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "tid": tid, "kind": kind})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    mmdd = AU._paris(now).strftime("%m-%d")

    def shop(tid, **kw):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.title(), "plan": "vip", "subscription_status": "active",
                               "is_active": True, **kw})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})
        db.card_templates.insert_one({"tenant_id": tid, "reward_threshold_stamps": 10, "reward_description": "Un café"})
        return {"Authorization": "Bearer " + auth.create_access_token(
            {"sub": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})}

    def person(tid, cid, **kw):
        doc = {"id": cid, "tenant_id": tid, "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}", "points": 0,
               "visits": 3, "birthday": mmdd, "created_at": now - dt.timedelta(days=200),
               "last_visit_date": now - dt.timedelta(days=2), **kw}
        db.customers.insert_one(doc)
        return doc

    def bday_rows(tid):
        return list(db.automations.find({"tenant_id": tid, "scenario": "birthday"}, {"_id": 0}))

    def run():
        """Today's run, with the day's mark wiped: the rule is tested, not the once-a-day."""
        db.automations.update_many({}, {"$set": {"last_run_at": None, "running_at": None}})
        pushed.clear()
        AU.run_due(now, source="daily")
        return [p["cid"] for p in pushed]

    def forget_sent():
        db.automation_log.delete_many({})
        db.send_counter.delete_many({})

    print("\n1. The Carte's switch is the real switch")
    H = shop("cafe")
    person("cafe", "a1")
    person("cafe", "a2")
    AU.migrate("cafe")
    db.automations.update_many({"tenant_id": "cafe", "scenario": "birthday"}, {"$set": {"status": "active"}})
    check("before: the switch reads on when the automation is on",
          http("GET", "/api/owner/card/settings", H).json()["toggles"]["birthday_notification"] is True)
    r = http("PUT", "/api/owner/card/settings", H, json={"birthday_notification": False})
    check("the owner's save goes through", r.status_code == 200)
    check("off on the Carte pauses the automation itself",
          [x["status"] for x in bday_rows("cafe")] == ["paused"])
    check("and the page says off", http("GET", "/api/owner/card/settings", H).json()["toggles"]["birthday_notification"] is False)
    check("the Automatisations page says paused too",
          next(x for x in http("GET", "/api/owner/automations", H).json()["rows"] if x["scenario"] == "birthday")["status"] == "paused")
    check("and NOBODY gets the birthday message", run() == [])
    check("nothing logged either", db.automation_log.count_documents({"tenant_id": "cafe"}) == 0)
    r = http("PUT", "/api/owner/card/settings", H, json={"birthday_notification": True})
    check("on again: the automation runs", [x["status"] for x in bday_rows("cafe")] == ["active"])
    check("everyone with a birthday gets it", sorted(run()) == ["a1", "a2"])
    check("never twice", run() == [])
    stamp = dt.datetime(2026, 1, 1, tzinfo=UTC)
    db.automations.update_many({"tenant_id": "cafe", "scenario": "birthday"}, {"$set": {"updated_at": stamp}})
    http("PUT", "/api/owner/card/settings", H, json={"birthday_notification": True})
    check("a save that does not change it touches nothing",
          AU._aware(bday_rows("cafe")[0]["updated_at"]) == stamp)
    http("PUT", "/api/owner/card/settings", H, json={"card_name": "Ma carte"})
    check("a save without the field leaves it alone", bday_rows("cafe")[0]["status"] == "active")
    aid = bday_rows("cafe")[0]["id"]
    http("POST", f"/api/owner/automations/{aid}/status", H, json={"status": "paused"})
    check("paused on the Automatisations page: the Carte reads off",
          http("GET", "/api/owner/card/settings", H).json()["toggles"]["birthday_notification"] is False)
    forget_sent()
    check("and it sends nothing", run() == [])
    check("the switch never writes to the old collection", db.push_scenarios.count_documents({"tenant_id": "cafe"}) == 0)

    print("\n2. Several birthday automations, and a « Personnalisée » on the birthday")
    H2 = shop("multi")
    person("multi", "m1")
    AU.migrate("multi")
    first = bday_rows("multi")[0]
    db.automations.update_one({"id": first["id"]}, {"$set": {"status": "active"}})
    db.automations.insert_one({**first, "id": "bday-2", "status": "active", "name": "Deuxième"})
    db.automations.insert_one({**first, "id": "bday-cust", "scenario": "custom", "status": "active", "name": "Perso",
                               "trigger": {"type": "date", "date_kind": "birthday", "repeat": "yearly"}})
    db.automations.insert_one({**first, "id": "other-cust", "scenario": "custom", "status": "active", "name": "Soldes",
                               "trigger": {"type": "date", "date_kind": "fixed", "date": "2026-12-25"}})
    http("PUT", "/api/owner/card/settings", H2, json={"birthday_notification": False})
    st = {x["id"]: x["status"] for x in db.automations.find({"tenant_id": "multi"}, {"_id": 0})}
    check("off pauses every birthday automation", st[first["id"]] == "paused" and st["bday-2"] == "paused")
    check("the « Personnalisée » on the birthday too", st["bday-cust"] == "paused")
    check("a « Personnalisée » on another date stays on", st["other-cust"] == "active")
    http("PUT", "/api/owner/card/settings", H2, json={"birthday_notification": True})
    st = {x["id"]: x["status"] for x in db.automations.find({"tenant_id": "multi", "scenario": "birthday"}, {"_id": 0})}
    check("on switches ONE back on, not all of them", sorted(st.values()) == ["active", "paused"])

    H3 = shop("deleted")
    AU.migrate("deleted")
    db.automations.delete_many({"tenant_id": "deleted", "scenario": "birthday"})
    check("no birthday automation at all: the switch reads off",
          http("GET", "/api/owner/card/settings", H3).json()["toggles"]["birthday_notification"] is False)
    http("PUT", "/api/owner/card/settings", H3, json={"birthday_notification": False})
    check("off changes nothing and makes no row", bday_rows("deleted") == [])
    http("PUT", "/api/owner/card/settings", H3, json={"birthday_notification": True})
    check("on makes one, active", [x["status"] for x in bday_rows("deleted")] == ["active"])

    print("\n3. Each establishment has its own switch")
    H4 = shop("group", branches=[{"id": "s-a", "name": "A", "status": "active"}, {"id": "s-b", "name": "B", "status": "active"}])
    person("group", "ga", branch_id="s-a", home_store_id="s-a")
    person("group", "gb", branch_id="s-b", home_store_id="s-b")
    AU.migrate("group")
    AU.split_per_store("group")
    db.automations.update_many({"tenant_id": "group", "scenario": "birthday"}, {"$set": {"status": "active"}})
    HA = {**H4, "X-FidClic-Store": "s-a"}
    HB = {**H4, "X-FidClic-Store": "s-b"}
    http("PUT", "/api/owner/card/settings", HA, json={"birthday_notification": False})
    st = {x["store_ids"][0]: x["status"] for x in bday_rows("group")}
    check("off in A pauses A's automation only", st == {"s-a": "paused", "s-b": "active"})
    check("A reads off, B reads on",
          http("GET", "/api/owner/card/settings", HA).json()["toggles"]["birthday_notification"] is False
          and http("GET", "/api/owner/card/settings", HB).json()["toggles"]["birthday_notification"] is True)

    print("\n4. Nobody's defaults turn themselves on")
    H5 = shop("fresh")
    person("fresh", "f1")
    http("GET", "/api/owner/card/settings", H5)
    http("PUT", "/api/owner/card/settings", H5, json={"card_name": "Nouvelle carte"})
    check("a new shop's card save writes no old scenario", db.push_scenarios.count_documents({"tenant_id": "fresh"}) == 0)
    AU.fire("tier_up", "fresh", db.customers.find_one({"id": "f1"}, {"_id": 0}), {"event": "visit"})
    check("first scan: birthday is NOT switched on", [x["status"] for x in bday_rows("fresh")] == ["paused"])
    check("a new shop's birthday sends nothing", "f1" not in run())

    # what a card save left behind before this fix: the old defaults, seeded just now
    shop("seeded")
    person("seeded", "s1", last_visit_date=now - dt.timedelta(days=90))
    from features import push_wallet as PW
    PW._seed("seeded")
    AU.fire("tier_up", "seeded", db.customers.find_one({"id": "s1"}, {"_id": 0}), {"event": "visit"})
    st = {x["scenario"]: x["status"] for x in db.automations.find({"tenant_id": "seeded"}, {"_id": 0})}
    check("old defaults seeded after the old engine ended turn NOTHING on",
          st["birthday"] == "paused" and st["inactive"] == "paused" and st["tier_up"] == "paused")
    check("that shop's clients hear nothing from them", "s1" not in run())

    # a real choice from the old engine's days is kept
    shop("oldtimer")
    db.push_scenarios.insert_many([
        {"id": "ot1", "tenant_id": "oldtimer", "builtin": "birthday", "enabled": True, "created_at": dt.datetime(2026, 9, 1, tzinfo=UTC)},
        {"id": "ot2", "tenant_id": "oldtimer", "builtin": "inactive", "enabled": False, "created_at": dt.datetime(2026, 9, 1, tzinfo=UTC)}])
    AU.migrate("oldtimer")
    st = {x["scenario"]: x["status"] for x in db.automations.find({"tenant_id": "oldtimer"}, {"_id": 0})}
    check("a switch from the old engine's days is kept, on and off", st["birthday"] == "active" and st["inactive"] == "paused")

    print("\n5. Every state that is not « active » sends nothing")
    shop("states")
    person("states", "st1")
    AU.migrate("states")
    row = bday_rows("states")[0]
    for status in ("paused", "draft"):
        db.automations.update_one({"id": row["id"]}, {"$set": {"status": status}})
        check(f"{status}: nobody", "st1" not in run())
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active", "schedule.valid_to": "2020-01-01"}})
    check("ended (date de fin passée): nobody", "st1" not in run())
    db.automations.delete_one({"id": row["id"]})
    check("deleted: nobody", "st1" not in run())
    check("deleted stays deleted: no run brings it back", bday_rows("states") == [])

    print("\n6. Switched off while something was on its way")
    shop("race")
    for i in range(3):
        person("race", f"r{i}")
    AU.migrate("race")
    row = bday_rows("race")[0]
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})
    stale = {**bday_rows("race")[0]}
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "paused"}})
    check("a run holding an old copy cannot claim a paused automation", AU._claim(stale, now) is False)
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active", "running_at": None}})

    def pause_on_first(tid, cust, title, body, kind="campaign", url=None):
        fake_dispatch(tid, cust, title, body, kind, url)
        db.automations.update_one({"id": row["id"]}, {"$set": {"status": "paused"}})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = pause_on_first
    db.automations.update_many({"tenant_id": "race"}, {"$set": {"last_run_at": None, "running_at": None}})
    pushed.clear()
    AU.run_due(now, source="daily")
    server.dispatch_to_customer = fake_dispatch
    check("off in the middle of a round: the rest get nothing", len([p for p in pushed if p["tid"] == "race"]) == 1)

    shop("queue")
    c = person("queue", "q1")
    AU.migrate("queue")
    row = bday_rows("queue")[0]
    H6 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@queue.fr", "role": "business_owner", "tenant_id": "queue"})}
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})
    db.automation_queue.insert_one({"id": "qq", "tenant_id": "queue", "automation_id": row["id"], "customer_id": "q1",
                                    "due_at": now - dt.timedelta(minutes=1), "ctx": {"event": "date"}, "created_at": now})
    http("PUT", "/api/owner/card/settings", H6, json={"birthday_notification": False})
    check("the Carte's off empties its queue", db.automation_queue.count_documents({"automation_id": row["id"]}) == 0)

    print("\n7. A message a limit held back does not go after the off")
    shop("held")
    c = person("held", "h1")
    person("held", "h2")
    AU.migrate("held")
    row = bday_rows("held")[0]
    H7 = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@held.fr", "role": "business_owner", "tenant_id": "held"})}
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})
    row = bday_rows("held")[0]
    real_over = SR.over_limit
    SR.over_limit = lambda *a, **k: "shop_day"
    server.dispatch_to_customer = real_dispatch
    AU._deliver("held", row, c, {"event": "date"}, now)
    server.dispatch_to_customer = fake_dispatch
    SR.over_limit = real_over
    held = db.deferred_messages.find_one({"tenant_id": "held", "customer_id": "h1"}, {"_id": 0})
    check("held back, and it remembers which automation", held and held.get("automation_id") == row["id"])
    later = now + dt.timedelta(days=2)
    http("POST", f"/api/owner/automations/{row['id']}/status", H7, json={"status": "paused"})
    check("the off drops what waits", db.deferred_messages.find_one({"id": held["id"]})["status"] == "dropped")
    pushed.clear()
    SR.drain(later)
    check("the next day's run does not send it", pushed == [])

    def waiting(mid, tid, cid, kind, **kw):
        db.deferred_messages.insert_one({"id": mid, "tenant_id": tid, "customer_id": cid, "title": "t", "body": "b", "kind": kind,
                                         "url": None, "reason": "shop_day", "priority": 1, "status": "waiting",
                                         "first_at": now, "due": now - dt.timedelta(hours=1), "created_at": now, **kw})
    waiting("w-aid", "held", "h1", "birthday", automation_id=row["id"])
    pushed.clear()
    SR.drain(now)
    check("paused without being told: dropped at the send", pushed == []
          and db.deferred_messages.find_one({"id": "w-aid"})["status"] == "dropped")
    waiting("w-old", "held", "h1", "birthday")
    pushed.clear()
    SR.drain(now)
    check("waiting since before this fix (no automation named): dropped when none is on", pushed == []
          and db.deferred_messages.find_one({"id": "w-old"})["status"] == "dropped")
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})
    waiting("w-on", "held", "h1", "birthday", automation_id=row["id"])
    waiting("w-old2", "held", "h2", "birthday")
    pushed.clear()
    SR.drain(now)
    check("still on: what waited goes", sorted(p["cid"] for p in pushed) == ["h1", "h2"])
    db.send_counter.delete_many({})
    waiting("w-camp", "held", "h1", "campaign")
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "paused"}})
    pushed.clear()
    SR.drain(now)
    check("a campaign that waited is not touched by an automation's switch", [p["kind"] for p in pushed] == ["campaign"])
    db.send_counter.delete_many({})
    SR.over_limit = lambda *a, **k: "shop_day"
    db.automations.update_one({"id": row["id"]}, {"$set": {"status": "active"}})
    waiting("w-again", "held", "h1", "birthday", automation_id=row["id"])
    SR.drain(now)
    SR.over_limit = real_over
    again = db.deferred_messages.find_one({"tenant_id": "held", "status": "waiting"}, {"_id": 0})
    check("waiting another day: it still names its automation", again and again.get("automation_id") == row["id"])

    print("\n8. Not only the birthday: every automation off stays silent")
    shop("all", google_review_url="https://g.page/r/x/review", google_reviews_enabled=True)
    pcust = person("all", "z1", last_visit_date=now - dt.timedelta(days=90), wallet_added_at=now)
    AU.migrate("all")
    db.automations.update_many({"tenant_id": "all"}, {"$set": {"status": "paused"}})
    pushed.clear()
    for sc, ctx in (("tier_up", {"event": "visit"}), ("near_reward", {"event": "visit"}), ("google_review", {"event": "visit"}),
                    ("welcome", {"event": "wallet"}), ("referral", {"event": "reward", "side": "parrain"}),
                    ("geo", {"store": "x"}), ("custom", {"event": "visit"})):
        said = AU.fire(sc, "all", pcust, ctx)
        check(f"{sc} off: says nothing", not said)
    check("the daily run says nothing either", "z1" not in run())
    check("not one line in the log", db.automation_log.count_documents({"tenant_id": "all", "status": "sent"}) == 0)
    # the same client and clock, switched on: the silence above was the switch, not the test
    db.automations.update_many({"tenant_id": "all", "scenario": {"$in": ["birthday", "inactive"]}}, {"$set": {"status": "active"}})
    check("switched on, the same client does hear", run().count("z1") >= 1)

    print("\n9. Insights, the Copilote and the settings read the real switch")
    H8 = shop("ins")
    person("ins", "i1")
    AU.migrate("ins")
    check("off: Insights says not done", IP._birthday_on("ins") is False)
    IP.activate("birthday", token_data=auth.TokenData(sub="o@ins.fr", email="o@ins.fr", role="business_owner", tenant_id="ins"))
    check("« Activer » turns on the automation that really sends", [x["status"] for x in bday_rows("ins")] == ["active"])
    check("Insights then says done", IP._birthday_on("ins") is True)
    check("no old row written", db.push_scenarios.count_documents({"tenant_id": "ins"}) == 0)
    view = http("GET", "/api/owner/auto-messages", H8).json()["birthday"]
    check("the settings view reads it too", view["enabled"] is True and view["id"] == bday_rows("ins")[0]["id"])
    http("PUT", "/api/owner/card/settings", H8, json={"birthday_notification": False})
    check("off: Insights goes back to not done", IP._birthday_on("ins") is False)
    check("and the settings view too", http("GET", "/api/owner/auto-messages", H8).json()["birthday"]["enabled"] is False)

    print("\n10. Who may touch it")
    H9 = shop("rival")
    AU.migrate("rival")
    db.automations.update_many({"tenant_id": "rival", "scenario": "birthday"}, {"$set": {"status": "active"}})
    MGR = {"Authorization": "Bearer " + auth.create_access_token({"sub": "m@rival.fr", "role": "manager", "tenant_id": "rival"})}
    db.users.insert_one({"email": "m@rival.fr", "role": "manager", "tenant_id": "rival"})
    check("no token: refused", http("PUT", "/api/owner/card/settings", {}, json={"birthday_notification": False}).status_code == 401)
    check("a manager: refused", http("PUT", "/api/owner/card/settings", MGR, json={"birthday_notification": False}).status_code == 403)
    check("and nothing changed", bday_rows("rival")[0]["status"] == "active")
    before = {x["id"]: x["status"] for x in db.automations.find({"tenant_id": "rival"}, {"_id": 0})}
    http("PUT", "/api/owner/card/settings", H, json={"birthday_notification": False})
    http("PUT", "/api/owner/card/settings", {**H, "X-FidClic-Store": "s-b"}, json={"birthday_notification": False})
    check("another shop's owner, even naming another shop's store, changes nothing here",
          before == {x["id"]: x["status"] for x in db.automations.find({"tenant_id": "rival"}, {"_id": 0})})
    check("nor in the shop whose store was named", {x["store_ids"][0]: x["status"] for x in bday_rows("group")}["s-b"] == "active")
    check("an unknown value is refused", http("PUT", "/api/owner/card/settings", H9, json={"birthday_notification": "maybe"}).status_code == 422)

    print("\n11. Shops whose Carte switch was already off get it honoured, once")
    t0 = dt.datetime(2026, 10, 20, tzinfo=UTC)
    for tid in ("fix-off", "fix-later", "fix-on", "fix-unmigrated"):
        shop(tid)
    for tid in ("fix-off", "fix-later", "fix-on"):
        AU.migrate(tid)
        db.automations.update_many({"tenant_id": tid, "scenario": "birthday"}, {"$set": {"status": "active", "updated_at": t0}})
    db.push_scenarios.insert_many([
        {"id": "p1", "tenant_id": "fix-off", "builtin": "birthday", "enabled": False, "updated_at": t0 + dt.timedelta(days=3)},
        {"id": "p2", "tenant_id": "fix-later", "builtin": "birthday", "enabled": False, "updated_at": t0 - dt.timedelta(days=3)},
        {"id": "p3", "tenant_id": "fix-on", "builtin": "birthday", "enabled": True, "updated_at": t0 + dt.timedelta(days=3)},
        {"id": "p4", "tenant_id": "fix-unmigrated", "builtin": "birthday", "enabled": False, "updated_at": t0}])
    fix_row = bday_rows("fix-off")[0]
    db.automation_queue.insert_one({"id": "fq", "tenant_id": "fix-off", "automation_id": fix_row["id"], "customer_id": "x",
                                    "due_at": now, "ctx": {}, "created_at": now})
    check("it runs at start-up (the mark is already there)", db.automation_meta.find_one({"_id": "birthday_card_off_v1"}))
    db.automation_meta.delete_one({"_id": "birthday_card_off_v1"})
    res = AU.honour_old_birthday_off()
    check("off on the Carte after the last change: paused", bday_rows("fix-off")[0]["status"] == "paused")
    check("its queue goes with it", db.automation_queue.count_documents({"id": "fq"}) == 0)
    check("switched on in Automatisations AFTER the Carte's off: the later choice stays", bday_rows("fix-later")[0]["status"] == "active")
    check("the Carte on: untouched", bday_rows("fix-on")[0]["status"] == "active")
    check("not migrated yet: no row made", bday_rows("fix-unmigrated") == [])
    check("it names the shops it paused, for an undo", res["tenants"] == ["fix-off"])
    db.automations.update_many({"tenant_id": "fix-off", "scenario": "birthday"}, {"$set": {"status": "active"}})
    res = AU.honour_old_birthday_off()
    check("once only: the owner's switching back on later stays", bday_rows("fix-off")[0]["status"] == "active"
          and res.get("already") is True)

    print("\n12. A closed establishment hands its switch to nobody")
    shop("closing", branches=[{"id": "c-a", "name": "A", "status": "closed"}, {"id": "c-b", "name": "B", "status": "active"},
                              {"id": "c-c", "name": "C", "status": "active"}])
    base = AU.new_doc("closing", "birthday")
    db.automations.insert_many([
        {**base, "id": "cl-a", "status": "active", "store_ids": ["c-a"]},
        {**base, "id": "cl-b", "status": "paused", "store_ids": ["c-b"]},
        {**base, "id": "cl-c", "status": "paused", "store_ids": ["c-c"]},
        {**AU.new_doc("closing", "inactive"), "id": "cl-new", "status": "paused", "store_ids": None}])
    db.automation_meta.update_one({"tenant_id": "closing"}, {"$set": {"migrated": True}}, upsert=True)
    AU.split_per_store("closing")
    on = [x for x in bday_rows("closing") if x["status"] == "active"]
    check("the closed store's active row is not copied onto the stores that said off", [x["id"] for x in on] == ["cl-a"])
    check("and no copy of it appears", len(bday_rows("closing")) == 3)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
