"""
AI meter + billing guardrails (user, 2026-11-01): every model call goes
through one gateway that writes what it cost (shop, feature, tokens, €),
refuses it when the shop's monthly AI budget (Starter 5 / Pro 10 / Pro AI 25 €,
raised by the super admin and then enforced) or the platform's daily cap
(20 €) is used up, slows abuse (per user, per request, input size, spikes)
and reuses an identical answer. Refused calls fall back to the template;
the owner is told « Limite IA du mois atteinte ».

Run: cd api && /usr/local/bin/python3 tests/test_ai_meter.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-meter")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["ANTHROPIC_API_KEY"] = "test-key"            # before server: its menu-photo helper reads it at import
for _k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(_k, None)
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import ai_meter as AM
    from services import llm, mailer

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "a", "name": "Café A", "plan": "silver", "subscription_status": "active", "is_active": True},
        {"id": "t2", "slug": "b", "name": "Salon B", "plan": "gold", "subscription_status": "active", "is_active": True},
        {"id": "t3", "slug": "c", "name": "Bar C", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.users.insert_many([
        {"email": "o@a.fr", "role": "business_owner", "tenant_id": "t1", "active": True, "first_name": "Ana"},
        {"email": "m@a.fr", "role": "manager", "tenant_id": "t1", "active": True},
        {"email": "o@c.fr", "role": "business_owner", "tenant_id": "t3", "active": True},
        {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "active": True},
    ])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, MANAGER, BOSS = tok("o@a.fr", "business_owner"), tok("m@a.fr", "manager"), tok("boss@fidclic.com", "super_admin", None)
    OWNER_AI = tok("o@c.fr", "business_owner", "t3")          # Pro AI: « Rédiger avec l'IA » is in its plan

    clock = [dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)]
    AM._now = lambda: clock[0]
    mails = []
    mailer.send = lambda to, subject, html, **kw: mails.append((to, subject)) or {"sent": True}

    sent = []
    usage = {"input_tokens": 1000, "output_tokens": 500, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}

    def fake_send(url, headers, body, timeout):
        sent.append(body)
        return 200, {"content": [{"type": "text", "text": "Bonjour"}], "usage": dict(usage)}
    AM._send = fake_send

    def reset():
        for c in ("ai_calls", "ai_spend", "ai_cache", "platform_alerts"):
            db[c].delete_many({})
        db.platform_settings.delete_many({"key": "ai_meter"})
        db.tenants.update_many({}, {"$unset": {"ai_budget_eur": ""}})
        sent.clear()
        mails.clear()
        usage.update(input_tokens=1000, output_tokens=500, cache_read_input_tokens=0, cache_creation_input_tokens=0)

    def ask(tid="t1", feature="campaign_ai", user="o@a.fr", text="Écris un message", **kw):
        with AM.scope(tenant_id=tid, feature=feature, user=user):
            return llm.complete("Tu es FidClic IA.", text, **kw)

    # ── prices ───────────────────────────────────────────────────────────
    print("Prix")
    rate = AM.settings()["usd_eur"]
    c = AM.cost_eur("anthropic", "claude-sonnet-5-5", {"in": 1000, "out": 500, "cache_read": 0, "cache_write": 0})
    check("Sonnet 5.5: 1 000 in + 500 out = (0,002 + 0,005) $ in €", abs(c - 0.007 * rate) < 1e-9)
    c = AM.cost_eur("anthropic", "claude-sonnet-5-5", {"in": 0, "out": 0, "cache_read": 1_000_000, "cache_write": 1_000_000})
    check("cache read 0,20 $/M and cache write 1,25 × input", abs(c - (0.20 + 2.5) * rate) < 1e-9)
    check("Haiku 5.5 is priced on its own row",
          abs(AM.cost_eur("anthropic", "claude-haiku-5-5", {"in": 1_000_000, "out": 0, "cache_read": 0, "cache_write": 0}) - 0.10 * rate) < 1e-9)
    unknown = AM.cost_eur("groq", "some-new-model", {"in": 1_000_000, "out": 0, "cache_read": 0, "cache_write": 0})
    check("an unknown model is never free: priced like the dearest row", unknown >= 4.0 * rate)
    u = AM.usage_of("groq", {"usage": {"prompt_tokens": 300, "completion_tokens": 40}}, 0, "")
    check("OpenAI-style usage read (Groq / NVIDIA)", u["in"] == 300 and u["out"] == 40 and not u["estimated"])
    u = AM.usage_of("anthropic", {}, 4000, "x" * 400)
    check("no usage sent back: estimated from the text (4 chars ≈ 1 token)", u["in"] == 1000 and u["out"] == 100 and u["estimated"])

    # ── budgets ──────────────────────────────────────────────────────────
    print("Budget par commerce")
    reset()
    check("defaults: Starter 5 €, Pro 10 €, Pro AI 25 €",
          (AM.limit_for("t1"), AM.limit_for("t2"), AM.limit_for("t3")) == (5.0, 10.0, 25.0))
    out = ask()
    check("a call answers and is written down", out == "Bonjour" and db.ai_calls.count_documents({}) == 1)
    row = db.ai_calls.find_one({}, {"_id": 0})
    check("the row: shop, feature, user, model, tokens, € and time",
          row["tenant_id"] == "t1" and row["feature"] == "campaign_ai" and row["user"] == "o@a.fr"
          and row["model"] == "claude-sonnet-5-5" and row["in"] == 1000 and row["out"] == 500
          and abs(row["eur"] - 0.007 * rate) < 1e-9 and row["status"] == "ok" and row["ms"] >= 0)
    check("no prompt and no answer kept in the meter (names, phones stay out)",
          not ({"system", "user_text", "prompt", "text", "answer", "body"} & set(row)) and "Écris" not in str(row))
    check("the month's spend follows", abs(AM.state("t1")["month_eur"] - 0.007 * rate) < 1e-9)

    usage["output_tokens"] = 1_000_000                       # one very long answer: ≈ 9 €
    ask()
    st = AM.state("t1")
    check("over 5 €: the shop is at its limit", st["month_eur"] > 5 and st["blocked"] == "budget")
    before = len(sent)
    out = ask()
    check("then the call is refused before the model: None (the caller's template answers)",
          out is None and len(sent) == before)
    check("…and written down as refused, at 0 €",
          db.ai_calls.count_documents({"status": "blocked", "reason": "budget", "eur": 0}) == 1)
    usage["output_tokens"] = 500
    check("another shop is untouched", ask("t2") == "Bonjour")
    kinds = [a["kind"] for a in db.platform_alerts.find({}, {"_id": 0, "kind": 1})]
    check("super admin alerted at 80 % and at 100 %, once each", kinds.count("ai_budget_80") == 1 and kinds.count("ai_budget_100") == 1)
    ask(), ask()
    kinds = [a["kind"] for a in db.platform_alerts.find({}, {"_id": 0, "kind": 1})]
    check("…never twice in the month", kinds.count("ai_budget_100") == 1)
    check("the super admins get the email", any(to == "boss@fidclic.com" for to, _s in mails))

    print("Le super admin relève la limite — et elle tient")
    r = http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS, json={"budget_eur": 50})
    check("PUT budget 50 € → 200", r.status_code == 200 or print(r.status_code, r.text[:300]))
    check("the new limit is the shop's", AM.limit_for("t1") == 50.0)
    usage["output_tokens"] = 500
    check("the shop answers again", ask() == "Bonjour")
    usage["output_tokens"] = 5_000_000                       # ≈ 46 € more: past the raised limit
    ask()
    check("the raised limit is enforced too", ask() is None and AM.state("t1")["blocked"] == "budget")
    check("back to the plan's default with null", http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS,
                                                         json={"budget_eur": None}).status_code == 200 and AM.limit_for("t1") == 5.0)
    check("a negative or absurd budget is refused (422)",
          http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS, json={"budget_eur": -1}).status_code == 422
          and http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS, json={"budget_eur": 100000}).status_code == 422)
    check("an unknown shop: 404", http("PUT", "/api/admin/ai/costs/shops/nope", headers=BOSS, json={"budget_eur": 9}).status_code == 404)
    check("an owner cannot raise their own limit (403)",
          http("PUT", "/api/admin/ai/costs/shops/t1", headers=OWNER, json={"budget_eur": 999}).status_code == 403)

    print("Réservation : jamais au-delà, même à plusieurs")
    reset()
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 4.9999}}, upsert=True)
    check("under the limit but the call could pass it: refused", ask(max_tokens=400) is None)
    check("nothing left reserved after a refusal", abs(db.ai_spend.find_one({"_id": AM.key_month("t1")})["eur"] - 4.9999) < 1e-9)
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 0}})
    ask(max_tokens=400)
    spent = db.ai_spend.find_one({"_id": AM.key_month("t1")})["eur"]
    check("after the call, the reservation is replaced by the real cost", abs(spent - 0.007 * rate) < 1e-9)

    print("Limite atteinte par petits appels (le dernier ne rentre plus)")
    reset()
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 4.999}}, upsert=True)
    check("the call that no longer fits is refused", ask(max_tokens=400) is None)
    check("the shop counts as at its limit though 4,999 € < 5 €", AM.state("t1")["blocked"] == "budget")
    check("…so the owner is told", AM.owner_alert("t1") is not None)
    check("…and the super admin, once", db.platform_alerts.count_documents({"kind": "ai_budget_100"}) == 1)
    ask(max_tokens=400)
    check("still once", db.platform_alerts.count_documents({"kind": "ai_budget_100"}) == 1)
    http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS, json={"budget_eur": 6})
    check("raised by the super admin: no longer at its limit", AM.state("t1")["blocked"] is None and ask() == "Bonjour")
    http("PUT", "/api/admin/ai/costs/shops/t1", headers=BOSS, json={"budget_eur": None})
    reset()
    db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"key": "ai_meter", "global_day_eur": 1.0}}, upsert=True)
    db.ai_spend.update_one({"_id": AM.key_day(None)}, {"$set": {"eur": 0.999}}, upsert=True)
    check("the platform's last call that does not fit: refused", ask("t3") is None)
    check("…the platform counts as paused, one alert", AM.state("t3")["blocked"] == "global"
          and db.platform_alerts.count_documents({"kind": "ai_global"}) == 1)

    print("Plafond global de la plateforme")
    reset()
    check("PUT settings: 1 € a day", http("PUT", "/api/admin/ai/costs/settings", headers=BOSS,
                                          json={"global_day_eur": 1.0}).status_code == 200)
    usage["output_tokens"] = 120_000                         # ≈ 1,1 €
    ask("t3")
    check("past the cap: every shop is paused", ask("t2") is None and ask("t3") is None)
    check("the super admin's own assistant too", ask(None, feature="admin_ai", user="boss@fidclic.com") is None)
    check("one alert for the day", db.platform_alerts.count_documents({"kind": "ai_global"}) == 1)
    clock[0] = dt.datetime(2026, 11, 11, 9, 0, tzinfo=UTC)
    usage["output_tokens"] = 500
    check("the next day it starts again", ask("t2") == "Bonjour")
    check("settings refused when absurd (422)",
          http("PUT", "/api/admin/ai/costs/settings", headers=BOSS, json={"global_day_eur": -5}).status_code == 422
          and http("PUT", "/api/admin/ai/costs/settings", headers=BOSS, json={"plan_budgets": {"silver": -1}}).status_code == 422)
    r = http("PUT", "/api/admin/ai/costs/settings", headers=BOSS, json={"plan_budgets": {"silver": 7}})
    check("plan defaults editable: Starter 7 €", r.status_code == 200 and AM.limit_for("t1") == 7.0)

    print("Jour et mois à l'heure de Paris")
    reset()
    clock[0] = dt.datetime(2026, 10, 31, 23, 30, tzinfo=UTC)     # 1 Nov 00:30 in Paris
    check("31 Oct 23:30 UTC is November in Paris", AM.key_month("t1").endswith("2026-11"))
    check("…and the 1st for the daily cap", AM.key_day(None).endswith("2026-11-01"))
    clock[0] = dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)

    print("Pic soudain")
    reset()
    for d in range(1, 15):                                    # 0,10 € a day for two weeks
        day = (clock[0] - dt.timedelta(days=d))
        db.ai_spend.update_one({"_id": AM.key_day("t3", day)}, {"$set": {"eur": 0.10}}, upsert=True)
    usage["output_tokens"] = 600_000                          # ≈ 5,5 € today: > 5 × 0,10 and > 20 % of 25 €
    ask("t3")
    check("a shop at many times its normal day is stopped for today",
          AM.state("t3")["blocked"] == "spike" and ask("t3") is None)
    check("one alert", db.platform_alerts.count_documents({"kind": "ai_spike"}) == 1)
    r = http("POST", "/api/admin/ai/costs/shops/t3/release", headers=BOSS)
    usage["output_tokens"] = 500
    check("« Débloquer » lets it go on today", r.status_code == 200 and ask("t3") == "Bonjour")
    clock[0] = dt.datetime(2026, 11, 10, 9, 5, tzinfo=UTC)
    check("…and stays released for the day", AM.state("t3")["blocked"] is None)
    reset()
    usage["output_tokens"] = 100_000                          # a new shop, first day, ≈ 0,9 €: under 20 % of its budget
    check("a new shop's normal first day is not a spike", ask("t3") == "Bonjour" and AM.state("t3")["blocked"] is None)

    print("Abus : vitesse, boucle, taille")
    reset()
    usage["output_tokens"] = 10
    lim = AM.settings()["user_per_min"]
    oks = sum(1 for _ in range(lim) if ask("t3", user="spam@b.fr") == "Bonjour")
    check(f"{lim} calls in a minute by one user go", oks == lim)
    check("the next one is refused (rate)", ask("t3", user="spam@b.fr") is None
          and db.ai_calls.count_documents({"reason": "rate"}) == 1)
    check("another user of the same shop is not slowed", ask("t3", user="calm@b.fr") == "Bonjour")
    clock[0] = clock[0] + dt.timedelta(minutes=2)
    check("a minute later it goes again", ask("t3", user="spam@b.fr") == "Bonjour")
    cap = AM.settings()["request_calls"]
    with AM.scope(tenant_id="t3", feature="copilot", user="loop@b.fr"):
        got = [llm.complete("s", f"tour {i}") for i in range(cap + 1)]
    check(f"one request: {cap} model calls at most (a tool loop stops)", got[:cap] == ["Bonjour"] * cap and got[cap] is None)
    big = "x" * (AM.settings()["input_chars"] + 1)
    check("a 50-page paste is refused (too_long), nothing sent", ask("t3", text=big) is None
          and db.ai_calls.count_documents({"reason": "too_long"}) == 1)
    sent.clear()
    ask("t3", max_tokens=50_000)
    check("max_tokens capped per feature", sent[-1]["max_tokens"] == AM.out_cap("campaign_ai"))
    check("…the menu photo keeps room for a long menu", AM.out_cap("menu_import") >= 4000)

    print("Cache")
    reset()
    a = ask("t3", text="Résume ma semaine", temperature=0.2)
    n = len(sent)
    b = ask("t3", text="Résume ma semaine", temperature=0.2)
    check("same question, low temperature: answered from the cache, not the model", a == b == "Bonjour" and len(sent) == n)
    check("…written down as cached, at 0 €", db.ai_calls.count_documents({"status": "cached", "eur": 0}) == 1)
    ask("t2", text="Résume ma semaine", temperature=0.2)
    check("never shared with another shop", len(sent) == n + 1)
    ask("t3", text="Écris une promo", temperature=0.7), ask("t3", text="Écris une promo", temperature=0.7)
    check("a creative call (« Rédiger », 0.7) is never cached: a new idea each time", len(sent) == n + 3)
    with AM.scope(tenant_id="t3", feature="copilot", user="o@c.fr"):
        llm.complete("S" * 9000, "question")
    check("the Copilote's long rules ask Anthropic to cache them", "cache_control" in sent[-1])
    ask("t3", text="autre")
    check("a one-off call does not (a cache write costs 25 % more)", "cache_control" not in sent[-1])

    print("Provider error")
    reset()
    AM._send = lambda url, headers, body, timeout: (500, {"error": "boom"})
    check("an error answers None", ask("t3") is None)
    row = db.ai_calls.find_one({}, {"_id": 0})
    check("…written down as error, at 0 €, reservation given back",
          row["status"] == "error" and row["eur"] == 0 and abs((db.ai_spend.find_one({"_id": AM.key_month("t3")}) or {}).get("eur", 0)) < 1e-9)
    AM._send = fake_send

    print("Tests forcés (_force_complete)")
    reset()
    llm._force_complete = lambda s, u: "forcé"
    got = [ask("t3", user="t@b.fr") for _ in range(AM.settings()["user_per_min"] + 5)]
    check("forced answers never trip the speed limit (the suite stays green)", set(got) == {"forcé"})
    db.ai_spend.update_one({"_id": AM.key_month("t3")}, {"$set": {"eur": 99}}, upsert=True)
    check("…but a shop at its limit is still refused", ask("t3") is None)
    llm._force_complete = None

    print("Le commerçant est prévenu")
    reset()
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 5.0}}, upsert=True)
    db.platform_settings.update_one({"key": "plan_limits"}, {"$set": {"notify_near_limit": False}}, upsert=True)
    al = http("GET", "/api/owner/limit-alerts", headers=OWNER).json()["alerts"]
    ai = [a for a in al if a["key"] == "ai_budget"]
    check("the dashboard banner says « Limite IA du mois atteinte » (even with the other alerts off)",
          ai and "Limite IA du mois atteinte" in ai[0]["message"])
    check("no euros shown to the merchant", "€" not in ai[0]["message"] and "used" not in ai[0])
    db.ai_spend.update_one({"_id": AM.key_month("t3")}, {"$set": {"eur": 25.0}}, upsert=True)
    r = http("POST", "/api/owner/campaigns/ai-draft", headers=OWNER_AI, json={"objective": "Faire revenir les clients", "segment": "all"})
    check("« Rédiger avec l'IA » says the limit plainly", r.status_code == 429 and "Limite IA du mois atteinte" in r.text)
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 1.0}})
    al = http("GET", "/api/owner/limit-alerts", headers=OWNER).json()["alerts"]
    check("under the limit: no AI banner", not [a for a in al if a["key"] == "ai_budget"])

    print("Branchement : chaque appel passe par le compteur")
    reset()
    llm._force_complete = None
    r = http("POST", "/api/owner/campaigns/ai-draft", headers=OWNER_AI, json={"objective": "Faire revenir les clients", "segment": "all"})
    row = db.ai_calls.find_one({}, {"_id": 0}) or {}
    check("an owner's HTTP call is billed to their shop, user and feature, without passing them",
          row.get("tenant_id") == "t3" and row.get("user") == "o@c.fr" and row.get("feature") == "campaign_ai")
    reset()
    with AM.scope(tenant_id="t3", feature="menu_import"):
        server._call_vision_anthropic(PNG, "image/png", "Lis ce menu")
    check("menu photo (server.py) metered", db.ai_calls.count_documents({"tenant_id": "t3", "feature": "menu_import"}) == 1)
    from services import ocr
    os.environ["OCR_PROVIDER"] = "anthropic"
    usage_txt = {"content": [{"type": "text", "text": '{"total": 12}'}], "usage": {"input_tokens": 10, "output_tokens": 5}}
    AM._send = lambda url, headers, body, timeout: (200, usage_txt)
    with AM.scope(tenant_id="t3", feature="invoice_ocr"):
        try:
            ocr._call_vision(PNG, "image/png")
        except Exception as exc:                  # the image helper may refuse the fake bytes: the meter is what counts
            print("    (ocr:", exc, ")")
    check("receipt OCR metered", db.ai_calls.count_documents({"feature": "invoice_ocr"}) >= 1)
    AM._send = fake_send
    check("a background job is billed to the shop it names", (ask("t2", feature="autopilot", user=None) and
                                                              db.ai_calls.count_documents({"tenant_id": "t2", "feature": "autopilot"}) == 1))

    print("Super admin › Coûts IA")
    reset()
    usage["output_tokens"] = 500
    ask("t1"), ask("t2", feature="copilot"), ask("t3", feature="copilot")
    r = http("GET", "/api/admin/ai/costs", headers=BOSS)
    check("200", r.status_code == 200 or print(r.status_code, r.text[:300]))
    d = r.json()
    shops = {s["tenant_id"]: s for s in d["shops"]}
    check("each shop: month €, limit, % and plan price for the margin",
          shops["t1"]["limit_eur"] == 5.0 and shops["t1"]["month_eur"] > 0 and "pct" in shops["t1"]
          and shops["t3"]["plan_price"] > 0 and "margin_pct" in shops["t3"])
    check("by feature", {f["feature"] for f in d["by_feature"]} >= {"campaign_ai", "copilot"})
    check("30 days of spend for the chart", len(d["by_day"]) == 30)
    check("today, month, cap, calls and refusals", all(k in d["summary"] for k in ("today_eur", "month_eur", "global_day_eur", "calls_today", "blocked_today", "paused")))
    check("the settings come along", d["settings"]["plan_budgets"]["vip"] == 25.0 and d["settings"]["global_day_eur"] == 20.0)
    check("owners and managers: refused", http("GET", "/api/admin/ai/costs", headers=OWNER).status_code in (401, 403)
          and http("GET", "/api/admin/ai/costs", headers=MANAGER).status_code in (401, 403))
    check("each change by the super admin is in the audit log",
          db.audit_logs.count_documents({"action": {"$regex": "^ai_meter\\."}}) >= 1 or db.audit_log.count_documents({"action": {"$regex": "^ai_meter\\."}}) >= 1)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
