"""
CA FidClic — only the revenue a FidClic feature brought back.

Each rule the merchant was promised (user, 2026-10-02) is checked on its own
client, so a failure names the rule that broke:

    a plain scan is not FidClic revenue
    a visit within 15 days after a campaign / proximity push / offer /
      automation is, under that source — the latest message wins
    a visit before the message, or more than 15 days after it, is not
    the messages sent because of a visit or a signup never count
    every visit of a filleul is CA Parrainage, however long after
    the Tableau de bord's « Impact FidClic » and Analyses' « CA FidClic » agree

    cd api && python3 tests/test_fidclic_impact.py
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
    from features import fidclic_impact as FI, analyses as A, dashboard_home as DH

    db = server.db
    A.init(db); DH.init(db); FI.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d, h=0: now - dt.timedelta(days=d, hours=h)

    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café"})
    people = ["plain", "camp", "before", "late", "reward", "nearr", "review", "welcome",
              "broadcast", "geo", "promo", "wallet", "perso", "bday", "rescue",
              "last", "filleul", "otherten", "oldcamp"]
    db.customers.insert_many([{"id": p, "tenant_id": "t1", "name": p, "visits": 3,
                               "created_at": ago(300), "last_visit_date": ago(1)} for p in people])

    def visit(cid, d, amount, h=0):
        db.visits.insert_one({"id": f"v-{cid}-{d}-{h}", "tenant_id": "t1", "customer_id": cid,
                              "amount_paid": amount, "visit_time": ago(d, h)})

    def msg(cid, kind, d, tenant="t1"):
        db.push_notifications.insert_one({"tenant_id": tenant, "customer_id": cid, "type": kind,
                                          "title": "x", "body": "x", "sent_at": ago(d)})

    # plain: a regular, no message at all
    visit("plain", 2, 10.0)
    # camp: campaign 5 days ago, came 2 days ago
    msg("camp", "campaign", 5); visit("camp", 2, 20.0)
    # before: came 6 days ago, the campaign went out 5 days ago
    visit("before", 6, 30.0); msg("before", "campaign", 5)
    # late: campaign 20 days ago, came 2 days ago — 18 days after
    msg("late", "campaign", 20); visit("late", 2, 40.0)
    # the messages a visit or a signup sends — never a reason to come
    for cid, kind in (("reward", "reward_unlocked"), ("nearr", "near_reward"),
                      ("review", "google_review"), ("welcome", "welcome"),
                      ("broadcast", "admin_broadcast")):
        msg(cid, kind, 5); visit(cid, 2, 50.0)
    # each source
    msg("geo", "proximity", 1); visit("geo", 0, 7.0, h=1)
    msg("promo", "promotion_update", 4); visit("promo", 2, 11.0)
    db.push_wallet_log.insert_one({"tenant_id": "t1", "customer_id": "wallet", "sent_at": ago(3)})
    visit("wallet", 2, 13.0)
    msg("perso", "card_override", 4); visit("perso", 3, 17.0)
    msg("bday", "birthday", 6); visit("bday", 2, 19.0)
    msg("rescue", "inactive_rescue", 6); visit("rescue", 2, 23.0)
    # last: an offer, then a proximity push — the latest takes the visit
    msg("last", "offer", 6); msg("last", "proximity", 3); visit("last", 2, 29.0)
    # filleul: parrainé, never messaged, comes 200 days and 2 days later
    db.referral_redemptions.insert_one({"tenant_id": "t1", "referrer_customer_id": "plain",
                                        "referee_customer_id": "filleul", "created_at": ago(250)})
    visit("filleul", 200, 31.0); visit("filleul", 2, 37.0)
    # otherten: the message belongs to another shop
    msg("otherten", "campaign", 4, tenant="t2"); visit("otherten", 2, 41.0)
    # oldcamp: a campaign row (no per-client row), sent 3 days ago
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "name": "Vieille campagne",
                             "sent_at": ago(3), "recipient_ids": ["oldcamp"]})
    visit("oldcamp", 1, 43.0)

    rows = list(db.visits.find({"tenant_id": "t1", "visit_time": {"$gte": ago(29)}}))
    by = {v["customer_id"]: s for v, s in FI.source_by_visit("t1", rows)}

    print("\nWhat is not FidClic revenue")
    check("a plain scan", by["plain"] is None)
    check("a visit before the campaign was sent", by["before"] is None)
    check("a visit more than 15 days after it", by["late"] is None)
    for cid in ("reward", "nearr", "review", "welcome", "broadcast"):
        check(f"a visit after a « {cid} » message (sent because of a visit or by the platform)",
              by[cid] is None)
    check("a message from another shop", by["otherten"] is None)

    print("\nWhat is, and under which source")
    check("a visit within 15 days of a campaign → Campagnes", by["camp"] == "campagnes")
    check("a campaign known only by its recipients → Campagnes", by["oldcamp"] == "campagnes")
    check("after a proximity push → Géolocalisation", by["geo"] == "geolocalisation")
    check("after a promotion → Offres", by["promo"] == "offres")
    check("after a Push Wallet offer → Offres", by["wallet"] == "offres")
    check("after a personal card offer → Offres", by["perso"] == "offres")
    check("after the birthday message → Automatisations", by["bday"] == "automatisations")
    check("after the relance des inactifs → Automatisations", by["rescue"] == "automatisations")
    check("the latest message takes the visit", by["last"] == "geolocalisation")
    check("a filleul's visit → Parrainage", by["filleul"] == "parrainage")

    long_rows = list(db.visits.find({"tenant_id": "t1", "customer_id": "filleul"}))
    check("every visit of a filleul, however long after joining",
          all(s == "parrainage" for _, s in FI.source_by_visit("t1", long_rows)))

    print("\nThe totals")
    imp = FI.impact("t1", rows)
    expected = 20 + 7 + 11 + 13 + 17 + 19 + 23 + 29 + 37 + 43
    check("CA FidClic adds up the counted visits only", imp["revenue"] == expected)
    check("and counts them", imp["visits"] == 10)
    check("Parrainage is the filleul's money", imp["sources"]["parrainage"]["revenue"] == 37.0)
    check("Offres adds its three", imp["sources"]["offres"]["revenue"] == 41.0)

    a = A.analyses(tab="vue", days=30, token_data=TD())["data"]
    strip = {s["key"]: s for s in a["strip"]}
    check("Analyses' CA FidClic is that figure", strip["fidclic"]["value"] == expected)
    check("its CA Parrainage card too", strip["referral"]["value"] == 37.0)
    check("the panel's sources add up to the total",
          round(sum(s["revenue"] for s in a["impact"]["sources"]), 2) == expected)
    h = DH.overview(days=30, token_data=TD())
    check("the Tableau de bord's Impact FidClic is the same figure", h["impact"]["value"] == expected)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
