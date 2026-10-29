"""
FidClic IA › « a repéré » — three detectors over the client brain (user,
2026-10-25: B), shown on the Tableau de bord, in the bell (from 3 clients),
as Clients chips and in Insights; each opens its clients or the composer
pre-filled for them (« Préparer le message »).

    « Habitués en retard »        a known rhythm (3 visit days), now past its
                                  window but not yet « décroche » — the moment
                                  to act before they slip away
    « Pas revenus après la 1ère   one visit, and since then longer than the
      visite »                    shop's usual rhythm × 1.5 — or than the
                                  owner's « Client bientôt perdu », if sooner —
                                  but not past the owner's « Client dormant »
    « Viennent moins souvent »    their last gaps are half again as long as
                                  before (client_brain trend « baisse »), not
                                  yet décroche

THE SECOND-VISIT RULE REPLACES « VENUS UNE SEULE FOIS » (user, 2026-10-25: A)
    The old fixed rule (joined in the last 30 days, one visit) counted a
    salon client seen 5 days ago — not due back for weeks — and forgot one
    seen 55 days ago, the one worth a message. clients_page.is_one_timer now
    asks here, so the bell, the Clients chip, Insights and the Copilote count
    the same clients. Its END is the owner's own « Client dormant » rule: what
    the owner calls dormant is the dormant list's business; its START is the
    brain's (the shop's usual rhythm), unless the owner's « bientôt perdu »
    comes first — a stricter owner wins. When even that starts after
    « dormant », the list is empty and the card says why.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request

from auth import require_role
from models import TokenData
from features import client_brain as CB
from features import store_scope as S

FIRST_VISIT_FACTOR = 1.5
BELL_MIN = 3                       # user, 2026-10-25: « 3 clients ya zyada »
READERS = ["business_owner", "administrateur", "manager"]
_TTL_S = 60

router = APIRouter(tags=["brain-detectors"])
_db = None
_window_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def init(db):
    global _db
    _db = db


def _rule_days(rules: List[Dict[str, Any]], key: str, default: int) -> int:
    r = next((r for r in rules if r.get("key") == key), None)
    try:
        return int(r["conditions"][0]["value"]) if r else default
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def second_visit_window(tid: Optional[str], fresh: bool = False) -> Dict[str, Any]:
    """From which day after their only visit a client is « pas revenu », and
    until which — with the reasons, for the card."""
    now = datetime.now(timezone.utc).timestamp()
    hit = _window_cache.get(tid or "")
    if hit and not fresh and now - hit[0] < _TTL_S:
        return hit[1]
    from features import customer_rules as R
    rules = R.load(tid) if tid else R.defaults()
    soon_lost = _rule_days(rules, "bientot_perdu", 31)
    dormant = _rule_days(rules, "dormant", 90)
    usual = CB.prior_for(tid, CB.champion())[0] if tid else CB.DEFAULT_GAP
    brain_start = round(FIRST_VISIT_FACTOR * float(usual), 1)
    start = min(brain_start, float(soon_lost))
    out = {"start": start, "end": float(dormant), "usual": float(usual), "brain_start": brain_start,
           "soon_lost": soon_lost, "dormant": dormant, "by": "boutique" if soon_lost < brain_start else "rythme",
           "empty": start >= dormant}
    _window_cache[tid or ""] = (now, out)
    return out


def _since_only_visit(cust: Dict[str, Any], at: datetime) -> Optional[float]:
    last = CB._aware(cust.get("last_visit_date")) or CB._aware((cust.get("brain") or {}).get("last"))
    return CB._days(last, at) if last else None


def is_second_visit_due(cust: Dict[str, Any], at: datetime, w: Optional[Dict[str, Any]] = None) -> bool:
    if int(cust.get("visits") or 0) != 1:
        return False
    w = w or second_visit_window(cust.get("tenant_id"))
    d = _since_only_visit(cust, at)
    return d is not None and w["start"] < d <= w["end"]


def is_late_regular(cust: Dict[str, Any], at: datetime) -> bool:
    b = cust.get("brain")
    return bool(b) and CB.known(b) and CB.rythme(b, at)["key"] == "en_retard"


def is_slowing(cust: Dict[str, Any], at: datetime) -> bool:
    b = cust.get("brain")
    return (bool(b) and CB.known(b) and b.get("trend") == "baisse"
            and CB.rythme(b, at)["key"] != "decroche")


DETECTORS = [
    {"key": "en_retard", "label": "Habitués en retard", "icon": "clock", "tone": "orange"},
    {"key": "one_timers", "label": "Pas revenus après la 1ère visite", "icon": "repeat", "tone": "violet"},
    {"key": "moins_souvent", "label": "Viennent moins souvent", "icon": "trending-down", "tone": "rose"},
]
LABELS = {d["key"]: d["label"] for d in DETECTORS}


def matches(key: str, cust: Dict[str, Any], at: datetime) -> bool:
    if key == "en_retard":
        return is_late_regular(cust, at)
    if key == "moins_souvent":
        return is_slowing(cust, at)
    if key == "one_timers":
        return is_second_visit_due(cust, at)
    return False


def _basket(c: Dict[str, Any]) -> float:
    b = (c.get("brain") or {}).get("basket")
    if b:
        return float(b)
    n = int(c.get("visits") or 0)
    return float(c.get("total_amount_paid") or 0) / n if n else 0.0


def detect(tid: str, people: List[Dict[str, Any]], at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The three lists, with the numbers behind each sentence."""
    at = at or datetime.now(timezone.utc)
    w = second_visit_window(tid)
    out = []
    for d in DETECTORS:
        if d["key"] == "one_timers":
            who = [c for c in people if is_second_visit_due(c, at, w)]
        else:
            who = [c for c in people if matches(d["key"], c, at)]
        who.sort(key=_basket, reverse=True)
        n = len(who)
        worth = round(sum(_basket(c) for c in who), 2)
        if d["key"] == "en_retard":
            late = sorted(int(CB.rythme(c["brain"], at).get("late_days") or 0) for c in who)
            why = (f"Ils ont un rythme connu (3 jours de visite au moins) et l'ont dépassé : "
                   f"{late[len(late) // 2]} jours de retard en médiane. Pas encore « décroché » : "
                   "c'est le bon moment.") if who else "Aucun habitué n'a dépassé son rythme."
        elif d["key"] == "moins_souvent":
            why = ("Leurs 3 derniers écarts entre deux visites sont au moins 1,5 fois plus longs "
                   "qu'avant (7 visites au moins).") if who else "Aucun habitué ne ralentit."
        else:
            usual = CB._when(w["usual"])
            if w["empty"]:
                why = (f"Votre règle « Client dormant » ({w['dormant']} j) arrive avant le moment où ils "
                       f"devraient revenir ({int(w['start'])} j) : la liste reste vide.")
            elif w["by"] == "boutique":
                why = (f"Venus une seule fois, il y a plus de {w['soon_lost']} jours (votre règle « Client "
                       f"bientôt perdu ») et moins de {w['dormant']} jours (« Client dormant »).")
            else:
                why = (f"Venus une seule fois, il y a plus de {int(w['brain_start'])} jours — vos clients "
                       f"reviennent d'habitude {usual} — et moins de {w['dormant']} jours (votre règle "
                       "« Client dormant »).")
        out.append({**d, "count": n, "ids": [c["id"] for c in who], "worth": worth,
                    "names": [c.get("name") or "" for c in who[:3]], "why": why,
                    "bell": n >= BELL_MIN,
                    "template": f"ia:{d['key']}", "clients": f"/dashboard/customers?segment={d['key']}"})
    return out


