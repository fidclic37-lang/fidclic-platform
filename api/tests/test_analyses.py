"""
Analyses — eight tabs over one window.

Each tab is asked for against a shop with a known month, and what is checked is
that its panels count what their labels claim. The two figures that could be
read as more than they are — attributed revenue and the retention rate — are
checked against the caveat the page prints beside them, so the words and the
arithmetic cannot drift apart.

    cd api && python3 tests/test_analyses.py
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
    from features import analyses as A

    db = server.db
    A.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    class Fresh:
        email, role, tenant_id = "new@shop.fr", "business_owner", "t9"

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café"})
    db.tenants.insert_one({"id": "t2", "name": "Rival"})

    # id, visits, spend, last visit (d), joined (d), tier, source, city, postal
    # The three Tours codes are the curated ones, so the town names resolve
    # without a network lookup; the two clients with no code fall back to the
    # town their signup left behind.
    CAST = [
        ("c1", 12, 240.0,  1, 400, "vip",    "qr_store",  "Tours",    "37000"),
        ("c2",  6, 120.0,  2, 300, "gold",   "instagram", "Tours",    "37100"),
        ("c3",  3,  45.0,  3,  10, "bronze", "website",   "La Riche", ""),
        ("c4",  1,   8.0, 95, 200, "bronze", "qr_store",  "Tours",    "37000"),
        ("c5",  8, 400.0,  4, 150, "vip",    "",          "Joué",     ""),
    ]
    db.customers.insert_many([
        {"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "visits": v,
         "total_amount_paid": sp, "tier": tier, "acquisition_source": src, "city": city,
         "postal_code": postal,
         "last_visit_date": now - dt.timedelta(days=last),
         "created_at": now - dt.timedelta(days=join)}
        for cid, v, sp, last, join, tier, src, city, postal in CAST
    ])
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival",
                             "visits": 99, "total_amount_paid": 9999.0, "tier": "vip",
                             "last_visit_date": now, "created_at": now})

    # this window: 120 € over 4 visits. One earlier, for the comparison.
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 40.0,
         "visit_time": (now - dt.timedelta(days=1)).replace(hour=12),
         "items": [{"name": "Café latte", "price": 5.0, "quantity": 2}]},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c2", "amount_paid": 30.0,
         "visit_time": (now - dt.timedelta(days=2)).replace(hour=13),
         "items": [{"name": "Café latte", "price": 5.0, "quantity": 1},
                   {"name": "Croissant", "price": 2.0, "quantity": 2}]},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c3", "amount_paid": 20.0,
         "visit_time": (now - dt.timedelta(days=3)).replace(hour=9),
         "items": [{"name": "Croissant", "price": 2.0, "quantity": 1}]},
        {"id": "v4", "tenant_id": "t1", "customer_id": "c5", "amount_paid": 30.0,
         "visit_time": (now - dt.timedelta(days=4)).replace(hour=19)},
        {"id": "v0", "tenant_id": "t1", "customer_id": "c1", "amount_paid": 60.0,
         "visit_time": (now - dt.timedelta(days=40)).replace(hour=12)},
    ])
    db.visits.insert_one({"id": "vx", "tenant_id": "t2", "customer_id": "x1",
                          "amount_paid": 999.0, "visit_time": now})
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "name": "Offre petit-déjeuner",
                             "status": "sent", "sent_at": now - dt.timedelta(days=5),
                             "recipient_ids": ["c1", "c2", "c3", "c4"],
                             "opens": 3, "clicks": 2,
                             "attributed_visit_customer_ids": ["c1", "c2"]})
    db.reviews.insert_many([
        {"tenant_id": "t1", "rating": 10, "text": "Excellent accueil", "topics": ["staff"],
         "created_at": now - dt.timedelta(days=2)},
        {"tenant_id": "t1", "rating": 8, "text": "Bon café", "topics": ["price", "staff"],
         "created_at": now - dt.timedelta(days=4)},
        {"tenant_id": "t1", "rating": 4, "text": "Attente un peu longue", "topics": ["wait_time"],
         "created_at": now - dt.timedelta(days=50)},
    ])

    def tab(key, days=30, who=TD):
        return A.analyses(tab=key, days=days, token_data=who())["data"]

    # ---- the tabs exist ------------------------------------------------------
    print("\nThe eight tabs")
    top = A.analyses(token_data=TD())
    check("eight tabs, in the design's order",
          [t["key"] for t in top["tabs"]]
          == ["vue", "campagnes", "fidelisation", "avis", "moments", "produits",
              "acquisition", "comportement"])
    check("they carry the design's labels",
          [t["label"] for t in top["tabs"]][:4]
          == ["Vue d'ensemble", "Campagnes", "Fidélisation", "Avis clients"])
    check("the default tab is the overview", top["tab"] == "vue")
    check("an unknown tab falls back rather than failing",
          A.analyses(tab="astrology", token_data=TD())["tab"] == "vue")
    check("every tab answers without raising",
          all(isinstance(tab(t["key"]), dict) for t in top["tabs"]))

    # ---- vue d'ensemble --------------------------------------------------------
    print("\nVue d'ensemble")
    v = tab("vue")
    strip = {s["key"]: s for s in v["strip"]}
    check("seven figures across the strip, as the design draws", len(v["strip"]) == 7)
    check("chiffre d'affaires is the money taken in the window", strip["revenue"]["value"] == 120.0)
    check("the rival's 999 € is not in it", strip["revenue"]["value"] != 1119.0)
    check("visites total counts the visits, not the clients", strip["visits"]["value"] == 4)
    check("panier moyen is revenue over visits", strip["basket"]["value"] == 30.0)
    check("clients fidélisés is five visits or more", strip["loyal"]["value"] == 3)
    check("clients inactifs is thirty days without coming", strip["inactive"]["value"] == 1)
    check("and is marked as one where down is good", strip["inactive"]["lower_is_better"] is True)
    check("visites avec campagnes counts the attributed visitors",
          strip["campaign_visits"]["value"] == 2)
    check("the revenue series adds up to the figure",
          round(sum(p["value"] for p in v["revenue_series"]), 2) == 120.0)
    check("one point per day of the window", len(v["revenue_series"]) == 30)
    check("the comparison reaches the window before", strip["revenue"]["delta_pct"] == 100)
    check("the overview carries the products panel", v["products"][0]["name"] == "Café latte")
    check("and the hours grid", v["hours"]["peak"] >= 1)
    check("and the status donut", v["status_mix"]["total"] == 5)

    # ---- campagnes ---------------------------------------------------------------
    print("\nCampagnes")
    c = tab("campagnes")
    row = c["table"][0]
    check("the campaign is listed", row["name"] == "Offre petit-déjeuner")
    check("reach is the recipients", row["reach"] == 4)
    check("clicks come from the row", row["clicks"] == 2)
    check("sales are the attributed visitors", row["sales"] == 2)
    check("conversion is sales over reach", row["conversion"] == 50.0)
    check("attributed revenue is those visitors' spend in the window",
          row["revenue"] == 70.0)         # c1 40 + c2 30
    check("the attribution rule is printed, not assumed",
          f"{A.ATTRIBUTION_DAYS} jours" in c["note"])
    check("the strip totals the table",
          {s["key"]: s["value"] for s in c["strip"]}["reach"] == 4)

    # ---- fidélisation -------------------------------------------------------------
    print("\nFidélisation")
    f = tab("fidelisation")
    fs = {s["key"]: s for s in f["strip"]}
    check("clients fidélisés agrees with the overview", fs["loyal"]["value"] == 3)
    check("clients revenus is two visits or more", fs["returning"]["value"] == 4)
    check("the retention rate is that share of the base", fs["retention"]["value"] == 80)
    check("and the page says it is not a monthly cohort",
          "cohorte" in f["retention_note"])
    check("the tier ladder has four rungs, in order",
          [t["key"] for t in f["tiers"]] == ["bronze", "silver", "gold", "vip"])
    check("and counts the real tiers",
          {t["key"]: t["count"] for t in f["tiers"]}["vip"] == 2)
    check("the shares of the ladder add up", sum(t["pct"] for t in f["tiers"]) == 100)

    # ---- avis ------------------------------------------------------------------------
    print("\nAvis clients")
    a = tab("avis")
    as_ = {s["key"]: s for s in a["strip"]}
    check("the average is shown out of 5, as the design does", as_["avg"]["unit"] == "/5")
    ten = round((10 + 8 + 4) / 3, 1)
    check("and halved from the /10 the data stores", as_["avg"]["value"] == round(ten / 2, 1))
    check("which is not the raw /10 figure", as_["avg"]["value"] != ten)
    check("every review is counted", as_["count"]["value"] == 3)
    check("only those in the window count for the period", as_["window"]["value"] == 2)
    check("the histogram has five rungs", len(a["histogram"]) == 5)
    check("a 10/10 lands on five stars",
          {h["stars"]: h["count"] for h in a["histogram"]}[5] == 1)
    check("a 4/10 lands on two", {h["stars"]: h["count"] for h in a["histogram"]}[2] == 1)
    check("the topics are counted across reviews",
          {t["name"]: t["count"] for t in a["topics"]}["staff"] == 2)
    check("recent reviews are newest first",
          a["recent"][0]["text"].startswith("Excellent"))

    # ---- moments ----------------------------------------------------------------------
    print("\nMoments de visite")
    m = tab("moments")
    check("seven weekday bars", len(m["weekday_bars"]) == 7)
    check("they add up to the visits of the window",
          sum(b["value"] for b in m["weekday_bars"]) == 4)
    check("the busiest day is named", m["best_day"]["visits"] >= 1)
    check("the grid covers the design's hours", m["hours"]["covers"] == "8h – 20h")
    check("a visit at 19h is inside the grid, a visit at 9h too",
          sum(n for row in m["hours"]["grid"] for n in row) == 4)

    # ---- produits ------------------------------------------------------------------------
    print("\nProduits")
    p = tab("produits")
    ps = {s["key"]: s for s in p["strip"]}
    check("the top seller leads", p["products"][0]["name"] == "Café latte")
    check("quantities are summed, not rows counted", p["products"][0]["sales"] == 3)
    check("revenue follows price × quantity", p["products"][0]["revenue"] == 15.0)
    check("references are counted, not units", ps["refs"]["value"] == 2)
    check("units are the quantities", ps["units"]["value"] == 6)
    check("each product carries its share of sales",
          sum(x["share"] for x in p["products"]) in range(99, 102))

    # ---- acquisition ----------------------------------------------------------------------
    print("\nAcquisition")
    acq = tab("acquisition")
    by = {s["name"]: s["count"] for s in acq["sources"]}
    raw_slugs = {"qr_store", "instagram", "facebook", "tiktok", "website"}
    check("no raw slug ever reaches the page", not (set(by) & raw_slugs))
    check("every label is one the page can show",
          set(by) <= set(A.SOURCE_LABELS.values()) | {"Autres", "Non renseigné"})
    # A year's window, and only the clients who joined inside it — derived from
    # the cast so the expectation cannot drift from the fixture.
    year = {s["name"]: s["count"] for s in
            A.analyses(tab="acquisition", days=365, token_data=TD())["data"]["sources"]}
    joined_in_year = [c for c in CAST if c[4] <= 365]
    expect = {}
    for c in joined_in_year:
        expect[A.SOURCE_LABELS.get(c[6], "Autres" if c[6] else "Non renseigné")] = \
            expect.get(A.SOURCE_LABELS.get(c[6], "Autres" if c[6] else "Non renseigné"), 0) + 1
    check("a slug is translated — qr_store reads 'Passage en magasin'",
          year.get("Passage en magasin") == expect.get("Passage en magasin"))
    check("the social networks are grouped under one label",
          year.get("Réseaux sociaux") == expect.get("Réseaux sociaux"))
    check("a client with no source is not silently dropped",
          year.get("Non renseigné") == expect.get("Non renseigné"))
    check("the counts are of the clients who joined inside the window",
          sum(year.values()) == len(joined_in_year))
    check("a client who joined before the window is not counted twice",
          sum(year.values()) < len(CAST))
    places = {x["name"]: x["count"] for x in acq["places"]}
    check("a postal code is read as the town it covers, never shown raw",
          "37000" not in places and places.get("Tours (centre)") == 2)
    check("two codes of one town are two different places",
          places.get("Tours Nord") == 1)
    check("a client with no postal code still lands on their own town",
          places.get("La Riche") == 1 and places.get("Joué") == 1)
    check("every client is placed somewhere", sum(places.values()) == len(CAST))
    check("the page says whose period it is describing", "période" in acq["window_note"])

    # ---- comportement ----------------------------------------------------------------------
    print("\nComportement")
    b = tab("comportement")
    bs = {s["key"]: s for s in b["strip"]}
    check("LTV is spend over clients", bs["ltv"]["value"] == round(813.0 / 5, 2))
    check("total LTV is the whole spend", bs["ltv_total"]["value"] == 813.0)
    check("four frequency buckets", len(b["frequency"]) == 4)
    check("everyone falls in exactly one",
          sum(x["count"] for x in b["frequency"]) == 5)
    check("each bucket explains its own rule",
          all(x["hint"] for x in b["frequency"]))
    check("the basket bands cover the range", len(b["basket_bands"]) == 5)
    check("and only count clients who have actually been in",
          sum(x["count"] for x in b["basket_bands"]) == 5)

    # ---- the window really moves ---------------------------------------------------------------
    print("\nThe window")
    short = A.analyses(tab="vue", days=2, token_data=TD())["data"]
    check("a shorter window has fewer days", len(short["revenue_series"]) == 2)
    check("and less money in it",
          short["strip"][6]["value"] < 120.0 or short["strip"][6]["value"] == 40.0)
    long_ = A.analyses(tab="vue", days=90, token_data=TD())["data"]
    check("a longer one reaches the older visit", long_["strip"][6]["value"] == 180.0)

    # ---- a shop with nothing ------------------------------------------------------------------
    print("\nA shop with nothing yet")
    for key in ("campagnes", "fidelisation", "avis", "moments", "produits",
                "acquisition", "comportement"):
        d = tab(key, who=Fresh)
        check(f"'{key}' says it is empty rather than drawing a plausible chart",
              d.get("empty") is True and bool(d.get("message")))
    vue_empty = tab("vue", who=Fresh)
    check("the overview reads zero across the strip",
          all(s["value"] == 0 for s in vue_empty["strip"]))
    check("its charts still have their days", len(vue_empty["revenue_series"]) == 30)
    check("and no product is invented", vue_empty["products"] == [])

    # ---- a shop with visits but no reviews -----------------------------------------------------
    print("\nA panel with no data of its own")
    db.reviews.delete_many({"tenant_id": "t1"})
    check("no reviews reads as no reviews, not as zero stars",
          tab("avis").get("empty") is True)

    # ---- CSV ---------------------------------------------------------------------------------
    print("\nExport")
    resp = A.export_analyses(days=30, token_data=TD())
    body = resp.body.decode()
    check("it opens in French Excel", body.startswith("﻿Indicateur;"))
    check("the headline figures are in it", "Chiffre d'affaires" in body)
    check("and the day-by-day series", "Nouveaux clients" in body)
    check("the filename says the date", "analyses-" in resp.headers["Content-Disposition"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
