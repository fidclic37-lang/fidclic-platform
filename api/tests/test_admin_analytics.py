"""
Super admin › Analytics global — the five figures against the previous
period, the curves per day / week / month (totals at the end of each step),
plans / sectors / cities, the revenue per plan (amounts), acquisition sources,
and the recent activity with its six kinds.

Run: cd api && /usr/local/bin/python3 tests/test_admin_analytics.py
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
    from features import admin_commerces as AC, admin_dashboard as AD, admin_analytics as AN

    db = server.db
    AC.init(db); AD.init(db); AN.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    d = lambda n: now - dt.timedelta(days=n)                  # noqa: E731
    db.tenants.insert_many([
        {"id": "a", "name": "Café Lumière", "city": "Paris", "sector": "cafe", "plan": "gold", "subscription_status": "active", "created_at": d(200)},
        {"id": "b", "name": "Fit Gym", "city": "Tours", "sector": "Bien-être", "plan": "silver", "subscription_status": "active", "created_at": d(10)},
        {"id": "c", "name": "Optique Vision", "city": "Tours", "sector": "Mode", "plan": "vip", "subscription_status": "active", "created_at": d(5)},
        {"id": "z", "name": "Fermé", "city": "Lyon", "plan": "gold", "is_active": False, "created_at": d(100)},
    ])
    db.customers.insert_many(
        [{"id": f"a{i}", "tenant_id": "a", "created_at": d(100), "acquisition_source": "qr_store"} for i in range(5)]
        + [{"id": f"b{i}", "tenant_id": "b", "created_at": d(3), "acquisition_source": "instagram"} for i in range(3)]
        + [{"id": "c1", "tenant_id": "c", "created_at": d(2), "acquisition_source": "qr_store"},
           {"id": "c2", "tenant_id": "c", "created_at": d(2)}])
    db.visits.insert_many(
        [{"id": f"va{i}", "tenant_id": "a", "visit_time": d(4), "amount_paid": 10.0} for i in range(4)]
        + [{"id": f"vc{i}", "tenant_id": "c", "visit_time": d(1), "amount_paid": 25.5} for i in range(2)]
        + [{"id": "old", "tenant_id": "a", "visit_time": d(45), "amount_paid": 20.0}])
    db.reviews.insert_one({"id": "r1", "tenant_id": "a", "rating": 9, "created_at": d(1)})
    db.campaigns.insert_one({"id": "k1", "tenant_id": "a", "name": "Menu d'automne", "sent_at": d(2)})
    db.fidclic_invoices.insert_one({"id": "i1", "tenant_id": "c", "amount_paid": 129.0, "plan": "vip", "paid_at": d(1)})
    server.log_audit("billing.plan_activated", actor="o@c.fr", tenant_id="c", target="c", meta={"to": "vip"})
    server.log_audit("etablissement.updated", actor="o@a.fr", tenant_id="a", target="a")

    r = AN.analytics(token_data=ADMIN)                       # the last 30 days, per day
    k = {x["key"]: x for x in r["kpis"]}
    print("\nFigures")
    check("commerces: active ones, +200 % vs the start (1 → 3)", k["commerces"]["value"] == 3 and k["commerces"]["delta"] == 200)
    check("clients finaux", k["clients"]["value"] == 10)
    check("visites in the period (the old one is before)", k["visites"]["value"] == 6)
    check("MRR = 65 + 33 + 108", k["mrr"]["value"] == 206)
    check("chiffre d'affaires total = the customers' spending", k["ca"]["value"] == 91.0 and k["ca"]["delta"] == round((91 - 20) / 20 * 100))
    print("\nCurves")
    g = r["growth"]["points"]
    check("one point a day, 30 days", r["grain"] == "day" and 30 <= len(g) <= 31)
    check("commerces: total at the end of each day", g[0]["value"] == 1 and g[-1]["value"] == 3)
    check("clients: total at the end of each day", r["clients"]["points"][-1]["value"] == 10 and r["clients"]["points"][0]["value"] == 5)
    check("MRR curve ends on the MRR", r["mrr"]["points"][-1]["value"] == 206)
    w = AN.analytics(grain="week", token_data=ADMIN)
    m = AN.analytics(date_from=d(120).date().isoformat(), date_to=now.date().isoformat(), grain="month", token_data=ADMIN)
    check("week and month steps", 4 <= len(w["growth"]["points"]) <= 6 and 4 <= len(m["growth"]["points"]) <= 5)
    long = AN.analytics(date_from=d(300).date().isoformat(), date_to=now.date().isoformat(), grain="day", token_data=ADMIN)
    check("a day step on 300 days moves up to weeks", long["grain"] == "week")
    print("\nBreakdowns")
    check("subscriptions per plan, in order, with %", [(p["label"], p["count"], p["pct"]) for p in r["plans"]["rows"]]
          == [("Starter", 1, 33), ("Pro", 1, 33), ("Pro AI", 1, 33)] and r["plans"]["total"] == 3)
    check("closed businesses are left out", all(c["label"] != "Lyon" for c in r["cities"]))
    check("cities: Tours 2, Paris 1", [(c["label"], c["count"]) for c in r["cities"]] == [("Tours", 2), ("Paris", 1)])
    check("revenue per plan: amounts, no percentage", [(x["label"], x["amount"]) for x in r["revenue"]["rows"]] == [("Pro", 40.0), ("Pro AI", 51.0)]
          and "pct" not in r["revenue"]["rows"][0] and r["revenue"]["total"] == 91.0)
    check("sources of the customers who joined in the period", [(s["label"], s["count"]) for s in r["sources"]]
          == [("Instagram", 3), ("QR Store", 1), ("Autres", 1)])
    print("\nActivity")
    kinds = {a["kind"] for a in AN.activity(token_data=ADMIN)["rows"]}
    check("six kinds: commerce, abonnement, avis, marketing, paiement, mise à jour", kinds == {"commerce", "abonnement", "avis", "marketing", "paiement", "maj"})
    texts = " | ".join(a["text"] for a in AN.activity(token_data=ADMIN)["rows"])
    check("in words", "Nouveau commerce ajouté : Optique Vision (Tours)" in texts and "Abonnement Pro AI activé : Optique Vision (Tours)" in texts
          and "Paiement reçu : €129,00 (Pro AI) - Optique Vision" in texts and "Avis client reçu : Café Lumière (9/10)" in texts)
    check("the page shows the 6 latest", len(r["activity"]) == 6)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
