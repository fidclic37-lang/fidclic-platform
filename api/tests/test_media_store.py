"""
Pictures out of the documents every page reads (2026-10-13). Measured on
production: a shop's signup page spent 1 547 of 1 554 ms in MongoDB for 4
calls — the card held every picture as a data: URL. Pictures now live once in
`media`; the card, campaigns, notifications and signup images keep a link
« /api/media/<id> », served with a year-long cache.

Run: cd api && /usr/local/bin/python3 tests/test_media_store.py
"""
import asyncio
import base64
import io
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-media-store")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def png(w, h, rgb):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(b, "PNG")
    return b.getvalue()


def data_url(raw, mime="image/png"):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def main():
    import server
    import auth
    import httpx
    from services import media as M
    from features import wallet_passes as WP

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    LOGO = png(300, 300, (200, 30, 30))
    PHOTO = png(1600, 1000, (20, 120, 220))
    TINY = "data:image/png;base64,iVBORw0KGgo="

    db.tenants.insert_one({"id": "t1", "slug": "royal", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-MEDIA001", "name": "Marie Dupont",
                             "visits": 3, "points": 30})
    OWNER = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    print("\nA card saved with pictures keeps links, not the pictures")
    r = http("PUT", "/api/owner/card/settings", headers=OWNER, json={
        "logo_url": data_url(LOGO), "hero_image_url": data_url(PHOTO), "poster_image_url": data_url(PHOTO),
        "reward_threshold_stamps": 10})
    check(f"saved ({r.status_code})", r.status_code == 200)
    tpl = M._raw(db.card_templates).find_one({"tenant_id": "t1"})
    check(f"logo → link ({tpl.get('logo_url')})", M.is_ref(tpl.get("logo_url")))
    check("banner and poster → links", M.is_ref(tpl.get("hero_image_url")) and M.is_ref(tpl.get("poster_image_url")))
    check("the same photo is stored once", tpl["hero_image_url"] == tpl["poster_image_url"]
          and db.media.count_documents({}) == 2)
    size = len(json.dumps(tpl, default=str))
    check(f"the card document is small ({size} bytes)", size < 5000)

    print("\nThe browser and the server get the very same pictures")
    r = http("GET", tpl["logo_url"])
    check(f"/api/media serves the bytes ({r.status_code}, {r.headers.get('content-type')})",
          r.status_code == 200 and r.content == LOGO and r.headers.get("content-type") == "image/png")
    cc = r.headers.get("cache-control", "")
    check(f"cached for a year, browser and edge ({cc})", "max-age=31536000" in cc and "s-maxage" in cc and "immutable" in cc)
    check("an unknown id: 404", http("GET", "/api/media/0123456789abcdef0123456789abcdef").status_code == 404)
    check("anything else: 404, never a crash", http("GET", "/api/media/..%2Fetc").status_code == 404)
    check("the server reads a link straight from the database", WP._fetch_image(tpl["logo_url"]) == LOGO)
    check("…also as a full URL of ours", WP._fetch_image("https://app.fidclic.com" + tpl["logo_url"]) == LOGO)
    files = WP.pass_files(WP._card_payload("FT-MEDIA001"))      # what build_pkpass signs
    from PIL import Image
    icon = Image.open(io.BytesIO(files["icon@3x.png"])).convert("RGB").getpixel((40, 40))
    check(f"the Wallet pass is drawn from the stored logo ({icon})", icon[0] > 150 and icon[2] < 80)
    check("…and the poster from the stored photo", Image.open(io.BytesIO(files["background@3x.png"])).convert("RGB")
          .getpixel((517, 900))[2] > 150)

    print("\nSaving the page again sends the links back: still valid")
    s = http("GET", "/api/owner/card/settings", headers=OWNER).json()
    r = http("PUT", "/api/owner/card/settings", headers=OWNER, json={
        **s["design"], **{k: v for k, v in s["advanced"].items() if k == "poster_image_url"}})
    check(f"re-saving with links is accepted ({r.status_code})", r.status_code == 200)
    tpl2 = M._raw(db.card_templates).find_one({"tenant_id": "t1"})
    check("…and changes nothing", tpl2["logo_url"] == tpl["logo_url"] and tpl2["poster_image_url"] == tpl["poster_image_url"])
    r = http("PUT", "/api/owner/card/settings", headers=OWNER, json={"poster_image_url": "javascript:alert(1)"})
    check(f"anything else is still refused ({r.status_code})", r.status_code == 400)
    r = http("PUT", "/api/owner/card/settings", headers=OWNER, json={"logo_url": TINY})
    check("a tiny picture may stay inline", M._raw(db.card_templates).find_one({"tenant_id": "t1"})["logo_url"] == TINY)

    print("\nA campaign's photo, and each recipient's copy")
    camp_photo = data_url(png(800, 400, (10, 200, 10)))
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "name": "Promo", "image_url": camp_photo})
    for i in range(20):
        db.push_notifications.insert_one({"customer_id": f"c{i}", "tenant_id": "t1", "campaign_id": "camp1",
                                          "image_url": camp_photo})
    c = M._raw(db.campaigns).find_one({"id": "camp1"})
    check("the campaign keeps a link", M.is_ref(c["image_url"]))
    links = {d["image_url"] for d in M._raw(db.push_notifications).find({"campaign_id": "camp1"})}
    check(f"20 notifications, one picture stored ({len(links)} link)", len(links) == 1 and M.is_ref(next(iter(links))))
    db.campaigns.update_one({"id": "camp1"}, {"$set": {"image_url": data_url(png(400, 400, (1, 2, 3)))}})
    check("an update with a new photo stores a link too", M.is_ref(M._raw(db.campaigns).find_one({"id": "camp1"})["image_url"]))
    doc = {"id": "camp2", "tenant_id": "t1", "image_url": camp_photo}
    db.campaigns.insert_one(doc)
    check("the caller's document still gets its _id", "_id" in doc)
    html = server._campaign_html("ROYAL", "Sujet", "Bonjour", {"name": "Marie"}, c["image_url"])
    check("an e-mail links the picture in full", "https://" in html and "/api/media/" in html)

    print("\nPictures already stored inline move once")
    raw_tpl = M._raw(db.card_templates)
    raw_tpl.insert_one({"tenant_id": "t9", "logo_url": data_url(LOGO), "store_id": None,
                        "pass_designer": {"images": [{"name": "background@3x.png", "data": data_url(PHOTO)},
                                                     {"name": "icon.png", "data": TINY}]},
                        "google_design": {"hero_image": data_url(PHOTO)}})
    M._raw(db.campaigns).insert_one({"id": "old", "tenant_id": "t9", "image_url": data_url(png(500, 500, (9, 9, 9)))})
    M._raw(db.push_notifications).insert_one({"customer_id": "x", "tenant_id": "t9", "image_url": data_url(png(500, 500, (9, 9, 9)))})
    moved = M.migrate()
    check(f"moved: {moved}", moved.get("card_templates") == 3 and moved.get("campaigns") == 1 and moved.get("push_notifications") == 1)
    t9 = raw_tpl.find_one({"tenant_id": "t9"})
    check("every big picture of the card is a link, nested ones too",
          M.is_ref(t9["logo_url"]) and M.is_ref(t9["pass_designer"]["images"][0]["data"]) and M.is_ref(t9["google_design"]["hero_image"]))
    check("the rest of the document untouched (names, the tiny icon)",
          t9["pass_designer"]["images"][0]["name"] == "background@3x.png" and t9["pass_designer"]["images"][1]["data"] == TINY)
    check("moving again moves nothing", sum(M.migrate().values()) == 0)
    from features import pass_designer as PD
    imgs = PD.images({"images": t9["pass_designer"]["images"]})
    check("a Pass Designer design reads its stored images", imgs.get("background@3x.png") == PHOTO)

    print("\nAt start: once, then the marker")
    db.platform_settings.delete_many({"key": "media_migrated"})
    M._raw(db.campaigns).insert_one({"id": "late", "tenant_id": "t9", "image_url": data_url(png(300, 300, (7, 7, 7)))})
    server._media_migrate_once()
    check("the first start moves what is left and sets the marker",
          M.is_ref(M._raw(db.campaigns).find_one({"id": "late"})["image_url"])
          and (db.platform_settings.find_one({"key": "media_migrated"}) or {}).get("value") == "v1")

    print("\nThe signup page answer is small")
    r = http("PUT", "/api/owner/join-link/image", headers=OWNER, json={"image": data_url(PHOTO)})
    page = http("GET", "/api/join/royal/page")
    check(f"its image is a link ({len(page.content)} bytes)", r.status_code == 200 and M.is_ref(page.json().get("signup_image"))
          and len(page.content) < 5000)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
