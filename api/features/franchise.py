"""
Offre Franchise — sold on quote (decided with the user): every network has
its own number of stores, so there is no public price.

    owner        « Nous contacter » on the Abonnement page files a request
                 (POST /api/owner/request-upgrade, requested_plan=franchise)
    super admin  sees the requests and the franchises here, and sets each
                 one's agreed monthly price (€ HT) and limits; they live on
                 the tenant as franchise_terms and apply through
                 server.features_for(). Payment: a custom price in Stripe, or
                 invoiced by hand — the platform's invoices follow Stripe's
                 real amounts either way.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["admin"])
_db = None
ADMIN = ["super_admin"]


def init(db):
    global _db
    _db = db


def _now():
    return datetime.now(timezone.utc)


class TermsIn(BaseModel):
    price: float = Field(..., ge=0, le=100000)
    establishments: int = Field(..., ge=1, le=1000)
    max_customers: Optional[int] = Field(None, ge=0)
    new_cards_per_month: Optional[int] = Field(None, ge=0)
    staff_accounts: Optional[int] = Field(None, ge=1)
    notes: Optional[str] = Field(None, max_length=2000)
    activate: bool = True


def _view(t: Dict[str, Any]) -> Dict[str, Any]:
    import server as core
    f = core.features_for(t)
    return {"id": t["id"], "name": t.get("name"), "plan": t.get("plan"), "status": t.get("subscription_status"),
            "stores": len([b for b in t.get("branches") or [] if b.get("status") != "closed"]) or 1,
            "terms": t.get("franchise_terms") or {},
            "effective": {k: f.get(k) for k in ("price", "establishments", "max_customers", "new_cards_per_month",
                                                 "staff_accounts")}}


@router.get("/api/admin/franchise")
def franchise_overview(token_data: TokenData = Depends(require_role(ADMIN))):
    reqs = list(_db.upgrade_requests.find({"requested_plan": "franchise", "status": "pending"}, {"_id": 0})
                .sort("created_at", -1).limit(100))
    for r in reqs:
        r["created_at"] = r["created_at"].isoformat() if isinstance(r.get("created_at"), datetime) else r.get("created_at")
    return {"requests": reqs,
            "franchises": [_view(t) for t in _db.tenants.find({"plan": "franchise"}, {"_id": 0}).sort("name", 1)]}


@router.put("/api/admin/tenants/{tid}/franchise")
def set_franchise(tid: str, body: TermsIn, token_data: TokenData = Depends(require_role(ADMIN))):
    import server as core
    t = _db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    terms = {k: v for k, v in body.dict().items() if k not in ("activate",) and v is not None}
    terms.update(updated_at=_now(), updated_by=token_data.email)
    sets: Dict[str, Any] = {"plan": "franchise", "franchise_terms": terms}
    if body.activate and (t.get("subscription_status") or "") in ("", "trialing", "onboarding", "past_due", "canceled", "expired"):
        sets["subscription_status"] = "active"
    _db.tenants.update_one({"id": tid}, {"$set": sets})
    _db.upgrade_requests.update_many({"tenant_id": tid, "requested_plan": "franchise", "status": "pending"},
                                     {"$set": {"status": "completed", "resolved_at": _now()}})
    core.log_audit("admin.franchise_terms", actor=token_data.email, actor_type="user", target=tid,
                   meta={"from_plan": t.get("plan"), "price": body.price, "establishments": body.establishments})
    return _view(_db.tenants.find_one({"id": tid}, {"_id": 0}))
