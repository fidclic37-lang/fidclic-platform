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


# A picture bigger than any screen needs (2026-10-13): Royal Trim's pass took
# 30 s on every cold server — one picture of its design came back from the
# free cluster in 15,6 s, and its « /api/media » link could never be kept by
# Vercel's edge (a function answers 4,5 Mo at most). The wallet uses 1125 px
# at most, the editor a little more: pictures are kept at 2 400 px on the long
# side, a photo as JPEG (q 88, its EXIF — the phone's rotation — kept), a
# picture with transparency as PNG. The look on a card does not change.
MAX_SIDE = 2400
SHRINK_ABOVE = 1_500_000          # bytes; smaller pictures are kept exactly as sent


def shrink(mime: str, raw: bytes) -> Tuple[str, bytes]:
    """(mime, bytes) of a lighter copy, or the picture unchanged when it is
    small, not one Pillow reads, animated, or would not get lighter."""
    if len(raw) <= SHRINK_ABOVE:
        return mime, raw
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        if getattr(im, "is_animated", False):
            return mime, raw
        exif = im.info.get("exif")
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        if max(im.size) <= MAX_SIDE and (im.format == "JPEG" or (alpha and im.format == "PNG")):
            return mime, raw                   # already its light form: never compressed twice
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        if alpha:
            im.convert("RGBA").save(out, "PNG", optimize=True)
            new_mime = "image/png"
        else:
            kw = {"exif": exif} if exif else {}
            im.convert("RGB").save(out, "JPEG", quality=88, optimize=True, progressive=True, **kw)
            new_mime = "image/jpeg"
        small = out.getvalue()
        return (new_mime, small) if len(small) < len(raw) else (mime, raw)
    except Exception:
        return mime, raw


# ---------------------------------------------------------------------------
# Vercel Blob (2026-10-13, user: « PREVIEW OF LOYALTY CARD KYUN LOAD N HO RHA »):
# measured on production, the free cluster hands a picture back at ~100 Ko/s
# (409 Ko in 4,2 s) and Vercel empties its edge cache at every deploy — so
# after each merge the card preview waited seconds per picture, and a cold one
# ran out of time. A picture now also lives in the project's Blob store
# (public, Paris, a random name): browsers and the server read it from Blob's
# own CDN, which no deploy empties. The cluster keeps its copy as a fallback.
# Without BLOB_READ_WRITE_TOKEN (tests, local) nothing changes.
# ---------------------------------------------------------------------------
BLOB_API = "https://vercel.com/api/blob"
BLOB_API_VERSION = "12"
BLOB_TIMEOUT_S = 15.0


def _blob_token() -> Optional[str]:
    import os
    return os.environ.get("BLOB_READ_WRITE_TOKEN") or None


def _ext(mime: str) -> str:
    return {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
            "image/svg+xml": "svg"}.get(mime, "bin")


def blob_put(mid: str, mime: str, raw: bytes) -> Optional[str]:
    """Upload one picture to Blob; its public URL, or None (no token, or Blob
    did not answer — the picture is still served from the cluster)."""
    token = _blob_token()
    if not token or not raw:
        return None
    try:
        import httpx
        from urllib.parse import urlencode
        r = httpx.put(f"{BLOB_API}/?{urlencode({'pathname': f'media/{mid}.{_ext(mime)}'})}", content=raw,
                      timeout=BLOB_TIMEOUT_S,
                      headers={"authorization": f"Bearer {token}", "x-api-version": BLOB_API_VERSION,
                               "x-vercel-blob-access": "public", "x-content-type": mime,
                               "x-add-random-suffix": "1", "x-cache-control-max-age": "31536000"})
        if r.status_code >= 300:
            print(f"media: blob upload refused ({r.status_code} {r.text[:200]})")
            return None
        url = (r.json() or {}).get("url")
        return url if isinstance(url, str) and url.startswith("https://") else None
    except Exception as exc:
        print(f"media: blob upload failed ({exc})")
        return None


