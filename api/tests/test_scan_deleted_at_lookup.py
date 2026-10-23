"""
A deleted client is said at the till the moment the card is read (QA R7,
2026-10-18: the scanner identified the deleted record, and only the final
save refused it — after the whole visit was typed). Its card answers 410
with the usual words; a restored client reads again.

Run: cd api && /usr/local/bin/python3 tests/test_scan_deleted_at_lookup.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-scan-deleted")
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

    db = server.db

    def get(url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "c", "name": "Café", "plan": "vip", "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps"})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-DEL00001", "name": "Léa", "visits": 2,
                             "points": 0, "deleted_at": dt.datetime.now(dt.timezone.utc)})

    r = get("/api/owner/scan/card", params={"barcode": "FT-DEL00001"})
    check(f"a deleted client's card is refused when read ({r.status_code})", r.status_code == 410)
    check(f"…with the usual words ({r.json().get('detail', '')[:50]}…)", "n'est plus active" in r.json().get("detail", ""))
    db.customers.update_one({"id": "c1"}, {"$set": {"deleted_at": None}})
    r = get("/api/owner/scan/card", params={"barcode": "FT-DEL00001"})
    check(f"restored: it reads again ({r.status_code})", r.status_code == 200 and r.json()["customer"]["name"] == "Léa")
    r = get("/api/owner/scan/card", params={"barcode": "FT-NOPE0001"})
    check("an unknown card still says « Aucun client trouvé »", r.status_code == 404)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
