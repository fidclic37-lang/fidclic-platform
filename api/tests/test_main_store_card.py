"""
A client never given a store belongs to the main store — its card too (user,
2026-10-14: Mahdi, no store, got the account's card « ROYAL TRIM PALISSY »
while Liberté, the main store, was set to « ROYAL TRIM LIBÉRTÉ »; saving
Liberté never refreshed his card).

Run: cd api && /usr/local/bin/python3 tests/test_main_store_card.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-main-store-card")
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
    import features.wallet_passes as WP

    db = server.db
    queued = []
    WP.queue_refresh = lambda tid, serials, design_changed=False: queued.append(sorted(s for s in serials if s)) or 0

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM LIBÉRTÉ", "plan": "vip",
                           "subscription_status": "active", "is_active": True,
                           "branches": [{"id": "main", "name": "ROYAL TRIM LIBÉR"},
                                        {"id": "pal", "name": "ROYAL TRIM PALIS"}]})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    # the account's card (copied into each store once) and each store's own
    db.card_templates.insert_many([
        {"tenant_id": "t1", "card_name": "ROYAL TRIM PALISSY"},
        {"tenant_id": "t1", "store_id": "main", "card_name": "ROYAL TRIM LIBÉRTÉ"},
        {"tenant_id": "t1", "store_id": "pal", "card_name": "ROYAL TRIM PALISSY"},
    ])
    for cid, bc, br in (("c_none", "FT-NONE0001", None), ("c_main", "FT-MAIN0001", "main"), ("c_pal", "FT-PAL00001", "pal")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": "Mahdi", "barcode_id": bc, "visits": 0, "points": 0,
                                 **({"branch_id": br} if br else {})})

    def pass_of(cid):
        return WP.build_pass_json(server._serialize_card_payload(db.customers.find_one({"id": cid}, {"_id": 0})))

    pj = pass_of("c_none")
    check(f"no store → the main store's card: logoText ({pj.get('logoText')})", pj.get("logoText") == "ROYAL TRIM LIBÉRTÉ")
    check("…organizationName too", pj.get("organizationName") == "ROYAL TRIM LIBÉRTÉ")
    check("…and its footer", any(f.get("value") == "ROYAL TRIM LIBÉRTÉ"
                                 for f in (pj.get("posterGeneric") or {}).get("footerFields") or [])
          or "posterGeneric" not in pj)
    check("a Liberté client: Liberté's card", pass_of("c_main").get("logoText") == "ROYAL TRIM LIBÉRTÉ")
    check("a Palissy client: Palissy's card", pass_of("c_pal").get("logoText") == "ROYAL TRIM PALISSY")
    p = server._serialize_card_payload(db.customers.find_one({"id": "c_none"}, {"_id": 0}))
    check(f"the web card says Liberté's name ({p['card'].get('card_name')})", p["card"].get("card_name") == "ROYAL TRIM LIBÉRTÉ")

    queued.clear()
    WP.notify_tenant.__globals__["_SC"].forget("t1")
    with WP._SC.store("t1", "main"):
        WP.notify_tenant("t1")
    check(f"saving Liberté refreshes its clients, those without a store too ({queued})",
          queued == [["FT-MAIN0001", "FT-NONE0001"]])
    queued.clear()
    with WP._SC.store("t1", "pal"):
        WP.notify_tenant("t1")
    check(f"saving Palissy refreshes Palissy's only ({queued})", queued == [["FT-PAL00001"]])

    # a one-shop account: nothing changes
    db.tenants.insert_one({"id": "t2", "slug": "solo", "name": "Solo", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t2", "card_name": "Solo Café"})
    db.customers.insert_one({"id": "c_solo", "tenant_id": "t2", "name": "A", "barcode_id": "FT-SOLO0001", "visits": 0, "points": 0})
    check("one-shop account: its card as before", pass_of("c_solo").get("logoText") == "Solo Café")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
