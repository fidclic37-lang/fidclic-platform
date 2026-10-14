"""
Carte de fidélité — the merchant's single card: design, rules, tiers, numbers.
Status: 🟢 Core.
Mounts at:
    GET  /api/owner/card/settings     → everything the page renders
    PUT  /api/owner/card/settings     → design + programme rules (one save)
    GET  /api/owner/card/stats?days=  → the four figures + their deltas
    PUT  /api/owner/card/rewards      → the reward ladder (paliers)

ONE CARD PER BUSINESS
    A tenant has exactly one card_templates document. This module is the
    read/write face of it for the new page; CardDesignerPage keeps writing the
    same document through /api/owner/card-template for the advanced knobs.

TWO PROGRAMME TYPES
    programme "points"  — the customer earns points (per euro spent by
                          default) and the ladder is read in points.
    programme "stamps"  — the classic loyalty card: one stamp per visit, a
                          reward every N stamps, ladder read in visits.
    The choice drives points_mode (per_euro / per_visit) and how a customer's
    tier is classified, so switching it actually changes the programme rather
    than only the wording.

EVERY FIGURE IS REAL
    No demo fallback here. Cards, scans, rewards and loyal customers are
    counted from customers / visits / rewards_redeemed, and each is compared
    with the previous window of the same length. An empty shop reads 0, which
    is the truth.
"""
from __future__ import annotations

import re

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S

router = APIRouter(tags=["loyalty-card"])
_db = None

# One card for every establishment: the same design, and stamps that count at
# every till. The owner edits it; administrateurs and managers read it, with
# the figures of their own establishments (features/store_scope.py).
READERS = ["business_owner", "administrateur", "manager"]

# What a merchant can actually run today. Each one changes how a scan earns,
# not just the wording on the page.
#   points_euro  1 € spent → N points        (points_mode per_euro)
#   points_visit fixed points per visit      (points_mode per_visit)
#   stamps       one stamp per visit, reward every N stamps
#   cashback     % of the bill kept as a euro balance (stored in cents)
PROGRESS_STYLES = ("stamps", "meter", "none")


def _progress_style(tpl: dict) -> str:
    """Which single indicator a stored card means.

    Cards saved before this choice existed have both flags on, because both
    defaulted to true. They are read as the meter: it is what the Wallet pass
    paints, so it is what those customers are already looking at."""
    stamps = tpl.get("show_stamps") is not False
    meter = tpl.get("show_meter") is not False
    if meter:
        return "meter"
    if stamps:
        return "stamps"
    return "none"


PROGRAMMES = ("points_euro", "points_visit", "stamps", "cashback")
LEGACY_PROGRAMMES = {"points": "points_euro"}

# The ladder the page shows under "Récompenses et paliers". Defaults are a
# sane starting point for a café; every merchant edits them.
DEFAULT_TIERS_POINTS = [
    {"key": "bronze", "min": 0,   "reward": "Boisson offerte"},
    {"key": "silver", "min": 100, "reward": "Pâtisserie offerte"},
    {"key": "gold",   "min": 300, "reward": "Menu offert"},
    {"key": "vip",    "min": 600, "reward": "Avantages VIP"},
]
DEFAULT_TIERS_STAMPS = [
    {"key": "bronze", "min": 0,  "reward": "Boisson offerte"},
    {"key": "silver", "min": 10, "reward": "Pâtisserie offerte"},
    {"key": "gold",   "min": 20, "reward": "Menu offert"},
    {"key": "vip",    "min": 40, "reward": "Avantages VIP"},
]
TIER_LABELS = {"bronze": "Bronze", "silver": "Argent", "gold": "Or", "vip": "VIP"}


