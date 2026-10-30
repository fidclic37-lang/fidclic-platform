"""
APNs for Wallet passes — "this pass changed, come and get it".

WHY
    A pass is rebuilt from live data every time Wallet asks for it, so its
    content is never stale. The question is *when* Wallet asks. Without a push
    it only asks when the customer pulls to refresh — so a stamp added at the
    counter showed up minutes or hours later, if at all. This module closes
    that gap: after a scan we tell Apple, Apple wakes the device, the device
    fetches the new pass, and the meter fills while the customer is still
    holding the phone.

HOW (Apple's Wallet web-service contract)
    • transport  HTTP/2 to api.push.apple.com, authenticated with the SAME
      Pass Type ID certificate that signs the passes — no extra key, no extra
      Apple account step.
    • payload    an empty JSON object. A pass push carries no alert: the alert
      the customer sees comes from `changeMessage` on a field inside the pass.
    • headers    apns-push-type alert, apns-priority 10 — delivered now; a
      background / 5 push is throttled by the device (see push_to_tokens).
    • topic      the pass type identifier.
    • tokens     stored per device in `pass_registrations` when Wallet
      registers (features/wallet_passes.py). 410 / BadDeviceToken means the
      customer deleted the pass — we drop the row so we stop pushing to it.

SAFETY
    Every entry point is best-effort: a push failure must never break a scan.
    Callers get a summary dict; nothing raises.
"""
from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from typing import Any, Dict, Iterable, List, Optional

APNS_HOST = "https://api.push.apple.com"
_CERT_LOCK = threading.Lock()
_cert_paths: Optional[tuple] = None


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _b64_env(name: str) -> bytes:
    v = _env(name)
    if not v:
        return b""
    try:
        return base64.b64decode(v)
    except Exception:
        return v.encode()


def is_configured() -> bool:
    return bool(_env("APPLE_PASS_TYPE_ID") and _b64_env("APPLE_PASS_CERT_B64")
                and _b64_env("APPLE_PASS_KEY_B64"))


def transport_ready() -> bool:
    """Is the HTTP/2 client actually available in this deployment? Reported in
    the owner's Wallet panel so a missing dependency shows up as a fact rather
    than as passes that quietly never update."""
    try:
        import httpx  # noqa: F401
        import h2     # noqa: F401
        return True
    except ImportError:
        return False


def _cert_files() -> Optional[tuple]:
    """httpx wants files on disk for the client certificate. The PEMs live in
    env vars, so they are written once to the function's private tmp dir."""
    global _cert_paths
    if _cert_paths:
        return _cert_paths
    with _CERT_LOCK:
        if _cert_paths:
            return _cert_paths
        cert, key = _b64_env("APPLE_PASS_CERT_B64"), _b64_env("APPLE_PASS_KEY_B64")
        if not cert or not key:
            return None
        d = tempfile.mkdtemp(prefix="fidclic-apns-")
        cp, kp = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
        for path, data in ((cp, cert), (kp, key)):
            with open(path, "wb") as fh:
                fh.write(data)
            os.chmod(path, 0o600)
        _cert_paths = (cp, kp)
        return _cert_paths


def push_to_tokens(tokens: Iterable[str], pass_type_id: Optional[str] = None) -> Dict[str, Any]:
    """Send the empty pass-update push to each device token.
    Returns {sent, gone, failed, errors[], results[]} — `gone` tokens are dead
    and should be deleted by the caller (it owns the registrations
    collection); `results` has one {token, status, reason, apns_id} per token:
    Apple's answer and its receipt number, kept in the push history.
    `pass_type_id`: a business's own id (services/pass_identity) — its topic
    and its certificate; the shared one by default."""
    out: Dict[str, Any] = {"sent": 0, "gone": [], "failed": 0, "errors": [], "results": []}
    tokens = [t for t in dict.fromkeys(tokens) if t]
    if not tokens:
        return out
    if not is_configured():
        out["errors"].append("apple pass certificate not configured")
        return out
    shared = not pass_type_id or pass_type_id == _env("APPLE_PASS_TYPE_ID")
    if shared:
        paths = _cert_files()
    else:
        from services import pass_identity as PI
        paths = PI.cert_files(pass_type_id)
    if not paths:
        out["errors"].append("certificate could not be materialised")
        return out

    try:
        import httpx
    except ImportError:
        out["errors"].append("httpx missing — add httpx[http2] to api/requirements.txt")
        return out

    topic = _env("APPLE_PASS_TYPE_ID") if shared else pass_type_id
    # alert + priority 10, not background + 5 (user, 2026-10-05: pushes
    # « reçus » by Apple, yet some iPhones never updated, or only on
    # pull-to-refresh, and the lock-screen alert came late or silently).
    # Apple defines priority 5 as « send based on power considerations on the
    # user's device » and throttles background pushes — a few test campaigns
    # in an hour, or Low Power Mode, and the device simply stops coming. The
    # payload stays the empty {} Wallet expects; the alert the customer sees
    # is still the changeMessage of the field that changed in the pass.
    headers = {
        "apns-topic": topic,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "content-type": "application/json",
    }
    try:
        with httpx.Client(http2=True, cert=paths, timeout=10.0) as client:
            for token in tokens:
                try:
                    r = client.post(f"{APNS_HOST}/3/device/{token}", headers=headers, content=b"{}")
                    why = ""
                    if r.status_code != 200:
                        try:
                            why = (r.json() or {}).get("reason", "")
                        except Exception:
                            why = ""
                    out["results"].append({"token": token, "status": r.status_code, "reason": why,
                                           "apns_id": (getattr(r, "headers", None) or {}).get("apns-id")})
                    if r.status_code == 200:
                        out["sent"] += 1
                    elif r.status_code in (410, 400):
                        # 410 Unregistered, 400 BadDeviceToken → the pass is gone
                        reason = ""
                        try:
                            reason = (r.json() or {}).get("reason", "")
                        except Exception:
                            pass
                        if r.status_code == 410 or reason in ("BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"):
                            out["gone"].append(token)
                        else:
                            out["failed"] += 1
                            out["errors"].append(f"{r.status_code} {reason}")
                    else:
                        out["failed"] += 1
                        out["errors"].append(f"{r.status_code} {r.text[:120]}")
                except Exception as e:  # noqa: BLE001 — one bad token must not stop the rest
                    out["failed"] += 1
                    out["errors"].append(str(e)[:120])
                    out["results"].append({"token": token, "status": 0, "reason": str(e)[:120], "apns_id": None})
    except Exception as e:  # noqa: BLE001 — TLS/handshake level
        out["errors"].append(str(e)[:200])
    return out
