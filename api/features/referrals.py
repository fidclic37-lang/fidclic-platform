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


# ---------- Models ----------
class ReferralConfig(BaseModel):
    tenant_id: Optional[str] = None
    enabled: bool = False
    referrer_reward_points: int = 50
    referee_reward_points: int = 25
    minimum_visits_to_earn: int = 1   # referee must reach this many visits before referrer is credited
    # When both are credited (user, 2026-10-08), from that visit on:
    #   once        — once, at that visit
    #   every       — at that visit and every visit after it
    #   first_then  — the points above at that visit, then *_next at each later one
    reward_mode: str = "once"
    referrer_reward_points_next: int = 0
    referee_reward_points_next: int = 0
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
        "referee_points": int(cfg.get("referee_reward_points", 25)),
        "referrer_points": 0,
        # What each side is owed, frozen now: changing the setting tomorrow
        # must not rewrite what a referral recorded today promised.
        "referrer_points_promised": int(cfg.get("referrer_reward_points", 50)),
        "referee_points_promised": int(cfg.get("referee_reward_points", 25)),
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
        parrain_pts = int(row.get("referrer_points_promised") or 0)
        filleul_pts = int(row.get("referee_points_promised") or row.get("referee_points") or 0)
        claimed = _db.referral_redemptions.update_one(
            {"_id": row["_id"], "referrer_pending": True},
            {"$set": {"referrer_pending": False, "referrer_points": parrain_pts, "referee_points": filleul_pts,
                      "settled_at": now, "rewarded_visits": 1, "last_rewarded_visit": visits}})
        kind = "first"
    else:
        if mode == "once":
            return None
        last = int(row.get("last_rewarded_visit") or need)
        if visits <= last:
            return None                                    # this visit is already paid
        if mode == "every":
            parrain_pts = int(cfg.get("referrer_reward_points", 50) or 0)
            filleul_pts = int(cfg.get("referee_reward_points", 25) or 0)
        else:
            parrain_pts = int(cfg.get("referrer_reward_points_next", 0) or 0)
            filleul_pts = int(cfg.get("referee_reward_points_next", 0) or 0)
        claimed = _db.referral_redemptions.update_one(
            {"_id": row["_id"], "$or": [{"last_rewarded_visit": {"$lt": visits}},
                                        {"last_rewarded_visit": {"$exists": False}}]},
            {"$set": {"last_rewarded_visit": visits, "last_rewarded_at": now},
             "$inc": {"referrer_points": parrain_pts, "referee_points": filleul_pts, "rewarded_visits": 1}})
        kind = "next"
    if not getattr(claimed, "modified_count", 1):
        return None

    if parrain_pts:
        _db.customers.update_one({"id": row["referrer_customer_id"]}, {"$inc": {"points": parrain_pts}})
    if filleul_pts:
        _db.customers.update_one({"id": filleul_id}, {"$inc": {"points": filleul_pts}})
    try:
        _announce(tenant_id, row["referrer_customer_id"], filleul, kind, parrain_pts, filleul_pts)
    except Exception as exc:                   # a message must never cost the points
        print(f"referrals: announce failed ({exc})")
    return {"referrer_customer_id": row["referrer_customer_id"], "kind": kind,
            "referrer_points": parrain_pts, "referee_points": filleul_pts}


def _first(name: Any, fallback: str) -> str:
    # « % » would break Wallet's « %@ » placeholder
    return ((str(name or "").strip().split(" ") or [""])[0] or fallback).replace("%", "")


def messages(kind: str, shop: str, parrain: str, filleul: str, parrain_pts: int, filleul_pts: int) -> Dict[str, Any]:
    """What each side is told when parrainage points land (user, 2026-10-09):
    the parrain hears that their friend came, the filleul whom they owe it to."""
    if kind == "first":
        return {"parrain": ("Parrainage réussi 🎉", f"Votre ami {filleul} est venu chez {shop} : +{parrain_pts} points."),
                "filleul": (f"Bienvenue chez {shop} 🎉",
                            f"Merci d'être venu grâce à {parrain} : +{filleul_pts} points de parrainage.")}
    return {"parrain": ("Parrainage 🎉", f"{filleul} est revenu chez {shop} : +{parrain_pts} points."),
            "filleul": ("Parrainage 🎉", f"+{filleul_pts} points de parrainage grâce à {parrain}.")}


