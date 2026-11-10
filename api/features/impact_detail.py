"""
« Impact FidClic » — the detail behind the figure (user, 2026-11-10).

The card said how much FidClic brought back, not when, not which clients, not
which message. Clicked, it opens on the page it sits on — the Tableau de bord
or Analyses — with the same period:

    Par action   each campagne / automatisation / offre / géoloc / parrain:
                 its name, when it went out, clients back, visits, CA
    Par visite   each visit counted: when, who, how much, where, which
                 message and how many days after it
    Par jour     the CA FidClic of each day, by source
    Export CSV   the visits, one line each

« Attendus de toute façon » (features/fidclic_impact) are listed, flagged, and
never in the total. Every visit is judged by fidclic_impact.explain — the
judge behind the card — so the detail adds up to the card's figure.

    GET /api/owner/home/impact[/export]       (the Tableau de bord's permission)
    GET /api/owner/analyses/impact[/export]   (Analyses' permission)
"""
from __future__ import annotations

import io
from collections import defaultdict
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
# totals, the actions and the days still count everything.
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


def _day(t: datetime):
    return t.astimezone(_PARIS).date()


def _names(coll: str, tid: str, ids: set, field: str = "name") -> Dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    q: Dict[str, Any] = {"tenant_id": tid, "id": {"$in": sorted(ids)}}
    if coll == "customers":
        q["deleted_at"] = None              # a deleted client keeps the visit, not the name
    return {d["id"]: (d.get(field) or "").strip() for d in _db[coll].find(q, {"_id": 0, "id": 1, field: 1})}


def _action_key(src: str, ref: Dict[str, Any]) -> str:
    if src == "parrainage":
        return f"p:{ref.get('parrain_id') or '?'}"
    if ref.get("campaign_id"):
        return f"c:{ref['campaign_id']}"
    if ref.get("automation_id"):
        return f"a:{ref['automation_id']}"
    # an offer, a proximity push, an old automatic message: by kind and title
    return f"k:{ref.get('kind') or src}:{(ref.get('title') or '').strip()[:80]}"


