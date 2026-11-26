"""
Clients › « Historique d'achats » › Modifier / Supprimer un achat (user,
2026-11-26: « koi bhi business apne clients ka products purchase edit kar
sake, catalogue se choose kar sake — accurate data ke liye »).

WHAT THE BUSINESS CAN CORRECT ON ONE PURCHASE (a visit)
    • The products: picked from ITS OWN catalogue, with quantities. The server
      prices every line from the catalogue — a browser cannot send a price.
    • The amount: the catalogue's total, or the till's own figure when the
      business says so (« montant manuel » — a discount, a rounding).
    • The day and the hour. Never in the future, never before 2000.
    • Or the whole purchase can be deleted: it is kept apart
      (visits_cancelled) and what it gave the card is taken back
      (features/merchant_api._undo_on_card — the same rule as an API refund).

WHAT DOES NOT MOVE ON AN EDIT
    The tampons and points the visit gave (the scan's rule at the time). The
    client's total spent follows the amount; the palier is re-read from it.

WHO
    The owner, administrateurs and managers — a manager only for the clients
    of their establishments (features/store_scope). Staff cannot.
    Every change goes to the client's history (customer_changes), with who
    and why, and to the audit log; the Wallet card refreshes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData

router = APIRouter(tags=["clients"])
_db = None

MAX_LINES = 50
MAX_QTY = 999
MAX_AMOUNT = 100000.0                 # the merchant API's ceiling (merchant_api.VisitIn)
FUTURE_SKEW = timedelta(minutes=10)   # a phone's clock a little ahead
OLDEST = datetime(2000, 1, 1, tzinfo=timezone.utc)
PARIS = ZoneInfo("Europe/Paris")


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def parse_visit_time(value: Any, now: Optional[datetime] = None) -> Optional[datetime]:
    """An ISO date from the editor → aware UTC. None when nothing was sent.
    Refuses garbage, the future (beyond a clock's skew) and anything before 2000."""
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("date")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError("date")
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    d = d.astimezone(timezone.utc)
    now = now or _now()
    if d > now + FUTURE_SKEW:
        raise ValueError("future")
    if d < OLDEST:
        raise ValueError("too_old")
    return d


def eur(x: float) -> str:
    """« 1 234,50 € » — the French figure the history shows."""
    s = f"{float(x or 0):,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} €"


def _day(d: Optional[datetime]) -> str:
    d = _aware(d)
    return d.astimezone(PARIS).strftime("%d/%m/%Y") if d else "—"


def _lines_key(lines: List[Dict[str, Any]]) -> List[tuple]:
    return [(str(x.get("item_id") or ""), int(x.get("qty") or 0)) for x in lines or []]


def _catalogue(tid: str) -> Dict[str, Dict[str, Any]]:
    doc = _db.tenant_catalog.find_one({"tenant_id": tid}, {"_id": 0, "items": 1}) or {}
    return {str(it.get("id")): it for it in (doc.get("items") or []) if it.get("id")}


def _resolve_lines(tid: str, items: List[Any]) -> tuple[float, List[Dict[str, Any]]]:
    """[{item_id, qty}] → the catalogue's lines and total. Anything the
    catalogue does not know, or a quantity out of 1..999, is refused: the
    business would otherwise believe a line was kept."""
    if len(items) > MAX_LINES:
        raise HTTPException(status_code=400, detail=f"Au plus {MAX_LINES} lignes par achat.")
    cat = _catalogue(tid)
    total, lines = 0.0, []
    for row in items:
        if not isinstance(row, dict):
            raise HTTPException(status_code=400, detail="Ligne invalide.")
        item_id = str(row.get("item_id") or row.get("id") or "").strip()
        qty = row.get("qty", 1)
        if isinstance(qty, bool) or not isinstance(qty, (int, float)) or int(qty) != qty:
            raise HTTPException(status_code=400, detail="La quantité doit être un nombre entier.")
        qty = int(qty)
        if qty < 1 or qty > MAX_QTY:
            raise HTTPException(status_code=400, detail=f"La quantité doit être entre 1 et {MAX_QTY}.")
        it = cat.get(item_id)
        if not it:
            raise HTTPException(status_code=400, detail="Ce produit n'est pas dans votre catalogue.")
        price = round(float(it.get("price") or 0), 2)
        line_total = round(qty * price, 2)
        total += line_total
        lines.append({"item_id": item_id, "name": it.get("name") or "Produit", "price": price,
                      "qty": qty, "line_total": line_total})
    return round(total, 2), lines


def _visit(tid: str, customer_id: str, visit_id: str) -> Dict[str, Any]:
    v = _db.visits.find_one({"id": visit_id, "tenant_id": tid, "customer_id": customer_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Achat introuvable.")
    return v


def _after_customer(tid: str, cid: str, time_changed: bool) -> Dict[str, Any]:
    """Re-read the client's total, last visit and palier after a change."""
    from features import customer_edit as CE
    c = _db.customers.find_one({"id": cid, "tenant_id": tid}, {"_id": 0}) or {}
    sets: Dict[str, Any] = {"updated_at": _now()}
    if float(c.get("total_amount_paid") or 0) < 0:
        sets["total_amount_paid"] = 0.0
        c["total_amount_paid"] = 0.0
    if time_changed:
        last = _db.visits.find_one({"tenant_id": tid, "customer_id": cid}, {"_id": 0, "visit_time": 1},
                                   sort=[("visit_time", -1)])
        if last and last.get("visit_time"):
            sets["last_visit_date"] = last["visit_time"]
    sets["tier"] = CE._tier(tid, int(c.get("visits") or 0), int(c.get("points") or 0),
                            float(c.get("total_amount_paid") or 0))
    _db.customers.update_one({"id": cid, "tenant_id": tid}, {"$set": sets})
    c.update(sets)
    return c


def _client_out(c: Dict[str, Any]) -> Dict[str, Any]:
    lv = _aware(c.get("last_visit_date"))
    return {"id": c.get("id"), "visits": int(c.get("visits") or 0),
            "total_amount_paid": round(float(c.get("total_amount_paid") or 0), 2),
            "tier": (c.get("tier") or "bronze").lower(), "last_visit": lv.isoformat() if lv else None}


def _follow_up(tid: str, c: Dict[str, Any]) -> None:
    """The Wallet card and FidClic IA follow; neither ever stops a save."""
    try:
        from features import customer_edit as CE
        CE._refresh_card(c)
    except Exception as e:
        print(f"visit edit: wallet refresh failed (non-fatal): {e}")
    try:
        from features import client_brain as CB
        CB.refresh(tid, c["id"])
    except Exception as e:
        print(f"visit edit: client brain not refreshed (non-fatal): {e}")


class PurchaseIn(BaseModel):
    items: Optional[List[Dict[str, Any]]] = None     # [{item_id, qty}] — replaces the lines
    amount_paid: Optional[float] = None
    amount_manual: bool = False                      # the till's figure over the catalogue's total
    visit_time: Optional[str] = None                 # ISO 8601
    reason: Optional[str] = Field(None, max_length=300)


@router.put("/api/owner/clients/{customer_id}/purchases/{visit_id}")
def edit_purchase(customer_id: str, visit_id: str, body: PurchaseIn, request: Request = None,
                  token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"],
                                                               partial_ok=True))):
    from features import customer_edit as CE
    import server as core
    tid = token_data.tenant_id
    c = CE._customer(token_data, request, customer_id)
    v = _visit(tid, customer_id, visit_id)

    sets: Dict[str, Any] = {}
    changed: List[str] = []
    old_lines = list(v.get("items") or [])
    old_amount = round(float(v.get("amount_paid") or 0), 2)
    old_time = _aware(v.get("visit_time"))

    # -- products -----------------------------------------------------------
    new_lines, cat_total = old_lines, None
    if body.items is not None:
        cat_total, new_lines = _resolve_lines(tid, body.items)
        if not new_lines and not (body.amount_manual and body.amount_paid is not None):
            raise HTTPException(status_code=400, detail="Ajoutez au moins un produit, ou indiquez un montant.")
        if _lines_key(new_lines) != _lines_key(old_lines):
            sets["items"] = new_lines
            changed.append("items")

    # -- amount -------------------------------------------------------------
    new_amount, manual = old_amount, bool(v.get("amount_manual"))
    if body.amount_manual or (body.items is None and body.amount_paid is not None):
        if body.amount_paid is None:
            raise HTTPException(status_code=400, detail="Indiquez le montant.")
        a = float(body.amount_paid)
        if a != a or a < 0 or a > MAX_AMOUNT:
            raise HTTPException(status_code=400, detail=f"Le montant doit être entre 0 et {int(MAX_AMOUNT)} €.")
        new_amount, manual = round(a, 2), True
    elif body.items is not None:
        new_amount, manual = cat_total, False
    if new_amount != old_amount:
        sets["amount_paid"] = new_amount
        changed.append("amount")
    if manual != bool(v.get("amount_manual")) or (manual and "amount" in changed):
        sets["amount_manual"] = manual

    # -- date and hour --------------------------------------------------------
    new_time = old_time
    if body.visit_time is not None and body.visit_time != "":
        try:
            new_time = parse_visit_time(body.visit_time)
        except ValueError as e:
            msg = {"future": "La date ne peut pas être dans le futur.",
                   "too_old": "La date est trop ancienne."}.get(str(e), "Date invalide.")
            raise HTTPException(status_code=400, detail=msg)
        if new_time != old_time:
            sets["visit_time"] = new_time
            changed.append("visit_time")

    if not changed:
        return {"row": CE.purchase_row(tid, v), "changed": [], "client": _client_out(c)}

    # -- write the visit, remembering what it was -----------------------------
    now = _now()
    sets.update({"edited_at": now, "edited_by": token_data.email})
    reason = " ".join((body.reason or "").split()) or None
    before = {"items": old_lines, "amount_paid": old_amount, "visit_time": old_time, "amount_manual": bool(v.get("amount_manual"))}
    _db.visits.update_one({"id": visit_id, "tenant_id": tid},
                          {"$set": sets, "$push": {"edits": {"at": now, "by": token_data.email, "reason": reason,
                                                              "before": before, "changed": changed}}})

    # -- the client follows ------------------------------------------------------
    delta = round(new_amount - old_amount, 2)
    if delta:
        _db.customers.update_one({"id": customer_id, "tenant_id": tid}, {"$inc": {"total_amount_paid": delta}})
    after_c = _after_customer(tid, customer_id, "visit_time" in changed)

    # -- history + audit -----------------------------------------------------------
    parts = []
    if "amount" in changed:
        parts.append(f"{eur(old_amount)} → {eur(new_amount)}")
    if "items" in changed:
        parts.append("produits : " + (", ".join(f"{x['qty']} × {x['name']}" for x in new_lines) or "aucun"))
    if "visit_time" in changed:
        parts.append(f"date : {_day(old_time)} → {_day(new_time)}")
    text = f"Achat du {_day(old_time)} modifié : " + " · ".join(parts)
    _db.customer_changes.insert_one({
        "id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": customer_id, "customer_name": c.get("name"),
        "kind": "visit_edited", "visit_id": visit_id, "fields": changed, "text": text, "reason": reason,
        "by": token_data.email, "at": now,
        "before": {"amount_paid": old_amount, "items": _lines_key(old_lines), "visit_time": old_time},
        "after": {"amount_paid": new_amount, "items": _lines_key(new_lines), "visit_time": new_time},
        "store_ids": [v["branch_id"]] if v.get("branch_id") else None,
    })
    try:
        core.log_audit("visit.edit", actor=token_data.email, actor_type="user", tenant_id=tid, target=visit_id,
                       request=request, meta={"customer_id": customer_id, "changed": changed,
                                              "amount_before": old_amount, "amount_after": new_amount})
    except Exception as e:
        print(f"visit edit: audit not written (non-fatal): {e}")
    _follow_up(tid, after_c)
    return {"row": CE.purchase_row(tid, _visit(tid, customer_id, visit_id)), "changed": changed,
            "client": _client_out(after_c), "text": text}


class CancelIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)


