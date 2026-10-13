"""
Rôles et permissions par page (user, 2026-10-13): any role name, an account's
own « Voir » / « Modifier » per page, set separately for each establishment;
the four built-in roles kept, their templates editable; only the owner
defines roles; nobody hands out more than they have.

Run: cd api && /usr/local/bin/python3 tests/test_role_perms.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-role-perms")
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
    from fastapi.routing import APIRoute
    from features import role_perms as RP

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "royal", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True,
                           "branches": [{"id": "pal", "name": "PALISSY"}, {"id": "mon", "name": "MONSTRE"},
                                        {"id": "lib", "name": "LIBERTÉ"}]})
    db.tenants.insert_one({"id": "t2", "slug": "solo", "name": "Solo", "plan": "vip", "subscription_status": "active", "is_active": True})
    db.users.insert_many([
        {"id": "u-o", "email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"id": "u-a", "email": "a@x.fr", "role": "administrateur", "tenant_id": "t1", "active": True, "branch_ids": ["pal", "mon"]},
        {"id": "u-m", "email": "m@x.fr", "role": "manager", "tenant_id": "t1", "active": True, "branch_ids": ["pal"]},
        {"id": "u-r", "email": "r@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
    ])
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Léa", "barcode_id": "FT-ROLE0001", "branch_id": "pal",
                             "visits": 1, "points": 0, "deleted_at": None})
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, ADMIN, MANAGER, OTHER = tok("o@x.fr", "business_owner"), tok("a@x.fr", "administrateur"), \
        tok("m@x.fr", "manager"), tok("r@x.fr", "business_owner", "t2")

    def H(who, store=None):
        return {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}

    def lv(**over):
        return {**{k: "none" for k in RP.PAGE_KEYS}, **over}

    print("0. Every page of the app belongs to a permission row")
    loose = []
    for r in server.app.routes:
        if not isinstance(r, APIRoute) or not r.path.startswith("/api/"):
            continue
        roles = None
        for d in r.dependant.dependencies:
            if getattr(d.call, "__name__", "") == "role_checker":
                for cell in d.call.__closure__ or []:
                    if isinstance(cell.cell_contents, list):
                        roles = cell.cell_contents
        if roles and set(roles) & {"administrateur", "manager", "staff"}:
            loose += [f"{m} {r.path}" for m in r.methods if RP.page_of(r.path) is None and not RP.is_common(r.path, m)]
    check(f"no team endpoint outside a page ({loose[:5]})", not loose)
    check("one row per sidebar page (18 + e-mail change + account deletion)", len(RP.PAGES) == 20)

    print("\n1. The owner creates a role, its name, its pages")
    r = http("POST", "/api/owner/team-access/roles", headers=H(OWNER),
             json={"label": "Responsable caisse", "perms": lv(scan="edit", customers="view", catalogue="view")})
    check(f"created ({r.status_code})", r.status_code == 200 and r.json().get("role", "").startswith("r_"))
    caisse = r.json()["role"]
    t = {x["key"]: x for x in r.json()["templates"]}
    check("listed with the four built-in roles", {"administrateur", "manager", "staff", caisse} <= set(t)
          and t[caisse]["label"] == "Responsable caisse" and t[caisse]["perms"]["scan"] == "edit")
    check("…and as a role card", any(x.get("custom") and x["label"] == "Responsable caisse" for x in r.json()["roles"]))
    check("a name already used is refused", http("POST", "/api/owner/team-access/roles", headers=H(OWNER),
                                                json={"label": "manager", "perms": {}}).status_code == 400)
    check("« Propriétaire » is refused", http("POST", "/api/owner/team-access/roles", headers=H(OWNER),
                                             json={"label": "Propriétaire", "perms": {}}).status_code == 400)
    check("an unknown page is refused", http("POST", "/api/owner/team-access/roles", headers=H(OWNER),
                                            json={"label": "X Y", "perms": {"nope": "edit"}}).status_code == 400)
    check("an administrateur cannot define roles", http("POST", "/api/owner/team-access/roles", headers=H(ADMIN),
                                                       json={"label": "Mon rôle", "perms": {}}).status_code == 403)
    check("Voir / Modifier switches are read too", RP.clean_perms({"scan": {"view": True, "edit": True},
                                                                  "customers": {"view": True, "edit": False}})["customers"] == "view")
    check("« Supprimer le compte » has no « Voir »", RP.clean_perms({"delete": "view"})["delete"] == "none")

    print("\n2. An account in it — its permissions per establishment")
    r = http("POST", "/api/owner/team-access/users", headers=H(OWNER), json={
        "email": "caisse@x.fr", "first_name": "Inès", "role": caisse, "branch_ids": ["pal", "mon"],
        "password": "Caisse!Royal2026",
        "perms": {"pal": lv(scan="edit", customers="edit", catalogue="view"), "mon": lv(scan="edit")}})
    check(f"created ({r.status_code})", r.status_code == 200)
    u = db.users.find_one({"email": "caisse@x.fr"})
    check("system role « membre », its role remembered", u["role"] == "membre" and u["custom_role"] == caisse)
    check("PALISSY and MONSTRE each have their own", u["perms"]["pal"]["customers"] == "edit" and u["perms"]["mon"]["customers"] == "none")
    row = {x["email"]: x for x in r.json()["users"]}["caisse@x.fr"]
    check("the list shows its role name", row["role_label"] == "Responsable caisse")
    CAISSE = tok("caisse@x.fr", "membre")
    me = http("GET", "/api/auth/me", headers=H(CAISSE)).json()
    check("its sidebar knows its pages per establishment",
          (me.get("page_perms") or {}).get("pal", {}).get("customers") == "edit"
          and (me.get("page_perms") or {}).get("mon", {}).get("scan") == "edit")

    print("\n3. The API keeps to it — per page, per establishment")
    check("PALISSY: it may scan", http("POST", "/api/owner/scan", headers=H(CAISSE, "pal"),
                                       json={"barcode_id": "FT-ROLE0001", "branch_id": "pal"}).status_code == 200)
    check("PALISSY: it sees the clients", http("GET", "/api/owner/clients/overview", headers=H(CAISSE, "pal")).status_code == 200)
    r = http("GET", "/api/owner/clients/overview", headers=H(CAISSE, "mon"))
    check(f"MONSTRE: no client list (« Voir » off there) ({r.status_code})", r.status_code == 403
          and "Clients" in str(r.json().get("detail")))
    r = http("POST", "/api/owner/campaigns", headers=H(CAISSE, "pal"), json={})
    check(f"no campaign page: refused, in French ({r.json().get('detail')})", r.status_code == 403
          and "Campagnes" in r.json()["detail"] and "modifier" in r.json()["detail"])
    check("the card: read for the scan it does, never changed",
          http("GET", "/api/owner/card/settings", headers=H(CAISSE, "pal")).status_code == 200
          and "Carte de fidélité" in str(http("PUT", "/api/owner/card/settings", headers=H(CAISSE, "pal"),
                                              json={"card_name": "X"}).json()))
    check("the catalogue: « Voir » lets it read…", http("GET", "/api/owner/catalogue/page", headers=H(CAISSE, "pal")).status_code == 200)
    r = http("POST", "/api/owner/catalogue/products", headers=H(CAISSE, "pal"), json={"name": "Coupe", "price": 20})
    check(f"…not change ({r.json().get('detail')})", r.status_code == 403 and "Catalogue" in str(r.json()))
    check("billing: refused", http("GET", "/api/billing/status", headers=H(CAISSE, "pal")).status_code == 403)
    check("the menu, the plan, its own security: allowed", http("GET", "/api/owner/branches", headers=H(CAISSE, "pal")).status_code == 200
          and http("GET", "/api/owner/plan-access", headers=H(CAISSE, "pal")).status_code == 200)
    check("a store that is not its own gives nothing more",
          RP.level_in(RP.per_store(u), "customers", "lib") == "none")
    check("without a store chosen: the lowest of its stores (never more than everywhere)",
          RP.level_in(RP.per_store(u), "customers", None) == "none")

    print("\n4. The four built-in roles: as before until the owner changes them")
    check("a manager without permissions of its own: the old rules", RP.per_store(db.users.find_one({"email": "m@x.fr"})) is None)
    check("…its clients page still works", http("GET", "/api/owner/clients/overview", headers=H(MANAGER, "pal")).status_code == 200)
    r = http("PUT", "/api/owner/team-access/roles/manager", headers=H(OWNER),
             json={"perms": {**RP.DEFAULT_TEMPLATES["manager"], "customers": "view", "card": "edit"}, "apply": "new"})
    check(f"the owner changes the Manager template for new accounts ({r.status_code})", r.status_code == 200)
    m = db.users.find_one({"email": "m@x.fr"})
    check("…the existing manager keeps what it had (written down)", m["perms"]["pal"]["customers"] == "edit"
          and m["perms"]["pal"]["card"] == "none")
    r = http("POST", "/api/owner/team-access/users", headers=H(OWNER), json={
        "email": "m2@x.fr", "role": "manager", "branch_ids": ["mon"], "password": "Manager!Royal2026"})
    check("a new manager gets the new template", db.users.find_one({"email": "m2@x.fr"})["perms"]["mon"]["card"] == "edit")
    M2 = tok("m2@x.fr", "manager")
    r = http("PUT", "/api/owner/customers/c1/home-store", headers=H(M2, "mon"), json={"branch_id": "mon"})
    check(f"…it only reads clients now: no move ({r.status_code})", r.status_code == 403 and "Clients" in str(r.json()))
    # a one-shop account: the manager covers the whole shop
    db.users.insert_one({"id": "u-s", "email": "sm@x.fr", "role": "manager", "tenant_id": "t2", "active": True,
                         "branch_ids": ["main"]})
    http("PUT", "/api/owner/team-access/roles/manager", headers=H(OTHER),
         json={"perms": {**RP.DEFAULT_TEMPLATES["manager"], "card": "edit"}, "apply": "all"})
    r = http("PUT", "/api/owner/card/settings", headers=H(tok("sm@x.fr", "manager", "t2")), json={"card_name": "Carte Solo"})
    check(f"a manager given the card edits it (an owner-only page before) ({r.status_code})", r.status_code == 200
          and db.card_templates.find_one({"tenant_id": "t2"})["card_name"] == "Carte Solo")
    check("…another account's templates are untouched (ROYAL TRIM's Manager still reads its clients only)",
          RP.templates("t1")["manager"]["perms"]["customers"] == "view" and RP.templates("t2")["manager"]["perms"]["customers"] == "edit")
    r = http("PUT", "/api/owner/team-access/roles/manager", headers=H(OWNER),
             json={"perms": {**RP.DEFAULT_TEMPLATES["manager"], "history": "none"}, "apply": "all"})
    check(f"« Appliquer à tous » rewrites every manager ({r.json().get('applied')})", r.json().get("applied") == 2
          and db.users.find_one({"email": "m@x.fr"})["perms"]["pal"]["history"] == "none")
    r = http("PUT", "/api/owner/team-access/roles/manager", headers=H(OWNER), json={"perms": None, "apply": "new"})
    check("back to the default template", r.status_code == 200
          and {x["key"]: x for x in r.json()["templates"]}["manager"]["customized"] is False)

    print("\n5. Nobody gives more than they have")
    r = http("POST", "/api/owner/team-access/users", headers=H(ADMIN), json={
        "email": "x1@x.fr", "role": caisse, "branch_ids": ["pal"], "password": "Caisse!Royal2026",
        "perms": {"pal": lv(billing="view")}})
    check(f"an administrateur cannot hand out billing ({r.status_code})", r.status_code == 403 and "Abonnement" in str(r.json()))
    r = http("POST", "/api/owner/team-access/users", headers=H(ADMIN), json={
        "email": "x2@x.fr", "role": caisse, "branch_ids": ["lib"], "password": "Caisse!Royal2026"})
    check("…nor a store it does not have", r.status_code == 403)
    r = http("POST", "/api/owner/team-access/users", headers=H(ADMIN), json={
        "email": "x3@x.fr", "role": caisse, "branch_ids": ["pal"], "password": "Caisse!Royal2026"})
    check("…but may create an account in the owner's role, for its stores", r.status_code == 200)
    check("a manager cannot create custom-role accounts", http("POST", "/api/owner/team-access/users", headers=H(MANAGER), json={
        "email": "x4@x.fr", "role": caisse, "branch_ids": ["pal"], "password": "Caisse!Royal2026"}).status_code == 403)
    check("another account's role key is unknown here", http("POST", "/api/owner/team-access/users", headers=H(OTHER), json={
        "email": "x5@x.fr", "role": caisse, "branch_ids": ["main"], "password": "Caisse!Royal2026"}).status_code == 400)

    print("\n6. Editing an account, deleting a role")
    r = http("PUT", "/api/owner/team-access/users/caisse@x.fr", headers=H(OWNER), json={
        "first_name": "Inès", "branch_ids": ["pal", "mon", "lib"]})
    u = db.users.find_one({"email": "caisse@x.fr"})
    check("a new store: the role's template there, the others kept", r.status_code == 200
          and u["perms"]["lib"]["catalogue"] == "view" and u["perms"]["pal"]["customers"] == "edit")
    r = http("PUT", "/api/owner/team-access/users/caisse@x.fr", headers=H(OWNER), json={
        "first_name": "Inès", "perms": {"mon": lv(scan="edit", history="view")}})
    check("one store's switches changed", db.users.find_one({"email": "caisse@x.fr"})["perms"]["mon"]["history"] == "view"
          and db.users.find_one({"email": "caisse@x.fr"})["perms"]["pal"]["customers"] == "edit")
    check("a role still in use cannot be deleted", http("DELETE", f"/api/owner/team-access/roles/{caisse}", headers=H(OWNER)).status_code == 400)
    check("a built-in role cannot be deleted", http("DELETE", "/api/owner/team-access/roles/manager", headers=H(OWNER)).status_code == 404)
    r = http("PUT", "/api/owner/team-access/users/caisse@x.fr", headers=H(OWNER), json={"role": "staff", "branch_ids": ["pal"]})
    u = db.users.find_one({"email": "caisse@x.fr"})
    check("moved to Employé: the custom role is gone", r.status_code == 200 and u["role"] == "staff" and "custom_role" not in u)
    db.users.delete_many({"custom_role": caisse})
    r = http("DELETE", f"/api/owner/team-access/roles/{caisse}", headers=H(OWNER))
    check("unused: deleted", r.status_code == 200 and caisse not in {x["key"] for x in r.json()["templates"]})

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
