"""
« Enregistrer une visite » — what the till needs to know about one card.

Status: ✅ Implemented.
Mounts at: /api/owner/scan/card
Collections: reads `customers`, `card_templates`, `campaigns`, `offer_uses`,
             `defi_rewards`, `rewards_earned`; writes nothing.

WHY A SECOND ENDPOINT
    /api/owner/scan/preview answers the old till: the stamps on the card and
    whether a paper card was already moved. The page now shows the client as
    the mockups do — balance, palier, next rung, contact, and everything that
    can be applied to this visit — so it needs one answer carrying all of it,
    in one round trip, before the staff touches anything.

ONE CHOICE, NOT SEVERAL
    Offers and rewards come back in a single `applicables` list. The page lets
    exactly one be picked (user, 2026-10-13): « jitne bhi available rewards ho
    woh sab dikhe, lekin choose unme se koi ek hi kar paaye ». Each entry says
    whether it can be used now; a customer one stamp short sees the reward
    announced for the next visit and cannot pick it (user, 2026-11-04).

WHAT IT DOES NOT DECIDE
    The card reward is earned by the card cycle — visits, through
    `visits_at_last_redemption` — on every programme, points included. Points
    are a balance and a palier; nothing here spends them. That is the engine
    as it stands (server.redeem_reward), and this endpoint reports it rather
    than inventing a second rule.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_role, TokenData

router = APIRouter(tags=["scan-page"])
_db = None

TILL = ["business_owner", "administrateur", "manager", "staff", "membre"]
# Sectors whose catalogue holds things one *does*, not things one sells.
SERVICE_SECTORS = {"salon", "spa", "gym"}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
    return v if isinstance(v, str) and v else None


def wording(sector: Optional[str]) -> Dict[str, str]:
    """A salon performs services, a bakery sells products. The till says the
    word the merchant would say."""
    if (sector or "").strip().lower() in SERVICE_SECTORS:
        return {"one": "service", "many": "services", "picker": "Choisir un service",
                "picker_sub": "Sélectionnez la prestation réalisée.", "field": "Service réalisé",
                "catalogue": "Catalogue services", "search": "Rechercher un service…"}
    return {"one": "produit", "many": "produits", "picker": "Choisir un produit",
            "picker_sub": "Sélectionnez ce qui a été vendu.", "field": "Produit du catalogue",
            "catalogue": "Catalogue produits", "search": "Rechercher un produit…"}


def _balance(cust: Dict[str, Any], tpl: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """The one number the card shows, and the next rung of the ladder.

    A points card counts points; a stamp card counts the stamps of the card in
    hand — never lifetime visits, which would re-announce a reward for ever
    (the cycle marker is what resets, see server.redeem_reward)."""
    from features import loyalty_card as LC
    programme = LC._programme(tpl)
    points = LC._is_points(programme)
    tiers = LC.tiers_for(tenant_id)
    if points:
        value = int(cust.get("points") or 0)
        unit = "€" if programme == "cashback" else "points"
        if programme == "cashback":
            value = round(value / 100, 2)                 # a cashback balance is kept in cents
    else:
        per = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
        size = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
        on_card = max(0, int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0))
        value, unit = min(on_card // per, size), "tampons"
    # The rung above the customer: what the card is working towards.
    nxt = next((t for t in tiers if t["min"] > value), None)
    cur = [t for t in tiers if t["min"] <= value]
    tier = cur[-1] if cur else (tiers[0] if tiers else None)
    floor = tier["min"] if tier else 0
    span = (nxt["min"] - floor) if nxt else 0
    return {
        "programme": programme, "value": value, "unit": unit,
        "tier_label": f"Niveau {tier['label']}" if tier else None,
        "next_at": nxt["min"] if nxt else None,
        "next_label": (f"Prochain palier : {nxt['min']} {unit}" if nxt
                       else "Palier le plus haut atteint"),
        "pct": round((value - floor) / span * 100) if span > 0 else (100 if nxt is None else 0),
    }


def _reward_label(tpl: Dict[str, Any], tiers: List[Dict[str, Any]]) -> str:
    """What a full card gives: the card's own reward, as the card and the pass
    say it, and as a banked one is named. Never the ladder's top rung: a palier's
    advantage is not what filling the card gives."""
    return (tpl.get("reward_description") or "").strip() or "Récompense fidélité"


def _card_reward(cust: Dict[str, Any], tpl: Dict[str, Any], tiers: List[Dict[str, Any]],
                 unit: str) -> Optional[Dict[str, Any]]:
    """The loyalty card's own reward: a full card, or one already waiting.

    `after_visit`: this scan will fill the card, so the reward is for the NEXT
    visit — shown, not to be picked (user, 2026-11-04). The visit about to be
    written counts as that next visit for whatever is already full or waiting
    (features/scan_page is read-only — server.scan does that part)."""
    from features import loyalty_card as LC
    waiting = _db.rewards_earned.count_documents({"customer_id": cust["id"], "status": "pending"})
    label = _reward_label(tpl, tiers)
    if LC._is_points(LC._programme(tpl)):
        # A points card buys its reward with points (2026-10-14). What this
        # visit is about to earn is not known here, so « after_visit » is left
        # to the stamp card, where one visit is always one step.
        price = max(int(tpl.get("reward_points") or 0), 0)
        balance = int(cust.get("points") or 0)
        if waiting == 0 and (not price or balance < price):
            return None                            # (a reward already earned is never lost, price or none)
        return {"id": "card", "kind": "card", "tone": "reward", "title": label,
                "sub": f"{price} points" if price else None, "discount_type": None, "discount_value": None,
                "available": True, "after_visit": False}
    per = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
    size = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1)
    need = size * per
    on_card = max(0, int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0))
    now_ok = on_card >= need or waiting > 0
    after_ok = (not now_ok) and (on_card + 1) >= need
    if not (now_ok or after_ok):
        return None
    return {"id": "card", "kind": "card", "tone": "reward", "title": label,
            "sub": f"{size} {unit}" if unit != "€" else None,
            "discount_type": None, "discount_value": None,
            "available": bool(now_ok), "after_visit": bool(after_ok)}


def next_visit_reward(tenant_id: str, customer_id: str) -> Optional[Dict[str, Any]]:
    """« Next visit pr reward » (user, 2026-11-05): the card reward the till can
    hand over at this client's next visit, read after today's visit is written.
    The same reading the till's list makes (`_card_reward`), so what is said here
    is what is offered there; a cagnotte's balance alone is not announced. `count`:
    full cards or balance waiting, of which one goes per visit. `earned_today`:
    this visit is the one that got there."""
    from features import store_cards as SC
    cust = _db.customers.find_one({"id": customer_id, "tenant_id": tenant_id}, {"_id": 0})
    if not cust:
        return None
    # the store this visit may just have given a client who had none
    with SC.store(tenant_id, cust.get("branch_id") or SC.store_for(tenant_id)):
        return _next_visit_reward(tenant_id, cust)


def _next_visit_reward(tenant_id: str, cust: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from features import loyalty_card as LC
    customer_id = cust["id"]
    tpl = _db.card_templates.find_one({"tenant_id": tenant_id}) or {}
    programme = LC._programme(tpl)
    points = LC._is_points(programme)
    row = _card_reward(cust, tpl, LC.tiers_for(tenant_id), "points" if points else "tampons")
    if not row or not row["available"]:
        return None
    rows = list(_db.rewards_earned.find({"customer_id": customer_id, "status": "pending"},
                                        {"_id": 0, "available_after_visits": 1}))
    if programme == "cashback" and not rows:       # a cagnotte: euros to spend, no reward to announce
        return None
    visits = int(cust.get("visits") or 0)
    today = any(r.get("available_after_visits") is not None and int(r["available_after_visits"]) >= visits for r in rows)
    if points:
        price = max(int(tpl.get("reward_points") or 0), 0)
        balance = int(cust.get("points") or 0)
        full = balance // price if price and programme != "cashback" else 0
        today = today or (full > 0 and balance - int(cust.get("points_last_earned") or 0) < price)
    else:
        need = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1) * max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
        on_card = max(0, visits - int(cust.get("visits_at_last_redemption") or 0))
        full = 1 if on_card >= need else 0
        today = today or (full > 0 and on_card - int(cust.get("last_scan_units") or 0) < need)
    return {"title": row["title"], "count": len(rows) + full, "programme": programme, "earned_today": bool(today)}


def reward_ahead(tenant_id: str, cust: Dict[str, Any], tpl: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """How far this client is from the card's reward, for the till to warn before
    the visit is written: « Plusieurs personnes », the amount and paper stamps are
    typed there. None when a reward is already there, or the card has none."""
    from features import loyalty_card as LC
    programme = LC._programme(tpl)
    points = LC._is_points(programme)
    tiers = LC.tiers_for(tenant_id)
    row = _card_reward(cust, tpl, tiers, "points" if points else "tampons")
    if row and row["available"]:
        return None
    title = _reward_label(tpl, tiers)
    if programme == "stamps":
        per = max(int(tpl.get("visits_per_stamp", 1) or 1), 1)
        need = max(int(tpl.get("reward_threshold_stamps", 10) or 10), 1) * per
        on_card = max(0, int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0))
        return {"title": title, "programme": programme, "need_visits": max(0, need - on_card), "per_stamp": per}
    price = max(int(tpl.get("reward_points") or 0), 0)
    if programme == "cashback" or not price:
        return None
    short = max(0, price - int(cust.get("points") or 0))
    if programme == "points_euro" or ((tpl.get("points_mode") or "").lower() == "per_euro" and programme != "points_visit"):
        return {"title": title, "programme": programme, "need_points": short, "per_euro": float(tpl.get("points_per_euro") or 10)}
    return {"title": title, "programme": programme, "need_points": short, "per_visit": int(tpl.get("points_per_visit", 10) or 10)}


def applicables(tenant_id: str, cust: Dict[str, Any], tpl: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Everything that can be put on this visit — offers first, then rewards.

    The page shows them all and lets one be chosen; nothing here enforces that,
    the scan does (server.scan refuses a second one)."""
    import server as core
    from features import loyalty_card as LC
    out: List[Dict[str, Any]] = []
    for o in core._offers_active_for(tenant_id, cust["id"]):
        if o.get("used"):                       # « Offre utilisée » — once per client
            continue
        # The helper answers what the till reads; the figures behind « -20 % »
        # live on the campaign itself, and the page needs them to take the
        # discount off the amount.
        camp = _db.campaigns.find_one({"id": o.get("id")}, {"_id": 0, "offer": 1}) or {}
        offer = camp.get("offer") or {}
        out.append({"id": f"offer:{o.get('id')}", "kind": "offer", "tone": "offer",
                    "title": o.get("label") or o.get("title") or "Offre",
                    "sub": o.get("terms") or o.get("title"),
                    "discount_type": offer.get("discount_type"),
                    "discount_value": offer.get("discount_value"),
                    "available": True, "after_visit": False})
    tiers = LC.tiers_for(tenant_id)
    unit = "points" if LC._is_points(LC._programme(tpl)) else "tampons"
    card = _card_reward(cust, tpl, tiers, unit)
    if card:
        out.append(card)
    for r in core._defi_rewards_of(cust["id"]):
        out.append({"id": f"defi:{r.get('id')}", "kind": "defi", "tone": "reward",
                    "title": r.get("reward") or r.get("title") or "Récompense",
                    "sub": r.get("defi_name") or r.get("sub"),
                    "discount_type": None, "discount_value": None,
                    "available": True, "after_visit": False})
    return out


