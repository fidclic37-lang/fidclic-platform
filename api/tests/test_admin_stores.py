"""
Super admin › Commerces › one business with several establishments (user,
2026-11-10: « royal trim franchise hai and i cannot see the other shops in the
super admin »).

    « Boutiques » tab   GET /api/admin/commerces/{tid}/stores — each open
                        establishment with its clients, visits, cards and
                        scans of the week.
    One establishment   ?store=<id> on the business page, its clients and its
                        other tabs: the same figures, for that store only —
                        counted like the owner's own pages (store_scope).
    Accéder au compte   ?store=<id> on view-as: the dashboard opens in that
                        store (the tab keeps it, no store picker).

Run: cd api && python3 -u tests/test_admin_stores.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-admin-stores")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    import server
    import auth
    import httpx

    db = server.db
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d, h=0: now - dt.timedelta(days=d, hours=h)        # noqa: E731

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    # Royal Trim: three open establishments and a closed one.
    db.tenants.insert_one({"id": "rt", "slug": "royal-trim", "name": "ROYAL TRIM LIBÉRTÉ", "is_active": True, "plan": "vip",
                           "subscription_status": "active", "created_at": ago(40),
                           "branches": [{"id": "main", "name": "ROYAL TRIM LIBÉRTÉ", "is_main": True, "city": "Tours"},
                                        {"id": "b2", "name": "ROYAL TRIM PL-MONSTRE", "city": "Tours"},
                                        {"id": "b3", "name": "ROYAL TRIM PALISSY", "city": "Tours"},
                                        {"id": "old", "name": "Fermée", "status": "closed"}]})
    db.users.insert_one({"email": "own@rt.fr", "role": "business_owner", "tenant_id": "rt"})
    # One-shop business.
    db.tenants.insert_one({"id": "solo", "slug": "solo", "name": "Café Solo", "is_active": True, "plan": "vip",
                           "subscription_status": "active", "created_at": ago(40)})
    db.users.insert_one({"email": "own@solo.fr", "role": "business_owner", "tenant_id": "solo"})
    db.users.insert_one({"email": "admin@fidclic.com", "role": "super_admin", "tenant_id": None})

    cust = [("c1", "main", "Alice Martin", ago(3)), ("c2", None, "Bruno Petit", ago(20)),
            ("c3", "b2", "Chloé Durand", ago(2)), ("c4", "b2", "David Roux", ago(25)),
            ("gone", "b2", "Effacé", ago(2))]
    for cid, b, name, created in cust:
        doc = {"id": cid, "tenant_id": "rt", "name": name, "visits": 2, "tier": "bronze", "created_at": created,
               "last_visit_date": ago(1), "barcode_id": "FT-" + cid.upper()}
        if b:
            doc["branch_id"] = b
        if cid == "gone":
            doc["deleted_at"] = ago(1)
        db.customers.insert_one(doc)
    db.customers.insert_one({"id": "s1", "tenant_id": "solo", "name": "Solo Client", "visits": 1, "created_at": ago(2)})
    visits = [("c1", "main", 1), ("c1", "main", 2), ("c2", None, 3), ("c4", "main", 4),
              ("c3", "b2", 1), ("c3", "b2", 2), ("c3", "b2", 10), ("c4", "b2", 5)]
    for i, (cid, b, d) in enumerate(visits):
        v = {"id": f"v{i}", "tenant_id": "rt", "customer_id": cid, "visit_time": ago(d), "amount_paid": 20, "points_awarded": 1}
        if b:
            v["branch_id"] = b
        db.visits.insert_one(v)
    db.rewards_redeemed.insert_one({"id": "r1", "tenant_id": "rt", "customer_id": "c1", "branch_id": "main", "redeemed_at": ago(2)})
    db.rewards_redeemed.insert_one({"id": "r2", "tenant_id": "rt", "customer_id": "c3", "branch_id": "b2", "redeemed_at": ago(2)})
    db.campaigns.insert_one({"id": "k-b2", "tenant_id": "rt", "name": "Promo Monstre", "status": "sent", "sent_at": ago(3),
                             "store_ids": ["b2"], "recipient_ids": ["c3", "c4"], "targeted_count": 2, "delivered_count": 2})
    db.campaigns.insert_one({"id": "k-all", "tenant_id": "rt", "name": "Ancienne campagne", "status": "sent", "sent_at": ago(5),
                             "recipient_ids": ["c1", "c3"], "targeted_count": 2, "delivered_count": 2})

    admin = auth.create_access_token({"sub": "admin@fidclic.com", "role": "super_admin"})
    A = {"Authorization": "Bearer " + admin}
    owner = auth.create_access_token({"sub": "own@rt.fr", "role": "business_owner", "tenant_id": "rt"})

    print("1. L'onglet « Boutiques »")
    r = http("GET", "/api/admin/commerces/rt/stores", headers=A)
    check(f"answers the super admin ({r.status_code})", r.status_code == 200, r.text[:200])
    d = r.json() if r.status_code == 200 else {}
    rows = {s["id"]: s for s in d.get("stores") or []}
    check("lists the three open establishments, never the closed one", list(rows) == ["main", "b2", "b3"], list(rows))
    check("a business with several establishments says so", d.get("multi") is True)
    m, b2, b3 = rows.get("main", {}), rows.get("b2", {}), rows.get("b3", {})
    check("names each one", m.get("name") == "ROYAL TRIM LIBÉRTÉ" and b2.get("name") == "ROYAL TRIM PL-MONSTRE", (m, b2))
    check("the main one is marked", m.get("is_main") is True and not b2.get("is_main"))
    # clients = who signed up or visited there (store_scope), never a deleted one
    check("Libérté: 3 clients (c1, c2 without a store, c4 who came by)", m.get("clients") == 3, m.get("clients"))
    check("PL-Monstre: 2 clients — the deleted one is not counted", b2.get("clients") == 2, b2.get("clients"))
    check("Palissy: nothing yet", b3.get("clients") == 0 and b3.get("visits_30d") == 0 and b3.get("scans_week") == 0, b3)
    check("visits of 30 days where they were scanned (4 · 4)", m.get("visits_30d") == 4 and b2.get("visits_30d") == 4,
          (m.get("visits_30d"), b2.get("visits_30d")))
    check("scans of the week (Libérté 4, PL-Monstre 3)", m.get("scans_week") == 4 and b2.get("scans_week") == 3,
          (m.get("scans_week"), b2.get("scans_week")))
    check("cards of the week: the clients who joined there (c1 · c3)", m.get("cards_week") == 1 and b2.get("cards_week") == 1,
          (m.get("cards_week"), b2.get("cards_week")))
    check("the latest scan of each (none yet at Palissy)", m.get("last_activity") and b2.get("last_activity") and b3.get("last_activity") is None,
          (m.get("last_activity"), b2.get("last_activity")))
    s = http("GET", "/api/admin/commerces/solo/stores", headers=A).json()
    check("a one-shop business: one row, not multi", len(s.get("stores") or []) == 1 and s.get("multi") is False, s)
    check("unknown business → 404", http("GET", "/api/admin/commerces/nope/stores", headers=A).status_code == 404)

    print("2. Une boutique : la même page, ses chiffres seulement")
    whole = http("GET", "/api/admin/commerces/rt", headers=A).json()
    k = lambda body, key: next((x["value"] for x in body.get("kpis") or [] if x["key"] == key), None)   # noqa: E731
    check("without a store: the whole business (4 clients, 8 visits)", k(whole, "clients") == 4 and k(whole, "visites") == 8,
          (k(whole, "clients"), k(whole, "visites")))
    check("…and says which stores it has", [x["id"] for x in whole.get("store_list") or []] == ["main", "b2", "b3"]
          and whole.get("store") is None, (whole.get("store_list"), whole.get("store")))
    one = http("GET", "/api/admin/commerces/rt?store=b2", headers=A)
    o = one.json()
    check(f"?store=b2 answers ({one.status_code})", one.status_code == 200, one.text[:200])
    check("names the store it shows", (o.get("store") or {}).get("id") == "b2" and (o.get("store") or {}).get("name") == "ROYAL TRIM PL-MONSTRE",
          o.get("store"))
    check("PL-Monstre: 2 clients, 4 visits, 1 reward", k(o, "clients") == 2 and k(o, "visites") == 4 and k(o, "recompenses") == 1,
          (k(o, "clients"), k(o, "visites"), k(o, "recompenses")))
    check("its scans of the week (3)", o.get("scans_week") == 3, o.get("scans_week"))
    check("its months: 4 visits in all", sum(x["visites"] for x in o.get("months") or []) == 4, o.get("months"))
    check("the split adds up to its 2 clients", sum(x["count"] for x in o.get("repartition") or []) == 2 and o.get("total_clients") == 2)
    lib = http("GET", "/api/admin/commerces/rt?store=main", headers=A).json()
    check("Libérté: 3 clients, 4 visits (the old ones without a store included), 1 reward",
          k(lib, "clients") == 3 and k(lib, "visites") == 4 and k(lib, "recompenses") == 1,
          (k(lib, "clients"), k(lib, "visites"), k(lib, "recompenses")))
    check("PL-Monstre's campaigns: its own + the old one for the whole shop", {c["id"] for c in (o.get("campagnes") or {}).get("recent") or []}
          == {"k-b2", "k-all"}, o.get("campagnes"))
    check("Libérté's: the old one only", {c["id"] for c in (lib.get("campagnes") or {}).get("recent") or []} == {"k-all"})
    check("an unknown store → 404, never the whole business", http("GET", "/api/admin/commerces/rt?store=zz", headers=A).status_code == 404)
    check("a closed store → 404", http("GET", "/api/admin/commerces/rt?store=old", headers=A).status_code == 404)
    check("a one-shop business with ?store=main shows itself", http("GET", "/api/admin/commerces/solo?store=main", headers=A).status_code == 200)

    print("3. Ses clients et les autres onglets")
    c = http("GET", "/api/admin/commerces/rt/clients?store=b2", headers=A).json()
    check("Clients › PL-Monstre: its 2 clients only", c.get("total") == 2 and {x["id"] for x in c.get("rows") or []} == {"c3", "c4"}, c)
    c = http("GET", "/api/admin/commerces/rt/clients?store=main&q=alice", headers=A).json()
    check("the search stays inside the store", c.get("total") == 1, c)
    c = http("GET", "/api/admin/commerces/rt/clients?store=b3", headers=A).json()
    check("an empty store: no client, no error", c.get("total") == 0 and c.get("rows") == [], c)
    x = http("GET", "/api/admin/commerces/rt/details?store=b2", headers=A).json()
    check("Fidélité › its tiers add up to its 2 clients", sum(t["count"] for t in (x.get("fidelite") or {}).get("tiers") or []) == 2, x.get("fidelite"))
    check("Fidélité › its rewards (1)", sum(m_["count"] for m_ in (x.get("fidelite") or {}).get("rewards") or []) == 1)
    check("Campagnes › its 2", {c_["id"] for c_ in x.get("campagnes") or []} == {"k-b2", "k-all"}, x.get("campagnes"))
    check("Notifications › out of its 2 clients", (x.get("notifications") or {}).get("total") == 2, x.get("notifications"))
    calls = []
    from features import geolocation as G
    real = G.compute
    G.compute = lambda *a, **k: calls.append(k.get("store_scope") if "store_scope" in k else (a[5] if len(a) > 5 else None)) or {"shop": None, "isochrones": {"bands": [], "total": 0}, "points": []}
    try:
        z1 = http("GET", "/api/admin/commerces/rt/zone?store=b2", headers=A)
        z2 = http("GET", "/api/admin/commerces/rt/zone", headers=A)
        z3 = http("GET", "/api/admin/commerces/rt/zone?store=zz", headers=A)
    finally:
        G.compute = real
    check("Zone de chalandise › that store's clients, centred on it",
          z1.status_code == 200 and len(calls) >= 2 and getattr(calls[0], "single", None) == "b2" and calls[1] is None, (z1.status_code, calls))
    check("zone: unknown store → 404", z3.status_code == 404)
    check("details: unknown store → 404", http("GET", "/api/admin/commerces/rt/details?store=zz", headers=A).status_code == 404)
    check("clients: unknown store → 404", http("GET", "/api/admin/commerces/rt/clients?store=zz", headers=A).status_code == 404)

    print("4. « Accéder au compte » dans cette boutique")
    v = http("POST", "/api/admin/commerces/rt/view-as?store=b2", headers=A)
    vj = v.json()
    check(f"opens ({v.status_code}) and names the store", v.status_code == 200 and (vj.get("store") or {}).get("id") == "b2", vj)
    audit = db.audit_logs.find_one({"action": "admin.view_as", "target": "rt"}, sort=[("_id", -1)]) or {}
    check("the audit keeps which store", (audit.get("meta") or {}).get("store") == "b2", audit.get("meta"))
    H = {"Authorization": "Bearer " + vj.get("token", ""), "X-FidClic-Store": "b2"}
    an = http("GET", "/api/owner/analyses?days=30", headers=H).json()
    check("the account then reads PL-Monstre's figures", (an.get("scope") or {}).get("ids") == ["b2"], an.get("scope"))
    check("view-as without a store still works (whole account)",
          http("POST", "/api/admin/commerces/rt/view-as", headers=A).json().get("store") is None)
    check("view-as with an unknown store → 404", http("POST", "/api/admin/commerces/rt/view-as?store=zz", headers=A).status_code == 404)

    print("5. Qui peut")
    O = {"Authorization": "Bearer " + owner}
    check("the business owner: never (403)", http("GET", "/api/admin/commerces/rt/stores", headers=O).status_code == 403)
    check("no session: never (401)", http("GET", "/api/admin/commerces/rt/stores").status_code == 401)
    check("the owner cannot read another store through ?store= on admin pages",
          http("GET", "/api/admin/commerces/rt?store=b2", headers=O).status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
