"""
Automatisations on the shop's clock, at their time (2026-10-09):
  • « Plage horaire », birthday, « date » and « date spécifique » read the
    day and the hour in Paris, not UTC (11h–13h ran 2 hours late; a date
    near midnight landed on the wrong day);
  • a 15-minute tick (/api/cron/tick, vercel.json) sends planned campaigns at
    their time — the daily run sent an 18:30 campaign the next morning — and
    runs a « Plage horaire » once a day when its window opens.

Run: cd api && /usr/local/bin/python3 tests/test_automations_paris.py
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automations-paris")
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
    import features.push_wallet as PW
    import features.campaigns_page as CPG

    db = server.db
    UTC = dt.timezone.utc
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.customers.insert_many([
        {"id": "a", "tenant_id": "t1", "name": "Anna", "barcode_id": "FT-A", "birthday": "10-14"},
        {"id": "b", "tenant_id": "t1", "name": "Bob", "barcode_id": "FT-B", "birthday": "10-13"},
    ])

    def scen(trigger, config, sid):
        db.push_scenarios.insert_one({"id": sid, "tenant_id": "t1", "name": sid, "trigger": trigger, "config": config,
                                      "enabled": True, "title": "t", "body": "b"})
        return db.push_scenarios.find_one({"id": sid}, {"_id": 0})

    print("1. Le jour et l'heure de Paris")
    # 13 Oct 2026 22:30 UTC = 14 Oct 00:30 in Paris (summer time, UTC+2)
    night = dt.datetime(2026, 10, 13, 22, 30, tzinfo=UTC)
    who = {c["id"] for c in PW._audience("t1", scen("birthday", {}, "bday"), night)}
    check("at 00:30 Paris on the 14th, the birthday of the 14th is today (not the 13th)", who == {"a"})
    check("« date spécifique » 2026-10-14 is today at 00:30 Paris",
          PW._audience("t1", scen("specific_date", {"date": "2026-10-14"}, "spec"), night))
    check("« le 14 du mois » too", PW._audience("t1", scen("date_event", {"day_of_month": 14}, "dom"), night))
    slot = scen("time_slot", {"weekdays": [], "from_hour": 11, "to_hour": 13}, "slot")
    at_1130_paris = dt.datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    at_1130_utc = dt.datetime(2026, 10, 14, 11, 30, tzinfo=UTC)          # 13:30 in Paris
    check("« 11h–13h » is open at 11:30 Paris (09:30 UTC)", PW._audience("t1", slot, at_1130_paris))
    check("…and closed at 13:30 Paris, even though it is 11:30 UTC", not PW._audience("t1", slot, at_1130_utc))
    winter = dt.datetime(2026, 12, 14, 10, 30, tzinfo=UTC)                # 11:30 Paris in winter (UTC+1)
    check("winter time: 10:30 UTC is 11:30 Paris, open", PW._audience("t1", slot, winter))
    for sid in ("bday", "spec", "dom"):
        db.push_scenarios.delete_one({"id": sid})

    print("\n2. Le tick toutes les 15 minutes : la plage horaire")
    r = server.tick_pass(dt.datetime(2026, 10, 14, 8, 45, tzinfo=UTC))              # 10:45 Paris
    check("10:45 Paris: not yet", db.push_wallet_pending.count_documents({"scenario_id": "slot"}) == 0)
    server.tick_pass(at_1130_paris)
    check("11:30 Paris: the window opens, the batch is prepared",
          db.push_wallet_pending.count_documents({"scenario_id": "slot"}) == 1)
    server.tick_pass(at_1130_paris + dt.timedelta(minutes=15))
    server.tick_pass(at_1130_paris + dt.timedelta(minutes=30))
    check("the next ticks in the window do nothing: once a day",
          db.push_wallet_pending.count_documents({"scenario_id": "slot"}) == 1)
    server.tick_pass(at_1130_paris + dt.timedelta(days=1))
    check("the next day it opens again", db.push_wallet_pending.count_documents({"scenario_id": "slot"}) == 2)

    print("\n3. Le tick : une campagne planifiée part à son heure")
    planned = dt.datetime(2026, 10, 14, 16, 30, tzinfo=UTC)                        # 18:30 Paris
    db.campaigns.insert_one({"id": "camp", "tenant_id": "t1", "name": "Ce soir", "content": "…", "status": "scheduled",
                             "scheduled_for": planned, "recipient_ids": ["a", "b"],
                             "channels": {"push": False, "wallet": False}})
    server.tick_pass(planned - dt.timedelta(minutes=10))
    check("18:20 Paris: still planned", db.campaigns.find_one({"id": "camp"})["status"] == "scheduled")
    r = server.tick_pass(planned + dt.timedelta(minutes=5))
    check(f"18:35 Paris: sent — not tomorrow morning ({r.get('campaigns')})",
          db.campaigns.find_one({"id": "camp"})["status"] == "sent")
    r = server.tick_pass(planned + dt.timedelta(minutes=20))
    check("a later tick does not send it again", (r.get("campaigns") or {}).get("sent") == 0)

    print("\n4. La configuration")
    crons = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "vercel.json")))["crons"]
    check("vercel.json calls /api/cron/tick every 15 minutes",
          {"path": "/api/cron/tick", "schedule": "*/15 * * * *"} in crons)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
