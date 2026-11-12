"""
Super admin › Paramètres › Plateforme (user, 2026-11-11), PR 2 of 3.

    signups_open / signups_message   off = no NEW business account (e-mail or
                                     Google/Apple); sign-in and drafts go on
    banner                           {message, level, starts_at, ends_at}: on
                                     every shop's dashboard between its dates
    trial_days                       the trial plan's « trial_duration_days »
                                     — the same override Plan Limits writes
                                     (plan_settings), one figure, two doors
    support_email                    where new support requests are e-mailed
    sender_name / sender_email       the « From » of FidClic's e-mails (Brevo)

Stored in platform_settings {key: "platform"}; read through a 30 s memo per
process. Empty = the built-in value (env, then the code's default).

    GET /api/admin/settings/platform   settings + shortcuts   (Paramètres « Voir »)
    PUT /api/admin/settings/platform   change, journaled      (« Modifier »)
    GET /api/platform/status           public: sign-ups open? the live banner
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from auth import TokenData
from features.platform_access import require_admin

router = APIRouter(tags=["admin"])
_db = None

KEY = "platform"
TTL_S = 30
DEFAULT_SUPPORT = "shuklaakshansh38@gmail.com"
DEFAULT_SIGNUPS_MESSAGE = "Les inscriptions sont fermées pour le moment. Revenez bientôt !"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_memo: Dict[str, Any] = {}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _raw() -> Dict[str, Any]:
    hit = _memo.get("v")
    if hit and time.time() - hit[0] < TTL_S:
        return hit[1]
    v: Dict[str, Any] = {}
    if _db is not None:
        try:
            v = (_db.platform_settings.find_one({"key": KEY}, {"_id": 0, "value": 1}) or {}).get("value") or {}
        except Exception:                                    # noqa: BLE001 — a setting never breaks a request
            v = {}
    _memo["v"] = (time.time(), v)
    return v


def forget() -> None:
    _memo.clear()


# ---------------------------------------------------------------------------
# what the rest of the platform reads
# ---------------------------------------------------------------------------
def signups_open() -> bool:
    return _raw().get("signups_open") is not False


def signups_message() -> str:
    return _raw().get("signups_message") or DEFAULT_SIGNUPS_MESSAGE


def assert_signups_open() -> None:
    """A NEW business account (e-mail sign-up, Google/Apple) — refused while
    sign-ups are closed. Sign-in and drafts already started are not asked."""
    if not signups_open():
        raise HTTPException(status_code=403, detail=signups_message())


def support_recipient() -> str:
    return _raw().get("support_email") or os.getenv("SUPPORT_RECIPIENT_EMAIL") or DEFAULT_SUPPORT


def sender() -> tuple:
    """(email, name) of FidClic's e-mails."""
    v = _raw()
    return (v.get("sender_email") or os.getenv("BREVO_SENDER_EMAIL") or "akshanshshukla963@gmail.com",
            v.get("sender_name") or os.getenv("BREVO_SENDER_NAME") or "FidClic")


def live_banner(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    b = _raw().get("banner")
    if not isinstance(b, dict) or not b.get("message"):
        return None
    now = now or _now()
    start, end = _aware(b.get("starts_at")), _aware(b.get("ends_at"))
    if (start and now < start) or (end and now >= end):
        return None
    bid = hashlib.sha1(f"{b.get('message')}|{b.get('starts_at')}|{b.get('ends_at')}|{b.get('level')}".encode()).hexdigest()[:12]
    return {"id": bid, "message": b["message"], "level": b.get("level") or "info",
            "starts_at": b.get("starts_at"), "ends_at": b.get("ends_at")}


def _trial_plan() -> str:
    from models import TRIAL_PLAN
    return TRIAL_PLAN


def trial_days() -> int:
    import server as core
    return int(core.get_plan_features(_trial_plan()).get("trial_duration_days", 30))


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
class BannerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., max_length=300)
    level: str = "info"
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Le message du bandeau est vide.")
        return v

    @field_validator("level")
    @classmethod
    def _level(cls, v: str) -> str:
        if v not in ("info", "warning"):
            raise ValueError("Niveau : info ou warning.")
        return v

    @model_validator(mode="after")
    def _dates(self):
        a, b = _aware(self.starts_at), _aware(self.ends_at)
        if a and b and b <= a:
            raise ValueError("La fin du bandeau doit être après son début.")
        return self


class PlatformIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signups_open: Optional[bool] = None
    signups_message: Optional[str] = Field(None, max_length=300)
    banner: Optional[BannerIn] = None
    trial_days: Optional[int] = Field(None, ge=1, le=365)
    support_email: Optional[str] = Field(None, max_length=200)
    sender_name: Optional[str] = Field(None, max_length=70)
    sender_email: Optional[str] = Field(None, max_length=200)

    @field_validator("support_email", "sender_email")
    @classmethod
    def _email(cls, v: Optional[str]) -> Optional[str]:
        v = (v or "").strip().lower()
        if not v:
            return None
        if not _EMAIL.match(v):
            raise ValueError("Adresse email invalide.")
        return v