# ---------------------------------------------------------------------------
# Blob as a shared cache of BUILT images (2026-10-14, after the Hobby plan was
# paused for « Fluid Active CPU »): a poster, a strip, the logos with the name
# are built once and kept at a fixed address, so a new server instance reads
# them from the edge instead of spending CPU building them again.
# ---------------------------------------------------------------------------
def _blob_host() -> Optional[str]:
    """The store's public host, from its token (vercel_blob_rw_<storeId>_<secret>),
    as the official SDK derives it."""
    token = _blob_token() or ""
    parts = token.split("_")
    if len(parts) >= 5 and parts[0] == "vercel" and parts[1] == "blob":
        return f"https://{parts[3].lower()}.public.blob.vercel-storage.com"
    return None


def cache_get(key: str) -> Optional[bytes]:
    """A built image kept under `key` (None: not there, or no Blob)."""
    host = _blob_host()
    if not host or not re.match(r"^[0-9a-f]{20,64}$", key or ""):
        return None
    try:
        import httpx
        r = httpx.get(f"{host}/imgcache/{key}.bin", timeout=6.0, follow_redirects=True)
        _note("imgcache_hit" if r.status_code == 200 else "imgcache_miss")
        return r.content if r.status_code == 200 and r.content else None
    except Exception:
        return None


def cache_put(key: str, raw: bytes) -> bool:
    token = _blob_token()
    if not token or not raw or not re.match(r"^[0-9a-f]{20,64}$", key or "") or len(raw) > 8 * 1024 * 1024:
        return False
    try:
        import httpx
        from urllib.parse import urlencode
        r = httpx.put(f"{BLOB_API}/?{urlencode({'pathname': f'imgcache/{key}.bin'})}", content=raw, timeout=10.0,
                      headers={"authorization": f"Bearer {token}", "x-api-version": BLOB_API_VERSION,
                               "x-vercel-blob-access": "public", "x-content-type": "application/octet-stream",
                               "x-add-random-suffix": "0", "x-allow-overwrite": "1",
                               "x-cache-control-max-age": "31536000"})
        return r.status_code < 300
    except Exception as exc:
        print(f"imgcache: not kept ({exc})")
        return False


def _blob_get(url: str) -> Optional[bytes]:
    try:
        import httpx
        r = httpx.get(url, timeout=BLOB_TIMEOUT_S, follow_redirects=True)
        return r.content if r.status_code == 200 and r.content else None
    except Exception as exc:
        print(f"media: blob read failed ({exc})")
        return None


def blob_url(mid: str) -> Optional[str]:
    """The picture's Blob URL, read without its bytes; uploaded now if it has
    none yet and a token is set (a picture stored before Blob — once)."""
    if _db is None or not _ID.match(mid or ""):
        return None
    meta = _raw(_db["media"]).find_one({"_id": mid}, {"data": 0}) or {}
    if meta.get("blob_url"):
        return meta["blob_url"]
    if not meta or not _blob_token():
        return None
    got = get(mid, cdn=False)
    return (_raw(_db["media"]).find_one({"_id": mid}, {"blob_url": 1}) or {}).get("blob_url") if got else None


def _blob(raw: bytes) -> Any:
    try:
        from bson.binary import Binary
        return Binary(raw)
    except Exception:                          # mongomock without bson: keep base64
        return base64.b64encode(raw).decode()


