"""
Campagnes — the composer, its audience, and what the last sends actually did.

Built to the approved mockup. One request fills the whole page: the five
figures across the top, the four audience cards with live counts, and the
recent sends with their rates.

WHAT A CAMPAIGN IS HERE
    A message to a chosen audience, delivered on two channels at once:

      • Push      — the web push the customer allowed on their phone.
      • Wallet    — the same message becomes the card's current offer, and
                    every pass is woken so Apple Wallet raises its own
                    notification (the pass fields carry `changeMessage`).

    The two are complementary on purpose: a customer who never allowed push
    still sees the offer when they open their wallet card, and the merchant
    does not have to think about which of their customers is which.

THE ONE FIGURE THAT COULD LIE
    "Taux d'ouverture". A wallet push has no read receipt — nothing tells us
    a notification was read. So an open here means *the card was opened
    within 72 hours of the send*, the same definition the Automatisations
    page uses, and the page prints that sentence under the figure rather
    than letting it be read as an email open rate.

    "CA généré" is the spend of recipients in the ATTRIBUTION_DAYS after the
    send, each visit once (the latest campaign before it) — counted by
    services/campaign_figures, the same for Analyses › Campagnes (QA F32). It
    is an association, not a proof, and it carries its own note.

NOTHING IS INVENTED
    A merchant who has never sent a campaign reads zeros and is told so. No
    demo rows, no placeholder rates.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role
from models import TokenData
from features import store_scope as S
from features import campaign_kinds as K

# Campaigns are the owner's, an administrateur's (its establishments) and a
# manager's (its establishment) — each reaches only its own clients.
SENDERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["campagnes"])
_db = None

INACTIVE_DAYS = 30          # "Clients inactifs · Plus de 30 jours"
LOYAL_VISITS = 3            # "Clients fidèles · Plus de 3 achats" — strictly more
BIRTHDAY_DAYS = 7           # "Anniversaire · Cette semaine"
from services import campaign_figures as CF
OPEN_WINDOW_H = CF.OPEN_WINDOW_H        # a card opened this long after a send counts as an open
ATTRIBUTION_DAYS = CF.ATTRIBUTION_DAYS  # a visit inside this window counts for the campaign
WALLET_OFFER_DAYS = 30      # how long a campaign stays the card's current offer

TITLE_MAX = 50
MESSAGE_MAX = 160


def init(db):
    global _db
    _db = db
    try:
        db.campaigns.create_index([("tenant_id", 1), ("sent_at", -1)])
        db.card_opens.create_index([("tenant_id", 1), ("at", -1)])
        db.card_opens.create_index([("customer_id", 1), ("day", 1)], unique=True)
        # who already has a campaign (a retried send), and the words they got (the Wallet pass)
        db.push_notifications.create_index([("campaign_id", 1), ("customer_id", 1)])
        db.campaigns.create_index([("tenant_id", 1), ("send_key", 1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def _delta(now_value: float, was_value: float) -> Optional[int]:
    """Percentage change, or None when there is no previous period to compare
    against — a made-up "+100 %" against zero tells the merchant nothing."""
    if not was_value:
        return None
    return round((now_value - was_value) / was_value * 100)


# ---------------------------------------------------------------------------
# The audience vocabulary. One definition, used by the cards, by the count
# under the composer and by the send itself, so the three can never disagree.
# ---------------------------------------------------------------------------
SEGMENTS: List[Dict[str, str]] = [
    {"key": "all",      "label": "Tous mes clients", "hint": "",                    "icon": "users"},
    {"key": "inactive", "label": "Clients inactifs", "hint": f"Plus de {INACTIVE_DAYS} jours", "icon": "clock"},
    {"key": "loyal",    "label": "Clients fidèles",  "hint": f"Plus de {LOYAL_VISITS} achats", "icon": "star"},
    {"key": "birthday", "label": "Anniversaire",     "hint": "Cette semaine",       "icon": "gift"},
]
SEGMENT_KEYS = {s["key"] for s in SEGMENTS}
SEGMENT_LABELS = {s["key"]: s["label"] for s in SEGMENTS}


def _birthday_window(at: datetime) -> List[str]:
    """The MM-DD strings covered by "cette semaine", today included."""
    return [(at + timedelta(days=i)).strftime("%m-%d") for i in range(BIRTHDAY_DAYS)]


def audience(tid: str, segment: str, at: Optional[datetime] = None,
             mine: Optional[set] = None) -> List[Dict[str, Any]]:
    """The customers a segment names. Anything unknown is refused rather than
    quietly falling through to the whole client base — a mistyped segment must
    never message everybody."""
    at = at or _now()
    if segment not in SEGMENT_KEYS:
        raise HTTPException(status_code=400, detail=f"Segment inconnu : {segment}")

    q: Dict[str, Any] = {"tenant_id": tid}
    if segment == "birthday":
        q["birthday"] = {"$in": _birthday_window(at)}

    if mine is not None:
        q["id"] = {"$in": list(mine)}
    people = list(_db.customers.find(q, {"_id": 0}))
    # « Fidèles » and « Inactifs » are the Clients page's own — the shop's
    # Règles clients — so a campaign reaches exactly the people that page
    # lists under the same name (user, 2026-10-02).
    if segment in ("loyal", "inactive"):
        from features import clients_page as CP, customer_rules as R
        rules = R.load(tid)
        test = CP.is_loyal if segment == "loyal" else CP.is_inactive
        people = [c for c in people if test(c, at, rules)]
    return people


def segment_cards(tid: str) -> List[Dict[str, str]]:
    """The audience cards, their hints read from the shop's Règles clients."""
    from features import customer_rules as R
    days = R.active_days(R.load(tid))
    hints = {"inactive": f"Pas venus depuis {days} jours", "loyal": "Selon vos Règles clients"}
    return [{**s, "hint": hints.get(s["key"], s["hint"])} for s in SEGMENTS]


# ---------------------------------------------------------------------------
# The redesign's audience (step 3, 2026-10-10): every client, a segment, the
# clients picked one by one, or a radius around the shop — then the optional
# filters. One resolver for the live count, the preview and the send.
# ---------------------------------------------------------------------------
EXTRA_SEGMENTS = [("new", "Nouveaux clients", "Inscrits depuis moins de 30 jours")]


