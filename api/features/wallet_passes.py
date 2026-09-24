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
    GOOGLE_WALLET_SA_B64      base64 of the service-account JSON key

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


def google_configured() -> bool:
    return bool(_env("GOOGLE_WALLET_ISSUER_ID") and _b64_env("GOOGLE_WALLET_SA_B64"))


def _site_url() -> str:
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("PUBLIC_SITE_URL") or "https://app.fidclic.com").rstrip("/")


def _auth_token(serial: str) -> str:
    """Per-pass authenticationToken (≥16 chars per Apple). Derived, so no
    storage and no way to forge one without the secret."""
    secret = (_env("PASS_AUTH_SECRET") or _env("JWT_SECRET") or "fidclic-dev-secret").encode()
    return hmac.new(secret, serial.encode(), hashlib.sha256).hexdigest()[:40]


@router.get("/api/wallet/config")
def wallet_config():
    return {"apple": apple_configured(), "google": google_configured()}


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
                  fallback_rgb: Tuple[int, int, int] = (28, 29, 34)) -> Dict[str, bytes]:
    """Return {'':1x, '@2x':2x, '@3x':3x} PNGs fitted (contain) or filling (cover)
    the given point box. Falls back to a flat brand tile when Pillow is missing
    or the image is unreadable — a pass MUST ship icon.png."""
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
                img = Image.new("RGBA", (w, h), fallback_rgb + (255,))
            elif cover:
                img = base.copy()
                scale = max(w / img.width, h / img.height)
                img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
                left, top = (img.width - w) // 2, (img.height - h) // 2
                img = img.crop((left, top, left + w, top + h))
            else:
                img = base.copy()
                img.thumbnail((w, h), Image.LANCZOS)
                canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2), img)
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

    # ---- the offer, written across the banner ------------------------------
    # This is the band the customer sees on the web card ("Avantage exclusif
    # fidélité · 10 € cagnottés"). Wallet cannot lay out text over an image, so
    # it is drawn here — otherwise the pass looks emptier than the card.
    if title:
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
    return core._serialize_card_payload(cust)


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
        ((card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")) in ("image", "composite")
         and bool(card.get("hero_image_url")))
        # the meter is painted into a strip too, so the same layout applies
        or (card.get("show_meter") is not False and threshold > 0)
    )

    tier_field = {"key": "tier", "label": "STATUT", "value": TIER_LABELS.get(tier, "Bronze")}
    points_field = {"key": "points", "label": (card.get("points_label") or "Points").upper(), "value": points,
                    "changeMessage": "Vous avez maintenant %@ points"}
    show_tier = show("show_tier") and show("show_tier_badge")

    secondary: List[Dict[str, Any]] = [{"key": "member", "label": (card.get("greeting_label") or "Membre").upper(), "value": first_name}]
    if has_banner and show_tier:
        # Statut moves down next to the member name (the header now holds points).
        secondary.append(tier_field)
    # Visits only when there is room: a storeCard row that carries four values
    # squeezes them to the point where the important one (the stamps) is hard
    # to read on a small screen.
    if show("show_visits") and len(secondary) < 2:
        secondary.append({"key": "visits", "label": (card.get("visits_label") or "Visites").upper(), "value": visits})
    if show("show_stamps"):
        secondary.append({"key": "stamps", "label": (card.get("stamps_label") or "Tampons").upper(),
                          "value": f"{stamps} / {threshold}", "changeMessage": "Tampons : %@"})

    # changeMessage is what makes Wallet raise a lock-screen notification when
    # the value changes after an update push. Without it the pass changes in
    # silence — which is why the offer and the reward both carry one.
    auxiliary = [{
        "key": "reward", "label": "PROCHAINE RÉCOMPENSE",
        "value": "Récompense débloquée !" if remaining <= 0 else f"Encore {remaining} tampon{'s' if remaining > 1 else ''} · {reward}",
        "changeMessage": "%@",
    }]
    offer_title, offer_sub = _offer_text(card)
    if offer_title:
        auxiliary.append({"key": "offer", "label": "OFFRE",
                          "value": f"{offer_title} · {offer_sub}" if offer_sub else offer_title,
                          "changeMessage": "%@"})

    back = [
        {"key": "program", "label": "Programme de fidélité", "value": f"{reward} tous les {threshold} tampons."},
        {"key": "card", "label": "Ma carte en ligne", "value": f"{_site_url()}/card/{serial}"},
    ]
    if card.get("tagline"):
        back.insert(0, {"key": "tagline", "label": org, "value": card["tagline"]})
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
            "message": serial, "messageEncoding": "iso-8859-1",
            # The human-readable line under the code is the merchant's call.
            **({"altText": serial} if card.get("show_card_number") is not False else {}),
        }],
        "storeCard": {
            # With a banner: points in the header, nothing over the image.
            # Without: the classic big number, statut in the header.
            "headerFields": ([points_field] if show("show_points") else []) if has_banner
            else ([tier_field] if show_tier else []),
            "primaryFields": [] if has_banner
            else ([points_field] if show("show_points") else []),
            "secondaryFields": secondary[:3],
            "auxiliaryFields": auxiliary[:4],
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

    lat, lng = tenant.get("lat") or tenant.get("latitude"), tenant.get("lng") or tenant.get("longitude")
    if lat and lng and card.get("location_reminder") is not False:
        pass_json["locations"] = [{"latitude": float(lat), "longitude": float(lng), "relevantText": f"Vous êtes près de {org} — pensez à scanner votre carte."}]
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


def build_pkpass(payload: Dict[str, Any]) -> bytes:
    card = payload["card"]
    files: Dict[str, bytes] = {"pass.json": json.dumps(build_pass_json(payload), ensure_ascii=False).encode("utf-8")}

    brand = _rgb(card.get("brand_color")) or (184, 92, 56)
    logo_raw = _fetch_image(card.get("logo_url"))
    for suffix, png in _png_variants(logo_raw, (29, 29), cover=True, fallback_rgb=brand).items():
        files[f"icon{suffix}.png"] = png
    for suffix, png in _png_variants(logo_raw, (160, 50), fallback_rgb=brand).items():
        files[f"logo{suffix}.png"] = png
    # ---- strip: banner photo and/or the progress meter ---------------------
    # A strip is produced when the merchant uploaded a banner OR when the meter
    # is on (show_meter, default true) — in that case the photo is replaced by a
    # quiet brand gradient, which still reads far better than a flat card.
    hero_mode = card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")
    hero_raw = _fetch_image(card.get("hero_image_url")) if hero_mode in ("image", "composite") else None
    with_meter = card.get("show_meter") is not False and int(card.get("reward_threshold") or 0) > 0
    if hero_raw or with_meter:
        cust = payload["customer"]
        threshold = max(1, int(card.get("reward_threshold") or card.get("reward_threshold_stamps") or 10))
        visits_per_stamp = max(1, int(card.get("visits_per_stamp") or 1))
        stamps = int(card.get("stamps_earned") if card.get("stamps_earned") is not None
                     else int(cust.get("visits") or 0) // visits_per_stamp)
        offer_title, offer_sub = _offer_text(card)
        strip3x = compose_strip(hero_raw, derive_colors(card), stamps, threshold, with_meter,
                                title=offer_title, subtitle=offer_sub)
        if strip3x:
            for suffix, png in _strip_variants(strip3x).items():
                files[f"strip{suffix}.png"] = png
        elif hero_raw:                       # no Pillow → ship the photo as-is
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


def notify_passes(serials: Iterable[str]) -> Dict[str, Any]:
    """Tell every device holding these passes to refresh. Best effort — a scan
    must never fail because a push did. Dead tokens are dropped."""
    from services import apns_passes

    serials = [s for s in dict.fromkeys(serials) if s]
    if not serials or not apns_passes.is_configured():
        return {"devices": 0, "sent": 0, "skipped": "not configured" if serials else "no serials"}
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}}, {"push_token": 1, "device_id": 1}))
    if not regs:
        return {"devices": 0, "sent": 0}
    res = apns_passes.push_to_tokens([r.get("push_token") for r in regs])
    for dead in res.get("gone", []):
        try:
            _db.pass_registrations.delete_many({"push_token": dead})
        except Exception:
            pass
    return {"devices": len(regs), "sent": res.get("sent", 0),
            "dropped": len(res.get("gone", [])), "failed": res.get("failed", 0),
            "errors": res.get("errors", [])[:3]}


