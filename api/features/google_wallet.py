"""
Google Wallet — customer loyalty pass claim + "Add to Google Wallet" save URL.

Status: ✅ Implemented (Demo Mode issuer; no save/delete callbacks yet).
Mounts at: POST /api/wallet/claim
Collection: writes a `google_wallet` sub-document on `customers`.

Flow:
- `/api/join/{slug}` (server.py) returns a short-lived, customer-specific
  `wallet_claim_token` (HS256, signed with the existing Fidclic JWT secret).
- The join page POSTs that token here. We validate it, look the customer up
  strictly from the token claims, create-or-reuse the customer's ONE permanent
  Google Wallet Loyalty Object, and return a signed Save-to-Wallet URL.

Duplicate-card guarantee:
- Object ID is deterministic (`<issuer>.cust_<tenant>_<customer>`) and, once
  stored on the customer doc, always reused. Removing the pass in Google
  Wallet only de-links it; re-adding uses the same object ID.

Phase 2 — tenant-specific classes (merchant branding):
- The owner clicks "Publier sur Google Wallet" in the Card Designer →
  POST /api/owner/wallet/publish builds a Loyalty CLASS from the existing
  card template (logo, brand colour, business name, reward text, links)
  and stores it at `tenant.google_wallet.class_id`. Nothing is created
  automatically when a tenant is created.
- Images: Google fetches class images over public HTTPS. The designer keeps
  logos/photos as base64 data URLs inside `card_templates`, so we serve them
  at GET /api/public/wallet-assets/{tenant_id}/{kind} — no extra storage.
- Points/tier sync: sync_wallet_after_points_change(customer_id) PATCHes
  the customer's ONE permanent object after scans / redemptions / bonuses.
  It never creates an object and never raises.

Config (env only — never VITE_, never in the repo):
  GOOGLE_WALLET_ISSUER_ID, GOOGLE_WALLET_PROJECT_ID,
  GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL, GOOGLE_WALLET_PRIVATE_KEY,
  GOOGLE_WALLET_CLASS_ID, GOOGLE_WALLET_ENV

Never logs: private key, OAuth assertion/token, or the signed Save JWT.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from auth import SECRET_KEY, ALGORITHM, require_role
from models import TokenData

logger = logging.getLogger("fidelitour.features.google_wallet")

router = APIRouter(tags=["google-wallet"])
_db = None


def init(db):
    global _db
    _db = db


# ---------- Constants ----------
WALLET_API_BASE = "https://walletobjects.googleapis.com/walletobjects/v1"
WALLET_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
WALLET_OAUTH_SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"
WALLET_SAVE_URL_PREFIX = "https://pay.google.com/gp/v/save/"
WALLET_CLAIM_PURPOSE = "google_wallet_claim"
HTTP_TIMEOUT = (5, 15)  # (connect, read) seconds

_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]")
_HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DATA_URL_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+);base64,(.+)$", re.DOTALL)
WALLET_ASSET_KINDS = ("logo", "hero")
WALLET_HERO_MAX_BYTES = 1_500_000


# ---------- Models ----------
class WalletClaimRequest(BaseModel):
    wallet_claim_token: str


class WalletSettingsRequest(BaseModel):
    programme_name: Optional[str] = None
    points_label: Optional[str] = None


class WalletHeroRequest(BaseModel):
    data_url: str


# ---------- Config ----------
def _get_config() -> dict:
    """Read required Google Wallet config from env. 503 if anything is missing.

    Values are never logged or returned to the client.
    """
    required = (
        "GOOGLE_WALLET_ISSUER_ID",
        "GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL",
        "GOOGLE_WALLET_PRIVATE_KEY",
        "GOOGLE_WALLET_CLASS_ID",
    )
    cfg = {k: (os.environ.get(k) or "").strip() for k in required}
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        logger.error("google_wallet: missing config %s", ",".join(missing))
        raise HTTPException(
            status_code=503,
            detail="Google Wallet n'est pas configuré sur ce serveur.",
        )
    cfg["GOOGLE_WALLET_PRIVATE_KEY"] = _normalize_private_key(cfg["GOOGLE_WALLET_PRIVATE_KEY"])
    cfg["GOOGLE_WALLET_PROJECT_ID"] = (os.environ.get("GOOGLE_WALLET_PROJECT_ID") or "").strip()
    cfg["GOOGLE_WALLET_ENV"] = (os.environ.get("GOOGLE_WALLET_ENV") or "").strip()
    return cfg


# Tolerant PEM framing: any dash count, any whitespace (incl. NBSP) inside the
# marker words, any case — copy/paste through docs and chat UIs mangles these.
_PEM_BODY_RE = re.compile(
    r"-{2,}\s*BEGIN\s+(RSA\s+)?PRIVATE\s+KEY\s*-{2,}(.*?)-{2,}\s*END\s+(?:RSA\s+)?PRIVATE\s+KEY\s*-{2,}",
    re.DOTALL | re.IGNORECASE,
)
_UNICODE_DASHES_RE = re.compile("[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]")
_NOT_BASE64_RE = re.compile(r"[^A-Za-z0-9+/=]")


def _normalize_private_key(raw: str) -> str:
    """Turn whatever was pasted into the Vercel env into a loadable PKCS#8 PEM.

    Handles the usual paste accidents without ever logging the value:
    surrounding quotes, the whole service-account JSON instead of just the
    key, literal "\\n" (or double-escaped "\\\\n") sequences, CRLF, spaces
    instead of newlines, missing trailing newline. Raises a 503 with a
    safe, structural-only log line if the result still doesn't parse.
    """
    value = (raw or "").strip()
    # Whole service-account JSON pasted → take its private_key field.
    if value.startswith("{"):
        try:
            value = (json.loads(value).get("private_key") or "").strip()
        except ValueError:
            value = ""
    # Surrounding quotes from a `KEY="..."` style paste.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    # Escaped newlines (single or double escaped) and CRLF → real newlines.
    value = value.replace("\\\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    # Unicode dashes / non-breaking spaces from rich-text copy → ASCII.
    value = _UNICODE_DASHES_RE.sub("-", value).replace("\u00a0", " ").replace("\u200b", "")

    m = _PEM_BODY_RE.search(value)
    if m:
        header = "RSA PRIVATE KEY" if m.group(1) else "PRIVATE KEY"
        body = m.group(2)
    else:
        # No recognisable framing → assume a bare base64 PKCS#8 body.
        header = "PRIVATE KEY"
        body = value
    # Keep only base64 characters (drops stray quotes, spaces, invisible chars).
    body = _NOT_BASE64_RE.sub("", body)
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    pem = f"-----BEGIN {header}-----\n" + "\n".join(lines) + f"\n-----END {header}-----\n"

    try:
        serialization.load_pem_private_key(pem.encode(), password=None)
    except (ValueError, TypeError):
        # Structural facts only — never the content.
        logger.error(
            "google_wallet: GOOGLE_WALLET_PRIVATE_KEY unparseable (len=%d, had_begin=%s, "
            "begin_word=%s, non_ascii=%d, had_literal_backslash_n=%s, body_len=%d)",
            len(raw or ""), bool(m), "begin" in (raw or "").lower(),
            sum(1 for ch in (raw or "") if ord(ch) > 127), "\\n" in (raw or ""), len(body),
        )
        raise HTTPException(
            status_code=503,
            detail="Google Wallet n'est pas configuré correctement sur ce serveur.",
        )
    return pem


def _get_tenant_class_id(tenant: Optional[dict], cfg: dict) -> str:
    """Resolve the Wallet class for a tenant.

    Phase 2 hook: a tenant-specific class lives at `tenant.google_wallet.class_id`.
    When absent we fall back to the shared GOOGLE_WALLET_CLASS_ID. We never
    auto-provision a tenant class during a public customer claim, and we never
    store a fake tenant-specific class ID. Future merchant-class provisioning
    should only need to touch this helper.
    """
    tenant_gw = (tenant or {}).get("google_wallet") or {}
    if isinstance(tenant_gw, dict) and (tenant_gw.get("class_status") or "") == "active":
        class_id = (tenant_gw.get("class_id") or "").strip()
        if class_id:
            return class_id
    return cfg["GOOGLE_WALLET_CLASS_ID"]


# ---------- Service-account auth ----------
_token_cache = {"token": None, "exp": 0}


def _get_access_token(cfg: dict) -> str:
    """Exchange an RS256 service-account assertion for a Wallet API access token.

    Cached in-process (~50 min) so the best-effort sync after a scan costs one
    PATCH, not an OAuth round-trip every time. The token is never logged.
    """
    now = int(time.time())
    if _token_cache["token"] and _token_cache["exp"] - 60 > now:
        return _token_cache["token"]
    assertion = jwt.encode(
        {
            "iss": cfg["GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL"],
            "scope": WALLET_OAUTH_SCOPE,
            "aud": WALLET_OAUTH_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        cfg["GOOGLE_WALLET_PRIVATE_KEY"],
        algorithm="RS256",
    )
    try:
        resp = requests.post(
            WALLET_OAUTH_TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException:
        logger.error("google_wallet: oauth token request failed (network)")
        raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
    if resp.status_code != 200:
        logger.error("google_wallet: oauth token request failed status=%s msg=%s", resp.status_code, _google_error(resp))
        raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
    token = (resp.json() or {}).get("access_token")
    if not token:
        logger.error("google_wallet: oauth token response missing access_token")
        raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
    _token_cache["token"] = token
    _token_cache["exp"] = now + int((resp.json() or {}).get("expires_in") or 3000)
    return token


def _wallet_request(method: str, path: str, access_token: str, json_body: Optional[dict] = None) -> requests.Response:
    try:
        return requests.request(
            method,
            f"{WALLET_API_BASE}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            json=json_body,
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException:
        logger.error("google_wallet: %s %s failed (network)", method, path.split("/")[1] if "/" in path else path)
        raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")


# ---------- Object helpers ----------
def _google_error(resp: requests.Response) -> str:
    """Google's own error message (e.g. "Class X not found") — never a credential."""
    try:
        err = (resp.json() or {}).get("error") or {}
        msg = err.get("message") or err.get("status") or ""
    except ValueError:
        msg = ""
    return str(msg)[:200]


