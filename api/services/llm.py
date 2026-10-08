"""
LLM text helper — one thin function to turn a prompt into text.

Used by Le Conseiller (advisory phrasing) and any feature that wants a natural
French sentence over deterministic facts. Deliberately tiny: detection logic
stays rule-based and testable; the LLM only *phrases* what the rules found, so a
missing key or a bad model reply degrades to the caller's template, never a crash.

CONFIG
    LLM_PROVIDER   "anthropic" | "groq" | "nvidia".
                   Defaults to "anthropic" when ANTHROPIC_API_KEY is set,
                   otherwise "groq" — so dropping the key in is enough to put
                   every agent on Claude without touching another variable.
    ANTHROPIC_API_KEY / GROQ_API_KEY / NVIDIA_API_KEY
    LLM_MODEL      optional override (the first provider's model)
    A provider that fails hands over to the next one with a key, in the
    order groq → nvidia → anthropic (after the chosen one).

SEAM
    _force_complete = callable(system, user) -> str   for deterministic tests.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Optional

logger = logging.getLogger("fidelitour.llm")

_force_complete = None

_ENDPOINTS = {
    "anthropic": ("https://api.anthropic.com/v1/messages",
                  "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions",
             "GROQ_API_KEY", "llama-3.3-70b-versatile"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions",
               "NVIDIA_API_KEY", "meta/llama-3.3-70b-instruct"),
}

ANTHROPIC_VERSION = "2023-06-01"


def _provider_name() -> str:
    explicit = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if explicit in _ENDPOINTS:
        return explicit
    # No explicit choice: prefer Claude when its key is present, else Groq.
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else "groq"


def _provider() -> tuple:
    return _ENDPOINTS[_provider_name()]


# When the first provider fails (no key, quota, timeout), the next one with a
# key answers (QA F05, 2026-10-08: Groq failed and FidClic IA fell back to a
# canned reply although an NVIDIA key was there).
FALLBACK_ORDER = ("groq", "nvidia", "anthropic")


def _chain() -> list:
    first = _provider_name()
    return [first] + [p for p in FALLBACK_ORDER if p != first]


def _has_key(name: str) -> bool:
    return bool(os.environ.get(_ENDPOINTS[name][1], "").strip())


def is_configured() -> bool:
    """Any provider with a key can answer."""
    return any(_has_key(p) for p in _ENDPOINTS)


def complete(system: str, user: str, *, max_tokens: int = 400,
             temperature: float = 0.4) -> Optional[str]:
    """Return the model's text, or None if no provider answered (caller falls back)."""
    if _force_complete is not None:
        return _force_complete(system, user)
    for i, name in enumerate(_chain()):
        if not _has_key(name):
            continue
        default = _ENDPOINTS[name][2]
        chosen = _model_for(name) if i == 0 else default
        for model in dict.fromkeys((chosen, default)):     # the chosen model, then the default once
            txt = _call(name, model, system, user, max_tokens, temperature)
            if txt:
                return txt
            logger.warning("LLM %s / %s gave no answer", name, model)
    return None


def _model_for(name: str) -> str:
    """LLM_MODEL, when it belongs to this provider — a Groq model name left in
    LLM_MODEL must not be sent to Claude (and the other way round)."""
    m = os.environ.get("LLM_MODEL", "").strip()
    if not m:
        return _ENDPOINTS[name][2]
    is_claude = m.lower().startswith("claude")
    return m if (name == "anthropic") == is_claude else _ENDPOINTS[name][2]


def _call(name: str, model: str, system: str, user: str, max_tokens: int,
          temperature: float) -> Optional[str]:
    url, key_env, _default = _ENDPOINTS[name]
    key = os.environ.get(key_env, "").strip()

    # Anthropic speaks its own dialect: x-api-key instead of a bearer token, a
    # mandatory version header, `system` hoisted out of the message list, and a
    # content-block array coming back. Same contract out (text or None), so
    # every caller is unaffected.
    if name == "anthropic":
        body = {
            "model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": [{"role": "user", "content": user}],
        }
        # Only send `system` when there is one — the API rejects an empty
        # string, and several callers pass "" when the prompt needs no framing.
        if (system or "").strip():
            body["system"] = system
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"x-api-key": key,
                         "anthropic-version": ANTHROPIC_VERSION,
                         "content-type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=45) as r:  # noqa: S310
                data = json.loads(r.read().decode() or "{}")
            blocks = data.get("content") or []
            txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return (txt or "").strip() or None
        except Exception as exc:  # noqa: BLE001
            logger.exception("Anthropic completion failed: %s", exc)
            return None

    payload = {
        "model": model, "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            data = json.loads(r.read().decode() or "{}")
        txt = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content")
        return (txt or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM completion failed (%s): %s", name, exc)
        return None
