"""
« Ce qui marche chez vous » — learning from the campaigns a shop sends.

    a message is taken apart the same way every time (offer, urgency, emoji,
      prénom, length, question, image, link, day, moment, audience)
    a campaign's effect is the clients who came back minus those who would
      have come anyway — regulars sent a message do not make it « work »
    a learning is stated only with enough campaigns on each side and a
      difference chance explains badly; otherwise nothing is claimed
    a mature campaign is measured once, and the sector pool holds no client
    a new shop gets its sector's learnings (3 shops at least), its own first
    the composer's tips, the IA's brief and the campaign's result read them
    nothing is ever sent by any of this; Starter does not get it

Run: cd api && /usr/local/bin/python3 tests/test_campaign_learning.py
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
    from features import campaign_learning as CL

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

    def paris(days_ago, hour, weekday=None):
        t = (now.astimezone(PARIS) - dt.timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if weekday is not None:
            t -= dt.timedelta(days=(t.weekday() - weekday) % 7)
        return t.astimezone(dt.timezone.utc)

    # ---- traits ----------------------------------------------------------------
    print("\nTaking a message apart")
    T = CL.traits_of
    check("« offert » is a gift", T("Café offert", "Ce week-end")["offer"] == "cadeau")
    check("« -20% » is a discount", T("Promo", "-20% sur tout")["offer"] == "remise")
    check("« 50 points offerts » is points, not a gift", T("Bonus", "50 points offerts à votre visite")["offer"] == "points")
    check("« nouveauté » is news", T("Nouveau", "Découvrez notre nouvelle carte")["offer"] == "nouveaute")
    check("« soirée dégustation » is an event", T("Ce jeudi", "Soirée dégustation")["offer"] == "evenement")
    check("nothing is « sans offre »", T("Bonjour", "On pense à vous")["offer"] == "aucune")
    check("« ce week-end » is urgency", T("Café offert", "Ce week-end seulement")["urgency"] == "oui")
    check("an emoji is seen", T("☕ Pause", "x")["emoji"] == "oui" and T("Pause", "x")["emoji"] == "non")
    check("{first_name} is the client's prénom", T("Salut {first_name}", "x")["prenom"] == "oui")
    check("length: under 80 is short", T("t", "court")["length"] == "court" and T("t", "x" * 90)["length"] == "long")
    check("a question", T("Envie d'un café ?", "x")["question"] == "oui")
    sat = paris(3, 18, weekday=5)
    tr = T("t", "m", when=sat, segment="inactive", image=True)
    check("the day and the moment are the shop's (Paris)", tr["day"] == "sam" and tr["week"] == "weekend" and tr["slot"] == "soir")
    check("the audience and the image", tr["audience"] == "inactive" and tr["image"] == "oui")

    # ---- shops ----------------------------------------------------------------
    db.tenants.insert_many([
        {"id": "t1", "name": "Café A", "sector": "cafe", "plan": "gold", "subscription_status": "active", "created_at": now},
        {"id": "t9", "name": "Starter", "sector": "cafe", "plan": "silver", "subscription_status": "active", "created_at": now},
    ])
    OWN = auth.create_access_token({"sub": "o@a.fr", "role": "business_owner", "tenant_id": "t1"})
    STARTER = auth.create_access_token({"sub": "o@s.fr", "role": "business_owner", "tenant_id": "t9"})
    db.users.insert_many([{"email": "o@a.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@s.fr", "role": "business_owner", "tenant_id": "t9"}])

    seq = [0]

    def clients(tid, n, regular=False):
        out = []
        for _ in range(n):
            seq[0] += 1
            cid = f"{tid}-c{seq[0]}"
            db.customers.insert_one({"id": cid, "tenant_id": tid, "name": f"Client {seq[0]}",
                                     "created_at": now - dt.timedelta(days=400)})
            if regular:     # 12 visits in the 180 days before 40 days ago
                db.visits.insert_many([{"tenant_id": tid, "customer_id": cid, "amount_paid": 5.0,
                                        "visit_time": now - dt.timedelta(days=45 + 14 * k)} for k in range(12)])
            out.append(cid)
        return out

    def campaign(tid, cid_list, title, message, sent, came, amount=10.0, **extra):
        seq[0] += 1
        kid = f"k{seq[0]}"
        db.campaigns.insert_one({"id": kid, "tenant_id": tid, "name": title, "content": message, "status": "sent",
                                 "segment": extra.pop("segment", "all"), "sent_at": sent,
                                 "recipient_ids": cid_list, **extra})
        for cid in cid_list[:came]:
            db.visits.insert_one({"tenant_id": tid, "customer_id": cid, "amount_paid": amount,
                                  "visit_time": sent + dt.timedelta(days=3)})
        return kid

    # ---- measuring one campaign ----------------------------------------------------
    print("\nWhat a campaign did")
    regs = clients("t1", 30, regular=True)
    k_reg = campaign("t1", regs, "Merci", "À bientôt", now - dt.timedelta(days=40), came=20)
    m = CL.measure("t1", db.campaigns.find_one({"id": k_reg}))
    p = 1 - __import__("math").exp(-(12 / 180) * 15)
    check("expected = each regular's own chance of coming anyway", abs(m["expected"] - 30 * p) < 0.05, m)
    check("so 20 regulars back is not a triumph", abs(m["effect"] - (20 - 30 * p) / 30) < 0.002 and m["effect"] < 0.1, m)
    check("its money", m["revenue"] == 200.0 and m["came"] == 20 and m["mature"] is True)
    young = campaign("t1", clients("t1", 10), "Jeune", "x", now - dt.timedelta(days=4), came=2)
    my = CL.measure("t1", db.campaigns.find_one({"id": young}))
    check("a campaign of 4 days is not mature yet, and says so", my["mature"] is False and my["day"] == 4)

    # ---- learning ---------------------------------------------------------------
    print("\nWhat works — and only when it holds up")
    sleepers = lambda: clients("t1", 30)
    for i in range(2):
        campaign("t1", sleepers(), "☕ Café offert", "Votre café est offert cette semaine", now - dt.timedelta(days=20 + i), came=18)
        campaign("t1", sleepers(), "Promo", "-20% sur votre prochaine visite", now - dt.timedelta(days=25 + i), came=4)
    L = CL.learnings("t1")
    check("two campaigns a side: nothing is claimed", not any(f["dimension"] == "offer" for f in L["learnings"]), L["learnings"][:1])
    for i in range(2):
        campaign("t1", sleepers(), "☕ Café offert", "Votre café est offert ce mois-ci", now - dt.timedelta(days=30 + i), came=17)
        campaign("t1", sleepers(), "Promo", "-15% pour vous", now - dt.timedelta(days=33 + i), came=5)
    L = CL.learnings("t1")
    offer = {f["value"]: f for f in L["learnings"] if f["dimension"] == "offer"}
    check("four a side: a gift works better here, and it is solid",
          "cadeau" in offer and offer["cadeau"]["better"] and offer["cadeau"]["confidence"] == "solide", offer.get("cadeau"))
    check("a discount works less well here", "remise" in offer and not offer["remise"]["better"])
    check("said in plain French, per 100 clients",
          "pour 100 touchés" in offer["cadeau"]["sentence"] and "chez vous" in offer["cadeau"]["sentence"], offer["cadeau"]["sentence"])
    check("young campaigns teach nothing yet", L["campaigns_measured"] == 9)
    check("the method is written out for the merchant", "6 derniers mois" in L["method"])

    print("\nMeasured once")
    n_out = db.campaign_outcomes.count_documents({"tenant_id": "t1"})
    CL.learnings("t1")
    check("asking again measures nothing twice", db.campaign_outcomes.count_documents({"tenant_id": "t1"}) == n_out == 9)
    row = db.campaign_outcomes.find_one({"tenant_id": "t1"}, {"_id": 0})
    check("the pooled row holds no client, no name", set(row) == {"campaign_id", "tenant_id", "sector", "traits", "n", "came",
                                                                  "expected", "revenue", "effect", "sent_at", "measured_at"}, sorted(row))
    check("a young campaign is not stored", db.campaign_outcomes.count_documents({"campaign_id": young}) == 0)

    # ---- sector ---------------------------------------------------------------
    print("\nA new shop learns from its sector")
    for t in ("s1", "s2"):
        db.tenants.insert_one({"id": t, "name": t, "sector": "cafe", "plan": "gold", "created_at": now})
        for i in range(2):
            campaign(t, clients(t, 30), "Croissant offert", "Un croissant offert", now - dt.timedelta(days=20 + i), came=16)
            campaign(t, clients(t, 30), "Remise", "-10% demain", now - dt.timedelta(days=22 + i), came=4)
        CL.learnings(t)
    db.tenants.insert_one({"id": "new", "name": "Nouveau café", "sector": "cafe", "plan": "gold", "created_at": now})
    db.tenants.insert_one({"id": "bak", "name": "Boulangerie", "sector": "bakery", "plan": "gold", "created_at": now})
    Ln = CL.learnings("new")
    check("three shops of its sector: their learning is offered",
          any(f["source"] == "secteur" and f["dimension"] == "offer" and f["value"] == "cadeau" for f in Ln["learnings"]), Ln["sector_shops"])
    check("and said to come from shops like it",
          any("commerces comme le vôtre" in f["sentence"] for f in Ln["learnings"]))
    check("another sector learns nothing from cafés", CL.learnings("bak")["learnings"] == [])
    db.campaign_outcomes.delete_many({"tenant_id": "s2"})
    check("two shops are not enough", not any(f["source"] == "secteur" for f in CL.learnings("new")["learnings"]))
    for t in ("s2",):
        CL.learnings(t)                                       # measured again for the rest of the test
    check("a shop's own learning comes before its sector's",
          all(f["source"] == "vous" for f in CL.learnings("t1")["learnings"] if f["dimension"] == "offer"))

    # ---- tips, result, IA ----------------------------------------------------------------
    print("\nAdvice while writing")
    tips = http("POST", "/api/owner/campaigns/learning/tips", OWN,
                json={"title": "Promo", "message": "-20% ce samedi", "segment": "all"}).json()
    kinds = {t["kind"]: t for t in tips["tips"]}
    check("a discount gets a warning", "warn" in kinds and "Une remise" in kinds["warn"]["text"], tips["tips"])
    check("and the gift is suggested instead",
          any(t["kind"] == "try" and t["value"] == "cadeau" and "un cadeau" in t["text"] for t in tips["tips"]), tips["tips"])
    good = http("POST", "/api/owner/campaigns/learning/tips", OWN, json={"title": "Café offert", "message": "Votre café est offert"}).json()
    check("a gift is confirmed", any(t["kind"] == "good" and t["value"] == "cadeau" for t in good["tips"]))
    check("nothing was sent while advising", db.push_notifications.count_documents({}) == 0)

    print("\nOne campaign, measured and taken apart")
    kid = db.campaigns.find_one({"tenant_id": "t1", "name": "☕ Café offert"})["id"]
    r = http("GET", f"/api/owner/campaigns/{kid}/result", OWN).json()
    played = {x["dimension"]: x for x in r["traits"]}
    check("its result", r["result"]["mature"] and r["result"]["came"] in (17, 18))
    check("and what played: the gift helped", played["offer"]["verdict"] == "plus" and played["emoji"]["value"] == "oui")
    check("another shop cannot read it", http("GET", f"/api/owner/campaigns/{kid}/result",
          auth.create_access_token({"sub": "x", "role": "business_owner", "tenant_id": "new"})).status_code == 404)
    page = http("GET", "/api/owner/campaigns/page", OWN).json()
    check("the Campagnes page shows each send's effect",
          any(x.get("result") and "effect" in x["result"] for x in page["recent"]))

    print("\nThe IA writes from it")
    from services import llm
    seen = {}
    llm._force_complete = None
    llm.is_configured = lambda: True
    llm.complete = lambda system, user, **kw: seen.update(user=user) or "TITRE: Votre café offert\nMESSAGE: On vous l'offre !"
    d = http("POST", "/api/owner/campaigns/ai-draft", OWN, json={"objective": "faire revenir", "segment": "all"})
    check("the brief tells the IA what works here", d.status_code == 200 and "Un cadeau" in seen.get("user", ""), seen.get("user", d.text)[:200])
    check("and what to avoid", "À éviter" in seen.get("user", "") and "remise" in seen.get("user", "").lower())

    print("\nThe plan")
    r9 = http("GET", "/api/owner/campaigns/learning", STARTER)
    check("Starter (no Campagnes) does not get it", r9.status_code in (402, 403), r9.status_code)
    check("Pro does", http("GET", "/api/owner/campaigns/learning", OWN).status_code == 200)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
