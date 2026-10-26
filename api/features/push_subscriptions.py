"""
Web Push subscription management — lets customer browsers register for
push notifications, and lets the backend fan out messages.

Status: ✅ Implemented.
Mounts at: /api/customer/push/* and /api/owner/push/*
Collections: `push_subscriptions` (one per customer device)

Flow:
    1. Customer visits their wallet card on phone (e.g. /card/FT-XXXXXX)
    2. Frontend asks for notification permission, gets browser subscription
    3. Frontend POSTs subscription to /api/customer/push/subscribe
    4. From now on, auto-campaigns dispatch via Web Push (free) instead of SMS
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from auth import require_role

router = APIRouter(tags=["web-push"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.push_subscriptions.create_index("customer_id")
        db.push_subscriptions.create_index([("tenant_id", 1), ("customer_id", 1)])
        db.push_subscriptions.create_index("endpoint", unique=True)
    except Exception:
        pass


class SubscribeRequest(BaseModel):
    tenant_slug: str
    barcode_id: str
    subscription: Dict[str, Any]   # the raw browser PushSubscription JSON


class TestPushRequest(BaseModel):
    barcode_id: str
    title: Optional[str] = "FidClic"
    body: Optional[str] = "Test web push from FidClic"


@router.get("/api/public/vapid-public-key")
def vapid_public_key():
    """Customer browsers fetch this to subscribe."""
    from services.web_push import public_key, is_configured           # noqa: WPS433
    if not is_configured():
        return {"configured": False, "key": ""}
    return {"configured": True, "key": public_key()}


def _owner_only(barcode_id: str, request: Optional[Request]) -> None:
    """Only the card's own phone (or the shop) — server._card_customer."""
    import server as core
    core._card_customer(barcode_id, request)


