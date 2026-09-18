#!/usr/bin/env python3
"""
Mapping tests: FidClic invoice -> B2Brouter shape.

These exist because the gap they cover was invisible for the whole project: with
PDP_PROVIDER=mock, MockPdp accepts any dict, so every existing test passed while
the real adapter would have failed on the first sandbox call.
"""
import sys, os, importlib.util
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
spec = importlib.util.spec_from_file_location(
    "pc", os.path.join(os.path.dirname(__file__), "..", "services", "pdp_connector.py"))
pc = importlib.util.module_from_spec(spec); spec.loader.exec_module(pc)

P, F = 0, 0
def ck(name, cond, got=None):
    global P, F
    if cond: P += 1; print(f"  ok   {name}")
    else:    F += 1; print(f"  FAIL {name}" + (f"  got={got!r}" if got is not None else ""))

BASE = {
    "number": "2026-0148", "date": "2026-08-01", "due_date": "2026-08-31",
    "supply_date": "2026-07-28", "purchase_order": "BC-991", "notes": "Merci.",
    "operation_category": "services", "payment_term": "30 jours",
    "buyer": {"legal_name": "Client Test SARL", "is_company": True,
              "siret": "552 100 554 00013", "vat_number": "FR12552100554",
              "email": "compta@client.fr",
              "address": {"street": "1 rue de la Paix", "postal_code": "75002",
                          "city": "Paris", "country": "FR"}},
    "lines": [{"description": "Prestation de services", "quantity": 2,
               "unit_price": 410.0, "vat_rate": 20}],
}

print("\nB2Brouter mapping")

m = pc.to_b2brouter_invoice(BASE)
ck("type is IssuedInvoice for a company buyer", m["type"] == "IssuedInvoice", m["type"])
ck("number carried", m["number"] == "2026-0148")
ck("contact name from legal_name", m["contact"]["name"] == "Client Test SARL")
ck("address flattened", m["contact"]["address"] == "1 rue de la Paix")
ck("postalcode key renamed", m["contact"]["postalcode"] == "75002")
ck("country lowercased", m["contact"]["country"] == "fr", m["contact"]["country"])
ck("SIRET -> scheme 0009, spaces stripped",
   m["contact"]["pin_scheme"] == "0009" and m["contact"]["pin_value"] == "55210055400013",
   (m["contact"].get("pin_scheme"), m["contact"].get("pin_value")))
ck("B2B routes over peppol", m["contact"]["transport_type_code"] == "peppol")
ck("one line mapped", len(m["invoice_lines_attributes"]) == 1)
ln = m["invoice_lines_attributes"][0]
ck("unit_price -> price", ln["price"] == 410.0, ln["price"])
ck("quantity preserved", ln["quantity"] == 2)
ck("standard rate -> category S", ln["taxes_attributes"][0]["category"] == "S")
ck("percent carried", ln["taxes_attributes"][0]["percent"] == 20)
ck("purchase_order -> buyer_reference", m["buyer_reference"] == "BC-991")
# The 422 the sandbox actually returned: pin_* alone is not enough.
ck("VAT number -> tin_value (BT-48), not taxcode",
   m["contact"].get("tin_value") == "FR12552100554" and "taxcode" not in m["contact"],
   m["contact"].get("tin_value"))
ck("SIRET -> cin_value as well as pin_value",
   m["contact"].get("cin_value") == "55210055400013", m["contact"].get("cin_value"))
ck("at least one of tin_value / cin_value always present",
   bool(m["contact"].get("tin_value") or m["contact"].get("cin_value")))
ck("supply_date -> operation_date", m["operation_date"] == "2026-07-28")
ck("send_after_import NOT set by the mapper", "send_after_import" not in m)

# --- B2C: e-reporting, not e-invoicing ---
b2c = {**BASE, "buyer": {"name": "Sophie D.", "is_company": False}}
m2 = pc.to_b2brouter_invoice(b2c)
ck("B2C -> IssuedSimplifiedInvoice", m2["type"] == "IssuedSimplifiedInvoice", m2["type"])
ck("B2C has no pin (no annuaire routing)", "pin_scheme" not in m2["contact"])
ck("B2C transport is email", m2["contact"]["transport_type_code"] == "email")

# --- VAT categories: the part a rate alone cannot express ---
def cat(line, buyer=None):
    d = {**BASE, "lines": [{**BASE["lines"][0], **line}]}
    if buyer: d["buyer"] = {**BASE["buyer"], **buyer}
    return pc.to_b2brouter_invoice(d)["invoice_lines_attributes"][0]["taxes_attributes"][0]["category"]

