"""
Défis — « Faites 3 visites avant le 15 octobre : 1 dessert offert »
(Campagnes › Défi, user 2026-10-10).

A défi is a campaign of kind « defi » (features/campaign_kinds.py). Its
participants are the campaign's recipients; it runs from the send to the end
of its last day (Paris). Rules chosen by the user:

- Which visits count: the OWNER picks — at most one per day (per_day), or
  every scan (per_scan). Only scans made during the défi count.
- Won when the visits reach the target: the reward becomes « à récupérer »
  (collection defi_rewards), valid for as many days as the owner chose; the
  customer gets « Défi réussi ! » (outside the daily send limit); the till
  shows it with a « Remettre » button.
- A customer can be in several défis at once; each counts on its own.

    POST /api/owner/defis/rewards/{reward_id}/redeem
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from auth import require_role
from models import TokenData
from features import campaign_kinds as K

router = APIRouter(tags=["defis"])
_db = None
TILL = ["business_owner", "administrateur", "manager", "staff"]


def init(db):
    global _db
    _db = db
    try:
        db.defi_rewards.create_index([("campaign_id", 1), ("customer_id", 1)], unique=True)
        db.defi_rewards.create_index([("customer_id", 1), ("status", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _running(customer: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """The défis this customer takes part in that are on right now."""
    rows = _db.campaigns.find({"tenant_id": customer.get("tenant_id"), "kind": "defi", "status": "sent",
                               "recipient_ids": customer.get("id")}, {"_id": 0})
    out = []
    for c in rows:
        sent = K.aware(c.get("sent_at"))
        _, until = K.window(c)
        if sent and until and sent <= at <= until:
            out.append(c)
    return out


def progress(c: Dict[str, Any], customer_id: str, at: Optional[datetime] = None) -> int:
    """Visits that count for this défi, so far."""
    at = at or _now()
    sent = K.aware(c.get("sent_at"))
    _, until = K.window(c)
    if not sent:
        return 0
    end = min(at, until) if until else at
    rows = _db.visits.find({"tenant_id": c.get("tenant_id"), "customer_id": customer_id,
                            "visit_time": {"$gte": sent, "$lte": end}}, {"_id": 0, "visit_time": 1})
    times = [t for r in rows if (t := K.aware(r.get("visit_time")))]
    if (c.get("defi") or {}).get("count_mode") == "per_scan":
        return len(times)
    return len({t.astimezone(K.PARIS).date() for t in times})


def after_scan(tenant_id: str, customer: Dict[str, Any], at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Called after a visit is recorded: the défis this visit wins."""
    at = at or _now()
    won = []
    for c in _running(customer, at):
        d = c.get("defi") or {}
        target = int(d.get("target") or 0)
        if not target or progress(c, customer["id"], at) < target:
            continue
        reward = {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "campaign_id": c["id"],
                  "customer_id": customer["id"], "title": c.get("name") or "Défi",
                  "reward": d.get("reward") or "Récompense", "won_at": at,
                  "expires_at": at + timedelta(days=int(d.get("reward_valid_days") or 30)),
                  "status": "pending"}
        try:
            _db.defi_rewards.insert_one(dict(reward))       # unique (campaign, customer): won once
        except Exception:
            continue
        won.append(_public(reward, at))
        try:
            import server as core
            core.dispatch_to_customer(tenant_id, customer, "Défi réussi ! 🎉",
                                      f"Bravo, vous avez relevé « {reward['title']} » : {reward['reward']}. "
                                      "Présentez votre carte en caisse.", kind="defi_won")
        except Exception as exc:
            print(f"defis: success message not sent (non-fatal): {exc}")
    return won


def _public(r: Dict[str, Any], at: datetime) -> Dict[str, Any]:
    exp = K.aware(r.get("expires_at"))
    return {"id": r["id"], "title": r.get("title"), "reward": r.get("reward"),
            "won_at": K.aware(r.get("won_at")).isoformat() if K.aware(r.get("won_at")) else None,
            "expires_at": exp.isoformat() if exp else None,
            "status": "expired" if r.get("status") == "pending" and exp and exp < at else r.get("status")}


def pending_rewards(customer_id: str, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    at = at or _now()
    rows = _db.defi_rewards.find({"customer_id": customer_id, "status": "pending"}, {"_id": 0})
    return [_public(r, at) for r in rows if (e := K.aware(r.get("expires_at"))) and e >= at]


def card_view(customer: Dict[str, Any], at: Optional[datetime] = None) -> Dict[str, Any]:
    """What the customer's card and « Vos offres » show: the défis running
    (soonest end first) and the rewards won, still to collect."""
    at = at or _now()
    won_ids = {r["campaign_id"] for r in _db.defi_rewards.find({"customer_id": customer.get("id")},
                                                                 {"_id": 0, "campaign_id": 1})}
    running = []
    for c in _running(customer, at):
        if c["id"] in won_ids:
            continue
        d = c.get("defi") or {}
        _, until = K.window(c)
        days_left = max(0, (until.astimezone(K.PARIS).date() - at.astimezone(K.PARIS).date()).days + 1) if until else None
        running.append({"id": c["id"], "title": c.get("name") or "Défi", "message": c.get("content") or "",
                        "target": int(d.get("target") or 0), "progress": progress(c, customer["id"], at),
                        "count_mode": d.get("count_mode"), "reward": d.get("reward"),
                        "end_date": d.get("end_date"), "days_left": days_left,
                        "image_url": c.get("image_url")})
    running.sort(key=lambda x: x.get("end_date") or "9999")
    return {"running": running, "won": pending_rewards(customer.get("id"), at)}


@router.post("/api/owner/defis/rewards/{reward_id}/redeem")
def redeem(reward_id: str, token_data: TokenData = Depends(require_role(TILL))):
    """« Remettre » at the till: the défi's reward is handed over."""
    r = _db.defi_rewards.find_one({"id": reward_id, "tenant_id": token_data.tenant_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Récompense introuvable.")
    if r.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Cette récompense a déjà été remise.")
    exp = K.aware(r.get("expires_at"))
    if exp and exp < _now():
        raise HTTPException(status_code=409, detail="Cette récompense a expiré.")
    done = _db.defi_rewards.update_one({"id": reward_id, "status": "pending"},
                                       {"$set": {"status": "redeemed", "redeemed_at": _now(),
                                                 "redeemed_by": getattr(token_data, "email", None)}})
    if not getattr(done, "modified_count", 1):
        raise HTTPException(status_code=409, detail="Cette récompense a déjà été remise.")
    return {"id": reward_id, "status": "redeemed"}
