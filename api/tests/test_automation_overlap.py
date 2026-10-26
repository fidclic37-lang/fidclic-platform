"""
Two automation runs at once never message a client twice (audit 2026-10-26:
the 15-minute tick and the daily cron overlapping sent a relance twice to
780 of 1 560 clients — « aujourd'hui fait » was only marked after sending).

A run that starts while another is sending is simulated by starting it from
inside the first one's push: the overlap is then exact, not a race of luck.

Edge cases: the inactive round, a birthday caught up after the round, a
queued message (plage / limite par jour), a « Nouvelle automatisation » on a
clock, a run that fails is retried by the next tick, the real cron endpoint.

Run: cd api && /usr/local/bin/python3 tests/test_automation_overlap.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-overlap")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ.pop("CRON_SECRET", None)
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    from features import temoin as _T
    _T.enabled = lambda tid: False     # every relance counts here (test_temoin has its own)
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU

    db = server.db
    pushed = []
    hook = {"fn": None}

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "kind": kind})
        fn, hook["fn"] = hook["fn"], None
        if fn:
            fn()                                    # the second run starts mid-send
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    old = dt.datetime(2025, 1, 1, tzinfo=UTC)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "sector": "cafe"})
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10})
    for i in range(12):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "name": f"Client {i}", "barcode_id": f"FT-{i}",
                                 "points": 0, "visits": 3, "created_at": old, "last_visit_date": old})

    def twice(kind):
        sent = [p["cid"] for p in pushed if p["kind"] == kind]
        return sorted({c for c in sent if sent.count(c) > 1})

    def only(scenario):
        db.automations.update_many({"tenant_id": "t1", "scenario": {"$ne": scenario}}, {"$set": {"status": "paused"}})

    # --- 1. the inactive round: tick + daily at the same moment ----------------
    print("\n── relance des inactifs ──")
    at = dt.datetime(2026, 10, 20, 8, 5, tzinfo=UTC)                   # Tue 10:05 Paris
    inact = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                       schedule={"days": "all", "hour": "10:00"})
    db.automations.insert_one(dict(inact))
    db.automation_meta.update_one({"_id": "tick"}, {"$set": {"at": at}}, upsert=True)
    inner = {}
    hook["fn"] = lambda: inner.update(AU.run_due(at, source="daily"))
    outer = AU.run_due(at, source="tick")
    got = [p["cid"] for p in pushed if p["kind"] == "push_wallet"]
    check(f"the 12 inactive clients are told ({len(set(got))})", len(set(got)) == 12)
    check(f"…each once, though two runs overlapped (twice: {twice('push_wallet')})", not twice("push_wallet"))
    check(f"…by the run that started first ({outer.get('time_sent')} + {inner.get('time_sent')})",
          outer.get("time_sent") == 12 and inner.get("time_sent") == 0)
    check("one log row per client", db.automation_log.count_documents({"automation_id": inact["id"]}) == 12)
    check("the day is marked done", AU._aware(db.automations.find_one({"id": inact["id"]})["last_run_at"]) == at)
    check("a later tick the same day sends nothing", AU.run_due(at + dt.timedelta(minutes=15), source="tick")["time_sent"] == 0)

    # --- 2. a run that fails is retried by the next tick ------------------------
    print("\n── un run qui plante ──")
    db.automations.update_one({"id": inact["id"]}, {"$set": {"status": "paused"}})
    retry = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                       schedule={"days": "all", "hour": "10:00"})
    db.automations.insert_one(dict(retry))
    real_due, boom = AU._inactive_due, {"n": 1}

    def failing(*a, **k):
        if boom["n"]:
            boom["n"] -= 1
            raise RuntimeError("Atlas timeout")
        return real_due(*a, **k)
    AU._inactive_due = failing
    s = AU.run_due(at + dt.timedelta(minutes=30), source="tick")
    check(f"the failure is counted ({s['errors']})", s["errors"] == 1)
    check("…and the day is NOT marked done", db.automations.find_one({"id": retry["id"]}).get("last_run_at") is None)
    s = AU.run_due(at + dt.timedelta(minutes=45), source="tick")
    AU._inactive_due = real_due
    check(f"the next tick sends it ({s['time_sent']})", s["time_sent"] == 12)
    db.automations.update_one({"id": retry["id"]}, {"$set": {"status": "paused"}})

    # --- 2b. a run killed by the 60 s timeout (no exception, no cleanup) --------
    print("\n── un run tué par le timeout ──")
    pushed.clear()
    killed = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                        schedule={"days": "all", "hour": "10:00"})
    db.automations.insert_one(dict(killed))

    class Killed(BaseException):
        pass
    real_dispatch = server.dispatch_to_customer

    def dying(*a, **k):
        out = real_dispatch(*a, **k)
        if len(pushed) == 5:
            raise Killed()
        return out
    server.dispatch_to_customer = dying
    t0 = at + dt.timedelta(hours=1)
    try:
        AU.run_due(t0, source="tick")
    except Killed:
        pass
    server.dispatch_to_customer = real_dispatch
    check(f"5 clients told before the kill ({len(pushed)})", len(pushed) == 5)
    check("the day is not marked done", db.automations.find_one({"id": killed["id"]}).get("last_run_at") is None)
    check("a run 4 minutes later waits (the dead run's lease)", AU.run_due(t0 + dt.timedelta(minutes=4), source="tick")["time_sent"] == 0)
    s = AU.run_due(t0 + dt.timedelta(minutes=15), source="tick")
    check(f"the next tick tells the 7 others ({s['time_sent']})", s["time_sent"] == 7)
    check(f"…12 clients in all, each once (twice: {twice('push_wallet')})",
          len({p['cid'] for p in pushed}) == 12 and not twice("push_wallet"))
    check("…and today is marked done", AU._aware(db.automations.find_one({"id": killed["id"]})["last_run_at"]) ==
          t0 + dt.timedelta(minutes=15))
    db.automations.update_one({"id": killed["id"]}, {"$set": {"status": "paused"}})

    # --- 3. a birthday caught up after the round, two ticks at once -------------
    print("\n── anniversaire rattrapé ──")
    pushed.clear()
    bd = AU.new_doc("t1", "birthday", status="active", trigger={"offset_days": 0, "offer_days": 7},
                    schedule={"days": "all", "hour": "10:00"})
    db.automations.insert_one(dict(bd))
    AU.run_due(at, source="tick")                                     # the round: nobody's birthday
    db.customers.update_many({"id": {"$in": ["c1", "c2", "c3"]}}, {"$set": {"birthday": "10-20"}})
    later = at + dt.timedelta(hours=3)
    hook["fn"] = lambda: AU.run_due(later, source="tick")
    AU.run_due(later, source="tick")
    got = sorted(p["cid"] for p in pushed if p["kind"] == "birthday")
    check(f"the 3 late birthdays are greeted ({got})", sorted(set(got)) == ["c1", "c2", "c3"])
    check(f"…each once (twice: {twice('birthday')})", not twice("birthday"))
    db.customers.update_one({"id": "c4"}, {"$set": {"birthday": "10-20"}})
    AU.run_due(later + dt.timedelta(minutes=15), source="tick")
    check("the next tick still catches a new one", [p["cid"] for p in pushed if p["kind"] == "birthday"].count("c4") == 1)
    db.automations.update_one({"id": bd["id"]}, {"$set": {"status": "paused"}})

    # --- 4. queued messages (plage horaire / limite) ---------------------------
    print("\n── messages en file d'attente ──")
    pushed.clear()
    q_auto = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "every", "every_days": 1},
                        schedule={"days": "all", "hour": "10:00"})
    db.automations.insert_one(dict(q_auto))
    due = at + dt.timedelta(days=2)
    for i in range(5):
        db.automation_queue.insert_one({"id": f"q{i}", "tenant_id": "t1", "automation_id": q_auto["id"],
                                        "customer_id": f"c{i}", "due_at": due - dt.timedelta(minutes=5),
                                        "ctx": {"event": "date"}, "created_at": at})
    db.automations.update_one({"id": q_auto["id"]}, {"$set": {"last_run_at": due}})   # the round itself is done
    hook["fn"] = lambda: AU.run_due(due, source="tick")
    AU.run_due(due, source="tick")
    got = [p["cid"] for p in pushed if p["kind"] == "push_wallet"]
    check(f"the 5 waiting messages leave ({sorted(set(got))})", sorted(set(got)) == [f"c{i}" for i in range(5)])
    check(f"…each once (twice: {twice('push_wallet')})", not twice("push_wallet"))
    check("the queue is empty", db.automation_queue.count_documents({"automation_id": q_auto["id"]}) == 0)
    db.automations.update_one({"id": q_auto["id"]}, {"$set": {"status": "paused"}})

    # --- 5. « Nouvelle automatisation » on a clock -----------------------------
    print("\n── nouvelle automatisation récurrente ──")
    pushed.clear()
    cu = AU.new_doc("t1", "custom", status="active", name="Chaque jour", created_at=at,
                    trigger={"type": "recurring", "period": "weekly", "every_weeks": 1, "weekdays": [0, 1, 2, 3, 4, 5, 6]},
                    message={"title": "Bonjour {prénom}", "body": "À bientôt"},
                    targeting={"mode": "all", "pick": "all"},
                    schedule={"tz": "Europe/Paris", "hour": "10:00", "window": False})
    db.automations.insert_one(dict(cu))
    day3 = at + dt.timedelta(days=3)
    hook["fn"] = lambda: AU.run_due(day3, source="tick")
    AU.run_due(day3, source="tick")
    got = [p["cid"] for p in pushed if p["kind"] == "automation"]
    check(f"everyone gets it ({len(set(got))})", len(set(got)) == 12)
    check(f"…once (twice: {twice('automation')})", not twice("automation"))
    db.automations.update_one({"id": cu["id"]}, {"$set": {"status": "paused"}})

    # --- 6. through the real cron endpoints ------------------------------------
    print("\n── via /api/cron/tick ──")
    pushed.clear()
    only("none")
    live = AU.new_doc("t1", "inactive", status="active", trigger={"days": 60, "repeat": "once"},
                      schedule={"days": "all", "hour": "00:00"})
    db.automations.insert_one(dict(live))
    hook["fn"] = lambda: AU.run_due(source="daily")                    # the daily cron lands mid-tick
    r = http("POST", "/api/cron/tick")
    got = [p["cid"] for p in pushed if p["kind"] == "push_wallet"]
    check(f"the tick answers ({r.status_code})", r.status_code == 200)
    check(f"12 clients, each once ({len(got)} messages, twice: {twice('push_wallet')})", len(got) == 12 and not twice("push_wallet"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