def notify_customer(customer_id: str) -> Dict[str, Any]:
    cust = _db.customers.find_one({"id": customer_id}, {"barcode_id": 1}) or {}
    return notify_passes([cust.get("barcode_id")]) if cust.get("barcode_id") else {"devices": 0, "sent": 0}


def notify_tenant(tenant_id: str, customer_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Every registered pass of a tenant (or just the given customers) — used
    when the card design or an offer changes."""
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_ids:
        q["id"] = {"$in": list(customer_ids)}
    serials = [c.get("barcode_id") for c in _db.customers.find(q, {"barcode_id": 1})]
    return notify_passes(serials)


@router.get("/api/owner/wallet/stats")
def owner_wallet_stats(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """How the Wallet side of the programme is doing: how many customers carry
    a native pass, on how many devices, and when they were last refreshed."""
    tid = token_data.tenant_id
    serials = [c["barcode_id"] for c in _db.customers.find(
        {"tenant_id": tid, "barcode_id": {"$exists": True}}, {"barcode_id": 1}) if c.get("barcode_id")]
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}},
                                            {"serial": 1, "updated_at": 1, "created_at": 1}))
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
    }


@router.post("/api/owner/wallet/notify")
def owner_notify(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Manual "refresh my customers' passes" — handy after a design change."""
    return notify_tenant(token_data.tenant_id)


@router.get("/api/card/{barcode_id}/apple-wallet.pkpass")
def download_apple_pass(barcode_id: str):
    return _pkpass_response(barcode_id)


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


@router.get("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}")
def serials_for_device(device_id: str, pass_type_id: str, passesUpdatedSince: Optional[str] = None):
    regs = list(_db.pass_registrations.find({"device_id": device_id, "pass_type_id": pass_type_id}))
    if not regs:
        return Response(status_code=204)
    serials = [r["serial"] for r in regs]
    since = None
    if passesUpdatedSince:
        try:
            since = datetime.fromtimestamp(int(passesUpdatedSince), tz=timezone.utc)
        except ValueError:
            since = None
    if since:
        # A pass changed when its customer changed (visit, redemption, tier).
        changed = _db.customers.find({"barcode_id": {"$in": serials}, "updated_at": {"$gt": since}}, {"barcode_id": 1})
        serials = [c["barcode_id"] for c in changed]
        if not serials:
            return Response(status_code=204)
    return {"serialNumbers": serials, "lastUpdated": str(int(time.time()))}


@router.delete("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}/{serial}")
def unregister_device(device_id: str, pass_type_id: str, serial: str,
                      authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    _db.pass_registrations.delete_one({"device_id": device_id, "serial": serial})
    return Response(status_code=200)


@router.get("/api/passes/v1/passes/{pass_type_id}/{serial}")
def latest_pass(pass_type_id: str, serial: str, authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    return _pkpass_response(serial)


@router.post("/api/passes/v1/log")
async def passkit_log(request: Request):
    try:
        body = await request.json()
        for line in (body or {}).get("logs", [])[:20]:
            print(f"[passkit] {line}")
    except Exception:
        pass
    return Response(status_code=200)


# ---------------------------------------------------------------------------
# Google Wallet — loyalty class per tenant, loyalty object per customer,
# "Save to Google Wallet" link = signed JWT. REST via urllib, no SDK.
# ---------------------------------------------------------------------------
_GW_SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
_GW_API = "https://walletobjects.googleapis.com/walletobjects/v1"


def _gw_sa() -> Dict[str, Any]:
    return json.loads(_b64_env("GOOGLE_WALLET_SA_B64").decode())


def _gw_access_token() -> str:
    import jwt  # pyjwt
    sa = _gw_sa()
    now = int(time.time())
    assertion = jwt.encode({"iss": sa["client_email"], "scope": _GW_SCOPE, "aud": sa["token_uri"],
                            "iat": now, "exp": now + 3600}, sa["private_key"], algorithm="RS256")
    data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion}).encode()
    with urllib.request.urlopen(urllib.request.Request(sa["token_uri"], data=data), timeout=10) as r:
        return json.loads(r.read())["access_token"]


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


def google_save_url(payload: Dict[str, Any]) -> str:
    import jwt
    cust, tenant, card = payload["customer"], payload["tenant"], payload["card"]
    issuer = _env("GOOGLE_WALLET_ISSUER_ID")
    sa = _gw_sa()
    token = _gw_access_token()
    org = card.get("card_name") or tenant.get("name") or "FidClic"
    colors = derive_colors(card)
    class_id = f"{issuer}.fidclic_{tenant['id']}".replace("-", "_")
    object_id = f"{issuer}.{cust['barcode_id']}".replace("-", "_")

    logo = card.get("logo_url") if (card.get("logo_url") or "").startswith("http") else None
    cls: Dict[str, Any] = {
        "id": class_id, "issuerName": tenant.get("name") or org, "programName": org,
        "reviewStatus": "UNDER_REVIEW", "hexBackgroundColor": _hex6(colors["backgroundColor"]),
        "countryCode": "FR",
    }
    if logo:
        cls["programLogo"] = {"sourceUri": {"uri": logo}}
    status, _ = _gw_call("GET", f"/loyaltyClass/{class_id}", None, token)
    _gw_call("PUT" if status == 200 else "POST", f"/loyaltyClass/{class_id}" if status == 200 else "/loyaltyClass", cls, token)

    visits = int(cust.get("visits") or 0)
    threshold = max(1, int(card.get("reward_threshold") or 10))
    stamps = min(threshold, int(card.get("stamps_earned") or 0))
    obj: Dict[str, Any] = {
        "id": object_id, "classId": class_id, "state": "ACTIVE",
        "accountId": cust["barcode_id"], "accountName": cust.get("name") or "Client",
        "barcode": {"type": "QR_CODE", "value": cust["barcode_id"], "alternateText": cust["barcode_id"]},
        "loyaltyPoints": {"label": "Tampons", "balance": {"string": f"{stamps} / {threshold}"}},
        "secondaryLoyaltyPoints": {"label": "Statut", "balance": {"string": TIER_LABELS.get((cust.get("tier") or "bronze").lower(), "Bronze")}},
        "textModulesData": [
            {"id": "reward", "header": "Prochaine récompense", "body": card.get("reward_description") or "Une récompense fidélité"},
            {"id": "visits", "header": "Visites", "body": str(visits)},
        ],
        "linksModuleData": {"uris": [{"uri": f"{_site_url()}/card/{cust['barcode_id']}", "description": "Ma carte en ligne"}]},
    }
    if card.get("tagline"):
        obj["textModulesData"].insert(0, {"id": "tagline", "header": org, "body": card["tagline"]})
    status, _ = _gw_call("GET", f"/loyaltyObject/{object_id}", None, token)
    _gw_call("PUT" if status == 200 else "POST", f"/loyaltyObject/{object_id}" if status == 200 else "/loyaltyObject", obj, token)

    claims = {"iss": sa["client_email"], "aud": "google", "typ": "savetowallet", "iat": int(time.time()),
              "origins": [_site_url()], "payload": {"loyaltyObjects": [{"id": object_id}]}}
    return "https://pay.google.com/gp/v/save/" + jwt.encode(claims, sa["private_key"], algorithm="RS256")


@router.get("/api/card/{barcode_id}/google-wallet")
def google_wallet_link(barcode_id: str):
    if not google_configured():
        raise HTTPException(status_code=503, detail="Google Wallet n'est pas encore configuré")
    try:
        return {"url": google_save_url(_card_payload(barcode_id))}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface Google's message to the merchant
        raise HTTPException(status_code=502, detail=f"Google Wallet: {str(e)[:200]}")
