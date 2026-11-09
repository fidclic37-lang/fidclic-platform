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
    GET  /api/v1/customers/{ref}         by id, card number (FT-…), phone (any
                                         format) or e-mail; two clients on one
                                         phone / e-mail → 409, never a guess
    POST /api/v1/customers               create a card (consent required)
    POST /api/v1/visits                  record a visit / sale — the same
                                         rules as a scan at the counter
                                         (stamps, points, tiers, rewards);
                                         external_id makes it idempotent
    GET  /api/v1/visits                  list (customer, since, page)
    POST /api/v1/visits/{ref}/cancel     a refund: by visit id or external_id;
                                         takes back what the visit gave
    POST /api/v1/rewards/hold            a borne locks a reward while the client
    DELETE /api/v1/rewards/hold/{id}     pays (30 s – 15 min), or lets it go
    POST /api/v1/rewards/redeem          the customer uses a reward
    POST /api/v1/customers/{ref}/verification         SMS code to the client,
    POST /api/v1/customers/{ref}/verification/check   then a one-use token;
                                         an « online » key redeems only with it

IDEMPOTENCY (2026-11-09)
    external_id is reserved BEFORE the work (a unique row), so the same ticket
    sent twice at once is written once; the same id with another body → 422;
    a call that failed frees its id; one that died is taken over after 60 s.

WEBHOOKS
    customer.created, visit.created, visit.cancelled, reward.unlocked,
    reward.redeemed — POST JSON to the business's URL, signed:
    X-FidClic-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "<t>.<body>")>
    Never to an internal address (checked at creation AND on every send, after
    DNS), never following a redirect; sent from a shared pool in the background,
    so the caller (the till) never waits for them. Every delivery is logged; failed
    ones are retried by the 15-minute tick and the daily cron (3 tries) and can
    be re-sent by hand. A delivery may arrive twice: dedupe on X-FidClic-Delivery.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import socket
import time
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor, wait as _wait_all
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import TokenData, require_role
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["api"])
_db = None
OWNER = ["business_owner"]
READERS = ["business_owner", "administrateur"]
EVENTS = {"customer.created": "Nouveau client (carte créée)", "visit.created": "Nouveau passage / achat",
          "visit.cancelled": "Passage annulé (remboursement)",
          "reward.unlocked": "Récompense débloquée", "reward.redeemed": "Récompense utilisée"}
API_VERSION = "2026-11-09"
RATE_PER_MINUTE = 120
MAX_KEYS = 10
MAX_HOOKS = 10
TIMEOUT_S = 3                 # one webhook endpoint
WEBHOOK_WORKERS = 8           # threads sending webhooks, shared by the instance; the caller never waits
WEBHOOK_QUEUE_MAX = 500       # deliveries held in memory at most; beyond, they wait (written down) for the tick
RETRIES = 3
IN_PROGRESS_S = 60            # an idempotent call older than this died: taken over
IDEMPOTENCY_DAYS = 30
CANCEL_MAX_DAYS = 90          # a refund later than this is a manual adjustment, not an API cancel
HOLD_MIN_S, HOLD_MAX_S, HOLD_DEFAULT_S = 30, 900, 300
HOLDS_PER_HOUR = 3            # holds per client per hour that did not end in a used reward
PHONE_TAIL_MIGRATION = "phone_tail_v1"
VERIFY_TTL_S = 600            # an SMS code
VERIFY_TOKEN_TTL_S = 900      # the token it gives
VERIFY_MAX_ATTEMPTS = 5
VERIFY_PER_HOUR = 3           # codes per client per hour
VERIFY_PER_DAY = 200          # codes per shop per day (SMS cost, SMS pumping)
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa", ".corp", ".intranet")

# While the API runs the counter's scan, the scan's own webhook would describe
# the visit before it is tagged (external_id, source): the API sends it itself.
_EMIT_SUSPENDED: contextvars.ContextVar = contextvars.ContextVar("fidclic_api_emit_suspended", default=False)


def init(db):
    global _db
    _db = db
    for coll, keys, kw in (
            ("api_keys", "hash", {"unique": True}),
            ("api_idempotency", [("tenant_id", 1), ("key", 1)], {"unique": True}),
            ("api_idempotency", "at", {"expireAfterSeconds": IDEMPOTENCY_DAYS * 86400, "name": "at_ttl"}),
            ("api_rate", [("key_id", 1), ("minute", 1)], {}),
            ("api_rate", "at", {"expireAfterSeconds": 2 * 3600, "name": "at_ttl"}),
            ("api_verifications", [("tenant_id", 1), ("customer_id", 1), ("at", -1)], {}),
            ("api_verifications", "token_hash", {"sparse": True}),
            ("api_verifications", "at", {"expireAfterSeconds": 86400, "name": "at_ttl"}),
            ("api_reward_holds", "id", {"unique": True}),
            ("api_reward_holds", "at", {"expireAfterSeconds": 7 * 86400, "name": "at_ttl"}),
            ("visits_cancelled", [("tenant_id", 1), ("id", 1)], {}),
            ("visits_cancelled", [("tenant_id", 1), ("external_id", 1)], {}),
            ("visits", [("tenant_id", 1), ("external_id", 1)], {"sparse": True}),
            ("customers", [("tenant_id", 1), ("phone_tail", 1)], {}),
            # a client is read by id on every scan, and by card number at the till and the API:
            # nothing indexed either before (#454 load lab: a scan of the whole collection each time)
            ("customers", "id", {}),
            ("customers", [("tenant_id", 1), ("barcode_id", 1)], {}),
            ("webhook_deliveries", [("tenant_id", 1), ("at", -1)], {}),
            ("webhook_deliveries", [("ok", 1), ("at", -1)], {})):
        try:                                  # one index failing (an old one of the same name) never stops the rest
            db[coll].create_index(keys, **kw)
        except Exception as e:
            print(f"merchant_api: index {coll} {keys} skipped: {e}")
    # every write of a client's phone also writes its 9 last digits (services/phone_tail)
    from services import doc_cache, phone_tail
    doc_cache.on_write("customers", phone_tail.hear)
    backfill_phone_tails()


