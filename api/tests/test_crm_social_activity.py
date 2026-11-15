"""
CRM › Prospects › how active a business is on social media (user, 2026-11-15):

    « jab social media links daalein, toh select kr sakein very active,
      moderately active, not very active and inactive… and filters mein bhi
      ye add kro ki classify kr sakein businesses ko »

Each prospect may say « Très actif », « Moyennement actif », « Peu actif » or
« Inactif » on social media (or nothing); the list filters by it (« Non
renseigné » too), and so do the pipeline and the export.

    cd api && python3 tests/test_crm_social_activity.py
"""
from __future__ import annotations

import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from models import TokenData
    from features import crm as C

    db = server.db
    C.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code):
        try:
            fn(); return False
        except HTTPException as e:
            return e.status_code == code

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem"})

    def add(name, act=None, **kw):
        return C.add_prospect(C.ProspectIn(name=name, city="Tours", instagram="https://instagram.com/x",
                                           social_activity=act, **kw), token_data=ADMIN)

    print("\nThe four levels")
    m = C.meta(token_data=ADMIN)
    check("offered in the form, in this order", [s["label"] for s in m["social_activities"]]
          == ["Très actif", "Moyennement actif", "Peu actif", "Inactif"])
    a = add("Café Très", "tres_actif")
    b = add("Boulangerie Moyen", "moyen")
    c = add("Fleuriste Peu", "peu_actif")
    d = add("Garage Inactif", "inactif")
    e = add("Pressing Rien")
    rows = {r["name"]: r for r in C.list_prospects(per_page=50, token_data=ADMIN)["rows"]}
    check("a prospect keeps its level and says it", rows["Café Très"]["social_activity"] == "tres_actif"
          and rows["Café Très"]["social_activity_label"] == "Très actif")
    check("none given: none said", rows["Pressing Rien"]["social_activity"] is None
          and rows["Pressing Rien"]["social_activity_label"] == "")
    check("an unknown level is refused", refused(lambda: add("X", "viral"), 400))

    print("\nChanged and cleared")
    pid = next(p["id"] for p in db.crm_prospects.find({"name": "Fleuriste Peu"}))
    C.edit_prospect(pid, C.ProspectIn(social_activity="tres_actif"), token_data=ADMIN)
    check("changed", db.crm_prospects.find_one({"id": pid})["social_activity"] == "tres_actif")
    C.edit_prospect(pid, C.ProspectIn(social_activity=""), token_data=ADMIN)
    check("cleared (« — »)", db.crm_prospects.find_one({"id": pid}).get("social_activity") is None)
    C.edit_prospect(pid, C.ProspectIn(social_activity="peu_actif"), token_data=ADMIN)
    C.edit_prospect(pid, C.ProspectIn(name="Fleuriste Peu"), token_data=ADMIN)
    check("an edit that does not name it keeps it", db.crm_prospects.find_one({"id": pid})["social_activity"] == "peu_actif")

    print("\nThe filter classifies the businesses")
    names = lambda **k: sorted(r["name"] for r in C.list_prospects(per_page=50, token_data=ADMIN, **k)["rows"])  # noqa: E731
    check("Très actif", names(social="tres_actif") == ["Café Très"])
    check("Inactif", names(social="inactif") == ["Garage Inactif"])
    check("« Non renseigné »", names(social="none") == ["Pressing Rien"])
    check("all of them without the filter", len(names()) == 5)
    check("with the other filters", names(social="moyen", city="Tours") == ["Boulangerie Moyen"]
          and names(social="moyen", city="Paris") == [])
    pipe = C.pipeline(social="tres_actif", token_data=ADMIN)
    check("the pipeline filters too", sum(len(col["rows"]) for col in pipe["columns"]) == 1)
    csv_text = C.export(social="inactif", token_data=ADMIN).body.decode("utf-8")
    check("the export filters and says it", "Garage Inactif" in csv_text and "Café Très" not in csv_text
          and "Activité réseaux" in csv_text and "Inactif" in csv_text)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
