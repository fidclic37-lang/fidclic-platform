"""
« LTV totale » et « Chiffre d'affaires » ne comptent pas les mêmes gens
(user, 2026-10-21 : sur 30 jours le CA dépassait la LTV de toujours).

Ce n'est pas une erreur : un client supprimé quitte la LTV — il n'est plus
dans aucun compte (store_scope.customer_filter, décidé le 2026-10-16) — mais
son argent reste dans le chiffre d'affaires, parce que le commerce l'a bien
encaissé. Restait que rien ne le disait à l'écran.

Run: cd api && /usr/local/bin/python3 tests/test_ltv_deleted.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ltv-deleted")
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
    import auth
    import httpx
    from features import analyses as A

    db = server.db
    now = datetime.now(timezone.utc)

    def http(url):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                         base_url="http://test") as ac:
                return await ac.get(url, headers=H)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Le Shop", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@shop.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@shop.fr", "role": "business_owner", "tenant_id": "t1"})}

    def client(cid, spent, deleted=None):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid, "barcode_id": f"FT-{cid}",
                                 "visits": 1, "total_amount_paid": spent, "deleted_at": deleted,
                                 "created_at": now - timedelta(days=5),
                                 "last_visit_date": now - timedelta(days=2)})
        db.visits.insert_one({"id": f"v{cid}", "tenant_id": "t1", "customer_id": cid,
                              "amount_paid": spent, "visit_time": now - timedelta(days=2)})

    client("c1", 200.0)
    client("c2", 100.0)
    client("c3", 303.0, deleted=now)          # supprimé depuis

    def strip():
        d = http("/api/owner/analyses?tab=vue&days=30").json()["data"]
        return {x["key"]: x for x in d["strip"]}

    print("\n1. Les deux chiffres, et pourquoi ils diffèrent")
    s = strip()
    check(f"CA : les trois visites, supprimé compris ({s['revenue']['value']} €)",
          s["revenue"]["value"] == 603.0)
    check(f"LTV totale : les clients encore là ({s['ltv_total']['value']} €)",
          s["ltv_total"]["value"] == 300.0)
    check("et oui, le CA d'une période peut dépasser la LTV de toujours",
          s["revenue"]["value"] > s["ltv_total"]["value"])

    print("\n2. La ligne sous « LTV totale » le dit")
    hint = s["ltv_total"]["hint"]
    check(f"elle annonce les 303 € partis ({hint})", "303" in hint and "supprimés" in hint)
    check("sans perdre ce qu'elle disait déjà", "depuis leur inscription" in hint)
    check("la somme se recompose : 300 + 303 = 603",
          s["ltv_total"]["value"] + 303.0 == s["revenue"]["value"])

    print("\n3. Sans client supprimé, rien ne s'ajoute")
    db.customers.update_one({"id": "c3"}, {"$set": {"deleted_at": None}})
    s2 = strip()
    check(f"la ligne redevient simple ({s2['ltv_total']['hint']})",
          "supprimés" not in s2["ltv_total"]["hint"])
    check("et les deux chiffres se rejoignent",
          s2["ltv_total"]["value"] == s2["revenue"]["value"] == 603.0)
    db.customers.update_one({"id": "c3"}, {"$set": {"deleted_at": now}})

    print("\n4. L'euro écrit à la française")
    check(f"303 € ({A._fr_eur(303)!r})", A._fr_eur(303) == "303\u00a0€")
    check(f"12 450 € avec son espace fine ({A._fr_eur(12450)!r})",
          A._fr_eur(12450) == "12\u202f450\u00a0€")
    check("zéro n'est jamais annoncé", A.Reader is not None and strip()["ltv_total"]["hint"])

    print("\n5. L'aide (le « ? ») dit la même chose")
    help_js = io.open(os.path.join(os.path.dirname(__file__), "..", "..", "src", "lib", "metricHelp.js"),
                      encoding="utf-8").read()
    ltv_help = help_js.split("ltv_total: {", 1)[1].split("},", 1)[0]
    check("« LTV totale » explique que les supprimés n'y sont plus",
          "supprimés" in ltv_help and "chiffre d'affaires" in ltv_help)
    check("…et que le CA d'une période peut donc la dépasser", "dépasser la LTV" in ltv_help)
    rev_help = help_js.split("revenue: {", 1)[1].split("},", 1)[0]
    check("« Chiffre d'affaires » le dit de son côté aussi", "supprimés" in rev_help)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


import io  # noqa: E402 — used by the help-text check above

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
