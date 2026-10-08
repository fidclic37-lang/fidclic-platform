"""
« Logo rond » and the Google Wallet design (user, 2026-10-08): the logo cut to
a disc with an optional ring, on every Apple logo; Google's own card — colour,
round or wide logo, hero, rows, barcode, details, notifications — and its
live preview.

Run: cd api && /usr/local/bin/python3 tests/test_google_design.py
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



    def png_of(url_or_bytes):
        raw = url_or_bytes if isinstance(url_or_bytes, bytes) else base64.b64decode(url_or_bytes.split(",")[1])
        return _Img.open(_io.BytesIO(raw)).convert("RGBA")

    def square_png(color=(20, 80, 160), size=200, transparent=False):
        im = _Img.new("RGBA", (size, size), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
        from PIL import ImageDraw
        ImageDraw.Draw(im).rectangle((40, 40, size - 40, size - 40), fill=color + (255,))
        b = _io.BytesIO(); im.save(b, "PNG"); return b.getvalue()

    print("Logo rond")
    disc = png_of(WP.round_logo(square_png()))
    check("the corners are transparent", disc.getpixel((2, 2))[3] == 0 and disc.getpixel((disc.width - 3, 2))[3] == 0)
    check("the middle is the logo", disc.getpixel((disc.width // 2, disc.height // 2))[3] == 255)
    ringed = png_of(WP.round_logo(square_png(transparent=True), "#D4AF37"))
    edge = ringed.getpixel((ringed.width // 2, 6))
    check("a ring in the chosen colour", abs(edge[0] - 212) < 25 and abs(edge[1] - 175) < 25 and edge[3] > 200)
    inside = ringed.getpixel((ringed.width // 2, 60))
    check("a logo with transparency sits on a white disc", inside[:3] == (255, 255, 255) and inside[3] == 255)

    logo_url = "data:image/png;base64," + base64.b64encode(square_png()).decode()
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"logo_url": logo_url, "logo_round": True, "logo_ring": True,
                                                                 "logo_ring_color": "#D4AF37"}})
    z = _zip.ZipFile(_io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    for name in ("logo@3x.png", "primaryLogo@3x.png"):
        im = _Img.open(_io.BytesIO(z.read(name))).convert("RGBA")
        check(f"{name}: round (transparent corners), square", im.getpixel((1, 1))[3] == 0 and im.width == im.height)
    icon = _Img.open(_io.BytesIO(z.read("icon@3x.png"))).convert("RGBA")
    check("the notification icon keeps the logo as it is", icon.getpixel((1, 1))[3] == 255)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"logo_round": False}})
    z = _zip.ZipFile(_io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    im = _Img.open(_io.BytesIO(z.read("logo@3x.png"))).convert("RGBA")
    check("toggle off → the logo as uploaded", im.getpixel((1, 1))[3] == 255)

    print("\nGoogle Wallet — the design")
    gd = WP.clean_google_design({"bg_color": "#691B1B", "program_name": "BLOO JOB", "logo": "wide",
                                 "rows": [["stamps", "points"], ["tier", "offer", "nope"], ["name"], ["card"]],
                                 "barcode": "EAN_13", "alt_text": "none", "hero": "photo",
                                 "details": [{"label": "Horaires", "value": "9h–19h, {prenom}"}, {"label": "", "value": "x"}],
                                 "notify": {"campaign": False}})
    check("rows: three at most, known values only", gd["rows"] == [["stamps", "points"], ["tier", "offer"], ["name"]])
    check("a wide logo / a photo hero without the image fall back", gd["logo"] == "round" and gd["hero"] == "fidclic")
    check("empty detail rows dropped; notifications default on", len(gd["details"]) == 1
          and gd["notify"] == {"campaign": False, "reward": True, "birthday": True})

    hero_url = "data:image/png;base64," + base64.b64encode(square_png((200, 120, 30), 600)).decode()
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"logo_round": True, "logo_ring": False, "google_design": {
        "bg_color": "#691B1B", "program_name": "BLOO JOB", "rows": [["stamps", "points"], ["tier"]],
        "barcode": "CODE_128", "alt_text": "card", "hero": "photo", "hero_image": hero_url,
        "details": [{"label": "Horaires", "value": "Ouvert pour vous, {prenom}"}], "notify": {"campaign": False}}}})
    payload = WP._card_payload("FT-TEST0001")
    cls, obj = WP._gw_class(payload), WP._gw_object(payload)
    check("the class: colour, name, our logo link (Google needs a public one)",
          cls["hexBackgroundColor"] == "#691B1B" and cls["programName"] == "BLOO JOB"
          and "/api/wallet/google/t1/logo.png?v=" in cls["programLogo"]["sourceUri"]["uri"])
    rows = cls["classTemplateInfo"]["cardTemplateOverride"]["cardRowTemplateInfos"]
    check("the rows: two values, then one",
          rows[0]["twoItems"]["startItem"]["firstValue"]["fields"][0]["fieldPath"] == "object.textModulesData['stamps']"
          and rows[1]["oneItem"]["item"]["firstValue"]["fields"][0]["fieldPath"] == "object.textModulesData['tier']")
    mods = {m["id"]: m for m in obj["textModulesData"]}
    check("each row value is in the card", "stamps" in mods and "tier" in mods and mods["tier"]["body"])
    check("the owner's detail row, with the customer's first name", mods["detail0"]["body"] == "Ouvert pour vous, Marie")
    check("the barcode: Code 128 with the card number, number under it",
          obj["barcode"] == {"type": "CODE_128", "value": "FT-TEST0001", "alternateText": "FT-TEST0001"})
    check("the hero: the owner's photo, served by us", "/api/wallet/google/t1/hero.png" in obj["heroImage"]["sourceUri"]["uri"])

    r = http("GET", "/api/wallet/google/t1/logo.png")
    lg = _Img.open(_io.BytesIO(r.content)).convert("RGBA")
    check(f"the logo Google fetches: a 660 px disc ({r.status_code})", r.status_code == 200 and lg.size == (660, 660)
          and lg.getpixel((2, 2))[3] == 0)
    r = http("GET", "/api/wallet/google/t1/hero.png")
    check(f"the hero Google fetches: 1032 × 336 ({r.status_code})",
          r.status_code == 200 and _Img.open(_io.BytesIO(r.content)).size == (1032, 336))
    check("an unknown image is a 404", http("GET", "/api/wallet/google/t1/secret.png").status_code == 404)

    print("\nGoogle Wallet — the live preview")
    pv = http("POST", "/api/owner/wallet/google-preview", headers=H, json={"card": {
        "google_design": {"bg_color": "#112233", "rows": [["name", "card"]], "barcode": "QR_CODE", "hero": "none"},
        "logo_round": True, "logo_ring": True, "logo_ring_color": "#FF0000"}}).json()
    check("the unsaved colour and rows", pv["class"]["hexBackgroundColor"] == "#112233"
          and "twoItems" in pv["class"]["classTemplateInfo"]["cardTemplateOverride"]["cardRowTemplateInfos"][0])
    check("no hero when « Aucune »", "heroImage" not in pv["object"] and pv["images"]["hero"] is None)
    ring_px = png_of(pv["images"]["logo"]).getpixel((330, 8))
    check("the logo with the unsaved red ring", ring_px[0] > 200 and ring_px[1] < 60)
    check("the field and code names for the editor", pv["row_fields"]["tier"] == "Statut" and pv["codes"]["EAN_13"] == "EAN-13")
    saved = WP._gw_class(WP._card_payload("FT-TEST0001"))
    check("the saved design is untouched by the preview", saved["hexBackgroundColor"] == "#691B1B")

    print("\nSaving from the page")
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"logo_round": True, "logo_ring_color": "red"})
    check(f"a bad ring colour is refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"google_design": {"rows": [["visits"]], "barcode": "AZTEC"}})
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check(f"the Google design is cleaned and saved ({r.status_code})", r.status_code == 200
          and tpl["google_design"]["rows"] == [["visits"]] and tpl["google_design"]["barcode"] == "AZTEC")
    adv = http("GET", "/api/owner/card/settings", headers=H).json()["advanced"]
    check("the page reads it back", adv["google_design"]["barcode"] == "AZTEC" and adv["logo_round"] is True)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
