"""
« Ce que FidClic IA retient » partout (user, 2026-10-30 — PR 3 of the
Copilote's memory): the owner's facts are the shop's truth, the account's
own come with them; automatic work (Autopilote) reads the owner's.

- Every AI that writes reads them: the campaign and automation drafts,
  the Autopilote, the campaign analysis.
- The pages that advise by rules change their advice: an offer on a day the
  shop is closed is not shown, advice for the clients the shop aims at goes
  up, an offer the owner does not want goes down — the card says
  « Selon ce que vous avez dit : … ». Firm facts come from each fact: at
  once by rules, then refined by the model in the regular pass.

Run: cd api && /usr/local/bin/python3 tests/test_memory_everywhere.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-memory-everywhere")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:700])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import copilot_memory as CM
    from features import reco_ranking as RR
    from services import llm

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime(2026, 10, 30, 10, tzinfo=UTC)
    CM.NOW = lambda: now

    def tok(email, role, tid):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}

    db.tenants.insert_many([{"id": "t", "slug": "t", "name": "Barbier Test", "sector": "salon", "activity_key": "barbier",
                             "plan": "vip", "is_active": True, "subscription_status": "active"},
                            {"id": "x", "slug": "x", "name": "Autre", "sector": "salon", "plan": "vip", "is_active": True}])
    db.users.insert_many([{"email": "o@t.fr", "role": "business_owner", "tenant_id": "t", "active": True},
                          {"email": "m@t.fr", "role": "manager", "tenant_id": "t", "active": True},
                          {"email": "o@x.fr", "role": "business_owner", "tenant_id": "x", "active": True}])
    O, M = tok("o@t.fr", "business_owner", "t"), tok("m@t.fr", "manager", "t")

    # ---------------------------------------------------------------- firm facts, by rules
    print("Les faits fermes (règles, tout de suite)")
    r = CM.rules_of
    check("« je ferme le lundi » → closed Monday", r("je ferme le lundi")["jours_fermes"] == [0], r("je ferme le lundi"))
    check("« Fermé le dimanche et le lundi » → both", sorted(r("Fermé le dimanche et le lundi")["jours_fermes"]) == [0, 6])
    check("« fermé le week-end » → Saturday and Sunday", sorted(r("fermé le week-end")["jours_fermes"]) == [5, 6])
    check("« on ne travaille pas les mardis » → Tuesday", r("on ne travaille pas les mardis")["jours_fermes"] == [1])
    check("« ouvert le lundi » → nothing closed", r("ouvert le lundi")["jours_fermes"] == [])
    check("« ma cible : les étudiants » → target students", r("ma cible : les étudiants")["cible"] == ["etudiants"])
    check("« on vise surtout les familles du quartier » → families and the neighbourhood",
          sorted(r("on vise surtout les familles du quartier")["cible"]) == ["familles", "quartier"])
    check("« j'ai deux étudiants en apprentissage » → no target (no aim said)", r("j'ai deux étudiants en apprentissage")["cible"] == [])
    check("« ma cible : les clients inactifs » → target the inactive", r("Ma cible : les clients inactifs")["cible"] == ["inactifs"])
    check("« je ne fais jamais de promo » → avoid offers", r("je ne fais jamais de promo")["eviter"] == ["offres"])
    check("« pas de remise, jamais » → avoid offers", r("pas de remise, jamais")["eviter"] == ["offres"])
    check("« j'aime les promos » → nothing to avoid", r("j'aime les promos")["eviter"] == [])
    check("« pas de parrainage chez moi » → avoid referral", r("pas de parrainage chez moi")["eviter"] == ["parrainage"])

    # ---------------------------------------------------------------- whose facts
    print("\nLes faits de qui")
    http("POST", "/api/me/ai-memory", O, json={"text": "Je ferme le lundi"})
    http("POST", "/api/me/ai-memory", M, json={"text": "Ma cible : les étudiants"})
    c_owner = CM.constraints("t", "o@t.fr")
    c_mgr = CM.constraints("t", "m@t.fr")
    c_auto = CM.constraints("t", None)
    check("the owner's facts count for everyone (the shop's truth)", 0 in c_owner["closed"] and 0 in c_mgr["closed"] and 0 in c_auto["closed"])
    check("the account's own facts count for that account", "etudiants" in c_mgr["targets"])
    check("…not for the owner, nor for automatic work", "etudiants" not in c_owner["targets"] and "etudiants" not in c_auto["targets"])
    check("another shop has none of them", not CM.constraints("x", "o@x.fr")["closed"])
    blk = CM.memory_block("t", "m@t.fr")
    check("the block AIs read: the owner's and the account's facts", "Je ferme le lundi" in blk and "Ma cible : les étudiants" in blk, blk)
    check("…automatic work: the owner's only", "étudiants" not in CM.memory_block("t", None))

    # ---------------------------------------------------------------- the model refines them
    print("\nL'IA affine les faits (passage régulier)")
    http("POST", "/api/me/ai-memory", O, json={"text": "Le mardi c'est jour de repos pour toute l'équipe"})
    seen = []

    def model(system, user):
        seen.append({"system": system, "user": user})
        if CM.RULES_MARK in system:
            if "repos" in user:
                return json.dumps({"jours_fermes": ["mardi"], "cible": ["martiens"], "eviter": ["offres"]})
            said = CM.rules_of(user.split("Phrase :", 1)[-1])          # a model that reads it as the rules do
            return json.dumps({**said, "jours_fermes": [CM.WEEKDAYS_FR[i] for i in said["jours_fermes"]]})
        return "[]"
    llm._force_complete = model
    CM.learn_due(now)
    f = db.copilot_memory.find_one({"tenant_id": "t", "by": "o@t.fr", "text": {"$regex": "repos"}})
    check("each fact is read once by the model for its firm facts", f and f.get("rules_by") == "ia"
          and f["rules"]["jours_fermes"] == [1], f)
    check("…words outside the list are dropped (« martiens »)", f and f["rules"]["cible"] == [])
    check("…and phones never reach it", all("06" not in s["user"] for s in seen))
    n = len(seen)
    CM.learn_due(now)
    check("…once: a second pass asks nothing", not any(CM.RULES_MARK in s["system"] for s in seen[n:]))
    fid = f["id"]
    http("PATCH", f"/api/me/ai-memory/{fid}", O, json={"text": "Le mercredi c'est jour de repos"})
    f = db.copilot_memory.find_one({"id": fid})
    check("an edited fact is read again (rules at once, the model next pass)", f["rules_by"] == "regle" and f["rules"]["jours_fermes"] == [2], f)
    llm._force_complete = None

    # ---------------------------------------------------------------- the advice changes
    print("\nLes conseils changent")
    items = [
        {"key": "offre_jour", "title": "Créer une offre spéciale lundi", "score": 100, "cta": {"kind": "template", "template": "offre_jour", "day": 0}},
        {"key": "affluence", "title": "Forte affluence prévue ce lundi", "score": 90},
        {"key": "etudiants", "title": "Créer une campagne étudiants", "score": 45, "cta": {"kind": "template", "template": "etudiants"}},
        {"key": "relance_inactifs", "title": "Relancer 20 clients inactifs", "score": 50, "cta": {"kind": "template", "template": "relance_inactifs"}},
        {"key": "offre_samedi", "title": "Créer une offre spéciale samedi", "score": 60, "cta": {"kind": "template", "template": "offre_jour", "day": 5}},
    ]
    out = RR.rank("t", items, lambda i, _n: i["score"], now, by="o@t.fr")
    keys = [i["key"] for i in out]
    check("closed on Monday: the Monday offer and « affluence ce lundi » are not shown", "offre_jour" not in keys and "affluence" not in keys, keys)
    check("…the other advice stays", {"relance_inactifs", "etudiants", "offre_samedi"} <= set(keys), keys)
    out = RR.rank("t", items, lambda i, _n: i["score"], now, by="m@t.fr")
    top = {i["key"]: i for i in out}
    check("the manager aims at students: their advice goes up", [i["key"] for i in out].index("etudiants")
          < [i["key"] for i in RR.rank("t", items, lambda i, _n: i["score"], now, by="o@t.fr")].index("etudiants"), [i["key"] for i in out])
    check("…and the card says why", top["etudiants"]["why_rank"].get("selon") == "Selon ce que vous avez dit : « Ma cible : les étudiants »",
          top["etudiants"]["why_rank"])
    check("…in « Pourquoi en premier ? » too", top["etudiants"]["why_rank"]["text"].startswith("Selon ce que vous avez dit"))
    http("POST", "/api/me/ai-memory", O, json={"text": "Je ne fais jamais de promo"})
    out = RR.rank("t", items, lambda i, _n: i["score"], now, by="o@t.fr")
    sat = next(i for i in out if i["key"] == "offre_samedi")
    base_rank = [i["key"] for i in out]
    near = {"key": "proximite", "title": "Cibler 12 clients à moins de 2 km", "score": 5,
            "cta": {"kind": "template", "template": "offre_locale"}}
    http("POST", "/api/me/ai-memory", M, json={"text": "On vise les gens du quartier"})
    got = next(i for i in RR.rank("t", items + [near], lambda i, _n: i["score"], now, by="m@t.fr") if i["key"] == "proximite")
    check("an idea known by its template (offre_locale) and its own key (proximite) both count",
          (got["why_rank"].get("selon") or "").endswith("« On vise les gens du quartier »"), got["why_rank"])
    check("no promotions wanted: the Saturday offer goes below the advice it led",
          base_rank.index("offre_samedi") > base_rank.index("relance_inactifs"), base_rank)
    check("…and says why", sat["why_rank"].get("selon") == "Selon ce que vous avez dit : « Je ne fais jamais de promo »", sat["why_rank"])
    check("no fact, no change: another shop's order is the estimate's", [i["key"] for i in RR.rank("x", items, lambda i, _n: i["score"], now, by="o@x.fr")][:2]
          == ["offre_jour", "affluence"])
    real = CM.constraints
    CM.constraints = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    check("a broken memory never empties a page (the order stays)", len(RR.rank("t", items, lambda i, _n: i["score"], now, by="o@t.fr")) == 5)
    CM.constraints = real

    print("\nSur les pages (le compte qui regarde)")
    asked = []
    real = CM.constraints

    def spy(tid, by=None):
        asked.append(by)
        return real(tid, by)
    CM.constraints = spy
    for url in ("/api/owner/copilot/page", "/api/owner/insights/page", "/api/owner/home/overview", "/api/owner/brain/detectors"):
        asked.clear()
        r = http("GET", url, M)
        check(f"{url}: ranked with the manager's facts too", r.status_code == 200 and "m@t.fr" in asked, (r.status_code, asked))
    CM.constraints = real

    # ---------------------------------------------------------------- the AIs that write
    print("\nLes IA qui écrivent")
    prompts = []

    def writer(system, user):
        prompts.append(user)
        return "Titre : Bonjour\nMessage : Bonjour {first_name}"
    llm._force_complete = writer
    http("POST", "/api/me/ai-memory", M, json={"text": "Mon numéro perso 06 11 22 33 44"})
    http("POST", "/api/owner/campaigns/ai-draft", M, json={"objective": "Faire revenir les clients", "segment": "all"})
    p = prompts[-1] if prompts else ""
    check("campaign draft: the owner's facts and the account's", "Je ferme le lundi" in p and "Ma cible : les étudiants" in p, p[-600:])
    check("…never a phone number", "11 22" not in p)
    http("POST", "/api/owner/automations/ai-draft", M, json={"objective": "Souhaiter les anniversaires"})
    p = prompts[-1] if prompts else ""
    check("automation draft: the same", "Je ferme le lundi" in p and "Ma cible : les étudiants" in p, p[-600:])
    from features import autopilot as AP
    AP.write("t", "inactive")
    p = prompts[-1] if prompts else ""
    check("Autopilote (automatic): the owner's facts, not the manager's", "Je ferme le lundi" in p and "étudiants" not in p, p[-600:])
    got = []
    server._call_llm = lambda prompt: (got.append(prompt) or (["- a", "- b", "- c"], "test"))
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t", "name": "Relance", "status": "sent", "sent_at": now - dt.timedelta(days=20),
                             "recipient_ids": [], "content": "Bonjour"})
    r = http("POST", "/api/owner/campaigns/k1/ai-analyze", O)
    check("campaign analysis: the owner's facts", r.status_code == 200 and got and "Je ferme le lundi" in got[-1], (r.status_code, got[-1][-400:] if got else None))
    llm._force_complete = None

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
