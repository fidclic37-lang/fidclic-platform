"""
Referral Program — additive feature module.

Status: ✅ Implemented.
Mounts at: /api/owner/referrals/* and /api/customer/referral/*
Collections: `referral_config`, `referral_codes`, `referral_redemptions`

Flow:
  1. Existing customer fetches/generates their referral code
  2. They share the code (or a URL with ?ref=CODE)
  3. New customer signs up via the existing /api/join/{slug} endpoint
  4. Frontend calls /api/customer/referral/redeem with new customer's
     barcode and the ref code → credits both referrer and referee
  5. Idempotent: a given new-customer can only be redeemed once

Does NOT modify the existing /api/join/{slug} signup endpoint.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import re
import secrets
import string

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["referrals"])
_db = None


def init(db):
    global _db
    _db = db
    try:
        db.referral_config.create_index("tenant_id", unique=True)
        db.referral_codes.create_index("code", unique=True)
        db.referral_codes.create_index([("tenant_id", 1), ("customer_id", 1)], unique=True)
        db.referral_redemptions.create_index([("tenant_id", 1), ("referee_customer_id", 1)], unique=True)
    except Exception:
        pass


# ---------- Models ----------
class ReferralConfig(BaseModel):
    tenant_id: Optional[str] = None
    enabled: bool = False
    referrer_reward_points: int = 50
    referee_reward_points: int = 25
    minimum_visits_to_earn: int = 1   # referee must reach this many visits before referrer is credited
    referrer_message: str = "Thanks for sharing! You earned {points} points."
    referee_message: str = "Welcome via a friend! Here are {points} points to start."


class GenerateCodeRequest(BaseModel):
    tenant_slug: str
    barcode_id: str


class RedeemRequest(BaseModel):
    tenant_slug: str
    new_customer_barcode_id: str
    code: str
    # Which channel the filleul arrived through — the ?src= on the shared link.
    # Unknown or missing reads as "link", the plain shared-URL case.
    source: Optional[str] = None


# ---------- Helpers ----------
def _new_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "REF-" + "".join(secrets.choice(alphabet) for _ in range(8))


# ---------- Owner endpoints ----------
@router.get("/api/owner/referrals/config")
def get_config(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
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


# ---------- Customer endpoints ----------
@router.post("/api/customer/referral/code")
def get_or_create_code(req: GenerateCodeRequest):
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    customer = _db.customers.find_one({"tenant_id": tenant["id"], "barcode_id": req.barcode_id})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    existing = _db.referral_codes.find_one({
        "tenant_id": tenant["id"], "customer_id": customer["id"]
    })
    if existing:
        return {"code": existing["code"], "share_url": f"/join/{req.tenant_slug}?ref={existing['code']}"}

    # Generate a unique code (collisions are astronomically unlikely but guard anyway)
    for _ in range(5):
        code = _new_code()
        if not _db.referral_codes.find_one({"code": code}):
            break
    else:
        raise HTTPException(status_code=500, detail="Could not allocate referral code")

    _db.referral_codes.insert_one({
        "tenant_id": tenant["id"],
        "customer_id": customer["id"],
        "code": code,
        "created_at": datetime.now(timezone.utc),
    })
    return {"code": code, "share_url": f"/join/{req.tenant_slug}?ref={code}"}


@router.post("/api/customer/referral/redeem")
def redeem(req: RedeemRequest):
    tenant = _db.tenants.find_one({"slug": req.tenant_slug})
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    config = _db.referral_config.find_one({"tenant_id": tenant["id"]}) or {}
    if not config.get("enabled", False):
        return {"redeemed": False, "reason": "referrals_disabled"}

    code_doc = _db.referral_codes.find_one({"code": req.code, "tenant_id": tenant["id"]})
    if not code_doc:
        raise HTTPException(status_code=404, detail="Invalid referral code")

    referee = _db.customers.find_one({"tenant_id": tenant["id"], "barcode_id": req.new_customer_barcode_id})
    if not referee:
        raise HTTPException(status_code=404, detail="Referee not found")

    if referee["id"] == code_doc["customer_id"]:
        raise HTTPException(status_code=400, detail="Cannot self-refer")

    # Idempotency
    if _db.referral_redemptions.find_one({"tenant_id": tenant["id"], "referee_customer_id": referee["id"]}):
        return {"redeemed": False, "reason": "already_redeemed"}

    referee_pts = int(config.get("referee_reward_points", 25))
    referrer_pts = int(config.get("referrer_reward_points", 50))

    _db.customers.update_one({"id": referee["id"]}, {"$inc": {"points": referee_pts}})

    # Referrer credit may be deferred until referee hits minimum_visits_to_earn
    referrer_credited_now = referee.get("visits", 0) >= int(config.get("minimum_visits_to_earn", 1))
    if referrer_credited_now:
        _db.customers.update_one({"id": code_doc["customer_id"]}, {"$inc": {"points": referrer_pts}})

    _db.referral_redemptions.insert_one({
        "tenant_id": tenant["id"],
        "referrer_customer_id": code_doc["customer_id"],
        "referee_customer_id": referee["id"],
        "code": req.code,
        "referee_points": referee_pts,
        "referrer_points": referrer_pts if referrer_credited_now else 0,
        # What the parrain is owed, recorded whether or not it has been paid —
        # the dashboard shows a pending row's promised reward, and the reward
        # must not drift if the merchant changes the setting in between.
        "referrer_points_promised": referrer_pts,
        "referrer_pending": not referrer_credited_now,
        "source": (req.source or "link").lower() if (req.source or "link").lower() in SOURCES else "other",
        "created_at": datetime.now(timezone.utc),
    })

    return {
        "redeemed": True,
        "referee_credited": referee_pts,
        "referrer_credited": referrer_pts if referrer_credited_now else 0,
        "referrer_pending": not referrer_credited_now,
    }


# ===========================================================================
# The Parrainage page — one payload behind the whole dashboard.
#
# Built to the approved mockup. Everything below counts real rows in
# `referral_redemptions`, `referral_codes` and `customers`; there is no demo
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

# Where a referral was shared from. The share sheet stamps one of these into
# the link, and redeem records whichever came back.
SOURCES: Dict[str, str] = {
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


def _rows_between(tid: str, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return list(_db.referral_redemptions.find(
        {"tenant_id": tid, "created_at": {"$gte": start, "$lte": end}}
    ).sort("created_at", -1))


@router.get("/api/owner/referrals/overview")
def overview(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    rows = _rows_between(tid, start, end)
    prev_rows = _rows_between(tid, prev_start, prev_end)
    config = _db.referral_config.find_one({"tenant_id": tid}) or {}

    people = _people([r.get("referrer_customer_id") for r in rows + prev_rows]
                     + [r.get("referee_customer_id") for r in rows])

    def points(batch):
        return sum(int(r.get("referrer_points") or 0) + int(r.get("referee_points") or 0)
                   for r in batch)

    # Revenue is programme-wide and all-time by design: it answers "what has
    # parrainage brought me", not "what did it bring me in September".
    all_referees = _db.referral_redemptions.distinct("referee_customer_id", {"tenant_id": tid})
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

    # ---- the table ----------------------------------------------------------
    recent = []
    for r in rows[:10]:
        parrain = people.get(r.get("referrer_customer_id") or "") or {}
        filleul = people.get(r.get("referee_customer_id") or "") or {}
        at = _aware(r.get("created_at"))
        pending = bool(r.get("referrer_pending"))
        source = (r.get("source") or "link").lower()
        recent.append({
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
        })

    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "enabled": bool(config.get("enabled")),
        "config": {"referrer_reward_points": int(config.get("referrer_reward_points") or 50),
                   "referee_reward_points": int(config.get("referee_reward_points") or 25),
                   "minimum_visits_to_earn": int(config.get("minimum_visits_to_earn") or 1)},
        "cards": cards,
        "series": series,
        "breakdown": {"total": total_seg, "segments": breakdown},
        "top_parrains": top,
        "recent": recent,
        "total_referrals": len(rows),
        "sources": [{"key": k, "label": v} for k, v in SOURCES.items()],
    }


@router.get("/api/owner/referrals/share")
def share_links(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    """The programme's own invitation links, one per channel.

    A merchant shares the programme itself (a poster, a story, a WhatsApp
    message); the ?src= is what later fills the table's Source column, so each
    channel gets its own link rather than one link for everything.
    """
    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    slug = tenant.get("slug") or ""
    base = f"{_public_url()}/join/{slug}"
    return {
        "slug": slug,
        "links": [{"key": k, "label": v, "url": f"{base}?ref=PROGRAMME&src={k}"}
                  for k, v in SOURCES.items() if k != "other"],
        "join_url": base,
    }


def _public_url() -> str:
    import os
    return (os.getenv("PUBLIC_APP_URL") or os.getenv("PUBLIC_SITE_URL")
            or "https://app.fidclic.com").rstrip("/")


@router.get("/api/owner/referrals/export")
def export_referrals(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    """Every parrainage of the period — the table without its ten-row limit."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    rows = _rows_between(tid, start, end)
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