def _safe_id_part(value: str) -> str:
    return _SAFE_ID_RE.sub("_", (value or "").replace("-", "_"))


def _build_object_id(issuer_id: str, tenant_id: str, customer_id: str) -> str:
    object_suffix = f"cust_{_safe_id_part(tenant_id)}_{_safe_id_part(customer_id)}"
    return f"{issuer_id}.{object_suffix}"


def _points_label(tenant: Optional[dict], tpl: Optional[dict]) -> str:
    gw = (tenant or {}).get("google_wallet") or {}
    label = (gw.get("points_label") or "").strip() if isinstance(gw, dict) else ""
    if not label:
        label = str((tpl or {}).get("points_label") or "").strip()
    return label[:20] or "Points"


def _reward_progress(customer: dict, tpl: Optional[dict]) -> Optional[str]:
    """"3 / 10 — Un café gratuit", using the same cycle math as the scan route
    (visits never decrement; stamps = visits - visits_at_last_redemption)."""
    if not tpl:
        return None
    try:
        visits_per_stamp = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
        threshold = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
        visits = int(customer.get("visits") or 0)
        last_red = int(customer.get("visits_at_last_redemption") or 0)
    except (TypeError, ValueError):
        return None
    stamps = max(0, visits - last_red) // visits_per_stamp
    stamps = min(stamps, threshold)
    reward = str(tpl.get("reward_description") or "").strip()
    return f"{stamps} / {threshold}" + (f" — {reward}" if reward else "")