def backfill_phone_tails(batch: int = 2000, cap: int = 50000) -> int:
    """Once: the clients written before the tail existed get theirs. Marked
    done in platform_settings only when none is left, so a start cut short
    goes on at the next. Never fatal."""
    from services import phone_tail
    try:
        if (_db.platform_settings.find_one({"key": PHONE_TAIL_MIGRATION}, {"_id": 0, "value": 1}) or {}).get("value") == "done":
            return 0
        n = 0
        while n < cap:
            rows = list(_db.customers.find({"phone_tail": {"$exists": False}}, {"_id": 1, "phone": 1}).limit(batch))
            if not rows:
                break
            from pymongo import UpdateOne
            _db.customers.bulk_write([UpdateOne({"_id": r["_id"], "phone_tail": {"$exists": False}},
                                                {"$set": {"phone_tail": phone_tail.tail(r.get("phone"))}}) for r in rows],
                                     ordered=False)
            n += len(rows)
        if not _db.customers.find_one({"phone_tail": {"$exists": False}}, {"_id": 1}):
            _db.platform_settings.update_one({"key": PHONE_TAIL_MIGRATION}, {"$set": {
                "key": PHONE_TAIL_MIGRATION, "value": "done", "at": _now(), "customers": n}}, upsert=True)
        if n:
            print(f"clients: phone tail written for {n} customers", flush=True)
        return n
    except Exception as e:  # noqa: BLE001 — a start must never fail on it
        print(f"clients: phone tail not written yet ({e})", flush=True)
        return 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, **extra})


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
    online: bool = False           # a website's key: a reward is used only after an SMS code


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
    return ApiCaller(tenant_id=k["tenant_id"], key_id=k["id"], key_name=k.get("name") or "", scopes=k.get("scopes") or ["read"],
                     online=bool(k.get("online")))


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


def _reward_available(c: Dict[str, Any], stamps: int, threshold: int) -> bool:
    import server as core
    from features import loyalty_card as LC
    tpl = _db.card_templates.find_one({"tenant_id": c["tenant_id"]}) or {}
    points_prog = LC._is_points(LC._programme(tpl))
    price = max(int(tpl.get("reward_points") or 0), 0)
    earned = (core._reward_earned_before(c, threshold, price, True) if points_prog and price
              else not points_prog and stamps - int(c.get("last_scan_units") or 0) >= threshold)
    return earned or _db.rewards_earned.count_documents(core.claimable_query(c)) > 0


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
            # false until the visit after the one that earned it (user, 2026-11-04)
            "reward_available": _reward_available(c, stamps, threshold),
            "total_spent": round(float(c.get("total_amount_paid") or 0), 2),
            "created_at": _iso(c.get("created_at")), "last_visit_at": _iso(c.get("last_visit_date"))}


def visit_out(v: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": v.get("id"), "customer_id": v.get("customer_id"), "amount": round(float(v.get("amount_paid") or 0), 2),
            "points": int(v.get("points_awarded") or 0), "items": v.get("items") or [], "branch_id": v.get("branch_id"),
            "external_id": v.get("external_id"), "source": v.get("source") or "scan", "at": _iso(v.get("visit_time"))}


LIVE = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}], "card_deleted_at": {"$exists": False}}


def _one(rows: List[Dict[str, Any]], what: str) -> Optional[Dict[str, Any]]:
    """One client, or none — two (a family on one phone, an old duplicate) is
    never settled by picking one: the caller asks with the card number."""
    ids = list(dict.fromkeys(r["id"] for r in rows if r.get("id")))
    if len(ids) > 1:
        raise _err(409, "ambiguous_customer", f"Plusieurs clients ont ce {what} : utilisez le numéro de carte (FT-…).",
                   matches=len(ids))
    return _db.customers.find_one({"id": ids[0]}, {"_id": 0}) if ids else None


def _find_customer(tenant_id: str, ref: str) -> Dict[str, Any]:
    """By id, card number, e-mail or phone — always inside this shop, never a
    deleted card. The text is plain text: no pattern a caller sends reaches
    the database as one."""
    import server as core
    ref = (ref or "").strip()
    c = None
    if ref:
        c = _db.customers.find_one({**LIVE, "tenant_id": tenant_id, "id": ref}, {"_id": 0})
        if not c:
            c = _db.customers.find_one({**LIVE, "tenant_id": tenant_id, "barcode_id": core.barcode_from(ref)}, {"_id": 0})
        if not c and "@" in ref:
            rows = list(_db.customers.find({**LIVE, "tenant_id": tenant_id,
                                            "email": {"$regex": "^" + re.escape(ref) + "$", "$options": "i"}},
                                           {"_id": 0, "id": 1}).limit(5))
            c = _one(rows, "e-mail")
        elif not c:
            digits = re.sub(r"\D", "", ref)
            if 9 <= len(digits) <= 15:
                tail = digits[-9:]              # « 06 12… », « +33 6 12… », « 0033612… » are one number
                # by the indexed tail (services/phone_tail); a client written before
                # it existed and not back-filled yet: the 9 digits, whatever sits between them
                rows = list(_db.customers.find({**LIVE, "tenant_id": tenant_id, "phone_tail": tail},
                                               {"_id": 0, "id": 1, "phone": 1}).limit(20))
                pattern = r"\D*".join(tail) + r"\D*$"
                rows += [r for r in _db.customers.find({**LIVE, "tenant_id": tenant_id, "phone_tail": {"$exists": False},
                                                        "phone": {"$regex": pattern}}, {"_id": 0, "id": 1, "phone": 1}).limit(20)
                         if re.sub(r"\D", "", r.get("phone") or "").endswith(tail)]
                c = _one(rows, "numéro de téléphone")
    if not c:
        raise _err(404, "customer_not_found", "Client introuvable (id, numéro de carte, téléphone ou e-mail).")
    return c


