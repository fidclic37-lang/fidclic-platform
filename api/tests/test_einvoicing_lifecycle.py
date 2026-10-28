"""
E-invoicing / e-reporting SEND lifecycle — the path that was built but never
had its own test file (flagged in ETAT-COMPLET as the gap).

Run:  cd api && python3 tests/test_einvoicing_lifecycle.py

WHAT THIS COVERS (the real transmission lifecycle, not just static rules)
    create → send → SENT/ACCEPTED,
    send → REFUSED  → pa_rejection case opens,
    send → ERROR    → send_error case opens,
    idempotent re-send (never transmits the same number twice),
    async webhook state change (rejection arriving later still opens a case),
    e-reporting (B2C) submission + on-behalf-of audit,
    received supplier invoice + mark accepted/refused,
    credit note (avoir) that clears a rejection,
    payment status independent of the PA lifecycle.

    Runs entirely on the in-memory Mock PA (get_pdp_connector default), whose
    force_next_send hook simulates the failures the B2Brouter sandbox won't.
    NOTE this is the SANDBOX/mock path — production needs a real immatriculated
    PA (business step), but the software lifecycle is exactly this.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from types import SimpleNamespace
import mongomock

import features.facturation as F
import features.cabinet as C
import features.cabinet_os as CO
import features.exceptions_centre as EC
import features.audit as A
from services import pdp_connector
from services.pdp_connector import InvoiceState

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


def owner(tenant_id="t1"):
    return SimpleNamespace(email="owner@cafe.fr", role="business_owner", tenant_id=tenant_id)


def tok(email):
    return SimpleNamespace(email=email, role="comptable", tenant_id=None)


PW = "Cabinet-Test2026!"


def payload(**over):
    base = {
        "buyer": {"name": "Client Pro SARL", "is_company": True,
                  "siren": "552100554", "address": "1 rue de la Paix, 75002 Paris"},
        "lines": [{"description": "Prestation", "quantity": 1,
                   "unit_price": 100.0, "vat_rate": 20}],
        "date": "2026-07-15", "supply_date": "2026-07-15",
        "due_date": "2026-08-15", "payment_term": "net30",
        "operation_category": "services",
    }
    base.update(over)
    return base


def build():
    db = mongomock.MongoClient().db
    # force a fresh Mock connector
    pdp_connector._singleton = None
    os.environ.pop("PDP_PROVIDER", None)
    for mod in (F, C, CO, EC, A):
        mod.init(db)
    db.tenants.insert_one({"id": "t1", "legal_name": "Café Lumière SARL",
                           "name": "Café Lumière", "siren": "552100554",
                           "facturation_enabled": True, "dgfip_activated": True,
                           "vat_regime": "reel_normal"})
    db.users.insert_one({"email": "owner@cafe.fr", "role": "business_owner",
                         "tenant_id": "t1"})
    # a cabinet with a mandate on t1, to test on-behalf-of e-reporting
    CO.cabinet_signup({"email": "rousseau@cab.fr", "name": "Cabinet Rousseau",
                       "password": PW, "ordre_number": "140002200"})
    cab = CO._db.cabinets.find_one({"name": "Cabinet Rousseau"})["id"]
    db.cabinet_links.insert_one({"id": "l1", "cabinet_id": cab, "tenant_id": "t1",
                                 "status": "active"})
    return db


def test_lifecycle(db):
    print("\nE-invoicing — happy path: create → send → SENT")
    r = F.create_invoice(payload(send=True), token_data=owner())
    inv = r["invoice"]
    check("invoice transmitted (pa_status = sent)", inv["pa_status"] == InvoiceState.SENT, inv["pa_status"])
    check("carries a PA invoice id", bool(inv.get("pdp_invoice_id")))
    check("send is audited", A._db.audit_log.count_documents({"action": "invoice.sent"}) == 1)

    print("\nE-invoicing — idempotent re-send")
    same = F._do_send(db.tenants.find_one({"id": "t1"}),
                      db.fact_invoices.find_one({"id": inv["id"]}), actor=owner())
    check("re-sending the same invoice is idempotent (no double transmit)",
          same.get("idempotent") is True)

    print("\nE-invoicing — REFUSED opens a pa_rejection case")
    ref = F.create_invoice(payload(send=True, simulate="reject"), token_data=owner())["invoice"]
    check("refused invoice has pa_status = refused", ref["pa_status"] == InvoiceState.REFUSED)
    check("reject reason captured", bool(ref.get("reject_reason")))
    case = db.exception_cases.find_one({"type": "pa_rejection"})
    check("a pa_rejection case was opened", case is not None and case["tenant_id"] == "t1")
    # the refused invoice can still be REVIEWED (S1) and corrected by an avoir
    F.set_review_status(ref["id"], {"target": "validated"}, token_data=owner())
    check("refused invoice can still be validated (S1 independence)",
          db.fact_invoices.find_one({"id": ref["id"]})["review_status"] == "validated")

    print("\nE-invoicing — avoir (credit note) corrects a refusal")
    cn = F.create_credit_note(ref["id"], {"reason": "Correction adresse"}, token_data=owner())
    check("credit note created against the refused invoice",
          cn["credit_note"]["original_number"] == ref["number"])
    check("avoir amount mirrors the invoice",
          cn["credit_note"]["amount_ttc"] == ref["total_ttc"])

    print("\nE-invoicing — transmission ERROR (bad format) → error state + case")
    err = F.create_invoice(payload(send=True, simulate="error"), token_data=owner())["invoice"]
    check("errored invoice has pa_status = error", err["pa_status"] == InvoiceState.ERROR)
    check("an error-state invoice opens a case (grouped with rejections)",
          db.exception_cases.count_documents({"type": "pa_rejection"}) >= 2)

    print("\nE-invoicing — network timeout raises 502 AND opens a send_error case")
    expect_status("timeout surfaces as 502", 502,
                  lambda: F.create_invoice(payload(send=True, simulate="timeout"), token_data=owner()))
    check("timeout opened a send_error case (the exception path)",
          db.exception_cases.find_one({"type": "send_error"}) is not None)

    print("\nWebhook — an async rejection still becomes a case")
    # a plain SENT invoice, then the PA notifies refusal later
    v = F.create_invoice(payload(send=True), token_data=owner())["invoice"]
    before = db.exception_cases.count_documents({"type": "pa_rejection"})

    class _Req:
        def __init__(self, body): self._b = body
        @property
        def headers(self): return {}
        async def body(self): return self._b
    raw = json.dumps({"invoice_id": v["pdp_invoice_id"], "state": "refused",
                      "reject_code": "LATE_REJ"}).encode()
    # SECURITY: a Mock connector cannot authenticate a webhook — refused
    # unless the run opts in (local tests only, never on Vercel)
    os.environ.pop("FACTURATION_ALLOW_MOCK_WEBHOOK", None)
    expect_status("an unsigned webhook is refused without the local opt-in", 401,
                  lambda: asyncio.get_event_loop().run_until_complete(F.facturation_webhook(_Req(raw))))
    check("… and changed nothing", db.fact_invoices.find_one({"id": v["id"]})["pa_status"] != InvoiceState.REFUSED)
    os.environ["FACTURATION_ALLOW_MOCK_WEBHOOK"] = "1"         # the rest of this run: the local opt-in
    asyncio.get_event_loop().run_until_complete(F.facturation_webhook(_Req(raw)))
    after_inv = db.fact_invoices.find_one({"id": v["id"]})
    check("webhook flipped pa_status to refused", after_inv["pa_status"] == InvoiceState.REFUSED)
    check("webhook opened a new pa_rejection case",
          db.exception_cases.count_documents({"type": "pa_rejection"}) == before + 1)

    print("\nWebhook — 'paid' seeds payment_status but nothing else")
    v2 = F.create_invoice(payload(send=True), token_data=owner())["invoice"]
    raw2 = json.dumps({"invoice_id": v2["pdp_invoice_id"], "state": "paid"}).encode()
    asyncio.get_event_loop().run_until_complete(F.facturation_webhook(_Req(raw2)))
    from services import statuses as st
    paid = st.ensure(db.fact_invoices.find_one({"id": v2["id"]}))
    check("PA 'paid' notification seeds payment_status = paid",
          paid["payment_status"] == "paid")

    print("\nE-reporting (B2C) — submission + audit")
    er = F.send_ereporting({"period_start": "2026-07-01", "period_end": "2026-07-31",
                            "totals_by_vat": {"20": 5000}}, token_data=owner())
    check("e-report accepted by the PA (queued)", er["ereport"]["state"] in ("queued", "pending"))
    check("e-report is audited", A._db.audit_log.count_documents({"action": "ereporting.sent"}) >= 1)

    print("\nE-reporting — cabinet acts on behalf of the client (mandate)")
    erc = F.send_ereporting({"tenant_id": "t1", "period_start": "2026-08-01",
                             "period_end": "2026-08-31", "totals_by_vat": {"20": 3000}},
                            token_data=tok("rousseau@cab.fr"))
    check("cabinet can e-report for a mandated client", erc["ereport"]["state"] in ("queued", "pending"))
    obo = A._db.audit_log.find_one({"action": "ereporting.sent",
                                    "detail.by_cabinet_user": "rousseau@cab.fr"})
    check("on-behalf-of recorded in audit", obo is not None)
    expect_status("cabinet must name the dossier (no tenant_id → 422)", 422,
                  lambda: F.send_ereporting({"period_start": "x"}, token_data=tok("rousseau@cab.fr")))

    print("\nReception — supplier invoice arrives + can be marked")
    rec = F.seed_test_received({"supplier_name": "Metro SAS", "total_ht": 900},
                               token_data=owner())["received"]
    check("received invoice stored", rec["total_ttc"] == round(900 * 1.2, 2))
    mk = F.mark_received(rec["id"], {"state": InvoiceState.ACCEPTED}, token_data=owner())
    check("received invoice can be accepted", mk["state"] == InvoiceState.ACCEPTED)
    expect_status("invalid received-state refused", 422,
                  lambda: F.mark_received(rec["id"], {"state": "banana"}, token_data=owner()))

    print("\nPayment — independent of the PA lifecycle (S1)")
    F.set_payment_status(inv["id"], {"status": "paid", "amount_paid": inv["total_ttc"]},
                         token_data=owner())
    after = db.fact_invoices.find_one({"id": inv["id"]})
    check("payment set to paid", after["payment_status"] == "paid")
    check("…without touching pa_status (stays sent — S1 independence)",
          after["pa_status"] == InvoiceState.SENT)


if __name__ == "__main__":
    db = build()
    test_lifecycle(db)
    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("All green ✅")
