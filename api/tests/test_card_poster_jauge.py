"""
Carte de fidélité, iOS 27 poster (user, 2026-10-11):
  • the photo covers the whole poster, as an iOS 27 poster does; « Ajuster »
    (poster_image_url) frames it, and Wallet ships exactly that frame;
  • the band under the fields: Apple's blur, or the owner's colour
    (footerBackgroundColor), as in Pass Designer;
  • the tampons are a text jauge under the QR (« ●●●○○○○○○○ »), nothing is
    painted over the photo; iOS 26 keeps its strip;
  • one tampon shape (● ★ ♥ ■ ◆) for every jauge: iOS 27 text, Google's row,
    the jauge painted in the iOS 26 strip and Google's banner;
  • Google: a jauge row only when the banner has none;
  • the « Aperçu » is faster: composed images are remembered.

Run: cd api && /usr/local/bin/python3 tests/test_card_poster_jauge.py
"""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import io
import json
import os
import sys
import time
import zipfile

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    import httpx
    from PIL import Image

    import auth as _auth
    import server
    from features import pass_designer as PD
    from features import wallet_passes as WP

    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "bloo-job", "name": "Bloo Job", "address": "1 rue Colbert, 37000 Tours"})
    db.card_templates.insert_one({
        "tenant_id": "t1", "surface_color": "#1E1B2E", "brand_color": "#D4AF37", "card_name": "BLOO JOB",
        "reward_threshold_stamps": 10, "reward_description": "Un café offert", "hero_mode": "none",
    })
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-JAUGE001", "name": "Marie Dupont",
                             "visits": 3, "points": 30, "tier": "bronze", "created_at": dt.datetime.now(dt.timezone.utc)})
    db.users.insert_one({"id": "u1", "email": "o@bloo.fr", "role": "business_owner", "tenant_id": "t1"})
    TOKEN = _auth.create_access_token({"sub": "o@bloo.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + TOKEN}

    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def setcard(**kw):
        db.card_templates.update_one({"tenant_id": "t1"}, {"$set": kw})

    def unset(*keys):
        db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {k: "" for k in keys}})

    def visits(n):
        db.customers.update_one({"id": "c1"}, {"$set": {"visits": n}})

    def pj():
        return WP.build_pass_json(WP._card_payload("FT-JAUGE001"))

    def field(block, key):
        return next((f for f in block if f["key"] == key), None)

    def bundle():
        return zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload("FT-JAUGE001"))))

    def png_data(w, h, rgb, fmt="PNG"):
        b = io.BytesIO(); Image.new("RGB", (w, h), rgb).save(b, fmt)
        return f"data:image/{fmt.lower()};base64," + base64.b64encode(b.getvalue()).decode()

    def img(raw):
        return Image.open(io.BytesIO(raw)).convert("RGB")

    # ------------------------------------------------------------------
    print("\nThe text jauge")
    check("default: ●●●○○○○○○○", WP.jauge_text(3, 10, None) == "●●●○○○○○○○")
    check("étoile: ★★★☆☆", WP.jauge_text(3, 5, "etoile") == "★★★☆☆")
    check("carré: ■■□□", WP.jauge_text(2, 4, "carre") == "■■□□")
    check("losange: ◆◇◇", WP.jauge_text(1, 3, "losange") == "◆◇◇")
    check("cœur: the filled heart is forced to text (no red emoji)",
          WP.jauge_text(2, 3, "coeur") == "♥︎♥︎♡")
    check("an unknown shape reads as the default", WP.jauge_text(1, 2, "pizza") == "●○")
    check("0 tampons: all empty", WP.jauge_text(0, 4, None) == "○○○○")
    check("full card: all filled", WP.jauge_text(10, 10, None) == "●" * 10)
    check("more tampons than the card: capped", WP.jauge_text(14, 10, None) == "●" * 10)
    check("negative never draws", WP.jauge_text(-2, 3, None) == "○○○")
    check("no threshold: no jauge", WP.jauge_text(3, 0, None) is None)
    check("20 tampons still fit", WP.jauge_text(3, 20, None) == "●●●" + "○" * 17)
    check("21+ tampons: no jauge (one line cannot hold them)", WP.jauge_text(3, 21, None) is None)
    check("stamp_shape: only known keys", WP.stamp_shape({"stamp_shape": "etoile"}) == "etoile"
          and WP.stamp_shape({"stamp_shape": "x"}) is None and WP.stamp_shape({}) is None)

    # ------------------------------------------------------------------
    print("\niOS 27 poster: the jauge under the QR")
    visits(3)
    p = pj()
    pg = p["posterGeneric"]
    st = field(pg["primaryFields"], "stamps")
    check(f"the stamps field is the jauge ({st and st['value']})", st and st["value"] == "●●●○○○○○○○")
    check(f"the count is in its label ({st and st['label']})", st and st["label"] == "TAMPONS · 3/10")
    check("it still notifies when a tampon is added", st and "%@" in st.get("changeMessage", ""))
    check("member first, jauge second (under the QR, in the band)",
          [f["key"] for f in pg["primaryFields"]][:2] == ["member", "stamps"])
    sc = field(p["storeCard"]["secondaryFields"], "stamps")
    check(f"iOS 26 keeps « 3 / 10 » ({sc and sc['value']})", sc and sc["value"] == "3 / 10")
    check("iOS 26 keeps its painted strip", {"strip.png", "strip@2x.png", "strip@3x.png"} <= set(bundle().namelist()))

    setcard(stamp_shape="etoile")
    st = field(pj()["posterGeneric"]["primaryFields"], "stamps")
    check(f"the owner's shape: ★ ({st['value']})", st["value"] == "★★★☆☆☆☆☆☆☆")
    setcard(stamp_shape="coeur")
    check("cœur on the pass", field(pj()["posterGeneric"]["primaryFields"], "stamps")["value"].startswith("♥︎"))
    unset("stamp_shape")

    visits(10)
    st = field(pj()["posterGeneric"]["primaryFields"], "stamps")
    check(f"full card: every shape filled, 10/10 ({st['label']})", st["value"] == "●" * 10 and st["label"].endswith("10/10"))
    visits(0)
    check("new customer: empty jauge, 0/10",
          field(pj()["posterGeneric"]["primaryFields"], "stamps")["value"] == "○" * 10)
    visits(3)

    setcard(stamps_label="Cafés")
    check("the owner's stamps label leads the count",
          field(pj()["posterGeneric"]["primaryFields"], "stamps")["label"] == "CAFÉS · 3/10")
    unset("stamps_label")

    setcard(show_meter=False)
    st = field(pj()["posterGeneric"]["primaryFields"], "stamps")
    check(f"jauge switched off: « 3 / 10 » as before ({st['value']})", st["value"] == "3 / 10" and st["label"] == "TAMPONS")
    unset("show_meter")

    # the page's default « Jauge » style: show_stamps off, show_meter on
    setcard(show_stamps=False, show_meter=True)
    p = pj()
    prim = p["posterGeneric"]["primaryFields"]
    j = field(prim, "jauge")
    check("« Jauge » style: the jauge takes the reward's slot (MEMBRE | TAMPONS ●●●○)",
          [f["key"] for f in prim] == ["member", "jauge"] and j["value"] == "●●●○○○○○○○" and j["label"] == "TAMPONS · 3/10")
    check("…and notifies on each new tampon", "%@" in j.get("changeMessage", ""))
    check("iOS 26 keeps its reward field and its painted strip",
          field(p["storeCard"]["secondaryFields"], "reward") is not None)
    setcard(stamps_change_message="Un tampon de plus : %@")
    check("the owner's tampon message is used", field(pj()["posterGeneric"]["primaryFields"], "jauge")["changeMessage"]
          == "Un tampon de plus : %@")
    unset("show_stamps", "show_meter", "stamps_change_message")

    setcard(reward_threshold_stamps=25)
    st = field(pj()["posterGeneric"]["primaryFields"], "stamps")
    check(f"25 tampons: the count in text, no jauge ({st['value']})", st["value"] == "3 / 25")
    setcard(reward_threshold_stamps=10)

    # ------------------------------------------------------------------
    print("\nThe poster: full bleed, nothing painted on it")
    setcard(hero_image_url=png_data(1600, 1000, (20, 120, 220), "JPEG"), hero_mode="image")
    bg = img(bundle().read("background@3x.png"))
    check("background is 1035×1515", bg.size == (1035, 1515))
    lo, mid = bg.getpixel((10, 1500)), bg.getpixel((517, 900))
    check(f"a landscape photo covers the card, edge to edge ({lo}, {mid})",
          all(abs(a - b) < 12 for a, b in zip(lo, (20, 120, 220))) and all(abs(a - b) < 12 for a, b in zip(mid, (20, 120, 220))))
    top = bg.getpixel((517, 10))
    check(f"a soft scrim at the top keeps the logo readable ({top})", top[2] < 200)
    row = [bg.getpixel((x, int(1515 * 0.205) + 12)) for x in range(0, 1035, 5)]
    check("no meter painted at the old place", not any(abs(r - 212) < 40 and abs(g - 175) < 40 and b < 100 for r, g, b in row))
    setcard(hero_image_url=png_data(600, 1400, (200, 30, 30)))
    bg = img(bundle().read("background@3x.png"))
    check("a tall photo covers it too", bg.getpixel((5, 900)) == (200, 30, 30) and bg.getpixel((1030, 1510)) == (200, 30, 30))

    # « Ajuster »: the owner's frame, already poster-shaped, ships as is
    framed = Image.new("RGB", (1035, 1515), (10, 200, 10))
    for y in range(1200, 1515):
        for x in range(0, 1035, 1):
            framed.putpixel((x, y), (250, 250, 0))
    b = io.BytesIO(); framed.save(b, "PNG")
    setcard(poster_image_url="data:image/png;base64," + base64.b64encode(b.getvalue()).decode())
    bg = img(bundle().read("background@3x.png"))
    check("« Ajuster »: the framed image is the poster, pixel for pixel",
          bg.getpixel((517, 800)) == (10, 200, 10) and bg.getpixel((517, 1400)) == (250, 250, 0))
    check("…and the 1x / 2x are the same frame",
          img(bundle().read("background.png")).size == (345, 505) and img(bundle().read("background@2x.png")).size == (690, 1010))
    unset("poster_image_url")

    db.card_templates.update_one({"tenant_id": "t1"}, {"$unset": {"hero_image_url": ""}, "$set": {"hero_mode": "none"}})
    bg = img(bundle().read("background@3x.png"))
    check("no photo: the brand gradient, still full size", bg.size == (1035, 1515))

    # ------------------------------------------------------------------
    print("\nThe band under the fields: Flou Apple or a colour")
    check("default: no footerBackgroundColor (Apple's blur)", "footerBackgroundColor" not in pj())
    setcard(poster_footer_color="#7A1F3D")
    p = pj()
    check(f"a colour: footerBackgroundColor = {p.get('footerBackgroundColor')}",
          p.get("footerBackgroundColor") == "rgb(122, 31, 61)")
    setcard(poster_style=False)
    check("poster off: no footer colour (iOS 26 card only)", "footerBackgroundColor" not in pj())
    unset("poster_style")
    setcard(poster_footer_color="")
    check("« Flou Apple » again: the key is gone", "footerBackgroundColor" not in pj())

    r = http("PUT", "/api/owner/card/settings", headers=H, json={"poster_footer_color": "#12AB34", "stamp_shape": "losange"})
    check(f"settings save the footer colour and the shape ({r.status_code})", r.status_code == 200)
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("stored as given", tpl.get("poster_footer_color") == "#12AB34" and tpl.get("stamp_shape") == "losange")
    check("the pass takes both", pj().get("footerBackgroundColor") == "rgb(18, 171, 52)"
          and field(pj()["posterGeneric"]["primaryFields"], "stamps")["value"].startswith("◆◆◆◇"))
    r = http("GET", "/api/owner/card/settings", headers=H)
    adv = (r.json() or {}).get("advanced") or {}
    check("the settings page reads them back", adv.get("poster_footer_color") == "#12AB34" and adv.get("stamp_shape") == "losange")
    check("…with the 5 shapes to choose from",
          [s["key"] for s in adv.get("stamp_shapes", [])] == ["rond", "etoile", "coeur", "carre", "losange"]
          and all(s["full"] and s["empty"] and s["label"] for s in adv["stamp_shapes"]))
    check("the list shows ♥ without the text selector", next(s for s in adv["stamp_shapes"] if s["key"] == "coeur")["full"] == "♥")
    for bad in ("red", "#12AB3", "#GGGGGG", "javascript:1"):
        r = http("PUT", "/api/owner/card/settings", headers=H, json={"poster_footer_color": bad})
        check(f"a bad colour « {bad} » is refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"stamp_shape": "pizza"})
    check(f"an unknown shape is refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"stamp_shape": "", "poster_footer_color": ""})
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("both can be reset (\"\" = default)", r.status_code == 200 and not tpl.get("stamp_shape") and not tpl.get("poster_footer_color"))
    r = http("PUT", "/api/owner/card/settings", json={"stamp_shape": "rond"})
    check(f"no token: refused ({r.status_code})", r.status_code in (401, 403))
    staff = _auth.create_access_token({"sub": "s@bloo.fr", "role": "staff", "tenant_id": "t1"})
    r = http("PUT", "/api/owner/card/settings", headers={"Authorization": "Bearer " + staff}, json={"stamp_shape": "rond"})
    check(f"staff cannot change the card ({r.status_code})", r.status_code == 403)

    # ------------------------------------------------------------------
    print("\nThe painted jauge (iOS 26 strip, Google's banner) in the owner's shape")
    theme = WP.derive_colors({"surface_color": "#1E1B2E", "brand_color": "#FF0000"})

    def strip_red(shape, stamps=3):
        im = img(WP.compose_strip(None, theme, stamps, 10, True, shape=shape))
        y = WP.STRIP_H - 62 + 13 - 4
        return im, sum(1 for x in range(0, WP.STRIP_W) if im.getpixel((x, y))[0] > 200 and im.getpixel((x, y))[1] < 60)

    im, bars = strip_red(None)
    check(f"no shape chosen: the bars of before ({bars} red px)", bars > 200)
    counts = {}
    for shape in WP.STAMP_SHAPES:
        im3, n3 = strip_red(shape, 3)
        im7, n7 = strip_red(shape, 7)
        counts[shape] = (n3, n7)
        check(f"{shape}: painted, and fills with progress ({n3} < {n7})", 0 < n3 < n7)
    check("each shape draws differently", len({c[0] for c in counts.values()}) >= 4)
    _, full = strip_red("rond", 10)
    _, none = strip_red("rond", 0)
    check(f"0 tampons: nothing filled; 10: all filled ({none}, {full})", none == 0 and full > 0)
    im = img(WP.compose_strip(None, theme, 3, 10, True, shape="rond"))
    check("the strip keeps its size", im.size == (WP.STRIP_W, WP.STRIP_H))
    check("50 tampons still fit the strip", img(WP.compose_strip(None, theme, 12, 50, True, shape="etoile")).size == (1125, 432))
    setcard(stamp_shape="etoile")
    a = bundle().read("strip@3x.png")
    setcard(stamp_shape="carre")
    b2 = bundle().read("strip@3x.png")
    check("the iOS 26 strip follows the owner's shape", a != b2)
    unset("stamp_shape")

    # ------------------------------------------------------------------
    print("\nGoogle Wallet")
    def gobj():
        return WP._gw_object(WP._card_payload("FT-JAUGE001"))
    o = gobj()
    lp = o.get("secondaryLoyaltyPoints") or o.get("loyaltyPoints")
    check(f"banner « fidclic » (jauge in it): the row stays « 3 / 10 » ({lp})", lp["balance"]["string"] == "3 / 10")
    check("…no extra jauge module", not any(m["id"] == "jauge" for m in o["textModulesData"]))
    setcard(google_design={"hero": "none"})
    o = gobj()
    lp = o.get("secondaryLoyaltyPoints") or o.get("loyaltyPoints")
    check(f"no banner: the row is the jauge ({lp})", lp["balance"]["string"] == "●●●○○○○○○○" and lp["label"].endswith("3/10"))
    setcard(stamp_shape="coeur")
    lp = (lambda x: x.get("secondaryLoyaltyPoints") or x.get("loyaltyPoints"))(gobj())
    check("…in the owner's shape", lp["balance"]["string"].startswith("♥"))
    unset("stamp_shape")
    setcard(show_stamps=False)
    o = gobj()
    lp = o.get("secondaryLoyaltyPoints") or o.get("loyaltyPoints")
    check(f"« Jauge » style: the row is the jauge, not the reward ({lp})", lp["balance"]["string"] == "●●●○○○○○○○")
    unset("show_stamps")
    setcard(stamps_label="Cafés")
    lp = (lambda x: x.get("secondaryLoyaltyPoints") or x.get("loyaltyPoints"))(gobj())
    check(f"the owner's label on Google too ({lp['label']})", lp["label"] == "Cafés · 3/10")
    unset("stamps_label")
    setcard(show_meter=False)
    o = gobj()
    lp = o.get("secondaryLoyaltyPoints") or o.get("loyaltyPoints")
    check("jauge off: « 3 / 10 », no module", lp["balance"]["string"] == "3 / 10"
          and not any(m["id"] == "jauge" for m in o["textModulesData"]))
    unset("show_meter")
    setcard(google_design={"hero": "fidclic"}, stamp_shape="etoile")
    check("the banner's link changes with the shape (Google re-reads it)", gobj()["heroImage"]["sourceUri"]["uri"].endswith("-etoile"))
    unset("stamp_shape", "google_design")

    # ------------------------------------------------------------------
    print("\nPass Designer template")
    st = http("GET", "/api/owner/card/pass-designer/starter", headers=H).json()
    prog = next((f for f in st["pass"]["posterGeneric"]["primaryFields"] if f["key"] == "JAUGE"), None)
    check(f"the starter's progress is the jauge ({prog})", prog and prog["value"] == "{jauge}" and "{tampons}" in prog["label"])
    r = http("PUT", "/api/owner/card/pass-designer", headers=H,
             json={"name": "Mon design", "pass_json": json.dumps(st["pass"]), "images": st.get("image_data") or {},
                   "source": "editor"})
    check(f"saved ({r.status_code})", r.status_code == 200)
    p = pj()
    prog = field(p["posterGeneric"]["primaryFields"], "JAUGE")
    check(f"filled per customer: {prog and prog['value']} / {prog and prog['label']}",
          prog and prog["value"] == "●●●○○○○○○○" and prog["label"] == "TAMPONS · 3 / 10")
    check("…and it notifies", prog and "%@" in prog.get("changeMessage", ""))
    setcard(stamp_shape="carre")
    check("the template's jauge takes the shape too",
          field(pj()["posterGeneric"]["primaryFields"], "JAUGE")["value"] == "■■■□□□□□□□")
    unset("stamp_shape")
    tpl_bg = PD.best(PD.images(PD.load("t1")), "background")
    files = WP.pass_files(WP._card_payload("FT-JAUGE001"))
    check("the template's background goes out untouched (nothing painted on it)",
          files.get("background@2x.png") == tpl_bg or files.get("background@3x.png") == PD.best(PD.images(PD.load("t1")), "background"))
    check("{jauge} and {tampons} are both placeholders", PD.PLACEHOLDERS.get("jauge") == "meter")
    http("DELETE", "/api/owner/card/pass-designer", headers=H)

    # 2026-10-12: a design made without a jauge (the user's « LOVES / ROLLS
    # ROYCE » one) showed no tampons at all on iOS 27
    def put_design(primary, footer=None):
        pg = {"headerFields": [{"key": "m", "label": "MEMBRE", "value": "{carte}"}], "primaryFields": primary,
              "footerFields": [{"key": "f", "value": "ROYALTY LIVES HERE"}], "backFields": []}
        raw = {"posterGeneric": pg, "barcodes": [{"format": "PKBarcodeFormatQR"}]}
        if footer:
            raw["footerBackgroundColor"] = footer
        r = http("PUT", "/api/owner/card/pass-designer", headers=H,
                 json={"name": "Royal", "pass_json": json.dumps(raw), "images": {}, "source": "editor"})
        assert r.status_code == 200, r.text
    put_design([{"key": "name", "value": "{prenom}"}, {"key": "loves", "label": "LOVES", "value": "ROLLS ROYCE"}])
    prim = pj()["posterGeneric"]["primaryFields"]
    j = field(prim, "jauge")
    check(f"a design without a jauge gets one under the QR ({[f['key'] for f in prim]})",
          j is not None and j["value"] == "●●●○○○○○○○" and j["label"] == "TAMPONS · 3/10" and "%@" in j["changeMessage"])
    check("…after the design's own fields, which stay as they are",
          [f["key"] for f in prim] == ["name", "loves", "jauge"] and prim[1]["value"] == "ROLLS ROYCE")
    setcard(stamp_shape="coeur")
    check("…in the owner's shape", field(pj()["posterGeneric"]["primaryFields"], "jauge")["value"].startswith("♥"))
    unset("stamp_shape")
    setcard(show_meter=False)
    check("jauge switched off: nothing added", field(pj()["posterGeneric"]["primaryFields"], "jauge") is None)
    unset("show_meter")
    put_design([{"key": "name", "value": "{prenom}"}, {"key": "p", "label": "PROGRESSION", "value": "{tampons}"}])
    prim = pj()["posterGeneric"]["primaryFields"]
    check(f"a design showing « 3 / 10 » gets the jauge in that very field ({prim[1]})",
          len(prim) == 2 and prim[1]["key"] == "p" and prim[1]["value"] == "●●●○○○○○○○" and prim[1]["label"] == "TAMPONS · 3/10")
    put_design([{"key": "name", "value": "{prenom}"}, {"key": "j", "label": "MES TAMPONS", "value": "{jauge}"}])
    prim = pj()["posterGeneric"]["primaryFields"]
    check("a design with its own {jauge} is left alone (no second jauge)",
          len(prim) == 2 and prim[1]["label"] == "MES TAMPONS" and prim[1]["value"] == "●●●○○○○○○○")
    put_design([{"key": f"k{i}", "label": f"L{i}", "value": f"v{i}"} for i in range(4)])
    prim = pj()["posterGeneric"]["primaryFields"]
    check("4 fields already (Wallet's maximum): nothing pushed out", len(prim) == 4 and field(prim, "jauge") is None)
    put_design([{"key": "name", "value": "{prenom}"}], footer="rgb(186,13,140)")
    check("the design's own footer colour is what iOS 27 draws",
          pj().get("footerBackgroundColor") == "rgb(186,13,140)")
    check("iOS 26 keeps FidClic's card with its strip", "storeCard" in pj())
    http("DELETE", "/api/owner/card/pass-designer", headers=H)

    # ------------------------------------------------------------------
    print("\nThe « Aperçu »: the editor's draft, and fast")
    r = http("POST", "/api/owner/wallet/preview", headers=H,
             json={"card": {"stamp_shape": "etoile", "poster_footer_color": "#334455"}, "visits": 3, "design": {}})
    d = r.json()
    pg = d["pass_json"]["posterGeneric"]
    check(f"the unsaved shape shows on the preview ({r.status_code})",
          field(pg["primaryFields"], "stamps")["value"] == "★★★☆☆☆☆☆☆☆")
    check("the unsaved footer colour too", d["pass_json"].get("footerBackgroundColor") == "rgb(51, 68, 85)")
    check("the preview ships the poster background", (d.get("images") or {}).get("background", "").startswith("data:image/jpeg"))
    r = http("POST", "/api/owner/wallet/google-preview", headers=H,
             json={"card": {"stamp_shape": "carre", "google_design": {"hero": "none"}}, "visits": 3})
    o = r.json()["object"]
    lp = o.get("secondaryLoyaltyPoints") or o.get("loyaltyPoints")
    check(f"Google's preview shows the jauge when no banner ({lp['balance']['string']})", lp["balance"]["string"] == "■■■□□□□□□□")

    photo = png_data(1600, 1000, (90, 140, 60), "JPEG")
    body = {"card": {"hero_image_url": photo, "hero_mode": "image", "card_name": "A"}, "visits": 3, "design": {}}
    WP._IMG_CACHE.clear()
    t0 = time.perf_counter(); http("POST", "/api/owner/wallet/preview", headers=H, json=body); cold = time.perf_counter() - t0
    body["card"]["card_name"] = "AB"            # typing the name: same images
    t0 = time.perf_counter(); r2 = http("POST", "/api/owner/wallet/preview", headers=H, json=body); warm = time.perf_counter() - t0
    check(f"typing does not rebuild the images: {cold:.2f}s → {warm:.2f}s", warm < cold * 0.6)
    check("…and the preview is still right", r2.status_code == 200 and r2.json()["pass_json"]["logoText"] == "AB")
    body["card"]["stamp_shape"] = "coeur"       # a real change is new work, not a stale image
    s1 = http("POST", "/api/owner/wallet/preview", headers=H, json=body).json()["images"].get("strip")
    body["card"]["stamp_shape"] = "rond"
    s2 = http("POST", "/api/owner/wallet/preview", headers=H, json=body).json()["images"].get("strip")
    check("a changed shape is a new strip (the memory never serves a stale one)", s1 and s2 and s1 != s2)
    WP._IMG_CACHE.clear()
    for i in range(WP._IMG_CACHE_MAX + 20):
        WP.compose_poster(None, {"surface_hex": "#%06x" % (i * 7919 % 0xFFFFFF), "brand_hex": "#D4AF37"})
    check(f"the memory stays bounded ({len(WP._IMG_CACHE)} ≤ {WP._IMG_CACHE_MAX})", len(WP._IMG_CACHE) <= WP._IMG_CACHE_MAX)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
