"""
FidClic IA safety fixes (user, 2026-10-29) — the open pentest points:

    P31  small sends: the témoin keeps max(4, 15 %) of the clients, never more
         than half, nobody under 3 (user's table: 3→1, 4–5→2, 6–7→3, 8–26→4,
         27+→15 %), so splitting a send in small ones no longer escapes it.
    P25  « template: client » (the one-client « Contacter ») no longer frees a
         group send from the témoin: only a send to ONE client is free.
    P07  a placeholder value (client name, product, sponsor…) is put in once:
         it never carries HTML, and a « {points} » inside it stays text.
    CSV  a cell typed by a client or an owner that Excel would run as a
         formula (= + - @) gets a leading apostrophe, in every export.
    Signup keeps only a known sector (the register path saved anything).
    Mail the super admin's AI report escapes the shop names it lists.

Run: cd api && /usr/local/bin/python3 tests/test_ai_safety.py
"""
import asyncio
import contextlib
import datetime as dt
import io
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-ai-safety")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
UTC = dt.timezone.utc


def check(label, cond, show=None):
    global passed, failed
    cond = bool(cond)
    if not cond and show is not None:
        print("    →", show)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    with contextlib.redirect_stdout(io.StringIO()):
        import server
    import auth
    import httpx
    import features.wallet_passes as WP
    import features.push_subscriptions as PS
    from features import temoin as T

    db = server.db
    pushed = []
    server.dispatch_to_customer = lambda tid, cust, title, body, kind="campaign", url=None: (
        pushed.append((cust["id"], kind)) or {"sent": True})
    WP.notify_passes = lambda *a, **k: {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    PS.fan_out_to_customer = lambda *a, **k: {"sent": 0}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    now = dt.datetime.now(UTC).replace(microsecond=0)
    db.tenants.insert_one({"id": "t1", "slug": "cafe", "name": "Café", "sector": "cafe", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.card_templates.insert_one({"tenant_id": "t1", "programme": "stamps"})
    db.users.insert_many([{"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True},
                          {"email": "boss@fidclic.com", "role": "super_admin", "first_name": "B"}])
    tok = lambda e, r, t="t1": {"Authorization": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})}  # noqa: E731
    H, BOSS = tok("o@x.fr", "business_owner"), tok("boss@fidclic.com", "super_admin", None)
    for i in range(40):
        db.customers.insert_one({"id": f"c{i:02d}", "tenant_id": "t1", "name": f"Client {i}", "visits": 2,
                                 "created_at": now - dt.timedelta(days=200), "barcode_id": f"B{i}",
                                 "last_visit_date": now - dt.timedelta(days=100)})

    # -------------------------------------------------------------------
    print("P31 — le groupe témoin des petits envois (tableau de l'utilisateur)")
    table = {0: 0, 1: 0, 2: 0, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 10: 4, 15: 4, 19: 4, 20: 4, 26: 4,
             27: 4, 33: 4, 34: 5, 40: 6, 100: 15, 1000: 150}
    got = {n: T.hold_count(n) for n in table}
    check("hold_count follows the table at every edge", got == table, {n: (got[n], table[n]) for n in table if got[n] != table[n]})
    check("never more than half, never the whole send", all(T.hold_count(n) <= n // 2 for n in range(0, 300)))
    check("a negative or odd count holds nobody", T.hold_count(-3) == 0)
    sent, held = T.split("t1", [{"id": f"p{i}"} for i in range(8)], "s8")
    check("8 clients: 4 messaged, 4 témoin, nobody twice",
          len(sent) == 4 and len(held) == 4 and not {c["id"] for c in sent} & {c["id"] for c in held})
    check("2 clients: both messaged", T.split("t1", [{"id": "a"}, {"id": "b"}], "s2")[1] == [])

    r = http("POST", "/api/owner/campaigns/audience-preview", headers=H,
             json={"audience": {"mode": "custom", "customer_ids": [f"c{i:02d}" for i in range(6)]}})
    check("the composer says 3 of 6 are kept out", r.status_code == 200 and r.json()["temoin"] == 3, r.json())
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Petit", "message": "Bonjour", "audience": {"mode": "custom",
                                                                       "customer_ids": [f"c{i:02d}" for i in range(6)]}})
    c = db.campaigns.find_one({"id": r.json().get("id")}) or {}
    check("a send to 6: 3 messaged, 3 témoin (was: nobody held)",
          r.status_code == 200 and len(c.get("recipient_ids") or []) == 3 and len(c.get("holdout_ids") or []) == 3, r.json())
    # the audit's attack: one big send cut in sends of 6
    tot = 0
    for k in range(5):
        ids = [f"c{i:02d}" for i in range(6 * k, 6 * k + 6)]
        r = http("POST", "/api/owner/campaigns/send-to-group", headers=H,
                 json={"customer_ids": ids, "name": f"Lot {k}", "content": "Bonjour"})
        tot += int(r.json().get("temoin") or 0)
    check("5 sends of 6 clients: the témoin is still drawn (15 in all)", tot == 15, tot)
    s = http("GET", "/api/owner/temoin", headers=H).json()
    check("Paramètres gets the minimum too (4)", s.get("min_hold_send") == 4, s)

    # -------------------------------------------------------------------
    print("P25 — « template: client » ne contourne plus le témoin")
    people = [{"id": f"p{i}"} for i in range(100)]
    check("a group send labelled « client » keeps its 15 témoin", len(T.split("t1", people, "x", "client")[1]) == 15)
    check("… and « brain » too", len(T.split("t1", people, "x", "brain")[1]) == 15)
    check("one client (« Contacter », profil): still never", T.split("t1", people[:1], "x", "client")[1] == [])
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Tous", "message": "Bonjour", "audience": {"mode": "all"}, "template": "client"})
    c = db.campaigns.find_one({"id": r.json().get("id")}) or {}
    check("the composer, everyone, template « client »: 6 témoin of 40",
          r.status_code == 200 and len(c.get("holdout_ids") or []) == 6, r.json())
    p = http("POST", "/api/owner/campaigns/audience-preview", headers=H,
             json={"audience": {"mode": "all"}, "template": "client"}).json()
    check("… and the preview says so", p.get("temoin") == 6, p)
    r = http("POST", "/api/owner/campaigns/compose", headers=H,
             json={"title": "Pour vous", "message": "Bonjour", "customer_ids": ["c01"], "template": "client"})
    check("« Contacter » one client: sent, no témoin", r.json().get("audience") == 1
          and not (db.campaigns.find_one({"id": r.json()["id"]}) or {}).get("holdout_ids"), r.json())

    # -------------------------------------------------------------------
    print("P07 — les valeurs des variables")
    db.customers.insert_one({"id": "evil", "tenant_id": "t1", "name": "<img src=x onerror=alert(1)> {points}",
                             "visits": 3, "points": 30,
                             "brain": {"visits_with_items": 5,
                                       "top_items": [{"name": "<b>Coupe</b> {prénom}", "share": 0.9}]}})
    ev = db.customers.find_one({"id": "evil"}, {"_id": 0})
    out = server.render_template("Salut {prénom}, votre {produit_habituel} · {name} · {points}", ev,
                                 db.tenants.find_one({"id": "t1"}))
    check("no « < » nor « > » reaches the message", "<" not in out and ">" not in out, out)
    check("a « {points} » typed in a name stays text (put in once)", out.count("30") == 1 and "{points}" in out, out)
    check("a « {prénom} » inside a product stays text", "Coupe {prénom}" in out, out)
    check("normal values still fill in", server.render_template("Bonjour {prénom} ({visits})",
                                                                {"name": "Zoé Martin", "visits": 4}) == "Bonjour Zoé (4)")
    check("an unknown « {truc} » is left as is", server.render_template("A {truc} B", {"name": "Zoé"}) == "A {truc} B")
    check("empty text stays empty", server.render_template("", {"name": "Zoé"}) == "")
    from features import automations as AU
    a = AU._render("Grâce à {parrain}, {prénom} !", {"id": "c01", "name": "Léa Roy"}, {"id": "t1", "name": "Café"},
                   {"parrain": "{points} <script>"})
    check("automations: a sponsor's name is put in once, without HTML",
          a == "Grâce à {points} , Léa !", a)

    # -------------------------------------------------------------------
    print("CSV — une cellule n'est jamais une formule")
    from services import safe_csv
    for v, want in [("=HYPERLINK(\"http://x\",\"y\")", "'=HYPERLINK(\"http://x\",\"y\")"), ("+1+1", "'+1+1"),
                    ("-2+3", "'-2+3"), ("@SUM(A1)", "'@SUM(A1)"), ("\t=1", "'\t=1"), ("\r=1", "'\r=1"),
                    ("Zoé", "Zoé"), ("", ""), ("-5,00", "-5,00"), ("+33 6 12 34 56 78", "+33 6 12 34 56 78"),
                    ("-12.5 €", "-12.5 €"), ("+4 %", "+4 %"), (-5, -5), (None, None), (3.5, 3.5)]:
        check(f"cell {v!r} → {want!r}", safe_csv.cell(v) == want, safe_csv.cell(v))
    buf = io.StringIO()
    safe_csv.writer(buf).writerows([["a", "=1"], ["b", 2]])
    check("the writer keeps « ; » and quotes as before", buf.getvalue() == "a;'=1\r\nb;2\r\n", repr(buf.getvalue()))
    root = pathlib.Path(__file__).resolve().parent.parent
    raw = [f"{p.relative_to(root)}:{i}" for p in sorted(root.glob("**/*.py")) if "tests" not in p.parts
           and p.name != "safe_csv.py"
           for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if re.search(r"\bcsv\.(writer|DictWriter)\(", line)]
    check("no export writes CSV without the guard", not raw, raw)
    db.customers.update_one({"id": "c05"}, {"$set": {"name": "=HYPERLINK(\"http://evil\",\"Cliquez\")"}})
    body = http("GET", "/api/owner/clients/export", headers=H).content.decode("utf-8-sig")
    line = next((ln for ln in body.split("\r\n") if "HYPERLINK" in ln), "")
    check("Clients › Exporter: a client's « =HYPERLINK » name is text", line.startswith("\"'=HYPERLINK") or line.startswith("'=HYPERLINK"), line[:60])

    # -------------------------------------------------------------------
    print("Inscription — seul un secteur connu est gardé")
    import services.email_check as EC
    EC.check = lambda e: {"ok": True}
    base = {"first_name": "Nora", "last_name": "Ben", "password": "Cafe-Lumiere2026!", "accepted_terms": True,
            "role": "business_owner", "phone": "0611223344"}
    r = http("POST", "/api/auth/register", json={**base, "email": "nora1@gmail.com", "sector": "=HYPERLINK(\"x\")"})
    u = db.users.find_one({"email": "nora1@gmail.com"}) or {}
    t = db.tenants.find_one({"id": u.get("tenant_id")}) or {}
    check("a formula as sector is not saved", r.status_code == 200 and not t.get("sector"), (r.status_code, t.get("sector")))
    r = http("POST", "/api/auth/register", json={**base, "email": "nora2@gmail.com", "sector": "cafe"})
    u = db.users.find_one({"email": "nora2@gmail.com"}) or {}
    check("a real sector is kept", (db.tenants.find_one({"id": u.get("tenant_id")}) or {}).get("sector") == "cafe")

    # -------------------------------------------------------------------
    print("Rapport FIDCLIC AI par e-mail — les noms sont échappés")
    from features import admin_ai as AA
    html = AA._email_html({"key": "x", "kind": "sectors", "title": "T <i>", "headline": "H", "detail": "D",
                           "rows": [{"name": "<a href='http://evil'>Gagnez</a>", "commerces": 1, "clients": 2,
                                     "visites": 3, "visites_par_commerce": 3, "ca": 4, "panier": 5, "evolution": None}]})
    check("a shop name cannot put a link in the super admin's mail", "<a href='http://evil'>" not in html
          and "&lt;a href=" in html, html[:300])

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
