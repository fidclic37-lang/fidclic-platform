"""
Scan before the iPhone registers (user, 2026-10-30, ROYAL TRIM LIBÉRTÉ,
card FT-1F64304A): signup 14:39:06, scan 14:40:07, the iPhone registered
14:40:24. At the scan no device was registered, so no push went out and the
card stayed on 0 tampons until the client pulled to refresh.

Now, when an iPhone registers (or comes back with a new push token) and the
card changed after the pass it holds was downloaded, that iPhone is pushed
at once and the change is stamped, so it fetches the current card.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_register_race.py
"""
import base64
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-race")
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


def main():
    import server
    from features import wallet_passes as W
    from services import apns_passes as AP

    db = server.db
    W._db = db
    PT = "pass.com.fidclic.test"
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda **kw: now - dt.timedelta(**kw)     # noqa: E731
    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "plan": "vip", "is_active": True})

    sent = []

    def fake_push(tokens):
        tokens = list(tokens)
        sent.extend(tokens)
        return {"sent": len(tokens), "gone": [], "failed": 0, "errors": [],
                "results": [{"token": t, "status": 200, "reason": "", "apns_id": "x"} for t in tokens]}

    AP.push_to_tokens, AP.is_configured = fake_push, (lambda: True)

    def client(cid, **fields):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "barcode_id": f"FT-{cid.upper()}",
                                 "created_at": ago(days=30), **fields})
        return f"FT-{cid.upper()}"

    def register(dev, serial, token):
        return W.register_device(dev, PT, serial, W.Registration(pushToken=token),
                                 f"ApplePass {W._auth_token(serial)}").status_code

    def pushed(token):
        return token in sent

    def kinds(serial):
        return [e["kind"] for e in db.pass_registration_log.find({"serial": serial}).sort("at", 1)]

    print("\nThe Royal Trim case: downloaded, scanned, then the iPhone registers")
    s = client("race", apple_downloaded_at=ago(seconds=78), last_visit_date=ago(seconds=17), updated_at=ago(seconds=17))
    check("registration still answers 201", register("DEVRACE00000000000001", s, "tokRACE0000000000000001") == 201)
    check("that iPhone is pushed at once", pushed("tokRACE0000000000000001"), sent)
    reg = db.pass_registrations.find_one({"serial": s})
    check("the change is stamped on the registration", reg.get("pass_changed_at") is not None)
    check("the push is in the history", db.pass_push_log.count_documents({"serial": s}) == 1)
    check("and the reason in the card's events", "caught_up" in kinds(s), kinds(s))
    tag = str(int(ago(seconds=78).timestamp()))
    r = W.serials_for_device("DEVRACE00000000000001", PT, tag)
    check("the iPhone asking « what changed since my pass » gets this card",
          isinstance(r, dict) and s in r.get("serialNumbers", []), r)

    print("\nThe same, through Apple's real HTTP callback")
    import asyncio
    import httpx
    s = client("http", apple_downloaded_at=ago(seconds=60), last_visit_date=ago(seconds=10), updated_at=ago(seconds=10))

    async def post():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
            return await ac.post(f"/api/passes/v1/devices/DEVHTTP0000000000001/registrations/{PT}/{s}",
                                 headers={"Authorization": f"ApplePass {W._auth_token(s)}"},
                                 json={"pushToken": "tokHTTP0000000000000001"})
    r = asyncio.get_event_loop().run_until_complete(post())
    check(f"POST registration → 201 ({r.status_code})", r.status_code == 201, r.text[:120])
    check("…and that iPhone pushed", pushed("tokHTTP0000000000000001"), sent)

    print("\nNothing changed since the download → no push")
    s = client("fresh", apple_downloaded_at=ago(minutes=2), last_visit_date=ago(days=3), updated_at=ago(minutes=5))
    check("201", register("DEVFRESH0000000000001", s, "tokFRESH000000000000001") == 201)
    check("not pushed", not pushed("tokFRESH000000000000001"), sent)
    check("no catch-up event", "caught_up" not in kinds(s), kinds(s))

    print("\nAn old client adds the card today, last visit a week ago")
    s = client("old", apple_downloaded_at=ago(minutes=1), last_visit_date=ago(days=7), updated_at=ago(days=7))
    register("DEVOLD00000000000001", s, "tokOLD0000000000000001")
    check("not pushed", not pushed("tokOLD0000000000000001"))

    print("\nNo download stamp (card added before this change)")
    s = client("nostamp_recent", last_visit_date=ago(minutes=3), updated_at=ago(minutes=3))
    register("DEVNSR00000000000001", s, "tokNSR0000000000000001")
    check("changed in the last minutes → pushed", pushed("tokNSR0000000000000001"))
    s = client("nostamp_old", last_visit_date=ago(days=2), updated_at=ago(days=2))
    register("DEVNSO00000000000001", s, "tokNSO0000000000000001")
    check("changed days ago → not pushed", not pushed("tokNSO0000000000000001"))
    s = client("nostamp_never")
    register("DEVNSN00000000000001", s, "tokNSN0000000000000001")
    check("never changed (no dates) → not pushed", not pushed("tokNSN0000000000000001"))

    print("\nThe same iPhone again")
    s = client("again", apple_downloaded_at=ago(minutes=5), last_visit_date=ago(minutes=1), updated_at=ago(minutes=1))
    register("DEVAGAIN000000000001", s, "tokAGAIN00000000000001")
    n = sent.count("tokAGAIN00000000000001")
    check("first registration pushed once", n == 1, n)
    check("same token again → 200 and no second push",
          register("DEVAGAIN000000000001", s, "tokAGAIN00000000000001") == 200
          and sent.count("tokAGAIN00000000000001") == 1, sent.count("tokAGAIN00000000000001"))
    register("DEVAGAIN000000000001", s, "tokAGAIN00000000000NEW")
    check("new push token while the card is newer than its pass → pushed on the new token",
          pushed("tokAGAIN00000000000NEW"))

    print("\nOnly the iPhone that just registered")
    s = client("two", apple_downloaded_at=ago(minutes=10), last_visit_date=ago(days=3), updated_at=ago(days=3))
    register("DEVTWOA0000000000001", s, "tokTWOA000000000000001")
    db.customers.update_one({"barcode_id": s}, {"$set": {"apple_downloaded_at": ago(minutes=4),
                                                         "last_visit_date": ago(minutes=1), "updated_at": ago(minutes=1)}})
    sent.clear()
    register("DEVTWOB0000000000001", s, "tokTWOB000000000000001")
    check("the new iPhone is pushed", pushed("tokTWOB000000000000001"), sent)
    check("the other one is not (it got the scan's own push)", not pushed("tokTWOA000000000000001"), sent)

    print("\nA push problem never breaks a registration")
    AP.push_to_tokens = lambda tokens: (_ for _ in ()).throw(RuntimeError("APNs down"))
    s = client("boom", apple_downloaded_at=ago(minutes=2), last_visit_date=ago(seconds=30), updated_at=ago(seconds=30))
    check("APNs raising → still 201", register("DEVBOOM0000000000001", s, "tokBOOM000000000000001") == 201)
    check("…and registered", db.pass_registrations.count_documents({"serial": s}) == 1)
    AP.is_configured = lambda: False
    s = client("nocert", apple_downloaded_at=ago(minutes=2), last_visit_date=ago(seconds=30), updated_at=ago(seconds=30))
    check("APNs not configured → still 201", register("DEVNOCERT00000000001", s, "tokNOCERT0000000000001") == 201)

    print("\nUnit: changed_since_pass")
    f = W.changed_since_pass
    check("visit after download → True", f({"apple_downloaded_at": ago(minutes=2), "last_visit_date": ago(minutes=1)}, now))
    check("visit before download → False", not f({"apple_downloaded_at": ago(minutes=1), "last_visit_date": ago(minutes=2)}, now))
    check("updated_at counts too", f({"apple_downloaded_at": ago(minutes=2), "updated_at": ago(minutes=1)}, now))
    check("naive datetimes (Mongo) read as UTC",
          f({"apple_downloaded_at": ago(minutes=2).replace(tzinfo=None), "last_visit_date": ago(minutes=1).replace(tzinfo=None)}, now))
    check("no stamp, changed 29 min ago → True", f({"last_visit_date": ago(minutes=29)}, now))
    check("no stamp, changed 31 min ago → False", not f({"last_visit_date": ago(minutes=31)}, now))
    check("empty → False", not f({}, now))
    check("strings / junk → False", not f({"last_visit_date": "hier", "apple_downloaded_at": 5}, now))


main()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
