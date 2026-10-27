"""
Whose phone is this card on? (user, 2026-10-08: « maine uska QR scan kiya toh
uska card khula, jabki mera card khulna chahiye tha »)

A card's QR encodes its public link, /card/FT-…, so the till can read it and a
phone camera can open it. That same link must NOT show the card to whoever
scans it: a friend scanning my card has to land on MY card for this shop, or
on the signup form when they have none.

THE OWNER KEY
    Every card has a key, an HMAC of its id with the server secret. Only the
    links that reach the card's owner carry it (?k=…): the Wallet pass's back
    and tiles, the signup confirmation, SMS / e-mail / push links, the staff
    « activer les notifications » QR. The QR on the card never carries it.

    The phone that opens a link with the right key keeps {card: key} in its
    storage (« my cards »). Opening /card/X without the key, the page asks
    `whose()` what to show, sending the cards this phone holds with their keys:

        • X is one of them               → the card
        • another of them is the same shop → that card (my own, not my friend's)
                                            — the same ESTABLISHMENT when the
                                            account has several (2026-10-14)
        • none                           → the signup form, the scanned card
                                            as parrain (Parrainage, never QR)

    A card removed from Apple Wallet no longer counts as held: Wallet tells us
    (the DELETE registration call) and the phone is told to forget it.

    The shop's own team (a signed-in owner / manager / staff of that shop, or
    a super admin) always sees the card: the dashboard opens customers' cards.
"""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


def _secret() -> bytes:
    from auth import _secret as signing_key          # never the committed key on Vercel (incident 2026-10-27)
    return ("card-owner:" + signing_key()).encode()


def key_for(barcode_id: str) -> str:
    bc = (barcode_id or "").strip().upper()
    return hmac.new(_secret(), bc.encode(), hashlib.sha256).hexdigest()[:20]


def valid(barcode_id: str, key: Optional[str]) -> bool:
    return bool(key) and hmac.compare_digest(key_for(barcode_id), str(key).strip().lower())


def owner_url(base: str, barcode_id: str, path: str = "", query: Optional[Dict[str, Any]] = None) -> str:
    """{base}/card/{id}{path}?…&k=… — a link for the card's owner only."""
    bc = (barcode_id or "").strip().upper()
    q = {k: v for k, v in (query or {}).items() if v is not None}
    q["k"] = key_for(bc)
    return f"{base}/card/{bc}{path}?{urllib.parse.urlencode(q)}"


def with_key(url: str, barcode_id: str) -> str:
    """Add the owner key to a link we already built."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}k={key_for(barcode_id)}"


def _utc(d):
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def held(customer: Dict[str, Any]) -> bool:
    """Still on the phone? False once every Apple Wallet that had the card
    removed it (wallet_passes.unregister_device), until its owner opens it
    again with the key — signing up again gives it back (card_claimed_at)."""
    removed = _utc(customer.get("wallet_removed_at"))
    if not removed:
        return True
    claimed = _utc(customer.get("card_claimed_at"))
    return bool(claimed and claimed > removed)


def whose(db, barcode_id: str, key: Optional[str], mine: Dict[str, str],
          viewer: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """What /card/{barcode_id} shows on this phone. None when the card does
    not exist (the page shows its own « carte introuvable »)."""
    bc = (barcode_id or "").strip().upper()
    card = db.customers.find_one({"barcode_id": bc}, {"_id": 0, "tenant_id": 1, "barcode_id": 1, "branch_id": 1})
    if not card:
        return None
    tid = card.get("tenant_id")

    # cards this phone really holds: right key, still exists, not removed from Wallet
    proven = {b.strip().upper(): k for b, k in (mine or {}).items() if b and valid(b, k)}
    drop = [b for b in (mine or {}) if b.strip().upper() not in proven]
    rows = {c["barcode_id"]: c for c in db.customers.find(
        {"barcode_id": {"$in": list(proven)}},
        {"_id": 0, "barcode_id": 1, "tenant_id": 1, "branch_id": 1, "wallet_removed_at": 1, "card_claimed_at": 1})}
    for b in list(proven):
        if b not in rows or not held(rows[b]):
            drop.append(b)
            proven.pop(b)

    out: Dict[str, Any] = {"drop": sorted(set(drop))}
    if valid(bc, key):                                   # the owner's own link
        db.customers.update_one({"barcode_id": bc}, {"$set": {"card_claimed_at": datetime.now(timezone.utc)}})
        return {**out, "drop": [b for b in out["drop"] if b != bc], "view": "card", "key": key_for(bc)}
    if bc in proven:
        return {**out, "view": "card"}
    if viewer and (viewer.get("role") == "super_admin" or
                   (viewer.get("tenant_id") == tid and viewer.get("role") in ("business_owner", "manager", "staff"))):
        return {**out, "view": "card", "shop": True}
    # An account with several establishments: one card per establishment
    # (user, 2026-10-14: my Liberté card opened when I scanned my friend's
    # Palissy card — I must get Palissy's signup, as a new client there). A
    # client never given a store belongs to the main one.
    tenant = db.tenants.find_one({"id": tid}, {"_id": 0, "slug": 1, "branches": 1}) or {}
    open_ = [b for b in tenant.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    main = next((b["id"] for b in open_ if b.get("is_main") or b["id"] == "main"), open_[0]["id"] if open_ else None)

    def store_of(row: Dict[str, Any]) -> Optional[str]:
        return (row.get("branch_id") or main) if len(open_) >= 2 else None
    here = store_of(card)
    own = next((b for b in proven if rows[b].get("tenant_id") == tid and store_of(rows[b]) == here), None)
    if own:
        return {**out, "view": "own", "barcode_id": own}
    store = next((b.get("slug") for b in open_ if b["id"] == here), None) if here else None
    return {**out, "view": "join", "slug": tenant.get("slug"), "parrain": bc, **({"store": store} if store else {})}


def owned_from(pairs: Iterable) -> Dict[str, str]:
    """The body's `mine`, as {card: key}, whatever shape the page sent."""
    out: Dict[str, str] = {}
    if isinstance(pairs, dict):
        pairs = pairs.items()
    for p in pairs or []:
        try:
            b, k = p
        except (TypeError, ValueError):
            continue
        if isinstance(b, str) and isinstance(k, str) and len(out) < 50:
            out[b.strip().upper()] = k.strip()
    return out
