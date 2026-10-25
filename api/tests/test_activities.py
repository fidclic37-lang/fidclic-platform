"""
Activités (user, 2026-10-25: « fleuriste, cbd and tabac, opticien, librairie
etc. sab alag kro », with researched rhythms): the precise trade under each
sector, chosen in Établissement, where brain-v2 starts a shop's usual rhythm.

Run: cd api && /usr/local/bin/python3 tests/test_activities.py
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-activities")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    from fastapi import HTTPException
    from models import TokenData
    from features import brain_v2 as V2
    from features import client_brain as CB
    from features import etablissement as E
    from services import activities as A

    db = server.db
    print("Le catalogue")
    sectors = {k for k, _ in E.SECTORS}
    check("every activity belongs to a sector of Établissement", all(a["sector"] in sectors for a in A.ACTIVITIES))
    check("every sector has at least one activity", sectors <= {a["sector"] for a in A.ACTIVITIES})
    check("every figure is a positive number of days, with its basis and source",
          all(a["gap"] > 0 and a["basis"] in ("étude", "pratique", "estimation") and a["source"] for a in A.ACTIVITIES))
    check("trades of one sector are apart (barbier ≠ coiffure femme, tabac ≠ opticien)",
          A.BY_KEY["barbier"]["gap"] == 21 and A.BY_KEY["coiffure_femme"]["gap"] == 56
          and A.BY_KEY["tabac_presse"]["gap"] == 2 and A.BY_KEY["opticien"]["gap"] == 180
          and A.BY_KEY["cbd"]["gap"] == 10 and A.BY_KEY["fleuriste"]["gap"] == 45 and A.BY_KEY["librairie"]["gap"] == 30)
    check("keys are unique", len(A.BY_KEY) == len(A.ACTIVITIES))
    check("every sector default and alias names a real activity",
          all(v in A.BY_KEY for v in A.SECTOR_DEFAULT.values()) and all(v in A.BY_KEY for v in A.ALIASES.values()))

    print("L'activité d'une boutique")
    check("the one it chose", A.of({"sector": "retail", "activity_key": "cbd"})["key"] == "cbd")
    check("one its sector names (older shops, the demo)", A.of({"sector": "Boulangerie"})["key"] == "boulangerie"
          and A.of({"sector": "barbier"})["key"] == "barbier")
    check("else its sector's most common trade", A.of({"sector": "salon"})["key"] == "coiffure_mixte"
          and A.of({"sector": "retail"})["key"] == "autre_commerce" and A.of({})["key"] == "autre")
    check("choices under a sector", [c["value"] for c in A.choices("salon")] == ["barbier", "coiffure_homme", "coiffure_femme", "coiffure_mixte"])

    print("brain-v2 part de là")
    check("CBD shop: 10 days", V2.sector_prior({"sector": "retail", "activity_key": "cbd"}) == (10.0, "secteur"))
    check("tabac: 2 days; opticien: 180", V2.sector_prior({"sector": "retail", "activity_key": "tabac_presse"})[0] == 2.0
          and V2.sector_prior({"sector": "retail", "activity_key": "opticien"})[0] == 180.0)
    db.tenants.insert_one({"id": "t1", "name": "RT", "sector": "salon", "activity_key": "barbier"})
    check("the shop's own brain-v2 prior reads its activity", CB.prior_for("t1", 2) == (21.0, "secteur"))
    check("v1 is left as it shipped (salon: 35 days)", CB.prior_for("t1", 1) == (35.0, "secteur"))

    print("Établissement")
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    OWNER = TokenData(email="o@x.fr", role="business_owner", tenant_id="t1")
    v = E.get_etablissement(token_data=OWNER)
    check("the page gets the activities and the shop's", v["business"]["activity_key"] == "barbier"
          and any(a["value"] == "cbd" and a["sector"] == "retail" for a in v["activities"]))
    E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(activity_key="coiffure_homme")), token_data=OWNER)
    check("saved", db.tenants.find_one({"id": "t1"})["activity_key"] == "coiffure_homme")
    try:
        E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(activity_key="cbd")), token_data=OWNER)
        refused = False
    except HTTPException as e:
        refused = e.status_code == 400 and "secteur" in e.detail
    check("an activity of another sector is refused", refused)
    try:
        E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(activity_key="nope")), token_data=OWNER)
        refused = False
    except HTTPException as e:
        refused = e.status_code == 400
    check("an unknown one too", refused)
    E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(sector="retail", activity_key="cbd")), token_data=OWNER)
    t = db.tenants.find_one({"id": "t1"})
    check("a new sector with its activity, in one save", t["sector"] == "retail" and t["activity_key"] == "cbd")
    E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(sector="cafe")), token_data=OWNER)
    check("a new sector alone: the other sector's activity goes", db.tenants.find_one({"id": "t1"}).get("activity_key") is None)
    E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(activity_key="glacier")), token_data=OWNER)
    E.put_etablissement(E.EtablissementIn(business=E.BusinessIn(activity_key="")), token_data=OWNER)
    check("« Non précisée » clears it", db.tenants.find_one({"id": "t1"}).get("activity_key") is None)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
