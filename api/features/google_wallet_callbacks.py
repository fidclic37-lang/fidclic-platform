"""
Google Wallet « saves and deletions » callbacks (user, 2026-10-10: « even
for Google Wallet also, deleted card ka data chahiye »).

Google calls our URL each time a customer saves a FidClic pass to Google
Wallet or deletes it, for every class whose `callbackOptions.url` is set
(wallet_passes._gw_class sets it; the daily cron puts it on classes created
before). Clients › Carte then reads « Retirée de Google Wallet · date », the
dashboard and the bell count it, and a pass saved again reads « Active ».

The message is signed by Google (protocol ECv2SigningOnly, sender
« GooglePayPasses », recipient = our issuer id). Nothing is believed before
the signature is checked against Google's own keys
(https://pay.google.com/gp/m/issuer/keys): an intermediate key signed by a
Google root key, then the message signed by that intermediate key — ECDSA
P-256 / SHA-256, every part length-prefixed (4 bytes, little-endian).
An expired message, another issuer's or a nonce already seen changes nothing.

    POST /api/passes/google/callback
"""
import base64
import json
import struct
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
_db = None

KEYS_URL = "https://pay.google.com/gp/m/issuer/keys"
PROTOCOL = "ECv2SigningOnly"
SENDER = "GooglePayPasses"
CALLBACK_PATH = "/api/passes/google/callback"
_KEYS: Dict[str, Any] = {"keys": None, "at": 0.0}


