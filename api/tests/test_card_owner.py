"""
Whose phone is a card on? (user, 2026-10-08: « maine uska QR scan kiya toh
uska card khula, jabki mera card khulna chahiye tha … card delete kiya and
uske baad … sign up page khulna chahiye tha »)

Run: cd api && /usr/local/bin/python3 tests/test_card_owner.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-owner")
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
    import auth
    import httpx
    import features.wallet_passes as W
    from services import card_owner as CO
    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([{"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active"},
                            {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active"}])
    for cid, tid, bc, phone in (("me", "t1", "FT-00000A01", "0611111111"), ("friend", "t1", "FT-00000F01", "0622222222"),
                                ("me2", "t2", "FT-00000B01", "0633333333")):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": cid.title(),
                                 "phone": phone, "visits": 3, "points": 30, "created_at": now})
    ME, FRIEND, OTHER_SHOP = "FT-00000A01", "FT-00000F01", "FT-00000B01"
    k = CO.key_for

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def whose(bc, key=None, mine=None, headers=None, shop=False):
        return http("POST", f"/api/card/{bc}/whose", headers=headers,
                    json={"k": key, "mine": mine or {}, "shop": shop}).json()

    print("\nScanning a friend's QR")
    r = whose(FRIEND)
    check("a phone with no card of the shop → the signup form, the friend as parrain",
          r["view"] == "join" and r["slug"] == "cafe" and r["parrain"] == FRIEND)
    r = whose(FRIEND, mine={ME: k(ME)})
    check("a phone holding my card of that shop → MY card", r["view"] == "own" and r["barcode_id"] == ME)
    r = whose(FRIEND, mine={OTHER_SHOP: k(OTHER_SHOP)})
    check("a card of another shop does not count → signup", r["view"] == "join")
    r = whose(FRIEND, mine={ME: "0" * 20})
    check("a card claimed without its key does not count, and the phone forgets it",
          r["view"] == "join" and ME in r["drop"])
    check("the friend's card itself never opens on my phone", whose(FRIEND, mine={ME: k(ME)})["view"] != "card")
    check("the referral programme being off changes nothing (no card shown)", whose(FRIEND)["view"] == "join")

    print("\nMy own links")
    r = whose(ME, key=k(ME))
    check("my link (Wallet / signup / SMS) opens my card and gives the phone its key",
          r["view"] == "card" and r["key"] == k(ME))
    check("then my card opens without the key", whose(ME, mine={ME: k(ME)})["view"] == "card")
    check("a wrong key is a stranger", whose(ME, key="deadbeef")["view"] == "join")
    check("an unknown card is a 404", http("POST", "/api/card/FT-NOPE0000/whose", json={}).status_code == 404)

    print("\nRemoved from Apple Wallet")
    auth_h = {"Authorization": "ApplePass " + W._auth_token(ME)}
    http("POST", f"/api/passes/v1/devices/dev1/registrations/pass.x/{ME}", headers=auth_h, json={"pushToken": "t"})
    check("while the pass is in Wallet, a friend's QR opens mine", whose(FRIEND, mine={ME: k(ME)})["view"] == "own")
    http("DELETE", f"/api/passes/v1/devices/dev1/registrations/pass.x/{ME}", headers=auth_h)
    r = whose(FRIEND, mine={ME: k(ME)})
    check("pass deleted → a friend's QR opens the signup form, and the phone forgets my card",
          r["view"] == "join" and ME in r["drop"])
    j = http("POST", "/api/join/cafe", json={"name": "Me", "phone": "0611111111", "postal_code": "37000",
                                             "birthday": "01-02", "consent_marketing": True, "accept_terms": True}).json()
    # (user, 2026-10-09) typing a number never hands over its card: the owner
    # finds it in Wallet or at the counter — a stranger with the number gets nothing
    det = j.get("detail") or {}
    check(f"signing up again with my number: told I have a card, given no card and no key ({det.get('code')})",
          det.get("code") == "already_member" and "barcode_id" not in j and "card_key" not in j)

    print("\nThe shop's team")
    def tok(role, tid):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": f"{role}@x.fr", "role": role, "tenant_id": tid})}
    db.users.insert_many([{"email": "business_owner@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "staff@x.fr", "role": "staff", "tenant_id": "t2"}])
    r = whose(FRIEND, headers=tok("business_owner", "t1"), shop=True)
    check("the shop's owner opens a customer's card from the dashboard", r["view"] == "card" and r.get("shop"))
    check("another shop's team is a stranger", whose(FRIEND, headers=tok("staff", "t2"), shop=True)["view"] == "join")
    check("the owner signed in on their phone who SCANS a customer's QR is a customer like any other",
          whose(FRIEND, headers=tok("business_owner", "t1"))["view"] == "join")

    print("\nLinks")
    pj = W.build_pass_json(W._card_payload(ME))
    qr = pj["barcodes"][0]["message"]
    check("the QR on the card never carries the key", "k=" not in qr and server.barcode_from(qr) == ME)
    backs = {f["key"]: f["value"] for style in pj.values() if isinstance(style, dict)
             for f in style.get("backFields", [])}
    check("« Ma carte en ligne » on the pass is the owner's link", backs.get("card", "").endswith(f"/card/{ME}?k={k(ME)}"))
    m = http("GET", f"/api/manifest/{ME}?k={k(ME)}").json()
    check("the home-screen app starts on the owner's link", m["start_url"] == f"/card/{ME}?k={k(ME)}")
    check("…only with the right key", http("GET", f"/api/manifest/{ME}?k=bad").json()["start_url"] == f"/card/{ME}"
          and http("GET", f"/api/manifest/{ME}").json()["start_url"] == f"/card/{ME}")
    act = {"type": "membershipBenefits"}
    check("a Wallet tile tapped with the key keeps it", f"k={k(ME)}" in W.featured_target(act, ME, {}, True))
    check("…and without it gives none away", "k=" not in W.featured_target(act, ME, {}, False))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
