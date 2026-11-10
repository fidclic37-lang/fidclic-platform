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

ATTENDUS DE TOUTE FAÇON (user, 2026-10-25)
    A message with no groupe témoin behind it — an anniversaire, an offer, one
    client, a small send — cannot prove itself. So when the client brain says
    the visit fell in that client's usual window anyway (their rhythm, read
    from their visits before that day), it is « attendu de toute façon »:
    shown apart, not in CA FidClic. A client without a known rhythm (fewer
    than 3 visit days) counts as before. A message that HAD a témoin is left
    whole: its real effect is the témoin's « +X € » (features/temoin.py).
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

_db = None
_PARIS = ZoneInfo("Europe/Paris")

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


def _messages(tid: str, ids: set, since: datetime, until: datetime) -> Dict[str, List[Tuple[datetime, str, bool, Dict[str, Any]]]]:
    """Every counted message each of these clients received, oldest first —
    with whether a groupe témoin measured it, and what it was (its kind, the
    campaign or automation that sent it, its title: the detail names it)."""
    out: Dict[str, List[Tuple[datetime, str, bool, Dict[str, Any]]]] = defaultdict(list)
    rng = {"$gte": since, "$lte": until}

    def add(cid, at, src, measured=False, ref=None):
        t = _aware(at)
        if cid in ids and t and src:
            out[cid].append((t, src, bool(measured), {**(ref or {}), "sent_at": t}))

    try:
        notes = list(_db.push_notifications.find({"tenant_id": tid, "sent_at": rng},
                                                 {"_id": 0, "customer_id": 1, "type": 1, "sent_at": 1,
                                                  "campaign_id": 1, "temoin": 1, "automation_id": 1, "title": 1}))
    except Exception:
        notes = []
    # The campaigns a témoin measured, found by the ids the messages name —
    # not by when the campaign was sent: a message's answer must not depend on
    # the period it is read in (features/visit_days sums each day on its own).
    try:
        named = sorted({m.get("campaign_id") for m in notes if m.get("campaign_id")})
        measured_camps = set(_db.campaigns.distinct("id", {"tenant_id": tid, "id": {"$in": named},
                                                          "holdout_ids.0": {"$exists": True}})) if named else set()
    except Exception:
        measured_camps = set()
    for m in notes:
        add(m.get("customer_id"), m.get("sent_at"), source_of(m.get("type")),
            m.get("temoin") or (m.get("campaign_id") in measured_camps),
            {"kind": m.get("type"), "campaign_id": m.get("campaign_id"),
             "automation_id": m.get("automation_id"), "title": m.get("title")})
    try:
        for m in _db.push_wallet_log.find({"tenant_id": tid, "sent_at": rng},
                                          {"_id": 0, "customer_id": 1, "sent_at": 1, "title": 1}):
            add(m.get("customer_id"), m.get("sent_at"), "offres", ref={"kind": "push_wallet", "title": m.get("title")})
    except Exception:
        pass
    try:
        # A campaign also names its recipients — older sends wrote no per-client row.
        for c in _db.campaigns.find({"tenant_id": tid, "sent_at": rng},
                                    {"_id": 0, "id": 1, "name": 1, "recipient_ids": 1, "sent_at": 1, "holdout_ids": 1}):
            for cid in c.get("recipient_ids") or []:
                add(cid, c.get("sent_at"), "campagnes", bool(c.get("holdout_ids")),
                    {"kind": "campaign", "campaign_id": c.get("id"), "title": c.get("name")})
    except Exception:
        pass
    for v in out.values():
        v.sort(key=lambda x: x[:3])
    return out


def _referees(tid: str, ids: set) -> set:
    return set(_parrains(tid, ids))


def _parrains(tid: str, ids: set) -> Dict[str, Optional[str]]:
    """{filleul: their parrain} for these clients."""
    try:
        return {r.get("referee_customer_id"): r.get("referrer_customer_id")
                for r in _db.referral_redemptions.find(
                    {"tenant_id": tid}, {"_id": 0, "referee_customer_id": 1, "referrer_customer_id": 1})
                if r.get("referee_customer_id") in ids}
    except Exception:
        return {}


def source_by_visit(tid: str, rows: Iterable[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Optional[str]]]:
    """Each visit with the FidClic source that brought it, or None."""
    return [(v, src) for v, src, _, _ in _touch_by_visit(tid, rows)]


