"""
Apple « Pass Designer » templates as the card's design (user, 2026-10-06):
import the .pkpasstemplate, and every customer's pass is that design filled
with their own data, signed and updated by FidClic.

Run: cd api && /usr/local/bin/python3 tests/test_pass_designer.py
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
import zipfile

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---- throwaway cert chain (never Apple's) ----------------------------------
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _selfsigned(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=30)).sign(key, hashes.SHA256()))
    return key, cert


key, cert = _selfsigned("Pass Type ID: pass.com.fidclic.test")
_, wwdr = _selfsigned("Fake WWDR")
os.environ.update({
    "APPLE_PASS_TYPE_ID": "pass.com.fidclic.test",
    "APPLE_TEAM_ID": "TEAM123456",
    "APPLE_PASS_CERT_B64": base64.b64encode(cert.public_bytes(serialization.Encoding.PEM)).decode(),
    "APPLE_PASS_KEY_B64": base64.b64encode(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
    "APPLE_WWDR_B64": base64.b64encode(wwdr.public_bytes(serialization.Encoding.PEM)).decode(),
    "PASS_AUTH_SECRET": "test-secret",
    "DISABLE_SEED": "1",
})

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from features import wallet_passes as WP

    db = server.db

    # a merchant who finished onboarding step 3 with the black/gold design
    db.tenants.insert_one({"id": "t1", "slug": "royal-trim", "name": "Royal Trim SARL", "address": "12 rue Nationale, 37000 Tours"})
    logo_png = base64.b64encode(bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000101"
        "0d6d6b5e0000000049454e44ae426082")).decode()
    db.card_templates.insert_one({
        "tenant_id": "t1", "layout_style": "wallet", "surface_color": "#000000", "brand_color": "#D4AF37",
        "card_name": "ROYAL TRIM", "tagline": "Coupe • Barbe • Soin", "logo_url": "data:image/png;base64," + logo_png,
        "reward_threshold_stamps": 10, "reward_description": "Une coupe offerte", "hero_mode": "none",
        "brand_fields": {"card_name": "ROYAL TRIM"},
    })
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-TEST0001", "name": "Marie Dupont",
                             "visits": 7, "points": 70, "tier": "gold", "created_at": dt.datetime.now(dt.timezone.utc)})

    passed = failed = 0

    def check(label, cond):
        global passed, failed
        cond = bool(cond)
        passed += cond; failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def status(fn, *a, **k):
        try:
            r = fn(*a, **k)
            return getattr(r, "status_code", 200), r
        except HTTPException as e:
            return e.status_code, None


    import io as _io, json as _json, zipfile as _zip, asyncio, httpx
    import auth as _auth
    from PIL import Image as _Img

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def png_url(w, h, rgb):
        b = _io.BytesIO(); _Img.new("RGB", (w, h), rgb).save(b, "PNG")
        return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()

    TOK = _auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + TOK}
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})

    # what Pass Designer saves (the user's SOE_PASS, same structure, other data)
    template = {
        "backgroundColor": "rgb(0,229,136)", "foregroundColor": "rgb(186,244,255)", "labelColor": "rgb(0,220,255)",
        "formatVersion": 1, "organizationName": "", "passTypeIdentifier": "pass.", "serialNumber": "",
        "teamIdentifier": "", "description": "", "suppressHeaderDarkening": False, "useAutomaticColors": False,
        "barcodes": [{"_id": "B1", "format": "PKBarcodeFormatPDF417", "message": "1234", "messageEncoding": "iso-8859-1"}],
        "featuredActions": [{"_id": "A1", "identifier": "offer_new", "type": "viewOffersRewards", "url": "https://"},
                            {"_id": "A2", "identifier": "rdv", "type": "bookAppointment", "url": "https://"}],
        "posterGeneric": {
            "headerFields": [{"_id": "H1", "key": "CUST_ID", "label": "MEMBRE", "value": "1234"}],
            "primaryFields": [{"_id": "P1", "key": "CUST_NAME", "value": "SPIRIT of ECSTACY"},
                              {"_id": "P2", "key": "", "label": "LOVES", "value": "ROLLS ROYCE"},
                              {"_id": "P3", "key": "HELLO", "label": "SALUT", "value": "Bonjour {prenom} !"}],
            "footerFields": [{"_id": "F1", "key": "", "value": "ROYALTY LIVES HERE"}, {"_id": "F2", "key": "", "value": ""}],
            "backFields": [{"_id": "K1", "key": "jhvkhv", "value": ""}, {"_id": "K2", "key": "POINTS", "label": "Points", "value": "0"}],
        },
    }
    print("\nImport")
    r = http("PUT", "/api/owner/card/pass-designer", headers=H, json={
        "name": "SOE_PASS", "pass_json": _json.dumps(template),
        "images": {"background@2x.png": png_url(690, 1010, (200, 120, 30)), "primaryLogo@2x.png": png_url(200, 200, (255, 255, 255)),
                   "evil.sh": "data:text/plain;base64,AAAA"}})
    check(f"the template is imported ({r.status_code})", r.status_code == 200 and r.json().get("active") is True
          and r.json().get("style") == "posterGeneric")
    tdoc = db.card_templates.find_one({"tenant_id": "t1"})
    check("only Wallet image names are kept",
          {i["name"] for i in tdoc["pass_designer"]["images"]} == {"background@2x.png", "primaryLogo@2x.png"})
    check("its featured actions become the card's, a link-less booking kept for the owner to fill",
          [(a["type"], a.get("url")) for a in tdoc.get("featured_actions") or []] == [("viewOffersRewards", ""), ("bookAppointment", "")])
    bad = http("PUT", "/api/owner/card/pass-designer", headers=H, json={"pass_json": "{not json"})
    check("an unreadable pass.json is refused", bad.status_code == 400)

    print("\nEach customer's pass is the design, filled with their own data")
    p = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    pg = p.get("posterGeneric") or {}
    flat = _json.dumps(p)
    check("the template's style, our storeCard behind it for iOS 26", bool(pg) and "storeCard" in p and "generic" not in p)
    check("no Pass Designer `_id` left", '"_id"' not in flat)
    head_f = pg["headerFields"][0]
    check("CUST_ID → the customer's card number", head_f["value"] == "FT-TEST0001" and head_f["label"] == "MEMBRE")
    prim = {f["key"]: f for f in pg["primaryFields"]}
    check("CUST_NAME → the customer's name", prim["CUST_NAME"]["value"] == "Marie Dupont")
    check("the business's own text stays as designed", any(f.get("value") == "ROLLS ROYCE" for f in pg["primaryFields"]))
    check("a {prenom} placeholder is filled", prim["HELLO"]["value"] == "Bonjour Marie !")
    check("every field keyed, the empty footer row dropped",
          all(f.get("key") for g in pg.values() if isinstance(g, list) for f in g)
          and [f["value"] for f in pg["footerFields"]] == ["ROYALTY LIVES HERE"])
    back = {f["key"]: f for f in pg["backFields"]}
    # points OR tampons, by the programme (user, 2026-10-12)
    check("tampons programme: the template's POINTS row is left out", "POINTS" not in back)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "points_visit"}})
    _bp = {f["key"]: f for f in WP.build_pass_json(WP._card_payload("FT-TEST0001"))["posterGeneric"]["backFields"]}
    check("points programme: POINTS → the balance, with a changeMessage (it notifies)",
          _bp["POINTS"]["value"] == 70 and "changeMessage" in _bp["POINTS"])
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"programme": ""}})
    check("our back follows: « Offre du moment » with its changeMessage (campaigns notify)",
          "offer" in back and back["offer"].get("changeMessage") == "%@" and "jhvkhv" not in back)
    check("the designer's text colours; the shop's background stays for the iOS 26 card",
          p["labelColor"] == "rgb(0,220,255)" and p["backgroundColor"] != "rgb(0,229,136)")
    check("FidClic's identity and web service", p["serialNumber"] == "FT-TEST0001" and p["passTypeIdentifier"] == "pass.com.fidclic.test"
          and p["webServiceURL"].endswith("/api/passes") and len(p["authenticationToken"]) >= 16 and p["organizationName"])
    check("the template's barcode format, carrying the card's message",
          p["barcodes"][0]["format"] == "PKBarcodeFormatPDF417" and p["barcodes"][0]["message"].endswith("/card/FT-TEST0001"))
    check("iOS 26 and earlier keep FidClic's card, with the same back",
          any(f["key"] == "member" for f in p["storeCard"]["secondaryFields"]) and p["storeCard"]["backFields"] == pg["backFields"])
    check("featured actions: the link-less booking is left off while the shop has no website",
          [a["type"] for a in p["featuredActions"]] == ["viewOffersRewards"])
    check("featured actions wired to our counter",
          p["featuredActions"][0]["type"] == "viewOffersRewards" and "/api/card/FT-TEST0001/action/" in p["featuredActions"][0]["url"])

    print("\nThe signed pass")
    z = _zip.ZipFile(_io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    names = set(z.namelist())
    check("the template's images, a 1x for each, and what Wallet requires",
          {"background@2x.png", "background.png", "primaryLogo@2x.png", "primaryLogo.png", "icon.png", "logo.png",
           "strip.png", "pass.json", "manifest.json", "signature"} <= names)
    check("the designer's background as designed", _Img.open(_io.BytesIO(z.read("background@2x.png"))).getpixel((10, 10)) == (200, 120, 30))
    man = _json.loads(z.read("manifest.json"))
    check("manifest covers every file", all(n in man for n in names - {"manifest.json", "signature"}))

    print("\nA template compressed in Finder (.zip)")
    zb = _io.BytesIO()
    with _zip.ZipFile(zb, "w") as zz:
        zz.writestr("SOE_ZIP.pkpasstemplate/pass.json", _json.dumps(template))
        zz.writestr("SOE_ZIP.pkpasstemplate/background@2x.png", base64.b64decode(png_url(690, 1010, (10, 200, 90)).split(",")[1]))
        zz.writestr("__MACOSX/SOE_ZIP.pkpasstemplate/._pass.json", b"junk")
    r = http("PUT", "/api/owner/card/pass-designer", headers=H, json={"zip": base64.b64encode(zb.getvalue()).decode()})
    check(f"imported from the .zip, named after the template ({r.status_code})",
          r.status_code == 200 and r.json().get("name") == "SOE_ZIP" and r.json().get("images") == ["background@2x.png"])
    r = http("PUT", "/api/owner/card/pass-designer", headers=H, json={"zip": base64.b64encode(b"not a zip").decode()})
    check("a file that is not a zip is refused", r.status_code == 400)

    print("\nThe owner's preview and going back")
    pv = http("POST", "/api/owner/wallet/preview", headers=H, json={"card": {}}).json()
    check("the preview draws the template's poster",
          pv.get("poster") and pv["poster"]["primaryFields"][0]["key"] == "CUST_NAME"
          and pv["poster"]["background"].startswith("data:image/png") and pv["colors"]["labelColor"] == "rgb(0,220,255)")
    check("…and the iOS 26 card as before: strip, shop colour", bool(pv.get("strip")) and pv["colors"]["backgroundColor"] != "rgb(0,229,136)")
    st = http("GET", "/api/owner/card/pass-designer", headers=H).json()
    check("status says which template", st.get("active") is True and st.get("name") == "SOE_ZIP")
    http("DELETE", "/api/owner/card/pass-designer", headers=H)
    p2 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("removing it brings the FidClic design back", "CUST_NAME" not in _json.dumps(p2))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
