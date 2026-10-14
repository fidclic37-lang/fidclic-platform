"""
Each establishment's own signup link and QR (user, 2026-10-12, multi-store).

  /join/<account-slug>/<store-slug>[/<channel>]   e.g. /join/royal-trim/palissy/insta

A customer who signs up through a store's link (or QR) is that store's member:
customers.branch_id is their « établissement d'origine », the store whose card
they carry and the only one that messages them. A visit still counts where it
is scanned. The account's own link (/join/royal-trim) asks « Votre
établissement » when there are several; a friend's card (parrainage) makes the
friend a member of the parrain's store. The owner — or an administrateur of
that store — can move a client to another store.

A store's slug comes from its name (« ROYAL TRIM PALISSY » on « royal-trim »
→ « palissy »), unique in the account, never a channel word; the owner can
change it.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import TokenData, require_role

router = APIRouter()
_db = None

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SLUG_MIN, SLUG_MAX = 2, 40
MAIN_WORD = "principal"


def init(db) -> None:
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(raw: str) -> str:
    s = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:SLUG_MAX].strip("-")


def _reserved() -> set:
    from services import sources as SRC
    return set(SRC.CHANNEL_WORDS.values()) | set(SRC.CHANNEL_WORDS) | {"preview", "inscription", "join", "p"}


def _open(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]


def multi(t: Dict[str, Any]) -> bool:
    return len(_open(t)) > 1


def _base_slug(t: Dict[str, Any], b: Dict[str, Any]) -> str:
    """The store's name without the account's own words: « palissy »."""
    full = slugify(b.get("name") or "")
    acct = slugify(t.get("name") or "") or (t.get("slug") or "")
    rest = full[len(acct):].strip("-") if acct and full.startswith(acct) else full
    if not rest or b.get("is_main") and not rest:
        rest = MAIN_WORD
    return rest or MAIN_WORD


def ensure_slugs(t: Dict[str, Any]) -> Dict[str, Any]:
    """Every open store gets a slug once (kept afterwards, even on a rename)."""
    branches = t.get("branches") or []
    taken = {b["slug"] for b in branches if b.get("slug")}
    changed = False
    reserved = _reserved()
    for b in branches:
        if not b.get("id") or b.get("slug"):
            continue
        base = _base_slug(t, b)
        if base in reserved:
            base = f"{base}-store"
        cand, n = base, 2
        while cand in taken:
            cand, n = f"{base}-{n}", n + 1
        b["slug"] = cand
        taken.add(cand)
        changed = True
    if changed and _db is not None:
        _db.tenants.update_one({"id": t["id"]}, {"$set": {"branches": branches}})
    return t


def public_stores(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    ensure_slugs(t)
    return [{"id": b["id"], "slug": b.get("slug"), "name": b.get("name") or "Établissement",
             "city": b.get("city") or "", "street": b.get("street") or "",
             "card_off": bool(b.get("card_off"))} for b in _open(t)]


def _signup(t: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The stores a customer may join: open, and with their card on (a store
    created since 2026-10-12 is off until its owner designs its card)."""
    return [b for b in _open(t) if not b.get("card_off")]


CARD_OFF_MSG = ("Cet établissement prépare encore sa carte de fidélité : "
                "les inscriptions ouvriront très bientôt.")


def store_by(t: Dict[str, Any], key: Optional[str]) -> Optional[Dict[str, Any]]:
    """A store of this account by slug or id (open ones only)."""
    if not key:
        return None
    k = str(key).strip().lower()
    ensure_slugs(t)
    for b in _open(t):
        if b.get("slug") == k or str(b.get("id")).lower() == k:
            return b
    for b in _open(t):                       # a renamed address: printed QR codes keep working
        if k in (b.get("previous_slugs") or []):
            return b
    return None


