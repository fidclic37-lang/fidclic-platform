"""
AI routing (user, 2026-11-04): every AI job has its own model — small jobs on
Sonnet, everything else on Opus, Haiku in no default. An answer that fails the
checks goes once to the next model up (Sonnet → Opus → Fable), then the
template. At 80 % of its month the shop is told and nothing else changes. A
model changed in Super admin › FIDCLIC AI › Routage applies at once, is
audited, can be undone in one click, and the Golden set tests what is set.

Run: cd api && /usr/local/bin/python3 tests/test_ai_routing.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-routing")
os.environ.setdefault("DISABLE_SEED", "1")
os.environ["ANTHROPIC_API_KEY"] = "test-key"            # before server: its helpers read it at import
for _k in ("LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY", "OCR_MODEL",
           "ANTHROPIC_MODEL", "ANTHROPIC_VISION_MODEL", "GOLDEN_ROUTES"):
    os.environ.pop(_k, None)
PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
SONNET, OPUS, FABLE, HAIKU = "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-5-5"
FR = "Bonjour, vous avez une belle semaine devant vous et la boutique est prête pour vous."
EN = "Hello, this is your week and you are ready for the best results with your shop."
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:600])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import ai_meter as AM, ai_routing as R, golden_set as GS, platform_access as PA
    from services import llm, mailer

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "a", "name": "Café <A>", "plan": "vip", "subscription_status": "active", "is_active": True},
        {"id": "t2", "slug": "b", "name": "Salon B", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.platform_roles.insert_many([
        {"id": "ai_read", "name": "IA lecture", "perms": {"ai": {"view": True, "edit": False}}},
        {"id": "ai_edit", "name": "IA modif", "perms": {"ai": {"view": True, "edit": True}}},
    ])
    db.users.insert_many([
        {"email": "o@a.fr", "role": "business_owner", "tenant_id": "t1", "active": True, "first_name": "Ana"},
        {"email": "ex@a.fr", "role": "business_owner", "tenant_id": "t1", "active": False},
        {"email": "m@a.fr", "role": "manager", "tenant_id": "t1", "active": True},
        {"email": "o@b.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
        {"email": "boss@fidclic.com", "role": "super_admin", "active": True},
        {"email": "read@fidclic.com", "role": "fidclic_team", "platform_role": "ai_read", "active": True},
        {"email": "edit@fidclic.com", "role": "fidclic_team", "platform_role": "ai_edit", "active": True},
    ])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, MANAGER, BOSS = tok("o@a.fr", "business_owner", "t1"), tok("m@a.fr", "manager", "t1"), tok("boss@fidclic.com", "super_admin")
    READER, EDITOR = tok("read@fidclic.com", "fidclic_team"), tok("edit@fidclic.com", "fidclic_team")

    clock = [dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)]
    AM._now = lambda: clock[0]
    mails = []
    mailer.send = lambda to, subject, html, **kw: mails.append((to, subject, html)) or {"sent": True}

    asked = []
    script = {}

    def fake_send(url, headers, body, timeout):
        m = body.get("model")
        asked.append(m)
        a = script.get(m, FR)
        if isinstance(a, int):
            return a, {"error": "boom"}
        a = a(body) if callable(a) else a
        if "api.anthropic.com" in url:
            return 200, {"content": [{"type": "text", "text": a}], "usage": {"input_tokens": 100, "output_tokens": 50}}
        return 200, {"choices": [{"message": {"content": a}}], "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
    AM._send = fake_send

    def reset(**answers):
        for c in ("ai_calls", "ai_spend", "ai_cache", "ai_blocks", "ai_rate", "ai_route_stats", "platform_alerts", "copilot_chats", "golden_runs", "audit_logs"):
            db[c].delete_many({})
        db.platform_settings.delete_many({"key": {"$in": ["ai_meter", "ai_routing"]}})
        db.platform_settings.insert_one({"key": "ai_meter", "shop_day_share": 1.0})
        db.tenants.update_many({}, {"$unset": {"ai_budget_eur": ""}})
        asked.clear()
        mails.clear()
        script.clear()
        script.update({{"sonnet": SONNET, "opus": OPUS, "fable": FABLE, "haiku": HAIKU}[k]: v for k, v in answers.items()})

    def stat(feature, kind):
        return sum(int(d.get(kind) or 0) for d in db.ai_route_stats.find({"feature": feature}))

    # ------------------------------------------------------------------
    print("La table : petits travaux sur Sonnet, le reste sur Opus")
    reset()
    for f in ("copilot", "campaign_ai", "automation_ai", "autopilot"):
        check(f"{f} → Opus", R.model_for(f) == OPUS)
    for f in ("conseiller", "support", "campaign_recap", "copilot_memory", "admin_ai", "invoice_ocr", "menu_import"):
        check(f"{f} → Sonnet", R.model_for(f) == SONNET)
    check("a job nobody listed → Opus (« baaki kaam »)", R.model_for("nouveau_truc") == OPUS and R.model_for(None) == OPUS)
    check("Haiku is in no default", HAIKU not in R.DEFAULTS.values() and R.OTHERS != HAIKU)
    check("every job the code calls has a row", {"copilot", "campaign_ai", "automation_ai", "autopilot", "conseiller", "support",
                                                 "campaign_recap", "copilot_memory", "admin_ai", "invoice_ocr", "menu_import"} <= set(R.DEFAULTS))
    check("the ladder: Haiku → Sonnet → Opus → Fable → nothing",
          R.stronger(HAIKU) == SONNET and R.stronger(SONNET) == OPUS and R.stronger(OPUS) == FABLE and R.stronger(FABLE) is None)
    check("a model off the ladder has nothing above it", R.stronger("claude-old") is None and R.stronger(None) is None)
    db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {"routes": {"support": OPUS, "copilot": "claude-mythos-5", "conseiller": 7}}}, upsert=True)
    check("a saved model is used", R.model_for("support") == OPUS)
    check("a tampered value in the database falls back to the default",
          R.model_for("copilot") == OPUS and R.model_for("conseiller") == SONNET)
    reset()

    # ------------------------------------------------------------------
    print("Les contrôles d'une réponse")
    p = R.problems
    check("a clean French answer", p("copilot", FR, "s", "u") == [])
    check("nothing to check", p("copilot", "", "s", "u") == [] and p("copilot", None, "s", "u") == [])
    check("a short answer without any common word is not « English »", p("copilot", "42.", "s", "u") == [] and p("campaign_ai", "Happy hour ce soir !", "s", "u") == [])
    check("English", p("copilot", EN, "s", "u") == ["anglais"])
    check("English asked by the owner is fine", p("campaign_ai", EN, "s", "Écris le message en anglais pour les touristes") == [])
    check("a phone in a Copilote answer", p("copilot", "Vous pouvez la joindre au 06 12 34 56 78 pour la relancer.", "s", "u") == ["contact"])
    check("+33 too", "contact" in p("copilot", "Son numéro est le +33 6 12 34 56 78 et vous pouvez le noter.", "s", "u"))
    check("an e-mail in a Copilote answer", p("copilot", "Son adresse est julie@example.fr et vous pouvez lui écrire.", "s", "u") == ["contact"])
    check("FidClic's own address is fine", p("copilot", "Écrivez à support@fidclic.com pour votre question.", "s", "u") == [])
    check("a phone even if the prompt had it (Copilote: never)", p("copilot", "Appelez le 06 12 34 56 78 pour la relancer.", "s", "tel 06 12 34 56 78") == ["contact"])
    words = ("et " * 240).strip()
    check("240 words pass", p("copilot", words, "s", "u") == [])
    check("241 words are too long", p("copilot", words + " et", "s", "u") == ["trop_long"])
    check("an amount never read (≥ 20 €)", p("copilot", "Votre CA est de 3 400 € sur la période et il progresse.", "s", "ca: 120") == ["montant"])
    check("an amount read in the prompt", p("copilot", "Votre CA est de 3 400 € sur la période et il progresse.", "s", "ca: 3400") == [])
    check("an amount with cents, read", p("copilot", "Votre panier est de 21,50 € et il progresse pour vous.", "s", "panier 21.5") == [])
    check("the sum of two figures read", p("copilot", "Les deux font 1 500 € sur la période pour vous.", "s", "a 1000 b 500") == [])
    check("the difference of two figures read", p("copilot", "Vous gagnez 500 € de plus que le mois dernier.", "s", "a 1500 b 1000") == [])
    check("a small offer idea (< 20 €) is not « never read »", p("copilot", "Proposez une remise de 5 € pour les faire revenir.", "s", "u") == [])
    check("exactly 20 € never read", p("copilot", "Proposez une remise de 20 € pour les faire revenir.", "s", "u") == ["montant"])
    check("several faults, each named", set(p("copilot", EN + " Call 06 12 34 56 78 for 900 €.", "s", "u")) == {"anglais", "contact", "montant"})
    check("Rédiger: a phone the owner gave is fine", p("campaign_ai", "Réservez au 02 47 00 00 00 pour votre table.", "s", "tel 02 47 00 00 00") == [])
    check("Rédiger: a phone it invented is not", p("campaign_ai", "Réservez au 02 47 00 00 00 pour votre table.", "s", "u") == ["contact"])
    check("Rédiger: an amount idea is not checked", p("campaign_ai", "Une remise de 50 € pour vous cette semaine.", "s", "u") == [])
    check("Support may quote an address from the docs", p("support", "Écrivez à aide@exemple.fr et la réponse vous parviendra.", "s", "u") == [])
    check("Support in English is not", p("support", EN, "s", "u") == ["anglais"])
    check("jobs that return data are not read", p("copilot_memory", EN, "s", "u") == [] and p("admin_ai", EN, "s", "u") == [] and p("invoice_ocr", EN, "s", "u") == [])
    check("a job nobody listed is not read", p("nouveau_truc", EN, "s", "u") == [])

    # ------------------------------------------------------------------
    print("Des chiffres piégés ne font jamais tomber une réponse")
    series = " ".join(str(i) for i in range(100, 1000)) * 2
    check("a long run of 3-digit numbers in the prompt", p("copilot", "Votre CA est de 3 400 € et il progresse.", "s", series) == ["montant"])
    check("a 400-digit number", p("copilot", "Votre CA est de 3 400 € et il progresse.", "s", "9" * 400) == ["montant"])
    check("a 5 000-digit number", p("copilot", "Votre CA est de 3 400 € et il progresse.", "s", "9" * 5000) == ["montant"])
    check("a 5 000-digit amount in the answer", p("copilot", "Votre CA est de " + "9" * 5000 + " € et il progresse pour vous.", "s", "u") == [])
    reset(opus=FR)
    real_problems = R.problems

    def boom(*a):
        raise RuntimeError("bug in a check")
    R.problems = boom
    check("a check that crashes never loses the answer", llm.complete("s", "u", feature="copilot", tenant_id="t1") == FR and asked == [OPUS])
    R.problems = real_problems

    print("Chaque travail part sur son modèle")
    reset()
    check("Copilote on Opus", llm.complete("s", "u", feature="copilot", tenant_id="t1") == FR and asked == [OPUS])
    asked.clear()
    check("Conseiller on Sonnet", llm.complete("s", "u", feature="conseiller", tenant_id="t1") == FR and asked == [SONNET])
    asked.clear()
    os.environ["LLM_MODEL"] = "claude-old-name"
    llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    check("the table wins over LLM_MODEL", asked == [SONNET])
    os.environ.pop("LLM_MODEL")
    asked.clear()
    check("the bill says which model", db.ai_calls.find_one({"feature": "copilot"})["model"] == OPUS
          and db.ai_calls.find_one({"feature": "conseiller"})["model"] == SONNET)

    asked.clear()
    with AM.scope(tenant_id="t1", feature="conseiller"):
        llm.complete("s", "u")
    check("a job named by the meter's scope has its model too", asked == [SONNET], asked)
    reset(sonnet=EN)
    with AM.scope(tenant_id="t1", feature="conseiller"):
        check("…and its checks", llm.complete("s", "u") == FR and asked == [SONNET, OPUS], asked)
    reset()
    r = server._call_vision_anthropic(PNG, "image/png", "Lis ce menu")
    check("the menu photo on the table's model", asked == [SONNET], (r, asked))
    asked.clear()
    db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {"routes": {"menu_import": OPUS, "campaign_recap": OPUS, "invoice_ocr": OPUS}}}, upsert=True)
    server._call_vision_anthropic(PNG, "image/png", "Lis ce menu")
    check("…and follows a change", asked == [OPUS])
    asked.clear()
    server._call_anthropic("Résume la campagne")
    check("the campaign recap follows the table", asked == [OPUS])
    asked.clear()
    from services import ocr
    os.environ["ANTHROPIC_API_KEY"] = "test-key"
    script[OPUS] = '{"total": 12}'
    ocr._call_vision(PNG, "image/png")
    check("the invoice photo follows the table", asked == [OPUS], asked)

    # ------------------------------------------------------------------
    print("Une réponse ratée monte une fois")
    reset(sonnet=EN)
    t = llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    check("Sonnet fails → Opus answers", t == FR and asked == [SONNET, OPUS], (t, asked))
    check("the climb is counted, with its reason", stat("conseiller", "escalated") == 1
          and db.ai_route_stats.find_one({"feature": "conseiller"})["why"] == {"anglais": 1})
    check("both calls are billed", db.ai_calls.count_documents({"feature": "conseiller", "status": "ok"}) == 2
          and float(db.ai_spend.find_one({"_id": AM.key_month("t1")})["eur"]) > 0)
    check("the learning log gets the answer that was used", (llm.last_call() or {}).get("text") == FR and llm.last_call()["model"] == OPUS)

    reset(sonnet=EN, opus=EN)
    t = llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    check("both fail → None (the template), one climb only", t is None and asked == [SONNET, OPUS], (t, asked))
    check("counted as refused", stat("conseiller", "rejected") == 1 and stat("conseiller", "escalated") == 1)
    check("the refused text is not left for the learning log", llm.last_call() is None)

    reset(opus=EN)
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("Opus fails → Fable once", t == FR and asked == [OPUS, FABLE], (t, asked))
    check("Fable's bill is on the row", db.ai_calls.find_one({"model": FABLE})["feature"] == "copilot")

    reset(opus=EN, fable=EN)
    check("Opus and Fable fail → None", llm.complete("s", "u", feature="copilot", tenant_id="t1") is None and asked == [OPUS, FABLE])

    reset(fable=EN)
    db.platform_settings.update_one({"key": "ai_routing"}, {"$set": {"routes": {"copilot": FABLE}}}, upsert=True)
    check("already on Fable: nothing above → None", llm.complete("s", "u", feature="copilot", tenant_id="t1") is None and asked == [FABLE])

    reset(sonnet=EN)
    t = llm.complete("s", "u", feature="copilot_memory", tenant_id="t1")
    check("a job without checks never climbs", t == EN and asked == [SONNET], asked)

    reset(opus=503)
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("a provider error is not a climb: the default model answers", t == FR and asked == [OPUS, SONNET] and stat("copilot", "escalated") == 0, asked)

    reset(opus=EN, fable=503)
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("Fable down during a climb → None, no weaker model", t is None and asked == [OPUS, FABLE], asked)

    reset()
    script[OPUS] = lambda body: json.dumps({"outils": [{"nom": "x", "args": {}}]})
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1", read=lambda raw: None)
    check("`read` says there is nothing to check (a tool call)", asked == [OPUS] and "outils" in t)
    reset(opus=json.dumps({"reponse": EN}))
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1", read=lambda raw: json.loads(raw)["reponse"])
    check("`read` picks the answer out of its wrapper", asked == [OPUS, FABLE], asked)
    reset()
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1", read=lambda raw: 1 / 0)
    check("a `read` that crashes never loses the answer", t == FR)

    reset(opus=EN)
    db.tenants.update_one({"id": "t1"}, {"$set": {"ai_budget_eur": 0.01}})
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("the climb pays the same budget: refused when it cannot", t is None and asked == [OPUS], asked)

    print("Sans Claude en premier")
    reset(opus=FR)
    os.environ["LLM_PROVIDER"], os.environ["GROQ_API_KEY"] = "groq", "g"
    groq_says = {"llama-3.3-70b-versatile": EN}
    script.update(groq_says)
    t = llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    check("Groq keeps its own model, then the climb goes to Claude", asked == ["llama-3.3-70b-versatile", OPUS] and t == FR, asked)
    reset()
    script["llama-3.3-70b-versatile"] = EN
    key = os.environ.pop("ANTHROPIC_API_KEY")
    t = llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    check("no Claude key: no climb, None", t is None and asked == ["llama-3.3-70b-versatile"], asked)
    os.environ["ANTHROPIC_API_KEY"] = key
    os.environ.pop("LLM_PROVIDER")
    os.environ.pop("GROQ_API_KEY")

    print("Le faux modèle des tests")
    reset()
    seen = []

    def fake(system, user):
        seen.append(llm.asked_model())
        return EN if llm.asked_model() == OPUS else FR
    llm._force_complete = fake
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("forced replies climb too and can tell the model", t == FR and seen == [OPUS, FABLE], seen)
    llm._force_complete = None

    # ------------------------------------------------------------------
    print("Copilote et Rédiger, par les vrais écrans")
    reset(opus=json.dumps({"reponse": EN}), fable=json.dumps({"reponse": FR}))
    r = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Mes chiffres ?"})
    check("Copilote: English from Opus, French from Fable", r.status_code == 200 and FR in r.text and asked == [OPUS, FABLE], (r.text, asked))
    reset(opus=json.dumps({"reponse": "Votre CA est de 98 765 € ce mois-ci et il progresse."}), fable=json.dumps({"reponse": "Votre CA est de 91 111 € ce mois-ci et il progresse."}))
    r = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Mes chiffres ?"})
    check("Copilote: two invented amounts → the facts answer, no invented figure", r.status_code == 200 and "98 765" not in r.text and "91 111" not in r.text
          and asked == [OPUS, FABLE] and r.json().get("source") != "model", (r.text, asked))
    reset()

    rounds = []

    def tools_then_answer(body):
        rounds.append(1)
        return json.dumps({"outils": [{"nom": "resume_periode", "args": {}}]}) if len(rounds) == 1 else json.dumps({"reponse": FR})
    script[OPUS] = tools_then_answer
    r = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Mes chiffres ?"})
    check("Copilote: a tool round is not a failed answer", asked == [OPUS, OPUS] and stat("copilot", "escalated") == 0, (asked, r.text))

    draft = "Titre : Vous nous manquez\nMessage : Passez nous voir cette semaine, on vous attend avec plaisir."
    english = "Title: We miss you\nMessage: Come and see us this week, you are the best and we are waiting for you with the best."
    reset(opus=english, fable=draft)
    r = http("POST", "/api/owner/campaigns/ai-draft", OWNER, json={"objective": "Faire revenir les clients"})
    check("Rédiger: Fable's French draft comes back", r.status_code == 200 and r.json().get("title") == "Vous nous manquez" and asked == [OPUS, FABLE], (r.status_code, r.text[:200], asked))
    reset(opus=english, fable=english)
    r = http("POST", "/api/owner/campaigns/ai-draft", OWNER, json={"objective": "Faire revenir les clients"})
    check("Rédiger: both English → the usual « could not write », no English text", r.status_code == 503 and "We miss" not in r.text, (r.status_code, r.text[:200]))

    # ------------------------------------------------------------------
    print("80 % du budget : le commerce est prévenu, rien d'autre ne change")
    reset()
    db.tenants.update_one({"id": "t1"}, {"$set": {"ai_budget_eur": 10.0}})
    db.ai_spend.insert_one({"_id": AM.key_month("t1"), "eur": 7.0})
    llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("below 80 %: nobody told", [m for m in mails if m[0] == "o@a.fr"] == [])
    r = http("GET", "/api/owner/limit-alerts", OWNER)
    check("below 80 %: no banner", not [a for a in r.json()["alerts"] if a.get("what") == "FidClic IA"], r.text)
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 8.0}})
    asked.clear()
    t = llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("at 80 %: same model, same answer", t == FR and asked == [OPUS])
    own = [m for m in mails if m[0] == "o@a.fr"]
    check("the owner gets one e-mail", len(own) == 1, mails)
    check("only the active owner of this shop", not [m for m in mails if m[0] in ("ex@a.fr", "m@a.fr", "o@b.fr")], mails)
    check("the shop's name is escaped in it", "<A>" not in own[0][2] and "&lt;A&gt;" in own[0][2])
    check("the owner's e-mail shows no euro (FidClic's own cost)", "€" not in own[0][1] + own[0][2], own)
    check("the super admins' alert still goes", [m for m in mails if m[0] == "boss@fidclic.com"])
    llm.complete("s2", "u", feature="copilot", tenant_id="t1")
    check("one e-mail for the month, not one per call", len([m for m in mails if m[0] == "o@a.fr"]) == 1)
    alert = next((a for a in http("GET", "/api/owner/limit-alerts", OWNER).json()["alerts"] if a.get("what") == "FidClic IA"), None)
    check("the banner says 80 %, and that all goes on", alert and alert["key"] == "ai_budget_80" and alert["pct"] >= 80 and "continue" in alert["message"] and "€" not in alert["message"], alert)
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 9.9}})
    asked.clear()
    t = llm.complete("s3", "u", feature="copilot", tenant_id="t1")
    check("at 99 %: still the same model", asked == [OPUS] and t == FR)
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 10.0}})
    llm.complete("s4", "u", feature="copilot", tenant_id="t1")
    alert = next((a for a in http("GET", "/api/owner/limit-alerts", OWNER).json()["alerts"] if a.get("what") == "FidClic IA"), None)
    check("at 100 %: the limit banner as before", alert and alert["key"] == "ai_budget" and alert["pct"] == 100, alert)
    db.tenants.update_one({"id": "t1"}, {"$set": {"ai_budget_eur": 12.0}})
    db.ai_spend.update_one({"_id": AM.key_month("t1")}, {"$set": {"eur": 10.0}, "$unset": {"full": ""}})
    mails.clear()
    llm.complete("s5", "u", feature="copilot", tenant_id="t1")
    check("a raised limit, 80 % again: told again", len([m for m in mails if m[0] == "o@a.fr"]) == 1, mails)
    clock[0] = dt.datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
    alert = next((a for a in http("GET", "/api/owner/limit-alerts", OWNER).json()["alerts"] if a.get("what") == "FidClic IA"), None)
    check("a new month: no banner", alert is None, alert)
    clock[0] = dt.datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    reset()
    db.tenants.update_one({"id": "t1"}, {"$set": {"ai_budget_eur": 10.0}})
    db.ai_spend.insert_one({"_id": AM.key_month("t1"), "eur": 8.5})
    real_send = mailer.send

    def broken(*a, **k):
        raise RuntimeError("smtp down")
    mailer.send = broken
    check("a mail server down never loses the answer", llm.complete("s", "u", feature="copilot", tenant_id="t1") == FR)
    mailer.send = real_send
    db.tenants.update_one({"id": "t1"}, {"$unset": {"ai_budget_eur": ""}})
    check("a shop with no spend: no banner", AM.owner_alert("t2") is None)
    check("no shop: no banner", AM.owner_alert(None) is None)

    # ------------------------------------------------------------------
    print("Super admin › Routage")
    reset()
    for who, h, code in (("owner", OWNER, 403), ("manager", MANAGER, 403), ("nobody", {}, 401)):
        r = http("GET", "/api/admin/ai/routing", h)
        check(f"{who} cannot read it ({code})", r.status_code in (code, 401, 403), r.status_code)
        r = http("PUT", "/api/admin/ai/routing/copilot", h, json={"model": SONNET})
        check(f"{who} cannot change it", r.status_code in (401, 403) and R.model_for("copilot") == OPUS, r.status_code)
    PA._cache.clear()
    check("a team member with « Voir » reads", http("GET", "/api/admin/ai/routing", READER).status_code == 200)
    r = http("PUT", "/api/admin/ai/routing/copilot", READER, json={"model": SONNET})
    check("…but cannot change", r.status_code == 403 and R.model_for("copilot") == OPUS, r.status_code)
    r = http("POST", "/api/admin/ai/routing/copilot/revert", READER)
    check("…nor undo", r.status_code == 403, r.status_code)
    r = http("PUT", "/api/admin/ai/routing/copilot", EDITOR, json={"model": SONNET})
    check("a team member with « Modifier » changes", r.status_code == 200 and R.model_for("copilot") == SONNET, r.text)
    reset()

    d = http("GET", "/api/admin/ai/routing", BOSS).json()
    rows = {x["feature"]: x for x in d["routes"]}
    check("every job has a row, plus « Autres »", set(R.DEFAULTS) | {"autre"} == set(rows), sorted(rows))
    check("each row: model, default, what comes above", rows["copilot"]["model"] == OPUS and rows["copilot"]["default"] == OPUS
          and rows["copilot"]["above"] == FABLE and rows["support"]["model"] == SONNET and rows["support"]["above"] == OPUS)
    check("the models offered are the ladder, with their prices", [m["id"] for m in d["models"]] == [HAIKU, SONNET, OPUS, FABLE]
          and d["models"][2]["in"] == 4.0 and d["models"][3]["out"] == 50.0, d["models"])
    check("Claude is in front: the table is live", d["provider"] == "anthropic" and d["active"] is True)
    os.environ["LLM_PROVIDER"] = "groq"
    d2 = http("GET", "/api/admin/ai/routing", BOSS).json()
    check("Groq in front: the page says the table sleeps", d2["provider"] == "groq" and d2["active"] is False)
    os.environ.pop("LLM_PROVIDER")

    r = http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": SONNET})
    check("a change is saved", r.status_code == 200, r.text)
    asked.clear()
    llm.complete("s", "u", feature="copilot", tenant_id="t1")
    check("the very next call uses it", asked == [SONNET], asked)
    log = db.audit_logs.find_one({"action": "ai_routing.change"}) or {}
    check("audited: who, from, to", log.get("actor") == "boss@fidclic.com" and log.get("target") == "copilot"
          and (log.get("meta") or {}).get("from") == OPUS and (log.get("meta") or {}).get("to") == SONNET, log)
    d = http("GET", "/api/admin/ai/routing", BOSS).json()
    row = {x["feature"]: x for x in d["routes"]}["copilot"]
    check("the page shows the previous model", row["previous"] == OPUS and row["model"] == SONNET and row["changed"] is True)
    check("the page asks for a Golden run", d["golden"]["stale"] is True, d["golden"])
    r = http("POST", "/api/admin/ai/routing/copilot/revert", BOSS)
    check("one click back", r.status_code == 200 and R.model_for("copilot") == OPUS, r.text)
    check("the undo is audited", db.audit_logs.find_one({"action": "ai_routing.revert", "target": "copilot"}))
    r = http("POST", "/api/admin/ai/routing/copilot/revert", BOSS)
    check("undo again = forward again", r.status_code == 200 and R.model_for("copilot") == SONNET)
    r = http("POST", "/api/admin/ai/routing/support/revert", BOSS)
    check("nothing to undo → 409", r.status_code == 409, r.status_code)
    r = http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": OPUS})
    before = db.audit_logs.count_documents({"action": "ai_routing.change"})
    r = http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": OPUS})
    check("the same model again changes nothing", r.status_code == 200 and db.audit_logs.count_documents({"action": "ai_routing.change"}) == before)

    r = http("PUT", "/api/admin/ai/routing/inconnu", BOSS, json={"model": OPUS})
    check("an unknown job → 404", r.status_code == 404, r.status_code)
    r = http("PUT", "/api/admin/ai/routing/routes.$set", BOSS, json={"model": OPUS})
    check("a job name with database syntax → 404", r.status_code == 404, r.status_code)
    for bad in ("claude-mythos-5", "gpt-5", "", None, {"$ne": 1}, ["x"], 7):
        r = http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": bad})
        check(f"a model off the list refused: {bad!r}", r.status_code in (400, 422), r.status_code)
    r = http("PUT", "/api/admin/ai/routing/autre", BOSS, json={"model": SONNET})
    check("« Autres » can change", r.status_code == 200 and R.model_for("nouveau_truc") == SONNET, r.text)
    r = http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": HAIKU})
    check("Haiku can be chosen by hand", r.status_code == 200 and R.model_for("copilot") == HAIKU, r.text)

    print("Les chiffres de la page")
    reset(sonnet=EN)
    llm.complete("s", "u", feature="conseiller", tenant_id="t1")
    llm.complete("s2", "u", feature="support", tenant_id="t1")
    db.ai_calls.insert_one({"feature": "conseiller", "model": SONNET, "status": "ok", "eur": 9.0, "at": clock[0] - dt.timedelta(days=31)})
    db.ai_route_stats.insert_one({"_id": "2026-09-01|conseiller", "day": "2026-09-01", "feature": "conseiller", "escalated": 50})
    rows = {x["feature"]: x for x in http("GET", "/api/admin/ai/routing", BOSS).json()["routes"]}
    r0 = rows["conseiller"]
    check("30 days of calls and euros, by job", r0["calls"] == 2 and 0 < r0["eur"] < 1, r0)
    check("climbs and refusals, 30 days only", r0["escalated"] == 1 and r0["rejected"] == 0 and r0["why"] == {"anglais": 1}, r0)
    check("a quiet job shows zeros", rows["autopilot"]["calls"] == 0 and rows["autopilot"]["eur"] == 0 and rows["autopilot"]["escalated"] == 0)
    body = http("GET", "/api/admin/ai/routing", BOSS).text
    check("no prompt, no answer on the page", FR not in body and EN not in body)
    check("the Coûts IA page does not count climbs as calls", next(f for f in http("GET", "/api/admin/ai/costs", BOSS).json()["by_feature"] if f["feature"] == "conseiller")["calls"] == 2)

    # ------------------------------------------------------------------
    print("Le Golden set teste ce qui est réglé")
    reset()
    calls = []

    def gh(method, path, json=None):
        calls.append((method, path, json))
        return (204, None) if path.endswith("/dispatches") else (200, {"workflow_runs": []})
    GS._gh = gh
    os.environ["GOLDEN_GITHUB_TOKEN"] = "x"
    db.golden_lock.delete_many({})
    http("PUT", "/api/admin/ai/routing/copilot", BOSS, json={"model": SONNET})
    r = http("POST", "/api/admin/ai/golden/run", BOSS)
    sent = next((c[2] for c in calls if c[1].endswith("/dispatches")), {})
    check("« Lancer » sends the table to the run", r.status_code == 200 and json.loads(sent["inputs"]["routes"])["copilot"] == SONNET, (r.text, sent))
    db.golden_lock.delete_many({})
    os.environ.pop("GOLDEN_GITHUB_TOKEN")
    check("the run applies it", R.apply_routes(json.dumps({"copilot": FABLE, "support": OPUS})) and R.model_for("copilot") == FABLE and R.model_for("support") == OPUS)
    check("…and only the ladder", R.apply_routes(json.dumps({"copilot": "gpt-5", "inconnu": OPUS})) == 0 and R.model_for("copilot") == FABLE)
    check("bad input is ignored", R.apply_routes("{pas du json") == 0 and R.apply_routes("[1]") == 0 and R.apply_routes("") == 0 and R.apply_routes(None) == 0)
    reset()
    current = R.current()
    db.golden_runs.insert_one({"_id": 1, "at": clock[0], "report": {"ok": True, "total": 249, "passed": 249, "routes": current}})
    g = http("GET", "/api/admin/ai/routing", BOSS).json()["golden"]
    check("a run on today's table: not stale", g["stale"] is False and g["ok"] is True and g["passed"] == 249, g)
    http("PUT", "/api/admin/ai/routing/support", BOSS, json={"model": OPUS})
    g = http("GET", "/api/admin/ai/routing", BOSS).json()["golden"]
    check("a change after it: stale again", g["stale"] is True, g)
    http("POST", "/api/admin/ai/routing/support/revert", BOSS)
    g = http("GET", "/api/admin/ai/routing", BOSS).json()["golden"]
    check("undone: that run counts again", g["stale"] is False, g)
    reset()
    check("no run at all: stale", http("GET", "/api/admin/ai/routing", BOSS).json()["golden"]["stale"] is True)
    db.golden_runs.insert_one({"_id": 2, "at": clock[0], "report": {"ok": False, "total": 249, "passed": 240}})
    check("an old report without a table: stale", http("GET", "/api/admin/ai/routing", BOSS).json()["golden"]["stale"] is True)

    print()
    print(f"{passed} ok, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
