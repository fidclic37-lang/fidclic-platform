"""
Paramètres › Préférences — how FidClic looks and behaves for each account.

Built to the approved mockup, without « Préférences d'affichage » (theme,
density, animations, simplified mode — removed by the user).

    Per account      language, time zone, date format, the e-mails it wants
                     from FidClic, items per page, the page it lands on, how
                     outside links open, confirmation of important actions.
    Per business     the currency amounts are shown in — every currency in the
                     world (decided with the user). Amounts are the shop's own
                     figures, typed in its own currency: the choice changes how
                     they are written, it converts nothing. The owner sets it,
                     the whole team sees it. FidClic's own prices and invoices
                     stay in euros.

Mounts at:
    GET  /api/me/preferences
    PUT  /api/me/preferences
    POST /api/me/preferences/reset
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["preferences"])
_db = None

ROLES = ["business_owner", "administrateur", "manager", "staff"]
LANGUAGES = ("fr", "en", "ar")
DATE_FORMATS = ("dmy", "mdy", "ymd", "dmy_dot")
LINK_TARGETS = ("same", "new")
PER_PAGE = (10, 20, 50, 100)
PAGES = ("/dashboard", "/dashboard/analytics", "/dashboard/customers", "/dashboard/campaigns",
         "/dashboard/scan", "/dashboard/insights", "/dashboard/card")
EMAILS = ("billing", "product", "tips", "alerts", "marketing")
DEFAULTS: Dict[str, Any] = {
    "language": "fr", "timezone": "Europe/Paris", "date_format": "dmy",
    "emails": {"billing": True, "product": True, "tips": True, "alerts": True, "marketing": False},
    "per_page": 20, "default_page": "/dashboard", "link_target": "same", "confirm_actions": True,
}


def init(db):
    global _db
    _db = db


def prefs_for(email: str) -> Dict[str, Any]:
    stored = ((_db.users.find_one({"email": email}, {"_id": 0, "preferences": 1}) or {}).get("preferences") or {})
    out = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS and k != "emails"}}
    out["emails"] = {**DEFAULTS["emails"], **(stored.get("emails") or {})}
    return out


def currency_for(tid: Optional[str]) -> str:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "currency": 1}) if tid else None
    return ((t or {}).get("currency") or "EUR").upper()


def wants_email(email: str, category: str) -> bool:
    """Whether an account wants this kind of e-mail from FidClic."""
    return bool(prefs_for(email)["emails"].get(category, True))


def _view(token: TokenData) -> Dict[str, Any]:
    return {"preferences": prefs_for(token.email), "currency": currency_for(token.tenant_id),
            "can_edit_currency": getattr(token, "role", None) == "business_owner", "defaults": DEFAULTS}


@router.get("/api/me/preferences")
def get_prefs(token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    return _view(token_data)


class EmailsIn(BaseModel):
    billing: Optional[bool] = None
    product: Optional[bool] = None
    tips: Optional[bool] = None
    alerts: Optional[bool] = None
    marketing: Optional[bool] = None


class PrefsIn(BaseModel):
    language: Optional[str] = None
    timezone: Optional[str] = Field(None, max_length=60)
    date_format: Optional[str] = None
    emails: Optional[EmailsIn] = None
    per_page: Optional[int] = None
    default_page: Optional[str] = None
    link_target: Optional[str] = None
    confirm_actions: Optional[bool] = None
    currency: Optional[str] = None


def _valid_timezone(tz: str) -> bool:
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return True
    except Exception:
        return False


@router.put("/api/me/preferences")
@SV.records("preferences")
def put_prefs(body: PrefsIn, token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    sets: Dict[str, Any] = {}
    checks = (("language", LANGUAGES), ("date_format", DATE_FORMATS), ("link_target", LINK_TARGETS),
              ("per_page", PER_PAGE), ("default_page", PAGES))
    for key, allowed in checks:
        v = getattr(body, key)
        if v is not None:
            if v not in allowed:
                raise HTTPException(status_code=400, detail="Valeur non disponible.")
            sets[f"preferences.{key}"] = v
    if body.timezone is not None:
        if not _valid_timezone(body.timezone):
            raise HTTPException(status_code=400, detail="Fuseau horaire inconnu.")
        sets["preferences.timezone"] = body.timezone
    if body.confirm_actions is not None:
        sets["preferences.confirm_actions"] = bool(body.confirm_actions)
    if body.emails:
        for k, v in body.emails.model_dump().items():
            if v is not None:
                sets[f"preferences.emails.{k}"] = bool(v)
    if sets:
        _db.users.update_one({"email": token_data.email}, {"$set": sets})
    if body.currency is not None:
        if getattr(token_data, "role", None) != "business_owner":
            raise HTTPException(status_code=403, detail="Seul le propriétaire choisit la devise du commerce.")
        code = body.currency.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise HTTPException(status_code=400, detail="Devise inconnue.")
        _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"currency": code}})
    return _view(token_data)


@router.post("/api/me/preferences/reset")
@SV.records("preferences")
def reset_prefs(token_data: TokenData = Depends(require_role(ROLES, partial_ok=True))):
    """Back to the defaults — the business's currency is not a preference of
    this account, so it stays."""
    _db.users.update_one({"email": token_data.email}, {"$unset": {"preferences": ""}})
    return _view(token_data)
