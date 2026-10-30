"""
One Apple Pass Type ID per business (user, 2026-10-30). Wallet groups every
pass that shares a pass type id, so all FidClic cards sat in one stack; a
test card under its own id stood apart. Each business now has its own id and
certificate — made by the platform through App Store Connect (services/
asc_api), never by hand, for every business, old and new.

    wallet_pass_types   one row per business: identifier, Apple's resource
                        id, certificate (PEM), private key (sealed), expiry,
                        status ready | pending | failed, the last error,
                        attempts and the next try

When it is made
    • on the tick (every 15 min): every open business without a ready id, a
      failed one whose next try has come, a certificate ≤ 30 days from expiry;
    • at the first card download if still missing (force) — a new customer
      should not get the common id because the tick had not come yet.
A failure never blocks a card: it is downloaded under the common id (and
stays on it), the reason is kept for the super admin, the next try backs off.

The key is sealed with a key derived from WALLET_KEYS_SECRET (or, failing
that, PASS_AUTH_SECRET / JWT_SECRET) — never stored readable, never sent.
"""
from __future__ import annotations

import base64
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from features.platform_access import require_admin

router = APIRouter(tags=["wallet-identities"])
_db = None

RENEW_BEFORE = timedelta(days=30)
LEASE = timedelta(minutes=3)               # one maker at a time per business
PER_TICK = 5                               # Apple's rate limit, and the tick's time
MAX_BACKOFF = timedelta(hours=24)
COMMON_PREFIX = "pass.com.fidclic"
_CACHE: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


def init(db):
    global _db
    _db = db
    try:
        _db.wallet_pass_types.create_index("tenant_id", unique=True)
        _db.wallet_pass_types.create_index("identifier")
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _env(name: str) -> str:
    import os
    return (os.getenv(name) or "").strip()


def common_type() -> str:
    return _env("APPLE_PASS_TYPE_ID")


# ---------------------------------------------------------------------------
# The id
# ---------------------------------------------------------------------------
def _prefix() -> str:
    common = common_type()
    return common.rsplit(".", 1)[0] if common.count(".") >= 2 else COMMON_PREFIX


def identifier_for(tenant: Dict[str, Any]) -> str:
    """pass.com.fidclic.<slug>-<6 of the tenant id>: readable, unique, and
    made once — a later slug change does not move it."""
    raw = (tenant or {}).get("slug") or (tenant or {}).get("name") or ""
    raw = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or "b"
    mark = re.sub(r"[^a-z0-9]", "", str((tenant or {}).get("id") or "").lower())[:6] or "x"
    head = f"{_prefix()}."
    room = 64 - len(head) - len(mark) - 1
    return f"{head}{slug[:room].strip('-') or 'b'}-{mark}"


# ---------------------------------------------------------------------------
# The sealed key
# ---------------------------------------------------------------------------
def _fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    secret = (_env("WALLET_KEYS_SECRET") or _env("PASS_AUTH_SECRET") or _env("JWT_SECRET") or "fidclic-dev-secret").encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"fidclic-wallet", info=b"pass-type-keys").derive(secret)
    return Fernet(base64.urlsafe_b64encode(key))


def _seal(data: bytes) -> str:
    return _fernet().encrypt(data).decode()


def _open(token: str) -> Optional[bytes]:
    try:
        return _fernet().decrypt((token or "").encode())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Making one
# ---------------------------------------------------------------------------
def _backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=15) * (2 ** max(0, attempts - 1)), MAX_BACKOFF)