def init(db):
    global _db
    _db = db
    try:
        _db.visits.create_index([("tenant_id", 1), ("visit_time", 1)])
        _db.rewards_redeemed.create_index([("tenant_id", 1), ("redeemed_at", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _name_fonts():
    from features.wallet_passes import NAME_FONTS
    return NAME_FONTS


def _template(tenant_id: str) -> Dict[str, Any]:
    tpl = _db.card_templates.find_one({"tenant_id": tenant_id}) or {}
    tpl.pop("_id", None)
    return tpl


def _programme(tpl: Dict[str, Any]) -> str:
    p = (tpl.get("programme") or "").strip().lower()
    p = LEGACY_PROGRAMMES.get(p, p)
    if p in PROGRAMMES:
        return p
    # Inferred for cards created before the page existed: a tenant already
    # earning per euro was running a points programme.
    return "points_euro" if tpl.get("points_mode") == "per_euro" else "stamps"


def _is_points(programme: str) -> bool:
    """Everything except the stamp card is counted on a balance."""
    return programme != "stamps"


def _unit(programme: str) -> str:
    return {"cashback": "€ cagnottés", "stamps": "visites"}.get(programme, "points")


def tiers_for(tenant_id: str) -> List[Dict[str, Any]]:
    """The ladder, always four rungs, always sorted, with the display range
    the page prints under each star."""
    tpl = _template(tenant_id)
    programme = _programme(tpl)
    rows = tpl.get("reward_tiers")
    if not isinstance(rows, list) or not rows:
        rows = DEFAULT_TIERS_POINTS if _is_points(programme) else DEFAULT_TIERS_STAMPS
    clean: List[Dict[str, Any]] = []
    for i, row in enumerate(rows[:4]):
        key = row.get("key") or ["bronze", "silver", "gold", "vip"][i]
        clean.append({
            "key": key,
            "label": TIER_LABELS.get(key, key.title()),
            "min": max(0, int(row.get("min") or 0)),
            "reward": (row.get("reward") or "").strip(),
        })
    clean.sort(key=lambda r: r["min"])
    unit = _unit(programme)
    for i, row in enumerate(clean):
        nxt = clean[i + 1]["min"] if i + 1 < len(clean) else None
        row["max"] = nxt
        row["range_label"] = (f"{row['min']} · {nxt} {unit}" if nxt is not None
                              else f"{row['min']}+ {unit}")
    return clean


def classify(customer: Dict[str, Any], tenant_id: str) -> str:
    """Which rung is this customer on? See tier_of."""
    return tier_of(customer, tenant_id)


# ---------------------------------------------------------------------------
# THE tier rule (QA F21, user 2026-10-09: « sab kuch dikhao »).
# A customer's palier comes from the ladder the owner sets under « Récompenses
# et paliers » — nowhere else. The scan, « Modifier la fiche » and a change of
# thresholds all use tier_of. One shortcut, shown and editable on the same
# card: VIP also from N visits with an average basket of at least X €.
# ---------------------------------------------------------------------------
VIP_SHORTCUT_DEFAULT = {"enabled": True, "min_visits": 10, "min_avg": 60}
TIER_ORDER = ["bronze", "silver", "gold", "vip"]


def vip_shortcut(tpl: Dict[str, Any]) -> Dict[str, Any]:
    raw = tpl.get("vip_shortcut") if isinstance(tpl.get("vip_shortcut"), dict) else {}
    out = {**VIP_SHORTCUT_DEFAULT, **{k: raw[k] for k in VIP_SHORTCUT_DEFAULT if k in raw}}
    out["enabled"] = bool(out["enabled"])
    out["min_visits"] = max(1, int(out["min_visits"] or 1))
    out["min_avg"] = max(0.0, float(out["min_avg"] or 0))
    return out


def earned_points(customer: Dict[str, Any]) -> int:
    """Points the client has EARNED over their life with the shop.

    Since a reward can be bought with points, `points` is a balance and goes
    down. The palier must not: it was earned by coming back. Cards written
    before the split have no `points_lifetime` — their balance has never been
    spent, so it IS what they earned."""
    v = customer.get("points_lifetime")
    return int(v if v is not None else (customer.get("points") or 0))


def floor_of(customer: Dict[str, Any]) -> str:
    """The highest rung this client has ever stood on.

    A palier is never taken back (user, 2026-10-13): « usne woh tier earn kiya
    hai loyalty dikha ke ». Cards from before carry no `tier_best`, so their
    current `tier` is their floor — nobody is demoted by this arriving."""
    best = (customer.get("tier_best") or customer.get("tier") or "bronze").lower()
    return best if best in TIER_ORDER else "bronze"


def tier_of(customer: Dict[str, Any], tenant_id: str, tpl: Optional[Dict[str, Any]] = None) -> str:
    """Points or visits against the ladder, per the programme; then the VIP
    shortcut (visits + average basket), if the owner keeps it on — and never
    below a rung already reached.

    A palier only ever goes up. Spending points on a reward, an owner raising
    the ladder, a correction at the till: none of them can send a client back
    down. What they earned, they keep."""
    tpl = tpl if tpl is not None else _template(tenant_id)
    programme = _programme(tpl)
    visits = int(customer.get("visits") or 0)
    value = earned_points(customer) if _is_points(programme) else visits
    tier = "bronze"
    for row in tiers_for(tenant_id):
        if value >= row["min"]:
            tier = row["key"]
    sc = vip_shortcut(tpl)
    if sc["enabled"] and tier != "vip" and visits >= sc["min_visits"]:
        avg = float(customer.get("total_amount_paid") or 0) / visits if visits else 0.0
        if avg >= sc["min_avg"]:
            tier = "vip"
    floor = floor_of(customer)
    return tier if TIER_ORDER.index(tier) >= TIER_ORDER.index(floor) else floor


def recompute_tiers(tenant_id: str, announce: bool = True) -> Dict[str, int]:
    """Every customer's palier again, after the owner changed the rule.

    Each card whose palier changed is refreshed. A customer who goes UP is
    told (user, 2026-10-09: « card update with push notifs »), outside the
    shop's daily limits (kind « tier_up », features/send_rules.EXEMPT); one
    who goes down only sees the card change. The daily « Atteinte d'un
    palier » scenario is not stamped, so nobody is congratulated twice."""
    tpl = _template(tenant_id)
    tenant = _db.tenants.find_one({"id": tenant_id}, {"_id": 0, "name": 1, "campaign_sender_name": 1}) or {}
    shop = tenant.get("campaign_sender_name") or tenant.get("name") or "votre commerce"
    rewards = {r["key"]: r.get("reward") or "" for r in tiers_for(tenant_id)}
    # "down" stays at zero now that a palier is a floor — kept so callers
    # and the page that reads this answer do not have to change.
    out = {"up": 0, "down": 0, "same": 0}
    quiet: List[str] = []                      # cards to refresh without a word
    live = {"tenant_id": tenant_id, "$or": [{"deleted_at": {"$exists": False}}, {"deleted_at": None}]}
    for c in _db.customers.find(live, {"_id": 0, "id": 1, "name": 1, "tier": 1, "visits": 1, "points": 1,
                                        "total_amount_paid": 1}):
        old = (c.get("tier") or "bronze").lower()
        new = tier_of(c, tenant_id, tpl)
        if new == old:
            out["same"] += 1
            continue
        up = TIER_ORDER.index(new) > (TIER_ORDER.index(old) if old in TIER_ORDER else 0)
        out["up" if up else "down"] += 1
        # `tier_best` is the floor from now on: a rung reached is never lost.
        _db.customers.update_one({"id": c["id"]}, {"$set": {"tier": new, "previous_tier": old,
                                                            "tier_best": new,
                                                            "tier_recomputed_at": _now(), "updated_at": _now()}})
        if not (up and announce):
            quiet.append(c["id"])
            continue
        if up and announce:
            label = TIER_LABELS.get(new, new)
            first = (c.get("name") or "").split(" ")[0]
            title = f"🎉 Nouveau palier : {label}"
            body = (f"Bravo{(' ' + first) if first else ''} ! Vous passez {label} chez {shop}."
                    + (f" Votre avantage : {rewards.get(new)}." if rewards.get(new) else ""))
            try:
                import server as core
                core.dispatch_to_customer(tenant_id, {**c, "tenant_id": tenant_id}, title, body, kind="tier_up")
            except Exception as exc:
                print(f"tiers: push not sent ({exc})")
            try:
                from features.wallet_passes import notify_customer
                notify_customer(c["id"], google_notify={"kind": "tier_up", "header": title, "body": body})
            except Exception as exc:
                print(f"tiers: wallet not refreshed ({exc})")
    if quiet:
        try:
            from features.wallet_passes import notify_tenant
            notify_tenant(tenant_id, customer_ids=quiet)
        except Exception:
            pass
    return out


# ---------------------------------------------------------------------------
# Settings — one read, one write
# ---------------------------------------------------------------------------
class CardSettings(BaseModel):
    # design
    card_name: Optional[str] = None
    surface_color: Optional[str] = None          # couleur principale
    brand_color: Optional[str] = None            # couleur secondaire
    logo_url: Optional[str] = None
    hero_image_url: Optional[str] = None         # image de fond
    welcome_text: Optional[str] = Field(None, max_length=100)
    card_message: Optional[str] = Field(None, max_length=120)
    # programme
    programme: Optional[str] = None              # see PROGRAMMES
    points_per_euro: Optional[float] = None
    cashback_rate: Optional[float] = None        # % of the bill, cashback only
    points_per_visit: Optional[int] = None
    reward_threshold_stamps: Optional[int] = None
    reward_points: Optional[int] = None          # points for the default reward
    reward_description: Optional[str] = None
    # toggles
    show_points: Optional[bool] = None
    show_qr: Optional[bool] = None
    show_message: Optional[bool] = None
    wallet_enabled: Optional[bool] = None
    birthday_notification: Optional[bool] = None
    # ── advanced: the knobs Apple and Google actually expose ──────────────
    code_type: Optional[str] = None              # qr | barcode | pdf417 | aztec | any PKBarcodeFormat…
    code_fallback: Optional[str] = None          # the format iOS 26 and earlier read
    # « Logo rond » (user, 2026-10-08): the logo cut to a disc, optional ring
    logo_round: Optional[bool] = None
    logo_ring: Optional[bool] = None
    logo_ring_color: Optional[str] = None
    # iOS 27 + every jauge (user, 2026-10-11): the band under the poster's
    # fields — "" = Apple's blur, "#RRGGBB" = that colour — and the tampons'
    # shape ("" = bars painted, ● in text; else wallet_passes.STAMP_SHAPES)
    poster_footer_color: Optional[str] = None
    stamp_shape: Optional[str] = None
    # the reward on the card (user, 2026-10-12): shown or not, and where —
    # "front" (under the QR) or "back" (⋯ › Détails du pass)
    reward_on_card: Optional[bool] = None
    reward_place: Optional[str] = None
    # the shop's name beside the logo, in every Wallet (user, 2026-10-12):
    # "" = the card's text colour, "#RRGGBB" = that colour (wallet_passes.name_logo)
    logo_text_color: Optional[str] = None
    name_logo_size: Optional[int] = None           # « Taille du logo » beside the name, 0–100 (0: the name alone)
    name_font: Optional[str] = None                # « Police du nom » (wallet_passes.NAME_FONTS), "" = default
    name_style: Optional[Dict[str, Any]] = None    # « Nom stylé »: letter by letter (wallet_passes.clean_name_style)
    # test, no control on the page (user, 2026-10-14): the card numbers whose
    # iOS 27 logo + name is drawn at 126 × 30 pt (wallet_passes._name_into_logos)
    poster_logo_test: Optional[List[str]] = None
    poster_logo_test_box: Optional[List[int]] = None   # its box in pt, [width, height] (default [126, 30])
    # the Google Wallet card's own design (wallet_passes.clean_google_design)
    google_design: Optional[Dict[str, Any]] = None
    show_card_number: Optional[bool] = None
    use_full_name: Optional[bool] = None
    greeting_label: Optional[str] = None
    points_label: Optional[str] = None
    visits_label: Optional[str] = None
    stamps_label: Optional[str] = None
    back_fields: Optional[List[Dict[str, str]]] = None   # [{label, value}]
    pass_expiration_date: Optional[str] = None
    location_reminder: Optional[bool] = None     # lock screen near the shop
    location_radius_m: Optional[int] = None      # Apple's maxDistance
    location_text: Optional[str] = None          # what the lock screen says
    allow_sharing: Optional[bool] = None
    strip_shine: Optional[bool] = None
    header_field: Optional[str] = None           # tier | points | visits | none
    show_tier: Optional[bool] = None
    show_visits: Optional[bool] = None
    show_stamps: Optional[bool] = None
    show_meter: Optional[bool] = None            # the gauge painted on the banner
    hero_mode: Optional[str] = None              # image | brand | none
    progress_style: Optional[str] = None         # stamps | meter | none
    code_content: Optional[str] = None           # number | url
    points_change_message: Optional[str] = None  # notification wording
    stamps_change_message: Optional[str] = None
    google_links: Optional[List[Dict[str, str]]] = None   # [{label, uri}]
    # iOS 27 (WWDC26): the poster style, and up to two tiles under the pass
    poster_style: Optional[bool] = None
    poster_image_url: Optional[str] = None                    # portrait photo for the poster
    featured_actions: Optional[List[Dict[str, str]]] = None   # [{type, url?}]



def _google_design(d):
    from features.wallet_passes import clean_google_design
    return clean_google_design(d)


def _barcode_formats():
    from features.wallet_passes import BARCODE_FORMATS, NEW_BARCODES
    return [{"format": k, "label": v, "ios27_only": k in NEW_BARCODES} for k, v in BARCODE_FORMATS.items()]


def _stamp_shapes():
    from features.wallet_passes import STAMP_SHAPES
    return [{"key": k, "label": lbl, "full": f.replace("\ufe0e", ""), "empty": e} for k, (lbl, f, e) in STAMP_SHAPES.items()]


def _featured_types():
    from features.wallet_passes import FEATURED_TYPES
    return FEATURED_TYPES


def _sector_reward(sector):
    from services.sector_rewards import default_reward
    return default_reward(sector)


@router.get("/api/owner/card/settings")
def get_card_settings(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    tpl = _template(tid)
    tenant = _db.tenants.find_one({"id": tid}) or {}
    from features import store_cards as SC          # several establishments: the chosen one's name
    _sn = SC.store_name(tid, SC.store_for(tid))
    if _sn:
        tenant = {**tenant, "name": _sn}
    programme = _programme(tpl)
    return {
        "tenant": {"name": tenant.get("name"), "slug": tenant.get("slug"), "city": tenant.get("city"),
                   "sector": tenant.get("sector")},
        "design": {
            "card_name": tpl.get("card_name") or f"Carte Fidélité – {tenant.get('name', '')}".strip(" –"),
            "surface_color": tpl.get("surface_color") or "#1C1D22",
            "brand_color": tpl.get("brand_color") or "#B85C38",
            "logo_url": tpl.get("logo_url") or "",
            "hero_image_url": tpl.get("hero_image_url") or "",
            "welcome_text": tpl.get("welcome_text") or tpl.get("tagline") or "",
            "card_message": tpl.get("card_message") or tpl.get("offer_box_text") or "",
        },
        "programme": {
            "type": programme,
            "points_per_euro": float(tpl.get("points_per_euro") or 10),
            "cashback_rate": float(tpl.get("cashback_rate") or 5),
            "unit": _unit(programme),
            "points_per_visit": int(tpl.get("points_per_visit") or 10),
            "reward_threshold_stamps": int(tpl.get("reward_threshold_stamps") or 10),
            "reward_points": int(tpl.get("reward_points") or 100),
            "reward_description": tpl.get("reward_description") or _sector_reward(tenant.get("sector")),
        },
        "toggles": {
            "show_points": tpl.get("show_points") is not False,
            "show_qr": tpl.get("show_qr") is not False,
            "show_message": tpl.get("show_message") is not False,
            "wallet_enabled": tpl.get("wallet_enabled") is not False,
            # The birthday message is the Automatisations page's "Anniversaire"
            # scenario — the one the daily run actually sends.
            "birthday_notification": bool((_db.push_scenarios.find_one({"tenant_id": tid, "builtin": "birthday"})
                                           or {"enabled": True}).get("enabled")),
        },
        "advanced": {
            "code_type": tpl.get("code_type") or "qr",
            "code_fallback": tpl.get("code_fallback") or "",
            "logo_round": bool(tpl.get("logo_round")),
            "logo_ring": bool(tpl.get("logo_ring")),
            "logo_ring_color": tpl.get("logo_ring_color") or "",
            "poster_footer_color": tpl.get("poster_footer_color") or "",
            "logo_text_color": tpl.get("logo_text_color") or "",
            "name_logo_size": 100 if tpl.get("name_logo_size") is None else int(tpl.get("name_logo_size")),
            "name_font": tpl.get("name_font") or "",
            "name_style": tpl.get("name_style") or None,
            "name_fonts": [{"key": k, "label": v[2]} for k, v in _name_fonts().items()],
            "stamp_shape": tpl.get("stamp_shape") or "",
            "reward_on_card": tpl.get("reward_on_card") is not False,
            "reward_place": "front" if tpl.get("reward_place") == "front" else "back",
            "stamp_shapes": _stamp_shapes(),
            "google_design": _google_design(tpl.get("google_design")),
            "barcode_formats": _barcode_formats(),
            "show_card_number": tpl.get("show_card_number") is not False,
            "use_full_name": bool(tpl.get("use_full_name")),
            "greeting_label": tpl.get("greeting_label") or "Membre",
            "points_label": tpl.get("points_label") or "Points",
            "visits_label": tpl.get("visits_label") or "Visites",
            "stamps_label": tpl.get("stamps_label") or "Tampons",
            "back_fields": tpl.get("back_fields") or [],
            "pass_expiration_date": tpl.get("pass_expiration_date") or "",
            "location_reminder": tpl.get("location_reminder") is not False,
            "location_radius_m": int(tpl.get("location_radius_m") or 150),
            "location_text": tpl.get("location_text") or "",
            "header_field": tpl.get("header_field") or "auto",
            "show_tier": tpl.get("show_tier") is not False,
            "show_visits": tpl.get("show_visits") is not False,
            "show_stamps": tpl.get("show_stamps") is not False,
            "show_meter": tpl.get("show_meter") is not False,
            # The stamps row and the progress bar are the same fact drawn twice,
            # so the page offers ONE choice. The two flags stay as the storage —
            # the pass builder and both previews already read them — and this is
            # what that pair means, read back as a single value.
            "progress_style": _progress_style(tpl),
            "hero_mode": tpl.get("hero_mode") or ("image" if tpl.get("hero_image_url") else "brand"),
            "code_content": tpl.get("code_content") or "number",
            "points_change_message": tpl.get("points_change_message") or "",
            "stamps_change_message": tpl.get("stamps_change_message") or "",
            "google_links": tpl.get("google_links") or [],
            "poster_style": tpl.get("poster_style") is not False,
            "poster_image_url": tpl.get("poster_image_url") or "",
            "featured_actions": tpl.get("featured_actions") or [],
            # needs: what the owner types for that button — link (required),
            # link_optional (FidClic's page otherwise), phone, place
            "featured_types": [{"type": k, "label": v[0],
                                "needs": {"url": "link", "offers": "link_optional", "program": "link_optional",
                                          "call": "phone", "place": "place"}[v[1]]}
                               for k, v in _featured_types().items()],
            "allow_sharing": bool(tpl.get("allow_sharing")),
            "strip_shine": bool(tpl.get("strip_shine")),
            # read-only context the panel needs to explain itself
            "has_coordinates": bool(tenant.get("lat") or tenant.get("latitude")),
        },
        "tiers": tiers_for(tid),
        "vip_shortcut": vip_shortcut(tpl),
    }


@router.put("/api/owner/card/settings")
def put_card_settings(body: CardSettings,
                      token_data: TokenData = Depends(require_role(["business_owner"]))):
    """One save for the whole page. Only the fields that were sent are written,
    so the advanced Card Designer's knobs are never wiped by this page."""
    tid = token_data.tenant_id
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    # « Afficher le QR code » and « Ajouter la carte au wallet » are gone from
    # the page (user, 2026-10-02): every card has its code (its kind is the
    # « Type de code » option) and can be added to the wallet. A card saved
    # with either switched off gets them back on its next save.
    payload["show_qr"] = True
    payload["wallet_enabled"] = True

    if "programme" in payload:
        payload["programme"] = LEGACY_PROGRAMMES.get(payload["programme"], payload["programme"])
        if payload["programme"] not in PROGRAMMES:
            raise HTTPException(status_code=400, detail="Type de programme inconnu")
        # The programme is not a label: it drives how a scan earns.
        payload["points_mode"] = ("per_euro" if payload["programme"] in ("points_euro", "cashback")
                                  else "per_visit")
    if payload.get("cashback_rate") is not None:
        payload["cashback_rate"] = max(0.5, min(50, float(payload["cashback_rate"])))

    from features.wallet_passes import BARCODE_FORMATS
    if payload.get("code_type") is not None and payload["code_type"] not in ("qr", "barcode", "pdf417", "aztec", *BARCODE_FORMATS):
        raise HTTPException(status_code=400, detail="Type de code inconnu")
    if payload.get("code_fallback") is not None and payload["code_fallback"] not in ("", *BARCODE_FORMATS):
        raise HTTPException(status_code=400, detail="Code de secours inconnu")
    if payload.get("logo_ring_color") and not re.match(r"^#[0-9A-Fa-f]{6}$", payload["logo_ring_color"]):
        raise HTTPException(status_code=400, detail="Couleur de bordure invalide.")
    if payload.get("poster_footer_color") and not re.match(r"^#[0-9A-Fa-f]{6}$", payload["poster_footer_color"]):
        raise HTTPException(status_code=400, detail="Couleur du pied invalide.")
    if payload.get("reward_place") is not None and payload["reward_place"] not in ("front", "back"):
        raise HTTPException(status_code=400, detail="Emplacement de la récompense inconnu.")
    if payload.get("logo_text_color") and not re.match(r"^#[0-9A-Fa-f]{6}$", payload["logo_text_color"]):
        raise HTTPException(status_code=400, detail="Couleur du nom invalide.")
    if payload.get("name_logo_size") is not None and not 0 <= int(payload["name_logo_size"]) <= 100:
        raise HTTPException(status_code=400, detail="Taille du logo : de 0 à 100 %.")
    if payload.get("name_font"):
        from features.wallet_passes import NAME_FONTS
        if payload["name_font"] not in NAME_FONTS:
            raise HTTPException(status_code=400, detail="Police du nom inconnue.")
    if "name_style" in payload:
        from features.wallet_passes import clean_name_style
        payload["name_style"] = clean_name_style(payload["name_style"])
    if payload.get("stamp_shape"):
        from features.wallet_passes import STAMP_SHAPES
        if payload["stamp_shape"] not in STAMP_SHAPES:
            raise HTTPException(status_code=400, detail="Forme de tampon inconnue.")
    if payload.get("google_design") is not None:
        payload["google_design"] = _google_design(payload["google_design"])
    if payload.get("header_field") is not None and payload["header_field"] not in ("auto", "tier", "points", "visits", "none"):
        raise HTTPException(status_code=400, detail="Champ d'en-tête inconnu")
    if payload.get("hero_mode") is not None and payload["hero_mode"] not in ("image", "brand", "none"):
        raise HTTPException(status_code=400, detail="Style de bannière inconnu")
    if payload.get("progress_style") is not None:
        style = payload.pop("progress_style")
        if style not in PROGRESS_STYLES:
            raise HTTPException(status_code=400, detail="Indicateur de progression inconnu")
        # One control in, two flags out — never both on, so the card can never
        # show the same progress twice again.
        payload["show_stamps"] = style == "stamps"
        payload["show_meter"] = style == "meter"
    if payload.get("code_content") is not None and payload["code_content"] not in ("number", "url"):
        raise HTTPException(status_code=400, detail="Contenu du code inconnu")
    if payload.get("location_radius_m") is not None:
        payload["location_radius_m"] = max(50, min(2000, int(payload["location_radius_m"])))
    if payload.get("google_links") is not None:
        payload["google_links"] = [
            {"label": (r.get("label") or "").strip()[:30], "uri": (r.get("uri") or "").strip()[:300]}
            for r in payload["google_links"][:3]
            if (r.get("uri") or "").strip().startswith(("http://", "https://", "tel:", "mailto:"))
        ]
    if payload.get("poster_image_url"):
        v = payload["poster_image_url"]
        from services import media as _M
        if not _M.is_image_value(v):        # a link to our own media is the saved picture
            raise HTTPException(status_code=400, detail="Image poster invalide.")
        if len(v) > 3_500_000:
            raise HTTPException(status_code=400, detail="L'image poster dépasse 2,5 Mo.")
    if payload.get("featured_actions") is not None:
        # Only what Wallet will draw: an unknown type would hide every tile.
        from features.wallet_passes import clean_featured
        payload["featured_actions"] = clean_featured(payload["featured_actions"], keep_empty=True)
    if payload.get("back_fields") is not None:
        # Keep it to rows the customer can actually read on the back.
        payload["back_fields"] = [
            {"label": (r.get("label") or "").strip()[:40], "value": (r.get("value") or "").strip()[:400]}
            for r in payload["back_fields"][:8]
            if (r.get("label") or "").strip() and (r.get("value") or "").strip()
        ]
    if payload.get("reward_threshold_stamps") is not None:
        payload["reward_threshold_stamps"] = max(1, min(50, int(payload["reward_threshold_stamps"])))
    if payload.get("points_per_euro") is not None:
        payload["points_per_euro"] = max(0.1, min(1000, float(payload["points_per_euro"])))
    if payload.get("reward_points") is not None:
        payload["reward_points"] = max(1, int(payload["reward_points"]))

    # The card face reads offer_box_text; keep the two in step so the wallet
    # pass and the web card show the merchant's message.
    if "card_message" in payload:
        payload["offer_box_text"] = payload["card_message"]
        payload["show_offer_box"] = bool(payload["card_message"])
    if "welcome_text" in payload:
        payload["greeting_label"] = payload.get("greeting_label") or "Membre"
        # the pass reads `tagline` (the onboarding's slogan): the « Texte
        # d'accueil » IS that text — it was saved apart and never reached the
        # card, only the preview (user, 2026-10-12)
        payload["tagline"] = (payload["welcome_text"] or "").strip()

    # The toggle switches the Automatisations page's "Anniversaire" scenario
    # (it used to write a collection nothing read).
    birthday = payload.pop("birthday_notification", None)
    if birthday is not None:
        try:
            from features import push_wallet as _PW
            if _PW._db is None:
                _PW.init(_db)
            _PW._seed(tid)
        except Exception:
            pass
        _db.push_scenarios.update_one({"tenant_id": tid, "builtin": "birthday"},
                                      {"$set": {"enabled": bool(birthday), "updated_at": _now()}})

    if (payload.get("reward_description") or "").strip():
        # Saved from this page, where the merchant sees it: the reward is now
        # theirs, never replaced by the sector's (services/sector_rewards).
        payload["reward_chosen"] = True
    if payload:
        payload["tenant_id"] = tid
        payload["updated_at"] = _now()
        _db.card_templates.update_one({"tenant_id": tid}, {"$set": payload}, upsert=True)
        # The Historique page reads this: "who changed what on the card, when".
        # Only the field names travel — a logo data-URI has no business in a log.
        try:
            from features import audit
            audit.log("card.settings.updated", tenant_id=tid, actor=token_data,
                      object_kind="card_template", object_id=tid,
                      after={k: True for k in payload
                             if k not in ("tenant_id", "updated_at")},
                      db=_db)
        except Exception:
            pass        # a history line is never worth losing a save over

    # The customers' cards must follow the merchant's change.
    wallet = {"devices": 0, "sent": 0}
    try:
        from features.wallet_passes import notify_tenant
        wallet = notify_tenant(tid)
    except Exception as e:  # noqa: BLE001 — a push must never fail a save
        print(f"card settings: wallet notify failed ({e})")

    return {"ok": True, "saved": sorted(k for k in payload if k not in ("tenant_id", "updated_at")),
            "wallet_passes_updated": wallet.get("sent", 0)}


class RewardTier(BaseModel):
    key: Optional[str] = None
    min: int = 0
    reward: str = ""


class VipShortcut(BaseModel):
    enabled: bool = True
    min_visits: int = Field(10, ge=1, le=1000)
    min_avg: float = Field(60, ge=0, le=100000)


class RewardsIn(BaseModel):
    tiers: List[RewardTier]
    vip_shortcut: Optional[VipShortcut] = None


@router.put("/api/owner/card/rewards")
def put_rewards(body: Union[RewardsIn, List[RewardTier]],
                token_data: TokenData = Depends(require_role(["business_owner"]))):
    """The four rungs (and the VIP shortcut). Thresholds must climb; the first
    one starts at 0 so no customer falls outside the ladder. Every customer's
    palier follows at once (recompute_tiers)."""
    tiers = body.tiers if isinstance(body, RewardsIn) else body
    shortcut = body.vip_shortcut if isinstance(body, RewardsIn) else None
    rows = [t.model_dump() for t in tiers][:4]
    if not rows:
        raise HTTPException(status_code=400, detail="Au moins un palier est requis")
    keys = ["bronze", "silver", "gold", "vip"]
    for i, row in enumerate(rows):
        row["key"] = row.get("key") if row.get("key") in keys else keys[i]
        row["min"] = max(0, int(row.get("min") or 0))
    # The rungs keep their order — Bronze, Argent, Or, VIP — whatever numbers
    # are typed. Sorting by number used to move the names: a Bronze ceiling
    # typed above Argent's made Argent the top rung (user's page, 2026-10-02).
    rows.sort(key=lambda r: keys.index(r["key"]))
    rows[0]["min"] = 0
    for i in range(1, len(rows)):
        if rows[i]["min"] <= rows[i - 1]["min"]:
            below = TIER_LABELS.get(rows[i - 1]["key"], rows[i - 1]["key"])
            here = TIER_LABELS.get(rows[i]["key"], rows[i]["key"])
            raise HTTPException(status_code=400, detail=(
                f"Le palier {here} doit commencer au-dessus du palier {below} : "
                "chaque palier va plus loin que le précédent."))
    update = {"reward_tiers": rows, "tenant_id": token_data.tenant_id, "updated_at": _now()}
    if shortcut is not None:
        update["vip_shortcut"] = shortcut.model_dump()
    _db.card_templates.update_one({"tenant_id": token_data.tenant_id}, {"$set": update}, upsert=True)
    try:
        from features import audit
        audit.log("card.rewards.updated", tenant_id=token_data.tenant_id, actor=token_data,
                  object_kind="card_template", object_id=token_data.tenant_id,
                  after={"tiers": True}, db=_db)
    except Exception:
        pass
    try:
        from features.wallet_passes import notify_tenant
        notify_tenant(token_data.tenant_id)
    except Exception:
        pass
    moved = recompute_tiers(token_data.tenant_id)
    return {"ok": True, "tiers": tiers_for(token_data.tenant_id),
            "vip_shortcut": vip_shortcut(_template(token_data.tenant_id)), "moved": moved}


# ---------------------------------------------------------------------------
# Statistics — four figures, each against the previous window
# ---------------------------------------------------------------------------
def _delta(current: int, previous: int) -> Optional[float]:
    """Percentage change, or None when there is nothing to compare with —
    "+100 %" out of zero would be a made-up number."""
    if previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


@router.get("/api/owner/card/stats")
def card_stats(days: int = Query(30, ge=1, le=365),
               token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
               request: Request = None):
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    tills = S.visit_filter(scope)                  # visits and rewards carry the till's branch_id
    mine = S.customer_ids(scope)
    people = {"id": {"$in": list(mine)}} if mine is not None else {}
    now = _now()
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    def customers_created(a: datetime, b: datetime) -> int:
        return _db.customers.count_documents({
            "tenant_id": tid, "created_at": {"$gte": a, "$lt": b},
            "card_deleted_at": {"$exists": False}, "deleted_at": {"$exists": False}, **people,
        })

    def visits_between(a: datetime, b: datetime) -> int:
        return _db.visits.count_documents({"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}, **tills})

    def rewards_between(a: datetime, b: datetime) -> int:
        return _db.rewards_redeemed.count_documents({"tenant_id": tid, "redeemed_at": {"$gte": a, "$lt": b}, **tills})

    active_cards = _db.customers.count_documents({
        "tenant_id": tid, "card_deleted_at": {"$exists": False}, "deleted_at": {"$exists": False}, **people,
    })
    scans, scans_prev = visits_between(start, now), visits_between(prev_start, start)
    rewards, rewards_prev = rewards_between(start, now), rewards_between(prev_start, start)
    # « Clients fidèles » is the Clients page's own (the shop's Règles clients),
    # as on every page (user, 2026-10-02) — today, against the period's start.
    from features import clients_page as CP, customer_rules as R
    rules = R.load(tid)
    base = list(_db.customers.find({"tenant_id": tid, "deleted_at": None, **people}, CP.FIELDS))
    loyal = sum(1 for c in base if CP.is_loyal(c, now, rules))
    loyal_prev = sum(1 for c in base if (CP._aware(c.get("created_at")) or now) < start and CP.is_loyal(c, start, rules))
    new_cards, new_cards_prev = customers_created(start, now), customers_created(prev_start, start)

    return {
        "window_days": days,
        "since": start.isoformat(),
        "cards_active": {"value": active_cards, "delta": _delta(new_cards, new_cards_prev),
                         "hint": "Cartes non supprimées. L'évolution compare les nouvelles cartes des deux périodes."},
        "qr_scans": {"value": scans, "delta": _delta(scans, scans_prev),
                     "hint": "Visites enregistrées en caisse sur la période."},
        "rewards_used": {"value": rewards, "delta": _delta(rewards, rewards_prev),
                         "hint": "Récompenses remises aux clients sur la période."},
        "loyal_customers": {"value": loyal, "delta": _delta(loyal, loyal_prev),
                            "hint": "Selon vos Règles clients, comme sur la page Clients. L'évolution compare avec le début de la période."},
    }
