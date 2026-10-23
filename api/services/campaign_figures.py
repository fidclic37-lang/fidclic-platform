"""
A campaign's figures, counted one way for every page (QA F32, 2026-10-11:
Campagnes read 1 click and 8 263 € for 7 campaigns, Analyses › Campagnes 0
clicks and 5 547 € for the same 7).

    Clics    the offer's clicks — the counter « Voir l'offre » and the
             campaign link increase (campaigns.offer_clicks). Analyses read a
             field nothing writes.
    Ouvertures  services/card_opens (the card opened within 72 h of the send,
             the offer opened, its link clicked) — already the Campagnes and
             Automatisations definition.
    CA généré   a recipient's visits in the ATTRIBUTION_DAYS after a send, and
             each visit once: it goes to the LATEST campaign that reached that
             client before it (last touch — the rule of « CA FidClic »,
             features/fidclic_impact). Campagnes added a visit to every
             campaign of those 15 days (two campaigns, twice); Analyses kept
             one visit per client and 30 days.
    Ventes   those visits, counted.

A campaign is counted in a period when it was sent in that period; its
visits are those of its own 15 days, whatever the period — so the same
campaigns give the same totals on both pages.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

ATTRIBUTION_DAYS = 15
OPEN_WINDOW_H = 72

REVENUE_NOTE = (f"CA généré : la dépense des destinataires dans les {ATTRIBUTION_DAYS} jours suivant l'envoi. "
                "Une visite compte une seule fois, pour la campagne la plus récente reçue avant elle.")


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


def clicks(c: Dict[str, Any]) -> int:
    return int(c.get("offer_clicks") or 0)


def attribution(db, tid: str, campaigns: Iterable[Dict[str, Any]],
                visit_filter: Optional[Dict[str, Any]] = None, detail: bool = False) -> Dict[str, Dict[str, Any]]:
    """{campaign id: {revenue, sales, buyers}} for these campaigns.

    Every sent campaign of the shop that reached a client competes for that
    client's visits (a newer campaign outside the list still takes the visits
    after it); each visit goes to one campaign at most. `visit_filter`: the
    establishment's visits only (store_scope.visit_filter). `detail`: each
    campaign also lists its visits ({customer_id, visit_time, amount}) — the
    dashboard's « Ventes attribuées » opened (2026-10-23)."""
    rows = [c for c in campaigns if c.get("id") and _aware(c.get("sent_at"))]
    out: Dict[str, Dict[str, Any]] = {c["id"]: {"revenue": 0.0, "sales": 0, "buyers": set(), "visits": []} for c in rows}
    def done(o):
        return {k: {"revenue": round(v["revenue"], 2), "sales": v["sales"], "buyers": len(v["buyers"]),
                    **({"visits": v["visits"]} if detail else {})} for k, v in o.items()}

    if not rows:
        return done(out)
    window = timedelta(days=ATTRIBUTION_DAYS)
    lo = min(_aware(c["sent_at"]) for c in rows)
    hi = max(_aware(c["sent_at"]) for c in rows) + window
    wanted = {c["id"]: set(c.get("recipient_ids") or []) for c in rows}
    people = set().union(*wanted.values())
    if not people:
        return done(out)

    # every send that could claim a visit between lo and hi, per client
    sends: Dict[str, List[tuple]] = defaultdict(list)
    for c in db.campaigns.find({"tenant_id": tid, "status": "sent"},
                               {"_id": 0, "id": 1, "sent_at": 1, "recipient_ids": 1}):
        at = _aware(c.get("sent_at"))
        if not at or at > hi or at + window < lo:
            continue
        for cid in set(c.get("recipient_ids") or []) & people:
            sends[cid].append((at, c["id"]))
    for c in rows:                                  # the page's own (store-limited) lists
        at = _aware(c["sent_at"])
        for cid in wanted[c["id"]]:
            if (at, c["id"]) not in sends[cid]:
                sends[cid].append((at, c["id"]))
    for lst in sends.values():
        lst.sort()

    q: Dict[str, Any] = {"tenant_id": tid, "customer_id": {"$in": list(people)},
                         "visit_time": {"$gte": lo, "$lte": hi}, **(visit_filter or {})}
    for v in db.visits.find(q, {"_id": 0, "customer_id": 1, "visit_time": 1, "amount_paid": 1}):
        t = _aware(v.get("visit_time"))
        cust = v.get("customer_id")
        lst = sends.get(cust)
        if not t or not lst:
            continue
        i = bisect_right([s[0] for s in lst], t) - 1        # the latest send at or before the visit
        if i < 0 or t - lst[i][0] > window:
            continue
        camp = lst[i][1]
        if camp in out and cust in wanted[camp]:
            out[camp]["revenue"] += float(v.get("amount_paid") or 0)
            out[camp]["sales"] += 1
            out[camp]["buyers"].add(cust)
            if detail:
                out[camp]["visits"].append({"customer_id": cust, "visit_time": t,
                                            "amount": round(float(v.get("amount_paid") or 0), 2)})
    return done(out)
