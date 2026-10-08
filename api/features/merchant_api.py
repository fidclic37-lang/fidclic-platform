"""
API & Intégrations — a business connects its own tools (caisse, site,
Zapier / Make / n8n, CRM) to FidClic.

Included in the plans whose « API & Intégrations » switch is on (Super admin ›
Plan Limits; Pro AI by default). Everything is checked on every call, so a
business that changes plan loses the API at once.

API KEYS (Paramètres › API & Intégrations)
    fc_live_… — shown once, stored as a SHA-256 hash. « Lecture » or
    « Lecture + écriture ». 120 requests a minute per key. Revocable.

PUBLIC API  /api/v1 — header « Authorization: Bearer fc_live_… » (or X-API-Key)
    GET  /api/v1/me                      the business and its card rules
    GET  /api/v1/customers               list (search, updated_since, page)
    GET  /api/v1/customers/{ref}         by id, card number (FT-…) or phone
    POST /api/v1/customers               create a card (consent required)
    POST /api/v1/visits                  record a visit / sale — the same
                                         rules as a scan at the counter
                                         (stamps, points, tiers, rewards);
                                         external_id makes it idempotent
    GET  /api/v1/visits                  list (customer, since, page)
    POST /api/v1/rewards/redeem          the customer uses a reward

WEBHOOKS
    customer.created, visit.created, reward.unlocked, reward.redeemed —
    POST JSON to the business's URL, signed:
    X-FidClic-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>
    Every delivery is logged; failed ones are retried by the daily cron
    (3 tries) and can be re-sent by hand.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import TokenData, require_role
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["api"])
_db = None
OWNER = ["business_owner"]
READERS = ["business_owner", "administrateur"]
EVENTS = {"customer.created": "Nouveau client (carte créée)", "visit.created": "Nouveau passage / achat",
          "reward.unlocked": "Récompense débloquée", "reward.redeemed": "Récompense utilisée"}
RATE_PER_MINUTE = 120
MAX_KEYS = 10
MAX_HOOKS = 10
TIMEOUT_S = 4
RETRIES = 3


def init(db):
    global _db
    _db = db
    try:
        db.api_keys.create_index("hash", unique=True)
        db.api_idempotency.create_index([("tenant_id", 1), ("key", 1)], unique=True)
        db.webhook_deliveries.create_index([("tenant_id", 1), ("at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return v if isinstance(v, str) else None


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _plan_ok(tenant_id: str) -> bool:
    from features import plan_limits
    return plan_limits.allows_tenant(tenant_id, "api_access")


def _locked(tenant_id: str) -> HTTPException:
    from features import plan_limits
    return HTTPException(status_code=403, detail=plan_limits.locked(plan_limits.tenant_features(tenant_id), "api_access"))


# ---------------------------------------------------------------------------
# Key authentication for /api/v1
# ---------------------------------------------------------------------------
class ApiCaller(BaseModel):
    tenant_id: str
    key_id: str
    key_name: str
    scopes: List[str]


def api_caller(request: Request) -> ApiCaller:
    h = request.headers.get("authorization") or ""
    raw = h[7:].strip() if h.lower().startswith("bearer ") else (request.headers.get("x-api-key") or "").strip()
    if not raw.startswith("fc_live_"):
        raise HTTPException(status_code=401, detail={"code": "missing_api_key",
                                                     "message": "Clé API manquante : en-tête « Authorization: Bearer fc_live_… »."})
    k = _db.api_keys.find_one({"hash": _hash(raw)}, {"_id": 0})
    if not k or k.get("revoked_at"):
        raise HTTPException(status_code=401, detail={"code": "invalid_api_key", "message": "Clé API invalide ou révoquée."})
    t = _db.tenants.find_one({"id": k["tenant_id"]}, {"_id": 0, "id": 1, "suspended_at": 1, "is_active": 1})
    if t is None or t.get("suspended_at") or t.get("is_active") is False:
        raise HTTPException(status_code=403, detail={"code": "business_suspended", "message": "Ce commerce est suspendu."})
    if not _plan_ok(k["tenant_id"]):
        raise _locked(k["tenant_id"])
    minute = int(time.time() // 60)
    doc = _db.api_rate.find_one_and_update({"key_id": k["id"], "minute": minute}, {"$inc": {"n": 1}, "$setOnInsert": {"at": _now()}},
                                           upsert=True, return_document=True) or {}
    if int(doc.get("n") or 0) > RATE_PER_MINUTE:
        raise HTTPException(status_code=429, detail={"code": "rate_limited",
                                                     "message": f"Limite de {RATE_PER_MINUTE} requêtes par minute atteinte. Réessayez dans un instant."})
    _db.api_keys.update_one({"id": k["id"]}, {"$set": {"last_used_at": _now()}, "$inc": {"calls": 1}})
    return ApiCaller(tenant_id=k["tenant_id"], key_id=k["id"], key_name=k.get("name") or "", scopes=k.get("scopes") or ["read"])


def writer(c: ApiCaller = Depends(api_caller)) -> ApiCaller:
    if "write" not in c.scopes:
        raise HTTPException(status_code=403, detail={"code": "read_only_key", "message": "Cette clé est en lecture seule."})
    return c


def _as_owner(c: ApiCaller) -> TokenData:
    """The existing flows (scan, redeem) run as the business itself."""
    return TokenData(email=f"api:{c.key_name or c.key_id}", role="business_owner", tenant_id=c.tenant_id)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
def _threshold(tenant_id: str) -> int:
    tpl = _db.card_templates.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
    return max(1, int(tpl.get("reward_threshold_stamps", 10) or 10) * int(tpl.get("visits_per_stamp", 1) or 1))


def _card_url(barcode: str) -> str:
    import os
    base = (os.environ.get("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")
    from services import card_owner as CO
    return CO.owner_url(base, barcode)       # sent to the customer: the owner's link


def customer_out(c: Dict[str, Any], threshold: Optional[int] = None) -> Dict[str, Any]:
    threshold = threshold or _threshold(c["tenant_id"])
    visits = int(c.get("visits") or 0)
    stamps = max(0, visits - int(c.get("visits_at_last_redemption") or 0))
    name = c.get("name") or ""
    return {"id": c["id"], "card_number": c.get("barcode_id"), "card_url": _card_url(c.get("barcode_id") or ""),
            "name": name, "first_name": c.get("first_name") or (name.split(" ")[0] if name else ""),
            "email": c.get("email") or None, "phone": c.get("phone") or None, "postal_code": c.get("postal_code") or None,
            "birthday": c.get("birthday") or None, "tier": c.get("tier") or "bronze", "points": int(c.get("points") or 0),
            "visits": visits, "stamps": min(stamps, threshold), "reward_threshold": threshold, "reward_unlocked": stamps >= threshold,
            "rewards_pending": _db.rewards_earned.count_documents({"customer_id": c["id"], "status": "pending"}),
            "total_spent": round(float(c.get("total_amount_paid") or 0), 2),
            "created_at": _iso(c.get("created_at")), "last_visit_at": _iso(c.get("last_visit_date"))}


def visit_out(v: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": v.get("id"), "customer_id": v.get("customer_id"), "amount": round(float(v.get("amount_paid") or 0), 2),
            "points": int(v.get("points_awarded") or 0), "items": v.get("items") or [], "branch_id": v.get("branch_id"),
            "external_id": v.get("external_id"), "source": v.get("source") or "scan", "at": _iso(v.get("visit_time"))}


LIVE = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}], "card_deleted_at": {"$exists": False}}


def _find_customer(tenant_id: str, ref: str) -> Dict[str, Any]:
    import server as core
    ref = (ref or "").strip()
    c = None
    if ref:
        c = _db.customers.find_one({**LIVE, "tenant_id": tenant_id, "id": ref}, {"_id": 0})
        if not c:
            c = _db.customers.find_one({**LIVE, "tenant_id": tenant_id, "barcode_id": core.barcode_from(ref)}, {"_id": 0})
        if not c:
            digits = re.sub(r"\D", "", ref)
            if len(digits) >= 9:
                tail = digits[-9:]              # « 06 12… », « +33 6 12… », « 0033612… » are one number
                for cand in _db.customers.find({**LIVE, "tenant_id": tenant_id, "phone": {"$nin": [None, ""]}},
                                               {"_id": 0, "id": 1, "phone": 1}):
                    if re.sub(r"\D", "", cand.get("phone") or "").endswith(tail):
                        c = _db.customers.find_one({"id": cand["id"]}, {"_id": 0})
                        break
    if not c:
        raise HTTPException(status_code=404, detail={"code": "customer_not_found", "message": "Client introuvable (id, numéro de carte ou téléphone)."})
    return c


def _idempotent(tenant_id: str, kind: str, external_id: Optional[str]):
    if not external_id:
        return None
    return _db.api_idempotency.find_one({"tenant_id": tenant_id, "key": f"{kind}:{external_id}"}, {"_id": 0})


def _remember(tenant_id: str, kind: str, external_id: Optional[str], response: Dict[str, Any]) -> None:
    if not external_id:
        return
    try:
        _db.api_idempotency.insert_one({"tenant_id": tenant_id, "key": f"{kind}:{external_id}", "response": response, "at": _now()})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /api/v1
# ---------------------------------------------------------------------------
@router.get("/api/v1/me")
def me(c: ApiCaller = Depends(api_caller)):
    import server as core
    t = _db.tenants.find_one({"id": c.tenant_id}, {"_id": 0}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": c.tenant_id}, {"_id": 0}) or {}
    return {"business": {"id": t.get("id"), "name": t.get("name"), "slug": t.get("slug"), "city": t.get("city"),
                         "sector": t.get("sector"), "branches": [{"id": b.get("id"), "name": b.get("name")} for b in t.get("branches") or []]},
            "plan": core.plan_label(t.get("plan")),
            "card": {"reward_threshold": _threshold(c.tenant_id), "reward": tpl.get("reward_description") or None,
                     "points_mode": tpl.get("points_mode") or "per_visit"},
            "key": {"name": c.key_name, "scopes": c.scopes}}


@router.get("/api/v1/customers")
def list_customers(search: str = "", updated_since: Optional[str] = None, page: int = 1, per_page: int = 50,
                   c: ApiCaller = Depends(api_caller)):
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    f: Dict[str, Any] = {**LIVE, "tenant_id": c.tenant_id}
    if search.strip():
        rx = {"$regex": re.escape(search.strip()), "$options": "i"}
        f = {**f, "$and": [{"$or": [{"name": rx}, {"email": rx}, {"phone": rx}, {"barcode_id": rx}]}]}
    if updated_since:
        try:
            since = datetime.fromisoformat(updated_since.replace("Z", "+00:00"))
            f["$and"] = f.get("$and", []) + [{"$or": [{"updated_at": {"$gte": since}}, {"created_at": {"$gte": since}},
                                                     {"last_visit_date": {"$gte": since}}]}]
        except ValueError:
            raise HTTPException(status_code=400, detail={"code": "bad_date", "message": "updated_since : date ISO 8601 attendue."})
    total = _db.customers.count_documents(f)
    thr = _threshold(c.tenant_id)
    rows = list(_db.customers.find(f, {"_id": 0}).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page))
    return {"data": [customer_out(x, thr) for x in rows], "page": page, "per_page": per_page, "total": total,
            "has_more": page * per_page < total}


@router.get("/api/v1/customers/{ref}")
def get_customer(ref: str, c: ApiCaller = Depends(api_caller)):
    return customer_out(_find_customer(c.tenant_id, ref))


class CustomerIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=6, max_length=30)
    email: Optional[str] = Field("", max_length=200)
    postal_code: Optional[str] = Field("", max_length=10)
    birthday: Optional[str] = Field("", max_length=10)
    consent: bool = False
    source: Optional[str] = Field(None, max_length=40)


@router.post("/api/v1/customers", status_code=201)
def create_customer(body: CustomerIn, c: ApiCaller = Depends(writer)):
    """Same path as the sign-up page: plan caps, duplicates (same phone or
    email → the existing card), consent proof."""
    import server as core
    if not body.consent:
        raise HTTPException(status_code=400, detail={"code": "consent_required",
                                                     "message": "consent: true requis — le client doit avoir accepté le programme de fidélité."})
    t = _db.tenants.find_one({"id": c.tenant_id}, {"_id": 0, "slug": 1})
    before = _db.customers.count_documents({"tenant_id": c.tenant_id})
    res = core.join_program(t["slug"], core.JoinRequest(name=body.name, phone=body.phone, email=body.email or "",
                                                          postal_code=body.postal_code or "", birthday=body.birthday or "",
                                                          consent=True, acquisition_source=None))
    cust = _db.customers.find_one({"tenant_id": c.tenant_id, "barcode_id": res["barcode_id"]}, {"_id": 0})
    if body.source:
        _db.customers.update_one({"id": cust["id"]}, {"$set": {"api_source": body.source[:40]}})
    created = _db.customers.count_documents({"tenant_id": c.tenant_id}) > before
    return {**customer_out(cust), "created": created}


class VisitIn(BaseModel):
    customer: str = Field(..., description="id, card number (FT-…) or phone")
    amount: float = Field(0, ge=0, le=100000)
    items: Optional[List[Dict[str, Any]]] = None      # [{item_id, qty}] from the business's catalogue
    branch_id: Optional[str] = None
    external_id: Optional[str] = Field(None, max_length=120)   # the ticket number: sent twice, counted once


@router.post("/api/v1/visits", status_code=201)
def create_visit(body: VisitIn, c: ApiCaller = Depends(writer)):
    import server as core
    hit = _idempotent(c.tenant_id, "visit", body.external_id)
    if hit:
        return {**hit["response"], "duplicate": True}
    cust = _find_customer(c.tenant_id, body.customer)
    res = core.scan_visit(core.ScanRequest(barcode_id=cust["barcode_id"], amount_paid=body.amount, items=body.items,
                                           branch_id=body.branch_id), token_data=_as_owner(c))
    v = _db.visits.find_one({"tenant_id": c.tenant_id, "customer_id": cust["id"]}, {"_id": 0}, sort=[("visit_time", -1)]) or {}
    if v.get("id"):
        _db.visits.update_one({"id": v["id"]}, {"$set": {"source": "api", "external_id": body.external_id, "api_key_id": c.key_id}})
        v.update(source="api", external_id=body.external_id)
    out = {"visit": visit_out(v), "customer": customer_out(_db.customers.find_one({"id": cust["id"]}, {"_id": 0})),
           "tier_upgraded": bool(res.get("tier_upgraded")), "reward_unlocked": bool(res.get("reward_unlocked"))}
    _remember(c.tenant_id, "visit", body.external_id, out)
    return {**out, "duplicate": False}


@router.get("/api/v1/visits")
def list_visits(customer: Optional[str] = None, since: Optional[str] = None, page: int = 1, per_page: int = 50,
                c: ApiCaller = Depends(api_caller)):
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    f: Dict[str, Any] = {"tenant_id": c.tenant_id}
    if customer:
        f["customer_id"] = _find_customer(c.tenant_id, customer)["id"]
    if since:
        try:
            f["visit_time"] = {"$gte": datetime.fromisoformat(since.replace("Z", "+00:00"))}
        except ValueError:
            raise HTTPException(status_code=400, detail={"code": "bad_date", "message": "since : date ISO 8601 attendue."})
    total = _db.visits.count_documents(f)
    rows = list(_db.visits.find(f, {"_id": 0}).sort("visit_time", -1).skip((page - 1) * per_page).limit(per_page))
    return {"data": [visit_out(v) for v in rows], "page": page, "per_page": per_page, "total": total, "has_more": page * per_page < total}


class RedeemIn(BaseModel):
    customer: str
    reward_name: Optional[str] = Field(None, max_length=120)
    external_id: Optional[str] = Field(None, max_length=120)


@router.post("/api/v1/rewards/redeem")
def redeem(body: RedeemIn, c: ApiCaller = Depends(writer)):
    import server as core
    hit = _idempotent(c.tenant_id, "redeem", body.external_id)
    if hit:
        return {**hit["response"], "duplicate": True}
    cust = _find_customer(c.tenant_id, body.customer)
    if customer_out(cust)["rewards_pending"] == 0 and not customer_out(cust)["reward_unlocked"]:
        raise HTTPException(status_code=409, detail={"code": "no_reward", "message": "Ce client n'a pas de récompense disponible."})
    core.redeem_reward(core.RedeemRewardRequest(customer_id=cust["id"], reward_name=body.reward_name, notes="API"), token_data=_as_owner(c))
    out = {"customer": customer_out(_db.customers.find_one({"id": cust["id"]}, {"_id": 0})), "redeemed": True}
    _remember(c.tenant_id, "redeem", body.external_id, out)
    return {**out, "duplicate": False}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
def sign(secret: str, body: bytes, ts: Optional[int] = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def _deliver(hook: Dict[str, Any], event: Dict[str, Any], attempt: int = 1, delivery_id: Optional[str] = None) -> Dict[str, Any]:
    import requests
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
    started = time.time()
    status, err = None, None
    try:
        r = requests.post(hook["url"], data=body, timeout=TIMEOUT_S, headers={
            "Content-Type": "application/json", "User-Agent": "FidClic-Webhooks/1.0", "X-FidClic-Event": event["type"],
            "X-FidClic-Delivery": event["id"], "X-FidClic-Signature": sign(hook["secret"], body)})
        status = r.status_code
    except Exception as e:                       # network, timeout, DNS
        err = f"{type(e).__name__}: {str(e)[:160]}"
    ok = status is not None and 200 <= status < 300
    row = {"tenant_id": hook["tenant_id"], "hook_id": hook["id"], "event_id": event["id"], "type": event["type"], "payload": event,
           "status": status, "ok": ok, "error": err, "ms": int((time.time() - started) * 1000), "attempts": attempt, "at": _now()}
    if delivery_id:
        _db.webhook_deliveries.update_one({"id": delivery_id}, {"$set": row})
        row["id"] = delivery_id
    else:
        row["id"] = uuid.uuid4().hex
        _db.webhook_deliveries.insert_one(dict(row))
    _db.webhooks.update_one({"id": hook["id"]}, {"$set": {"last_status": status, "last_ok": ok, "last_at": _now()},
                                                 "$inc": {"failures": 0 if ok else 1}})
    if ok:
        _db.webhooks.update_one({"id": hook["id"]}, {"$set": {"failures": 0}})
    return row


def emit(tenant_id: Optional[str], kind: str, data: Dict[str, Any]) -> int:
    """Send `kind` to the business's webhooks. Never raises; returns how many
    endpoints were called."""
    if not tenant_id or kind not in EVENTS:
        return 0
    try:
        hooks = list(_db.webhooks.find({"tenant_id": tenant_id, "active": True, "events": kind}, {"_id": 0}))
        if not hooks or not _plan_ok(tenant_id):
            return 0
        event = {"id": "evt_" + uuid.uuid4().hex[:24], "type": kind, "created_at": _now().isoformat(), "data": data}
        for h in hooks:
            _deliver(h, event)
        return len(hooks)
    except Exception as e:
        print(f"webhooks: {kind} for {tenant_id} failed: {e}")
        return 0


def emit_customer(kind: str, tenant_id: Optional[str], customer_id: Optional[str], extra: Optional[Dict[str, Any]] = None,
                  with_visit: bool = False) -> None:
    """Hook for the core flows (join, scan, redeem)."""
    try:
        if not tenant_id or not _db.webhooks.find_one({"tenant_id": tenant_id, "active": True, "events": kind}, {"_id": 1}):
            return
        c = _db.customers.find_one({"id": customer_id}, {"_id": 0})
        if c:
            extra = dict(extra or {})
            if with_visit:
                v = _db.visits.find_one({"tenant_id": tenant_id, "customer_id": customer_id}, {"_id": 0}, sort=[("visit_time", -1)])
                extra["visit"] = visit_out(v) if v else None
            emit(tenant_id, kind, {"customer": customer_out(c), **extra})
    except Exception as e:
        print(f"webhooks: {kind} skipped: {e}")


def retry_failed(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Daily cron: failed deliveries of the last 3 days, up to RETRIES tries."""
    now = now or _now()
    n = ok = 0
    for d in list(_db.webhook_deliveries.find({"ok": False, "attempts": {"$lt": RETRIES}, "at": {"$gte": now - timedelta(days=3)}}, {"_id": 0}).limit(500)):
        h = _db.webhooks.find_one({"id": d["hook_id"], "active": True}, {"_id": 0})
        if not h or not _plan_ok(h["tenant_id"]):
            continue
        r = _deliver(h, d["payload"], attempt=int(d.get("attempts") or 1) + 1, delivery_id=d["id"])
        n += 1
        ok += bool(r["ok"])
    return {"retried": n, "ok": ok}


