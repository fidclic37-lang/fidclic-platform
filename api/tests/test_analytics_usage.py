"""
Super admin › Analytics › « Utilisation des plans » — cartes actives,
notifications envoyées, géolocalisation activée; the three tabs (utilisation
par commerce with its filters and pages, répartition par plan,
renouvellements) and the CSV export.

Run: cd api && /usr/local/bin/python3 tests/test_analytics_usage.py
"""
import datetime as dt
from zoneinfo import ZoneInfo
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from models import TokenData
    from features import admin_commerces as AC, admin_dashboard as AD, analytics_usage as U, plan_limits as PL

    db = server.db
    AC.init(db); AD.init(db); U.init(db); PL.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    d = lambda n: now - dt.timedelta(days=n)                  # noqa: E731
    later = lambda n: now + dt.timedelta(days=n)              # noqa: E731
    # a moment surely inside this month, by the UTC and by the Paris clock: the
    # suite also runs on the 1st, when « 2 days ago » is last month
    _p = now.astimezone(ZoneInfo("Europe/Paris")).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _start = max(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), _p.astimezone(dt.timezone.utc))
    in_month = _start + (now - _start) / 2
    db.tenants.insert_many([
        {"id": "a", "name": "Café Lumière", "city": "Tours", "sector": "cafe", "plan": "gold", "subscription_status": "active",
         "created_at": d(200), "geo_enabled": True, "subscription_period_end": later(3)},
        {"id": "b", "name": "Fit Gym", "city": "Tours", "sector": "Bien-être", "plan": "silver", "subscription_status": "active",
         "created_at": d(100), "geo_enabled": True, "subscription_period_end": later(20)},     # geo on, but not in Starter
        {"id": "c", "name": "Optique Vision", "city": "Paris", "sector": "Mode", "plan": "vip", "subscription_status": "trialing",
         "created_at": d(5), "trial_ends_at": later(2)},                                       # geo in the plan, not switched on
        {"id": "e", "name": "Sushi Zen", "city": "Paris", "sector": "restaurant", "plan": "gold", "subscription_status": "past_due",
         "created_at": d(90), "geo_enabled": True, "subscription_period_end": later(40)},
        {"id": "z", "name": "Fermé", "city": "Lyon", "plan": "gold", "is_active": False, "created_at": d(100)},
    ])
    db.customers.insert_many(
        [{"id": f"a{i}", "tenant_id": "a", "created_at": d(400), "last_visit_date": d(10)} for i in range(4)]     # active
        + [{"id": "a-old", "tenant_id": "a", "created_at": d(800), "last_visit_date": d(500)}]                    # dormant
        + [{"id": f"b{i}", "tenant_id": "b", "created_at": d(3)} for i in range(3)]                               # joined, no visit: active
        + [{"id": "c1", "tenant_id": "c", "created_at": d(2), "last_visit_date": d(1)},
           {"id": "gone", "tenant_id": "c", "created_at": d(2), "deleted_at": d(1)},                              # deleted: never counts
           {"id": "z1", "tenant_id": "z", "created_at": d(2)}])                                                    # business closed
    # Before the period (30 days ago): a0..a3 had come within the year (visit 50 days ago), b/c did not exist yet.
    db.visits.insert_many([{"id": f"v{i}", "tenant_id": "a", "customer_id": f"a{i}", "visit_time": d(50)} for i in range(4)])
    push = lambda tid, days, sent=1: {"tenant_id": tid, "channel": "web_push", "result": {"sent": sent}, "timestamp": d(days)}   # noqa: E731
    db.delivery_log.insert_many([push("a", 1), push("a", 1), push("a", 2), push("b", 1), push("a", 1, sent=0),
                                 {"tenant_id": "a", "channel": "email", "result": {"sent": 1}, "timestamp": d(1)},
                                 push("a", 40), push("z", 1)])
    db.delivery_log.update_one({"tenant_id": "b", "timestamp": d(1)}, {"$set": {"timestamp": in_month}})
    for i in range(1800):                                     # Fit Gym (Starter, 2 000 notifications) near its limit
        db.delivery_log.insert_one(push("b", 0.01))

    print("\nChiffres")
    f = U.usage_figures(token_data=ADMIN)
    check("cartes actives: dormant, deleted and closed-business cards left out (4 + 3 + 1)", f["cards"]["value"] == 8)
    check("cartes actives vs the start of the period (4 → 8 = +100 %)", f["cards"]["delta"] == 100)
    check("notifications envoyées: web push that really left, in the period, open businesses only", f["push"]["value"] == 1804)
    check("notifications vs the period before (1 → 1804)", f["push"]["delta"] == 180300)
    check("a 30-day period is labelled « mois »", f["push"]["month"] is True)
    check("géolocalisation activée: in the plan AND switched on (Café Lumière, Sushi Zen)", f["geo"]["value"] == 2 and f["geo"]["pct"] == 50)

    print("\nUtilisation par commerce")
    U._cache.clear()
    r = U.usage_commerces(token_data=ADMIN)
    rows = {x["id"]: x for x in r["rows"]}
    check("the four open businesses, by name", r["total"] == 4 and [x["name"] for x in r["rows"]][0] == "Café Lumière")
    a, b, c = rows["a"], rows["b"], rows["c"]
    check("cartes = active cards against the plan's limit (Pro 4 500)", a["cards"]["used"] == 4 and a["cards"]["limit"] == 4500)
    check("notifications = this month's against the monthly limit", b["push"]["used"] == 1801 and b["push"]["limit"] == 2000 and b["push"]["pct"] == 90)
    check("Pro AI: unlimited notifications", c["push"]["limit"] is None and c["push"]["pct"] is None)
    check("IA / Wallet / Multi-sites follow the plan", (a["ai"], b["ai"], c["ai"]) == (True, False, True) and b["wallet"] and c["multi"] and not a["multi"])
    check("géo: on / not in the plan / included but off", (a["geo"], b["geo"], c["geo"]) == ("on", "none", "off"))
    check("renouvellement: end of the billing period", a["renewal"]["kind"] == "renouvellement" and a["renewal"]["days"] in (2, 3))
    check("trial: its end", c["renewal"]["kind"] == "fin_essai" and c["trial"])
    check("late payment flagged", rows["e"]["renewal"]["kind"] == "retard")
    check("statut from the Commerces page", a["status"] in AC.STATUS_LABELS and a["status_label"] == AC.STATUS_LABELS[a["status"]])
    check("plan filter", [x["id"] for x in U.usage_commerces(plan="gold", token_data=ADMIN)["rows"]] == ["a", "e"])
    check("ville + recherche", [x["id"] for x in U.usage_commerces(city="Paris", q="sushi", token_data=ADMIN)["rows"]] == ["e"])
    check("géo « incluse, non activée » filter", [x["id"] for x in U.usage_commerces(geo="off", token_data=ADMIN)["rows"]] == ["c"])
    check("IA non filter", [x["id"] for x in U.usage_commerces(ia="non", token_data=ADMIN)["rows"]] == ["b"])
    check("near the limit (≥ 80 %)", [x["id"] for x in U.usage_commerces(usage="alerte", token_data=ADMIN)["rows"]] == ["b"])
    check("renouvellement within 7 days", {x["id"] for x in U.usage_commerces(renew="7", token_data=ADMIN)["rows"]} == {"a", "c"})
    check("essai only", [x["id"] for x in U.usage_commerces(sub="essai", token_data=ADMIN)["rows"]] == ["c"])
    p = U.usage_commerces(per_page=10, page=9, token_data=ADMIN)
    check("pages: an out-of-range page falls back to the last", p["page"] == 1 and p["pages"] == 1)
    s = U.usage_commerces(sort="-push", token_data=ADMIN)
    check("sort by notifications", s["rows"][0]["id"] == "b")
    check("filter options", r["options"]["cities"] == ["Paris", "Tours"] and [o["key"] for o in r["options"]["plans"]] == ["silver", "gold", "vip"])

    print("\nRépartition par plan")
    pl = {x["key"]: x for x in U.usage_plans(token_data=ADMIN)["rows"]}
    check("commerces and share per plan", pl["gold"]["count"] == 2 and pl["gold"]["pct"] == 50 and pl["silver"]["pct"] == 25)
    check("MRR counts paying businesses only (Sushi Zen is late)", pl["gold"]["mrr"] == float(server.get_plan_features("gold")["price"]))
    check("trials counted", pl["vip"]["trials"] == 1 and pl["vip"]["paying"] == 0)
    check("near the limit per plan", pl["silver"]["near"] == 1)
    check("features of the plan", pl["silver"]["geo"] is False and pl["gold"]["geo_on"] == 2 and pl["vip"]["multi"])

    print("\nRenouvellements")
    rn = U.usage_renewals(within="30", token_data=ADMIN)
    check("next 30 days, soonest first", [x["id"] for x in rn["rows"]] == ["c", "a", "b"])
    check("summary: 2 in 7 days, 1 trial ending, 1 late", rn["summary"]["week"] == 2 and rn["summary"]["trials"] == 1 and rn["summary"]["late"] == 1)
    check("amount due in 7 days counts real renewals only", rn["summary"]["week_amount"] == float(server.get_plan_features("gold")["price"]))
    check("all dates", U.usage_renewals(within="all", token_data=ADMIN)["total"] == 4)
    check("by type", [x["id"] for x in U.usage_renewals(within="all", kind="retard", token_data=ADMIN)["rows"]] == ["e"])

    print("\nExport (CSV)")
    body = U.usage_export(tab="commerces", city="Tours", token_data=ADMIN).body.decode("utf-8-sig")
    lines = body.strip().splitlines()
    check("the filtered rows, French headers", len(lines) == 3 and lines[0].startswith("Commerce;Secteur;Ville;Plan;Statut"))
    check("ticked rows only", len(U.usage_export(tab="commerces", ids="c", token_data=ADMIN).body.decode("utf-8-sig").strip().splitlines()) == 2)
    check("unlimited written out", "illimité" in U.usage_export(ids="c", token_data=ADMIN).body.decode("utf-8-sig"))
    check("plans tab", "Proches de la limite" in U.usage_export(tab="plans", token_data=ADMIN).body.decode("utf-8-sig"))
    check("renewals tab", U.usage_export(tab="renewals", within="7", token_data=ADMIN).body.decode("utf-8-sig").count("\n") == 3)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