def _build_loyalty_object(object_id: str, class_id: str, customer: dict, tenant: Optional[dict],
                          tpl: Optional[dict] = None) -> dict:
    barcode_id = str(customer.get("barcode_id") or "")
    try:
        points = int(customer.get("points") or 0)
    except (TypeError, ValueError):
        points = 0
    obj = {
        "id": object_id,
        "classId": class_id,
        "state": "ACTIVE",
        "accountId": barcode_id,
        "accountName": str(customer.get("name") or ""),
        "loyaltyPoints": {
            "label": _points_label(tenant, tpl),
            "balance": {"int": points},
        },
        "barcode": {
            "type": "QR_CODE",
            "value": barcode_id,
            "alternateText": barcode_id,
        },
    }
    # Optional, safe text modules only when the data exists.
    text_modules = []
    tenant_name = (tenant or {}).get("name")
    if tenant_name:
        text_modules.append({"id": "merchant", "header": "Commerçant", "body": str(tenant_name)})
    tier = customer.get("tier")
    if tier:
        text_modules.append({"id": "tier", "header": "Niveau", "body": str(tier).capitalize()})
    progress = _reward_progress(customer, tpl)
    if progress:
        text_modules.append({"id": "reward_progress", "header": "Récompense", "body": progress})
    if text_modules:
        obj["textModulesData"] = text_modules
    return obj


def _object_id_tail(object_id: str) -> str:
    """Safe log fragment: last 12 chars of the object ID."""
    return object_id[-12:]


def sync_customer_wallet_object(customer: dict, tenant: dict) -> None:
    """Create or update the customer's permanent Google Wallet object.

    Must always reuse customer.google_wallet.object_id.
    """
    cfg = _get_config()
    _ensure_wallet_object(customer, tenant, cfg)


