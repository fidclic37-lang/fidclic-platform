"""
Caisse connectors — the common frame, written once; each caisse brand is a
plug in services/pos/ (Square first).

WHAT IT DOES
    1. Connect     the owner clicks « Connecter Square » (Paramètres › API &
                   Intégrations › Caisse), logs in to their own Square, says
                   yes; Square sends them back with a code; we keep the tokens
                   SEALED (Fernet). One-use state, 10 minutes. One Square shop
                   belongs to one FidClic business.
    2. Cards out   every live card becomes a Square customer: name + the
                   card's own code (reference_id). Nothing else leaves —
                   no phone, no e-mail, no birthday. Square's till scans the
                   card's QR and puts that customer on the sale.
    3. Tickets in  Square rings our door (webhook, signed) when a payment or
                   a refund is finished. EVERY ticket is kept (pos_tickets),
                   scanned or not. A sale with a FidClic card becomes a visit
                   through the API's own path (merchant_api.create_visit: the
                   counter's rules, idempotent on « square:<payment id> »).
                   A full refund cancels the visit (merchant_api.cancel_visit);
                   a partial one is kept and shown.
    4. Never lost  each event is written before any work; a failure leaves it
                   pending and the 15-minute tick tries again (5 times, then
                   « failed », counted on the page). Past INLINE_PER_15MIN
                   events a connection waits for the tick: a till flooding us
                   never floods the database (wallet storm, 2026-11-12).
    5. Night check once per Paris day, after 03:00, the day's tickets are
                   fetched from the caisse and any the door missed are applied
                   (same ids → never twice).
    6. Status      the page shows connected / à reconnecter, the shop, the
                   store map (caisse location → FidClic store), today's
                   tickets, the failed ones. Never a token.

Rewards applied at the till (Square customer group + pricing rule) are the
next PR; this one earns.

Who: owner connects, maps, checks now and disconnects; owner + administrateur
read (the same as API & Intégrations). Plan: « API & Intégrations » (and
« Cartes »), checked on every ticket — a plan that loses it keeps its
tickets (status not_applied) but nothing touches the cards.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from auth import TokenData, require_role
from services import pos as POS
from services.pos.base import PosError

router = APIRouter(tags=["caisse"])
_db = None

OWNER = ["business_owner"]
READERS = ["business_owner", "administrateur"]
PARIS = ZoneInfo("Europe/Paris")

STATE_TTL_MIN = 10
INLINE_PER_15MIN = 600          # events a connection may have applied at once in 15 min; past it, the tick does it
MAX_ATTEMPTS = 5
TICK_EVENTS = 300               # pending events the tick handles per run, all connections
SYNC_PER_TICK = 200             # cards pushed per connection per tick
SYNC_TOTAL_PER_TICK = 1000
MAX_AMOUNT = 100000.0           # the API's own ceiling for one visit
RECONCILE_HOUR = 3              # Paris
REFRESH_BEFORE = timedelta(days=7)
MANUAL_COOLDOWN_S = 300
MAX_BODY = 256 * 1024
CLAIM_STALE_S = 60
FINAL = {"matched", "unmatched", "rejected", "not_applied", "refused", "refunded", "partial_refund",
         "refund_manual", "refund_unknown_sale", "refund_done"}


def init(db):
    global _db
    _db = db
    for coll, keys, kw in (
            ("pos_connections", "id", {"unique": True}),
            ("pos_connections", [("provider", 1), ("merchant_id", 1)], {}),
            ("pos_connections", "tenant_id", {}),
            ("pos_oauth_states", "state_hash", {"unique": True}),
            ("pos_oauth_states", "expires_at", {"expireAfterSeconds": 0, "name": "exp_ttl"}),
            ("pos_events", [("provider", 1), ("id", 1)], {"unique": True}),
            ("pos_events", [("state", 1), ("at", 1)], {}),
            ("pos_events", [("conn_id", 1), ("at", -1)], {}),
            ("pos_events", "at", {"expireAfterSeconds": 90 * 86400, "name": "at_ttl"}),
            ("pos_tickets", [("provider", 1), ("ticket_id", 1)], {"unique": True}),
            ("pos_tickets", [("tenant_id", 1), ("at", -1)], {}),
            ("pos_customer_links", [("conn_id", 1), ("customer_id", 1)], {"unique": True}),
            ("pos_customer_links", [("conn_id", 1), ("provider_customer_id", 1)], {})):
        try:
            db[coll].create_index(keys, **kw)
        except Exception as e:
            print(f"pos_connectors: index {coll} {keys} skipped: {e}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def _iso(v: Any) -> Optional[str]:
    d = _aware(v)
    return d.isoformat() if d else None


def _err(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# Sealed tokens
# ---------------------------------------------------------------------------
def _fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    secret = (os.environ.get("POS_TOKENS_SECRET") or os.environ.get("JWT_SECRET") or "fidclic-dev-secret").encode()
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"fidclic-pos", info=b"caisse-tokens").derive(secret)
    return Fernet(base64.urlsafe_b64encode(key))


def _seal(tokens: Dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps({"a": tokens.get("access_token"), "r": tokens.get("refresh_token")}).encode()).decode()


def _open(conn: Dict[str, Any]) -> Dict[str, str]:
    try:
        d = json.loads(_fernet().decrypt((conn.get("tokens_sealed") or "").encode()))
        return {"access_token": d.get("a") or "", "refresh_token": d.get("r") or ""}
    except Exception:
        return {"access_token": "", "refresh_token": ""}


def _token(conn: Dict[str, Any]) -> str:
    t = _open(conn).get("access_token")
    if not t:
        raise PosError("Connexion à la caisse perdue : reconnectez-la.", code="reconnect")
    return t


# ---------------------------------------------------------------------------
# The business
# ---------------------------------------------------------------------------
def _tenant_ok(tid: str) -> bool:
    from features import merchant_api as M
    from features import plan_limits
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "id": 1, "suspended_at": 1, "is_active": 1})
    if not t or t.get("suspended_at") or t.get("is_active") is False:
        return False
    return M._plan_ok(tid) and plan_limits.allows_tenant(tid, "cards")


def _need_plan(token_data: TokenData) -> None:
    from features import merchant_api as M
    M._need_plan(token_data)


def _stores(tid: str) -> List[Dict[str, str]]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) or {}
    return [{"id": str(b["id"]), "name": str(b.get("name") or b["id"])} for b in (t.get("branches") or [])
            if isinstance(b, dict) and b.get("id") and b.get("status") != "closed"]


def _caller(conn: Dict[str, Any]):
    from features import merchant_api as M
    return M.ApiCaller(tenant_id=conn["tenant_id"], key_id=conn["id"], key_name=conn.get("label") or conn["provider"],
                       scopes=["read", "write"])


def _scan_code(tid: str, barcode: str) -> str:
    """What the card's QR says — the reference id the caisse's scanner reads."""
    from features import wallet_passes as WP
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "code_type": 1}) or {}
    fmt = {"barcode": "PKBarcodeFormatCode128", "pdf417": "PKBarcodeFormatPDF417",
           "aztec": "PKBarcodeFormatAztec"}.get(tpl.get("code_type"), tpl.get("code_type"))
    if fmt not in getattr(WP, "BARCODE_FORMATS", ()):
        fmt = "PKBarcodeFormatQR"
    return WP.barcode_message(fmt, barcode) or WP.barcode_message("PKBarcodeFormatQR", barcode)


def _live():
    from features import merchant_api as M
    return dict(M.LIVE)


# ---------------------------------------------------------------------------
# Applying one ticket (the heart)
# ---------------------------------------------------------------------------
def _claim(t: Dict[str, Any], conn: Dict[str, Any], extra: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The ticket's row, taken for this worker — None when it is done or being done."""
    now = _now()
    key = {"provider": t["provider"], "ticket_id": t["ticket_id"]}
    _db.pos_tickets.update_one(key, {"$setOnInsert": {
        **key, "tenant_id": conn["tenant_id"], "conn_id": conn["id"], "kind": t["kind"], "amount": float(t.get("amount") or 0),
        "currency": t.get("currency"), "location_id": t.get("location_id"), "provider_customer_id": t.get("customer_id"),
        "refund_of": t.get("refund_of"), "at": _aware(t.get("at")) or now, "created_at": now, "status": "new", **extra}}, upsert=True)
    return _db.pos_tickets.find_one_and_update(
        {**key, "tenant_id": conn["tenant_id"],
         "$or": [{"status": "new"}, {"status": "processing", "claimed_at": {"$lt": now - timedelta(seconds=CLAIM_STALE_S)}}]},
        {"$set": {"status": "processing", "claimed_at": now}}, return_document=True)