def _people(tid: str, mine: Optional[set]) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {"tenant_id": tid, "deleted_at": {"$exists": False}}
    if mine is not None:
        q["id"] = {"$in": list(mine)}
    return list(_db.customers.find(q, {"_id": 0}))


def segment_options(tid: str, at: datetime, mine: Optional[set]) -> List[Dict[str, Any]]:
    """« Segment de clients »: ours, then the shop's own from Segmentation."""
    out = [{"key": s["key"], "label": s["label"], "hint": s["hint"]}
           for s in segment_cards(tid) if s["key"] != "all"]
    out += [{"key": k, "label": label, "hint": hint} for k, label, hint in EXTRA_SEGMENTS]
    for doc in _db.saved_segments.find({"tenant_id": tid}, {"_id": 0, "id": 1, "name": 1}):
        out.append({"key": f"seg:{doc['id']}", "label": doc.get("name") or "Segment", "hint": "Segmentation"})
    for o in out:
        try:
            o["count"] = len(_segment_people(tid, o["key"], at, mine))
        except HTTPException:
            o["count"] = 0
    return out


def _segment_people(tid: str, key: str, at: datetime, mine: Optional[set]) -> List[Dict[str, Any]]:
    if key in SEGMENT_KEYS:
        return audience(tid, key, at, mine)
    if key == "new":
        return K.apply_filters(tid, _people(tid, mine), K.FiltersIn(new=True), at)
    if key.startswith("seg:"):
        from features import segmentation as SEG
        doc = _db.saved_segments.find_one({"id": key[4:], "tenant_id": tid}, {"_id": 0})
        if not doc:
            raise HTTPException(status_code=400, detail="Ce segment n'existe plus.")
        SEG.learn(tid, SEG._rules_of(doc))
        return SEG.evaluate(tid, SEG._rules_of(doc), _people(tid, mine), at=at)
    raise HTTPException(status_code=400, detail=f"Segment inconnu : {key}")


def _segment_label(tid: str, key: str) -> str:
    if key in SEGMENT_LABELS:
        return SEGMENT_LABELS[key]
    for k, label, _hint in EXTRA_SEGMENTS:
        if k == key:
            return label
    if key.startswith("seg:"):
        doc = _db.saved_segments.find_one({"id": key[4:], "tenant_id": tid}, {"_id": 0, "name": 1}) or {}
        return doc.get("name") or "Segment"
    return "Segment"


def _km(v: Any) -> str:
    return f"{float(v):g}".replace(".", ",")


def resolve_audience(tid: str, a: "K.AudienceIn", at: datetime,
                     mine: Optional[set]) -> Tuple[List[Dict[str, Any]], str]:
    if a.mode == "all":
        people, label = _people(tid, mine), "Tous les clients"
    elif a.mode == "segment":
        if not a.segment:
            raise HTTPException(status_code=400, detail="Choisissez un segment.")
        people, label = _segment_people(tid, a.segment, at, mine), f"Segment : {_segment_label(tid, a.segment)}"
    elif a.mode == "custom":
        ids = [i for i in (a.customer_ids or []) if mine is None or i in mine]
        if not ids:
            raise HTTPException(status_code=400, detail="Sélectionnez au moins un client.")
        people = list(_db.customers.find({"tenant_id": tid, "id": {"$in": ids},
                                          "deleted_at": {"$exists": False}}, {"_id": 0}))
        label = f"{len(people)} client{'s' if len(people) > 1 else ''} choisi{'s' if len(people) > 1 else ''}"
    elif a.mode == "zone":
        if a.km is None or not (0 < float(a.km) <= 500):
            raise HTTPException(status_code=400, detail="Choisissez un rayon entre 1 et 500 km.")
        people, _ = K.zone_people(tid, _people(tid, mine), float(a.km))
        label = f"À moins de {_km(a.km)} km"
    else:
        raise HTTPException(status_code=400, detail="Destinataires inconnus.")
    # « Tous les clients » means everyone: no filter applies (user, 2026-10-10)
    f = None if a.mode == "all" else a.filters
    if f and f.active and f.inactive:
        raise HTTPException(status_code=400, detail="« Clients actifs » et « Clients inactifs » ne peuvent pas être cochés ensemble.")
    if f and f.min_points is not None and not (0 <= int(f.min_points) <= 1_000_000):
        raise HTTPException(status_code=400, detail="Nombre de points minimum invalide.")
    people = K.apply_filters(tid, people, f, at)
    return people, label + K.filters_label(f)


def best_slot(tid: str) -> Optional[Dict[str, Any]]:
    """« Conseil FIDCLIC AI »: the busiest two hours (Paris, 90 days), when
    there are enough visits to say it (Insights' own reading)."""
    try:
        from features import insights_page as IP
        shop = IP.Shop(tid, _now(), None)
        hrs = IP._hours(shop)
    except Exception as exc:
        print(f"campagnes: best slot unavailable ({exc})")
        return None
    if not hrs:
        return None
    a, b = hrs["busy"]
    names = {range(5, 11): "Matin", range(11, 14): "Midi", range(14, 18): "Après-midi", range(18, 24): "Soir"}
    name = next((n for r, n in names.items() if int(a) in r), "Créneau")
    return {"from": f"{int(a):02d}:00", "to": f"{int(b):02d}:00", "label": f"{name} ({int(a):02d}:00 - {int(b):02d}:00)",
            "visits": hrs.get("visits"), "days": hrs.get("days")}


def _has_position(tid: str) -> bool:
    try:
        from features import geolocation as geo
        lat, lng, _ = geo._shop_position(_db.tenants.find_one({"id": tid}) or {})
        return lat is not None and lng is not None
    except Exception:
        return False


class PreviewIn(BaseModel):
    audience: K.AudienceIn
    exclude_ids: Optional[List[str]] = None