def sync_wallet_after_points_change(customer_id: str) -> None:
    """Best-effort live sync after points/visits/tier/redemption changed.

    Called from the scan, redeem and bonus paths. Only PATCHes an object the
    customer ALREADY has (customer.google_wallet.object_id) — never creates
    one, never replaces one, and never raises: a Wallet hiccup must not
    break a scan. Google pushes the updated balance to the saved pass.
    """
    try:
        if _db is None or not customer_id:
            return
        customer = _db.customers.find_one({"id": customer_id})
        if not customer:
            return
        gw = customer.get("google_wallet") or {}
        object_id = (gw.get("object_id") or "").strip() if isinstance(gw, dict) else ""
        if not object_id:
            return
        cfg = _get_config()
        tenant = _db.tenants.find_one({"id": customer.get("tenant_id")})
        tpl = _db.card_templates.find_one({"tenant_id": customer.get("tenant_id")}) or {}
        class_id = (gw.get("class_id") or "").strip() or _get_tenant_class_id(tenant, cfg)
        body = _build_loyalty_object(object_id, class_id, customer, tenant, tpl)
        resp = _wallet_request("PATCH", f"/loyaltyObject/{object_id}", _get_access_token(cfg), body)
        if resp.status_code == 200:
            _db.customers.update_one(
                {"_id": customer["_id"]},
                {"$set": {"google_wallet.last_synced_at": datetime.now(timezone.utc)}},
            )
            logger.info("google_wallet: synced object ..%s", _object_id_tail(object_id))
        else:
            logger.warning("google_wallet: sync object ..%s status=%s msg=%s",
                           _object_id_tail(object_id), resp.status_code, _google_error(resp))
    except Exception as exc:  # noqa: BLE001 — best effort by design
        logger.warning("google_wallet: sync skipped (%s)", type(exc).__name__)


def _ensure_wallet_object(customer: dict, tenant: Optional[dict], cfg: dict) -> str:
    """Create-or-reuse-then-reconcile the customer's ONE Wallet object.

    Returns the permanent object ID and persists the `google_wallet`
    sub-document on the customer (without overwriting `created_at`).
    """
    issuer_id = cfg["GOOGLE_WALLET_ISSUER_ID"]
    class_id = _get_tenant_class_id(tenant, cfg)
    stored = customer.get("google_wallet") or {}
    stored_object_id = (stored.get("object_id") or "").strip() if isinstance(stored, dict) else ""
    object_id = stored_object_id or _build_object_id(issuer_id, customer["tenant_id"], customer["id"])
    # Preserve the class the object was originally issued under: Google does
    # not allow changing an object's class after creation.
    if stored_object_id and isinstance(stored, dict) and stored.get("class_id"):
        class_id = stored["class_id"]

    access_token = _get_access_token(cfg)
    tpl = _db.card_templates.find_one({"tenant_id": customer["tenant_id"]}) or {}
    body = _build_loyalty_object(object_id, class_id, customer, tenant, tpl)

    get_resp = _wallet_request("GET", f"/loyaltyObject/{object_id}", access_token)
    if get_resp.status_code == 200:
        existing_class = (get_resp.json() or {}).get("classId")
        if existing_class:
            body["classId"] = existing_class
            class_id = existing_class
        patch_resp = _wallet_request("PATCH", f"/loyaltyObject/{object_id}", access_token, body)
        if patch_resp.status_code != 200:
            logger.error("google_wallet: patch object ..%s status=%s msg=%s", _object_id_tail(object_id), patch_resp.status_code, _google_error(patch_resp))
            raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
        logger.info("google_wallet: reused object ..%s", _object_id_tail(object_id))
    elif get_resp.status_code == 404:
        ins_resp = _wallet_request("POST", "/loyaltyObject", access_token, body)
        if ins_resp.status_code == 409:
            # Raced / already exists — never create a second object; reuse it.
            logger.info("google_wallet: insert conflict, reusing object ..%s", _object_id_tail(object_id))
            re_get = _wallet_request("GET", f"/loyaltyObject/{object_id}", access_token)
            if re_get.status_code != 200:
                logger.error("google_wallet: refetch after 409 ..%s status=%s msg=%s", _object_id_tail(object_id), re_get.status_code, _google_error(re_get))
                raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
            existing_class = (re_get.json() or {}).get("classId")
            if existing_class:
                class_id = existing_class
        elif ins_resp.status_code != 200:
            # Which service account / class the request was made with — both are
            # public identifiers shown in the Wallet Console, not credentials.
            logger.error(
                "google_wallet: insert object ..%s status=%s msg=%s sa=%s class=%s",
                _object_id_tail(object_id), ins_resp.status_code, _google_error(ins_resp),
                cfg["GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL"], class_id,
            )
            raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")
        else:
            logger.info("google_wallet: created object ..%s", _object_id_tail(object_id))
    else:
        logger.error("google_wallet: get object ..%s status=%s msg=%s", _object_id_tail(object_id), get_resp.status_code, _google_error(get_resp))
        raise HTTPException(status_code=502, detail="Google Wallet est temporairement indisponible.")

    now = datetime.now(timezone.utc)
    fields = {
        "google_wallet.object_id": object_id,
        "google_wallet.class_id": class_id,
        "google_wallet.status": "link_generated",
        "google_wallet.save_link_generated_at": now,
        "pass_issued": True,
    }
    # Only set on first store — never overwrite the original created_at.
    if not (isinstance(stored, dict) and stored.get("created_at")):
        fields["google_wallet.created_at"] = now
    _db.customers.update_one({"_id": customer["_id"]}, {"$set": fields})
    return object_id


