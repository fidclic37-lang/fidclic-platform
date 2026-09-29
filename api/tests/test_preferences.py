"""
Paramètres › Préférences — each account's own choices, the business's
currency (owner only), validation, reset, and the e-mail switches honoured.

Run: cd api && /usr/local/bin/python3 tests/test_preferences.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from models import TokenData
    from features import preferences as PR

    db = server.db
    PR.init(db)
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

    OWNER = TokenData(email="o@c.fr", role="business_owner", tenant_id="t1")
    SARA = TokenData(email="sara@c.fr", role="manager", tenant_id="t1")
    db.tenants.insert_one({"id": "t1", "name": "Café"})
    db.users.insert_many([{"email": "o@c.fr", "role": "business_owner", "tenant_id": "t1"},
                          {"email": "sara@c.fr", "role": "manager", "tenant_id": "t1"}])

    v = PR.get_prefs(token_data=OWNER)
    check("defaults: French, Paris, 31/12/2026, euros, 20 per page, marketing e-mails off",
          v["preferences"]["language"] == "fr" and v["preferences"]["timezone"] == "Europe/Paris"
          and v["preferences"]["date_format"] == "dmy" and v["currency"] == "EUR"
          and v["preferences"]["per_page"] == 20 and v["preferences"]["emails"]["marketing"] is False)
    PR.put_prefs(PR.PrefsIn(language="en", timezone="America/New_York", date_format="ymd", per_page=50,
                            default_page="/dashboard/customers", link_target="new", confirm_actions=False,
                            emails=PR.EmailsIn(billing=False)), token_data=SARA)
    s = PR.get_prefs(token_data=SARA)["preferences"]
    check("each account keeps its own", s["language"] == "en" and s["per_page"] == 50 and s["emails"]["billing"] is False
          and PR.get_prefs(token_data=OWNER)["preferences"]["language"] == "fr")
    check("an unknown time zone is refused", refused(lambda: PR.put_prefs(PR.PrefsIn(timezone="Mars/Olympus"), token_data=SARA), 400))
    check("a value not offered is refused", refused(lambda: PR.put_prefs(PR.PrefsIn(per_page=7), token_data=SARA), 400))

    print("\nCurrency — the business's")
    PR.put_prefs(PR.PrefsIn(currency="chf"), token_data=OWNER)
    check("the owner sets it, for everyone", PR.get_prefs(token_data=SARA)["currency"] == "CHF")
    check("a manager cannot", refused(lambda: PR.put_prefs(PR.PrefsIn(currency="USD"), token_data=SARA), 403))
    check("not a currency code → refused", refused(lambda: PR.put_prefs(PR.PrefsIn(currency="EURO"), token_data=OWNER), 400))
    me = server.get_me(token_data=SARA)
    check("/auth/me carries the currency and the account's choices", me["currency"] == "CHF" and me["preferences"]["language"] == "en")

    print("\nReset")
    PR.reset_prefs(token_data=SARA)
    check("back to the defaults — the business's currency stays",
          PR.get_prefs(token_data=SARA)["preferences"]["language"] == "fr" and PR.get_prefs(token_data=SARA)["currency"] == "CHF")

    print("\nE-mails")
    PR.put_prefs(PR.PrefsIn(emails=PR.EmailsIn(billing=False)), token_data=OWNER)
    check("« Emails de facturation » off is honoured", PR.wants_email("o@c.fr", "billing") is False and PR.wants_email("o@c.fr", "alerts") is True)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