def _habit(tid: str, cust: Dict[str, Any]) -> Optional[str]:
    from features import client_brain as CB
    b = cust.get("brain")
    if not CB.current(b):
        b = CB.refresh(tid, cust.get("id")) or {}
    return CB.caisse_line(b)


def _multi(tenant: Dict[str, Any], tpl: Dict[str, Any]) -> Dict[str, Any]:
    from features import multi_person as MP
    from features import loyalty_card as LC
    s = MP.settings(tenant, tpl)
    return {"enabled": s["enabled"], "max": s["max"], "programme": LC._programme(tpl)}


@router.get("/api/owner/scan/card")
def card(barcode: str = Query(..., min_length=2, max_length=64),
         token_data: TokenData = Depends(require_role(TILL))):
    import server as core
    code = (barcode or "").strip().upper()
    cust = _db.customers.find_one({"tenant_id": token_data.tenant_id, "barcode_id": code}, {"_id": 0})
    if not cust:
        raise HTTPException(status_code=404, detail="Aucun client trouvé avec ce code.")
    if cust.get("deleted_at"):
        # said as soon as the card is read, not after the whole visit is typed
        # (QA R7: the till identified a deleted client, the final save refused)
        raise HTTPException(status_code=410, detail=core.DELETED_CARD_MSG)
    # the client's own store's card, as the scan reads it: at another store's till
    # the list named that till's reward, and the scan then counted the client's own
    from features import store_cards as SC
    SC.set_for_customer(cust)
    tpl = _db.card_templates.find_one({"tenant_id": token_data.tenant_id}) or {}
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}, {"_id": 0, "sector": 1, "activity_key": 1}) or {}

    rule = core._card_rule(token_data.tenant_id)
    on_card = max(0, int(cust.get("visits") or 0) - int(cust.get("visits_at_last_redemption") or 0))
    paper_done = cust.get("paper_stamps") is not None
    return {
        "customer": {
            "id": cust.get("id"), "barcode_id": cust.get("barcode_id"),
            "name": cust.get("name") or "", "phone": cust.get("phone") or "",
            "email": cust.get("email") or "", "since": _iso(cust.get("created_at")),
            "visits": int(cust.get("visits") or 0),
            # one line for the staff (FidClic IA, 2026-10-24): « D'habitude : Coupe + Barbe · ~25 € · … »
            "habit": _habit(token_data.tenant_id, cust),
        },
        "balance": _balance(cust, tpl, token_data.tenant_id),
        "applicables": applicables(token_data.tenant_id, cust, tpl),
        "reward_ahead": reward_ahead(token_data.tenant_id, cust, tpl),
        "paper": {
            # Room left on the card in hand, and only ever once per client.
            "max": 0 if paper_done else max(0, rule["visits"] - on_card) // rule["per_stamp"],
            "done": paper_done,
            "count": int(cust.get("paper_stamps") or 0) if paper_done else 0,
            "message": core._paper_done_message(cust) if paper_done else None,
        },
        "wording": wording(tenant.get("sector")),
        # « Plusieurs personnes » (user, 2026-10-30): whether the till offers it,
        # how many at most, and the programme (what « × N » multiplies)
        "multi": _multi(tenant, tpl),
    }
