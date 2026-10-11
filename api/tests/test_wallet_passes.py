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
        # this suite is the classic storeCard; the iOS 27 poster has test_wallet_poster
        "poster_style": False,
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

    check("config: apple on, google off", {k: v for k, v in WP.wallet_config().items() if k != "in_plan"} == {"apple": True, "google": False})

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
    # a tampons programme shows tampons, never points (user, 2026-10-12)
    check("tampons programme: statut in the header, no points anywhere",
          [f["key"] for f in sc["headerFields"]] == ["tier"] and sc["headerFields"][0]["value"] == "Or"
          and not any(f["key"] == "points" for g in ("headerFields", "primaryFields", "secondaryFields") for f in sc[g]))
    check("primaryFields empty with a strip", sc["primaryFields"] == [])
    sec = {f["key"]: f["value"] for f in sc["secondaryFields"]}
    # Three fields, not four: a storeCard row squeezes four values to the point
    # where the stamps — the one that matters — become hard to read.
    check("member/stamps/visits in one readable row, the statut not twice",
          sec == {"member": "Marie", "stamps": "7 / 10", "visits": 7})
    check("no « Récompense » added to the front by itself", "reward" not in sec)
    back_by_key = {f["key"]: f for f in sc["backFields"]}
    check("reward spelt out on the back, not squeezed in the front row",
          back_by_key["next_reward"]["value"] == "Encore 3 tampons avant : Une coupe offerte"
          and sc["auxiliaryFields"] == [])
    # Wallet only notifies when an EXISTING field changes: the offer field is
    # there before any campaign, so the first campaign is a change, not a birth.
    check("offer field always on the back, with a changeMessage",
          back_by_key["offer"]["value"] == "Aucune offre en ce moment." and back_by_key["offer"]["changeMessage"] == "%@")
    from PIL import Image as _LI
    lw, lh = _LI.open(io.BytesIO(z.read("logo.png"))).size
    check(f"logo only as wide as it is (no 160-pt padding eating the name): {lw}x{lh}", lw <= 50 and lh == 50)
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
    # Clients › Carte (2026-10-10): removed, then put back in Apple Wallet → Active
    from features import card_status as _CS
    gone = db.customers.find_one({"barcode_id": "FT-TEST0001"})
    check("the last Wallet removing it marks the card « Retirée »", _CS.state_of(gone)["state"] == "wallet_removed")
    time.sleep(0.01)
    status(WP.register_device, "dev2", "pass.com.fidclic.test", "FT-TEST0001", reg, hdr)
    back = db.customers.find_one({"barcode_id": "FT-TEST0001"})
    check("added to a Wallet again: the card reads « Active »", back.get("wallet_added_at") and _CS.state_of(back)["state"] == "active")
    status(WP.unregister_device, "dev2", "pass.com.fidclic.test", "FT-TEST0001", hdr)

    # ---- banner (strip) layout ------------------------------------------
    # 1×1 pixel JPEG stand-in for the merchant's artwork.
    banner = ("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
              "DBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
              "AAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==")
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"hero_image_url": banner, "hero_mode": "image",
                                                               "programme": "points_visit"}})
    pj2 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    sc2 = pj2["storeCard"]
    check("banner: nothing drawn over the artwork (primaryFields empty)", sc2["primaryFields"] == [])
    check("banner: points move to the header", [f["key"] for f in sc2["headerFields"]] == ["points"]
          and sc2["headerFields"][0]["value"] == 70)
    check("banner: statut joins the secondary row", "tier" in [f["key"] for f in sc2["secondaryFields"]])
    check("points programme: points = the customer's real balance, no tampons",
          sc2["headerFields"][0]["value"] == 70 and "stamps" not in [f["key"] for f in sc2["secondaryFields"]])
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
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"hero_image_url": "", "hero_mode": "none"}})
    pj3 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("points programme (no jauge), no photo: classic layout (points primary, statut header)",
          pj3["storeCard"]["primaryFields"][0]["key"] == "points"
          and pj3["storeCard"]["headerFields"][0]["key"] == "tier")
    z3 = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    check("meter off, no photo: no strip at all", "strip.png" not in z3.namelist())

    # ---- the meter is really painted into the strip ------------------------
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"programme": "stamps"}})
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

    # ---- a wallet campaign with a photo (user, 2026-10-05) -----------------
    # Wallet shows no image in a notification or on the back: the photo
    # becomes the banner while the campaign is the offer, and the back links
    # to the campaign on the web card.
    _red = io.BytesIO()
    _IM.new("RGB", (600, 300), (220, 20, 20)).save(_red, "PNG")
    photo = "data:image/png;base64," + base64.b64encode(_red.getvalue()).decode()
    db.campaigns.delete_many({})
    db.campaigns.insert_one({"id": "camp-photo", "tenant_id": "t1", "name": "Séance offerte",
                             "content": "Venez cette semaine", "status": "sent", "wallet_offer": True,
                             "recipient_ids": ["c1"], "sent_at": dt.datetime.now(dt.timezone.utc), "image_url": photo})
    pjc = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    backc = {f["key"]: f for f in pjc["storeCard"]["backFields"]}
    check("campaign photo: the back links to the campaign on the web card",
          backc.get("offer_link", {}).get("value", "").startswith(f"{WP._site_url()}/card/FT-TEST0001?offre=camp-photo&k=")
          and 'href="' in backc["offer_link"].get("attributedValue", ""))
    check("campaign photo: the link sits right under the offer",
          (lambda ks: ks.index("offer_link") == ks.index("offer") + 1)([f["key"] for f in pjc["storeCard"]["backFields"]]))
    check("« Dernier message » (Automatisations) opens the back, always there",
          pjc["storeCard"]["backFields"][0]["key"] == "news")
    check("campaign photo: banner layout (nothing over the photo)", pjc["storeCard"]["primaryFields"] == [])
    zc = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    top = _IM.open(io.BytesIO(zc.read("strip@3x.png"))).convert("RGB").getpixel((560, 60))
    check(f"campaign photo: it is the strip (top pixel {top})", top[0] > 150 and top[1] < 90 and top[2] < 90)
    gobj = WP._gw_object(WP._card_payload("FT-TEST0001"))
    check("campaign photo: Google gets the link, not a raw URL in the details",
          "?offre=camp-photo&k=" in gobj["linksModuleData"]["uris"][0]["uri"]
          and not any(t["id"] == "offer_link" for t in gobj["textModulesData"]))
    check("campaign photo: Google's banner URL changes with the campaign",
          "-camp-photo-" in gobj["heroImage"]["sourceUri"]["uri"])
    db.campaigns.update_one({"id": "camp-photo"}, {"$set": {
        "sent_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=WP.CAMPAIGN_OFFER_DAYS + 1)}})
    pje = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("campaign over: link gone", "offer_link" not in {f["key"] for f in pje["storeCard"]["backFields"]})
    ze = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-TEST0001"))))
    tope = _IM.open(io.BytesIO(ze.read("strip@3x.png"))).convert("RGB").getpixel((560, 60))
    check(f"campaign over: the photo leaves the strip ({tope})", not (tope[0] > 150 and tope[1] < 90))
    db.campaigns.delete_many({})

    # ---- lifecycle: relevantDate / expirationDate / voided ---------------
    db.tenants.update_one({"id": "t1"}, {"$set": {"weekly_schedule": [
        {"day": d, "open_from": "09:00", "open_to": "19:00", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]}})
    pj4 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("relevantDate = next opening (lock screen at the right moment)",
          "relevantDate" in pj4 and pj4["relevantDate"].endswith("Z"))
    check("points field carries a changeMessage",
          any(f.get("changeMessage") for grp in pj4["storeCard"].values() for f in grp))

    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"pass_expiration_date": "2027-01-31T23:59:00Z"}})
    pj5 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("merchant expiry lands on the pass", pj5.get("expirationDate") == "2027-01-31T23:59:00Z")
    check("a live card is not voided", "voided" not in pj5)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"pass_expiration_date": ""}})

    db.customers.update_one({"id": "c1"}, {"$set": {"card_deleted_at": dt.datetime.now(dt.timezone.utc)}})
    pj6 = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    check("deleted card → voided + expired", pj6.get("voided") is True and "expirationDate" in pj6)
    check("voided pass explains itself on the back",
          any(f["key"] == "voided" for f in pj6["storeCard"]["backFields"]))
    db.customers.update_one({"id": "c1"}, {"$unset": {"card_deleted_at": ""}})

    db.tenants.update_one({"id": "t1"}, {"$set": {"is_active": False}})
    check("deactivated business → voided", WP.build_pass_json(WP._card_payload("FT-TEST0001")).get("voided") is True)
    db.tenants.update_one({"id": "t1"}, {"$set": {"is_active": True}})

    # ---- update pushes ----------------------------------------------------
    import services.apns_passes as APNS
    calls = {}
    def fake_push(tokens):
        calls["tokens"] = list(tokens)
        return {"sent": len(calls["tokens"]), "gone": ["dead-token"], "failed": 0, "errors": []}
    APNS.push_to_tokens, APNS.is_configured = fake_push, (lambda: True)
    db.pass_registrations.insert_one({"device_id": "dev9", "serial": "FT-TEST0001",
                                      "push_token": "tok9", "pass_type_id": "pass.com.fidclic.test"})
    db.pass_registrations.insert_one({"device_id": "devX", "serial": "FT-TEST0001",
                                      "push_token": "dead-token", "pass_type_id": "pass.com.fidclic.test"})
    res = WP.notify_customer("c1")
    check("push sent to every device holding the pass", res["devices"] == 2 and res["sent"] == 2)
    check("dead token dropped from the registrations", db.pass_registrations.count_documents({"push_token": "dead-token"}) == 0)
    check("notify_tenant covers the whole customer base", WP.notify_tenant("t1")["devices"] == 1)
    server.refresh_wallet_pass("c1")          # must never raise
    check("refresh_wallet_pass is fire-and-forget", calls["tokens"] == ["tok9"])

    # A push must be answered with the pass: the device asks what changed since
    # its last fetch. A campaign doesn't touch the customer, so before this fix
    # the answer was 204 and the pass (and its notification) never came.
    db.customers.update_one({"id": "c1"}, {"$unset": {"updated_at": ""}})
    before = str(int(time.time()) - 5)
    WP.notify_customer("c1")
    st, r = status(WP.serials_for_device, "dev9", "pass.com.fidclic.test", before)
    check("after a push, the device is told the pass changed", st == 200 and r["serialNumbers"] == ["FT-TEST0001"])
    st, _ = status(WP.serials_for_device, "dev9", "pass.com.fidclic.test", str(int(time.time()) + 60))
    check("and only once: nothing newer → 204", st == 204)

    # ---- the owner can see the update chain --------------------------------
    import asyncio
    class _Req:
        async def json(self): return {"logs": ["Error fetching pass FT-TEST0001: 401", "other shop FT-ZZZZ9999 failed"]}
    asyncio.run(WP.passkit_log(_Req()))
    WP.latest_pass("pass.com.fidclic.test", "FT-TEST0001", "ApplePass " + WP._auth_token("FT-TEST0001"))
    class _OT2:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"
    st = WP.owner_wallet_stats(_OT2())
    d0 = st["devices_detail"][0]
    check("stats: last push, its result, the check and the fetch are visible",
          bool(d0["last_push_at"] and d0["last_push_result"] == "ok" and d0["last_check_at"] and d0["last_fetch_at"]))
    check("stats: only this shop's device log lines", [x["line"] for x in st["device_logs"]] == ["Error fetching pass FT-TEST0001: 401"])

    # ---- a wallet campaign: short title in front, full text on the back ---
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                             "recipient_ids": ["c1"], "name": "Salut",
                             "content": "On vous attend pour un cadeau",
                             "sent_at": dt.datetime.now(dt.timezone.utc)})
    pjc = WP.build_pass_json(WP._card_payload("FT-TEST0001"))
    front = pjc["storeCard"]["secondaryFields"] + pjc["storeCard"]["auxiliaryFields"]
    check("campaign: at most three short fields in the front row", len(front) <= 3)
    check("campaign: its title in front", any(f["key"] == "offer_title" and f["value"] == "Salut" for f in front))
    offer_back = next(f for f in pjc["storeCard"]["backFields"] if f["key"] == "offer")
    check("campaign: full text on the back, it is what the notification says",
          offer_back["value"] == "Salut — On vous attend pour un cadeau" and offer_back["changeMessage"] == "%@")
    check("campaign: statut kept (top right, or on the back)",
          any(f["key"] == "tier" for f in pjc["storeCard"]["headerFields"])
          or any(f["key"] == "tier_back" for f in pjc["storeCard"]["backFields"]))
    db.campaigns.delete_one({"id": "camp1"})

    # ---- nothing written over the merchant's photo ------------------------
    photo = _LI.new("RGB", (1125, 432), (10, 120, 200)); pb = io.BytesIO(); photo.save(pb, "PNG")
    with_text = _LI.open(io.BytesIO(WP.compose_strip(pb.getvalue(), {}, 0, 10, False, title="SALUT",
                                                     subtitle="On vous attend"))).convert("RGB")
    check("photo strip: the offer is not burnt into the picture",
          all(with_text.getpixel((x, 200)) == (10, 120, 200) for x in range(300, 830, 10)))

    # ---- the designer's preview IS the pass ------------------------------
    class _OT:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"
    pv = WP.owner_wallet_preview(WP.PassPreviewIn(card={"card_name": "NOUVEAU NOM"}, visits=3), _OT())
    real = WP.build_pass_json(WP._card_payload("FT-TEST0001"))["storeCard"]
    check("preview: same front fields as the real pass (keys, order)",
          [f["key"] for f in pv["secondaryFields"]] == [f["key"] for f in real["secondaryFields"]]
          and [f["key"] for f in pv["headerFields"]] == [f["key"] for f in real["headerFields"]])
    check("preview: the unsaved name is used", pv["logoText"] == "NOUVEAU NOM")
    check("preview: strip and logo are the real images", (pv["strip"] or "").startswith("data:image/png;base64,")
          and pv["logo"].startswith("data:image/png;base64,") and pv["logo_width"] <= 100)
    check("preview: the offer is on the back, like the pass", any(f["key"] == "offer" for f in pv["backFields"]))
    check("preview: a sample customer, never a real one", pv["sample"]["name"] == "Marie Dupont"
          and pv["barcode"]["altText"] == "FT-5A3C91E2")

    # ---- unconfigured is a clean 503, never a 500 ------------------------
    os.environ["APPLE_PASS_KEY_B64"] = ""
    check("unconfigured → 503", status(WP.download_apple_pass, "FT-TEST0001")[0] == 503)
    check("google unconfigured → 503", status(WP.google_wallet_link, "FT-TEST0001")[0] == 503)
    check("unknown card → 404", status(WP.serials_for_device, "nobody", "x", None)[0] == 204 and status(lambda: WP._card_payload("FT-NOPE"))[0] == 404)

    # ---- Google Wallet: both ways of configuring it -----------------------------------------
    # Two shapes are in the wild. A deployment that holds everything Google
    # needs must not be told it is unconfigured because it used the other pair
    # of variable names.
    print("\nGoogle Wallet — les deux façons de le configurer")
    KEYS = ("GOOGLE_WALLET_ISSUER_ID", "GOOGLE_WALLET_CLASS_ID", "GOOGLE_WALLET_SA_B64",
            "GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL", "GOOGLE_WALLET_PRIVATE_KEY")
    saved = {k: os.environ.get(k) for k in KEYS}

    def only(**env):
        for k in KEYS:
            os.environ.pop(k, None)
        os.environ.update(env)

    only()
    check("nothing configured reads as not configured",
          WP.google_configured() is False and WP._gw_issuer() == "")
    check("and asking for the credentials says so rather than crashing",
          WP._gw_credentials() is None)

    import base64 as _b64, json as _json
    sa_json = _json.dumps({"client_email": "sa@p.iam.gserviceaccount.com",
                           "private_key": "-----BEGIN-----\nk\n-----END-----"})
    only(GOOGLE_WALLET_ISSUER_ID="3388000000012345678",
         GOOGLE_WALLET_SA_B64=_b64.b64encode(sa_json.encode()).decode())
    check("the issuer id + the whole JSON key still works",
          WP.google_configured() and WP._gw_issuer() == "3388000000012345678")
    check("and a JSON key with no token_uri gets Google's own",
          WP._gw_credentials()["token_uri"] == "https://oauth2.googleapis.com/token")

    only(GOOGLE_WALLET_CLASS_ID="3388000000012345678.fidclic_loyalty",
         GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL="sa@p.iam.gserviceaccount.com",
         GOOGLE_WALLET_PRIVATE_KEY="-----BEGIN-----" + chr(92) + "nkey" + chr(92) + "n-----END-----")
    check("the class id + the two key fields works too", WP.google_configured())
    check("the issuer id is read out of the class id",
          WP._gw_issuer() == "3388000000012345678")
    key = WP._gw_credentials()["private_key"]
    check("a key pasted with literal backslash-n is repaired",
          chr(92) + "n" not in key and key.count(chr(10)) == 2)

    only(GOOGLE_WALLET_CLASS_ID="3388000000012345678.x")
    check("an issuer with no service account is not 'configured'",
          WP.google_configured() is False)
    only(GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL="sa@p.iam.gserviceaccount.com",
         GOOGLE_WALLET_PRIVATE_KEY="k")
    check("a service account with no issuer is not 'configured' either",
          WP.google_configured() is False)
    only(GOOGLE_WALLET_CLASS_ID="not-a-number.suffix",
         GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL="sa@p.iam.gserviceaccount.com",
         GOOGLE_WALLET_PRIVATE_KEY="k")
    check("a class id whose head is not an issuer number is refused",
          WP._gw_issuer() == "" and WP.google_configured() is False)

    # ---- a mangled private key is repaired (user, 2026-10-04: MalformedFraming) ----
    print("\nGoogle Wallet — clé privée abîmée, réparée")
    from cryptography.hazmat.primitives.asymmetric import rsa as _rsa
    from cryptography.hazmat.primitives import serialization as _ser
    _k = _rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = _k.private_bytes(_ser.Encoding.PEM, _ser.PrivateFormat.PKCS8, _ser.NoEncryption()).decode()
    body = "".join(pem.strip().splitlines()[1:-1])
    def loads(k):
        try:
            _ser.load_pem_private_key(WP._normalize_pem(k).encode(), password=None)
            return True
        except Exception:
            return False
    check("clean key loads", loads(pem))
    check("quoted, with literal backslash-n (JSON copy) loads", loads('"' + pem.replace(chr(10), chr(92) + "n") + '"'))
    check("one line, breaks turned into spaces, loads", loads(pem.replace(chr(10), " ")))
    check("body only, no BEGIN/END, loads", loads(body))
    check("whole PEM base64-encoded loads", loads(_b64.b64encode(pem.encode()).decode()))

    # ---- Google follows every change, notifies on campaign + reward only --------
    print("\nGoogle Wallet — synchronisation et notifications")
    only(GOOGLE_WALLET_ISSUER_ID="3388000000012345678",
         GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL="sa@p.iam.gserviceaccount.com",
         GOOGLE_WALLET_PRIVATE_KEY=pem.replace(chr(10), " "))
    gcalls = []
    quota = {"on": False}
    def fake_call(method, path, body, token):
        gcalls.append((method, path, body))
        if path.endswith("/addMessage") and quota["on"] and body["message"]["messageType"] == "TEXT_AND_NOTIFY":
            return 429, {"error": {"message": "QuotaExceededException"}}
        return 200, {}
    real_call, real_tok = WP._gw_call, WP._gw_access_token
    WP._gw_call, WP._gw_access_token = fake_call, (lambda: "tok")
    try:
        check("nothing synced for a customer who never added the Google card",
              WP.google_sync(["FT-TEST0001"])["cards"] == 0 and not gcalls)
        db.google_wallet_objects.insert_one({"serial": "FT-TEST0001", "tenant_id": "t1",
                                             "object_id": "3388000000012345678.FT_TEST0001"})
        res = WP.notify_customer("c1")
        put = [c for c in gcalls if c[0] == "PUT" and "/loyaltyObject/" in c[1]]
        check("a scan sends the new card to Google", res["google"]["synced"] == 1 and len(put) == 1)
        check("a plain scan does not notify", not any(c[1].endswith("/addMessage") for c in gcalls))
        obj = put[0][2]
        check("same content as Apple: member, tampons (a tampons programme), offer on the details",
              obj["accountName"] == "Marie" and obj["loyaltyPoints"]["label"].startswith("Tampons")
              and "secondaryLoyaltyPoints" not in obj
              and any(t["header"] == "Offre du moment" for t in obj["textModulesData"]))
        gcalls.clear()
        WP.notify_customer("c1", google_notify="reward")
        msg = [c[2]["message"] for c in gcalls if c[1].endswith("/addMessage")]
        check("reward unlocked → one notifying message", len(msg) == 1 and msg[0]["messageType"] == "TEXT_AND_NOTIFY"
              and msg[0]["header"] == "Récompense débloquée !")
        gcalls.clear()
        db.campaigns.insert_one({"id": "gcamp", "tenant_id": "t1", "status": "sent", "wallet_offer": True,
                                 "recipient_ids": ["c1"], "name": "Bonjour {first_name}", "content": "-20 % ce soir",
                                 "sent_at": dt.datetime.now(dt.timezone.utc)})
        WP.notify_passes(["FT-TEST0001"], google_notify="campaign")
        msg = [c[2]["message"] for c in gcalls if c[1].endswith("/addMessage")]
        put = [c[2] for c in gcalls if c[0] == "PUT" and "/loyaltyObject/" in c[1]]
        check("campaign → notifying message, name filled in", len(msg) == 1 and msg[0]["messageType"] == "TEXT_AND_NOTIFY"
              and msg[0]["header"] == "Bonjour Marie")
        check("and not twice in the card (the PUT leaves it to addMessage)", not put[0].get("messages"))
        gcalls.clear()
        quota["on"] = True
        r = WP.notify_passes(["FT-TEST0001"], google_notify="campaign")
        kinds = [c[2]["message"]["messageType"] for c in gcalls if c[1].endswith("/addMessage")]
        check("over Google's 3-a-day limit: still in the card, without notification",
              kinds == ["TEXT_AND_NOTIFY", "TEXT"] and r["google"]["notified"] == 0)
        quota["on"] = False
        db.campaigns.delete_one({"id": "gcamp"})
        check("automations' call with message= no longer raises", isinstance(WP.notify_customer("c1", message="Joyeux anniversaire"), dict))
        gcalls.clear()
        WP.notify_customer("c1", message="x", google_notify={"kind": "birthday", "header": "Joyeux anniversaire Marie !",
                                                             "body": "Un dessert offert cette semaine"})
        msg = [c[2]["message"] for c in gcalls if c[1].endswith("/addMessage")]
        check("birthday → one notifying message with the scenario's own words", len(msg) == 1
              and msg[0]["messageType"] == "TEXT_AND_NOTIFY" and msg[0]["header"] == "Joyeux anniversaire Marie !")
        gcalls.clear()
        WP.notify_customer("c1", google_notify={"kind": "parrainage", "header": "Parrainage réussi 🎉",
                                                "body": "Votre ami Sami est venu chez Le Café : +50 points."})
        msg = [c[2]["message"] for c in gcalls if c[1].endswith("/addMessage")]
        check("parrainage → one notifying message with its words (#168 sent none)", len(msg) == 1
              and msg[0]["messageType"] == "TEXT_AND_NOTIFY" and "Sami" in msg[0]["body"])
        class _OT3:
            email, role, tenant_id = "owner@x.fr", "business_owner", "t1"
        g = WP.owner_wallet_stats(_OT3())["google"]
        check("stats show the Google side", g["cards"] == 1 and g["recent"][0]["last_sync_result"].startswith("ok"))
        # the scan really asks for a notification when it completes a card
        seen = {}
        real_refresh = server.refresh_wallet_pass
        server.refresh_wallet_pass = lambda cid, reward_earned=False, google_notify=None: seen.setdefault("r", []).append(reward_earned)
        try:
            db.customers.update_one({"id": "c1"}, {"$set": {"visits": 9, "visits_at_last_redemption": 0}})
            class _ST:
                email, role, tenant_id = "owner@x.fr", "business_owner", "t1"
            server.scan_visit(server.ScanRequest(barcode_id="FT-TEST0001", amount_paid=5.0), _ST())
            server.scan_visit(server.ScanRequest(barcode_id="FT-TEST0001", amount_paid=5.0), _ST())
        finally:
            server.refresh_wallet_pass = real_refresh
        check("the scan that completes the card asks for the reward notification, the next one does not",
              seen.get("r") == [True, False])
    finally:
        WP._gw_call, WP._gw_access_token = real_call, real_tok

    only(**{k: v for k, v in saved.items() if v is not None})

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