def _build_save_url(cfg: dict, object_id: str) -> str:
    save_jwt = jwt.encode(
        {
            "iss": cfg["GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL"],
            "aud": "google",
            "typ": "savetowallet",
            "iat": int(time.time()),
            "payload": {"loyaltyObjects": [{"id": object_id}]},
        },
        cfg["GOOGLE_WALLET_PRIVATE_KEY"],
        algorithm="RS256",
    )
    return WALLET_SAVE_URL_PREFIX + save_jwt


# ---------- Route ----------
@router.post("/api/wallet/claim")
def claim_wallet_pass(req: WalletClaimRequest):
    # 1. Validate the short-lived claim token (same secret/algorithm as app auth).
    try:
        claims = jwt.decode(req.wallet_claim_token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Lien Google Wallet expiré, veuillez réessayer depuis votre carte.")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Jeton Google Wallet invalide.")
    if claims.get("purpose") != WALLET_CLAIM_PURPOSE or claims.get("sub") != "wallet-claim":
        raise HTTPException(status_code=401, detail="Jeton Google Wallet invalide.")
    customer_id = claims.get("customer_id")
    tenant_id = claims.get("tenant_id")
    barcode_id = claims.get("barcode_id")
    if not (customer_id and tenant_id and barcode_id):
        raise HTTPException(status_code=401, detail="Jeton Google Wallet invalide.")

    # 2. Config gate.
    cfg = _get_config()

    # 3. Customer strictly from validated claims — all three must match.
    customer = _db.customers.find_one({
        "id": customer_id,
        "tenant_id": tenant_id,
        "barcode_id": barcode_id,
    })
    if not customer:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    tenant = _db.tenants.find_one({"id": tenant_id})

    # 4. Create/reuse/update the permanent object, then sign the save URL.
    object_id = _ensure_wallet_object(customer, tenant, cfg)
    save_url = _build_save_url(cfg, object_id)
    logger.info("google_wallet: save link generated for object ..%s", _object_id_tail(object_id))
    return {
        "object_id": object_id,
        "save_url": save_url,
        "status": "link_generated",
    }


# ======================================================================
# Phase 2 — tenant-specific Google Wallet CLASS (merchant branding)
# ======================================================================
# Google Wallet: the CLASS carries the look (logo, hero image, background
# colour, programme name, links); the OBJECT carries per-customer data.
# One class per tenant, created only when the owner clicks "Publier".

# ---------- Images: serve the designer's data URLs over public HTTPS ----------
def _decode_data_url(value: str):
    """data:image/...;base64,... → (bytes, mime) or None."""
    m = _DATA_URL_RE.match((value or "").strip())
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2), validate=False), m.group(1)
    except (ValueError, TypeError):
        return None


def _tenant_asset(tenant_id: str, kind: str):
    """Resolve a tenant image → (bytes, mime, version) | ("url", http_url, version) | None.

    logo  → card_templates.logo_url (what the owner already uploaded in the designer)
    hero  → wallet_assets (Wallet-specific banner) else card_templates.hero_image_url
    """
    if _db is None or kind not in WALLET_ASSET_KINDS:
        return None
    tpl = _db.card_templates.find_one({"tenant_id": tenant_id}) or {}
    src = ""
    if kind == "logo":
        src = tpl.get("logo_url") or (tpl.get("brand_fields") or {}).get("logo_url") or ""
    else:
        doc = _db.wallet_assets.find_one({"tenant_id": tenant_id, "kind": "hero"}) or {}
        src = doc.get("data_url") or tpl.get("hero_image_url") or (tpl.get("brand_fields") or {}).get("hero_image_url") or ""
    src = str(src or "").strip()
    if not src:
        return None
    if src.startswith("http://") or src.startswith("https://"):
        return ("url", src, hashlib.md5(src.encode()).hexdigest()[:10])
    decoded = _decode_data_url(src)
    if not decoded:
        return None
    data, mime = decoded
    return (data, mime, hashlib.md5(data).hexdigest()[:10])


