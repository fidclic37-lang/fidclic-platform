"""
Auto-generated messages for birthdays + inactive customers.

Status: ✅ Implemented (template-based; no LLM dependency).
Mounts at: /api/owner/auto-campaigns/*
Collections:
  - `auto_campaign_config` (one doc per tenant)
  - existing `customers`, `tenants`, `push_notifications`, `customer_status_config`

Each tenant configures:
  - birthday: enabled, message template, points_to_credit (welcome-style boost)
  - inactive: enabled, message template, days_to_trigger (uses
    customer_status_config when not overridden)

The actual sending is template substitution + write to `push_notifications`
for now (so it shows up on the History page). Real channel delivery (Apple
Wallet APN, Google Wallet, SMS, Email) is wired separately — adding more
channels means appending to `dispatch_message()` below without touching the
rest of this module.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from auth import require_role

router = APIRouter(tags=["auto-campaigns"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.auto_campaign_config.create_index("tenant_id", unique=True)
        db.auto_campaign_log.create_index([("tenant_id", 1), ("kind", 1), ("customer_id", 1)])
    except Exception:
        pass


# ---------- Models ----------
class AutoCampaignConfig(BaseModel):
    tenant_id: Optional[str] = None
    birthday_enabled: bool = True
    # Both title and body are now editable — no more hardcoded strings
    # composed in run_birthdays(). The owner controls everything.
    birthday_title: str = "Joyeux anniversaire {first_name} ! 🎂"
    birthday_message: str = "Joyeux anniversaire {first_name} ! 🎂 Une boisson est offerte aujourd'hui chez {business_name}."
    birthday_bonus_points: int = 50
    inactive_enabled: bool = True
    inactive_title: str = "{business_name} — vous nous manquez"
    inactive_message: str = "{first_name}, vous nous manquez chez {business_name}. -10% sur votre prochaine visite — à bientôt !"
    inactive_trigger_days: int = 0
    inactive_cooldown_days: int = 30
    almost_there_enabled: bool = True
    almost_there_title: str = "Plus qu'une visite ! 🎁"
    almost_there_message: str = "{first_name}, vous êtes à 1 visite d'une récompense chez {business_name} ! ☕"
    almost_there_visits_left: int = 1
    almost_there_cooldown_days: int = 7
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _config(tenant_id: str) -> AutoCampaignConfig:
    doc = _db.auto_campaign_config.find_one({"tenant_id": tenant_id}) or {}
    payload = {**AutoCampaignConfig().model_dump(), **{k: v for k, v in doc.items() if k != "_id"}}
    return AutoCampaignConfig(**payload)


def _substitute(template: str, ctx: Dict[str, Any]) -> str:
    """Lightweight {placeholder} substitution — no f-string, no LLM."""
    out = template or ""
    for k, v in (ctx or {}).items():
        out = out.replace("{" + k + "}", str(v) if v is not None else "")
    return out


def _build_ctx(customer: dict, tenant: dict) -> Dict[str, Any]:
    name = customer.get("name") or ""
    return {
        "first_name": name.split(" ")[0] if name else "",
        "name": name,
        "business_name": tenant.get("name") or "your favourite spot",
        "tier": (customer.get("tier") or "bronze").title(),
        "points": int(customer.get("points", 0) or 0),
        "visits": int(customer.get("visits", 0) or 0),
    }


def _dispatch_message(tenant_id: str, customer: dict, kind: str, title: str, body: str):
    """Record + deliver a message.

    Always:
      1) Writes to `push_notifications` so the History page surfaces it.
      2) Writes to `auto_campaign_log` so cooldown logic works.
    Best-effort:
      3) Sends a real SMS via Twilio if configured (TWILIO_* env vars set
         on Render) AND the customer has a phone number on file.
         Failures are logged in `delivery_log` but never raise — the
         message is still considered "dispatched" because the platform
         did everything in its power.

    Closure check:
      Before sending, ask features.business_hours.is_open_on(today). If the
      tenant is closed today (weekly closure, public holiday, or annual
      vacation), the message is skipped — we never send 'come visit today'
      on a day the door is locked.
    """
    now = datetime.now(timezone.utc)
    # Respect tenant closures — never push 'come visit' on a closed day
    try:
        from features.business_hours import is_open_on        # noqa: WPS433
        if not is_open_on(tenant_id, now.date()):
            _db.delivery_log.insert_one({
                "tenant_id": tenant_id,
                "customer_id": customer.get("id"),
                "channel": "skipped_closed_day",
                "kind": kind,
                "result": {"reason": "tenant_closed_today"},
                "timestamp": now,
            })
            return
    except Exception:
        pass    # never let a closure-check failure block dispatch
    _db.push_notifications.insert_one({
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "customer_id": customer.get("id"),
        "type": kind,
        "title": title,
        "body": body,
        "sent_at": now,
    })
    _db.auto_campaign_log.insert_one({
        "tenant_id": tenant_id,
        "customer_id": customer.get("id"),
        "kind": kind,
        "sent_at": now,
    })

    # ---- Real-channel delivery — Web Push first, SMS as fallback ----
    # Channel preference: Web Push > SMS > (email later).
    # Web Push is free, instant, and customer already opted in via the wallet
    # card page. SMS is the fallback for customers who haven't subscribed.
    push_sent = False
    try:
        from features.push_subscriptions import fan_out_to_customer       # noqa: WPS433
        push_result = fan_out_to_customer(tenant_id, customer.get("id"), title, body)
        push_sent = (push_result.get("sent", 0) > 0)
        _db.delivery_log.insert_one({
            "tenant_id": tenant_id,
            "customer_id": customer.get("id"),
            "channel": "web_push",
            "kind": kind,
            "result": push_result,
            "timestamp": now,
        })
    except Exception:
        pass

    # SMS fallback only if push didn't reach any device
    if not push_sent:
        try:
            from services.sms import send_sms, is_configured              # noqa: WPS433
            phone = customer.get("phone")
            if phone and is_configured():
                result = send_sms(phone, body)
                _db.delivery_log.insert_one({
                    "tenant_id": tenant_id,
                    "customer_id": customer.get("id"),
                    "channel": "sms_fallback",
                    "kind": kind,
                    "phone": phone,
                    "result": result,
                    "timestamp": now,
                })
        except Exception:
            pass


# ---------- Config endpoints ----------
@router.get("/api/owner/auto-campaigns/config")
def get_config(token_data=Depends(require_role(["business_owner", "manager"]))):
    return _config(token_data.tenant_id).model_dump()


@router.put("/api/owner/auto-campaigns/config")
def put_config(
    cfg: AutoCampaignConfig,
    token_data=Depends(require_role(["business_owner"])),
):
    cfg.tenant_id = token_data.tenant_id
    cfg.updated_at = datetime.now(timezone.utc)
    payload = cfg.model_dump()
    _db.auto_campaign_config.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


# ----------------------------------------------------------------------
# Pending auto-runs queue
#
# Cron jobs (or manual "Prepare" calls from the owner) write a row to
# `pending_auto_runs` with status='pending'. The owner reviews, edits if
# wanted, then approves to actually send. Nothing leaves the server
# without an explicit owner approval.
# ----------------------------------------------------------------------

def _prepare_run(tenant_id: str, kind: str, title: str, body_template: str,
                 candidates: list) -> str:
    """Create a single pending_auto_runs row covering N recipients. Returns
    the row id. Caller passes already-filtered candidates (cooldowns, dedup,
    etc. applied)."""
    if not candidates:
        return ""
    recipients = [
        {
            "customer_id": c.get("id"),
            "name": c.get("name") or "",
            "phone": c.get("phone") or "",
            "email": c.get("email") or "",
            "first_name": (c.get("name") or "").split(" ")[0],
        }
        for c in candidates
    ]
    # Retire the previous unapproved batch of this kind — see the long note on
    # server.py::_supersede_pending. Without it the queue accumulates one
    # identical copy per run, because a prepared batch never writes the
    # auto_campaign_log row that the cooldown checks.
    try:
        _db.pending_auto_runs.update_many(
            {"tenant_id": tenant_id, "kind": kind, "status": "pending"},
            {"$set": {"status": "superseded",
                      "superseded_at": datetime.now(timezone.utc)}},
        )
    except Exception as _e:
        print(f"_prepare_run: supersede failed ({kind}): {_e}")

    row_id = str(uuid.uuid4())
    _db.pending_auto_runs.insert_one({
        "id": row_id,
        "tenant_id": tenant_id,
        "kind": kind,                         # birthday | inactive | almost_there
        "title": title,
        "body_template": body_template,
        "recipients": recipients,
        "recipient_count": len(recipients),
        "status": "pending",                   # pending | approved | skipped
        "prepared_at": datetime.now(timezone.utc),
    })
    return row_id


# ---------- Run endpoints ----------
@router.post("/api/owner/auto-campaigns/run-birthdays")
def run_birthdays(
    dry_run: bool = False,
    prepare: bool = False,
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    """Find today's birthday customers.
       prepare=True   → write to pending_auto_runs queue (owner reviews + approves).
       dry_run=True   → return previews without writing anything.
       Otherwise      → send immediately (legacy path; cron now uses prepare=True).
    """
    cfg = _config(token_data.tenant_id)
    if not cfg.birthday_enabled:
        return {"sent": 0, "reason": "disabled"}
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    today_mmdd = datetime.now(timezone.utc).strftime("%m-%d")

    customers = list(_db.customers.find({
        "tenant_id": token_data.tenant_id,
        "birthday": today_mmdd,
    }).limit(2000))

    eligible = []
    previews = []
    for c in customers:
        already = _db.auto_campaign_log.find_one({
            "tenant_id": token_data.tenant_id,
            "customer_id": c["id"],
            "kind": "birthday",
            "sent_at": {"$gte": datetime.now(timezone.utc) - timedelta(hours=20)},
        })
        if already:
            continue
        eligible.append(c)
        ctx = _build_ctx(c, tenant)
        previews.append({
            "customer_id": c["id"], "name": c.get("name"),
            "body": _substitute(cfg.birthday_message, ctx),
        })

    if dry_run:
        return {"found": len(customers), "eligible": len(eligible), "dry_run": True, "preview": previews}

    if prepare:
        # Queue rather than send. Title/body templates carry forward; per-customer
        # personalisation happens at approve time.
        title_template = cfg.birthday_title or "🎂 Joyeux anniversaire !"
        run_id = _prepare_run(token_data.tenant_id, "birthday", title_template, cfg.birthday_message, eligible)
        return {"prepared": True, "run_id": run_id, "recipient_count": len(eligible)}

    sent = 0
    for c in eligible:
        ctx = _build_ctx(c, tenant)
        body = _substitute(cfg.birthday_message, ctx)
        title = _substitute(cfg.birthday_title, ctx)
        _dispatch_message(token_data.tenant_id, c, "birthday", title, body)
        if cfg.birthday_bonus_points > 0:
            _db.customers.update_one({"id": c["id"]}, {"$inc": {"points": cfg.birthday_bonus_points}})
            # Google Wallet — live points/tier sync on the customer's existing pass
            # (no-op unless they already added one; never raises).
            try:
                from features.google_wallet import sync_wallet_after_points_change  # noqa: WPS433
                sync_wallet_after_points_change(c["id"])
            except Exception:
                pass
        sent += 1
    return {"found": len(customers), "sent": sent, "dry_run": False}


@router.post("/api/owner/auto-campaigns/run-inactive")
def run_inactive(
    dry_run: bool = False,
    prepare: bool = False,
    limit: int = 200,
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    cfg = _config(token_data.tenant_id)
    if not cfg.inactive_enabled:
        return {"sent": 0, "reason": "disabled"}
    trigger_days = cfg.inactive_trigger_days
    if trigger_days <= 0:
        status_cfg = _db.customer_status_config.find_one({"tenant_id": token_data.tenant_id}) or {}
        trigger_days = int(status_cfg.get("dormant_after_days", 90) or 90)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=trigger_days)
    cooldown_cutoff = now - timedelta(days=max(1, cfg.inactive_cooldown_days))
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    candidates = list(_db.customers.find({
        "tenant_id": token_data.tenant_id,
        "last_visit_date": {"$lte": cutoff},
    }).limit(limit * 5))

    eligible = []
    previews = []
    for c in candidates:
        recent_log = _db.auto_campaign_log.find_one({
            "tenant_id": token_data.tenant_id,
            "customer_id": c["id"],
            "kind": "inactive_rescue",
            "sent_at": {"$gte": cooldown_cutoff},
        })
        if recent_log:
            continue
        eligible.append(c)
        ctx = _build_ctx(c, tenant)
        previews.append({
            "customer_id": c["id"], "name": c.get("name"),
            "days_since_last": (now - c["last_visit_date"]).days if c.get("last_visit_date") else None,
            "body": _substitute(cfg.inactive_message, ctx),
        })
        if len(eligible) >= limit:
            break

    if dry_run:
        return {"trigger_days": trigger_days, "eligible": len(eligible), "dry_run": True, "preview": previews}

    if prepare:
        run_id = _prepare_run(token_data.tenant_id, "inactive_rescue", cfg.inactive_title, cfg.inactive_message, eligible)
        return {"prepared": True, "run_id": run_id, "recipient_count": len(eligible)}

    sent = 0
    for c in eligible:
        ctx = _build_ctx(c, tenant)
        body = _substitute(cfg.inactive_message, ctx)
        title = _substitute(cfg.inactive_title, ctx)
        _dispatch_message(token_data.tenant_id, c, "inactive_rescue", title, body)
        sent += 1
    return {"trigger_days": trigger_days, "candidates": len(candidates), "sent": sent, "dry_run": False}


@router.post("/api/owner/auto-campaigns/run-almost-there")
def run_almost_there(
    dry_run: bool = False,
    prepare: bool = False,
    limit: int = 200,
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    """Find customers who are EXACTLY `almost_there_visits_left` visits away
    from the next reward, and send them a personalised nudge. Reward cycle
    is read from card_templates: every (visits_per_stamp * reward_threshold_stamps)
    visits unlocks the next reward."""
    cfg = _config(token_data.tenant_id)
    if not cfg.almost_there_enabled:
        return {"sent": 0, "reason": "disabled"}

    tpl = _db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
    visits_per_stamp = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
    reward_threshold = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
    cycle = visits_per_stamp * reward_threshold

    target_remaining = max(1, int(cfg.almost_there_visits_left))
    now = datetime.now(timezone.utc)
    cooldown_cutoff = now - timedelta(days=max(1, cfg.almost_there_cooldown_days))
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}

    candidates = list(_db.customers.find({
        "tenant_id": token_data.tenant_id,
        "visits": {"$gt": 0},
    }).limit(limit * 5))

    eligible = []
    previews = []
    for c in candidates:
        v = int(c.get("visits", 0) or 0)
        remaining = cycle - (v % cycle) if (v % cycle) else cycle
        if remaining != target_remaining:
            continue
        recent_log = _db.auto_campaign_log.find_one({
            "tenant_id": token_data.tenant_id,
            "customer_id": c["id"],
            "kind": "almost_there",
            "sent_at": {"$gte": cooldown_cutoff},
        })
        if recent_log:
            continue
        eligible.append(c)
        ctx = _build_ctx(c, tenant)
        ctx["visits_left"] = target_remaining
        previews.append({
            "customer_id": c["id"], "name": c.get("name"),
            "visits": v, "visits_left": target_remaining,
            "body": _substitute(cfg.almost_there_message, ctx),
        })
        if len(eligible) >= limit:
            break

    if dry_run:
        return {"cycle_visits": cycle, "eligible": len(eligible), "dry_run": True, "preview": previews}

    if prepare:
        run_id = _prepare_run(token_data.tenant_id, "almost_there", cfg.almost_there_title, cfg.almost_there_message, eligible)
        return {"prepared": True, "run_id": run_id, "recipient_count": len(eligible)}

    sent = 0
    for c in eligible:
        ctx = _build_ctx(c, tenant)
        ctx["visits_left"] = target_remaining
        body = _substitute(cfg.almost_there_message, ctx)
        title = _substitute(cfg.almost_there_title, ctx)
        _dispatch_message(token_data.tenant_id, c, "almost_there", title, body)
        sent += 1
    return {"cycle_visits": cycle, "candidates_scanned": len(candidates), "sent": sent, "dry_run": False}


# ============================================================
# Pending auto-runs review queue
# ============================================================
@router.get("/api/owner/auto-campaigns/pending")
def list_pending_auto_runs(
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    """Owner-facing list of auto-campaign batches that have been PREPARED but
    not yet SENT. Each row shows recipient count, title, body template — the
    owner reviews and approves to send (or skip to discard).
    """
    rows = list(_db.pending_auto_runs.find(
        {"tenant_id": token_data.tenant_id, "status": "pending"},
        {"_id": 0},
    ).sort("prepared_at", -1).limit(100))
    return {"pending": rows, "count": len(rows)}


class EditPendingRunRequest(BaseModel):
    title: Optional[str] = None
    body_template: Optional[str] = None


@router.put("/api/owner/auto-campaigns/pending/{run_id}")
def edit_pending_auto_run(
    run_id: str,
    req: EditPendingRunRequest,
    token_data=Depends(require_role(["business_owner"])),
):
    """Edit the title and/or body template of a pending run BEFORE approval."""
    update = {}
    if req.title is not None: update["title"] = req.title
    if req.body_template is not None: update["body_template"] = req.body_template
    if not update:
        return {"updated": False}
    res = _db.pending_auto_runs.update_one(
        {"id": run_id, "tenant_id": token_data.tenant_id, "status": "pending"},
        {"$set": update},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pending run not found or already processed")
    return {"updated": True}


@router.post("/api/owner/auto-campaigns/pending/{run_id}/approve")
def approve_pending_auto_run(
    run_id: str,
    token_data=Depends(require_role(["business_owner"])),
):
    """Owner clicked Approve. Now actually fire each message in the batch,
    using the final title + body_template stored on the run."""
    run = _db.pending_auto_runs.find_one({
        "id": run_id, "tenant_id": token_data.tenant_id, "status": "pending",
    })
    if not run:
        raise HTTPException(status_code=404, detail="Pending run not found or already processed")

    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    title_tpl = run.get("title", "")
    body_tpl = run.get("body_template", "")
    sent = 0
    for r in run.get("recipients", []):
        # Re-load the customer at send time so we have fresh points/visits
        c = _db.customers.find_one({"id": r.get("customer_id"), "tenant_id": token_data.tenant_id})
        if not c:
            continue
        ctx = _build_ctx(c, tenant)
        title = _substitute(title_tpl, ctx)
        body = _substitute(body_tpl, ctx)
        try:
            _dispatch_message(token_data.tenant_id, c, run.get("kind") or "auto", title, body)
            sent += 1
        except Exception as _e:
            # Best effort — don't let one bad recipient nuke the rest
            print(f"approve_pending_auto_run dispatch failed for {r.get('customer_id')}: {_e}")
    _db.pending_auto_runs.update_one(
        {"id": run_id},
        {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc), "sent_count": sent}},
    )
    return {"approved": True, "sent": sent, "run_id": run_id}


@router.post("/api/owner/auto-campaigns/pending/{run_id}/skip")
def skip_pending_auto_run(
    run_id: str,
    token_data=Depends(require_role(["business_owner"])),
):
    """Owner declined this batch — discard without sending."""
    res = _db.pending_auto_runs.update_one(
        {"id": run_id, "tenant_id": token_data.tenant_id, "status": "pending"},
        {"$set": {"status": "skipped", "skipped_at": datetime.now(timezone.utc)}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pending run not found")
    return {"skipped": True}


@router.post("/api/owner/auto-campaigns/test-sms")
def test_sms(
    body: Dict[str, Any],
    token_data=Depends(require_role(["business_owner"])),
):
    """Send a single test SMS to any phone number — for manual verification
    that Twilio credentials work end-to-end. Body: {to: str, message?: str}."""
    from services.sms import send_sms, is_configured                     # noqa: WPS433
    if not is_configured():
        return {
            "sent": False,
            "error": "twilio_not_configured",
            "hint": "Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER on Render.",
        }
    to = (body or {}).get("to") or ""
    msg = (body or {}).get("message") or "Test SMS from FidéliTour — Twilio is wired correctly!"
    result = send_sms(to, msg)
    _db.delivery_log.insert_one({
        "tenant_id": token_data.tenant_id,
        "channel": "sms",
        "kind": "manual_test",
        "phone": to,
        "result": result,
        "timestamp": datetime.now(timezone.utc),
    })
    return result


@router.get("/api/owner/auto-campaigns/log")
def log(
    days: int = 30,
    kind: Optional[str] = None,
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = {"tenant_id": token_data.tenant_id, "sent_at": {"$gte": cutoff}}
    if kind:
        query["kind"] = kind
    rows = list(_db.auto_campaign_log.find(query).sort("sent_at", -1).limit(500))
    counts: Dict[str, int] = {}
    for r in rows:
        r.pop("_id", None)
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1
    return {"counts": counts, "log": rows}
