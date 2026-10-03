"""
Tableau de bord — the home page's payload.

Eleven panels read off one month of visits. What this suite protects is that
each one counts what its label says: revenue is money taken, the goal is the
merchant's own number rather than an invented one, and "Impact FidClic" only
claims visits the platform can actually tie to something it sent.

    cd api && python3 tests/test_dashboard_home.py
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from features import dashboard_home as DH, clients_page as CP

    db = server.db
    DH.init(db)
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
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "city": "Tours"})
    db.tenants.insert_one({"id": "t2", "name": "Rival"})

    # Six clients, and visits spread across this window and the one before it.
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Marie", "visits": 8,
         "created_at": now - dt.timedelta(days=200), "last_visit_date": now - dt.timedelta(days=1)},
        {"id": "c2", "tenant_id": "t1", "name": "Paul", "visits": 6,
         "created_at": now - dt.timedelta(days=180), "last_visit_date": now - dt.timedelta(days=2)},
        {"id": "c3", "tenant_id": "t1", "name": "Sophie", "visits": 2,
         "created_at": now - dt.timedelta(days=5), "last_visit_date": now - dt.timedelta(days=3)},
        {"id": "c4", "tenant_id": "t1", "name": "Karim", "visits": 3,
         "created_at": now - dt.timedelta(days=120), "last_visit_date": now - dt.timedelta(days=4)},
        {"id": "c5", "tenant_id": "t1", "name": "Inès", "visits": 1,
         "created_at": now - dt.timedelta(days=300), "last_visit_date": now - dt.timedelta(days=90)},
        {"id": "c6", "tenant_id": "t1", "name": "Hugo", "visits": 0,
         "created_at": now - dt.timedelta(days=400)},
    ])
    db.customers.insert_one({"id": "x1", "tenant_id": "t2", "name": "Rival", "visits": 99,
                             "created_at": now, "last_visit_date": now})

    # this window: 100 € over 5 visits → basket 20 €
    THIS = [("c1", 30.0, 1), ("c2", 20.0, 2), ("c3", 15.0, 3), ("c4", 25.0, 4), ("c1", 10.0, 5)]
    # the one before: 60 € over 2 visits
    PREV = [("c1", 40.0, 40), ("c2", 20.0, 45)]
    db.visits.insert_many([
        {"id": f"v{i}", "tenant_id": "t1", "customer_id": cid, "amount_paid": amt,
         "visit_time": (now - dt.timedelta(days=ago)).replace(hour=12),
         "items": [{"name": "Café latte", "price": 5.0, "qty": 2}] if i < 3 else
                  [{"name": "Croissant", "price": 2.0, "quantity": 1}]}
        for i, (cid, amt, ago) in enumerate(THIS + PREV)
    ])
    db.visits.insert_one({"id": "vx", "tenant_id": "t2", "customer_id": "x1",
                          "amount_paid": 500.0, "visit_time": now})

    d = DH.overview(days=30, token_data=TD())
    cards = {c["key"]: c for c in d["cards"]}

    # ---- the four figures -----------------------------------------------------
    print("\nThe four figures")
    check("four cards: CA, clients, fidélisés, inactifs (« Panier moyen » replaced, user 2026-10-02)",
          [c["key"] for c in d["cards"]] == ["revenue", "clients", "loyal", "inactive"])
    check("chiffre d'affaires is the money actually taken", cards["revenue"]["value"] == 100.0)
    check("the rival's 500 € is not in it", cards["revenue"]["value"] != 600.0)
    check("clients totaux counts the whole base", cards["clients"]["value"] == 6)
    CP.init(db)
    cp = {c["key"]: c["value"] for c in CP.overview(token_data=TD())["cards"]}
    check("fidélisés = the Clients page's « Clients fidèles » (same rules)", cards["loyal"]["value"] == cp["loyal"])
    check("inactifs = the Clients page's « Clients inactifs » (gone 90 days, never came)", cards["inactive"]["value"] == cp["inactive"] == 2)
    check("each card opens its list", cards["loyal"]["to"] == "/dashboard/customers?segment=loyal"
          and cards["inactive"]["to"] == "/dashboard/customers?segment=inactive" and cards["clients"]["to"] == "/dashboard/customers")
    check("the comparison is against the window before",
          cards["revenue"]["delta_pct"] == round((100 - 60) / 60 * 100))
    check("the revenue card carries the FidClic badge of the design",
          cards["revenue"]["badge"] == "FidClic")
    check("a rival shop sees only its own money",
          DH.overview(days=30, token_data=Rival())["cards"][0]["value"] == 500.0)

    # ---- the goal ---------------------------------------------------------------
    print("\nObjectif du mois — the merchant's number, not ours")
    check("unset, the card says so rather than inventing a target",
          d["goal"]["is_set"] is False and d["goal"]["target"] == 0)
    check("and shows no percentage against nothing", d["goal"]["pct"] is None)
    DH.set_goal(DH.Goal(monthly_revenue_goal=250.0), token_data=TD())
    g = DH.overview(days=30, token_data=TD())["goal"]
    check("once set, it is the merchant's own figure", g["target"] == 250.0)
    check("progress is measured on the calendar month", g["reached"] > 0)
    check("what is left is what is left", g["remaining"] == round(250.0 - g["reached"], 2))
    check("the percentage follows", g["pct"] == round(g["reached"] / 250.0 * 100))
    DH.set_goal(DH.Goal(monthly_revenue_goal=1.0), token_data=TD())
    over = DH.overview(days=30, token_data=TD())["goal"]
    check("beating the goal caps the bar at 100, not 4000", over["pct"] == 100)
    check("and nothing is left to do", over["remaining"] == 0)
    check("the goal survives a reload", DH.get_goal(token_data=TD())["monthly_revenue_goal"] == 1.0)
    DH.set_goal(DH.Goal(monthly_revenue_goal=250.0), token_data=TD())

    # ---- impact -------------------------------------------------------------------
    print("\nImpact FidClic claims only what it can tie to a send")
    check("with nothing sent, it claims nothing",
          DH.overview(days=30, token_data=TD())["impact"]["value"] == 0.0)
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "name": "Offre petit-déjeuner",
                             "sent_at": now - dt.timedelta(days=6), "status": "sent",
                             "recipient_ids": ["c1"], "clicks": 4,
                             "attributed_visit_customer_ids": ["c1"]})
    imp = DH.overview(days=30, token_data=TD())["impact"]
    check("a client who was sent something and then came in is counted",
          imp["value"] == 40.0)          # c1's two visits: 30 + 10
    check("clients nobody contacted are not", imp["value"] != 100.0)
    check("the attribution window is published, not hidden", imp["window_days"] == 15)
    db.push_wallet_log.insert_one({"id": "l1", "tenant_id": "t1", "scenario_id": "s1",
                                   "customer_id": "c2", "sent_at": now - dt.timedelta(days=5)})
    check("a Push Wallet send counts the same as a campaign",
          DH.overview(days=30, token_data=TD())["impact"]["value"] == 60.0)

    # ---- the two charts ---------------------------------------------------------------
    print("\nThe two charts")
    d = DH.overview(days=30, token_data=TD())
    check("one point per day of the window", len(d["revenue_series"]) == 30)
    check("the revenue series adds up to the card",
          round(sum(p["value"] for p in d["revenue_series"]), 2) == cards["revenue"]["value"])
    check("new clients has its own series", len(d["new_series"]) == 30)
    check("and counts the ones who joined in the window", d["new_total"] == 1)
    check("a shorter window really is shorter",
          len(DH.overview(days=7, token_data=TD())["revenue_series"]) == 7)

    # ---- campaigns -----------------------------------------------------------------------
    print("\nPerformance des campagnes")
    c = d["campaigns"]
    check("campaigns sent in the window are counted", c["sent"] == 1)
    check("clients touchés is the recipients", c["touched"] == 1)
    check("clicks come from the campaign row", c["clicks"] == 4)
    check("ventes attribuées are the attributed visitors", c["sales"] == 1)
    check("the best campaign is named", c["best"]["name"] == "Offre petit-déjeuner")
    check("with its own conversion rate", c["best"]["conversion"] == 100.0)

    # ---- products -------------------------------------------------------------------------
    print("\nProduits les plus populaires")
    p = d["products"]
    check("the top seller leads", p[0]["name"] == "Café latte")
    check("quantities are summed, not rows counted", p[0]["sales"] == 6)
    check("revenue follows price × quantity", p[0]["revenue"] == 30.0)
    check("at most five are listed", len(p) <= 5)

    # ---- when people come --------------------------------------------------------------------
    print("\nHeures d'affluence")
    h = d["hours"]
    check("seven days", h["weekdays"] == ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"])
    check("six slots, as the design draws", len(h["slots"]) == 6)
    check("the grid matches the axes", len(h["grid"]) == 7 and len(h["grid"][0]) == 6)
    check("the busiest cell is published so the scale can be drawn", h["peak"] >= 1)
    check("every visit of the window is in the grid", 
          sum(n for row in h["grid"] for n in row) == 5)
    check("the hours the grid covers are published", h["covers"] == "8h – 20h")
    check("nothing fell outside them here", h["outside"] == 0)
    db.visits.insert_one({"id": "vnight", "tenant_id": "t1", "customer_id": "c1",
                          "amount_paid": 12.0,
                          "visit_time": (now - dt.timedelta(days=2)).replace(hour=23)})
    night = DH.overview(days=30, token_data=TD())["hours"]
    check("a visit outside the grid's hours is counted, not silently dropped — "
          "a bar's busiest hour must not vanish", night["outside"] == 1)

    # ---- who the clients are --------------------------------------------------------------------
    print("\nStatut des clients")
    mix = {s["key"]: s for s in d["status_mix"]["slices"]}
    check("four slices, in the design's order",
          [s["key"] for s in d["status_mix"]["slices"]]
          == ["loyal", "new", "occasional", "inactive"])
    check("everyone is in exactly one",
          sum(s["count"] for s in d["status_mix"]["slices"]) == 6)
    check("inactif first: gone ninety days or never came", mix["inactive"]["count"] == 2)
    seg = lambda k: CP.list_page(segment=k, per_page=100, token_data=TD())["total"]       # noqa: E731
    check("each slice opens exactly its clients on the Clients page",
          all(mix[k]["count"] == seg(mix[k]["segment"]) for k in mix))
    check("a client who joined this week is nouveau", mix["new"]["count"] == 1)
    check("shares add up to about 100 %",
          99 <= sum(s["pct"] for s in d["status_mix"]["slices"]) <= 101)

    # ---- recommendations ------------------------------------------------------------------------
    print("\nRecommandations — only advice the figures support")
    keys = {r["key"] for r in d["recommendations"]}
    check("at most three are shown", len(d["recommendations"]) <= 3)
    check("with inactive clients, winning them back is offered", "reactivate" in keys)
    check("each one carries somewhere to go",
          all(r["to"].startswith("/dashboard") for r in d["recommendations"]))
    db.customers.update_many({"tenant_id": "t1"},
                             {"$set": {"last_visit_date": now, "visits": 9}})
    healthy = DH.overview(days=30, token_data=TD())["recommendations"]
    check("a shop with nobody to win back is not told to win people back",
          "reactivate" not in {r["key"] for r in healthy})

    # ---- an empty shop -----------------------------------------------------------------------------
    print("\nA shop that opened yesterday")
    class Fresh:
        email, role, tenant_id = "new@shop.fr", "business_owner", "t3"
    empty = DH.overview(days=30, token_data=Fresh())
    check("every figure reads zero", all(c["value"] == 0 for c in empty["cards"]))
    check("no figure invents a percentage", all(c["delta_pct"] is None for c in empty["cards"]))
    check("the charts still have their days", len(empty["revenue_series"]) == 30)
    check("there are no products to show", empty["products"] == [])
    check("and no best campaign to name", empty["campaigns"]["best"] is None)
    check("the status donut is empty rather than a fake slice",
          empty["status_mix"]["total"] == 0)
    check("it is told to set a goal, since it has none",
          "set_goal" in {r["key"] for r in empty["recommendations"]})

    # ---- the header and its period control ---------------------------------------------------
    print("\nL'en-tête et sa période")
    src = open(os.path.join(os.path.dirname(__file__), "..", "..",
                            "src", "pages", "DashboardHomePage.jsx")).read()
    check("the greeting is the page title, not a boxed panel",
          "<header className=" in src and "rounded-2xl border border-[#D7E6FF]" not in src)
    check("only the name is in brand blue",
          'Bonjour <span className="text-[#2F6BFF]">{firstName' in src)
    check("the page names itself above the greeting, as the design does",
          "Tableau de bord\n          </p>" in src)

    check("the period survives a reload", "localStorage.setItem('fidclic:dh_days'" in src)
    check("and travels in the URL, so a shared link shows the same thing",
          "url.searchParams.set('days'" in src)
    check("a period that is not valid never reaches the API",
          "validPeriod(next) ? String(next) : '30'" in src)
    check("every picker on the page reads the same value",
          src.count("RangePicker value={period} onChange={setDays}") == 3)
    menu = open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "components", "PeriodMenu.jsx")).read()
    check("the menu offers « Aujourd'hui » and a period of one's own",
          "label: \"Aujourd'hui\"" in menu and "Personnalisé" in menu)
    check("a typed period is capped at two years, as the API is",
          "MAX_DAYS = 730" in menu and "MAX_MONTHS = 24" in menu)

    print("\nThe period")
    today = DH.overview(days=1, token_data=TD())
    check("« Aujourd'hui » reads from midnight in Paris",
          dt.datetime.fromisoformat(today["from"]).astimezone(ZoneInfo("Europe/Paris")).hour == 0)
    check("and draws the day hour by hour",
          today["revenue_series"][0]["label"] == "0h"
          and len(today["revenue_series"]) == dt.datetime.now(ZoneInfo("Europe/Paris")).hour + 1)
    check("two years can be asked for", DH.overview(days=730, token_data=TD())["days"] == 730)
    check("and none of them can be changed mid-refetch",
          src.count("busy={loading}") == 3)

    # The four the picker offers are the four the API is asked for, and the
    # API answers on that period rather than on a fixed month.
    for n in (7, 30, 90, 365):
        payload = DH.overview(days=n, token_data=TD())
        check(f"{n} days is answered as {n} days",
              payload["days"] == n and len(payload["revenue_series"]) == n)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
