"""
Super admin › « Centre de support » and the merchant's « Mes demandes »,
end to end over HTTP, as the two browsers call them:
a merchant opens a ticket with a screenshot → the team sees it (counters,
tabs, search, filters, priority first) → replies, notes, mentions →
the merchant reads (double tick) and answers → statuses, urgent, resolved →
rating and satisfaction; tickets opened by the team; files (types, size,
who may download); saved replies, tags, bulk actions, exports; old tickets;
the old public form; who may do what.

Run: cd api && /usr/local/bin/python3 tests/test_support_center.py
"""
import asyncio
import csv
import datetime as dt
import io
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from features import support_center as SC
    from services import mailer

    db = server.db
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def http(method, url, token=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers={"Authorization": "Bearer " + token} if token else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    tok = lambda email, role, tid=None: auth.create_access_token({"sub": email, "role": role, **({"tenant_id": tid} if tid else {})})   # noqa: E731
    for ch in ("_support_send_smtp", "_support_send_resend", "_support_send_formsubmit"):      # no real email from a test
        setattr(server, ch, lambda subject, message, ticket: (False, "not_configured"))
    mails = []
    mailer.send = lambda to, subject, html, text=None, to_name=None: (mails.append((to, subject, text)), {"sent": True})[1]

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "cb", "slug": "comptoir", "name": "Le Comptoir du Burger", "sector": "restaurant", "city": "Tours", "plan": "vip", "phone": "06 12 34 56 78",
         "subscription_status": "active", "subscription_started_at": now - dt.timedelta(days=200), "created_at": now - dt.timedelta(days=300)},
        {"id": "ac", "slug": "atelier", "name": "L'Atelier Coiffure", "sector": "coiffure", "city": "Tours", "plan": "silver",
         "subscription_status": "active", "created_at": now - dt.timedelta(days=90)},
    ])
    db.users.insert_many([
        {"email": "meriem@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B."},
        {"email": "sam@fidclic.com", "role": "fidclic_team", "platform_role": "support", "first_name": "Sam", "last_name": "L."},
        {"email": "ana@fidclic.com", "role": "fidclic_team", "platform_role": "analyste", "first_name": "Ana", "last_name": "K."},
        {"email": "contact@comptoirduburger.fr", "role": "business_owner", "tenant_id": "cb", "first_name": "Karim", "last_name": "B."},
        {"email": "staff@comptoirduburger.fr", "role": "staff", "tenant_id": "cb"},
        {"email": "owner@atelier.fr", "role": "business_owner", "tenant_id": "ac", "first_name": "Lina"},
    ])
    db.customers.insert_many([{"id": f"c{i}", "tenant_id": "cb", "created_at": now - dt.timedelta(days=20)} for i in range(6)])
    db.campaigns.insert_many([{"id": f"k{i}", "tenant_id": "cb"} for i in range(2)])
    BOSS, SAM, ANA = tok("meriem@fidclic.com", "super_admin"), tok("sam@fidclic.com", "fidclic_team"), tok("ana@fidclic.com", "fidclic_team")
    CB, CBSTAFF, AC = (tok("contact@comptoirduburger.fr", "business_owner", "cb"), tok("staff@comptoirduburger.fr", "staff", "cb"),
                       tok("owner@atelier.fr", "business_owner", "ac"))
    PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 2048

    print("\nLe commerçant ouvre une demande")
    up = http("POST", "/api/owner/support/files", CB, files={"file": ("Capture ecran.png", PNG, "image/png")}).json()
    check("screenshot uploaded", up.get("name") == "Capture ecran.png" and up["size"] == len(PNG))
    r = http("POST", "/api/owner/support/tickets", CB, json={"subject": "Carte sur Apple Wallet", "category": "wallet", "attachments": [up["id"]],
                                                             "body": "Bonjour,\n\nj'ai un problème avec ma carte de fidélité sur Apple Wallet."})
    T1 = r.json().get("id")
    t = db.support_tickets.find_one({"id": T1})
    check("ticket created: nouveau, unread for the team", r.status_code == 200 and t["status"] == "nouveau" and t["unread_team"] == 1)
    check("Pro AI business → haute priorité, pinned first", t["priority"] == "haute" and t["pin"] == 1)
    check("the team's bell gets it", db.support_alerts.count_documents({"ticket_id": T1, "audience": "team", "kind": "new"}) == 1)
    check("the file belongs to the first message", db.support_files.find_one({"id": up["id"]})["message_id"] is not None)
    check("staff of the business cannot open tickets", http("POST", "/api/owner/support/tickets", CBSTAFF, json={"subject": "x", "body": "y"}).status_code == 403)
    r2 = http("POST", "/api/owner/support/tickets", AC, json={"subject": "Modifier ma carte", "body": "Est-ce que je peux modifier ma carte ?", "category": "carte"})
    T2 = r2.json()["id"]
    check("Starter business → normale", db.support_tickets.find_one({"id": T2})["priority"] == "normale")
    check("empty message refused", http("POST", "/api/owner/support/tickets", AC, json={"subject": "x", "body": "  "}).status_code == 400)

    print("\nBoîte de réception")
    lst = http("GET", "/api/admin/support/tickets", BOSS).json()
    check("both tickets, priority one first", [x["id"] for x in lst["rows"]] == [T1, T2])
    row = lst["rows"][0]
    check("row: commerce, plan, preview, status, unread",
          row["commerce"]["name"] == "Le Comptoir du Burger" and row["commerce"]["plan"]["label"] == "Pro AI"
          and row["preview"].startswith("Bonjour") and row["status_label"] == "Nouveau" and row["unread"] == 1)
    check("tabs counted", lst["tabs"] == {"tous": 2, "nouveaux": 2, "en_cours": 0})
    check("search finds words inside messages", [x["id"] for x in http("GET", "/api/admin/support/tickets?q=modifier ma carte", BOSS).json()["rows"]] == [T2])
    check("search by commerce name", [x["id"] for x in http("GET", "/api/admin/support/tickets?q=comptoir", BOSS).json()["rows"]] == [T1])
    check("filter by category", [x["id"] for x in http("GET", "/api/admin/support/tickets?category=wallet", BOSS).json()["rows"]] == [T1])
    check("filter by plan", [x["id"] for x in http("GET", "/api/admin/support/tickets?plan=silver", BOSS).json()["rows"]] == [T2])
    check("filter unread", len(http("GET", "/api/admin/support/tickets?unread=1", BOSS).json()["rows"]) == 2)
    check("assignees: team members who can see support only", {m["email"] for m in lst["options"]["team"]} == {"meriem@fidclic.com", "sam@fidclic.com"})
    check("an analyste (no support right) is refused", http("GET", "/api/admin/support/tickets", ANA).status_code == 403)
    check("a merchant is refused", http("GET", "/api/admin/support/tickets", CB).status_code == 403)
    ov = http("GET", "/api/admin/support/overview", BOSS).json()
    k = {x["key"]: x for x in ov["kpis"]}
    check("cards: 2 nouveaux, +2 this month", k["nouveau"]["value"] == 2 and k["nouveau"]["period"] == 2 and ov["unread"] == 2)

    print("\nLe ticket ouvert")
    d = http("GET", f"/api/admin/support/tickets/{T1}", BOSS).json()
    check("opening reads it", db.support_tickets.find_one({"id": T1})["unread_team"] == 0)
    check("the thread with the screenshot", d["messages"][0]["attachments"][0]["name"] == "Capture ecran.png")
    c = d["commerce"]
    check("commerce panel: phone, owner email, city, plan, since",
          c["phone"] == "06 12 34 56 78" and c["email"] == "contact@comptoirduburger.fr" and c["city"] == "Tours"
          and c["plan"]["label"] == "Pro AI" and c["plan_since"])
    check("panel figures: 6 clients, 2 campaigns, no rating yet", c["clients"] == 6 and c["campaigns"] == 2 and c["satisfaction"] is None)
    check("status « Client … » from the Commerces page rules", c["status_label"].startswith("Client "))
    check("the team downloads the screenshot", http("GET", f"/api/support/files/{up['id']}", BOSS).content == PNG)

    print("\nRéponse, note interne, mention")
    r = http("POST", f"/api/admin/support/tickets/{T1}/messages", BOSS, json={"body": "Bonjour,\n\nMerci pour votre message. Est-ce aussi sur Google Wallet ?"})
    t = db.support_tickets.find_one({"id": T1})
    check("reply: en attente, merchant unread, assigned to who answered, first response",
          r.status_code == 200 and t["status"] == "en_attente" and t["unread_merchant"] == 1 and t["assigned_to"] == "meriem@fidclic.com" and t["first_response_at"])
    check("…by email to the merchant", mails and mails[-1][0] == "contact@comptoirduburger.fr" and "Nouvelle réponse" in mails[-1][1])
    check("…and in the merchant's bell", any(a["title"].startswith("Nouvelle réponse") for a in http("GET", "/api/owner/support/alerts", CB).json()["alerts"]))
    nup = http("POST", "/api/admin/support/files", BOSS, files={"file": ("logs.txt", b"trace", "text/plain")}).json()
    before = len(mails)
    http("POST", f"/api/admin/support/tickets/{T1}/messages", BOSS, json={"body": "@Sam L. peux-tu vérifier le certificat ?", "kind": "note",
                                                                         "mentions": ["sam@fidclic.com"], "attachments": [nup["id"]]})
    check("a note emails nobody", len(mails) == before)
    check("the mentioned teammate is told", any("mentionné" in a["title"] for a in http("GET", "/api/admin/support/alerts", SAM).json()["alerts"]))
    check("…not the others", not any("mentionné" in a["title"] for a in http("GET", "/api/admin/support/alerts", BOSS).json()["alerts"]))
    check("a note's file is never served to the merchant", http("GET", f"/api/support/files/{nup['id']}", CB).status_code == 404)
    check("nor is another business's file", http("GET", f"/api/support/files/{up['id']}", AC).status_code == 404)

    print("\nCôté commerçant")
    mine = http("GET", "/api/owner/support/tickets", CB).json()["rows"]
    check("Mes demandes: only theirs, « Réponse reçue », 1 unread", [x["id"] for x in mine] == [T1] and mine[0]["status_label"] == "Réponse reçue" and mine[0]["unread"] == 1)
    th = http("GET", f"/api/owner/support/tickets/{T1}", CB).json()
    check("the thread has no internal note", [m["kind"] for m in th["messages"]] == ["message", "message"] and "@Sam" not in str(th))
    check("another business cannot open it", http("GET", f"/api/owner/support/tickets/{T1}", AC).status_code == 404)
    check("the merchant downloads their own screenshot", http("GET", f"/api/support/files/{up['id']}", CB).status_code == 200)
    d = http("GET", f"/api/admin/support/tickets/{T1}", BOSS).json()
    team_msg = [m for m in d["messages"] if m["author_type"] == "team" and m["kind"] == "message"][0]
    check("double tick: the merchant has read the answer", team_msg["read"] is True)
    check("notes and history stay on the team's side", {m["kind"] for m in d["messages"]} >= {"note", "event"})
    up2 = http("POST", "/api/owner/support/files", CB, files={"file": ("wallet.png", PNG, "image/png")}).json()
    http("POST", f"/api/owner/support/tickets/{T1}/messages", CB, json={"body": "D'accord, voici la capture. C'est uniquement sur Apple Wallet.", "attachments": [up2["id"]]})
    t = db.support_tickets.find_one({"id": T1})
    check("merchant answer: back to « En cours », unread for the team", t["status"] == "en_cours" and t["unread_team"] == 1 and t["last_from"] == "merchant")
    check("…the assignee's bell", any("Nouveau message" in a["title"] for a in http("GET", "/api/admin/support/alerts", BOSS).json()["alerts"]))
    check("a file can't be attached twice", http("POST", f"/api/owner/support/tickets/{T1}/messages", CB, json={"body": "x", "attachments": [up2["id"]]}).status_code == 400)

    print("\nStatut, priorité, catégorie, assignation, tags")
    r = http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"status": "urgent", "category": "carte", "assigned_to": "sam@fidclic.com",
                                                                      "tags": ["Apple Wallet", "Carte fidélité", "Technique", "Urgent", "Certificat"]})
    t = db.support_tickets.find_one({"id": T1})
    check("urgent, carte fidélité, assigned to Sam", r.status_code == 200 and t["status"] == "urgent" and t["category"] == "carte" and t["assigned_to"] == "sam@fidclic.com")
    http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"add_tags": ["Google Wallet"]})
    http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"remove_tags": ["Certificat"]})
    http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"add_tags": ["Certificat"]})
    tg = db.support_tickets.find_one({"id": T1})["tags"]
    check("one tag added or removed at a time keeps the others", "Google Wallet" in tg and "Certificat" in tg and "Apple Wallet" in tg and len(tg) == 6)
    http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"remove_tags": ["Google Wallet"]})
    check("a new tag joins the managed list", "Certificat" in [x["label"] for x in http("GET", "/api/admin/support/tags", BOSS).json()["tags"]])
    check("Sam is told", any("assigné" in a["title"] for a in http("GET", "/api/admin/support/alerts", SAM).json()["alerts"]))
    check("history written", db.support_messages.count_documents({"ticket_id": T1, "kind": "event", "meta.field": "status", "meta.to": "urgent"}) == 1)
    check("assigning someone without support refused", http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"assigned_to": "ana@fidclic.com"}).status_code == 400)
    check("unknown status refused", http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"status": "bof"}).status_code == 400)
    http("POST", f"/api/admin/support/tickets/{T1}/messages", SAM, json={"body": "On regarde le certificat Apple."})
    check("urgent stays urgent after a reply", db.support_tickets.find_one({"id": T1})["status"] == "urgent")
    check("merchant sees urgent as « En cours »", http("GET", "/api/owner/support/tickets", CB).json()["rows"][0]["status"] == "en_cours")
    check("urgent card", {x["key"]: x for x in http("GET", "/api/admin/support/overview", BOSS).json()["kpis"]}["urgent"]["value"] == 1)
    check("filter urgents tab", [x["id"] for x in http("GET", "/api/admin/support/tickets?tab=urgents", BOSS).json()["rows"]] == [T1])

    print("\nRésolu et note")
    check("rating refused before it is resolved", http("POST", f"/api/owner/support/tickets/{T1}/rating", CB, json={"stars": 5}).status_code == 400)
    before = len(mails)
    http("PATCH", f"/api/admin/support/tickets/{T1}", BOSS, json={"status": "resolu"})
    t = db.support_tickets.find_one({"id": T1})
    check("resolved: date, unpinned, email", t["status"] == "resolu" and t["resolved_at"] and t["pin"] == 0 and len(mails) == before + 1)
    check("the merchant is asked to rate", http("GET", "/api/owner/support/tickets", CB).json()["rows"][0]["can_rate"] is True)
    check("stars between 1 and 5", http("POST", f"/api/owner/support/tickets/{T1}/rating", CB, json={"stars": 9}).status_code == 422)
    http("POST", f"/api/owner/support/tickets/{T1}/rating", CB, json={"stars": 4, "comment": "Rapide, merci"})
    check("rated", db.support_tickets.find_one({"id": T1})["rating"]["stars"] == 4)
    check("satisfaction in the commerce panel", http("GET", f"/api/admin/support/tickets/{T1}", BOSS).json()["commerce"]["satisfaction"] == 4.0)
    http("POST", f"/api/owner/support/tickets/{T1}/messages", CB, json={"body": "En fait ça recommence…"})
    t = db.support_tickets.find_one({"id": T1})
    check("a new message reopens it (rated again later)", t["status"] == "en_cours" and t["rating"] is None and t["resolved_at"] is None)

    print("\nTicket créé par l'équipe")
    r = http("POST", "/api/admin/support/tickets", SAM, json={"tenant_id": "ac", "subject": "Suite à votre appel", "category": "facturation",
                                                             "body": "Bonjour Lina, comme convenu au téléphone, voici le récapitulatif."})
    T3 = r.json()["id"]
    t = db.support_tickets.find_one({"id": T3})
    check("visible to the merchant, waiting for them, assigned to its author",
          r.status_code == 200 and t["status"] == "en_attente" and t["assigned_to"] == "sam@fidclic.com"
          and T3 in [x["id"] for x in http("GET", "/api/owner/support/tickets", AC).json()["rows"]])
    check("…emailed to the owner", mails[-1][0] == "owner@atelier.fr")
    r = http("POST", "/api/admin/support/tickets", BOSS, json={"tenant_id": "ac", "subject": "Suivi interne", "body": "À rappeler jeudi", "kind": "note"})
    T4 = r.json()["id"]
    check("a note-only ticket: en cours, the merchant sees no message",
          db.support_tickets.find_one({"id": T4})["status"] == "en_cours" and http("GET", f"/api/owner/support/tickets/{T4}", AC).json()["messages"] == [])
    check("a commerce is required", http("POST", "/api/admin/support/tickets", BOSS, json={"subject": "x", "body": "y"}).status_code == 400)
    check("commerce picker", [x["name"] for x in http("GET", "/api/admin/support/commerces?q=atel", BOSS).json()["rows"]] == ["L'Atelier Coiffure"])

    print("\nFichiers")
    check("too big refused (10 MB)", http("POST", "/api/owner/support/files", CB, files={"file": ("big.png", b"0" * (10 * 1024 * 1024 + 1), "image/png")}).status_code == 413)
    check("unknown type refused", http("POST", "/api/owner/support/files", CB, files={"file": ("x.exe", b"MZ", "application/x-msdownload")}).status_code == 415)
    check("PDF accepted", http("POST", "/api/owner/support/files", CB, files={"file": ("facture.pdf", b"%PDF-1.4", "application/pdf")}).status_code == 200)
    check("someone else's pending file can't be attached",
          http("POST", f"/api/admin/support/tickets/{T1}/messages", BOSS, json={"body": "x", "attachments": [db.support_files.find_one({"name": "facture.pdf"})["id"]]}).status_code == 400)
    check("a file needs a signed-in user", http("GET", f"/api/support/files/{up['id']}").status_code in (401, 403))

    print("\nRéponses enregistrées, tags, actions groupées, exports")
    reps = http("GET", "/api/admin/support/replies", BOSS).json()["rows"]
    check("three ready-made replies", len(reps) == 3)
    rid = http("POST", "/api/admin/support/replies", BOSS, json={"title": "Relance", "body": "Bonjour {prenom}, avez-vous pu tester ?"}).json()["id"]
    http("PUT", f"/api/admin/support/replies/{rid}", BOSS, json={"title": "Relance J+2", "body": "Bonjour {prenom}, avez-vous pu tester ?"})
    check("saved reply added and renamed", any(x["title"] == "Relance J+2" for x in http("GET", "/api/admin/support/replies", BOSS).json()["rows"]))
    http("DELETE", f"/api/admin/support/replies/{rid}", BOSS)
    check("…and deleted", len(http("GET", "/api/admin/support/replies", BOSS).json()["rows"]) == 3)
    tags = http("GET", "/api/admin/support/tags", BOSS).json()["tags"]
    tags = [x for x in tags if x["label"] != "Technique"] + [{"label": "Wallet Apple", "color": "rose"}]
    tags = [x for x in tags if x["label"] != "Apple Wallet"]
    http("PUT", "/api/admin/support/tags", BOSS, json={"tags": tags, "renamed": {"Apple Wallet": "Wallet Apple"}})
    t = db.support_tickets.find_one({"id": T1})
    check("renamed tag follows, deleted tag leaves the ticket", "Wallet Apple" in t["tags"] and "Apple Wallet" not in t["tags"] and "Technique" not in t["tags"])
    http("POST", "/api/admin/support/tickets/bulk", BOSS, json={"ids": [T2, T3], "status": "resolu"})
    check("bulk resolve", all(db.support_tickets.find_one({"id": x})["status"] == "resolu" for x in (T2, T3)))
    http("POST", f"/api/admin/support/tickets/{T2}/unread", BOSS)
    check("mark as unread", db.support_tickets.find_one({"id": T2})["unread_team"] == 1)
    ex = http("GET", "/api/admin/support/export?status=resolu", BOSS)
    rows = list(csv.reader(io.StringIO(ex.content.decode("utf-8-sig")), delimiter=";"))
    check("export: filtered tickets with French headers", ex.status_code == 200 and rows[0][0] == "Commerce" and len(rows) == 3)
    check("export of ticked tickets", len(list(csv.reader(io.StringIO(http("GET", f"/api/admin/support/export?ids={T1}", BOSS).content.decode("utf-8-sig")), delimiter=";"))) == 2)
    th = http("GET", f"/api/admin/support/tickets/{T1}/export", BOSS).content.decode("utf-8-sig")
    check("conversation export has messages, notes and history", "Note interne" in th and "Historique" in th and "Capture ecran.png" in th)
    check("an analyste cannot export", http("GET", "/api/admin/support/export", ANA).status_code == 403)

    print("\nAnciens tickets et ancien formulaire")
    db.support_tickets.insert_one({"id": "old1", "subject": "Ancien", "message": "Bonjour, ancien ticket", "from_email": "x@y.fr",
                                   "status": "open", "priority": "prioritaire", "created_at": now - dt.timedelta(days=40)})
    SC._migrate()
    o = db.support_tickets.find_one({"id": "old1"})
    check("old ticket brought to the new shape", o["v"] == 2 and o["status"] == "nouveau" and o["priority"] == "haute"
          and db.support_messages.find_one({"ticket_id": "old1"})["body"] == "Bonjour, ancien ticket")
    check("…only once", SC._migrate() == 0)
    r = http("POST", "/api/support/contact", json={"subject": "Question", "message": "Bonjour", "from_email": "owner@atelier.fr"})
    nt = db.support_tickets.find_one({"id": r.json()["ticket_id"]})
    check("the public form opens a conversation for the right business", nt["tenant_id"] == "ac" and nt["status"] == "nouveau" and nt["source"] == "formulaire")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
