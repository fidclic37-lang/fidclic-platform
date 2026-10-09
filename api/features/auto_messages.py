"""
Messages automatiques — the messages that go out on their own, without
anyone approving them.

Decided with the user: four messages are automatic, everything else waits
for an OK (features/push_wallet.py, "À valider").

    Bienvenue           at sign-up — worded, with its points, on this
                        Automatisations page (features/welcome_bonus.py rules).
    Avis Google         after a scan — how often is each shop's choice:
                        at every scan, once every N days, or once only; and
                        never again once the client followed the link, if
                        the shop wants.
    Récompense proche   after the scan that leaves a client N visits (2 by
                        default) from its reward. On a points card, "visits"
                        are counted at the client's own average per visit.
                        Once per card cycle.
    Anniversaire        the birthday scenario of the Automatisations page,
                        which the daily run sends without approval.

Mounts at:
    GET  /api/owner/auto-messages      → the settings, for the Automatisations page
    PUT  /api/owner/auto-messages      → owner
    GET  /api/avis/{barcode_id}        → (public) the Google review link, counted

Every message is logged in `push_notifications` (the card's feed and the
Historique page read it) and delivered by server.dispatch_to_customer.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["auto-messages"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
FREQUENCIES = ("every_scan", "days", "once")

DEFAULTS: Dict[str, Dict[str, Any]] = {
    "google_review": {
        "enabled": True, "frequency": "days", "days": 30, "stop_after_click": True,
        "title": "Votre avis compte ⭐",
        "body": "Merci pour votre visite chez {business_name}, {first_name} ! "
                "Un petit avis Google nous aiderait beaucoup.",
    },
    "near_reward": {
        # one visit away by default (user, 2026-10-09)
        "enabled": True, "visits_left": 1,
        "title": "Vous y êtes presque, {first_name} ! ✨",
        "body": "Plus que {visits_left} {visites} chez {business_name} pour débloquer : {reward}.",
    },
}


def init(db):
    global _db
    _db = db
    try:
        db.auto_message_config.create_index("tenant_id", unique=True)
        db.push_notifications.create_index([("tenant_id", 1), ("customer_id", 1), ("type", 1), ("sent_at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


def config(tid: str) -> Dict[str, Dict[str, Any]]:
    doc = _db.auto_message_config.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    return {k: {**v, **(doc.get(k) or {})} for k, v in DEFAULTS.items()}


def _render(text: str, cust: Dict[str, Any], tenant: Dict[str, Any], **extra: Any) -> str:
    values = {"first_name": (cust.get("name") or "").split(" ")[0], "name": cust.get("name") or "",
              "business_name": tenant.get("campaign_sender_name") or tenant.get("name") or "",
              "points": str(cust.get("points") or 0), "visits": str(cust.get("visits") or 0),
              **{k: str(v) for k, v in extra.items()}}
    out = text or ""
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out.strip()


def _send(tid: str, cust: Dict[str, Any], kind: str, title: str, body: str,
          url: Optional[str] = None, **log: Any) -> Dict[str, Any]:
    _db.push_notifications.insert_one({"tenant_id": tid, "customer_id": cust["id"], "type": kind,
                                       "title": title, "body": body, "sent_at": _now(), "automatic": True,
                                       **log})
    try:
        import server as core
        if url:
            return core.dispatch_to_customer(tid, cust, title, body, kind=kind, url=url) or {}
        return core.dispatch_to_customer(tid, cust, title, body, kind=kind) or {}
    except Exception as exc:
        print(f"auto_messages: {kind} not delivered ({exc})")
    return {}


def _last(tid: str, cid: str, kind: str) -> Optional[datetime]:
    row = _db.push_notifications.find_one({"tenant_id": tid, "customer_id": cid, "type": kind},
                                          sort=[("sent_at", -1)])
    return _aware((row or {}).get("sent_at"))


# ---------------------------------------------------------------------------
# Bienvenue — at sign-up
# ---------------------------------------------------------------------------
def welcome(tid: str, cust: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The shop's welcome: its message, and its points credited once. Never
    raises — a welcome that cannot be sent must not cost a client its card."""
    try:
        from features.welcome_bonus import welcome_state
        state = welcome_state(tid)
        if not state["active"]:
            return None
        points, message = state["points"], state["message"]
        tenant = _db.tenants.find_one({"id": tid}) or {}
        if points and not _db.welcome_bonus_claims.find_one({"tenant_id": tid, "customer_id": cust["id"]}):
            _db.customers.update_one({"id": cust["id"]}, {"$inc": {"points": points}})
            _db.welcome_bonus_claims.insert_one({"tenant_id": tid, "customer_id": cust["id"],
                                                 "points": points, "created_at": _now()})
        body = _render(message or "Bienvenue chez {business_name} !", cust, tenant, points=points)
        title = _render("Bienvenue chez {business_name} 🎉", cust, tenant)
        _send(tid, cust, "welcome", title, body, points=points)
        return {"title": title, "message": body, "points": points}
    except Exception as exc:
        print(f"auto_messages: welcome failed ({exc})")
        return None


