"""
« Objectifs et récompenses » — les paliers que le commerce se fixe lui-même.

Run: cd api && python3 tests/test_milestones.py
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
    from fastapi import HTTPException
    from features import milestones as MS
    from features import role_perms as RP
    from features import scan_page as SP

    db = server.db
    MS.init(db); RP.init(db); SP.init(db)
    passed = failed = 0
    NOW = dt.datetime.now(dt.timezone.utc)

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id, sid = "owner@x.fr", "business_owner", "t1", None

    db.tenants.insert_one({"id": "t1", "name": "Salon", "sector": "salon", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps", "reward_threshold_stamps": 50,
                                  "visits_per_stamp": 1, "points_per_visit": 10})

    def put(items):
        return MS.put_milestones(MS.MilestonesIn(items=[MS.MilestoneIn(**i) for i in items]), TD())

    def fails(label, fn, text=None):
        try:
            fn()
        except HTTPException as e:
            return check(f"{label} ({e.detail})", text is None or text.lower() in str(e.detail).lower())
        return check(label + " — devait être refusé", False)

    print("\n— ce que le commerce écrit —")
    out = put([{"label": "Café offert", "unit": "visits", "threshold": 10},
               {"label": "Bouteille offerte", "unit": "amount", "threshold": 500, "repeat": True},
               {"label": "Soin offert", "unit": "points", "threshold": 200}])
    check("trois objectifs, chacun sur sa propre unité",
          [i["unit"] for i in out["items"]] == ["amount", "points", "visits"])
    check("chacun garde son id", all(i.get("id") for i in out["items"]))
    fails("deux objectifs au même seuil : refusé",
          lambda: put([{"label": "A", "unit": "visits", "threshold": 10},
                       {"label": "B", "unit": "visits", "threshold": 10}]), "même seuil")
    fails("une récompense vide : refusée",
          lambda: put([{"label": "   ", "unit": "visits", "threshold": 5}]), "récompense")
    fails("une unité inconnue : refusée",
          lambda: put([{"label": "A", "unit": "lunes", "threshold": 5}]), "unité")
    check("le même seuil sur une AUTRE unité est permis",
          len(put([{"label": "A", "unit": "visits", "threshold": 10},
                   {"label": "B", "unit": "points", "threshold": 10}])["items"]) == 2)

    print("\n— atteint pendant CETTE visite —")
    put([{"label": "Café offert", "unit": "visits", "threshold": 3, "valid_days": 30}])
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "barcode_id": "FT-OBJ1", "name": "Sarah",
                             "visits": 2, "points": 0, "created_at": NOW})
    r = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ1", amount_paid=10.0), TD())
    check("la 3e visite déclenche l'objectif", [w["reward"] for w in r["objectifs_won"]] == ["Café offert"])
    rows = SP.card(barcode="FT-OBJ1", token_data=TD())["applicables"]
    check("la caisse le propose tout de suite",
          any(a["kind"] == "defi" and a["title"] == "Café offert" for a in rows))

    print("\n— une fois, c'est une fois —")
    r2 = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ1", amount_paid=10.0), TD())
    check("la visite suivante ne le redonne pas", r2["objectifs_won"] == [])
    check("une seule récompense en attente",
          db.defi_rewards.count_documents({"customer_id": "c1", "kind": "objectif"}) == 1)

    print("\n— à chaque fois —")
    put([{"label": "Bon d'achat", "unit": "visits", "threshold": 2, "repeat": True, "valid_days": 30}])
    db.customers.insert_one({"id": "c2", "tenant_id": "t1", "barcode_id": "FT-OBJ2", "name": "Paul",
                             "visits": 1, "points": 0, "created_at": NOW})
    a = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ2"), TD())      # 2 visites
    b = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ2"), TD())      # 3
    c = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ2"), TD())      # 4
    check("gagné à 2, rien à 3, regagné à 4",
          len(a["objectifs_won"]) == 1 and b["objectifs_won"] == [] and len(c["objectifs_won"]) == 1)
    check("deux récompenses, pas une de plus",
          db.defi_rewards.count_documents({"customer_id": "c2", "kind": "objectif"}) == 2)

    print("\n— un client déjà loin n'encaisse pas tout le passé —")
    put([{"label": "Surprise", "unit": "visits", "threshold": 10, "repeat": True, "valid_days": 30}])
    db.customers.insert_one({"id": "c3", "tenant_id": "t1", "barcode_id": "FT-OBJ3", "name": "Ancien",
                             "visits": 99, "points": 0, "created_at": NOW})
    d = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ3"), TD())
    check("une seule récompense, celle du palier atteint (pas dix)", len(d["objectifs_won"]) == 1)

    print("\n— sur le montant dépensé —")
    put([{"label": "Bouteille", "unit": "amount", "threshold": 100, "valid_days": 30}])
    db.customers.insert_one({"id": "c4", "tenant_id": "t1", "barcode_id": "FT-OBJ4", "name": "Riche",
                             "visits": 0, "points": 0, "total_amount_paid": 0, "created_at": NOW})
    e1 = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ4", amount_paid=60.0), TD())
    e2 = server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ4", amount_paid=60.0), TD())
    check("60 € ne suffisent pas, 120 € oui", e1["objectifs_won"] == [] and len(e2["objectifs_won"]) == 1)

    print("\n— les points comptés sont ceux GAGNÉS —")
    cust = {"id": "x", "points": 10, "points_lifetime": 250}
    check("un solde dépensé ne fait pas reculer l'objectif", MS.progress_of(cust, "points") == 250)
    check("une carte d'avant la bascule lit son solde", MS.progress_of({"id": "y", "points": 70}, "points") == 70)

    print("\n— désactivé —")
    put([{"label": "Rien", "unit": "visits", "threshold": 1, "active": False}])
    db.customers.insert_one({"id": "c5", "tenant_id": "t1", "barcode_id": "FT-OBJ5", "visits": 0, "created_at": NOW})
    check("un objectif désactivé ne donne rien",
          server.scan_visit(server.ScanRequest(barcode_id="FT-OBJ5"), TD())["objectifs_won"] == [])

    print("\n— la permission —")
    check("« Objectifs et récompenses » est une permission à part entière", "milestones" in RP.PAGE_KEYS)
    check("elle couvre ses routes", RP.page_of("/api/owner/milestones") == "milestones")
    check("ce n'est pas une route commune à tous", not RP.is_common("/api/owner/milestones", "PUT"))
    check("l'employé ne l'a pas au départ", RP.DEFAULT_TEMPLATES["staff"].get("milestones", "none") == "none")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
