"""
QA small suggestions (2026-10-08):
  UX01  import: « Envoyer leur carte par email » was ticked in advance
  UX02  icon-only buttons without an accessible name (Clients, Segmentation)
  UX10  the signup fields were only checked by the browser
  (UX08, the recommendations PDF, is covered in test_insights_page.py)

Run: cd api && /usr/local/bin/python3 tests/test_ux_small.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ux-small")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import httpx
    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "plan": "vip", "subscription_status": "active"})

    def join(**kw):
        body = {"name": "Léa Martin", "phone": "06 12 34 56 78", "postal_code": "37000", "birthday": "25/12/1990",
                "consent": True, "consent_policy_version": "2026-07-21", **kw}

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.post("/api/join/cafe", json=body)
        return asyncio.get_event_loop().run_until_complete(run())

    print("\nInscription : le serveur vérifie aussi (UX10)")
    for field, bad, word in (("phone", "abc", "téléphone"), ("phone", "12", "téléphone"),
                             ("postal_code", "ABCDE", "Code postal"), ("postal_code", "3700", "Code postal"),
                             ("birthday", "13-99", "naissance"), ("birthday", "30/02/1990", "naissance"),
                             ("birthday", "25/12", "naissance"),      # the year is asked now (2026-10-09)
                             ("email", "pas-un-mail", "e-mail"), ("name", "   ", "nom")):
        r = join(**{field: bad})
        check(f"{field} « {bad} » is refused, in French ({r.status_code})", r.status_code == 400 and word in r.json()["detail"])
    r = join()
    check("a valid signup goes through", r.status_code == 200 and r.json().get("barcode_id"))
    c = db.customers.find_one({"barcode_id": r.json()["barcode_id"]})
    check("the birthday is stored as MM-DD, the full date beside it",
          c["birthday"] == "12-25" and c.get("birth_date") == "1990-12-25")
    r = join(phone="+33 6 98 76 54 32", birthday="29/02/2000", name="Paul")
    check("« 29/02/2000 » is read as 02-29", r.status_code == 200
          and db.customers.find_one({"barcode_id": r.json()["barcode_id"]})["birthday"] == "02-29")

    print("\nLe formulaire")
    jp = open(os.path.join(ROOT, "src", "pages", "JoinPage.jsx")).read()
    check("date of birth: JJ/MM/AAAA (2026-10-09), no free « MM-DD »", 'placeholder="MM-DD"' not in jp
          and 'placeholder="JJ/MM/AAAA"' in jp)
    check("postal code: 5 digits", 'maxLength={5}' in jp and "postalDigits" in jp)

    print("\nImport (UX01)")
    ci = open(os.path.join(ROOT, "src", "components", "ClientImport.jsx")).read()
    check("the e-mail is not ticked in advance", "const [invite, setInvite] = useState(false);" in ci
          and "setInvite(Boolean(data.mailer_ready" not in ci)
    check("the button says how many e-mails will go", "et envoyer ${nf(willEmail)} email" in ci)

    print("\nBoutons à icône (UX02)")
    cp = open(os.path.join(ROOT, "src", "pages", "ClientsPage.jsx")).read()
    sp = open(os.path.join(ROOT, "src", "pages", "SegmentationPage.jsx")).read()
    check("Clients: save / cancel the filter are named", 'aria-label="Enregistrer ce filtre"' in cp
          and "aria-label=\"Annuler l'enregistrement du filtre\"" in cp)
    check("Segmentation: the ⋮ menu is named and says it opens a menu",
          "aria-label={`Actions pour le segment" in sp and 'aria-haspopup="menu"' in sp)
    check("close buttons are named", cp.count('aria-label="Fermer"') >= 1 and sp.count('aria-label="Fermer"') >= 2)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
