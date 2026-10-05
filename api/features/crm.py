"""
CRM de prospection — FidClic's own sales machine (super admin + commercials).

Built to the approved mockups. Everything the pages show is counted from
these collections; nothing is invented, and an empty CRM shows zeros.

    crm_prospects   one business FidClic wants to sign (or has signed)
    crm_activities  its history: notes, calls, e-mails, stage changes, imports
    crm_tasks       what someone has to do next, and when
    crm_goals       the month's objective (clients signed)

WHO (decided with the user)
    super_admin   everything, and manages the sales team;
    commercial    a new role: sees the CRM only.

STAGES
    nouveau → a_contacter → contacte → rdv → proposition → essai → signe,
    and perdu (with its reason). « essai » was added to the mockup's six so a
    business on its free trial reads as what it is.

THE STATUS IS NEVER TYPED BY HAND FOR FIDCLIC'S OWN USERS (decided with the
user): every business that signed up on FidClic is linked to its prospect
and its stage follows its subscription — onboarding or trial → essai; active
(or an older account never billed) → signe; cancelled → perdu. The link is
made on import (SIRET, e-mail, phone, then name + postal code) and kept by
sync_tenants(), run when the CRM opens and every day.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from auth import require_role, TokenData, hash_password

router = APIRouter(tags=["crm"])
from features.platform_access import require_admin, require_super
_db = None

CRM = ["super_admin", "commercial"]
ADMIN = ["super_admin"]
STAGES = [
    ("nouveau", "Nouveau"), ("a_contacter", "À contacter"), ("contacte", "Contacté"), ("rdv", "Rendez-vous"),
    ("proposition", "Proposition"), ("essai", "En essai"), ("signe", "Signé"), ("perdu", "Perdu"),
]
STAGE_KEYS = [k for k, _ in STAGES]
FUNNEL = [k for k in STAGE_KEYS if k != "perdu"]
SOURCES = [("google", "Recherche Google"), ("import", "Fichiers / Import"), ("social", "Réseaux sociaux"),
           ("recommandation", "Recommandations"), ("evenement", "Événements"), ("inscription", "Inscription FidClic"),
           ("autre", "Autres")]
LOST_REASONS = ["Pas intéressé", "Trop cher", "Déjà une solution", "Pas de réponse", "Abonnement résilié", "Autre"]
TASK_TYPES = [("appel", "Appel"), ("email", "Email"), ("relance", "Relance"), ("rdv", "Rendez-vous"),
              ("proposition", "Proposition"), ("preparation", "Préparation"), ("suivi", "Suivi")]
CONFIRM = ("confirme", "a_confirmer", "annule")
TASK_PRESETS = [
    {"title": "Appeler le commerce", "type": "appel", "priority": "haute"},
    {"title": "Envoyer proposition", "type": "email", "priority": "moyenne"},
    {"title": "Relancer après devis", "type": "relance", "priority": "haute"},
    {"title": "Préparer RDV", "type": "preparation", "priority": "moyenne"},
    {"title": "Envoyer documentation", "type": "email", "priority": "basse"},
    {"title": "Confirmer rendez-vous", "type": "rdv", "priority": "basse"},
    {"title": "Suivi après salon", "type": "suivi", "priority": "moyenne"},
]
PRIORITIES = ("haute", "moyenne", "basse")
STAGE_WORDS = {
    "nouveau": ["nouveau", "new", "lead"], "a_contacter": ["a contacter", "to contact", "a appeler"],
    "contacte": ["contacte", "contacted", "en cours"], "rdv": ["rdv", "rendez-vous", "rendez vous", "meeting", "demo"],
    "proposition": ["proposition", "devis", "offre", "proposal"], "essai": ["essai", "trial", "test"],
    "signe": ["signe", "client", "signed", "won", "gagne", "actif", "abonne"], "perdu": ["perdu", "lost", "refus"],
}


def init(db):
    global _db
    _db = db
    try:
        db.crm_prospects.create_index("id", unique=True)
        db.crm_prospects.create_index("tenant_id")
        db.crm_prospects.create_index([("stage", 1), ("updated_at", -1)])
        db.crm_activities.create_index([("prospect_id", 1), ("at", -1)])
        db.crm_activities.create_index([("at", -1)])
        db.crm_tasks.create_index([("status", 1), ("due_at", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            p = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _iso(v: Any) -> Optional[str]:
    v = _aware(v)
    return v.isoformat() if v else None


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def _digits(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return ("0" + d[2:]) if d.startswith("33") and len(d) == 11 else d


def _log(pid: str, kind: str, text: str, by: Optional[str], **meta) -> None:
    _db.crm_activities.insert_one({"id": uuid.uuid4().hex, "prospect_id": pid, "type": kind, "text": text,
                                   "by": by, "at": meta.pop("at", None) or _now(), "meta": meta})
    _db.crm_prospects.update_one({"id": pid}, {"$set": {"last_activity_at": _now()}})


def _stage_from_word(word: str) -> Optional[str]:
    w = _fold(word)
    if not w:
        return None
    for key, words in STAGE_WORDS.items():
        if w in words or any(x in w for x in words if len(x) > 3):
            return key
    return None


# ---------------------------------------------------------------------------
# FidClic's own businesses → their stage
# ---------------------------------------------------------------------------
def stage_of_tenant(t: Dict[str, Any]) -> str:
    status = (t.get("subscription_status") or "").lower()
    if status in ("onboarding", "trialing"):
        return "essai"
    if status in ("canceled", "cancelled", "unpaid", "incomplete_expired"):
        return "perdu"
    return "signe"                     # active, past_due, or an older account never billed


SECTOR_LABELS = {"cafe": "Café / Salon de thé", "restaurant": "Restauration / Fast-food", "pizzeria": "Restauration / Fast-food",
                 "bakery": "Boulangerie", "boulangerie": "Boulangerie", "bar": "Bar", "spa": "Bien-être",
                 "salon": "Coiffure / Beauté", "gym": "Salle de sport", "retail": "Commerce de proximité", "other": "Autre",
                 "optician": "Opticien", "wine bar": "Bar à vin", "wine_bar": "Bar à vin", "chocolatier": "Chocolatier",
                 "book store": "Librairie", "bookstore": "Librairie", "creperie": "Crêperie", "crêperie": "Crêperie",
                 "hair salon": "Coiffure / Beauté", "hair_salon": "Coiffure / Beauté", "barber": "Barbier", "florist": "Fleuriste",
                 "butcher": "Boucherie", "cheese": "Fromagerie", "brasserie": "Brasserie", "fashion": "Mode", "clothing": "Mode",
                 "beauty": "Coiffure / Beauté", "pharmacy": "Pharmacie", "hotel": "Hôtel", "tea": "Café / Salon de thé"}


def _sector_label(key: str) -> str:
    k = (key or "").strip()
    return SECTOR_LABELS.get(k.lower(), k[:1].upper() + k[1:] if k else "")


def _tenant_fields(t: Dict[str, Any]) -> Dict[str, Any]:
    owner = _db.users.find_one({"tenant_id": t["id"], "role": "business_owner"}, {"_id": 0}) or {}
    street = t.get("street") or (t.get("address") or "").split(",")[0].strip()
    return {"name": t.get("name") or t.get("legal_name") or "Commerce", "city": t.get("city") or "",
            "postal_code": t.get("postal_code") or "", "address": street, "phone": t.get("phone") or "",
            "email": t.get("email") or owner.get("email") or "", "siret": t.get("siret") or "",
            "website": t.get("website") or "", "sector": _sector_label(t.get("sector") or ""),
            "contact_name": " ".join(x for x in (owner.get("first_name"), owner.get("last_name")) if x)}


def _link_tenant(pid: str, t: Dict[str, Any], by: Optional[str], at: Optional[datetime] = None) -> None:
    """`at`: when the stage was really reached — a business already on
    FidClic signed when it signed up, not when the CRM first saw it."""
    p = _db.crm_prospects.find_one({"id": pid}) or {}
    stage = stage_of_tenant(t)
    if at is None and not p.get("tenant_id"):
        # First time this business is tied to its account: it reached this
        # stage when it signed up (or started its trial), not today.
        at = _aware(t.get("trial_started_at")) or _aware(t.get("created_at"))
    sets: Dict[str, Any] = {"tenant_id": t["id"], "tenant_status": t.get("subscription_status"), "updated_at": _now()}
    for k, v in _tenant_fields(t).items():
        if v and not p.get(k):
            sets[k] = v
    if p.get("stage") != stage:
        sets["stage"] = stage
        if stage == "signe":
            sets["signed_at"] = at or _now()
        if stage == "perdu":
            sets["lost_reason"] = "Abonnement résilié"
    _db.crm_prospects.update_one({"id": pid}, {"$set": sets})
    if p.get("stage") != stage:
        _log(pid, "stage", f"Étape : {dict(STAGES)[stage]} (compte FidClic)", by or "FidClic",
             frm=p.get("stage"), to=stage, auto=True, at=at)


def sync_tenants() -> Dict[str, int]:
    """Every business on FidClic has its prospect, at the stage its account
    says. Idempotent."""
    out = {"created": 0, "updated": 0}
    linked = {p["tenant_id"]: p["id"] for p in _db.crm_prospects.find({"tenant_id": {"$ne": None}}, {"tenant_id": 1, "id": 1})}
    # A sign-up still in onboarding is a hidden draft, not a business yet.
    for t in _db.tenants.find({"onboarding_status": {"$nin": ["verify", "company", "plan"]}}, {"_id": 0}):
        if not t.get("id"):
            continue
        pid = linked.get(t["id"]) or (_match({**_tenant_fields(t)}) or {}).get("id")
        if pid:
            before = (_db.crm_prospects.find_one({"id": pid}, {"stage": 1}) or {}).get("stage")
            _link_tenant(pid, t, None)
            if before != stage_of_tenant(t):
                out["updated"] += 1
            continue
        pid = uuid.uuid4().hex
        created = _aware(t.get("created_at")) or _now()
        _db.crm_prospects.insert_one({"id": pid, **_tenant_fields(t), "source": "inscription", "stage": None,
                                      "created_at": created, "updated_at": _now(), "last_activity_at": created,
                                      "assigned_to": None, "tenant_id": None, "ref": _next_ref()})
        _link_tenant(pid, t, None, at=_aware(t.get("trial_started_at")) or created)
        out["created"] += 1
    return out


def _same_place(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Same name is the same business when it is in the same place — or when
    one of the two does not say where it is."""
    pa, pb = a.get("postal_code") or "", b.get("postal_code") or ""
    ca, cb = _fold(a.get("city") or ""), _fold(b.get("city") or "")
    if pa and pb:
        return pa == pb
    if ca and cb:
        return ca == cb
    return True


