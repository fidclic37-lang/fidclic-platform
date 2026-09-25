"""
Clients — the page's own API: four figures, eight quick segments, one table.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/clients/overview  → the four figures and the segment counts
    GET /api/owner/clients/list      → the table: filtered, sorted, paginated
    GET /api/owner/clients/export    → the same rows as CSV

WHY A SECOND ENDPOINT NEXT TO /api/owner/customers
    That one answers "give me the customers matching these filters" and hands
    back a plain array — no total, no page, no segment counts. Four pages and a
    dozen features read it, so it is left exactly as it is; this module adds
    what the Clients page needs on top and nothing else changes.

THE VOCABULARY, DEFINED ONCE
    The page shows a status and a segment against every client, and both have
    to mean the same thing in the figures, the chips and the rows. They are
    computed in one place — `classify` — from real columns:

      Statut    Inactif   no visit for INACTIVE_DAYS (30) or never
                Fidèle    LOYAL_VISITS (5) visits or more
                Actif     everyone else who has been in

      Segments  the eight chips, each a plain predicate over the same row.
                "Clients locaux" is the only one that needs more than the
                customer document: it asks services.communes / the catchment
                radius how far away they live.
"""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from auth import require_role, TokenData

router = APIRouter(tags=["clients"])
_db = None

INACTIVE_DAYS = 30          # no visit for this long → inactif
LOYAL_VISITS = 5            # this many visits or more → fidèle
NEW_DAYS = 30               # joined inside this → nouveau
BIG_BASKET_FACTOR = 1.5     # average ticket this many times the shop's → gros panier
LOCAL_KM = 5.0              # inside the catchment's first ring → client local
MAX_PER_PAGE = 100

STATUSES = {
    "loyal":    {"label": "Fidèle",  "tone": "green"},
    "active":   {"label": "Actif",   "tone": "blue"},
    "inactive": {"label": "Inactif", "tone": "rose"},
}

SEGMENTS: List[Dict[str, str]] = [
    {"key": "all",       "label": "Tous les clients",     "icon": "users",  "tone": "blue"},
    {"key": "loyal",     "label": "Clients fidèles",      "icon": "crown",  "tone": "amber"},
    {"key": "inactive",  "label": "Clients inactifs",     "icon": "send",   "tone": "rose"},
    {"key": "new",       "label": "Nouveaux clients",     "icon": "userplus", "tone": "violet"},
    {"key": "big",       "label": "Gros paniers",         "icon": "bag",    "tone": "orange"},
    {"key": "local",     "label": "Clients locaux",       "icon": "pin",    "tone": "blue"},
    {"key": "birthday",  "label": "Anniversaires du mois", "icon": "gift",  "tone": "violet"},
    {"key": "vip",       "label": "VIP",                  "icon": "star",   "tone": "amber"},
]


def init(db):
    global _db
    _db = db
    try:
        _db.customers.create_index([("tenant_id", 1), ("created_at", -1)])
    except Exception:
        pass


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


# ---------------------------------------------------------------------------
# the vocabulary
# ---------------------------------------------------------------------------
def status_of(cust: Dict[str, Any], at: datetime) -> str:
    """Inactif wins over fidèle: a client with forty visits who has not been in
    for three months is a problem, not a success, and the page should say so."""
    last = _aware(cust.get("last_visit_date"))
    if not last or (at - last).days >= INACTIVE_DAYS:
        return "inactive"
    if int(cust.get("visits") or 0) >= LOYAL_VISITS:
        return "loyal"
    return "active"


def _avg_ticket(cust: Dict[str, Any]) -> float:
    visits = int(cust.get("visits") or 0)
    if visits <= 0:
        return 0.0
    return float(cust.get("total_amount_paid") or 0) / visits


