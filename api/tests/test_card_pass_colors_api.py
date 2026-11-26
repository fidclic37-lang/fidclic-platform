"""
« Ma carte en ligne » must look like the shop's real Wallet card (user,
2026-11-26: « door door tak card design se match nahi karta »). GET
/api/card/{bc} now says which colours the customer sees on the Apple card:

    card.pass_colors = {background, foreground, label, footer, name, poster}

  · from the active Apple Pass Designer design of the card's OWN store
    (features/pass_designer, one card_templates document per establishment),
  · else from FidClic's own pass colours (wallet_passes.derive_colors) and the
    card's fields (poster_footer_color, logo_text_color);
  · `footer` null = Apple's blur of the photo (the page reads the photo);
  · lower-case #rrggbb or null — nothing the owner typed reaches the page raw.

Run: cd api && python3 tests/test_card_pass_colors_api.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-card-pass-colors")
os.environ.setdefault("DISABLE_SEED", "1")

passed = failed = 0
HEX = re.compile(r"^#[0-9a-f]{6}$")


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def design(bg, fg, label, footer=None, style="posterGeneric", active=True):
    p = {style: {"primaryFields": [{"key": "member", "label": "MEMBRE", "value": "{prenom}"}]},
         "backgroundColor": bg, "foregroundColor": fg, "labelColor": label}
    if footer:
        p["footerBackgroundColor"] = footer
    return {"active": active, "pass": p, "images": []}


def main():
    import auth
    import server
    import httpx
    from services import card_owner as CO

    db = server.db

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    def login(role, tenant):
        email = f"{role}-{tenant}@x.fr"
        db.users.update_one({"email": email}, {"$set": {"email": email, "role": role, "tenant_id": tenant}}, upsert=True)
        return {"Authorization": "Bearer " + auth.create_access_token({"sub": email, "role": role, "tenant_id": tenant})}

    db.tenants.insert_one({"id": "t1", "slug": "rt", "name": "ROYAL TRIM", "is_active": True, "plan": "vip",
                           "subscription_status": "active",
                           "branches": [{"id": "main", "name": "LIBERTÉ", "is_main": True},
                                        {"id": "pal", "name": "PALISSY"},
                                        {"id": "mon", "name": "PL-MONSTRE"}]})
    db.tenants.insert_one({"id": "t2", "slug": "fc", "name": "FIDCLIC CAFÉ", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    db.tenants.insert_one({"id": "t3", "slug": "gs", "name": "GREEN", "is_active": True, "plan": "vip",
                           "subscription_status": "active"})
    real = db["card_templates"]._real
    # the account's card (Liberté reads it): black / white / grey in Pass Designer, no footer colour
    real.insert_one({"tenant_id": "t1", "store_id": None, "programme": "stamps",
                     "pass_designer": design("rgb(0, 0, 0)", "rgb(255, 255, 255)", "rgb(255,255,255)")})
    # Palissy: its own design — graphite, a bronze footer band, warm label
    real.insert_one({"tenant_id": "t1", "store_id": "pal", "programme": "stamps",
                     "pass_designer": design("rgb(30, 31, 34)", "#FFFFFF", "rgb(184, 148, 106)",
                                             footer="rgb(140, 106, 72)")})
    # PL-Monstre: a design switched OFF → FidClic's own colours, the card's own footer colour
    real.insert_one({"tenant_id": "t1", "store_id": "mon", "programme": "stamps", "surface_color": "#12211A",
                     "poster_footer_color": "#5D6236", "logo_text_color": "#C8A752",
                     "pass_designer": design("rgb(1,2,3)", "rgb(4,5,6)", "rgb(7,8,9)", active=False)})
    # FidClic blue + yellow, no Pass Designer: the poster's band = the owner's footer colour
    real.insert_one({"tenant_id": "t2", "store_id": None, "programme": "points_visit",
                     "surface_color": "#1450B8", "brand_color": "#1450B8", "poster_footer_color": "#1450b8",
                     "logo_text_color": "#F8B008"})
    # hostile values the owner (or an import) could store
    real.insert_one({"tenant_id": "t3", "store_id": None, "programme": "stamps",
                     "poster_footer_color": "red;}</style><script>alert(1)</script>",
                     "logo_text_color": "url(javascript:alert(1))", "poster_style": False,
                     "pass_designer": design("expression(alert(1))", "rgb(999, 0, 0)", "#12",
                                             style="storeCard")})

    def cust(cid, tid, branch=None):
        bc = f"FT-{cid.upper()}"
        db.customers.insert_one({"id": cid, "tenant_id": tid, "barcode_id": bc, "name": cid.title(),
                                 "visits": 2, "points": 0, "branch_id": branch})
        return bc

    LIB, PAL, MON, NONE = cust("lib1", "t1", "main"), cust("pal1", "t1", "pal"), cust("mon1", "t1", "mon"), cust("nob1", "t1")
    FC, GS = cust("fc1", "t2"), cust("gs1", "t3")

    def colors(bc, headers=None):
        r = http("GET", f"/api/card/{bc}", headers=headers if headers is not None else {"X-Card-Key": CO.key_for(bc)})
        return r.status_code, (r.json().get("card") or {}).get("pass_colors") if r.status_code == 200 else None

    print("1. Liberté: the account's Pass Designer design")
    st, pc = colors(LIB)
    check(f"200 + pass_colors present ({st}, {pc})", st == 200 and isinstance(pc, dict))
    check("background #000000", pc and pc.get("background") == "#000000")
    check("foreground / label white", pc and pc.get("foreground") == "#ffffff" and pc.get("label") == "#ffffff")
    check("no footer colour → null (Apple's blur of the photo)", pc and pc.get("footer") is None)
    check("a poster card", pc and pc.get("poster") is True)
    check("exactly the documented keys", pc and set(pc) == {"background", "foreground", "label", "footer", "name", "poster"})

    print("2. Palissy: its OWN design, never the account's")
    st, pp = colors(PAL)
    check(f"background graphite #1e1f22 ({pp})", pp and pp.get("background") == "#1e1f22")
    check("label bronze #b8946a", pp and pp.get("label") == "#b8946a")
    check("footer band #8c6a48", pp and pp.get("footer") == "#8c6a48")
    check("two stores, two answers", pc != pp)

    print("3. PL-Monstre: design switched off → FidClic's colours + the card's fields")
    st, pm = colors(MON)
    check(f"background = the card's surface #12211a ({pm})", pm and pm.get("background") == "#12211a")
    check("foreground = the readable ink FidClic draws (light on dark)", pm and pm.get("foreground") == "#f4f3f0")
    check("label: a hex", pm and HEX.match(pm.get("label") or ""))
    check("footer = poster_footer_color #5d6236", pm and pm.get("footer") == "#5d6236")
    check("name = logo_text_color #c8a752", pm and pm.get("name") == "#c8a752")
    check("the switched-off design's colours never show", pm and "#010203" not in pm.values())

    print("4. A client with no store of their own reads the main store's card")
    st, pn = colors(NONE)
    check(f"same as Liberté ({pn})", pn == pc)

    print("5. FidClic blue + yellow, no Pass Designer")
    st, pf = colors(FC)
    check(f"background blue #1450b8 ({pf})", pf and pf.get("background") == "#1450b8")
    check("footer blue #1450b8", pf and pf.get("footer") == "#1450b8")
    check("name yellow #f8b008", pf and pf.get("name") == "#f8b008")

    print("6. Hostile values never come out raw")
    st, pg = colors(GS)
    check(f"200 ({st}, {pg})", st == 200 and isinstance(pg, dict))
    vals = [v for k, v in (pg or {}).items() if k != "poster"]
    check("every colour is #rrggbb or null", all(v is None or HEX.match(v) for v in vals))
    check("no script / url / expression anywhere", not any(re.search(r"script|url|expression|[<>;{}()]", str(v)) for v in vals))
    check("rgb(999,0,0) is clamped to a real colour, '#12' refused",
          pg and pg.get("foreground") in ("#ff0000", None) and pg.get("label") is None)
    check("a storeCard design: not a poster", pg and pg.get("poster") is False)

    print("7. Who may read it: the card's own rule")
    check("no key → 403", colors(PAL, headers={})[0] == 403)
    check("Liberté's key on Palissy's card → 403", colors(PAL, headers={"X-Card-Key": CO.key_for(LIB)})[0] == 403)
    check("another business's owner → 403", colors(PAL, headers=login("business_owner", "t2"))[0] == 403)
    st, po = colors(PAL, headers={**login("business_owner", "t1"), "X-FidClic-Store": "main"})
    check(f"the owner with the menu on Liberté still sees Palissy's own colours ({po})", st == 200 and po == pp)

    print("8. hex_color, unit")
    from features.card_page import hex_color as H
    for raw, want in [("rgb(0,0,0)", "#000000"), ("RGB( 20 , 80 , 184 )", "#1450b8"), ("rgba(1,2,3,0.5)", "#010203"),
                      ("#ABC", "#aabbcc"), ("abcdef", "#abcdef"), (" #1450B8 ", "#1450b8"), ("rgb(-5, 300, 7)", "#00ff07"),
                      ("", None), (None, None), (12, None), ("#12", None), ("#1234567", None), ("blue", None),
                      ("rgb(1,2)", None), ("#fff;}", None), ("rgb(1,2,3);x", None), ("#" + "a" * 60, None)]:
        check(f"hex_color({raw!r}) → {want}", H(raw) == want)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