def _release(t: Dict[str, Any]) -> None:
    _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": t["ticket_id"], "status": "processing"}, {"$set": {"status": "new"}})


def _finish(t: Dict[str, Any], status: str, **fields) -> str:
    _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": t["ticket_id"]},
                               {"$set": {"status": status, "done_at": _now(), **fields}, "$unset": {"claimed_at": ""}})
    return status


def _find_card(conn: Dict[str, Any], adapter, provider_customer_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not provider_customer_id:
        return None
    link = _db.pos_customer_links.find_one({"conn_id": conn["id"], "provider_customer_id": provider_customer_id}, {"_id": 0})
    if link:
        c = _db.customers.find_one({"id": link["customer_id"], "tenant_id": conn["tenant_id"], **_live()}, {"_id": 0})
        if c:
            return c
    import server as core
    ref = adapter.customer_reference(_token(conn), provider_customer_id)        # PosError → the event waits
    code = core.barcode_from(ref or "")
    if not code:
        return None
    c = _db.customers.find_one({"tenant_id": conn["tenant_id"], "barcode_id": code.upper(), **_live()}, {"_id": 0})
    if c:
        try:
            _db.pos_customer_links.update_one({"conn_id": conn["id"], "customer_id": c["id"]}, {"$set": {
                "tenant_id": conn["tenant_id"], "provider": conn["provider"], "provider_customer_id": provider_customer_id,
                "reference_id": (ref or "")[:300], "at": _now()}}, upsert=True)
        except Exception as e:
            print(f"pos: link not kept (non-fatal): {e}")
    return c


def _apply_sale(conn: Dict[str, Any], adapter, t: Dict[str, Any]) -> str:
    from features import merchant_api as M
    branch = (conn.get("location_map") or {}).get(t.get("location_id") or "") or conn.get("default_branch") or None
    row = _claim(t, conn, {"branch_id": branch})
    if row is None:
        return "duplicate"
    try:
        amount = float(t.get("amount") or 0)
        if amount < 0 or amount > MAX_AMOUNT:
            return _finish(t, "rejected", reason="amount")
        if not _tenant_ok(conn["tenant_id"]):
            return _finish(t, "not_applied", reason="plan")
        cust = _find_card(conn, adapter, t.get("customer_id"))
        if not cust:
            return _finish(t, "unmatched", customer_id=None)
        ext = f"{t['provider']}:{t['ticket_id']}"
        try:
            res = M.create_visit(M.VisitIn(customer=cust["id"], amount=round(amount, 2), branch_id=branch, external_id=ext),
                                 c=_caller(conn))
        except HTTPException as e:
            if 400 <= e.status_code < 500:
                d = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
                return _finish(t, "refused", customer_id=cust["id"], reason=str(d.get("code") or d.get("message") or e.status_code)[:80])
            raise
        vid = ((res or {}).get("visit") or {}).get("id")
        if vid:
            _db.visits.update_one({"id": vid}, {"$set": {"source": "pos", "pos_provider": t["provider"], "pos_ticket_id": t["ticket_id"]}})
        _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"last_ticket_at": _now()}})
        return _finish(t, "matched", customer_id=cust["id"], visit_id=vid)
    except BaseException:
        _release(t)
        raise


