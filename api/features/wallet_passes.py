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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

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
    return {"backgroundColor": _css(bg), "foregroundColor": _css(ink), "labelColor": _css(label)}  # type: ignore[arg-type]


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
# pass.json
# ---------------------------------------------------------------------------
TIER_LABELS = {"bronze": "Bronze", "silver": "Argent", "gold": "Or", "vip": "VIP"}


def _card_payload(barcode_id: str) -> Dict[str, Any]:
    import server as core
    cust = _db.customers.find_one({"barcode_id": barcode_id})
    if not cust:
        raise HTTPException(status_code=404, detail="Card not found")
    return core._serialize_card_payload(cust)


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
    points_per_visit = int(card.get("points_per_visit") or 10)
    points = min(visits * points_per_visit, threshold * visits_per_stamp * points_per_visit)
    tier = (cust.get("tier") or "bronze").lower()
    first_name = (cust.get("name") or "Client").split(" ")[0]
    reward = card.get("reward_description") or "Une récompense fidélité"

    show = lambda k, default=True: card.get(k) is not False if card.get(k) is not None else default  # noqa: E731

    # A banner (strip) image changes the layout. In a storeCard, Wallet draws
    # the primary fields ON TOP of the strip — so a merchant who uploaded a
    # photo would get their own artwork covered by a big number. With a banner
    # we therefore leave primaryFields empty (clean image, edge to edge) and
    # move the points up to the header, exactly like Apple's own sample passes.
    has_banner = (card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")) in ("image", "composite") \
        and bool(card.get("hero_image_url"))

    tier_field = {"key": "tier", "label": "STATUT", "value": TIER_LABELS.get(tier, "Bronze")}
    points_field = {"key": "points", "label": (card.get("points_label") or "Points").upper(), "value": points}
    show_tier = show("show_tier") and show("show_tier_badge")

    secondary: List[Dict[str, Any]] = [{"key": "member", "label": (card.get("greeting_label") or "Membre").upper(), "value": first_name}]
    if has_banner and show_tier:
        # Statut moves down next to the member name (the header now holds points).
        secondary.append(tier_field)
    if show("show_visits"):
        secondary.append({"key": "visits", "label": (card.get("visits_label") or "Visites").upper(), "value": visits})
    if show("show_stamps"):
        secondary.append({"key": "stamps", "label": (card.get("stamps_label") or "Tampons").upper(), "value": f"{stamps} / {threshold}"})

    auxiliary = [{
        "key": "reward", "label": "PROCHAINE RÉCOMPENSE",
        "value": "Récompense débloquée !" if remaining <= 0 else f"Encore {remaining} tampon{'s' if remaining > 1 else ''} · {reward}",
    }]
    if card.get("show_offer_box") is not False and card.get("offer_box_text"):
        auxiliary.append({"key": "offer", "label": "OFFRE", "value": card["offer_box_text"]})

    back = [
        {"key": "program", "label": "Programme de fidélité", "value": f"{reward} tous les {threshold} tampons."},
        {"key": "card", "label": "Ma carte en ligne", "value": f"{_site_url()}/card/{serial}"},
    ]
    if card.get("tagline"):
        back.insert(0, {"key": "tagline", "label": org, "value": card["tagline"]})
    for k, lbl in (("address", "Adresse"), ("phone", "Téléphone"), ("website", "Site web")):
        if tenant.get(k):
            back.append({"key": k, "label": lbl, "value": tenant[k]})

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
        "sharingProhibited": True,
        **colors,
        "barcodes": [{
            "format": "PKBarcodeFormatCode128" if card.get("code_type") == "barcode" else "PKBarcodeFormatQR",
            "message": serial, "messageEncoding": "iso-8859-1", "altText": serial,
        }],
        "storeCard": {
            # With a banner: points in the header, nothing over the image.
            # Without: the classic big number, statut in the header.
            "headerFields": ([points_field] if show("show_points") else []) if has_banner
            else ([tier_field] if show_tier else []),
            "primaryFields": [] if has_banner
            else ([points_field] if show("show_points") else []),
            "secondaryFields": secondary[:4],
            "auxiliaryFields": auxiliary[:4],
            "backFields": back,
        },
    }
    lat, lng = tenant.get("lat") or tenant.get("latitude"), tenant.get("lng") or tenant.get("longitude")
    if lat and lng:
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
    hero_mode = card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")
    if hero_mode in ("image", "composite") and card.get("hero_image_url"):
        hero_raw = _fetch_image(card.get("hero_image_url"))
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
