"""
Équipe & accès — the franchise roles, who creates whom, who sees what.

Run:
    cd api && python3 tests/test_team_access.py
"""
import asyncio
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from fastapi import HTTPException
    from models import TokenData
    from features import team_access as T

    db = server.db
    T.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def as_(email, role, tid="t1"):
        return TokenData(email=email, role=role, tenant_id=tid)

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return e.status_code, e.detail
        return None

    def guard(token, roles, partial_ok=False):
        """Run auth.require_role's checker the way FastAPI would."""
        checker = auth.require_role(roles, partial_ok=partial_ok)
        try:
            asyncio.get_event_loop().run_until_complete(checker(token_data=token))
            return 200
        except HTTPException as e:
            return e.status_code

    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "slug": "corner", "plan": "vip", "branches": [
        {"id": "b-tours", "name": "Le Corner Café", "city": "Tours"},
        {"id": "b-blois", "name": "Corner Blois", "city": "Blois"},
        {"id": "b-orleans", "name": "Corner Orléans", "city": "Orléans"},
    ]})
    db.tenants.insert_one({"id": "t2", "name": "Solo", "slug": "solo"})
    db.users.insert_many([
        {"email": "meriem@corner.fr", "role": "business_owner", "tenant_id": "t1", "first_name": "Meriem", "last_name": "B.",
         "hashed_password": "x"},
        {"email": "old.manager@corner.fr", "role": "manager", "tenant_id": "t1", "hashed_password": "x"},  # before establishments
        {"email": "solo@solo.fr", "role": "business_owner", "tenant_id": "t2", "hashed_password": "x"},
    ])
    OWNER = as_("meriem@corner.fr", "business_owner")

    print("\nLes rôles et les établissements")
    d = T.get_team(token=OWNER)
    check("four roles, in order", [r["key"] for r in d["roles"]] == ["business_owner", "administrateur", "manager", "staff"])
    check("the owner sees every establishment", [s["id"] for s in d["stores"]] == ["b-tours", "b-blois", "b-orleans"])
    check("a shop without branches has one establishment, named after it",
          T.stores("t2") == [{"id": "main", "name": "Solo", "city": ""}])
    check("the owner may create every role below it", d["me"]["can_create"] == ["administrateur", "manager", "staff"])

    print("\nPropriétaire → Administrateur")
    out = T.create_user(T.UserIn(email="Ali@Corner.fr", first_name="Ali", last_name="T.", role="administrateur",
                                 branch_ids=["b-tours", "b-blois"]), token=OWNER)
    check("the account is created with a password shown once",
          out["credentials"]["email"] == "ali@corner.fr" and len(out["credentials"]["password"]) >= 8)
    ali = db.users.find_one({"email": "ali@corner.fr"})
    check("with its establishments and who created it", ali["branch_ids"] == ["b-tours", "b-blois"] and ali["created_by"] == "meriem@corner.fr")
    check("the password is stored hashed, never in clear", ali["hashed_password"] != out["credentials"]["password"])
    check("it covers some establishments: scope partial", T.scope_of(ali) == "partial")
    check("an administrateur needs at least one establishment",
          refused(lambda: T.create_user(T.UserIn(email="x@c.fr", role="administrateur", branch_ids=[]), token=OWNER)))
    check("an unknown establishment is refused",
          refused(lambda: T.create_user(T.UserIn(email="x@c.fr", role="administrateur", branch_ids=["nope"]), token=OWNER)))
    check("an email already used is refused",
          refused(lambda: T.create_user(T.UserIn(email="ali@corner.fr", role="staff", branch_ids=["b-tours"]), token=OWNER)))
    check("a bad email is refused",
          refused(lambda: T.create_user(T.UserIn(email="ali", role="staff", branch_ids=["b-tours"]), token=OWNER)))

    ALI = as_("ali@corner.fr", "administrateur")
    print("\nAdministrateur → Managers de ses établissements")
    d = T.get_team(token=ALI)
    check("it sees only its establishments", [s["id"] for s in d["stores"]] == ["b-tours", "b-blois"])
    check("it may create managers and employés, not administrateurs", d["me"]["can_create"] == ["manager", "staff"])
    T.create_user(T.UserIn(email="sara@corner.fr", first_name="Sara", role="manager", branch_ids=["b-tours"]), token=ALI)
    check("a manager in one of its establishments", db.users.find_one({"email": "sara@corner.fr"})["branch_ids"] == ["b-tours"])
    check("not in an establishment it does not manage",
          refused(lambda: T.create_user(T.UserIn(email="z@c.fr", role="manager", branch_ids=["b-orleans"]), token=ALI))[0] == 403)
    check("a manager works in exactly one establishment",
          refused(lambda: T.create_user(T.UserIn(email="z@c.fr", role="manager", branch_ids=["b-tours", "b-blois"]), token=ALI)))
    check("it cannot create another administrateur",
          refused(lambda: T.create_user(T.UserIn(email="z@c.fr", role="administrateur", branch_ids=["b-tours"]), token=ALI))[0] == 403)

    SARA = as_("sara@corner.fr", "manager")
    print("\nManager → Employés de son établissement")
    check("a manager may only create employés", T.get_team(token=SARA)["me"]["can_create"] == ["staff"])
    T.create_user(T.UserIn(email="lea@corner.fr", first_name="Léa", role="staff", branch_ids=["b-tours"]), token=SARA)
    check("an employé in its establishment", db.users.find_one({"email": "lea@corner.fr"})["branch_ids"] == ["b-tours"])
    check("not elsewhere",
          refused(lambda: T.create_user(T.UserIn(email="k@c.fr", role="staff", branch_ids=["b-blois"]), token=SARA))[0] == 403)
    T.create_user(T.UserIn(email="karim@corner.fr", role="staff", branch_ids=["b-orleans"]), token=OWNER)

    print("\nChacun ne voit que ce qui est sous lui")
    seen = lambda tok: sorted(u["email"] for u in T.get_team(token=tok)["users"])
    check("the owner sees everyone",
          seen(OWNER) == sorted(["meriem@corner.fr", "old.manager@corner.fr", "ali@corner.fr", "sara@corner.fr",
                                 "lea@corner.fr", "karim@corner.fr"]))
    check("the administrateur sees itself and its establishments' people — not Orléans, not the owner",
          seen(ALI) == ["ali@corner.fr", "lea@corner.fr", "sara@corner.fr"])
    check("the manager sees itself and its employés", seen(SARA) == ["lea@corner.fr", "sara@corner.fr"])
    rows = {u["email"]: u for u in T.get_team(token=ALI)["users"]}
    check("it cannot manage itself", rows["ali@corner.fr"]["manageable"] is False)
    check("but manages the people below it", rows["sara@corner.fr"]["manageable"] and rows["lea@corner.fr"]["manageable"])
    check("a manager cannot touch its administrateur",
          refused(lambda: T.set_status("ali@corner.fr", T.StatusIn(active=False), token=SARA))[0] == 403)
    check("an administrateur cannot touch an employé outside its establishments",
          refused(lambda: T.delete_user("karim@corner.fr", token=ALI))[0] == 403)
    check("nobody can touch the owner",
          refused(lambda: T.set_status("meriem@corner.fr", T.StatusIn(active=False), token=ALI))[0] == 403)
    check("another shop's accounts are out of reach",
          refused(lambda: T.delete_user("solo@solo.fr", token=OWNER))[0] == 404)

    print("\nModifier, déplacer, désactiver")
    T.update_user("sara@corner.fr", T.UserUpdate(first_name="Sara", last_name="K.", role="manager",
                                                  branch_ids=["b-blois"]), token=ALI)
    check("a manager can be moved to another of the administrateur's establishments",
          db.users.find_one({"email": "sara@corner.fr"})["branch_ids"] == ["b-blois"])
    check("its manager then no longer manages Léa (still in Tours)",
          refused(lambda: T.delete_user("lea@corner.fr", token=SARA))[0] == 403)
    T.store_access("b-orleans", "ali@corner.fr", T.StoreAccessIn(enabled=True), token=OWNER)
    check("the owner gives Ali a third establishment", db.users.find_one({"email": "ali@corner.fr"})["branch_ids"] == ["b-blois", "b-orleans", "b-tours"])
    check("covering all of them, Ali's scope becomes all", T.scope_of(db.users.find_one({"email": "ali@corner.fr"})) == "all")
    T.store_access("b-orleans", "ali@corner.fr", T.StoreAccessIn(enabled=False), token=OWNER)
    check("and takes it back", "b-orleans" not in db.users.find_one({"email": "ali@corner.fr"})["branch_ids"])
    T.store_access("b-tours", "karim@corner.fr", T.StoreAccessIn(enabled=True), token=OWNER)
    check("giving an employé an establishment moves it there", db.users.find_one({"email": "karim@corner.fr"})["branch_ids"] == ["b-tours"])
    check("an employé cannot be left without one",
          refused(lambda: T.store_access("b-tours", "karim@corner.fr", T.StoreAccessIn(enabled=False), token=OWNER)))
    out = T.new_password("lea@corner.fr", token=ALI)
    check("a new password is generated and shown once", out["credentials"]["email"] == "lea@corner.fr")
    T.set_status("lea@corner.fr", T.StatusIn(active=False), token=ALI)
    check("an account can be switched off", db.users.find_one({"email": "lea@corner.fr"})["active"] is False)

    print("\nCe que le serveur laisse passer")
    LEA = as_("lea@corner.fr", "staff")
    check("a switched-off employé is refused at once, token or not", guard(LEA, ["business_owner", "manager", "staff"]) == 401)
    T.set_status("lea@corner.fr", T.StatusIn(active=True), token=ALI)
    check("switched back on, it scans again", guard(LEA, ["business_owner", "manager", "staff"]) == 200)
    check("an employé never reaches the manager's data pages", guard(LEA, ["business_owner", "manager"]) == 403)
    check("a manager covering one of three establishments is kept out of the data pages for now",
          guard(SARA, ["business_owner", "manager"]) == 403)
    check("it still reaches the team page", guard(SARA, ["business_owner", "administrateur", "manager"], partial_ok=True) == 200)
    check("and the scan, which works on its own shop", guard(SARA, ["business_owner", "manager", "staff"]) == 200)
    OLD = as_("old.manager@corner.fr", "manager")
    check("a manager created before establishments keeps its access (it covers all)", guard(OLD, ["business_owner", "manager"]) == 200)
    check("an administrateur is not on any data page yet", guard(ALI, ["business_owner", "manager"]) == 403)
    check("a deleted account is refused", (T.delete_user("karim@corner.fr", token=OWNER),
                                           guard(as_("karim@corner.fr", "staff"), ["staff"]))[1] == 401)
    check("the owner is never slowed down by these checks", guard(OWNER, ["business_owner"]) == 200)

    print("\nConnexion")
    from services import password_policy
    pw = password_policy.generate()
    db.users.update_one({"email": "lea@corner.fr"}, {"$set": {"hashed_password": auth.hash_password(pw)}})
    from fastapi import Response
    server.login(server.LoginRequest(email="lea@corner.fr", password=pw), Response())
    check("a login records Dernière connexion", db.users.find_one({"email": "lea@corner.fr"}).get("last_login_at") is not None)
    check("and the account leaves Invitations en attente",
          "lea@corner.fr" not in [u["email"] for u in T.get_team(token=OWNER)["pending"]])
    check("an account never used is pending", "sara@corner.fr" in [u["email"] for u in T.get_team(token=OWNER)["pending"]])
    T.set_status("lea@corner.fr", T.StatusIn(active=False), token=OWNER)
    check("a switched-off account cannot log in",
          refused(lambda: server.login(server.LoginRequest(email="lea@corner.fr", password=pw), Response()))[0] == 403)
    me = server.get_me(token_data=SARA)
    check("/auth/me tells the app a manager's establishments and scope",
          me.get("branch_ids") == ["b-blois"] and me.get("scope") == "partial" and me.get("role_label") == "Manager")

    print("\nPermissions")
    d = T.get_team(token=OWNER)
    check("an administrateur has everything on its establishments except billing and deleting the account",
          d["matrix"]["administrateur"]["billing"] is False and d["matrix"]["administrateur"]["delete"] is False
          and d["matrix"]["administrateur"]["settings"] == "own")
    check("a manager: clients, campaigns, its employés — no settings",
          d["matrix"]["manager"]["settings"] is False and d["matrix"]["manager"]["campaigns"] == "own"
          and d["matrix"]["manager"]["team"] == "own")
    check("an employé only scans", [k for k, v in d["matrix"]["staff"].items() if v] == ["scan"])
    check("the rows carry their permission chips",
          {u["email"]: u for u in d["users"]}["sara@corner.fr"]["permissions"][:2] == ["Enregistrer une visite", "Analyses"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
