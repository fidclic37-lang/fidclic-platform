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
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from services import card_owner as CO

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from auth import require_role, TokenData

from features import store_cards as _SC  # one card per establishment (multi-store)

router = APIRouter(tags=["wallet-passes"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        _db.pass_registrations.create_index([("device_id", 1), ("serial", 1)], unique=True)
        _db.pass_registrations.create_index([("serial", 1)])
        _db.pass_push_log.create_index([("serial", 1), ("sent_at", -1)])
        _db.pass_push_log.create_index([("device_id", 1), ("checked_at", 1)])
        _db.img_cache.create_index("at", expireAfterSeconds=30 * 24 * 3600)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Push history (user, 2026-10-05) — one row per push per device: Apple's
# answer and receipt number (apns-id), then whether that device came back
# for the pass. « Did it arrive? » is then read, not guessed.
# ---------------------------------------------------------------------------
PUSH_LOG_DAYS = 30
PENDING = timedelta(minutes=2)       # a device usually comes back within seconds


def _short(v: Optional[str], head: int = 6, tail: int = 4) -> Optional[str]:
    """Device ids and push tokens, recognisable but never shown whole."""
    if not v:
        return None
    v = str(v)
    return v if len(v) <= head + tail + 1 else f"{v[:head]}…{v[-tail:]}"


def _log_pushes(regs: List[Dict[str, Any]], results: List[Dict[str, Any]], at: datetime) -> None:
    by_token = {r.get("token"): r for r in results or []}
    rows = []
    for reg in regs:
        res = by_token.get(reg.get("push_token")) or {}
        rows.append({"tenant_id": reg.get("tenant_id"), "serial": reg.get("serial"), "device_id": reg.get("device_id"),
                     "token": _short(reg.get("push_token")), "sent_at": at,
                     "status": res.get("status"), "reason": res.get("reason") or None, "apns_id": res.get("apns_id"),
                     "checked_at": None, "fetched_at": None})
    try:
        if rows:
            _db.pass_push_log.insert_many(rows)
        _db.pass_push_log.delete_many({"sent_at": {"$lt": at - timedelta(days=PUSH_LOG_DAYS)}})
    except Exception as exc:                       # noqa: BLE001 — a log never blocks a push
        print(f"wallet: push history not written ({exc})")


def _push_state(row: Dict[str, Any], now: datetime) -> str:
    """What happened to one push, in the merchant's words."""
    status = row.get("status")
    if status is not None and status != 200:
        return f"refusé par Apple ({row.get('reason') or status})"
    if row.get("fetched_at"):
        return "mis à jour"
    sent = row.get("sent_at")
    sent = sent if not isinstance(sent, datetime) or sent.tzinfo else sent.replace(tzinfo=timezone.utc)
    if isinstance(sent, datetime) and now - sent < PENDING:
        return "en attente"
    if row.get("checked_at"):
        return "demandé, pas téléchargé"
    return "pas récupéré"


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
    # A Vercel preview deployment speaks for itself: a pass added from the
    # preview link must register with, and be updated by, THAT deployment —
    # otherwise production answers its first update with production's design
    # (user, 2026-10-06: test the new card on a preview link before production).
    if os.getenv("VERCEL_ENV") == "preview":
        host = os.getenv("VERCEL_BRANCH_URL") or os.getenv("VERCEL_URL")
        if host:
            return f"https://{host}".rstrip("/")
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
_FETCHED: Dict[str, Tuple[float, bytes]] = {}
_MISSED: Dict[str, float] = {}                    # links that failed, and when


def _fetch_image(src: Optional[str]) -> Optional[bytes]:
    """data: URL or https URL → raw bytes (None on any failure)."""
    if not src:
        return None
    try:
        from services import media as _M
        if _M.is_ref(src):                         # our own picture: straight from the database
            return _M.resolve(src)
        if src.startswith("data:"):
            head, _, data = src.partition(",")
            return base64.b64decode(data) if ";base64" in head else urllib.parse.unquote_to_bytes(data)
        if src.startswith("http"):
            hit = _FETCHED.get(src)
            if hit and time.time() - hit[0] < 600:          # the same photo on every preview keystroke
                return hit[1]
            miss = _MISSED.get(src)
            if miss and time.time() - miss < 300:            # a dead link is not waited for again
                return None
            try:
                with urllib.request.urlopen(src, timeout=4) as r:  # noqa: S310 — merchant-provided image URL
                    data = r.read()
            except Exception:
                _MISSED[src] = time.time()
                while len(_MISSED) > 64:
                    _MISSED.pop(next(iter(_MISSED)))
                return None
            _FETCHED[src] = (time.time(), data)
            while len(_FETCHED) > 16:
                _FETCHED.pop(next(iter(_FETCHED)))
            return data
    except Exception:
        return None
    return None


def _png_variants(raw: Optional[bytes], box: Tuple[int, int], cover: bool = False,
                  fallback_rgb: Tuple[int, int, int] = (28, 29, 34), tight: bool = False) -> Dict[str, bytes]:
    return _cached("png_variants", (raw or b"", box, cover, fallback_rgb, tight),
                   lambda: _make_png_variants(raw, box, cover, fallback_rgb, tight))


def _make_png_variants(raw: Optional[bytes], box: Tuple[int, int], cover: bool = False,
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
            img.save(buf, format="PNG", compress_level=3)
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
# Tampon shapes (user, 2026-10-11: the owner picks the shape, for Android
# and iOS alike) — one choice for every jauge: the iOS 27 text jauge under
# the QR, Google's jauge row, and the jauge painted into the iOS 26 strip and
# Google's banner. No choice yet → the painted bars of before and ● in text.
# ---------------------------------------------------------------------------
STAMP_SHAPES: Dict[str, Tuple[str, str, str]] = {
    # key → (label, filled glyph, empty glyph). U+FE0E keeps ♥ a text glyph:
    # iOS would otherwise draw the red emoji, whatever the card's colours.
    "rond": ("Rond", "●", "○"),
    "etoile": ("Étoile", "★", "☆"),
    "coeur": ("Cœur", "♥︎", "♡"),
    "carre": ("Carré", "■", "□"),
    "losange": ("Losange", "◆", "◇"),
}
JAUGE_MAX = 15          # past 15 tampons a spaced row no longer fits: « 3 / 25 » instead


def stamp_shape(card: Dict[str, Any]) -> Optional[str]:
    """The owner's shape, or None for the default (bars painted, ● in text)."""
    s = card.get("stamp_shape")
    return s if s in STAMP_SHAPES else None


def apply_programme_rules(card: Dict[str, Any]) -> Dict[str, Any]:
    """Points OR tampons on the card, never both (user, 2026-10-12: « dono is
    not good »), decided by the programme itself: a tampons programme shows
    the jauge and no points, every other one its balance and no jauge. The
    old « Afficher le solde de points » / « Indicateur de progression »
    switches no longer decide. Also the reward's defaults: on the card, on
    its back. In place; returns the card."""
    from features.loyalty_card import _programme
    prog = _programme(card)
    stamps = prog == "stamps"
    card["programme"] = prog
    card["show_points"] = not stamps
    card["show_meter"] = stamps
    card["show_stamps"] = stamps
    card["reward_on_card"] = card.get("reward_on_card") is not False
    card["reward_place"] = "front" if card.get("reward_place") == "front" else "back"
    return card


def jauge_text(stamps: int, threshold: int, shape: Optional[str]) -> Optional[str]:
    """« ● ● ● ○ ○ ○ ○ ○ ○ ○ » — the jauge Wallet writes itself, crisp on any
    photo, a space between the tampons (user, 2026-10-12: « symbols k beech
    mein gap do »). None when there is nothing to draw or too many tampons
    for one line."""
    if threshold <= 0 or threshold > JAUGE_MAX:
        return None
    _, full, empty = STAMP_SHAPES.get(shape or "rond", STAMP_SHAPES["rond"])
    done = max(0, min(threshold, int(stamps)))
    return " ".join([full] * done + [empty] * (threshold - done))


def _shape_points(shape: str, cx: float, cy: float, r: float) -> List[Tuple[float, float]]:
    import math
    if shape == "losange":
        return [(cx, cy - r), (cx + r * 0.82, cy), (cx, cy + r), (cx - r * 0.82, cy)]
    if shape == "etoile":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            k = r if i % 2 == 0 else r * 0.46
            pts.append((cx + k * math.cos(a), cy + k * math.sin(a) + r * 0.06))
        return pts
    if shape == "coeur":
        pts = []
        for i in range(48):
            t = 2 * math.pi * i / 48
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((cx + x * r / 16.5, cy + (y + 2) * r / 16.5))
        return pts
    return []


def paint_stamps(d: Any, shape: str, x0: float, x1: float, cy: float, max_size: float, threshold: int,
                 stamps: int, fill: Tuple[int, int, int], empty_fill: Tuple[int, ...],
                 empty_line: Tuple[int, ...], line_w: int = 2) -> None:
    """A row of `threshold` shapes centred between x0 and x1, the first
    `stamps` filled with the brand colour — the painted jauge's shapes."""
    if threshold <= 0:
        return
    gap_k = 0.32
    size = min(max_size, (x1 - x0) / (threshold + gap_k * (threshold - 1)))
    gap = size * gap_k
    total = threshold * size + (threshold - 1) * gap
    left = x0 + ((x1 - x0) - total) / 2
    done = max(0, min(threshold, stamps))
    r = size / 2
    for i in range(threshold):
        cx = left + i * (size + gap) + r
        on = i < done
        kw = {"fill": fill + (255,)} if on else {"fill": empty_fill, "outline": empty_line, "width": line_w}
        if shape == "rond":
            d.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)
        elif shape == "carre":
            k = r * 0.9
            d.rounded_rectangle([cx - k, cy - k, cx + k, cy + k], radius=max(1, round(k * 0.22)), **kw)
        else:
            pts = _shape_points(shape, cx, cy, r)
            if on:
                d.polygon(pts, fill=kw["fill"])
            else:
                d.polygon(pts, fill=empty_fill)
                d.line(pts + [pts[0]], fill=empty_line, width=line_w, joint="curve")


# ---------------------------------------------------------------------------
# Composed images, remembered (the « Aperçu » was slow, user 2026-10-11):
# typing a name rebuilt the same photo, strip and poster on every keystroke.
# Keyed by a hash of every input, so a changed photo or count is new work.
# ---------------------------------------------------------------------------
_IMG_CACHE: Dict[str, Any] = {}
_IMG_CACHE_MAX = 48
_IMG_CACHE_BYTES = 48 * 1024 * 1024      # a serverless instance has memory to spare, not to waste


def _size(v: Any) -> int:
    if isinstance(v, (bytes, str)):
        return len(v)
    if isinstance(v, dict):
        return sum(_size(x) for x in v.values())
    return 64


# The images a pass is made of, shared by every server instance (user,
# 2026-10-12: « preview 20 seconds »): on Vercel each new instance started
# with an empty memory cache and rebuilt the poster, the strip and the logos
# — seconds of image work every time. Built once, kept 30 days in Mongo.
_SHARED_KINDS = {"poster", "poster_variants", "strip", "strip_variants", "png_variants", "name_logo",
                 "round_logo", "template_scaled", "preview_jpeg", "slim_photo"}
_SHARED_MAX = 12 * 1024 * 1024


def _shared_get(kind: str, key: str) -> Any:
    if kind not in _SHARED_KINDS or _db is None:
        return None
    try:
        doc = _db.img_cache.find_one({"_id": key})
    except Exception:
        return None
    if not doc:
        return None
    if "b" in doc:
        return bytes(doc["b"])
    if "s" in doc:
        return str(doc["s"])
    if "d" in doc:
        return {k[1:]: bytes(v) for k, v in doc["d"].items()}         # stored as "k" + key
    return None


def _shared_put(kind: str, key: str, value: Any) -> None:
    if kind not in _SHARED_KINDS or _db is None:
        return
    try:
        if isinstance(value, (bytes, bytearray)):
            body: Dict[str, Any] = {"b": bytes(value)}
        elif isinstance(value, str):
            body = {"s": value}
        elif isinstance(value, dict) and value and all(isinstance(v, (bytes, bytearray)) for v in value.values()):
            if any("." in str(k) or "$" in str(k) for k in value):
                return
            body = {"d": {f"k{k}": bytes(v) for k, v in value.items()}}   # "" / "@2x" / "@3x" → "k" + key
        else:
            return
        if _size(value) > _SHARED_MAX:
            return
        _db.img_cache.update_one({"_id": key}, {"$set": {**body, "kind": kind, "at": datetime.now(timezone.utc)}},
                                 upsert=True)
    except Exception as exc:                               # a cache that fails is just a slower preview
        print(f"wallet: image not shared ({exc})")


def _cached(kind: str, parts: Tuple[Any, ...], make):
    h = hashlib.sha1(kind.encode())
    for p in parts:
        h.update(b"\x00")
        h.update(p if isinstance(p, (bytes, bytearray)) else repr(p).encode())
    key = h.hexdigest()
    if key in _IMG_CACHE:
        _IMG_CACHE[key] = _IMG_CACHE.pop(key)          # most recent last
        return _IMG_CACHE[key]
    out = _shared_get(kind, key)
    if out is None:
        out = make()
        if out is not None:
            _shared_put(kind, key, out)
    if out is not None:
        _IMG_CACHE[key] = out
        while len(_IMG_CACHE) > 1 and (len(_IMG_CACHE) > _IMG_CACHE_MAX
                                       or sum(_size(v) for v in _IMG_CACHE.values()) > _IMG_CACHE_BYTES):
            _IMG_CACHE.pop(next(iter(_IMG_CACHE)))
    return out


# ---------------------------------------------------------------------------
# The strip — the only place a pass can show a progress meter
# ---------------------------------------------------------------------------
# PassKit has no progress element: a pass can show text, images and a barcode,
# nothing else. Every loyalty card you have seen with a filling gauge (Starbucks,
# Loopy-built cards…) draws it INTO the strip image, server-side, per customer.
# That is what this does — so the meter updates with the pass, like the fields.
STRIP_W, STRIP_H = 1125, 432          # Apple's 375 × 144 pt at 3×


def compose_strip(raw: Optional[bytes], theme: Dict[str, str], stamps: int, threshold: int,
                  with_meter: bool, title: str = "", subtitle: str = "", shape: Optional[str] = None) -> Optional[bytes]:
    return _cached("strip", (raw or b"", sorted(theme.items()), stamps, threshold, with_meter, title, subtitle, shape),
                   lambda: _make_strip(raw, theme, stamps, threshold, with_meter, title, subtitle, shape))


def _make_strip(raw: Optional[bytes], theme: Dict[str, str], stamps: int, threshold: int,
                with_meter: bool, title: str = "", subtitle: str = "", shape: Optional[str] = None) -> Optional[bytes]:
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
        buf = io.BytesIO(); img.save(buf, "PNG", compress_level=3); return buf.getvalue()

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
    if shape in STAMP_SHAPES:                  # the owner's tampon shape, not bars
        paint_stamps(d, shape, pad, STRIP_W - pad, y0 + bar_h / 2 - 4, 58, threshold, stamps,
                     brand, empty_fill, empty_line, 3)
        buf = io.BytesIO(); img.save(buf, "PNG", compress_level=3)
        return buf.getvalue()
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

    buf = io.BytesIO(); img.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# iOS 27 « Poster Generic » (WWDC26 « What's new in Wallet », user 2026-10-06)
# ---------------------------------------------------------------------------
# The pass carries `posterGeneric` (iOS 27 draws it: full-bleed artwork,
# primary logo, header, up to 4 primary fields, one footer, the barcode) next
# to `generic`, which iOS 26 and earlier read — Apple's documented pairing.
# With the poster switched off the card is the classic storeCard.
POSTER_W, POSTER_H = 1035, 1515       # 345 × 505 pt at 3×


def compose_poster(raw: Optional[bytes], theme: Dict[str, str], scrim: bool = True) -> Optional[bytes]:
    """The poster's background, as an iOS 27 poster is meant to be: the
    merchant's photo over the whole card (user, 2026-10-11: « jaise poster
    aata hai woh rhe default, pure mein as bg image »), or the brand gradient,
    with a soft scrim at the top so the logo and the header read on any photo.
    Nothing else is painted: the tampons are a jauge Wallet writes in the
    band under the QR (build_pass_json). To frame the photo another way the
    owner uses « Ajuster » (poster_image_url, already the poster's shape).
    PNG at 3×, None without Pillow."""
    return _cached("poster", (raw or b"", sorted(theme.items()), scrim), lambda: _make_poster(raw, theme, scrim))


def _make_poster(raw: Optional[bytes], theme: Dict[str, str], scrim: bool = True) -> Optional[bytes]:
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return None
    surface = _rgb(theme.get("surface_hex")) or (28, 29, 34)
    brand = _rgb(theme.get("brand_hex")) or (184, 92, 56)
    base = None
    if raw:
        try:
            base = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            base = None
    if base is not None:
        # full bleed: the photo covers the card, centred
        scale = max(POSTER_W / base.width, POSTER_H / base.height)
        big = base.resize((max(POSTER_W, round(base.width * scale)), max(POSTER_H, round(base.height * scale))),
                          Image.LANCZOS)
        left, top = (big.width - POSTER_W) // 2, (big.height - POSTER_H) // 2
        img = big.crop((left, top, left + POSTER_W, top + POSTER_H))
    else:
        def mix(a, b, t):
            return tuple(round(x + (y - x) * t) for x, y in zip(a, b))
        img = Image.new("RGB", (POSTER_W, POSTER_H), surface)
        sheen = Image.new("RGB", (POSTER_W, POSTER_H), mix(surface, brand, 0.6))
        diag = Image.linear_gradient("L").resize((POSTER_H * 2, POSTER_H * 2)).rotate(-30, resample=Image.BICUBIC)
        diag = diag.crop(((diag.width - POSTER_W) // 2, (diag.height - POSTER_H) // 2,
                          (diag.width + POSTER_W) // 2, (diag.height + POSTER_H) // 2))
        img = Image.composite(sheen, img, diag.point(lambda v: 255 - v)).filter(ImageFilter.GaussianBlur(18))

    if scrim:     # a Pass Designer design has Apple's own (« Assombrir le haut de l'image »)
        _paint_top_scrim(img, light=raw is None and _lum(surface) > 0.45)
    buf = io.BytesIO(); img.save(buf, "PNG", compress_level=3)
    return buf.getvalue()


def _paint_top_scrim(img: Any, light: bool = False) -> None:
    """A soft shade at the top so the logo and the header read on any photo."""
    from PIL import ImageDraw
    W, H = img.size
    scrim = (255, 255, 255) if light else (0, 0, 0)
    d = ImageDraw.Draw(img, "RGBA")
    band = int(H * 0.30)
    for i in range(band):
        a = int((120 if light else 150) * (1 - i / band) ** 1.4)
        d.line([(0, i), (W, i)], fill=scrim + (a,))


def _poster_variants(png3x: bytes) -> Dict[str, bytes]:
    return _cached("poster_variants", (png3x,), lambda: _make_poster_variants(png3x))


def _make_poster_variants(png3x: bytes) -> Dict[str, bytes]:
    from PIL import Image
    big = Image.open(io.BytesIO(png3x))
    out: Dict[str, bytes] = {"@3x": png3x}            # the master is already the @3x PNG
    for suffix, k in (("", 1), ("@2x", 2)):
        im = big.resize((345 * k, 505 * k), Image.LANCZOS)
        b = io.BytesIO(); im.save(b, "PNG", compress_level=3); out[suffix] = b.getvalue()
    return out


# Featured actions — the two tiles iOS 27 draws under the pass. Apple's list
# (WWDC26, « Defining the metadata of your Wallet Pass »), all 14, in the
# order a loyalty programme reaches for them. One unknown type and Wallet
# hides EVERY tile.
# type → (label in our UI, what it needs)
#   offers / program → FidClic's own page, unless the owner gives a link
#   call             → a phone number (tel://), the shop's by default
#   place            → an Apple Maps Place ID (Plans › Partager › Copier le lien)
#   url              → the owner's https link (the shop's website if none)
FEATURED_TYPES: Dict[str, Tuple[str, str]] = {
    "viewOffersRewards": ("Voir les offres et récompenses", "offers"),
    "membershipBenefits": ("Voir les avantages membres", "program"),
    "bookAppointment": ("Prendre rendez-vous", "url"),
    "order": ("Commander (livraison ou retrait)", "url"),
    "shop": ("Boutique en ligne", "url"),
    "addToBalance": ("Recharger le solde", "url"),
    "call": ("Appeler", "call"),
    "place": ("Itinéraire (Plans)", "place"),
    "viewSchedule": ("Voir le planning", "url"),
    "bookStay": ("Réserver un séjour", "url"),
    "bookCar": ("Louer une voiture", "url"),
    "bookFlight": ("Réserver un vol", "url"),
    "watchTrailer": ("Voir la bande-annonce", "url"),
    "listenToMusic": ("Écouter la musique", "url"),
}
MAX_FEATURED = 2
_HTTPS = re.compile(r"^https://[^/\s]+\.[^/\s]+")


def site_link(website: Any) -> Optional[str]:
    """The shop's website from Établissement, as an https link (or None)."""
    w = (website or "").strip() if isinstance(website, str) else ""
    if not w or " " in w:
        return None
    w = re.sub(r"^http://", "https://", w if "://" in w else f"https://{w}")
    return w[:500] if _HTTPS.match(w) else None


def phone_link(phone: Any) -> Optional[str]:
    """A phone number as Wallet's call action wants it: tel://+33…"""
    p = re.sub(r"[^\d+]", "", str(phone or "").replace("tel://", "").replace("tel:", ""))
    if re.fullmatch(r"0\d{9}", p):                      # French national → +33
        p = "+33" + p[1:]
    return f"tel://{p}" if re.fullmatch(r"\+?\d{6,15}", p) else None


def place_id_of(v: Any) -> Optional[str]:
    """An Apple Maps Place ID, typed as is or inside a Plans share link
    (https://maps.apple.com/place?place-id=I…)."""
    v = str(v or "").strip()
    m = re.search(r"[?&]place-id=([A-Za-z0-9._-]{4,80})", v)
    if m:
        return m.group(1)
    return v if re.fullmatch(r"I[A-Za-z0-9._-]{5,80}", v) else None


def clean_featured(rows: Any, tenant: Optional[Dict[str, Any]] = None, keep_empty: bool = False) -> List[Dict[str, str]]:
    """What the merchant chose, kept only when Wallet will draw it: one of
    Apple's types, at most two, each once, with what that type needs.
    A link-only button with no link (Pass Designer leaves it at "https://")
    opens the shop's website; a call, the shop's phone. When nothing can
    stand in, the button is left off the pass — but `keep_empty` keeps it in
    the settings so the owner can fill it in."""
    tenant = tenant or {}
    out: List[Dict[str, str]] = []
    for r in rows or []:
        r = r or {}
        t = r.get("type")
        if t not in FEATURED_TYPES or any(o["type"] == t for o in out):
            continue
        kind = FEATURED_TYPES[t][1]
        url = str(r.get("url") or "").strip()
        row: Optional[Dict[str, str]] = None
        if kind in ("offers", "program"):
            row = {"type": t, "url": url[:500] if _HTTPS.match(url) else ""}
        elif kind == "url":
            link = url if _HTTPS.match(url) else ("" if keep_empty else (site_link(tenant.get("website")) or ""))
            row = {"type": t, "url": link[:500]} if (link or keep_empty) else None
        elif kind == "call":
            tel = phone_link(r.get("phone") or (url if url.startswith("tel") else ""))
            if not tel and not keep_empty:
                tel = phone_link(tenant.get("phone"))
            row = {"type": t, "phone": tel or ""} if (tel or keep_empty) else None
        elif kind == "place":
            pid = place_id_of(r.get("place") or r.get("placeIdentifier") or url)
            row = {"type": t, "place": pid or ""} if (pid or keep_empty) else None
        if row:
            out.append(row)
        if len(out) == MAX_FEATURED:
            break
    return out


def featured_json(actions: List[Dict[str, str]], serial: str) -> List[Dict[str, str]]:
    """pass.json featuredActions: links go through our counter, a call and a
    place go straight to the phone and to Plans (nothing to count there)."""
    out = []
    for i, a in enumerate(actions):
        ident = f"fa{i + 1}-{a['type']}"
        kind = FEATURED_TYPES[a["type"]][1]
        if kind == "call":
            if a.get("phone"):
                out.append({"identifier": ident, "type": a["type"], "url": a["phone"]})
        elif kind == "place":
            if a.get("place"):
                out.append({"identifier": ident, "type": a["type"], "placeIdentifier": a["place"]})
        else:
            # the owner key rides along, so the tile lands on the owner's card (services/card_owner)
            out.append({"identifier": ident, "type": a["type"],
                        "url": f"{_site_url()}/api/card/{serial}/action/{ident}?k={CO.key_for(serial)}"})
    return out


def featured_target(action: Dict[str, str], serial: str, tenant: Dict[str, Any], owner: bool = False) -> Optional[str]:
    """Where a tile sends the customer. `owner`: the tap carried the card's
    owner key, so the card links carry it on (services/card_owner)."""
    kind = FEATURED_TYPES.get(action.get("type") or "", ("", ""))[1]
    card_url = f"{_site_url()}/card/{serial}"
    if kind == "offers":                        # user, 2026-10-07: offers only, not the whole card
        return action.get("url") or (CO.owner_url(_site_url(), serial, "/offres") if owner else f"{card_url}/offres")
    if kind == "program":
        return action.get("url") or (CO.owner_url(_site_url(), serial, query={"onglet": "programme"}) if owner
                                     else f"{card_url}?onglet=programme")
    if kind == "url":
        return action.get("url") or None
    return None


# ---------------------------------------------------------------------------
# Barcodes — Wallet's eight formats (iOS 27 adds Code 39, Codabar, EAN-13 and
# ITF). What each one can carry decides the message:
#   QR / PDF417 / Aztec → the card's URL (a phone camera opens it: the card
#                         invites, and the till reads the id out of it)
#   Code128 / Code 39   → the card number, FT-XXXXXXXX
#   EAN-13 / ITF / Codabar → digits only: « 20 » + the card's hex id in
#                         decimal (server.barcode_from reads it back)
# ---------------------------------------------------------------------------
BARCODE_FORMATS = {
    "PKBarcodeFormatQR": "QR code", "PKBarcodeFormatPDF417": "PDF417", "PKBarcodeFormatAztec": "Aztec",
    "PKBarcodeFormatCode128": "Code 128", "PKBarcodeFormatCode39": "Code 39",
    "PKBarcodeFormatCodabar": "Codabar", "PKBarcodeFormatEAN13": "EAN-13", "PKBarcodeFormatI2of5": "ITF (2 parmi 5)",
}
NEW_BARCODES = {"PKBarcodeFormatCode39", "PKBarcodeFormatCodabar", "PKBarcodeFormatEAN13", "PKBarcodeFormatI2of5"}
_LINK_CODES = {"PKBarcodeFormatQR", "PKBarcodeFormatPDF417", "PKBarcodeFormatAztec"}
_DIGIT_CODES = {"PKBarcodeFormatCodabar", "PKBarcodeFormatEAN13", "PKBarcodeFormatI2of5"}


def numeric_code(serial: str) -> Optional[str]:
    """FT-C945EB3C → 203376802620 (12 digits). Only the 8-hex ids every real
    card has; None for anything else."""
    m = re.fullmatch(r"FT-([0-9A-F]{8})", (serial or "").upper())
    return f"20{int(m.group(1), 16):010d}" if m else None


def _ean13(d12: str) -> str:
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(d12))
    return d12 + str((10 - s % 10) % 10)


def barcode_message(fmt: str, serial: str) -> Optional[str]:
    if fmt in _LINK_CODES:
        return f"{_site_url()}/card/{serial}"
    if fmt in ("PKBarcodeFormatCode128", "PKBarcodeFormatCode39"):
        return serial.upper()
    digits = numeric_code(serial)
    if not digits:
        return None
    return _ean13(digits) if fmt == "PKBarcodeFormatEAN13" else digits


def build_barcodes(fmt: str, fallback: Optional[str], serial: str, alt: Optional[str]) -> List[Dict[str, str]]:
    """The pass's barcodes: the chosen format, then the fallback iOS 26 and
    earlier read (Wallet shows the first format it supports). A format the
    card cannot carry, or an iOS 27-only one with no fallback, gets a QR."""
    out: List[Dict[str, str]] = []
    for f in (fmt, fallback):
        if f in BARCODE_FORMATS and not any(b["format"] == f for b in out):
            msg = barcode_message(f, serial)
            if msg:
                out.append({"format": f, "message": msg, "messageEncoding": "iso-8859-1",
                            **({"altText": alt} if alt else {})})
    if not out or all(b["format"] in NEW_BARCODES for b in out):
        out.append({"format": "PKBarcodeFormatQR", "message": barcode_message("PKBarcodeFormatQR", serial),
                    "messageEncoding": "iso-8859-1", **({"altText": alt} if alt else {})})
    return out


def _strip_variants(png3x: bytes) -> Dict[str, bytes]:
    """3× master → the @2x and 1× Wallet also asks for."""
    return _cached("strip_variants", (png3x,), lambda: _make_strip_variants(png3x))


def _make_strip_variants(png3x: bytes) -> Dict[str, bytes]:
    try:
        from PIL import Image
    except ImportError:
        return {"@3x": png3x}
    master = Image.open(io.BytesIO(png3x)).convert("RGB")
    out: Dict[str, bytes] = {"@3x": png3x}            # the master is already the @3x PNG
    for suffix, k in (("", 1), ("@2x", 2)):
        img = master.resize((375 * k, 144 * k), Image.LANCZOS)
        buf = io.BytesIO(); img.save(buf, "PNG", compress_level=3)
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
    _attach_auto_news(payload.get("card") or {}, cust)
    if isinstance(payload.get("card"), dict) and isinstance(cust.get("points_news"), dict):
        payload["card"]["points_news"] = cust["points_news"]          # features/referrals._announce
    return payload


CAMPAIGN_OFFER_DAYS = 30


def _attach_auto_news(card: Dict[str, Any], cust: Dict[str, Any]) -> None:
    """The latest Automatisation message, for the pass (features/automations):
    the « Dernier message » field — whose change makes Apple raise the
    lock-screen banner — and the action button's link on the back."""
    try:
        from features import automations as AU
        full = _db.customers.find_one({"id": cust.get("id")}, {"_id": 0, "auto_news": 1}) or {}
        news = AU.latest_for(full)
        if news:
            card["auto_news"] = news
    except Exception as exc:
        print(f"wallet: automation message lookup failed (non-fatal): {exc}")


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
        # live until its own end — an offer's last day, an event's day — or 30
        # days after the send (features/campaign_kinds, redesign 2026-10-10)
        from features import campaign_kinds as _K
        now = _now()
        rows = _db.campaigns.find(
            {"tenant_id": cust.get("tenant_id"), "status": "sent",
             "wallet_offer": True, "recipient_ids": cust.get("id")},
            {"_id": 0, "id": 1, "name": 1, "content": 1, "sent_at": 1, "image_url": 1, "status": 1,
             "kind": 1, "offer": 1, "event": 1, "defi": 1})
        newest, newest_at = None, None
        for c in rows:
            at = _parse_dt(c.get("sent_at"))
            if at and _K.is_live(c, now) and (newest_at is None or at > newest_at):
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


POINTS_NEWS_HOURS = 24


def _points_news(card: Dict[str, Any], points: int) -> Optional[str]:
    """Why the points just moved, when they moved for a reason worth saying
    (a parrainage: « Votre ami Marie est venu… »). Wallet shows the field's
    changeMessage when the balance changes, so the reason rides on it — only
    while the balance is still the one it was written for, and for a day."""
    news = card.get("points_news")
    if not isinstance(news, dict) or not news.get("text"):
        return None
    try:
        if int(news.get("points")) != int(points):
            return None
    except (TypeError, ValueError):
        return None
    at = _parse_dt(news.get("at"))
    if not at or _now() - at > timedelta(hours=POINTS_NEWS_HOURS):
        return None
    return str(news["text"])


@_SC.payload_store
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
    pending = max(0, int(cust.get("rewards_pending") or 0))
    # The card page shows the customer's points balance (1 800 pts). The pass
    # used to show a figure derived from the current cycle, so the same
    # customer read 1 800 on the web and 100 in Wallet. One number, one source.
    points = int(cust.get("points") or 0)
    tier = (cust.get("tier") or "bronze").lower()
    # "Marie" or "Marie Dupont" — the merchant's choice in the advanced panel.
    full_name = (cust.get("name") or "Client").strip()
    first_name = full_name if card.get("use_full_name") else full_name.split(" ")[0]
    reward = card.get("reward_description") or "Une récompense fidélité"

    apply_programme_rules(card)
    stamp_prog = card["programme"] == "stamps"
    # The reward (user, 2026-10-12): the owner's own words, shown or not,
    # under the QR or on the back — never added to the card by itself.
    reward_on = card["reward_on_card"]
    reward_front = reward_on and card["reward_place"] == "front"
    reward_field = {"key": "reward", "label": "RÉCOMPENSE", "value": reward}
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
                    "changeMessage": _points_news(card, points)
                    or (card.get("points_change_message") or "Vous avez maintenant %@ points")}
    show_tier = show("show_tier") and show("show_tier_badge")

    # ---- the front row ------------------------------------------------------
    # With a strip, Wallet puts secondary AND auxiliary fields on ONE line, so
    # every field must be a short value or the row turns into « PROCHAINE
    # RÉCOM… · Encore 9 tampons · Un café gra… » (user's iPhone, 2026-10-04).
    # Three fields at most: who, how far, and the offer (or the statut).
    secondary: List[Dict[str, Any]] = [{"key": "member", "label": (card.get("greeting_label") or "Membre").upper(), "value": first_name}]
    if reward_front:
        secondary.append(reward_field)
    if stamp_prog:
        # changeMessage is what makes Wallet raise a lock-screen notification
        # when the value changes after an update push.
        secondary.append({"key": "stamps", "label": (card.get("stamps_label") or "Tampons").upper(),
                          "value": f"{stamps} / {threshold}",
                          "changeMessage": (card.get("stamps_change_message") or "Tampons : %@")})
    offer_title, offer_sub = _offer_text(card)
    header_fields = _header_fields(card, has_banner, show("show_points"), show_tier,
                                   points_field, tier_field, visits, card.get("visits_label"))
    tier_up = any(f["key"] == "tier" for f in header_fields)      # never twice on one card
    tier_front = False
    if offer_title:
        secondary.append({"key": "offer_title", "label": "OFFRE", "value": offer_title})
    elif show_tier and not tier_up and (has_banner or not show("show_points")):
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
    reward_points = int(card.get("reward_points") or 0)
    back = [
        {"key": "offer", "label": "Offre du moment", "value": offer_full, "changeMessage": "%@"},
        {"key": "next_reward", "label": "Prochaine récompense",
         "value": "Récompense débloquée : présentez votre carte !" if remaining <= 0
         else f"Encore {remaining} tampon{'s' if remaining > 1 else ''} avant : {reward}"},
        # a full card restarts on the next visit; its reward stays valid
        # until handed over (user, 2026-10-09)
        {"key": "pending_rewards", "label": "Récompense à récupérer",
         "value": (f"{pending} récompense{'s' if pending > 1 else ''} à récupérer : {reward}. "
                   "Présentez votre carte en caisse.") if pending else "Aucune pour le moment.",
         "changeMessage": "%@"},
        {"key": "program", "label": "Programme de fidélité",
         "value": f"{reward} tous les {threshold} tampons." if stamp_prog
         else (f"{reward} dès {reward_points} points." if reward_points else f"{reward}.")},
        {"key": "card", "label": "Ma carte en ligne", "value": CO.owner_url(_site_url(), serial)},
    ]
    if not stamp_prog:                    # « Encore N tampons » means nothing on a points card
        back = [f for f in back if f["key"] != "next_reward"]
    else:
        # No points on a tampons card's face (user, 2026-10-12), but the
        # balance stays on its back: a parrainage credits points, and Wallet
        # only rings for a field that was already there — « Votre ami Lina
        # est venu… » rides on this one (_points_news).
        back.insert(next((i + 1 for i, f in enumerate(back) if f["key"] == "pending_rewards"), len(back)),
                    {**points_field, "label": (card.get("points_label") or "Points")})
    if not reward_on:                     # « Non »: no reward on the card, front or back
        back = [f for f in back if f["key"] not in ("next_reward", "program")]
    if show_tier and not tier_front and not tier_up:
        back.insert(1, {"key": "tier_back", "label": "Statut", "value": tier_field["value"]})
    # Tapping a Wallet notification only opens the pass, and the back of a pass
    # holds text only: the link opens the campaign itself — photo, full text —
    # on the web card (?offre= opens it straight away).
    campaign_id = (card.get("campaign_offer") or {}).get("id") if isinstance(card.get("campaign_offer"), dict) else None
    if campaign_id:
        offer_url = CO.owner_url(_site_url(), serial, query={"offre": str(campaign_id)})
        back.insert(1, {"key": "offer_link", "label": "Voir l'offre", "value": offer_url,
                        "attributedValue": f'<a href="{offer_url}">Voir l\'offre en entier</a>'})
    # Automatisations (2026-10-11): ALWAYS present — Wallet only rings for a
    # field that changes, never for one that appears — and its button's link.
    news = card.get("auto_news") if isinstance(card.get("auto_news"), dict) else None
    if news:
        # a parrainage message rides on the points field's banner: shown here, silently
        back.insert(0, {"key": "news", "label": "Dernier message",
                        "value": f"{news.get('title') or ''} — {news.get('body') or ''}".strip(" —").replace("%", ""),
                        **({"changeMessage": "%@"} if news.get("pass", True) else {})})
    else:
        back.insert(0, {"key": "news", "label": "Dernier message", "value": "Aucun message pour le moment."})
    if news and news.get("button_url") and news.get("button_label"):
        back.insert(1, {"key": "news_link", "label": news["button_label"], "value": news["button_url"],
                        "attributedValue": f'<a href="{news["button_url"]}">{news["button_label"]}</a>'})
    # Géolocalisation (features/geo_automation): while this client's automation
    # allows it, the pass carries the shop's locations (below) and its message
    # here, so the card the lock screen opens says it — quietly, no banner.
    geo, geo_rules = None, False
    try:
        from features import geo_automation as GA
        geo_rules = GA.governs(tenant.get("id"))
        if geo_rules:
            full = _db.customers.find_one({"barcode_id": serial}, {"_id": 0}) or {}
            geo = GA.for_pass({**full, "tenant_id": full.get("tenant_id") or tenant.get("id")})
    except Exception as exc:
        print(f"wallet: geolocation lookup failed (non-fatal): {exc}")
    if geo:
        back.insert(1, {"key": "geo_msg", "label": "Près de chez vous", "value": geo["text"]})
        if geo.get("button_url") and geo.get("button_label"):
            back.insert(2, {"key": "geo_link", "label": geo["button_label"], "value": geo["button_url"],
                            "attributedValue": f'<a href="{geo["button_url"]}">{geo["button_label"]}</a>'})
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
        # QR / PDF417 / Aztec carry the card URL, never the bare id: the same
        # code has to work for the till AND for a stranger's camera, which is
        # what makes a customer's own card an invitation. The till pulls the
        # id back out of it (server.barcode_from). The line under the code is
        # the merchant's call.
        "barcodes": build_barcodes(
            {"barcode": "PKBarcodeFormatCode128", "pdf417": "PKBarcodeFormatPDF417",
             "aztec": "PKBarcodeFormatAztec"}.get(card.get("code_type"), card.get("code_type")
                                                  if card.get("code_type") in BARCODE_FORMATS else "PKBarcodeFormatQR"),
            card.get("code_fallback"), serial, serial if card.get("show_card_number") is not False else None),
        "storeCard": {
            # With a banner: points in the header, nothing over the image.
            # Without: the classic big number, statut in the header. The
            # merchant can override which value sits top-right.
            "headerFields": header_fields,
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
    # establishment with a pin — Apple takes up to ten. With an active
    # Géolocalisation automation, IT decides: its message, its establishments,
    # only while its rules hold for this client (none → no locations).
    if geo_rules:
        if geo:
            pass_json["locations"] = [{"latitude": la, "longitude": lo, "maxDistance": geo["radius"],
                                       "relevantText": geo["text"]} for la, lo in geo["spots"][:10]]
    elif card.get("location_reminder") is not False:
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

    # ---- iOS 27: Poster Generic + featured actions ---------------------------
    # The storeCard stays as the card for iOS 26 and earlier — banner strip,
    # logo, colours, exactly as before (user, 2026-10-07: « ios26 mein image
    # strip and logo gaayab… pichla version toh rakho »). Wallet on iOS 27
    # draws `posterGeneric` instead; older iPhones skip the key they don't
    # know and keep the storeCard (checked on iOS 26.6.2).
    if card.get("poster_style") is not False:
        # Apple's sample (user, 2026-10-06): labelled fields — who, and how
        # far. The offer lives on the back, where its changeMessage still
        # raises the notification.
        member_field = next((f for f in secondary if f["key"] == "member"),
                            {"key": "member", "label": "MEMBRE", "value": first_name})
        primary: List[Dict[str, Any]] = [member_field]
        if reward_front:
            primary.append(reward_field)
        # The tampons as a jauge Wallet writes in the band under the QR (user,
        # 2026-10-11): crisp on any photo, never painted over it. The count
        # moves to the label: « TAMPONS · 3/10 » over « ●●●○○○○○○○ ».
        # It takes the progress slot, whichever it was (« Tampons » or the
        # reward): the mockup's MEMBRE | TAMPONS ●●●○○○○○○○ 3/10.
        progress = None
        if stamp_prog:
            jauge = jauge_text(stamps, threshold, stamp_shape(card))
            progress = ({"key": "stamps", "label": f"{(card.get('stamps_label') or 'Tampons').upper()} · {stamps}/{threshold}",
                         "value": jauge, "changeMessage": card.get("stamps_change_message") or "Tampons : %@"} if jauge
                        else next((f for f in secondary if f["key"] == "stamps"), None))
        if progress:
            primary.append(progress)
        elif len(primary) == 1 and show_tier and show("show_points"):
            primary.append(tier_field)
        header = ([points_field] if show("show_points") else ([tier_field] if show_tier else []))
        pass_json["posterGeneric"] = {
            "headerFields": header[:1],
            "primaryFields": primary[:4],
            # Only the logo on top, like Apple's poster: the shop's name is the
            # footer, and the running campaign's offer next to it — a campaign
            # changes the card itself, not just its back (user, 2026-10-07).
            "footerFields": [{"key": "footer", "value": org[:60]}]
            + ([{"key": "offer_front", "label": "OFFRE", "value": offer_title}] if offer_title else []),
            "backFields": back,
        }
        # logoText stays: it is the iOS 26 card's shop name next to the logo
        # (the poster draws its primaryLogo only).
        # The band under the fields: Apple's blur by default, or the owner's
        # colour, as in Pass Designer (user, 2026-10-11: « footer jidhar blur
        # aata hai udhar color daalne ka option »).
        foot = _rgb(card.get("poster_footer_color"))
        if foot:
            pass_json["footerBackgroundColor"] = _css(foot)
    fa = featured_json(clean_featured(card.get("featured_actions"), tenant), serial)
    if fa:
        pass_json["featuredActions"] = fa

    # ---- an Apple Pass Designer template is the design (features/pass_designer)
    try:
        from features import pass_designer as PD
        tpl = PD.load(tenant.get("id") or cust.get("tenant_id"))
    except Exception:
        tpl = None
    if tpl:
        since = cust.get("created_at")
        values = {
            "name": full_name if card.get("use_full_name") is not False else first_name,
            # points OR tampons, by the programme: a field showing the other
            # one is left out (an empty {placeholder} field disappears)
            "first_name": full_name.split(" ")[0], "card": serial, "points": points if not stamp_prog else "",
            "stamps": f"{stamps} / {threshold}" if stamp_prog else "", "tier": tier_field["value"],
            # the reward: the owner's words, only where the owner put it
            "reward": reward if reward_front else "",
            # the running campaign's offer, short, or nothing (a front field
            # holding only {offre} then disappears)
            "offer": offer_title or "", "visits": visits, "shop": org,
            # {jauge}: the tampons as shapes, « ●●●○○○○○○○ »
            "meter": ((jauge_text(stamps, threshold, stamp_shape(card)) or f"{stamps} / {threshold}") if stamp_prog else ""),
            "member_since": since.strftime("%d/%m/%Y") if isinstance(since, datetime) else "",
        }
        pass_json = PD.apply(pass_json, tpl, values)
        # iOS 27 with a design (user, 2026-10-12: « tampons preview mein nhi aa
        # rhe in ios27 »): nothing is painted on a poster since 2026-10-11, so a
        # design without a {jauge} field had no tampons at all. The jauge goes
        # under the QR anyway: a field showing « 3 / 10 » becomes the jauge,
        # else one is added (Wallet takes 4 primary fields).
        pg = pass_json.get("posterGeneric")

        def place(field: Dict[str, Any], at: Optional[int] = None) -> None:
            """A field we add to a design's poster: in the primary row while it
            holds one field, else in the footer row — a third primary field
            squeezed the customer's name into « AK-SHANSH » (user, 2026-10-12)."""
            prim = pg.setdefault("primaryFields", [])
            foot = pg.setdefault("footerFields", [])
            if len(prim) < 2 or (len(foot) >= 2 and len(prim) < 4):
                # (a footer already full — Wallet draws two — keeps the old place)
                prim.insert(len(prim) if at is None else min(at, len(prim)), field)
            elif len(foot) < 2:
                foot.append(field)
        if isinstance(pg, dict) and reward_front:          # « Sous le QR code »: the design gets it too
            front = [f for g in ("headerFields", "primaryFields", "footerFields") for f in pg.get(g) or []]
            if not any(f.get("value") == reward for f in front):
                place(dict(reward_field), 1)
        jauge = jauge_text(stamps, threshold, stamp_shape(card)) if stamp_prog else None
        if isinstance(pg, dict) and jauge:
            front = [f for g in ("headerFields", "primaryFields", "footerFields") for f in pg.get(g) or []]
            if not any(f.get("value") == jauge for f in front):
                prim = pg.setdefault("primaryFields", [])
                label = f"{(card.get('stamps_label') or 'Tampons').upper()} · {stamps}/{threshold}"
                hit = next((f for f in prim if str(f.get("value")) == f"{stamps} / {threshold}"), None)
                if hit:
                    hit.update({"label": label, "value": jauge})
                    hit.setdefault("changeMessage", "Tampons : %@")
                else:
                    place({"key": "jauge", "label": label, "value": jauge,
                           "changeMessage": card.get("stamps_change_message") or "Tampons : %@"})
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


@_SC.payload_store
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
                         title=title, subtitle=sub, shape=stamp_shape(card))


def _stamp_state(payload: Dict[str, Any]) -> Tuple[int, int]:
    """(stamps on the card now, stamps for the reward) — what every meter draws."""
    card, cust = payload["card"], payload["customer"]
    threshold = max(1, int(card.get("reward_threshold") or card.get("reward_threshold_stamps") or 10))
    visits_per_stamp = max(1, int(card.get("visits_per_stamp") or 1))
    stamps = int(card.get("stamps_earned") if card.get("stamps_earned") is not None
                 else int(cust.get("visits") or 0) // visits_per_stamp)
    return stamps, threshold


@_SC.payload_store
def poster_png(payload: Dict[str, Any], scrim: bool = True) -> Optional[bytes]:
    """The iOS 27 poster background (1035×1515): same photo as the strip — the
    live campaign's, else the merchant's banner, else the brand gradient."""
    card = payload["card"]
    raw = None
    if not _campaign_photo(card) and card.get("poster_image_url"):
        raw = _fetch_image(card.get("poster_image_url"))     # the owner's « Ajuster », poster-shaped
    return compose_poster(raw or _hero_raw(card), derive_colors(card), scrim)


def _css_rgb(v: Any) -> Optional[Tuple[int, int, int]]:
    """« rgb(1, 2, 3) » (pass.json) or « #010203 » → (1, 2, 3)."""
    m = re.match(r"\s*rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", str(v or ""))
    if m:
        return tuple(int(x) for x in m.groups())  # type: ignore[return-value]
    return _rgb(v)


# ---------------------------------------------------------------------------
# « Nom stylé » (user, 2026-10-13: « MUSEUM mein M bada »): the name beside the
# logo, letter by letter — each its size, colour and font, symbols included —
# drawn into the logo image, so Apple (iOS 26 and 27) and Google show exactly it.
# card_templates.name_style = {"letters": [{"c": "M", "s": 140, "color": "#D4AF37", "font": "cinzel"}, …]}
# ---------------------------------------------------------------------------
NAME_FONTS: Dict[str, Tuple[str, Optional[int], str]] = {
    "dejavu": ("DejaVuSans-Bold.ttf", None, "Sans gras"),
    "dejavu-light": ("DejaVuSans.ttf", None, "Sans"),
    "cinzel": ("Cinzel.ttf", 700, "Cinzel"),
    "playfair": ("PlayfairDisplay.ttf", 700, "Playfair Display"),
    "montserrat": ("Montserrat.ttf", 700, "Montserrat"),
    "bebas": ("BebasNeue.ttf", None, "Bebas Neue"),
    "oswald": ("Oswald.ttf", 600, "Oswald"),
    "greatvibes": ("GreatVibes.ttf", None, "Great Vibes"),
    "pacifico": ("Pacifico.ttf", None, "Pacifico"),
}
NAME_MAX_LETTERS = 40
NAME_SIZE_MIN, NAME_SIZE_MAX = 50, 200
_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")
_FONT_OBJ: Dict[Tuple[str, int], Any] = {}
_GLYPH: Dict[Tuple[str, str], bool] = {}


def _name_font(key: str, px: int):
    from PIL import ImageFont
    k = (key if key in NAME_FONTS else "dejavu", max(1, int(px)))
    f = _FONT_OBJ.get(k)
    if f is None:
        file, weight, _ = NAME_FONTS[k[0]]
        try:
            f = ImageFont.truetype(os.path.join(_FONTS_DIR, file), k[1])
            if weight:
                try:
                    f.set_variation_by_axes([weight])
                except Exception:
                    pass
        except Exception:
            f = ImageFont.load_default()
        if len(_FONT_OBJ) > 400:
            _FONT_OBJ.clear()
        _FONT_OBJ[k] = f
    return f


def _has_glyph(key: str, ch: str) -> bool:
    """Does this font draw `ch`? (else its empty box would show: DejaVu draws it)"""
    k = (key, ch)
    if k not in _GLYPH:
        try:
            from PIL import Image, ImageDraw
            f = _name_font(key, 40)

            def ink(t: str) -> bytes:
                im = Image.new("L", (80, 80), 0)
                ImageDraw.Draw(im).text((10, 10), t, font=f, fill=255)
                return im.tobytes()
            _GLYPH[k] = ch == " " or ink(ch) != ink("\U0010FFFD")
        except Exception:
            _GLYPH[k] = key == "dejavu"
    return _GLYPH[k]


def clean_name_style(raw: Any) -> Optional[Dict[str, Any]]:
    """The owner's styled name, checked (a French 400 on anything odd). None or
    no letters: the plain name, as before."""
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("letters"), list):
        raise HTTPException(status_code=400, detail="Nom stylé invalide.")
    letters = raw["letters"]
    if len(letters) > NAME_MAX_LETTERS:
        raise HTTPException(status_code=400, detail=f"Nom stylé : {NAME_MAX_LETTERS} caractères au plus.")
    out = []
    for x in letters:
        if not isinstance(x, dict):
            raise HTTPException(status_code=400, detail="Nom stylé invalide.")
        c = str(x.get("c") or "")
        if len(c) != 1 or (not c.isprintable() and c != " "):
            raise HTTPException(status_code=400, detail="Nom stylé : un caractère par case.")
        try:
            size = int(x.get("s") or 100)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Taille de lettre invalide.")
        if not NAME_SIZE_MIN <= size <= NAME_SIZE_MAX:
            raise HTTPException(status_code=400, detail=f"Taille de lettre : {NAME_SIZE_MIN} à {NAME_SIZE_MAX} %.")
        color = x.get("color") or None
        if color and not re.match(r"^#[0-9A-Fa-f]{6}$", str(color)):
            raise HTTPException(status_code=400, detail="Couleur de lettre invalide.")
        fnt = x.get("font") or None
        if fnt and fnt not in NAME_FONTS:
            raise HTTPException(status_code=400, detail="Police inconnue.")
        out.append({"c": c, "s": size, "color": color.upper() if color else None, "font": fnt})
    while out and out[-1]["c"] == " ":
        out.pop()
    while out and out[0]["c"] == " ":
        out.pop(0)
    return {"letters": out} if out else None


def styled_letters(card: Dict[str, Any]) -> Optional[Tuple[Tuple[str, int, Optional[str], Optional[str]], ...]]:
    ns = card.get("name_style") if isinstance(card, dict) else None
    letters = (ns or {}).get("letters") if isinstance(ns, dict) else None
    if not letters:
        return None
    try:
        return tuple((str(x["c"])[:1], int(x.get("s") or 100), x.get("color"), x.get("font"))
                     for x in letters if x.get("c"))
    except Exception:
        return None


def _styled_name_image(letters, color: Tuple[int, int, int], room: int, H: int, k: float):
    """The styled name, as large as it fits in room × H (one line, else up to
    three, never cut): an RGBA image, or None."""
    from PIL import Image, ImageDraw
    glyphs = []
    for c, size, col, fkey in letters:
        key = fkey if fkey in NAME_FONTS else "dejavu"
        if not _has_glyph(key, c):
            key = "dejavu"                       # a symbol the font lacks: drawn, not boxed
        glyphs.append((c, size / 100.0, _rgb(col) if col else tuple(color), key))
    words: List[List[Any]] = [[]]
    for g in glyphs:
        if g[0] == " ":
            words.append([])
        else:
            words[-1].append(g)
    words = [w for w in words if w]
    if not words:
        return None

    def metrics(gl, base):
        f = _name_font(gl[3], round(base * gl[1]))
        a, d = f.getmetrics()
        return f, f.getlength(gl[0]), a, d

    def line_box(line, base):
        """(width, ascent, descent, left overhang) — a script letter's swash
        reaches past its advance: the ink decides the width, never cut."""
        x, asc, desc, left, right = 0.0, 0, 0, 0.0, 0.0
        sp = _name_font("dejavu", round(base)).getlength(" ")
        for i, word in enumerate(line):
            if i:
                x += sp
            for gl in word:
                f, adv, a, d = metrics(gl, base)
                l0, _, r0, _ = f.getbbox(gl[0], anchor="ls")
                left, right = min(left, x + l0), max(right, x + r0, x + adv)
                x, asc, desc = x + adv, max(asc, a), max(desc, d)
        return right - left, asc, desc, -left

    def wrap(base):
        rows, cur = [], []
        for word in words:
            if cur and line_box(cur + [word], base)[0] > room:
                rows.append(cur)
                cur = [word]
            else:
                cur.append(word)
        return rows + ([cur] if cur else [])

    def fits(rows, base):
        boxes = [line_box(r, base) for r in rows]
        return all(b[0] <= room for b in boxes) and sum(b[1] + b[2] for b in boxes) <= H, boxes
    chosen = None
    for pt in range(20, 11, -1):
        ok, boxes = fits([words], pt * k)
        if ok:
            chosen = ([words], pt * k, boxes)
            break
    if chosen is None:
        for pt in range(16, 3, -1):
            rows = wrap(pt * k)
            ok, boxes = fits(rows, pt * k)
            if len(rows) <= 3 and ok:
                chosen = (rows, pt * k, boxes)
                break
    if chosen is None:
        base = 4 * k
        rows = wrap(base)
        chosen = (rows, base, [line_box(r, base) for r in rows])
    rows, base, boxes = chosen
    tw = int(max(b[0] for b in boxes)) + 1
    th = sum(b[1] + b[2] for b in boxes)
    img = Image.new("RGBA", (max(1, min(room, tw)), max(1, min(H, th))), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = 0
    sp = _name_font("dejavu", round(base)).getlength(" ")
    for row, (_, asc, desc, lead) in zip(rows, boxes):
        x, baseline = lead, y + asc
        for i, word in enumerate(row):
            if i:
                x += sp
            for gl in word:
                f, adv, _, _ = metrics(gl, base)
                d.text((x, baseline), gl[0], font=f, fill=tuple(gl[2]) + (255,), anchor="ls")
                x += adv
        y += asc + desc
    return img


def name_logo(raw: Optional[bytes], name: str, color: Tuple[int, int, int],
              box: Tuple[int, int] = (160, 50), letters=None) -> Dict[str, bytes]:
    """The shop's logo with its FULL name beside it, in one image (user,
    2026-10-12: « BLOO J… » on iOS 27 — Wallet cuts its own logoText — and the
    name's colour chosen by the owner, in every Wallet). Apple draws a logo up
    to 160 × 50 pt: the name is written as large as it fits (20 pt down to
    11 pt), on two lines if it must, never cut. {'':1x, '@2x', '@3x'}."""
    if letters:
        return _cached("name_logo", (raw or b"", "styled", letters, color, box),
                       lambda: _make_name_logo(raw, name, color, box, letters))
    return _cached("name_logo", (raw or b"", name, color, box), lambda: _make_name_logo(raw, name, color, box))


def _make_name_logo(raw: Optional[bytes], name: str, color: Tuple[int, int, int],
                    box: Tuple[int, int], letters=None) -> Dict[str, bytes]:
    from PIL import Image, ImageDraw, ImageFont
    fonts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "fonts")

    def font(px: int):
        try:
            return ImageFont.truetype(os.path.join(fonts_dir, "DejaVuSans-Bold.ttf"), px)
        except Exception:
            return ImageFont.load_default()
    base = None
    if raw:
        try:
            base = Image.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            base = None
    name = re.sub(r"\s+", " ", name or "").strip()
    out: Dict[str, bytes] = {}
    for suffix, k0 in (("", 1), ("@2x", 2), ("@3x", 3)):
        W, H = box[0] * k0, box[1] * k0
        k = k0 * box[1] / 50                  # the sizes below are for Apple's 50-pt-high logo
        logo = None
        if base is not None:
            sc = min(H / base.height, (W * 0.4) / base.width)
            logo = base.resize((max(1, round(base.width * sc)), max(1, round(base.height * sc))), Image.LANCZOS)
        lw = logo.width if logo is not None else 0
        gap = round(8 * k) if logo is not None and name else 0
        room = max(10, W - lw - gap)
        if letters:                                    # « Nom stylé »: letter by letter
            gap = round(8 * k) if logo is not None else 0
            room = max(10, W - lw - gap)
            text = _styled_name_image(letters, color, room, H, k)
            cw = min(W, lw + gap + (text.width if text else 0)) if text else max(lw, 1)
            img = Image.new("RGBA", (max(1, cw), H), (0, 0, 0, 0))
            if logo is not None:
                img.paste(logo, (0, (H - logo.height) // 2), logo)
            if text is not None:
                img.paste(text, (lw + gap, (H - text.height) // 2), text)
            b = io.BytesIO()
            img.save(b, "PNG")
            out[suffix] = b.getvalue()
            continue
        draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

        def width(t: str, f) -> int:
            return int(draw.textlength(t, font=f))
        lines, f = [name], font(round(20 * k))

        def lh_of(fnt) -> int:
            a, d = fnt.getmetrics() if hasattr(fnt, "getmetrics") else (12 * k, 3 * k)
            return a + d

        def wrap(fnt) -> List[str]:
            rows, cur = [], ""
            for w in name.split(" "):
                t = f"{cur} {w}".strip()
                if not cur or width(t, fnt) <= room:
                    cur = t
                else:
                    rows.append(cur)
                    cur = w
            return rows + ([cur] if cur else [])
        if name:
            done = False
            for pt in range(20, 11, -1):                       # one line, as large as it fits
                f = font(round(pt * k))
                if width(name, f) <= room:
                    lines, done = [name], True
                    break
            if not done:                                       # up to three lines, never cut
                for pt in range(16, 4, -1):
                    f = font(round(pt * k))
                    rows = wrap(f)
                    if len(rows) <= 3 and all(width(r, f) <= room for r in rows) and lh_of(f) * len(rows) <= H:
                        lines, done = rows, True
                        break
                if not done:
                    f, lines = font(round(5 * k)), wrap(font(round(5 * k)))
        asc, desc = f.getmetrics() if hasattr(f, "getmetrics") else (12 * k, 3 * k)
        lh = asc + desc
        tw = max((width(t, f) for t in lines), default=0) if name else 0
        cw = min(W, lw + gap + tw) if name else max(lw, 1)
        img = Image.new("RGBA", (max(1, cw), H), (0, 0, 0, 0))
        if logo is not None:
            img.paste(logo, (0, (H - logo.height) // 2), logo)
        if name:
            d = ImageDraw.Draw(img)
            top = (H - lh * len(lines)) // 2
            for i, t in enumerate(lines):
                d.text((lw + gap, top + i * lh), t, font=f, fill=tuple(color) + (255,))
        b = io.BytesIO()
        img.save(b, "PNG")
        out[suffix] = b.getvalue()
    return out


def _best_file(files: Dict[str, bytes], base: str) -> Optional[bytes]:
    for suffix in ("@3x", "@2x", ""):
        if f"{base}{suffix}.png" in files:
            return files[f"{base}{suffix}.png"]
    return None


def _name_into_logos(files: Dict[str, bytes], card: Dict[str, Any]) -> None:
    """Apple: the shop's name moves from logoText into the logo images (iOS 26
    logo.png, iOS 27 primaryLogo.png) — written in full, in the owner's colour
    (« Couleur du nom ») or the card's text colour."""
    try:
        pj = json.loads(files["pass.json"])
        letters = styled_letters(card)               # « Nom stylé »: the owner's letters, in its place
        name = "".join(x[0] for x in letters) if letters else str(pj.get("logoText") or "").strip()
        if not name.strip():
            return
        color = _rgb(card.get("logo_text_color")) or _css_rgb(pj.get("foregroundColor")) or (255, 255, 255)
        done = False
        for base in ("logo", "primaryLogo"):
            src = _best_file(files, base)
            if src is None and base == "logo":
                continue
            if src is None:
                continue
            # the image is made from the plain logo (a design's logo may already be a disc)
            for suffix, png in name_logo(src, name, color, letters=letters).items():
                files[f"{base}{suffix}.png"] = png
            done = True
        if done:
            pj.pop("logoText", None)
            files["pass.json"] = json.dumps(pj, ensure_ascii=False).encode("utf-8")
    except Exception as exc:          # a pass without its name image still has logoText
        print(f"wallet: name image failed ({exc})")


def round_logo(raw: Optional[bytes], ring: Optional[str] = None, size: int = 600) -> Optional[bytes]:
    """The shop's logo as a disc (user, 2026-10-08: « logo gol »). Wallet draws
    a logo as it gets it, so the corners are made transparent here.
    - A logo with its own transparency sits on a white disc, with a margin.
    - A full picture is cropped to fill the circle.
    - `ring` (#rrggbb) adds a thin border, readable on a dark photo.
    Drawn 4× and scaled down, so the edge is smooth."""
    if not raw:
        return raw
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return raw
    try:
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
    except Exception:
        return raw
    big = size * 4
    im.thumbnail((big, big), Image.LANCZOS)
    hist = im.getchannel("A").histogram()
    see_through = sum(hist[:250]) > 0.05 * im.width * im.height
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ring_w = int(big * 0.055) if ring else 0
    inner = big - 2 * ring_w
    if see_through:                                   # a drawn logo: on a white disc
        disc = Image.new("RGBA", (inner, inner), (255, 255, 255, 255))
        fit = int(inner * 0.74)
        k = min(fit / im.width, fit / im.height)
        logo = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        disc.alpha_composite(logo, ((inner - logo.width) // 2, (inner - logo.height) // 2))
    else:                                             # a picture: it fills the circle
        k = max(inner / im.width, inner / im.height)
        pic = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        left, top = (pic.width - inner) // 2, (pic.height - inner) // 2
        disc = pic.crop((left, top, left + inner, top + inner))
    mask = Image.new("L", (inner, inner), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, inner - 1, inner - 1), fill=255)
    if ring:
        rgb = _rgb(ring) or (212, 175, 55)
        ImageDraw.Draw(canvas).ellipse((0, 0, big - 1, big - 1), fill=rgb + (255,))
    canvas.paste(disc, (ring_w, ring_w), mask)
    out = io.BytesIO()
    canvas.resize((size, size), Image.LANCZOS).save(out, "PNG", optimize=True)
    return out.getvalue()


def _logo_look(card: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """(round?, ring colour) — the « Logo rond » and « Bordure » toggles."""
    if not card.get("logo_round"):
        return False, None
    ring = (card.get("logo_ring_color") or card.get("brand_color") or "#D4AF37") if card.get("logo_ring") else None
    return True, ring


def _template_files(tpl: Dict[str, Any], card: Dict[str, Any]) -> Dict[str, bytes]:
    """A design's images (Pass Designer template or the editor), plus what
    Wallet needs that it may lack: icon.png and the logo, and the @2x / 1x of
    an image given at @3x (or the 1x of an @2x). Nothing else is added — a
    thumbnail appears only when the owner gave one, as in Pass Designer."""
    from features import pass_designer as PD
    imgs = dict(PD.images(tpl))
    brand = _rgb(card.get("brand_color")) or (184, 92, 56)
    # « Identité » is the one place for the logo and the photo (user,
    # 2026-10-12: « logo and bg image identity and images dono jagah hai,
    # images se htao »): a design draws the card's own, framed as the owner
    # framed it (« Ajuster »). The design's images are only what a card
    # without them falls back on.
    card_logo = _fetch_image(card.get("logo_url"))
    if card_logo:
        imgs = {n: v for n, v in imgs.items() if not re.match(r"^(logo|primaryLogo)(@[23]x)?\.png$", n)}
        for base in ("logo", "primaryLogo"):
            for suffix, png in _png_variants(card_logo, (100, 50), fallback_rgb=brand, tight=True).items():
                imgs[f"{base}{suffix}.png"] = png
    if isinstance((tpl.get("pass") or {}).get("posterGeneric"), dict) and \
            (card.get("poster_image_url") or _hero_raw(card)):
        bg = poster_png({"card": card}, scrim=False)
        if bg:
            imgs = {n: v for n, v in imgs.items() if not re.match(r"^background(@[23]x)?\.png$", n)}
            for suffix, png in _poster_variants(bg).items():
                imgs[f"background{suffix}.png"] = png
    logo_raw = card_logo or PD.best(imgs, "logo") or PD.best(imgs, "primaryLogo")
    try:
        from PIL import Image

        def scaled(data: bytes, k: float) -> bytes:
            def make() -> bytes:
                im = Image.open(io.BytesIO(data))
                b = io.BytesIO()
                im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS).save(b, "PNG", compress_level=3)
                return b.getvalue()
            return _cached("template_scaled", (data, k), make)       # the same design on every preview
        for name in list(imgs):
            if name.endswith("@3x.png"):
                for suffix, k in (("@2x", 2 / 3), ("", 1 / 3)):
                    if name.replace("@3x", suffix) not in imgs:
                        imgs[name.replace("@3x", suffix)] = scaled(imgs[name], k)
        for name in list(imgs):
            if name.endswith("@2x.png") and name.replace("@2x", "") not in imgs:
                imgs[name.replace("@2x", "")] = scaled(imgs[name], 0.5)
    except Exception:
        pass
    if not any(n.startswith("icon") for n in imgs):
        for suffix, png in _png_variants(logo_raw, (29, 29), cover=True, fallback_rgb=brand).items():
            imgs[f"icon{suffix}.png"] = png
    if not any(n.startswith("logo") for n in imgs):
        for suffix, png in _png_variants(logo_raw, (100, 50), fallback_rgb=brand, tight=True).items():
            imgs[f"logo{suffix}.png"] = png
    is_round, ring = _logo_look(card)
    if is_round:                                      # « Logo rond »: both logos, every size
        for base in ("logo", "primaryLogo"):
            src = PD.best(imgs, base)
            if src:
                for suffix, png in _png_variants(round_logo(src, ring), (50, 50), tight=True).items():
                    imgs[f"{base}{suffix}.png"] = png
    return imgs


@_SC.payload_store
def pass_files(payload: Dict[str, Any]) -> Dict[str, bytes]:
    """Every file of the pass but the manifest and signature — what the
    owner's preview shows and what build_pkpass signs."""
    card = payload["card"]
    files: Dict[str, bytes] = {"pass.json": json.dumps(build_pass_json(payload), ensure_ascii=False).encode("utf-8")}

    try:
        from features import pass_designer as PD
        tpl = PD.load((payload.get("tenant") or {}).get("id") or (payload.get("customer") or {}).get("tenant_id"))
    except Exception:
        tpl = None
    if tpl:
        files.update(_template_files(tpl, card))
        if "storeCard" in json.loads(files["pass.json"]):   # iOS 26: the card as before, strip in
            strip3x = strip_png(payload)
            for suffix, png in (_strip_variants(strip3x) if strip3x else {}).items():
                files[f"strip{suffix}.png"] = png
    else:
        brand = _rgb(card.get("brand_color")) or (184, 92, 56)
        icon_raw = _fetch_image(card.get("logo_url"))
        is_round, ring = _logo_look(card)
        logo_raw = round_logo(icon_raw, ring) if is_round else icon_raw
        for suffix, png in _png_variants(icon_raw, (29, 29), cover=True, fallback_rgb=brand).items():
            files[f"icon{suffix}.png"] = png
        # The logo sits left of the shop name: at most 50 pt square-ish, never
        # wider than it needs, so the name is written out in full.
        for suffix, png in _png_variants(logo_raw, (100, 50), fallback_rgb=brand, tight=True).items():
            files[f"logo{suffix}.png"] = png
        # ---- strip: banner photo and/or the progress meter ---------------------
        # A strip is produced when the merchant uploaded a banner OR when the meter
        # is on (show_meter, default true) — in that case the photo is replaced by a
        # quiet brand gradient, which still reads far better than a flat card.
        poster_on = card.get("poster_style") is not False
        strip3x = strip_png(payload)            # the iOS 26 storeCard keeps its strip
        if strip3x:
            for suffix, png in _strip_variants(strip3x).items():
                files[f"strip{suffix}.png"] = png
        else:                                    # no Pillow → ship the photo as-is
            hero_raw = _hero_raw(card)
            if hero_raw:
                for suffix, png in _png_variants(hero_raw, (375, 144), cover=True).items():
                    files[f"strip{suffix}.png"] = png

        # ---- iOS 27 poster: full-bleed background + primary logo ---------------
        if card.get("poster_style") is not False:
            poster3x = poster_png(payload)
            if poster3x:
                for suffix, png in _poster_variants(poster3x).items():
                    files[f"background{suffix}.png"] = png
            for suffix, png in _png_variants(logo_raw, (100, 50), fallback_rgb=brand, tight=True).items():
                files[f"primaryLogo{suffix}.png"] = png
    _name_into_logos(files, card)
    return files


# The pass a customer downloads (user, 2026-10-12: « Add to Apple Wallet takes
# ages »): its photo layers were 3–7 MB of lossless PNG — seconds on a phone
# network before Wallet even opens. Wallet only takes PNG, so the photos keep
# 6 bits per colour (64 levels: no visible change, PSNR ≈ 42 dB) and compress
# to about half. Logos, icons and the name keep every bit.
_PHOTO_LAYERS = ("background", "strip", "thumbnail")


def _slim_photo(png: bytes) -> bytes:
    def make() -> bytes:
        try:
            from PIL import Image, ImageOps
            im = Image.open(io.BytesIO(png))
            if im.mode not in ("RGB", "L"):
                return png                        # a transparent layer stays exact
            out = io.BytesIO()
            ImageOps.posterize(im.convert("RGB"), 6).save(out, "PNG", compress_level=6)
            return out.getvalue() if out.tell() < len(png) else png
        except Exception:
            return png
    return _cached("slim_photo", (png,), make)


def slim_pass_files(files: Dict[str, bytes]) -> Dict[str, bytes]:
    return {n: (_slim_photo(b) if n.endswith(".png") and n.startswith(_PHOTO_LAYERS) else b) for n, b in files.items()}


@_SC.payload_store
def build_pkpass(payload: Dict[str, Any]) -> bytes:
    files = slim_pass_files(pass_files(payload))
    manifest = json.dumps({name: hashlib.sha1(data).hexdigest() for name, data in files.items()}).encode()
    files["manifest.json"] = manifest
    files["signature"] = _sign_manifest(manifest)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


# A signed pass ready before the customer taps « Ajouter à Apple Wallet »
# (user, 2026-10-12: « wallet khulne mein bahut time lagta hai »): the card page
# asks for it as soon as it opens (POST …/wallet-prepare) and the tap gets the
# bytes at once. The key is the pass itself — its fields and its design — so a
# visit or a design change since builds a fresh one.
_PKPASS_MEM: Dict[str, Tuple[str, bytes]] = {}
_PKPASS_TTL = 24 * 3600


def _pkpass_key(payload: Dict[str, Any]) -> str:
    h = hashlib.sha1(json.dumps(build_pass_json(payload), sort_keys=True, default=str).encode())
    h.update(json.dumps(payload.get("card") or {}, sort_keys=True, default=str).encode())
    h.update(str(payload.get("store_id") or "").encode())
    return h.hexdigest()


def _pkpass_cache_get(serial: str, key: str) -> Optional[bytes]:
    hit = _PKPASS_MEM.get(serial)
    if hit and hit[0] == key:
        return hit[1]
    if _db is None:
        return None
    try:
        row = _db.pkpass_cache.find_one({"_id": serial, "key": key})
    except Exception:
        return None
    if row and row.get("data"):
        data = bytes(row["data"])
        _PKPASS_MEM[serial] = (key, data)
        return data
    return None


def _pkpass_cache_put(serial: str, key: str, data: bytes) -> None:
    _PKPASS_MEM[serial] = (key, data)
    while len(_PKPASS_MEM) > 50:
        _PKPASS_MEM.pop(next(iter(_PKPASS_MEM)))
    if _db is None or len(data) > _SHARED_MAX:
        return
    try:
        from bson.binary import Binary
        _db.pkpass_cache.update_one({"_id": serial}, {"$set": {"key": key, "data": Binary(data),
                                                              "at": datetime.now(timezone.utc)}}, upsert=True)
        _db.pkpass_cache.create_index("at", expireAfterSeconds=_PKPASS_TTL)
    except Exception as exc:
        print(f"wallet: pass not cached ({exc})")


def signed_pass(barcode_id: str, payload: Optional[Dict[str, Any]] = None) -> bytes:
    payload = payload or _card_payload(barcode_id)
    key = _pkpass_key(payload)
    data = _pkpass_cache_get(barcode_id, key)
    if data is None:
        data = build_pkpass(payload)
        _pkpass_cache_put(barcode_id, key, data)
    return data


def _pkpass_response(barcode_id: str) -> Response:
    if not apple_configured():
        raise HTTPException(status_code=503, detail="Apple Wallet n'est pas encore configuré")
    data = signed_pass(barcode_id)
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
        res["google"].pop("done", None)
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
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}},
                                            {"push_token": 1, "device_id": 1, "serial": 1, "tenant_id": 1}))
    if not regs:
        return {"devices": 0, "sent": 0}
    sent_at = datetime.now(timezone.utc)
    res = apns_passes.push_to_tokens([r.get("push_token") for r in regs])
    _log_pushes(regs, res.get("results") or [], sent_at)
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
    when the card design or an offer changes. Queued, then worked for a few
    seconds: a save never waits for every card (see queue_refresh)."""
    q: Dict[str, Any] = {"tenant_id": tenant_id}
    if customer_ids:
        q["id"] = {"$in": list(customer_ids)}
    else:                      # one establishment's card changed: only its members' cards
        sid = _SC.store_for(tenant_id)
        if sid:
            q["branch_id"] = sid
    serials = [c.get("barcode_id") for c in _db.customers.find(q, {"barcode_id": 1})]
    queue_refresh(tenant_id, serials, design_changed=not customer_ids)
    return drain_refresh(tenant_id)


# ---------------------------------------------------------------------------
# Wallet refresh queue (2026-10-13). Renaming an establishment answered
# « erreur 504 » (user): the save sent every card to Apple and, one request
# per card, to Google, inside the request — past Vercel's 30 s the request
# was cut. Every card to refresh is now queued per account, then worked for
# REFRESH_BUDGET_S; what is left is worked by the page right after (POST
# /api/owner/wallet/refresh, until nothing is left) and by the daily cron.
# Nothing is dropped: a card leaves the queue only once it was sent.
# ---------------------------------------------------------------------------
REFRESH_BUDGET_S = 6.0
APPLE_CHUNK = 100
# what is left of this request's budget: a save that changes the card twice
# (its name, then its sector's reward) still waits REFRESH_BUDGET_S at most
import contextvars as _cv
_SPENT: "_cv.ContextVar[float]" = _cv.ContextVar("fidclic_wallet_spent", default=0.0)


def queue_refresh(tenant_id: str, serials: Iterable[str], design_changed: bool = False) -> int:
    serials = [s for s in dict.fromkeys(serials) if s]
    if not serials or not tenant_id:
        return 0
    sets: Dict[str, Any] = {"tenant_id": tenant_id, "queued_at": datetime.now(timezone.utc)}
    if design_changed:
        sets["design"] = True
    _db.wallet_refresh.update_one({"tenant_id": tenant_id},
                                  {"$addToSet": {"apple": {"$each": serials}, "google": {"$each": serials}},
                                   "$set": sets}, upsert=True)
    return len(serials)


def refresh_left(tenant_id: str) -> int:
    doc = _db.wallet_refresh.find_one({"tenant_id": tenant_id}, {"_id": 0, "apple": 1, "google": 1}) or {}
    return len(set(doc.get("apple") or []) | set(doc.get("google") or []))


def drain_refresh(tenant_id: str, budget: Optional[float] = None) -> Dict[str, Any]:
    """Send queued cards until `budget` seconds are spent (default: what this
    request has left of REFRESH_BUDGET_S); returns what was done and how many
    cards are still waiting (`left`)."""
    out: Dict[str, Any] = {"devices": 0, "sent": 0, "google": {"cards": 0, "synced": 0, "errors": []}, "left": 0}
    doc = _db.wallet_refresh.find_one({"tenant_id": tenant_id}, {"_id": 0})
    if not doc:
        return out
    shared = budget is None
    if shared:
        budget = REFRESH_BUDGET_S - _SPENT.get()
        if budget <= 0:                            # this request already spent its share
            out["left"] = refresh_left(tenant_id)
            return out
    started = time.monotonic()
    deadline = started + max(0.5, budget)
    apple, google = list(doc.get("apple") or []), list(doc.get("google") or [])
    done_apple: List[str] = []
    for i in range(0, len(apple), APPLE_CHUNK):
        if done_apple and time.monotonic() > deadline:
            break
        chunk = apple[i:i + APPLE_CHUNK]
        try:
            r = _notify_apple(chunk)
            out["devices"] += int(r.get("devices") or 0)
            out["sent"] += int(r.get("sent") or 0)
        except Exception as exc:                   # noqa: BLE001 — a push never breaks the queue
            print(f"wallet refresh: apple failed ({exc})")
        done_apple += chunk
    done_google: List[str] = []
    if google and time.monotonic() < deadline:
        try:
            g = google_sync(google, update_class=bool(doc.get("design")), deadline=deadline)
            done_google = g.pop("done", [])
            out["google"] = g
        except Exception as exc:                   # noqa: BLE001
            out["google"]["errors"].append(str(exc)[:160])
    if done_apple or done_google:
        _db.wallet_refresh.update_one({"tenant_id": tenant_id},
                                      {"$pull": {"apple": {"$in": done_apple}, "google": {"$in": done_google}}})
    left = refresh_left(tenant_id)
    if not left:
        _db.wallet_refresh.delete_one({"tenant_id": tenant_id, "apple": {"$size": 0}, "google": {"$size": 0}})
    out["left"] = left
    if shared:
        _SPENT.set(_SPENT.get() + (time.monotonic() - started))
    return out


def drain_all(budget_each: float = 5.0) -> int:
    """The cron's pass over every account with cards still waiting."""
    n = 0
    for d in list(_db.wallet_refresh.find({}, {"_id": 0, "tenant_id": 1})):
        try:
            drain_refresh(d["tenant_id"], budget_each)
            n += 1
        except Exception as exc:                   # noqa: BLE001
            print(f"wallet refresh: {d.get('tenant_id')} failed ({exc})")
    return n


@router.post("/api/owner/wallet/refresh")
def owner_wallet_refresh(token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    """The page's follow-up after a save: send what is still waiting (a few
    seconds' worth) and say how many cards are left."""
    tid = token_data.tenant_id
    if not _db.wallet_refresh.find_one({"tenant_id": tid}, {"_id": 1}):
        return {"left": 0}
    r = drain_refresh(tid, budget=20.0)
    return {"left": r["left"], "sent": r["sent"], "google_synced": (r.get("google") or {}).get("synced", 0)}


def _iso_or_none(d: Any) -> Optional[str]:
    if not isinstance(d, datetime):
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@router.get("/api/owner/wallet/stats")
def owner_wallet_stats(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """How the Wallet side of the programme is doing: how many customers carry
    a native pass, on how many devices, and when they were last refreshed."""
    tid = token_data.tenant_id
    people = [c for c in _db.customers.find({"tenant_id": tid, "barcode_id": {"$exists": True}},
                                             {"_id": 0, "barcode_id": 1, "name": 1, "created_at": 1})
              if c.get("barcode_id")]
    serials = [c["barcode_id"] for c in people]
    regs = list(_db.pass_registrations.find({"serial": {"$in": serials}},
                                            {"serial": 1, "device_id": 1, "push_token": 1, "pass_type_id": 1,
                                             "updated_at": 1, "created_at": 1, "last_push_at": 1,
                                             "last_push_result": 1, "last_check_at": 1, "last_fetch_at": 1}))
    now = datetime.now(timezone.utc)
    history: Dict[tuple, List[Dict[str, Any]]] = {}
    for row in _db.pass_push_log.find({"serial": {"$in": serials}}, {"_id": 0}).sort("sent_at", -1).limit(500):
        key = (row.get("device_id"), row.get("serial"))
        if len(history.setdefault(key, [])) < 5:
            history[key].append(row)
    names = {c["barcode_id"]: c.get("name") for c in people}
    with_pass = {r.get("serial") for r in regs}
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
        # Per device, the whole chain Apple's guide describes:
        # deviceLibraryIdentifier → pushToken → passTypeIdentifier → serialNumber,
        # then the last pushes with Apple's answer, its apns-id and whether the
        # device came back for the pass (« mis à jour » / « pas récupéré »).
        "devices_detail": [{
            "card": r.get("serial"), "customer": names.get(r.get("serial")),
            "device": _short(r.get("device_id")), "push_token": _short(r.get("push_token")),
            "pass_type": r.get("pass_type_id"),
            "registered_at": _iso_or_none(r.get("created_at")), "registration_updated_at": _iso_or_none(r.get("updated_at")),
            "last_push_at": _iso_or_none(r.get("last_push_at")), "last_push_result": r.get("last_push_result"),
            "last_check_at": _iso_or_none(r.get("last_check_at")), "last_fetch_at": _iso_or_none(r.get("last_fetch_at")),
            "pushes": [{"sent_at": _iso_or_none(h.get("sent_at")), "apple": h.get("status"),
                        "reason": h.get("reason"), "apns_id": h.get("apns_id"),
                        "asked_at": _iso_or_none(h.get("checked_at")), "downloaded_at": _iso_or_none(h.get("fetched_at")),
                        "state": _push_state(h, now)}
                       for h in history.get((r.get("device_id"), r.get("serial")), [])],
        } for r in sorted(regs, key=lambda r: _iso_or_none(r.get("updated_at") or r.get("created_at")) or "", reverse=True)[:30]],
        # iOS 27 tiles under the pass: what is on, and how often it is tapped.
        "featured_actions": {
            "active": [{"type": a["type"], "label": FEATURED_TYPES[a["type"]][0]}
                       for a in clean_featured((_db.card_templates.find_one({"tenant_id": tid}) or {}).get("featured_actions"),
                                               _db.tenants.find_one({"id": tid}, {"_id": 0}) or {})],
            "clicks_30d": {row["_id"]: row["n"] for row in _db.pass_action_clicks.aggregate([
                {"$match": {"tenant_id": tid, "at": {"$gte": now - timedelta(days=30)}}},
                {"$group": {"_id": "$type", "n": {"$sum": 1}}}])},
        },
        # Customers whose card is on no device: never added to Wallet, removed,
        # or added without the device registering (re-add it with internet on).
        "cards_without_device": [{"card": c["barcode_id"], "customer": c.get("name"),
                                  "joined_at": _iso_or_none(c.get("created_at"))}
                                 for c in people if c["barcode_id"] not in with_pass][:30],
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
    # the card editor's unsaved design ({pass, images, options}); images the
    # page already holds come as "saved"
    design: Optional[Dict[str, Any]] = None


# Keys a draft may change on the preview — the designer's own fields, nothing
# that would let a request read another tenant's data.
_PREVIEW_KEYS = {
    "card_name", "surface_color", "surface", "brand_color", "logo_url", "hero_image_url", "hero_mode",
    "tagline", "offer_box_text", "offer_box_subtext", "show_offer_box", "show_points", "show_tier",
    "show_tier_badge", "show_visits", "show_stamps", "show_meter", "code_type", "show_card_number",
    "use_full_name", "greeting_label", "points_label", "visits_label", "stamps_label",
    "reward_threshold_stamps", "reward_description", "points_per_visit", "visits_per_stamp",
    "header_field", "strip_shine", "back_fields", "allow_sharing",
    "poster_style", "featured_actions", "poster_image_url",
    "logo_round", "logo_ring", "logo_ring_color", "google_design", "google_links",
    "poster_footer_color", "stamp_shape", "logo_text_color", "name_style",
    "programme", "points_mode", "reward_points", "reward_on_card", "reward_place",
}


def _data_url(png: Optional[bytes]) -> Optional[str]:
    return "data:image/png;base64," + base64.b64encode(png).decode() if png else None


def _preview_payload(tid: str, body: "PassPreviewIn"):
    """A sample customer's card payload with the page's unsaved fields."""
    import server as core
    visits = max(0, min(int(body.visits or 0), 500))
    # a real-shaped card id (8 hex): every barcode format can carry it, EAN-13
    # and ITF included, so the preview shows the code the customer will get
    sample = {"id": "preview-sample", "tenant_id": tid, "barcode_id": "FT-5A3C91E2",
              "name": "Marie Dupont", "visits": visits, "tier": "bronze", "points": 0}
    payload = core._serialize_card_payload(sample)
    card = payload["card"]
    card.update({k: v for k, v in (body.card or {}).items() if k in _PREVIEW_KEYS and v is not None})
    if (body.card or {}).get("reward_threshold_stamps"):
        card["reward_threshold"] = body.card["reward_threshold_stamps"]
    card.pop("stamps_earned", None)            # recomputed from the sample's visits
    apply_programme_rules(card)                # the draft's programme decides points or tampons
    sample["points"] = visits * int(card.get("points_per_visit") or 10)
    payload["customer"] = {**payload.get("customer", {}), **sample}
    return payload, sample, visits


@router.post("/api/owner/wallet/preview")
def owner_wallet_preview(body: PassPreviewIn,
                         token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    """The Apple Wallet pass exactly as build_pkpass() would make it — the same
    pass.json fields, the same strip and logo images — for a sample customer,
    with the designer's unsaved fields applied. The page draws THIS, so the
    preview cannot drift from the real pass again (user, 2026-10-04: the
    preview still showed the old layout after the pass changed)."""
    tid = token_data.tenant_id
    payload, sample, visits = _preview_payload(tid, body)
    card = payload["card"]

    if body.design is not None:
        from features import pass_designer as PD
        with PD.preview_design(tid, PD.design_from_body(tid, body.design)):
            return _design_preview(payload, sample, visits)

    # the very files the pass ships (user, 2026-10-12: « preview mein change,
    # wallet mein nahi ») — the logo carries the shop's name since then
    files = pass_files(payload)
    pj = json.loads(files["pass.json"])
    strip2x = files.get("strip@2x.png")
    logo2x = files.get("logo@2x.png") or _png_variants(_fetch_image(card.get("logo_url")), (100, 50),
                                                      fallback_rgb=_rgb(card.get("brand_color")) or (184, 92, 56), tight=True).get("@2x")
    logo_w = 50
    try:
        from PIL import Image
        if logo2x:
            logo_w = round(Image.open(io.BytesIO(logo2x)).width / 2)
    except Exception:
        pass
    sc = (pj.get("storeCard") or pj.get("generic") or {})
    bc = (pj.get("barcodes") or [{}])[0]
    return {
        "logoText": pj.get("logoText"),
        "colors": {k: pj.get(k) for k in ("backgroundColor", "foregroundColor", "labelColor")},
        "headerFields": sc.get("headerFields", []), "primaryFields": sc.get("primaryFields", []),
        "secondaryFields": sc.get("secondaryFields", []), "auxiliaryFields": sc.get("auxiliaryFields", []),
        "backFields": sc.get("backFields", []),
        "barcode": {"format": bc.get("format"), "message": bc.get("message"), "altText": bc.get("altText")},
        "strip": (_preview_image("strip", strip2x) if strip2x else None) if "storeCard" in pj else None,
        "logo": _data_url(logo2x), "logo_width": logo_w,
        "sample": {"name": sample["name"], "visits": visits},
        # iOS 27 « poster » — the same fields and background the pass ships
        "poster": _poster_preview(pj, payload, files.get("primaryLogo@2x.png") or logo2x, own=True),
    }


def _preview_image(name: str, png: bytes) -> Optional[str]:
    """A file of the pass for the page: photos as JPEG (a poster PNG is a
    megabyte), artwork with transparency as PNG."""
    if name.split("@")[0].split(".")[0] in ("background", "strip"):
        def jpeg() -> Optional[str]:
            try:
                from PIL import Image
                b = io.BytesIO()
                Image.open(io.BytesIO(png)).convert("RGB").save(b, "JPEG", quality=82)
                return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
            except Exception:
                return None
        out = _cached("preview_jpeg", (png,), jpeg)
        if out:
            return out
    return _data_url(png)


@_SC.payload_store
def _design_preview(payload: Dict[str, Any], sample: Dict[str, Any], visits: int) -> Dict[str, Any]:
    """The card editor's preview: the whole pass.json the customer's iPhone
    gets — every style it carries — and its images (@2x), from the very
    files build_pkpass signs."""
    files = pass_files(payload)
    pj = json.loads(files["pass.json"])
    images: Dict[str, str] = {}
    for base in ("background", "primaryLogo", "logo", "icon", "strip", "thumbnail", "footer"):
        png = files.get(f"{base}@2x.png") or files.get(f"{base}.png")
        if png:
            images[base] = _preview_image(base, png)
    return {
        "pass_json": pj,
        "styles": [st for st in ("posterGeneric", "generic", "storeCard", "coupon", "eventTicket", "boardingPass") if st in pj],
        "images": images,
        "actions": [{"type": a["type"], "label": FEATURED_TYPES[a["type"]][0]}
                    for a in clean_featured(payload["card"].get("featured_actions"), payload.get("tenant"))
                    if any(f["type"] == a["type"] for f in pj.get("featuredActions") or [])],
        "sample": {"name": sample["name"], "visits": visits},
    }


@_SC.payload_store
def _poster_preview(pj: Dict[str, Any], payload: Dict[str, Any], logo2x: Optional[bytes],
                    own: bool = False) -> Optional[Dict[str, Any]]:
    pg = pj.get("posterGeneric")
    if not pg:
        return None
    try:
        from features import pass_designer as PD
        tpl = PD.load((payload.get("tenant") or {}).get("id"))
    except Exception:
        tpl = None
    if tpl:                                   # a Pass Designer template: the card's photo and logo first
        imgs = _template_files(tpl, payload["card"])
        bg2x = imgs.get("background@2x.png") or PD.best(imgs, "background")
        if not own:                           # `own`: the pass's own primaryLogo (with the name)
            logo2x = PD.best(imgs, "primaryLogo") or PD.best(imgs, "logo") or logo2x
    else:
        bg3x = poster_png(payload)
        bg2x = _poster_variants(bg3x).get("@2x") if bg3x else None
    return {"headerFields": pg.get("headerFields", []), "primaryFields": pg.get("primaryFields", []),
            "footerFields": pg.get("footerFields", []), "background": _preview_image("background", bg2x) if bg2x else None,
            "logo": _data_url(logo2x),
            "actions": [{"type": a.get("type"), "label": FEATURED_TYPES.get(a.get("type"), ("", ""))[0]}
                        for a in clean_featured(payload["card"].get("featured_actions"), payload.get("tenant"))]}


@router.post("/api/owner/wallet/notify")
def owner_notify(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Manual "refresh my customers' passes" — handy after a design change."""
    return notify_tenant(token_data.tenant_id)


def _owner_only(barcode_id: str, request: Optional[Request]) -> None:
    """A Wallet pass is the card itself — only its owner's phone (or the
    shop) may download it (server._card_customer, 2026-10-09)."""
    import server as core
    core._card_customer(barcode_id, request)


@router.get("/api/card/{barcode_id}/apple-wallet.pkpass")
def download_apple_pass(barcode_id: str, request: Request = None):
    _owner_only(barcode_id, request)
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
    if not existing:
        # the pass is in an Apple Wallet (again): Clients › Carte reads « Active »
        _db.customers.update_one({"barcode_id": serial}, {"$set": {"wallet_added_at": datetime.now(timezone.utc)}})
        try:                                     # Bienvenue (once per client, features/automations)
            from features import automations as AU
            full = _db.customers.find_one({"barcode_id": serial}, {"_id": 0})
            if full:
                AU.wallet_added(full.get("tenant_id"), full, "apple")
        except Exception as exc:
            print(f"wallet: welcome not sent (non-fatal): {exc}")
    return Response(status_code=200 if existing else 201)


@router.api_route("/api/passes/v1/devices/{device_id}/registrations/{pass_type_id}", methods=["GET", "HEAD"])
def serials_for_device(device_id: str, pass_type_id: str, passesUpdatedSince: Optional[str] = None):
    regs = list(_db.pass_registrations.find({"device_id": device_id, "pass_type_id": pass_type_id}))
    if not regs:
        return Response(status_code=204)
    _db.pass_registrations.update_many({"device_id": device_id}, {"$set": {"last_check_at": datetime.now(timezone.utc)}})
    try:        # push history: this device came back after its pushes
        _db.pass_push_log.update_many({"device_id": device_id, "checked_at": None},
                                      {"$set": {"checked_at": datetime.now(timezone.utc)}})
    except Exception:
        pass
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
    # removed from the last Wallet that had it: the card no longer counts as
    # on the phone until its owner opens it again (services/card_owner.held)
    if not _db.pass_registrations.count_documents({"serial": serial}, limit=1):
        _db.customers.update_one({"barcode_id": serial}, {"$set": {"wallet_removed_at": datetime.now(timezone.utc)}})
    return Response(status_code=200)


# HEAD too: Wallet may ask before it downloads; a 405 there left some
# devices on the pass they already had.
@router.api_route("/api/passes/v1/passes/{pass_type_id}/{serial}", methods=["GET", "HEAD"])
def latest_pass(pass_type_id: str, serial: str, authorization: Optional[str] = Header(default=None)):
    _check_pass_auth(authorization, serial)
    _db.pass_registrations.update_many({"serial": serial}, {"$set": {"last_fetch_at": datetime.now(timezone.utc)}})
    try:        # push history: downloaded by the devices that asked (the GET carries no device id)
        _db.pass_push_log.update_many({"serial": serial, "checked_at": {"$ne": None}, "fetched_at": None},
                                      {"$set": {"fetched_at": datetime.now(timezone.utc)}})
    except Exception:
        pass
    return _pkpass_response(serial)


@router.get("/api/card/{serial}/action/{identifier}")
def featured_action_click(serial: str, identifier: str, k: Optional[str] = None):
    """A tile under the iOS 27 pass was tapped: count it, then send the
    customer where the merchant chose. Public — Wallet opens it like a link,
    with the card's owner key; without it (an old pass, a guessed link) the
    card links stay bare and the card page decides (services/card_owner)."""
    from fastapi.responses import RedirectResponse
    owner = CO.valid(serial, k)
    home = CO.owner_url(_site_url(), serial) if owner else f"{_site_url()}/card/{serial}"
    cust = _db.customers.find_one({"barcode_id": serial}, {"_id": 0, "id": 1, "tenant_id": 1, "branch_id": 1})
    if not cust:
        return RedirectResponse(_site_url(), status_code=302)
    _SC.set_for_customer(cust)
    tpl = _db.card_templates.find_one({"tenant_id": cust.get("tenant_id")}, {"_id": 0, "featured_actions": 1}) or {}
    kind = identifier.split("-", 1)[1] if "-" in identifier else identifier
    tenant = _db.tenants.find_one({"id": cust.get("tenant_id")}, {"_id": 0}) or {}
    action = next((a for a in clean_featured(tpl.get("featured_actions"), tenant) if a["type"] == kind), None)
    if not action:
        return RedirectResponse(home, status_code=302)
    try:
        _db.pass_action_clicks.insert_one({"tenant_id": cust.get("tenant_id"), "customer_id": cust.get("id"),
                                           "type": kind, "at": datetime.now(timezone.utc)})
    except Exception:
        pass
    return RedirectResponse(featured_target(action, serial, tenant, owner) or home, status_code=302)


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
    """The Google class is the card's design: one per establishment that has
    its own card (multi-store), else the account's."""
    issuer = _gw_issuer()
    sid = _SC.store_for(tenant_id)
    cls = f"fidclic_{tenant_id}_{sid}" if sid and _SC.own_card(tenant_id, sid) else f"fidclic_{tenant_id}"
    return (f"{issuer}.{cls}".replace("-", "_"),
            f"{issuer}.{serial}".replace("-", "_"))


# ---------------------------------------------------------------------------
# Google Wallet design (Carte de fidélité › Design de la carte › Google Wallet,
# user 2026-10-08). Google builds its card differently from Apple: one
# background colour (Google picks the text colour), a round logo (or a wide
# one), a hero banner at the foot, up to three rows of values, the barcode,
# and a « Détails » screen with text and links. No tiles: links take their
# place. Stored as card_templates.google_design.
# ---------------------------------------------------------------------------
# what a row can show → (label in our UI, Google fieldPath)
GOOGLE_ROW_FIELDS: Dict[str, Tuple[str, str]] = {
    "name": ("Nom du client", "object.accountName"),
    "card": ("N° de carte", "object.accountId"),
    "points": ("Points", "object.textModulesData['points']"),
    "stamps": ("Tampons", "object.textModulesData['stamps']"),
    "reward": ("Prochaine récompense", "object.textModulesData['next_reward']"),
    "tier": ("Statut", "object.textModulesData['tier']"),
    "offer": ("Offre du moment", "object.textModulesData['offer']"),
    "visits": ("Visites", "object.textModulesData['visits']"),
}
# Google's barcode types → the Apple format whose message they carry
GOOGLE_CODES: Dict[str, Tuple[str, str]] = {
    "QR_CODE": ("QR code", "PKBarcodeFormatQR"), "AZTEC": ("Aztec", "PKBarcodeFormatAztec"),
    "PDF_417": ("PDF417", "PKBarcodeFormatPDF417"), "DATA_MATRIX": ("Data Matrix", "PKBarcodeFormatQR"),
    "CODE_128": ("Code 128", "PKBarcodeFormatCode128"), "CODE_39": ("Code 39", "PKBarcodeFormatCode39"),
    "EAN_13": ("EAN-13", "PKBarcodeFormatEAN13"), "CODABAR": ("Codabar", "PKBarcodeFormatCodabar"),
}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _img_ok(v: Any, limit: int = 3_500_000) -> bool:
    from services import media as _M
    return _M.is_image_value(v) and len(v) <= limit


def clean_google_design(d: Any) -> Dict[str, Any]:
    d = d if isinstance(d, dict) else {}
    out: Dict[str, Any] = {}
    if _HEX.match(str(d.get("bg_color") or "")):
        out["bg_color"] = d["bg_color"]
    if isinstance(d.get("program_name"), str) and d["program_name"].strip():
        out["program_name"] = d["program_name"].strip()[:40]
    out["logo"] = "wide" if d.get("logo") == "wide" and _img_ok(d.get("wide_logo")) else "round"
    if _img_ok(d.get("wide_logo"), 2_000_000):
        out["wide_logo"] = d["wide_logo"]
    out["hero"] = d.get("hero") if d.get("hero") in ("fidclic", "photo", "none") else "fidclic"
    if _img_ok(d.get("hero_image")):
        out["hero_image"] = d["hero_image"]
    if out["hero"] == "photo" and "hero_image" not in out:
        out["hero"] = "fidclic"
    rows = []
    for row in (d.get("rows") or [])[:3]:
        keys = [k for k in (row or [])[:3] if k in GOOGLE_ROW_FIELDS]
        if keys:
            rows.append(keys)
    out["rows"] = rows
    out["barcode"] = d.get("barcode") if d.get("barcode") in GOOGLE_CODES else "QR_CODE"
    out["alt_text"] = "none" if d.get("alt_text") == "none" else "card"
    out["details"] = [{"label": str(r.get("label") or "").strip()[:40], "value": str(r.get("value") or "").strip()[:500]}
                      for r in (d.get("details") or [])[:6]
                      if isinstance(r, dict) and str(r.get("label") or "").strip() and str(r.get("value") or "").strip()]
    n = d.get("notify") if isinstance(d.get("notify"), dict) else {}
    out["notify"] = {k: n.get(k) is not False for k in ("campaign", "reward", "birthday")}
    return out


def _gw_image_url(tenant_id: str, what: str, card: Dict[str, Any]) -> str:
    # the version changes with the image, so Google fetches the new one
    src = {"logo": card.get("logo_url"), "wide": (card.get("google_design") or {}).get("wide_logo"),
           "hero": (card.get("google_design") or {}).get("hero_image"),
           "name": card.get("logo_url")}[what] or ""
    look = f"{bool(card.get('logo_round'))}{bool(card.get('logo_ring'))}{card.get('logo_ring_color') or ''}"
    if what == "name":                        # the name and its colour are in the image
        look += f"{card.get('logo_text_color') or ''}{card.get('_shop_name') or ''}"
        look += json.dumps(card.get("name_style") or {}, sort_keys=True)
    v = hashlib.sha1((src + look).encode()).hexdigest()[:10]
    sid = _SC.store_for(tenant_id)
    own = sid and (_SC.own_card(tenant_id, sid) or (what == "name" and _SC.store_name(tenant_id, sid)))
    store_q = f"&store={sid}" if own else ""
    return f"{_site_url()}/api/wallet/google/{tenant_id}/{what}.png?v={v}{store_q}"


def _gw_callback_url() -> str:
    from features.google_wallet_callbacks import callback_url
    return callback_url()


@_SC.payload_store
def _gw_class(payload: Dict[str, Any]) -> Dict[str, Any]:
    tenant, card = payload["tenant"], payload["card"]
    gd = clean_google_design(card.get("google_design"))
    org = card.get("card_name") or tenant.get("name") or "FidClic"
    class_id, _ = _gw_ids(tenant["id"], payload["customer"]["barcode_id"])
    cls: Dict[str, Any] = {
        "id": class_id, "issuerName": tenant.get("name") or org, "programName": gd.get("program_name") or org,
        "reviewStatus": "UNDER_REVIEW",
        "hexBackgroundColor": gd.get("bg_color") or _hex6(derive_colors(card)["backgroundColor"]),
        "countryCode": "FR",
        # Google tells us when a customer saves or deletes the pass
        # (features/google_wallet_callbacks — Clients › Carte, 2026-10-10)
        "callbackOptions": {"url": _gw_callback_url()},
    }
    # a data: URL logo (most uploads) is served by us: Google needs a public link
    if card.get("logo_url"):
        cls["programLogo"] = {"sourceUri": {"uri": _gw_image_url(tenant["id"], "logo", card)}}
    if gd["logo"] == "wide":
        cls["wideProgramLogo"] = {"sourceUri": {"uri": _gw_image_url(tenant["id"], "wide", card)}}
    elif card.get("logo_text_color") or styled_letters(card):
        # « Couleur du nom » (user, 2026-10-12): Google picks its own text colour,
        # so the logo and the shop's name come as one wide logo, which replaces
        # Google's logo + issuer name; the line under it then says what the card is
        cls["wideProgramLogo"] = {"sourceUri": {"uri": _gw_image_url(
            tenant["id"], "name", {**card, "_shop_name": tenant.get("name") or org})}}
        cls["programName"] = gd.get("program_name") or "Carte de fidélité"
    if gd["rows"]:
        def item(key: str) -> Dict[str, Any]:
            return {"firstValue": {"fields": [{"fieldPath": GOOGLE_ROW_FIELDS[key][1]}]}}
        infos = []
        for keys in gd["rows"]:
            if len(keys) == 1:
                infos.append({"oneItem": {"item": item(keys[0])}})
            elif len(keys) == 2:
                infos.append({"twoItems": {"startItem": item(keys[0]), "endItem": item(keys[1])}})
            else:
                infos.append({"threeItems": {"startItem": item(keys[0]), "middleItem": item(keys[1]),
                                             "endItem": item(keys[2])}})
        cls["classTemplateInfo"] = {"cardTemplateOverride": {"cardRowTemplateInfos": infos}}
    return cls


def _fill_vars(text: str, cust: Dict[str, Any], card: Dict[str, Any]) -> str:
    """{prenom}, {points}… in the owner's own detail rows, like the Apple fields."""
    full = (cust.get("name") or "Client").strip()
    values = {"prenom": full.split(" ")[0], "first_name": full.split(" ")[0], "nom": full, "name": full,
              "carte": cust.get("barcode_id"), "card": cust.get("barcode_id"), "points": cust.get("points") or 0,
              "visites": cust.get("visits") or 0, "visits": cust.get("visits") or 0,
              "commerce": card.get("card_name") or "", "shop": card.get("card_name") or ""}
    return re.sub(r"\{([a-z_]{2,20})\}", lambda m: str(values.get(m.group(1), m.group(0))), text or "")


@_SC.payload_store
def _gw_object(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The Google card, read off the SAME pass.json Apple gets (build_pass_json):
    the member, the progress and the offer say the same thing on both phones."""
    cust, tenant, card = payload["customer"], payload["tenant"], payload["card"]
    pj = build_pass_json(payload)
    sc = (pj.get("storeCard") or pj.get("generic") or {})
    by_key = {f["key"]: f for grp in ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields")
              for f in sc.get(grp, [])}
    class_id, object_id = _gw_ids(tenant["id"], cust["barcode_id"])
    gd = clean_google_design(card.get("google_design"))
    member = by_key.get("member", {}).get("value") or cust.get("name") or "Client"
    points = by_key.get("points")
    progress = by_key.get("stamps") or by_key.get("reward")
    serial = cust["barcode_id"]
    code_fmt = GOOGLE_CODES[gd["barcode"]][1]
    code_value = barcode_message(code_fmt, serial)
    code_type = gd["barcode"] if code_value else "QR_CODE"       # a code the card id cannot fill → QR
    # Apple's back of the pass = Google's details: offer, reward, statut…
    back = [{"id": f["key"][:20], "header": str(f["label"])[:40], "body": str(f["value"])[:500]}
            for f in sc.get("backFields", []) if f["key"] not in ("card", "offer_link", "geo_link")]
    # the values a row of the card can show (classTemplateInfo), as modules
    tier_v = next((f["value"] for f in sc.get("backFields", []) if f["key"] == "tier_back"), None) \
        or by_key.get("tier", {}).get("value")
    extra = {"points": ("Points", cust.get("points") or 0), "tier": ("Statut", tier_v),
             "visits": ("Visites", cust.get("visits") or 0),
             "stamps": (str((progress or {}).get("label") or "Tampons").title(), (progress or {}).get("value"))}
    wanted = {k for row in gd["rows"] for k in row}
    front = [{"id": k, "header": lbl, "body": str(v)} for k, (lbl, v) in extra.items()
             if k in wanted and v not in (None, "")]
    owner_rows = [{"id": f"detail{i}", "header": r["label"], "body": _fill_vars(r["value"], cust, card)}
                  for i, r in enumerate(gd["details"])]
    modules = front + owner_rows + [m for m in back if m["id"] not in {x["id"] for x in front}]
    if gd["hero"] == "none":
        hero = None
    elif gd["hero"] == "photo":
        hero = _gw_image_url(tenant["id"], "hero", card)
    else:   # Google has no strip either: it gets the same painted banner, meter in.
        hero = (f"{_site_url()}/api/card/{serial}/wallet-strip.png"
                f"?v={int(cust.get('visits') or 0)}-{int(time.time()) // 3600}"
                f"-{(card.get('campaign_offer') or {}).get('id') or 0}-{stamp_shape(card) or 'barre'}")
    obj: Dict[str, Any] = {
        "id": object_id, "classId": class_id, "state": "INACTIVE" if pj.get("voided") else "ACTIVE",
        "accountId": serial, "accountName": str(member),
        "barcode": {"type": code_type, "value": code_value or barcode_message("PKBarcodeFormatQR", serial),
                    **({"alternateText": serial} if gd["alt_text"] == "card" else {})},
        **({"heroImage": {"sourceUri": {"uri": hero}}} if hero else {}),
        "textModulesData": modules[:10],
        "linksModuleData": {"uris": [{"uri": f["value"], "description": f["label"]}       # Automatisations' button
                                     for f in sc.get("backFields", []) if f["key"] in ("news_link", "geo_link")]
                            + [{"uri": f["value"], "description": "Voir l'offre en entier"}
                               for f in sc.get("backFields", []) if f["key"] == "offer_link"]
                            + [{"uri": CO.owner_url(_site_url(), cust["barcode_id"]), "description": "Ma carte en ligne"}]
                            + [{"uri": l["uri"], "description": l.get("label") or l["uri"]}
                               for l in (card.get("google_links") or []) if l.get("uri")]},
    }
    # Google « Nearby passes »: the same locations as Apple's (Google writes
    # the lock-screen words itself and decides the distance)
    if pj.get("locations"):
        obj["merchantLocations"] = [{"latitude": l["latitude"], "longitude": l["longitude"]}
                                    for l in pj["locations"][:10]]
    if points:
        obj["loyaltyPoints"] = {"label": str(points["label"]).title(), "balance": {"int": int(points["value"] or 0)}}
    # The jauge rides in the banner (hero « fidclic »). With a photo or no
    # banner it would be gone: then Google's own row carries it, in the
    # owner's shape (user, 2026-10-11: « agar meter nhi h toh add kr do »).
    jauge = None
    if gd["hero"] != "fidclic" and card.get("show_meter") is not False:
        st, th = _stamp_state(payload)
        st = max(0, min(st, th))
        jauge = jauge_text(st, th, stamp_shape(card))
    if jauge:
        label = (card.get("stamps_label") or "Tampons").strip().title()
        obj["secondaryLoyaltyPoints" if points else "loyaltyPoints"] = {
            "label": f"{label} · {st}/{th}", "balance": {"string": jauge}}
    elif progress:
        obj["secondaryLoyaltyPoints" if points else "loyaltyPoints"] = {
            "label": str(progress["label"]).title(), "balance": {"string": str(progress["value"])}}
    # The campaign stays as a message in the card (Google's banner element).
    campaign = card.get("campaign_offer") if isinstance(card.get("campaign_offer"), dict) else {}
    if (campaign.get("title") or "").strip():
        obj["messages"] = [{"id": "campaign", "header": campaign["title"].strip()[:60],
                            "body": (campaign.get("subtitle") or "").strip()[:300] or campaign["title"].strip()[:300],
                            "messageType": "TEXT"}]
    return obj


@_SC.payload_store
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
    return _gw_save_link(obj["id"])


def _gw_save_link(object_id: str) -> str:
    """The « Save to Google Wallet » link of an object Google already has."""
    import jwt
    sa = _gw_sa()
    claims = {"iss": sa["client_email"], "aud": "google", "typ": "savetowallet", "iat": int(time.time()),
              "origins": [_site_url()], "payload": {"loyaltyObjects": [{"id": object_id}]}}
    return "https://pay.google.com/gp/v/save/" + jwt.encode(claims, sa["private_key"], algorithm="RS256")


def google_link_fast(barcode_id: str) -> str:
    """The object exists at Google already (made once, kept in step by
    google_sync on every change): its link needs no call to Google — instant.
    Otherwise the full round (class, object) once."""
    row = _db.google_wallet_objects.find_one({"serial": barcode_id, "object_id": {"$exists": True}}, {"_id": 0})
    if row and row.get("object_id") and row.get("linked_class") == _gw_class_id_for(barcode_id):
        return _gw_save_link(row["object_id"])
    payload = _card_payload(barcode_id)
    url = google_save_url(payload)
    _db.google_wallet_objects.update_one({"serial": barcode_id},
                                         {"$set": {"linked_class": _gw_class_id_for(barcode_id, payload)}})
    return url


def _gw_class_id_for(barcode_id: str, payload: Optional[Dict[str, Any]] = None) -> str:
    """The Google class this card belongs to now (its establishment's)."""
    cust = (payload or {}).get("customer") or _db.customers.find_one({"barcode_id": barcode_id},
                                                                      {"_id": 0, "tenant_id": 1, "branch_id": 1}) or {}
    tid = (payload or {}).get("tenant", {}).get("id") or cust.get("tenant_id")
    sid = (payload or {}).get("store_id") or cust.get("branch_id")
    with _SC.store(tid, sid) if sid else _SC.store(None, None):
        return _gw_ids(tid, barcode_id)[0]


# Notifications on Google (user, 2026-10-04): a campaign, a reward unlock and
# the birthday message. Google allows 3 notifying messages per card per 24 h;
# past that the message still lands in the card, silently.
GOOGLE_NOTIFY = {"campaign", "reward", "birthday", "parrainage", "near_reward", "tier_up", "automation"}


def _gw_reason(body: Dict[str, Any]) -> str:
    err = (body or {}).get("error") or {}
    return str(err.get("message") or err.get("status") or "")[:160]


def google_sync(serials: Iterable[str], notify: Any = None, update_class: bool = False,
                deadline: Optional[float] = None) -> Dict[str, Any]:
    """Push the current card to Google for every customer who added it.

    Apple pulls a changed pass after a push; Google does not — the server has
    to send the new object itself. Called wherever Apple passes are woken
    (scan, redemption, campaign, card design), so both wallets move together.
    `notify` ("campaign" | "reward" | {"kind": "birthday" | "parrainage" | "near_reward", "header", "body"})
    adds a TEXT_AND_NOTIFY message; anything
    else updates the card without a notification. `update_class`: the design
    changed (colours, logo, name) — only then is the class sent again.
    `deadline` (time.monotonic()): stop there; `done` lists the serials
    handled (the refresh queue keeps the others)."""
    serials = [x for x in dict.fromkeys(serials) if x]
    kind = notify.get("kind") if isinstance(notify, dict) else notify
    out: Dict[str, Any] = {"cards": 0, "synced": 0, "notified": 0, "errors": [], "done": list(serials)}
    if not serials or not google_configured():
        return out
    rows = list(_db.google_wallet_objects.find({"serial": {"$in": serials}}, {"_id": 0}))
    if not rows:
        return out
    have = {r["serial"] for r in rows}
    out["done"] = [x for x in serials if x not in have]      # no Google card: nothing to send
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
    worked = 0
    for row in rows:
        if deadline is not None and worked and time.monotonic() > deadline:
            break                                  # at least one card per call, then the clock
        worked += 1
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
            elif kind in ("birthday", "parrainage", "near_reward", "tier_up", "automation"):
                head = (notify.get("header") or {"birthday": "Joyeux anniversaire !", "parrainage": "Parrainage",
                                                 "near_reward": "Vous y êtes presque !",
                                                 "tier_up": "Nouveau palier",
                                                 "automation": "Nouveau message"}[kind]).strip()
                message = {"id": f"{kind}-{int(time.time())}", "header": head[:60],
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
                # « Notifications » in the Google design: off → the message
                # still lands in the card, without the buzz
                allowed = clean_google_design(payload["card"].get("google_design"))["notify"].get(kind, True)
                if message and kind in GOOGLE_NOTIFY and not allowed:
                    _gw_call("POST", f"/loyaltyObject/{obj['id']}/addMessage",
                             {"message": {**message, "messageType": "TEXT"}}, token)
                    result = "ok · message sans notification (désactivée)"
                elif message and kind in GOOGLE_NOTIFY:
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
        out["done"].append(row["serial"])
    out["errors"] = out["errors"][:3]
    return out


def _gw_image(card: Dict[str, Any], what: str) -> Optional[bytes]:
    """The images Google fetches: the logo (always a disc — Google draws it
    round; ours keeps the white disc and the ring of « Logo rond »), the wide
    logo, the hero banner (1032 × 336)."""
    gd = card.get("google_design") or {}
    if what == "logo":
        _, ring = _logo_look(card)
        return round_logo(_fetch_image(card.get("logo_url")), ring, size=660)
    if what == "wide":
        return _png_variants(_fetch_image(gd.get("wide_logo")), (640, 200), tight=True).get("@2x")
    if what == "hero":
        return _png_variants(_fetch_image(gd.get("hero_image")), (516, 168), cover=True).get("@2x")
    if what == "name":
        _, ring = _logo_look(card)
        color = _rgb(card.get("logo_text_color")) or (255, 255, 255)
        return name_logo(round_logo(_fetch_image(card.get("logo_url")), ring, size=400), card.get("_shop_name") or "",
                         color, box=(640, 200), letters=styled_letters(card)).get("@2x")
    return None


@router.get("/api/wallet/name-fonts/{key}.ttf")
def name_font_file(key: str):
    """The fonts of « Nom stylé », for the editor to show each letter as the
    card will (public, OFL-licensed files from assets/fonts)."""
    if key not in NAME_FONTS:
        raise HTTPException(status_code=404, detail="Police inconnue")
    with open(os.path.join(_FONTS_DIR, NAME_FONTS[key][0]), "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type="font/ttf", headers={"Cache-Control": "public, max-age=2592000, immutable"})


@router.get("/api/wallet/google/{tenant_id}/{what}.png")
def google_image(tenant_id: str, what: str, store: Optional[str] = None):
    """Public: Google's servers fetch these when they draw the card
    (`store`: an establishment with its own card)."""
    if what not in ("logo", "wide", "hero", "name"):
        raise HTTPException(status_code=404, detail="Image inconnue")
    with _SC.store(tenant_id, store):
        tpl = _db.card_templates.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
    card = {**(tpl.get("brand_fields") or {}), **tpl}
    if what == "name":
        t = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1}) or {}
        card["_shop_name"] = _SC.store_name(tenant_id, store) or t.get("name") or card.get("card_name") or ""
    png = _gw_image(card, what)
    if not png:
        raise HTTPException(status_code=404, detail="Image absente")
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/api/owner/wallet/google-preview")
def owner_google_preview(body: PassPreviewIn,
                         token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    """The Google Wallet card as google_save_url() would send it, for a sample
    customer, with the page's unsaved fields (google_design…): the class, the
    object, and their images as data URLs (Google's links point at the site)."""
    payload, sample, visits = _preview_payload(token_data.tenant_id, body)
    card = payload["card"]
    cls, obj = _gw_class(payload), _gw_object(payload)
    gd = clean_google_design(card.get("google_design"))
    hero = None
    if gd["hero"] == "photo":
        hero = _gw_image(card, "hero")
    elif gd["hero"] == "fidclic":
        hero = strip_png(payload)
    return {
        "class": cls, "object": obj,
        "images": {"logo": _data_url(_gw_image(card, "logo")),
                   "wide": _data_url(_gw_image(card, "wide")) if gd["logo"] == "wide" else (
                       # « Couleur du nom »: the logo + the name, as Google gets it
                       _data_url(_gw_image({**card, "_shop_name": (payload.get("tenant") or {}).get("name")
                                            or card.get("card_name") or ""}, "name"))
                       if card.get("logo_text_color") or styled_letters(card) else None),
                   "hero": _preview_image("strip", hero) if hero else None},
        "row_fields": {k: v[0] for k, v in GOOGLE_ROW_FIELDS.items()},
        "codes": {k: v[0] for k, v in GOOGLE_CODES.items()},
        "configured": google_configured(),
        "sample": {"name": sample["name"], "visits": visits},
    }


@router.post("/api/card/{barcode_id}/wallet-prepare")
def wallet_prepare(barcode_id: str, request: Request = None):
    """Asked by the card page as it opens: the signed Apple pass is built and
    kept, the Google link is made — so « Ajouter à … » opens the Wallet at once."""
    _owner_only(barcode_id, request)
    out: Dict[str, Any] = {"apple": False, "google_url": None}
    if not _wallet_in_plan(barcode_id):
        return out
    payload = None
    if apple_configured():
        try:
            payload = _card_payload(barcode_id)
            signed_pass(barcode_id, payload)
            out["apple"] = True
        except Exception as exc:
            print(f"wallet prepare: apple ({exc})")
    if google_configured():
        try:
            out["google_url"] = google_link_fast(barcode_id)
        except Exception as exc:
            print(f"wallet prepare: google ({exc})")
    return out


@router.get("/api/card/{barcode_id}/google-wallet")
def google_wallet_link(barcode_id: str, request: Request = None):
    _owner_only(barcode_id, request)
    if not _wallet_in_plan(barcode_id):
        raise HTTPException(status_code=403, detail="Google Wallet n'est pas inclus dans l'offre de ce commerce.")
    if not google_configured():
        raise HTTPException(status_code=503, detail="Google Wallet n'est pas encore configuré")
    try:
        return {"url": google_link_fast(barcode_id)}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — surface Google's message to the merchant
        raise HTTPException(status_code=502, detail=f"Google Wallet: {str(e)[:200]}")
