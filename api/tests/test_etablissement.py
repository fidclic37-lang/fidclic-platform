"""
Paramètres › Établissement — the shop's identity, address and pin, legal
information, one proximity radius, and its points de vente; who may change what.

Run: cd api && /usr/local/bin/python3 tests/test_etablissement.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from models import TokenData
    from features import etablissement as E
    from features import team_access as T
    from features import store_scope as S

    db = server.db
    for m in (E, T, S):
        m.init(db)
    server.get_plan_features = lambda plan: {"multi_branch": plan != "silver"}
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def refused(fn, code=403):
        try:
            fn()
            return False
        except HTTPException as e:
            return e.status_code == code

    as_ = lambda email, role: TokenData(email=email, role=role, tenant_id="t1")
    OWNER, ALI, SARA = as_("o@c.fr", "business_owner"), as_("ali@c.fr", "administrateur"), as_("sara@c.fr", "manager")
    db.tenants.insert_one({"id": "t1", "slug": "corner", "name": "Le Corner Café", "plan": "gold", "sector": "cafe",
                           "legal_name": "Corner SAS", "siret": "12345678901234",
                           "address": "12 Rue Nationale, 37000 Tours", "postal_code": "37000", "city": "Tours",
                           "phone": "+33 2 47 12 34 56"})
    db.users.insert_many([
        {"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"},
        {"email": "ali@c.fr", "role": "administrateur", "tenant_id": "t1", "branch_ids": ["main"], "active": True},
        {"email": "sara@c.fr", "role": "manager", "tenant_id": "t1", "branch_ids": ["main"], "active": True},
    ])

    print("\nThe page reads what onboarding wrote")
    v = E.get_etablissement(token_data=OWNER)
    check("the street, out of onboarding's combined address", v["address"]["street"] == "12 Rue Nationale")
    check("the legal information", v["legal"] == {"legal_name": "Corner SAS", "siret": "12345678901234", "vat_number": ""})
    check("a shop without branches is its own main establishment",
          [s["id"] for s in v["stores"]] == ["main"] and v["stores"][0]["is_main"])
    check("one radius, 200 m unless set", v["geo"]["radius_m"] == 200)
    check("the owner may change everything", all(v["can"][k] for k in ("brand", "legal", "geo", "hours", "add_store")))

    print("\nSaving")
    v = E.put_etablissement(E.EtablissementIn(
        business=E.BusinessIn(name="Le Corner Café", email="contact@lecornercafe.fr", description="Café de spécialité",
                              sector="cafe", logo_url="data:image/png;base64,AAA"),
        address=E.AddressIn(street="12 Rue Nationale", postal_code="37000", city="Tours", lat=47.3936, lng=0.6892, pin="manuel"),
        geo=E.GeoIn(enabled=True, radius_m=5000, cooldown_days=3)), token_data=OWNER)
    t = db.tenants.find_one({"id": "t1"})
    check("identity saved", t["email"] == "contact@lecornercafe.fr" and t["description"] == "Café de spécialité")
    check("the logo is the card's logo — one logo for the shop",
          db.card_templates.find_one({"tenant_id": "t1"})["logo_url"] == "data:image/png;base64,AAA")
    check("the pin the owner placed is kept", (t["lat"], t["lng"], t["pin_source"]) == (47.3936, 0.6892, "manuel"))
    check("the address stays readable by older pages", t["address"] == "12 Rue Nationale, 37000 Tours")
    check("the radius is capped at 2 km", t["geo_radius_meters"] == 2000 and t["geo_cooldown_days"] == 3)
    check("a bad e-mail is refused", refused(lambda: E.put_etablissement(E.EtablissementIn(
        business=E.BusinessIn(email="nope")), token_data=OWNER), 400))
    check("a bad SIRET is refused", refused(lambda: E.put_etablissement(E.EtablissementIn(
        legal=E.LegalIn(siret="123")), token_data=OWNER), 400))
    check("half a pin is refused", refused(lambda: E.put_etablissement(E.EtablissementIn(
        address=E.AddressIn(lat=47.0)), token_data=OWNER), 400))

    print("\nWho changes what")
    E.put_etablissement(E.EtablissementIn(legal=E.LegalIn(legal_name="Corner Tours SAS", siret="987 654 321 00012")),
                        token_data=ALI)
    t = db.tenants.find_one({"id": "t1"})
    check("an administrateur may change the legal information",
          t["legal_name"] == "Corner Tours SAS" and t["siret"] == "98765432100012" and t["siren"] == "987654321")
    check("… not the shop's name, address or radius", refused(lambda: E.put_etablissement(E.EtablissementIn(
        business=E.BusinessIn(name="X")), token_data=ALI)))
    check("a manager changes nothing", refused(lambda: E.put_etablissement(
        E.EtablissementIn(legal=E.LegalIn(legal_name="X")), token_data=SARA))
          and E.get_etablissement(token_data=SARA)["can"]["legal"] is False)
    check("a manager reads", E.get_etablissement(token_data=SARA)["business"]["name"] == "Le Corner Café")

    print("\nPoints de vente")
    v = E.add_store(E.StoreIn(name="Le Corner Café Blois", street="3 Rue du Commerce", postal_code="41000",
                              city="Blois", phone="+33 2 54 00 00 00", lat=47.586, lng=1.335), token_data=OWNER)
    ids = [s["id"] for s in v["stores"]]
    check("the first point de vente turns the shop into its main establishment, id 'main'",
          ids[0] == "main" and len(ids) == 2 and v["stores"][0]["is_main"])
    check("the main establishment keeps the shop's address and pin",
          v["stores"][0]["street"] == "12 Rue Nationale" and v["stores"][0]["lat"] == 47.3936)
    blois = ids[1]
    check("both are establishments of the menu", [s["id"] for s in T.stores("t1")] == ["main", blois])
    db.visits.insert_many([{"id": "old", "tenant_id": "t1", "customer_id": "c1", "branch_id": None},
                           {"id": "new", "tenant_id": "t1", "customer_id": "c1", "branch_id": "main"}])
    check("the main establishment's visits, before and after, stay its own",
          db.visits.count_documents({"tenant_id": "t1", **S.visit_filter(S.Scope("t1", ["main"]))}) == 2)
    check("an administrateur edits a point de vente it covers",
          E.edit_store("main", E.StoreIn(phone="+33 2 47 99 99 99"), token_data=ALI)["stores"][0]["phone"] == "+33 2 47 99 99 99")
    check("… not one it does not", refused(lambda: E.edit_store(blois, E.StoreIn(phone="0"), token_data=ALI)))
    check("… nor close one", refused(lambda: E.edit_store("main", E.StoreIn(status="closed"), token_data=ALI)))
    v = E.edit_store(blois, E.StoreIn(status="closed"), token_data=OWNER)
    check("the owner closes a point de vente — kept, marked closed, out of the menu",
          any(s["id"] == blois and s["status"] == "closed" for s in v["stores"])
          and [s["id"] for s in T.stores("t1")] == ["main"])
    check("the main establishment cannot be closed",
          refused(lambda: E.edit_store("main", E.StoreIn(status="closed"), token_data=OWNER), 400))
    E.edit_store("main", E.StoreIn(street="14 Rue Nationale", lat=47.3940, lng=0.6890), token_data=OWNER)
    t = db.tenants.find_one({"id": "t1"})
    check("editing the main establishment moves the shop's address and pin with it",
          t["street"] == "14 Rue Nationale" and t["lat"] == 47.3940)
    db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "silver"}})
    check("a plan without several points de vente cannot add one",
          refused(lambda: E.add_store(E.StoreIn(name="X"), token_data=OWNER)))

    db.tenants.update_one({"id": "t1"}, {"$set": {"branches.0.id": "branch-x-main"}})
    E.put_etablissement(E.EtablissementIn(address=E.AddressIn(street="16 Rue Nationale")), token_data=OWNER)
    check("a main establishment flagged principal (any id) follows the shop's address",
          db.tenants.find_one({"id": "t1"})["branches"][0]["street"] == "16 Rue Nationale")
    db.tenants.update_one({"id": "t1"}, {"$set": {"branches.0.id": "main"}})

    print("\nThe wallet pass uses the one radius, at every open establishment")
    from features import wallet_passes as WP
    db.tenants.update_one({"id": "t1"}, {"$set": {"geo_radius_meters": 300, "branches.1.status": "open"}})
    db.customers.insert_one({"id": "c1", "tenant_id": "t1", "name": "Ana", "barcode_id": "FT-C1", "visits": 1})
    WP.init(db)
    pj = WP.build_pass_json(WP._card_payload("FT-C1"))
    check("two pins, 300 m each", [l["maxDistance"] for l in pj.get("locations", [])] == [300, 300])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