@router.post("/api/customer/push/subscribe")
def subscribe(req: SubscribeRequest, request: Request = None):
    """Browser subscribes a customer to web push notifications — from the
    card's own phone only: anyone holding the card number could otherwise
    have another customer's messages sent to their browser (2026-10-09)."""
    _owner_only(req.barcode_id, request)
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        return {"ok": False, "error": "tenant_not_found"}
    customer = _db.customers.find_one({
        "tenant_id": tenant["id"], "barcode_id": req.barcode_id
    })
    if not customer:
        return {"ok": False, "error": "customer_not_found"}

    endpoint = (req.subscription or {}).get("endpoint")
    if not endpoint:
        return {"ok": False, "error": "missing_endpoint"}

    _db.push_subscriptions.update_one(
        {"endpoint": endpoint},
        {
            "$set": {
                "tenant_id": tenant["id"],
                "customer_id": customer["id"],
                "subscription": req.subscription,
                "endpoint": endpoint,
                "updated_at": datetime.now(timezone.utc),
            },
            "$setOnInsert": {
                "id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )
    return {"ok": True}


@router.post("/api/customer/push/unsubscribe")
def unsubscribe(req: SubscribeRequest):
    endpoint = (req.subscription or {}).get("endpoint")
    if endpoint:
        _db.push_subscriptions.delete_one({"endpoint": endpoint})
    return {"ok": True}


@router.post("/api/owner/push/test")
def test_push(
    req: TestPushRequest,
    token_data=Depends(require_role(["business_owner"])),
):
    """Owner sends a test push to one of their own customers (verification)."""
    from services.web_push import send_push, is_configured            # noqa: WPS433
    if not is_configured():
        return {"sent": False, "error": "vapid_not_configured"}

    customer = _db.customers.find_one({
        "tenant_id": token_data.tenant_id, "barcode_id": req.barcode_id
    })
    if not customer:
        return {"sent": False, "error": "customer_not_found"}

    subs = list(_db.push_subscriptions.find({
        "tenant_id": token_data.tenant_id, "customer_id": customer["id"],
    }))
    if not subs:
        return {"sent": False, "error": "no_active_subscriptions"}

    sent = 0
    expired = []
    for s in subs:
        result = send_push(s["subscription"], req.title or "FidClic", req.body or "Test")
        if result.get("sent"):
            sent += 1
        elif result.get("expired"):
            expired.append(s["endpoint"])
    # Clean up expired endpoints
    if expired:
        _db.push_subscriptions.delete_many({"endpoint": {"$in": expired}})
    return {"sent": sent, "subs_total": len(subs), "expired_cleaned": len(expired)}


@router.get("/api/card/{barcode_id}/notification-status")
def get_notification_status(barcode_id: str, request: Request = None):
    """Returns whether the customer has an active push subscription, and if
    not, how many campaigns they've missed in the last 30 days. Powers the
    in-card 'missed offers' banner — see MyWalletCardPage."""
    from datetime import timedelta
    if _db is None:
        return {"subscribed": False, "missed_count": 0}
    _owner_only(barcode_id, request)
    bc = (barcode_id or "").strip().upper()
    customer = _db.customers.find_one({"barcode_id": bc})
    if not customer:
        return {"subscribed": False, "missed_count": 0, "error": "customer_not_found"}
    has_sub = _db.push_subscriptions.count_documents({"customer_id": customer["id"]}) > 0
    if has_sub:
        return {"subscribed": True, "missed_count": 0}
    # Count campaigns sent to this customer in the last 30 days while they
    # were unsubscribed. We use the `notifications` collection (where every
    # outgoing campaign push gets logged) as the source of truth.
    since = datetime.now(timezone.utc) - timedelta(days=30)
    missed = 0
    try:
        missed = _db.notifications.count_documents({
            "tenant_id": customer.get("tenant_id"),
            "customer_id": customer["id"],
            "created_at": {"$gte": since},
            "type": {"$in": ["campaign", "offer", "flash_sale", "news", "voucher_expiry"]},
        })
    except Exception:
        missed = 0
    return {
        "subscribed": False,
        "missed_count": int(missed),
        "since_days": 30,
    }


@router.post("/api/card/{barcode_id}/test-push")
def customer_self_test_push(barcode_id: str, request: Request = None):
    """Customer-initiated test push, no auth — they can only fire to their
    own device(s). Lets the customer verify push is actually working from
    their wallet card without needing the owner to send a campaign.

    Returns a structured result the wallet card surfaces in a toast so the
    customer sees exactly why a push failed if it does (no subscription
    registered, VAPID not configured, endpoint expired, etc).
    """
    from services.web_push import send_push, is_configured            # noqa: WPS433
    if _db is None:
        return {"sent": 0, "error": "db_not_initialised"}
    _owner_only(barcode_id, request)
    if not is_configured():
        return {"sent": 0, "error": "vapid_not_configured",
                "hint": "Server missing VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY."}
    bc = (barcode_id or "").strip().upper()
    customer = _db.customers.find_one({"barcode_id": bc})
    if not customer:
        return {"sent": 0, "error": "customer_not_found"}
    subs = list(_db.push_subscriptions.find({"customer_id": customer["id"]}))
    if not subs:
        return {
            "sent": 0,
            "error": "no_subscription",
            "hint": "Open the card, toggle 'Autoriser les notifications' on, then tap Test again.",
        }
    sent = 0
    expired = []
    errors = []
    for s in subs:
        result = send_push(
            s["subscription"],
            "FidClic — test push ✓",
            "If you see this, push notifications are working. Tap to open your card.",
        )
        if result.get("sent"):
            sent += 1
        elif result.get("expired"):
            expired.append(s["endpoint"])
        elif result.get("error"):
            errors.append(result["error"])
    if expired:
        _db.push_subscriptions.delete_many({"endpoint": {"$in": expired}})
    return {
        "sent": sent,
        "subs_total": len(subs),
        "expired_cleaned": len(expired),
        "errors": errors[:3],
    }


def fan_out_to_customer(tenant_id: str, customer_id: str, title: str, body: str,
                        url: Optional[str] = None) -> Dict[str, Any]:
    """Helper: send a push to all of one customer's subscribed devices.
    Called by auto_campaigns._dispatch_message."""
    if _db is None:
        return {"sent": 0, "error": "db_not_initialised"}
    from services import client_status as _CS                         # noqa: WPS433
    if _CS.is_paused(_db, customer_id):                              # paused by the business: nothing
        return {"sent": 0, "error": "paused"}
    from services.web_push import send_push, is_configured            # noqa: WPS433
    if not is_configured():
        return {"sent": 0, "error": "vapid_not_configured"}

    from services import send_batch as _SB
    b = _SB.current(tenant_id, customer_id)          # a big send read every client's devices at once
    subs = b.subs(customer_id) if b is not None else list(_db.push_subscriptions.find({
        "tenant_id": tenant_id, "customer_id": customer_id
    }))
    if not subs:
        return {"sent": 0, "error": "no_subscription"}

    sent = 0
    expired = []
    for s in subs:
        r = send_push(s["subscription"], title, body, url=url) if url else send_push(s["subscription"], title, body)
        if r.get("sent"):
            sent += 1
        elif r.get("expired"):
            expired.append(s["endpoint"])
    if expired:
        _db.push_subscriptions.delete_many({"endpoint": {"$in": expired}})
        if b is not None:
            b.forget_subs(expired)
    return {"sent": sent, "subs_total": len(subs), "expired_cleaned": len(expired)}
