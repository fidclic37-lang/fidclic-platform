"""
« Produits qui font revenir » — the actions (PR3, user 2026-10-31).

    · One-shot buyers who did not come back → an offer on the Aimant product
    · new clients (one visit, still in their window) → the Aimant product for
      the 2nd visit
    · where: Insights, Copilote, Tableau de bord, Fiche client — Pro AI only
    · the témoin's answer on the product card: « 42 % revenus vs 18 % témoin »

The shop below is made up: Coupe brings people back, Soin visage does not,
Gel is in between. Local mongomock only.

Run: cd api && /usr/local/bin/python3 tests/test_product_actions.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-product-actions")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    from features import product_return as PR
    from features import product_actions as PA
    from features import insights_page as IP
    from features import temoin as T
    from features import copilot_tools as CT
    from features import store_scope as S

    db = server.db
    NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    PA._now = lambda: NOW
    IP._now = lambda: NOW
    T._now = lambda: NOW
    CT.NOW = lambda: NOW

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, tid, **extra):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid, **extra})}

    def TD(email, role, tid):
        return type("TD", (), {"email": email, "role": role, "tenant_id": tid, "view_by": None, "view_only": False})()

    # ------------------------------------------------------------------ pure pieces
    print("Pièces simples")
    check("a product's ref is the same whatever the order of its keys", PA.ref(["b", "a"]) == PA.ref(["a", "b"]))
    check("…10 hex characters", len(PA.ref(["p1"])) == 10 and all(ch in "0123456789abcdef" for ch in PA.ref(["p1"])))
    check("…and differs from another product's", PA.ref(["p1"]) != PA.ref(["p2"]))

    from features import reco_journal as RJ
    check("a « prc: » key names a client: never journaled as an idea", RJ.clean("prc:c12") is None)
    check("the product actions are one family in the super admin's table",
          RJ.family("pr:os:0123456789") == "pr" and RJ.family("pr:new:0123456789") == "pr")

    d = lambda days: NOW - dt.timedelta(days=days)          # noqa: E731
    occ = lambda days, items, store="main": {"day": PR.paris_day(d(days)), "at": d(days), "store": store,  # noqa: E731
                                             "items": set(items), "amount": 20.0}
    tl = {
        "late": [occ(30, ["s"])],                    # took Soin, silent 30 days > window 21
        "early": [occ(10, ["s"])],                   # took Soin 10 days ago: still in their chance
        "gone": [occ(150, ["s"])],                   # silent 150 days: too long ago to ask
        "edge_w": [occ(21, ["s"])],                  # exactly the window: late
        "edge_max": [occ(120, ["s"])],               # exactly 120 days: still asked
        "edge_out": [occ(121, ["s"])],               # 121: no longer
        "back": [occ(60, ["s"]), occ(40, [])],       # took Soin, came back after: not lapsed
        "other": [occ(30, ["c"])],                   # took Coupe: not this product
        "gare": [occ(30, ["s"], "b2")],              # Soin at the other store
        "new": [occ(5, ["c"])],                      # one visit 5 days ago
        "new_old_member": [occ(5, ["c"])],           # one visit, but a member for a year
        "two": [occ(9, ["c"]), occ(3, [])],          # two visits: not new
        "new_late": [occ(25, ["c"])],                # one visit 25 days ago: past the window
    }
    joined = {k: v[0]["at"] for k, v in tl.items()}     # joined at their first visit
    joined["new_old_member"] = d(365)
    joined["unknown"] = None
    groups = {"S": {"s"}, "SG": {"s", "g"}}
    a = PA.audiences(tl, PR.paris_day(NOW), 21, joined, NOW, groups)
    check("lapsed: silent past the window, up to 120 days, last visit with the product",
          set(a["one_shot"]["S"]) == {"late", "edge_w", "edge_max", "gare"}, sorted(a["one_shot"]["S"]))
    check("a « toujours ensemble » pair counts any of its products", set(a["one_shot"]["SG"]) == set(a["one_shot"]["S"]))
    check("new: one visit inside the window, joined recently",
          set(a["new"]) == {"new", "early"}, sorted(a["new"]))
    a2 = PA.audiences(tl, PR.paris_day(NOW), 21, joined, NOW, groups, store="b2")
    check("one establishment: only the clients whose last visit was there", set(a2["one_shot"]["S"]) == {"gare"}, a2)
    check("nobody → empty lists, never a crash", PA.audiences({}, PR.paris_day(NOW), 21, {}, NOW, groups)
          == {"one_shot": {"S": [], "SG": []}, "new": []})
    tl_none = {"x": [occ(30, ["s"])]}
    check("a client with no join date is not « new » unless their visit is recent",
          PA.audiences(tl_none, PR.paris_day(NOW), 21, {}, NOW, groups)["new"] == [])

    # ------------------------------------------------------------------ the shop
    rnd = random.Random(7)
    db.tenants.insert_many([
        {"id": "s", "slug": "s", "name": "Salon", "sector": "salon", "activity_key": "barbier", "plan": "vip",
         "is_active": True, "subscription_status": "active", "product_return_window_days": 21},
        {"id": "g", "slug": "g", "name": "Gold", "sector": "salon", "activity_key": "barbier", "plan": "gold",
         "is_active": True, "subscription_status": "active"},
        {"id": "x", "slug": "x", "name": "Autre", "sector": "salon", "plan": "vip", "is_active": True,
         "subscription_status": "active"},
    ])
    db.users.insert_many([{"email": "o@s", "role": "business_owner", "tenant_id": "s", "active": True},
                          {"email": "o@g", "role": "business_owner", "tenant_id": "g", "active": True},
                          {"email": "o@x", "role": "business_owner", "tenant_id": "x", "active": True}])
    db.tenant_catalog.insert_one({"tenant_id": "s", "items": [{"id": "p1", "name": "Coupe"}, {"id": "p2", "name": "Soin visage"},
                                                             {"id": "p3", "name": "Gel"}]})
    NAMES = {"p1": "Coupe", "p2": "Soin visage", "p3": "Gel"}
    RATE = {"p1": 0.85, "p2": 0.1, "p3": 0.5}
    custs, visits, only = [], [], {}
    for i in range(360):
        pid = ["p1", "p2", "p3"][i % 3]
        cid = f"c{i}"
        first = NOW - dt.timedelta(days=rnd.randint(25, 400), hours=rnd.randint(0, 6))
        custs.append({"id": cid, "tenant_id": "s", "name": f"Client {i}", "created_at": first, "deleted_at": None,
                      "visits": 1})
        visits.append({"id": f"v{i}a", "tenant_id": "s", "customer_id": cid, "visit_time": first, "amount_paid": 20,
                       "items": [{"item_id": pid, "name": NAMES[pid]}]})
        if rnd.random() < RATE[pid]:
            visits.append({"id": f"v{i}b", "tenant_id": "s", "customer_id": cid, "amount_paid": 20, "items": [],
                           "visit_time": first + dt.timedelta(days=rnd.randint(5, 18))})
        else:
            only[cid] = (pid, first)
    new_ids = []
    for i in range(6):
        cid = f"n{i}"
        new_ids.append(cid)
        custs.append({"id": cid, "tenant_id": "s", "name": f"Nouveau {i}", "created_at": d(3), "deleted_at": None, "visits": 1})
        visits.append({"id": f"vn{i}", "tenant_id": "s", "customer_id": cid, "visit_time": d(3), "amount_paid": 20,
                       "items": [{"item_id": "p1", "name": "Coupe"}]})
    custs.append({"id": "old", "tenant_id": "s", "name": "Ancien", "created_at": d(300), "deleted_at": None, "visits": 1})
    visits.append({"id": "vold", "tenant_id": "s", "customer_id": "old", "visit_time": d(3), "amount_paid": 20,
                   "items": [{"item_id": "p1", "name": "Coupe"}]})
    custs.append({"id": "xc", "tenant_id": "x", "name": "Pas à vous", "created_at": d(40), "deleted_at": None})
    db.customers.insert_many(custs)
    db.visits.insert_many(visits)
    today = PR.paris_day(NOW)
    lapsed_soin = {cid for cid, (pid, at) in only.items()
                   if pid == "p2" and 21 <= (today - PR.paris_day(at)).days <= 120}

    print("\nLe calcul de la semaine garde les actions (des nombres, jamais des noms)")
    PR.compute("s", NOW)
    doc = PR.result("s")
    prods = {p["name"]: p for p in doc["views"]["first"]["products"]}
    check("the made-up shop reads as made: Coupe aimant, Soin visage one-shot",
          prods["Coupe"]["bucket"] == "aimant" and prods["Soin visage"]["bucket"] == "one_shot",
          {k: v["bucket"] for k, v in prods.items()})
    check("each weighed product keeps its ref and its products' names",
          prods["Coupe"].get("ref") == PA.ref(["p1"]) and prods["Coupe"].get("names") == ["Coupe"], prods["Coupe"])
    act = doc.get("actions") or {}
    check("the Aimant to offer is Coupe", (act.get("aimant") or {}).get("name") == "Coupe", act)
    os_ = {x["name"]: x for x in act.get("one_shot") or []}
    check("Soin visage's lapsed buyers are counted", (os_.get("Soin visage") or {}).get("lapsed") == len(lapsed_soin),
          (os_.get("Soin visage"), len(lapsed_soin)))
    check("the new clients still in their window are counted (not the old member)", act.get("new") == 6, act.get("new"))
    check("no client id in the stored document", not any(c in json.dumps(doc, default=str) for c in ("\"c1\"", "\"n0\"", "\"old\"")))
    REF_SOIN, REF_COUPE = PA.ref(["p2"]), PA.ref(["p1"])

    # ------------------------------------------------------------------ the composer
    print("\nLe composer pré-rempli")
    O = tok("o@s", "business_owner", "s")
    URL = "/api/owner/insights/templates/"
    r = http("GET", URL + f"pr:os:{REF_SOIN}", O)
    j = r.json()
    check("One-shot buyers → an offer to set (step 1)", r.status_code == 200 and j.get("kind") == "offre" and j.get("start_step") == 1, j)
    check("…on the Aimant product", "Coupe" in j.get("message", "") and "Coupe" in j.get("title", ""), j)
    check("…sent to exactly the lapsed buyers", set((j.get("audience") or {}).get("ids") or []) == lapsed_soin,
          len((j.get("audience") or {}).get("ids") or []))
    check("…and the audience says who they are", "Soin visage" in (j.get("audience") or {}).get("label", ""), j.get("audience"))
    r = http("GET", URL + f"pr:new:{REF_COUPE}", O)
    check("new clients → the Aimant for their 2nd visit", r.status_code == 200 and set(r.json()["audience"]["ids"]) == set(new_ids)
          and "Coupe" in r.json()["message"], r.text[:300])
    check("an Aimant asked as a One-shot → 404", http("GET", URL + f"pr:os:{REF_COUPE}", O).status_code == 404)
    for bad in ("pr:os:zzzzzzzzzz", "pr:os:.*", "pr:os:", "pr:new:" + "a" * 40, "pr:xx:" + REF_SOIN):
        check(f"a made-up key ({bad[:16]}) → 404", http("GET", URL + bad, O).status_code == 404)
    some = sorted(lapsed_soin)[0]
    r = http("GET", URL + f"prc:{some}", O)
    check("Fiche client « Contacter »: that one client, the Aimant named",
          r.status_code == 200 and r.json()["audience"]["ids"] == [some] and "Coupe" in r.json()["message"], r.text[:300])
    check("another shop's client → 404", http("GET", URL + "prc:xc", O).status_code == 404)
    db.product_return.insert_one({**{k: v for k, v in doc.items() if k != "_id"}, "tenant_id": "g"})
    G = tok("o@g", "business_owner", "g")
    check("Pro (not Pro AI): the actions are locked (403)", http("GET", URL + f"pr:os:{REF_SOIN}", G).status_code == 403)
    X = tok("o@x", "business_owner", "x")
    check("a shop with no analysis → 404, never another shop's", http("GET", URL + f"pr:os:{REF_SOIN}", X).status_code == 404)

    # ------------------------------------------------------------------ Insights
    print("\nInsights")
    items = {i["key"]: i for i in IP._payload("s", NOW)["opportunities"]["all"]}
    one = items.get("produit_one_shot")
    check("a card for the One-shot product", one is not None, list(items))
    check("…naming both products and the clients",
          one and "Soin visage" in one["title"] and "Coupe" in one["body"] and str(len(lapsed_soin)) in one["body"], one)
    check("…its button opens the composer on them", one and one["cta"]["template"] == f"pr:os:{REF_SOIN}", one and one["cta"])
    new = items.get("produit_aimant_nouveaux")
    check("a card for the new clients", new and new["cta"]["template"] == f"pr:new:{REF_COUPE}" and "6" in new["body"], new)
    gi = {i["key"] for i in IP._payload("g", NOW)["opportunities"]["all"]}
    check("Pro: no product cards", not ({"produit_one_shot", "produit_aimant_nouveaux"} & gi), gi)

    # ------------------------------------------------------------------ Tableau de bord
    print("\nTableau de bord")
    r = http("GET", "/api/owner/home/overview", O)
    pr = r.json().get("product_return") or {}
    check("the small card: top Aimant and top One-shot",
          (pr.get("aimant") or {}).get("name") == "Coupe" and (pr.get("one_shot") or {}).get("name") == "Soin visage", pr)
    check("…with how many of 10 come back", isinstance((pr.get("aimant") or {}).get("back"), int), pr)
    check("Pro: no card", http("GET", "/api/owner/home/overview", G).json().get("product_return") is None)

    # ------------------------------------------------------------------ Fiche client
    print("\nFiche client")
    r = http("GET", f"/api/owner/clients/{some}/profil", O)
    p = r.json().get("produits") or {}
    check("a Soin visage client: the tag says One-shot",
          {"name": "Soin visage", "bucket": "one_shot"} in [{k: t[k] for k in ("name", "bucket")} for t in p.get("tags") or []], p)
    check("…and Coupe is suggested, with the prefilled message",
          (p.get("suggest") or {}).get("name") == "Coupe" and (p.get("suggest") or {}).get("template") == f"prc:{some}", p)
    coupe_client = next(cid for cid, (pid, _) in only.items() if pid == "p1")
    p = http("GET", f"/api/owner/clients/{coupe_client}/profil", O).json().get("produits") or {}
    check("a client who already takes Coupe: tagged Aimant, nothing suggested",
          any(t["bucket"] == "aimant" for t in p.get("tags") or []) and not p.get("suggest"), p)
    check("Pro: no product block on the fiche",
          "produits" not in http("GET", f"/api/owner/clients/{some}/profil", G).json()
          or not http("GET", f"/api/owner/clients/{some}/profil", G).json().get("produits"))

    # ------------------------------------------------------------------ Copilote
    print("\nCopilote")
    OT = TD("o@s", "business_owner", "s")
    res = CT.run(OT, None, S.resolve(OT, None), "produits_retour", {}, NOW)
    data = res.get("data") or {}
    check("the tool answers", res.get("ok"), res)
    check("…with the Aimant and how many come back",
          any(x.get("nom") == "Coupe" and "sur_10_reviennent" in x for x in data.get("aimants") or []), data)
    check("…the One-shot and its lapsed buyers",
          any(x.get("nom") == "Soin visage" for x in data.get("one_shot") or [])
          and (data.get("actions") or {}).get("nouveaux_clients") == 6, data)
    check("…and where to see it", res.get("source", {}).get("to") == "/dashboard/analytics#produits", res.get("source"))
    GT = TD("o@g", "business_owner", "g")
    gres = CT.run(GT, None, S.resolve(GT, None), "produits_retour", {}, NOW)
    check("Pro: the verdicts only", gres.get("ok") and "sur_10_reviennent" not in json.dumps(gres["data"]), gres)
    XT = TD("o@x", "business_owner", "x")
    jobs = db.ai_jobs.count_documents({})
    xres = CT.run(XT, None, S.resolve(XT, None), "produits_retour", {}, NOW)
    check("no analysis yet: said so, and the tool starts nothing (read-only)",
          xres.get("ok") and "statut" in xres["data"] and db.ai_jobs.count_documents({}) == jobs, xres)

    # ------------------------------------------------------------------ the témoin's answer
    print("\nLe test avec groupe témoin, sur la carte du produit")
    sent = [f"t{i}" for i in range(10)]
    held = [f"h{i}" for i in range(4)]
    at = NOW - dt.timedelta(days=20)
    db.campaigns.insert_one({"id": "k1", "tenant_id": "s", "status": "sent", "template": f"pr:os:{REF_SOIN}",
                             "sent_at": at, "recipient_ids": sent, "holdout_ids": held})
    db.visits.insert_many([{"id": f"tv{i}", "tenant_id": "s", "customer_id": c, "amount_paid": 20, "items": [],
                            "visit_time": at + dt.timedelta(days=3)} for i, c in enumerate(sent[:5] + held[:1])])
    db.campaigns.insert_one({"id": "k2", "tenant_id": "s", "status": "sent", "template": f"pr:new:{REF_COUPE}",
                             "sent_at": NOW - dt.timedelta(days=5), "recipient_ids": ["n0", "n1", "n2", "n3"],
                             "holdout_ids": ["n4", "n5"]})
    db.campaigns.insert_one({"id": "k3", "tenant_id": "x", "status": "sent", "template": f"pr:os:{REF_SOIN}",
                             "sent_at": at, "recipient_ids": ["zz"], "holdout_ids": ["zy"]})
    r = http("GET", "/api/owner/analyses/produits-retour", O)
    cards = {p["name"]: p for p in r.json()["views"]["first"]["products"]}
    t = cards["Soin visage"].get("test") or {}
    check("15 days over: « 50 % revenus vs 25 % témoin »", t.get("ready") and t.get("rate") == 50.0 and t.get("temoin_rate") == 25.0, t)
    check("…said to be on few clients (under 30 témoin)", t.get("enough") is False, t)
    t = cards["Coupe"].get("test") or {}
    check("a test still running: its result date", t.get("ready") is False and t.get("ready_on", "").startswith("2026-11-07"), t)
    check("another shop's campaign is never read", cards["Soin visage"]["test"].get("campaign") in (None, "k1"))
    acts = r.json().get("actions") or {}
    check("the page is told the actions (counts only)",
          (acts.get("aimant") or {}).get("name") == "Coupe" and acts.get("new") == 6, acts)
    g = http("GET", "/api/owner/analyses/produits-retour", G).json()
    check("Pro: no actions, no test, no ref", "actions" not in g and not any(
        "test" in p or "ref" in p for p in g["views"]["first"]["products"]), g.get("actions"))
    one = {i["key"]: i for i in IP._payload("s", NOW)["opportunities"]["all"]}.get("produit_one_shot")
    check("Insights repeats the test", one and "50 %" in one["body"] and "25 %" in one["body"], one and one["body"])

    # ------------------------------------------------------------------ old documents
    print("\nLes analyses d'avant (sans actions) sont refaites une fois")
    db.tenants.insert_one({"id": "m", "slug": "m", "name": "M", "plan": "vip", "is_active": True})
    db.visits.insert_one({"id": "vm", "tenant_id": "m", "customer_id": "cm", "visit_time": d(40),
                          "items": [{"item_id": "p1", "name": "Coupe"}]})
    db.product_return.insert_one({"tenant_id": "m", "store": "all", "built_at": d(1), "views": {}})
    started = PR.due(NOW)
    check("a document without actions is rebuilt even if fresh", "m" in started, started)
    check("…not one that has them", "s" not in started, started)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
