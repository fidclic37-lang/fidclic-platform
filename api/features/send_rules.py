"""
Paramètres › Notifications — how much reaches a client, and the page that
shows it.

LIMITES D'ENVOI (decided with the user)
    Each business sets its own limits on the Notifications page:
        per client     max per day, max per week
        whole shop     max per day, max per week
    0 means no limit. No time-of-day window, no closed-days rule, no Sunday
    rule — a business sends whenever it wants.

    Not counted, never held: what follows a client's own action —
    welcome, points after a scan, reward unlocked, récompense proche, the
    Google review request.

    When a message would go over a limit it is not lost: it waits for the
    next day (`deferred_messages`) and the daily run sends the waiting ones
    first, in this order — anniversaire → récompense proche → campagne
    manuelle → automatisation → IA. A message still waiting after 7 days is
    dropped (an offer for last week is not worth sending).

Mounts at:
    GET /api/owner/notifications/overview?period=current|previous
    PUT /api/owner/notifications/rules          → owner
"""
from __future__ import annotations

import contextvars
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["notifications"])
_db = None

PARIS = ZoneInfo("Europe/Paris")
READERS = ["business_owner", "administrateur", "manager"]
EXEMPT = {"welcome", "google_review", "near_reward", "reward_unlocked", "points", "scan", "transactional", "test"}
PRIORITY = {"birthday": 0, "near_reward": 1, "campaign": 2, "offer": 2, "news": 2,
            "push_wallet": 3, "automation": 3, "copilot": 4, "ai": 4}
DEFAULT_RULES = {"per_client_day": 3, "per_client_week": 10, "shop_day": 0, "shop_week": 0}
MAX_WAIT_DAYS = 7
# Set while the daily run re-sends a held message: it has already been
# checked and counted, so the gate lets it through as is.
_released = contextvars.ContextVar("send_rules_released", default=False)


