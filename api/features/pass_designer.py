"""
Apple « Pass Designer » templates, used as the card's design (user, 2026-10-06:
design the card in Pass Designer, add it to Apple Wallet, test the
notifications, then use it in FidClic).

WHAT A TEMPLATE IS
    The `.pkpasstemplate` package Pass Designer saves (macOS 27): a pass.json
    (any style — posterGeneric, generic, storeCard, coupon, eventTicket,
    boardingPass — colours, fields, barcodes, featuredActions, Pass Designer's
    own `_id`s) and its images (background@2x.png, primaryLogo@2x.png…).

WHAT FIDCLIC DOES WITH IT (Apple's Pass Builder idea, server side)
    The template is the design; each customer's pass is the template filled
    in and signed by us:
      • identity, serial, web service, barcode message: ours, so the pass is
        updated and notified like every FidClic card;
      • fields: a value is the customer's own when its KEY says so (CUST_NAME,
        CUST_ID, POINTS, STAMPS…) or when it holds a {placeholder}; the rest is
        the business's text as designed;
      • the back: the template's rows, then ours (« Offre du moment » with its
        changeMessage — what makes a campaign notify —, next reward, links…);
      • a poster without its own fallback gets a `generic` one for iOS ≤ 26;
      • featured actions: the template's, wired to our counted redirect.

Mounts at:
    GET    /api/owner/card/pass-designer     → what is imported
    PUT    /api/owner/card/pass-designer     → owner, import a template
    DELETE /api/owner/card/pass-designer     → owner, back to the FidClic design
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_role, TokenData

router = APIRouter(tags=["pass-designer"])
_db = None

STYLES = ("posterGeneric", "generic", "storeCard", "coupon", "eventTicket", "boardingPass")
GROUPS = ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields", "footerFields", "backFields")
IMAGE_RE = re.compile(r"^(background|primaryLogo|logo|icon|thumbnail|strip|footer)(@[23]x)?\.png$")
MAX_PASS_JSON = 200_000
MAX_IMAGE = 3_500_000          # a data: URL
NEW_BARCODES = {"PKBarcodeFormatEAN13", "PKBarcodeFormatCode39", "PKBarcodeFormatCodabar", "PKBarcodeFormatITF"}

# A field whose key names a customer value is filled per customer — the way
# Pass Builder's setValue(forKey:) does it in Apple's session.
KEY_MAP = {
    "name": {"CUST_NAME", "CUSTOMER_NAME", "MEMBER_NAME", "NAME", "NOM", "CLIENT", "CLIENT_NAME"},
    "first_name": {"FIRST_NAME", "PRENOM", "CUST_FIRST_NAME"},
    "card": {"CUST_ID", "CUSTOMER_ID", "MEMBER_ID", "CARD_ID", "CARD_NUMBER", "ID", "NUMERO", "NUMERO_CARTE"},
    "points": {"POINTS", "SOLDE", "BALANCE", "CUST_POINTS"},
    "stamps": {"STAMPS", "TAMPONS", "CUST_STAMPS"},
    "tier": {"TIER", "STATUS", "STATUT", "LEVEL", "NIVEAU"},
    "reward": {"REWARD", "RECOMPENSE", "NEXT_REWARD"},
    "offer": {"OFFER", "OFFRE", "CURRENT_OFFER"},
    "visits": {"VISITS", "VISITES"},
    "member_since": {"MEMBER_SINCE", "MEMBRE_DEPUIS", "JOINED"},
}
# {placeholder} → value, French and English spellings
PLACEHOLDERS = {
    "prenom": "first_name", "first_name": "first_name", "nom": "name", "name": "name",
    "carte": "card", "card": "card", "points": "points", "tampons": "stamps", "stamps": "stamps",
    "statut": "tier", "tier": "tier", "recompense": "reward", "reward": "reward",
    "offre": "offer", "offer": "offer", "visites": "visits", "visits": "visits",
    "membre_depuis": "member_since", "member_since": "member_since", "commerce": "shop", "shop": "shop",
}
# values that change, and so notify the customer when they do
NOTIFY = {"points": "Vous avez maintenant %@ points", "stamps": "Tampons : %@", "offer": "%@", "tier": "Nouveau statut : %@"}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# The template
# ---------------------------------------------------------------------------
def _strip_ids(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _strip_ids(x) for k, x in v.items() if k != "_id"}
    if isinstance(v, list):
        return [_strip_ids(x) for x in v]
    return v


def clean_template(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Pass Designer's pass.json, made a valid pass skeleton: no `_id`s, no
    empty rows, every field keyed (Wallet rejects an empty or repeated key)."""
    t = _strip_ids(raw)
    seen: set = set()
    for style in STYLES:
        block = t.get(style)
        if not isinstance(block, dict):
            continue
        for g in GROUPS:
            rows = []
            for i, f in enumerate(block.get(g) or []):
                if not isinstance(f, dict):
                    continue
                if str(f.get("value") or "").strip() == "" and not str(f.get("label") or "").strip():
                    continue
                key = re.sub(r"[^A-Za-z0-9_]", "_", str(f.get("key") or "").strip()) or f"{g[:-6]}{i + 1}"
                while key in seen:
                    key += "_"
                seen.add(key)
                rows.append({**f, "key": key})
            if rows:
                block[g] = rows
            else:
                block.pop(g, None)
    return t


