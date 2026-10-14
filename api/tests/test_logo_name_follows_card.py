"""
The logo's name is the card's name (user, 2026-10-14): Liberté's card was
copied from the account's, its « Nom stylé » letters still spelled « ROYAL TRIM
PALISSY » while its footer said « ROYAL TRIM LIBERTÉ ».

Run: cd api && /usr/local/bin/python3 tests/test_logo_name_follows_card.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-logo-name")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def letters(text, big=None):
    return [{"c": c, "s": 160 if i == big else 100, "color": None, "font": "playfair" if i == big else None}
            for i, c in enumerate(text)]


def main():
    import server  # noqa: F401  (wires the modules)
    import features.wallet_passes as WP

    def spell(t):
        return "".join(x[0] for x in t)

    card = {"name_style": {"letters": letters("ROYAL TRIM PALISSY", big=0)}}
    got = WP.letters_for(card, "ROYAL TRIM LIBERTÉ")
    check("another store's letters → this card's name", spell(got) == "ROYAL TRIM LIBERTÉ")
    check("the matching start keeps its style (big R)", got[0][1] == 160 and got[0][3] == "playfair")
    check("new letters are plain", got[-1][1] == 100 and got[-1][3] is None)

    card = {"name_style": {"letters": letters("★ Royal Trim Liberte ★")}}
    got = WP.letters_for(card, "ROYAL TRIM LIBERTÉ")
    check("symbols, case and accents of the same name are kept", spell(got) == "★ Royal Trim Liberte ★")

    check("no « Nom stylé » → None", WP.letters_for({}, "ROYAL TRIM LIBERTÉ") is None)
    check("no name → letters unchanged",
          spell(WP.letters_for({"name_style": {"letters": letters("ABC")}}, "")) == "ABC")

    # Apple: the pass's logoText is the card's name, the logo image is drawn from it
    seen = {}
    real = WP.name_logo
    WP.name_logo = lambda src, name, color, box=(160, 50), letters=None, **kw: (seen.setdefault("n", name), {})[1]
    try:
        import json
        files = {"pass.json": json.dumps({"logoText": "ROYAL TRIM LIBERTÉ"}).encode(), "logo.png": b"x"}
        WP._best_file = (lambda f, base, _o=WP._best_file: f.get(f"{base}.png"))
        WP._name_into_logos(files, {"name_style": {"letters": letters("ROYAL TRIM PALISSY")}})
    finally:
        WP.name_logo = real
    check("Apple logo drawn with the card's name", seen.get("n") == "ROYAL TRIM LIBERTÉ")

    # organizationName (Wallet's details, notifications): the card's name too
    import server as S
    db = S.db
    db.tenants.insert_one({"id": "t9", "name": "ROYAL TRIM PALISSY", "slug": "rt9"})
    db.card_templates.insert_one({"tenant_id": "t9", "card_name": "ROYAL TRIM LIBERTÉ"})
    db.customers.insert_one({"id": "c9", "tenant_id": "t9", "barcode_id": "FT-T9000001", "name": "Mahdi",
                             "visits": 0, "points": 0})
    pj = WP.build_pass_json(S._serialize_card_payload(db.customers.find_one({"id": "c9"}, {"_id": 0})))
    check(f"organizationName = the card's name ({pj.get('organizationName')})",
          pj.get("organizationName") == "ROYAL TRIM LIBERTÉ")
    check("logoText = the card's name", pj.get("logoText") == "ROYAL TRIM LIBERTÉ")

    # test switch « apple_logo_text »: Apple writes the name, no name image
    seen.clear()
    WP.name_logo = lambda src, name, color, **k: (seen.setdefault("n", name), {})[1]
    try:
        pj_of = lambda sn: {"pass.json": json.dumps({"logoText": "ROYAL TRIM LIBÉRTÉ", "serialNumber": sn}).encode(),  # noqa: E731
                            "logo.png": b"x"}
        files = pj_of("FT-7DA5BB50")
        WP._name_into_logos(files, {"apple_logo_text": ["FT-7DA5BB50"]})
        check("apple_logo_text: the listed card — no name image, logoText kept",
              "n" not in seen and json.loads(files["pass.json"]).get("logoText") == "ROYAL TRIM LIBÉRTÉ")
        WP._name_into_logos(pj_of("FT-B2295A08"), {"apple_logo_text": ["FT-7DA5BB50"]})
        check("…another card: as before", seen.get("n") == "ROYAL TRIM LIBÉRTÉ")
    finally:
        WP.name_logo = real

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
