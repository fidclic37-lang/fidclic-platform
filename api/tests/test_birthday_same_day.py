"""
Anniversaire the same day, and its offer's validity (user, 2026-10-20):
- after the day's 10:00 round, a birthday that turns up later (birthday
  saved, card added) is greeted on a later tick, until 20:00 Paris; later
  than that, the next morning — never twice;
- a card added less than an hour ago waits that hour (« Bienvenue » first);
- the offer lasts the days the business sets (7 by default): {fin_offre},
  the Wallet card's « Validité », gone from the card once over; a missed
  greeting still goes while the offer lasts, not after.

Run: cd api && /usr/local/bin/python3 tests/test_birthday_same_day.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-birthday-same-day")
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
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind})
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda *a, **k: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "is_active": True})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10})
    old = dt.datetime(2026, 1, 1, tzinfo=UTC)
    for cid, bday in (("c_early", "10-20"), ("c_late", "05-05"), ("c_new", "05-05")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": f"FT-{cid.upper()}",
                                 "birthday": bday, "points": 0, "visits": 0, "created_at": old})

    bd = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "birthday"][0]
    check(f"a new birthday automation: offer valid 7 days ({bd['trigger'].get('offer_days')})", bd["trigger"].get("offer_days") == 7)
    r = http("PUT", f"/api/owner/automations/{bd['id']}", json={
        "scenario": "birthday", "status": "active", "trigger": {"offset_days": 0, "offer_days": 7},
        "message": {"title": "Joyeux anniversaire {prénom} !", "body": "Votre cadeau vous attend jusqu'au {fin_offre}.",
                    "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "hour": "10:00"}})
    check(f"saved ({r.status_code})", r.status_code == 200)
    check("the trigger reads « offre valable 7 jours »", "offre valable 7 jours" in
          [x for x in http("GET", "/api/owner/automations").json()["rows"] if x["id"] == bd["id"]][0]["trigger_text"])
    db.automation_meta.update_one({"_id": "tick"}, {"$set": {"at": dt.datetime(2026, 10, 20, 6, 0, tzinfo=UTC)}}, upsert=True)

    def bday_sent():
        return [p["cid"] for p in pushed if p["kind"] == "birthday"]

    # Tuesday 20 Oct 2026, Paris = UTC+2
    AU.run_due(dt.datetime(2026, 10, 20, 8, 0, tzinfo=UTC), source="tick")       # 10:00
    check(f"10:00: today's birthday is greeted ({bday_sent()})", bday_sent() == ["c_early"])
    check(f"…with its offer's last day ({pushed[-1]['body']})", "26 octobre" in pushed[-1]["body"])
    news = AU.latest_for(db.customers.find_one({"id": "c_early"}), dt.datetime(2026, 10, 21, 8, 0, tzinfo=UTC))
    check(f"the Wallet card says how long ({news and news.get('until_label')})",
          news and news.get("until_label") == "Offre valable jusqu'au 26 octobre")
    check("…and drops it once the offer is over",
          AU.latest_for(db.customers.find_one({"id": "c_early"}), dt.datetime(2026, 10, 27, 8, 0, tzinfo=UTC)) is None)

    # 13:00: a birthday saved as today, after the round
    db.customers.update_one({"id": "c_late"}, {"$set": {"birthday": "10-20"}})
    AU.run_due(dt.datetime(2026, 10, 20, 11, 0, tzinfo=UTC), source="tick")      # 13:00
    check(f"13:00: a birthday saved after 10:00 is greeted the same day ({bday_sent()})", bday_sent() == ["c_early", "c_late"])
    AU.run_due(dt.datetime(2026, 10, 20, 11, 15, tzinfo=UTC), source="tick")
    check("…once", bday_sent().count("c_late") == 1)

    # 15:00: a card added today with today's birthday waits an hour
    db.customers.update_one({"id": "c_new"}, {"$set": {"birthday": "10-20",
                                                       "created_at": dt.datetime(2026, 10, 20, 13, 0, tzinfo=UTC)}})
    AU.run_due(dt.datetime(2026, 10, 20, 13, 30, tzinfo=UTC), source="tick")     # 15:30, 30 min after the card
    check("a card added 30 min ago: not yet (« Bienvenue » first)", "c_new" not in bday_sent())
    AU.run_due(dt.datetime(2026, 10, 20, 14, 0, tzinfo=UTC), source="tick")      # 16:00, one hour after
    check("…an hour after the card, it goes", "c_new" in bday_sent())

    # after 20:00: the next morning
    db.customers.insert_one({"id": "c_night", "tenant_id": "t1", "name": "Nuit", "barcode_id": "FT-NIGHT",
                             "birthday": "10-20", "points": 0, "visits": 0, "created_at": old})
    AU.run_due(dt.datetime(2026, 10, 20, 18, 30, tzinfo=UTC), source="tick")     # 20:30
    check("20:30: too late today", "c_night" not in bday_sent())
    AU.run_due(dt.datetime(2026, 10, 21, 8, 0, tzinfo=UTC), source="tick")       # tomorrow 10:00
    check("…greeted the next morning", "c_night" in bday_sent())
    check("…and nobody greeted twice", len(bday_sent()) == len(set(bday_sent())))

    # the offer's length decides how late a missed greeting may still go
    http("PUT", f"/api/owner/automations/{bd['id']}", json={
        "scenario": "birthday", "status": "active", "trigger": {"offset_days": 0, "offer_days": 3},
        "message": {"title": "Joyeux anniversaire {prénom} !", "body": "Jusqu'au {fin_offre}.", "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "hour": "10:00"}})
    check("the business sets 3 days", [x for x in http("GET", "/api/owner/automations").json()["rows"]
                                        if x["id"] == bd["id"]][0]["trigger"]["offer_days"] == 3)
    for cid, bday in (("c_2ago", "10-20"), ("c_5ago", "10-17")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "barcode_id": f"FT-{cid.upper()}",
                                 "birthday": bday, "points": 0, "visits": 0, "created_at": old})
    AU.run_due(dt.datetime(2026, 10, 22, 8, 0, tzinfo=UTC), source="tick")       # Thu 22, 10:00
    check("2 days after the birthday, within 3 days: still greeted", "c_2ago" in bday_sent())
    check(f"…with « 22 octobre » as the last day ({pushed[-1]['body']})", "22 octobre" in pushed[-1]["body"])
    check("5 days after, the 3-day offer is over: not sent", "c_5ago" not in bday_sent())
    r = http("PUT", f"/api/owner/automations/{bd['id']}", json={
        "scenario": "birthday", "status": "active", "trigger": {"offset_days": 0, "offer_days": 0},
        "message": {"title": "x", "body": "y", "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "hour": "10:00"}})
    check(f"0 days is refused ({r.status_code})", r.status_code == 400)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
