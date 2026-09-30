"""Stripe billing for FidClic.

The platform is sold as a B2B2B SaaS:

  - The PLATFORM OWNER (the developer) sells FidClic to a RESELLER.
  - The RESELLER configures the Stripe account stored in env vars and resells
    the platform as their own SaaS product to many BUSINESSES (tenants).
  - Each BUSINESS pays the RESELLER monthly via Stripe Subscriptions.
  - The reseller pays the platform owner separately (out of band — that's
    not a Stripe relationship; it's a contract).

Architecture:

  - Single Stripe account (the reseller's). All Subscriptions are children of
    that account.
  - Each tenant is mapped to:
      stripe_customer_id  → Stripe Customer
      stripe_subscription_id → Stripe Subscription (one per tenant)
      subscription_status → 'trialing' | 'active' | 'past_due' | 'canceled' | 'unpaid'
      plan                → existing field (basic | gold | vip | chain), now
                            also reflected in the Stripe price.
  - Webhooks keep the local DB in sync. We never trust the frontend's claim
    about subscription state.

Endpoints exposed at /api/billing/*:

  POST /api/billing/checkout       Create a Stripe Checkout session for a plan.
  POST /api/billing/portal         Customer self-serve (cancel / upgrade / cards).
  POST /api/billing/webhook        Stripe → us, signed with STRIPE_WEBHOOK_SECRET.
  GET  /api/billing/status         Current subscription view for the dashboard.

Tenant feature gating:
  When the subscription is past_due or canceled, the platform downgrades to
  read-only: existing customers visible, no new visits, no campaign sends.
  Restored automatically when the subscription becomes active again.
"""

from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import pymongo

# Stripe SDK is optional at import time so the platform still boots without it
# (handy for local dev / preview builds without billing configured).
try:
    import stripe  # type: ignore
except ImportError:  # pragma: no cover
    stripe = None  # type: ignore

from auth import require_role, TokenData

router = APIRouter()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
PUBLIC_URL = os.environ.get("VITE_PUBLIC_URL", "").rstrip("/") or os.environ.get("PUBLIC_URL", "").rstrip("/")

# Plan → price-id mapping. The actual euros are managed in Stripe Dashboard.
# We keep these in env so the reseller can change pricing without a redeploy.
PLAN_PRICE_IDS = {
    # "silver" is the Starter plan's key in the catalogue (models.PLAN_FEATURES);
    # "basic" is kept for tenants created before it.
    "silver": os.environ.get("STRIPE_PRICE_STARTER", "").strip(),
    "basic":  os.environ.get("STRIPE_PRICE_STARTER", "").strip(),
    "gold":   os.environ.get("STRIPE_PRICE_GROWTH", "").strip(),
    "vip":    os.environ.get("STRIPE_PRICE_PRO", "").strip(),
    # 'chain' tier is custom-quoted and not available via self-serve checkout.
}

if STRIPE_SECRET_KEY and stripe is not None:
    stripe.api_key = STRIPE_SECRET_KEY

# Lazy-import db at function-call time to dodge circular imports with server.py.
def _db():
    from server import db  # noqa: WPS433
    return db


