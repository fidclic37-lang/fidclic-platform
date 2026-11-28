"""What every caisse plug gives the frame (features/pos_connectors.py).

A TICKET is a plain dict, the same for every brand:
    provider     "square", …
    ticket_id    the caisse's own id of the sale or refund
    kind         "sale" | "refund"
    amount       euros (float), what was paid for the goods — never the tip
    currency     "EUR", …
    location_id  the caisse's shop / register id (mapped to a FidClic store)
    customer_id  the caisse's customer id on the sale, or None (not scanned)
    refund_of    for a refund: the sale's ticket_id
    at           aware UTC datetime

A plug (class) has:
    name, label, configured()
    authorize_url(state) · exchange_code(code) · refresh(refresh_token) · revoke(access_token)
        tokens = {access_token, refresh_token, expires_at (datetime), merchant_id}
    merchant_name(token) · list_locations(token) → [{id, name, currency, status}]
    verify_webhook(signature, raw_body, url) → bool    (never True without a key)
    parse_event(payload) → {event_id, merchant_id, type, ticket | None}
    list_tickets(token, location_ids, begin, end) → [ticket]     (the nightly check)
    get_sale(token, ticket_id) → ticket | None
    customer_reference(token, customer_id) → the card code stored on the caisse's customer, or None
    push_customers(token, rows) → {fidclic_id: caisse_customer_id}
        rows = [{fidclic_id, reference_id, given_name, family_name}] — nothing else ever leaves
    delete_customers(token, caisse_customer_ids) → how many (only the ones FidClic made)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# Currencies without cents (ISO 4217 exponent 0): their amounts are not divided by 100.
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}


class PosError(Exception):
    """A caisse said no, or could not be reached. `code` is ours, the message is shown to the owner."""

    def __init__(self, message: str, code: str = "pos_error", status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.status = status


def money(m: Any) -> float:
    """{amount: 1250, currency: "EUR"} → 12.5. Missing or broken → 0.0."""
    if not isinstance(m, dict):
        return 0.0
    try:
        raw = int(m.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0
    cur = str(m.get("currency") or "").upper()
    return float(raw) if cur in ZERO_DECIMAL else raw / 100.0


def parse_time(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not isinstance(v, str) or not v:
        return None
    s = v.strip().replace("Z", "+00:00")
    if "." in s:                                   # 2026-11-28T10:15:00.123+00:00 → drop the fraction
        head, _, tail = s.partition(".")
        tz = ""
        for sign in ("+", "-"):
            if sign in tail:
                tz = sign + tail.split(sign, 1)[1]
                break
        s = head + tz
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