def style_of(t: Dict[str, Any]) -> Optional[str]:
    return next((s for s in STYLES if isinstance(t.get(s), dict)), None)


def load(tid: Optional[str]) -> Optional[Dict[str, Any]]:
    """The imported template, if this business uses one."""
    if not tid or _db is None:
        return None
    doc = (_db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "pass_designer": 1}) or {}).get("pass_designer")
    return doc if doc and doc.get("active", True) is not False and isinstance(doc.get("pass"), dict) else None


# ---------------------------------------------------------------------------
# Filling it for one customer
# ---------------------------------------------------------------------------
def _kind_of_key(key: str) -> Optional[str]:
    k = (key or "").upper()
    return next((kind for kind, keys in KEY_MAP.items() if k in keys), None)


def _fill(text: Any, values: Dict[str, Any]) -> Any:
    if not isinstance(text, str) or "{" not in text:
        return text
    def rep(m):
        kind = PLACEHOLDERS.get(m.group(1).strip().lower())
        return str(values.get(kind, m.group(0))) if kind else m.group(0)
    return re.sub(r"\{([^{}]{1,30})\}", rep, text)


def _fields(rows: List[Dict[str, Any]], values: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for f in rows or []:
        f = dict(f)
        kind = _kind_of_key(f.get("key"))
        if kind:
            f["value"] = values.get(kind, f.get("value"))
            if kind in NOTIFY and "changeMessage" not in f:
                f["changeMessage"] = NOTIFY[kind]
        else:
            f["value"] = _fill(f.get("value"), values)
        if "label" in f:
            f["label"] = _fill(f["label"], values)
        out.append(f)
    return out


def apply(pj: Dict[str, Any], tpl: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    """FidClic's pass `pj` (identity, web service, barcode, back, relevance…)
    dressed in the template's design."""
    t = clean_template(tpl["pass"])
    style = style_of(t)
    if not style:
        return pj
    ours_style = next((s for s in STYLES if s in pj), None)
    our_back = (pj.get(ours_style) or {}).get("backFields", []) if ours_style else []
    out = {k: v for k, v in pj.items() if k not in STYLES and k != "logoText"}

    block = {g: _fields(rows, values) for g, rows in t[style].items() if g in GROUPS}
    for k, v in t[style].items():                       # transitType and other style keys
        if k not in GROUPS:
            block[k] = v
    keys = {f["key"] for g in GROUPS for f in block.get(g, [])}
    block["backFields"] = block.get("backFields", []) + [f for f in our_back if f["key"] not in keys]
    out[style] = block

    # iOS 26 and earlier: the poster's own fallback, or one made from it
    if style == "posterGeneric":
        if isinstance(t.get("generic"), dict):
            out["generic"] = {g: _fields(rows, values) for g, rows in t["generic"].items() if g in GROUPS}
            out["generic"]["backFields"] = block["backFields"]
        else:
            prim = block.get("primaryFields", [])
            out["generic"] = {"headerFields": block.get("headerFields", [])[:1], "primaryFields": prim[:1],
                              "secondaryFields": (prim[1:] + block.get("footerFields", []))[:4],
                              "backFields": block["backFields"]}

    for k in ("backgroundColor", "foregroundColor", "labelColor", "footerBackgroundColor",
              "suppressHeaderDarkening", "useAutomaticColors", "logoText", "suppressStripShine"):
        if k in t and t[k] not in (None, ""):
            out[k] = t[k]

    # the template's barcode formats, carrying OUR message; Apple's advice for
    # the iOS 27-only formats: keep a classic one after them for older iPhones
    ours = (pj.get("barcodes") or [{}])[0]
    tb = [b for b in t.get("barcodes") or [] if isinstance(b, dict) and b.get("format")]
    if tb:
        bars = [{"format": b["format"], "message": ours.get("message", ""), "messageEncoding": "iso-8859-1",
                 **({"altText": ours["altText"]} if ours.get("altText") else {})} for b in tb]
        if all(b["format"] in NEW_BARCODES for b in bars):
            bars.append({**bars[0], "format": "PKBarcodeFormatQR"})
        out["barcodes"] = bars
    return out


def actions_of(t: Dict[str, Any]) -> List[Dict[str, str]]:
    """The template's featured actions, as FidClic's settings store them."""
    out = []
    for a in t.get("featuredActions") or []:
        url = (a.get("url") or "").strip()
        out.append({"type": a.get("type"), **({"url": url} if re.match(r"^https://[^/]+\.[^/]+", url) else {})})
    return out


def images(tpl: Dict[str, Any]) -> Dict[str, bytes]:
    """The template's images as pass files (PNG bytes by name)."""
    out: Dict[str, bytes] = {}
    for name, url in _image_items(tpl):
        if IMAGE_RE.match(name) and isinstance(url, str) and url.startswith("data:image/"):
            try:
                out[name] = base64.b64decode(url.split(",", 1)[1])
            except Exception:
                continue
    return out


def _image_items(tpl: Dict[str, Any]):
    """Images are stored as [{name, data}] — a file name has a dot, and a
    Mongo key may not."""
    for row in tpl.get("images") or []:
        if isinstance(row, dict):
            yield row.get("name") or "", row.get("data")


def best(imgs: Dict[str, bytes], base: str) -> Optional[bytes]:
    return imgs.get(f"{base}@3x.png") or imgs.get(f"{base}@2x.png") or imgs.get(f"{base}.png")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
class TemplateIn(BaseModel):
    name: Optional[str] = None
    pass_json: Optional[str] = None
    images: Dict[str, str] = {}
    # or the template compressed in Finder (right click › Compress), base64:
    # a .pkpasstemplate is a macOS package, which a browser cannot upload
    zip: Optional[str] = None


MAX_ZIP = 12_000_000


def _from_zip(b64: str):
    """pass.json + images out of a zipped .pkpasstemplate."""
    import zipfile
    try:
        raw = base64.b64decode(b64.split(",", 1)[-1])
    except Exception:
        raise HTTPException(status_code=400, detail="Fichier .zip illisible.")
    if len(raw) > MAX_ZIP:
        raise HTTPException(status_code=400, detail="Le modèle compressé dépasse 12 Mo.")
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Ce n'est pas un fichier .zip valide.")
    names = [n for n in z.namelist() if not n.startswith("__MACOSX/") and not n.endswith("/")]
    pj = next((n for n in names if n.rsplit("/", 1)[-1] == "pass.json"), None)
    if not pj:
        raise HTTPException(status_code=400, detail="Le .zip ne contient pas de pass.json (modèle Pass Designer).")
    imgs = {n.rsplit("/", 1)[-1]: "data:image/png;base64," + base64.b64encode(z.read(n)).decode()
            for n in names if IMAGE_RE.match(n.rsplit("/", 1)[-1])}
    folder = pj.rsplit("/", 1)[0] if "/" in pj else ""
    name = folder.rsplit("/", 1)[-1].replace(".pkpasstemplate", "") if folder else None
    return z.read(pj).decode("utf-8", "replace"), imgs, name


@router.get("/api/owner/card/pass-designer")
def get_template(token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    t = load(token_data.tenant_id)
    if not t:
        return {"active": False}
    return {"active": True, "name": t.get("name"), "style": style_of(t["pass"]),
            "imported_at": t.get("imported_at").isoformat() if isinstance(t.get("imported_at"), datetime) else t.get("imported_at"),
            "images": sorted(n for n, _ in _image_items(t))}


@router.put("/api/owner/card/pass-designer")
def put_template(body: TemplateIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    if body.zip:
        pass_json, zimgs, zname = _from_zip(body.zip)
        body = TemplateIn(name=body.name or zname, pass_json=pass_json, images=zimgs)
    if not body.pass_json:
        raise HTTPException(status_code=400, detail="Choisissez le modèle (.pkpasstemplate ou .zip).")
    if len(body.pass_json) > MAX_PASS_JSON:
        raise HTTPException(status_code=400, detail="pass.json est trop volumineux.")
    try:
        raw = json.loads(body.pass_json)
    except ValueError:
        raise HTTPException(status_code=400, detail="pass.json illisible : choisissez le modèle enregistré par Pass Designer.")
    if not isinstance(raw, dict) or not style_of(raw):
        raise HTTPException(status_code=400, detail="Ce modèle n'a pas de style de carte (poster, générique, store card…).")
    imgs: List[Dict[str, str]] = []
    for name, url in (body.images or {}).items():
        name = name.rsplit("/", 1)[-1]
        if not IMAGE_RE.match(name):
            continue
        if not isinstance(url, str) or not url.startswith("data:image/png") or len(url) > MAX_IMAGE:
            raise HTTPException(status_code=400, detail=f"Image {name} invalide ou trop lourde (max 2,5 Mo).")
        imgs.append({"name": name, "data": url})
    tid = token_data.tenant_id
    doc = {"active": True, "name": (body.name or "Modèle Pass Designer")[:80], "pass": raw, "images": imgs,
           "imported_at": _now(), "imported_by": token_data.email}
    sets: Dict[str, Any] = {"tenant_id": tid, "pass_designer": doc, "poster_style": True, "updated_at": _now()}
    from features.wallet_passes import clean_featured
    acts = clean_featured(actions_of(raw))
    if acts or raw.get("featuredActions") is not None:
        sets["featured_actions"] = acts
    _db.card_templates.update_one({"tenant_id": tid}, {"$set": sets}, upsert=True)
    try:
        from features.wallet_passes import notify_tenant
        notify_tenant(tid)                     # cards already in Wallet take the new design
    except Exception:
        pass
    return get_template(token_data=token_data)


@router.delete("/api/owner/card/pass-designer")
def delete_template(token_data: TokenData = Depends(require_role(["business_owner"]))):
    tid = token_data.tenant_id
    _db.card_templates.update_one({"tenant_id": tid}, {"$unset": {"pass_designer": ""}, "$set": {"updated_at": _now()}})
    try:
        from features.wallet_passes import notify_tenant
        notify_tenant(tid)
    except Exception:
        pass
    return {"active": False}
