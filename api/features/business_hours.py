"""
Business hours, weekly closing day, French public holidays, and annual closures.

Status: ✅ Implemented.
Mounts at: /api/owner/settings/hours/*
Storage: tenant doc fields `weekly_schedule`, `holiday_closures`, `annual_closures`

Why this exists:
  Without it, FidClic would happily fire 'come visit today!' messages on
  Easter Monday (when most cafés are closed) — embarrassing the merchant
  and frustrating the customer. This module:

  1. Lets the owner declare the weekly rhythm (fermé le lundi, etc.)
  2. Lists the 11 French public holidays for the next 2 years (with movable
     feasts computed via dateutil.easter)
  3. Lets the owner tick which holidays they close for
  4. Lets the owner add free-form annual closures (vacances août 5–25)
  5. Exposes `is_open_on(tenant, date)` for any other module to check

Other modules (auto_campaigns.py, push, geolocation) check `is_open_on()`
before firing time-sensitive notifications.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta, date
from typing import Optional, Dict, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import require_role

# dateutil is now in requirements.txt
try:
    from dateutil.easter import easter
except ImportError:                                          # graceful no-op fallback
    def easter(_y: int) -> date:                              # type: ignore
        return date(_y, 4, 1)


router = APIRouter(tags=["business-hours"])
_db = None


def init(db):
    global _db
    _db = db


# ─── Default weekly schedule (every day open 7-19h) ────────────────────────
DEFAULT_WEEKLY = [
    {"day": "monday",    "open_from": "07:00", "open_to": "19:00", "closed": False},
    {"day": "tuesday",   "open_from": "07:00", "open_to": "19:00", "closed": False},
    {"day": "wednesday", "open_from": "07:00", "open_to": "19:00", "closed": False},
    {"day": "thursday",  "open_from": "07:00", "open_to": "19:00", "closed": False},
    {"day": "friday",    "open_from": "07:00", "open_to": "22:00", "closed": False},
    {"day": "saturday",  "open_from": "09:00", "open_to": "22:00", "closed": False},
    {"day": "sunday",    "open_from": "09:00", "open_to": "13:00", "closed": False},
]

# Mon=0 .. Sun=6 mapping to the schedule index
DAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


# ─── French public holidays — fixed dates + movable (Easter-based) ─────────
def french_public_holidays(year: int) -> List[Dict[str, str]]:
    """Return the 11 public holidays for a given year, with French names + ISO date."""
    e = easter(year)                                         # Easter Sunday → moves the 3 movable feasts
    return [
        {"key": "jour_de_lan",       "name": "Jour de l'An",        "date": f"{year}-01-01"},
        {"key": "lundi_paques",      "name": "Lundi de Pâques",     "date": (e + timedelta(days=1)).isoformat()},
        {"key": "fete_du_travail",   "name": "Fête du Travail",     "date": f"{year}-05-01"},
        {"key": "victoire_1945",     "name": "Victoire 1945",       "date": f"{year}-05-08"},
        {"key": "ascension",         "name": "Ascension",           "date": (e + timedelta(days=39)).isoformat()},
        {"key": "lundi_pentecote",   "name": "Lundi de Pentecôte",  "date": (e + timedelta(days=50)).isoformat()},
        {"key": "fete_nationale",    "name": "Fête nationale",      "date": f"{year}-07-14"},
        {"key": "assomption",        "name": "Assomption",          "date": f"{year}-08-15"},
        {"key": "toussaint",         "name": "Toussaint",           "date": f"{year}-11-01"},
        {"key": "armistice",         "name": "Armistice 1918",      "date": f"{year}-11-11"},
        {"key": "noel",              "name": "Noël",                "date": f"{year}-12-25"},
    ]


def _resolve_tenant(tenant_id: str) -> dict:
    return _db.tenants.find_one({"id": tenant_id}) or {}


def _resolve_weekly(tenant: dict) -> List[dict]:
    """Get the tenant's weekly schedule, falling back to defaults."""
    raw = tenant.get("weekly_schedule")
    if isinstance(raw, list) and len(raw) == 7:
        return raw
    return DEFAULT_WEEKLY


def is_open_on(tenant_id: str, target: date) -> bool:
    """Public helper: is `tenant_id` open on `target` date?

    Other modules (auto_campaigns, push) call this BEFORE firing any
    'come visit' message to avoid pushing on a closed day.

    Closed if:
      - the weekly schedule for that weekday says closed=True, OR
      - the date is in `holiday_closures` (owner ticked this holiday), OR
      - the date falls inside any range in `annual_closures`
    """
    if _db is None:
        return True                                          # safe default — don't block messages
    tenant = _resolve_tenant(tenant_id)
    if not tenant:
        return True

    # 1. Weekly rhythm
    weekly = _resolve_weekly(tenant)
    weekday_idx = target.weekday()                           # 0=Mon..6=Sun
    if weekday_idx < len(weekly) and weekly[weekday_idx].get("closed"):
        return False

    iso = target.isoformat()

    # 2. Holiday closures (e.g. {"2026-04-13": true})
    holidays = tenant.get("holiday_closures") or {}
    if isinstance(holidays, dict) and holidays.get(iso):
        return False

    # 3. Annual closure ranges (vacances) — list of {"start": "2026-08-05", "end": "2026-08-25"}
    annual = tenant.get("annual_closures") or []
    for window in annual:
        try:
            start = date.fromisoformat(window.get("start"))
            end = date.fromisoformat(window.get("end"))
            if start <= target <= end:
                return False
        except Exception:
            continue

    return True


