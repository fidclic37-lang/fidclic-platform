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
                "birth_date": "date de naissance",
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
        "birth_date": c.get("birth_date") or "", "age": CF.age_of(c.get("birth_date")),
        "is_student": bool(c.get("is_student")), "acquisition_source": c.get("acquisition_source") or "",
        "barcode_id": c.get("barcode_id"), "points": int(c.get("points") or 0), "visits": visits,
        "stamps_in_cycle": max(0, visits - int(c.get("visits_at_last_redemption") or 0)),
        "visits_at_last_redemption": int(c.get("visits_at_last_redemption") or 0),
        "tier": (c.get("tier") or "bronze").lower(),
        # stamps added (or removed) by hand — on the card only, never visits (QA R5 F22)
        "stamps_adjusted": int(c.get("stamps_adjusted") or 0),
        # stamps moved from a paper card at a scan (once per customer)
        "paper_stamps": int(c.get("paper_stamps") or 0),
        "paper_stamps_at": c.get("paper_stamps_at"),
    }


@router.get("/api/owner/clients/{customer_id}/fiche")
def get_fiche(customer_id: str, request: Request = None,
              token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    c = _customer(token_data, request, customer_id)
    rows = list(_db.customer_changes.find({"customer_id": customer_id, "tenant_id": token_data.tenant_id},
                                          {"_id": 0}).sort("at", -1).limit(20))
    from services import sources as SRC
    # « Établissement d'origine » (multi-store, 2026-10-12): the stores this
    # account may move the client between — the owner all, an administrateur its own
    t = _db.tenants.find_one({"id": token_data.tenant_id}, {"_id": 0, "branches": 1}) or {}
    open_ = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    if token_data.role != "business_owner":
        from features import store_scope as S
        mine = set(S.resolve(token_data, requested="").allowed)
        movable = [b for b in open_ if b["id"] in mine] if (not c.get("branch_id") or c.get("branch_id") in mine) else []
    else:
        movable = open_
    return {"client": {**_view(c), "branch_id": c.get("branch_id")},
            "home_store": {"id": c.get("branch_id"),
                           "name": next((b.get("name") for b in open_ if b["id"] == c.get("branch_id")), None),
                           "choices": [{"id": b["id"], "name": b.get("name") or "Établissement"} for b in movable]
                           if len(open_) > 1 else []},
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
        # « 25/12/1990 » keeps the year (the age in Clients); « 25/12 » only the day
        b = CF.birth(body.birthday)
        new["birthday"] = b["birthday"]
        if b["birth_date"]:
            new["birth_date"] = b["birth_date"]
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


def _card_size(tid: str):
    """Stamps for a reward and visits per stamp (Carte de fidélité)."""
    tpl = _db.card_templates.find_one({"tenant_id": tid}) or {}
    return (max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1),
            max(int(tpl.get("visits_per_stamp", 1) or 1), 1))


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
    if points < 0:
        raise HTTPException(status_code=400, detail=f"Le client n'a que {int(c.get('points') or 0)} points.")
    # Stamps move THIS card's meter only (QA R5 F22, user 2026-10-09: « sirf
    # card ka meter »). A +1 stamp used to add a visit: the card and the CSV
    # read 3 visits while the history held 2. Visits, palier and figures stay
    # the scans'; the cycle marker moves instead (as for paper-card stamps).
    visits = int(c.get("visits") or 0)
    size, per = _card_size(tid)
    on_card = visits - int(c.get("visits_at_last_redemption") or 0)
    after_card = on_card + body.visits * per
    if after_card < 0:
        have = max(0, on_card) // per
        raise HTTPException(status_code=400, detail=f"Impossible de retirer plus de {have} tampon{'s' if have > 1 else ''} "
                                                    "sur la carte en cours.")
    if body.visits > 0 and after_card > size * per:
        have, room = on_card // per, max(0, size * per - on_card) // per
        raise HTTPException(status_code=400, detail=(
            f"La carte en cours a {have} tampon{'s' if have > 1 else ''} sur {size} : {room} au maximum."
            if room else f"La carte en cours est complète ({size}/{size}) : remettez d'abord la récompense."))
    upd = {"points": points, "updated_at": _now(),
           "tier": _tier(tid, visits, points, float(c.get("total_amount_paid") or 0))}
    inc = {}
    if body.visits:
        inc = {"visits_at_last_redemption": -body.visits * per, "stamps_adjusted": body.visits}
    _db.customers.update_one({"id": customer_id}, {"$set": upd, **({"$inc": inc} if inc else {})})
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
                                     "before": {"points": int(c.get("points") or 0), "stamps": on_card // per},
                                     "after": {"points": points, "stamps": after_card // per}})
    after = _db.customers.find_one({"id": customer_id}, {"_id": 0})
    _refresh_card(after)
    return {"client": _view(after), "text": text}
