"""
Self-serve onboarding — STEP 2 (company details) + trial lifecycle.
Status: 🟢 Core.
Mounts at: /api/onboarding/status, /api/onboarding/company
Cron hook: run_trial_reminders() — called by /api/cron/agent-daily.

THE FLOW (app.fidclic.com)
    1. /register (server.py)      → personal account: prénom, nom, email,
                                    téléphone, mot de passe, CGU/DPA accepted.
                                    Tenant stub with onboarding_status="company",
                                    subscription_status="onboarding". No trial yet.
       — or —  Google / Apple      → same stub, terms NOT yet accepted
                                    (features/oauth.py).
    2. /onboarding/entreprise      → THIS module: raison sociale, secteur,
                                    activité, SIRET, adresse. On success the
                                    tenant becomes onboarding_status="done" and
                                    the 28-day trial starts NOW.
    3. Day 27                      → run_trial_reminders() emails the owner
                                    ("choisissez votre formule") once.
    4. Day 28                      → trial expired: BillingBanner locks paid
                                    features until Stripe checkout completes
                                    (features/billing.py flips status to active).

WHY THE TRIAL STARTS AT STEP 2
    A trial that starts at step 1 burns days while the owner hasn't even
    named their shop. Starting it when the company is set up means the 28
    days are 28 days of actually using the product.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role, TokenData

router = APIRouter(tags=["onboarding"])
_db = None

SECTORS = {"cafe", "restaurant", "pizzeria", "bakery", "bar", "spa", "salon",
           "gym", "retail", "other"}


def init(db):
    global _db
    _db = db
    try:
        _db.tenants.create_index([("subscription_status", 1), ("trial_ends_at", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _site_url() -> str:
    return os.getenv("PUBLIC_SITE_URL", "https://app.fidclic.com")


class CompanyDetails(BaseModel):
    legal_name: str                      # raison sociale (as on the Kbis)
    name: Optional[str] = None           # nom commercial shown to customers; defaults to legal_name
    sector: str
    activity: Optional[str] = None       # free text: "Boulangerie artisanale bio"
    siret: Optional[str] = None          # 14 digits, optional at signup
    address: str                         # rue
    postal_code: str
    city: str
    country: Optional[str] = "FR"          # ISO-3166 alpha-2 (step-2 select)
    phone: Optional[str] = None
    accepted_terms: Optional[bool] = None  # required only for Google/Apple users (no step 1 checkbox)


@router.get("/api/onboarding/status")
def onboarding_status(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    user = _db.users.find_one({"email": token_data.email}) or {}
    return {
        "onboarding_status": tenant.get("onboarding_status", "done"),
        "subscription_status": tenant.get("subscription_status"),
        "terms_accepted": bool(user.get("terms_accepted_at")),
        "slug": tenant.get("slug"),
        "tenant_name": tenant.get("name"),
        "prefill": {
            "name": tenant.get("name"),
            "sector": tenant.get("sector"),
            "phone": tenant.get("phone"),
            "postal_code": tenant.get("postal_code"),
        },
    }


@router.post("/api/onboarding/company")
def complete_company(body: CompanyDetails, request: Request,
                     token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Step 2. Idempotent: an already-onboarded tenant just gets its details
    updated (Settings reuses this) and its trial is NOT restarted."""
    # server.py is the app module; importing lazily avoids a circular import
    # at feature-load time and keeps a single slug / trial implementation.
    import server as core

    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    user = _db.users.find_one({"email": token_data.email}) or {}

    legal_name = body.legal_name.strip()
    if len(legal_name) < 2:
        raise HTTPException(status_code=400, detail="La raison sociale est requise")
    if body.sector not in SECTORS:
        raise HTTPException(status_code=400, detail="Secteur inconnu")
    if not body.address.strip() or not body.city.strip():
        raise HTTPException(status_code=400, detail="L'adresse complète est requise")
    if not re.fullmatch(r"\d{5}", body.postal_code.strip()):
        raise HTTPException(status_code=400, detail="Code postal invalide (5 chiffres)")
    siret = re.sub(r"\D", "", body.siret or "")
    if siret and len(siret) != 14:
        raise HTTPException(status_code=400, detail="Le SIRET doit contenir 14 chiffres")

    # Google / Apple signups skipped the step-1 checkbox: the consent is
    # collected here instead, and is mandatory before the account is usable.
    if not user.get("terms_accepted_at"):
        if not body.accepted_terms:
            raise HTTPException(
                status_code=400,
                detail="Vous devez accepter les Conditions Générales, la Politique de Confidentialité et le DPA",
            )
        _db.users.update_one({"email": token_data.email}, {"$set": {
            "terms_accepted_at": _now(), "terms_version": core.TERMS_VERSION,
        }})

    display_name = (body.name or "").strip() or legal_name
    update: Dict[str, Any] = {
        "name": display_name,
        "legal_name": legal_name,
        "sector": body.sector,
        "activity": (body.activity or "").strip() or None,
        "address": f"{body.address.strip()}, {body.postal_code.strip()} {body.city.strip()}",
        "postal_code": body.postal_code.strip(),
        "city": body.city.strip(),
        "country": (body.country or "FR").strip().upper()[:2],
        "onboarding_status": "done",
    }
    if siret:
        update["siret"] = siret
        update["siren"] = siret[:9]
    if body.phone and body.phone.strip():
        update["phone"] = body.phone.strip()

    first_completion = tenant.get("onboarding_status") == "company"
    if first_completion:
        # Slug was derived from "Prénom Nom" at step 1 — replace it with the
        # real shop name so /join/<slug> reads well on the customer side.
        update["slug"] = core._unique_slug(display_name)
        trial: Dict[str, Any] = {}
        core._start_trial(trial, tenant.get("plan") or "silver")
        update.update(trial)

    _db.tenants.update_one({"id": tenant["id"]}, {"$set": update})
    core.log_audit("onboarding.company_completed", actor=token_data.email, actor_type="user",
                   tenant_id=tenant["id"], request=request,
                   meta={"first_completion": first_completion, "sector": body.sector})
    fresh = _db.tenants.find_one({"id": tenant["id"]}) or {}
    return {
        "ok": True,
        "onboarding_status": "done",
        "slug": fresh.get("slug"),
        "trial": core._compute_trial_state(fresh),
    }


