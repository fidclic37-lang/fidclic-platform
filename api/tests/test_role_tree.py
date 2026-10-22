"""
The role tree (user, 2026-10-22): « proprietaire sabka kar sakta,
administrateur keval apne niche waale ka… jo roles admin ne banaye, unhone
roles banaye… and so on ». Making roles and changing them is a permission
(« Créer et modifier les rôles »); one manages the roles below one's own and
the accounts in them, never one's own role or one above. Shop-wide
push-wallet scenarios: whoever has « Modifier » Automatisations everywhere.

Run: cd api && /usr/local/bin/python3 tests/test_role_tree.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-role-tree")
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

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True},
                                                           {"id": "pal", "name": "PALISSY"}]})
    tok = lambda e, r: "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": "t1"})  # noqa: E731
    db.users.insert_many([
        {"id": "o", "email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"id": "a", "email": "amjad@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True},
        {"id": "a2", "email": "hamada@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True,
         "branch_ids": ["pal"]},
    ])
    O, A, A2 = tok("o@x.fr", "business_owner"), tok("amjad@x.fr", "administrateur"), tok("hamada@x.fr", "administrateur")
    pages = lambda **over: {**{k: "none" for k in RP.PAGE_KEYS}, **over}  # noqa: E731

    print("1. Making roles is a permission")
    r = http("POST", "/api/owner/team-access/roles", A, json={"label": "Chef", "perms": pages(scan="edit")})
    check(f"an administrateur without it cannot make a role ({r.status_code})", r.status_code == 403)
    # the owner gives the administrateurs « Créer et modifier les rôles » (and the rest)
    admin_perms = {**{k: "edit" for k in RP.PAGE_KEYS}, "billing": "none", "delete": "none", "email_change": "none"}
    r = http("PUT", "/api/owner/team-access/roles/administrateur", O, json={"perms": admin_perms, "apply": "all"})
    check(f"the owner gives it ({r.status_code})", r.status_code == 200)
    me = http("GET", "/api/owner/team-access", A).json()["me"]
    check("…AMJAD may now define roles", me["can_define_roles"] is True)
    owner_role = http("POST", "/api/owner/team-access/roles", O, json={"label": "Caisse du patron", "perms": pages(scan="edit")}).json()["role"]
    r = http("POST", "/api/owner/team-access/roles", A, json={"label": "Chef", "perms": pages(scan="edit", customers="edit", team="edit", roles="edit")})
    check(f"AMJAD makes « Chef » ({r.status_code})", r.status_code == 200)
    chef = r.json()["role"]
    check("…under his own role", db.tenants.find_one({"id": "t1"})["role_defs"][chef]["parent"] == "administrateur")
    r = http("POST", "/api/owner/team-access/roles", A, json={"label": "Trop", "perms": pages(billing="view")})
    check(f"…never with more than he has (billing) ({r.status_code})", r.status_code == 403)

    print("\n2. Who changes which role")
    def can_edit_role(who, key):
        return http("PUT", f"/api/owner/team-access/roles/{key}", who,
                    json={"perms": pages(scan="edit", customers="view", team="edit", roles="edit"), "apply": "all"}).status_code == 200
    check("AMJAD changes « Chef » (below him)", can_edit_role(A, chef))
    check("…another administrateur too (same role above it)", can_edit_role(A2, chef))
    check("…but not his own role", not can_edit_role(A, "administrateur"))
    check("…nor a role the owner made", not can_edit_role(A, owner_role))
    check("the owner changes every one", can_edit_role(O, chef) and can_edit_role(O, owner_role))

    print("\n3. And so on, down the tree")
    r = http("POST", "/api/owner/team-access/users", A, json={"email": "chef@x.fr", "role": chef, "branch_ids": ["lib", "pal"],
                                                              "password": "Chef!Royal2026"})
    check(f"AMJAD gives « Chef » to an account ({r.status_code})", r.status_code == 200)
    C = tok("chef@x.fr", "membre")
    r = http("POST", "/api/owner/team-access/roles", C, json={"label": "Commis", "perms": pages(scan="edit")})
    check(f"the Chef makes « Commis » ({r.status_code})", r.status_code == 200)
    commis = r.json()["role"]
    check("…under « Chef »", db.tenants.find_one({"id": "t1"})["role_defs"][commis]["parent"] == chef)
    check("the Chef changes « Commis »", can_edit_role(C, commis))
    check("…not « Chef », his own", not can_edit_role(C, chef))
    check("…not « Administrateur », above him", not can_edit_role(C, "administrateur"))
    check("AMJAD changes « Commis » too (two levels below)", can_edit_role(A, commis))
    check("…and so does the owner", can_edit_role(O, commis))
    team = http("GET", "/api/owner/team-access", A).json()
    chef_row = next(u for u in team["users"] if u["email"] == "chef@x.fr")
    check("AMJAD manages the Chef's account", chef_row["manageable"] is True)
    team_c = http("GET", "/api/owner/team-access", C).json()
    check(f"the Chef may give only « Commis » ({team_c['me']['assignable_roles']})", team_c["me"]["assignable_roles"] == [commis])
    r = http("POST", "/api/owner/team-access/users", C, json={"email": "x@x.fr", "role": owner_role, "branch_ids": ["lib"],
                                                              "password": "Commis!Royal2026"})
    check(f"…not a role above or beside him ({r.status_code})", r.status_code == 403)

    print("\n4. Shop-wide push-wallet scenarios")
    body = {"name": "Relance", "trigger": "inactivity", "title": "Revenez", "body": "On vous attend", "config": {"days": 30}}
    r = http("POST", "/api/owner/push-wallet/scenarios", A, json=body)
    check(f"AMJAD (Automatisations « Modifier » in every store) creates one ({r.status_code})", r.status_code == 200)
    r = http("POST", "/api/owner/push-wallet/scenarios", A2, json=body)
    check(f"HAMADA (only PALISSY) cannot change the whole shop ({r.status_code})", r.status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
