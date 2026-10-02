"""
CA FidClic (« Impact FidClic ») — the revenue FidClic brought back, and only that.

A plain scan is not FidClic revenue: that client was coming anyway. A visit
counts when a FidClic feature brought the client in (user, 2026-10-02):

    Parrainage      every visit of a client who joined through a parrain's
                    card, for as long as they stay a client.
    Campagnes       a campaign (sent now, scheduled or recurring) received in
    Géolocalisation the proximity push sent when they walked by
    Offres          an offer on the card: promotion, flash sale, Push Wallet,
                    personal card offer
    Automatisations anniversaire, relance des inactifs, « plus que N points »
                    — any of those received in the WINDOW_DAYS before the visit.

What is NOT counted: the messages FidClic sends *because* of a visit or a
signup — « Récompense débloquée », « Plus que 2 visites », the Google review
request, « Bienvenue » — a regular gets one nearly every visit, so counting
them would turn their ordinary next visit into FidClic revenue. Nor the
platform's own announcements (admin broadcast).

One visit, one source: a filleul's visits are Parrainage; otherwise the latest
message before the visit takes it (last touch). The total is a floor — FidClic
surely brings back more than it can prove.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

_db = None

WINDOW_DAYS = 15

SOURCES: List[Tuple[str, str, str]] = [
    ("campagnes", "Campagnes", "blue"),
    ("geolocalisation", "Géolocalisation", "violet"),
    ("offres", "Offres", "amber"),
    ("automatisations", "Automatisations", "green"),
    ("parrainage", "Parrainage", "rose"),
]

# Sent because of a visit or a signup, or by the platform itself: never a reason to come.
NOT_COUNTED = {"reward_unlocked", "near_reward", "google_review", "welcome", "tier_up",
               "admin_broadcast", "order_status", "safety"}
GEO = {"proximity"}
OFFERS = {"offer", "flash_sale", "voucher_expiry", "promotion_update", "card_override", "push_wallet"}
AUTOMATIONS = {"birthday", "inactive", "inactive_rescue", "almost_there", "reactivation"}


def init(db):
    global _db
    _db = db


def source_of(kind: Optional[str]) -> Optional[str]:
    k = (kind or "").strip()
    if k in NOT_COUNTED:
        return None
    if k in GEO:
        return "geolocalisation"
    if k in OFFERS:
        return "offres"
    if k in AUTOMATIONS:
        return "automatisations"
    return "campagnes"          # campaign, scheduled, manual, news, event, custom…


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            p = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return p if p.tzinfo else p.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _messages(tid: str, ids: set, since: datetime, until: datetime) -> Dict[str, List[Tuple[datetime, str]]]:
    """Every counted message each of these clients received, oldest first."""
    out: Dict[str, List[Tuple[datetime, str]]] = defaultdict(list)
    rng = {"$gte": since, "$lte": until}

    def add(cid, at, src):
        t = _aware(at)
        if cid in ids and t and src:
            out[cid].append((t, src))

    try:
        for m in _db.push_notifications.find({"tenant_id": tid, "sent_at": rng},
                                             {"_id": 0, "customer_id": 1, "type": 1, "sent_at": 1}):
            add(m.get("customer_id"), m.get("sent_at"), source_of(m.get("type")))
    except Exception:
        pass
    try:
        for m in _db.push_wallet_log.find({"tenant_id": tid, "sent_at": rng},
                                          {"_id": 0, "customer_id": 1, "sent_at": 1}):
            add(m.get("customer_id"), m.get("sent_at"), "offres")
    except Exception:
        pass
    try:
        # A campaign also names its recipients — older sends wrote no per-client row.
        for c in _db.campaigns.find({"tenant_id": tid, "sent_at": rng},
                                    {"_id": 0, "recipient_ids": 1, "sent_at": 1}):
            for cid in c.get("recipient_ids") or []:
                add(cid, c.get("sent_at"), "campagnes")
    except Exception:
        pass
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def _referees(tid: str, ids: set) -> set:
    try:
        return {r.get("referee_customer_id") for r in _db.referral_redemptions.find(
            {"tenant_id": tid}, {"_id": 0, "referee_customer_id": 1})} & ids
    except Exception:
        return set()


def source_by_visit(tid: str, rows: Iterable[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Optional[str]]]:
    """Each visit with the FidClic source that brought it, or None."""
    rows = list(rows)
    times = [_aware(v.get("visit_time")) for v in rows]
    ids = {v.get("customer_id") for v in rows if v.get("customer_id")}
    known = [t for t in times if t]
    if not ids or not known:
        return [(v, None) for v in rows]
    window = timedelta(days=WINDOW_DAYS)
    msgs = _messages(tid, ids, min(known) - window, max(known))
    referees = _referees(tid, ids)
    out = []
    for v, t in zip(rows, times):
        cid = v.get("customer_id")
        if cid in referees:
            out.append((v, "parrainage"))
            continue
        src = None
        mine = msgs.get(cid)
        if mine and t:
            # The latest message strictly before the visit, if recent enough.
            i = bisect_left(mine, (t,)) - 1
            while i >= 0 and mine[i][0] >= t:
                i -= 1
            if i >= 0 and t - mine[i][0] <= window:
                src = mine[i][1]
        out.append((v, src))
    return out


def impact(tid: str, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """{"revenue", "visits", "sources": {key: {"revenue", "visits"}}}"""
    by = {k: {"revenue": 0.0, "visits": 0} for k, _, _ in SOURCES}
    for v, src in source_by_visit(tid, rows):
        if src:
            by[src]["revenue"] += float(v.get("amount_paid") or 0)
            by[src]["visits"] += 1
    return {"revenue": round(sum(s["revenue"] for s in by.values()), 2),
            "visits": sum(s["visits"] for s in by.values()),
            "sources": {k: {"revenue": round(s["revenue"], 2), "visits": s["visits"]} for k, s in by.items()}}
