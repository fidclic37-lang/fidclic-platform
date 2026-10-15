"""
OCR — read a supplier receipt/invoice image into structured accounting fields.

WHY THIS EXISTS (research: Chapter 4, the "saisie" time-sink)
    A collaborateur retypes supplier invoices into the ledger by hand — Dext/
    Pennylane charge per document for exactly this. If FidClic reads the photo,
    the human only *checks* the numbers instead of *typing* them. This is the
    foundation the Saisie agent stands on: OCR proposes, a human validates.

HOW IT WORKS
    A vision LLM (Groq by default, NVIDIA NIM as fallback — both keys already in
    env) receives the image and a strict JSON schema, and returns the fields.
    We never trust it blindly: every extraction carries a `confidence` 0..1.
    High confidence can flow to a draft entry automatically; low confidence is
    flagged needs_review. The human is always the last gate (see agent_saisie).

CONFIG
    OCR_PROVIDER   "anthropic" | "groq" | "nvidia".
                   Defaults to "anthropic" when ANTHROPIC_API_KEY is set,
                   else "groq". Reading an invoice correctly is the whole
                   value of this module — a wrong total_ttc costs the
                   collaborateur more time than typing it would have — so
                   the best available model should win by default.
    ANTHROPIC_API_KEY / GROQ_API_KEY / NVIDIA_API_KEY
    OCR_MODEL      optional model override

SEAM
    _force_extract = callable(image_b64, mime) -> dict   lets tests exercise the
    whole pipeline (feature endpoint → received-invoice draft → Saisie entry)
    without a network call or an API key.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

logger = logging.getLogger("fidelitour.ocr")

# Test seam — see module docstring.
_force_extract = None

_ENDPOINTS = {
    "anthropic": ("https://api.anthropic.com/v1/messages",
                  "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions",
             "GROQ_API_KEY", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "nvidia": ("https://integrate.api.nvidia.com/v1/chat/completions",
               "NVIDIA_API_KEY", "meta/llama-4-scout-17b-16e-instruct"),
}

ANTHROPIC_VERSION = "2023-06-01"
# The only media types the Anthropic image block accepts.
_ANTHROPIC_MEDIA = ("image/jpeg", "image/png", "image/gif", "image/webp")

_PROMPT = (
    "You are an accounting OCR. Read this French supplier invoice/receipt image "
    "and return ONLY a JSON object, no prose, with these keys: "
    "supplier_name (string), supplier_siren (9 digits or empty), "
    "invoice_number (string), date (YYYY-MM-DD or empty), "
    "total_ht (number), total_vat (number), total_ttc (number), "
    "vat_rate (number, the dominant rate e.g. 20), "
    "currency (ISO e.g. EUR), "
    "category_guess (one of: fournitures, services, restauration, transport, "
    "telecom, loyer, honoraires, autre), "
    "confidence (number 0..1 = how sure you are the amounts are correct). "
    "If a value is unreadable use empty string or 0 and lower the confidence."
)


def _provider_name() -> str:
    explicit = os.environ.get("OCR_PROVIDER", "").strip().lower()
    if explicit in _ENDPOINTS:
        return explicit
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else "groq"


def _provider() -> tuple:
    return _ENDPOINTS[_provider_name()]


def is_configured() -> bool:
    _url, key_env, _model = _provider()
    return bool(os.environ.get(key_env, "").strip())


def _coerce_num(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    if not x:
        return 0.0
    s = re.sub(r"[^\d,.\-]", "", str(x)).replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _normalize(raw: dict) -> dict:
    """Coerce the model's JSON into a stable, self-consistent record."""
    ht = _coerce_num(raw.get("total_ht"))
    vat = _coerce_num(raw.get("total_vat"))
    ttc = _coerce_num(raw.get("total_ttc"))
    rate = _coerce_num(raw.get("vat_rate")) or 20.0
    # backfill any missing total from the other two (invoices must reconcile)
    if ttc and not ht and not vat:
        ht = round(ttc / (1 + rate / 100.0), 2)
        vat = round(ttc - ht, 2)
    elif ht and not ttc:
        vat = vat or round(ht * rate / 100.0, 2)
        ttc = round(ht + vat, 2)
    siren = "".join(ch for ch in str(raw.get("supplier_siren") or "") if ch.isdigit())
    conf = _coerce_num(raw.get("confidence"))
    if conf > 1:
        conf = conf / 100.0
    # if the arithmetic doesn't reconcile, trust it less
    if ht and ttc and abs((ht + vat) - ttc) > max(0.02, ttc * 0.02):
        conf = min(conf, 0.5)
    return {
        "ok": True,
        "supplier_name": (raw.get("supplier_name") or "").strip() or "Fournisseur inconnu",
        "supplier_siren": siren if len(siren) == 9 else "",
        "invoice_number": (raw.get("invoice_number") or "").strip(),
        "date": (str(raw.get("date") or "")[:10]),
        "total_ht": round(ht, 2), "total_vat": round(vat, 2), "total_ttc": round(ttc, 2),
        "vat_rate": rate,
        "currency": (raw.get("currency") or "EUR").strip().upper()[:3] or "EUR",
        "category_guess": (raw.get("category_guess") or "autre").strip().lower(),
        "confidence": round(max(0.0, min(1.0, conf)), 2),
    }


