"""
Le journal des recommandations (user, 2026-10-29, PR-A): every idea FidClic
IA shows is recorded — shown, opened in the composer, dismissed / later,
sent — and what it brought, measured with the groupe témoin. Every surface:
Copilote, Insights, Tableau de bord, « FidClic IA a repéré ». The owner reads
« La dernière fois : +X € » on the card; the super admin reads adoption,
acceptance, execution and ROI. Recording never breaks a page.

Run: cd api && /usr/local/bin/python3 tests/test_reco_journal.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-reco-journal")
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
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import reco_journal as RJ

    db = server.db
    server.dispatch_to_customer = lambda *a, **k: {"sent": True}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    for tid, sector in (("t1", "cafe"), ("t2", "salon")):
        db.tenants.insert_one({"id": tid, "slug": tid, "name": tid.upper(), "sector": sector, "plan": "vip",
                               "subscription_status": "active", "is_active": True})
        db.card_templates.insert_one({"tenant_id": tid, "programme": "stamps", "reward_description": "Un café"})
    db.users.insert_many([{"email": "o@t1.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "m@t1.fr", "role": "manager", "tenant_id": "t1", "active": True},
                          {"email": "o@t2.fr", "role": "business_owner", "tenant_id": "t2", "active": True},
                          {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "B"}])
    tok = lambda e, r, t=None: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, MGR, H2, BOSS = (tok("o@t1.fr", "business_owner", "t1"), tok("m@t1.fr", "manager", "t1"),
                        tok("o@t2.fr", "business_owner", "t2"), tok("boss@fidclic.com", "super_admin"))
    # 120 clients: regulars, late ones, gone ones — enough for every surface to speak
    for i in range(120):
        last = now - dt.timedelta(days=(5, 40, 100)[i % 3])
        db.customers.insert_one({"id": f"c{i:03d}", "tenant_id": "t1", "name": f"Client {i}", "visits": 4,
                                 "total_amount_paid": 60.0, "created_at": now - dt.timedelta(days=300),
                                 "last_visit_date": last, "barcode_id": f"B{i}"})
        for k in range(4):
            db.visits.insert_one({"id": f"v{i}-{k}", "tenant_id": "t1", "customer_id": f"c{i:03d}",
                                  "amount_paid": 15.0, "visit_time": last - dt.timedelta(days=21 * k)})

    def rows(**q):
        return list(db.reco_events.find({"tenant_id": "t1", **q}, {"_id": 0}))

    print("Ce qui est montré")
    cp = http("GET", "/api/owner/copilot/page", headers=H)
    recs = (cp.json().get("recommendations") or {}).get("all") or []
    keys = {RJ.key_of(r) for r in recs} - {None}
    shown = {r["key"] for r in rows(kind="shown", surface="copilote")}
    check("Copilote: each idea on the page is recorded as shown", cp.status_code == 200 and keys and keys <= shown,
          (keys, shown))
    first = next(r for r in rows(kind="shown", surface="copilote") if r["key"] == RJ.key_of(recs[0]))
    check("…with its rank, what it is worth and how many clients", first["rank"] == 1 and "worth_eur" in first
          and "audience" in first, first)
    http("GET", "/api/owner/copilot/page", headers=H)
    again = next(r for r in rows(kind="shown", surface="copilote") if r["key"] == RJ.key_of(recs[0]))
    check("every page view counts (one row per idea and day, n = 2)", again["n"] == 2 and len(rows(kind="shown",
          surface="copilote", key=first["key"])) == 1, again)
    ins = http("GET", "/api/owner/insights/page", headers=H)
    check("Insights: recorded too", ins.status_code == 200 and rows(kind="shown", surface="insights"))
    det = http("GET", "/api/owner/brain/detectors", headers=H)
    rep = rows(kind="shown", surface="repere")
    check("« FidClic IA a repéré »: recorded with its full key (ia:…)", det.status_code == 200 and rep
          and all(r["key"].startswith("ia:") for r in rep), rep[:2])
    home = http("GET", "/api/owner/home/overview", headers=H)
    check("Tableau de bord: recorded too", home.status_code == 200 and rows(kind="shown", surface="dashboard"))
    check("nothing of t1 is written under t2", not db.reco_events.find_one({"tenant_id": "t2"}))
    check("no client id is kept in the journal", all("ids" not in r and "customer_id" not in r
                                                     for r in db.reco_events.find({}, {"_id": 0})))

    print("\nCe que le commerçant en fait")
    k = "relance_inactifs"
    t = http("GET", f"/api/owner/insights/templates/{k}", headers=H, params={"from": "copilote"})
    check("opening the composer from an idea records « opened » (with where from)",
          t.status_code == 200 and rows(kind="opened", key=k, surface="copilote"))
    http("GET", "/api/owner/insights/templates/ia:en_retard", headers=H, params={"from": "repere"})
    check("…full key for « a repéré »", rows(kind="opened", key="ia:en_retard", surface="repere"))
    http("GET", f"/api/owner/insights/templates/{k}", headers=H, params={"from": "<script>"})
    check("an unknown « from » is « autre »", rows(kind="opened", key=k, surface="autre"))
    http("GET", "/api/owner/insights/templates/client:c001", headers=H, params={"from": "clients"})
    check("a message to one client is not an idea: nothing recorded", not rows(key="client:c001"))
    for kind, label in (("not_relevant", "dismissed"), ("later", "later"), ("accepted", "accepted")):
        http("POST", f"/api/owner/copilot/recommendations/{k}/feedback", headers=H, json={"kind": kind})
        check(f"Copilote « {kind} » → {label}", rows(kind=label, key=k, surface="copilote"))
    db.reco_events.delete_many({})

    print("\nLa campagne garde son idée")
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Revenez", "message": "Bonjour {prénom}", "audience": {"mode": "all"},
                   "template": "ia", "reco_key": "ia:en_retard", "reco_surface": "repere", "draft": True})
    c = db.campaigns.find_one({"id": r.json().get("id")}) or {}
    check("compose keeps reco_key and where it came from", c.get("reco_key") == "ia:en_retard"
          and c.get("reco_surface") == "repere", {k2: c.get(k2) for k2 in ("reco_key", "reco_surface", "template")})
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "X", "message": "Y", "audience": {"mode": "all"}, "reco_key": "client:c001",
                   "reco_surface": "evil", "draft": True})
    c = db.campaigns.find_one({"id": r.json().get("id")}) or {}
    check("a one-client key or an odd surface is not kept", not c.get("reco_key") and c.get("reco_surface") in (None, "autre"), c.get("reco_surface"))
    check("an old campaign without reco_key reads its template", RJ.reco_of({"template": "relance_inactifs"}) == "relance_inactifs"
          and RJ.reco_of({"template": "client"}) is None and RJ.reco_of({"reco_key": "ia:x", "template": "ia"}) == "ia:x")

    print("\nCe que l'idée a rapporté (groupe témoin)")
    db.campaigns.delete_many({})
    # sent 20 days ago: 160 messaged, 40 témoin; messaged came back more and spent more
    sent_at = now - dt.timedelta(days=20)
    rec_ids = [f"r{i}" for i in range(160)]
    hold_ids = [f"h{i}" for i in range(40)]
    for i, cid in enumerate(rec_ids + hold_ids):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "visits": 1, "created_at": now - dt.timedelta(days=200),
                                 "last_visit_date": now - dt.timedelta(days=90)})
        came = (i < 80) if cid.startswith("r") else (i - 160 < 10)
        if came:
            db.visits.insert_one({"id": f"x{cid}", "tenant_id": "t1", "customer_id": cid, "amount_paid": 20.0,
                                  "visit_time": sent_at + dt.timedelta(days=3)})
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "status": "sent", "sent_at": sent_at, "name": "Relance",
                             "template": "relance_inactifs", "reco_key": "relance_inactifs", "reco_surface": "copilote",
                             "recipient_ids": rec_ids, "holdout_ids": hold_ids})
    out = RJ.outcomes("t1", now=now)
    o = out.get("relance_inactifs") or {}
    # messaged: 80/160 came, 20 € each → 10 €/client; témoin 10/40 → 5 €/client → +5 × 160 = 800 €
    check("measured: +800 € (10 €/client vs 5 €/client témoin, × 160)", o.get("extra_revenue") == 800.0 and o.get("enough"), o)
    line = RJ.line(o)
    check("owner's line: « La dernière fois : +800 € (mesuré avec le groupe témoin) »",
          line == "La dernière fois : +800 € (mesuré avec le groupe témoin)", line)
    RJ._cache.clear()
    db.copilot_feedback.delete_many({})          # the « pas pertinent » above hid it for 90 days
    cp = http("GET", "/api/owner/copilot/page", headers=H).json()
    hit = [x for x in (cp.get("recommendations") or {}).get("all") or [] if RJ.key_of(x) == "relance_inactifs"]
    check("…shown on the Copilote card", hit and (hit[0].get("last_result") or {}).get("text") == line,
          [RJ.key_of(x) for x in (cp.get("recommendations") or {}).get("all") or []])
    check("a pending one (< 15 days): « Envoyée le …, résultat le … »",
          RJ.line({"pending": 5, "sent_at": (now - dt.timedelta(days=3)).isoformat(), "enough": False}).startswith("Envoyée le "))
    check("too few témoin clients: said plainly",
          RJ.line({"pending": 0, "enough": False, "extra_revenue": 120.0}) == "La dernière fois : trop peu de clients témoins pour conclure")
    check("nothing gained: said plainly",
          RJ.line({"pending": 0, "enough": True, "extra_revenue": -40.0}) == "La dernière fois : pas de gain mesuré")
    check("never measured (no témoin): no line", RJ.line({}) is None and RJ.line(None) is None)
    check("t2 reads nothing of t1's results", RJ.outcomes("t2", now=now) == {})

    print("\nSuper admin — adoption, acceptation, exécution, ROI")
    db.reco_events.delete_many({})
    day = RJ.day_of(now)
    db.reco_events.insert_many([
        {"tenant_id": "t1", "sector": "cafe", "key": "relance_inactifs", "surface": "copilote", "kind": "shown", "day": day, "n": 3},
        {"tenant_id": "t1", "sector": "cafe", "key": "relance_inactifs", "surface": "copilote", "kind": "opened", "day": day, "n": 1},
        {"tenant_id": "t1", "sector": "cafe", "key": "offre_jour", "surface": "insights", "kind": "shown", "day": day, "n": 1},
        {"tenant_id": "t2", "sector": "salon", "key": "relance_inactifs", "surface": "dashboard", "kind": "shown", "day": day, "n": 2},
        {"tenant_id": "t2", "key": None, "kind": "shown", "day": "pas une date", "n": "x"},          # a broken row
    ])
    k_ = http("GET", "/api/admin/ai/recos", headers=BOSS, params={"days": 30})
    d = k_.json()
    tot = d.get("totals") or {}
    check("totals: 2 shops shown ideas, 1 opened one → adoption 50 %",
          k_.status_code == 200 and tot.get("shops_shown") == 2 and tot.get("shops_opened") == 1 and tot.get("adoption_pct") == 50, tot)
    check("acceptance = opened / shown ideas (shop × idea): 1 of 3 → 33 %", tot.get("acceptance_pct") == 33, tot)
    check("execution = sent / opened: 1 of 1 → 100 %", tot.get("sent") == 1 and tot.get("execution_pct") == 100, tot)
    check("ROI: 1 campaign measured, +800 €", tot.get("measured") == 1 and tot.get("euros") == 800.0, tot)
    by = {r["key"]: r for r in d.get("by_key") or []}
    check("by idea: relance_inactifs shown in 2 shops, opened in 1, sent 1, +800 €",
          by.get("relance_inactifs", {}).get("shops_shown") == 2 and by["relance_inactifs"].get("euros") == 800.0, by.get("relance_inactifs"))
    check("by surface and by sector", {r["surface"] for r in d.get("by_surface") or []} >= {"copilote", "dashboard", "insights"}
          and {r["sector"] for r in d.get("by_sector") or []} >= {"cafe", "salon"})
    check("a broken row is skipped, not fatal", k_.status_code == 200)
    check("a shop owner cannot read it", http("GET", "/api/admin/ai/recos", headers=H).status_code in (401, 403))
    from features import temoin as T
    calls = []
    real_block = T.campaign_block
    T.campaign_block = lambda *a, **k: calls.append(1) or real_block(*a, **k)
    RJ.kpis(now - dt.timedelta(days=30), now, now)
    T.campaign_block = real_block
    check("a finished result is kept on the campaign: read again, never recounted",
          not calls and (db.campaigns.find_one({"id": "k1"}) or {}).get("reco_result", {}).get("extra_revenue") == 800.0, calls)
    db.campaigns.insert_one({"id": "k2", "tenant_id": "t2", "status": "sent", "sent_at": (now - dt.timedelta(days=2)).isoformat(),
                             "template": "relance_inactifs", "recipient_ids": ["z1"], "holdout_ids": []})
    check("a campaign whose sent_at is ISO text (« Contacter (N) ») is counted too",
          RJ.kpis(now - dt.timedelta(days=30), now, now)["totals"]["sent"] == 2)
    reads = []
    real_agg = db.reco_events.aggregate
    db.reco_events.aggregate = lambda p, *a, **k: reads.append(p) or real_agg(p, *a, **k)
    RJ.kpis(now - dt.timedelta(days=7), now, now)
    db.reco_events.aggregate = real_agg
    check("only the period's days are read, grouped in the database",
          reads and "day" in reads[0][0]["$match"] and "$group" in reads[0][1], reads[:1])

    print("\nJamais bloquant")
    real = RJ._write
    RJ._write = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
    check("the journal down: Copilote still answers", http("GET", "/api/owner/copilot/page", headers=H).status_code == 200)
    check("…Insights, détecteurs, tableau de bord, composer too",
          all(http("GET", u, headers=H).status_code == 200 for u in
              ("/api/owner/insights/page", "/api/owner/brain/detectors", "/api/owner/home/overview",
               "/api/owner/insights/templates/relance_inactifs?from=copilote")))
    RJ._write = real
    db.reco_events.delete_many({})
    ok = http("GET", "/api/owner/copilot/page", headers=MGR).status_code == 200
    mine = list(db.reco_events.find({"tenant_id": "t1"}, {"_id": 0}))
    check("a manager's view records under the store it looks at", ok and mine and all(r.get("store_key") for r in mine), mine[:1])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
