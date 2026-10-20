"""
A campaign planned for 14:20 left at 14:30 (user, 2026-10-20): planned
campaigns only went on the 15-minute tick. /api/cron/campaigns-due runs
every minute (vercel.json) and sends just the campaigns whose minute has
come — never twice, even next to the tick.

Run: cd api && /usr/local/bin/python3 tests/test_campaigns_on_the_minute.py
"""
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-campaigns-minute")
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
    import httpx
    from features import campaigns_page as CP

    db = server.db
    sent = []
    CP._deliver = lambda tid, doc, people: sent.append(doc["id"]) or {"delivered": len(people), "reach": len(people)}
    server.CRON_SECRET = "s3cret"

    def get(url, headers=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.get(url, headers=headers or {})
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "k", "name": "Kebab", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "A", "barcode_id": "FT-A"})
    db.campaigns.insert_many([
        {"id": "due", "tenant_id": "t1", "status": "scheduled", "scheduled_for": now - dt.timedelta(seconds=20),
         "recipient_ids": ["c1"], "name": "ANJONAO"},
        {"id": "later", "tenant_id": "t1", "status": "scheduled", "scheduled_for": now + dt.timedelta(minutes=5),
         "recipient_ids": ["c1"], "name": "plus tard"},
    ])

    crons = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "vercel.json")))["crons"]
    check("vercel.json runs it every minute",
          any(c["path"] == "/api/cron/campaigns-due" and c["schedule"] == "* * * * *" for c in crons))
    check("refused without the cron secret", get("/api/cron/campaigns-due").status_code == 401)
    r = get("/api/cron/campaigns-due", {"x-cron-secret": "s3cret"})
    check(f"the minute it is due, it leaves ({r.status_code}, {sent})", r.status_code == 200 and sent == ["due"])
    check("…marked sent", db.campaigns.find_one({"id": "due"})["status"] == "sent")
    check("one planned in 5 minutes waits", db.campaigns.find_one({"id": "later"})["status"] == "scheduled")
    get("/api/cron/campaigns-due", {"x-cron-secret": "s3cret"})
    server.tick_pass()
    check("next to the tick, never sent twice", sent.count("due") == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