def _touch_by_visit(tid: str, rows: Iterable[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Optional[str], bool, Optional[Dict[str, Any]]]]:
    """Each visit, its source, whether that message had a groupe témoin, and
    what brought it (the message, or the parrain) — None when nothing did."""
    rows = list(rows)
    times = [_aware(v.get("visit_time")) for v in rows]
    ids = {v.get("customer_id") for v in rows if v.get("customer_id")}
    known = [t for t in times if t]
    if not ids or not known:
        return [(v, None, False, None) for v in rows]
    window = timedelta(days=WINDOW_DAYS)
    msgs = _messages(tid, ids, min(known) - window, max(known))
    parrains = _parrains(tid, ids)
    out = []
    for v, t in zip(rows, times):
        cid = v.get("customer_id")
        if cid in parrains:
            out.append((v, "parrainage", False, {"kind": "parrainage", "parrain_id": parrains[cid]}))
            continue
        src, measured, ref = None, False, None
        mine = msgs.get(cid)
        if mine and t:
            # The latest message strictly before the visit, if recent enough.
            i = bisect_left(mine, (t,)) - 1
            while i >= 0 and mine[i][0] >= t:
                i -= 1
            if i >= 0 and t - mine[i][0] <= window:
                src, measured, ref = mine[i][1], mine[i][2], mine[i][3]
        out.append((v, src, measured, ref))
    return out


def _paris_day(t: datetime):
    return t.astimezone(_PARIS).date()


def expected_anyway(tid: str, visits: List[Dict[str, Any]]) -> set:
    """Of these visits, the ones the client brain saw coming: the client had a
    known rhythm from their visits on the days before, and this day fell in
    its window. Returns their positions in `visits`."""
    from features import client_brain as CB
    times = [_aware(v.get("visit_time")) for v in visits]
    ids = list({v.get("customer_id") for v in visits if v.get("customer_id")})
    if not ids or not any(times):
        return set()
    until = max(t for t in times if t)
    history: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in _db.visits.find({"tenant_id": tid, "customer_id": {"$in": ids}, "visit_time": {"$lt": until}},
                             {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1, "items": 1}):
        if _aware(h.get("visit_time")):
            history[h["customer_id"]].append(h)
    try:
        args = CB.model_args(tid, CB.champion())
    except Exception:
        return set()
    out = set()
    for i, (v, t) in enumerate(zip(visits, times)):
        if not t:
            continue
        day = _paris_day(t)
        before = [h for h in history.get(v.get("customer_id"), []) if _paris_day(_aware(h["visit_time"])) < day]
        if len(before) < CB.RHYTHM_MIN_VISITS:
            continue
        b = CB.build(before, at=t, **args)
        if not CB.known(b):
            continue
        r = CB.rythme(b, t)
        lo, hi = r.get("next_from"), r.get("next_to")
        if lo and hi and _paris_day(lo) <= day <= _paris_day(hi):
            out.add(i)
    return out


def classify(tid: str, rows: Iterable[Dict[str, Any]]) -> List[Tuple[Optional[str], bool, bool]]:
    """Each visit, on its own: (the FidClic source that brought it or None,
    whether « attendus » could claim it — a message no témoin measured —,
    whether the brain saw it coming and it is set apart). A visit's answer
    never depends on the other visits passed with it, so a day can be judged
    once and summed (features/visit_days)."""
    return [(src, cand, apart) for src, cand, apart, _ in explain(tid, rows)]


def explain(tid: str, rows: Iterable[Dict[str, Any]]) -> List[Tuple[Optional[str], bool, bool, Optional[Dict[str, Any]]]]:
    """classify's answer, and for each visit what brought it: {"kind",
    "sent_at", "title", "campaign_id", "automation_id"} for a message,
    {"kind": "parrainage", "parrain_id"} for a filleul, None for a plain scan.
    The « Impact FidClic » detail (features/impact_detail) reads it."""
    rows = list(rows)
    touch = _touch_by_visit(tid, rows)
    # a message no témoin measured: the visits the brain saw coming are set apart
    cand = [i for i, (_, src, measured, _) in enumerate(touch) if src and not measured and src != "parrainage"]
    anyway = expected_anyway(tid, [rows[i] for i in cand]) if cand else set()
    apart = {cand[j] for j in anyway}
    cands = set(cand)
    return [(src, i in cands, i in apart, ref) for i, (_, src, _, ref) in enumerate(touch)]


def impact(tid: str, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """{"revenue", "visits", "sources": {key: {"revenue", "visits"}},
        "attendus": {"revenue", "visits"}}"""
    rows = list(rows)
    by = {k: {"revenue": 0.0, "visits": 0} for k, _, _ in SOURCES}
    apart = {"revenue": 0.0, "visits": 0}
    for v, (src, _, anyway) in zip(rows, classify(tid, rows)):
        if not src:
            continue
        amount = float(v.get("amount_paid") or 0)
        if anyway:
            apart["revenue"] += amount
            apart["visits"] += 1
            continue
        by[src]["revenue"] += amount
        by[src]["visits"] += 1
    return {"revenue": round(sum(s["revenue"] for s in by.values()), 2),
            "visits": sum(s["visits"] for s in by.values()),
            "sources": {k: {"revenue": round(s["revenue"], 2), "visits": s["visits"]} for k, s in by.items()},
            "attendus": {"revenue": round(apart["revenue"], 2), "visits": apart["visits"]}}
