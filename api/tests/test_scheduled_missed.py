"""
Scheduled campaigns after the daily cron was off: on time → sent (every 15
minutes now); more than a day late → « Non envoyée », never sent on its own;
the business then sends it or drops it. Both schedulers (Campagnes page and
the older scheduled_campaigns).

Run: cd api && /usr/local/bin/python3 tests/test_scheduled_missed.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from starlette.requests import Request
    from models import TokenData
    from features import campaigns_page as CP

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    SENT = []
    CP._deliver = lambda tid, doc, people: SENT.append(doc["id"]) or {"delivered": len(people), "reach": len(people)}
    server._dispatch_campaign_to_customers = lambda tenant, **kw: SENT.append(kw["name"]) or {"id": "x"}

    now = dt.datetime.now(dt.timezone.utc)
    OWNER = TokenData(email="o@cafe.fr", role="business_owner", tenant_id="t1")
    db.tenants.insert_one({"id": "t1", "name": "Café", "plan": "gold"})
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "t1", "name": f"C{i}"} for i in range(3)])
    camp = lambda cid, when: {"id": cid, "tenant_id": "t1", "name": cid, "content": "Offre", "status": "scheduled",   # noqa: E731
                              "scheduled_for": when, "recipient_ids": ["c0", "c1"]}
    db.campaigns.insert_many([camp("on-time", now - dt.timedelta(minutes=10)), camp("august", now - dt.timedelta(days=50)),
                              camp("later", now + dt.timedelta(hours=3))])
    sched = lambda sid, when, rec=None: {"id": sid, "tenant_id": "t1", "name": sid, "content": "Old", "status": "scheduled",  # noqa: E731
                                         "run_at": when, "recurrence": rec, "segment": {"type": "all"}}
    db.scheduled_campaigns.insert_many([sched("old-on-time", now - dt.timedelta(minutes=5)),
                                        sched("old-august", now - dt.timedelta(days=40)),
                                        sched("old-weekly", now - dt.timedelta(days=40), "weekly")])

    print("\nThe 15-minute cron")
    def req(secret=None):
        return Request({"type": "http", "method": "GET", "path": "/api/cron/scheduled-campaigns", "query_string": b"",
                        "headers": [(b"authorization", f"Bearer {secret}".encode())] if secret else []})
    server.CRON_SECRET = "s"
    check("a wrong secret is refused", refused(lambda: server.cron_scheduled_campaigns(req("nope")), 401))
    out = server.cron_scheduled_campaigns(req("s"))
    check("on time: sent", "on-time" in SENT and db.campaigns.find_one({"id": "on-time"})["status"] == "sent")
    check("not yet due: untouched", db.campaigns.find_one({"id": "later"})["status"] == "scheduled")
    check("50 days late: NOT sent, « missed »", "august" not in SENT and db.campaigns.find_one({"id": "august"})["status"] == "missed")
    check("older scheduler: on time sent, late one missed", "old-on-time" in SENT and "old-august" not in SENT
          and db.scheduled_campaigns.find_one({"id": "old-august"})["status"] == "missed")
    wk = db.scheduled_campaigns.find_one({"id": "old-weekly"})
    wk_at = wk["run_at"] if wk["run_at"].tzinfo else wk["run_at"].replace(tzinfo=dt.timezone.utc)
    check("a weekly one skips to its next date, no catch-up burst", "old-weekly" not in SENT and wk["status"] == "scheduled"
          and now < wk_at <= now + dt.timedelta(days=7))
    check("summary", out["campagnes"]["missed"] == 1 and out["legacy"]["missed"] == 1)
    n = len(SENT)
    server.cron_scheduled_campaigns(req("s"))
    check("running twice sends nothing twice", len(SENT) == n)

    print("\nThe business decides")
    pg = CP.page(token_data=OWNER)
    check("both shown under « Non envoyées »", {m["id"] for m in pg["missed"]} == {"august", "old-august"})
    CP.send_missed("august", token_data=OWNER)
    check("« Envoyer maintenant » sends it", "august" in SENT and db.campaigns.find_one({"id": "august"})["status"] == "sent")
    check("…only once", refused(lambda: CP.send_missed("august", token_data=OWNER), 404))
    CP.dismiss_missed("old-august", token_data=OWNER)
    check("« Ne pas envoyer » keeps it, cancelled", db.scheduled_campaigns.find_one({"id": "old-august"})["status"] == "cancelled")
    check("the list is empty again", CP.page(token_data=OWNER)["missed"] == [])
    other = TokenData(email="x@y.fr", role="business_owner", tenant_id="t2")
    db.campaigns.insert_one({**camp("t1-missed", now), "status": "missed"})
    check("another business cannot touch it", refused(lambda: CP.send_missed("t1-missed", token_data=other), 404))

    print("\nThe daily run does the same")
    db.campaigns.insert_one(camp("daily-late", now - dt.timedelta(days=3)))
    server.CRON_SECRET = ""
    server.run_daily_triggers(req())
    check("daily run: late → missed, not sent", db.campaigns.find_one({"id": "daily-late"})["status"] == "missed" and "daily-late" not in SENT)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
