"""
CA FidClic — each message in its own box, and only genuine reasons (user, 2026-11-10).

    « automation ko automation mein rakho, campaign ko campaign mein »
    « welcome, inscription, nth visit… client ko koi incentive ya reason
      nahi diye waapis aane ka, toh unko mat gino »

An automation's message is Automatisations (a relance « Client inactif »
was counted in Offres, a « Personnalisée » in Campagnes, a Push Wallet
scenario in Offres). A message sent BECAUSE of a visit, a signup or a
palier gives no reason to come back and is never counted, whatever its
delay: Bienvenue, Personnalisée « Nᵉ visite / après une visite / après
l'inscription », a custom rule on an action or on loyalty, palier atteint
(the Push Wallet one too), « Merci pour votre parrainage ».

    cd api && python3 tests/test_impact_genuine.py
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
    from features import fidclic_impact as FI, analyses as A, impact_detail as ID, visit_days as VD

    db = server.db
    A.init(db); FI.init(db); ID.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    now = dt.datetime.now(dt.timezone.utc)
    ago = lambda d: now - dt.timedelta(days=d)
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café"})
    FI.expected_anyway = lambda tid, visits: set()        # the brain is not under test here

    AUTOS = {
        "a_inactive": ("inactive", {"type": "inactivity", "days": 30}),
        "a_birthday": ("birthday", {}),
        "a_welcome": ("welcome", {}),
        "a_tier": ("tier_up", {}),
        "a_near": ("near_reward", {}),
        "a_referral": ("referral", {}),
        "a_review": ("google_review", {"type": "after_visit"}),
        "a_geo": ("geo", {}),
        "a_c_date": ("custom", {"type": "date", "date": "2026-11-01"}),
        "a_c_recurring": ("custom", {"type": "recurring", "mode": "weekly"}),
        "a_c_behavior": ("custom", {"type": "behavior", "inactive_days": 20}),
        "a_c_geo": ("custom", {"type": "geo"}),
        "a_c_visits": ("custom", {"type": "visits", "visits": 5}),
        "a_c_after_visit": ("custom", {"type": "after_visit", "delay_days": 7}),
        "a_c_after_signup": ("custom", {"type": "after_signup"}),
        "a_c_action": ("custom", {"type": "action", "action": "visit"}),
        "a_c_loyalty": ("custom", {"type": "loyalty", "visits": 10}),
    }
    PUSH_KIND = {"inactive": "push_wallet", "birthday": "birthday", "welcome": "welcome", "tier_up": "tier_up",
                 "near_reward": "near_reward", "referral": "parrainage", "google_review": "google_review",
                 "geo": "proximity", "custom": "automation"}
    for aid, (sc, tr) in AUTOS.items():
        db.automations.insert_one({"id": aid, "tenant_id": "t1", "scenario": sc, "name": aid, "trigger": tr})

    expect = {}

    def case(cid, want, *, note=None, wallet=None, recipients=None):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "visits": 3, "created_at": ago(300)})
        if note:
            db.push_notifications.insert_one({"tenant_id": "t1", "customer_id": cid, "title": cid,
                                              "body": "x", "sent_at": ago(5), **note})
        if wallet:
            db.push_wallet_log.insert_one({"tenant_id": "t1", "customer_id": cid, "title": cid, "sent_at": ago(5), **wallet})
        if recipients:
            db.campaigns.insert_one({"id": f"camp-{cid}", "tenant_id": "t1", "name": cid, "status": "sent",
                                     "sent_at": ago(5), "recipient_ids": [cid]})
        db.visits.insert_one({"id": f"v-{cid}", "tenant_id": "t1", "customer_id": cid, "amount_paid": 10.0,
                              "visit_time": ago(2)})
        expect[cid] = want

    def auto(aid):
        sc = AUTOS[aid][0]
        return {"type": PUSH_KIND[sc], "automation_id": aid, "automatic": True}

    # each automation in its own box
    case("inactive", "automatisations", note=auto("a_inactive"))
    case("birthday", "automatisations", note=auto("a_birthday"))
    case("c_date", "automatisations", note=auto("a_c_date"))
    case("c_recurring", "automatisations", note=auto("a_c_recurring"))
    case("c_behavior", "automatisations", note=auto("a_c_behavior"))
    case("geo", "geolocalisation", note=auto("a_geo"))
    case("c_geo", "geolocalisation", note=auto("a_c_geo"))
    case("gone_auto", "automatisations", note={"type": "automation", "automation_id": "deleted-since"})
    # sent because of a visit, a signup or a palier: no reason to come back
    for aid in ("a_welcome", "a_tier", "a_near", "a_referral", "a_review", "a_c_visits",
                "a_c_after_visit", "a_c_after_signup", "a_c_action", "a_c_loyalty"):
        case(aid[2:], None, note=auto(aid))
    case("merci_old", None, note={"type": "parrainage"})              # an older « Merci » without its automation
    # campaigns stay campaigns, offers stay offers
    case("camp", "campagnes", note={"type": "campaign", "campaign_id": "c1"})
    case("camp_rec", "campagnes", recipients=True)
    case("scheduled", "campagnes", note={"type": "scheduled"})
    case("promo", "offres", note={"type": "promotion_update"})
    case("perso", "offres", note={"type": "card_override"})
    case("flash", "offres", note={"type": "flash_sale"})
    # the automations the owner runs by hand
    case("rescue", "automatisations", note={"type": "inactive_rescue"})
    case("almost", "automatisations", note={"type": "almost_there"})
    # Push Wallet scenarios: automations — a palier one is a reaction
    db.push_scenarios.insert_many([
        {"id": "pw_inact", "tenant_id": "t1", "name": "Relance 14 jours", "trigger": "inactivity"},
        {"id": "pw_bday", "tenant_id": "t1", "name": "Anniversaire", "trigger": "birthday"},
        {"id": "pw_tier", "tenant_id": "t1", "name": "Palier", "trigger": "tier_up"},
    ])
    case("pw_inact", "automatisations", wallet={"scenario_id": "pw_inact"})
    case("pw_bday", "automatisations", wallet={"scenario_id": "pw_bday"})
    case("pw_tier", None, wallet={"scenario_id": "pw_tier"})
    case("pw_gone", "automatisations", wallet={"scenario_id": "deleted-since"})
    # what the message WAS when it went out wins over what the automation is now
    case("sent_timed", "automatisations", note={**auto("a_c_after_visit"), "trigger": "date", "timed": True})
    case("sent_reaction", None, note={**auto("a_c_date"), "trigger": "after_visit", "timed": False})
    case("pw_sent_tier", None, wallet={"scenario_id": "pw_inact", "trigger": "tier_up"})

    rows = list(db.visits.find({"tenant_id": "t1"}, {"_id": 0}))
    got = {v["customer_id"]: src for v, src in FI.source_by_visit("t1", rows)}

    print("\nEach message in its own box, only genuine reasons")
    for cid, want in expect.items():
        check(f"{cid:16s} → {want or 'not counted'}", got.get(cid) == want)

    print("\nThe figures follow")
    VD.ENABLED = True
    imp = A.analyses(tab="vue", days=30, token_data=TD())["data"]["impact"]
    by = {s["key"]: s["visits"] for s in imp["sources"]}
    want_by = {k: sum(1 for w in expect.values() if w == k)
               for k in ("campagnes", "geolocalisation", "offres", "automatisations", "parrainage")}
    check("Analyses counts each box as above", by == want_by)
    check("the reactions are in no box", imp["visits"] == sum(want_by.values()))
    d = ID.analyses_impact(days=30, token_data=TD())
    check("the detail says the same", d["totals"]["revenue"] == imp["revenue"])
    check("a register summed by the old rules is summed again", VD.SCHEMA >= 3)

    print("\nWhat a message was is kept when it goes out")
    src = open(os.path.join(os.path.dirname(__file__), "..", "features", "automations.py")).read()
    check("an automation's message keeps its trigger and whether it was timed",
          '"trigger": (row.get("trigger") or {}).get("type")' in src and '"timed": is_timed(scenario, row.get("trigger"))' in src)
    pw = open(os.path.join(os.path.dirname(__file__), "..", "features", "push_wallet.py")).read()
    check("a Push Wallet message keeps its trigger", '"trigger": row.get("trigger")' in pw)

    print("\nThe « déjà contacté » guard is untouched")
    from features import resend_guard as RG
    check("it still reads the message kinds as before",
          FI.source_of("push_wallet") == "offres" and FI.source_of("campaign") == "campagnes")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
