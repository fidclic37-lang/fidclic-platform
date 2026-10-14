"""
A product's price is never « nothing » (QA F31, 2026-10-11): the owner erased
the price of an 11,11 € product by mistake, saved, and it became free without
a word. No price is now refused; a 0 sent on purpose is still a free product.

Run: cd api && /usr/local/bin/python3 tests/test_price_required.py
"""
import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    import server                      # noqa: F401 — boots the app + db
    from fastapi import HTTPException
    from features import catalogue_page as K

    db = server.db
    K.init(db)
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

    db.tenants.insert_one({"id": "t1", "name": "Le Corner Café", "slug": "corner"})
    prices = lambda: {p["name"]: p["price"] for p in K.page(token_data=TD())["products"]}

    print("\nAdding a product")
    msg = refused(lambda: K.create_product(K.ProductIn(name="Menu midi"), token_data=TD()))
    check(f"without a price: refused ({msg})", msg and "Prix obligatoire" in msg)
    check("…and nothing added", "Menu midi" not in prices())
    pid = K.create_product(K.ProductIn(name="Menu midi", price=11.11), token_data=TD())["id"]
    free = K.create_product(K.ProductIn(name="Verre d'eau", price=0), token_data=TD())["id"]
    check("a price: added", prices().get("Menu midi") == 11.11)
    check("0 typed on purpose: a free product", prices().get("Verre d'eau") == 0)

    print("\nEditing it")
    msg = refused(lambda: K.update_product(pid, K.ProductIn(name="Menu midi", price=None), token_data=TD()))
    check(f"the price erased: refused ({msg})", msg and "Prix obligatoire" in msg)
    check("…and the product keeps 11,11 €", prices().get("Menu midi") == 11.11)
    K.update_product(pid, K.ProductIn(name="Menu midi", price=12.5), token_data=TD())
    check("a new price: saved", prices().get("Menu midi") == 12.5)
    check("a negative price: still refused",
          refused(lambda: K.update_product(pid, K.ProductIn(name="Menu midi", price=-1), token_data=TD())) == "Prix invalide.")

    print("\nImporting a menu read from a photo")
    msg = refused(lambda: K.import_products(K.ImportIn(items=[K.ProductIn(name="Thé vert", price=3),
                                                              K.ProductIn(name="Tarte du jour")]), token_data=TD()))
    check(f"a line without a price: refused ({msg})", msg and "Prix obligatoire" in msg)
    check("…and nothing of that import added", "Thé vert" not in prices() and "Tarte du jour" not in prices())
    out = K.import_products(K.ImportIn(items=[K.ProductIn(name="Thé vert", price=3),
                                              K.ProductIn(name="Tarte du jour", price=0)]), token_data=TD())
    check("every line priced: imported", out["added"] == 2 and prices().get("Tarte du jour") == 0)

    print("\nThrough the API (what the page sends)")
    import asyncio
    import auth
    import httpx

    db.users.insert_one({"email": "owner@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token({"sub": "owner@x.fr", "role": "business_owner", "tenant_id": "t1"})}

    async def call(method, url, **kw):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
            return await ac.request(method, url, headers=H, **kw)
    r = asyncio.get_event_loop().run_until_complete(call("POST", "/api/owner/catalogue/products", json={"name": "Café", "price": None}))
    check(f"price null: 400 in French, not a 422 ({r.status_code}, {r.json().get('detail')})",
          r.status_code == 400 and "Prix obligatoire" in r.json()["detail"])
    r = asyncio.get_event_loop().run_until_complete(call("POST", "/api/owner/catalogue/products", json={"name": "Café"}))
    check(f"no price at all: the same ({r.status_code})", r.status_code == 400)

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
