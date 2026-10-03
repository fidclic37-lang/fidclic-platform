"""
Paramètres › « Réinitialiser » — back to how a tab was before its last save
(user, 2026-10-03: « Dernier enregistrement wapas », one button per tab).

Every save of a settings tab first notes the tab as it was (only when the
save really changes something), on a short stack per tab. « Réinitialiser »
puts the newest note back and drops it: pressing again goes one more save
back. Nothing else is touched.

    etablissement     name, contact, sector, description, address and GPS
                      point, legal details, proximity reminder, opening
                      hours and closures, the points de vente's details
                      (a point de vente added since stays)
    regles-clients    the shop's customer rules
    lien-inscription  the signup page's texts and its link name (only if the
                      old name is still free)
    equipe            roles, establishments and active / paused of the
                      accounts that still exist (no account created or
                      deleted, no password)
    donnees           consent, retention, cookies notice, privacy policy
    notifications     sending limits
    preferences       this account's preferences (+ the shop's currency,
                      for the owner)
    api               webhook addresses, events and on / off (a webhook
                      created or deleted since is left as it is)

Sécurité and Abonnement have no reset: a password, two-step login, a payment
or a cancellation is not a setting to put back.

Routes:
    GET  /api/owner/settings-versions/{section}          what a reset would bring back
    POST /api/owner/settings-versions/{section}/revert   do it
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_role
from models import TokenData

router = APIRouter(tags=["settings-versions"])
_db = None

KEEP = 20                         # notes kept per tab
ALL_ROLES = ["business_owner", "administrateur", "manager", "staff"]


def init(db):
    global _db
    _db = db
    try:
        db.settings_versions.create_index([("tenant_id", 1), ("section", 1), ("owner", 1), ("at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tenant(tid: str) -> Dict[str, Any]:
    return _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}


_MISSING = "__absent__"


def _fields(doc: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
    return {k: copy.deepcopy(doc[k]) if k in doc else _MISSING for k in keys}


def _set_fields(collection, query: Dict[str, Any], data: Dict[str, Any]) -> None:
    sets = {k: v for k, v in data.items() if v != _MISSING}
    unsets = {k: "" for k, v in data.items() if v == _MISSING}
    upd: Dict[str, Any] = {}
    if sets:
        upd["$set"] = sets
    if unsets:
        upd["$unset"] = unsets
    if upd:
        collection.update_one(query, upd)


# ---------------------------------------------------------------------------
# what each tab is, and how to put it back
# ---------------------------------------------------------------------------
ET_FIELDS = ["name", "phone", "email", "sector", "description", "street", "postal_code", "city", "address",
             "lat", "lng", "pin_source", "legal_name", "siret", "siren", "vat_number", "geo_enabled",
             "geo_radius_meters", "geo_cooldown_days", "weekly_schedule", "holiday_closures", "annual_closures"]
BRANCH_FIELDS = ["name", "street", "postal_code", "city", "phone", "address", "latitude", "longitude", "status"]


def _cap_etablissement(tok: TokenData) -> Dict[str, Any]:
    t = _tenant(tok.tenant_id)
    return {"tenant": _fields(t, ET_FIELDS),
            "branches": {b["id"]: _fields(b, BRANCH_FIELDS) for b in t.get("branches") or [] if b.get("id")}}


def _put_etablissement(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    _set_fields(_db.tenants, {"id": tok.tenant_id}, data.get("tenant") or {})
    t = _tenant(tok.tenant_id)
    old = data.get("branches") or {}
    branches = []
    for b in t.get("branches") or []:
        before = old.get(b.get("id"))
        if before is not None:
            b = {**{k: v for k, v in b.items() if k not in BRANCH_FIELDS},
                 **{k: v for k, v in before.items() if v != _MISSING}}
        branches.append(b)
    if t.get("branches") is not None:
        _db.tenants.update_one({"id": tok.tenant_id}, {"$set": {"branches": branches}})
    return []


def _cap_rules(tok: TokenData) -> Dict[str, Any]:
    from features import customer_rules as CR
    return {"rules": CR.load(tok.tenant_id)}


def _put_rules(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    from features import customer_rules as CR
    CR._save(tok.tenant_id, copy.deepcopy(data.get("rules") or CR.defaults()))
    return []


def _cap_join(tok: TokenData) -> Dict[str, Any]:
    t = _tenant(tok.tenant_id)
    return {"slug": t.get("slug"), "join_page": copy.deepcopy(t.get("join_page", _MISSING))}


def _put_join(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    notes: List[str] = []
    _set_fields(_db.tenants, {"id": tok.tenant_id}, {"join_page": data.get("join_page", _MISSING)})
    t = _tenant(tok.tenant_id)
    old, now = data.get("slug"), t.get("slug")
    if old and old != now:
        from features import join_link as JL
        check = JL.check_slug(old, tok.tenant_id)
        if check.get("available"):
            upd: Dict[str, Any] = {"$set": {"slug": check["slug"], "slug_updated_at": _now()}}
            if now:
                upd["$addToSet"] = {"previous_slugs": now}
            _db.tenants.update_one({"id": tok.tenant_id}, upd)
            _db.tenants.update_one({"id": tok.tenant_id}, {"$pull": {"previous_slugs": check["slug"]}})
        else:
            notes.append(f"Le lien « {old} » n'est plus disponible : le lien actuel est conservé.")
    return notes


TEAM_FIELDS = ["role", "branch_ids", "active", "first_name", "last_name"]


def _cap_team(tok: TokenData) -> Dict[str, Any]:
    users = _db.users.find({"tenant_id": tok.tenant_id, "role": {"$ne": "super_admin"}}, {"_id": 0})
    # A list, not a dict keyed by e-mail: a field name may not hold a dot.
    return {"users": sorted(({"email": u["email"], "fields": _fields(u, TEAM_FIELDS)} for u in users if u.get("email")),
                            key=lambda x: x["email"])}


def _put_team(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    for row in data.get("users") or []:
        q = {"email": row.get("email"), "tenant_id": tok.tenant_id}
        if row.get("email") and _db.users.find_one(q, {"_id": 1}):
            _set_fields(_db.users, q, row.get("fields") or {})
    return []


def _cap_privacy(tok: TokenData) -> Dict[str, Any]:
    return _fields(_tenant(tok.tenant_id), ["privacy"])


def _put_privacy(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    _set_fields(_db.tenants, {"id": tok.tenant_id}, data)
    return []


def _cap_send(tok: TokenData) -> Dict[str, Any]:
    return _fields(_tenant(tok.tenant_id), ["send_rules"])


def _put_send(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    _set_fields(_db.tenants, {"id": tok.tenant_id}, data)
    return []


def _cap_prefs(tok: TokenData) -> Dict[str, Any]:
    u = _db.users.find_one({"email": tok.email}, {"_id": 0, "preferences": 1}) or {}
    out = {"user": _fields(u, ["preferences"])}
    if getattr(tok, "role", None) == "business_owner":
        out["tenant"] = _fields(_tenant(tok.tenant_id), ["currency"])
    return out


def _put_prefs(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    _set_fields(_db.users, {"email": tok.email}, data.get("user") or {})
    if "tenant" in data and getattr(tok, "role", None) == "business_owner":
        _set_fields(_db.tenants, {"id": tok.tenant_id}, data["tenant"])
    return []


HOOK_FIELDS = ["url", "events", "active"]


def _cap_hooks(tok: TokenData) -> Dict[str, Any]:
    return {"hooks": {h["id"]: _fields(h, HOOK_FIELDS)
                      for h in _db.webhooks.find({"tenant_id": tok.tenant_id}, {"_id": 0}) if h.get("id")}}


def _put_hooks(tok: TokenData, data: Dict[str, Any]) -> List[str]:
    for hid, fields in (data.get("hooks") or {}).items():
        _set_fields(_db.webhooks, {"id": hid, "tenant_id": tok.tenant_id}, fields)
    return []


SECTIONS: Dict[str, Dict[str, Any]] = {
    "etablissement": {"label": "Établissement", "cap": _cap_etablissement, "put": _put_etablissement,
                      "roles": ["business_owner"], "per_user": False},
    "regles-clients": {"label": "Règles clients", "cap": _cap_rules, "put": _put_rules,
                       "roles": ["business_owner"], "per_user": False},
    "lien-inscription": {"label": "Lien d'inscription & QR", "cap": _cap_join, "put": _put_join,
                         "roles": ["business_owner"], "per_user": False},
    "equipe": {"label": "Équipe & accès", "cap": _cap_team, "put": _put_team,
               "roles": ["business_owner"], "per_user": False},
    "donnees": {"label": "Données & confidentialité", "cap": _cap_privacy, "put": _put_privacy,
                "roles": ["business_owner"], "per_user": False},
    "notifications": {"label": "Notifications", "cap": _cap_send, "put": _put_send,
                      "roles": ["business_owner"], "per_user": False},
    "preferences": {"label": "Préférences", "cap": _cap_prefs, "put": _put_prefs,
                    "roles": ALL_ROLES, "per_user": True},
    "api": {"label": "APIs & Intégrations", "cap": _cap_hooks, "put": _put_hooks,
            "roles": ["business_owner"], "per_user": False},
}


def _owner_key(section: str, tok: TokenData) -> Optional[str]:
    return tok.email if SECTIONS[section]["per_user"] else None


def _query(section: str, tok: TokenData) -> Dict[str, Any]:
    return {"tenant_id": tok.tenant_id, "section": section, "owner": _owner_key(section, tok)}


# ---------------------------------------------------------------------------
# noting the tab before a save
# ---------------------------------------------------------------------------
@contextmanager
def recorded(tok: TokenData, section: str):
    """Wrap a save: the tab as it was is kept if the save changed it.

        with SV.recorded(token_data, "etablissement"):
            ... the save ...
    """
    if _db is None or section not in SECTIONS:
        yield
        return
    spec = SECTIONS[section]
    try:
        before = spec["cap"](tok)
    except Exception as exc:                      # never let a note block a save
        print(f"settings_versions: capture {section} failed ({exc})")
        before = None
    yield
    if before is None:
        return
    try:
        after = spec["cap"](tok)
        if after == before:
            return
        _db.settings_versions.insert_one({
            **_query(section, tok), "data": before, "at": _now(),
            "by": getattr(tok, "email", None),
        })
        old = list(_db.settings_versions.find(_query(section, tok), {"_id": 1}).sort("at", -1).skip(KEEP))
        if old:
            _db.settings_versions.delete_many({"_id": {"$in": [o["_id"] for o in old]}})
    except Exception as exc:
        print(f"settings_versions: note {section} failed ({exc})")


def records(section: str, token_arg: str = "token_data"):
    """Decorator for a save endpoint (under its @router line):

        @router.put("/api/owner/privacy")
        @SV.records("donnees")
        def put_privacy(body, token_data=Depends(...)): ...

    FastAPI reads the wrapped function's signature (functools.wraps)."""
    import functools

    def deco(fn: Callable):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            tok = kwargs.get(token_arg)
            if tok is None:
                return fn(*args, **kwargs)
            with recorded(tok, section):
                return fn(*args, **kwargs)
        # The endpoint's modules use `from __future__ import annotations`: hand
        # FastAPI the signature with its types already resolved, or it would
        # look for them (EtablissementIn, …) in this module.
        import inspect
        inner.__signature__ = inspect.signature(fn, eval_str=True)
        return inner
    return deco


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------
def _check(section: str, tok: TokenData) -> Dict[str, Any]:
    spec = SECTIONS.get(section)
    if not spec:
        raise HTTPException(status_code=404, detail="Cette section n'a pas de réinitialisation.")
    if getattr(tok, "role", None) not in spec["roles"]:
        raise HTTPException(status_code=403, detail="Seul le propriétaire peut réinitialiser cette section.")
    return spec