# ---------------------------------------------------------------------------
# Paramètres › API & Intégrations (owner)
# ---------------------------------------------------------------------------
def _need_plan(token_data: TokenData) -> None:
    if not _plan_ok(token_data.tenant_id):
        raise _locked(token_data.tenant_id)


def _key_out(k: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": k["id"], "name": k.get("name"), "prefix": k.get("prefix"), "scopes": k.get("scopes") or ["read"],
            "created_at": _iso(k.get("created_at")), "created_by": k.get("created_by"), "last_used_at": _iso(k.get("last_used_at")),
            "calls": int(k.get("calls") or 0), "revoked": bool(k.get("revoked_at"))}


def _hook_out(h: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": h["id"], "url": h["url"], "events": h.get("events") or [], "active": bool(h.get("active")),
            "secret": h.get("secret"), "created_at": _iso(h.get("created_at")), "last_status": h.get("last_status"),
            "last_ok": h.get("last_ok"), "last_at": _iso(h.get("last_at")), "failures": int(h.get("failures") or 0)}


@router.get("/api/owner/integrations")
def page(token_data: TokenData = Depends(require_role(READERS))):
    _need_plan(token_data)
    tid = token_data.tenant_id
    keys = [_key_out(k) for k in _db.api_keys.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", -1)]
    hooks = [_hook_out(h) for h in _db.webhooks.find({"tenant_id": tid}, {"_id": 0}).sort("created_at", -1)]
    deliveries = [{k: (v if k != "at" else _iso(v)) for k, v in d.items() if k != "payload"}
                  for d in _db.webhook_deliveries.find({"tenant_id": tid}, {"_id": 0}).sort("at", -1).limit(20)]
    since = _now() - timedelta(days=30)
    return {"keys": keys, "webhooks": hooks, "deliveries": deliveries, "events": [{"key": k, "label": v} for k, v in EVENTS.items()],
            "base_url": "https://app.fidclic.com/api/v1", "rate_per_minute": RATE_PER_MINUTE,
            "stats": {"calls_30d": _db.visits.count_documents({"tenant_id": tid, "source": "api", "visit_time": {"$gte": since}}),
                      "active_keys": sum(1 for k in keys if not k["revoked"]), "active_hooks": sum(1 for h in hooks if h["active"])}}


class KeyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    write: bool = False


@router.post("/api/owner/integrations/keys", status_code=201)
def create_key(body: KeyIn, token_data: TokenData = Depends(require_role(OWNER))):
    import server as core
    _need_plan(token_data)
    if _db.api_keys.count_documents({"tenant_id": token_data.tenant_id, "revoked_at": None}) >= MAX_KEYS:
        raise HTTPException(status_code=400, detail=f"{MAX_KEYS} clés actives au maximum : révoquez-en une d'abord.")
    raw = "fc_live_" + secrets.token_urlsafe(30).replace("-", "").replace("_", "")[:40]
    k = {"id": uuid.uuid4().hex, "tenant_id": token_data.tenant_id, "name": body.name.strip(), "prefix": raw[:14],
         "hash": _hash(raw), "scopes": ["read", "write"] if body.write else ["read"], "created_at": _now(),
         "created_by": token_data.email, "revoked_at": None, "calls": 0}
    _db.api_keys.insert_one(dict(k))
    core.log_audit("api.key_create", actor=token_data.email, actor_type="user", tenant_id=token_data.tenant_id, target=k["id"],
                   meta={"name": k["name"], "scopes": k["scopes"]})
    return {**_key_out(k), "key": raw}


@router.delete("/api/owner/integrations/keys/{key_id}")
def revoke_key(key_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    import server as core
    r = _db.api_keys.update_one({"id": key_id, "tenant_id": token_data.tenant_id, "revoked_at": None}, {"$set": {"revoked_at": _now()}})
    if not r.modified_count:
        raise HTTPException(status_code=404, detail="Clé introuvable.")
    core.log_audit("api.key_revoke", actor=token_data.email, actor_type="user", tenant_id=token_data.tenant_id, target=key_id)
    return {"ok": True}


class HookIn(BaseModel):
    url: str = Field(..., max_length=500)
    events: List[str]
    active: bool = True


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if not re.match(r"^https://[^\s/]+\.[^\s]+", url):
        raise HTTPException(status_code=400, detail="L'adresse doit commencer par https:// (ex. https://votre-outil.fr/fidclic).")
    host = re.sub(r"^https://([^/:?#]+).*$", r"\1", url).lower()
    if host in ("localhost",) or host.endswith(".local") or re.match(r"^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)", host):
        raise HTTPException(status_code=400, detail="Adresse interne refusée : utilisez une adresse publique.")
    return url


def _check_events(events: List[str]) -> List[str]:
    ev = [e for e in dict.fromkeys(events) if e in EVENTS]
    if not ev:
        raise HTTPException(status_code=400, detail="Choisissez au moins un événement.")
    return ev


@router.post("/api/owner/integrations/webhooks", status_code=201)
def create_hook(body: HookIn, token_data: TokenData = Depends(require_role(OWNER))):
    import server as core
    _need_plan(token_data)
    if _db.webhooks.count_documents({"tenant_id": token_data.tenant_id}) >= MAX_HOOKS:
        raise HTTPException(status_code=400, detail=f"{MAX_HOOKS} webhooks au maximum.")
    h = {"id": uuid.uuid4().hex, "tenant_id": token_data.tenant_id, "url": _check_url(body.url), "events": _check_events(body.events),
         "active": body.active, "secret": "whsec_" + secrets.token_hex(24), "created_at": _now(), "created_by": token_data.email, "failures": 0}
    _db.webhooks.insert_one(dict(h))
    core.log_audit("api.webhook_create", actor=token_data.email, actor_type="user", tenant_id=token_data.tenant_id, target=h["id"],
                   meta={"url": h["url"], "events": h["events"]})
    return _hook_out(h)


@router.put("/api/owner/integrations/webhooks/{hook_id}")
@SV.records("api")
def edit_hook(hook_id: str, body: HookIn, token_data: TokenData = Depends(require_role(OWNER))):
    _need_plan(token_data)
    r = _db.webhooks.update_one({"id": hook_id, "tenant_id": token_data.tenant_id},
                                {"$set": {"url": _check_url(body.url), "events": _check_events(body.events), "active": body.active}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Webhook introuvable.")
    return _hook_out(_db.webhooks.find_one({"id": hook_id}, {"_id": 0}))


@router.delete("/api/owner/integrations/webhooks/{hook_id}")
def delete_hook(hook_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    import server as core
    r = _db.webhooks.delete_one({"id": hook_id, "tenant_id": token_data.tenant_id})
    if not r.deleted_count:
        raise HTTPException(status_code=404, detail="Webhook introuvable.")
    core.log_audit("api.webhook_delete", actor=token_data.email, actor_type="user", tenant_id=token_data.tenant_id, target=hook_id)
    return {"ok": True}


@router.post("/api/owner/integrations/webhooks/{hook_id}/test")
def test_hook(hook_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    _need_plan(token_data)
    h = _db.webhooks.find_one({"id": hook_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not h:
        raise HTTPException(status_code=404, detail="Webhook introuvable.")
    event = {"id": "evt_test_" + uuid.uuid4().hex[:16], "type": "test", "created_at": _now().isoformat(),
             "data": {"message": "Test FidClic — votre webhook est bien relié."}}
    d = _deliver(h, event)
    return {"ok": d["ok"], "status": d["status"], "error": d["error"], "ms": d["ms"]}


@router.post("/api/owner/integrations/deliveries/{delivery_id}/resend")
def resend(delivery_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    _need_plan(token_data)
    d = _db.webhook_deliveries.find_one({"id": delivery_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    h = _db.webhooks.find_one({"id": (d or {}).get("hook_id"), "tenant_id": token_data.tenant_id}, {"_id": 0}) if d else None
    if not d or not h:
        raise HTTPException(status_code=404, detail="Envoi introuvable.")
    r = _deliver(h, d["payload"], attempt=int(d.get("attempts") or 1) + 1, delivery_id=d["id"])
    return {"ok": r["ok"], "status": r["status"], "error": r["error"]}
