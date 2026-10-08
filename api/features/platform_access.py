"""
Super admin › Sécurité › Utilisateurs & Rôles — FidClic's own team.

WHO (decided with the user)
    super_admin    everything, always; the only one who manages users, roles
                   and the security settings.
    fidclic_team   a team member with a role (users.platform_role): the five
                   of the mockup — Administrateur, Analyste, Support, Finance —
                   plus Commercial, and any role the super admin creates.
    commercial     the older CRM-only account: read as the Commercial role.

PERMISSIONS: two switches per section, « Voir » and « Modifier » (decided
with the user). They are enforced by the server — require_admin(module) on
every super-admin endpoint: a read needs Voir, a change needs Modifier — and
the app only shows what the role can see. A change of role applies at once
(permissions are read on each call, cached 30 s).
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import get_current_user_data, hash_password, TokenData

router = APIRouter(tags=["admin"])
_db = None

TEAM_ROLES = ("super_admin", "fidclic_team", "commercial")
READ = {"GET", "HEAD", "OPTIONS"}
MODULES = [
    ("dashboard", "Dashboard"), ("commerces", "Commerces"), ("clients", "Clients finaux"), ("analytics", "Analytics"),
    ("insights", "Insights"), ("notifications", "Notifications"), ("abonnements", "Abonnements"),
    ("plan_limits", "Plan Limits"), ("ai", "FIDCLIC AI"), ("crm", "CRM de prospection"),
    ("facturation", "Facturation"), ("support", "Support"), ("securite", "Admin"), ("parametres", "Paramètres"),
    ("equipe", "Suivi d'équipe"),        # FidClic's team tasks (features/team_tasks.py)
]
MODULE_KEYS = [k for k, _ in MODULES]
# Managing users, roles and security settings stays with the super admin,
# whatever the switches say — nobody can hand themselves more access.
SUPER_ONLY_EDIT = {"securite"}


def _p(view: List[str], edit: List[str]) -> Dict[str, Dict[str, bool]]:
    return {k: {"view": k in view or k in edit, "edit": k in edit} for k in MODULE_KEYS}


PRESETS = [
    {"id": "super_admin", "name": "Super Admin", "icon": "crown", "tone": "violet",
     "description": "Accès complet à toutes les fonctionnalités.", "perms": _p(MODULE_KEYS, MODULE_KEYS)},
    {"id": "administrateur", "name": "Administrateur", "icon": "settings", "tone": "blue",
     "description": "Gestion des commerces, utilisateurs et paramètres.",
     "perms": _p(["dashboard", "commerces", "clients", "analytics", "securite", "support"],
                 ["dashboard", "commerces", "clients", "analytics", "support"])},
    {"id": "analyste", "name": "Analyste", "icon": "chart", "tone": "green",
     "description": "Accès aux données, analytics et rapports.", "perms": _p(["analytics", "insights"], [])},
    {"id": "support", "name": "Support", "icon": "headset", "tone": "orange",
     "description": "Gestion du support et consultation limitée.",
     "perms": _p(["commerces", "notifications", "support"], ["support"])},
    {"id": "finance", "name": "Finance", "icon": "users", "tone": "rose",
     "description": "Accès aux abonnements, facturation et paiements.",
     "perms": _p(["abonnements", "ai", "securite", "facturation"], ["abonnements", "facturation"])},
    {"id": "commercial", "name": "Commercial", "icon": "briefcase", "tone": "cyan",
     "description": "Prospection : CRM, tâches, appels et séquences.", "perms": _p(["crm"], ["crm"])},
]
SYSTEM_IDS = {r["id"] for r in PRESETS}


def init(db):
    global _db
    _db = db
    try:
        db.platform_roles.create_index("id", unique=True)
    except Exception:
        pass
    for r in PRESETS:
        if not db.platform_roles.find_one({"id": r["id"]}):
            db.platform_roles.insert_one({**r, "system": True, "created_at": _now()})
    # Super Admin always has everything, even if an old copy says otherwise.
    db.platform_roles.update_one({"id": "super_admin"}, {"$set": {"perms": PRESETS[0]["perms"]}})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_perms(perms: Dict[str, Any]) -> Dict[str, Dict[str, bool]]:
    out = {}
    for k in MODULE_KEYS:
        v = (perms or {}).get(k) or {}
        edit = bool(v.get("edit"))
        out[k] = {"view": bool(v.get("view")) or edit, "edit": edit}      # Modifier implies Voir
    return out


# ---------------------------------------------------------------------------
# Who can do what
# ---------------------------------------------------------------------------
_cache: Dict[str, Any] = {}


def forget(email: Optional[str] = None) -> None:
    if email:
        _cache.pop(email, None)
    else:
        _cache.clear()


def role_id_of(user: Dict[str, Any]) -> Optional[str]:
    role = user.get("role")
    if role == "super_admin":
        return "super_admin"
    if role == "commercial":
        return user.get("platform_role") or "commercial"
    if role == "fidclic_team":
        return user.get("platform_role")
    return None


def perms_for(email: str) -> Optional[Dict[str, Dict[str, bool]]]:
    """None when this is not an active member of FidClic's team."""
    hit = _cache.get(email)
    if hit and hit[0] > _now():
        return hit[1]
    u = _db.users.find_one({"email": email}, {"_id": 0, "role": 1, "platform_role": 1, "active": 1}) or {}
    perms = None
    if u.get("role") in TEAM_ROLES and u.get("active") is not False:
        rid = role_id_of(u)
        r = _db.platform_roles.find_one({"id": rid}, {"_id": 0, "perms": 1}) if rid else None
        perms = _clean_perms((r or {}).get("perms") or {})
    _cache[email] = (_now() + timedelta(seconds=30), perms)
    return perms