# ---------------------------------------------------------------------------
# Idempotency: the external_id is reserved before the work, not after it
# ---------------------------------------------------------------------------
def _fingerprint(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()[:32]


def _is_duplicate(e: Exception) -> bool:
    try:
        from pymongo.errors import DuplicateKeyError
        if isinstance(e, DuplicateKeyError):
            return True
    except Exception:
        pass
    return "duplicate" in type(e).__name__.lower() or "E11000" in str(e)


def _idem_begin(tenant_id: str, kind: str, external_id: Optional[str], fp: str) -> Optional[Dict[str, Any]]:
    """None: go ahead, the id is ours until _idem_done / _idem_abort. A dict:
    the answer already given for this id — send it again."""
    if not external_id:
        return None
    key = f"{kind}:{external_id}"
    for _round in range(3):
        try:
            _db.api_idempotency.insert_one({"tenant_id": tenant_id, "key": key, "state": "pending", "fp": fp, "at": _now()})
            return None
        except Exception as e:
            if not _is_duplicate(e):
                raise
        row = _db.api_idempotency.find_one({"tenant_id": tenant_id, "key": key}, {"_id": 0})
        if row is None:                       # freed between the two reads: try again
            continue
        if (row.get("state") or "done") == "done":      # rows from before 2026-11-09 have no state: they are done
            if row.get("fp") and row["fp"] != fp:
                raise _err(422, "idempotency_conflict",
                           f"external_id « {external_id} » a déjà servi pour une autre requête (autre client, montant ou articles).")
            return row.get("response") or {}
        # still pending: running elsewhere, or dead (then whatever it carried was never written)
        started = _aware(row.get("at")) or _now()
        if started > _now() - timedelta(seconds=IN_PROGRESS_S):
            raise _err(409, "request_in_progress",
                       f"Une requête avec external_id « {external_id} » est en cours : réessayez dans quelques secondes.")
        took = _db.api_idempotency.update_one({"tenant_id": tenant_id, "key": key, "state": "pending", "at": row.get("at")},
                                              {"$set": {"at": _now(), "fp": fp}})
        if getattr(took, "modified_count", 0):
            return None                       # the call that held it died: ours now
    raise _err(409, "request_in_progress", f"Une requête avec external_id « {external_id} » est en cours : réessayez.")


def _idem_done(tenant_id: str, kind: str, external_id: Optional[str], response: Dict[str, Any]) -> None:
    if external_id:
        _db.api_idempotency.update_one({"tenant_id": tenant_id, "key": f"{kind}:{external_id}"},
                                       {"$set": {"state": "done", "response": response, "at": _now()}})


def _idem_abort(tenant_id: str, kind: str, external_id: Optional[str]) -> None:
    """A call that failed gives its id back, so the corrected call can use it."""
    if external_id:
        try:
            _db.api_idempotency.delete_one({"tenant_id": tenant_id, "key": f"{kind}:{external_id}", "state": "pending"})
        except Exception as e:
            print(f"merchant_api: idempotency row not freed: {e}")


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
    customer: str = Field(..., description="id, card number (FT-…), phone or e-mail")
    amount: float = Field(0, ge=0, le=100000)
    items: Optional[List[Dict[str, Any]]] = None      # [{item_id, qty}] from the business's catalogue
    branch_id: Optional[str] = None
    external_id: Optional[str] = Field(None, max_length=120)   # the ticket number: sent twice, counted once


def _reward_unlocked_by(res: Dict[str, Any]) -> bool:
    """The rule the counter's scan uses for its own reward.unlocked."""
    return bool(res.get("reward_unlocked") and res.get("stamps_in_cycle") == res.get("reward_threshold"))


@router.post("/api/v1/visits", status_code=201)
def create_visit(body: VisitIn, c: ApiCaller = Depends(writer)):
    import server as core
    fp = _fingerprint({"customer": body.customer.strip(), "amount": round(float(body.amount or 0), 2),
                       "items": body.items or [], "branch_id": body.branch_id or ""})
    hit = _idem_begin(c.tenant_id, "visit", body.external_id, fp)
    if hit is not None:
        return {**hit, "duplicate": True}
    try:
        cust = _find_customer(c.tenant_id, body.customer)
        token = _EMIT_SUSPENDED.set(True)
        try:
            res = core.scan_visit(core.ScanRequest(barcode_id=cust["barcode_id"], amount_paid=body.amount, items=body.items,
                                                   branch_id=body.branch_id), token_data=_as_owner(c))
        finally:
            _EMIT_SUSPENDED.reset(token)
        vid = res.get("visit_id")
        v = (_db.visits.find_one({"id": vid}, {"_id": 0}) if vid else None) or {}
        if v.get("id"):
            _db.visits.update_one({"id": v["id"]}, {"$set": {"source": "api", "external_id": body.external_id, "api_key_id": c.key_id}})
            v.update(source="api", external_id=body.external_id)
        out = {"visit": visit_out(v), "customer": customer_out(_db.customers.find_one({"id": cust["id"]}, {"_id": 0})),
               "tier_upgraded": bool(res.get("tier_upgraded")), "reward_unlocked": bool(res.get("reward_unlocked")),
               "next_visit_reward": res.get("next_visit_reward")}
        _idem_done(c.tenant_id, "visit", body.external_id, out)
    except BaseException:
        _idem_abort(c.tenant_id, "visit", body.external_id)
        raise
    # sent now that the visit carries its external_id (the scan's own was held back)
    emit_customer("visit.created", c.tenant_id, cust["id"], visit_id=v.get("id"))
    if _reward_unlocked_by(res):
        emit_customer("reward.unlocked", c.tenant_id, cust["id"])
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


# ---------------------------------------------------------------------------
# Cancel a visit (refund)
# ---------------------------------------------------------------------------
class CancelIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=200)
    external_id: Optional[str] = Field(None, max_length=120)


