"""
What FidClic IA tells an account follows that account's rights (pentest
2026-11-03, #427): a manager with « Analyses » off got the 30-day revenue,
visits, basket and star product in the Copilote's prompt, in its fallback
answer and on the FidClic IA page, although the tools were closed. Each figure
now opens with the page that shows it, the same pages as the tools.

Run: cd api && /usr/local/bin/python3 tests/test_copilot_facts_perms.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-facts-perms")
os.environ.setdefault("DISABLE_SEED", "1")
for _k in ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_k, None)
passed = failed = 0
ANALYTICS = {"visites_30j", "evolution_visites_pct", "ca_30j_eur", "evolution_ca_pct", "panier_moyen_eur",
             "meilleur_jour", "meilleur_jour_ecart_pct", "prevision_affluence"}
CLIENTS = {"clients_total", "clients_inactifs_30j", "clients_a_risque", "anniversaires_7j", "nouveaux_une_visite"}


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
    from features import golden_set as GS, role_perms as RP
    from services import llm

    db = server.db
    GS.seed(db)
    # The demo shop lives on 28 Oct 2026 (GS.DEMO_NOW): read its 30 days from
    # there, as the golden run does — on the real clock its revenue left the
    # window by late November and the file proved nothing (found 2026-11-09, PR #454).
    from features import copilot as K, copilot_tools as CT
    K._now = lambda: GS.DEMO_NOW
    CT.NOW = lambda: GS.DEMO_NOW
    db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"user_per_min": 100000, "shop_day_share": 1.0}}, upsert=True)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test", timeout=60) as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def manager(email, stores, **off):
        view = {p["key"]: "view" for p in RP.PAGES}
        view["ai"] = "edit"
        db.users.delete_many({"email": email})
        db.users.insert_one({"email": email, "role": "manager", "tenant_id": GS.SALON, "active": True, "branch_ids": stores,
                             "perms": {b: {**view, **off} for b in stores}})
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": "manager", "tenant_id": GS.SALON})}

    prompts = []

    def model(system, user):
        prompts.append(user)
        return json.dumps({"reponse": "Voici ce que je peux vous dire pour le moment."})

    def facts_for(headers, message="Mes chiffres ?"):
        prompts.clear()
        llm._force_complete = model
        r = http("POST", "/api/owner/copilot/chat", headers, json={"message": message})
        llm._force_complete = None
        m = re.search(r"Données du commerce \(JSON\) :\n(\{.*\})(?: Pour ce qui[^\n]*)?\n\nQuestion", prompts[0], re.S) if prompts else None
        return (json.loads(m.group(1)) if m else None), r

    ACCOUNT = GS.ACCOUNTS["sans_ca"][0]
    OWNER = GS.headers("owner")
    NO_CA = GS.headers("sans_ca")

    print("Le propriétaire : rien ne change")
    f, r = facts_for(OWNER)
    check("every figure is there", ANALYTICS <= set(f) and CLIENTS <= set(f) and {"produit_star", "recommandations"} <= set(f), sorted(f or {}))
    check("nothing is said to be locked", "acces_limite" not in f)
    owner_ca = f["ca_30j_eur"]
    check("the demo shop has revenue (else this file proves nothing)", owner_ca > 100, owner_ca)
    check("a period question has its figures", "periode_demandee" in facts_for(OWNER, "Mes chiffres de la semaine dernière ?")[0])

    print("Manager sans Analyses, Insights, Catalogue")
    f, r = facts_for(NO_CA)
    check("no visits, revenue, basket, best day, forecast", not (ANALYTICS & set(f)), sorted(f))
    check("no star product", "produit_star" not in f)
    check("no recommendations", "recommandations" not in f)
    check("no figure of a period he asked for", "periode_demandee" not in facts_for(NO_CA, "Mes chiffres de la semaine dernière ?")[0])
    check("clients stay: the Clients page is his", CLIENTS <= set(f))
    check("the model is told what is locked, so it says so", {"Analyses", "Insights", "Catalogue produits"} <= set(f.get("acces_limite") or []), f.get("acces_limite"))
    check("the owner's revenue is nowhere in the prompt", str(owner_ca) not in prompts[0] if prompts else False)

    print("La réponse de secours (modèle absent)")
    llm._force_complete = None
    r = http("POST", "/api/owner/copilot/chat", NO_CA, json={"message": "Quel est mon chiffre d'affaires ce mois-ci ?"})
    j = r.json()
    check("no figure, and it says why", r.status_code == 200 and j["source"] == "facts" and "€" not in j["reply"] and "Analyses" in j["reply"] and "accès" in j["reply"].lower(), j.get("reply"))
    check("no button to a page he cannot open", not [a for a in j["actions"] if a.get("to") == "/dashboard/analytics"], j["actions"])
    r = http("POST", "/api/owner/copilot/chat", NO_CA, json={"message": "Que me conseilles-tu ?"})
    j = r.json()
    check("no recommendation with its estimated impact", "€" not in j["reply"] and "impact" not in j["reply"], j["reply"])
    check("not « pas assez de données », which would be untrue", "pas encore assez de données" not in j["reply"], j["reply"])
    j = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Quel est mon chiffre d'affaires ce mois-ci ?"}).json()
    check("the owner's fallback keeps its figures", "€" in j["reply"] and [a for a in j["actions"] if a.get("to") == "/dashboard/analytics"], j)

    print("Page par page")
    h = manager("a1@gs-salon.test", ["b1", "b2"], customers="none", segmentation="none")
    f, _ = facts_for(h)
    check("Clients off: no client counts", not (CLIENTS & set(f)) and "Clients" in f["acces_limite"], sorted(f))
    check("…Analyses on: the figures stay", ANALYTICS <= set(f))
    h = manager("a2@gs-salon.test", ["b1", "b2"], customers="none")
    check("segmentation alone opens the counts, like the tool", CLIENTS <= set(facts_for(h)[0]))
    h = manager("a3@gs-salon.test", ["b1", "b2"], campaigns="none")
    f, _ = facts_for(h)
    check("Campagnes off: no recent campaigns", "campagnes_recentes" not in f and "Campagnes" in f["acces_limite"], sorted(f))
    h = manager("a4@gs-salon.test", ["b1", "b2"], insights="none")
    f, _ = facts_for(h)
    check("Insights off only: figures yes, recommendations no", "recommandations" not in f and ANALYTICS <= set(f))
    h = manager("a5@gs-salon.test", ["b1", "b2"], catalogue="none")
    check("Catalogue off, Analyses on: the star product stays, like the tool", "produit_star" in facts_for(h)[0])
    h = manager("a6@gs-salon.test", ["b1", "b2"], analytics="none")
    check("Analyses off, Catalogue on: the star product stays, like the tool", "produit_star" in facts_for(h)[0])

    print("Un établissement sans le droit, l'autre avec")
    db.users.delete_many({"email": "a7@gs-salon.test"})
    view = {p["key"]: "view" for p in RP.PAGES}
    view["ai"] = "edit"
    db.users.insert_one({"email": "a7@gs-salon.test", "role": "manager", "tenant_id": GS.SALON, "active": True, "branch_ids": ["b1", "b2"],
                         "perms": {"b1": dict(view), "b2": {**view, "analytics": "none", "catalogue": "none"}}})
    h = {"Authorization": "Bearer " + auth.create_access_token({"sub": "a7@gs-salon.test", "role": "manager", "tenant_id": GS.SALON})}
    check("in the store where it is on: figures", ANALYTICS <= set(facts_for({**h, "X-Fidclic-Store": "b1"})[0]))
    check("in the store where it is off: none", not (ANALYTICS & set(facts_for({**h, "X-Fidclic-Store": "b2"})[0])))

    print("La page FidClic IA")
    d = http("GET", "/api/owner/copilot/page", NO_CA).json()
    check("no activity figures", d["activity"]["cards"] == [] and d["activity"].get("locked") is True, d["activity"])
    check("no forecast", d["forecast"]["days"] == [], d["forecast"])
    check("no recommendation without Insights", d["recommendations"]["total"] == 0 and d["recommendations"]["all"] == [], d["recommendations"]["total"])
    check("no opportunity with its euros", d["opportunities"]["total"] == 0, d["opportunities"]["total"])
    check("no growth estimate in euros", not d["growth"].get("euros"), d["growth"])
    d = http("GET", "/api/owner/copilot/page", OWNER).json()
    check("the owner's page is whole", d["activity"]["cards"] and d["forecast"]["days"] is not None and "locked" not in d["activity"]
          and d["recommendations"]["total"] > 0, d["activity"])

    print("Les autres comptes")
    check("staff still refused", http("POST", "/api/owner/copilot/chat", GS.headers("staff"), json={"message": "Mes chiffres ?"}).status_code == 403)
    check("nobody: refused", http("POST", "/api/owner/copilot/chat", {}, json={"message": "Mes chiffres ?"}).status_code in (401, 403))
    gare, _ = facts_for(GS.headers("gare"))
    check("the Gare manager sees his store's figures, below the shop's", ANALYTICS <= set(gare) and gare["ca_30j_eur"] < owner_ca, (gare.get("ca_30j_eur"), owner_ca))

    print("Les ruptures de visites (/api/owner/ai/anomaly/recent)")
    now = dt.datetime.now(dt.timezone.utc)
    db.visits.delete_many({"tenant_id": GS.SALON})      # the demo's own visits fall inside these two weeks, depending on today's date
    db.visits.insert_many([{"id": f"an{i}", "tenant_id": GS.SALON, "customer_id": "x", "branch_id": b, "visit_time": now - dt.timedelta(days=d), "amount_paid": 5}
                           for i, (b, d) in enumerate([("b1", 1), ("b1", 2), ("b1", 3), ("b2", 1), ("b1", 9), ("b2", 9), ("b2", 10)])])
    db.visits.insert_one({"id": "an-other", "tenant_id": GS.AUTRE, "customer_id": "y", "visit_time": now - dt.timedelta(days=1), "amount_paid": 777})
    url = "/api/owner/ai/anomaly/recent"
    r = http("GET", url, NO_CA)
    check("Analyses off: refused, no counts", r.status_code == 403 and "current" not in r.text, (r.status_code, r.text[:160]))
    a = http("GET", url, GS.headers("gare")).json()["anomalies"][0]
    check("the Gare manager: his store only", (a["current"], a["previous"]) == (1, 2), a)
    a = http("GET", url, {**OWNER, "X-Fidclic-Store": "b1"}).json()["anomalies"][0]
    check("the owner in one store: that store", (a["current"], a["previous"]) == (3, 1), a)
    a = http("GET", url, OWNER).json()["anomalies"][0]
    check("the owner, no store chosen: the whole shop, never another shop", a["current"] >= 4 and a["previous"] >= 3, a)
    h = manager("a8@gs-salon.test", ["b1", "b2"], ai="none")
    check("Analyses on, FidClic IA off: this is an Analyses figure", http("GET", url, h).status_code == 200)
    check("nobody: refused", http("GET", url, {}).status_code in (401, 403))
    check("staff: refused", http("GET", url, GS.headers("staff")).status_code == 403)

    print("Une seule lecture du compte")
    real = RP._db.users
    reads = [0]

    class Spy:
        def __getattr__(self, a):
            return getattr(real, a)

        def find_one(self, *a, **k):
            reads[0] += 1
            return real.find_one(*a, **k)

    class Db:
        def __getattr__(self, a):
            return Spy() if a == "users" else getattr(db, a)
    pages = ("analytics", "catalogue", "customers", "segmentation", "insights", "campaigns")
    token = auth.TokenData(email=ACCOUNT, role="manager", tenant_id=GS.SALON)
    check("open_pages says the same as may, page by page", RP.open_pages(token, pages) == {p for p in pages if RP.may(token, p, "view")})
    check("…only the pages asked", RP.open_pages(token, ("customers",)) == {"customers"} and RP.open_pages(token, ()) == set())
    check("…the owner: all, no token: none", RP.open_pages(auth.TokenData(email="o", role="business_owner", tenant_id=GS.SALON), pages) == set(pages)
          and RP.open_pages(None, pages) == set())
    check("…another shop's token: none", RP.open_pages(auth.TokenData(email=ACCOUNT, role="manager", tenant_id=GS.AUTRE), pages) == set())
    RP._db = Db()
    try:
        http("GET", "/api/owner/copilot/page", NO_CA)
        page_reads = reads[0]
        reads[0] = 0
        http("GET", "/api/owner/copilot/page", OWNER)
        owner_reads = reads[0]
        reads[0] = 0
        llm._force_complete = model
        http("POST", "/api/owner/copilot/chat", NO_CA, json={"message": "Bonjour"})
        llm._force_complete = None
        chat_reads = reads[0]
    finally:
        RP._db = db
    check("the page, a manager: at most 2 reads (the guard + the figures)", page_reads <= 2, page_reads)
    check("the page, the owner: none", owner_reads == 0, owner_reads)
    check("the chat, a manager: at most 3 (the guard, the figures, the tools)", chat_reads <= 3, chat_reads)

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
