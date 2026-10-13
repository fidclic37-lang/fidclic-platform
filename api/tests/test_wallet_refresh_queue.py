"""
Wallet refresh queue (user, 2026-10-13: renaming an establishment answered
« erreur 504 »). A save used to send every card to Apple and, one request per
card, to Google, inside the request; past Vercel's 30 s it was cut. Cards are
now queued and worked for a few seconds; the page sends the rest right after
(POST /api/owner/wallet/refresh) and the daily cron catches anything left.
Every /api answer also says where its time went (Server-Timing).

Run: cd api && /usr/local/bin/python3 tests/test_wallet_refresh_queue.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-wallet-refresh")
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
    from features import wallet_passes as WP

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "sector": "salon", "street": "11 Place de la Liberté", "postal_code": "37000", "city": "Tours",
                           "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True, "status": "active"},
                                        {"id": "pal", "name": "ROYAL TRIM PALISSY", "status": "active"},
                                        {"id": "mon", "name": "ROYAL TRIM PL-MONSTER", "status": "active"}]})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM", "reward_threshold_stamps": 10})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    serials = []
    for i in range(40):
        bc = f"FT-Q{i:07d}"
        serials.append(bc)
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "barcode_id": bc, "name": f"Client {i}",
                                 "visits": 1, "points": 10, "branch_id": "main"})
        db.google_wallet_objects.insert_one({"serial": bc, "tenant_id": "t1", "object_id": f"3388.{bc}"})
    OWNER = "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})

    # Google, configured and slow: 0.2 s a card (40 cards → 8 s, past the budget)
    calls = []
    WP.google_configured = lambda: True
    WP._gw_access_token = lambda: "token"

    def slow_call(method, path, body, token):
        time.sleep(0.2)
        calls.append((method, path))
        return 200, {}
    WP._gw_call = slow_call
    WP.REFRESH_BUDGET_S = 1.0

    print("\nA save is no longer held up by every card")
    import contextvars
    t0 = time.perf_counter()
    r = contextvars.copy_context().run(WP.notify_tenant, "t1")      # as one request
    took = time.perf_counter() - t0
    left = WP.refresh_left("t1")
    check(f"notify_tenant returns within its budget ({took:.1f} s for 40 slow cards)", took < 2.5)
    check(f"some cards sent at once ({r['google'].get('synced')}), the rest queued ({left})", 0 < r["google"].get("synced", 0) < 40
          and left == 40 - r["google"].get("synced", 0) and r["left"] == left)
    q = db.wallet_refresh.find_one({"tenant_id": "t1"})
    check("the queue knows the design changed (the class is sent again)", q and q.get("design") is True)

    t0 = time.perf_counter()
    r = http("PUT", "/api/owner/etablissement", headers={"Authorization": OWNER, "X-FidClic-Store": "main"},
             json={"business": {"name": "ROYAL TRIM LIBERTÉ", "phone": "", "email": "", "sector": "salon", "description": ""},
                   "address": {"street": "11 Place de la Liberté", "postal_code": "37000", "city": "Tours"}})
    took = time.perf_counter() - t0
    check(f"renaming the establishment answers in time ({r.status_code}, {took:.1f} s)", r.status_code == 200 and took < 5)
    t = db.tenants.find_one({"id": "t1"})
    check("…and the name is saved", next(b for b in t["branches"] if b["id"] == "main")["name"] == "ROYAL TRIM LIBERTÉ")
    st = r.headers.get("server-timing", "")
    check(f"the answer says where its time went ({st})", "app;dur=" in st and "db;dur=" in st)

    print("\nThe page sends the rest right after")
    rounds = 0
    while True:
        rounds += 1
        r = http("POST", "/api/owner/wallet/refresh", headers={"Authorization": OWNER})
        if r.status_code != 200 or not r.json().get("left") or rounds > 20:
            break
    check(f"emptied in {rounds} follow-up call(s)", r.status_code == 200 and r.json().get("left") == 0)
    check("the queue is gone", db.wallet_refresh.count_documents({"tenant_id": "t1"}) == 0)
    puts = {p for m, p in calls if m == "PUT" and p.startswith("/loyaltyObject/")}
    check(f"every card reached Google ({len(puts)} of 40)", len(puts) == 40)
    r = http("POST", "/api/owner/wallet/refresh", headers={"Authorization": OWNER})
    check("nothing waiting: a cheap answer", r.status_code == 200 and r.json() == {"left": 0})
    r = http("POST", "/api/owner/wallet/refresh")
    check(f"not signed in: refused ({r.status_code})", r.status_code in (401, 403))

    print("\nThe daily run catches what a closed page left")
    WP.queue_refresh("t1", serials[:5])
    check("five cards waiting", WP.refresh_left("t1") == 5)
    WP.REFRESH_BUDGET_S = 6.0
    n = WP.drain_all(budget_each=5.0)
    check(f"drain_all handled the account ({n})", n == 1 and WP.refresh_left("t1") == 0)

    print("\nNothing is lost when a card fails")
    def failing(method, path, body, token):
        if "Q0000003" in path:
            raise RuntimeError("Google down")
        return 200, {}
    WP._gw_call = failing
    WP.queue_refresh("t1", serials[:5])
    WP.drain_refresh("t1", 5.0)
    row = db.google_wallet_objects.find_one({"serial": "FT-Q0000003"})
    check("a card Google refuses is recorded (as before), the others still sent", (row.get("last_sync_result") or "").startswith("erreur")
          and WP.refresh_left("t1") == 0)
    check("a scan still refreshes its card at once (not queued)",
          WP.notify_passes(["FT-Q0000001"]).get("google", {}).get("synced") == 1 and WP.refresh_left("t1") == 0)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