def segment_of(cust: Dict[str, Any], at: datetime, shop_avg: float,
               local_ids: Optional[set] = None) -> str:
    """The one chip a client is shown under in the table. Most specific first,
    so a VIP reads VIP rather than "fidèle like everybody else"."""
    if (cust.get("tier") or "").lower() == "vip":
        return "vip"
    created = _aware(cust.get("created_at"))
    if created and (at - created).days <= NEW_DAYS:
        return "new"
    if shop_avg and _avg_ticket(cust) >= shop_avg * BIG_BASKET_FACTOR:
        return "big"
    if int(cust.get("visits") or 0) >= LOYAL_VISITS:
        return "loyal"
    if local_ids is not None and cust.get("id") in local_ids:
        return "local"
    return "active"


def _matches_segment(key: str, cust: Dict[str, Any], at: datetime,
                     shop_avg: float, local_ids: set) -> bool:
    """A chip's own predicate. Deliberately NOT `segment_of(...) == key`: the
    chips overlap on purpose — a VIP is also a fidèle, and clicking "Clients
    fidèles" should show them."""
    if key == "all":
        return True
    if key == "loyal":
        return int(cust.get("visits") or 0) >= LOYAL_VISITS
    if key == "inactive":
        return status_of(cust, at) == "inactive"
    if key == "new":
        created = _aware(cust.get("created_at"))
        return bool(created and (at - created).days <= NEW_DAYS)
    if key == "big":
        return bool(shop_avg) and _avg_ticket(cust) >= shop_avg * BIG_BASKET_FACTOR
    if key == "local":
        return cust.get("id") in local_ids
    if key == "birthday":
        return str(cust.get("birthday") or "")[:2] == at.strftime("%m")
    if key == "vip":
        return (cust.get("tier") or "").lower() == "vip"
    return True


# ---------------------------------------------------------------------------
# the shop's own numbers, needed before any client can be classified
# ---------------------------------------------------------------------------
def _shop_average_ticket(rows: List[Dict[str, Any]]) -> float:
    spend = sum(float(c.get("total_amount_paid") or 0) for c in rows)
    visits = sum(int(c.get("visits") or 0) for c in rows)
    return (spend / visits) if visits else 0.0


def _local_ids(tid: str, rows: List[Dict[str, Any]]) -> set:
    """Who lives inside the first catchment ring. Reuses the Géolocalisation
    machinery rather than inventing a second idea of "near"."""
    try:
        from features import geolocation as geo
    except Exception:
        return set()
    tenant = (_db.tenants.find_one({"id": tid}) or {})
    lat, lng, _src = geo._shop_position(tenant)
    if lat is None:
        return set()
    near = set()
    for c in rows:
        clat, clng, _how = geo._client_position(c)
        if clat is None:
            continue
        if geo._haversine_km(lat, lng, clat, clng) <= LOCAL_KM:
            near.add(c["id"])
    return near


FIELDS = {"_id": 0, "id": 1, "name": 1, "email": 1, "phone": 1, "tier": 1, "visits": 1,
          "points": 1, "total_amount_paid": 1, "created_at": 1, "last_visit_date": 1,
          "birthday": 1, "postal_code": 1, "city": 1, "barcode_id": 1,
          "latitude": 1, "longitude": 1, "is_student": 1}


def _load(tid: str) -> List[Dict[str, Any]]:
    return list(_db.customers.find({"tenant_id": tid}, FIELDS))


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace("-", " ").split() if p]
    if not parts:
        return "?"
    return (parts[0][:2] if len(parts) == 1 else parts[0][0] + parts[-1][0]).upper()


def _public(cust: Dict[str, Any], at: datetime, shop_avg: float, local_ids: set) -> Dict[str, Any]:
    st = status_of(cust, at)
    seg = segment_of(cust, at, shop_avg, local_ids)
    last = _aware(cust.get("last_visit_date"))
    joined = _aware(cust.get("created_at"))
    return {
        "id": cust["id"], "name": cust.get("name") or "Client",
        "initials": _initials(cust.get("name") or ""),
        "email": cust.get("email") or "", "phone": cust.get("phone") or "",
        "barcode_id": cust.get("barcode_id"),
        "tier": (cust.get("tier") or "bronze").lower(),
        "status": st, "status_label": STATUSES[st]["label"], "status_tone": STATUSES[st]["tone"],
        "segment": seg,
        "segment_label": next((s["label"] for s in SEGMENTS if s["key"] == seg), "Actif"),
        "visits": int(cust.get("visits") or 0),
        "spent": round(float(cust.get("total_amount_paid") or 0), 2),
        "last_visit": last.isoformat() if last else None,
        "joined": joined.isoformat() if joined else None,
        "city": cust.get("city") or "",
    }


