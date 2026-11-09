"""
The Golden set's shadow replay (user, 2026-11-09, part C): the owners' own
Copilote questions, asked again in production with the model being tried —
nothing kept, nothing billed to the shop, each answer read by the live checks
and set beside the answer the owner got.

Run: cd api && python3 tests/test_golden_shadow.py
"""
import asyncio
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-golden-shadow")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    from features import golden_shadow as SH, ai_routing as AR
    from services import llm

    db = server.db
    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    for tid, name, extra in (("a", "Barbier A", {}), ("b", "Café B", {}), ("off", "Fleuriste Off", {"golden_real_off": True}),
                             ("demo1", "Démo", {"demo": True})):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": name, "plan": "vip", "is_active": True, "subscription_status": "active", **extra})
        db.users.insert_one({"email": f"o@{tid}.fr", "role": "business_owner", "tenant_id": tid, "active": True})
        db.customers.insert_one({"id": f"{tid}-c1", "tenant_id": tid, "name": "Marie Durand", "phone": "0612345678",
                                 "visits": 3, "created_at": now - dt.timedelta(days=40)})
        db.visits.insert_one({"id": f"{tid}-v1", "tenant_id": tid, "customer_id": f"{tid}-c1", "amount_paid": 25.0,
                              "visit_time": now - dt.timedelta(days=1)})

    clock = [0]

    def said(tid, q, a, days=1, **kw):
        clock[0] += 1                            # each question its own minute, as in a real chat
        at = now - dt.timedelta(days=days, minutes=clock[0])
        db.copilot_chats.insert_many([
            {"tenant_id": tid, "by": f"o@{tid}.fr", "role": "user", "text": q, "at": at, **kw},
            {"id": f"m-{tid}-{q[:6]}-{days}", "tenant_id": tid, "by": f"o@{tid}.fr", "role": "assistant", "text": a, "source": "model",
             "at": at + dt.timedelta(milliseconds=1)}])
    said("a", "Combien de visites ce mois-ci ?", "Vous avez eu 1 visite ce mois-ci.")
    said("a", "Combien de visites ce mois-ci ?", "Vous avez eu 1 visite ce mois-ci.", days=2)          # the same question twice
    said("a", "Qui est ma meilleure cliente ?", "Votre meilleure cliente est Marie Durand.")
    said("b", "Quel est mon chiffre d'affaires ?", "Votre chiffre d'affaires est de 25 €.")
    said("b", "Retiens que je ferme le lundi", "C'est noté.", memo=True)                             # a « Retiens que… »
    said("b", "Question d'un super admin", "…", view_by="admin@fidclic.fr")                          # an admin in the account
    said("off", "Combien de visites ?", "1 visite.")                                                 # the shop said no
    said("demo1", "Combien de visites ?", "1 visite.")
    said("a", "Une très vieille question", "…", days=40)

    A = {"Authorization": "Bearer " + auth.create_access_token({"sub": "sa@fidclic.fr", "role": "super_admin"})}
    db.users.insert_one({"email": "sa@fidclic.fr", "role": "super_admin"})
    O = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@a.fr", "role": "business_owner", "tenant_id": "a"})}

    print("\n1. Which real questions are replayed")
    picked = SH.pick(10, now)
    texts = [p["question"] for p in picked]
    check("only shops in the real-data test (not turned off, not a demo)", {p["tenant_id"] for p in picked} == {"a", "b"})
    check("no « Retiens que… », no super admin's question, nothing older than 14 days",
          not any("Retiens" in t or "super admin" in t or "vieille" in t for t in texts))
    check("the same question once per shop", texts.count("Combien de visites ce mois-ci ?") == 1)
    check("each with the answer the owner got", all(p["old"] for p in picked))
    check("shops take turns", [p["tenant_id"] for p in picked][:2] in (["a", "b"], ["b", "a"]))
    check("a limit is a limit", len(SH.pick(1, now)) == 1)

    print("\n2. A run: the question asked again, nothing kept, nothing billed to the shop")
    chats_before = db.copilot_chats.count_documents({})
    seen_models = []

    from features import ai_meter as AM
    billed = []

    def model(system, user):
        seen_models.append(AR.model_for("copilot"))
        billed.append(AM._who(AM._ctx.get() or {}))
        user = user.split("Question du commerçant")[-1]          # (the memory carries past questions too)
        if "meilleure cliente" in user:
            return json.dumps({"reponse": "Votre meilleure cliente est Marie Durand, joignable au 06 12 34 56 78."})
        if "chiffre d'affaires" in user:
            return json.dumps({"reponse": "Votre chiffre d'affaires est de 25 € ce mois-ci."})
        return json.dumps({"reponse": "Vous avez eu 1 visite ce mois-ci."})
    llm._force_complete = model
    os.environ.setdefault("ANTHROPIC_API_KEY", "test")
    r = http("POST", "/api/admin/ai/shadow", A, json={"count": 10, "routes": {"copilot": AR.FABLE}})
    check("a super admin starts a run", r.status_code == 200)
    rid = r.json()["id"]
    for _ in range(10):
        st = http("POST", f"/api/admin/ai/shadow/{rid}/step", A).json()
        if st["status"] == "done":
            break
    run = http("GET", f"/api/admin/ai/shadow/{rid}", A).json()
    check("every question answered again", run["status"] == "done" and run["done"] == run["total"] == 3)
    check("with the model being tried", seen_models and set(seen_models) == {AR.FABLE})
    check("the live table did not move", AR.model_for("copilot") == AR.DEFAULTS["copilot"])
    check("nothing kept: no chat, no learning-log row, no memory",
          db.copilot_chats.count_documents({}) == chats_before and db.ai_examples.count_documents({}) == 0
          and db.copilot_memory.count_documents({}) == 0)
    check("nothing on the shops' AI budget", not any(k for k in db.ai_spend.distinct("_id") if ":a:" in str(k) or ":b:" in str(k)
                                                     or str(k).endswith(":a") or str(k).endswith(":b")))
    check("billed to the platform, under the run's name", billed and all(b == (None, f"golden-shadow:{rid}") for b in billed))
    items = {i["question"]: i for i in run["items"]}
    best = items["Qui est ma meilleure cliente ?"]
    check("the new answer giving a phone: a regression, said why", best["verdict"] == "regression" and "contact" in best["new"]["problems"])
    check("…the client's name hidden on the page", "Marie" not in json.dumps(run["items"]))
    ok = items["Combien de visites ce mois-ci ?"]
    check("a good answer, as good as before: ok", ok["verdict"] == "ok" and ok["old"]["problems"] == [])
    check("the summary counts them", run["summary"]["regression"] == 1 and run["summary"]["ok"] == 2)

    print("\n3. Limits and doors")
    check("an owner can't start or read one", http("POST", "/api/admin/ai/shadow", O, json={"count": 5}).status_code == 403
          and http("GET", f"/api/admin/ai/shadow/{rid}", O).status_code == 403)
    check("an unknown model is refused", http("POST", "/api/admin/ai/shadow", A, json={"count": 5, "routes": {"copilot": "gpt-9"}}).status_code == 400)
    check("at most 50 questions", http("POST", "/api/admin/ai/shadow", A, json={"count": 500}).status_code == 422)
    r = http("POST", "/api/admin/ai/shadow", A, json={"count": 10, "max_eur": 0.5})
    rid2 = r.json()["id"]
    db.ai_calls.insert_one({"user": f"golden-shadow:{rid2}", "eur": 0.6, "tenant_id": None, "feature": "copilot"})
    for _ in range(5):
        st = http("POST", f"/api/admin/ai/shadow/{rid2}/step", A).json()
        if st["status"] != "running":
            break
    check("its own budget spent: it stops, said so", st["status"] == "stopped" and st["why"] == "budget")
    r = http("POST", "/api/admin/ai/shadow", A, json={"count": 10})
    rid3 = r.json()["id"]
    a = SH.step(rid3, budget_s=0.0001)
    b = SH.step(rid3, budget_s=30)
    run3 = http("GET", f"/api/admin/ai/shadow/{rid3}", A).json()
    check("two steps at once never answer the same question twice", run3["done"] == run3["total"]
          and len({i["question"] + i["tenant"] for i in run3["items"]}) == len(run3["items"]))
    check("the list of runs", len(http("GET", "/api/admin/ai/shadow", A).json()["runs"]) == 3)
    llm._force_complete = None

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
