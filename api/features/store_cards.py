"""
One card per establishment (user, 2026-10-12, multi-store): the design, the
programme, the reward, the paliers, the Pass Designer design and the Google
card are each establishment's. A client is always ruled by their HOME store's
card (customers.branch_id), wherever they are scanned.

How: card_templates keeps the account's card (no store_id) and, beside it,
one document per establishment that has its own (store_id). Every read and
write of card_templates goes through `StoreCardTemplates`, which picks the
document of the establishment « in context »:
  • a dashboard request: the establishment chosen in the menu (X-FidClic-Store);
  • a client's card, pass, Google card, scan rules, automations: their home store.
An establishment without its own document still reads the account's card — the
existing stores keep the design they had (« undo mat kro ») — and its first
edit copies it, so the change stays its own. An establishment created from now
on starts with its card OFF (branch.card_off) and a blank card: no signup
until its owner designs it; its first save switches it on.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_db = None
HEADER = b"x-fidclic-store"

# (tenant_id or None, store_id) — None tenant: « the menu's store, if it is this account's »
_STORE: contextvars.ContextVar = contextvars.ContextVar("fidclic_card_store", default=None)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def current() -> Optional[tuple]:
    return _STORE.get()


def set_store(tenant_id: Optional[str], store_id: Optional[str]) -> None:
    """For the rest of this request / task (a client's card: their home store)."""
    _STORE.set((tenant_id, store_id) if store_id else None)


def set_for_customer(cust: Optional[Dict[str, Any]]) -> None:
    """A client's home store. A client without one (a one-shop account, the
    owner's preview sample) keeps the establishment already in context."""
    if cust and cust.get("tenant_id") and cust.get("branch_id"):
        set_store(cust["tenant_id"], cust["branch_id"])


@contextmanager
def store(tenant_id: Optional[str], store_id: Optional[str]):
    tok = _STORE.set((tenant_id, store_id) if store_id else None)
    try:
        yield
    finally:
        _STORE.reset(tok)


def customer_store(argname: str = "cust"):
    """Decorator: run the function under the card of its customer's home store
    (the argument `argname`, a customer document)."""
    import functools
    import inspect

    def deco(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*a, **k):
            cust = None
            try:
                cust = sig.bind_partial(*a, **k).arguments.get(argname)
            except TypeError:
                pass
            if isinstance(cust, dict) and cust.get("tenant_id") and cust.get("branch_id"):
                with store(cust["tenant_id"], cust["branch_id"]):
                    return fn(*a, **k)
            return fn(*a, **k)
        return wrapper
    return deco


def payload_store(fn):
    """Decorator for the pass / Google builders: the card payload says whose
    card it is (payload["store_id"], set by _serialize_card_payload)."""
    import functools

    @functools.wraps(fn)
    def wrapper(payload, *a, **k):
        if isinstance(payload, dict) and payload.get("store_id"):
            tid = (payload.get("tenant") or {}).get("id") or (payload.get("customer") or {}).get("tenant_id")
            if tid:
                with store(tid, payload["store_id"]):
                    return fn(payload, *a, **k)
        return fn(payload, *a, **k)
    return wrapper


def own_card(tid: str, sid: Optional[str]) -> bool:
    """Does this establishment have its own card document (designed on its own)?"""
    if not sid or _db is None:
        return False
    return _db["card_templates"]._real.find_one({"tenant_id": tid, "store_id": sid}, {"_id": 1}) is not None


# One card read asks for the account's establishments several times (whose
# card, is it off, its name): kept for the request (cleared when it starts and
# ends, StoreMiddleware) and 3 s at most, so one preview reads them once.
_BR: Dict[str, tuple] = {}
_BR_TTL = 3.0


def _branches(tid: str) -> list:
    import time
    hit = _BR.get(tid)
    if hit and time.monotonic() - hit[0] < _BR_TTL:
        return hit[1]
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "branches": 1}) if _db is not None else None
    branches = (t or {}).get("branches") or []
    if len(_BR) > 500:
        _BR.clear()
    _BR[tid] = (time.monotonic(), branches)
    return branches


def forget(tid: Optional[str] = None) -> None:
    """An establishment changed (created, renamed, its card switched on)."""
    if tid is None:
        _BR.clear()
    else:
        _BR.pop(tid, None)


def _branch(tid: str, sid: str) -> Optional[Dict[str, Any]]:
    return next((b for b in _branches(tid) if b.get("id") == sid), None)


def store_for(tid: Any) -> Optional[str]:
    """The establishment in context for this account, or None (the account's card)."""
    cur = _STORE.get()
    if not cur or not isinstance(tid, str):
        return None
    ctid, sid = cur
    if ctid is not None and ctid != tid:
        return None
    if ctid is None and not _branch(tid, sid):          # the menu's store must be this account's
        return None
    return sid


