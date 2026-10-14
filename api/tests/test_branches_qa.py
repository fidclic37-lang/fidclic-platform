"""
Establishments, QA R6 (2026-10-11):
  F26  a point de vente saved with its name only — Adresse, Code postal and
       Ville are marked required;
  F29  Historique (and its CSV) did not say in which establishment each row
       happened;
  F35  Géolocalisation kept the main shop's town (« La Colle-sur-Loup et
       alentours ») for the Paris and Lyon establishments.
(F27 — the menu's list refreshed after a save — is the page's: e2e.)

Run: cd api && /usr/local/bin/python3 tests/test_branches_qa.py
"""
import asyncio
import csv
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-branches-qa")
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

    def http(method, url, store=None, **kw):
        h = {"Authorization": "Bearer " + TOKEN, **({"X-FidClic-Store": store} if store else {})}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=h, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({
        "id": "t1", "slug": "ok", "name": "ok", "plan": "vip", "subscription_status": "active", "is_active": True,
        "city": "La Colle-sur-Loup", "postal_code": "06480", "lat": 43.686, "lng": 7.103,
        "branches": [
            {"id": "main", "name": "ok", "is_main": True, "city": "La Colle-sur-Loup", "postal_code": "06480",
             "street": "1 rue A", "latitude": 43.686, "longitude": 7.103},
            {"id": "paris", "name": "QA Paris", "city": "Paris", "postal_code": "75001", "street": "2 rue B",
             "latitude": 48.86, "longitude": 2.34},
        ]})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    TOKEN = auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})

    print("\nF26 — Adresse, Code postal and Ville are required")
    r = http("POST", "/api/owner/etablissement/stores", json={"name": "QA R6 Branch A Paris"})
    check(f"name only: refused, the missing fields named ({r.json().get('detail')})",
          r.status_code == 400 and r.json()["detail"] == "Complétez : Adresse, Code postal, Ville.")
    r = http("POST", "/api/owner/etablissement/stores", json={"name": "Nice", "street": "4 rue D", "postal_code": "06000"})
    check(f"one missing: named ({r.json().get('detail')})", r.status_code == 400 and r.json()["detail"] == "Complétez : Ville.")
    r = http("POST", "/api/owner/etablissement/stores",
             json={"name": "Nice", "street": "4 rue D", "postal_code": "06000", "city": "Nice"})
    names = [b["name"] for b in db.tenants.find_one({"id": "t1"})["branches"]]
    check(f"complete: saved ({r.status_code})", r.status_code == 200 and "Nice" in names and "QA R6 Branch A Paris" not in names)
    r = http("PUT", "/api/owner/etablissement/stores/paris", json={"name": "QA Paris", "street": "", "postal_code": "75001", "city": "Paris"})
    check(f"an edit that empties the address: refused ({r.status_code})", r.status_code == 400 and "Adresse" in r.json()["detail"])
    # the plan's 3 establishments are used; two more written straight in, as older data
    db.tenants.update_one({"id": "t1"}, {"$push": {"branches": {"$each": [
        {"id": "lyon", "name": "QA Lyon", "city": "Lyon", "postal_code": "69001", "street": "3 rue C",
         "latitude": 45.767, "longitude": 4.834},
        {"id": "old", "name": "Ancien sans adresse", "city": "", "postal_code": "", "street": ""}]}}})
    r = http("PUT", "/api/owner/etablissement/stores/old", json={"status": "closed"})
    check(f"closing an older one without address still works ({r.status_code})", r.status_code == 200)

    print("\nF29 — every history row says where it happened")
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Ana", "barcode_id": "FT-ANA00001", "branch_id": "paris"},
        {"id": "c2", "tenant_id": "t1", "name": "Ben", "barcode_id": "FT-BEN00001", "branch_id": "lyon"},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "branch_id": "paris", "visit_time": now - dt.timedelta(hours=3),
         "amount_paid": 10.0, "points_awarded": 10},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c1", "branch_id": "lyon", "visit_time": now - dt.timedelta(hours=2),
         "amount_paid": 20.0, "points_awarded": 10},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c2", "visit_time": now - dt.timedelta(hours=1),
         "amount_paid": 5.0, "points_awarded": 10},                       # recorded before stores: the main one
    ])
    rows = {r["id"]: r for r in http("GET", "/api/owner/history/activity?tab=scan&per_page=50").json()["rows"]}
    check(f"the visit's own till, not the client's home ({rows['v2']['store']})", rows["v2"]["store"] == "QA Lyon"
          and rows["v1"]["store"] == "QA Paris")
    check(f"an untagged visit: the main establishment ({rows['v3']['store']})", rows["v3"]["store"] == "ok"
          and rows["v3"]["store_id"] == "main")
    out = http("GET", "/api/owner/history/export?tab=scan")
    table = list(csv.reader(io.StringIO(out.content.decode("utf-8-sig")), delimiter=";"))
    check(f"the CSV has « Établissement » and its id ({table[0][:3]})", table[0][1:3] == ["Établissement", "ID établissement"])
    by_store = {}
    for row in table[1:]:
        by_store[row[1]] = by_store.get(row[1], 0) + 1
    check(f"…so a combined export splits by establishment ({by_store})", by_store == {"QA Lyon": 1, "QA Paris": 1, "ok": 1})

    print("\nF35 — the map is named after the establishment chosen")
    g = http("GET", "/api/owner/geo/catchment", store="lyon").json()
    check(f"Lyon: « Lyon et alentours », the marker « QA Lyon / Lyon » ({g.get('local_label')}, {g['shop']})",
          g.get("local_label") == "Lyon et alentours" and g["shop"]["name"] == "QA Lyon" and g["shop"]["city"] == "Lyon")
    local = next((s for s in g.get("scopes") or [] if s["key"] == "local"), {})
    check(f"…and the « local » choice says so too ({local.get('label')})", local.get("label") == "Lyon et alentours")
    g = http("GET", "/api/owner/geo/catchment", store="paris").json()
    check(f"Paris: « Paris et alentours » ({g.get('local_label')})", g.get("local_label") == "Paris et alentours"
          and g["shop"]["name"] == "QA Paris")
    g = http("GET", "/api/owner/geo/catchment", store="main").json()
    check(f"the main one keeps its own town ({g.get('local_label')})", g.get("local_label") == "La Colle-sur-Loup et alentours")


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