class _Caller:
    """What merchant_api._undo_on_card reads of an API caller — here the account."""
    def __init__(self, tenant_id: str, email: str):
        self.tenant_id, self.key_name, self.key_id = tenant_id, email, email


@router.post("/api/owner/clients/{customer_id}/purchases/{visit_id}/cancel")
def cancel_purchase(customer_id: str, visit_id: str, body: Optional[CancelIn] = None, request: Request = None,
                    token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"],
                                                                 partial_ok=True))):
    from features import customer_edit as CE, merchant_api as MA
    import server as core
    tid = token_data.tenant_id
    body = body or CancelIn()
    c = CE._customer(token_data, request, customer_id)
    v = _visit(tid, customer_id, visit_id)
    if v.get("paper_stamps"):
        raise HTTPException(status_code=409, detail="Cet achat a transféré une carte papier : ajustez les tampons "
                                                    "depuis « Ajuster » plutôt que de le supprimer.")
    claimed = _db.visits.find_one_and_delete({"id": visit_id, "tenant_id": tid, "customer_id": customer_id})
    if not claimed:
        raise HTTPException(status_code=404, detail="Achat introuvable.")
    claimed.pop("_id", None)
    reason = " ".join((body.reason or "").split()) or None
    now = _now()
    kept = {**claimed, "cancelled_at": now, "cancel_reason": reason, "cancelled_by": token_data.email,
            "cancel_source": "owner"}
    _db.visits_cancelled.insert_one(dict(kept))          # kept apart at once: a purchase is never just lost
    undone = MA._undo_on_card(kept, _Caller(tid, token_data.email))
    _db.visits_cancelled.update_one({"tenant_id": tid, "id": visit_id}, {"$set": undone})

    # the row _undo_on_card wrote reads « Passage annulé (API) »: say what happened here
    amount = round(float(claimed.get("amount_paid") or 0), 2)
    text = f"Achat du {_day(claimed.get('visit_time'))} supprimé : {eur(amount)}"
    row = _db.customer_changes.find_one({"tenant_id": tid, "customer_id": customer_id, "kind": "visit_cancelled",
                                         "by": f"api:{token_data.email}"}, {"_id": 0, "id": 1}, sort=[("at", -1)])
    fix = {"kind": "visit_deleted", "by": token_data.email, "text": text, "reason": reason, "visit_id": visit_id,
           "store_ids": [claimed["branch_id"]] if claimed.get("branch_id") else None}
    if row:
        _db.customer_changes.update_one({"id": row["id"]}, {"$set": fix})
    else:
        _db.customer_changes.insert_one({"id": str(uuid.uuid4()), "tenant_id": tid, "customer_id": customer_id,
                                         "customer_name": c.get("name"), "at": now, "visits_delta": -1, **fix})
    try:
        core.log_audit("visit.delete", actor=token_data.email, actor_type="user", tenant_id=tid, target=visit_id,
                       request=request, meta={"customer_id": customer_id, "amount": amount, "reason": reason})
    except Exception as e:
        print(f"visit delete: audit not written (non-fatal): {e}")
    after_c = _db.customers.find_one({"id": customer_id, "tenant_id": tid}, {"_id": 0}) or {}
    _follow_up(tid, after_c)
    return {"deleted": visit_id, "reversed": undone.get("reversed") or {}, "not_reversed": undone.get("not_reversed") or [],
            "client": _client_out(after_c), "text": text}
