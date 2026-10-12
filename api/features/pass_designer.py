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

THE EDITOR (Carte de fidélité › Design Apple Wallet, user 2026-10-07)
    Builds the very same template in the browser — style, fallback style for
    iOS 26 and earlier, colours, images, barcode + fallback, fields with the
    customer's own data as {placeholders} — so an imported template and an
    edited one go through one engine, and the preview is this engine's output.

Mounts at:
    GET    /api/owner/card/pass-designer          → what is in use (?full=1: everything, for the editor)
    GET    /api/owner/card/pass-designer/starter  → the current FidClic card as a template to edit
    PUT    /api/owner/card/pass-designer          → owner, save an edited design or import a template
    DELETE /api/owner/card/pass-designer          → owner, back to the FidClic design
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
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
# iOS 26 and earlier: FidClic's own card (strip, logo, shop colour — user,
# 2026-10-07: « pichla version toh rakho »), or one made from the poster
FALLBACKS = ("fidclic", "generic", "storeCard", "coupon", "eventTicket")
COLOR_KEYS = ("backgroundColor", "foregroundColor", "labelColor", "stripColor", "footerBackgroundColor")
FLAG_KEYS = ("suppressHeaderDarkening", "useAutomaticColors", "suppressStripShine")
# Apple: textAlignment is invalid on primary and back fields
FIELD_KEYS = ("key", "label", "value", "changeMessage", "textAlignment", "dateStyle", "timeStyle", "isRelative",
              "ignoresTimeZone", "numberStyle", "currencyCode", "dataDetectorTypes", "attributedValue", "row")
# the largest each image needs to be (@3x px); bigger uploads are scaled down
IMAGE_MAX = {"background": (1035, 1515), "strip": (1125, 432), "thumbnail": (270, 270), "logo": (480, 150),
             "primaryLogo": (480, 150), "icon": (87, 87), "footer": (858, 45)}

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
    "jauge": "meter", "meter": "meter",
}
# values that change, and so notify the customer when they do. The offer is
# not here: FidClic's own « Offre du moment » on the back already notifies,
# and two changed fields would ring twice.
NOTIFY = {"points": "Vous avez maintenant %@ points", "stamps": "Tampons : %@", "meter": "Tampons : %@",
          "tier": "Nouveau statut : %@"}
_ONLY = re.compile(r"^\s*\{([^{}]{1,30})\}\s*$")

# The owner's preview: a design not saved yet stands in for the saved one
# while one request builds the pass (contextvars: one per request).
_override: ContextVar = ContextVar("pass_designer_override", default=None)


@contextmanager
def preview_design(tid: str, design: Optional[Dict[str, Any]]):
    token = _override.set((tid, design) if design else None)
    try:
        yield
    finally:
        _override.reset(token)


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
                row = {k: v for k, v in f.items() if k in FIELD_KEYS and v not in (None, "")}
                row["key"] = key
                row.setdefault("value", "")
                if g in ("primaryFields", "backFields"):
                    row.pop("textAlignment", None)
                rows.append(row)
            if rows:
                block[g] = rows
            else:
                block.pop(g, None)
    return t


def style_of(t: Dict[str, Any]) -> Optional[str]:
    return next((s for s in STYLES if isinstance(t.get(s), dict)), None)


def load(tid: Optional[str]) -> Optional[Dict[str, Any]]:
    """The imported template, if this business uses one."""
    ov = _override.get()
    if ov and ov[0] == tid:
        return ov[1]
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


# A field whose KEY names a customer value (Pass Designer's CUST_NAME,
# CUST_ID…) used to show that value whatever its text — « SPIRIT OF ECSTACY »
# in the editor, « Marie » on the card (user, 2026-10-12: « fields mein jo
# bhi hai woh directly card mein dikhni chahiye »). Such a text is written as
# the matching {placeholder} once (import, or the editor opening an older
# design), and from then on the text IS the field: what the owner types is
# what the card shows.
KIND_PLACEHOLDER = {"name": "{nom}", "first_name": "{prenom}", "card": "{carte}", "points": "{points}",
                    "stamps": "{tampons}", "tier": "{statut}", "reward": "{recompense}", "offer": "{offre}",
                    "visits": "{visites}", "member_since": "{membre_depuis}"}


