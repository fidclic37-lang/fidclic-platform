"""
Tests for Export FEC.

Run:  cd api && python3 tests/test_fec.py

WHY THESE MATTER
    A FEC that a tax auditor rejects is worse than no FEC. The invariants:
      - every entry balances (sum debit == sum credit) to the centime,
      - exactly the 18 columns, in order,
      - ONLY validated invoices become entries (drafts must never hit books),
      - amounts use the FEC decimal (comma), dates YYYYMMDD,
      - cabinet export is mandate-scoped (no other cabinet's client leaks).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace
import mongomock

import features.fec as FEC
import features.facturation as F
import features.cabinet as C
import features.cabinet_os as CO
import features.audit as A

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


def tok(email, role="comptable", tenant_id=None):
    return SimpleNamespace(email=email, role=role, tenant_id=tenant_id)


PW = "Cabinet-Test2026!"


def inv_payload(**over):
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
    for mod in (FEC, F, C, CO, A):
        mod.init(db)
    CO.cabinet_signup({"email": "rousseau@cab.fr", "name": "Cabinet Rousseau",
                       "password": PW, "ordre_number": "140002200"})
    CO.cabinet_signup({"email": "other@cabB.fr", "name": "Cabinet B", "password": PW})
    cab_b = CO._db.cabinets.find_one({"name": "Cabinet B"})["id"]
    cab_a = CO._db.cabinets.find_one({"name": "Cabinet Rousseau"})["id"]
    db.tenants.insert_one({"id": "t1", "legal_name": "Café Lumière SARL",
                           "name": "Café Lumière", "siren": "552100554",
                           "facturation_enabled": True, "dgfip_activated": True,
                           "vat_regime": "reel_normal"})
    db.tenants.insert_one({"id": "tB", "legal_name": "Autre", "siren": "542107651",
                           "facturation_enabled": True})
    db.cabinet_links.insert_one({"id": "l1", "cabinet_id": cab_a, "tenant_id": "t1",
                                 "status": "active"})
    db.cabinet_links.insert_one({"id": "lB", "cabinet_id": cab_b, "tenant_id": "tB",
                                 "status": "active"})
    return db


def test_fec(db):
    r = tok("rousseau@cab.fr")

    print("\nFEC — only validated invoices become entries")
    # a DRAFT (not validated) must NOT appear
    F.create_invoice(inv_payload(tenant_id="t1"), token_data=r)
    # a VALIDATED single-rate invoice
    v1 = F.create_invoice(inv_payload(tenant_id="t1"), token_data=r)["invoice"]
    F.set_review_status(v1["id"], {"target": "validated"}, token_data=r)
    # a VALIDATED multi-rate invoice (20% + 10%)
    v2 = F.create_invoice(inv_payload(tenant_id="t1", lines=[
        {"description": "A", "quantity": 1, "unit_price": 200.0, "vat_rate": 20},
        {"description": "B", "quantity": 2, "unit_price": 50.0, "vat_rate": 10},
    ]), token_data=r)["invoice"]
    F.set_review_status(v2["id"], {"target": "validated"}, token_data=r)

    invoices = FEC._invoices_for("t1", "", "")
    check("only the 2 validated invoices are picked up", len(invoices) == 2, len(invoices))
    lines = FEC.build_fec_lines(invoices)
    # v1: 1 debit + 1 credit707 + 1 credit44571 = 3
    # v2: 1 debit + 2 credit707 + 2 credit44571 = 5  → total 8
    check("entry lines generated (3 + 5)", len(lines) == 8, len(lines))

    print("\nFEC — the accounting invariant: débit == crédit")
    def to_f(s): return float(s.replace(",", "."))
    deb = sum(to_f(l["Debit"]) for l in lines)
    cre = sum(to_f(l["Credit"]) for l in lines)
    check("total debit == total credit (balanced books)", round(deb, 2) == round(cre, 2),
          f"{deb} vs {cre}")
    # v1: TTC 120 debit; HT 100 + VAT 20 credit
    check("single invoice debit = TTC 120,00",
          any(l["Debit"] == "120,00" and l["CompteNum"] == "411000" for l in lines))
    check("VAT credited to 445710",
          any(l["CompteNum"] == "445710" and l["Credit"] == "20,00" for l in lines))

    print("\nFEC — format norm")
    body = FEC.render_fec(lines)
    header = body.split("\n")[0].split("\t")
    check("exactly 18 columns in order", header == FEC.FEC_COLUMNS, header)
    check("tab-separated", "\t" in body)
    check("decimal uses a comma", "120,00" in body and "120.00" not in body)
    check("dates are YYYYMMDD", any("20260715" in l for l in body.split("\n")))
    check("client SIREN is the auxiliary account", "C552100554" in body)

    print("\nFEC — date range filter")
    F.create_invoice(inv_payload(tenant_id="t1", date="2026-09-01",
                                 supply_date="2026-09-01", due_date="2026-10-01"),
                     token_data=r)
    vSep = db.fact_invoices.find_one({"date": "2026-09-01"})
    F.set_review_status(vSep["id"], {"target": "validated"}, token_data=r)
    july = FEC._invoices_for("t1", "2026-07-01", "2026-07-31")
    check("range filter keeps only July", all(i["date"].startswith("2026-07") for i in july)
          and len(july) == 2)

    print("\nFEC — scoping")
    from fastapi.responses import PlainTextResponse
    resp = FEC.cabinet_fec("t1", token_data=r)
    check("cabinet export returns the file", isinstance(resp, PlainTextResponse))
    check("filename carries SIREN + FEC", "552100554FEC" in resp.headers["content-disposition"])
    expect_status("cannot export another cabinet's client (mandate scope)", 403,
                  lambda: FEC.cabinet_fec("tB", token_data=r))
    check("export is audited",
          A._db.audit_log.count_documents({"action": "fec.exported"}) >= 1)
    row = A._db.audit_log.find_one({"action": "fec.exported"}) or {}
    check("… with the period as plain text, even when called without one",
          (row.get("detail") or {}).get("from") == "" and (row.get("detail") or {}).get("to") == "")
    FEC.cabinet_fec("t1", date_from="2026-07-01", date_to="2026-07-31", token_data=r)
    check("… and the period asked when there is one", A._db.audit_log.find_one(
        {"action": "fec.exported", "detail.from": "2026-07-01", "detail.to": "2026-07-31"}) is not None)
    check("a refused export (other cabinet) is not audited as exported",
          A._db.audit_log.count_documents({"action": "fec.exported", "tenant_id": "tB"}) == 0)
    FEC.owner_fec(token_data=tok("owner@t1", "business_owner", "t1"))
    check("the owner's own export is audited too", A._db.audit_log.find_one(
        {"action": "fec.exported", "tenant_id": "t1", "actor_role": "business_owner"}) is not None)

    print("\nFEC — empty is valid (header only)")
    empty = FEC.render_fec(FEC.build_fec_lines([]))
    check("empty FEC still has the 18-column header",
          empty.strip().split("\t") == FEC.FEC_COLUMNS)


if __name__ == "__main__":
    db = build()
    test_fec(db)
    print("\n" + "=" * 62)
    print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for f in FAIL:
            print("  ✗", f)
        sys.exit(1)
    print("All green ✅")
