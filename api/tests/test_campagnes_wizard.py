"""
Campagnes redesign (user's 9 mockups, 2026-10-10): the four kinds and their
step-1 terms, the audience of step 3 (all · segment · picked · km zone +
filters), the list's tabs and statuses, the card and the till, and the Défi
from start to reward. Edge cases first: every refusal writes nothing.

Run: cd api && /usr/local/bin/python3 tests/test_campagnes_wizard.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-campagnes-wizard")
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
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import campaign_kinds as K, defis as D

    db = server.db
    sent_push = []
    real_dispatch = server.dispatch_to_customer
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: (
        sent_push.append((cust.get("id"), title, kind)) or {"sent": True, "channel": "push"})
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    today = K.paris_today(now)
    iso = lambda d: d.isoformat()                                     # noqa: E731
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active",
         "lat": 47.394, "lng": 0.684},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active"},
    ])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, STAFF, H2 = tok("o@x.fr", "business_owner"), tok("s@x.fr", "staff"), tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Un café offert"})
    # 1 km ≈ 0.009° of latitude
    people = [("c1", "Alice Martin", 0.004, 120, 20, 5), ("c2", "Bruno Roy", 0.03, 40, 200, 1),
              ("c3", "Chloé Dubois", 0.12, 0, 3, 0), ("c4", "David Petit", None, 300, 60, 12)]
    for cid, name, dlat, pts, joined_days, visits in people:
        doc = {"id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-0000{cid.upper()}0", "points": pts,
               "visits": visits, "created_at": now - dt.timedelta(days=joined_days),
               "last_visit_date": now - dt.timedelta(days=2 if visits else 400)}
        if dlat is not None:
            doc.update(latitude=47.394 + dlat, longitude=0.684)
        db.customers.insert_one(doc)
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Autre", "barcode_id": "FT-0000X1000", "created_at": now})

    def compose(**kw):
        body = {"title": "-20% sur votre prochain achat", "message": "Bonjour {prénom} !", **kw}
        return http("POST", "/api/owner/campaigns/compose", json=body)

    def preview(**a):
        return http("POST", "/api/owner/campaigns/audience-preview", json={"audience": a})

    count0 = lambda: db.campaigns.count_documents({})                 # noqa: E731

    print("\n1. Offre spéciale — what step 1 accepts")
    n = count0()
    bad = [
        ({"discount_type": "percent", "discount_value": 0}, "0 %"),
        ({"discount_type": "percent", "discount_value": -5}, "négatif"),
        ({"discount_type": "percent", "discount_value": 101}, "101 %"),
        ({"discount_type": "amount", "discount_value": 10001}, "10 001 €"),
        ({"discount_type": "coupon", "discount_value": 5}, "type inconnu"),
        ({"start_date": iso(today + dt.timedelta(days=3)), "end_date": iso(today + dt.timedelta(days=1))}, "fin avant début"),
        ({"start_date": iso(today - dt.timedelta(days=9)), "end_date": iso(today - dt.timedelta(days=2))}, "déjà terminée"),
        ({"start_date": iso(today)}, "début sans fin"),
        ({"end_date": "2026-13-45"}, "date impossible"),
        ({"all_day": False}, "heures manquantes"),
        ({"all_day": False, "time_from": "19:00", "time_to": "17:00"}, "fin avant début (heures)"),
        ({"all_day": False, "time_from": "25:00", "time_to": "26:00"}, "heure impossible"),
    ]
    for offer, why in bad:
        r = compose(kind="offre", offer=offer)
        check(f"refused: {why} ({r.json().get('detail', '')[:60]})", r.status_code == 400)
    check("…and none of them was saved", count0() == n)
    r = compose(kind="unknown")
    check("an unknown kind is refused", r.status_code == 400)
    r = compose(kind="offre", offer={"discount_type": "percent", "discount_value": 20,
                                     "end_date": iso(today + dt.timedelta(days=7)), "all_day": False,
                                     "time_from": "17:00", "time_to": "19:00"})
    c = db.campaigns.find_one({"id": r.json().get("id")})
    check("an offer with only its last day starts today", r.status_code == 200 and c["offer"]["start_date"] == iso(today))
    check("…keeps its happy hours", c["offer"]["time_from"] == "17:00" and c["offer"]["time_to"] == "19:00")
    check("…and reaches everyone (4 clients of this shop, not the other's)", len(c["recipient_ids"]) == 4)
    check("its terms read « -20 % · du … au … · 17h–19h »",
          K.terms_label(c).startswith("-20 % · du ") and K.terms_label(c).endswith("17h–19h"))
    r = compose(kind="offre", offer={"discount_type": "amount", "discount_value": 5, "all_day": True,
                                     "time_from": "10:00", "time_to": "09:00"})
    c5 = db.campaigns.find_one({"id": r.json()["id"]})
    check("« Toute la journée » ignores any hours sent", r.status_code == 200 and c5["offer"]["time_from"] is None)
    check("« -5 € »", K.discount_label(c5["offer"]) == "-5 €")

    print("\n2. Événement, Nouveauté")
    check("an event needs its day", compose(kind="evenement", event={"place": "Ici"}).status_code == 400)
    check("an event already past is refused",
          compose(kind="evenement", event={"date": iso(today - dt.timedelta(days=1))}).status_code == 400)
    check("a wrong hour is refused",
          compose(kind="evenement", event={"date": iso(today), "time": "7h"}).status_code == 400)
    r = compose(kind="evenement", event={"date": iso(today + dt.timedelta(days=10)), "time": "18:00", "place": "Au café"},
                title="Soirée dégustation", details="Venez goûter nos nouveaux cafés.")
    ev = db.campaigns.find_one({"id": r.json()["id"]})
    check("an event is saved with its day, hour, place and details",
          ev["event"]["time"] == "18:00" and ev["event"]["place"] == "Au café" and ev["details"].startswith("Venez"))
    check("…and stays on the card until its day (not 30 days)",
          K.window(ev)[1] == K.end_of(today + dt.timedelta(days=10)))
    r = compose(kind="nouveaute", title="Nouveau menu", details="Trois nouveaux plats.", image_url="https://x.fr/a.png")
    check("a Nouveauté is saved with its details and photo", r.status_code == 200
          and db.campaigns.find_one({"id": r.json()["id"]})["kind"] == "nouveaute")

    print("\n3. Défi — what step 1 accepts")
    n = count0()
    for d, why in [({"target": 0, "end_date": iso(today + dt.timedelta(days=5)), "reward": "x", "reward_valid_days": 7}, "0 visite"),
                   ({"target": True, "end_date": iso(today + dt.timedelta(days=5)), "reward": "x", "reward_valid_days": 7}, "true"),
                   ({"target": 3, "end_date": iso(today - dt.timedelta(days=1)), "reward": "x", "reward_valid_days": 7}, "fini"),
                   ({"target": 9, "end_date": iso(today + dt.timedelta(days=2)), "count_mode": "per_day", "reward": "x",
                     "reward_valid_days": 7}, "9 visites en 3 jours, 1 par jour"),
                   ({"target": 3, "end_date": iso(today + dt.timedelta(days=5)), "reward": "  ", "reward_valid_days": 7}, "sans récompense"),
                   ({"target": 3, "end_date": iso(today + dt.timedelta(days=5)), "reward": "x", "reward_valid_days": 0}, "validité 0"),
                   ({"target": 3, "end_date": iso(today + dt.timedelta(days=5)), "reward": "x", "reward_valid_days": 400}, "validité 400"),
                   ({"target": 3, "end_date": iso(today + dt.timedelta(days=5)), "count_mode": "x", "reward": "x",
                     "reward_valid_days": 7}, "mode inconnu")]:
        r = compose(kind="defi", defi=d)
        check(f"refused: {why} ({r.json().get('detail', '')[:70]})", r.status_code == 400)
    check("…and none saved", count0() == n)
    r = compose(kind="defi", defi={"target": 9, "end_date": iso(today + dt.timedelta(days=2)), "count_mode": "per_scan",
                                   "reward": "1 dessert offert", "reward_valid_days": 14})
    check("9 visits in 3 days IS possible when every scan counts", r.status_code == 200)

    print("\n4. Destinataires")
    check("all → 4", preview(mode="all").json()["count"] == 4)
    check("a segment needs its key", preview(mode="segment").status_code == 400)
    check("an unknown segment is refused (never « everybody »)", preview(mode="segment", segment="nope").status_code == 400)
    check("new clients (30 days) → Alice and Chloé",
          set(preview(mode="segment", segment="new").json()["ids"]) == {"c1", "c3"})
    db.saved_segments.insert_one({"id": "s1", "tenant_id": "t1", "name": "Gros points",
                                  "rules": [{"field": "visits", "op": "gt", "value": 4}]})
    p = http("GET", "/api/owner/campaigns/page").json()
    check("Segmentation's own segments are offered", any(o["key"] == "seg:s1" for o in p["segment_options"]))
    check("…with their count", next(o for o in p["segment_options"] if o["key"] == "seg:s1")["count"] == 2)
    check("picked clients: another shop's id is dropped",
          preview(mode="custom", customer_ids=["c2", "x1"]).json()["ids"] == ["c2"])
    names = preview(mode="custom", customer_ids=["c2", "x1"]).json()["names"]
    check("the chosen clients come back with their names, another shop's never",
          names == {"c2": db.customers.find_one({"id": "c2"})["name"]})
    check("picking nobody is refused", preview(mode="custom", customer_ids=[]).status_code == 400)
    z1 = preview(mode="zone", km=1).json()
    check("within 1 km → Alice only (0,4 km)", z1["ids"] == ["c1"] and z1["zone"][0]["km"] < 1)
    z5 = preview(mode="zone", km=5).json()
    check("within 5 km → Alice and Bruno, nearest first",
          [r["id"] for r in z5["zone"]] == ["c1", "c2"])
    check("within 20 km → three (David has no position)", preview(mode="zone", km=20).json()["count"] == 3)
    check("a radius of 0 is refused", preview(mode="zone", km=0).status_code == 400)
    r = http("POST", "/api/owner/campaigns/audience-preview", headers=H2, json={"audience": {"mode": "zone", "km": 5}})
    check("a shop without a position is told plainly", r.status_code == 400 and "position" in r.json()["detail"])
    ALL4 = ["c1", "c2", "c3", "c4"]
    every = preview(mode="all", filters={"min_points": 100, "active": True, "inactive": True})
    check("« Tous les clients » ignores any filter: everyone, labelled plainly",
          every.status_code == 200 and set(every.json()["ids"]) == set(ALL4) and every.json()["label"] == "Tous les clients")
    check("« actifs » and « inactifs » together are refused",
          preview(mode="custom", customer_ids=ALL4, filters={"active": True, "inactive": True}).status_code == 400)
    check("minimum 100 points → Alice and David",
          set(preview(mode="custom", customer_ids=ALL4, filters={"min_points": 100}).json()["ids"]) == {"c1", "c4"})
    # everyone came 2 days ago, except Chloé who joined 3 days ago and never came
    # (aged from her signup, as on Clients): nobody is inactive yet
    check("« inactifs » → nobody yet", preview(mode="custom", customer_ids=ALL4, filters={"inactive": True}).json()["ids"] == [])
    check("« actifs » → those who came (Alice, Bruno, David)",
          set(preview(mode="custom", customer_ids=ALL4, filters={"active": True}).json()["ids"]) == {"c1", "c2", "c4"})
    check("« nouveaux » + ≥ 100 points → Alice",
          preview(mode="custom", customer_ids=ALL4, filters={"new": True, "min_points": 100}).json()["ids"] == ["c1"])
    s = preview(mode="all").json()["sample"]
    check("the preview's sample is a real client, with their points", s["first_name"] in ("Alice", "Bruno", "Chloé", "David")
          and "points" in s and s["next_reward"] == "Un café offert")
    r = compose(audience={"mode": "zone", "km": 5, "filters": {"min_points": 100}})
    c = db.campaigns.find_one({"id": r.json()["id"]})
    check("the send reaches exactly the preview (5 km + ≥100 pts → Alice)", c["recipient_ids"] == ["c1"]
          and c["audience_label"] == "À moins de 5 km · ≥ 100 points")
    r = compose(audience={"mode": "custom", "customer_ids": ["x1"]})
    check("a send to nobody is refused", r.status_code == 400)

    print("\n5. Planification")
    r = compose(kind="offre", offer={"discount_type": "percent", "discount_value": 10,
                                     "start_date": iso(today), "end_date": iso(today + dt.timedelta(days=1))},
                schedule_at=(now + dt.timedelta(days=5)).isoformat())
    check("an offer that would be over at its planned send is refused", r.status_code == 400)
    r = compose(kind="offre", offer={"discount_type": "percent", "discount_value": 10,
                                     "start_date": iso(today), "end_date": iso(today + dt.timedelta(days=9))},
                schedule_at=(now + dt.timedelta(days=5)).isoformat(), title="Plus tard")
    pid = r.json()["id"]
    check("a plan inside the offer's dates is saved « Programmée »", r.json()["status"] == "scheduled")
    db.campaigns.update_one({"id": pid}, {"$set": {"offer.end_date": iso(today + dt.timedelta(days=2))}})
    import features.campaigns_page as CPG
    CPG.run_due(now + dt.timedelta(days=5, minutes=1))
    gone = db.campaigns.find_one({"id": pid})
    check("one whose offer ended before it could leave is cancelled, never sent",
          gone["status"] == "cancelled" and gone.get("cancel_reason") and not gone.get("sent_at"))

    print("\n6. Vos campagnes récentes")
    db.campaigns.insert_many([
        {"id": "old", "tenant_id": "t1", "name": "Ancienne promo", "content": "x", "status": "sent", "kind": "offre",
         "offer": {"discount_type": "percent", "discount_value": 15, "start_date": iso(today - dt.timedelta(days=20)),
                   "end_date": iso(today - dt.timedelta(days=10)), "all_day": True},
         "sent_at": now - dt.timedelta(days=20), "recipient_ids": ["c1"], "created_at": now - dt.timedelta(days=20)},
        {"id": "legacy", "tenant_id": "t1", "name": "Message d'avant", "content": "x", "status": "sent",
         "sent_at": now - dt.timedelta(days=40), "recipient_ids": ["c1"], "created_at": now - dt.timedelta(days=40)},
        {"id": "dr", "tenant_id": "t1", "name": "Brouillon", "content": "x", "status": "draft", "recipient_ids": [],
         "created_at": now},
    ])
    L = lambda **q: http("GET", "/api/owner/campaigns/list", params=q).json()     # noqa: E731
    allr = L(tab="all", per_page=50)
    st = {r["id"]: r["status"] for r in allr["rows"]}
    check("an offer past its last day is « Terminée »", st["old"] == "ended")
    check("a campaign of before (no dates), 40 days ago, is « Terminée »", st["legacy"] == "ended")
    check("…and its type reads « Notification »",
          next(r for r in allr["rows"] if r["id"] == "legacy")["type_label"] == "Notification")
    check("a draft reads « Brouillon »", st["dr"] == "draft")
    check("a live one reads « En cours »", any(r["status"] == "live" for r in allr["rows"]))
    check("the plan cancelled by the cron is under « Annulées »", any(r["id"] == pid for r in L(tab="cancelled")["rows"]))
    check("tabs count what they show", allr["counts"]["ended"] == len(L(tab="ended", per_page=50)["rows"]))
    p1 = L(tab="all")
    check("five per page, with pages", len(p1["rows"]) == 5 and p1["pages"] == -(-allr["total"] // 5))
    check("search by name", [r["id"] for r in L(search="ancienne")["rows"]] == ["old"])
    check("an unknown tab is refused", http("GET", "/api/owner/campaigns/list", params={"tab": "x"}).status_code == 400)
    check("another shop sees none of these", http("GET", "/api/owner/campaigns/list", headers=H2).json()["total"] == 0)
    r = http("POST", f"/api/owner/campaigns/drafts/{pid}/cancel-schedule")
    check("cancelling twice is refused", r.status_code == 409)
    check("a cancelled one can be deleted", http("DELETE", f"/api/owner/campaigns/drafts/{pid}").status_code == 200)

    print("\n7. Sur la carte et en caisse")
    db.campaigns.delete_many({})
    long_end = today + dt.timedelta(days=40)
    r = compose(kind="offre", title="Happy hour", offer={"discount_type": "percent", "discount_value": 20,
                "start_date": iso(today), "end_date": iso(long_end), "all_day": True})
    card = server._serialize_card_payload(db.customers.find_one({"id": "c1"}))
    row = next(o for o in card["offers"] if o["id"] == r.json()["id"])
    check("an offer ending in 40 days is still on the card (not cut at 30)", row["valid_until"].startswith(
        K.end_of(long_end).isoformat()[:10]) or K.end_of(long_end).isoformat()[:13] in row["valid_until"])
    check("…with its terms and its « -20 % »", row["discount_label"] == "-20 %" and row["terms"].startswith("-20 %"))
    pre = http("GET", "/api/owner/scan/preview", headers=STAFF, params={"barcode": "FT-0000C10"}).json()
    check("the till reminds « Offre active : -20 % » for this client", [o["label"] for o in pre["offers_active"]] == ["-20 %"])
    c = db.campaigns.find_one({"id": r.json()["id"]})
    hm = now.astimezone(K.PARIS)
    outside = dict(c, offer={**c["offer"], "all_day": False, "time_from": "00:00", "time_to": "00:01"})
    inside = dict(c, offer={**c["offer"], "all_day": False,
                            "time_from": (hm - dt.timedelta(minutes=30)).strftime("%H:%M") if hm.hour else "00:00",
                            "time_to": (hm + dt.timedelta(minutes=30)).strftime("%H:%M") if hm.hour < 23 else "23:59"})
    t_now = dt.datetime.now(dt.timezone.utc)
    check("outside its happy hour it is not active at the till", not K.active_now(outside, t_now) or hm.strftime("%H:%M") < "00:01")
    check("inside its happy hour it is", K.active_now(inside, t_now))
    rendered = server.render_template("Bonjour {prénom}, {visites} visites chez {nom_commerce} — {prochaine_récompense}",
                                      db.customers.find_one({"id": "c1"}), db.tenants.find_one({"id": "t1"}))
    check(f"the wizard's French variables are filled ({rendered})",
          rendered == "Bonjour Alice, 5 visites chez Café Lumière — Un café offert")

    print("\n8. Défi, du début à la récompense")
    db.visits.delete_many({})
    r = compose(kind="defi", title="Défi de la semaine", message="3 visites = 1 dessert",
                audience={"mode": "custom", "customer_ids": ["c1", "c2"]},
                defi={"target": 3, "end_date": iso(today + dt.timedelta(days=6)), "count_mode": "per_day",
                      "reward": "1 dessert offert", "reward_valid_days": 10})
    did = r.json()["id"]
    # the défi started three days ago, Alice came the day before yesterday
    db.campaigns.update_one({"id": did}, {"$set": {"sent_at": now - dt.timedelta(days=3)}})
    db.visits.insert_one({"tenant_id": "t1", "customer_id": "c1", "visit_time": now - dt.timedelta(days=2), "amount_paid": 3})
    db.visits.insert_one({"tenant_id": "t1", "customer_id": "c1", "visit_time": now - dt.timedelta(days=5), "amount_paid": 3})
    cv = D.card_view(db.customers.find_one({"id": "c1"}))
    check("before the défi's start does not count: 1 / 3", cv["running"][0]["progress"] == 1 and cv["running"][0]["target"] == 3)
    check("the card shows it with its reward and days left", cv["running"][0]["reward"] == "1 dessert offert"
          and cv["running"][0]["days_left"] == 7)
    check("it is not an offer on the card (it has its own block)",
          all(o["id"] != did for o in server._serialize_card_payload(db.customers.find_one({"id": "c1"}))["offers"]))
    scan = lambda bc, h=STAFF: http("POST", "/api/owner/scan", headers=h, json={"barcode_id": bc, "amount_paid": 4}).json()  # noqa: E731
    s1 = scan("FT-0000C10")
    check("today's visit: 2 / 3, not won", not s1["defis_won"])
    s2 = scan("FT-0000C10")
    check("a second visit the same day does not count (one per day)", not s2["defis_won"]
          and D.card_view(db.customers.find_one({"id": "c1"}))["running"][0]["progress"] == 2)
    db.visits.insert_one({"tenant_id": "t1", "customer_id": "c1", "visit_time": now - dt.timedelta(days=1), "amount_paid": 3})
    sent_push.clear()
    s3 = scan("FT-0000C10")
    check("the third day wins it", [w["reward"] for w in s3["defis_won"]] == ["1 dessert offert"])
    check("« Défi réussi ! » is sent, outside the daily limit", [(k, t) for _, t, k in sent_push if k == "defi_won"]
          and "defi_won" in __import__("features.send_rules", fromlist=["x"]).EXEMPT)
    check("the till shows it to hand over", [x["reward"] for x in s3["defi_rewards"]] == ["1 dessert offert"])
    s4 = scan("FT-0000C10")
    check("won once: another visit wins nothing more", not s4["defis_won"]
          and db.defi_rewards.count_documents({"campaign_id": did, "customer_id": "c1"}) == 1)
    cv = D.card_view(db.customers.find_one({"id": "c1"}))
    check("the card: no longer running, the reward waiting", not cv["running"] and cv["won"][0]["reward"] == "1 dessert offert")
    exp = dt.datetime.fromisoformat(cv["won"][0]["expires_at"])
    check("the reward is valid the days the owner chose (10)", abs((exp - now).days - 10) <= 1)
    rid = cv["won"][0]["id"]
    check("another shop cannot hand it over", http("POST", f"/api/owner/defis/rewards/{rid}/redeem", headers=H2).status_code == 404)
    check("staff hand it over", http("POST", f"/api/owner/defis/rewards/{rid}/redeem", headers=STAFF).status_code == 200)
    check("…once", http("POST", f"/api/owner/defis/rewards/{rid}/redeem", headers=STAFF).status_code == 409)
    s5 = scan("FT-0000C20")
    check("Bruno (1 visit) is at 1 / 3", not s5["defis_won"]
          and D.card_view(db.customers.find_one({"id": "c2"}))["running"][0]["progress"] == 1)
    s6 = scan("FT-0000C30")
    check("Chloé is not in this défi", not D.card_view(db.customers.find_one({"id": "c3"}))["running"])
    db.campaigns.update_one({"id": did}, {"$set": {"defi.end_date": iso(today - dt.timedelta(days=1))}})
    check("after its last day it disappears from the card", not D.card_view(db.customers.find_one({"id": "c2"}))["running"])
    db.defi_rewards.insert_one({"id": "exp", "tenant_id": "t1", "campaign_id": "z", "customer_id": "c2", "reward": "x",
                                "status": "pending", "won_at": now - dt.timedelta(days=30),
                                "expires_at": now - dt.timedelta(days=1)})
    check("an expired reward is not offered at the till", all(x["id"] != "exp" for x in D.pending_rewards("c2")))
    check("…nor handed over", http("POST", "/api/owner/defis/rewards/exp/redeem", headers=STAFF).status_code == 409)
    r = compose(kind="defi", title="Chaque passage", audience={"mode": "custom", "customer_ids": ["c3"]},
                defi={"target": 2, "end_date": iso(today + dt.timedelta(days=3)), "count_mode": "per_scan",
                      "reward": "Un cookie", "reward_valid_days": 3})
    scan("FT-0000C30")
    check("counting every scan: two the same day win it", [w["reward"] for w in scan("FT-0000C30")["defis_won"]] == ["Un cookie"])

    print("\n9. Les chiffres du mois")
    p = http("GET", "/api/owner/campaigns/page").json()
    check("the five figures are there, « vs. mois précédent »", len(p["strip"]) == 5 and p["month_label"] == "vs. mois précédent")
    check("kinds are offered", [k["key"] for k in p["kinds"]] == ["offre", "nouveaute", "evenement", "defi", "configurer"])
    check("the shop's position is known (zone possible)", p["has_position"] is True)

    print("\n10. Configurer une offre — any other message")
    db.campaigns.delete_many({})
    n = count0()
    r = compose(kind="configurer", title="Soirée privée",
                offer={"start_date": iso(today + dt.timedelta(days=3)), "end_date": iso(today + dt.timedelta(days=1))})
    check("its dates are checked like an offer's", r.status_code == 400 and count0() == n)
    r = compose(kind="configurer", title="Soirée privée", offer={"all_day": False, "time_from": "20:00", "time_to": "18:00"})
    check("…and its hours", r.status_code == 400 and count0() == n)
    end7 = today + dt.timedelta(days=7)
    r = compose(kind="configurer", title="Un café offert pour 2 achetés", details="Du lundi au vendredi.",
                offer={"discount_type": "percent", "discount_value": 50, "start_date": iso(today), "end_date": iso(end7),
                       "all_day": False, "time_from": "08:00", "time_to": "11:00"},
                audience={"mode": "custom", "customer_ids": ["c1"]})
    cf = db.campaigns.find_one({"id": r.json().get("id")})
    check("it is saved as « Configurer une offre »", r.status_code == 200 and cf["kind"] == "configurer"
          and K.KINDS[cf["kind"]] == "Configurer une offre")
    check("a discount sent by mistake is dropped (this type has none)",
          cf["offer"]["discount_type"] is None and cf["offer"]["discount_value"] is None)
    check("its terms read « du … au … · 8h–11h »", K.terms_label(cf).startswith("du ") and K.terms_label(cf).endswith("8h–11h"))
    check("it stays live until its last day", K.window(cf)[1] == K.end_of(end7))
    card = server._serialize_card_payload(db.customers.find_one({"id": "c1"}))
    row = next((o for o in card["offers"] if o["id"] == cf["id"]), None)
    check("it is on the client's card like an offer, with its description",
          row is not None and row["details"] == "Du lundi au vendredi." and not row.get("discount_label"))
    check("…not on a client who did not get it",
          all(o["id"] != cf["id"] for o in server._serialize_card_payload(db.customers.find_one({"id": "c2"}))["offers"]))
    lr = http("GET", "/api/owner/campaigns/list", params={"kind": "configurer"}).json()
    check("the list's type filter finds it, typed « Configurer une offre »",
          [x["type_label"] for x in lr["rows"]] == ["Configurer une offre"])

    print("\n11. Une campagne ouverte (clic sur la ligne)")
    db.visits.insert_many([
        {"id": "v-a", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 12.5, "visit_time": now + dt.timedelta(minutes=5)},
        {"id": "v-b", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 7.5, "visit_time": now + dt.timedelta(minutes=9)},
        {"id": "v-c", "tenant_id": "t1", "customer_id": "c2", "amount_paid": 99, "visit_time": now + dt.timedelta(minutes=5)},
        {"id": "v-d", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 50, "visit_time": now + dt.timedelta(days=20)},
    ])
    det = http("GET", f"/api/owner/campaigns/{cf['id']}/detail").json()
    check("it shows what was said, to whom and when", det["message"] == "Bonjour {prénom} !"
          and det["details"] == "Du lundi au vendredi." and det["recipients"] == 1 and det["sent_at"])
    st = det["stats"] or {}
    check("one recipient came back within 15 days (not the client who never got it)",
          st.get("recipients") == 1 and st.get("came_back") == 1 and st.get("came_back_rate") == 100)
    check("its CA counts that client's visits inside 15 days only (12,50 + 7,50 €)", st.get("revenue") == 20.0)
    # to whom by name, and by whom (user, 2026-10-20: « kisko target kiya gaya tha »)
    check(f"« Envoyée à » names the client ({det.get('recipients_list')})",
          [p["name"] for p in det.get("recipients_list") or []] == ["Alice Martin"] and det.get("recipients_more") == 0)
    db.users.update_one({"email": "o@x.fr"}, {"$set": {"first_name": "Olivia", "last_name": "Owner"}})
    det = http("GET", f"/api/owner/campaigns/{cf['id']}/detail").json()
    check(f"« Envoyée par » names the team member and the role ({det.get('sent_by_label')})",
          (det.get("sent_by_label") or "").startswith("Olivia Owner ("))
    # sent from « Accéder au compte »: the token says the owner, the campaign says FidClic
    ADMIN_AS = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "view_by": "admin@fidelitour.com",
         "act_by": "admin@fidelitour.com"})}
    r_as = http("POST", "/api/owner/campaigns/compose", headers=ADMIN_AS,
                json={"title": "Test admin", "message": "Bonjour", "customer_ids": ["c1"]})
    if r_as.status_code == 200:
        det_as = http("GET", f"/api/owner/campaigns/{r_as.json()['id']}/detail").json()
        check(f"sent from « Accéder au compte »: « Super admin FidClic » ({det_as.get('sent_by_label')})",
              det_as.get("sent_by_label") == "Super admin FidClic")
        db.campaigns.delete_one({"id": r_as.json()["id"]})
    else:
        check(f"sent from « Accéder au compte » ({r_as.status_code} {r_as.text[:120]})", False)
    check("a sent campaign can't be edited, cancelled or deleted from it",
          not det["can_edit"] and not det["can_cancel"] and not det["can_delete"])
    check("its card window is given", det["live_until"] is not None and det["live_until"][:10] == K.end_of(end7).isoformat()[:10])
    later = (now + dt.timedelta(days=2)).isoformat()
    sid = compose(kind="nouveaute", title="Nouveau menu", schedule_at=later).json()["id"]
    det = http("GET", f"/api/owner/campaigns/{sid}/detail").json()
    check("a planned one has no figures yet, and can be edited or cancelled",
          det["stats"] is None and det["status"] == "scheduled" and det["can_edit"] and det["can_cancel"] and not det["can_delete"])
    did = compose(kind="nouveaute", title="Brouillon", draft=True).json()["id"]
    det = http("GET", f"/api/owner/campaigns/{did}/detail").json()
    check("a draft can be edited and deleted", det["status"] == "draft" and det["can_edit"] and det["can_delete"])
    check("another shop can't open it", http("GET", f"/api/owner/campaigns/{cf['id']}/detail", headers=H2).status_code == 404)
    check("an unknown id is a plain 404", http("GET", "/api/owner/campaigns/nope/detail").status_code == 404)
    check("staff can't open campaigns", http("GET", f"/api/owner/campaigns/{cf['id']}/detail", headers=STAFF).status_code == 403)
    db.campaigns.update_one({"id": cf["id"]}, {"$set": {"link_url": "javascript:alert(1)"}})
    check("a stored link that is not http(s) is never handed out",
          http("GET", f"/api/owner/campaigns/{cf['id']}/detail").json()["link_url"] is None)

    server.dispatch_to_customer = real_dispatch
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