def _who(email: Optional[str], tid: str) -> Optional[str]:
    if not email:
        return None
    u = _db.users.find_one({"email": email, "tenant_id": tid}, {"_id": 0, "first_name": 1, "last_name": 1, "name": 1})
    if not u:
        return email
    name = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or u.get("name")
    return name or email


def _aware(d: Any) -> Optional[datetime]:
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return None


@router.get("/api/owner/settings-versions/{section}")
def status(section: str, token_data: TokenData = Depends(require_role(ALL_ROLES, partial_ok=True))):
    spec = SECTIONS.get(section)
    if not spec:
        return {"section": section, "supported": False, "allowed": False, "available": False}
    allowed = getattr(token_data, "role", None) in spec["roles"]
    last = _db.settings_versions.find_one(_query(section, token_data), {"_id": 0}, sort=[("at", -1)]) if allowed else None
    count = _db.settings_versions.count_documents(_query(section, token_data)) if allowed else 0
    at = _aware(last.get("at")) if last else None
    return {"section": section, "label": spec["label"], "supported": True, "allowed": allowed,
            "available": bool(last), "count": count,
            "saved_at": at.isoformat() if at else None,
            "saved_by": _who(last.get("by"), token_data.tenant_id) if last else None}


@router.post("/api/owner/settings-versions/{section}/revert")
def revert(section: str, token_data: TokenData = Depends(require_role(ALL_ROLES, partial_ok=True))):
    spec = _check(section, token_data)
    last = _db.settings_versions.find_one(_query(section, token_data), sort=[("at", -1)])
    if not last:
        raise HTTPException(status_code=400, detail="Aucun enregistrement à annuler dans cette section.")
    notes = spec["put"](token_data, last.get("data") or {}) or []
    _db.settings_versions.delete_one({"_id": last["_id"]})
    try:
        from server import log_audit
        log_audit("settings.reverted", actor=getattr(token_data, "email", None), actor_type="user",
                  tenant_id=token_data.tenant_id, target=section,
                  meta={"to": (_aware(last.get("at")) or _now()).isoformat()})
    except Exception:
        pass
    return {"ok": True, "notes": notes, **status(section, token_data=token_data)}
