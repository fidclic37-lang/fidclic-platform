"""
Transactional email via Brevo (HTTP API, no SDK dependency).

WHY BREVO
    French provider (CNIL-friendly story for a French SMB product), free tier
    300 emails/day — plenty for relances at this stage.

KEY RESOLUTION
    env BREVO_API_KEY only (set in the Vercel project env — never in the
    repo; GitHub push protection rightly blocks it, including base64'd).
    Without it → disabled mode: send() returns {"sent": False} and the
    caller carries on. Email must never be able to break business logic.

TESTABILITY
    Tests monkeypatch `_post` (single network seam) — no network, no key.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional

SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "akshanshshukla963@gmail.com")
SENDER_NAME = os.getenv("BREVO_SENDER_NAME", "FidClic")


def _api_key() -> Optional[str]:
    return os.getenv("BREVO_API_KEY") or None


def _post(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    """The single network seam (tests replace this)."""
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={"api-key": key, "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "{}")


def send(to: str, subject: str, html: str,
         text: Optional[str] = None,
         to_name: Optional[str] = None,
         reply_to: Optional[str] = None) -> Dict[str, Any]:
    """Send one email. Never raises — a failed relance is a log line and a
    retry on the next agent run, not a crashed request."""
    key = _api_key()
    if not key:
        return {"sent": False, "reason": "mailer_disabled"}
    payload = {
        "sender": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "to": [{"email": to, **({"name": to_name} if to_name else {})}],
        "subject": subject,
        "htmlContent": html,
        **({"textContent": text} if text else {}),
        **({"replyTo": {"email": reply_to}} if reply_to else {}),
    }
    try:
        res = _post(payload, key)
        return {"sent": True, "message_id": res.get("messageId")}
    except Exception as e:                                   # noqa: BLE001
        return {"sent": False, "reason": str(e)[:200]}


BATCH_SIZE = 500     # Brevo takes up to 1 000 versions per call; stay well under


def ready() -> bool:
    """Whether emails can go out at all (BREVO_API_KEY set)."""
    return bool(_api_key())


def send_batch(messages: List[Dict[str, Any]], sender_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Many personal emails in a few calls (Brevo « messageVersions »).

    `messages`: [{"to", "to_name"?, "subject", "html", "text"?}]. Returns one
    result per message, in order: {"sent": bool, "reason"?}. Never raises —
    a chunk that fails marks its own messages failed and the rest carry on.
    One call per BATCH_SIZE recipients keeps an import of a thousand clients
    inside a single request's time."""
    key = _api_key()
    if not key:
        return [{"sent": False, "reason": "mailer_disabled"} for _ in messages]
    out: List[Dict[str, Any]] = []
    for i in range(0, len(messages), BATCH_SIZE):
        chunk = messages[i:i + BATCH_SIZE]
        first = chunk[0]
        payload = {
            "sender": {"email": SENDER_EMAIL, "name": (sender_name or SENDER_NAME)[:70]},
            "subject": first["subject"],
            "htmlContent": first["html"],
            "messageVersions": [{
                "to": [{"email": m["to"], **({"name": m["to_name"]} if m.get("to_name") else {})}],
                "subject": m["subject"],
                "htmlContent": m["html"],
                **({"textContent": m["text"]} if m.get("text") else {}),
            } for m in chunk],
        }
        try:
            _post(payload, key)
            out.extend({"sent": True} for _ in chunk)
        except Exception as e:                               # noqa: BLE001
            out.extend({"sent": False, "reason": str(e)[:200]} for _ in chunk)
    return out
