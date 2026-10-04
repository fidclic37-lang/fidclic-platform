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
    send. It is an association, not a proof, and it carries its own note.

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

# Campaigns are the owner's, an administrateur's (its establishments) and a
# manager's (its establishment) — each reaches only its own clients.
SENDERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["campagnes"])
_db = None

INACTIVE_DAYS = 30          # "Clients inactifs · Plus de 30 jours"
LOYAL_VISITS = 3            # "Clients fidèles · Plus de 3 achats" — strictly more
BIRTHDAY_DAYS = 7           # "Anniversaire · Cette semaine"
OPEN_WINDOW_H = 72          # a card opened this long after a send counts as an open
ATTRIBUTION_DAYS = 15       # a visit inside this window counts for the campaign
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
# Rates
# ---------------------------------------------------------------------------
def _opened_ids(tid: str, recipients: List[str], sent_at: datetime) -> set:
    """Recipients who opened their card inside OPEN_WINDOW_H of the send.

    `card_opens` carries one row per customer per day, written when the card
    is fetched. It is the only signal we have: a wallet push returns no read
    receipt, so this is what "ouverture" can honestly mean here.
    """
    if not recipients or not sent_at:
        return set()
    rows = _db.card_opens.find(
        {"tenant_id": tid, "customer_id": {"$in": recipients},
         "at": {"$gte": sent_at, "$lte": sent_at + timedelta(hours=OPEN_WINDOW_H)}},
        {"_id": 0, "customer_id": 1})
    return {r["customer_id"] for r in rows}


def _attributed_revenue(tid: str, recipients: List[str], sent_at: datetime,
                        scope: Optional["S.Scope"] = None) -> float:
    if not recipients or not sent_at:
        return 0.0
    rows = _db.visits.find(
        {"tenant_id": tid, "customer_id": {"$in": recipients},
         "visit_time": {"$gte": sent_at, "$lte": sent_at + timedelta(days=ATTRIBUTION_DAYS)},
         **(S.visit_filter(scope) if scope else {})},
        {"_id": 0, "amount_paid": 1})
    return round(sum(float(r.get("amount_paid") or 0) for r in rows), 2)


def _pct(part: float, whole: float) -> int:
    return round(part / whole * 100) if whole else 0


def _limit(rows: List[Dict[str, Any]], mine: Optional[set]) -> List[Dict[str, Any]]:
    """For an administrateur or a manager, a campaign counts for the clients of
    its establishments only; one that reached none of them is not shown."""
    if mine is None:
        return rows
    out = []
    for c in rows:
        ids = [i for i in c.get("recipient_ids") or [] if i in mine]
        if ids:
            out.append({**c, "recipient_ids": ids, "delivered_count": min(int(c.get("delivered_count") or 0), len(ids)),
                        "targeted_count": len(ids)})
    return out


def _sent_between(tid: str, start: datetime, end: datetime, mine: Optional[set] = None) -> List[Dict[str, Any]]:
    rows = list(_db.campaigns.find({"tenant_id": tid, "status": "sent"}, {"_id": 0}))
    return _limit([c for c in rows
                   if (d := _aware(c.get("sent_at"))) and start <= d <= end], mine)