def _make(row: Dict[str, Any], tenant: Dict[str, Any]) -> Dict[str, Any]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from services import asc_api as A

    ident = row["identifier"]
    rid = row.get("asc_id")
    if not rid:
        ok, found = A.find_pass_type(ident)
        if not ok:
            return {"ok": False, "error": f"Apple (liste des identifiants) : {found}"}
        if not found:
            ok, found = A.create_pass_type(ident, tenant.get("name") or ident)
            if not ok:
                return {"ok": False, "error": f"Apple (création de l'identifiant) : {found}"}
        rid = found.get("id")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (x509.CertificateSigningRequestBuilder()
           .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"FidClic {ident}")]))
           .sign(key, hashes.SHA256()))
    ok, cert = A.create_certificate(rid, ident, csr.public_bytes(serialization.Encoding.PEM).decode())
    if not ok:
        return {"ok": False, "error": f"Apple (certificat) : {cert}", "asc_id": rid}
    try:
        c = x509.load_der_x509_certificate(cert["content"])
    except Exception:
        return {"ok": False, "error": "Apple a renvoyé un certificat illisible", "asc_id": rid}
    expires = _aware(getattr(c, "not_valid_after_utc", None)) or c.not_valid_after.replace(tzinfo=timezone.utc)
    return {"ok": True, "asc_id": rid, "asc_cert_id": cert.get("id"),
            "cert_pem": c.public_bytes(serialization.Encoding.PEM).decode(),
            "key_enc": _seal(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption())),
            "expires_at": expires}


def _due(row: Optional[Dict[str, Any]], now: datetime, force: bool) -> bool:
    if not row:
        return True
    if row.get("status") == "ready":
        exp = _aware(row.get("expires_at"))
        return bool(exp and exp - now <= RENEW_BEFORE)
    if row.get("status") == "pending":
        lease = _aware(row.get("lease_until"))
        return not lease or lease < now
    nxt = _aware(row.get("next_try_at"))
    return force or not nxt or nxt <= now


