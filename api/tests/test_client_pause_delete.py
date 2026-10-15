"""
Clients › « Mettre en pause » / « Reprendre » / « Supprimer » / « Rétablir »
(user, 2026-10-15).
  • paused: no message of any kind; the card still works at the till.
  • deleted: gone from the lists, kept in the database; the till refuses the
    card; the same phone can sign up again; restorable from « Supprimés ».

Run: cd api && /usr/local/bin/python3 tests/test_client_pause_delete.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-pause-delete")
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
    from features import automations as AU
    from services import client_status as CS

    db = server.db
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.queue_refresh = lambda *a, **k: 0

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Shop", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "Shop"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    for cid, bc, ph in (("c1", "FT-PD000001", "06 11 11 11 11"), ("c2", "FT-PD000002", "06 22 22 22 22")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": bc, "phone": ph,
                                 "visits": 1, "points": 0, "created_at": server.datetime.now(server.timezone.utc)})

    print("1. Pause")
    r = http("POST", "/api/owner/clients/c1/pause", headers=H)
    check(f"paused ({r.status_code})", r.status_code == 200 and db.customers.find_one({"id": "c1"}).get("paused_at"))
    res = server.dispatch_to_customer("t1", {"id": "c1"}, "Promo", "Texte")
    check(f"no push / SMS ({res})", res.get("reason") == "paused" and not res.get("sent"))
    check("no automation (geo included)", not AU.matches("t1", {"targeting": {}}, db.customers.find_one({"id": "c1"}, {"_id": 0})))
    check("…another client still matches", AU.matches("t1", {"targeting": {}}, db.customers.find_one({"id": "c2"}, {"_id": 0})))
    check("dropped from an audience", [p["id"] for p in CS.drop_paused(db, "t1", [{"id": "c1"}, {"id": "c2"}])] == ["c2"])
    card = WP._card_payload("FT-PD000001")["card"]
    check("the Wallet card carries no offer / news", card.get("_paused") and not card.get("campaign_offer") and not card.get("auto_news"))
    rows = http("GET", "/api/owner/clients/list", headers=H).json()
    row = next((x for x in rows.get("rows") or rows.get("clients") or [] if x["id"] == "c1"), {})
    check(f"the list says « En pause » ({row.get('paused')})", row.get("paused") is True)
    r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-PD000001"})
    check(f"the card still works at the till ({r.status_code})", r.status_code == 200)
    r = http("POST", "/api/owner/clients/c1/resume", headers=H)
    check("resumed: messages again", r.status_code == 200 and not db.customers.find_one({"id": "c1"}).get("paused_at")
          and server.dispatch_to_customer("t1", {"id": "c1"}, "Promo", "Texte").get("reason") != "paused")

    print("\n2. Delete")
    r = http("POST", "/api/owner/clients/c2/delete", headers=H)
    check(f"deleted ({r.status_code})", r.status_code == 200 and db.customers.find_one({"id": "c2"}).get("deleted_at"))
    rows = http("GET", "/api/owner/clients/list", headers=H).json()
    ids = [x["id"] for x in rows.get("rows") or rows.get("clients") or []]
    check(f"gone from the list ({ids})", "c2" not in ids and "c1" in ids)
    check("kept in the database", db.customers.find_one({"id": "c2"}) is not None)
    r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-PD000002"})
    check(f"the till refuses the card ({r.status_code})", r.status_code == 410)
    pj = WP.build_pass_json(WP._card_payload("FT-PD000002"))
    check("the Wallet card says « plus active »", "plus active" in str(pj))
    d = http("GET", "/api/owner/clients/deleted", headers=H).json()
    check("listed in « Supprimés »", [c["id"] for c in d["clients"]] == ["c2"])
    r = http("POST", "/api/owner/clients/c2/restore", headers=H)
    check(f"restored ({r.status_code})", r.status_code == 200 and not db.customers.find_one({"id": "c2"}).get("deleted_at"))
    r = http("POST", "/api/owner/scan", headers=H, json={"barcode_id": "FT-PD000002"})
    check(f"…its card works again ({r.status_code})", r.status_code == 200)

    print("\n3. Deleted, then signed up again")
    http("POST", "/api/owner/clients/c2/delete", headers=H)
    r = http("POST", "/api/join/shop", json={"name": "Client c2", "phone": "06 22 22 22 22", "postal_code": "37000",
                                            "birthday": "25/12/1990", "consent": True})
    check(f"the same phone signs up again ({r.status_code})", r.status_code == 200 and r.json().get("barcode_id") != "FT-PD000002")
    r = http("POST", "/api/owner/clients/c2/restore", headers=H)
    check(f"the old card can't come back over the new one ({r.status_code})", r.status_code == 409)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
