"""
The name beside the logo, large and on one line (user, 2026-10-14: « naam
chhota kyun ho jaata hai … ek hi line mein, bada, bina crop »). Apple gives the
logo and the name 160 × 50 pt together, so the owner chooses:
  • « Taille du logo à côté du nom »: 0–100 % (0 = the name alone);
  • « Police du nom »: a narrow font writes a long name larger;
  • no 20 pt ceiling: a short name fills the 50 pt height.
In Apple (iOS 26 logo, iOS 27 primaryLogo) and Google (wide logo) alike.

Run: cd api && /usr/local/bin/python3 tests/test_name_size.py
"""
import asyncio
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-name-size")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    import features.wallet_passes as WP
    from PIL import Image

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    logo = Image.new("RGBA", (320, 242), (200, 160, 40, 255))
    b = io.BytesIO()
    logo.save(b, "PNG")
    raw = b.getvalue()
    LONG = "ROYAL TRIM PALISSY"

    def ink(png):
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        white = Image.new("L", im.size, 0)
        px = im.load()
        wp = white.load()
        for y in range(im.height):
            for x in range(im.width):
                r, g, bl, a = px[x, y]
                if a > 128 and r > 230 and g > 230 and bl > 230:
                    wp[x, y] = 255
        return white.getbbox()                     # the name's ink (white), not the logo's

    def text_height(png):
        bb = ink(png)
        return (bb[3] - bb[1]) if bb else 0

    print("1. A long name: the smaller the logo, the larger the name")
    full = WP.name_logo(raw, LONG, (255, 255, 255))["@3x"]
    half = WP.name_logo(raw, LONG, (255, 255, 255), logo_pct=50)["@3x"]
    alone = WP.name_logo(raw, LONG, (255, 255, 255), logo_pct=0)["@3x"]
    narrow = WP.name_logo(raw, LONG, (255, 255, 255), logo_pct=0, font_key="bebas")["@3x"]
    h100, h50, h0, hb = text_height(full), text_height(half), text_height(alone), text_height(narrow)
    check(f"logo 100 % → 50 % → 0 %: the name grows ({h100} → {h50} → {h0} px)", h100 < h50 < h0)
    check(f"…and a narrow font (Bebas Neue) larger still ({hb} px, {hb / max(h100, 1):.1f}× the default)", hb > h0 and hb >= 3 * h100)
    for label, png in (("100 %", full), ("0 %", alone), ("Bebas", narrow)):
        im = Image.open(io.BytesIO(png))
        bb = ink(png)
        check(f"{label}: one line, whole, inside Apple's 160 × 50 pt", im.size[0] <= 480 and im.size[1] == 150
              and bb and bb[2] <= im.size[0] and bb[3] <= im.size[1] and (bb[3] - bb[1]) < 150 * 0.8)
    a0 = Image.open(io.BytesIO(alone)).convert("RGBA")
    check("0 %: no logo at all (the name starts at the left edge)", ink(alone)[0] < 10
          and not any(p[:3] == (200, 160, 40) for p in a0.getdata()))

    print("\n2. No 20 pt ceiling: a short name fills the height")
    short = WP.name_logo(raw, "MUSEUM", (255, 255, 255), logo_pct=0, font_key="cinzel")["@3x"]
    check(f"« MUSEUM » alone: capitals {text_height(short)} px high (under the old 20 pt they could not pass ~45 px)", text_height(short) > 60)

    print("\n3. Saved with the card, refused when odd")
    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": LONG, "surface_color": "#000000",
                                  "brand_color": "#FFFFFF", "logo_url": "data:image/png;base64," + __import__("base64").b64encode(raw).decode()})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Léa", "barcode_id": "FT-SIZE0001", "visits": 2,
                             "points": 0, "deleted_at": None})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    adv = http("GET", "/api/owner/card/settings", headers=H).json()["advanced"]
    check("by default: logo 100 %, the default font", adv["name_logo_size"] == 100 and adv["name_font"] == "")
    before = WP.pass_files(server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0})))
    r = http("PUT", "/api/owner/card/settings", headers=H, json={"name_logo_size": 0, "name_font": "bebas"})
    check(f"saved ({r.status_code})", r.status_code == 200)
    adv = http("GET", "/api/owner/card/settings", headers=H).json()["advanced"]
    check("read back", adv["name_logo_size"] == 0 and adv["name_font"] == "bebas")
    check("refused: 150 %", http("PUT", "/api/owner/card/settings", headers=H, json={"name_logo_size": 150}).status_code == 400)
    check("refused: an unknown font", http("PUT", "/api/owner/card/settings", headers=H, json={"name_font": "comic"}).status_code == 400)

    print("\n4. In the Wallets, not only in the preview")
    payload = server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0}))
    after = WP.pass_files(payload)
    check("Apple iOS 26 logo: the larger name", text_height(after["logo@3x.png"]) > 2 * text_height(before["logo@3x.png"]))
    if "primaryLogo@3x.png" in after:
        check("Apple iOS 27 primaryLogo: too", text_height(after["primaryLogo@3x.png"]) > 2 * text_height(before["primaryLogo@3x.png"]))
    check("logoText left out (Wallet would cut it)", "logoText" not in json.loads(after["pass.json"]))
    WP._site_url = lambda: "https://app.fidclic.com"
    u1 = WP._gw_image_url("t1", "name", {"logo_url": "x", "name_logo_size": 100})
    u2 = WP._gw_image_url("t1", "name", {"logo_url": "x", "name_logo_size": 0, "name_font": "bebas"})
    check("Google: a new image address when the size or font change (Google fetches it again)", u1 != u2)
    r = http("GET", "/api/wallet/google/t1/name.png")
    check(f"Google's name image follows the settings ({r.status_code})", r.status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
