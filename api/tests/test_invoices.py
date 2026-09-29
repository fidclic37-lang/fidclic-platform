"""
Factures FidClic → commerçant: recorded from Stripe, issued once the issuer
is complete, numbered in one continuous series, frozen, and rendered as a
PDF carrying the mentions French law requires.

Run: cd api && /usr/local/bin/python3 tests/test_invoices.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import invoices as INV

    db = server.db
    INV.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class ADMIN:
        email, role, tenant_id = "admin@fidclic.com", "super_admin", None

    class OWNER:
        email, role, tenant_id = "o@corner.fr", "business_owner", "t1"

    class OTHER:
        email, role, tenant_id = "o@rival.fr", "business_owner", "t2"

    db.tenants.insert_many([
        {"id": "t1", "name": "Le Corner Café", "legal_name": "Corner SAS", "plan": "vip", "siret": "12345678900012",
         "street": "12 Rue Nationale", "postal_code": "37000", "city": "Tours", "country": "FR",
         "vat_number": "FR12123456789", "email": "contact@corner.fr", "stripe_customer_id": "cus_1"},
        {"id": "t2", "name": "Rival", "plan": "silver"},
    ])

    def paid(sid, cents=15480, tax=None, subtotal=None, when=1790000000):
        obj = {"id": sid, "amount_paid": cents, "currency": "eur", "status_transitions": {"paid_at": when},
               "lines": {"data": [{"description": "FidClic Pro AI — abonnement mensuel", "quantity": 1,
                                   "amount": cents, "period": {"start": when, "end": when + 30 * 86400}}]}}
        if tax is not None:
            obj.update({"tax": tax, "subtotal": subtotal})
        return obj

    print("\nBefore the issuer is complete, payments wait")
    row = INV.record_payment("t1", paid("in_1"))
    check("recorded, no number yet", row["status"] == "awaiting_issuer" and not row.get("number"))
    check("the owner sees it as being issued, and cannot download a numberless invoice",
          INV.list_invoices(token_data=OWNER())["invoices"][0]["number"] is None)
    try:
        INV.invoice_pdf(row["id"], token_data=OWNER()); early = True
    except HTTPException as e:
        early = e.status_code != 409
    check("… 409, not a half invoice", early is False)

    print("\nThe super-admin completes the issuer")
    r = INV.put_issuer(INV.IssuerIn(legal_name="FidClic SAS", legal_form="SAS", share_capital="10 000 €",
                                    address="1 Place Jean Jaurès", postal_code="37000", city="Tours",
                                    siren="987 654 321", rcs_city="Tours", vat_number="fr 12 987654321",
                                    email="facturation@fidclic.com"), token_data=ADMIN())
    check("complete, and the waiting payment is invoiced at once", r["complete"] and r["issued_now"] == 1)
    inv = db.fidclic_invoices.find_one({"stripe_invoice_id": "in_1"})
    check("first number of the year's series", inv["number"].endswith("-0001") and inv["number"].startswith("FAC-"))
    check("154,80 € TTC at 20 %: 129,00 HT + 25,80 TVA",
          (inv["total_ht"], inv["total_vat"], inv["total_ttc"]) == (129.0, 25.8, 154.8))
    check("issuer and buyer frozen on the invoice",
          inv["issuer"]["siren"] == "987654321" and inv["buyer"]["name"] == "Corner SAS" and inv["buyer"]["siret"])

    print("\nFrom now on, each payment is invoiced as it arrives")
    inv2 = INV.record_payment("t1", paid("in_2", when=1792600000))
    check("numbered next, no gap", inv2["number"].endswith("-0002"))
    check("the same Stripe payment is never invoiced twice", INV.record_payment("t1", paid("in_2")) is None)
    inv3 = INV.record_payment("t1", paid("in_3", cents=12000, tax=2000, subtotal=10000, when=1795200000))
    check("Stripe's own tax lines are used when present", (inv3["total_ht"], inv3["total_vat"]) == (100.0, 20.0))
    db.tenants.update_one({"id": "t1"}, {"$set": {"street": "99 Autre Rue"}})
    check("a later change of address never rewrites an old invoice",
          db.fidclic_invoices.find_one({"stripe_invoice_id": "in_1"})["buyer"]["address"] == "12 Rue Nationale")

    print("\nThe PDF")
    pdf = INV.render_pdf(db.fidclic_invoices.find_one({"stripe_invoice_id": "in_1"}, {"_id": 0}))
    check("a PDF", pdf[:4] == b"%PDF" and len(pdf) > 2000)
    try:
        from pypdf import PdfReader
        import io
        text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
        for must in ("FACTURE", inv["number"], "SIREN 987654321", "RCS Tours", "FR12987654321", "Corner SAS",
                     "SIRET", "Total HT", "TVA 20", "Total TTC", "prestation de services", "40 €",
                     "trois fois le taux", "escompte", "Payée le"):
            check(f"carries « {must} »", must in text)
    except ImportError:
        print("  · pypdf not installed: text checks skipped")
    resp = INV.invoice_pdf(inv["id"], token_data=OWNER())
    check("the owner downloads it, named by its number",
          resp.media_type == "application/pdf" and inv["number"] in resp.headers["content-disposition"])
    try:
        INV.invoice_pdf(inv["id"], token_data=OTHER()); leak = True
    except HTTPException as e:
        leak = e.status_code != 404
    check("another business never gets it", leak is False)

    print("\nFranchise en base de TVA")
    INV.put_issuer(INV.IssuerIn(legal_name="FidClic EI", legal_form="EI", share_capital="0 €", address="1 rue",
                                postal_code="37000", city="Tours", siren="987654321", rcs_city="Tours",
                                vat_applicable=False), token_data=ADMIN())
    inv4 = INV.record_payment("t1", paid("in_4", cents=3900, when=1797800000))
    check("no VAT: HT = TTC", (inv4["total_ht"], inv4["total_vat"]) == (39.0, 0.0))
    try:
        from pypdf import PdfReader
        import io
        check("… and the art. 293 B mention", "293 B" in PdfReader(io.BytesIO(INV.render_pdf(inv4))).pages[0].extract_text())
    except ImportError:
        pass

    print("\nIssuer form")
    try:
        INV.put_issuer(INV.IssuerIn(siren="123"), token_data=ADMIN()); bad = True
    except HTTPException:
        bad = False
    check("a bad SIREN is refused", bad is False)
    check("an issuer with VAT but no VAT number is not complete",
          INV.issuer_complete({**INV.issuer(), "vat_applicable": True, "vat_number": ""}) is False)

    print("\nOverview")
    v = INV.billing_overview(token_data=OWNER())
    check("plan, usage, catalogue, latest invoice",
          v["plan"]["key"] == "vip" and len(v["usage"]) == 4 and len(v["catalogue"]) == 3 and v["latest_invoice"]["number"])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
