"""
Super admin › Paramètres › Mes paramètres (user, 2026-11-11), PR 3 of 3 —
every member of FidClic's team, about themselves only:

    GET /api/admin/me            profil, sécurité (password, 2FA), sessions, mes alertes
    PUT /api/admin/me/profile    nom, prénom, téléphone, photo (≤ 2 Mo, an image)
    PUT /api/admin/me/alerts     {kind: "email" | "bell"} for the types my role opens

The password, 2FA and sessions themselves use the shops' routes
(features/security_page), opened to the team: the same rules everywhere.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from auth import TokenData, require_role
from features import team_alerts as TA

router = APIRouter(tags=["admin"])
_db = None

TEAM = list(TA.TEAM)
PHOTO_MAX = 2 * 1024 * 1024
ROLE_LABELS = {"super_admin": "Super Admin", "fidclic_team": "Équipe FidClic", "commercial": "Commercial"}


def init(db):
    global _db
    _db = db
    TA.init(db)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _me(token: TokenData) -> Dict[str, Any]:
    u = _db.users.find_one({"email": token.email}, {"_id": 0})
    if not u or u.get("role") not in TEAM or u.get("active") is False:
        raise HTTPException(status_code=403, detail="Réservé à l'équipe FidClic.")
    return u


def _role_label(u: Dict[str, Any]) -> str:
    if u.get("role") == "fidclic_team" and u.get("platform_role"):
        r = _db.platform_roles.find_one({"id": u["platform_role"]}, {"_id": 0, "name": 1}) or {}
        return r.get("name") or ROLE_LABELS["fidclic_team"]
    return ROLE_LABELS.get(u.get("role"), u.get("role") or "")


def _view(u: Dict[str, Any], sid: Optional[str]) -> Dict[str, Any]:
    sessions = list(_db.user_sessions.find({"email": u["email"], "revoked_at": None,
                                            "last_seen": {"$gte": _now() - timedelta(days=30)}}, {"_id": 0}).sort("last_seen", -1))
    changed = _aware(u.get("password_changed_at")) or _aware(u.get("created_at"))
    return {
        "profile": {"email": u["email"], "first_name": u.get("first_name") or "", "last_name": u.get("last_name") or "",
                    "phone": u.get("phone") or "", "photo": u.get("photo") or None, "role": _role_label(u)},
        "security": {"has_password": bool(u.get("hashed_password")), "provider": u.get("auth_provider"),
                     "password_changed_at": changed.isoformat() if changed and u.get("hashed_password") else None,
                     "totp": bool(u.get("totp_enabled")), "backup_codes_left": len(u.get("totp_backup") or [])},
        "sessions": [{"sid": s["sid"], "device": s.get("device") or "Appareil", "browser": s.get("browser") or "",
                      "os": s.get("os") or "", "kind": s.get("kind") or "desktop",
                      "place": ", ".join(x for x in (s.get("city"), s.get("country")) if x),
                      "current": s["sid"] == sid, "last_seen": (_aware(s.get("last_seen")) or _now()).isoformat()}
                     for s in sessions],
        "alerts": TA.prefs(u),
    }


@router.get("/api/admin/me")
def me(token_data: TokenData = Depends(require_role(TEAM))):
    return _view(_me(token_data), getattr(token_data, "sid", None))


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: Optional[str] = Field(None, max_length=80)
    last_name: Optional[str] = Field(None, max_length=80)
    phone: Optional[str] = Field(None, max_length=30)
    photo: Optional[str] = Field(None, max_length=4 * 1024 * 1024)

    @field_validator("first_name", "last_name")
    @classmethod
    def _trim(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() if v is not None else None


@router.put("/api/admin/me/profile")
def save_profile(body: ProfileIn, request: Request, token_data: TokenData = Depends(require_role(TEAM))):
    u = _me(token_data)
    sent = body.model_dump(exclude_unset=True)
    sets: Dict[str, Any] = {}
    unset: Dict[str, Any] = {}
    for k in ("first_name", "last_name"):
        if k in sent:
            sets[k] = sent[k] or ""
    if "phone" in sent:
        if sent["phone"]:
            from services import customer_fields as CF
            sets["phone"] = CF.phone(sent["phone"])
        else:
            unset["phone"] = ""
    if "photo" in sent:
        p = sent["photo"]
        if not p:
            unset["photo"] = ""
        else:
            if not p.startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
                raise HTTPException(status_code=400, detail="La photo doit être une image (PNG, JPEG ou WebP).")
            try:
                raw = base64.b64decode(p.split(",", 1)[1], validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(status_code=400, detail="Photo illisible.")
            if len(raw) > PHOTO_MAX:
                raise HTTPException(status_code=413, detail="Photo trop lourde (2 Mo maximum).")
            from services import media
            sets["photo"] = media.put(p)
    if sets or unset:
        _db.users.update_one({"email": u["email"]}, {**({"$set": sets} if sets else {}), **({"$unset": unset} if unset else {})})
        import server as core
        core.log_audit("platform.profile_update", actor=u["email"], actor_type="user", target=u["email"], request=request,
                       meta={"fields": sorted(set(sets) | set(unset))})
    return _view(_me(token_data), getattr(token_data, "sid", None))


@router.put("/api/admin/me/alerts")
def save_alerts(body: Dict[str, str], request: Request, token_data: TokenData = Depends(require_role(TEAM))):
    u = _me(token_data)
    cur = dict(u.get("alert_prefs") or {})
    for k, v in (body or {}).items():
        if k not in TA.LABELS:
            raise HTTPException(status_code=400, detail=f"Type d'alerte inconnu : {str(k)[:30]}.")
        if v not in TA.CHANNELS:
            raise HTTPException(status_code=422, detail="Choisissez « email » ou « bell ».")
        if not TA.may(u, k):
            raise HTTPException(status_code=400, detail=f"Votre rôle n'ouvre pas « {TA.LABELS[k]} ».")
        cur[k] = v
    _db.users.update_one({"email": u["email"]}, {"$set": {"alert_prefs": cur}})
    import server as core
    core.log_audit("platform.alert_prefs_update", actor=u["email"], actor_type="user", target=u["email"], request=request, meta=body)
    return _view(_me(token_data), getattr(token_data, "sid", None))
