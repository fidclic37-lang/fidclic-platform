"""
Referral Program — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/owner/referrals/* and /api/customer/referral/*
Collections: `referral_config`, `referral_redemptions`

THE ONLY WAY IN IS AN EXISTING CUSTOMER'S OWN CARD
    There is no referral link and no second QR to share. The card a customer
    already carries *is* the invitation:

      1. A stranger points their camera at a customer's loyalty card.
      2. The QR is that card's public URL, so the phone opens it.
      3. The phone has no card of its own → it is sent to the signup form,
         which says who invited them.
      4. They sign up. The referral is recorded, PENDING — no points yet, and
         the new client's source is « Parrainage ».
      5. From the visit the owner chose (the 1st by default), parrain and
         filleul are credited — once, at every visit, or a first amount then
         another at each later visit (« Quand créditer », user 2026-10-08).

    Nothing to print, nothing to copy, nothing to explain to a customer.

WHY POINTS WAIT FOR THE FIRST VISIT
    A signup costs nothing to fake. A visit does not. Crediting at signup
    would let anyone mint points from a phone; crediting at the first real
    purchase means the programme only ever pays for a customer who came.

SELF-REFERRAL
    The parrain's own phone keeps its card, so it never reaches the signup
    form. If they land there anyway (new phone, cleared browser), the signup
    dedupes them on their phone number and returns their existing card — no
    new customer, so no referral.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import re
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_role
from features import store_scope as S

# The Parrainage page is read by the owner, administrateurs and managers — a
# parrainage belongs to the establishments of the client it brought in. The
# programme's settings are the shop's: the owner's.
READERS = ["business_owner", "administrateur", "manager"]
from models import TokenData

router = APIRouter(tags=["referrals"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.referral_config.create_index("tenant_id", unique=True)
        db.referral_redemptions.create_index([("tenant_id", 1), ("referee_customer_id", 1)], unique=True)
    except Exception:
        pass


REWARD_MODES = ("once", "every", "first_then")
# What each side receives (user, 2026-10-13): the owner chooses, for the
# parrain and for the filleul separately, points, tampons or an offer of
# their own (« 1 café offert ») handed over at the till — whatever the
# programme of the card.
REWARD_KINDS = ("points", "stamps", "offer")
SIDES = ("referrer", "referee")
OFFER_MAX = 80


# ---------- Models ----------
class ReferralConfig(BaseModel):
    tenant_id: Optional[str] = None
    enabled: bool = False
    # Nothing until the owner saves an amount (user, 2026-10-20, QA R7 F41:
    # « default 0 hi rakho dono ka… jo business owner save krega woh hi »)
    referrer_reward_points: int = 0
    referee_reward_points: int = 0
    minimum_visits_to_earn: int = 1   # referee must reach this many visits before referrer is credited
    # When both are credited (user, 2026-10-08), from that visit on:
    #   once        — once, at that visit
    #   every       — at that visit and every visit after it
    #   first_then  — the points above at that visit, then *_next at each later one
    reward_mode: str = "once"
    referrer_reward_points_next: int = 0
    referee_reward_points_next: int = 0
    # each side's kind of reward, and its amount for tampons / words for an offer
    referrer_reward_kind: str = "points"
    referee_reward_kind: str = "points"
    referrer_reward_stamps: int = 0
    referee_reward_stamps: int = 0
    referrer_reward_stamps_next: int = 0
    referee_reward_stamps_next: int = 0
    referrer_reward_offer: str = ""
    referee_reward_offer: str = ""
    referrer_reward_offer_next: str = ""
    referee_reward_offer_next: str = ""
    referrer_message: str = "Thanks for sharing! You earned {points} points."
    referee_message: str = "Welcome via a friend! Here are {points} points to start."



# ---------- Owner endpoints ----------
@router.get("/api/owner/referrals/config")
def get_config(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    doc = _db.referral_config.find_one({"tenant_id": token_data.tenant_id})
    if not doc:
        return ReferralConfig(tenant_id=token_data.tenant_id).model_dump()
    doc.pop("_id", None)
    return doc


@router.put("/api/owner/referrals/config")
def update_config(
    config: ReferralConfig,
    token_data: TokenData = Depends(require_role(["business_owner"])),
):
    config.tenant_id = token_data.tenant_id
    if config.reward_mode not in REWARD_MODES:
        raise HTTPException(status_code=400, detail="Mode de crédit inconnu.")
    for f in ("referrer_reward_points", "referee_reward_points",
              "referrer_reward_points_next", "referee_reward_points_next"):
        setattr(config, f, max(0, min(10000, int(getattr(config, f) or 0))))
    for side, who in (("referrer", "parrain"), ("referee", "filleul")):
        if getattr(config, f"{side}_reward_kind") not in REWARD_KINDS:
            raise HTTPException(status_code=400, detail="Type de récompense inconnu.")
        for f in (f"{side}_reward_stamps", f"{side}_reward_stamps_next"):
            setattr(config, f, max(0, min(50, int(getattr(config, f) or 0))))
        for f in (f"{side}_reward_offer", f"{side}_reward_offer_next"):
            setattr(config, f, " ".join(str(getattr(config, f) or "").split())[:OFFER_MAX])
        if config.enabled and getattr(config, f"{side}_reward_kind") == "offer" and not getattr(config, f"{side}_reward_offer"):
            raise HTTPException(status_code=400, detail=f"Décrivez l'offre du {who} (par exemple « 1 café offert »).")
    config.minimum_visits_to_earn = max(1, min(20, int(config.minimum_visits_to_earn or 1)))
    payload = config.model_dump()
    _db.referral_config.update_one(
        {"tenant_id": token_data.tenant_id},
        {"$set": payload},
        upsert=True,
    )
    return payload


@router.get("/api/owner/referrals/leaderboard")
def leaderboard(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """Top customers by successful referrals."""
    pipeline = [
        {"$match": {"tenant_id": token_data.tenant_id}},
        {"$group": {"_id": "$referrer_customer_id", "successful_referrals": {"$sum": 1}}},
        {"$sort": {"successful_referrals": -1}},
        {"$limit": 50},
    ]
    rows = list(_db.referral_redemptions.aggregate(pipeline))
    out = []
    for row in rows:
        cust = _db.customers.find_one({"id": row["_id"]}) or {}
        out.append({
            "customer_id": row["_id"],
            "name": cust.get("name", "Unknown"),
            "successful_referrals": row["successful_referrals"],
        })
    return {"leaderboard": out}


# ---------------------------------------------------------------------------
# Recording a referral
#
# There is no code to redeem: the parrain is identified by the barcode of the
# card that was scanned, and the filleul by the card they just created.
# ---------------------------------------------------------------------------
def record(tenant_id: str, parrain_barcode: str, filleul: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Write a PENDING referral. Called by the signup, never by the customer.

    Returns the row, or None with a reason logged — a referral that cannot be
    recorded must never stop a signup from completing.
    """
    if not parrain_barcode or not filleul:
        return None
    cfg = _db.referral_config.find_one({"tenant_id": tenant_id}) or {}
    if not cfg.get("enabled", False):
        return None

    parrain = _db.customers.find_one(
        {"tenant_id": tenant_id, "barcode_id": str(parrain_barcode).strip().upper()})
    if not parrain or parrain["id"] == filleul.get("id"):
        return None                       # unknown card, or their own
    if _db.referral_redemptions.find_one(
            {"tenant_id": tenant_id, "referee_customer_id": filleul["id"]}):
        return None                       # a filleul is parrainé exactly once

    row = {
        "tenant_id": tenant_id,
        "referrer_customer_id": parrain["id"],
        "referee_customer_id": filleul["id"],
        # Nothing at signup, for either side: points are given at the
        # filleul's visit only (settle) — user, 2026-10-20.
        "referee_points": 0,
        "referrer_points": 0,
        # What each side is owed, frozen now: changing the setting tomorrow
        # must not rewrite what a referral recorded today promised.
        "referrer_points_promised": int(cfg.get("referrer_reward_points") or 0),
        "referee_points_promised": int(cfg.get("referee_reward_points") or 0),
        "referrer_reward_promised": reward_of(cfg, "referrer"),
        "referee_reward_promised": reward_of(cfg, "referee"),
        "referrer_pending": True,
        "source": "qr_card",
        "created_at": datetime.now(timezone.utc),
    }
    try:
        _db.referral_redemptions.insert_one(dict(row))
    except Exception as exc:              # unique index: someone got there first
        print(f"referrals: could not record ({exc})")
        return None
    return row


