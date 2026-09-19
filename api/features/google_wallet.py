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

Config (env only — never VITE_, never in the repo):
  GOOGLE_WALLET_ISSUER_ID, GOOGLE_WALLET_PROJECT_ID,
  GOOGLE_WALLET_SERVICE_ACCOUNT_EMAIL, GOOGLE_WALLET_PRIVATE_KEY,
  GOOGLE_WALLET_CLASS_ID, GOOGLE_WALLET_ENV

Never logs: private key, OAuth assertion/token, or the signed Save JWT.
"""
from __future__ import annotations

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
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth import SECRET_KEY, ALGORITHM

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


# ---------- Models ----------
class WalletClaimRequest(BaseModel):
    wallet_claim_token: str


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
    class_id = (tenant_gw.get("class_id") or "").strip() if isinstance(tenant_gw, dict) else ""
    if class_id:
        return class_id
    return cfg["GOOGLE_WALLET_CLASS_ID"]


# ---------- Service-account auth ----------
def _get_access_token(cfg: dict) -> str:
    """Exchange an RS256 service-account assertion for a Wallet API access token."""
    now = int(time.time())
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


def _build_loyalty_object(object_id: str, class_id: str, customer: dict, tenant: Optional[dict]) -> dict:
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
            "label": "Points",
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
    if text_modules:
        obj["textModulesData"] = text_modules
    return obj


def _object_id_tail(object_id: str) -> str:
    """Safe log fragment: last 12 chars of the object ID."""
    return object_id[-12:]


def sync_customer_wallet_object(customer: dict, tenant: dict) -> None:
    """Create or update the customer's permanent Google Wallet object.

    Intended for future calls after points/visits/tier change.
    Must always reuse customer.google_wallet.object_id.
    """
    cfg = _get_config()
    _ensure_wallet_object(customer, tenant, cfg)


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
    body = _build_loyalty_object(object_id, class_id, customer, tenant)

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