def _announce(tenant_id: str, parrain_id: str, filleul: Dict[str, Any], kind: str,
              parrain_pts: int, filleul_pts: int) -> None:
    """Tell both sides, each on their own card: the Wallet pass (Apple shows
    the reason when the points change, Google gets a message) and web push.
    No SMS — the Wallet card is the channel, and an SMS costs the shop."""
    from features.wallet_passes import notify_customer
    tenant = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1}) or {}
    parrain = _db.customers.find_one({"id": parrain_id}, {"_id": 0, "name": 1}) or {}
    shop = (tenant.get("name") or "votre commerce").replace("%", "")
    said = messages(kind, shop, _first(parrain.get("name"), "votre parrain"),
                    _first(filleul.get("name"), "Votre ami"), parrain_pts, filleul_pts)
    now = datetime.now(timezone.utc)
    for cid, pts, side in ((parrain_id, parrain_pts, "parrain"), (filleul["id"], filleul_pts, "filleul")):
        if not pts:
            continue
        title, body = said[side]
        total = int((_db.customers.find_one({"id": cid}, {"_id": 0, "points": 1}) or {}).get("points") or 0)
        _db.customers.update_one({"id": cid}, {"$set": {"points_news": {
            "text": f"{body} Vous avez maintenant %@ points.", "points": total, "at": now, "kind": "parrainage"}}})
        try:
            notify_customer(cid, google_notify={"kind": "parrainage", "header": title, "body": body})
        except Exception as exc:
            print(f"referrals: wallet notify failed ({exc})")
        try:
            from features.push_subscriptions import fan_out_to_customer
            fan_out_to_customer(tenant_id, cid, title, body)
        except Exception as exc:
            print(f"referrals: web push failed ({exc})")


@router.get("/api/card/{barcode_id}/inviter")
def inviter(barcode_id: str):
    """Who is inviting, for the signup form — and nothing else.

    A stranger who scanned a card lands on the signup page, and the page says
    who invited them. It gets a first name and the shop's slug; it never gets
    the card, the points, or anything else about that customer.
    """
    cust = _db.customers.find_one({"barcode_id": (barcode_id or "").strip().upper()},
                                  {"_id": 0, "tenant_id": 1, "name": 1})
    if not cust:
        raise HTTPException(status_code=404, detail="Carte inconnue")
    tenant = _db.tenants.find_one({"id": cust["tenant_id"]}, {"_id": 0, "slug": 1, "name": 1}) or {}
    cfg = _db.referral_config.find_one({"tenant_id": cust["tenant_id"]}) or {}
    first = (cust.get("name") or "").strip().split(" ")[0]
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "first_name": first,
        "slug": tenant.get("slug"),
        "business_name": tenant.get("name"),
        "referee_points": int(cfg.get("referee_reward_points", 25)),
        "referrer_points": int(cfg.get("referrer_reward_points", 50)),
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
        else int(r.get("referrer_points_promised")
                 or config.get("referrer_reward_points") or 0),
        "source": source if source in SOURCES else "other",
        "source_label": SOURCES.get(source, SOURCES["other"]),
    }


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

    def points(batch):
        return sum(int(r.get("referrer_points") or 0) + int(r.get("referee_points") or 0)
                   for r in batch)

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
        {"key": "points", "label": "Points offerts", "icon": "gift", "tone": "amber",
         "value": points(rows), "delta_pct": _delta(points(rows), points(prev_rows))},
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

    # ---- the leaderboard ----------------------------------------------------
    tally: Dict[str, Dict[str, int]] = {}
    for r in rows:
        rid = r.get("referrer_customer_id")
        if not rid:
            continue
        acc = tally.setdefault(rid, {"filleuls": 0, "points": 0})
        acc["filleuls"] += 1
        acc["points"] += int(r.get("referrer_points") or 0)
    top = []
    for rid, acc in sorted(tally.items(), key=lambda kv: (-kv[1]["points"], -kv[1]["filleuls"]))[:5]:
        person = people.get(rid) or {}
        name = person.get("name") or "Client supprimé"
        top.append({"customer_id": rid, "name": _short(name), "full_name": name,
                    "initials": _initials(name), "tier": (person.get("tier") or "bronze").lower(),
                    "filleuls": acc["filleuls"], "points": acc["points"]})

    # ---- the table: its first rows (« Voir tous » pages through all of them) --
    recent = [_table_row(r, people, config) for r in rows[:10]]

    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "enabled": bool(config.get("enabled")),
        "config": {"referrer_reward_points": int(config.get("referrer_reward_points") or 50),
                   "referee_reward_points": int(config.get("referee_reward_points") or 25),
                   "minimum_visits_to_earn": int(config.get("minimum_visits_to_earn") or 1),
                   "reward_mode": config.get("reward_mode") if config.get("reward_mode") in REWARD_MODES else "once",
                   "referrer_reward_points_next": int(config.get("referrer_reward_points_next") or 0),
                   "referee_reward_points_next": int(config.get("referee_reward_points_next") or 0)},
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
    w.writerow(["Date", "Parrain", "Filleul", "Statut", "Récompense (points)", "Source"])
    for r in rows:
        at = _aware(r.get("created_at"))
        w.writerow([
            at.strftime("%d/%m/%Y") if at else "",
            (people.get(r.get("referrer_customer_id") or "") or {}).get("name") or "",
            (people.get(r.get("referee_customer_id") or "") or {}).get("name") or "",
            "En attente" if r.get("referrer_pending") else "Validé",
            int(r.get("referrer_points") or 0) if not r.get("referrer_pending")
            else int(r.get("referrer_points_promised") or 0),
            SOURCES.get((r.get("source") or "link").lower(), SOURCES["other"]),
        ])
    data = "﻿" + buf.getvalue()
    name = f"fidclic-parrainage-{start:%Y%m%d}-{end:%Y%m%d}.csv"
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