def settle(tenant_id: str, filleul_id: str) -> Optional[Dict[str, Any]]:
    """Pay parrain and filleul when the filleul has actually come.

    Called after every visit is recorded. Until the filleul reaches the
    owner's visit (« Visites du filleul avant validation »), a referral has
    promised points and paid none — a signup is free to fake, a visit is not.
    From that visit on, the programme's « Quand créditer » decides:
      once        the first payment only
      every       the same points at every later visit too
      first_then  the first payment, then the *_next points at each later visit
    Each visit is paid at most once, however many tills scan it.
    """
    row = _db.referral_redemptions.find_one({"tenant_id": tenant_id, "referee_customer_id": filleul_id})
    if not row:
        return None
    cfg = _db.referral_config.find_one({"tenant_id": tenant_id}) or {}
    filleul = _db.customers.find_one({"id": filleul_id})
    need = max(1, int(cfg.get("minimum_visits_to_earn", 1) or 1))
    visits = int((filleul or {}).get("visits") or 0)
    if not filleul or visits < need:
        return None
    now = datetime.now(timezone.utc)
    mode = cfg.get("reward_mode") if cfg.get("reward_mode") in REWARD_MODES else "once"

    if row.get("referrer_pending", True):
        # The first payment — what was promised at signup. Claimed first: two
        # tills scanning the same card at once must not pay twice.
        parrain_r = row.get("referrer_reward_promised") or {
            "kind": "points", "n": int(row.get("referrer_points_promised") or 0)}
        filleul_r = row.get("referee_reward_promised") or {
            "kind": "points", "n": int(row["referee_points_promised"] if "referee_points_promised" in row
                                       else row.get("referee_points") or 0)}     # rows older than the promise fields
        parrain_pts, filleul_pts = _points(parrain_r), _points(filleul_r)
        claimed = _db.referral_redemptions.update_one(
            {"_id": row["_id"], "referrer_pending": True},
            {"$set": {"referrer_pending": False, "referrer_points": parrain_pts, "referee_points": filleul_pts,
                      "referrer_given": _tally(parrain_r), "referee_given": _tally(filleul_r),
                      "settled_at": now, "rewarded_visits": 1, "last_rewarded_visit": visits}})
        kind = "first"
    else:
        if mode == "once":
            return None
        last = int(row.get("last_rewarded_visit") or need)
        if visits <= last:
            return None                                    # this visit is already paid
        which = "first" if mode == "every" else "next"
        parrain_r, filleul_r = reward_of(cfg, "referrer", which), reward_of(cfg, "referee", which)
        parrain_pts, filleul_pts = _points(parrain_r), _points(filleul_r)
        tally = {"$set": {"last_rewarded_visit": visits, "last_rewarded_at": now},
                 "$inc": {"referrer_points": parrain_pts, "referee_points": filleul_pts, "rewarded_visits": 1}}
        for side, r in (("referrer", parrain_r), ("referee", filleul_r)):
            t = _tally(r)
            if not isinstance(row.get(f"{side}_given"), dict):
                # paid before the tally existed: start it from what it gave so far
                tally["$set"][f"{side}_given"] = _add(given(row, side, cfg), t)
                continue
            for key in ("points", "stamps", "offers"):
                if t[key]:
                    tally["$inc"][f"{side}_given.{key}"] = t[key]
            if t["offer_text"] and not row[f"{side}_given"].get("offer_text"):
                tally["$set"][f"{side}_given.offer_text"] = t["offer_text"]
        claimed = _db.referral_redemptions.update_one(
            {"_id": row["_id"], "$or": [{"last_rewarded_visit": {"$lt": visits}},
                                        {"last_rewarded_visit": {"$exists": False}}]}, tally)
        kind = "next"
    if not getattr(claimed, "modified_count", 1):
        return None

    tag = f"parrainage:{row.get('referee_customer_id')}:{visits}"
    _give(tenant_id, row["referrer_customer_id"], parrain_r, f"{tag}:parrain")
    _give(tenant_id, filleul_id, filleul_r, f"{tag}:filleul")
    try:
        _announce(tenant_id, row["referrer_customer_id"], filleul, kind, parrain_r, filleul_r)
    except Exception as exc:                   # a message must never cost the reward
        print(f"referrals: announce failed ({exc})")
    return {"referrer_customer_id": row["referrer_customer_id"], "kind": kind,
            "referrer_points": parrain_pts, "referee_points": filleul_pts,
            "referrer_reward": label(parrain_r), "referee_reward": label(filleul_r)}


