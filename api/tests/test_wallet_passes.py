"""
Wallet passes — builds a real, signed .pkpass against a throwaway self-signed
certificate chain (so no Apple secret is needed to run this), then checks the
bundle Apple's Wallet would receive: manifest hashes, pass.json contents that
mirror the onboarding step-3 design, and the PassKit web-service auth.

    cd api && python3 tests/test_wallet_passes.py
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
        passed += cond; failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def status(fn, *a, **k):
        try:
            r = fn(*a, **k)
            return getattr(r, "status_code", 200), r
        except HTTPException as e:
            return e.status_code, None

    check("config: apple on, google off", WP.wallet_config() == {"apple": True, "google": False})

    resp = WP.download_apple_pass("FT-TEST0001")
    check("pkpass response mime", resp.media_type == "application/vnd.apple.pkpass" and "attachment" in resp.headers["content-disposition"])
    data = WP.build_pkpass(WP._card_payload("FT-TEST0001"))
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    check("bundle has pass.json/manifest/signature/icon/logo", {"pass.json", "manifest.json", "signature", "icon.png", "logo.png"} <= names)
    check("retina variants present", {"icon@2x.png", "icon@3x.png", "logo@2x.png"} <= names)
    # Default template: no photo but the meter is on, so a brand-gradient strip
    # is generated and the pass uses the banner layout.
    check("strip generated for the meter even without a photo", "strip.png" in names)
    manifest = json.loads(z.read("manifest.json"))
    check("manifest sha1 matches every file", all(manifest[n] == hashlib.sha1(z.read(n)).hexdigest() for n in names - {"manifest.json", "signature"}))
    sig = z.read("signature")
    check("signature is DER PKCS#7", sig[:1] == b"\x30" and len(sig) > 500)
    pj = json.loads(z.read("pass.json"))
    check("storeCard + ids", pj["formatVersion"] == 1 and pj["passTypeIdentifier"] == "pass.com.fidclic.test" and pj["teamIdentifier"] == "TEAM123456" and "storeCard" in pj)
    check("serial = barcode; QR altText", pj["serialNumber"] == "FT-TEST0001" and pj["barcodes"][0]["format"] == "PKBarcodeFormatQR" and pj["barcodes"][0]["altText"] == "FT-TEST0001")
    check("design → colours (black surface, light ink)", pj["backgroundColor"] == "rgb(0, 0, 0)" and pj["foregroundColor"] == "rgb(244, 243, 240)")
    check("card_name → logoText", pj["logoText"] == "ROYAL TRIM")
    sc = pj["storeCard"]
    check("points in the header (nothing over the strip)", sc["headerFields"][0]["value"] == 70)
    check("primaryFields empty with a strip", sc["primaryFields"] == [])
    sec = {f["key"]: f["value"] for f in sc["secondaryFields"]}
    check("member/tier/visits/stamps fields", sec == {"member": "Marie", "tier": "Or", "visits": 7, "stamps": "7 / 10"})
    check("reward text", sc["auxiliaryFields"][0]["value"] == "Encore 3 tampons · Une coupe offerte")
    check("tagline on the back", any(f.get("value") == "Coupe • Barbe • Soin" for f in sc["backFields"]))
    check("webServiceURL + auth token ≥16", pj["webServiceURL"].endswith("/api/passes") and len(pj["authenticationToken"]) >= 16)
    tok = pj["authenticationToken"]

    # ---- PassKit web service --------------------------------------------
    hdr = "ApplePass " + tok
    reg = WP.Registration(pushToken="abc")
    check("register → 201", status(WP.register_device, "dev1", "pass.com.fidclic.test", "FT-TEST0001", reg, hdr)[0] == 201)
    check("re-register → 200", status(WP.register_device, "dev1", "pass.com.fidclic.test", "FT-TEST0001", reg, hdr)[0] == 200)
    check("bad token → 401", status(WP.register_device, "dev1", "pass.com.fidclic.test", "FT-TEST0001", reg, "ApplePass nope")[0] == 401)
    st, r = status(WP.serials_for_device, "dev1", "pass.com.fidclic.test", None)
    check("serials for device", st == 200 and r["serialNumbers"] == ["FT-TEST0001"])
    st, r = status(WP.serials_for_device, "dev1", "pass.com.fidclic.test", str(int(time.time()) + 60))
    check("nothing changed since → 204", st == 204)
    check("latest pass via web service (auth ok)", status(WP.latest_pass, "pass.com.fidclic.test", "FT-TEST0001", hdr)[0] == 200)
    check("latest pass bad auth → 401", status(WP.latest_pass, "pass.com.fidclic.test", "FT-TEST0001", "ApplePass x")[0] == 401)
    check("unregister → 200", status(WP.unregister_device, "dev1", "pass.com.fidclic.test", "FT-TEST0001", hdr)[0] == 200)
    check("no registrations → 204", status(WP.serials_for_device, "dev1", "pass.com.fidclic.test", None)[0] == 204)

    # ---- banner (strip) layout ------------------------------------------
    # 1×1 pixel JPEG stand-in for the merchant's artwork.
    banner = ("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
              "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
              "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"hero_image_url": banner, "hero_mode": "image"}})
    pj2 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    sc2 = pj2["storeCard"]
    check("banner: nothing drawn over the artwork (primaryFields empty)", sc2["primaryFields"] == [])
    check("banner: points move to the header", [f["key"] for f in sc2["headerFields"]] == ["points"]
          and sc2["headerFields"][0]["value"] == 70)
    check("banner: statut joins the secondary row", "tier" in [f["key"] for f in sc2["secondaryFields"]])
    data2 = WP.build_pkpass(WP._card_payload("FT-TEST0001"))
    z2 = zipfile.ZipFile(io.BytesIO(data2))
    check("banner: strip.png at 1x/2x/3x", {"strip.png", "strip@2x.png", "strip@3x.png"} <= set(z2.namelist()))
    man2 = json.loads(z2.read("manifest.json"))
    check("banner: manifest still complete",
          all(man2[n] == hashlib.sha1(z2.read(n)).hexdigest() for n in set(z2.namelist()) - {"manifest.json", "signature"}))
    from PIL import Image as _I
    w, h = _I.open(io.BytesIO(z2.read("strip.png"))).size
    check("banner: strip is Apple's 375x144 at 1x", (w, h) == (375, 144))
    w3, h3 = _I.open(io.BytesIO(z2.read("strip@3x.png"))).size
    check("banner: strip@3x is 1125x432", (w3, h3) == (1125, 432))
    # ---- meter off + no photo → the classic layout (big number) -----------
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"hero_image_url": "", "hero_mode": "none",
                                                               "show_meter": False}})
    pj3 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("meter off, no photo: classic layout (points primary, statut header)",
          pj3["storeCard"]["primaryFields"][0]["key"] == "points"
          and pj3["storeCard"]["headerFields"][0]["key"] == "tier")
    z3 = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    check("meter off, no photo: no strip at all", "strip.png" not in z3.namelist())

    # ---- the meter is really painted into the strip ------------------------
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"show_meter": True}})
    from PIL import Image as _IM
    def strip_of(visits):
        db.customers.update_one({"id": "c1"}, {"$set": {"visits": visits}})
        zz = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
        return _IM.open(io.BytesIO(zz.read("strip@3x.png"))).convert("RGB")
    im2, im9 = strip_of(2), strip_of(9)
    row = 432 - 50          # inside the meter band
    def filled(im):         # count pixels close to the brand gold
        return sum(1 for x in range(0, 1125, 3)
                   for px in [im.getpixel((x, row))]
                   if abs(px[0] - 212) < 40 and abs(px[1] - 175) < 40 and abs(px[2] - 55) < 45)
    f2, f9 = filled(im2), filled(im9)
    check(f"meter fills with progress (2 stamps: {f2} px < 9 stamps: {f9} px)", 0 < f2 < f9)
    db.customers.update_one({"id": "c1"}, {"$set": {"visits": 7}})

    # ---- unconfigured is a clean 503, never a 500 ------------------------
    os.environ["APPLE_PASS_KEY_B64"] = ""
    check("unconfigured → 503", status(WP.download_apple_pass, "FT-TEST0001")[0] == 503)
    check("google unconfigured → 503", status(WP.google_wallet_link, "FT-TEST0001")[0] == 503)
    check("unknown card → 404", status(WP.serials_for_device, "nobody", "x", None)[0] == 204 and status(lambda: WP._card_payload("FT-NOPE"))[0] == 404)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