def _match(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An existing prospect this row is — never a second copy of a business."""
    tries = []
    if row.get("siret"):
        tries.append({"siret": re.sub(r"\D", "", row["siret"])})
    if row.get("email"):
        tries.append({"email": row["email"].lower()})
    for q in tries:
        p = _db.crm_prospects.find_one(q, {"_id": 0})
        if p:
            return p
    ph = _digits(row.get("phone") or "")
    name = _fold(row.get("name") or "")
    if ph or name:
        for p in _db.crm_prospects.find({}, {"_id": 0, "id": 1, "phone": 1, "name": 1, "postal_code": 1, "city": 1, "tenant_id": 1, "stage": 1}):
            if ph and len(ph) >= 9 and _digits(p.get("phone") or "") == ph:
                return p
            if name and _fold(p.get("name") or "") == name and _same_place(row, p):
                return p
    return None


def _match_tenant(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if row.get("siret"):
        t = _db.tenants.find_one({"siret": re.sub(r"\D", "", row["siret"])}, {"_id": 0})
        if t:
            return t
    if row.get("email"):
        e = row["email"].lower()
        t = _db.tenants.find_one({"email": e}, {"_id": 0})
        if t:
            return t
        u = _db.users.find_one({"email": e, "role": "business_owner"}, {"tenant_id": 1})
        if u and u.get("tenant_id"):
            return _db.tenants.find_one({"id": u["tenant_id"]}, {"_id": 0})
    ph, name = _digits(row.get("phone") or ""), _fold(row.get("name") or "")
    for t in _db.tenants.find({"onboarding_status": {"$nin": ["verify", "company", "plan"]}}, {"_id": 0}):
        if ph and len(ph) >= 9 and _digits(t.get("phone") or "") == ph:
            return t
        if name and _fold(t.get("name") or "") == name and _same_place(row, t):
            return t
    return None


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def _users() -> Dict[str, Dict[str, Any]]:
    return {u["email"]: u for u in _db.users.find({"role": {"$in": CRM + ["fidclic_team"]}}, {"_id": 0, "hashed_password": 0})}


def _name(u: Dict[str, Any]) -> str:
    n = " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x).strip()
    return n or (u.get("email") or "").split("@")[0]


def _next_task(pid: str) -> Optional[Dict[str, Any]]:
    t = _db.crm_tasks.find_one({"prospect_id": pid, "status": {"$ne": "terminee"}}, {"_id": 0}, sort=[("due_at", 1)])
    return {"label": t["title"], "due_at": _iso(t.get("due_at"))} if t else None


def _row(p: Dict[str, Any], users: Dict[str, Dict[str, Any]], last: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    u = users.get(p.get("assigned_to") or "")
    return {
        "id": p["id"], "ref": p.get("ref"), "name": p.get("name") or "", "sector": p.get("sector") or "",
        "city": p.get("city") or "", "postal_code": p.get("postal_code") or "", "address": p.get("address") or "",
        "contact_name": p.get("contact_name") or "", "contact_role": p.get("contact_role") or "",
        "phone": p.get("phone") or "", "email": p.get("email") or "", "website": p.get("website") or "",
        "instagram": p.get("instagram") or "", "facebook": p.get("facebook") or "", "siret": p.get("siret") or "",
        "size": p.get("size") or 1, "stage": p.get("stage") or "nouveau",
        "stage_label": dict(STAGES).get(p.get("stage") or "nouveau"), "lost_reason": p.get("lost_reason"),
        "source": p.get("source") or "autre", "source_label": dict(SOURCES).get(p.get("source") or "autre", "Autres"),
        "assigned_to": p.get("assigned_to"), "assigned_name": _name(u) if u else None,
        "tenant_id": p.get("tenant_id"), "on_fidclic": bool(p.get("tenant_id")),
        "next_action": _next_task(p["id"]),
        "last_action": ({"label": last.get("text"), "at": _iso(last.get("at"))} if last else None),
        "last_activity_at": _iso(p.get("last_activity_at")), "created_at": _iso(p.get("created_at")),
    }


def _filter(q: str = "", sector: str = "", city: str = "", stage: str = "", assigned: str = "",
            source: str = "") -> Dict[str, Any]:
    f: Dict[str, Any] = {}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        f["$or"] = [{"name": rx}, {"contact_name": rx}, {"city": rx}, {"email": rx}, {"phone": rx}, {"sector": rx}]
    if sector:
        f["sector"] = sector
    if city:
        f["city"] = city
    if stage:
        f["stage"] = stage
    if assigned:
        f["assigned_to"] = None if assigned == "none" else assigned
    if source:
        f["source"] = source
    return f


@router.get("/api/crm/prospects")
def list_prospects(q: str = "", sector: str = "", city: str = "", stage: str = "", assigned: str = "", source: str = "",
                   sort: str = "-last_activity_at", page: int = 1, per_page: int = 10,
                   token_data: TokenData = Depends(require_admin("crm"))):
    page, per_page = max(1, int(page)), max(1, min(200, int(per_page)))
    f = _filter(q, sector, city, stage, assigned, source)
    key, direction = (sort[1:], -1) if sort.startswith("-") else (sort, 1)
    if key not in ("name", "city", "sector", "stage", "last_activity_at", "created_at"):
        key = "last_activity_at"
    total = _db.crm_prospects.count_documents(f)
    rows = list(_db.crm_prospects.find(f, {"_id": 0}).sort([(key, direction), ("id", 1)])
                .skip((page - 1) * per_page).limit(per_page))
    users = _users()
    lasts = {}
    for a in _db.crm_activities.find({"prospect_id": {"$in": [r["id"] for r in rows]}}, {"_id": 0}).sort("at", -1):
        lasts.setdefault(a["prospect_id"], a)
    # The stage bar above the list: how many prospects each stage holds with
    # the other filters as they are, so one click moves from stage to stage.
    base = _filter(q, sector, city, "", assigned, source)
    stage_counts = {"all": _db.crm_prospects.count_documents(base),
                    **{k: _db.crm_prospects.count_documents({**base, "stage": k}) for k in STAGE_KEYS}}
    return {"rows": [_row(r, users, lasts.get(r["id"])) for r in rows], "total": total, "page": page,
            "pages": max(1, -(-total // per_page)), "per_page": per_page, "stage_counts": stage_counts}


@router.get("/api/crm/meta")
def meta(token_data: TokenData = Depends(require_admin("crm"))):
    users = _users()
    return {
        "stages": [{"key": k, "label": v} for k, v in STAGES],
        "sources": [{"key": k, "label": v} for k, v in SOURCES],
        "lost_reasons": LOST_REASONS,
        "task_types": [{"key": k, "label": v} for k, v in TASK_TYPES],
        "priorities": list(PRIORITIES),
        "sectors": sorted({s for s in _db.crm_prospects.distinct("sector") if s}),
        "cities": sorted({s for s in _db.crm_prospects.distinct("city") if s}),
        "users": [{"email": e, "name": _name(u), "role": u.get("role"), "active": u.get("active") is not False}
                  for e, u in users.items()],
        "me": {"email": token_data.email, "role": token_data.role},
    }


@router.get("/api/crm/prospects/{pid}")
def get_prospect(pid: str, token_data: TokenData = Depends(require_admin("crm"))):
    p = _db.crm_prospects.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    users = _users()
    acts = list(_db.crm_activities.find({"prospect_id": pid}, {"_id": 0}).sort("at", -1).limit(100))
    tasks = list(_db.crm_tasks.find({"prospect_id": pid}, {"_id": 0}).sort("due_at", 1))
    tenant = _db.tenants.find_one({"id": p.get("tenant_id")}, {"_id": 0, "subscription_status": 1, "plan": 1,
                                                              "trial_ends_at": 1, "created_at": 1}) if p.get("tenant_id") else None
    return {
        **_row(p, users, acts[0] if acts else None),
        "notes": [a for a in acts if a["type"] == "note"],
        "activities": [{**a, "at": _iso(a.get("at")), "by_name": _name(users[a["by"]]) if a.get("by") in users else a.get("by")}
                       for a in acts],
        "tasks": [_task_view(t, users) for t in tasks],
        "fidclic": ({"status": tenant.get("subscription_status"), "plan": tenant.get("plan"),
                     "trial_ends_at": _iso(tenant.get("trial_ends_at")), "since": _iso(tenant.get("created_at"))} if tenant else None),
    }


class ProspectIn(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    sector: Optional[str] = Field(None, max_length=80)
    city: Optional[str] = Field(None, max_length=80)
    postal_code: Optional[str] = Field(None, max_length=10)
    address: Optional[str] = Field(None, max_length=200)
    contact_name: Optional[str] = Field(None, max_length=120)
    contact_role: Optional[str] = Field(None, max_length=60)
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=160)
    website: Optional[str] = Field(None, max_length=200)
    instagram: Optional[str] = Field(None, max_length=200)
    facebook: Optional[str] = Field(None, max_length=200)
    siret: Optional[str] = Field(None, max_length=20)
    size: Optional[int] = Field(None, ge=1, le=10000)
    source: Optional[str] = None
    assigned_to: Optional[str] = None
    stage: Optional[str] = None
    lost_reason: Optional[str] = None


def _clean(body: ProspectIn) -> Dict[str, Any]:
    d = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if "email" in d:
        d["email"] = d["email"].lower()
        if d["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", d["email"]):
            raise HTTPException(status_code=400, detail="Adresse e-mail invalide.")
    if "siret" in d:
        d["siret"] = re.sub(r"\D", "", d["siret"])
    if "source" in d and d["source"] not in dict(SOURCES):
        raise HTTPException(status_code=400, detail="Source inconnue.")
    if "stage" in d and d["stage"] not in STAGE_KEYS:
        raise HTTPException(status_code=400, detail="Étape inconnue.")
    if d.get("assigned_to") and d["assigned_to"] not in _users():
        raise HTTPException(status_code=400, detail="Utilisateur inconnu.")
    return d


def _next_ref() -> str:
    from pymongo import ReturnDocument
    doc = _db.crm_counters.find_one_and_update({"key": "prospect"}, {"$inc": {"seq": 1}}, upsert=True,
                                               return_document=ReturnDocument.AFTER)
    return f"{int(doc['seq']):03d}"


def create(data: Dict[str, Any], by: Optional[str], source: str = "autre", note: Optional[str] = None) -> Dict[str, Any]:
    pid = uuid.uuid4().hex
    now = _now()
    doc = {"id": pid, "ref": _next_ref(), "stage": "nouveau", "source": source, "assigned_to": None, "tenant_id": None,
           "created_at": now, "updated_at": now, "last_activity_at": now, "size": 1, **data}
    _db.crm_prospects.insert_one(doc)
    _log(pid, "created", note or "Prospect ajouté", by)
    t = _match_tenant(doc)
    if t and not _db.crm_prospects.find_one({"tenant_id": t["id"], "id": {"$ne": pid}}):
        _link_tenant(pid, t, by)
    return _db.crm_prospects.find_one({"id": pid}, {"_id": 0})


@router.post("/api/crm/prospects")
def add_prospect(body: ProspectIn, token_data: TokenData = Depends(require_admin("crm"))):
    d = _clean(body)
    if not d.get("name"):
        raise HTTPException(status_code=400, detail="Le nom du commerce est obligatoire.")
    if _match(d):
        raise HTTPException(status_code=409, detail="Ce commerce est déjà dans vos prospects.")
    p = create({k: v for k, v in d.items() if k not in ("stage",)}, token_data.email, d.get("source") or "autre")
    if d.get("stage") and not p.get("tenant_id"):
        set_stage(p["id"], StageIn(stage=d["stage"], lost_reason=d.get("lost_reason")), token_data=token_data)
    return _row(_db.crm_prospects.find_one({"id": p["id"]}, {"_id": 0}), _users())


@router.put("/api/crm/prospects/{pid}")
def edit_prospect(pid: str, body: ProspectIn, token_data: TokenData = Depends(require_admin("crm"))):
    p = _db.crm_prospects.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    d = _clean(body)
    stage = d.pop("stage", None)
    lost = d.pop("lost_reason", None)
    if "assigned_to" in d and d["assigned_to"] != p.get("assigned_to"):
        who = _users().get(d["assigned_to"] or "")
        _log(pid, "assigned", f"Assigné à {_name(who)}" if who else "Plus assigné", token_data.email)
    if d:
        d["updated_at"] = _now()
        _db.crm_prospects.update_one({"id": pid}, {"$set": d})
    if stage:
        set_stage(pid, StageIn(stage=stage, lost_reason=lost), token_data=token_data)
    return get_prospect(pid, token_data=token_data)


class StageIn(BaseModel):
    stage: str
    lost_reason: Optional[str] = None


@router.post("/api/crm/prospects/{pid}/stage")
def set_stage(pid: str, body: StageIn, token_data: TokenData = Depends(require_admin("crm"))):
    p = _db.crm_prospects.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    if body.stage not in STAGE_KEYS:
        raise HTTPException(status_code=400, detail="Étape inconnue.")
    if p.get("tenant_id") and body.stage != p.get("stage"):     # the next sync would undo a hand move
        raise HTTPException(status_code=409, detail="Ce commerce est sur FidClic : son étape suit son abonnement.")
    if body.stage == "perdu" and not body.lost_reason:
        raise HTTPException(status_code=400, detail="Indiquez le motif de perte.")
    if p.get("stage") == body.stage:
        return {"stage": body.stage}
    sets: Dict[str, Any] = {"stage": body.stage, "updated_at": _now()}
    if body.stage == "perdu":
        sets["lost_reason"] = body.lost_reason
    if body.stage == "signe":
        sets["signed_at"] = _now()
    _db.crm_prospects.update_one({"id": pid}, {"$set": sets})
    label = dict(STAGES)[body.stage] + (f" — {body.lost_reason}" if body.stage == "perdu" else "")
    _log(pid, "stage", f"Étape : {label}", token_data.email, frm=p.get("stage"), to=body.stage)
    return {"stage": body.stage}


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/api/crm/prospects/{pid}/notes")
def add_note(pid: str, body: NoteIn, token_data: TokenData = Depends(require_admin("crm"))):
    if not _db.crm_prospects.find_one({"id": pid}):
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    _log(pid, "note", body.text.strip(), token_data.email)
    return {"ok": True}


@router.delete("/api/crm/prospects/{pid}")
def delete_prospect(pid: str, token_data: TokenData = Depends(require_super())):
    p = _db.crm_prospects.find_one({"id": pid})
    if not p:
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    if p.get("tenant_id"):
        raise HTTPException(status_code=409, detail="Un commerce inscrit sur FidClic ne se supprime pas du CRM.")
    _db.crm_prospects.delete_one({"id": pid})
    _db.crm_activities.delete_many({"prospect_id": pid})
    _db.crm_tasks.delete_many({"prospect_id": pid})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def _task_view(t: Dict[str, Any], users: Dict[str, Dict[str, Any]], names: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    due = _aware(t.get("due_at"))
    status = t.get("status") or "a_faire"
    if status != "terminee" and due and due < _now():
        status = "en_retard"
    u = users.get(t.get("assigned_to") or "")
    pr = (names or {}).get(t.get("prospect_id")) or {}
    dur = int(t.get("duration_min") or 30)
    return {"id": t["id"], "title": t.get("title"), "type": t.get("type") or "suivi",
            "type_label": dict(TASK_TYPES).get(t.get("type") or "suivi", "Suivi"), "priority": t.get("priority") or "moyenne",
            "status": status, "due_at": _iso(due), "end_at": _iso(due + timedelta(minutes=dur)) if due else None,
            "duration_min": dur, "confirm_status": t.get("confirm_status") or "a_confirmer",
            "description": t.get("description") or "",
            "prospect_id": t.get("prospect_id"), "prospect": pr.get("name"), "contact": pr.get("contact_name"),
            "contact_role": pr.get("contact_role"), "phone": pr.get("phone"), "email": pr.get("email"),
            "sector": pr.get("sector"), "city": pr.get("city"),
            "address": ", ".join(x for x in (pr.get("address"), " ".join(y for y in (pr.get("postal_code"), pr.get("city")) if y)) if x),
            "assigned_to": t.get("assigned_to"), "assigned_name": _name(u) if u else None, "done_at": _iso(t.get("done_at"))}


PROSPECT_CARD = {"_id": 0, "id": 1, "name": 1, "contact_name": 1, "contact_role": 1, "phone": 1, "email": 1, "sector": 1,
                 "city": 1, "address": 1, "postal_code": 1}


def _names(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {p["id"]: p for p in _db.crm_prospects.find({"id": {"$in": list({r.get("prospect_id") for r in rows if r.get("prospect_id")})}},
                                                       PROSPECT_CARD)}


class TaskIn(BaseModel):
    title: Optional[str] = Field(None, max_length=160)
    type: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[str] = None
    prospect_id: Optional[str] = None
    assigned_to: Optional[str] = None
    description: Optional[str] = Field(None, max_length=2000)
    status: Optional[str] = None
    duration_min: Optional[int] = Field(None, ge=5, le=600)
    confirm_status: Optional[str] = None


def _task_data(body: TaskIn) -> Dict[str, Any]:
    d = {k: v for k, v in body.model_dump().items() if v is not None}
    if "type" in d and d["type"] not in dict(TASK_TYPES):
        raise HTTPException(status_code=400, detail="Type de tâche inconnu.")
    if "priority" in d and d["priority"] not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Priorité inconnue.")
    if "status" in d and d["status"] not in ("a_faire", "en_cours", "terminee"):
        raise HTTPException(status_code=400, detail="Statut inconnu.")
    if "confirm_status" in d and d["confirm_status"] not in CONFIRM:
        raise HTTPException(status_code=400, detail="Statut de rendez-vous inconnu.")
    if d.get("assigned_to") and d["assigned_to"] not in _users():
        raise HTTPException(status_code=400, detail="Utilisateur inconnu.")
    if "due_at" in d:
        due = _aware(d["due_at"])
        if not due:
            raise HTTPException(status_code=400, detail="Date d'échéance invalide.")
        d["due_at"] = due
    if d.get("prospect_id") and not _db.crm_prospects.find_one({"id": d["prospect_id"]}):
        raise HTTPException(status_code=404, detail="Prospect introuvable")
    return d


def _task_query(q: str = "", assigned: str = "", priority: str = "", type: str = "", prospect_id: str = "",
                date_from: Optional[str] = None, date_to: Optional[str] = None, day: str = "") -> Dict[str, Any]:
    f: Dict[str, Any] = {}
    if prospect_id:
        f["prospect_id"] = prospect_id
    if assigned:
        f["assigned_to"] = assigned
    if priority:
        f["priority"] = priority
    if type:
        f["type"] = type
    if day == "today":
        start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        f["due_at"] = {"$gte": start, "$lt": start + timedelta(days=1)}
    elif date_from or date_to:
        f["due_at"] = {**({"$gte": _aware(date_from)} if _aware(date_from) else {}),
                       **({"$lt": _aware(date_to)} if _aware(date_to) else {})}
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        ids = [p["id"] for p in _db.crm_prospects.find({"$or": [{"name": rx}, {"contact_name": rx}]}, {"id": 1})]
        f["$or"] = [{"title": rx}, {"prospect_id": {"$in": ids}}]
    return f


@router.get("/api/crm/tasks")
def list_tasks(status: str = "", assigned: str = "", day: str = "", prospect_id: str = "", q: str = "",
               priority: str = "", type: str = "", date_from: Optional[str] = Query(None, alias="from"),
               date_to: Optional[str] = Query(None, alias="to"), page: int = 1, per_page: int = 50,
               token_data: TokenData = Depends(require_admin("crm"))):
    page, per_page = max(1, int(page)), max(1, min(500, int(per_page)))
    f = _task_query(q, assigned, priority, type, prospect_id,
                    date_from if isinstance(date_from, str) else None, date_to if isinstance(date_to, str) else None, day)
    rows = list(_db.crm_tasks.find(f, {"_id": 0}).sort("due_at", 1))
    users = _users()
    views = [_task_view(r, users, _names(rows)) for r in rows]
    counts = {s: sum(1 for v in views if v["status"] == s) for s in ("a_faire", "en_cours", "terminee", "en_retard")}
    counts["all"] = len(views)
    if status:
        views = [v for v in views if v["status"] == status]
    total = len(views)
    return {"rows": views[(page - 1) * per_page: page * per_page], "total": total, "counts": counts,
            "pages": max(1, -(-total // per_page))}


@router.get("/api/crm/tasks/summary")
def tasks_summary(token_data: TokenData = Depends(require_admin("crm"))):
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    users = _users()
    allv = [_task_view(t, users) for t in _db.crm_tasks.find({}, {"_id": 0})]

    def span_counts(a: datetime, b: datetime) -> Dict[str, int]:
        inside = [v for v in allv if v["due_at"] and a <= _aware(v["due_at"]) < b]
        return {"today": len(inside), "en_cours": sum(1 for v in inside if v["status"] == "en_cours"),
                "terminee": sum(1 for v in allv if v["done_at"] and a <= _aware(v["done_at"]) < b),
                "en_retard": sum(1 for v in inside if v["status"] == "en_retard")}

    week, prev = span_counts(today - timedelta(days=6), today + timedelta(days=1)), span_counts(today - timedelta(days=13), today - timedelta(days=6))
    series = {k: [span_counts(today - timedelta(days=d), today - timedelta(days=d - 1))[k] for d in range(6, -1, -1)]
              for k in ("today", "en_cours", "terminee", "en_retard")}
    value = {"today": sum(1 for v in allv if v["due_at"] and today <= _aware(v["due_at"]) < today + timedelta(days=1)),
             "en_cours": sum(1 for v in allv if v["status"] == "en_cours"),
             "terminee": sum(1 for v in allv if v["status"] == "terminee"),
             "en_retard": sum(1 for v in allv if v["status"] == "en_retard")}
    cards = [{"key": k, "value": value[k], "delta": _delta(week[k], prev[k]), "series": series[k]} for k in value]
    total = len(allv) or 1
    by_status = [{"key": k, "label": l, "count": sum(1 for v in allv if v["status"] == k),
                  "pct": round(sum(1 for v in allv if v["status"] == k) / total * 100)}
                 for k, l in (("a_faire", "À faire"), ("en_cours", "En cours"), ("terminee", "Terminées"), ("en_retard", "En retard"))]
    by_type = [{"key": k, "label": l, "count": sum(1 for v in allv if v["type"] == k),
                "pct": round(sum(1 for v in allv if v["type"] == k) / total * 100)} for k, l in TASK_TYPES]
    load = {}
    for v in allv:
        if v["status"] != "terminee" and v["assigned_name"]:
            load[v["assigned_name"]] = load.get(v["assigned_name"], 0) + 1
    workload = [{"label": k, "count": c, "pct": round(c / total * 100)} for k, c in sorted(load.items(), key=lambda x: -x[1])]
    return {"cards": cards, "by_status": by_status, "by_type": [t for t in by_type if t["count"]], "workload": workload,
            "presets": TASK_PRESETS + [{k: t.get(k) for k in ("id", "title", "type", "priority", "description")}
                                       for t in _db.crm_task_templates.find({}, {"_id": 0})]}


class TemplateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    type: str = "suivi"
    priority: str = "moyenne"
    description: str = Field("", max_length=2000)


@router.post("/api/crm/tasks/templates")
def add_template(body: TemplateIn, token_data: TokenData = Depends(require_admin("crm"))):
    if body.type not in dict(TASK_TYPES) or body.priority not in PRIORITIES:
        raise HTTPException(status_code=400, detail="Type ou priorité inconnu.")
    t = {"id": uuid.uuid4().hex, **body.model_dump(), "created_by": token_data.email, "created_at": _now()}
    _db.crm_task_templates.insert_one(t)
    t.pop("_id", None)
    return t


@router.delete("/api/crm/tasks/templates/{tid}")
def delete_template(tid: str, token_data: TokenData = Depends(require_admin("crm"))):
    if not _db.crm_task_templates.delete_one({"id": tid}).deleted_count:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return {"deleted": True}


@router.post("/api/crm/tasks")
def add_task(body: TaskIn, token_data: TokenData = Depends(require_admin("crm"))):
    d = _task_data(body)
    if not d.get("title") or not d.get("due_at"):
        raise HTTPException(status_code=400, detail="Titre et date d'échéance obligatoires.")
    t = {"id": uuid.uuid4().hex, "status": "a_faire", "type": "suivi", "priority": "moyenne",
         "assigned_to": token_data.email, "created_by": token_data.email, "created_at": _now(), **d}
    _db.crm_tasks.insert_one(t)
    if t.get("prospect_id"):
        _log(t["prospect_id"], "task", f"Tâche créée : {t['title']}", token_data.email)
    return _task_view(t, _users())


@router.put("/api/crm/tasks/{tid}")
def edit_task(tid: str, body: TaskIn, token_data: TokenData = Depends(require_admin("crm"))):
    t = _db.crm_tasks.find_one({"id": tid})
    if not t:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    d = _task_data(body)
    if d.get("status") == "terminee" and t.get("status") != "terminee":
        d["done_at"] = _now()
        if t.get("prospect_id"):
            _log(t["prospect_id"], "task_done", f"Tâche terminée : {t.get('title')}", token_data.email)
    _db.crm_tasks.update_one({"id": tid}, {"$set": d})
    return _task_view(_db.crm_tasks.find_one({"id": tid}, {"_id": 0}), _users())


@router.delete("/api/crm/tasks/{tid}")
def delete_task(tid: str, token_data: TokenData = Depends(require_admin("crm"))):
    if not _db.crm_tasks.delete_one({"id": tid}).deleted_count:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Import / export
# ---------------------------------------------------------------------------
MAX_FILE = 8 * 1024 * 1024


def _plan(row: Dict[str, Any]) -> Dict[str, Any]:
    """What importing this row will do — shown before anything is written."""
    existing = _match(row)
    tenant = _match_tenant(row)
    if tenant:
        stage, why = stage_of_tenant(tenant), "Compte FidClic trouvé"
    elif existing:
        stage, why = existing.get("stage") or "nouveau", "Déjà dans vos prospects"
    else:
        stage, why = _stage_from_word(row.get("status") or "") or "nouveau", "Nouveau prospect"
    return {"action": "update" if existing else "create", "stage": stage, "stage_label": dict(STAGES)[stage],
            "why": why, "existing_id": (existing or {}).get("id"), "tenant_id": (tenant or {}).get("id")}


@router.post("/api/crm/import/preview")
async def import_preview(file: UploadFile = File(...), token_data: TokenData = Depends(require_admin("crm"))):
    from features import crm_import
    data = await file.read()
    if len(data) > MAX_FILE:
        raise HTTPException(status_code=413, detail="Fichier trop lourd (8 Mo maximum).")
    name = (file.filename or "").lower()
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    try:
        rows, merged = crm_import.parse_with_stats(name, data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Fichier illisible ({str(exc)[:120]}).")
    if not rows:
        raise HTTPException(status_code=422, detail="Aucun commerce reconnu dans ce fichier. Il faut une colonne (ou une ligne) avec le nom du commerce, "
                                                    "et si possible adresse, téléphone ou e-mail.")
    # The city most rows give — offered as the default for the rows without one.
    cities: Dict[str, int] = {}
    for r in rows:
        if r.get("city"):
            cities[r["city"]] = cities.get(r["city"], 0) + 1
    return {"filename": file.filename, "rows": [{**r, **_plan(r)} for r in rows[:2000]], "total": len(rows),
            "duplicates_in_file": merged, "no_city": sum(1 for r in rows if not r.get("city")),
            "suggested_city": max(cities, key=cities.get) if cities else "", "formats": crm_import.ACCEPTED}


class ImportIn(BaseModel):
    rows: List[Dict[str, Any]]
    source: str = "import"
    assign_to: Optional[str] = None
    filename: Optional[str] = None
    default_city: Optional[str] = Field(None, max_length=80)


@router.post("/api/crm/import/commit")
def import_commit(body: ImportIn, token_data: TokenData = Depends(require_admin("crm"))):
    from features.crm_import import FIELDS
    if body.source not in dict(SOURCES):
        raise HTTPException(status_code=400, detail="Source inconnue.")
    if body.assign_to and body.assign_to not in _users():
        raise HTTPException(status_code=400, detail="Utilisateur inconnu.")
    out = {"created": 0, "updated": 0, "linked": 0, "skipped": 0}
    for raw in body.rows[:2000]:
        row = {k: str(raw.get(k) or "").strip() for k in FIELDS}
        if not row["city"] and (body.default_city or "").strip():
            row["city"] = body.default_city.strip()
        if not row["name"]:
            out["skipped"] += 1
            continue
        plan = _plan(row)
        data = {k: v for k, v in row.items() if v and k not in ("status", "source", "notes")}
        if plan["existing_id"]:
            p = _db.crm_prospects.find_one({"id": plan["existing_id"]}) or {}
            fill = {k: v for k, v in data.items() if not p.get(k)}
            if fill:
                _db.crm_prospects.update_one({"id": p["id"]}, {"$set": {**fill, "updated_at": _now()}})
            pid = p["id"]
            _log(pid, "import", f"Mis à jour par import ({body.filename or 'fichier'})", token_data.email)
            out["updated"] += 1
        else:
            if body.assign_to:
                data["assigned_to"] = body.assign_to
            pid = create(data, token_data.email, body.source, f"Importé ({body.filename or 'fichier'})")["id"]
            out["created"] += 1
        if row["notes"]:
            _log(pid, "note", row["notes"], token_data.email)
        p = _db.crm_prospects.find_one({"id": pid}) or {}
        if plan["tenant_id"]:
            if not p.get("tenant_id"):
                t = _db.tenants.find_one({"id": plan["tenant_id"]}, {"_id": 0})
                if t and not _db.crm_prospects.find_one({"tenant_id": t["id"], "id": {"$ne": pid}}):
                    _link_tenant(pid, t, token_data.email)
                    out["linked"] += 1
        elif plan["action"] == "create" and plan["stage"] not in ("nouveau", "essai", "signe"):
            set_stage(pid, StageIn(stage=plan["stage"], lost_reason="Autre" if plan["stage"] == "perdu" else None),
                      token_data=token_data)
    return out


@router.get("/api/crm/export")
def export(q: str = "", sector: str = "", city: str = "", stage: str = "", assigned: str = "", source: str = "",
           ids: str = "", token_data: TokenData = Depends(require_admin("crm"))):
    # « ids » = the rows ticked in a list: export just those (comma-separated).
    f = {"id": {"$in": [i for i in ids.split(",") if i]}} if ids.strip() else _filter(q, sector, city, stage, assigned, source)
    rows = list(_db.crm_prospects.find(f, {"_id": 0}).sort("name", 1))
    users = _users()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Réf", "Nom du commerce", "Secteur", "Ville", "Code postal", "Adresse", "Contact", "Téléphone", "Email",
                "Site web", "SIRET", "Statut", "Motif de perte", "Source", "Assigné à", "Sur FidClic", "Dernière activité"])
    for p in rows:
        r = _row(p, users)
        w.writerow([r["ref"] or "", r["name"], r["sector"], r["city"], r["postal_code"], r["address"], r["contact_name"],
                    r["phone"], r["email"], r["website"], r["siret"], r["stage_label"], r["lost_reason"] or "",
                    r["source_label"], r["assigned_name"] or "", "oui" if r["on_fidclic"] else "non",
                    (r["last_activity_at"] or "")[:10]])
    return Response(content=("﻿" + buf.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="prospects-{_now():%Y-%m-%d}.csv"'})


# ---------------------------------------------------------------------------
# Calendrier — the tasks, as events in time
# ---------------------------------------------------------------------------
@router.get("/api/crm/calendar")
def calendar(date_from: str = Query(..., alias="from"), date_to: str = Query(..., alias="to"), type: str = "",
             assigned: str = "", sector: str = "", status: str = "", q: str = "",
             token_data: TokenData = Depends(require_admin("crm"))):
    start, end = _aware(date_from), _aware(date_to)
    if not start or not end or end <= start or end - start > timedelta(days=62):
        raise HTTPException(status_code=400, detail="Période invalide.")
    f = _task_query(q, assigned, "", type, "", start.isoformat(), end.isoformat())
    if sector:
        f["prospect_id"] = {"$in": [p["id"] for p in _db.crm_prospects.find({"sector": sector}, {"id": 1})]}
    rows = list(_db.crm_tasks.find(f, {"_id": 0}).sort("due_at", 1))
    users = _users()
    events = [_task_view(r, users, _names(rows)) for r in rows]
    if status:
        events = [e for e in events if e["confirm_status"] == status or e["status"] == status]
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week0 = today - timedelta(days=today.weekday())
    allt = list(_db.crm_tasks.find({}, {"_id": 0, "due_at": 1, "type": 1, "status": 1, "done_at": 1, "created_at": 1}))

    def n(pred, a, b):
        return sum(1 for t in allt if pred(t) and _aware(t.get("due_at")) and a <= _aware(t["due_at"]) < b)

    def pair(pred, a, b, width):
        return {"value": n(pred, a, b), "delta": _delta(n(pred, a, b), n(pred, a - width, b - width)),
                "series": [n(pred, a - width + width * i / 7, a - width + width * (i + 1) / 7) for i in range(7)] + [n(pred, a, b)]}

    anyt = lambda t: True                                  # noqa: E731
    cards = {"today": pair(anyt, today, today + timedelta(days=1), timedelta(days=1)),
             "week": pair(anyt, week0, week0 + timedelta(days=7), timedelta(days=7)),
             "rdv": pair(lambda t: t.get("type") == "rdv", week0, week0 + timedelta(days=7), timedelta(days=7)),
             "relances": pair(lambda t: t.get("type") == "relance" and t.get("status") != "terminee", week0, week0 + timedelta(days=7), timedelta(days=7))}
    upcoming_rows = list(_db.crm_tasks.find({"type": "rdv", "due_at": {"$gte": now}, "status": {"$ne": "terminee"}}, {"_id": 0}).sort("due_at", 1).limit(6))
    days = [today - timedelta(days=d) for d in range(6, -1, -1)]
    kinds = [("appel", "Appels"), ("email", "Emails"), ("rdv", "Rendez-vous"), ("relance", "Relances"), ("proposition", "Propositions")]
    activity = [{"day": d.date().isoformat(), **{k: sum(1 for t in allt if t.get("type") == k and _aware(t.get("done_at"))
                                                         and d <= _aware(t["done_at"]) < d + timedelta(days=1)) for k, _ in kinds}} for d in days]
    return {"events": events, "cards": cards,
            "upcoming": [_task_view(r, users, _names(upcoming_rows)) for r in upcoming_rows],
            "today": list_tasks(day="today", per_page=6, token_data=token_data)["rows"],
            "activity": activity, "activity_kinds": [{"key": k, "label": l,
                                                      "total": sum(a[k] for a in activity)} for k, l in kinds]}


# ---------------------------------------------------------------------------
# Pipeline — the board
# ---------------------------------------------------------------------------
@router.get("/api/crm/pipeline")
def pipeline(q: str = "", sector: str = "", city: str = "", assigned: str = "", source: str = "",
             token_data: TokenData = Depends(require_admin("crm"))):
    users = _users()
    cols = []
    for key, label in STAGES:
        f = {**_filter(q, sector, city, key, assigned, source)}
        count = _db.crm_prospects.count_documents(f)
        rows = list(_db.crm_prospects.find(f, {"_id": 0}).sort("last_activity_at", -1).limit(60))
        cols.append({"key": key, "label": label, "count": count, "rows": [_row(r, users) for r in rows]})
    total = sum(c["count"] for c in cols)
    signed = next(c["count"] for c in cols if c["key"] == "signe")
    return {"columns": cols, "total": total, "conversion": round(signed / total * 100) if total else None}


# ---------------------------------------------------------------------------
# Vue d'ensemble
# ---------------------------------------------------------------------------
def _entered(stage: str, start: datetime, end: datetime) -> int:
    """Prospects that reached this stage (or beyond) inside the window."""
    later = set(FUNNEL[FUNNEL.index(stage):]) if stage in FUNNEL else {stage}
    return len(set(_db.crm_activities.distinct("prospect_id", {"type": "stage", "meta.to": {"$in": list(later)},
                                                               "at": {"$gte": start, "$lt": end}})))


def _series(fn, start: datetime, end: datetime, n: int = 8) -> List[int]:
    step = (end - start) / n
    return [fn(start + step * i, start + step * (i + 1)) for i in range(n)]


def _delta(now_v: int, prev_v: int) -> Optional[int]:
    return round((now_v - prev_v) / prev_v * 100) if prev_v else None


@router.get("/api/crm/overview")
def overview(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
             token_data: TokenData = Depends(require_admin("crm"))):
    try:
        sync_tenants()
    except Exception as exc:
        print(f"crm: tenant sync failed ({exc})")
    end = (_aware(date_to) or _now()) + timedelta(days=1 if date_to else 0)
    start = _aware(date_from) or (end - timedelta(days=30))
    span = end - start
    pstart, pend = start - span, start
    total = _db.crm_prospects.count_documents({})
    stage_count = {k: _db.crm_prospects.count_documents({"stage": k}) for k in STAGE_KEYS}

    def created(a, b):
        return _db.crm_prospects.count_documents({"created_at": {"$gte": a, "$lt": b}})

    cards = []
    for key, label, fn in (
        ("total", "Prospects total", created),
        ("contact", "En cours de contact", lambda a, b: _entered("contacte", a, b)),
        ("rdv", "Rendez-vous planifiés", lambda a, b: _entered("rdv", a, b)),
        ("proposition", "Propositions envoyées", lambda a, b: _entered("proposition", a, b)),
        ("signe", "Clients signés", lambda a, b: _entered("signe", a, b)),
    ):
        value = {"total": total, "contact": sum(stage_count[k] for k in ("contacte", "rdv", "proposition", "essai")),
                 "rdv": stage_count["rdv"], "proposition": stage_count["proposition"], "signe": stage_count["signe"]}[key]
        cards.append({"key": key, "label": label, "value": value,
                      "delta": _delta(fn(start, end), fn(pstart, pend)), "series": _series(fn, start, end)})

    def dist(field: str, labels: Optional[Dict[str, str]] = None, top: int = 7):
        counts: Dict[str, int] = {}
        for p in _db.crm_prospects.find({}, {field: 1}):
            k = p.get(field) or ("autre" if field == "source" else "")
            counts[k] = counts.get(k, 0) + 1
        items = sorted(((k, v) for k, v in counts.items() if k), key=lambda x: -x[1])
        head, tail = items[:top], items[top:]
        rows = [{"key": k, "label": (labels or {}).get(k, k), "count": v, "pct": round(v / total * 100) if total else 0} for k, v in head]
        if tail:
            n = sum(v for _, v in tail)
            rows.append({"key": "_autres", "label": f"Autres ({len(tail)})", "count": n, "pct": round(n / total * 100) if total else 0})
        return rows

    month = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    goal_doc = _db.crm_goals.find_one({"month": month.strftime("%Y-%m")}) or {}
    target = int(goal_doc.get("target") or 0)
    signed_month = _entered("signe", month, _now() + timedelta(seconds=1))
    # The first step counts every prospect (it opens the whole list): « Prospects », not « Nouveau ».
    funnel = [{"key": k, "label": v if k != "nouveau" else "Prospects", "count": stage_count[k] if k != "nouveau" else total,
               "pct": round((stage_count[k] if k != "nouveau" else total) / total * 100) if total else 0}
              for k, v in STAGES if k != "perdu"]
    users = _users()
    acts = list(_db.crm_activities.find({}, {"_id": 0}).sort("at", -1).limit(8))
    names = {p["id"]: p.get("name") for p in _db.crm_prospects.find({"id": {"$in": [a["prospect_id"] for a in acts]}}, {"id": 1, "name": 1})}
    return {
        "from": start.isoformat(), "to": (end - timedelta(seconds=1)).isoformat(),
        "cards": cards,
        "sources": dist("source", dict(SOURCES), 6),
        "sectors": dist("sector", None, 7),
        "cities": dist("city", None, 6),
        "goal": {"target": target, "signed": signed_month, "pct": round(signed_month / target * 100) if target else None,
                 "propositions": _entered("proposition", month, _now() + timedelta(seconds=1)),
                 "rdv": _entered("rdv", month, _now() + timedelta(seconds=1)), "month": month.strftime("%Y-%m")},
        "funnel": funnel,
        "lost": {"count": stage_count["perdu"], "reasons": [
            {"label": r, "count": _db.crm_prospects.count_documents({"stage": "perdu", "lost_reason": r})} for r in LOST_REASONS]},
        "today_tasks": list_tasks(day="today", per_page=6, token_data=token_data)["rows"],
        "activity": [{"text": a["text"], "prospect": names.get(a["prospect_id"]), "type": a["type"], "at": _iso(a["at"]),
                      "by": _name(users[a["by"]]) if a.get("by") in users else (a.get("by") or "FidClic")} for a in acts],
    }


class GoalIn(BaseModel):
    target: int = Field(..., ge=0, le=100000)


@router.put("/api/crm/goal")
def set_goal(body: GoalIn, token_data: TokenData = Depends(require_super())):
    month = _now().strftime("%Y-%m")
    _db.crm_goals.update_one({"month": month}, {"$set": {"month": month, "target": body.target}}, upsert=True)
    return {"month": month, "target": body.target}


# ---------------------------------------------------------------------------
# The sales team (super admin only)
# ---------------------------------------------------------------------------
class MemberIn(BaseModel):
    email: str = Field(..., max_length=160)
    first_name: str = Field("", max_length=60)
    last_name: str = Field("", max_length=60)


@router.get("/api/crm/team")
def team(token_data: TokenData = Depends(require_super())):
    counts = {}
    for p in _db.crm_prospects.find({"assigned_to": {"$ne": None}}, {"assigned_to": 1}):
        counts[p["assigned_to"]] = counts.get(p["assigned_to"], 0) + 1
    return {"members": [{"email": e, "name": _name(u), "role": u.get("role"), "active": u.get("active") is not False,
                         "prospects": counts.get(e, 0)} for e, u in _users().items()]}


@router.post("/api/crm/team")
def add_member(body: MemberIn, token_data: TokenData = Depends(require_super())):
    email = body.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Adresse e-mail invalide.")
    if _db.users.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Un compte existe déjà avec cet e-mail.")
    from services import password_policy
    password = password_policy.generate()
    _db.users.insert_one({"id": uuid.uuid4().hex, "email": email, "role": "commercial", "tenant_id": None,
                          "first_name": body.first_name.strip(), "last_name": body.last_name.strip(),
                          "hashed_password": hash_password(password), "auth_provider": "password",
                          "active": True, "created_at": _now(), "created_by": token_data.email})
    return {"credentials": {"email": email, "password": password}}


class ActiveIn(BaseModel):
    active: bool


@router.post("/api/crm/team/{email}/status")
def member_status(email: str, body: ActiveIn, token_data: TokenData = Depends(require_super())):
    u = _db.users.find_one({"email": email.lower(), "role": "commercial"})
    if not u:
        raise HTTPException(status_code=404, detail="Commercial introuvable")
    _db.users.update_one({"email": u["email"]}, {"$set": {"active": body.active}})
    if not body.active:
        try:
            from features.security_page import revoke
            revoke({"email": u["email"]})
        except Exception:
            pass
    return {"active": body.active}