# ---------------------------------------------------------------------------
# Day-27 reminder — called by the daily cron. Pure function of the DB so it
# is trivially unit-testable with mongomock.
# ---------------------------------------------------------------------------
def _owner_email(tenant_id: str) -> Optional[Dict[str, Any]]:
    return _db.users.find_one({"tenant_id": tenant_id, "role": "business_owner"})


def _reminder_html(first_name: str, shop: str, days_left: int, ends_at: datetime) -> str:
    when = ends_at.astimezone(timezone.utc).strftime("%d/%m/%Y")
    hello = f"Bonjour {first_name}," if first_name else "Bonjour,"
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:auto;color:#1C1917">
      <p>{hello}</p>
      <p>Votre essai gratuit FidClic pour <strong>{shop}</strong> se termine
         <strong>{'demain' if days_left <= 1 else f'dans {days_left} jours'}</strong> ({when}).</p>
      <p>Pour continuer à fidéliser vos clients sans interruption, choisissez
         votre formule dès maintenant :</p>
      <p style="margin:24px 0">
        <a href="{_site_url()}/dashboard/settings?tab=billing"
           style="background:#B85C38;color:#fff;padding:12px 22px;border-radius:999px;
                  text-decoration:none;font-weight:600">Choisir ma formule</a>
      </p>
      <p style="color:#57534E;font-size:13px">Sans action de votre part, l'accès aux
         fonctionnalités payantes sera suspendu à la fin de l'essai. Vos données et
         vos clients restent conservés.</p>
      <p style="color:#8B8680;font-size:12px">— L'équipe FidClic</p>
    </div>
    """


def run_trial_reminders(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Email every trialing tenant whose trial ends within
    TRIAL_REMINDER_DAYS_BEFORE days (default 1 → day 27 of 28), once.
    Returns a summary for the cron response."""
    import server as core
    from models import TRIAL_REMINDER_DAYS_BEFORE
    from services import mailer

    now = now or _now()
    out = {"checked": 0, "reminders_sent": 0, "skipped_no_email": 0, "failures": []}
    for tenant in _db.tenants.find({"subscription_status": "trialing",
                                    "trial_reminder_sent_at": {"$exists": False}}):
        out["checked"] += 1
        state = core._compute_trial_state(tenant)
        days_left = state.get("days_left")
        if days_left is None or state.get("is_expired"):
            continue
        window = int(core.get_plan_features(state["plan"]).get(
            "trial_reminder_days_before", TRIAL_REMINDER_DAYS_BEFORE))
        if days_left > window:
            continue
        owner = _owner_email(tenant["id"])
        if not owner:
            out["skipped_no_email"] += 1
            continue
        ends_at = datetime.fromisoformat(state["trial_ends_at"])
        try:
            res = mailer.send(
                to=owner["email"],
                to_name=" ".join(x for x in [owner.get("first_name"), owner.get("last_name")] if x) or None,
                subject="Votre essai FidClic se termine demain — choisissez votre formule",
                html=_reminder_html(owner.get("first_name") or "", tenant.get("name") or "votre commerce",
                                    days_left, ends_at),
            )
            _db.tenants.update_one({"id": tenant["id"]}, {"$set": {
                "trial_reminder_sent_at": now,
                "trial_reminder_message_id": (res or {}).get("messageId"),
            }})
            out["reminders_sent"] += 1
        except Exception as e:  # noqa: BLE001 — one bad tenant must not stop the sweep
            out["failures"].append({"tenant": tenant.get("slug"), "error": str(e)[:120]})
    return out
