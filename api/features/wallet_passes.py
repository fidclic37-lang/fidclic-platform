"""
Native wallet passes — Apple Wallet (.pkpass) + Google Wallet (loyalty object).
Status: 🟢 Core once the certificates are in Vercel; safe no-op before that.

Mounts at:
    GET  /api/wallet/config                          → which wallets are live
    GET  /api/card/{barcode_id}/apple-wallet.pkpass  → signed pass (download)
    GET  /api/card/{barcode_id}/google-wallet         → { url } "Save to Google Wallet"
    Apple PassKit web service (spec: developer.apple.com → Wallet → Web Service):
    POST   /api/passes/v1/devices/{dev}/registrations/{ptid}/{serial}
    GET    /api/passes/v1/devices/{dev}/registrations/{ptid}
    DELETE /api/passes/v1/devices/{dev}/registrations/{ptid}/{serial}
    GET    /api/passes/v1/passes/{ptid}/{serial}
    POST   /api/passes/v1/log

DESIGN CONTRACT
    The pass is built from the SAME card_template fields that WalletPassPreview
    renders (onboarding step 3 / Card Designer), so what the merchant saw is
    what lands in Wallet:
        surface_color / surface   → backgroundColor
        ink (derived, cardTheme)  → foregroundColor
        label tint (derived)      → labelColor
        logo_url                  → logo.png + icon.png
        card_name / tagline       → logoText (+ back field)
        hero_image_url            → strip.png (375×144, when hero_mode is image)
        points / visits / stamps / tier / reward → fields
        barcode_id                → QR + altText, serialNumber

ENV (Vercel — never in git)
    APPLE_PASS_TYPE_ID   pass.com.fidclic.loyalty
    APPLE_TEAM_ID        10-char team id
    APPLE_PASS_CERT_B64  base64 of pass-cert.pem   (openssl pkcs12 -clcerts -nokeys)
    APPLE_PASS_KEY_B64   base64 of pass-key.pem    (openssl pkcs12 -nocerts -nodes)
    APPLE_WWDR_B64       base64 of Apple WWDR G4 in PEM
    PASS_AUTH_SECRET     any long random string (per-pass auth tokens); JWT_SECRET fallback
    GOOGLE_WALLET_ISSUER_ID   numeric issuer id (pay.google.com/business/console)
                              — or GOOGLE_WALLET_CLASS_ID, whose head is that id
    GOOGLE_WALLET_SA_B64      base64 of the service-account JSON key
                              — or GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL plus
                                GOOGLE_WALLET_PRIVATE_KEY, the two fields of it

UPDATES
    Every pass carries webServiceURL + authenticationToken, so Wallet's
    pull-to-refresh and the registration endpoints work out of the box.
    APNs push ("your card changed") is the follow-up: it needs an HTTP/2
    client to api.push.apple.com signed with the same pass certificate —
    registrations are already stored in `pass_registrations` for it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import require_role, TokenData

router = APIRouter(tags=["wallet-passes"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        _db.pass_registrations.create_index([("device_id", 1), ("serial", 1)], unique=True)
        _db.pass_registrations.create_index([("serial", 1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Config / env
# ---------------------------------------------------------------------------
def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _b64_env(name: str) -> bytes:
    v = _env(name)
    if not v:
        return b""
    try:
        return base64.b64decode(v)
    except Exception:
        return v.encode()  # someone pasted the PEM directly — accept it


def apple_configured() -> bool:
    return all([_env("APPLE_PASS_TYPE_ID"), _env("APPLE_TEAM_ID"),
                _b64_env("APPLE_PASS_CERT_B64"), _b64_env("APPLE_PASS_KEY_B64"), _b64_env("APPLE_WWDR_B64")])


def _gw_issuer() -> str:
    """The numeric issuer id, however it was configured.

    Two shapes are in the wild and both are legitimate:
      GOOGLE_WALLET_ISSUER_ID   the id on its own
      GOOGLE_WALLET_CLASS_ID    "<issuer>.<suffix>" — the id is the head of it
    Reading both means a deployment that set one does not silently report
    "Google is not configured" while holding everything it needs.
    """
    direct = _env("GOOGLE_WALLET_ISSUER_ID")
    if direct:
        return direct
    class_id = _env("GOOGLE_WALLET_CLASS_ID")
    head = class_id.split(".", 1)[0].strip() if class_id else ""
    return head if head.isdigit() else ""


def google_configured() -> bool:
    return bool(_gw_issuer() and _gw_credentials())


def _site_url() -> str:
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("PUBLIC_SITE_URL") or "https://app.fidclic.com").rstrip("/")


def _auth_token(serial: str) -> str:
    """Per-pass authenticationToken (≥16 chars per Apple). Derived, so no
    storage and no way to forge one without the secret."""
    secret = (_env("PASS_AUTH_SECRET") or _env("JWT_SECRET") or "fidclic-dev-secret").encode()
    return hmac.new(secret, serial.encode(), hashlib.sha256).hexdigest()[:40]


def _wallet_in_plan(barcode_id: str) -> bool:
    """Super admin › Plan Limits › « Wallet (Apple/Google) » for this card's business."""
    c = _db.customers.find_one({"barcode_id": barcode_id}, {"_id": 0, "tenant_id": 1}) if barcode_id else None
    if not c:
        return True
    from features import plan_limits
    return plan_limits.allows_tenant(c.get("tenant_id"), "wallet")


@router.get("/api/wallet/config")
def wallet_config(barcode: str = ""):
    on = _wallet_in_plan(barcode) if barcode else True
    return {"apple": on and apple_configured(), "google": on and google_configured(), "in_plan": on}


