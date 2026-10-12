"""
One card per establishment (user, 2026-10-12, multi-store « ROYAL TRIM /
PALISSY / PL-MONSTER »: « ek k card mein change kr rha toh teeno k mein ho rha »):
  • the card page shows and saves the card of the establishment chosen in the menu;
  • its customers carry it — pass, Google, the web card, the scan's rules —
    wherever they are scanned; the other establishments keep theirs;
  • the existing stores keep the design they had (« undo mat kro »);
  • a store created from now starts blank, its card OFF: no signup, no client
    moved there, until its owner saves its card;
  • a save refreshes only that establishment's cards.

Run: cd api && /usr/local/bin/python3 tests/test_store_cards.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-store-cards")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server
    import auth
    import httpx
    import features.wallet_passes as WP
    from features import store_cards as SC

    db = server.db
    pushed = []
    WP.notify_passes = lambda serials, *a, **k: pushed.append(sorted(s for s in serials if s)) or {"sent": 0}
    WP.notify_customer = lambda *a, **k: {}
    from features import plan_limits as PL
    _feat = PL.tenant_features
    PL.tenant_features = lambda tid: {**_feat(tid), "establishments": 10}

    def card_of(barcode):
        """The card every surface reads (web card, pass, Google)."""
        c = db.customers.find_one({"barcode_id": barcode}, {"_id": 0})
        return server._serialize_card_payload(c) if c else {}

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active",
         "is_active": True,
         "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True},
                      {"id": "pal", "name": "ROYAL TRIM PALISSY"},
                      {"id": "mon", "name": "ROYAL TRIM PL-MONSTER"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_many([
        {"tenant_id": "t1", "card_name": "Carte Royal", "surface_color": "#111111", "brand_color": "#B85C38",
         "reward_threshold_stamps": 10, "visits_per_stamp": 1, "reward_description": "Coupe offerte",
         "welcome_text": "Bienvenue chez Royal"},
        {"tenant_id": "t2", "card_name": "Carte Solo", "reward_threshold_stamps": 8, "reward_description": "Café offert"},
    ])
    BC = {"c_pal": "FT-PAL00001", "c_mon": "FT-MON00001", "c_main": "FT-MAIN0001"}
    for cid, br in (("c_pal", "pal"), ("c_mon", "mon"), ("c_main", "main")):
        db.customers.insert_one({"id": cid, "tenant_id": "t1", "name": f"Client {cid}", "barcode_id": BC[cid],
                                 "branch_id": br, "visits": 0, "points": 0, "deleted_at": None})
    db.customers.insert_one({"id": "s1", "tenant_id": "t2", "name": "Solo client", "barcode_id": "FT-SOLO0001",
                             "visits": 0, "points": 0, "deleted_at": None})
    for e, role, t in (("o@x.fr", "business_owner", "t1"), ("r@x.fr", "business_owner", "t2")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t, "active": True})
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, SOLO = tok("o@x.fr", "business_owner"), tok("r@x.fr", "business_owner", "t2")

    def as_(store, who=None):
        h = {"Authorization": who or OWNER}
        if store:
            h["X-FidClic-Store"] = store
        return h

    def card_name(store, who=None):
        r = http("GET", "/api/owner/card/settings", headers=as_(store, who))
        return r.status_code, (r.json().get("design") or {}).get("card_name"), r.json()

    def raw(store):
        return db["card_templates"]._real.find_one({"tenant_id": "t1", "store_id": store}, {"_id": 0}) or {}

    print("1. The existing stores keep the card they had")
    for s in ("main", "pal", "mon"):
        code, name, _ = card_name(s)
        check(f"{s}: « Carte Royal » ({code})", code == 200 and name == "Carte Royal")
    check("no establishment has its own card yet", db["card_templates"]._real.count_documents({"store_id": {"$ne": None}}) == 0)

    print("\n2. PALISSY changes its card: only PALISSY's")
    pushed.clear()
    r = http("PUT", "/api/owner/card/settings", headers=as_("pal"),
             json={"card_name": "Carte Palissy", "reward_threshold_stamps": 5, "reward_description": "Barbe offerte"})
    check(f"saved ({r.status_code})", r.status_code == 200)
    check("PALISSY now has its own card", raw("pal").get("card_name") == "Carte Palissy")
    check("…copied from the one it had (its colours, its welcome text kept)",
          raw("pal").get("surface_color") == "#111111" and raw("pal").get("welcome_text") == "Bienvenue chez Royal")
    check("the account's card is untouched", raw(None).get("card_name") == "Carte Royal"
          and raw(None).get("reward_threshold_stamps") == 10)
    check("PALISSY reads its card", card_name("pal")[1] == "Carte Palissy")
    check("PL-MONSTER still reads its own (unchanged)", card_name("mon")[1] == "Carte Royal")
    check("the main store too", card_name("main")[1] == "Carte Royal")
    check(f"only PALISSY's members' cards are refreshed ({pushed})", pushed and all(p == [BC["c_pal"]] for p in pushed))

    pushed.clear()
    r = http("PUT", "/api/owner/card/settings", headers=as_("mon"), json={"card_name": "Carte Monster"})
    check("PL-MONSTER changes its own", r.status_code == 200 and card_name("mon")[1] == "Carte Monster")
    check("…PALISSY keeps its change", card_name("pal")[1] == "Carte Palissy")
    check("…refresh: PL-MONSTER's members only", pushed and all(p == [BC["c_mon"]] for p in pushed))
    pushed.clear()
    http("POST", "/api/owner/wallet/notify", headers=as_("pal"))
    check("« Actualiser les cartes » in PALISSY: PALISSY's cards only", pushed == [[BC["c_pal"]]])

    print("\n3. A customer carries their home store's card, wherever they are")
    pal_card = card_of(BC["c_pal"])
    mon_card = card_of(BC["c_mon"])
    main_card = card_of(BC["c_main"])
    nm = lambda p: (p.get("card") or {}).get("card_name")  # noqa: E731
    check(f"PALISSY's client: « Carte Palissy » ({nm(pal_card)})", nm(pal_card) == "Carte Palissy")
    check(f"PL-MONSTER's client: « Carte Monster » ({nm(mon_card)})", nm(mon_card) == "Carte Monster")
    check(f"the main store's client: the account's card ({nm(main_card)})", nm(main_card) == "Carte Royal")
    with SC.store(None, "mon"):                       # the menu's store of an owner's browser
        pal_card2 = card_of(BC["c_pal"])
    check("…even opened in a browser where PL-MONSTER is chosen", nm(pal_card2) == "Carte Palissy")
    sample = {"id": "preview-sample", "tenant_id": "t1", "barcode_id": "FT-EXEMPLE1", "name": "Marie", "visits": 3}
    with SC.store(None, "pal"):                       # the owner's preview, PALISSY chosen in the menu
        prev = server._serialize_card_payload(sample)
    check(f"the owner's preview (a sample client) shows the menu's store card ({nm(prev)})",
          nm(prev) == "Carte Palissy" and prev.get("store_id") == "pal")
    r = http("POST", "/api/owner/wallet/google-preview", headers=as_("pal"), json={"card": {}, "visits": 3})
    check(f"…the Google preview too ({r.status_code})", r.status_code == 200 and "Carte Palissy" in str(r.json())
          or "Barbe offerte" in str(r.json()))
    cust = db.customers.find_one({"id": "c_pal"}, {"_id": 0})
    payload = server._serialize_card_payload(cust)
    check("the pass payload says whose card it is", payload.get("store_id") == "pal")
    pj = WP.build_pass_json(payload)
    check("Apple pass: built from PALISSY's card", "Carte Palissy" in str(pj) or pj.get("description") == "Carte Palissy"
          or "Barbe offerte" in str(pj))
    WP._gw_issuer = lambda: "333"
    with SC.store("t1", "pal"):
        cls_pal = WP._gw_ids("t1", BC["c_pal"])[0]
    with SC.store("t1", "main"):
        cls_main = WP._gw_ids("t1", BC["c_main"])[0]
    check(f"Google: PALISSY's own class ({cls_pal})", cls_pal == "333.fidclic_t1_pal")
    check(f"…a store still on the account's card keeps the account's class ({cls_main})", cls_main == "333.fidclic_t1")
    with SC.store("t1", "pal"):
        url = WP._gw_image_url("t1", "logo", {"logo_url": "x"})
    check("…its images are PALISSY's", url.endswith("&store=pal"))

    print("\n4. The scan follows the client's home store")
    r = http("POST", "/api/owner/scan", headers=as_("mon"), json={"barcode_id": BC["c_pal"], "branch_id": "mon"})
    check(f"PALISSY's client scanned at PL-MONSTER: PALISSY's 5 stamps ({r.status_code} {r.json().get('reward_threshold')})",
          r.status_code == 200 and r.json().get("reward_threshold") == 5)
    r = http("POST", "/api/owner/scan", headers=as_("pal"), json={"barcode_id": BC["c_main"], "branch_id": "pal"})
    check(f"the main store's client scanned at PALISSY: the account's 10 ({r.json().get('reward_threshold')})",
          r.status_code == 200 and r.json().get("reward_threshold") == 10)
    check("the visit counts where it is scanned", r.json().get("visit_branch_id") == "pal")

    print("\n5. A store created from now: blank, card off")
    r = http("POST", "/api/owner/etablissement/stores", headers=as_("main"), json={"name": "ROYAL TRIM LIBERTE", "city": "Tours"})
    check(f"created ({r.status_code})", r.status_code == 200)
    new = next((b for b in db.tenants.find_one({"id": "t1"})["branches"] if b.get("name") == "ROYAL TRIM LIBERTE"), {})
    nid = new.get("id")
    check("its card is OFF", new.get("card_off") is True)
    code, name, body = card_name(nid)
    check(f"its card page starts blank — nothing of the others ({name})",
          code == 200 and name not in ("Carte Royal", "Carte Palissy", "Carte Monster")
          and (body.get("design") or {}).get("surface_color") not in ("#111111",))
    pub = http("GET", "/api/join/royal-trim/page").json()
    st = next((x for x in pub["stores"] if x["id"] == nid), {})
    check("the signup page lists it as not open yet", st.get("card_off") is True and pub.get("card_off_message"))
    j = http("POST", "/api/join/royal-trim", json={"name": "Léa", "phone": "0612121212", "postal_code": "37000",
                                                    "birthday": "02/03/1995", "consent": True, "store": st.get("slug")})
    check(f"no signup through its link ({j.status_code})", j.status_code == 400
          and (j.json().get("detail") or {}).get("code") == "store_card_off")
    r = http("PUT", "/api/owner/customers/c_pal/home-store", headers=as_("pal"), json={"branch_id": nid})
    check(f"no client moved there ({r.status_code})", r.status_code == 400)
    check("other stores' signups still work",
          http("POST", "/api/join/royal-trim", json={"name": "Marc", "phone": "0613131313", "postal_code": "37000",
                                                     "birthday": "02/03/1995", "consent": True, "store": "mon"}).status_code == 200)

    r = http("PUT", "/api/owner/card/settings", headers=as_(nid), json={"card_name": "Carte Liberté", "reward_threshold_stamps": 6})
    check(f"its owner designs it ({r.status_code})", r.status_code == 200 and card_name(nid)[1] == "Carte Liberté")
    check("…from blank: nothing copied from the account's card", not raw(nid).get("welcome_text")
          and raw(nid).get("surface_color") != "#111111")
    check("…and its card is ON", not next(b for b in db.tenants.find_one({"id": "t1"})["branches"] if b["id"] == nid).get("card_off"))
    j = http("POST", "/api/join/royal-trim", json={"name": "Léa", "phone": "0612121212", "postal_code": "37000",
                                                    "birthday": "02/03/1995", "consent": True, "store": st.get("slug")})
    check(f"signups open ({j.status_code})", j.status_code == 200)
    lea = db.customers.find_one({"barcode_id": j.json().get("barcode_id")}, {"_id": 0}) or {}
    check("Léa carries LIBERTÉ's card", lea.get("branch_id") == nid
          and nm(card_of(lea.get("barcode_id"))) == "Carte Liberté")
    check("the others are untouched", card_name("pal")[1] == "Carte Palissy" and card_name("main")[1] == "Carte Royal")

    print("\n6. Nothing leaks between accounts, a one-shop account is as before")
    code, name, _ = card_name("pal", SOLO)
    check(f"another account sending PALISSY's id reads its own card ({name})", name == "Carte Solo")
    r = http("PUT", "/api/owner/card/settings", headers=as_("pal", SOLO), json={"card_name": "Solo 2"})
    check("…and writes its own", r.status_code == 200 and card_name(None, SOLO)[1] == "Solo 2"
          and db["card_templates"]._real.count_documents({"tenant_id": "t2", "store_id": {"$ne": None}}) == 0)
    check("…PALISSY's card unchanged", card_name("pal")[1] == "Carte Palissy")
    check("a one-shop account: one card, as before",
          db["card_templates"]._real.count_documents({"tenant_id": "t2"}) == 1
          and nm(card_of("FT-SOLO0001")) == "Solo 2")
    check("account-wide lists read one card per account (no store copies)",
          sorted(x["tenant_id"] for x in db.card_templates.find({}, {"tenant_id": 1})) == ["t1", "t2"])

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