def store_name(tid: str, sid: Optional[str]) -> Optional[str]:
    """The establishment's own name when the account has several (its card,
    pass and signup page say « ROYAL TRIM PALISSY », not the account's name)."""
    if not sid or _db is None:
        return None
    open_ = [b for b in _branches(tid) if b.get("id") and b.get("status") != "closed"]
    if len(open_) < 2:
        return None
    b = next((b for b in open_ if b["id"] == sid), None)
    return (b or {}).get("name") or None


def card_off(tid: str, sid: Optional[str]) -> bool:
    b = _branch(tid, sid) if sid else None
    return bool(b and b.get("card_off"))


class StoreCardTemplates:
    """card_templates, read and written for the establishment in context."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @staticmethod
    def _tid(flt: Any) -> Optional[str]:
        if isinstance(flt, dict) and isinstance(flt.get("tenant_id"), str) and "store_id" not in flt:
            return flt["tenant_id"]
        return None

    def find_one(self, flt=None, *a, **k):
        tid = self._tid(flt)
        if tid is None:
            if isinstance(flt, dict) and "store_id" not in flt:
                return self._real.find_one({**flt, "store_id": None}, *a, **k)
            return self._real.find_one(flt, *a, **k)
        sid = store_for(tid)
        if sid:
            doc = self._real.find_one({**flt, "store_id": sid}, *a, **k)
            if doc is not None:
                return doc
            if card_off(tid, sid):
                return None                          # a new establishment: blank, never another's
        return self._real.find_one({**flt, "store_id": None}, *a, **k)

    def find(self, flt=None, *a, **k):
        flt = dict(flt or {})
        if "store_id" not in flt:
            flt["store_id"] = None                   # account-wide scans read the account's cards
        return self._real.find(flt, *a, **k)

    def _ensure(self, tid: str, sid: str) -> None:
        """The establishment's own document, made on its first edit: a copy of
        the account's card (an existing store keeps its design), or blank (a
        store created since 2026-10-12)."""
        if self._real.find_one({"tenant_id": tid, "store_id": sid}, {"_id": 1}):
            return
        base: Dict[str, Any] = {}
        if not card_off(tid, sid):
            base = self._real.find_one({"tenant_id": tid, "store_id": None}, {"_id": 0}) or {}
        self._real.insert_one({**base, "tenant_id": tid, "store_id": sid, "store_created_at": _now()})

    def update_one(self, flt, update, *a, **k):
        tid = self._tid(flt)
        if tid is None:
            return self._real.update_one(flt, update, *a, **k)
        sid = store_for(tid)
        if sid:
            self._ensure(tid, sid)
            res = self._real.update_one({**flt, "store_id": sid}, update, *a, **k)
            if card_off(tid, sid) and _db is not None:   # designed: the card is on
                _db.tenants.update_one({"id": tid, "branches.id": sid}, {"$set": {"branches.$.card_off": False,
                                                                                  "branches.$.card_on_at": _now()}})
                forget(tid)
            return res
        return self._real.update_one({**flt, "store_id": None}, update, *a, **k)

    def count_documents(self, flt=None, *a, **k):
        flt = dict(flt or {})
        if "store_id" not in flt:
            flt["store_id"] = None
        return self._real.count_documents(flt, *a, **k)


def _install(db) -> None:
    """db.card_templates (and db["card_templates"]) → the store-aware proxy."""
    cls = type(db)
    if getattr(cls, "_fidclic_store_cards", False):
        return
    orig_getitem = cls.__getitem__

    def getitem(self, name):
        coll = orig_getitem(self, name)
        # a thin wrapper per access (pymongo builds a new Collection each time too)
        return StoreCardTemplates(coll) if name == "card_templates" else coll

    def getattr_(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getitem(self, name)
    cls.__getitem__ = getitem
    cls.__getattr__ = getattr_
    cls._fidclic_store_cards = True


def init(db) -> None:
    global _db
    _db = db
    _install(db)
    try:
        db["card_templates"]._real.create_index([("tenant_id", 1), ("store_id", 1)])
    except Exception:
        pass


class StoreMiddleware:
    """Pure ASGI: the menu's establishment (X-FidClic-Store) for this request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            val = None
            for k, v in scope.get("headers") or []:
                if k == HEADER:
                    val = v.decode("latin-1").strip()
                    break
            tok = _STORE.set((None, val) if val and val != "all" else None)
            forget()                               # the establishments, read afresh for this request
            try:
                return await self.app(scope, receive, send)
            finally:
                _STORE.reset(tok)
                forget()
        return await self.app(scope, receive, send)
