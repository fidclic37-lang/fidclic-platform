"""
Referral Program — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/owner/referrals/* and /api/customer/referral/*
Collections: `referral_config`, `referral_codes`, `referral_redemptions`

Flow:
  1. Existing customer fetches/generates their referral code
  2. They share the code (or a URL with ?ref=CODE)
  3. New customer signs up via the existing /api/join/{slug} endpoint
  4. Frontend calls /api/customer/referral/redeem with new customer's
     barcode and the ref code → credits both referrer and referee
  5. Idempotent: a given new-customer can only be redeemed once

Does NOT modify the existing /api/join/{slug} signup endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["referrals"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.referral_config.create_index("tenant_id", unique=True)
        db.referral_codes.create_index("code", unique=True)
        db.referral_codes.create_index([("tenant_id", 1), ("customer_id", 1)], unique=True)
        db.referral_redemptions.create_index([("tenant_id", 1), ("referee_customer_id", 1)], unique=True)
    except Exception:
        pass


# ---------- Models ----------
class ReferralConfig(BaseModel):
    tenant_id: Optional[str] = None
    enabled: bool = False
    referrer_reward_points: int = 50
    referee_reward_points: int = 25
    minimum_visits_to_earn: int = 1   # referee must reach this many visits before referrer is credited
    referrer_message: str = "Thanks for sharing! You earned {points} points."
    referee_message: str = "Welcome via a friend! Here are {points} points to start."


class GenerateCodeRequest(BaseModel):
    tenant_slug: str
    barcode_id: str


class RedeemRequest(BaseModel):
    tenant_slug: str
    new_customer_barcode_id: str
    code: str


# ---------- Helpers ----------
def _new_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "REF-" + "".join(secrets.choice(alphabet) for _ in range(8))


# ---------- Owner endpoints ----------
@router.get("/api/owner/referrals/config")
def get_config(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    doc = _db.referral_config.find_one({"tenant_id": token_data.tenant_id})
    if not doc:
        return ReferralConfig(tenant_id=token_data.tenant_id).model_dump()
    doc.pop("_id", None)
    return doc


@router.put("/api/owner/referrals/config")
def update_config(
    config: ReferralConfig,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    config.tenant_id = token_data.tenant_id
    payload = config.model_dump()
    _db.referral_config.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


@router.get("/api/owner/referrals/leaderboard")
def leaderboard(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Top customers by successful referrals."""
    pipeline = [
        {"$match": {"tenant_id": token_data.tenant_id}},
        {"$group": {"_id": "$referrer_customer_id", "successful_referrals": {"$sum": 1}}},
        {"$sort": {"successful_referrals": -1}},
        {"$limit": 50},
    ]
    rows = list(_db.referral_redemptions.aggregate(pipeline))
    out = []
    for row in rows:
        cust = _db.customers.find_one({"id": row["_id"]}) or {}
        out.append({
            "customer_id": row["_id"],
            "name": cust.get("name", "Unknown"),
            "successful_referrals": row["successful_referrals"],
        })
    return {"leaderboard": out}


# ---------- Customer endpoints ----------
@router.post("/api/customer/referral/code")
def get_or_create_code(req: GenerateCodeRequest):
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    customer = _db.customers.find_one({"tenant_id": tenant["id"], "barcode_id": req.barcode_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    existing = _db.referral_codes.find_one({
        "tenant_id": tenant["id"], "customer_id": customer["id"]
    })
    if existing:
        return {"code": existing["code"], "share_url": f"/join/{req.tenant_slug}?ref={existing['code']}"}

    # Generate a unique code (collisions are astronomically unlikely but guard anyway)
    for _ in range(5):
        code = _new_code()
        if not _db.referral_codes.find_one({"code": code}):
            break
    else:
        raise HTTPException(status_code=500, detail="Could not allocate referral code")

    _db.referral_codes.insert_one({
        "tenant_id": tenant["id"],
        "customer_id": customer["id"],
        "code": code,
        "created_at": datetime.now(timezone.utc),
    })
    return {"code": code, "share_url": f"/join/{req.tenant_slug}?ref={code}"}


@router.post("/api/customer/referral/redeem")
def redeem(req: RedeemRequest):
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    config = _db.referral_config.find_one({"tenant_id": tenant["id"]}) or {}
    if not config.get("enabled", False):
        return {"redeemed": False, "reason": "referrals_disabled"}

    code_doc = _db.referral_codes.find_one({"code": req.code, "tenant_id": tenant["id"]})
    if not code_doc:
        raise HTTPException(status_code=404, detail="Invalid referral code")

    referee = _db.customers.find_one({"tenant_id": tenant["id"], "barcode_id": req.new_customer_barcode_id})
    if not referee:
        raise HTTPException(status_code=404, detail="Referee not found")

    if referee["id"] == code_doc["customer_id"]:
        raise HTTPException(status_code=400, detail="Cannot self-refer")

    # Idempotency
    if _db.referral_redemptions.find_one({"tenant_id": tenant["id"], "referee_customer_id": referee["id"]}):
        return {"redeemed": False, "reason": "already_redeemed"}

    referee_pts = int(config.get("referee_reward_points", 25))
    referrer_pts = int(config.get("referrer_reward_points", 50))

    _db.customers.update_one({"id": referee["id"]}, {"$inc": {"points": referee_pts}})

    # Referrer credit may be deferred until referee hits minimum_visits_to_earn
    referrer_credited_now = referee.get("visits", 0) >= int(config.get("minimum_visits_to_earn", 1))
    if referrer_credited_now:
        _db.customers.update_one({"id": code_doc["customer_id"]}, {"$inc": {"points": referrer_pts}})
    # Google Wallet — live points sync on existing passes (no-op otherwise; never raises).
    try:
        from features.google_wallet import sync_wallet_after_points_change  # noqa: WPS433
        sync_wallet_after_points_change(referee["id"])
        if referrer_credited_now:
            sync_wallet_after_points_change(code_doc["customer_id"])
    except Exception:
        pass

    _db.referral_redemptions.insert_one({
        "tenant_id": tenant["id"],
        "referrer_customer_id": code_doc["customer_id"],
        "referee_customer_id": referee["id"],
        "code": req.code,
        "referee_points": referee_pts,
        "referrer_points": referrer_pts if referrer_credited_now else 0,
        "referrer_pending": not referrer_credited_now,
        "created_at": datetime.now(timezone.utc),
    })

    return {
        "redeemed": True,
        "referee_credited": referee_pts,
        "referrer_credited": referrer_pts if referrer_credited_now else 0,
        "referrer_pending": not referrer_credited_now,
    }
