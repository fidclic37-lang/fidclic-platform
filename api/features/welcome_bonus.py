"""
Welcome Bonus & Configurable Earn Rules — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/owner/earn-rules and /api/customer/welcome-bonus
Collection: `earn_rules` (one document per tenant_id)

What this gives merchants:
- Set a one-time welcome bonus (X points) credited on first claim
- Configure points_per_visit (already in card_templates, mirrored here)
- Configure max_redemption_pct (cap on how much a single visit can be paid in points)
- Configure accrual_delay_minutes (anti-fraud: points lock for N minutes after a scan)

Does NOT modify the existing scan or join endpoints. The frontend simply
calls /api/customer/welcome-bonus/claim once after a successful signup,
and consults this config when rendering wallet/redemption UIs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["earn-rules"])
_db = None


def init(db):
    global _db
    _db = db
    # Ensure index for fast tenant lookup; idempotent.
    try:
        db.earn_rules.create_index("tenant_id", unique=True)
        db.welcome_bonus_claims.create_index([("tenant_id", 1), ("customer_id", 1)], unique=True)
    except Exception:
        pass


# ---------- Models ----------
class EarnRules(BaseModel):
    tenant_id: Optional[str] = None
    welcome_bonus_points: int = 0           # 0 = disabled
    welcome_bonus_message: str = "Welcome! Here are some bonus points to start."
    welcome_bonus_only_first_visit: bool = True
    points_per_visit: int = 10              # mirrored from card_templates for clarity
    max_redemption_pct: float = 100.0       # 0..100 — cap on % of bill payable with points
    accrual_delay_minutes: int = 0          # points unlock after N minutes
    enabled: bool = True
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WelcomeBonusClaim(BaseModel):
    tenant_slug: str
    barcode_id: str


# ---------- Owner endpoints ----------
@router.get("/api/owner/earn-rules")
def get_earn_rules(token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"],
                                                                partial_ok=True))):
    """Read on the Carte de fidélité page by everyone who sees it; changed by
    the owner only (the card is the same at every establishment)."""
    doc = _db.earn_rules.find_one({"tenant_id": token_data.tenant_id})
    if not doc:
        return EarnRules(tenant_id=token_data.tenant_id).model_dump()
    doc.pop("_id", None)
    return doc


@router.put("/api/owner/earn-rules")
def update_earn_rules(
    rules: EarnRules,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    rules.tenant_id = token_data.tenant_id
    rules.updated_at = datetime.now(timezone.utc)
    payload = rules.model_dump()
    _db.earn_rules.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


# ---------- Customer-facing ----------
@router.post("/api/customer/welcome-bonus/claim")
def claim_welcome_bonus(req: WelcomeBonusClaim):
    """Frontend calls this once, immediately after a successful join.
    Idempotent: claiming twice for the same customer is a no-op."""
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant_id = tenant["id"]

    rules_doc = _db.earn_rules.find_one({"tenant_id": tenant_id}) or {}
    if not rules_doc.get("enabled", True):
        return {"claimed": False, "reason": "earn_rules_disabled"}
    bonus = int(rules_doc.get("welcome_bonus_points", 0) or 0)
    if bonus <= 0:
        return {"claimed": False, "reason": "welcome_bonus_not_set"}

    customer = _db.customers.find_one({"tenant_id": tenant_id, "barcode_id": req.barcode_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Idempotency: only credit once per customer
    existing = _db.welcome_bonus_claims.find_one(
        {"tenant_id": tenant_id, "customer_id": customer["id"]}
    )
    if existing:
        return {"claimed": False, "reason": "already_claimed", "credited": existing.get("points", 0)}

    if rules_doc.get("welcome_bonus_only_first_visit", True) and customer.get("visits", 0) > 0:
        return {"claimed": False, "reason": "first_visit_only_violated"}

    _db.customers.update_one({"id": customer["id"]}, {"$inc": {"points": bonus}})
    _db.welcome_bonus_claims.insert_one({
        "tenant_id": tenant_id,
        "customer_id": customer["id"],
        "points": bonus,
        "created_at": datetime.now(timezone.utc),
    })
    return {
        "claimed": True,
        "credited": bonus,
        "message": rules_doc.get("welcome_bonus_message", "Welcome bonus credited."),
    }


@router.get("/api/customer/earn-rules/{slug}")
def public_earn_rules(slug: str):
    """Public read for customer-facing UIs that need to display the rules
    (e.g. 'You can pay up to 50% of your bill with points')."""
    tenant = _db.tenants.find_one({"slug": slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    doc = _db.earn_rules.find_one({"tenant_id": tenant["id"]}) or {}
    return {
        "welcome_bonus_points": doc.get("welcome_bonus_points", 0),
        "points_per_visit": doc.get("points_per_visit", 10),
        "max_redemption_pct": doc.get("max_redemption_pct", 100.0),
    }