def init(db):
    global _db
    _db = db
    try:
        db.google_wallet_events.create_index("nonce", unique=True)
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def callback_url() -> str:
    """Always production's: the class is shared by every deployment, and a
    preview link (often protected) would swallow production's deletions."""
    import os
    return (os.getenv("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/") + CALLBACK_PATH


# ---------------------------------------------------------------------------
# signature (Google's ECv2SigningOnly)
# ---------------------------------------------------------------------------
def _lp(*parts: str) -> bytes:
    out = b""
    for p in parts:
        b = p.encode("utf-8")
        out += struct.pack("<I", len(b)) + b
    return out


def _root_keys() -> List[str]:
    """Google's current root keys for this protocol, cached one hour."""
    if _KEYS["keys"] is not None and time.time() - _KEYS["at"] < 3600:
        return _KEYS["keys"]
    with urllib.request.urlopen(KEYS_URL, timeout=10) as r:
        data = json.loads(r.read().decode())
    now_ms = int(time.time() * 1000)
    keys = [k["keyValue"] for k in data.get("keys", [])
            if k.get("protocolVersion") == PROTOCOL
            and (not k.get("keyExpiration") or int(k["keyExpiration"]) > now_ms)]
    _KEYS.update(keys=keys, at=time.time())
    return keys


def _verify(public_b64: str, signature_b64: str, data: bytes) -> bool:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.exceptions import InvalidSignature
    try:
        key = serialization.load_der_public_key(base64.b64decode(public_b64))
        if not isinstance(key, ec.EllipticCurvePublicKey):
            return False
        key.verify(base64.b64decode(signature_b64), data, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_and_open(token: Dict[str, Any], recipient_id: str, root_keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """The signed message's content, once Google's signatures hold — else ValueError."""
    if not isinstance(token, dict) or token.get("protocolVersion") != PROTOCOL:
        raise ValueError("protocol")
    inter = token.get("intermediateSigningKey") or {}
    signed_key = inter.get("signedKey")
    if not isinstance(signed_key, str) or not inter.get("signatures"):
        raise ValueError("intermediate key")
    roots = root_keys if root_keys is not None else _root_keys()
    data = _lp(SENDER, PROTOCOL, signed_key)
    if not any(_verify(root, sig, data) for root in roots for sig in inter["signatures"]):
        raise ValueError("intermediate signature")
    key = json.loads(signed_key)
    if int(key.get("keyExpiration") or 0) <= int(time.time() * 1000):
        raise ValueError("intermediate key expired")
    message = token.get("signedMessage")
    if not isinstance(message, str):
        raise ValueError("message")
    if not _verify(key["keyValue"], token.get("signature") or "", _lp(SENDER, recipient_id, PROTOCOL, message)):
        raise ValueError("message signature")
    body = json.loads(message)
    if int(body.get("expTimeMillis") or 0) <= int(time.time() * 1000):
        raise ValueError("expired")
    return body


# ---------------------------------------------------------------------------
# the endpoint
# ---------------------------------------------------------------------------
def _serial_of(object_id: str) -> Optional[str]:
    row = _db.google_wallet_objects.find_one({"object_id": object_id}, {"serial": 1})
    if row and row.get("serial"):
        return row["serial"]
    # issuer.FT_ABCD1234 → FT-ABCD1234 (an object made before we kept the map)
    tail = object_id.split(".", 1)[-1]
    if tail.upper().startswith("FT_"):
        return "FT-" + tail[3:].upper()
    return None


@router.post(CALLBACK_PATH)
async def google_callback(request: Request):
    from features import wallet_passes as WP
    issuer = WP._gw_issuer()
    if not issuer:
        raise HTTPException(status_code=404)
    try:
        token = json.loads((await request.body()).decode("utf-8"))
        body = verify_and_open(token, issuer)
    except Exception as exc:          # unsigned, forged, expired, malformed
        print(f"google callback refused: {exc}")
        raise HTTPException(status_code=400, detail="Message non vérifié.")
    event, object_id, nonce = body.get("eventType"), str(body.get("objectId") or ""), body.get("nonce")
    if event not in ("save", "del") or not object_id.startswith(f"{issuer}."):
        return {"ok": True, "ignored": True}
    # Google may deliver twice: the nonce is kept, a repeat changes nothing
    try:
        _db.google_wallet_events.insert_one({"nonce": str(nonce or f"{object_id}:{event}:{body.get('expTimeMillis')}"),
                                             "object_id": object_id, "event": event, "at": _now()})
    except Exception:
        return {"ok": True, "duplicate": True}
    serial = _serial_of(object_id)
    cust = _db.customers.find_one({"barcode_id": serial}, {"_id": 0, "id": 1, "tenant_id": 1}) if serial else None
    if not cust:
        return {"ok": True, "ignored": True}
    field = "google_removed_at" if event == "del" else "google_added_at"
    _db.customers.update_one({"id": cust["id"]}, {"$set": {field: _now()}})
    if event == "save":
        try:                                     # Bienvenue (once per client, features/automations)
            from features import automations as AU
            AU.wallet_added(cust["tenant_id"], cust, "google")
        except Exception as exc:
            print(f"google callback: welcome not sent (non-fatal): {exc}")
    return {"ok": True}


def ensure_callbacks() -> Dict[str, Any]:
    """Put the callback URL on every shop's Google Wallet class (the daily
    cron): classes created before 2026-10-10 had none, so Google never told
    us of a deletion. Idempotent; a class already pointing here is skipped."""
    from features import wallet_passes as WP
    if not WP.google_configured():
        return {"configured": False}
    token = WP._gw_access_token()
    url = callback_url()
    done = skipped = failed = 0
    for tid in _db.google_wallet_objects.distinct("tenant_id"):
        class_id, _ = WP._gw_ids(tid, "FT-0")
        status, cls = WP._gw_call("GET", f"/loyaltyClass/{class_id}", None, token)
        if status != 200:
            failed += 1
            continue
        if (cls.get("callbackOptions") or {}).get("url") == url:
            skipped += 1
            continue
        status, _ = WP._gw_call("PATCH", f"/loyaltyClass/{class_id}", {"callbackOptions": {"url": url}}, token)
        if status == 200:
            done += 1
        else:
            failed += 1
    return {"configured": True, "updated": done, "already": skipped, "failed": failed}