# ---------------------------------------------------------------------------
# The rewards themselves
# ---------------------------------------------------------------------------
def reward_of(cfg: Dict[str, Any], side: str, which: str = "first") -> Dict[str, Any]:
    """One side's reward from the settings: {kind: points, n} · {kind: stamps,
    n} · {kind: offer, text}. `which`: « first » (the validation, and every
    visit in « À chaque visite »), « next » (the later visits of « Bonus puis
    récurrent »)."""
    kind = cfg.get(f"{side}_reward_kind")
    kind = kind if kind in REWARD_KINDS else "points"
    nx = "_next" if which == "next" else ""
    if kind == "offer":
        return {"kind": "offer", "text": str(cfg.get(f"{side}_reward_offer{nx}") or "").strip()}
    if kind == "stamps":
        return {"kind": "stamps", "n": max(0, int(cfg.get(f"{side}_reward_stamps{nx}") or 0))}
    return {"kind": "points", "n": max(0, int(cfg.get(f"{side}_reward_points{nx}") or 0))}


def _points(r: Dict[str, Any]) -> int:
    return int(r.get("n") or 0) if r.get("kind") == "points" else 0


def label(r: Dict[str, Any]) -> str:
    """« 50 points », « 2 tampons », « 1 café offert » — or « » for nothing."""
    kind, n = r.get("kind"), int(r.get("n") or 0)
    if kind == "offer":
        return str(r.get("text") or "").strip()
    if not n:
        return ""
    if kind == "stamps":
        return f"{n} tampon{'s' if n > 1 else ''}"
    return f"{n} point{'s' if n > 1 else ''}"


# ---------------------------------------------------------------------------
# What a parrainage has given (user, 2026-10-27: the page said « 0 points »
# to a shop in tampons — the friends had their tampons in Wallet). Each row
# keeps a tally per side, `referrer_given` / `referee_given`:
#   {points, stamps, offers, offer_text}
# written when it is paid, so the page, the leaderboard and the CSV read what
# was handed over, in its own kind, whatever the setting says today.
# ---------------------------------------------------------------------------
def _n(x: Any) -> int:
    try:
        return max(0, int(x or 0))
    except (TypeError, ValueError):
        return 0


def _zero() -> Dict[str, Any]:
    return {"points": 0, "stamps": 0, "offers": 0, "offer_text": ""}


def _tally(r: Dict[str, Any]) -> Dict[str, Any]:
    """One reward ({kind, n|text}) as a tally — nothing for an empty one,
    the way _give hands nothing over."""
    t = _zero()
    if not isinstance(r, dict) or not label(r):
        return t
    if r.get("kind") == "offer":
        t.update(offers=1, offer_text=str(r.get("text") or "").strip())
    elif r.get("kind") == "stamps":
        t["stamps"] = _n(r.get("n"))
    else:
        t["points"] = _n(r.get("n"))
    return t


def _add(a: Dict[str, Any], b: Dict[str, Any], times: int = 1) -> Dict[str, Any]:
    return {"points": a["points"] + b["points"] * times, "stamps": a["stamps"] + b["stamps"] * times,
            "offers": a["offers"] + b["offers"] * times, "offer_text": a["offer_text"] or b["offer_text"]}


