"""
Happy Hour / Time-Based Bonus Rules — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/owner/happy-hour/*
Collection: `happy_hour_rules` (multiple rules per tenant)

A rule is a (day_of_week, start_time, end_time) window that applies a
points multiplier or a fixed bonus to qualifying scans during that window.

Frontend integration pattern (does not modify existing scan endpoint):
  1. Staff scans a customer normally via existing /api/owner/scan
  2. Frontend then calls /api/owner/happy-hour/apply with the customer
     barcode_id; backend checks the active rules and credits any extra
     points as a separate adjustment, logged in `happy_hour_credits`.

This keeps the original visit log clean and the bonus auditable.
"""
from __future__ import annotations

from datetime import datetime, timezone, time as dtime
from typing import Optional, List
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["happy-hour"])
_db = None

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def init(db):
    global _db
    _db = db
    try:
        db.happy_hour_rules.create_index("tenant_id")
        db.happy_hour_credits.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception:
        pass


# ---------- Models ----------
class HappyHourRule(BaseModel):
    id: Optional[str] = None
    tenant_id: Optional[str] = None
    name: str = "Happy Hour"
    days: List[str] = Field(default_factory=lambda: list(DAYS))   # subset of DAYS
    start_time: str = "17:00"   # HH:MM, 24h
    end_time: str = "19:00"     # HH:MM
    multiplier: float = 2.0     # multiplies points_per_visit; ignored if fixed_bonus > 0
    fixed_bonus: int = 0        # if > 0, adds this flat number of points instead
    enabled: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ApplyRequest(BaseModel):
    barcode_id: str


def _parse_time(t: str) -> Optional[dtime]:
    try:
        h, m = t.split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def _is_rule_active(rule: dict, now: datetime) -> bool:
    if not rule.get("enabled", True):
        return False
    today_key = DAYS[now.weekday()]
    if today_key not in (rule.get("days") or DAYS):
        return False
    start = _parse_time(rule.get("start_time", "00:00"))
    end = _parse_time(rule.get("end_time", "23:59"))
    if not start or not end:
        return False
    now_t = now.time()
    if start <= end:
        return start <= now_t <= end
    # Overnight window (e.g. 22:00 → 02:00)
    return now_t >= start or now_t <= end


# ---------- Owner endpoints ----------
@router.get("/api/owner/happy-hour")
def list_rules(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    rules = list(_db.happy_hour_rules.find({"tenant_id": token_data.tenant_id}))
    for r in rules:
        r.pop("_id", None)
    return {"rules": rules}


@router.post("/api/owner/happy-hour")
def create_rule(
    rule: HappyHourRule,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    rule.id = str(uuid.uuid4())
    rule.tenant_id = token_data.tenant_id
    payload = rule.model_dump()
    _db.happy_hour_rules.insert_one(payload)
    payload.pop("_id", None)
    return payload


@router.put("/api/owner/happy-hour/{rule_id}")
def update_rule(
    rule_id: str,
    rule: HappyHourRule,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    existing = _db.happy_hour_rules.find_one({"id": rule_id, "tenant_id": token_data.tenant_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.id = rule_id
    rule.tenant_id = token_data.tenant_id
    _db.happy_hour_rules.update_one({"id": rule_id}, {"$set": rule.model_dump()})
    return rule.model_dump()


@router.delete("/api/owner/happy-hour/{rule_id}")
def delete_rule(rule_id: str, token_data: TokenData = Depends(require_role(["business_owner"]))):
    res = _db.happy_hour_rules.delete_one({"id": rule_id, "tenant_id": token_data.tenant_id})
    return {"deleted": res.deleted_count}


@router.get("/api/owner/happy-hour/active-now")
def active_now(token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager", "staff"]))):
    """Useful for the Scan page to show 'Happy Hour active!' indicator."""
    now = datetime.now(timezone.utc)
    rules = list(_db.happy_hour_rules.find({"tenant_id": token_data.tenant_id, "enabled": True}))
    active = [r for r in rules if _is_rule_active(r, now)]
    for r in active:
        r.pop("_id", None)
    return {"active": bool(active), "rules": active}


@router.post("/api/owner/happy-hour/apply")
def apply_to_scan(
    req: ApplyRequest,
    token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager", "staff"])),
):
    """Call this after a normal scan; credits extra points if any happy-hour
    rule is active right now. Logged in happy_hour_credits for audit."""
    now = datetime.now(timezone.utc)
    customer = _db.customers.find_one({"tenant_id": token_data.tenant_id, "barcode_id": req.barcode_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    rules = list(_db.happy_hour_rules.find({"tenant_id": token_data.tenant_id, "enabled": True}))
    active_rules = [r for r in rules if _is_rule_active(r, now)]
    if not active_rules:
        return {"credited": 0, "active_rule": None}

    # Use the first active rule (merchants typically have one at a time)
    rule = active_rules[0]
    earn = _db.earn_rules.find_one({"tenant_id": token_data.tenant_id}) or {}
    base_points = int(earn.get("points_per_visit", 10) or 10)

    if rule.get("fixed_bonus", 0) > 0:
        bonus = int(rule["fixed_bonus"])
    else:
        bonus = int(round(base_points * (rule.get("multiplier", 1.0) - 1.0)))

    if bonus <= 0:
        return {"credited": 0, "active_rule": rule.get("name")}

    _db.customers.update_one({"id": customer["id"]}, {"$inc": {"points": bonus}})
    _db.happy_hour_credits.insert_one({
        "tenant_id": token_data.tenant_id,
        "customer_id": customer["id"],
        "rule_id": rule["id"],
        "rule_name": rule.get("name"),
        "points_credited": bonus,
        "created_at": now,
    })
    return {"credited": bonus, "active_rule": rule.get("name")}
