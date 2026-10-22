"""
Permissions decide, for every business (user, 2026-10-22, AMJAD — an
administrateur with every right on the three stores — saw 6 of the 11
Paramètres tabs): a team account reaches what its role's « Voir » /
« Modifier » give, inside each page too; what they do not give is refused
with « Accès non autorisé » (the page stays in the menu); a change of
permissions applies on the very next request.

Run: cd api && /usr/local/bin/python3 tests/test_permissions_drive_access.py
"""
import asyncio
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-perms-drive")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import role_perms as RP

    db = server.db

    def http(method, url, who, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": who}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for tid, name in (("t1", "ROYAL TRIM"), ("t2", "AUTRE COMMERCE")):        # two businesses, same rules
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": "vip", "subscription_status": "active",
                               "is_active": True, "description": "", "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True},
                                                                                  {"id": "pal", "name": "PALISSY"}]})
    full = {**{k: "edit" for k in RP.PAGE_KEYS}}
    db.tenants.update_one({"id": "t1"}, {"$set": {"role_defs": {"administrateur": {"perms": full}}}})   # « 21 of 21 · edited »
    db.tenants.update_one({"id": "t2"}, {"$set": {"role_defs": {
        "r_lecture": {"label": "Lecture", "perms": {**{k: "none" for k in RP.PAGE_KEYS}, "settings": "view", "dashboard": "view"}},
        "r_rien": {"label": "Caisse", "perms": {**{k: "none" for k in RP.PAGE_KEYS}, "scan": "edit"}}}}})
    users = [("amjad@x.fr", "administrateur", "t1", {}), ("plain@x.fr", "administrateur", "t2", {}),
             ("lect@x.fr", "membre", "t2", {"custom_role": "r_lecture"}), ("caisse@x.fr", "membre", "t2", {"custom_role": "r_rien"})]
    for email, role, tid, extra in users:
        db.users.insert_one({"id": email, "email": email, "role": role, "tenant_id": tid, "active": True, **extra})
    T = {e: "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t}) for e, r, t, _ in users}

    print("1. Every right given: everything, like the owner")
    v = http("GET", "/api/owner/etablissement", T["amjad@x.fr"]).json()
    check(f"AMJAD may edit the whole Établissement ({v.get('can')})",
          v["can"]["brand"] and v["can"]["hours"] and v["can"]["geo"] and v["can"]["add_store"])
    check("…but not the owner's own name", v["can"]["owner_name"] is False)
    r = http("PUT", "/api/owner/etablissement", T["amjad@x.fr"], json={"business": {"description": "Barbier"}})
    check(f"…and saves it ({r.status_code})", r.status_code == 200)
    for path in ("/api/owner/customer-rules", "/api/owner/privacy", "/api/owner/notifications/overview"):
        r = http("GET", path, T["amjad@x.fr"])
        check(f"…opens the other Paramètres tabs: {path} ({r.status_code})", r.status_code == 200)
    me = http("GET", "/api/auth/me", T["amjad@x.fr"]).json()
    check("…and his menu knows it", all((p or {}).get("settings") == "edit" for p in (me.get("page_perms") or {}).values())
          and me.get("page_perms"))

    print("\n2. Another business, a built-in role never changed: its template applies too")
    v = http("GET", "/api/owner/etablissement", T["plain@x.fr"]).json()
    check("an administrateur's template (Paramètres « Modifier ») edits the Établissement", v["can"]["brand"])
    me = http("GET", "/api/auth/me", T["plain@x.fr"]).json()
    check("…and gets its page permissions (the menu)", bool(me.get("page_perms")))

    print("\n3. View only, and nothing at all")
    r = http("GET", "/api/owner/etablissement", T["lect@x.fr"])
    check(f"« Voir » Paramètres: reads ({r.status_code})", r.status_code == 200 and not r.json()["can"]["brand"])
    r = http("PUT", "/api/owner/etablissement", T["lect@x.fr"], json={"business": {"description": "x"}})
    check(f"…cannot save ({r.status_code})", r.status_code == 403 and "non autorisé" in r.text)
    r = http("GET", "/api/owner/etablissement", T["caisse@x.fr"])
    check(f"no Paramètres: « Accès non autorisé » ({r.status_code}, {r.json().get('detail')})",
          r.status_code == 403 and "Accès non autorisé" in r.json().get("detail", ""))

    print("\n4. A change applies on the next request")
    db.tenants.update_one({"id": "t2"}, {"$set": {"role_defs.r_rien.perms.settings": "edit"}})
    r = http("GET", "/api/owner/etablissement", T["caisse@x.fr"])
    check(f"given Paramètres: open at once ({r.status_code})", r.status_code == 200 and r.json()["can"]["brand"])
    db.tenants.update_one({"id": "t1"}, {"$set": {"role_defs.administrateur.perms.settings": "none"}})
    r = http("GET", "/api/owner/etablissement", T["amjad@x.fr"])
    check(f"taken away: refused at once ({r.status_code})", r.status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
