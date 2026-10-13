"""
Where a request's time goes (2026-10-13: « platform load hone mein bahut
time lag rha hai »). Every /api answer carries a Server-Timing header —
the browser's Network tab shows it under « Timing » — with the whole time,
the time spent in MongoDB and the number of database calls:

    Server-Timing: app;dur=1712, db;dur=1650;desc="14 appels"

The database time is read with pymongo's command monitoring (registered
before the client is made); the request's tally lives in a contextvar, a
dict shared with the worker thread FastAPI runs a sync endpoint in.
"""
from __future__ import annotations

import contextvars
import time
from typing import Any, Dict, Optional

_REQ: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("fidclic_timing", default=None)


_COLL: Dict[int, str] = {}     # request_id → "find media" (from the started event)


class _Listener:
    """pymongo.monitoring.CommandListener, without importing it at module level."""

    def started(self, event):  # noqa: D401
        try:
            name = event.command_name
            coll = event.command.get(name) if hasattr(event, "command") else ""
            if len(_COLL) > 2000:
                _COLL.clear()
            _COLL[event.request_id] = f"{name} {coll if isinstance(coll, str) else ''}".strip()
        except Exception:
            pass

    def succeeded(self, event):
        self._add(event)

    def failed(self, event):
        self._add(event)

    @staticmethod
    def _add(event):
        what = _COLL.pop(getattr(event, "request_id", None), "") if _COLL else ""
        tally = _REQ.get()
        if tally is not None:
            us = int(getattr(event, "duration_micros", 0) or 0)
            tally["db_us"] += us
            tally["db_n"] += 1
            if us > tally.get("slow_us", 0):         # the slowest call, named in the header
                tally["slow_us"], tally["slow"] = us, what


def note(key: str, value: Any = 1) -> None:
    """Count something for this request's header (e.g. where pictures came from)."""
    tally = _REQ.get()
    if tally is not None:
        if isinstance(value, str):
            tally.setdefault("notes", {})[key] = value[:60]
        else:
            tally.setdefault("notes", {})[key] = tally.get("notes", {}).get(key, 0) + value


def install_listener() -> None:
    """Before the MongoClient is created."""
    try:
        from pymongo import monitoring

        class L(_Listener, monitoring.CommandListener):
            pass
        monitoring.register(L())
    except Exception as exc:  # noqa: BLE001 — timing must never stop the app
        print(f"server timing: no db monitoring ({exc})")


def _clean(v: str) -> str:
    return "".join(c for c in str(v) if c.isalnum() or c in " _-./:")[:60]


class TimingMiddleware:
    """Pure ASGI: adds Server-Timing to /api responses."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not str(scope.get("path", "")).startswith("/api/"):
            return await self.app(scope, receive, send)
        tally = {"db_us": 0, "db_n": 0}
        tok = _REQ.set(tally)
        t0 = time.perf_counter()

        async def send_wrapped(message):
            if message.get("type") == "http.response.start":
                total = (time.perf_counter() - t0) * 1000
                value = (f'app;dur={total:.0f}, db;dur={tally["db_us"] / 1000:.0f};'
                         f'desc="{tally["db_n"]} appels"')
                if tally.get("slow"):
                    value += f', slow;dur={tally["slow_us"] / 1000:.0f};desc="{_clean(tally["slow"])}"'
                for k, v in (tally.get("notes") or {}).items():
                    value += f', {_clean(k)};desc="{_clean(str(v))}"'
                headers = list(message.get("headers") or [])
                headers.append((b"server-timing", value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)
        try:
            return await self.app(scope, receive, send_wrapped)
        finally:
            _REQ.reset(tok)
