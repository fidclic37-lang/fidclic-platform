"""
« Cette carte, qui l'a supprimée ? » (user, 2026-10-23).

Le bandeau du tableau de bord annonçait « 1 carte retirée », et la colonne
Carte disait « Supprimée » — sans dire par qui. Or DEUX personnes peuvent
supprimer une carte depuis la page de la carte : le client sur son téléphone
(il a la clé) ET un compte du commerce (« Voir sa carte » du tableau de bord).
Apple et Google, eux, ne peuvent venir que du téléphone du client.

Chaque perte et chaque récupération laisse maintenant une ligne dans
l'Historique, avec l'auteur, et la colonne Carte le dit aussi.

Run: cd api && /usr/local/bin/python3 tests/test_card_lost_log.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-lost")
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
    from features import card_status as CS
    from features import activity_history as AH
    from services import card_owner as CO

    db = server.db
    now = datetime.now(timezone.utc)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                         base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Le Shop", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@shop.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    OWNER = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@shop.fr", "role": "business_owner", "tenant_id": "t1"})}

    def client(cid, bc):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": cid.title(), "barcode_id": bc,
                                 "visits": 1, "total_amount_paid": 10.0, "deleted_at": None,
                                 "created_at": now, "pass_issued": True})

    def events(cid=None):
        q = {"tenant_id": "t1", "kind": "card_state"}
        if cid:
            q["customer_id"] = cid
        return [f"{e.get('text')} · {e.get('by')}" for e in db.customer_changes.find(q, {"_id": 0})]

    def state(cid):
        return CS.state_of(db.customers.find_one({"id": cid}, {"_id": 0}))

    # ------------------------------------------------------------------ 1
    print("\n1. Le client supprime sa carte depuis son téléphone")
    client("marie", "FT-MARIE001")
    r = http("DELETE", "/api/card/FT-MARIE001", headers={"X-Card-Key": CO.key_for("FT-MARIE001")})
    check(f"la suppression passe ({r.status_code})", r.status_code == 200)
    st = state("marie")
    check(f"la colonne Carte dit « Supprimée · {st.get('by_label')} »",
          st["state"] == "deleted" and st["by"] == "client" and st["by_label"] == "par le client")
    check(f"et l'Historique le note ({events('marie')})",
          events("marie") == ["Carte supprimée depuis la page de la carte · le client"])

    # ------------------------------------------------------------------ 2
    print("\n2. Le commerce supprime la carte depuis « Voir sa carte »")
    client("paul", "FT-PAUL0001")
    r = http("DELETE", "/api/card/FT-PAUL0001", headers=OWNER)
    check(f"le commerce le peut aussi ({r.status_code})", r.status_code == 200)
    st = state("paul")
    check(f"mais la carte dit QUI : « {st.get('by_label')} »",
          st["by"] == "o@shop.fr" and st["by_label"] == "par o@shop.fr")
    check(f"l'Historique nomme le compte ({events('paul')})",
          events("paul") == ["Carte supprimée depuis la page de la carte · o@shop.fr"])
    check("les deux suppressions ne se confondent pas",
          state("marie")["by"] != state("paul")["by"])

    # ------------------------------------------------------------------ 3
    print("\n3. Apple Wallet : seulement le téléphone du client")
    client("lina", "FT-LINA0001")
    db.pass_registrations.insert_one({"device_id": "d1", "serial": "FT-LINA0001"})
    import features.wallet_passes as WP
    WP._check_pass_auth = lambda *a, **k: None
    r = http("DELETE", "/api/passes/v1/devices/d1/registrations/pass.fidclic/FT-LINA0001")
    check(f"Apple nous le dit ({r.status_code})", r.status_code == 200)
    check(f"état « Retirée d'Apple Wallet » ({state('lina')['state']})",
          state("lina")["state"] == "wallet_removed")
    check(f"et l'Historique dit le client ({events('lina')})",
          events("lina") == ["Carte retirée d'Apple Wallet · le client"])

    # ------------------------------------------------------------------ 4
    print("\n4. Récupérée : la ligne le dit aussi")
    r = http("POST", "/api/owner/clients/marie/card/readd", headers=OWNER, json={"channel": "qr"})
    url = (r.json() or {}).get("url") or ""
    token = url.rsplit("/", 1)[-1] if url else None
    check(f"le commerce obtient un lien de récupération ({r.status_code})", bool(token))
    used = http("POST", f"/api/card-readd/{token}") if token else None
    check(f"le téléphone qui l'ouvre reprend la carte ({used and used.status_code})",
          used is not None and used.status_code == 200)
    check(f"la carte est de nouveau active ({state('marie')['state']})",
          state("marie")["state"] == "active")
    check(f"et la récupération est au journal ({events('marie')[-1]})",
          events("marie")[-1] == "Carte récupérée sur un téléphone · le client")

    # ------------------------------------------------------------------ 5
    print("\n5. Dans l'Historique du commerce")
    check("« Carte du client » est une activité connue",
          "card_state" in AH.ACTIONS and AH.ACTIONS["card_state"]["tone"] == "red")
    check("elle est dans l'onglet « Modifications de la carte »",
          "card_state" in AH.TAB_ACTIONS["card"])
    check("…et dans « Activité des clients », car elle concerne UN client",
          "card_state" in AH.TAB_ACTIONS["clients"] and "card_state" in AH.TAB_ACTIONS["all"])
    feed = http("GET", "/api/owner/history/activity?tab=card&per_page=50", headers=OWNER).json()
    rows = [x.get("detail") or "" for x in (feed.get("rows") or feed.get("items") or [])]
    check(f"le commerce voit les quatre lignes ({len(rows)})",
          sum(1 for x in rows if "Carte " in x) >= 4)
    check("et chacune nomme son auteur",
          all(("le client" in x or "@" in x) for x in rows if "Carte " in x))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