# ---------------------------------------------------------------------------
# Avis Google — after a scan
# ---------------------------------------------------------------------------
def public_base() -> str:
    return (os.environ.get("PUBLIC_APP_URL") or "https://app.fidclic.com").rstrip("/")


def google_review(tid: str, cust: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    at = at or _now()
    tenant = _db.tenants.find_one({"id": tid}) or {}
    if not (tenant.get("google_reviews_enabled") and tenant.get("google_review_url")):
        return False
    cfg = config(tid)["google_review"]
    if not cfg.get("enabled"):
        return False
    if cfg.get("stop_after_click") and _db.google_review_clicks.find_one({"tenant_id": tid, "customer_id": cust["id"]}):
        return False
    last = _last(tid, cust["id"], "google_review")
    freq = cfg.get("frequency") if cfg.get("frequency") in FREQUENCIES else "days"
    if freq == "once" and last:
        return False
    if freq == "days" and last and at - last < timedelta(days=max(1, int(cfg.get("days") or 30))):
        return False
    link = f"{public_base()}/api/avis/{cust.get('barcode_id')}"
    _send(tid, cust, "google_review", _render(cfg["title"], cust, tenant), _render(cfg["body"], cust, tenant),
          url=link)
    return True


@router.get("/api/avis/{barcode_id}")
def review_link(barcode_id: str):
    """The link the push carries: counted, then on to the shop's Google page."""
    cust = _db.customers.find_one({"barcode_id": (barcode_id or "").strip().upper()},
                                  {"_id": 0, "id": 1, "tenant_id": 1})
    if not cust:
        raise HTTPException(status_code=404, detail="Carte inconnue")
    tenant = _db.tenants.find_one({"id": cust["tenant_id"]}) or {}
    url = tenant.get("google_review_url")
    if not url:
        raise HTTPException(status_code=404, detail="Lien d'avis non configuré")
    _db.google_review_clicks.insert_one({"tenant_id": cust["tenant_id"], "customer_id": cust["id"],
                                         "at": _now(), "via": "push"})
    return RedirectResponse(url=url, status_code=302)


# ---------------------------------------------------------------------------
# Récompense proche — after a scan
# ---------------------------------------------------------------------------
def visits_to_reward(tid: str, cust: Dict[str, Any], tpl: Dict[str, Any]) -> Optional[int]:
    """How many visits stand between this client and its next reward. None when
    the card has no such thing (cashback) or it is already earned."""
    programme = tpl.get("programme") or ("points_euro" if tpl.get("points_mode") == "per_euro" else "stamps")
    if programme == "cashback":
        return None
    if programme in ("points_euro", "points_visit") or tpl.get("points_mode") == "per_euro":
        goal = int(tpl.get("reward_points") or 100)
        missing = goal - int(cust.get("points") or 0)
        if missing <= 0:
            return None
        recent = [float(v.get("points_awarded") or 0) for v in _db.visits.find(
            {"tenant_id": tid, "customer_id": cust["id"]}, {"_id": 0, "points_awarded": 1}
        ).sort("visit_time", -1).limit(10)]
        recent = [p for p in recent if p > 0]
        if not recent:
            return None
        return math.ceil(missing / (sum(recent) / len(recent)))
    per_stamp = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
    cycle = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1) * per_stamp
    in_cycle = int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0)
    left = cycle - in_cycle
    return left if left > 0 else None


