"""
Historique — every activity on the loyalty programme, in one feed.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/history/activity   → the paginated table
    GET /api/owner/history/stats      → the four figures above it
    GET /api/owner/history/export     → the same rows as CSV
    GET /api/owner/history/filters    → what the Type / Action selects offer

WHERE THE ROWS COME FROM
    Nothing here is a new source of truth. Six collections the platform
    already writes are read and normalised into one row shape:

        visits              → Scan QR code            (+ points earned)
        rewards_redeemed    → Récompense utilisée     (− points spent)
        card_message_views  → Message affiché         (the card was opened
                              while a message was live — logged in server.py)
        customers           → Nouveau client          (created_at)
        push_notifications  → Message envoyé          (campaign sends)
        audit_log           → Modification de la carte

    So the Historique can never disagree with the pages it summarises: it is
    the same rows, read a second way.

PAGINATION ACROSS SIX COLLECTIONS
    `total` is counted exactly, per source, with count_documents. For the page
    itself each source yields at most `page * per_page` rows — enough that the
    merged, date-sorted slice is exactly right, and never the whole history.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth import require_role, TokenData
from features import store_scope as S

# The Historique is read by the owner, administrateurs and managers — each
# the activity of the establishments it may see.
READERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["history"])
_db = None

MAX_PER_PAGE = 100
MAX_EXPORT_ROWS = 20000

# The table shows each merchant their own clock; the CSV must not disagree with
# it. Every merchant on this platform is French, so the export is written in
# Paris time rather than UTC — a 20:35 scan reads 20:35 in both places.
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Europe/Paris")
except Exception:       # no tzdata in the image — UTC is wrong by an hour or two,
    LOCAL_TZ = timezone.utc     # but never wrong by a day, and never crashes

# ---------------------------------------------------------------------------
# The vocabulary the page is built on. One definition, used by the table, the
# tabs, the Action select, the four figures and the CSV alike.
# ---------------------------------------------------------------------------
ACTIONS: Dict[str, Dict[str, str]] = {
    "scan":         {"label": "Scan QR code",           "icon": "qr",      "tone": "blue"},
    "reward":       {"label": "Récompense utilisée",    "icon": "gift",    "tone": "amber"},
    "message_view": {"label": "Message affiché",        "icon": "message", "tone": "violet"},
    "signup":       {"label": "Nouveau client",         "icon": "user",    "tone": "green"},
    "campaign":     {"label": "Message envoyé",         "icon": "send",    "tone": "violet"},
    "card_update":  {"label": "Modification de la carte", "icon": "card",  "tone": "slate"},
    # by the shop's team (features/customer_edit.py)
    "client_update": {"label": "Fiche client modifiée", "icon": "user",   "tone": "slate"},
    "adjustment":    {"label": "Ajustement manuel",     "icon": "gift",   "tone": "amber"},
    # une carte perdue ou retrouvée, et par qui (user, 2026-10-23)
    "card_state":    {"label": "Carte du client",       "icon": "card",   "tone": "red"},
}

# Tab → the actions it shows. "Activité des clients" is what a customer did;
# the narrower tabs are subsets of it.
TABS: List[Dict[str, Any]] = [
    {"key": "all",      "label": "Toutes les activités",     "actions": list(ACTIONS)},
    {"key": "clients",  "label": "Activité des clients",     "actions": ["signup", "scan", "reward", "message_view", "client_update", "adjustment", "card_state"]},
    {"key": "points",   "label": "Points et récompenses",    "actions": ["scan", "reward", "adjustment"]},
    {"key": "scan",     "label": "Scan du QR code",          "actions": ["scan"]},
    {"key": "messages", "label": "Messages envoyés",         "actions": ["campaign", "message_view"]},
    {"key": "card",     "label": "Modifications de la carte", "actions": ["card_update", "card_state"]},
]
TAB_ACTIONS = {t["key"]: set(t["actions"]) for t in TABS}

# The audit actions the card page writes; anything else in the log belongs to
# another product and must not leak into this merchant-facing page.
CARD_AUDIT_ACTIONS = ("card.settings.updated", "card.rewards.updated")


def init(db):
    global _db
    _db = db
    for coll, index in (
        ("visits", [("tenant_id", 1), ("visit_time", -1)]),
        ("rewards_redeemed", [("tenant_id", 1), ("redeemed_at", -1)]),
        ("card_message_views", [("tenant_id", 1), ("at", -1)]),
        ("customers", [("tenant_id", 1), ("created_at", -1)]),
        ("push_notifications", [("tenant_id", 1), ("sent_at", -1)]),
    ):
        try:
            _db[coll].create_index(index)
        except Exception:
            pass        # best-effort; a missing index slows the page, never breaks it


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------
def _aware(dt: Any) -> Optional[datetime]:
    """Every timestamp in this feed ends up as an aware UTC datetime — the
    collections store a mix of datetimes and ISO strings."""
    if isinstance(dt, datetime):
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(dt, str) and dt:
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _window(date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime]:
    """The period picker, resolved. Defaults to the last 30 days; `to` covers
    the whole of its day so "21 sept." includes everything that happened on the
    21st."""
    now = datetime.now(timezone.utc)
    end = _aware(date_to) or now
    end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    start = _aware(date_from) or (end - timedelta(days=29))
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), start
    return start, end


# ---------------------------------------------------------------------------
# sources — each returns (count_query, collection, time_field, row builder)
# ---------------------------------------------------------------------------
def _name_map(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    ids = [i for i in dict.fromkeys(ids) if i]
    if not ids:
        return {}
    rows = _db.customers.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1, "barcode_id": 1, "branch_id": 1})
    return {r["id"]: r for r in rows}


def _sources(tid: str, start: datetime, end: datetime,
             scope: Optional["S.Scope"] = None) -> Dict[str, Dict[str, Any]]:
    """action key → how to count it, how to read it, how to render it."""
    span = {"$gte": start, "$lte": end}
    # Limited to the chosen establishments: scans and rewards by their tills,
    # everything about a client by the clients of those establishments.
    tills = S.visit_filter(scope) if scope else {}
    mine = S.customer_ids(scope) if scope else None
    clients = {} if mine is None else {"customer_id": {"$in": list(mine)}}
    rule = _card_rule(tid)
    return {
        "scan": {
            "coll": "visits", "time": "visit_time",
            "query": {"tenant_id": tid, "visit_time": span, **tills},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "detail": "Scan de la carte en magasin",
                "points": int(d.get("points_awarded") or 0),
                "stamps": _visit_stamps(d, rule),
                # a 0 € visit is 0 €, not blank (QA F14); no amount at all stays blank
                "amount": None if d.get("amount_paid") is None else float(d.get("amount_paid") or 0),
            },
        },
        "reward": {
            "coll": "rewards_redeemed", "time": "redeemed_at",
            "query": {"tenant_id": tid, "redeemed_at": span, **tills},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "customer_name": d.get("customer_name"),
                "detail": d.get("reward_name") or "Récompense utilisée",
                # A redemption spends the card, not a points balance, unless
                # the programme counts points — then the cost is recorded.
                "points": _reward_points(d, rule),
                "stamps": _reward_stamps(d, rule),
            },
        },
        "message_view": {
            "coll": "card_message_views", "time": "at",
            "query": {"tenant_id": tid, "at": span, **clients},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "detail": "Le message sur la carte a été affiché",
                "points": None,
            },
        },
        "signup": {
            "coll": "customers", "time": "created_at",
            "query": {"tenant_id": tid, "created_at": span,
                      **({} if mine is None else {"id": {"$in": list(mine)}})},
            "row": lambda d: {
                "customer_id": d.get("id"),
                "customer_name": d.get("name"),
                "detail": f"Inscription au programme{_source_suffix(d)}",
                "points": 0,
                "stamps": 0,
            },
        },
        "campaign": {
            "coll": "push_notifications", "time": "sent_at",
            "query": {"tenant_id": tid, "sent_at": span, "type": "campaign", **clients},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "detail": d.get("title") or "Message envoyé",
                "points": None,
            },
        },
        "client_update": {
            "coll": "customer_changes", "time": "at",
            "query": {"tenant_id": tid, "kind": "profile", "at": span, **clients},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "customer_name": d.get("customer_name"),
                "detail": f"{d.get('text') or 'Fiche modifiée'} · par {d.get('by') or 'l’équipe'}",
                "points": None,
            },
        },
        # Une carte perdue ou retrouvée (user, 2026-10-23 : « supprimée » ne
        # disait pas qui l'avait fait — le client depuis sa carte, ou le
        # commerce depuis « Voir sa carte » ; Apple et Google, eux, ne peuvent
        # venir que du téléphone du client).
        "card_state": {
            "coll": "customer_changes", "time": "at",
            "query": {"tenant_id": tid, "kind": "card_state", "at": span, **clients},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "customer_name": d.get("customer_name"),
                "detail": f"{d.get('text') or 'Carte modifiée'} · {d.get('by') or 'le client'}",
                "points": None,
            },
        },
        "adjustment": {
            "coll": "customer_changes", "time": "at",
            "query": {"tenant_id": tid, "kind": "adjust", "at": span, **clients},
            "row": lambda d: {
                "customer_id": d.get("customer_id"),
                "customer_name": d.get("customer_name"),
                "detail": f"{d.get('text')} — {d.get('reason')} · par {d.get('by') or 'l’équipe'}",
                "points": int(d.get("points_delta") or 0) or None,
                "stamps": int(d.get("visits_delta") or 0) or None,
            },
        },
        "card_update": {
            "coll": "audit_log", "time": "at",
            # audit_log stores `at` as an ISO string, so the window is applied
            # lexically — ISO-8601 in UTC sorts and compares as text.
            # A change to the card is the whole shop's: shown on "all" only.
            "query": {"tenant_id": tid, "action": {"$in": list(CARD_AUDIT_ACTIONS)},
                      "at": {"$gte": start.isoformat(), "$lte": end.isoformat()},
                      **({} if mine is None else {"_never": True})},
            "row": lambda d: {
                "customer_id": None,
                "customer_name": d.get("actor_email"),
                "detail": _card_change_detail(d),
                "points": None,
                "is_staff": True,
            },
        },
    }


# ---------------------------------------------------------------------------
# points AND tampons on every row (user, 2026-10-15: a tampons shop saw « 0 »
# points on every scan). Since that day a visit records the tampons it gave
# and a reward what it cost; older rows are worked out from the card's rule.
# ---------------------------------------------------------------------------
def _card_rule(tid: str) -> Dict[str, Any]:
    """The card of the establishment in the menu (features/store_cards)."""
    from features import loyalty_card as _LC
    tpl = _db.card_templates.find_one({"tenant_id": tid}) or {}
    return {"programme": _LC._programme(tpl),
            "per": max(int(tpl.get("visits_per_stamp") or 1), 1),
            "size": max(int(tpl.get("reward_threshold_stamps") or 10), 1),
            "price": max(int(tpl.get("reward_points") or 0), 0)}


def unit_of(tid: str) -> str:
    """What the column shows first: the shop's own programme."""
    return "stamps" if _card_rule(tid)["programme"] == "stamps" else "points"


