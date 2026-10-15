"""
A photo made ready for a vision model (2026-10-15: an iPhone menu photo,
.HEIC, failed « Import depuis une photo »).

The vision APIs take JPEG / PNG / GIF / WebP only, and a phone photo is often
HEIC and several MB — over Vercel's 4.5 MB request body once in base64. Every
photo is opened (HEIC too, through pillow-heif), turned upright from its EXIF,
brought down to 1600 px on its long side — about what the models read at full
detail anyway — and sent as JPEG. A file that will not open is passed on as
it came, so the provider says what is wrong with it.
"""
import base64
import io
from typing import Tuple

try:                                           # HEIC / HEIF from an iPhone
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:                              # noqa: BLE001 — without it, HEIC is passed on as is
    pass

MAX_SIDE = 1600


def for_vision(image_b64: str, mime: str = "") -> Tuple[str, str]:
    """(base64 JPEG, "image/jpeg"), or what came in when it cannot be read."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(io.BytesIO(base64.b64decode(image_b64)))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            bg = Image.new("RGB", im.size, (255, 255, 255))      # a transparent PNG: on white, not black
            im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1])
            im = bg
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        return base64.b64encode(out.getvalue()).decode(), "image/jpeg"
    except Exception:                          # noqa: BLE001
        return image_b64, (mime or "image/jpeg")
