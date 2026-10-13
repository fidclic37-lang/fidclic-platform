"""
Catalogue produits — the shop's products, their categories, and what sells.

Mounts at:
    GET    /api/owner/catalogue/page?days=30         → everything the page shows
    POST   /api/owner/catalogue/products              → add a product
    PUT    /api/owner/catalogue/products/{id}         → edit one
    DELETE /api/owner/catalogue/products/{id}         → remove one
    POST   /api/owner/catalogue/products/{id}/duplicate
    POST   /api/owner/catalogue/products/bulk         → activate / deactivate / move / delete many
    POST   /api/owner/catalogue/products/import       → many at once (a photo of the menu, checked)
    PUT    /api/owner/catalogue/products/{id}/image   → its photo (a small JPEG/PNG/WebP)
    DELETE /api/owner/catalogue/products/{id}/image
    GET    /api/catalogue-image/{image_id}            → (public) the photo itself
    POST   /api/owner/catalogue/categories            → add a category
    PUT    /api/owner/catalogue/categories            → rename / recolour (moves its products)
    DELETE /api/owner/catalogue/categories/{name}     → remove (its products move elsewhere)

Storage — the same `tenant_catalog` document the Scan page and the older
settings editor already use, so the three never disagree:
    items:      [{id, name, price, category, subtitle, active, image_id,
                  created_at, updated_at}]   (older rows lack the new fields:
                  read as active, no subtitle, no photo)
    categories: [{name, color}]  — colours, and categories with no product yet
Photos live apart, in `catalogue_images`, so the Scan page's catalogue stays
light: {id, tenant_id, mime, data (bytes)}. A replaced photo gets a new id, so
its URL can be cached for ever.

Sales are what staff record at the till: each visit's `items` lines
({item_id, name, qty, price}) from the Scan page's picker. A line is matched
to its product by id, or by name for lines written before ids existed.
"""
from __future__ import annotations

import base64
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from auth import require_role, TokenData
from features import store_scope as S

router = APIRouter(tags=["catalogue"])
_db = None

PALETTE = ["blue", "orange", "violet", "green", "rose", "amber", "teal", "slate"]
UNCATEGORISED = "Sans catégorie"
PERIODS = (7, 30, 90, 365)
DEFAULT_DAYS = 30
TOP_SHARE = 0.8            # "Produits les plus vendus" = those making 80 % of sales
MAX_PRODUCTS = 500
MAX_IMAGE_BYTES = 400_000
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
NAME_MAX, SUBTITLE_MAX, CATEGORY_MAX = 60, 60, 40
# The catalogue is the whole shop's: the owner edits it. Its sales follow the
# establishment menu (features/store_scope.py) — what was sold at those tills.
READERS = ["business_owner", "administrateur", "manager"]


def init(db):
    global _db
    _db = db
    try:
        db.catalogue_images.create_index("id", unique=True)
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


def _money(x: float) -> float:
    return round(float(x or 0), 2)


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------
def _doc(tid: str) -> Dict[str, Any]:
    return _db.tenant_catalog.find_one({"tenant_id": tid}) or {"tenant_id": tid, "items": [], "categories": []}


def _items(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(i) for i in doc.get("items") or []]


def _save(tid: str, items: List[Dict[str, Any]], categories: Optional[List[Dict[str, Any]]] = None) -> None:
    update: Dict[str, Any] = {"tenant_id": tid, "items": items, "updated_at": _now()}
    if categories is not None:
        update["categories"] = categories
    _db.tenant_catalog.update_one({"tenant_id": tid}, {"$set": update}, upsert=True)


