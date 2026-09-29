"""
CRM de prospection — import from files (no LLM), automatic stages from
FidClic's own businesses, no duplicates, stages, tasks, overview, the
commercial role and the team.

Run: cd api && /usr/local/bin/python3 tests/test_crm.py
"""
import asyncio
import datetime as dt
import io
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    import auth
    from fastapi import HTTPException, UploadFile
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

    def guard(token, roles):
        try:
            asyncio.get_event_loop().run_until_complete(auth.require_role(roles)(token_data=token)); return 200
        except HTTPException as e:
            return e.status_code

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    db.users.insert_one({"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B."})
    # FidClic's own businesses: one on trial, one paying, one gone.
    db.tenants.insert_many([
        {"id": "t1", "name": "Café Lumière", "postal_code": "37000", "city": "Tours", "phone": "06 23 45 67 89",
         "subscription_status": "trialing", "created_at": now - dt.timedelta(days=5)},
        {"id": "t2", "name": "The Barber Club", "siret": "12345678900012", "subscription_status": "active",
         "created_at": now - dt.timedelta(days=200)},
        {"id": "t3", "name": "Fit Gym", "subscription_status": "canceled", "created_at": now - dt.timedelta(days=90)},
    ])

    def upload(name, text):
        f = UploadFile(filename=name, file=io.BytesIO(text.encode() if isinstance(text, str) else text))
        return asyncio.get_event_loop().run_until_complete(C.import_preview(file=f, token_data=ADMIN))

    print("\nImport — preview, then commit")
    csv_text = ("Nom du commerce;Secteur;Ville;Code postal;Contact;Téléphone;Email;Statut\n"
                "Café Lumière;Café / Salon de thé;Tours;37000;Thomas D.;06 23 45 67 89;thomas@cafelumiere.fr;\n"
                "The Barber Club;Barbershop;Tours;37000;Karim A.;07 11 22 33 44;;\n"
                "Chicken Street;Restauration rapide;Tours;37000;Yassine K.;06 12 34 56 78;;à contacter\n")
    prev = upload("prospects.csv", csv_text)
    by = {r["name"]: r for r in prev["rows"]}
    check("three businesses read from the CSV", prev["total"] == 3)
    check("a business on its free trial is recognised → En essai", by["Café Lumière"]["stage"] == "essai"
          and by["Café Lumière"]["tenant_id"] == "t1")
    check("a new business keeps the file's status", by["Chicken Street"]["stage"] == "a_contacter")
    check("nothing written by a preview", db.crm_prospects.count_documents({"name": "Chicken Street"}) == 0)
    res = C.import_commit(C.ImportIn(rows=prev["rows"], filename="prospects.csv", assign_to="boss@fidclic.com"), token_data=ADMIN)
    check("committed", res["created"] + res["updated"] == 3)
    cs = db.crm_prospects.find_one({"name": "Chicken Street"})
    check("… at its stage, assigned, with its history", cs["stage"] == "a_contacter" and cs["assigned_to"] == "boss@fidclic.com"
          and db.crm_activities.count_documents({"prospect_id": cs["id"]}) >= 2)

    print("\nFidClic's own businesses set their stage")
    C.sync_tenants()
    stage = lambda n: db.crm_prospects.find_one({"name": n})["stage"]
    check("trial → En essai", stage("Café Lumière") == "essai")
    check("paying → Signé", stage("The Barber Club") == "signe")
    check("cancelled → Perdu, « Abonnement résilié »", stage("Fit Gym") == "perdu"
          and db.crm_prospects.find_one({"name": "Fit Gym"})["lost_reason"] == "Abonnement résilié")
    check("never twice the same business", db.crm_prospects.count_documents({"name": "Café Lumière"}) == 1
          and db.crm_prospects.count_documents({}) == 4)
    C.sync_tenants()
    check("syncing again changes nothing", db.crm_prospects.count_documents({}) == 4)
    db.tenants.update_one({"id": "t1"}, {"$set": {"subscription_status": "active"}})
    C.sync_tenants()
    check("the trial becomes a subscription → Signé, on its own", stage("Café Lumière") == "signe")
    lum = db.crm_prospects.find_one({"name": "Café Lumière"})
    check("a FidClic business's stage cannot be set by hand",
          refused(lambda: C.set_stage(lum["id"], C.StageIn(stage="essai"), token_data=ADMIN), 409))
    check("the old signing date is kept, not « today »",
          C._entered("signe", now - dt.timedelta(days=30), now + dt.timedelta(seconds=5)) == 1)   # only Café Lumière now

    print("\nFree text and PDF")
    md = "## Salon Élégance\n- Gérant: Sophie L.\n- sophie@elegance.fr\n- 06 98 76 54 32\n- Coiffure, 37100 Tours\n"
    prev = upload("liste.md", md)
    check("a Markdown list → a business with its contact", prev["rows"][0]["name"] == "Salon Élégance"
          and prev["rows"][0]["email"] == "sophie@elegance.fr" and prev["rows"][0]["sector"] == "Coiffure / Beauté")
    from reportlab.pdfgen import canvas
    buf = io.BytesIO(); cv = canvas.Canvas(buf)
    for i, line in enumerate(["Maison Gourmet", "Boulangerie artisanale", "Pierre M. 06 55 44 33 22", "3 rue Colbert, 37000 Tours"]):
        cv.drawString(72, 750 - i * 16, line)
    cv.showPage(); cv.save()
    prev = upload("liste.pdf", buf.getvalue())
    check("a PDF → the same", prev["rows"][0]["name"] == "Maison Gourmet" and prev["rows"][0]["phone"] == "06 55 44 33 22"
          and prev["rows"][0]["postal_code"] == "37000")
    check("an unknown format is refused", refused(lambda: upload("x.docx", "a"), 400))
    check("a file with nothing recognisable says so", refused(lambda: upload("vide.txt", "bonjour\nmerci"), 422))

    print("\nProspects, stages, notes")
    p = C.add_prospect(C.ProspectIn(name="Zen & You", sector="Bien-être", city="Tours", phone="06 66 77 88 99", source="google"), token_data=ADMIN)
    check("added by hand", p["stage"] == "nouveau" and p["source_label"] == "Recherche Google")
    check("a duplicate is refused", refused(lambda: C.add_prospect(C.ProspectIn(name="Zen & You", phone="0666778899"), token_data=ADMIN), 409))
    C.set_stage(p["id"], C.StageIn(stage="rdv"), token_data=ADMIN)
    check("lost needs its reason", refused(lambda: C.set_stage(p["id"], C.StageIn(stage="perdu"), token_data=ADMIN), 400))
    C.add_note(p["id"], C.NoteIn(text="Intéressée, rappeler lundi"), token_data=ADMIN)
    d = C.get_prospect(p["id"], token_data=ADMIN)
    check("its history shows the stage and the note", any(a["type"] == "stage" for a in d["activities"]) and d["notes"])
    lst = C.list_prospects(q="zen", token_data=ADMIN)
    check("search", lst["total"] == 1 and lst["rows"][0]["stage_label"] == "Rendez-vous")
    check("filter by stage", C.list_prospects(stage="signe", token_data=ADMIN)["total"] == 2)

    print("\nTasks")
    t = C.add_task(C.TaskIn(title="Appeler Zen & You", type="appel", priority="haute", prospect_id=p["id"],
                            due_at=(now + dt.timedelta(hours=1)).isoformat()), token_data=ADMIN)
    check("created, shown as the prospect's next action", C.get_prospect(p["id"], token_data=ADMIN)["next_action"]["label"] == "Appeler Zen & You")
    late = C.add_task(C.TaskIn(title="Relancer", due_at=(now - dt.timedelta(days=1)).isoformat()), token_data=ADMIN)
    check("an overdue task reads « en retard »", late["status"] == "en_retard")
    C.edit_task(t["id"], C.TaskIn(status="terminee"), token_data=ADMIN)
    check("done, logged on the prospect", any(a["type"] == "task_done" for a in C.get_prospect(p["id"], token_data=ADMIN)["activities"]))

    print("\nOverview")
    C.set_goal(C.GoalIn(target=150), token_data=ADMIN)
    o = C.overview(token_data=ADMIN)
    cards = {c["key"]: c for c in o["cards"]}
    check("counted from the CRM", cards["total"]["value"] == 5 and cards["signe"]["value"] == 2 and cards["rdv"]["value"] == 1)
    check("the month's objective", o["goal"]["target"] == 150 and o["goal"]["signed"] >= 1)
    check("sources, sectors, cities, funnel", o["sources"] and o["sectors"] and o["cities"] and len(o["funnel"]) == 7)
    check("lost reasons counted", {r["label"]: r["count"] for r in o["lost"]["reasons"]}["Abonnement résilié"] == 1)

    print("\nExport")
    body = C.export(token_data=ADMIN).body.decode("utf-8")
    check("CSV for Excel with every prospect", body.startswith("﻿") and body.count("\n") == 6 and "Zen & You" in body)

    print("\nThe sales team")
    cred = C.add_member(C.MemberIn(email="sofia@fidclic.com", first_name="Sofia", last_name="R."), token_data=ADMIN)["credentials"]
    check("a commercial account, credentials shown once", cred["email"] == "sofia@fidclic.com" and len(cred["password"]) >= 10)
    SOFIA = TokenData(email="sofia@fidclic.com", role="commercial", tenant_id=None)
    check("a commercial opens the CRM", guard(SOFIA, C.CRM) == 200)
    check("… not the rest of the super admin", guard(SOFIA, ["super_admin"]) == 403)
    check("… nor the team", guard(SOFIA, C.ADMIN) == 403)
    C.edit_prospect(p["id"], C.ProspectIn(assigned_to="sofia@fidclic.com"), token_data=ADMIN)
    check("prospects can be assigned to them", C.list_prospects(assigned="sofia@fidclic.com", token_data=SOFIA)["total"] == 1)
    C.member_status("sofia@fidclic.com", C.ActiveIn(active=False), token_data=ADMIN)
    check("switched off: cannot sign in", refused(lambda: server.login(server.LoginRequest(email="sofia@fidclic.com", password=cred["password"]),
                                                                       server.Response(), None), 403))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
