"""
AI meter + billing guardrails (user, 2026-11-01).

Every model call — services/llm, services/ocr, the menu photo and the
campaign recap in server.py — goes through `call()`: one gate where it is

  • weighed before it goes: the platform's daily cap (20 €, all shops), the
    shop's monthly AI budget (Starter 5 / Pro 10 / Pro AI 25 €, or what the
    super admin set — enforced the same way), a sudden spike, the user's
    speed, the request's number of calls, the input's size;
  • paid for in advance: its worst cost (its input, its max_tokens) is
    reserved atomically on the shop's month and the platform's day, so
    twenty calls at once can never pass a limit together; the real cost
    replaces the reservation when the answer comes back;
  • written down: shop, user, feature, provider, model, tokens (in, out,
    cache), time, €, status. Never the prompt or the answer.

A refused call answers None: every caller already falls back to its
template. The owner sees « Limite IA du mois atteinte » (the dashboard
banner, « Rédiger avec l'IA »); the super admins get one alert and one email
per threshold (80 %, 100 %, global cap, spike). Super admin › FIDCLIC AI ›
Coûts IA reads all of it and sets the limits.

Days and months are Paris days and months. Prices are $ per million tokens
(Anthropic's 2026-10 list; Groq / NVIDIA editable), turned into € at
`usd_eur`; a model missing from the list is priced like the dearest row,
never as free.

SEAMS  _now() and _send(url, headers, body, timeout) -> (status, json).
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import math
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from auth import TokenData
from features.platform_access import require_admin

router = APIRouter(tags=["ai-meter"])
_db = None
PARIS = ZoneInfo("Europe/Paris")
_UNSET = object()

DEFAULTS: Dict[str, Any] = {
    "plan_budgets": {"silver": 5.0, "gold": 10.0, "vip": 25.0, "franchise": 25.0},
    "default_budget": 5.0,          # a plan not in the list
    "global_day_eur": 20.0,         # 0 = every AI call stopped (the emergency switch)
    "usd_eur": 0.92,
    "user_per_min": 30,             # model calls per user per minute
    "request_calls": 12,            # model calls in one HTTP request (a tool loop stops)
    "input_chars": 60000,           # ≈ 15 000 tokens of text
    "spike_factor": 5.0,            # today vs the 14 days before
    "spike_min_share": 0.2,         # …and at least this share of the month's budget
    "prices": {},                   # overrides: {model: [in, out, cache_read, cache_write]} $/M
}

# $ per million tokens: input, output, cache read, cache write (1,25 × input).
PRICES: Dict[str, Tuple[float, float, float, float]] = {
    "claude-fable-5": (10.0, 50.0, 0.25, 12.5),
    "claude-mythos-5": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5),
    "claude-sonnet-4": (3.0, 15.0, 0.30, 3.75),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-haiku-4": (1.0, 5.0, 0.10, 1.25),
    "llama-3.3-70b": (0.59, 0.79, 0.0, 0.59),
    "meta-llama/llama-4-scout": (0.11, 0.34, 0.0, 0.11),
    "meta-llama/llama-4-maverick": (0.20, 0.60, 0.0, 0.20),
    "meta/llama": (0.59, 0.79, 0.0, 0.59),
    "gemini-": (0.10, 0.40, 0.0, 0.10),
}
OUT_CAPS = {"menu_import": 4000, "invoice_ocr": 1000}
OUT_CAP = 1500
CACHE_FEATURES = {"copilot"}         # several rounds on the same long rules: Anthropic's cache pays
CACHE_MIN_CHARS = 8000
IMAGE_TOKENS = 1600                  # what one photo is reckoned at before the answer says
ALERT_KINDS = {"ai_budget_80", "ai_budget_100", "ai_global", "ai_spike"}
LIMIT_MESSAGE = "Limite IA du mois atteinte. FidClic IA reprend le 1er du mois prochain."
PAUSE_MESSAGE = "FidClic IA est en pause pour aujourd'hui. Réessayez demain."
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]

_ctx: contextvars.ContextVar = contextvars.ContextVar("ai_meter_ctx", default=None)


def init(db):
    global _db
    _db = db
    try:
        db.ai_calls.create_index([("at", -1)])
        db.ai_calls.create_index([("user", 1), ("at", -1)])
        db.ai_calls.create_index([("tenant_id", 1), ("at", -1)])
        db.ai_calls.create_index("at", name="ai_calls_ttl", expireAfterSeconds=400 * 86400)
        db.ai_cache.create_index("exp", expireAfterSeconds=0)
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _send(url: str, headers: Dict[str, str], body: Dict[str, Any], timeout: float) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
            return getattr(r, "status", 200), json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}


# ---------------------------------------------------------------------------
# settings, keys, prices

def settings() -> Dict[str, Any]:
    s = {**DEFAULTS, "plan_budgets": dict(DEFAULTS["plan_budgets"])}
    if _db is not None:
        doc = _db.platform_settings.find_one({"key": "ai_meter"}, {"_id": 0}) or {}
        for k in DEFAULTS:
            if k in doc and doc[k] is not None:
                s[k] = {**s[k], **doc[k]} if isinstance(DEFAULTS[k], dict) else doc[k]
    return s


def _paris(at: Optional[datetime] = None) -> datetime:
    return (at or _now()).astimezone(PARIS)


def key_month(tid: Optional[str], at: Optional[datetime] = None) -> str:
    return f"m:{tid or 'all'}:{_paris(at).strftime('%Y-%m')}"


def key_day(tid: Optional[str], at: Optional[datetime] = None) -> str:
    return f"d:{tid or 'all'}:{_paris(at).strftime('%Y-%m-%d')}"


def _price(model: str) -> Tuple[float, float, float, float]:
    over = settings()["prices"] or {}
    m = (model or "").lower()
    if m in over:
        return tuple(float(x) for x in over[m])          # type: ignore[return-value]
    best = max((k for k in PRICES if m.startswith(k)), key=len, default=None)
    if best:
        return PRICES[best]
    if m.endswith(":free"):
        return (0.0, 0.0, 0.0, 0.0)
    return max(PRICES.values(), key=lambda p: p[0] + p[1])   # unknown: the dearest, never free


def cost_eur(provider: str, model: str, u: Dict[str, int]) -> float:
    p_in, p_out, p_cr, p_cw = _price(model)
    usd = (u.get("in", 0) * p_in + u.get("out", 0) * p_out
           + u.get("cache_read", 0) * p_cr + u.get("cache_write", 0) * p_cw) / 1_000_000
    return usd * float(settings()["usd_eur"])


def usage_of(provider: str, data: Dict[str, Any], in_chars: int, out_text: str) -> Dict[str, Any]:
    u = (data or {}).get("usage") or {}
    if "input_tokens" in u or "output_tokens" in u:
        return {"in": int(u.get("input_tokens") or 0), "out": int(u.get("output_tokens") or 0),
                "cache_read": int(u.get("cache_read_input_tokens") or 0),
                "cache_write": int(u.get("cache_creation_input_tokens") or 0), "estimated": False}
    if "prompt_tokens" in u or "completion_tokens" in u:
        cached = int(((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0)
        return {"in": int(u.get("prompt_tokens") or 0) - cached, "out": int(u.get("completion_tokens") or 0),
                "cache_read": cached, "cache_write": 0, "estimated": False}
    return {"in": math.ceil(in_chars / 4), "out": math.ceil(len(out_text or "") / 4),
            "cache_read": 0, "cache_write": 0, "estimated": True}


def out_cap(feature: Optional[str]) -> int:
    return OUT_CAPS.get(feature or "", OUT_CAP)


def limit_for(tid: Optional[str]) -> float:
    if not tid or _db is None:
        return math.inf
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "plan": 1, "ai_budget_eur": 1}) or {}
    if t.get("ai_budget_eur") is not None:
        return float(t["ai_budget_eur"])
    s = settings()
    return float(s["plan_budgets"].get(t.get("plan") or "", s["default_budget"]))


# ---------------------------------------------------------------------------
# who is calling

@contextlib.contextmanager
def scope(tenant_id: Any = _UNSET, feature: Optional[str] = None, user: Any = _UNSET):
    """Name the shop, feature and user of the calls inside (background jobs,
    tests). Inside an HTTP request the token already names them."""
    parent = _ctx.get() or {}
    ctx = dict(parent)
    if tenant_id is not _UNSET:
        ctx["tenant_id"] = tenant_id
    if user is not _UNSET:
        ctx["user"] = user
    if feature:
        ctx["feature"] = feature
    ctx["calls"] = parent.get("calls") or [0]
    tok = _ctx.set(ctx)
    try:
        yield ctx
    finally:
        _ctx.reset(tok)


class Middleware:
    """Pure ASGI: each API request gets its own meter context (the token is
    read only if a model is called)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope_, receive, send):
        if scope_.get("type") == "http" and (scope_.get("path") or "").startswith("/api/"):
            tok = _ctx.set({"asgi": scope_, "calls": [0]})
            try:
                return await self.app(scope_, receive, send)
            finally:
                _ctx.reset(tok)
        return await self.app(scope_, receive, send)


