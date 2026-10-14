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
    # 2026-10-13: the free cluster hands megabytes back in seconds — a photo is rebuilt, never fetched
    check("the poster is built, and not stored in the database (a photo: rebuilt is faster)",
          first and WP._db.img_cache.count_documents({"kind": "poster"}) == 0)
    WP._IMG_CACHE.clear()                                   # a new instance: empty memory
    t0 = time.perf_counter()
    again = WP.compose_poster(raw, theme)
    warm = time.perf_counter() - t0
    check(f"a new instance builds the very same poster ({cold:.2f}s → {warm:.2f}s)", again == first)
    v1 = WP._png_variants(raw, (100, 50), tight=True)
    WP._IMG_CACHE.clear()
    v2 = WP._png_variants(raw, (100, 50), tight=True)
    check("variants ({'', '@2x', '@3x'}) come back with their keys", v1 == v2 and set(v2) == {"", "@2x", "@3x"})
    WP.name_logo(raw, "ROYAL TRIM", (255, 255, 255))
    check("nothing is written to the database for an image (a write cost 4.5 s on the free cluster)",
          WP._db.img_cache.count_documents({}) == 0)
    check("the shared cache expires (30 days)",
          any(ix.get("expireAfterSeconds") == 30 * 24 * 3600 for ix in WP._db.img_cache.index_information().values()))
    huge = b"x" * (WP._SHARED_MAX + 1)
    WP._shared_put("poster", "huge", huge)
    check("an image over 12 MB is not stored", WP._db.img_cache.find_one({"_id": "huge"}) is None)

    print("\nThe preview sends photos as JPEG")
    jpg = WP._preview_image("background", first)
    check(f"background: JPEG, smaller than the PNG ({len(jpg) // 1024} KB vs {len(first) * 4 // 3 // 1024} KB)",
          jpg.startswith("data:image/jpeg") and len(jpg) < len(base64.b64encode(first)))

    print("\nA picture kept in `media` is read once per server, not once per use")
    from services import media as M
    reads = []
    real_get = M._raw

    class Spy:
        def __init__(self, coll):
            self.coll = coll

        def find_one(self, *a, **k):
            reads.append(1)
            return self.coll.find_one(*a, **k)

        def __getattr__(self, n):
            return getattr(self.coll, n)
    M._raw = lambda coll: Spy(real_get(coll)) if getattr(real_get(coll), "name", "") == "media" else real_get(coll)
    try:
        M._MEM.clear()
        M._mem_size = 0
        ref = M.put("data:image/png;base64," + base64.b64encode(first).decode())
        M._MEM.clear()                          # a new server: nothing in memory yet
        M._mem_size = 0
        reads.clear()
        for _ in range(5):
            WP._fetch_image(ref)
        check(f"five uses, one read from the database ({len(reads)})", len(reads) == 1)
        kept = M.shrink("image/png", first)[1]      # what `media` keeps (lighter when big, 2026-10-13)
        check("…the same bytes every time", WP._fetch_image(ref) == kept)
        check("a link that is not a picture of ours reads nothing", M.get("not-an-id") is None)
    finally:
        M._raw = real_get

    print("\nOn Vercel a picture comes from the edge (60 ms), not from the free cluster (seconds)")
    import urllib.request as UR

    class Resp:
        status = 200
        headers = {"Content-Type": "image/png"}

        def __init__(self, raw):
            self.raw = raw

        def read(self):
            return self.raw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    asked = []
    real_open = UR.urlopen
    os.environ["VERCEL"] = "1"
    real_site = WP._site_url
    WP._site_url = lambda: "https://app.fidclic.com"
    M._raw = lambda coll: Spy(real_get(coll)) if getattr(real_get(coll), "name", "") == "media" else real_get(coll)
    try:
        M._MEM.clear(); M._mem_size = 0; reads.clear()
        UR.urlopen = lambda req, timeout=None: asked.append(req.full_url) or Resp(b"EDGE")
        got = M.get(ref.split("/")[-1])
        check("read from the edge copy of « /api/media/<id> », no database read",
              got == ("image/png", b"EDGE") and asked and asked[0].endswith(ref.split("/")[-1]) and not reads)
        M._MEM.clear(); M._mem_size = 0; reads.clear()

        def down(req, timeout=None):
            raise OSError("edge down")
        UR.urlopen = down
        check("the edge unreachable: the database, as before", M.get(ref.split("/")[-1])[1] == M.shrink("image/png", first)[1]
              and len(reads) == 1)
        M._MEM.clear(); M._mem_size = 0; reads.clear(); asked.clear()
        UR.urlopen = lambda req, timeout=None: asked.append(1) or Resp(b"EDGE")
        M.get(ref.split("/")[-1], cdn=False)
        check("the « /api/media » route itself never asks the edge (it IS the edge's source)", not asked and len(reads) == 1)
    finally:
        UR.urlopen = real_open
        os.environ.pop("VERCEL", None)
        WP._site_url = real_site
        M._raw = real_get
        M._MEM.clear(); M._mem_size = 0

    print("\nA card's pictures are fetched together, not one after the other")
    import threading
    import time as _t
    ids = []
    for i in range(4):
        im = Image.effect_noise((120, 120), 50 + i).convert("RGB")      # over 1 KB: stored in `media`
        b = io.BytesIO()
        im.save(b, "PNG")
        ids.append(M.put("data:image/png;base64," + base64.b64encode(b.getvalue()).decode()))
    M._MEM.clear(); M._mem_size = 0
    seen, threads = [], set()
    real_g = M.get

    def slow_get(mid, cdn=True):
        seen.append(mid)
        threads.add(threading.get_ident())
        _t.sleep(0.3)                               # a cold picture
        return real_g(mid, cdn)
    M.get = slow_get
    try:
        t0 = _t.perf_counter()
        n = M.prefetch({"logo_url": ids[0], "poster_image_url": ids[1]}, {"images": [{"data": ids[2]}, {"data": ids[3]}, {"data": ids[0]}]})
        took = _t.perf_counter() - t0
    finally:
        M.get = real_g
    check(f"4 pictures (one linked twice): 4 fetches ({n}, {len(seen)})", n == 4 and len(seen) == 4)
    check(f"…at the same time, not 4 × 0.3 s ({took:.2f}s, {len(threads)} threads)", took < 0.8 and len(threads) > 1)
    check("…all in memory afterwards", all(i.split("/")[-1] in M._MEM for i in ids))
    check("nothing to fetch the second time", M.prefetch({"logo_url": ids[0]}) == 0)

    print("\nThe establishments of an account: read once per preview")
    from features import store_cards as SC
    SC.forget()
    WP._db.tenants.insert_one({"id": "tz", "branches": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]})
    n = []
    real_find = WP._db.tenants.find_one
    WP._db.tenants.find_one = lambda *a, **k: n.append(1) or real_find(*a, **k)
    try:
        for _ in range(10):
            SC.store_name("tz", "a")
            SC.card_off("tz", "b")
        check(f"20 questions, {len(n)} read", len(n) == 1)
        SC.forget("tz")
        SC.store_name("tz", "a")
        check("…and read again once an establishment changed", len(n) == 2)
    finally:
        WP._db.tenants.find_one = real_find

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
