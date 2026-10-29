"""
One request, one read of the same document.

WHY
    A scan was measured at 1 222 ms in production, 1 068 ms of it database, over
    70 round trips (Server-Timing, 2026-10-14). Counted locally, 22 of 31 were
    the SAME four documents fetched again and again inside one request: the
    tenant six times, the card template five, the plan settings four. On a
    shared Atlas every one of those costs ~15 ms, and none of them could have
    changed between the first read and the last.

WHAT IT DOES
    `tenants`, `card_templates` and `plan_settings` are read through a memo
    that lives for exactly one request. The same `find_one` is answered from it;
    anything else goes straight through.

WHAT IT DELIBERATELY LEAVES ALONE
    `customers` is not memoised. The scan writes it in the middle of the
    request and reads it again afterwards, on purpose — the figures after the
    visit are what the objectifs and the receipt are built from. A memo there
    would have to be invalidated exactly right to be correct, and being wrong
    means a client's visit silently not counting. Not worth 7 round trips.

    Writes drop that collection's memo anyway, so a request that saves the card
    template and reads it back still sees what it wrote.

    Outside a request — crons, startup, scripts — the contextvar is unset and
    nothing is cached at all.

WRITE HOOKS
    The same wrapper lets a feature hear every write to a collection, wherever
    it comes from: `on_write(name, fn)`. `fn(collection, method, args, kwargs)`
    runs before the write and may return a callable run after it (never let it
    break the write). The register of past days (features/visit_days) hears
    `visits` and what decides CA FidClic this way, instead of every writer
    having to remember it.
"""
from __future__ import annotations

import contextvars
from typing import Any, Callable, Dict, Optional

# Read many times per request, written rarely, and never by the till.
CACHED = ("tenants", "card_templates", "plan_settings",
          "brain_shop")             # a shop's facts for the Profil client page (features/client_brain)
WRITES = ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
          "delete_one", "delete_many", "find_one_and_update", "find_one_and_replace",
          "find_one_and_delete", "bulk_write")

HOOKS: Dict[str, Callable[..., Optional[Callable[[], None]]]] = {}


def on_write(name: str, fn: Callable[..., Optional[Callable[[], None]]]) -> None:
    HOOKS[name] = fn


_REQ: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "fidclic_doc_cache", default=None)


def begin() -> Any:
    """Start a memo for this request; returns the token to reset with."""
    return _REQ.set({})


def end(token: Any) -> None:
    try:
        _REQ.reset(token)
    except Exception:
        pass


def _key(name: str, flt: Any, proj: Any) -> Optional[str]:
    """A key, or None when this call is not safe to remember.

    Only a plain filter of scalars — no regex, no $-operators carrying
    objects, nothing whose repr could collide — and only the shapes the hot
    paths actually use."""
    if not isinstance(flt, dict) or not flt:
        return None
    for v in flt.values():
        if not isinstance(v, (str, int, float, bool, type(None))):
            return None
    try:
        shape = sorted(proj.items()) if isinstance(proj, dict) else proj
        return "%s|%r|%r" % (name, sorted(flt.items()), shape)
    except Exception:
        return None


class Memo:
    """A collection that answers the same find_one once per request."""

    def __init__(self, real, name: str):
        self._real = real
        self._name = name

    def __getattr__(self, attr):
        target = getattr(self._real, attr)
        if attr in WRITES:
            def wrapped(*a, **k):
                box = _REQ.get()
                if box is not None:
                    # what was read before this write is no longer the truth
                    for key in [x for x in box if x.startswith(f"{self._name}|")]:
                        box.pop(key, None)
                return target(*a, **k)
            return wrapped
        return target

    def find_one(self, flt=None, projection=None, *a, **k):
        box = _REQ.get()
        if box is None or a or k:
            return self._real.find_one(flt, projection, *a, **k)
        key = _key(self._name, flt, projection)
        if key is None:
            return self._real.find_one(flt, projection)
        if key in box:
            return box[key]
        doc = self._real.find_one(flt, projection)
        box[key] = doc
        return doc


class Watched:
    """A collection whose writes a hook hears (WRITE HOOKS above)."""

    def __init__(self, real, name: str):
        self._real = real
        self._name = name

    def __getattr__(self, attr):
        target = getattr(self._real, attr)
        hook = HOOKS.get(self._name)
        if attr not in WRITES or hook is None:
            return target

        def wrapped(*a, **k):
            try:
                after = hook(self._real, attr, a, k)
            except Exception as exc:          # a hook never stops a write
                print(f"doc_cache: {self._name}.{attr} hook failed ({exc})")
                after = None
            out = target(*a, **k)
            if after:
                try:
                    after()
                except Exception as exc:
                    print(f"doc_cache: {self._name}.{attr} after-hook failed ({exc})")
            return out
        return wrapped


def install(db) -> None:
    """db.tenants / db["tenants"] … → the memo. Idempotent."""
    cls = type(db)
    if getattr(cls, "_fidclic_doc_cache", False):
        return
    orig_getitem = cls.__getitem__

    def getitem(self, name):
        coll = orig_getitem(self, name)
        if name in HOOKS:
            box = self.__dict__.setdefault("_fidclic_watched", {})
            w = box.get(name)
            if w is None or w._real is not coll:
                w = Watched(coll, name)
                box[name] = w
            return w
        if name not in CACHED:
            return coll
        # The SAME wrapper every time, not a fresh one per access: the driver
        # hands back the same collection object, and code (tests included)
        # patches methods on it expecting that to stick.
        box = self.__dict__.setdefault("_fidclic_memos", {})
        memo = box.get(name)
        if memo is None or memo._real is not coll:
            memo = Memo(coll, name)
            box[name] = memo
        return memo

    def getattr_(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getitem(self, name)

    cls.__getitem__ = getitem
    cls.__getattr__ = getattr_
    cls._fidclic_doc_cache = True


class Middleware:
    """Pure ASGI: one memo per HTTP request, dropped when it ends."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        token = begin()
        try:
            await self.app(scope, receive, send)
        finally:
            end(token)
