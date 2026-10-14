"""
« Nom stylé » (user, 2026-10-13: « MUSEUM mein M bada », each letter its size,
colour and font, symbols too — and it must show in Apple AND Google Wallet).

Run: cd api && /usr/local/bin/python3 tests/test_name_style.py
"""
import asyncio
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-name-style")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
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

    db.tenants.insert_one({"id": "t1", "slug": "museum", "name": "Museum", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "MUSEUM", "surface_color": "#14532D",
                                  "brand_color": "#FFFFFF", "reward_threshold_stamps": 10})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Ryan Notch", "barcode_id": "FT-NAME0001",
                             "visits": 2, "points": 0, "deleted_at": None})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    WP.apple_configured = lambda: True
    WP._sign_manifest = lambda m: b"sig"

    def L(text, over=None):
        over = over or {}
        return [{"c": c, "s": 100, "color": None, "font": None, **over.get(i, {})} for i, c in enumerate(text)]

    def save(style):
        return http("PUT", "/api/owner/card/settings", headers=H, json={"name_style": style})

    def ink_right(png: bytes) -> int:
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        bb = im.getchannel("A").getbbox()
        return bb[2] if bb else 0

    def colors(png: bytes):
        im = Image.open(io.BytesIO(png)).convert("RGBA")
        return {px[:3] for px in im.getdata() if px[3] > 200}

    print("1. Saved, checked")
    museum = L("MUSEUM", {0: {"s": 150, "font": "cinzel", "color": "#D4AF37"}})
    for i in range(1, 6):
        museum[i]["font"] = "cinzel"
    r = save({"letters": museum})
    check(f"saved ({r.status_code})", r.status_code == 200)
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("stored letter by letter", [x["c"] for x in tpl["name_style"]["letters"]] == list("MUSEUM")
          and tpl["name_style"]["letters"][0] == {"c": "M", "s": 150, "color": "#D4AF37", "font": "cinzel"})
    s = http("GET", "/api/owner/card/settings", headers=H).json()["advanced"]
    check("the card page gets it back, with the font list",
          s["name_style"]["letters"][0]["s"] == 150 and {"cinzel", "greatvibes", "bebas"} <= {f["key"] for f in s["name_fonts"]})
    for bad, why in (({"letters": L("AB", {0: {"s": 300}})}, "a size over 200 %"),
                     ({"letters": L("AB", {0: {"s": 20}})}, "a size under 50 %"),
                     ({"letters": L("AB", {0: {"color": "red"}})}, "a colour that is not #RRGGBB"),
                     ({"letters": L("AB", {0: {"font": "comic"}})}, "an unknown font"),
                     ({"letters": [{"c": "AB"}]}, "two characters in one box"),
                     ({"letters": L("X" * 41)}, "more than 40 characters"),
                     ("MUSEUM", "not a letter list")):
        check(f"refused: {why}", save(bad).status_code in (400, 422))
    check("spaces at the ends are dropped", (save({"letters": L(" ♛ ROYAL ")}).status_code == 200
          and "".join(x["c"] for x in db.card_templates.find_one({"tenant_id": "t1"})["name_style"]["letters"]) == "♛ ROYAL"))
    save({"letters": museum})

    print("\n2. Apple: the logo images carry it (iOS 26 and iOS 27)")
    payload = server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0}))
    check("the card payload carries the style", (payload["card"].get("name_style") or {}).get("letters"))
    files = WP.pass_files(payload)
    pj = json.loads(files["pass.json"])
    check("no logoText (Wallet would cut it): the name is in the image", "logoText" not in pj)
    gold = (212, 175, 55)
    check("iOS 26 logo: the gold « M » is drawn", any(max(abs(a - b) for a, b in zip(c, gold)) < 30 for c in colors(files["logo@3x.png"])))
    check("iOS 27 primaryLogo: too", any(max(abs(a - b) for a, b in zip(c, gold)) < 30 for c in colors(files["primaryLogo@3x.png"])))
    plain = WP.name_logo(None, "MUSEUM", (255, 255, 255))["@3x"]
    big = WP.name_logo(None, "MUSEUM", (255, 255, 255), letters=WP.styled_letters({"name_style": {"letters": museum}}))["@3x"]
    check("a styled name differs from the plain one", plain != big)
    z = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(payload)))
    check("the signed pass has it", z.read("logo@3x.png") == files["logo@3x.png"])

    print("\n3. Fonts and symbols")
    for key in WP.NAME_FONTS:
        png = WP.name_logo(None, "", (255, 255, 255), letters=(("A", 100, None, key), ("b", 100, None, key)))["@3x"]
        check(f"{key}: draws", ink_right(png) > 0)
    sym = WP.name_logo(None, "", (255, 255, 255), letters=(("★", 100, "#FFCC00", "greatvibes"), ("A", 100, None, "greatvibes")))["@3x"]
    check("a symbol the font lacks is drawn by the fallback font (yellow star, not a box)",
          any(c[0] > 200 and c[1] > 150 and c[2] < 80 for c in colors(sym)))
    long = WP.name_logo(None, "", (255, 255, 255),
                        letters=tuple((c, 150 if i == 0 else 100, None, "greatvibes") for i, c in enumerate("Royal Trim Palissy Centre Ville")))
    im = Image.open(io.BytesIO(long["@3x"]))
    check(f"a long script name fits the 160 × 50 pt box, never cut ({im.size})", im.size[0] <= 480 and im.size[1] == 150
          and ink_right(long["@3x"]) < im.size[0])
    check("the font files are served to the editor", http("GET", "/api/wallet/name-fonts/cinzel.ttf").status_code == 200
          and http("GET", "/api/wallet/name-fonts/../server.py").status_code == 404
          and http("GET", "/api/wallet/name-fonts/nope.ttf").status_code == 404)

    print("\n4. Google: the same name, as its wide logo")
    WP._gw_issuer = lambda: "333"
    WP._site_url = lambda: "https://app.fidclic.com"
    cls = WP._gw_class(payload)
    uri = ((cls.get("wideProgramLogo") or {}).get("sourceUri") or {}).get("uri") or ""
    check(f"the class carries the name image ({uri[-40:]})", "/name.png" in uri)
    r = http("GET", "/api/wallet/google/t1/name.png")
    check(f"Google's fetch gets the styled name ({r.status_code})", r.status_code == 200
          and any(max(abs(a - b) for a, b in zip(c, gold)) < 30 for c in colors(r.content)))
    v1 = uri
    save({"letters": L("MUSEUM", {0: {"s": 180, "color": "#FF0000"}})})
    payload = server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0}))
    v2 = ((WP._gw_class(payload).get("wideProgramLogo") or {}).get("sourceUri") or {}).get("uri")
    check("a new style: a new image address, so Google fetches it again", v1 != v2)
    pv = http("POST", "/api/owner/wallet/google-preview", headers=H, json={"card": {"name_style": {"letters": museum}}, "visits": 2})
    check("the Google preview shows it", pv.status_code == 200 and (pv.json().get("images") or {}).get("wide"))

    print("\n5. Back to the plain name")
    r = save({})
    check("« Revenir au nom simple »", r.status_code == 200 and not db.card_templates.find_one({"tenant_id": "t1"}).get("name_style"))
    files = WP.pass_files(server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0})))
    check("the logo shows the plain card name again", colors(files["logo@3x.png"]) and not any(
        max(abs(a - b) for a, b in zip(c, (255, 0, 0))) < 30 for c in colors(files["logo@3x.png"])))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
