"""
Super admin › Plan Limits — what each plan unlocks (pricing grid), the server
lock on every section (HTTP, as the browser calls it), AI levels and quotas,
editing limits (overrides, back to default, reset), « Appliquer
automatiquement » off (old limits kept until renewal), offers created by the
super admin, the near-limit banner and email, priority support, wallet, and
the team / establishment caps.

Run: cd api && /usr/local/bin/python3 tests/test_plan_limits.py
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
    import models
    from fastapi import HTTPException
    from models import TokenData
    from features import plan_limits as PL, admin_commerces as AC, plans_public as PP, wallet_passes as WP

    db = server.db
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

    def http(method, url, token, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": "Bearer " + token}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def owner_token(email, tid):
        return auth.create_access_token({"sub": email, "role": "business_owner", "tenant_id": tid})

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    old = now - dt.timedelta(days=100)
    db.tenants.insert_many([
        {"id": "st", "slug": "st", "name": "Starter Café", "plan": "silver", "subscription_status": "active", "created_at": old,
         "subscription_period_end": now + dt.timedelta(days=12)},
        {"id": "pr", "slug": "pr", "name": "Pro Bistro", "plan": "gold", "subscription_status": "active", "created_at": old},
        {"id": "ai", "slug": "ai", "name": "Pro AI Brasserie", "plan": "vip", "subscription_status": "active", "created_at": old},
    ])
    db.users.insert_many([
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B."},
        {"email": "o@st.fr", "role": "business_owner", "tenant_id": "st", "first_name": "Sam"},
        {"email": "o@pr.fr", "role": "business_owner", "tenant_id": "pr", "first_name": "Paula"},
        {"email": "o@ai.fr", "role": "business_owner", "tenant_id": "ai", "first_name": "Ali"},
    ])
    ST, PR, AI = owner_token("o@st.fr", "st"), owner_token("o@pr.fr", "pr"), owner_token("o@ai.fr", "ai")
    OST = TokenData(email="o@st.fr", role="business_owner", tenant_id="st")

    print("\nWhat each plan unlocks (pricing grid)")
    f = {k: server.get_plan_features(k) for k in ("silver", "gold", "vip")}
    locked_on_starter = ["crm_advanced", "segmentation", "campaigns", "automations", "geo_proximity", "referral", "advanced_analytics"]
    check("Starter: card, wallet; the seven sections and AI locked",
          f["silver"]["wallet"] and not any(f["silver"][k] for k in locked_on_starter) and f["silver"]["ai_level"] == "none")
    check("Pro: every section, a little AI (analyses de base)", all(f["gold"][k] for k in locked_on_starter) and f["gold"]["ai_level"] == "basic")
    check("Pro AI: everything, analyses avancées, API", f["vip"]["ai_level"] == "advanced" and f["vip"]["api_access"] and f["vip"]["priority_support"])
    check("prices 39 / 79 / 129 €", [f[k]["price"] for k in ("silver", "gold", "vip")] == [39, 79, 129])
    pub = {p["key"]: p["features"] for p in PP.public_plans()["plans"]}
    check("the public grid reads the same switches", not pub["silver"]["campaigns"] and pub["gold"]["segments"] and pub["vip"]["api"])

    print("\nThe server lock (HTTP)")
    cases = {"/api/owner/segmentation/page": "segmentation", "/api/owner/analyses": "advanced_analytics",
             "/api/owner/insights/page": "advanced_analytics", "/api/owner/campaigns/page": "campaigns",
             "/api/owner/auto-campaigns/config": "automations", "/api/owner/push-wallet/scenarios": "automations",
             "/api/owner/referrals/overview": "referral", "/api/owner/geo/catchment": "geo_proximity",
             "/api/owner/history/activity": "crm_advanced", "/api/owner/segments": "crm_advanced",
             "/api/owner/copilot/page": "ai", "/api/owner/campaigns/ai-draft": "ai", "/api/owner/clients/export": "csv_export",
             "/api/owner/insights/templates/x": "campaigns"}
    check("every section maps to its switch", all(PL.rule_for(p) == k for p, k in cases.items()))
    check("the bell's alerts and the Google review link stay open",
          PL.rule_for("/api/owner/insights/alerts") is None and PL.rule_for("/api/owner/insights/google-review") is None)
    r = http("GET", "/api/owner/segmentation/page", ST)
    d = r.json().get("detail") or {}
    check("Starter → 403 PLAN_FEATURE_DISABLED with the plan that unlocks it",
          r.status_code == 403 and d.get("code") == "PLAN_FEATURE_DISABLED" and d["upgrade"]["label"] == "Pro" and d["upgrade"]["price"] == 79)
    check("Pro gets through the lock", http("GET", "/api/owner/segmentation/page", PR).status_code != 403)
    check("Starter: FIDCLIC AI locked, upgrade to Pro", http("GET", "/api/owner/copilot/page", ST).json()["detail"]["upgrade"]["key"] == "gold")
    check("no token → the endpoint's own 401, not the lock", http("GET", "/api/owner/segmentation/page", "x").status_code == 401)
    acc = http("GET", "/api/owner/plan-access", ST).json()
    check("plan-access: sections for the menu locks", acc["sections"]["campaigns"] is False and acc["sections"]["ai-assistant"] is False
          and "campaigns" in acc["locked"] and acc["ai_level"] == "none")

    print("\nAI levels and quotas")
    q = None
    for _ in range(models.AI_LEVEL_LIMITS["basic"]["copilot_questions_per_day"]):
        PL.record_ai("pr", "copilot_question")
    q = PL.ai_quota("pr", server.get_plan_features("gold"), "copilot_question")
    check("« analyses de base »: Copilot questions capped per day", q and q["code"] == "PLAN_QUOTA_REACHED" and q["upgrade"]["key"] == "vip")
    check("Pro AI: no per-feature cap", PL.ai_quota("ai", server.get_plan_features("vip"), "copilot_question") is None)
    for _ in range(50):
        PL.record_ai("ai", "ai_call")
    check("the daily AI request cap still applies", (PL.ai_quota("ai", server.get_plan_features("vip"), "ai_call") or {}).get("feature") == "ai_queries_per_day")
    check("recommendations: 3 on base, all on avancées", PL.ai_recommendation_limit("pr") == 3 and PL.ai_recommendation_limit("ai") is None)

    print("\nEditing limits")
    PL.save_settings(PL.SettingsIn(auto_apply=True, notify_near_limit=True, alert_threshold=80,
                                   alert_message="Vous avez utilisé {pourcentage}% de votre limite de {fonctionnalité}."), token_data=ADMIN)
    PL.save_limits("gold", PL.LimitsIn(features={"push_per_month": 7000, "segmentation": False}), token_data=ADMIN)
    check("an override applies (auto on)", server.features_for(db.tenants.find_one({"id": "pr"}))["push_per_month"] == 7000)
    check("a switch turned off locks the section at once", http("GET", "/api/owner/segmentation/page", PR).status_code == 403)
    PL.save_limits("gold", PL.LimitsIn(features={"segmentation": True, "push_per_month": 6000}), token_data=ADMIN)
    check("back to the default value: no override kept", (db.plan_settings.find_one({"plan": "gold"}) or {}).get("overrides") == {})
    check("history in plain French", PL.page(token_data=ADMIN)["history"][0]["text"].startswith("Modification des limites — Pro"))
    check("a wrong value is refused", status(lambda: PL.save_limits("gold", PL.LimitsIn(features={"ai_level": "super"}), token_data=ADMIN)) == 400)

    print("\n« Appliquer automatiquement » off")
    PL.save_settings(PL.SettingsIn(auto_apply=False, notify_near_limit=True, alert_threshold=80, alert_message="x {pourcentage}"), token_data=ADMIN)
    res = PL.save_limits("silver", PL.LimitsIn(features={"new_cards_per_month": 300}), token_data=ADMIN)
    st = db.tenants.find_one({"id": "st"})
    check("the business already on Starter keeps 500 until its renewal", res["kept_until_renewal"] == 1
          and server.features_for(st)["new_cards_per_month"] == 500 and abs((AC._aware(st["limits_pin"]["until"]) - (now + dt.timedelta(days=12))).total_seconds()) < 5)
    check("a new business on Starter gets 300", server.features_for({"id": "new", "plan": "silver"})["new_cards_per_month"] == 300)
    db.tenants.update_one({"id": "st"}, {"$set": {"limits_pin.until": now - dt.timedelta(minutes=1)}})
    check("after its renewal: the new limits", server.features_for(db.tenants.find_one({"id": "st"}))["new_cards_per_month"] == 300)
    check("next cycle: the monthly anniversary when no period end is known",
          PL.next_cycle({"created_at": now - dt.timedelta(days=40)}, now) > now)
    PL.save_settings(PL.SettingsIn(auto_apply=True, notify_near_limit=True, alert_threshold=80, alert_message="Vous avez utilisé {pourcentage}% de votre limite de {fonctionnalité}."), token_data=ADMIN)
    PL.reset(token_data=ADMIN)
    check("reset: defaults back, pins cleared", server.get_plan_features("silver")["new_cards_per_month"] == 500
          and "limits_pin" not in db.tenants.find_one({"id": "st"}))

    print("\nOffers created by the super admin")
    key = PL.create_plan(PL.NewPlanIn(label="Pro Restauration", tagline="Pour les restaurants", price=99, copy_from="gold"), token_data=ADMIN)["key"]
    check("a new offer with the limits it was copied from", server.get_plan_features(key)["segmentation"] is True and server.get_plan_features(key)["price"] == 99)
    check("same name refused", status(lambda: PL.create_plan(PL.NewPlanIn(label="Pro Restauration"), token_data=ADMIN)) == 409)
    AC.change_plan("pr", AC.PlanIn(plan=key), token_data=ADMIN)
    tp = db.tenants.find_one({"id": "pr"})
    check("given to a business: its label, its limits", server.plan_label(tp["plan"]) == "Pro Restauration" and server.features_for(tp)["price"] == 99)
    PL.save_limits(key, PL.LimitsIn(features={"wallet": False}), token_data=ADMIN)
    db.customers.insert_one({"id": "c1", "tenant_id": "pr", "barcode_id": "FT-PR1", "created_at": now})
    check("its switches apply (wallet off → no wallet button)", WP.wallet_config(barcode="FT-PR1")["in_plan"] is False)
    check("wallet pass refused", status(lambda: WP.download_apple_pass("FT-PR1")) == 403)
    check("cannot delete an offer a business is on", status(lambda: PL.delete_plan(key, token_data=ADMIN)) == 409)
    check("Starter/Pro names do not change", status(lambda: PL.save_meta("gold", PL.MetaIn(label="Business"), token_data=ADMIN)) == 400)
    PL.save_meta(key, PL.MetaIn(active=False), token_data=ADMIN)
    check("an inactive offer is never proposed as the upgrade",
          all(p["key"] != key for p in PL.plans_catalog(active_only=True)))
    AC.change_plan("pr", AC.PlanIn(plan="gold"), token_data=ADMIN)
    check("deleted once nobody is on it", status(lambda: PL.delete_plan(key, token_data=ADMIN)) == 200 and key not in server.custom_plans(refresh=True))

    print("\nNear-limit banner and email")
    db.customers.insert_many([{"id": f"s{i}", "tenant_id": "st", "created_at": now} for i in range(420)])   # 84 % of 500 cards
    al = PL.limit_alerts(token_data=OST)["alerts"]
    check("banner: the message with the percentage and the limit", al and al[0]["message"] == "Vous avez utilisé 84% de votre limite de cartes de fidélité."
          and al[0]["upgrade"]["label"] == "Pro")
    sent = []
    from services import mailer
    real = mailer.send
    mailer.send = lambda to, subject, html, text=None, to_name=None: (sent.append((to, subject)), {"sent": True})[1]
    PL.run_limit_alerts(now); PL.run_limit_alerts(now)
    mailer.send = real
    check("one email per limit and month, to the owner", len(sent) == 1 and sent[0][0] == "o@st.fr")

    print("\nPriority support, caps")
    for ch in ("_support_send_smtp", "_support_send_resend", "_support_send_formsubmit"):   # no real email from a test
        setattr(server, ch, lambda subject, message, ticket: (False, "not_configured"))
    server.submit_support_ticket(server.SupportTicketIn(subject="Aide", message="Bonjour", from_email="o@ai.fr"))
    server.submit_support_ticket(server.SupportTicketIn(subject="Aide", message="Bonjour", from_email="o@st.fr"))
    tk = server.list_support_tickets(token_data=ADMIN)["tickets"]
    check("Pro AI ticket: prioritaire, listed first, bell alert", tk[0]["priority"] == "prioritaire" and tk[0]["tenant_id"] == "ai"
          and db.platform_alerts.count_documents({"kind": "support_priority"}) == 1)
    check("Starter ticket: normale", any(t["tenant_id"] == "st" and t["priority"] == "normale" for t in tk))
    r = http("POST", "/api/owner/team-access/users", ST, json={"email": "new@st.fr", "first_name": "N", "last_name": "V", "role": "staff"})
    db.users.insert_one({"email": "second@st.fr", "role": "staff", "tenant_id": "st"})
    r = http("POST", "/api/owner/team-access/users", ST, json={"email": "third@st.fr", "first_name": "T", "last_name": "V", "role": "staff"})
    check("Starter: 2 team accounts, the 3rd is refused with the plan that has more", r.status_code == 403
          and (r.json().get("detail") or {}).get("upgrade", {}).get("label") == "Pro")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
