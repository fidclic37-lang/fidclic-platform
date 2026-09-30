"""
Custom Tier Thresholds + Big-Spender Definition.

Status: ✅ Implemented.
Mounts at:
  /api/owner/tier-definitions    — owner sets their own
  /api/admin/tier-definitions/{tenant_id}    — super-admin sets per tenant
Collection: `tier_definitions` (one document per tenant)

The customer's `tier` field on the existing scan endpoint still uses the
hardcoded thresholds in server.py — that file is intentionally left alone
to avoid the risk of breaking live scans. To apply the custom thresholds:
  1) Owner saves their thresholds via PUT /api/owner/tier-definitions
  2) They click "Recompute tiers now" → POST /api/owner/tier-definitions/recompute
     which iterates customers and rewrites .tier based on the new rules.
Going forward, the same recompute is invoked nightly via cron (already
present at /api/cron/daily-triggers — not modified here).
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import require_role

router = APIRouter(tags=["tier-definitions"])
from features.platform_access import require_admin
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.tier_definitions.create_index("tenant_id", unique=True)
    except Exception:
        pass


class TierDefinition(BaseModel):
    tenant_id: Optional[str] = None
    silver_min_visits: int = 10
    gold_min_visits: int = 20
    vip_min_visits: int = 40
    # Big spender = orthogonal label (not part of the tier ladder).
    # Owner can use it as a filter criterion on the campaigns page.
    big_spender_min_amount: float = 500.0
    big_spender_min_avg_ticket: float = 0.0    # 0 = ignore avg ticket
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _resolve(tenant_id: str) -> TierDefinition:
    doc = _db.tier_definitions.find_one({"tenant_id": tenant_id}) or {}
    payload = {**TierDefinition().model_dump(), **{k: v for k, v in doc.items() if k != "_id"}}
    return TierDefinition(**payload)


def _classify(visits: int, defn: TierDefinition) -> str:
    if visits >= defn.vip_min_visits:    return "vip"
    if visits >= defn.gold_min_visits:   return "gold"
    if visits >= defn.silver_min_visits: return "silver"
    return "bronze"


def _recompute_for_tenant(tenant_id: str) -> dict:
    defn = _resolve(tenant_id)
    customers = list(_db.customers.find({"tenant_id": tenant_id}))
    counts = {"bronze": 0, "silver": 0, "gold": 0, "vip": 0}
    big_spenders = 0
    updated = 0
    for c in customers:
        new_tier = _classify(int(c.get("visits", 0) or 0), defn)
        counts[new_tier] += 1
        spent = float(c.get("total_amount_paid", 0) or 0)
        avg_ticket = (spent / c["visits"]) if c.get("visits") else 0.0
        is_big = (
            spent >= defn.big_spender_min_amount
            and (defn.big_spender_min_avg_ticket <= 0 or avg_ticket >= defn.big_spender_min_avg_ticket)
        )
        if is_big:
            big_spenders += 1
        if new_tier != c.get("tier") or bool(c.get("is_big_spender")) != is_big:
            _db.customers.update_one(
                {"id": c["id"]},
                {"$set": {"tier": new_tier, "is_big_spender": is_big}},
            )
            updated += 1
    return {"distribution": counts, "big_spenders": big_spenders, "customers_updated": updated}


# ---------- Owner endpoints ----------
@router.get("/api/owner/tier-definitions")
def get_owner_def(token_data=Depends(require_role(["business_owner", "manager"]))):
    return _resolve(token_data.tenant_id).model_dump()


@router.put("/api/owner/tier-definitions")
def update_owner_def(
    defn: TierDefinition,
    token_data=Depends(require_role(["business_owner"])),
):
    if not (defn.silver_min_visits < defn.gold_min_visits < defn.vip_min_visits):
        raise HTTPException(status_code=400, detail="Thresholds must be silver < gold < vip.")
    defn.tenant_id = token_data.tenant_id
    defn.updated_at = datetime.now(timezone.utc)
    payload = defn.model_dump()
    _db.tier_definitions.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


@router.post("/api/owner/tier-definitions/recompute")
def recompute_owner(token_data=Depends(require_role(["business_owner"]))):
    return _recompute_for_tenant(token_data.tenant_id)


@router.get("/api/owner/big-spenders")
def list_big_spenders(
    limit: int = 200,
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    """Customers flagged as big spenders by the current definition.
    Useful for ad-hoc 'reward our biggest fans' campaigns."""
    defn = _resolve(token_data.tenant_id)
    query = {
        "tenant_id": token_data.tenant_id,
        "total_amount_paid": {"$gte": defn.big_spender_min_amount},
    }
    rows = list(_db.customers.find(query).sort("total_amount_paid", -1).limit(limit))
    out = []
    for c in rows:
        c.pop("_id", None)
        spent = float(c.get("total_amount_paid", 0) or 0)
        avg_ticket = (spent / c["visits"]) if c.get("visits") else 0.0
        if defn.big_spender_min_avg_ticket > 0 and avg_ticket < defn.big_spender_min_avg_ticket:
            continue
        c["avg_ticket"] = round(avg_ticket, 2)
        out.append(c)
    return {"definition": defn.model_dump(), "count": len(out), "big_spenders": out}


# ---------- Admin endpoints (super-admin can override per tenant) ----------
@router.get("/api/admin/tier-definitions/{tenant_id}")
def get_admin_def(
    tenant_id: str,
    token_data=Depends(require_admin("commerces")),
):
    return _resolve(tenant_id).model_dump()


@router.put("/api/admin/tier-definitions/{tenant_id}")
def update_admin_def(
    tenant_id: str,
    defn: TierDefinition,
    token_data=Depends(require_admin("commerces")),
):
    if not (defn.silver_min_visits < defn.gold_min_visits < defn.vip_min_visits):
        raise HTTPException(status_code=400, detail="Thresholds must be silver < gold < vip.")
    if not _db.tenants.find_one({"id": tenant_id}):
        raise HTTPException(status_code=404, detail="Tenant not found")
    defn.tenant_id = tenant_id
    defn.updated_at = datetime.now(timezone.utc)
    payload = defn.model_dump()
    _db.tier_definitions.update_one(
        {"tenant_id": tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


@router.post("/api/admin/tier-definitions/{tenant_id}/recompute")
def recompute_admin(
    tenant_id: str,
    token_data=Depends(require_admin("commerces")),
):
    return _recompute_for_tenant(tenant_id)
