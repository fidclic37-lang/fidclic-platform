"""
« Attendus de toute façon » (user, 2026-10-25): after a message with no groupe
témoin behind it (anniversaire, offre, one client…), a client who came in
their usual window — the client brain, from their visits before that day —
would have come anyway: shown apart, NOT in CA FidClic. No known rhythm:
counted as before. A message a témoin measured is left whole.

Run: cd api && /usr/local/bin/python3 tests/test_attendus.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-attendus")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


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
    import features.wallet_passes as WP
    from features import automations as AU
    from features import fidclic_impact as FI

    db = server.db
    server.dispatch_to_customer = lambda *a, **k: {"sent": True}
    WP.notify_customer = lambda *a, **k: {}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    # noon UTC: every visit on its own Paris day, whatever the hour the test runs
    base = dt.datetime.now(UTC).replace(hour=11, minute=0, second=0, microsecond=0)
    ago = lambda d: base - dt.timedelta(days=d)                                      # noqa: E731
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    def client(cid, days, amount=10.0):
        for d in days:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": amount, "visit_time": ago(d)})
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "visits": len(days),
                                 "created_at": ago(max(days) + 1)})

    def message(cid, d, kind="birthday", **extra):
        db.push_notifications.insert_one({"tenant_id": "t1", "customer_id": cid, "type": kind, "sent_at": ago(d),
                                          "title": "x", "body": "x", **extra})

    # a weekly regular, due on day −8: the birthday message on −9 changed nothing
    client("due", [50, 43, 36, 29, 22, 15, 8], 12.0)
    message("due", 9)
    # the same habit, but silent for 3 weeks: the message brought them back
    client("late", [58, 51, 44, 37, 30, 8], 20.0)
    message("late", 9)
    # one visit before: no rhythm to say — counted as before
    client("new", [40, 8], 7.0)
    message("new", 9)
    # due too, but the message was a campaign a groupe témoin measured: left whole
    client("camp", [50, 43, 36, 29, 22, 15, 8], 30.0)
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "name": "Promo", "status": "sent", "sent_at": ago(9),
                             "recipient_ids": ["camp"], "holdout_ids": ["someone"]})
    message("camp", 9, "campaign", campaign_id="k1")
    # a filleul with the same habit: their visits are Parrainage, forever
    client("fil", [50, 43, 36, 29, 22, 15, 8], 5.0)
    message("fil", 9)
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referee_customer_id": "fil"})

    print("Qui serait venu de toute façon")
    rows = list(db.visits.find({"tenant_id": "t1", "visit_time": {"$gte": ago(10)}}, {"_id": 0}))
    imp = FI.impact("t1", rows)
    check("the due regular after an anniversaire: « attendu », 12 € apart", imp["attendus"] == {"revenue": 12.0, "visits": 1}, imp)
    check("CA FidClic keeps the late one (20 €), the new one (7 €), the measured campaign (30 €) and the filleul (5 €)",
          imp["revenue"] == 62.0 and imp["sources"]["parrainage"]["revenue"] == 5.0 and imp["sources"]["automatisations"]["revenue"] == 27.0
          and imp["sources"]["campagnes"]["revenue"] == 30.0, imp)
    pos = FI.expected_anyway("t1", [r for r in rows if r["customer_id"] in ("due", "late", "new")])
    names = {[r for r in rows if r["customer_id"] in ("due", "late", "new")][i]["customer_id"] for i in pos}
    check("the brain read from the visits BEFORE that day: only « due »", names == {"due"}, names)

    print("Le message mesuré par un groupe témoin")
    row = {"id": "a1", "tenant_id": "t1", "scenario": "inactive", "status": "active", "message": {"title": "x", "body": "x"}}
    bday = {"id": "a2", "tenant_id": "t1", "scenario": "birthday", "status": "active", "message": {"title": "x", "body": "x"}}
    from features import temoin as T
    T.holds_automation = lambda *a, **k: False            # every relance messaged here
    AU._deliver("t1", row, db.customers.find_one({"id": "new"}, {"_id": 0}), {}, base)
    AU._deliver("t1", bday, db.customers.find_one({"id": "new"}, {"_id": 0}), {}, base)
    check("a relance's card row says a témoin measures it", db.push_notifications.find_one({"automation_id": "a1"})["temoin"] is True)
    check("an anniversaire's does not", db.push_notifications.find_one({"automation_id": "a2"})["temoin"] is False)

    print("Analyses")
    imp2 = http("GET", "/api/owner/analyses?tab=vue&days=30", headers=H).json()["data"]["impact"]
    check("Impact FidClic shows them apart, and says why", imp2["attendus"]["visits"] >= 1
          and "attendus de toute façon" in imp2["note"], imp2.get("attendus"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
