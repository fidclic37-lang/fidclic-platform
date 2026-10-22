"""
Paramètres › Établissement — who the shop is, where it is, when it is open.

Built to the approved mockup (8 blocks), plus what the user asked to add
because it lived nowhere else: the GPS pin the owner can place, the proximity
radius, the opening hours (features/business_hours.py, same data), and the
legal information taken at onboarding and never editable since.

Mounts at:
    GET  /api/owner/etablissement                   → everything the page shows
    PUT  /api/owner/etablissement                   → save (fields by role, below)
    POST /api/owner/etablissement/geocode           → an address → a pin (BAN)
    POST /api/owner/etablissement/stores            → add a point de vente
    PUT  /api/owner/etablissement/stores/{id}       → edit / close one

WHO CHANGES WHAT
    Propriétaire    everything.
    Administrateur  the legal information, and the points de vente it covers
                    (address, phone, pin) — decided with the user.
    Manager         reads.

ONE RADIUS
    The proximity reminder has one radius, set here (tenant.geo_radius_meters):
    the web card's "vous passez devant" and the Apple Wallet pass both use it.

THE MAIN ESTABLISHMENT
    A shop without branches is one virtual establishment, "main". Adding its
    first point de vente turns the shop itself into a real branch with the id
    "main" — so its past visits (no branch tag) stay its own, see
    store_scope._branch_values.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["etablissement"])
_db = None

READERS = ["business_owner", "administrateur", "manager"]
EDITORS = ["business_owner", "administrateur"]
MAIN = "main"
DEFAULT_RADIUS = 200
SECTORS = [
    ("cafe", "Café / Salon de thé"), ("restaurant", "Restaurant"), ("pizzeria", "Pizzeria"),
    ("bakery", "Boulangerie / Pâtisserie"), ("bar", "Bar"), ("spa", "Spa / Bien-être"),
    ("salon", "Coiffure / Beauté"), ("gym", "Salle de sport"), ("retail", "Commerce de détail"),
    ("other", "Autre"),
]
BAN_URL = "https://api-adresse.data.gouv.fr/search/"


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tenant(tid: str) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    return t


def _street(t: Dict[str, Any]) -> str:
    """Onboarding stored "rue, CP ville" in `address`; the page edits the street."""
    if t.get("street"):
        return t["street"]
    addr = (t.get("address") or "").strip()
    return addr.split(",")[0].strip() if "," in addr else addr


def _pos(d: Dict[str, Any]):
    lat = d.get("lat", d.get("latitude"))
    lng = d.get("lng", d.get("longitude"))
    return (float(lat), float(lng)) if lat is not None and lng is not None else (None, None)


def _selected(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Several establishments: the one chosen in the menu, whose name, address
    and phone this page shows and edits (user, 2026-10-12: renaming PALISSY
    leaves the other stores as they are). None: a one-shop account — the
    account's own fields, as before."""
    from features import store_cards as SC
    open_ = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    if len(open_) < 2:
        return None
    sid = SC.store_for(t.get("id"))
    return next((b for b in open_ if b["id"] == sid), None)


def _me(token: TokenData) -> Dict[str, Any]:
    return _db.users.find_one({"email": getattr(token, "email", None)}, {"_id": 0}) or {}


def _owner(tid: str, token: TokenData) -> Dict[str, Any]:
    """The shop's owner account: the signed-in one when it is the owner (also
    when the super admin views the shop as it), else the first owner."""
    me = _me(token)
    if me.get("role") == "business_owner" and me.get("tenant_id") == tid:
        return me
    rows = list(_db.users.find({"tenant_id": tid, "role": "business_owner"}, {"_id": 0}).sort("created_at", 1).limit(1))
    return rows[0] if rows else {}


NAME_MAX = 60
# letters (any alphabet, accents), spaces, hyphens, apostrophes, dots — « Jean-Luc », « D'Arcy », « Mª »
NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '’.\-][^\W\d_]*)*$")


def _clean_name(raw: Optional[str], label: str) -> str:
    v = re.sub(r"\s+", " ", (raw or "").strip())
    if not v:
        raise HTTPException(status_code=400, detail=f"Le {label} du propriétaire est obligatoire.")
    if len(v) > NAME_MAX:
        raise HTTPException(status_code=400, detail=f"Le {label} du propriétaire dépasse {NAME_MAX} caractères.")
    if not NAME_RE.match(v):
        raise HTTPException(status_code=400, detail=f"Le {label} du propriétaire ne peut contenir que des lettres, espaces, tirets et apostrophes.")
    return v


