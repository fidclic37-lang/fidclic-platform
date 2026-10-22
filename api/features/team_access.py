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
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["team-access"])
_db = None

# « membre »: an account in a role the owner created (features/role_perms) —
# below the administrateur, beside the manager.
ROLES = ["business_owner", "administrateur", "manager", "membre", "staff"]
RANK = {"business_owner": 0, "administrateur": 1, "manager": 2, "membre": 2, "staff": 3}
TEAM_ROLES = ["administrateur", "manager", "membre", "staff"]
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
    "membre": {"label": "Rôle personnalisé", "tone": "slate", "icon": "badge",
               "description": "Les pages et les établissements choisis par le propriétaire."},
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


def role_label(user: Dict[str, Any]) -> str:
    from features import role_perms as RP
    if user.get("role") == RP.CUSTOM_ROLE:
        return (RP.templates(user.get("tenant_id")).get(user.get("custom_role") or "") or {}).get("label") \
            or ROLE_META["membre"]["label"]
    return ROLE_META.get(user.get("role"), {}).get("label", user.get("role") or "")


def identity(user: Dict[str, Any]) -> Dict[str, Any]:
    if not user or user.get("role") not in ROLES or not user.get("tenant_id"):
        return {}
    from features import role_perms as RP
    all_ids = [s["id"] for s in stores(user["tenant_id"])]
    return {"branch_ids": _covered(user, all_ids), "scope": scope_of(user),
            "role_label": role_label(user),
            # « Peut changer d'établissement » — read by the sidebar's switcher
            # and the Scan page (src/lib/storeSwitch.js)
            **({"can_switch_store": bool(user["can_switch_store"])}
               if isinstance(user.get("can_switch_store"), bool) else {}),
            # the sidebar: this account's pages per establishment (None: the role's usual menu)
            "page_perms": RP.nav_for(user)}


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


def assignable(me: Dict[str, Any]) -> List[str]:
    """The roles this account may give (a built-in key or a custom role's key):
    the roles BELOW its own in the role tree (role_perms.below, 2026-10-22)."""
    from features import role_perms as RP
    return RP.below(me.get("tenant_id"), RP.my_key(me))


