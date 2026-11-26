"""
« Ma carte en ligne » — the redesigned customer card page (2026-11-25).

Opened from the Wallet pass's back link, it reads GET /api/card/{bc} plus:

    GET /api/card/{barcode_id}/activity?limit=20&before=<ISO>
        The client's own history, newest first: visits, rewards used,
        validated parrainages. Same rule as the card itself
        (server._card_customer): the owner key or a login of that shop.

and three fields this module adds to GET /api/card/{bc} (`enrich`):
    customer.first_name   the first word of the name, as written
    card.socials          [{network, url}] — https links on the network's own
                          domain only, built from card.details
    card.hero_photo_url   the iOS 27 poster's photo (wallet_passes.poster_png's
                          order), a link a plain <img> loads, or null

WHAT THE FEED NEVER SHOWS
    Another client's phone, e-mail, surname, id or amounts; another business
    or another client's rows; a cancelled visit (moved to visits_cancelled);
    a parrainage not validated yet (referrer_pending).

PAGING
    Rows are ordered by (at desc, kind, id) — `id` being the row's Mongo _id,
    so two rows at the very same millisecond still have one order. `next` is
    an opaque cursor (« c1. » + base64 of time | kind | id) of the page's last
    item, passed back as `before`; each source reads at most limit+1 rows
    after it, indexed, with a projection, and the merge keeps `limit`. A plain
    ISO date in `before` still works (everything strictly older). A visit
    whose time was saved as text (old rows) is read by its own small query and
    paged by the same rule — never dropped.

WHOSE EUROS
    A shop login that does not cover a visit's establishment sees the visit
    (kind, time, points, tampons, store name) with `amount: null` (user rule:
    managers see that a client came, not another store's euros). The owner,
    an account covering every store, a super admin and the card's own phone
    see every amount.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["card-page"])
_db = None

DEFAULT_LIMIT, MAX_LIMIT = 20, 100
MAX_INPUT = 300               # a social value longer than this is not a handle nor a profile link
MAX_PHOTO_URL = 2048
CAMPAIGN_PEEK = 5             # the card page's wallet-campaign read: the newest few, never the whole history
TEXT_DATED_CAP = 500          # old visits whose time is text, read per client (a handful in practice)
CURSOR_PREFIX = "c1."
MAX_BEFORE = 160
FIRST_NAME_MAX = 40
NETWORKS = ("instagram", "facebook", "tiktok", "snapchat")
LABELS = {"instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok", "snapchat": "Snapchat"}


def init(db) -> None:
    global _db
    _db = db
    try:   # the feed's three per-client reads (visits already has tenant+customer+time)
        db.rewards_redeemed.create_index([("tenant_id", 1), ("customer_id", 1), ("redeemed_at", -1)])
        db.referral_redemptions.create_index([("tenant_id", 1), ("referrer_customer_id", 1), ("settled_at", -1)])
    except Exception:
        pass
    try:   # the card page's campaign photo: this client's newest wallet campaigns, a few rows
        db.campaigns.create_index([("tenant_id", 1), ("recipient_ids", 1), ("sent_at", -1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# socials
# ---------------------------------------------------------------------------
_A = re.ASCII
_RULES: Dict[str, Dict[str, Any]] = {
    "instagram": {"hosts": {"instagram.com", "www.instagram.com", "m.instagram.com"},
                  "handle": re.compile(r"[A-Za-z0-9._]{1,30}", _A),
                  "reserved": {"p", "reel", "reels", "explore", "stories", "tv", "accounts", "direct", "about"}},
    "facebook": {"hosts": {"facebook.com", "www.facebook.com", "m.facebook.com", "web.facebook.com",
                           "fb.com", "www.fb.com"},
                 "handle": re.compile(r"[A-Za-z0-9.\-]{1,80}", _A),
                 "reserved": {"sharer", "sharer.php", "share", "dialog", "login", "login.php", "plugins",
                              "groups", "events", "watch", "photo", "photo.php", "story.php", "permalink.php",
                              "pages", "hashtag", "l.php"}},
    "tiktok": {"hosts": {"tiktok.com", "www.tiktok.com", "m.tiktok.com"},
               "handle": re.compile(r"[A-Za-z0-9._]{1,24}", _A)},
    "snapchat": {"hosts": {"snapchat.com", "www.snapchat.com"},
                 "handle": re.compile(r"[A-Za-z0-9._\-]{3,15}", _A)},
}
_CANON = {"instagram": "https://www.instagram.com/{}", "facebook": "https://www.facebook.com/{}",
          "tiktok": "https://www.tiktok.com/@{}", "snapchat": "https://www.snapchat.com/add/{}"}
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.I)
_ALL_HOSTS = {h for r in _RULES.values() for h in r["hosts"]}


def _looks_like_url(s: str) -> bool:
    """A scheme (https:, javascript:, data:…), « //… », or a host we know
    (« instagram.com/name »). « royal.trim » stays a handle."""
    return bool(_SCHEME.match(s)) or s.startswith("//") or s.split("/", 1)[0].lower() in _ALL_HOSTS


def _handle_ok(network: str, h: str) -> bool:
    rule = _RULES[network]
    return bool(rule["handle"].fullmatch(h)) and h.lower() not in rule.get("reserved", set())


def _from_url(network: str, s: str) -> Optional[str]:
    if "\\" in s:
        return None                                  # « https://instagram.com\@evil.com »: browsers disagree
    url = s if "://" in s else "https://" + s.lstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or port is not None or parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower()
    if host not in _RULES[network]["hosts"]:
        return None
    segs = [x for x in parts.path.split("/") if x]
    if network == "facebook" and segs[:1] == ["profile.php"]:
        ids = parse_qs(parts.query).get("id") or []
        return (f"https://www.facebook.com/profile.php?id={ids[0]}"
                if ids and re.fullmatch(r"\d{1,20}", ids[0], _A) else None)
    if not segs:
        return None
    if network == "tiktok":
        if not segs[0].startswith("@"):
            return None
        h = segs[0][1:]
    elif network == "snapchat":
        if segs[0] == "add" and len(segs) >= 2:
            h = segs[1]
        elif segs[0].startswith("@"):
            h = segs[0][1:]
        else:
            return None
    else:
        h = segs[0]
        if network == "instagram" and len(segs) > 1:
            return None                              # a post / a reel, not a profile
    return _CANON[network].format(h) if _handle_ok(network, h) else None


def social_url(network: str, value: Any) -> Optional[str]:
    """A handle (« @name », « name ») or a profile link of `network` → its
    canonical https link; None for anything else."""
    if network not in _RULES or not isinstance(value, str):
        return None
    s = value.strip()
    if not s or len(s) > MAX_INPUT or any(c.isspace() for c in s) or not s.isascii():
        return None
    if _looks_like_url(s):
        return _from_url(network, s)
    if "/" in s:
        return None                                  # « evil.com/x »: a link, not ours
    h = s[1:] if s.startswith("@") else s
    return _CANON[network].format(h) if h and _handle_ok(network, h) else None


def socials(details: Any) -> List[Dict[str, str]]:
    """The networks the page shows, always in the same order."""
    if not isinstance(details, dict):
        return []
    out = []
    for n in NETWORKS:
        url = social_url(n, details.get(n))
        if url:
            out.append({"network": n, "url": url})
    return out


# ---------------------------------------------------------------------------
# the store's button — the home's 3rd tile (user, 2026-11-25)
#
# « Prendre rendez-vous » by default; its name and link are set ONLY by the
# FidClic super admin, per établissement (admin_commerces: GET / PUT
# /api/admin/commerces/{tid}/card-cta[/{store_id}]), kept on the tenant as
# card_cta = {store_id: {label, url}} — top level, never inside `branches`
# (the owner rewrites those) nor in the card template (the owner's designer).
# A value stored against the rules (an old row, a hand edit) is never served.
# ---------------------------------------------------------------------------
CTA_DEFAULT_LABEL = "Prendre rendez-vous"
CTA_MAX_LABEL = 28
CTA_MAX_URL = 500
_CTA_BAD_LABEL = re.compile(r"[\x00-\x1f\x7f<>]")
_CTA_HOST = re.compile(r"(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}", _A)
_CTA_URL_CHARS = re.compile(r"[!-~]+", _A)          # printable ASCII, no space


def clean_cta_label(v: Any) -> str:
    """The button's name: plain text, trimmed, 1–28 characters. ValueError
    (French, for the super admin) otherwise."""
    if not isinstance(v, str) or not v.strip():
        raise ValueError("Le nom du bouton est obligatoire.")
    s = v.strip()
    if len(s) > CTA_MAX_LABEL:
        raise ValueError(f"Le nom du bouton fait {CTA_MAX_LABEL} caractères au plus.")
    if _CTA_BAD_LABEL.search(s):
        raise ValueError("Le nom du bouton est du texte simple (pas de < >, pas de retour à la ligne).")
    return s


def clean_cta_url(v: Any) -> Optional[str]:
    """The button's link: None when empty, else an https:// link to a public
    host (« www.planity.com/x » gets its https://). ValueError otherwise —
    no other scheme (javascript:, data:, http:…), no spaces, no login part
    (« https://planity.com@evil.com »), no port, ≤ 500 characters."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("Le lien doit être une adresse https://.")
    s = v.strip()
    if not s:
        return None
    if not _CTA_URL_CHARS.fullmatch(s) or "\\" in s:
        raise ValueError("Le lien ne peut contenir ni espace ni caractère spécial : copiez-le depuis la barre d'adresse.")
    if _SCHEME.match(s) and not s.lower().startswith("https://"):
        raise ValueError("Le lien doit commencer par https://.")
    if s.startswith("//"):
        raise ValueError("Le lien doit commencer par https://.")
    url = s if s.lower().startswith("https://") else "https://" + s
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ValueError("Ce lien n'est pas une adresse valide.")
    host = (parts.hostname or "").lower()
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("Le lien ne peut pas contenir d'identifiant (« …@… »).")
    if port is not None:
        raise ValueError("Le lien ne peut pas contenir de port (« :8080 »).")
    if not _CTA_HOST.fullmatch(host):
        raise ValueError("Ce lien n'est pas une adresse de site valide.")
    out = f"https://{host}{url[len('https://') + len(parts.netloc):]}"
    if len(out) > CTA_MAX_URL:
        raise ValueError(f"Le lien fait {CTA_MAX_URL} caractères au plus.")
    return out


def _main_store_id(t: Dict[str, Any]) -> str:
    """The store a client with no store belongs to: the main branch, the only
    open one, else « main » (a one-shop account)."""
    open_ = [b for b in (t.get("branches") or []) if isinstance(b, dict) and b.get("id") and b.get("status") != "closed"]
    main = next((b["id"] for b in open_ if b.get("is_main") or b["id"] == "main"), None)
    return main or (open_[0]["id"] if open_ else "main")


def cta_for(t: Any, store_id: Optional[str]) -> Dict[str, Any]:
    """{label, url} of `store_id`'s button (no store: the main one), the
    default when not set or when what is stored breaks the rules."""
    default = {"label": CTA_DEFAULT_LABEL, "url": None}
    if not isinstance(t, dict):
        return default
    sid = store_id or _main_store_id(t)
    m = t.get("card_cta")
    row = m.get(sid) if isinstance(m, dict) else None
    if not isinstance(row, dict):
        return default
    try:
        return {"label": clean_cta_label(row.get("label")), "url": clean_cta_url(row.get("url"))}
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# first name
# ---------------------------------------------------------------------------
def first_name(name: Any) -> str:
    if not isinstance(name, str):
        return ""
    words = name.split()
    return words[0][:FIRST_NAME_MAX] if words else ""


# ---------------------------------------------------------------------------
# the poster's photo
# ---------------------------------------------------------------------------
_RASTER_DATA = re.compile(r"^data:image/(png|jpe?g|gif|webp);", re.I)
_UNSAFE_URL = re.compile(r"[\s\"'()<>\\`]")


def _public_image(src: Any) -> Optional[str]:
    """A link a plain <img> / CSS background loads without the owner key."""
    from services import media as _M
    if not isinstance(src, str) or not src:
        return None
    if src.startswith("data:"):
        if not _RASTER_DATA.match(src):
            return None                              # svg or not an image: never handed out
        ref = _M.put(src)                            # a big one gets our public link (stored once)
        return ref if _M.is_ref(ref) or len(ref) < _M.MIN_INLINE else None
    if len(src) > MAX_PHOTO_URL or _UNSAFE_URL.search(src):
        return None
    if src.startswith(_M.PREFIX):
        return src if re.fullmatch(r"/api/media/[0-9a-f]{32}(\.[a-z0-9]{2,5})?", src, _A) else None
    return src if src.lower().startswith("https://") else None


def hero_photo_url(card: Any) -> Optional[str]:
    """wallet_passes.poster_png's order — the live campaign's photo (when it
    is on the Wallet card), the « Ajuster » poster, the banner — but a link,
    and None where the poster would draw the brand gradient."""
    if not isinstance(card, dict):
        return None
    camp = card.get("campaign_offer") if isinstance(card.get("campaign_offer"), dict) else {}
    candidates = []
    if camp.get("wallet_photo"):
        candidates.append(camp.get("image_url"))
    candidates.append(card.get("poster_image_url"))
    hero_mode = card.get("hero_mode") or ("image" if card.get("hero_image_url") else "brand")
    if hero_mode in ("image", "composite"):
        candidates.append(card.get("hero_image_url"))
    for c in candidates:
        url = _public_image(c)
        if url:
            return url
    return None


def campaign_offer_for_photo(cust: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What hero_photo_url needs of the Wallet pass's campaign offer
    (wallet_passes._attach_campaign_offer's choice: the NEWEST wallet campaign
    this client received, if still live and named), read with one bounded,
    indexed query — the pass reads every such campaign of the client and
    renders its text, the page only needs the photo."""
    from features import campaign_kinds as _K
    from features import wallet_passes as _WP
    rows = _db.campaigns.find(
        {"tenant_id": cust.get("tenant_id"), "status": "sent", "wallet_offer": True, "recipient_ids": cust.get("id")},
        # the pass's own projection: the same fields decide « live »
        {"_id": 0, "id": 1, "name": 1, "sent_at": 1, "image_url": 1, "status": 1,
         "kind": 1, "offer": 1, "event": 1, "defi": 1, "wallet_photo": 1}).sort("sent_at", -1).limit(CAMPAIGN_PEEK)
    newest, newest_at = None, None
    for c in rows:
        at = _WP._parse_dt(c.get("sent_at"))
        if at and (newest_at is None or at > newest_at):
            newest, newest_at = c, at
    if not newest or not _K.is_live(newest, _WP._now()) or not (newest.get("name") or "").strip():
        return None
    return {"id": newest.get("id"), "image_url": newest.get("image_url") or None,
            "wallet_photo": bool(newest.get("wallet_photo"))}


def last_visit(cust: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """This client's newest visit at this shop, for « Donner mon avis » (open
    14 days after it, one review per visit): {last_visit_date: ISO Z, last_visit_id}.
    Only the client's own row, one indexed read (tenant, customer, visit_time);
    a cancelled visit has left `visits`. Old data with no row → the customer's
    own last_visit_date, no id."""
    out: Dict[str, Optional[str]] = {"last_visit_date": None, "last_visit_id": None}
    if not isinstance(cust, dict) or not cust.get("id") or not cust.get("tenant_id"):
        return out
    row = None
    try:
        row = _db.visits.find_one({"tenant_id": cust["tenant_id"], "customer_id": cust["id"]},
                                  {"_id": 0, "id": 1, "visit_time": 1}, sort=[("visit_time", -1)])
    except Exception as exc:  # noqa: BLE001 — the card must open even if this read fails
        print(f"card page: last visit lookup failed (non-fatal): {exc}")
    if row and iso(row.get("visit_time")):
        out["last_visit_date"] = iso(row.get("visit_time"))
        out["last_visit_id"] = str(row["id"]) if row.get("id") else None
    else:
        out["last_visit_date"] = iso(cust.get("last_visit_date"))
    return out


_RGB_CSS = re.compile(r"^\s*rgba?\(\s*(-?\d{1,4})\s*,\s*(-?\d{1,4})\s*,\s*(-?\d{1,4})\s*(?:,\s*[\d.]+\s*)?\)\s*$", re.I)
_HEX_CSS = re.compile(r"^\s*#?([0-9a-f]{3}|[0-9a-f]{6})\s*$", re.I)


def hex_color(v: Any) -> Optional[str]:
    """« rgb(1, 2, 3) » / « #010203 » / « #abc » → « #010203 » (lower case),
    anything else → None: only a plain colour ever reaches the page's CSS."""
    if not isinstance(v, str) or len(v) > 40:
        return None
    m = _RGB_CSS.match(v)
    if m:
        return "#" + "".join("%02x" % max(0, min(255, int(x))) for x in m.groups())
    m = _HEX_CSS.match(v)
    if m:
        h = m.group(1).lower()
        return "#" + ("".join(c * 2 for c in h) if len(h) == 3 else h)
    return None


def pass_colors(card: Dict[str, Any], cust: Dict[str, Any]) -> Dict[str, Any]:
    """The colours the client sees on the Apple Wallet card (user, 2026-11-26:
    the page must read as the same object): the active Pass Designer design of
    the card's OWN store (its home store, else the main one — as the pass is
    built), else FidClic's own pass colours (wallet_passes.derive_colors) and
    the card's fields. footer None = Apple's blur of the photo's bottom."""
    from features import pass_designer as _PD
    from features import store_cards as _SC
    from features import wallet_passes as _WP
    tid = cust.get("tenant_id")
    sid = cust.get("branch_id") or _SC.main_store(tid)
    # pass_designer.load's rule (active, a pass.json), read without the design's
    # images — they can weigh megabytes and the page needs only colours
    with _SC.store(tid, sid):
        doc = _db.card_templates.find_one({"tenant_id": tid},
                                          {"_id": 0, "pass_designer.active": 1, "pass_designer.pass": 1}) or {}
    tpl = doc.get("pass_designer") if isinstance(doc.get("pass_designer"), dict) else None
    if tpl and tpl.get("active", True) is False:
        tpl = None
    t = tpl.get("pass") if isinstance(tpl, dict) and isinstance(tpl.get("pass"), dict) else None
    style = _PD.style_of(t) if t else None
    own = _WP.derive_colors(card)
    pick = lambda k: hex_color((t or {}).get(k)) if style else None   # noqa: E731
    footer = pick("footerBackgroundColor") if style else None
    if not footer:
        # FidClic's poster band (wallet_passes.build_pass_json); a design without
        # its own footer keeps the pass's
        footer = hex_color(card.get("poster_footer_color"))
    poster = (style == "posterGeneric") if style else card.get("poster_style") is not False
    return {
        "background": pick("backgroundColor") or hex_color(own.get("backgroundColor")),
        "foreground": pick("foregroundColor") or (None if style and t.get("foregroundColor") else hex_color(own.get("foregroundColor"))),
        "label": pick("labelColor") or (None if style and t.get("labelColor") else hex_color(own.get("labelColor"))),
        "footer": footer if poster else None,
        "name": hex_color(card.get("logo_text_color")),
        "poster": bool(poster),
    }


def enrich(payload: Dict[str, Any], cust: Dict[str, Any]) -> Dict[str, Any]:
    """The fields GET /api/card/{bc} adds for the page."""
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("customer"), dict):
        payload["customer"]["first_name"] = first_name(cust.get("name"))
        payload["customer"].update(last_visit(cust))
    card = payload.get("card")
    if isinstance(card, dict):
        card["socials"] = socials(card.get("details"))
        # the store's button: the card's own store, one small read (always
        # written here, so nothing the owner's designer saved can stand in)
        try:
            t = _db.tenants.find_one({"id": cust.get("tenant_id")}, {"_id": 0, "card_cta": 1, "branches": 1}) or {}
            # the card's OWN store (its home store, else the main one) — never the
            # request's store header, which the payload's store_id may follow
            card["cta"] = cta_for(t, cust.get("branch_id"))
        except Exception as exc:  # noqa: BLE001 — a button must never cost the card
            print(f"card page: store button failed (non-fatal): {exc}")
            card["cta"] = {"label": CTA_DEFAULT_LABEL, "url": None}
        probe = dict(card)
        # a paused card carries no campaign (wallet_passes); an offer the
        # payload already carries is reused, else one small read
        if not cust.get("paused_at") and not isinstance(card.get("campaign_offer"), dict):
            try:
                offer = campaign_offer_for_photo(cust)
                if offer:
                    probe["campaign_offer"] = offer
            except Exception as exc:  # noqa: BLE001 — a missing photo must never cost the card
                print(f"card page: campaign photo lookup failed (non-fatal): {exc}")
        elif cust.get("paused_at"):
            probe.pop("campaign_offer", None)
        try:
            card["hero_photo_url"] = hero_photo_url(probe)
        except Exception as exc:  # noqa: BLE001
            print(f"card page: hero photo failed (non-fatal): {exc}")
            card["hero_photo_url"] = None
        try:   # the Wallet card's own colours (one small read, the store's design)
            card["pass_colors"] = pass_colors(card, cust)
        except Exception as exc:  # noqa: BLE001 — colours must never cost the card
            print(f"card page: pass colours failed (non-fatal): {exc}")
            card["pass_colors"] = None
    return payload


# ---------------------------------------------------------------------------
# the activity feed
# ---------------------------------------------------------------------------
def clamp_limit(n: Optional[int]) -> int:
    if n is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, int(n)))


