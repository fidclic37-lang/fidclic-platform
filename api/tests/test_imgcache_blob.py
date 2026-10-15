"""
Built images shared through Vercel Blob (2026-10-14: the Hobby plan was paused
for « Fluid Active CPU »). A poster, a strip, the logo with the name — built
once by one server instance, then read from the edge by the others instead of
being built again. Without a Blob token (local, tests): memory only, as before.

Run: cd api && /usr/local/bin/python3 tests/test_imgcache_blob.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-imgcache")
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

    def json(self):
        return {}


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server  # noqa: F401
    import httpx
    import features.wallet_passes as WP
    from services import media as M
    from PIL import Image

    store = {}
    gets, puts = [], []
    real_get, real_put = httpx.get, httpx.put

    def fake_get(url, **kw):
        gets.append(url)
        path = url.split(".com/", 1)[-1]
        return Resp(200, store[path]) if path in store else Resp(404)

    def fake_put(url, content=None, headers=None, **kw):
        from urllib.parse import parse_qs, urlparse
        puts.append((url, headers))
        store[parse_qs(urlparse(url).query)["pathname"][0]] = content
        return Resp(200)

    httpx.get, httpx.put = fake_get, fake_put
    WP._SYNC_PUT = True                         # uploads run in the background in production
    os.environ["BLOB_READ_WRITE_TOKEN"] = "vercel_blob_rw_AbCdStore123_secretpart"
    try:
        print("1. The store's address comes from its token")
        check(f"host ({M._blob_host()})", M._blob_host() == "https://abcdstore123.public.blob.vercel-storage.com")

        print("\n2. Built once, read back by another instance")
        im = Image.effect_noise((900, 600), 60).convert("RGB")
        b = io.BytesIO()
        im.save(b, "JPEG")
        raw = b.getvalue()
        theme = WP.derive_colors({"surface_color": "#111111", "brand_color": "#B85C38"})
        builds = []
        real_make = WP._make_poster
        WP._make_poster = lambda *a, **k: builds.append(1) or real_make(*a, **k)
        WP._IMG_CACHE.clear()
        first = WP.compose_poster(raw, theme)
        check(f"the first instance builds the poster, and keeps it in Blob ({len(puts)} upload)",
              first and len(builds) == 1 and len(puts) >= 1)
        url, headers = puts[0]
        check("…at a fixed address (no random suffix), public, cached a year",
              "imgcache%2F" in url and headers["x-add-random-suffix"] == "0"
              and headers["x-vercel-blob-access"] == "public" and headers["x-cache-control-max-age"] == "31536000")
        WP._IMG_CACHE.clear()                                   # another instance: empty memory
        again = WP.compose_poster(raw, theme)
        check("another instance reads it — nothing built", again == first and len(builds) == 1)
        WP._make_poster = real_make

        print("\n3. Every shape comes back as it was")
        v1 = WP._png_variants(raw, (100, 50), tight=True)
        WP._IMG_CACHE.clear()
        v2 = WP._png_variants(raw, (100, 50), tight=True)
        check("variants {'', '@2x', '@3x'}", v1 == v2 and set(v2) == {"", "@2x", "@3x"})
        n1 = WP.name_logo(raw, "ROYAL TRIM PALISSY", (255, 255, 255), logo_pct=50, font_key="bebas")
        WP._IMG_CACHE.clear()
        n2 = WP.name_logo(raw, "ROYAL TRIM PALISSY", (255, 255, 255), logo_pct=50, font_key="bebas")
        check("the logo with the name", n1 == n2)
        check("pack / unpack: bytes, text, variants", WP._unpack(WP._pack(b"x")) == b"x" and WP._unpack(WP._pack("é")) == "é"
              and WP._unpack(WP._pack({"": b"a", "@2x": b"bb"})) == {"": b"a", "@2x": b"bb"})

        print("\n4. Never in the way")
        httpx.get = lambda url, **kw: (_ for _ in ()).throw(OSError("edge down"))
        WP._IMG_CACHE.clear()
        check("Blob unreachable: the image is simply built", WP.compose_poster(raw, theme) == first)
        httpx.get = fake_get
        check("a key that is not a hash is never fetched", M.cache_get("../etc/passwd") is None)
        check("over 8 MB: not kept", M.cache_put("a" * 40, b"x" * (8 * 1024 * 1024 + 1)) is False)
    finally:
        httpx.get, httpx.put = real_get, real_put
        os.environ.pop("BLOB_READ_WRITE_TOKEN", None)

    print("\n5. Without a Blob token: memory only")
    gets.clear()
    puts.clear()
    WP._IMG_CACHE.clear()
    WP.compose_poster(raw, theme)
    check("no call to Blob at all", not gets and not puts)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