def _cancel_answer(v: Dict[str, Any], duplicate: bool) -> Dict[str, Any]:
    cust = _db.customers.find_one({"id": v.get("customer_id")}, {"_id": 0})
    return {"cancelled": True, "duplicate": duplicate, "visit": {**visit_out(v), "cancelled_at": _iso(v.get("cancelled_at"))},
            "customer": customer_out(cust) if cust else None,
            "reversed": v.get("reversed") or {}, "not_reversed": v.get("not_reversed") or []}


def _undo_on_card(v: Dict[str, Any], c: ApiCaller) -> Dict[str, Any]:
    """Take back what this visit gave: one visit, its points, its spend, the
    meter's move and any reward it banked — never below zero. What was handed
    out since (points spent, a reward used, messages) stays, and is named."""
    import server as core
    from features import loyalty_card as LC
    cid, tid = v["customer_id"], c.tenant_id
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    programme = v.get("programme") or LC._programme(tpl)
    stamp_card = programme == "stamps"
    pts = max(int(v.get("points_awarded") or 0), 0)
    amount = round(max(float(v.get("amount_paid") or 0), 0.0), 2)
    persons = max(int(v.get("persons") or 1), 1)
    inc: Dict[str, Any] = {"visits": -1, "points": -pts, "points_lifetime": -pts, "total_amount_paid": -amount}
    # the scan moved the meter's baseline by (0 if tampons else 1) − (persons − 1): move it back
    base = (persons - 1) if stamp_card else -1
    not_reversed: List[str] = []
    rewards_cancelled = 0
    banked = list(_db.rewards_earned.find({"tenant_id": tid, "customer_id": cid, "visit_id": v["id"]}, {"_id": 0}))
    if not banked and stamp_card and isinstance(v.get("visit_time"), datetime):
        t0 = _aware(v["visit_time"])           # rows banked before rewards carried their visit
        banked = [r for r in _db.rewards_earned.find({"tenant_id": tid, "customer_id": cid, "visit_id": {"$exists": False},
                                                       "earned_at": {"$gte": t0 - timedelta(seconds=1), "$lte": t0 + timedelta(seconds=120)}},
                                                      {"_id": 0})]
    for r in banked:
        if r.get("status") == "pending":
            done = _db.rewards_earned.update_one({"id": r["id"], "status": "pending"},
                                                 {"$set": {"status": "cancelled", "cancelled_at": _now(), "cancelled_visit_id": v["id"]}})
            if getattr(done, "modified_count", 0):
                base -= int(r.get("threshold") or _threshold(tid))
                rewards_cancelled += 1
                continue
        if r.get("status") != "cancelled":
            not_reversed.append("reward_already_used")
    if base:
        inc["visits_at_last_redemption"] = base
    later = _db.visits.find_one({"tenant_id": tid, "customer_id": cid}, {"_id": 0, "visit_time": 1}, sort=[("visit_time", -1)])
    sets: Dict[str, Any] = {"updated_at": _now()}
    unsets: Dict[str, Any] = {}
    if later and later.get("visit_time"):
        sets["last_visit_date"] = later["visit_time"]
    else:
        unsets["last_visit_date"] = ""
    vt = _aware(v.get("visit_time"))
    if not later or not vt or (_aware(later.get("visit_time")) or vt) < vt:
        # it was the latest visit: what « the latest scan brought » is nothing now
        sets.update({"last_scan_units": 0, "points_last_earned": 0})
    upd: Dict[str, Any] = {"$inc": inc, "$set": sets}
    if unsets:
        upd["$unset"] = unsets
    _db.customers.update_one({"id": cid, "tenant_id": tid}, upd)
    after = _db.customers.find_one({"id": cid}, {"_id": 0}) or {}
    fixes: Dict[str, Any] = {}
    recovered_points = pts
    if int(after.get("points") or 0) < 0:
        recovered_points = pts + int(after["points"])
        fixes["points"] = 0
        not_reversed.append("points_already_spent")
    for f in ("points_lifetime", "visits"):
        if int(after.get(f) or 0) < 0:
            fixes[f] = 0
    if float(after.get("total_amount_paid") or 0) < 0:
        fixes["total_amount_paid"] = 0.0
    if fixes:
        _db.customers.update_one({"id": cid}, {"$set": fixes})
    try:
        _db.customer_changes.insert_one({
            "id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cid, "customer_name": after.get("name"),
            "kind": "visit_cancelled", "visits_delta": -1, "points_delta": -recovered_points,
            "text": f"Passage annulé ({c.key_name or 'API'}) : {amount:.2f} €".replace(".", ","),
            "reason": v.get("cancel_reason") or "Remboursement", "by": f"api:{c.key_name or c.key_id}", "at": _now(),
        })
    except Exception as e:
        print(f"cancel: history not written (non-fatal): {e}")
    try:
        from features import client_brain as CB
        CB.refresh(tid, cid)
    except Exception as e:
        print(f"cancel: client brain not refreshed (non-fatal): {e}")
    try:
        core.refresh_wallet_pass(cid)
    except Exception as e:
        print(f"cancel: wallet pass not refreshed (non-fatal): {e}")
    return {"reversed": {"visits": 1, "points": recovered_points, "amount": amount,
                         "stamps": int(v.get("stamps_awarded") or 0), "rewards_cancelled": rewards_cancelled},
            "not_reversed": list(dict.fromkeys(not_reversed))}