def detail(tid: str, scope: Optional["S.Scope"], span: "P.Span", at: Optional[datetime] = None,
           limit: Optional[int] = -1) -> Dict[str, Any]:
    """The detail of [span]. `limit` caps the visits listed (-1: MAX_VISITS,
    None: all of them — the CSV)."""
    at = at or _now()
    cap = MAX_VISITS if limit == -1 else limit
    vfilter = S.visit_filter(scope) if scope is not None else {}
    rows = list(_db.visits.find(
        {"tenant_id": tid, "visit_time": {"$gte": span.start, "$lte": span.end}, **vfilter},
        {"_id": 0, "id": 1, "customer_id": 1, "amount_paid": 1, "visit_time": 1, "branch_id": 1}))
    rows = [v for v in rows if FI._aware(v.get("visit_time"))]
    judged = [(v, *x) for v, x in zip(rows, FI.explain(tid, rows))]
    judged = [j for j in judged if j[1]]          # a plain scan is not FidClic's

    clients = _names("customers", tid, {v.get("customer_id") for v, *_ in judged})
    parrain_ids = {ref.get("parrain_id") for _, src, _, _, ref in judged if src == "parrainage" and ref}
    parrains = _names("customers", tid, parrain_ids)
    camps = _names("campaigns", tid, {ref.get("campaign_id") for *_, ref in judged if ref})
    autos = _names("automations", tid, {ref.get("automation_id") for *_, ref in judged if ref})
    stores = (scope.names if scope is not None else {}) or {}
    main_name = stores.get("main") or (next(iter(stores.values()), None) if len(stores) == 1 else None) \
        or ((_db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}).get("name") or "")

    def store_name(b) -> str:
        if b in (None, "", "main"):
            return main_name
        return stores.get(b) or "Établissement"

    def action_name(src: str, ref: Dict[str, Any]) -> str:
        if src == "parrainage":
            p = parrains.get(ref.get("parrain_id"))
            return f"Parrainage · {p}" if p else "Parrainage"
        if ref.get("campaign_id") and camps.get(ref["campaign_id"]):
            return camps[ref["campaign_id"]]
        if ref.get("automation_id") and autos.get(ref["automation_id"]):
            return autos[ref["automation_id"]]
        return (ref.get("title") or "").strip() or KIND_LABELS.get(src, "Message")

    sources = {k: {"revenue": 0.0, "visits": 0} for k, _, _ in FI.SOURCES}
    apart = {"revenue": 0.0, "visits": 0}
    actions: Dict[str, Dict[str, Any]] = {}
    days: Dict[str, Dict[str, float]] = defaultdict(lambda: {**{k: 0.0 for k, _, _ in FI.SOURCES}, "attendus": 0.0})
    visits: List[Dict[str, Any]] = []
    for v, src, _cand, anyway, ref in judged:
        ref = ref or {}
        t = FI._aware(v["visit_time"])
        amount = round(float(v.get("amount_paid") or 0), 2)
        key = _action_key(src, ref)
        name = action_name(src, ref)
        sent = ref.get("sent_at")
        a = actions.setdefault(key, {"key": key, "source": src, "kind": KIND_LABELS.get(src, ""), "name": name,
                                     "first_sent": None, "last_sent": None, "clients": set(), "visits": 0,
                                     "revenue": 0.0, "attendus": {"visits": 0, "revenue": 0.0}})
        if sent:
            a["first_sent"] = min(a["first_sent"] or sent, sent)
            a["last_sent"] = max(a["last_sent"] or sent, sent)
        day = _day(t).isoformat()
        if anyway:
            apart["revenue"] += amount; apart["visits"] += 1
            a["attendus"]["visits"] += 1; a["attendus"]["revenue"] += amount
            days[day]["attendus"] += amount
        else:
            sources[src]["revenue"] += amount; sources[src]["visits"] += 1
            a["clients"].add(v.get("customer_id")); a["visits"] += 1; a["revenue"] += amount
            days[day][src] += amount
        cid = v.get("customer_id")
        visits.append({
            "id": v.get("id"), "at": t.isoformat(), "client_id": cid if cid in clients else None,
            "client": clients.get(cid) or DELETED, "amount": amount, "store": store_name(v.get("branch_id")),
            "source": src, "action": key, "action_name": name,
            "sent_at": sent.isoformat() if sent else None,
            "days_after": (_day(t) - _day(sent)).days if sent else None,
            "attendu": bool(anyway),
        })

    visits.sort(key=lambda x: x["at"], reverse=True)
    out_actions = []
    for a in actions.values():
        out_actions.append({**a, "clients": len(a["clients"]), "revenue": round(a["revenue"], 2),
                            "first_sent": a["first_sent"].isoformat() if a["first_sent"] else None,
                            "last_sent": a["last_sent"].isoformat() if a["last_sent"] else None,
                            "attendus": {"visits": a["attendus"]["visits"],
                                         "revenue": round(a["attendus"]["revenue"], 2)}})
    out_actions.sort(key=lambda a: (-a["revenue"], -a["visits"], a["name"]))
    out_days = []
    for d in sorted(days):
        x = {k: round(val, 2) for k, val in days[d].items()}
        out_days.append({"date": d, **x, "total": round(sum(x[k] for k, _, _ in FI.SOURCES), 2)})
    return {
        "from": span.start.isoformat(), "to": span.end.isoformat(),
        "date_from": span.date_from, "date_to": span.date_to,
        "window_days": FI.WINDOW_DAYS,
        "sources": [{"key": k, "label": l, "tone": tone} for k, l, tone in FI.SOURCES],
        "totals": {"revenue": round(sum(s["revenue"] for s in sources.values()), 2),
                   "visits": sum(s["visits"] for s in sources.values()),
                   "sources": {k: {"revenue": round(s["revenue"], 2), "visits": s["visits"]} for k, s in sources.items()},
                   "attendus": {"revenue": round(apart["revenue"], 2), "visits": apart["visits"]}},
        "actions": out_actions,
        "days": out_days,
        "visits": visits if cap is None else visits[:cap],
        "truncated": cap is not None and len(visits) > cap,
    }


def _for(request, days, date_from, date_to, token_data) -> Dict[str, Any]:
    at = _now()
    span = P.span(P.clamp_days(days), date_from, date_to, at)
    return detail(token_data.tenant_id, S.resolve(token_data, request), span, at)


def _csv(request, days, date_from, date_to, token_data) -> Response:
    at = _now()
    span = P.span(P.clamp_days(days), date_from, date_to, at)
    d = detail(token_data.tenant_id, S.resolve(token_data, request), span, at, limit=None)
    buf = io.StringIO()
    w = safe_csv.writer(buf)
    labels = {s["key"]: s["label"] for s in d["sources"]}
    w.writerow(["Date", "Heure", "Client", "Montant (€)", "Établissement", "Source", "Message",
                "Message envoyé le", "Jours après le message", "Compté dans le CA FidClic"])
    for v in d["visits"]:
        t = datetime.fromisoformat(v["at"]).astimezone(_PARIS)
        sent = datetime.fromisoformat(v["sent_at"]).astimezone(_PARIS).strftime("%d/%m/%Y") if v["sent_at"] else ""
        w.writerow([t.strftime("%d/%m/%Y"), t.strftime("%H:%M"), v["client"], f"{v['amount']:.2f}".replace(".", ","),
                    v["store"], labels.get(v["source"], v["source"]), v["action_name"], sent,
                    "" if v["days_after"] is None else v["days_after"],
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
