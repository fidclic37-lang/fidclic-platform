"""
Sécurité › changer l'adresse e-mail du compte.

Run: cd api && python3 tests/test_account_email.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server
    from models import TokenData
    from auth import hash_password
    from features import account_email as E
    from features import role_perms as RP

    db = server.db
    E.init(db)
    RP.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    def fails(label, fn, code=None, text=None):
        from fastapi import HTTPException
        try:
            fn()
        except HTTPException as e:
            ok = (code is None or e.status_code == code) and (text is None or text.lower() in str(e.detail).lower())
            return check(f"{label} (refusé: {e.detail})", ok)
        return check(label + " — devait être refusé", False)

    # --- the mails FidClic would send, captured -------------------------------
    sent = []

    class _Mailer:
        @staticmethod
        def send(to, subject, html, **k):
            sent.append({"to": to, "subject": subject, "html": html})
            return True

    import types
    fake = types.ModuleType("services.mailer")
    fake.send = _Mailer.send
    sys.modules["services.mailer"] = fake

    # --- a shop with an owner -------------------------------------------------
    db.tenants.insert_one({"id": "t1", "name": "Café Lumière"})
    db.users.insert_one({"email": "old@shop.fr", "role": "business_owner", "tenant_id": "t1",
                         "hashed_password": hash_password("Bon!Motdepasse1")})
    db.users.insert_one({"email": "pris@autre.fr", "role": "business_owner", "tenant_id": "t2",
                         "hashed_password": hash_password("x")})
    OWNER = TokenData(email="old@shop.fr", role="business_owner", tenant_id="t1")

    print("\n— la demande —")
    fails("un mot de passe faux n'ouvre rien",
          lambda: E.start(E.StartIn(new_email="new@shop.fr", password="nope", method="link"), None, OWNER),
          400, "mot de passe")
    fails("une adresse invalide est refusée",
          lambda: E.start(E.StartIn(new_email="pas-une-adresse", password="Bon!Motdepasse1"), None, OWNER), 400)
    fails("sa propre adresse n'a rien à changer",
          lambda: E.start(E.StartIn(new_email="old@shop.fr", password="Bon!Motdepasse1"), None, OWNER), 400, "déjà")
    fails("l'adresse d'un autre compte est refusée",
          lambda: E.start(E.StartIn(new_email="pris@autre.fr", password="Bon!Motdepasse1"), None, OWNER), 409)
    check("rien n'a été envoyé pour autant", sent == [])

    # --- the code route -------------------------------------------------------
    print("\n— par code —")
    r = E.start(E.StartIn(new_email="new@shop.fr", password="Bon!Motdepasse1", method="code"), None, OWNER)
    check("la demande part vers la NOUVELLE adresse", r["sent_to"] == "new@shop.fr" and sent[-1]["to"] == "new@shop.fr")
    check("l'ancienne adresse ne reçoit rien à ce stade", all(m["to"] != "old@shop.fr" for m in sent))
    row = db.email_changes.find_one({"user_email": "old@shop.fr", "used": False})
    check("le code n'est pas stocké en clair", "token_hash" in row and len(row["token_hash"]) == 64)
    import re as _re
    code = _re.search(r"letter-spacing:7px;color:#0B1C3F\">(\d{6})<", sent[-1]["html"]).group(1)
    check("le code fait six chiffres", len(code) == 6 and code.isdigit())

    fails("un mauvais code ne passe pas",
          lambda: E.confirm(E.ConfirmIn(code="000000" if code != "000000" else "111111"), None, OWNER), 400)
    check("l'essai raté est compté", (db.email_changes.find_one({"id": row["id"]}) or {}).get("attempts") == 1)

    out = E.confirm(E.ConfirmIn(code=code), None, OWNER)
    check("l'adresse a changé", out["email"] == "new@shop.fr"
          and db.users.find_one({"email": "new@shop.fr"}) is not None
          and db.users.find_one({"email": "old@shop.fr"}) is None)
    check("l'ancienne adresse est gardée dans l'historique du compte",
          db.users.find_one({"email": "new@shop.fr"}).get("previous_emails") == ["old@shop.fr"])
    check("l'ANCIENNE adresse est prévenue après coup", sent[-1]["to"] == "old@shop.fr")
    check("…sans écrire la nouvelle adresse en entier", "new@shop.fr" not in sent[-1]["html"])
    fails("le même code ne sert pas deux fois",
          lambda: E.confirm(E.ConfirmIn(code=code), None, OWNER), 400, "aucune demande")

    # --- history is not rewritten --------------------------------------------
    print("\n— l'historique garde ce qui s'est passé —")
    NEW = TokenData(email="new@shop.fr", role="business_owner", tenant_id="t1")
    done = db.email_changes.find_one({"id": row["id"]})
    check("la demande garde l'adresse d'alors", done["user_email"] == "old@shop.fr")

    # --- the link route -------------------------------------------------------
    print("\n— par lien —")
    sent.clear()
    r2 = E.start(E.StartIn(new_email="encore@shop.fr", password="Bon!Motdepasse1", method="link"), None, NEW)
    check("le lien part vers la nouvelle adresse", r2["method"] == "link" and sent[-1]["to"] == "encore@shop.fr")
    tok = _re.search(r"/changer-email\?token=([\w\-]+)", sent[-1]["html"]).group(1)
    check("le jeton est long", len(tok) > 30)
    E.confirm(E.ConfirmIn(token=tok), None, NEW)
    check("le lien change l'adresse", db.users.find_one({"email": "encore@shop.fr"}) is not None)
    check("les deux anciennes sont gardées",
          db.users.find_one({"email": "encore@shop.fr"})["previous_emails"] == ["old@shop.fr", "new@shop.fr"])

    # --- expiry, supersede, cancel -------------------------------------------
    print("\n— durée de vie —")
    LAST = TokenData(email="encore@shop.fr", role="business_owner", tenant_id="t1")
    E.start(E.StartIn(new_email="a@shop.fr", password="Bon!Motdepasse1", method="code"), None, LAST)
    first = db.email_changes.find_one({"user_email": "encore@shop.fr", "used": False})
    E.start(E.StartIn(new_email="b@shop.fr", password="Bon!Motdepasse1", method="code"), None, LAST)
    check("une nouvelle demande annule la précédente",
          db.email_changes.find_one({"id": first["id"]})["used"] is True
          and E._pending("encore@shop.fr")["new_email"] == "b@shop.fr")

    db.email_changes.update_one({"user_email": "encore@shop.fr", "used": False},
                                {"$set": {"expires_at": E._now() - dt.timedelta(minutes=1)}})
    check("une demande expirée n'est plus en cours", E._pending("encore@shop.fr") is None)

    E.start(E.StartIn(new_email="c@shop.fr", password="Bon!Motdepasse1", method="code"), None, LAST)
    E.cancel(None, LAST)
    check("annuler ferme la demande", E._pending("encore@shop.fr") is None)

    print("\n— la permission —")
    check("« Changer l'adresse e-mail » est une permission à part entière",
          "email_change" in RP.PAGE_KEYS and RP.LABEL["email_change"].startswith("Changer"))
    check("aucun rôle intégré ne l'a au départ",
          all(t.get("email_change", "none") == "none" for t in RP.DEFAULT_TEMPLATES.values()))
    check("elle couvre les routes du changement", RP.page_of("/api/security/email/start") == "email_change")
    check("…sans toucher à la suppression du compte", RP.page_of("/api/security/account") == "delete")
    check("ce n'est pas une route commune à tous", not RP.is_common("/api/security/email/start", "POST"))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
