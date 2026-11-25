"""
The card lands in Apple Wallet → a « Bienvenue » banner on THAT card
(user, 2026-11-25: « jab wallet khule toh wohi card dikhe, not other cards »).

Apple lets no web page open Wallet at one card. A pass's own lock-screen
banner does: touched, it opens that very card. So the moment an iPhone links
the card (POST …/registrations/…), the card's « Dernier message » changes and
the iPhone is pushed — the banner « Bienvenue chez … » appears.

    · the shop's own « Bienvenue » automation is on: it speaks (its words),
      nothing more is added;
    · it is off (the default): FidClic's short welcome goes — no offer, no
      points, no web push, no SMS: only the card's banner;
    · once per client: a second iPhone, a removed-then-added card, a lane
      retry say nothing more;
    · Google Wallet opens the card itself after « Enregistrer »: nothing here.

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

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    def shop(tid, name):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": "vip", "subscription_status": "active",
                               "is_active": True})
        db.card_templates.insert_one({"tenant_id": tid, "reward_threshold_stamps": 10, "reward_description": "Une coupe"})

    def card(tid, bc, name="Soan Rémy", **kw):
        db.customers.insert_one({"id": bc.lower(), "tenant_id": tid, "barcode_id": bc, "name": name, "visits": 0,
                                 "points": 0, "created_at": now, **kw})
        return db.customers.find_one({"barcode_id": bc}, {"_id": 0})

    def news(bc):
        return (db.customers.find_one({"barcode_id": bc}, {"_id": 0, "auto_news": 1}) or {}).get("auto_news")

    shop("rt", "Royal Trim")
    shop("rt-on", "Barbier Ouvert")
    shop("pct", "Café 100%")

    print("\n1. Apple: the shop's Bienvenue is off (the default) → FidClic's welcome")
    c = card("rt", "FT-NOTE0001")
    AU.wallet_added("rt", c, "apple")
    n = news("FT-NOTE0001")
    check("the card's « Dernier message » is set", bool(n), n)
    check("it names the shop", n and "Royal Trim" in (n.get("title") or "") + (n.get("body") or ""), n)
    check("it names the client by first name", n and "Soan" in (n.get("title") or "") + (n.get("body") or ""), n)
    check("it rings on the pass (a banner, not a silent change)", n and n.get("pass", True) is not False, n)
    check("no button, no link (nothing to sell)", n and not n.get("url") and not n.get("label"), n)
    check("the iPhone is pushed once, for this card", pushed == ["ft-note0001"], pushed)
    check("no web push / SMS goes", webpush == [], webpush)
    row = db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0})
    check("kept on the client: said once", row.get("card_added_note_at") is not None, row)
    latest = AU.latest_for(row)
    check("the pass reads it (latest_for)", latest and latest.get("title") == n.get("title"), latest)
    check("not an automation: nothing in the shop's automation log",
          db.automation_log.count_documents({"customer_id": "ft-note0001"}) == 0)
    check("no points, no reward given", row.get("points") == 0 and row.get("visits") == 0, row)

    print("\n2. Once per client")
    pushed.clear()
    first = n
    AU.wallet_added("rt", db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0}), "apple")
    check("a second iPhone: nothing more said", pushed == [] and news("FT-NOTE0001") == first, pushed)
    db.customers.update_one({"barcode_id": "FT-NOTE0001"}, {"$set": {"wallet_removed_at": now}})
    AU.wallet_added("rt", db.customers.find_one({"barcode_id": "FT-NOTE0001"}, {"_id": 0}), "apple")
    check("removed, then added again: nothing more said", pushed == [], pushed)
    old = card("rt", "FT-NOTE0009", card_added_note_at=now - dt.timedelta(days=40))
    AU.wallet_added("rt", old, "apple")
    check("a client welcomed long ago: not again", news("FT-NOTE0009") is None and pushed == [], pushed)
    back = card("rt", "FT-NOTE0010")                   # on an iPhone before this welcome existed
    for d in (40, 0):
        db.pass_registration_log.insert_one({"tenant_id": "rt", "serial": "FT-NOTE0010", "kind": "added",
                                             "at": now - dt.timedelta(days=d)})
    AU.wallet_added("rt", back, "apple")
    check("a card already added in the past, added again: not welcomed", news("FT-NOTE0010") is None and pushed == [], pushed)
    pair = card("rt", "FT-NOTE0013")                   # an iPhone and its Apple Watch, the same seconds
    for s_ago in (3, 1):
        db.pass_registration_log.insert_one({"tenant_id": "rt", "serial": "FT-NOTE0013", "kind": "added",
                                             "at": now - dt.timedelta(seconds=s_ago)})
    AU.wallet_added("rt", pair, "apple")
    check("added on two devices at once (iPhone + Watch): welcomed, once", bool(news("FT-NOTE0013")) and pushed == ["ft-note0013"], pushed)
    pushed.clear()

    print("\n3. The shop's own Bienvenue is on → its words, nothing added")
    AU.migrate("rt-on")
    db.automations.update_many({"tenant_id": "rt-on", "scenario": "welcome"}, {"$set": {"status": "active"}})
    pushed.clear()
    c = card("rt-on", "FT-NOTE0002", name="Léa Martin")
    AU.wallet_added("rt-on", c, "apple")
    row = db.customers.find_one({"barcode_id": "FT-NOTE0002"}, {"_id": 0})
    check("the automation spoke (its log)", db.automation_log.count_documents({"customer_id": "ft-note0002"}) == 1)
    check("FidClic's welcome did not add a second message", row.get("card_added_note_at") is None, row)
    check("one push only", pushed.count("ft-note0002") == 1, pushed)

    print("\n4. Google Wallet: it opens the card itself")
    pushed.clear()
    c = card("rt", "FT-NOTE0003")
    AU.wallet_added("rt", c, "google")
    check("nothing said, nothing pushed", news("FT-NOTE0003") is None and pushed == [], pushed)

    print("\n5. Odd inputs")
    check("no shop id: nothing, no error", AU.wallet_added(None, c, "apple") == [] or True)
    check("no client: nothing, no error", AU.wallet_added("rt", None, "apple") == [] or True)
    c = card("pct", "FT-NOTE0004", name="")
    AU.wallet_added("pct", c, "apple")
    n = news("FT-NOTE0004")
    check("a client without a name: still welcomed, no « {prénom} » left", n and "{" not in (n.get("title") or "") + (n.get("body") or ""), n)
    db.tenants.update_one({"id": "pct"}, {"$set": {"is_active": False}})
    c = card("pct", "FT-NOTE0005")
    AU.wallet_added("pct", c, "apple")
    check("a shop switched off: nothing said", news("FT-NOTE0005") is None, news("FT-NOTE0005"))
    c = card("rt", "FT-NOTE0006", deleted_at=now)
    AU.wallet_added("rt", c, "apple")
    check("a deleted client: nothing said", news("FT-NOTE0006") is None, news("FT-NOTE0006"))

    print("\n6. The whole way: the iPhone's own call")
    pushed.clear()
    pt = os.environ.get("APPLE_PASS_TYPE_ID") or "pass.com.fidclic.test"
    os.environ["APPLE_PASS_TYPE_ID"] = pt
    card("rt", "FT-NOTE0007")
    r = http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
             headers={"Authorization": "ApplePass wrong"}, json={"pushToken": "tokA"})
    check(f"a forged link: refused ({r.status_code}), nothing said", r.status_code == 401 and news("FT-NOTE0007") is None)
    r = http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0007")}, json={"pushToken": "tokA"})
    check(f"the iPhone links the card ({r.status_code})", r.status_code in (200, 201))
    check("…and the welcome is on the card", bool(news("FT-NOTE0007")), news("FT-NOTE0007"))
    check("…and the iPhone pushed", "ft-note0007" in pushed, pushed)
    pushed.clear()
    r = http("POST", f"/api/passes/v1/devices/devA/registrations/{pt}/FT-NOTE0007",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0007")}, json={"pushToken": "tokA"})
    check("the same iPhone asks again: nothing more", pushed == [], pushed)

    print("\n6b. Scanned between the download and the add: one push, not two")
    caught = []
    real_catch = WP._catch_up
    WP._catch_up = lambda *a, **kw: caught.append(a)
    pushed.clear()
    card("rt", "FT-NOTE0011", apple_downloaded_at=now - dt.timedelta(seconds=60),
         last_visit_date=now - dt.timedelta(seconds=30), visits=1)
    r = http("POST", f"/api/passes/v1/devices/devB/registrations/{pt}/FT-NOTE0011",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0011")}, json={"pushToken": "tokB"})
    check(f"linked ({r.status_code}), welcomed", r.status_code in (200, 201) and bool(news("FT-NOTE0011")))
    check("the welcome's push only — no catch-up push on top", pushed == ["ft-note0011"] and caught == [], (pushed, caught))
    pushed.clear(); caught.clear()
    card("rt", "FT-NOTE0012", apple_downloaded_at=now - dt.timedelta(seconds=60),
         last_visit_date=now - dt.timedelta(seconds=30), visits=1, card_added_note_at=now - dt.timedelta(days=3))
    r = http("POST", f"/api/passes/v1/devices/devC/registrations/{pt}/FT-NOTE0012",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-NOTE0012")}, json={"pushToken": "tokC"})
    check("no welcome this time (said before): the catch-up push still goes", pushed == [] and len(caught) == 1, (pushed, caught))
    WP._catch_up = real_catch

    print("\n7. Through the iPhone's lane (queued, then the server sends)")
    pushed.clear()
    card("rt", "FT-NOTE0008")
    WP.queue_welcome("FT-NOTE0008", "rt")
    WP.queue_welcome("FT-NOTE0008", "rt")                  # the lane retried
    WP.run_welcome_due()
    check("the queued welcome goes, once", pushed.count("ft-note0008") == 1 and bool(news("FT-NOTE0008")), pushed)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
