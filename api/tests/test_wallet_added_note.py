"""
The card lands in Apple Wallet → only the shop's own « Bienvenue » speaks.

History. 2026-11-25 (c1a0d9a): when the shop's Bienvenue automation said
nothing, FidClic sent its own « Bienvenue chez … 🎉 » on the card (the pass's
banner opens that very card). 2026-11-26, the user: Royal Trim Liberté had
its Bienvenue OFF and a client still got « Bienvenue chez Royal Trim
Liberté » — « bilkul na bheje ». Then, case by case: a client outside the
automation's audience, a client of another establishment, a client the
owner paused (« very very imp »), a plan without automations — none of them
gets anything: « fidclic ka apna khud ka message mat rkho kuch ».

    · the shop's Bienvenue is on and targets this client: its words, once;
    · in every other case: nothing — no card message, no push, no web push,
      no SMS;
    · once per client: a second iPhone, a removed-then-added card, a card
      already in a Wallet before (any trace, 2026-11-26 Mahdi's case), a
      lane retry say nothing more;
    · Google Wallet opens the card itself after « Enregistrer ».

Run: cd api && python3 tests/test_wallet_added_note.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-added-note")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


def main():
    import server
    import httpx
    from features import automations as AU
    from features import wallet_passes as WP

    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    pushed, webpush = [], []
    WP.notify_customer = lambda cid, message=None, google_notify=None: pushed.append(cid) or {}
    server.dispatch_to_customer = lambda *a, **kw: webpush.append(a) or {}
    WP._ping_main = lambda: None                  # never wake a real server from a test
    pt = os.environ.get("APPLE_PASS_TYPE_ID") or "pass.com.fidclic.test"
    os.environ["APPLE_PASS_TYPE_ID"] = pt

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    def shop(tid, name, plan="vip", welcome=None, **kw):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": plan, "subscription_status": "active",
                               "is_active": True, **kw})
        db.card_templates.insert_one({"tenant_id": tid, "reward_threshold_stamps": 10, "reward_description": "Une coupe"})
        if welcome is not None:
            AU.migrate(tid)
            db.automations.update_many({"tenant_id": tid, "scenario": "welcome"}, {"$set": welcome})

    def card(tid, bc, name="Soan Rémy", **kw):
        db.customers.insert_one({"id": bc.lower(), "tenant_id": tid, "barcode_id": bc, "name": name, "visits": 0,
                                 "points": 0, "created_at": now, **kw})
        return db.customers.find_one({"barcode_id": bc}, {"_id": 0})

    def fidclic_note(bc):
        row = db.customers.find_one({"barcode_id": bc}, {"_id": 0, "auto_news": 1, "card_added_note_at": 1}) or {}
        n = row.get("auto_news") or {}
        return n.get("kind") == "card_added" or row.get("card_added_note_at") is not None

    def welcomes(bc):
        return db.automation_log.count_documents({"customer_id": bc.lower(), "scenario": "welcome"})

    def silent(bc, label):
        """Nothing at all went to this client."""
        web = [a for a in webpush if len(a) > 1 and isinstance(a[1], dict) and a[1].get("id") == bc.lower()]
        check(label, not fidclic_note(bc) and welcomes(bc) == 0 and bc.lower() not in pushed and not web,
              (fidclic_note(bc), welcomes(bc), pushed, len(web)))

    ON = {"status": "active"}
    shop("rt-off", "Royal Trim Liberté")                          # never set up: off (the default)
    shop("rt-paused", "Barbier Pausé", welcome={"status": "paused"})
    shop("rt", "Royal Trim", welcome=ON)

    print("\n0. The shop's Bienvenue is off (user, 2026-11-26: « bilkul na bheje ») → nothing at all")
    c = card("rt-off", "FT-OFF00001")
    out = AU.wallet_added("rt-off", c, "apple")
    silent("FT-OFF00001", "never set up (off by default): nothing")
    check("wallet_added says nothing was sent", not any(out or []), out)
    check("FidClic's own message is gone (no card_added_note any more)", not hasattr(AU, "card_added_note"))
    c = card("rt-paused", "FT-OFF00002")
    AU.wallet_added("rt-paused", c, "apple")
    silent("FT-OFF00002", "switched off on the Automatisations page: nothing")
    card("rt-off", "FT-OFF00003")
    r = http("POST", f"/api/passes/v1/devices/devOff/registrations/{pt}/FT-OFF00003",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-OFF00003")}, json={"pushToken": "tokOff"})
    check(f"the iPhone's own call links the card ({r.status_code})", r.status_code in (200, 201))
    silent("FT-OFF00003", "…and nothing is said")
    card("rt-off", "FT-OFF00004")
    WP.queue_welcome("FT-OFF00004", "rt-off")
    WP.run_welcome_due()
    silent("FT-OFF00004", "through the iPhone's lane: nothing")
    caught = []
    real_catch = WP._catch_up
    WP._catch_up = lambda *a, **kw: caught.append(a)
    card("rt-off", "FT-OFF00005", apple_downloaded_at=now - dt.timedelta(seconds=60),
         last_visit_date=now - dt.timedelta(seconds=30), visits=1)
    http("POST", f"/api/passes/v1/devices/devOff5/registrations/{pt}/FT-OFF00005",
         headers={"Authorization": "ApplePass " + WP._auth_token("FT-OFF00005")}, json={"pushToken": "tokOff5"})
    check("scanned before the add: the catch-up push still brings the card up to date",
          len(caught) == 1 and not fidclic_note("FT-OFF00005"), caught)
    WP._catch_up = real_catch
    pushed.clear()

    print("\n1. On, but this client is not in its audience → nothing (user: « as simple as that »)")
    shop("seg", "Barbier Fidèles", welcome={**ON, "targeting": {"mode": "segment", "segment": "loyal"}})
    c = card("seg", "FT-SEG00001", name="Ravi Kumar")
    AU.wallet_added("seg", c, "apple")
    silent("FT-SEG00001", "a new client outside « Clients fidèles »: nothing")

    print("\n2. On for establishment A only, the client is B's → nothing")
    shop("multi", "Barbier Deux", branches=[{"id": "A", "name": "A", "is_main": True}, {"id": "B", "name": "B"}],
         welcome={**ON, "store_ids": ["A"]})
    c = card("multi", "FT-MUL00001", name="Sara Benali", branch_id="B")
    AU.wallet_added("multi", c, "apple")
    silent("FT-MUL00001", "Sara (store B): nothing")
    c = card("multi", "FT-MUL00002", name="Inès Morel", branch_id="A")
    AU.wallet_added("multi", c, "apple")
    check("Inès (store A): the shop's Bienvenue, once", welcomes("FT-MUL00002") == 1 and pushed.count("ft-mul00002") == 1, pushed)
    pushed.clear()

    print("\n3. A client the owner paused → nothing, ever (user: « very very imp »)")
    c = card("rt", "FT-PAU00001", name="Paul Arnaud", paused_at=now - dt.timedelta(days=1))
    AU.wallet_added("rt", c, "apple")
    silent("FT-PAU00001", "paused client, Bienvenue on for everyone: nothing")
    card("rt", "FT-PAU00002", paused_at=now)
    http("POST", f"/api/passes/v1/devices/devPau/registrations/{pt}/FT-PAU00002",
         headers={"Authorization": "ApplePass " + WP._auth_token("FT-PAU00002")}, json={"pushToken": "tokPau"})
    silent("FT-PAU00002", "paused client, the iPhone's own call: nothing")

    print("\n4. A plan without Automatisations → nothing, even with the switch on")
    shop("silver", "Barbier Silver", plan="silver", welcome=ON)
    c = card("silver", "FT-SIL00001")
    AU.wallet_added("silver", c, "apple")
    silent("FT-SIL00001", "Silver plan, Bienvenue left on: nothing")

    print("\n5. On and targets the client → the shop's words, once")
    c = card("rt", "FT-NOTE0001")
    AU.wallet_added("rt", c, "apple")
    row = db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0})
    check("the automation spoke (its log)", welcomes("FT-NOTE0001") == 1)
    check("the iPhone is pushed once, for this card", pushed == ["ft-note0001"], pushed)
    check("nothing from FidClic itself", not fidclic_note("FT-NOTE0001"), row)
    pushed.clear()
    AU.wallet_added("rt", db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0}), "apple")
    check("a second iPhone: nothing more", pushed == [] and welcomes("FT-NOTE0001") == 1, pushed)
    db.customers.update_one({"barcode_id": "FT-NOTE0001"}, {"$set": {"wallet_removed_at": now}})
    AU.wallet_added("rt", db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0}), "apple")
    check("removed, then added again: nothing more", pushed == [] and welcomes("FT-NOTE0001") == 1, pushed)
    pair = card("rt", "FT-NOTE0013")                   # an iPhone and its Apple Watch, the same seconds
    for s_ago in (3, 1):
        db.pass_registration_log.insert_one({"tenant_id": "rt", "serial": "FT-NOTE0013", "kind": "added",
                                             "at": now - dt.timedelta(seconds=s_ago)})
    AU.wallet_added("rt", pair, "apple")
    check("added on two devices at once (iPhone + Watch): welcomed, once",
          welcomes("FT-NOTE0013") == 1 and pushed == ["ft-note0013"], pushed)
    pushed.clear()

    print("\n6. Already in a Wallet before (user, 2026-11-26: Mahdi's card, added in October) → nothing")
    oct_ = dt.datetime(2026, 10, 12, 9, 0, tzinfo=dt.timezone.utc)
    jan = dt.datetime(2026, 1, 1, 0, 0, tzinfo=dt.timezone.utc)
    c = card("rt", "FT-OLD00001")
    db.pass_registrations.insert_one({"device_id": "devOct", "serial": "FT-OLD00001", "push_token": "tOct",
                                      "tenant_id": "rt", "created_at": oct_})
    AU.wallet_added("rt", c, "apple")
    silent("FT-OLD00001", "another iPhone held it since October")
    AU.wallet_added("rt", card("rt", "FT-OLD00002", wallet_added_at=oct_), "apple")
    silent("FT-OLD00002", "« added » in October on the client")
    AU.wallet_added("rt", card("rt", "FT-OLD00003", wallet_first_added_at=jan), "apple")
    silent("FT-OLD00003", "first added on 1 Jan 2026")
    AU.wallet_added("rt", card("rt", "FT-OLD00004", apple_unregistered_fetch_at=oct_), "apple")
    silent("FT-OLD00004", "an iPhone already fetched it (unregistered)")
    c = card("rt", "FT-OLD00005")
    db.pass_push_log.insert_one({"serial": "FT-OLD00005", "device_id": "devP", "sent_at": oct_})
    AU.wallet_added("rt", c, "apple")
    silent("FT-OLD00005", "an iPhone was pushed this card before")
    back = card("rt", "FT-NOTE0010")
    for d in (40, 0):
        db.pass_registration_log.insert_one({"tenant_id": "rt", "serial": "FT-NOTE0010", "kind": "added",
                                             "at": now - dt.timedelta(days=d)})
    AU.wallet_added("rt", back, "apple")
    silent("FT-NOTE0010", "the registration log has an older add")
    c = card("rt", "FT-OLD00006")                      # iPhone + its Watch, a minute apart: one add
    db.pass_registrations.insert_one({"device_id": "devW", "serial": "FT-OLD00006", "push_token": "tW",
                                      "tenant_id": "rt", "created_at": now - dt.timedelta(minutes=1)})
    AU.wallet_added("rt", c, "apple")
    check("another device a minute ago (Watch): still one welcome", pushed == ["ft-old00006"], pushed)
    pushed.clear()
    check("a client never in a Wallet: added_before is False", AU.added_before(card("rt", "FT-OLD00007"), now) is False)
    check("odd inputs: added_before never raises", AU.added_before(None, now) is False and AU.added_before({}, now) is False)
    check("dates as text are read too", AU.added_before(card("rt", "FT-OLD00008",
                                                             wallet_added_at="2026-10-12T09:00:00+00:00"), now) is True)

    print("\n7. Google Wallet")
    c = card("rt-off", "FT-NOTE0003")
    AU.wallet_added("rt-off", c, "google")
    silent("FT-NOTE0003", "Bienvenue off: nothing")

    print("\n8. Odd inputs")
    check("no shop id: nothing, no error", AU.wallet_added(None, c, "apple") == [])
    check("no client: nothing, no error", AU.wallet_added("rt", None, "apple") == [])
    AU.wallet_added("rt", card("rt", "FT-NOTE0006", deleted_at=now), "apple")
    silent("FT-NOTE0006", "a deleted client: nothing")

    print("\n9. The whole way: the iPhone's own call (Bienvenue on)")
    card("rt", "FT-NOTE0007")
    r = http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
             headers={"Authorization": "ApplePass wrong"}, json={"pushToken": "tokA"})
    check(f"a forged link: refused ({r.status_code}), nothing said",
          r.status_code == 401 and welcomes("FT-NOTE0007") == 0 and pushed == [])
    r = http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0007")}, json={"pushToken": "tokA"})
    check(f"the iPhone links the card ({r.status_code})", r.status_code in (200, 201))
    check("…the shop's Bienvenue goes, the iPhone pushed", welcomes("FT-NOTE0007") == 1 and "ft-note0007" in pushed, pushed)
    pushed.clear()
    http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
         headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0007")}, json={"pushToken": "tokA"})
    check("the same iPhone asks again: nothing more", pushed == [], pushed)
    row = db.customers.find_one({"barcode_id": "FT-NOTE0007"}, {"_id": 0})
    check("the first add's date is kept on the client", row.get("wallet_first_added_at") is not None, row)
    card("rt", "FT-OLD00011", wallet_added_at=oct_)
    r = http("POST", f"/api/passes/v1/devices/devM/registrations/{pt}/FT-OLD00011",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-OLD00011")}, json={"pushToken": "tokM"})
    silent("FT-OLD00011", f"a card added in October, linked again today ({r.status_code}): nothing")
    row = db.customers.find_one({"barcode_id": "FT-OLD00011"}, {"_id": 0})
    first = row.get("wallet_first_added_at")
    first = first if not first or first.tzinfo else first.replace(tzinfo=dt.timezone.utc)
    check("the October date stays the first add", first == oct_, row)

    print("\n10. Through the iPhone's lane (queued, then the server sends)")
    card("rt", "FT-NOTE0008")
    WP.queue_welcome("FT-NOTE0008", "rt")
    WP.queue_welcome("FT-NOTE0008", "rt")                  # the lane retried
    WP.run_welcome_due()
    check("the queued Bienvenue goes, once", pushed.count("ft-note0008") == 1 and welcomes("FT-NOTE0008") == 1, pushed)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