def is_configured() -> bool:
    """True if Stripe is fully wired (keys present + SDK installed)."""
    return bool(STRIPE_SECRET_KEY and stripe is not None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_customer(tenant: dict) -> str:
    """Return the Stripe customer_id for a tenant, creating one if needed."""
    if tenant.get("stripe_customer_id"):
        return tenant["stripe_customer_id"]
    customer = stripe.Customer.create(
        email=tenant.get("email") or tenant.get("contact_email") or "",
        name=tenant.get("name", ""),
        metadata={"tenant_id": tenant["id"], "tenant_slug": tenant.get("slug", "")},
    )
    _db().tenants.update_one(
        {"id": tenant["id"]},
        {"$set": {"stripe_customer_id": customer.id}},
    )
    return customer.id


def _plan_from_price_id(price_id: str) -> Optional[str]:
    """Reverse-lookup: given a Stripe price ID, return our internal plan name."""
    for plan, pid in PLAN_PRICE_IDS.items():
        if pid and pid == price_id:
            return plan
    return None


def is_subscription_active(tenant: dict) -> bool:
    """Read-only feature gate. True iff tenant is allowed to use paid features.
    A tenant with no subscription_status (legacy / not-yet-billed) is treated
    as active so existing data remains visible — billing was added after
    launch, so we grandfather everyone in. Once we ship checkout, new tenants
    start in 'trialing' from day one.
    """
    if not is_configured():
        return True  # billing not enabled at all
    status = tenant.get("subscription_status")
    if status is None:
        return True  # legacy tenant, grandfathered
    return status in ("active", "trialing")


# ---------------------------------------------------------------------------
# Public DTOs
# ---------------------------------------------------------------------------
class CheckoutRequest(BaseModel):
    plan: str  # 'basic' | 'gold' | 'vip'
    success_path: Optional[str] = "/dashboard?billing=success"
    cancel_path: Optional[str] = "/dashboard?billing=cancelled"


class PortalRequest(BaseModel):
    return_path: Optional[str] = "/settings"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/billing/status")
def billing_status(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Compact view used by the Settings → Billing tab."""
    db = _db()
    tenant = db.tenants.find_one({"id": token_data.tenant_id}) or {}
    return {
        "configured": is_configured(),
        "plan": tenant.get("plan", "basic"),
        "subscription_status": tenant.get("subscription_status"),
        "current_period_end": tenant.get("subscription_period_end"),
        "trial_end": tenant.get("subscription_trial_end"),
        "cancel_at_period_end": bool(tenant.get("subscription_cancel_at_period_end")),
        "has_stripe_customer": bool(tenant.get("stripe_customer_id")),
        "available_plans": [
            {"id": "basic", "name": "Starter", "price_id_set": bool(PLAN_PRICE_IDS["basic"])},
            {"id": "gold", "name": "Growth", "price_id_set": bool(PLAN_PRICE_IDS["gold"])},
            {"id": "vip", "name": "Pro", "price_id_set": bool(PLAN_PRICE_IDS["vip"])},
        ],
    }


@router.post("/api/billing/checkout")
def create_checkout(req: CheckoutRequest, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Returns a Stripe Checkout URL the owner should redirect to."""
    if req.plan == "franchise":
        raise HTTPException(status_code=400, detail="L'offre Franchise est sur devis : contactez-nous depuis la page Abonnement.")
    if not is_configured():
        raise HTTPException(status_code=503, detail="Billing not configured. Ask the platform admin to set STRIPE_SECRET_KEY.")
    price_id = PLAN_PRICE_IDS.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Plan '{req.plan}' not available for self-serve checkout.")
    db = _db()
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer_id = _ensure_customer(tenant)
    base = PUBLIC_URL or "https://app.fidclic.com"
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base}{req.success_path}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base}{req.cancel_path}",
        client_reference_id=tenant["id"],
        subscription_data={
            # 14-day trial sweetens self-serve sign-ups; reseller can lower in
            # Stripe Dashboard → Product → Edit price.
            "trial_period_days": 14,
            "metadata": {"tenant_id": tenant["id"], "tenant_slug": tenant.get("slug", "")},
        },
        allow_promotion_codes=True,
        # Tax: configure via Stripe Tax in Dashboard. We don't pass tax behaviour
        # here so it inherits whatever the price object specifies.
    )
    return {"url": session.url, "session_id": session.id}