@router.post("/api/v1/visits/{ref}/cancel")
def cancel_visit(ref: str, body: Optional[CancelIn] = Body(None), c: ApiCaller = Depends(writer)):
    import server as core
    body = body or CancelIn()
    ref = (ref or "").strip()
    where = {"tenant_id": c.tenant_id, "$or": [{"id": ref}, {"external_id": ref}]}
    hit = _idem_begin(c.tenant_id, "cancel", body.external_id, _fingerprint({"visit": ref}))
    if hit is not None:
        return {**hit, "duplicate": True}
    try:
        # an external_id reused after its 30 days: the latest visit is the one meant
        v = _db.visits.find_one(where, {"_id": 0}, sort=[("visit_time", -1)]) if ref else None
        if not v:
            gone = _db.visits_cancelled.find_one(where, {"_id": 0}, sort=[("cancelled_at", -1)]) if ref else None
            if not gone:
                raise _err(404, "visit_not_found", "Passage introuvable (id ou external_id).")
            out = _cancel_answer(gone, duplicate=True)
            _idem_done(c.tenant_id, "cancel", body.external_id, out)
            return out
        vt = _aware(v.get("visit_time"))
        if vt and vt < _now() - timedelta(days=CANCEL_MAX_DAYS):
            raise _err(409, "visit_too_old", f"Ce passage a plus de {CANCEL_MAX_DAYS} jours : corrigez-le dans Clients › Ajuster.")
        if v.get("paper_stamps"):
            raise _err(409, "visit_not_cancellable",
                       "Ce passage a transféré une carte papier : corrigez-le dans Clients › Ajuster.")
        claimed = _db.visits.find_one_and_delete({"id": v["id"], "tenant_id": c.tenant_id})
        if not claimed:                        # another call cancelled it a moment ago
            gone = _db.visits_cancelled.find_one({"tenant_id": c.tenant_id, "id": v["id"]}, {"_id": 0})
            if not gone:
                raise _err(409, "request_in_progress", "Ce passage est en cours d'annulation : réessayez.")
            out = _cancel_answer(gone, duplicate=True)
            _idem_done(c.tenant_id, "cancel", body.external_id, out)
            return out
        claimed.pop("_id", None)
        kept = {**claimed, "cancelled_at": _now(), "cancel_reason": (body.reason or "").strip() or None,
                "cancelled_by": f"api:{c.key_name or c.key_id}", "cancel_key_id": c.key_id}
        _db.visits_cancelled.insert_one(dict(kept))      # kept apart at once: a visit is never just lost
        undone = _undo_on_card(kept, c)
        _db.visits_cancelled.update_one({"tenant_id": c.tenant_id, "id": kept["id"]}, {"$set": undone})
        kept.update(undone)
        out = _cancel_answer(kept, duplicate=False)
        _idem_done(c.tenant_id, "cancel", body.external_id, out)
    except BaseException:
        _idem_abort(c.tenant_id, "cancel", body.external_id)
        raise
    try:
        core.log_audit("api.visit_cancel", actor=f"api:{c.key_name or c.key_id}", actor_type="api", tenant_id=c.tenant_id,
                       target=kept["id"], meta={"customer_id": kept.get("customer_id"), "amount": kept.get("amount_paid")})
    except Exception as e:
        print(f"cancel: audit not written (non-fatal): {e}")
    emit(c.tenant_id, "visit.cancelled", {"visit": out["visit"], "customer": out["customer"],
                                          "reversed": out["reversed"], "not_reversed": out["not_reversed"]})
    return out


# ---------------------------------------------------------------------------
# Rewards: hold (borne), verification (website), redeem
# ---------------------------------------------------------------------------
class HoldIn(BaseModel):
    customer: str
    ttl_seconds: int = Field(HOLD_DEFAULT_S, ge=HOLD_MIN_S, le=HOLD_MAX_S)


def _refuse_no_reward(cust: Dict[str, Any]) -> None:
    out = customer_out(cust)
    if out["reward_available"]:
        return
    if out["rewards_pending"] or out["reward_unlocked"]:
        raise _err(409, "reward_next_visit", "Récompense disponible à la prochaine visite.")
    raise _err(409, "no_reward", "Ce client n'a pas de récompense disponible.")


@router.post("/api/v1/rewards/hold", status_code=201)
def hold_reward(body: HoldIn, c: ApiCaller = Depends(writer)):
    cust = _find_customer(c.tenant_id, body.customer)
    _refuse_no_reward(cust)
    now = _now()
    # a reward held again and again would never reach the till (#454 pentest):
    # holds that did not end in a used reward are counted, per client, per hour
    if _db.api_reward_holds.count_documents({"tenant_id": c.tenant_id, "customer_id": cust["id"], "state": {"$ne": "used"},
                                             "at": {"$gte": now - timedelta(hours=1)}}) >= HOLDS_PER_HOUR:
        raise _err(429, "too_many_holds", f"{HOLDS_PER_HOUR} réservations par heure au maximum pour ce client : "
                                          "la récompense reste disponible à la caisse.")
    hold = {"id": "hold_" + secrets.token_hex(12), "until": now + timedelta(seconds=body.ttl_seconds),
            "key_id": c.key_id, "key_name": c.key_name, "at": now}
    took = _db.customers.update_one(
        {"id": cust["id"], "tenant_id": c.tenant_id,
         "$or": [{"reward_hold": {"$exists": False}}, {"reward_hold": None}, {"reward_hold.until": {"$lte": now}}]},
        {"$set": {"reward_hold": hold}})
    if not getattr(took, "modified_count", 0):
        cur = (_db.customers.find_one({"id": cust["id"]}, {"_id": 0, "reward_hold": 1}) or {}).get("reward_hold") or {}
        raise _err(409, "reward_held", "Cette récompense est déjà réservée par une autre caisse.",
                   expires_at=_iso(cur.get("until")))
    _db.api_reward_holds.insert_one({**hold, "tenant_id": c.tenant_id, "customer_id": cust["id"], "state": "active"})
    return {"hold_id": hold["id"], "expires_at": _iso(hold["until"]), "customer": customer_out(cust)}