def parse_before(s: Optional[str]) -> Optional[datetime]:
    """ISO 8601 → aware UTC datetime; ValueError when unreadable or outside
    the dates a datetime can hold once in UTC (0001-01-01+14:00…)."""
    if s is None or not str(s).strip():
        return None
    s = str(s).strip()
    if len(s) > 40:
        raise ValueError("date too long")
    s = re.sub(r"(T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?) (\d{2}:?\d{2})$", r"\1+\2", s)   # an unencoded « + » arrives as a space
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    try:
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("date out of range") from exc


# ---------------------------------------------------------------------------
# the paging cursor: (at, kind, tie) — tie = the row's _id, typed
# ---------------------------------------------------------------------------
KINDS = ("referral", "reward", "visit")          # the order rows of one instant take
_KIND_CODE = {"visit": "v", "reward": "r", "referral": "p"}
_CODE_KIND = {v: k for k, v in _KIND_CODE.items()}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_HEX24 = re.compile(r"[0-9a-f]{24}")


@dataclass(frozen=True)
class Position:
    """Where a page starts: rows strictly after this one in (at desc, kind, tie).
    kind None: a plain date — every row strictly older."""
    at: datetime
    kind: Optional[str] = None
    tie: Optional[str] = None


def _ms(d: datetime) -> datetime:
    """Mongo keeps milliseconds: every time is compared at that precision."""
    return d.replace(microsecond=d.microsecond - d.microsecond % 1000)


