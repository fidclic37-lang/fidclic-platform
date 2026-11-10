"""
« Impact FidClic » — the detail behind the figure (user, 2026-11-10).

The card said how much FidClic brought back, not when, not which clients, not
which message. Clicked, it opens on the page it sits on — the Tableau de bord
or Analyses — with the same period: the visits FidClic counted, each with
when, who, how much, its source and its message, and an export CSV.
No « Par action » / « Par jour », no « Établissement » (the one chosen in
the menu) nor « Délai » (user, 2026-11-10: « hata do completely »).

« Attendus de toute façon » (features/fidclic_impact) are listed, flagged, and
never in the total. Every visit is judged by fidclic_impact.explain — the
judge behind the card — so the detail adds up to the card's figure.

    GET /api/owner/home/impact[/export]       (the Tableau de bord's permission)
    GET /api/owner/analyses/impact[/export]   (Analyses' permission)
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth import require_role, TokenData
from features import fidclic_impact as FI, period as P, store_scope as S
from services import safe_csv

_db = None
_PARIS = ZoneInfo("Europe/Paris")
router = APIRouter(tags=["impact"])
READERS = ["business_owner", "administrateur", "manager"]

# A month of a busy shop is a few hundred lines; the list stops here, the
# totals still count everything.
MAX_VISITS = 2000

KIND_LABELS = {
    "campagnes": "Campagne", "geolocalisation": "Géolocalisation", "offres": "Offre",
    "automatisations": "Automatisation", "parrainage": "Parrainage",
}
DELETED = "Client supprimé"


def init(db):
    global _db
    _db = db
    FI.init(db)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _names(coll: str, tid: str, ids: set, field: str = "name") -> Dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    q: Dict[str, Any] = {"tenant_id": tid, "id": {"$in": sorted(ids)}}
    if coll == "customers":
        q["deleted_at"] = None              # a deleted client keeps the visit, not the name
    return {d["id"]: (d.get(field) or "").strip() for d in _db[coll].find(q, {"_id": 0, "id": 1, field: 1})}


def detail(tid: str, scope: Optional["S.Scope"], span: "P.Span", at: Optional[datetime] = None,
           limit: Optional[int] = -1, hide_clients: bool = False) -> Dict[str, Any]:
    """The detail of [span]. `limit` caps the visits listed (-1: MAX_VISITS,
    None: all of them — the CSV). `hide_clients`: a team member without the
    Clients page sees « Client » and the source, never a name or an amount
    (user, 2026-11-10)."""
    at = at or _now()
    cap = MAX_VISITS if limit == -1 else limit
    vfilter = S.visit_filter(scope) if scope is not None else {}
    rows = list(_db.visits.find(
        {"tenant_id": tid, "visit_time": {"$gte": span.start, "$lte": span.end}, **vfilter},
        {"_id": 0, "id": 1, "customer_id": 1, "amount_paid": 1, "visit_time": 1}))
    rows = [v for v in rows if FI._aware(v.get("visit_time"))]
    judged = [(v, *x) for v, x in zip(rows, FI.explain(tid, rows))]
    judged = [j for j in judged if j[1]]          # a plain scan is not FidClic's

    clients = _names("customers", tid, {v.get("customer_id") for v, *_ in judged})
    parrain_ids = {ref.get("parrain_id") for _, src, _, _, ref in judged if src == "parrainage" and ref}
    parrains = _names("customers", tid, parrain_ids)
    camps = _names("campaigns", tid, {ref.get("campaign_id") for *_, ref in judged if ref})
    autos = _names("automations", tid, {ref.get("automation_id") for *_, ref in judged if ref})
    def action_name(src: str, ref: Dict[str, Any]) -> str:
        if src == "parrainage":
            p = None if hide_clients else parrains.get(ref.get("parrain_id"))
            return f"Parrainage · {p}" if p else "Parrainage"
        if ref.get("campaign_id") and camps.get(ref["campaign_id"]):
            return camps[ref["campaign_id"]]
        if ref.get("automation_id") and autos.get(ref["automation_id"]):
            return autos[ref["automation_id"]]
        return (ref.get("title") or "").strip() or KIND_LABELS.get(src, "Message")

    sources = {k: {"revenue": 0.0, "visits": 0} for k, _, _ in FI.SOURCES}
    apart = {"revenue": 0.0, "visits": 0}
    visits: List[Dict[str, Any]] = []
    for v, src, _cand, anyway, ref in judged:
        ref = ref or {}
        t = FI._aware(v["visit_time"])
        amount = round(float(v.get("amount_paid") or 0), 2)
        if anyway:
            apart["revenue"] += amount; apart["visits"] += 1
        else:
            sources[src]["revenue"] += amount; sources[src]["visits"] += 1
        cid = v.get("customer_id")
        visits.append({
            "id": v.get("id"), "at": t.isoformat(),
            "client_id": None if hide_clients else (cid if cid in clients else None),
            "client": "Client" if hide_clients else (clients.get(cid) or DELETED),
            "amount": None if hide_clients else amount,
            "source": src, "action_name": action_name(src, ref),
            "attendu": bool(anyway),
        })

    visits.sort(key=lambda x: x["at"], reverse=True)
    return {
        "from": span.start.isoformat(), "to": span.end.isoformat(),
        "date_from": span.date_from, "date_to": span.date_to,
        "window_days": FI.WINDOW_DAYS,
        "sources": [{"key": k, "label": l, "tone": tone} for k, l, tone in FI.SOURCES],
        "totals": {"revenue": round(sum(s["revenue"] for s in sources.values()), 2),
                   "visits": sum(s["visits"] for s in sources.values()),
                   "sources": {k: {"revenue": round(s["revenue"], 2), "visits": s["visits"]} for k, s in sources.items()},
                   "attendus": {"revenue": round(apart["revenue"], 2), "visits": apart["visits"]}},
        "visits": visits if cap is None else visits[:cap],
        "truncated": cap is not None and len(visits) > cap,
        "clients_hidden": bool(hide_clients),
    }


def _hide(token_data, request) -> bool:
    """No « Voir » on the Clients page: no client's name or amount here either."""
    from features import role_perms as RP
    return not RP.may(token_data, "customers", "view", request)


