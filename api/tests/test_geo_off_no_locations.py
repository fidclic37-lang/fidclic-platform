"""
Géolocalisation OFF means no location on the pass (user, 2026-10-15): with
the switch off and the automation paused, a client still got « Vous êtes près
de ROYAL TRIM LIBERTÉ — pensez à scanner votre carte » on his lock screen —
the card's own « rappel » ignored the switch. Switching it also sends every
card of the account again.

Run: cd api && /usr/local/bin/python3 tests/test_geo_off_no_locations.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-geo-off")
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
    WP.queue_refresh = lambda tid, serials, design_changed=False: queued.append(sorted(serials)) or 0
    WP.drain_refresh = lambda tid, budget=None: {"left": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "geo_enabled": False,
                           "branches": [{"id": "main", "name": "ROYAL TRIM LIBÉRTÉ", "is_main": True,
                                         "latitude": 47.3798, "longitude": 0.6922},
                                        {"id": "pal", "name": "ROYAL TRIM PALISSY", "latitude": 47.3941, "longitude": 0.6848}]})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM LIBÉRTÉ"})   # « rappel » left at its default (on)
    db.automations.insert_one({"tenant_id": "t1", "id": "g1", "scenario": "geo", "status": "paused"})
    for cid, bc, br in (("c1", "FT-GEO00001", "main"), ("c2", "FT-GEO00002", "pal")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": "RDX", "barcode_id": bc, "branch_id": br,
                                 "visits": 0, "points": 0})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def pass_of(cid):
        return WP.build_pass_json(server._serialize_card_payload(db.customers.find_one({"id": cid}, {"_id": 0})))

    pj = pass_of("c1")
    check(f"switch OFF, automation paused: no location on the pass ({pj.get('locations')})", not pj.get("locations"))

    r = http("PUT", "/api/owner/settings/geo", headers=H, json={"geo_enabled": True})
    check(f"switched ON ({r.status_code})", r.status_code == 200)
    check(f"…every card of the account is sent again ({queued})", queued and queued[-1] == ["FT-GEO00001", "FT-GEO00002"])
    pj = pass_of("c1")
    check(f"switch ON, no active automation: the card's « rappel » ({len(pj.get('locations') or [])} spots)",
          pj.get("locations") and "pensez à scanner" in pj["locations"][0]["relevantText"])

    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"location_reminder": False}})
    check("switch ON, « rappel » off: no location", not pass_of("c1").get("locations"))

    queued.clear()
    r = http("PUT", "/api/owner/settings/geo", headers=H, json={"geo_enabled": False})
    check("switched OFF: every card sent again", r.status_code == 200 and queued == [["FT-GEO00001", "FT-GEO00002"]])
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"location_reminder": True}})
    check("switch OFF, « rappel » on: still no location", not pass_of("c1").get("locations"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
