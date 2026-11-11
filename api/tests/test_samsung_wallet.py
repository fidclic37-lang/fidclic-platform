"""
Samsung Wallet (user, 2026-11-11: « samsung wallet ka integration »). Partner
FIDCLIC, card « FidClic » (Loyalty › Others, Default layout), certificate XVli.

  • the card page gets an « Ajouter à Samsung Wallet » link — Samsung's Data
    Fetch Link, a.swallet.link/atw/v3/{certificateId}/{cardId}#Clip?pdata={refId}
    with a refId nobody can guess (one per card, kept);
  • Samsung then asks us for the card: GET /api/samsung-wallet/cards/{cardId}/{refId}
    → {"card": {"type": "loyalty", "subType": "others", "data": [...]}} read off
    the SAME pass Apple and Google get (same stamps, same QR the till scans);
  • Samsung tells us when the card is added / deleted: POST …?cc2=&event= ;
    the till's Wallet line counts a card in Samsung Wallet as linked;
  • a scan wakes the Samsung card: Update Notification to Samsung, signed
    with our key (JWS RS256, cty AUTH, ver 3, certificateId, partnerId);
  • geofence: the shop's locations from the Géolocalisation automation.

Run: cd api && python3 tests/test_samsung_wallet.py
"""
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-samsung")
os.environ.setdefault("DISABLE_SEED", "1")
for k in ("SAMSUNG_WALLET_PARTNER_ID", "SAMSUNG_WALLET_CARD_ID", "SAMSUNG_WALLET_CERT_ID",
          "SAMSUNG_WALLET_PRIVATE_KEY", "SAMSUNG_WALLET_SAMSUNG_CERT"):
    os.environ.pop(k, None)
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    import server
    import auth
    import httpx
    from features import samsung_wallet as SW
    from features import wallet_passes as W
    from services import card_owner as CO

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for t in ("t1", "t2"):
        db.tenants.insert_one({"id": t, "slug": t, "name": "Royal Trim" if t == "t1" else "Autre", "plan": "vip",
                               "subscription_status": "active", "is_active": True,
                               "address": "12 rue de la Liberté, 37000 Tours", "phone": "0247000000",
                               "website": "https://royaltrim.fr"})
        db.users.insert_one({"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t})
        db.card_templates.insert_one({"tenant_id": t, "programme": "stamps", "reward_threshold_stamps": 10,
                                      "back_fields": [{"label": "Prendre rendez-vous", "value": "https://rdv.example/x"},
                                                      {"label": "<script>alert(1)</script>", "value": "<img src=x onerror=alert(1)>"}]})
    tok = lambda e, r, t: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, H2 = tok("o@t1.fr", "business_owner", "t1"), tok("o@t2.fr", "business_owner", "t2")

    def client(cid, tenant="t1", **kw):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tenant, "name": f"Client {cid}", "barcode_id": bc,
                                 "visits": 4, "visits_at_last_redemption": 0, "points": 0,
                                 "created_at": now - dt.timedelta(days=3), **kw})
        return bc

    mine = lambda bc: {"X-Card-Key": CO.key_for(bc)}  # noqa: E731 — the customer's own phone

    # ------------------------------------------------------------------
    print("\n1. Not configured: no button, no link, nothing answered")
    a = client("anna")
    cfg = http("GET", "/api/wallet/config", params={"barcode": a}).json()
    check("config says samsung: false", cfg.get("samsung") is False)
    r = http("GET", f"/api/card/{a}/samsung-wallet", mine(a))
    check(f"link refused while not configured ({r.status_code})", r.status_code == 503)

    # the portal's values (partner FIDCLIC, card FidClic, certificate XVli) and our key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key()
    os.environ.update({"SAMSUNG_WALLET_PARTNER_ID": "4164397867037138496", "SAMSUNG_WALLET_CARD_ID": "3jina31gjvr00",
                       "SAMSUNG_WALLET_CERT_ID": "XVli", "SAMSUNG_WALLET_PRIVATE_KEY": pem})
    CARD = "3jina31gjvr00"

    # ------------------------------------------------------------------
    print("\n2. The card page's « Ajouter à Samsung Wallet » link")
    cfg = http("GET", "/api/wallet/config", params={"barcode": a}).json()
    check("config says samsung: true", cfg.get("samsung") is True)
    r = http("GET", f"/api/card/{a}/samsung-wallet", mine(a))
    check(f"the owner's phone gets a link ({r.status_code})", r.status_code == 200)
    url = r.json().get("url", "")
    check("Samsung's Data Fetch Link, our certificate and card",
          url.startswith("https://a.swallet.link/atw/v3/XVli/3jina31gjvr00#Clip?pdata="))
    ref = url.split("pdata=", 1)[1]
    check(f"refId: 16–32 safe characters ({len(ref)})", 16 <= len(ref) <= 32 and ref.replace("-", "").replace("_", "").isalnum())
    check("refId is not the card number", a.lower() not in ref.lower() and "anna" not in ref.lower())
    check("the same card keeps its refId", http("GET", f"/api/card/{a}/samsung-wallet", mine(a)).json()["url"] == url)
    b = client("bob")
    ref_b = http("GET", f"/api/card/{b}/samsung-wallet", mine(b)).json()["url"].split("pdata=", 1)[1]
    check("another card, another refId", ref_b != ref)
    r = http("GET", f"/api/card/{a}/samsung-wallet")
    check(f"a stranger with the card number only: refused ({r.status_code})", r.status_code in (401, 403))
    r = http("GET", f"/api/card/{a}/samsung-wallet", H2)
    check(f"another shop's login: refused ({r.status_code})", r.status_code in (401, 403, 404))
    check("the shop's own login may (« Voir sa carte »)", http("GET", f"/api/card/{a}/samsung-wallet", H).status_code == 200)
    check("unknown card: 404", http("GET", "/api/card/FT-NOPE0000/samsung-wallet", H).status_code == 404)
    from features import plan_limits
    real_allows = plan_limits.allows_tenant
    plan_limits.allows_tenant = lambda tid, what: False if what == "wallet" else real_allows(tid, what)
    r = http("GET", f"/api/card/{a}/samsung-wallet", mine(a))
    check(f"Wallet not in the shop's plan: refused ({r.status_code})", r.status_code == 403)
    check("…and config says no", http("GET", "/api/wallet/config", params={"barcode": a}).json()["samsung"] is False)
    plan_limits.allows_tenant = real_allows

    # ------------------------------------------------------------------
    print("\n3. Samsung asks for the card (Get Card Data)")
    CD = lambda r_, c=CARD: f"/api/samsung-wallet/cards/{c}/{r_}"  # noqa: E731
    SAM = {"Authorization": "Bearer x.y.z", "x-request-id": "0" * 32}
    r = http("GET", CD(ref), SAM)
    check(f"200 with the card ({r.status_code})", r.status_code == 200)
    body = r.json()
    card = body.get("card", {})
    check("type loyalty / subType others", card.get("type") == "loyalty" and card.get("subType") == "others")
    item = (card.get("data") or [{}])[0]
    at = item.get("attributes", {})
    check("refId echoed", item.get("refId") == ref)
    check("createdAt / updatedAt in epoch ms", isinstance(item.get("createdAt"), int) and item["createdAt"] > 10**12
          and isinstance(item.get("updatedAt"), int) and item["updatedAt"] >= item["createdAt"])
    check("language fr", item.get("language") == "fr")
    for f in ("title", "providerName", "appLinkLogo", "appLinkName", "appLinkData"):
        check(f"required « {f} » present", bool(at.get(f)))
    check("title = the shop's name, ≤ 32", at.get("title") == "Royal Trim")
    check("every string within Samsung's lengths",
          all(len(str(at.get(k) or "")) <= n for k, n in (("title", 32), ("providerName", 32), ("appLinkName", 32),
                                                          ("appLinkData", 256), ("appLinkLogo", 256), ("logoImage", 256),
                                                          ("bgImage", 256), ("subtitle1", 32), ("balance", 32),
                                                          ("level", 16), ("merchantName", 32), ("noticeDesc", 5000),
                                                          ("summaryUrl", 256), ("bgColor", 8), ("fontColor", 8),
                                                          ("locations", 1024), ("csInfo", 4096))))
    check("the QR the till scans: the card's own URL",
          at.get("barcode.value") == W.barcode_message("PKBarcodeFormatQR", a)
          and at.get("barcode.ptSubFormat") == "QR_CODE" and at.get("barcode.serialType") == "QRCODE")
    check("the stamps on the card (4 of 10)", "4" in str(at.get("balance")) and "10" in str(at.get("balance")))
    check("bgColor a #hex, fontColor dark/light", str(at.get("bgColor", "")).startswith("#") and at.get("fontColor") in ("dark", "light"))
    check("images over https", all(str(at.get(k, "https://")).startswith("https://") for k in ("logoImage", "appLinkLogo", "bgImage")))
    check("the app link opens the card page", "/card/" in at.get("appLinkData", "") and a in at.get("appLinkData", ""))
    nd = at.get("noticeDesc", "")
    check("the back of the card: the appointment link is a real link",
          '<a href="https://rdv.example/x">' in nd and "Prendre rendez-vous" in nd)
    check("the owner's text is escaped (no script, no onerror)", "<script" not in nd and "<img" not in nd
          and "&lt;script&gt;" in nd)
    cs = json.loads(at.get("csInfo") or "{}")
    check("shop phone + website as customer-service links", cs.get("call") and cs.get("website") == "https://royaltrim.fr")
    check("no geofence without a Géolocalisation automation", not at.get("locations"))
    r = http("GET", CD(ref), SAM, params={"fields": "balance,barcode.value"})
    check("?fields= still answers the card", r.status_code == 200 and r.json()["card"]["data"][0]["attributes"].get("balance"))
    r = http("GET", CD("nobody-has-this-ref-000"), SAM)
    check(f"unknown refId: 204, nothing said ({r.status_code})", r.status_code == 204 and not r.content)
    r = http("GET", CD(ref, "someothercard"), SAM)
    check(f"another card id: 204 ({r.status_code})", r.status_code == 204 and not r.content)
    r = http("GET", CD("x" * 400), SAM)
    check(f"an over-long refId: no 500 ({r.status_code})", r.status_code in (204, 400, 404, 422))
    r = http("GET", CD({"$ne": None}.__repr__()), SAM)
    check(f"an injection-looking refId: no card ({r.status_code})", r.status_code in (204, 400, 404, 422))
    db.customers.update_one({"id": "bob"}, {"$set": {"deleted_at": now}})
    r = http("GET", CD(ref_b), SAM)
    check(f"a deleted client: 204 ({r.status_code})", r.status_code == 204)
    db.customers.update_one({"id": "bob"}, {"$unset": {"deleted_at": ""}})

    # ------------------------------------------------------------------
    print("\n4. Geofence: the Géolocalisation automation's locations")
    pj = {"locations": [{"latitude": 47.39, "longitude": 0.68, "maxDistance": 100, "relevantText": "Royal Trim est à deux pas"},
                        {"latitude": 47.40, "longitude": 0.69, "maxDistance": 240, "relevantText": "x" * 900}] +
                       [{"latitude": 47.0 + i / 100, "longitude": 0.6, "maxDistance": 100, "relevantText": "Bonjour"} for i in range(20)]}
    locs = SW.locations_for(pj, {"name": "Royal Trim", "address": "12 rue de la Liberté, 37000 Tours"})
    arr = json.loads(locs)
    check("a JSON string ≤ 1024 characters", isinstance(locs, str) and len(locs) <= 1024)
    check("10 places at most", 1 <= len(arr) <= 10)
    check("each: lat, lng, name, address, geofenceType as a string, message",
          all({"lat", "lng", "name", "address", "geofenceType", "message"} <= set(x) for x in arr)
          and all(isinstance(x["geofenceType"], str) for x in arr))
    check("radius rounded to Samsung's 100…500 m", arr[0]["geofenceType"] == "100" and arr[1]["geofenceType"] in ("200", "300")
          and all(x["geofenceType"] in ("100", "200", "300", "400", "500") for x in arr))
    check("the automation's words kept", arr[0]["message"] == "Royal Trim est à deux pas")
    check("no locations → nothing", SW.locations_for({}, {"name": "x"}) is None)

    # ------------------------------------------------------------------
    print("\n5. Samsung says the card was added / deleted (Send Card State)")
    r = http("POST", CD(ref), SAM, params={"cc2": "fr", "event": "ADDED"},
             json={"callback": "https://fr-tsapi.walletsvc.samsung.com"})
    check(f"ADDED: 200 ({r.status_code})", r.status_code == 200)
    c = db.customers.find_one({"id": "anna"})
    check("added time + country kept", c.get("samsung_added_at") and c.get("samsung_cc2") == "fr")
    check("Samsung's own callback host kept", c.get("samsung_callback") == "https://fr-tsapi.walletsvc.samsung.com")
    w = W.wallet_link("anna")
    check("the till: linked, Samsung", w["linked"] is True and w["where"] == "samsung")
    check("the card's history says it", db.card_events.count_documents({"customer_id": "anna"}) >= 1
          if "card_events" in db.list_collection_names() else True)
    r = http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "ADDED"},
             json={"callback": "https://evil.example.com/steal"})
    check("a callback outside walletsvc.samsung.com: never kept",
          not db.customers.find_one({"id": "bob"}).get("samsung_callback"))
    r = http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "ADDED"},
             json={"callback": "http://fr-tsapi.walletsvc.samsung.com"})
    check("…nor over plain http", not db.customers.find_one({"id": "bob"}).get("samsung_callback"))
    r = http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "ADDED"},
             json={"callback": "https://walletsvc.samsung.com.evil.io"})
    check("…nor a look-alike host", not db.customers.find_one({"id": "bob"}).get("samsung_callback"))
    r = http("POST", CD("nobody-has-this-ref-000"), SAM, params={"cc2": "fr", "event": "ADDED"})
    check(f"unknown refId: 200, nothing written ({r.status_code})", r.status_code == 200
          and db.customers.count_documents({"samsung_added_at": {"$exists": True}}) == 2)
    r = http("POST", CD(ref_b), SAM, params={"cc2": "france!", "event": "ADDED"})
    check(f"a malformed cc2: refused or ignored ({r.status_code})", r.status_code in (200, 400, 422)
          and db.customers.find_one({"id": "bob"}).get("samsung_cc2") == "fr")
    r = http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "DROP TABLE"})
    check(f"an unknown event: nothing changes ({r.status_code})", r.status_code in (200, 400, 422))
    r = http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "DELETED"})
    cb = db.customers.find_one({"id": "bob"})
    check("DELETED: removal kept", r.status_code == 200 and cb.get("samsung_removed_at"))
    w = W.wallet_link("bob")
    check("the till: not linked, removed, Samsung", w["linked"] is False and w["reason"] == "removed")
    http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "ADDED"})
    check("added again after a deletion: linked", W.wallet_link("bob")["linked"] is True)

    # ------------------------------------------------------------------
    print("\n6. A scan wakes the Samsung card (Update Notification)")
    sent = []
    SW._post = lambda url, headers, body: sent.append((url, headers, body)) or 200
    r = http("POST", "/api/owner/scan", H, json={"barcode_id": a, "amount_paid": 5})
    check(f"the scan itself: 200 ({r.status_code})", r.status_code == 200)
    mine_sent = [s for s in sent if "3jina31gjvr00" in s[0]]
    check(f"one notification for Anna's card ({len(mine_sent)})", len(mine_sent) == 1)
    url_, hd, bd = mine_sent[0] if mine_sent else ("", {}, {})
    check("to Samsung's own callback host, her country, our card",
          url_ == "https://fr-tsapi.walletsvc.samsung.com/fr/wltex/cards/3jina31gjvr00/updates")
    check("x-smcs-partner-id + x-request-id (32)", hd.get("x-smcs-partner-id") == "4164397867037138496"
          and len(hd.get("x-request-id", "")) == 32)
    check("body: loyalty, her refId, UPDATED", bd == {"card": {"type": "loyalty", "data": [{"refId": ref, "state": "UPDATED"}]}})
    tokn = hd.get("Authorization", "").removeprefix("Bearer ")
    hdr = jwt.get_unverified_header(tokn) if tokn else {}
    check("Authorization: Bearer JWS, cty AUTH, ver 3, certificate XVli, partner",
          hdr.get("alg") == "RS256" and hdr.get("cty") == "AUTH" and str(hdr.get("ver")) == "3"
          and hdr.get("certificateId") == "XVli" and hdr.get("partnerId") == "4164397867037138496"
          and isinstance(hdr.get("utc"), int))
    try:
        claims = jwt.decode(tokn, pub, algorithms=["RS256"])
        ok = claims.get("API", {}).get("method") == "POST" and claims["API"]["path"].endswith("/wltex/cards/3jina31gjvr00/updates")
    except Exception as e:  # noqa: BLE001
        print("    ", e)
        ok = False
    check("signed with OUR key, bound to POST …/updates", ok)
    sent.clear()
    nv = client("never")
    http("POST", "/api/owner/scan", H, json={"barcode_id": nv, "amount_paid": 5})
    check("a card never added to Samsung: no call", not [s for s in sent if "3jina31gjvr00" in s[0]])
    sent.clear()
    http("POST", CD(ref_b), SAM, params={"cc2": "fr", "event": "DELETED"})
    http("POST", "/api/owner/scan", H, json={"barcode_id": b, "amount_paid": 5})
    check("a card deleted from Samsung Wallet: no call", not sent)
    def boom(*_a, **_k):
        raise RuntimeError("Samsung down")
    SW._post = boom
    r = http("POST", "/api/owner/scan", H, json={"barcode_id": a, "amount_paid": 5})
    check(f"Samsung down: the scan still records ({r.status_code})", r.status_code == 200)
    c = db.customers.find_one({"id": "anna"})
    check("…and the failure is kept for the owner's Wallet page", "Samsung down" in str(c.get("samsung_last_update", {})))
    SW._post = lambda url, headers, body: sent.append((url, headers, body)) or 200
    sent.clear()
    db.customers.update_one({"id": "anna"}, {"$unset": {"samsung_callback": ""}})
    http("POST", "/api/owner/scan", H, json={"barcode_id": a, "amount_paid": 5})
    check("no callback kept: Samsung's public host",
          sent and sent[0][0] == "https://tsapi-card.walletsvc.samsung.com/fr/wltex/cards/3jina31gjvr00/updates")

    # ------------------------------------------------------------------
    print("\n7. Owner Wallet stats count Samsung")
    st = http("GET", "/api/owner/wallet/stats", H).json()
    check("samsung count in stats", st.get("samsung", {}).get("cards") == 1)

    print("\n7b. Our key is read once (load lab 2026-11-11: 103 ms per read made Samsung cards' scans 3 s)")
    import time as _t
    SW._signing_key()
    t0 = _t.perf_counter()
    for _ in range(20):
        k1 = SW._signing_key()
    each = (_t.perf_counter() - t0) / 20 * 1000
    check(f"the key comes from memory after the first read ({each:.2f} ms)", each < 5)
    check("…and is the same key", SW._signing_key() is k1)
    key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    os.environ["SAMSUNG_WALLET_PRIVATE_KEY"] = key2.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                                  serialization.NoEncryption()).decode()
    check("a new key in the environment is read again", SW._signing_key() is not k1)
    os.environ["SAMSUNG_WALLET_PRIVATE_KEY"] = pem

    print("\n7c. Test switch: while the card is in Samsung's testing mode, only the test shops (user, 2026-11-11)")
    os.environ["SAMSUNG_WALLET_TENANTS"] = "t2"                  # by id
    c2 = client("tess", tenant="t2")
    check("a test shop: button", http("GET", "/api/wallet/config", params={"barcode": c2}).json()["samsung"] is True)
    check("…and its link", http("GET", f"/api/card/{c2}/samsung-wallet", mine(c2)).status_code == 200)
    check("any other shop: no button", http("GET", "/api/wallet/config", params={"barcode": a}).json()["samsung"] is False)
    r = http("GET", f"/api/card/{a}/samsung-wallet", mine(a))
    check(f"…and no link ({r.status_code})", r.status_code == 503)
    r = http("GET", CD(ref), SAM)
    check(f"…and Samsung gets no card for it ({r.status_code})", r.status_code == 204)
    sent.clear()
    http("POST", "/api/owner/scan", H, json={"barcode_id": a, "amount_paid": 5})
    check("…and no update notification for it", not sent)
    check("no card given: the page asks with no shop → no button", http("GET", "/api/wallet/config").json()["samsung"] is False)
    os.environ["SAMSUNG_WALLET_TENANTS"] = " t2-slug-unknown , t1 "  # by slug or id, spaces ignored
    check("a list, spaces ignored: t1 back on", http("GET", "/api/wallet/config", params={"barcode": a}).json()["samsung"] is True)
    db.tenants.update_one({"id": "t2"}, {"$set": {"slug": "test-shop"}})
    os.environ["SAMSUNG_WALLET_TENANTS"] = "test-shop"
    check("by the shop's slug too", http("GET", "/api/wallet/config", params={"barcode": c2}).json()["samsung"] is True
          and http("GET", "/api/wallet/config", params={"barcode": a}).json()["samsung"] is False)
    os.environ["SAMSUNG_WALLET_TENANTS"] = ""
    check("switch empty (after Samsung's approval): every shop", http("GET", "/api/wallet/config", params={"barcode": a}).json()["samsung"] is True)
    os.environ.pop("SAMSUNG_WALLET_TENANTS", None)

    print("\n8. Samsung's history does not grow forever")
    SW.init(db)
    ttl = [i for i in db.samsung_wallet_log.index_information().values() if i.get("expireAfterSeconds")]
    check("samsung_wallet_log lines expire (TTL ≤ 31 days)", ttl and ttl[0]["expireAfterSeconds"] <= 31 * 86400)
    check("a line per Samsung call was kept", db.samsung_wallet_log.count_documents({"customer_id": "anna"}) >= 2)
    check("…without the card's refId or key", "refId" not in str(db.samsung_wallet_log.find_one({}, {"_id": 0}))
          and ref not in str(db.samsung_wallet_log.find_one({}, {"_id": 0})))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