def _apply_refund(conn: Dict[str, Any], adapter, t: Dict[str, Any]) -> str:
    from features import merchant_api as M
    row = _claim(t, conn, {})
    if row is None:
        return "duplicate"
    added = False
    try:
        sale = _db.pos_tickets.find_one({"provider": t["provider"], "ticket_id": t.get("refund_of"), "tenant_id": conn["tenant_id"]}, {"_id": 0})
        if not sale:
            return _finish(t, "refund_unknown_sale")
        after = _db.pos_tickets.find_one_and_update({"provider": t["provider"], "ticket_id": sale["ticket_id"]},
                                                    {"$inc": {"refunded_amount": float(t.get("amount") or 0)}}, return_document=True) or sale
        added = True
        full = float(after.get("refunded_amount") or 0) >= float(sale.get("amount") or 0) - 0.005
        if sale.get("status") == "matched" or (sale.get("status") == "partial_refund" and sale.get("visit_id")):
            if full:
                try:
                    M.cancel_visit(f"{t['provider']}:{sale['ticket_id']}",
                                   body=M.CancelIn(reason="Remboursement caisse", external_id=f"{t['provider']}:refund:{t['ticket_id']}"),
                                   c=_caller(conn))
                    _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": sale["ticket_id"]}, {"$set": {"status": "refunded"}})
                except HTTPException as e:
                    if not 400 <= e.status_code < 500:
                        raise
                    _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": sale["ticket_id"]}, {"$set": {"status": "refund_manual"}})
            else:
                _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": sale["ticket_id"]}, {"$set": {"status": "partial_refund"}})
        elif sale.get("status") in ("unmatched", "not_applied", "rejected"):
            _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": sale["ticket_id"]},
                                       {"$set": {"refund_state": "full" if full else "partial"}})
        return _finish(t, "refund_done", sale_ticket_id=sale["ticket_id"])
    except BaseException:
        # the refund's amount was added before the work: take it back so a retry counts it once
        try:
            if added:
                _db.pos_tickets.update_one({"provider": t["provider"], "ticket_id": t.get("refund_of")},
                                           {"$inc": {"refunded_amount": -float(t.get("amount") or 0)}})
        except Exception:
            pass
        _release(t)
        raise


