"""
FACTURE WATCHDOG — detect the factures that went quiet.
=======================================================

WHY THIS FILE EXISTS
--------------------
Sending an invoice and getting its status back are two DIFFERENT journeys across
companies we do not control:

    FidClic -> B2Brouter -> the client's PA -> the client's software -> a human

The forward journey works if every link passes the document along. The return
journey only works if every link bothers to send a status BACK. If any link stays
quiet, the invoice arrives perfectly and we never learn about it.

That is not an error. Nothing failed. There is simply silence — and silence is
invisible to every error handler ever written, because there is no error to handle.

    Café Lumière issues 4 800 EUR on 12 March. The UI shows "Envoyée".
    Nobody looks again. On 15 May the client asks "which invoice?".
    Two months of cash flow gone, and the practice has no answer.

No Plateforme Agréée will solve this: a PA's job ends at transmission. Detecting
the ABSENCE of a follow-up is the platform's job, which means ours.

HOW IT WORKS
------------
Every invoice already carries a `lifecycle` array of {family, state, at}. So we
already know exactly when each invoice last changed state — nobody was asking.
This module asks, once a day, and opens an Exception-Centre case when an invoice
has been sitting in a non-final state for longer than it should.

It writes NOTHING to the invoice itself. It only opens cases. A watchdog that can
corrupt the thing it watches is worse than no watchdog.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Thresholds. Deliberately conservative: a false alarm costs a glance, a missed
# silent invoice costs a client relationship.
# ---------------------------------------------------------------------------
class Threshold:
    # Handed to the PA but never confirmed as delivered. On a healthy PEPPOL
    # route `registered` follows within seconds, so two days is already abnormal.
    SENT_UNCONFIRMED_DAYS = 2

    # Delivered, but the buyer has neither accepted nor refused. Not an error —
    # people are slow — but after two weeks the practice should chase it.
    REGISTERED_NO_ANSWER_DAYS = 15

    # Past its due date and still not paid. This has stopped being a document
    # problem and become a cash-flow problem.
    OVERDUE_GRACE_DAYS = 5

    # Sent over a channel with no return path at all (email, paper). We will
    # NEVER get a status, so the only honest thing is to prompt a human check.
    BLIND_CHANNEL_DAYS = 7


FINAL_STATES = {"accepted", "refused", "paid", "cancelled"}
BLIND_CHANNELS = {"email", "paper", "manual"}


def _parse(ts: Any) -> Optional[datetime]:
    """Timestamps have been written by several generations of this codebase."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not isinstance(ts, str):
        return None
    raw = ts.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(raw)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def last_change(inv: Dict[str, Any]) -> Optional[datetime]:
    """When did this invoice last move? Falls back through the shapes we have."""
    lifecycle = inv.get("lifecycle") or []
    stamps = [_parse(e.get("at")) for e in lifecycle if isinstance(e, dict)]
    stamps = [s for s in stamps if s]
    if stamps:
        return max(stamps)
    return _parse(inv.get("updated_at")) or _parse(inv.get("created_at"))


def days_since(when: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    if not when:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - when).total_seconds() / 86400.0


def current_state(inv: Dict[str, Any]) -> str:
    pa = inv.get("pa")
    if isinstance(pa, dict) and pa.get("state"):
        return str(pa["state"])
    return str(inv.get("state") or "draft")


# ---------------------------------------------------------------------------
# The rules. Pure function: takes an invoice, returns a finding or None.
# Kept free of I/O so it is trivially testable and cannot break anything.
# ---------------------------------------------------------------------------
def evaluate(inv: Dict[str, Any], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    state = current_state(inv)
    if state in FINAL_STATES or state == "draft":
        return None

    now = now or datetime.now(timezone.utc)
    stuck = days_since(last_change(inv), now)
    if stuck is None:
        return None

    number = inv.get("number")
    channel = (inv.get("channel") or "").lower()
    ttc = inv.get("total_ttc")

    # 1. Overdue outranks everything: it is the one with a money consequence.
    due = _parse(inv.get("due_date"))
    if due and state != "paid":
        overdue = days_since(due, now)
        if overdue is not None and overdue > Threshold.OVERDUE_GRACE_DAYS:
            return _finding(
                inv, "overdue_unpaid", "high", overdue,
                fr=f"Facture {number} : échue depuis {int(overdue)} jours, toujours pas payée.",
                action_fr="Relancer le client. Vérifier d'abord qu'il l'a bien reçue.")

    # 2. A channel that can never answer. Not a failure — but a human must look.
    if channel in BLIND_CHANNELS and stuck > Threshold.BLIND_CHANNEL_DAYS:
        return _finding(
            inv, "blind_channel_unverified", "medium", stuck,
            fr=f"Facture {number} : envoyée par {channel}, aucun suivi possible sur ce canal.",
            action_fr="Confirmer la réception avec le client. Aucun accusé ne viendra.")

    # 3. Handed over but never confirmed delivered. This is Case C.
    #
    # Explicitly NOT for blind channels. On email there is no annuaire, no route
    # and no acknowledgement to wait for, so telling the practice to "check the
    # annuaire" would send them looking for something that does not exist. A
    # watchdog that gives confident wrong advice is worse than one that stays quiet.
    if (state == "sent"
            and channel not in BLIND_CHANNELS
            and stuck > Threshold.SENT_UNCONFIRMED_DAYS):
        return _finding(
            inv, "sent_not_confirmed", "high", stuck,
            fr=f"Facture {number} : déposée il y a {int(stuck)} jours, livraison jamais confirmée.",
            action_fr="Vérifier le SIRET dans l'annuaire, puis contacter le client. "
                      "La facture a peut-être été livrée sans accusé de réception.")

    # 4. Delivered, no answer. Normal for a while, then not.
    if state in ("registered", "received") and stuck > Threshold.REGISTERED_NO_ANSWER_DAYS:
        return _finding(
            inv, "no_buyer_response", "medium", stuck,
            fr=f"Facture {number} : livrée il y a {int(stuck)} jours, ni acceptée ni refusée.",
            action_fr="Relancer le client. Le silence ne vaut pas acceptation.")

    return None


def _finding(inv, kind, severity, days, fr, action_fr) -> Dict[str, Any]:
    return {
        "kind": kind,
        "severity": severity,
        "days": round(days, 1),
        "invoice_id": inv.get("id"),
        "number": inv.get("number"),
        "tenant_id": inv.get("tenant_id"),
        "state": current_state(inv),
        "channel": inv.get("channel"),
        "total_ttc": inv.get("total_ttc"),
        "detail_fr": fr,
        "action_fr": action_fr,
    }


def scan(invoices: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Evaluate a batch. Sorted so the practice sees money and age first."""
    out = [f for f in (evaluate(i, now) for i in invoices) if f]
    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda f: (rank.get(f["severity"], 9), -(f["total_ttc"] or 0), -f["days"]))
    return out
