"""
The card preview took ~20 s on app.fidclic.com (user, 2026-10-12). What made
it slow, and what stops it now:
  • a dead or slow image link was fetched again on every preview (8 s each);
  • every new server instance rebuilt the poster, the strip and the logos —
    now shared through Mongo (img_cache) for 30 days;
  • the preview sent its photos as PNG (2.5 MB) — now JPEG.

Run: cd api && /usr/local/bin/python3 tests/test_preview_speed.py
"""
import base64
import io
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-preview-speed")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server  # noqa: F401 — wires the database
    import urllib.request
    from features import wallet_passes as WP
    from PIL import Image

    print("A dead image link is not waited for twice")
    calls = []

    def dead(url, timeout=None):
        calls.append((url, timeout))
        raise OSError("timed out")
    real = urllib.request.urlopen
    urllib.request.urlopen = dead
    try:
        WP._MISSED.clear()
        check("the first try gives nothing", WP._fetch_image("https://dead.example/logo.png") is None)
        check("…and waits 4 s at most (was 8)", calls and calls[0][1] == 4)
        WP._fetch_image("https://dead.example/logo.png")
        WP._fetch_image("https://dead.example/logo.png")
        check("the next previews do not fetch it again", len(calls) == 1)
        WP._MISSED["https://dead.example/logo.png"] = time.time() - 301
        WP._fetch_image("https://dead.example/logo.png")
        check("after 5 minutes it is tried again (the link may be back)", len(calls) == 2)
    finally:
        urllib.request.urlopen = real

    print("\nOne server builds the images, every server reuses them")
    im = Image.effect_noise((900, 600), 60).convert("RGB")
    b = io.BytesIO()
    im.save(b, "JPEG")
    raw = b.getvalue()
    theme = WP.derive_colors({"surface_color": "#111111", "brand_color": "#B85C38"})
    WP._IMG_CACHE.clear()
    WP._db.img_cache.delete_many({})
    t0 = time.perf_counter()
    first = WP.compose_poster(raw, theme)
    cold = time.perf_counter() - t0
    check("the poster is built and shared", first and WP._db.img_cache.count_documents({"kind": "poster"}) == 1)
    WP._IMG_CACHE.clear()                                   # a new instance: empty memory
    t0 = time.perf_counter()
    again = WP.compose_poster(raw, theme)
    warm = time.perf_counter() - t0
    check(f"a new instance gets the same poster from the shared cache ({cold:.2f}s → {warm:.3f}s)",
          again == first and warm < cold)
    v1 = WP._png_variants(raw, (100, 50), tight=True)
    WP._IMG_CACHE.clear()
    v2 = WP._png_variants(raw, (100, 50), tight=True)
    check("variants ({'', '@2x', '@3x'}) come back with their keys", v1 == v2 and set(v2) == {"", "@2x", "@3x"})
    doc = WP._db.img_cache.find_one({"kind": "png_variants"})
    check("…stored without an empty field name", doc and all(k.startswith("k") for k in doc["d"]))
    check("the shared cache expires (30 days)",
          any(ix.get("expireAfterSeconds") == 30 * 24 * 3600 for ix in WP._db.img_cache.index_information().values()))
    huge = b"x" * (WP._SHARED_MAX + 1)
    WP._shared_put("poster", "huge", huge)
    check("an image over 12 MB is not stored", WP._db.img_cache.find_one({"_id": "huge"}) is None)

    print("\nThe preview sends photos as JPEG")
    jpg = WP._preview_image("background", first)
    check(f"background: JPEG, smaller than the PNG ({len(jpg) // 1024} KB vs {len(first) * 4 // 3 // 1024} KB)",
          jpg.startswith("data:image/jpeg") and len(jpg) < len(base64.b64encode(first)))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
