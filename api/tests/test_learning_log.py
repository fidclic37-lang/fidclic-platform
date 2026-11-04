"""
Learning log (user, 2026-11-02): every text FidClic IA writes — Rédiger
(campaign, automation), Autopilot, Copilote, the composer's prefills — is kept
with what the owner did with it (sent as is, edited, dropped), the owner's
👍 / 👎 on the Copilote, and what it brought in (groupe témoin, 15 days).
Names, phones, e-mails, IBANs and the shop's name are scrubbed; rows are
training-ready from day one (the user's choice). Super admin › Apprentissage
reads it and exports the good examples as JSONL.

Run: cd api && /usr/local/bin/python3 tests/test_learning_log.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-learning-log")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, *info):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or not info else f"  → {info}"))


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import learning_log as LL
    from services import llm

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_many([
        {"id": "t1", "slug": "rt", "name": "Royal Test", "plan": "vip", "subscription_status": "active", "is_active": True,
         "sector": "salon", "activity_key": "barbier", "branches": [{"id": "b1", "name": "Royal Test Gare", "is_main": True}]},
        {"id": "t2", "slug": "other", "name": "Autre Shop", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 10})
    db.users.insert_many([
        {"email": "o@rt.fr", "role": "business_owner", "tenant_id": "t1", "active": True, "first_name": "Ana"},
        {"email": "o@other.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
        {"email": "boss@fidclic.com", "role": "super_admin", "active": True},
    ])
    db.customers.insert_many([
        {"id": f"c{i}", "tenant_id": "t1", "name": n, "phone": f"06123456{i:02d}", "visits": 3, "barcode_id": f"B{i}",
         "created_at": now - dt.timedelta(days=90), "last_visit_date": now - dt.timedelta(days=40)}
        for i, n in enumerate(["Sophie Martin", "Karim Benali", "Léa Dubois"] + [f"X{k}" for k in range(30)])])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    OWNER, OTHER, BOSS = tok("o@rt.fr", "business_owner"), tok("o@other.fr", "business_owner", "t2"), tok("boss@fidclic.com", "super_admin", None)

    # The fake Copilote answer carries a phone and an e-mail on purpose: the scrub is
    # the last line of defence, so the live checks (test_ai_routing) stand aside here.
    from features import ai_routing
    ai_routing.CHECKS = {}
    answers = {"campaign": "TITRE: Votre coupe vous attend\nMESSAGE: {prénom}, -10 % sur votre coupe cette semaine chez Royal Test.",
               "copilot": "Sophie Martin (06 12 34 56 00) revient tous les 21 jours ; écrivez-lui à sophie@mail.fr."}
    llm._force_complete = lambda system, user: answers["copilot"] if "Données du commerce" in user else answers["campaign"]

    # ── scrub ────────────────────────────────────────────────────────────
    print("Données personnelles retirées")
    s = LL.scrub("t1", "Sophie Martin et Karim ont appelé le 06 12 34 56 78, écrivez à karim@x.fr — IBAN FR76 3000 6000 0112 3456 7890 189. Royal Test Gare vous attend.")
    check("full name and first name → {prénom}", "Sophie" not in s and "Martin" not in s and "Karim" not in s and s.count("{prénom}") == 2, s)
    check("phone and e-mail hidden", "06 12 34 56 78" not in s and "karim@x.fr" not in s, s)
    check("IBAN hidden", "FR76" not in s and "189" not in s, s)
    check("the shop's and its store's name → {commerce}", "Royal Test" not in s and "{commerce}" in s, s)
    check("an ordinary word is untouched", "vous attend" in s and "appelé" in s)
    check("another shop's clients are not this shop's names", LL.scrub("t2", "Sophie viendra") == "Sophie viendra")

    # ── Rédiger avec l'IA (campagne) ─────────────────────────────────────
    print("Rédiger une campagne")
    r = http("POST", "/api/owner/campaigns/ai-draft", headers=OWNER, json={"objective": "Faire revenir les clients", "segment": "all"})
    ex_id = r.json().get("ai_example_id")
    check("the draft carries its example id", r.status_code == 200 and ex_id, r.text[:200])
    ex = db.ai_examples.find_one({"id": ex_id}, {"_id": 0})
    check("kept: shop, trade, surface, model, prompt, output — proposed", ex and ex["tenant_id"] == "t1" and ex["activity"] == "barbier"
          and ex["surface"] == "campaign_ai" and ex["status"] == "proposed" and ex["system_ref"] and ex["input_z"]
          and ex["output"]["title"] == "Votre coupe vous attend", ex)
    check("…the output scrubbed (shop name → {commerce})", "Royal Test" not in ex["output"]["message"] and "{commerce}" in ex["output"]["message"])
    check("…training-ready from day one", ex["training_ok"] is True)
    check("…no owner e-mail in the row", "o@rt.fr" not in json.dumps(ex, default=str))
    inp = LL.unpack(ex["input_z"])
    check("the prompt is kept, scrubbed, compressed", "Faire revenir" in inp and "Royal Test" not in inp, inp[:120])
    check("the system prompt once, by reference", db.ai_prompts.count_documents({"_id": ex["system_ref"]}) == 1)

    r = http("POST", "/api/owner/campaigns/compose", headers=OWNER, json={
        "title": "Votre coupe vous attend", "message": "{prénom}, -10 % sur votre coupe cette semaine chez Royal Test.",
        "audience": {"mode": "all"}, "ai_example_id": ex_id})
    ex = db.ai_examples.find_one({"id": ex_id}, {"_id": 0})
    cid = r.json().get("id")
    check("sent as written → accepted, linked to its campaign", r.status_code == 200 and ex["status"] == "accepted"
          and ex["campaign_id"] == cid and ex["similarity"] >= 0.97, ex)

    r = http("POST", "/api/owner/campaigns/ai-draft", headers=OWNER, json={"objective": "Promo", "segment": "all"})
    ex2 = r.json()["ai_example_id"]
    http("POST", "/api/owner/campaigns/compose", headers=OWNER, json={
        "title": "Ma promo à moi", "message": "Bonjour {prénom}, venez Karim vous offre le shampoing !", "audience": {"mode": "all"},
        "ai_example_id": ex2})
    e2 = db.ai_examples.find_one({"id": ex2}, {"_id": 0})
    check("edited by the owner → edited, his words kept (scrubbed)", e2["status"] == "edited" and e2["similarity"] < 0.97
          and e2["final"]["title"] == "Ma promo à moi" and "Karim" not in e2["final"]["message"], e2)

    r = http("POST", "/api/owner/campaigns/ai-draft", headers=OWNER, json={"objective": "Brouillon", "segment": "all"})
    ex3 = r.json()["ai_example_id"]
    d = http("POST", "/api/owner/campaigns/compose", headers=OWNER, json={
        "title": "Votre coupe vous attend", "message": "x", "audience": {"mode": "all"}, "draft": True, "ai_example_id": ex3}).json()
    check("a draft keeps it proposed, and remembers the example", db.ai_examples.find_one({"id": ex3})["status"] == "proposed"
          and http("GET", f"/api/owner/campaigns/drafts/{d['id']}", headers=OWNER).json().get("ai_example_id") == ex3)
    check("another shop cannot attach this example", http("POST", "/api/owner/campaigns/compose", headers=OTHER, json={
        "title": "x", "message": "y", "audience": {"mode": "all"}, "ai_example_id": ex3}).status_code in (200, 400)
          and db.ai_examples.find_one({"id": ex3})["status"] == "proposed")
    check("a made-up id is ignored, the send still goes", http("POST", "/api/owner/campaigns/compose", headers=OWNER, json={
        "title": "x", "message": "y", "audience": {"mode": "all"}, "ai_example_id": "nope"}).status_code == 200)

    # ── templates (Insights / Produits / Fiche) ──────────────────────────
    print("Modèle pré-rempli")
    r = http("GET", "/api/owner/insights/templates/client:c0", headers=OWNER)
    tid_ex = r.json().get("ai_example_id")
    check("an Insights prefill is an example too", r.status_code == 200 and tid_ex
          and db.ai_examples.find_one({"id": tid_ex})["surface"] == "template", r.text[:200])
    again = http("GET", "/api/owner/insights/templates/client:c0", headers=OWNER).json().get("ai_example_id")
    check("opened twice the same day: one row, not two", again == tid_ex
          and db.ai_examples.count_documents({"surface": "template", "source_key": "client:c0"}) == 1)

    # ── automation ───────────────────────────────────────────────────────
    print("Rédiger une automatisation")
    llm._force_complete = lambda system, user: "TITRE: On vous attend {prénom}\nMESSAGE: Revenez chez {nom_commerce} !"
    r = http("POST", "/api/owner/automations/ai-draft", headers=OWNER, json={"objective": "Relancer les inactifs"})
    aex = r.json().get("ai_example_id")
    check("the automation draft carries its id", r.status_code == 200 and aex, r.text[:200])
    base = {"scenario": "inactive", "name": "Inactifs 60 j", "status": "active", "trigger": {"days": 60, "repeat": "once"},
            "message": {"title": "On vous attend {prénom}", "body": "Revenez vite chez {nom_commerce}, café offert !",
                        "button": {"enabled": False, "label": "", "link_type": "card"}},
            "targeting": {"mode": "all", "filters": {}}, "schedule": {"days": "all", "hour": "10:00"}, "ai_example_id": aex}
    r = http("POST", "/api/owner/automations", headers=OWNER, json=base)
    a = db.ai_examples.find_one({"id": aex}, {"_id": 0})
    check("saved with an edit → edited, linked to the automation", r.status_code == 200 and a["status"] == "edited"
          and a["automation_id"] == r.json()["id"], (r.status_code, r.text[:200], a))
    check("the id is not stored on the automation itself", "ai_example_id" not in db.automations.find_one({"id": r.json()["id"]}))

    # ── autopilot ────────────────────────────────────────────────────────
    print("Autopilot")
    from features import autopilot as AP
    llm._force_complete = lambda system, user: "TITRE: Ça fait longtemps\nMESSAGE: {prénom}, votre place vous attend cette semaine."
    p = AP._save("t1", "weekly", now.date(), now + dt.timedelta(hours=2), "custom", ["c0", "c1"], "En retard", [], {}, "en_retard", now)
    pex = p.get("ai_example_id")
    check("a proposal is an example", pex and db.ai_examples.find_one({"id": pex})["surface"] == "autopilot")
    r = http("POST", f"/api/owner/autopilot/{p['id']}/approve", headers=OWNER, json={"title": "Vous nous manquez, passez nous voir"})
    pe = db.ai_examples.find_one({"id": pex}, {"_id": 0})
    check("approved with a new title → edited, linked to its campaign", r.status_code == 200 and pe["status"] == "edited"
          and pe["campaign_id"] == r.json()["campaign_id"], (r.status_code, r.text[:200], pe))
    p2 = AP._save("t1", "daily", now.date(), now + dt.timedelta(hours=3), "custom", ["c2"], "Jour", [], {}, "en_retard", now)
    http("POST", f"/api/owner/autopilot/{p2['id']}/skip", headers=OWNER)
    check("skipped → rejected", db.ai_examples.find_one({"id": p2["ai_example_id"]})["status"] == "rejected")

    # ── copilote ─────────────────────────────────────────────────────────
    print("Copilote : 👍 / 👎")
    llm._force_complete = lambda system, user: answers["copilot"]
    r = http("POST", "/api/owner/copilot/chat", headers=OWNER, json={"message": "Qui revient le plus souvent ?"})
    mid = r.json().get("id")
    cx = db.ai_examples.find_one({"id": mid}, {"_id": 0})
    check("each model answer has an id and is an example", r.status_code == 200 and mid and cx and cx["surface"] == "copilot", r.text[:200])
    check("…scrubbed: no client name, phone or e-mail", cx and all(x not in cx["output"]["text"] for x in ("Sophie", "06 12 34", "sophie@mail.fr")), cx)
    check("the owner still sees the real answer", "Sophie Martin" in r.json()["reply"])
    r = http("POST", "/api/owner/ai/feedback", headers=OWNER, json={"id": mid, "vote": "down", "reason": "faux_chiffre", "text": "Elle vient tous les mois, Sophie."})
    cx = db.ai_examples.find_one({"id": mid}, {"_id": 0})
    check("👎 with a reason and a note (scrubbed)", r.status_code == 200 and cx["feedback"]["vote"] == "down"
          and cx["feedback"]["reason"] == "faux_chiffre" and "Sophie" not in cx["feedback"]["text"] and cx["label"] == "bad", cx)
    h = http("GET", "/api/owner/copilot/chat", headers=OWNER).json()
    rows = h.get("messages") or h.get("rows") or h.get("items") or []
    check("the history shows the vote on that answer", any(m.get("id") == mid and m.get("vote") == "down" for m in rows), str(h)[:300])
    check("👍 replaces it", http("POST", "/api/owner/ai/feedback", headers=OWNER, json={"id": mid, "vote": "up"}).status_code == 200
          and db.ai_examples.find_one({"id": mid})["feedback"]["vote"] == "up" and db.ai_examples.find_one({"id": mid})["label"] == "good")
    check("a bad vote or reason is refused (422)",
          http("POST", "/api/owner/ai/feedback", headers=OWNER, json={"id": mid, "vote": "maybe"}).status_code == 422
          and http("POST", "/api/owner/ai/feedback", headers=OWNER, json={"id": mid, "vote": "down", "reason": "<script>"}).status_code == 422)
    check("another shop cannot vote on it (404)", http("POST", "/api/owner/ai/feedback", headers=OTHER, json={"id": mid, "vote": "down"}).status_code == 404)

    # ── outcome, abandon ─────────────────────────────────────────────────
    print("Le résultat, 15 jours après")
    from features import temoin as T
    real_block = T.campaign_block
    T.campaign_block = lambda tid, c, at: {"ready": True, "enough": True, "rate": 30, "temoin_rate": 10, "extra_revenue": 120.0}
    db.campaigns.update_one({"id": cid}, {"$set": {"sent_at": now - dt.timedelta(days=17)}})
    db.ai_examples.update_one({"id": ex3}, {"$set": {"created_at": now - dt.timedelta(days=9)}})
    out = LL.due(now)
    T.campaign_block = real_block
    ex = db.ai_examples.find_one({"id": ex_id}, {"_id": 0})
    check("the témoin's answer is kept on the example", ex["outcome"]["rate"] == 30 and ex["outcome"]["temoin_rate"] == 10
          and ex["label"] == "good", ex.get("outcome"))
    check("a draft never sent after 7 days → abandoned", db.ai_examples.find_one({"id": ex3})["status"] == "abandoned")
    check("the tick runs it", "learning_log" in server.tick_pass())

    # ── super admin ──────────────────────────────────────────────────────
    print("Super admin › Apprentissage")
    r = http("GET", "/api/admin/ai/learning", headers=BOSS)
    d = r.json()
    surf = {x["surface"]: x for x in d.get("surfaces", [])}
    check("200, per surface: generated, accepted, edited, rejected, abandoned", r.status_code == 200
          and surf["campaign_ai"]["total"] >= 3 and surf["campaign_ai"]["accepted"] == 1 and surf["campaign_ai"]["edited"] == 1
          and surf["autopilot"]["rejected"] == 1, d)
    check("votes and reasons", d["feedback"]["up"] >= 1 and "reasons" in d["feedback"])
    check("good examples against the 10 000 goal", d["good"] >= 1 and d["goal"] == 10000)
    check("recent examples, scrubbed", d["recent"] and "Sophie" not in json.dumps(d["recent"]))
    check("owners refused", http("GET", "/api/admin/ai/learning", headers=OWNER).status_code in (401, 403))
    r = http("GET", "/api/admin/ai/learning/export.jsonl", headers=BOSS)
    lines = [json.loads(x) for x in r.text.strip().splitlines() if x.strip()]
    check("export: one JSON line per good example, chat-shaped", r.status_code == 200 and lines
          and all({"messages", "surface", "label"} <= set(x) for x in lines)
          and lines[0]["messages"][-1]["role"] == "assistant", r.text[:300])
    check("…the owner's final words are the answer when he edited", any("Ma promo à moi" in x["messages"][-1]["content"] for x in lines))
    check("…no name, phone, e-mail anywhere", all(w not in r.text for w in ("Sophie", "Karim", "06 12 34", "@mail.fr", "o@rt.fr")))
    check("export refused to owners", http("GET", "/api/admin/ai/learning/export.jsonl", headers=OWNER).status_code in (401, 403))

    print("Pentest (2026-11-02) : les failles corrigées")
    db.customers.insert_many([{"id": f"p{i}", "tenant_id": "t1", "name": n, "deleted_at": None}
                              for i, n in enumerate(["Li Wang", "Bo Dupont", "Anne Le Goff"])])
    LL._names.clear()
    s = LL.scrub("t1", "Li et Bo viennent; sôphie aussi. Elle habite 12 rue des Lilas 37000 Tours, née le 03/04/1990 (1990-04-03). "
                      "Le salon est ouvert le lundi, la semaine.")
    check("2-letter names are scrubbed (Li, Bo)", " Li " not in f" {s} " and " Bo" not in s and s.startswith("{prénom} et {prénom}"), s)
    check("a name written without its accent or with another one (sôphie) too", "sôphie" not in s.lower() and "sophie" not in s.lower(), s)
    check("a street address → [adresse]", "rue des Lilas" not in s and "[adresse]" in s, s)
    check("a birth date, either way → [date]", "03/04/1990" not in s and "1990-04-03" not in s and s.count("[date]") == 2, s)
    check("common words stay, even when a client is called « Le Goff »", "Le salon est ouvert le lundi, la semaine." in s, s)
    import time as _t
    db.customers.insert_many([{"id": f"big{i}", "tenant_id": "t1", "name": f"Prenom{chr(97 + i % 26)}{chr(97 + (i // 26) % 26)} Nomx{i}"}
                              for i in range(20000)])
    LL._names.clear()
    LL.scrub("t1", "warm-up")
    big = ("Sophie revient le mardi; Données du commerce (JSON) : " + '{"clients": 3000, "ca": 12345.6, "jour": "mardi"} ' * 300)
    t0 = _t.perf_counter()
    out = LL.scrub("t1", big)
    ms = (_t.perf_counter() - t0) * 1000
    check(f"a 20 KB prompt on a 20 000-client shop is scrubbed fast ({ms:.0f} ms)", ms < 300 and out.startswith("{prénom} revient"))
    db.customers.delete_many({"id": {"$regex": "^big"}})
    LL._names.clear()
    db.users.insert_one({"email": "lecture@fidclic.com", "role": "fidclic_team", "platform_role": "lecture_ai", "active": True})
    db.platform_roles.insert_one({"id": "lecture_ai", "name": "Lecture IA", "perms": {"ai": {"view": True, "edit": True}}})
    TEAM = tok("lecture@fidclic.com", "fidclic_team", None)
    check("a team member with FIDCLIC AI reads the page", http("GET", "/api/admin/ai/learning", headers=TEAM).status_code == 200)
    check("…but only the super admin downloads the examples", http("GET", "/api/admin/ai/learning/export.jsonl", headers=TEAM).status_code == 403
          and http("GET", "/api/admin/ai/learning/export.jsonl", headers=BOSS).status_code == 200)
    LL.TEMPLATE_DAY_MAX = 3
    ids = [LL.capture("t1", "template", {"title": "t", "message": "m"}, source_key=f"client:x{i}", dedupe_day=True) for i in range(5)]
    check("prefills: at most N new rows a day per shop (a script opening every client's template)",
          ids[:3] == [x for x in ids[:3] if x] and ids[3] is None and ids[4] is None
          or sum(1 for x in ids if x) <= 3, ids)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
