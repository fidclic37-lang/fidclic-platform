"""
QA F19 (2026-10-09): Insights said « Vos meilleurs créneaux sont entre 11h et
13h » to a shop whose visits were all at 14:48–14:57 Paris time — it read the
UTC hour (12:48). Now: the shop's clock, and the text says what it is read
on (clock, period, number of visits); too few visits → said as general advice.

Run: cd api && /usr/local/bin/python3 tests/test_insights_paris_hours.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-insights-hours")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server  # noqa: F401  (wires the features to the database)
    import features.insights_page as IP

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime(2026, 10, 9, 16, 0, tzinfo=UTC)           # summer time: Paris = UTC+2
    db.tenants.insert_one({"id": "t1", "name": "Le Café", "plan": "vip", "subscription_status": "active"})
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "t1", "name": f"C{i}", "visits": 1} for i in range(30)])

    def visits(tid, n, utc_hour, utc_minute=50, days_back=1):
        for i in range(n):
            db.visits.insert_one({"id": f"{tid}-v{utc_hour}-{i}-{days_back}", "tenant_id": tid, "customer_id": f"c{i % 30}",
                                  "amount_paid": 10.0,
                                  "visit_time": (now - dt.timedelta(days=days_back + i % 20)).replace(hour=utc_hour, minute=utc_minute)})

    print("1. Le créneau à l'heure de Paris")
    visits("t1", 25, 12)                                        # 12:50 UTC = 14:50 Paris
    hrs = IP._hours(IP.Shop("t1", now))
    check(f"25 visits at 14:50 Paris → busiest « 14h–16h », not 12h–14h / 11h–13h ({hrs and hrs['busy']})",
          hrs and hrs["busy"] == (14, 16))
    tip = next(t for t in IP._tips(IP.Shop("t1", now)) if t["key"] == "horaires")["body"]
    check("the advice says the clock, the period and how many visits",
          "entre 14h et 16h" in tip and "heure de Paris" in tip and "25 passages" in tip and "90 derniers jours" in tip)

    print("\n2. Le jour, au calendrier de Paris")
    db.tenants.insert_one({"id": "t2", "name": "La Nuit", "plan": "vip", "subscription_status": "active"})
    # Sunday 22:30 UTC is Monday 00:30 in Paris (winter) / 00:30 in summer at 22:30 UTC too
    sundays = [dt.datetime(2026, 9, d, 22, 30, tzinfo=UTC) for d in (6, 13, 20, 27)] + [dt.datetime(2026, 10, 4, 22, 30, tzinfo=UTC)]
    n = 0
    for day in sundays:
        for _ in range(4):
            db.visits.insert_one({"id": f"t2-{n}", "tenant_id": "t2", "customer_id": "c1", "amount_paid": 5.0, "visit_time": day})
            n += 1
    for d in (1, 2, 8, 9, 15, 16, 22, 23):                     # a little on Tuesdays/Wednesdays at noon
        db.visits.insert_one({"id": f"t2-x{d}", "tenant_id": "t2", "customer_id": "c1", "amount_paid": 5.0,
                              "visit_time": dt.datetime(2026, 9, d, 10, 0, tzinfo=UTC)})
        db.visits.insert_one({"id": f"t2-y{d}", "tenant_id": "t2", "customer_id": "c1", "amount_paid": 5.0,
                              "visit_time": dt.datetime(2026, 9, d, 11, 0, tzinfo=UTC)})
    best = IP._best_weekday(IP.Shop("t2", now))
    check(f"Sunday 22:30 UTC visits count as Monday in Paris ({best and IP.WEEKDAY_FR[best['weekday']]})",
          best and best["weekday"] == 0)

    print("\n3. Pas assez de passages : un conseil général, dit comme tel")
    db.tenants.insert_one({"id": "t3", "name": "Nouveau", "plan": "vip", "subscription_status": "active"})
    visits("t3", 5, 12)
    tip = next(t for t in IP._tips(IP.Shop("t3", now)) if t["key"] == "horaires")["body"]
    check("« Conseil général », with the threshold, no invented créneau",
          tip.startswith("Conseil général") and "20 sur 90 jours" in tip and "entre" not in tip)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
