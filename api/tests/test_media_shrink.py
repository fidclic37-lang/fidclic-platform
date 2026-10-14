"""
Pictures kept light (2026-10-13): Royal Trim's Apple pass took 30 s on every
cold server — one picture of its design came back from the free cluster in
15,6 s and its « /api/media » link could never be kept by Vercel's edge (4,5 Mo
per answer at most). Pictures are now kept at 2 400 px on the long side; one
stored before is made lighter the first time it is read, under the same link.

Run: cd api && /usr/local/bin/python3 tests/test_media_shrink.py
"""
import asyncio
import base64
import io
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-media-shrink")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def noisy_png(w, h, alpha=False):
    """A photo-like picture PNG keeps big (noise does not compress)."""
    from PIL import Image
    random.seed(7)
    im = Image.frombytes("RGB", (w, h), bytes(random.getrandbits(8) for _ in range(w * h * 3)))
    if alpha:
        im = im.convert("RGBA")
        im.putalpha(Image.new("L", (w, h), 180))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def main():
    import server
    import httpx
    from PIL import Image
    from services import media as M

    db = server.db
    raw_media = M._raw(db.media)

    def http(method, url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url)
        return asyncio.get_event_loop().run_until_complete(run())

    big = noisy_png(3000, 2000)
    print(f"\nA big photo is kept light ({len(big) // 1024} Ko sent)")
    link = M.put("data:image/png;base64," + base64.b64encode(big).decode())
    doc = raw_media.find_one({"_id": link.rsplit("/", 1)[1]})
    kept = M.get(link.rsplit("/", 1)[1], cdn=False)
    im = Image.open(io.BytesIO(kept[1]))
    check(f"stored lighter: {doc['size'] // 1024} Ko, under 4,5 Mo ({doc.get('original_size', 0) // 1024} Ko sent)",
          doc["size"] < len(big) and doc["size"] < 4_500_000 and doc.get("original_size") == len(big))
    check(f"2 400 px on the long side, the same shape ({im.size})", im.size == (2400, 1600))
    check(f"a photo as JPEG ({kept[0]})", kept[0] == "image/jpeg" and im.format == "JPEG")
    again = M.put("data:image/png;base64," + base64.b64encode(big).decode())
    check("the same upload again: the same link, stored once", again == link and raw_media.count_documents({}) == 1)
    r = http("GET", link)
    check(f"/api/media serves it ({r.status_code}, {len(r.content) // 1024} Ko)", r.status_code == 200
          and r.headers["content-type"] == "image/jpeg" and len(r.content) == doc["size"])

    print("\nTransparency and small pictures are kept as they are")
    logo = noisy_png(2600, 1300, alpha=True)
    got = M.get(M.put("data:image/png;base64," + base64.b64encode(logo).decode()).rsplit("/", 1)[1], cdn=False)
    li = Image.open(io.BytesIO(got[1]))
    check(f"a picture with transparency stays PNG with its alpha ({got[0]}, {li.mode}, {li.size})",
          got[0] == "image/png" and li.mode == "RGBA" and max(li.size) == 2400)
    small = noisy_png(400, 300)
    sid = M.put("data:image/png;base64," + base64.b64encode(small).decode()).rsplit("/", 1)[1]
    check("a small picture: byte for byte as sent", M.get(sid, cdn=False)[1] == small)

    print("\nA big picture stored before is made lighter the first time it is read")
    old = noisy_png(4000, 3000)
    raw_media.insert_one({"_id": "ab" * 16, "mime": "image/png", "data": M._blob(old), "size": len(old)})
    M._MEM.pop("ab" * 16, None)
    got = M.get("ab" * 16, cdn=False)
    doc = raw_media.find_one({"_id": "ab" * 16})
    check(f"read lighter ({len(old) // 1024} Ko → {len(got[1]) // 1024} Ko)", len(got[1]) < len(old) / 3)
    check("…and written back under the same link", doc["size"] == len(got[1]) and doc.get("original_size") == len(old)
          and doc["mime"] == "image/jpeg")
    M._MEM.pop("ab" * 16, None)
    check("next read: the light one", M.get("ab" * 16, cdn=False)[1] == got[1])

    print("\nAnything Pillow cannot read is left alone")
    junk = b"\x89PNG not really" * 200_000
    check("unreadable bytes unchanged", M.shrink("image/png", junk) == ("image/png", junk))


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
