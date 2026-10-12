"""
Paramètres › Lien d'inscription & QR — the shop's signup link, its QR code,
how many people it brings in, and the page they land on.

Mounts at:
    GET  /api/owner/join-link              → everything the tab shows
    GET  /api/owner/join-link/slug-check   → is this custom name free?
    PUT  /api/owner/join-link/slug         → change the link's name
    PUT  /api/owner/join-link/page         → the signup page's own words
    GET  /api/join/{slug}/page             → (public) those words, for the page
    POST /api/join/{slug}/view             → (public) one visit of the page

Collections:
    tenants     `slug` (the live name), `previous_slugs` (every name it had —
                a QR code already printed on a counter must keep working after
                a rename), `join_page` (title, subtitle, benefits, button).
    join_views  one row per visitor, per day, per shop: {tenant_id, visitor,
                day, src, at}. A reload is not a second visit.
    customers   read-only; `signup_channel == "join_page"` marks the clients
                who signed up through the page (set by POST /api/join).

Honesty about the figures: visits are counted from the day this shipped.
Until a full comparison window has been measured, a delta is not shown, and
the conversion rate only compares signups and visits over the same span.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from auth import require_role, TokenData
from features import settings_versions as SV   # « Réinitialiser » (Paramètres)

router = APIRouter(tags=["join-link"])
_db = None

WINDOW_DAYS = 30
SLUG_MIN, SLUG_MAX = 3, 40
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Names a shop cannot take: they read as FidClic itself, or as a page of the app.
RESERVED = {
    "admin", "api", "app", "dashboard", "login", "register", "inscription", "join",
    "card", "carte", "fidclic", "fidelitour", "support", "aide", "help", "www",
    "static", "assets", "public", "modules", "onboarding", "cabinet", "facturation",
}
QR_SOURCE = "qr_store"
from services.sources import SIGNUP_SOURCES as _SIGNUP  # one list (services/sources)
KNOWN_SOURCES = set(_SIGNUP)

DEFAULT_PAGE = {
    "title": "Rejoignez notre programme de fidélité !",
    "subtitle": "Cumulez des points, profitez d'offres exclusives et récompensez votre fidélité.",
    "benefits": ["Des points à chaque achat", "Des offres exclusives",
                 "Un cadeau d'anniversaire", "Des surprises toute l'année"],
    "button": "Je m'inscris",
}
LIMITS = {"title": 80, "subtitle": 160, "benefit": 50, "benefits": 4, "button": 30}


def init(db):
    global _db
    _db = db
    try:
        db.join_views.create_index([("tenant_id", 1), ("visitor", 1), ("day", 1)], unique=True)
        db.join_views.create_index([("tenant_id", 1), ("at", -1)])
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
# slugs
# ---------------------------------------------------------------------------
def normalize_slug(raw: str) -> str:
    """"Le Corner Café" → "le-corner-cafe": accents off, anything else a dash."""
    ascii_name = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """The shop a link points at — by its current name, or by any name it had."""
    if not slug:
        return None
    return (_db.tenants.find_one({"slug": slug})
            or _db.tenants.find_one({"previous_slugs": slug}))


def check_slug(raw: str, tid: str) -> Dict[str, Any]:
    slug = normalize_slug(raw)
    out = {"slug": slug, "available": False, "reason": ""}
    if len(slug) < SLUG_MIN:
        out["reason"] = f"{SLUG_MIN} caractères minimum (lettres, chiffres, tirets)."
    elif len(slug) > SLUG_MAX:
        out["reason"] = f"{SLUG_MAX} caractères maximum."
    elif not SLUG_RE.match(slug):
        out["reason"] = "Lettres, chiffres et tirets uniquement."
    elif slug in RESERVED:
        out["reason"] = "Ce nom est réservé."
    else:
        other = tenant_by_slug(slug)
        if other and other.get("id") != tid:
            out["reason"] = "Ce nom est déjà pris par un autre commerce."
        else:
            out["available"] = True
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def _pct(now_value: float, was_value: float) -> Optional[float]:
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100, 1)


def stats(tid: str, at: Optional[datetime] = None, store: Optional[str] = None) -> Dict[str, Any]:
    """The page's figures — one establishment's (its members, its link's
    visits) when the account has several (multi-store, 2026-10-12)."""
    at = at or _now()
    start, prev_start = at - timedelta(days=WINDOW_DAYS), at - timedelta(days=2 * WINDOW_DAYS)
    cq: Dict[str, Any] = {"tenant_id": tid, **({"branch_id": store} if store else {})}
    customers = list(_db.customers.find(cq, {"_id": 0, "created_at": 1, "signup_channel": 1}))
    created = [(_aware(c.get("created_at")), c.get("signup_channel")) for c in customers]
    new_now = sum(1 for d, _ in created if d and d >= start)
    new_prev = sum(1 for d, _ in created if d and prev_start <= d < start)

    vq: Dict[str, Any] = {"tenant_id": tid, **({"store": store} if store else {})}
    first = _db.join_views.find_one(vq, sort=[("at", 1)])
    since = _aware(first.get("at")) if first else None

    def views(lo, hi, src=None):
        q: Dict[str, Any] = {**vq, "at": {"$gte": lo, "$lt": hi}}
        if src:
            q["src"] = src
        return _db.join_views.count_documents(q)

    scans_now = views(start, at + timedelta(seconds=1), QR_SOURCE)
    # A comparison is only fair once the previous window was fully measured.
    full_prev = bool(since and since <= prev_start)
    scans_prev = views(prev_start, start, QR_SOURCE) if full_prev else None

    def conversion(lo, hi):
        """Signups through the page over visits of the page, same span —
        which starts no earlier than the first visit ever measured."""
        if not since:
            return None
        lo = max(lo, since)
        if lo >= hi:
            return None
        visits = views(lo, hi)
        if not visits:
            return None
        signed = sum(1 for d, ch in created if d and lo <= d < hi and ch == "join_page")
        return round(min(signed / visits * 100, 100.0), 1)

    conv_now = conversion(start, at + timedelta(seconds=1))
    conv_prev = conversion(prev_start, start) if full_prev else None
    return {
        "window_days": WINDOW_DAYS,
        "new_signups": {"value": new_now, "delta_pct": _pct(new_now, new_prev)},
        "total": {"value": len(customers)},
        "qr_scans": {"value": scans_now,
                     "delta_pct": _pct(scans_now, scans_prev) if scans_prev is not None else None},
        "conversion": {"value": conv_now,
                       "delta_pts": (round(conv_now - conv_prev, 1)
                                     if conv_now is not None and conv_prev is not None else None)},
        "tracking_since": since.isoformat() if since else None,
    }


# ---------------------------------------------------------------------------
# the signup page's words
# ---------------------------------------------------------------------------
def page_of(tenant: Dict[str, Any]) -> Dict[str, Any]:
    saved = tenant.get("join_page") or {}
    page = {**DEFAULT_PAGE, **{k: v for k, v in saved.items() if k in DEFAULT_PAGE and v}}
    page["benefits"] = [b for b in (page.get("benefits") or []) if b][:LIMITS["benefits"]]
    return page


def _brand(tid: str) -> Dict[str, str]:
    """The shop's logo, as set on its Carte de fidélité."""
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1}) or {}
    return {"logo_url": tpl.get("logo_url") or ""}


