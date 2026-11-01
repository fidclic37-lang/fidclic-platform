"""
« Import depuis une photo » with an iPhone photo (2026-10-15): Anthropic
answered HTTP 400 « `temperature` is deprecated for this model » (Claude 4.7+
refuse it), and the photo was a .HEIC, which no vision API reads.
- no `temperature` to Anthropic anywhere; effort « low » on the models that have it;
- every photo goes out as a JPEG of at most 1600 px (HEIC too);
- the menu prompt reads any shop's list, a barber's included.

Run: cd api && /usr/local/bin/python3 tests/test_vision_photo.py
"""
import asyncio
import base64
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-vision-photo")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


class Resp:
    def __init__(self, body):
        self.status_code, self._b, self.text = 200, body, json.dumps(body)

    def json(self):
        return self._b


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    import requests
    from PIL import Image
    from services import llm, ocr
    from services.vision_image import for_vision

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    big = Image.effect_noise((4032, 3024), 40).convert("RGB")
    b = io.BytesIO()
    big.save(b, "HEIF", quality=60)
    heic = b.getvalue()

    print("1. Any photo becomes a JPEG a vision model reads")
    out, mime = for_vision(base64.b64encode(heic).decode(), "image/heic")
    im = Image.open(io.BytesIO(base64.b64decode(out)))
    check(f"an iPhone HEIC → JPEG {im.size}", mime == "image/jpeg" and im.format == "JPEG" and max(im.size) == 1600)
    png = io.BytesIO()
    Image.new("RGBA", (300, 200), (0, 0, 0, 0)).save(png, "PNG")
    out, _ = for_vision(base64.b64encode(png.getvalue()).decode(), "image/png")
    px = Image.open(io.BytesIO(base64.b64decode(out))).getpixel((10, 10))
    check(f"a transparent PNG on white, not black {px}", px[0] > 240)
    check("not an image: passed on as it came", for_vision("bm90IGFuIGltYWdl", "image/jpeg") == ("bm90IGFuIGltYWdl", "image/jpeg"))

    print("\n2. What goes to Anthropic: no temperature, effort low where it exists")
    check("Claude Sonnet 5.5: effort low", llm.anthropic_extras("claude-sonnet-5-5") == {"output_config": {"effort": "low"}})
    check("Claude Haiku 4.5: nothing (it refuses effort)", llm.anthropic_extras("claude-haiku-4-5") == {})
    sent = []
    from features import ai_meter as AM            # every provider POST goes through the AI meter's sender
    real_post = AM._send
    AM._send = lambda url, headers, body, timeout: sent.append(body) or (200, Resp(
        {"content": [{"type": "text", "text": '[{"name":"Coupe + barbe+ coiffage","price":29,"category":"Coupe / Coiffage / Barbe"}]'}]}).json())
    old_key = server.ANTHROPIC_API_KEY
    server.ANTHROPIC_API_KEY = "sk-test"
    try:
        server.db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip",
                                      "subscription_status": "active", "is_active": True})
        server.db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
        H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
        r = http("POST", "/api/owner/catalog/parse-menu", headers=H,
                 json={"image_base64": "data:image/heic;base64," + base64.b64encode(heic).decode(), "mime": "image/heic"})
        check(f"the menu photo is read ({r.status_code})", r.status_code == 200 and "Coupe" in r.text)
        body = sent[0] if sent else {}
        check("…no temperature sent", "temperature" not in body)
        check("…effort low, room for a long menu", body.get("output_config") == {"effort": "low"} and body.get("max_tokens") >= 4000)
        img = (body.get("messages") or [{}])[0].get("content", [{}])[0].get("source", {})
        check("…the photo as a JPEG", img.get("media_type") == "image/jpeg"
              and Image.open(io.BytesIO(base64.b64decode(img.get("data", "")))).format == "JPEG")
        prompt = body["messages"][0]["content"][1]["text"]
        check("…a prompt for any shop's list (a barber's too)", "barber" in prompt and "restaurant/cafe menu" not in prompt)
        sent.clear()
        server._call_anthropic("Bonjour")
        check("the text helper sends no temperature either", sent and "temperature" not in sent[0])
    finally:
        AM._send = real_post
        server.ANTHROPIC_API_KEY = old_key

    print("\n3. services/llm and services/ocr (campaign lines, invoices)")
    bodies = []

    class U:
        def __init__(self, req):
            bodies.append(json.loads(req.data))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "{}"}]}).encode()
    import urllib.request as _UR
    real_open = _UR.urlopen
    _UR.urlopen = lambda req, timeout=0: U(req)          # llm and ocr both reach the model through features/ai_meter
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    try:
        llm._call("anthropic", "claude-sonnet-5-5", "", "Une phrase", 100, 0.7)
        check("llm: no temperature, effort low", "temperature" not in bodies[-1] and bodies[-1].get("output_config") == {"effort": "low"})
        prov = ocr._provider_name
        ocr._provider_name = lambda: "anthropic"
        try:
            ocr._call_vision(base64.b64encode(heic).decode(), "image/heic")
        except Exception:
            pass
        ocr._provider_name = prov
        last = bodies[-1]
        src = last["messages"][0]["content"][0]["source"]
        check("ocr: no temperature, the photo as a JPEG", "temperature" not in last and src["media_type"] == "image/jpeg")
    finally:
        _UR.urlopen = real_open
        os.environ.pop("ANTHROPIC_API_KEY", None)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