def _category_list(doc: Dict[str, Any], items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every category the shop has — declared ones first, then any a product
    carries that was never declared (typed in the older editor) — each with a
    colour, handed out from the palette in order so it never changes."""
    declared = [dict(c) for c in doc.get("categories") or [] if c.get("name")]
    names = [c["name"] for c in declared]
    for it in items:
        cat = (it.get("category") or "").strip()
        if cat and cat not in names:
            names.append(cat)
            declared.append({"name": cat})
    used = {c.get("color") for c in declared if c.get("color")}
    free = [p for p in PALETTE if p not in used] or PALETTE
    k = 0
    for c in declared:
        if c.get("color") not in PALETTE:
            c["color"] = free[k % len(free)]
            k += 1
    return declared


def _image_url(image_id: Optional[str]) -> Optional[str]:
    return f"/api/catalogue-image/{image_id}" if image_id else None


# ---------------------------------------------------------------------------
# sales
# ---------------------------------------------------------------------------
def sales(tid: str, items: List[Dict[str, Any]], since: datetime, until: Optional[datetime] = None,
          scope: Optional["S.Scope"] = None) -> Dict[str, Dict[str, float]]:
    """{product id: {sales, revenue}} from the visits' item lines."""
    by_name = {(i.get("name") or "").strip().lower(): i["id"] for i in items}
    ids = {i["id"] for i in items}
    q: Dict[str, Any] = {"tenant_id": tid, "items.0": {"$exists": True}, "visit_time": {"$gte": since},
                         **(S.visit_filter(scope) if scope else {})}
    if until:
        q["visit_time"]["$lt"] = until
    out: Dict[str, Dict[str, float]] = {}
    for v in _db.visits.find(q, {"_id": 0, "items": 1}):
        for line in v.get("items") or []:
            pid = str(line.get("item_id") or "")
            if pid not in ids:
                pid = by_name.get(str(line.get("name") or "").strip().lower(), "")
            if not pid:
                continue
            qty = int(line.get("qty") or line.get("quantity") or 1)
            revenue = float(line.get("line_total") or (float(line.get("price") or 0) * qty))
            acc = out.setdefault(pid, {"sales": 0, "revenue": 0.0})
            acc["sales"] += qty
            acc["revenue"] += revenue
    return out


def daily(tid: str, items: List[Dict[str, Any]], since: datetime, days: int,
          scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    ids = {i["id"] for i in items}
    by_name = {(i.get("name") or "").strip().lower(): i["id"] for i in items}
    buckets: Dict[str, Dict[str, float]] = {}
    for v in _db.visits.find({"tenant_id": tid, "items.0": {"$exists": True}, "visit_time": {"$gte": since},
                              **(S.visit_filter(scope) if scope else {})},
                             {"_id": 0, "items": 1, "visit_time": 1}):
        at = _aware(v.get("visit_time"))
        if not at:
            continue
        key = at.strftime("%Y-%m-%d")
        for line in v.get("items") or []:
            pid = str(line.get("item_id") or "")
            if pid not in ids and not by_name.get(str(line.get("name") or "").strip().lower()):
                continue
            qty = int(line.get("qty") or line.get("quantity") or 1)
            b = buckets.setdefault(key, {"sales": 0, "revenue": 0.0})
            b["sales"] += qty
            b["revenue"] += float(line.get("line_total") or (float(line.get("price") or 0) * qty))
    start = since.date()
    return [{"date": (start + timedelta(days=n)).isoformat(),
             "sales": int(buckets.get((start + timedelta(days=n)).isoformat(), {}).get("sales", 0)),
             "revenue": _money(buckets.get((start + timedelta(days=n)).isoformat(), {}).get("revenue", 0))}
            for n in range(days + 1)]


def top_count(counts: List[int], share: float = TOP_SHARE) -> int:
    """How few products make `share` of all sales — the shop's real best-sellers."""
    total = sum(counts)
    if not total:
        return 0
    running, n = 0, 0
    for c in sorted(counts, reverse=True):
        if c <= 0:
            break
        running += c
        n += 1
        if running >= total * share:
            break
    return n


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------
def _payload(tid: str, days: int = DEFAULT_DAYS, scope: Optional["S.Scope"] = None,
             can_edit: bool = True) -> Dict[str, Any]:
    days = days if days in PERIODS else DEFAULT_DAYS
    at = _now()
    since, prev_since = at - timedelta(days=days), at - timedelta(days=2 * days)
    doc = _doc(tid)
    items = _items(doc)
    sold = sales(tid, items, since, scope=scope)
    sold_prev = sales(tid, items, prev_since, since, scope=scope)
    cats = _category_list(doc, items)
    colour = {c["name"]: c["color"] for c in cats}

    products = []
    for it in items:
        s = sold.get(it["id"], {})
        products.append({
            "id": it["id"], "name": it.get("name") or "", "subtitle": it.get("subtitle") or "",
            "category": it.get("category") or "", "color": colour.get(it.get("category") or "", "slate"),
            "price": _money(it.get("price")), "active": it.get("active", True) is not False,
            "image_url": _image_url(it.get("image_id")),
            "sales": int(s.get("sales", 0)), "revenue": _money(s.get("revenue", 0)),
            "sales_prev": int(sold_prev.get(it["id"], {}).get("sales", 0)),
            "created_at": (_aware(it.get("created_at")) or at).isoformat(),
        })
    active = [p for p in products if p["active"]]
    for c in cats:
        mine = [p for p in products if p["category"] == c["name"]]
        c.update({"count": len(mine), "active_count": sum(1 for p in mine if p["active"]),
                  "sales": sum(p["sales"] for p in mine), "revenue": _money(sum(p["revenue"] for p in mine))})
    total_sales = sum(p["sales"] for p in products)
    total_revenue = sum(p["revenue"] for p in products)
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    return {
        "shop": tenant.get("name") or "",
        "scope": scope.describe() if scope else None,
        "can_edit": can_edit,
        "days": days, "periods": list(PERIODS),
        "kpis": {
            "total": len(products),
            "top": top_count([p["sales"] for p in products]),
            "inactive": len(products) - len(active),
            "avg_price": _money(sum(p["price"] for p in active) / len(active)) if active else 0.0,
        },
        "products": products,
        "categories": cats,
        "stats": {
            "sales": total_sales, "revenue": _money(total_revenue),
            "sold_products": sum(1 for p in products if p["sales"] > 0),
            "avg_sold_price": _money(total_revenue / total_sales) if total_sales else 0.0,
            "prev_sales": sum(p["sales_prev"] for p in products),
            "daily": daily(tid, items, since, days, scope),
        },
        "palette": PALETTE,
        "limits": {"name": NAME_MAX, "subtitle": SUBTITLE_MAX, "category": CATEGORY_MAX,
                   "products": MAX_PRODUCTS, "image_bytes": MAX_IMAGE_BYTES},
    }


@router.get("/api/owner/catalogue/page")
def page(days: int = Query(DEFAULT_DAYS), request: Request = None,
         token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _payload(token_data.tenant_id, days, S.resolve(token_data, request),
                    can_edit=token_data.role == "business_owner")


def _view(tid: str, token_data: TokenData, request: Optional[Request]) -> Dict[str, Any]:
    """What an edit answers with: the page, on the establishments shown."""
    return _payload(tid, scope=S.resolve(token_data, request))


# ---------------------------------------------------------------------------
# products
# ---------------------------------------------------------------------------
class ProductIn(BaseModel):
    name: str
    price: Optional[float] = None        # required — but refused in French, not as a 422
    category: Optional[str] = ""
    subtitle: Optional[str] = ""
    active: bool = True


def _clean(body: ProductIn) -> Dict[str, Any]:
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom au produit.")
    if len(name) > NAME_MAX:
        raise HTTPException(status_code=400, detail=f"Nom limité à {NAME_MAX} caractères.")
    # no price is not « 0 » (QA F31: an erased price made a paid product free);
    # a 0 sent on purpose is a free product
    if body.price is None:
        raise HTTPException(status_code=400, detail="Prix obligatoire : indiquez le prix (0 pour un produit offert).")
    if body.price < 0 or body.price > 100000:
        raise HTTPException(status_code=400, detail="Prix invalide.")
    subtitle = (body.subtitle or "").strip()
    category = (body.category or "").strip()
    if len(subtitle) > SUBTITLE_MAX or len(category) > CATEGORY_MAX:
        raise HTTPException(status_code=400, detail="Texte trop long.")
    return {"name": name, "price": _money(body.price), "category": category or None,
            "subtitle": subtitle, "active": bool(body.active)}


def _find(items: List[Dict[str, Any]], pid: str) -> Dict[str, Any]:
    for it in items:
        if it.get("id") == pid:
            return it
    raise HTTPException(status_code=404, detail="Produit introuvable.")


def _declare(doc: Dict[str, Any], items: List[Dict[str, Any]], category: Optional[str]) -> List[Dict[str, Any]]:
    cats = _category_list(doc, items)
    if category and category not in [c["name"] for c in cats]:
        cats.append({"name": category})
        cats = _category_list({"categories": cats}, items)
    return [{"name": c["name"], "color": c["color"]} for c in cats]


@router.post("/api/owner/catalogue/products")
def create_product(body: ProductIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    if len(items) >= MAX_PRODUCTS:
        raise HTTPException(status_code=400, detail=f"{MAX_PRODUCTS} produits maximum.")
    fields = _clean(body)
    now = _now()
    product = {"id": str(uuid.uuid4()), **fields, "image_id": None, "created_at": now, "updated_at": now}
    items.append(product)
    _save(tid, items, _declare(doc, items, fields["category"]))
    return {"id": product["id"], **_view(tid, token_data, request)}


@router.put("/api/owner/catalogue/products/{pid}")
def update_product(pid: str, body: ProductIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    it = _find(items, pid)
    it.update(_clean(body))
    it["updated_at"] = _now()
    _save(tid, items, _declare(doc, items, it.get("category")))
    return _view(tid, token_data, request)


def _drop_images(tid: str, image_ids: List[Optional[str]]) -> None:
    ids = [i for i in image_ids if i]
    if ids:
        _db.catalogue_images.delete_many({"tenant_id": tid, "id": {"$in": ids}})


@router.delete("/api/owner/catalogue/products/{pid}")
def delete_product(pid: str, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    it = _find(items, pid)
    _save(tid, [i for i in items if i.get("id") != pid])
    _drop_images(tid, [it.get("image_id")])
    return _view(tid, token_data, request)


@router.post("/api/owner/catalogue/products/{pid}/duplicate")
def duplicate_product(pid: str, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    if len(items) >= MAX_PRODUCTS:
        raise HTTPException(status_code=400, detail=f"{MAX_PRODUCTS} produits maximum.")
    src = _find(items, pid)
    now = _now()
    copy = {**src, "id": str(uuid.uuid4()), "name": f"{src.get('name', '')} (copie)"[:NAME_MAX],
            "image_id": None, "created_at": now, "updated_at": now}
    img = _db.catalogue_images.find_one({"tenant_id": tid, "id": src.get("image_id")}) if src.get("image_id") else None
    if img:
        copy["image_id"] = uuid.uuid4().hex
        _db.catalogue_images.insert_one({"id": copy["image_id"], "tenant_id": tid,
                                         "mime": img["mime"], "data": img["data"], "created_at": now})
    items.insert(items.index(src) + 1, copy)
    _save(tid, items)
    return {"id": copy["id"], **_view(tid, token_data, request)}


class ImportIn(BaseModel):
    items: List[ProductIn]


@router.post("/api/owner/catalogue/products/import")
def import_products(body: ImportIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    """Several products at once — the lines read from a photo of the menu,
    after the owner has checked them. A name already in the catalogue is
    skipped rather than doubled."""
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    have = {(i.get("name") or "").strip().lower() for i in items}
    now = _now()
    added = 0
    for raw in body.items:
        fields = _clean(raw)
        if fields["name"].lower() in have:
            continue
        if len(items) >= MAX_PRODUCTS:
            break
        items.append({"id": str(uuid.uuid4()), **fields, "image_id": None, "created_at": now, "updated_at": now})
        have.add(fields["name"].lower())
        added += 1
    cats = _category_list(doc, items)
    _save(tid, items, [{"name": c["name"], "color": c["color"]} for c in cats])
    return {"added": added, **_view(tid, token_data, request)}


class BulkIn(BaseModel):
    ids: List[str]
    action: str                     # activate | deactivate | delete | category
    category: Optional[str] = None


@router.post("/api/owner/catalogue/products/bulk")
def bulk(body: BulkIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    chosen = set(body.ids)
    if not chosen:
        raise HTTPException(status_code=400, detail="Aucun produit sélectionné.")
    now = _now()
    if body.action == "delete":
        _drop_images(tid, [i.get("image_id") for i in items if i.get("id") in chosen])
        _save(tid, [i for i in items if i.get("id") not in chosen])
        return _view(tid, token_data, request)
    if body.action not in ("activate", "deactivate", "category"):
        raise HTTPException(status_code=400, detail="Action inconnue.")
    category = (body.category or "").strip() or None
    if body.action == "category" and category and len(category) > CATEGORY_MAX:
        raise HTTPException(status_code=400, detail="Nom de catégorie trop long.")
    for it in items:
        if it.get("id") not in chosen:
            continue
        if body.action == "category":
            it["category"] = category
        else:
            it["active"] = body.action == "activate"
        it["updated_at"] = now
    _save(tid, items, _declare(doc, items, category) if body.action == "category" else None)
    return _view(tid, token_data, request)


# ---------------------------------------------------------------------------
# photos
# ---------------------------------------------------------------------------
class ImageIn(BaseModel):
    data_url: str


@router.put("/api/owner/catalogue/products/{pid}/image")
def put_image(pid: str, body: ImageIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    m = re.match(r"^data:(image/[a-z]+);base64,(.+)$", body.data_url or "", re.S)
    if not m or m.group(1) not in IMAGE_MIMES:
        raise HTTPException(status_code=400, detail="Image JPEG, PNG ou WebP attendue.")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Image illisible.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image trop lourde.")
    doc = _doc(tid)
    items = _items(doc)
    it = _find(items, pid)
    old = it.get("image_id")
    it["image_id"] = uuid.uuid4().hex
    it["updated_at"] = _now()
    _db.catalogue_images.insert_one({"id": it["image_id"], "tenant_id": tid, "mime": m.group(1),
                                     "data": raw, "created_at": _now()})
    _save(tid, items)
    _drop_images(tid, [old])
    return _view(tid, token_data, request)


@router.delete("/api/owner/catalogue/products/{pid}/image")
def delete_image(pid: str, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    it = _find(items, pid)
    old, it["image_id"] = it.get("image_id"), None
    _save(tid, items)
    _drop_images(tid, [old])
    return _view(tid, token_data, request)


@router.get("/api/catalogue-image/{image_id}")
def get_image(image_id: str):
    """Public on purpose: a product photo is shown to staff and clients alike.
    The id is random and changes with every new photo, so it caches for ever."""
    img = _db.catalogue_images.find_one({"id": image_id})
    if not img:
        raise HTTPException(status_code=404, detail="Image introuvable")
    return Response(content=bytes(img["data"]), media_type=img.get("mime") or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------------------------------------------------------------------
# categories
# ---------------------------------------------------------------------------
class CategoryIn(BaseModel):
    name: str
    color: Optional[str] = None
    old_name: Optional[str] = None


def _cat_name(raw: str) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom à la catégorie.")
    if len(name) > CATEGORY_MAX:
        raise HTTPException(status_code=400, detail=f"{CATEGORY_MAX} caractères maximum.")
    return name


@router.post("/api/owner/catalogue/categories")
def create_category(body: CategoryIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    name = _cat_name(body.name)
    cats = _category_list(doc, items)
    if name.lower() in [c["name"].lower() for c in cats]:
        raise HTTPException(status_code=400, detail="Cette catégorie existe déjà.")
    cats.append({"name": name, "color": body.color if body.color in PALETTE else None})
    cats = _category_list({"categories": cats}, items)
    _save(tid, items, [{"name": c["name"], "color": c["color"]} for c in cats])
    return _view(tid, token_data, request)


@router.put("/api/owner/catalogue/categories")
def update_category(body: CategoryIn, request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    old = (body.old_name or "").strip()
    name = _cat_name(body.name)
    cats = _category_list(doc, items)
    target = next((c for c in cats if c["name"] == old), None)
    if not target:
        raise HTTPException(status_code=404, detail="Catégorie introuvable.")
    if name != old and name.lower() in [c["name"].lower() for c in cats if c is not target]:
        raise HTTPException(status_code=400, detail="Une autre catégorie porte déjà ce nom.")
    target["name"] = name
    if body.color in PALETTE:
        target["color"] = body.color
    for it in items:
        if (it.get("category") or "") == old:
            it["category"] = name
    _save(tid, items, [{"name": c["name"], "color": c["color"]} for c in cats])
    return _view(tid, token_data, request)


@router.delete("/api/owner/catalogue/categories/{name}")
def delete_category(name: str, move_to: str = Query(""),
                    request: Request = None,
        token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    doc = _doc(tid)
    items = _items(doc)
    cats = _category_list(doc, items)
    if name not in [c["name"] for c in cats]:
        raise HTTPException(status_code=404, detail="Catégorie introuvable.")
    dest = move_to.strip() or None
    if dest == name:
        raise HTTPException(status_code=400, detail="Choisissez une autre catégorie.")
    for it in items:
        if (it.get("category") or "") == name:
            it["category"] = dest
    keep = [{"name": c["name"], "color": c["color"]} for c in cats if c["name"] != name]
    if dest and dest not in [c["name"] for c in keep]:
        keep.append({"name": dest})
        keep = [{"name": c["name"], "color": c["color"]} for c in _category_list({"categories": keep}, items)]
    _save(tid, items, keep)
    return _view(tid, token_data, request)
