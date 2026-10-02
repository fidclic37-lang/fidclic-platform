"""
Autopilot — the daily and weekly campaigns FidClic IA prepares, and the owner
validates (user, 2026-10-02).

    Pro AI only; both rhythms off until switched on; owner's times and day
    the daily « bon client au bon moment » groups, each client in one group
    clients at their limit or contacted in 3 days are left out, and said so
    a day without a real group has no campaign
    nothing leaves before the owner validates; validated = sent (or, with a
      precise cron, scheduled at the owner's time); 24 h then « expirée »
    the IA never invents an offer; without a model, a template
    the bell says it; the Copilote's switch is this Autopilot
    the cron Vercel calls runs it — and the scheduled campaigns again

Run: cd api && /usr/local/bin/python3 tests/test_autopilot.py
"""
import asyncio
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from features import autopilot as AP, copilot as K

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, bearer=None, **kw):
        headers = {"Authorization": "Bearer " + bearer} if bearer else {}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    PARIS = ZoneInfo("Europe/Paris")
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(PARIS)

    db.tenants.insert_many([
        {"id": "t1", "name": "Café Lumière", "sector": "cafe", "plan": "vip", "subscription_status": "active", "created_at": now},
        {"id": "pro", "name": "Pro", "sector": "cafe", "plan": "gold", "subscription_status": "active", "created_at": now},
    ])
    db.users.insert_many([{"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@p.fr", "role": "business_owner", "tenant_id": "pro"}])
    OWN = auth.create_access_token({"sub": "o@c.fr", "role": "business_owner", "tenant_id": "t1"})
    PRO = auth.create_access_token({"sub": "o@p.fr", "role": "business_owner", "tenant_id": "pro"})
    MAN = auth.create_access_token({"sub": "m@c.fr", "role": "manager", "tenant_id": "t1"})

    def client(cid, visit_days_ago, name=None):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": name or f"Client {cid}", "barcode_id": f"FT-{cid}",
                                 "visits": len(visit_days_ago), "created_at": now - dt.timedelta(days=400),
                                 "last_visit_date": now - dt.timedelta(days=min(visit_days_ago)) if visit_days_ago else None})
        for d in visit_days_ago:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": 8.0,
                                  "visit_time": now - dt.timedelta(days=d, hours=1)})

    # en retard: every 7 days, last seen 11 days ago (1.5 × 7 = 10.5)
    for i in range(6):
        client(f"late{i}", [11, 18, 25, 32, 39])
    # their usual day is today: 5 visits, all on today's weekday, last 7 days ago
    for i in range(2):
        client(f"day{i}", [7, 14, 21, 28, 35])
    # new, a week on: one visit 8 days ago
    for i in range(3):
        client(f"new{i}", [8])
    # nobody's moment: came yesterday
    for i in range(4):
        client(f"fresh{i}", [1, 9, 17])

    print("\nThe plan")
    check("Pro (not Pro AI) does not get it", http("GET", "/api/owner/autopilot", PRO).json()["plan_ok"] is False)
    check("… and cannot switch it on", http("PUT", "/api/owner/autopilot", PRO, json={"daily": {"enabled": True}}).status_code == 403)
    g = http("GET", "/api/owner/autopilot", OWN).json()
    check("Pro AI does, both rhythms off at first", g["plan_ok"] and not g["settings"]["daily"]["enabled"] and not g["settings"]["weekly"]["enabled"])
    check("a manager reads, does not change", http("PUT", "/api/owner/autopilot", MAN, json={"daily": {"enabled": True}}).status_code == 403)

    print("\nToday's « bon client au bon moment »")
    groups = AP.daily_groups("t1", now)
    check("late regulars", set(groups["en_retard"]) == {f"late{i}" for i in range(6)}, groups)
    check("today is their usual day", set(groups["jour_habituel"]) == {"day0", "day1"}, groups)
    check("new clients a week on", set(groups["nouveaux_j7"]) == {"new0", "new1", "new2"})
    check("those who came yesterday are left alone", not any(c.startswith("fresh") for v in groups.values() for c in v))

    # two late regulars are already taken: one got a campaign yesterday, one is at its daily limit
    db.campaigns.insert_one({"id": "kprev", "tenant_id": "t1", "name": "Happy hour", "status": "sent",
                             "sent_at": now - dt.timedelta(hours=20), "recipient_ids": ["late0"]})
    db.tenants.update_one({"id": "t1"}, {"$set": {"send_rules": {"per_client_day": 1}}})
    from features import send_rules as SR
    SR.record("t1", "late1", "campaign", now)

    sent_before = db.push_notifications.count_documents({})
    r = http("PUT", "/api/owner/autopilot", OWN, json={"daily": {"enabled": True, "hour": 11, "minute": 30},
                                                      "weekly": {"enabled": False, "weekday": today.weekday(), "hour": 10}})
    check("the owner sets the daily time", r.status_code == 200 and r.json()["settings"]["daily"]["hour"] == 11)
    res = http("POST", "/api/owner/autopilot/prepare", OWN).json()
    p = res["pending"][0] if res["pending"] else {}
    check("today's campaign is prepared", res["prepared"] == 1 and p.get("kind") == "daily", res)
    check("for the largest group of the day", p.get("audience_label") == "Clients en retard sur leur habitude" and p.get("audience_count") == 4, p)
    check("the client contacted yesterday and the one at its limit are left out, and it says so",
          p.get("left_out") == {"limit": 1, "recent": 1}, p.get("left_out"))
    sa = dt.datetime.fromisoformat(p["send_at"]).astimezone(PARIS)
    check("at the owner's time today", sa.date() == today.date() and (sa.hour, sa.minute) == (11, 30))
    check("valid 24 h after", dt.datetime.fromisoformat(p["expires_at"]) - dt.datetime.fromisoformat(p["send_at"]) == dt.timedelta(hours=24))
    check("written, without a model, from a template", p["written_by"] == "modele" and "{first_name}" in p["title"])
    check("NOTHING was sent", db.push_notifications.count_documents({}) == sent_before
          and db.campaigns.count_documents({"tenant_id": "t1"}) == 1)
    check("preparing again prepares nothing twice",
          http("POST", "/api/owner/autopilot/prepare", OWN).json()["prepared"] == 0
          and db.autopilot_proposals.count_documents({"tenant_id": "t1", "kind": "daily"}) == 1)

    print("\nThe bell, and who validates")
    served = server.get_proactive_alerts(token_data=type("T", (), {"tenant_id": "t1", "role": "business_owner", "email": "o@c.fr"})(), branch_id=None)
    al = [a for a in served["alerts"] if str(a["id"]).startswith("autopilot:")]
    check("the bell says today's campaign is ready", al and "prête" in al[0]["title"]
          and al[0]["action"]["href"] == "/dashboard/automations#autopilot", al)
    check("a manager cannot validate", http("POST", f"/api/owner/autopilot/{p['id']}/approve", MAN, json={}).status_code == 403)

    print("\nValidating")
    r = http("POST", f"/api/owner/autopilot/{p['id']}/approve", OWN,
             json={"title": "{first_name}, on vous attend", "exclude_ids": ["late2"]})
    out = r.json()
    camp = db.campaigns.find_one({"id": out.get("campaign_id")}) or {}
    check("validated: sent now (daily cron)", r.status_code == 200 and out["status"] == "sent" and camp.get("status") == "sent", r.text[:200])
    check("to the proposal's clients minus the one the owner left out",
          sorted(camp.get("recipient_ids") or []) == ["late3", "late4", "late5"], camp.get("recipient_ids"))
    check("with the owner's edit", camp.get("name") == "{first_name}, on vous attend")
    check("tagged for the learning", camp.get("template") == "autopilot_daily" and camp.get("segment") == "custom"
          and camp.get("autopilot_id") == p["id"])
    check("cannot be validated twice", http("POST", f"/api/owner/autopilot/{p['id']}/approve", OWN, json={}).status_code == 409)
    check("the bell goes quiet", not AP.alerts("t1"))

    print("\nThe weekly campaign")
    for i in range(12):
        db.customers.insert_one({"id": f"old{i}", "tenant_id": "t1", "name": f"Ancien {i}", "barcode_id": f"FT-O{i}",
                                 "visits": 2, "created_at": now - dt.timedelta(days=400),
                                 "last_visit_date": now - dt.timedelta(days=120)})
    http("PUT", "/api/owner/autopilot", OWN, json={"weekly": {"enabled": True, "weekday": today.weekday(), "hour": 18, "minute": 0}})
    w = [x for x in http("POST", "/api/owner/autopilot/prepare", OWN).json()["pending"] if x["kind"] == "weekly"]
    check("prepared on its day, at the owner's time", w and dt.datetime.fromisoformat(w[0]["send_at"]).astimezone(PARIS).hour == 18, w)
    check("to the inactive clients when they are many", w and w[0]["segment"] == "inactive" and w[0]["audience_count"] >= 12, w and w[0])
    tomorrow = (today + dt.timedelta(days=1)).weekday()
    db.autopilot_proposals.delete_many({"tenant_id": "t1", "kind": "weekly"})
    http("PUT", "/api/owner/autopilot", OWN, json={"weekly": {"enabled": True, "weekday": tomorrow, "hour": 10}})
    w2 = [x for x in http("POST", "/api/owner/autopilot/prepare", OWN).json()["pending"] if x["kind"] == "weekly"]
    check("… or the day before, so the owner has time", w2 and w2[0]["for_date"] == (today + dt.timedelta(days=1)).date().isoformat())
    in3 = (today + dt.timedelta(days=3)).weekday()
    db.autopilot_proposals.delete_many({"tenant_id": "t1", "kind": "weekly"})
    http("PUT", "/api/owner/autopilot", OWN, json={"weekly": {"enabled": True, "weekday": in3, "hour": 10}})
    check("not earlier", not [x for x in http("POST", "/api/owner/autopilot/prepare", OWN).json()["pending"] if x["kind"] == "weekly"])

    print("\nValidated the day before, on the daily cron")
    db.autopilot_proposals.delete_many({"tenant_id": "t1", "kind": "weekly"})
    http("PUT", "/api/owner/autopilot", OWN, json={"weekly": {"enabled": True, "weekday": tomorrow, "hour": 18}})
    wd = [x for x in http("POST", "/api/owner/autopilot/prepare", OWN).json()["pending"] if x["kind"] == "weekly"][0]
    r = http("POST", f"/api/owner/autopilot/{wd['id']}/approve", OWN, json={}).json()
    sc = db.campaigns.find_one({"id": r["campaign_id"]})
    check("never a day early: it waits for its day's morning run", r["status"] == "scheduled"
          and AP._aware(sc["scheduled_for"]).date() == (now + dt.timedelta(days=1)).astimezone(PARIS).date()
          and AP._aware(sc["scheduled_for"]).hour == AP.MORNING_UTC, sc.get("scheduled_for"))

    print("\nThe exact time, with a cron every 15 min")
    db.autopilot_proposals.delete_many({"tenant_id": "t1", "kind": "weekly"})
    http("PUT", "/api/owner/autopilot", OWN, json={"weekly": {"enabled": True, "weekday": tomorrow, "hour": 10}})
    wp = [x for x in http("POST", "/api/owner/autopilot/prepare", OWN).json()["pending"] if x["kind"] == "weekly"][0]
    os.environ["FIDCLIC_CRON_PRECISE"] = "1"
    r = http("POST", f"/api/owner/autopilot/{wp['id']}/approve", OWN, json={}).json()
    sc = db.campaigns.find_one({"id": r["campaign_id"]})
    check("validated early: scheduled for the owner's time", r["status"] == "scheduled" and sc["status"] == "scheduled"
          and AP._aware(sc["scheduled_for"]) == dt.datetime.fromisoformat(wp["send_at"]), (r, sc.get("scheduled_for")))
    os.environ.pop("FIDCLIC_CRON_PRECISE")

    print("\n24 h, then « expirée »")
    db.autopilot_proposals.insert_one({"id": "old", "tenant_id": "t1", "kind": "daily", "for_date": "2026-01-01",
                                       "status": "pending", "title": "x", "message": "y", "customer_ids": ["new0"],
                                       "audience_count": 1, "send_at": now - dt.timedelta(hours=30),
                                       "expires_at": now - dt.timedelta(hours=6)})
    r = http("POST", "/api/owner/autopilot/old/approve", OWN, json={})
    check("too late: not sent, and said so", r.status_code == 410 and db.autopilot_proposals.find_one({"id": "old"})["status"] == "expired")
    db.autopilot_proposals.update_one({"id": "old"}, {"$set": {"status": "pending"}})
    AP.run(now)
    check("the cron expires it too", db.autopilot_proposals.find_one({"id": "old"})["status"] == "expired")

    print("\nA day with no real group")
    db.autopilot_proposals.delete_many({"tenant_id": "t1", "kind": "daily"})
    db.visits.delete_many({"tenant_id": "t1", "customer_id": {"$regex": "^(late|day|new)"}})
    made = AP.prepare("t1", now)
    d = [m for m in made if m["kind"] == "daily"][0]
    check("no campaign, and the reason", d["status"] == "empty" and "pas de campagne" in d["reasons"][0])

    print("\nThe IA never invents an offer")
    from services import llm
    llm._force_complete = None
    llm.is_configured = lambda: True
    seen = {}
    llm.complete = lambda system, user, **kw: seen.update(user=user) or "TITRE: On pense à vous\nMESSAGE: Passez nous voir, {first_name} !"
    t, m, by = AP.write("t1", "en_retard")
    check("it writes when a model is there", by == "ia" and t == "On pense à vous", (t, m, by))
    check("told not to promise anything", "N'invente aucune offre" in seen.get("user", ""))
    llm.complete = lambda system, user, **kw: "TITRE: Café offert !\nMESSAGE: -20% pour vous"
    check("an invented offer is refused: template instead", AP.write("t1", "en_retard")[2] == "modele")

    print("\nOne Autopilot")
    db.copilot_plans.insert_one({"tenant_id": "t9", "autopilot": True})
    db.tenants.insert_one({"id": "t9", "name": "Ancien", "plan": "vip", "created_at": now})
    s9 = AP.settings("t9")
    check("a shop that had the Copilote's Autopilot on keeps it on, as this one", s9["daily"]["enabled"] and s9["weekly"]["enabled"])
    check("… and the old one stops", db.copilot_plans.find_one({"tenant_id": "t9"})["autopilot"] is False)
    T = type("T", (), {"tenant_id": "t1", "role": "business_owner", "email": "o@c.fr"})
    K.set_autopilot(K.Autopilot(enabled=False), token_data=T())
    s1 = AP.settings("t1")
    check("the Copilote's switch drives this Autopilot", not s1["daily"]["enabled"] and not s1["weekly"]["enabled"])

    print("\nThe cron Vercel calls")
    os.environ["CRON_SECRET"] = "s3cret"
    from features import cron
    db.campaigns.insert_one({"id": "due", "tenant_id": "t1", "name": "Planifiée", "content": "Bonjour", "status": "scheduled",
                             "scheduled_for": now - dt.timedelta(minutes=5), "recipient_ids": ["fresh0"],
                             "channels": {"push": True, "wallet": True}})
    http("PUT", "/api/owner/autopilot", OWN, json={"daily": {"enabled": True, "hour": 9}})
    db.autopilot_proposals.delete_many({"tenant_id": "t1"})
    summary = cron.agent_daily(authorization="Bearer s3cret")
    check("agent-daily runs the loyalty side's daily pass again", "daily_triggers" in summary, summary.get("failures"))
    check("… so a scheduled campaign leaves", db.campaigns.find_one({"id": "due"})["status"] == "sent")
    check("… and the Autopilot prepares", db.autopilot_proposals.count_documents({"tenant_id": "t1"}) >= 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
