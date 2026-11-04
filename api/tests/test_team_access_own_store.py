"""
Équipe & accès: only the stores the viewer should reach
(docs/tasks/roles-access-own-store.md). The invite form offers the store open
in the menu; a non-owner sees and changes its own store only, and the API
refuses the rest. Only an owner login sees every store.

Run: cd api && python3 tests/test_team_access_own_store.py
"""
import asyncio
import contextlib
import copy
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-team-own-store")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
A, B, C = "store-a", "store-b", "store-c"
TEAM = "/api/owner/team-access"


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

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else [], **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def account(uid, role, tid="t1", stores=None, **more):
        doc = {"id": uid, "email": f"{uid}@x.test", "first_name": uid, "role": role, "tenant_id": tid,
               "active": True, "hashed_password": "x", **more}
        if stores is not None:
            doc["branch_ids"] = stores
        return doc

    def seed():
        db.users.delete_many({})
        db.tenants.delete_many({})
        db.tenants.insert_many([
            {"id": "t1", "slug": "t1", "name": "Shop", "plan": "vip", "subscription_status": "active", "is_active": True,
             "branches": [{"id": A, "name": "Alpha", "is_main": True}, {"id": B, "name": "Beta"}, {"id": C, "name": "Gamma"}],
             "role_defs": {"chef": {"label": "Chef", "perms": {"team": "edit", "roles": "edit"}, "parent": "administrateur"},
                           "sous": {"label": "Sous", "perms": {"scan": "edit"}, "parent": "chef"},
                           "caisse": {"label": "Caisse", "perms": {"scan": "view"}, "parent": "administrateur"}}},
            {"id": "t2", "slug": "t2", "name": "Other", "plan": "vip", "subscription_status": "active", "is_active": True,
             "branches": [{"id": "other-x", "name": "Xeno"}, {"id": "other-y", "name": "Yuma"}]},
            {"id": "t3", "slug": "t3", "name": "Solo", "plan": "vip", "subscription_status": "active", "is_active": True},
        ])
        db.users.insert_many([
            account("owner", "business_owner"),
            account("adm2", "administrateur", stores=[A, B]),
            account("adm1", "administrateur", stores=[A]),
            account("admall", "administrateur", stores=[A, B, C]),
            account("admnone", "administrateur", stores=[]),
            account("mgr", "manager", stores=[A]),
            account("mgrold", "manager"),
            account("emp", "staff", stores=[A], perms={A: {"team": "edit"}}),
            account("chef", "membre", stores=[A, B], custom_role="chef",
                    perms={A: {"team": "edit", "roles": "edit"}, B: {"team": "edit", "roles": "edit"}}),
            account("staffa", "staff", stores=[A]),
            account("staffb", "staff", stores=[B]),
            account("staffc", "staff", stores=[C]),
            account("sousab", "membre", stores=[A, B], custom_role="sous",
                    perms={A: {"scan": "edit"}, B: {"scan": "view"}}),
            account("sousb", "membre", stores=[B], custom_role="sous"),
            account("owner2", "business_owner", tid="t2"),
            account("solo", "business_owner", tid="t3"),
            account("solomgr", "manager", tid="t3", stores=["main"]),
        ])

    def tok(uid, role, tid="t1"):
        return "Bearer " + auth.create_access_token({"sub": f"{uid}@x.test", "role": role, "tenant_id": tid})

    OWNER, ADM2 = tok("owner", "business_owner"), tok("adm2", "administrateur")
    ADM1, ADMALL = tok("adm1", "administrateur"), tok("admall", "administrateur")
    ADMNONE, MGR = tok("admnone", "administrateur"), tok("mgr", "manager")
    MGROLD, EMP = tok("mgrold", "manager"), tok("emp", "staff")
    CHEF, OWNER2 = tok("chef", "membre"), tok("owner2", "business_owner", "t2")
    SOLO, SOLOMGR = tok("solo", "business_owner", "t3"), tok("solomgr", "manager", "t3")
    NON_OWNERS = {"administrateur 2 stores": ADM2, "administrateur 1 store": ADM1, "manager": MGR,
                  "staff with team rights": EMP, "custom role": CHEF}

    def call(who, method, path, store=None, **kw):
        """`store`: one value for the header, or a list of (name, value) lines."""
        headers = [("Authorization", who)]
        if isinstance(store, list):
            headers += store
        elif store is not None:
            headers.append(("X-FidClic-Store", store))
        return http(method, path, headers=headers, **kw)

    def view(who, store=None, **kw):
        r = call(who, "GET", TEAM, store, **kw)
        return r.json() if r.status_code == 200 else {"_status": r.status_code, "_body": r.text}

    ids = lambda rows: sorted(s["id"] for s in rows)                         # noqa: E731
    people = lambda rows: sorted(u["id"] for u in rows)                      # noqa: E731
    row = lambda d, uid: next(u for u in d["users"] if u["id"] == uid)       # noqa: E731
    user = lambda uid: db.users.find_one({"id": uid}, {"_id": 0})            # noqa: E731

    def snapshot():
        return (sorted((copy.deepcopy(u) for u in db.users.find({}, {"_id": 0})), key=lambda u: u["id"]),
                copy.deepcopy(db.tenants.find_one({"id": "t1"}, {"_id": 0})))

    def invite(store=None, branch_ids=None, role="staff", who=ADM2, email="new@x.test", **kw):
        return call(who, "POST", f"{TEAM}/users", store, json={"email": email, "first_name": "New", "role": role,
                                                               "branch_ids": branch_ids or []}, **kw)

    seed()

    print("\n1. Invite form: the open store only")
    d = view(OWNER, A)
    check(f"AC1 owner, A open: only A offered ({d.get('invite_stores')})", ids(d.get("invite_stores", [])) == [A])
    d = view(OWNER, "all")
    check("AC2 owner, « all »: every store offered", ids(d.get("invite_stores", [])) == [A, B, C])
    d = view(OWNER)
    check("AC2 owner, nothing named: every store offered", ids(d.get("invite_stores", [])) == [A, B, C])
    d = view(ADM2, A)
    check("AC3 two-store administrateur, A open: only A", ids(d.get("invite_stores", [])) == [A])
    d = view(ADM2, "all")
    check("AC3 two-store administrateur, « all »: its own two, never C", ids(d.get("invite_stores", [])) == [A, B])
    d = view(ADM2)
    check("AC3 two-store administrateur, nothing named: its own two", ids(d.get("invite_stores", [])) == [A, B])
    d = view(MGR, A)
    check("AC4 manager of A: only A", ids(d.get("invite_stores", [])) == [A])
    d = view(MGR)
    check("AC4 manager of A, nothing named: only A", ids(d.get("invite_stores", [])) == [A])

    for label, target in (("B, its other store", [B]), ("C, not its store", [C]), ("A and B", [A, B])):
        role = "sous" if len(target) > 1 else "staff"
        r = invite(A, target, role=role)
        check(f"AC5 A open, invite to {label}: 403 ({r.status_code}), no account",
              r.status_code == 403 and not db.users.find_one({"email": "new@x.test"}))
    r = invite(A, [A])
    new = db.users.find_one({"email": "new@x.test"})
    check(f"AC6 A open, invite to A: created with A only ({r.status_code})", r.status_code == 200 and new and new["branch_ids"] == [A])
    check("AC6 the reply names A's store only", r.status_code == 200 and ids(r.json()["invite_stores"]) == [A])
    db.users.delete_one({"email": "new@x.test"})
    r = invite("all", [A, B], role="sous")
    check(f"AC3 « all »: invite to both own stores works ({r.status_code})", r.status_code == 200)
    db.users.delete_one({"email": "new@x.test"})
    r = invite("all", [C])
    check(f"AC5 « all »: invite to a store not its own: 403 ({r.status_code})", r.status_code == 403)
    d = view(ADMNONE)
    check("AC7 no store left: nothing offered", d.get("stores") == [] and d.get("invite_stores") == [])
    r = invite(None, [A], who=ADMNONE)
    check(f"AC7 no store left: invite refused ({r.status_code})", r.status_code == 403)
    r = invite(None, [], who=ADMNONE)
    check(f"AC7 no store left: invite with no store refused ({r.status_code})", r.status_code in (400, 403))

    print("\n2. Accès par établissement: own store only")
    d = view(ADM2, A)
    check("AC8 stores holds A only", ids(d.get("stores", [])) == [A])
    check(f"AC8 users: people with A ({people(d.get('users', []))})",
          all(A in user(u["id"]).get("branch_ids", [A]) for u in d.get("users", []))
          and set(people(d.get("users", []))) >= {"adm2", "staffa", "sousab"})
    check("AC8 all_users holds the same people, never B's", people(d.get("all_users", [])) == people(d.get("users", []))
          and "staffb" not in people(d.get("all_users", [])) and "sousb" not in people(d.get("all_users", [])))
    check("AC8 pending holds A's people only", "staffb" not in people(d.get("pending", [])) and "sousb" not in people(d.get("pending", [])))
    s = row(d, "sousab")
    check(f"AC9 a person on A and B shows A only ({s['branch_ids']})", s["branch_ids"] == [A])
    check(f"AC9 …in the label ({s['stores_label']})", s["stores_label"] == "Alpha")
    check("AC9 …in the permissions", set((s.get("perms") or {}).keys()) == {A})
    me = row(d, "adm2")
    check(f"AC9 the viewer's own row shows A only ({me['stores_label']})", me["branch_ids"] == [A] and me["stores_label"] == "Alpha")
    r = call(ADM2, "GET", TEAM, A)
    check("AC9 nothing in the reply names the other stores", not any(x in r.text for x in (B, C, "Beta", "Gamma")))
    r = call(MGR, "GET", TEAM)
    check("AC9 a manager's reply, nothing named: no other store", not any(x in r.text for x in (B, C, "Beta", "Gamma")))
    d = view(ADM2)
    check("AC10 nothing named: its own stores", ids(d.get("stores", [])) == [A, B])
    check("AC10 nothing named: never someone of C", "staffc" not in people(d.get("all_users", [])))
    r = call(ADM2, "GET", TEAM)
    check("AC10 nothing in the reply names C", C not in r.text and "Gamma" not in r.text)
    d = view(OWNER, A)
    check("AC11 owner, A open: every store still listed", ids(d.get("stores", [])) == [A, B, C])
    check("AC11 owner, A open: all_users still has everyone", {"staffb", "staffc", "sousb"} <= set(people(d.get("all_users", []))))
    check("AC11 owner, A open: the open store is named", d.get("store_id") == A)
    check("AC11 owner, A open: a person on A and B still shows both", row(d, "sousab")["branch_ids"] == [A, B])

    print("\n3. The API refuses another store")
    before = snapshot()
    actions = [("POST", f"{TEAM}/users", {"email": "x@x.test", "role": "staff", "branch_ids": [A]}),
               ("PUT", f"{TEAM}/users/staffa", {"first_name": "Z"}), ("POST", f"{TEAM}/users/staffa/status", {"active": False}),
               ("POST", f"{TEAM}/users/staffa/password", None), ("DELETE", f"{TEAM}/users/staffa", None),
               ("PUT", f"{TEAM}/stores/{A}/users/staffa", {"enabled": True}),
               ("PUT", f"{TEAM}/roles/sous", {"perms": {"scan": "view"}, "apply": "all"}),
               ("POST", f"{TEAM}/roles", {"label": "Nouveau", "perms": {}}), ("DELETE", f"{TEAM}/roles/sous", None)]
    for label, who in NON_OWNERS.items():
        foreign = C
        r = call(who, "GET", TEAM, foreign)
        check(f"AC13 {label}, read, header names C: 403 ({r.status_code})", r.status_code == 403)
        r = call(who, "GET", TEAM, params={"store": foreign})
        check(f"AC13 {label}, read, ?store=C: 403 ({r.status_code})", r.status_code == 403)
        for method, path, body in actions:
            kw = {"json": body} if body is not None else {}
            r = call(who, method, path, foreign, **kw)
            check(f"AC13 {label}, {method} {path.replace(TEAM, '')}, header names C: 403 ({r.status_code})", r.status_code == 403)
            r = call(who, method, path, params={"store": foreign}, **kw)
            check(f"AC13 {label}, {method} {path.replace(TEAM, '')}, ?store=C: 403 ({r.status_code})", r.status_code == 403)
    check("AC13 nothing changed", snapshot() == before)

    for name, kw in (("header A, ?store=C", {"store": A, "params": {"store": C}}),
                     ("header C, ?store=A", {"store": C, "params": {"store": A}}),
                     ("header A, ?store=B", {"store": A, "params": {"store": B}}),
                     ("header B, ?store=A", {"store": B, "params": {"store": A}}),
                     ("two headers A and C", {"store": [("X-FidClic-Store", A), ("X-FidClic-Store", C)]}),
                     ("two headers C and A", {"store": [("X-FidClic-Store", C), ("X-FidClic-Store", A)]}),
                     ("repeated ?store=", {"params": [("store", A), ("store", C)]}),
                     ("repeated ?store=, reversed", {"params": [("store", C), ("store", A)]})):
        r = call(ADM2, "GET", TEAM, **kw)
        check(f"AC14 read, {name}: refused ({r.status_code})", r.status_code in (400, 403))
        r = call(ADM2, "POST", f"{TEAM}/users", json={"email": "x@x.test", "role": "staff", "branch_ids": [A]}, **kw)
        check(f"AC14 invite, {name}: refused ({r.status_code})", r.status_code in (400, 403))
        r = call(ADM2, "PUT", f"{TEAM}/stores/{A}/users/sousab", json={"enabled": False}, **kw)
        check(f"AC14 store access, {name}: refused ({r.status_code})", r.status_code in (400, 403))
    check("AC14 nothing changed", snapshot() == before)
    r = call(OWNER, "GET", TEAM, A, params={"store": B})
    check(f"AC14 an owner naming two of its stores is refused too ({r.status_code})", r.status_code == 400)
    d = view(OWNER, A, params={"store": "other-x"})
    check("AC21 an owner: its store and another shop's id is simply its store", d.get("store_id") == A)

    d = view(ADM2, "all", params={"store": A})
    check("AC15 header « all », ?store=A: behaves as A", ids(d.get("stores", [])) == [A] and d.get("store_id") == A)
    d = view(ADM2, A, params={"store": "all"})
    check("AC15 header A, ?store=all: behaves as A", ids(d.get("stores", [])) == [A] and d.get("store_id") == A)
    r = call(ADM2, "POST", f"{TEAM}/users", A, params={"store": "all"}, json={"email": "x@x.test", "role": "staff", "branch_ids": [B]})
    check(f"AC15 header A, ?store=all, invite to B: 403 ({r.status_code})", r.status_code == 403)
    r = call(ADM2, "GET", TEAM, f"  {C}  ")
    check(f"AC15 spaces around a foreign store change nothing: 403 ({r.status_code})", r.status_code == 403)

    for on in (True, False):
        r = call(ADM2, "PUT", f"{TEAM}/stores/{B}/users/sousab", A, json={"enabled": on})
        check(f"AC16 A open, {'give' if on else 'take'} B: 403 ({r.status_code})", r.status_code == 403)
        r = call(ADM2, "PUT", f"{TEAM}/stores/{C}/users/sousab", json={"enabled": on})
        check(f"AC16 nothing named, {'give' if on else 'take'} C: 403 ({r.status_code})", r.status_code == 403)
        r = call(ADM2, "PUT", f"{TEAM}/stores/{C}/users/sousab", "all", json={"enabled": on})
        check(f"AC16 « all », {'give' if on else 'take'} C: 403 ({r.status_code})", r.status_code == 403)
    check("AC16 nothing changed", snapshot() == before)

    for name, method, path, kw in (
            ("edit", "PUT", f"{TEAM}/users/staffb", {"json": {"first_name": "Z"}}),
            ("status", "POST", f"{TEAM}/users/staffb/status", {"json": {"active": False}}),
            ("password", "POST", f"{TEAM}/users/staffb/password", {}),
            ("delete", "DELETE", f"{TEAM}/users/staffb", {}),
            ("give A", "PUT", f"{TEAM}/stores/{A}/users/sousb", {"json": {"enabled": True}})):
        r = call(ADM2, method, path, A, **kw)
        check(f"AC17 A open, {name} on someone only in B: 403 ({r.status_code})", r.status_code == 403)
    check("AC17 nothing changed", snapshot() == before)

    print("\n4. Someone on A and B, from A")
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "Z", "role": "sous", "branch_ids": [A, C]})
    check(f"AC18 naming C: 403 ({r.status_code})", r.status_code == 403)
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "Z", "role": "sous", "branch_ids": [A, B]})
    check(f"AC18 naming B: 403 ({r.status_code})", r.status_code == 403)
    check("AC18 nothing changed", snapshot() == before)
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={
        "first_name": "Z", "role": "sous", "branch_ids": [A],
        "perms": {A: {"scan": "view"}, B: {"scan": "edit"}, C: {"scan": "edit"}}})
    u = user("sousab")
    check(f"AC18 sending only A keeps B ({r.status_code}, {u['branch_ids']})", r.status_code == 200 and sorted(u["branch_ids"]) == [A, B])
    check("AC18 A's permissions change", u["perms"][A].get("scan") == "view")
    check("AC18 B's permissions stay, whatever the body says", u["perms"][B].get("scan") == "view")
    check("AC18 C gets nothing", C not in u["perms"])
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "Z", "role": "sous"})
    check("AC18 no store list sent: A and B stay", r.status_code == 200 and sorted(user("sousab")["branch_ids"]) == [A, B])
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "Z", "role": "sous", "branch_ids": []})
    u = user("sousab")
    check(f"AC18 taking A away keeps B ({r.status_code}, {u['branch_ids']})", r.status_code == 200 and u["branch_ids"] == [B])
    check("AC18 …and A's people no longer show them", "sousab" not in people(r.json().get("users", [])))

    seed()
    before = snapshot()
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "sousab", "role": "caisse", "branch_ids": [A]})
    check(f"AC19 A open, role change on someone also in B: 403 ({r.status_code})", r.status_code == 403)
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "sousab", "role": "staff", "branch_ids": [A]})
    check(f"AC19 A open, to a single-store role: 403 ({r.status_code})", r.status_code == 403)
    check("AC19 nothing changed", snapshot() == before)
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", json={"first_name": "sousab", "role": "caisse", "branch_ids": [A, B]})
    check(f"AC19 nothing named: the same change works ({r.status_code})", r.status_code == 200 and user("sousab")["custom_role"] == "caisse")
    seed()
    r = call(ADM2, "PUT", f"{TEAM}/users/staffa", A, json={"first_name": "Z", "role": "manager", "branch_ids": [A]})
    check(f"A open, role change on someone only in A works ({r.status_code})", r.status_code == 200 and user("staffa")["role"] == "manager")
    r = call(ADM2, "POST", f"{TEAM}/users/sousab/status", A, json={"active": False})
    check(f"account-level action on someone in A and B stays allowed ({r.status_code})", r.status_code == 200 and user("sousab")["active"] is False)
    r = call(ADM2, "PUT", f"{TEAM}/stores/{A}/users/sousab", A, json={"enabled": False})
    check(f"the open store can be taken from someone in A and B ({r.status_code})", r.status_code == 200 and user("sousab")["branch_ids"] == [B])

    print("\n4b. Accounts before stores, odd store values, rights elsewhere")
    seed()
    r = call(ADMALL, "PUT", f"{TEAM}/users/mgrold", A, json={"first_name": "Ren", "role": "manager", "branch_ids": [A]})
    check(f"a manager from before stores can still be saved from an open store ({r.status_code})",
          r.status_code == 200 and user("mgrold")["first_name"] == "Ren")
    r = call(ADMALL, "PUT", f"{TEAM}/users/mgrold", A, json={"first_name": "Ren", "role": "staff", "branch_ids": [A]})
    check(f"…still on every store, as it was ({r.status_code})", "branch_ids" not in user("mgrold"))
    r = call(ADMALL, "PUT", f"{TEAM}/users/mgrold", A, json={"first_name": "Ren", "role": "staff", "branch_ids": [A]})
    check(f"AC19 …its role does not change from one open store ({r.status_code})", r.status_code == 403 and user("mgrold")["role"] == "manager")
    r = call(ADMALL, "PUT", f"{TEAM}/users/mgrold", A, json={"first_name": "Ren", "role": "manager", "branch_ids": []})
    check(f"…taking A away would leave a manager on several: refused ({r.status_code})", r.status_code == 400 and "branch_ids" not in user("mgrold"))
    seed()
    db.users.insert_one(account("mgrtwo", "manager", stores=[A, B]))
    r = call(ADM2, "PUT", f"{TEAM}/users/mgrtwo", A, json={"first_name": "Ren", "role": "manager", "branch_ids": [A]})
    check(f"a manager on two stores can be renamed, both stay ({r.status_code})",
          r.status_code == 200 and user("mgrtwo")["first_name"] == "Ren" and user("mgrtwo")["branch_ids"] == [A, B])
    seed()
    db.users.insert_one(account("mgrtwo", "manager", stores=[A, B]))
    before = snapshot()
    r = call(ADM2, "PUT", f"{TEAM}/stores/{A}/users/mgrtwo", A, json={"enabled": True})
    check(f"AC18 « giving » A does not take B from a manager on both ({r.status_code})", r.status_code == 403)
    check("AC18 nothing changed", snapshot() == before)
    r = call(ADMALL, "PUT", f"{TEAM}/stores/{A}/users/mgrold", A, json={"enabled": True})
    check(f"AC18 nor pin a manager from before stores to A ({r.status_code})", r.status_code == 403 and "branch_ids" not in user("mgrold"))
    for value in ("null", "undefined"):
        d = view(MGR, value)
        check(f"a menu value « {value} » names no store", ids(d.get("stores", [])) == [A])
    seed()
    db.users.update_one({"id": "adm2"}, {"$set": {"perms": {A: {"team": "edit", "scan": "edit"}, B: {"team": "edit", "scan": "view"}}}})
    db.users.update_one({"id": "sousab"}, {"$set": {"perms": {A: {"scan": "edit"}, B: {"scan": "edit"}}}})
    r = call(ADM2, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "Ren", "role": "sous", "branch_ids": [A]})
    u = user("sousab")
    check(f"AC18 a right the viewer lacks in B does not block a save for A ({r.status_code})", r.status_code == 200 and u["first_name"] == "Ren")
    check("AC18 …and B's rights stay", u["perms"][B]["scan"] == "edit")
    r = call(ADM2, "PUT", f"{TEAM}/stores/{A}/users/sousab", A, json={"enabled": False})
    check(f"AC18 …nor taking A away ({r.status_code})", r.status_code == 200 and user("sousab")["branch_ids"] == [B])

    print("\n4c. A role's template does not reach another store's accounts")
    seed()
    db.users.update_one({"id": "adm1"}, {"$set": {"perms": {A: {"roles": "edit", "team": "edit", "scan": "edit"}}}})
    db.users.insert_many([account("sousc", "membre", stores=[C], custom_role="sous", perms={C: {"scan": "edit"}}),
                          account("sousc2", "membre", stores=[C], custom_role="sous"),
                          account("sousa", "membre", stores=[A], custom_role="sous")])
    db.tenants.update_one({"id": "t1"}, {"$set": {"role_defs.sous.parent": "administrateur"}})
    r = call(ADM1, "PUT", f"{TEAM}/roles/sous", A, json={"perms": {"scan": "view"}, "apply": "all"})
    check(f"a one-store administrateur saves the role ({r.status_code})", r.status_code == 200)
    check(f"only accounts it reaches count ({r.json().get('applied')})", r.json().get("applied") == 2)
    check("the account in A follows", user("sousa")["perms"][A]["scan"] == "view")
    check("an account only in C keeps its rights", user("sousc")["perms"][C]["scan"] == "edit")
    check("…also one that followed the template until now", user("sousc2")["perms"][C]["scan"] == "edit")
    u = user("sousab")
    check("someone in A and B follows in A only", u["perms"][A]["scan"] == "view" and u["perms"][B]["scan"] == "view" and sorted(u["branch_ids"]) == [A, B])
    db.users.update_one({"id": "sousab"}, {"$set": {"perms": {A: {"scan": "edit"}, B: {"scan": "edit"}}}})
    r = call(ADM1, "PUT", f"{TEAM}/roles/sous", A, json={"perms": {"scan": "none"}, "apply": "all"})
    u = user("sousab")
    check("someone in A and B keeps B's rights", u["perms"][A]["scan"] == "none" and u["perms"][B]["scan"] == "edit")
    r = call(ADM1, "PUT", f"{TEAM}/roles/staff", A, json={"perms": {"scan": "none"}, "apply": "all"})
    check(f"a built-in role too ({r.status_code})", r.status_code == 200 and user("staffa")["perms"][A]["scan"] == "none")
    check("…a staff member only in C keeps scanning", user("staffc")["perms"][C]["scan"] == "edit")
    check("…also in B", user("staffb")["perms"][B]["scan"] == "edit")
    seed()
    db.users.update_one({"id": "owner"}, {"$set": {"first_name": "owner"}})
    db.users.insert_one(account("sousc", "membre", stores=[C], custom_role="sous", perms={C: {"scan": "edit"}}))
    r = call(OWNER, "PUT", f"{TEAM}/roles/sous", A, json={"perms": {"scan": "view"}, "apply": "all"})
    check(f"an owner's « all » still reaches every account ({r.status_code})", r.status_code == 200 and user("sousc")["perms"][C]["scan"] == "view")
    for apply in ("all", "new"):
        seed()
        db.users.update_one({"id": "adm1"}, {"$set": {"perms": {A: {"roles": "edit", "team": "edit", "scan": "edit"}}}})
        db.tenants.update_one({"id": "t1"}, {"$set": {"role_defs.sous.parent": "administrateur"}})
        db.users.update_one({"id": "sousab"}, {"$set": {"perms": {A: {"scan": "edit"}}}})      # rights written before B was given
        r = call(ADM1, "PUT", f"{TEAM}/roles/sous", A, json={"perms": {"scan": "none"}, "apply": apply})
        check(f"« {apply} »: rights in B that came from the template stay ({r.status_code})",
              r.status_code == 200 and user("sousab")["perms"].get(B, {}).get("scan") == "edit")

    print("\n5. The older team endpoints: an owner only")
    seed()
    before = snapshot()
    for label, who in (("administrateur of every store", ADMALL), ("manager from before stores", MGROLD),
                       ("administrateur 2 stores", ADM2), ("manager of a one-store shop", SOLOMGR)):
        r = call(who, "GET", "/api/owner/team", A)
        check(f"AC20 {label}: list refused ({r.status_code})", r.status_code == 403)
        r = call(who, "POST", "/api/owner/team", A, json={"email": "x@x.test", "password": "Aa1!aaaaaaaa", "role": "staff"})
        check(f"AC20 {label}: create refused ({r.status_code})", r.status_code == 403)
        r = call(who, "DELETE", "/api/owner/team/staffb@x.test", A)
        check(f"AC20 {label}: delete refused ({r.status_code})", r.status_code == 403)
        r = call(who, "POST", "/api/owner/team/staffb@x.test/reset-password", A, json={})
        check(f"AC20 {label}: password refused ({r.status_code})", r.status_code == 403)
    check("AC20 nothing changed", snapshot() == before)
    r = call(OWNER, "GET", "/api/owner/team")
    check(f"AC20 an owner still reads the list ({r.status_code})", r.status_code == 200 and any(m["email"] == "staffb@x.test" for m in r.json()["members"]))

    print("\n6. Another shop, one-store shops, owners")
    r = call(ADM2, "GET", TEAM, "other-x")
    check(f"AC21 non-owner naming another shop's store: 403 ({r.status_code})", r.status_code == 403)
    r = invite("other-x", ["other-x"])
    check(f"AC21 …invite there: refused ({r.status_code})", r.status_code == 403)
    d = view(OWNER2, A)
    check("AC21 the other shop's owner: a foreign id is ignored", ids(d.get("stores", [])) == ["other-x", "other-y"] and d.get("store_id") is None)
    check("AC21 …and every store of its own offered", ids(d.get("invite_stores", [])) == ["other-x", "other-y"])
    r = call(OWNER2, "POST", f"{TEAM}/users", A, json={"email": "x2@x.test", "role": "staff", "branch_ids": [A]})
    check(f"AC21 the other shop's owner cannot give a store of this shop ({r.status_code})", r.status_code == 400)

    d = view(SOLO, "main")
    check("AC24 one-store owner, main", ids(d.get("stores", [])) == ["main"] and ids(d.get("invite_stores", [])) == ["main"])
    d = view(SOLO, "leftover-id")
    check("AC24 one-store owner, a leftover id: ignored", ids(d.get("stores", [])) == ["main"] and d.get("store_id") is None)
    d = view(SOLOMGR)
    check("AC24 one-store manager, nothing named", ids(d.get("stores", [])) == ["main"] and ids(d.get("invite_stores", [])) == ["main"])
    d = view(SOLOMGR, "main")
    check("AC24 one-store manager, main", ids(d.get("invite_stores", [])) == ["main"])
    r = call(SOLOMGR, "POST", f"{TEAM}/users", "main", json={"email": "x3@x.test", "role": "staff"})
    check(f"AC24 one-store manager invites with no store chosen ({r.status_code})", r.status_code == 200 and user(db.users.find_one({"email": "x3@x.test"})["id"])["branch_ids"] == ["main"])

    print("\n7. An owner still reaches everything (AC23)")
    seed()
    r = call(OWNER, "POST", f"{TEAM}/users", A, json={"email": "o1@x.test", "role": "administrateur", "branch_ids": [B, C]})
    check(f"owner, A open: the API still creates elsewhere ({r.status_code})", r.status_code == 200 and db.users.find_one({"email": "o1@x.test"})["branch_ids"] == [B, C])
    r = call(OWNER, "PUT", f"{TEAM}/stores/{C}/users/sousab", A, json={"enabled": True})
    check(f"owner, A open: gives C ({r.status_code})", r.status_code == 200 and C in user("sousab")["branch_ids"])
    r = call(OWNER, "PUT", f"{TEAM}/users/sousab", A, json={"first_name": "sousab", "role": "sous", "branch_ids": [B]})
    check(f"owner, A open: moves someone entirely ({r.status_code})", r.status_code == 200 and user("sousab")["branch_ids"] == [B])
    r = call(OWNER, "DELETE", f"{TEAM}/users/staffc", A)
    check(f"owner, A open: deletes someone of C ({r.status_code})", r.status_code == 200 and not user("staffc"))
    d = view(ADMALL, A)
    check("an administrateur of every store is limited too, with A open", ids(d.get("stores", [])) == [A] and ids(d.get("invite_stores", [])) == [A])
    d = view(ADMALL, "all")
    check("…and sees all three with nothing named", ids(d.get("stores", [])) == [A, B, C])

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
