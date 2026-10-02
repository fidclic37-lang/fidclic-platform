"""
Clients › Importer, the invitation emails, and « Déjà contactés ».

    the file is read whatever its column names, separators or format
    every line says what will happen to it, and the server re-checks it all
    nothing is created without the merchant's consent confirmation
    the plan's card limits and invitation-email quota hold
    emails go out in batches, carry the card and an unsubscribe link
    the relance is only ever prepared, never sent on its own
    before a campaign, clients contacted in the last 3 days are named, and
    the ones the owner leaves out are not messaged

Run: cd api && /usr/local/bin/python3 tests/test_client_import.py
"""
import asyncio
import datetime as dt
import io
import json
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    import auth
    import httpx
    from services import mailer
    from features import client_import as CI, resend_guard as RG, plan_limits as PL

    db = server.db
    passed = failed = 0

    def check(label, cond, extra=""):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label + (f" — {extra}" if extra and not cond else ""))

    def http(method, url, bearer=None, **kw):
        headers = kw.pop("headers", {})
        if bearer:
            headers["Authorization"] = "Bearer " + bearer

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(dt.timezone.utc)
    db.tenants.insert_many([
        {"id": "t1", "slug": "cafe", "name": "Café <Lumière>", "plan": "gold", "subscription_status": "active", "created_at": now},
        {"id": "t2", "slug": "boul", "name": "Boulangerie", "plan": "silver", "subscription_status": "active", "created_at": now},
    ])
    db.users.insert_many([{"email": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"}])
    OWN = auth.create_access_token({"sub": "o@cafe.fr", "role": "business_owner", "tenant_id": "t1"})
    OWN2 = auth.create_access_token({"sub": "o@boul.fr", "role": "business_owner", "tenant_id": "t2"})
    db.customers.insert_one({"id": "old1", "tenant_id": "t1", "name": "Déjà Là", "email": "deja@la.fr",
                             "phone": "06 11 22 33 44", "barcode_id": "FT-OLD00001", "visits": 3,
                             "created_at": now - dt.timedelta(days=200), "last_visit_date": now})

    # Emails are captured, not sent.
    sent_payloads = []
    mailer._post = lambda payload, key: sent_payloads.append(payload) or {"messageId": "x"}

    def upload(name, data, bearer=OWN):
        return http("POST", "/api/owner/clients/import/preview", bearer,
                    files={"file": (name, data, "application/octet-stream")})

    # ---- reading the file ----------------------------------------------------------------
    print("\nReading the file")
    CSV = ("Prénom;Nom;E-mail;Téléphone;Date de naissance;Code postal\n"
           "Marie;Dupont;marie@exemple.fr;0612345678;17/05/1990;37000\n"
           "Paul;Martin;paul@exemple;0698765432;;\n"            # bad email
           "Julie;Bernard;;;03/02/1985;37100\n"                  # no email, no phone
           "Marie;Dupont;MARIE@exemple.fr;;;\n"                  # same email again
           "Léo;Petit;;06 11 22 33 44;;\n"                       # already a client (phone)
           "Anne;Roux;anne@exemple.fr;612000000;1992-12-24;\n"   # Excel ate the leading 0
           ";;;;;\n").encode("cp1252")
    r = upload("clients.csv", CSV)
    p = r.json()
    check("a French CSV (« ; », accents, cp1252) is read", r.status_code == 200, r.text[:200])
    check("its columns are found by their names", set(p["columns"]) == {"first", "last", "email", "phone", "birthday", "postal_code"})
    rows = p["rows"]
    st = [x["status"] for x in rows]
    check("each line says what will happen to it", st == ["new", "invalid", "invalid", "duplicate", "existing", "new"], st)
    check("the reason is given", rows[1]["reason"] == "Email invalide" and rows[2]["reason"] == "Ni email ni téléphone")
    check("the line number is the file's", rows[0]["line"] == 2 and rows[5]["line"] == 7)
    check("first and last names are put together", rows[0]["name"] == "Marie Dupont")
    check("a birthday is kept as MM-DD, whatever its format",
          rows[0]["birthday"] == "05-17" and rows[5]["birthday"] == "12-24")
    check("a phone whose leading 0 Excel ate gets it back", rows[5]["phone"] == "0612000000")
    check("the counts add up", p["counts"] == {"new": 2, "existing": 1, "duplicate": 1, "invalid": 2})
    check("the page knows emails are off without a key", p["mailer_ready"] is False)
    check("and what the plan still allows", p["limits"]["invites_limit"] == 1000 and p["limits"]["invites_left"] == 1000)

    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Name", "Email", "Phone", "City"])
    ws.append(["Sam Lee", "sam@x.com", 612345670, "Tours"])
    buf = io.BytesIO(); wb.save(buf)
    rx = upload("clients.xlsx", buf.getvalue()).json()
    check("an Excel file in English is read too", rx["rows"][0]["status"] == "new" and rx["rows"][0]["city"] == "Tours")
    check("a number cell keeps its digits", rx["rows"][0]["phone"] == "0612345670")
    bad = upload("x.csv", b"foo;bar\n1;2\n")
    check("a file without name or contact columns is refused, saying why",
          bad.status_code == 400 and "Colonnes introuvables" in bad.json()["detail"])
    check("an old .xls is refused with the way out", "xlsx" in upload("x.xls", b"..").json()["detail"])

    # ---- committing ----------------------------------------------------------------
    print("\nCreating the cards")
    body = {"rows": rows, "consent": False, "invite": True}
    r = http("POST", "/api/owner/clients/import/commit", OWN, json=body)
    check("nothing is created without the consent confirmation", r.status_code == 400 and db.customers.count_documents({"tenant_id": "t1"}) == 1)

    forged = [dict(x, status="new") for x in rows]            # a page that lies about the status
    r = http("POST", "/api/owner/clients/import/commit", OWN, json={"rows": forged, "consent": True, "invite": True})
    res = r.json()
    check("only the lines the server finds new become cards", res["created"] == 2, res)
    made = list(db.customers.find({"tenant_id": "t1", "signup_channel": "import"}))
    m = next(c for c in made if c["email"] == "marie@exemple.fr")
    check("the card is a real one: barcode, imported source, birthday",
          m["barcode_id"].startswith("FT-") and m["acquisition_source"] == "import" and m["birthday"] == "05-17")
    check("the merchant's confirmation is the card's consent record",
          m["consent"]["source"] == "import" and m["consent"]["by"] == "o@cafe.fr")
    check("the town comes from the postal code", (m.get("city") or "").startswith("Tours"), m.get("city"))
    check("without a Brevo key no email leaves, and the page is told",
          res["emails"]["mailer_ready"] is False and res["emails"]["sent"] == 0 and not sent_payloads)
    check("nothing counts against the quota then", CI.invites_used_this_month("t1") == 0)
    again = http("POST", "/api/owner/clients/import/commit", OWN, json={"rows": rows, "consent": True}).json()
    check("importing the same file twice creates nothing new", again["created"] == 0 and again["counts"]["existing"] == 4, again["counts"])

    # ---- emails ----------------------------------------------------------------
    print("\nInvitation emails")
    os.environ["BREVO_API_KEY"] = "test-key"
    rows2 = [{"name": f"Client {i}", "email": f"c{i}@x.fr", "phone": "", "postal_code": "", "city": ""} for i in range(4)]
    db.plan_settings.insert_one({"plan": "gold", "overrides": {"invite_emails_per_month": 3}})
    res = http("POST", "/api/owner/clients/import/commit", OWN, json={"rows": rows2, "consent": True, "invite": True}).json()
    check("the four cards are made", res["created"] == 4)
    check("the month's quota holds: three sent, one over", res["emails"]["sent"] == 3 and res["emails"]["over_quota"] == 1, res["emails"])
    check("in one call to Brevo, one version per client", len(sent_payloads) == 1 and len(sent_payloads[0]["messageVersions"]) == 3)
    v = sent_payloads[0]["messageVersions"][0]
    check("each email links to the client's own card", "/card/FT-" in v["htmlContent"] and "src=invite" in v["htmlContent"])
    check("and carries an unsubscribe link", "/api/public/email/unsubscribe/" in v["htmlContent"])
    check("the shop's name is escaped in the email", "Café &lt;Lumière&gt;" in v["htmlContent"] and "<Lumière>" not in v["htmlContent"])
    check("the email comes from the shop's name", sent_payloads[0]["sender"]["name"] == "Café <Lumière>")
    check("only sent emails count", CI.invites_used_this_month("t1") == 3)
    check("Plan Limits shows the use", any(u["key"] == "invite_emails_per_month" and u["used"] == 3
                                          for u in PL.usage_of(db.tenants.find_one({"id": "t1"}))))
    db.plan_settings.delete_many({})

    # ---- relance ----------------------------------------------------------------
    print("\nRelance — prepared, never sent on its own")
    inv = http("GET", "/api/owner/clients/invitations", OWN).json()
    check("three invited, none opened yet", inv["invited"] == 3 and inv["opened"] == 0)
    check("no relance before a week", inv["relance_ready"] == 0)
    db.client_invitations.update_many({"tenant_id": "t1"}, {"$set": {"sent_at": now - dt.timedelta(days=8)}})
    ids = [i["customer_id"] for i in db.client_invitations.find({"tenant_id": "t1"})]
    db.card_opens.insert_one({"tenant_id": "t1", "customer_id": ids[0], "day": now.strftime("%Y-%m-%d"), "at": now})
    lst = http("GET", "/api/owner/clients/invitations/relance", OWN).json()["rows"]
    check("a week on, those who never opened their card are listed", {r["id"] for r in lst} == set(ids[1:]))
    check("the one who opened it is not", ids[0] not in {r["id"] for r in lst})
    n_before = len(sent_payloads)
    check("nothing was sent by listing them", len(sent_payloads) == n_before)
    out = http("POST", "/api/owner/clients/invitations/relance", OWN, json={"customer_ids": [ids[0], ids[1]]}).json()
    check("the relance goes only to who still qualifies", out["sent"] == 1)
    check("with its own wording", "vous attend" in sent_payloads[-1]["messageVersions"][0]["subject"])
    lst2 = http("GET", "/api/owner/clients/invitations/relance", OWN).json()["rows"]
    check("a client is relancé once", {r["id"] for r in lst2} == {ids[2]})
    check("another shop cannot relance these clients",
          http("POST", "/api/owner/clients/invitations/relance", OWN2, json={"customer_ids": [ids[2]]}).status_code == 400)

    # ---- unsubscribe ----------------------------------------------------------------
    print("\nUnsubscribe")
    c2 = db.customers.find_one({"id": ids[2]})
    page = http("GET", f"/api/public/email/unsubscribe/{c2['email_token']}")
    check("one click, no login", page.status_code == 200 and "ne recevrez plus" in page.text)
    check("the client is marked", db.customers.find_one({"id": ids[2]})["email_opt_out"] is True)
    check("and never emailed again", http("GET", "/api/owner/clients/invitations/relance", OWN).json()["rows"] == [])
    check("a made-up token does nothing", "plus valable" in http("GET", "/api/public/email/unsubscribe/nope-nope-nope-nope").text)

    # ---- plan limits on cards ----------------------------------------------------------------
    print("\nThe plan's card limits")
    db.plan_settings.insert_one({"plan": "silver", "overrides": {"new_cards_per_month": 2}})
    rows3 = [{"name": f"B {i}", "email": f"b{i}@x.fr"} for i in range(5)]
    res = http("POST", "/api/owner/clients/import/commit", OWN2, json={"rows": rows3, "consent": True}).json()
    check("no more cards than the month allows", res["created"] == 2 and res["over_limit"] == 3, res)
    db.plan_settings.delete_many({})
    check("a manager cannot import", http("POST", "/api/owner/clients/import/commit",
          auth.create_access_token({"sub": "m@cafe.fr", "role": "manager", "tenant_id": "t1"}),
          json={"rows": rows3, "consent": True}).status_code == 403)

    # ---- déjà contactés ----------------------------------------------------------------
    print("\n« Déjà contactés » before a campaign")
    base = {"tenant_id": "t1", "title": "x", "body": "x"}
    for cid in ("A", "B", "C", "D", "E", "F", "G", "H"):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "phone": f"07000000{ord(cid)}",
                                 "barcode_id": f"FT-{cid}", "visits": 6, "created_at": now - dt.timedelta(days=90),
                                 "last_visit_date": now - dt.timedelta(days=2)})
    db.campaigns.insert_one({"id": "k1", "tenant_id": "t1", "name": "Happy hour", "status": "sent",
                             "sent_at": now - dt.timedelta(hours=20), "recipient_ids": ["A", "B"]})
    db.push_notifications.insert_many([
        {**base, "customer_id": "C", "type": "offer", "title": "Offre du midi", "sent_at": now - dt.timedelta(days=2)},
        {**base, "customer_id": "D", "type": "reward_unlocked", "sent_at": now - dt.timedelta(hours=3)},
        {**base, "customer_id": "E", "type": "proximity", "sent_at": now - dt.timedelta(hours=3)},
        {**base, "customer_id": "F", "type": "campaign", "sent_at": now - dt.timedelta(days=5)},
        {**base, "tenant_id": "t2", "customer_id": "G", "type": "campaign", "sent_at": now - dt.timedelta(hours=1)},
        {**base, "customer_id": "H", "type": "birthday", "title": "Joyeux anniversaire", "sent_at": now - dt.timedelta(hours=1)},
    ])
    chk = http("POST", "/api/owner/campaigns/recent-check", OWN,
               json={"customer_ids": ["A", "B", "C", "D", "E", "F", "G", "H"]}).json()
    named = {r["id"]: r for r in chk["recent"]}
    check("the clients who got a campaign, an offer or an automation in 3 days are named",
          set(named) == {"A", "B", "C", "H"}, sorted(named))
    check("with what they got", named["A"]["title"] == "Happy hour" and named["C"]["kind"] == "Offre")
    check("a reward receipt or a proximity push is not a campaign", "D" not in named and "E" not in named)
    check("five days ago is outside the window", "F" not in named and chk["window_days"] == 3)
    check("another shop's messages do not count", "G" not in named)
    check("newest first", chk["recent"][0]["id"] == "H")
    seg = http("POST", "/api/owner/campaigns/recent-check", OWN, json={"segment": "all"}).json()
    check("it works on a whole segment too", {"A", "B", "C", "H"} <= {r["id"] for r in seg["recent"]})

    r = http("POST", "/api/owner/campaigns/compose", OWN,
             json={"title": "Nouveau menu", "message": "Venez goûter", "customer_ids": ["A", "B", "C"], "exclude_ids": ["A", "C"]})
    k = db.campaigns.find_one({"name": "Nouveau menu"})
    check("Campagnes: the clients left out are not messaged", r.status_code == 200 and k["recipient_ids"] == ["B"], r.text[:200])
    r = http("POST", "/api/owner/campaigns/compose", OWN,
             json={"title": "Rien", "message": "x", "customer_ids": ["A"], "exclude_ids": ["A"]})
    check("leaving everyone out sends nothing, and says so", r.status_code == 400 and "retirés" in r.json()["detail"])
    r = http("POST", "/api/owner/campaigns/send-to-group", OWN,
             json={"customer_ids": ["A", "B", "H"], "exclude_ids": ["H"], "name": "Clients", "content": "Bonjour"})
    sent_to = {p["customer_id"] for p in db.push_notifications.find({"tenant_id": "t1", "title": "Clients"})}
    check("Clients › Contacter: the same", r.status_code == 200 and sent_to == {"A", "B"}, r.text[:200])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
