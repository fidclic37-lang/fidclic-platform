"""
« Objectifs et récompenses » — les paliers que le commerce se fixe lui-même.

Status: ✅ Implemented.
Mounts at: /api/owner/milestones
Collections: `milestones` (one document per tenant), writes `defi_rewards`.

WHAT IT IS, AND WHAT IT IS NOT
    « Récompenses et paliers » (features/loyalty_card) is the client's LEVEL —
    Bronze to VIP, one ladder, read by the segments, the VIP rule and the badge
    on the card. It stays exactly as it is.

    An objectif is something else: « at 10 visits, a coffee », « at 500 € spent,
    a bottle ». As many as the owner wants, each counted on whatever suits it —
    so they cannot be rungs of the level ladder, which has to be ordered on one
    axis to mean anything (user, 2026-10-14).

HOW A REWARD IS HANDED OVER
    Reaching an objectif writes a reward « à remettre » into `defi_rewards`,
    the same place a défi's reward waits. The till already reads that list and
    already knows how to hand one over, so a staff member sees it next to the
    offers at the next scan with nothing new to learn.

ONCE, OR EVERY TIME
    The owner chooses per objectif. « Une fois » fires when the figure first
    passes the threshold. « À chaque fois » fires again at every multiple — the
    reward is keyed on the occurrence, so a scan that is replayed, or two tills
    scanning at once, cannot hand the same one out twice.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["milestones"])
_db = None

READERS = ["business_owner", "administrateur", "manager", "staff", "membre"]
WRITERS = ["business_owner", "administrateur", "manager", "membre"]
MAX_MILESTONES = 30
# What a figure can be counted on. Each reads a field the customer already
# carries, so nothing new has to be tracked.
UNITS: Dict[str, Dict[str, Any]] = {
    "visits": {"label": "Visites", "field": "visits", "suffix": "visites"},
    "points": {"label": "Points", "field": "points_lifetime", "suffix": "points"},
    "amount": {"label": "Montant dépensé", "field": "total_amount_paid", "suffix": "€"},
}
VALID_DAYS_DEFAULT = 60


def init(db):
    global _db
    _db = db
    try:
        db.milestones.create_index("tenant_id", unique=True)
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _doc(tid: str) -> Dict[str, Any]:
    return _db.milestones.find_one({"tenant_id": tid}, {"_id": 0}) or {"tenant_id": tid, "items": []}


def items_of(tid: str) -> List[Dict[str, Any]]:
    return [i for i in (_doc(tid).get("items") or []) if isinstance(i, dict)]


def progress_of(cust: Dict[str, Any], unit: str) -> float:
    """Where this client stands, on that objectif's own count.

    Points read what was EARNED, never the balance: a reward bought with points
    must not undo the progress towards the next objectif (features/loyalty_card
    .earned_points, same reasoning as the palier)."""
    if unit == "points":
        v = cust.get("points_lifetime")
        return float(v if v is not None else (cust.get("points") or 0))
    return float(cust.get(UNITS.get(unit, UNITS["visits"])["field"]) or 0)


# ---------------------------------------------------------------------------
# What the owner sets
# ---------------------------------------------------------------------------
class MilestoneIn(BaseModel):
    id: Optional[str] = None
    label: str = Field(..., max_length=80)            # the reward itself
    unit: str = "visits"
    threshold: float = Field(..., gt=0, le=1_000_000)
    repeat: bool = False                              # « à chaque fois »
    valid_days: int = Field(VALID_DAYS_DEFAULT, ge=1, le=365)
    active: bool = True


class MilestonesIn(BaseModel):
    items: List[MilestoneIn]


def _clean(body: MilestonesIn) -> List[Dict[str, Any]]:
    if len(body.items) > MAX_MILESTONES:
        raise HTTPException(status_code=400, detail=f"{MAX_MILESTONES} objectifs au maximum.")
    out: List[Dict[str, Any]] = []
    seen = set()
    for raw in body.items:
        label = (raw.label or "").strip()
        if not label:
            raise HTTPException(status_code=400, detail="Chaque objectif a besoin de sa récompense.")
        if raw.unit not in UNITS:
            raise HTTPException(status_code=400, detail="Unité inconnue.")
        # A threshold in visits or points is a count, not a measurement.
        th = round(float(raw.threshold), 2) if raw.unit == "amount" else float(int(raw.threshold))
        if th <= 0:
            raise HTTPException(status_code=400, detail="Le seuil doit être supérieur à zéro.")
        key = (raw.unit, th)
        if key in seen:
            raise HTTPException(status_code=400,
                                detail=f"Deux objectifs au même seuil ({th:g} {UNITS[raw.unit]['suffix']}).")
        seen.add(key)
        out.append({"id": raw.id or str(uuid.uuid4()), "label": label, "unit": raw.unit,
                    "threshold": th, "repeat": bool(raw.repeat),
                    "valid_days": int(raw.valid_days), "active": bool(raw.active)})
    out.sort(key=lambda i: (i["unit"], i["threshold"]))
    return out


@router.get("/api/owner/milestones")
def get_milestones(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return {"items": items_of(token_data.tenant_id),
            "units": [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "field"}} for k, v in UNITS.items()],
            "max": MAX_MILESTONES}


@router.put("/api/owner/milestones")
def put_milestones(body: MilestonesIn, token_data: TokenData = Depends(require_role(WRITERS))):
    items = _clean(body)
    _db.milestones.update_one({"tenant_id": token_data.tenant_id},
                              {"$set": {"tenant_id": token_data.tenant_id, "items": items,
                                        "updated_at": _now(), "updated_by": getattr(token_data, "email", None)}},
                              upsert=True)
    return {"items": items}


# ---------------------------------------------------------------------------
# What happens at the till
# ---------------------------------------------------------------------------
def _grant(tid: str, cust: Dict[str, Any], m: Dict[str, Any], occurrence: int, at: datetime) -> Optional[Dict[str, Any]]:
    """One reward, waiting to be handed over. The key carries the occurrence, so
    the same objectif can be won again without ever being granted twice."""
    row = {
        "id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": cust["id"],
        # `defi_rewards` keys a reward by the campaign that gave it; an objectif
        # takes that slot with its own id and the occurrence behind it.
        "campaign_id": f"objectif:{m['id']}#{occurrence}",
        "kind": "objectif",
        "title": f"{m['threshold']:g} {UNITS[m['unit']]['suffix']}",
        "reward": m["label"], "status": "pending", "won_at": at,
        "expires_at": at + timedelta(days=int(m.get("valid_days") or VALID_DAYS_DEFAULT)),
    }
    try:
        _db.defi_rewards.insert_one(dict(row))
    except Exception:
        return None                      # already granted (unique campaign+customer)
    row.pop("_id", None)
    return row


def after_scan(tenant_id: str, customer: Dict[str, Any], at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Objectifs this visit just reached. Best effort: the till calls it right
    after the visit is written, so the reward is there for the same scan."""
    at = at or _now()
    won: List[Dict[str, Any]] = []
    for m in items_of(tenant_id):
        if not m.get("active", True):
            continue
        th = float(m.get("threshold") or 0)
        if th <= 0:
            continue
        value = progress_of(customer, m.get("unit") or "visits")
        if value < th:
            continue
        # « Une fois »: occurrence 1, for ever. « À chaque fois »: the multiple
        # just reached — only that one. Handing out every past multiple would
        # mean a client with 100 visits collecting ten rewards the moment the
        # owner writes « toutes les 10 visites », for visits made before the
        # objectif existed.
        n = int(value // th) if m.get("repeat") else 1
        got = _grant(tenant_id, customer, m, n, at)
        if got:
            won.append(got)
    return won
