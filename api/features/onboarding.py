"""
Self-serve onboarding — STEPS 2 and 3 (company details, plan) + trial lifecycle.
Status: 🟢 Core.
Mounts at: /api/onboarding/status, /api/onboarding/company, /api/onboarding/start-trial
Cron hooks: run_trial_reminders(), purge_abandoned_signups() — called by
/api/cron/agent-daily.

THE FLOW (app.fidclic.com)
    1. /register (server.py)      → personal account: prénom, nom, email,
                                    téléphone, mot de passe, CGU/DPA accepted.
                                    Tenant stub with onboarding_status="company",
                                    subscription_status="onboarding",
                                    is_active=False. No trial yet.
       — or —  Google / Apple      → same stub, terms NOT yet accepted
                                    (features/oauth.py).
    2. /onboarding/entreprise      → raison sociale, secteur, activité, SIRET,
                                    adresse. The tenant moves to
                                    onboarding_status="plan". Still a draft.
    3. /onboarding/formule         → the three plans side by side, real HT price
                                    struck through, « 0 € », 30-day trial.
                                    /api/onboarding/start-trial: the business
                                    goes live (is_active=True, "done") and the
                                    30-day trial starts on TRIAL_PLAN (Pro AI).
    4. /onboarding/carte           → card design, optional (« Passer »).
    Day 29                         → run_trial_reminders() emails the owner
                                    ("choisissez votre formule") once.
    Day 30                         → trial expired: BillingBanner locks paid
                                    features until Stripe checkout completes
                                    (features/billing.py flips status to active).

WHY A SIGN-UP IS A HIDDEN DRAFT UNTIL STEP 3 (user, 2026-10-04)
    Someone who leaves after step 1 or 2 is not a business: the super admin
    must not list or count it. The rows exist (the owner can log back in and
    resume where they stopped), but is_active=False keeps them out of every
    admin list, count and cron, and purge_abandoned_signups() deletes them
    after DRAFT_SIGNUP_TTL_DAYS.

WHY THE TRIAL STARTS AT STEP 3
    A trial that starts at step 1 burns days while the owner hasn't even
    named their shop, and every trial day is a day of the real product.
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


DRAFT_STATES = ("verify", "company", "plan")


def _trial_plan() -> str:
    from models import TRIAL_PLAN
    return TRIAL_PLAN


def _trial_days() -> int:
    import server as core
    return int(core.get_plan_features(_trial_plan()).get("trial_duration_days", 30))


class CompanyDetails(BaseModel):
    legal_name: str                      # raison sociale (as on the Kbis)
    name: Optional[str] = None           # nom commercial shown to customers; defaults to legal_name
    sector: str
    activity: Optional[str] = None       # free text: "Boulangerie artisanale bio"
    siret: Optional[str] = None          # 14 digits, optional at signup
    # The address is taken from `address_token` (services/addresses.py), a
    # suggestion signed by our own address search inside `country`. The text
    # fields below only matter for the « adresse introuvable » path: a
    # verified city (token kind "city") plus the street the owner typed, and
    # the postal code when the city's record has none.
    address: str = ""                    # rue
    postal_code: str = ""
    city: str = ""
    country: Optional[str] = "FR"          # ISO-3166 alpha-2 (step-2 select)
    address_token: Optional[str] = None
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
        "trial_plan": _trial_plan(),
        "trial_days": _trial_days(),
        "prefill": {
            "name": tenant.get("name"),
            "sector": tenant.get("sector"),
            "phone": tenant.get("phone"),
            "postal_code": tenant.get("postal_code"),
        },
    }


def _verified_place(body: CompanyDetails) -> Dict[str, Any]:
    """The address from the signed suggestion, never from the typed text — so
    the city always exists, belongs to the selected country and matches the
    postal code."""
    from services import addresses
    country = (body.country or "FR").strip().upper()[:2]
    tok = addresses.verify(body.address_token or "")
    if not tok:
        raise HTTPException(status_code=400, detail="Choisissez votre adresse dans la liste proposée.")
    if (tok.get("country") or "").upper() != country:
        raise HTTPException(status_code=400, detail="Cette adresse n'est pas dans le pays sélectionné.")
    street, postcode = tok.get("street") or "", tok.get("postcode") or ""
    if tok.get("kind") == "city":
        street = body.address.strip()
        if len(street) < 3 or not re.search(r"[^\W\d_]", street):
            raise HTTPException(status_code=400, detail="Indiquez le numéro et le nom de la rue.")
    if not postcode:
        postcode = body.postal_code.strip()
        if not addresses.postcode_ok(country, postcode):
            raise HTTPException(status_code=400, detail="Code postal invalide pour ce pays.")
    return {"kind": tok.get("kind"), "country": country, "street": street, "postcode": postcode,
            "city": tok.get("city") or "", "lat": tok.get("lat"), "lng": tok.get("lng")}


@router.get("/api/onboarding/address-search")
def address_search(q: str = "", country: str = "FR", kind: str = "address",
                   token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Suggestions for step 2, inside the selected country only."""
    from services import addresses
    try:
        return {"results": addresses.search(q, country, kind)}
    except Exception as exc:      # noqa: BLE001 — a geocoder outage is a message, not a 500
        print(f"onboarding: address search failed ({country}): {exc}")
        raise HTTPException(status_code=503, detail="La recherche d'adresse est momentanément indisponible. Réessayez dans un instant.")


