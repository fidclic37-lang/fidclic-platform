"""
Géolocalisation automation (user's mockups, 2026-10-11): the zone (the
establishments, the shop's one radius), the lock screen of Apple and Google
Wallet (locations on the pass, switched on and off client by client), the
card opened near a shop (every rule: hours, days, period, holidays, weather,
targeting, the gap per client), the owner's map (rounded detections, consent,
30 days), « Terminée », and the real numbers. Edge cases: a refusal writes
nothing, unknown weather never sends, another shop sees nothing.

Run: cd api && /usr/local/bin/python3 tests/test_geo_automation.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-geo-automation")
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
    from features import geo_automation as GA
    from features import period as P

    db = server.db
    woken = []
    WP.notify_passes = lambda serials, *a, **k: woken.append(sorted(serials)) or {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}
    server.dispatch_to_customer = lambda *a, **k: {"sent": True}
    weather = {"now": {"code": 0, "temp": 18.0}, "calls": 0, "fail": False}

    def fake_weather(lat, lng):
        weather["calls"] += 1
        if weather["fail"]:
            raise OSError("no network")
        return dict(weather["now"])
    GA.fetch_weather = fake_weather

    def set_weather(code, temp):
        weather["now"] = {"code": code, "temp": temp}
        db.geo_weather.delete_many({})

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else H, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    UTC = dt.timezone.utc
    now = dt.datetime.now(UTC)
    paris = P.local(now)
    MAIN = (47.3941, 0.6848)       # Tours
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café Lumière", "plan": "vip", "subscription_status": "active",
         "is_active": True, "geo_enabled": True, "geo_radius_meters": 200,
         "branches": [{"id": "b1", "name": "Café Lumière - Main", "latitude": MAIN[0], "longitude": MAIN[1],
                       "address": "12 rue Nationale", "postal_code": "37000", "city": "Tours"},
                      {"id": "b2", "name": "Café Lumière - Plumereau", "latitude": 47.3955, "longitude": 0.6820,
                       "address": "8 place Plumereau", "postal_code": "37000", "city": "Tours"},
                      {"id": "b3", "name": "Fermé", "latitude": 47.0, "longitude": 0.5, "status": "closed"}]},
        {"id": "t2", "slug": "rival", "name": "Rival", "plan": "vip", "subscription_status": "active",
         "is_active": True, "geo_enabled": True, "lat": 48.85, "lng": 2.35},
    ])
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "s@x.fr", "role": "staff", "tenant_id": "t1"},
                          {"email": "r@x.fr", "role": "business_owner", "tenant_id": "t2"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, STAFF, H2 = tok("o@x.fr", "business_owner"), tok("s@x.fr", "staff"), tok("r@x.fr", "business_owner", "t2")
    db.card_templates.insert_one({"tenant_id": "t1", "reward_threshold_stamps": 10, "reward_description": "Un café offert",
                                  "card_name": "Café Lumière"})

    def person(cid, name, tid="t1", **kw):
        doc = {"id": cid, "tenant_id": tid, "name": name, "barcode_id": f"FT-{cid.upper()}", "points": 0, "visits": 0,
               "consent": {"accepted": True}, "created_at": now - dt.timedelta(days=200),
               "last_visit_date": now - dt.timedelta(days=2), **kw}
        db.customers.insert_one(doc)
        return doc
    person("c1", "Alice Martin", visits=0, gender="F", birth_date="1995-01-01")      # never came
    person("c2", "Bruno Roy", visits=4, gender="M", birth_date="1970-05-05")         # regular
    person("c3", "Chloé Dubois", visits=15, wallet_added_at=now)                     # an old client, Wallet
    person("c4", "Denis Noconsent", visits=2, consent={"accepted": False})
    person("r1", "Rival client", tid="t2")
    db.pass_registrations.insert_many([{"serial": "FT-C3", "tenant_id": "t1", "device_id": "d3", "push_token": "x"},
                                       {"serial": "FT-C2", "tenant_id": "t1", "device_id": "d2", "push_token": "y"}])
    db.push_subscriptions.insert_one({"tenant_id": "t1", "customer_id": "c1", "endpoint": "https://push/1"})

    print("\n1. Jours fériés, météo, plages (the engine's own rules)")
    h26 = GA.holidays(2026)
    check("2026: Pâques lundi 6 avril, Ascension 14 mai, Pentecôte lundi 25 mai",
          {dt.date(2026, 4, 6), dt.date(2026, 5, 14), dt.date(2026, 5, 25)} <= h26)
    check("…and 1er mai, 14 juillet, 25 décembre", {dt.date(2026, 5, 1), dt.date(2026, 7, 14), dt.date(2026, 12, 25)} <= h26)
    check("an ordinary day is not one", not GA.is_holiday(dt.date(2026, 10, 13)))
    check("Pâques 2027 → lundi 29 mars", dt.date(2027, 3, 29) in GA.holidays(2027))
    check("clear sky, 18 °C = Ensoleillé only", GA.classify(0, 18) == ["sun"])
    check("overcast, 5 °C = Nuageux + Froid", GA.classify(3, 5) == ["clouds", "cold"])
    check("rain showers, 26 °C = Pluie + Chaud", GA.classify(80, 26) == ["rain", "hot"])
    check("snow counts as Pluie (précipitations)", "rain" in GA.classify(73, -1))
    check("exactly 10 °C is not Froid, exactly 25 °C is Chaud", "cold" not in GA.classify(1, 10) and "hot" in GA.classify(1, 25))

    def at_paris(d, hh, mm=0):
        return AU._from_paris(d, hh, mm)
    monday = dt.date(2026, 10, 12)
    sl = {"window": True, "slots": [{"from": "11:00", "to": "14:00"}, {"from": "17:00", "to": "21:00"}], "days": "all"}
    check("12:30 is inside 11h–14h", AU.in_window(sl, at_paris(monday, 12, 30)))
    check("15:00 waits for 17:00 the same day", AU.next_window(sl, at_paris(monday, 15)) == at_paris(monday, 17))
    check("22:00 waits for 11:00 the next day", AU.next_window(sl, at_paris(monday, 22)) == at_paris(monday + dt.timedelta(days=1), 11))
    night = {"window": True, "slots": [{"from": "21:00", "to": "08:00"}], "days": "all"}
    check("night slot: 23:30 is inside 21h – 8h", AU.in_window(night, at_paris(monday, 23, 30)))
    check("night slot: 07:00 the next morning is still inside", AU.in_window(night, at_paris(monday, 7)))
    check("night slot: 12:00 is outside", not AU.in_window(night, at_paris(monday, 12)))
    allday = {"window": False, "days": "all"}
    check("toute la journée: 03:00 is inside", AU.in_window(allday, at_paris(monday, 3)))
    check("jours fériés off: 14 juillet is skipped", not AU.in_window({**allday, "holidays": False}, at_paris(dt.date(2026, 7, 14), 12)))
    check("jours fériés on (default): 14 juillet is fine", AU.in_window(allday, at_paris(dt.date(2026, 7, 14), 12)))
    check("weekdays only: Saturday is outside", not AU.in_window({**allday, "days": "specific", "weekdays": [0, 1, 2, 3, 4]},
                                                                 at_paris(dt.date(2026, 10, 17), 12)))
    per = {**allday, "valid_from": "2026-10-15", "valid_to": "2026-10-20"}
    check("période: before its start = outside", not AU.in_window(per, at_paris(monday, 12)))
    check("période: inside = inside", AU.in_window(per, at_paris(dt.date(2026, 10, 16), 12)))
    check("période: its last day still counts", AU.in_window(per, at_paris(dt.date(2026, 10, 20), 23)))
    check("période: the day after = outside", not AU.in_window(per, at_paris(dt.date(2026, 10, 21), 9)))
    check("no slot ticked and no day: never opens (far away)",
          AU.next_window({"window": False, "days": "specific", "weekdays": []}, now) > now + dt.timedelta(days=300))
    check("an old automation (no slots) keeps its single window", AU.slots_of({"window": True, "window_from": "09:00",
                                                                               "window_to": "21:00"}) == [((9, 0), (21, 0))])

    print("\n2. The weather, cached, and never guessed")
    set_weather(0, 18)
    w = GA.weather_now("t1", *MAIN)
    check("the shop's weather now: sunny, 18 °C", w and w["tags"] == ["sun"] and w["temp"] == 18)
    calls = weather["calls"]
    GA.weather_now("t1", *MAIN)
    check("read again within 20 minutes: no second call", weather["calls"] == calls)
    check("later than 20 minutes: asked again", GA.weather_now("t1", *MAIN, at=now + dt.timedelta(minutes=25)) and weather["calls"] == calls + 1)
    db.geo_weather.delete_many({})
    weather["fail"] = True
    check("no network: unknown (None), never raises", GA.weather_now("t1", *MAIN) is None)
    check("unknown weather + « Pluie » asked = not sent", not GA.weather_ok("t1", {"weather": ["rain"]}, {"lat": MAIN[0], "lng": MAIN[1]}, now))
    check("unknown weather + nothing asked = fine", GA.weather_ok("t1", {"weather": []}, None, now))
    weather["fail"] = False
    set_weather(61, 12)
    check("raining: « Pluie » asked = sent", GA.weather_ok("t1", {"weather": ["rain"]}, {"lat": MAIN[0], "lng": MAIN[1]}, now))
    check("raining: « Ensoleillé » or « Chaud » asked = not sent",
          not GA.weather_ok("t1", {"weather": ["sun", "hot"]}, {"lat": MAIN[0], "lng": MAIN[1]}, now))
    set_weather(0, 18)

    print("\n3. The zone: the shop's establishments")
    an = GA.anchors("t1")
    check("the two open establishments, never the closed one", [a["id"] for a in an] == ["b1", "b2"])
    check("each with its address and position", an[0]["address"].startswith("12 rue Nationale") and an[0]["lat"] == MAIN[0])
    check("a one-shop business: its own position, id « main »", GA.anchors("t2")[0]["id"] == "main" and GA.anchors("t2")[0]["lat"] == 48.85)
    page = http("GET", "/api/owner/automations").json()
    check("the page gives step 2 the establishments, the radius and the choices",
          page["geo"]["radius_m"] == 200 and len(page["geo"]["anchors"]) == 2 and page["geo"]["radii"] == [50, 100, 200, 500]
          and [w["key"] for w in page["geo"]["weather"]] == ["sun", "clouds", "rain", "cold", "hot"])
    check("…and what lets it run (enabled, plan, privacy, marketing)", page["geo"]["live"]["ok"] is True)

    print("\n4. Saving a géolocalisation: checks first, nothing written on a refusal")
    old_geo = [r for r in page["rows"] if r["scenario"] == "geo"]
    for r in old_geo:                                  # the one carried over from before
        http("DELETE", f"/api/owner/automations/{r['id']}")
    base = {"scenario": "geo", "name": "Passants midi", "status": "active",
            "trigger": {"cooldown_days": 7, "weather": [], "stores": [], "radius_m": 100},
            "message": {"title": "Offre à deux pas !", "body": "{prénom}, à {distance} : {offre} chez {établissement}.",
                        "button": {"enabled": True, "label": "Voir l'offre", "link_type": "card"}},
            "targeting": {"mode": "filtered", "passants": "all", "filters": {}},
            "schedule": {"days": "all", "window": False, "holidays": True}}
    n0 = db.automations.count_documents({"tenant_id": "t1"})
    radius0 = db.tenants.find_one({"id": "t1"})["geo_radius_meters"]

    def bad(patch, why, where="trigger"):
        body = {**base, where: {**base[where], **patch}} if where else {**base, **patch}
        r = http("POST", "/api/owner/automations", json=body)
        check(f"refused: {why} ({r.json().get('detail', '')[:70]})", r.status_code == 400)
    bad({"weather": ["snow"]}, "an unknown weather")
    bad({"weather": "rain"}, "weather that is not a list")
    bad({"stores": ["nope"]}, "only unknown establishments ticked (2+ establishments)")
    bad({"radius_m": 20}, "a radius under 50 m")
    bad({"radius_m": 5000}, "a radius over 2 km")
    bad({"cooldown_days": 0}, "a gap of 0 day")
    bad({"passants": "vip"}, "an unknown type of passants", "targeting")
    bad({"window": True, "slots": [{"from": "10:00", "to": "10:00"}]}, "a slot that starts and ends together", "schedule")
    bad({"window": True, "slots": [{"from": "25:00", "to": "10:00"}]}, "an impossible hour", "schedule")
    bad({"window": True, "slots": [{"from": f"{h:02d}:00", "to": f"{h:02d}:30"} for h in range(7)]}, "more than 6 slots", "schedule")
    bad({"valid_from": "2026-10-20", "valid_to": "2026-10-10"}, "an end before the start", "schedule")
    bad({"valid_to": (paris.date() - dt.timedelta(days=1)).isoformat()}, "an end already passed, switched on", "schedule")
    bad({"valid_from": "demain"}, "a date that is not one", "schedule")
    check("…none of them was saved, the shop's radius untouched",
          db.automations.count_documents({"tenant_id": "t1"}) == n0 and db.tenants.find_one({"id": "t1"})["geo_radius_meters"] == radius0)
    r = http("POST", "/api/owner/automations", json={**base, "status": "draft",
                                                      "schedule": {**base["schedule"], "valid_to": "2020-01-01"}})
    check("a draft may carry a past end date", r.status_code == 200)
    http("DELETE", f"/api/owner/automations/{r.json()['id']}")
    other = {**base, "scenario": "custom", "trigger": {"type": "after_visit"}, "targeting": {"mode": "all"},
             "schedule": {"window": True, "slots": [{"from": "21:00", "to": "08:00"}]}}
    check("a night slot is a géolocalisation thing: refused elsewhere",
          http("POST", "/api/owner/automations", json=other).status_code == 400)

    woken.clear()
    r = http("POST", "/api/owner/automations", json={**base, "trigger": {**base["trigger"], "stores": ["b1", "b2"]},
                                                      "schedule": {**base["schedule"], "window": True,
                                                                   "slots": [{"from": "17:00", "to": "21:00"},
                                                                             {"from": "11:00", "to": "14:00"},
                                                                             {"from": "11:00", "to": "14:00"}]}})
    check("a valid géolocalisation is created", r.status_code == 200)
    g = r.json()
    doc = db.automations.find_one({"id": g["id"]})
    check("every establishment ticked = all ([]), the ones opened later too", doc["trigger"]["stores"] == [])
    check("the radius went to the shop (one radius, Paramètres › Établissement)",
          db.tenants.find_one({"id": "t1"})["geo_radius_meters"] == 100 and "radius_m" not in doc["trigger"])
    check("slots sorted, the duplicate dropped", doc["schedule"]["slots"] == [{"from": "11:00", "to": "14:00"}, {"from": "17:00", "to": "21:00"}])
    check("targeting kept as « filtered » with its passants", doc["targeting"]["mode"] == "filtered" and doc["targeting"]["passants"] == "all")
    check("the list reads its zone and hours", g["trigger_text"].startswith("Entrée dans la zone") and "11h–14h / 17h–21h" in g["schedule_text"])
    check("a géolocalisation row carries its real results (nothing yet)", g["results"] == {"sent": 0, "clicks": 0, "visits_24h": 0})
    r = http("PUT", f"/api/owner/automations/{g['id']}", json={**base, "trigger": {**base["trigger"], "stores": ["b2", "nope"]}})
    check("one establishment ticked: only it is watched, unknown ids dropped",
          r.status_code == 200 and db.automations.find_one({"id": g["id"]})["trigger"]["stores"] == ["b2"])
    r = http("PUT", f"/api/owner/automations/{g['id']}", json={**base, "trigger": {**base["trigger"], "weather": ["sun", "sun", "hot"]}})
    check("weather ticks kept once each", db.automations.find_one({"id": g["id"]})["trigger"]["weather"] == ["sun", "hot"])
    check("the list says the weather asked", "météo : ensoleillé ou chaud" in r.json()["trigger_text"])

    print("\n5. Targeting: type de passants, filters, clients joignables")

    def pv(**tg):
        return http("POST", "/api/owner/automations/preview", json={"scenario": "geo", "targeting": {"mode": "filtered", **tg}}).json()
    check("tous les passants: the 4 clients", pv(passants="all")["count"] == 4)
    check("nouveaux passants (0 visite): Alice", pv(passants="new")["count"] == 1)
    check("passants réguliers (1 – 10): Bruno and Denis", pv(passants="regular")["count"] == 2)
    check("anciens clients (11 +): Chloé", pv(passants="old")["count"] == 1)
    check("« filtered » applies the filters: femmes = Alice", pv(passants="all", filters={"gender": ["F"]})["count"] == 1)
    check("passants AND filters: réguliers + hommes = Bruno", pv(passants="regular", filters={"gender": ["M"]})["count"] == 1)
    check("…and nobody when they exclude each other", pv(passants="new", filters={"gender": ["M"]})["count"] == 0)
    re_ = pv(passants="all")["reachable"]
    check("joignables = Wallet (Chloé, Bruno's pass) + notifications (Alice) = 3; Denis is not reachable",
          re_ == {"total": 3, "wallet": 2, "push": 1})
    check("another shop's clients are never counted", http("POST", "/api/owner/automations/preview", headers=H2,
                                                           json={"scenario": "geo", "targeting": {"mode": "filtered"}}).json()["count"] == 1)

    print("\n6. The card opened near a shop (proximity ping)")
    db.automations.update_one({"id": g["id"]}, {"$set": {"trigger.stores": [], "trigger.weather": [], "schedule.window": False}})

    def ping(cid, lat=MAIN[0], lng=MAIN[1]):
        return http("POST", "/api/public/proximity-ping", headers={}, json={"customer_id": cid, "latitude": lat, "longitude": lng}).json()
    far = ping("c2", 47.41, 0.70)
    check("2 km away: out of range, nothing kept", far["status"] == "out_of_range" and db.geo_detections.count_documents({}) == 0)
    woken.clear()
    r = ping("c2", MAIN[0] + 0.0003, MAIN[1])
    check("inside 100 m: the message is shown", r["status"] == "sent" and r["title"] == "Offre à deux pas !")
    check("{distance} is the real one, rounded to 10 m", "à 30 m" in r["body"] or "à 40 m" in r["body"])
    check("{prénom} and {établissement} filled", r["body"].startswith("Bruno") and "Café Lumière - Main" in r["body"])
    check("{offre} without a running offer: « notre offre du moment »", "notre offre du moment" in r["body"])
    check("the button goes through the click counter", "/api/auto/c/" in (r.get("button_url") or ""))
    det = db.geo_detections.find_one({"customer_id": "c2"})
    check("the detection is kept, rounded (never the exact spot)", det and det["lat"] != MAIN[0] + 0.0003 and abs(det["lat"] - (MAIN[0] + 0.0003)) < 0.0005)
    check("…with its establishment and distance", det["store_id"] == "b1" and 20 <= det["distance_m"] <= 45)
    check("told on the card: his Wallet pass is woken (the gap starts)", ["FT-C2"] in woken)
    r2 = ping("c2")
    check("again within 7 days: not again (the gap per client)", r2["status"] == "ignored")
    check("…but the detection still counts for the map", db.geo_detections.count_documents({"customer_id": "c2"}) == 2)
    ping("c4")
    check("a client without consent: no detection kept", db.geo_detections.count_documents({"customer_id": "c4"}) == 0)
    db.automation_log.delete_many({})
    h = paris.hour
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": True,
                                                         "schedule.slots": [{"from": f"{(h + 2) % 24:02d}:00", "to": f"{(h + 3) % 24:02d}:00"}]}})
    check("outside its hours: a passer-by does not wait — nothing", ping("c1")["status"] == "ignored"
          and db.automation_queue.count_documents({}) == 0)
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": False, "trigger.weather": ["rain"]}})
    set_weather(0, 18)
    check("« Pluie » asked, sunny now: nothing", ping("c1")["status"] == "ignored")
    set_weather(63, 11)
    check("it rains: sent", ping("c1")["status"] == "sent")
    db.automations.update_one({"id": g["id"]}, {"$set": {"trigger.weather": [], "trigger.stores": ["b2"]}})
    check("near Main, but only Plumereau is watched: nothing", ping("c3")["status"] == "ignored")
    check("near Plumereau: sent, signed Plumereau", "Plumereau" in ping("c3", 47.3955, 0.6820).get("body", ""))
    db.automations.update_one({"id": g["id"]}, {"$set": {"trigger.stores": [], "targeting.passants": "new"}})
    db.automation_log.delete_many({})
    check("passants « nouveaux »: Bruno (4 visites) gets nothing", ping("c2")["status"] == "ignored")
    db.automations.update_one({"id": g["id"]}, {"$set": {"targeting.passants": "all",
                                                         "schedule.valid_to": (paris.date() - dt.timedelta(days=1)).isoformat()}})
    check("its period is over (« Terminée »): nothing", ping("c2")["status"] == "ignored")
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.valid_to": None,
                                                         "schedule.valid_from": (paris.date() + dt.timedelta(days=2)).isoformat()}})
    check("its period starts in two days: nothing yet", ping("c2")["status"] == "ignored")
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.valid_from": None}})
    db.tenants.update_one({"id": "t1"}, {"$set": {"geo_enabled": False}})
    check("the shop switched geolocation off: nothing", ping("c2")["status"] == "ignored")
    db.tenants.update_one({"id": "t1"}, {"$set": {"geo_enabled": True}})
    check("back on: sent", ping("c2")["status"] == "sent")
    check("an unknown client: ignored, no error", ping("ghost")["status"] == "ignored")

    print("\n7. The Wallet lock screen: locations on the pass, client by client")
    db.automation_log.delete_many({})
    st = GA.for_pass(db.customers.find_one({"id": "c3"}))
    check("Chloé (Wallet, targeted, in hours): her pass carries the zone", st and len(st["spots"]) == 2 and st["radius"] == 100)
    check("…with Apple's lock-screen words (our message), « à {distance} » = « à deux pas »",
          st["text"] == "Offre à deux pas ! — Chloé, à deux pas : notre offre du moment chez Café Lumière - Main.")
    check("…and the button's own link (no click counter off-line)", st["button_label"] == "Voir l'offre" and "/card/FT-C3" in st["button_url"])
    db.automation_log.insert_one({"id": "L1", "tenant_id": "t1", "automation_id": g["id"], "customer_id": "c3",
                                  "sent_at": now - dt.timedelta(days=1), "status": "sent"})
    check("told on her card yesterday (gap 7 j): her pass goes quiet", GA.for_pass(db.customers.find_one({"id": "c3"})) is None)
    db.automation_log.delete_many({})
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": True,
                                                         "schedule.slots": [{"from": f"{(h + 2) % 24:02d}:00", "to": f"{(h + 3) % 24:02d}:00"}]}})
    check("outside its hours: no locations", GA.for_pass(db.customers.find_one({"id": "c3"})) is None)
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": False, "trigger.weather": ["hot"]}})
    set_weather(0, 18)
    check("« Chaud » asked at 18 °C: no locations", GA.for_pass(db.customers.find_one({"id": "c3"})) is None)
    db.automations.update_one({"id": g["id"]}, {"$set": {"trigger.weather": [], "targeting.passants": "new"}})
    check("not in the targeting (nouveaux, she came 15 times): no locations", GA.for_pass(db.customers.find_one({"id": "c3"})) is None)
    db.automations.update_one({"id": g["id"]}, {"$set": {"targeting.passants": "all"}})
    from features import privacy_page as PP
    keep = PP.marketing_allowed
    PP.marketing_allowed = lambda tid: False
    check("« Communications marketing » off: no locations", GA.for_pass(db.customers.find_one({"id": "c3"})) is None)
    PP.marketing_allowed = keep

    pj = WP.build_pass_json(WP._card_payload("FT-C3"))
    locs = pj.get("locations") or []
    check("the Apple pass: two locations, our words, the shop's radius",
          len(locs) == 2 and locs[0]["maxDistance"] == 100 and locs[0]["relevantText"].startswith("Offre à deux pas !"))
    back = {f["key"]: f for f in pj["storeCard"]["backFields"]} if "storeCard" in pj else \
        {f["key"]: f for f in (pj.get("generic") or {}).get("backFields", [])}
    check("…the message on the back, quietly (no banner)", "geo_msg" in back and "changeMessage" not in back["geo_msg"])
    check("…and its button as a link", back.get("geo_link", {}).get("label") == "Voir l'offre")
    obj = WP._gw_object(WP._card_payload("FT-C3"))
    check("the Google card: the same places as « Nearby passes » merchantLocations",
          [round(m["latitude"], 4) for m in obj.get("merchantLocations", [])] == [47.3941, 47.3955])
    check("…its button in the links", any(u["description"] == "Voir l'offre" for u in obj["linksModuleData"]["uris"]))
    db.automations.update_one({"id": g["id"]}, {"$set": {"targeting.passants": "new"}})
    pj = WP.build_pass_json(WP._card_payload("FT-C3"))
    check("an active géolocalisation that leaves her out: no locations at all (not the old reminder)", not pj.get("locations"))
    check("…and Google gets none either", "merchantLocations" not in WP._gw_object(WP._card_payload("FT-C3")))
    db.automations.update_one({"id": g["id"]}, {"$set": {"status": "paused"}})
    pj = WP.build_pass_json(WP._card_payload("FT-C3"))
    check("no active géolocalisation: the card designer's own reminder, as before",
          pj.get("locations") and "pensez à scanner" in pj["locations"][0]["relevantText"])
    db.automations.update_one({"id": g["id"]}, {"$set": {"status": "active", "targeting.passants": "all"}})

    print("\n8. Waking the passes only when their locations change")
    db.customers.update_many({}, {"$unset": {"geo_pass_key": ""}})
    woken.clear()
    out = GA.sync_passes(tids=["t1"])
    check("first run: the Wallet holders whose state changed are woken (Chloé, Bruno)", woken == [["FT-C2", "FT-C3"]] and out["changed"] == 2)
    woken.clear()
    GA.sync_passes(tids=["t1"])
    check("nothing changed: nobody woken", woken == [])
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": True,
                                                         "schedule.slots": [{"from": f"{(h + 2) % 24:02d}:00", "to": f"{(h + 3) % 24:02d}:00"}]}})
    GA.sync_passes(tids=["t1"])
    check("the window closes: both woken (locations off)", woken == [["FT-C2", "FT-C3"]]
          and db.customers.find_one({"id": "c3"})["geo_pass_key"] == "off")
    woken.clear()
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.window": False}})
    r = http("PUT", f"/api/owner/automations/{g['id']}", json=base)
    check("saving in the page wakes the passes right away", woken and "FT-C3" in woken[-1])
    check("Alice has no Wallet: never in a pass sync", all("FT-C1" not in w for w in woken))
    check("the daily run calls it (and forgets old detections)", "geo_passes" in str(open(os.path.join(os.path.dirname(__file__), "..", "server.py")).read()))

    print("\n9. The owner's map: real detections only")
    db.geo_detections.insert_one({"tenant_id": "t1", "customer_id": "c1", "store_id": "b1", "lat": 47.39, "lng": 0.68,
                                  "distance_m": 50, "at": now - dt.timedelta(days=10)})
    db.geo_detections.insert_one({"tenant_id": "t1", "customer_id": "c1", "store_id": "b1", "lat": 47.39, "lng": 0.68,
                                  "distance_m": 50, "at": now - dt.timedelta(days=40)})
    db.geo_detections.insert_one({"tenant_id": "t2", "customer_id": "r1", "store_id": "main", "lat": 48.85, "lng": 2.35,
                                  "distance_m": 5, "at": now})
    z = http("GET", "/api/owner/automations/geo/zone").json()
    check("7 days: the recent points with their counts", sum(p["count"] for p in z["points"]) == db.geo_detections.count_documents(
        {"tenant_id": "t1", "at": {"$gte": now - dt.timedelta(days=7)}}))
    check("clients this week and today, distinct", z["clients_week"] >= 2 and z["clients_today"] >= 1 and z["clients_week"] <= 4)
    check("never another shop's detections", all(p["lat"] != 48.85 for p in z["points"]))
    check("the weather now, in words", z["weather_now"] and z["weather_now"]["labels"] == ["Ensoleillé"])
    check("staff can't read it", http("GET", "/api/owner/automations/geo/zone", headers=STAFF).status_code == 403)
    gone = GA.purge(now)
    check("past 30 days, a detection is forgotten", gone == 1 and db.geo_detections.count_documents({"at": {"$lt": now - dt.timedelta(days=30)}}) == 0)

    print("\n10. Real results, « Terminée », and the other automations")
    log = db.automation_log.find_one({"automation_id": g["id"]}) or {}
    db.automation_log.insert_one({"id": "R1", "tenant_id": "t1", "automation_id": g["id"], "customer_id": "c2",
                                  "sent_at": now - dt.timedelta(hours=30), "status": "sent", "clicked_at": now - dt.timedelta(hours=29)})
    db.visits.insert_one({"id": "v1", "tenant_id": "t1", "customer_id": "c2", "visit_time": now - dt.timedelta(hours=20)})
    res = GA.results("t1", g["id"])
    check("results: sent, clicks, visits within 24 h of the message", res["clicks"] >= 1 and res["visits_24h"] >= 1 and res["sent"] >= 1)
    db.automations.update_one({"id": g["id"]}, {"$set": {"schedule.valid_to": (paris.date() - dt.timedelta(days=1)).isoformat()}})
    page = http("GET", "/api/owner/automations").json()
    row = next(r for r in page["rows"] if r["id"] == g["id"])
    check("its period over: the list says « Terminée » (ended)", row["status"] == "ended" and page["counts"]["ended"] == 1)
    check("…not counted as active", page["counts"]["active"] == sum(1 for r in page["rows"] if r["status"] == "active"))
    r = http("POST", f"/api/owner/automations/{g['id']}/status", json={"status": "active"})
    check("switching it on again is refused until the end date moves", r.status_code == 400 and "date de fin" in r.json()["detail"])
    nxt = (paris.date() + dt.timedelta(days=30)).isoformat()
    r = http("PUT", f"/api/owner/automations/{g['id']}", json={**base, "schedule": {**base["schedule"], "valid_to": nxt}})
    check("a new end date: active again", r.status_code == 200 and r.json()["status"] == "active")
    check("…and the list shows its period", "jusqu'au" in r.json()["schedule_text"])

    welcome = next(r for r in db.automations.find({"tenant_id": "t1", "scenario": "welcome"}))
    db.automations.update_one({"id": welcome["id"]}, {"$set": {"status": "active", "schedule.window": False,
                                                               "schedule.valid_to": (paris.date() - dt.timedelta(days=1)).isoformat()}})
    n = len([x for x in AU.fire("welcome", "t1", db.customers.find_one({"id": "c1"}), {"event": "wallet"}) if not x.get("queued")])
    check("Bienvenue « Terminée »: a new client gets nothing", n == 0)
    db.automations.update_one({"id": welcome["id"]}, {"$set": {"schedule.valid_to": None}})
    check("Bienvenue without a period: sent", len(AU.fire("welcome", "t1", db.customers.find_one({"id": "c1"}), {"event": "wallet"})) == 1)
    bday = next(r for r in db.automations.find({"tenant_id": "t1", "scenario": "birthday"}))
    db.customers.update_one({"id": "c2"}, {"$set": {"birthday": paris.strftime("%m-%d")}})
    db.automations.update_one({"id": bday["id"]}, {"$set": {"status": "active", "last_run_at": None,
                                                            "schedule.valid_from": (paris.date() + dt.timedelta(days=3)).isoformat()}})
    s1 = AU.run_due(source="daily")
    check("Anniversaire not yet started (début in 3 days): not sent", not db.automation_log.find_one({"automation_id": bday["id"]}))
    db.automations.update_one({"id": bday["id"]}, {"$set": {"schedule.valid_from": None, "schedule.holidays": False}})
    AU.run_due(source="daily")
    sent_today = bool(db.automation_log.find_one({"automation_id": bday["id"]}))
    check("…started, it goes (unless today is a public holiday and holidays are off)",
          sent_today != GA.is_holiday(paris.date()))
    r = http("PUT", f"/api/owner/automations/{bday['id']}", json={
        "scenario": "birthday", "name": "Anniversaire", "status": "active", "trigger": {"offset_days": 0},
        "message": {"title": "Joyeux anniversaire", "body": "Bonne fête {prénom} !"},
        "schedule": {"days": "all", "hour": "10:00", "valid_from": "2026-11-01", "valid_to": "2026-12-31"}})
    check("Période de validité on any automation: saved and shown", r.status_code == 200
          and "du 01/11/2026 au 31/12/2026" in r.json()["schedule_text"])
    check("another shop can't read this shop's zone points", all(p["lat"] != 47.39 for p in http(
        "GET", "/api/owner/automations/geo/zone", headers=H2).json()["points"]))
    del log, s1


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
