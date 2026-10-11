"""
Avis Google automation (user's updated mockups, 2026-10-11) and the new
targeting filters of every automation: the Google link (one shop = the
Insights link; several établissements = each its own, required), the three
triggers (après la visite + délai, client fidèle at the N-th visit, date
spécifique at its hour), the frequency (une fois / tous les N jours / envoi
intelligent at the client's own hour, 8h–20h), the stop after a click, the
établissement's link and name in the message, and « Type de client » (card
statut), « Nombre de visites », « Âge » min–max. Edge cases first: a refusal
writes nothing.

Run: cd api && /usr/local/bin/python3 tests/test_avis_google.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-avis-google")
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
    from features import automations as AU
    from features import period as P

    db = server.db
    sent = []
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: sent.append(
        {"cid": cust.get("id"), "tid": tid, "title": title, "body": body, "url": url}) or {"sent": True}
    WP.notify_customer = lambda *a, **k: {}
    WP.notify_passes = lambda *a, **k: {}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    today = P.local(now).date()
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Solo", "plan": "vip", "subscription_status": "active", "is_active": True},
        {"id": "t2", "slug": "duo", "name": "Duo", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "b1", "name": "Duo Centre"}, {"id": "b2", "name": "Duo Gare"},
                      {"id": "b3", "name": "Fermé", "status": "closed"}]},
    ])
    db.users.insert_many([{"email": "o1@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o2@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, t: {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": "business_owner", "tenant_id": t})}  # noqa: E731
    H, H2 = tok("o1@x.fr", "t1"), tok("o2@x.fr", "t2")
    for t in ("t1", "t2"):
        db.automation_meta.insert_one({"tenant_id": t, "migrated": True})     # no carried-over rows: a clean page

    def person(cid, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": kw.pop("name", cid.title()), "barcode_id": f"FT-{cid.upper()}",
               "visits": 1, "points": 0, "tier": "bronze", "created_at": now - dt.timedelta(days=100), **kw}
        db.customers.insert_one(doc)
        return doc
    person("ana", name="Ana Lima", visits=1, tier="bronze", birth_date="2000-03-03")
    person("ben", name="Ben Roy", visits=5, tier="silver", birth_date="1980-03-03")
    person("cyd", name="Cyd Vo", visits=12, tier="gold", birth_date="1960-03-03")
    person("dee", name="Dee Vip", visits=30, tier="vip")
    person("eva", tid="t2", name="Eva Duo", visits=1)
    person("fox", tid="t2", name="Fox Duo", visits=3)

    base = {"scenario": "google_review", "name": "Demande d'avis Google", "status": "active",
            "trigger": {"type": "after_visit", "delay_value": 2, "delay_unit": "hours", "frequency": "once"},
            "message": {"title": "Votre avis compte ! ⭐", "body": "Merci {prénom} ! Laissez un avis pour {établissement} : {lien_avis}",
                        "image_url": "/automations/avis-google.png",
                        "button": {"enabled": True, "label": "Laisser un avis", "link_type": "google_review"}},
            "targeting": {"mode": "all"},
            "schedule": {"days": "all", "window": False}}

    print("\n1. The Google link: checks first, nothing written on a refusal")

    def bad(body, why, headers=None):
        r = http("POST", "/api/owner/automations", headers=headers, json=body)
        check(f"refused: {why} ({r.json().get('detail', '')[:75]})", r.status_code == 400)
    n0 = db.automations.count_documents({})
    bad(base, "no Google link at all (one shop)")
    bad({**base, "google_links": {"main": "pas un lien"}}, "a link that is not one")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"}, "name": "x" * 101}, "a name over 100 characters")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"}, "trigger": {"type": "soon"}}, "an unknown trigger")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"},
         "trigger": {"type": "date", "date": (today - dt.timedelta(days=1)).isoformat()}}, "a date already passed")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"},
         "trigger": {"type": "date", "date": (today + dt.timedelta(days=3)).isoformat(), "frequency": "smart"}},
        "« envoi intelligent » on a fixed date")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"},
         "trigger": {"type": "after_visit", "delay_value": 30, "delay_unit": "minutes"}}, "a délai in minutes")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"},
         "trigger": {"type": "loyal", "visits": 0}}, "client fidèle at 0 visit")
    bad({**base, "google_links": {"main": "https://g.page/r/solo/review"},
         "message": {**base["message"], "image_url": "/autre/image.png"}}, "an image that is not ours nor uploaded")
    bad({**base, "google_links": {"b1": "https://g.page/r/centre/review"}}, "Duo: the Gare link missing (2 établissements)", H2)
    check("…nothing saved, no link stored", db.automations.count_documents({}) == n0
          and not db.tenants.find_one({"id": "t1"}).get("google_review_url"))
    r = http("POST", "/api/owner/automations", json={**base, "google_links": {"main": "g.page/r/solo/review"},
                                                      "description": "ignored for Avis"})
    check("one shop: created with its link", r.status_code == 200)
    a1 = r.json()
    t1 = db.tenants.find_one({"id": "t1"})
    check("the link went to the shop (Insights › Avis Google), https added, requests switched on",
          t1["google_review_url"] == "https://g.page/r/solo/review" and t1["google_reviews_enabled"] is True)
    check("Avis Google keeps no description (mockup)", a1["description"] == "")
    check("its default image is accepted", a1["message"]["image_url"] == "/automations/avis-google.png")
    check("the list says « Après la visite · 2 heures après · une seule fois »",
          a1["trigger_text"] == "Après la visite · 2 heures après · une seule fois")
    page = http("GET", "/api/owner/automations").json()
    check("the page shows the shop's link (one field)", page["google"]["links"] == {"main": "https://g.page/r/solo/review"}
          and page["google"]["stores"] == [])
    r = http("POST", "/api/owner/automations", headers=H2, json={**base, "google_links": {
        "b1": "https://g.page/r/centre/review", "b2": "https://g.page/r/gare/review", "b3": "https://x.fr"}})
    check("Duo (2 établissements): created with one link each", r.status_code == 200)
    a2 = r.json()
    br = {b["id"]: b.get("google_review_url") for b in db.tenants.find_one({"id": "t2"})["branches"]}
    check("each établissement keeps its own link; the closed one is not touched",
          br == {"b1": "https://g.page/r/centre/review", "b2": "https://g.page/r/gare/review", "b3": None})
    p2 = http("GET", "/api/owner/automations", headers=H2).json()
    check("Duo's page asks one link per open établissement", [x["id"] for x in p2["google"]["stores"]] == ["b1", "b2"])

    print("\n2. Après la visite: délai, plage 8h–20h, the établissement's own link")
    sent.clear()
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ana"}, {"_id": 0}), {"event": "visit"})
    q = db.automation_queue.find_one({"automation_id": a1["id"], "customer_id": "ana"})
    check("2 h after the visit: waiting, not sent now", not sent and q and abs((q["due_at"].replace(tzinfo=UTC) if q["due_at"].tzinfo is None else q["due_at"]) - (now + dt.timedelta(hours=2))) < dt.timedelta(minutes=2))
    db.automation_queue.update_many({}, {"$set": {"due_at": now - dt.timedelta(minutes=1)}})
    AU.run_due(source="tick")
    check("released when due: sent once", len(sent) == 1 and sent[0]["cid"] == "ana")
    log = db.automation_log.find_one({"customer_id": "ana"})
    check("{prénom}, {établissement} and {lien_avis} filled (one shop: its name, the counted link)",
          "Merci Ana" in log["body"] and "Café Solo" in log["body"] and "/api/avis/FT-ANA" in log["body"])
    check("the button goes to the review page through the counter", log["target_url"].endswith("/api/avis/FT-ANA"))
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ana"}, {"_id": 0}), {"event": "visit"})
    check("« une seule fois »: her next visit asks nothing", db.automation_queue.count_documents({"customer_id": "ana"}) == 0)
    sent.clear()
    db.automations.update_one({"id": a2["id"]}, {"$set": {"trigger.delay_value": 0}})
    AU.fire("google_review", "t2", db.customers.find_one({"id": "fox"}, {"_id": 0}), {"event": "visit", "branch_id": "b2"})
    lg = db.automation_log.find_one({"customer_id": "fox"})
    check("Duo: a visit at the Gare → the Gare's name and link", lg and "Duo Gare" in lg["body"] and lg["target_url"].endswith("?b=b2"))
    rr = http("GET", "/api/avis/FT-FOX?b=b2", headers={}, follow_redirects=False)
    check("the counted link opens the Gare's Google page", rr.status_code == 302 and rr.headers["location"] == "https://g.page/r/gare/review")
    check("…and the click is kept", db.google_review_clicks.find_one({"customer_id": "fox"}))
    db.visits.insert_one({"id": "v-eva", "tenant_id": "t2", "customer_id": "eva", "branch_id": "b1", "visit_time": now})
    rr = http("GET", "/api/avis/FT-EVA", headers={}, follow_redirects=False)
    check("a link without ?b= (old messages): the client's last visit picks the établissement",
          rr.headers.get("location") == "https://g.page/r/centre/review")
    db.tenants.update_one({"id": "t2", "branches.id": "b1"}, {"$set": {"branches.$.google_review_url": None}})
    sent.clear()
    AU.fire("google_review", "t2", db.customers.find_one({"id": "eva"}, {"_id": 0}), {"event": "visit", "branch_id": "b1"})
    check("an établissement without its link: nothing is sent", not sent and not db.automation_log.find_one({"customer_id": "eva"}))
    db.tenants.update_one({"id": "t2", "branches.id": "b1"}, {"$set": {"branches.$.google_review_url": "https://g.page/r/centre/review"}})
    db.automations.update_one({"id": a2["id"]}, {"$set": {"schedule.window": True, "schedule.window_from": "08:00",
                                                          "schedule.window_to": "20:00"}})
    night = AU._from_paris(today, 23, 0)
    db.automation_log.delete_many({"customer_id": "eva"})
    db.google_review_clicks.delete_many({"customer_id": "eva"})        # her click above (the redirect check)
    AU.fire("google_review", "t2", db.customers.find_one({"id": "eva"}, {"_id": 0}), {"event": "visit", "branch_id": "b1"}, at=night)
    q = db.automation_queue.find_one({"customer_id": "eva"})
    check("a visit at 23h with the 8h–20h plage: waits for 8h the next morning",
          q and AU._paris(q["due_at"].replace(tzinfo=UTC) if q["due_at"].tzinfo is None else q["due_at"]).hour == 8)
    db.automation_queue.delete_many({})

    print("\n3. Stop after a click, répétition, envoi intelligent")
    db.automations.update_one({"id": a1["id"]}, {"$set": {"trigger.frequency": "days", "trigger.every_days": 30,
                                                          "trigger.delay_value": 0}})
    db.google_review_clicks.insert_one({"tenant_id": "t1", "customer_id": "ana", "at": now})
    db.automation_log.delete_many({"customer_id": "ana"})
    sent.clear()
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ana"}, {"_id": 0}), {"event": "visit"})
    check("a client who opened the review page is never asked again", not sent)
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ben"}, {"_id": 0}), {"event": "visit"})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ben"}, {"_id": 0}), {"event": "visit"})
    check("tous les 30 jours: the same day, once", sum(1 for x in sent if x["cid"] == "ben") == 1)
    db.automation_log.update_many({"customer_id": "ben"}, {"$set": {"sent_at": now - dt.timedelta(days=31)}})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ben"}, {"_id": 0}), {"event": "visit"})
    check("31 days later: asked again", sum(1 for x in sent if x["cid"] == "ben") == 2)
    db.automations.update_one({"id": a1["id"]}, {"$set": {"trigger.frequency": "every_scan"}})
    db.automation_log.update_many({"customer_id": "ben"}, {"$set": {"sent_at": now - dt.timedelta(hours=25)}})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ben"}, {"_id": 0}), {"event": "visit"})
    check("an old « après chaque visite » reads as at most once a day", sum(1 for x in sent if x["cid"] == "ben") == 3)
    db.automations.update_one({"id": a1["id"]}, {"$set": {"trigger.frequency": "smart", "trigger.delay_value": 2,
                                                          "schedule.window": True, "schedule.window_from": "08:00",
                                                          "schedule.window_to": "20:00"}})
    for i in range(5):                                # Cyd always comes around 17h (Paris)
        db.visits.insert_one({"id": f"cv{i}", "tenant_id": "t1", "customer_id": "cyd",
                              "visit_time": AU._from_paris(today - dt.timedelta(days=i + 1), 17, 10)})
    check("Cyd's usual hour: 17h", AU.usual_hour("t1", db.customers.find_one({"id": "cyd"})) == 17)
    check("a client with few visits: the shop's hour, never before 8h nor after 19h",
          8 <= AU.usual_hour("t1", db.customers.find_one({"id": "dee"})) <= 19)
    morning = AU._from_paris(today, 9, 0)
    sent.clear()
    AU.fire("google_review", "t1", db.customers.find_one({"id": "cyd"}, {"_id": 0}), {"event": "visit"}, at=morning)
    q = db.automation_queue.find_one({"customer_id": "cyd"})
    due = q["due_at"].replace(tzinfo=UTC) if q["due_at"].tzinfo is None else q["due_at"]
    check("envoi intelligent: after the 2 h délai, at HER hour (17h) the same day", not sent and due == AU._from_paris(today, 17, 0))
    late = AU._from_paris(today, 18, 30)
    db.automation_queue.delete_many({})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "cyd"}, {"_id": 0}), {"event": "visit"}, at=late)
    q = db.automation_queue.find_one({"customer_id": "cyd"})
    due = q["due_at"].replace(tzinfo=UTC) if q["due_at"].tzinfo is None else q["due_at"]
    check("…a visit at 18h30: 17h tomorrow", due == AU._from_paris(today + dt.timedelta(days=1), 17, 0))
    db.automation_queue.delete_many({})
    db.automation_log.insert_one({"id": "L-cyd", "tenant_id": "t1", "automation_id": a1["id"], "customer_id": "cyd",
                                  "sent_at": now - dt.timedelta(days=90), "status": "sent"})
    AU.fire("google_review", "t1", db.customers.find_one({"id": "cyd"}, {"_id": 0}), {"event": "visit"})
    check("envoi intelligent asks once: never again", db.automation_queue.count_documents({"customer_id": "cyd"}) == 0)

    print("\n4. Client fidèle and Date spécifique")
    r = http("PUT", f"/api/owner/automations/{a1['id']}", json={**base, "trigger": {"type": "loyal", "visits": 5, "delay_value": 0,
                                                                                    "frequency": "once"}})
    check("client fidèle saved, read « à la 5e visite »", r.status_code == 200 and "à la 5e visite" in r.json()["trigger_text"])
    db.google_review_clicks.delete_many({})
    db.automation_log.delete_many({"tenant_id": "t1"})
    sent.clear()
    for cid in ("ana", "ben", "cyd"):
        AU.fire("google_review", "t1", db.customers.find_one({"id": cid}, {"_id": 0}), {"event": "visit"})
    check("only Ben, at exactly his 5th visit", [x["cid"] for x in sent] == ["ben"])
    on = (today + dt.timedelta(days=2)).isoformat()
    r = http("PUT", f"/api/owner/automations/{a1['id']}", json={**base, "trigger": {"type": "date", "date": on, "frequency": "once"},
                                                                 "schedule": {"days": "all", "hour": "10:00"}})
    check("date spécifique saved at 10:00, read with its date", r.status_code == 200 and r.json()["kind"] == "time"
          and r.json()["schedule_text"].endswith("10:00"))
    db.automation_log.delete_many({"tenant_id": "t1"})
    sent.clear()
    AU.run_due(at=AU._from_paris(today, 11, 0), source="tick")
    check("not on another day", not sent)
    AU.fire("google_review", "t1", db.customers.find_one({"id": "ana"}, {"_id": 0}), {"event": "visit"})
    check("a visit does not trigger a date automation", not sent)
    day = today + dt.timedelta(days=2)
    AU.run_due(at=AU._from_paris(day, 9, 45), source="tick")
    check("its day, 9:45: not yet (10:00)", not sent)
    AU.run_due(at=AU._from_paris(day, 10, 5), source="tick")
    check("its day, 10:05: every targeted client of the shop", sorted(x["cid"] for x in sent) == ["ana", "ben", "cyd", "dee"])
    AU.run_due(at=AU._from_paris(day, 10, 20), source="tick")
    check("the next tick sends nothing again", len(sent) == 4)

    print("\n5. Every automation's filters: Type de client (statut), Nombre de visites, Âge")

    def pv(**f):
        r = http("POST", "/api/owner/automations/preview", json={"scenario": "custom", "targeting": {"mode": "segment", "segment": "all", "filters": f}})
        return r.json()["count"]
    check("Nouveaux = Bronze: Ana", pv(client_type=["new"]) == 1)
    check("Réguliers = Argent: Ben", pv(client_type=["regular"]) == 1)
    check("Fidèles = Or + VIP: Cyd and Dee", pv(client_type=["loyal"]) == 2)
    check("a client with no statut counts as Bronze", (db.customers.update_one({"id": "ana"}, {"$unset": {"tier": ""}}) and pv(client_type=["new"]) == 1))
    check("visits 2 to 12: Ben and Cyd", pv(visits_min=2, visits_max=12) == 2)
    check("at least 12 visits: Cyd and Dee", pv(visits_min=12) == 2)
    check("at most 1 visit: Ana", pv(visits_max=1) == 1)
    check("age 25 – 50: Ana (26) and Ben (46)", pv(age_min=25, age_max=50) == 2)
    check("age up to 30: Ana only", pv(age_max=30) == 1)
    check("age from 60 (no max = 65+): Cyd; Dee has no birth date → out", pv(age_min=60) == 1)
    check("an old « Fréquence de visite » no longer filters", pv(frequency=["loyal"]) == 4)
    check("« Tous mes clients » still ignores every filter",
          http("POST", "/api/owner/automations/preview", json={"scenario": "custom", "targeting": {"mode": "all", "filters": {"visits_min": 99}}}).json()["count"] == 4)
    cbase = {"scenario": "custom", "name": "Test", "status": "active", "trigger": {"type": "after_visit"},
             "message": {"title": "T", "body": "B"}, "targeting": {"mode": "segment", "segment": "all", "filters": {}}}
    for f, why in (({"visits_min": 5, "visits_max": 2}, "visits max below min"), ({"age_min": 50, "age_max": 30}, "age end before start"),
                   ({"age_min": 5}, "an age under 10"), ({"client_type": ["vip"]}, "an unknown type de client"),
                   ({"visits_min": -1}, "negative visits")):
        bad({**cbase, "targeting": {**cbase["targeting"], "filters": f}}, why)
    r = http("POST", "/api/owner/automations", json={**cbase, "description": "Remercier après chaque visite", "name": "N" * 100,
                                                      "targeting": {**cbase["targeting"], "filters": {"client_type": ["loyal"], "visits_min": "3", "age_max": 65}}})
    d = db.automations.find_one({"id": r.json()["id"]})
    check("a custom automation keeps a 100-character name and its description", r.status_code == 200 and len(d["name"]) == 100
          and d["description"] == "Remercier après chaque visite")
    check("…its filters stored as typed (numbers)", d["targeting"]["filters"]["client_type"] == ["loyal"]
          and d["targeting"]["filters"]["visits_min"] == 3 and d["targeting"]["filters"]["age_max"] == 65)
    bad({**cbase, "description": "x" * 501}, "a description over 500 characters")
    r = http("POST", f"/api/owner/automations/{a1['id']}/status", json={"status": "paused"})
    r = http("POST", f"/api/owner/automations/{a1['id']}/status", json={"status": "active"})
    check("switching an Avis Google back on uses the shop's saved link", r.status_code == 200 and r.json()["status"] == "active")
    check("another shop never sees these rows", all(x["id"] != a1["id"] for x in http("GET", "/api/owner/automations", headers=H2).json()["rows"]))


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
