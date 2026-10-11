"""
Automatisations redesign (user's mockups, 2026-10-11): the eight scenarios,
the old settings carried over and the removed ones deleted, the wizard's
checks, targeting, the clock (hour, days, window, delay, catch-up), each
event, the action button from the push to its target, the Wallet pass and
the card, and the page's figures. Edge cases first: a refusal writes nothing.

Run: cd api && /usr/local/bin/python3 tests/test_automations_redesign.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-automations-redesign")
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
    from features import automations as AU

    db = server.db
    pushed, wallet = [], []
    defer = {"on": False}

    def fake_dispatch(tid, cust, title, body, kind="campaign", url=None):
        pushed.append({"cid": cust.get("id"), "title": title, "body": body, "kind": kind, "url": url})
        return {"deferred": True} if defer["on"] else {"sent": True, "channel": "push"}
    server.dispatch_to_customer = fake_dispatch
    WP.notify_customer = lambda cid, message=None, google_notify=None: wallet.append((cid, google_notify)) or {}
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active",
         "is_active": True, "google_review_url": "https://g.page/r/cafe/review", "google_reviews_enabled": True,
         "geo_enabled": True},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "m@x.fr", "role": "manager", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, MGR, STAFF, H2 = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager"), tok("s@x.fr", "staff"), \
        tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Un café offert"})

    def person(cid, name, **kw):
        doc = {"id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-{cid.upper()}", "points": 0, "visits": 0,
               "created_at": now - dt.timedelta(days=200), "last_visit_date": now - dt.timedelta(days=2), **kw}
        db.customers.insert_one(doc)
        return doc
    person("c1", "Alice Martin", gender="F", birth_date="1990-01-01", total_amount_paid=320, birthday="01-01")
    person("c2", "Bruno Roy", gender="M", birth_date="2004-05-05", total_amount_paid=20,
           last_visit_date=now - dt.timedelta(days=45))
    person("c3", "Chloé Dubois", wallet_added_at=now - dt.timedelta(days=5))

    # the OLD automations of this shop, before the redesign
    db.push_scenarios.insert_many([
        {"id": "o-bday", "tenant_id": "t1", "builtin": "birthday", "trigger": "birthday", "enabled": True,
         "title": "Joyeux anniversaire {first_name} !", "body": "Toute l'équipe de {business_name} vous souhaite…"},
        {"id": "o-inact", "tenant_id": "t1", "builtin": "inactive", "trigger": "inactivity", "enabled": False,
         "config": {"days": 45}, "title": "Revenez", "body": "On vous attend"},
        {"id": "o-offer", "tenant_id": "t1", "builtin": "special_offer", "trigger": "date_event", "enabled": True,
         "title": "Promo", "body": "-20%"},
        {"id": "o-cart", "tenant_id": "t1", "builtin": "cart_recovery", "trigger": "inactivity", "enabled": True,
         "title": "Panier", "body": "x"},
        {"id": "o-mine", "tenant_id": "t1", "trigger": "time_slot", "enabled": True, "title": "Happy", "body": "y"},
    ])
    db.push_wallet_log.insert_many([{"id": "l1", "tenant_id": "t1", "scenario_id": "o-offer", "customer_id": "c1"},
                                    {"id": "l2", "tenant_id": "t1", "scenario_id": "o-bday", "customer_id": "c1"}])
    db.push_wallet_pending.insert_one({"id": "lot", "tenant_id": "t1", "scenario_id": "o-cart"})
    db.auto_message_config.insert_one({"tenant_id": "t1",
                                       "near_reward": {"enabled": True, "visits_left": 2, "title": "Plus que {visits_left} !",
                                                       "body": "Encore {visits_left} {visites} pour {reward}"},
                                       "google_review": {"enabled": True, "frequency": "days", "days": 10}})

    print("\n1. Les anciennes automatisations deviennent les nouvelles")
    page = http("GET", "/api/owner/automations").json()
    by = {}
    for r in page["rows"]:
        by.setdefault(r["scenario"], []).append(r)
    check("only the eight scenarios, in the mockup's order",
          [s["key"] for s in page["scenarios"]] == AU.ORDER and set(by) <= set(AU.ORDER))
    check("the birthday keeps its words, in the wizard's French variables, and stays on",
          by["birthday"][0]["message"]["title"] == "Joyeux anniversaire {prénom} !" and by["birthday"][0]["status"] == "active")
    check("Client inactif keeps its 45 days and stays off", by["inactive"][0]["trigger"]["days"] == 45
          and by["inactive"][0]["status"] == "paused")
    check("Proche de la récompense keeps X = 2 and its words",
          by["near_reward"][0]["trigger"]["visits_left"] == 2 and "{visites_restantes}" in by["near_reward"][0]["message"]["title"])
    check("Avis Google keeps every 10 days, with its review button",
          by["google_review"][0]["trigger"]["every_days"] == 10 and by["google_review"][0]["message"]["button"]["link_type"] == "google_review")
    check("Parrainage: one for the parrain, one for the filleul",
          sorted(r["trigger"]["side"] for r in by["referral"]) == ["filleul", "parrain"])
    check("Offre spéciale, Relance panier and the shop's own « Plage horaire » are gone, data included",
          db.push_scenarios.count_documents({"tenant_id": "t1"}) == 0
          and not db.push_wallet_log.find_one({"id": "l1"}) and db.push_wallet_log.find_one({"id": "l2"}))
    check("nothing waits for an OK any more", db.push_wallet_pending.count_documents({}) == 0)
    n_rows = len(page["rows"])
    check("reading again changes nothing (once per shop)", len(http("GET", "/api/owner/automations").json()["rows"]) == n_rows)
    check("another shop sees none of them", all(r["id"] not in {x["id"] for x in page["rows"]}
                                                 for r in http("GET", "/api/owner/automations", headers=H2).json()["rows"]))

    print("\n2. Ce que l'assistant accepte")
    base = {"scenario": "inactive", "name": "Inactifs 60 j", "status": "active",
            "trigger": {"days": 60, "repeat": "once"},
            "message": {"title": "On vous attend {prénom}", "body": "Revenez chez {nom_commerce} !",
                        "button": {"enabled": True, "label": "Voir mon offre", "link_type": "url", "url": "monsite.fr/menu"}},
            "targeting": {"mode": "all", "filters": {}}, "schedule": {"days": "all", "hour": "10:00"}}
    count0 = db.automations.count_documents({"tenant_id": "t1"})

    def bad(patch, why):
        body = {**base, **patch}
        r = http("POST", "/api/owner/automations", json=body)
        check(f"refused: {why} ({r.json().get('detail', '')[:70]})", r.status_code == 400)
    bad({"scenario": "special_offer"}, "a removed scenario")
    bad({"message": {**base["message"], "title": ""}}, "no title")
    bad({"message": {**base["message"], "title": "x" * 61}}, "title over 60")
    bad({"message": {**base["message"], "body": "x" * 181}}, "message over 180")
    bad({"message": {**base["message"], "button": {"enabled": True, "label": "", "link_type": "card"}}}, "a button without text")
    bad({"message": {**base["message"], "button": {"enabled": True, "label": "Go", "link_type": "url", "url": "javascript:alert(1)"}}},
        "a javascript: link")
    bad({"message": {**base["message"], "button": {"enabled": True, "label": "Go", "link_type": "offer", "offer_id": "nope"}}},
        "an offer that doesn't exist")
    bad({"trigger": {"days": 3}}, "inactive under 7 days")
    bad({"trigger": {"days": True}}, "a boolean for days")
    bad({"schedule": {"days": "specific", "weekdays": [], "hour": "10:00"}}, "specific days with none ticked")
    bad({"schedule": {"days": "all", "hour": "25:00"}}, "an impossible hour")
    bad({"targeting": {"mode": "segment"}}, "a segment not chosen")
    bad({"targeting": {"mode": "all", "filters": {"age": "12-15"}}}, "an unknown age band")
    bad({"scenario": "referral", "trigger": {}}, "parrainage without its side")
    bad({"scenario": "geo", "trigger": {"cooldown_days": 0}}, "geo cooldown 0")
    bad({"scenario": "welcome", "schedule": {"days": "all", "window": True, "window_from": "21:00", "window_to": "09:00"}},
        "a window that ends before it starts")
    check("…and none of them was saved", db.automations.count_documents({"tenant_id": "t1"}) == count0)
    r = http("POST", "/api/owner/automations", json=base)
    a60 = r.json()
    check("a second Client inactif (60 j) is created next to the first", r.status_code == 200
          and len([x for x in http("GET", "/api/owner/automations").json()["rows"] if x["scenario"] == "inactive"]) == 2)
    check("its link was completed to https://", a60["message"]["button"]["url"] == "https://monsite.fr/menu")
    check("its trigger reads « Après 60 jours sans visite »", a60["trigger_text"] == "Après 60 jours sans visite")
    draft = http("POST", "/api/owner/automations", json={**base, "status": "draft",
                                                          "message": {"title": "", "body": "", "button": {"enabled": False}}}).json()
    check("a draft may be incomplete", draft.get("status") == "draft")
    r = http("POST", f"/api/owner/automations/{draft['id']}/status", json={"status": "active"})
    check("…but can't be switched on until complete", r.status_code == 400)
    r = http("PUT", f"/api/owner/automations/{a60['id']}", json={**base, "scenario": "birthday"})
    check("an automation never changes scenario", r.status_code == 400)
    check("a manager can't create one", http("POST", "/api/owner/automations", headers=MGR, json=base).status_code == 403)
    check("staff can't even read them", http("GET", "/api/owner/automations", headers=STAFF).status_code == 403)
    check("another shop can't touch it", http("DELETE", f"/api/owner/automations/{a60['id']}", headers=H2).status_code == 404)
    dup = http("POST", f"/api/owner/automations/{a60['id']}/duplicate").json()
    check("duplicate = a paused-free draft copy", dup["status"] == "draft" and dup["name"].endswith("(copie)"))
    check("delete removes it", http("DELETE", f"/api/owner/automations/{dup['id']}").status_code == 200
          and not db.automations.find_one({"id": dup["id"]}))

    print("\n3. Le ciblage")
    pv = lambda **t: http("POST", "/api/owner/automations/preview", json={"scenario": "inactive", "targeting": t}).json()  # noqa: E731
    check("all clients: 3", pv(mode="all")["count"] == 3)
    check("clients with a Wallet card: Chloé", pv(mode="wallet")["count"] == 1)
    check("« Tous mes clients » ignores filters (everyone, as in Campagnes)", pv(mode="all", filters={"gender": "F"})["count"] == 3)
    real_seg = AU._segment_ids
    AU._segment_ids = lambda tid, key, at: {"c1", "c2", "c3"} if key == "tous" else set()      # a segment of the three
    check("Genre femme: Alice", pv(mode="segment", segment="tous", filters={"gender": "F"})["count"] == 1)
    check("Âge 18–24: Bruno (born 2004)", pv(mode="segment", segment="tous", filters={"age": "18-24"})["count"] == 1)
    check("Montant > 200 €: Alice", pv(mode="segment", segment="tous", filters={"spent": "200-500"})["count"] == 1)
    check("Dernière visite > 30 j: Bruno", pv(mode="segment", segment="tous", filters={"last_visit": ">30"})["count"] == 1)
    check("a segment alone: its clients", pv(mode="segment", segment="tous")["count"] == 3)
    AU._segment_ids = real_seg
    check("a real client fills the preview", pv(mode="all")["sample"]["first_name"] in ("Alice", "Bruno", "Chloé"))

    print("\n4. Bienvenue, à l'inscription, dans sa plage horaire")
    wel = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "welcome"][0]
    http("PUT", f"/api/owner/automations/{wel['id']}", json={
        "scenario": "welcome", "status": "active", "trigger": {},
        "message": {"title": "Bienvenue {prénom} 🎉", "body": "Merci de nous rejoindre chez {nom_commerce} !",
                    "button": {"enabled": True, "label": "Voir ma carte", "link_type": "card"}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "window": False}})
    pushed.clear()
    r = http("POST", "/api/join/cafe", headers={}, json={"name": "Dina Sow", "phone": "0611111111", "postal_code": "37000",
                                                         "birthday": "02/03/1995", "consent": True})
    dina = db.customers.find_one({"barcode_id": r.json().get("barcode_id")}) or {}
    check(f"signing up sends the welcome at once ({r.status_code})",
          [p["title"] for p in pushed if p["cid"] == dina.get("id")] == ["Bienvenue Dina 🎉"])
    check("its tap goes through the counted link, the button's text riding on it",
          (pushed[-1]["url"] or "").startswith(AU.public_base() + "/api/auto/c/") and "?b=Voir%20ma%20carte" in pushed[-1]["url"])
    check("the welcome is never sent twice", AU.fire("welcome", "t1", dina) == [])
    card = server._serialize_card_payload(db.customers.find_one({"id": dina["id"]}))
    check("the card shows it at the top with its button", card["auto_message"]["title"] == "Bienvenue Dina 🎉"
          and card["auto_message"]["button_label"] == "Voir ma carte")
    log = db.automation_log.find_one({"customer_id": dina["id"]})
    r = http("GET", f"/api/auto/c/{log['id']}", headers={}, follow_redirects=False)
    check("the button opens the card itself (owner link, with its key)", r.status_code == 302
          and f"/card/{dina['barcode_id']}" in r.headers["location"] and "k=" in r.headers["location"])
    check("…and the click is counted", db.automation_log.find_one({"id": log["id"]})["clicked_at"] is not None)
    check("an unknown link is a 404", http("GET", "/api/auto/c/nope", headers={}, follow_redirects=False).status_code == 404)

    # a window 09:00–21:00: a signup at 23:00 Paris waits for 09:00
    http("PUT", f"/api/owner/automations/{wel['id']}", json={
        "scenario": "welcome", "status": "active", "trigger": {},
        "message": {"title": "Bienvenue {prénom}", "body": "Merci !", "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "window": True, "window_from": "09:00", "window_to": "21:00"}})
    late = dt.datetime(2026, 10, 14, 21, 0, tzinfo=UTC)           # 23:00 in Paris
    eva = person("c4", "Eva Petit")
    pushed.clear()
    res = AU.fire("welcome", "t1", eva, at=late)
    q = db.automation_queue.find_one({"customer_id": "c4"})
    check("at 23:00 it is not sent, it waits", not pushed and res and res[0].get("queued") and q)
    check("…for 09:00 Paris the next morning", q["due_at"].replace(tzinfo=UTC) == dt.datetime(2026, 10, 15, 7, 0, tzinfo=UTC))
    AU.run_due(dt.datetime(2026, 10, 15, 6, 45, tzinfo=UTC), source="tick")
    check("the 08:45 tick leaves it", not pushed)
    AU.run_due(dt.datetime(2026, 10, 15, 7, 0, tzinfo=UTC), source="tick")
    check("the 09:00 tick sends it, once", [p["cid"] for p in pushed] == ["c4"])
    AU.run_due(dt.datetime(2026, 10, 15, 7, 15, tzinfo=UTC), source="tick")
    check("…and never again", len(pushed) == 1)

    print("\n5. Anniversaire, à son heure")
    bd = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "birthday"][0]
    http("PUT", f"/api/owner/automations/{bd['id']}", json={
        "scenario": "birthday", "status": "active", "trigger": {"offset_days": -3},
        "message": {"title": "Bientôt votre anniversaire {prénom} !", "body": "Une surprise vous attend chez {nom_commerce}.",
                    "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "hour": "10:00"}})
    db.customers.update_one({"id": "c2"}, {"$set": {"birthday": "10-18"}})    # 3 days after the 15th
    pushed.clear()
    db.automation_meta.update_one({"_id": "tick"}, {"$set": {"at": dt.datetime(2026, 10, 15, 6, 0, tzinfo=UTC)}}, upsert=True)
    AU.run_due(dt.datetime(2026, 10, 15, 7, 30, tzinfo=UTC), source="tick")    # 09:30 Paris
    check("3 days before, at 09:30, not yet (10:00)", not [p for p in pushed if p["kind"] == "birthday"])
    AU.run_due(dt.datetime(2026, 10, 15, 8, 0, tzinfo=UTC), source="tick")     # 10:00 Paris
    check("at 10:00 Bruno gets it", [p["cid"] for p in pushed if p["kind"] == "birthday"] == ["c2"])
    AU.run_due(dt.datetime(2026, 10, 15, 9, 0, tzinfo=UTC), source="tick")
    AU.run_due(dt.datetime(2026, 10, 16, 8, 0, tzinfo=UTC), source="tick")
    check("not twice the same day, nor the next", len([p for p in pushed if p["kind"] == "birthday"]) == 1)
    # weekdays only: a birthday falling on a Saturday is caught up on Monday
    http("PUT", f"/api/owner/automations/{bd['id']}", json={
        "scenario": "birthday", "status": "active", "trigger": {"offset_days": 0},
        "message": {"title": "Joyeux anniversaire {prénom}", "body": "Bon anniversaire !", "button": {"enabled": False}},
        "targeting": {"mode": "all"}, "schedule": {"days": "weekdays", "hour": "10:00"}})
    db.automations.update_one({"id": bd["id"]}, {"$set": {"last_run_at": None}})
    db.customers.update_one({"id": "c3"}, {"$set": {"birthday": "10-17"}})    # Saturday 17 Oct 2026
    pushed.clear()
    AU.run_due(dt.datetime(2026, 10, 17, 8, 30, tzinfo=UTC), source="tick")    # Saturday
    check("« jours ouvrés »: nothing on Saturday", not pushed)
    AU.run_due(dt.datetime(2026, 10, 19, 8, 30, tzinfo=UTC), source="tick")    # Monday
    check("Monday catches up Chloé's Saturday birthday", [p["cid"] for p in pushed] == ["c3"])
    # without a 15-minute tick (Vercel Hobby) the daily run sends today's, early
    db.automation_meta.delete_one({"_id": "tick"})
    db.automations.update_one({"id": bd["id"]}, {"$set": {"last_run_at": None, "schedule.days": "all"}})
    db.customers.update_one({"id": "c1"}, {"$set": {"birthday": "10-20"}})
    pushed.clear()
    AU.run_due(dt.datetime(2026, 10, 20, 7, 0, tzinfo=UTC), source="daily")   # 09:00 Paris, before 10:00
    check("no tick seen: the daily run at 09:00 still sends today's birthday", [p["cid"] for p in pushed] == ["c1"])

    print("\n6. Client inactif")
    inact = [r for r in http("GET", "/api/owner/automations").json()["rows"]
             if r["scenario"] == "inactive" and r["name"] == "Inactifs 60 j"][0]
    http("PUT", f"/api/owner/automations/{inact['id']}", json={**base, "trigger": {"days": 30, "repeat": "once"}})
    for d in [x["id"] for x in db.automations.find({"tenant_id": "t1", "scenario": "inactive"}) if x["id"] != inact["id"]]:
        db.automations.update_one({"id": d}, {"$set": {"status": "paused"}})
    pushed.clear()
    db.automations.update_one({"id": inact["id"]}, {"$set": {"last_run_at": None}})
    AU.run_due(now, source="daily")
    check("Bruno (45 days away) is told", [p["cid"] for p in pushed if p["kind"] == "push_wallet"] == ["c2"])
    db.automations.update_one({"id": inact["id"]}, {"$set": {"last_run_at": None}})
    pushed.clear()
    AU.run_due(now + dt.timedelta(days=1), source="daily")
    check("« une fois par absence »: not again while he stays away", not [p for p in pushed if p["kind"] == "push_wallet"])
    db.customers.update_one({"id": "c2"}, {"$set": {"last_visit_date": now + dt.timedelta(days=2)}})
    db.automations.update_one({"id": inact["id"]}, {"$set": {"last_run_at": None}})
    AU.run_due(now + dt.timedelta(days=40), source="daily")
    check("he came back, then stayed away 38 days: told again", "c2" in [p["cid"] for p in pushed if p["kind"] == "push_wallet"])

    print("\n7. Proche de la récompense, Avis Google, Parrainage, Géolocalisation")
    check("carried-over event automations keep sending at once, as before",
          all(not r["schedule"]["window"] for r in http("GET", "/api/owner/automations").json()["rows"]
              if r["scenario"] in ("near_reward", "google_review", "referral", "geo")))
    check("a new one starts with a 09:00–21:00 window", AU.new_doc("t1", "near_reward")["schedule"]["window"] is True)
    nr = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "near_reward"][0]
    pushed.clear()
    AU.fire("near_reward", "t1", db.customers.find_one({"id": "c1"}), {"visits_left": 3, "cycle": "a"})
    check("3 visits left, the automation says 2: nothing", not pushed)
    said = AU.fire("near_reward", "t1", db.customers.find_one({"id": "c1"}), {"visits_left": 2, "cycle": "a"})
    check(f"2 visits left: « {said[0]['title'] if said else ''} »", said and said[0]["title"] == "Plus que 2 !")
    check("…once per card", AU.fire("near_reward", "t1", db.customers.find_one({"id": "c1"}), {"visits_left": 2, "cycle": "a"}) == [])
    check("…and again on the next card", AU.fire("near_reward", "t1", db.customers.find_one({"id": "c1"}),
                                                    {"visits_left": 2, "cycle": "b"}) != [])
    check("Wallet was woken with Google's « near_reward » message", ("c1", {"kind": "near_reward", "header": "Plus que 2 !",
                                                                           "body": said[0]["body"]}) in wallet)

    gr = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "google_review"][0]
    pushed.clear()
    AU.fire("google_review", "t1", db.customers.find_one({"id": "c3"}))
    check("Avis Google after a visit, its button going to the review page",
          pushed and db.automation_log.find_one({"customer_id": "c3", "scenario": "google_review"})["target_url"]
          == f"{AU.public_base()}/api/avis/FT-C3")
    AU.fire("google_review", "t1", db.customers.find_one({"id": "c3"}))
    check("…not again within its 10 days", len(pushed) == 1)
    db.tenants.update_one({"id": "t1"}, {"$set": {"google_reviews_enabled": False}})
    check("no Google link switched on: never asked", AU.fire("google_review", "t1", db.customers.find_one({"id": "c2"})) == [])
    db.tenants.update_one({"id": "t1"}, {"$set": {"google_reviews_enabled": True}})

    for r in [x for x in http("GET", "/api/owner/automations").json()["rows"] if x["scenario"] == "referral"]:
        http("POST", f"/api/owner/automations/{r['id']}/status", json={"status": "active"})
    pushed.clear()
    from features import referrals as RF
    RF._announce("t1", "c1", db.customers.find_one({"id": "c2"}), "first", 50, 25)
    who = {p["cid"]: p["body"] for p in pushed if p["kind"] == "parrainage"}
    check("the parrain hears his friend came, with his points",
          "Bruno" in who.get("c1", "") and "+50" in who.get("c1", ""))
    check("the filleul hears whom he owes it to", "Alice" in who.get("c2", "") and "+25" in who.get("c2", ""))
    check("the parrainage rides on the points banner, not a second one",
          (db.customers.find_one({"id": "c1"})["auto_news"].get("pass") is False)
          and "%@" in db.customers.find_one({"id": "c1"})["points_news"]["text"])

    geo = [r for r in http("GET", "/api/owner/automations").json()["rows"] if r["scenario"] == "geo"][0]
    http("POST", f"/api/owner/automations/{geo['id']}/status", json={"status": "active"})
    s1 = AU.fire("geo", "t1", db.customers.find_one({"id": "c2"}), {"store": "Tours centre"})
    check("Géolocalisation speaks the shop's words", s1 and "Café Lumière" in s1[0]["body"])
    check("…then waits its 7 days", AU.fire("geo", "t1", db.customers.find_one({"id": "c2"}), {"store": "x"}) == [])

    print("\n8. Le bouton d'action, la carte Wallet")
    camp = {"id": "off1", "tenant_id": "t1", "name": "-20%", "status": "sent", "kind": "offre", "sent_at": now,
            "recipient_ids": ["c1"]}
    db.campaigns.insert_one(camp)
    r = http("PUT", f"/api/owner/automations/{gr['id']}", json={
        "scenario": "google_review", "status": "active", "trigger": {"frequency": "every_scan"},
        "message": {"title": "Merci {prénom}", "body": "Votre avis compte.",
                    "button": {"enabled": True, "label": "Voir l'offre", "link_type": "offer", "offer_id": "off1"}},
        "targeting": {"mode": "all"}, "schedule": {"days": "all", "window": False}})
    check("a button may open one of the shop's offers", r.status_code == 200)
    AU.fire("google_review", "t1", db.customers.find_one({"id": "c2"}))
    lg = db.automation_log.find_one({"customer_id": "c2", "scenario": "google_review"})
    check("…the card opens straight on that offer", "offre=off1" in lg["target_url"])
    pj = WP.build_pass_json(WP._card_payload("FT-C2"))
    back = {f["key"]: f for f in (pj.get("storeCard") or pj.get("generic") or {}).get("backFields", [])}
    check("the pass's « Dernier message » carries it, with a changeMessage (Apple's banner)",
          back["news"]["value"].startswith("Merci Bruno") and back["news"].get("changeMessage") == "%@")
    check("…and the button's link sits on the back", back["news_link"]["label"] == "Voir l'offre"
          and back["news_link"]["value"].endswith(lg["id"]))
    pj3 = WP.build_pass_json(WP._card_payload("FT-C4"))
    back3 = {f["key"]: f for f in (pj3.get("storeCard") or pj3.get("generic") or {}).get("backFields", [])}
    check("a client with no message still has the field (so the first one rings)",
          "news" in back3)
    defer["on"] = True
    db.customers.update_one({"id": "c3"}, {"$unset": {"auto_news": ""}})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "c3"}))
    check("held by the shop's daily limits: logged « deferred », the card stays quiet",
          db.automation_log.find_one({"customer_id": "c3", "status": "deferred"})
          and not db.customers.find_one({"id": "c3"}).get("auto_news"))
    defer["on"] = False

    print("\n9. En pause, la page")
    http("POST", f"/api/owner/automations/{gr['id']}/status", json={"status": "paused"})
    pushed.clear()
    AU.fire("google_review", "t1", db.customers.find_one({"id": "c1"}))
    check("a paused automation sends nothing", not pushed)
    p = http("GET", "/api/owner/automations").json()
    check("the figures: active count, clients reached in 30 days, an open rate",
          p["stats"]["active"] == sum(1 for r in p["rows"] if r["status"] == "active") and p["stats"]["reach"] >= 4
          and p["stats"]["open_rate"] >= 0)
    check("each row says how many clients it reached", any(r["reach"] for r in p["rows"]))
    check("the live offers are offered to the button", [o["id"] for o in p["offers"]] == ["off1"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