def apply_ticket(conn: Dict[str, Any], t: Dict[str, Any], adapter=None) -> str:
    adapter = adapter or POS.get(conn["provider"])
    if t.get("kind") == "refund":
        return _apply_refund(conn, adapter, t)
    return _apply_sale(conn, adapter, t)


# ---------------------------------------------------------------------------
# Events (the webhook door and the tick)
# ---------------------------------------------------------------------------
def _conn_for(provider: str, merchant_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not merchant_id:
        return None
    return _db.pos_connections.find_one({"provider": provider, "merchant_id": merchant_id, "status": {"$ne": "disconnected"}}, {"_id": 0})


def _ticket_out(t: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not t:
        return None
    return {**t, "at": _aware(t.get("at"))}


def _run_event(ev: Dict[str, Any]) -> None:
    conn = _db.pos_connections.find_one({"id": ev.get("conn_id"), "status": {"$ne": "disconnected"}}, {"_id": 0}) if ev.get("conn_id") else None
    if not conn:
        _db.pos_events.update_one({"provider": ev["provider"], "id": ev["id"]}, {"$set": {"state": "ignored", "reason": "no_connection", "done_at": _now()}})
        return
    try:
        status = apply_ticket(conn, ev["ticket"])
        _db.pos_events.update_one({"provider": ev["provider"], "id": ev["id"]},
                                  {"$set": {"state": "done", "result": status, "done_at": _now()}, "$inc": {"attempts": 1}})
    except Exception as e:
        n = int(ev.get("attempts") or 0) + 1
        state = "failed" if n >= MAX_ATTEMPTS else "pending"
        _db.pos_events.update_one({"provider": ev["provider"], "id": ev["id"]},
                                  {"$set": {"state": state, "attempts": n, "error": f"{type(e).__name__}: {str(e)[:160]}", "tried_at": _now()}})


@router.post("/api/pos/{provider}/webhook")
async def webhook(provider: str, request: Request):
    adapter = POS.get(provider)
    if adapter is None:
        raise HTTPException(status_code=404, detail="Caisse inconnue.")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Trop gros.")
    sig = request.headers.get("x-square-hmacsha256-signature") or ""
    url = os.environ.get(f"{provider.upper()}_WEBHOOK_URL") or str(request.url)
    if not adapter.verify_webhook(sig, raw, url):
        raise HTTPException(status_code=401, detail="Signature invalide.")
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        return {"ok": True, "ignored": "not_json"}
    ev = adapter.parse_event(payload)
    if not ev.get("event_id"):
        return {"ok": True, "ignored": "no_event_id"}
    conn = _conn_for(adapter.name, ev.get("merchant_id"))
    now = _now()
    doc = {"id": str(ev["event_id"])[:120], "provider": adapter.name, "merchant_id": ev.get("merchant_id"), "type": ev.get("type"),
           "conn_id": (conn or {}).get("id"), "tenant_id": (conn or {}).get("tenant_id"), "ticket": _ticket_out(ev.get("ticket")),
           "at": now, "attempts": 0, "inline": False,
           "state": "pending" if (conn and ev.get("ticket")) else "ignored",
           "reason": None if conn else "no_connection"}
    if conn and not ev.get("ticket"):
        doc["reason"] = "not_a_ticket"
    try:
        _db.pos_events.insert_one(dict(doc))
    except Exception as e:
        if "duplicate" in str(e).lower() or "E11000" in str(e):
            return {"ok": True, "duplicate": True}
        raise
    if doc["state"] != "pending":
        return {"ok": True, "ignored": doc["reason"]}
    _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"last_event_at": now}})
    busy = _db.pos_events.count_documents({"conn_id": conn["id"], "inline": True, "at": {"$gte": now - timedelta(minutes=15)}})
    if busy >= INLINE_PER_15MIN:
        return {"ok": True, "queued": True}
    _db.pos_events.update_one({"provider": adapter.name, "id": doc["id"]}, {"$set": {"inline": True}})
    _run_event(doc)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Cards out
