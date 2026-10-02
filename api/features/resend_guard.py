"""
« Déjà contactés » — before a campaign goes out, who on the list already got
one in the last few days (user, 2026-10-02).

A client can sit in two segments at once (fidèle AND inactif, say). Sending
to one segment and then to the other would reach them twice. So before any
campaign is sent — from Campagnes or from Clients › Contacter — the page asks
here: of these clients, who already received a campaign in the last
WINDOW_DAYS days, when, and which one? The owner then ticks, client by client,
who gets this one too; the others are left out of the send (`exclude_ids`).

What counts as « une campagne »: what the shop sent to bring clients back —
campaigns (sent now or scheduled), offers, Push Wallet offers and the
automations (anniversaire, relance…). Not the messages that follow a client's
own visit or signup, nor a proximity push (features/fidclic_impact.py draws
the same line).

The per-client daily / weekly caps stay the owner's own setting
(Paramètres › Notifications); this does not replace them.

Mounts at:
    POST /api/owner/campaigns/recent-check   {customer_ids?, segment?}
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from auth import require_role, TokenData
from features import store_scope as S

router = APIRouter(tags=["campaigns"])
_db = None

WINDOW_DAYS = 3
SENDERS = ["business_owner", "administrateur", "manager"]
SOURCE_LABELS = {"campagnes": "Campagne", "offres": "Offre", "automatisations": "Automatisation"}


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def recently_contacted(tid: str, ids: List[str], at: Optional[datetime] = None,
                       days: int = WINDOW_DAYS) -> Dict[str, Dict[str, Any]]:
    """{customer_id: {"at", "title", "kind"}} — the latest campaign each of
    these clients received in the last `days` days."""
    from features.fidclic_impact import source_of
    at = at or _now()
    since = at - timedelta(days=days)
    wanted = set(ids)
    out: Dict[str, Dict[str, Any]] = {}

    def keep(cid, when, title, kind):
        t = _aware(when)
        if cid not in wanted or not t or not kind:
            return
        if cid not in out or t > out[cid]["at"]:
            out[cid] = {"at": t, "title": (title or "").strip() or SOURCE_LABELS.get(kind, "Campagne"), "kind": kind}

    try:
        for m in _db.push_notifications.find(
                {"tenant_id": tid, "sent_at": {"$gte": since, "$lte": at}},
                {"_id": 0, "customer_id": 1, "type": 1, "title": 1, "sent_at": 1}):
            src = source_of(m.get("type"))
            if src in SOURCE_LABELS:                    # not a proximity push, not a receipt
                keep(m.get("customer_id"), m.get("sent_at"), m.get("title"), src)
    except Exception:
        pass
    try:
        for m in _db.push_wallet_log.find({"tenant_id": tid, "sent_at": {"$gte": since, "$lte": at}},
                                          {"_id": 0, "customer_id": 1, "title": 1, "sent_at": 1}):
            keep(m.get("customer_id"), m.get("sent_at"), m.get("title"), "offres")
    except Exception:
        pass
    try:
        # A campaign also names its recipients (older sends wrote no per-client row).
        for c in _db.campaigns.find({"tenant_id": tid, "status": "sent", "sent_at": {"$gte": since, "$lte": at}},
                                    {"_id": 0, "name": 1, "recipient_ids": 1, "sent_at": 1}):
            for cid in c.get("recipient_ids") or []:
                keep(cid, c.get("sent_at"), c.get("name"), "campagnes")
    except Exception:
        pass
    return out


def without(people: List[Dict[str, Any]], exclude_ids: Optional[List[str]]) -> List[Dict[str, Any]]:
    """The send's list minus the clients the owner chose to leave out."""
    drop = set(exclude_ids or [])
    return [c for c in people if c.get("id") not in drop] if drop else people


class Check(BaseModel):
    customer_ids: Optional[List[str]] = Field(None, max_length=50_000)
    segment: Optional[str] = None


@router.post("/api/owner/campaigns/recent-check")
def recent_check(body: Check, request: Request = None,
                 token_data: TokenData = Depends(require_role(SENDERS, partial_ok=True))):
    """Of the clients about to receive a campaign, who already got one lately."""
    tid = token_data.tenant_id
    at = _now()
    scope = S.resolve(token_data, request)
    mine = S.customer_ids(scope)
    if body.customer_ids:
        ids = [i for i in body.customer_ids if mine is None or i in mine]
    elif body.segment:
        from features.campaigns_page import audience
        ids = [c["id"] for c in audience(tid, body.segment, at, mine)]
    else:
        ids = []
    hits = recently_contacted(tid, ids, at)
    names = {c["id"]: c for c in _db.customers.find(
        {"tenant_id": tid, "id": {"$in": list(hits)}}, {"_id": 0, "id": 1, "name": 1, "phone": 1, "email": 1})}
    rows = sorted(({"id": cid, "name": (names.get(cid) or {}).get("name") or "Client",
                    "contact": (names.get(cid) or {}).get("phone") or (names.get(cid) or {}).get("email") or "",
                    "at": h["at"].isoformat(), "title": h["title"], "kind": SOURCE_LABELS[h["kind"]]}
                   for cid, h in hits.items()), key=lambda r: r["at"], reverse=True)
    return {"total": len(ids), "recent": rows, "window_days": WINDOW_DAYS}
