"""
Géolocalisation clients — catchment rings, travel-time bands, communes.

What this suite protects: a client lands in exactly one ring and one band,
the bands really move when the transport mode changes, the combined overlap is
counted rather than assumed, and a shop with no address says so instead of
drawing circles around Paris.

    cd api && python3 tests/test_geolocation.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import geolocation as GEO

    db = server.db
    GEO.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    now = dt.datetime.now(dt.timezone.utc)
    TOURS = (47.3941, 0.6848)
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "city": "Tours",
                           "lat": TOURS[0], "lng": TOURS[1]})

    # A degree of latitude is ~111.2 km, so a client placed N degrees north of
    # the shop sits a known distance away — that is how the rings are tested.
    def north(km):
        return TOURS[0] + km / 111.19

    PEOPLE = [
        ("c1", "Marie",   1.0,  "Tours"),            # ring 1, ≤5 min by car
        ("c2", "Paul",    3.0,  "Tours"),            # ring 1, ≤15 min
        ("c3", "Sophie",  4.9,  "La Riche"),         # ring 1, ≤15 min
        ("c4", "Karim",   7.0,  "Saint-Cyr"),        # ring 2, ≤15 min
        ("c5", "Inès",   12.0,  "Joué-lès-Tours"),   # ring 2, ≤25 min
        ("c6", "Hugo",   17.0,  "Rochecorbon"),      # ring 3, ≤35 min
        ("c7", "Léa",    28.0,  "Amboise"),          # ring 3, beyond 35 min by car
        ("c8", "Théo",   80.0,  "Blois"),            # outside every ring
    ]
    db.customers.insert_many([
        {"id": cid, "tenant_id": "t1", "name": name, "city": city,
         "latitude": north(km), "longitude": TOURS[1], "created_at": now - dt.timedelta(days=400)}
        for cid, name, km, city in PEOPLE
    ])
    # Everyone visited inside the window except Théo, who is out of range anyway.
    db.visits.insert_many([
        {"id": f"v{i}", "tenant_id": "t1", "customer_id": cid, "visit_time": now - dt.timedelta(days=2)}
        for i, (cid, *_rest) in enumerate(PEOPLE)
    ])

    def run(mode="car", scope="local", days=20):
        start = (now - dt.timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=23, minute=59, second=59)
        return GEO.compute("t1", start, end, mode, scope)

    # ---- rings -------------------------------------------------------------
    print("\nZones de chalandise — distance rings")
    d = run()
    check("the shop is positioned from its own coordinates", d["shop"]["position_source"] == "gps")
    by = {z["key"]: z for z in d["catchment"]["zones"]}
    check("zone 1 holds the three clients within 5 km", by["z1"]["clients"] == 3)
    check("zone 2 holds the two between 5 and 15 km", by["z2"]["clients"] == 2)
    check("zone 3 holds the two between 15 and 30 km", by["z3"]["clients"] == 2)
    check("the 80 km client is in no ring", d["catchment"]["total"] == 7)
    check("a client is counted once, never twice",
          sum(z["clients"] for z in d["catchment"]["zones"]) == d["catchment"]["total"])
    check("the rings are labelled as the design names them",
          [z["label"] for z in d["catchment"]["zones"]] == ["Zone 1", "Zone 2", "Zone 3"])
    check("shares add up to about 100 %", 99 <= sum(z["pct"] for z in d["catchment"]["zones"]) <= 101)

    # ---- bands -------------------------------------------------------------
    print("\nIsochrones — travel-time bands")
    bands = {b["minutes"]: b for b in d["isochrones"]["bands"]}
    check("the four bands of the design are there", sorted(bands) == [5, 15, 25, 35])
    check("they are flagged as an estimate, not a routed time", d["isochrones"]["estimated"] is True)
    check("at 30 km/h the 5-minute band reaches 2.5 km", bands[5]["radius_km"] == 2.5)
    check("and the 35-minute band reaches 17.5 km", bands[35]["radius_km"] == 17.5)
    check("the 1 km client is in the 5-minute band", bands[5]["clients"] == 1)
    check("a client falls in exactly one band",
          sum(b["clients"] for b in d["isochrones"]["bands"]) == d["isochrones"]["total"])
    check("the 28 km client is beyond 35 min by car", d["isochrones"]["total"] == 6)

    print("\nThe transport mode really changes the reach")
    walk = run(mode="walk")
    wb = {b["minutes"]: b for b in walk["isochrones"]["bands"]}
    check("on foot the speed drops to 4.5 km/h", walk["speed_kmh"] == 4.5)
    check("on foot 35 minutes reaches only ~2.6 km", wb[35]["radius_km"] == 2.62)
    check("so far fewer clients are within reach", walk["isochrones"]["total"] < d["isochrones"]["total"])
    bike = run(mode="bike")
    check("the bike sits between the two",
          walk["isochrones"]["total"] <= bike["isochrones"]["total"] <= d["isochrones"]["total"])
    check("the rings do not move with the mode",
          [z["clients"] for z in walk["catchment"]["zones"]] == [z["clients"] for z in d["catchment"]["zones"]])
    check("but each ring is retimed for the mode",
          walk["catchment"]["zones"][0]["minutes_to"] > d["catchment"]["zones"][0]["minutes_to"])

    # ---- the combined view --------------------------------------------------
    print("\nThe combined view counts the overlap, not an assumption")
    c = d["combined"]
    check("it reports both totals", c["catchment_total"] == 7 and c["isochrone_total"] == 6)
    check("the overlap is the clients in a ring AND a band", c["both"] == 6)
    check("the overlap never exceeds either side",
          c["both"] <= c["catchment_total"] and c["both"] <= c["isochrone_total"])

    # ---- communes -----------------------------------------------------------
    print("\nCommunes")
    z1 = d["communes"]["zones"]["z1"]
    check("zone 1's communes are the ones its clients live in",
          {r["name"] for r in z1} == {"Tours", "La Riche"})
    check("they are ranked by client count", z1[0]["name"] == "Tours" and z1[0]["clients"] == 2)
    check("the combined list spans every zone",
          {r["name"] for r in d["communes"]["combined"]} >= {"Tours", "Saint-Cyr", "Rochecorbon"})
    pins = {p["name"]: p for p in d["commune_pins"]}
    check("each commune gets a point for the map", "Tours" in pins and "lat" in pins["Tours"])
    check("a commune's point sits where its clients are",
          abs(pins["Rochecorbon"]["lat"] - north(17.0)) < 0.01)

    # ---- scope --------------------------------------------------------------
    print("\nZone géographique")
    local = run(scope="local")
    check("'Tours et alentours' drops what is past 35 km", local["out_of_range"] >= 1)
    check("and the 80 km client is gone either way",
          all(p["lat"] < north(40) for p in local["points"]))
    check("the local scope is named after the shop's town (not « Tours » for everyone)", local["local_label"] == "Tours et alentours")
    france = run(scope="france")
    fz = {z["key"]: z for z in france["catchment"]["zones"]}
    # QA F11 (2026-10-08): « Toute la France » dropped every client past 30 km
    check("'Toute la France' keeps everyone: the 80 km client is « Au-delà »",
          france["catchment"]["total"] == 8 and fz["far"]["clients"] == 1 and fz["far"]["far"])
    fb = {b["minutes"]: b for b in france["isochrones"]["bands"]}
    check("…and past the last band too (28 km and 80 km by car)", fb["far"]["clients"] == 2 and france["isochrones"]["total"] == 8)
    check("the local scope has no « Au-delà »", "far" not in {z["key"] for z in local["catchment"]["zones"]})

    # ---- period -------------------------------------------------------------
    print("\nPériode")
    db.visits.delete_many({"customer_id": {"$in": ["c4", "c5", "c6", "c7"]}})
    fewer = run()
    check("only the clients who came in the window are mapped", fewer["catchment"]["total"] == 3)
    db.visits.insert_many([
        {"id": f"w{cid}", "tenant_id": "t1", "customer_id": cid, "visit_time": now - dt.timedelta(days=2)}
        for cid in ("c4", "c5", "c6", "c7")
    ])
    check("and they come back when they do", run()["catchment"]["total"] == 7)
    # QA F11: imported / new clients who have not come yet were never mapped
    db.customers.insert_one({"id": "n1", "tenant_id": "t1", "name": "Nouvelle", "city": "Tours",
                             "latitude": north(2.0), "longitude": TOURS[1], "created_at": now - dt.timedelta(days=1)})
    check("a client who joined in the window is mapped too, before any visit", run()["catchment"]["total"] == 8)
    db.customers.insert_one({"id": "o1", "tenant_id": "t1", "name": "Ancienne", "city": "Tours",
                             "latitude": north(2.5), "longitude": TOURS[1], "created_at": now - dt.timedelta(days=500)})
    check("an old client with no visit in the window is not", run()["catchment"]["total"] == 8)
    start = (now - dt.timedelta(days=20)).replace(hour=0, minute=0, second=0, microsecond=0)
    check("« Tous les clients » maps the whole base",
          GEO.compute("t1", start, now, "car", "local", None, "tous")["catchment"]["total"] == 9)
    db.customers.delete_many({"id": {"$in": ["n1", "o1"]}})

    # ---- position precision --------------------------------------------------
    print("\nHow precisely each client is placed")
    db.customers.insert_one({"id": "c9", "tenant_id": "t1", "name": "Postal only",
                             "postal_code": "37000", "created_at": now})
    db.visits.insert_one({"id": "v9", "tenant_id": "t1", "customer_id": "c9",
                          "visit_time": now - dt.timedelta(days=1)})
    p = run()["precision"]
    check("GPS clients are counted as exact", p["gps"] == 8)
    check("a postal-code client is reported as such", p["postal"] == 1)
    # a code the small built-in table does not know: its real centre (BAN,
    # cached), not its department's (QA F11: La Colle-sur-Loup → the hills)
    db.commune_cache.insert_one({"postal_code": "06480", "lat": 43.6862, "lng": 7.1036})
    db.customers.insert_one({"id": "c10", "tenant_id": "t1", "name": "Colle", "postal_code": "06480", "created_at": now})
    lat, lng, how = GEO._client_position({"id": "c10", "postal_code": "06480"}, GEO._resolve_postals([{"postal_code": "06480"}]))
    check("an unlisted postal code lands on its own centre", how == "postal" and abs(lat - 43.6862) < 0.02 and abs(lng - 7.1036) < 0.02)
    lat, lng, how = GEO._client_position({"id": "c11", "postal_code": "06999"}, {})
    check("one still unknown says « department »", how == "department")
    db.customers.delete_one({"id": "c10"})
    check("the two clients in one postal code do not stack",
          GEO._jitter("a") != GEO._jitter("b"))
    check("but one client always lands in the same place",
          GEO._jitter("a") == GEO._jitter("a"))
    db.customers.delete_one({"id": "c9"})
    db.visits.delete_one({"id": "v9"})

    # ---- a shop with no address ---------------------------------------------
    print("\nA shop we cannot place")
    db.tenants.insert_one({"id": "t2", "name": "Sans adresse"})
    class NoAddr:
        email, role, tenant_id = "b@b.fr", "business_owner", "t2"
    blank = GEO.compute("t2", now - dt.timedelta(days=20), now, "car", "local")
    check("it says so rather than guessing", blank["positioned"] is False)
    check("and names the reason", blank["reason"] == "no_shop_position")
    check("no rings are drawn", blank["catchment"]["zones"] == [] and blank["points"] == [])
    db.tenants.update_one({"id": "t2"}, {"$set": {"address": "3 rue de Lyon, 69001 Lyon"}})
    found = GEO.compute("t2", now - dt.timedelta(days=20), now, "car", "local")
    check("a postal code in the address is enough to place it", found["positioned"] is True)
    check("and it is reported as a postal-level position", found["shop"]["position_source"] == "postal")

    # ---- CSV ----------------------------------------------------------------
    print("\nExport")
    resp = GEO.export_csv(date_from=None, date_to=None, mode="car", scope="france", token_data=TD())
    body = resp.body.decode()
    check("it opens in French Excel", body.startswith("﻿Section;"))
    check("the rings are in it", "Zone de chalandise;Zone 1" in body)
    check("the bands are in it, flagged as estimates", "Isochrone (estimation);5 min" in body)
    check("the communes are in it", "Communes · Zone 1;Tours" in body)
    check("the filename says the period", "geolocalisation-" in resp.headers["Content-Disposition"])

    # ---- guard rails ---------------------------------------------------------
    print("\nGuard rails")
    check("an unknown mode falls back to the car", run(mode="hovercraft")["speed_kmh"] == 30.0)
    check("an unknown scope falls back to local",
          GEO.compute("t1", now - dt.timedelta(days=20), now, "car", "moon")["scope"] == "local")
    check("the map never ships more points than it can draw",
          len(run()["points"]) <= GEO.MAX_MAP_POINTS)
    check("a ring boundary belongs to the outer ring", GEO._zone_of(5.0) == "z2")
    check("and 0 km belongs to the first", GEO._zone_of(0.0) == "z1")
    check("a distance past the last ring belongs to none", GEO._zone_of(31.0) is None)

    # ---- commune names, not postal codes ---------------------------------------
    print("\nA client's town")
    from services import communes
    communes.init(db)
    communes._memory.clear()
    # The network is not part of this suite: the lookup is stubbed, and what is
    # tested is that the page asks for a name and prefers the client's own.
    calls = []
    communes._fetch = lambda postal: (calls.append(postal) or {"37200": "Tours", "37540": "Saint-Cyr-sur-Loire"}.get(postal, ""))
    label = lambda cust: GEO._commune(cust)[0]      # noqa: E731
    check("a known district beats the bare commune — 37200 is Tours Sud",
          label({"postal_code": "37200"}) == "Tours Sud")
    check("and the centre is named as the design names it",
          label({"postal_code": "37000"}) == "Tours (centre)")
    check("the postal code leads, because it is finer than a typed town",
          label({"city": "Tours", "postal_code": "37100"}) == "Tours Nord")
    check("an arrondissement is arithmetic, not a lookup",
          label({"postal_code": "75003"}) == "Paris 3e"
          and label({"postal_code": "75001"}) == "Paris 1er"
          and label({"postal_code": "69007"}) == "Lyon 7e")
    check("a code outside the arrondissement range is not one",
          communes._arrondissement("75099") == "" and communes._arrondissement("13020") == "")
    check("a commune with no district falls back to its name",
          label({"postal_code": "37540"}) == "Saint-Cyr-sur-Loire")
    check("that name is looked up once, then cached",
          label({"postal_code": "37540"}) == "Saint-Cyr-sur-Loire" and calls.count("37540") == 1)
    check("a curated district needs no lookup at all", "37200" not in calls)
    check("an unresolvable code falls back to the code, never to blank",
          label({"postal_code": "99999"}) == "99999")
    check("a client with neither reads as 'Non renseigné'",
          label({}) == "Non renseigné")
    check("an imported city is still used when there is no code",
          label({"city": "La Riche"}) == "La Riche")

    print("\nTwo codes that share a name are told apart")
    names = communes  # noqa: F841 — readability only
    d = GEO._display_names({"Tours": {"37000", "37100"}, "Saint-Cyr-sur-Loire": {"37540"}})
    check("a commune with one code stays plain", d["Saint-Cyr-sur-Loire|37540"] == "Saint-Cyr-sur-Loire")
    check("a commune with two gets the code appended, not an invented district",
          d["Tours|37000"] == "Tours (37000)" and d["Tours|37100"] == "Tours (37100)")
    communes._fetch = lambda postal: (_ for _ in ()).throw(RuntimeError("network down"))
    communes._memory.clear()
    db.commune_cache.delete_many({})      # the cache would otherwise answer first
    check("a lookup that blows up never costs the page its row",
          GEO._commune({"postal_code": "37540"})[0] == "37540")
    check("five digits are required before anything is asked",
          communes._clean("3720") == "" and communes._clean("37200") == "37200")
    check("a code with spaces still resolves", communes._clean(" 37 200 ") == "37200")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
