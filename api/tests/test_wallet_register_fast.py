"""
A card added to Apple Wallet must be linked to its iPhone at once, and stay
updated (user, 2026-11-20, a client of a multi-store shop: card downloaded
at 18:49:16, added to Apple Wallet, scanned at 18:49:51 — 2/10 on his card
page, 0 in Wallet even after pulling to refresh; his iPhone's registration
never reached the database, so no push could ever reach the card).

What this test holds the server to:

    · the registration is written first, before anything else: a database
      that is busy for a moment (a full pool, a reconnect) is tried again,
      the iPhone still gets its 201 and the row is there;
    · what follows a registration (the history line, « Bienvenue », the
      catch-up push for a card scanned before) runs after the answer — the
      iPhone never waits for it, and its failure never undoes the link;
    · a push the iPhone did not come back for within RETRY_AFTER is sent once
      more (the next tick), never twice, never for a refused push, never
      after RETRY_UNTIL, never to an iPhone that left, never past the breaker.

Run: cd api && python3 tests/test_wallet_register_fast.py
"""
import base64
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo
from pymongo import errors as mongo_errors

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-register-fast")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["APPLE_PASS_TYPE_ID"] = "pass.com.fidclic.test"
os.environ["APPLE_PASS_CERT_B64"] = base64.b64encode(b"cert").decode()
os.environ["APPLE_PASS_KEY_B64"] = base64.b64encode(b"key").decode()
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


class Flaky:
    """A collection whose next `fails` calls of `method` raise like a busy pool."""

    def __init__(self, coll, method, fails, exc=mongo_errors.WaitQueueTimeoutError):
        self._c, self._m, self.left, self._exc, self.calls = coll, method, fails, exc, 0

    def __getattr__(self, name):
        real = getattr(self._c, name)
        if name != self._m:
            return real

        def call(*a, **k):
            self.calls += 1
            if self.left > 0:
                self.left -= 1
                raise self._exc("pool busy")
            return real(*a, **k)
        return call


class DbWith:
    """The database, with one collection replaced."""

    def __init__(self, db, **colls):
        self._db, self._colls = db, colls

    def __getattr__(self, name):
        return self._colls.get(name) or getattr(self._db, name)

    def __getitem__(self, name):
        return self._colls.get(name) or self._db[name]


