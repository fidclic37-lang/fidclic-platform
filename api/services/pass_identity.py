"""
Apple pass identities — one Pass Type ID per business (user, 2026-10-30).

WHY
    Wallet groups the passes that share a pass type identifier. Every FidClic
    card used the one in APPLE_PASS_TYPE_ID, so a customer's cards of several
    shops sat together in one stack. A business with its own identity gets
    its own place in Wallet.

WHAT
    pass_identities  {tenant_id, pass_type_id, cert_pem, key_enc, expires_at,
                      source: manual|api, active, created_at, updated_at}
    The private key is encrypted with PASS_IDENTITY_SECRET (Fernet); without
    that secret nothing is stored. The shared identity stays in the
    environment, as before.

RULES
    • a card is pinned to one id the first time its pass is made
      (customers.apple_pass_type_id) and never moves: an installed pass
      whose identifier changed would no longer update;
    • cards already in a Wallet keep the shared id (user: « waise hi chalne
      do »); new cards of a business with an active identity take its id;
    • « active » only decides new cards — an identity switched off keeps
      signing the cards already on it.
"""
from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

_db = None
_FILES: Dict[str, Tuple[str, str]] = {}
_FILES_LOCK = threading.Lock()


def init(db) -> None:
    global _db
    _db = db
    try:
        _db.pass_identities.create_index("tenant_id", unique=True)
        _db.pass_identities.create_index("pass_type_id", unique=True)
    except Exception:
        pass


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _b64_env(name: str) -> bytes:
    v = _env(name)
    if not v:
        return b""
    try:
        return base64.b64decode(v)
    except Exception:
        return v.encode()


def shared_pt() -> str:
    return _env("APPLE_PASS_TYPE_ID")


@dataclass
class Identity:
    pass_type_id: str
    cert_pem: bytes
    key_pem: bytes
    key_password: Optional[bytes] = None


def _fernet():
    secret = _env("PASS_IDENTITY_SECRET")
    if len(secret) < 16:
        raise ValueError("PASS_IDENTITY_SECRET manquant : la clé ne peut pas être gardée chiffrée.")
    from cryptography.fernet import Fernet
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _shared() -> Optional[Identity]:
    cert, key = _b64_env("APPLE_PASS_CERT_B64"), _b64_env("APPLE_PASS_KEY_B64")
    if not (shared_pt() and cert and key):
        return None
    pw = _env("APPLE_PASS_KEY_PASSWORD")
    return Identity(shared_pt(), cert, key, pw.encode() if pw else None)


def get(pass_type_id: Optional[str]) -> Optional[Identity]:
    """The identity that signs (and pushes) passes of this id; None for an
    id FidClic does not hold."""
    if not pass_type_id or pass_type_id == shared_pt():
        return _shared()
    if _db is None:
        return None
    doc = _db.pass_identities.find_one({"pass_type_id": pass_type_id})
    if not doc:
        return None
    try:
        key = _fernet().decrypt(doc["key_enc"].encode())
    except Exception as exc:                       # noqa: BLE001
        print(f"pass identity {pass_type_id}: key not readable ({exc})")
        return None
    return Identity(pass_type_id, doc["cert_pem"].encode(), key)


def for_new_card(tenant_id: Optional[str]) -> str:
    if tenant_id and _db is not None:
        doc = _db.pass_identities.find_one({"tenant_id": tenant_id, "active": True}, {"pass_type_id": 1})
        if doc:
            return doc["pass_type_id"]
    return shared_pt()


def _in_a_wallet(c: Dict[str, Any]) -> bool:
    """Already given an Apple pass under the shared id: added, downloaded or
    registered on an iPhone."""
    if c.get("wallet_added_at") or c.get("apple_downloaded_at") or c.get("wallet_removed_at"):
        return True
    serial = c.get("barcode_id")
    return bool(serial and _db is not None and _db.pass_registrations.count_documents({"serial": serial}, limit=1))


def pin(c: Optional[Dict[str, Any]]) -> str:
    """The pass type id of this card — chosen once, then kept."""
    c = c or {}
    if c.get("apple_pass_type_id"):
        return c["apple_pass_type_id"]
    if not c.get("id") or _db is None:
        return shared_pt()
    pt = shared_pt() if _in_a_wallet(c) else for_new_card(c.get("tenant_id"))
    try:
        _db.customers.update_one({"id": c["id"], "apple_pass_type_id": {"$exists": False}},
                                 {"$set": {"apple_pass_type_id": pt}})
        stored = _db.customers.find_one({"id": c["id"]}, {"apple_pass_type_id": 1}) or {}
        pt = stored.get("apple_pass_type_id") or pt       # two first builds at once: one wins
    except Exception as exc:                       # noqa: BLE001
        print(f"pass identity: card not pinned ({exc})")
    return pt


