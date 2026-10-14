"""
Paramètres › Sécurité — for the owner, administrateurs and managers.

Built to the approved mockup. Each account manages its own password, its
2FA and its sessions. What it may do to others follows the team hierarchy
(features/team_access._can_manage — decided with the user: a manager acts
on its staff only, an administrateur on the managers and staff of its
establishments, the owner on everyone). The team list and the activity
follow the establishment menu (features/store_scope.py).

SESSIONS
    Each login opens a session (user_sessions) whose id travels in the JWT
    (`sid`). auth.get_current_user_data checks it on every call, so
    « Déconnecter » ends a device at once, not when its token expires.
    Device, browser, OS and city are read from the request (Vercel's
    x-vercel-ip-* headers give the city; nothing is sent to a third party).

2FA (decided with the user: a phone app)
    TOTP, RFC 6238 — Google Authenticator, Microsoft Authenticator, 1Password…
    Once on, every login (password or Google/Apple) asks for the 6-digit code.
    Ten one-time backup codes are shown once, stored hashed.

SUPPRESSION DU COMPTE (decided with the user)
    The owner: the business is closed at once (every other account is signed
    out and blocked, the subscription stops at the end of the paid period),
    and everything is deleted 30 days later — the owner can cancel until then.
    FidClic's invoices are kept: the law requires it.
    An administrateur or a manager: only its own login is deleted.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData, SECRET_KEY, ALGORITHM, verify_password, hash_password

router = APIRouter(tags=["security"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
DELETION_DAYS = 30
TOUCH_EVERY = timedelta(minutes=5)
COUNTRIES = {"FR": "France", "BE": "Belgique", "CH": "Suisse", "LU": "Luxembourg", "MC": "Monaco", "DE": "Allemagne",
             "ES": "Espagne", "IT": "Italie", "GB": "Royaume-Uni", "US": "États-Unis", "MA": "Maroc", "IN": "Inde"}
ACTIVITY_LABELS = {
    "auth.login": "Connexion réussie", "auth.oauth_login": "Connexion réussie", "auth.login_failed": "Connexion refusée",
    "security.password_changed": "Mot de passe modifié", "security.2fa_enabled": "Double authentification activée",
    "security.2fa_disabled": "Double authentification désactivée", "security.session_revoked": "Appareil déconnecté",
    "security.sessions_revoked": "Autres appareils déconnectés", "privacy.export": "Export des données clients",
    "privacy.settings_updated": "Modification des paramètres de confidentialité",
    "gdpr.erased_by_business": "Suppression d'un client", "etablissement.updated": "Modification de l'établissement",
    "team.user_created": "Ajout d'un membre d'équipe", "team.password_reset": "Mot de passe d'un membre réinitialisé",
    "security.account_deletion_requested": "Suppression du compte demandée",
    "security.account_deletion_cancelled": "Suppression du compte annulée",
}


def init(db):
    global _db
    _db = db
    try:
        db.user_sessions.create_index("sid", unique=True)
        db.user_sessions.create_index([("email", 1), ("revoked_at", 1)])
    except Exception:
        pass
    # auth.py asks us on every call whether a session is still open.
    import auth
    auth.set_session_check(session_ok)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------------------
# TOTP (RFC 6238) — no dependency
# ---------------------------------------------------------------------------
def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp(secret: str, at: Optional[float] = None, step: int = 30, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int((at if at is not None else time.time()) // step)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_ok(secret: str, code: str, at: Optional[float] = None, window: int = 1) -> bool:
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != 6 or not secret:
        return False
    t = at if at is not None else time.time()
    return any(hmac.compare_digest(totp(secret, t + k * 30), code) for k in range(-window, window + 1))


def _hash_code(code: str) -> str:
    return hashlib.sha256(("fidclic-backup:" + code.replace("-", "").upper()).encode()).hexdigest()


def check_second_factor(user: Dict[str, Any], code: str) -> bool:
    """A TOTP code, or one unused backup code (then spent)."""
    if totp_ok(user.get("totp_secret") or "", code):
        return True
    h = _hash_code(code or "")
    if h in (user.get("totp_backup") or []):
        _db.users.update_one({"email": user["email"]}, {"$pull": {"totp_backup": h}})
        return True
    return False


def make_challenge(email: str) -> str:
    return jwt.encode({"sub": email, "purpose": "2fa", "exp": _now() + timedelta(minutes=5)}, SECRET_KEY, algorithm=ALGORITHM)


def read_challenge(token: str) -> str:
    try:
        p = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Le délai est dépassé. Reconnectez-vous.")
    if p.get("purpose") != "2fa":
        raise HTTPException(status_code=401, detail="Demande invalide.")
    return p["sub"]


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _device(ua: str) -> Dict[str, str]:
    u = ua or ""
    os_ = ("iOS" if ("iPhone" in u or "iPad" in u) else "Android" if "Android" in u else "macOS" if "Mac OS" in u
           else "Windows" if "Windows" in u else "Linux" if "Linux" in u else "Autre")
    browser = ("Edge" if "Edg/" in u else "Chrome" if ("Chrome/" in u or "CriOS" in u) else "Firefox" if ("Firefox/" in u or "FxiOS" in u)
               else "Safari" if "Safari/" in u else "Navigateur")
    device = ("iPhone" if "iPhone" in u else "iPad" if "iPad" in u else "Android" if "Android" in u
              else "Mac" if os_ == "macOS" else "Windows" if os_ == "Windows" else "Ordinateur")
    kind = "mobile" if device in ("iPhone", "Android") else "tablet" if device == "iPad" else "desktop"
    return {"device": device, "os": os_, "browser": browser, "kind": kind}


def _place(request: Optional[Request]) -> Dict[str, str]:
    if request is None:
        return {"city": "", "country": ""}
    h = request.headers
    city = urllib.parse.unquote(h.get("x-vercel-ip-city") or "")
    cc = (h.get("x-vercel-ip-country") or "").upper()
    return {"city": city, "country": COUNTRIES.get(cc, cc)}


def _ip(request: Optional[Request]) -> str:
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for") or ""
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "")


def open_session(user: Dict[str, Any], request: Optional[Request] = None) -> str:
    sid = uuid.uuid4().hex
    ua = request.headers.get("user-agent", "") if request is not None else ""
    _db.user_sessions.insert_one({"sid": sid, "email": user["email"], "tenant_id": user.get("tenant_id"),
                                  "created_at": _now(), "last_seen": _now(), "ip": _ip(request), "ua": ua[:300],
                                  **_device(ua), **_place(request), "revoked_at": None})
    return sid


def session_ok(email: str, sid: Optional[str]) -> bool:
    """Called by auth on every request. Tokens issued before sessions existed
    carry no sid and stay valid until they expire."""
    if not sid:
        return True
    s = _db.user_sessions.find_one({"sid": sid}, {"_id": 0, "email": 1, "revoked_at": 1, "last_seen": 1})
    if not s or s.get("email") != email or s.get("revoked_at"):
        return False
    last = _aware(s.get("last_seen"))
    if not last or _now() - last > TOUCH_EVERY:
        _db.user_sessions.update_one({"sid": sid}, {"$set": {"last_seen": _now()}})
    return True


def is_caisse(sid: Optional[str]) -> bool:
    """Read by server._slide_session: a till keeps its session far longer, so a
    shop that closes for the summer does not come back to a login screen."""
    if not sid:
        return False
    s = _db.user_sessions.find_one({"sid": sid}, {"_id": 0, "till_store": 1, "till_since": 1})
    return bool(s and s.get("till_since"))


def _caisse_of(tid: str, s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not s.get("till_since"):
        return None
    name = None
    try:
        from features import store_cards as SC
        name = SC.store_name(tid, s.get("till_store"))
    except Exception:
        pass
    return {"store_id": s.get("till_store"), "store": name or ""}


def revoke(q: Dict[str, Any]) -> int:
    return _db.user_sessions.update_many({**q, "revoked_at": None}, {"$set": {"revoked_at": _now()}}).modified_count


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def _audit(action, token, request=None, target=None, meta=None):
    try:
        from server import log_audit
        log_audit(action, actor=getattr(token, "email", None), actor_type="user",
                  tenant_id=getattr(token, "tenant_id", None), target=target, request=request, meta=meta or {})
    except Exception:
        pass


def _me(token: TokenData) -> Dict[str, Any]:
    u = _db.users.find_one({"email": token.email}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    return u


def _name(u: Dict[str, Any]) -> str:
    n = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    return n or u.get("name") or (u.get("email") or "").split("@")[0]


def _ago(at: Optional[datetime]) -> str:
    at = _aware(at)
    if not at:
        return ""
    d = _now() - at
    if d < timedelta(minutes=5):
        return "Maintenant"
    if d < timedelta(hours=1):
        return f"Il y a {int(d.total_seconds() // 60)} min"
    if d < timedelta(days=1):
        return f"Il y a {int(d.total_seconds() // 3600)} h"
    return f"Il y a {d.days} jour{'s' if d.days > 1 else ''}"


def _team(token: TokenData, request: Optional[Request]) -> List[Dict[str, Any]]:
    from features import team_access as T
    from features import store_scope as S
    me = _me(token)
    st = T.stores(token.tenant_id)
    all_ids = [s["id"] for s in st]
    try:
        scope = S.resolve(token, request)
        shown_ids = set(scope.ids if scope.ids is not None else scope.all_ids)
    except HTTPException:
        shown_ids = set(all_ids)
    out = []
    for u in _db.users.find({"tenant_id": token.tenant_id, "role": {"$in": T.ROLES}}, {"_id": 0, "hashed_password": 0}):
        if not T._visible(me, u, all_ids):
            continue
        covered = set(T._covered(u, all_ids))
        if u.get("role") != "business_owner" and covered and not covered & shown_ids:
            continue                       # another establishment's team
        full = set(all_ids) <= covered
        out.append({"id": u.get("id") or u["email"], "email": u["email"], "name": _name(u), "role": u.get("role"),
                    "role_label": T.ROLE_META.get(u.get("role"), {}).get("label", u.get("role")),
                    "access": "Accès complet" if u.get("role") == "business_owner" or (full and u.get("role") != "staff")
                    else "Accès limité", "active": u.get("active") is not False,
                    "totp": bool(u.get("totp_enabled")), "is_me": u["email"] == me["email"],
                    "can_reset_password": T._can_manage(me, u, all_ids)})
    out.sort(key=lambda r: (not r["is_me"], T.RANK.get(r["role"], 9), r["name"].lower()))
    return out


def _activity(token: TokenData, team_emails: List[str], limit: int = 30) -> List[Dict[str, Any]]:
    """What this account may see: the owner, the whole shop; others, their own
    actions and those of the people they manage."""
    q: Dict[str, Any] = {"tenant_id": token.tenant_id, "action": {"$in": list(ACTIVITY_LABELS)}}
    if getattr(token, "role", None) != "business_owner":
        q["actor"] = {"$in": team_emails}
    rows = list(_db.audit_logs.find(q, {"_id": 0}).sort("ts", -1).limit(limit))
    names = {u["email"]: _name(u) for u in _db.users.find({"email": {"$in": list({r.get("actor") for r in rows})}},
                                                          {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "name": 1})}
    out = []
    for r in rows:
        meta = r.get("meta") or {}
        where = " • ".join(x for x in (meta.get("browser"), meta.get("os"), meta.get("place")) if x)
        out.append({"action": r["action"], "label": ACTIVITY_LABELS.get(r["action"], r["action"]),
                    "by": names.get(r.get("actor"), r.get("actor") or ""), "where": where,
                    "at": _aware(r.get("ts")).isoformat() if _aware(r.get("ts")) else None,
                    "ok": r["action"] != "auth.login_failed"})
    return out


@router.get("/api/security/overview")
def overview(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    sid = getattr(token_data, "sid", None)
    owner = getattr(token_data, "role", None) == "business_owner"
    sessions = list(_db.user_sessions.find({"email": me["email"], "revoked_at": None,
                                            "last_seen": {"$gte": _now() - timedelta(days=30)}}, {"_id": 0}).sort("last_seen", -1))
    current = next((s for s in sessions if s["sid"] == sid), sessions[0] if sessions else None)
    team = _team(token_data, request)
    t = _db.tenants.find_one({"id": token_data.tenant_id}, {"_id": 0, "deletion_scheduled_at": 1, "privacy": 1}) or {}
    try:
        from features.privacy_page import settings as privacy_settings
        retention = privacy_settings(token_data.tenant_id)["retention"]
    except Exception:
        retention = {"inactive_years": 3, "active": False}
    scheduled = _aware(t.get("deletion_scheduled_at"))
    checks = {"password": bool(me.get("hashed_password")) or bool(me.get("auth_provider")),
              "totp": bool(me.get("totp_enabled")), "backup": True, "encryption": True}
    return {
        "secure": all(checks.values()), "checks": checks,
        "me": {"email": me["email"], "name": _name(me), "role": me.get("role"),
               "has_password": bool(me.get("hashed_password")), "provider": me.get("auth_provider"),
               "password_changed_at": (_aware(me.get("password_changed_at")) or _aware(me.get("created_at")) or _now()).isoformat()
               if me.get("hashed_password") else None,
               "totp": bool(me.get("totp_enabled")), "backup_codes_left": len(me.get("totp_backup") or [])},
        "last_activity": {"at": (_aware((current or {}).get("created_at")) or _aware(me.get("last_login_at")) or _now()).isoformat(),
                          "city": (current or {}).get("city") or "", "country": (current or {}).get("country") or ""},
        "sessions": [{"sid": s["sid"], "device": s.get("device") or "Appareil", "browser": s.get("browser") or "",
                      "os": s.get("os") or "", "kind": s.get("kind") or "desktop",
                      "place": ", ".join(x for x in (s.get("city"), s.get("country")) if x),
                      # a till, and the establishment it sits in — so a device
                      # left scanning is never mistaken for someone's phone
                      "caisse": _caisse_of(token_data.tenant_id, s),
                      "current": s["sid"] == (current or {}).get("sid"), "seen": _ago(s.get("last_seen"))} for s in sessions],
        # « Code de la caisse » — off by default
        "caisse_pin": pin_config(token_data.tenant_id),
        "team": team,
        "activity": _activity(token_data, [m["email"] for m in team])[:12],
        "protection": {"backup": True, "encryption": True, "retention_years": retention.get("inactive_years", 3),
                       "retention_active": bool(retention.get("active")), "can_edit": owner},
        "deletion": {"scheduled_at": scheduled.isoformat() if scheduled else None,
                     "purge_on": (scheduled + timedelta(days=DELETION_DAYS)).date().isoformat() if scheduled else None,
                     "scope": "business" if owner else "self"},
    }


@router.get("/api/security/activity")
def activity(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    team = _team(token_data, request)
    return {"activity": _activity(token_data, [m["email"] for m in team], limit=200)}


# ---------------------------------------------------------------------------
# Password
# ---------------------------------------------------------------------------
class PasswordIn(BaseModel):
    current: Optional[str] = ""
    new: str = Field(..., max_length=200)


@router.post("/api/security/password")
def change_password(body: PasswordIn, request: Request = None,
                    token_data: TokenData = Depends(require_role(READERS + ["staff"], partial_ok=True))):
    me = _me(token_data)
    if me.get("hashed_password") and not verify_password(body.current or "", me["hashed_password"]):
        raise HTTPException(status_code=400, detail="Le mot de passe actuel est incorrect.")
    from services import password_policy
    password_policy.assert_valid(body.new)
    _db.users.update_one({"email": me["email"]}, {"$set": {"hashed_password": hash_password(body.new),
                                                           "password_changed_at": _now()}})
    # Every other device must sign in again with the new password.
    n = revoke({"email": me["email"], "sid": {"$ne": getattr(token_data, "sid", None)}})
    _audit("security.password_changed", token_data, request, meta={"other_sessions_closed": n})
    return {"ok": True, "other_sessions_closed": n}


# ---------------------------------------------------------------------------
# 2FA
# ---------------------------------------------------------------------------
@router.post("/api/security/2fa/setup")
def totp_setup(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    if me.get("totp_enabled"):
        raise HTTPException(status_code=409, detail="La double authentification est déjà activée.")
    secret = new_secret()
    _db.users.update_one({"email": me["email"]}, {"$set": {"totp_pending": secret}})
    label = urllib.parse.quote(f"FidClic:{me['email']}")
    return {"secret": secret, "uri": f"otpauth://totp/{label}?secret={secret}&issuer=FidClic&digits=6&period=30"}


class CodeIn(BaseModel):
    code: str = Field(..., max_length=20)


@router.post("/api/security/2fa/enable")
def totp_enable(body: CodeIn, request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    secret = me.get("totp_pending")
    if not secret:
        raise HTTPException(status_code=400, detail="Recommencez la configuration.")
    if not totp_ok(secret, body.code):
        raise HTTPException(status_code=400, detail="Code incorrect. Vérifiez l'heure de votre téléphone et réessayez.")
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper() for _ in range(10)]
    _db.users.update_one({"email": me["email"]}, {"$set": {"totp_secret": secret, "totp_enabled": True,
                                                           "totp_enabled_at": _now(), "totp_backup": [_hash_code(c) for c in codes]},
                                                  "$unset": {"totp_pending": ""}})
    _audit("security.2fa_enabled", token_data, request)
    return {"enabled": True, "backup_codes": codes}


class DisableIn(BaseModel):
    password: Optional[str] = ""
    code: Optional[str] = ""


@router.post("/api/security/2fa/disable")
def totp_disable(body: DisableIn, request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    if not me.get("totp_enabled"):
        return {"enabled": False}
    if not check_second_factor(me, body.code or ""):
        raise HTTPException(status_code=400, detail="Code incorrect.")
    if me.get("hashed_password") and not verify_password(body.password or "", me["hashed_password"]):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect.")
    _db.users.update_one({"email": me["email"]}, {"$set": {"totp_enabled": False},
                                                  "$unset": {"totp_secret": "", "totp_backup": "", "totp_pending": ""}})
    _audit("security.2fa_disabled", token_data, request)
    return {"enabled": False}


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------
@router.delete("/api/security/sessions/{sid}")
def end_session(sid: str, request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    if sid == getattr(token_data, "sid", None):
        raise HTTPException(status_code=400, detail="Pour cet appareil, utilisez « Se déconnecter ».")
    if not revoke({"email": token_data.email, "sid": sid}):
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    _audit("security.session_revoked", token_data, request)
    return {"ok": True}


class CaisseIn(BaseModel):
    store_id: Optional[str] = None


@router.post("/api/security/caisse")
def mark_caisse(body: CaisseIn, request: Request = None,
                token_data: TokenData = Depends(require_role(["business_owner", "administrateur"]))):
    """« Cet appareil est la caisse ».

    The till is left on a counter and scans all day: it should never be sent
    back to a login screen, and the owner should be able to tell it apart from
    their own phone in the list below — « Caisse — Plumereau », not a third
    « Chrome sur Windows » (user, 2026-10-14).

    It marks THIS session, nothing else: same sid, same « Déconnecter ».

    Not under /sessions/: that path already ends in {sid}, and « caisse » was
    swallowed as a session id — the call came back « Appareil introuvable ».
    """
    sid = getattr(token_data, "sid", None)
    if not sid:
        raise HTTPException(status_code=400, detail="Reconnectez-vous sur cet appareil pour l'enregistrer.")
    store = (body.store_id or "").strip() or None
    if store:
        t = _db.tenants.find_one({"id": token_data.tenant_id}, {"_id": 0, "branches": 1}) or {}
        open_ = {b["id"] for b in (t.get("branches") or []) if b.get("id") and b.get("status") != "closed"}
        if open_ and store not in open_:
            raise HTTPException(status_code=400, detail="Cet établissement n'existe pas.")
    _db.user_sessions.update_one({"sid": sid}, {"$set": {"till_store": store, "till_since": _now()}})
    _audit("security.caisse_on", token_data, request, meta={"store": store})
    return {"ok": True, "store_id": store}


@router.delete("/api/security/caisse")
def unmark_caisse(request: Request = None,
                  token_data: TokenData = Depends(require_role(["business_owner", "administrateur"]))):
    """This device goes back to being an ordinary one."""
    sid = getattr(token_data, "sid", None)
    if sid:
        _db.user_sessions.update_one({"sid": sid}, {"$unset": {"till_store": "", "till_since": ""}})
        _audit("security.caisse_off", token_data, request)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Le code de la caisse
# ---------------------------------------------------------------------------
# Off by default: a till should open on the scanner (user, 2026-10-14). A shop
# that wants a lock turns it on and picks who shares it — one code for the shop,
# or one per device. It is a lock, not a login: the session stays whole, the
# code only decides whether this device may scan right now.
UNLOCK_HOURS = 12


def pin_config(tid: str) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "caisse_pin": 1}) or {}
    c = t.get("caisse_pin") or {}
    return {"on": bool(c.get("on")), "mode": c.get("mode") or "shop", "set": bool(c.get("hash"))}


def _pin_hash(tid: str, sid: Optional[str], mode: str) -> Optional[str]:
    if mode == "device":
        s = _db.user_sessions.find_one({"sid": sid}, {"_id": 0, "till_pin": 1}) or {}
        return s.get("till_pin")
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "caisse_pin": 1}) or {}
    return (t.get("caisse_pin") or {}).get("hash")


def till_locked(tid: str, sid: Optional[str]) -> bool:
    """May this till scan right now? Only ever true for a till with the code on."""
    if not sid or not is_caisse(sid):
        return False
    cfg = pin_config(tid)
    if not cfg["on"]:
        return False
    s = _db.user_sessions.find_one({"sid": sid}, {"_id": 0, "till_unlocked_until": 1}) or {}
    until = _aware(s.get("till_unlocked_until"))
    return not (until and until > _now())


class PinIn(BaseModel):
    on: Optional[bool] = None
    mode: Optional[str] = None                 # "shop" | "device"
    code: Optional[str] = Field(None, max_length=12)


@router.put("/api/security/caisse/code")
def set_pin(body: PinIn, request: Request = None,
            token_data: TokenData = Depends(require_role(["business_owner", "administrateur"]))):
    """Turn the code on or off, choose who shares it, set it.

    With « device » the code is set on the till you are standing at — there is
    no other sensible place to type one device's code.
    """
    tid = token_data.tenant_id
    cur = (_db.tenants.find_one({"id": tid}, {"_id": 0, "caisse_pin": 1}) or {}).get("caisse_pin") or {}
    mode = (body.mode or cur.get("mode") or "shop").strip()
    if mode not in ("shop", "device"):
        raise HTTPException(status_code=400, detail="Mode inconnu.")
    code = (body.code or "").strip()
    if code and (not code.isdigit() or not 4 <= len(code) <= 8):
        raise HTTPException(status_code=400, detail="Le code est composé de 4 à 8 chiffres.")
    on = cur.get("on") if body.on is None else bool(body.on)
    if on and not code and not _pin_hash(tid, getattr(token_data, "sid", None), mode):
        raise HTTPException(status_code=400, detail="Choisissez d'abord un code.")
    sets = {"caisse_pin.on": bool(on), "caisse_pin.mode": mode, "caisse_pin.updated_at": _now()}
    if code and mode == "shop":
        sets["caisse_pin.hash"] = hash_password(code)
    _db.tenants.update_one({"id": tid}, {"$set": sets})
    if code and mode == "device":
        sid = getattr(token_data, "sid", None)
        if not sid:
            raise HTTPException(status_code=400, detail="Reconnectez-vous sur cet appareil.")
        _db.user_sessions.update_one({"sid": sid}, {"$set": {"till_pin": hash_password(code)}})
    _audit("security.caisse_code", token_data, request, meta={"on": bool(on), "mode": mode})
    return pin_config(tid)


class UnlockIn(BaseModel):
    code: str = Field(..., max_length=12)


@router.post("/api/security/caisse/unlock")
def unlock_till(body: UnlockIn, request: Request = None,
                token_data: TokenData = Depends(require_role(READERS + ["staff", "membre"], partial_ok=True))):
    """The code typed on the till. Right, it scans for the rest of the day."""
    tid, sid = token_data.tenant_id, getattr(token_data, "sid", None)
    cfg = pin_config(tid)
    h = _pin_hash(tid, sid, cfg["mode"])
    if not h or not verify_password((body.code or "").strip(), h):
        _audit("security.caisse_unlock_refused", token_data, request)
        raise HTTPException(status_code=403, detail="Code incorrect.")
    _db.user_sessions.update_one({"sid": sid}, {"$set": {
        "till_unlocked_until": _now() + timedelta(hours=UNLOCK_HOURS)}})
    _audit("security.caisse_unlock", token_data, request)
    return {"ok": True, "hours": UNLOCK_HOURS}


@router.post("/api/security/sessions/revoke-others")
def end_others(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    n = revoke({"email": token_data.email, "sid": {"$ne": getattr(token_data, "sid", None)}})
    _audit("security.sessions_revoked", token_data, request, meta={"count": n})
    return {"closed": n}


# ---------------------------------------------------------------------------
# Deleting the account
# ---------------------------------------------------------------------------
class DeleteIn(BaseModel):
    password: Optional[str] = ""
    confirm: str = ""


@router.post("/api/security/account/delete")
def delete_account(body: DeleteIn, request: Request = None,
                   token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token_data)
    if body.confirm.strip().upper() != "SUPPRIMER":
        raise HTTPException(status_code=400, detail="Tapez SUPPRIMER pour confirmer.")
    if me.get("hashed_password") and not verify_password(body.password or "", me["hashed_password"]):
        raise HTTPException(status_code=400, detail="Mot de passe incorrect.")
    if getattr(token_data, "role", None) != "business_owner":
        # A team account: only its own login goes.
        _audit("security.account_deletion_requested", token_data, request, meta={"scope": "self"})
        revoke({"email": me["email"]})
        _db.users.delete_one({"email": me["email"]})
        return {"deleted": "self"}
    tid = token_data.tenant_id
    at = _now()
    _db.tenants.update_one({"id": tid}, {"$set": {"deletion_scheduled_at": at, "deletion_requested_by": me["email"]}})
    # Everyone else is signed out and kept out until the owner changes their mind.
    others = [u["email"] for u in _db.users.find({"tenant_id": tid, "email": {"$ne": me["email"]}}, {"email": 1})]
    revoke({"email": {"$in": others}})
    try:
        from features import billing as BL
        t = _db.tenants.find_one({"id": tid}) or {}
        if BL.is_configured() and t.get("stripe_subscription_id"):
            BL.stripe.Subscription.modify(t["stripe_subscription_id"], cancel_at_period_end=True)
            _db.tenants.update_one({"id": tid}, {"$set": {"subscription_cancel_at_period_end": True}})
    except Exception as exc:
        print(f"security: subscription not stopped ({exc})")
    _audit("security.account_deletion_requested", token_data, request, meta={"scope": "business"})
    return {"deleted": "scheduled", "purge_on": (at + timedelta(days=DELETION_DAYS)).date().isoformat()}


@router.post("/api/security/account/restore")
def restore_account(request: Request = None, token_data: TokenData = Depends(require_role(["business_owner"]))):
    _db.tenants.update_one({"id": token_data.tenant_id}, {"$unset": {"deletion_scheduled_at": "", "deletion_requested_by": ""}})
    try:
        from features import billing as BL
        t = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
        if BL.is_configured() and t.get("stripe_subscription_id"):
            BL.stripe.Subscription.modify(t["stripe_subscription_id"], cancel_at_period_end=False)
            _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"subscription_cancel_at_period_end": False}})
    except Exception as exc:
        print(f"security: subscription not resumed ({exc})")
    _audit("security.account_deletion_cancelled", token_data, request)
    return {"restored": True}


KEEP = {"fidclic_invoices", "invoice_counters", "audit_logs", "platform_settings", "plan_settings", "tenants", "users",
        "commune_cache", "copilot_cache"}


def purge_due(at: Optional[datetime] = None) -> Dict[str, int]:
    """Daily: businesses whose 30 days have passed are deleted for good.
    FidClic's own invoices stay (10-year legal retention)."""
    at = at or _now()
    out = {"tenants": 0, "documents": 0}
    for t in list(_db.tenants.find({"deletion_scheduled_at": {"$lte": at - timedelta(days=DELETION_DAYS)}}, {"_id": 0, "id": 1})):
        tid = t["id"]
        for name in _db.list_collection_names():
            if name in KEEP:
                continue
            try:
                out["documents"] += _db[name].delete_many({"tenant_id": tid}).deleted_count
            except Exception:
                pass
        emails = [u["email"] for u in _db.users.find({"tenant_id": tid}, {"email": 1})]
        _db.user_sessions.delete_many({"email": {"$in": emails}})
        out["documents"] += _db.users.delete_many({"tenant_id": tid}).deleted_count
        _db.tenants.delete_one({"id": tid})
        _db.audit_logs.insert_one({"id": uuid.uuid4().hex, "ts": at, "action": "security.account_purged",
                                   "actor": "system", "actor_type": "system", "tenant_id": tid, "meta": {}})
        out["tenants"] += 1
    return out
