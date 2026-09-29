"""
Tests for S13 — abonnements (standing instructions) + the daily cron.

Run:  cd api && python3 tests/test_s13.py

WHY THESE MATTER
    The whole answer to "who approved this amount?" lives here:
      - only EC/superviseur can WRITE an instruction (writing = approving),
      - the agent COPIES it (never edits a number), as a draft, in its own name,
      - one invoice per month per instruction, no matter how often the run
        fires (cron + button both), and a paused instruction bills nothing,
      - the cron pass is isolated per cabinet and rejects strangers (401).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from types import SimpleNamespace
import mongomock

import features.cabinet_os as CO
import features.agent_billing as AB
import features.agent_collect as AC
import features.cabinet as C
import features.facturation as F
import features.audit as A
import features.cron as CRON
import features.agent_gardien as GD  # cron now also runs Le Gardien nightly
from services import mailer

PASS, FAIL = [], []


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


def build():
    db = mongomock.MongoClient().db
    for mod in (CO, AB, AC, C, F, A, CRON, GD):
        mod.init(db)
    os.environ["BREVO_API_KEY"] = "test-key"
    mailer._post = lambda payload, key: {"messageId": "t"}

    CO.cabinet_signup({"email": "rousseau@cab.fr", "name": "Cabinet Rousseau",
                       "password": PW})
    r = tok("rousseau@cab.fr")
    CO.create_member({"email": "lea@cab.fr", "role": "collaborateur",
                      "password": PW, "full_name": "Léa"}, token_data=r)
    cab = CO._db.cabinets.find_one({"name": "Cabinet Rousseau"})["id"]
    db.tenants.insert_one({"id": "t1", "legal_name": "Gym Metro SARL",
                           "name": "Gym Metro", "siren": "552100554",
                           "facturation_enabled": True, "dgfip_activated": True})
    db.cabinet_links.insert_one({"id": "l1", "cabinet_id": cab, "tenant_id": "t1",
                                 "status": "active"})
    return db, cab


SUB = {
    "label": "Adhésion mensuelle Gym Metro",
    "buyer": {"name": "Client Abonné SARL", "siren": "542107651",
              "address": "5 rue du Sport, 37000 Tours", "is_company": True},
    "lines": [{"description": "Abonnement mensuel", "quantity": 1,
               "unit_price": 450.0, "vat_rate": 20}],
    "day_of_month": 1,          # already reached, whatever today is
}


def test_s13(db, cab):
    r = tok("rousseau@cab.fr")
    ym = date.today().strftime("%Y-%m")

    print("\nS13 — the standing instruction (writing = approving)")
    res = AB.create_subscription("t1", dict(SUB), token_data=r)
    sub = res["subscription"]
    check("instruction recorded", res["ok"] is True)
    check("approval is recorded forever",
          sub["approved_by"] == "rousseau@cab.fr" and bool(sub["approved_at"]))
    expect_status("collaborateur cannot approve an instruction", 403,
                  lambda: AB.create_subscription("t1", dict(SUB),
                                                 token_data=tok("lea@cab.fr")))
    expect_status("bad buyer SIREN refused", 422,
                  lambda: AB.create_subscription("t1", {**SUB,
                      "buyer": {**SUB["buyer"], "siren": "111111111"}}, token_data=r))
    expect_status("day 31 refused (must exist in every month)", 422,
                  lambda: AB.create_subscription("t1", {**SUB, "day_of_month": 31},
                                                 token_data=r))

    print("\nS13 — the agent executes: copies, never invents")
    out = AB.run_billing_for_cabinet(cab, "test")
    check("one draft created", out["invoices_drafted"] == 1, out)
    inv = db.fact_invoices.find_one({"notes": {"$regex": "Adhésion"}})
    check("amount copied exactly from the instruction (540 € TTC)",
          inv["total_ttc"] == 540.0)
    check("created_by is the agent", CO.is_agent_email(inv["created_by"]))
    check("it is a DRAFT (agent transmits nothing)", inv["pa_status"] == "draft")
    q = C.review_queue(token_data=r)
    check("draft waits in the human queue",
          any(x["id"] == inv["id"] for x in q["queue"]))

    out2 = AB.run_billing_for_cabinet(cab, "test")
    check("second run same month drafts NOTHING (idempotent)",
          out2["invoices_drafted"] == 0 and out2["skipped"] == 1)

    print("\nS13 — pause works; audit tells the whole story")
    AB.update_subscription(sub["id"], {"active": False}, token_data=r)
    db.subscriptions.update_one({"id": sub["id"]}, {"$set": {"last_run_ym": None}})
    out3 = AB.run_billing_for_cabinet(cab, "test")
    check("paused instruction bills nothing", out3["invoices_drafted"] == 0)
    AB.update_subscription(sub["id"], {"active": True}, token_data=r)
    entry = A._db.audit_log.find_one({"action": "agent.invoice_drafted",
                                      "detail.subscription_id": sub["id"]}) or \
            A._db.audit_log.find_one({"action": "agent.invoice_drafted"})
    check("audit links draft → instruction → approver",
          entry and entry["detail"].get("approved_by") == "rousseau@cab.fr")
    expect_status("amount cannot be edited in place (approval integrity)", 422,
                  lambda: AB.update_subscription(sub["id"], {"lines": []},
                                                 token_data=r))

    print("\nS13 — the cron: locked door, isolated cabinets")
    os.environ["CRON_SECRET"] = "s3cret-cron"
    expect_status("wrong secret → 401", 401,
                  lambda: CRON.agent_daily(authorization="Bearer wrong"))
    db.subscriptions.update_one({"id": sub["id"]}, {"$set": {"last_run_ym": None}})
    summary = CRON.agent_daily(authorization="Bearer s3cret-cron")
    check("cron walks the cabinets", summary["cabinets"] >= 1)
    check("cron drafted the due invoice", summary["invoices_drafted"] == 1, summary)
    check("cron reports no failures", summary["failures"] == [])
    entry2 = A._db.audit_log.find_one({"action": "agent.invoice_drafted",
                                       "detail.triggered_by": "cron"})
    check("cron-triggered draft audited with triggered_by=cron", entry2 is not None)


if __name__ == "__main__":
    # The cron pass reaches modules that import server.py, which opens the
    # MongoDB configured for the app. Like every other suite, keep that on the
    # in-memory mongomock server so the test needs no database running.
    os.environ.setdefault("DISABLE_SEED", "1")
    with mongomock.patch(servers=(("localhost", 27017),)):
        # Boot the app first: its feature loader initialises every module on
        # its own database. build() then points the modules under test at this
        # test's database — otherwise the cron's import would re-point them
        # half-way through the run.
        import server  # noqa: F401
        db, cab = build()
        test_s13(db, cab)
    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("All green ✅")
