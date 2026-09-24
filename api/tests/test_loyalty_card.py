"""
Carte de fidélité — the page's own API: settings, the reward ladder, and the
four figures. Every number here is counted from real rows; nothing is demo.

    cd api && python3 tests/test_loyalty_card.py
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
    from fastapi import HTTPException
    from features import loyalty_card as LC

    db = server.db
    LC.init(db)                      # the loader does this at boot; tests call it directly
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "name": "Le Petit Café", "slug": "le-petit-cafe", "city": "Tours"})

    # ---- defaults ---------------------------------------------------------
    s = LC.get_card_settings(TD())
    check("card name falls back to the shop", s["design"]["card_name"] == "Carte Fidélité – Le Petit Café")
    check("a fresh tenant runs the stamps programme", s["programme"]["type"] == "stamps")
    check("ladder has four rungs, sorted", [t["key"] for t in s["tiers"]] == ["bronze", "silver", "gold", "vip"])
    check("ladder ranges read in visits", s["tiers"][0]["range_label"].endswith("visites"))
    check("every toggle defaults to on", all(s["toggles"][k] for k in
          ("show_points", "show_qr", "show_message", "wallet_enabled")))

    # ---- saving -----------------------------------------------------------
    LC.put_card_settings(LC.CardSettings(
        card_name="Carte Fidélité – Le Petit Café", surface_color="#8B5E3C", brand_color="#F5E9D7",
        welcome_text="Savourez chaque visite, collectez des points !", card_message="Merci de faire partie de notre communauté !",
        programme="points", points_per_euro=10, reward_points=100,
        reward_description="1 boisson offerte", show_qr=True, birthday_notification=False), TD())
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("design saved", tpl["surface_color"] == "#8B5E3C" and tpl["brand_color"] == "#F5E9D7")
    check("programme is a rule, not a label (points → per_euro)",
          tpl["programme"] == "points" and tpl["points_mode"] == "per_euro")
    check("message reaches the card face too", tpl["offer_box_text"] == "Merci de faire partie de notre communauté !")
    check("birthday toggle lands on the automation, not the card",
          db.auto_campaigns.find_one({"tenant_id": "t1"})["birthday"]["enabled"] is False)

    s2 = LC.get_card_settings(TD())
    check("ladder switches to points once the programme does", s2["tiers"][1]["range_label"].endswith("points"))

    # ---- the ladder -------------------------------------------------------
    LC.put_rewards([LC.RewardTier(min=0, reward="Boisson offerte"),
                    LC.RewardTier(min=100, reward="Pâtisserie offerte"),
                    LC.RewardTier(min=300, reward="Menu offert"),
                    LC.RewardTier(min=600, reward="Avantages VIP")], TD())
    tiers = LC.tiers_for("t1")
    check("ranges printed as the page shows them", tiers[0]["range_label"] == "0 · 100 points"
          and tiers[3]["range_label"] == "600+ points")
    try:
        LC.put_rewards([LC.RewardTier(min=0, reward="A"), LC.RewardTier(min=0, reward="B")], TD())
        check("a flat ladder is refused", False)
    except HTTPException as e:
        check("a flat ladder is refused", e.status_code == 400)

    check("classified on points in a points programme",
          LC.classify({"points": 350, "visits": 1}, "t1") == "gold")
    LC.put_card_settings(LC.CardSettings(programme="stamps"), TD())
    LC.put_rewards([LC.RewardTier(min=0, reward="A"), LC.RewardTier(min=10, reward="B"),
                    LC.RewardTier(min=20, reward="C"), LC.RewardTier(min=40, reward="D")], TD())
    check("classified on visits in a stamps programme",
          LC.classify({"points": 350, "visits": 12}, "t1") == "silver")

    # ---- advanced options (what Apple and Google actually expose) ---------
    LC.put_card_settings(LC.CardSettings(
        code_type="barcode", show_card_number=False, use_full_name=True,
        stamps_label="Cafés", allow_sharing=True, location_reminder=False,
        pass_expiration_date="2027-06-30T23:59:00Z",
        back_fields=[{"label": "Horaires", "value": "Lun-Sam 8h-19h"},
                     {"label": "", "value": "ignoré"}]), TD())
    adv = LC.get_card_settings(TD())["advanced"]
    check("advanced options saved", adv["code_type"] == "barcode" and adv["use_full_name"] is True
          and adv["stamps_label"] == "Cafés")
    check("empty back rows dropped", adv["back_fields"] == [{"label": "Horaires", "value": "Lun-Sam 8h-19h"}])
    try:
        LC.put_card_settings(LC.CardSettings(code_type="hologramme"), TD())
        check("unknown code type refused", False)
    except HTTPException as e:
        check("unknown code type refused", e.status_code == 400)

    # they must reach the pass itself, not just the settings document
    from features import wallet_passes as WP
    WP.init(db)
    db.customers.insert_one({"id": "cadv", "tenant_id": "t1", "barcode_id": "FT-ADV1", "name": "Marie Dupont",
                             "visits": 3, "points": 30, "tier": "bronze",
                             "created_at": dt.datetime.now(dt.timezone.utc)})
    os.environ.update({"APPLE_PASS_TYPE_ID": "pass.test", "APPLE_TEAM_ID": "TEAM"})
    pj = WP.build_pass_json(WP._card_payload("FT-ADV1"))
    check("code type reaches the pass", pj["barcodes"][0]["format"] == "PKBarcodeFormatCode128")
    check("card number hidden when asked", "altText" not in pj["barcodes"][0])
    check("full name honoured", any(f.get("value") == "Marie Dupont" for f in pj["storeCard"]["secondaryFields"]))
    check("custom back row on the pass",
          any(f["label"] == "Horaires" for f in pj["storeCard"]["backFields"]))
    check("sharing allowed when asked", pj["sharingProhibited"] is False)
    check("expiry reaches the pass", pj.get("expirationDate") == "2027-06-30T23:59:00Z")
    LC.put_card_settings(LC.CardSettings(code_type="qr", show_card_number=True, use_full_name=False,
                                         back_fields=[], pass_expiration_date=""), TD())
    db.customers.delete_one({"id": "cadv"})

    # ---- statistics -------------------------------------------------------
    def visit(cid, days_ago):
        db.visits.insert_one({"id": f"v{db.visits.count_documents({})}", "tenant_id": "t1",
                              "customer_id": cid, "visit_time": now - dt.timedelta(days=days_ago)})
    for i in range(4):
        db.customers.insert_one({"id": f"c{i}", "tenant_id": "t1", "barcode_id": f"FT-{i}",
                                 "created_at": now - dt.timedelta(days=3)})
    db.customers.insert_one({"id": "gone", "tenant_id": "t1", "barcode_id": "FT-X",
                             "created_at": now - dt.timedelta(days=3),
                             "card_deleted_at": now})
    visit("c0", 2); visit("c0", 5); visit("c1", 8); visit("c2", 9)      # window
    visit("c3", 40); visit("c3", 45); visit("c3", 50)                    # previous window
    db.rewards_redeemed.insert_one({"tenant_id": "t1", "customer_id": "c0", "redeemed_at": now - dt.timedelta(days=4)})
    db.rewards_redeemed.insert_one({"tenant_id": "t1", "customer_id": "c3", "redeemed_at": now - dt.timedelta(days=41)})

    st = LC.card_stats(30, TD())
    check("cartes actives ignores deleted cards", st["cards_active"]["value"] == 4)
    check("scans = visits in the window", st["qr_scans"]["value"] == 4)
    check("récompenses = redemptions in the window", st["rewards_used"]["value"] == 1)
    check("clients fidèles = came back twice", st["loyal_customers"]["value"] == 1)
    check("delta compares with the previous window",
          st["qr_scans"]["delta"] == round((4 - 3) / 3 * 100, 1))
    check("no delta invented out of zero", LC.card_stats(2, TD())["rewards_used"]["delta"] is None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
