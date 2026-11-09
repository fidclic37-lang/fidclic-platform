"""
Numbers that are not numbers (#454's pentest, user 2026-11-09).

WHY
    Python's JSON reader turns « 1e309 » into infinity and accepts the
    literals NaN, Infinity and -Infinity. A route with a limit (amount ≤
    100 000) then refused it — and the refusal itself crashed while being
    written, because JSON cannot say « infinity »: a 500 instead of a 422. A
    route without a limit let it through to the code (int(∞) → OverflowError,
    a stored ∞ that breaks every later page that reads it).

WHAT
    Middleware   a JSON body (up to 2 MB) holding a non-finite number is
                 refused with a 422 before any route reads it — on every route.
    Handler      a validation error is always written: a non-finite value in
                 it is spelled as text, so the answer is a 422, never a 500
                 (query strings such as ?x=inf reach pydantic as a float too).
"""
from __future__ import annotations

import json
import math
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

LIMIT_BYTES = 2_000_000
MESSAGE = "Nombre invalide : un nombre infini ou NaN (non fini) n'est pas accepté."
WRITES = (b"POST", b"PUT", b"PATCH", b"DELETE")


class _NotFinite(ValueError):
    pass


def _float(text: str) -> float:
    v = float(text)
    if not math.isfinite(v):
        raise _NotFinite(text)
    return v


def _constant(text: str) -> float:
    raise _NotFinite(text)


def has_non_finite(body: bytes) -> bool:
    """True when the JSON holds 1e309, NaN, Infinity… anywhere. A body that
    is not JSON at all is the route's to refuse."""
    if not body:
        return False
    try:
        json.loads(body, parse_float=_float, parse_constant=_constant)
    except _NotFinite:
        return True
    except (ValueError, RecursionError, UnicodeDecodeError):
        return False
    return False


def finite(value: Any) -> Any:
    """The same value with every non-finite float spelled as text."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    return value


def _refusal() -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": [
        {"type": "finite_number", "loc": ["body"], "msg": MESSAGE, "input": None}]})


class Middleware:
    """Pure ASGI: reads a JSON write's body once, refuses it or hands the
    same bytes on to the route."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method", "").encode() not in WRITES:
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        if b"json" not in (headers.get(b"content-type") or b"").lower():
            return await self.app(scope, receive, send)
        chunks, size, more, gone = [], 0, True, False
        while more:
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                gone = True
                break
            part = msg.get("body", b"") or b""
            chunks.append(part)
            size += len(part)
            more = bool(msg.get("more_body"))
        body = b"".join(chunks)
        if not gone and size <= LIMIT_BYTES and has_non_finite(body):
            return await _refusal()(scope, receive, send)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        if gone:
            async def replay():               # noqa: F811 — the client left: say so to the route
                return {"type": "http.disconnect"}
        return await self.app(scope, replay, send)


async def validation_error(request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's own 422, with any non-finite value written as text."""
    return JSONResponse(status_code=422, content={"detail": finite(jsonable_encoder(exc.errors()))})


def install(app) -> None:
    app.add_middleware(Middleware)
    app.add_exception_handler(RequestValidationError, validation_error)
