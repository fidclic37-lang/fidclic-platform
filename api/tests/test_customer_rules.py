"""
Règles clients — the rules page and the classification it drives.

What this guards: the seven built-ins exist with the design's figures, a save
is validated (the time line and the frequency ladder cannot cross), deleted
built-ins come back, the older flat fields stay in step, and the Clients page
actually follows whatever the owner saves.

Run:
    cd api && python3 tests/test_customer_rules.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import customer_rules as R
    from features import clients_page as CP

    db = server.db
    R.init(db)
    CP.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    class TD2:
        email, role, tenant_id = "owner@y.fr", "business_owner", "t2"

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return e.detail
        return None

    def put(rules, td=TD):
        return R.put_rules(R.RulesIn(rules=[R.RuleIn(**r) for r in rules]), token_data=td())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café"})
    db.tenants.insert_one({"id": "t2", "name": "Ancien réglage"})

    # ---- the built-ins ---------------------------------------------------------
    print("\nThe seven rules of the design")
    page = R.get_rules(token_data=TD())
    rules = page["rules"]
    check("seven, in the design's order",
          [r["key"] for r in rules] == ["actif", "bientot_perdu", "dormant", "nouveau",
                                        "regulier", "fidele", "vip"])
    check("with the design's names",
          [r["name"] for r in rules][:3] == ["Client actif", "Client bientôt perdu", "Client dormant"])
    figures = {r["key"]: [c["value"] for c in r["conditions"]] for r in rules}
    check("and the design's figures (30 / 31 / 90 days, 1 visit, 3 visits + 2 a month, 4, 8)",
          figures == {"actif": [30], "bientot_perdu": [31], "dormant": [90], "nouveau": [1],
                      "regulier": [3, 2], "fidele": [4], "vip": [8]})
    check("every one switched on", all(r["enabled"] for r in rules))
    check("descriptions fit the 200-character box", all(len(r["description"]) <= 200 for r in rules))
    check("the page knows the shop's name for its breadcrumb", page["shop"] == "Le Corner Café")
    check("the criteria the owner may pick exclude the one reserved to 'bientôt perdu'",
          [c["type"] for c in page["criteria"] if c["builtin_only"]] == ["at_risk_since"])

    print("\nA shop that had set the older status card keeps its figures")
    db.customer_status_config.insert_one({"tenant_id": "t2", "active_within_days": 21,
                                          "dormant_after_days": 120, "about_to_lose_days": 14,
                                          "loyal_visits_per_month": 5, "regular_visits_per_month": 3})
    old = {r["key"]: [c["value"] for c in r["conditions"]] for r in R.load("t2")}
    check("its active window (21 days)", old["actif"] == [21])
    check("its dormant threshold (120 days)", old["dormant"] == [120])
    check("an 'about to lose' inside the active window moves to the day after it",
          old["bientot_perdu"] == [22])
    check("its frequency figures", old["fidele"] == [5] and old["regulier"] == [3, 3])

    # ---- saving ---------------------------------------------------------------
    print("\nSaving")
    edited = [dict(r) for r in rules]
    edited[0] = {**edited[0], "conditions": [{"type": "visited_within", "value": 21}],
                 "description": "Venu dans les trois dernières semaines."}
    edited[5] = {**edited[5], "enabled": False}
    out = put(edited)
    saved = {r["key"]: r for r in out["rules"]}
    check("a figure is saved", saved["actif"]["conditions"][0]["value"] == 21)
    check("a description is saved", saved["actif"]["description"] == "Venu dans les trois dernières semaines.")
    check("a rule can be switched off", saved["fidele"]["enabled"] is False)
    doc = db.customer_status_config.find_one({"tenant_id": "t1"})
    check("the older flat fields follow, for the pages that still read them",
          doc["active_within_days"] == 21 and doc["dormant_after_days"] == 90
          and doc["loyal_visits_per_month"] == 4 and doc["regular_visits_per_month"] == 2)
    check("the order is saved as shown", [r["order"] for r in out["rules"]] == list(range(7)))

    print("\nWhat a save refuses")
    base = [dict(r) for r in out["rules"]]

    def with_(key, conditions):
        return [{**r, "conditions": conditions} if r["key"] == key else r for r in base]

    check("'bientôt perdu' starting inside 'actif'",
          refused(lambda: put(with_("bientot_perdu", [{"type": "at_risk_since", "value": 10}]))))
    check("'dormant' before 'bientôt perdu'",
          refused(lambda: put(with_("dormant", [{"type": "not_visited_since", "value": 25}]))))
    check("'fidèle' asking fewer visits a month than 'régulier'",
          refused(lambda: put(with_("fidele", [{"type": "visits_per_month", "value": 1}]))))
    check("'VIP' asking no more than 'fidèle'",
          refused(lambda: put(with_("vip", [{"type": "visits_per_month", "value": 4}]))))
    check("changing what a built-in measures",
          refused(lambda: put(with_("actif", [{"type": "visits_min", "value": 3}]))))
    check("a figure out of range",
          refused(lambda: put(with_("actif", [{"type": "visited_within", "value": 0}]))))
    check("a nameless rule",
          refused(lambda: put(base + [{"name": " ", "conditions": [{"type": "visits_min", "value": 2}]}])))
    check("a description over 200 characters",
          refused(lambda: put(base + [{"name": "Long", "description": "x" * 201,
                                       "conditions": [{"type": "visits_min", "value": 2}]}])))
    check("more than three conditions",
          refused(lambda: put(base + [{"name": "Trop", "conditions": [{"type": "visits_min", "value": 2}] * 4}])))
    check("an owner rule borrowing the reserved criterion",
          refused(lambda: put(base + [{"name": "Moi", "conditions": [{"type": "at_risk_since", "value": 40}]}])))
    check("an unknown icon",
          refused(lambda: put(base + [{"name": "Moi", "icon": "rocket",
                                       "conditions": [{"type": "visits_min", "value": 2}]}])))
    check("a refused save changes nothing",
          [r["conditions"] for r in R.load("t1")] == [r["conditions"] for r in base])

    # ---- the owner's own rules --------------------------------------------------
    print("\nAjouter une règle")
    mine = {"name": "Gros dépensiers", "icon": "shopping-bag", "tone": "violet",
            "description": "Plus de 200 € dépensés.",
            "conditions": [{"type": "spent_min", "value": 200}, {"type": "visits_min", "value": 2}]}
    out = put(base + [mine])
    added = out["rules"][-1]
    check("it is added at the end", added["name"] == "Gros dépensiers" and added["key"] is None)
    check("with an id of its own", added["id"].startswith("r_"))
    again = put(out["rules"])
    check("and keeps that id across saves", again["rules"][-1]["id"] == added["id"])

    # ---- delete / restore --------------------------------------------------------
    print("\nSupprimer, puis rétablir")
    without = [r for r in again["rules"] if r["key"] != "dormant"]
    out = put(without)
    check("a built-in can be deleted", "dormant" not in [r["key"] for r in out["rules"]])
    check("the page then offers to bring it back",
          [d["key"] for d in out["deleted_builtins"]] == ["dormant"])
    back = R.restore_builtins(token_data=TD())
    keys = [r["key"] for r in back["rules"]]
    check("restoring puts it back at its usual place", keys.index("dormant") == 2)
    check("with its usual figure",
          next(r for r in back["rules"] if r["key"] == "dormant")["conditions"][0]["value"] == 90)
    check("and leaves the owner's own rule alone", back["rules"][-1]["name"] == "Gros dépensiers")
    check("nothing is left to restore", back["deleted_builtins"] == [])
    check("a shop's rules are its own", R.get_rules(token_data=TD2())["rules"][0]["conditions"][0]["value"] == 21
          and R.load("t1")[0]["conditions"][0]["value"] == 21)

    # ---- classification -------------------------------------------------------------
    print("\nWhat a client is shown as")
    rules = R.load("t1")        # actif 21 days, fidèle off, "Gros dépensiers" added

    def kind(**c):
        return R.status_key(R.primary(c, now, rules))

    joined = lambda d: now - dt.timedelta(days=d)
    ago = lambda d: now - dt.timedelta(days=d)
    check("the shop's own window: 20 days ago is actif",
          kind(visits=2, created_at=joined(300), last_visit_date=ago(20)) == "actif")
    check("22 days ago is no longer (21-day window, 'bientôt perdu' starts at 31) — Inactif",
          kind(visits=2, created_at=joined(300), last_visit_date=ago(22)) == "inactif")
    check("bientôt perdu from day 31", kind(visits=2, created_at=joined(300),
                                            last_visit_date=ago(40)) == "bientot_perdu")
    check("dormant from day 90, before anything else",
          kind(visits=90, created_at=joined(100), last_visit_date=ago(95), total_amount_paid=900) == "dormant")
    check("a signed-up client who never came for 100 days is dormant too",
          kind(visits=0, created_at=joined(100)) == "dormant")
    check("the owner's rule comes before the frequency rules",
          kind(visits=30, created_at=joined(30), last_visit_date=ago(1), total_amount_paid=500)
          == again["rules"][-1]["id"])
    check("VIP at 8 visits a month",
          kind(visits=16, created_at=joined(60), last_visit_date=ago(1), total_amount_paid=50) == "vip")
    check("a switched-off rule is never the answer (fidèle is off → régulier)",
          kind(visits=10, created_at=joined(60), last_visit_date=ago(1)) == "regulier")
    check("the first visit reads nouveau",
          kind(visits=1, created_at=joined(2), last_visit_date=ago(2)) == "nouveau")
    check("a visit a month since the first month is monthly, not 30× — one visit yesterday is not VIP",
          R.visits_per_month({"visits": 1, "created_at": joined(1)}, now) == 1.0)

    # ---- the Clients page follows ------------------------------------------------------
    print("\nThe Clients page follows the rules")
    db.customers.insert_many([
        {"id": "a", "tenant_id": "t1", "name": "Ana", "visits": 3, "total_amount_paid": 30,
         "created_at": joined(200), "last_visit_date": ago(25)},
        {"id": "b", "tenant_id": "t1", "name": "Ben", "visits": 12, "total_amount_paid": 60,
         "created_at": joined(60), "last_visit_date": ago(2)},
    ])
    ov = CP.overview(TD())
    cards = {c["key"]: c for c in ov["cards"]}
    check("inactifs uses the 21-day window: Ana (25 days) counts", cards["inactive"]["value"] == 1)
    check("fidèles falls back to the visit count while the rule is off", cards["loyal"]["value"] == 1)
    check("the Statut filter offers the rules that are on, then Inactif and Sans statut",
          [s["key"] for s in ov["statuses"]][-2:] == ["inactif", "aucun"]
          and "fidele" not in [s["key"] for s in ov["statuses"]])
    rows = {r["name"]: r for r in CP.list_page(token_data=TD())["rows"]}
    check("each row reads the rule's own name", rows["Ben"]["status_label"] == "Client régulier")
    check("in the rule's colour", rows["Ben"]["status_tone"] == "violet")
    check("the status filter uses the rule keys",
          CP.list_page(status="inactif", token_data=TD())["total"] == 1)

    switched = [dict(r) for r in R.load("t1")]
    for r in switched:
        if r["key"] == "fidele":
            r["enabled"] = True
    put(switched)
    ov = CP.overview(TD())
    check("switch 'Client fidèle' back on and Ben (6 a month) counts under it",
          {c["key"]: c for c in ov["cards"]}["loyal"]["value"] == 1
          and CP.list_page(status="fidele", token_data=TD())["total"] == 1)

    # ---- who may do what ------------------------------------------------------------------
    print("\nRoles")
    check("a manager may read the rules", "rules" in R.get_rules(token_data=type("M", (), {
        "email": "m@x.fr", "role": "manager", "tenant_id": "t1"})()))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
