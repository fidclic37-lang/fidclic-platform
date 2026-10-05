"""
Super admin › Commerces — every business on FidClic, its health, and one
page per business. Built to the approved mockups (« Tous les commerces »,
« Café Lumière »).

STATUT (decided with the user, 2026-10-01) is how much the business
actually uses FidClic, per week: new loyalty cards given AND scans (visits),
over the last `window_days` days brought to a week (or since sign-up when
younger). The weaker of the two decides:
    actif      both above actif_min            (default 25 a week)
    à risque   the weaker between inactif_max and actif_min (15–25)
    inactif    the weaker below inactif_max     (default 15 a week)
    suspendu   switched off by the super admin (see below)
    résilié    the client told us they stop — marked by the team (see below)
    essai non converti  the trial ended without a subscription
The super admin can change the numbers (platform_settings).

STANDING (where the business stands with FidClic, standing_of): en essai,
abonné (paid subscription running), impayé (stopped paying, or suspended —
the same thing for the user), résilié, essai non converti.

RÉSILIER (decided with the user, 2026-10-01): marked by hand when the client
says they stop. The account closes at once (team sessions end, sign-in
refused) AND the customers' cards stop working (card page, wallet updates,
joining). Nothing is deleted; « Annuler la résiliation » reopens everything.

SUSPENDRE (decided with the user): the owner and the team can no longer
sign in (their sessions end at once); the customers' cards keep working.

ACCÉDER AU COMPTE (decided with the user): opens the business's dashboard
read-only — a 30-minute token flagged view_only; auth refuses every call
that is not a read, the page shows a banner, and each opening is audited.
"""
from __future__ import annotations

import csv
import io
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData, create_access_token, hash_password

router = APIRouter(tags=["admin"])
from features.platform_access import require_admin
_db = None
ADMIN = ["super_admin"]
# v2 (2026-10-01): weekly cards AND scans — the old per-day numbers are not reused.
RULES_KEY = "commerce_status_rules_v2"
DEFAULT_RULES = {"actif_min": 25, "inactif_max": 15, "window_days": 7}
STATUS_LABELS = {"actif": "Actif", "a_risque": "À risque", "inactif": "Inactif", "suspendu": "Suspendu",
                 "resilie": "Résilié", "non_converti": "Essai non converti"}
STANDING_LABELS = {"essai": "En essai", "abonne": "Abonné", "impaye": "Impayé", "resilie": "Résilié", "non_converti": "Essai non converti"}
TEAM = ["business_owner", "administrateur", "manager", "staff"]
VIEW_MINUTES = 30


def init(db):
    global _db
    _db = db
    import auth
    auth.set_tenant_check(is_suspended)
    auth.set_act_hook(_log_act)


def _log_act(admin: str, tid: Optional[str], method: str, path: str) -> None:
    """A change made from « Accéder au compte »: the business's own records
    show the owner's account, the audit says which admin really did it."""
    import server as core
    core.log_audit("admin.act_as.write", actor=admin, actor_type="user", target=tid, tenant_id=tid,
                   meta={"method": method, "path": path[:200]})


