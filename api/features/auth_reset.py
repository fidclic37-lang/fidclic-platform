"""
Password reset by email — magic link (S3 finale).

Status: 🟢 Core.
Mounts at: /api/auth/forgot-password, /api/auth/reset-password
Storage: password_resets.

WHY ONLY NOW
    A reset email needs a mailer; the mailer arrived with S12 (Brevo). Until
    then the honest fallback was human paths (EC resets employees, support
    resets owners) — those stay, this ADDS the self-serve road.

SECURITY DECISIONS (each one blocks a real attack)
    - No user enumeration: /forgot-password answers the SAME {"ok": true}
      whether the email exists or not. Otherwise an attacker can test which
      emails have accounts.
    - The token is 32 random url-safe bytes; we store only its SHA-256. A DB
      leak therefore leaks nothing usable — same reason we hash passwords.
    - 30-minute expiry, single-use, and all previous tokens of that email are
      invalidated on each new request AND on success.
    - Max 3 requests per email per hour — an attacker cannot flood a victim's
      inbox (and cannot burn our Brevo quota).
    - The new password passes the same S3 policy as everywhere else.
    - Cabinet members' must_change_password flag is cleared — they chose this
      password themselves, which is the whole point of that flag.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["auth-reset"])
_db = None

TOKEN_TTL_MIN = 30
MAX_PER_HOUR = 3


def init(db):
    global _db
    _db = db
    try:
        _db.password_resets.create_index([("token_hash", 1)])
        _db.password_resets.create_index([("email", 1), ("created_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audit(*args, **kwargs):
    try:
        from features import audit
        audit.log(*args, **kwargs)
    except Exception:
        pass


def _site_url() -> str:
    return os.getenv("PUBLIC_SITE_URL", "https://app.fidclic.com")


@router.post("/api/auth/forgot-password")
def forgot_password(body: Dict[str, Any]):
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email:
        # even malformed input gets the neutral answer — nothing to learn here
        return {"ok": True}

    user = _db.users.find_one({"email": email})
    if not user:
        return {"ok": True}                      # no enumeration

    hour_ago = (_now() - timedelta(hours=1)).isoformat()
    recent = _db.password_resets.count_documents(
        {"email": email, "created_at": {"$gte": hour_ago}})
    if recent >= MAX_PER_HOUR:
        return {"ok": True}                      # silently absorb the flood

    # newest request wins: kill any previous live token for this email
    _db.password_resets.update_many({"email": email, "used": False},
                                    {"$set": {"used": True, "voided": True}})

    token = secrets.token_urlsafe(32)
    _db.password_resets.insert_one({
        "id": str(uuid4()), "email": email,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "used": False,
        "expires_at": (_now() + timedelta(minutes=TOKEN_TTL_MIN)).isoformat(),
        "created_at": _now().isoformat(),
    })

    link = f"{_site_url()}/reinitialiser?token={token}"
    from services import mailer
    mailer.send(
        to=email,
        subject="Réinitialisation de votre mot de passe FidClic",
        html=f"""
        <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1C1917">
          <p>Bonjour,</p>
          <p>Une réinitialisation de mot de passe a été demandée pour ce compte.
          Ce lien est valable <strong>{TOKEN_TTL_MIN} minutes</strong> et ne peut servir qu'une fois :</p>
          <p style="text-align:center;margin:24px 0">
            <a href="{link}" style="background:#B85C38;color:#fff;padding:12px 22px;
               border-radius:24px;text-decoration:none;font-weight:bold">
               Choisir un nouveau mot de passe</a>
          </p>
          <p style="font-size:12px;color:#57534E">Si vous n'êtes pas à l'origine de
          cette demande, ignorez cet email — votre mot de passe reste inchangé.</p>
        </div>""",
    )
    _audit("auth.reset_requested", actor=None, object_kind="user", object_id=email)
    return {"ok": True}


@router.post("/api/auth/reset-password")
def reset_password(body: Dict[str, Any]):
    token = (body.get("token") or "").strip()
    new = body.get("new_password") or ""
    if not token:
        raise HTTPException(422, "Lien invalide.")

    row = _db.password_resets.find_one(
        {"token_hash": hashlib.sha256(token.encode()).hexdigest()})
    if not row or row.get("used"):
        raise HTTPException(410, "Ce lien a déjà été utilisé ou n'est plus valide — redemandez-en un.")
    if row["expires_at"] < _now().isoformat():
        raise HTTPException(410, "Ce lien a expiré (30 min) — redemandez-en un.")

    from services import password_policy
    password_policy.assert_valid(new)

    from auth import hash_password
    _db.users.update_one({"email": row["email"]},
                         {"$set": {"hashed_password": hash_password(new)}})
    _db.password_resets.update_many({"email": row["email"]},
                                    {"$set": {"used": True}})
    # they chose this password themselves — the forced-change flag is satisfied
    _db.cabinet_memberships.update_many({"user_email": row["email"]},
                                        {"$set": {"must_change_password": False}})
    _audit("auth.reset_completed", actor=None, object_kind="user",
           object_id=row["email"])
    return {"ok": True}