# ---------------------------------------------------------------------------
def _split(name: str):
    parts = (name or "").strip().split()
    return (parts[0] if parts else "Client"), " ".join(parts[1:])


def sync_customers(conn_id: str, limit: int = SYNC_PER_TICK) -> int:
    conn = _db.pos_connections.find_one({"id": conn_id, "status": "connected"}, {"_id": 0})
    if not conn or not _tenant_ok(conn["tenant_id"]):
        return 0
    adapter = POS.get(conn["provider"])
    linked = {l["customer_id"] for l in _db.pos_customer_links.find({"conn_id": conn_id}, {"_id": 0, "customer_id": 1})}
    rows = []
    for c in _db.customers.find({"tenant_id": conn["tenant_id"], "barcode_id": {"$exists": True, "$ne": None}, **_live()},
                                {"_id": 0, "id": 1, "name": 1, "barcode_id": 1}).sort("created_at", 1):
        if c["id"] in linked or not c.get("barcode_id"):
            continue
        given, family = _split(c.get("name") or "")
        rows.append({"fidclic_id": c["id"], "reference_id": _scan_code(conn["tenant_id"], c["barcode_id"]),
                     "given_name": given, "family_name": family})
        if len(rows) >= limit:
            break
    if not rows:
        return 0
    made = adapter.push_customers(_token(conn), rows)
    refs = {r["fidclic_id"]: r["reference_id"] for r in rows}
    for fid, pcid in made.items():
        _db.pos_customer_links.update_one({"conn_id": conn_id, "customer_id": fid}, {"$set": {
            "tenant_id": conn["tenant_id"], "provider": conn["provider"], "provider_customer_id": pcid,
            "reference_id": refs.get(fid), "at": _now()}}, upsert=True)
    _db.pos_connections.update_one({"id": conn_id}, {"$set": {"customers_synced_at": _now()}})
    return len(made)