@router.get("/api/public/wallet-assets/{tenant_id}/{kind}")
def public_wallet_asset(tenant_id: str, kind: str):
    """Public image endpoint Google fetches when rendering the class.

    Logos/photos are already public by nature (they are printed on every
    customer's pass). Cached for a day; the class references a `?v=<hash>`
    URL so a re-upload gets a fresh URL and Google re-fetches it.
    """
    asset = _tenant_asset(tenant_id, kind)
    if not asset:
        raise HTTPException(status_code=404, detail="Image introuvable.")
    if asset[0] == "url":
        return Response(status_code=302, headers={"Location": asset[1]})
    data, mime, _version = asset
    return Response(content=data, media_type=mime,
                    headers={"Cache-Control": "public, max-age=86400"})


def _asset_url(base_url: str, tenant_id: str, kind: str) -> Optional[str]:
    asset = _tenant_asset(tenant_id, kind)
    if not asset:
        return None
    if asset[0] == "url":
        return asset[1]
    return f"{base_url}/api/public/wallet-assets/{tenant_id}/{kind}?v={asset[2]}"


def _public_base_url(request: Optional[Request]) -> str:
    base = (os.environ.get("PUBLIC_APP_URL") or "").strip().rstrip("/")
    if base:
        return base
    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        if host:
            return f"{proto.split(',')[0].strip()}://{host.split(',')[0].strip()}"
    return ""