def _can_manage(me: Dict[str, Any], other: Dict[str, Any], all_ids: List[str]) -> bool:
    from features import role_perms as RP
    if other.get("email") == me.get("email") or other.get("role") == "business_owner":
        return False
    if me.get("role") == "business_owner":
        return True
    # an account in a role below one's own (any depth) — never one's own
    # role, a sibling's or a role above (user, 2026-10-22)
    if (RP.role_key(other) or other.get("role")) not in assignable(me):
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
    if role == "membre" and not ids:
        raise HTTPException(status_code=400, detail="Choisissez au moins un établissement.")
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
    from features import role_perms as RP
    role = u.get("role")
    covered = _covered(u, all_ids)
    eff = RP.effective(u)
    perms = [p["label"] for p in RP.PAGES
             if any(RP.RANKV[(lv or {}).get(p["key"], "none")] >= 1 for lv in (eff or {}).values())]
    if role == "business_owner":
        perms = ["Accès complet"]
    last = u.get("last_login_at")
    return {
        "id": u.get("id") or u.get("email"),
        "email": u.get("email"), "name": _display_name(u),
        "first_name": u.get("first_name") or "", "last_name": u.get("last_name") or "",
        "role": role, "role_label": role_label(u),
        "role_key": RP.role_key(u) or role, "custom_role": u.get("custom_role"),
        # per establishment {page: none|view|edit}; None for the owner (everything)
        "perms": eff, "own_perms": isinstance(u.get("perms"), dict),
        "branch_ids": covered,
        "can_switch_store": u.get("can_switch_store"),
        "switches_store": (u.get("can_switch_store") if isinstance(u.get("can_switch_store"), bool)
                           else role in ("business_owner", "administrateur")),
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
    everyone = [u for u in users if _visible(me, u, all_ids)]
    everyone.sort(key=lambda u: (RANK.get(u.get("role"), 9), _display_name(u).lower()))
    # The establishment chosen in the menu (user, 2026-10-14: « jisko jo stores
    # alloted hai, woh keval usi stores k roles and access mein dikhe »): the
    # list, the role counts and the pending invitations are its team — the
    # owner and the accounts that have it. « Accès par établissement » still
    # lists everyone (all_users): it is where a store is given or taken.
    sel = None
    if len(all_ids) > 1:
        from features import store_cards as SC
        sid = SC.store_for(tid)
        sel = sid if sid in all_ids else None
    shown = [u for u in everyone if sel is None or u.get("role") == "business_owner"
             or u.get("email") == me.get("email") or sel in _covered(u, all_ids)]
    rows = [_public(u, me, all_ids, names) for u in shown]
    all_rows = rows if sel is None else [_public(u, me, all_ids, names) for u in everyone]
    counts = {r: sum(1 for u in shown if u.get("role") == r) for r in ROLES}
    mine = _covered(me, all_ids)
    from features import role_perms as RP
    tpls = RP.templates(tid)
    custom_counts: Dict[str, int] = {}
    for u in shown:
        if u.get("role") == RP.CUSTOM_ROLE:
            custom_counts[u.get("custom_role") or ""] = custom_counts.get(u.get("custom_role") or "", 0) + 1
    return {
        "me": {"email": me.get("email"), "role": me.get("role"), "branch_ids": mine,
               "can_create": [r for r in TEAM_ROLES if r != "membre" and r in assignable(me)],
               "can_assign_custom": any(k not in RP.BUILTIN for k in assignable(me)),
               # the roles it may give, and the role definitions it may change (role tree)
               "assignable_roles": assignable(me), "manageable_roles": RP.manageable_roles(me),
               "scope": scope_of(me),
               # what the creator may hand out (an account never gets more), None: everything
               "perms": RP.effective(me),
               "can_define_roles": RP.can_define_roles(me)},
        "stores": [s for s in st if s["id"] in mine],
        "all_stores_count": len(st),
        "roles": [{"key": r, **ROLE_META[r], "count": counts[r]} for r in ROLES if r != "membre"]
        + [{"key": k, "label": d["label"], "tone": "slate", "icon": "badge", "custom": True,
            "description": d.get("description") or "Rôle personnalisé.", "count": custom_counts.get(k, 0)}
           for k, d in tpls.items() if not d["builtin"]],
        # Rôles et permissions par page: the pages, every role's template
        "pages": RP.PAGES,
        "templates": list(tpls.values()),
        "users": rows,
        "all_users": all_rows,
        "store_id": sel,
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


def _audit(action: str, token: TokenData, target: str) -> None:
    """Shown on Paramètres › Sécurité › Activités récentes."""
    try:
        from server import log_audit
        log_audit(action, actor=token.email, actor_type="user", tenant_id=token.tenant_id, target=target)
    except Exception:
        pass


@router.get("/api/owner/team-access")
def get_team(token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _payload(token)


class UserIn(BaseModel):
    email: Optional[str] = None
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    role: str                                  # a built-in role, or a role the owner created (its key)
    branch_ids: List[str] = []
    password: Optional[str] = None
    perms: Optional[Dict[str, Any]] = None     # {store: {page: none|view|edit}} — else the role's template


def _system_role(tid: str, role: str):
    """(system role, custom role key) of what was chosen."""
    from features import role_perms as RP
    if role in ROLES:
        if role == RP.CUSTOM_ROLE:
            raise HTTPException(status_code=400, detail="Choisissez un rôle.")
        return role, None
    if role in RP.templates(tid) and not RP.templates(tid)[role]["builtin"]:
        return RP.CUSTOM_ROLE, role
    raise HTTPException(status_code=400, detail="Rôle inconnu.")


def _perms_for(tid: str, role_k: str, ids: List[str], raw: Optional[Dict[str, Any]],
               me: Dict[str, Any], keep: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Dict[str, str]]]:
    """The account's permissions per establishment: what was sent, else what it
    had there, else its role's template. Never more than the creator has."""
    from features import role_perms as RP
    tpl = RP.templates(tid).get(role_k) or {}
    if raw is None and keep is None and tpl.get("builtin") and not tpl.get("customized"):
        return None                            # the role's usual rules, as before
    if raw is not None and not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="Permissions invalides.")
    out = {}
    for sid in ids:
        if raw is not None and sid in raw:
            out[sid] = RP.clean_perms(raw[sid])
        elif keep and isinstance(keep.get(sid), dict):
            out[sid] = RP.clean_perms(keep[sid])
        else:
            out[sid] = RP.clean_perms(tpl.get("perms") or {})
    over = RP.within(out, RP.effective(me))
    if over:
        raise HTTPException(status_code=403, detail=f"Vous ne pouvez pas donner plus que vos propres droits : « {RP.LABEL[over]} ».")
    return out


def _clean_names(body: UserIn) -> Dict[str, str]:
    first, last = (body.first_name or "").strip(), (body.last_name or "").strip()
    if len(first) > NAME_MAX or len(last) > NAME_MAX:
        raise HTTPException(status_code=400, detail="Nom trop long.")
    return {"first_name": first, "last_name": last}


@router.post("/api/owner/team-access/users")
def create_user(body: UserIn, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    sys_role, custom = _system_role(token.tenant_id, body.role)
    if (custom or sys_role) not in assignable(me):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas créer ce rôle.")
    from services import email_check   # a copied address's invisible characters (2026-10-14)
    email = email_check.clean(body.email)
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=400, detail="Adresse email invalide.")
    if _db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cet email.")
    from features import plan_limits
    f = plan_limits.tenant_features(token.tenant_id)
    cap = int(f.get("staff_accounts") or 0)
    if cap and _db.users.count_documents({"tenant_id": token.tenant_id}) >= cap:
        raise HTTPException(status_code=403, detail={**plan_limits.locked(f, "staff_accounts"),
                            "message": f"Votre offre {f.get('label')} inclut {cap} comptes équipe (propriétaire compris).",
                            "upgrade": plan_limits._next_bigger(f, "staff_accounts")})
    ids = _check_assignment(sys_role, body.branch_ids, me, all_ids)
    perms = _perms_for(token.tenant_id, custom or sys_role, ids, body.perms, me)
    from services import password_policy
    password = (body.password or "").strip() or password_policy.generate()
    password_policy.assert_valid(password)
    doc = {"id": str(uuid.uuid4()), "email": email, "role": sys_role, "tenant_id": token.tenant_id,
           **({"custom_role": custom} if custom else {}), **({"perms": perms} if perms is not None else {}),
           **_clean_names(body), "branch_ids": ids, "active": True, "auth_provider": "password",
           "hashed_password": hash_password(password), "created_at": _now(),
           "created_by": me.get("email")}
    _db.users.insert_one(doc)
    _audit("team.user_created", token, email)
    return {"credentials": {"email": email, "password": password}, **_payload(token)}


class UserUpdate(BaseModel):
    first_name: Optional[str] = ""
    last_name: Optional[str] = ""
    role: Optional[str] = None
    branch_ids: Optional[List[str]] = None
    perms: Optional[Dict[str, Any]] = None
    # « Peut changer d'établissement » (user, 2026-10-14). Unset = the role
    # decides: the owner and an administrateur choose, the others work where
    # they are. Set, it wins — that is how the owner hands the choice to one
    # account without changing its role.
    can_switch_store: Optional[bool] = None


@router.put("/api/owner/team-access/users/{uid}")
@SV.records("equipe", token_arg="token")
def update_user(uid: str, body: UserUpdate, token: TokenData = Depends(require_role(READERS, partial_ok=True))):
    me = _me(token)
    all_ids = [s["id"] for s in stores(token.tenant_id)]
    u = _find(token.tenant_id, uid)
    if not _can_manage(me, u, all_ids):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas modifier ce compte.")
    from features import role_perms as RP
    chosen = body.role or RP.role_key(u) or u["role"]
    role, custom = _system_role(token.tenant_id, chosen)
    if (custom or role) not in assignable(me):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas attribuer ce rôle.")
    ids = _check_assignment(role, body.branch_ids if body.branch_ids is not None
                            else _covered(u, all_ids), me, all_ids)
    same_role = (custom or role) == (RP.role_key(u) or u["role"])
    keep = u.get("perms") if same_role and isinstance(u.get("perms"), dict) else None
    perms = _perms_for(token.tenant_id, custom or role, ids, body.perms, me, keep=keep)
    names = _clean_names(UserIn(role=role, first_name=body.first_name, last_name=body.last_name))
    sets = {**names, "role": role, "branch_ids": ids, "updated_at": _now()}
    # Only the owner and an administrateur hand out the choice of establishment
    # — and never to themselves beyond what their role already gives.
    if body.can_switch_store is None:
        unset_switch = True
    else:
        unset_switch = False
        sets["can_switch_store"] = bool(body.can_switch_store)
    unset = {}
    if custom:
        sets["custom_role"] = custom
    else:
        unset["custom_role"] = ""
    if perms is not None:
        sets["perms"] = perms
    else:
        unset["perms"] = ""
    if unset_switch:
        unset["can_switch_store"] = ""      # back to what the role says
    _db.users.update_one({"email": u["email"]}, {"$set": sets, **({"$unset": unset} if unset else {})})
    _audit("team.user_updated", token, u["email"])
    return _payload(token)


class StatusIn(BaseModel):
    active: bool


@router.post("/api/owner/team-access/users/{uid}/status")
@SV.records("equipe", token_arg="token")
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
                                                         "updated_at": _now(), "password_changed_at": _now()}})
    # The old password stops working everywhere, at once.
    try:
        from features.security_page import revoke
        revoke({"email": u["email"]})
    except Exception:
        pass
    _audit("team.password_reset", token, u["email"])
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
@SV.records("equipe", token_arg="token")
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
    if u["role"] in ("administrateur", "membre"):
        ids = sorted(set(covered) | {store_id}) if body.enabled else [b for b in covered if b != store_id]
    else:
        if not body.enabled:
            raise HTTPException(status_code=400, detail="Choisissez plutôt son nouvel établissement.")
        ids = [store_id]
    ids = _check_assignment(u["role"], ids, me, all_ids)
    sets: Dict[str, Any] = {"branch_ids": ids, "updated_at": _now()}
    if isinstance(u.get("perms"), dict):       # a new establishment starts with the role's template
        from features import role_perms as RP
        sets["perms"] = _perms_for(token.tenant_id, RP.role_key(u) or u["role"], ids, None, me, keep=u["perms"])
    _db.users.update_one({"email": u["email"]}, {"$set": sets})
    return _payload(token)