ck("0% domestic, exempt flag -> E", cat({"vat_rate": 0, "vat_exempt": True}) == "E")
ck("0% domestic, no flag -> Z", cat({"vat_rate": 0}) == "Z")
ck("0% reverse charge -> AE", cat({"vat_rate": 0, "reverse_charge": True}) == "AE")
ck("0% EU buyer -> K (intra-community)",
   cat({"vat_rate": 0}, {"address": {"country": "DE"}}) == "K")
ck("0% non-EU buyer -> G (export)",
   cat({"vat_rate": 0}, {"address": {"country": "CH"}}) == "G")
ck("explicit vat_category wins", cat({"vat_rate": 20, "vat_category": "ae"}) == "AE")

# --- identifier fallbacks ---
no_siret = {**BASE, "buyer": {**BASE["buyer"], "siret": "", "siren": "552100554"}}
ck("SIREN fallback -> scheme 0002",
   pc.to_b2brouter_invoice(no_siret)["contact"]["pin_scheme"] == "0002")
# A French VAT number is FR + 2 check chars + the 9-digit SIREN, so with nothing
# else on the buyer we recover a real 0002 SIREN from it. Scheme 9957 used to be
# emitted here and is NOT in the ICD 6523 list (Annexe 7 G1.73) — this test used
# to assert the bug.
only_vat = {**BASE, "buyer": {**BASE["buyer"], "siret": "", "siren": "",
                              "vat_number": "FR40552100554"}}
_vat_pin = pc.to_b2brouter_invoice(only_vat)["contact"]
ck("FR VAT fallback -> scheme 0002, not 9957", _vat_pin["pin_scheme"] == "0002")
ck("FR VAT fallback -> SIREN extracted from the VAT number",
   _vat_pin["pin_value"] == "552100554")

# Non-French VAT: we have no legitimate routing identifier, so emit none rather
# than route to a bad address. The PA rejects loudly, which is what we want.
foreign = {**BASE, "buyer": {**BASE["buyer"], "siret": "", "siren": "",
                             "vat_number": "DE811907980"}}
_foreign = pc.to_b2brouter_invoice(foreign)["contact"]
ck("non-FR VAT -> no pin_scheme guessed", "pin_scheme" not in _foreign)
ck("non-FR VAT -> tin_value still carries the VAT number",
   _foreign.get("tin_value") == "DE811907980")

# --- pass-through: the sandbox smoke test builds the vendor shape itself ---
already = {"type": "IssuedInvoice", "number": "X", "invoice_lines_attributes": [], "contact": {}}
conn = pc.B2BrouterPdp("test_x", "2026-04-20", "https://example.invalid")
sent = {}
conn._request = lambda method, path, body=None: sent.update({"body": body}) or {"invoice": {"id": 1, "state": "new"}}
conn.create_invoice("acct", already)
ck("pre-shaped payload passes through untouched",
   sent["body"]["invoice"]["number"] == "X" and sent["body"]["invoice"]["send_after_import"] is False)

conn.create_invoice("acct", BASE)
ck("FidClic doc gets mapped before send",
   "invoice_lines_attributes" in sent["body"]["invoice"] and
   sent["body"]["invoice"]["contact"]["pin_value"] == "55210055400013")

# --- documented sandbox test recipients (verified against B2Brouter docs) ---
print("\nSandbox test recipients")
for key, expect in [("registered", "9508397101047"),
                    ("refused",     "9506215594996"),
                    ("no_receiver", "9500047420799")]:
    ck(f"{key} GLN constant", pc.SANDBOX_RECIPIENTS[key]["pin_value"] == expect)
    ck(f"{key} uses scheme 0088 (GLN, not SIRET)",
       pc.SANDBOX_RECIPIENTS[key]["pin_scheme"] == "0088")

# The whole point: an explicit pin must override SIRET, or the test recipients
# are unreachable from the app and only the standalone script can use them.
sbx = {**BASE, "buyer": {**BASE["buyer"], **pc.SANDBOX_RECIPIENTS["refused"]}}
m3 = pc.to_b2brouter_invoice(sbx)
ck("explicit pin_scheme/pin_value overrides SIRET",
   m3["contact"]["pin_scheme"] == "0088" and m3["contact"]["pin_value"] == "9506215594996",
   (m3["contact"]["pin_scheme"], m3["contact"]["pin_value"]))
ck("sandbox recipient still routes over peppol",
   m3["contact"]["transport_type_code"] == "peppol")

print(f"\n{'='*46}\nPASSED: {P}   FAILED: {F}")
sys.exit(1 if F else 0)