@router.delete("/api/v1/rewards/hold/{hold_id}")
def release_hold(hold_id: str, c: ApiCaller = Depends(writer)):
    h = _db.api_reward_holds.find_one({"id": hold_id, "tenant_id": c.tenant_id}, {"_id": 0})
    if not h:
        raise _err(404, "hold_not_found", "Réservation introuvable.")
    freed = _db.customers.update_one({"id": h["customer_id"], "tenant_id": c.tenant_id, "reward_hold.id": hold_id},
                                     {"$unset": {"reward_hold": ""}})
    _db.api_reward_holds.update_one({"id": hold_id, "state": "active"}, {"$set": {"state": "released", "released_at": _now()}})
    return {"released": bool(getattr(freed, "modified_count", 0))}


class VerifyCheckIn(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


def _masked(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return "•• •• •• " + (f"{d[-4:-2]} {d[-2:]}" if len(d) >= 4 else d)


@router.post("/api/v1/customers/{ref}/verification")
def send_verification(ref: str, c: ApiCaller = Depends(writer)):
    """An SMS code to the client's own phone: proof, for a website, that the
    person typing the number is the client before a reward is used."""
    from services import sms as SMS
    cust = _find_customer(c.tenant_id, ref)
    phone = (cust.get("phone") or "").strip()
    if len(re.sub(r"\D", "", phone)) < 9:
        raise _err(409, "no_phone", "Aucun numéro de téléphone sur cette carte.")
    if not SMS.is_configured():
        raise _err(503, "sms_unavailable", "L'envoi de SMS n'est pas disponible pour le moment.")
    now = _now()
    if _db.api_verifications.count_documents({"tenant_id": c.tenant_id, "customer_id": cust["id"],
                                              "at": {"$gte": now - timedelta(hours=1)}}) >= VERIFY_PER_HOUR:
        raise _err(429, "too_many_codes", f"{VERIFY_PER_HOUR} codes par heure au maximum pour ce client.")
    if _db.api_verifications.count_documents({"tenant_id": c.tenant_id, "at": {"$gte": now - timedelta(days=1)}}) >= VERIFY_PER_DAY:
        raise _err(429, "too_many_codes", f"{VERIFY_PER_DAY} codes par jour au maximum pour ce commerce.")
    code = f"{secrets.randbelow(10 ** 6):06d}"
    row = {"id": "ver_" + secrets.token_hex(10), "tenant_id": c.tenant_id, "customer_id": cust["id"], "key_id": c.key_id,
           "attempts": 0, "state": "sent", "at": now, "expires_at": now + timedelta(seconds=VERIFY_TTL_S)}
    row["code_hash"] = _hash(f"{row['id']}:{code}")
    _db.api_verifications.insert_one(dict(row))
    shop = (_db.tenants.find_one({"id": c.tenant_id}, {"_id": 0, "name": 1}) or {}).get("name") or "FidClic"
    res = SMS.send_sms(phone, f"{shop[:30]} : votre code est {code}. Il expire dans {VERIFY_TTL_S // 60} min. Ne le partagez pas.")
    if not (res or {}).get("sent"):
        _db.api_verifications.update_one({"id": row["id"]}, {"$set": {"state": "failed", "error": str((res or {}).get("error"))[:80]}})
        raise _err(502, "sms_failed", "Le SMS n'a pas pu être envoyé : vérifiez le numéro du client.")
    return {"sent": True, "channel": "sms", "to": _masked(phone), "verification_id": row["id"], "expires_at": _iso(row["expires_at"])}


@router.post("/api/v1/customers/{ref}/verification/check")
def check_verification(ref: str, body: VerifyCheckIn, c: ApiCaller = Depends(writer)):
    cust = _find_customer(c.tenant_id, ref)
    now = _now()
    row = _db.api_verifications.find_one({"tenant_id": c.tenant_id, "customer_id": cust["id"], "state": {"$in": ["sent", "locked"]}},
                                         {"_id": 0}, sort=[("at", -1)])
    if not row or (_aware(row.get("expires_at")) or now) <= now:
        raise _err(400, "wrong_code", "Code incorrect ou expiré : demandez-en un nouveau.")
    if row.get("state") == "locked" or int(row.get("attempts") or 0) >= VERIFY_MAX_ATTEMPTS:
        raise _err(429, "too_many_attempts", "Trop d'essais : demandez un nouveau code.")
    code = re.sub(r"\D", "", body.code)
    if not hmac.compare_digest(_hash(f"{row['id']}:{code}"), row.get("code_hash") or ""):
        n = int(row.get("attempts") or 0) + 1
        _db.api_verifications.update_one({"id": row["id"]}, {"$set": {"attempts": n, **({"state": "locked"} if n >= VERIFY_MAX_ATTEMPTS else {})}})
        raise _err(400, "wrong_code", "Code incorrect.", attempts_left=max(0, VERIFY_MAX_ATTEMPTS - n))
    token = "vt_" + secrets.token_urlsafe(24)
    took = _db.api_verifications.update_one({"id": row["id"], "state": "sent"},
                                            {"$set": {"state": "verified", "verified_at": now, "token_hash": _hash(token),
                                                      "token_until": now + timedelta(seconds=VERIFY_TOKEN_TTL_S), "token_used": False}})
    if not getattr(took, "modified_count", 0):
        raise _err(400, "wrong_code", "Code déjà utilisé : demandez-en un nouveau.")
    return {"verified": True, "verification_token": token, "expires_at": _iso(now + timedelta(seconds=VERIFY_TOKEN_TTL_S))}


def _use_token(c: ApiCaller, customer_id: str, token: Optional[str]) -> Optional[str]:
    """Spend a verification token once; returns its row id (to give it back
    if the reward then fails), or refuses."""
    now = _now()
    row = _db.api_verifications.find_one_and_update(
        {"tenant_id": c.tenant_id, "customer_id": customer_id, "token_hash": _hash(token or "-"), "token_used": False,
         "token_until": {"$gt": now}},
        {"$set": {"token_used": True, "token_used_at": now}}) if token else None
    if not row:
        raise _err(403, "verification_required",
                   "Clé « site en ligne » : vérifiez d'abord le client par SMS (POST /customers/{ref}/verification).")
    return row["id"]


class RedeemIn(BaseModel):
    customer: str
    reward_name: Optional[str] = Field(None, max_length=120)
    external_id: Optional[str] = Field(None, max_length=120)
    hold_id: Optional[str] = Field(None, max_length=60)
    verification_token: Optional[str] = Field(None, max_length=80)


@router.post("/api/v1/rewards/redeem")
def redeem(body: RedeemIn, c: ApiCaller = Depends(writer)):
    import server as core
    fp = _fingerprint({"customer": body.customer.strip(), "reward_name": body.reward_name or "", "hold_id": body.hold_id or ""})
    hit = _idem_begin(c.tenant_id, "redeem", body.external_id, fp)
    if hit is not None:
        return {**hit, "duplicate": True}
    token_row = None
    try:
        cust = _find_customer(c.tenant_id, body.customer)
        if c.online:
            token_row = _use_token(c, cust["id"], body.verification_token)
        # server.redeem_reward decides, on any programme (a points card has no `reward_unlocked`)
        try:
            core.redeem_reward(core.RedeemRewardRequest(customer_id=cust["id"], reward_name=body.reward_name, notes="API",
                                                        hold_id=body.hold_id), token_data=_as_owner(c))
        except HTTPException as e:
            if e.detail == core.NEXT_VISIT_REFUSAL:
                raise _err(409, "reward_next_visit", e.detail)
            if e.status_code == 409 and str(e.detail).startswith(core.HELD_REFUSAL):
                raise _err(409, "reward_held", str(e.detail))
            if e.status_code == 400:             # nothing to hand over, or another till just took it
                raise _err(409, "no_reward", "Ce client n'a pas de récompense disponible.")
            raise
        if body.hold_id:
            _db.api_reward_holds.update_one({"id": body.hold_id, "tenant_id": c.tenant_id, "state": "active"},
                                            {"$set": {"state": "used", "used_at": _now()}})
        out = {"customer": customer_out(_db.customers.find_one({"id": cust["id"]}, {"_id": 0})), "redeemed": True}
        _idem_done(c.tenant_id, "redeem", body.external_id, out)
    except BaseException:
        if token_row:                         # the reward failed: the client's proof is not spent
            _db.api_verifications.update_one({"id": token_row}, {"$set": {"token_used": False}})
        _idem_abort(c.tenant_id, "redeem", body.external_id)
        raise
    return {**out, "duplicate": False}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
def sign(secret: str, body: bytes, ts: Optional[int] = None) -> str:
    ts = ts or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def _resolve(host: str) -> List[str]:
    """Every address a name points to (tests replace this)."""
    return list(dict.fromkeys(i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)))


def _literal_ip(host: str) -> Optional[ipaddress._BaseAddress]:
    """The address a host written as one stands for — also the short and the
    decimal forms (« 127.1 », « 2130706433 », « 0x7f.1 ») a resolver accepts."""
    h = (host or "").strip("[]")
    try:
        return ipaddress.ip_address(h)
    except ValueError:
        pass
    if re.fullmatch(r"[0-9a-fA-FxX.]+", h) and re.search(r"\d", h):
        try:
            return ipaddress.ip_address(socket.inet_aton(h))
        except (OSError, ValueError):
            return None
    return None


def _inside(ip: ipaddress._BaseAddress) -> bool:
    mapped = getattr(ip, "ipv4_mapped", None)
    ip = mapped or ip
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
                or ip.is_unspecified or not ip.is_global)