def _who(ctx: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    if "tenant_id" in ctx or "user" in ctx or "asgi" not in ctx:
        return ctx.get("tenant_id"), ctx.get("user")
    if "_resolved" not in ctx:
        tid = email = None
        try:
            import auth
            import jwt
            req = Request(ctx["asgi"])
            h = req.headers.get("authorization") or ""
            token = h[7:] if h.startswith("Bearer ") else req.cookies.get("access_token")
            if token:
                p = jwt.decode(token, auth._secret(), algorithms=[auth.ALGORITHM], options={"verify_exp": False})
                tid, email = p.get("tenant_id"), p.get("sub")
        except Exception:
            pass
        ctx["_resolved"] = (tid, email)
    return ctx["_resolved"]


def blocked_reason() -> Optional[str]:
    """Why the last model call of this request was refused (None: it was not)."""
    return (_ctx.get() or {}).get("last_block")


def limit_message(reason: Optional[str] = None) -> str:
    return LIMIT_MESSAGE if (reason or blocked_reason()) == "budget" else PAUSE_MESSAGE


# ---------------------------------------------------------------------------
# money: reserve, settle, state

def _spent(key: str) -> float:
    return float(((_db.ai_spend.find_one({"_id": key}, {"eur": 1}) or {}).get("eur")) or 0.0)


def _tag(limit: float) -> int:
    return int(round(limit * 100))


def _full(key: str, limit: float) -> bool:
    """At its limit: spent it all, or the last call refused no longer fits in
    what is left (small calls stop a hair under the limit — 4,996 € of 5 €)."""
    doc = _db.ai_spend.find_one({"_id": key}, {"eur": 1, "full": 1}) or {}
    spent = float(doc.get("eur") or 0)
    need = (doc.get("full") or {}).get(str(_tag(limit)))
    return spent >= limit or (need is not None and spent + float(need) > limit)


def _mark_full(key: str, limit: float, est: float) -> None:
    _db.ai_spend.update_one({"_id": key}, {"$set": {f"full.{_tag(limit)}": est}}, upsert=True)


def _take(key: str, est: float, cap: float) -> bool:
    if cap == math.inf:
        _db.ai_spend.update_one({"_id": key}, {"$inc": {"eur": est}}, upsert=True)
        return True
    if est > cap:
        return False
    _db.ai_spend.update_one({"_id": key}, {"$setOnInsert": {"eur": 0.0}}, upsert=True)
    return _db.ai_spend.update_one({"_id": key, "eur": {"$lte": cap - est}}, {"$inc": {"eur": est}}).modified_count == 1


def _add(key: str, eur: float) -> None:
    if eur:
        _db.ai_spend.update_one({"_id": key}, {"$inc": {"eur": eur}}, upsert=True)


def _spike_line(tid: str, limit: float) -> float:
    now = _now()
    days = [key_day(tid, now - timedelta(days=d)) for d in range(1, 15)]
    past = sum(float(r.get("eur") or 0) for r in _db.ai_spend.find({"_id": {"$in": days}}, {"eur": 1}))
    s = settings()
    return max(float(s["spike_factor"]) * past / 14, float(s["spike_min_share"]) * (limit if limit != math.inf else 0))


def _spiking(tid: str, limit: float) -> bool:
    doc = _db.ai_spend.find_one({"_id": key_day(tid)}, {"eur": 1, "released": 1}) or {}
    line = _spike_line(tid, limit)
    return not doc.get("released") and line > 0 and float(doc.get("eur") or 0) >= line


def state(tid: Optional[str]) -> Dict[str, Any]:
    limit = limit_for(tid)
    month = _spent(key_month(tid)) if tid else 0.0
    today = _spent(key_day(tid)) if tid else 0.0
    blocked = None
    if tid and limit != math.inf and _full(key_month(tid), limit):
        blocked = "budget"
    elif tid and _spiking(tid, limit):
        blocked = "spike"
    elif _full(key_day(None), float(settings()["global_day_eur"])):
        blocked = "global"
    return {"month_eur": month, "today_eur": today, "limit_eur": limit if limit != math.inf else None,
            "pct": round(100 * month / limit) if tid and limit not in (0, math.inf) else (100 if tid and limit == 0 else 0),
            "blocked": blocked}


def _reserve(tid: Optional[str], est: float) -> Optional[str]:
    g = key_day(None)
    cap = float(settings()["global_day_eur"])
    if tid:
        limit = limit_for(tid)
        if not _take(key_month(tid), est, limit):
            _mark_full(key_month(tid), limit, est)
            _alerts_after(tid)
            return "budget"
        if _spiking(tid, limit):
            _add(key_month(tid), -est)
            return "spike"
    if not _take(g, est, cap):
        if tid:
            _add(key_month(tid), -est)
        _mark_full(g, cap, est)
        _alerts_after(None)
        return "global"
    if tid:
        _add(key_day(tid), est)
    return None


def _settle(tid: Optional[str], delta: float) -> None:
    _add(key_day(None), delta)
    if tid:
        _add(key_month(tid), delta)
        _add(key_day(tid), delta)


# ---------------------------------------------------------------------------
# alerts

def _alert_once(key: str, stamp: str, kind: str, text: str, tid: Optional[str]) -> None:
    now = _now()
    _db.ai_spend.update_one({"_id": key}, {"$setOnInsert": {"eur": 0.0}}, upsert=True)
    if _db.ai_spend.update_one({"_id": key, f"alerts.{stamp}": {"$exists": False}},
                               {"$set": {f"alerts.{stamp}": now}}).modified_count != 1:
        return
    _db.platform_alerts.insert_one({"id": uuid.uuid4().hex, "kind": kind, "email": None, "tenant_id": tid,
                                    "text": text, "at": now, "read_by": []})
    try:
        from services import mailer
        for u in _db.users.find({"role": "super_admin", "active": {"$ne": False}}, {"_id": 0, "email": 1}):
            if u.get("email"):
                mailer.send(u["email"], f"FidClic — {text.split(' : ')[0]}",
                            f"<div style='font-family:Arial,sans-serif;font-size:14px;color:#0B1C3F'><p>{text}</p>"
                            f"<p><a href='https://app.fidclic.com/admin/ai/couts'>Voir Coûts IA</a></p></div>")
    except Exception as exc:                 # noqa: BLE001 — the alert row is written either way
        print(f"ai_meter: alert email failed ({exc})")


def _alerts_after(tid: Optional[str]) -> None:
    s = settings()
    name = None
    if tid:
        limit = limit_for(tid)
        month = _spent(key_month(tid))
        name = ((_db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}).get("name")) or tid
        if limit not in (0, math.inf):
            lim_tag = int(round(limit * 100))
            if month >= 0.8 * limit:
                _alert_once(key_month(tid), f"b80_{lim_tag}", "ai_budget_80",
                            f"Budget IA à 80 % : {name} — {month:.2f} € sur {limit:.2f} € ce mois-ci.", tid)
            if _full(key_month(tid), limit):
                _alert_once(key_month(tid), f"b100_{lim_tag}", "ai_budget_100",
                            f"Budget IA atteint : {name} — {month:.2f} € sur {limit:.2f} €. FidClic IA répond avec les modèles simples.", tid)
        if _spiking(tid, limit):
            _alert_once(key_day(tid), "spike", "ai_spike",
                        f"Pic IA : {name} — {_spent(key_day(tid)):.2f} € aujourd'hui, bien au-dessus de ses jours habituels. FidClic IA est en pause pour lui jusqu'à demain.", tid)
    g = _spent(key_day(None))
    cap = float(s["global_day_eur"])
    if _full(key_day(None), cap):
        _alert_once(key_day(None), f"cap_{int(round(cap * 100))}", "ai_global",
                    f"Plafond IA du jour atteint : {g:.2f} € sur {cap:.2f} €. Toute l'IA est en pause jusqu'à minuit.", None)