# ---------------------------------------------------------------------------
# roles (the owner only): create, change a template, delete a role
# ---------------------------------------------------------------------------
class RoleIn(BaseModel):
    label: Optional[str] = None
    description: Optional[str] = None
    perms: Optional[Dict[str, Any]] = None     # {page: none|view|edit}; None on a built-in role: back to its defaults
    apply: str = "new"                         # "new": accounts created from now · "all": every account in it


def _role_label(raw: Optional[str], tid: str, skip: Optional[str] = None) -> str:
    from features import role_perms as RP
    label = re.sub(r"\s+", " ", raw or "").strip()
    if not 2 <= len(label) <= 40:
        raise HTTPException(status_code=400, detail="Nom du rôle : 2 à 40 caractères.")
    taken = {d["label"].lower() for k, d in RP.templates(tid).items() if k != skip} | {"propriétaire"}
    if label.lower() in taken:
        raise HTTPException(status_code=400, detail="Un rôle porte déjà ce nom.")
    return label


def _apply_to_accounts(tid: str, key: str, perms: Dict[str, str]) -> int:
    from features import role_perms as RP
    q = {"tenant_id": tid, **({"role": RP.CUSTOM_ROLE, "custom_role": key} if key not in RP.BUILTIN else {"role": key})}
    all_ids = [s["id"] for s in stores(tid)]
    n = 0
    for u in _db.users.find(q, {"_id": 0, "email": 1, "branch_ids": 1, "role": 1}):
        ids = _covered(u, all_ids)
        _db.users.update_one({"email": u["email"]}, {"$set": {"perms": {sid: dict(perms) for sid in ids},
                                                             "updated_at": _now()}})
        n += 1
    return n