def _blocked_host(host: str) -> bool:
    h = (host or "").lower().strip(".")
    if not h or h == "localhost" or h.endswith(BLOCKED_SUFFIXES) or "." not in h.strip("[]") and not _literal_ip(h):
        return True
    ip = _literal_ip(h)
    return bool(ip and _inside(ip))


def _target_refusal(url: str) -> Optional[str]:
    """Why this URL must not be called now (after DNS), or None."""
    host = (urlsplit(url).hostname or "").lower()
    if _blocked_host(host):
        return f"blocked_address: {host}"
    if _literal_ip(host):
        return None
    try:
        ips = _resolve(host)
    except Exception as e:
        return f"dns_error: {type(e).__name__}"
    for a in ips:
        try:
            if _inside(ipaddress.ip_address(a.split("%")[0])):
                return f"blocked_address: {host} → {a}"
        except ValueError:
            return f"blocked_address: {host} → {a}"
    return None if ips else "dns_error: no address"


def _deliver(hook: Dict[str, Any], event: Dict[str, Any], attempt: int = 1, delivery_id: Optional[str] = None) -> Dict[str, Any]:
    import requests
    body = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode()
    started = time.time()
    status, err = None, None
    refusal = _target_refusal(hook["url"])
    if refusal:
        err = refusal
    else:
        try:
            r = requests.post(hook["url"], data=body, timeout=TIMEOUT_S, allow_redirects=False, headers={
                "Content-Type": "application/json", "User-Agent": "FidClic-Webhooks/1.0", "X-FidClic-Event": event["type"],
                "X-FidClic-Delivery": event["id"], "X-FidClic-Api-Version": API_VERSION,
                "X-FidClic-Signature": sign(hook["secret"], body)})
            status = r.status_code
            if 300 <= status < 400:
                err = "redirect_not_followed"
        except Exception as e:                   # network, timeout, DNS
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


_POOL: Optional[ThreadPoolExecutor] = None
_POOL_LOCK = threading.Lock()
_INFLIGHT: set = set()


