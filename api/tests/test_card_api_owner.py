"""
A card's number is printed in its QR — at the counter, to friends, in
photos. Until 2026-10-09 that number alone let anyone read the customer's
card (name, e-mail, birthday, spend), change its prefs, delete it, download
or erase all their data (RGPD), download their Wallet pass, subscribe a
browser to their messages, fire a test push or post a review as them.

Now every one of those needs the card's owner key (the customer's own phone,
services/card_owner) or a login of that shop (or a FidClic super admin).

Run: cd api && /usr/local/bin/python3 tests/test_card_api_owner.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-api-owner")
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
    import auth
    import httpx
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.tenants.insert_one({"id": "t2", "slug": "autre", "name": "Autre", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-SECRET01", "name": "Marie Dupont",
                             "email": "marie@exemple.fr", "phone": "0611111111", "birthday": "03-14", "visits": 4,
                             "points": 40, "total_amount_paid": 80.0})
    BC, KEY = "FT-SECRET01", CO.key_for("FT-SECRET01")
    OWN = {"X-Card-Key": KEY}
    tok = lambda role, tid: {"Authorization": "Bearer " + auth.create_access_token({"sub": f"{role}-{tid}@x.fr", "role": role, "tenant_id": tid})}
    for role, tid in (("business_owner", "t1"), ("staff", "t1"), ("business_owner", "t2"), ("super_admin", None)):
        db.users.insert_one({"email": f"{role}-{tid}@x.fr", "role": role, "tenant_id": tid})

    print("1. Le numéro seul ne suffit plus")
    calls = [
        ("GET", f"/api/card/{BC}", {}),
        ("PUT", f"/api/card/{BC}/prefs", {"json": {"push_enabled": False}}),
        ("GET", f"/api/card/{BC}/my-data", {}),
        ("POST", f"/api/card/{BC}/forget-me", {"json": {"confirm": True}}),
        ("DELETE", f"/api/card/{BC}", {}),
        ("POST", f"/api/card/{BC}/wallet-readded", {}),
        ("GET", f"/api/card/{BC}/apple-wallet.pkpass", {}),
        ("GET", f"/api/card/{BC}/google-wallet", {}),
        ("GET", f"/api/card/{BC}/notification-status", {}),
        ("POST", f"/api/card/{BC}/test-push", {}),
        ("POST", "/api/customer/push/subscribe", {"json": {"tenant_slug": "cafe", "barcode_id": BC,
                                                            "subscription": {"endpoint": "https://push.example/x"}}}),
        ("POST", "/api/public/reviews", {"json": {"barcode_id": BC, "rating": 2, "text": "nul"}}),
    ]
    for method, url, kw in calls:
        r = http(method, url, **kw)
        check(f"{method} {url.replace('/api', '')} without the key → 403 ({r.status_code})", r.status_code == 403)
    c = db.customers.find_one({"id": "c1"})
    check("…and nothing happened: not erased, not deleted, no subscription, no review",
          c["name"] == "Marie Dupont" and not c.get("card_deleted_at") and not c.get("gdpr_erased_at")
          and db.push_subscriptions.count_documents({}) == 0 and db.reviews.count_documents({}) == 0)
    r = http("GET", f"/api/card/{BC}", headers={"X-Card-Key": "0" * 20})
    check(f"a made-up key → 403 ({r.status_code})", r.status_code == 403)
    r = http("GET", f"/api/card/{BC}", headers=tok("business_owner", "t2"))
    check(f"another shop's login → 403 ({r.status_code})", r.status_code == 403)

    print("\n2. Le téléphone du client, et la boutique, gardent tout")
    r = http("GET", f"/api/card/{BC}", headers=OWN)
    check(f"the owner key opens the card ({r.status_code})", r.status_code == 200 and r.json()["customer"]["name"] == "Marie Dupont")
    r = http("GET", f"/api/card/{BC}?k={KEY}")
    check(f"…as ?k= too ({r.status_code})", r.status_code == 200)
    r = http("PUT", f"/api/card/{BC}/prefs", headers=OWN, json={"push_enabled": False})
    check(f"prefs change with the key ({r.status_code})", r.status_code == 200)
    r = http("GET", f"/api/card/{BC}/my-data", headers=OWN)
    check(f"RGPD export with the key ({r.status_code})", r.status_code == 200 and r.json()["profile"]["email"] == "marie@exemple.fr")
    r = http("POST", "/api/public/reviews", headers=OWN, json={"barcode_id": BC, "rating": 9, "text": "Top"})
    check(f"a review from the card's own phone ({r.status_code})", r.status_code in (200, 201))
    for who in (("business_owner", "t1"), ("staff", "t1"), ("super_admin", None)):
        r = http("GET", f"/api/card/{BC}", headers=tok(*who))
        check(f"« Voir sa carte » for {who[0]} of the shop ({r.status_code})", r.status_code == 200)
    r = http("DELETE", f"/api/card/{BC}", headers=OWN)
    check(f"the customer deletes their own card ({r.status_code})",
          r.status_code == 200 and db.customers.find_one({"id": "c1"}).get("card_deleted_at"))

    print("\n3. Ce qui reste public, exprès")
    r = http("GET", f"/api/card/{BC}/inviter")
    check(f"the parrainage invite (first name only) ({r.status_code})", r.status_code == 200 and "email" not in r.json())
    r = http("POST", f"/api/card/{BC}/whose", json={})
    check(f"« whose card is this » for the QR scan ({r.status_code})", r.status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