def require_admin(module: str, write: Optional[bool] = None):
    """The guard of every super-admin endpoint. A read needs « Voir » on the
    module, anything else « Modifier » (write= overrides, for POSTs that only
    read, like the AI question box)."""
    async def checker(request: Request, token_data: TokenData = Depends(get_current_user_data)):
        if token_data.role not in TEAM_ROLES:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        request.state.platform_actor = token_data.email
        if token_data.role == "super_admin":
            return token_data
        perms = perms_for(token_data.email)
        if perms is None:
            raise HTTPException(status_code=401, detail="Ce compte a été désactivé.")
        need = "edit" if (write if write is not None else request.method not in READ) else "view"
        if need == "edit" and module in SUPER_ONLY_EDIT:
            raise HTTPException(status_code=403, detail="Réservé au Super Admin.")
        if not (perms.get(module) or {}).get(need):
            label = dict(MODULES).get(module, module)
            raise HTTPException(status_code=403, detail=f"Accès refusé : votre rôle ne permet pas de {'modifier' if need == 'edit' else 'voir'} « {label} ».")
        return token_data
    return checker


def require_super():
    async def checker(request: Request, token_data: TokenData = Depends(get_current_user_data)):
        if token_data.role != "super_admin":
            raise HTTPException(status_code=403, detail="Réservé au Super Admin.")
        request.state.platform_actor = token_data.email
        return token_data
    return checker


def identity(user: Dict[str, Any]) -> Dict[str, Any]:
    """What /auth/me adds for a member of the team."""
    rid = role_id_of(user)
    if not rid:
        return {}
    r = _db.platform_roles.find_one({"id": rid}, {"_id": 0, "name": 1}) or {}
    return {"platform_role": rid, "platform_role_name": r.get("name") or rid, "permissions": perms_for(user["email"]) or {}}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _audit(action: str, actor: str, target: str, meta: Dict[str, Any], request: Optional[Request] = None) -> None:
    import server as core
    core.log_audit(action, actor=actor, actor_type="user", target=target, request=request, meta=meta)


def _online(email: str) -> bool:
    return bool(_db.user_sessions.find_one({"email": email, "revoked_at": None, "last_seen": {"$gte": _now() - timedelta(minutes=10)}}))