def tie_of(_id: Any) -> str:
    """A row's _id as a string that sorts like Mongo sorts _ids (strings before ObjectIds)."""
    return f"b{_id}" if isinstance(_id, ObjectId) else f"a{_id}"


def encode_cursor(at: datetime, kind: str, tie: str) -> str:
    ms = (at - _EPOCH) // timedelta(milliseconds=1)
    raw = f"{ms}|{_KIND_CODE[kind]}|{tie}".encode()
    return CURSOR_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def parse_cursor(s: str) -> Position:
    """« c1.… » → Position; ValueError for anything else."""
    body = s[len(CURSOR_PREFIX):]
    if not body or len(s) > MAX_BEFORE or not re.fullmatch(r"[A-Za-z0-9_\-]+", body):
        raise ValueError("bad cursor")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("bad cursor") from exc
    parts = raw.split("|", 2)
    if len(parts) != 3 or not re.fullmatch(r"-?\d{1,15}", parts[0]) or parts[1] not in _CODE_KIND:
        raise ValueError("bad cursor")
    tie = parts[2]
    if not (tie[:1] == "b" and _HEX24.fullmatch(tie[1:])) and not (tie[:1] == "a" and 0 < len(tie) <= 80
                                                                   and tie.isprintable()):
        raise ValueError("bad cursor")
    try:
        at = _EPOCH + timedelta(milliseconds=int(parts[0]))
    except OverflowError as exc:
        raise ValueError("bad cursor") from exc
    return Position(at=at, kind=_CODE_KIND[parts[1]], tie=tie)