def init(db):
    global _db
    _db = db
    try:
        db.send_counter.create_index([("tenant_id", 1), ("customer_id", 1), ("at", -1)])
        db.send_counter.create_index([("tenant_id", 1), ("at", -1)])
        db.deferred_messages.create_index([("status", 1), ("due", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day_start(at: datetime) -> datetime:
    local = at.astimezone(PARIS)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _week_start(at: datetime) -> datetime:
    local = at.astimezone(PARIS)
    monday = local - timedelta(days=local.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def rules(tid: str) -> Dict[str, int]:
    t = (_db.tenants.find_one({"id": tid}, {"_id": 0, "send_rules": 1}) or {}).get("send_rules") or {}
    return {k: int(t.get(k, v) or 0) for k, v in DEFAULT_RULES.items()}


def counted(kind: str) -> bool:
    return (kind or "campaign") not in EXEMPT


def over_limit(tid: str, cid: str, at: Optional[datetime] = None) -> Optional[str]:
    """Which limit a new message to this client would break, if any."""
    at = at or _now()
    r = rules(tid)
    day, week = _day_start(at), _week_start(at)
    checks = (("per_client_day", {"customer_id": cid, "at": {"$gte": day}}),
              ("per_client_week", {"customer_id": cid, "at": {"$gte": week}}),
              ("shop_day", {"at": {"$gte": day}}),
              ("shop_week", {"at": {"$gte": week}}))
    for key, q in checks:
        cap = r[key]
        if cap > 0 and _db.send_counter.count_documents({"tenant_id": tid, **q}) >= cap:
            return key
    return None


def record(tid: str, cid: str, kind: str, at: Optional[datetime] = None) -> None:
    _db.send_counter.insert_one({"tenant_id": tid, "customer_id": cid, "kind": kind, "at": at or _now()})


def defer(tid: str, customer: Dict[str, Any], title: str, body: str, kind: str,
          url: Optional[str], reason: str, at: Optional[datetime] = None, first: Optional[datetime] = None) -> None:
    at = at or _now()
    _db.deferred_messages.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": customer.get("id"),
        "title": title, "body": body, "kind": kind, "url": url, "reason": reason,
        "priority": PRIORITY.get(kind, 3), "status": "waiting",
        "first_at": first or at, "due": _day_start(at) + timedelta(days=1), "created_at": at})


def gate(tid: str, customer: Dict[str, Any], title: str, body: str, kind: str,
         url: Optional[str] = None, first: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Called by server.dispatch_to_customer before sending. None = go ahead
    (and the send is counted); otherwise the message waits for tomorrow."""
    if not counted(kind) or not customer.get("id") or _released.get():
        return None
    try:
        reason = over_limit(tid, customer["id"])
        if reason:
            defer(tid, customer, title, body, kind, url, reason, first=first)
            return {"sent": False, "channel": None, "deferred": True, "reason": reason}
        record(tid, customer["id"], kind)
    except Exception as exc:          # a counter must never stop a send
        print(f"send_rules: gate skipped ({exc})")
    return None


def drain(at: Optional[datetime] = None) -> Dict[str, int]:
    """Daily: the messages that waited go first, most important first."""
    at = at or _now()
    out = {"sent": 0, "waiting": 0, "dropped": 0}
    import server as core
    rows = list(_db.deferred_messages.find({"status": "waiting", "due": {"$lte": at}}, {"_id": 0})
                .sort([("priority", 1), ("created_at", 1)]))
    for m in rows:
        _db.deferred_messages.update_one({"id": m["id"]}, {"$set": {"status": "retried", "retried_at": at}})
        first = m.get("first_at")
        first = first if not isinstance(first, datetime) or first.tzinfo else first.replace(tzinfo=timezone.utc)
        if isinstance(first, datetime) and at - first > timedelta(days=MAX_WAIT_DAYS):
            _db.deferred_messages.update_one({"id": m["id"]}, {"$set": {"status": "dropped"}})
            out["dropped"] += 1
            continue
        cust = _db.customers.find_one({"id": m["customer_id"], "tenant_id": m["tenant_id"]}, {"_id": 0})
        if not cust:
            continue
        if over_limit(m["tenant_id"], cust["id"], at):
            defer(m["tenant_id"], cust, m["title"], m["body"], m["kind"], m.get("url"), "still_over", at, first)
            out["waiting"] += 1
            continue
        record(m["tenant_id"], cust["id"], m["kind"], at)
        token = _released.set(True)
        try:
            core.dispatch_to_customer(m["tenant_id"], cust, m["title"], m["body"], kind=m["kind"],
                                      **({"url": m["url"]} if m.get("url") else {}))
            _db.deferred_messages.update_one({"id": m["id"]}, {"$set": {"status": "sent"}})
            out["sent"] += 1
        except Exception as exc:
            print(f"send_rules: deferred send failed ({exc})")
        finally:
            _released.reset(token)
    return out


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
def _month_bounds(period: str, at: datetime):
    start = at.astimezone(PARIS).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if period == "previous":
        end = start
        start = (start - timedelta(days=1)).replace(day=1)
    else:
        end = (start + timedelta(days=32)).replace(day=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@router.get("/api/owner/notifications/overview")
def overview(period: str = "current", token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    at = _now()
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    plan = t.get("plan") or "silver"
    try:
        from server import get_plan_features
        f = get_plan_features(plan)
    except Exception:
        f = {}
    start, end = _month_bounds("previous" if period == "previous" else "current", at)
    sent = _db.delivery_log.count_documents({"tenant_id": tid, "channel": "web_push",
                                             "result.sent": {"$gt": 0}, "timestamp": {"$gte": start, "$lt": end}})
    quota = int(f.get("push_per_month") or 0)                  # 0 = unlimited
    r = rules(tid)
    ordered = ["silver", "gold", "vip"]
    upper = ordered[ordered.index(plan) + 1] if plan in ordered and plan != "vip" else None
    auto = _db.auto_message_config.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    scen = {s.get("builtin"): s for s in _db.push_scenarios.find({"tenant_id": tid}, {"_id": 0, "builtin": 1, "enabled": 1})}
    rules_doc = _db.earn_rules.find_one({"tenant_id": tid}) or {}
    others = [s for k, s in scen.items() if k not in ("birthday", "inactive")]
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1}) or {}
    last = _db.push_notifications.find_one({"tenant_id": tid}, {"_id": 0, "title": 1, "body": 1}, sort=[("sent_at", -1)])
    return {
        "period": "previous" if period == "previous" else "current",
        "usage": {"sent": sent, "quota": quota, "remaining": None if not quota else max(0, quota - sent),
                  "pct": round(sent / quota * 100) if quota else None,
                  "renews_on": end.astimezone(PARIS).date().isoformat()},
        "plan": {"key": plan, "label": f.get("label") or plan.title(), "upgrade": upper,
                 "push_per_month": quota, "shop_day": r["shop_day"], "shop_week": r["shop_week"]},
        "rules": r,
        # Consent is taken at sign-up (the join page records the proof); a
        # client may switch notifications off from its card.
        "consent": {"with_consent": _db.customers.count_documents({"tenant_id": tid, "consent.accepted": True,
                                                                   "deleted_at": {"$exists": False}}),
                    "total": _db.customers.count_documents({"tenant_id": tid, "deleted_at": {"$exists": False}}),
                    "switched_off": _db.card_prefs.count_documents({"tenant_id": tid, "push_enabled": False})},
        "automatic": [
            {"key": "welcome", "label": "Bienvenue nouveau client", "sub": "Notification lors de l'inscription.",
             "on": rules_doc.get("enabled", True) is not False and bool(rules_doc.get("welcome_bonus_message") or rules_doc.get("welcome_bonus_points")),
             "to": "/dashboard/card"},
            {"key": "birthday", "label": "Anniversaire", "sub": "Notification à la date d'anniversaire du client.",
             "on": bool((scen.get("birthday") or {}).get("enabled")), "to": "/dashboard/automations"},
            {"key": "inactive", "label": "Inactivité", "sub": "Rappel aux clients inactifs.",
             "on": bool((scen.get("inactive") or {}).get("enabled")), "to": "/dashboard/automations"},
            {"key": "near_reward", "label": "Récompense de fidélité", "sub": "Notification quand la récompense approche.",
             "on": (auto.get("near_reward") or {}).get("enabled", True) is not False, "to": "/dashboard/automations"},
            {"key": "others", "label": "Autres scénarios", "sub": "Notifications liées à vos automatisations.",
             "on": any(s.get("enabled") for s in others), "to": "/dashboard/automations"},
        ],
        "preview": {"shop": t.get("campaign_sender_name") or t.get("name") or "", "logo_url": tpl.get("logo_url") or "",
                    "title": (last or {}).get("title") or "🎉 Votre boisson offerte vous attend !",
                    "body": (last or {}).get("body") or "Vous avez atteint 200 points."},
        "can_edit": getattr(token_data, "role", None) == "business_owner",
    }


class RulesIn(BaseModel):
    per_client_day: Optional[int] = Field(None, ge=0, le=100)
    per_client_week: Optional[int] = Field(None, ge=0, le=500)
    shop_day: Optional[int] = Field(None, ge=0, le=1_000_000)
    shop_week: Optional[int] = Field(None, ge=0, le=5_000_000)


@router.put("/api/owner/notifications/rules")
def put_rules(body: RulesIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    new = {**rules(tid), **{k: v for k, v in body.model_dump().items() if v is not None}}
    for day, week in (("per_client_day", "per_client_week"), ("shop_day", "shop_week")):
        if new[day] and new[week] and new[week] < new[day]:
            raise HTTPException(status_code=400, detail="La limite par semaine ne peut pas être inférieure à celle par jour.")
    _db.tenants.update_one({"id": tid}, {"$set": {"send_rules": new}})
    return {"rules": new}