def parrain_store(t: Dict[str, Any], parrain: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The store a friend's card brings its filleul into — always one, never a
    question (user, 2026-10-14: « jis store ka card scan kiya gya hai usi store
    ka card banayega »). The parrain's own store; a card from before the stores
    (no store, or one closed / not taking signups since) belongs to the main
    shop, as every card did then. None only for a one-shop account."""
    stores = _signup(t)
    if not stores:
        return None
    pid = (parrain or {}).get("branch_id")
    return next((b for b in stores if b["id"] == pid), None) \
        or next((b for b in stores if b.get("is_main")), None) or stores[0]


def home_for_signup(t: Dict[str, Any], store: Optional[str], parrain: Optional[Dict[str, Any]],
                    strict: bool = True, parrain_link: bool = False) -> Optional[str]:
    """The new customer's home store, or a French 400.
    - a friend's card (`parrain_link`, even one not found): the parrain's store,
      see parrain_store — the form never asks;
    - else the store of the link, or the one chosen on the form;
    - one open store: that one; none (a one-shop account): None."""
    stores = _signup(t)
    if not stores:
        return None
    if parrain or parrain_link:
        return parrain_store(t, parrain)["id"]
    hit = store_by(t, store)
    if hit and hit.get("card_off"):
        raise HTTPException(status_code=400, detail={"code": "store_card_off", "message": CARD_OFF_MSG})
    if hit:
        return hit["id"]
    if len(stores) == 1:
        return stores[0]["id"]
    if store:
        raise HTTPException(status_code=400, detail="Cet établissement n'existe pas ou n'accepte plus d'inscriptions.")
    if strict:
        raise HTTPException(status_code=400, detail={"code": "store_required",
                                                     "message": "Choisissez votre établissement."})
    return None


def link_of(t: Dict[str, Any], b: Dict[str, Any], base: str) -> str:
    return f"{base}/join/{t.get('slug')}/{b.get('slug')}"


# ---------------------------------------------------------------------------
# owner endpoints
# ---------------------------------------------------------------------------
class StoreSlugIn(BaseModel):
    slug: str


@router.put("/api/owner/stores/{branch_id}/slug")
def put_store_slug(branch_id: str, body: StoreSlugIn,
                   token_data: TokenData = Depends(require_role(["business_owner"]))):
    t = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    ensure_slugs(t)
    branches = t.get("branches") or []
    me = next((b for b in branches if b.get("id") == branch_id and b.get("status") != "closed"), None)
    if not me:
        raise HTTPException(status_code=404, detail="Établissement introuvable.")
    slug = slugify(body.slug)
    if len(slug) < SLUG_MIN or not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail=f"Adresse : {SLUG_MIN} à {SLUG_MAX} lettres ou chiffres, séparés par des tirets.")
    if slug in _reserved():
        raise HTTPException(status_code=400, detail="Ce mot est réservé (canal de diffusion) : choisissez-en un autre.")
    if any((b.get("slug") == slug or slug in (b.get("previous_slugs") or [])) and b.get("id") != branch_id for b in branches):
        raise HTTPException(status_code=400, detail="Un autre établissement utilise déjà cette adresse.")
    if me.get("slug") != slug:
        prev = [p for p in (me.get("previous_slugs") or []) if p != slug]
        if me.get("slug"):
            prev.append(me["slug"])
        me["previous_slugs"] = prev[-5:]
        me["slug"] = slug
        _db.tenants.update_one({"id": t["id"]}, {"$set": {"branches": branches}})
    return {"id": branch_id, "slug": slug}


class HomeStoreIn(BaseModel):
    branch_id: str


@router.put("/api/owner/customers/{customer_id}/home-store")
def put_home_store(customer_id: str, body: HomeStoreIn,
                   token_data: TokenData = Depends(require_role(["business_owner", "administrateur"], partial_ok=True))):
    """« Établissement d'origine »: the owner moves a client to any store; an
    administrateur only between stores it works in."""
    tid = token_data.tenant_id
    t = _db.tenants.find_one({"id": tid}) or {}
    cust = _db.customers.find_one({"id": customer_id, "tenant_id": tid, "deleted_at": None}, {"_id": 0})
    if not cust:
        raise HTTPException(status_code=404, detail="Client introuvable.")
    target = next((b for b in _open(t) if b["id"] == body.branch_id), None)
    if not target:
        raise HTTPException(status_code=400, detail="Établissement inconnu ou fermé.")
    if target.get("card_off"):
        raise HTTPException(status_code=400, detail="Cet établissement n'a pas encore sa carte de fidélité : "
                                                    "créez-la (Carte de fidélité) avant d'y rattacher des clients.")
    if token_data.role != "business_owner":
        from features import store_scope as S
        sc = S.resolve(token_data, requested="")
        mine = set(sc.allowed)
        if target["id"] not in mine or (cust.get("branch_id") and cust["branch_id"] not in mine):
            raise HTTPException(status_code=403, detail="Cet établissement ne fait pas partie de votre accès.")
    if cust.get("branch_id") != target["id"]:
        _db.customers.update_one({"id": customer_id}, {"$set": {
            "branch_id": target["id"], "home_store_changed_at": _now(),
            "home_store_changed_by": getattr(token_data, "email", None)}})
        try:                       # the card follows its store (Wallet refresh)
            from features.wallet_passes import notify_customer
            notify_customer(customer_id)
        except Exception as exc:
            print(f"home store: pass not refreshed ({exc})")
    return {"ok": True, "branch_id": target["id"], "name": target.get("name")}
