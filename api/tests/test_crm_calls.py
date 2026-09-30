"""
CRM › Appels — logging calls, planned calls, the figures, recordings and
the phone call-log import.

Run: cd api && /usr/local/bin/python3 tests/test_crm_calls.py
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
    from fastapi import HTTPException, UploadFile
    from models import TokenData
    from features import crm as C
    from features import crm_calls as K

    db = server.db
    C.init(db)
    K.init(db)
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

    def run(coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    ADMIN = TokenData(email="boss@fidclic.com", role="super_admin", tenant_id=None)
    SOFIA = TokenData(email="sofia@fidclic.com", role="commercial", tenant_id=None)
    now = dt.datetime.now(dt.timezone.utc)
    db.users.insert_many([{"email": "boss@fidclic.com", "role": "super_admin", "first_name": "Meriem", "last_name": "B."},
                          {"email": "sofia@fidclic.com", "role": "commercial", "first_name": "Sofia", "last_name": "R."}])
    db.tenants.insert_one({"id": "t1", "name": "The Barber Club", "subscription_status": "active", "created_at": now})
    zinc = C.create({"name": "Le Petit Zinc", "phone": "06 23 45 67 89", "city": "Tours", "sector": "Restaurant",
                     "contact_name": "Thomas D."}, "boss@fidclic.com")
    paul = C.create({"name": "Boulangerie Paul", "phone": "+33 7 11 22 33 44", "city": "Blois", "sector": "Boulangerie"},
                    "boss@fidclic.com")
    arts = C.create({"name": "Café des Arts", "phone": "02 38 00 00 04", "city": "Orléans", "sector": "Café"}, "boss@fidclic.com")
    C.sync_tenants()
    barber = db.crm_prospects.find_one({"tenant_id": "t1"})

    print("\nLogging a call")
    check("a call needs its business", refused(lambda: K.add_call(K.CallIn(result="interesse"), token_data=ADMIN), 400))
    check("a done call needs its result", refused(lambda: K.add_call(K.CallIn(prospect_id=zinc["id"]), token_data=ADMIN), 400))
    c1 = K.add_call(K.CallIn(prospect_id=zinc["id"], result="interesse", duration_sec=134, notes="Très intéressé"), token_data=ADMIN)
    check("saved with duration and number", c1["duration"] == "2 min 14" and c1["number"] == "06 23 45 67 89")
    check("a reached prospect moves to « Contacté »", db.crm_prospects.find_one({"id": zinc["id"]})["stage"] == "contacte")
    check("the call is in the prospect's history",
          db.crm_activities.find_one({"prospect_id": zinc["id"], "type": "call"})["text"].startswith("Appel — Intéressé"))
    K.add_call(K.CallIn(prospect_id=paul["id"], result="sans_reponse"), token_data=SOFIA)
    check("no answer does not move the stage", db.crm_prospects.find_one({"id": paul["id"]})["stage"] == "nouveau")
    K.add_call(K.CallIn(prospect_id=zinc["id"], result="rdv_obtenu", duration_sec=300), token_data=SOFIA)
    check("a meeting moves it to « Rendez-vous »", db.crm_prospects.find_one({"id": zinc["id"]})["stage"] == "rdv")
    K.add_call(K.CallIn(prospect_id=zinc["id"], result="interesse", duration_sec=60), token_data=ADMIN)
    check("never backwards", db.crm_prospects.find_one({"id": zinc["id"]})["stage"] == "rdv")
    K.add_call(K.CallIn(prospect_id=barber["id"], result="rdv_obtenu", duration_sec=60), token_data=ADMIN)
    check("a business on FidClic keeps its own stage", db.crm_prospects.find_one({"id": barber["id"]})["stage"] == "signe")

    print("\nPlanned calls")
    check("a planned call must be in the future", refused(lambda: K.add_call(
        K.CallIn(prospect_id=arts["id"], status="planifie", at=(now - dt.timedelta(days=1)).isoformat()), token_data=ADMIN), 400))
    pl = K.add_call(K.CallIn(prospect_id=arts["id"], status="planifie", at=(now + dt.timedelta(days=1)).isoformat()), token_data=ADMIN)
    task = db.crm_tasks.find_one({"id": pl["task_id"]})
    check("it is also a task, so it shows in the calendar", task and task["type"] == "appel")
    check("completing it needs a result", refused(lambda: K.edit_call(pl["id"], K.CallIn(status="termine"), token_data=ADMIN), 400))
    done = K.edit_call(pl["id"], K.CallIn(result="a_relancer", duration_sec=45), token_data=ADMIN)
    check("noting the result completes it", done["status"] == "termine" and done["result"] == "a_relancer")
    check("…and closes its task", db.crm_tasks.find_one({"id": pl["task_id"]})["status"] == "terminee")
    pl2 = K.add_call(K.CallIn(prospect_id=paul["id"], status="planifie", at=(now + dt.timedelta(hours=3)).isoformat()), token_data=ADMIN)
    same = K.add_call(K.CallIn(prospect_id=paul["id"], result="interesse", duration_sec=30), token_data=ADMIN)
    check("calling a business with a call planned today completes that one", same["id"] == pl2["id"]
          and db.crm_tasks.find_one({"id": pl2["task_id"]})["status"] == "terminee")

    print("\nFigures")
    lst = K.list_calls(token_data=ADMIN)
    check("tab counts", lst["counts"] == {"all": 7, "effectues": 7, "reponses": 6, "rdv": 2, "sans_reponse": 1})
    check("tab filter", K.list_calls(tab="rdv", token_data=ADMIN)["total"] == 2)
    check("search by business", K.list_calls(q="zinc", token_data=ADMIN)["total"] == 3)
    check("filter by city", K.list_calls(city="Blois", token_data=ADMIN)["total"] == 2)
    check("filter by who called", K.list_calls(assigned="sofia@fidclic.com", token_data=ADMIN)["total"] == 2)
    sm = K.calls_summary(token_data=ADMIN)
    cards = {c["key"]: c["value"] for c in sm["cards"]}
    check("five cards", cards == {"total": 7, "effectues": 7, "reponses": 6, "rdv": 2, "sans_reponse": 1})
    check("results breakdown", {r["key"]: r["count"] for r in sm["results"]}["interesse"] == 3)
    check("per person", {r["label"]: r["count"] for r in sm["by_user"]} == {"Meriem B.": 5, "Sofia R.": 2})
    check("today in the 7-day chart", sm["per_day"][-1]["effectues"] == 7 and sm["per_day"][-1]["reponses"] == 6)
    detail = K.get_call(c1["id"], token_data=ADMIN)
    check("detail: history of that business", len(detail["history"]) == 3 and detail["contact"] == "Thomas D.")

    print("\nRecording")
    bad = UploadFile(filename="notes.pdf", file=io.BytesIO(b"x"))
    check("audio only", refused(lambda: run(K.upload_recording(c1["id"], bad, token_data=ADMIN)), 400))
    run(K.upload_recording(c1["id"], UploadFile(filename="appel.m4a", file=io.BytesIO(b"AUDIO")), token_data=ADMIN))
    check("stored and flagged", K.list_calls(q="zinc", token_data=ADMIN)["rows"][-1]["has_recording"] or
          any(r["has_recording"] for r in K.list_calls(q="zinc", token_data=ADMIN)["rows"]))
    check("played back", K.get_recording(c1["id"], token_data=ADMIN).body == b"AUDIO")
    K.delete_recording(c1["id"], token_data=ADMIN)
    check("removed", refused(lambda: K.get_recording(c1["id"], token_data=ADMIN), 404))

    print("\nPhone call log import")
    csv_log = ("Numéro;Date;Durée;Type\n"
               "06 23 45 67 89;28/09/2026 11:02;2:14;Sortant\n"
               "0711223344;28/09/2026 10:30;0;sortant\n"
               "0711223344;28/09/2026 12:00;0;Manqué\n"
               "0999999999;28/09/2026 10:30;65;sortant\n")
    pv = run(K.import_calls_preview(UploadFile(filename="journal.csv", file=io.BytesIO(csv_log.encode())), token_data=ADMIN))
    check("numbers matched to prospects, others left out", len(pv["rows"]) == 3 and pv["unknown"] == 1)
    check("+33 and spaces don't matter", {r["prospect"] for r in pv["rows"]} == {"Le Petit Zinc", "Boulangerie Paul"})
    check("0 s → sans réponse, a missed call from them → rappel demandé, else à qualifier",
          sorted(r["result"] for r in pv["rows"]) == ["a_qualifier", "rappel_demande", "sans_reponse"])
    res = K.import_calls_commit(K.CallImportIn(rows=pv["rows"]), token_data=ADMIN)
    check("imported", res["created"] == 3)
    again = run(K.import_calls_preview(UploadFile(filename="journal.csv", file=io.BytesIO(csv_log.encode())), token_data=ADMIN))
    check("a second import is spotted as duplicate", all(r["duplicate"] for r in again["rows"]))
    check("…and skipped", K.import_calls_commit(K.CallImportIn(rows=again["rows"]), token_data=ADMIN)["created"] == 0)
    xml = ('<?xml version="1.0"?><calls count="1"><call number="+33238000004" duration="95" date="1790000000000" '
           'type="2" contact_name="Arts" /></calls>')
    px = run(K.import_calls_preview(UploadFile(filename="calls.xml", file=io.BytesIO(xml.encode())), token_data=ADMIN))
    check("Android backup XML read too", len(px["rows"]) == 1 and px["rows"][0]["duration_sec"] == 95)
    check("a file without numbers is refused",
          refused(lambda: run(K.import_calls_preview(UploadFile(filename="x.csv", file=io.BytesIO(b"a;b\n1;2\n")), token_data=ADMIN)), 422))

    print("\nDelete & export")
    check("a commercial cannot delete someone else's call", refused(lambda: K.delete_call(c1["id"], token_data=SOFIA), 403))
    K.delete_call(c1["id"], token_data=ADMIN)
    check("deleted with its history line", not db.crm_calls.find_one({"id": c1["id"]})
          and not db.crm_activities.find_one({"meta.call_id": c1["id"]}))
    out = K.export_calls(token_data=ADMIN).body.decode("utf-8-sig")
    check("CSV export", out.startswith("Date;Commerce") and "Boulangerie Paul" in out)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
