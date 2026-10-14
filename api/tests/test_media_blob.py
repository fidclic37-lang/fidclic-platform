"""
Pictures in Vercel Blob (2026-10-13, user: « PREVIEW OF LOYALTY CARD KYUN LOAD N
HO RHA »): the free cluster hands a picture back at ~100 Ko/s and Vercel's edge
forgets it at every deploy. With BLOB_READ_WRITE_TOKEN set, a picture also
lives in Blob: the server reads it there, /api/media sends browsers there.
Blob is played here (no network).

Run: cd api && /usr/local/bin/python3 tests/test_media_blob.py
"""
import asyncio
import base64
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-media-blob")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


class Resp:
    def __init__(self, status, body=b"", js=None):
        self.status_code, self.content, self._js, self.text = status, body, js, ""

    def json(self):
        return self._js


def main():
    import server
    import httpx
    from PIL import Image
    from services import media as M

    db = server.db
    raw_media = M._raw(db.media)
    store, puts, gets, full_reads = {}, [], [], []
    up = {"ok": True}

    def fake_put(url, content=None, headers=None, timeout=None):
        puts.append((url, dict(headers or {})))
        if not up["ok"]:
            return Resp(503)
        u = f"https://abc.public.blob.vercel-storage.com/{url.split('pathname=')[1].replace('%2F', '/')}-RAND"
        store[u] = content
        return Resp(200, js={"url": u})

    def fake_get(url, timeout=None, follow_redirects=None):
        gets.append(url)
        return Resp(200, store[url]) if up["ok"] and url in store else Resp(503)

    httpx.put, httpx.get = fake_put, fake_get
    os.environ["BLOB_READ_WRITE_TOKEN"] = "vercel_blob_rw_test"

    real_find_one = raw_media.find_one

    def spy(q, proj=None, *a, **k):
        if proj is None or "data" not in (proj or {}) or (proj or {}).get("data") != 0:
            full_reads.append(q.get("_id"))
        return real_find_one(q, proj, *a, **k)
    raw_media.find_one = spy

    def png(w, h, rgb):
        b = io.BytesIO()
        Image.new("RGB", (w, h), rgb).save(b, "PNG")
        return b.getvalue()

    def http(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request("GET", url)
        return asyncio.get_event_loop().run_until_complete(run())

    print("\nA new picture goes to Blob too")
    pic = png(400, 300, (200, 30, 30))
    link = M.put("data:image/png;base64," + base64.b64encode(pic).decode())
    mid = link.rsplit("/", 1)[1]
    url, headers = puts[-1]
    check(f"uploaded as media/<id>.png, public, Paris store via the API ({url[:60]}…)",
          url.startswith("https://vercel.com/api/blob/?pathname=media%2F" + mid) and url.endswith(".png"))
    check("with the token, the type, a random suffix, a year of cache",
          headers.get("authorization") == "Bearer vercel_blob_rw_test" and headers.get("x-vercel-blob-access") == "public"
          and headers.get("x-content-type") == "image/png" and headers.get("x-add-random-suffix") == "1"
          and headers.get("x-cache-control-max-age") == "31536000")
    doc = real_find_one({"_id": mid})
    check("the cluster keeps its copy and the Blob link", doc.get("blob_url", "").startswith("https://abc.public.blob")
          and doc.get("data"))

    print("\nRead from Blob, not from the cluster")
    M._MEM.clear(); M._mem_size = 0; full_reads.clear(); gets.clear()
    got = M.get(mid)
    check("the picture's bytes, from Blob", got and got[1] == pic and gets == [doc["blob_url"]])
    check("the cluster read without the picture's bytes", mid not in full_reads)

    print("\n/api/media sends the browser to Blob")
    r = http(link)
    check(f"307 to the Blob URL ({r.status_code})", r.status_code == 307 and r.headers["location"] == doc["blob_url"])
    check("…cached a year", "max-age=31536000" in r.headers.get("cache-control", ""))
    r = http(link + "?raw=1")
    check(f"?raw=1: the bytes, same origin (« Ajuster ») ({r.status_code})", r.status_code == 200 and r.content == pic)

    print("\nA picture stored before Blob moves there once")
    old = png(500, 500, (9, 120, 9))
    raw_media.insert_one({"_id": "cd" * 16, "mime": "image/png", "data": M._blob(old), "size": len(old)})
    M._MEM.clear(); M._mem_size = 0; puts.clear()
    got = M.get("cd" * 16)
    check("read from the cluster this once, and uploaded", got[1] == old and len(puts) == 1
          and real_find_one({"_id": "cd" * 16}).get("blob_url"))
    M._MEM.clear(); M._mem_size = 0; full_reads.clear()
    check("next time: from Blob", M.get("cd" * 16)[1] == old and "cd" * 16 not in full_reads)

    print("\nBlob down: the cluster, as before")
    up["ok"] = False
    M._MEM.clear(); M._mem_size = 0
    check("a picture in Blob still read (from the cluster)", M.get(mid)[1] == pic)
    noisy = io.BytesIO()
    Image.frombytes("RGB", (120, 80), os.urandom(120 * 80 * 3)).save(noisy, "PNG")     # over 1 Ko: kept in `media`
    other = M.put("data:image/png;base64," + base64.b64encode(noisy.getvalue()).decode())
    check("a new picture still saved, without a Blob link", other.startswith("/api/media/")
          and not real_find_one({"_id": other.rsplit("/", 1)[1]}).get("blob_url"))
    r = http(other)
    check(f"…and served from here ({r.status_code})", r.status_code == 200)

    print("\nNo token (tests, local): nothing changes")
    del os.environ["BLOB_READ_WRITE_TOKEN"]
    up["ok"] = True
    puts.clear()
    M.put("data:image/png;base64," + base64.b64encode(png(320, 200, (4, 5, 6))).decode())
    check("no upload attempted", not puts)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
