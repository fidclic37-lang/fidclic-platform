"""
Équipe & accès per establishment (user, 2026-10-14: « maine ek aadmi ko bas
ek store ka access diya lekin dusre stores mein bhi uska naam hai »): with a
store chosen in the menu, the list, the role counts and the pending
invitations show its team only — the owner, and the accounts that have it.
« Accès par établissement » still lists everyone (where a store is given).

Run: cd api && /usr/local/bin/python3 tests/test_team_per_store.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-team-per-store")
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

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "lib", "name": "LIBERTÉ", "is_main": True}, {"id": "pal", "name": "PALISSY"},
                      {"id": "mon", "name": "PL-MONSTER"}]},
        {"id": "t2", "slug": "solo", "name": "Solo", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.users.insert_many([
        {"id": "o", "email": "o@x.fr", "first_name": "Mahdi", "role": "business_owner", "tenant_id": "t1", "active": True},
        {"id": "a", "email": "amjad@x.fr", "first_name": "Amjad", "role": "administrateur", "tenant_id": "t1",
         "active": True, "branch_ids": ["lib", "pal", "mon"], "last_login_at": None},
        {"id": "h", "email": "hamada@x.fr", "first_name": "Hamada", "role": "administrateur", "tenant_id": "t1",
         "active": True, "branch_ids": ["mon"]},
        {"id": "z", "email": "hamza@x.fr", "first_name": "Hamza", "role": "administrateur", "tenant_id": "t1",
         "active": True, "branch_ids": ["pal"]},
        {"id": "s", "email": "staff@x.fr", "first_name": "Sam", "role": "staff", "tenant_id": "t1",
         "active": True, "branch_ids": ["pal"]},
        {"id": "r", "email": "r@x.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
        {"id": "r2", "email": "r2@x.fr", "role": "staff", "tenant_id": "t2", "active": True},
    ])
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, AMJAD, SOLO = tok("o@x.fr", "business_owner"), tok("amjad@x.fr", "administrateur"), tok("r@x.fr", "business_owner", "t2")

    def team(who, store=None):
        h = {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}
        return http("GET", "/api/owner/team-access", headers=h).json()

    names = lambda d: sorted(u["email"].split("@")[0] for u in d["users"])  # noqa: E731

    print("1. Each store shows its own team")
    pal = team(OWNER, "pal")
    check(f"PALISSY: the owner, Amjad, Hamza, Sam — not Hamada ({names(pal)})", names(pal) == ["amjad", "hamza", "o", "staff"])
    mon = team(OWNER, "mon")
    check(f"PL-MONSTER: the owner, Amjad, Hamada ({names(mon)})", names(mon) == ["amjad", "hamada", "o"])
    lib = team(OWNER, "lib")
    check(f"LIBERTÉ: the owner and Amjad ({names(lib)})", names(lib) == ["amjad", "o"])
    counts = {r["key"]: r["count"] for r in pal["roles"]}
    check(f"the role cards count that store's team ({counts.get('administrateur')} administrateurs at PALISSY)",
          counts.get("administrateur") == 2 and counts.get("staff") == 1)
    check("pending invitations: that store's only", {u["email"] for u in mon["pending"]} <= {"amjad@x.fr", "hamada@x.fr"}
          and "hamza@x.fr" not in {u["email"] for u in mon["pending"]})

    print("\n2. « Accès par établissement » still reaches everyone")
    check("all_users lists every account (to give Hamada PALISSY from there)",
          sorted(u["email"].split("@")[0] for u in pal["all_users"]) == ["amjad", "hamada", "hamza", "o", "staff"])
    r = http("PUT", "/api/owner/team-access/stores/pal/users/h", headers={"Authorization": OWNER, "X-FidClic-Store": "pal"},
             json={"enabled": True})
    check(f"Hamada given PALISSY ({r.status_code})", r.status_code == 200 and "hamada" in names(r.json()))
    check("…and now in PALISSY's list", "hamada" in names(team(OWNER, "pal")))

    print("\n3. As before where nothing is chosen")
    check("no store chosen: everyone", names(team(OWNER)) == ["amjad", "hamada", "hamza", "o", "staff"])
    check("an administrateur in PALISSY: its own row is always there", "amjad" in names(team(AMJAD, "pal")))
    check("a one-shop account: unchanged", sorted(u["email"] for u in team(SOLO)["users"]) == ["r2@x.fr", "r@x.fr"])
    check("another account's store id is ignored", sorted(u["email"] for u in team(SOLO, "pal")["users"]) == ["r2@x.fr", "r@x.fr"])

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
