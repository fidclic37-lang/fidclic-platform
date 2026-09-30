"""
CRM › Vue d'ensemble › « Pilotage commercial » — the block that replaced the
repeated « Tâches à venir / Activité récente / Accès rapides » (2026-09-30).

Three panels, each line opening what to act on:
- À traiter maintenant: overdue tasks, rendez-vous to confirm (next 7 days),
  active prospects with no next action, with no salesperson, propositions
  without news for 7 days, trials ending within 7 days, prospects idle for 30
  days, email replies received (7 days). A line opens the list of prospects
  concerned (GET /api/crm/pilotage/attention/{key}) with their actions.
- Équipe commerciale: per salesperson — active prospects, overdue tasks,
  calls and signatures over the period, conversion; plus « Non assigné ».
- Santé du pipeline: per stage — prospects, conversion to the next stage over
  the period, average days spent in the stage, idle ones (14 days); and the
  signatures to expect from propositions and trials at the historical rates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import TokenData
from features.platform_access import require_admin
from features import crm as C

router = APIRouter(tags=["crm"])
_db = None
ACTIVE = ["nouveau", "a_contacter", "contacte", "rdv", "proposition", "essai"]
WORKED = ["a_contacter", "contacte", "rdv", "proposition", "essai", "signe"]      # the funnel after « Prospects »
IDLE_DAYS = 30
STALE_DAYS = 14
QUIET_PROPOSAL_DAYS = 7

ATTENTION = [
    ("overdue", "Tâches en retard", "alarm", "rose"),
    ("rdv_confirm", "Rendez-vous à confirmer (7 jours)", "calendar", "violet"),
    ("no_next", "Prospects sans prochaine action", "compass", "amber"),
    ("unassigned", "Prospects sans commercial", "user", "blue"),
    ("quiet_proposals", "Propositions sans nouvelles depuis 7 jours", "file", "amber"),
    ("trials_ending", "Essais qui se terminent dans 7 jours", "hourglass", "rose"),
    ("idle", "Prospects inactifs depuis 30 jours", "moon", "slate"),
    ("replies", "Réponses aux emails (7 jours)", "mail", "green"),
]


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _open_tasks() -> List[Dict[str, Any]]:
    return list(_db.crm_tasks.find({"status": {"$ne": "terminee"}}, {"_id": 0}))


def _attention_ids(now: datetime) -> Dict[str, List[str]]:
    """Prospect ids behind each « À traiter » line (tasks keep their own ids)."""
    active = {p["id"]: p for p in _db.crm_prospects.find({"stage": {"$in": ACTIVE}}, {"_id": 0})}
    tasks = _open_tasks()
    with_next = {t.get("prospect_id") for t in tasks}
    week = now + timedelta(days=7)
    out: Dict[str, List[str]] = {}
    out["overdue"] = [t["id"] for t in tasks if (C._aware(t.get("due_at")) or week) < now]
    out["rdv_confirm"] = [t["id"] for t in tasks if t.get("type") == "rdv" and (t.get("confirm_status") or "a_confirmer") == "a_confirmer"
                          and now <= (C._aware(t.get("due_at")) or now - timedelta(days=1)) <= week]
    out["no_next"] = [pid for pid in active if pid not in with_next]
    out["unassigned"] = [pid for pid, p in active.items() if not p.get("assigned_to")]
    last = lambda p: C._aware(p.get("last_activity_at")) or C._aware(p.get("created_at")) or now   # noqa: E731
    out["quiet_proposals"] = [pid for pid, p in active.items() if p.get("stage") == "proposition"
                              and last(p) < now - timedelta(days=QUIET_PROPOSAL_DAYS)]
    trial = []
    for pid, p in active.items():
        if p.get("stage") == "essai" and p.get("tenant_id"):
            t = _db.tenants.find_one({"id": p["tenant_id"]}, {"_id": 0, "trial_ends_at": 1})
            end = C._aware((t or {}).get("trial_ends_at"))
            if end and now <= end <= week:
                trial.append(pid)
    out["trials_ending"] = trial
    out["idle"] = [pid for pid, p in active.items() if last(p) < now - timedelta(days=IDLE_DAYS)]
    replied = {s.get("prospect_id") for s in _db.crm_email_sends.find({"replied_at": {"$gte": now - timedelta(days=7)}},
                                                                      {"_id": 0, "prospect_id": 1})}
    out["replies"] = [pid for pid in replied if pid]
    return out


def _stage_trips() -> Dict[str, List[tuple]]:
    """Every prospect's stage changes, oldest first: {pid: [(at, from, to)]}."""
    trips: Dict[str, List[tuple]] = defaultdict(list)
    for a in _db.crm_activities.find({"type": "stage"}, {"_id": 0, "prospect_id": 1, "at": 1, "meta": 1}):
        at = C._aware(a.get("at"))
        m = a.get("meta") or {}
        if at and m.get("to"):
            trips[a["prospect_id"]].append((at, m.get("from"), m["to"]))
    for v in trips.values():
        v.sort(key=lambda x: x[0])
    return trips