def _covers(token: TokenData, tid: str) -> List[str]:
    from features import team_access as T
    all_ids = [s["id"] for s in T.stores(tid)]
    if getattr(token, "role", None) == "business_owner":
        return all_ids
    me = _me(token)
    return T._covered(me, all_ids) if me else []


def _store_view(t: Dict[str, Any], b: Dict[str, Any], editable: bool) -> Dict[str, Any]:
    lat, lng = _pos(b)
    return {"id": b.get("id"), "name": b.get("name") or t.get("name") or "Établissement",
            "is_main": b.get("id") == MAIN or bool(b.get("is_main")),
            "street": b.get("street") or (b.get("address") or "").split(",")[0].strip(),
            "postal_code": b.get("postal_code") or "", "city": b.get("city") or "",
            "phone": b.get("phone") or "", "lat": lat, "lng": lng,
            "status": b.get("status") or "open", "editable": editable}


def _full(token: TokenData) -> bool:
    """« Paramètres » with « Modifier » (Équipe & accès): the whole page, like
    the owner (user, 2026-10-22: « saari permissions di hai toh sab
    accessible hona chahiye »). The owner's own name stays his."""
    from features import role_perms as RP
    return RP.may(token, "settings", "edit")


def _view(tid: str, token: TokenData) -> Dict[str, Any]:
    t = _tenant(tid)
    role = getattr(token, "role", None)
    owner = _full(token)
    mine = set(_covers(token, tid))
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1}) or {}
    lat, lng = _pos(t)
    branches = [b for b in t.get("branches") or [] if b.get("id")]
    if branches:
        stores = [_store_view(t, b, (role in EDITORS or owner) and b["id"] in mine) for b in branches]
        stores.sort(key=lambda s: (not s["is_main"], s["status"] == "closed", s["name"].lower()))
    else:
        stores = [_store_view(t, {"id": MAIN, "name": t.get("name"), "street": _street(t),
                                  "postal_code": t.get("postal_code"), "city": t.get("city"),
                                  "phone": t.get("phone"), "lat": lat, "lng": lng}, owner)]
    try:
        from server import features_for
        multi = bool(features_for(t).get("multi_branch"))
    except Exception:
        multi = False
    o = _owner(tid, token)
    sel = _selected(t)
    if sel:
        slat, slng = _pos(sel)
        addr = {"street": _street(sel), "postal_code": sel.get("postal_code") or "", "city": sel.get("city") or "",
                "country": t.get("country") or "FR", "lat": slat, "lng": slng,
                "pin": sel.get("pin_source") or ("adresse" if slat is not None else None)}
    else:
        addr = {"street": _street(t), "postal_code": t.get("postal_code") or "", "city": t.get("city") or "",
                "country": t.get("country") or "FR", "lat": lat, "lng": lng,
                "pin": t.get("pin_source") or ("adresse" if lat is not None else None)}
    return {
        # the owner's own name (« Bonjour … » on the dashboard), changed by the owner only
        "owner": {"first_name": o.get("first_name") or "", "last_name": o.get("last_name") or "",
                  "email": o.get("email") or ""},
        "can": {"brand": owner, "owner_name": role == "business_owner", "legal": role in EDITORS or owner,
                "geo": owner, "hours": owner,
                "add_store": owner and multi, "plan_allows_stores": multi},
        "business": {"name": (sel or {}).get("name") or t.get("name") or "", "logo_url": tpl.get("logo_url") or "",
                     "phone": (sel.get("phone") if sel else None) or t.get("phone") or "",
                     "email": t.get("email") or t.get("contact_email") or "",
                     "sector": t.get("sector") or "", "activity": t.get("activity") or "",
                     "description": t.get("description") or "", "website": t.get("website") or ""},
        # several establishments: the page is the chosen one's (its name, address, phone)
        "store": {"id": sel["id"], "name": sel.get("name") or "", "account_name": t.get("name") or ""} if sel else None,
        "address": addr,
        "legal": {"legal_name": t.get("legal_name") or "", "siret": t.get("siret") or "",
                  "vat_number": t.get("vat_number") or ""},
        "geo": {"enabled": bool(t.get("geo_enabled")), "radius_m": int(t.get("geo_radius_meters") or DEFAULT_RADIUS),
                "cooldown_days": int(t.get("geo_cooldown_days") or 1), "vip_only": bool(t.get("vip_geo_only"))},
        "stores": stores,
        "sectors": [{"value": k, "label": v} for k, v in SECTORS],
    }