@router.post("/api/billing/portal")
def create_portal(req: PortalRequest, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Returns a Stripe Customer Portal URL for self-serve subscription mgmt."""
    if not is_configured():
        raise HTTPException(status_code=503, detail="Billing not configured.")
    db = _db()
    tenant = db.tenants.find_one({"id": token_data.tenant_id})
    if not tenant or not tenant.get("stripe_customer_id"):
        raise HTTPException(status_code=400, detail="Tenant has no Stripe customer. Subscribe first.")
    base = PUBLIC_URL or "https://app.fidclic.com"
    portal = stripe.billing_portal.Session.create(
        customer=tenant["stripe_customer_id"],
        return_url=f"{base}{req.return_path}",
    )
    return {"url": portal.url}


@router.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    """Stripe → us. We mirror subscription state into the tenant document.

    Subscribed events (configure in Stripe Dashboard → Webhooks):
      checkout.session.completed
      customer.subscription.updated
      customer.subscription.deleted
      invoice.paid
      invoice.payment_failed
    """
    if not is_configured():
        raise HTTPException(status_code=503, detail="Billing not configured.")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook signature verification failed: {e}")

    db = _db()
    etype = event["type"]
    obj = event["data"]["object"]

    def _find_tenant_for_customer(customer_id: str) -> Optional[dict]:
        return db.tenants.find_one({"stripe_customer_id": customer_id})

    if etype == "checkout.session.completed":
        # Initial subscribe — link tenant to subscription.
        tenant_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("tenant_id")
        sub_id = obj.get("subscription")
        cust_id = obj.get("customer")
        if tenant_id:
            update = {"stripe_customer_id": cust_id}
            if sub_id:
                update["stripe_subscription_id"] = sub_id
            db.tenants.update_one({"id": tenant_id}, {"$set": update})

    elif etype in ("customer.subscription.updated", "customer.subscription.created"):
        cust_id = obj.get("customer")
        tenant = _find_tenant_for_customer(cust_id)
        if tenant:
            items = (obj.get("items") or {}).get("data") or []
            price_id = items[0]["price"]["id"] if items else None
            plan = _plan_from_price_id(price_id) if price_id else tenant.get("plan", "basic")
            period_end = obj.get("current_period_end")
            trial_end = obj.get("trial_end")
            db.tenants.update_one(
                {"id": tenant["id"]},
                {"$set": {
                    "stripe_subscription_id": obj.get("id"),
                    "subscription_status": obj.get("status"),
                    "subscription_period_end": datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None,
                    "subscription_trial_end": datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None,
                    "subscription_cancel_at_period_end": bool(obj.get("cancel_at_period_end")),
                    "plan": plan,
                }},
            )
            if obj.get("status") == "active" and (plan != tenant.get("plan") or tenant.get("subscription_status") != "active"):
                try:                              # Analytics › Activité récente: « Abonnement Pro activé »
                    import server as core
                    core.log_audit("billing.plan_activated", actor="stripe", actor_type="system", tenant_id=tenant["id"],
                                   target=tenant["id"], meta={"to": plan})
                except Exception:
                    pass

    elif etype == "customer.subscription.deleted":
        cust_id = obj.get("customer")
        tenant = _find_tenant_for_customer(cust_id)
        if tenant:
            db.tenants.update_one(
                {"id": tenant["id"]},
                {"$set": {
                    "subscription_status": "canceled",
                    "subscription_cancel_at_period_end": False,
                }},
            )

    elif etype == "invoice.payment_failed":
        cust_id = obj.get("customer")
        tenant = _find_tenant_for_customer(cust_id)
        if tenant:
            # Stripe will already have moved the subscription to 'past_due'
            # via subscription.updated, but flag it here too for redundancy.
            db.tenants.update_one(
                {"id": tenant["id"]},
                {"$set": {"subscription_status": "past_due", "last_payment_failed_at": datetime.now(timezone.utc)}},
            )

    elif etype == "invoice.paid":
        cust_id = obj.get("customer")
        tenant = _find_tenant_for_customer(cust_id)
        if tenant:
            db.tenants.update_one(
                {"id": tenant["id"]},
                {"$set": {"last_payment_succeeded_at": datetime.now(timezone.utc)}},
            )
            # Every payment becomes a FidClic invoice (features/invoices.py),
            # issued as soon as the issuer's legal details are complete.
            if (obj.get("amount_paid") or 0) > 0:
                try:
                    from features.invoices import record_payment
                    record_payment(tenant["id"], obj)
                except Exception as _e:
                    print(f"billing: invoice not recorded (non-fatal): {_e}")

    return {"received": True, "type": etype}
