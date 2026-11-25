"""
The card page's 3rd home tile (user, 2026-11-25): a call-to-action button —
« Prendre rendez-vous » by default — whose name and link only the FidClic
super admin sets, per établissement (store). A shop without bookings gets
any name (« Commander », « Voir le menu ») and link.

    GET /api/admin/commerces/{tid}/card-cta              each store + its button
    PUT /api/admin/commerces/{tid}/card-cta/{store_id}   {label, url}
    GET /api/card/{bc}  → card.cta = {label, url|null} of the card's own store

Unit: the label / url rules (card_page.clean_cta_label / clean_cta_url /
cta_for). HTTP on the mongomock server: who may read / write, other
businesses and stores, owner saves that try to slip the field in, the payload
per store. Run: cd api && python3 tests/test_card_cta.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-cta")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def raises(fn):
    try:
        fn()
    except ValueError as e:
        return str(e) or True
    return False


def unit():
    from features import card_page as CP
    print("unit — label")
    check("default label", CP.CTA_DEFAULT_LABEL == "Prendre rendez-vous")
    check("trimmed", CP.clean_cta_label("  Commander  ") == "Commander")
    check("28 chars ok", CP.clean_cta_label("x" * 28) == "x" * 28)
    check("29 chars refused", raises(lambda: CP.clean_cta_label("x" * 29)))
    check("1 char ok", CP.clean_cta_label("A") == "A")
    for bad in ("", "   ", None, 42, ["x"], "a\nb", "a\tb", "a\x00b", "<b>x</b>", "<img src=x onerror=alert(1)>", "a>b"):
        check(f"label refused: {bad!r}", raises(lambda b=bad: CP.clean_cta_label(b)))
    check("accents and apostrophes are plain text", CP.clean_cta_label("Réserver l’atelier & co") == "Réserver l’atelier & co")

    print("unit — url")
    check("empty → no link", CP.clean_cta_url("") is None and CP.clean_cta_url(None) is None and CP.clean_cta_url("  ") is None)
    check("https kept", CP.clean_cta_url("https://www.planity.com/royal-trim-37000") == "https://www.planity.com/royal-trim-37000")
    check("trimmed", CP.clean_cta_url("  https://www.planity.com/x  ") == "https://www.planity.com/x")
    check("no scheme → https:// added", CP.clean_cta_url("www.planity.com/x") == "https://www.planity.com/x")
    check("host lower-cased", CP.clean_cta_url("https://WWW.Planity.COM/X") == "https://www.planity.com/X")
    check("query + fragment kept", CP.clean_cta_url("https://a.fr/r?x=1&y=2#top") == "https://a.fr/r?x=1&y=2#top")
    for bad in ("http://planity.com/x", "javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>x</script>",
                "vbscript:x", "ftp://a.fr/x", "//evil.com/x", "https://", "https:///x", "https://a b.fr", "https://a.fr/x y",
                "https://user:pw@evil.com", "https://planity.com@evil.com", "https://a.fr\\@evil.com", "https://a.fr:8443/x",
                "https://localhost/x", "https://127.0.0.1/x", "https://exámple.com", "https://a.fr/\x00",
                "https://" + "a" * 490 + ".fr", 42, ["https://a.fr"], "mailto:a@b.fr", "tel:0611"):
        check(f"url refused: {str(bad)[:40]!r}", raises(lambda b=bad: CP.clean_cta_url(b)))
    check("500 chars is the limit", CP.clean_cta_url("https://a.fr/" + "x" * (500 - 13)) is not None
          and raises(lambda: CP.clean_cta_url("https://a.fr/" + "x" * (501 - 13))))

    print("unit — cta_for")
    t = {"card_cta": {"main": {"label": "Commander", "url": "https://a.fr/menu"},
                      "pal": {"label": "Prendre rendez-vous", "url": None},
                      "bad": {"label": "<script>", "url": "javascript:alert(1)"},
                      "odd": "not a dict"}}
    check("its own store", CP.cta_for(t, "main") == {"label": "Commander", "url": "https://a.fr/menu"})
    check("a store without a link", CP.cta_for(t, "pal") == {"label": "Prendre rendez-vous", "url": None})
    check("a store never set: the default", CP.cta_for(t, "zzz") == {"label": "Prendre rendez-vous", "url": None})
    check("no store id: the main store", CP.cta_for(t, None) == CP.cta_for(t, "main"))
    check("a stored value that breaks the rules is never served",
          CP.cta_for(t, "bad") == {"label": "Prendre rendez-vous", "url": None})
    check("junk stored", CP.cta_for(t, "odd") == {"label": "Prendre rendez-vous", "url": None})
    check("no tenant / no map", CP.cta_for(None, "main") == CP.cta_for({}, "main") == CP.cta_for({"card_cta": "x"}, "main")
          == {"label": "Prendre rendez-vous", "url": None})
    check("one-store account whose only branch is not « main »",
          CP.cta_for({"branches": [{"id": "b1"}], "card_cta": {"b1": {"label": "Voir le menu", "url": None}}}, None)["label"]
          == "Voir le menu")


def http_suite():
    import auth
    import server
    import httpx
    from services import card_owner as CO

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers or {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def tok(email, role, tenant=None, **extra):
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant, "active": True, **extra}},
                            upsert=True)
        claims = {"sub": email, "role": role, **({"tenant_id": tenant} if tenant else {})}
        return {"Authorization": "Bearer " + auth.create_access_token(claims)}

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIBERTÉ", "is_main": True},
                                        {"id": "pal", "name": "PALISSY"},
                                        {"id": "old", "name": "FERMÉE", "status": "closed"}]})
    db.tenants.insert_one({"id": "t2", "slug": "gs", "name": "GREEN SMOKE", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db["card_templates"]._real.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps",
                                           "cta": {"label": "Owner injected", "url": "https://evil.example.com"}})
    db["card_templates"]._real.insert_one({"tenant_id": "t2", "store_id": None, "programme": "stamps"})

    def cust(cid, tid, branch=None):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": cid.title(), "visits": 1,
                                 "points": 0, "branch_id": branch})
        return bc

    BC_MAIN, BC_PAL, BC_T2, BC_NONE = cust("marie", "t1", "main"), cust("paul", "t1", "pal"), cust("zoe", "t2"), cust("noe", "t1")
    key = lambda bc: {"X-Card-Key": CO.key_for(bc)}   # noqa: E731

    BOSS = tok("boss@fidclic.com", "super_admin")
    db.platform_roles.insert_one({"id": "editeur", "perms": {"commerces": {"view": True, "edit": True}}})
    db.platform_roles.insert_one({"id": "aveugle", "perms": {}})
    TEAM = tok("eve@fidclic.com", "fidclic_team", platform_role="editeur")
    BLIND = tok("bob@fidclic.com", "fidclic_team", platform_role="aveugle")
    OWNER = tok("o@t1.fr", "business_owner", "t1")
    MANAGER = tok("m@t1.fr", "manager", "t1", branch_ids=["main", "pal"])
    STAFF = tok("s@t1.fr", "staff", "t1")
    OWNER2 = tok("o@t2.fr", "business_owner", "t2")
    BASE = "/api/admin/commerces"

    print("http — the default, before anything is set")
    card = http("GET", f"/api/card/{BC_MAIN}", key(BC_MAIN)).json().get("card", {})
    check("card.cta: « Prendre rendez-vous », no link", card.get("cta") == {"label": "Prendre rendez-vous", "url": None})
    check("the owner's card designer cannot put its own cta in the payload", card.get("cta", {}).get("label") != "Owner injected")
    g = http("GET", f"{BASE}/t1/card-cta", BOSS)
    rows = g.json().get("stores", []) if g.status_code == 200 else []
    check("super admin reads every open store", g.status_code == 200 and [r["id"] for r in rows] == ["main", "pal"])
    check("… each with the default", all(r["label"] == "Prendre rendez-vous" and r["url"] is None and r["is_set"] is False
                                         for r in rows))
    check("… names and main flag", rows and rows[0]["name"] == "LIBERTÉ" and rows[0]["is_main"] and not rows[1]["is_main"])
    g2 = http("GET", f"{BASE}/t2/card-cta", BOSS).json()
    check("a one-shop business: its single store is « main »", [r["id"] for r in g2.get("stores", [])] == ["main"])

    print("http — the super admin sets two stores differently")
    r1 = http("PUT", f"{BASE}/t1/card-cta/main", BOSS, json={"label": " Prendre rendez-vous ", "url": "https://www.planity.com/rt-liberte"})
    r2 = http("PUT", f"{BASE}/t1/card-cta/pal", BOSS, json={"label": "Commander", "url": "www.ubereats.com/fr/store/rt"})
    check("saved (main)", r1.status_code == 200 and r1.json() == {"id": "main", "label": "Prendre rendez-vous",
                                                                   "url": "https://www.planity.com/rt-liberte", "is_set": True})
    check("saved (pal), link normalised", r2.status_code == 200 and r2.json().get("url") == "https://www.ubereats.com/fr/store/rt")
    check("stored on the tenant per store", (db.tenants.find_one({"id": "t1"}) or {}).get("card_cta", {}).get("pal", {}).get("label")
          == "Commander")
    c_main = http("GET", f"/api/card/{BC_MAIN}", key(BC_MAIN)).json()["card"]["cta"]
    c_pal = http("GET", f"/api/card/{BC_PAL}", key(BC_PAL)).json()["card"]["cta"]
    c_none = http("GET", f"/api/card/{BC_NONE}", key(BC_NONE)).json()["card"]["cta"]
    c_t2 = http("GET", f"/api/card/{BC_T2}", key(BC_T2)).json()["card"]["cta"]
    check("Liberté's card shows Liberté's button", c_main == {"label": "Prendre rendez-vous", "url": "https://www.planity.com/rt-liberte"})
    check("Palissy's card shows Palissy's button", c_pal == {"label": "Commander", "url": "https://www.ubereats.com/fr/store/rt"})
    check("a client with no store: the main store's", c_none == c_main)
    check("another business is untouched", c_t2 == {"label": "Prendre rendez-vous", "url": None})
    check("?store= on the card cannot pick another store's button",
          http("GET", f"/api/card/{BC_MAIN}?store=pal", key(BC_MAIN)).json()["card"]["cta"] == c_main)
    check("a store header cannot pick another store's button either (client without a store)",
          http("GET", f"/api/card/{BC_NONE}", {**key(BC_NONE), "X-FidClic-Store": "pal"}).json()["card"]["cta"] == c_main)
    check("a shop login viewing a card sees that card's own store",
          http("GET", f"/api/card/{BC_PAL}", MANAGER).json().get("card", {}).get("cta") == c_pal)
    rows = http("GET", f"{BASE}/t1/card-cta", BOSS).json()["stores"]
    check("the admin list reads them back", [(r["label"], r["is_set"]) for r in rows] == [("Prendre rendez-vous", True), ("Commander", True)])
    r3 = http("PUT", f"{BASE}/t1/card-cta/pal", BOSS, json={"label": "Voir le menu", "url": ""})
    check("a link can be removed", r3.status_code == 200 and r3.json()["url"] is None
          and http("GET", f"/api/card/{BC_PAL}", key(BC_PAL)).json()["card"]["cta"] == {"label": "Voir le menu", "url": None})
    check("url missing from the body = no link", http("PUT", f"{BASE}/t1/card-cta/pal", BOSS, json={"label": "Voir le menu"}).json()
          .get("url", "x") is None)
    http("PUT", f"{BASE}/t1/card-cta/pal", BOSS, json={"label": "Commander", "url": "https://www.ubereats.com/fr/store/rt"})
    logs = list(db.audit_log.find({"action": "admin.card_cta", "tenant_id": "t1"})) or \
        list(db.audit_logs.find({"action": "admin.card_cta", "tenant_id": "t1"}))
    check("every change is in the audit log (who, which store, before/after)",
          logs and logs[-1].get("actor") == "boss@fidclic.com" and logs[-1].get("meta", {}).get("store") == "pal"
          and "before" in logs[-1].get("meta", {}))

    print("http — bad input")
    for body, why in (({"label": "", "url": None}, "empty label"), ({"label": "x" * 29}, "label too long"),
                      ({"label": "<script>alert(1)</script>"}, "html in label"), ({"label": "a\nb"}, "newline in label"),
                      ({"label": 5}, "label not text"), ({}, "no label"),
                      ({"label": "Ok", "url": "javascript:alert(1)"}, "javascript:"),
                      ({"label": "Ok", "url": "data:text/html;base64,PHNjcmlwdD4="}, "data:"),
                      ({"label": "Ok", "url": "http://planity.com"}, "http"),
                      ({"label": "Ok", "url": "https://planity.com@evil.com"}, "userinfo"),
                      ({"label": "Ok", "url": "https://a.fr/ x"}, "space"),
                      ({"label": "Ok", "url": "https://a.fr/" + "x" * 600}, "too long"),
                      ({"label": "Ok", "url": 12}, "url not text")):
        r = http("PUT", f"{BASE}/t1/card-cta/main", BOSS, json=body)
        check(f"400 — {why}", r.status_code in (400, 422) and isinstance(r.json().get("detail"), (str, list)))
    check("nothing bad was stored", http("GET", f"/api/card/{BC_MAIN}", key(BC_MAIN)).json()["card"]["cta"] == c_main)
    check("a closed store is 404", http("PUT", f"{BASE}/t1/card-cta/old", BOSS, json={"label": "Ok"}).status_code == 404)
    check("a store of another business is 404", http("PUT", f"{BASE}/t2/card-cta/pal", BOSS, json={"label": "Ok"}).status_code == 404)
    check("an unknown business is 404", http("PUT", f"{BASE}/nope/card-cta/main", BOSS, json={"label": "Ok"}).status_code == 404
          and http("GET", f"{BASE}/nope/card-cta", BOSS).status_code == 404)
    for sid in ("$where", "main.x", "a.b"):
        check(f"a store id that would be a Mongo path is refused: {sid}",
              http("PUT", f"{BASE}/t1/card-cta/{sid}", BOSS, json={"label": "Ok"}).status_code in (400, 404))
    check("… and wrote nothing", set((db.tenants.find_one({"id": "t1"}) or {}).get("card_cta", {})) == {"main", "pal"})

    print("http — nobody else may write it")
    for name, h in (("owner", OWNER), ("manager", MANAGER), ("staff", STAFF), ("another business's owner", OWNER2),
                    ("a FidClic team member (even with « Modifier commerces »)", TEAM), ("a team member without rights", BLIND),
                    ("no login", None)):
        r = http("PUT", f"{BASE}/t1/card-cta/main", h, json={"label": "Hacked", "url": "https://evil.example.com"})
        check(f"{name}: refused ({r.status_code})", r.status_code in (401, 403))
    check("owner / manager / staff cannot read the admin list either",
          all(http("GET", f"{BASE}/t1/card-cta", h).status_code in (401, 403) for h in (OWNER, MANAGER, STAFF, BLIND, None)))
    check("a team member with « Voir commerces » may read it", http("GET", f"{BASE}/t1/card-cta", TEAM).status_code == 200)
    # the owner's own saves cannot slip the field in
    http("PUT", "/api/owner/etablissement", OWNER, json={"card_cta": {"main": {"label": "Hacked", "url": "https://evil.example.com"}},
                                                         "business": {"card_cta": {"main": {"label": "Hacked"}}}})
    http("PUT", "/api/owner/etablissement/stores/main", OWNER, json={"name": "LIBERTÉ", "card_cta": {"label": "Hacked"},
                                                                     "cta": {"label": "Hacked"}})
    http("PUT", "/api/owner/settings/geo", OWNER, json={"geo_enabled": True, "card_cta": {"main": {"label": "Hacked"}}})
    http("POST", "/api/owner/card-template/details", OWNER, json={"cta": {"label": "Hacked", "url": "https://evil.example.com"}})
    after = (db.tenants.find_one({"id": "t1"}) or {}).get("card_cta", {})
    check("owner saves never write card_cta", after.get("main", {}).get("label") == "Prendre rendez-vous"
          and "Hacked" not in str(after))
    check("the card still shows the super admin's button",
          http("GET", f"/api/card/{BC_MAIN}", key(BC_MAIN)).json()["card"]["cta"] == c_main)
    vtok = auth.create_access_token({"sub": "o@t1.fr", "role": "business_owner", "tenant_id": "t1", "view_by": "boss@fidclic.com"})
    check("a « view as » owner session is not the super admin either",
          http("PUT", f"{BASE}/t1/card-cta/main", {"Authorization": f"Bearer {vtok}"}, json={"label": "Hacked"}).status_code in (401, 403))

    print("http — reading the card")
    check("another card's key does not open this card (nor its button)",
          http("GET", f"/api/card/{BC_MAIN}", key(BC_PAL)).status_code == 403)
    check("another business's owner cannot read the card", http("GET", f"/api/card/{BC_MAIN}", OWNER2).status_code == 403)


if __name__ == "__main__":
    unit()
    http_suite()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
