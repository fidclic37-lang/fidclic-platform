"""
What counts as « ouverture » for a campaign or an automatic push — one
definition for the Campagnes page and the Automatisations page (user,
2026-10-05: « open rate kyun nhi measure ho rha … jabki main khol rha hun card
ko, and also click krke link bhi khol rha hun »).

A wallet notification returns no read receipt: Apple and Google never tell us
that the pass was looked at. What we CAN see, and count, for a recipient:

    1. the web card opened within OPEN_WINDOW_H of the send — any opening,
       not just the first of the day;
    2. the campaign itself opened: from the card's offers feed, or through
       « Voir l'offre » on the back of the Wallet pass (the pixel);
    3. the campaign's link clicked.

THE BUG IT FIXES
    card_opens keeps one row per customer per day, and only stored the
    FIRST opening of that day. A customer who looked at their card in the
    morning and again after an afternoon campaign read as « not opened ».
    Every opening is now kept on the day's row (`ats`, the last 100).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

OPEN_WINDOW_H = 72
KEEP_PER_DAY = 100


def _aware(d: Any) -> Optional[datetime]:
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def log(db, cust: Dict[str, Any], now: Optional[datetime] = None) -> None:
    """The customer just opened their card."""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    db.card_opens.update_one(
        {"customer_id": cust["id"], "day": day},
        {"$setOnInsert": {"tenant_id": cust.get("tenant_id"), "customer_id": cust["id"], "day": day, "at": now},
         "$set": {"last_at": now},
         "$push": {"ats": {"$each": [now], "$slice": -KEEP_PER_DAY}},
         "$inc": {"opens": 1}},
        upsert=True)
    db.customers.update_one({"id": cust["id"]}, {"$set": {"last_card_open_at": now}})


def open_times(db, tid: str, ids: Iterable[str], start: datetime, end: datetime) -> Dict[str, List[datetime]]:
    """customer id → every card opening between start and end."""
    ids = list(ids)
    out: Dict[str, List[datetime]] = {}
    if not ids:
        return out
    start, end = _aware(start), _aware(end)
    rows = db.card_opens.find(
        {"tenant_id": tid, "customer_id": {"$in": ids},
         "day": {"$gte": start.strftime("%Y-%m-%d"), "$lte": end.strftime("%Y-%m-%d")}},
        {"_id": 0, "customer_id": 1, "at": 1, "last_at": 1, "ats": 1})
    for r in rows:
        times = r.get("ats") or [r.get("at"), r.get("last_at")]   # rows written before `ats`
        for t in times:
            t = _aware(t)
            if t and start <= t <= end:
                out.setdefault(r["customer_id"], []).append(t)
    return out


def opened_ids(db, tid: str, recipients: List[str], sent_at: Optional[datetime],
               campaign: Optional[Dict[str, Any]] = None, window_h: int = OPEN_WINDOW_H) -> Set[str]:
    """Recipients who opened: their card within `window_h` of the send, or
    this campaign itself (offers feed / « Voir l'offre »), or its link."""
    sent_at = _aware(sent_at)
    if not recipients or not sent_at:
        return set()
    wanted = set(recipients)
    opened = set(open_times(db, tid, wanted, sent_at, sent_at + timedelta(hours=window_h)))
    if campaign and campaign.get("id"):
        for r in db.campaign_opens.find({"campaign_id": campaign["id"], "customer_id": {"$in": list(wanted)}},
                                        {"_id": 0, "customer_id": 1}):
            opened.add(r["customer_id"])
        opened |= wanted & set(campaign.get("click_customer_ids") or [])
    return opened & wanted