def _totals(tid: str, rows: List[Dict[str, Any]], scope: Optional["S.Scope"] = None) -> Dict[str, float]:
    reach = opened = clicks = 0
    revenue = 0.0
    for c in rows:
        ids = list(c.get("recipient_ids") or [])
        at = _aware(c.get("sent_at"))
        reach += len(ids)
        opened += len(_opened_ids(tid, ids, at))
        clicks += int(c.get("offer_clicks") or 0)
        revenue += _attributed_revenue(tid, ids, at, scope)
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
    start, prev_start = at - timedelta(days=30), at - timedelta(days=60)

    now_rows = _sent_between(tid, start, at, mine)
    prev_rows = _sent_between(tid, prev_start, start, mine)
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
    for c in sorted(_limit(list(_db.campaigns.find({"tenant_id": tid}, {"_id": 0})), mine),
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
            "sent": int(c.get("delivered_count") or 0) or len(ids),
            "open_rate": _pct(len(_opened_ids(tid, ids, sent_at)), len(ids)),
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
        "open_note": f"Une ouverture = la carte ouverte dans les {OPEN_WINDOW_H} h suivant l'envoi. "
                     "Une notification wallet ne renvoie pas d'accusé de lecture.",
        "revenue_note": f"Le CA généré est la dépense des destinataires dans les "
                        f"{ATTRIBUTION_DAYS} jours suivant l'envoi.",
        "empty": not recent,
        "scope": scope.describe(),
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
    draft: bool = False
    # Which recommendation this campaign came from (Insights, Segmentation,
    # FidClic IA). Recorded so the recommendation can step aside once it has
    # been used, and something new can take its place.
    template: Optional[str] = None


def _clean(text: str, limit: int) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())[:limit]


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

    at = _now()
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    if req.customer_ids:
        ids = [i for i in req.customer_ids if mine is None or i in mine]
        people = list(_db.customers.find({"tenant_id": tid, "id": {"$in": ids}}, {"_id": 0}))
        label = f"{len(people)} client{'s' if len(people) > 1 else ''}"
    else:
        people = audience(tid, req.segment, at, mine)
        label = SEGMENT_LABELS.get(req.segment, "Sélection")
    from features.resend_guard import without
    people = without(people, req.exclude_ids)
    if not people and not req.draft and req.exclude_ids:
        raise HTTPException(status_code=400, detail="Aucun client à contacter : tous ont été retirés de l'envoi.")
    if mine is not None and not people and not req.draft:
        raise HTTPException(status_code=400, detail="Aucun client à contacter dans vos établissements.")

    when = _aware(req.schedule_at)
    status = "draft" if req.draft else ("scheduled" if when and when > at else "sent")

    doc = {
        "id": str(uuid.uuid4()),
        "tenant_id": tid,
        "name": title,
        "content": message,
        "status": status,
        "source": "push",
        "segment": req.segment if not req.customer_ids else "custom",
        "audience_label": label,
        "image_url": req.image_url or None,
        "link_url": req.link_url or None,
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
        "template": (req.template or "").strip()[:40] or None,
        # For which establishments it was sent (None = the whole shop), and by whom.
        "store_ids": scope.ids,
        "sent_by": getattr(token_data, "email", None),
    }

    if status != "sent":
        _db.campaigns.insert_one(dict(doc))
        return {"id": doc["id"], "status": status, "audience": len(people),
                "scheduled_for": when.isoformat() if when else None}

    # Saved as sent BEFORE delivering: _deliver() wakes the Wallet passes, and
    # an iPhone fetches its new pass within seconds. The pass builder reads the
    # campaign from the database (wallet_passes._attach_campaign_offer); saved
    # after, the pass came back unchanged and Wallet raised no notification
    # (user, 2026-10-04 — the offer only appeared later, silently).
    doc["sent_at"] = at
    _db.campaigns.insert_one(dict(doc))
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
    delivered = 0
    sent_at = doc["sent_at"]
    try:
        import server as core
    except Exception:
        core = None
    tenant = _db.tenants.find_one({"id": tid}) or {}

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
            woken = int((notify_passes(serials) or {}).get("sent") or 0)
        except Exception as exc:
            print(f"campagnes: wallet wake-up failed: {exc}")

    return {"delivered": delivered, "wallet_woken": woken, "reach": len(people)}


def run_due(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Send the campaigns whose scheduled time has come. Called by the daily
    cron; safe to call twice — a campaign leaves `scheduled` before it sends."""
    at = now or _now()
    out = {"sent": 0, "recipients": 0}
    from features import plan_limits
    for doc in list(_db.campaigns.find({"status": "scheduled"}, {"_id": 0})):
        when = _aware(doc.get("scheduled_for"))
        if not when or when > at:
            continue
        if not plan_limits.allows_tenant(doc.get("tenant_id"), "campaigns"):
            continue                    # Campagnes no longer in the plan: it will show as « non envoyée »
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