def _view() -> Dict[str, Any]:
    v = _raw()
    email, name = sender()
    b = v.get("banner") if isinstance(v.get("banner"), dict) else None
    return {"signups_open": signups_open(), "signups_message": v.get("signups_message") or "",
            "banner": b, "banner_live": live_banner() is not None,
            "trial_days": trial_days(), "trial_plan": _trial_plan(),
            "support_email": support_recipient(), "support_email_custom": bool(v.get("support_email")),
            "sender_name": name, "sender_email": email, "sender_custom": bool(v.get("sender_email") or v.get("sender_name"))}


def _shortcuts() -> List[Dict[str, Any]]:
    out = []
    try:
        from features import ai_meter as AM
        s = AM.settings()
        mode = "fixe" if s.get("cap_mode") == "fixed" else f"{s.get('per_shop_eur')} € × commerce actif"
        out.append({"key": "ai", "label": "Plafond IA du jour", "value": f"{AM.global_cap():.0f} € / jour ({mode})", "href": "/admin/ai/couts"})
    except Exception:                                        # noqa: BLE001
        out.append({"key": "ai", "label": "Plafond IA du jour", "value": "€ — indisponible", "href": "/admin/ai/couts"})
    out.append({"key": "plans", "label": "Plan Limits", "value": f"Essai : {trial_days()} jours sur le plan {_trial_plan()}",
                "href": "/admin/plans"})
    try:
        from features import platform_security as PS
        s = PS.settings()
        countries = len(s.get("allowed_countries") or [])
        out.append({"key": "security", "label": "Sécurité des connexions",
                    "value": f"{s.get('max_failed')} tentatives, blocage {s.get('lock_minutes')} min"
                             + (f", {countries} pays autorisé{'s' if countries > 1 else ''}" if countries else ", tous pays"),
                    "href": "/admin/securite/parametres"})
    except Exception:                                        # noqa: BLE001
        out.append({"key": "security", "label": "Sécurité des connexions", "value": "tentatives — indisponible", "href": "/admin/securite/parametres"})
    issuer = ((_db.platform_settings.find_one({"key": "invoice_issuer"}, {"_id": 0, "value": 1}) or {}).get("value") or {}) if _db is not None else {}
    out.append({"key": "invoicing", "label": "Émetteur des factures",
                "value": issuer.get("legal_name") or "Non renseigné", "href": "/admin/facturation"})
    return out


@router.get("/api/admin/settings/platform")
def get_platform(token_data: TokenData = Depends(require_admin("parametres"))):
    return {"settings": _view(), "shortcuts": _shortcuts()}


@router.put("/api/admin/settings/platform")
def put_platform(body: PlatformIn, request: Request, token_data: TokenData = Depends(require_admin("parametres"))):
    sent = body.model_dump(exclude_unset=True)
    if not sent:
        raise HTTPException(status_code=400, detail="Rien à enregistrer.")
    cur = dict((_db.platform_settings.find_one({"key": KEY}, {"_id": 0, "value": 1}) or {}).get("value") or {})
    changed = []
    for k, v in sent.items():
        if k == "trial_days":
            continue
        if k == "banner" and v is not None:
            v = {**v, "starts_at": _aware(v.get("starts_at")).isoformat() if v.get("starts_at") else None,
                 "ends_at": _aware(v.get("ends_at")).isoformat() if v.get("ends_at") else None}
        if isinstance(v, str):
            v = v.strip() or None
        if cur.get(k) != v:
            changed.append(k)
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    _db.platform_settings.update_one({"key": KEY}, {"$set": {"key": KEY, "value": cur, "updated_at": _now(),
                                                            "updated_by": token_data.email}}, upsert=True)
    if "trial_days" in sent and sent["trial_days"] is not None and sent["trial_days"] != trial_days():
        plan = _trial_plan()
        over = dict((_db.plan_settings.find_one({"plan": plan}) or {}).get("overrides") or {})
        over["trial_duration_days"] = int(sent["trial_days"])
        _db.plan_settings.update_one({"plan": plan}, {"$set": {"plan": plan, "overrides": over, "updated_at": _now(),
                                                               "updated_by": token_data.email}}, upsert=True)
        changed.append("trial_days")
    forget()
    import server as core
    for k in changed:
        core.log_audit("platform.settings_update", actor=token_data.email, actor_type="user", target=k, request=request,
                       meta={"changed": k, "value": (sent.get(k) if k != "banner" else (sent.get(k) or {}).get("message"))})
    return {"settings": _view(), "shortcuts": _shortcuts(), "changed": changed}


@router.get("/api/platform/status")
def status():
    """Public: what the sign-up page and every shop's dashboard need to know."""
    open_ = signups_open()
    return {"signups_open": open_, "signups_message": None if open_ else signups_message(), "banner": live_banner()}
