"""
Super admin › Dashboard — period figures, platform trend, sectors / plans,
status cards with their weekly history, rule-based opportunities, top 5,
recent activity.

Run: cd api && /usr/local/bin/python3 tests/test_admin_dashboard.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from models import TokenData
    from features import admin_commerces as A
    from features import admin_dashboard as D

    db = server.db
    A.init(db)
    D.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(days=200)
    db.tenants.insert_many([
        {"id": "a", "name": "Boulangerie Saint-Michel", "sector": "boulangerie", "city": "Tours", "plan": "gold",
         "subscription_status": "active", "created_at": old},
        {"id": "b", "name": "Café Lumière", "sector": "cafe", "city": "Tours", "plan": "silver", "subscription_status": "active",
         "created_at": old},
        {"id": "c", "name": "Réseau Loire", "sector": "restaurant", "city": "Blois", "plan": "franchise",
         "franchise_terms": {"price": 450, "establishments": 5}, "subscription_status": "active", "created_at": old},
        {"id": "d", "name": "Juice Lab", "sector": "cafe", "city": "Tours", "plan": "silver", "subscription_status": "trialing",
         "trial_ends_at": now + dt.timedelta(days=2), "created_at": now - dt.timedelta(days=5)},
    ])
    # a: 12 new cards a day for 3 weeks; b: 3 a day; c, d: almost none.
    db.customers.insert_many([{"id": f"a{i}", "tenant_id": "a", "name": "X", "pass_issued": True, "visits": 2,
                               "last_visit_date": now, "created_at": now - dt.timedelta(hours=2 * i + 1)} for i in range(252)])
    db.customers.insert_many([{"id": f"b{i}", "tenant_id": "b", "name": "X", "pass_issued": i % 2 == 0, "visits": 1,
                               "last_visit_date": now, "created_at": now - dt.timedelta(hours=8 * i + 1)} for i in range(63)])
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "c", "name": "X", "created_at": old} for i in range(4)])
    # Visits: b drops from 40 to 10.
    db.visits.insert_many([{"id": f"vb{i}", "tenant_id": "b", "customer_id": "b1", "visit_time": now - dt.timedelta(days=31 + i % 25)} for i in range(40)]
                          + [{"id": f"vb2{i}", "tenant_id": "b", "customer_id": "b1", "visit_time": now - dt.timedelta(days=i % 25)} for i in range(10)]
                          + [{"id": f"va{i}", "tenant_id": "a", "customer_id": "a1", "visit_time": now - dt.timedelta(days=i % 20), "amount_paid": 10.5} for i in range(30)])
    # This week's scans (statut = weekly cards AND scans, the weaker decides):
    # a ≈ 35 scans and 84 cards → actif; b ≈ 16 scans and 21 cards → à risque.
    db.visits.insert_many([{"id": f"wa{i}", "tenant_id": "a", "customer_id": "a1", "visit_time": now - dt.timedelta(hours=1 + i * 6)} for i in range(25)]
                          + [{"id": f"wb{i}", "tenant_id": "b", "customer_id": "b1", "visit_time": now - dt.timedelta(hours=1 + i * 12)} for i in range(13)])
    db.campaigns.insert_one({"id": "k1", "tenant_id": "a", "name": "Promo", "sent_at": now - dt.timedelta(days=2)})
    db.delivery_log.insert_many([{"tenant_id": "a", "kind": "campaign", "result": {"sent": 1}, "timestamp": now - dt.timedelta(days=2)},
                                 {"tenant_id": "a", "kind": "campaign", "result": {"sent": 0}, "timestamp": now - dt.timedelta(days=2)}])
    db.upgrade_requests.insert_one({"id": "r1", "tenant_id": "b", "tenant_name": "Café Lumière", "requested_plan": "franchise",
                                    "status": "pending", "created_at": now - dt.timedelta(hours=3)})
    server.log_audit("admin.plan_change", actor="boss@fidclic.com", actor_type="user", target="b", tenant_id="b",
                     meta={"from": "silver", "to": "gold"})

    D.CACHE_SECONDS = 0                 # every call below recomputes
    d = D.dashboard(token_data=ADMIN)
    print("\nFigures")
    k = {x["key"]: x for x in d["kpis"]}
    check("figures: Commerces, Impayé, clients, cartes, CA, MRR", list(k) == ["commerces", "impaye", "clients", "cartes", "ca", "mrr"])
    check("commerces = en essai + abonnés", k["commerces"]["value"] == 4 and k["clients"]["value"] == 319)
    check("…1 in trial, 3 signed", k["commerces"]["breakdown"] == {"essai": 1, "abonne": 3})
    check("no impayé yet", k["impaye"]["value"] == 0)
    check("cartes actives = cards on a phone", k["cartes"]["value"] == 252 + 32)
    check("chiffre d'affaires total = what customers spent in the period", k["ca"]["value"] == 315.0)
    check("MRR: paying businesses, franchise at its agreed price", k["mrr"]["value"] == 65 + 33 + 450)
    check("each figure has its trend", all(len(x["series"]) == 8 for x in d["kpis"] if x["key"] != "impaye"))
    p = D.dashboard(date_from=(now - dt.timedelta(days=7)).date().isoformat(), date_to=now.date().isoformat(), token_data=ADMIN)
    check("a shorter period counts less", {x["key"]: x for x in p["kpis"]}["ca"]["value"] < 315.0)
    db.tenants.update_one({"id": "c"}, {"$set": {"suspended_at": now}})
    D._cache.clear()
    kk = {x["key"]: x for x in D.dashboard(token_data=ADMIN)["kpis"]}
    check("a suspended business leaves Commerces and counts as Impayé", kk["commerces"]["value"] == 3 and kk["impaye"]["value"] == 1
          and kk["impaye"]["suspendus"] == 1 and kk["impaye"]["mrr_at_stake"] == 450)
    db.tenants.update_one({"id": "c"}, {"$unset": {"suspended_at": ""}})
    D._cache.clear()

    print("\nCharts")
    check("Évolution and the sector donut left the Dashboard", "evolution" not in d and "sectors" not in d)
    check("ville, chiffre d'affaires per plan, sources", d["cities"][0] == {"key": "Tours", "label": "Tours", "count": 3, "pct": 75}
          and d["revenue"]["total"] == 315.0 and d["revenue"]["rows"][0]["label"] == "Pro" and d["sources"])
    from features import admin_analytics as AN
    AN.init(db)
    an = AN.analytics(token_data=ADMIN)
    check("…the same figures as Analytics", an["cities"] == d["cities"] and an["revenue"] == d["revenue"] and an["sources"] == d["sources"])
    check("Analytics: six calendar months of « Évolution »", len(an["evolution"]) == 6 and an["evolution"][-1]["commerces"] == 4)
    check("…twelve on request", len(AN.analytics(months=12, token_data=ADMIN)["evolution"]) == 12)
    check("Analytics: sector donut in French", {s["label"] for s in an["sectors_donut"]} == {"Boulangerie", "Café / Salon de thé", "Restauration / Fast-food"})
    check("plans incl. franchise and trial", {p_["key"]: p_["count"] for p_ in d["plans"]} == {"silver": 1, "gold": 1, "franchise": 1, "essai": 1})

    sh = D._share({"A": 5, "B": 4, "Autres": 2, "C": 1, "D": 1}, top=2)
    check("one « Autres », last, holding the rest and the ungrouped", [x["label"] for x in sh] == ["A", "B", "Autres"] and sh[-1]["count"] == 4)

    print("\nStatus cards")
    sc = {x["key"]: x for x in d["status_cards"]}
    check("six cards: nouveaux, actifs, inactifs, à risque, résilié, essais non convertis",
          [x["key"] for x in d["status_cards"]] == ["nouveaux", "actif", "inactif", "a_risque", "resilie", "non_converti"])
    check("actif / à risque / inactif from weekly cards AND scans", sc["actif"]["value"] == 1 and sc["a_risque"]["value"] == 1 and sc["inactif"]["value"] == 2)
    check("share of the businesses still with us", sc["actif"]["pct"] == 25)
    check("twelve weeks of history, ending with today's count", len(sc["actif"]["bars"]) == 12 and sc["actif"]["bars"][-1] == 1)
    check("12 weeks ago: three businesses with nothing yet → inactif, the fourth not signed up",
          sc["inactif"]["bars"][0] == 3 and sc["actif"]["bars"][0] + sc["a_risque"]["bars"][0] == 0)
    check("new this month", sc["nouveaux"]["value"] >= 1 and sum(sc["nouveaux"]["bars"]) >= 1)

    print("\nOpportunities (rules, named)")
    o = {x["key"]: x for x in d["opportunities"]}
    check("no campaign for 30 days", {t["name"] for t in o["no_campaign"]["tenants"]} == {"Café Lumière", "Réseau Loire"})
    check("falling activity", [t["id"] for t in o["falling"]["tenants"]] == ["b"])
    check("trial ending in 3 days", [t["id"] for t in o["trial_ending"]["tenants"]] == ["d"])
    check("pending franchise request", [t["id"] for t in o["franchise"]["tenants"]] == ["b"])
    check("labels say how many", o["falling"]["label"].startswith("1 commerce en baisse"))
    db.tenants.update_one({"id": "a"}, {"$set": {"plan": "silver"}})
    db.plan_settings.insert_one({"plan": "silver", "overrides": {"max_customers": 280}})
    o2 = {x["key"]: x for x in D.dashboard(token_data=ADMIN)["opportunities"]}
    check("near the card limit, and ready for a bigger plan", [t["id"] for t in o2["near_limit"]["tenants"]] == ["a"]
          and "a" in [t["id"] for t in o2["upgrade"]["tenants"]])
    db.plan_settings.delete_many({})
    db.tenants.update_one({"id": "a"}, {"$set": {"plan": "gold"}})

    check("one-pass active count = server.count_active_customers", all(D._active_by_tenant(now).get(t, 0) == server.count_active_customers(t)
                                                                     for t in ("a", "b", "c", "d")))

    print("\nTop and activity")
    check("top 5 by clients", [t["id"] for t in d["top"]][:2] == ["a", "b"] and d["top"][0]["plan"]["label"] == "Pro")
    kinds = [e["kind"] for e in d["activity"]]
    check("recent activity: sign-up, campaign, plan change, request, new clients",
          {"signup", "campaign", "plan", "request", "clients"} <= set(kinds))
    check("newest first", d["activity"] == sorted(d["activity"], key=lambda e: e["at"], reverse=True))
    check("plan change says to what", any(e["kind"] == "plan" and e["sub"] == "Café Lumière → Pro" for e in d["activity"]))

    D.CACHE_SECONDS = 60
    first = D.dashboard(token_data=ADMIN)
    db.tenants.insert_one({"id": "z", "name": "Nouveau", "created_at": now})
    check("cached for a minute", D.dashboard(token_data=ADMIN) is first)

    print("\nImpayé, résilié, essais non convertis, lists")
    db.tenants.insert_many([
        {"id": "e", "name": "Ex Client", "city": "Tours", "plan": "gold", "subscription_status": "active", "created_at": old,
         "resiliated_at": now - dt.timedelta(days=3), "resiliation_reason": "Fermeture", "phone": "0611223344"},
        {"id": "f", "name": "Essai Perdu", "city": "Tours", "plan": "silver", "subscription_status": "trialing", "created_at": now - dt.timedelta(days=40),
         "trial_ends_at": now - dt.timedelta(days=5)},
        {"id": "g", "name": "Retard Paiement", "city": "Blois", "plan": "silver", "subscription_status": "past_due", "created_at": old},
        {"id": "i", "name": "Converti", "city": "Blois", "plan": "silver", "subscription_status": "active", "created_at": now - dt.timedelta(days=40),
         "trial_ends_at": now - dt.timedelta(days=10), "subscription_started_at": now - dt.timedelta(days=10)},
    ])
    db.users.insert_one({"email": "owner@ex.fr", "role": "business_owner", "tenant_id": "e", "first_name": "Léa", "last_name": "Martin"})
    D._cache.clear()
    d2 = D.dashboard(token_data=ADMIN)
    k2 = {x["key"]: x for x in d2["kpis"]}
    s2 = {x["key"]: x for x in d2["status_cards"]}
    z = 1                                   # the business added by hand earlier in this test
    check("Commerces: the converted trial joins, résilié / non converti / impayé don't", k2["commerces"]["value"] == 5 + z
          and k2["commerces"]["breakdown"] == {"essai": 1, "abonne": 4 + z} and k2["commerces"]["series"][-1] == 5 + z)
    check("Impayé: the late payer", k2["impaye"]["value"] == 1 and k2["impaye"]["suspendus"] == 0)
    check("MRR leaves out résilié and impayé", k2["mrr"]["value"] == 65 + 33 + 450 + 33)
    check("Résilié card: 1 in the period, 1 in all", s2["resilie"]["value"] == 1 and s2["resilie"]["total"] == 1 and sum(s2["resilie"]["bars"]) == 1)
    check("Essais non convertis: 1, conversion 50 % (1 of 2 trials ended)", s2["non_converti"]["value"] == 1
          and s2["non_converti"]["ended"] == 2 and s2["non_converti"]["conversion"] == 50)
    check("résilié and non converti stay out of actif / inactif / à risque",
          s2["actif"]["value"] + s2["inactif"]["value"] + s2["a_risque"]["value"] == 6 + z)
    L = lambda key: D.dashboard_list(key, token_data=ADMIN)                     # noqa: E731
    r = L("resilie")
    check("every card opens its businesses — résiliés with reason, owner and phone",
          [x["id"] for x in r["rows"]] == ["e"] and r["rows"][0]["resiliation_reason"] == "Fermeture"
          and r["rows"][0]["email"] == "owner@ex.fr" and r["rows"][0]["owner"] == "Léa Martin" and r["rows"][0]["phone"] == "0611223344")
    check("essai / abonné / impayé / non converti lists", [x["id"] for x in L("essai")["rows"]] == ["d"]
          and {x["id"] for x in L("abonne")["rows"]} - {"z"} == {"a", "b", "c", "i"} and [x["id"] for x in L("impaye")["rows"]] == ["g"]
          and [x["id"] for x in L("non_converti")["rows"]] == ["f"])
    check("Commerces list = essai + abonnés", {x["id"] for x in L("commerces")["rows"]} - {"z"} == {"a", "b", "c", "d", "i"})
    check("actif list carries cards and scans a week", L("actif")["rows"][0]["id"] == "a" and L("actif")["rows"][0]["scans_week"] >= 25)
    m = L("mrr")
    check("MRR list: biggest first, € / mois", m["metric_label"] == "€ / mois" and m["rows"][0]["id"] == "c" and m["rows"][0]["metric"] == 450)
    check("CA list sorted by what customers spent", L("ca")["rows"][0]["id"] == "a")
    try:
        L("nope"); unknown = False
    except Exception as e:
        unknown = getattr(e, "status_code", None) == 404
    check("unknown list refused", unknown)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