def parse_position(s: Optional[str]) -> Optional[Position]:
    """`before`: the cursor a page gave as `next`, or a plain ISO date."""
    if s is None or not str(s).strip():
        return None
    s = str(s).strip()
    if s[:1] in ("c", "C"):                        # an ISO date never starts with a letter
        if not s.startswith(CURSOR_PREFIX):
            raise ValueError("unknown cursor version")
        return parse_cursor(s)
    d = parse_before(s)
    return Position(at=d) if d else None


def _after(pos: Optional[Position], at: datetime, kind: str, tie: str) -> bool:
    if pos is None:
        return True
    if at != pos.at:
        return at < pos.at
    return pos.kind is not None and (kind, tie) > (pos.kind, pos.tie)


def _tie_gt(tie: str) -> Dict[str, Any]:
    if tie[:1] == "b":
        return {"_id": {"$gt": ObjectId(tie[1:])}}
    # a string _id: the later strings, and every ObjectId (they sort after strings)
    return {"$or": [{"_id": {"$gt": tie[1:]}}, {"_id": {"$type": "objectId"}}]}


def _span(field: str, pos: Optional[Position], kind: str) -> Dict[str, Any]:
    """The Mongo filter for rows of `kind` after `pos` — date-typed times only."""
    if pos is None:
        return {field: {"$type": "date"}}
    older = {field: {"$lt": pos.at}}
    if pos.kind is None or kind < pos.kind:
        return older
    if kind > pos.kind:
        return {field: {"$lte": pos.at}}
    return {"$or": [older, {field: pos.at, **_tie_gt(pos.tie)}]}