def _for(request, days, date_from, date_to, token_data) -> Dict[str, Any]:
    at = _now()
    span = P.span(P.clamp_days(days), date_from, date_to, at)
    return detail(token_data.tenant_id, S.resolve(token_data, request), span, at,
                  hide_clients=_hide(token_data, request))


def _csv(request, days, date_from, date_to, token_data) -> Response:
    at = _now()
    span = P.span(P.clamp_days(days), date_from, date_to, at)
    d = detail(token_data.tenant_id, S.resolve(token_data, request), span, at, limit=None,
               hide_clients=_hide(token_data, request))
    buf = io.StringIO()
    w = safe_csv.writer(buf)
    labels = {s["key"]: s["label"] for s in d["sources"]}
    w.writerow(["Date", "Heure", "Client", "Montant (€)", "Source", "Message", "Compté dans le CA FidClic"])
    for v in d["visits"]:
        t = datetime.fromisoformat(v["at"]).astimezone(_PARIS)
        w.writerow([t.strftime("%d/%m/%Y"), t.strftime("%H:%M"), v["client"],
                    "" if v["amount"] is None else f"{v['amount']:.2f}".replace(".", ","),
                    labels.get(v["source"], v["source"]), v["action_name"],
                    "Non (attendu de toute façon)" if v["attendu"] else "Oui"])
    return Response(content="﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fidclic-impact-{at:%Y%m%d}.csv"'})


@router.get("/api/owner/home/impact")
def home_impact(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _for(request, days, date_from, date_to, token_data)


@router.get("/api/owner/analyses/impact")
def analyses_impact(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                    date_from: Optional[str] = None, date_to: Optional[str] = None,
                    token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _for(request, days, date_from, date_to, token_data)


@router.get("/api/owner/home/impact/export")
def home_export(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                date_from: Optional[str] = None, date_to: Optional[str] = None,
                token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _csv(request, days, date_from, date_to, token_data)


@router.get("/api/owner/analyses/impact/export")
def analyses_export(request: Request = None, days: int = Query(30, ge=1, le=P.MAX_DAYS),
                    date_from: Optional[str] = None, date_to: Optional[str] = None,
                    token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    return _csv(request, days, date_from, date_to, token_data)