SORTS: Dict[str, Tuple[Callable[[Dict[str, Any]], Any], bool]] = {
    "recent":  (lambda c: _aware(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), True),
    "oldest":  (lambda c: _aware(c.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc), False),
    "name":    (lambda c: (c.get("name") or "").lower(), False),
    "spend":   (lambda c: float(c.get("total_amount_paid") or 0), True),
    "visits":  (lambda c: int(c.get("visits") or 0), True),
    "last":    (lambda c: _aware(c.get("last_visit_date")) or datetime.min.replace(tzinfo=timezone.utc), True),
}
SORT_LABELS = [
    {"key": "recent", "label": "Date d'inscription (plus récent)"},
    {"key": "oldest", "label": "Date d'inscription (plus ancien)"},
    {"key": "name",   "label": "Nom (A → Z)"},
    {"key": "spend",  "label": "Total dépensé (plus élevé)"},
    {"key": "visits", "label": "Visites (plus nombreuses)"},
    {"key": "last",   "label": "Dernière visite (plus récente)"},
]

SPEND_BANDS = {
    "lt50":   (0.0, 50.0), "50_150": (50.0, 150.0),
    "150_500": (150.0, 500.0), "gt500": (500.0, None),
}
JOINED_BANDS = {"30d": 30, "90d": 90, "1y": 365}


def _filtered(rows: List[Dict[str, Any]], at: datetime, shop_avg: float, local_ids: set,
              segment: str, status: str, spend: str, joined: str, search: str) -> List[Dict[str, Any]]:
    out = []
    needle = (search or "").strip().lower()
    for c in rows:
        if segment and segment != "all" and not _matches_segment(segment, c, at, shop_avg, local_ids):
            continue
        if status and status_of(c, at) != status:
            continue
        if spend in SPEND_BANDS:
            low, high = SPEND_BANDS[spend]
            total = float(c.get("total_amount_paid") or 0)
            if total < low or (high is not None and total >= high):
                continue
        if joined in JOINED_BANDS:
            created = _aware(c.get("created_at"))
            if not created or (at - created).days > JOINED_BANDS[joined]:
                continue
        if needle:
            hay = f"{c.get('name') or ''} {c.get('email') or ''} {c.get('phone') or ''} {c.get('barcode_id') or ''}".lower()
            if needle not in hay:
                continue
        out.append(c)
    return out