def _rows(coll, base: Dict[str, Any], field: str, proj: Dict[str, Any], pos: Optional[Position], kind: str,
          take: int, text_dates: bool = False) -> Iterable[Dict[str, Any]]:
    """This source's first `take` rows after `pos`, as (doc, at, tie)."""
    proj = {**proj, "_id": 1, field: 1}
    for d in coll.find({**base, **_span(field, pos, kind)}, proj).sort([(field, -1), ("_id", 1)]).limit(take):
        at = _aware(d.get(field))
        if at is not None:
            yield d, _ms(at), tie_of(d.get("_id"))
    if text_dates:   # old rows whose time is text: compared once read, by the same rule
        for d in coll.find({**base, field: {"$type": "string"}}, proj).limit(TEXT_DATED_CAP):
            at = _aware(d.get(field))
            if at is None:
                continue
            at, tie = _ms(at), tie_of(d.get("_id"))
            if _after(pos, at, kind, tie):
                yield d, at, tie


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    if isinstance(v, str) and v.strip():
        try:
            return parse_before(v)
        except ValueError:
            return None
    return None


def iso(v: Any) -> Optional[str]:
    d = _aware(v)
    if d is None:
        return None
    d = d.astimezone(timezone.utc)
    base = d.strftime("%Y-%m-%dT%H:%M:%S")
    if d.microsecond:
        base += f".{d.microsecond // 1000:03d}" if d.microsecond % 1000 == 0 else f".{d.microsecond:06d}"
    return base + "Z"


