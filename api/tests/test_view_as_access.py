"""
« Accéder au compte » with full access (user, 2026-10-09): past the token's
30 minutes every page of the business answered « Not enough permissions »
under a banner still saying « accès complet » — the expired token fell back
to the super admin's own cookie. Now an expired one says so (401
VIEW_EXPIRED), the tab renews it, and every owner page works in the meantime.

Run: cd api && /usr/local/bin/python3 tests/test_view_as_access.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-view-as")
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

    def http(method, url, cookies=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test",
                                         cookies=cookies or {}) as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "ok", "name": "ok", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.users.insert_one({"email": "own@x.fr", "role": "business_owner", "tenant_id": "t1"})
    db.users.insert_one({"email": "admin@fidclic.com", "role": "super_admin", "tenant_id": None})
    admin = auth.create_access_token({"sub": "admin@fidclic.com", "role": "super_admin"})
    COOKIE = {"access_token": admin}

    r = http("POST", "/api/admin/commerces/t1/view-as", headers={"Authorization": "Bearer " + admin})
    view = r.json()["token"]
    check(f"the super admin opens the account with full access ({r.status_code})", r.status_code == 200 and r.json()["full_access"])
    H = {"Authorization": "Bearer " + view}

    print("1. Toutes les pages du commerce")
    paths = sorted({p.path for p in server.app.routes if getattr(p, "methods", None) and "GET" in p.methods
                    and p.path.startswith("/api/owner/") and "{" not in p.path})
    refused = {}
    for p in paths:
        s = http("GET", p, headers=H, cookies=COOKIE)
        if s.status_code in (401, 403):
            refused[p] = s.json().get("detail")
    hidden = {p for p in refused if "/facturation/" in p}            # e-invoicing: hidden module, on purpose
    check(f"{len(paths)} owner pages answer the super admin; only the hidden Facturation module refuses ({len(refused)})",
          set(refused) == hidden)
    r = http("PUT", "/api/owner/referrals/config", headers=H, cookies=COOKIE, json={"enabled": True})
    check(f"…and it can change things (Parrainage settings) ({r.status_code})", r.status_code == 200)
    act = db.audit_logs.find_one({"action": "admin.act_as.write", "actor": "admin@fidclic.com"}) \
        or db.audit_logs.find_one({"event": "admin.act_as.write"})
    check("…recorded under the super admin's name in the journal", act)

    print("\n2. Après 30 minutes")
    expired = auth.create_access_token({"sub": "own@x.fr", "role": "business_owner", "tenant_id": "t1",
                                        "view_by": "admin@fidclic.com", "act_by": "admin@fidclic.com"},
                                       dt.timedelta(minutes=-1))
    r = http("GET", "/api/owner/referrals/overview", headers={"Authorization": "Bearer " + expired}, cookies=COOKIE)
    det = r.json().get("detail") or {}
    check(f"an expired account token no longer falls back to the super admin's cookie: 401 VIEW_EXPIRED ({r.status_code})",
          r.status_code == 401 and det.get("code") == "VIEW_EXPIRED" and det.get("tenant_id") == "t1")
    r = http("POST", "/api/admin/commerces/t1/view-as", headers={"Authorization": "Bearer " + admin}, cookies=COOKIE)
    check(f"the tab renews it with the super admin's own session ({r.status_code})", r.status_code == 200 and r.json()["token"])
    r = http("GET", "/api/owner/referrals/overview", headers={"Authorization": "Bearer " + r.json()["token"]}, cookies=COOKIE)
    check(f"…and the page works again ({r.status_code})", r.status_code == 200)
    r = http("GET", "/api/owner/referrals/overview", headers={"Authorization": "Bearer " + admin})
    check(f"the super admin's own session is not a business account (403 as before) ({r.status_code})", r.status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