@router.get("/api/owner/etablissement")
def get_etablissement(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _view(token_data.tenant_id, token_data)


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------
class BusinessIn(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    logo_url: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=30)
    email: Optional[str] = Field(None, max_length=120)
    sector: Optional[str] = None
    description: Optional[str] = Field(None, max_length=500)


class AddressIn(BaseModel):
    street: Optional[str] = Field(None, max_length=160)
    postal_code: Optional[str] = Field(None, max_length=10)
    city: Optional[str] = Field(None, max_length=80)
    lat: Optional[float] = None
    lng: Optional[float] = None
    pin: Optional[str] = None               # "adresse" | "manuel"


class LegalIn(BaseModel):
    legal_name: Optional[str] = Field(None, max_length=160)
    siret: Optional[str] = None
    vat_number: Optional[str] = Field(None, max_length=20)


class GeoIn(BaseModel):
    enabled: Optional[bool] = None
    radius_m: Optional[int] = None
    cooldown_days: Optional[int] = None


class OwnerIn(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class EtablissementIn(BaseModel):
    owner: Optional[OwnerIn] = None
    business: Optional[BusinessIn] = None
    address: Optional[AddressIn] = None
    legal: Optional[LegalIn] = None
    geo: Optional[GeoIn] = None


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LOGO = 2_800_000       # a 2 Mo image, as a data URI


def _check_pin(lat: Optional[float], lng: Optional[float]) -> None:
    if (lat is None) != (lng is None):
        raise HTTPException(status_code=400, detail="Le point GPS est incomplet.")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="Point GPS invalide.")


def _clean_siret(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits and len(digits) != 14:
        raise HTTPException(status_code=400, detail="Le SIRET compte 14 chiffres.")
    return digits


@router.put("/api/owner/etablissement")
@SV.records("etablissement")
def put_etablissement(body: EtablissementIn,
                      token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    t = _tenant(tid)
    owner = _full(token_data)
    if getattr(token_data, "role", None) not in EDITORS and not owner:
        raise HTTPException(status_code=403, detail="Accès non autorisé : vous ne pouvez pas modifier « Paramètres ».")
    if body.owner and getattr(token_data, "role", None) != "business_owner":
        raise HTTPException(status_code=403, detail="Seul le propriétaire modifie son propre nom.")
    if not owner and (body.business or body.address or body.geo):
        raise HTTPException(status_code=403, detail="Accès non autorisé : vous ne pouvez pas modifier « Paramètres ».")
    sets: Dict[str, Any] = {}
    owner_names: Dict[str, str] = {}
    sel = _selected(t)
    store_sets: Dict[str, Any] = {}          # the chosen establishment's own fields
    if body.owner:
        # checked before anything is written: a refused name saves nothing
        owner_names = {"first_name": _clean_name(body.owner.first_name, "prénom"),
                       "last_name": _clean_name(body.owner.last_name, "nom")}

    if body.business:
        b = body.business
        if b.name is not None:
            if not b.name.strip():
                raise HTTPException(status_code=400, detail="Le nom du commerce est obligatoire.")
            (store_sets if sel else sets)["name"] = b.name.strip()
        if b.phone is not None:
            (store_sets if sel else sets)["phone"] = b.phone.strip()
        if b.email is not None:
            if b.email.strip() and not EMAIL_RE.match(b.email.strip()):
                raise HTTPException(status_code=400, detail="Adresse e-mail invalide.")
            sets["email"] = b.email.strip()
        if b.sector:                            # left unchosen: nothing to save
            if b.sector not in dict(SECTORS):
                raise HTTPException(status_code=400, detail="Secteur inconnu.")
            sets["sector"] = b.sector
        if b.description is not None:
            sets["description"] = b.description.strip()
        if b.logo_url is not None:
            from services import media as _M
            if b.logo_url and not _M.is_image_value(b.logo_url):
                raise HTTPException(status_code=400, detail="Logo invalide.")
            if len(b.logo_url) > MAX_LOGO:
                raise HTTPException(status_code=400, detail="Le logo dépasse 2 Mo.")
            # The same logo as the card's — one logo for the shop.
            _db.card_templates.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, "logo_url": b.logo_url,
                                                                         "updated_at": _now()}}, upsert=True)

    if body.address:
        a = body.address
        _check_pin(a.lat, a.lng)
        src = sel or t
        street = (a.street if a.street is not None else _street(src)).strip()
        postal = (a.postal_code if a.postal_code is not None else src.get("postal_code") or "").strip()
        city = (a.city if a.city is not None else src.get("city") or "").strip()
        if postal and not re.fullmatch(r"\d{4,5}", postal):
            raise HTTPException(status_code=400, detail="Code postal invalide.")
    if body.address and sel:
        # the chosen establishment's address; the account's follows its main one
        store_sets.update({"street": street, "postal_code": postal, "city": city,
                           "address": f"{street}, {postal} {city}".strip(", "),
                           **({"latitude": a.lat, "longitude": a.lng,
                               "pin_source": "manuel" if a.pin == "manuel" else "adresse"} if a.lat is not None else {})})
        if sel.get("id") == MAIN or sel.get("is_main"):
            sets.update({"street": street, "postal_code": postal, "city": city, "address": store_sets["address"],
                         **({"lat": a.lat, "lng": a.lng, "pin_source": store_sets["pin_source"]}
                            if a.lat is not None else {})})
    elif body.address:
        sets.update({"street": street, "postal_code": postal, "city": city,
                     "address": f"{street}, {postal} {city}".strip(", ")})
        if a.lat is not None:
            sets.update({"lat": a.lat, "lng": a.lng, "pin_source": "manuel" if a.pin == "manuel" else "adresse"})
        # A shop whose main establishment is a real branch keeps both in step.
        branches = t.get("branches") or []
        idx = next((i for i, br in enumerate(branches) if br.get("id") == MAIN), None)
        if idx is None:
            idx = next((i for i, br in enumerate(branches) if br.get("is_main")), None)
        if idx is not None:
            branches[idx] = {**branches[idx], "street": street, "postal_code": postal, "city": city,
                             "address": sets["address"],
                             **({"latitude": a.lat, "longitude": a.lng} if a.lat is not None else {})}
            sets["branches"] = branches

    if body.legal:
        lg = body.legal
        if lg.legal_name is not None:
            sets["legal_name"] = lg.legal_name.strip()
        if lg.siret is not None:
            siret = _clean_siret(lg.siret)
            sets["siret"] = siret
            sets["siren"] = siret[:9] if siret else ""
        if lg.vat_number is not None:
            sets["vat_number"] = lg.vat_number.strip().upper()

    if body.geo:
        g = body.geo
        if g.enabled is not None:
            sets["geo_enabled"] = bool(g.enabled)
        if g.radius_m is not None:
            sets["geo_radius_meters"] = max(50, min(2000, int(g.radius_m)))
        if g.cooldown_days is not None:
            sets["geo_cooldown_days"] = max(1, min(30, int(g.cooldown_days)))

    if owner_names:
        me = _owner(tid, token_data)
        if not me.get("email"):
            raise HTTPException(status_code=404, detail="Compte du propriétaire introuvable.")
        if any((me.get(k) or "") != v for k, v in owner_names.items()):
            # one place: every page reads the name from the account (team, admin, e-mails, « Bonjour »)
            _db.users.update_one({"email": me["email"]}, {"$set": {**owner_names, "updated_at": _now()}})
            try:
                from server import log_audit
                log_audit("owner.renamed", actor=getattr(token_data, "email", None), actor_type="user",
                          tenant_id=tid, target=me["email"], meta={"by": getattr(token_data, "view_by", None)})
            except Exception:
                pass

    if store_sets:
        _db.tenants.update_one({"id": tid, "branches.id": sel["id"]},
                               {"$set": {f"branches.$.{k}": v for k, v in store_sets.items()}})
        try:
            from server import log_audit
            log_audit("etablissement.store_updated", actor=getattr(token_data, "email", None), actor_type="user",
                      tenant_id=tid, target=sel["id"], meta={"fields": sorted(store_sets)})
        except Exception:
            pass
        if any(k in store_sets and store_sets[k] != sel.get(k) for k in ("name", "street", "postal_code", "city", "phone")):
            try:                       # its members' cards carry its name, address and phone (QA R7 F40)
                from features import store_cards as SC
                from features.wallet_passes import notify_tenant
                with SC.store(tid, sel["id"]):
                    notify_tenant(tid)
            except Exception:
                pass

    if sets:
        sets["updated_at"] = _now()
        _db.tenants.update_one({"id": tid}, {"$set": sets})
        if "sector" in sets:
            # A card whose reward was never chosen follows the new sector.
            try:
                from services import sector_rewards
                if sector_rewards.apply(_db, tid, sets["sector"]):
                    from features.wallet_passes import notify_tenant
                    notify_tenant(tid)
            except Exception:
                pass
        try:
            from server import log_audit
            log_audit("etablissement.updated", actor=getattr(token_data, "email", None), actor_type="user",
                      tenant_id=tid, target=tid, meta={"fields": sorted(k for k in sets if k != "updated_at")})
        except Exception:
            pass
    return _view(tid, token_data)


