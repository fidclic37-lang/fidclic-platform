"""
Web Push wrapper using VAPID protocol — free, no third-party SaaS needed.

Reads two env vars on Vercel:
    VAPID_PRIVATE_KEY   (PEM-encoded EC private key, base64-stripped)
    VAPID_PUBLIC_KEY    (URL-safe base64 of the public key)
    VAPID_SUBJECT       ("mailto:contact@fidclic.com" or your business email)

Generate keys once with:
    from py_vapid import Vapid
    v = Vapid(); v.generate_keys()
    print('PRIVATE:', v.private_pem().decode())
    print('PUBLIC:', v.public_key_b64())

Then add to Vercel env vars + redeploy.

Free — no per-message fee, no SaaS subscription.
"""
from __future__ import annotations
import os
import json
import logging
from typing import Optional

logger = logging.getLogger("fidelitour.webpush")

_VAPID_PRIV = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
_VAPID_PUB = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
_VAPID_SUB = os.environ.get("VAPID_SUBJECT", "mailto:contact@fidclic.com").strip()


def is_configured() -> bool:
    return bool(_VAPID_PRIV and _VAPID_PUB)


def public_key() -> str:
    """The VAPID public key, given to browsers when they subscribe."""
    return _VAPID_PUB


def send_push(subscription: dict, title: str, body: str, *,
              url: Optional[str] = None,
              icon: Optional[str] = None,
              badge: Optional[str] = None) -> dict:
    """Send a Web Push notification to one subscription endpoint.

    `subscription` is the JSON dict the browser handed us (has `endpoint`,
    `keys.p256dh`, `keys.auth`).

    Returns {sent: bool, error?: str, no_op?: bool}.
    Never raises — any failure is logged + returned as {sent: False}.
    """
    if not is_configured():
        return {"sent": False, "error": "vapid_not_configured", "no_op": True}

    try:
        from pywebpush import webpush, WebPushException        # noqa: WPS433

        payload = {
            "title": title,
            "body": body,
            "url": url or "/",
            "icon": icon or "/favicon.svg",
            "badge": badge or "/favicon.svg",
        }
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=_VAPID_PRIV,
            vapid_claims={"sub": _VAPID_SUB},
        )
        logger.info("WebPush sent to %s", subscription.get("endpoint", "?")[:60])
        return {"sent": True}
    except Exception as exc:                                    # noqa: BLE001
        # If subscription is gone/expired, the caller should remove it.
        gone = "410" in str(exc) or "404" in str(exc)
        logger.warning("WebPush failed (%s): %s", "expired" if gone else "error", exc)
        return {"sent": False, "error": str(exc), "expired": gone}
