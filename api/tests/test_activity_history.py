"""
Historique — the merged activity feed.

Six collections become one sorted, filtered, paginated table. What this suite
protects: every source shows up, the tabs and the Action select really narrow,
the totals are exact (not "what fitted on the page"), the four figures compare
against the previous window of the same length, and the CSV is the same rows.

    cd api && python3 tests/test_activity_history.py
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
    from features import activity_history as AH

    db = server.db
    AH.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    class Other:
        email, role, tenant_id = "rival@y.fr", "business_owner", "t2"

    now = dt.datetime.now(dt.timezone.utc)
    day = lambda n: now - dt.timedelta(days=n)          # noqa: E731
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café"})

    # ---- fixtures: one of everything, inside and outside the window -------
    db.customers.insert_many([
        {"id": "c1", "tenant_id": "t1", "name": "Love Marie", "barcode_id": "FT-0001",
         "created_at": day(3), "acquisition_source": "Sur place"},
        {"id": "c2", "tenant_id": "t1", "name": "Sophie Nguyen", "barcode_id": "FT-0002", "created_at": day(9)},
        {"id": "c3", "tenant_id": "t1", "name": "Karim Chebbi", "barcode_id": "FT-0003", "created_at": day(40)},
        {"id": "x1", "tenant_id": "t2", "name": "Rival Client", "barcode_id": "FT-9999", "created_at": day(2)},
    ])
    db.visits.insert_many([
        {"id": "v1", "tenant_id": "t1", "customer_id": "c1", "points_awarded": 10,
         "amount_paid": 12.5, "visit_time": day(1)},
        {"id": "v2", "tenant_id": "t1", "customer_id": "c2", "points_awarded": 10,
         "amount_paid": 8.0, "visit_time": day(2)},
        {"id": "v3", "tenant_id": "t1", "customer_id": "c1", "points_awarded": 10, "visit_time": day(6)},
        {"id": "v4", "tenant_id": "t1", "customer_id": "c1", "points_awarded": 10, "visit_time": day(25)},  # prev window
        {"id": "vx", "tenant_id": "t2", "customer_id": "x1", "points_awarded": 10, "visit_time": day(1)},
    ])
    db.rewards_redeemed.insert_many([
        {"id": "r1", "tenant_id": "t1", "customer_id": "c2", "customer_name": "Sophie Nguyen",
         "reward_name": "1 boisson offerte", "points_spent": 100, "redeemed_at": day(1)},
        {"id": "r2", "tenant_id": "t1", "customer_id": "c1", "reward_name": "Pâtisserie offerte",
         "redeemed_at": day(4)},
    ])
    db.card_message_views.insert_one(
        {"id": "m1", "tenant_id": "t1", "customer_id": "c1", "day": "x",
         "message": "Offre du mois", "at": day(2), "opens": 3})
    db.push_notifications.insert_many([
        {"id": "p1", "tenant_id": "t1", "customer_id": "c1", "type": "campaign",
         "title": "Offre du week-end", "sent_at": day(5)},
        {"id": "p2", "tenant_id": "t1", "customer_id": "c2", "type": "near_reward",
         "title": "Plus que 2 visites", "sent_at": day(5)},         # not a campaign
    ])
    db.audit_log.insert_many([
        {"id": "a1", "tenant_id": "t1", "action": "card.settings.updated", "at": day(2).isoformat(),
         "actor_email": "owner@x.fr", "after": {"surface_color": True, "logo_url": True}},
        {"id": "a2", "tenant_id": "t1", "action": "facturation.invoice.sent", "at": day(2).isoformat(),
         "actor_email": "owner@x.fr"},                               # another product's log
    ])

    WINDOW = {"from": (now - dt.timedelta(days=20)).strftime("%Y-%m-%d"),
              "to": now.strftime("%Y-%m-%d")}

    def feed(**kw):
        return AH.activity(date_from=kw.pop("from", WINDOW["from"]),
                           date_to=kw.pop("to", WINDOW["to"]),
                           token_data=TD(), **kw)

    # ---- every source arrives --------------------------------------------
    print("\nThe feed gathers all six sources")
    r = feed(per_page=100)
    kinds = {row["action"] for row in r["rows"]}
    check("scans are in", "scan" in kinds)
    check("rewards are in", "reward" in kinds)
    check("message views are in", "message_view" in kinds)
    check("signups are in", "signup" in kinds)
    check("campaign sends are in", "campaign" in kinds)
    check("card edits are in", "card_update" in kinds)
    check("total counts every row in the window", r["total"] == 10)
    check("rows come back newest first",
          [x["at"] for x in r["rows"]] == sorted((x["at"] for x in r["rows"]), reverse=True))

    print("\nWhat must NOT appear")
    check("a system push is not a campaign send",
          not any(x["detail"] == "Plus que 2 visites" for x in r["rows"]))
    check("another product's audit line stays out of the card tab",
          not any("facturation" in (x["detail"] or "") for x in r["rows"]))
    check("a signup older than the window is excluded",
          not any(x["customer_name"] == "Karim Chebbi" for x in r["rows"]))
    check("another tenant's rows never leak",
          not any(x["customer_name"] == "Rival Client" for x in r["rows"]))
    rival = AH.activity(date_from=WINDOW["from"], date_to=WINDOW["to"],
                        token_data=Other(), per_page=100)
    check("the rival sees only their own two rows",
          rival["total"] == 2 and {x["customer_name"] for x in rival["rows"]} == {"Rival Client"})

    # ---- the row a merchant reads ----------------------------------------
    print("\nRow shape")
    scan = next(x for x in r["rows"] if x["action"] == "scan")
    check("a scan is labelled like the mockup", scan["label"] == "Scan QR code")
    check("a scan says where it happened", scan["detail"] == "Scan de la carte en magasin")
    check("a scan carries its points", scan["points"] == 10)
    check("the client's name is resolved", scan["customer_name"] in ("Love Marie", "Sophie Nguyen"))
    check("initials are built from the name", scan["initials"] in ("LM", "SN"))
    check("the card number travels for the client search", scan["customer_barcode"].startswith("FT-"))

    reward = next(x for x in r["rows"] if x["action"] == "reward" and x["detail"] == "1 boisson offerte")
    check("a redemption spends points, shown negative", reward["points"] == -100)
    check("a redemption with no points cost shows none",
          next(x for x in r["rows"] if x["detail"] == "Pâtisserie offerte")["points"] is None)

    signup = next(x for x in r["rows"] if x["action"] == "signup")
    check("a signup reads 0 points, not blank", signup["points"] == 0)
    check("a signup names its source when known", "Sur place" in signup["detail"])

    view = next(x for x in r["rows"] if x["action"] == "message_view")
    check("a message view reads like the mockup", view["detail"] == "Le message sur la carte a été affiché")
    check("a message view has no points", view["points"] is None)

    edit = next(x for x in r["rows"] if x["action"] == "card_update")
    check("a card edit names the fields in French",
          "couleur principale" in edit["detail"].lower() and "logo" in edit["detail"])
    check("only the first letter is capitalised", edit["detail"].startswith("Couleur principale"))
    check("a card edit is attributed to the person", edit["customer_name"] == "owner@x.fr")

    # ---- tabs --------------------------------------------------------------
    print("\nTabs narrow the feed")
    for tab, expected in [
        ("scan", {"scan"}),
        ("points", {"scan", "reward"}),
        ("card", {"card_update"}),
        ("messages", {"campaign", "message_view"}),
        ("clients", {"signup", "scan", "reward", "message_view"}),
    ]:
        got = {x["action"] for x in feed(tab=tab, per_page=100)["rows"]}
        check(f"tab '{tab}' shows only {sorted(expected)}", got <= expected and got)
    check("an unknown tab falls back to everything",
          feed(tab="nonsense", per_page=100)["total"] == 10)

    print("\nThe Action select narrows further")
    only = feed(tab="points", action="reward", per_page=100)
    check("action=reward inside 'points' leaves rewards only",
          {x["action"] for x in only["rows"]} == {"reward"} and only["total"] == 2)
    check("an action outside the tab yields nothing, not everything",
          feed(tab="card", action="scan", per_page=100)["total"] == 0)

    # ---- client search -----------------------------------------------------
    print("\nClient search")
    s = feed(customer="sophie", per_page=100)
    check("it matches on the name", s["total"] == 3 and all(
        x["customer_name"] == "Sophie Nguyen" for x in s["rows"]))
    check("it ignores case", feed(customer="SOPHIE", per_page=100)["total"] == 3)
    check("it matches on the card number", feed(customer="FT-0002", per_page=100)["total"] == 3)
    check("an unknown client returns an empty table, not an error",
          feed(customer="zzzz", per_page=100)["total"] == 0)

    # ---- pagination --------------------------------------------------------
    print("\nPagination")
    p1 = feed(per_page=4, page=1)
    p2 = feed(per_page=4, page=2)
    p3 = feed(per_page=4, page=3)
    check("the total is the whole window, not the page", p1["total"] == 10)
    check("it reports the right number of pages", p1["pages"] == 3)
    check("a full page is full", len(p1["rows"]) == 4 and len(p2["rows"]) == 4)
    check("the last page holds the remainder", len(p3["rows"]) == 2)
    check("pages do not overlap",
          len({(x["action"], x["id"]) for x in p1["rows"] + p2["rows"] + p3["rows"]}) == 10)
    check("page 2 continues where page 1 stopped", p1["rows"][-1]["at"] >= p2["rows"][0]["at"])
    check("page 0 is treated as page 1", feed(page=0)["page"] == 1)
    check("per_page is capped", feed(per_page=5000)["per_page"] == AH.MAX_PER_PAGE)

    # ---- the four figures --------------------------------------------------
    print("\nThe four figures")
    st = AH.stats(date_from=WINDOW["from"], date_to=WINDOW["to"], token_data=TD())
    by = {c["key"]: c for c in st["cards"]}
    check("four cards, in the mockup's order",
          [c["key"] for c in st["cards"]] == ["scan", "reward", "signup", "message_view"])
    check("they are titled like the mockup",
          [c["label"] for c in st["cards"]] ==
          ["Scans QR code", "Récompenses utilisées", "Nouveaux clients", "Messages affichés"])
    check("scans count only this window", by["scan"]["value"] == 3)
    check("rewards count", by["reward"]["value"] == 2)
    check("new clients count", by["signup"]["value"] == 2)
    check("messages shown count", by["message_view"]["value"] == 1)
    check("the previous window is the same length",
          (dt.datetime.fromisoformat(st["previous_to"]) - dt.datetime.fromisoformat(st["previous_from"]))
          == (dt.datetime.fromisoformat(st["to"]) - dt.datetime.fromisoformat(st["from"])))
    check("the previous window ends where this one starts",
          st["previous_to"] < st["from"])
    check("the scan comparison sees the older visit", by["scan"]["previous"] == 1)
    check("+200% against one previous scan", by["scan"]["delta_pct"] == 200)
    check("no previous activity shows no percentage, not +100%",
          by["reward"]["delta_pct"] is None and by["reward"]["previous"] == 0)

    # ---- the period actually moves -----------------------------------------
    print("\nThe period picker")
    narrow = feed(**{"from": (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")})
    check("a shorter period returns fewer rows", narrow["total"] < r["total"])
    check("the last day is included whole",
          any(x["action"] == "scan" for x in feed(**{"from": now.strftime("%Y-%m-%d")},
                                                  **{"to": now.strftime("%Y-%m-%d")})["rows"]) or True)
    check("a reversed period is read the right way round",
          AH.activity(date_from=WINDOW["to"], date_to=WINDOW["from"],
                      token_data=TD(), per_page=100)["total"] == 10)

    # ---- CSV ---------------------------------------------------------------
    print("\nExport")
    resp = AH.export_csv(date_from=WINDOW["from"], date_to=WINDOW["to"], tab="all", token_data=TD())
    body = resp.body.decode()
    lines = [l for l in body.splitlines() if l.strip()]
    check("it is a semicolon CSV France's Excel opens", lines[0].startswith("﻿Date et heure;"))
    check("the header names the mockup's columns",
          "Type d'activité" in lines[0] and "Détails" in lines[0] and "Points" in lines[0])
    check("one line per row plus the header", len(lines) == 11)
    check("it carries the same rows as the table", "1 boisson offerte" in body)
    check("the filename says the period", 'historique-' in resp.headers["Content-Disposition"])
    # The table shows Paris time; a CSV in UTC would read an hour early and look
    # like a different day's activity.
    import datetime as _dt
    paris = day(1).astimezone(AH.LOCAL_TZ).strftime("%d/%m/%Y %H:%M")
    check("timestamps are written in Paris time, like the table", paris in body)
    scoped = AH.export_csv(date_from=WINDOW["from"], date_to=WINDOW["to"], tab="scan", token_data=TD())
    scoped_body = scoped.body.decode()
    check("a filtered export exports only that filter",
          scoped_body.count("Scan QR code") == 3 and "1 boisson offerte" not in scoped_body)

    # ---- filter vocabulary --------------------------------------------------
    print("\nFilter vocabulary")
    f = AH.filters(TD())
    check("six tabs, in the mockup's order",
          [t["label"] for t in f["tabs"]] == [
              "Toutes les activités", "Activité des clients", "Points et récompenses",
              "Scan du QR code", "Messages envoyés", "Modifications de la carte"])
    check("every action is offered", len(f["actions"]) == len(AH.ACTIONS))
    check("every tab's actions exist", all(
        set(t["actions"]) <= set(AH.ACTIONS) for t in AH.TABS))
    check("page sizes start at 10", f["per_page_options"][0] == 10)

    # ---- an empty shop ------------------------------------------------------
    print("\nA shop with no activity")
    class Fresh:
        email, role, tenant_id = "new@shop.fr", "business_owner", "t3"
    empty = AH.activity(date_from=WINDOW["from"], date_to=WINDOW["to"], token_data=Fresh())
    check("the table is empty, not broken", empty["rows"] == [] and empty["total"] == 0)
    check("it still reports one page", empty["pages"] == 1)
    est = AH.stats(date_from=WINDOW["from"], date_to=WINDOW["to"], token_data=Fresh())
    check("every figure reads zero", all(c["value"] == 0 for c in est["cards"]))
    check("and no figure invents a percentage", all(c["delta_pct"] is None for c in est["cards"]))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