def _health(start: datetime, end: datetime, now: datetime) -> Dict[str, Any]:
    trips = _stage_trips()
    counts = {k: _db.crm_prospects.count_documents({"stage": k}) for k in WORKED}
    stale = {k: 0 for k in WORKED}
    for p in _db.crm_prospects.find({"stage": {"$in": ACTIVE}}, {"_id": 0, "stage": 1, "last_activity_at": 1, "created_at": 1}):
        last = C._aware(p.get("last_activity_at")) or C._aware(p.get("created_at")) or now
        if p.get("stage") in stale and last < now - timedelta(days=STALE_DAYS):
            stale[p["stage"]] += 1
    # Time spent in a stage: from entering it to the next move (or now, while still in it).
    spent: Dict[str, List[float]] = defaultdict(list)
    reached_all: Dict[str, set] = defaultdict(set)
    reached_win: Dict[str, set] = defaultdict(set)
    for pid, tr in trips.items():
        for i, (at, _frm, to) in enumerate(tr):
            nxt = tr[i + 1][0] if i + 1 < len(tr) else now
            spent[to].append((nxt - at).total_seconds() / 86400)
            if to in C.FUNNEL:
                for s in C.FUNNEL[:C.FUNNEL.index(to) + 1]:      # reaching a stage means passing the earlier ones
                    reached_all[s].add(pid)
                    if start <= at < end:
                        reached_win[s].add(pid)
    rows = []
    for i, k in enumerate(WORKED):
        nxt = WORKED[i + 1] if i + 1 < len(WORKED) else None
        conv = round(len(reached_win[nxt]) / len(reached_win[k]) * 100) if nxt and reached_win[k] else None
        days = spent.get(k) or []
        rows.append({"key": k, "label": dict(C.STAGES)[k], "count": counts[k], "stale": stale.get(k, 0),
                     "conversion": conv, "next": dict(C.STAGES).get(nxt) if nxt else None,
                     "avg_days": round(sum(days) / len(days), 1) if days and k != "signe" else None})

    def rate(stage: str) -> Optional[float]:
        base = reached_all.get(stage) or set()
        return len(base & reached_all.get("signe", set())) / len(base) if base else None
    rp, re_ = rate("proposition"), rate("essai")
    forecast = round((counts["proposition"] * rp if rp is not None else 0) + (counts["essai"] * re_ if re_ is not None else 0))
    lost = _db.crm_prospects.count_documents({"stage": "perdu"})
    won = counts["signe"]
    return {"stages": rows, "forecast": forecast, "forecast_basis": {"proposition": round(rp * 100) if rp is not None else None,
                                                                      "essai": round(re_ * 100) if re_ is not None else None},
            "win_rate": round(won / (won + lost) * 100) if won + lost else None}


def _team(start: datetime, end: datetime, now: datetime) -> List[Dict[str, Any]]:
    users = C._users()
    tasks = _open_tasks()
    per: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"active": 0, "total": 0, "signed": 0, "overdue": 0, "calls": 0, "signed_period": 0})
    owner = {}
    for p in _db.crm_prospects.find({}, {"_id": 0, "id": 1, "stage": 1, "assigned_to": 1}):
        who = p.get("assigned_to") or ""
        owner[p["id"]] = who
        r = per[who]
        r["total"] += 1
        r["active"] += p.get("stage") in ACTIVE
        r["signed"] += p.get("stage") == "signe"
    for t in tasks:
        if (C._aware(t.get("due_at")) or now) < now:
            per[t.get("assigned_to") or owner.get(t.get("prospect_id"), "")]["overdue"] += 1
    for c in _db.crm_calls.find({"at": {"$gte": start, "$lt": end}}, {"_id": 0, "by": 1}):
        per[c.get("by") or ""]["calls"] += 1
    for a in _db.crm_activities.find({"type": "stage", "meta.to": "signe", "at": {"$gte": start, "$lt": end}}, {"_id": 0, "prospect_id": 1}):
        per[owner.get(a["prospect_id"], "")]["signed_period"] += 1
    rows = []
    for email, r in per.items():
        if not email:
            continue
        u = users.get(email) or {}
        rows.append({"email": email, "name": C._name(u) if u else email.split("@")[0], **r,
                     "conversion": round(r["signed"] / r["total"] * 100) if r["total"] else None})
    rows.sort(key=lambda x: (-x["signed_period"], -x["active"], x["name"].lower()))
    none = per.get("")
    if none and (none["active"] or none["overdue"]):
        rows.append({"email": "none", "name": "Non assigné", **none, "conversion": None})
    return rows


@router.get("/api/crm/pilotage")
def pilotage(date_from: Optional[str] = Query(None, alias="from"), date_to: Optional[str] = Query(None, alias="to"),
             token_data: TokenData = Depends(require_admin("crm"))):
    now = _now()
    end = (C._aware(date_to) + timedelta(days=1)) if C._aware(date_to) else now
    start = C._aware(date_from) or end - timedelta(days=30)
    ids = _attention_ids(now)
    attention = [{"key": k, "label": l, "icon": i, "tone": t, "count": len(ids[k])} for k, l, i, t in ATTENTION]
    return {"attention": attention, "total": sum(a["count"] for a in attention), "team": _team(start, end, now),
            "health": _health(start, end, now), "from": start.isoformat(), "to": end.isoformat()}


@router.get("/api/crm/pilotage/attention/{key}")
def attention_list(key: str, token_data: TokenData = Depends(require_admin("crm"))):
    if key not in {k for k, *_ in ATTENTION}:
        raise HTTPException(status_code=404, detail="Liste inconnue.")
    now = _now()
    ids = _attention_ids(now)[key]
    users = C._users()
    label = next(l for k, l, *_ in ATTENTION if k == key)
    if key in ("overdue", "rdv_confirm"):
        tasks = list(_db.crm_tasks.find({"id": {"$in": ids}}, {"_id": 0}).sort("due_at", 1))
        names = C._names(tasks)
        return {"key": key, "label": label, "kind": "tasks", "rows": [C._task_view(t, users, names) for t in tasks]}
    rows = [C._row(p, users) for p in _db.crm_prospects.find({"id": {"$in": ids}}, {"_id": 0})]
    rows.sort(key=lambda r: r.get("last_activity_at") or r.get("created_at") or "")
    return {"key": key, "label": label, "kind": "prospects", "rows": rows}
