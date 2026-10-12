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


class _Listener:
    """pymongo.monitoring.CommandListener, without importing it at module level."""

    def started(self, event):  # noqa: D401
        pass

    def succeeded(self, event):
        self._add(event)

    def failed(self, event):
        self._add(event)

    @staticmethod
    def _add(event):
        tally = _REQ.get()
        if tally is not None:
            tally["db_us"] += int(getattr(event, "duration_micros", 0) or 0)
            tally["db_n"] += 1


def install_listener() -> None:
    """Before the MongoClient is created."""
    try:
        from pymongo import monitoring

        class L(_Listener, monitoring.CommandListener):
            pass
        monitoring.register(L())
    except Exception as exc:  # noqa: BLE001 — timing must never stop the app
        print(f"server timing: no db monitoring ({exc})")


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
                headers = list(message.get("headers") or [])
                headers.append((b"server-timing", value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)
        try:
            return await self.app(scope, receive, send_wrapped)
        finally:
            _REQ.reset(tok)