# ─── API endpoints ─────────────────────────────────────────────────────────
class WeeklyDay(BaseModel):
    day: str
    open_from: Optional[str] = "07:00"
    open_to: Optional[str] = "19:00"
    closed: bool = False


@router.get("/api/owner/settings/hours")
def get_hours(token_data=Depends(require_role(["business_owner", "manager"]))):
    """Returns:
      - weekly_schedule:    7-day rhythm
      - holiday_closures:   { "YYYY-MM-DD": true } for ticked closures
      - annual_closures:    list of {start, end} ranges
      - upcoming_holidays:  next 24 months of French public holidays (with `closed: bool`)
    """
    tenant = _resolve_tenant(token_data.tenant_id)
    weekly = _resolve_weekly(tenant)
    closures = tenant.get("holiday_closures") or {}
    annual = tenant.get("annual_closures") or []

    # Generate 2 years of upcoming public holidays
    now = datetime.now(timezone.utc)
    today = now.date()
    upcoming: List[Dict[str, Any]] = []
    for y in (today.year, today.year + 1):
        for h in french_public_holidays(y):
            try:
                hd = date.fromisoformat(h["date"])
            except Exception:
                continue
            if hd < today:
                continue                                     # skip past holidays
            upcoming.append({
                **h,
                "weekday": hd.strftime("%A"),
                "closed": bool(closures.get(h["date"])),
            })
    upcoming.sort(key=lambda h: h["date"])

    return {
        "weekly_schedule": weekly,
        "holiday_closures": closures,
        "annual_closures": annual,
        "upcoming_holidays": upcoming,
    }


@router.put("/api/owner/settings/hours/weekly")
def set_weekly(
    payload: Dict[str, Any],
    token_data=Depends(require_role(["business_owner"])),
):
    """payload: { weekly_schedule: [ {day, open_from, open_to, closed}, ... ] }"""
    weekly = payload.get("weekly_schedule")
    if not isinstance(weekly, list) or len(weekly) != 7:
        raise HTTPException(status_code=400, detail="weekly_schedule must be a 7-element list")
    cleaned = []
    for entry in weekly:
        cleaned.append({
            "day": entry.get("day", "").lower(),
            "open_from": str(entry.get("open_from") or "07:00"),
            "open_to":   str(entry.get("open_to")   or "19:00"),
            "closed":    bool(entry.get("closed")),
        })
    _db.tenants.update_one(
        {"id": token_data.tenant_id},
        {"$set": {"weekly_schedule": cleaned}},
    )
    return {"ok": True, "weekly_schedule": cleaned}


@router.put("/api/owner/settings/hours/holidays")
def set_holidays(
    payload: Dict[str, Any],
    token_data=Depends(require_role(["business_owner"])),
):
    """payload: { holiday_closures: { "YYYY-MM-DD": true, ... } }"""
    closures = payload.get("holiday_closures") or {}
    if not isinstance(closures, dict):
        raise HTTPException(status_code=400, detail="holiday_closures must be a dict")
    cleaned = {k: bool(v) for k, v in closures.items() if isinstance(k, str) and len(k) == 10}
    _db.tenants.update_one(
        {"id": token_data.tenant_id},
        {"$set": {"holiday_closures": cleaned}},
    )
    return {"ok": True, "holiday_closures": cleaned}


@router.put("/api/owner/settings/hours/annual")
def set_annual(
    payload: Dict[str, Any],
    token_data=Depends(require_role(["business_owner"])),
):
    """payload: { annual_closures: [ {start: "YYYY-MM-DD", end: "YYYY-MM-DD", label?: "Vacances août"}, ... ] }"""
    items = payload.get("annual_closures") or []
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="annual_closures must be a list")
    cleaned = []
    for item in items:
        try:
            s = date.fromisoformat(item.get("start"))
            e = date.fromisoformat(item.get("end"))
            if s > e:
                continue
            cleaned.append({
                "start": s.isoformat(),
                "end": e.isoformat(),
                "label": str(item.get("label") or "Fermeture annuelle"),
            })
        except Exception:
            continue
    _db.tenants.update_one(
        {"id": token_data.tenant_id},
        {"$set": {"annual_closures": cleaned}},
    )
    return {"ok": True, "annual_closures": cleaned}


@router.get("/api/owner/settings/hours/is-open")
def check_is_open(
    target: Optional[str] = None,                            # YYYY-MM-DD; default today
    token_data=Depends(require_role(["business_owner", "manager"])),
):
    """Convenience endpoint — useful for the Settings UI to preview the next
    'closed' date so the owner sees a confirmation."""
    if target:
        try:
            t = date.fromisoformat(target)
        except Exception:
            raise HTTPException(status_code=400, detail="target must be YYYY-MM-DD")
    else:
        t = datetime.now(timezone.utc).date()
    return {"date": t.isoformat(), "is_open": is_open_on(token_data.tenant_id, t)}
