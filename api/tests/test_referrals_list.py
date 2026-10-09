"""
Parrainage › Derniers parrainages › « Voir tous » (QA R5 F25, 2026-10-09:
only 10 of 51 reachable on screen). Every row is reachable, 20 per page,
searchable by the parrain's or the filleul's name.

Run: cd api && /usr/local/bin/python3 tests/test_referrals_list.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-referrals-list")
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
    now = dt.datetime.now(dt.timezone.utc)
    for tid in ("t1", "t2"):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid, "plan": "vip", "subscription_status": "active"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.customers.insert_one({"id": "p0", "tenant_id": "t1", "name": "Hélène Parrain", "tier": "gold"})
    for i in range(51):
        name = "Zoé Éloïse" if i == 7 else f"Filleul {i:02d}"
        db.customers.insert_one({"id": f"f{i}", "tenant_id": "t1", "name": name})
        db.referral_redemptions.insert_one({"tenant_id": "t1", "referrer_customer_id": "p0", "referee_customer_id": f"f{i}",
                                            "created_at": now - dt.timedelta(hours=i), "referrer_points": 50, "source": "card"})
    db.customers.insert_one({"id": "x", "tenant_id": "t2", "name": "Autre Boutique"})
    db.referral_redemptions.insert_one({"tenant_id": "t2", "referrer_customer_id": "x", "referee_customer_id": "x",
                                        "created_at": now, "referrer_points": 50})

    def get(q=""):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get("/api/owner/referrals/list" + q, headers=H)
        return asyncio.get_event_loop().run_until_complete(run()).json()

    print("\nVoir tous")
    p1, p2, p3 = get("?page=1"), get("?page=2"), get("?page=3")
    check("51 parrainages, 3 pages of 20", p1["total"] == 51 and p1["pages"] == 3 and len(p1["rows"]) == 20)
    check("page 3 holds the last 11", len(p3["rows"]) == 11)
    ids = [r["id"] for r in p1["rows"] + p2["rows"] + p3["rows"]]
    check("every row reachable, none twice", len(ids) == 51 and len(set(ids)) == 51)
    ats = [r["at"] for r in p1["rows"] + p2["rows"] + p3["rows"]]
    check("newest first, across the pages", ats == sorted(ats, reverse=True))
    check("a page past the end shows the last one", get("?page=9")["page"] == 3)
    check("another shop's parrainage never shows", all(r["parrain"]["name"] != "Autre B." for r in p1["rows"] + p2["rows"] + p3["rows"]))

    print("\nRecherche")
    r = get("?search=eloise")
    check("« eloise » finds « Zoé Éloïse » (accents ignored)", r["total"] == 1 and r["rows"][0]["filleul"]["name"].startswith("Zoé"))
    check("the parrain's name finds all of theirs", get("?search=helene")["total"] == 51)
    check("nothing found → 0, page 1", get("?search=personne")["total"] == 0)
    check("per_page is capped", get("?per_page=500").get("detail") is not None or len(get("?per_page=100")["rows"]) == 51)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
