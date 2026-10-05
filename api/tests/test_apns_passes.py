"""
Wallet pass update pushes leave as alert / priority 10 (user, 2026-10-05:
notifications that Apple accepted never reached some iPhones, or arrived
silently — background / priority 5 pushes are throttled by the device).

Run: cd api && /usr/local/bin/python3 tests/test_apns_passes.py
"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["APPLE_PASS_TYPE_ID"] = "pass.com.fidclic.test"
os.environ["APPLE_PASS_CERT_B64"] = base64.b64encode(b"-----BEGIN CERTIFICATE-----\nx\n").decode()
os.environ["APPLE_PASS_KEY_B64"] = base64.b64encode(b"-----BEGIN PRIVATE KEY-----\nx\n").decode()

import httpx  # noqa: E402
from services import apns_passes as AP  # noqa: E402

passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    passed += bool(cond); failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))


sent = []


class FakeResp:
    def __init__(self, code, body=None):
        self.status_code, self._body, self.text = code, body or {}, ""

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, content=None):
        sent.append({"url": url, "headers": headers, "content": content, "http2": self.kw.get("http2")})
        if url.endswith("/dead"):
            return FakeResp(410, {"reason": "Unregistered"})
        if url.endswith("/bad"):
            return FakeResp(400, {"reason": "BadDeviceToken"})
        return FakeResp(200)


real = httpx.Client
httpx.Client = FakeClient
try:
    print("\nThe push Apple receives")
    out = AP.push_to_tokens(["tok1", "dead", "bad", "tok1"])
    h = sent[0]["headers"]
    check("production APNs over HTTP/2", sent[0]["url"].startswith("https://api.push.apple.com/3/device/")
          and sent[0]["http2"] is True)
    check("topic = the pass type id", h["apns-topic"] == "pass.com.fidclic.test")
    check("push type alert (not background, which iOS throttles)", h["apns-push-type"] == "alert")
    check("priority 10 — delivered now, not « based on power considerations »", h["apns-priority"] == "10")
    check("payload is the empty {} Wallet expects", sent[0]["content"] == b"{}")
    check("one push per device, duplicates removed", len(sent) == 3)
    check("Unregistered / BadDeviceToken are reported as gone (the caller deletes them)",
          set(out["gone"]) == {"dead", "bad"} and out["sent"] == 1)
finally:
    httpx.Client = real

print("\nWallet may ask with HEAD")
import mongomock  # noqa: E402
os.environ["DISABLE_SEED"] = "1"
with mongomock.patch(servers=(("localhost", 27017),)):
    import asyncio
    import server
    from features import wallet_passes as W

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    r = http("HEAD", "/api/passes/v1/devices/dev1/registrations/pass.com.fidclic.test")
    check(f"HEAD on the device's registrations is answered (got {r.status_code})", r.status_code in (200, 204))
    r = http("HEAD", "/api/passes/v1/passes/pass.com.fidclic.test/FT-NOPE")
    check(f"HEAD on a pass is routed, not 405 (got {r.status_code})", r.status_code != 405)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
