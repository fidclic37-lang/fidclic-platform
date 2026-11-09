"""
A birthday is a date in France, not in UTC (found 2026-11-09, PR #454).

Every « whose birthday is it? » read the day from UTC: « Envoyer maintenant »,
the « Anniversaire aujourd'hui » audience, the daily preparation, the
Campagnes « cette semaine » list and Insights' 30 days. From 00:00 to 01:00 in
Paris (02:00 in summer) UTC is still yesterday: the button looked for
yesterday's birthdays and missed today's.

Each entry point is read at 00:30 Paris on the 1st, winter and summer, and at
noon (where UTC and Paris agree) so the fix is not just « one day later ».

Run: cd api && python3 tests/test_birthday_paris_day.py
"""
import asyncio
import datetime as dt
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-birthday-paris-day")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail}"))


UTC = dt.timezone.utc
# (the instant, the Paris day it is, the UTC day it is)
MOMENTS = [
    (dt.datetime(2026, 11, 30, 23, 30, tzinfo=UTC), "12-01", "11-30"),    # winter: Paris = UTC+1
    (dt.datetime(2027, 6, 30, 22, 30, tzinfo=UTC), "07-01", "06-30"),     # summer: Paris = UTC+2
    (dt.datetime(2026, 11, 15, 12, 0, tzinfo=UTC), "11-15", "11-15"),     # noon: both agree
]


def main():
    import server
    import auth
    import httpx
    from features import automations as AU
    from features import auto_campaigns as AC
    from features import campaigns_page as CP
    from features import insights_page as IP

    db = server.db

    def http(method, url, headers, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    print("Le jour de Paris, en un seul endroit")
    for at, paris, utc in MOMENTS:
        check(f"{at:%Y-%m-%d %H:%M} UTC is {paris} in Paris", AU.paris_mmdd(at) == paris, AU.paris_mmdd(at))
    check("…and 6 days later from there", AU.paris_mmdd(MOMENTS[0][0], days=6) == "12-07")

    for n, (at, paris, utc) in enumerate(MOMENTS):
        print(f"\n{at:%Y-%m-%d %H:%M} UTC — {paris} in Paris")
        tid = f"t{n}"
        db.tenants.insert_one({"id": tid, "slug": tid, "name": f"Shop {n}", "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})
        db.card_templates.insert_one({"tenant_id": tid, "reward_threshold_stamps": 10, "reward_description": "Un café"})
        H = {"Authorization": "Bearer " + auth.create_access_token(
            {"sub": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid})}
        people = [{"id": f"{tid}-today", "birthday": paris}]
        if utc != paris:
            people.append({"id": f"{tid}-utc", "birthday": utc})
        for p in people:
            db.customers.insert_one({**p, "tenant_id": tid, "name": "Léa Martin", "barcode_id": f"FT-{p['id'].upper()}",
                                     "points": 0, "visits": 3, "phone": "0611111111",
                                     "created_at": at - dt.timedelta(days=200),
                                     "last_visit_date": at - dt.timedelta(days=2)})
        AU.migrate(tid)
        db.automations.update_many({"tenant_id": tid}, {"$set": {"status": "paused"}})
        db.automations.update_many({"tenant_id": tid, "scenario": "birthday"}, {"$set": {"status": "active"}})

        # « Envoyer maintenant » — dry run lists who it would reach
        AC._now = lambda at=at: at
        r = http("POST", "/api/owner/auto-campaigns/run-birthdays?dry_run=true", H)
        ids = {p.get("customer_id") or p.get("id") for p in (r.json().get("preview") or [])}
        check(f"« Envoyer maintenant » finds the Paris birthday ({ids})", f"{tid}-today" in ids and f"{tid}-utc" not in ids,
              r.json())

        # the campaigns' « Anniversaire aujourd'hui » audience
        got = {c["id"] for c in server._resolve_segment(tid, {"type": "birthday_today"}, now=at)}
        check(f"audience « anniversaire aujourd'hui » = the Paris day ({got})", got == {f"{tid}-today"})

        # the automation that sends them (its window also catches up the days
        # before, while the offer runs — so only « today's is in » is asked)
        row = db.automations.find_one({"tenant_id": tid, "scenario": "birthday"}, {"_id": 0})
        got = {c["id"] for c in AU._birthday_due(tid, row, at)}
        check(f"the birthday automation reaches the Paris birthday ({got})", f"{tid}-today" in got)

        # Campagnes « cette semaine »: today (Paris) first, never yesterday
        week = CP._birthday_window(at)
        check(f"« cette semaine » starts on {paris}", week[0] == paris and utc == paris or utc not in week, week)

        # Insights: the next 30 days
        shop = SimpleNamespace(at=at, people=[{"id": "a", "birthday": f"1990-{paris}"}, {"id": "b", "birthday": f"1990-{utc}"}])
        got = {c["id"] for c in IP._birthdays(shop)}
        check(f"Insights' 30 days start on the Paris day ({got})", got == ({"a"} if utc != paris else {"a", "b"}))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
