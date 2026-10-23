"""
« Enregistrer une visite » — la carte scannée, l'offre ou la récompense
appliquée, et ce que la visite vaut.

Run: cd api && python3 tests/test_scan_page.py
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
    from features import scan_page as SP

    db = server.db
    SP.init(db)
    passed = failed = 0
    NOW = dt.datetime.now(dt.timezone.utc)

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id, sid = "owner@x.fr", "business_owner", "t1", None

    db.tenants.insert_one({"id": "t1", "name": "Salon Élégance", "sector": "salon", "is_active": True})
    db.tenants.insert_one({"id": "t2", "name": "Boulangerie", "sector": "bakery", "is_active": True})
    # a stamp card: 3 stamps for a reward, one stamp a visit
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 3,
                                  "visits_per_stamp": 1, "points_per_visit": 10})
    db.tenant_catalog.insert_one({"tenant_id": "t1", "items": [
        {"id": "s-coupe", "name": "Coupe femme", "price": 45.0, "category": "Coupe"},
        {"id": "s-brush", "name": "Brushing", "price": 25.0, "category": "Brushing"},
    ]})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-SAL001", "name": "Sarah",
                             "phone": "06 12 34 56 78", "email": "sarah@email.com",
                             "visits": 0, "points": 0, "tier": "bronze", "created_at": NOW})

    def scan(**kw):
        kw.setdefault("barcode_id", "FT-SAL001")
        return server.scan_visit(server.ScanRequest(**kw), TD())

    print("\n— le mot du métier —")
    check("un salon fait des services", SP.wording("salon")["catalogue"] == "Catalogue services")
    check("une boulangerie vend des produits", SP.wording("bakery")["catalogue"] == "Catalogue produits")
    check("un secteur inconnu ne casse rien", SP.wording(None)["one"] == "produit")

    print("\n— la carte scannée —")
    c = SP.card(barcode="ft-sal001", token_data=TD())        # saisie en minuscules
    check("le client est retrouvé quel que soit la casse", c["customer"]["barcode_id"] == "FT-SAL001")
    check("ses coordonnées sont là", c["customer"]["phone"] == "06 12 34 56 78" and c["customer"]["email"])
    check("une carte à tampons compte des tampons", c["balance"]["unit"] == "tampons" and c["balance"]["value"] == 0)
    check("rien à appliquer sur une carte neuve", c["applicables"] == [])
    check("la carte papier est encore possible", c["paper"]["done"] is False and c["paper"]["max"] == 3)

    print("\n— le catalogue fait le montant —")
    r = scan(items=[{"item_id": "s-coupe", "qty": 1}, {"item_id": "s-brush", "qty": 2}])
    check("plusieurs prestations s'additionnent (45 + 2×25)", r["amount_paid"] == 95.0)
    v = db.visits.find_one({"customer_id": "c1"}, sort=[("visit_time", -1)])
    check("chaque ligne est gardée sur la visite", len(v["items"]) == 2
          and {i["name"] for i in v["items"]} == {"Coupe femme", "Brushing"})
    check("un prix envoyé par le navigateur est ignoré",
          scan(items=[{"item_id": "s-coupe", "qty": 1}], amount_paid=9999.0)["amount_paid"] == 45.0)

    print("\n— la récompense débloquée AUJOURD'HUI se remet aujourd'hui —")
    # deux visites faites : la carte est à 2/3. La troisième la remplit.
    db.customers.update_one({"id": "c1"}, {"$set": {"visits": 2, "visits_at_last_redemption": 0}})
    c = SP.card(barcode="FT-SAL001", token_data=TD())
    card_row = next((a for a in c["applicables"] if a["kind"] == "card"), None)
    check("la carte annonce la récompense comme « après cette visite »",
          card_row and card_row["available"] is False and card_row["after_visit"] is True)
    out = scan(items=[{"item_id": "s-coupe", "qty": 1}], apply="card")
    check("elle est remise dans le même scan", out["applied"] == {"kind": "card", "ok": True,
                                                                 "label": out["applied"].get("label")}
          or (out["applied"] or {}).get("ok") is True)
    check("le cycle de la carte repart", db.customers.find_one({"id": "c1"})["visits_at_last_redemption"] == 3)
    check("les visites de toujours ne baissent jamais", db.customers.find_one({"id": "c1"})["visits"] == 3)

    print("\n— une récompense non méritée —")
    bad = scan(apply="card")
    check("la visite est quand même enregistrée", bad["visits"] == 4)
    check("…et le refus est dit, pas caché", bad["applied"]["ok"] is False and bad["applied"]["error"])

    print("\n— l'offre enlève sa remise —")
    db.campaigns.insert_one({"id": "camp1", "tenant_id": "t1", "name": "-20% soin cheveux", "status": "sent",
                             "kind": "offre", "recipient_ids": ["c1"],
                             "offer": {"discount_type": "percent", "discount_value": 20}})
    o = scan(items=[{"item_id": "s-coupe", "qty": 1}], apply="offer:camp1")
    check("45,00 € moins 20 % font 36,00 €", o["amount_paid"] == 36.0)
    check("l'offre est marquée utilisée", db.offer_uses.find_one({"campaign_id": "camp1", "customer_id": "c1"}))
    again = scan(items=[{"item_id": "s-coupe", "qty": 1}], apply="offer:camp1")
    check("deux fois la même offre : refusée, la visite reste", again["applied"]["ok"] is False and again["visits"] == 6)

    db.campaigns.insert_one({"id": "camp2", "tenant_id": "t1", "name": "5 € de remise", "status": "sent",
                             "kind": "offre", "recipient_ids": ["c1"],
                             "offer": {"discount_type": "amount", "discount_value": 5}})
    check("une remise en euros se soustrait aussi",
          scan(items=[{"item_id": "s-brush", "qty": 1}], apply="offer:camp2")["amount_paid"] == 20.0)

    print("\n— le montant tapé par le comptoir —")
    db.campaigns.insert_one({"id": "camp3", "tenant_id": "t1", "name": "-50%", "status": "sent",
                             "kind": "offre", "recipient_ids": ["c1"],
                             "offer": {"discount_type": "percent", "discount_value": 50}})
    m = scan(items=[{"item_id": "s-coupe", "qty": 1}], apply="offer:camp3",
             amount_paid=40.0, amount_manual=True)
    check("un montant saisi à la main a le dernier mot", m["amount_paid"] == 40.0)

    print("\n— la carte papier, une seule fois —")
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "barcode_id": "FT-SAL002", "name": "Léa",
                             "visits": 0, "points": 0, "created_at": NOW})
    p1 = server.scan_visit(server.ScanRequest(barcode_id="FT-SAL002", paper_stamps=2), TD())
    check("les tampons du papier arrivent sur la carte", p1["stamps_in_cycle"] >= 2)
    c2 = SP.card(barcode="FT-SAL002", token_data=TD())
    check("et ne peuvent plus l'être", c2["paper"]["done"] is True and c2["paper"]["max"] == 0)

    print("\n— une carte à points —")
    db.card_templates.insert_one({"tenant_id": "t2", "programme": "points_euro", "points_per_euro": 1,
                                  "reward_tiers": [{"key": "bronze", "min": 0, "reward": "Boisson offerte"},
                                                   {"key": "silver", "min": 100, "reward": "Pâtisserie"},
                                                   {"key": "gold", "min": 200, "reward": "Brushing offert"},
                                                   {"key": "vip", "min": 400, "reward": "VIP"}]})
    db.customers.insert_one({"id": "c3", "tenant_id": "t2", "barcode_id": "FT-BOU001", "name": "Paul",
                             "visits": 4, "points": 120, "created_at": NOW})

    class TD2(TD):
        tenant_id = "t2"

    c3 = SP.card(barcode="FT-BOU001", token_data=TD2())
    check("elle compte des points, pas des tampons", c3["balance"]["unit"] == "points" and c3["balance"]["value"] == 120)
    check("le palier vient de l'échelle du commerce", c3["balance"]["tier_label"] == "Niveau Argent")
    check("et le prochain palier aussi", c3["balance"]["next_at"] == 200)
    check("la barre est remplie entre les deux paliers", c3["balance"]["pct"] == 20)

    print("\nUne carte supprimée est refusée dès le scan (QA R7, 2026-10-18)")
    from fastapi import HTTPException
    db.customers.insert_one({"id": "c4", "tenant_id": "t2", "barcode_id": "FT-SUP001", "name": "Supprimé",
                             "visits": 2, "points": 0, "created_at": NOW, "deleted_at": NOW})
    try:
        SP.card(barcode="FT-SUP001", token_data=TD2())
        refused = None
    except HTTPException as e:
        refused = e
    check(f"410 et le message de la caisse, avant de remplir la visite ({getattr(refused, 'status_code', None)})",
          refused is not None and refused.status_code == 410 and "supprimé" in str(refused.detail))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
