"""
The business chooses the interval, automation by automation (user, 2026-11-04:
« ek baar unko gaya, toh fir next us fixed days k interval k baad hi jaaye »).
X is the business's own number; 20 and 13 below are just examples.

Géolocalisation, Avis Google, Relance, Palier and every Personnalisée. Parrainage,
Anniversaire, Bienvenue and Proche récompense keep their own rule (not touched).

Géolocalisation (user): as soon as FidClic sends the message the client's Wallet
pass loses the shop's location for X days, then gets it back. A lock-screen
message is shown by the phone, which tells nobody: only what FidClic sent starts
the interval.

Run: cd api && python3 tests/test_automation_frequency.py
"""
import asyncio
import datetime as dt
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automation-frequency")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:300]}"))


def main():
    import server
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import automations as AU
    from features import custom_rules as CR
    from features import geo_automation as GA
    from features import temoin as T

    db = server.db
    T.enabled = lambda tid: False
    woken = []
    WP.notify_passes = lambda serials, *a, **k: woken.extend(serials) or {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    server.dispatch_to_customer = lambda *a, **k: {"sent": True}
    GA.fetch_weather = lambda lat, lng: {"code": 0, "temp": 18.0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=H if headers is None else headers, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    SHOP = (47.3941, 0.6848)
    FAR = (47.5000, 0.9000)                   # a custom address, far from the shop
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "geo_enabled": True, "geo_radius_meters": 200,
                           "lat": SHOP[0], "lng": SHOP[1], "google_reviews_enabled": True,
                           "google_review_url": "https://g.page/r/x"})
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})

    def person(cid, **kw):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid.title(), "barcode_id": f"FT-{cid.upper()}",
                                 "points": 0, "visits": 2, "consent": {"accepted": True}, "geo_consent": True,
                                 "created_at": now - dt.timedelta(days=300),
                                 "last_visit_date": now - dt.timedelta(days=200), **kw})
        db.pass_registrations.insert_one({"tenant_id": "t1", "serial": f"FT-{cid.upper()}", "device": cid})
        return cid

    def cust(cid):
        return db.customers.find_one({"id": cid}, {"_id": 0})

    MSG = {"title": "Bonjour", "body": "Un message"}

    def save(scenario, trigger, **over):
        return http("POST", "/api/owner/automations", json={
            "scenario": scenario, "name": f"Test {scenario}", "status": "active", "trigger": trigger, "message": dict(MSG),
            "targeting": {"mode": "all", "pick": "all", "passants": "all", "filters": {}},
            "schedule": {"days": "all", "window": False, "holidays": True, "tz": "Europe/Paris", "hour": "10:00", **over}})

    def only(row_id):
        """This automation alone is live: the shop's other ones stay quiet."""
        db.automations.update_many({"tenant_id": "t1", "id": {"$ne": row_id}}, {"$set": {"status": "paused"}})
        db.automations.update_one({"id": row_id}, {"$set": {"status": "active"}})
        return db.automations.find_one({"id": row_id}, {"_id": 0})

    def age_logs(aid, cid, days):
        """As if the last message to this client went out `days` days ago."""
        db.automation_log.update_many({"automation_id": aid, "customer_id": cid},
                                      {"$set": {"sent_at": now - dt.timedelta(days=days)}})

    def ping(cid, at=SHOP):
        return http("POST", "/api/public/proximity-ping", headers={},
                    json={"customer_id": cid, "latitude": at[0], "longitude": at[1]}).json()

    http("GET", "/api/owner/automations")     # the shop's saved scenarios set up

    # ------------------------------------------------------------------
    print("\nGéolocalisation: the business types its own X")
    # ------------------------------------------------------------------
    for x in (1, 20, 120, 365):
        r = save("geo", {"cooldown_days": x, "weather": [], "stores": []})
        check(f"X = {x} is saved", r.status_code == 200 and r.json().get("trigger", {}).get("cooldown_days") == x, r.text[:160])
    for x in (0, 366):
        check(f"X = {x} is refused", save("geo", {"cooldown_days": x, "weather": [], "stores": []}).status_code == 400)

    print("\nGéolocalisation: sent, then quiet for X days, then again (X = 20)")
    geo = save("geo", {"cooldown_days": 20, "weather": [], "stores": []}).json()
    only(geo["id"])
    a = person("alice")
    GA.sync_passes(tids=["t1"])                # the location is on the phone
    woken.clear()
    check("near the shop: the card-open message goes", ping(a).get("status") == "sent")
    check("…at once the pass loses the location (no 15-minute wait)", GA.for_pass(cust(a)) is None
          and "FT-ALICE" in woken and (cust(a).get("geo_pass_key") or "off") == "off", woken)
    check("passing again the same day: nothing", ping(a).get("status") == "ignored")
    age_logs(geo["id"], a, 19)
    check("19 days later: still nothing", ping(a).get("status") == "ignored")
    check("…and still no location on the pass", GA.for_pass(cust(a)) is None)
    age_logs(geo["id"], a, 20)
    check("20 days later: the pass carries the location again", GA.for_pass(cust(a)) is not None)
    woken.clear()
    GA.sync_passes(tids=["t1"])
    check("…the tick puts it back on the phone", "FT-ALICE" in woken, woken)
    check("…and the message can go again", ping(a).get("status") == "sent")
    b = person("bruno")
    check("another client is on their own clock", ping(b).get("status") == "sent")

    # ------------------------------------------------------------------
    print("\nRelance inactifs: « Relancer régulièrement » tous les X jours")
    # ------------------------------------------------------------------
    for x in (1, 3, 45, 365):
        r = save("inactive", {"days": 30, "repeat": "every", "every_days": x})
        check(f"X = {x} is saved", r.status_code == 200 and r.json()["trigger"]["every_days"] == x, r.text[:160])
    check("X = 0 is refused", save("inactive", {"days": 30, "repeat": "every", "every_days": 0}).status_code == 400)
    ina = only(save("inactive", {"days": 30, "repeat": "every", "every_days": 3}).json()["id"])
    i = person("ines")
    due = lambda: i in [c["id"] for c in AU._inactive_due("t1", ina, now)]  # noqa: E731
    check("never told: due", due())
    db.automation_log.insert_one({"id": str(uuid.uuid4()), "tenant_id": "t1", "automation_id": ina["id"], "customer_id": i, "sent_at": now})
    check("just told: not due", not due())
    age_logs(ina["id"], i, 2)
    check("2 days later: not due (X = 3)", not due())
    age_logs(ina["id"], i, 3)
    check("3 days later: due", due())

    # ------------------------------------------------------------------
    print("\nAvis Google: au plus une fois tous les X jours")
    # ------------------------------------------------------------------
    gr = only(save("google_review", {"type": "after_visit", "frequency": "days", "every_days": 20, "delay_value": 0,
                                     "delay_unit": "hours"}).json()["id"])
    check("X = 20 is saved", gr["trigger"]["every_days"] == 20)
    g = person("gaia")
    ctx = lambda: {"event": "visit"}  # noqa: E731
    check("never asked: goes", AU._eligible("t1", gr, cust(g), ctx(), now))
    db.automation_log.insert_one({"id": str(uuid.uuid4()), "tenant_id": "t1", "automation_id": gr["id"], "customer_id": g, "sent_at": now})
    age_logs(gr["id"], g, 19)
    check("19 days later: not yet", not AU._eligible("t1", gr, cust(g), ctx(), now))
    age_logs(gr["id"], g, 20)
    check("20 days later: goes", AU._eligible("t1", gr, cust(g), ctx(), now))

    # ------------------------------------------------------------------
    print("\nPalier: au moins X jours entre deux envois")
    # ------------------------------------------------------------------
    ti = only(save("tier_up", {"condition": "visits", "threshold": 5, "repeat": "custom", "min_days": 20}).json()["id"])
    check("X = 20 is saved", ti["trigger"]["min_days"] == 20)
    t = person("theo", visits=10)
    db.automation_log.insert_one({"id": str(uuid.uuid4()), "tenant_id": "t1", "automation_id": ti["id"], "customer_id": t, "sent_at": now, "level": 5})
    age_logs(ti["id"], t, 19)
    check("a new palier 19 days later: waits", not AU._eligible("t1", ti, cust(t), {"event": "visit"}, now))
    age_logs(ti["id"], t, 20)
    check("20 days later: goes", AU._eligible("t1", ti, cust(t), {"event": "visit"}, now))

    # ------------------------------------------------------------------
    print("\nPersonnalisée: any X, on any déclencheur")
    # ------------------------------------------------------------------
    def custom(trigger, x, **sched):
        return save("custom", trigger, dedupe=True, min_gap_days=x, **sched)

    act = {"type": "action", "action": "visit", "repeat": "every", "delay_value": 0, "delay_unit": "hours"}
    for x in (1, 13, 200, 365):
        r = custom(act, x)
        check(f"X = {x} is saved", r.status_code == 200 and r.json()["schedule"]["min_gap_days"] == x, r.text[:160])
    for x in (0, 366):
        check(f"X = {x} is refused", custom(act, x).status_code == 400)
    cu = only(custom(act, 13).json()["id"])
    c = person("clara")
    db.automation_log.insert_one({"id": str(uuid.uuid4()), "tenant_id": "t1", "automation_id": cu["id"], "customer_id": c, "sent_at": now})
    age_logs(cu["id"], c, 12)
    check("12 days later: not yet (X = 13)", not CR.rules_ok(cu, cust(c), now))
    age_logs(cu["id"], c, 13)
    check("13 days later: goes", CR.rules_ok(cu, cust(c), now))

    print("\nPersonnalisée géolocalisée, loin de la boutique (X = 13)")
    cg = only(custom({"type": "geo", "address": "Gare", "lat": FAR[0], "lng": FAR[1], "radius_m": 300, "days": "all",
                      "from": "00:00", "to": "23:59", "new_only": False}, 13).json()["id"])
    d = person("dora")
    check("the pass carries the custom address", GA.for_pass(cust(d)) is not None)
    GA.sync_passes(tids=["t1"])                # the location is on the phone
    woken.clear()
    check("near it: the message goes", ping(d, FAR).get("status") == "sent")
    check("…at once the pass loses the location, even far from the shop",
          GA.for_pass(cust(d)) is None and "FT-DORA" in woken and (cust(d).get("geo_pass_key") or "off") == "off", woken)
    check("passing again: nothing", ping(d, FAR).get("status") != "sent")
    age_logs(cg["id"], d, 12)
    check("12 days later: still quiet", GA.for_pass(cust(d)) is None and ping(d, FAR).get("status") != "sent")
    age_logs(cg["id"], d, 13)
    check("13 days later: the location is back and the message can go",
          GA.for_pass(cust(d)) is not None and ping(d, FAR).get("status") == "sent")

    print("\nPentest: who, and what can be sent")
    db.users.insert_many([{"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "o2@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    db.tenants.insert_one({"id": "t2", "slug": "autre", "name": "Autre", "plan": "vip", "subscription_status": "active", "is_active": True})
    tok = lambda e, r, t: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    row = db.automations.find_one({"id": geo["id"]}, {"_id": 0})
    body = {k: row[k] for k in ("scenario", "name", "message", "targeting", "schedule")}
    body["trigger"] = {**row["trigger"], "cooldown_days": 1}
    check("staff cannot change an interval", http("PUT", f"/api/owner/automations/{geo['id']}", headers=tok("s@x.fr", "staff", "t1"),
                                                  json=body).status_code == 403)
    r = http("PUT", f"/api/owner/automations/{geo['id']}", headers=tok("o2@x.fr", "business_owner", "t2"), json=body)
    check(f"another shop's owner cannot ({r.status_code})", r.status_code in (403, 404))
    check("…the interval did not move", db.automations.find_one({"id": geo["id"]})["trigger"]["cooldown_days"] == 20)
    for bad in ("20; drop", 20.5, True, None, -5, [20], {"$gt": 0}):
        r = save("geo", {"cooldown_days": bad, "weather": [], "stores": []})
        check(f"cooldown_days={bad!r} → refused ({r.status_code})", r.status_code in (400, 422), r.text[:120])
    check("pausing and starting again does not reset a client's interval", True if (
        http("POST", f"/api/owner/automations/{geo['id']}/status", json={"status": "paused"}).status_code == 200
        and http("POST", f"/api/owner/automations/{geo['id']}/status", json={"status": "active"}).status_code == 200
        and only(geo["id"]) and db.automation_log.update_many({"automation_id": geo["id"], "customer_id": b},
                                                              {"$set": {"sent_at": now - dt.timedelta(days=5)}}) is not None
        and ping(b).get("status") == "ignored") else False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
