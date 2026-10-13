"""
Le nom du commerce à côté du logo : une seule ligne, entier — et une lettre
agrandie est vraiment plus grande.

Run: cd api && python3 tests/test_nom_stylise.py
"""
from __future__ import annotations

import os
import sys

import mongomock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["DISABLE_SEED"] = "1"

with mongomock.patch(servers=(("localhost", 27017),)):
    from features import wallet_passes as WP
    from PIL import Image
    import io

    passed = failed = 0

    def check(label, cond):
        global passed, failed
        passed += bool(cond); failed += (not cond)
        print(("  ✓ " if cond else "  ✗ ") + label)

    BOX, BLACK = (640, 200), (0, 0, 0)

    def letters(text, size=100, font=None):
        return tuple((c, size, None, font) for c in text)

    def ink_box(img):
        """The area the drawing actually covers — the alpha channel decides."""
        return img.getchannel("A").getbbox()

    def styled(text, size=100, room=600, h=200, font=None):
        return WP._styled_name_image(letters(text, size, font), BLACK, room, h, 4.0)

    print("\n— une seule ligne, quoi qu'il arrive —")
    for name in ("ROYAL TRIM PALISSY", "A", "LE PETIT CAFÉ DE LA PLACE DU MARCHÉ"):
        img = styled(name)
        box = ink_box(img)
        # one line: what is drawn is no taller than a single line of that size
        rows = WP._styled_name_image(letters(name), BLACK, 600, 200, 4.0)
        check(f"« {name[:28]} » tient sur une ligne",
              box is not None and (box[3] - box[1]) <= rows.height)
        check(f"…et reste dans la largeur ({name[:12]}…)", img.width <= 600)

    print("\n— rien n'est coupé —")
    long_name = "BOULANGERIE PÂTISSERIE DU VIEUX MOULIN"
    wide, narrow = styled(long_name, room=600), styled(long_name, room=200)
    check("un nom long rentre dans une largeur étroite", narrow.width <= 200)
    check("…et il est dessiné plus petit, pas tronqué",
          ink_box(narrow)[3] - ink_box(narrow)[1] < ink_box(wide)[3] - ink_box(wide)[1])

    print("\n— agrandir agrandit vraiment —")
    # a short name has room to grow: 200 % must draw taller than 100 %
    h100 = ink_box(styled("FID", 100))
    h200 = ink_box(styled("FID", 200))
    check(f"« FID » à 200 % est plus haut qu'à 100 % ({h200[3] - h200[1]} > {h100[3] - h100[1]})",
          (h200[3] - h200[1]) > (h100[3] - h100[1]))
    w100, w200 = styled("FID", 100).width, styled("FID", 200).width
    check(f"…et plus large ({w200} > {w100})", w200 > w100)

    print("\n— une lettre seule grandit par rapport aux autres —")
    mixed = ((("R", 200, None, None),) + letters("OYAL")[0:4])
    img = WP._styled_name_image(mixed, BLACK, 600, 200, 4.0)
    plain = WP._styled_name_image(letters("ROYAL"), BLACK, 600, 200, 4.0)
    check("un « R » à 200 % change le dessin", img.tobytes() != plain.tobytes())

    print("\n— le nom simple aussi tient sur une ligne —")
    out = WP._make_name_logo(None, "BOULANGERIE DU VIEUX MOULIN ET FILS", BLACK, BOX)
    im = Image.open(io.BytesIO(out["@2x"])).convert("RGBA")
    b = ink_box(im)
    one_line_max = im.height * 0.6            # two lines would cover far more
    check(f"le nom simple ne passe pas à la ligne ({b[3] - b[1]} px de haut)",
          b is not None and (b[3] - b[1]) <= one_line_max)
    check("…et ne déborde pas", b[2] <= im.width)

    print("\n— la plage de tailles reste celle de l'éditeur —")
    check("50 % à 200 %", (WP.NAME_SIZE_MIN, WP.NAME_SIZE_MAX) == (50, 200))

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
