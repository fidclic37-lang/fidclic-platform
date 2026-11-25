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
    Each source reads at most limit+1 rows older than `before`, indexed, with
    a projection; the merge keeps `limit`. `next` is the last item's `at` when
    more exist — passed back as `before`. Rows at the very same millisecond as
    a page's last one could be skipped (never seen in practice: one till).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["card-page"])
_db = None

DEFAULT_LIMIT, MAX_LIMIT = 20, 100
MAX_INPUT = 300               # a social value longer than this is not a handle nor a profile link
MAX_PHOTO_URL = 2048
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


def enrich(payload: Dict[str, Any], cust: Dict[str, Any]) -> Dict[str, Any]:
    """The three fields GET /api/card/{bc} adds for the page."""
    if not isinstance(payload, dict):
        return payload
    if isinstance(payload.get("customer"), dict):
        payload["customer"]["first_name"] = first_name(cust.get("name"))
    card = payload.get("card")
    if isinstance(card, dict):
        card["socials"] = socials(card.get("details"))
        probe = dict(card)
        if not cust.get("paused_at"):                # a paused card carries no campaign (wallet_passes)
            try:
                from features import wallet_passes as _WP
                _WP._attach_campaign_offer(probe, cust)
            except Exception as exc:  # noqa: BLE001 — a missing photo must never cost the card
                print(f"card page: campaign photo lookup failed (non-fatal): {exc}")
        try:
            card["hero_photo_url"] = hero_photo_url(probe)
        except Exception as exc:  # noqa: BLE001
            print(f"card page: hero photo failed (non-fatal): {exc}")
            card["hero_photo_url"] = None
    return payload


# ---------------------------------------------------------------------------
# the activity feed
# ---------------------------------------------------------------------------
def clamp_limit(n: Optional[int]) -> int:
    if n is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, int(n)))


def parse_before(s: Optional[str]) -> Optional[datetime]:
    """ISO 8601 → aware UTC datetime; ValueError when unreadable."""
    if s is None or not str(s).strip():
        return None
    s = str(s).strip()
    if len(s) > 40:
        raise ValueError("date too long")
    s = re.sub(r"(T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?) (\d{2}:?\d{2})$", r"\1+\2", s)   # an unencoded « + » arrives as a space
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
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


def activity(cust: Dict[str, Any], limit: int = DEFAULT_LIMIT, before: Optional[datetime] = None) -> Dict[str, Any]:
    from features import loyalty_card as _LC
    from features import referrals as _R
    from features import store_cards as _SC
    tid, cid = cust["tenant_id"], cust["id"]
    take = limit + 1
    span = {"$lt": before} if before else {"$exists": True, "$ne": None}

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

    items: List[Dict[str, Any]] = []
    for d in _db.visits.find({"tenant_id": tid, "customer_id": cid, "visit_time": span},
                             {"_id": 0, "visit_time": 1, "points_awarded": 1, "stamps_awarded": 1, "paper_stamps": 1,
                              "amount_paid": 1, "branch_id": 1}).sort("visit_time", -1).limit(take):
        items.append({"kind": "visit", "_at": _aware(d.get("visit_time")),
                      "points": int(d.get("points_awarded") or 0),
                      "stamps": _visit_stamps(d, per) if stamps_card else None,
                      "amount": None if d.get("amount_paid") is None else float(d.get("amount_paid") or 0),
                      "store": store_of(d.get("branch_id"))})

    for d in _db.rewards_redeemed.find({"tenant_id": tid, "customer_id": cid, "redeemed_at": span},
                                       {"_id": 0, "redeemed_at": 1, "reward_name": 1, "branch_id": 1}
                                       ).sort("redeemed_at", -1).limit(take):
        name = str(d.get("reward_name") or "").strip()
        items.append({"kind": "reward", "_at": _aware(d.get("redeemed_at")),
                      "title": name if name and name != "Reward" else reward_default,
                      "store": store_of(d.get("branch_id"))})

    proj = {"_id": 0, "settled_at": 1, "referrer_customer_id": 1, "referee_customer_id": 1, "referrer_pending": 1,
            "referrer_points": 1, "referee_points": 1, "referrer_given": 1, "referee_given": 1,
            "referrer_reward_promised": 1, "referee_reward_promised": 1, "rewarded_visits": 1}
    refs = []
    for side, mine, other in (("referrer", "referrer_customer_id", "referee_customer_id"),
                              ("referee", "referee_customer_id", "referrer_customer_id")):
        for d in _db.referral_redemptions.find({"tenant_id": tid, mine: cid, "referrer_pending": False,
                                                "settled_at": span}, proj).sort("settled_at", -1).limit(take):
            refs.append((side, d.get(other), d))
    friends = {}
    ids = list({f for _, f, _ in refs if f})
    if ids:   # one read for every friend's name — the first word only leaves this module
        friends = {c["id"]: first_name(c.get("name"))
                   for c in _db.customers.find({"tenant_id": tid, "id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1})}
    for side, fid, d in refs:
        got = _R.given(d, side)
        items.append({"kind": "referral", "_at": _aware(d.get("settled_at")),
                      "role": "parrain" if side == "referrer" else "filleul",
                      "points": _n_or_none(got.get("points")), "stamps": _n_or_none(got.get("stamps")),
                      "offer": (got.get("offer_text") or None) if got.get("offers") else None,
                      "friend": friends.get(fid) or None})

    items = [i for i in items if i["_at"] is not None]
    items.sort(key=lambda i: i["_at"], reverse=True)
    more = len(items) > limit
    page = items[:limit]
    for i in page:
        i["at"] = iso(i.pop("_at"))
    # the keys in a stable order: kind, at first
    page = [{"kind": i["kind"], "at": i["at"], **{k: v for k, v in i.items() if k not in ("kind", "at")}}
            for i in page]
    return {"items": page, "next": page[-1]["at"] if more and page else None}


@router.get("/api/card/{barcode_id}/activity")
def card_activity(barcode_id: str, request: Request, limit: Optional[int] = Query(None),
                  before: Optional[str] = Query(None, max_length=64)):
    import server as core
    cust = core._card_customer(barcode_id, request)
    try:
        b = parse_before(before)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Date « before » illisible (ISO 8601 attendu).")
    return activity(cust, clamp_limit(limit), b)
