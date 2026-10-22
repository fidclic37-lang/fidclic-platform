"""
Each establishment's own link and QR — the client's home store (user,
2026-10-12, multi-store « ROYAL TRIM / PALISSY / PL-MONSTER »):
  • /join/<account>/<store>: the signup is that store's member;
  • the account's own link asks « Votre établissement » (several stores);
  • a friend's card: the friend joins the parrain's store;
  • a visit counts where it is scanned, the home store stays;
  • no random store, no visit moved; an older client → first visit's store;
  • the owner (or that store's administrateur) moves a client.

Run: cd api && /usr/local/bin/python3 tests/test_store_links.py
"""
import asyncio
import os
from datetime import datetime, timezone
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-links")
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
    from features import store_links as SL

    db = server.db
    woken = []
    WP.notify_customer = lambda cid, *a, **k: woken.append(cid) or {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True},
                      {"id": "pal", "name": "ROYAL TRIM PALISSY"},
                      {"id": "mon", "name": "ROYAL TRIM PL-MONSTER"},
                      {"id": "old", "name": "ROYAL TRIM ANCIEN", "status": "closed"},
                      {"id": "ins", "name": "Insta"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True},
        {"id": "t3", "slug": "uno", "name": "Uno", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "u1", "name": "Uno Centre"}]},
    ])
    for e, role, t, br in (("o@x.fr", "business_owner", "t1", None), ("a@x.fr", "administrateur", "t1", ["pal", "mon"]),
                           ("m@x.fr", "manager", "t1", ["mon"]), ("r@x.fr", "business_owner", "t2", None)):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t, "active": True, **({"branch_ids": br} if br else {})})
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, ADMIN, MANAGER, OTHER = tok("o@x.fr", "business_owner"), tok("a@x.fr", "administrateur"), \
        tok("m@x.fr", "manager"), tok("r@x.fr", "business_owner", "t2")

    print("1. Each establishment's address")
    pub = http("GET", "/api/join/royal-trim/page").json()
    slugs = {x["id"]: x["slug"] for x in pub["stores"]}
    check(f"from the name, without the account's words ({slugs})", slugs.get("pal") == "palissy" and slugs.get("mon") == "pl-monster")
    check("the main store, named like the account: « principal »", slugs.get("main") == "principal")
    check("a store named like a channel never takes the channel's word", slugs.get("ins") not in ("insta", "instagram"))
    check("a closed store is not offered", "old" not in slugs)
    check("kept once made", db.tenants.find_one({"id": "t1"})["branches"][1]["slug"] == "palissy")
    check("a one-shop account: no question", http("GET", "/api/join/solo/page").json()["stores"] == []
          and http("GET", "/api/join/uno/page").json()["stores"] == [])
    r = http("GET", "/api/owner/join-link", headers=OWNER).json()
    check("the owner's page lists each store's address", {x["slug"] for x in r["stores"]} >= {"palissy", "pl-monster"})

    r = http("PUT", "/api/owner/stores/pal/slug", headers=OWNER, json={"slug": "Palissy Tours"})
    check(f"the owner renames it ({r.status_code} {r.json()})", r.status_code == 200 and r.json()["slug"] == "palissy-tours")
    check("…a store's own word is refused when taken",
          http("PUT", "/api/owner/stores/mon/slug", headers=OWNER, json={"slug": "palissy-tours"}).status_code == 400)
    check("…a channel word is refused", http("PUT", "/api/owner/stores/mon/slug", headers=OWNER, json={"slug": "insta"}).status_code == 400)
    check("…one letter is refused", http("PUT", "/api/owner/stores/mon/slug", headers=OWNER, json={"slug": "x"}).status_code == 400)
    check("…an administrateur cannot", http("PUT", "/api/owner/stores/pal/slug", headers=ADMIN, json={"slug": "abc"}).status_code == 403)
    check("…another account's store is not found", http("PUT", "/api/owner/stores/pal/slug", headers=OTHER, json={"slug": "abc"}).status_code == 404)
    check("…a closed store is not found", http("PUT", "/api/owner/stores/old/slug", headers=OWNER, json={"slug": "abc"}).status_code == 404)

    print("\n2. Signing up through a store's link")
    n = [0]

    def join(slug="royal-trim", **kw):
        n[0] += 1
        body = {"name": f"Client {n[0]}", "phone": f"06{n[0]:08d}", "postal_code": "37000", "birthday": "02/03/1995",
                "consent": True, **kw}
        return http("POST", f"/api/join/{slug}", json=body)

    def home(bc):
        return (db.customers.find_one({"barcode_id": bc}) or {}).get("branch_id")
    r = join(store="palissy-tours")
    pal_client = r.json().get("barcode_id")
    check(f"through PALISSY's link: a PALISSY member ({r.status_code})", r.status_code == 200 and home(pal_client) == "pal")
    r = join(store="mon")
    check("by the store's id too", r.status_code == 200 and home(r.json()["barcode_id"]) == "mon")
    r = join(store="palissy")
    check("the store's old address (renamed) still signs up there — printed QR codes keep working",
          r.status_code == 200 and home(r.json()["barcode_id"]) == "pal")
    r = join()
    d = r.json().get("detail") or {}
    check(f"the account's own link, nothing chosen: « Choisissez votre établissement » ({r.status_code})",
          r.status_code == 400 and (d.get("code") == "store_required" if isinstance(d, dict) else "établissement" in str(d)))
    check("…and no card was made", db.customers.count_documents({"tenant_id": "t1", "name": f"Client {n[0]}"}) == 0)
    r = join(store="nowhere")
    check("an unknown store is refused", r.status_code == 400)
    r = join(store="old")
    check("a closed store is refused", r.status_code == 400)
    r = join(slug="solo")
    check("a one-shop account (no stores): no store asked", r.status_code == 200 and home(r.json()["barcode_id"]) is None)
    r = join(slug="uno")
    check("an account with one store: that store", r.status_code == 200 and home(r.json()["barcode_id"]) == "u1")

    print("\n3. Parrainage: the friend joins the parrain's store")
    r = join(store="mon", parrain_barcode=pal_client)
    check(f"a friend of a PALISSY member, even on another link: PALISSY ({r.status_code})",
          r.status_code == 200 and home(r.json()["barcode_id"]) == "pal")
    r = join(parrain_barcode=pal_client)
    check("…and with no store chosen at all", r.status_code == 200 and home(r.json()["barcode_id"]) == "pal")
    # 2026-10-14 (prod, ROYAL TRIM): a card from before the stores has none; the
    # form shows no store on a friend's link, so the server must never ask
    db.customers.insert_one({"id": "legacy", "tenant_id": "t1", "name": "Mahdi Ancien", "barcode_id": "FT-LEGACY01",
                             "phone": "0611111111", "deleted_at": None})
    r = join(parrain_barcode="FT-LEGACY01")
    check(f"a friend of a card with no store: the main shop, nothing asked ({r.status_code})",
          r.status_code == 200 and home(r.json()["barcode_id"]) == "main")
    db.customers.update_one({"id": "legacy"}, {"$set": {"branch_id": "old"}})
    r = join(parrain_barcode="FT-LEGACY01")
    check("…a parrain whose store has closed: the main shop", r.status_code == 200 and home(r.json()["barcode_id"]) == "main")
    r = join(parrain_barcode="FT-NOSUCH99")
    check(f"…a friend's link with a card number not found: the main shop, never « Choisissez » ({r.status_code})",
          r.status_code == 200 and home(r.json()["barcode_id"]) == "main")
    inv = http("GET", f"/api/card/{pal_client}/inviter").json()
    check(f"the form is told the friend's store, to name it ({inv.get('store')})",
          (inv.get("store") or {}).get("name") == "ROYAL TRIM PALISSY")
    check("…and the main shop for a card from before the stores",
          (http("GET", "/api/card/FT-LEGACY01/inviter").json().get("store") or {}).get("name") == "ROYAL TRIM")
    solo = join(slug="solo").json()["barcode_id"]
    check("a one-shop account: no store to name", http("GET", f"/api/card/{solo}/inviter").json().get("store") is None)

    print("\n4. A visit counts where it is scanned")
    r = http("POST", "/api/owner/scan", headers=OWNER, json={"barcode_id": pal_client, "amount_paid": 5, "branch_id": "mon"})
    v = db.visits.find_one({"customer_id": db.customers.find_one({"barcode_id": pal_client})["id"]}, sort=[("visit_time", -1)])
    check(f"scanned at PL-MONSTER: the visit is PL-MONSTER's ({r.status_code})", r.status_code == 200 and v["branch_id"] == "mon")
    check("…the client stays a PALISSY member", home(pal_client) == "pal")

    print("\n5. Older clients: no random store, no visit moved")
    db.customers.insert_many([
        {"id": "legacy1", "tenant_id": "t1", "name": "Ancien Un", "barcode_id": "FT-LEG1", "visits": 2},
        {"id": "legacy2", "tenant_id": "t1", "name": "Ancien Deux", "barcode_id": "FT-LEG2", "visits": 0}])
    import datetime as dt
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    db.visits.insert_many([
        {"id": "lv1", "tenant_id": "t1", "customer_id": "legacy1", "branch_id": "mon", "visit_time": t0},
        {"id": "lv2", "tenant_id": "t1", "customer_id": "legacy1", "branch_id": "pal", "visit_time": t0 + dt.timedelta(days=3)},
        {"id": "lv3", "tenant_id": "t1", "customer_id": "legacy1", "visit_time": t0 + dt.timedelta(days=5)}])
    server._ensure_branch_assignments("t1")
    check("a client with visits: their first visit's store", home("FT-LEG1") == "mon")
    check("a client with none: the main store", home("FT-LEG2") == "main")
    check("tagged visits keep the store they were scanned in",
          db.visits.find_one({"id": "lv1"})["branch_id"] == "mon" and db.visits.find_one({"id": "lv2"})["branch_id"] == "pal")
    server._backfill_visits_from_customers("t1", ["main", "pal", "mon"])
    check("an untagged old visit gets the home store; the others are untouched",
          db.visits.find_one({"id": "lv3"})["branch_id"] == "mon" and db.visits.find_one({"id": "lv2"})["branch_id"] == "pal")

    print("\n6. Moving a client to another store")
    cid = db.customers.find_one({"barcode_id": pal_client})["id"]
    fiche = http("GET", f"/api/owner/clients/{cid}/fiche", headers=OWNER).json()
    check("the fiche says the home store and where it can go",
          fiche["home_store"]["id"] == "pal" and {c["id"] for c in fiche["home_store"]["choices"]} == {"main", "pal", "mon", "ins"})
    woken.clear()
    r = http("PUT", f"/api/owner/customers/{cid}/home-store", headers=OWNER, json={"branch_id": "main"})
    check(f"the owner moves them ({r.status_code})", r.status_code == 200 and home(pal_client) == "main")
    check("…and their Wallet card refreshes", woken == [cid])
    r = http("PUT", f"/api/owner/customers/{cid}/home-store", headers=ADMIN, json={"branch_id": "pal"})
    check(f"an administrateur cannot take a client from a store it does not have ({r.status_code} {r.text[:60]})",
          r.status_code == 403 and "accès" in r.text)
    r0 = http("PUT", f"/api/owner/customers/{cid}/home-store", headers=OWNER, json={"branch_id": "pal"})
    r = http("PUT", f"/api/owner/customers/{cid}/home-store", headers=ADMIN, json={"branch_id": "mon"})
    check(f"…but moves one between its own stores ({r.status_code})", r.status_code == 200 and home(pal_client) == "mon")
    r = http("PUT", f"/api/owner/customers/{cid}/home-store", headers=ADMIN, json={"branch_id": "main"})
    check("…never to a store it does not have", r.status_code == 403)
    # permissions decide (2026-10-22): the owner gives the manager role only « Voir » here
    db.tenants.update_one({"id": "t1"}, {"$set": {"role_defs.manager.perms.customers": "view"}})
    check("a manager cannot", http("PUT", f"/api/owner/customers/{cid}/home-store", headers=MANAGER,
                                   json={"branch_id": "mon"}).status_code == 403)
    check("a closed store is refused", http("PUT", f"/api/owner/customers/{cid}/home-store", headers=OWNER,
                                            json={"branch_id": "old"}).status_code == 400)
    check("another account's client is not found", http("PUT", f"/api/owner/customers/{cid}/home-store", headers=OTHER,
                                                         json={"branch_id": "pal"}).status_code == 404)
    fa = http("GET", f"/api/owner/clients/{cid}/fiche", headers=ADMIN).json()
    check("the administrateur's fiche offers only its stores", {c["id"] for c in fa["home_store"]["choices"]} == {"pal", "mon"})

    print("\n7. The link page's figures are the chosen store's")
    # the main store's clients from before it had establishments carry no store, and
    # its first visits none either (prod, 2026-10-14: Paramètres 3 clients, Clients 5)
    db.customers.insert_one({"id": "c-old", "tenant_id": "t1", "name": "Ancien", "created_at": datetime.now(timezone.utc)})
    db.visits.insert_many([{"id": f"v-old{i}", "tenant_id": "t1", "customer_id": "c-old",
                            "visit_time": datetime.now(timezone.utc)} for i in range(3)])
    db.visits.insert_one({"id": "v-pal", "tenant_id": "t1", "customer_id": "c-old", "branch_id": "pal",
                          "visit_time": datetime.now(timezone.utc)})
    for sid in ("main", "pal", "mon"):
        st = http("GET", "/api/owner/join-link", headers={**OWNER, "X-FidClic-Store": sid}).json()
        cl = http("GET", "/api/owner/clients/list?per_page=200", headers={**OWNER, "X-FidClic-Store": sid}).json()
        listed = cl.get("total", len(cl.get("rows") or []))
        check(f"{sid}: total = the Clients page's ({st['stats']['total']['value']} = {listed})",
              st["stats"]["total"]["value"] == listed and st["store_id"] == sid)
        till = db.visits.count_documents({"tenant_id": "t1", "branch_id": {"$in": [None, "main"] if sid == "main" else [sid]}})
        check(f"{sid}: scans QR = its till's visits ({st['stats']['qr_scans']['value']} = {till})",
              st["stats"]["qr_scans"]["value"] == till)
    st = http("GET", "/api/owner/join-link", headers={**OWNER, "X-FidClic-Store": "main"}).json()
    check("the old client and its 3 visits count for the main store",
          st["stats"]["qr_scans"]["value"] >= 3 and "c-old" in [r["id"] for r in http(
              "GET", "/api/owner/clients/list?per_page=200", headers={**OWNER, "X-FidClic-Store": "main"}).json()["rows"]])
    http("POST", "/api/join/royal-trim/view", json={"visitor": "visitor-abc-123", "src": "qr", "store": "palissy-tours"})
    v = db.join_views.find_one({"visitor": "visitor-abc-123"})
    check("a visit of a store's page is that store's", v and v.get("store") == "pal")

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