def _store_names(t: Dict[str, Any]):
    names = {b.get("id"): b.get("name") or None for b in t.get("branches") or [] if b.get("id")}
    main = next((b.get("id") for b in t.get("branches") or [] if b.get("is_main")), "main")

    def name_of(branch_id: Any) -> Optional[str]:
        sid = branch_id or main
        return names.get(sid) or ((t.get("name") or None) if sid == main else None)
    return name_of


def _visit_stamps(d: Dict[str, Any], per: int) -> Optional[int]:
    """activity_history's rule: the visit's tampons + the paper card's; an old
    row (before 2026-10-15) gave one, unknown when a tampon takes several visits."""
    paper = int(d.get("paper_stamps") or 0)
    if "stamps_awarded" in d:
        return int(d.get("stamps_awarded") or 0) + paper
    return 1 + paper if per == 1 else (paper or None)


def _n_or_none(v: Any) -> Optional[int]:
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def activity(cust: Dict[str, Any], limit: int = DEFAULT_LIMIT, before: Any = None,
             stores: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """The client's feed after `before` (a Position, or a datetime: strictly
    older). `stores`: the establishments the reader covers, None = all — a
    visit elsewhere comes with `amount: None`."""
    from features import loyalty_card as _LC
    from features import referrals as _R
    from features import store_cards as _SC
    tid, cid = cust["tenant_id"], cust["id"]
    take = limit + 1
    pos = Position(at=before) if isinstance(before, datetime) else before
    covered = None if stores is None else set(stores)

    # the client's card (their home store's): tampons or a balance, its reward
    sid = cust.get("branch_id") or _SC.main_store(tid)
    with _SC.store(tid, sid):
        tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "programme": 1, "points_mode": 1,
                                                               "visits_per_stamp": 1, "reward_description": 1}) or {}
    stamps_card = _LC._programme(tpl) == "stamps"
    per = max(int(tpl.get("visits_per_stamp") or 1), 1)
    reward_default = tpl.get("reward_description") or "Une récompense fidélité"
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1, "branches": 1}) or {}
    store_of = _store_names(t)
    main_id = next((b.get("id") for b in t.get("branches") or [] if b.get("is_main")), "main")

    items: List[Dict[str, Any]] = []
    for d, at, tie in _rows(_db.visits, {"tenant_id": tid, "customer_id": cid}, "visit_time",
                            {"points_awarded": 1, "stamps_awarded": 1, "paper_stamps": 1, "amount_paid": 1,
                             "branch_id": 1}, pos, "visit", take, text_dates=True):
        mine = covered is None or (d.get("branch_id") or main_id) in covered
        items.append({"kind": "visit", "_at": at, "_tie": tie,
                      "points": int(d.get("points_awarded") or 0),
                      "stamps": _visit_stamps(d, per) if stamps_card else None,
                      "amount": None if not mine or d.get("amount_paid") is None else float(d.get("amount_paid") or 0),
                      "store": store_of(d.get("branch_id"))})

    for d, at, tie in _rows(_db.rewards_redeemed, {"tenant_id": tid, "customer_id": cid}, "redeemed_at",
                            {"reward_name": 1, "branch_id": 1}, pos, "reward", take):
        name = str(d.get("reward_name") or "").strip()
        items.append({"kind": "reward", "_at": at, "_tie": tie,
                      "title": name if name and name != "Reward" else reward_default,
                      "store": store_of(d.get("branch_id"))})

    proj = {"referrer_customer_id": 1, "referee_customer_id": 1, "referrer_pending": 1,
            "referrer_points": 1, "referee_points": 1, "referrer_given": 1, "referee_given": 1,
            "referrer_reward_promised": 1, "referee_reward_promised": 1, "rewarded_visits": 1}
    refs = []
    for side, mine_f, other in (("referrer", "referrer_customer_id", "referee_customer_id"),
                                ("referee", "referee_customer_id", "referrer_customer_id")):
        for d, at, tie in _rows(_db.referral_redemptions, {"tenant_id": tid, mine_f: cid, "referrer_pending": False},
                                "settled_at", proj, pos, "referral", take):
            refs.append((side, d.get(other), d, at, tie))
    friends = {}
    ids = list({f for _, f, _, _, _ in refs if f})
    if ids:   # one read for every friend's name — the first word only leaves this module
        friends = {c["id"]: first_name(c.get("name"))
                   for c in _db.customers.find({"tenant_id": tid, "id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1})}
    for side, fid, d, at, tie in refs:
        got = _R.given(d, side)
        items.append({"kind": "referral", "_at": at, "_tie": tie,
                      "role": "parrain" if side == "referrer" else "filleul",
                      "points": _n_or_none(got.get("points")), "stamps": _n_or_none(got.get("stamps")),
                      "offer": (got.get("offer_text") or None) if got.get("offers") else None,
                      "friend": friends.get(fid) or None})

    # (at desc, kind, tie): Python's sort is stable, also in reverse
    items.sort(key=lambda i: (i["kind"], i["_tie"]))
    items.sort(key=lambda i: i["_at"], reverse=True)
    more = len(items) > limit
    page = items[:limit]
    last = page[-1] if more and page else None
    nxt = encode_cursor(last["_at"], last["kind"], last["_tie"]) if last else None
    # the keys in a stable order: kind, at first; nothing internal leaves
    page = [{"kind": i["kind"], "at": iso(i["_at"]),
             **{k: v for k, v in i.items() if k not in ("kind", "_at", "_tie")}} for i in page]
    return {"items": page, "next": nxt}


@router.get("/api/card/{barcode_id}/activity")
def card_activity(barcode_id: str, request: Request, limit: Optional[int] = Query(None),
                  before: Optional[str] = Query(None, max_length=MAX_BEFORE)):
    import server as core
    cust, _who, stores = core._card_access(barcode_id, request)
    try:
        b = parse_position(before)
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(status_code=422, detail="« before » illisible : le `next` d'une page, ou une date ISO 8601.")
    return activity(cust, clamp_limit(limit), b, stores=stores)