# ---------------------------------------------------------------------------
# Night check and tokens
# ---------------------------------------------------------------------------
def reconcile(conn: Dict[str, Any], now: Optional[datetime] = None, begin: Optional[datetime] = None) -> int:
    now = now or _now()
    adapter = POS.get(conn["provider"])
    start = begin or ((_aware(conn.get("last_reconcile_at")) or _aware(conn.get("created_at")) or now) - timedelta(hours=2))
    locs = [l["id"] for l in conn.get("locations") or [] if l.get("id")]
    n = 0
    tickets = adapter.list_tickets(_token(conn), locs, start, now)
    for t in sorted(tickets, key=lambda x: (x["kind"] == "refund", _aware(x.get("at")) or now)):
        if apply_ticket(conn, t, adapter) not in ("duplicate",):
            n += 1
    return n


def _refresh(conn: Dict[str, Any], now: datetime) -> None:
    adapter = POS.get(conn["provider"])
    try:
        tok = adapter.refresh(_open(conn).get("refresh_token") or "")
    except PosError as e:
        if e.code in ("unauthorized", "reconnect", "no_token") or (e.status and 400 <= e.status < 500):
            _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"status": "error", "error": {
                "code": "reconnect", "message": "Square ne nous laisse plus lire vos ventes : reconnectez la caisse.", "at": now}}})
        else:
            _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"error": {"code": "refresh_later", "message": str(e)[:160], "at": now}}})
        return
    _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"tokens_sealed": _seal(tok), "expires_at": tok["expires_at"],
                                                                "status": "connected", "error": None}})


