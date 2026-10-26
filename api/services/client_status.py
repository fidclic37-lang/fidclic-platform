"""
A client the business has paused hears nothing from it (user, 2026-10-15):
no campaign, automation, géolocalisation, push, SMS, e-mail, Wallet offer or
« Dernier message ». The card itself keeps working at the till — stamps and
points still count. Every path that sends something to a client asks here.

    customers.paused_at   set by « Mettre en pause », removed by « Reprendre »
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set


def is_paused(db, customer_id: Optional[str]) -> bool:
    """Read from the database: callers often hold a projected customer."""
    if db is None or not customer_id:
        return False
    from services import send_batch as _SB
    b = _SB.current()
    if b is not None and customer_id in b.ids:            # a big send read them all at once
        return b.paused(customer_id)
    try:
        return db.customers.find_one({"id": customer_id, "paused_at": {"$ne": None}}, {"_id": 1}) is not None
    except Exception:
        return False


def paused_ids(db, tenant_id: Optional[str]) -> Set[str]:
    if db is None or not tenant_id:
        return set()
    try:
        return set(db.customers.distinct("id", {"tenant_id": tenant_id, "paused_at": {"$ne": None}}))
    except Exception:
        return set()


def drop_paused(db, tenant_id: Optional[str], people: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The audience without its paused clients (one query for the whole list)."""
    people = list(people or [])
    gone = paused_ids(db, tenant_id)
    return [p for p in people if p.get("id") not in gone] if gone else people


NOT_PAUSED = {"$or": [{"paused_at": {"$exists": False}}, {"paused_at": None}]}
