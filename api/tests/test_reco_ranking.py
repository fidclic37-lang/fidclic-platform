"""
La recommandation qui apprend (user, 2026-10-29/30, PR-B): every idea's
place comes from its estimate × what was learned — from every data point of
the journal (shown, opened, dismissed, later) and every measured send (€,
groupe témoin), the shop's own blended with the network's (every shop
weighs the same; same activité first, then secteur). Ideas with little
data still get their chance (Thompson sampling, one draw per shop × idea ×
Paris day: the order holds all day). Every card says « Pourquoi en premier ? ».
Copilote, Insights, Tableau de bord, « a repéré ».

Run: cd api && /usr/local/bin/python3 tests/test_reco_ranking.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-reco-ranking")
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
    from features import reco_journal as RJ
    from features import reco_ranking as RR

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime(2026, 10, 30, 10, tzinfo=UTC)
    day = RJ.day_of(now)

    def shown(tid, key, days, opened=0, dismissed=0, later=0, surface="copilote"):
        rows = []
        for d in range(days):
            dd = RJ.day_of(now - dt.timedelta(days=d))
            rows.append({"tenant_id": tid, "key": key, "surface": surface, "kind": "shown", "day": dd, "n": 1, "store_key": "all"})
        for kind, n in (("opened", opened), ("dismissed", dismissed), ("later", later)):
            for d in range(n):
                rows.append({"tenant_id": tid, "key": key, "surface": surface, "kind": kind,
                             "day": RJ.day_of(now - dt.timedelta(days=d)), "n": 1, "store_key": "all"})
        if rows:
            db.reco_events.insert_many(rows)

    def sends(tid, key, euros, enough=True):
        for i, e in enumerate(euros):
            db.campaigns.insert_one({"id": f"{tid}-{key}-{i}", "tenant_id": tid, "status": "sent",
                                     "sent_at": now - dt.timedelta(days=30 + i), "reco_key": key,
                                     "reco_result": {"measured": True, "enough": enough, "pending": 0, "extra_revenue": e}})

    print("Le calcul (pur)")
    ref = {"open": 0.2, "eur": 100.0}
    m0, p0 = RR.factor({"shown": 0, "opened": 0, "dismissed": 0, "later": 0, "results": []}, None, ref, None)
    check("nothing known, nowhere: ×1 (the estimate decides)", m0 == 1.0, (m0, p0))
    own_good = {"shown": 10, "opened": 6, "dismissed": 0, "later": 0, "results": [600.0, 500.0, 700.0]}
    own_bad = {"shown": 10, "opened": 1, "dismissed": 4, "later": 2, "results": [-50.0, 0.0]}
    mg, _ = RR.factor(own_good, None, ref, None)
    mb, _ = RR.factor(own_bad, None, ref, None)
    check("taken often and paid well → above ×1; dismissed and paid nothing → below", mg > 1.5 and mb < 0.7, (mg, mb))
    check("never beyond ×0.25 – ×4", all(RR.CLIP[0] <= m <= RR.CLIP[1] for m in (mg, mb, RR.factor(
        {"shown": 50, "opened": 50, "dismissed": 0, "later": 0, "results": [99999.0] * 20}, None, ref, None)[0])))
    seed = ("t1", "relance_inactifs", day)
    a1 = RR.factor({"shown": 2, "opened": 1, "dismissed": 0, "later": 0, "results": []}, {"open": 0.3, "eur": 200.0, "shops": 4}, ref, seed)[0]
    a2 = RR.factor({"shown": 2, "opened": 1, "dismissed": 0, "later": 0, "results": []}, {"open": 0.3, "eur": 200.0, "shops": 4}, ref, seed)[0]
    draws = {round(RR.factor({"shown": 2, "opened": 1, "dismissed": 0, "later": 0, "results": []},
                             {"open": 0.3, "eur": 200.0, "shops": 4}, ref, ("t1", "relance_inactifs", f"2026-10-{d:02d}"))[0], 4)
             for d in range(1, 29)}
    check("one draw per shop × idea × day: the same all day", a1 == a2)
    check("…and another on other days (little data: it explores)", len(draws) > 5, len(draws))
    def rel_spread(own):
        v = [RR.factor(own, {"open": 0.3, "eur": 200.0, "shops": 4}, ref, ("t1", "k", f"2026-10-{d:02d}"))[0] for d in range(1, 29)]
        return (max(v) - min(v)) / (sum(v) / len(v))
    big = {"shown": 400, "opened": 120, "dismissed": 0, "later": 0, "results": [200.0] * 40}
    small = {"shown": 2, "opened": 1, "dismissed": 0, "later": 0, "results": []}
    check("much data: the draws are far narrower than with little (it has learned)",
          rel_spread(big) < rel_spread(small) / 2, (round(rel_spread(big), 2), round(rel_spread(small), 2)))
    m_bad_rows, _ = RR.factor({"shown": "x", "opened": None, "dismissed": -3, "later": 1.5, "results": ["a", None, 10]}, {"open": "?", "eur": None}, {}, None)
    check("broken numbers never crash, stay in bounds", RR.CLIP[0] <= m_bad_rows <= RR.CLIP[1])

    print("\nLe réseau : chaque commerce pèse pareil")
    for tid, sector, act in (("big", "salon", "barbier"), ("b1", "salon", "barbier"), ("b2", "salon", "barbier"),
                             ("b3", "salon", "barbier"), ("b4", "salon", "barbier"), ("c1", "cafe", None), ("t1", "cafe", None),
                             ("t2", "cafe", None)):
        db.tenants.insert_one({"id": tid, "name": tid, "sector": sector, "activity_key": act, "is_active": True,
                               "plan": "vip", "subscription_status": "active"})
    sends("big", "relance_inactifs", [1000.0] * 50)          # one shop, 50 sends at +1 000 €
    db.tenants.insert_one({"id": "b5", "name": "b5", "sector": "salon", "activity_key": "barbier", "is_active": True})
    db.campaigns.insert_one({"id": "b5-p", "tenant_id": "b5", "status": "sent", "sent_at": now - dt.timedelta(days=3),
                             "reco_key": "relance_inactifs", "recipient_ids": ["x"], "holdout_ids": ["y"]})   # still pending
    for t in ("b1", "b2", "b3", "b4"):
        sends(t, "relance_inactifs", [0.0])                   # four shops, one send at 0 €
    for t in ("big", "b1", "b2", "b3", "b4"):
        shown(t, "relance_inactifs", 10, opened=2)
    out = RR.learn(now)
    net = RR.network_for({"sector": "salon", "activity_key": "barbier"}, "relance_inactifs")
    check("network € per send = the middle shop (median of 1 000, 0, 0, 0, 0 = 0), not ~900 nor 200",
          net and net["eur"] == 0.0 and net["shops"] == 5, net)
    check("network open rate = the middle shop's (2 / 10)", net and abs(net["open"] - 0.2) < 1e-9, net)
    check("learning ran and is remembered for the day", out.get("ideas") and RR.learn_due(now) is None
          and RR.learn_due(now + dt.timedelta(hours=25)) is not None)
    # one odd shop (a typo at the till, or on purpose) must not move the network (pentest #401)
    for i, e in enumerate((80.0, 90.0, 100.0, 110.0)):
        db.tenants.insert_one({"id": f"m{i}", "name": "m", "sector": "salon", "activity_key": "barbier", "is_active": True})
        sends(f"m{i}", "median_test", [e])
        shown(f"m{i}", "median_test", 10, opened=(1, 2, 3, 4)[i])
    db.tenants.insert_one({"id": "odd", "name": "odd", "sector": "salon", "activity_key": "barbier", "is_active": True})
    sends("odd", "median_test", [100000.0] * 200)
    shown("odd", "median_test", 10, opened=10)
    RR.learn(now)
    mt = RR.network_for({"sector": "salon", "activity_key": "barbier"}, "median_test")
    check("one shop claiming +100 000 € a send among four at 80–110 €: the network stays at 100 €",
          mt and mt["eur"] == 100.0 and mt["shops"] == 5, mt)
    check("…and its 10 opens in 10 do not lift the open rate (middle shop: 3 in 10)", mt and abs(mt["open"] - 0.3) < 1e-9, mt)
    db.campaigns.delete_many({"tenant_id": "m3"})
    RR.learn(now)
    mt = RR.network_for({"sector": "salon", "activity_key": "barbier"}, "median_test")
    check("an even count: the two middle shops' average (90 + 100) / 2 = 95", mt and mt["eur"] == 95.0, mt)
    ref_eur = RR._network_doc()["ref"]["eur"]
    check("the all-trades reference is the middle shop too, not pulled by +100 000 €", ref_eur is not None and ref_eur < 1000, ref_eur)
    w = RR.why({"net_eur": 100.0, "shown": 1}, "barbiers")
    check("the network line says « en général » (a middle shop), not « en moyenne »",
          "Chez les barbiers comme vous : +100 € par envoi en général" in w and "moyenne" not in w, w)
    for t in ("o1", "o2"):
        db.tenants.insert_one({"id": t, "name": t, "sector": "retail", "activity_key": "opticien", "is_active": True})
        sends(t, "offre_jour", [400.0])
    RR.learn(now)
    check("fewer than 3 shops: no network figure (it would be one competitor's own)",
          RR.network_for({"sector": "retail", "activity_key": "opticien"}, "offre_jour") is None)
    check("a café reads no barber figures (sector first)", RR.network_for({"sector": "cafe"}, "relance_inactifs") is None
          or RR.network_for({"sector": "cafe"}, "relance_inactifs")["shops"] != 5)
    check("only finished, measured sends count (a shop with only a pending send is not in it)",
          net and net["shops"] == 5 and "b5" not in str(RR._network_doc()))

    print("\nLe Copilote apprend")
    db.users.insert_one({"email": "o@t1.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1"})}
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_description": "Un café"})
    for i in range(150):
        last = now - dt.timedelta(days=(5, 40, 100)[i % 3])
        db.customers.insert_one({"id": f"c{i:03d}", "tenant_id": "t1", "name": f"Client {i}", "visits": 4, "total_amount_paid": 60.0,
                                 "created_at": now - dt.timedelta(days=300), "last_visit_date": last, "barcode_id": f"B{i}"})
        for k in range(4):
            db.visits.insert_one({"id": f"v{i}-{k}", "tenant_id": "t1", "customer_id": f"c{i:03d}", "amount_paid": 15.0,
                                  "visit_time": last - dt.timedelta(days=21 * k)})
    RR.NOW = lambda: now                          # the page's clock (sends 30 days ago are finished)
    base = [RJ.key_of(r) for r in (http("GET", "/api/owner/copilot/page", headers=H).json()["recommendations"]["all"])]
    check("the page lists ideas", len(base) >= 2, base)
    last = base[-1]
    shown("t1", last, 12, opened=9)
    sends("t1", last, [900.0, 800.0, 1000.0])
    RR._cache.clear()
    recs = http("GET", "/api/owner/copilot/page", headers=H).json()["recommendations"]["all"]
    order = [RJ.key_of(r) for r in recs]
    check(f"the idea that paid here (+900 € a send, taken 9 times in 12) rises from last ({last})",
          order.index(last) < base.index(last), (base, order))
    top = next(r for r in recs if RJ.key_of(r) == last)
    why = (top.get("why_rank") or {}).get("text") or ""
    check("« Pourquoi en premier ? » says it: what it brought here, how often it is taken",
          "+900 €" in why and "9 fois sur 12" in why, why)
    check("every card carries its reason", all((r.get("why_rank") or {}).get("text") for r in recs), [r.get("why_rank") for r in recs])
    first = base[0]
    shown("t1", first, 10, dismissed=5)
    RR._cache.clear()
    order2 = [RJ.key_of(r) for r in http("GET", "/api/owner/copilot/page", headers=H).json()["recommendations"]["all"]]
    check("an idea pushed aside 5 times falls", order2.index(first) >= order.index(first), (order, order2))
    a = [RJ.key_of(r) for r in http("GET", "/api/owner/copilot/page", headers=H).json()["recommendations"]["all"]]
    b = [RJ.key_of(r) for r in http("GET", "/api/owner/copilot/page", headers=H).json()["recommendations"]["all"]]
    check("the same order all day (two loads)", a == b)

    print("\nInsights, Tableau de bord, « a repéré »")
    ins = http("GET", "/api/owner/insights/page", headers=H).json()
    cards = [i for k in ("opportunities", "actions", "ideas") for i in (ins.get(k) or {}).get("shown") or []]
    check("Insights: every card shown carries its reason", cards and all((i.get("why_rank") or {}).get("text") for i in cards))
    home = http("GET", "/api/owner/home/overview", headers=H).json()
    check("Tableau de bord: 3 ideas at most, each with its reason",
          len(home["recommendations"]) <= 3 and all((r.get("why_rank") or {}).get("text") for r in home["recommendations"]))
    det = http("GET", "/api/owner/brain/detectors", headers=H).json()["detectors"]
    check("« a repéré »: each list with its reason", all((d.get("why_rank") or {}).get("text") for d in det))

    print("\nJamais bloquant")
    real = RR.factor
    RR.factor = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    RR._cache.clear()
    r = http("GET", "/api/owner/copilot/page", headers=H)
    RR.factor = real
    check("ranking down: the page still answers, in the estimate's order", r.status_code == 200
          and [RJ.key_of(x) for x in r.json()["recommendations"]["all"]])
    db.campaigns.insert_one({"id": "junk", "tenant_id": "t1", "status": "sent", "sent_at": "pas une date", "reco_key": "x",
                             "reco_result": {"extra_revenue": "beaucoup", "enough": "oui"}})
    db.reco_events.insert_one({"tenant_id": "t1", "key": None, "kind": "shown", "day": 5})
    RR._cache.clear()
    check("junk rows in the journal or campaigns: still 200", http("GET", "/api/owner/copilot/page", headers=H).status_code == 200
          and RR.learn(now + dt.timedelta(days=2)) is not None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
