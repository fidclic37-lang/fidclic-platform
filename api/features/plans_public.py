"""
Plan catalogue + usage — ONE source of truth for what each formula includes.
Status: 🟢 Core.
Mounts at:
    GET /api/public/plans          → public catalogue (no auth) — the marketing
                                     site builds fidclic.com/tarifs from THIS
    GET /api/owner/usage           → this tenant's live consumption vs its limits

WHY THIS EXISTS
    The prices and limits used to live in two places: PLAN_FEATURES here and a
    hand-typed table on the marketing site. They drifted (site promised 1 500
    customers, the app capped at 1 000), which means selling something the
    product does not deliver. Now the site fetches this endpoint at build time
    and fails its build if it cannot — so the two can no longer disagree.

    Admin overrides (db.plan_settings, /admin/plans) are folded in by
    get_plan_features(), so a price change made in the admin editor also shows
    on the website at the next deploy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from auth import require_role, TokenData

router = APIRouter(tags=["plans"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        _db.delivery_log.create_index([("tenant_id", 1), ("channel", 1), ("timestamp", 1)])
    except Exception:
        pass


def _month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def push_used_this_month(tenant_id: str, now: Optional[datetime] = None) -> int:
    """Push notifications actually delivered to this tenant's customers since
    the 1st of the month. Counted from delivery_log, which dispatch_to_customer
    already writes for every single send — so the number the merchant sees is
    the number that really left the server."""
    try:
        return _db.delivery_log.count_documents({
            "tenant_id": tenant_id,
            "channel": "web_push",
            "result.sent": {"$gt": 0},
            "timestamp": {"$gte": _month_start(now)},
        })
    except Exception:
        return 0


def campaigns_used_this_month(tenant_id: str, now: Optional[datetime] = None) -> int:
    try:
        return _db.campaigns.count_documents({
            "tenant_id": tenant_id,
            "sent_at": {"$gte": _month_start(now)},
        })
    except Exception:
        return 0


def push_quota_state(tenant_id: str, plan: str) -> Dict[str, Any]:
    """{limit, used, remaining, exceeded}. limit 0 = unlimited."""
    import server as core
    limit = int(core.get_plan_features(plan).get("push_per_month", 0) or 0)
    used = push_used_this_month(tenant_id)
    return {
        "limit": limit,
        "used": used,
        "remaining": None if limit <= 0 else max(0, limit - used),
        "exceeded": limit > 0 and used >= limit,
    }


@router.get("/api/public/plans")
def public_plans():
    """The catalogue the marketing site renders. No auth: it is public pricing."""
    import server as core
    from models import ANNUAL_DISCOUNT, PLAN_ORDER

    plans = []
    for key in PLAN_ORDER:
        f = core.get_plan_features(key)
        plans.append({
            "key": key,
            "label": f.get("label"),
            "price_monthly": f.get("price"),
            "limits": {
                "max_customers": f.get("max_customers"),          # clients ACTIFS (12 mois)
                "new_cards_per_month": f.get("new_cards_per_month", 0),
                "push_per_month": f.get("push_per_month", 0),
                "campaigns_per_month": f.get("campaigns_per_month", 0),
                "staff_accounts": f.get("staff_accounts"),
                "establishments": f.get("establishments"),
                "ai_queries_per_day": f.get("ai_queries_per_day", 0),
            },
            "features": {
                "digital_card": True,
                "wallet": True,
                "rewards": True,
                "crm": key != "silver",
                "segments": key != "silver",
                "campaigns": True,
                "automation": key != "silver",
                "geo": bool(f.get("geo_proximity")),
                "referral": key != "silver",
                "analytics": key != "silver",
                "ai": int(f.get("ai_queries_per_day", 0) or 0) > 0,
                "csv_import": bool(f.get("csv_export")),
                "multi_branch": bool(f.get("multi_branch")),
            },
            "trial_days": f.get("trial_duration_days", 28),
        })
    return {
        "currency": "EUR",
        "taxes": "HT",
        "annual_discount": ANNUAL_DISCOUNT,
        "trial_days": plans[0]["trial_days"],
        "trial_requires_card": False,
        "plans": plans,
    }


@router.get("/api/owner/usage")
def owner_usage(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Live consumption for the dashboard: customers, push and campaigns used
    this month against the plan's limits. What we sell is what we count."""
    import server as core

    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    plan = tenant.get("plan") or "silver"
    f = core.get_plan_features(plan)
    # The plan counts ACTIVE customers (a visit within the year); dormant
    # records stay in the base and cost the merchant nothing.
    customers = core.count_active_customers(token_data.tenant_id)
    dormant = _db.customers.count_documents({
        "tenant_id": token_data.tenant_id,
        "card_deleted_at": {"$exists": False}, "deleted_at": {"$exists": False},
    }) - customers
    month_start = _month_start()
    new_cards = _db.customers.count_documents({"tenant_id": token_data.tenant_id,
                                               "created_at": {"$gte": month_start}})
    staff = _db.users.count_documents({"tenant_id": token_data.tenant_id})

    def block(used: int, limit: Optional[int]) -> Dict[str, Any]:
        lim = int(limit or 0)
        return {
            "used": used,
            "limit": lim or None,          # None = unlimited
            "remaining": None if lim <= 0 else max(0, lim - used),
            "exceeded": lim > 0 and used >= lim,
        }

    return {
        "plan": plan,
        "plan_label": f.get("label"),
        "period_start": _month_start().isoformat(),
        "customers": block(customers, f.get("max_customers")),
        "dormant_customers": max(0, dormant),
        "new_cards": block(new_cards, f.get("new_cards_per_month")),
        "push": block(push_used_this_month(token_data.tenant_id), f.get("push_per_month")),
        "campaigns": block(campaigns_used_this_month(token_data.tenant_id), f.get("campaigns_per_month")),
        "staff_accounts": block(staff, f.get("staff_accounts")),
    }