def show_keys(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The design with every key-filled field written as its placeholder."""
    t = copy.deepcopy(raw)
    for style in STYLES:
        block = t.get(style)
        if not isinstance(block, dict):
            continue
        for g in GROUPS:
            for f in block.get(g) or []:
                if not isinstance(f, dict):
                    continue
                kind = _kind_of_key(f.get("key"))
                val = f.get("value")
                if kind and not (isinstance(val, str) and _ONLY.match(val)
                                 and PLACEHOLDERS.get(_ONLY.match(val).group(1).strip().lower()) == kind):
                    f["value"] = KIND_PLACEHOLDER[kind]
    return t


def _fields(rows: List[Dict[str, Any]], values: Dict[str, Any], by_key: bool = True) -> List[Dict[str, Any]]:
    """`by_key`: an older design, saved before show_keys — its key-named
    fields still show the customer's value."""
    out = []
    for f in rows or []:
        f = dict(f)
        kind = _kind_of_key(f.get("key")) if by_key else None
        if kind:
            f["value"] = values.get(kind, f.get("value"))
        else:
            only = _ONLY.match(f["value"]) if isinstance(f.get("value"), str) else None
            kind = PLACEHOLDERS.get(only.group(1).strip().lower()) if only else None
            # a lone {points} keeps the number (Wallet formats it), else text
            f["value"] = values.get(kind, f.get("value")) if kind else _fill(f.get("value"), values)
        if kind and f["value"] in (None, ""):
            continue                                    # {offre} with no campaign running: no empty row
        if kind in NOTIFY and "changeMessage" not in f:
            f["changeMessage"] = NOTIFY[kind]
        if "label" in f:
            f["label"] = _fill(f["label"], values)
        out.append(f)
    return out


def _fallback_from(block: Dict[str, Any], style: str) -> Dict[str, Any]:
    """An iOS 26 card made from the poster, as Pass Designer's « Generate
    Compatible Pass » lays it out: the first primary field big, the others
    under it, the footer last."""
    head, prim, foot = block.get("headerFields", [])[:3], block.get("primaryFields", []), block.get("footerFields", [])
    if style in ("storeCard", "coupon"):                # one row under the strip
        return {"headerFields": head, "primaryFields": prim[:1], "secondaryFields": (prim[1:] + foot)[:4],
                "backFields": block.get("backFields", [])}
    return {"headerFields": head, "primaryFields": prim[:1], "secondaryFields": prim[1:5],
            "auxiliaryFields": foot[:4], "backFields": block.get("backFields", [])}


def options_of(tpl: Dict[str, Any]) -> Dict[str, Any]:
    o = dict(tpl.get("options") or {})
    if o.get("fallback") not in FALLBACKS + ("template",):
        # an imported template with its own iOS 26 style keeps it
        own = any(isinstance(tpl.get("pass", {}).get(st), dict) for st in STYLES if st != "posterGeneric")
        o["fallback"] = "template" if own else "fidclic"
    if o.get("alt_text") not in ("card", "none", "custom"):
        o["alt_text"] = "card"
    return o


def apply(pj: Dict[str, Any], tpl: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Any]:
    """FidClic's pass `pj` (identity, web service, barcode, back, relevance…)
    dressed in the template's design."""
    t = clean_template(tpl["pass"])
    opts = options_of(tpl)
    style = style_of(t)
    if not style:
        return pj
    ours_style = next((st for st in STYLES if st in pj), None)
    our_back = (pj.get(ours_style) or {}).get("backFields", []) if ours_style else []
    out = {k: v for k, v in pj.items() if k not in STYLES and k != "logoText"}

    by_key = not tpl.get("literal")
    block = {g: _fields(rows, values, by_key) for g, rows in t[style].items() if g in GROUPS}
    for k, v in t[style].items():                       # transitType and other style keys
        if k not in GROUPS:
            block[k] = v
    keys = {f["key"] for g in GROUPS for f in block.get(g, [])}
    block["backFields"] = block.get("backFields", []) + [f for f in our_back if f["key"] not in keys]
    out[style] = block

    # iOS 26 and earlier
    fb = opts["fallback"]
    if style == "posterGeneric":
        own = next((st for st in STYLES if st != "posterGeneric" and isinstance(t.get(st), dict)), None)
        if fb == "template" and own:
            out[own] = {g: _fields(rows, values, by_key) for g, rows in t[own].items() if g in GROUPS}
            out[own]["backFields"] = block["backFields"]
        elif fb in ("fidclic", "template") and isinstance(pj.get("storeCard"), dict):
            fb = "fidclic"
            out["storeCard"] = {**pj["storeCard"], "backFields": block["backFields"]}
        else:
            fb = fb if fb in FALLBACKS[1:] else "generic"
            out[fb] = _fallback_from(block, fb)

    for k in COLOR_KEYS + FLAG_KEYS:
        if k in t and t[k] not in (None, ""):
            out[k] = t[k]
    # The poster draws over its photo and never shows backgroundColor, so with
    # FidClic's card behind it the card keeps the shop's colour on iOS 26; the
    # text colours stay the design's, which the poster does show.
    if style == "posterGeneric" and fb == "fidclic":
        if pj.get("backgroundColor"):
            out["backgroundColor"] = pj["backgroundColor"]
        out["logoText"] = pj.get("logoText") or values.get("shop") or ""
    # The shop's name is set once, in Identité (user, 2026-10-12: « logo text
    # style se htao, already hai in the identity »): a design's own logoText
    # no longer overrides it.

    # the barcode: the design's format and fallback, carrying OUR message
    from features.wallet_passes import build_barcodes, BARCODE_FORMATS
    tb = [b for b in t.get("barcodes") or [] if isinstance(b, dict) and b.get("format") in BARCODE_FORMATS]
    if tb:
        alt_mode = opts["alt_text"]
        alt_tpl = str(tb[0].get("altText") or "")
        if alt_mode == "none":
            alt = None
        elif alt_mode == "custom":
            alt = _fill(opts.get("alt_custom") or "", values) or None
        else:                       # a template's sample text (« 00001 ») is not the customer's
            alt = _fill(alt_tpl, values) if "{" in alt_tpl else values.get("card")
        fallback = opts.get("barcode_fallback") or (tb[1]["format"] if len(tb) > 1 else None)
        out["barcodes"] = build_barcodes(tb[0]["format"], fallback, values.get("card") or pj.get("serialNumber"), alt)
    return out


def actions_of(t: Dict[str, Any]) -> List[Dict[str, str]]:
    """The template's featured actions, as FidClic's settings store them."""
    out = []
    for a in t.get("featuredActions") or []:
        url = (a.get("url") or "").strip()
        out.append({"type": a.get("type"), "place": a.get("placeIdentifier") or "",
                    **({"phone": url} if url.startswith("tel") else {}),
                    **({"url": url} if re.match(r"^https://[^/]+\.[^/]+", url) else {})})
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
    # file name → data: URL (PNG, JPEG or WebP; made PNG here), or "saved" to
    # keep the image already stored under that name
    images: Dict[str, str] = {}
    # the editor's choices that are not pass.json keys
    options: Optional[Dict[str, Any]] = None
    featured_actions: Optional[List[Dict[str, Any]]] = None
    source: Optional[str] = None             # "editor" | "import"
    # or the template compressed in Finder (right click › Compress), base64:
    # a .pkpasstemplate is a macOS package, which a browser cannot upload
    zip: Optional[str] = None


def _clean_options(o: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    o = o or {}
    from features.wallet_passes import BARCODE_FORMATS
    out: Dict[str, Any] = {}
    if o.get("fallback") in FALLBACKS + ("template",):
        out["fallback"] = o["fallback"]
    if o.get("barcode_fallback") in BARCODE_FORMATS:
        out["barcode_fallback"] = o["barcode_fallback"]
    if o.get("alt_text") in ("card", "none", "custom"):
        out["alt_text"] = o["alt_text"]
    if isinstance(o.get("alt_custom"), str):
        out["alt_custom"] = o["alt_custom"][:60]
    return out


def png_data(name: str, url: str) -> Optional[str]:
    """Any uploaded picture as the PNG Wallet wants, no larger than it needs
    to be for its slot (IMAGE_MAX at @3x)."""
    m = IMAGE_RE.match(name)
    if not m or not isinstance(url, str) or not url.startswith("data:image/"):
        return None
    try:
        raw = base64.b64decode(url.split(",", 1)[1])
    except Exception:
        return None
    try:
        from PIL import Image
    except ImportError:
        return url if url.startswith("data:image/png") else None
    try:
        im = Image.open(io.BytesIO(raw))
        im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") or "transparency" in im.info else im.convert("RGB")
        mw, mh = IMAGE_MAX.get(m.group(1), (1125, 1515))
        k = {"@3x": 1, "@2x": 2 / 3, None: 1 / 3}[m.group(2)]
        im.thumbnail((max(1, int(mw * k)), max(1, int(mh * k))), Image.LANCZOS)
        b = io.BytesIO()
        im.save(b, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()
    except Exception:
        return None


def _images_in(body_images: Dict[str, str], saved: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    have = {row.get("name"): row.get("data") for row in saved or [] if isinstance(row, dict)}
    imgs: List[Dict[str, str]] = []
    for name, url in (body_images or {}).items():
        name = name.rsplit("/", 1)[-1]
        if not IMAGE_RE.match(name):
            continue
        if url == "saved":
            if have.get(name):
                imgs.append({"name": name, "data": have[name]})
            continue
        if not isinstance(url, str) or len(url) > MAX_IMAGE * 3:
            raise HTTPException(status_code=400, detail=f"Image {name} trop lourde.")
        png = png_data(name, url)
        if not png or len(png) > MAX_IMAGE * 2:
            raise HTTPException(status_code=400, detail=f"Image {name} illisible ou trop lourde.")
        imgs.append({"name": name, "data": png})
    return imgs


def design_from_body(tid: str, body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """An unsaved design sent by the editor, as load() would return it (for
    the preview). Images marked "saved" come from the stored one."""
    raw = body.get("pass")
    if not isinstance(raw, dict) or not style_of(raw):
        return None
    stored = (_db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "pass_designer": 1}) or {}).get("pass_designer") or {}
    try:
        imgs = _images_in(body.get("images") or {}, stored.get("images") or [])
    except HTTPException:
        imgs = []
    return {"active": True, "name": "aperçu", "pass": raw, "images": imgs, "options": _clean_options(body.get("options")),
            "literal": True}


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
def get_template(full: bool = False,
                 token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    t = load(token_data.tenant_id)
    if not t:
        return {"active": False}
    out = {"active": True, "name": t.get("name"), "style": style_of(t["pass"]), "source": t.get("source") or "import",
           "imported_at": t.get("imported_at").isoformat() if isinstance(t.get("imported_at"), datetime) else t.get("imported_at"),
           "images": sorted(n for n, _ in _image_items(t))}
    if full:                                   # the editor opens it
        # an older design opens with its key-filled fields as placeholders,
        # so the editor shows what the card shows
        out.update({"pass": _strip_ids(t["pass"] if t.get("literal") else show_keys(t["pass"])), "options": options_of(t),
                    "image_data": {n: d for n, d in _image_items(t)}})
    return out


@router.get("/api/owner/card/pass-designer/starter")
def get_starter(token_data: TokenData = Depends(require_role(["business_owner", "administrateur", "manager"]))):
    """The card as FidClic draws it today, as a design the owner can edit:
    a poster with the customer's name and progress, the offer when one runs,
    FidClic's own card for iOS 26 and earlier."""
    import server as core
    from features import wallet_passes as WP
    tid = token_data.tenant_id
    sample = {"id": "starter", "tenant_id": tid, "barcode_id": "FT-EXEMPLE1", "name": "Marie Dupont",
              "visits": 3, "points": 30, "tier": "bronze"}
    payload = core._serialize_card_payload(sample)
    card, tenant = payload["card"], payload["tenant"]
    colors = WP.derive_colors(card)
    org = card.get("card_name") or tenant.get("name") or "FidClic"
    header = ([{"key": "POINTS", "label": (card.get("points_label") or "Points").upper(), "value": "{points}"}]
              if card.get("show_points") is not False else
              [{"key": "STATUT", "label": "STATUT", "value": "{statut}"}])
    # the tampons as a jauge under the QR, the count in its label (user, 2026-10-11)
    # (key JAUGE: a STAMPS key would be filled with « 3 / 10 », see KEY_MAP)
    progress = ({"key": "JAUGE", "label": (card.get("stamps_label") or "Tampons").upper() + " · {tampons}",
                 "value": "{jauge}"}
                if card.get("show_stamps") is not False else
                {"key": "REWARD", "label": "RÉCOMPENSE", "value": "{recompense}"})
    raw = {
        "posterGeneric": {
            "headerFields": header,
            "primaryFields": [{"key": "member", "label": (card.get("greeting_label") or "Membre").upper(), "value": "{prenom}"},
                              progress],
            # the offer of the campaign running, on the front (user, 2026-10-07)
            "footerFields": [{"key": "shop", "value": org}, {"key": "offer_front", "label": "OFFRE", "value": "{offre}"}],
            "backFields": [],
        },
        **{k: v for k, v in colors.items() if k in COLOR_KEYS},
        "barcodes": [{"format": {"barcode": "PKBarcodeFormatCode128", "pdf417": "PKBarcodeFormatPDF417",
                                 "aztec": "PKBarcodeFormatAztec"}.get(card.get("code_type"),
                                 card.get("code_type") if card.get("code_type") in WP.BARCODE_FORMATS
                                 else "PKBarcodeFormatQR")}],
    }
    images: Dict[str, str] = {}
    try:
        photo = None
        if card.get("poster_image_url"):
            photo = WP._fetch_image(card.get("poster_image_url"))
        bg = WP.compose_poster(photo or WP._hero_raw(card), colors)
        if bg:
            images["background@3x.png"] = "data:image/png;base64," + base64.b64encode(bg).decode()
        logo = WP._fetch_image(card.get("logo_url"))
        if logo:
            for name, box in (("primaryLogo@3x.png", (160, 50)), ("logo@3x.png", (160, 50))):
                png = WP._png_variants(logo, box, tight=True).get("@3x")
                if png:
                    images[name] = "data:image/png;base64," + base64.b64encode(png).decode()
    except Exception:
        pass
    return {"name": f"Design {org}"[:80], "pass": raw, "image_data": images,
            "options": {"fallback": "fidclic", "alt_text": "card" if card.get("show_card_number") is not False else "none"}}


@router.put("/api/owner/card/pass-designer")
def put_template(body: TemplateIn, token_data: TokenData = Depends(require_role(["business_owner"]))):
    if body.zip:
        pass_json, zimgs, zname = _from_zip(body.zip)
        body = TemplateIn(name=body.name or zname, pass_json=pass_json, images=zimgs, source="import")
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
    tid = token_data.tenant_id
    stored = (_db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "pass_designer": 1}) or {}).get("pass_designer") or {}
    imgs = _images_in(body.images or {}, stored.get("images") or [])
    # the editor sends what it shows; an import is written out first
    raw = raw if body.source == "editor" else show_keys(raw)
    raw.pop("logoText", None)                    # the name is Identité's
    doc = {"active": True, "name": (body.name or "Modèle Pass Designer")[:80], "pass": raw, "images": imgs,
           "options": _clean_options(body.options), "source": "editor" if body.source == "editor" else "import",
           "imported_at": _now(), "imported_by": token_data.email, "literal": True}
    sets: Dict[str, Any] = {"tenant_id": tid, "pass_designer": doc, "poster_style": True, "updated_at": _now()}
    from features.wallet_passes import clean_featured
    if body.featured_actions is not None:            # the editor's buttons
        sets["featured_actions"] = clean_featured(body.featured_actions, keep_empty=True)
    else:                                            # an imported template's
        acts = clean_featured(actions_of(raw), keep_empty=True)
        if acts or raw.get("featuredActions") is not None:
            sets["featured_actions"] = acts
    # An imported template's photo and logo become the card's (« Identité »,
    # the one place they are set — user, 2026-10-12), so the owner sees and
    # frames them there. A logo the card already has is kept.
    if doc["source"] == "import":
        have = {row["name"]: row["data"] for row in imgs if isinstance(row, dict)}
        bg = next((have[n] for n in ("background@3x.png", "background@2x.png", "background.png") if have.get(n)), None)
        if bg and style_of(raw) == "posterGeneric" and len(bg) <= 3_500_000:
            sets["poster_image_url"] = bg
        cur = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1}) or {}
        lg = next((have[n] for n in ("primaryLogo@3x.png", "primaryLogo@2x.png", "logo@3x.png", "logo@2x.png",
                                     "primaryLogo.png", "logo.png") if have.get(n)), None)
        if lg and not cur.get("logo_url"):
            sets["logo_url"] = lg
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