def _submit(fn, *args):
    """Hand a delivery to the instance's shared pool (tests replace this)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = ThreadPoolExecutor(max_workers=WEBHOOK_WORKERS, thread_name_prefix="fidclic-webhook")
        fut = _POOL.submit(fn, *args)
        _INFLIGHT.add(fut)
    fut.add_done_callback(_INFLIGHT.discard)
    return fut


def drain_webhooks(timeout: float = 10.0) -> None:
    """Wait for the deliveries this instance has in hand (tests, shutdown)."""
    _wait_all(list(_INFLIGHT), timeout=timeout)


def _deliver_all(hooks: List[Dict[str, Any]], event: Dict[str, Any]) -> None:
    """Every endpoint, in the background: the caller (a scan at the till)
    never waits for a merchant's server. Each delivery is written down BEFORE
    it is handed over, so one the instance never finishes (frozen after the
    answer, recycled) stays « pending » and the 15-minute tick sends it."""
    for h in hooks:
        row = {"id": uuid.uuid4().hex, "tenant_id": h["tenant_id"], "hook_id": h["id"], "event_id": event["id"],
               "type": event["type"], "payload": event, "status": None, "ok": False, "error": "pending", "ms": 0,
               "attempts": 1, "at": _now()}
        _db.webhook_deliveries.insert_one(dict(row))
        if len(_INFLIGHT) >= WEBHOOK_QUEUE_MAX:   # an endpoint down for long: memory stays flat, the tick sends it
            continue
        try:
            _submit(_deliver, h, event, 1, row["id"])
        except Exception as e:                 # no thread to be had: the tick will send it
            print(f"webhooks: {event['type']} queued for the tick ({e})")


def emit(tenant_id: Optional[str], kind: str, data: Dict[str, Any]) -> int:
    """Send `kind` to the business's webhooks. Never raises; returns how many
    endpoints were called."""
    if not tenant_id or kind not in EVENTS:
        return 0
    try:
        hooks = list(_db.webhooks.find({"tenant_id": tenant_id, "active": True, "events": kind}, {"_id": 0}))
        if not hooks or not _plan_ok(tenant_id):
            return 0
        event = {"id": "evt_" + uuid.uuid4().hex[:24], "type": kind, "api_version": API_VERSION,
                 "created_at": _now().isoformat(), "data": data}
        _deliver_all(hooks, event)
        return len(hooks)
    except Exception as e:
        print(f"webhooks: {kind} for {tenant_id} failed: {e}")
        return 0


def emit_customer(kind: str, tenant_id: Optional[str], customer_id: Optional[str], extra: Optional[Dict[str, Any]] = None,
                  with_visit: bool = False, visit_id: Optional[str] = None) -> None:
    """Hook for the core flows (join, scan, redeem). `visit_id` names the
    visit; `with_visit` alone means the client's latest."""
    if _EMIT_SUSPENDED.get():
        return
    try:
        if not tenant_id or not _db.webhooks.find_one({"tenant_id": tenant_id, "active": True, "events": kind}, {"_id": 1}):
            return
        c = _db.customers.find_one({"id": customer_id}, {"_id": 0})
        if c:
            extra = dict(extra or {})
            if visit_id:
                v = _db.visits.find_one({"tenant_id": tenant_id, "id": visit_id}, {"_id": 0})
                extra["visit"] = visit_out(v) if v else None
            elif with_visit:
                v = _db.visits.find_one({"tenant_id": tenant_id, "customer_id": customer_id}, {"_id": 0}, sort=[("visit_time", -1)])
                extra["visit"] = visit_out(v) if v else None
            emit(tenant_id, kind, {"customer": customer_out(c), **extra})
    except Exception as e:
        print(f"webhooks: {kind} skipped: {e}")


def retry_failed(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The 15-minute tick and the daily cron: failed deliveries of the last 3
    days, up to RETRIES tries — not one sent under 2 minutes ago, which may
    still be on its way."""
    now = now or _now()
    n = ok = 0
    for d in list(_db.webhook_deliveries.find({"ok": False, "attempts": {"$lt": RETRIES},
                                               "at": {"$gte": now - timedelta(days=3), "$lte": now - timedelta(minutes=2)}},
                                              {"_id": 0}).limit(500)):
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
            "calls": int(k.get("calls") or 0), "revoked": bool(k.get("revoked_at")), "online": bool(k.get("online"))}


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
    online: bool = False      # « Site en ligne »: rewards only after the client's SMS code


@router.post("/api/owner/integrations/keys", status_code=201)
def create_key(body: KeyIn, token_data: TokenData = Depends(require_role(OWNER))):
    import server as core
    _need_plan(token_data)
    if _db.api_keys.count_documents({"tenant_id": token_data.tenant_id, "revoked_at": None}) >= MAX_KEYS:
        raise HTTPException(status_code=400, detail=f"{MAX_KEYS} clés actives au maximum : révoquez-en une d'abord.")
    raw = "fc_live_" + secrets.token_urlsafe(30).replace("-", "").replace("_", "")[:40]
    k = {"id": uuid.uuid4().hex, "tenant_id": token_data.tenant_id, "name": body.name.strip(), "prefix": raw[:14],
         "hash": _hash(raw), "scopes": ["read", "write"] if body.write else ["read"], "created_at": _now(),
         "created_by": token_data.email, "revoked_at": None, "calls": 0, "online": bool(body.online)}
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
    """At creation: https, a public name or address. Where a name points is
    checked again on every send (_target_refusal), because DNS can change."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        parts.port                            # a malformed port raises
    except ValueError:
        parts, host = None, ""
    if not parts or parts.scheme != "https" or not host or re.search(r"\s", url) or parts.username or parts.password:
        raise HTTPException(status_code=400, detail="L'adresse doit commencer par https:// (ex. https://votre-outil.fr/fidclic).")
    if _blocked_host(host):
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
