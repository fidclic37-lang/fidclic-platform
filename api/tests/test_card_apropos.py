"""
The card's « À propos » (user, 2026-10-22): filled by Paramètres ›
Établissement — description, opening hours, phone, website — plus the
card's « Informations complémentaires » (the Wallet pass's back lines). An
establishment's own address and phone stay its own.

Run: cd api && /usr/local/bin/python3 tests/test_card_apropos.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-apropos")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server

    db = server.db
    week = [{"day": d, "open_from": "09:00", "open_to": "19:00", "closed": False}
            for d in ("monday", "tuesday", "wednesday", "thursday", "friday")]
    week += [{"day": "saturday", "open_from": "10:00", "open_to": "18:00", "closed": False},
             {"day": "sunday", "open_from": "07:00", "open_to": "19:00", "closed": True}]
    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
                           "is_active": True, "address": "11 Place de la Liberté, 37000 Tours", "phone": "0247000000",
                           "description": "Barbier depuis 2015, coupe et barbe.", "website": "royaltrim.fr",
                           "weekly_schedule": week,
                           "branches": [{"id": "main", "name": "LIBÉRTÉ", "is_main": True},
                                        {"id": "pal", "name": "PALISSY", "street": "5 rue Palissy", "postal_code": "37000",
                                         "city": "Tours", "phone": "0247111111"}]})
    db.card_templates.insert_one({"tenant_id": "t1", "card_name": "ROYAL TRIM",
                                  "back_fields": [{"label": "Instagram", "value": "@royaltrim"},
                                                  {"label": "Conditions", "value": "Valable sur présentation de la carte."},
                                                  {"label": "", "value": "ligne vide ignorée"}]})
    for cid, br in (("c_main", "main"), ("c_pal", "pal")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": "Mahdi", "barcode_id": f"FT-{cid.upper()}",
                                 "branch_id": br, "visits": 0, "points": 0})

    def details(cid):
        return server._serialize_card_payload(db.customers.find_one({"id": cid}, {"_id": 0}))["card"]["details"]

    d = details("c_main")
    check(f"À propos = the établissement's description ({d.get('about')})", d.get("about") == "Barbier depuis 2015, coupe et barbe.")
    check(f"opening hours, days in a row together ({d.get('hours')!r})",
          d.get("hours") == "Lundi – Vendredi : 09:00 – 19:00\nSamedi : 10:00 – 18:00\nDimanche : fermé")
    check("phone", d.get("phone") == "0247000000")
    check(f"website, as a link ({d.get('website')})", d.get("website") == "https://royaltrim.fr")
    check("address", d.get("address") == "11 Place de la Liberté, 37000 Tours")
    secs = [(x.get("title"), x.get("body")) for x in d.get("custom_sections") or []]
    check(f"the back lines follow ({secs})", secs == [("Instagram", "@royaltrim"),
                                                      ("Conditions", "Valable sur présentation de la carte.")])

    d = details("c_pal")
    check(f"Palissy keeps its own address ({d.get('address')})", d.get("address") == "5 rue Palissy, 37000 Tours")
    check(f"…and its own phone ({d.get('phone')})", d.get("phone") == "0247111111")
    check("…with the account's description and hours", d.get("about") and d.get("hours", "").startswith("Lundi"))

    db.tenants.update_one({"id": "t1"}, {"$unset": {"weekly_schedule": "", "description": "", "website": ""}})
    db.card_templates.update_one({"tenant_id": "t1"}, {"$set": {"details": {"about": "Ancien texte"}}, "$unset": {"back_fields": ""}})
    d = details("c_main")
    check("nothing saved in Établissement: an older À propos stays", d.get("about") == "Ancien texte")
    check("…and no invented opening hours", not d.get("hours"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
