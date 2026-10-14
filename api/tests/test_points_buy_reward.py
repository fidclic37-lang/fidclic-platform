"""
Les points achètent la récompense — et le palier ne redescend jamais.

Run: cd api && python3 tests/test_points_buy_reward.py
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from features import loyalty_card as LC

    db = server.db
    LC.init(db)
    passed = failed = 0
    NOW = dt.datetime.now(dt.timezone.utc)

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    LADDER = [{"key": "bronze", "min": 0, "reward": "Boisson offerte"},
              {"key": "silver", "min": 100, "reward": "Pâtisserie offerte"},
              {"key": "gold", "min": 200, "reward": "Brushing offert"},
              {"key": "vip", "min": 400, "reward": "Avantages VIP"}]
    db.tenants.insert_one({"id": "t1", "name": "Salon", "is_active": True})
    # `programme` says what kind of card it is; `points_mode` is what the scan
    # reads to credit. The settings page writes both — a fixture must too.
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "points_euro",
                                  "points_mode": "per_euro", "points_per_euro": 1,
                                  "reward_points": 200, "reward_tiers": LADDER,
                                  "reward_threshold_stamps": 10, "visits_per_stamp": 1})

    class TD:
        email, role, tenant_id, sid = "owner@x.fr", "business_owner", "t1", None

    def fresh(cid):
        return db.customers.find_one({"id": cid}, {"_id": 0})

    print("\n— ce qui compte pour le palier —")
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-PT001", "name": "Sarah",
                             "visits": 4, "points": 250, "points_lifetime": 250, "tier": "gold",
                             "tier_best": "gold", "created_at": NOW})
    check("250 points gagnés : palier Or", LC.tier_of(fresh("c1"), "t1") == "gold")

    print("\n— la récompense se paie en points —")
    out = server.redeem_reward(server.RedeemRewardRequest(customer_id="c1"), TD())
    c1 = fresh("c1")
    check("l'échange est enregistré", bool(out))
    check("le solde paie les 200 points", c1["points"] == 50)
    check("ce qui a été GAGNÉ ne bouge pas", c1["points_lifetime"] == 250)
    check("le palier Or reste", LC.tier_of(c1, "t1") == "gold" and c1.get("tier_best") == "gold")
    check("le cycle de la carte à tampons n'est pas touché",
          int(c1.get("visits_at_last_redemption") or 0) == 0)

    print("\n— pas assez de points —")
    from fastapi import HTTPException
    try:
        server.redeem_reward(server.RedeemRewardRequest(customer_id="c1"), TD())
        check("un solde trop bas est refusé", False)
    except HTTPException as e:
        check(f"un solde trop bas est refusé ({e.detail})", e.status_code == 400 and "150" in str(e.detail))

    print("\n— le palier ne redescend JAMAIS —")
    # le commerce relève son échelle : Or passe de 200 à 1000
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"reward_tiers": [
        {"key": "bronze", "min": 0, "reward": "x"}, {"key": "silver", "min": 500, "reward": "x"},
        {"key": "gold", "min": 1000, "reward": "x"}, {"key": "vip", "min": 2000, "reward": "x"}]}})
    LC._template.cache_clear() if hasattr(LC._template, "cache_clear") else None
    c1 = fresh("c1")
    check("une échelle relevée ne dégrade personne", LC.tier_of(c1, "t1") == "gold")
    res = LC.recompute_tiers("t1", announce=False)
    check("le recalcul ne fait descendre personne", res["down"] == 0)
    check("…et le palier est toujours Or", (fresh("c1").get("tier") or "") == "gold")

    # une correction au comptoir qui enlève des points
    db.customers.update_one({"id": "c1"}, {"$set": {"points": 0, "points_lifetime": 0}})
    check("même à zéro point, le palier gagné reste", LC.tier_of(fresh("c1"), "t1") == "gold")

    print("\n— une carte d'avant la bascule —")
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "barcode_id": "FT-PT002", "name": "Ancien",
                             "visits": 3, "points": 300, "tier": "gold", "created_at": NOW})
    old = fresh("c2")
    check("sans points_lifetime, le solde EST ce qui a été gagné", LC.earned_points(old) == 300)
    check("sans tier_best, le palier actuel est le plancher", LC.floor_of(old) == "gold")
    check("elle n'est donc pas dégradée", LC.tier_of(old, "t1") == "gold")

    print("\n— la bascule, une seule fois —")
    # elle a déjà tourné à l'import, sur une base vide : on la rejoue ici
    db.platform_settings.delete_one({"key": "points_split"})
    server._points_split_once()
    c2 = fresh("c2")
    check("points_lifetime est rempli depuis le solde", c2["points_lifetime"] == 300)
    check("tier_best est rempli depuis le palier du jour", c2["tier_best"] == "gold")
    mark = db.platform_settings.find_one({"key": "points_split"}, {"_id": 0, "value": 1})
    check("elle laisse sa marque", (mark or {}).get("value") == "v1")
    db.customers.update_one({"id": "c2"}, {"$set": {"points_lifetime": 999}})
    server._points_split_once()
    check("relancée, elle ne réécrit rien", fresh("c2")["points_lifetime"] == 999)

    print("\n— une carte à tampons ne change pas —")
    db.tenants.insert_one({"id": "t2", "name": "Café", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t2", "programme": "stamps", "reward_threshold_stamps": 3,
                                  "visits_per_stamp": 1, "points_per_visit": 10, "reward_points": 200})
    db.customers.insert_one({"id": "c3", "tenant_id": "t2", "barcode_id": "FT-ST001", "name": "Paul",
                             "visits": 3, "points": 30, "points_lifetime": 30, "created_at": NOW})

    class TD2(TD):
        tenant_id = "t2"

    server.redeem_reward(server.RedeemRewardRequest(customer_id="c3"), TD2())
    c3 = fresh("c3")
    check("c'est le cycle de la carte qui avance", int(c3.get("visits_at_last_redemption") or 0) == 3)
    check("et aucun point n'est retiré", c3["points"] == 30)

    print("\n— la caisse propose la récompense quand le solde suffit —")
    from features import scan_page as SP
    SP.init(db)
    db.customers.insert_one({"id": "c5", "tenant_id": "t1", "barcode_id": "FT-PT005", "name": "Riche",
                             "visits": 1, "points": 250, "points_lifetime": 250, "created_at": NOW})
    rows = SP.card(barcode="FT-PT005", token_data=TD())["applicables"]
    row = next((a for a in rows if a["kind"] == "card"), None)
    check("elle est proposée, au prix en points", row and row["available"] is True and row["sub"] == "200 points")
    db.customers.update_one({"id": "c5"}, {"$set": {"points": 10}})
    rows = SP.card(barcode="FT-PT005", token_data=TD())["applicables"]
    check("solde trop bas : rien n'est proposé",
          not [a for a in rows if a["kind"] == "card"])

    print("\n— un scan crédite les deux —")
    db.customers.insert_one({"id": "c4", "tenant_id": "t1", "barcode_id": "FT-PT004", "name": "Neuf",
                             "visits": 0, "points": 0, "created_at": NOW})
    server.scan_visit(server.ScanRequest(barcode_id="FT-PT004", amount_paid=20.0), TD())
    c4 = fresh("c4")
    check("le solde monte", c4["points"] == 20)
    check("et ce qui a été gagné aussi", c4["points_lifetime"] == 20)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