def ensure(tenant_id: str, force: bool = False, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Make (or renew) this business's id and certificate when due. Never
    raises. `force`: retry a failure now (a card is being downloaded)."""
    from services import asc_api as A
    now = now or _now()
    try:
        if not A.configured() or not common_type():
            return {"status": "skipped", "reason": "App Store Connect non configuré"}
        tenant = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "id": 1, "slug": 1, "name": 1})
        if not tenant:
            return {"status": "skipped", "reason": "commerce introuvable"}
        row = _db.wallet_pass_types.find_one({"tenant_id": tenant_id})
        if not _due(row, now, force):
            return {"status": (row or {}).get("status"), "identifier": (row or {}).get("identifier")}
        ident = (row or {}).get("identifier") or identifier_for(tenant)
        if not row:
            try:
                _db.wallet_pass_types.insert_one({"tenant_id": tenant_id, "identifier": ident, "status": "new",
                                                  "attempts": 0, "created_at": now})
            except Exception:
                pass                                # another maker inserted it first
        # the lease: one atomic claim, so two ticks (or a tick and a download)
        # never ask Apple twice for the same business
        prev = _db.wallet_pass_types.find_one_and_update(
            {"tenant_id": tenant_id, "$or": [{"lease_until": None}, {"lease_until": {"$lt": now}}]},
            {"$set": {"lease_until": now + LEASE}})
        if prev is None:
            return {"status": "pending", "identifier": ident}
        renewing = prev.get("status") == "ready"
        if not renewing:
            _db.wallet_pass_types.update_one({"tenant_id": tenant_id}, {"$set": {"status": "pending"}})
        made = _make(prev, tenant)
        if made.get("ok"):
            made.pop("ok")
            _db.wallet_pass_types.update_one({"tenant_id": tenant_id}, {"$set": {
                **made, "status": "ready", "error": None, "attempts": 0, "next_try_at": None,
                "lease_until": None, "ready_at": now}})
            with _LOCK:
                _CACHE.pop(ident, None)
            return {"status": "ready", "identifier": ident}
        attempts = int(prev.get("attempts") or 0) + 1
        upd = {"error": made.get("error"), "attempts": attempts, "next_try_at": now + _backoff(attempts),
               "lease_until": None, "failed_at": now}
        if made.get("asc_id"):
            upd["asc_id"] = made["asc_id"]
        if not renewing:                           # a renewal failure keeps the certificate that works
            upd["status"] = "failed"
        _db.wallet_pass_types.update_one({"tenant_id": tenant_id}, {"$set": upd})
        print(f"wallet identity {tenant_id}: {made.get('error')}")
        return {"status": "ready" if renewing else "failed", "error": made.get("error"), "identifier": ident}
    except Exception as exc:                       # noqa: BLE001
        print(f"wallet identity {tenant_id}: {exc}")
        return {"status": "failed", "error": str(exc)[:160]}


def run_due(now: Optional[datetime] = None, limit: int = PER_TICK) -> Dict[str, Any]:
    """The tick: a few businesses at a time, the oldest need first."""
    from services import asc_api as A
    now = now or _now()
    if not A.configured() or not common_type():
        return {"skipped": "App Store Connect non configuré"}
    rows = {r["tenant_id"]: r for r in _db.wallet_pass_types.find({}, {"_id": 0, "key_enc": 0, "cert_pem": 0})}
    todo: List[str] = []
    for t in _db.tenants.find({"resiliated_at": None, "is_active": {"$ne": False}}, {"_id": 0, "id": 1}):
        if _due(rows.get(t["id"]), now, False):
            todo.append(t["id"])
    out = {"due": len(todo), "made": 0, "failed": 0}
    for tid in todo[:limit]:
        r = ensure(tid, now=now)
        out["made" if r.get("status") == "ready" else "failed"] += 1
    return out


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def tenant_type(tenant_id: Optional[str]) -> Optional[str]:
    if not tenant_id or _db is None:
        return None
    row = _db.wallet_pass_types.find_one({"tenant_id": tenant_id, "status": "ready"}, {"identifier": 1})
    return (row or {}).get("identifier")


def tenant_of_type(identifier: str) -> Optional[str]:
    row = _db.wallet_pass_types.find_one({"identifier": identifier}, {"tenant_id": 1}) if _db is not None else None
    return (row or {}).get("tenant_id")


def identity_for_type(identifier: str) -> Optional[Dict[str, bytes]]:
    """{cert_pem, key_pem} of a business's id (cached per process)."""
    with _LOCK:
        hit = _CACHE.get(identifier)
    row = _db.wallet_pass_types.find_one({"identifier": identifier, "status": "ready"},
                                         {"_id": 0, "cert_pem": 1, "key_enc": 1})
    if not row:
        return None
    if hit and hit.get("cert") == row.get("cert_pem"):
        return hit["identity"]
    key = _open(row.get("key_enc") or "")
    if not key or not row.get("cert_pem"):
        return None
    identity = {"cert_pem": row["cert_pem"].encode(), "key_pem": key}
    with _LOCK:
        _CACHE[identifier] = {"cert": row["cert_pem"], "identity": identity}
    return identity


@router.get("/api/admin/wallet-identities")
def admin_list(token_data=Depends(require_admin("commerces", write=False))):
    """Super admin: where each business's Apple id stands — never a key."""
    names = {t["id"]: t.get("name") for t in _db.tenants.find({}, {"_id": 0, "id": 1, "name": 1})}
    rows, counts = [], {"ready": 0, "pending": 0, "failed": 0, "new": 0}
    for r in _db.wallet_pass_types.find({}, {"_id": 0, "key_enc": 0, "cert_pem": 0}).sort("tenant_id", 1):
        st = r.get("status") or "new"
        counts[st] = counts.get(st, 0) + 1
        rows.append({"tenant_id": r["tenant_id"], "name": names.get(r["tenant_id"]), "identifier": r.get("identifier"),
                     "status": st, "error": r.get("error"), "attempts": r.get("attempts") or 0,
                     "expires_at": _aware(r.get("expires_at")).isoformat() if r.get("expires_at") else None,
                     "next_try_at": _aware(r.get("next_try_at")).isoformat() if r.get("next_try_at") else None})
    from services import asc_api as A
    return {"configured": A.configured(), "common": common_type(), "counts": counts, "rows": rows,
            "without": len([t for t in names if t not in {r["tenant_id"] for r in rows}])}
