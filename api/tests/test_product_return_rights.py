"""
« Produits qui font revenir » — who may change it (pentest of #417, user
2026-10-31: fix it). Every account that may see Analyses reads the
analysis; changing the shop's window or starting a recompute takes
« Modifier » on Analyses (Équipe & accès). The page is told (`can_edit`)
so « Modifier » / « Recalculer » only show to those who may.

Run: cd api && /usr/local/bin/python3 tests/test_product_return_rights.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-product-return-rights")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
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
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, **extra):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": "a", **extra})}

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "a", "name": "A", "plan": "vip", "is_active": True, "subscription_status": "active"})
    db.users.insert_many([{"email": "o@a", "role": "business_owner", "tenant_id": "a", "active": True},
                          {"email": "m@a", "role": "manager", "tenant_id": "a", "active": True},
                          {"email": "ad@a", "role": "administrateur", "tenant_id": "a", "active": True}])
    db.product_return.insert_one({"tenant_id": "a", "store": "all", "built_at": now, "window_days": 21, "window_source": "rythme",
                                  "coverage": {"total": 1, "with_items": 1, "pct": 100},
                                  "views": {"first": {"n": 1, "products": []}, "all": {"n": 1, "products": []}}})
    O, M, AD = tok("o@a", "business_owner"), tok("m@a", "manager"), tok("ad@a", "administrateur")
    URL = "/api/owner/analyses/produits-retour"

    print("Qui peut changer l'analyse")
    r = http("GET", URL, M)
    check("a manager who only sees Analyses reads it", r.status_code == 200, r.text)
    check("…and is told it cannot change it (no « Modifier »)", r.json().get("can_edit") is False, r.json().get("can_edit"))
    r = http("PUT", f"{URL}/fenetre", M, json={"days": 30})
    check("…cannot change the shop's window (403)", r.status_code == 403, (r.status_code, r.text))
    check("…and the window is unchanged", "product_return_window_days" not in (db.tenants.find_one({"id": "a"}) or {}))
    r = http("POST", f"{URL}/recalculer", M)
    check("…cannot start a recompute (403)", r.status_code == 403, (r.status_code, r.text))
    check("…so no job is queued", db.ai_jobs.count_documents({"tenant_id": "a", "by": "owner"}) == 0)

    check("an administrateur (« Modifier » on Analyses) may", http("GET", URL, AD).json().get("can_edit") is True
          and http("PUT", f"{URL}/fenetre", AD, json={"days": 30}).status_code == 200)
    db.ai_jobs.delete_many({})
    check("the owner may", http("GET", URL, O).json().get("can_edit") is True
          and http("PUT", f"{URL}/fenetre", O, json={"days": None}).status_code == 200
          and http("POST", f"{URL}/recalculer", O).status_code == 200)
    db.users.update_one({"email": "m@a"}, {"$set": {"perms": {"main": {"analytics": "edit"}}}})
    check("a manager given « Modifier » on Analyses may", http("PUT", f"{URL}/fenetre", M, json={"days": 14}).status_code == 200,
          http("GET", URL, M).json().get("can_edit"))
    VO = tok("o@a", "business_owner", view_by="adm@x", view_only=True)
    check("read-only « Accéder au compte » may not", http("POST", f"{URL}/recalculer", VO).status_code in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