# ---------------------------------------------------------------------------
# the gate

def _text_chars(body: Dict[str, Any]) -> Tuple[int, int]:
    chars = images = 0
    sys_ = body.get("system")
    if isinstance(sys_, str):
        chars += len(sys_)
    elif isinstance(sys_, list):
        chars += sum(len(b.get("text") or "") for b in sys_ if isinstance(b, dict))
    for part in (c for x in body.get("contents") or [] for c in (x.get("parts") or [])):
        chars += len(part.get("text") or "")
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, str):
            chars += len(c)
        elif isinstance(c, list):
            for b in c:
                if b.get("type") == "text":
                    chars += len(b.get("text") or "")
                elif b.get("type") in ("image", "image_url"):
                    images += 1
    return chars, images


def _system_chars(body: Dict[str, Any]) -> int:
    s = body.get("system")
    if isinstance(s, str):
        return len(s)
    for m in body.get("messages") or []:
        if m.get("role") == "system" and isinstance(m.get("content"), str):
            return len(m["content"])
    return 0


def _record(tid, user, feature, provider, model, status, reason=None, u=None, eur=0.0, ms=0) -> None:
    u = u or {}
    _db.ai_calls.insert_one({
        "id": uuid.uuid4().hex, "at": _now(), "tenant_id": tid, "user": user, "feature": feature,
        "provider": provider, "model": model, "status": status, "reason": reason,
        "in": int(u.get("in") or 0), "out": int(u.get("out") or 0),
        "cache_read": int(u.get("cache_read") or 0), "cache_write": int(u.get("cache_write") or 0),
        "estimated": bool(u.get("estimated")), "eur": round(float(eur), 6), "ms": int(ms)})


