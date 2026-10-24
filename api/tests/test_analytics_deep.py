"""
Super admin › Analytics › « Analyses avancées » and Dashboard › « À suivre
aujourd'hui » (2026-10-01): cohorts (still a client), sector benchmarks
(medians, sample size), feature adoption per plan, upgrades / downgrades,
top / bottom growth (combined score with its eligibility rules), the map
(own position, postal code, town), and the four « À suivre » blocks with
their permissions.

Run: cd api && /usr/local/bin/python3 tests/test_analytics_deep.py
"""
import asyncio
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from models import TokenData
    from features import analytics_deep as X, admin_dashboard as D, analytics_usage as U
    from services import communes

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(url, token):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as c:
                return await c.get(url, headers={"Authorization": f"Bearer {token}"})
        return asyncio.get_event_loop().run_until_complete(run())

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d, h=0: now - dt.timedelta(days=d, hours=h)        # noqa: E731
    old = ago(200)
    db.tenants.insert_many([
        {"id": "A", "name": "Café Alpha", "sector": "cafe", "city": "Tours", "postal_code": "37000", "plan": "gold", "subscription_status": "active",
         "created_at": old, "geo_enabled": True, "lat": 47.39, "lng": 0.68},
        {"id": "B", "name": "Café Beta", "sector": "cafe", "city": "Tours", "postal_code": "37100", "plan": "silver", "subscription_status": "active",
         "created_at": old},
        {"id": "C", "name": "Boulangerie Gamma", "sector": "boulangerie", "city": "Blois", "plan": "vip", "subscription_status": "active", "created_at": old},
        {"id": "D", "name": "Ex Delta", "sector": "cafe", "city": "Paris", "plan": "gold", "subscription_status": "active", "created_at": old,
         "resiliated_at": ago(10)},
        {"id": "E", "name": "Essai Perdu", "sector": "cafe", "city": "Tours", "plan": "silver", "subscription_status": "trialing",
         "created_at": ago(40), "trial_ends_at": ago(3)},
        {"id": "F", "name": "Essai En Cours", "sector": "cafe", "city": "Tours", "plan": "silver", "subscription_status": "trialing",
         "created_at": ago(25), "trial_ends_at": now + dt.timedelta(days=3)},
        {"id": "G", "name": "Retard", "sector": "cafe", "city": "Tours", "plan": "silver", "subscription_status": "past_due", "created_at": old},
    ])
    # Activity: A doubles (+100 % on scans, cards and CA), B halves (−50 %), C almost nothing.
    def customers(tid, n, days_ago, wallet=False):
        db.customers.insert_many([{"id": f"{tid}-{days_ago}-{i}", "tenant_id": tid, "created_at": ago(days_ago, i % 20), "pass_issued": wallet}
                                  for i in range(n)])
    def visits(tid, n, from_days, to_days, amount):
        span = (from_days - to_days) * 24
        db.visits.insert_many([{"id": f"v-{tid}-{from_days}-{i}", "tenant_id": tid, "customer_id": f"{tid}-c{i % 10}",
                                "visit_time": ago(to_days, 1 + i * span // max(n, 1)), "amount_paid": amount} for i in range(n)])
    customers("A", 10, 45); customers("A", 20, 10, wallet=True)
    customers("B", 10, 45); customers("B", 5, 10)
    customers("C", 2, 10)
    visits("A", 20, 60, 30, 10.0); visits("A", 40, 30, 0, 10.0)
    visits("B", 40, 60, 30, 10.0); visits("B", 20, 30, 0, 10.0)
    visits("C", 5, 20, 0, 0)

    print("\nCohortes de rétention (still a client)")
    co = X.cohorts(months=12, token_data=ADMIN)
    cur = co["rows"][-1]
    check("twelve signup months, oldest first", len(co["rows"]) == 12 and co["rows"][0]["cohort"] < cur["cohort"])
    by = {r["cohort"]: r for r in co["rows"]}
    e_month = ago(40).strftime("%Y-%m")
    f_month = ago(25).strftime("%Y-%m")
    if e_month == f_month:
        r = by[e_month]
        check("E (trial lost) and F (trial running): 2 in the cohort, 1 still a client today", r["size"] == 2 and r["cells"][-1]["kept"] == 1)
    else:
        check("E's cohort: lost today", by[e_month]["size"] == 1 and by[e_month]["cells"][-1]["kept"] == 0)
        check("F's cohort: still a client", by[f_month]["size"] == 1 and by[f_month]["cells"][-1]["kept"] == 1)
    check("a month without sign-ups has no %", any(r["size"] == 0 and all(c["pct"] is None for c in r["cells"]) for r in co["rows"]))

    print("\nBenchmarks par secteur (medians over 90 days)")
    bm = {r["sector"]: r for r in X.benchmarks(token_data=ADMIN)["rows"]}
    cafe = bm.get("Café / Salon de thé")
    check("café: A and B (D résilié, E/F too young or lost, G no activity)", cafe and cafe["n"] == 2 and cafe["low_sample"])
    check("panier moyen = median of each business's average ticket", cafe["panier"] == 10.0)
    check("taux de retour: every customer came back", cafe["retour"] == 100.0)
    check("the platform line comes first", X.benchmarks(token_data=ADMIN)["rows"][0]["sector"] == "Toute la plateforme")
    check("C counts with its 5 scans (no amount → no panier)", bm["Boulangerie"]["n"] == 1 and bm["Boulangerie"]["panier"] is None)

    print("\nAdoption des fonctionnalités par plan")
    db.campaigns.insert_one({"id": "k", "tenant_id": "A", "sent_at": ago(5)})
    db.auto_campaign_log.insert_one({"tenant_id": "A", "sent_at": ago(2)})
    db.ai_queries.insert_one({"tenant_id": "C", "created_at": ago(1)})
    db.referral_config.insert_one({"tenant_id": "A", "enabled": True})
    db.saved_segments.insert_one({"tenant_id": "B", "name": "VIP"})
    db.api_keys.insert_many([{"id": "k1", "hash": "h1", "prefix": "p1", "tenant_id": "C", "revoked_at": None}, {"id": "k2", "hash": "h2", "prefix": "p2", "tenant_id": "B", "revoked_at": ago(1)}])
    ad = {r["plan"]: {c["key"]: c for c in r["cells"]} | {"_n": r["count"]} for r in X.adoption(token_data=ADMIN)["rows"]}
    check("Pro: A uses wallet, campagnes, automatisations, géo, parrainage", ad["gold"]["_n"] == 1 and all(ad["gold"][k]["count"] == 1 for k in
          ("wallet", "campagnes", "automatisations", "geo", "parrainage")))
    check("Starter: B's segment counts, its revoked API key doesn't; F, G are Starter clients too", ad["silver"]["_n"] == 3
          and ad["silver"]["segments"]["count"] == 1 and ad["silver"]["api"]["count"] == 0)
    check("Pro AI: C uses the AI and the API", ad["vip"]["ia"]["count"] == 1 and ad["vip"]["api"]["count"] == 1)
    check("whether the plan includes it", ad["silver"]["campagnes"]["included"] is False and ad["gold"]["campagnes"]["included"] is True)

    print("\nUpgrades / downgrades")
    server.log_audit("admin.plan_change", actor="boss@fidclic.com", actor_type="user", target="B", tenant_id="B", meta={"from": "silver", "to": "gold"})
    server.log_audit("admin.plan_change", actor="boss@fidclic.com", actor_type="user", target="A", tenant_id="A", meta={"from": "vip", "to": "gold"})
    server.log_audit("billing.plan_activated", actor="stripe", actor_type="system", target="C", tenant_id="C", meta={"to": "vip"})
    # Through tomorrow: mongomock compares an audit row written a few ms ago oddly against « now ».
    pm = X.plan_moves(date_from=(now - dt.timedelta(days=30)).date().isoformat(), date_to=(now + dt.timedelta(days=1)).date().isoformat(), token_data=ADMIN)
    check("1 upgrade, 1 downgrade, 1 activation", pm["upgrades"] == 1 and pm["downgrades"] == 1 and pm["activations"] == 1)
    up = next(r for r in pm["rows"] if r["kind"] == "upgrade")
    check("with the € / month it moved and who did it", up["name"] == "Café Beta" and up["mrr_change"] == 32.0 and up["by"] == "boss@fidclic.com")
    check("online payment named", any(r["by"] == "Paiement en ligne" for r in pm["rows"]))

    print("\nTop / bottom croissance (combined score)")
    g = X.growth(token_data=ADMIN)
    check("A on top with +100 % on scans, cards and CA", g["top"][0]["id"] == "A" and g["top"][0]["score"] == 100
          and g["top"][0]["parts"] == {"scans": 100, "cartes": 100, "ca": 100})
    check("B at the bottom with −50 %", g["bottom"][0]["id"] == "B" and g["bottom"][0]["score"] == -50)
    check("left out: C and G too little activity, F too young; D résilié and E non converti not ranked",
          g["too_quiet"] == 2 and g["too_young"] == 1 and g["eligible"] == 2 and {r["id"] for r in g["top"] + g["bottom"]} == {"A", "B"})
    check("the same business is never top and bottom", not ({r["id"] for r in g["top"]} & {r["id"] for r in g["bottom"]}))
    check("growth capped at +300 %", X._growth(100, 1) == 300.0 and X._growth(0, 10) == -100.0 and X._growth(0, 0) is None)

    print("\nCarte des commerces")
    asked = []
    communes._fetch_position = lambda q, postcode="", kind="municipality": (asked.append((q, postcode)), (47.40, 0.70) if postcode else (47.59, 1.33))[1]
    mp = X.commerces_map(token_data=ADMIN)
    pts = {p["id"]: p for p in mp["points"]}
    check("own position first", pts["A"]["lat"] == 47.39 and pts["A"]["source"] == "adresse")
    check("else the postal code's centre", pts["B"]["source"] == "code postal" and pts["B"]["lat"] == 47.40)
    check("else the town", pts["C"]["source"] == "ville" and pts["C"]["lat"] == 47.59)
    n = len(asked)
    X.commerces_map(token_data=ADMIN)
    check("each place is looked up once (cached)", len(asked) == n)
    check("standing on every point", pts["D"]["standing"] == "resilie" and pts["G"]["standing"] == "impaye")

    print("\nDashboard › À suivre aujourd'hui")
    db.support_tickets.insert_many([{"id": "s1", "status": "urgent", "unread_team": 0, "created_at": ago(2), "first_response_at": ago(2) + dt.timedelta(hours=3)},
                                    {"id": "s2", "status": "nouveau", "unread_team": 2, "created_at": ago(1), "last_from": "merchant"},
                                    {"id": "s3", "status": "resolu", "created_at": ago(5), "first_response_at": ago(5) + dt.timedelta(hours=1),
                                     "resolved_at": ago(4), "rating": {"stars": 4, "at": ago(4)}}])
    # a rendez-vous later TODAY in Paris: « now + 2 h » was tomorrow after 22:00 (CI ran at 23:10)
    from zoneinfo import ZoneInfo
    paris_end = now.astimezone(ZoneInfo("Europe/Paris")).replace(hour=23, minute=59, second=0, microsecond=0)
    rdv_today = min(now + dt.timedelta(hours=2), paris_end.astimezone(dt.timezone.utc))
    db.crm_tasks.insert_many([{"id": "t1", "status": "a_faire", "due_at": ago(1)}, {"id": "t2", "type": "rdv", "status": "a_faire", "due_at": rdv_today}])
    db.crm_prospects.insert_many([{"id": "p1", "stage": "proposition"}, {"id": "p2", "stage": "contacte"}])
    db.fidclic_invoices.insert_one({"id": "i1", "tenant_id": "A", "paid_at": now - dt.timedelta(minutes=30), "amount_paid": 79.0})
    U._cache.clear()
    td = D.dashboard_today(token_data=ADMIN)
    todo = {i["key"]: i for i in td["todo"]}
    check("à faire: trial ending (F), impayé (G)", todo["essai_7j"]["count"] == 1 and todo["impaye"]["count"] == 1)
    check("à faire: support urgent + unread, CRM overdue and today's rendez-vous", todo["support"]["count"] == 2 and todo["crm_retard"]["count"] == 1
          and todo["crm_rdv"]["count"] == 1)
    check("each line says what it opens", todo["essai_7j"]["action"] == {"list": "essai_7j"} and todo["support"]["action"]["href"] == "/admin/support")
    en = td["encaissements"]
    check("encaissé ce mois", en["month"] == 79.0 and en["month_invoices"] == 1)
    check("en retard: the impayé's € / month", en["late_count"] == 1 and en["late"] == 33.0)
    check("à encaisser sous 30 jours: running subscriptions, not the résilié one", en["upcoming_count"] == 3 and en["upcoming_30"] == 65 + 33 + 108)
    sp = td["support"]
    check("support: open, urgent, unread, waiting for us, first answer, satisfaction",
          sp["open"] == 2 and sp["urgent"] == 1 and sp["unread"] == 1 and sp["waiting_us"] == 1 and sp["first_response_hours"] == 2.0 and sp["satisfaction"] == 4.0)
    cr = td["crm"]
    check("CRM: active prospects, propositions, overdue, rendez-vous this week", cr["active"] == 2 and cr["proposals"] == 1 and cr["overdue"] == 1 and cr["rdv_7j"] == 1)
    lst = {r["id"] for r in D.dashboard_list("essai_7j", token_data=ADMIN)["rows"]}
    check("the « essais sous 7 jours » list", lst == {"F"})

    print("\nPermissions")
    db.platform_roles.insert_one({"id": "dash_only", "name": "Tableau de bord", "perms": {"dashboard": {"view": True, "edit": False}}})
    db.users.insert_one({"email": "dash@fidclic.com", "role": "fidclic_team", "platform_role": "dash_only", "first_name": "Dash"})
    tok = auth.create_access_token({"sub": "dash@fidclic.com", "role": "fidclic_team"})
    r = http("/api/admin/dashboard/today", tok).json()
    check("a member with only « Dashboard » gets no support / CRM / encaissements block", r["support"] is None and r["crm"] is None
          and r["encaissements"] is None and "support" not in {i["key"] for i in r["todo"]})
    check("…and cannot open the advanced analyses", http("/api/admin/analytics/deep/cohorts", tok).status_code == 403)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
