"""
« Ajouter à Apple Wallet », then the Wallet opens (user, 2026-11-25: the card
was added but the Wallet app never opened).

Safari hands the pass to iOS, iOS adds it and comes back to Safari: nothing in
iOS opens the Wallet app, and the page is never told. The iPhone does tell our
server, though — it links itself to the card (POST …/registrations/…) the
moment the card is in its Wallet. The page asks:

    GET /api/card/{id}/apple-wallet/added  →  {"added": true | false}

    · true only for a link made AFTER this card's pass was last downloaded
      (the tap): a card already on a phone from an older tap says false;
    · the card's own key (or the shop) only, like the pass itself;
    · the answer says nothing else: no device, no token, no date.

Run: cd api && python3 tests/test_apple_wallet_added.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-apple-added")
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
    from services import card_owner as CO

    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda **kw: now - dt.timedelta(**kw)     # noqa: E731

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "t1", "name": "T1", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.tenants.insert_one({"id": "t2", "slug": "t2", "name": "T2", "plan": "vip", "subscription_status": "active",
                           "is_active": True})

    def card(bc, tid="t1", **kw):
        db.customers.insert_one({"id": bc.lower(), "tenant_id": tid, "barcode_id": bc, "name": "Léa", "visits": 0, **kw})
        return {"X-Card-Key": CO.key_for(bc)}

    def link(bc, at, device="dev1", tid="t1"):
        db.pass_registrations.insert_one({"device_id": device, "serial": bc, "push_token": "tok-" + device,
                                          "pass_type_id": "pass.x", "tenant_id": tid, "created_at": at, "updated_at": at})

    def added(bc, headers):
        r = http("GET", f"/api/card/{bc}/apple-wallet/added", headers=headers)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else None)

    print("\n1. Who may ask")
    k = card("FT-ADD00001", apple_downloaded_at=ago(seconds=20))
    link("FT-ADD00001", ago(seconds=5))
    s, _ = added("FT-ADD00001", {})
    check(f"the card number alone: refused ({s})", s in (401, 403))
    s, _ = added("FT-ADD00001", {"X-Card-Key": "wrong"})
    check(f"a wrong key: refused ({s})", s in (401, 403))
    s, _ = added("FT-ADD00001", {"X-Card-Key": CO.key_for("FT-OTHER001")})
    check(f"another card's key: refused ({s})", s in (401, 403))
    r = http("GET", f"/api/card/FT-ADD00001/apple-wallet/added?k={CO.key_for('FT-ADD00001')}")
    check(f"the key as ?k= (the pass link's own way): allowed ({r.status_code})", r.status_code == 200)
    s, _ = added("FT-NOPE0001", {"X-Card-Key": CO.key_for("FT-NOPE0001")})
    check(f"an unknown card: 404 ({s})", s == 404)

    print("\n2. Added after the tap")
    s, body = added("FT-ADD00001", k)
    check("a link made after the download: added", s == 200 and body == {"added": True}, f"{s} {body}")
    check("the answer holds nothing else (no device, token, date)", set(body or {}) == {"added"})
    s, body = added("ft-add00001", k)
    check("the card number in small letters: same answer", s == 200 and body == {"added": True}, f"{s} {body}")

    print("\n3. Not added (yet)")
    k = card("FT-ADD00002", apple_downloaded_at=ago(seconds=10))
    s, body = added("FT-ADD00002", k)
    check("tapped, nothing linked yet: not added", s == 200 and body == {"added": False}, f"{s} {body}")
    k = card("FT-ADD00003")
    link("FT-ADD00003", ago(days=3))
    s, body = added("FT-ADD00003", k)
    check("never downloaded: not added (even with an old link)", s == 200 and body == {"added": False}, f"{s} {body}")
    k = card("FT-ADD00004", apple_downloaded_at=ago(seconds=8))
    link("FT-ADD00004", ago(days=2))
    s, body = added("FT-ADD00004", k)
    check("already on this phone from an older tap: not added (nothing new)", body == {"added": False}, f"{s} {body}")
    link("FT-ADD00004", ago(seconds=2), device="dev2")
    s, body = added("FT-ADD00004", k)
    check("…then a second iPhone adds it: added", body == {"added": True}, f"{s} {body}")

    print("\n4. The clocks of two functions")
    # the iPhone's link is written by the wallet lane (another Vercel function):
    # its clock may be a hair behind the server's
    k = card("FT-ADD00005", apple_downloaded_at=ago(seconds=10))
    link("FT-ADD00005", ago(seconds=11))
    s, body = added("FT-ADD00005", k)
    check("a link 1 s « before » the download (clock skew): added", body == {"added": True}, f"{s} {body}")
    k = card("FT-ADD00006", apple_downloaded_at=ago(minutes=1))
    link("FT-ADD00006", ago(minutes=5))
    s, body = added("FT-ADD00006", k)
    check("a link minutes before the download: not added", body == {"added": False}, f"{s} {body}")
    k = card("FT-ADD00007", apple_downloaded_at=ago(seconds=30).replace(tzinfo=None))
    link("FT-ADD00007", ago(seconds=3).replace(tzinfo=None))
    s, body = added("FT-ADD00007", k)
    check("dates stored without a time zone (as Mongo gives them back): added", body == {"added": True}, f"{s} {body}")

    print("\n5. Only this card's own link")
    k = card("FT-ADD00008", apple_downloaded_at=ago(seconds=20))
    link("FT-ADD00009", ago(seconds=2))                 # another card, same moment
    s, body = added("FT-ADD00008", k)
    check("another card's fresh link: not added", body == {"added": False}, f"{s} {body}")
    k = card("FT-ADD00010", tid="t2", apple_downloaded_at=ago(seconds=20), wallet_added_at=ago(seconds=3))
    s, body = added("FT-ADD00010", k)
    check("wallet_added_at after the download (link row already gone): added", body == {"added": True}, f"{s} {body}")

    print("\n6. The whole way: the iPhone's own call, then the page's question")
    from features import wallet_passes as WP
    WP._after_register = lambda *a, **kw: None        # « Bienvenue » etc. — not this test's
    k = card("FT-ADD00011", apple_downloaded_at=ago(seconds=15))
    s, body = added("FT-ADD00011", k)
    check("before the iPhone's call: not added", body == {"added": False}, f"{s} {body}")
    pt = os.environ.get("APPLE_PASS_TYPE_ID") or "pass.com.fidclic.test"
    os.environ["APPLE_PASS_TYPE_ID"] = pt
    r = http("POST", f"/api/passes/v1/devices/devZ/registrations/{pt}/FT-ADD00011",
             headers={"Authorization": "ApplePass wrong-token"}, json={"pushToken": "tokZ"})
    check(f"a forged link (wrong pass token): refused ({r.status_code})", r.status_code == 401)
    s, body = added("FT-ADD00011", k)
    check("…and the card does not read « added »", body == {"added": False}, f"{s} {body}")
    r = http("POST", f"/api/passes/v1/devices/devZ/registrations/{pt}/FT-ADD00011",
             headers={"Authorization": "ApplePass " + WP._auth_token("FT-ADD00011")}, json={"pushToken": "tokZ"})
    check(f"the iPhone links the card ({r.status_code})", r.status_code in (200, 201))
    s, body = added("FT-ADD00011", k)
    check("then the page reads « added »", s == 200 and body == {"added": True}, f"{s} {body}")

    print("\n7. Shop logins (pentest)")
    import auth

    def tok(email, role, tid):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}
    db.users.insert_many([{"email": "own1@x.fr", "role": "business_owner", "tenant_id": "t1", "is_active": True},
                          {"email": "own2@x.fr", "role": "business_owner", "tenant_id": "t2", "is_active": True},
                          {"email": "staff2@x.fr", "role": "staff", "tenant_id": "t2", "is_active": True}])
    s, body = added("FT-ADD00001", tok("own2@x.fr", "business_owner", "t2"))
    check(f"another shop's owner: refused ({s})", s in (401, 403))
    s, body = added("FT-ADD00001", tok("staff2@x.fr", "staff", "t2"))
    check(f"another shop's staff: refused ({s})", s in (401, 403))
    s, body = added("FT-ADD00001", tok("own1@x.fr", "business_owner", "t1"))
    check(f"the card's own shop (« Voir sa carte »): allowed ({s})", s == 200 and body == {"added": True})
    s, body = added("FT-ADD00001", {"Authorization": "Bearer not-a-token"})
    check(f"a forged token: refused ({s})", s in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
