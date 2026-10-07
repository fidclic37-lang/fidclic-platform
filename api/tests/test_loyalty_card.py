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
        programme="points_euro", points_per_euro=10, reward_points=100,
        reward_description="1 boisson offerte", show_qr=True, birthday_notification=False), TD())
    tpl = db.card_templates.find_one({"tenant_id": "t1"})
    check("design saved", tpl["surface_color"] == "#8B5E3C" and tpl["brand_color"] == "#F5E9D7")
    check("programme is a rule, not a label (points → per_euro)",
          tpl["programme"] == "points_euro" and tpl["points_mode"] == "per_euro")
    check("message reaches the card face too", tpl["offer_box_text"] == "Merci de faire partie de notre communauté !")
    check("birthday toggle lands on the Automatisations' birthday scenario, not the card",
          db.push_scenarios.find_one({"tenant_id": "t1", "builtin": "birthday"})["enabled"] is False
          and LC.get_card_settings(TD())["toggles"]["birthday_notification"] is False)

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
    before = [(t["key"], t["min"]) for t in LC.tiers_for("t1")]
    try:
        # Bronze's ceiling (Argent's floor) typed above Argent's own ceiling.
        LC.put_rewards([LC.RewardTier(key="bronze", min=0), LC.RewardTier(key="silver", min=500),
                        LC.RewardTier(key="gold", min=300), LC.RewardTier(key="vip", min=600)], TD())
        check("a ceiling above the next rung's is refused, saying which", False)
    except HTTPException as e:
        check("a ceiling above the next rung's is refused, saying which",
              e.status_code == 400 and "Or" in e.detail and "Argent" in e.detail)
    check("and the rungs keep their names and order", [(t["key"], t["min"]) for t in LC.tiers_for("t1")] == before)

    check("classified on points in a points programme",
          LC.classify({"points": 350, "visits": 1}, "t1") == "gold")
    LC.put_card_settings(LC.CardSettings(programme="stamps"), TD())
    LC.put_rewards([LC.RewardTier(min=0, reward="A"), LC.RewardTier(min=10, reward="B"),
                    LC.RewardTier(min=20, reward="C"), LC.RewardTier(min=40, reward="D")], TD())
    check("classified on visits in a stamps programme",
          LC.classify({"points": 350, "visits": 12}, "t1") == "silver")

    # ---- the four programmes really change how a scan earns ---------------
    class STD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"
    db.customers.insert_one({"id": "cscan", "tenant_id": "t1", "barcode_id": "FT-SCAN1", "name": "Léa",
                             "visits": 0, "points": 0, "tier": "bronze",
                             "created_at": dt.datetime.now(dt.timezone.utc)})

    def scan_once(amount):
        before = db.customers.find_one({"id": "cscan"})["points"]
        r = server.scan_visit(server.ScanRequest(barcode_id="FT-SCAN1", amount_paid=amount), STD())
        return r["points"] - before

    LC.put_card_settings(LC.CardSettings(programme="points_euro", points_per_euro=10), TD())
    check("points par euro: 20 € → 200 points", scan_once(20.0) == 200)
    LC.put_card_settings(LC.CardSettings(programme="points_visit", points_per_visit=25), TD())
    check("points par visite: flat 25 whatever the bill", scan_once(20.0) == 25)
    LC.put_card_settings(LC.CardSettings(programme="cashback", cashback_rate=5), TD())
    check("cagnotte 5 %: 20 € → 100 cents (1,00 €)", scan_once(20.0) == 100)
    # The till has no points field: a number sent by a browser never beats the
    # card's rules (it used to give a cashback card 10 instead of its euros).
    before = db.customers.find_one({"id": "cscan"})["points"]
    r = server.scan_visit(server.ScanRequest(barcode_id="FT-SCAN1", amount_paid=20.0, points=999), STD())
    check("a points value sent by the client is ignored (cashback still 100)", r["points"] - before == 100)
    check("the scan answer says what it added (the till shows it)", r["points_earned"] == 100)
    LC.put_card_settings(LC.CardSettings(programme="stamps"), TD())
    check("tampons: the bill does not change the earning", scan_once(20.0) == scan_once(3.0))
    LC.put_card_settings(LC.CardSettings(programme="cashback"), TD())
    check("cagnotte ladder reads in euros", "€ cagnottés" in LC.tiers_for("t1")[1]["range_label"])
    try:
        LC.put_card_settings(LC.CardSettings(programme="loterie"), TD())
        check("unknown programme refused", False)
    except HTTPException as e:
        check("unknown programme refused", e.status_code == 400)
    LC.put_card_settings(LC.CardSettings(programme="stamps"), TD())
    # The scans above wrote real visits; clear them so the statistics block
    # below measures the fixture it sets up and nothing else.
    db.customers.delete_one({"id": "cscan"})
    db.visits.delete_many({"customer_id": "cscan"})

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
    # these knobs are the classic storeCard's (the iOS 27 poster has its own test)
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"poster_style": False}})
    pj = WP.build_pass_json(WP._card_payload("FT-ADV1"))
    check("code type reaches the pass", pj["barcodes"][0]["format"] == "PKBarcodeFormatCode128")
    check("card number hidden when asked", "altText" not in pj["barcodes"][0])
    check("full name honoured", any(f.get("value") == "Marie Dupont" for f in pj["storeCard"]["secondaryFields"]))
    check("custom back row on the pass",
          any(f["label"] == "Horaires" for f in pj["storeCard"]["backFields"]))
    check("sharing allowed when asked", pj["sharingProhibited"] is False)
    check("expiry reaches the pass", pj.get("expirationDate") == "2027-06-30T23:59:00Z")
    # the second wave of advanced options
    LC.put_card_settings(LC.CardSettings(
        header_field="visits", hero_mode="brand", code_content="url",
        show_tier=False, show_meter=False, location_radius_m=5000,
        location_text="Un café vous attend !",
        points_change_message="Nouveau solde : %@ points",
        google_links=[{"label": "Réserver", "uri": "https://cafe.fr/reserver"},
                      {"label": "Pirate", "uri": "javascript:alert(1)"}]), TD())
    adv2 = LC.get_card_settings(TD())["advanced"]
    check("header field choice saved", adv2["header_field"] == "visits")
    check("radius clamped to Apple's sane range", adv2["location_radius_m"] == 2000)
    check("only real links kept", adv2["google_links"] == [{"label": "Réserver", "uri": "https://cafe.fr/reserver"}])
    db.customers.insert_one({"id": "cadv2", "tenant_id": "t1", "barcode_id": "FT-ADV2", "name": "Lea",
                             "visits": 6, "points": 60, "tier": "silver",
                             "created_at": dt.datetime.now(dt.timezone.utc)})
    pj2 = WP.build_pass_json(WP._card_payload("FT-ADV2"))
    check("header shows the chosen value", pj2["storeCard"]["headerFields"][0]["value"] == 6)
    check("a Code 128 carries the card number (a link is too dense for a 1D code)",
          pj2["barcodes"][0]["format"] == "PKBarcodeFormatCode128" and pj2["barcodes"][0]["message"] == "FT-ADV2")
    check("statut hidden when asked",
          all(f["key"] != "tier" for grp in pj2["storeCard"].values() for f in grp))
    check("custom update wording on the pass", any(
        f.get("changeMessage") == "Nouveau solde : %@ points"
        for grp in pj2["storeCard"].values() for f in grp))
    db.customers.delete_one({"id": "cadv2"})
    for bad, field in (("hologramme", "code_type"), ("milieu", "header_field"),
                       ("video", "hero_mode"), ("nfc", "code_content")):
        try:
            LC.put_card_settings(LC.CardSettings(**{field: bad}), TD())
            check(f"{field}={bad} refused", False)
        except HTTPException as e:
            check(f"{field}={bad} refused", e.status_code == 400)

    LC.put_card_settings(LC.CardSettings(code_type="qr", show_card_number=True, use_full_name=False,
                                         back_fields=[], pass_expiration_date="", header_field="auto",
                                         hero_mode="image", code_content="number", show_tier=True,
                                         show_meter=True, google_links=[]), TD())
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
    from features import clients_page as _CP, customer_rules as _R
    _rules = _R.load("t1")
    _loyal = sum(1 for c in db.customers.find({"tenant_id": "t1", "deleted_at": None}, _CP.FIELDS)
                 if _CP.is_loyal(c, LC._now(), _rules))
    check("clients fidèles = the Clients page's own (Règles clients)", st["loyal_customers"]["value"] == _loyal)
    check("delta compares with the previous window",
          st["qr_scans"]["delta"] == round((4 - 3) / 3 * 100, 1))
    check("no delta invented out of zero", LC.card_stats(2, TD())["rewards_used"]["delta"] is None)

    # ---- one progress indicator, never two -------------------------------------
    print("\nIndicateur de progression")
    LC.put_card_settings(LC.CardSettings(progress_style="stamps"), TD())
    a = LC.get_card_settings(TD())["advanced"]
    check("choosing stamps turns the meter off",
          a["progress_style"] == "stamps" and a["show_stamps"] is True and a["show_meter"] is False)
    LC.put_card_settings(LC.CardSettings(progress_style="meter"), TD())
    a = LC.get_card_settings(TD())["advanced"]
    check("choosing the meter turns the stamps off",
          a["progress_style"] == "meter" and a["show_meter"] is True and a["show_stamps"] is False)
    LC.put_card_settings(LC.CardSettings(progress_style="none"), TD())
    a = LC.get_card_settings(TD())["advanced"]
    check("choosing none turns both off",
          a["progress_style"] == "none" and a["show_meter"] is False and a["show_stamps"] is False)
    check("the card can never carry both at once", not (a["show_meter"] and a["show_stamps"]))
    try:
        LC.put_card_settings(LC.CardSettings(progress_style="sparkles"), TD())
        check("an unknown indicator is refused", False)
    except HTTPException as exc:
        check("an unknown indicator is refused", exc.status_code == 400)
    check("a card saved before the choice existed reads as the meter — what its "
          "customers already see in Wallet",
          LC._progress_style({}) == "meter")
    check("a card that had only stamps keeps them",
          LC._progress_style({"show_meter": False}) == "stamps")
    check("a card with neither reads as none",
          LC._progress_style({"show_meter": False, "show_stamps": False}) == "none")

    # ---- the QR sits on the card, not on a white plate ---------------------------------------
    print("\nLe QR code sur la carte, pas sur une plaque blanche")
    root = os.path.join(os.path.dirname(__file__), "..", "..", "src")
    theme = open(os.path.join(root, "lib", "cardTheme.js")).read()
    check("the code's colours are the card's own, not hardcoded white",
          "codeBg: bg," in theme and "codeInk: ink," in theme
          and "codeBg: '#FFFFFF'" not in theme)

    for rel in (("components", "WalletCard.jsx"), ("components", "PremiumLoyaltyCard.jsx"),
                ("components", "AuchanCard.jsx"), ("pages", "MyWalletCardPage.jsx")):
        name = rel[-1]
        src = open(os.path.join(root, *rel)).read()
        block = src[max(0, src.index("<QRCodeSVG") - 400): src.index("<QRCodeSVG") + 400]
        check(f"{name}: no white plate around the code",
              'bg-white rounded' not in block and 'bgColor="#FFFFFF"' not in block)
        check(f"{name}: the quiet zone the plate used to give is asked for",
              "marginSize={4}" in block)

    check("WalletCard's code block is no longer a filled box",
          "background: 'transparent', borderRadius: 12, padding: 0," in
          open(os.path.join(root, "components", "WalletCard.jsx")).read())

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