def _last_login(email: str) -> Optional[str]:
    s = _db.platform_logins.find_one({"email": email, "ok": True}, {"_id": 0, "at": 1}, sort=[("at", -1)])
    if not s:
        s2 = _db.user_sessions.find_one({"email": email}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
        at = (s2 or {}).get("created_at")
    else:
        at = s["at"]
    if isinstance(at, datetime):
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        return at.isoformat()
    return None


def _user_view(u: Dict[str, Any], roles: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    rid = role_id_of(u)
    r = roles.get(rid) or {}
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u["email"].split("@")[0]
    return {"email": u["email"], "name": name, "first_name": u.get("first_name") or "", "last_name": u.get("last_name") or "",
            "role_id": rid, "role_name": r.get("name") or rid, "role_tone": r.get("tone") or "blue", "role_icon": r.get("icon"),
            "active": u.get("active") is not False, "online": _online(u["email"]), "last_login": _last_login(u["email"]),
            "two_fa": bool(u.get("totp_enabled")), "locked_until": _iso(u.get("locked_until")),
            "created_at": _iso(u.get("created_at"))}


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return v if isinstance(v, str) else None


def team_users() -> List[Dict[str, Any]]:
    return list(_db.users.find({"role": {"$in": list(TEAM_ROLES)}}, {"_id": 0, "hashed_password": 0, "totp_secret": 0, "backup_codes": 0}))


def _roles_map() -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in _db.platform_roles.find({}, {"_id": 0})}


@router.get("/api/admin/security/users")
def list_users(q: str = "", role: str = "", token_data: TokenData = Depends(require_admin("securite"))):
    roles = _roles_map()
    rows = [_user_view(u, roles) for u in team_users()]
    if q:
        f = q.strip().lower()
        rows = [r for r in rows if f in r["email"].lower() or f in r["name"].lower()]
    if role:
        rows = [r for r in rows if r["role_id"] == role]
    rows.sort(key=lambda r: (r["role_id"] != "super_admin", not r["active"], r["name"].lower()))
    return {"rows": rows, "me": token_data.email}


class UserIn(BaseModel):
    email: Optional[str] = Field(None, max_length=200)
    first_name: Optional[str] = Field(None, max_length=60)
    last_name: Optional[str] = Field(None, max_length=60)
    role_id: Optional[str] = None
    active: Optional[bool] = None


def _role_fields(role_id: str) -> Dict[str, Any]:
    if role_id == "super_admin":
        return {"role": "super_admin", "platform_role": None}
    if not _db.platform_roles.find_one({"id": role_id}):
        raise HTTPException(status_code=400, detail="Rôle inconnu.")
    return {"role": "fidclic_team", "platform_role": role_id}


def _active_supers(excluding: Optional[str] = None) -> int:
    return _db.users.count_documents({"role": "super_admin", "active": {"$ne": False},
                                      **({"email": {"$ne": excluding}} if excluding else {})})


@router.post("/api/admin/security/users")
def add_user(body: UserIn, request: Request, token_data: TokenData = Depends(require_super())):
    email = (body.email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Email invalide.")
    if not body.role_id:
        raise HTTPException(status_code=400, detail="Choisissez un rôle.")
    if _db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email.")
    password = secrets.token_urlsafe(9)
    _db.users.insert_one({"email": email, "first_name": (body.first_name or "").strip(), "last_name": (body.last_name or "").strip(),
                          "hashed_password": hash_password(password), "auth_provider": "password", "tenant_id": None,
                          "active": True, "created_at": _now(), "created_by": token_data.email, **_role_fields(body.role_id)})
    _audit("platform.user_create", token_data.email, email, {"role": body.role_id}, request)
    return {"email": email, "password": password}


@router.put("/api/admin/security/users/{email}")
def edit_user(email: str, body: UserIn, request: Request, token_data: TokenData = Depends(require_super())):
    email = email.strip().lower()
    u = _db.users.find_one({"email": email, "role": {"$in": list(TEAM_ROLES)}})
    if not u:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    sets: Dict[str, Any] = {}
    for k in ("first_name", "last_name"):
        v = getattr(body, k)
        if v is not None:
            sets[k] = v.strip()
    if body.role_id and body.role_id != role_id_of(u):
        if email == token_data.email:
            raise HTTPException(status_code=400, detail="Vous ne pouvez pas changer votre propre rôle.")
        if u.get("role") == "super_admin" and body.role_id != "super_admin" and _active_supers(excluding=email) == 0:
            raise HTTPException(status_code=400, detail="Il doit rester au moins un Super Admin actif.")
        sets.update(_role_fields(body.role_id))
    if body.active is not None and body.active != (u.get("active") is not False):
        if email == token_data.email:
            raise HTTPException(status_code=400, detail="Vous ne pouvez pas désactiver votre propre compte.")
        if not body.active and u.get("role") == "super_admin" and _active_supers(excluding=email) == 0:
            raise HTTPException(status_code=400, detail="Il doit rester au moins un Super Admin actif.")
        sets["active"] = body.active
    if sets:
        _db.users.update_one({"email": email}, {"$set": sets})
        forget(email)
        if sets.get("active") is False or "role" in sets:
            # Off, or another role: every open session ends now.
            _db.user_sessions.update_many({"email": email, "revoked_at": None}, {"$set": {"revoked_at": _now()}})
        _audit("platform.user_update", token_data.email, email, {k: v for k, v in sets.items() if k != "platform_role"}
               | ({"role": body.role_id} if "role" in sets else {}), request)
    return _user_view(_db.users.find_one({"email": email}, {"_id": 0}), _roles_map())


@router.post("/api/admin/security/users/{email}/reset-password")
def reset_password(email: str, request: Request, token_data: TokenData = Depends(require_super())):
    email = email.strip().lower()
    if not _db.users.find_one({"email": email, "role": {"$in": list(TEAM_ROLES)}}):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    password = secrets.token_urlsafe(9)
    _db.users.update_one({"email": email}, {"$set": {"hashed_password": hash_password(password)}, "$unset": {"locked_until": ""}})
    _db.user_sessions.update_many({"email": email, "revoked_at": None}, {"$set": {"revoked_at": _now()}})
    _audit("platform.user_password_reset", token_data.email, email, {}, request)
    return {"email": email, "password": password}


@router.post("/api/admin/security/users/{email}/unlock")
def unlock(email: str, request: Request, token_data: TokenData = Depends(require_super())):
    _db.users.update_one({"email": email.strip().lower()}, {"$unset": {"locked_until": ""}})
    _audit("platform.user_unlock", token_data.email, email, {}, request)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def _role_view(r: Dict[str, Any], users: List[Dict[str, Any]]) -> Dict[str, Any]:
    members = [u for u in users if role_id_of(u) == r["id"]]
    return {"id": r["id"], "name": r.get("name"), "description": r.get("description") or "", "icon": r.get("icon") or "shield",
            "tone": r.get("tone") or "blue", "system": bool(r.get("system")), "locked": r["id"] == "super_admin",
            "perms": _clean_perms(r.get("perms") or {}), "users": len(members),
            "members": [{"email": u["email"], "name": " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u["email"],
                         "active": u.get("active") is not False} for u in members]}


@router.get("/api/admin/security/roles")
def list_roles(token_data: TokenData = Depends(require_admin("securite"))):
    users = team_users()
    order = {r["id"]: i for i, r in enumerate(PRESETS)}
    roles = sorted(_db.platform_roles.find({}, {"_id": 0}), key=lambda r: (order.get(r["id"], 99), r.get("created_at") or _now()))
    return {"roles": [_role_view(r, users) for r in roles],
            "modules": [{"key": k, "label": l, "super_only_edit": k in SUPER_ONLY_EDIT} for k, l in MODULES]}


class RoleIn(BaseModel):
    name: Optional[str] = Field(None, max_length=40)
    description: Optional[str] = Field(None, max_length=160)
    icon: Optional[str] = Field(None, max_length=20)
    tone: Optional[str] = Field(None, max_length=20)
    perms: Optional[Dict[str, Dict[str, bool]]] = None


@router.post("/api/admin/security/roles")
def add_role(body: RoleIn, request: Request, token_data: TokenData = Depends(require_super())):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom au rôle.")
    if _db.platform_roles.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(status_code=409, detail="Un rôle porte déjà ce nom.")
    r = {"id": uuid.uuid4().hex[:12], "name": name, "description": (body.description or "").strip(), "icon": body.icon or "shield",
         "tone": body.tone or "blue", "system": False, "perms": _clean_perms(body.perms or {}), "created_at": _now(),
         "created_by": token_data.email}
    _db.platform_roles.insert_one(r)
    _audit("platform.role_create", token_data.email, name, {"role": r["id"]}, request)
    return _role_view(r, team_users())


@router.put("/api/admin/security/roles/{rid}")
def edit_role(rid: str, body: RoleIn, request: Request, token_data: TokenData = Depends(require_super())):
    r = _db.platform_roles.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    if rid == "super_admin":
        raise HTTPException(status_code=400, detail="Le rôle Super Admin a toujours tous les accès.")
    sets: Dict[str, Any] = {}
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="Donnez un nom au rôle.")
        sets["name"] = body.name.strip()
    for k in ("description", "icon", "tone"):
        v = getattr(body, k)
        if v is not None:
            sets[k] = v.strip()
    if body.perms is not None:
        sets["perms"] = _clean_perms(body.perms)
    if sets:
        _db.platform_roles.update_one({"id": rid}, {"$set": {**sets, "updated_at": _now(), "updated_by": token_data.email}})
        forget()
        changed = [k for k in MODULE_KEYS if "perms" in sets and sets["perms"][k] != _clean_perms(r.get("perms") or {})[k]]
        _audit("platform.role_update", token_data.email, r.get("name"), {"role": rid, "modules": changed}, request)
    return _role_view(_db.platform_roles.find_one({"id": rid}, {"_id": 0}), team_users())


@router.delete("/api/admin/security/roles/{rid}")
def delete_role(rid: str, request: Request, token_data: TokenData = Depends(require_super())):
    r = _db.platform_roles.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    if r.get("system"):
        raise HTTPException(status_code=400, detail="Les rôles de base ne se suppriment pas.")
    if any(role_id_of(u) == rid for u in team_users()):
        raise HTTPException(status_code=409, detail="Des utilisateurs ont encore ce rôle : réassignez-les d'abord.")
    _db.platform_roles.delete_one({"id": rid})
    _audit("platform.role_delete", token_data.email, r.get("name"), {"role": rid}, request)
    return {"ok": True}


class AssignIn(BaseModel):
    emails: List[str]


@router.post("/api/admin/security/roles/{rid}/assign")
def assign(rid: str, body: AssignIn, request: Request, token_data: TokenData = Depends(require_super())):
    if not _db.platform_roles.find_one({"id": rid}):
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    done = 0
    for e in body.emails[:100]:
        try:
            edit_user(e, UserIn(role_id=rid), request, token_data)
            done += 1
        except HTTPException:
            continue
    return {"assigned": done}
