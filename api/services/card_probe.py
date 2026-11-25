"""
Failed card lookups, counted per client IP (pentest 2026-11-25, finding 6).

A card number is printed in its QR, so numbers can be guessed: an unknown one
answers 404, a real one without its owner key 403. Each such FAILED lookup of
/api/card/{bc} (server._card_access) is one row here; after LIMIT failures in
WINDOW from one IP, that IP gets 429 on every card route until the window
has passed. A successful lookup is never counted and never slowed beyond one
indexed count — real customers open their card with its key and never fail.

Kept in Mongo (one row per failure, TTL-expired), not in process memory:
on Vercel every request may land on another instance. The IP is
server._client_ip's — the first X-Forwarded-For address, which Vercel's edge
sets itself (it overwrites what a client sends), the socket address otherwise.

Never raises: a counter outage must not lock customers out of their card.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

COLLECTION = "card_probe_fails"
LIMIT = 30
WINDOW = timedelta(minutes=10)
MESSAGE = "Trop de tentatives, réessayez dans quelques minutes."
_ready: set = set()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll(db):
    c = db[COLLECTION]
    if id(db) not in _ready:
        try:
            c.create_index([("ip", 1), ("at", -1)])
            c.create_index("at", expireAfterSeconds=int(WINDOW.total_seconds()), name="at_ttl")
        except Exception as exc:  # noqa: BLE001
            print(f"card probe: index not created ({exc})")
        _ready.add(id(db))
    return c


def _key(ip: str) -> str:
    return (ip or "").strip()[:64]


def _failures(db, ip: str) -> int:
    return _coll(db).count_documents({"ip": _key(ip), "at": {"$gt": _now() - WINDOW}}, limit=LIMIT)


def blocked(db, ip: str) -> bool:
    """True when this IP already failed LIMIT times within WINDOW."""
    if not _key(ip):
        return False
    try:
        return _failures(db, ip) >= LIMIT
    except Exception as exc:  # noqa: BLE001
        print(f"card probe: count failed (non-fatal): {exc}")
        return False


def fail(db, ip: str) -> None:
    """One failed lookup from this IP (nothing more is stored once it is blocked)."""
    if not _key(ip):
        return
    try:
        if _failures(db, ip) >= LIMIT:
            return
        _coll(db).insert_one({"ip": _key(ip), "at": _now()})
    except Exception as exc:  # noqa: BLE001
        print(f"card probe: not recorded (non-fatal): {exc}")
