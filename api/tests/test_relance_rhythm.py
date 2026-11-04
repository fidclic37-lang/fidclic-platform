"""
« Client inactif » listens to the client brain (user, 2026-11-04: « jo apne
rhythm pe hain, unhe mat bhejo ») and fires on the same day as the shop's
« inactif » chip (a rule of 35 days: both from 36 full days).

A monthly-and-a-bit client is not lost at day 36: the brain says « À l'heure »
until their window ends, so no offer goes out — when they pass it, the relance
goes by itself. The owner can switch this off, per automation.

Run: cd api && /usr/local/bin/python3 tests/test_relance_rhythm.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-relance-rhythm")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra != "" and not cond else ""))


def main():
    import server
    from features import temoin as _T
    _T.enabled = lambda tid: False
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU
    from features import client_brain as CB
    from features import clients_page as CP

    db = server.db
    pushed = []

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append(cust.get("id"))
        return {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    ago = lambda **kw: now - dt.timedelta(**kw)   # noqa: E731
    db.tenants.insert_many([{"id": t, "slug": t, "name": t.upper(), "plan": "vip", "subscription_status": "active", "is_active": True}
                            for t in ("t1", "t2")])
    db.users.insert_many([{"email": f"o@{t}.fr", "role": "business_owner", "tenant_id": t} for t in ("t1", "t2")])
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def brain(last, gap=40.0, spread=3.0, n=6):
        return {"v": CB.VERSION, "model": 1, "visits_n": n, "n_gaps": n - 1, "last": last, "first": ago(days=300),
                "gap_days": gap, "spread_days": spread, "days_n": n}

    def person(cid, days_away, b=None, t="t1", **kw):
        last = ago(days=days_away)
        db.customers.insert_one({"id": cid, "tenant_id": t, "name": cid, "barcode_id": f"FT-{cid}", "visits": 6,
                                 "created_at": ago(days=400), "last_visit_date": last,
                                 **({"brain": b(last)} if b else {}), **kw})

    print("\nThe boundary: chip and relance on the same day")
    days35 = dt.timedelta(days=35)
    check("35 days exactly → not yet lapsed", not CP.lapsed(now - days35, now, 35))
    check("35 days 23 h → not yet", not CP.lapsed(now - days35 - dt.timedelta(hours=23), now, 35))
    check("36 full days → lapsed", CP.lapsed(now - dt.timedelta(days=36), now, 35))
    check("a future date → not lapsed", not CP.lapsed(now + dt.timedelta(days=2), now, 35))
    check("no date → lapsed", CP.lapsed(None, now, 35))
    person("edge35", 35)
    person("edge36", 36)
    row = {"id": "r", "tenant_id": "t1", "scenario": "inactive", "trigger": {"days": 35, "repeat": "once"}}
    rules = [{"key": "actif", "conditions": [{"value": 35}]}]
    for cid, away in (("edge35", 35), ("edge36", 36)):
        c = db.customers.find_one({"id": cid})
        due = cid in [x["id"] for x in AU._inactive_due("t1", row, now)]
        check(f"{away} days: the relance and the chip agree ({due})", due == CP.is_inactive(c, now, rules))

    print("\nThe switch: on by default")
    on_time = lambda last: brain(last, gap=40, spread=3)      # noqa: E731
    person("habit38", 38, on_time)                           # within 40 ± 3
    person("late50", 50, on_time)                            # past the window
    person("lost120", 120, on_time)                          # décroche
    person("nobrain", 50)                                    # no brain yet
    person("toosoon", 50, lambda last: {"v": CB.VERSION, "visits_n": 2, "n_gaps": 1, "last": last, "gap_days": 40, "days_n": 2})
    person("weekly", 50, lambda last: brain(last, gap=7, spread=1))
    ids = lambda r: {x["id"] for x in AU._inactive_due("t1", r, now)}     # noqa: E731
    got = ids(row)
    check("on their rhythm → no message", "habit38" not in got, got)
    check("past their window → message", "late50" in got, got)
    check("décroche → message", "lost120" in got, got)
    check("no brain → message, as before", "nobrain" in got, got)
    check("too early to know → message, as before", "toosoon" in got, got)
    check("a weekly client 50 days away → message", "weekly" in got, got)
    off = {**row, "trigger": {**row["trigger"], "respect_rhythm": False}}
    check("switch off → the on-rhythm client gets it too", "habit38" in ids(off), ids(off))
    on = {**row, "trigger": {**row["trigger"], "respect_rhythm": True}}
    check("switch on, said outright → same as the default", ids(on) == got)
    check("another shop's clients are not read", not (ids(row) & {"x"}))
    db.customers.update_one({"id": "habit38"}, {"$set": {"brain": {"v": "junk"}}})
    check("a broken brain never blocks → message", "habit38" in ids(row))
    db.customers.update_one({"id": "habit38"}, {"$set": {"brain": on_time(ago(days=38))}})

    print("\nOnce they pass their window, the relance goes by itself")
    later = now + dt.timedelta(days=8)                        # 46 days away: window ended at 43
    check("8 days later the same client is due", "habit38" in {x["id"] for x in AU._inactive_due("t1", row, later)})

    print("\nThrough the real endpoints")
    base = {"scenario": "inactive", "name": "Relance 35", "status": "active",
            "trigger": {"days": 35, "repeat": "once"},
            "message": {"title": "On vous attend", "body": "Revenez nous voir !"},
            "targeting": {"mode": "all", "filters": {}}, "schedule": {"days": "all", "hour": "10:00"}}
    r = http("POST", "/api/owner/automations", json=base)
    check(f"created ({r.status_code})", r.status_code in (200, 201), r.text[:200])
    aid = r.json().get("id") or (r.json().get("row") or {}).get("id")
    saved = db.automations.find_one({"id": aid})
    check("saved with the switch on when not said", (saved["trigger"] or {}).get("respect_rhythm") is True, saved.get("trigger"))
    r = http("PUT", f"/api/owner/automations/{aid}", json={**base, "trigger": {**base["trigger"], "respect_rhythm": False}})
    check("saved off when the owner says so", db.automations.find_one({"id": aid})["trigger"].get("respect_rhythm") is False, r.text[:160])
    r = http("PUT", f"/api/owner/automations/{aid}", json={**base, "trigger": {**base["trigger"], "respect_rhythm": "nope"}})
    check("junk reads as on", db.automations.find_one({"id": aid})["trigger"].get("respect_rhythm") is True)
    check("the default trigger has it on", AU.new_doc("t1", "inactive")["trigger"].get("respect_rhythm") is True)
    for x in db.automations.find({"tenant_id": "t1", "scenario": "inactive", "id": {"$ne": aid}}):
        db.automations.update_one({"id": x["id"]}, {"$set": {"status": "paused"}})
    pv = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": {"mode": "all", "filters": {}},
                                                               "trigger": {"days": 35}}).json()["inactive"]
    check(f"preview says how many are held back ({pv.get('on_rhythm')})", pv.get("on_rhythm") == 1, pv)
    pv0 = http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": {"mode": "all", "filters": {}},
                                                                "trigger": {"days": 35, "respect_rhythm": False}}).json()["inactive"]
    check("…and counts them when off", pv0.get("on_rhythm") == 0 and pv0["count"] == pv["count"] + 1, (pv0.get("count"), pv["count"]))
    pushed.clear()
    db.automations.update_one({"id": aid}, {"$set": {"last_run_at": None}})
    AU.run_due(now, source="daily")
    check("the run does not message the on-rhythm client", "habit38" not in pushed and "late50" in pushed, pushed)
    check("no « told » row for the held client, so it can go later",
          db.automation_log.count_documents({"customer_id": "habit38"}) == 0)
    check("the old automation without the field behaves as on",
          "habit38" not in ids({"id": "old", "tenant_id": "t1", "scenario": "inactive", "trigger": {"days": 35}}))

    print("\nQueued, then came back on time: nothing to say (same boundary)")
    q = {"id": "q1", "tenant_id": "t1", "automation_id": aid, "customer_id": "edge35", "due_at": ago(minutes=1), "ctx": {}}
    db.automation_queue.insert_one(q)
    pushed.clear()
    db.automations.update_one({"id": aid}, {"$set": {"last_run_at": now}})
    AU.run_due(now, source="daily")
    check("35 days exactly, in the queue → not sent", "edge35" not in pushed, pushed)


main()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
