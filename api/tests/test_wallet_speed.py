"""
« Add to Apple / Google Wallet takes ages after signing up » (user, 2026-10-12).
What made it slow, and what stops it now:
  • the signed pass carried 3–7 MB of lossless photos — now 6 bits per colour
    (no visible change), about half the size; logos stay exact;
  • the pass was built on the tap — now the card page asks for it as it opens
    (POST /api/card/<id>/wallet-prepare) and the tap gets the kept bytes;
    a visit or a design change since builds a fresh one;
  • Google: five calls to Google on every tap — now once; the link of a card
    Google already has is signed locally, no call at all;
  • the signup's « Ajouter à Apple Wallet » sits above the card now
    (2026-10-16), so the pass and the card's own view are asked for at the same
    instant — each image is built once and the other caller waits for it.

Run: cd api && /usr/local/bin/python3 tests/test_wallet_speed.py
"""
import asyncio
import base64
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-speed")
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
    import httpx
    import features.wallet_passes as WP
    from services import card_owner as CO
    from PIL import Image

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def durl(im, fmt):
        b = io.BytesIO()
        im.save(b, fmt)
        return f"data:image/{fmt.lower()};base64," + base64.b64encode(b.getvalue()).decode()

    photo = Image.open(os.path.join(os.path.dirname(__file__), "..", "..", "public", "brand", "login-hero.jpg")).convert("RGB")
    logo = Image.effect_noise((400, 400), 40).convert("RGBA")
    db.tenants.insert_one({"id": "t1", "slug": "royal", "name": "ROYAL TRIM", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM", "logo_url": durl(logo, "PNG"),
                                  "hero_image_url": durl(photo, "JPEG"), "poster_image_url": durl(photo, "JPEG"),
                                  "surface_color": "#000000", "brand_color": "#FFFFFF", "reward_threshold_stamps": 10})
    BC = "FT-SPEED001"
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Marie Dupont", "barcode_id": BC, "visits": 3,
                             "points": 0, "deleted_at": None})
    KEY = {"X-Card-Key": CO.key_for(BC)}

    WP.apple_configured = lambda: True
    WP._sign_manifest = lambda manifest: b"signature"
    builds = []
    real_build = WP.build_pkpass

    def counting_build(payload):
        builds.append(1)
        return real_build(payload)
    WP.build_pkpass = counting_build

    print("1. The pass is lighter, the logos untouched")
    files = WP.pass_files(WP._card_payload(BC))
    slim = WP.slim_pass_files(files)
    before, after = sum(map(len, files.values())), sum(map(len, slim.values()))
    check(f"photos: {before // 1024} KB → {after // 1024} KB (at least a third less)", after < before * 0.67)
    check("every photo is still a PNG of the same size",
          all(Image.open(io.BytesIO(slim[n])).size == Image.open(io.BytesIO(files[n])).size
              for n in files if n.startswith(("background", "strip"))))
    check("logos, icons and the name image: the very same bytes",
          all(slim[n] == files[n] for n in files if n.startswith(("logo", "icon", "primaryLogo"))))
    check("pass.json unchanged", slim["pass.json"] == files["pass.json"])
    z = zipfile.ZipFile(io.BytesIO(WP.build_pkpass(WP._card_payload(BC))))
    import json
    man = json.loads(z.read("manifest.json"))
    import hashlib
    check("the manifest signs the slim files", all(hashlib.sha1(z.read(n)).hexdigest() == h for n, h in man.items()))

    print("\n2. Ready before the tap")
    builds.clear()
    WP._PKPASS_MEM.clear()
    db.pkpass_cache.delete_many({})
    check("without the card's key: refused", http("POST", f"/api/card/{BC}/wallet-prepare").status_code in (401, 403))
    r = http("POST", f"/api/card/{BC}/wallet-prepare", headers=KEY)
    check(f"the card page prepares it ({r.status_code} {r.json()})", r.status_code == 200 and r.json()["apple"] is True)
    check("…built once", len(builds) == 1)
    r = http("GET", f"/api/card/{BC}/apple-wallet.pkpass", headers=KEY)
    check(f"the tap: the kept pass, nothing built ({r.status_code}, {len(r.content) // 1024} KB)",
          r.status_code == 200 and len(builds) == 1 and r.content[:2] == b"PK")
    WP._PKPASS_MEM.clear()                                  # another server instance
    http("GET", f"/api/card/{BC}/apple-wallet.pkpass", headers=KEY)
    # 2026-10-13: a 2 MB pass is not kept in the free cluster (seconds to read back) — rebuilt
    check("another server instance: built again there (a big pass is not kept in the database)", len(builds) == 2)
    db.customers.update_one({"id": "c1"}, {"$set": {"visits": 4}})
    http("GET", f"/api/card/{BC}/apple-wallet.pkpass", headers=KEY)
    check("a visit since: a fresh pass (the tampons are right)", len(builds) == 3)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"card_name": "ROYAL TRIM PALISSY"}})
    http("GET", f"/api/card/{BC}/apple-wallet.pkpass", headers=KEY)
    check("a design change since: a fresh pass", len(builds) == 4)
    http("GET", f"/api/card/{BC}/apple-wallet.pkpass", headers=KEY)
    check("…then kept again", len(builds) == 4)
    check("no megabytes written to the database for it", db.pkpass_cache.count_documents({}) == 0)

    print("\n3. Google: one round with Google, then none")
    calls = []
    WP.google_configured = lambda: True
    WP._gw_issuer = lambda: "333"
    WP._gw_access_token = lambda: calls.append("token") or "tok"
    WP._gw_call = lambda method, path, body, token: calls.append(f"{method} {path.split('/')[1]}") or (404, {})
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    pem = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    WP._gw_sa = lambda: {"client_email": "fidclic@x.iam.gserviceaccount.com", "private_key": pem}
    r = http("POST", f"/api/card/{BC}/wallet-prepare", headers=KEY)
    url = r.json().get("google_url") or ""
    check(f"prepared: the Save link ({len(calls)} calls to Google, once)",
          url.startswith("https://pay.google.com/gp/v/save/") and len(calls) >= 3)
    calls.clear()
    r = http("GET", f"/api/card/{BC}/google-wallet", headers=KEY)
    check(f"the tap: no call to Google at all ({calls})", r.status_code == 200 and calls == []
          and r.json()["url"].startswith("https://pay.google.com/gp/v/save/"))
    db.tenants.update_one({"id": "t1"}, {"$set": {"branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True},
                                                               {"id": "pal", "name": "ROYAL TRIM PALISSY"}]}})
    db.customers.update_one({"id": "c1"}, {"$set": {"branch_id": "pal"}})
    db["card_templates"]._real.insert_one({"tenant_id": "t1", "store_id": "pal", "card_name": "Carte Palissy"})
    calls.clear()
    http("GET", f"/api/card/{BC}/google-wallet", headers=KEY)
    check("the card moved to its store's own design: one full round again", len(calls) >= 3)
    calls.clear()
    http("GET", f"/api/card/{BC}/google-wallet", headers=KEY)
    check("…then none again", calls == [])

    print("\n4. Two requests at the same instant build one image, not two")
    import threading
    import time as _time
    WP._IMG_CACHE.clear()
    builds, outs = [], []
    def slow():
        builds.append(1)
        _time.sleep(0.25)                     # as long as drawing a poster
        return b"poster-bytes"
    def ask():
        outs.append(WP._cached("png_variants", ("one-and-the-same",), slow))
    ths = [threading.Thread(target=ask) for _ in range(4)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    check(f"four callers at once → one build ({len(builds)})", len(builds) == 1)
    check("and all four get the image", outs == [b"poster-bytes"] * 4)
    check("the lock is let go of afterwards", not WP._BUILDING)

    print("\n5. The card's view and the pass at the same instant")
    WP._IMG_CACHE.clear()
    WP._PKPASS_MEM.clear()
    db.pkpass_cache.delete_many({})
    heavy = []
    real_cached = WP._cached
    def counting(kind, parts, make):
        def wrapped():
            heavy.append(kind)
            return make()
        return real_cached(kind, parts, wrapped)
    WP._cached = counting
    try:
        got = {}
        def both(name, method, url):
            async def run():                  # a thread of its own needs a loop of its own
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                             base_url="http://test") as ac:
                    return await ac.request(method, url, headers=KEY)
            loop = asyncio.new_event_loop()
            try:
                got[name] = loop.run_until_complete(run()).status_code
            except Exception as exc:          # noqa: BLE001 — the check reports it
                got[name] = repr(exc)[:80]
            finally:
                loop.close()
        pair = [threading.Thread(target=both, args=("view", "GET", f"/api/card/{BC}/pass-view")),
                threading.Thread(target=both, args=("prep", "POST", f"/api/card/{BC}/wallet-prepare?only=apple"))]
        for t in pair:
            t.start()
        for t in pair:
            t.join()
        together = len(heavy)
        check(f"both answered ({got})", got == {"view": 200, "prep": 200})
        WP._IMG_CACHE.clear()
        WP._PKPASS_MEM.clear()
        db.pkpass_cache.delete_many({})
        heavy.clear()
        http("GET", f"/api/card/{BC}/pass-view", headers=KEY)
        http("POST", f"/api/card/{BC}/wallet-prepare?only=apple", headers=KEY)
        one_then_the_other = len(heavy)
        check(f"at once costs no more image work than one after the other "
              f"({together} vs {one_then_the_other})", together <= one_then_the_other)
    finally:
        WP._cached = real_cached

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
