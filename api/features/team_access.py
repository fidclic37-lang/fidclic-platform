"""
Paramètres › Équipe & accès — who works in the shop, in which role, on which
establishments.

Mounts at:
    GET    /api/owner/team-access                      → everything the tab shows
    POST   /api/owner/team-access/users                → create an account
    PUT    /api/owner/team-access/users/{id}           → name, role, establishments
    POST   /api/owner/team-access/users/{id}/status    → switch on / off
    POST   /api/owner/team-access/users/{id}/password  → a new password, shown once
    DELETE /api/owner/team-access/users/{id}
    PUT    /api/owner/team-access/stores/{store_id}/users/{id}  → give / take an establishment

THE FOUR ROLES (a franchise, from the top)
    business_owner  Propriétaire    every establishment, everything.
    administrateur  Administrateur  a regional director: everything on the
                                    establishments given to them — no more,
                                    no less — except billing and deleting the
                                    account. Settings they change will apply
                                    to their establishments only (and be
                                    visible to the owner).
    manager         Manager         one establishment: its clients, its
                                    campaigns, its employés. No settings.
    staff           Employé         one establishment: scanning cards.

WHO CREATES WHOM — each responsable creates the accounts just below it and
hands over the email and password (no invitation e-mail):
    Propriétaire  → Administrateurs (and anyone below)
    Administrateur→ Managers and Employés of its establishments
    Manager       → Employés of its establishment
One can only see, edit, switch off or delete accounts below one's own role
and inside one's own establishments.

ESTABLISHMENTS are the shop's branches (tenant.branches). A shop without
branches has one establishment, "main", named after the shop.

SCOPE. An account covering every establishment has scope "all"; one covering
some has "partial". auth.require_role keeps "partial" accounts out of the data
pages until those pages filter by establishment (they are being brought
over one by one), so nobody ever sees more than their establishments. Older
manager accounts, created before establishments were assigned, cover all.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth as auth_mod
from auth import require_role, TokenData, hash_password

router = APIRouter(tags=["team-access"])
_db = None

ROLES = ["business_owner", "administrateur", "manager", "staff"]
RANK = {r: i for i, r in enumerate(ROLES)}
TEAM_ROLES = ["administrateur", "manager", "staff"]
ALL_ROLES = ROLES
MAIN = "main"
NAME_MAX = 60

ROLE_META = {
    "business_owner": {"label": "Propriétaire", "tone": "blue", "icon": "crown",
                       "description": "Accès complet à toutes les fonctionnalités et tous les établissements."},
    "administrateur": {"label": "Administrateur", "tone": "green", "icon": "shield",
                       "description": "Accès complet à ses établissements, sauf la facturation et la suppression du compte."},
    "manager": {"label": "Manager", "tone": "orange", "icon": "users",
                "description": "Gère les clients, les campagnes et les employés de son établissement. Pas d'accès aux paramètres."},
    "staff": {"label": "Employé", "tone": "violet", "icon": "user",
              "description": "Scanne les cartes des clients dans son établissement."},
}

# What each role may do — fixed, as decided for the franchise model. Values:
# "all" (every establishment), "own" (its establishments), False.
PERMISSIONS = [
    {"key": "clients", "label": "Clients", "full": "Voir et gérer les clients"},
    {"key": "campaigns", "label": "Campagnes", "full": "Créer et envoyer des campagnes"},
    {"key": "analytics", "label": "Analyses", "full": "Voir les analyses et insights"},
    {"key": "team", "label": "Équipe", "full": "Gérer l'équipe"},
    {"key": "settings", "label": "Paramètres", "full": "Modifier les paramètres"},
    {"key": "automations", "label": "Automatisations", "full": "Automatisations"},
    {"key": "catalogue", "label": "Catalogue", "full": "Catalogue et carte de fidélité"},
    {"key": "scan", "label": "Scan", "full": "Scanner les cartes clients"},
    {"key": "billing", "label": "Facturation", "full": "Abonnement et facturation"},
    {"key": "delete", "label": "Suppression du compte", "full": "Supprimer le compte"},
]
MATRIX = {
    "business_owner": {p["key"]: "all" for p in PERMISSIONS},
    "administrateur": {"clients": "own", "campaigns": "own", "analytics": "own", "team": "own",
                       "settings": "own", "automations": "own", "catalogue": "own", "scan": "own",
                       "billing": False, "delete": False},
    "manager": {"clients": "own", "campaigns": "own", "analytics": "own", "team": "own",
                "settings": False, "automations": False, "catalogue": False, "scan": "own",
                "billing": False, "delete": False},
    "staff": {"scan": "own", **{k: False for k in ("clients", "campaigns", "analytics", "team",
                                                   "settings", "automations", "catalogue",
                                                   "billing", "delete")}},
}
NOTES = {
    "business_owner": "Toutes les permissions, sur tous les établissements.",
    "administrateur": "Tout sur ses établissements, sauf la facturation et la suppression du compte. "
                      "Ses changements de paramètres ne s'appliquent qu'à ses établissements.",
    "manager": "Clients, campagnes et employés de son établissement. Ne modifie pas les paramètres.",
    "staff": "Scan des cartes dans son établissement.",
}


def init(db):
    global _db
    _db = db
    try:
        db.users.create_index("email", unique=True)
    except Exception:
        pass
    auth_mod.set_team_status_lookup(status_of)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# establishments & scope
# ---------------------------------------------------------------------------
def stores(tid: str) -> List[Dict[str, Any]]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1, "name": 1, "city": 1}) or {}
    branches = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    if branches:
        return [{"id": b["id"], "name": b.get("name") or "Établissement",
                 "city": b.get("city") or b.get("postal_code") or ""} for b in branches]
    return [{"id": MAIN, "name": t.get("name") or "Mon établissement", "city": t.get("city") or ""}]


def _covered(user: Dict[str, Any], all_ids: List[str]) -> List[str]:
    """Establishments an account covers. The owner, and team accounts made
    before establishments were assigned, cover all."""
    if user.get("role") == "business_owner" or "branch_ids" not in user:
        return list(all_ids)
    return [b for b in user.get("branch_ids") or [] if b in all_ids]


def scope_of(user: Dict[str, Any]) -> str:
    all_ids = [s["id"] for s in stores(user.get("tenant_id"))]
    covered = _covered(user, all_ids)
    return "all" if set(all_ids) <= set(covered) else "partial"


def status_of(email: str) -> Optional[Dict[str, Any]]:
    """What auth.require_role needs about a team account, read live."""
    u = _db.users.find_one({"email": email}, {"_id": 0, "role": 1, "tenant_id": 1, "branch_ids": 1, "active": 1})
    if not u:
        return None
    return {"active": u.get("active", True) is not False, "scope": scope_of(u)}


def identity(user: Dict[str, Any]) -> Dict[str, Any]:
    if not user or user.get("role") not in ROLES or not user.get("tenant_id"):
        return {}
    all_ids = [s["id"] for s in stores(user["tenant_id"])]
    return {"branch_ids": _covered(user, all_ids), "scope": scope_of(user),
            "role_label": ROLE_META[user["role"]]["label"]}


# ---------------------------------------------------------------------------
# who may do what to whom
# ---------------------------------------------------------------------------
def _me(token: TokenData) -> Dict[str, Any]:
    me = _db.users.find_one({"email": token.email}, {"_id": 0, "hashed_password": 0})
    if not me or me.get("tenant_id") != token.tenant_id:
        raise HTTPException(status_code=403, detail="Compte introuvable.")
    return me


def creatable(role: str) -> List[str]:
    return [r for r in TEAM_ROLES if RANK[r] > RANK.get(role, 99)]


def _can_manage(me: Dict[str, Any], other: Dict[str, Any], all_ids: List[str]) -> bool:
    if other.get("email") == me.get("email"):
        return False
    if RANK.get(other.get("role"), -1) <= RANK.get(me.get("role"), 99):
        return False
    mine = set(_covered(me, all_ids))
    theirs = set(_covered(other, all_ids))
    return bool(theirs) and theirs <= mine


def _visible(me: Dict[str, Any], other: Dict[str, Any], all_ids: List[str]) -> bool:
    return other.get("email") == me.get("email") or me.get("role") == "business_owner" \
        or _can_manage(me, other, all_ids)


def _check_assignment(role: str, branch_ids: List[str], me: Dict[str, Any], all_ids: List[str]) -> List[str]:
    ids = [b for b in dict.fromkeys(branch_ids or []) if b]
    if len(all_ids) == 1 and not ids:
        ids = list(all_ids)
    unknown = [b for b in ids if b not in all_ids]
    if unknown:
        raise HTTPException(status_code=400, detail="Établissement inconnu.")
    if role == "administrateur" and not ids:
        raise HTTPException(status_code=400, detail="Un administrateur gère au moins un établissement.")
    if role in ("manager", "staff") and len(ids) != 1:
        raise HTTPException(status_code=400,
                            detail=f"Un {ROLE_META[role]['label'].lower()} travaille dans un seul établissement.")
    mine = set(_covered(me, all_ids))
    if not set(ids) <= mine:
        raise HTTPException(status_code=403, detail="Vous ne pouvez attribuer que vos propres établissements.")
    return ids


def _display_name(u: Dict[str, Any]) -> str:
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    if name:
        return name
    local = (u.get("email") or "").split("@")[0]
    return re.sub(r"[._-]+", " ", local).strip().title() or "Utilisateur"


def _public(u: Dict[str, Any], me: Dict[str, Any], all_ids: List[str], store_names: Dict[str, str]) -> Dict[str, Any]:
    role = u.get("role")
    covered = _covered(u, all_ids)
    perms = [p["label"] for p in PERMISSIONS if MATRIX.get(role, {}).get(p["key"])]
    if role == "business_owner":
        perms = ["Accès complet"]
    last = u.get("last_login_at")
    return {
        "id": u.get("id") or u.get("email"),
        "email": u.get("email"), "name": _display_name(u),
        "first_name": u.get("first_name") or "", "last_name": u.get("last_name") or "",
        "role": role, "role_label": ROLE_META.get(role, {}).get("label", role),
        "branch_ids": covered,
        "stores_label": "Tous" if role == "business_owner" or set(all_ids) <= set(covered)
        and len(all_ids) > 1 else ", ".join(store_names.get(b, b) for b in covered),
        "permissions": perms,
        "active": u.get("active", True) is not False,
        "last_login_at": last.isoformat() if isinstance(last, datetime) else (last or None),
        "created_at": u["created_at"].isoformat() if isinstance(u.get("created_at"), datetime) else None,
        "created_by": u.get("created_by") or None,
        "pending": not last,
        "is_me": u.get("email") == me.get("email"),
        "manageable": _can_manage(me, u, all_ids),
    }


def _find(tid: str, uid: str) -> Dict[str, Any]:
    u = _db.users.find_one({"tenant_id": tid, "$or": [{"id": uid}, {"email": uid}]}, {"_id": 0})
    if not u or u.get("role") not in ROLES:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    return u


def _payload(token: TokenData) -> Dict[str, Any]:
    me = _me(token)
    tid = token.tenant_id
    st = stores(tid)
    all_ids = [s["id"] for s in st]
    names = {s["id"]: s["name"] for s in st}
    users = list(_db.users.find({"tenant_id": tid, "role": {"$in": ROLES}}, {"_id": 0, "hashed_password": 0}))
    shown = [u for u in users if _visible(me, u, all_ids)]
    shown.sort(key=lambda u: (RANK.get(u.get("role"), 9), _display_name(u).lower()))
    rows = [_public(u, me, all_ids, names) for u in shown]
    counts = {r: sum(1 for u in shown if u.get("role") == r) for r in ROLES}
    mine = _covered(me, all_ids)
    return {
        "me": {"email": me.get("email"), "role": me.get("role"), "branch_ids": mine,
               "can_create": creatable(me.get("role")), "scope": scope_of(me)},
        "stores": [s for s in st if s["id"] in mine],
        "all_stores_count": len(st),
        "roles": [{"key": r, **ROLE_META[r], "count": counts[r]} for r in ROLES],
        "users": rows,
        # Accounts handed out but never used — owners are not "invited".
        "pending": [r for r in rows if r["pending"] and not r["is_me"] and r["role"] != "business_owner"],
        "permissions": PERMISSIONS,
        "matrix": MATRIX,
        "notes": NOTES,
    }


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
READERS = ["business_owner", "administrateur", "manager"]


@router.get("/api/owner/team-access")
def get_team(token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _payload(token)


class UserIn(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    role: str
    branch_ids: List[str] = []
    password: Optional[str] = None


def _clean_names(body: UserIn) -> Dict[str, str]:
    first, last = (body.first_name or "").strip(), (body.last_name or "").strip()
    if len(first) > NAME_MAX or len(last) > NAME_MAX:
        raise HTTPException(status_code=400, detail="Nom trop long.")
    return {"first_name": first, "last_name": last}


@router.post("/api/owner/team-access/users")
def create_user(body: UserIn, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    if body.role not in creatable(me.get("role")):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas créer ce rôle.")
    email = (body.email or "").strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Adresse email invalide.")
    if _db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")
    ids = _check_assignment(body.role, body.branch_ids, me, all_ids)
    from services import password_policy
    password = (body.password or "").strip() or password_policy.generate()
    password_policy.assert_valid(password)
    doc = {"id": str(uuid.uuid4()), "email": email, "role": body.role, "tenant_id": token.tenant_id,
           **_clean_names(body), "branch_ids": ids, "active": True, "auth_provider": "password",
           "hashed_password": hash_password(password), "created_at": _now(),
           "created_by": me.get("email")}
    _db.users.insert_one(doc)
    return {"credentials": {"email": email, "password": password}, **_payload(token)}


class UserUpdate(BaseModel):
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    role: Optional[str] = None
    branch_ids: Optional[List[str]] = None


@router.put("/api/owner/team-access/users/{uid}")
def update_user(uid: str, body: UserUpdate, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce compte.")
    role = body.role or u["role"]
    if role not in creatable(me.get("role")):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas attribuer ce rôle.")
    ids = _check_assignment(role, body.branch_ids if body.branch_ids is not None
                            else _covered(u, all_ids), me, all_ids)
    names = _clean_names(UserIn(role=role, first_name=body.first_name, last_name=body.last_name))
    _db.users.update_one({"email": u["email"]}, {"$set": {**names, "role": role, "branch_ids": ids,
                                                         "updated_at": _now()}})
    return _payload(token)


class StatusIn(BaseModel):
    active: bool


@router.post("/api/owner/team-access/users/{uid}/status")
def set_status(uid: str, body: StatusIn, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce compte.")
    _db.users.update_one({"email": u["email"]}, {"$set": {"active": bool(body.active), "updated_at": _now()}})
    return _payload(token)


@router.post("/api/owner/team-access/users/{uid}/password")
def new_password(uid: str, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce compte.")
    from services import password_policy
    password = password_policy.generate()
    _db.users.update_one({"email": u["email"]}, {"$set": {"hashed_password": hash_password(password),
                                                         "updated_at": _now()}})
    return {"credentials": {"email": u["email"], "password": password}, **_payload(token)}


@router.delete("/api/owner/team-access/users/{uid}")
def delete_user(uid: str, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas supprimer ce compte.")
    _db.users.delete_one({"email": u["email"], "tenant_id": token.tenant_id})
    return _payload(token)


class StoreAccessIn(BaseModel):
    enabled: bool


@router.put("/api/owner/team-access/stores/{store_id}/users/{uid}")
def store_access(store_id: str, uid: str, body: StoreAccessIn,
                 token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """Accès par établissement. An administrateur's establishments are a set
    and can be given or taken one by one; a manager or an employé works in
    exactly one, so "giving" one moves them there."""
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce compte.")
    covered = _covered(u, all_ids)
    if u["role"] == "administrateur":
        ids = sorted(set(covered) | {store_id}) if body.enabled else [b for b in covered if b != store_id]
    else:
        if not body.enabled:
            raise HTTPException(status_code=400, detail="Choisissez plutôt son nouvel établissement.")
        ids = [store_id]
    ids = _check_assignment(u["role"], ids, me, all_ids)
    _db.users.update_one({"email": u["email"]}, {"$set": {"branch_ids": ids, "updated_at": _now()}})
    return _payload(token)
