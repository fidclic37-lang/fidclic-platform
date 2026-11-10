"""
The name FidClic gives a business's Apple Pass Type ID (live, 2026-11-09).

Apple refused « ROYAL TRIM Liberté » with 409 « An invalid value … was provided
for the parameter 'name' »: an identifier's name takes plain letters, digits
and spaces only — no accent, no apostrophe, no « & », « - » or « . ». The shop
name went to Apple as typed. The name is only a label in Apple's developer
account (customers never see it), so it is cleaned before it is sent.

Run: cd api && python3 tests/test_wallet_identity_name.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

passed = failed = 0


def check(label, cond, detail=None):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label + ("" if cond or detail is None else f"  → {detail!r}"))


def main():
    from services import asc_api as A

    print("Le nom envoyé à Apple")
    for raw, want in [
        ("ROYAL TRIM Liberté", "ROYAL TRIM Liberte"),
        ("ROYAL TRIM LIBÉRTÉ", "ROYAL TRIM LIBERTE"),
        ("L'Atelier & Co.", "L Atelier Co"),
        ("Café-Crème  du   Coin", "Cafe Creme du Coin"),
        ("Green Smoke", "Green Smoke"),
        ("Le Bœuf Couronné", "Le Boeuf Couronne"),
        ("Æsir Øl Straße", "AEsir Ol Strasse"),
        ("QA FidClic AI 31102026", "QA FidClic AI 31102026"),
    ]:
        got = A.apple_name(raw, "pass.com.fidclic.x")
        check(f"« {raw} » → « {want} »", got == want, got)
    plain = re.compile(r"^[A-Za-z0-9 ]+$")
    for raw in ("Æøß œuvre ½", "日本の店", "🍕🍕", "@@@", "", None, "   "):
        got = A.apple_name(raw, "pass.com.fidclic.royal-trim")
        check(f"« {raw} » still gives Apple a plain, non-empty name ({got})", bool(got) and bool(plain.match(got)), got)
    check("nothing usable: the identifier's words stand in",
          A.apple_name("日本", "pass.com.fidclic.royal-trim") == "FidClic royal trim")
    long = A.apple_name("Boulangerie " * 20, "pass.com.fidclic.x")
    check(f"never longer than Apple takes ({len(long)})", len(long) <= 50 and not long.endswith(" "))

    print("\nCe qui part vraiment chez Apple")
    sent = []

    def fake_call(method, path, body=None, **kw):
        sent.append((method, path, body))
        return 201, {"data": {"id": "R1", "attributes": {}}}

    real = A._call
    A._call = fake_call
    try:
        ok, row = A.create_pass_type("pass.com.fidclic.royal-trim-liberte", "ROYAL TRIM Liberté")
    finally:
        A._call = real
    attrs = sent[0][2]["data"]["attributes"] if sent else {}
    check("the POST carries the cleaned name", ok and attrs.get("name") == "ROYAL TRIM Liberte", attrs)
    check("…and the identifier untouched", attrs.get("identifier") == "pass.com.fidclic.royal-trim-liberte", attrs)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
