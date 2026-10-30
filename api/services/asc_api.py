"""
App Store Connect API — just what Wallet needs (user, 2026-10-30): a Pass
Type ID per business and its certificate, made by the platform, never by hand.

ENV (Vercel)
    ASC_KEY_ID        the key's id (App Store Connect › Users and Access ›
                      Integrations › Team Keys)
    ASC_ISSUER_ID     the issuer id shown above the keys
    ASC_PRIVATE_KEY   the downloaded .p8 — as is, or base64 of it

The API is free with the Apple Developer Program. Calls are signed with a
short ES256 token (20 minutes at most, Apple's limit). Nothing here raises to
the caller's caller: every function returns (ok, data | error text).

Certificates: Apple's reference lacks the relationship a PASS_TYPE_ID
certificate needs; Apple DTS (forums 735692) says `passTypeId` with the pass
type id. The resource id is sent first, the identifier string if Apple
answers that it does not know it.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import jwt

API = "https://api.appstoreconnect.apple.com"
TOKEN_SECONDS = 15 * 60


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _private_key() -> bytes:
    raw = _env("ASC_PRIVATE_KEY")
    if not raw:
        return b""
    if "BEGIN" in raw:
        return raw.replace("\\n", "\n").encode()
    try:
        return base64.b64decode(raw)
    except Exception:
        return b""


def configured() -> bool:
    return bool(_env("ASC_KEY_ID") and _env("ASC_ISSUER_ID") and _private_key())


def _token() -> str:
    now = int(time.time())
    return jwt.encode({"iss": _env("ASC_ISSUER_ID"), "iat": now, "exp": now + TOKEN_SECONDS, "aud": "appstoreconnect-v1"},
                      _private_key(), algorithm="ES256", headers={"kid": _env("ASC_KEY_ID"), "typ": "JWT"})


def _send(method: str, url: str, headers: Dict[str, str], body: Optional[bytes]) -> Tuple[int, Dict[str, Any]]:
    """One HTTPS call. Replaced in tests — Apple is never called there."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _call(method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    headers = {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}
    try:
        return _send(method, API + path, headers, json.dumps(body).encode() if body is not None else None)
    except Exception as exc:                       # noqa: BLE001 — network, TLS
        return 0, {"errors": [{"detail": str(exc)[:160]}]}


def _why(status: int, data: Dict[str, Any]) -> str:
    errs = (data or {}).get("errors") or [{}]
    return f"{status} {errs[0].get('detail') or errs[0].get('title') or ''}".strip()[:200]


def find_pass_type(identifier: str) -> Tuple[bool, Any]:
    q = urllib.parse.urlencode({"filter[identifier]": identifier, "limit": "1"})
    status, data = _call("GET", f"/v1/passTypeIds?{q}")
    if status != 200:
        return False, _why(status, data)
    for row in data.get("data") or []:
        if (row.get("attributes") or {}).get("identifier") == identifier:
            return True, row
    return True, None


def create_pass_type(identifier: str, name: str) -> Tuple[bool, Any]:
    status, data = _call("POST", "/v1/passTypeIds", {"data": {"type": "passTypeIds", "attributes": {
        "identifier": identifier, "name": (name or identifier)[:60]}}})
    if status in (200, 201):
        return True, data.get("data")
    if status == 409:                              # made by an earlier, interrupted try
        ok, row = find_pass_type(identifier)
        if ok and row:
            return True, row
    return False, _why(status, data)


def create_certificate(resource_id: str, identifier: str, csr_pem: str) -> Tuple[bool, Any]:
    """{content (DER bytes), expires (ISO), id} for this pass type's CSR."""
    last = ""
    for rel in dict.fromkeys([resource_id, identifier]):
        status, data = _call("POST", "/v1/certificates", {"data": {
            "type": "certificates",
            "attributes": {"certificateType": "PASS_TYPE_ID", "csrContent": csr_pem},
            "relationships": {"passTypeId": {"data": {"type": "passTypeIds", "id": rel}}}}})
        if status in (200, 201):
            att = (data.get("data") or {}).get("attributes") or {}
            try:
                content = base64.b64decode(att.get("certificateContent") or "")
            except Exception:
                content = b""
            if not content:
                return False, "certificat vide"
            return True, {"content": content, "expires": att.get("expirationDate"), "id": (data.get("data") or {}).get("id")}
        last = _why(status, data)
        if status not in (404, 409, 400):
            break
    return False, last
