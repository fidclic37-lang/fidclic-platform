"""
Reviews & Ratings — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/customer/reviews and /api/owner/reviews/*
Collection: `reviews`

A customer leaves a 1–5 star review with optional text after a visit.
Owner sees a list, sees aggregated stats, and can post a public response.

Plumbing for the AI Complaint-Deflection feature lives in
`ai_brand_voice.py` and consumes events from this collection.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

# A review at or below this asks for a reply. Out of ten, so the bottom half.
NEEDS_RESPONSE_AT = 5

router = APIRouter(tags=["reviews"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.reviews.create_index([("tenant_id", 1), ("created_at", -1)])
        db.reviews.create_index("customer_id")
    except Exception:
        pass


class ReviewSubmit(BaseModel):
    tenant_slug: str
    barcode_id: Optional[str] = None    # if missing, treated as anonymous
    # Out of TEN, like everything else that touches `reviews`: the Review model
    # says so, /api/public/reviews enforces it, and the Analyses page halves it
    # to /5 exactly once for display. This used to cap at 5, so the same
    # collection held two different scales and a 5/5 was indistinguishable
    # from a mediocre 5/10.
    rating: int = Field(..., ge=1, le=10)
    text: str = ""
    visit_id: Optional[str] = None


class OwnerResponse(BaseModel):
    response_text: str


@router.post("/api/customer/reviews")
def submit_review(req: ReviewSubmit):
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    customer = None
    if req.barcode_id:
        customer = _db.customers.find_one({"tenant_id": tenant["id"], "barcode_id": req.barcode_id})

    # Sentiment and topics are what the owner's filters and the Analyses page
    # read. Writing a review without them would leave a row that no filter can
    # ever find, so this runs the very same analyser as /api/public/reviews.
    analysis = {"sentiment": None, "sentiment_score": None,
                "topics": [], "topic_scores": {}, "language": None}
    try:
        import server as core
        analysis = core.analyze_review_text(req.text or "", req.rating)
    except Exception as exc:
        print(f"reviews: sentiment analysis unavailable (non-fatal): {exc}")

    review = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant["id"],
        "customer_id": customer["id"] if customer else None,
        "customer_name": customer["name"] if customer else "Anonymous",
        "rating": req.rating,
        "text": req.text.strip(),
        "visit_id": req.visit_id,
        "sentiment": analysis["sentiment"],
        "sentiment_score": analysis["sentiment_score"],
        "topics": analysis["topics"],
        "topic_scores": analysis["topic_scores"],
        "language": analysis["language"],
        "owner_response": None,
        "owner_responded_at": None,
        "created_at": datetime.now(timezone.utc),
    }
    _db.reviews.insert_one(review)
    review.pop("_id", None)
    return {"submitted": True, "review_id": review["id"]}


@router.get("/api/customer/reviews/{slug}")
def public_reviews(slug: str, limit: int = 20):
    """Public-facing list of reviews for a tenant (anonymized)."""
    tenant = _db.tenants.find_one({"slug": slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    rows = list(
        _db.reviews.find({"tenant_id": tenant["id"]}).sort("created_at", -1).limit(limit)
    )
    out = []
    for r in rows:
        r.pop("_id", None)
        out.append({
            "rating": r.get("rating"),
            "text": r.get("text"),
            "first_name": (r.get("customer_name") or "Anonymous").split(" ")[0],
            "owner_response": r.get("owner_response"),
            "created_at": r.get("created_at"),
        })
    return {"reviews": out}


# NOTE — GET /api/owner/reviews is NOT defined here.
#
# It used to be, and it was dead code: server.py declares the same path with
# its own decorator, and `register_all` runs at the very bottom of server.py,
# so server.py's handler was always registered first and FastAPI always served
# that one. This one never ran.
#
# Removing it is not cosmetic. The two answered differently — server.py's
# takes branch_id / sentiment / topic / min_rating / max_rating / limit and
# attaches customer_name and customer_tier, which is exactly what the reviews
# drill-down reads; this one took only rating / days and returned bare rows.
# Had the registration order ever shifted, the page would have silently lost
# every customer name and every filter.
#
# The routes below are this module's own and are not duplicated anywhere.


@router.get("/api/owner/reviews/stats")
def review_stats(
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
    days: int = 30,
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = list(_db.reviews.find({"tenant_id": token_data.tenant_id, "created_at": {"$gte": cutoff}}))
    if not rows:
        return {"count": 0, "avg_rating": None, "distribution": {}, "needs_response": 0}
    # Ten buckets, because the ratings are out of ten. This used to declare
    # five and then grow keys 6..10 on the fly, so the distribution was both
    # incomplete on an empty bucket and mislabelled on a full one.
    counts = {n: 0 for n in range(1, 11)}
    for r in rows:
        n = int(r.get("rating") or 0)
        if 1 <= n <= 10:
            counts[n] += 1
    avg = sum(int(r.get("rating") or 0) for r in rows) / len(rows)
    # Unhappy is the bottom half of the scale, not the bottom three of ten.
    needs_response = sum(1 for r in rows
                         if int(r.get("rating") or 0) <= NEEDS_RESPONSE_AT
                         and not r.get("owner_response"))
    return {
        "count": len(rows),
        "avg_rating": round(avg, 2),
        "distribution": counts,
        "needs_response": needs_response,
    }


@router.post("/api/owner/reviews/{review_id}/respond")
def respond(
    review_id: str,
    req: OwnerResponse,
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    review = _db.reviews.find_one({"id": review_id, "tenant_id": token_data.tenant_id})
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    _db.reviews.update_one(
        {"id": review_id},
        {"$set": {
            "owner_response": req.response_text.strip(),
            "owner_responded_at": datetime.now(timezone.utc),
        }},
    )
    return {"ok": True}
