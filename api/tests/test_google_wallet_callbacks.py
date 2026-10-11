"""
Google Wallet tells us of saves and deletions (user, 2026-10-10: « even for
Google Wallet also, deleted card ka data chahiye »). Messages are built here
exactly as Google signs them (ECv2SigningOnly: a root key signs an
intermediate key, which signs the message), with test keys in place of
Google's — and every forgery is refused.

Run: cd api && /usr/local/bin/python3 tests/test_google_wallet_callbacks.py
"""
import asyncio
import base64
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-google-callbacks")
os.environ.setdefault("DISABLE_SEED", "1")
ISSUER = "3388000000012345678"
os.environ["GOOGLE_WALLET_ISSUER_ID"] = ISSUER
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import server
    import auth
    import httpx
    from features import google_wallet_callbacks as G
    from features import wallet_passes as WP
    from features import card_status as CS

    db = server.db
    b64 = lambda b: base64.b64encode(b).decode()           # noqa: E731
    pub = lambda k: b64(k.public_key().public_bytes(serialization.Encoding.DER,   # noqa: E731
                                                    serialization.PublicFormat.SubjectPublicKeyInfo))
    sign = lambda k, data: b64(k.sign(data, ec.ECDSA(hashes.SHA256())))           # noqa: E731
    root, inter, stranger = (ec.generate_private_key(ec.SECP256R1()) for _ in range(3))
    G._KEYS.update(keys=[pub(root)], at=time.time())      # Google's root key, in this test
    ms = lambda s: str(int((time.time() + s) * 1000))     # noqa: E731

    def token(event, object_id, nonce, *, recipient=ISSUER, exp=600, root_key=root, inter_key=inter,
              protocol="ECv2SigningOnly", tamper=None):
        signed_key = json.dumps({"keyValue": pub(inter_key), "keyExpiration": ms(3600)})
        msg = json.dumps({"classId": f"{ISSUER}.fidclic_t1", "objectId": object_id, "eventType": event,
                          "expTimeMillis": int(ms(exp)), "nonce": nonce})
        t = {"protocolVersion": protocol, "signedMessage": msg,
             "signature": sign(inter_key, G._lp("GooglePayPasses", recipient, "ECv2SigningOnly", msg)),
             "intermediateSigningKey": {"signedKey": signed_key,
                                        "signatures": [sign(root_key, G._lp("GooglePayPasses", "ECv2SigningOnly", signed_key))]}}
        if tamper:
            t["signedMessage"] = t["signedMessage"].replace('"del"', '"save"')
        return t

    def post(body):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.post("/api/passes/google/callback", json=body,
                                     headers={"User-Agent": "Googlebot"})
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    O = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.customers.insert_one({"id": "g1", "tenant_id": "t1", "barcode_id": "FT-ABCD1234", "name": "Gaëlle Vert",
                             "phone": "0611111111", "visits": 2, "created_at": now})
    obj = f"{ISSUER}.FT_ABCD1234"
    db.google_wallet_objects.insert_one({"serial": "FT-ABCD1234", "object_id": obj, "tenant_id": "t1"})
    state = lambda: CS.state_of(db.customers.find_one({"id": "g1"}))["state"]   # noqa: E731

    def http(method, url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=O)
        return asyncio.get_event_loop().run_until_complete(run())

    print("\nForgeries change nothing")
    for label, t in (
        ("a message signed by someone else's key", token("del", obj, "n-x1", inter_key=stranger, root_key=stranger)),
        ("an intermediate key not signed by Google", token("del", obj, "n-x2", root_key=stranger)),
        ("a message meant for another issuer", token("del", obj, "n-x3", recipient="999")),
        ("an expired message", token("del", obj, "n-x4", exp=-5)),
        ("another protocol", token("del", obj, "n-x5", protocol="ECv2")),
        ("a message changed after signing", token("del", obj, "n-x6", tamper=True)),
        ("no signature at all", {"signedMessage": json.dumps({"objectId": obj, "eventType": "del"})}),
    ):
        r = post(t)
        check(f"refused (400): {label}", r.status_code == 400)
    check("…and the card is still « Active »", state() == "active")

    print("\nDeleted from Google Wallet")
    r = post(token("del", obj, "n-1"))
    check("Google's signed « del » is accepted", r.status_code == 200 and r.json().get("ok"))
    check("the card reads « Retirée de Google Wallet »", state() == "google_removed")
    row = next(x for x in http("GET", "/api/owner/clients/list?per_page=50").json()["rows"] if x["id"] == "g1")
    check("Clients › Carte says it, with the date", row["card"]["label"] == "Retirée de Google Wallet" and row["card"]["at"])
    check("the « Supprimée (24 h) » filter finds it",
          "g1" in http("GET", "/api/owner/clients/ids?card=recent").json()["ids"])
    home = http("GET", "/api/owner/home/overview").json()
    check("the dashboard banner counts it", home["cards_lost"]["count"] == 1)
    bell = [a["title"] for a in http("GET", "/api/owner/insights/alerts/multi-store").json()["alerts"]
            if str(a.get("id", "")).startswith("card-lost:")]
    check(f"the bell: « Gaëlle V. a retiré sa carte de Google Wallet » ({bell})",
          bell == ["Gaëlle V. a retiré sa carte de Google Wallet"])
    first = db.customers.find_one({"id": "g1"})["google_removed_at"]
    r = post(token("del", obj, "n-1"))
    check("Google sending it twice (same nonce) changes nothing",
          r.status_code == 200 and db.customers.find_one({"id": "g1"})["google_removed_at"] == first)

    print("\nSaved again")
    time.sleep(0.01)
    r = post(token("save", obj, "n-2"))
    check("a « save » after it: « Active » again", r.status_code == 200 and state() == "active")

    print("\nNot ours")
    r = post(token("del", "1111.FT_ZZZZ0000", "n-3"))
    check("another issuer's pass is ignored", r.status_code == 200 and r.json().get("ignored"))
    r = post(token("del", f"{ISSUER}.FT_NOPE0000", "n-4"))
    check("an unknown pass is ignored", r.status_code == 200 and r.json().get("ignored"))

    print("\nThe class tells Google where to call")
    os.environ["VERCEL_ENV"], os.environ["VERCEL_URL"] = "preview", "x-git-branch.vercel.app"
    cls = WP._gw_class({"tenant": {"id": "t1", "name": "Café"}, "card": {}, "customer": {"barcode_id": "FT-ABCD1234"}})
    os.environ.pop("VERCEL_ENV"); os.environ.pop("VERCEL_URL")
    check("callbackOptions.url = production's, even built from a preview",
          cls.get("callbackOptions", {}).get("url") == "https://app.fidclic.com/api/passes/google/callback")
    calls = []
    classes = {f"{ISSUER}.fidclic_t1": {}, f"{ISSUER}.fidclic_t2": {"callbackOptions": {"url": G.callback_url()}}}
    db.google_wallet_objects.insert_one({"serial": "FT-T2000001", "object_id": f"{ISSUER}.FT_T2000001", "tenant_id": "t2"})
    WP.google_configured = lambda: True
    WP._gw_access_token = lambda: "tok"

    def fake_call(method, path, body, tok):
        calls.append((method, path, body))
        cid = path.rsplit("/", 1)[-1]
        return (200, classes.get(cid, {})) if cid in classes else (404, {})
    WP._gw_call = fake_call
    out = G.ensure_callbacks()
    check(f"the daily run puts the URL on a class without it, skips one that has it ({out})",
          out["updated"] == 1 and out["already"] == 1
          and ("PATCH", f"/loyaltyClass/{ISSUER}.fidclic_t1", {"callbackOptions": {"url": G.callback_url()}}) in calls)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
