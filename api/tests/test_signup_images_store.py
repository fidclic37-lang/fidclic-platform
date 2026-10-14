"""
Signup-page images out of the account document (user, 2026-10-12: « why does
the platform take so much time to load now »). Kept inside the tenant
(tenant.signup_image, branches[].signup_image), each 2 Mo image rode along on
every read of the account — the menu's store check reads its branches on each
card read — and a three-store account's pages took seconds. They now live in
`signup_images`; images already stored inline move there at start.

Run: cd api && /usr/local/bin/python3 tests/test_signup_images_store.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-signup-images-store")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
BIG = "data:image/jpeg;base64," + "A" * 1_500_000          # a 1.5 Mo image
SMALL = "data:image/png;base64,QUFBQQ=="


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
    from features import join_link as JL
    from services import media as M
    import base64 as _b64

    def same(v, data_url):
        """The picture is the one sent (kept inline, or as a link to `media`)."""
        if v == data_url:
            return True
        return M.is_ref(v) and M.resolve(v) == _b64.b64decode(data_url.split(",", 1)[1])

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    # an account saved before the move: images inside the tenant document
    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True, "slug": "principal", "signup_image": BIG},
                      {"id": "pal", "name": "ROYAL TRIM PALISSY", "slug": "palissy", "signup_image": BIG},
                      {"id": "mon", "name": "ROYAL TRIM PL-MONSTER", "slug": "pl-monster"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True,
         "signup_image": SMALL, "signup_image_at": "x"},
    ])
    db.users.insert_one({"email": "o@x.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    OWNER = "Bearer " + auth.create_access_token({"sub": "o@x.fr", "role": "business_owner", "tenant_id": "t1"})

    print("\nImages stored inside an account move out")
    moved = JL.move_inline_images()
    check(f"three images moved ({moved})", moved == 3)
    t1 = db.tenants.find_one({"id": "t1"}, {"_id": 0})
    t2 = db.tenants.find_one({"id": "t2"}, {"_id": 0})
    check("no image left in the stores", not any("signup_image" in b for b in t1["branches"]))
    check("no image left on a one-shop account", "signup_image" not in t2 and "signup_image_at" not in t2)
    check("the stores keep everything else", [b["name"] for b in t1["branches"]] == ["ROYAL TRIM", "ROYAL TRIM PALISSY", "ROYAL TRIM PL-MONSTER"]
          and t1["branches"][1]["slug"] == "palissy")
    size = len(json.dumps(t1, default=str))
    check(f"the account document is light again ({size} bytes)", size < 5000)
    check("each image kept, as a link to `media` (big) or inline (tiny)",
          M.is_ref(JL.image_of("t1", "main")) and same(JL.image_of("t1", "main"), BIG) and same(JL.image_of("t1", "pal"), BIG)
          and JL.image_of("t2", None) == SMALL and JL.image_of("t1", "mon") == "")
    check("moving twice moves nothing", JL.move_inline_images() == 0)

    print("\nThe signup page still shows each establishment's own")
    p = http("GET", "/api/join/royal-trim/page?store=palissy").json()
    check("PALISSY's link: its image", same(p.get("signup_image"), BIG))
    p = http("GET", "/api/join/royal-trim/page").json()
    check("the account's link: the main store's", same(p.get("signup_image"), BIG))
    p = http("GET", "/api/join/royal-trim/page?store=pl-monster").json()
    check("a store without one: none (the card's logo shows)", p.get("signup_image") == "")
    check("a one-shop account: its own", http("GET", "/api/join/solo/page").json().get("signup_image") == SMALL)

    print("\nA new image goes to signup_images, never into the account")
    r = http("PUT", "/api/owner/join-link/image", headers={"Authorization": OWNER, "X-FidClic-Store": "mon"},
             json={"image": SMALL})
    check(f"saved for PL-MONSTER ({r.status_code})", r.status_code == 200 and JL.image_of("t1", "mon") == SMALL)
    t1 = db.tenants.find_one({"id": "t1"}, {"_id": 0})
    check("the account document stays light", not any("signup_image" in b for b in t1["branches"]) and "signup_image" not in t1)
    r = http("PUT", "/api/owner/join-link/image", headers={"Authorization": OWNER, "X-FidClic-Store": "mon"},
             json={"image": ""})
    check("removed: back to the card's logo", r.status_code == 200 and JL.image_of("t1", "mon") == ""
          and db.signup_images.count_documents({"tenant_id": "t1", "store_id": "mon"}) == 0)
    r = http("PUT", "/api/owner/join-link/image", headers={"Authorization": OWNER, "X-FidClic-Store": "nope"},
             json={"image": SMALL})
    check(f"a store that is not this account's is refused ({r.status_code})", r.status_code == 400)

    print("\nThe menu's store check reads a light account")
    from features import store_cards as SC
    b = SC._branch("t1", "pal")
    check("the store found, without any image", b and b["id"] == "pal" and "signup_image" not in b)


if __name__ == "__main__":
    main()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
