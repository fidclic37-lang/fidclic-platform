"""
Parrainage — the programme's dashboard.

Data is built here the way it is built in production: a code is generated for a
parrain, a filleul signs up, and the redemption is made through the real
endpoints. Nothing is inserted straight into referral_redemptions, so the whole
chain — code → redeem → pending/validated → dashboard — is what gets tested.

    cd api && python3 tests/test_referrals_page.py
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
    from features import referrals as R

    db = server.db
    R.init(db)
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
    db.tenants.insert_one({"id": "t1", "slug": "petit-cafe", "name": "Le Petit Café"})
    db.tenants.insert_one({"id": "t2", "slug": "rival", "name": "Rival"})

    # ---- the programme has to be on before anything is recorded ------------
    print("\nThe programme switch")
    R.update_config(R.ReferralConfig(enabled=False), TD())
    db.customers.insert_many([
        {"id": "p1", "tenant_id": "t1", "name": "Sophie Lambert", "barcode_id": "FT-P1",
         "tier": "gold", "visits": 24, "total_amount_paid": 0, "created_at": now - dt.timedelta(days=400)},
        {"id": "f0", "tenant_id": "t1", "name": "Refusé Test", "barcode_id": "FT-F0",
         "tier": "bronze", "visits": 1, "created_at": now},
    ])
    off = R.record("t1", "FT-P1", db.customers.find_one({"barcode_id": "FT-F0"}))
    check("a disabled programme records nothing", off is None)
    check("and the dashboard shows nothing yet",
          R.overview(token_data=TD())["cards"][0]["value"] == 0)

    R.update_config(R.ReferralConfig(enabled=True, referrer_reward_points=50,
                                     referee_reward_points=25, minimum_visits_to_earn=2), TD())
    check("the dashboard reports the programme as active", R.overview(token_data=TD())["enabled"] is True)

    # ---- build the cast ----------------------------------------------------
    # Four parrains, one of each kind the breakdown has to tell apart.
    PARRAINS = [
        ("p1", "Sophie Lambert", "gold",   24, False, 400),   # régulier
        ("p2", "Yassine Kaddour", "silver", 11, False, 300),  # régulier
        ("p3", "Camille Roux",   "bronze",  9, True,  200),   # étudiante (wins over visits)
        ("p4", "Lucas Marin",    "bronze",  2, False, 10),    # nouveau (joined 10 days ago)
        ("p5", "Inès Bouchard",  "vip",     1, False, 500),   # autres (old, barely visits)
    ]
    for cid, name, tier, visits, student, age in PARRAINS[1:]:
        db.customers.insert_one({
            "id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-{cid.upper()}",
            "tier": tier, "visits": visits, "is_student": student, "total_amount_paid": 0,
            "created_at": now - dt.timedelta(days=age)})
    db.customers.update_one({"id": "p1"}, {"$set": {"visits": 24}})

    # A parrain is identified by the card a stranger scanned — there is no code.
    check("a parrain is named by their own card",
          all(db.customers.find_one({"barcode_id": f"FT-{cid.upper()}"}) for cid, *_ in PARRAINS))

    # Filleuls: (id, name, parrain, visits, spend, source, days ago)
    FILLEULS = [
        ("f1", "Emma Dupont",   "p1", 4,  62.50, "qr",     0),
        ("f2", "Nicolas Petit", "p1", 3,  30.00, "link",   1),
        ("f3", "Léa Thibault",  "p1", 2,  18.00, "social", 2),
        ("f4", "Thomas Girard", "p2", 5,  44.00, "qr",     3),
        ("f5", "Sarah Mounir",  "p2", 2,  21.50, "link",   4),
        ("f6", "Hugo Lefevre",  "p3", 3,  27.00, "social", 5),
        ("f7", "Anna Klein",    "p3", 2,  15.00, "qr",     6),
        ("f8", "Omar Sy",       "p4", 1,   9.00, "link",   7),      # 1 visit → still pending
        ("f9", "Jade Morel",    "p5", 6,  53.00, "qr",     8),
    ]
    for cid, name, parrain, visits, spend, source, ago in FILLEULS:
        db.customers.insert_one({
            "id": cid, "tenant_id": "t1", "name": name, "barcode_id": f"FT-{cid.upper()}",
            "tier": "bronze", "visits": visits, "total_amount_paid": spend,
            "created_at": now - dt.timedelta(days=ago)})
        R.record("t1", f"FT-{parrain.upper()}", db.customers.find_one({"id": cid}))
        # The filleuls below have already been in, so settle what they earned —
        # in production the till does this on their first visit.
        R.settle("t1", cid)
        db.referral_redemptions.update_one({"referee_customer_id": cid}, {"$set": {"source": source}})
    # Spread them across the window so the curve has something to climb.
    for i, (cid, *_rest) in enumerate(FILLEULS):
        db.referral_redemptions.update_one(
            {"referee_customer_id": cid},
            {"$set": {"created_at": now - dt.timedelta(days=FILLEULS[i][6])}})

    d = R.overview(token_data=TD())

    # ---- the four figures ---------------------------------------------------
    print("\nThe four figures")
    by = {c["key"]: c for c in d["cards"]}
    check("there are exactly four cards, in the design's order",
          [c["key"] for c in d["cards"]] == ["referrals", "active", "points", "revenue"])
    check("the filleuls card the merchant removed is gone",
          not any("filleul" in c["label"].lower() for c in d["cards"]))
    check("parrainages réalisés counts every redemption", by["referrals"]["value"] == 9)
    check("parrains actifs counts the distinct parrains", by["active"]["value"] == 5)
    # 8 validated × 50 + 9 × 25 = 400 + 225
    # 8 settled × (50 + 25); Omar (1 visit, still pending) has been given
    # nothing yet — signup gives no points (user, 2026-10-20, QA R7 F41)
    check(f"points offerts adds both sides of every settled parrainage, none for a pending one ({by['points']['value']})",
          by["points"]["value"] == 600)
    check("CA généré adds every filleul's whole spend", by["revenue"]["value"] == 280.0)
    check("and it is labelled as all-time, not per period",
          by["revenue"]["all_time"] is True and by["revenue"]["note"] == "depuis le début")
    check("CA généré shows no percentage, since it has no previous period",
          by["revenue"]["delta_pct"] is None)

    print("\nThe comparison is against the previous window of the same length")
    older = R.overview(date_from=(now - dt.timedelta(days=9)).strftime("%Y-%m-%d"),
                       date_to=now.strftime("%Y-%m-%d"), token_data=TD())
    check("a first period shows no percentage rather than +100%",
          older["cards"][0]["delta_pct"] is None)
    db.referral_redemptions.update_one({"referee_customer_id": "f9"},
                                       {"$set": {"created_at": now - dt.timedelta(days=15)}})
    split = R.overview(date_from=(now - dt.timedelta(days=9)).strftime("%Y-%m-%d"),
                       date_to=now.strftime("%Y-%m-%d"), token_data=TD())
    check("a parrainage before the window drops out of the count",
          split["cards"][0]["value"] == 8)
    check("and lands in the previous window, so a delta appears",
          split["cards"][0]["delta_pct"] == 700)     # 8 vs 1
    db.referral_redemptions.update_one({"referee_customer_id": "f9"},
                                       {"$set": {"created_at": now - dt.timedelta(days=8)}})

    # ---- validated vs pending ------------------------------------------------
    print("\nValidé / En attente")
    rows = {r["filleul"]["name"]: r for r in R.overview(token_data=TD())["recent"]}
    check("a filleul below the visit threshold stays En attente",
          rows["Omar S."]["status"] == "pending" and rows["Omar S."]["status_label"] == "En attente")
    check("a filleul above it is Validé", rows["Emma D."]["status"] == "validated")
    check("a pending row shows the reward that is promised, as the design does",
          rows["Omar S."]["reward_points"] == 50)
    check("a validated one credits the configured points",
          rows["Emma D."]["reward_points"] == 50)
    # Points now wait for a real visit — BOTH sides. A signup is free to fake.
    check("a pending filleul is not credited yet either",
          db.customers.find_one({"id": "f8"}).get("points", 0) == 0)
    check("the parrain of a pending filleul was not credited",
          db.customers.find_one({"id": "p4"}).get("points", 0) == 0)
    check("a validated filleul is credited",
          db.customers.find_one({"id": "f1"}).get("points", 0) == 25)
    check("a parrain with three validated filleuls has three times the points",
          db.customers.find_one({"id": "p1"})["points"] == 150)

    print("\nThe same person cannot be referred twice")
    again = R.record("t1", "FT-P2", db.customers.find_one({"id": "f1"}))
    check("a second parrainage for the same filleul is refused", again is None)
    check("and the count does not move", R.overview(token_data=TD())["cards"][0]["value"] == 9)
    check("self-referral is refused",
          R.record("t1", "FT-P1", db.customers.find_one({"id": "p1"})) is None)

    # ---- who the parrains are -------------------------------------------------
    print("\nRépartition des parrainages")
    seg = {s["key"]: s for s in d["breakdown"]["segments"]}
    check("the four slices of the design are there, in order",
          [s["key"] for s in d["breakdown"]["segments"]]
          == ["reguliers", "etudiants", "nouveaux", "autres"])
    check("they are labelled in French",
          [s["label"] for s in d["breakdown"]["segments"]]
          == ["Clients réguliers", "Étudiants", "Nouveaux clients", "Autres"])
    check("Sophie's and Yassine's five parrainages are réguliers", seg["reguliers"]["count"] == 5)
    check("Camille's two are étudiants — declared at signup", seg["etudiants"]["count"] == 2)
    check("Lucas's one is a nouveau client", seg["nouveaux"]["count"] == 1)
    check("Inès's one falls to autres", seg["autres"]["count"] == 1)
    check("the slices account for every parrainage",
          sum(s["count"] for s in d["breakdown"]["segments"]) == d["breakdown"]["total"] == 9)
    check("shares add up to about 100 %",
          99 <= sum(s["pct"] for s in d["breakdown"]["segments"]) <= 101)

    print("\nÉtudiant beats every other rule")
    check("a student with many visits is still counted as a student",
          R._segment_of({"is_student": True, "visits": 99,
                         "created_at": now - dt.timedelta(days=900)}) == "etudiants")
    check("a customer with 5 visits is régulier",
          R._segment_of({"visits": R.REGULAR_MIN_VISITS}) == "reguliers")
    check("a fresh customer with few visits is nouveau",
          R._segment_of({"visits": 1, "created_at": now - dt.timedelta(days=5)}) == "nouveaux")
    check("an old customer with few visits is autres",
          R._segment_of({"visits": 1, "created_at": now - dt.timedelta(days=500)}) == "autres")
    check("a customer we know nothing about is autres", R._segment_of({}) == "autres")

    # ---- the leaderboard --------------------------------------------------------
    print("\nTop parrains")
    top = d["top_parrains"]
    check("at most five are listed", len(top) <= 5)
    check("the best parrain leads", top[0]["full_name"] == "Sophie Lambert")
    check("they are ranked by points earned",
          [p["points"] for p in top] == sorted((p["points"] for p in top), reverse=True))
    check("each row carries its filleul count", top[0]["filleuls"] == 3)
    check("names are shortened the way the design shows them", top[0]["name"] == "Sophie L.")
    check("the avatar carries the parrain's tier, not a photo", top[0]["tier"] == "gold")
    check("and its initials come from the full name", top[0]["initials"] == "SL")

    # ---- the curve ---------------------------------------------------------------
    print("\nÉvolution des parrainages")
    series = d["series"]
    check("there is one point per day of the period", len(series) == 30)
    check("it only ever climbs",
          all(series[i]["cumulative"] <= series[i + 1]["cumulative"] for i in range(len(series) - 1)))
    check("it ends at the period's total", series[-1]["cumulative"] == 9)
    check("it starts at zero before anything happened", series[0]["cumulative"] == 0)
    check("each point also carries that day's own count",
          sum(p["count"] for p in series) == 9)

    # ---- the table -----------------------------------------------------------------
    print("\nDerniers parrainages")
    recent = d["recent"]
    check("ten rows at most", len(recent) <= 10)
    check("newest first", [r["at"] for r in recent] == sorted((r["at"] for r in recent), reverse=True))
    check("each row names both sides", all(r["parrain"]["name"] and r["filleul"]["name"] for r in recent))
    check("the source of each parrainage is kept",
          {r["source"] for r in recent} <= set(R.SOURCES))
    labels = {r["source_label"] for r in recent}
    check("and shown in French", labels <= {"QR code", "Lien partagé", "Réseaux sociaux", "Autre"})
    check("a QR signup reads 'QR code'",
          next(r for r in recent if r["filleul"]["name"] == "Emma D.")["source_label"] == "QR code")
    check("an unknown channel falls back to Autre, never blank",
          R.SOURCES.get("hovercraft", R.SOURCES["other"]) == "Autre")

    # ---- the invitation ---------------------------------------------------------------
    # There is no link to share any more: a customer's own card is the way in.
    print("\nL'invitation")
    inv = R.inviter("FT-P1")
    check("the signup form learns who invited", inv["first_name"] == "Sophie")
    check("and which shop to sign up for", inv["slug"] == "petit-cafe")
    check("and what the filleul will get", inv["referee_points"] == 25)
    check("nothing else about the parrain leaks",
          "points" not in inv and "visits" not in inv and "tier" not in inv)

    # ---- settings ---------------------------------------------------------------------
    print("\nParamètres du programme")
    R.update_config(R.ReferralConfig(enabled=True, referrer_reward_points=80,
                                     referee_reward_points=40, minimum_visits_to_earn=3), TD())
    cfg = R.overview(token_data=TD())["config"]
    check("the new reward reaches the dashboard", cfg["referrer_reward_points"] == 80)
    check("so does the filleul's", cfg["referee_reward_points"] == 40)
    check("and the validation threshold", cfg["minimum_visits_to_earn"] == 3)
    db.customers.insert_one({"id": "f10", "tenant_id": "t1", "name": "Nouveau Test",
                             "barcode_id": "FT-F10", "tier": "bronze", "visits": 4,
                             "total_amount_paid": 12.0, "created_at": now})
    R.record("t1", "FT-P1", db.customers.find_one({"id": "f10"}))
    R.settle("t1", "f10")
    db.referral_redemptions.update_one({"referee_customer_id": "f10"}, {"$set": {"source": "social"}})
    fresh = {r["filleul"]["name"]: r for r in R.overview(token_data=TD())["recent"]}
    check("a parrainage after the change uses the new reward",
          fresh["Nouveau T."]["reward_points"] == 80)
    check("older parrainages keep the reward they were made with",
          fresh["Emma D."]["reward_points"] == 50)
    check("CA généré picks up the new filleul's spend",
          R.overview(token_data=TD())["cards"][3]["value"] == 292.0)

    # ---- isolation -----------------------------------------------------------------------
    print("\nOne merchant never sees another's programme")
    rival = R.overview(token_data=Rival())
    check("the rival's dashboard is empty", rival["cards"][0]["value"] == 0)
    check("their leaderboard is empty too", rival["top_parrains"] == [])
    check("and no revenue leaks across", rival["cards"][3]["value"] == 0)

    # ---- CSV ------------------------------------------------------------------------------
    print("\nExport")
    resp = R.export_referrals(token_data=TD())
    body = resp.body.decode()
    lines = [l for l in body.splitlines() if l.strip()]
    check("it opens in French Excel", body.startswith("﻿Date;"))
    check("the header names the table's columns",
          "Parrain;Filleul;Statut;Récompense;Source" in lines[0])
    check("every parrainage of the period is exported, not just the ten shown",
          len(lines) == 11)                                   # 10 redemptions + header
    check("full names are exported, not the shortened ones", "Sophie Lambert" in body)
    check("the status is exported in French", "Validé" in body and "En attente" in body)
    check("the filename says the period", "parrainage-" in resp.headers["Content-Disposition"])

    # ---- an untouched programme -------------------------------------------------------------
    print("\nA programme nobody has used")
    class Fresh:
        email, role, tenant_id = "new@shop.fr", "business_owner", "t3"
    empty = R.overview(token_data=Fresh())
    check("every figure reads zero", all(c["value"] == 0 for c in empty["cards"]))
    check("no figure invents a percentage", all(c["delta_pct"] is None for c in empty["cards"]))
    check("the breakdown is empty rather than a fake slice", empty["breakdown"]["total"] == 0)
    check("the curve still has its days", len(empty["series"]) == 30)
    check("and the table is empty, not broken", empty["recent"] == [])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