@router.get("/api/owner/wallet/google-status")
def google_status(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Where this issuer stands with Google.

    Google gates production: until the issuer is approved, a pass can only be
    saved by accounts on the test list. The class carries the verdict as
    `reviewStatus` — draft / underReview / approved / rejected — so the answer
    comes from Google rather than from a guess.
    """
    if not google_configured():
        return {"configured": False, "issuer_id": None, "review_status": None,
                "message": "Google Wallet n'est pas configuré : il manque l'identifiant émetteur "
                           "(GOOGLE_WALLET_ISSUER_ID ou GOOGLE_WALLET_CLASS_ID) ou le compte de "
                           "service (GOOGLE_WALLET_SA_B64, ou SERVICE_ACCOUNT_EMAIL + PRIVATE_KEY)."}
    try:
        token = _gw_access_token()
        issuer = _gw_issuer()
        class_id = f"{issuer}.fidclic_{token_data.tenant_id}".replace("-", "_")
        status, body = _gw_call("GET", f"/loyaltyClass/{class_id}", None, token)
    except Exception as exc:
        return {"configured": True, "issuer_id": _gw_issuer(),
                "review_status": None,
                "message": (("La clé privée Google est illisible, même après réparation automatique. "
                             "Dans Vercel, remplacez GOOGLE_WALLET_SA_B64 par le fichier JSON du compte de "
                             "service encodé en base64 (ou GOOGLE_WALLET_PRIVATE_KEY par le champ "
                             "« private_key » de ce fichier, recopié tel quel), puis redéployez.")
                            if any(w in str(exc) for w in ("PEM", "key", "Key", "Could not deserialize"))
                            else f"Google n'a pas répondu : {exc}")}
    if status != 200:
        return {"configured": True, "issuer_id": _gw_issuer(),
                "review_status": "draft",
                "message": "La carte n'a pas encore été créée chez Google. "
                           "Elle le sera au premier « Ajouter à Google Wallet »."}
    review = body.get("reviewStatus") or "draft"
    says = {
        "draft":       "Brouillon : seuls vos comptes de test peuvent ajouter la carte.",
        "underReview": "En cours d'examen par Google.",
        "approved":    "Approuvé : tous vos clients peuvent ajouter la carte.",
        "rejected":    "Refusé par Google — voir les commentaires dans la console.",
    }
    return {"configured": True, "issuer_id": _gw_issuer(),
            "review_status": review, "class_id": class_id,
            "review_comments": (body.get("review") or {}).get("comments") or [],
            "message": says.get(review, review)}


# ---------------------------------------------------------------------------
# Colour derivation — a Python mirror of src/lib/cardTheme.js so the pass
# colours match the on-screen preview exactly. Keep the two in sync.
# ---------------------------------------------------------------------------
SURFACE_PRESETS = {
    "noir": "#141519", "anthracite": "#1C1D22", "marine": "#101B2E", "foret": "#12211A",
    "espresso": "#211711", "blanc": "#FDFCFA", "creme": "#F6EFE3", "sable": "#EFE9DD",
}
INK_LIGHT, INK_DARK = "#F4F3F0", "#17181C"


def _rgb(hex_: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not hex_ or not isinstance(hex_, str):
        return None
    h = hex_.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _lum(c: Tuple[int, int, int]) -> float:
    def ch(v: int) -> float:
        v2 = v / 255
        return v2 / 12.92 if v2 <= 0.03928 else ((v2 + 0.055) / 1.055) ** 2.4
    r, g, b = c
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _blend(fg: Tuple[int, int, int], bg: Tuple[int, int, int], alpha: float) -> Tuple[int, int, int]:
    return tuple(round(f * alpha + b * (1 - alpha)) for f, b in zip(fg, bg))  # type: ignore[return-value]


def _css(c: Tuple[int, int, int]) -> str:
    return "rgb(%d, %d, %d)" % c


def derive_colors(card: Dict[str, Any]) -> Dict[str, str]:
    bg = _rgb(card.get("surface_color")) or _rgb(SURFACE_PRESETS.get(card.get("surface") or "")) \
        or (_rgb(SURFACE_PRESETS["blanc"]) if card.get("surface") == "clair" else _rgb(SURFACE_PRESETS["anthracite"]))
    ink = _rgb(INK_LIGHT) if _contrast(_rgb(INK_LIGHT), bg) >= _contrast(_rgb(INK_DARK), bg) else _rgb(INK_DARK)  # type: ignore[arg-type]
    label = _blend(ink, bg, 0.55)  # type: ignore[arg-type]
    brand = _rgb(card.get("brand_color")) or (184, 92, 56)
    return {
        "backgroundColor": _css(bg), "foregroundColor": _css(ink), "labelColor": _css(label),  # type: ignore[arg-type]
        # not part of pass.json — read by compose_strip()
        "surface_hex": "#%02X%02X%02X" % bg, "brand_hex": "#%02X%02X%02X" % brand,  # type: ignore[str-format]
    }


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
def _fetch_image(src: Optional[str]) -> Optional[bytes]:
    """data: URL or https URL → raw bytes (None on any failure)."""
    if not src:
        return None
    try:
        if src.startswith("data:"):
            head, _, data = src.partition(",")
            return base64.b64decode(data) if ";base64" in head else urllib.parse.unquote_to_bytes(data)
        if src.startswith("http"):
            with urllib.request.urlopen(src, timeout=8) as r:  # noqa: S310 — merchant-provided image URL
                return r.read()
    except Exception:
        return None
    return None


def _png_variants(raw: Optional[bytes], box: Tuple[int, int], cover: bool = False,
                  fallback_rgb: Tuple[int, int, int] = (28, 29, 34), tight: bool = False) -> Dict[str, bytes]:
    """Return {'':1x, '@2x':2x, '@3x':3x} PNGs fitted (contain) or filling (cover)
    the given point box. Falls back to a flat brand tile when Pillow is missing
    or the image is unreadable — a pass MUST ship icon.png.

    `tight` (the logo): the canvas is only as wide as the fitted image. Wallet
    reserves the logo's full width, transparent padding included — a square
    logo centred in a 160-pt canvas left the shop name 20 pt and cut it to
    « Royal T… »."""
    out: Dict[str, bytes] = {}
    try:
        from PIL import Image  # Pillow — in api/requirements.txt
        base = None
        if raw:
            try:
                base = Image.open(io.BytesIO(raw)).convert("RGBA")
            except Exception:
                base = None
        for suffix, k in (("", 1), ("@2x", 2), ("@3x", 3)):
            w, h = box[0] * k, box[1] * k
            if base is None:
                img = Image.new("RGBA", ((h if tight else w), h), fallback_rgb + (255,))
            elif cover:
                img = base.copy()
                scale = max(w / img.width, h / img.height)
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
                left, top = (img.width - w) // 2, (img.height - h) // 2
                img = img.crop((left, top, left + w, top + h))
            else:
                img = base.copy()
                # fit, up or down: a 64-px logo must still fill a 150-px @3x box
                scale = min(w / img.width, h / img.height)
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
                cw = img.width if tight else w
                canvas = Image.new("RGBA", (cw, h), (0, 0, 0, 0))
                canvas.paste(img, ((cw - img.width) // 2, (h - img.height) // 2), img)
                img = canvas
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            out[suffix] = buf.getvalue()
        return out
    except ImportError:
        pass
    # No Pillow: ship the raw bytes if they are already a PNG, else a 1×1 tile.
    if raw and raw[:8] == b"\x89PNG\r\n\x1a\n":
        return {"": raw}
    import struct
    import zlib
    w, h = box
    row = b"\x00" + bytes(fallback_rgb) * w
    idat = zlib.compress(row * h)

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return {"": png}


# ---------------------------------------------------------------------------
# The strip — the only place a pass can show a progress meter
# ---------------------------------------------------------------------------
# PassKit has no progress element: a pass can show text, images and a barcode,
# nothing else. Every loyalty card you have seen with a filling gauge (Starbucks,
# Loopy-built cards…) draws it INTO the strip image, server-side, per customer.
# That is what this does — so the meter updates with the pass, like the fields.
STRIP_W, STRIP_H = 1125, 432          # Apple's 375 × 144 pt at 3×


def compose_strip(raw: Optional[bytes], theme: Dict[str, str], stamps: int, threshold: int,
                  with_meter: bool, title: str = "", subtitle: str = "") -> Optional[bytes]:
    """Build the strip: the merchant's photo (or a brand gradient when there is
    none), the current offer written across it, and a segmented progress meter
    burnt into the bottom band. Returns PNG bytes at 3×, or None without Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        return None

    surface = _rgb(theme.get("surface_hex")) or (28, 29, 34)
    brand = _rgb(theme.get("brand_hex")) or (184, 92, 56)

    base: Optional["Image.Image"] = None
    if raw:
        try:
            base = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            base = None

    if base is not None:
        scale = max(STRIP_W / base.width, STRIP_H / base.height)
        base = base.resize((max(1, round(base.width * scale)), max(1, round(base.height * scale))), Image.LANCZOS)
        left, top = (base.width - STRIP_W) // 2, (base.height - STRIP_H) // 2
        img = base.crop((left, top, left + STRIP_W, top + STRIP_H))
    else:
        # No photo: a diagonal brand sheen over the card surface — quiet, but
        # it reads as designed rather than as a flat rectangle.
        def mix(a, b, t):
            return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
        img = Image.new("RGB", (STRIP_W, STRIP_H), surface)
        sheen = Image.new("RGB", (STRIP_W, STRIP_H), mix(surface, brand, 0.55))
        diag = Image.linear_gradient("L").resize((STRIP_W * 2, STRIP_W * 2)).rotate(-35, resample=Image.BICUBIC)
        diag = diag.crop(((diag.width - STRIP_W) // 2, (diag.height - STRIP_H) // 2,
                          (diag.width + STRIP_W) // 2, (diag.height + STRIP_H) // 2))
        img = Image.composite(sheen, img, diag.point(lambda v: 255 - v))
        # a soft highlight where the sheen is strongest, then a touch of blur
        halo = Image.new("RGB", (STRIP_W, STRIP_H), mix(surface, brand, 0.85))
        img = Image.composite(halo, img, diag.point(lambda v: max(0, 255 - v * 3) // 3))
        img = img.filter(ImageFilter.GaussianBlur(14))

    ink = (255, 255, 255) if (raw is not None or _lum(surface) <= 0.45) else (25, 25, 28)
    shadow = (0, 0, 0, 130) if ink == (255, 255, 255) else (255, 255, 255, 140)

    # ---- the offer, written across the brand gradient ----------------------
    # Only on the gradient (no photo): there it fills an otherwise plain band.
    # Over the merchant's own photo it fought with whatever the picture holds
    # and read as amateur (user, 2026-10-04); the offer has its own field.
    if title and base is None:
        d0 = ImageDraw.Draw(img, "RGBA")
        # Pillow's built-in font has no É, è or € — French copy came out as
        # tofu boxes. DejaVu (bundled, free licence) covers Latin-1 and the
        # euro sign; if the file is ever missing we fall back rather than fail.
        fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
        def font_at(size: int, bold: bool = True):
            name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
            try:
                return ImageFont.truetype(os.path.join(fonts_dir, name), size)
            except Exception:
                return ImageFont.load_default(size=size)

        def fit(text: str, size: int, max_w: int, bold: bool = True):
            for s_ in range(size, 22, -2):
                f_ = font_at(s_, bold)
                if d0.textlength(text, font=f_) <= max_w:
                    return f_
            return font_at(22, bold)
        max_w = STRIP_W - 140
        f_title = fit(title.upper(), 62, max_w)
        f_sub = fit(subtitle, 36, max_w, bold=False) if subtitle else None
        block_h = 66 + (44 if f_sub else 0)
        y = (STRIP_H - (150 if with_meter and threshold > 0 else 0) - block_h) // 2
        for text, font, dy, alpha in ((title.upper(), f_title, 0, 255),
                                      (subtitle, f_sub, 66, 215) if f_sub else (None, None, 0, 0)):
            if not text:
                continue
            w = d0.textlength(text, font=font)
            x = (STRIP_W - w) / 2
            d0.text((x + 2, y + dy + 2), text, font=font, fill=shadow)       # legibility on any photo
            d0.text((x, y + dy), text, font=font, fill=ink + (alpha,))

    if not with_meter or threshold <= 0:
        buf = io.BytesIO(); img.save(buf, "PNG", optimize=True); return buf.getvalue()

    # ---- meter: scrim + segmented track, one segment per stamp -------------
    # The scrim follows the card: dark on a dark surface, light on a crème or
    # blanc one, so the bar never sits in a heavy black band on a pale card.
    light_card = raw is None and _lum(surface) > 0.45
    scrim_rgb = (255, 255, 255) if light_card else (0, 0, 0)
    empty_fill = (0, 0, 0, 38) if light_card else (255, 255, 255, 46)
    empty_line = (0, 0, 0, 64) if light_card else (255, 255, 255, 80)

    d = ImageDraw.Draw(img, "RGBA")
    band = 150
    for i in range(band):                      # soft scrim so the bar reads on any photo
        a = int((150 if light_card else 165) * (i / band) ** 1.6)
        d.line([(0, STRIP_H - band + i), (STRIP_W, STRIP_H - band + i)], fill=scrim_rgb + (a,))

    pad, bar_h = 64, 26
    y0 = STRIP_H - 62
    inner = STRIP_W - 2 * pad
    gap = 10
    seg = (inner - gap * (threshold - 1)) / threshold if threshold > 1 else inner
    done = max(0, min(threshold, stamps))
    for i in range(threshold):
        x0 = pad + i * (seg + gap)
        box = [x0, y0, x0 + seg, y0 + bar_h]
        if i < done:
            d.rounded_rectangle(box, radius=bar_h // 2, fill=brand + (255,))
        else:
            d.rounded_rectangle(box, radius=bar_h // 2, fill=empty_fill)
            d.rounded_rectangle(box, radius=bar_h // 2, outline=empty_line, width=2)

    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _strip_variants(png3x: bytes) -> Dict[str, bytes]:
    """3× master → the @2x and 1× Wallet also asks for."""
    try:
        from PIL import Image
    except ImportError:
        return {"@3x": png3x}
    master = Image.open(io.BytesIO(png3x)).convert("RGB")
    out: Dict[str, bytes] = {}
    for suffix, k in (("", 1), ("@2x", 2), ("@3x", 3)):
        img = master if k == 3 else master.resize((375 * k, 144 * k), Image.LANCZOS)
        buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
        out[suffix] = buf.getvalue()
    return out


# ---------------------------------------------------------------------------
# pass.json
# ---------------------------------------------------------------------------
TIER_LABELS = {"bronze": "Bronze", "silver": "Argent", "gold": "Or", "vip": "VIP"}


def _card_payload(barcode_id: str) -> Dict[str, Any]:
    import server as core
    cust = _db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    payload = core._serialize_card_payload(cust)
    _attach_campaign_offer(payload.get("card") or {}, cust)
    return payload


CAMPAIGN_OFFER_DAYS = 30


def _attach_campaign_offer(card: Dict[str, Any], cust: Dict[str, Any]) -> None:
    """Put the merchant's newest wallet campaign on the pass as its offer.

    This is what makes a campaign visible in Apple Wallet. The pass has no
    message of its own — the notification the customer sees is Wallet reacting
    to a field that changed, which is why the offer field carries a
    `changeMessage`. So the campaign becomes the field, the pass is woken, and
    Wallet raises the banner itself.

    Only campaigns the merchant chose to put on the wallet are read, only for
    the customers they were sent to, and only for CAMPAIGN_OFFER_DAYS — after
    that the card goes back to the merchant's own offer rather than showing a
    promotion that has expired.
    """
    try:
        since = _now() - timedelta(days=CAMPAIGN_OFFER_DAYS)
        rows = _db.campaigns.find(
            {"tenant_id": cust.get("tenant_id"), "status": "sent",
             "wallet_offer": True, "recipient_ids": cust.get("id")},
            {"_id": 0, "id": 1, "name": 1, "content": 1, "sent_at": 1, "image_url": 1})
        newest, newest_at = None, None
        for c in rows:
            at = _parse_dt(c.get("sent_at"))
            if at and at >= since and (newest_at is None or at > newest_at):
                newest, newest_at = c, at
        if newest and (newest.get("name") or "").strip():
            title, sub = newest["name"].strip(), (newest.get("content") or "").strip()
            # {first_name}, {points}… filled for this customer, as in the push.
            try:
                import server as core
                tenant = _db.tenants.find_one({"id": cust.get("tenant_id")}) or {}
                title, sub = core.render_template(title, cust, tenant), core.render_template(sub, cust, tenant)
            except Exception:
                pass
            card["campaign_offer"] = {"title": title, "subtitle": sub, "id": newest.get("id"),
                                      "image_url": newest.get("image_url") or None}
    except Exception as exc:        # a missing offer must never cost the pass
        print(f"wallet: campaign offer lookup failed (non-fatal): {exc}")


def _campaign_photo(card: Dict[str, Any]) -> Optional[str]:
    """The photo attached to the live wallet campaign, if any (user, 2026-10-05:
    « photo bhi attach ki thi, toh woh kidhar dikhegi »). Apple shows no image
    in a notification or on the back of a pass — the strip is the only place a
    picture can live — so while the campaign is the card's offer, its photo is
    the banner. When the campaign expires the merchant's own banner returns."""
    campaign = card.get("campaign_offer") if isinstance(card.get("campaign_offer"), dict) else {}
    return campaign.get("image_url") or None


def _hero_raw(card: Dict[str, Any]) -> Optional[bytes]:
    """Bytes of the strip photo: the campaign's, else the merchant's banner."""
    photo = _campaign_photo(card)
    if photo:
        raw = _fetch_image(photo)
        if raw:
            return raw
    hero_mode = card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")
    return _fetch_image(card.get("hero_image_url")) if hero_mode in ("image", "composite") else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    """Apple wants W3C date-time with an offset."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _next_opening(tenant_id: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """When does this shop next open? Used as the pass's relevantDate so the
    card surfaces on the lock screen at opening time — exactly when the
    customer might walk in — instead of never."""
    now = now or _now()
    try:
        from features import business_hours as bh
        tenant = _db.tenants.find_one({"id": tenant_id}) or {}
        weekly = bh._resolve_weekly(tenant)
    except Exception:
        return None
    for ahead in range(0, 8):
        day = (now + timedelta(days=ahead)).date()
        try:
            if not bh.is_open_on(tenant_id, day):
                continue
        except Exception:
            return None
        row = weekly[day.weekday()] if day.weekday() < len(weekly) else {}
        opens = (row or {}).get("open_from") or "09:00"
        try:
            hh, mm = (int(x) for x in str(opens).split(":")[:2])
        except ValueError:
            hh, mm = 9, 0
        when = datetime.combine(day, dt_time(hh, mm), tzinfo=timezone.utc)
        if when > now:
            return when
    return None


def _offer_text(card: Dict[str, Any]) -> Tuple[str, str]:
    """The merchant's current offer, wherever the designer stored it: the
    offer box, the strip band, or the promotion block. The web card shows all
    three, so the pass must read all three or the customer sees a different
    card in Wallet than in the browser."""
    # A campaign the merchant pushed to the wallet is the current offer, and it
    # wins: it is the most recent thing they decided to say, and it is the
    # reason the customer's phone just buzzed.
    campaign = card.get("campaign_offer") if isinstance(card.get("campaign_offer"), dict) else {}
    if (campaign.get("title") or "").strip():
        return campaign["title"].strip(), (campaign.get("subtitle") or "").strip()
    promo = card.get("promotion") if isinstance(card.get("promotion"), dict) else {}
    if card.get("show_offer_box") is not False and (card.get("offer_box_text") or "").strip():
        return card["offer_box_text"].strip(), (card.get("offer_box_subtext") or "").strip()
    if (promo.get("title") or "").strip():
        return promo["title"].strip(), (promo.get("subtitle") or promo.get("body") or "").strip()
    if (card.get("strip_title") or "").strip():
        return card["strip_title"].strip(), (card.get("strip_subtitle") or "").strip()
    active = card.get("active_offer") if isinstance(card.get("active_offer"), dict) else {}
    if active.get("active") and (active.get("title") or "").strip():
        return active["title"].strip(), (active.get("description") or "").strip()
    return "", ""


def _header_fields(card: Dict[str, Any], has_banner: bool, show_points: bool, show_tier: bool,
                   points_field: Dict[str, Any], tier_field: Dict[str, Any],
                   visits: int, visits_label: Optional[str]) -> List[Dict[str, Any]]:
    """Top-right of the pass — the only field visible while the pass is
    collapsed in the stack, so the merchant gets to choose it."""
    choice = (card.get("header_field") or "auto").lower()
    if choice == "none":
        return []
    if choice == "points":
        return [points_field] if show_points else []
    if choice == "tier":
        return [tier_field] if show_tier else []
    if choice == "visits":
        return [{"key": "visits_h", "label": (visits_label or "Visites").upper(), "value": visits}]
    # auto — points when a banner leaves no room for the big number, else statut
    if has_banner:
        return [points_field] if show_points else ([tier_field] if show_tier else [])
    return [tier_field] if show_tier else []


def _void_reason(cust: Dict[str, Any], tenant_doc: Dict[str, Any]) -> Optional[str]:
    """A pass stays in Wallet forever unless it says otherwise. These are the
    cases where it must stop pretending to be usable."""
    if cust.get("gdpr_erased_at") or cust.get("deleted_at"):
        return "erased"
    if cust.get("card_deleted_at"):
        return "deleted"
    if tenant_doc.get("is_active") is False:
        return "tenant_inactive"
    return None


def build_pass_json(payload: Dict[str, Any]) -> Dict[str, Any]:
    cust, tenant, card = payload["customer"], payload["tenant"], payload["card"]
    serial = cust["barcode_id"]
    colors = derive_colors(card)
    org = card.get("card_name") or tenant.get("name") or "FidClic"

    visits = int(cust.get("visits") or 0)
    threshold = max(1, int(card.get("reward_threshold") or card.get("reward_threshold_stamps") or 10))
    visits_per_stamp = max(1, int(card.get("visits_per_stamp") or 1))
    stamps = min(threshold, int(card.get("stamps_earned") if card.get("stamps_earned") is not None else visits // visits_per_stamp))
    remaining = threshold - stamps
    # The card page shows the customer's points balance (1 800 pts). The pass
    # used to show a figure derived from the current cycle, so the same
    # customer read 1 800 on the web and 100 in Wallet. One number, one source.
    points = int(cust.get("points") or 0)
    tier = (cust.get("tier") or "bronze").lower()
    # "Marie" or "Marie Dupont" — the merchant's choice in the advanced panel.
    full_name = (cust.get("name") or "Client").strip()
    first_name = full_name if card.get("use_full_name") else full_name.split(" ")[0]
    reward = card.get("reward_description") or "Une récompense fidélité"

    show = lambda k, default=True: card.get(k) is not False if card.get(k) is not None else default  # noqa: E731

    # A banner (strip) image changes the layout. In a storeCard, Wallet draws
    # the primary fields ON TOP of the strip — so a merchant who uploaded a
    # photo would get their own artwork covered by a big number. With a banner
    # we therefore leave primaryFields empty (clean image, edge to edge) and
    # move the points up to the header, exactly like Apple's own sample passes.
    has_banner = (
        bool(_campaign_photo(card))
        or ((card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")) in ("image", "composite")
         and bool(card.get("hero_image_url")))
        # the meter is painted into a strip too, so the same layout applies
        or (card.get("show_meter") is not False and threshold > 0)
    )

    tier_field = {"key": "tier", "label": "STATUT", "value": TIER_LABELS.get(tier, "Bronze")}
    points_field = {"key": "points", "label": (card.get("points_label") or "Points").upper(), "value": points,
                    "changeMessage": (card.get("points_change_message") or "Vous avez maintenant %@ points")}
    show_tier = show("show_tier") and show("show_tier_badge")

    # ---- the front row ------------------------------------------------------
    # With a strip, Wallet puts secondary AND auxiliary fields on ONE line, so
    # every field must be a short value or the row turns into « PROCHAINE
    # RÉCOM… · Encore 9 tampons · Un café gra… » (user's iPhone, 2026-10-04).
    # Three fields at most: who, how far, and the offer (or the statut).
    secondary: List[Dict[str, Any]] = [{"key": "member", "label": (card.get("greeting_label") or "Membre").upper(), "value": first_name}]
    if show("show_stamps"):
        secondary.append({"key": "stamps", "label": (card.get("stamps_label") or "Tampons").upper(),
                          "value": f"{stamps} / {threshold}",
                          "changeMessage": (card.get("stamps_change_message") or "Tampons : %@")})
    else:
        # changeMessage is what makes Wallet raise a lock-screen notification
        # when the value changes after an update push.
        secondary.append({"key": "reward", "label": "RÉCOMPENSE",
                          "value": "Débloquée !" if remaining <= 0 else f"Encore {remaining}",
                          "changeMessage": "Récompense : %@"})
    offer_title, offer_sub = _offer_text(card)
    tier_front = False
    if offer_title:
        secondary.append({"key": "offer_title", "label": "OFFRE", "value": offer_title})
    elif show_tier and (has_banner or not show("show_points")):
        secondary.append(tier_field)
        tier_front = True
    elif show("show_visits"):
        secondary.append({"key": "visits", "label": (card.get("visits_label") or "Visites").upper(), "value": visits})
    auxiliary: List[Dict[str, Any]] = []

    # The offer lives on the back in full, and is ALWAYS there. Wallet only
    # notifies when an existing field changes value — a field that appears
    # for the first time is silent — so the very first campaign a customer
    # receives must change this field, not create it.
    offer_full = (f"{offer_title} — {offer_sub}" if offer_sub else offer_title) if offer_title \
        else "Aucune offre en ce moment."
    back = [
        {"key": "offer", "label": "Offre du moment", "value": offer_full, "changeMessage": "%@"},
        {"key": "next_reward", "label": "Prochaine récompense",
         "value": "Récompense débloquée : présentez votre carte !" if remaining <= 0
         else f"Encore {remaining} tampon{'s' if remaining > 1 else ''} avant : {reward}"},
        {"key": "program", "label": "Programme de fidélité", "value": f"{reward} tous les {threshold} tampons."},
        {"key": "card", "label": "Ma carte en ligne", "value": f"{_site_url()}/card/{serial}"},
    ]
    if show_tier and not tier_front:
        back.insert(1, {"key": "tier_back", "label": "Statut", "value": tier_field["value"]})
    # Tapping a Wallet notification only opens the pass, and the back of a pass
    # holds text only: the link opens the campaign itself — photo, full text —
    # on the web card (?offre= opens it straight away).
    campaign_id = (card.get("campaign_offer") or {}).get("id") if isinstance(card.get("campaign_offer"), dict) else None
    if campaign_id:
        offer_url = f"{_site_url()}/card/{serial}?offre={urllib.parse.quote(str(campaign_id))}"
        back.insert(1, {"key": "offer_link", "label": "Voir l'offre", "value": offer_url,
                        "attributedValue": f'<a href="{offer_url}">Voir l\'offre en entier</a>'})
    if card.get("tagline"):
        back.append({"key": "tagline", "label": org, "value": card["tagline"]})
    for k, lbl in (("address", "Adresse"), ("phone", "Téléphone"), ("website", "Site web")):
        if tenant.get(k):
            back.append({"key": k, "label": lbl, "value": tenant[k]})
    # Rows the merchant wrote themselves (horaires, CGU, Instagram…).
    for i, row in enumerate(card.get("back_fields") or []):
        label, value = (row.get("label") or "").strip(), (row.get("value") or "").strip()
        if label and value:
            back.append({"key": f"custom{i}", "label": label, "value": value})

    pass_json: Dict[str, Any] = {
        "formatVersion": 1,
        "passTypeIdentifier": _env("APPLE_PASS_TYPE_ID"),
        "teamIdentifier": _env("APPLE_TEAM_ID"),
        "serialNumber": serial,
        "organizationName": tenant.get("name") or org,
        "description": f"Carte de fidélité {org}",
        "logoText": org,
        "webServiceURL": f"{_site_url()}/api/passes",
        "authenticationToken": _auth_token(serial),
        "sharingProhibited": not bool(card.get("allow_sharing")),
        "suppressStripShine": not bool(card.get("strip_shine")),
        **{k: v for k, v in colors.items() if k.endswith("Color")},
        "barcodes": [{
            "format": {
                "barcode": "PKBarcodeFormatCode128",
                "pdf417": "PKBarcodeFormatPDF417",
                "aztec": "PKBarcodeFormatAztec",
            }.get(card.get("code_type"), "PKBarcodeFormatQR"),
            # Always the card URL, never the bare id: the same QR has to work
            # for the till AND for a stranger's camera, which is what makes a
            # customer's own card an invitation. The till pulls the id back
            # out of the URL (server.barcode_from).
            "message": f"{_site_url()}/card/{serial}",
            "messageEncoding": "iso-8859-1",
            # The human-readable line under the code is the merchant's call.
            **({"altText": serial} if card.get("show_card_number") is not False else {}),
        }],
        "storeCard": {
            # With a banner: points in the header, nothing over the image.
            # Without: the classic big number, statut in the header. The
            # merchant can override which value sits top-right.
            "headerFields": _header_fields(card, has_banner, show("show_points"), show_tier,
                                           points_field, tier_field, visits, card.get("visits_label")),
            "primaryFields": [] if has_banner
            else ([points_field] if show("show_points") else []),
            "secondaryFields": secondary[:3],
            "auxiliaryFields": auxiliary,
            "backFields": back,
        },
    }
    # ---- lifecycle: relevance, expiry, void -------------------------------
    # relevantDate — Wallet surfaces the pass on the lock screen around this
    # moment. An offer that ends soon wins; otherwise the shop's next opening.
    offer_until = _parse_dt(card.get("offer_expires_at") or card.get("active_offer_expires_at"))
    if offer_until and offer_until > _now():
        pass_json["relevantDate"] = _iso(_now())
    else:
        opening = _next_opening(tenant.get("id") or "")
        if opening:
            pass_json["relevantDate"] = _iso(opening)

    # expirationDate — set by the merchant for a seasonal or campaign card.
    expires = _parse_dt(card.get("pass_expiration_date"))
    if expires:
        pass_json["expirationDate"] = _iso(expires)

    # voided — the card was deleted by the customer, erased under the GDPR, or
    # the business was deactivated. Wallet then greys the pass out instead of
    # letting someone present a card that no longer exists.
    cust_doc = _db.customers.find_one({"barcode_id": serial}) or {}
    tenant_doc = _db.tenants.find_one({"id": tenant.get("id")}) or {}
    reason = _void_reason(cust_doc, tenant_doc)
    if reason:
        pass_json["voided"] = True
        pass_json["expirationDate"] = pass_json.get("expirationDate") or _iso(_now())
        back.insert(0, {"key": "voided", "label": "Carte inactive",
                        "value": "Cette carte n'est plus active. Contactez l'établissement pour en obtenir une nouvelle."})

    # One radius for the shop (Paramètres › Établissement), and every open
    # establishment with a pin — Apple takes up to ten.
    if card.get("location_reminder") is not False:
        radius = int(tenant_doc.get("geo_radius_meters") or card.get("location_radius_m") or 200)
        text = card.get("location_text") or f"Vous êtes près de {org} — pensez à scanner votre carte."
        spots = []
        lat, lng = tenant.get("lat") or tenant.get("latitude"), tenant.get("lng") or tenant.get("longitude")
        if lat and lng:
            spots.append((float(lat), float(lng)))
        for b in tenant_doc.get("branches") or []:
            if b.get("status") != "closed" and b.get("latitude") is not None and b.get("longitude") is not None:
                p = (float(b["latitude"]), float(b["longitude"]))
                if p not in spots:
                    spots.append(p)
        if spots:
            pass_json["locations"] = [{"latitude": la, "longitude": lo, "maxDistance": radius,
                                       "relevantText": text} for la, lo in spots[:10]]
    return pass_json


# ---------------------------------------------------------------------------
# Signing + bundling
# ---------------------------------------------------------------------------
def _sign_manifest(manifest: bytes) -> bytes:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.serialization import pkcs7

    cert = x509.load_pem_x509_certificate(_b64_env("APPLE_PASS_CERT_B64"))
    pw = _env("APPLE_PASS_KEY_PASSWORD")
    key = serialization.load_pem_private_key(_b64_env("APPLE_PASS_KEY_B64"), password=pw.encode() if pw else None)
    wwdr = x509.load_pem_x509_certificate(_b64_env("APPLE_WWDR_B64"))
    return (pkcs7.PKCS7SignatureBuilder()
            .set_data(manifest)
            .add_signer(cert, key, hashes.SHA256())
            .add_certificate(wwdr)
            .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature, pkcs7.PKCS7Options.Binary]))


def strip_png(payload: Dict[str, Any]) -> Optional[bytes]:
    """The 1125×432 strip a card ships with — the merchant's banner with the
    progress meter painted into it, or the brand gradient with the meter when
    there is no banner. One function so Apple's strip.png, Google's heroImage
    and the web preview cannot drift apart."""
    card = payload["card"]
    cust = payload["customer"]
    hero_raw = _hero_raw(card)
    with_meter = card.get("show_meter") is not False and int(card.get("reward_threshold") or 0) > 0
    if not hero_raw and not with_meter:
        return None
    threshold = max(1, int(card.get("reward_threshold") or card.get("reward_threshold_stamps") or 10))
    visits_per_stamp = max(1, int(card.get("visits_per_stamp") or 1))
    stamps = int(card.get("stamps_earned") if card.get("stamps_earned") is not None
                 else int(cust.get("visits") or 0) // visits_per_stamp)
    title, sub = _offer_text(card)
    return compose_strip(hero_raw, derive_colors(card), stamps, threshold, with_meter,
                         title=title, subtitle=sub)


def build_pkpass(payload: Dict[str, Any]) -> bytes:
    card = payload["card"]
    files: Dict[str, bytes] = {"pass.json": json.dumps(build_pass_json(payload), ensure_ascii=False).encode("utf-8")}

    brand = _rgb(card.get("brand_color")) or (184, 92, 56)
    logo_raw = _fetch_image(card.get("logo_url"))
    for suffix, png in _png_variants(logo_raw, (29, 29), cover=True, fallback_rgb=brand).items():
        files[f"icon{suffix}.png"] = png
    # The logo sits left of the shop name: at most 50 pt square-ish, never
    # wider than it needs, so the name is written out in full.
    for suffix, png in _png_variants(logo_raw, (100, 50), fallback_rgb=brand, tight=True).items():
        files[f"logo{suffix}.png"] = png
    # ---- strip: banner photo and/or the progress meter ---------------------
    # A strip is produced when the merchant uploaded a banner OR when the meter
    # is on (show_meter, default true) — in that case the photo is replaced by a
    # quiet brand gradient, which still reads far better than a flat card.
    strip3x = strip_png(payload)
    if strip3x:
        for suffix, png in _strip_variants(strip3x).items():
            files[f"strip{suffix}.png"] = png
    else:                                    # no Pillow → ship the photo as-is
        hero_raw = _hero_raw(card)
        if hero_raw:
            for suffix, png in _png_variants(hero_raw, (375, 144), cover=True).items():
                files[f"strip{suffix}.png"] = png

    manifest = json.dumps({name: hashlib.sha1(data).hexdigest() for name, data in files.items()}).encode()
    files["manifest.json"] = manifest
    files["signature"] = _sign_manifest(manifest)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def _pkpass_response(barcode_id: str) -> Response:
    if not apple_configured():
        raise HTTPException(status_code=503, detail="Apple Wallet n'est pas encore configuré")
    payload = _card_payload(barcode_id)
    data = build_pkpass(payload)
    fname = f"fidclic-{barcode_id}.pkpass"
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.apple.pkpass",
                            headers={"Content-Disposition": f'attachment; filename="{fname}"',
                                     "Last-Modified": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
                                     "Cache-Control": "no-store"})


def notify_passes(serials: Iterable[str], google_notify: Any = None,
                  design_changed: bool = False) -> Dict[str, Any]:
    """Tell every device holding these passes to refresh — Apple by push,
    Google by sending it the new card. Best effort — a scan must never fail
    because a push did. Dead tokens are dropped."""
    serials = [s for s in dict.fromkeys(serials) if s]
    res = _notify_apple(serials)
    try:
        res["google"] = google_sync(serials, notify=google_notify, update_class=design_changed)
    except Exception as exc:                       # noqa: BLE001
        res["google"] = {"errors": [str(exc)[:160]]}
    return res


def _notify_apple(serials: List[str]) -> Dict[str, Any]:
    from services import apns_passes

    if not serials or not apns_passes.is_configured():
        return {"devices": 0, "sent": 0, "skipped": "not configured" if serials else "no serials"}
    # Stamp the change BEFORE the push: the device answers the push by asking
    # which passes changed since its last fetch (serials_for_device). Without
    # this a campaign or a design change left the customer record untouched,
    # the answer was « nothing changed » (204), and the pass — and its
    # lock-screen notification — never came.
    _db.pass_registrations.update_many({"serial": {"$in": serials}},
                                       {"$set": {"pass_changed_at": datetime.now(timezone.utc)}})
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}}, {"push_token": 1, "device_id": 1}))
    if not regs:
        return {"devices": 0, "sent": 0}
    res = apns_passes.push_to_tokens([r.get("push_token") for r in regs])
    # What Apple answered, kept on the registrations: the owner's Wallet stats
    # show it, so « no notification » can be traced without server logs.
    outcome = "ok" if res.get("sent") else ("; ".join(res.get("errors", [])[:2]) or "not sent")
    _db.pass_registrations.update_many({"serial": {"$in": serials}}, {"$set": {
        "last_push_at": datetime.now(timezone.utc), "last_push_result": outcome[:200]}})
    for dead in res.get("gone", []):
        try:
            _db.pass_registrations.delete_many({"push_token": dead})
        except Exception:
            pass
    return {"devices": len(regs), "sent": res.get("sent", 0),
            "dropped": len(res.get("gone", [])), "failed": res.get("failed", 0),
            "errors": res.get("errors", [])[:3]}


def notify_customer(customer_id: str, message: Optional[str] = None,
                    google_notify: Any = None) -> Dict[str, Any]:
    """`message` is accepted for the automations' calls (push_wallet), which
    passed it while this function took no such argument — every scenario's
    wake-up raised a TypeError and was silently skipped. The message itself
    reaches the customer by web push / SMS; the pass shows the card."""
    cust = _db.customers.find_one({"id": customer_id}, {"barcode_id": 1}) or {}
    return (notify_passes([cust.get("barcode_id")], google_notify=google_notify)
            if cust.get("barcode_id") else {"devices": 0, "sent": 0})


def notify_tenant(tenant_id: str, customer_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Every registered pass of a tenant (or just the given customers) — used
    when the card design or an offer changes."""
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_ids:
        q["id"] = {"$in": list(customer_ids)}
    serials = [c.get("barcode_id") for c in _db.customers.find(q, {"barcode_id": 1})]
    return notify_passes(serials, design_changed=not customer_ids)


def _iso_or_none(d: Any) -> Optional[str]:
    if not isinstance(d, datetime):
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@router.get("/api/owner/wallet/stats")
def owner_wallet_stats(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """How the Wallet side of the programme is doing: how many customers carry
    a native pass, on how many devices, and when they were last refreshed."""
    tid = token_data.tenant_id
    serials = [c["barcode_id"] for c in _db.customers.find(
        {"tenant_id": tid, "barcode_id": {"$exists": True}}, {"barcode_id": 1}) if c.get("barcode_id")]
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}},
                                            {"serial": 1, "updated_at": 1, "created_at": 1, "last_push_at": 1,
                                             "last_push_result": 1, "last_check_at": 1, "last_fetch_at": 1}))
    customers = len(serials)
    installed = len({r["serial"] for r in regs})
    last = max([r.get("updated_at") or r.get("created_at") for r in regs if r.get("updated_at") or r.get("created_at")],
               default=None)
    try:
        from services import apns_passes
        push_ready = apns_passes.is_configured() and apns_passes.transport_ready()
    except Exception:
        push_ready = False
    return {
        "apple_configured": apple_configured(),
        "push_ready": push_ready,             # can we actually wake devices?
        "customers": customers,
        "passes_installed": installed,        # customers carrying the pass
        "devices": len(regs),                 # iPhone + Watch count as two
        "install_rate": round(installed / customers * 100) if customers else 0,
        "last_registration_at": last.isoformat() if last else None,
        # The update chain, newest device first: we push → the iPhone asks
        # what changed → it fetches the pass. A gap shows where it breaks.
        "devices_detail": [{
            "card": r.get("serial"),
            "last_push_at": _iso_or_none(r.get("last_push_at")), "last_push_result": r.get("last_push_result"),
            "last_check_at": _iso_or_none(r.get("last_check_at")), "last_fetch_at": _iso_or_none(r.get("last_fetch_at")),
        } for r in sorted(regs, key=lambda r: _iso_or_none(r.get("updated_at") or r.get("created_at")) or "", reverse=True)[:10]],
        # Only lines naming one of THIS shop's cards: the log is shared by every
        # device, and another shop's card numbers are not ours to show.
        "google": {
            "configured": google_configured(),
            "cards": _db.google_wallet_objects.count_documents({"serial": {"$in": serials}}),
            "recent": [{"card": g.get("serial"), "last_sync_at": _iso_or_none(g.get("last_sync_at")),
                        "last_sync_result": g.get("last_sync_result")}
                       for g in _db.google_wallet_objects.find({"serial": {"$in": serials}}, {"_id": 0})
                       .sort("updated_at", -1).limit(10)],
        },
        "device_logs": [{"at": _iso_or_none(d.get("at")), "line": d.get("line")}
                        for d in _db.pass_device_logs.find({}, {"_id": 0}).sort("at", -1).limit(200)
                        if any(sr in (d.get("line") or "") for sr in serials)][:10],
    }


class PassPreviewIn(BaseModel):
    card: Dict[str, Any] = {}          # the designer's unsaved fields, if any
    visits: int = 3


# Keys a draft may change on the preview — the designer's own fields, nothing
# that would let a request read another tenant's data.
_PREVIEW_KEYS = {
    "card_name", "surface_color", "surface", "brand_color", "logo_url", "hero_image_url", "hero_mode",
    "tagline", "offer_box_text", "offer_box_subtext", "show_offer_box", "show_points", "show_tier",
    "show_tier_badge", "show_visits", "show_stamps", "show_meter", "code_type", "show_card_number",
    "use_full_name", "greeting_label", "points_label", "visits_label", "stamps_label",
    "reward_threshold_stamps", "reward_description", "points_per_visit", "visits_per_stamp",
    "header_field", "strip_shine", "back_fields", "allow_sharing",
}


def _data_url(png: Optional[bytes]) -> Optional[str]:
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


@router.post("/api/owner/wallet/preview")
def owner_wallet_preview(body: PassPreviewIn,
                         token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    """The Apple Wallet pass exactly as build_pkpass() would make it — the same
    pass.json fields, the same strip and logo images — for a sample customer,
    with the designer's unsaved fields applied. The page draws THIS, so the
    preview cannot drift from the real pass again (user, 2026-10-04: the
    preview still showed the old layout after the pass changed)."""
    import server as core
    tid = token_data.tenant_id
    visits = max(0, min(int(body.visits or 0), 500))
    sample = {"id": "preview-sample", "tenant_id": tid, "barcode_id": "FT-EXEMPLE1",
              "name": "Marie Dupont", "visits": visits, "tier": "bronze", "points": 0}
    payload = core._serialize_card_payload(sample)
    card = payload["card"]
    card.update({k: v for k, v in (body.card or {}).items() if k in _PREVIEW_KEYS and v is not None})
    if body.card.get("reward_threshold_stamps"):
        card["reward_threshold"] = body.card["reward_threshold_stamps"]
    card.pop("stamps_earned", None)            # recomputed from the sample's visits
    sample["points"] = visits * int(card.get("points_per_visit") or 10)
    payload["customer"] = {**payload.get("customer", {}), **sample}

    pj = build_pass_json(payload)
    strip3x = strip_png(payload)
    strip2x = _strip_variants(strip3x).get("@2x") if strip3x else None
    logo2x = _png_variants(_fetch_image(card.get("logo_url")), (100, 50),
                           fallback_rgb=_rgb(card.get("brand_color")) or (184, 92, 56), tight=True).get("@2x")
    logo_w = 50
    try:
        from PIL import Image
        if logo2x:
            logo_w = round(Image.open(io.BytesIO(logo2x)).width / 2)
    except Exception:
        pass
    sc = pj.get("storeCard", {})
    bc = (pj.get("barcodes") or [{}])[0]
    return {
        "logoText": pj.get("logoText"),
        "colors": {k: pj.get(k) for k in ("backgroundColor", "foregroundColor", "labelColor")},
        "headerFields": sc.get("headerFields", []), "primaryFields": sc.get("primaryFields", []),
        "secondaryFields": sc.get("secondaryFields", []), "auxiliaryFields": sc.get("auxiliaryFields", []),
        "backFields": sc.get("backFields", []),
        "barcode": {"format": bc.get("format"), "message": bc.get("message"), "altText": bc.get("altText")},
        "strip": _data_url(strip2x), "logo": _data_url(logo2x), "logo_width": logo_w,
        "sample": {"name": sample["name"], "visits": visits},
    }


@router.post("/api/owner/wallet/notify")
def owner_notify(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Manual "refresh my customers' passes" — handy after a design change."""
    return notify_tenant(token_data.tenant_id)


@router.get("/api/card/{barcode_id}/apple-wallet.pkpass")
def download_apple_pass(barcode_id: str):
    if not _wallet_in_plan(barcode_id):
        raise HTTPException(status_code=403, detail="Apple Wallet n'est pas inclus dans l'offre de ce commerce.")
    return _pkpass_response(barcode_id)


@router.get("/api/card/{barcode_id}/wallet-strip.png")
def wallet_strip(barcode_id: str):
    """The card's banner with the meter painted on it.

    Google Wallet fetches its hero image over HTTP — it cannot take the bytes
    inline the way a .pkpass can — so the same picture Apple gets inside the
    pass is served here. Public by design: it is a banner and a progress bar,
    carries no personal data beyond what the customer's own card shows, and the
    card number in the path is already the customer's public identifier.
    """
    png = strip_png(_card_payload(barcode_id))
    if not png:
        raise HTTPException(status_code=404, detail="No strip for this card")
    return Response(content=png, media_type="image/png",
                    # Google re-fetches when the ?v= changes, so a long cache is
                    # safe and keeps their crawler off the database.
                    headers={"Cache-Control": "public, max-age=3600"})


# ---------------------------------------------------------------------------
# Apple PassKit web service — registrations + refresh (spec-shaped routes)
# ---------------------------------------------------------------------------
def _check_pass_auth(authorization: Optional[str], serial: str) -> None:
    expected = "ApplePass " + _auth_token(serial)
    if not authorization or not hmac.compare_digest(authorization.strip(), expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


class Registration(BaseModel):
    pushToken: str


@router.post("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}/{serial}")
def register_device(device_id: str, pass_type_id: str, serial: str, body: Registration,
                    authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    cust = _db.customers.find_one({"barcode_id": serial}, {"tenant_id": 1})
    if not cust:
        raise HTTPException(status_code=404)
    existing = _db.pass_registrations.find_one({"device_id": device_id, "serial": serial})
    _db.pass_registrations.update_one(
        {"device_id": device_id, "serial": serial},
        {"$set": {"push_token": body.pushToken, "pass_type_id": pass_type_id, "tenant_id": cust.get("tenant_id"),
                  "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True)
    return Response(status_code=200 if existing else 201)


@router.api_route("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}", methods=["GET", "HEAD"])
def serials_for_device(device_id: str, pass_type_id: str, passesUpdatedSince: Optional[str] = None):
    regs = list(_db.pass_registrations.find({"device_id": device_id, "pass_type_id": pass_type_id}))
    if not regs:
        return Response(status_code=204)
    _db.pass_registrations.update_many({"device_id": device_id}, {"$set": {"last_check_at": datetime.now(timezone.utc)}})
    serials = [r["serial"] for r in regs]
    since = None
    if passesUpdatedSince:
        try:
            since = datetime.fromtimestamp(int(passesUpdatedSince), tz=timezone.utc)
        except ValueError:
            since = None
    if since:
        # A pass changed when its customer changed (visit, redemption, tier)
        # or when we pushed it an update (campaign, offer, design — see
        # notify_passes).
        def _aware(d):
            return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)
        pushed = {r["serial"] for r in regs if (_aware(r.get("pass_changed_at")) or since) > since}
        changed = {c["barcode_id"] for c in _db.customers.find(
            {"barcode_id": {"$in": serials}, "updated_at": {"$gt": since}}, {"barcode_id": 1})}
        serials = [x for x in serials if x in pushed or x in changed]
        if not serials:
            return Response(status_code=204)
    return {"serialNumbers": serials, "lastUpdated": str(int(time.time()))}


@router.delete("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}/{serial}")
def unregister_device(device_id: str, pass_type_id: str, serial: str,
                      authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    _db.pass_registrations.delete_one({"device_id": device_id, "serial": serial})
    return Response(status_code=200)


# HEAD too: Wallet may ask before it downloads; a 405 there left some
# devices on the pass they already had.
@router.api_route("/api/passes/v1/passes/{pass_type_id}/{serial}", methods=["GET", "HEAD"])
def latest_pass(pass_type_id: str, serial: str, authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    _db.pass_registrations.update_many({"serial": serial}, {"$set": {"last_fetch_at": datetime.now(timezone.utc)}})
    return _pkpass_response(serial)


@router.post("/api/passes/v1/log")
async def passkit_log(request: Request):
    try:
        body = await request.json()
        lines = [str(x)[:500] for x in (body or {}).get("logs", [])[:20]]
        for line in lines:
            print(f"[passkit] {line}")
        # Kept (last 50) so the owner's Wallet stats can show what the iPhone
        # complained about — Vercel logs are not something a merchant reads.
        if lines:
            _db.pass_device_logs.insert_many([{"at": datetime.now(timezone.utc), "line": l} for l in lines])
            old = [d["_id"] for d in _db.pass_device_logs.find({}, {"_id": 1}).sort("at", -1).skip(50)]
            if old:
                _db.pass_device_logs.delete_many({"_id": {"$in": old}})
    except Exception:
        pass
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Google Wallet — loyalty class per tenant, loyalty object per customer,
# "Save to Google Wallet" link = signed JWT. REST via urllib, no SDK.
# ---------------------------------------------------------------------------
_GW_SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
_GW_API = "https://walletobjects.googleapis.com/walletobjects/v1"


def _gw_credentials() -> Optional[Dict[str, Any]]:
    """The service account, from whichever pair of variables is set.

      GOOGLE_WALLET_SA_B64                                 the whole JSON key
      GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL + _PRIVATE_KEY   the two fields of it

    Only `client_email`, `private_key` and `token_uri` are ever used, so the
    second shape is not a lesser one — it carries everything that matters. A
    key pasted with literal \n instead of newlines (which is what a console
    copy-paste usually produces) is repaired rather than left to fail at
    signing time with an opaque error.
    """
    blob = _b64_env("GOOGLE_WALLET_SA_B64")
    if blob:
        try:
            sa = json.loads(blob.decode())
        except Exception:
            return None
        if sa.get("client_email") and sa.get("private_key"):
            sa.setdefault("token_uri", "https://oauth2.googleapis.com/token")
            sa["private_key"] = _normalize_pem(sa["private_key"])
            return sa
        return None

    email = _env("GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL")
    key = _env("GOOGLE_WALLET_PRIVATE_KEY") or _b64_env("GOOGLE_WALLET_PRIVATE_KEY_B64").decode(errors="ignore")
    if not (email and key):
        return None
    return {"client_email": email, "private_key": _normalize_pem(key),
            "token_uri": "https://oauth2.googleapis.com/token"}



def _normalize_pem(key: str) -> str:
    """Repair the ways a private key gets mangled on its way into an
    environment variable (user, 2026-10-04: « Unable to load PEM file …
    MalformedFraming »):
      - wrapped in quotes, or with the JSON's literal \n kept as text;
      - its line breaks turned into spaces (a one-line paste);
      - pasted without the BEGIN/END lines, or base64-encoded whole.
    The key itself is never changed, only its framing."""
    import re as _re
    k = (key or "").strip().strip('"').strip("'").strip()
    k = k.replace("\\r", "").replace("\\n", "\n").replace("\r", "")
    if "BEGIN" not in k:
        try:                                                  # the whole PEM, base64-encoded
            dec = base64.b64decode(k, validate=False).decode("utf-8", "ignore")
            if "-----BEGIN" in dec:
                k = dec.strip()
        except Exception:
            pass
    m = _re.search(r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----(.*?)-----END \1-----", k, _re.S)
    if m:
        kind, body = m.group(1), _re.sub(r"\s+", "", m.group(2))
    elif "BEGIN" not in k and _re.fullmatch(r"[A-Za-z0-9+/=\s]{100,}", k):
        kind, body = "PRIVATE KEY", _re.sub(r"\s+", "", k)   # body only, no frame
    else:
        return k
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return f"-----BEGIN {kind}-----\n" + "\n".join(lines) + f"\n-----END {kind}-----\n"


def _gw_sa() -> Dict[str, Any]:
    sa = _gw_credentials()
    if not sa:
        raise HTTPException(status_code=503,
                            detail="Google Wallet n'est pas configuré sur cette installation.")
    return sa


_GW_TOKEN: Dict[str, Any] = {"token": None, "exp": 0}


def _gw_access_token() -> str:
    import jwt  # pyjwt
    if _GW_TOKEN["token"] and _GW_TOKEN["exp"] > time.time() + 60:
        return _GW_TOKEN["token"]
    sa = _gw_sa()
    now = int(time.time())
    assertion = jwt.encode({"iss": sa["client_email"], "scope": _GW_SCOPE, "aud": sa["token_uri"],
                            "iat": now, "exp": now + 3600}, sa["private_key"], algorithm="RS256")
    data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}).encode()
    with urllib.request.urlopen(urllib.request.Request(sa["token_uri"], data=data), timeout=10) as r:
        tok = json.loads(r.read())["access_token"]
    _GW_TOKEN.update(token=tok, exp=now + 3300)
    return tok


def _gw_call(method: str, path: str, body: Optional[Dict[str, Any]], token: str) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(_GW_API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, json.loads(e.read() or b"{}")


def _hex6(rgb_css: str) -> str:
    nums = [int(x) for x in rgb_css.strip("rgb() ").split(",")]
    return "#%02X%02X%02X" % tuple(nums)


def _gw_ids(tenant_id: str, serial: str) -> Tuple[str, str]:
    issuer = _gw_issuer()
    return (f"{issuer}.fidclic_{tenant_id}".replace("-", "_"),
            f"{issuer}.{serial}".replace("-", "_"))


def _gw_class(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant, card = payload["tenant"], payload["card"]
    org = card.get("card_name") or tenant.get("name") or "FidClic"
    class_id, _ = _gw_ids(tenant["id"], payload["customer"]["barcode_id"])
    cls: Dict[str, Any] = {
        "id": class_id, "issuerName": tenant.get("name") or org, "programName": org,
        "reviewStatus": "UNDER_REVIEW", "hexBackgroundColor": _hex6(derive_colors(card)["backgroundColor"]),
        "countryCode": "FR",
    }
    logo = card.get("logo_url") if (card.get("logo_url") or "").startswith("http") else None
    if logo:
        cls["programLogo"] = {"sourceUri": {"uri": logo}}
    return cls


def _gw_object(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The Google card, read off the SAME pass.json Apple gets (build_pass_json):
    the member, the progress and the offer say the same thing on both phones."""
    cust, tenant, card = payload["customer"], payload["tenant"], payload["card"]
    pj = build_pass_json(payload)
    sc = pj.get("storeCard", {})
    by_key = {f["key"]: f for grp in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields")
              for f in sc.get(grp, [])}
    class_id, object_id = _gw_ids(tenant["id"], cust["barcode_id"])
    member = by_key.get("member", {}).get("value") or cust.get("name") or "Client"
    points = by_key.get("points")
    progress = by_key.get("stamps") or by_key.get("reward")
    obj: Dict[str, Any] = {
        "id": object_id, "classId": class_id, "state": "INACTIVE" if pj.get("voided") else "ACTIVE",
        "accountId": cust["barcode_id"], "accountName": str(member),
        "barcode": {"type": "QR_CODE", "value": f"{_site_url()}/card/{cust['barcode_id']}",
                    "alternateText": cust["barcode_id"]},
        # Google has no strip either: it gets the same painted banner, meter in.
        "heroImage": {"sourceUri": {"uri": f"{_site_url()}/api/card/{cust['barcode_id']}/wallet-strip.png"
                                           f"?v={int(cust.get('visits') or 0)}-{int(time.time()) // 3600}"
                                           f"-{(card.get('campaign_offer') or {}).get('id') or 0}"}},
        # Apple's back of the pass = Google's details: offer, reward, statut…
        "textModulesData": [{"id": f["key"][:20], "header": str(f["label"])[:40], "body": str(f["value"])[:500]}
                            for f in sc.get("backFields", []) if f["key"] not in ("card", "offer_link")][:10],
        "linksModuleData": {"uris": [{"uri": f["value"], "description": "Voir l'offre en entier"}
                                     for f in sc.get("backFields", []) if f["key"] == "offer_link"]
                            + [{"uri": f"{_site_url()}/card/{cust['barcode_id']}", "description": "Ma carte en ligne"}]
                            + [{"uri": l["uri"], "description": l.get("label") or l["uri"]}
                               for l in (card.get("google_links") or []) if l.get("uri")]},
    }
    if points:
        obj["loyaltyPoints"] = {"label": str(points["label"]).title(), "balance": {"int": int(points["value"] or 0)}}
    if progress:
        obj["secondaryLoyaltyPoints" if points else "loyaltyPoints"] = {
            "label": str(progress["label"]).title(), "balance": {"string": str(progress["value"])}}
    # The campaign stays as a message in the card (Google's banner element).
    campaign = card.get("campaign_offer") if isinstance(card.get("campaign_offer"), dict) else {}
    if (campaign.get("title") or "").strip():
        obj["messages"] = [{"id": "campaign", "header": campaign["title"].strip()[:60],
                            "body": (campaign.get("subtitle") or "").strip()[:300] or campaign["title"].strip()[:300],
                            "messageType": "TEXT"}]
    return obj


def google_save_url(payload: Dict[str, Any]) -> str:
    import jwt
    sa = _gw_sa()
    token = _gw_access_token()
    cls, obj = _gw_class(payload), _gw_object(payload)
    status, _ = _gw_call("GET", f"/loyaltyClass/{cls['id']}", None, token)
    _gw_call("PUT" if status == 200 else "POST", f"/loyaltyClass/{cls['id']}" if status == 200 else "/loyaltyClass", cls, token)
    status, _ = _gw_call("GET", f"/loyaltyObject/{obj['id']}", None, token)
    _gw_call("PUT" if status == 200 else "POST", f"/loyaltyObject/{obj['id']}" if status == 200 else "/loyaltyObject", obj, token)
    # Remembered so every later change is sent to Google (google_sync).
    cust = payload["customer"]
    _db.google_wallet_objects.update_one(
        {"serial": cust["barcode_id"]},
        {"$set": {"object_id": obj["id"], "tenant_id": payload["tenant"]["id"], "updated_at": datetime.now(timezone.utc)},
         "$setOnInsert": {"created_at": datetime.now(timezone.utc)}}, upsert=True)
    claims = {"iss": sa["client_email"], "aud": "google", "typ": "savetowallet", "iat": int(time.time()),
              "origins": [_site_url()], "payload": {"loyaltyObjects": [{"id": obj["id"]}]}}
    return "https://pay.google.com/gp/v/save/" + jwt.encode(claims, sa["private_key"], algorithm="RS256")


# Notifications on Google (user, 2026-10-04): a campaign, a reward unlock and
# the birthday message. Google allows 3 notifying messages per card per 24 h;
# past that the message still lands in the card, silently.
GOOGLE_NOTIFY = {"campaign", "reward", "birthday"}


def _gw_reason(body: Dict[str, Any]) -> str:
    err = (body or {}).get("error") or {}
    return str(err.get("message") or err.get("status") or "")[:160]


def google_sync(serials: Iterable[str], notify: Any = None, update_class: bool = False) -> Dict[str, Any]:
    """Push the current card to Google for every customer who added it.

    Apple pulls a changed pass after a push; Google does not — the server has
    to send the new object itself. Called wherever Apple passes are woken
    (scan, redemption, campaign, card design), so both wallets move together.
    `notify` ("campaign" | "reward" | {"kind": "birthday", "header", "body"})
    adds a TEXT_AND_NOTIFY message; anything
    else updates the card without a notification. `update_class`: the design
    changed (colours, logo, name) — only then is the class sent again."""
    serials = [x for x in dict.fromkeys(serials) if x]
    kind = notify.get("kind") if isinstance(notify, dict) else notify
    out: Dict[str, Any] = {"cards": 0, "synced": 0, "notified": 0, "errors": []}
    if not serials or not google_configured():
        return out
    rows = list(_db.google_wallet_objects.find({"serial": {"$in": serials}}, {"_id": 0}))
    if not rows:
        return out
    out["cards"] = len(rows)
    try:
        token = _gw_access_token()
    except Exception as exc:                       # bad key, Google down: say so, never raise
        msg = f"Connexion à Google impossible : {str(exc)[:120]}"
        _db.google_wallet_objects.update_many({"serial": {"$in": serials}}, {"$set": {
            "last_sync_at": datetime.now(timezone.utc), "last_sync_result": msg}})
        out["errors"].append(msg)
        return out
    classes_done = set()
    for row in rows:
        result = "ok"
        try:
            payload = _card_payload(row["serial"])
            cls = _gw_class(payload)
            if update_class and cls["id"] not in classes_done:   # the design lives on the class
                _gw_call("PUT", f"/loyaltyClass/{cls['id']}", cls, token)
                classes_done.add(cls["id"])
            obj = _gw_object(payload)
            message = None
            if kind == "campaign" and obj.get("messages"):
                message = dict(obj["messages"][0])
                obj["messages"] = []                   # sent below, with the notification
            elif kind == "birthday":
                head = (notify.get("header") or "Joyeux anniversaire !").strip()
                message = {"id": f"birthday-{int(time.time())}", "header": head[:60],
                           "body": ((notify.get("body") or "").strip() or head)[:300]}
            elif kind == "reward":
                reward = payload["card"].get("reward_description") or "Votre récompense"
                message = {"id": f"reward-{int(time.time())}", "header": "Récompense débloquée !",
                           "body": f"{reward} — présentez votre carte en caisse."}
            st, body = _gw_call("PUT", f"/loyaltyObject/{obj['id']}", obj, token)
            if st != 200:
                result = f"HTTP {st} {_gw_reason(body)}".strip()
            else:
                out["synced"] += 1
                if message and kind in GOOGLE_NOTIFY:
                    st2, body2 = _gw_call("POST", f"/loyaltyObject/{obj['id']}/addMessage",
                                          {"message": {**message, "messageType": "TEXT_AND_NOTIFY"}}, token)
                    if st2 == 200:
                        out["notified"] += 1
                        result = "ok · notification envoyée"
                    else:
                        # Over Google's 3-a-day limit (or refused): still put it in the card.
                        _gw_call("POST", f"/loyaltyObject/{obj['id']}/addMessage",
                                 {"message": {**message, "messageType": "TEXT"}}, token)
                        result = f"ok · sans notification ({_gw_reason(body2) or 'HTTP ' + str(st2)})"
        except Exception as exc:                       # one card must not stop the others
            result = f"erreur : {str(exc)[:140]}"
        if not result.startswith("ok"):
            out["errors"].append(result)
        _db.google_wallet_objects.update_one({"serial": row["serial"]}, {"$set": {
            "last_sync_at": datetime.now(timezone.utc), "last_sync_result": result[:200]}})
    out["errors"] = out["errors"][:3]
    return out


@router.get("/api/card/{barcode_id}/google-wallet")
def google_wallet_link(barcode_id: str):
    if not _wallet_in_plan(barcode_id):
        raise HTTPException(status_code=403, detail="Google Wallet n'est pas inclus dans l'offre de ce commerce.")
    if not google_configured():
        raise HTTPException(status_code=503, detail="Google Wallet n'est pas encore configuré")
    try:
        return {"url": google_save_url(_card_payload(barcode_id))}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface Google's message to the merchant
        raise HTTPException(status_code=502, detail=f"Google Wallet: {str(e)[:200]}")