def check(pass_type_id: str, cert_pem: str, key_pem: str) -> datetime:
    """Refuses anything Apple would not accept; returns the certificate's end."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID

    pt = (pass_type_id or "").strip()
    if not pt.startswith("pass.") or len(pt) > 200 or " " in pt:
        raise ValueError("L'identifiant doit commencer par « pass. » (ex. pass.com.fidclic.royaltrim).")
    if pt == shared_pt():
        raise ValueError("C'est l'identifiant partagé de FidClic : il ne peut pas appartenir à un seul commerce.")
    try:
        cert = x509.load_pem_x509_certificate((cert_pem or "").encode())
    except Exception:
        raise ValueError("Certificat illisible (format PEM attendu).")
    try:
        key = serialization.load_pem_private_key((key_pem or "").encode(), password=None)
    except Exception:
        raise ValueError("Clé privée illisible (PEM sans mot de passe attendu).")
    uid = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.USER_ID)]
    cn = [a.value for a in cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)]
    if pt not in uid and not any(str(v).endswith(pt) for v in cn):
        raise ValueError(f"Ce certificat n'est pas celui de {pt}.")
    pub = serialization.PublicFormat.SubjectPublicKeyInfo
    if (key.public_key().public_bytes(serialization.Encoding.PEM, pub)
            != cert.public_key().public_bytes(serialization.Encoding.PEM, pub)):
        raise ValueError("La clé privée ne correspond pas au certificat.")
    end = cert.not_valid_after_utc
    if end <= datetime.now(timezone.utc):
        raise ValueError("Ce certificat a expiré.")
    return end


def save(tenant_id: str, pass_type_id: str, cert_pem: str, key_pem: str, source: str = "manual") -> Dict[str, Any]:
    pt = (pass_type_id or "").strip()
    end = check(pt, cert_pem, key_pem)
    taken = _db.pass_identities.find_one({"pass_type_id": pt, "tenant_id": {"$ne": tenant_id}}, {"tenant_id": 1})
    if taken:
        raise ValueError("Cet identifiant appartient déjà à un autre commerce.")
    mine = _db.pass_identities.find_one({"tenant_id": tenant_id}, {"pass_type_id": 1}) or {}
    if mine.get("pass_type_id") and mine["pass_type_id"] != pt and _cards_on(mine["pass_type_id"]):
        raise ValueError("Des cartes utilisent déjà l'identifiant actuel de ce commerce : il ne peut pas être remplacé.")
    now = datetime.now(timezone.utc)
    _db.pass_identities.update_one({"tenant_id": tenant_id}, {
        "$set": {"pass_type_id": pt, "cert_pem": cert_pem if cert_pem.endswith("\n") else cert_pem + "\n",
                 "key_enc": _fernet().encrypt(key_pem.encode()).decode(), "expires_at": end,
                 "source": source, "active": True, "updated_at": now},
        "$setOnInsert": {"created_at": now}}, upsert=True)
    _FILES.pop(pt, None)
    return status(tenant_id)


def set_active(tenant_id: str, active: bool) -> Dict[str, Any]:
    if not _db.pass_identities.find_one({"tenant_id": tenant_id}):
        raise ValueError("Ce commerce n'a pas d'identifiant Apple propre.")
    _db.pass_identities.update_one({"tenant_id": tenant_id}, {"$set": {"active": bool(active),
                                                                     "updated_at": datetime.now(timezone.utc)}})
    return status(tenant_id)


def _cards_on(pt: str) -> int:
    return _db.customers.count_documents({"apple_pass_type_id": pt})


def status(tenant_id: str) -> Dict[str, Any]:
    doc = _db.pass_identities.find_one({"tenant_id": tenant_id}, {"_id": 0, "key_enc": 0, "cert_pem": 0}) or {}
    end = doc.get("expires_at")
    if isinstance(end, datetime) and not end.tzinfo:
        end = end.replace(tzinfo=timezone.utc)
    return {"pass_type_id": doc.get("pass_type_id"), "source": doc.get("source"), "active": bool(doc.get("active")),
            "expires_at": end.isoformat() if isinstance(end, datetime) else None,
            "cards": _cards_on(doc["pass_type_id"]) if doc.get("pass_type_id") else 0,
            "shared": shared_pt()}


def cert_files(pass_type_id: Optional[str]) -> Optional[Tuple[str, str]]:
    """httpx wants the APNs client certificate on disk: written once per id
    to the function's private tmp dir."""
    ident = get(pass_type_id)
    if not ident:
        return None
    pt = ident.pass_type_id
    with _FILES_LOCK:
        hit = _FILES.get(pt)
        if hit and all(os.path.exists(p) for p in hit):
            return hit
        d = tempfile.mkdtemp(prefix="fidclic-apns-")
        cp, kp = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
        for path, data in ((cp, ident.cert_pem), (kp, ident.key_pem)):
            with open(path, "wb") as fh:
                fh.write(data)
            os.chmod(path, 0o600)
        _FILES[pt] = (cp, kp)
        return _FILES[pt]