def run_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The 15-minute tick: retries, tokens, cards out, the night check. Idempotent."""
    now = now or _now()
    out = {"events": 0, "refreshed": 0, "synced": 0, "reconciled": 0, "errors": 0}
    if _db is None:
        return out
    for ev in list(_db.pos_events.find({"state": "pending"}, {"_id": 0}).sort("at", 1).limit(TICK_EVENTS)):
        _run_event(ev)
        out["events"] += 1
    paris = now.astimezone(PARIS)
    today = paris.strftime("%Y-%m-%d")
    synced = 0
    for conn in list(_db.pos_connections.find({"status": {"$in": ["connected", "error"]}}, {"_id": 0})):
        try:
            exp = _aware(conn.get("expires_at"))
            if exp and exp < now + REFRESH_BEFORE:
                _refresh(conn, now)
                out["refreshed"] += 1
                conn = _db.pos_connections.find_one({"id": conn["id"]}, {"_id": 0}) or conn
            if conn.get("status") != "connected" or not _tenant_ok(conn["tenant_id"]):
                continue
            if synced < SYNC_TOTAL_PER_TICK:
                k = sync_customers(conn["id"], limit=min(SYNC_PER_TICK, SYNC_TOTAL_PER_TICK - synced))
                synced += k
                out["synced"] += k
            if paris.hour >= RECONCILE_HOUR and conn.get("last_reconcile_day") != today:
                # the day is taken before the work: two ticks at once never ask twice
                took = _db.pos_connections.update_one({"id": conn["id"], "last_reconcile_day": conn.get("last_reconcile_day")},
                                                      {"$set": {"last_reconcile_day": today}})
                if getattr(took, "modified_count", 0):
                    out["reconciled"] += reconcile(conn, now)
                    _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"last_reconcile_at": now}})
        except Exception as e:
            out["errors"] += 1
            _db.pos_connections.update_one({"id": conn["id"]}, {"$set": {"error": {"code": "tick", "message": str(e)[:160], "at": now}}})
    return out


# ---------------------------------------------------------------------------
# Owner endpoints
# ---------------------------------------------------------------------------
def _adapter_or_404(provider: str):
    a = POS.get(provider)
    if a is None:
        raise _err(404, "unknown_caisse", "Caisse inconnue.")
    return a


def _mine(conn_id: str, tid: str) -> Dict[str, Any]:
    c = _db.pos_connections.find_one({"id": conn_id, "tenant_id": tid}, {"_id": 0})
    if not c:
        raise _err(404, "not_found", "Connexion introuvable.")
    return c


def _conn_out(c: Dict[str, Any]) -> Dict[str, Any]:
    start = datetime.now(PARIS).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    tick = {"tenant_id": c["tenant_id"], "conn_id": c["id"], "kind": "sale", "at": {"$gte": start}}
    return {"id": c["id"], "provider": c["provider"], "label": c.get("label"), "status": c.get("status"),
            "error": ({"code": c["error"].get("code"), "message": c["error"].get("message"), "at": _iso(c["error"].get("at"))}
                      if isinstance(c.get("error"), dict) else None),
            "merchant_name": c.get("merchant_name"), "locations": c.get("locations") or [], "location_map": c.get("location_map") or {},
            "connected_at": _iso(c.get("created_at")), "last_event_at": _iso(c.get("last_event_at")),
            "last_ticket_at": _iso(c.get("last_ticket_at")), "last_reconcile_day": c.get("last_reconcile_day"),
            "customers_linked": _db.pos_customer_links.count_documents({"conn_id": c["id"]}),
            "today": {"tickets": _db.pos_tickets.count_documents(tick),
                      "matched": _db.pos_tickets.count_documents({**tick, "status": "matched"})},
            "failed_events": _db.pos_events.count_documents({"conn_id": c["id"], "state": "failed"})}


@router.get("/api/owner/pos")
def page(token_data: TokenData = Depends(require_role(READERS))):
    _need_plan(token_data)
    tid = token_data.tenant_id
    providers = [{"name": n, "label": cls.label, "configured": cls().configured()} for n, cls in POS.adapters().items()]
    conns = [_conn_out(c) for c in _db.pos_connections.find({"tenant_id": tid, "status": {"$ne": "disconnected"}}, {"_id": 0})]
    return {"providers": providers, "connections": conns, "stores": _stores(tid)}


@router.post("/api/owner/pos/{provider}/connect")
def connect(provider: str, token_data: TokenData = Depends(require_role(OWNER))):
    a = _adapter_or_404(provider)
    _need_plan(token_data)
    if not a.configured():
        raise _err(409, "not_configured", f"La connexion {a.label} n'est pas encore ouverte.")
    state = secrets.token_urlsafe(32)
    _db.pos_oauth_states.insert_one({"state_hash": hashlib.sha256(state.encode()).hexdigest(), "provider": a.name,
                                     "tenant_id": token_data.tenant_id, "by": token_data.email, "at": _now(),
                                     "expires_at": _now() + timedelta(minutes=STATE_TTL_MIN)})
    return {"url": a.authorize_url(state)}


def _back(ok: bool, why: str = "") -> RedirectResponse:
    q = "caisse=ok" if ok else f"caisse=erreur&raison={why or 'inconnue'}"
    return RedirectResponse(f"/dashboard/parametres/api?{q}", status_code=303)


@router.get("/api/pos/{provider}/callback")
def callback(provider: str, code: str = "", state: str = "", error: str = ""):
    a = POS.get(provider)
    if a is None:
        return _back(False, "caisse")
    st = _db.pos_oauth_states.find_one_and_delete({"state_hash": hashlib.sha256((state or "").encode()).hexdigest(), "provider": a.name}) if state else None
    if not st or (_aware(st.get("expires_at")) or _now()) <= _now():
        return _back(False, "lien")
    if error or not code:
        return _back(False, "refus")
    tid = st["tenant_id"]
    if not _tenant_ok(tid):
        return _back(False, "plan")
    try:
        tok = a.exchange_code(code)
    except PosError:
        return _back(False, "code")
    mid = tok.get("merchant_id")
    other = _db.pos_connections.find_one({"provider": a.name, "merchant_id": mid, "status": {"$ne": "disconnected"},
                                          "tenant_id": {"$ne": tid}}, {"_id": 0, "id": 1})
    if not mid or other:
        a.revoke(tok["access_token"])
        return _back(False, "deja_liee")
    try:
        name = a.merchant_name(tok["access_token"])
        locs = a.list_locations(tok["access_token"])
    except PosError:
        name, locs = a.label, []
    stores = _stores(tid)
    now = _now()
    mine = _db.pos_connections.find_one({"tenant_id": tid, "provider": a.name}, {"_id": 0})
    fields = {"tenant_id": tid, "provider": a.name, "label": a.label, "merchant_id": mid, "merchant_name": name, "locations": locs,
              "default_branch": stores[0]["id"] if stores else None, "tokens_sealed": _seal(tok), "expires_at": tok["expires_at"],
              "status": "connected", "error": None, "connected_by": st.get("by"), "updated_at": now}
    if mine:
        keep = {k: v for k, v in (mine.get("location_map") or {}).items() if any(l["id"] == k for l in locs)}
        _db.pos_connections.update_one({"id": mine["id"]}, {"$set": {**fields, "location_map": keep}})
        cid = mine["id"]
    else:
        cid = "pos_" + uuid.uuid4().hex[:16]
        _db.pos_connections.insert_one({"id": cid, "created_at": now, "location_map": {}, **fields})
    try:
        import server as core
        core.log_audit("pos.connect", actor=st.get("by"), actor_type="user", tenant_id=tid, target=cid, meta={"provider": a.name})
    except Exception:
        pass
    return _back(True)


@router.put("/api/owner/pos/connections/{conn_id}/locations")
def set_locations(conn_id: str, body: Dict[str, Any] = Body(...), token_data: TokenData = Depends(require_role(OWNER))):
    c = _mine(conn_id, token_data.tenant_id)
    m = body.get("map") if isinstance(body, dict) else None
    if not isinstance(m, dict):
        raise _err(400, "bad_map", "Carte des magasins attendue.")
    locs = {l["id"] for l in c.get("locations") or []}
    stores = {s["id"] for s in _stores(token_data.tenant_id)}
    clean = {}
    for k, v in m.items():
        if k not in locs:
            raise _err(400, "unknown_location", "Cet emplacement n'est pas celui de votre caisse.")
        if v in (None, ""):
            continue
        if v not in stores:
            raise _err(400, "unknown_store", "Établissement inconnu.")
        clean[k] = v
    _db.pos_connections.update_one({"id": conn_id}, {"$set": {"location_map": clean, "updated_at": _now()}})
    return {"ok": True, "location_map": clean}


@router.post("/api/owner/pos/connections/{conn_id}/sync")
def sync_now(conn_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    _need_plan(token_data)
    c = _mine(conn_id, token_data.tenant_id)
    now = _now()
    took = _db.pos_connections.update_one(
        {"id": conn_id, "status": "connected",
         "$or": [{"manual_sync_at": {"$exists": False}}, {"manual_sync_at": None},
                 {"manual_sync_at": {"$lt": now - timedelta(seconds=MANUAL_COOLDOWN_S)}}]},
        {"$set": {"manual_sync_at": now}})
    if not getattr(took, "modified_count", 0):
        if c.get("status") != "connected":
            raise _err(409, "not_connected", "La caisse n'est pas connectée.")
        raise _err(429, "too_soon", "Une vérification vient d'être faite : réessayez dans 5 minutes.")
    try:
        pushed = sync_customers(conn_id, limit=SYNC_PER_TICK)
        n = reconcile(c, now, begin=now - timedelta(days=2))
    except PosError as e:
        return JSONResponse(status_code=502, content={"detail": {"code": e.code, "message": str(e)}})
    return {"ok": True, "customers_pushed": pushed, "tickets_applied": n}


@router.delete("/api/owner/pos/connections/{conn_id}")
def disconnect(conn_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    c = _mine(conn_id, token_data.tenant_id)
    tok = _open(c).get("access_token")
    if tok:
        POS.get(c["provider"]).revoke(tok)
    _db.pos_connections.update_one({"id": conn_id}, {"$set": {"status": "disconnected", "disconnected_at": _now(), "error": None},
                                                    "$unset": {"tokens_sealed": ""}})
    try:
        import server as core
        core.log_audit("pos.disconnect", actor=token_data.email, actor_type="user", tenant_id=token_data.tenant_id, target=conn_id,
                       meta={"provider": c["provider"]})
    except Exception:
        pass
    return {"ok": True}