def _visit_stamps(d: Dict[str, Any], rule: Dict[str, Any]) -> Optional[int]:
    paper = int(d.get("paper_stamps") or 0)
    if "stamps_awarded" in d:
        return int(d.get("stamps_awarded") or 0) + paper
    # before 2026-10-15: one visit, one tampon — unknown when a tampon takes several visits
    return 1 + paper if rule["per"] == 1 else (paper or None)


def _reward_points(d: Dict[str, Any], rule: Dict[str, Any]) -> Optional[int]:
    if d.get("points_spent"):
        return -abs(int(d["points_spent"]))
    if "stamps_spent" in d or rule["programme"] == "stamps":
        return None
    return -rule["price"] if rule["price"] else None


def _reward_stamps(d: Dict[str, Any], rule: Dict[str, Any]) -> Optional[int]:
    if d.get("stamps_spent"):
        return -abs(int(d["stamps_spent"]))
    if d.get("points_spent") or rule["programme"] != "stamps":
        return None
    return -rule["size"]


def _source_suffix(customer: Dict[str, Any]) -> str:
    from services import sources as _src
    raw = (customer.get("acquisition_source") or "").strip()
    key = _src.normalize(raw)
    # a known source by its label; an older free-text one (« Sur place ») as written
    return f" · {_src.label(key) if key else raw}" if raw else ""