# ---------------------------------------------------------------------------
# owner endpoints
# ---------------------------------------------------------------------------
def channels(tid: str, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One link per channel (user, 2026-10-08: the owner copies the
    Instagram link into the Instagram bio, nothing to type): its word, and how
    many clients each one brought — over the window and in all."""
    from services import sources as SRC
    at = at or _now()
    start = at - timedelta(days=WINDOW_DAYS)
    total: Dict[str, int] = {}
    recent: Dict[str, int] = {}
    for c in _db.customers.find({"tenant_id": tid}, {"_id": 0, "acquisition_source": 1, "created_at": 1}):
        k = SRC.key_of(c)
        total[k] = total.get(k, 0) + 1
        d = _aware(c.get("created_at"))
        if d and d >= start:
            recent[k] = recent.get(k, 0) + 1
    return [{"key": k, "label": SRC.label(k), "word": w, "total": total.get(k, 0), "recent": recent.get(k, 0)}
            for k, w in SRC.CHANNEL_WORDS.items()]


def _store_of(token: TokenData, request: Optional[Request]) -> Optional[str]:
    """The establishment chosen in the menu, when the account has several."""
    try:
        from features import store_scope as S
        sc = S.resolve(token, request)
        return sc.ids[0] if sc.ids and len(sc.ids) == 1 else None
    except Exception:
        return None


def _payload(tid: str, store: Optional[str] = None) -> Dict[str, Any]:
    t = _db.tenants.find_one({"id": tid}) or {}
    from features import store_links as SL
    return {
        # multi-store (2026-10-12): each establishment's own link and QR
        "stores": SL.public_stores(t) if t else [],
        "channels": channels(tid),
        "shop": {"name": t.get("name") or "", "city": t.get("city") or "",
                 "slug": t.get("slug") or "", **_brand(tid)},
        "stats": stats(tid, store=store),
        "store_id": store,
        "page": page_of(t),
        "defaults": DEFAULT_PAGE,
        "limits": {**LIMITS, "slug_min": SLUG_MIN, "slug_max": SLUG_MAX},
    }


@router.get("/api/owner/join-link")
def get_join_link(request: Request = None,
                  token_data: TokenData = Depends(require_role(["business_owner", "manager"], partial_ok=True))):
    return _payload(token_data.tenant_id, _store_of(token_data, request))


@router.get("/api/owner/join-link/slug-check")
def slug_check(slug: str = Query(""),
               token_data: TokenData = Depends(require_role(["business_owner"]))):
    return check_slug(slug, token_data.tenant_id)


class SlugIn(BaseModel):
    slug: str


@router.put("/api/owner/join-link/slug")
@SV.records("lien-inscription")
def put_slug(body: SlugIn, request: Request = None, token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    result = check_slug(body.slug, tid)
    if not result["available"]:
        raise HTTPException(status_code=400, detail=result["reason"])
    t = _db.tenants.find_one({"id": tid}) or {}
    old, new = t.get("slug"), result["slug"]
    if old != new:
        update: Dict[str, Any] = {"$set": {"slug": new, "slug_updated_at": _now()}}
        if old:
            update["$addToSet"] = {"previous_slugs": old}
        _db.tenants.update_one({"id": tid}, update)
        # Taking back a name the shop once had: it is live again, not "previous".
        _db.tenants.update_one({"id": tid}, {"$pull": {"previous_slugs": new}})
    return _payload(tid, _store_of(token_data, request))


class PageIn(BaseModel):
    title: str = ""
    subtitle: str = ""
    benefits: List[str] = []
    button: str = ""


@router.put("/api/owner/join-link/page")
@SV.records("lien-inscription")
def put_page(body: PageIn, request: Request = None, token_data: TokenData = Depends(require_role(["business_owner"]))):
    title, subtitle, button = body.title.strip(), body.subtitle.strip(), body.button.strip()
    benefits = [b.strip() for b in body.benefits if b and b.strip()]
    if not title or not button:
        raise HTTPException(status_code=400, detail="Le titre et le bouton ne peuvent pas être vides.")
    if len(title) > LIMITS["title"] or len(subtitle) > LIMITS["subtitle"] or len(button) > LIMITS["button"]:
        raise HTTPException(status_code=400, detail="Texte trop long.")
    if len(benefits) > LIMITS["benefits"] or any(len(b) > LIMITS["benefit"] for b in benefits):
        raise HTTPException(status_code=400,
                            detail=f"{LIMITS['benefits']} avantages maximum, {LIMITS['benefit']} caractères chacun.")
    _db.tenants.update_one({"id": token_data.tenant_id}, {"$set": {"join_page": {
        "title": title, "subtitle": subtitle, "benefits": benefits, "button": button,
        "updated_at": _now()}}})
    return _payload(token_data.tenant_id, _store_of(token_data, request))


# ---------------------------------------------------------------------------
# public endpoints — the signup page itself
# ---------------------------------------------------------------------------
@router.get("/api/join/{slug}/page")
def public_page(slug: str, store: Optional[str] = None):
    """`store`: the link's second segment — an establishment's slug (its own
    card and logo) or a channel word (ignored)."""
    t = tenant_by_slug(slug)
    if not t:
        raise HTTPException(status_code=404, detail="Commerce introuvable")
    from features import store_links as SL
    from features import store_cards as SC
    stores = SL.public_stores(t)
    st = SL.store_by(t, store)
    with SC.store(t["id"], st["id"] if st else None):
        brand = _brand(t["id"])
    return {"slug": t.get("slug"), "name": t.get("name") or "", "city": t.get("city") or "",
            "page": page_of(t), **brand,
            # « Votre établissement »: the stores of the account (one → no question);
            # a store whose card is off is listed (its link says so) but not offered
            "stores": stores if len(stores) > 1 else [],
            "card_off_message": SL.CARD_OFF_MSG}


class ViewIn(BaseModel):
    visitor: str
    src: Optional[str] = None
    store: Optional[str] = None          # the establishment of the link (its slug)


@router.post("/api/join/{slug}/view")
def record_view(slug: str, body: ViewIn):
    """One visit per visitor per day. The visitor id is a random string the
    page keeps in the browser — no personal data, no cookie banner needed."""
    t = tenant_by_slug(slug)
    visitor = re.sub(r"[^A-Za-z0-9_-]", "", body.visitor or "")[:64]
    if not t or len(visitor) < 8:
        return {"ok": False}
    from services.sources import normalize
    src = normalize(body.src) or ""
    from features import store_links as SL
    st = SL.store_by(t, body.store)
    at = _now()
    try:
        _db.join_views.update_one(
            {"tenant_id": t["id"], "visitor": visitor, "day": at.strftime("%Y-%m-%d")},
            {"$setOnInsert": {"tenant_id": t["id"], "visitor": visitor,
                              "day": at.strftime("%Y-%m-%d"), "at": at,
                              "src": src if src in KNOWN_SOURCES else None,
                              "store": st["id"] if st else None}},
            upsert=True)
    except Exception:
        # Two tabs racing on the unique index: the visit is already counted.
        pass
    return {"ok": True}
