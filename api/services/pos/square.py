"""The Square plug (see base.py for what a plug gives the frame).

Environment (Vercel / local):
    SQUARE_ENV                     "sandbox" (default) | "production"
    SQUARE_APPLICATION_ID          sandbox-sq0idb-… / sq0idp-…
    SQUARE_APPLICATION_SECRET      the OAuth secret (server only, never in a link)
    SQUARE_WEBHOOK_SIGNATURE_KEY   the webhook subscription's key
    SQUARE_WEBHOOK_URL             the exact notification URL set in Square (it is signed)
    SQUARE_API_BASE                sandbox only: a local stand-in for Square (e2e); ignored in production

How a card reaches a Square sale: FidClic pushes each card as a Square
customer whose reference_id is the card's own code (what its QR says).
Square's till scans a customer's QR/barcode and adds the customer whose
reference id it is (Square help 7387); the finished payment then carries
that customer_id, which comes back to us on the webhook.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from services.pos.base import PosError, iso, money, parse_time

SQUARE_VERSION = "2025-01-23"
SCOPES = ["MERCHANT_PROFILE_READ", "PAYMENTS_READ", "ORDERS_READ", "CUSTOMERS_READ", "CUSTOMERS_WRITE"]
BATCH = 100                     # Square's bulk-create limit
MAX_PAGES = 50                  # the nightly check reads at most 50 pages a location (≈ 5 000 tickets)
TIMEOUT_S = 10


def _env(k: str) -> str:
    return (os.environ.get(k) or "").strip()


class SquareAdapter:
    name = "square"
    label = "Square"

    def __init__(self):
        self.app_id = _env("SQUARE_APPLICATION_ID")
        self.secret = _env("SQUARE_APPLICATION_SECRET")
        self.sig_key = _env("SQUARE_WEBHOOK_SIGNATURE_KEY")
        prod = _env("SQUARE_ENV").lower() == "production"
        self.base = "https://connect.squareup.com" if prod else "https://connect.squareupsandbox.com"
        # a local stand-in for Square's sandbox (the e2e journey); never in production
        override = _env("SQUARE_API_BASE")
        if override and not prod:
            self.base = override.rstrip("/")

    def configured(self) -> bool:
        return bool(self.app_id and self.secret)

    # ------------------------------------------------------------------ HTTP
    def http(self, method: str, path: str, token: Optional[str] = None, json: Optional[dict] = None,
             params: Optional[dict] = None, client_auth: bool = False):
        """One call to Square → (status, body dict). Replaced by a fake in tests."""
        import requests
        headers = {"Square-Version": SQUARE_VERSION, "Accept": "application/json", "Content-Type": "application/json"}
        if client_auth:
            headers["Authorization"] = "Client " + self.secret
        elif token:
            headers["Authorization"] = "Bearer " + token
        try:
            r = requests.request(method, self.base + path, headers=headers, json=json, params=params,
                                 timeout=TIMEOUT_S, allow_redirects=False)
        except Exception as e:
            raise PosError(f"Square injoignable : {type(e).__name__}", code="unreachable")
        try:
            body = r.json()
        except Exception:
            body = {}
        return r.status_code, body if isinstance(body, dict) else {}

    def _call(self, method: str, path: str, **kw) -> Dict[str, Any]:
        status, body = self.http(method, path, **kw)
        if status >= 400:
            errs = body.get("errors") or []
            what = ", ".join(str(e.get("code") or "") for e in errs if isinstance(e, dict)) or f"HTTP {status}"
            code = "unauthorized" if status in (401, 403) else ("not_found" if status == 404 else "square_error")
            raise PosError(f"Square a refusé : {what}", code=code, status=status)
        return body

    # ----------------------------------------------------------------- OAuth
    def authorize_url(self, state: str) -> str:
        q = {"client_id": self.app_id, "scope": " ".join(SCOPES), "session": "false", "state": state}
        redirect = _env("SQUARE_REDIRECT_URL")
        if redirect:
            q["redirect_uri"] = redirect
        return f"{self.base}/oauth2/authorize?{urlencode(q)}"

    def _tokens(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not body.get("access_token"):
            raise PosError("Square n'a pas donné de jeton.", code="no_token")
        return {"access_token": body["access_token"], "refresh_token": body.get("refresh_token") or "",
                "expires_at": parse_time(body.get("expires_at")) or (datetime.now(timezone.utc) + timedelta(days=30)),
                "merchant_id": body.get("merchant_id") or ""}

    def exchange_code(self, code: str) -> Dict[str, Any]:
        j = {"client_id": self.app_id, "client_secret": self.secret, "code": code, "grant_type": "authorization_code"}
        redirect = _env("SQUARE_REDIRECT_URL")
        if redirect:
            j["redirect_uri"] = redirect
        return self._tokens(self._call("POST", "/oauth2/token", json=j))

    def refresh(self, refresh_token: str) -> Dict[str, Any]:
        return self._tokens(self._call("POST", "/oauth2/token", json={
            "client_id": self.app_id, "client_secret": self.secret, "refresh_token": refresh_token, "grant_type": "refresh_token"}))

    def revoke(self, access_token: str) -> bool:
        try:
            self._call("POST", "/oauth2/revoke", json={"client_id": self.app_id, "access_token": access_token}, client_auth=True)
            return True
        except PosError:
            return False

    # ---------------------------------------------------------------- shop
    def merchant_name(self, token: str) -> str:
        m = (self._call("GET", "/v2/merchants/me", token=token).get("merchant") or {})
        return str(m.get("business_name") or m.get("id") or "Square")[:120]

    def list_locations(self, token: str) -> List[Dict[str, Any]]:
        out = []
        for l in self._call("GET", "/v2/locations", token=token).get("locations") or []:
            if isinstance(l, dict) and l.get("id"):
                out.append({"id": str(l["id"]), "name": str(l.get("name") or l["id"])[:120],
                            "currency": l.get("currency"), "status": l.get("status")})
        return out

    # -------------------------------------------------------------- webhook
    def verify_webhook(self, signature: str, raw_body: bytes, url: str) -> bool:
        if not self.sig_key or not signature:
            return False
        want = base64.b64encode(hmac.new(self.sig_key.encode(), url.encode() + (raw_body or b""), hashlib.sha256).digest()).decode()
        return hmac.compare_digest(want, signature.strip())

    def _sale(self, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(p, dict) or p.get("status") != "COMPLETED" or not p.get("id"):
            return None
        m = p.get("amount_money") or {}
        return {"provider": self.name, "ticket_id": str(p["id"]), "kind": "sale", "amount": money(m),
                "currency": str((m or {}).get("currency") or "EUR").upper(), "location_id": p.get("location_id"),
                "customer_id": p.get("customer_id") or None, "refund_of": None,
                "at": parse_time(p.get("created_at")) or datetime.now(timezone.utc)}

    def _refund(self, r: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(r, dict) or r.get("status") != "COMPLETED" or not r.get("id") or not r.get("payment_id"):
            return None
        m = r.get("amount_money") or {}
        return {"provider": self.name, "ticket_id": str(r["id"]), "kind": "refund", "amount": money(m),
                "currency": str((m or {}).get("currency") or "EUR").upper(), "location_id": r.get("location_id"),
                "customer_id": None, "refund_of": str(r["payment_id"]),
                "at": parse_time(r.get("created_at")) or datetime.now(timezone.utc)}

    def parse_event(self, payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"event_id": None, "merchant_id": None, "type": None, "ticket": None}
        kind = str(payload.get("type") or "")
        obj = ((payload.get("data") or {}).get("object") or {}) if isinstance(payload.get("data"), dict) else {}
        ticket = None
        if kind in ("payment.created", "payment.updated"):
            ticket = self._sale(obj.get("payment"))
        elif kind in ("refund.created", "refund.updated"):
            ticket = self._refund(obj.get("refund"))
        return {"event_id": payload.get("event_id"), "merchant_id": payload.get("merchant_id"), "type": kind, "ticket": ticket}

    # -------------------------------------------------------- nightly check
    def _pages(self, path: str, key: str, token: str, params: Dict[str, Any]):
        cursor = None
        for _ in range(MAX_PAGES):
            q = dict(params)
            if cursor:
                q["cursor"] = cursor
            body = self._call("GET", path, token=token, params=q)
            for row in body.get(key) or []:
                yield row
            cursor = body.get("cursor")
            if not cursor:
                return

    def list_tickets(self, token: str, location_ids: List[str], begin: datetime, end: datetime) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for loc in location_ids or []:
            q = {"begin_time": iso(begin), "end_time": iso(end), "location_id": loc, "sort_order": "ASC"}
            for p in self._pages("/v2/payments", "payments", token, q):
                t = self._sale(p)
                if t:
                    out.append(t)
            for r in self._pages("/v2/refunds", "refunds", token, {**q, "status": "COMPLETED"}):
                t = self._refund(r)
                if t:
                    out.append(t)
        return out

    def get_sale(self, token: str, ticket_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._sale((self._call("GET", f"/v2/payments/{ticket_id}", token=token).get("payment")) or {})
        except PosError as e:
            if e.code == "not_found":
                return None
            raise

    # ------------------------------------------------------------ customers
    def customer_reference(self, token: str, customer_id: Optional[str]) -> Optional[str]:
        if not customer_id:
            return None
        try:
            c = self._call("GET", f"/v2/customers/{customer_id}", token=token).get("customer") or {}
        except PosError as e:
            if e.code == "not_found":
                return None
            raise
        ref = c.get("reference_id")
        return str(ref)[:300] if ref else None

    def push_customers(self, token: str, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for i in range(0, len(rows or []), BATCH):
            chunk = rows[i:i + BATCH]
            body = {"customers": {r["fidclic_id"]: {k: v for k, v in {
                "given_name": (r.get("given_name") or "")[:100], "family_name": (r.get("family_name") or "")[:100],
                "reference_id": r["reference_id"], "note": "Carte FidClic"}.items() if v} for r in chunk}}
            res = self._call("POST", "/v2/customers/bulk-create", token=token, json=body).get("responses") or {}
            for fid, one in res.items():
                cid = ((one or {}).get("customer") or {}).get("id")
                if cid:
                    out[fid] = str(cid)
        return out
