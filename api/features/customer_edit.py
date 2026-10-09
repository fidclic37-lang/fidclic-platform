"""
Clients › « Modifier la fiche » and « Ajuster points / tampons » (QA UX04,
user, 2026-10-08: there was no way to correct a customer).

DECIDED WITH THE USER
    • Editable: name, phone, e-mail, birthday, postal code, student, source.
      The same rules as the signup form (services/customer_fields); a phone
      or an e-mail already on another client of the shop is refused, so no
      duplicate card appears.
    • Points and stamps (visits) can be adjusted by hand, with a reason —
      compulsory — kept in the client's history.
    • Who: the owner, administrateurs and managers (a manager only for the
      clients of their establishments). Staff (scan only) cannot.
    • After a change the client's Wallet card refreshes (no alert on the
      phone) and the Historique shows « Fiche client modifiée » /
      « Ajustement manuel », by whom.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S
from services import customer_fields as CF

router = APIRouter(tags=["clients"])
_db = None
EDITORS = ["business_owner", "administrateur", "manager"]

FIELD_LABELS = {"name": "nom", "phone": "téléphone", "email": "e-mail", "birthday": "anniversaire",
                "postal_code": "code postal", "is_student": "étudiant", "acquisition_source": "source"}


def init(db):
    global _db
    _db = db
    try:
        db.customer_changes.create_index([("tenant_id", 1), ("at", -1)])
        db.customer_changes.create_index([("customer_id", 1), ("at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _customer(token_data: TokenData, request: Optional[Request], customer_id: str) -> Dict[str, Any]:
    tid = token_data.tenant_id
    c = _db.customers.find_one({"id": customer_id, "tenant_id": tid}, {"_id": 0})
    if not c or c.get("deleted_at") or c.get("is_deleted"):
        raise HTTPException(status_code=404, detail="Client introuvable.")
    mine = S.customer_ids(S.resolve(token_data, request))
    if mine is not None and customer_id not in mine:
        raise HTTPException(status_code=403, detail="Ce client n'appartient pas à vos établissements.")
    return c


def _refresh_card(c: Dict[str, Any]) -> None:
    """The Wallet card follows (no alert on the phone: nothing for it to say)."""
    if not c.get("barcode_id"):
        return
    try:
        from features.wallet_passes import notify_passes
        notify_passes([c["barcode_id"]])
    except Exception as exc:                       # a refresh never stops a save
        print(f"customer edit: wallet refresh failed ({exc})")


def _tier(tid: str, visits: int, points: int, paid: float) -> str:
    """The scan's own rule: the owner's ladder (features/loyalty_card.tier_of)."""
    from features import loyalty_card as LC
    return LC.tier_of({"visits": visits, "points": points, "total_amount_paid": paid}, tid)


def _view(c: Dict[str, Any]) -> Dict[str, Any]:
    visits = int(c.get("visits") or 0)
    return {
        "id": c["id"], "name": c.get("name") or "", "phone": c.get("phone") or "", "email": c.get("email") or "",
        "birthday": c.get("birthday") or "", "postal_code": c.get("postal_code") or "",
        "is_student": bool(c.get("is_student")), "acquisition_source": c.get("acquisition_source") or "",
        "barcode_id": c.get("barcode_id"), "points": int(c.get("points") or 0), "visits": visits,
        "stamps_in_cycle": max(0, visits - int(c.get("visits_at_last_redemption") or 0)),
        "visits_at_last_redemption": int(c.get("visits_at_last_redemption") or 0),
        "tier": (c.get("tier") or "bronze").lower(),
    }


@router.get("/api/owner/clients/{customer_id}/fiche")
def get_fiche(customer_id: str, request: Request = None,
              token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    c = _customer(token_data, request, customer_id)
    rows = list(_db.customer_changes.find({"customer_id": customer_id, "tenant_id": token_data.tenant_id},
                                          {"_id": 0}).sort("at", -1).limit(20))
    from services import sources as SRC
    return {"client": _view(c),
            "sources": [{"key": k, "label": SRC.label(k)} for k in SRC.SIGNUP_SOURCES],
            "changes": [{"at": r["at"].isoformat() if isinstance(r.get("at"), datetime) else r.get("at"),
                         "kind": r["kind"], "text": r["text"], "by": r.get("by"), "reason": r.get("reason")}
                        for r in rows]}


class FicheIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    birthday: Optional[str] = None
    postal_code: Optional[str] = None
    is_student: Optional[bool] = None
    acquisition_source: Optional[str] = None


@router.put("/api/owner/clients/{customer_id}/fiche")
def save_fiche(customer_id: str, body: FicheIn, request: Request = None,
               token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    c = _customer(token_data, request, customer_id)
    new: Dict[str, Any] = {}
    if body.name is not None:
        new["name"] = CF.name(body.name)
    if body.phone is not None:
        new["phone"] = CF.phone(body.phone)
    if body.email is not None:
        new["email"] = CF.email(body.email).lower()
    if body.birthday is not None:
        new["birthday"] = CF.birthday(body.birthday)
    if body.postal_code is not None:
        new["postal_code"] = CF.postal_code(body.postal_code)
    if body.is_student is not None:
        new["is_student"] = bool(body.is_student)
    if body.acquisition_source is not None:
        from services import sources as SRC
        key = SRC.normalize(body.acquisition_source) if body.acquisition_source else None
        if body.acquisition_source and key not in SRC.SOURCES:
            raise HTTPException(status_code=400, detail="Source inconnue.")
        new["acquisition_source"] = key

    # the same person twice is how a second card appears: refuse
    if "phone" in new:
        digits = CF.phone_digits(new["phone"])
        for o in _db.customers.find({"tenant_id": tid, "id": {"$ne": customer_id}}, {"_id": 0, "phone": 1, "name": 1}):
            if CF.phone_digits(o.get("phone")) == digits:
                raise HTTPException(status_code=409, detail=f"Ce téléphone est déjà celui de {o.get('name') or 'un autre client'}.")
    if new.get("email"):
        clash = _db.customers.find_one({"tenant_id": tid, "id": {"$ne": customer_id},
                                        "email": {"$regex": f"^{_re_escape(new['email'])}$", "$options": "i"}},
                                       {"_id": 0, "name": 1})
        if clash:
            raise HTTPException(status_code=409, detail=f"Cet e-mail est déjà celui de {clash.get('name') or 'un autre client'}.")

    changed = [k for k, v in new.items() if (c.get(k) or ("" if k != "is_student" else False)) != (v if v is not None else "")]
    if not changed:
        return {"client": _view(c), "changed": []}
    _db.customers.update_one({"id": customer_id}, {"$set": {**{k: new[k] for k in changed}, "updated_at": _now()}})
    text = "Fiche modifiée : " + ", ".join(FIELD_LABELS[k] for k in changed)
    _db.customer_changes.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": customer_id,
                                     "customer_name": new.get("name") or c.get("name"), "kind": "profile",
                                     "fields": changed, "text": text, "by": token_data.email, "at": _now(),
                                     "store_ids": c.get("branch_ids") or ([c["branch_id"]] if c.get("branch_id") else None)})
    after = _db.customers.find_one({"id": customer_id}, {"_id": 0})
    if {"name"} & set(changed):
        _refresh_card(after)
    return {"client": _view(after), "changed": changed}


def _re_escape(s: str) -> str:
    import re
    return re.escape(s)


class AdjustIn(BaseModel):
    points: int = Field(0, ge=-100000, le=100000)
    visits: int = Field(0, ge=-1000, le=1000)            # tampons = visits in the current cycle
    reason: str = Field("", max_length=300)


@router.post("/api/owner/clients/{customer_id}/ajustement")
def adjust(customer_id: str, body: AdjustIn, request: Request = None,
           token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    """+/− points and stamps, with a compulsory reason. No visit is created
    (the shop's figures stay the scans'), only the card's counters move."""
    tid = token_data.tenant_id
    c = _customer(token_data, request, customer_id)
    reason = " ".join((body.reason or "").split())
    if not reason:
        raise HTTPException(status_code=400, detail="Indiquez la raison de l'ajustement.")
    if not body.points and not body.visits:
        raise HTTPException(status_code=400, detail="Rien à ajuster : indiquez des points ou des tampons.")
    points = int(c.get("points") or 0) + body.points
    visits = int(c.get("visits") or 0) + body.visits
    floor = int(c.get("visits_at_last_redemption") or 0)
    if points < 0:
        raise HTTPException(status_code=400, detail=f"Le client n'a que {int(c.get('points') or 0)} points.")
    if visits < floor:
        raise HTTPException(status_code=400, detail=f"Impossible de retirer plus de {int(c.get('visits') or 0) - floor} tampon(s) "
                                                    "sur la carte en cours.")
    upd = {"points": points, "visits": visits, "updated_at": _now(),
           "tier": _tier(tid, visits, points, float(c.get("total_amount_paid") or 0))}
    _db.customers.update_one({"id": customer_id}, {"$set": upd})
    parts = []
    if body.points:
        parts.append(f"{'+' if body.points > 0 else ''}{body.points} point{'s' if abs(body.points) > 1 else ''}")
    if body.visits:
        parts.append(f"{'+' if body.visits > 0 else ''}{body.visits} tampon{'s' if abs(body.visits) > 1 else ''}")
    text = "Ajustement manuel : " + " et ".join(parts)
    _db.customer_changes.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": customer_id,
                                     "customer_name": c.get("name"), "kind": "adjust", "points_delta": body.points,
                                     "visits_delta": body.visits, "reason": reason, "text": text,
                                     "by": token_data.email, "at": _now(),
                                     "before": {"points": int(c.get("points") or 0), "visits": int(c.get("visits") or 0)},
                                     "after": {"points": points, "visits": visits}})
    after = _db.customers.find_one({"id": customer_id}, {"_id": 0})
    _refresh_card(after)
    return {"client": _view(after), "text": text}