# ---------- Class content: auto-mapped from the existing Card Designer ----------
def _http_url(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    if not v.startswith("http://") and not v.startswith("https://"):
        v = "https://" + v
    return v[:2000]


def _brand_color(tpl: dict) -> str:
    brand = tpl.get("brand_fields") or {}
    layout = tpl.get("layout_style") or brand.get("layout_style") or ""
    candidates = []
    if layout == "wallet":
        candidates += [tpl.get("brand_color"), brand.get("brand_color")]
    candidates += [tpl.get("primary_color"), brand.get("primary_color")]
    for c in candidates:
        c = str(c or "").strip()
        if _HEX_COLOR_RE.match(c):
            return c.lower()
    return "#b85c38"


def _tenant_class_id(cfg: dict, tenant: dict) -> str:
    gw = tenant.get("google_wallet") or {}
    stored = (gw.get("class_id") or "").strip() if isinstance(gw, dict) else ""
    if stored:
        return stored
    slug = _safe_id_part(str(tenant.get("slug") or tenant.get("id") or ""))
    return f"{cfg['GOOGLE_WALLET_ISSUER_ID']}.t_{slug}"


def _build_loyalty_class(class_id: str, tenant: dict, tpl: dict, base_url: str) -> dict:
    gw = tenant.get("google_wallet") or {}
    settings = gw if isinstance(gw, dict) else {}
    details = tpl.get("details") or {}
    name = str(tenant.get("name") or "").strip() or "Programme fidélité"
    programme = (settings.get("programme_name") or "").strip() or name

    logo_url = _asset_url(base_url, tenant["id"], "logo")
    if not logo_url:
        raise HTTPException(status_code=400, detail="Ajoutez d'abord un logo dans le Card Designer, puis enregistrez.")

    cls = {
        "id": class_id,
        "issuerName": name[:40],
        "programName": programme[:40],
        "programLogo": {"sourceUri": {"uri": logo_url}, "contentDescription": {
            "defaultValue": {"language": "fr", "value": f"Logo {name}"}}},
        "hexBackgroundColor": _brand_color(tpl),
        "reviewStatus": "UNDER_REVIEW",
        "countryCode": "FR",
        "multipleDevicesAndHoldersAllowedStatus": "ONE_USER_ALL_DEVICES",
        "accountNameLabel": "Membre",
        "accountIdLabel": "N° de carte",
    }
    hero_url = _asset_url(base_url, tenant["id"], "hero")
    if hero_url:
        cls["heroImage"] = {"sourceUri": {"uri": hero_url}, "contentDescription": {
            "defaultValue": {"language": "fr", "value": name}}}

    website = _http_url(details.get("website") or tenant.get("website"))
    if website:
        cls["homepageUri"] = {"uri": website, "description": f"Site {name}"[:40]}

    uris = []
    if website:
        uris.append({"uri": website, "description": "Site web", "id": "website"})
    insta = (details.get("instagram") or "").strip()
    if insta:
        uris.append({"uri": _http_url(insta if "instagram.com" in insta else f"instagram.com/{insta.lstrip('@')}"),
                     "description": "Instagram", "id": "instagram"})
    fb = (details.get("facebook") or "").strip()
    if fb:
        uris.append({"uri": _http_url(fb if "facebook.com" in fb else f"facebook.com/{fb}"),
                     "description": "Facebook", "id": "facebook"})
    phone = "".join(ch for ch in str(details.get("phone") or tenant.get("phone") or "") if ch.isdigit() or ch == "+")
    if phone:
        uris.append({"uri": f"tel:{phone}", "description": "Appeler", "id": "phone"})
    if uris:
        cls["linksModuleData"] = {"uris": uris}

    text_modules = []
    reward = str(tpl.get("reward_description") or "").strip()
    if reward:
        try:
            threshold = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
            body = f"{reward} — après {threshold} passages"
        except (TypeError, ValueError):
            body = reward
        text_modules.append({"id": "reward", "header": "Récompense", "body": body[:500]})
    about = str(details.get("about") or "").strip()
    if about:
        text_modules.append({"id": "about", "header": name[:40], "body": about[:500]})
    address = str(details.get("address") or tenant.get("address") or "").strip()
    if address:
        text_modules.append({"id": "address", "header": "Adresse", "body": address[:200]})
    if text_modules:
        cls["textModulesData"] = text_modules
    return cls


def _upsert_tenant_class(tenant: dict, base_url: str) -> dict:
    """Create-or-update the tenant's ONE Wallet class from its card template.

    Stores the outcome on `tenant.google_wallet`. Google's own error message
    is surfaced to the owner (it's about content — a bad image URL, say —
    never credentials).
    """
    cfg = _get_config()
    tpl = _db.card_templates.find_one({"tenant_id": tenant["id"]}) or {}
    class_id = _tenant_class_id(cfg, tenant)
    body = _build_loyalty_class(class_id, tenant, tpl, base_url)
    token = _get_access_token(cfg)

    get_resp = _wallet_request("GET", f"/loyaltyClass/{class_id}", token)
    if get_resp.status_code == 200:
        body.pop("reviewStatus", None)  # never downgrade an approved class
        resp = _wallet_request("PATCH", f"/loyaltyClass/{class_id}", token, body)
        action = "updated"
    elif get_resp.status_code == 404:
        resp = _wallet_request("POST", "/loyaltyClass", token, body)
        action = "created"
        if resp.status_code == 409:
            body.pop("reviewStatus", None)
            resp = _wallet_request("PATCH", f"/loyaltyClass/{class_id}", token, body)
            action = "updated"
    else:
        resp, action = get_resp, "get"

    now = datetime.now(timezone.utc)
    if resp.status_code != 200:
        msg = _google_error(resp) or f"HTTP {resp.status_code}"
        logger.error("google_wallet: class %s %s status=%s msg=%s", action, class_id, resp.status_code, msg)
        _db.tenants.update_one({"id": tenant["id"]}, {"$set": {
            "google_wallet.last_error": msg[:300], "google_wallet.last_error_at": now}})
        raise HTTPException(status_code=502, detail=f"Google Wallet a refusé la carte : {msg}")

    review = (resp.json() or {}).get("reviewStatus") or "UNDER_REVIEW"
    fields = {
        "google_wallet.class_id": class_id,
        "google_wallet.class_status": "active",
        "google_wallet.review_status": review,
        "google_wallet.asset_base_url": base_url,
        "google_wallet.updated_at": now,
        "google_wallet.last_error": None,
    }
    gw = tenant.get("google_wallet") or {}
    if not (isinstance(gw, dict) and gw.get("published_at")):
        fields["google_wallet.published_at"] = now
    _db.tenants.update_one({"id": tenant["id"]}, {"$set": fields})
    logger.info("google_wallet: class %s %s (review=%s)", action, class_id, review)
    return {"class_id": class_id, "action": action, "review_status": review}


def resync_tenant_class_if_published(tenant_id: str) -> None:
    """Best-effort re-push of the class after the owner saves the designer.

    No-op unless the tenant already published; never raises.
    """
    try:
        if _db is None:
            return
        tenant = _db.tenants.find_one({"id": tenant_id})
        gw = (tenant or {}).get("google_wallet") or {}
        if not (isinstance(gw, dict) and gw.get("class_status") == "active" and gw.get("class_id")):
            return
        base_url = gw.get("asset_base_url") or _public_base_url(None)
        if not base_url:
            return
        _upsert_tenant_class(tenant, base_url)
    except Exception as exc:  # noqa: BLE001 — best effort by design
        logger.warning("google_wallet: class resync skipped (%s)", type(exc).__name__)


# ---------- Owner endpoints (Card Designer → "Google Wallet" section) ----------
_OWNER = require_role(["business_owner"])


def _wallet_status_payload(tenant: dict, base_url: str) -> dict:
    gw = tenant.get("google_wallet") or {}
    gw = gw if isinstance(gw, dict) else {}
    tpl = _db.card_templates.find_one({"tenant_id": tenant["id"]}) or {}
    details = tpl.get("details") or {}
    configured = all((os.environ.get(k) or "").strip() for k in (
        "GOOGLE_WALLET_ISSUER_ID", "GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL",
        "GOOGLE_WALLET_PRIVATE_KEY", "GOOGLE_WALLET_CLASS_ID"))
    hero_doc = _db.wallet_assets.find_one({"tenant_id": tenant["id"], "kind": "hero"}, {"_id": 1})
    return {
        "configured": configured,
        "class_id": gw.get("class_id"),
        "class_status": gw.get("class_status") or "unpublished",
        "review_status": gw.get("review_status"),
        "published_at": gw.get("published_at"),
        "updated_at": gw.get("updated_at"),
        "last_error": gw.get("last_error"),
        "programme_name": gw.get("programme_name") or "",
        "points_label": gw.get("points_label") or "",
        "has_wallet_hero": bool(hero_doc),
        "preview": {
            "business_name": tenant.get("name") or "",
            "programme_name": (gw.get("programme_name") or "").strip() or tenant.get("name") or "",
            "points_label": _points_label(tenant, tpl),
            "background_color": _brand_color(tpl),
            "logo_url": _asset_url(base_url, tenant["id"], "logo"),
            "hero_url": _asset_url(base_url, tenant["id"], "hero"),
            "reward_text": tpl.get("reward_description") or "",
            "website": _http_url(details.get("website") or tenant.get("website")),
        },
    }


@router.get("/api/owner/wallet/status")
def owner_wallet_status(request: Request, token_data: TokenData = Depends(_OWNER)):
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _wallet_status_payload(tenant, _public_base_url(request))


@router.post("/api/owner/wallet/settings")
def owner_wallet_settings(req: WalletSettingsRequest, request: Request, token_data: TokenData = Depends(_OWNER)):
    fields = {}
    if req.programme_name is not None:
        fields["google_wallet.programme_name"] = req.programme_name.strip()[:40]
    if req.points_label is not None:
        fields["google_wallet.points_label"] = req.points_label.strip()[:20]
    if fields:
        _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": fields})
        resync_tenant_class_if_published(token_data.tenant_id)
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    return _wallet_status_payload(tenant, _public_base_url(request))


@router.post("/api/owner/wallet/hero")
def owner_wallet_hero(req: WalletHeroRequest, request: Request, token_data: TokenData = Depends(_OWNER)):
    """Optional Wallet-specific banner (Google shows it under the header, ~3:1)."""
    decoded = _decode_data_url(req.data_url)
    if not decoded:
        raise HTTPException(status_code=400, detail="Image invalide.")
    if len(decoded[0]) > WALLET_HERO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image trop lourde (max 1,5 Mo).")
    _db.wallet_assets.update_one(
        {"tenant_id": token_data.tenant_id, "kind": "hero"},
        {"$set": {"data_url": req.data_url, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    resync_tenant_class_if_published(token_data.tenant_id)
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    return _wallet_status_payload(tenant, _public_base_url(request))


@router.delete("/api/owner/wallet/hero")
def owner_wallet_hero_delete(request: Request, token_data: TokenData = Depends(_OWNER)):
    _db.wallet_assets.delete_one({"tenant_id": token_data.tenant_id, "kind": "hero"})
    resync_tenant_class_if_published(token_data.tenant_id)
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    return _wallet_status_payload(tenant, _public_base_url(request))


@router.post("/api/owner/wallet/publish")
def owner_wallet_publish(request: Request, token_data: TokenData = Depends(_OWNER)):
    """Owner clicked "Publier sur Google Wallet" — create/update THIS tenant's class."""
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    base_url = _public_base_url(request)
    if not base_url:
        raise HTTPException(status_code=503, detail="URL publique introuvable (PUBLIC_APP_URL).")
    result = _upsert_tenant_class(tenant, base_url)
    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    payload = _wallet_status_payload(tenant, base_url)
    payload["result"] = result
    return payload