def _block(ctx, tid, user, feature, provider, model, reason) -> Tuple[None, str]:
    ctx["last_block"] = reason
    _record(tid, user, feature, provider, model, "blocked", reason)
    return None, "blocked"


def allow_forced(feature: Optional[str] = None, tenant_id: Any = _UNSET) -> bool:
    """Tests that force the model's answer: no speed limits (the suite makes
    many calls in a second), but a shop at its limit is still refused."""
    if _db is None:
        return True
    ctx = _ctx.get() or {}
    tid = tenant_id if tenant_id is not _UNSET else _who(ctx)[0]
    st = state(tid)
    if st["blocked"]:
        ctx["last_block"] = st["blocked"]
        return False
    return True


def call(provider: str, model: str, url: str, headers: Dict[str, str], body: Dict[str, Any], *,
         feature: Optional[str] = None, tenant_id: Any = _UNSET, timeout: float = 45,
         cache_ttl: int = 0, out_text=None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Send one model request through the gate. (json, None), or (None, error);
    error == "blocked" when a guard refused it (nothing was sent).
    `out_text(json) -> str` reads the answer, for the estimate when the
    provider does not send its usage."""
    if _db is None:
        st, data = _send(url, headers, body, timeout)
        return (data, None) if st < 400 else (None, f"HTTP {st}")
    ctx = _ctx.get()
    if ctx is None:
        ctx = {"calls": [0]}
    tid, user = (tenant_id, _who(ctx)[1]) if tenant_id is not _UNSET else _who(ctx)
    feature = feature or ctx.get("feature") or "autre"
    ctx.pop("last_block", None)
    s = settings()

    chars, images = _text_chars(body)
    if chars > int(s["input_chars"]):
        return _block(ctx, tid, user, feature, provider, model, "too_long")
    if "max_tokens" in body:                       # (Gemini names it otherwise: never add a field it refuses)
        body["max_tokens"] = min(int(body.get("max_tokens") or out_cap(feature)), out_cap(feature))
    out_max = int(body.get("max_tokens") or out_cap(feature))
    if provider == "anthropic" and feature in CACHE_FEATURES and _system_chars(body) >= CACHE_MIN_CHARS:
        body["cache_control"] = {"type": "ephemeral"}

    ckey = None
    if cache_ttl:
        ckey = hashlib.sha256(json.dumps([tid, provider, model, body], sort_keys=True, default=str).encode()).hexdigest()
        hit = _db.ai_cache.find_one({"_id": ckey})
        if hit and hit.get("exp") and _aware(hit["exp"]) > _now():
            _record(tid, user, feature, provider, model, "cached")
            return hit["data"], None

    if ctx["calls"][0] >= int(s["request_calls"]):
        return _block(ctx, tid, user, feature, provider, model, "loop")
    if user and _db.ai_calls.count_documents({"user": user, "at": {"$gte": _now() - timedelta(seconds=60)},
                                               "status": {"$ne": "blocked"}}) >= int(s["user_per_min"]):
        return _block(ctx, tid, user, feature, provider, model, "rate")

    est = cost_eur(provider, model, {"in": math.ceil(chars / 4) + images * IMAGE_TOKENS, "out": out_max})
    reason = _reserve(tid, est)
    if reason:
        return _block(ctx, tid, user, feature, provider, model, reason)
    ctx["calls"][0] += 1

    t0 = time.monotonic()
    try:
        status, data = _send(url, headers, body, timeout)
    except Exception as exc:                 # noqa: BLE001 — a dead provider is an error row, not a crash
        status, data = 0, {"error": str(exc)}
    ms = (time.monotonic() - t0) * 1000
    if status >= 400 or status == 0:
        _settle(tid, -est)
        _record(tid, user, feature, provider, model, "error", f"HTTP {status}", ms=ms)
        return None, f"HTTP {status}: {str(data)[:200]}"

    txt = ""
    try:
        txt = out_text(data) if out_text else ""
    except Exception:
        txt = ""
    u = usage_of(provider, data, chars + images * IMAGE_TOKENS * 4, txt)
    eur = cost_eur(provider, model, u)
    _settle(tid, eur - est)
    _record(tid, user, feature, provider, model, "ok", u=u, eur=eur, ms=ms)
    if ckey:
        _db.ai_cache.update_one({"_id": ckey}, {"$set": {"data": data, "exp": _now() + timedelta(seconds=cache_ttl)}}, upsert=True)
    try:
        _alerts_after(tid)
    except Exception as exc:                 # noqa: BLE001
        print(f"ai_meter: alerts failed ({exc})")
    return data, None


def _aware(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# the owner's banner

def owner_alert(tid: Optional[str]) -> Optional[Dict[str, Any]]:
    if not tid or _db is None:
        return None
    st = state(tid)
    if st["blocked"] != "budget":
        return None
    nxt = (_paris().replace(day=1) + timedelta(days=32)).replace(day=1)
    return {"key": "ai_budget", "what": "FidClic IA", "pct": 100, "upgrade": None,
            "message": f"Limite IA du mois atteinte : FidClic IA répond avec des réponses simplifiées jusqu'au 1er {MONTHS[nxt.month - 1]}."}


# ---------------------------------------------------------------------------
# Super admin › FIDCLIC AI › Coûts IA

def _round(v: float) -> float:
    return round(float(v or 0), 2)


@router.get("/api/admin/ai/costs")
def costs(token_data: TokenData = Depends(require_admin("ai"))):
    import server as core
    s = settings()
    now = _now()
    month_start = _paris(now).replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    day_start = _paris(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    days = [now - timedelta(days=d) for d in range(29, -1, -1)]
    day_rows = {r["_id"]: r for r in _db.ai_spend.find({"_id": {"$in": [key_day(None, d) for d in days]}})}
    by_day = [{"day": _paris(d).strftime("%Y-%m-%d"), "eur": _round(day_rows.get(key_day(None, d), {}).get("eur"))} for d in days]

    feats: Dict[str, Dict[str, Any]] = {}
    calls_today = blocked_today = 0
    for r in _db.ai_calls.find({"at": {"$gte": month_start}}, {"_id": 0, "feature": 1, "eur": 1, "status": 1, "at": 1}):
        f = feats.setdefault(r.get("feature") or "autre", {"feature": r.get("feature") or "autre", "eur": 0.0, "calls": 0, "blocked": 0})
        f["eur"] += float(r.get("eur") or 0)
        f["calls"] += 1
        f["blocked"] += r.get("status") == "blocked"
        if _aware(r["at"]) >= day_start:
            calls_today += 1
            blocked_today += r.get("status") == "blocked"
    by_feature = sorted(({**f, "eur": _round(f["eur"])} for f in feats.values()), key=lambda f: -f["eur"])

    shops = []
    for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "name": 1, "plan": 1, "ai_budget_eur": 1}):
        st = state(t["id"])
        price = float(core.features_for(t).get("price") or 0)
        month = st["month_eur"]
        shops.append({"tenant_id": t["id"], "name": t.get("name") or t["id"], "plan": t.get("plan"),
                      "month_eur": _round(month), "today_eur": _round(st["today_eur"]),
                      "limit_eur": st["limit_eur"], "custom_limit": t.get("ai_budget_eur") is not None,
                      "pct": st["pct"], "state": st["blocked"] or ("near" if st["pct"] >= 80 else "ok"),
                      "plan_price": price, "margin_pct": round(100 * (price - month) / price) if price else None})
    shops.sort(key=lambda x: -x["month_eur"])
    today = _spent(key_day(None))
    paused = _full(key_day(None), float(s["global_day_eur"]))
    alerts = list(_db.platform_alerts.find({"kind": {"$in": sorted(ALERT_KINDS)}}, {"_id": 0}).sort("at", -1).limit(20))
    return {"summary": {"today_eur": _round(today), "month_eur": _round(sum(f["eur"] for f in feats.values())),
                        "global_day_eur": float(s["global_day_eur"]), "paused": paused,
                        "calls_today": calls_today, "blocked_today": blocked_today},
            "by_day": by_day, "by_feature": by_feature, "shops": shops, "alerts": alerts,
            "settings": {k: s[k] for k in ("plan_budgets", "global_day_eur", "usd_eur", "user_per_min", "request_calls", "input_chars")}}


class ShopBudgetIn(BaseModel):
    budget_eur: Optional[float] = Field(None, ge=0, le=1000)


class SettingsIn(BaseModel):
    plan_budgets: Optional[Dict[str, float]] = None
    global_day_eur: Optional[float] = Field(None, ge=0, le=1000)
    usd_eur: Optional[float] = Field(None, ge=0.5, le=2)
    user_per_min: Optional[int] = Field(None, ge=1, le=600)
    request_calls: Optional[int] = Field(None, ge=1, le=50)
    input_chars: Optional[int] = Field(None, ge=1000, le=400000)

    @field_validator("plan_budgets")
    @classmethod
    def _budgets(cls, v):
        if v is None:
            return v
        for k, x in v.items():
            if k not in ("silver", "gold", "vip", "franchise") or not 0 <= float(x) <= 1000:
                raise ValueError("budget de plan entre 0 et 1000 €")
        return v


def _audit(action: str, token_data: TokenData, request: Request, target: Optional[str], meta: Dict[str, Any]) -> None:
    try:
        import server as core
        core.log_audit(action, actor=token_data.email, actor_type="admin", target=target, request=request, meta=meta)
    except Exception:
        pass


@router.put("/api/admin/ai/costs/shops/{tenant_id}")
def set_shop_budget(tenant_id: str, body: ShopBudgetIn, request: Request,
                    token_data: TokenData = Depends(require_admin("ai"))):
    if not _db.tenants.find_one({"id": tenant_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    if body.budget_eur is None:
        _db.tenants.update_one({"id": tenant_id}, {"$unset": {"ai_budget_eur": ""}})
    else:
        _db.tenants.update_one({"id": tenant_id}, {"$set": {"ai_budget_eur": float(body.budget_eur)}})
    _audit("ai_meter.shop_budget", token_data, request, tenant_id, {"budget_eur": body.budget_eur})
    return {"ok": True, "limit_eur": limit_for(tenant_id)}


@router.post("/api/admin/ai/costs/shops/{tenant_id}/release")
def release_spike(tenant_id: str, request: Request, token_data: TokenData = Depends(require_admin("ai"))):
    if not _db.tenants.find_one({"id": tenant_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    _db.ai_spend.update_one({"_id": key_day(tenant_id)}, {"$set": {"released": True}}, upsert=True)
    _audit("ai_meter.release", token_data, request, tenant_id, {"day": key_day(tenant_id)})
    return {"ok": True}


@router.put("/api/admin/ai/costs/settings")
def set_settings(body: SettingsIn, request: Request, token_data: TokenData = Depends(require_admin("ai"))):
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    if "plan_budgets" in upd:
        upd["plan_budgets"] = {**settings()["plan_budgets"], **{k: float(x) for k, x in upd["plan_budgets"].items()}}
    if upd:
        _db.platform_settings.update_one({"key": "ai_meter"}, {"$set": {"key": "ai_meter", **upd}}, upsert=True)
    _audit("ai_meter.settings", token_data, request, None, upd)
    return {"ok": True, "settings": settings()}
