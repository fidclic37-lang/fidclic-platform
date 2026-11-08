"""
« Comment faire… ? » / « Où je vois… ? » (golden set, #427): the Copilote did not
know FidClic's own pages. It now gets the menu as a guide in its prompt, a
read-only « aide » tool over the support articles, and, with no model, a
plain answer naming the page and a button to it.

Run: cd api && /usr/local/bin/python3 tests/test_copilot_howto.py
"""
import asyncio
import contextlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-howto")
os.environ.setdefault("DISABLE_SEED", "1")
for _k in ("ANTHROPIC_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "GROQ_API_KEY", "NVIDIA_API_KEY"):
    os.environ.pop(_k, None)
passed = failed = 0


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", str(show)[:500])
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from features import app_guide as G, copilot_tools as CT, golden_set as GS, role_perms as RP
    from features.golden_set import fold
    from services import llm
    import httpx

    db = server.db
    GS.seed(db)
    db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"user_per_min": 100000}}, upsert=True)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test", timeout=60) as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    OWNER, NO_CA = GS.headers("owner"), GS.headers("sans_ca")
    how = [q for q in GS.questions() if q["type"] == "comment" and q["account"] == "owner"]
    check("the golden set's how-to questions are here", len(how) >= 15, len(how))

    print("Sans modèle : la page, et un bouton vers elle")
    for q in how:
        page = q["need"][0]["value"][0]
        r = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": q["text"]}).json()
        to = [a.get("to") for a in r["actions"] if a.get("kind") == "navigate"]
        check(f"{q['text'][:52]} → « {page} »", page in fold(r["reply"]) and to, (r["reply"], r["actions"]))

    print("Le guide dans le prompt")
    text = G.guide_text()
    for p in RP.PAGES:
        if p.get("to"):
            check(f"the guide names « {p['label']} »", p["label"] in text)
    check("not the hidden permission rows", "Créer et modifier les rôles" not in text)
    seen = []
    llm._force_complete = lambda s, u: seen.append(s) or json.dumps({"reponse": "Ouvrez la page Parrainage dans le menu."})
    http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Comment activer le parrainage ?"})
    llm._force_complete = None
    check("…sent to the model", seen and "Parrainage" in seen[0] and "Où trouver quoi" in seen[0], seen[:1])

    print("L'outil « aide »")
    import auth
    owner_tok = auth.TokenData(email=GS.ACCOUNTS["owner"][0], role="business_owner", tenant_id=GS.SALON)
    noca_tok = auth.TokenData(email=GS.ACCOUNTS["sans_ca"][0], role="manager", tenant_id=GS.SALON)
    check("open to the owner", "aide" in CT.available(owner_tok))
    check("open to any account with FidClic IA", "aide" in CT.available(noca_tok))
    from features import store_scope as S
    r = CT.run(owner_tok, None, S.resolve(owner_tok, None), "aide", {"question": "Comment ajouter un membre de mon équipe ?"})
    check("it reads the support article and the page", r["ok"] and any("equipe" in fold(a["titre"]) for a in r["data"]["articles"])
          and "Équipe" in r["data"]["page"]["nom"], r)
    check("its source is the help", r["source"]["label"] == "Aide FidClic", r.get("source"))
    r = CT.run(owner_tok, None, S.resolve(owner_tok, None), "aide", {"question": ""})
    check("an empty question is an error, said plainly", not r["ok"] and r["erreur"])

    print("Le reste ne change pas")
    r = http("POST", "/api/owner/copilot/chat", OWNER, json={"message": "Quel est mon chiffre d'affaires ce mois-ci ?"}).json()
    check("a figures question still gets figures", "€" in r["reply"], r["reply"])
    r = http("POST", "/api/owner/copilot/chat", NO_CA, json={"message": "Où je vois mes statistiques détaillées ?"}).json()
    check("a page the account cannot open: named, and said so", "analyses" in fold(r["reply"]) and "acces" in fold(r["reply"]), r["reply"])
    check("no question about a page: no guess", G.page_for("Bonjour, ça va ?") is None and G.page_for("") is None)

    print()
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
