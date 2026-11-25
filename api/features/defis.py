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
    try:   # the card's défi read: this client's défis not over yet. Partial: only
           # défi campaigns are in it, never the shop's other (long-list) sends.
        db.campaigns.create_index([("tenant_id", 1), ("recipient_ids", 1), ("defi.end_date", 1)],
                                  name="defi_running", partialFilterExpression={"kind": "defi"})
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# What a running défi needs, never its recipients list (thousands of ids on a
# shop-wide send: the card open used to move all of them, load review 2026-11-25)
DEFI_FIELDS = {"_id": 0, "id": 1, "tenant_id": 1, "name": 1, "content": 1, "kind": 1, "status": 1,
               "sent_at": 1, "defi": 1, "visible_until": 1, "image_url": 1}


def first_live_day(at: datetime) -> str:
    """The first day (Paris, ISO) whose end is still ahead of `at`: a défi
    ending that day or later is not over (K.window: until = end_of(end_date))."""
    d = at.astimezone(K.PARIS).date()
    if K.end_of(d) < at:                        # 23:59:59.x: that day has ended
        d += timedelta(days=1)
    return d.isoformat()


def _running(customer: Dict[str, Any], at: datetime) -> List[Dict[str, Any]]:
    """The défis this customer takes part in that are on right now.

    The read only returns défis not over (end date today or later, through
    the `defi_running` index) and the rare one without an end date; the exact
    window check stays below, so the result is the same as reading them all."""
    base = {"tenant_id": customer.get("tenant_id"), "recipient_ids": customer.get("id"), "kind": "defi",
            "status": "sent"}
    rows = _db.campaigns.find({"$or": [dict(base, **{"defi.end_date": {"$gte": first_live_day(at)}}),
                                       dict(base, **{"defi.end_date": {"$in": [None, ""]}})]}, DEFI_FIELDS)
    out = []
    for c in rows:
        sent = K.aware(c.get("sent_at"))
        _, until = K.window(c)
        if sent and until and sent <= at <= until:
            out.append(c)
    return out


def _counted(c: Dict[str, Any], times: List[datetime], at: datetime) -> int:
    sent = K.aware(c.get("sent_at"))
    _, until = K.window(c)
    end = min(at, until) if until else at
    mine = [t for t in times if sent <= t <= end]
    if (c.get("defi") or {}).get("count_mode") == "per_scan":
        return len(mine)
    return len({t.astimezone(K.PARIS).date() for t in mine})


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


def progress_many(cs: List[Dict[str, Any]], customer_id: str, at: Optional[datetime] = None) -> Dict[str, int]:
    """progress() for several défis with one visits read per shop (the card
    used to read the visits once per running défi)."""
    at = at or _now()
    out: Dict[str, int] = {}
    by_tenant: Dict[Any, List[Dict[str, Any]]] = {}
    for c in cs:
        if K.aware(c.get("sent_at")):
            by_tenant.setdefault(c.get("tenant_id"), []).append(c)
        else:
            out[c["id"]] = 0
    for tid, group in by_tenant.items():
        ends = []
        for c in group:
            _, until = K.window(c)
            ends.append(min(at, until) if until else at)
        rows = _db.visits.find({"tenant_id": tid, "customer_id": customer_id,
                                "visit_time": {"$gte": min(K.aware(c.get("sent_at")) for c in group),
                                               "$lte": max(ends)}}, {"_id": 0, "visit_time": 1})
        times = [t for r in rows if (t := K.aware(r.get("visit_time")))]
        for c in group:
            out[c["id"]] = _counted(c, times, at)
    return out


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
    return {"id": r["id"], "title": r.get("title"), "reward": r.get("reward"), "kind": r.get("kind") or "defi",
            "won_at": K.aware(r.get("won_at")).isoformat() if K.aware(r.get("won_at")) else None,
            "expires_at": exp.isoformat() if exp else None,
            "status": "expired" if r.get("status") == "pending" and exp and exp < at else r.get("status")}


def pending_rewards(customer_id: str, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    at = at or _now()
    rows = _db.defi_rewards.find({"customer_id": customer_id, "status": "pending"}, {"_id": 0})
    return _pending_public(list(rows), at)


def _pending_public(rows: List[Dict[str, Any]], at: datetime) -> List[Dict[str, Any]]:
    # a parrainage offer (features/referrals, 2026-10-13) waits here too, with no end date
    return [_public(r, at) for r in rows
            if (e := K.aware(r.get("expires_at"))) is None and r.get("kind") == "parrainage" or (e and e >= at)]


def card_view(customer: Dict[str, Any], at: Optional[datetime] = None) -> Dict[str, Any]:
    """What the customer's card and « Vos offres » show: the défis running
    (soonest end first) and the rewards won, still to collect.

    Three reads whatever the number of défis: the running ones, then one
    rewards read (the pending ones + those of the running défis, which hides
    a défi already won), then one visits read for every défi's progress."""
    at = at or _now()
    cid = customer.get("id")
    live = _running(customer, at)
    ids = [c["id"] for c in live]
    q: Dict[str, Any] = {"customer_id": cid, "status": "pending"}
    if ids:
        q = {"customer_id": cid, "$or": [{"status": "pending"}, {"campaign_id": {"$in": ids}}]}
    # in insertion order, as the pending read returns them (sorted here: a
    # Mongo sort on _id could walk the whole collection's _id index instead)
    rows = sorted(_db.defi_rewards.find(q), key=lambda r: str(r.get("_id")))
    won_ids = {r.get("campaign_id") for r in rows}
    live = [c for c in live if c["id"] not in won_ids]
    counts = progress_many(live, cid, at)
    running = []
    for c in live:
        d = c.get("defi") or {}
        _, until = K.window(c)
        days_left = max(0, (until.astimezone(K.PARIS).date() - at.astimezone(K.PARIS).date()).days + 1) if until else None
        running.append({"id": c["id"], "title": c.get("name") or "Défi", "message": c.get("content") or "",
                        "target": int(d.get("target") or 0), "progress": counts.get(c["id"], 0),
                        "count_mode": d.get("count_mode"), "reward": d.get("reward"),
                        "end_date": d.get("end_date"), "days_left": days_left,
                        "image_url": c.get("image_url")})
    running.sort(key=lambda x: x.get("end_date") or "9999")
    pending = [{k: v for k, v in r.items() if k != "_id"} for r in rows if r.get("status") == "pending"]
    return {"running": running, "won": _pending_public(pending, at)}


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
