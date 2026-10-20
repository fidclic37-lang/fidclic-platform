"""
Le logo et le nom dans l'en-tête Apple (user, 2026-10-20).

En regardant la carte d'un autre commerce, dont le logo remplit tout le haut :
  1. sans nom écrit à côté, NOTRE logo était bridé à 100 pt de large alors
     qu'Apple en donne 160 — un tiers de moins que permis ;
  2. « text ka size kam krta hun toh logo ka size nhi badhta » : réduire le
     nom laissait un trou au lieu d'agrandir le logo ;
  3. huit lignes de 400 caractères au dos ne suffisent pas pour des
     conditions d'utilisation.

Run: cd api && /usr/local/bin/python3 tests/test_logo_name_size.py
"""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mongomock
import pymongo

pymongo.MongoClient = mongomock.MongoClient
os.environ.setdefault("JWT_SECRET", "test-secret-logo-name")
os.environ.setdefault("DISABLE_SEED", "1")
passed = failed = 0


def check(label, cond):
    global passed, failed
    cond = bool(cond)
    passed += cond
    failed += (not cond)
    print(("  ✓ " if cond else "  ✗ ") + label)


def main():
    import server                                   # noqa: F401 — wires the modules
    import features.wallet_passes as WP
    from features import loyalty_card as LC
    from PIL import Image

    def png(w, h, colour=(200, 60, 40, 255)):
        b = io.BytesIO()
        Image.new("RGBA", (w, h), colour).save(b, "PNG")
        return b.getvalue()

    def size(data):
        return Image.open(io.BytesIO(data)).size

    WIDE = png(1200, 300)        # a wordmark: four times wider than tall
    SQUARE = png(600, 600)

    print("\n1. Sans nom : le logo a toute la place qu'Apple donne")
    out = WP._png_variants(WIDE, WP.LOGO_BOX, tight=True)
    w1, h1 = size(out["@2x"])
    check(f"la boîte est bien celle d'Apple, 160 × 50 ({WP.LOGO_BOX})", WP.LOGO_BOX == (160, 50))
    check(f"un wordmark fait 320 px de large en @2x, pas 200 ({w1}×{h1})", w1 == 320)
    before = WP._png_variants(WIDE, (100, 50), tight=True)
    check(f"c'est bien plus qu'avant ({size(before['@2x'])[0]} px)", w1 > size(before["@2x"])[0])
    sq = size(WP._png_variants(SQUARE, WP.LOGO_BOX, tight=True)["@2x"])
    check(f"un logo carré ne change pas : la hauteur le borne ({sq})", sq == (100, 100))
    check("iOS 27 garde sa boîte mesurée sur un vrai iPhone", WP.POSTER_LOGO_BOX == (126, 30))

    print("\n2. Le nom plus petit → le logo prend la place")
    # Un logo LARGE : c'est lui qui peut grandir. Un logo carré touche déjà les
    # 50 pt de haut de l'en-tête Apple — rien ne peut l'agrandir, et le test le
    # dit plus bas pour que personne ne cherche un réglage qui n'existe pas.
    def built(name_pct, logo=WIDE):
        return WP.name_logo(logo, "MAISON DUPONT", (255, 255, 255), box=(160, 50),
                            name_pct=name_pct)["@2x"]

    full = Image.open(io.BytesIO(built(100))).convert("RGBA")
    half = Image.open(io.BytesIO(built(50))).convert("RGBA")

    def logo_width(im):
        """The logo is the opaque block on the left; the name is drawn in white
        further right. Measure the first run of fully-coloured pixels."""
        px = im.load()
        y = im.height // 2
        w = 0
        while w < im.width and px[w, y][3] > 0 and px[w, y][:3] != (255, 255, 255):
            w += 1
        return w

    lw_full, lw_half = logo_width(full), logo_width(half)
    check(f"à 100 % le logo garde sa place habituelle ({lw_full} px)", lw_full > 0)
    check(f"à 50 % le nom est écrit plus petit et le logo grandit "
          f"({lw_full} → {lw_half} px)", lw_half > lw_full)
    check("…sans dépasser la hauteur de la boîte", half.height == 100)
    tiny = Image.open(io.BytesIO(built(10))).convert("RGBA")
    check(f"à 10 % il grandit encore ({logo_width(tiny)} px)", logo_width(tiny) >= lw_half)
    check("sans logo, « Taille du nom » écrit simplement plus petit",
          WP.name_logo(None, "MAISON DUPONT", (255, 255, 255), box=(160, 50), name_pct=40)["@2x"]
          != WP.name_logo(None, "MAISON DUPONT", (255, 255, 255), box=(160, 50), name_pct=100)["@2x"])
    check("« Taille du logo » à 0 reste le nom seul",
          logo_width(Image.open(io.BytesIO(WP.name_logo(WIDE, "MAISON DUPONT", (255, 255, 255),
                                                        box=(160, 50), logo_pct=0)["@2x"])).convert("RGBA")) == 0)
    # Un logo carré est déjà au maximum : l'en-tête fait 50 pt de haut.
    sq_full = Image.open(io.BytesIO(built(100, SQUARE))).convert("RGBA")
    sq_half = Image.open(io.BytesIO(built(40, SQUARE))).convert("RGBA")
    check(f"un logo carré touche déjà la hauteur : rien à gagner "
          f"({logo_width(sq_full)} → {logo_width(sq_half)} px, hauteur {sq_full.height})",
          logo_width(sq_full) == logo_width(sq_half) == sq_full.height)
    check("une valeur absurde vaut 100 %, pas une erreur",
          WP._logo_pct("n'importe quoi") == 100 and WP._logo_pct(-5) == 0 and WP._logo_pct(900) == 100)
    check("chaque taille a sa propre image en cache",
          built(100) != built(50))

    print("\n3. Le dos de la carte")
    check(f"vingt lignes, pas huit ({LC.BACK_FIELDS_MAX})", LC.BACK_FIELDS_MAX == 20)
    import auth
    import asyncio
    import httpx
    db = server.db
    db.tenants.insert_one({"id": "t1", "slug": "shop", "name": "Le Shop", "plan": "vip",
                           "subscription_status": "active", "is_active": True})
    db.users.insert_one({"email": "o@shop.fr", "role": "business_owner", "tenant_id": "t1", "active": True})
    H = {"Authorization": "Bearer " + auth.create_access_token(
        {"sub": "o@shop.fr", "role": "business_owner", "tenant_id": "t1"})}

    def http(method, url, **kw):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),
                                         base_url="http://test") as ac:
                return await ac.request(method, url, headers=H, **kw)
        return asyncio.new_event_loop().run_until_complete(run())

    rows = [{"label": f"Ligne {i}", "value": f"Valeur {i}"} for i in range(25)]
    rows[0] = {"label": "Conditions d'utilisation", "value": "x" * 3000}
    r = http("PUT", "/api/owner/card/settings", json={"back_fields": rows})
    kept = (db.card_templates.find_one({"tenant_id": "t1"}) or {}).get("back_fields") or []
    check(f"vingt lignes gardées sur vingt-cinq envoyées ({len(kept)}, {r.status_code})",
          r.status_code == 200 and len(kept) == 20)
    check(f"une ligne porte de vraies conditions, 2 000 caractères ({len(kept[0]['value'])})",
          len(kept[0]["value"]) == 2000)
    check("et le libellé a de la place aussi (60)", len(kept[0]["label"]) == len("Conditions d'utilisation"))

    print(f"\n{passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
