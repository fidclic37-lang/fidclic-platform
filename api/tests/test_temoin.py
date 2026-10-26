"""
Groupe témoin (user, 2026-10-25): 15 % of each group campaign / relance
automation, drawn at random per send, get nothing; 15 days later both groups
are compared — « +X € grâce à FidClic ». Never one client, never anniversaire
/ récompense / bienvenue; switchable in Paramètres; counts only, no names.

Run: cd api && /usr/local/bin/python3 tests/test_temoin.py
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
os.environ.setdefault("JWT_SECRET", "test-secret-temoin")
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
    from features import automations as AU
    from features import campaigns_page as CPG
    from features import temoin as T

    db = server.db
    pushed = []
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: (
        pushed.append((cust["id"], kind)) or {"sent": True})
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "m@x.fr", "role": "manager", "tenant_id": "t1", "active": True},
                          {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "B"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, MGR, BOSS = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager"), tok("boss@fidclic.com", "super_admin", None)
    for i in range(40):
        db.customers.insert_one({"id": f"c{i:02d}", "tenant_id": "t1", "name": f"Client {i}", "visits": 2,
                                 "created_at": now - dt.timedelta(days=200), "barcode_id": f"B{i}",
                                 "last_visit_date": now - dt.timedelta(days=100)})

    print("Le tirage")
    people = [{"id": f"p{i}"} for i in range(100)]
    sent, held = T.split("t1", people, "seed-a")
    check("100 clients: 85 messaged, 15 témoin, nobody twice",
          len(sent) == 85 and len(held) == 15 and not {c["id"] for c in sent} & {c["id"] for c in held})
    check("the same send draws the same témoin", [c["id"] for c in T.split("t1", people, "seed-a")[1]]
          == [c["id"] for c in held])
    check("another send, another draw", {c["id"] for c in T.split("t1", people, "seed-b")[1]} != {c["id"] for c in held})
    check("fewer than 7 clients: nobody held", T.split("t1", people[:6], "x")[1] == [])
    check("one client (« Contacter », profil): never", T.split("t1", people, "x", "client")[1] == []
          and T.split("t1", people, "x", "brain")[1] == [])

    print("Une campagne")
    r = http("POST", "/api/owner/campaigns/audience-preview", headers=H, json={"audience": {"mode": "all"}})
    check("the composer is told: 6 of 40 kept out", r.json()["count"] == 40 and r.json()["temoin"] == 6
          and r.json()["temoin_share"] == 15, r.json())
    one = http("POST", "/api/owner/campaigns/audience-preview", headers=H,
               json={"audience": {"mode": "custom", "customer_ids": ["c01"]}, "template": "client"}).json()
    check("… and nothing for one client", one["temoin"] == 0)
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Une attention", "message": "Bonjour {prénom}", "audience": {"mode": "all"}})
    c = db.campaigns.find_one({"id": r.json()["id"]})
    check("sent to 34, the 6 others are its témoin", r.status_code == 200 and r.json()["audience"] == 34
          and r.json()["temoin"] == 6 and len(c["recipient_ids"]) == 34 and len(c["holdout_ids"]) == 6, r.json())
    fed = set(db.push_notifications.distinct("customer_id", {"campaign_id": c["id"]}))
    check("the témoin gets no card message and no push",
          not fed & set(c["holdout_ids"]) and not {p[0] for p in pushed} & set(c["holdout_ids"]) and len(fed) == 34)
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Pour vous", "message": "Bonjour", "customer_ids": ["c01"], "template": "client"})
    check("« Contacter » one client: sent, no témoin", r.json()["audience"] == 1
          and not db.campaigns.find_one({"id": r.json()["id"]}).get("holdout_ids"))
    later = (now + dt.timedelta(days=2)).isoformat()
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Plus tard", "message": "Bonjour", "audience": {"mode": "all"}, "schedule_at": later})
    planned = db.campaigns.find_one({"id": r.json()["id"]})
    pushed.clear()
    CPG.run_due(now + dt.timedelta(days=2, minutes=1))
    check("a scheduled one leaves without its témoin", len(planned["holdout_ids"]) == 6
          and not {p[0] for p in pushed} & set(planned["holdout_ids"]) and len(pushed) == 34)

    print("Clients › « Contacter (N) » et les anciennes campagnes récurrentes")
    pushed.clear()
    ids20 = [f"c{i:02d}" for i in range(20)]
    r = http("POST", "/api/owner/campaigns/send-to-group", headers=H,
             json={"customer_ids": ids20, "name": "Coucou", "content": "Bonjour"})
    g = db.campaigns.find_one({"id": r.json()["id"]})
    check("« Contacter (20) »: 17 messaged, 3 témoin", r.json()["temoin"] == 3 and len(g["recipient_ids"]) == 17
          and len(g["holdout_ids"]) == 3 and not {p[0] for p in pushed} & set(g["holdout_ids"])
          and not db.push_notifications.find_one({"campaign_id": g["id"], "customer_id": {"$in": g["holdout_ids"]}}), r.json())
    r = http("POST", "/api/owner/campaigns/send-to-group", headers=H,
             json={"customer_ids": ["c01", "c02"], "name": "Coucou", "content": "Bonjour"})
    check("… two clients: both get it", r.json()["temoin"] == 0 and r.json()["targeted_count"] == 2)
    pushed.clear()
    old_style = server._dispatch_campaign_to_customers(db.tenants.find_one({"id": "t1"}), "Chaque lundi", "Bonjour",
                                                       list(db.customers.find({"tenant_id": "t1"}, {"_id": 0})),
                                                       trigger_type="scheduled")
    oc = db.campaigns.find_one({"id": old_style["id"]})
    check("an old recurring campaign keeps its 15 % out too", len(oc["holdout_ids"]) == 6 and len(oc["recipient_ids"]) == 34
          and not {p[0] for p in pushed} & set(oc["holdout_ids"]))

    print("Ce qu'elle a rapporté")
    sent_ids = [f"s{i}" for i in range(85)]
    hold_ids = [f"h{i}" for i in range(15)]
    at = now - dt.timedelta(days=20)
    for i, cid in enumerate(sent_ids + hold_ids):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "visits": 3, "created_at": now - dt.timedelta(days=300)})
    for i, cid in enumerate(sent_ids):       # 40 % came back, 20 € each
        if i % 5 < 2:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": 20.0,
                                  "visit_time": at + dt.timedelta(days=3)})
    for i, cid in enumerate(hold_ids):       # 20 %, 20 € each
        if i % 5 == 0:
            db.visits.insert_one({"tenant_id": "t1", "customer_id": cid, "amount_paid": 20.0,
                                  "visit_time": at + dt.timedelta(days=3)})
    db.visits.insert_one({"tenant_id": "t1", "customer_id": "h1", "amount_paid": 99.0,
                          "visit_time": at - dt.timedelta(days=1)})            # before: not counted
    db.campaigns.insert_one({"id": "old", "tenant_id": "t1", "name": "Vieille", "content": "x", "status": "sent",
                             "kind": "info", "sent_at": at, "created_at": at, "recipient_ids": sent_ids,
                             "holdout_ids": hold_ids, "channels": {"push": True, "wallet": False}})
    m = T.measure("t1", T._rows_campaign(db.campaigns.find_one({"id": "old"})), now)
    check("40 % back among the messaged, 20 % in the témoin: +20 points",
          m["sent"]["rate"] == 40.0 and m["temoin"]["rate"] == 20.0 and m["points"] == 20.0, m)
    check("+340 € grâce à FidClic ((8 € − 4 €) × 85), about 17 more clients",
          m["extra_revenue"] == 340.0 and m["extra_clients"] == 17, m)
    check("15 témoin clients: said not to be enough yet", not m["enough"])
    d = http("GET", "/api/owner/campaigns/old/detail", headers=H).json()
    tb = d["stats"]["temoin"]
    check("the campaign's detail: both groups and the figure", tb["counts"] == {"sent": 85, "temoin": 15}
          and tb["extra_revenue"] == 340.0, tb)
    check("… never the témoin's names", not any(h in str(d) for h in ("'h0'", '"h0"', "h11")))
    fresh = T.campaign_block("t1", c, now)
    check("a send still inside its 15 days: in progress, no figure", fresh["pending"] == 40 and fresh["sent"]["n"] == 0
          and fresh["extra_revenue"] is None, fresh)

    print("Automatisations de relance")
    row = {"id": "a-inact", "tenant_id": "t1", "scenario": "inactive", "status": "active", "name": "Relance",
           "trigger": {"days": 30}, "message": {"title": "On vous attend", "body": "Bonjour"}}
    db.automations.insert_one(dict(row))
    pushed.clear()
    said = [AU._deliver("t1", row, db.customers.find_one({"id": f"c{i:02d}"}, {"_id": 0}), {}, now) for i in range(40)]
    logs = list(db.automation_log.find({"automation_id": "a-inact"}))
    held_logs = [g for g in logs if g["status"] == "holdout"]
    drawn = {f"c{i:02d}" for i in range(40) if T.holds_automation("t1", row, f"c{i:02d}", now)}
    check("the témoin is exactly who the draw picked", {g["customer_id"] for g in held_logs} == drawn, len(held_logs))
    # the share on a fixed moment (40 draws at « now » made it flaky, ~2 % of runs)
    fixed = dt.datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    share = sum(T.holds_automation("t1", row, f"x{i}", fixed) for i in range(2000)) / 2000
    check(f"about 15 % kept out over 2 000 draws ({share:.1%})", 0.13 <= share <= 0.17)
    check("a fresh draw per message: another moment, other clients",
          {i for i in range(200) if T.holds_automation("t1", row, f"x{i}", fixed)}
          != {i for i in range(200) if T.holds_automation("t1", row, f"x{i}", fixed + dt.timedelta(days=1))})
    hid = {g["customer_id"] for g in held_logs}
    check("the témoin: logged, but no message, no push, no card news",
          not {p[0] for p in pushed} & hid and not db.push_notifications.find_one({"automation_id": "a-inact",
                                                                                   "customer_id": {"$in": list(hid)}})
          and sum(1 for s in said if s is None) == len(hid)
          and not any((db.customers.find_one({"id": h}) or {}).get("auto_news") for h in hid))
    due = {c["id"] for c in AU._inactive_due("t1", row, now + dt.timedelta(days=1))}
    check("« once per absence »: a témoin client is not drawn again tomorrow", not due & hid)
    view = AU._row_view(db.automations.find_one({"id": "a-inact"}, {"_id": 0}), "t1")
    check("the automation's results: messaged vs témoin, figure pending",
          view and view["temoin"]["counts"]["temoin"] == len(hid) and view["temoin"]["pending"] == 40
          and view["sent"] == 40 - len(hid), view and view.get("temoin"))
    bday = {"id": "a-bday", "tenant_id": "t1", "scenario": "birthday", "status": "active",
            "message": {"title": "Joyeux anniversaire", "body": "Bonjour"}}
    gave = [AU._deliver("t1", bday, db.customers.find_one({"id": f"c{i:02d}"}, {"_id": 0}), {}, now) for i in range(40)]
    check("anniversaire: everyone, always", all(gave) and not db.automation_log.find_one({"automation_id": "a-bday",
                                                                                      "status": "holdout"}))

    print("Analyses")
    a = http("GET", "/api/owner/analyses?tab=vue&days=30", headers=H).json()["data"]["impact"]["uplift"]
    check("Impact FidClic carries the témoin's answer, by source",
          a["enabled"] and a["by"]["campagnes"]["sent"]["n"] >= 85 and "automatisations" in a["by"], a)

    print("Paramètres")
    g = http("GET", "/api/owner/temoin", headers=H).json()
    check("on by default, 15 %", g["enabled"] and g["share"] == 15 and g["can_edit"])
    check("a manager cannot switch it off", http("PUT", "/api/owner/temoin", headers=MGR,
                                                 json={"enabled": False}).status_code == 403)
    http("PUT", "/api/owner/temoin", headers=H, json={"enabled": False})
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Sans témoin", "message": "Bonjour", "audience": {"mode": "all"}})
    everyone = db.customers.count_documents({"tenant_id": "t1"})
    check("switched off: everyone gets it", r.json()["audience"] == everyone and r.json()["temoin"] == 0, r.json())
    check("… and the composer says so", http("POST", "/api/owner/campaigns/audience-preview", headers=H,
                                            json={"audience": {"mode": "all"}}).json()["temoin"] == 0)
    check("… and relances are no longer held", not T.holds_automation("t1", row, "c01", now)
          and not any(T.holds_automation("t1", row, f"c{i}", now) for i in range(100)))
    off = http("GET", "/api/owner/analyses?tab=vue&days=30", headers=H).json()["data"]["impact"]["uplift"]
    check("Analyses knows it is off (« pas mesuré »)", off["enabled"] is False)
    http("PUT", "/api/owner/temoin", headers=H, json={"enabled": True})

    print("Super admin › Précision")
    u = http("GET", "/api/admin/ai/uplift", headers=BOSS)
    cafe = next((s for s in u.json()["sectors"] if s["sector"] == "cafe"), None)
    check("every shop's témoin, by sector", u.status_code == 200 and cafe and cafe["shops"] == 1
          and cafe["temoin"]["n"] >= 15 and cafe["per_100"] is not None, u.json())
    check("merchants: refused", http("GET", "/api/admin/ai/uplift", headers=H).status_code in (401, 403))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
