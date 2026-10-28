"""
Sector playbooks, PR2 — FidClic IA writes for the shop's own trade, and the
automations open on the trade's words (user, 2026-10-26: « jahaan jahaan
possible and important ho »).

  · every IA brief (Générer avec l'IA, Besoin d'inspiration, Autopilot, the
    Copilote chat) names the activité, its words, its moments and its rules;
  · the trade's rules hold on what the IA writes: a tabac never promotes
    tobacco (loi Évin), a CBD shop makes no health claim, a bar never pushes
    drinking — a draft that breaks them is refused, Autopilot falls back;
  · « Client inactif » and « Géolocalisation » open on the trade's words;
    the owner's own words are never replaced.

Run: /usr/local/bin/python3 api/tests/test_sector_ia.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-for-sector-ia")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}")


def main():
    import server
    import auth
    import httpx
    import features.insights_page as I
    import features.copilot as C
    import features.automations as AU
    import features.autopilot as AP
    import features.campaigns_page as CP
    from services import activities as A
    from services import llm
    from services import playbooks as PB

    db = server.db
    for mod in (I, C, AU, AP, CP):
        mod._db = db

    # ---- 1. the brief: activité, words, moments, rules ---------------------------------------
    print("\nLe brief de l'IA")
    for a in A.ACTIVITIES:
        ctx = PB.prompt_context(PB.of({"activity_key": a["key"]}), 6)
        if a["label"] not in ctx or "{" in ctx or len(ctx) > 900:
            check(f"brief of {a['key']}", False)
            break
    else:
        check("every activity has a brief naming it, with no stray {token}, under 900 characters", True)
    barb = PB.prompt_context(PB.of({"activity_key": "barbier"}), 6)
    check("a barbier's brief says « prestations »", "prestations" in barb)
    check("… and names its offer when asked", "1 taille de barbe offerte" in barb)
    check("… but never when the offer is not wanted (Autopilot)",
          "1 taille de barbe offerte" not in PB.prompt_context(PB.of({"activity_key": "barbier"}), 6, offer=False))
    check("… and its moment of the month (Fête des pères in June)", "Fête des pères" in barb)
    check("… not out of season (no Fête des pères in January)",
          "Fête des pères" not in PB.prompt_context(PB.of({"activity_key": "barbier"}), 1))
    check("a café's brief speaks of café, not of coupes",
          "café" in PB.prompt_context(PB.of({"sector": "cafe"}), 6).lower()
          and "coupe" not in PB.prompt_context(PB.of({"sector": "cafe"}), 6).lower())
    tab = PB.prompt_context(PB.of({"activity_key": "tabac_presse"}), 6)
    check("a tabac's brief forbids tobacco (loi Évin)", "loi Évin" in tab and "tabac" in tab.lower())
    check("a bar-tabac's too", "loi Évin" in PB.prompt_context(PB.of({"activity_key": "bar_tabac"}), 6))
    check("a CBD shop's brief forbids any health claim",
          "santé" in PB.prompt_context(PB.of({"activity_key": "cbd"}), 6))
    check("a bar's brief forbids pushing drinks",
          "alcool" in PB.prompt_context(PB.of({"sector": "bar"}), 6).lower())
    check("a caviste's too", "alcool" in PB.prompt_context(PB.of({"activity_key": "caviste"}), 6).lower())
    check("a barbier has no such rule", "loi Évin" not in barb and "alcool" not in barb.lower())
    check("a blank shop still gets a brief", "Activité" in PB.prompt_context(PB.of({}), 6))
    check("a damaged tenant gets a brief, no crash",
          "Activité" in PB.prompt_context(PB.of({"activity_key": ["x"], "sector": {"a": 1}}), 6))
    check("a month out of range does not crash", "Activité" in PB.prompt_context(PB.of({}), 13)
          and "Activité" in PB.prompt_context(PB.of({}), 0))

    # ---- 2. the rules, on what the IA wrote ----------------------------------------------------
    print("\nLes règles du métier sur le texte de l'IA")
    tp, cb, br, bb = (PB.of({"activity_key": "tabac_presse"}), PB.of({"activity_key": "cbd"}),
                      PB.of({"sector": "bar"}), PB.of({"activity_key": "barbier"}))
    check("a tabac's draft about cigarettes breaks the rule", PB.breaks_rules(tp, "Vos cigarettes vous attendent"))
    check("… about vapes too", PB.breaks_rules(tp, "Nouvelle e-cigarette en boutique"))
    check("… « Tabac » with a capital too", PB.breaks_rules(tp, "Votre TABAC préféré"))
    check("… but presse and jeux are fine", not PB.breaks_rules(tp, "Presse, jeux, recharges : on vous attend"))
    check("a CBD draft that promises sleep breaks the rule", PB.breaks_rules(cb, "Retrouvez le sommeil avec nos huiles"))
    check("… that soothes stress too", PB.breaks_rules(cb, "Une huile qui apaise le stress"))
    check("… a plain novelty is fine", not PB.breaks_rules(cb, "De nouvelles références en boutique"))
    check("a bar draft pushing drinks breaks the rule", PB.breaks_rules(br, "Bière à volonté ce soir !"))
    check("… « 2 verres pour le prix d'1 » too", PB.breaks_rules(br, "2 verres pour le prix d'1"))
    check("… a soirée quiz is fine", not PB.breaks_rules(br, "Soirée quiz jeudi, venez entre amis !"))
    check("a barbier is free to say « tabac »", not PB.breaks_rules(bb, "Une odeur de tabac ? Notre soin barbe"))
    check("empty text never breaks", not PB.breaks_rules(tp, "") and not PB.breaks_rules(tp, None))
    # the pentest of 2026-10-28: hidden and indirect words (user: « saare findings mazboot karo »)
    for txt in ("Vos c1garettes vous attendent", "Votre t-a-b-a-c préféré", "Votre t a b a c préféré",
                "Votre tаbac", "Des clopes au comptoir", "Nouveau : sachets de snus",
                "Nouveaux arômes pour votre vapoteuse", "Votre e-liquide préféré", "Cig@rettes en stock",
                "Des cigarettes électroniques", "Votre TÂBÂC", "ci\u200bgarettes en stock", "🚬 nouveautés",
                "Smokes & cigs", "taaabac", "C I G A R E T T E S", "ｔａｂａｃ", "Puffs à 8 €"):
        check(f"tabac: « {txt} » breaks the rule", PB.breaks_rules(tp, txt))
    for txt in ("Votre bureau de tabac vous attend", "Le tabac-presse du quartier", "Votre bar-tabac préféré",
                "Votre bar tabac du coin", "Presse, jeux, recharges, colis", "Un café au comptoir ?",
                "Le lien ci-joint", "Cartes à jouer et jeux de grattage", "Timbres et colis"):
        check(f"tabac: « {txt} » (the place, no product) is fine", not PB.breaks_rules(tp, txt))
    check("… but the place named next to a product still breaks",
          PB.breaks_rules(tp, "Votre bureau de tabac : -10 % sur les cigarettes"))
    for txt in ("Pour des nuits paisibles", "Zen toute la journée", "Idéal pour se relaxer",
                "Bon pour le corps", "Découvrez les bienfaits du CBD", "Une huile relaxante",
                "Retrouvez la sérénité", "Dormez mieux grâce à nos fleurs", "Effet garanti"):
        check(f"CBD: « {txt} » breaks the rule", PB.breaks_rules(cb, txt))
    for txt in ("De nouvelles références en boutique", "Arômes fruités et notes boisées", "Venez nous voir samedi"):
        check(f"CBD: « {txt} » is fine", not PB.breaks_rules(cb, txt))
    for txt in ("Pintes à 3 € toute la soirée", "Happy hour : 2 bières achetées = 1 offerte",
                "Tournée générale offerte !", "Le cocktail à 5 € ce soir", "Verre de vin offert",
                "-50 % sur les bières", "Shooter gratuit pour tous", "Spritz à 4€"):
        check(f"bar: « {txt} » breaks the rule", PB.breaks_rules(br, txt))
    for txt in ("Soirée quiz jeudi, venez entre amis !", "Nouvelle carte des cocktails ce mois-ci",
                "Planche apéro offerte pour 4 personnes", "1 café offert", "Concert live samedi à 21 h",
                "Softs et jus à 2 €"):
        check(f"bar: « {txt} » is fine", not PB.breaks_rules(br, txt))
    bad =[(a["key"], lv["key"]) for a in A.ACTIVITIES for p in [PB.of({"activity_key": a["key"]})]
           for lv in p["levers"] if lv.get("template")
           and PB.breaks_rules(p, lv["template"]["title"] + " " + lv["template"]["message"])]
    check(f"FidClic's own trade templates follow their rules ({bad})", not bad)

    # ---- 3. automations open on the trade's words ----------------------------------------------
    print("\nLes messages par défaut des automatisations")
    for a in A.ACTIVITIES:
        play = PB.of({"activity_key": a["key"]})
        t = PB.automation_texts(play)
        bad = [k for k, v in t.items() if k not in AU.SCENARIOS or not v.get("title") or not v.get("body")
               or len(v["title"]) > AU.TITLE_MAX or len(v["body"]) > AU.BODY_MAX
               or "{emoji}" in v["title"] + v["body"] or PB.breaks_rules(play, v["title"] + " " + v["body"])]
        if bad or set(t) - {"inactive", "geo"}:
            check(f"automation texts of {a['key']} ({bad})", False)
            break
    else:
        check("every activity: only inactive/geo, within limits, no stray {emoji}, within its rules", True)
    for a in A.ACTIVITIES:
        t = PB.automation_texts(PB.of({"activity_key": a["key"]}))
        toks = {w for v in t.values() for w in __import__("re").findall(r"\{([^}]+)\}", v["title"] + v["body"])}
        if toks - set(AU.VARIABLES["common"]):
            check(f"tokens of {a['key']}: {toks}", False)
            break
    else:
        check("… and only use tokens the sender fills ({prénom}, {nom_commerce})", True)
    sal = PB.automation_texts(PB.of({"activity_key": "barbier"}))
    check("a barbier's « Client inactif » speaks of the coupe", "coupe" in sal["inactive"]["title"].lower())
    caf = PB.automation_texts(PB.of({"sector": "cafe"}))
    check("a café's speaks of a pause, with ☕", "☕" in caf["inactive"]["title"] + caf["geo"]["title"])
    check("a tabac's names no tobacco", "tabac" not in str(PB.automation_texts(tp)).lower())
    check("a blank shop keeps the generic words", PB.automation_texts(PB.of({})) == {})

    # ---- 4. through the endpoints --------------------------------------------------------------
    print("\nPar les écrans")
    for tid, extra in {"barb": {"sector": "salon", "activity_key": "barbier"},
                       "tab": {"sector": "retail", "activity_key": "tabac_presse"},
                       "cafe": {"sector": "cafe"}, "blank": {}}.items():
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.title(), "is_active": True, "plan": "vip",
                               "subscription_status": "active", **extra})
        db.users.insert_one({"email": f"o@{tid}", "role": "business_owner", "tenant_id": tid})

    def H(tid, role="business_owner"):
        return {"Authorization": "Bearer " + auth.create_access_token(
            {"sub": f"o@{tid}", "role": role, "tenant_id": tid})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    seen = {}
    reply = {"text": "TITRE: Un moment pour vous\nMESSAGE: On vous attend cette semaine, {prénom} !"}

    def fake(system, user):
        seen["system"], seen["user"] = system, user
        return reply["text"]
    llm._force_complete = fake
    try:
        r = http("POST", "/api/owner/campaigns/ai-draft", headers=H("barb"), json={"objective": "faire revenir"})
        check(f"Générer avec l'IA answers ({r.status_code})", r.status_code == 200)
        check("… its brief names the barbier", "Barbier" in seen.get("user", ""))
        check("… and keeps the owner's objective", "faire revenir" in seen.get("user", ""))
        r = http("POST", "/api/owner/automations/ai-draft", headers=H("barb"), json={"objective": "anniversaire"})
        check(f"Besoin d'inspiration answers ({r.status_code})", r.status_code == 200)
        check("… its brief names the barbier", "Barbier" in seen.get("user", ""))
        seen.clear()
        r = http("POST", "/api/owner/copilot/chat", headers=H("cafe"), json={"message": "Quelle campagne lancer ?"})
        check(f"the Copilote chat answers ({r.status_code})", r.status_code == 200)
        check("… its data carries the café's activité", "Café" in seen.get("user", "") and "metier" in seen.get("user", ""))
        title, message, by = AP.write("barb", "inactive")
        check("Autopilot writes with the IA for a barbier", by == "ia")
        check("… its brief names the barbier", "Barbier" in seen.get("user", ""))
        check("… and never hands it an offer to promise", "1 taille de barbe offerte" not in seen.get("user", ""))

        reply["text"] = "TITRE: Vos cigarettes\nMESSAGE: Le tabac vous attend chez nous, {prénom} !"
        r = http("POST", "/api/owner/campaigns/ai-draft", headers=H("tab"), json={"objective": "vendre plus"})
        check(f"a tabac's draft promoting tobacco is refused ({r.status_code})", r.status_code == 503)
        check("… with a plain reason", "loi Évin" in r.text or "règles" in r.text)
        r = http("POST", "/api/owner/automations/ai-draft", headers=H("tab"), json={"objective": "vendre plus"})
        check(f"… in Besoin d'inspiration too ({r.status_code})", r.status_code == 503)
        title, message, by = AP.write("tab", "inactive")
        check("Autopilot falls back to its template", by == "modele" and "tabac" not in (title + message).lower())
        r = http("POST", "/api/owner/campaigns/ai-draft", headers=H("barb"), json={"objective": "x"})
        check("the same words are fine for a barbier", r.status_code == 200)
        reply["text"] = "TITRE: Bonjour\nMESSAGE: À bientôt !"
        r = http("POST", "/api/owner/campaigns/ai-draft", headers=H("blank"), json={"objective": "x"})
        check(f"a blank shop still drafts ({r.status_code})", r.status_code == 200)
    finally:
        llm._force_complete = None

    r = http("GET", "/api/owner/automations", headers=H("barb"))
    check(f"GET /automations answers ({r.status_code})", r.status_code == 200)
    sc = {s["key"]: s for s in r.json().get("scenarios", [])} if r.status_code == 200 else {}
    check("… the editor opens « Client inactif » on the barbier's words",
          "coupe" in sc.get("inactive", {}).get("title", "").lower())
    check("… and keeps the other scenarios as they were",
          sc.get("birthday", {}).get("title") == AU.SCENARIOS["birthday"]["title"])
    check("the shared catalogue is not changed by a shop", AU.SCENARIOS["inactive"]["title"]
          == "On ne vous a pas vu depuis un moment")
    rows = list(db.automations.find({"tenant_id": "barb", "scenario": "inactive"}))
    check("a new shop's « Client inactif » is created with the trade's words",
          len(rows) == 1 and "coupe" in rows[0]["message"]["title"].lower())
    rb = http("GET", "/api/owner/automations", headers=H("blank")).json()
    check("a blank shop keeps the generic words", {s["key"]: s for s in rb["scenarios"]}["inactive"]["title"]
          == AU.SCENARIOS["inactive"]["title"])
    # the owner's own words stay
    db.automations.update_one({"tenant_id": "barb", "scenario": "inactive"},
                              {"$set": {"message.title": "Mon titre à moi"}})
    http("GET", "/api/owner/automations", headers=H("barb"))
    check("the owner's own words are never replaced",
          db.automations.find_one({"tenant_id": "barb", "scenario": "inactive"})["message"]["title"] == "Mon titre à moi")

    # ---- 5. the rules hold on the owner's own words too (pentest, 2026-10-28) ------------------
    print("\nLes règles sur les mots du commerçant")
    bad_words = {"title": "Promo cigarettes", "message": "Vos cigarettes à -10 % cette semaine"}
    r = http("POST", "/api/owner/campaigns/compose", headers=H("tab"),
             json={**bad_words, "push": True, "wallet": True, "draft": False})
    check(f"the composer refuses a tabac's tobacco promotion ({r.status_code})", r.status_code == 422)
    check("… saying why (loi Évin)", "loi Évin" in r.text)
    r = http("POST", "/api/owner/campaigns/compose", headers=H("tab"),
             json={**bad_words, "push": False, "wallet": False, "draft": True})
    check(f"… even as a draft ({r.status_code})", r.status_code == 422)
    check("nothing was saved", db.campaigns.count_documents({"tenant_id": "tab"}) == 0)
    r = http("POST", "/api/owner/campaigns/compose", headers=H("tab"),
             json={"title": "Presse et jeux", "message": "Votre bureau de tabac vous attend", "draft": True})
    check(f"a tabac's honest words are saved ({r.status_code})", r.status_code != 422)
    r = http("POST", "/api/owner/campaigns/compose", headers=H("barb"),
             json={**bad_words, "draft": True})
    check(f"a barbier is not bound by the tabac's rule ({r.status_code})", r.status_code != 422)
    r = http("POST", "/api/owner/campaigns", headers=H("tab"), json={"name": "x", "content": "Promo clopes"})
    check(f"the old campaign endpoint refuses it too ({r.status_code})", r.status_code == 422)
    r = http("POST", "/api/owner/campaigns/send-to-group", headers=H("tab"),
             json={"name": "x", "content": "Promo c1garettes", "customer_ids": []})
    check(f"… and send-to-group ({r.status_code})", r.status_code == 422)
    r = http("POST", "/api/owner/campaigns/schedule", headers=H("tab"),
             json={"name": "x", "content": "Promo vapoteuses", "run_at": "2030-01-01T10:00:00Z"})
    check(f"… and the scheduler ({r.status_code})", r.status_code == 422)
    check("nothing was scheduled", db.scheduled_campaigns.count_documents({"tenant_id": "tab"}) == 0)
    auto = {"scenario": "custom", "name": "x", "status": "draft", "trigger": {"type": "after_visit"},
            "message": {"title": "Promo", "body": "Vos cigarettes vous attendent"}}
    r = http("POST", "/api/owner/automations", headers=H("tab"), json=auto)
    check(f"an automation with tobacco words is refused ({r.status_code})", r.status_code == 422)
    ok_auto = {**auto, "message": {"title": "Presse", "body": "Vos journaux vous attendent"}}
    r = http("POST", "/api/owner/automations", headers=H("tab"), json=ok_auto)
    check(f"… one with honest words is saved ({r.status_code})", r.status_code == 200)
    if r.status_code == 200:
        r2 = http("PUT", f"/api/owner/automations/{r.json()['id']}", headers=H("tab"), json=auto)
        check(f"… and cannot be changed into tobacco words ({r2.status_code})", r2.status_code == 422)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
