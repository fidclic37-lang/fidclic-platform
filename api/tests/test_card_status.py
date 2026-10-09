"""
Card active or deleted, and getting it back (user, 2026-10-09).

Run: cd api && /usr/local/bin/python3 tests/test_card_status.py
"""
import asyncio
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-status")
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
    import features.card_status as CS
    from services import card_owner as CO, mailer

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    sent = []
    mailer.ready = lambda: True
    mailer.send = lambda to, subject, html, text=None, to_name=None, reply_to=None: sent.append((to, subject, html)) or {"sent": True}

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Le Café", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    tok = lambda role: {"Authorization": "Bearer " + auth.create_access_token({"sub": f"{role}@x.fr", "role": role, "tenant_id": "t1"})}
    for role in ("business_owner", "manager", "staff"):
        db.users.insert_one({"email": f"{role}@x.fr", "role": role, "tenant_id": "t1"})
    O, ST = tok("business_owner"), tok("staff")
    db.customers.insert_many([
        {"id": "a", "tenant_id": "t1", "barcode_id": "FT-AAAA0001", "name": "Anna Petit", "phone": "0611111111",
         "email": "anna@exemple.fr", "visits": 3, "created_at": now},
        {"id": "b", "tenant_id": "t1", "barcode_id": "FT-BBBB0002", "name": "Bruno Roy", "phone": "0622222222",
         "visits": 5, "created_at": now, "card_deleted_at": now - dt.timedelta(days=2)},
        {"id": "c", "tenant_id": "t1", "barcode_id": "FT-CCCC0003", "name": "Clara Diaz", "phone": "0633333333",
         "email": "clara@exemple.fr", "visits": 7, "created_at": now, "wallet_removed_at": now - dt.timedelta(days=1)},
        {"id": "d", "tenant_id": "t1", "barcode_id": "FT-DDDD0004", "name": "Dina Kay", "phone": "0644444444",
         "visits": 2, "created_at": now, "wallet_removed_at": now - dt.timedelta(days=5),
         "card_claimed_at": now - dt.timedelta(days=4)},
    ])

    print("1. Le statut de la carte, dans Clients")
    rows = {r["id"]: r for r in http("GET", "/api/owner/clients/list?per_page=50", headers=O).json()["rows"]}
    check("Anna: Active", rows["a"]["card"]["state"] == "active")
    check("Bruno: Supprimée, with the date", rows["b"]["card"]["state"] == "deleted" and rows["b"]["card"]["at"])
    check("Clara: Retirée d'Apple Wallet", rows["c"]["card"]["label"] == "Retirée d'Apple Wallet")
    check("Dina, removed then opened again with her key: Active", rows["d"]["card"]["state"] == "active")
    ids = set(http("GET", "/api/owner/clients/ids?card=deleted", headers=O).json()["ids"])
    check("filter « Carte supprimée » → Bruno and Clara", ids == {"b", "c"})
    ids = set(http("GET", "/api/owner/clients/ids?card=active", headers=O).json()["ids"])
    check("filter « Carte active » → Anna and Dina", ids == {"a", "d"})
    csv = http("GET", "/api/owner/clients/export?card=deleted", headers=O).text
    check("the export says it too", "Carte" in csv.splitlines()[0] and "Supprimée" in csv)

    print("\n2. La cloche et le tableau de bord")
    bell = http("GET", "/api/owner/insights/alerts/multi-store", headers=O).json()["alerts"]
    titles = [a["title"] for a in bell if str(a.get("id", "")).startswith("card-lost:")]
    check(f"the bell: « Bruno R. a supprimé sa carte » and Clara's removal ({titles})",
          "Bruno R. a supprimé sa carte" in titles and "Clara D. a retiré sa carte d'Apple Wallet" in titles)
    home = http("GET", "/api/owner/home/overview", headers=O).json()
    check("the dashboard counts 2 lost cards in 30 days, linking to the filter",
          home.get("cards_lost", {}).get("count") == 2 and home["cards_lost"]["href"].endswith("card=deleted"))

    print("\n3. Récupérer la carte : QR en caisse")
    r = http("POST", "/api/owner/card-readd/find", headers=ST, json={"phone": "06 22 22 22 22"})
    check(f"staff find Bruno by phone on the Scan page ({r.status_code})", r.status_code == 200 and r.json()["id"] == "b")
    r = http("POST", "/api/owner/clients/b/card/readd", headers=ST, json={"channel": "qr"})
    link = r.json()
    check(f"staff get a QR link, 48 h ({r.status_code})", r.status_code == 200 and "/carte/recuperer/" in link["url"]
          and link["hours"] == 48)
    token = link["url"].rsplit("/", 1)[1]
    r = http("GET", f"/api/card-readd/{token}")
    check("the page shows the shop and a first name, nothing more",
          r.json() == {"business_name": "Le Café", "first_name": "Bruno", "expires_at": r.json()["expires_at"]})
    check("opening the page does not use the link", not db.card_readd_links.find_one({"token": token})["used_at"])
    r = http("POST", f"/api/card-readd/{token}")
    j = r.json()
    check(f"« Récupérer ma carte »: the card and its owner key ({r.status_code})",
          r.status_code == 200 and j["barcode_id"] == "FT-BBBB0002" and CO.valid("FT-BBBB0002", j["card_key"]))
    b = db.customers.find_one({"id": "b"})
    check("…the card is active again", not b.get("card_deleted_at") and CS.state_of(b)["state"] == "active")
    r = http("POST", f"/api/card-readd/{token}")
    check(f"used once — the second time is refused ({r.status_code})", r.status_code == 410 and "déjà été utilisé" in r.json()["detail"])

    print("\n4. Par e-mail : propriétaire, admin, manager")
    r = http("POST", "/api/owner/clients/c/card/readd", headers=ST, json={"channel": "email"})
    check(f"staff may not send the e-mail ({r.status_code})", r.status_code == 403)
    r = http("POST", "/api/owner/clients/c/card/readd", headers=O, json={"channel": "email"})
    check(f"the owner sends it to Clara ({r.status_code})", r.status_code == 200 and r.json().get("sent")
          and sent and sent[-1][0] == "clara@exemple.fr" and "/carte/recuperer/" in sent[-1][2])
    r = http("POST", "/api/owner/clients/b/card/readd", headers=tok("manager"), json={"channel": "email"})
    check(f"no e-mail on file: said plainly ({r.status_code})", r.status_code == 400 and "QR" in r.json()["detail"])
    tok_c = db.card_readd_links.find_one({"customer_id": "c", "channel": "email"})["token"]
    db.card_readd_links.update_one({"token": tok_c}, {"$set": {"expires_at": now - dt.timedelta(minutes=1)}})
    r = http("POST", f"/api/card-readd/{tok_c}")
    check(f"after 48 h the link is refused ({r.status_code})", r.status_code == 410 and "expiré" in r.json()["detail"])
    info = http("GET", "/api/owner/clients/c/card", headers=O).json()
    check("the fiche lists the links sent and their state", info["links"][0]["state"] == "expired" and info["can_email"])

    print("\n5. Le passage en caisse le signale")
    r = http("POST", "/api/owner/scan", headers=O, json={"barcode_id": "FT-CCCC0003", "amount_paid": 5})
    check(f"scanning Clara's number: the receipt knows her card is gone ({r.status_code})",
          r.status_code == 200 and r.json().get("card_state", {}).get("state") == "wallet_removed")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