def people(tid: str, scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    CB.ensure(tid)
    from features import clients_page as CP
    return list(_db.customers.find(S.customer_filter(scope) if scope else {"tenant_id": tid, "deleted_at": None},
                                   CP.FIELDS))


@router.get("/api/owner/brain/detectors")
def get_detectors(request: Request = None, token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    found = detect(tid, people(tid, scope))
    out = [{k: v for k, v in d.items() if k != "ids"} for d in found]
    # the ranking that learns (2026-10-30): what these clients are worth × what was learned
    from features import reco_ranking as RR
    out = RR.rank(tid, out, lambda d, n: float(d.get("worth") or 0) + float(d.get("count") or 0) / 100 + (len(out) - n) / 1000)
    # the journal of ideas (2026-10-29)
    from features import reco_journal as RJ
    RJ.shown(tid, "repere", out, scope.key)
    RJ.attach(tid, out)
    return {"detectors": out, "window": second_visit_window(tid)}


# ---------------------------------------------------------------------------
# « Préparer le message »: the composer's words for each list
# ---------------------------------------------------------------------------
TEMPLATES = {
    "en_retard": {"title": "💛 Vous nous manquez",
                  "message": "Cela fait un moment ! Un petit plus vous attend pour {produit_habituel}, "
                             "sur présentation de votre carte."},
    "one_timers": {"title": "🎁 Merci pour votre première visite !",
                   "message": "On vous attend pour la deuxième : une attention vous attend pour "
                              "{produit_habituel}, sur présentation de votre carte."},
    "moins_souvent": {"title": "✨ Une attention pour vous",
                      "message": "Ça nous fait toujours plaisir de vous voir ! Un petit plus vous attend "
                                 "pour {produit_habituel} cette semaine, sur présentation de votre carte."},
}
