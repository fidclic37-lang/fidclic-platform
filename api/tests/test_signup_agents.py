"""
Liens d'inscription par employé (user, 2026-10-16).

The user's first worry, in their words: « ek employee k qr/link se kisi
customer ne signup kiya, and woh dusre employee k hisse mein dikha rha, ya
dikha hi nhi rha, ya update hi nhi ho rha ». So this file is mostly about the
ways attribution could go wrong:

  1. the words                 unique, never a channel, never an establishment,
                               two Maries, accents, renaming, archiving
  2. the signup                the right employee, every time; an unknown or an
                               archived word brings NO employee, never another
  3. what the shop then sees   Clients, the source lists, the leaderboard
  4. the establishment         the employee's own, whatever the address said
  5. who may do what           the permission, and the employee's own link
  6. the e-mails               only the chosen ones, only those with an address

Run: cd api && /usr/local/bin/python3 tests/test_signup_agents.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-signup-agents")
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
    from features import signup_agents as SA
    from features import clients_page as CP
    from services import sources as SRC

    db = server.db
    now = datetime.now(timezone.utc)

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_one({
        "id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "is_active": True,
        "subscription_status": "active",
        "branches": [{"id": "lib", "name": "ROYAL TRIM LIBERTÉ", "slug": "liberte", "is_main": True},
                     {"id": "pal", "name": "ROYAL TRIM PALISSY", "slug": "palissy"}]})
    db.users.insert_one({"email": "o@royal.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    OWNER = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@royal.fr", "role": "business_owner", "tenant_id": "t1"})}

    def add(name, **kw):
        return http("POST", "/api/owner/signup-agents", headers=OWNER, json={"name": name, **kw})

    def agent_list():
        return http("GET", "/api/owner/signup-agents", headers=OWNER).json()["agents"]

    def agents():                               # by name — distinct names only
        return {a["name"]: a for a in agent_list()}

    def board():                                # by word: two employees may share a name
        return {r["word"]: r for r in http("GET", "/api/owner/signup-agents", headers=OWNER).json()["leaderboard"]}

    def by_word(w):
        return next(a for a in agent_list() if a["word"] == w)

    phones = {}

    def signup(word, name, store="liberte"):
        """The address always says Liberté — so « the employee's own
        establishment wins » is really tested, not merely assumed."""
        phones[name] = phones.get(name) or f"07{str(10000000 + len(phones))[:8]}"
        body = {"name": name, "phone": phones[name], "postal_code": "37000",
                "birthday": "1990-05-04", "accepted_terms": True, "consent": True,
                "acquisition_source": word, "store": store}
        return http("POST", "/api/join/royal-trim", json=body)

    # ---------------------------------------------------------------- 1
    print("\n1. Le mot du lien — unique, et jamais celui d'autre chose")
    r = add("Marie Dupont", email="marie@royal.fr", store_id="pal")
    check(f"un employé est créé ({r.status_code})", r.status_code == 200)
    A = agents()
    check("son lien est /inscription/royal-trim/palissy/e-marie-dupont",
          A["Marie Dupont"]["link"].endswith("/inscription/royal-trim/palissy/e-marie-dupont"))
    add("Marie Dupont", store_id="lib")
    words = sorted(a["word"] for a in agent_list() if a["name"] == "Marie Dupont")
    check(f"deux Marie, deux mots différents ({words})", words == ["e-marie-dupont", "e-marie-dupont-2"])
    add("Joël Lefèvre", store_id="lib")
    check("les accents deviennent un mot simple (e-joel-lefevre)",
          agents()["Joël Lefèvre"]["word"] == "e-joel-lefevre")
    add("insta", store_id="lib")
    check("un employé nommé « insta » ne vole pas le lien du canal Instagram",
          agents()["insta"]["word"] == "e-insta")
    add("palissy", store_id="lib")
    check("ni celui d'un établissement", agents()["palissy"]["word"] == "e-palissy")
    add("Sans Établissement")
    sans = by_word("e-sans-etablissement")
    check("un employé créé sans établissement prend le principal — sinon son QR "
          "tomberait sur « Choisissez votre établissement »",
          sans["store_id"] == "lib" and sans["link"].endswith("/royal-trim/liberte/e-sans-etablissement"))
    check("un nom vide est refusé (400)", add("   ").status_code == 400)
    check("une adresse e-mail invalide est refusée (400)",
          add("Paul", email="pas-une-adresse").status_code == 400)
    check("deux employés ne peuvent pas partager une adresse (409)",
          add("Autre Marie", email="marie@royal.fr").status_code == 409)

    # ---------------------------------------------------------------- 2
    print("\n2. L'inscription — le bon employé, à chaque fois")
    marie = by_word("e-marie-dupont")
    autre = by_word("e-marie-dupont-2")
    r = signup("e-marie-dupont", "Client Un")
    check(f"un client s'inscrit par son lien ({r.status_code})", r.status_code == 200)
    bc = r.json()["barcode_id"]
    c1 = db.customers.find_one({"barcode_id": bc}, {"_id": 0})
    check("la source du client est cet employé, par son identifiant",
          c1["acquisition_source"] == f"agent:{marie['id']}")
    check("…et pas celle de l'autre Marie", c1["acquisition_source"] != f"agent:{autre['id']}")
    signup("e-marie-dupont-2", "Client Deux")
    c2 = db.customers.find_one({"name": "Client Deux"}, {"_id": 0})
    check("le deuxième lien donne le deuxième employé",
          c2["acquisition_source"] == f"agent:{autre['id']}")
    r = signup("e-personne", "Client Trois")
    c3 = db.customers.find_one({"name": "Client Trois"}, {"_id": 0})
    check(f"un mot qui n'existe pas n'amène AUCUN employé ({c3.get('acquisition_source')})",
          r.status_code == 200 and not c3.get("acquisition_source"))
    r = signup(f"agent:{marie['id']}", "Client Quatre")
    c4 = db.customers.find_one({"name": "Client Quatre"}, {"_id": 0})
    check("un identifiant envoyé à la main est accepté s'il est de ce commerce",
          c4["acquisition_source"] == f"agent:{marie['id']}")
    db.tenants.insert_one({"id": "t2", "slug": "autre-shop", "name": "Autre", "is_active": True,
                           "subscription_status": "active"})
    db.signup_agents.insert_one({"id": "foreign01", "tenant_id": "t2", "name": "Voisin", "word": "e-voisin",
                                 "email": None, "phone": None, "store_id": None, "archived_at": None,
                                 "created_at": now})
    signup("agent:foreign01", "Client Cinq")
    c5 = db.customers.find_one({"name": "Client Cinq"}, {"_id": 0})
    check("l'employé d'un AUTRE commerce est ignoré", not c5.get("acquisition_source"))
    signup("e-voisin", "Client Six")
    c6 = db.customers.find_one({"name": "Client Six"}, {"_id": 0})
    check("…son mot aussi", not c6.get("acquisition_source"))
    check("un canal reste un canal", signup("insta", "Client Sept").status_code == 200
          and db.customers.find_one({"name": "Client Sept"})["acquisition_source"] == "instagram")

    # ---------------------------------------------------------------- 3
    print("\n3. Ce que le commerce voit ensuite")
    check("le client porte le nom de l'employé comme source",
          SRC.label(SRC.key_of(c1)) == "Marie Dupont")
    bb = CP._brought_by(c1)
    check(f"Clients › les 3 points : « Apporté par {bb and bb['name']} »",
          bb and bb["name"] == "Marie Dupont" and bb["id"] == marie["id"] and bb["at"])
    check("un client venu sans employé n'affiche rien", CP._brought_by(c3) is None)
    counts = {}
    for c in db.customers.find({"tenant_id": "t1"}, {"_id": 0, "acquisition_source": 1}):
        k = SRC.key_of(c)
        counts[k] = counts.get(k, 0) + 1
    rows = {x["key"]: x for x in SRC.ordered(counts)}
    check(f"les employés sont des sources à part entière, une par employé "
          f"({[(x['label'], x['count']) for x in SRC.ordered(counts)]})",
          rows[f"agent:{marie['id']}"]["count"] == 2
          and rows[f"agent:{marie['id']}"]["label"] == "Marie Dupont"
          and rows[f"agent:{autre['id']}"]["count"] == 1
          and rows["instagram"]["count"] == 1)
    check("…et deux employés du même nom restent deux sources distinctes",
          rows[f"agent:{marie['id']}"]["key"] != rows[f"agent:{autre['id']}"]["key"])
    b = board()
    check(f"le classement : Marie 2, l'autre Marie 1 ({b['e-marie-dupont']['total']})",
          b["e-marie-dupont"]["total"] == 2 and b["e-marie-dupont"]["month"] == 2
          and b["e-marie-dupont"]["rank"] == 1 and b["e-marie-dupont-2"]["total"] == 1)
    db.customers.update_one({"barcode_id": bc}, {"$set": {"total_amount_paid": 48.5}})
    check("le CA suit les clients de l'employé", board()["e-marie-dupont"]["revenue"] == 48.5)
    db.customers.update_one({"name": "Client Un"}, {"$set": {"created_at": now - timedelta(days=70)}})
    b = board()
    check(f"un client d'il y a deux mois sort du mois, pas du total "
          f"({b['e-marie-dupont']['month']}/{b['e-marie-dupont']['total']})",
          b["e-marie-dupont"]["month"] == 1 and b["e-marie-dupont"]["total"] == 2)
    db.customers.update_one({"name": "Client Quatre"}, {"$set": {"deleted_at": now}})
    check("un client effacé ne compte plus", board()["e-marie-dupont"]["total"] == 1)
    db.customers.update_one({"name": "Client Quatre"}, {"$set": {"deleted_at": None}})

    # renaming must follow everywhere, at once
    http("PUT", f"/api/owner/signup-agents/{marie['id']}", headers=OWNER, json={"name": "Marie D."})
    check("renommer l'employée renomme la source partout", SRC.label(SRC.key_of(c1)) == "Marie D.")
    check("…sans changer son lien (les QR déjà imprimés)",
          agents()["Marie D."]["word"] == "e-marie-dupont")
    check("…et sans changer le client en base",
          db.customers.find_one({"barcode_id": bc})["acquisition_source"] == f"agent:{marie['id']}")

    # ---------------------------------------------------------------- 4
    print("\n4. L'établissement — celui de l'employé")
    check("le client de Marie (Palissy) est un client de Palissy", c1.get("branch_id") == "pal")
    signup("e-marie-dupont", "Client Huit")
    c8 = db.customers.find_one({"name": "Client Huit"}, {"_id": 0})
    check("même si l'adresse dit un autre établissement", c8.get("branch_id") == "pal")
    check("le client de l'autre Marie (Liberté) est à Liberté",
          db.customers.find_one({"name": "Client Deux"}).get("branch_id") == "lib")

    # ---------------------------------------------------------------- 5
    print("\n5. Archiver — le lien s'arrête, l'histoire reste")
    r = http("DELETE", f"/api/owner/signup-agents/{marie['id']}", headers=OWNER)
    check(f"l'employée est archivée, pas effacée ({r.status_code})",
          r.status_code == 200 and db.signup_agents.find_one({"id": marie["id"]})["archived_at"])
    signup("e-marie-dupont", "Client Neuf")
    c9 = db.customers.find_one({"name": "Client Neuf"}, {"_id": 0})
    check("son lien n'amène plus personne — et surtout pas quelqu'un d'autre",
          not c9.get("acquisition_source"))
    check("ses anciens clients gardent son nom", SRC.label(SRC.key_of(c1)) == "Marie D.")
    check("elle reste dans le classement, marquée archivée", board()["e-marie-dupont"]["archived"] is True)
    add("Nouvelle Marie Dupont")
    check("son mot n'est jamais réattribué",
          agents()["Nouvelle Marie Dupont"]["word"] == "e-nouvelle-marie-dupont")
    http("PUT", f"/api/owner/signup-agents/{marie['id']}", headers=OWNER, json={"archived": False})
    signup("e-marie-dupont", "Client Dix")
    check("désarchivée, son lien remarche",
          db.customers.find_one({"name": "Client Dix"})["acquisition_source"] == f"agent:{marie['id']}")

    # ---------------------------------------------------------------- 6
    print("\n6. Qui peut quoi")
    db.users.insert_one({"email": "staff@royal.fr", "role": "staff", "tenant_id": "t1", "active": True,
                         "email_lower": "staff@royal.fr"})
    STAFF = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "staff@royal.fr", "role": "staff", "tenant_id": "t1"})}
    check("un employé sans le droit « edit » ne crée pas de lien (403)",
          http("POST", "/api/owner/signup-agents", headers=STAFF,
               json={"name": "X"}).status_code in (403,))
    check("…ni n'en archive (403)",
          http("DELETE", f"/api/owner/signup-agents/{marie['id']}", headers=STAFF).status_code == 403)
    http("PUT", f"/api/owner/signup-agents/{agents()['Marie D.']['id']}", headers=OWNER,
         json={"email": "staff@royal.fr"})
    mine = http("GET", "/api/owner/signup-agents", headers=STAFF).json()
    check("il voit SON lien (reconnu à son adresse) et tout le classement",
          mine["mine"] == marie["id"] and len(mine["leaderboard"]) >= 2 and mine["can_edit"] is False)
    db.users.insert_one({"email": "o2@autre.fr", "role": "business_owner", "tenant_id": "t2", "active": True})
    OTHER = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o2@autre.fr", "role": "business_owner", "tenant_id": "t2"})}
    check("le propriétaire d'un autre commerce ne voit pas ces employés",
          all(a["name"] != "Marie D." for a in http("GET", "/api/owner/signup-agents",
                                                    headers=OTHER).json()["agents"]))
    check("…et ne peut pas archiver les nôtres (404)",
          http("DELETE", f"/api/owner/signup-agents/{marie['id']}", headers=OTHER).status_code == 404)
    check("sans jeton : refusé", http("GET", "/api/owner/signup-agents").status_code in (401, 403))
    from features import role_perms as RP
    check("la permission est une ligne du tableau des rôles",
          "employee_links" in RP.PAGE_KEYS and RP.page_of("/api/owner/signup-agents") == "employee_links")
    check("un administrateur l'a par défaut, un employé non",
          RP.DEFAULT_TEMPLATES["administrateur"]["employee_links"] == "edit"
          and RP.DEFAULT_TEMPLATES["staff"]["employee_links"] == "none")

    # ---------------------------------------------------------------- 7
    print("\n7. Envoyer les liens par e-mail")
    SENT = []
    from services import mailer
    mailer.send = lambda **kw: SENT.append(kw) or {"messageId": "m1"}
    sans = agents()["Joël Lefèvre"]["id"]
    avec = agents()["Marie D."]["id"]
    r = http("POST", "/api/owner/signup-agents/send", headers=OWNER, json={"agent_ids": [avec, sans]})
    d = r.json()
    check(f"un envoi pour celui qui a une adresse, l'autre est signalé ({d['sent']}, {d['no_email']})",
          d["sent"] == 1 and len(d["no_email"]) == 1 and d["no_email"][0]["name"] == "Joël Lefèvre")
    check("l'e-mail porte SON lien et dit à quoi il sert",
          "e-marie-dupont" in SENT[-1]["html"] and "classement" in SENT[-1]["html"])
    check("…et prévient de ne pas le partager", "ne le partagez pas" in SENT[-1]["html"])
    check("la date d'envoi est retenue", agents()["Marie D."]["sent_at"])
    check("sans personne choisie : 400",
          http("POST", "/api/owner/signup-agents/send", headers=OWNER, json={"agent_ids": []}).status_code == 400)
    check("un employé sans le droit n'envoie rien (403)",
          http("POST", "/api/owner/signup-agents/send", headers=STAFF,
               json={"agent_ids": [avec]}).status_code == 403)
    SENT.clear()
    http("POST", "/api/owner/signup-agents/send", headers=OWNER, json={"agent_ids": ["inconnu"]})
    check("un identifiant inconnu n'envoie rien", SENT == [])

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