# ---------------------------------------------------------------------------
# an address → a pin
# ---------------------------------------------------------------------------
class GeocodeIn(BaseModel):
    street: str = ""
    postal_code: str = ""
    city: str = ""


@router.post("/api/owner/etablissement/geocode")
def geocode(body: GeocodeIn, token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    """The Base Adresse Nationale's answer for an address; the postal code's
    centre if it has none. The owner then moves the pin if needed."""
    q = " ".join(x for x in (body.street, body.postal_code, body.city) if x).strip()
    if not q:
        raise HTTPException(status_code=400, detail="Saisissez une adresse.")
    try:
        import httpx
        params = {"q": q, "limit": 1}
        if re.fullmatch(r"\d{5}", body.postal_code or ""):
            params["postcode"] = body.postal_code
        r = httpx.get(BAN_URL, params=params, timeout=4.0)
        feats = (r.json() or {}).get("features") or [] if r.status_code == 200 else []
        if feats:
            lng, lat = feats[0]["geometry"]["coordinates"]
            props = feats[0].get("properties") or {}
            return {"lat": float(lat), "lng": float(lng), "label": props.get("label") or q,
                    "precise": props.get("type") in ("housenumber", "street"), "source": "ban"}
    except Exception as exc:
        print(f"etablissement: geocode failed ({exc})")
    if body.postal_code:
        try:
            from server import get_postal_coords
            lat, lng = get_postal_coords(body.postal_code)
            return {"lat": lat, "lng": lng, "label": body.postal_code, "precise": False, "source": "postal"}
        except Exception:
            pass
    raise HTTPException(status_code=404, detail="Adresse introuvable — placez le point sur la carte.")


# ---------------------------------------------------------------------------
# points de vente
# ---------------------------------------------------------------------------
class StoreIn(BaseModel):
    name: Optional[str] = Field(None, max_length=80)
    street: Optional[str] = Field(None, max_length=160)
    postal_code: Optional[str] = Field(None, max_length=10)
    city: Optional[str] = Field(None, max_length=80)
    phone: Optional[str] = Field(None, max_length=30)
    lat: Optional[float] = None
    lng: Optional[float] = None
    status: Optional[str] = None            # "open" | "closed" (owner) — never deleted


def _branch_doc(body: StoreIn, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    d = dict(base or {})
    for k in ("name", "street", "postal_code", "city", "phone"):
        v = getattr(body, k)
        if v is not None:
            d[k] = v.strip()
    if d.get("postal_code") and not re.fullmatch(r"\d{4,5}", d["postal_code"]):
        raise HTTPException(status_code=400, detail="Code postal invalide.")
    d["address"] = f"{d.get('street', '')}, {d.get('postal_code', '')} {d.get('city', '')}".strip(", ")
    _check_pin(body.lat, body.lng)
    if body.lat is not None:
        d["latitude"], d["longitude"] = body.lat, body.lng
    return d


_ADDRESS = (("street", "Adresse"), ("postal_code", "Code postal"), ("city", "Ville"))


def _require_address(doc: Dict[str, Any], body: StoreIn, creating: bool) -> None:
    """Adresse, Code postal and Ville are marked required (QA F26: a point de
    vente was saved with its name only, « Adresse à compléter »): a new one
    needs all three; an edit that touches the address keeps all three. Closing
    or reopening an older one without an address still works."""
    if not creating and all(getattr(body, k) is None for k, _ in _ADDRESS):
        return
    missing = [label for k, label in _ADDRESS if not (doc.get(k) or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Complétez : {', '.join(missing)}.")


@router.post("/api/owner/etablissement/stores")
def add_store(body: StoreIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    t = _tenant(tid)
    if not _view(tid, token_data)["can"]["plan_allows_stores"]:
        raise HTTPException(status_code=403, detail="Votre formule ne permet pas plusieurs points de vente.")
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Donnez un nom au point de vente.")
    branches = [b for b in t.get("branches") or []]
    from features import plan_limits
    f = plan_limits.tenant_features(tid)
    cap = int(f.get("establishments") or 0)
    if cap and max(1, len(branches)) >= cap:
        raise HTTPException(status_code=403, detail={**plan_limits.locked(f, "establishments"),
                            "message": f"Votre offre {f.get('label')} inclut {cap} établissement{'s' if cap > 1 else ''}.",
                            "upgrade": plan_limits._next_bigger(f, "establishments")})
    if not branches:
        # The shop itself becomes the main establishment, under the id its
        # untagged visits already belong to.
        lat, lng = _pos(t)
        branches.append({"id": MAIN, "name": t.get("name") or "Établissement principal", "is_main": True,
                         "street": _street(t), "postal_code": t.get("postal_code") or "",
                         "city": t.get("city") or "", "phone": t.get("phone") or "",
                         "address": t.get("address") or "",
                         **({"latitude": lat, "longitude": lng} if lat is not None else {})})
    # A new establishment starts with a blank card, OFF until its owner designs
    # it (user, 2026-10-12): no signup there before (features/store_cards).
    doc = _branch_doc(body)
    _require_address(doc, body, creating=True)
    new = {"id": str(uuid.uuid4()), "is_main": False, "created_at": _now(), "card_off": True, **doc}
    branches.append(new)
    _db.tenants.update_one({"id": tid}, {"$set": {"branches": branches}})
    return _view(tid, token_data)


@router.put("/api/owner/etablissement/stores/{store_id}")
@SV.records("etablissement")
def edit_store(store_id: str, body: StoreIn,
               token_data: TokenData = Depends(require_role(EDITORS, partial_ok=True))):
    tid = token_data.tenant_id
    t = _tenant(tid)
    owner = _full(token_data)
    if (getattr(token_data, "role", None) not in EDITORS and not owner) or store_id not in _covers(token_data, tid):
        raise HTTPException(status_code=403, detail="Ce point de vente ne fait pas partie des vôtres.")
    if body.status is not None and not owner:
        raise HTTPException(status_code=403, detail="Seul le propriétaire ferme ou rouvre un point de vente.")
    branches = t.get("branches") or []
    if not branches and store_id == MAIN:
        # No branches: the main establishment is the shop itself. Its name is
        # the shop's (the owner's to change, in block 1).
        base = {"street": _street(t), "postal_code": t.get("postal_code") or "", "city": t.get("city") or "",
                "phone": t.get("phone") or ""}
        doc = _branch_doc(StoreIn(**{**body.model_dump(), "name": None}), base)
        _require_address(doc, body, creating=False)
        sets = {k: doc[k] for k in ("street", "postal_code", "city", "phone", "address")}
        if body.lat is not None:
            sets.update({"lat": body.lat, "lng": body.lng, "pin_source": "manuel"})
        _db.tenants.update_one({"id": tid}, {"$set": sets})
        return _view(tid, token_data)
    idx = next((i for i, b in enumerate(branches) if b.get("id") == store_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Point de vente introuvable")
    if body.status is not None:
        if body.status not in ("open", "closed"):
            raise HTTPException(status_code=400, detail="Statut inconnu.")
        if body.status == "closed" and (branches[idx].get("is_main") or store_id == MAIN):
            raise HTTPException(status_code=400, detail="L'établissement principal ne peut pas être fermé.")
    doc = _branch_doc(body, branches[idx])
    _require_address(doc, body, creating=False)
    if body.status is not None:
        doc["status"] = body.status
        doc["closed_at" if body.status == "closed" else "reopened_at"] = _now()
    branches[idx] = doc
    sets: Dict[str, Any] = {"branches": branches}
    # The main establishment's address is the shop's address.
    if doc.get("is_main") or store_id == MAIN:
        sets.update({"street": doc.get("street", ""), "postal_code": doc.get("postal_code", ""),
                     "city": doc.get("city", ""), "address": doc.get("address", "")})
        if body.lat is not None:
            sets.update({"lat": body.lat, "lng": body.lng, "pin_source": "manuel"})
    _db.tenants.update_one({"id": tid}, {"$set": sets})
    return _view(tid, token_data)
