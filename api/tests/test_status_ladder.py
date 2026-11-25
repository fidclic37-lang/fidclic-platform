"""
Statut ladder (user, 2026-11-25): one name per client, clash-free by
construction.

The bug it ends: an owner added « N'a pas visité depuis 45 jours » and nobody
ever got it — « Client bientôt perdu » (31+) and « Client dormant » (90+) were
asked first, so every client past 45 days already had a name.

Now a client's one Statut is read in this order, on every page:
  1. Absence — the time line. Built-ins and the owner's own steps, each saying
     only « à partir de N jours »; a step ends where the next one starts.
  2. The owner's other rules (several conditions mixed) — as before.
  3. Frequency — the owner's steps « à partir de N visites / mois » sit
     between Régulier, Fidèle and Très actif; then Nouveau, then Actif.
Rules page shows each step's range and how many clients it holds; a change
says how many clients move before (preview) and after (save). The « Statut
des clients » donut (Tableau de bord, Analyses) is these statuses, each slice
opening its clients; Insights' « inactifs » follow the shop's « Client actif ».

Run:
    cd api && python3 tests/test_status_ladder.py
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
    from features import dashboard_home as DH
    from features import analyses as A
    from features import insights_page as I

    db = server.db
    for mod in (R, CP):
        mod.init(db)
    DH._db = A._db = I._db = db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def owner(tid):
        return type("TD", (), {"email": f"o@{tid}", "role": "business_owner", "tenant_id": tid})

    TD = owner("t1")

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return str(e.detail)
        return None

    def body(rules):
        return R.RulesIn(rules=[R.RuleIn(**{k: v for k, v in r.items() if k in R.RuleIn.model_fields})
                                for r in rules])

    def put(rules, td=TD):
        return R.put_rules(body(rules), token_data=td())

    def step(name, days, enabled=True):
        return {"name": name, "icon": "clock", "tone": "amber", "enabled": enabled,
                "conditions": [{"type": "not_visited_since", "value": days}]}

    def freq(name, per_month):
        return {"name": name, "icon": "star", "tone": "violet",
                "conditions": [{"type": "visits_per_month", "value": per_month}]}

    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d: now - dt.timedelta(days=d)          # noqa: E731
    for tid in ("t1", "t2"):
        db.tenants.insert_one({"id": tid, "name": f"Shop {tid}", "sector": "cafe"})

    base = R.load("t1")

    def kind(rules, **c):
        return R.status_key(R.primary(c, now, rules))

    def by_name(rules, name):
        return next(r for r in rules if r["name"] == name)

    # ---- 1. absence: the owner's step finally gets its clients ------------------------------
    print("\n1. An owner step « à partir de 45 jours » between Bientôt perdu and Dormant")
    out = put(base + [step("À relancer", 45)])
    rules = R.load("t1")
    relance = by_name(rules, "À relancer")["id"]
    check("50 days away, 12 visits → À relancer (was Bientôt perdu for ever)",
          kind(rules, visits=12, created_at=ago(400), last_visit_date=ago(50)) == relance)
    check("44 days away → still Bientôt perdu",
          kind(rules, visits=12, created_at=ago(400), last_visit_date=ago(44)) == "bientot_perdu")
    check("45 days away → À relancer (its first day)",
          kind(rules, visits=12, created_at=ago(400), last_visit_date=ago(45.2)) == relance)
    check("95 days away → Dormant", kind(rules, visits=3, created_at=ago(400), last_visit_date=ago(95)) == "dormant")
    check("10 visits but 100 days away → Dormant, never Régulier",
          kind(rules, visits=10, created_at=ago(200), last_visit_date=ago(100)) == "dormant")
    check("never came, signed up 50 days ago → Nouveau (a step before Dormant needs a visit, like Bientôt perdu)",
          kind(rules, visits=0, created_at=ago(50)) == "nouveau")
    check("never came, signed up 100 days ago → Dormant", kind(rules, visits=0, created_at=ago(100)) == "dormant")
    check("a client in the shop this week is not absent (Actif window)",
          kind(rules, visits=2, created_at=ago(300), last_visit_date=ago(3)) == "actif")

    print("\n   A step after Dormant, and a step switched off")
    put(R.load("t1") + [step("Perdu", 180)])
    rules = R.load("t1")
    perdu = by_name(rules, "Perdu")["id"]
    check("200 days away → Perdu", kind(rules, visits=4, created_at=ago(400), last_visit_date=ago(200)) == perdu)
    check("never came for 200 days → Perdu (after Dormant, no visit needed)",
          kind(rules, visits=0, created_at=ago(200)) == perdu)
    check("120 days away → Dormant still", kind(rules, visits=4, created_at=ago(400), last_visit_date=ago(120)) == "dormant")
    off = [dict(r, enabled=False) if r["id"] == relance else r for r in R.load("t1")]
    put(off)
    rules = R.load("t1")
    check("À relancer switched off → 50 days reads Bientôt perdu again",
          kind(rules, visits=12, created_at=ago(400), last_visit_date=ago(50)) == "bientot_perdu")
    put([dict(r, enabled=True) if r["id"] == relance else r for r in R.load("t1")])
    no_dormant = [dict(r, enabled=False) if r.get("key") == "dormant" else r for r in R.load("t1")]
    check("Dormant switched off → 120 days falls on the highest step below it (À relancer)",
          kind(no_dormant, visits=4, created_at=ago(400), last_visit_date=ago(120)) == by_name(no_dormant, "À relancer")["id"])

    # ---- 3. frequency: an owner step between Fidèle (4) and Très actif (8) ------------------
    print("\n3. A frequency step « à partir de 6 visites / mois »")
    put(R.load("t1") + [freq("Habitué", 6)])
    rules = R.load("t1")
    hab = by_name(rules, "Habitué")["id"]
    check("7 a month → Habitué", kind(rules, visits=14, created_at=ago(60), last_visit_date=ago(1)) == hab)
    check("9 a month → Très actif", kind(rules, visits=18, created_at=ago(60), last_visit_date=ago(1)) == "vip")
    check("5 a month → Fidèle", kind(rules, visits=10, created_at=ago(60), last_visit_date=ago(1)) == "fidele")
    check("one visit yesterday → Nouveau", kind(rules, visits=1, created_at=ago(1), last_visit_date=ago(1)) == "nouveau")

    # ---- 2. the owner's mixed rules sit between the two ladders, as before --------------------
    print("\n2. A mixed rule (several conditions) — between absence and frequency")
    put(R.load("t1") + [{"name": "Gros dépensiers", "icon": "shopping-bag", "tone": "amber",
                         "conditions": [{"type": "spent_min", "value": 300}, {"type": "visits_min", "value": 5}]}])
    rules = R.load("t1")
    gros = by_name(rules, "Gros dépensiers")["id"]
    check("a present big spender at 7 a month → Gros dépensiers (before frequency)",
          kind(rules, visits=14, created_at=ago(60), last_visit_date=ago(1), total_amount_paid=400) == gros)
    check("the same big spender 50 days away → À relancer (absence first)",
          kind(rules, visits=14, created_at=ago(400), last_visit_date=ago(50), total_amount_paid=400) == relance)

    # ---- validation: a step can never hide another --------------------------------------------
    print("\nA step that would cross another is refused, with its reason")
    cur = R.load("t1")
    msg = refused(lambda: put(cur + [step("Trop tôt", 30)]))
    check("starting inside « Client actif » (30 days)", msg and "Client actif" in msg and "Trop tôt" in msg)
    msg = refused(lambda: put(cur + [step("Doublon", 31)]))
    check("starting the same day as Bientôt perdu", msg and "31" in msg and "Doublon" in msg)
    msg = refused(lambda: put(cur + [step("Doublon", 90)]))
    check("starting the same day as Dormant", msg and "Client dormant" in msg)
    msg = refused(lambda: put(cur + [step("Encore 45", 45)]))
    check("two steps on the same day", msg and "À relancer" in msg and "Encore 45" in msg)
    msg = refused(lambda: put(cur + [freq("Comme fidèle", 4)]))
    check("a frequency step equal to Fidèle (4)", msg and "Client fidèle" in msg)
    msg = refused(lambda: put(cur + [freq("Comme régulier", 2)]))
    check("a frequency step equal to Régulier (2)", msg and "Client régulier" in msg)
    check("nothing refused was saved", len(R.load("t1")) == len(cur))

    # ---- the rules page: reading order, ranges, counts ----------------------------------------
    print("\nThe rules page reads the ladders")
    db.customers.insert_many([
        {"id": "p1", "tenant_id": "t1", "name": "Ana", "visits": 12, "total_amount_paid": 60,
         "created_at": ago(400), "last_visit_date": ago(50)},                    # À relancer
        {"id": "p2", "tenant_id": "t1", "name": "Ben", "visits": 12, "total_amount_paid": 60,
         "created_at": ago(400), "last_visit_date": ago(40)},                    # Bientôt perdu
        {"id": "p3", "tenant_id": "t1", "name": "Cleo", "visits": 10, "total_amount_paid": 50,
         "created_at": ago(200), "last_visit_date": ago(100)},                   # Dormant
        {"id": "p4", "tenant_id": "t1", "name": "Dan", "visits": 14, "total_amount_paid": 70,
         "created_at": ago(60), "last_visit_date": ago(1)},                      # Habitué
        {"id": "p5", "tenant_id": "t1", "name": "Eve", "visits": 1, "total_amount_paid": 8,
         "created_at": ago(1), "last_visit_date": ago(1)},                       # Nouveau
        {"id": "p6", "tenant_id": "t1", "name": "Fay", "visits": 2, "total_amount_paid": 20,
         "created_at": ago(300), "last_visit_date": ago(3)},                     # Actif
        {"id": "p7", "tenant_id": "t1", "name": "Gone", "visits": 9, "total_amount_paid": 90,
         "created_at": ago(300), "last_visit_date": ago(50), "deleted_at": ago(2)},   # deleted: nowhere
        {"id": "q1", "tenant_id": "t2", "name": "Other shop", "visits": 12,
         "created_at": ago(400), "last_visit_date": ago(50)},
    ])
    page = R.get_rules(token_data=TD())
    names = [r["name"] for r in page["rules"]]
    check("reading order: the time line, then frequency, then the owner's mixed rules",
          names == ["Client actif", "Client bientôt perdu", "À relancer", "Client dormant", "Perdu",
                    "Nouveau client", "Client régulier", "Client fidèle", "Habitué", "Client très actif",
                    "Gros dépensiers"])
    row = {r["name"]: r for r in page["rules"]}
    check("each rule says its group",
          [row[n]["group"] for n in ("Client actif", "À relancer", "Habitué", "Gros dépensiers")]
          == ["absence", "absence", "frequency", "custom"])
    rg = lambda n: row[n]["range"]                       # noqa: E731
    check("Client actif 0 – 30 days", rg("Client actif") == {"from": 0, "to": 30})
    check("Bientôt perdu now ends where À relancer starts: 31 – 44", rg("Client bientôt perdu") == {"from": 31, "to": 44})
    check("À relancer 45 – 89", rg("À relancer") == {"from": 45, "to": 89})
    check("Dormant 90 – 179", rg("Client dormant") == {"from": 90, "to": 179})
    check("Perdu 180 and over", rg("Perdu") == {"from": 180, "to": None})
    check("frequency steps say where they start",
          [rg(n)["from"] for n in ("Client régulier", "Client fidèle", "Habitué", "Client très actif")] == [2, 4, 6, 8])
    check("Nouveau says its visit ceiling", rg("Nouveau client") == {"max": 1})
    check("a mixed rule has no range", rg("Gros dépensiers") is None)
    cnt = {n: row[n]["count"] for n in row}
    check("each rule counts its clients (one each here)",
          [cnt[n] for n in ("À relancer", "Client bientôt perdu", "Client dormant", "Habitué",
                            "Nouveau client", "Client actif")] == [1, 1, 1, 1, 1, 1])
    check("every live client of this shop is counted once — the deleted one and the other shop's are not",
          sum(cnt.values()) + sum(page["fallback_counts"].values()) == 6)

    print("\n   A switched-off step has no range, the others close over it")
    put([dict(r, enabled=False) if r["id"] == relance else r for r in R.load("t1")])
    row = {r["name"]: r for r in R.get_rules(token_data=TD())["rules"]}
    check("À relancer off: no range", row["À relancer"]["range"] is None)
    check("Bientôt perdu runs to Dormant again: 31 – 89", row["Client bientôt perdu"]["range"] == {"from": 31, "to": 89})
    put([dict(r, enabled=True) if r["id"] == relance else r for r in R.load("t1")])

    # ---- before / after a change: how many clients move ---------------------------------------
    print("\nBefore saving, the owner sees who moves; after saving, how many moved")
    cur = R.load("t1")
    moved = [dict(r, conditions=[{"type": "not_visited_since", "value": 38}]) if r["id"] == relance else r for r in cur]
    pv = R.preview_rules(body(moved), token_data=TD())
    check("preview: Ben (40 days) moves from Bientôt perdu to À relancer",
          pv["changed"] == 1 and pv["moves"][0]["from_label"] == "Client bientôt perdu"
          and pv["moves"][0]["to_label"] == "À relancer" and pv["moves"][0]["count"] == 1)
    check("a preview saves nothing", by_name(R.load("t1"), "À relancer")["conditions"][0]["value"] == 45)
    check("a crossing preview is refused like a save",
          refused(lambda: R.preview_rules(body(cur + [step("Doublon", 90)]), token_data=TD())) is not None)
    new_step = R.preview_rules(body(cur + [step("Très loin", 48)]), token_data=TD())
    check("preview of a new step names it though it has no id yet (Ana, 50 days, moves into it)",
          [(m["from_label"], m["to_label"]) for m in new_step["moves"]] == [("À relancer", "Très loin")]
          and new_step["changed"] == 1)
    saved = put(moved)
    check("the save answers how many clients changed", saved["changed"] == 1)
    check("another shop's preview reads its own clients only",
          R.preview_rules(body(R.load("t2") + [step("À relancer", 45)]), token_data=owner("t2")())["changed"] == 1)

    # ---- the donut: one slice per status, each opens its clients ------------------------------
    print("\n« Statut des clients » is the Statut column, slice by slice")
    put(cur)                                   # À relancer back at 45
    d = DH.overview(days=30, token_data=TD())
    mix = d["status_mix"]
    keys = [s["key"] for s in mix["slices"]]
    check("slices are the statuses, in reading order, only those with clients",
          keys == ["actif", "bientot_perdu", relance, "dormant", "nouveau", hab])
    check("everyone in exactly one", mix["total"] == 6 and sum(s["count"] for s in mix["slices"]) == 6)
    check("each slice opens the Clients page on its Statut",
          all(s["to"] == f"/dashboard/customers?statut={s['key']}" for s in mix["slices"]))
    check("and that filter holds exactly its clients",
          all(CP.list_page(status=s["key"], per_page=100, token_data=TD())["total"] == s["count"] for s in mix["slices"]))
    check("in the rule's own name and colour",
          next(s for s in mix["slices"] if s["key"] == relance)["label"] == "À relancer"
          and next(s for s in mix["slices"] if s["key"] == relance)["tone"] == "amber")
    check("shares add up to about 100 %", 99 <= sum(s["pct"] for s in mix["slices"]) <= 101)
    check("the dashboard's advice still comes", isinstance(d.get("recommendations"), list))
    vue = A.analyses(tab="vue", token_data=TD())["data"]
    check("Analyses draws the same slices", [s["key"] for s in vue["status_mix"]["slices"]] == keys)

    # ---- Insights' « inactifs » follow the shop's Client actif ----------------------------------
    print("\nInsights' inactifs: the shop's own « Client actif » window")
    short = [dict(r, conditions=[{"type": "visited_within", "value": 2}]) if r.get("key") == "actif" else r
             for r in R.load("t1")]
    put(short)
    shop = I.Shop("t1", now)
    check("with a 2-day window, Fay (3 days ago) is inactive", "p6" in {c["id"] for c in I._inactive(shop)})
    found = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("key") == "inactifs" and "body" in x:
                found.append(x["body"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(I._payload("t1", now))
    check("the advice says the shop's own days", found and "depuis plus de 2 jours" in found[0])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
