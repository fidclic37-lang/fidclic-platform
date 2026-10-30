"""
The Apple pass goes out in one piece, with its length (2026-10-15, measured on
production: a 1,6 Mo pass ready in 27 ms took 3,6 s to arrive — a BytesIO given
to StreamingResponse is sent line by line, about 6 000 writes).

Run: cd api && /usr/local/bin/python3 tests/test_pkpass_one_piece.py
"""
import asyncio
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-pkpass-one-piece")
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
        import server  # noqa: F401
    import features.wallet_passes as WP

    big = os.urandom(1_610_064)
    WP.apple_configured = lambda: True
    WP.signed_pass = lambda bc, payload=None, **kw: big
    r = WP._pkpass_response("FT-ONEPIECE")
    sends = []

    async def run():
        async def receive():
            return {"type": "http.request"}

        async def send(msg):
            sends.append(msg)
        await r({"type": "http", "method": "GET", "headers": []}, receive, send)
    asyncio.get_event_loop().run_until_complete(run())
    bodies = [m for m in sends if m["type"] == "http.response.body"]
    head = dict((k.decode(), v.decode()) for k, v in next(m for m in sends if m["type"] == "http.response.start")["headers"])
    check(f"one body write, not thousands ({len(bodies)})", len(bodies) == 1)
    check("the whole pass", b"".join(m.get("body", b"") for m in bodies) == big)
    check(f"its length announced ({head.get('content-length')})", head.get("content-length") == str(len(big)))
    check("still a pass, still not cached", head.get("content-type") == "application/vnd.apple.pkpass"
          and head.get("cache-control") == "no-store" and "fidclic-FT-ONEPIECE.pkpass" in head.get("content-disposition", ""))
    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