def near_reward(tid: str, cust: Dict[str, Any], tpl: Dict[str, Any], cycle_start: Optional[datetime]) -> Any:
    """False, or what was said: {title, body, deferred}. Counted in the
    shop's sending limits (send_rules) — over them it waits for tomorrow,
    and the Wallet card then stays quiet too (server.scan_visit)."""
    cfg = config(tid)["near_reward"]
    if not cfg.get("enabled"):
        return False
    want = max(1, int(cfg.get("visits_left") or 1))
    left = visits_to_reward(tid, cust, tpl)
    if left != want:
        return False
    q: Dict[str, Any] = {"tenant_id": tid, "customer_id": cust["id"], "type": "near_reward"}
    if cycle_start is not None:
        q["sent_at"] = {"$gt": cycle_start}
    if _db.push_notifications.find_one(q):
        return False
    tenant = _db.tenants.find_one({"id": tid}) or {}
    reward = tpl.get("reward_description") or "votre récompense"
    word = "visite" if left == 1 else "visites"
    title = _render(cfg["title"], cust, tenant, visits_left=left, reward=reward, visites=word)
    body = _render(cfg["body"], cust, tenant, visits_left=left, reward=reward, visites=word)
    res = _send(tid, cust, "near_reward", title, body, visits_remaining=left)
    held = bool(res.get("deferred")) or res.get("reason") == "marketing_off"
    return {"title": title, "body": body, "deferred": held}


def after_scan(tid: str, cid: str) -> Dict[str, bool]:
    """Called by the scan once the visit is recorded. Never raises."""
    out = {"google_review": False}
    try:
        cust = _db.customers.find_one({"id": cid, "tenant_id": tid})
        if cust:
            out["google_review"] = google_review(tid, cust)
    except Exception as exc:
        print(f"auto_messages: after_scan failed ({exc})")
    return out


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class GoogleReviewIn(BaseModel):
    enabled: Optional[bool] = None
    frequency: Optional[str] = None
    days: Optional[int] = Field(None, ge=1, le=365)
    stop_after_click: Optional[bool] = None
    title: Optional[str] = Field(None, max_length=120)
    body: Optional[str] = Field(None, max_length=400)


class NearRewardIn(BaseModel):
    enabled: Optional[bool] = None
    visits_left: Optional[int] = Field(None, ge=1, le=10)
    title: Optional[str] = Field(None, max_length=120)
    body: Optional[str] = Field(None, max_length=400)


class AutoMessagesIn(BaseModel):
    google_review: Optional[GoogleReviewIn] = None
    near_reward: Optional[NearRewardIn] = None


def _view(tid: str) -> Dict[str, Any]:
    tenant = _db.tenants.find_one({"id": tid}) or {}
    birthday = _db.push_scenarios.find_one({"tenant_id": tid, "builtin": "birthday"}, {"_id": 0}) or {}
    from features.welcome_bonus import welcome_state
    w = welcome_state(tid)
    return {
        **config(tid),
        "google_link": {"url": tenant.get("google_review_url") or "",
                        "on": bool(tenant.get("google_reviews_enabled") and tenant.get("google_review_url"))},
        "welcome": {"enabled": w["enabled"], "message": w["message"], "points": w["points"],
                    "only_first_visit": w["only_first_visit"], "active": w["active"],
                    "default_message": w["default_message"]},
        "birthday": {"id": birthday.get("id"), "enabled": bool(birthday.get("enabled")),
                     "title": birthday.get("title") or "", "body": birthday.get("body") or ""},
    }


@router.get("/api/owner/auto-messages")
def get_auto_messages(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _view(token_data.tenant_id)


@router.put("/api/owner/auto-messages")
def put_auto_messages(body: AutoMessagesIn,
                      token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    sets: Dict[str, Any] = {}
    for key in ("google_review", "near_reward"):
        part = getattr(body, key)
        if part is None:
            continue
        for field, value in part.model_dump().items():
            if value is None:
                continue
            if field == "frequency" and value not in FREQUENCIES:
                raise HTTPException(status_code=400, detail="Fréquence inconnue")
            if field in ("title", "body") and not str(value).strip():
                raise HTTPException(status_code=400, detail="Le titre et le message ne peuvent pas être vides.")
            sets[f"{key}.{field}"] = value.strip() if isinstance(value, str) else value
    if sets:
        _db.auto_message_config.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, **sets}}, upsert=True)
    return _view(tid)
