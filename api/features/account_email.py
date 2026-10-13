"""
Changer l'adresse e-mail du compte — « Paramètres › Sécurité ».

Status: ✅ Implemented.
Mounts at: /api/security/email/*
Collections: `email_changes` (one pending request per account), writes `users`,
             `user_sessions`; reads `tenants` for the notice's shop name.

WHY IT EXISTS
    The e-mail is the account: it is the login, and every lookup in the code
    finds a user by it. Until now it was written once, at sign-up, and nothing
    could change it — a typo at registration meant living with it, or a new
    business with no history.

THE FLOW
    1. start   — the new address, the account's password, and whether the
                 proof arrives as a link or as a code. FidClic mails it to the
                 NEW address: if it was mistyped, nothing arrives and nothing
                 changes. The current address keeps working throughout.
    2. confirm — the link's token, or the code. Single use, 30 minutes.
    3. done    — the address moves, every other session is closed, and the OLD
                 address is told (that notice is what makes a stolen session
                 visible to the real owner).

WHAT IS *NOT* REWRITTEN
    History keeps the address that did the thing. An audit line saying
    « old@shop.fr opened the till on 3 March » is a fact, and rewriting it
    would quietly rewrite the past. The account instead carries
    `previous_emails`, so the trail is still followable. Live pointers — the
    sessions — do move, because those name the account as it is now.

WHO MAY
    The owner and FidClic's own team always. For the shop's other accounts it
    is a permission like any other (features/role_perms: `email_change`), off
    in every built-in role until the owner grants it in « Équipe & accès ».
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData, verify_password

router = APIRouter(tags=["account-email"])
_db = None

TTL_MIN = 30                 # a link or a code is worth half an hour
MAX_PER_HOUR = 3             # starts, per account — an annoyed colleague cannot flood an inbox
MAX_ATTEMPTS = 5             # wrong codes before the request is burnt
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Every role that has an account of its own and can reach Paramètres.
READERS = ["business_owner", "administrateur", "manager", "staff", "membre"]


def init(db):
    global _db
    _db = db
    try:
        db.email_changes.create_index([("token_hash", 1)])
        db.email_changes.create_index([("user_email", 1), ("created_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _me(token: TokenData) -> Dict[str, Any]:
    u = _db.users.find_one({"email": token.email}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return u


def _audit(action: str, token: TokenData, request=None, meta=None):
    try:
        from server import log_audit
        log_audit(action, actor=getattr(token, "email", None), actor_type="user",
                  tenant_id=getattr(token, "tenant_id", None), request=request, meta=meta or {})
    except Exception:
        pass


def _site_url() -> str:
    import os
    return (os.environ.get("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


def _shop_name(token: TokenData) -> str:
    t = _db.tenants.find_one({"id": getattr(token, "tenant_id", None)}, {"_id": 0, "name": 1}) or {}
    return t.get("name") or "FidClic"


def _taken(email: str, mine: str) -> bool:
    """Is some other account already on that address? A pending request counts:
    two people must not both be mid-change towards the same inbox."""
    if email != mine and _db.users.find_one({"email": email}, {"_id": 1}):
        return True
    other = _db.email_changes.find_one({"new_email": email, "used": False,
                                        "user_email": {"$ne": mine},
                                        "expires_at": {"$gt": _now()}})
    return bool(other)


def _pending(email: str) -> Optional[Dict[str, Any]]:
    return _db.email_changes.find_one({"user_email": email, "used": False,
                                       "expires_at": {"$gt": _now()}}, {"_id": 0})


# ---------------------------------------------------------------------------
# The page's own state
# ---------------------------------------------------------------------------
@router.get("/api/security/email")
def state(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    p = _pending(token_data.email)
    return {"email": token_data.email,
            "pending": ({"new_email": p["new_email"], "method": p["method"],
                         "expires_at": _aware(p["expires_at"]).isoformat()} if p else None),
            "ttl_minutes": TTL_MIN}


# ---------------------------------------------------------------------------
# 1 — ask
# ---------------------------------------------------------------------------
class StartIn(BaseModel):
    new_email: str = Field(..., max_length=200)
    password: str = Field(..., max_length=200)
    method: str = Field("link")           # "link" | "code"


@router.post("/api/security/email/start")
def start(body: StartIn, request: Request = None,
          token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    new_email = (body.new_email or "").strip().lower()
    method = body.method if body.method in ("link", "code") else "link"

    if not EMAIL_RE.match(new_email):
        raise HTTPException(status_code=400, detail="Adresse e-mail invalide.")
    if new_email == (me.get("email") or "").lower():
        raise HTTPException(status_code=400, detail="C'est déjà l'adresse de ce compte.")
    # A social account has no password to check against — it must set one first.
    if not me.get("hashed_password"):
        raise HTTPException(status_code=400,
                            detail="Ce compte se connecte avec Google ou Apple. Créez d'abord un mot de passe.")
    if not verify_password(body.password or "", me["hashed_password"]):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect.")
    if _taken(new_email, me["email"]):
        raise HTTPException(status_code=409, detail="Cette adresse est déjà utilisée par un autre compte.")

    recent = _db.email_changes.count_documents({"user_email": me["email"],
                                                "created_at": {"$gte": _now() - timedelta(hours=1)}})
    if recent >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Trop de demandes. Réessayez dans une heure.")

    # The newest request wins — an older link or code stops working.
    _db.email_changes.update_many({"user_email": me["email"], "used": False},
                                  {"$set": {"used": True, "superseded_at": _now()}})

    proof = secrets.token_urlsafe(32) if method == "link" else f"{secrets.randbelow(1000000):06d}"
    _db.email_changes.insert_one({
        "id": secrets.token_urlsafe(12), "user_email": me["email"], "new_email": new_email,
        "method": method, "token_hash": _hash(proof), "attempts": 0, "used": False,
        "tenant_id": getattr(token_data, "tenant_id", None),
        "created_at": _now(), "expires_at": _now() + timedelta(minutes=TTL_MIN),
    })
    _send_proof(new_email, proof, method, _shop_name(token_data))
    _audit("security.email_change_requested", token_data, request,
           meta={"to": new_email, "method": method})
    return {"ok": True, "method": method, "sent_to": new_email, "ttl_minutes": TTL_MIN}


def _send_proof(to: str, proof: str, method: str, shop: str) -> None:
    """Mailed by FidClic, to the NEW address only."""
    from services import mailer
    if method == "link":
        link = f"{_site_url()}/changer-email?token={proof}"
        body = f"""
          <p>Vous avez demandé à utiliser cette adresse pour vous connecter à FidClic
             ({shop}). Ce lien est valable <strong>{TTL_MIN} minutes</strong> et ne sert qu'une fois :</p>
          <p style="text-align:center;margin:24px 0">
            <a href="{link}" style="background:#2F6BFF;color:#fff;padding:12px 22px;
               border-radius:24px;text-decoration:none;font-weight:bold">Confirmer cette adresse</a>
          </p>"""
    else:
        body = f"""
          <p>Vous avez demandé à utiliser cette adresse pour vous connecter à FidClic
             ({shop}). Voici votre code, valable <strong>{TTL_MIN} minutes</strong> :</p>
          <p style="text-align:center;margin:24px 0;font-size:30px;font-weight:bold;
                    letter-spacing:7px;color:#0B1C3F">{proof}</p>"""
    mailer.send(
        to=to,
        subject="Confirmez votre nouvelle adresse e-mail FidClic",
        html=f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1C1917">
          <p>Bonjour,</p>{body}
          <p style="font-size:12px;color:#57534E">Si vous n'êtes pas à l'origine de cette demande,
          ignorez cet e-mail — rien ne change et l'ancienne adresse continue de fonctionner.</p>
        </div>""")


# ---------------------------------------------------------------------------
# 2 — confirm
# ---------------------------------------------------------------------------
class ConfirmIn(BaseModel):
    token: Optional[str] = Field(None, max_length=200)      # from the link
    code: Optional[str] = Field(None, max_length=12)        # typed in


@router.post("/api/security/email/confirm")
def confirm(body: ConfirmIn, request: Request = None,
            token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    proof = (body.token or body.code or "").strip()
    if not proof:
        raise HTTPException(status_code=422, detail="Lien ou code manquant.")
    req = _pending(token_data.email)
    if not req:
        raise HTTPException(status_code=400, detail="Aucune demande en cours. Recommencez.")
    if int(req.get("attempts") or 0) >= MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Trop d'essais. Recommencez la demande.")
    if _hash(proof) != req["token_hash"]:
        _db.email_changes.update_one({"id": req["id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400,
                            detail="Lien invalide." if req["method"] == "link" else "Code incorrect.")

    old, new = req["user_email"], req["new_email"]
    # Checked again at the last moment: someone may have taken it meanwhile.
    if _taken(new, old):
        raise HTTPException(status_code=409, detail="Cette adresse vient d'être utilisée par un autre compte.")

    _db.email_changes.update_one({"id": req["id"]}, {"$set": {"used": True, "confirmed_at": _now()}})
    _db.users.update_one({"email": old}, {"$set": {"email": new, "email_changed_at": _now()},
                                          "$push": {"previous_emails": old}})
    # Sessions name the account as it is now, so they follow it; every other
    # one is closed, so a device that is not here signs in with the new address.
    _db.user_sessions.update_many({"email": old}, {"$set": {"email": new}})
    closed = _db.user_sessions.update_many(
        {"email": new, "revoked_at": None, "sid": {"$ne": getattr(token_data, "sid", None)}},
        {"$set": {"revoked_at": _now()}}).modified_count
    _notify_old(old, new, _shop_name(token_data))
    _audit("security.email_changed", token_data, request,
           meta={"from": old, "to": new, "other_sessions_closed": closed})
    return {"ok": True, "email": new, "other_sessions_closed": closed}


def _notify_old(old: str, new: str, shop: str) -> None:
    """The old address is told after the fact — that notice is how someone
    whose session was stolen finds out their login was moved."""
    from services import mailer
    masked = new.split("@")[0][:2] + "…@" + new.split("@")[-1]
    mailer.send(
        to=old,
        subject="L'adresse e-mail de votre compte FidClic a changé",
        html=f"""<div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1C1917">
          <p>Bonjour,</p>
          <p>L'adresse de connexion du compte FidClic ({shop}) est désormais
             <strong>{masked}</strong>. Cette adresse-ci ne permet plus de se connecter.</p>
          <p style="font-size:12px;color:#57534E">Vous n'êtes pas à l'origine de ce changement ?
          Écrivez-nous immédiatement depuis cette adresse — nous rétablirons l'accès.</p>
        </div>""")


# ---------------------------------------------------------------------------
# 3 — give up
# ---------------------------------------------------------------------------
@router.post("/api/security/email/cancel")
def cancel(request: Request = None,
           token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    n = _db.email_changes.update_many({"user_email": token_data.email, "used": False},
                                      {"$set": {"used": True, "cancelled_at": _now()}}).modified_count
    if n:
        _audit("security.email_change_cancelled", token_data, request)
    return {"ok": True, "cancelled": n}