def _parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (it may wrap it in prose)."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def _call_vision(image_b64: str, mime: str) -> dict:
    from services.llm import anthropic_extras
    from services.vision_image import for_vision
    image_b64, mime = for_vision(image_b64, mime)   # HEIC, huge photos → a JPEG every provider reads
    url, key_env, default_model = _provider()
    key = os.environ.get(key_env, "").strip()
    model = os.environ.get("OCR_MODEL", "").strip() or default_model

    # Anthropic: own auth header, own version header, image as a base64 block
    # rather than a data: URL, and the answer in a content-block array.
    if _provider_name() == "anthropic":
        media = (mime or "image/jpeg").lower()
        if media not in _ANTHROPIC_MEDIA:
            media = "image/jpeg"
        body = {
            "model": model, "max_tokens": 700, **anthropic_extras(model),   # no temperature: Claude 4.7+ refuses it
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media, "data": image_b64}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"x-api-key": key,
                     "anthropic-version": ANTHROPIC_VERSION,
                     "content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
            data = json.loads(r.read().decode() or "{}")
        blocks = data.get("content") or []
        content = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return _parse_json(content)

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 700,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }],
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as r:  # noqa: S310
        data = json.loads(r.read().decode() or "{}")
    content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
    return _parse_json(content)


def extract_invoice(image_b64: str, mime: str = "image/jpeg",
                    kind: str = "achat") -> dict:
    """Read one image into structured fields. Never raises.

    kind: "achat" (supplier invoice — default) or "vente" (an invoice the
    business ITSELF issued, photographed to backfill history). For a vente
    the counterparty we extract is the CUSTOMER, and we ask the model for it;
    the normalized field name stays `supplier_name` (generic counterparty)
    so the pipeline and the test seam stay unchanged.

    Returns a normalized record with `ok` and `confidence`, or
    {ok: False, no_op: True} when no provider is configured.
    """
    global _PROMPT
    prompt_backup = _PROMPT
    if kind == "vente":
        # swap the counterparty wording for this call only (restored in finally)
        _PROMPT = _PROMPT.replace(
            "supplier_name (string), supplier_siren (9 digits or empty)",
            "supplier_name (string — here: the CUSTOMER the invoice is billed to), "
            "supplier_siren (customer SIREN, 9 digits or empty)")
    try:
        if _force_extract is not None:
            return _normalize(_force_extract(image_b64, mime))

        if not is_configured():
            return {"ok": False, "no_op": True, "confidence": 0.0,
                    "error": "ocr_not_configured"}
        if not image_b64:
            return {"ok": False, "confidence": 0.0, "error": "empty_image"}

        try:
            raw = _call_vision(image_b64, mime)
            if not raw:
                return {"ok": False, "confidence": 0.0, "error": "no_json_from_model"}
            return _normalize(raw)
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR extraction failed: %s", exc)
            return {"ok": False, "confidence": 0.0, "error": str(exc)[:200]}
    finally:
        _PROMPT = prompt_backup
