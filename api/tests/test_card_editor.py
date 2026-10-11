"""
The card editor (user, 2026-10-07): Pass Designer's options in FidClic —
styles and the iOS 26 fallback, the 14 featured actions, the 8 barcodes and
their fallback, fields with the customer's own data, the live preview.

Run: cd api && /usr/local/bin/python3 tests/test_card_editor.py
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
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "barcode_id": "FT-C945EB3C", "name": "Me",
                             "visits": 1, "points": 10, "tier": "bronze", "created_at": dt.datetime.now(dt.timezone.utc)})

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


    print("Barcodes — the eight formats, each with what it can carry")
    check("EAN-13: « 20 » + the hex id in decimal + check digit",
          WP.barcode_message("PKBarcodeFormatEAN13", "FT-C945EB3C") == "2033768026201")
    check("ITF / Codabar: the 12 digits", WP.barcode_message("PKBarcodeFormatI2of5", "FT-C945EB3C") == "203376802620"
          and WP.barcode_message("PKBarcodeFormatCodabar", "FT-C945EB3C") == "203376802620")
    check("Code 39 / Code 128: the card number", WP.barcode_message("PKBarcodeFormatCode39", "FT-C945EB3C") == "FT-C945EB3C")
    check("QR / PDF417 / Aztec: the card link", WP.barcode_message("PKBarcodeFormatAztec", "FT-C945EB3C").endswith("/card/FT-C945EB3C"))
    for code in ("2033768026201", "203376802620", "A203376802620A"):
        check(f"the till reads {code} back as the card", server.barcode_from(code) == "FT-C945EB3C")
    check("…and the link and the number as before", server.barcode_from("https://x.fr/card/ft-c945eb3c") == "FT-C945EB3C")
    bars = WP.build_barcodes("PKBarcodeFormatEAN13", "PKBarcodeFormatPDF417", "FT-C945EB3C", "FT-C945EB3C")
    check("an iOS 27 format first, the chosen fallback after it (older iPhones read that one)",
          [b["format"] for b in bars] == ["PKBarcodeFormatEAN13", "PKBarcodeFormatPDF417"])
    bars = WP.build_barcodes("PKBarcodeFormatCode39", None, "FT-C945EB3C", None)
    check("no fallback chosen for an iOS 27 format → a QR after it", [b["format"] for b in bars][-1] == "PKBarcodeFormatQR")
    bars = WP.build_barcodes("PKBarcodeFormatEAN13", None, "FT-ADV2", None)
    check("a card id that cannot become digits → the QR only", [b["format"] for b in bars] == ["PKBarcodeFormatQR"])

    print("\nFeatured actions — Apple's 14")
    check("all 14 types, and only Apple's", len(WP.FEATURED_TYPES) == 14 and "viewMembership" not in WP.FEATURED_TYPES)
    acts = WP.clean_featured([{"type": "call"}, {"type": "place", "place": "I6F2B8B3D6C3E7A3"}],
                             {"phone": "02 47 00 00 00"})
    fa = WP.featured_json(acts, "FT-TEST0001")
    check("Appeler: the shop's phone as tel://+33…", fa[0] == {"identifier": "fa1-call", "type": "call", "url": "tel://+33247000000"})
    check("Itinéraire: a Maps Place ID", fa[1]["placeIdentifier"] == "I6F2B8B3D6C3E7A3")
    check("a call with no phone anywhere is left off", WP.clean_featured([{"type": "call"}], {}) == [])
    acts = WP.clean_featured([{"type": "viewOffersRewards", "url": "https://shop.fr/offres"}, {"type": "membershipBenefits"}])
    check("offers / benefits: the owner's link, or FidClic's page",
          WP.featured_target(acts[0], "FT-1", {}) == "https://shop.fr/offres"
          and WP.featured_target(acts[1], "FT-1", {}).endswith("/card/FT-1?onglet=programme"))

    print("\nThe editor: starting from the card as it is")
    st = http("GET", "/api/owner/card/pass-designer/starter", headers=H).json()
    pg = st["pass"]["posterGeneric"]
    check("a poster with the customer's name and progress as {placeholders}",
          pg["primaryFields"][0]["value"] == "{prenom}" and "{" in pg["primaryFields"][1]["value"])
    check("the offer on the front", any(f["value"] == "{offre}" for f in pg["footerFields"]))
    check("FidClic's card for iOS 26 and earlier", st["options"]["fallback"] == "fidclic")
    check("the shop's logo as the poster's logo", "primaryLogo@3x.png" in st["image_data"])

    print("\nSaving a design made in the editor")
    design = {
        "posterGeneric": {
            "headerFields": [{"key": "pts", "label": "POINTS", "value": "{points}"}],
            "primaryFields": [{"key": "who", "label": "MEMBRE", "value": "{prenom}"},
                              {"key": "prog", "label": "TAMPONS", "value": "{tampons}", "textAlignment": "PKTextAlignmentRight"}],
            "footerFields": [{"key": "shop", "value": "ROYAL TRIM"}, {"key": "off", "label": "OFFRE", "value": "{offre}"}],
            "backFields": [{"key": "hours", "label": "Horaires", "value": "Mar–Sam 9h–19h"}],
        },
        "foregroundColor": "rgb(255,255,255)", "labelColor": "rgb(212,175,55)", "backgroundColor": "rgb(20,20,20)",
        "footerBackgroundColor": "rgb(120,20,40)", "stripColor": "rgb(255,255,255)",
        "barcodes": [{"format": "PKBarcodeFormatEAN13"}],
    }
    r = http("PUT", "/api/owner/card/pass-designer", headers=H, json={
        "name": "Mon design", "pass_json": _json.dumps(design), "source": "editor",
        "options": {"fallback": "generic", "barcode_fallback": "PKBarcodeFormatCode128", "alt_text": "card"},
        "images": {"background@3x.png": png_url(2000, 3000, (10, 120, 200)).replace("image/png", "image/png"),
                   "thumbnail@3x.png": png_url(400, 400, (0, 0, 0))},
        "featured_actions": [{"type": "viewOffersRewards"}, {"type": "bookAppointment", "url": "https://planity.com/x"}]})
    check(f"saved ({r.status_code})", r.status_code == 200 and r.json().get("source") == "editor")
    tdoc = db.card_templates.find_one({"tenant_id": "t1"})["pass_designer"]
    bg = next(i for i in tdoc["images"] if i["name"] == "background@3x.png")["data"]
    check("a big upload is scaled to Wallet's 1035×1515", _Img.open(_io.BytesIO(base64.b64decode(bg.split(",")[1]))).size == (1010, 1515))
    check("the editor's buttons are the card's", [a["type"] for a in db.card_templates.find_one({"tenant_id": "t1"})["featured_actions"]]
          == ["viewOffersRewards", "bookAppointment"])
    p = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    pg = p["posterGeneric"]
    check("each customer's own values", pg["primaryFields"][0]["value"] == "Marie")
    # points OR tampons, by the programme (user, 2026-10-12): a tampons
    # programme leaves the design's {points} field out
    check("tampons programme: the design's POINTS field is left out", pg["headerFields"] == [])
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "points_visit"}})
    pgp = WP.build_pass_json(WP._card_payload("FT-TEST0001"))["posterGeneric"]
    check("points programme: the balance, notifying when it changes, and no tampons",
          pgp["headerFields"][0]["value"] == "70" and pgp["headerFields"][0].get("changeMessage")
          and not any(f["key"] in ("prog", "jauge", "stamps") for f in pgp["primaryFields"]))
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"programme": ""}})
    check("no campaign running → no empty « OFFRE » row", [f["key"] for f in pg["footerFields"]] == ["shop"])
    check("the design's back, then FidClic's (offer that notifies, links…)",
          pg["backFields"][0]["key"] == "hours" and any(f["key"] == "offer" and f.get("changeMessage") for f in pg["backFields"]))
    check("iOS 26: a generic made from the poster — first primary big, the rest under it, footer last",
          "storeCard" not in p and p["generic"]["primaryFields"][0]["key"] == "who"
          and [f["key"] for f in p["generic"]["secondaryFields"]] == ["prog"]
          and [f["key"] for f in p["generic"]["auxiliaryFields"]] == ["shop"])
    check("colours apply to both, footer and strip colours too",
          p["backgroundColor"] == "rgb(20,20,20)" and p["footerBackgroundColor"] == "rgb(120,20,40)" and p["stripColor"] == "rgb(255,255,255)")
    check("EAN-13 cannot carry « FT-TEST0001 » → the Code 128 fallback alone",
          [b["format"] for b in p["barcodes"]] == ["PKBarcodeFormatCode128"] and p["barcodes"][0]["message"] == "FT-TEST0001")
    p2 = WP.build_pass_json(WP._card_payload("FT-C945EB3C"))
    check("a real card: EAN-13, then the Code 128 fallback, each with its own message",
          [b["format"] for b in p2["barcodes"]] == ["PKBarcodeFormatEAN13", "PKBarcodeFormatCode128"]
          and p2["barcodes"][0]["message"] == "2033768026201" and p2["barcodes"][1]["message"] == "FT-C945EB3C"
          and p2["barcodes"][0]["altText"] == "FT-C945EB3C")
    check("textAlignment kept where Apple allows it", pg["primaryFields"][1].get("textAlignment") is None)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"offer_box_text": "-20% ce week-end", "show_offer_box": True}})
    pg = WP.build_pass_json(WP._card_payload("FT-TEST0001"))["posterGeneric"]
    off = next((f for f in pg["footerFields"] if f["key"] == "off"), None)
    check("a campaign running → its offer on the front", bool(off) and "20" in str(off["value"]) and "changeMessage" not in off)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"offer_box_text": ""}})
    z = _zip.ZipFile(_io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    names = set(z.namelist())
    check("@3x upload → @2x and 1x made", {"background@3x.png", "background@2x.png", "background.png",
                                            "thumbnail@2x.png", "thumbnail.png", "icon.png", "logo.png"} <= names)
    check("no strip: the generic fallback has none", "strip.png" not in names)

    print("\nThe editor's live preview — unsaved changes, the real engine")
    draft = _json.loads(_json.dumps(design))
    draft["posterGeneric"]["primaryFields"][0]["label"] = "CLIENT"
    pv = http("POST", "/api/owner/wallet/preview", headers=H, json={"card": {"featured_actions": [{"type": "shop", "url": "https://shop.fr"}]},
              "design": {"pass": draft, "images": {"background@3x.png": "saved"}, "options": {"fallback": "storeCard"}}}).json()
    pj = pv.get("pass_json") or {}
    check("the unsaved label is in the preview", pj.get("posterGeneric", {}).get("primaryFields", [{}])[0].get("label") == "CLIENT")
    check("…with the unsaved fallback style", pv.get("styles") == ["posterGeneric", "storeCard"])
    check("…the saved background, as a light JPEG", (pv.get("images") or {}).get("background", "").startswith("data:image/jpeg"))
    check("…and the unsaved button", [a["type"] for a in pv.get("actions") or []] == ["shop"])
    saved = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("the saved design is untouched by the preview", saved["posterGeneric"]["primaryFields"][0]["label"] == "MEMBRE"
          and "generic" in saved)
    full = http("GET", "/api/owner/card/pass-designer?full=1", headers=H).json()
    check("the editor reopens it: pass, options, images", full["options"]["fallback"] == "generic"
          and "background@3x.png" in full["image_data"] and full["pass"]["posterGeneric"])
    r = http("PUT", "/api/owner/card/pass-designer", headers=H, json={
        "name": "Mon design", "pass_json": _json.dumps(design), "source": "editor", "options": {"fallback": "fidclic"},
        "images": {"background@3x.png": "saved"}})
    tdoc = db.card_templates.find_one({"tenant_id": "t1"})["pass_designer"]
    check("saving again keeps an image sent as « saved »", [i["name"] for i in tdoc["images"]] == ["background@3x.png"])
    p = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("fallback « FidClic » → the card as before, in the shop's colour",
          "storeCard" in p and "generic" not in p and p["backgroundColor"] != "rgb(20,20,20)" and p.get("logoText"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