def _freeze(tid: str, key: str, old_perms: Dict[str, str]) -> None:
    from features import role_perms as RP
    q = {"tenant_id": tid, "perms": {"$exists": False},
         **({"role": RP.CUSTOM_ROLE, "custom_role": key} if key not in RP.BUILTIN else {"role": key})}
    all_ids = [s["id"] for s in stores(tid)]
    for u in _db.users.find(q, {"_id": 0, "email": 1, "branch_ids": 1, "role": 1}):
        _db.users.update_one({"email": u["email"]}, {"$set": {
            "perms": {sid: dict(old_perms) for sid in _covered(u, all_ids)}}})


def _role_guard(token: TokenData, key: Optional[str], perms: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """« Créer et modifier les rôles » (a permission, 2026-10-22): a new role
    goes under one's own; an existing one must be below it; and a role never
    gets more than its author has."""
    from features import role_perms as RP
    me = _me(token)
    if not RP.can_define_roles(token):
        raise HTTPException(status_code=403, detail="Accès non autorisé : vous ne pouvez pas modifier « Créer et modifier les rôles ».")
    if key is not None and key not in RP.manageable_roles(me):
        raise HTTPException(status_code=403, detail="Ce rôle n'est pas sous le vôtre : seul un rôle au-dessus peut le modifier.")
    if perms is not None and me.get("role") != "business_owner":
        # a role is for any establishment: never more than the author has in
        # the least of its own
        eff = RP.effective(me) or {}
        least = {k: min((p.get(k, "none") for p in eff.values()), key=lambda v: RP.RANKV[v], default="none")
                 for k in RP.PAGE_KEYS}
        over = RP.within({"x": perms}, {"x": least})
        if over:
            raise HTTPException(status_code=403, detail=f"Vous ne pouvez pas donner plus que vos propres droits : « {RP.LABEL[over]} ».")
    return me


@router.post("/api/owner/team-access/roles")
@SV.records("equipe", token_arg="token")
def create_role(body: RoleIn, token: TokenData = Depends(require_role(["business_owner"], partial_ok=True))):
    from features import role_perms as RP
    tid = token.tenant_id
    label = _role_label(body.label, tid)
    key = RP.new_role_key()
    perms = RP.clean_perms(body.perms or {})
    me = _role_guard(token, None, perms)
    _db.tenants.update_one({"id": tid}, {"$set": {f"role_defs.{key}": {
        "label": label, "description": (body.description or "").strip()[:160], "perms": perms,
        "parent": RP.my_key(me),                 # its place in the role tree
        "created_at": _now(), "created_by": token.email}}})
    _audit("team.role_created", token, label)
    return {"role": key, **_payload(token)}


@router.put("/api/owner/team-access/roles/{key}")
@SV.records("equipe", token_arg="token")
def update_role(key: str, body: RoleIn, token: TokenData = Depends(require_role(["business_owner"], partial_ok=True))):
    from features import role_perms as RP
    tid = token.tenant_id
    tpls = RP.templates(tid)
    if key not in tpls:
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    if body.apply not in ("new", "all"):
        raise HTTPException(status_code=400, detail="Choisissez à qui appliquer.")
    _role_guard(token, key, RP.clean_perms(body.perms) if body.perms is not None else None)
    sets: Dict[str, Any] = {}
    if key in RP.BUILTIN:
        perms = RP.clean_perms(body.perms) if body.perms is not None else dict(RP.DEFAULT_TEMPLATES[key])
        sets[f"role_defs.{key}.perms"] = perms if body.perms is not None else None
    else:
        if body.label is not None:
            sets[f"role_defs.{key}.label"] = _role_label(body.label, tid, skip=key)
        if body.description is not None:
            sets[f"role_defs.{key}.description"] = body.description.strip()[:160]
        perms = RP.clean_perms(body.perms) if body.perms is not None else tpls[key]["perms"]
        sets[f"role_defs.{key}.perms"] = perms
    sets[f"role_defs.{key}.updated_at"] = _now()
    if body.apply == "new":
        # « Seulement les nouveaux comptes »: the accounts already in this role
        # keep what they had (their own permissions, written down now)
        _freeze(tid, key, tpls[key]["perms"])
    _db.tenants.update_one({"id": tid}, {"$set": sets})
    applied = _apply_to_accounts(tid, key, perms) if body.apply == "all" else 0
    _audit("team.role_updated", token, key)
    return {"applied": applied, **_payload(token)}


@router.delete("/api/owner/team-access/roles/{key}")
@SV.records("equipe", token_arg="token")
def delete_role(key: str, token: TokenData = Depends(require_role(["business_owner"], partial_ok=True))):
    from features import role_perms as RP
    tid = token.tenant_id
    if key in RP.BUILTIN or key not in RP.templates(tid):
        raise HTTPException(status_code=404, detail="Rôle introuvable.")
    _role_guard(token, key, None)
    used = _db.users.count_documents({"tenant_id": tid, "role": RP.CUSTOM_ROLE, "custom_role": key})
    if used:
        raise HTTPException(status_code=400, detail=f"{used} compte{'s' if used > 1 else ''} ont ce rôle : "
                                                    "changez-leur de rôle d'abord.")
    _db.tenants.update_one({"id": tid}, {"$unset": {f"role_defs.{key}": ""}})
    _audit("team.role_deleted", token, key)
    return _payload(token)
