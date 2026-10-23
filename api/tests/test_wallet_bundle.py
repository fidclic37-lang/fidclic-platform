"""
One Blob read per card design (2026-10-15, measured on production: the
« Félicitations » card 6,9 s, « Ajouter à Apple Wallet » 5,5 s on a fresh
instance — 13 to 15 Blob reads in a row, one per picture, not the drawing).
A request's pictures are kept together under the design + tampons; a fresh
instance reads that one object and draws nothing. Uploads never hold the
answer back.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_bundle.py
"""
import base64
import json
import contextlib
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-bundle")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


class Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content, self.text = status, content, ""


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import httpx
    import features.wallet_passes as WP
    from PIL import Image

    db = server.db
    store, gets, puts = {}, [], []

    def fake_get(url, **kw):
        path = url.split(".com/", 1)[-1]
        if path.startswith("imgcache/"):
            gets.append(path)
        return Resp(200, store[path]) if path in store else Resp(404)

    def fake_put(url, content=None, headers=None, **kw):
        from urllib.parse import parse_qs, urlparse
        p = parse_qs(urlparse(url).query)["pathname"][0]
        puts.append(p)
        store[p] = content
        return Resp(200)

    real = httpx.get, httpx.put
    httpx.get, httpx.put = fake_get, fake_put
    os.environ["BLOB_READ_WRITE_TOKEN"] = "vercel_blob_rw_AbCdStore123_secretpart"
    WP._SYNC_PUT = True
    try:
        photo = Image.effect_noise((1200, 800), 50).convert("RGB")
        b = io.BytesIO()
        photo.save(b, "JPEG")
        hero = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
        logo = Image.new("RGBA", (300, 300), (200, 160, 40, 255))
        b = io.BytesIO()
        logo.save(b, "PNG")
        db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM PALISSY", "programme": "stamps",
                                      "surface_color": "#000000", "brand_color": "#FFFFFF", "poster_style": True,
                                      "hero_image_url": hero, "stamp_style": "hexagon", "reward_threshold_stamps": 10,
                                      "logo_url": "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()})
        for cid, bc, v in (("a", "FT-BUNDLE01", 0), ("b", "FT-BUNDLE02", 0), ("c", "FT-BUNDLE03", 4)):
            db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": bc,
                                     "visits": v, "points": 0, "deleted_at": None})
        pay = lambda cid: server._serialize_card_payload(db.customers.find_one({"id": cid}, {"_id": 0}))  # noqa: E731

        def fresh_instance():
            WP._IMG_CACHE.clear()
            gets.clear()
            puts.clear()

        print("1. The first new client of the store: drawn, then kept whole")
        fresh_instance()
        first = WP.pass_files_for_wallet(pay("a"))
        view_a = WP._live_view(pay("a"), "Client a", 0)
        check(f"the pass's pictures and the card's view kept ({len(puts)} uploads)", len(puts) >= 2)
        reference = WP.slim_pass_files(WP.pass_files(pay("a")))
        check("the same files as before this change (pictures and pass.json)",
              first == reference)

        print("\n2. The next new client, on a fresh instance: one read each, nothing drawn")
        fresh_instance()
        drawn = []
        real_make = WP._make_poster
        WP._make_poster = lambda *a, **k: drawn.append(1) or real_make(*a, **k)
        t = time.time()
        view = WP._live_view(pay("b"), "Client b", 0)
        reads_view = len(gets)
        files = WP.pass_files_for_wallet(pay("b"))
        took = time.time() - t
        WP._make_poster = real_make
        check(f"the « Félicitations » card: one Blob read ({reads_view})", reads_view == 1)
        check(f"the Apple pass: one more ({len(gets) - reads_view})", len(gets) - reads_view == 1)
        check("…the poster not drawn again", drawn == [])
        check("…the same pictures as the first client's",
              {k: v for k, v in files.items() if k.endswith(".png")} == {k: v for k, v in first.items() if k.endswith(".png")})
        pj = json.loads(files["pass.json"])
        check("…but this client's own pass.json (number)", "FT-BUNDLE02" in files["pass.json"].decode()
              and "FT-BUNDLE01" not in files["pass.json"].decode())
        check("…the shop's name drawn in the logo, as on the first pass",
              ("logoText" in pj) == ("logoText" in json.loads(first["pass.json"])))
        check("…the view: same pictures, this client's name",
              view["poster"] == {**view_a["poster"]} and view["logo"] == view_a["logo"] and view["sample"]["name"] == "Client b")
        check(f"…nothing uploaded again ({puts})", puts == [])
        check(f"…quick ({took:.2f} s)", took < 1.0)

        print("\n3. Another state of the card: its own pictures, never the wrong ones")
        fresh_instance()
        four = WP.pass_files_for_wallet(pay("c"))
        check("4 tampons: a different strip than 0", four.get("strip@2x.png") != first.get("strip@2x.png"))
        db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_threshold_stamps": 8, "reward_threshold": 8}})
        changed = WP.pass_files_for_wallet(pay("a"))
        check("a design changed (8 tampons a card): the meter drawn again", changed.get("strip@2x.png") != first.get("strip@2x.png")
              and changed == WP.slim_pass_files(WP.pass_files(pay("a"))))

        print("\n4. Uploads in the background")
        WP._SYNC_PUT = False
        real_put = WP._put_blob
        WP._put_blob = lambda k, raw: time.sleep(3.0)      # an upload far slower than the drawing
        fresh_instance()
        db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"surface_color": "#333333"}})
        t = time.time()
        WP.pass_files_for_wallet(pay("a"))
        took = time.time() - t
        WP._put_blob = real_put
        check(f"a new design drawn without waiting for its uploads ({took:.2f} s)", took < 2.5)
        print("\n5. An Android phone prepares Google only")
        built = []
        saved = (WP._owner_only, WP._wallet_in_plan, WP.apple_configured, WP.google_configured, WP.signed_pass, WP.google_link_fast)
        WP._owner_only = lambda *a, **k: None
        WP._wallet_in_plan = lambda *a, **k: True
        WP.apple_configured = WP.google_configured = lambda: True
        WP.signed_pass = lambda *a, **k: built.append("apple")
        WP.google_link_fast = lambda bc: "https://pay.google.com/gp/v/save/x"
        try:
            out = WP.wallet_prepare("FT-BUNDLE02", None, only="google")
            check(f"no Apple pass built for it ({built})", built == [] and out["google_url"])
            WP.wallet_prepare("FT-BUNDLE02", None, only="")
            check("without `only`: both, as before", built == ["apple"])
        finally:
            (WP._owner_only, WP._wallet_in_plan, WP.apple_configured, WP.google_configured,
             WP.signed_pass, WP.google_link_fast) = saved
    finally:
        httpx.get, httpx.put = real
        os.environ.pop("BLOB_READ_WRITE_TOKEN", None)
        WP._SYNC_PUT = False

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
