"""
Super admin › Insights — the four rules (Opportunité, Upgrade potentiel,
À surveiller, Risque) on real dated facts, growth buckets, the trend and the
deltas re-computed on past days, the editable thresholds, the table (tabs,
sector, priority order) and the CSV export.

Run: cd api && /usr/local/bin/python3 tests/test_admin_insights.py
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
    from features import admin_commerces as AC
    from features import admin_insights as I

    db = server.db
    AC.init(db)
    I.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(days=200)
    T = lambda tid, name, sector, plan="silver", created=old, **kw: {"id": tid, "name": name, "sector": sector, "city": "Tours",  # noqa: E731
                                                                     "plan": plan, "subscription_status": "active", "created_at": created, **kw}
    db.tenants.insert_many([
        T("upg", "Café Lumière", "Café"),                          # 450 / 500 cards this month → upgrade
        T("opp", "Boulangerie Saint-Michel", "Boulangerie"),       # 330 / 500 → opportunité
        T("pus", "Fit Gym", "Bien-être"),                          # 1 700 / 2 000 push → upgrade (notifications)
        T("rsk", "Salon Élégance", "Coiffure"),                    # visits -80 % → risque
        T("qui", "Optique Vision", "Mode"),                        # no notification for 70 days → à surveiller (haute)
        T("new", "Sushi Zen", "Restaurant", created=now - dt.timedelta(days=5)),   # too young to be « à surveiller »
        T("sus", "Kebab Istanbul", "Restaurant", suspended_at=now),                # suspended: not analysed
        T("nos", "Sans Secteur", ""),                              # never notified, no sector given
    ])
    today = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if today > now:
        today = now
    cust = lambda tid, n, at: [{"id": f"{tid}-{at.timestamp()}-{i}", "tenant_id": tid, "created_at": at} for i in range(n)]  # noqa: E731
    db.customers.insert_many(cust("upg", 450, today) + cust("opp", 330, today) + cust("rsk", 5, today))
    push = lambda tid, n, at: [{"tenant_id": tid, "channel": "web_push", "result": {"sent": 1}, "timestamp": at} for _ in range(n)]  # noqa: E731
    recent = now - dt.timedelta(days=3)
    db.delivery_log.insert_many(push("pus", 1700, today) + push("upg", 1, recent) + push("opp", 1, recent) + push("rsk", 1, recent)
                                + push("qui", 1, now - dt.timedelta(days=70)))
    visit = lambda tid, n, at: [{"id": f"v-{tid}-{at.timestamp()}-{i}", "tenant_id": tid, "visit_time": at} for i in range(n)]  # noqa: E731
    db.visits.insert_many(visit("rsk", 50, now - dt.timedelta(days=45)) + visit("rsk", 10, now - dt.timedelta(days=5))
                          + visit("upg", 20, now - dt.timedelta(days=45)) + visit("upg", 40, now - dt.timedelta(days=5))
                          + visit("opp", 30, now - dt.timedelta(days=45)) + visit("opp", 31, now - dt.timedelta(days=5)))

    print("\nThe four rules")
    b = I.board(token_data=ADMIN, type="upgrade")
    c = b["counts"]
    check("upgrade: cards ≥ 80 % and push ≥ 80 %", c["upgrade"] == 2)
    check("opportunité: cards between 60 and 80 %", c["opportunite"] == 1)
    check("risque: visits down by 30 % or more", c["risque"] == 1)
    check("à surveiller: no notification for 30 days, young businesses left out",
          {r["tenant_id"] for r in I.board(token_data=ADMIN, type="surveiller")["rows"]} == {"qui", "nos"})
    check("a suspended business is not analysed", all(r["tenant_id"] != "sus" for t in I.TYPE_LABEL for r in I.board(token_data=ADMIN, type=t)["rows"]))
    up = {r["tenant_id"]: r for r in b["rows"]}
    check("details: the cards quota", up["upg"]["details"] == "Cartes : 450 / 500 (90 %)")
    check("details: the notification quota when it is the higher one", up["pus"]["details"] == "Notifications : 1 700 / 2 000 (85 %)")
    check("recommendation: the next plan by name", up["upg"]["recommendation"] == "Proposer l'offre Pro" and up["upg"]["priority"] == "haute")
    rk = I.board(token_data=ADMIN, type="risque")["rows"][0]
    check("risque details and priority", rk["details"] == "-80 % de visites (30 derniers jours)" and rk["priority_label"] == "Haute")
    sv = I.board(token_data=ADMIN, type="surveiller")["rows"]
    qu = next(r for r in sv if r["tenant_id"] == "qui")
    check("never notified: said so, listed first", sv[0]["tenant_id"] == "nos" and sv[0]["details"] == "Aucune notification envoyée")
    check("à surveiller: days since the last notification, haute after 60 days",
          qu["details"] == "Aucune notification depuis 70 jours" and qu["priority"] == "haute")
    op = I.board(token_data=ADMIN, type="opportunite")["rows"][0]
    check("opportunité: « Proposer un upgrade », moyenne", op["recommendation"] == "Proposer un upgrade" and op["priority"] == "moyenne")

    print("\nFigures")
    k = {x["key"]: x for x in b["kpis"]}
    check("businesses analysed (suspended left out)", k["analyses"]["value"] == 7)
    check("growth buckets: upg +100 % croissance, rsk baisse, opp stable",
          k["croissance"]["value"] >= 1 and k["baisse"]["value"] >= 1 and k["stable"]["value"] >= 1)
    check("upgrade opportunities = businesses with Opportunité or Upgrade", k["upgrade"]["value"] == 3)
    check("cards: four, with the rule in the text", [x["key"] for x in b["cards"]] == ["opportunite", "surveiller", "risque", "upgrade"]
          and "plus de 80 %" in b["cards"][3]["sub"])
    check("distribution adds up", sum(x["count"] for x in b["distribution"]) == b["total"] == 6)
    check("trend ends on today's counts", b["trend"][-1]["upgrade"] == 2 and b["trend"][-1]["risque"] == 1)
    check("a past day is re-computed (no card yet 29 days ago)", b["trend"][0]["upgrade"] <= 1)
    labels = [s["label"] for s in b["sectors"]]
    check("top sectors from the insights", set(labels) >= {"Café", "Coiffure"})
    check("no sector given → one single « Autres », last", labels.count("Autres") == 1 and labels[-1] == "Autres")

    print("\nTable")
    check("rows sorted: haute first", [r["priority"] for r in b["rows"]] == sorted([r["priority"] for r in b["rows"]], key=lambda p: p != "haute"))
    check("sector filter", [r["tenant_id"] for r in I.board(token_data=ADMIN, type="upgrade", sector="Café")["rows"]] == ["upg"])
    check("pagination", I.board(token_data=ADMIN, type="upgrade", per_page=1)["pages"] == 2)
    csv = I.export(ids="upg:upgrade,rsk:risque", token_data=ADMIN).body.decode("utf-8")
    check("CSV of the ticked rows", csv.count("\n") == 3 and "Café Lumière" in csv and "Salon Élégance" in csv)

    print("\nRules")
    try:
        I.put_rules(I.RulesIn(opportunity_min=90, upgrade_min=80, risk_drop=30), token_data=ADMIN)
        check("opportunité must stay below upgrade", False)
    except HTTPException as e:
        check("opportunité must stay below upgrade", e.status_code == 400)
    I.put_rules(I.RulesIn(opportunity_min=60, upgrade_min=95, risk_drop=30), token_data=ADMIN)
    c2 = I.board(token_data=ADMIN)["counts"]
    check("a new threshold applies at once (90 % is now an opportunité)", c2["upgrade"] == 0 and c2["opportunite"] == 2)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
