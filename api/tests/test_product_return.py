"""
« Produits qui font revenir » — which products bring clients back.

Run:
    cd api && python3 tests/test_product_return.py

The shop below is made up with effects hidden in it on purpose; the engine
has to find them, and must not be fooled by the two traps the user named
(2026-10-28): a product bought WITH a good one (Shampoo rides along with
Barbe) and a product sold in a bad season (Coffret in December).
"""
import datetime as dt
import math
import os
import random
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from features import product_return as PR
    from features import ai_jobs as JOBS

    db = server.db
    PR.init(db)
    JOBS.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    import asyncio
    import httpx

    class _Client:
        def _go(self, method, url, **kw):
            async def run():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                    return await ac.request(method, url, **kw)
            return asyncio.get_event_loop().run_until_complete(run())

        def get(self, url, **kw): return self._go("GET", url, **kw)
        def post(self, url, **kw): return self._go("POST", url, **kw)
        def put(self, url, **kw): return self._go("PUT", url, **kw)

    c = _Client()

    def tok(email, role, tid):
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tid})}

    NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.timezone.utc)
    sig = lambda x: 1 / (1 + math.exp(-x))

    # ------------------------------------------------------------------
    print("\nPure pieces")
    # ------------------------------------------------------------------
    check("a visit at 23:30 UTC on the DST night is the next Paris day",
          PR.paris_day(dt.datetime(2026, 3, 28, 23, 30, tzinfo=dt.timezone.utc)) == dt.date(2026, 3, 29))
    check("a naive date is read as UTC", PR.paris_day(dt.datetime(2026, 7, 1, 21, 59)) == dt.date(2026, 7, 1))
    check("default window = 2× the shop's rhythm", PR.window_for(21.0, None) == (42, "rythme"))
    check("a very fast shop still waits a week", PR.window_for(2.0, None) == (7, "rythme"))
    check("a very slow shop waits at most 180 days", PR.window_for(400.0, None) == (180, "rythme"))
    check("the owner's own days win", PR.window_for(21.0, 30) == (30, "personnalise"))
    check("nonsense days are ignored", PR.window_for(21.0, 2) == (42, "rythme")
          and PR.window_for(21.0, "abc") == (42, "rythme") and PR.window_for(21.0, 999) == (42, "rythme"))

    rnd = random.Random(3)
    rows = []
    for _ in range(4000):
        a, b = rnd.random() < .5, rnd.random() < .5
        act = [i for i, on in ((1, a), (2, b)) if on]
        rows.append((act, rnd.random() < sig(-0.3 + 1.0 * a)))
    beta, se = PR.fit(rows, 3, ridge=1.0)
    check("fit finds a real effect (≈ +1.0)", 0.75 < beta[1] < 1.25)
    check("fit finds no effect where there is none", abs(beta[2]) < 2 * se[2] + 0.05)
    check("standard errors are positive and small with lots of data", 0 < se[1] < 0.15)
    sep = [([1], True)] * 40 + [([], False)] * 40
    b2, s2 = PR.fit(sep, 2, ridge=1.0)
    check("a perfectly separating product stays finite (ridge)", all(math.isfinite(x) for x in b2 + s2) and b2[1] < 10)
    few = [([1], True)] * 3 + [([], i % 2 == 0) for i in range(200)]
    b3, _ = PR.fit(few, 2, ridge=2.0)
    check("3 lucky buyers are pulled towards the average (shrinkage)", b3[1] < 1.5)
    b4, s4 = PR.fit([], 2, ridge=1.0)
    check("no rows → zeros, no crash", b4 == [0.0, 0.0])

    # ------------------------------------------------------------------
    print("\nA made-up barber shop with hidden effects")
    # ------------------------------------------------------------------
    db.tenants.insert_one({"id": "t1", "name": "Le Barbier", "plan": "vip", "is_active": True,
                           "sector": "coiffure", "product_return_window_days": 30})
    db.users.insert_many([
        {"email": "owner@barbier.fr", "role": "business_owner", "tenant_id": "t1"},
        {"email": "owner@gold.fr", "role": "business_owner", "tenant_id": "tg"},
        {"email": "owner@silver.fr", "role": "business_owner", "tenant_id": "ts"},
        {"email": "staff@barbier.fr", "role": "staff", "tenant_id": "t1"},
    ])
    CAT = [("p-coupe", "Coupe", 20), ("p-barbe", "Barbe", 12), ("p-shampoo", "Shampoo", 6),
           ("p-colo", "Coloration", 45), ("p-gel", "Gel", 8), ("p-cire", "Cire", 9),
           ("p-coffret", "Coffret cadeau", 30), ("p-soin", "Soin visage", 25)]
    db.tenant_catalog.insert_one({"tenant_id": "t1", "items": [
        {"id": i, "name": n, "price": p, "category": "Prestations"} for i, n, p in CAT]})
    price = {i: p for i, _, p in CAT}
    name = {i: n for i, n, _ in CAT}

    rnd = random.Random(11)
    visits, customers, offer_uses = [], [], []
    truth = {"barbe": 0.9, "colo": -0.9, "december": -1.0}

    def line(pid, by_name=False):
        return ({"name": name[pid], "qty": 1, "price": price[pid]} if by_name else
                {"item_id": pid, "name": name[pid], "qty": 1, "price": price[pid]})

    for k in range(1500):
        cid = f"c{k}"
        first = NOW - dt.timedelta(days=rnd.randint(45, 700), hours=rnd.randint(0, 10))
        dec = first.astimezone(PR.PARIS).month == 12
        barbe = rnd.random() < .4
        shampoo = rnd.random() < (.6 if barbe else .1)        # rides along with Barbe
        colo = rnd.random() < .12
        gel = rnd.random() < .15                              # Gel and Cire: always together
        coffret = rnd.random() < (.5 if dec else .02)         # a December product
        soin = k < 12                                         # sold 12 times only
        basket = ["p-coupe"] + [p for p, on in (("p-barbe", barbe), ("p-shampoo", shampoo), ("p-colo", colo),
                                                ("p-gel", gel), ("p-cire", gel), ("p-coffret", coffret),
                                                ("p-soin", soin)) if on]
        branch = "b2" if k % 5 == 0 else None                 # one in five at the second store
        logit = -0.2 + truth["barbe"] * barbe + truth["colo"] * colo + truth["december"] * dec
        back = rnd.random() < sig(logit)
        gap = rnd.randint(3, 28) if back else rnd.randint(31, 120)
        items = [line(p, by_name=(k % 7 == 0)) for p in basket]   # some old lines carry no id
        visits.append({"id": f"v{k}a", "tenant_id": "t1", "customer_id": cid, "visit_time": first,
                       "amount_paid": float(sum(price[p] for p in basket)), "items": items, "branch_id": branch})
        if k % 10 == 0:                                       # a double scan the same day
            visits.append({"id": f"v{k}d", "tenant_id": "t1", "customer_id": cid,
                           "visit_time": first + dt.timedelta(minutes=20), "amount_paid": 0.0, "branch_id": branch})
        second = first + dt.timedelta(days=gap)
        if second < NOW and (back or rnd.random() < .5):
            # comes back at ANY store — one in three goes to the other one
            visits.append({"id": f"v{k}b", "tenant_id": "t1", "customer_id": cid, "visit_time": second,
                           "amount_paid": 20.0, "items": [line("p-coupe")],
                           "branch_id": ("b2" if k % 3 == 0 else None)})
        if k % 9 == 0:
            offer_uses.append({"tenant_id": "t1", "customer_id": cid, "campaign_id": "o1", "used_at": first})
        customers.append({"id": cid, "tenant_id": "t1", "name": f"Client {k}", "created_at": first, "visits": 2})

    # a client who bought Barbe 5 days ago has had no time to come back
    customers.append({"id": "fresh", "tenant_id": "t1", "name": "Nouveau", "created_at": NOW - dt.timedelta(days=5)})
    visits.append({"id": "vf", "tenant_id": "t1", "customer_id": "fresh", "visit_time": NOW - dt.timedelta(days=5),
                   "amount_paid": 32.0, "items": [line("p-coupe"), line("p-barbe")]})
    # a client from before the history the engine reads: never a « first purchase »
    customers.append({"id": "old", "tenant_id": "t1", "name": "Ancien", "created_at": NOW - dt.timedelta(days=2000)})
    visits.append({"id": "vo", "tenant_id": "t1", "customer_id": "old", "visit_time": NOW - dt.timedelta(days=200),
                   "amount_paid": 45.0, "items": [line("p-colo")]})
    # visits without products (the till skipped the picker)
    for k in range(300):
        visits.append({"id": f"vn{k}", "tenant_id": "t1", "customer_id": f"n{k}",
                       "visit_time": NOW - dt.timedelta(days=rnd.randint(1, 80)), "amount_paid": 15.0})
    db.visits.insert_many(visits)
    db.customers.insert_many(customers)
    db.offer_uses.insert_many(offer_uses)

    out = PR.compute("t1", NOW)
    res = PR.result("t1", "all")
    first = res["views"]["first"]
    prods = {p["name"]: p for p in first["products"]}

    print("\nWhat the engine says (first purchase)")
    check("the window is the owner's 30 days", res["window_days"] == 30 and res["window_source"] == "personnalise")
    check("a purchase younger than the window is not judged",
          first["n"] == 1500 and "fresh" not in str(first))
    check("a client older than the history is never a first purchase", prods["Coloration"]["clients"] < 1500 * .2)
    check("Barbe brings clients back → Aimant", prods["Barbe"]["bucket"] == "aimant" and prods["Barbe"]["ratio_low"] > 1)
    check("Coloration loses them → One-shot", prods["Coloration"]["bucket"] == "one_shot" and prods["Coloration"]["ratio_high"] < 1)
    check("Trap 4: Shampoo LOOKS good on its own (rides with Barbe)…",
          prods["Shampoo"]["raw_rate"] > first["base_rate"] + 0.05)
    check("…but with Barbe counted, Shampoo is Neutre", prods["Shampoo"]["bucket"] == "neutre"
          and prods["Shampoo"]["ratio_low"] <= 1 <= prods["Shampoo"]["ratio_high"])
    check("Trap 5: Coffret LOOKS bad on its own (sold in December)…",
          prods["Coffret cadeau"]["raw_rate"] < first["base_rate"] - 0.05)
    check("…but with the season counted, Coffret is not called One-shot", prods["Coffret cadeau"]["bucket"] != "one_shot")
    dec = [m for m in first["months"] if m["month"] == 12]
    check("December is kept and said on its own line", dec and dec[0]["rate"] < first["base_rate"])
    check("Gel and Cire always sell together → one entry « effet commun »",
          "Gel + Cire" in prods and "Gel" not in prods and "Cire" not in prods and prods["Gel + Cire"]["together"])
    check("Soin visage: 12 sales, no verdict, and how far from 30",
          prods["Soin visage"]["bucket"] == "insufficient" and prods["Soin visage"]["clients"] == 12
          and prods["Soin visage"]["needed"] == 30)
    check("Coupe in nearly every basket → nothing to compare it with, said honestly",
          prods["Coupe"]["bucket"] in ("neutre", "insufficient", "everywhere"))
    b = prods["Barbe"]
    check("x sur 10 range is ordered and inside 0–10", 0 <= b["back_low"] <= b["back"] <= b["back_high"] <= 10)
    check("a reliability word", b["fiabilite"] in ("haute", "moyenne", "faible"))
    check("median days to come back is inside the window", 3 <= b["days_back"] <= 28)
    check("90-day CA after the purchase, in euros", b["ca90"] is not None and b["ca90"] > 0)
    check("a line saved by name only is matched to its product", prods["Barbe"]["clients"] > 500)
    check("promo days are known to the model", first["controls"]["promo"] > 100)
    check("same-day double scan is one purchase, not a return",
          all(p.get("days_back") is None or p["days_back"] >= 1 for p in first["products"]))
    check("no client id or name in the result", "Client " not in str(res) and "c12" not in str(res))

    print("\nStores")
    r2 = PR.result("t1", "b2")
    p2 = {p["name"]: p for p in r2["views"]["first"]["products"]}
    check("the second store has its own figures (its own sales only)", r2["views"]["first"]["n"] == 300)
    check("a return at the other store still counts as a return",
          r2["views"]["first"]["base_rate"] > 0.3)
    check("main store figures exclude the second store's sales",
          PR.result("t1", "main")["views"]["first"]["n"] == 1200)
    check("coverage: share of visits with products (last 90 days)",
          0 < res["coverage"]["pct"] < 100 and res["coverage"]["total"] >= 300)

    print("\nAll visits view")
    allv = res["views"]["all"]
    check("every eligible purchase is an example, regulars included", allv["n"] > first["n"])

    # ------------------------------------------------------------------
    print("\nA combo: two products that only work together")
    # ------------------------------------------------------------------
    db.tenants.insert_one({"id": "t2", "name": "Salon de thé", "plan": "vip", "product_return_window_days": 30})
    db.tenant_catalog.insert_one({"tenant_id": "t2", "items": [
        {"id": "a", "name": "Thé", "price": 4}, {"id": "b", "name": "Gâteau", "price": 5}]})
    rnd = random.Random(5)
    vv, cc = [], []
    for k in range(1600):
        first_at = NOW - dt.timedelta(days=rnd.randint(45, 600))
        a, bb = rnd.random() < .5, rnd.random() < .5
        items = [{"item_id": x, "name": n, "qty": 1, "price": 4} for x, n, on in (("a", "Thé", a), ("b", "Gâteau", bb)) if on]
        if not items:
            items = [{"name": "Café", "qty": 1, "price": 2}]
        back = rnd.random() < sig(-0.6 + 1.4 * (a and bb))
        vv.append({"id": f"w{k}", "tenant_id": "t2", "customer_id": f"d{k}", "visit_time": first_at, "items": items,
                   "amount_paid": 9.0})
        if back:
            vv.append({"id": f"w{k}b", "tenant_id": "t2", "customer_id": f"d{k}",
                       "visit_time": first_at + dt.timedelta(days=rnd.randint(2, 25)), "amount_paid": 4.0})
        cc.append({"id": f"d{k}", "tenant_id": "t2", "created_at": first_at})
    db.visits.insert_many(vv)
    db.customers.insert_many(cc)
    PR.compute("t2", NOW)
    combos = PR.result("t2", "all")["views"]["first"]["combos"]
    check("Thé + Gâteau together do better than apart", any(
        {x["a"], x["b"]} == {"Thé", "Gâteau"} and x["effect"] == "plus" for x in combos))
    check("an unknown product (no catalogue line) is still analysed by its name",
          any(p["name"] == "Café" for p in PR.result("t2", "all")["views"]["first"]["products"]))

    # ------------------------------------------------------------------
    print("\nAn empty shop")
    # ------------------------------------------------------------------
    db.tenants.insert_one({"id": "te", "name": "Vide", "plan": "vip"})
    PR.compute("te", NOW)
    e = PR.result("te", "all")
    check("no visits → an honest empty result", e["views"]["first"]["n"] == 0 and e["views"]["first"]["products"] == []
          and e["coverage"]["pct"] == 0)

    # ------------------------------------------------------------------
    print("\nThrough the API")
    # ------------------------------------------------------------------
    db.product_return.delete_many({"tenant_id": "t1"})
    OWNER = tok("owner@barbier.fr", "business_owner", "t1")
    r = c.get("/api/owner/analyses/produits-retour", headers=OWNER)
    check("first call: nothing yet → « en cours », the work is queued",
          r.status_code == 200 and r.json()["status"] == "pending"
          and db.ai_jobs.find_one({"kind": "product_return", "tenant_id": "t1", "status": {"$in": ["queued", "running"]}}))
    JOBS.run_now("product_return", "t1", NOW)
    r = c.get("/api/owner/analyses/produits-retour", headers=OWNER).json()
    check("then the figures (Pro AI: everything)", r["status"] == "ready" and r["level"] == "full"
          and any(p["name"] == "Barbe" and "ratio_low" in p for p in r["views"]["first"]["products"]))
    r = c.get("/api/owner/analyses/produits-retour?view=all", headers=OWNER).json()
    check("?view=all answers the all-visits view", r["view"] == "all")

    db.tenants.insert_one({"id": "tg", "name": "Pro shop", "plan": "gold"})
    db.tenants.insert_one({"id": "ts", "name": "Starter shop", "plan": "silver"})
    for doc in db.product_return.find({"tenant_id": "t1"}, {"_id": 0}):
        db.product_return.insert_one({**doc, "tenant_id": "tg"})
    g = c.get("/api/owner/analyses/produits-retour", headers=tok("owner@gold.fr", "business_owner", "tg")).json()
    gp = g["views"]["first"]["products"]
    check("Pro: the buckets only — no ranges, no combos", g["level"] == "buckets" and gp
          and all(set(p) <= {"name", "bucket", "clients", "needed", "together"} for p in gp)
          and "combos" not in g["views"]["first"])
    s = c.get("/api/owner/analyses/produits-retour", headers=tok("owner@silver.fr", "business_owner", "ts"))
    check("Starter: locked with the upgrade (the platform's plan rule)",
          s.status_code == 403 and "PLAN_FEATURE_DISABLED" in s.text)
    check("another shop's owner never reads t1",
          "Barbe" not in str(c.get("/api/owner/analyses/produits-retour",
                                   headers=tok("owner@silver.fr", "business_owner", "ts")).json()))

    print("\nWho sees which store")
    db.tenants.update_one({"id": "t1"}, {"$set": {"branches": [
        {"id": "main", "name": "Liberté"}, {"id": "b2", "name": "Palissy"}]}})
    db.users.insert_one({"email": "mgr@barbier.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b2"]})
    MGR = tok("mgr@barbier.fr", "manager", "t1")
    m = c.get("/api/owner/analyses/produits-retour", headers={**MGR, "X-FidClic-Store": "main"}).json()
    check("a manager of Palissy asking for Liberté still gets Palissy only",
          m["status"] == "ready" and m["views"]["first"]["n"] == 300)
    o = c.get("/api/owner/analyses/produits-retour", headers={**OWNER, "X-FidClic-Store": "main"}).json()
    check("the owner picks Liberté → Liberté's own figures", o["views"]["first"]["n"] == 1200)
    o = c.get("/api/owner/analyses/produits-retour", headers={**OWNER, "X-FidClic-Store": "all"}).json()
    check("the owner on the whole shop → every store", o["views"]["first"]["n"] == 1500)
    check("a client name typed into a product never runs as HTML here (plain JSON, no markup added)",
          c.get("/api/owner/analyses/produits-retour", headers=OWNER).headers["content-type"].startswith("application/json"))

    r = c.put("/api/owner/analyses/produits-retour/fenetre", json={"days": 45}, headers=OWNER)
    check("the owner sets their own window → saved, recomputed",
          r.status_code == 200 and db.tenants.find_one({"id": "t1"})["product_return_window_days"] == 45
          and db.ai_jobs.find_one({"kind": "product_return", "tenant_id": "t1", "status": {"$in": ["queued", "running"]}}))
    check("days out of 7–180 are refused",
          c.put("/api/owner/analyses/produits-retour/fenetre", json={"days": 3}, headers=OWNER).status_code == 400
          and c.put("/api/owner/analyses/produits-retour/fenetre", json={"days": 500}, headers=OWNER).status_code == 400)
    r = c.put("/api/owner/analyses/produits-retour/fenetre", json={"days": None}, headers=OWNER)
    check("null → back to the shop's rhythm", r.status_code == 200
          and db.tenants.find_one({"id": "t1"}).get("product_return_window_days") is None)
    check("staff cannot change it",
          c.put("/api/owner/analyses/produits-retour/fenetre", json={"days": 40},
                headers=tok("staff@barbier.fr", "staff", "t1")).status_code == 403)
    j1 = c.post("/api/owner/analyses/produits-retour/recalculer", headers=OWNER).json()
    j2 = c.post("/api/owner/analyses/produits-retour/recalculer", headers=OWNER).json()
    check("« Recalculer » twice = one job", j1["job_id"] == j2["job_id"])

    print("\nThe weekly tick")
    db.ai_jobs.delete_many({})
    db.product_return.update_many({"tenant_id": "t1"}, {"$set": {"built_at": NOW - dt.timedelta(days=8)}})
    started = PR.due(NOW)
    check("a week-old result is rebuilt", "t1" in started)
    check("a shop without any product line is left alone", "te" not in started)
    check("a fresh result is not rebuilt", "t1" not in PR.due(NOW))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