_FIELD_LABELS = {
    "card_name": "nom de la carte", "surface_color": "couleur principale",
    "brand_color": "couleur secondaire", "logo_url": "logo",
    "hero_image_url": "image de fond", "hero_mode": "style de bannière",
    "welcome_text": "texte d'accueil", "card_message": "message sur la carte",
    "programme": "type de programme", "reward_threshold_stamps": "seuil de récompense",
    "reward_description": "récompense", "points_per_euro": "points par euro",
    "points_per_visit": "points par visite", "cashback_rate": "taux de cagnotte",
    "code_type": "type de code", "pass_expiration_date": "date d'expiration",
    "tiers": "paliers",
}


def _card_change_detail(entry: Dict[str, Any]) -> str:
    """"couleur principale, logo et seuil de récompense modifiés" — the field
    names the merchant recognises, not the database ones."""
    changed = list((entry.get("after") or {}).keys()) or list((entry.get("detail") or {}).get("fields") or [])
    labels = [_FIELD_LABELS.get(f, f.replace("_", " ")) for f in changed]
    labels = list(dict.fromkeys(labels))[:4]
    if not labels:
        return "Carte de fidélité mise à jour"
    if len(labels) == 1:
        return _sentence(f"{labels[0]} modifié")
    return _sentence(f"{', '.join(labels[:-1])} et {labels[-1]} modifiés")