def _delta(now_value: float, was_value: float) -> Optional[int]:
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@router.get("/api/owner/clients/overview")
def overview(token_data: TokenData = Depends(require_role(["business_owner", "manager"]))):
    tid = token_data.tenant_id
    at = _now()
    rows = _load(tid)
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)

    total = len(rows)
    loyal = sum(1 for c in rows if int(c.get("visits") or 0) >= LOYAL_VISITS)
    inactive = sum(1 for c in rows if status_of(c, at) == "inactive")
    month_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = sum(1 for c in rows
                         if (_aware(c.get("created_at")) or at) >= month_start)

    # The month before, for the comparison the design puts under each figure.
    prev_end = month_start - timedelta(microseconds=1)
    prev_start = prev_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    before = [c for c in rows if (_aware(c.get("created_at")) or at) < month_start]
    prev_new = sum(1 for c in rows
                   if prev_start <= (_aware(c.get("created_at")) or at) <= prev_end)
    prev_loyal = sum(1 for c in before if int(c.get("visits") or 0) >= LOYAL_VISITS)
    prev_inactive = sum(1 for c in before if status_of(c, prev_end) == "inactive")

    return {
        "cards": [
            {"key": "total", "label": "Clients total", "icon": "users", "tone": "blue",
             "value": total, "delta_pct": _delta(total, len(before)), "note": "vs mois précédent"},
            {"key": "loyal", "label": "Clients fidèles", "icon": "crown", "tone": "amber",
             "value": loyal, "delta_pct": _delta(loyal, prev_loyal), "note": "vs mois précédent"},
            {"key": "inactive", "label": "Clients inactifs", "icon": "send", "tone": "rose",
             "value": inactive, "delta_pct": _delta(inactive, prev_inactive),
             "note": "vs mois précédent", "lower_is_better": True},
            {"key": "new", "label": "Nouveaux clients", "icon": "userplus", "tone": "violet",
             "value": new_this_month, "delta_pct": _delta(new_this_month, prev_new),
             "note": "ce mois-ci"},
        ],
        "segments": [{**s, "count": sum(1 for c in rows
                                        if _matches_segment(s["key"], c, at, shop_avg, local))}
                     for s in SEGMENTS],
        "sorts": SORT_LABELS,
        "statuses": [{"key": k, "label": v["label"], "tone": v["tone"]} for k, v in STATUSES.items()],
        "shop_average_ticket": round(shop_avg, 2),
        "definitions": {
            "loyal_visits": LOYAL_VISITS, "inactive_days": INACTIVE_DAYS,
            "new_days": NEW_DAYS, "big_basket_factor": BIG_BASKET_FACTOR, "local_km": LOCAL_KM,
        },
    }


@router.get("/api/owner/clients/list")
def list_page(
    segment: str = "all",
    status: str = "",
    spend: str = "",
    joined: str = "",
    search: str = "",
    sort: str = "recent",
    page: int = 1,
    per_page: int = 10,
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    tid = token_data.tenant_id
    at = _now()
    per_page = max(1, min(MAX_PER_PAGE, int(per_page or 10)))
    page = max(1, int(page or 1))

    rows = _load(tid)
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)
    rows = _filtered(rows, at, shop_avg, local, segment, status, spend, joined, search)

    key, reverse = SORTS.get(sort, SORTS["recent"])
    rows.sort(key=key, reverse=reverse)

    total = len(rows)
    window = rows[(page - 1) * per_page: page * per_page]
    return {
        "rows": [_public(c, at, shop_avg, local) for c in window],
        "total": total, "page": page, "per_page": per_page,
        "pages": max(1, math.ceil(total / per_page)),
    }


@router.get("/api/owner/clients/export")
def export_clients(
    segment: str = "all", status: str = "", spend: str = "", joined: str = "",
    search: str = "", sort: str = "recent",
    token_data: TokenData = Depends(require_role(["business_owner", "manager"])),
):
    """Every client the filters select — the table without its page limit."""
    tid = token_data.tenant_id
    at = _now()
    rows = _load(tid)
    shop_avg = _shop_average_ticket(rows)
    local = _local_ids(tid, rows)
    rows = _filtered(rows, at, shop_avg, local, segment, status, spend, joined, search)
    key, reverse = SORTS.get(sort, SORTS["recent"])
    rows.sort(key=key, reverse=reverse)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Client", "Email", "Téléphone", "Statut", "Segment", "Visites",
                "Total dépensé (€)", "Dernière visite", "Inscription", "Ville"])
    for c in rows:
        p = _public(c, at, shop_avg, local)
        w.writerow([p["name"], p["email"], p["phone"], p["status_label"], p["segment_label"],
                    p["visits"], f"{p['spent']:.2f}".replace(".", ","),
                    (p["last_visit"] or "")[:10], (p["joined"] or "")[:10], p["city"]])
    data = "﻿" + buf.getvalue()
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             f'attachment; filename="fidclic-clients-{at:%Y%m%d}.csv"'})
