"""
Lien d'inscription & QR — the link, its renames, its figures, its page.

Run:
    cd api && python3 tests/test_join_link.py
"""
import datetime as dt
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import join_link as J

    db = server.db
    J.init(db)
    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    class TD:
        email, role, tenant_id = "owner@x.fr", "business_owner", "t1"

    def refused(fn):
        try:
            fn()
        except HTTPException as e:
            return e.detail
        return None

    now = dt.datetime.now(dt.timezone.utc)
    days = lambda n: now - dt.timedelta(days=n)
    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "slug": "le-corner-cafe", "city": "Tours"})
    db.tenants.insert_one({"id": "t2", "name": "Voisin", "slug": "le-voisin"})
    db.card_templates.insert_one({"tenant_id": "t1", "logo_url": "data:image/png;base64,AAAA"})

    # ---- names ---------------------------------------------------------------
    print("\nLe nom du lien")
    check("accents and spaces become a clean name", J.normalize_slug("Le Corner Café !") == "le-corner-cafe")
    check("the shop's own name is available to it", J.check_slug("le-corner-cafe", "t1")["available"])
    check("another shop's name is not", "déjà pris" in J.check_slug("le-voisin", "t1")["reason"])
    check("too short is refused", not J.check_slug("ab", "t1")["available"])
    check("an app word is reserved", "réservé" in J.check_slug("admin", "t1")["reason"])
    check("a free name is available", J.check_slug("Corner Tours", "t1") == {
        "slug": "corner-tours", "available": True, "reason": ""})

    out = J.put_slug(J.SlugIn(slug="Corner Tours"), token_data=TD())
    t = db.tenants.find_one({"id": "t1"})
    check("renaming sets the new name", out["shop"]["slug"] == "corner-tours" and t["slug"] == "corner-tours")
    check("and keeps the old one", t["previous_slugs"] == ["le-corner-cafe"])
    check("so a QR code printed with the old name still finds the shop",
          J.tenant_by_slug("le-corner-cafe")["id"] == "t1")
    check("the core signup endpoint follows it too",
          server.get_join_info("le-corner-cafe")["slug"] == "corner-tours")
    check("nobody else can take the old name", "déjà pris" in J.check_slug("le-corner-cafe", "t2")["reason"])
    check("a new shop is never given it either", server._unique_slug("Le Corner Café") != "le-corner-cafe")
    J.put_slug(J.SlugIn(slug="le-corner-cafe"), token_data=TD())
    t = db.tenants.find_one({"id": "t1"})
    check("taking an old name back makes it live again, not 'previous'",
          t["slug"] == "le-corner-cafe" and "le-corner-cafe" not in t["previous_slugs"])
    check("a refused name changes nothing",
          refused(lambda: J.put_slug(J.SlugIn(slug="le-voisin"), token_data=TD()))
          and db.tenants.find_one({"id": "t1"})["slug"] == "le-corner-cafe")

    # ---- figures ---------------------------------------------------------------
    print("\nLes chiffres")
    db.customers.insert_many(
        [{"id": f"n{i}", "tenant_id": "t1", "created_at": days(3), "signup_channel": "join_page"} for i in range(6)]
        + [{"id": f"p{i}", "tenant_id": "t1", "created_at": days(40)} for i in range(4)]
        + [{"id": f"o{i}", "tenant_id": "t1", "created_at": days(400)} for i in range(5)]
        + [{"id": "x", "tenant_id": "t2", "created_at": days(1)}])
    s = J.stats("t1")
    check("nouveaux inscrits counts the last 30 days", s["new_signups"]["value"] == 6)
    check("against the 30 before (4 → 6 = +50 %)", s["new_signups"]["delta_pct"] == 50.0)
    check("total des inscrits is everyone, since the start", s["total"]["value"] == 15)
    check("before any visit is measured there is no conversion rate, not a fake one",
          s["conversion"]["value"] is None and s["tracking_since"] is None)

    for i in range(3):
        J.record_view("le-corner-cafe", J.ViewIn(visitor=f"visitor-{i:04d}", src="qr_store"))
    J.record_view("le-corner-cafe", J.ViewIn(visitor="visitor-0000", src="qr_store"))   # same day again
    J.record_view("le-corner-cafe", J.ViewIn(visitor="visitor-insta1", src="instagram"))
    J.record_view("corner-tours", J.ViewIn(visitor="visitor-oldlink", src="bogus"))     # an old name
    check("a reload the same day is not a second visit",
          db.join_views.count_documents({"tenant_id": "t1", "visitor": "visitor-0000"}) == 1)
    check("a visit through an old name counts for the shop",
          db.join_views.count_documents({"tenant_id": "t1", "visitor": "visitor-oldlink"}) == 1)
    check("an unknown source is kept as none", db.join_views.find_one({"visitor": "visitor-oldlink"})["src"] is None)
    check("a visitor id too short to be real is ignored",
          J.record_view("le-corner-cafe", J.ViewIn(visitor="x"))["ok"] is False)
    check("an unknown shop is ignored", J.record_view("nowhere", J.ViewIn(visitor="visitor-9999"))["ok"] is False)

    s = J.stats("t1")
    # « Scans QR » = the cards scanned at the till, since the start (user, 2026-10-14),
    # whatever channel the client signed up through — not the page's visits
    check(f"scans QR are the till's visits ({s['qr_scans']['value']})",
          s["qr_scans"]["value"] == db.visits.count_documents({"tenant_id": "t1"}))
    db.visits.insert_many([{"id": f"vq{i}", "tenant_id": "t1", "customer_id": "x", "visit_time": days(400)} for i in range(2)])
    check("…all of them, a year ago too", J.stats("t1")["qr_scans"]["value"] == db.visits.count_documents({"tenant_id": "t1"}))
    # measured from the first visit (seconds ago): 0 signups since then over 5 visits
    check("conversion compares signups and visits over the same span only", s["conversion"]["value"] == 0.0)

    # Pretend tracking started two months ago, with visits in both windows.
    db.join_views.delete_many({})
    rows = ([{"tenant_id": "t1", "visitor": f"v{i}", "day": f"a{i}", "at": days(10), "src": "qr_store"} for i in range(40)]
            + [{"tenant_id": "t1", "visitor": f"w{i}", "day": f"b{i}", "at": days(45), "src": "qr_store"} for i in range(20)]
            + [{"tenant_id": "t1", "visitor": "first", "day": "c", "at": days(70), "src": None}])
    db.join_views.insert_many(rows)
    db.customers.insert_many([{"id": f"q{i}", "tenant_id": "t1", "created_at": days(45),
                               "signup_channel": "join_page"} for i in range(2)])
    s = J.stats("t1")
    check("conversion now: 6 signups / 40 visits = 15 %", s["conversion"]["value"] == 15.0)
    check("and its change in points against the window before (2/20 = 10 % → +5)",
          s["conversion"]["delta_pts"] == 5.0)
    check("imports and staff-created clients are not counted as page signups",
          all(c.get("signup_channel") != "join_page" for c in db.customers.find({"id": {"$regex": "^p"}})))

    # ---- the page ---------------------------------------------------------------------
    print("\nLa page d'inscription")
    d = J.get_join_link(token_data=TD())
    check("the tab gets the shop, the figures and the page's words",
          d["shop"]["name"] == "Le Corner Café" and d["shop"]["city"] == "Tours" and "stats" in d)
    check("the logo comes from the Carte de fidélité", d["shop"]["logo_url"].startswith("data:image"))
    check("an untouched page reads the design's words",
          d["page"]["title"] == "Rejoignez notre programme de fidélité !"
          and d["page"]["button"] == "Je m'inscris" and len(d["page"]["benefits"]) == 4)
    J.put_page(J.PageIn(title="Bienvenue au Corner !", subtitle="Un café offert au 10e.",
                        benefits=["Un café offert", " ", "Des offres"], button="Je rejoins"), token_data=TD())
    pub = J.public_page("le-corner-cafe")
    check("the owner's words reach the public page",
          pub["page"]["title"] == "Bienvenue au Corner !" and pub["page"]["button"] == "Je rejoins")
    check("empty benefits are dropped", pub["page"]["benefits"] == ["Un café offert", "Des offres"])
    check("the public page answers under an old name too", J.public_page("corner-tours")["slug"] == "le-corner-cafe")
    check("an empty title is refused", refused(lambda: J.put_page(J.PageIn(title=" ", button="Go"), token_data=TD())))
    check("five benefits are refused",
          refused(lambda: J.put_page(J.PageIn(title="T", button="B", benefits=["a"] * 5), token_data=TD())))

    print("\nL'inscription elle-même")
    server.db.tenants.update_one({"id": "t1"}, {"$set": {"plan": "gold"}})
    try:
        r = server.join_program("corner-tours", server.JoinRequest(
            name="Marie Test", phone="0600000099", postal_code="37000", birthday="05-12",
            consent=True, acquisition_source="qr_store"))
        c = db.customers.find_one({"phone": "0600000099"})
        check("signing up through an old name lands in the right shop", c and c["tenant_id"] == "t1")
        check("and is marked as a signup through the page", c and c.get("signup_channel") == "join_page")
    except HTTPException as e:
        check(f"signup through the page works (refused: {e.detail})", False)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
