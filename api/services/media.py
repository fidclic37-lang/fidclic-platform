"""
Images out of the documents that every page reads (2026-10-13).

WHY
    Measured on production with Server-Timing: the signup page of a shop
    with photos spent 1 547 ms of 1 554 ms in MongoDB, for 4 calls. The card
    (card_templates) held every picture as a data: URL — logo, banner, poster,
    « Ajuster » frame, Pass Designer images, each establishment's copy — so a
    read of one field still made the free cluster load megabytes. The card is
    read by nearly every page, pass, scan and preview. A campaign's photo was
    copied into the campaign and into each recipient's notification.

WHAT
    A picture is stored once in `media` (its id is a hash of its bytes, so
    the same picture is never stored twice) and the document keeps a short
    link: « /api/media/<id> ». The browser loads it like any image and caches
    it for good (the link changes when the picture does); the server reads
    it back with `resolve()`.

    The documents of MEDIA_COLLECTIONS are written through MediaCollection:
    a data:image value written there becomes a link on the way in — every
    save of a card, a campaign or a notification, whatever page made it.
    `migrate()` moves the pictures already stored.
"""
from __future__ import annotations

import base64
import hashlib
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple

PREFIX = "/api/media/"
MIN_INLINE = 1024            # a tiny icon may stay inline; anything bigger moves
MEDIA_COLLECTIONS = ("card_templates", "campaigns", "push_notifications", "notifications", "signup_images")
_DATA = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+)(;[^,]*)?,(.*)$", re.S)
_ID = re.compile(r"^[0-9a-f]{32}$")
_db = None


def init(db) -> None:
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_ref(v: Any) -> bool:
    """A link this module made (relative, or absolute on any of our hosts)."""
    return isinstance(v, str) and (v.startswith(PREFIX) or ("://" in v and PREFIX in v.split("://", 1)[1]))


def is_image_value(v: Any) -> bool:
    """What an image field may hold: a data:image URL, an https link or one of ours."""
    return isinstance(v, str) and (v.startswith("data:image/") or v.startswith("https://") or is_ref(v))


def _decode(data_url: str) -> Optional[Tuple[str, bytes]]:
    m = _DATA.match(data_url or "")
    if not m:
        return None
    mime, params, payload = m.group(1), m.group(2) or "", m.group(3)
    try:
        if ";base64" in params:
            raw = base64.b64decode(payload, validate=False)
        else:
            from urllib.parse import unquote_to_bytes
            raw = unquote_to_bytes(payload)
    except Exception:
        return None
    return mime.lower(), raw


def put(data_url: str) -> str:
    """Store a data:image URL once; returns its link (or the value unchanged
    when it is not one, or too small to be worth a link)."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or len(data_url) < MIN_INLINE or _db is None:
        return data_url
    dec = _decode(data_url)
    if not dec:
        return data_url
    mime, raw = dec
    mid = hashlib.sha256(mime.encode() + b"\0" + raw).hexdigest()[:32]
    real = _raw(_db["media"])
    if not real.find_one({"_id": mid}, {"_id": 1}):
        try:
            from bson.binary import Binary
            blob: Any = Binary(raw)
        except Exception:                      # mongomock without bson: keep base64
            blob = base64.b64encode(raw).decode()
        try:
            real.insert_one({"_id": mid, "mime": mime, "data": blob, "size": len(raw), "at": _now()})
        except Exception:
            pass                               # stored meanwhile by another request
    return PREFIX + mid


# A picture's id is the hash of its bytes: once read, it never changes, so the
# server keeps it in memory (2026-10-13: a card preview with a Pass Designer
# design read the same pictures 29 times — 14 MB from the free cluster per
# preview, over Vercel's 30 s: « Aperçu indisponible »).
_MEM: "OrderedDict[str, Tuple[str, bytes]]" = OrderedDict()
_MEM_MAX = 160 * 1024 * 1024
_mem_size = 0


def _remember(mid: str, got: Tuple[str, bytes]) -> None:
    global _mem_size
    if mid in _MEM or len(got[1]) > _MEM_MAX // 4:
        return
    _MEM[mid] = got
    _mem_size += len(got[1])
    while _mem_size > _MEM_MAX and _MEM:
        _, old = _MEM.popitem(last=False)
        _mem_size -= len(old[1])


def _from_cdn(mid: str) -> Optional[Tuple[str, bytes]]:
    """On Vercel: the picture from the edge's copy of « /api/media/<id> »
    (cached a year, ~60 ms) rather than from the free cluster, which hands
    megabytes back in seconds (2026-10-13, « Aperçu indisponible »)."""
    import os
    if not os.environ.get("VERCEL"):
        return None
    try:
        import urllib.request
        from features.wallet_passes import _site_url
        site = (_site_url() or "").rstrip("/")
        if not site.startswith("https://"):
            return None
        req = urllib.request.Request(f"{site}{PREFIX}{mid}", headers={"User-Agent": "FidClic-media/1"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
            mime = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0]
        return (mime, raw) if raw else None
    except Exception:
        return None


def get(mid: str, cdn: bool = True) -> Optional[Tuple[str, bytes]]:
    """`cdn=False`: the database only (the « /api/media » route itself)."""
    if _db is None or not _ID.match(mid or ""):
        return None
    hit = _MEM.get(mid)
    if hit is not None:
        _MEM.move_to_end(mid)
        return hit
    if cdn:
        got = _from_cdn(mid)
        if got:
            _remember(mid, got)
            return got
    doc = _raw(_db["media"]).find_one({"_id": mid})
    if not doc:
        return None
    data = doc.get("data")
    if isinstance(data, str):
        data = base64.b64decode(data)
    got = (doc.get("mime") or "application/octet-stream", bytes(data))
    _remember(mid, got)
    return got


def resolve(src: Any) -> Optional[bytes]:
    """The bytes behind one of our links, without going through HTTP."""
    if not is_ref(src):
        return None
    mid = src.split(PREFIX, 1)[1].split("?", 1)[0].split(".", 1)[0]
    got = get(mid)
    return got[1] if got else None


def to_data_url(src: Any) -> Any:
    """For the rare reader that needs the picture inline (an e-mail)."""
    if not is_ref(src):
        return src
    mid = src.split(PREFIX, 1)[1].split("?", 1)[0]
    got = get(mid)
    return f"data:{got[0]};base64,{base64.b64encode(got[1]).decode()}" if got else src


def absolute(src: Any, site: str) -> Any:
    """Our link as a full URL, for what leaves the app (a push, an e-mail)."""
    if isinstance(src, str) and src.startswith(PREFIX):
        return site.rstrip("/") + src
    return src


# ---------------------------------------------------------------------------
# moving pictures out of what is written
# ---------------------------------------------------------------------------
def externalize(v: Any) -> Any:
    """Every big data:image value inside `v` → a link (dicts and lists walked)."""
    if isinstance(v, str):
        return put(v) if v.startswith("data:image/") and len(v) >= MIN_INLINE else v
    if isinstance(v, dict):
        return {k: externalize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [externalize(x) for x in v]
    return v


_VALUE_OPS = ("$set", "$setOnInsert", "$push", "$addToSet")


def externalize_update(update: Any) -> Any:
    if isinstance(update, dict) and any(str(k).startswith("$") for k in update):
        return {op: (externalize(body) if op in _VALUE_OPS else body) for op, body in update.items()}
    if isinstance(update, list):                 # an aggregation-pipeline update: left alone
        return update
    return externalize(update)                   # a replacement document


class MediaCollection:
    """A collection whose writes move pictures into `media` first."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def insert_one(self, doc, *a, **k):
        return self._real.insert_one(externalize(_with_id(doc)), *a, **k)

    def insert_many(self, docs, *a, **k):
        return self._real.insert_many([externalize(_with_id(d)) for d in list(docs)], *a, **k)

    def update_one(self, flt, update, *a, **k):
        return self._real.update_one(flt, externalize_update(update), *a, **k)

    def update_many(self, flt, update, *a, **k):
        return self._real.update_many(flt, externalize_update(update), *a, **k)

    def replace_one(self, flt, doc, *a, **k):
        return self._real.replace_one(flt, externalize(doc), *a, **k)

    def find_one_and_update(self, flt, update, *a, **k):
        return self._real.find_one_and_update(flt, externalize_update(update), *a, **k)