@router.post("/api/onboarding/company")
def complete_company(body: CompanyDetails, request: Request,
                     token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Step 2. Moves a draft to the plan step; the trial starts there, not
    here. Idempotent: an already-onboarded tenant just gets its details
    updated (Settings reuses this) and its trial is NOT restarted."""
    # server.py is the app module; importing lazily avoids a circular import
    # at feature-load time and keeps a single slug / trial implementation.
    import server as core

    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.get("onboarding_status") == "verify":
        raise HTTPException(status_code=409, detail="Vérifiez d'abord votre e-mail ou votre téléphone.")
    user = _db.users.find_one({"email": token_data.email}) or {}

    legal_name = body.legal_name.strip()
    if len(legal_name) < 2:
        raise HTTPException(status_code=400, detail="La raison sociale est requise")
    if body.sector not in SECTORS:
        raise HTTPException(status_code=400, detail="Secteur inconnu")
    place = _verified_place(body)
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
        "address": f"{place['street']}, {place['postcode']} {place['city']}",
        "postal_code": place["postcode"],
        "city": place["city"],
        "country": place["country"],
        "address_verified": place["kind"],          # "address" (exact) or "city" (street typed)
    }
    if place["kind"] == "address" and place.get("lat") is not None:
        update.update({"lat": place["lat"], "lng": place["lng"], "pin_source": "adresse"})
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
    if tenant.get("onboarding_status") in DRAFT_STATES:
        update["onboarding_status"] = "plan"       # step 3 next; still a draft

    _db.tenants.update_one({"id": tenant["id"]}, {"$set": update})
    core.log_audit("onboarding.company_completed", actor=token_data.email, actor_type="user",
                   tenant_id=tenant["id"], request=request,
                   meta={"first_completion": first_completion, "sector": body.sector})
    fresh = _db.tenants.find_one({"id": tenant["id"]}) or {}
    status = fresh.get("onboarding_status", "done")
    return {
        "ok": True,
        "onboarding_status": status,
        "slug": fresh.get("slug"),
        "trial": core._compute_trial_state(fresh) if status == "done" else None,
    }


@router.post("/api/onboarding/start-trial")
def start_trial(request: Request,
                token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Step 3, « Commencer l'essai gratuit ». The plan page only SHOWS the
    plans (the owner picks one when the trial ends); every trial runs on
    TRIAL_PLAN. This is the moment the business exists: it leaves draft
    (is_active=True), appears in the super admin, and the trial starts.
    Idempotent for a business that is already live."""
    import server as core

    tenant = _db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    status = tenant.get("onboarding_status", "done")
    if status == "verify":
        raise HTTPException(status_code=409, detail="Vérifiez d'abord votre e-mail ou votre téléphone.")
    if status == "company":
        raise HTTPException(status_code=409, detail="Complétez d'abord votre établissement.")
    if status == "plan":
        plan = _trial_plan()
        update: Dict[str, Any] = {
            "onboarding_status": "done",
            "is_active": True,
            "plan": plan,
            # "Inscrit le" in the super admin = the day the business went
            # live, not the day a draft was started.
            "created_at": _now(),
        }
        core._start_trial(update, plan)
        _db.tenants.update_one({"id": tenant["id"]}, {"$set": update})
        core.log_audit("onboarding.trial_started", actor=token_data.email, actor_type="user",
                       tenant_id=tenant["id"], request=request,
                       meta={"plan": plan, "trial_days": update.get("trial_duration_days")})
    fresh = _db.tenants.find_one({"id": tenant["id"]}) or {}
    return {
        "ok": True,
        "onboarding_status": fresh.get("onboarding_status", "done"),
        "plan": fresh.get("plan"),
        "trial": core._compute_trial_state(fresh),
    }


def purge_abandoned_signups(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Daily cron. Sign-ups that stopped before the plan step:
    - any still visible (made before drafts were hidden) are hidden now;
    - the ones older than DRAFT_SIGNUP_TTL_DAYS are deleted with their owner
      login and card template. A draft has no customers, visits or invoices:
      the business never went live."""
    from models import DRAFT_SIGNUP_TTL_DAYS

    now = now or _now()
    draft = {"onboarding_status": {"$in": list(DRAFT_STATES)}}
    hidden = _db.tenants.update_many({**draft, "is_active": {"$ne": False}},
                                     {"$set": {"is_active": False}}).modified_count
    cutoff = now - timedelta(days=DRAFT_SIGNUP_TTL_DAYS)
    ids = [t["id"] for t in _db.tenants.find({**draft, "created_at": {"$lt": cutoff}}, {"_id": 0, "id": 1})]
    if ids:
        _db.users.delete_many({"tenant_id": {"$in": ids}})
        _db.card_templates.delete_many({"tenant_id": {"$in": ids}})
        _db.tenants.delete_many({"id": {"$in": ids}})
    return {"hidden": hidden, "deleted": len(ids)}


# ---------------------------------------------------------------------------
# Day-29 reminder — called by the daily cron. Pure function of the DB so it
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
        <a href="{_site_url()}/dashboard/parametres/abonnement"
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
    TRIAL_REMINDER_DAYS_BEFORE days (default 1 → day 29 of 30), once.
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
        # Paramètres › Préférences › Emails de facturation switched off.
        try:
            from features.preferences import wants_email
            if not wants_email(owner["email"], "billing"):
                out.setdefault("skipped_by_preference", 0)
                out["skipped_by_preference"] += 1
                continue
        except Exception:
            pass
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
