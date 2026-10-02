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

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
    """Which rung is this customer on? Points or visits, per the programme."""
    tpl = _template(tenant_id)
    programme = _programme(tpl)
    value = int(customer.get("points") or 0) if _is_points(programme) \
        else int(customer.get("visits") or 0)
    tier = "bronze"
    for row in tiers_for(tenant_id):
        if value >= row["min"]:
            tier = row["key"]
    return tier


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
    code_type: Optional[str] = None              # qr | barcode | pdf417 | aztec
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


@router.get("/api/owner/card/settings")
def get_card_settings(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    tpl = _template(tid)
    tenant = _db.tenants.find_one({"id": tid}) or {}
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
            "welcome_text": tpl.get("welcome_text") or "",
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
            "reward_description": tpl.get("reward_description") or "Une boisson offerte",
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
            "allow_sharing": bool(tpl.get("allow_sharing")),
            "strip_shine": bool(tpl.get("strip_shine")),
            # read-only context the panel needs to explain itself
            "has_coordinates": bool(tenant.get("lat") or tenant.get("latitude")),
        },
        "tiers": tiers_for(tid),
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

    if payload.get("code_type") is not None and payload["code_type"] not in ("qr", "barcode", "pdf417", "aztec"):
        raise HTTPException(status_code=400, detail="Type de code inconnu")
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


@router.put("/api/owner/card/rewards")
def put_rewards(tiers: List[RewardTier],
                token_data: TokenData = Depends(require_role(["business_owner"]))):
    """The four rungs. Thresholds must climb; the first one starts at 0 so no
    customer falls outside the ladder."""
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
    _db.card_templates.update_one({"tenant_id": token_data.tenant_id},
                                  {"$set": {"reward_tiers": rows, "tenant_id": token_data.tenant_id,
                                            "updated_at": _now()}}, upsert=True)
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
    return {"ok": True, "tiers": tiers_for(token_data.tenant_id)}


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

    def loyal_between(a: datetime, b: datetime) -> int:
        """Customers who came back at least twice inside the window — the
        figure a merchant actually cares about behind "clients fidèles"."""
        try:
            rows = _db.visits.aggregate([
                {"$match": {"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}, **tills}},
                {"$group": {"_id": "$customer_id", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gte": 2}}},
                {"$count": "total"},
            ])
            return next(iter(rows), {}).get("total", 0)
        except Exception:
            # mongomock cannot always run this pipeline — count in Python.
            seen: Dict[str, int] = {}
            for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": a, "$lt": b}, **tills},
                                     {"customer_id": 1}):
                seen[v.get("customer_id")] = seen.get(v.get("customer_id"), 0) + 1
            return sum(1 for n in seen.values() if n >= 2)

    active_cards = _db.customers.count_documents({
        "tenant_id": tid, "card_deleted_at": {"$exists": False}, "deleted_at": {"$exists": False}, **people,
    })
    scans, scans_prev = visits_between(start, now), visits_between(prev_start, start)
    rewards, rewards_prev = rewards_between(start, now), rewards_between(prev_start, start)
    loyal, loyal_prev = loyal_between(start, now), loyal_between(prev_start, start)
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
                            "hint": "Clients venus au moins deux fois sur la période."},
    }
