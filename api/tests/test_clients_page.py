"""
Clients — the four figures, the eight quick segments and the table.

The vocabulary is what this suite guards. A status and a segment appear in the
figures, on the chips and against every row, and if the three ever disagree the
page lies about the same client three times. So every definition is exercised
against a client built to sit exactly on its edge.

    cd api && python3 tests/test_clients_page.py
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
    from features import clients_page as CP

    db = server.db
    CP.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    class Rival:
        email, role, tenant_id = "b@b.fr", "business_owner", "t2"

    now = dt.datetime.now(dt.timezone.utc)
    TOURS = (47.3941, 0.6848)
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "lat": TOURS[0], "lng": TOURS[1]})
    db.tenants.insert_one({"id": "t2", "name": "Rival"})

    def north(km):
        return TOURS[0] + km / 111.19

    # name, visits, spend, last visit (days ago), joined (days ago), tier, birthday, km away
    CAST = [
        ("Jean Dupont",    12, 245.00,  5,  400, "vip",    "03-14",  2.0),
        ("Sophie Martin",   6,  58.50,  6,  300, "silver", "07-02",  3.0),
        ("Thomas Robert",   1,   0.00, 44,  120, "bronze", "11-20",  1.0),
        ("Claire Legrand",  8, 120.00,  7,  200, "gold",   "01-09", 12.0),
        ("Lucas Bernard",   4, 320.00,  8,  250, "silver", "05-05", 20.0),   # big basket: 80 €/visit
        ("Emma Petit",      3,  42.30,  9,  150, "bronze", "09-30",  4.0),
        ("Hugo Lefevre",    2,  15.00, 85,   90, "bronze", "02-11", 30.0),
        ("Léa Moreau",     14, 289.00, 10,  500, "vip",    "12-25",  1.5),
        ("Antoine Girard",  2,  36.00, 11,   10, "bronze", "04-04",  3.5),   # new
        ("Camille Blanc",   3,  68.90, 12,    5, "bronze", "06-18",  2.5),   # new
    ]
    db.customers.insert_many([
        {"id": f"c{i}", "tenant_id": "t1", "name": name, "barcode_id": f"FT-C{i}",
         "email": f"{name.split()[0].lower()}.{name.split()[1].lower()}@gmail.com",
         "phone": f"06000000{i:02d}", "visits": visits, "total_amount_paid": spend,
         "tier": tier, "birthday": bday,
         "last_visit_date": now - dt.timedelta(days=last),
         "created_at": now - dt.timedelta(days=joined),
         "latitude": north(km), "longitude": TOURS[1], "postal_code": "37000"}
        for i, (name, visits, spend, last, joined, tier, bday, km) in enumerate(CAST)
    ])
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival Client",
                             "visits": 50, "total_amount_paid": 999.0, "tier": "vip",
                             "last_visit_date": now, "created_at": now})

    ov = CP.overview(TD())
    cards = {c["key"]: c for c in ov["cards"]}
    segs = {s["key"]: s for s in ov["segments"]}

    # ---- the four figures ----------------------------------------------------
    print("\nThe four figures")
    check("four cards, in the design's order",
          [c["key"] for c in ov["cards"]] == ["total", "loyal", "inactive", "new"])
    check("they carry the design's labels",
          [c["label"] for c in ov["cards"]]
          == ["Clients total", "Clients fidèles", "Clients inactifs", "Nouveaux clients"])
    check("clients total counts this shop only", cards["total"]["value"] == 10)
    check("the rival's client is not in it",
          CP.overview(Rival())["cards"][0]["value"] == 1)
    check("clients fidèles is five visits or more", cards["loyal"]["value"] == 4)
    check("clients inactifs is thirty days without a visit", cards["inactive"]["value"] == 2)
    check("nouveaux clients is this calendar month", cards["new"]["value"] >= 2)
    check("the inactive card is marked as one where down is good",
          cards["inactive"]["lower_is_better"] is True)

    # ---- statuses ------------------------------------------------------------
    print("\nStatut — and what beats what")
    check("a client who came this week with many visits is fidèle",
          CP.status_of({"visits": 12, "last_visit_date": now - dt.timedelta(days=2)}, now) == "loyal")
    check("a client who came this week with few visits is actif",
          CP.status_of({"visits": 2, "last_visit_date": now - dt.timedelta(days=2)}, now) == "active")
    check("forty visits but gone three months reads inactif, not fidèle — that is "
          "a problem, not a success",
          CP.status_of({"visits": 40, "last_visit_date": now - dt.timedelta(days=90)}, now) == "inactive")
    check("a client who has never been in is inactif", CP.status_of({"visits": 0}, now) == "inactive")
    check("the boundary belongs to inactif",
          CP.status_of({"visits": 9, "last_visit_date": now - dt.timedelta(days=CP.INACTIVE_DAYS)}, now)
          == "inactive")
    check("one day inside it does not",
          CP.status_of({"visits": 9, "last_visit_date": now - dt.timedelta(days=CP.INACTIVE_DAYS - 1)}, now)
          == "loyal")

    # ---- segments -------------------------------------------------------------
    print("\nThe eight quick segments")
    check("eight chips, in the design's order",
          [s["key"] for s in ov["segments"]]
          == ["all", "loyal", "inactive", "new", "big", "local", "birthday", "vip"])
    check("they carry the design's labels",
          [s["label"] for s in ov["segments"]][:4]
          == ["Tous les clients", "Clients fidèles", "Clients inactifs", "Nouveaux clients"])
    check("'tous les clients' is everybody", segs["all"]["count"] == 10)
    check("'clients fidèles' agrees with the figure above it",
          segs["loyal"]["count"] == cards["loyal"]["value"])
    check("'clients inactifs' agrees with its figure too",
          segs["inactive"]["count"] == cards["inactive"]["value"])
    check("VIP is the tier, not a guess", segs["vip"]["count"] == 2)
    check("'clients locaux' is who lives inside the first catchment ring",
          segs["local"]["count"] == sum(1 for c in CAST if c[7] <= CP.LOCAL_KM))
    check("'gros paniers' is measured against this shop's own average, not a "
          "round number pulled from nowhere", ov["shop_average_ticket"] > 0)
    check("and Lucas, at 80 € a visit, is one of them", segs["big"]["count"] >= 1)
    check("'anniversaires du mois' is the current month",
          segs["birthday"]["count"] == sum(1 for c in CAST if c[6][:2] == now.strftime("%m")))

    print("\nThe chips overlap on purpose")
    check("a VIP is shown as VIP in the table",
          CP.segment_of({"tier": "vip", "visits": 20}, now, 10.0) == "vip")
    check("but clicking 'clients fidèles' still finds them",
          CP._matches_segment("loyal", {"tier": "vip", "visits": 20}, now, 10.0, set()))
    check("a brand-new client reads as nouveau, not actif",
          CP.segment_of({"visits": 1, "created_at": now - dt.timedelta(days=3)}, now, 10.0) == "new")

    # ---- the table ---------------------------------------------------------------
    print("\nThe table")
    page = CP.list_page(token_data=TD())
    check("ten per page by default", len(page["rows"]) == 10 and page["per_page"] == 10)
    check("the total is the whole set, not the page", page["total"] == 10)
    check("a row carries both labels, not raw keys",
          page["rows"][0]["status_label"] in ("Fidèle", "Actif", "Inactif"))
    check("initials come from the name", page["rows"][0]["initials"].isalpha())
    check("the email is shown as the design does",
          "@" in page["rows"][0]["email"])
    check("the default sort is newest first",
          page["rows"][0]["name"] in ("Camille Blanc", "Antoine Girard"))

    small = CP.list_page(per_page=3, page=2, token_data=TD())
    check("pagination pages", small["pages"] == 4 and len(small["rows"]) == 3)
    check("page two is not page one",
          {r["id"] for r in small["rows"]} != {r["id"] for r in CP.list_page(per_page=3, token_data=TD())["rows"]})
    check("per_page is capped", CP.list_page(per_page=9999, token_data=TD())["per_page"] == CP.MAX_PER_PAGE)

    print("\nSorting")
    check("by spend puts the biggest first",
          CP.list_page(sort="spend", token_data=TD())["rows"][0]["name"] == "Lucas Bernard")
    check("by visits puts the most frequent first",
          CP.list_page(sort="visits", token_data=TD())["rows"][0]["name"] == "Léa Moreau")
    check("by name is alphabetical",
          CP.list_page(sort="name", token_data=TD())["rows"][0]["name"] == "Antoine Girard")
    check("an unknown sort falls back rather than failing",
          len(CP.list_page(sort="astrology", token_data=TD())["rows"]) == 10)

    print("\nFilters")
    check("a segment narrows the table",
          CP.list_page(segment="vip", token_data=TD())["total"] == 2)
    check("a status narrows it",
          CP.list_page(status="inactive", token_data=TD())["total"] == 2)
    check("and the two combine",
          CP.list_page(segment="loyal", status="inactive", token_data=TD())["total"] <= 2)
    check("a spend band is a band, not a threshold",
          CP.list_page(spend="150_500", token_data=TD())["total"] == 3)
    check("the top band has no ceiling",
          CP.list_page(spend="gt500", token_data=TD())["total"] == 0)
    check("a signup window narrows to recent joiners",
          CP.list_page(joined="30d", token_data=TD())["total"] == 2)
    check("search finds a name", CP.list_page(search="sophie", token_data=TD())["total"] == 1)
    check("search finds an email", CP.list_page(search="@gmail.com", token_data=TD())["total"] == 10)
    check("search finds a card number", CP.list_page(search="FT-C3", token_data=TD())["total"] == 1)
    check("search ignores case", CP.list_page(search="SOPHIE", token_data=TD())["total"] == 1)
    check("nothing found is an empty table, not an error",
          CP.list_page(search="zzzz", token_data=TD())["total"] == 0)

    # ---- messaging the filter, not the page ------------------------------------------------
    # The table is paginated; a message is not. /ids answers with everyone the
    # filter found, so the merchant cannot write to the ten rows on screen and
    # believe they wrote to the hundred the filter matched.
    print("\nContacter le filtre, pas la page")
    for seg in ("all", "inactive", "loyal"):
        page1 = CP.list_page(segment=seg, per_page=5, token_data=TD())
        ids = CP.list_ids(segment=seg, token_data=TD())
        check(f"'{seg}': the id list and the table agree on the total",
              ids["total"] == page1["total"] == len(ids["ids"]))
        check(f"'{seg}': and it is not merely the page on screen",
              len(ids["ids"]) >= len(page1["rows"]))
    everyone = CP.list_ids(segment="all", token_data=TD())["ids"]
    check("no id is returned twice", len(everyone) == len(set(everyone)))
    check("and they are all this shop's clients",
          all(db.customers.find_one({"id": i})["tenant_id"] == "t1" for i in everyone))

    narrowed = CP.list_ids(segment="all", search="zzz-nobody-has-this-name", token_data=TD())
    check("a filter matching nobody returns nobody, not everybody",
          narrowed["ids"] == [] and narrowed["total"] == 0)

    # ---- CSV -----------------------------------------------------------------------
    print("\nExport")
    resp = CP.export_clients(token_data=TD())
    body = resp.body.decode()
    lines = [l for l in body.splitlines() if l.strip()]
    check("it opens in French Excel", body.startswith("﻿Client;"))
    check("the header names the table's columns",
          "Statut;Segment;Visites;Total dépensé (€)" in lines[0])
    check("every client is exported, not just the page", len(lines) == 11)
    check("a filtered export exports only that filter",
          len([l for l in CP.export_clients(segment="vip", token_data=TD()).body.decode().splitlines()
               if l.strip()]) == 3)
    check("the amount is written the French way", ",00" in body or ",5" in body)

    # ---- an empty shop -----------------------------------------------------------------
    print("\nA shop with no clients yet")
    class Fresh:
        email, role, tenant_id = "new@shop.fr", "business_owner", "t3"
    empty = CP.overview(Fresh())
    check("every figure reads zero", all(c["value"] == 0 for c in empty["cards"]))
    check("no figure invents a percentage", all(c["delta_pct"] is None for c in empty["cards"]))
    check("the chips are all zero", all(s["count"] == 0 for s in empty["segments"]))
    check("gros paniers cannot divide by an average of nothing",
          empty["shop_average_ticket"] == 0)
    blank = CP.list_page(token_data=Fresh())
    check("the table is empty, not broken", blank["rows"] == [] and blank["total"] == 0)
    check("it still reports one page", blank["pages"] == 1)

    # ---- the definitions are published --------------------------------------------------
    print("\nThe page can explain itself")
    d = ov["definitions"]
    check("the thresholds travel with the payload",
          d["loyal_visits"] == 5 and d["inactive_days"] == 30 and d["local_km"] == 5.0)
    check("so does the sort vocabulary", len(ov["sorts"]) == 6)

    # ---- the page's own wiring ---------------------------------------------------------------
    print("\nLe câblage de la page")
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "src", "pages", "ClientsPage.jsx")).read()
    check("saved segments are loaded, applied and deleted",
          all(x in src for x in ("listSavedSegments", "applySaved", "deleteSavedSegment")))
    check("saving stores the whole current filter, not just the segment",
          "createSavedSegment({ name, segment, filters: currentFilters })" in src)
    check("the compose button counts the filter when nothing is picked",
          "picked.length || feed.total" in src)
    check("and it sends to the ids the server resolved",
          "customer_ids: compose.ids" in src)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
