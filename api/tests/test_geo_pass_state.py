"""
A pass downloaded while the Géolocalisation was on kept the shop's locations
after it was turned off (user, 2026-10-17: « off hai lekin fir bhi aa rha
hai », ROYAL TRIM LIBERTÉ). The server sent nothing; the iPhone showed the
lock-screen message from the locations still inside the pass, because the
state the phone got was never remembered and turning it off woke no pass.

Run: cd api && /usr/local/bin/python3 tests/test_geo_pass_state.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-geo-state")
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
    import features.wallet_passes as WP
    import features.geo_automation as GA

    db = server.db
    woken = []
    WP.notify_passes = lambda serials, *a, **k: woken.append(sorted(serials))
    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "is_active": True,
                           "subscription_status": "active", "geo_enabled": True,
                           "branches": [{"id": "main", "name": "LIBÉRTÉ", "is_main": True,
                                         "latitude": 47.3798, "longitude": 0.6922}]})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM"})
    db.automations.insert_one({"tenant_id": "t1", "id": "g1", "scenario": "geo", "status": "active"})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "RDX", "barcode_id": "FT-GEO10001",
                             "branch_id": "main", "visits": 0, "points": 0})
    db.pass_registrations.insert_one({"tenant_id": "t1", "serial": "FT-GEO10001", "device": "d1"})

    # the automation's rules hold for this client right now
    state = {"automation_id": "g1", "title": "Tout près", "body": "Passez nous voir", "text": "Tout près — Passez nous voir",
             "button_label": None, "button_url": None, "spots": [(47.3798, 0.6922)], "radius": 200}
    real_for_pass = GA.for_pass
    GA.for_pass = lambda cust, at=None: state if db.automations.find_one({"id": "g1", "status": "active"}) else None

    def payload():
        return server._serialize_card_payload(db.customers.find_one({"id": "c1"}, {"_id": 0}))

    p = payload()
    pj = WP.build_pass_json(p)
    check("geo on: the pass carries the shop's location", bool(pj.get("locations")))
    check("an owner preview remembers nothing", db.customers.find_one({"id": "c1"}).get("geo_pass_key") is None)

    WP._note_geo(p)              # what signed_pass / Google sync do when a phone gets it
    k = db.customers.find_one({"id": "c1"}).get("geo_pass_key")
    check(f"the phone's pass is remembered as carrying them ({k})", k and k not in ("off", "unknown"))

    db.automations.update_one({"id": "g1"}, {"$set": {"status": "paused"}})
    GA.sync_passes(tids=["t1"])
    check(f"turned off: that pass is woken to lose them ({woken})", woken == [["FT-GEO10001"]])
    p = payload()
    check("…and the new pass has no location", not WP.build_pass_json(p).get("locations"))
    WP._note_geo(p)
    check("…remembered off", db.customers.find_one({"id": "c1"}).get("geo_pass_key") == "off")

    woken.clear()
    GA.sync_passes(tids=["t1"])
    check("nothing changed: no pass woken again", woken == [])

    # passes already on phones before this fix: one silent recheck (cron sync)
    db.customers.update_one({"id": "c1"}, {"$set": {"geo_pass_key": "off"}})    # stale: really carries them
    db.tenants.insert_one({"id": "t2", "name": "SANS GEO", "is_active": True})
    db.customers.insert_one({"id": "c9", "tenant_id": "t2", "barcode_id": "FT-NOGEO001"})
    db.pass_registrations.insert_one({"tenant_id": "t2", "serial": "FT-NOGEO001", "device": "d9"})
    woken.clear()
    GA.sync_passes()
    check(f"once: every pass of a shop that had a Géolocalisation is woken ({woken})", woken == [["FT-GEO10001"]])
    check("…a shop that never had one is left alone", db.customers.find_one({"id": "c9"}).get("geo_pass_key") is None)
    woken.clear()
    GA.sync_passes()
    check("…and never again", woken == [])

    GA.for_pass = real_for_pass
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
