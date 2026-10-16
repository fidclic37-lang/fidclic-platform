"""
« Image de la page d'inscription » (user, 2026-10-12): the picture at the top
of the signup page, chosen by each establishment in Paramètres › Lien
d'inscription & QR; without one, the card's logo (as before).

Run: cd api && /usr/local/bin/python3 tests/test_signup_image.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-signup-image")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0
IMG_A = "data:image/png;base64,QUFBQQ=="
IMG_B = "data:image/jpeg;base64,QkJCQg=="
LOGO = "data:image/png;base64,TE9HTw=="
LOGO_PAL = "data:image/png;base64,UEFM"
SRC = "data:image/png;base64,U1JD"      # the picture before framing


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

    db = server.db

    def http(method, url, headers=None, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as ac:
                return await ac.request(method, url, headers=headers if headers is not None else {}, **kw)
        return asyncio.get_event_loop().run_until_complete(run())

    db.tenants.insert_many([
        {"id": "t1", "slug": "royal-trim", "name": "ROYAL TRIM", "plan": "vip", "subscription_status": "active", "is_active": True,
         "branches": [{"id": "main", "name": "ROYAL TRIM", "is_main": True, "slug": "principal"},
                      {"id": "pal", "name": "ROYAL TRIM PALISSY", "slug": "palissy"},
                      {"id": "mon", "name": "ROYAL TRIM PL-MONSTER", "slug": "pl-monster"}]},
        {"id": "t2", "slug": "solo", "name": "Solo Café", "plan": "vip", "subscription_status": "active", "is_active": True},
    ])
    db.card_templates.insert_many([{"tenant_id": "t1", "logo_url": LOGO}, {"tenant_id": "t2", "logo_url": LOGO}])
    db["card_templates"]._real.insert_one({"tenant_id": "t1", "store_id": "pal", "logo_url": LOGO_PAL})
    for e, role, t in (("o@x.fr", "business_owner", "t1"), ("m@x.fr", "manager", "t1"), ("r@x.fr", "business_owner", "t2")):
        db.users.insert_one({"email": e, "role": role, "tenant_id": t, "active": True,
                             **({"branch_ids": ["pal"]} if role == "manager" else {})})
    tok = lambda e, r, t="t1": "Bearer " + auth.create_access_token({"sub": e, "role": r, "tenant_id": t})  # noqa: E731
    OWNER, MANAGER, SOLO = tok("o@x.fr", "business_owner"), tok("m@x.fr", "manager"), tok("r@x.fr", "business_owner", "t2")

    def as_(store, who=OWNER):
        return {"Authorization": who, **({"X-FidClic-Store": store} if store else {})}

    def page(store=None, slug="royal-trim"):
        return http("GET", f"/api/join/{slug}/page", params={"store": store} if store else {}).json()

    print("1. Without an image of its own: the card's logo (as before)")
    check("PALISSY's link: PALISSY's card logo", page("palissy")["logo_url"] == LOGO_PAL)
    check("PL-MONSTER's link: the account's card logo", page("pl-monster")["logo_url"] == LOGO)
    v = http("GET", "/api/owner/join-link", headers=as_("pal")).json()["shop"]
    check("the settings page says: no image yet, the card's logo is used",
          v["signup_image"] == "" and v["card_logo_url"] == LOGO_PAL and v["logo_url"] == LOGO_PAL)

    print("\n2. PALISSY chooses its own")
    r = http("PUT", "/api/owner/join-link/image", headers=as_("pal"), json={"image": IMG_A})
    check(f"saved ({r.status_code})", r.status_code == 200 and r.json()["shop"]["signup_image"] == IMG_A)
    check("PALISSY's signup page shows it", page("palissy")["logo_url"] == IMG_A)
    check("PL-MONSTER's and the main store's do not", page("pl-monster")["logo_url"] == LOGO
          and page("principal")["logo_url"] == LOGO)
    check("PALISSY's card logo is untouched", db["card_templates"]._real.find_one({"store_id": "pal"})["logo_url"] == LOGO_PAL)
    r = http("PUT", "/api/owner/join-link/image", headers=as_("main"), json={"image": IMG_B})
    check("the main store chooses another", r.status_code == 200 and page("principal")["logo_url"] == IMG_B)
    check("…the account's own link shows the main store's", page()["logo_url"] == IMG_B)
    check("…PALISSY keeps its own", page("palissy")["logo_url"] == IMG_A)
    r = http("PUT", "/api/owner/join-link/image", headers=as_("pal"), json={"image": ""})
    check("« Revenir au logo de la carte »", r.status_code == 200 and page("palissy")["logo_url"] == LOGO_PAL)

    print("\n3. « Ajuster » reopens the whole picture, not the crop")
    # What is shown is a crop; a crop cannot be zoomed back out from itself, so
    # the picture as it came is kept beside it (user, 2026-10-16).
    r = http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
             json={"image": IMG_A, "source": SRC, "frame": {"zoom": 1.4, "x": -12, "y": -30}})
    v = r.json()["shop"]
    check(f"saved with its picture before framing ({r.status_code})",
          r.status_code == 200 and v["signup_image"] == IMG_A and v["signup_image_src"] == SRC)
    check("…and where it was framed", v["signup_image_frame"] == {"zoom": 1.4, "x": -12, "y": -30})
    check("the signup page still shows the crop, not the whole picture",
          page("palissy")["logo_url"] == IMG_A)
    # Reframing sends no picture again: the server already has it.
    r = http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
             json={"image": IMG_B, "frame": {"zoom": 1, "x": 0, "y": 0}})
    v = r.json()["shop"]
    check("reframing keeps the picture and moves the frame",
          v["signup_image"] == IMG_B and v["signup_image_src"] == SRC
          and v["signup_image_frame"] == {"zoom": 1, "x": 0, "y": 0})
    check("another store has none of it", http("GET", "/api/owner/join-link",
                                               headers=as_("main")).json()["shop"]["signup_image_src"] == "")
    http("PUT", "/api/owner/join-link/image", headers=as_("pal"), json={"image": ""})
    check("« Revenir au logo de la carte » takes the picture with it",
          http("GET", "/api/owner/join-link", headers=as_("pal")).json()["shop"]["signup_image_src"] == "")

    print("\n4. Refused")
    check("not an image", http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
                               json={"image": "javascript:alert(1)"}).status_code == 400)
    check("over 2 Mo", http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
                            json={"image": "data:image/png;base64," + "A" * 2_900_000}).status_code == 400)
    check("a picture before framing over 2 Mo",
          http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
               json={"image": IMG_A, "source": "data:image/png;base64," + "A" * 2_900_000}).status_code == 400)
    check("a picture before framing that is not an image",
          http("PUT", "/api/owner/join-link/image", headers=as_("pal"),
               json={"image": IMG_A, "source": "javascript:alert(1)"}).status_code == 400)
    check("no establishment chosen (several stores)",
          http("PUT", "/api/owner/join-link/image", headers=as_(None), json={"image": IMG_A}).status_code == 400)
    check("a manager cannot", http("PUT", "/api/owner/join-link/image", headers=as_("pal", MANAGER),
                                   json={"image": IMG_A}).status_code == 403)
    check("another account's store id is ignored (one-shop account: its own)",
          http("PUT", "/api/owner/join-link/image", headers=as_("pal", SOLO), json={"image": IMG_A}).status_code == 200
          and page(slug="solo")["logo_url"] == IMG_A and page("palissy")["logo_url"] == LOGO_PAL)

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