def given(row: Dict[str, Any], side: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What one side of a parrainage has received so far. A pending row has
    given nothing. Rows paid before `*_given` existed read back from their
    points and their promise; their later visits (« À chaque visite », « Bonus
    puis récurrent ») from the settings in `cfg` — the closest record there is."""
    if row.get("referrer_pending", True):
        return _zero()
    g = row.get(f"{side}_given")
    if isinstance(g, dict):
        return {"points": _n(g.get("points")), "stamps": _n(g.get("stamps")), "offers": _n(g.get("offers")),
                "offer_text": str(g.get("offer_text") or "") if isinstance(g.get("offer_text"), str) else ""}
    t = {**_zero(), "points": _n(row.get(f"{side}_points"))}       # points were always counted on the row
    first = row.get(f"{side}_reward_promised")
    if isinstance(first, dict) and first.get("kind") in ("stamps", "offer"):
        t = _add(t, _tally(first))
    later = _n(row.get("rewarded_visits") or 1) - 1
    mode = (cfg or {}).get("reward_mode")
    if later > 0 and mode in ("every", "first_then"):
        nxt = reward_of(cfg, side, "first" if mode == "every" else "next")
        if nxt.get("kind") in ("stamps", "offer"):
            t = _add(t, _tally(nxt), later)
    return t


def words(t: Dict[str, Any]) -> str:
    """« 2 tampons », « 50 points », « 1 café offert », « 2 tampons · 50 points »
    — or « » for nothing."""
    parts = []
    if t.get("stamps"):
        parts.append(label({"kind": "stamps", "n": t["stamps"]}))
    if t.get("points"):
        parts.append(label({"kind": "points", "n": t["points"]}))
    if t.get("offers"):
        n = t["offers"]
        parts.append(t.get("offer_text") if n == 1 and t.get("offer_text") else f"{n} offre{'s' if n > 1 else ''}")
    return " · ".join(parts)


def _clean(t: Any) -> Dict[str, Any]:
    if not isinstance(t, dict):
        return _zero()
    return {"points": _n(t.get("points")), "stamps": _n(t.get("stamps")), "offers": _n(t.get("offers")),
            "offer_text": t.get("offer_text") if isinstance(t.get("offer_text"), str) else ""}


def total_words(a: Any, b: Any) -> str:
    """Both sides of a parrainage together (user, 2026-10-28: « 2 tampons »
    showed while each side got 2): tampons and points add up (« 4 tampons »,
    « 2 tampons · 75 points »); offers keep their names (« 1 coupe offerte +
    -20 % sur la coupe », « 2 × 1 café offert »)."""
    a, b = _clean(a), _clean(b)
    numbers = words({**_zero(), "stamps": a["stamps"] + b["stamps"], "points": a["points"] + b["points"]})
    offers = [words({**_zero(), "offers": t["offers"], "offer_text": t["offer_text"]}) for t in (a, b) if t["offers"]]
    if len(offers) == 2 and offers[0] == offers[1] and a["offers"] == b["offers"] == 1:
        offers = [f"2 × {offers[0]}"]
    return " · ".join(x for x in (numbers, " + ".join(offers)) if x)


def _main_kind(t: Dict[str, Any]) -> str:
    for kind, key in (("stamps", "stamps"), ("offer", "offers"), ("points", "points")):
        if t.get(key):
            return kind
    return ""


def _give(tenant_id: str, customer_id: str, r: Dict[str, Any], tag: str) -> None:
    """Hand one side its reward.
      points  added to the card's points
      stamps  on the card's meter, the way a paper card's stamps are moved in
              (the cycle marker steps back — visits are not invented)
      offer   waits at the till with « Remettre », beside the défis won
    """
    if not label(r):
        return
    kind = r.get("kind")
    now = datetime.now(timezone.utc)
    if kind == "points":
        _db.customers.update_one({"id": customer_id}, {"$inc": {"points": int(r["n"])}, "$set": {"updated_at": now}})
    elif kind == "stamps":
        # a tampon is worth « visits_per_stamp » visits on the client's own card
        # (their home store's, multi-store 2026-10-12)
        cust = _db.customers.find_one({"id": customer_id}, {"_id": 0, "branch_id": 1}) or {}
        try:
            from features import store_cards as SC
            with SC.store(tenant_id, cust.get("branch_id")):
                tpl = _db.card_templates.find_one({"tenant_id": tenant_id}) or {}
        except Exception:
            tpl = _db.card_templates.find_one({"tenant_id": tenant_id}) or {}
        per = max(1, int(tpl.get("visits_per_stamp", 1) or 1))
        _db.customers.update_one({"id": customer_id}, {"$inc": {"visits_at_last_redemption": -int(r["n"]) * per},
                                                       "$set": {"updated_at": now}})
    elif kind == "offer":
        try:
            _db.defi_rewards.insert_one({
                "id": str(uuid.uuid4()), "tenant_id": tenant_id, "campaign_id": tag, "customer_id": customer_id,
                "kind": "parrainage", "title": "Parrainage", "reward": r["text"], "won_at": now,
                "expires_at": None, "status": "pending"})
        except Exception as exc:               # unique (campaign_id, customer): this visit already gave it
            print(f"referrals: offer not banked ({exc})")


def _first(name: Any, fallback: str) -> str:
    # « % » would break Wallet's « %@ » placeholder
    return ((str(name or "").strip().split(" ") or [""])[0] or fallback).replace("%", "")


def messages(kind: str, shop: str, parrain: str, filleul: str, parrain_got: Any, filleul_got: Any) -> Dict[str, Any]:
    """What each side is told when a parrainage reward lands (user, 2026-10-09):
    the parrain hears that their friend came, the filleul whom they owe it to.
    `*_got`: a number of points, or the reward's words (« 2 tampons »)."""
    def what(x):
        return f"+{x} points" if isinstance(x, int) else (f"+{x}" if str(x)[:1].isdigit() else str(x))
    if kind == "first":
        return {"parrain": ("Parrainage réussi 🎉", f"Votre ami {filleul} est venu chez {shop} : {what(parrain_got)}."),
                "filleul": (f"Bienvenue chez {shop} 🎉",
                            f"Merci d'être venu grâce à {parrain} : {what(filleul_got)} de parrainage.")}
    return {"parrain": ("Parrainage 🎉", f"{filleul} est revenu chez {shop} : {what(parrain_got)}."),
            "filleul": ("Parrainage 🎉", f"{what(filleul_got)} de parrainage grâce à {parrain}.")}


def _announce(tenant_id: str, parrain_id: str, filleul: Dict[str, Any], kind: str,
              parrain_r: Dict[str, Any], filleul_r: Dict[str, Any]) -> None:
    """Tell each side, on their own card, through the shop's « Parrainage »
    automations (features/automations, 2026-10-11): one for the parrain, one
    for the filleul, words and button chosen by the shop. No automation
    switched on for a side → that side gets the points quietly. No SMS."""
    from features import automations as AU
    parrain = _db.customers.find_one({"id": parrain_id}, {"_id": 0}) or {}
    filleul_doc = _db.customers.find_one({"id": filleul["id"]}, {"_id": 0}) or filleul
    names = {"parrain": _first(parrain.get("name"), "votre parrain"), "filleul": _first(filleul.get("name"), "Votre ami")}
    as_reward = lambda x: x if isinstance(x, dict) else {"kind": "points", "n": int(x or 0)}   # noqa: E731 — a number is points
    for cust, r, side in ((parrain, as_reward(parrain_r), "parrain"), (filleul_doc, as_reward(filleul_r), "filleul")):
        if not label(r) or not cust.get("id"):
            continue
        AU.fire("referral", tenant_id, cust, {"side": side, "points": _points(r), "reward": label(r),
                                              "reward_kind": r.get("kind"), "kind": kind, **names})


@router.get("/api/card/{barcode_id}/inviter")
def inviter(barcode_id: str):
    """Who is inviting, for the signup form — and nothing else.

    A stranger who scanned a card lands on the signup page, and the page says
    who invited them. It gets a first name and the shop's slug; it never gets
    the card, the points, or anything else about that customer.
    """
    cust = _db.customers.find_one({"barcode_id": (barcode_id or "").strip().upper()},
                                  {"_id": 0, "tenant_id": 1, "name": 1, "branch_id": 1})
    if not cust:
        raise HTTPException(status_code=404, detail="Carte inconnue")
    tenant = _db.tenants.find_one({"id": cust["tenant_id"]}, {"_id": 0, "id": 1, "slug": 1, "name": 1, "branches": 1}) or {}
    # the friend joins the inviter's store (store_links.parrain_store): the
    # form names it and never asks (user, 2026-10-14)
    from features import store_links as SL
    if tenant.get("branches"):
        SL.ensure_slugs(tenant)
    home = SL.parrain_store(tenant, cust)
    cfg = _db.referral_config.find_one({"tenant_id": cust["tenant_id"]}) or {}
    first = (cust.get("name") or "").strip().split(" ")[0]
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "first_name": first,
        "slug": tenant.get("slug"),
        "business_name": tenant.get("name"),
        "store": {"slug": home.get("slug"), "name": home.get("name")} if home else None,
        "referee_points": int(cfg.get("referee_reward_points") or 0),
        "referrer_points": int(cfg.get("referrer_reward_points") or 0),
        # what each side receives, in words (« 25 points », « 1 tampon », « 1 café offert »)
        "referee_reward": label(reward_of(cfg, "referee")),
        "referrer_reward": label(reward_of(cfg, "referrer")),
        # when they are paid, so the signup form says it right
        "minimum_visits": max(1, int(cfg.get("minimum_visits_to_earn", 1) or 1)),
        "reward_mode": cfg.get("reward_mode") if cfg.get("reward_mode") in REWARD_MODES else "once",
    }


