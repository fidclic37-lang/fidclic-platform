"""
« Roz ka hisaab », PR 3 — Insights and the Copilote read the register of past
days (user, 2026-10-28).

insights_page.Shop read every visit of the last 152 days on each Insights,
Copilote, Campagnes (« Conseil FIDCLIC AI ») and automation editor load, to
add up 30 days, the month, 56 and 90 days. It now adds up the days of
features/visit_days; today and the cut ends stay live, and no visit is judged
for CA FidClic (none of these pages shows it).

    · each figure is the one the visits give: panier moyen, CA 30 jours, the
      month against the same days of last month, the goal, the best weekday,
      products per visit, the top product, the busy and quiet hours, the
      Copilote's base and its 15-day basket — every scope, DST days, the 1st
      of a month, odd rows
    · the whole page and the Copilote: identical with or without the register
    · warm, only today's and the cut ends' visits are read
    · a past day that changes moves the page at once
    · a manager sees only their establishment, through HTTP

Run: cd api && /usr/local/bin/python3 tests/test_visit_days_insights.py
"""
import datetime as dt
import os
import random
import sys
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-visit-days-insights")
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
    from features import insights_page as I, copilot as C, visit_days as VD, store_scope as S

    db = server.db
    rnd = random.Random(393)
    AT0 = dt.datetime(2026, 10, 28, 11, 0, tzinfo=UTC)          # 12:00 in Paris
    AT = [AT0]
    I._now = C._now = VD._now = lambda: AT[0]

    class TD:
        email, role, tenant_id = "owner@t1.fr", "business_owner", "t1"

    class Req:
        def __init__(self, store=None):
            self.query_params = {"store": store} if store else {}
            self.headers = {}

    db.tenants.insert_many([
        {"id": "t1", "name": "Café Test", "city": "Tours", "sector": "cafe", "plan": "vip",
         "monthly_revenue_goal": 2500,
         "branches": [{"id": "main", "name": "Centre"}, {"id": "b2", "name": "Plumereau"},
                      {"id": "b3", "name": "Gare"}]},
        {"id": "t2", "name": "Rival", "sector": "cafe"}])
    db.users.insert_many([{"email": "owner@t1.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "mgr@t1.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["b2"]}])

    # ── data: 30 clients over 8 months, busy lunches, odd rows ───────────────
    STORES = [None, "main", "b2", "", "b3"]
    NAMES = ["Café", "Croissant", "Thé.vert", "$pécial", "  Latte  ", "", None]
    customers, visits = [], []
    for i in range(30):
        cid = f"c{i:02d}"
        gap = rnd.choice([2, 3, 4, 6, 7, 9])
        home = rnd.choice(STORES)
        t = AT0 - dt.timedelta(days=240 - rnd.random() * gap)
        n = 0
        while t < AT0 + dt.timedelta(days=2):          # a few rows in the future
            items = [{"name": rnd.choice(NAMES), "price": rnd.choice([2, 3.5, 4.2, None]),
                      **({"qty": rnd.choice([1, 2, 3])} if rnd.random() < .5 else
                         {"quantity": rnd.choice([1, 2])} if rnd.random() < .5 else {})}
                     for _ in range(rnd.choice([0, 1, 1, 2, 3]))]
            local = t.astimezone(PARIS).replace(hour=rnd.choice([7, 8, 9, 11, 12, 12, 13, 13, 15, 17, 19, 21]),
                                                minute=rnd.choice([0, 10, 59]))
            vt = local.astimezone(UTC)
            vt = vt if rnd.random() < .9 else (vt.replace(tzinfo=None) if rnd.random() < .5 else vt.isoformat())
            visits.append({"id": f"v{len(visits):05d}", "tenant_id": "t1", "customer_id": cid,
                           "branch_id": home if rnd.random() < .8 else rnd.choice(STORES),
                           "amount_paid": rnd.choice([round(rnd.uniform(2, 40), 2), 0, None, "12.5", "n/a"]),
                           "visit_time": vt, "items": items if rnd.random() < .95 else None})
            n += 1
            t = t + dt.timedelta(days=gap * rnd.uniform(.7, 1.3), hours=rnd.uniform(-5, 5))
        customers.append({"id": cid, "tenant_id": "t1", "name": f"Client {i}", "visits": n,
                          "total_amount_paid": round(rnd.uniform(20, 400), 2), "branch_id": home,
                          "created_at": AT0 - dt.timedelta(days=rnd.choice([3, 20, 200, 250])),
                          "last_visit_date": AT0 - dt.timedelta(days=rnd.choice([1, 9, 40, 120])),
                          "birthday": rnd.choice(["1990-11-02", "1985-10-30", None])})
    # the nights of the clock changes, and midnight in Paris
    for when in (dt.datetime(2026, 10, 25, 0, 30, tzinfo=UTC), dt.datetime(2026, 10, 25, 1, 30, tzinfo=UTC),
                 dt.datetime(2026, 10, 24, 22, 0, tzinfo=UTC), dt.datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
                 dt.datetime(2026, 9, 30, 22, 30, tzinfo=UTC)):
        visits.append({"id": f"v-dst-{when:%m%d%H}", "tenant_id": "t1", "customer_id": "c02",
                       "branch_id": "b2", "amount_paid": 7, "visit_time": when,
                       "items": [{"name": "Café", "qty": "2"}, {"name": "", "quantity": 3}]})
    db.customers.insert_many(customers)
    db.visits.insert_many(visits)
    db.reviews.insert_many([{"tenant_id": "t1", "customer_id": "c01", "rating": 9},
                            {"tenant_id": "t1", "customer_id": "c03", "rating": 10}])
    db.visits.insert_one({"id": "r1", "tenant_id": "t2", "customer_id": "x1", "amount_paid": 500,
                          "visit_time": AT0 - dt.timedelta(days=3)})

    def scope(store=None):
        return S.resolve(TD(), Req(store))

    def both(store=None):
        VD.ENABLED = False
        want = I._payload("t1", AT[0], scope(store))
        VD.ENABLED = True
        got = I._payload("t1", AT[0], scope(store))
        return want, got

    def same(label, store=None):
        want, got = both(store)
        d = diff(want, got)
        check(label, d is None, d)
        return want, got

    # ── 1. each figure is the one the visits give ─────────────────────────────
    def reference(shop):
        """The figures from the visits themselves, as insights_page computed
        them before (a visit dated in the future is not in any period)."""
        at = shop.at

        def when(v):
            return I._aware(v.get("visit_time"))
        rows = [v for v in shop.visits if when(v) and when(v) <= at]

        def since(days):
            return [v for v in rows if when(v) >= at - dt.timedelta(days=days)]

        def rev(a, b):
            return sum(I._num(v.get("amount_paid")) for v in rows if a <= when(v) <= b)
        month = since(30)
        out = {"monthly": round(sum(I._num(v.get("amount_paid")) for v in month), 6),
               "shop_avg": round(sum(I._num(v.get("amount_paid")) for v in month) / len(month), 6) if month else None}
        start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_start = (start - dt.timedelta(days=1)).replace(day=1)
        out["month"], out["prev"] = round(rev(start, at), 6), round(rev(prev_start, prev_start + (at - start)), 6)
        with_items = [v for v in since(90) if v.get("items")]
        out["items_per_visit"] = (round(sum(sum(I._qty(i) for i in v["items"]) for v in with_items) / len(with_items), 6)
                                  if len(with_items) >= 5 else None)
        tally = Counter()
        for v in since(90):
            for i in (v.get("items") or []):
                name = str(i.get("name") or "").strip()
                if name:
                    tally[name] += I._qty(i)
        out["top_qty"] = max(tally.values()) if tally else None
        per = defaultdict(int)
        for v in since(90):
            per[I._paris(when(v)).hour] += 1
        out["hours"] = dict(per)
        out["n90"], out["n56"], out["n30"], out["n15"] = len(since(90)), len(since(56)), len(month), len(since(15))
        prev15 = [v for v in month if when(v) < at - dt.timedelta(days=15)]
        out["prev15"] = (len(prev15), round(sum(I._num(v.get("amount_paid")) for v in prev15), 6))
        return out

    def figures(shop):
        tally = Counter()
        top = I._top_product(shop)
        hrs = I._hours(shop)
        return {"monthly": round(shop.monthly, 6),
                "shop_avg": round(shop.shop_avg, 6) if shop.shop_avg_window else None,
                "items_per_visit": round(I._items_per_visit(shop), 6) if I._items_per_visit(shop) is not None else None,
                "top": top, "hours": hrs}

    print("Chaque chiffre, celui des visites")
    for label, at in (("28/10 12:00", AT0), ("1er novembre 00:15", dt.datetime(2026, 10, 31, 23, 15, tzinfo=UTC)),
                      ("26/10 01:30, heure d'hiver", dt.datetime(2026, 10, 26, 0, 30, tzinfo=UTC)),
                      ("1er octobre 00:30, minuit Paris", dt.datetime(2026, 9, 30, 22, 30, tzinfo=UTC))):
        AT[0] = at
        for store in (None, "b2"):
            shop = I.Shop("t1", at, scope(store))
            ref, got = reference(shop), figures(shop)
            where = f"{label}, {store or 'tous'}"
            check(f"{where}: CA 30 jours ({got['monthly']} €) and panier moyen",
                  abs(got["monthly"] - ref["monthly"]) < 1e-6
                  and (got["shop_avg"] is None if ref["shop_avg"] is None else abs(got["shop_avg"] - ref["shop_avg"]) < 1e-6),
                  (got, ref))
            h = I._hero(shop)
            want_pct = round((ref["month"] - ref["prev"]) / ref["prev"] * 100) if ref["prev"] > 0 else None
            check(f"{where}: the month against the same days of last month ({h.get('pct')} %)",
                  h.get("pct") == want_pct and abs(h["revenue"] - round(ref["month"] + 1e-9, 2)) < .005, (h, ref))
            g = I._goal(shop)
            check(f"{where}: the goal's takings ({g['reached']} €)", abs(g["reached"] - round(ref["month"] + 1e-9, 2)) < .005)
            check(f"{where}: products per visit ({got['items_per_visit']})", got["items_per_visit"] == ref["items_per_visit"],
                  (got["items_per_visit"], ref["items_per_visit"]))
            top_qty = Counter()
            for v in shop.recent(90):
                if I._aware(v.get("visit_time")) <= at:
                    for i in (v.get("items") or []):
                        if str(i.get("name") or "").strip():
                            top_qty[str(i.get("name")).strip()] += I._qty(i)
            check(f"{where}: the top product is a most sold one ({got['top']})",
                  (got["top"] is None and ref["top_qty"] is None) or top_qty.get(got["top"]) == ref["top_qty"],
                  (got["top"], top_qty.most_common(3)))
            if got["hours"]:
                slots = {s: ref["hours"].get(s, 0) + ref["hours"].get(s + 1, 0) for s in range(7, 22)}
                check(f"{where}: busy hours {got['hours']['busy']} on {got['hours']['visits']} visits",
                      got["hours"]["visits"] == ref["n90"] and slots[got["hours"]["busy"][0]] == max(slots.values()),
                      (got["hours"], ref["hours"]))
            check(f"{where}: the Copilote's base ({C._base_visits(shop)} visits in 30 days)",
                  C._base_visits(shop) == ref["n30"], (C._base_visits(shop), ref["n30"]))
    AT[0] = AT0

    # ── 2. the whole page, with and without the register ─────────────────────
    print("La page entière, registre froid puis chaud")
    for at in (AT0, dt.datetime(2026, 10, 31, 23, 15, tzinfo=UTC), dt.datetime(2026, 10, 26, 0, 30, tzinfo=UTC)):
        AT[0] = at
        for store in (None, "main", "b2"):
            same(f"{at:%d/%m %H:%M} UTC, {store or 'tous'}: identical")
    AT[0] = AT0

    def copilot(store=None):
        shop = I.Shop("t1", AT[0], scope(store))
        fc = C.forecast_week(shop)
        return {"recs": C.recommendations(shop), "forecast": fc, "opps": C.opportunities(shop, fc)}
    for store in (None, "b2"):
        VD.ENABLED = False
        want = copilot(store)
        VD.ENABLED = True
        got = copilot(store)
        check(f"Copilote, {store or 'tous'}: recommendations, forecast, opportunities identical",
              diff(want, got) is None, diff(want, got))

    # every visit document read for the figures
    import mongomock.collection as MC
    reads = {"n": 0, "requests": 0}
    real_find = MC.Collection.find

    def counting(self, *a, **k):
        cur = real_find(self, *a, **k)
        if self.name == "visits":
            reads["n"] += len(list(cur.clone()))
            reads["requests"] += 1
        return cur
    MC.Collection.find = counting
    I._payload("t1", AT0, scope())
    MC.Collection.find = real_find
    total = db.visits.count_documents({"tenant_id": "t1"})
    check(f"warm: only today's and the cut ends' visits are read ({reads['n']} rows; {total} in the shop)",
          reads["n"] < total / 10, reads)
    # seven periods, each with its own cut ends: one trip to the database
    check(f"…in one request, not one per cut end ({reads['requests']})", reads["requests"] == 1, reads)

    # ── 3. a past day that changes ────────────────────────────────────────────
    print("Un jour passé qui change")
    before = I.Shop("t1", AT0, scope())
    m0 = before.monthly
    db.visits.insert_one({"id": "new1", "tenant_id": "t1", "customer_id": "c03", "branch_id": "main",
                          "amount_paid": 33, "visit_time": AT0 - dt.timedelta(days=2, hours=1),
                          "items": [{"name": "Gâteau", "price": 33, "qty": 1}]})
    after = I.Shop("t1", AT0, scope())
    check("a visit added two days ago: CA 30 jours +33 €", round(after.monthly - m0, 2) == 33)
    same("…and the whole page identical")
    db.visits.delete_one({"id": "new1"})
    check("deleted again: back as it was", round(I.Shop("t1", AT0, scope()).monthly - m0, 2) == 0)

    # a day summed before the register counted till lines (#392, #396 rows)
    old_day = VD.day_of(AT0 - dt.timedelta(days=20))
    row = db.visit_days.find_one({"tenant_id": "t1", "day": old_day}, {"_id": 0})
    db.visit_days.update_one({"tenant_id": "t1", "day": old_day}, {"$set": {
        "v": 1, "stores": [{k: x for k, x in s.items() if k not in ("iv", "iq")} for s in row["stores"]]}})
    VD.ENABLED = True
    w = I._items_per_visit(I.Shop("t1", AT0, scope()))
    row = db.visit_days.find_one({"tenant_id": "t1", "day": old_day})
    check("a day summed by the older layout is summed again, till lines included",
          row["v"] == VD.SCHEMA and all("iv" in s for s in row["stores"]) and w is not None)
    same("…and the page identical")

    # ── 4. an empty shop ──────────────────────────────────────────────────────
    print("Commerce vide")
    db.tenants.insert_one({"id": "t3", "name": "Vide", "sector": "cafe"})
    VD.ENABLED = False
    want = I._payload("t3", AT0, None)
    VD.ENABLED = True
    got = I._payload("t3", AT0, None)
    check("no visit: identical, and the page still starts", diff(want, got) is None and got["hero"]["direction"] == "start",
          diff(want, got))

    # ── 5. through HTTP, with a manager's establishment ──────────────────────
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
    I._now = C._now = VD._now = lambda: real_now
    mgr = auth.create_access_token({"sub": "mgr@t1.fr", "role": "manager", "tenant_id": "t1"})
    VD.ENABLED = False
    want = get("/api/owner/insights/page", mgr).json()
    VD.ENABLED = True
    r = get("/api/owner/insights/page", mgr)
    check(f"a manager of Plumereau: identical through HTTP ({r.status_code})",
          r.status_code == 200 and diff(want, r.json()) is None, diff(want, r.json()))
    r = get("/api/owner/insights/page", mgr, store="main")
    check("…and never the establishments they don't cover", (r.json().get("scope") or {}).get("ids") == ["b2"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
