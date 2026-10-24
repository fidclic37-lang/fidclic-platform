"""
Tests for S12 — the collection agent (relances de pièces).

Run:  cd api && python3 tests/test_s12.py

WHY THESE MATTER
    First autonomous work. The traps:
      - spamming (one email per piece, or reminding before it's time),
      - harassing forever (no escalation to a human),
      - lying in the audit (sends not recorded, or recorded under a human),
      - a broken mailer breaking the run (email must never crash logic).
    The mailer's network seam is replaced — no real emails leave the tests.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from types import SimpleNamespace
import mongomock

import features.cabinet_os as CO
import features.agent_collect as AC
import features.exceptions_centre as EC
import features.audit as A
from services import mailer

PASS, FAIL = [], []
SENT = []            # captured outbound emails


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}{('  → ' + str(extra)) if extra and not cond else ''}")


def expect_status(name, code, fn):
    try:
        fn()
        check(name, False, f"no error raised (expected {code})")
    except Exception as e:
        check(name, getattr(e, "status_code", None) == code, e)


def tok(email):
    return SimpleNamespace(email=email, role="comptable", tenant_id=None)


PW = "Cabinet-Test2026!"


def fake_post(payload, key):
    SENT.append(payload)
    return {"messageId": f"test-{len(SENT)}"}


def build():
    db = mongomock.MongoClient().db
    for mod in (CO, AC, EC, A):
        mod.init(db)
    os.environ["BREVO_API_KEY"] = "test-key-not-real"   # mailer enabled in tests
    mailer._post = fake_post                       # the seam

    CO.cabinet_signup({"email": "rousseau@cab.fr", "name": "Cabinet Rousseau",
                       "password": PW})
    CO.cabinet_signup({"email": "other@cabB.fr", "name": "Cabinet B", "password": PW})
    r = tok("rousseau@cab.fr")
    CO.create_member({"email": "lea@cab.fr", "role": "collaborateur",
                      "password": PW, "full_name": "Léa"}, token_data=r)
    cab_a = CO._db.cabinets.find_one({"name": "Cabinet Rousseau"})["id"]
    cab_b = CO._db.cabinets.find_one({"name": "Cabinet B"})["id"]
    db.tenants.insert_one({"id": "t1", "legal_name": "Boulangerie Petit",
                           "facturation_enabled": True})
    db.tenants.insert_one({"id": "tB", "legal_name": "Client B"})
    db.cabinet_links.insert_one({"id": "l1", "cabinet_id": cab_a, "tenant_id": "t1",
                                 "status": "active",
                                 "assignee_membership_id":
                                     CO._db.cabinet_memberships.find_one(
                                         {"user_email": "lea@cab.fr"})["id"]})
    db.cabinet_links.insert_one({"id": "lB", "cabinet_id": cab_b, "tenant_id": "tB",
                                 "status": "active"})
    return db, cab_a


def test_s12(db, cab_a):
    r = tok("rousseau@cab.fr")
    today = AC._today()                      # the agent's day: Paris, whatever the machine's clock zone

    print("\nS12 — recording what is missing")
    res = AC.create_request("t1", {"label": "Relevé bancaire juillet",
                                   "client_email": "patron@boulangerie.fr",
                                   "due_date": (today - timedelta(days=1)).isoformat()},
                            token_data=r)
    req1 = res["request"]
    check("request recorded", res["ok"] is True)
    res2 = AC.create_request("t1", {"label": "Facture fournisseur Metro",
                                    "client_email": "patron@boulangerie.fr",
                                    "due_date": (today - timedelta(days=1)).isoformat()},
                             token_data=r)
    req2 = res2["request"]
    check("second piece recorded", res2["ok"] is True)
    check("default reliability = 70 (benefit of the doubt)",
          AC.list_requests("t1", token_data=r)["reliability"] == 70)
    expect_status("empty label refused", 422,
                  lambda: AC.create_request("t1", {"label": "  "}, token_data=r))
    expect_status("no email known → explicit 422", 422,
                  lambda: AC.create_request("t1", {"label": "X"}, token_data=r))
    expect_status("cannot ask on another cabinet's dossier", 403,
                  lambda: AC.create_request("tB", {"label": "X", "client_email": "a@b.c"},
                                            token_data=r))

    print("\nS12 — the run: one email per client, listing everything")
    out = AC.run_collection(token_data=r)
    check("run sent exactly ONE email for two pieces", out["emails_sent"] == 1
          and len(SENT) == 1, out)
    body = SENT[0]["htmlContent"]
    check("email lists BOTH pieces", "Relevé bancaire" in body and "Metro" in body)
    check("email goes to the client", SENT[0]["to"][0]["email"] == "patron@boulangerie.fr")
    check("reminder stamped on the request",
          len((db.doc_requests.find_one({"id": req1["id"]})["reminders"])) == 1)

    out2 = AC.run_collection(token_data=r)
    check("same-day second run does NOT re-send (cadence respected)",
          out2["emails_sent"] == 0 and len(SENT) == 1)

    expect_status("collaborateur cannot trigger the run (EC/superviseur only)", 403,
                  lambda: AC.run_collection(token_data=tok("lea@cab.fr")))

    print("\nS12 — audit: the agent's name, the human's trigger")
    entry = A._db.audit_log.find_one({"action": "agent.reminder_sent"})
    check("send audited as agent.reminder_sent", entry is not None)
    check("actor is the AGENT identity", CO.is_agent_email(entry["actor_email"]))
    check("triggered_by names the human",
          entry["detail"]["triggered_by"] == "rousseau@cab.fr")

    print("\nS12 — receiving teaches the score")
    rr = AC.mark_received(req2["id"], token_data=r)
    check("piece marked received (late — after due date)", rr["on_time"] is False)
    t = db.tenants.find_one({"id": "t1"})
    check("reliability counters count COMPLETED cycles only",
          t["doc_reliability"]["asked"] == 1 and t["doc_reliability"]["received"] == 1)
    expect_status("cannot receive twice", 409,
                  lambda: AC.mark_received(req2["id"], token_data=r))

    print("\nS12 — escalation: after 3 reminders, a human takes over")
    db.doc_requests.update_one({"id": req1["id"]}, {"$set": {"reminders": [
        {"at": (today - timedelta(days=9)).isoformat(), "nth": 1, "sent": True},
        {"at": (today - timedelta(days=6)).isoformat(), "nth": 2, "sent": True},
        {"at": (today - timedelta(days=3)).isoformat(), "nth": 3, "sent": True},
    ]}})
    out3 = AC.run_collection(token_data=r)
    check("exhausted request escalates to a case", out3["cases_opened"] == 1)
    check("request status = escalated",
          db.doc_requests.find_one({"id": req1["id"]})["status"] == "escalated")
    case = db.exception_cases.find_one({"type": "missing_document"})
    check("Exception Centre case exists, on the dossier", case is not None
          and case["tenant_id"] == "t1")
    check("case landed on the dossier owner (Léa)",
          case.get("assignee_membership_id") ==
          CO._db.cabinet_memberships.find_one({"user_email": "lea@cab.fr"})["id"])

    print("\nS12 — a dead mailer never breaks the run")
    def broken_post(payload, key):
        raise RuntimeError("brevo down")
    mailer._post = broken_post
    AC.create_request("t1", {"label": "Attestation URSSAF",
                             "client_email": "patron@boulangerie.fr",
                             "due_date": (today - timedelta(days=1)).isoformat()},
                      token_data=r)
    out4 = AC.run_collection(token_data=r)
    check("run completes despite mailer failure", out4["ok"] is True
          and out4["emails_sent"] == 0)
    nreq = db.doc_requests.find_one({"label": "Attestation URSSAF"})
    check("failed attempt is stamped with the error",
          nreq["reminders"] and nreq["reminders"][0]["sent"] is False)
    mailer._post = fake_post


if __name__ == "__main__":
    db, cab_a = build()
    test_s12(db, cab_a)
    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("All green ✅")