class WhoseRequest(BaseModel):
    k: Optional[str] = None          # the owner key, when the link carried one
    mine: object = None              # the cards this phone holds: {card: key}
    shop: bool = False               # opened from the dashboard (?vue=commerce)


@router.post("/api/card/{barcode_id}/whose")
async def card_whose(barcode_id: str, body: WhoseRequest, request: Request):
    """What /card/{id} shows on this phone — the card, the phone's own card
    for that shop, or the signup form (services/card_owner)."""
    from services import card_owner as CO
    from auth import get_current_user_data
    viewer = None
    # Only a dashboard link asks for the shop's view: an owner signed in on
    # their own phone who scans a customer's QR is a customer like any other.
    if body.shop and (request.headers.get("authorization") or request.cookies.get("access_token")):
        try:
            td = await get_current_user_data(request)
            viewer = {"role": td.role, "tenant_id": td.tenant_id}
        except Exception:
            viewer = None
    out = CO.whose(_db, barcode_id, body.k, CO.owned_from(body.mine), viewer)
    if out is None:
        raise HTTPException(status_code=404, detail="Carte inconnue")
    return out


# ===========================================================================
# The Parrainage page — one payload behind the whole dashboard.
#
# Built to the approved mockup. Everything below counts real rows in
# `referral_redemptions` and `customers`; there is no demo
# data, so a programme nobody has used yet reads zero and says so.
#
# TWO DEFINITIONS WORTH KNOWING, BOTH DECIDED WITH THE MERCHANT
#   • "CA généré via parrainage" is the whole spend of every filleul since they
#     joined, for the life of the programme — not just the selected period. It
#     answers "what has parrainage brought me", so the card says "depuis le
#     début" and deliberately does not move with the date filter.
#   • The breakdown splits parrains by who they are: étudiants first (declared
#     at signup — the segment French merchants build offers around), then
#     réguliers, nouveaux, and everyone else.
# ===========================================================================
from typing import Any, Dict, List, Tuple                      # noqa: E402
from datetime import timedelta                                 # noqa: E402
import csv                                                     # noqa: E402
import io                                                      # noqa: E402

