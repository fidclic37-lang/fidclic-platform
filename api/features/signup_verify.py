"""
Sign-up verification — a 6-digit code by e-mail or SMS (user, 2026-10-04/05:
« verified either by sms on their provided phone number or provided email,
they can choose amongst the 2 »).

THE FLOW
    /register (server.py) → onboarding_status="verify" (still a hidden draft)
    /onboarding/verification → the owner picks e-mail or SMS, gets a code,
    types it → onboarding_status="company" → step 2 as before.
    Google / Apple sign-ups skip it: the provider already verified the e-mail.

WHICH CHANNELS
    E-mail when Brevo is configured (BREVO_API_KEY), SMS when Twilio is
    (TWILIO_*). With neither, nobody could ever finish signing up, so /register
    goes straight to the company step (verification_required() is False) —
    the moment a provider is configured, every new sign-up is verified.

SAFETY
    Codes are stored hashed, live 10 minutes, allow 5 tries; one send per
    60 s and 5 per hour per account (SMS costs money; e-mail can be abused).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from auth import TokenData, require_role

router = APIRouter(tags=["signup-verify"])
_db = None

CODE_TTL = timedelta(minutes=10)
MAX_TRIES = 5
COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5
MAX_EMAIL_CHANGES = 3          # per hour: each new address could otherwise be sent codes afresh


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def channels() -> Dict[str, bool]:
    from services import mailer, sms
    return {"email": mailer.ready(), "sms": sms.is_configured()}


def verification_required() -> bool:
    c = channels()
    return c["email"] or c["sms"]


def _hash(user_email: str, code: str) -> str:
    return hashlib.sha256(f"{user_email}:{code}".encode()).hexdigest()


def _mask_email(e: str) -> str:
    local, _, dom = (e or "").partition("@")
    return (local[:2] + "•••" + "@" + dom) if dom else e


def _mask_phone(p: str) -> str:
    p = (p or "").strip()
    return (p[:4] + " •• •• " + p[-2:]) if len(p) > 6 else p


def _owner(token_data: TokenData) -> Dict[str, Any]:
    user = _db.users.find_one({"email": token_data.email}) or {}
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    if tenant.get("onboarding_status") != "verify":
        raise HTTPException(status_code=409, detail="Ce compte est déjà vérifié.")
    return {"user": user, "tenant": tenant}


@router.get("/api/auth/check-email")
def check_email(email: str = ""):
    """Live check for the sign-up form (format, typo, throwaway, domain)."""
    from services import email_check
    return email_check.check(email)


@router.get("/api/onboarding/verify")
def verify_state(token_data: TokenData = Depends(require_role(["business_owner"]))):
    o = _owner(token_data)
    user, tenant = o["user"], o["tenant"]
    return {"channels": channels(),
            "email": _mask_email(user.get("email") or ""),
            "phone": _mask_phone(tenant.get("phone") or user.get("phone") or "")}


class SendIn(BaseModel):
    channel: str = "email"          # "email" | "sms"


@router.post("/api/onboarding/verify/send")
def send_code(body: SendIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    from services import mailer, sms
    o = _owner(token_data)
    user, tenant = o["user"], o["tenant"]
    ch = "sms" if body.channel == "sms" else "email"
    if not channels()[ch]:
        raise HTTPException(status_code=503, detail="Ce mode de vérification n'est pas disponible pour le moment. Choisissez l'autre.")
    now = _now()
    last = _db.signup_codes.find_one({"email": user["email"]}, sort=[("created_at", -1)])
    if last and (_aware(last.get("created_at")) or now) > now - COOLDOWN:
        wait = int(((_aware(last["created_at"]) + COOLDOWN) - now).total_seconds()) + 1
        raise HTTPException(status_code=429, detail=f"Patientez {wait} s avant de demander un nouveau code.")
    if _db.signup_codes.count_documents({"email": user["email"], "created_at": {"$gte": now - timedelta(hours=1)}}) >= MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Trop de codes demandés. Réessayez dans une heure.")

    code = f"{secrets.randbelow(1_000_000):06d}"
    if ch == "email":
        res = mailer.send(
            to=user["email"],
            subject=f"{code} — votre code FidClic",
            html=(f"<div style='font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0B1C3F'>"
                  f"<p>Bonjour {user.get('first_name') or ''},</p><p>Votre code de vérification FidClic :</p>"
                  f"<p style='font-size:32px;font-weight:bold;letter-spacing:6px;margin:18px 0'>{code}</p>"
                  f"<p style='color:#64748B;font-size:13px'>Il est valable 10 minutes. Si vous n'êtes pas à l'origine "
                  f"de cette inscription, ignorez cet e-mail.</p></div>"),
            text=f"Votre code FidClic : {code} (valable 10 minutes).",
        )
        to = _mask_email(user["email"])
    else:
        phone = sms.normalize_phone(tenant.get("phone") or user.get("phone") or "")
        if not phone:
            raise HTTPException(status_code=400, detail="Numéro de téléphone invalide : choisissez la vérification par e-mail.")
        res = sms.send_sms(phone, f"FidClic : votre code de vérification est {code} (valable 10 min).")
        to = _mask_phone(phone)
    if not res.get("sent"):
        raise HTTPException(status_code=502, detail="L'envoi du code a échoué. Réessayez, ou choisissez l'autre mode.")
    _db.signup_codes.update_many({"email": user["email"], "used": False}, {"$set": {"used": True}})
    _db.signup_codes.insert_one({"email": user["email"], "channel": ch, "code_hash": _hash(user["email"], code),
                                 "tries": 0, "used": False, "created_at": now, "expires_at": now + CODE_TTL})
    return {"ok": True, "channel": ch, "to": to, "expires_in": int(CODE_TTL.total_seconds())}


class EmailIn(BaseModel):
    email: str


@router.post("/api/onboarding/verify/email")
def change_email(body: EmailIn, response: Response, request: Request = None,
                 token_data: TokenData = Depends(require_role(["business_owner"]))):
    """« Modifier l'adresse e-mail » on the code page (QA BUG-001, 2026-10-11):
    an owner who typed « …@gmial.com » waited for a code that went elsewhere,
    and could only log out. While the account is still being verified, the
    address can be corrected: the same checks as the sign-up (shape, typos,
    throwaway inboxes, a domain that receives mail), not another account's,
    3 changes an hour. The codes and sessions of the old address end; the
    browser gets a session for the new one (the login is the e-mail)."""
    import server as core
    from services import email_check
    o = _owner(token_data)                         # only while the code is awaited
    user, tenant = o["user"], o["tenant"]
    new = (body.email or "").strip().lower()
    verdict = email_check.check(new)
    if not verdict["ok"]:
        raise HTTPException(status_code=400, detail=verdict["reason"])
    old = user["email"]
    if new == old:
        raise HTTPException(status_code=400, detail="C'est déjà l'adresse de ce compte.")
    if _db.users.find_one({"email": new}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="Cette adresse e-mail est déjà utilisée par un autre compte FidClic.")
    now = _now()
    recent = [t for t in (tenant.get("verify_email_changes") or []) if (_aware(t) or now) > now - timedelta(hours=1)]
    if len(recent) >= MAX_EMAIL_CHANGES:
        raise HTTPException(status_code=429, detail="Trop de changements d'adresse. Réessayez dans une heure.")
    _db.users.update_one({"email": old}, {"$set": {"email": new, "email_changed_from": old, "email_changed_at": now},
                                          "$unset": {"email_verified_at": ""}})
    _db.tenants.update_one({"id": tenant["id"]}, {"$set": {"verify_email_changes": recent + [now]}})
    _db.signup_codes.update_many({"email": old, "used": False}, {"$set": {"used": True}})
    try:
        from features import security_page as SEC
        SEC.revoke({"email": old})
    except Exception as exc:
        print(f"signup verify: old sessions not closed ({exc})")
    core.log_audit("auth.email_corrected", actor=new, actor_type="user", tenant_id=tenant["id"],
                   request=request, meta={"from": old})
    session = core._issue_session(response, _db.users.find_one({"email": new}), request)
    return {**session, "email": _mask_email(new)}


class CheckIn(BaseModel):
    code: str


@router.post("/api/onboarding/verify/check")
def check_code(body: CheckIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    o = _owner(token_data)
    user, tenant = o["user"], o["tenant"]
    row = _db.signup_codes.find_one({"email": user["email"], "used": False}, sort=[("created_at", -1)])
    exp = _aware(row.get("expires_at")) if row else None
    if not row or not exp or exp < _now():
        raise HTTPException(status_code=400, detail="Code expiré : demandez-en un nouveau.")
    if row.get("tries", 0) >= MAX_TRIES:
        raise HTTPException(status_code=400, detail="Trop d'essais : demandez un nouveau code.")
    code = "".join(ch for ch in (body.code or "") if ch.isdigit())
    if not secrets.compare_digest(_hash(user["email"], code), row["code_hash"]):
        _db.signup_codes.update_one({"_id": row["_id"]}, {"$inc": {"tries": 1}})
        left = MAX_TRIES - row.get("tries", 0) - 1
        raise HTTPException(status_code=400, detail=f"Code incorrect. {left} essai{'s' if left > 1 else ''} restant{'s' if left > 1 else ''}."
                            if left > 0 else "Code incorrect. Demandez un nouveau code.")
    _db.signup_codes.update_one({"_id": row["_id"]}, {"$set": {"used": True}})
    field = "phone_verified_at" if row.get("channel") == "sms" else "email_verified_at"
    _db.users.update_one({"email": user["email"]}, {"$set": {field: _now()}})
    _db.tenants.update_one({"id": tenant["id"]}, {"$set": {"onboarding_status": "company"}})
    return {"ok": True, "onboarding_status": "company"}
