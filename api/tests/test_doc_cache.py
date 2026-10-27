"""
Un document, une lecture par requête (services/doc_cache).

Run: cd api && python3 tests/test_doc_cache.py
"""
from __future__ import annotations

import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from services import doc_cache as DC

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    reads = {"n": 0}
    real = type(db.tenants._real).find_one

    def counted(self, *a, **k):
        reads["n"] += 1
        return real(self, *a, **k)
    type(db.tenants._real).find_one = counted

    db.tenants.insert_one({"id": "tc1", "name": "Avant"})
    db.customers.insert_one({"id": "cc1", "tenant_id": "tc1", "name": "Client"})

    print("\n— dans une requête —")
    tok = DC.begin(); reads["n"] = 0
    a = db.tenants.find_one({"id": "tc1"})
    b = db.tenants.find_one({"id": "tc1"})
    check(f"la même question n'est posée qu'une fois ({reads['n']})", reads["n"] == 1)
    check("…et la réponse est la même", a == b and a["name"] == "Avant")
    db.tenants.find_one({"id": "autre"})
    check(f"une autre question est posée ({reads['n']})", reads["n"] == 2)
    DC.end(tok)

    print("\n— une écriture efface ce qui a été lu —")
    tok = DC.begin(); reads["n"] = 0
    db.tenants.find_one({"id": "tc1"})
    db.tenants.update_one({"id": "tc1"}, {"$set": {"name": "Après"}})
    fresh = db.tenants.find_one({"id": "tc1"})
    check("on relit ce qu'on vient d'écrire", fresh["name"] == "Après")
    check(f"donc deux lectures, pas une ({reads['n']})", reads["n"] == 2)
    DC.end(tok)

    print("\n— d'une requête à l'autre —")
    tok = DC.begin(); reads["n"] = 0
    db.tenants.find_one({"id": "tc1"})
    DC.end(tok)
    tok2 = DC.begin()
    db.tenants.update_one({"id": "tc1"}, {"$set": {"name": "Encore"}})
    DC.end(tok2)
    tok3 = DC.begin()
    check("rien ne traverse deux requêtes", db.tenants.find_one({"id": "tc1"})["name"] == "Encore")
    DC.end(tok3)

    print("\n— hors requête, rien n'est gardé —")
    reads["n"] = 0
    db.tenants.find_one({"id": "tc1"})
    db.tenants.find_one({"id": "tc1"})
    check(f"un cron lit à chaque fois ({reads['n']})", reads["n"] == 2)

    print("\n— ce qui n'est pas mémorisé —")
    tok = DC.begin(); reads["n"] = 0
    db.tenants.find_one({"id": {"$in": ["tc1"]}})
    db.tenants.find_one({"id": {"$in": ["tc1"]}})
    check(f"un filtre avec un opérateur passe toujours ({reads['n']})", reads["n"] == 2)
    DC.end(tok)
    check("les clients ne sont jamais mémorisés", "customers" not in DC.CACHED)
    check("…le scan les réécrit au milieu de sa requête",
          set(DC.CACHED) == {"tenants", "card_templates", "plan_settings",
                             # a shop's facts for Profil (2026-10-27): written in the background, never by the till
                             "brain_shop"})

    print("\n— la même enveloppe à chaque accès —")
    check("un patch posé sur la collection tient", db.tenants is db.tenants)

    type(db.tenants._real).find_one = real
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