def main():
    import asyncio
    import httpx
    import server
    from fastapi import BackgroundTasks, HTTPException
    from features import wallet_passes as W
    from services import apns_passes as AP

    db = server.db
    W._db = db
    real_db = db
    PT = "pass.com.fidclic.test"
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda **kw: now - dt.timedelta(**kw)     # noqa: E731
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "plan": "vip", "is_active": True})
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "T2", "plan": "vip", "is_active": True})

    sent = []

    def fake_push(tokens, topic=None, cert_paths=None):
        tokens = list(tokens)
        sent.extend(tokens)
        return {"sent": len(tokens), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200, "reason": "", "apns_id": "x"} for t in tokens]}

    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def card(serial, tid="t1", **kw):
        db.customers.insert_one({"id": "c-" + serial, "tenant_id": tid, "barcode_id": serial, "name": "Client",
                                 "visits": 0, "points": 0, **kw})

    def register(serial, device="dev1", token="tok1", pt=PT):
        return http("POST", f"/api/passes/v1/devices/{device}/registrations/{pt}/{serial}",
                    headers={"Authorization": "ApplePass " + W._auth_token(serial)}, json={"pushToken": token})

    # ------------------------------------------------------------------ a busy database
    print("\n1. A busy database for a moment: the iPhone is still linked")
    card("FT-BUSY0001", apple_downloaded_at=ago(seconds=20))
    flaky = Flaky(real_db.pass_registrations, "find_one_and_update", fails=2)
    W._db = DbWith(real_db, pass_registrations=flaky)
    r = register("FT-BUSY0001")
    W._db = real_db
    check(f"201 after two busy answers ({r.status_code})", r.status_code == 201, r.text[:200])
    check("the registration row is written", db.pass_registrations.find_one({"serial": "FT-BUSY0001", "device_id": "dev1"}))
    check(f"tried three times ({flaky.calls})", flaky.calls == 3)

    card("FT-BUSY0002", apple_downloaded_at=ago(seconds=20))
    flaky = Flaky(real_db.customers, "find_one", fails=1, exc=mongo_errors.AutoReconnect)
    W._db = DbWith(real_db, customers=flaky)
    r = register("FT-BUSY0002")
    W._db = real_db
    check(f"the card read busy once: still 201 ({r.status_code})", r.status_code == 201, r.text[:200])
    check("…and linked", db.pass_registrations.find_one({"serial": "FT-BUSY0002"}))

    card("FT-DOWN0001", apple_downloaded_at=ago(seconds=20))
    flaky = Flaky(real_db.pass_registrations, "find_one_and_update", fails=99)
    W._db = DbWith(real_db, pass_registrations=flaky)
    r = register("FT-DOWN0001")
    W._db = real_db
    check(f"a database really down: 503, so the iPhone tries again later ({r.status_code})", r.status_code == 503)
    check(f"…after a few tries, not forever ({flaky.calls})", 2 <= flaky.calls <= 4)
    check("…nothing half-written", not db.pass_registrations.find_one({"serial": "FT-DOWN0001"}))

    # ------------------------------------------------------------------ the rest after the answer
    print("\n2. What follows a registration runs after the answer")
    from features import automations as AU
    calls = []
    real_added = AU.wallet_added
    AU.wallet_added = lambda tid, c, where: calls.append(("welcome", c.get("barcode_id")))
    card("FT-LATE0001", apple_downloaded_at=ago(seconds=40), last_visit_date=ago(seconds=5),
         updated_at=ago(seconds=5))
    bg = BackgroundTasks()
    resp = W.register_device("dev9", PT, "FT-LATE0001", W.Registration(pushToken="tok9"),
                             authorization="ApplePass " + W._auth_token("FT-LATE0001"), background=bg)
    check(f"answered 201 ({resp.status_code})", resp.status_code == 201)
    check("linked before the answer", db.pass_registrations.find_one({"serial": "FT-LATE0001", "device_id": "dev9"}))
    check("« Bienvenue » not yet sent when the iPhone gets its answer", calls == [])
    check("no push yet either", "tok9" not in sent)
    asyncio.get_event_loop().run_until_complete(bg())
    check("« Bienvenue » sent right after", calls == [("welcome", "FT-LATE0001")])
    check("the card scanned before the link is pushed right after", "tok9" in sent)
    ev = [e["kind"] for e in db.pass_registration_log.find({"serial": "FT-LATE0001"})]
    check(f"the history says « added » ({ev})", "added" in ev)
    check("Clients › Carte reads « Active »",
          (db.customers.find_one({"barcode_id": "FT-LATE0001"}) or {}).get("wallet_added_at"))

    AU.wallet_added = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("automation broke"))
    card("FT-LATE0002", apple_downloaded_at=ago(seconds=20))
    r = register("FT-LATE0002", device="dev8", token="tok8")
    check(f"a broken « Bienvenue » never undoes the link ({r.status_code})",
          r.status_code == 201 and db.pass_registrations.find_one({"serial": "FT-LATE0002"}))
    AU.wallet_added = real_added

    r = register("FT-LATE0002", device="dev8", token="tok8")
    check(f"the same iPhone again: 200, one row ({r.status_code})",
          r.status_code == 200 and db.pass_registrations.count_documents({"serial": "FT-LATE0002"}) == 1)

    print("\n3. Never under another business's id, never with a wrong key")
    card("FT-SAFE0001", apple_downloaded_at=ago(seconds=20))
    r = http("POST", f"/api/passes/v1/devices/devX/registrations/{PT}/FT-SAFE0001",
             headers={"Authorization": "ApplePass wrong-key-wrong-key-wrong"}, json={"pushToken": "tokX"})
    check(f"a wrong key: 401, nothing written ({r.status_code})",
          r.status_code == 401 and not db.pass_registrations.find_one({"serial": "FT-SAFE0001"}))
    db.wallet_identities.insert_one({"tenant_id": "t2", "pass_type_id": "pass.com.fidclic.t2", "status": "ready"})
    from features import wallet_identities as WI
    real_of = WI.tenant_of_type
    WI.tenant_of_type = lambda pt: "t2" if pt == "pass.com.fidclic.t2" else None
    r = register("FT-SAFE0001", device="devY", token="tokY", pt="pass.com.fidclic.t2")
    WI.tenant_of_type = real_of
    check(f"another business's pass type id: 404, nothing written ({r.status_code})",
          r.status_code == 404 and not db.pass_registrations.find_one({"serial": "FT-SAFE0001"}))
    r = register("FT-NOPE0001")
    check(f"an unknown card: 404 ({r.status_code})", r.status_code == 404)

    # ------------------------------------------------------------------ the push the iPhone did not take
    print("\n4. A push the iPhone did not come back for: sent once more")
    del sent[:]
    rows = [
        ("FT-RTRY0001", "devA", "tokA", ago(minutes=12), 200, None, None),       # not taken: retried
        ("FT-RTRY0002", "devB", "tokB", ago(minutes=12), 200, ago(minutes=11), ago(minutes=11)),  # taken
        ("FT-RTRY0003", "devC", "tokC", ago(minutes=3), 200, None, None),        # too early
        ("FT-RTRY0004", "devD", "tokD", ago(hours=3), 200, None, None),          # too late
        ("FT-RTRY0005", "devE", "tokE", ago(minutes=12), 410, None, None),       # refused by Apple
        ("FT-RTRY0006", "devF", "tokF", ago(minutes=12), 200, None, None),       # iPhone left since
        ("FT-RTRY0007", "devG", "tokG", ago(minutes=12), 200, ago(minutes=11), None),  # asked, not downloaded
    ]
    for serial, dev, tok, at, st, checked, fetched in rows:
        card(serial)
        if serial != "FT-RTRY0006":
            db.pass_registrations.insert_one({"device_id": dev, "serial": serial, "push_token": tok, "pass_type_id": PT,
                                              "tenant_id": "t1"})
        db.pass_push_log.insert_one({"tenant_id": "t1", "serial": serial, "device_id": dev, "token": W._short(tok),
                                     "sent_at": at, "status": st, "checked_at": checked, "fetched_at": fetched, "one_card": True})
    # a design change pushed to the whole shop: never retried (2026-11-12, the push storm)
    card("FT-RTRY0009")
    db.pass_registrations.insert_one({"device_id": "devI", "serial": "FT-RTRY0009", "push_token": "tokI", "pass_type_id": PT,
                                      "tenant_id": "t1"})
    db.pass_push_log.insert_one({"tenant_id": "t1", "serial": "FT-RTRY0009", "device_id": "devI", "token": W._short("tokI"),
                                 "sent_at": ago(minutes=12), "status": 200, "checked_at": None, "fetched_at": None})
    out = W.retry_unfetched(now)
    check(f"the push not taken is sent again ({sorted(sent)})", "tokA" in sent)
    check("a push taken: not again", "tokB" not in sent)
    check("a push of 3 minutes ago: not yet", "tokC" not in sent)
    check("a push of 3 hours ago: given up (the next real change carries it)", "tokD" not in sent)
    check("a push Apple refused: never again", "tokE" not in sent)
    check("an iPhone that left: nothing", "tokF" not in sent)
    check("an iPhone that asked but did not download: sent again", "tokG" in sent)
    check("a whole-shop push (a design change): never retried", "tokI" not in sent)
    check(f"counted ({out})", out.get("retried") == 2)
    again = db.pass_registrations.find_one({"serial": "FT-RTRY0001"}) or {}
    check("the card is stamped changed, so the iPhone's « what changed » lists it", again.get("pass_changed_at"))
    log = list(db.pass_push_log.find({"serial": "FT-RTRY0001"}).sort("sent_at", 1))
    check(f"the retry is in the push history ({len(log)})", len(log) == 2 and log[0].get("retried_at"))
    del sent[:]
    W.retry_unfetched(now + dt.timedelta(minutes=15))
    check(f"the next tick: never a second retry ({sent})", "tokA" not in sent and "tokG" not in sent)

    print("\n4b. A scan's push is marked one card, a whole-shop push is not")
    card("FT-MARK0001", visits=1)
    db.pass_registrations.insert_one({"device_id": "devM", "serial": "FT-MARK0001", "push_token": "tokM", "pass_type_id": PT,
                                      "tenant_id": "t1"})
    W.notify_passes(["FT-MARK0001"])
    row = db.pass_push_log.find_one({"serial": "FT-MARK0001"}, sort=[("sent_at", -1)]) or {}
    check(f"a scan's push: one card ({row.get('one_card')})", row.get("one_card") is True)
    big = [f"FT-BIG{i:05d}" for i in range(8)]
    for i, sr in enumerate(big):
        card(sr)
        db.pass_registrations.insert_one({"device_id": f"devBig{i}", "serial": sr, "push_token": f"tokBig{i}",
                                          "pass_type_id": PT, "tenant_id": "t1"})
    W.notify_passes(big)
    rowb = db.pass_push_log.find_one({"serial": big[0]}) or {}
    check(f"a push of 8 cards: not marked ({rowb.get('one_card')})", not rowb.get("one_card") and rowb.get("sent_at"))

    print("\n5. The breaker still holds a retry")
    del sent[:]
    card("FT-RTRY0008")
    db.pass_registrations.insert_one({"device_id": "devH", "serial": "FT-RTRY0008", "push_token": "tokH",
                                      "pass_type_id": PT, "tenant_id": "t1"})
    db.pass_push_log.insert_one({"tenant_id": "t1", "serial": "FT-RTRY0008", "device_id": "devH", "token": W._short("tokH"),
                                 "sent_at": ago(minutes=12), "status": 200, "checked_at": None, "fetched_at": None,
                                 "one_card": True})
    real_storm = W._storm
    W._storm = lambda tid, n: 999
    W.retry_unfetched(now)
    W._storm = real_storm
    check("past the breaker: held", "tokH" not in sent)

    print("\n6. The 15-minute tick runs it")
    res = server.tick_pass(now)
    check(f"tick_pass has a wallet_retry step ({sorted(res)[:30]})", "wallet_retry" in res)
    check("…without failure", not [f for f in res.get("failures", []) if f.get("step") == "wallet_retry"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
