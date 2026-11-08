"""
The old AI stub routes under /api/owner/ai/* opened with « FidClic IA » alone:
a manager without « Clients » got today's birthdays by name, and the tier
counts; a manager of one store got the whole shop. Each now belongs to the
page that shows that data, and counts the store in scope (pentest #437/#447).

Run: cd api && /usr/local/bin/python3 tests/test_ai_stub_rights.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-stubs")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:400])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import golden_set as GS, role_perms as RP

    db = server.db
    GS.seed(db)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def manager(email, stores, **off):
        view = {p["key"]: "view" for p in RP.PAGES}
        view["ai"] = "edit"
        db.users.delete_many({"email": email})
        db.users.insert_one({"email": email, "role": "manager", "tenant_id": GS.SALON, "active": True, "branch_ids": stores,
                             "perms": {b: {**view, **off} for b in stores}})
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": "manager", "tenant_id": GS.SALON})}

    mmdd = dt.datetime.now(ZoneInfo("Europe/Paris")).strftime("%m-%d")
    db.customers.update_many({"tenant_id": GS.SALON}, {"$set": {"birthday": "01-01" if mmdd != "01-01" else "02-02"}})
    db.customers.insert_many([
        {"id": "bd-centre", "tenant_id": GS.SALON, "name": "Alice Centre", "birthday": mmdd, "branch_id": "b1", "tier": "silver", "visits": 12},
        {"id": "bd-gare", "tenant_id": GS.SALON, "name": "Bruno Gare", "birthday": mmdd, "branch_id": "b2", "tier": "bronze", "visits": 2},
        {"id": "bd-gone", "tenant_id": GS.SALON, "name": "Chloé Supprimée", "birthday": mmdd, "branch_id": "b1",
         "deleted_at": dt.datetime.now(dt.timezone.utc)},
        {"id": "bd-other", "tenant_id": GS.AUTRE, "name": "Denis Voisin", "birthday": mmdd},
    ])
    OWNER, GARE, STAFF = GS.headers("owner"), GS.headers("gare"), GS.headers("staff")
    NO_CLIENTS = manager("nocl@gs-salon.test", ["b1", "b2"], customers="none", segmentation="none")
    NO_CA = GS.headers("sans_ca")                 # Analyses, Insights, Catalogue off; Clients on

    print("Anniversaires du jour")
    url = "/api/owner/ai/birthday/today"
    names = lambda h: sorted(b["name"] for b in http("GET", url, h).json().get("birthdays", []))   # noqa: E731
    check("the owner: both stores, no deleted client, no other shop", names(OWNER) == ["Alice Centre", "Bruno Gare"], names(OWNER))
    check("the Gare manager: his store only", names(GARE) == ["Bruno Gare"], names(GARE))
    r = http("GET", url, NO_CLIENTS)
    check("Clients off: refused, no name", r.status_code == 403 and "Alice" not in r.text, (r.status_code, r.text[:150]))
    check("Clients on, Analyses off: allowed", http("GET", url, NO_CA).status_code == 200)

    print("Paliers (tier-optimizer)")
    url = "/api/owner/ai/tier-optimizer/suggestion"
    d = http("GET", url, OWNER).json()["current_distribution"]
    g = http("GET", url, GARE).json()["current_distribution"]
    check("the Gare manager counts fewer clients than the shop", 0 < sum(g.values()) < sum(d.values()), (g, d))
    r = http("GET", url, NO_CLIENTS)
    check("Clients off: refused", r.status_code == 403 and "bronze" not in r.text, r.status_code)
    check("no invented promise (« 142 customers », « similar cafés »)", "142" not in http("GET", url, OWNER).text
          and "similar" not in http("GET", url, OWNER).text)

    print("Les autres")
    check("customer locales: Clients off → refused", http("GET", "/api/owner/ai/translate/customer-locales", NO_CLIENTS).status_code == 403)
    check("newsletter preview: Analyses off → refused", http("GET", "/api/owner/ai/newsletter/preview", NO_CA).status_code == 403)
    check("suggestions (Insights page): Insights off → refused", http("GET", "/api/owner/ai/suggestions", NO_CA).status_code == 403)
    check("suggestions: the owner still has them", http("GET", "/api/owner/ai/suggestions", OWNER).status_code == 200)
    for u in ("/api/owner/ai/birthday/today", "/api/owner/ai/tier-optimizer/suggestion", "/api/owner/ai/suggestions"):
        check(f"staff refused: {u}", http("GET", u, STAFF).status_code == 403)
        check(f"nobody refused: {u}", http("GET", u, {}).status_code in (401, 403))

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
