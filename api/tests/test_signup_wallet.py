"""
The signup's « Félicitations » page and the Apple pass (user, 2026-10-13, QA BUG-008):
  • the card shown is the owner's current design — the very pass the Wallet
    gets — read with the customer's own key (GET /api/card/{id}/pass-view);
  • the pass is light: its photo layers are 256-colour PNG (Royal Trim's
    pass weighed 2,6 Mo: 5 s to download even when ready).

Run: cd api && /usr/local/bin/python3 tests/test_signup_wallet.py
"""
import asyncio
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-signup-wallet")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def photo(w, h):
    """A photo-like picture: smooth gradients and noise, the kind PNG keeps big."""
    import random
    from PIL import Image
    random.seed(4)
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            n = random.randint(-18, 18)
            px[x, y] = (max(0, min(255, 120 + x * 120 // w + n)), max(0, min(255, 60 + y * 150 // h + n)),
                        max(0, min(255, 200 - x * 90 // w + n)))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def main():
    import server
    import httpx
    from PIL import Image
    from features import wallet_passes as WP
    from services import card_owner as CO

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "royal", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM", "programme": "stamps",
                                  "reward_threshold_stamps": 10, "brand_color": "#0B0F17"})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-WAL00001", "name": "Léa Martin",
                             "visits": 3, "points": 0})
    key = CO.key_for("FT-WAL00001")

    print("\nThe « Félicitations » page reads the real pass")
    r = http("GET", "/api/card/FT-WAL00001/pass-view")
    check(f"without the card's key: refused ({r.status_code})", r.status_code in (401, 403))
    r = http("GET", "/api/card/FT-WAL00001/pass-view", headers={"X-Card-Key": key})
    check(f"with it: the pass ({r.status_code})", r.status_code == 200)
    v = r.json()
    fields = [f for k in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields") for f in v.get(k) or []]
    values = " ".join(str(f.get("value")) for f in fields)
    check(f"the customer's own name, not the sample's ({v.get('sample')})", v["sample"]["name"] == "Léa Martin"
          and "Marie Dupont" not in values)
    check("the pass's own colours and code", v.get("colors", {}).get("backgroundColor") and v.get("barcode", {}).get("message"))
    check("an unknown card: 404", http("GET", "/api/card/FT-NOPE0000/pass-view", headers={"X-Card-Key": key}).status_code == 404)

    print("\nThe pass is light: photos in 256 colours")
    big = photo(1035, 1515)
    slim = WP._slim_photo(big)
    im = Image.open(io.BytesIO(slim))
    check(f"a photo layer: {len(big) // 1024} KB → {len(slim) // 1024} KB", len(slim) < len(big) * 0.6)
    check(f"…a valid PNG, 256 colours, same size ({im.format}, {im.mode}, {im.size})",
          im.format == "PNG" and im.mode == "P" and im.size == (1035, 1515))
    a, b = Image.open(io.BytesIO(big)).convert("RGB"), im.convert("RGB")
    diff = sum(abs(x - y) for p, q in zip(list(a.getdata())[::997], list(b.getdata())[::997]) for x, y in zip(p, q))
    n = len(list(a.getdata())[::997]) * 3
    check(f"…and looks the same (mean difference {diff / n:.1f} / 255)", diff / n < 12)
    logo = io.BytesIO()
    Image.new("RGBA", (300, 100), (200, 30, 30, 128)).save(logo, "PNG")
    check("a transparent layer (logo) stays exact", WP._slim_photo(logo.getvalue()) == logo.getvalue())
    files = WP.slim_pass_files({"background@3x.png": big, "logo@3x.png": logo.getvalue(), "pass.json": b"{}"})
    check("only the photo layers change", files["background@3x.png"] == slim and files["logo@3x.png"] == logo.getvalue()
          and files["pass.json"] == b"{}")

    print("\nBUG-006 — the campaign photo on the Wallet card only if the owner chose it")
    from datetime import datetime, timezone
    from features import campaigns_page as CP
    check("the switch is off by default", CP.Compose(title="x", message="y").wallet_photo is False)
    from datetime import timedelta
    sent = datetime.now(timezone.utc) - timedelta(minutes=2)
    base = {"tenant_id": "t1", "status": "sent", "wallet_offer": True, "recipient_ids": ["c1"],
            "content": "Jusqu'à dimanche", "image_url": "/api/media/0123456789abcdef0123456789abcdef"}
    db.campaigns.insert_one({**base, "id": "k1", "name": "-20 % sur la coupe", "sent_at": sent})
    card = {}
    WP._attach_campaign_offer(card, db.customers.find_one({"id": "c1"}))
    check("a campaign without the switch: still the card's offer", card.get("campaign_offer", {}).get("title") == "-20 % sur la coupe")
    check("…but not its photo: the card keeps its own picture", WP._campaign_photo(card) is None)
    db.campaigns.insert_one({**base, "id": "k2", "name": "Soirée barbe", "wallet_photo": True,
                             "sent_at": sent + timedelta(minutes=1)})       # the newer one
    card = {}
    WP._attach_campaign_offer(card, db.customers.find_one({"id": "c1"}))
    check(f"switch on: the photo becomes the card's banner ({WP._campaign_photo(card)})",
          WP._campaign_photo(card) == base["image_url"])


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
