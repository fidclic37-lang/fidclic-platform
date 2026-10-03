"""
Super admin › FIDCLIC AI — questions understood (keywords, then the model),
the eight analyses on real data (risk levels and reasons, limits, upgrades,
sectors, comparison, no campaign, inactive, recommendations), the CSV,
saved analyses and automatic reports.

Run: cd api && /usr/local/bin/python3 tests/test_admin_ai.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from fastapi import HTTPException
    from models import TokenData
    from features import admin_commerces as AC, admin_dashboard as AD, admin_insights as AI_INS, admin_ai as A
    from services import llm

    db = server.db
    for m in (AC, AD, AI_INS, A):
        m.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def status(fn):
        try:
            fn(); return 200
        except HTTPException as e:
            return e.status_code

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    d = lambda n: now - dt.timedelta(days=n)                  # noqa: E731
    T = lambda tid, name, sector, plan="gold", **kw: {"id": tid, "name": name, "sector": sector, "city": "Tours", "plan": plan,  # noqa: E731
                                                      "subscription_status": "active", "created_at": d(200), **kw}
    db.tenants.insert_many([
        T("fall", "Fit Gym", "Restaurant", "silver"),        # visits -80 %, no notification, no campaign → Élevé
        T("dip", "Kebab Istanbul", "Restaurant"),            # visits -35 %, campaign sent → Moyen
        T("ok", "Café Lumière", "Barber", "gold"),           # stable, busy
        T("full", "Optique Vision", "Barber", "silver"),     # 450 / 500 cards this month
        T("dead", "Sushi Zen", "Restaurant"),                 # no visit for 60 days
        T("new", "Tea Palace", "Barber", created_at=d(5)),    # too young
    ])
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"})
    V = lambda tid, n, day, amount=10.0: [{"id": f"{tid}-{day}-{i}", "tenant_id": tid, "visit_time": d(day), "amount_paid": amount} for i in range(n)]  # noqa: E731
    db.visits.insert_many(V("fall", 50, 45) + V("fall", 10, 10) + V("dip", 40, 45) + V("dip", 26, 10)
                          + V("ok", 30, 45, 20) + V("ok", 32, 10, 20) + V("full", 20, 45) + V("full", 22, 5) + V("dead", 30, 60))
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "full", "created_at": now, "last_visit_date": d(5)} for i in range(450)]
                             + [{"id": f"k{i}", "tenant_id": "ok", "created_at": d(100), "last_visit_date": d(10)} for i in range(5)])
    db.customers.update_many({"tenant_id": "dead"}, {"$set": {}})
    for tid in ("fall", "dip", "ok", "full", "dead"):
        db.customers.insert_one({"id": f"last-{tid}", "tenant_id": tid, "created_at": d(150),
                                 "last_visit_date": d(60) if tid == "dead" else d(5)})
    db.campaigns.insert_many([{"id": "k1", "tenant_id": "dip", "sent_at": d(3)}, {"id": "k2", "tenant_id": "ok", "sent_at": d(2)},
                              {"id": "k3", "tenant_id": "full", "sent_at": d(4)}])
    db.delivery_log.insert_many([{"tenant_id": t, "channel": "web_push", "result": {"sent": 1}, "timestamp": d(3)} for t in ("dip", "ok", "full")]
                                + [{"tenant_id": "fall", "channel": "web_push", "result": {"sent": 1}, "timestamp": d(50)}])

    print("\nQuestions understood")
    expect = {"Quels commerces risquent de partir ?": "risque", "Quels clients approchent de leur limite ?": "limite",
              "Quels commerces pourraient passer au plan supérieur ?": "upgrade", "Quels secteurs utilisent le plus FIDCLIC ?": "secteurs",
              "Quels commerces n'utilisent pas les campagnes ?": "sans_campagne", "Donne-moi les commerces inactifs depuis 30 jours.": "inactifs",
              "Analyse les performances des restaurants par rapport aux barbers.": "comparaison",
              "Montre-moi les opportunités d'upgrade.": "upgrade", "Quelles sont tes recommandations stratégiques ?": "recommandations"}
    check("the mockup's questions go to the right analysis", all(A.route(q) == k for q, k in expect.items()))

    print("\nCommerces à risque")
    r = A.ask(A.AskIn(question="Quels commerces risquent de partir ?"), token_data=ADMIN)
    by = {x["tenant_id"]: x for x in r["rows"]}
    check("the answer names how many", r["headline"].startswith("J'ai analysé") and "3 commerces à risque" in r["headline"])
    check("Fit Gym: Élevé, -80 % de visites first, then no notification → Contacter",
          by["fall"]["level_label"] == "Élevé" and by["fall"]["reasons"][0] == "-80 % de visites" and by["fall"]["action"] == "Contacter"
          and any("Aucune notification" in x for x in by["fall"]["reasons"]))
    check("Kebab: Moyen → Relancer", by["dip"]["level_label"] == "Moyen" and by["dip"]["action"] == "Relancer")
    check("stable and too-young businesses are not listed", "ok" not in by and "new" not in by)
    check("no visit at all → Élevé, said so", by["dead"]["level_label"] == "Élevé" and by["dead"]["reasons"][0].startswith("Aucune visite depuis"))
    check("charts: levels donut, sectors, activity lines", [x["count"] for x in r["charts"]["donut"]["rows"][:2]] == [2, 1]
          and r["charts"]["bars"]["rows"][0]["label"] == "Restauration / Fast-food" and len(r["charts"]["lines"]["series"]) == 3)
    check("a daily trend per row", len(by["fall"]["trend"]) == 30 and sum(by["fall"]["trend"]) == 10)

    print("\nThe other analyses")
    lim = A.analysis("limite", token_data=ADMIN)
    check("limite: Optique Vision at 90 % of its cards, upgrade to Pro", any(x["tenant_id"] == "full" and x["pct"] == 90 and x["action"] == "Proposer l'offre Pro"
                                                                             for x in lim["rows"]))
    up = A.analysis("upgrade", token_data=ADMIN)
    check("upgrade: with the MRR it would bring (+32 €)", any(x["tenant_id"] == "full" and x["gain"] == 32 for x in up["rows"]) and "+€32" in up["headline"])
    sec = A.analysis("secteurs", token_data=ADMIN)
    check("secteurs: sorted by visits, with basket and change", sec["rows"][0]["name"] == "Barbier" and sec["rows"][0]["visites"] == 54
          and sec["rows"][0]["panier"] == round((32 * 20 + 22 * 10) / 54, 2))
    cmp = A.ask(A.AskIn(question="Analyse les performances des restaurants par rapport aux barbers."), token_data=ADMIN)
    check("comparaison: the two sectors named, per-business averages", {x["name"] for x in cmp["rows"]} == {"Restauration / Fast-food", "Barbier"}
          and "visites par commerce" in cmp["headline"])
    one = A.ask(A.AskIn(question="Compare les restaurants et les fleuristes."), token_data=ADMIN)
    check("comparaison: a named sector with no business is said so", one["headline"].startswith("Je n'ai trouvé que « Restauration")
          and [x["name"] for x in one["rows"]] == ["Restauration / Fast-food"])
    sc = A.analysis("sans_campagne", token_data=ADMIN)
    check("sans campagne: Fit Gym and Sushi Zen, never had one", {x["tenant_id"] for x in sc["rows"]} == {"fall", "dead"}
          and sc["rows"][0]["reasons"] == ["Jamais de campagne"])
    ina = A.analysis("inactifs", token_data=ADMIN)
    check("inactifs: Sushi Zen (last visit 60 days ago)", [x["tenant_id"] for x in ina["rows"]] == ["dead"] and ina["rows"][0]["days"] == 60)
    reco = A.analysis("recommandations", token_data=ADMIN)
    check("recommandations: actions with impact, high priority first", reco["rows"] and reco["rows"][0]["level"] == "eleve"
          and any("Proposer l'offre supérieure" in x["name"] for x in reco["rows"]))

    print("\nOutside the analyses")
    u = A.ask(A.AskIn(question="Quelle heure est-il ?"), token_data=ADMIN)
    check("without a model: not understood, suggestions offered", u["key"] == "unknown" and u["suggestions"])
    os.environ["GROQ_API_KEY"] = os.environ.get("GROQ_API_KEY") or "test"
    calls = []
    llm._force_complete = lambda system, user: (calls.append(user), "risque" if "Classe" in system else "Il y a 6 commerces actifs.")[1]
    orig_cfg = llm.is_configured
    llm.is_configured = lambda: True
    m = A.ask(A.AskIn(question="Qui va probablement résilier bientôt ?"), token_data=ADMIN)
    check("a free question routed by the model", m["key"] == "risque")
    llm._force_complete = lambda system, user: "aucune" if "Classe" in system else "Il y a 6 commerces actifs sur la plateforme."
    g = A.ask(A.AskIn(question="Combien de commerces avons-nous ?"), token_data=ADMIN)
    check("otherwise the model answers from the figures", g["key"] == "general" and g["headline"].startswith("Il y a 6"))
    llm._force_complete = None
    llm.is_configured = orig_cfg

    print("\nExport, saved analyses, reports")
    csv = A.export("risque", token_data=ADMIN).body.decode("utf-8")
    check("CSV of the table", csv.startswith("﻿Commerce;Secteur") and "Fit Gym" in csv and "Contacter" in csv)
    s = A.save(A.SaveIn(key="risque", question="Quels commerces risquent de partir ?"), token_data=ADMIN)
    check("saved with its last result", s["last_count"] == 3 and A.list_saved(token_data=ADMIN)["rows"][0]["id"] == s["id"])
    check("run again with fresh data", A.run_saved(s["id"], token_data=ADMIN)["key"] == "risque")
    check("bad recipient refused", status(lambda: A.create_report(A.ReportIn(saved_id=s["id"], recipients=["nope"]), token_data=ADMIN)) == 400)
    rep = A.create_report(A.ReportIn(saved_id=s["id"], frequency="weekly", weekday=now.weekday(), recipients=["boss@fidclic.com"]), token_data=ADMIN)
    check("next run shown", rep["next_at"] > now.isoformat())
    from services import mailer
    sent = []
    real = mailer.send
    mailer.send = lambda to, subject, html, text=None, to_name=None: (sent.append((to, subject, html)), {"sent": True})[1]
    A.run_due_reports(now); A.run_due_reports(now)
    check("due today: sent once, with the table", len(sent) == 1 and "Fit Gym" in sent[0][2] and "FIDCLIC AI" in sent[0][1])
    check("send now", A.send_now(rep["id"], token_data=ADMIN)["sent"] == 1)
    mailer.send = lambda *a, **k: {"sent": False, "reason": "mailer_disabled"}
    check("email not configured → a clear error", status(lambda: A.send_now(rep["id"], token_data=ADMIN)) == 502)
    mailer.send = real
    A.delete_saved(s["id"], token_data=ADMIN)
    check("deleting the analysis removes its reports", not A.list_reports(token_data=ADMIN)["rows"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
