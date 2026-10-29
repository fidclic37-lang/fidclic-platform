"""
« Roz ka hisaab », PR 2 — Analyses read the register of past days (user, 2026-10-28).

Vue d'ensemble, Moments de visite and Produits read every visit of their
period (and the one before) and judged each for CA FidClic and « attendus ».
They now add up the days of features/visit_days, as the Tableau de bord does;
today and the cut ends stay live.

    · every tab that reads visits, and the CSV export: EXACTLY the figures read
      from the visits — every period, every establishment
    · warm, only today's and the cut ends' visits are read
    · a past day that changes moves the page at once
    · a manager sees only their establishment, through HTTP

Run: cd api && /usr/local/bin/python3 tests/test_visit_days_analyses.py
"""
import datetime as dt
import os
import random
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-visit-days-analyses")
os.environ.setdefault("DISABLE_SEED", "1")
UTC, PARIS = dt.timezone.utc, ZoneInfo("Europe/Paris")
passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {str(detail)[:400]}"))


def diff(a, b, path=""):
    """The first place two payloads differ, or None."""
    if type(a) is not type(b):
        return f"{path}: {a!r} != {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                return f"{path}.{k}: missing on one side"
            d = diff(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            d = diff(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def main():
    import server
    from features import analyses as A, visit_days as VD, client_brain as CB

    db = server.db
    rnd = random.Random(392)
    AT0 = dt.datetime(2026, 10, 28, 11, 0, tzinfo=UTC)          # 12:00 in Paris
    A._now = lambda: AT0
    VD._now = lambda: AT0

    class TD:
        email, role, tenant_id = "owner@t1.fr", "business_owner", "t1"

    class Req:
        def __init__(self, store=None):
            self.query_params = {"store": store} if store else {}
            self.headers = {}

    db.tenants.insert_many([
        {"id": "t1", "name": "Café Test", "city": "Tours", "sector": "cafe", "plan": "vip",
         "branches": [{"id": "main", "name": "Centre"}, {"id": "b2", "name": "Plumereau"},
                      {"id": "b3", "name": "Gare"}]},
        {"id": "t2", "name": "Rival", "sector": "cafe"}])
    db.users.insert_many([{"email": "owner@t1.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "mgr@t1.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b2"]}])

    # ── data: regular clients over 14 months, every kind of message ──────────
    STORES = [None, "main", "b2", "", "b3"]
    NAMES = ["Café", "Croissant", "Thé.vert", "$pécial", "  Latte  ", "", None]
    customers, visits = [], []
    for i in range(18):
        cid = f"c{i:02d}"
        gap = rnd.choice([4, 6, 7, 9, 12, 15])
        home = rnd.choice(STORES)
        t = AT0 - dt.timedelta(days=420 - rnd.random() * gap)
        n = 0
        while t < AT0 + dt.timedelta(days=2):          # a few rows in the future: never counted
            items = [{"name": rnd.choice(NAMES), "price": rnd.choice([2, 3.5, 4.2, None]),
                      **({"qty": rnd.choice([1, 2, 3])} if rnd.random() < .6 else
                         {"quantity": rnd.choice([1, 2])} if rnd.random() < .5 else {})}
                     for _ in range(rnd.choice([0, 1, 1, 2, 3]))]
            # the hours a café keeps, and some outside the 8h–20h grid
            local = (t.astimezone(PARIS)).replace(hour=rnd.choice([7, 8, 9, 11, 12, 13, 15, 17, 19, 21]))
            vt = local.astimezone(UTC)
            vt = vt if rnd.random() < .9 else (vt.replace(tzinfo=None) if rnd.random() < .5 else vt.isoformat())
            visits.append({"id": f"v{len(visits):05d}", "tenant_id": "t1", "customer_id": cid,
                           "branch_id": home if rnd.random() < .8 else rnd.choice(STORES),
                           "amount_paid": rnd.choice([round(rnd.uniform(2, 40), 2), 0, None, "12.5"]),
                           "visit_time": vt, "items": items if rnd.random() < .95 else None})
            n += 1
            t = t + dt.timedelta(days=gap * rnd.uniform(.7, 1.3), hours=rnd.uniform(-5, 5))
        customers.append({"id": cid, "tenant_id": "t1", "name": f"Client {i}", "visits": n,
                          "total_amount_paid": round(rnd.uniform(20, 400), 2), "branch_id": home,
                          "created_at": AT0 - dt.timedelta(days=rnd.choice([3, 20, 200, 430])),
                          "last_visit_date": AT0 - dt.timedelta(days=rnd.choice([1, 9, 40, 120]))})
    # the night of the change to winter time, and midnight in Paris
    for when in (dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC), dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                 dt.datetime(2026, 10, 24, 22, 0, tzinfo=UTC), dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)):
        visits.append({"id": f"v-dst-{when:%m%d%H}", "tenant_id": "t1", "customer_id": "c02",
                       "branch_id": "b2", "amount_paid": 7, "visit_time": when, "items": [{"name": "Café"}]})
    db.customers.insert_many(customers)
    db.visits.insert_many(visits)

    KINDS = ["campaign", "offer", "birthday", "inactive", "proximity", "welcome", "manual", "flash_sale"]
    notes = []
    for c in customers:
        for _ in range(16):
            notes.append({"tenant_id": "t1", "customer_id": c["id"], "type": rnd.choice(KINDS),
                          "sent_at": AT0 - dt.timedelta(days=rnd.uniform(0, 410)),
                          "campaign_id": rnd.choice([None, "k1", "k2"]), "temoin": rnd.random() < .1})
    db.push_notifications.insert_many(notes)
    db.campaigns.insert_many([{"id": f"k{j}", "tenant_id": "t1", "name": f"Camp {j}", "status": "sent",
                               "sent_at": AT0 - dt.timedelta(days=rnd.uniform(0, 400)),
                               "recipient_ids": rnd.sample([c["id"] for c in customers], 6),
                               **({"holdout_ids": ["c17"]} if j % 2 else {})} for j in range(8)])
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referee_customer_id": "c05", "referrer_customer_id": "c06"})
    db.visits.insert_one({"id": "r1", "tenant_id": "t2", "customer_id": "x1", "amount_paid": 500,
                          "visit_time": AT0 - dt.timedelta(days=3)})
    for c in customers:
        CB.refresh("t1", c["id"])
    CB._usual_cache.clear()

    def both(tab, days=30, store=None):
        CB._usual_cache.clear()
        VD.ENABLED = False
        want = A.analyses(request=Req(store), tab=tab, days=days, token_data=TD())
        VD.ENABLED = True
        got = A.analyses(request=Req(store), tab=tab, days=days, token_data=TD())
        return want, got

    def same(label, tab, days=30, store=None):
        want, got = both(tab, days, store)
        d = diff(want, got)
        check(label, d is None, d)
        return want, got

    # ── 1. the data is worth testing ──────────────────────────────────────────
    print("Les données")
    w, _ = both("vue", 365)
    imp = w["data"]["impact"]
    check(f"a year of visits, CA FidClic by source, « attendus » ({imp['attendus']['visits']}), hours outside "
          f"the grid ({w['data']['hours']['outside']})",
          w["data"]["revenue_total"] > 0 and sum(1 for s in imp["sources"] if s["visits"]) >= 3
          and imp["attendus"]["visits"] > 0 and w["data"]["hours"]["outside"] > 0, imp)

    # ── 2. exactly the same figures ───────────────────────────────────────────
    print("Mêmes chiffres, registre froid puis chaud")
    for days in (1, 2, 7, 30, 90, 365):
        for store in (None, "main", "b2"):
            for tab in ("vue", "moments", "produits"):
                same(f"{tab}, {days} jour(s), {store or 'tous'}: identical", tab, days, store)
    check("the register was filled", db.visit_days.count_documents({"tenant_id": "t1"}) > 300)

    # every visit document read for the figures (the page, CA FidClic,
    # « attendus ») — not the groupe témoin's « +X € », measured per campaign
    # by features/temoin.py on its own
    import traceback
    import mongomock.collection as MC
    reads = {"n": 0}
    real_find = MC.Collection.find

    def counting(self, *a, **k):
        cur = real_find(self, *a, **k)
        if (self.name == "visits" and VD.ENABLED      # the register's read, not the reference's
                and not any(f.filename.endswith("temoin.py") for f in traceback.extract_stack())):
            reads["n"] += len(list(cur.clone()))
        return cur
    MC.Collection.find = counting
    for tab in ("vue", "moments", "produits"):
        same(f"{tab}, 365 jours, warm: identical", tab, 365)
    MC.Collection.find = real_find
    total = db.visits.count_documents({"tenant_id": "t1"})
    check(f"warm: today's visits and their clients' history only ({reads['n']} rows for 3 tabs; "
          f"{total} in the shop)", reads["n"] / 3 < total / 5, reads)

    # Moments and Produits show no CA FidClic and no period before: they judge
    # no visit (no client brain built) and read today's visits once
    from features import fidclic_impact as FI
    judged, lives = {"n": 0}, {"n": 0}
    real_classify, real_raw = FI.classify, VD._raw

    def judging(*a, **k):
        judged["n"] += 1
        return real_classify(*a, **k)

    def live(*a, **k):
        lives["n"] += 1
        return real_raw(*a, **k)
    FI.classify, VD._raw = judging, live
    for tab in ("moments", "produits"):
        A.analyses(request=Req(), tab=tab, days=30, token_data=TD())
    FI.classify, VD._raw = real_classify, real_raw
    check(f"Moments and Produits judge no visit for CA FidClic ({judged['n']}) and read the visits "
          f"once each ({lives['n']})", judged["n"] == 0 and lives["n"] == 2, (judged, lives))
    for tab in ("moments", "produits"):
        for days, store in ((1, None), (30, "b2"), (365, None)):
            same(f"…{tab}, {days} jour(s), {store or 'tous'}: still identical", tab, days, store)

    # the tabs that read no visit are unchanged by the register
    for tab in ("campagnes", "fidelisation", "avis", "acquisition", "comportement"):
        same(f"{tab}: identical", tab, 90)

    # ── 3. the CSV export ─────────────────────────────────────────────────────
    print("Export CSV")
    for days, store in ((30, None), (365, "b2"), (1, None)):
        VD.ENABLED = False
        want = A.export_analyses(request=Req(store), days=days, token_data=TD()).body
        VD.ENABLED = True
        got = A.export_analyses(request=Req(store), days=days, token_data=TD()).body
        check(f"{days} jour(s), {store or 'tous'}: the same file", want == got and len(got) > 100)

    # ── 4. an empty period, an empty shop ─────────────────────────────────────
    print("Rien à montrer")

    class TD2:
        email, role, tenant_id = "o@t3.fr", "business_owner", "t3"
    db.tenants.insert_one({"id": "t3", "name": "Vide"})
    for tab in ("vue", "moments", "produits"):
        VD.ENABLED = False
        want = A.analyses(request=Req(), tab=tab, days=30, token_data=TD2())
        VD.ENABLED = True
        got = A.analyses(request=Req(), tab=tab, days=30, token_data=TD2())
        check(f"a shop with no visit, {tab}: identical", diff(want, got) is None, diff(want, got))
    check("…the empty tabs still say so", got["data"].get("empty") is True)

    # ── 5. a past day that changes ────────────────────────────────────────────
    print("Un jour passé qui change")
    before = A.analyses(request=Req(), tab="vue", days=30, token_data=TD())["data"]
    db.visits.insert_one({"id": "new1", "tenant_id": "t1", "customer_id": "c03", "branch_id": "main",
                          "amount_paid": 33, "visit_time": AT0 - dt.timedelta(days=2, hours=1),
                          "items": [{"name": "Gâteau", "price": 33, "qty": 1}]})
    _, after = same("a visit added two days ago: identical", "vue")
    check("…and the page moved (+33 €, +1 visit)",
          round(after["data"]["revenue_total"] - before["revenue_total"], 2) == 33
          and after["data"]["moments"]["total"] == before["moments"]["total"] + 1)
    _, p = same("…its product too", "produits")
    check("…« Gâteau » is in the products", any(x["name"] == "Gâteau" for x in p["data"]["products"]))
    db.visits.delete_one({"id": "new1"})
    same("deleted again: identical", "vue")

    # ── 6. through HTTP, with a manager's establishment ──────────────────────
    print("HTTP")
    import asyncio
    import auth
    import httpx

    def get(url, token, store=None):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://t") as ac:
                return await ac.get(url, headers={"Authorization": f"Bearer {token}",
                                                  **({"X-FidClic-Store": store} if store else {})})
        return asyncio.new_event_loop().run_until_complete(run())
    real_now = dt.datetime.now(UTC)
    A._now = lambda: real_now
    VD._now = lambda: real_now
    mgr = auth.create_access_token({"sub": "mgr@t1.fr", "role": "manager", "tenant_id": "t1"})
    for tab in ("vue", "produits"):
        VD.ENABLED = False
        want = get(f"/api/owner/analyses?tab={tab}&days=90", mgr).json()
        VD.ENABLED = True
        r = get(f"/api/owner/analyses?tab={tab}&days=90", mgr)
        check(f"a manager of Plumereau, {tab}: identical through HTTP ({r.status_code})",
              r.status_code == 200 and diff(want, r.json()) is None, diff(want, r.json()))
    r = get("/api/owner/analyses?tab=vue&days=90", mgr, store="main")
    check("…and never the establishments they don't cover", r.json().get("scope", {}).get("ids") == ["b2"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
