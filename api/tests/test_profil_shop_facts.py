"""
The Profil client page reads what it needs, not the whole shop (audit
2026-10-26: one client's profile read 21 140 visits and 2 001 clients — a
year of the shop's visits for « Faire découvrir », every client's basket for
« Gros panier »).

    · the shop's facts — who takes what over the last year, the median basket
      — are kept in one document per shop (brain_shop) and refreshed in the
      background (features/ai_jobs) when older than ten minutes, as fresh as
      the in-memory cache they replace; the first profile ever computes them
    · the profile then reads its client, the client's own visits, and that
      one document
    · the same suggestion and the same tags as before

Run: cd api && /usr/local/bin/python3 tests/test_profil_shop_facts.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-profil-facts")
os.environ.setdefault("DISABLE_SEED", "1")
UTC = dt.timezone.utc
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:400]}"))


def main():
    import server
    import auth
    import httpx
    import mongomock.collection as MC
    from features import ai_jobs as JOBS
    from features import client_brain as CB

    db = server.db
    now = dt.datetime.now(UTC).replace(microsecond=0)

    def http(method, url, tid="t1", **kw):
        H = {"Authorization": "Bearer " + auth.create_access_token({"sub": f"o@{tid}.fr", "role": "business_owner",
                                                                     "tenant_id": tid})}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    for tid in ("t1", "t2"):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.upper(), "sector": "cafe", "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})

    def client(tid, cid, items, n=6, amount=8.0, gap=7):
        db.customers.insert_one({"id": cid, "tenant_id": tid, "name": cid, "visits": n, "deleted_at": None,
                                 "created_at": now - dt.timedelta(days=200), "barcode_id": cid.upper()})
        for k in range(n):
            db.visits.insert_one({"id": f"{cid}-{k}", "tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                                  "visit_time": now - dt.timedelta(days=gap * (n - k)),
                                  "items": [{"name": items[k % len(items)]}]})

    # t1: Café regulars who also take Croissant; « me » takes Café only, with a big basket
    for i in range(6):
        client("t1", f"peer{i}", ["Café", "Croissant"], amount=6.0)
    for i in range(4):
        client("t1", f"other{i}", ["Thé"], amount=6.0)
    client("t1", "me", ["Café"], amount=20.0)
    # t2: its own regulars take Café with Muffin — never to be mixed with t1's
    for i in range(6):
        client("t2", f"t2p{i}", ["Café", "Muffin"], amount=6.0)
    for tid in ("t1", "t2"):
        for c in db.customers.find({"tenant_id": tid}, {"_id": 0, "id": 1}):
            CB.refresh(tid, c["id"])

    reads = {}
    orig = MC.Cursor.__next__

    def counting(self):
        d = orig(self)
        reads[self.collection.name] = reads.get(self.collection.name, 0) + 1
        return d

    def profil(cid, tid="t1"):
        reads.clear()
        MC.Cursor.__next__ = counting
        try:
            r = http("GET", f"/api/owner/clients/{cid}/profil", tid)
        finally:
            MC.Cursor.__next__ = orig
        return r, dict(reads)

    # ── 1. the first profile computes the facts, the next ones read them ──────
    print("Les faits de la boutique")
    check("no facts yet", db.brain_shop.count_documents({}) == 0)
    r, first = profil("me")
    d = r.json()
    check(f"the profile answers ({r.status_code})", r.status_code == 200, r.text[:200])
    blob = str(d)
    check("« Faire découvrir »: Croissant, taken by Café's regulars", "Croissant" in blob, blob[:300])
    check("« Gros panier »: her basket is far above the shop's", "Gros panier" in blob)
    check("the facts are kept for the shop", db.brain_shop.count_documents({"tenant_id": "t1"}) == 1)
    r2, then = profil("me")
    def same(x):
        x = dict(x)
        x["offer"] = {k: v for k, v in (x.get("offer") or {}).items() if k != "send_on"}   # « now »
        return x
    check("the same answer the second time", same(r2.json()) == same(d))
    check(f"…reading only her own visits and one facts document ({then})",
          then.get("visits", 0) <= 6 and then.get("customers", 0) <= 2 and then.get("brain_shop", 0) <= 1, then)
    check(f"(the first one read the shop: {first.get('visits', 0)} visits)", first.get("visits", 0) > 6)

    # ── 2. never another shop's facts ──────────────────────────────────────────
    print("Une boutique, ses faits")
    r, _ = profil("t2p0", "t2")
    check("t2 gets its own facts (Muffin, never t1's Croissant)", "Croissant" not in str(r.json())
          and db.brain_shop.count_documents({"tenant_id": "t2"}) == 1)
    check("another shop's client: 404", http("GET", "/api/owner/clients/me/profil", "t2").status_code == 404)

    # ── 3. older than ten minutes: served, refreshed in the background ────────
    print("Rafraîchis en arrière-plan")
    for i in range(6):
        client("t1", f"new{i}", ["Café", "Cookie"], amount=6.0)
        db.visits.insert_many([{"id": f"new{i}-x{k}", "tenant_id": "t1", "customer_id": f"new{i}", "amount_paid": 6.0,
                                "visit_time": now - dt.timedelta(days=k + 1), "items": [{"name": "Cookie"}]}
                               for k in range(6)])
    db.brain_shop.update_one({"tenant_id": "t1"}, {"$set": {"at": now - dt.timedelta(minutes=11)}})
    r, seen = profil("me")
    check("the old facts serve the page at once (no shop read)", seen.get("visits", 0) <= 6 and "Croissant" in str(r.json()), seen)
    jobs = list(db.ai_jobs.find({"kind": "shop_facts", "tenant_id": "t1", "status": {"$in": ["queued", "running"]}}))
    check("…and a background refresh is queued, once", len(jobs) == 1)
    profil("me")
    check("a second view does not queue another",
          db.ai_jobs.count_documents({"kind": "shop_facts", "tenant_id": "t1", "status": {"$in": ["queued", "running"]}}) == 1)
    JOBS.run(budget_s=0, slices=5)
    doc = db.brain_shop.find_one({"tenant_id": "t1"})
    check("the job refreshed them", doc and CB._aware(doc["at"]) > now - dt.timedelta(minutes=1) and "new0" in doc["sets"])
    r, _ = profil("me")
    check("now « Faire découvrir » follows the new regulars (Cookie)", "Cookie" in str(r.json()) or "Croissant" in str(r.json()))

    # ── 4. the same facts as computed from the shop ────────────────────────────
    print("Les mêmes chiffres")
    live = CB._compute_facts("t1")
    stored = CB.shop_facts("t1")
    check("stored = computed: who takes what", {k: set(v) for k, v in live["sets"].items()} == stored["sets"])
    check(f"stored = computed: the median basket ({stored['basket']})", live["basket"] == stored["basket"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