def _sentence(text: str) -> str:
    """Upper-case the first letter only — str.capitalize() would lower-case the
    rest, turning "QR code modifié" into "Qr code modifié"."""
    return text[:1].upper() + text[1:]


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def _collect(tid: str, start: datetime, end: datetime, actions: List[str],
             per_source: int, scope: Optional["S.Scope"] = None) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Pull at most `per_source` newest rows for each action, plus the exact
    count of each. Returns (rows sorted newest first, {action: total})."""
    rows: List[Dict[str, Any]] = []
    totals: Dict[str, int] = {}
    sources = _sources(tid, start, end, scope)

    for action in actions:
        spec = sources.get(action)
        if not spec:
            continue
        coll, field = _db[spec["coll"]], spec["time"]
        try:
            totals[action] = coll.count_documents(spec["query"])
        except Exception:
            totals[action] = 0
        if per_source <= 0:
            continue
        try:
            docs = list(coll.find(spec["query"]).sort(field, -1).limit(per_source))
        except Exception:
            docs = []
        for d in docs:
            at = _aware(d.get(field))
            if at is None:
                continue
            base = spec["row"](d)
            rows.append({
                "id": str(d.get("id") or d.get("_id") or ""),
                "action": action,
                "label": ACTIONS[action]["label"],
                "icon": ACTIONS[action]["icon"],
                "tone": ACTIONS[action]["tone"],
                "at": at,
                # where it happened: the visit's / reward's till (QA F29)
                "branch_id": d.get("branch_id"),
                "till": spec["coll"] in ("visits", "rewards_redeemed"),
                **base,
            })

    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows, totals


def _attach_names(rows: List[Dict[str, Any]]) -> None:
    """One lookup for the whole page, not one per row."""
    people = _name_map([r.get("customer_id") for r in rows if r.get("customer_id")])
    for r in rows:
        person = people.get(r.get("customer_id") or "") or {}
        name = r.get("customer_name") or person.get("name") or ""
        r["customer_name"] = name or ("Système" if r.get("is_staff") else "Client supprimé")
        r["customer_barcode"] = person.get("barcode_id")
        r["initials"] = _initials(r["customer_name"])
        # a row without a till of its own (a signup, a message): the client's
        # establishment — a visit without one was recorded at the main till
        if not r.get("branch_id") and not r.get("till"):
            r["branch_id"] = person.get("branch_id")


def _attach_stores(tid: str, rows: List[Dict[str, Any]]) -> None:
    """The establishment of each row, by name (QA F29: « Toutes les branches »
    showed no establishment; the CSV neither). A visit recorded before stores
    existed — or without one — belongs to the main establishment."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1, "branches": 1}) or {}
    names = {b.get("id"): b.get("name") or "" for b in t.get("branches") or [] if b.get("id")}
    main = next((b.get("id") for b in t.get("branches") or [] if b.get("is_main")), "main")
    for r in rows:
        sid = r.get("branch_id") or main
        r["store_id"] = sid
        r["store_name"] = names.get(sid) or (t.get("name") or "" if sid == main else "")


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"[\s'-]+", (name or "").strip()) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _matches_customer(row: Dict[str, Any], needle: str) -> bool:
    hay = f"{row.get('customer_name') or ''} {row.get('customer_barcode') or ''}".lower()
    return needle in hay


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@router.get("/api/owner/history/filters")
def filters(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The tabs and the two selects, defined once on the server so the page and
    the CSV can never offer a filter the feed does not implement."""
    return {
        "tabs": [{"key": t["key"], "label": t["label"]} for t in TABS],
        "actions": [{"key": k, "label": v["label"], "icon": v["icon"], "tone": v["tone"]}
                    for k, v in ACTIONS.items()],
        "per_page_options": [10, 25, 50, 100],
        "unit": unit_of(token_data.tenant_id),      # « points » or « stamps »: the column's first view
    }


@router.get("/api/owner/history/activity")
def activity(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    tab: str = "all",
    action: Optional[str] = None,
    customer: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    per_page = max(1, min(MAX_PER_PAGE, int(per_page or 10)))
    page = max(1, int(page or 1))

    wanted = TAB_ACTIONS.get(tab, TAB_ACTIONS["all"])
    if action and action in ACTIONS:
        wanted = wanted & {action}
    wanted_list = [a for a in ACTIONS if a in wanted]

    needle = (customer or "").strip().lower()
    # A name search filters after the merge (names live on `customers`, not on
    # every row), so it needs a wider read than the page itself.
    per_source = (page * per_page) if not needle else min(MAX_EXPORT_ROWS, 2000)
    rows, totals = _collect(tid, start, end, wanted_list, per_source, S.resolve(token_data, request))
    _attach_names(rows)
    _attach_stores(tid, rows)

    if needle:
        rows = [r for r in rows if _matches_customer(r, needle)]
        total = len(rows)
    else:
        total = sum(totals.values())

    window = rows[(page - 1) * per_page: page * per_page]
    return {
        "rows": [_public(r) for r in window],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, -(-total // per_page)),
        "counts": totals,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "unit": unit_of(tid),
    }


def _public(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": r["id"], "action": r["action"], "label": r["label"],
        "icon": r["icon"], "tone": r["tone"], "at": r["at"].isoformat(),
        "customer_id": r.get("customer_id"), "customer_name": r["customer_name"],
        "customer_barcode": r.get("customer_barcode"), "initials": r["initials"],
        "detail": r.get("detail") or "", "points": r.get("points"), "stamps": r.get("stamps"),
        "amount": r.get("amount"),
        "store_id": r.get("store_id"), "store": r.get("store_name") or "",
    }


@router.get("/api/owner/history/stats")
def stats(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """The four figures, each against the previous window of the same length —
    so "+32%" always means "compared with the 21 days before these 21 days"."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    span = end - start
    prev_end = start - timedelta(microseconds=1)
    prev_start = prev_end - span

    keys = ["scan", "reward", "signup", "message_view"]
    scope = S.resolve(token_data, request)
    _, now_totals = _collect(tid, start, end, keys, per_source=0, scope=scope)
    _, was_totals = _collect(tid, prev_start, prev_end, keys, per_source=0, scope=scope)

    titles = {"scan": "Scans QR code", "reward": "Récompenses utilisées",
              "signup": "Nouveaux clients", "message_view": "Messages affichés"}
    return {
        "from": start.isoformat(), "to": end.isoformat(),
        "previous_from": prev_start.isoformat(), "previous_to": prev_end.isoformat(),
        "cards": [{
            "key": k, "label": titles[k], "icon": ACTIONS[k]["icon"], "tone": ACTIONS[k]["tone"],
            "value": now_totals.get(k, 0),
            "previous": was_totals.get(k, 0),
            "delta_pct": _delta(now_totals.get(k, 0), was_totals.get(k, 0)),
        } for k in keys],
    }


def _delta(now: int, was: int) -> Optional[int]:
    """None when there is nothing to compare against — a first month shows no
    percentage rather than a meaningless +100%."""
    if not was:
        return None
    return round((now - was) / was * 100)


@router.get("/api/owner/history/export")
def export_csv(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    tab: str = "all",
    action: Optional[str] = None,
    customer: Optional[str] = None,
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """The rows currently on screen — same filters, no pagination — as CSV."""
    tid = token_data.tenant_id
    start, end = _window(date_from, date_to)
    wanted = TAB_ACTIONS.get(tab, TAB_ACTIONS["all"])
    if action and action in ACTIONS:
        wanted = wanted & {action}
    rows, _ = _collect(tid, start, end, [a for a in ACTIONS if a in wanted], MAX_EXPORT_ROWS,
                       S.resolve(token_data, request))
    _attach_names(rows)
    _attach_stores(tid, rows)
    needle = (customer or "").strip().lower()
    if needle:
        rows = [r for r in rows if _matches_customer(r, needle)]

    buf = io.StringIO()
    # utf-8-sig via the BOM below: Excel in France opens CSV as latin-1 without it.
    w = csv.writer(buf, delimiter=";")
    # the establishment and its stable id (QA F29: a combined export could not be split by branch)
    w.writerow(["Date et heure", "Établissement", "ID établissement", "Client", "Numéro de carte", "Type d'activité",
                "Détails", "Points", "Tampons", "Montant (€)"])
    for r in rows:
        w.writerow([
            r["at"].astimezone(LOCAL_TZ).strftime("%d/%m/%Y %H:%M"),
            r.get("store_name") or "", r.get("store_id") or "",
            r["customer_name"], r.get("customer_barcode") or "",
            r["label"], r.get("detail") or "",
            "" if r.get("points") is None else r["points"],
            "" if r.get("stamps") is None else r["stamps"],
            "" if r.get("amount") is None else f"{r['amount']:.2f}".replace(".", ","),
        ])
    data = "﻿" + buf.getvalue()
    name = f"fidclic-historique-{start:%Y%m%d}-{end:%Y%m%d}.csv"
    # Built whole in memory anyway (the row count is capped), so a plain
    # Response is simpler than a stream and easier to assert on.
    return Response(
        content=data, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