def _can_act(token_data: TokenData) -> bool:
    """Full access to a business's account: the Super Admin, and a team member
    allowed to « Modifier » Commerces. The others may only look."""
    if token_data.role == "super_admin":
        return True
    from features.platform_access import perms_for
    return bool(((perms_for(token_data.email) or {}).get("commerces") or {}).get("edit"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(v: Any) -> Optional[str]:
    v = _aware(v)
    return v.isoformat() if v else None


def _delta(cur: float, prev: float) -> Optional[int]:
    return round((cur - prev) / prev * 100) if prev else None


def rules() -> Dict[str, Any]:
    doc = (_db.platform_settings.find_one({"key": RULES_KEY}, {"_id": 0}) or {}).get("value") or {}
    return {**DEFAULT_RULES, **{k: v for k, v in doc.items() if k in DEFAULT_RULES}}


LIVE = {"$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}], "card_deleted_at": {"$exists": False}}


def _count_by_tenant(coll: str, match: Dict[str, Any]) -> Dict[str, int]:
    return {r["_id"]: r["n"] for r in _db[coll].aggregate([{"$match": match}, {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}}}])}


def _plan_label(t: Dict[str, Any]) -> Dict[str, str]:
    import server as core
    key = core._canonical_plan(t.get("plan"))
    status = (t.get("subscription_status") or "").lower()
    if status in ("trialing", "onboarding") or (not status and t.get("trial_ends_at")):
        return {"key": "essai", "label": "Essai"}
    custom = core.custom_plans().get(key)
    if custom:
        return {"key": key, "label": custom.get("label") or key, "color": custom.get("color"), "custom": True}
    return {"key": key, "label": core.PLAN_LABELS.get(key, key.title())}


def _sector(key: Optional[str]) -> str:
    from features.crm import _sector_label
    return _sector_label(key or "")


def standing_of(t: Dict[str, Any], now: Optional[datetime] = None) -> str:
    """Where the business stands with FidClic — shared by the Commerces
    page, the Dashboard, Analytics and Support."""
    now = now or _now()
    if t.get("resiliated_at"):
        return "resilie"
    status = (t.get("subscription_status") or "").lower()
    if t.get("suspended_at") or status in ("past_due", "unpaid"):
        return "impaye"
    if status == "active":
        return "abonne"
    trial_end = _aware(t.get("trial_ends_at"))
    if status in ("trialing", "onboarding") or (not status and trial_end):
        return "non_converti" if trial_end and trial_end < now else "essai"
    if status in ("canceled", "cancelled", "incomplete_expired"):
        # Never paid → a trial that did not convert; paid then cancelled
        # through Stripe → treated as résilié (the team marks the others).
        return "resilie" if t.get("subscription_started_at") else "non_converti"
    # No subscription data at all: a business FidClic set up by hand (demo
    # accounts, early clients) — on its plan, as the Commerces page shows it.
    return "abonne"


def status_of(t: Dict[str, Any], new_cards: int, r: Dict[str, Any], now: datetime, scans: int = 0) -> Dict[str, Any]:
    if t.get("suspended_at"):
        return {"key": "suspendu", "cards_week": None, "scans_week": None}
    standing = standing_of(t, now)
    if standing in ("resilie", "non_converti"):
        return {"key": standing, "cards_week": None, "scans_week": None}
    created = _aware(t.get("created_at")) or now
    days = max(1.0, min(float(r["window_days"]), (now - created).total_seconds() / 86400))
    cards_w, scans_w = new_cards / days * 7, scans / days * 7
    weaker = min(cards_w, scans_w)
    key = "actif" if weaker > r["actif_min"] else "a_risque" if weaker >= r["inactif_max"] else "inactif"
    return {"key": key, "cards_week": round(cards_w, 1), "scans_week": round(scans_w, 1)}


def snapshot(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One row per business with its figures and its statut — shared by the
    list, the dashboard and the exports."""
    now = now or _now()
    r = rules()
    since = now - timedelta(days=int(r["window_days"]))
    tenants = list(_db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0}))
    # One pass over the customers, not over every visit: each customer keeps
    # its own visit count (never decremented) and its last visit date.
    clients, visits, last = {}, {}, {}
    for x in _db.customers.aggregate([{"$match": LIVE}, {"$group": {"_id": "$tenant_id", "n": {"$sum": 1}, "v": {"$sum": "$visits"},
                                                                    "at": {"$max": "$last_visit_date"}}}]):
        clients[x["_id"]], visits[x["_id"]], last[x["_id"]] = x["n"], int(x.get("v") or 0), x.get("at")
    cards = _count_by_tenant("customers", {**LIVE, "created_at": {"$gte": since}})
    scans = _count_by_tenant("visits", {"visit_time": {"$gte": since}})
    logos = {c["tenant_id"]: c.get("logo_url") or (c.get("brand_fields") or {}).get("logo_url")
             for c in _db.card_templates.find({}, {"_id": 0, "tenant_id": 1, "logo_url": 1, "brand_fields.logo_url": 1})}
    rows = []
    for t in tenants:
        st = status_of(t, cards.get(t["id"], 0), r, now, scans.get(t["id"], 0))
        standing = standing_of(t, now)
        la = _aware(last.get(t["id"]))
        rows.append({"id": t["id"], "name": t.get("name") or "—", "sector": _sector(t.get("sector")), "city": t.get("city") or "",
                     "postal_code": t.get("postal_code") or "", "plan": _plan_label(t), "logo": logos.get(t["id"]),
                     "clients": clients.get(t["id"], 0), "visits": visits.get(t["id"], 0), "cards_window": cards.get(t["id"], 0),
                     "cards_week": st["cards_week"], "scans_week": st["scans_week"], "last_activity": la.isoformat() if la else None,
                     "standing": standing, "standing_label": STANDING_LABELS[standing],
                     "status": st["key"], "status_label": STATUS_LABELS[st["key"]],
                     "created_at": _iso(t.get("created_at")), "new_this_month": bool(_aware(t.get("created_at")) and
                                                                                    _aware(t.get("created_at")) >= now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)),
                     "subscription_status": t.get("subscription_status"), "suspended": bool(t.get("suspended_at"))})
    return rows


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
class RulesIn(BaseModel):
    actif_min: float = Field(..., gt=0, le=100000)       # a week, cards AND scans
    inactif_max: float = Field(..., ge=0, le=100000)
    window_days: int = Field(7, ge=1, le=90)


@router.get("/api/admin/commerces/rules")
def get_rules(token_data: TokenData = Depends(require_admin("commerces"))):
    return rules()


@router.put("/api/admin/commerces/rules")
def put_rules(body: RulesIn, token_data: TokenData = Depends(require_admin("commerces"))):
    if body.inactif_max > body.actif_min:
        raise HTTPException(status_code=400, detail="Le seuil « Inactif » doit être plus petit que le seuil « Actif ».")
    _db.platform_settings.update_one({"key": RULES_KEY}, {"$set": {"key": RULES_KEY, "value": body.dict(), "updated_at": _now(),
                                                                   "updated_by": token_data.email}}, upsert=True)
    return rules()


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
TABS = ("actif", "inactif", "a_risque", "nouveaux", "suspendu", "resilie", "non_converti")
SORTS = {"name": lambda r: (r["name"] or "").lower(), "clients": lambda r: r["clients"], "visits": lambda r: r["visits"],
         "last_activity": lambda r: r["last_activity"] or "", "status": lambda r: r["status"], "created_at": lambda r: r["created_at"] or ""}


def _filtered(rows, tab="", q="", sector="", city="", plan="", status=""):
    out = rows
    if tab == "nouveaux":
        out = [r for r in out if r["new_this_month"]]
    elif tab in TABS:
        out = [r for r in out if r["status"] == tab]
    if q:
        f = q.strip().lower()
        out = [r for r in out if f in r["name"].lower() or f in r["city"].lower() or f in r["sector"].lower()]
    if sector:
        out = [r for r in out if r["sector"] == sector]
    if city:
        out = [r for r in out if r["city"] == city]
    if plan:
        out = [r for r in out if r["plan"]["key"] == plan]
    if status:
        out = [r for r in out if r["status"] == status]
    return out


def _cards(rows: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    total = len(rows)
    month_ago = now - timedelta(days=30)
    before = sum(1 for r in rows if _aware(r["created_at"]) and _aware(r["created_at"]) < month_ago)
    st = {k: sum(1 for r in rows if r["status"] == k) for k in STATUS_LABELS}
    pct = lambda n: round(n / total * 100) if total else 0      # noqa: E731
    clients = sum(r["clients"] for r in rows)
    clients_before = _db.customers.count_documents({**LIVE, "created_at": {"$lt": month_ago}})

    def cum(coll, match, field):
        return [(_db[coll].count_documents({**match, field: {"$lt": now - timedelta(days=30 * (7 - i))}})) for i in range(8)]
    return [
        {"key": "total", "value": total, "delta": _delta(total, before),
         "series": cum("tenants", {"is_active": {"$ne": False}}, "created_at")},
        {"key": "actif", "value": st["actif"], "pct": pct(st["actif"])},
        {"key": "inactif", "value": st["inactif"], "pct": pct(st["inactif"])},
        {"key": "a_risque", "value": st["a_risque"], "pct": pct(st["a_risque"])},
        {"key": "nouveaux", "value": sum(1 for r in rows if r["new_this_month"])},
        {"key": "clients", "value": clients, "delta": _delta(clients, clients_before), "series": cum("customers", LIVE, "created_at")},
    ]


@router.get("/api/admin/commerces")
def list_commerces(tab: str = "", q: str = "", sector: str = "", city: str = "", plan: str = "", status: str = "",
                   sort: str = "-clients", page: int = 1, per_page: int = 15,
                   token_data: TokenData = Depends(require_admin("commerces"))):
    now = _now()
    rows = snapshot(now)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    base = _filtered(rows, "", q, sector, city, plan, status)
    counts = {"all": len(base), **{k: len(_filtered(base, k)) for k in TABS}}
    out = _filtered(base, tab)
    key = sort.lstrip("-")
    out.sort(key=SORTS.get(key, SORTS["clients"]), reverse=sort.startswith("-"))
    total = len(out)
    return {"rows": out[(page - 1) * per_page: page * per_page], "total": total, "page": page, "per_page": per_page,
            "pages": max(1, -(-total // per_page)), "counts": counts, "cards": _cards(rows, now), "rules": rules(),
            "options": {"sectors": sorted({r["sector"] for r in rows if r["sector"]}),
                        "cities": sorted({r["city"] for r in rows if r["city"]}),
                        "plans": [{"key": "essai", "label": "Essai"}] + [{"key": k, "label": v} for k, v in
                                                                         __import__("models").PLAN_LABELS.items()]}}


@router.get("/api/admin/commerces/export")
def export_commerces(tab: str = "", q: str = "", sector: str = "", city: str = "", plan: str = "", status: str = "",
                     token_data: TokenData = Depends(require_admin("commerces"))):
    rows = _filtered(snapshot(), tab, q, sector, city, plan, status)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Commerce", "Secteur", "Ville", "Code postal", "Plan", "Clients", "Visites", "Cartes / semaine", "Scans / semaine",
                "Dernière activité", "Statut", "Situation", "Inscrit le"])
    for r in rows:
        w.writerow([r["name"], r["sector"], r["city"], r["postal_code"], r["plan"]["label"], r["clients"], r["visits"],
                    r["cards_week"] if r["cards_week"] is not None else "", r["scans_week"] if r["scans_week"] is not None else "",
                    r["last_activity"] or "", r["status_label"], r["standing_label"], (r["created_at"] or "")[:10]])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="commerces.csv"'})


# ---------------------------------------------------------------------------
# Add / edit
# ---------------------------------------------------------------------------
class CommerceIn(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    sector: Optional[str] = Field(None, max_length=80)
    city: Optional[str] = Field(None, max_length=80)
    postal_code: Optional[str] = Field(None, max_length=10)
    address: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=30)
    website: Optional[str] = Field(None, max_length=200)
    owner_email: Optional[str] = Field(None, max_length=200)
    owner_first_name: Optional[str] = Field(None, max_length=60)
    owner_last_name: Optional[str] = Field(None, max_length=60)


def _slug(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", name.lower())
    s = re.sub(r"[^a-z0-9]+", "-", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip("-") or "commerce"
    base, n = s, 2
    while _db.tenants.find_one({"slug": s}):
        s = f"{base}-{n}"; n += 1
    return s


@router.post("/api/admin/commerces")
def add_commerce(body: CommerceIn, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    name, email = (body.name or "").strip(), (body.owner_email or "").strip().lower()
    if not name or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Le nom du commerce et l'email du propriétaire sont obligatoires.")
    if _db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet email.")
    tid = str(uuid.uuid4())
    t = {"id": tid, "slug": _slug(name), "name": name, "plan": "silver", "sector": (body.sector or "").strip(),
         "city": (body.city or "").strip(), "postal_code": (body.postal_code or "").strip(), "address": (body.address or "").strip(),
         "phone": (body.phone or "").strip(), "website": (body.website or "").strip(), "branches": [], "is_active": True,
         "onboarding_status": "done", "created_at": _now(), "created_by_admin": token_data.email}
    core._start_trial(t)
    _db.tenants.insert_one(t)
    password = secrets.token_urlsafe(9)
    _db.users.insert_one({"email": email, "role": "business_owner", "tenant_id": tid, "first_name": (body.owner_first_name or "").strip(),
                          "last_name": (body.owner_last_name or "").strip(), "hashed_password": hash_password(password),
                          "auth_provider": "password", "created_at": _now()})
    core.log_audit("admin.commerce_create", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                   meta={"name": name, "owner": email})
    return {"id": tid, "owner": {"email": email, "password": password}}


@router.put("/api/admin/commerces/{tid}")
def edit_commerce(tid: str, body: CommerceIn, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    t = _db.tenants.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    sets = {k: v.strip() for k, v in body.dict(exclude_unset=True).items()
            if k in ("name", "sector", "city", "postal_code", "address", "phone", "website") and isinstance(v, str)}
    if "name" in sets and not sets["name"]:
        raise HTTPException(status_code=400, detail="Le nom ne peut pas être vide.")
    if sets:
        _db.tenants.update_one({"id": tid}, {"$set": sets})
        core.log_audit("admin.commerce_edit", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                       meta={"fields": sorted(sets)})
    return {"ok": True}


class PlanIn(BaseModel):
    plan: str


@router.post("/api/admin/commerces/{tid}/plan")
def change_plan(tid: str, body: PlanIn, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    t = _db.tenants.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    custom = core.custom_plans(refresh=True).get(body.plan)
    if body.plan not in ("silver", "gold", "vip") and not custom:
        raise HTTPException(status_code=400, detail="Pour la Franchise, fixez ses conditions (prix, limites).")
    if custom and custom.get("active") is False:
        raise HTTPException(status_code=400, detail="Cette offre est désactivée.")
    _db.tenants.update_one({"id": tid}, {"$set": {"plan": body.plan}})
    core.log_audit("admin.plan_change", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                   meta={"from": t.get("plan"), "to": body.plan})
    return {"plan": body.plan}


# ---------------------------------------------------------------------------
# Suspend / view as
# ---------------------------------------------------------------------------
class SuspendIn(BaseModel):
    reason: Optional[str] = Field(None, max_length=300)


@router.post("/api/admin/commerces/{tid}/suspend")
def suspend(tid: str, body: SuspendIn, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    t = _db.tenants.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    _db.tenants.update_one({"id": tid}, {"$set": {"suspended_at": _now(), "suspended_by": token_data.email,
                                                  "suspended_reason": (body.reason or "").strip()}})
    emails = [u["email"] for u in _db.users.find({"tenant_id": tid, "role": {"$in": TEAM}}, {"email": 1})]
    ended = _db.user_sessions.update_many({"email": {"$in": emails}, "revoked_at": None}, {"$set": {"revoked_at": _now()}}).modified_count
    core.log_audit("admin.commerce_suspend", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                   meta={"reason": body.reason, "sessions_ended": ended})
    forget(tid)
    return {"suspended": True, "sessions_ended": ended}


@router.post("/api/admin/commerces/{tid}/reactivate")
def reactivate(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    if not _db.tenants.find_one({"id": tid}):
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    _db.tenants.update_one({"id": tid}, {"$unset": {"suspended_at": "", "suspended_by": "", "suspended_reason": ""}})
    core.log_audit("admin.commerce_reactivate", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid)
    forget(tid)
    return {"suspended": False}


class ResilierIn(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)
    contacted_at: Optional[str] = None           # when the client told us (defaults to now)


def _end_sessions(tid: str) -> int:
    emails = [u["email"] for u in _db.users.find({"tenant_id": tid, "role": {"$in": TEAM}}, {"email": 1})]
    return _db.user_sessions.update_many({"email": {"$in": emails}, "revoked_at": None}, {"$set": {"revoked_at": _now()}}).modified_count


@router.post("/api/admin/commerces/{tid}/resilier")
def resilier(tid: str, body: ResilierIn, token_data: TokenData = Depends(require_admin("commerces"))):
    """The client told us they stop (user, 2026-10-01): the account closes at
    once and the customers' cards stop working. Nothing is deleted."""
    import server as core
    t = _db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    if t.get("resiliated_at"):
        raise HTTPException(status_code=409, detail="Ce commerce est déjà résilié.")
    if len(body.reason.strip()) < 2:
        raise HTTPException(status_code=400, detail="Indiquez la raison de la résiliation.")
    told = _aware(body.contacted_at) or _now()
    stripe_note = None
    if t.get("stripe_subscription_id"):
        try:
            from features import billing as BL
            if BL.is_configured():
                BL.stripe.Subscription.cancel(t["stripe_subscription_id"])
                stripe_note = "abonnement Stripe annulé"
        except Exception as exc:                          # noqa: BLE001
            stripe_note = f"Stripe : {str(exc)[:120]}"
    _db.tenants.update_one({"id": tid}, {"$set": {"resiliated_at": _now(), "resiliated_by": token_data.email,
                                                  "resiliation_reason": body.reason.strip(), "resiliation_told_at": told}})
    ended = _end_sessions(tid)
    core.log_audit("admin.commerce_resilie", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                   meta={"reason": body.reason.strip(), "told_at": told.isoformat(), "sessions_ended": ended, "stripe": stripe_note})
    forget(tid)
    return {"resiliated": True, "sessions_ended": ended, "stripe": stripe_note}


@router.post("/api/admin/commerces/{tid}/annuler-resiliation")
def annuler_resiliation(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "resiliated_at": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    _db.tenants.update_one({"id": tid}, {"$unset": {"resiliated_at": "", "resiliated_by": "", "resiliation_reason": "", "resiliation_told_at": ""}})
    core.log_audit("admin.commerce_resiliation_annulee", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid)
    forget(tid)
    return {"resiliated": False}


_suspended_cache: Dict[str, Any] = {}
_closed: Dict[str, Any] = {"at": None, "ids": set(), "slugs": set()}


def forget(tid: Optional[str] = None) -> None:
    """Drop what is cached about a business after it changed."""
    if tid:
        _suspended_cache.pop(tid, None)
    _closed["at"] = None


def is_suspended(tenant_id: Optional[str]):
    """Called by auth on every request of a business's team (cached 30 s):
    the reason the account is closed, or None."""
    if not tenant_id or _db is None:
        return None
    hit = _suspended_cache.get(tenant_id)
    if hit and hit[1] > _now():
        return hit[0]
    t = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "suspended_at": 1, "resiliated_at": 1}) or {}
    val = ("Ce compte a été résilié. Contactez FidClic." if t.get("resiliated_at")
           else "Ce compte est suspendu. Contactez FidClic." if t.get("suspended_at") else None)
    _suspended_cache[tenant_id] = (val, _now() + timedelta(seconds=30))
    return val


def closed_programs() -> Dict[str, Any]:
    """Résiliés businesses (ids and join slugs) — their customers' cards stop
    working. Re-read every 30 s; empty almost always, so it costs nothing."""
    if _db is None:
        return {"ids": set(), "slugs": set()}
    if not _closed["at"] or _closed["at"] < _now():
        rows = list(_db.tenants.find({"resiliated_at": {"$ne": None}}, {"_id": 0, "id": 1, "slug": 1}))
        _closed.update(at=_now() + timedelta(seconds=30), ids={r["id"] for r in rows}, slugs={r.get("slug") for r in rows if r.get("slug")})
    return _closed


@router.post("/api/admin/commerces/{tid}/view-as")
def view_as(tid: str, request: Request = None, token_data: TokenData = Depends(require_admin("commerces", write=False))):
    import server as core
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    owner = _db.users.find_one({"tenant_id": tid, "role": "business_owner"}, {"_id": 0, "email": 1})
    if not owner:
        raise HTTPException(status_code=409, detail="Ce commerce n'a pas de compte propriétaire.")
    # The Super Admin works in the account with full access (user,
    # 2026-10-05: « it should not be view only … 100% access »); every change
    # is audited (_log_act). A team member without « Modifier » only looks.
    full = _can_act(token_data)
    claims = {"sub": owner["email"], "role": "business_owner", "tenant_id": tid, "view_by": token_data.email}
    claims.update({"act_by": token_data.email} if full else {"view_only": True})
    token = create_access_token(claims, timedelta(minutes=VIEW_MINUTES))
    core.log_audit("admin.view_as", actor=token_data.email, actor_type="user", target=tid, tenant_id=tid, request=request,
                   meta={"as": owner["email"], "minutes": VIEW_MINUTES, "full_access": full})
    return {"token": token, "minutes": VIEW_MINUTES, "name": t.get("name"), "full_access": full}


# ---------------------------------------------------------------------------
# One business
# ---------------------------------------------------------------------------
def _tenant(tid: str) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    return t


def _series_counts(coll: str, match: Dict[str, Any], field: str, now: datetime, days: int = 30, n: int = 8):
    step = timedelta(days=days) / n
    start = now - timedelta(days=days)
    return [_db[coll].count_documents({**match, field: {"$gte": start + step * i, "$lt": start + step * (i + 1)}}) for i in range(n)]


def _owner(tid: str) -> Dict[str, Any]:
    return _db.users.find_one({"tenant_id": tid, "role": "business_owner"}, {"_id": 0, "hashed_password": 0, "totp_secret": 0,
                                                                              "backup_codes": 0}) or {}


@router.get("/api/admin/commerces/{tid}")
def get_commerce(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    import server as core
    from features import customer_status as CS
    t = _tenant(tid)
    now = _now()
    row = next((r for r in snapshot(now) if r["id"] == tid), None) or {}
    m30, m60 = now - timedelta(days=30), now - timedelta(days=60)
    cust = list(_db.customers.find({"tenant_id": tid, **LIVE}, {"_id": 0, "id": 1, "created_at": 1, "last_visit_date": 1,
                                                                 "visits": 1, "pass_issued": 1, "tier": 1}))
    cfg = CS._resolve_config(tid)
    total = len(cust)

    def last(c):
        return _aware(c.get("last_visit_date"))

    def active(c, at):
        lv = last(c)
        return bool(lv and (at - lv).days <= cfg.active_within_days and lv <= at)
    act_now = sum(1 for c in cust if active(c, now))
    act_prev = sum(1 for c in cust if active(c, m30) and (_aware(c.get("created_at")) or now) <= m30)
    total_prev = sum(1 for c in cust if (_aware(c.get("created_at")) or now) <= m30)
    visits30 = _db.visits.count_documents({"tenant_id": tid, "visit_time": {"$gte": m30}})
    visits60 = _db.visits.count_documents({"tenant_id": tid, "visit_time": {"$gte": m60, "$lt": m30}})
    pts = lambda a, b: sum(v.get("points_awarded") or 0 for v in _db.visits.find(          # noqa: E731
        {"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}}, {"points_awarded": 1}))
    rew = lambda a, b: _db.rewards_redeemed.count_documents({"tenant_id": tid, "redeemed_at": {"$gte": a, "$lt": b}})  # noqa: E731
    returning = sum(1 for c in cust if int(c.get("visits") or 0) >= 2)
    ret_prev = sum(1 for c in cust if int(c.get("visits") or 0) >= 2 and (_aware(c.get("created_at")) or now) <= m30)
    kpis = [
        {"key": "clients", "value": total, "delta": _delta(total, total_prev), "series": _series_counts("customers", {"tenant_id": tid, **LIVE}, "created_at", now)},
        {"key": "actifs", "value": act_now, "delta": _delta(act_now, act_prev)},
        {"key": "dormants", "value": total - act_now, "delta": _delta(total - act_now, total_prev - act_prev)},
        {"key": "visites", "value": visits30, "delta": _delta(visits30, visits60), "series": _series_counts("visits", {"tenant_id": tid}, "visit_time", now)},
        {"key": "points", "value": pts(m30, now), "delta": _delta(pts(m30, now), pts(m60, m30))},
        {"key": "recompenses", "value": rew(m30, now), "delta": _delta(rew(m30, now), rew(m60, m30))},
        {"key": "retour", "value": round(returning / total * 100) if total else 0,
         "delta": (round(returning / total * 100) - round(ret_prev / total_prev * 100)) if total and total_prev else None},
    ]
    # 6 months of new clients, clients who came, visits.
    months = []
    for a, b in month_windows(now):
        months.append({"month": a.strftime("%Y-%m"),
                       "nouveaux": _db.customers.count_documents({"tenant_id": tid, **LIVE, "created_at": {"$gte": a, "$lt": b}}),
                       "actifs": len(_db.visits.distinct("customer_id", {"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}})),
                       "visites": _db.visits.count_documents({"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}})})
    split = {"actifs": 0, "bientot_perdus": 0, "nouveaux": 0, "dormants": 0}
    for c in cust:
        created, lv = _aware(c.get("created_at")), last(c)
        if created and created >= m30:
            split["nouveaux"] += 1
        elif lv and (now - lv).days <= cfg.about_to_lose_days:
            split["actifs"] += 1
        elif lv and (now - lv).days <= cfg.active_within_days:
            split["bientot_perdus"] += 1
        else:
            split["dormants"] += 1
    labels = {"actifs": "Actifs", "dormants": "Dormants", "nouveaux": "Nouveaux (30 j)", "bientot_perdus": "Bientôt perdus"}
    repartition = [{"key": k, "label": labels[k], "count": v, "pct": round(v / total * 100) if total else 0} for k, v in split.items()]
    per = _visits_per_customer(tid, m30)
    share = lambda n: round(n / total * 100) if total else 0            # noqa: E731
    # Cartes actives: the card is on the phone. Fidèles: 5 visits or more.
    # Réguliers: 2 visits or more in the last 30 days. Attrition: no visit for 90 days.
    fid = {"cartes_actives": share(sum(1 for c in cust if c.get("pass_issued"))),
           "fideles": share(sum(1 for c in cust if int(c.get("visits") or 0) >= 5)),
           "reguliers": share(sum(1 for n in per.values() if n >= 2)),
           "attrition": share(sum(1 for c in cust if last(c) and (now - last(c)).days > 90))}
    camps = list(_db.campaigns.find({"tenant_id": tid, "sent_at": {"$ne": None}}, {"_id": 0}).sort("sent_at", -1).limit(50))
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month = [c for c in camps if _aware(c.get("sent_at")) and _aware(c["sent_at"]) >= month_start]
    delivered = sum(int(c.get("delivered_count") or c.get("targeted_count") or 0) for c in camps[:20])
    opens = sum(int(c.get("opens_unique") or 0) for c in camps[:20])
    clicks = sum(int(c.get("offer_clicks_unique") or 0) for c in camps[:20])
    f = core.features_for(t)
    usage = _usage(t, f)
    owner = _owner(tid)
    return {
        "id": tid, "name": t.get("name"), "logo": row.get("logo"), "sector": _sector(t.get("sector")), "city": t.get("city") or "",
        "postal_code": t.get("postal_code") or "", "address": t.get("address") or "", "phone": t.get("phone") or "",
        "website": t.get("website") or "", "status": row.get("status"), "status_label": row.get("status_label"),
        "cards_week": row.get("cards_week"), "scans_week": row.get("scans_week"), "standing": row.get("standing"),
        "standing_label": row.get("standing_label"), "resiliated": bool(t.get("resiliated_at")), "resiliated_at": _iso(t.get("resiliated_at")),
        "resiliation_reason": t.get("resiliation_reason"), "plan": row.get("plan"), "plan_key": core._canonical_plan(t.get("plan")),
        "created_at": _iso(t.get("created_at")), "renews_on": _iso(t.get("subscription_period_end") or t.get("trial_ends_at")),
        "subscription_status": t.get("subscription_status"), "suspended": bool(t.get("suspended_at")),
        "suspended_reason": t.get("suspended_reason"), "suspended_at": _iso(t.get("suspended_at")),
        "owner": {"email": owner.get("email"), "name": " ".join(x for x in (owner.get("first_name"), owner.get("last_name")) if x)},
        "crm_prospect_id": (_db.crm_prospects.find_one({"tenant_id": tid}, {"_id": 0, "id": 1}) or {}).get("id"),
        "kpis": kpis, "months": months, "repartition": repartition, "total_clients": total, "fidelite": fid,
        "campagnes": {"this_month": len(this_month), "open_rate": round(opens / delivered * 100) if delivered else 0,
                      "click_rate": round(clicks / delivered * 100) if delivered else 0,
                      "recent": [_camp(c) for c in camps[:5]]},
        "usage": usage, "plan_label": f.get("label"), "price": f.get("price") or None, "on_quote": bool(f.get("on_quote")),
        "franchise_terms": t.get("franchise_terms") or {},
        "payment_method": _pm(t), "stores": len([b for b in t.get("branches") or [] if b.get("status") != "closed"]) or 1,
    }


def month_windows(now: datetime, n: int = 6) -> List[tuple]:
    """The last n calendar months, oldest first, as (start, end) — exact
    month arithmetic, never « 31 days back » (which skips or repeats months)."""
    out = []
    y, m = now.year, now.month
    for _ in range(n):
        a = datetime(y, m, 1, tzinfo=timezone.utc)
        b = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
        out.append((a, b))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def _visits_per_customer(tid: str, since: datetime) -> Dict[str, int]:
    return {r["_id"]: r["n"] for r in _db.visits.aggregate([{"$match": {"tenant_id": tid, "visit_time": {"$gte": since}}},
                                                           {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}}])}


def _camp(c: Dict[str, Any]) -> Dict[str, Any]:
    d = int(c.get("delivered_count") or c.get("targeted_count") or 0)
    return {"id": c.get("id"), "name": c.get("name"), "type": {"push": "Push Wallet", "email": "Push", "other": "Push"}.get(c.get("source") or "", "Push"),
            "recipients": int(c.get("targeted_count") or d), "open_rate": round(int(c.get("opens_unique") or 0) / d * 100) if d else 0,
            "click_rate": round(int(c.get("offer_clicks_unique") or 0) / d * 100) if d else 0, "sent_at": _iso(c.get("sent_at")),
            "status": "Terminée" if c.get("sent_at") else (c.get("status") or "Brouillon")}


def _pm(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        from features import invoices as I
        return I._payment_method(t)
    except Exception:
        return None


def _usage(t: Dict[str, Any], f: Dict[str, Any]) -> List[Dict[str, Any]]:
    from features import plans_public as PP
    try:
        u = PP.owner_usage(token_data=TokenData(email="admin", role="business_owner", tenant_id=t["id"]))
    except Exception:
        u = {}
    month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ai_used = _db.ai_queries.count_documents({"tenant_id": t["id"], "created_at": {"$gte": month_start}})
    ai_limit = int(f.get("ai_queries_per_day") or 0) * 30
    out = []
    for key, label in (("customers", "Cartes"), ("push", "Notifications"), ("campaigns", "Campagnes")):
        b = u.get(key) or {}
        lim = b.get("limit")
        out.append({"key": key, "label": label, "used": b.get("used", 0), "limit": lim,
                    "pct": round(b.get("used", 0) / lim * 100) if lim else None})
    out.append({"key": "ai", "label": "IA (analyses)", "used": ai_used, "limit": ai_limit or None,
                "pct": round(ai_used / ai_limit * 100) if ai_limit else None})
    return out


@router.get("/api/admin/commerces/{tid}/clients")
def commerce_clients(tid: str, q: str = "", page: int = 1, per_page: int = 20, token_data: TokenData = Depends(require_admin("commerces"))):
    """No contact details here: the super admin sees how the programme works,
    not who the business's customers are."""
    _tenant(tid)
    page, per_page = max(1, int(page)), max(1, min(100, int(per_page)))
    f: Dict[str, Any] = {"tenant_id": tid, **LIVE}
    if q:
        f["name"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    total = _db.customers.count_documents(f)
    rows = list(_db.customers.find(f, {"_id": 0, "id": 1, "name": 1, "tier": 1, "visits": 1, "points": 1, "last_visit_date": 1,
                                       "created_at": 1, "acquisition_source": 1, "pass_issued": 1})
                .sort("created_at", -1).skip((page - 1) * per_page).limit(per_page))
    for r in rows:
        n = (r.get("name") or "").split()
        r["name"] = (n[0] + (f" {n[1][0]}." if len(n) > 1 and n[1] else "")) if n else "—"
        r["last_visit_date"], r["created_at"] = _iso(r.get("last_visit_date")), _iso(r.get("created_at"))
    return {"rows": rows, "total": total, "page": page, "pages": max(1, -(-total // per_page))}


@router.get("/api/admin/commerces/{tid}/details")
def commerce_details(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    """The other tabs: Fidélité, Campagnes, Notifications, Abonnement, Paramètres."""
    import server as core
    t = _tenant(tid)
    now = _now()
    tiers = {r["_id"] or "bronze": r["n"] for r in _db.customers.aggregate([{"$match": {"tenant_id": tid, **LIVE}},
                                                                             {"$group": {"_id": "$tier", "n": {"$sum": 1}}}])}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    rewards = []
    for a, b in month_windows(now):
        rewards.append({"month": a.strftime("%Y-%m"), "count": _db.rewards_redeemed.count_documents({"tenant_id": tid, "redeemed_at": {"$gte": a, "$lt": b}})})
    camps = [_camp(c) for c in _db.campaigns.find({"tenant_id": tid}, {"_id": 0}).sort("sent_at", -1).limit(100)]
    m30 = now - timedelta(days=30)
    kinds = {}
    # delivery_log: one row per message dispatched (server.dispatch_to_customer),
    # {kind, channel, result: {sent: <devices reached | bool>}, timestamp}.
    for d in _db.delivery_log.find({"tenant_id": tid, "timestamp": {"$gte": m30}}, {"_id": 0, "kind": 1, "result": 1}):
        k = d.get("kind") or "autre"
        e = kinds.setdefault(k, {"kind": k, "sent": 0, "failed": 0})
        e["sent" if (d.get("result") or {}).get("sent") else "failed"] += 1
    subs = len(_db.push_subscriptions.distinct("customer_id", {"tenant_id": tid}))
    total = _db.customers.count_documents({"tenant_id": tid, **LIVE})
    invoices = [{"number": i.get("number"), "paid_at": _iso(i.get("paid_at")), "amount": i.get("amount_paid") or i.get("total"),
                 "status": i.get("status")} for i in _db.fidclic_invoices.find({"tenant_id": tid}, {"_id": 0}).sort("paid_at", -1).limit(24)]
    team = [{"email": u["email"], "role": u.get("role"), "name": " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x),
             "active": u.get("active") is not False, "two_fa": bool(u.get("totp_enabled"))}
            for u in _db.users.find({"tenant_id": tid}, {"_id": 0, "email": 1, "role": 1, "first_name": 1, "last_name": 1, "active": 1,
                                                          "totp_enabled": 1})]
    f = core.features_for(t)
    return {
        "fidelite": {"tiers": [{"key": k, "label": k.capitalize(), "count": tiers.get(k, 0)} for k in ("bronze", "silver", "gold", "vip")],
                     "rewards": rewards, "points_mode": tpl.get("points_mode") or "per_visit",
                     "reward_threshold": tpl.get("reward_threshold_stamps") or tpl.get("reward_threshold"),
                     "reward_label": (tpl.get("brand_fields") or {}).get("reward_text") or tpl.get("reward_description")},
        "campagnes": camps,
        "notifications": {"subscribed": subs, "total": total, "pct": round(subs / total * 100) if total else 0,
                          "by_kind": sorted(kinds.values(), key=lambda x: -(x["sent"] + x["failed"]))},
        "abonnement": {"plan": f.get("label"), "plan_key": core._canonical_plan(t.get("plan")), "price": f.get("price") or None,
                       "on_quote": bool(f.get("on_quote")), "status": t.get("subscription_status"),
                       "trial_ends_at": _iso(t.get("trial_ends_at")), "renews_on": _iso(t.get("subscription_period_end")),
                       "since": _iso(t.get("created_at")), "payment_method": _pm(t), "invoices": invoices,
                       "franchise_terms": t.get("franchise_terms") or {}},
        "parametres": {"address": t.get("address"), "postal_code": t.get("postal_code"), "city": t.get("city"),
                       "phone": t.get("phone"), "website": t.get("website"), "legal_name": t.get("legal_name"), "siret": t.get("siret"),
                       "stores": [{"id": b.get("id"), "name": b.get("name") or ("Établissement principal" if b.get("is_main") or b.get("id") == "main" else b.get("id")),
                                   "city": b.get("city"), "status": b.get("status") or "open"} for b in t.get("branches") or []],
                       "geo_radius_meters": t.get("geo_radius_meters"), "sender_name": t.get("campaign_sender_name"), "team": team},
    }


@router.get("/api/admin/commerces/{tid}/zone")
def commerce_zone(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    from features import geolocation as G
    _tenant(tid)
    now = _now()
    d = G.compute(tid, now - timedelta(days=365), now, "car", "local")
    return {"shop": d.get("shop"), "bands": (d.get("isochrones") or {}).get("bands", []), "total": (d.get("isochrones") or {}).get("total", 0),
            "points": (d.get("points") or [])[:400]}