@router.post("/api/owner/campaigns/audience-preview")
def audience_preview(req: PreviewIn, request: Request = None,
                     token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """The live count of step 3, the clients of a zone (nearest first), and one
    real recipient to fill the phone preview's variables."""
    tid = token_data.tenant_id
    at = _now()
    # only the members of the establishment chosen in the menu (multi-store PR5)
    mine = S.home_customer_ids(S.resolve(token_data, request))
    people, label = resolve_audience(tid, req.audience, at, mine)
    from features.resend_guard import without
    people = without(people, req.exclude_ids)
    zone = None
    if req.audience.mode == "zone":
        from features import segmentation as SEG
        dist = SEG._distances(tid, people)
        zone = sorted(({"id": c["id"], "name": c.get("name") or "Client", "km": round(dist.get(c["id"]) or 0, 1)}
                       for c in people), key=lambda r: r["km"])[:300]
    names = None
    if req.audience.mode == "custom" and req.audience.customer_ids:
        # the chips of step 3 name the clients handed over by Insights / Clients
        want = [i for i in req.audience.customer_ids[:60] if mine is None or i in mine]
        names = {c["id"]: c.get("name") or "Client"
                 for c in _db.customers.find({"tenant_id": tid, "id": {"$in": want}}, {"_id": 0, "id": 1, "name": 1})}
    sample = None
    if people:
        c = people[0]
        try:
            import server as core
            ptnr = core._compute_points_to_next_reward(c, tid)
        except Exception:
            ptnr = 0
        tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "reward_description": 1}) or {}
        sample = {"first_name": (c.get("name") or "").split(" ")[0] or "Client", "points": int(c.get("points") or 0),
                  "visits": int(c.get("visits") or 0), "points_missing": ptnr,
                  "next_reward": tpl.get("reward_description") or "votre récompense"}
    return {"count": len(people), "label": label, "zone": zone, "sample": sample, "names": names,
            "ids": [c["id"] for c in people] if len(people) <= 5000 else None}


def _row(c: Dict[str, Any], tid: str, at: datetime) -> Dict[str, Any]:
    ids = list(c.get("recipient_ids") or [])
    sent_at = _aware(c.get("sent_at"))
    st = K.status_of(c, at)
    kind = c.get("kind")
    return {
        "id": c.get("id"), "name": c.get("name") or "Campagne",
        "kind": kind or "message", "type_label": K.KINDS.get(kind, K.LEGACY_LABEL),
        "recipients": len(ids) or int(c.get("targeted_count") or 0),
        "open_rate": _pct(len(_opened_ids(tid, ids, sent_at, c)), len(ids)) if c.get("status") == "sent" and ids and sent_at else None,
        "status": st, "status_label": STATUS_TEXT.get(st, K.STATUS_LABELS.get(st, st)),
        "sent_at": sent_at.isoformat() if sent_at else None,
        "scheduled_for": (d.isoformat() if (d := _aware(c.get("scheduled_for"))) else None),
        "created_at": (d.isoformat() if (d := _aware(c.get("created_at"))) else None),
        "terms": K.terms_label(c), "image_url": c.get("image_url"),
        "cancel_reason": c.get("cancel_reason"),
    }


STATUS_TEXT = dict(K.STATUS_LABELS)