from fastapi import Query                                      # noqa: E402
from fastapi.responses import Response                         # noqa: E402

# Where a referral came from. There is one way in now — a customer's own card
# was scanned — but the older labels stay so rows recorded under the retired
# link programme still read correctly in the table and the export.
SOURCES: Dict[str, str] = {
    "qr_card": "Carte d'un client",
    "qr": "QR code",
    "link": "Lien partagé",
    "social": "Réseaux sociaux",
    "other": "Autre",
}

# Who the parrain is. Étudiant wins over everything else — it is the segment
# the merchant builds offers around, so a student who also visits often is
# still counted as a student.
REGULAR_MIN_VISITS = 5
NEW_CUSTOMER_DAYS = 90
SEGMENTS: List[Tuple[str, str, str]] = [
    ("reguliers", "Clients réguliers", "blue"),
    ("etudiants", "Étudiants", "teal"),
    ("nouveaux", "Nouveaux clients", "amber"),
    ("autres", "Autres", "violet"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _window(date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime]:
    end = (_aware(date_to) or _now()).replace(hour=23, minute=59, second=59, microsecond=999999)
    start = (_aware(date_from) or (end - timedelta(days=29))).replace(
        hour=0, minute=0, second=0, microsecond=0)
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), start
    return start, end


def _segment_of(cust: Dict[str, Any]) -> str:
    if cust.get("is_student"):
        return "etudiants"
    if int(cust.get("visits") or 0) >= REGULAR_MIN_VISITS:
        return "reguliers"
    joined = _aware(cust.get("created_at"))
    if joined and (_now() - joined).days <= NEW_CUSTOMER_DAYS:
        return "nouveaux"
    return "autres"


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s'-]+", (name or "").strip()) if p]
    if not parts:
        return "?"
    return (parts[0][:2] if len(parts) == 1 else parts[0][0] + parts[-1][0]).upper()


def _short(name: str) -> str:
    """"Sophie Lambert" → "Sophie L." — the design's own shorthand, which also
    keeps a full surname off a screen the whole counter can see."""
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return "Client"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


def _people(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    rows = _db.customers.find(
        {"id": {"$in": ids}},
        {"_id": 0, "id": 1, "name": 1, "tier": 1, "visits": 1, "is_student": 1,
         "created_at": 1, "total_amount_paid": 1},
    )
    return {r["id"]: r for r in rows}


def _delta(now_value: float, was_value: float) -> Optional[int]:
    """None when there is nothing to compare against — a first month shows no
    percentage rather than a meaningless +100%."""
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


def _rows_between(tid: str, start: datetime, end: datetime, mine: Optional[set] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tid, "created_at": {"$gte": start, "$lte": end}}
    if mine is not None:
        q["referee_customer_id"] = {"$in": list(mine)}
    return list(_db.referral_redemptions.find(q).sort("created_at", -1))


def _table_row(r: Dict[str, Any], people: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """One line of « Derniers parrainages »."""
    parrain = people.get(r.get("referrer_customer_id") or "") or {}
    filleul = people.get(r.get("referee_customer_id") or "") or {}
    at = _aware(r.get("created_at"))
    pending = bool(r.get("referrer_pending"))
    source = (r.get("source") or "link").lower()
    reward = _row_reward(r, config)
    reward_ree = _row_reward(r, config, "referee")
    both = _add(reward, reward_ree)
    return {
        "id": str(r.get("_id") or ""),
        "at": at.isoformat() if at else None,
        "parrain": {"name": _short(parrain.get("name") or "Client supprimé"),
                    "initials": _initials(parrain.get("name") or ""),
                    "tier": (parrain.get("tier") or "bronze").lower()},
        "filleul": {"name": _short(filleul.get("name") or "Client supprimé"),
                    "initials": _initials(filleul.get("name") or ""),
                    "tier": (filleul.get("tier") or "bronze").lower()},
        "status": "pending" if pending else "validated",
        "status_label": "En attente" if pending else "Validé",
        # Validated → what was actually credited. Pending → what is promised,
        # as recorded when the parrainage was made, so a later change to the
        # setting cannot rewrite history.
        "reward_points": int(r.get("referrer_points") or 0) if not pending
        else int(r["referrer_points_promised"] if r.get("referrer_points_promised") is not None
                 else config.get("referrer_reward_points") or 0),
        # both sides together (user, 2026-10-28), each side for the tooltip
        "reward": total_words(reward, reward_ree),
        "reward_parrain": words(reward),
        "reward_filleul": words(reward_ree),
        "reward_kind": _main_kind(both),
        "source": source if source in SOURCES else "other",
        "source_label": SOURCES.get(source, SOURCES["other"]),
    }


def _row_reward(r: Dict[str, Any], config: Dict[str, Any], side: str = "referrer") -> Dict[str, Any]:
    """One side of a row: validated → what was given; pending → the promise
    recorded with the row, in its kind (an old points number left beside a
    tampons promise must not show)."""
    if not r.get("referrer_pending"):
        return given(r, side, config)
    promised = r.get(f"{side}_reward_promised")
    if not isinstance(promised, dict):
        promised = {"kind": "points", "n": r[f"{side}_points_promised"] if r.get(f"{side}_points_promised") is not None
                    else (config or {}).get(f"{side}_reward_points")}
    return _tally(promised)


CARD_LABELS = {"points": "Points offerts", "stamps": "Tampons offerts", "offer": "Offres offertes"}
CARD_KEYS = {"points": "points", "stamps": "stamps", "offer": "offers"}


def _parrains(rows: List[Dict[str, Any]], people: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every parrain of these rows, ranked: what they got (points, tampons,
    offers), then how many friends they brought."""
    tally: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        rid = r.get("referrer_customer_id")
        if not rid:
            continue
        acc = tally.setdefault(rid, {"filleuls": 0, "got": _zero()})
        acc["filleuls"] += 1
        acc["got"] = _add(acc["got"], given(r, "referrer", config))
    rank = lambda kv: (-kv[1]["got"]["points"], -kv[1]["got"]["stamps"], -kv[1]["got"]["offers"],  # noqa: E731
                       -kv[1]["filleuls"], kv[0])
    out = []
    for i, (rid, acc) in enumerate(sorted(tally.items(), key=rank), 1):
        person = people.get(rid) or {}
        name = person.get("name") or "Client supprimé"
        out.append({"rank": i, "customer_id": rid, "name": _short(name), "full_name": name,
                    "initials": _initials(name), "tier": (person.get("tier") or "bronze").lower(),
                    "filleuls": acc["filleuls"], "points": acc["got"]["points"],
                    "reward": words(acc["got"]), "reward_kind": _main_kind(acc["got"])})
    return out


def _fold(text: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", text or "") if unicodedata.category(ch) != "Mn").lower()


@router.get("/api/owner/referrals/list")
def list_referrals(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    search: str = "",
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """Every parrainage of the period, page by page, searchable by the parrain's
    or the filleul's name (QA R5 F25, 2026-10-09: « Voir tous » stopped at ten
    of fifty-one; the rest was reachable only in the CSV)."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    rows = _rows_between(tid, start, end, S.customer_ids(S.resolve(token_data, request)))
    people = _people([r.get("referrer_customer_id") for r in rows]
                     + [r.get("referee_customer_id") for r in rows])
    words = _fold(search).split()
    if words:
        def hay(r):
            return _fold(" ".join([(people.get(r.get("referrer_customer_id") or "") or {}).get("name") or "",
                                   (people.get(r.get("referee_customer_id") or "") or {}).get("name") or ""]))
        rows = [r for r in rows if all(w in hay(r) for w in words)]
    total = len(rows)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    config = _db.referral_config.find_one({"tenant_id": tid}) or {}
    chunk = rows[(page - 1) * per_page: page * per_page]
    return {"rows": [_table_row(r, people, config) for r in chunk],
            "total": total, "page": page, "pages": pages, "per_page": per_page}


@router.get("/api/owner/referrals/parrains")
def list_parrains(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    search: str = Query("", max_length=80),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """« Top parrains › Voir tous » (user, 2026-10-28: it downloaded a CSV):
    every parrain of the period, ranked like the top five, searchable by name,
    page by page. Only the clients of the establishments this account sees."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    rows = _rows_between(tid, start, end, S.customer_ids(S.resolve(token_data, request)))
    people = _people([r.get("referrer_customer_id") for r in rows])
    config = _db.referral_config.find_one({"tenant_id": tid}) or {}
    ranked = _parrains(rows, people, config)
    terms = _fold(search).split()
    if terms:
        ranked = [p for p in ranked if all(w in _fold(p["full_name"]) for w in terms)]
    total = len(ranked)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    chunk = ranked[(page - 1) * per_page: page * per_page]
    for p in chunk:
        p.pop("full_name", None)                 # the short name is what the screen shows
    return {"rows": chunk, "total": total, "page": page, "pages": pages, "per_page": per_page}


@router.get("/api/owner/referrals/overview")
def overview(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    tid = token_data.tenant_id
    mine = S.customer_ids(S.resolve(token_data, request))
    start, end = _window(date_from, date_to)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    rows = _rows_between(tid, start, end, mine)
    prev_rows = _rows_between(tid, prev_start, prev_end, mine)
    config = _db.referral_config.find_one({"tenant_id": tid}) or {}

    people = _people([r.get("referrer_customer_id") for r in rows + prev_rows]
                     + [r.get("referee_customer_id") for r in rows])

    def handed(batch):
        # given only: a parrainage still waiting for the filleul's visit has
        # given nothing (older rows wrote the filleul's 25 at signup)
        t = _zero()
        for r in batch:
            t = _add(_add(t, given(r, "referrer", config)), given(r, "referee", config))
        return t

    # the card speaks the reward the shop gives today (tampons, points or its
    # offer); anything else handed over before a change is named beneath
    kind = config.get("referrer_reward_kind") if config.get("referrer_reward_kind") in REWARD_KINDS else "points"
    now_t, prev_t = handed(rows), handed(prev_rows)
    key = CARD_KEYS[kind]
    also = words({**now_t, key: 0})

    # Revenue is programme-wide and all-time by design: it answers "what has
    # parrainage brought me", not "what did it bring me in September".
    all_referees = _db.referral_redemptions.distinct("referee_customer_id", {"tenant_id": tid})
    if mine is not None:
        all_referees = [i for i in all_referees if i in mine]
    revenue = 0.0
    for cust in _db.customers.find({"id": {"$in": list(all_referees)}},
                                   {"_id": 0, "total_amount_paid": 1}):
        revenue += float(cust.get("total_amount_paid") or 0)

    parrains = {r.get("referrer_customer_id") for r in rows if r.get("referrer_customer_id")}
    prev_parrains = {r.get("referrer_customer_id") for r in prev_rows if r.get("referrer_customer_id")}

    cards = [
        {"key": "referrals", "label": "Parrainages réalisés", "icon": "users",
         "tone": "teal", "value": len(rows), "delta_pct": _delta(len(rows), len(prev_rows))},
        {"key": "active", "label": "Parrains actifs", "icon": "user", "tone": "blue",
         "value": len(parrains), "delta_pct": _delta(len(parrains), len(prev_parrains))},
        {"key": "points", "label": CARD_LABELS[kind], "icon": "gift", "tone": "amber", "kind": kind,
         "value": now_t[key], "delta_pct": _delta(now_t[key], prev_t[key]),
         **({"also": f"+ {also}"} if also else {})},
        {"key": "revenue", "label": "CA généré via parrainage", "icon": "euro", "tone": "violet",
         "value": round(revenue, 2), "unit": "€", "all_time": True,
         "note": "depuis le début", "delta_pct": None},
    ]

    # ---- the curve: parrainages accumulated across the period --------------
    days = max(1, (end.date() - start.date()).days + 1)
    per_day = {(start.date() + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for r in rows:
        at = _aware(r.get("created_at"))
        if at:
            key = at.date().isoformat()
            if key in per_day:
                per_day[key] += 1
    running = 0
    series = []
    for day in sorted(per_day):
        running += per_day[day]
        series.append({"date": day, "count": per_day[day], "cumulative": running})

    # ---- who the parrains are ----------------------------------------------
    seg_counts = {key: 0 for key, _label, _tone in SEGMENTS}
    for r in rows:
        person = people.get(r.get("referrer_customer_id") or "")
        seg_counts[_segment_of(person) if person else "autres"] += 1
    total_seg = sum(seg_counts.values())
    breakdown = [{"key": key, "label": label, "tone": tone,
                  "count": seg_counts[key],
                  "pct": round(seg_counts[key] / total_seg * 100) if total_seg else 0}
                 for key, label, tone in SEGMENTS]

    # ---- the leaderboard (its first five; « Voir tous » lists them all) -----
    top = _parrains(rows, people, config)[:5]

    # ---- the table: its first rows (« Voir tous » pages through all of them) --
    recent = [_table_row(r, people, config) for r in rows[:10]]

    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "enabled": bool(config.get("enabled")),
        # the settings as saved, every field (kind, tampons, offer…): the
        # modal re-opens on them and saves them back unchanged
        "config": {**ReferralConfig().model_dump(exclude={"tenant_id", "enabled"}),
                   **{k: v for k, v in config.items() if k not in ("_id", "tenant_id", "enabled")},
                   "minimum_visits_to_earn": int(config.get("minimum_visits_to_earn") or 1),
                   "reward_mode": config.get("reward_mode") if config.get("reward_mode") in REWARD_MODES else "once"},
        "cards": cards,
        "series": series,
        "breakdown": {"total": total_seg, "segments": breakdown},
        "top_parrains": top,
        "recent": recent,
        "total_referrals": len(rows),
        "sources": [{"key": k, "label": v} for k, v in SOURCES.items()],
    }


def _public_url() -> str:
    import os
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("PUBLIC_SITE_URL")
            or "https://app.fidclic.com").rstrip("/")


def _cell(v: Any) -> str:
    """A CSV cell Excel shows and never runs: a client's name or the shop's
    offer starting with = + - @ would be a formula (pentest 2026-10-27)."""
    v = str(v or "")
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


@router.get("/api/owner/referrals/export")
def export_referrals(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """Every parrainage of the period — the table without its ten-row limit."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    rows = _rows_between(tid, start, end, S.customer_ids(S.resolve(token_data, request)))
    people = _people([r.get("referrer_customer_id") for r in rows]
                     + [r.get("referee_customer_id") for r in rows])
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    config = _db.referral_config.find_one({"tenant_id": tid}) or {}
    w.writerow(["Date", "Parrain", "Filleul", "Statut", "Récompense parrain", "Récompense filleul",
                "Récompense totale", "Source"])
    for r in rows:
        at = _aware(r.get("created_at"))
        w.writerow([_cell(c) for c in (
            at.strftime("%d/%m/%Y") if at else "",
            (people.get(r.get("referrer_customer_id") or "") or {}).get("name") or "",
            (people.get(r.get("referee_customer_id") or "") or {}).get("name") or "",
            "En attente" if r.get("referrer_pending") else "Validé",
            words(_row_reward(r, config)),
            words(_row_reward(r, config, "referee")),
            total_words(_row_reward(r, config), _row_reward(r, config, "referee")),
            SOURCES.get((r.get("source") or "link").lower(), SOURCES["other"]),
        )])
    data = "﻿" + buf.getvalue()
    name = f"fidclic-parrainage-{start:%Y%m%d}-{end:%Y%m%d}.csv"
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
