"""
Rapport de vos campagnes — the month's campaigns, measured (Pro AI).

    the owner picks the day; on it, last month's report is written once
    only campaigns whose 15 days are over are counted; the others are listed
      with the day their result comes
    totals, the month before, CA FidClic, best/weakest, Autopilot, advice
    a PDF; an email with the PDF when the owner keeps it on and Brevo is on
    the bell until the owner opens it; Pro AI only; the cron Vercel calls runs it

Run: cd api && /usr/local/bin/python3 tests/test_campaign_report.py
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
    from features import campaign_report as CR

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
    P = lambda y, m, d, h=12: dt.datetime(y, m, d, h, tzinfo=PARIS).astimezone(dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)

    db.tenants.insert_many([
        {"id": "t1", "name": "Café Lumière", "sector": "cafe", "plan": "vip", "subscription_status": "active", "created_at": P(2025, 1, 1)},
        {"id": "pro", "name": "Pro", "plan": "gold", "subscription_status": "active", "created_at": P(2025, 1, 1)},
    ])
    db.users.insert_many([{"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@p.fr", "role": "business_owner", "tenant_id": "pro"}])
    OWN = auth.create_access_token({"sub": "o@c.fr", "role": "business_owner", "tenant_id": "t1"})
    PRO = auth.create_access_token({"sub": "o@p.fr", "role": "business_owner", "tenant_id": "pro"})

    # Ten sleepers (no visit for a year), so « expected anyway » is ~0.
    sleepers = [f"s{i}" for i in range(10)]
    for cid in sleepers:
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "barcode_id": f"FT-{cid}",
                                 "created_at": P(2024, 1, 1), "last_visit_date": P(2025, 6, 1), "visits": 3})
    # A: 5 sept, 6 of 10 came back on the 8th — measurable on 10 oct.
    db.campaigns.insert_one({"id": "A", "tenant_id": "t1", "name": "Café offert", "content": "Votre café est offert",
                             "status": "sent", "sent_at": P(2026, 9, 5), "recipient_ids": sleepers, "segment": "inactive"})
    for cid in sleepers[:6]:
        db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": 10.0, "visit_time": P(2026, 9, 8)})
    # B: 28 sept, an Autopilot one — its 15 days end on 13 oct.
    db.campaigns.insert_one({"id": "B", "tenant_id": "t1", "name": "Merci", "content": "x", "status": "sent",
                             "template": "autopilot_weekly", "sent_at": P(2026, 9, 28), "recipient_ids": sleepers[6:]})
    # The month before: one campaign, 2 back.
    db.campaigns.insert_one({"id": "Z", "tenant_id": "t1", "name": "Août", "content": "x", "status": "sent",
                             "sent_at": P(2026, 8, 3), "recipient_ids": sleepers[:5]})
    for cid in sleepers[:2]:
        db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": 10.0, "visit_time": P(2026, 8, 6)})
    db.autopilot_proposals.insert_many([
        {"id": "p1", "tenant_id": "t1", "kind": "daily", "for_date": "2026-09-10", "status": "sent"},
        {"id": "p2", "tenant_id": "t1", "kind": "daily", "for_date": "2026-09-11", "status": "expired"},
        {"id": "p3", "tenant_id": "t1", "kind": "daily", "for_date": "2026-09-12", "status": "skipped"},
        {"id": "p4", "tenant_id": "t1", "kind": "daily", "for_date": "2026-09-13", "status": "empty"},
    ])

    print("\nThe report of a month")
    d = CR.build("t1", "2026-09", P(2026, 10, 10))
    t = d["totals"]
    check("both campaigns of the month are listed", [c["id"] for c in d["campaigns"]] == ["A", "B"])
    check("only the one whose 15 days are over is counted", t["measured"] == 1 and t["touched"] == 10 and t["came"] == 6, t)
    check("its effect: back minus expected anyway", abs(t["extra"] - (6 - t["expected"])) < 0.11 and t["extra"] > 5.5, t)
    check("the money of those back", t["revenue"] == 60.0)
    check("the other says when its result comes", d["pending"][0]["id"] == "B" and d["pending"][0]["ready_on"] == "2026-10-13")
    check("and that it is an Autopilot one", d["pending"][0]["autopilot"] is True)
    check("against the month before", d["previous"]["label"] == "août 2026" and d["previous"]["came"] == 2)
    check("the month's CA FidClic", d["fidclic_ca"] == 60.0, d["fidclic_ca"])
    check("the Autopilot's month (an empty day is not a proposal)",
          d["autopilot"] == {"prepared": 3, "sent": 1, "skipped": 1, "expired": 1}, d["autopilot"])
    check("advice for next month, in plain French", any("expiré" in a for a in d["advice"]) and any("inactifs" in a for a in d["advice"]), d["advice"])
    check("labelled in French", d["label"] == "septembre 2026")
    check("« le mieux » is a campaign that did better than expected", [r["id"] for r in d["best"]] == ["A"] and d["weakest"] == [])
    d8 = CR.build("t1", "2026-08", P(2026, 10, 10))
    check("a month whose campaign did worse is never « le mieux »",
          all(r["extra"] >= 1 for r in d8["best"]) and all(r["extra"] < 1 for r in d8["weakest"]))

    print("\nThe owner's day")
    s = http("GET", "/api/owner/campaign-reports", OWN).json()
    check("the 16th by default, email on", s["settings"] == {"day": 16, "email": True})
    check("a day past the 28th is refused", http("PUT", "/api/owner/campaign-reports/settings", OWN, json={"day": 30}).status_code == 422)
    check("before its day: not due", CR.due("t1", P(2026, 10, 10)) is None)
    check("on its day: last month's is due", CR.due("t1", P(2026, 10, 16)) == "2026-09")

    print("\nWritten once, on its day")
    sent = []
    from services import mailer
    mailer._post = lambda payload, key: sent.append(payload) or {"messageId": "m"}
    os.environ.pop("BREVO_API_KEY", None)
    r = CR.run(P(2026, 10, 16, 9))
    check("the cron writes it", r["written"] == 1 and db.campaign_reports.count_documents({"tenant_id": "t1", "month": "2026-09"}) == 1)
    check("without Brevo, no email — and it is noted", not sent and db.campaign_reports.find_one({"month": "2026-09"})["email"]["reason"] == "mailer_disabled")
    check("the next day writes nothing again", CR.run(P(2026, 10, 17, 9))["written"] == 0)
    check("Pro (not Pro AI) gets none", db.campaign_reports.count_documents({"tenant_id": "pro"}) == 0)

    print("\nThe bell, then the page")
    al = CR.alerts("t1", P(2026, 10, 16, 10))
    check("the bell says it is ready", al and "septembre 2026" in al[0]["title"]
          and al[0]["action"]["href"] == "/dashboard/campaigns/reports?month=2026-09")
    g = http("GET", "/api/owner/campaign-reports/2026-09", OWN)
    check("the page shows it", g.status_code == 200 and g.json()["data"]["label"] == "septembre 2026")
    check("opened: the bell goes quiet", CR.alerts("t1", P(2026, 10, 16, 10)) == [])
    check("Pro is shown the lock", http("GET", "/api/owner/campaign-reports/2026-09", PRO).status_code == 403
          and http("GET", "/api/owner/campaign-reports", PRO).json()["plan_ok"] is False)

    print("\nPDF and email")
    pdf = http("GET", "/api/owner/campaign-reports/2026-09/pdf", OWN)
    check("a real PDF", pdf.status_code == 200 and pdf.content[:4] == b"%PDF" and pdf.headers["content-type"] == "application/pdf")
    os.environ["BREVO_API_KEY"] = "k"
    res = CR.email("t1", db.campaign_reports.find_one({"tenant_id": "t1", "month": "2026-09"}))
    import base64
    att = sent[-1]["attachment"][0] if sent else {}
    check("emailed to the owner, PDF attached", res.get("sent") and sent[-1]["to"] == [{"email": "o@c.fr"}]
          and base64.b64decode(att.get("content", ""))[:4] == b"%PDF", res)
    http("PUT", "/api/owner/campaign-reports/settings", OWN, json={"day": 16, "email": False})
    check("the owner can turn the email off", CR.email("t1", db.campaign_reports.find_one({"month": "2026-09"}))["reason"] == "owner_off")

    print("\nOn demand")
    check("a month not over is refused", http("POST", "/api/owner/campaign-reports/generate", OWN,
          json={"month": f"{now.astimezone(PARIS).year}-{now.astimezone(PARIS).month:02d}"}).status_code == 400)
    gen = http("POST", "/api/owner/campaign-reports/generate", OWN, json={"month": "2026-09"})
    check("a past month can be written again now", gen.status_code == 200 and gen.json()["month"] == "2026-09")

    print("\nThe cron Vercel calls")
    os.environ["CRON_SECRET"] = "s"
    db.campaign_report_settings.update_one({"tenant_id": "t1"}, {"$set": {"day": 1}})
    from features import cron
    cron.agent_daily(authorization="Bearer s")
    check("agent-daily writes last month's report on its day",
          db.campaign_reports.count_documents({"tenant_id": "t1", "month": CR.previous_month(now)}) == 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