def put(data_url: str) -> str:
    """Store a data:image URL once; returns its link (or the value unchanged
    when it is not one, or too small to be worth a link)."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or len(data_url) < MIN_INLINE or _db is None:
        return data_url
    dec = _decode(data_url)
    if not dec:
        return data_url
    mime, raw = dec
    # the id is the picture as sent: the same upload is still stored once
    mid = hashlib.sha256(mime.encode() + b"\0" + raw).hexdigest()[:32]
    real = _raw(_db["media"])
    if not real.find_one({"_id": mid}, {"_id": 1}):
        kept_mime, kept = shrink(mime, raw)
        doc = {"_id": mid, "mime": kept_mime, "data": _blob(kept), "size": len(kept), "at": _now()}
        if len(kept) != len(raw):
            doc["original_size"] = len(raw)
        url = blob_put(mid, kept_mime, kept)
        if url:
            doc["blob_url"] = url
        try:
            real.insert_one(doc)
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


import threading
_MEM_LOCK = threading.Lock()                   # prefetch fills it from several threads


def _remember(mid: str, got: Tuple[str, bytes]) -> None:
    global _mem_size
    with _MEM_LOCK:
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
        # one wait, long enough for an edge MISS (its origin reads the cluster):
        # timing out and then reading the cluster again cost twice (2026-10-13)
        with urllib.request.urlopen(req, timeout=12) as resp:
            if resp.status != 200:
                _note("media_cdn_fail", f"http {resp.status}")
                return None
            raw = resp.read()
            mime = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0]
        return (mime, raw) if raw else None
    except Exception as exc:
        _note("media_cdn_fail", f"{type(exc).__name__} {exc}")
        return None


_REF_RE = re.compile(r"/api/media/([0-9a-f]{32})")


def prefetch(*objs: Any) -> int:
    """Every picture these documents link to, fetched AT ONCE (threads) into
    memory before the work starts: a cold preview waited for its pictures one
    after the other — 4 × (edge miss + cluster) went past Vercel's 30 s."""
    import json
    ids = []
    for o in objs:
        try:
            text = o if isinstance(o, str) else json.dumps(o, default=str)
        except Exception:
            continue
        ids += [m for m in _REF_RE.findall(text) if m not in _MEM]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return 0
    if len(ids) == 1:
        get(ids[0])
        return 1
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    ctx = contextvars.copy_context()                   # the request's timing tally follows
    with ThreadPoolExecutor(max_workers=min(8, len(ids))) as pool:
        list(pool.map(lambda m: ctx.copy().run(get, m), ids))
    return len(ids)


def _note(key: str, value: Any = 1) -> None:
    """Where this request's pictures came from, in its Server-Timing header."""
    try:
        from services import server_timing as ST
        ST.note(key, value)
    except Exception:
        pass


def get(mid: str, cdn: bool = True) -> Optional[Tuple[str, bytes]]:
    """`cdn=False`: the database only (the « /api/media » route itself)."""
    if _db is None or not _ID.match(mid or ""):
        return None
    with _MEM_LOCK:
        hit = _MEM.get(mid)
        if hit is not None:
            _MEM.move_to_end(mid)
    if hit is not None:
        _note("media_mem")
        return hit
    # in Blob: its few bytes of metadata from the cluster, the picture from Blob's
    # CDN — before the edge copy, whose origin is this very app (cold after a deploy)
    meta = _raw(_db["media"]).find_one({"_id": mid}, {"data": 0}) if _blob_token() else {}
    if meta is None:
        return None
    if meta.get("blob_url"):
        raw = _blob_get(meta["blob_url"])
        if raw:
            got = (meta.get("mime") or "application/octet-stream", raw)
            _remember(mid, got)
            _note("media_blob")
            return got
    if cdn:
        got = _from_cdn(mid)
        if got:
            _remember(mid, got)
            _note("media_cdn")
            return got
    _note("media_db")
    import time
    t0 = time.perf_counter()
    doc = _raw(_db["media"]).find_one({"_id": mid})
    ms = (time.perf_counter() - t0) * 1000
    if not doc:
        return None
    data = doc.get("data")
    if isinstance(data, str):
        data = base64.b64decode(data)
    got = (doc.get("mime") or "application/octet-stream", bytes(data))
    if ms > 1000:                              # which picture, how big: in Server-Timing
        _note("media_slow", f"{mid[:8]} {len(got[1]) // 1024} Ko {ms:.0f} ms")
    if len(got[1]) > SHRINK_ABOVE and not doc.get("original_size"):
        # stored before pictures were kept light: lighter from now on, same link
        kept_mime, kept = shrink(*got)
        if len(kept) < len(got[1]):
            try:
                _raw(_db["media"]).update_one({"_id": mid}, {"$set": {
                    "mime": kept_mime, "data": _blob(kept), "size": len(kept),
                    "original_size": len(got[1]), "shrunk_at": _now()}})
            except Exception:
                pass
            got = (kept_mime, kept)
    # not in Blob yet: put it there now, so this is the last slow read (once per picture)
    if not doc.get("blob_url") and _blob_token():
        url = blob_put(mid, got[0], got[1])
        if url:
            try:
                _raw(_db["media"]).update_one({"_id": mid}, {"$set": {"blob_url": url}})
            except Exception:
                pass
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
