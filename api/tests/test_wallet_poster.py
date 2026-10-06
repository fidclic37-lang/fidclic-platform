"""
iOS 27 Poster Generic + featured actions (WWDC26, user 2026-10-06): the pass
carries `posterGeneric` next to the classic `storeCard`, a full-bleed
background with the meter, the primary logo, and up to two tiles under it.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_poster.py
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


    import io as _io, json as _json, zipfile as _zip, asyncio, httpx
    import auth as _auth
    from PIL import Image as _Img
    from models import TokenData

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def pj():
        return WP.build_pass_json(WP._card_payload("FT-TEST0001"))

    def bundle():
        return _zip.ZipFile(_io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))

    print("\nPoster Generic (iOS 27), on by default")
    p = pj()
    pg = p.get("posterGeneric") or {}
    check("posterGeneric is in pass.json", bool(pg))
    check("…next to the storeCard, the card iOS 26 and earlier keep showing (no generic)",
          "storeCard" in p and "generic" not in p)
    check("iOS 26 keeps the card as before: progress and member in the secondary row",
          any(f["key"] == "member" for f in p["storeCard"]["secondaryFields"])
          and any(f["key"] in ("stamps", "reward") for f in p["storeCard"]["secondaryFields"]))
    check("labelled like Apple's sample: MEMBRE / Marie first", pg["primaryFields"][0]["key"] == "member"
          and pg["primaryFields"][0]["value"] == "Marie" and bool(pg["primaryFields"][0].get("label")))
    check("only the logo on top: no logoText, the shop's name is the footer",
          "logoText" not in p and pg["footerFields"][0]["value"] == "ROYAL TRIM")
    check("the offer is not on the poster's face (it stays on the back)",
          all(f["key"] != "offer_title" for f in pg["primaryFields"]))
    check("at most 4 primary fields, 1 header, 1 footer",
          len(pg["primaryFields"]) <= 4 and len(pg["headerFields"]) <= 1 and len(pg["footerFields"]) == 1)
    check("progress in the primary fields, with its changeMessage (notifications)",
          any(f["key"] == "stamps" and "changeMessage" in f for f in pg["primaryFields"]))
    check("the back is the same back (offer with changeMessage, links…)",
          [f["key"] for f in pg["backFields"]] == [f["key"] for f in p["storeCard"]["backFields"]])
    z = bundle()
    names = set(z.namelist())
    check("background.png at 1x/2x/3x + primaryLogo (iOS 27)",
          {"background.png", "background@2x.png", "background@3x.png", "primaryLogo.png"} <= names)
    check("the strip and logo stay for the iOS 26 storeCard", {"strip.png", "strip@2x.png", "logo.png"} <= names)
    check("background is Apple's 345×505 pt (1035×1515 at 3x)",
          _Img.open(_io.BytesIO(z.read("background@3x.png"))).size == (1035, 1515)
          and _Img.open(_io.BytesIO(z.read("background.png"))).size == (345, 505))
    man = _json.loads(z.read("manifest.json"))
    check("manifest covers the new images", all(n in man for n in ("background.png", "primaryLogo.png")))

    def gold_pixels(stamps):
        db.customers.update_one({"id": "c1"}, {"$set": {"visits": stamps}})
        im = _Img.open(_io.BytesIO(bundle().read("background@3x.png"))).convert("RGB")
        y = int(1515 * 0.205) + 12
        return sum(1 for x in range(0, 1035, 3) for px in [im.getpixel((x, y))]
                   if abs(px[0] - 212) < 40 and abs(px[1] - 175) < 40 and abs(px[2] - 55) < 45)
    g2, g8 = gold_pixels(2), gold_pixels(8)
    check(f"the meter is painted in the poster and fills with progress ({g2} < {g8})", 0 < g2 < g8)
    db.customers.update_one({"id": "c1"}, {"$set": {"visits": 7}})

    print("\nThe poster photo stays sharp")
    def png_data(w, h, rgb):
        b = _io.BytesIO(); _Img.new("RGB", (w, h), rgb).save(b, "PNG")
        return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    # a landscape banner: blurred behind, the whole photo sharp in the middle band
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"hero_image_url": png_data(1125, 432, (20, 120, 220)),
                                                               "hero_mode": "image"}})
    im = _Img.open(_io.BytesIO(bundle().read("background@3x.png"))).convert("RGB")
    band = im.getpixel((517, int(1515 * 0.265) + 200))
    check(f"a landscape banner is shown whole, sharp, in the middle band ({band})", band == (20, 120, 220))
    # the « Image poster » wins; at the poster's shape it fills the card
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"poster_image_url": png_data(1035, 1515, (200, 40, 40))}})
    im = _Img.open(_io.BytesIO(bundle().read("background@3x.png"))).convert("RGB")
    check("a poster-shaped image fills the card edge to edge",
          im.getpixel((517, 1400)) == (200, 40, 40) and im.getpixel((5, 900)) == (200, 40, 40))
    # any other shape is shown whole, never cropped: a square photo keeps its 4 corners
    sq = _Img.new("RGB", (800, 800), (30, 160, 60))
    for (cx, cy) in ((0, 0), (799, 0), (0, 799), (799, 799)):
        for dx in range(-40, 41):
            for dy in range(-40, 41):
                if 0 <= cx + dx < 800 and 0 <= cy + dy < 800:
                    sq.putpixel((cx + dx, cy + dy), (250, 250, 0))
    b = _io.BytesIO(); sq.save(b, "PNG")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"poster_image_url":
                                 "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()}})
    im = _Img.open(_io.BytesIO(bundle().read("background@3x.png"))).convert("RGB")
    top_y = (1515 - 1035) // 2 + 36           # the square sits centred, 1035 wide; corner ≈ 52 px
    centre, corner = im.getpixel((517, 757)), im.getpixel((30, top_y))
    check(f"a square photo is shown whole: centre green {centre}, its yellow corner kept {corner}",
          centre == (30, 160, 60) and corner[0] > 180 and corner[1] > 180 and corner[2] < 90)
    r = http("PUT", "/api/owner/card/settings", headers={"Authorization": "Bearer " + _auth.create_access_token(
        {"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}, json={"poster_image_url": "javascript:alert(1)"})
    check("anything but an image is refused", r.status_code == 400)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"poster_image_url": "", "hero_image_url": ""},
                                                      "$set": {"hero_mode": "none"}})

    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"poster_style": False}})
    p2 = pj()
    check("the merchant can switch the poster off → the classic storeCard, strip included",
          "posterGeneric" not in p2 and "storeCard" in p2 and "generic" not in p2
          and "background.png" not in bundle().namelist() and "strip.png" in bundle().namelist())
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"poster_style": ""}})

    print("\nThe test link (Vercel preview)")
    os.environ.update({"VERCEL_ENV": "preview", "VERCEL_BRANCH_URL": "fidclic-platform-git-feat-x.vercel.app"})
    check("a pass from a preview deployment talks to that deployment, not production",
          pj()["webServiceURL"] == "https://fidclic-platform-git-feat-x.vercel.app/api/passes")
    os.environ.pop("VERCEL_ENV"); os.environ.pop("VERCEL_BRANCH_URL")
    check("production keeps its own address", not pj()["webServiceURL"].startswith("https://fidclic-platform-git"))

    print("\nThe owner's preview draws the poster")
    import auth as _auth
    _tk = _auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    pv = http("POST", "/api/owner/wallet/preview", headers={"Authorization": "Bearer " + _tk}, json={"card": {}}).json()
    check("preview has the poster: fields, background, logo",
          bool(pv.get("poster")) and pv["poster"]["background"].startswith("data:image/png")
          and pv["poster"]["primaryFields"][0]["key"] == "member")
    check("…and the iOS 26 card as before, strip included", bool(pv.get("strip")) and bool(pv.get("secondaryFields")))

    print("\nFeatured actions — none by default")
    check("no tiles until the merchant chooses", "featuredActions" not in pj())
    OWN = TokenData(email="o@x.fr", role="business_owner", tenant_id="t1")
    import auth
    tok = auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    r = http("PUT", "/api/owner/card/settings", headers={"Authorization": "Bearer " + tok}, json={"featured_actions": [
        {"type": "viewOffersRewards"}, {"type": "bookAppointment", "url": "https://planity.com/royal-trim"},
        {"type": "place"}]})
    saved = (db.card_templates.find_one({"tenant_id": "t1"}) or {}).get("featured_actions")
    check("saved: at most two, in the merchant's order", r.status_code == 200 and [a["type"] for a in saved] ==
          ["viewOffersRewards", "bookAppointment"])
    r = http("PUT", "/api/owner/card/settings", headers={"Authorization": "Bearer " + tok}, json={"featured_actions": [
        {"type": "unknownThing"}, {"type": "order", "url": "http://not-https"}, {"type": "place"}]})
    saved = (db.card_templates.find_one({"tenant_id": "t1"}) or {}).get("featured_actions")
    check("an unknown type (would hide every tile) is dropped; a link-less button is kept for the owner to fill",
          [a["type"] for a in saved] == ["order", "place"] and saved[0]["url"] == "")
    check("…and left off the pass while it has no link and the shop no website",
          [a["type"] for a in pj().get("featuredActions") or []] == ["place"])
    db.tenants.update_one({"id": "t1"}, {"$set": {"website": "www.royal-trim.fr"}})
    check("…or opens the shop's website from Établissement",
          [a["type"] for a in pj().get("featuredActions") or []] == ["order", "place"])
    db.tenants.update_one({"id": "t1"}, {"$unset": {"website": ""}})
    http("PUT", "/api/owner/card/settings", headers={"Authorization": "Bearer " + tok}, json={"featured_actions": [
        {"type": "viewOffersRewards"}, {"type": "bookAppointment", "url": "https://planity.com/royal-trim"}]})
    fa = pj().get("featuredActions") or []
    check("pass.json: identifier, type, url for each", len(fa) == 2 and all(set(a) == {"identifier", "type", "url"} for a in fa))
    check("the url goes through our counter", fa[0]["url"].endswith("/api/card/FT-TEST0001/action/fa1-viewOffersRewards"))
    s = http("GET", "/api/owner/card/settings", headers={"Authorization": "Bearer " + tok}).json()
    check("the settings page offers only Apple's published types",
          {t["type"] for t in s["advanced"]["featured_types"]} <= set(WP.FEATURED_TYPES) and s["advanced"]["poster_style"] is True)

    print("\nA tap on a tile")
    r = http("GET", fa[1]["url"].split("http://test")[-1].split(WP._site_url())[-1], follow_redirects=False)
    check(f"redirects to the merchant's booking page ({r.status_code})",
          r.status_code == 302 and r.headers["location"] == "https://planity.com/royal-trim")
    r = http("GET", "/api/card/FT-TEST0001/action/fa1-viewOffersRewards", follow_redirects=False)
    check("« Voir les offres » opens the card's offers", r.status_code == 302 and r.headers["location"].endswith("/card/FT-TEST0001?onglet=offres"))
    check("each tap is counted", db.pass_action_clicks.count_documents({"tenant_id": "t1"}) == 2)
    r = http("GET", "/api/card/FT-TEST0001/action/fa9-order", follow_redirects=False)
    check("a tile the merchant removed lands on the card, uncounted",
          r.status_code == 302 and r.headers["location"].endswith("/card/FT-TEST0001")
          and db.pass_action_clicks.count_documents({"tenant_id": "t1"}) == 2)
    st = WP.owner_wallet_stats(token_data=OWN)
    check("Wallet stats show the tiles and their taps",
          st["featured_actions"]["clicks_30d"] == {"viewOffersRewards": 1, "bookAppointment": 1}
          and [a["type"] for a in st["featured_actions"]["active"]] == ["viewOffersRewards", "bookAppointment"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