def _with_id(doc: Any) -> Any:
    """pymongo gives an inserted dict its `_id`; the copy written here is not
    the caller's dict, so the id is made first and lands on both."""
    if isinstance(doc, dict) and "_id" not in doc:
        try:
            from bson import ObjectId
            doc["_id"] = ObjectId()
        except Exception:
            pass
    return doc


def _raw(coll):
    """Under any wrapper (StoreCardTemplates, MediaCollection), the pymongo collection."""
    seen = 0
    while hasattr(coll, "_real") and seen < 5:
        coll = coll._real
        seen += 1
    return coll


def install(db) -> None:
    """db.<name> / db[<name>] for MEDIA_COLLECTIONS → writes through MediaCollection.
    Runs after store_cards._install, around whatever it returns."""
    init(db)
    cls = type(db)
    if getattr(cls, "_fidclic_media", False):
        return
    prev_getitem = cls.__getitem__

    def getitem(self, name):
        coll = prev_getitem(self, name)
        if name not in MEDIA_COLLECTIONS:
            return coll
        inner = getattr(coll, "_real", None)
        if inner is not None and type(coll).__name__ == "StoreCardTemplates":
            if not isinstance(inner, MediaCollection):
                coll._real = MediaCollection(inner)
            return coll
        return MediaCollection(coll)

    def getattr_(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getitem(self, name)
    cls.__getitem__ = getitem
    cls.__getattr__ = getattr_
    cls._fidclic_media = True


# ---------------------------------------------------------------------------
# moving the pictures already stored
# ---------------------------------------------------------------------------
def _paths(v: Any, base: str = "") -> Iterable[Tuple[str, str]]:
    """(dotted path, value) of every big data:image string inside a document."""
    if isinstance(v, str):
        if v.startswith("data:image/") and len(v) >= MIN_INLINE:
            yield base, v
    elif isinstance(v, dict):
        for k, x in v.items():
            if k == "_id":
                continue
            yield from _paths(x, f"{base}.{k}" if base else str(k))
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _paths(x, f"{base}.{i}")


def migrate(collections: Iterable[str] = MEDIA_COLLECTIONS, limit: Optional[int] = None) -> Dict[str, int]:
    """Moves stored data:image values into `media`, field by field ($set of
    the dotted path, so nothing else of the document is rewritten). Safe to
    run again; returns how many pictures moved per collection."""
    out: Dict[str, int] = {}
    if _db is None:
        return out
    for name in collections:
        real = _raw(_db[name])
        moved = 0
        q: Dict[str, Any] = {}
        if name != "card_templates":           # big, many: only the documents with an inline picture
            q = {"$or": [{f: {"$regex": "^data:image/"}} for f in ("image_url", "image", "data")]}
        for doc in real.find(q):
            sets = {path: put(val) for path, val in _paths(doc)}
            sets = {p: v for p, v in sets.items() if is_ref(v)}
            if sets:
                real.update_one({"_id": doc["_id"]}, {"$set": sets})
                moved += len(sets)
            if limit and moved >= limit:
                break
        out[name] = moved
    return out