@router.get("/api/owner/campaigns/list")
def list_campaigns(tab: str = "all", search: str = "", page: int = 1, per_page: int = 5, kind: str = "",
                   request: Request = None,
                   token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """« Vos campagnes récentes »: Toutes · En cours · Programmées · Terminées ·
    Annulées, newest first, searchable by name, five per page."""
    tid = token_data.tenant_id
    at = _now()
    if tab not in K.TABS:
        raise HTTPException(status_code=400, detail="Onglet inconnu.")
    per_page = max(1, min(int(per_page or 5), 50))
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    # the campaigns of the establishment chosen (an older one: if it reached its clients)
    docs = _limit(list(_db.campaigns.find({"tenant_id": tid}, {"_id": 0})), mine, scope)
    rows = [_row(c, tid, at) for c in docs]
    q = (search or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (r["name"] or "").lower()]
    if kind:
        # the funnel next to the search: one type (« message » = before the redesign)
        rows = [r for r in rows if r["kind"] == kind]
    counts = {t: 0 for t in K.TABS}
    for r in rows:
        counts["all"] += 1
        t = K.tab_of(r["status"])
        if t != "all":
            counts[t] += 1
    if tab != "all":
        rows = [r for r in rows if K.tab_of(r["status"]) == tab]

    def when(r):
        return r["sent_at"] or r["scheduled_for"] or r["created_at"] or ""
    rows.sort(key=when, reverse=True)
    total = len(rows)
    pages = max(1, -(-total // per_page))
    page = max(1, min(int(page or 1), pages))
    return {"rows": rows[(page - 1) * per_page: page * per_page], "total": total, "page": page,
            "pages": pages, "per_page": per_page, "counts": counts}


@router.get("/api/owner/campaigns/{campaign_id}/detail")
def campaign_detail(campaign_id: str, request: Request = None,
                    token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """A row of « Vos campagnes récentes » opened (user, 2026-10-10: a click
    always shows the campaign): what was said, to whom, when, and — once sent —
    what it did (opens, clicks, clients back within 15 days, their spend)."""
    tid = token_data.tenant_id
    at = _now()
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    found = _limit([c for c in [_db.campaigns.find_one({"tenant_id": tid, "id": campaign_id}, {"_id": 0})] if c], mine, scope)
    if not found:
        raise HTTPException(status_code=404, detail="Campagne introuvable.")
    c = found[0]
    row = _row(c, tid, at)
    ids = list(c.get("recipient_ids") or [])
    sent_at = _aware(c.get("sent_at"))
    stats = None
    if c.get("status") == "sent" and sent_at:
        opened = _opened_ids(tid, ids, sent_at, c)
        back = _db.visits.distinct("customer_id", {
            "tenant_id": tid, "customer_id": {"$in": ids},
            "visit_time": {"$gte": sent_at, "$lte": sent_at + timedelta(days=ATTRIBUTION_DAYS)},
            **S.visit_filter(scope)}) if ids else []
        delivered = int(c.get("delivered_count") or 0)
        stats = {"recipients": len(ids), "delivered": min(delivered, len(ids)) if delivered else None,
                 "opened": len(opened), "open_rate": _pct(len(opened), len(ids)),
                 "clicks": CF.clicks(c), "came_back": len(back),
                 "came_back_rate": _pct(len(back), len(ids)),
                 "revenue": CF.attribution(_db, tid, [c], S.visit_filter(scope))[c["id"]]["revenue"],
                 "window_days": ATTRIBUTION_DAYS, "open_window_h": OPEN_WINDOW_H}
    _, until = K.window(c) if sent_at else (None, None)
    st = row["status"]
    # To whom, by name, and by whom (user, 2026-10-20: « campaign ki details mein
    # ye kyun nhi dekh paa rhe ki kisko target kiya gaya tha »)
    shown = ids[:RECIPIENTS_SHOWN]
    names = {p["id"]: p for p in _db.customers.find({"tenant_id": tid, "id": {"$in": shown}},
                                                    {"_id": 0, "id": 1, "name": 1, "barcode_id": 1})}
    recipients_list = [{"id": i, "name": (names.get(i) or {}).get("name") or "Client supprimé",
                        "barcode_id": (names.get(i) or {}).get("barcode_id")} for i in shown]
    return {**row, "recipients_list": recipients_list, "recipients_more": max(0, len(ids) - len(shown)),
            "sent_by_label": _sender_label(tid, c), "title": c.get("name") or "", "message": c.get("content") or "", "details": c.get("details"),
            "link_url": safe_link(c.get("link_url")), "audience_label": c.get("audience_label") or "Sélection",
            "discount": K.discount_label(c.get("offer")) if c.get("kind") in K.OFFER_KINDS else None,
            "live_until": until.isoformat() if until else None,
            "cancelled_at": (d.isoformat() if (d := _aware(c.get("cancelled_at"))) else None),
            "stats": stats,
            "can_edit": st in ("draft", "scheduled", "cancelled"), "can_cancel": st == "scheduled",
            "can_delete": st in ("draft", "cancelled")}


RECIPIENTS_SHOWN = 50


def _sender_label(tid: str, c: Dict[str, Any]) -> Optional[str]:
    """« Envoyée par »: the team member's name and role, « Super admin FidClic »
    when sent from « Accéder au compte », and FidClic IA when it proposed it."""
    if c.get("sent_by_admin"):
        who = "Super admin FidClic"
    elif c.get("sent_by"):
        u = _db.users.find_one({"email": c["sent_by"]}, {"_id": 0, "hashed_password": 0}) or {}
        if u and u.get("tenant_id") in (tid, None):
            from features import team_access as TA
            role = TA.role_label(u)
            who = TA._display_name(u) + (f" ({role})" if role else "")
        else:
            who = c["sent_by"]
    else:
        return None
    return who + (" — proposée par FidClic IA" if c.get("autopilot_id") else "")


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------
def _opened_ids(tid: str, recipients: List[str], sent_at: datetime,
                campaign: Optional[Dict[str, Any]] = None) -> set:
    """Recipients who opened: their card within OPEN_WINDOW_H of the send, the
    campaign itself (offers feed, « Voir l'offre » in Wallet), or its link —
    one definition with the Automatisations page (services/card_opens)."""
    from services import card_opens
    return card_opens.opened_ids(_db, tid, recipients, sent_at, campaign, OPEN_WINDOW_H)


def _pct(part: float, whole: float) -> int:
    return round(part / whole * 100) if whole else 0


def _limit(rows: List[Dict[str, Any]], mine: Optional[set], scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    """The campaigns of the establishment chosen in the menu: those it sent
    (store_ids, multi-store PR5); older ones, sent for the whole shop, count
    for the clients of its establishments only."""
    if mine is None:
        return rows
    out = []
    for c in rows:
        if c.get("store_ids") and scope is not None and not scope.is_all:
            if set(c["store_ids"]) & set(scope.ids or []):
                out.append(c)
            continue
        ids = [i for i in c.get("recipient_ids") or [] if i in mine]
        if ids:
            out.append({**c, "recipient_ids": ids, "delivered_count": min(int(c.get("delivered_count") or 0), len(ids)),
                        "targeted_count": len(ids)})
    return out


def _sent_between(tid: str, start: datetime, end: datetime, mine: Optional[set] = None,
                  scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    rows = list(_db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}))
    return _limit([c for c in rows
                   if (d := _aware(c.get("sent_at"))) and start <= d <= end], mine, scope)


def _totals(tid: str, rows: List[Dict[str, Any]], scope: Optional["S.Scope"] = None) -> Dict[str, float]:
    reach = opened = clicks = 0
    att = CF.attribution(_db, tid, rows, S.visit_filter(scope) if scope else None)
    for c in rows:
        ids = list(c.get("recipient_ids") or [])
        at = _aware(c.get("sent_at"))
        reach += len(ids)
        opened += len(_opened_ids(tid, ids, at, c))
        clicks += CF.clicks(c)
    revenue = sum(a["revenue"] for a in att.values())
    return {"campaigns": len(rows), "reach": reach, "opened": opened,
            "clicks": clicks, "revenue": round(revenue, 2)}


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
@router.get("/api/owner/campaigns/page")
def page(request: Request = None,
         token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    tid = token_data.tenant_id
    at = _now()
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    # « vs. mois précédent »: this calendar month so far vs the whole last month
    # (Paris), as the user chose for the redesign (2026-10-10)
    start, prev_start, _ = K.month_bounds(at)

    now_rows = _sent_between(tid, start, at, mine, scope)
    prev_rows = _sent_between(tid, prev_start, start, mine, scope)
    cur, was = _totals(tid, now_rows, scope), _totals(tid, prev_rows, scope)

    strip = [
        {"key": "sent", "label": "Campagnes envoyées", "icon": "send",
         "value": cur["campaigns"], "delta_pct": _delta(cur["campaigns"], was["campaigns"])},
        {"key": "reach", "label": "Clients touchés", "icon": "users",
         "value": cur["reach"], "delta_pct": _delta(cur["reach"], was["reach"])},
        {"key": "open_rate", "label": "Taux d'ouverture", "icon": "mail", "unit": "%",
         "value": _pct(cur["opened"], cur["reach"]),
         "delta_pct": _delta(_pct(cur["opened"], cur["reach"]), _pct(was["opened"], was["reach"]))},
        {"key": "clicks", "label": "Clics générés", "icon": "chart",
         "value": cur["clicks"], "delta_pct": _delta(cur["clicks"], was["clicks"])},
        {"key": "revenue", "label": "CA généré", "icon": "euro", "unit": "€",
         "value": cur["revenue"], "delta_pct": _delta(cur["revenue"], was["revenue"])},
    ]

    segments = []
    for s in segment_cards(tid):
        segments.append({**s, "count": len(audience(tid, s["key"], at, mine))})

    recent = []
    for c in sorted(_limit(list(_db.campaigns.find({"tenant_id": tid}, {"_id": 0})), mine, scope),
                    key=lambda c: _aware(c.get("sent_at")) or _aware(c.get("created_at")) or at,
                    reverse=True)[:8]:
        ids = list(c.get("recipient_ids") or [])
        sent_at = _aware(c.get("sent_at"))
        res = None
        if c.get("status") == "sent" and ids and sent_at:
            try:
                from features.campaign_learning import measure
                res = measure(tid, c, at)
            except Exception as exc:
                print(f"campagnes: result unavailable ({exc})")
        recent.append({
            "id": c.get("id"),
            # What it did: clients back vs expected (features/campaign_learning.py).
            "result": res,
            "name": c.get("name") or "Campagne",
            "subtitle": (c.get("content") or "")[:60],
            "image_url": c.get("image_url"),
            "audience": c.get("audience_label") or SEGMENT_LABELS.get(c.get("segment") or "", "Sélection"),
            "audience_count": len(ids) or int(c.get("targeted_count") or 0),
            # Only a sent campaign has been sent or opened (QA F03: a draft
            # showed « Envoyées 3 » and « 0 % » — its audience, not a send).
            "sent": (int(c.get("delivered_count") or 0) or len(ids)) if c.get("status") == "sent" else None,
            "open_rate": _pct(len(_opened_ids(tid, ids, sent_at, c)), len(ids)) if c.get("status") == "sent" else None,
            "status": c.get("status") or "draft",
            "sent_at": sent_at.isoformat() if sent_at else None,
            "scheduled_for": (d.isoformat() if (d := _aware(c.get("scheduled_for"))) else None),
        })

    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1, "campaign_sender_name": 1}) or {}
    card = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0, "logo_url": 1, "brand_fields.logo_url": 1}) or {}
    return {
        # The phone preview signs the notification with the name the customer
        # will actually see, not a placeholder.
        "tenant_name": tenant.get("campaign_sender_name") or tenant.get("name") or "FidClic",
        # Apple Wallet signs its alert with the card's name and logo.
        "wallet_name": tenant.get("name") or "FidClic",
        "logo_url": (card.get("brand_fields") or {}).get("logo_url") or card.get("logo_url") or "",
        "strip": strip,
        "segments": segments,
        "recent": recent,
        "limits": {"title": TITLE_MAX, "message": MESSAGE_MAX},
        "open_note": f"Une ouverture = la carte ouverte dans les {OPEN_WINDOW_H} h suivant l'envoi, l'offre "
                     "ouverte (« Voir l'offre » dans le Wallet) ou son lien cliqué. Une notification wallet "
                     "ne renvoie pas d'accusé de lecture : un client qui regarde seulement la carte dans "
                     "Apple Wallet ou Google Wallet n'est pas compté.",
        "revenue_note": CF.REVENUE_NOTE,
        "empty": not recent,
        "scope": scope.describe(),
        # the redesign's wizard: segments to pick from, the best time to send,
        # whether « Zone géographique » can work (the shop's position)
        "segment_options": segment_options(tid, at, mine),
        "best_slot": best_slot(tid),
        "kinds": [{"key": k, "label": v} for k, v in K.KINDS.items()],
        "has_position": _has_position(tid),
        "month_label": "vs. mois précédent",
    }


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
class Compose(BaseModel):
    title: str
    message: str
    segment: str = "all"
    customer_ids: Optional[List[str]] = None
    # Clients the owner chose not to message again (« Déjà contactés »,
    # features/resend_guard.py).
    exclude_ids: Optional[List[str]] = None
    image_url: Optional[str] = None
    link_url: Optional[str] = None
    schedule_at: Optional[str] = None
    push: bool = True
    wallet: bool = True
    # the photo on the Wallet card too, while the campaign runs (QA BUG-006,
    # user 2026-10-13: the owner chooses; off by default — « Mes offres » then)
    wallet_photo: bool = False
    draft: bool = False
    # Reprendre un brouillon (QA F02): the draft this save / send replaces —
    # saved again, scheduled or sent, it stays one campaign.
    draft_id: Optional[str] = None
    # Which recommendation this campaign came from (Insights, Segmentation,
    # FidClic IA). Recorded so the recommendation can step aside once it has
    # been used, and something new can take its place.
    template: Optional[str] = None
    # The redesign (2026-10-10): the kind and its step-1 terms, the details
    # shown on the card, and the audience as chosen in step 3.
    kind: Optional[str] = None
    offer: Optional[K.OfferIn] = None
    event: Optional[K.EventIn] = None
    defi: Optional[K.DefiIn] = None
    details: Optional[str] = None
    audience: Optional[K.AudienceIn] = None
    # One key per wizard (user, 2026-10-20: « aisa toh nhi n ki … waapis chala
    # jaaye »): « Envoyer » pressed again after an error that came back late —
    # the send had in fact left — returns that campaign instead of a second one.
    send_key: Optional[str] = None
    # « Sur la carte jusqu'au » for a campaign with no date of its own (a
    # Nouveauté). An offer's end, an event's day and a défi's end are theirs.
    visible_until: Optional[str] = None


def _clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


_LINK = re.compile(r"^https?://[^\s/?#]+\.[^\s/?#]{2,}(?:[/?#]\S*)?$", re.I)


def clean_link(raw: Optional[str]) -> Optional[str]:
    """The campaign's « Ajouter un lien » (QA UX09: « not-a-url » was saved).

    A web address or nothing: « monsite.fr/menu » gets its https://, anything
    else — a sentence, javascript:, a phone number — is refused with a
    sentence the owner understands. The customer's card opens this link, so
    only http(s) ever reaches it."""
    s = (raw or "").strip()
    if not s:
        return None
    if not re.match(r"^[a-z][a-z0-9+.-]*:", s, re.I):
        s = "https://" + s.lstrip("/")
    if not _LINK.match(s) or len(s) > 500:
        raise HTTPException(status_code=400, detail="Lien invalide : saisissez une adresse web, par exemple https://monsite.fr.")
    return s


def safe_link(raw: Optional[str]) -> Optional[str]:
    """A stored link the customer's card may open: http(s) only, else none."""
    s = (raw or "").strip()
    return s if _LINK.match(s) else None


# What can still be changed: a draft, and a planned campaign not yet sent
# (user, 2026-10-08: « planifiée ko cancel ya edit karne ka button »).
EDITABLE = ("draft", "scheduled", "cancelled")


def _own_draft(tid: str, draft_id: str, allow: Tuple[str, ...] = EDITABLE) -> Dict[str, Any]:
    doc = _db.campaigns.find_one({"id": draft_id, "tenant_id": tid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Brouillon introuvable.")
    if doc.get("status") not in allow:
        raise HTTPException(status_code=409, detail="Cette campagne est déjà partie : elle ne peut plus être modifiée."
                            if doc.get("status") in ("sent", "sending") else "Cette campagne n'est plus un brouillon.")
    return doc


@router.get("/api/owner/campaigns/drafts/{draft_id}")
def get_draft(draft_id: str, token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """« Reprendre » a draft (QA F02) or « Modifier » a planned campaign:
    what the composer needs to open it."""
    d = _own_draft(token_data.tenant_id, draft_id)
    when = _aware(d.get("scheduled_for")) if d.get("status") == "scheduled" else None
    custom = d.get("segment") == "custom"
    return {
        "id": d["id"], "title": d.get("name") or "", "message": d.get("content") or "",
        "segment": "all" if custom else (d.get("segment") or "all"),
        # a hand-picked list (Clients, Insights) stays that list
        "audience": {"label": d.get("audience_label") or "Sélection", "ids": list(d.get("recipient_ids") or [])}
        if custom else None,
        "image_url": d.get("image_url") or "", "link_url": d.get("link_url") or "",
        "push": bool((d.get("channels") or {}).get("push", True)),
        "wallet": bool((d.get("channels") or {}).get("wallet", True)),
        "wallet_photo": bool(d.get("wallet_photo")),
        "template": d.get("template"),
        "visible_until": d.get("visible_until"),
        "status": d.get("status"),
        "scheduled_for": when.isoformat() if when else None,
        "kind": d.get("kind"), "offer": d.get("offer"), "event": d.get("event"), "defi": d.get("defi"),
        "details": d.get("details") or "", "audience_spec": d.get("audience_spec"),
    }


@router.post("/api/owner/campaigns/drafts/{draft_id}/cancel-schedule")
def cancel_schedule(draft_id: str, token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """« Annuler l'envoi »: the planned campaign does not leave. It is listed
    under « Annulées » (redesign, 2026-10-10), its message kept: « Modifier »
    plans or sends it again, « Supprimer » removes it."""
    _own_draft(token_data.tenant_id, draft_id, allow=("scheduled",))
    done = _db.campaigns.update_one({"id": draft_id, "tenant_id": token_data.tenant_id, "status": "scheduled"},
                                    {"$set": {"status": "cancelled", "cancelled_at": _now()}})
    if not getattr(done, "modified_count", 0):                 # the cron took it in between
        raise HTTPException(status_code=409, detail="Cette campagne est déjà partie : elle ne peut plus être annulée.")
    return {"id": draft_id, "status": "cancelled"}


@router.delete("/api/owner/campaigns/drafts/{draft_id}")
def delete_draft(draft_id: str, token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """« Supprimer » a draft (QA F02). Only drafts: what was sent is history,
    and a planned one is cancelled first (« Annuler l'envoi »)."""
    _own_draft(token_data.tenant_id, draft_id, allow=("draft", "cancelled"))
    _db.campaigns.delete_one({"id": draft_id, "tenant_id": token_data.tenant_id, "status": {"$in": ["draft", "cancelled"]}})
    return {"deleted": True}


@router.post("/api/owner/campaigns/compose")
def compose(req: Compose, request: Request = None,
            token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """Create the campaign, then save it, schedule it or send it.

    One endpoint rather than three so the audience is resolved once: the count
    the merchant approved on screen is the count that is written to the
    campaign, whatever happens next.
    """
    tid = token_data.tenant_id
    title, message = _clean(req.title, TITLE_MAX), _clean(req.message, MESSAGE_MAX)
    if not title or not message:
        raise HTTPException(status_code=400, detail="Un titre et un message sont nécessaires.")
    if not req.push and not req.wallet and not req.draft:
        raise HTTPException(status_code=400, detail="Choisissez au moins un canal.")
    link = clean_link(req.link_url)
    send_key = re.sub(r"[^A-Za-z0-9-]", "", req.send_key or "")[:64] or None
    if send_key and not req.draft:
        already = _db.campaigns.find_one({"tenant_id": tid, "send_key": send_key,
                                          "status": {"$in": ["sent", "sending", "scheduled"]}}, {"_id": 0})
        if already:
            return {"id": already["id"], "status": "scheduled" if already["status"] == "scheduled" else "sent",
                    "audience": len(already.get("recipient_ids") or []), "already": True,
                    "scheduled_for": (d.isoformat() if (d := _aware(already.get("scheduled_for"))) else None)}
    previous = _own_draft(tid, req.draft_id) if req.draft_id else None

    at = _now()
    # each establishment writes to its own members (multi-store PR5)
    scope = S.sending_scope(token_data, request)
    mine = S.home_customer_ids(scope)
    when_req = _aware(req.schedule_at)
    send_at = when_req if (when_req and when_req > at and not req.draft) else at
    # the kind and its terms (step 1), checked against the moment it leaves
    kind = K.clean_kind(req.kind)
    terms: Dict[str, Any] = {"offer": None, "event": None, "defi": None}
    if kind == "offre":
        terms["offer"] = K.clean_offer(req.offer, send_at)
    elif kind == "configurer":
        # no discount here: a title, a description, and its dates when it has some
        terms["offer"] = K.clean_offer(req.offer.model_copy(update={"discount_type": None, "discount_value": None})
                                       if req.offer else None, send_at)
    elif kind == "evenement":
        terms["event"] = K.clean_event(req.event, send_at)
    elif kind == "defi":
        terms["defi"] = K.clean_defi(req.defi, send_at)
    details = re.sub(r"[ \t]+", " ", (req.details or "").strip())[:500] or None
    visible_until = None
    if kind not in K.OFFER_KINDS and kind not in ("evenement", "defi"):
        until_day = K._day(req.visible_until, "Date « Sur la carte jusqu'au »")
        if until_day and until_day < send_at.astimezone(K.PARIS).date():
            raise HTTPException(status_code=400, detail="La date « Sur la carte jusqu'au » est avant l'envoi.")
        visible_until = until_day.isoformat() if until_day else None
    if req.audience is not None:
        people, label = resolve_audience(tid, req.audience, at, mine)
    elif req.customer_ids:
        ids = [i for i in req.customer_ids if mine is None or i in mine]
        people = list(_db.customers.find({"tenant_id": tid, "id": {"$in": ids}}, {"_id": 0}))
        label = f"{len(people)} client{'s' if len(people) > 1 else ''}"
    else:
        people = audience(tid, req.segment, at, mine)
        label = SEGMENT_LABELS.get(req.segment, "Sélection")
    if not people and not req.draft and not req.exclude_ids:
        raise HTTPException(status_code=400, detail="Aucun client ne correspond à ces destinataires.")
    from features.resend_guard import without
    people = without(people, req.exclude_ids)
    if not people and not req.draft and req.exclude_ids:
        raise HTTPException(status_code=400, detail="Aucun client à contacter : tous ont été retirés de l'envoi.")
    if mine is not None and not people and not req.draft:
        raise HTTPException(status_code=400, detail="Aucun client à contacter dans vos établissements.")

    from services import client_status as _CS
    people = _CS.drop_paused(_db, tid, people)       # paused by the business: not in the audience
    when = _aware(req.schedule_at)
    status = "draft" if req.draft else ("scheduled" if when and when > at else "sent")

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "name": title,
        "content": message,
        "status": status,
        "source": "push",
        "segment": ("custom" if (req.customer_ids or (req.audience and req.audience.mode != "all")) else req.segment),
        "audience_label": label,
        "image_url": req.image_url or None,
        "link_url": link,
        "channels": {"push": bool(req.push), "wallet": bool(req.wallet)},
        "recipient_ids": [c["id"] for c in people],
        "targeted_count": len(people),
        "delivered_count": 0,
        "opens": 0, "opens_unique": 0, "offer_clicks": 0, "offer_clicks_unique": 0,
        "visits_from_campaign": 0,
        "filters": {},
        "created_at": at,
        "sent_at": None,
        "scheduled_for": when if status == "scheduled" else None,
        # How long this stays the card's current offer once sent. Read by the
        # wallet pass builder, so the pass and the web card agree.
        "wallet_offer": bool(req.wallet),
        "wallet_photo": bool(req.wallet_photo and req.image_url),
        "template": (req.template or "").strip()[:40] or None,
        "kind": kind, **terms, "details": details, "visible_until": visible_until,
        "audience_spec": req.audience.dict() if req.audience is not None else None,
        # For which establishments it was sent (None = the whole shop), and by whom.
        "store_ids": scope.ids,
        "sent_by": getattr(token_data, "email", None),
        # « Accéder au compte »: the token's email is the owner's — keep who really sent it
        "sent_by_admin": getattr(token_data, "view_by", None),
        "send_key": send_key,
    }

    if previous:                                   # the draft becomes this campaign
        doc["id"] = previous["id"]
        doc["created_at"] = previous.get("created_at") or at

    def save():
        if previous:
            # only while still a draft / planned: the cron may have sent it meanwhile
            done = _db.campaigns.replace_one({"id": doc["id"], "tenant_id": tid, "status": {"$in": list(EDITABLE)}},
                                             dict(doc))
            if not getattr(done, "matched_count", 1):
                raise HTTPException(status_code=409, detail="Cette campagne est déjà partie : elle ne peut plus être modifiée.")
        else:
            _db.campaigns.insert_one(dict(doc))

    if status != "sent":
        save()
        return {"id": doc["id"], "status": status, "audience": len(people),
                "scheduled_for": when.isoformat() if when else None}

    # Saved as sent BEFORE delivering: _deliver() wakes the Wallet passes, and
    # an iPhone fetches its new pass within seconds. The pass builder reads the
    # campaign from the database (wallet_passes._attach_campaign_offer); saved
    # after, the pass came back unchanged and Wallet raised no notification
    # (user, 2026-10-04 — the offer only appeared later, silently).
    doc["sent_at"] = at
    save()
    result = _deliver(tid, doc, people)
    _db.campaigns.update_one({"id": doc["id"]}, {"$set": {"delivered_count": result["delivered"]}})
    return {"id": doc["id"], "status": "sent", "audience": len(people), **result}


def _deliver(tid: str, doc: Dict[str, Any], people: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Write the offer to every card, push it, then wake the wallet passes.

    The card feed is written first and unconditionally: a customer who never
    allowed push must still find the offer when they open their card. The push
    and the wallet wake-up are best-effort on top of that — one customer's
    dead subscription must not stop the rest of the send.
    """
    from services import client_status as _CS
    people = _CS.drop_paused(_db, tid, people)       # paused since it was planned: skipped
    delivered = 0
    sent_at = doc["sent_at"]
    try:
        import server as core
    except Exception:
        core = None
    tenant = _db.tenants.find_one({"id": tid}) or {}
    # A send that stopped half-way is retried by the cron: whoever already
    # has this campaign on their card is not messaged a second time.
    reached = set(_db.push_notifications.distinct("customer_id", {"tenant_id": tid, "campaign_id": doc["id"]}))
    people = [c for c in people if c.get("id") not in reached]

    for cust in people:
        title, message = doc["name"], doc["content"]
        if core and hasattr(core, "render_template"):
            try:
                title = core.render_template(doc["name"], cust, tenant)
                message = core.render_template(doc["content"], cust, tenant)
            except Exception:
                pass
        try:
            _db.push_notifications.insert_one({
                "customer_id": cust["id"], "tenant_id": tid, "campaign_id": doc["id"],
                "title": title, "body": message, "image_url": doc.get("image_url"),
                "link_url": doc.get("link_url"), "type": "campaign", "sent_at": sent_at,
            })
        except Exception as exc:
            print(f"campagnes: card feed write failed for {cust.get('id')}: {exc}")
        if doc["channels"]["push"] and core and hasattr(core, "dispatch_to_customer"):
            try:
                if core.dispatch_to_customer(tid, cust, title, message, kind="campaign")["sent"]:
                    delivered += 1
            except Exception as exc:
                print(f"campagnes: push failed for {cust.get('id')}: {exc}")

    woken = 0
    if doc["channels"]["wallet"]:
        try:
            from features.wallet_passes import notify_passes
            serials = [c.get("barcode_id") for c in people if c.get("barcode_id")]
            woken = int((notify_passes(serials, google_notify="campaign") or {}).get("sent") or 0)
        except Exception as exc:
            print(f"campagnes: wallet wake-up failed: {exc}")

    return {"delivered": delivered, "wallet_woken": woken, "reach": len(people)}


def run_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Send the campaigns whose scheduled time has come. Called every minute
    (/api/cron/campaigns-due) and by the tick; safe to call twice — a
    campaign leaves `scheduled` before it sends."""
    at = now or _now()
    out = {"sent": 0, "recipients": 0}
    from features import plan_limits
    for doc in list(_db.campaigns.find({"status": "scheduled"}, {"_id": 0})):
        when = _aware(doc.get("scheduled_for"))
        if not when or when > at:
            continue
        if not plan_limits.allows_tenant(doc.get("tenant_id"), "campaigns"):
            continue                    # Campagnes no longer in the plan: it will show as « non envoyée »
        _, until = K.window({**doc, "sent_at": at})
        if doc.get("kind") and until and until < at:
            # its offer / event / défi ended before it could leave
            _db.campaigns.update_one({"id": doc["id"], "status": "scheduled"},
                                     {"$set": {"status": "cancelled", "cancelled_at": at,
                                               "cancel_reason": "Terminée avant son envoi"}})
            continue
        claimed = _db.campaigns.update_one(
            {"id": doc["id"], "status": "scheduled"}, {"$set": {"status": "sending"}})
        if not getattr(claimed, "modified_count", 1):
            continue
        people = list(_db.customers.find(
            {"tenant_id": doc["tenant_id"], "id": {"$in": list(doc.get("recipient_ids") or [])}},
            {"_id": 0}))
        doc["sent_at"] = at
        doc.setdefault("channels", {"push": True, "wallet": True})
        # Sent first, then delivered — the passes it wakes must find it (see compose).
        _db.campaigns.update_one({"id": doc["id"]}, {"$set": {"status": "sent", "sent_at": at}})
        try:
            res = _deliver(doc["tenant_id"], doc, people)
        except Exception as exc:                       # one tenant must not stop the cron
            print(f"campagnes: scheduled send failed for {doc['id']}: {exc}")
            _db.campaigns.update_one({"id": doc["id"]}, {"$set": {"status": "scheduled", "sent_at": None}})
            continue
        _db.campaigns.update_one({"id": doc["id"]}, {"$set": {"delivered_count": res["delivered"]}})
        out["sent"] += 1
        out["recipients"] += res["reach"]
    return out


# ---------------------------------------------------------------------------
# The assistant
# ---------------------------------------------------------------------------
class Draft(BaseModel):
    objective: str
    segment: Optional[str] = "all"


EXAMPLES = [
    "Faire revenir les clients inactifs",
    "Promouvoir une offre spéciale",
    "Anniversaire client",
    "Augmenter la fréquentation en magasin",
]

_SYSTEM = (
    "Tu écris des notifications push pour le programme de fidélité d'un commerce français. "
    f"Réponds en français, sur deux lignes exactement.\n"
    f"Ligne 1 : TITRE: un titre accrocheur de {TITLE_MAX} caractères maximum.\n"
    f"Ligne 2 : MESSAGE: un message de {MESSAGE_MAX} caractères maximum, chaleureux et concret.\n"
    "Pas de guillemets, pas d'explication, pas de hashtag. Un emoji au maximum."
)


def _parse(raw: str) -> Tuple[str, str]:
    """Pull a title and a message out of whatever the model actually wrote.

    Models ignore the format often enough that refusing on the first
    unlabelled answer would make the button feel broken. So: labelled lines
    first, then any loose lines, and finally — when the answer came back as
    one block — the first sentence becomes the title and the rest the message.
    Nothing is invented; the text is the model's own, only apportioned.
    """
    title = message = ""
    loose: List[str] = []
    for line in (raw or "").splitlines():
        line = line.strip().lstrip("-•*# ").strip().strip('"')
        low = line.lower()
        if low.startswith("titre"):
            title = line.split(":", 1)[-1].strip().strip('"')
        elif low.startswith("message"):
            message = line.split(":", 1)[-1].strip().strip('"')
        elif line:
            loose.append(line)
    if not title and loose:
        title = loose.pop(0)
    if not message and loose:
        message = " ".join(loose)
    if title and not message:
        head, sep, tail = title.partition(". ")
        if sep and tail.strip():
            title, message = head, tail
        else:
            message = title
    return _clean(title, TITLE_MAX), _clean(message, MESSAGE_MAX)


@router.post("/api/owner/campaigns/ai-draft")
def ai_draft(req: Draft,
             token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """Turn the merchant's objective into a title and a message.

    The model only ever writes the two strings; it never picks the audience
    and never sends anything. If it is unavailable the merchant is told so
    plainly and the composer stays exactly as they left it — a fabricated
    message would be worse than none.
    """
    objective = _clean(req.objective, 200)
    if not objective:
        raise HTTPException(status_code=400, detail="Décrivez votre objectif en une phrase.")

    tenant = _db.tenants.find_one({"id": token_data.tenant_id}) or {}
    who = SEGMENT_LABELS.get(req.segment or "all", "vos clients")
    user = (f"Commerce : {tenant.get('name') or 'un commerce'}. "
            f"Audience : {who}. Objectif : {objective}.")
    # What this shop's own campaigns taught (features/campaign_learning.py):
    # the IA writes in the style that brought clients back here.
    try:
        from features.campaign_learning import prompt_hints
        hints = prompt_hints(token_data.tenant_id)
        if hints:
            user += " " + hints
    except Exception as exc:
        print(f"campagnes: learning hints unavailable ({exc})")
    try:
        from services import llm
        # Say which of the two it is: "reformulez" is the wrong advice when the
        # real answer is that no provider key is set on this deployment.
        if llm._force_complete is None and not llm.is_configured():
            raise HTTPException(
                status_code=503,
                detail="L'assistant n'est pas configuré sur cette installation.")
        raw = llm.complete(_SYSTEM, user, max_tokens=180, temperature=0.7)
    except HTTPException:
        raise
    except Exception as exc:
        print(f"campagnes: ai-draft failed ({exc})")
        raise HTTPException(status_code=503,
                            detail="L'assistant n'est pas disponible pour le moment.")
    title, message = _parse(raw or "")
    if not title or not message:
        raise HTTPException(status_code=503,
                            detail="L'assistant n'a pas pu rédiger ce message. Reformulez votre objectif.")
    return {"title": title, "message": message, "examples": EXAMPLES}
