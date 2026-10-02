"""
Autopilot — FidClic IA prepares the campaigns; the owner validates them
(user, 2026-10-02). Pro AI only.

TWO RHYTHMS, EACH SWITCHED ON ITS OWN
    Quotidien     every day, a small campaign to « le bon client au bon
                  moment » — the clients whose moment is today:
                    · en retard sur leur habitude: regulars now 1.5× past
                      their usual gap (a three-day window, so a client is
                      met once, not every day)
                    · leur jour habituel: clients who mostly come on today's
                      weekday and have not been seen this week
                    · nouveaux, une semaine après: one visit, 7–9 days ago
                  the largest group of the day becomes the campaign; a day
                  with no group of at least MIN_DAILY clients has none.
    Hebdomadaire  once a week, on the owner's day and time, a campaign to a
                  big group: the inactive clients when they are many, else
                  the loyal ones, else everybody — not the same group as the
                  week before when there is a choice.

WHAT IS LEFT OUT, ALWAYS
    Clients at their own daily / weekly limit (Paramètres › Notifications,
    send_rules.over_limit), and clients who got a campaign in the last 3
    days (resend_guard) — so the owner's validation pop-up has nothing left
    to ask about. The proposal says how many were left out and why.

THE WORDS
    Written by the IA, briefed with what works for this shop
    (campaign_learning.prompt_hints) — or, without a model, by a template.
    Never a promise the shop has not made: no discount or gift is invented.
    When the shop's campaigns show a gift works, the proposal says so as
    advice, and the owner adds it if they want.

NOTHING LEAVES WITHOUT THE OWNER
    A proposal is « À valider » in the bell and on Automatisations. The owner
    validates (edited or not), or skips. It can be validated until 24 h after
    its time; then it is « expirée » — an offer for yesterday is not sent.
    With a cron every 15 min (FIDCLIC_CRON_PRECISE=1, Vercel Pro), a
    validated campaign leaves at the owner's time; on the daily cron it
    leaves when it is validated on its day, or on that day's morning run when
    validated the day before — never a day early.

The Copilote's « Mode Autopilot » switch is this one (one Autopilot).

Mounts at:
    GET  /api/owner/autopilot                    settings, proposals, history
    PUT  /api/owner/autopilot                    owner: rhythms, days, times
    POST /api/owner/autopilot/prepare            prepare today's / this week's now
    POST /api/owner/autopilot/{id}/approve       owner: send (edited or not)
    POST /api/owner/autopilot/{id}/skip          owner
"""
from __future__ import annotations

import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_role
from models import TokenData

router = APIRouter(tags=["autopilot"])
_db = None

PARIS = ZoneInfo("Europe/Paris")
READERS = ["business_owner", "administrateur", "manager"]
OWNER = ["business_owner"]
VALID_HOURS = 24
MORNING_UTC = 6          # just before the daily cron (07:00 UTC) of the campaign's day
MIN_DAILY = 3
DAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
DEFAULTS = {"daily": {"enabled": False, "hour": 11, "minute": 0},
            "weekly": {"enabled": False, "weekday": 5, "hour": 10, "minute": 0}}


def init(db):
    global _db
    _db = db
    try:
        db.autopilot_proposals.create_index([("tenant_id", 1), ("kind", 1), ("for_date", 1)], unique=True)
        db.autopilot_proposals.create_index([("status", 1), ("expires_at", 1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def precise() -> bool:
    """A cron every 15 min (Vercel Pro): campaigns leave at the owner's time."""
    return os.getenv("FIDCLIC_CRON_PRECISE", "") in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Who may use it, and its settings
# ---------------------------------------------------------------------------
def plan_ok(tid: str) -> bool:
    from features import plan_limits as PL
    f = PL.tenant_features(tid)
    return (f.get("ai_level") or "none") == "advanced" and PL.allows(f, "campaigns")


def settings(tid: str) -> Dict[str, Any]:
    doc = _db.autopilot_config.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    if not doc:
        # The Copilote's old « Mode Autopilot » was switched on: it is this one now.
        legacy = _db.copilot_plans.find_one({"tenant_id": tid, "autopilot": True}, {"_id": 0, "tenant_id": 1})
        if legacy:
            doc = {"daily": {**DEFAULTS["daily"], "enabled": True}, "weekly": {**DEFAULTS["weekly"], "enabled": True}}
            _db.autopilot_config.update_one({"tenant_id": tid}, {"$set": {"tenant_id": tid, **doc, "migrated": True}}, upsert=True)
            _db.copilot_plans.update_one({"tenant_id": tid}, {"$set": {"autopilot": False}})
    return {"daily": {**DEFAULTS["daily"], **(doc.get("daily") or {})},
            "weekly": {**DEFAULTS["weekly"], **(doc.get("weekly") or {})}}


def any_on(tid: str) -> bool:
    s = settings(tid)
    return bool(s["daily"]["enabled"] or s["weekly"]["enabled"])


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------
def _at(day, hour: int, minute: int) -> datetime:
    """A Paris wall-clock time on a Paris date, in UTC."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=PARIS).astimezone(timezone.utc)


def _weekly_date(cfg: Dict[str, Any], now: datetime):
    """The weekly campaign's date to prepare now: its day, or the day before."""
    today = now.astimezone(PARIS).date()
    for d in (today, today + timedelta(days=1)):
        if d.weekday() == int(cfg["weekday"]):
            return d
    return None


# ---------------------------------------------------------------------------
# Who
# ---------------------------------------------------------------------------
def _available(tid: str, ids: List[str], at: datetime) -> Tuple[List[str], Dict[str, int]]:
    """These clients minus those at their limit or contacted in 3 days."""
    from features import send_rules as SR, resend_guard as RG
    left = {"limit": 0, "recent": 0}
    recent = RG.recently_contacted(tid, ids, at)
    out = []
    for cid in ids:
        if cid in recent:
            left["recent"] += 1
        elif SR.over_limit(tid, cid, at):
            left["limit"] += 1
        else:
            out.append(cid)
    return out, left


def _visits_by_client(tid: str, at: datetime, days: int = 365) -> Dict[str, List[datetime]]:
    out: Dict[str, List[datetime]] = {}
    for v in _db.visits.find({"tenant_id": tid, "visit_time": {"$gte": at - timedelta(days=days), "$lte": at}},
                             {"_id": 0, "customer_id": 1, "visit_time": 1}):
        t = _aware(v.get("visit_time"))
        if t and v.get("customer_id"):
            out.setdefault(v["customer_id"], []).append(t)
    for ts in out.values():
        ts.sort()
    return out


DAILY_GROUPS = {
    "en_retard": ("Clients en retard sur leur habitude", "Faire revenir des habitués qui tardent"),
    "jour_habituel": ("Clients dont c'est le jour habituel", "Rappeler aux habitués que c'est leur jour"),
    "nouveaux_j7": ("Nouveaux clients, une semaine après", "Faire revenir un nouveau client pour la 2e fois"),
}


def daily_groups(tid: str, at: datetime) -> Dict[str, List[str]]:
    """Today's « bon client au bon moment », each client in one group only."""
    visits = _visits_by_client(tid, at)
    today = at.astimezone(PARIS)
    groups: Dict[str, List[str]] = {k: [] for k in DAILY_GROUPS}
    for cid, ts in visits.items():
        last = ts[-1]
        since = (at - last).total_seconds() / 86400
        if len(ts) >= 3:
            gaps = [(b - a).total_seconds() / 86400 for a, b in zip(ts, ts[1:])]
            usual = max(1.0, sum(gaps) / len(gaps))
            if usual * 1.5 <= since < usual * 1.5 + 3:
                groups["en_retard"].append(cid)
                continue
        if len(ts) >= 4:
            days = Counter(t.astimezone(PARIS).weekday() for t in ts)
            if days.get(today.weekday(), 0) / len(ts) >= 0.5 and since >= 5:
                groups["jour_habituel"].append(cid)
                continue
        if len(ts) == 1 and 7 <= since < 10:
            groups["nouveaux_j7"].append(cid)
    return groups


def weekly_audience(tid: str, at: datetime) -> Tuple[str, List[str], str]:
    """(segment, ids, why) — inactive when many, else loyal, else everybody;
    not the same as last week's when there is a choice."""
    from features import clients_page as CP, customer_rules as R
    rules = R.load(tid)
    people = list(_db.customers.find({"tenant_id": tid, "deleted_at": None}, CP.FIELDS))
    inactive = [c["id"] for c in people if CP.is_inactive(c, at, rules)]
    loyal = [c["id"] for c in people if CP.is_loyal(c, at, rules)]
    last = _db.autopilot_proposals.find_one({"tenant_id": tid, "kind": "weekly", "status": {"$in": ["sent", "scheduled"]}},
                                            sort=[("for_date", -1)])
    last_seg = (last or {}).get("segment")
    choices = []
    if people and len(inactive) >= max(10, 0.1 * len(people)):
        choices.append(("inactive", inactive, f"{len(inactive)} clients ne viennent plus : c'est le groupe le plus utile à relancer."))
    if len(loyal) >= 10:
        choices.append(("loyal", loyal, f"{len(loyal)} clients fidèles : les remercier les garde fidèles."))
    choices.append(("all", [c["id"] for c in people], "Toute votre clientèle, pour garder le lien."))
    pick = next((c for c in choices if c[0] != last_seg), choices[0])
    return pick


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------
TEMPLATES = {
    "en_retard": ("{first_name}, on ne vous oublie pas", "Cela fait un petit moment ! Passez nous voir cette semaine chez {business_name}, on sera ravis de vous revoir."),
    "jour_habituel": ("C'est votre jour, {first_name} !", "Aujourd'hui, c'est un peu votre jour chez {business_name}. On vous attend !"),
    "nouveaux_j7": ("Merci pour votre première visite", "{first_name}, merci d'être passé chez {business_name} ! Revenez quand vous voulez, vos points vous attendent."),
    "inactive": ("Vous nous manquez, {first_name}", "Ça fait longtemps ! Toute l'équipe de {business_name} serait ravie de vous revoir bientôt."),
    "loyal": ("Merci, {first_name} !", "Merci pour votre fidélité. Toute l'équipe de {business_name} est heureuse de vous compter parmi ses habitués."),
    "all": ("Des nouvelles de {business_name}", "{first_name}, passez nous voir cette semaine chez {business_name} : on vous attend !"),
}
OBJECTIVES = {
    "en_retard": "faire revenir des habitués qui tardent à revenir",
    "jour_habituel": "rappeler à des habitués que c'est le jour où ils viennent d'habitude",
    "nouveaux_j7": "faire revenir une 2e fois des clients venus une seule fois il y a une semaine",
    "inactive": "faire revenir des clients qui ne viennent plus",
    "loyal": "remercier les clients fidèles",
    "all": "garder le lien avec toute la clientèle",
}
NO_PROMISE = ("N'invente aucune offre, remise, cadeau ni prix : le commerçant ajoutera une offre s'il le souhaite. "
              "Tu peux utiliser {first_name} et {business_name}.")


def write(tid: str, key: str) -> Tuple[str, str, str]:
    """(title, message, by) — the IA briefed with what works here, or a template."""
    from features import campaigns_page as C
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "name": 1}) or {}
    try:
        from services import llm
        from features.campaign_learning import prompt_hints
        if llm._force_complete is not None or llm.is_configured():
            user = (f"Commerce : {tenant.get('name') or 'un commerce'}. Objectif : {OBJECTIVES[key]}. "
                    f"{prompt_hints(tid)} {NO_PROMISE}")
            title, message = C._parse(llm.complete(C._SYSTEM, user, max_tokens=180, temperature=0.7) or "")
            if title and message and not re.search(r"\d+\s?%|-\s?\d+\s?€|\boffert|\bgratuit|\bcadeau", (title + message).lower()):
                return title, message, "ia"
    except Exception as exc:
        print(f"autopilot: IA unavailable ({exc})")
    t, m = TEMPLATES[key]
    return t, m, "modele"


def _advice(tid: str) -> List[str]:
    """What the shop's own results say about offers — advice, never applied."""
    try:
        from features.campaign_learning import learnings
        rows = learnings(tid)["learnings"]
    except Exception:
        return []
    out = []
    for f in rows:
        if f["dimension"] == "offer" and f["better"] and f["value"] != "aucune":
            out.append(f"{f['label']} marche mieux "
                       f"{'chez vous' if f['source'] == 'vous' else 'chez les commerces comme le vôtre'} : "
                       "ajoutez-en un si vous le souhaitez.")
        if f["dimension"] in ("day", "week", "slot") and f["better"]:
            out.append(f"Moment qui marche le mieux : {f['label'][0].lower() + f['label'][1:]}.")
    return out[:3]


# ---------------------------------------------------------------------------
# Preparing
# ---------------------------------------------------------------------------
def _save(tid: str, kind: str, day, send_at: datetime, seg: str, ids: List[str], label: str,
          reasons: List[str], left: Dict[str, int], key: str, now: datetime) -> Dict[str, Any]:
    if not ids:
        doc = {"id": str(uuid.uuid4()), "tenant_id": tid, "kind": kind, "for_date": day.isoformat(),
               "status": "empty", "reasons": reasons, "created_at": now}
    else:
        title, message, by = write(tid, key)
        doc = {"id": str(uuid.uuid4()), "tenant_id": tid, "kind": kind, "for_date": day.isoformat(),
               "status": "pending", "title": title, "message": message, "written_by": by,
               "segment": seg, "customer_ids": ids, "audience_label": label, "audience_count": len(ids),
               "left_out": left, "reasons": reasons, "advice": _advice(tid),
               "send_at": send_at, "expires_at": send_at + timedelta(hours=VALID_HOURS),
               "created_at": now}
    try:
        _db.autopilot_proposals.insert_one(dict(doc))
    except Exception:                                   # prepared twice at once: the first one stays
        doc = _db.autopilot_proposals.find_one({"tenant_id": tid, "kind": kind, "for_date": day.isoformat()}, {"_id": 0})
    return doc


def prepare(tid: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Today's daily proposal and this week's weekly one, if switched on and not
    prepared yet. Sends nothing."""
    now = now or _now()
    if not plan_ok(tid):
        return []
    cfg = settings(tid)
    made = []
    today = now.astimezone(PARIS).date()
    if cfg["daily"]["enabled"] and not _db.autopilot_proposals.find_one(
            {"tenant_id": tid, "kind": "daily", "for_date": today.isoformat()}):
        groups = daily_groups(tid, now)
        best_key, best_ids, best_left = None, [], {"limit": 0, "recent": 0}
        for key, ids in groups.items():
            ok, left = _available(tid, ids, now)
            if len(ok) > len(best_ids):
                best_key, best_ids, best_left = key, ok, left
        send_at = _at(today, cfg["daily"]["hour"], cfg["daily"]["minute"])
        if best_key and len(best_ids) >= MIN_DAILY:
            label, why = DAILY_GROUPS[best_key]
            reasons = [f"{label} : {len(best_ids)} clients aujourd'hui.", f"Objectif : {why.lower()}."]
            made.append(_save(tid, "daily", today, send_at, "custom", best_ids, label, reasons, best_left, best_key, now))
        else:
            made.append(_save(tid, "daily", today, send_at, "custom", [], "", [
                "Aucun groupe de clients dont c'est le moment aujourd'hui : pas de campagne, pour ne pas déranger."],
                {}, "all", now))
    wd = _weekly_date(cfg["weekly"], now) if cfg["weekly"]["enabled"] else None
    if wd and not _db.autopilot_proposals.find_one({"tenant_id": tid, "kind": "weekly", "for_date": wd.isoformat()}):
        seg, ids, why = weekly_audience(tid, now)
        ok, left = _available(tid, ids, now)
        from features.campaigns_page import SEGMENT_LABELS
        made.append(_save(tid, "weekly", wd, _at(wd, cfg["weekly"]["hour"], cfg["weekly"]["minute"]),
                          seg, ok, SEGMENT_LABELS.get(seg, "Clients"), [why], left, seg, now))
    return made


def expire(now: Optional[datetime] = None) -> int:
    now = now or _now()
    r = _db.autopilot_proposals.update_many({"status": "pending", "expires_at": {"$lt": now}},
                                            {"$set": {"status": "expired"}})
    return int(getattr(r, "modified_count", 0) or 0)


def run(now: Optional[datetime] = None) -> Dict[str, int]:
    """The cron: expire what was not validated, prepare what is due."""
    now = now or _now()
    out = {"expired": expire(now), "tenants": 0, "prepared": 0}
    for doc in _db.autopilot_config.find({"$or": [{"daily.enabled": True}, {"weekly.enabled": True}]},
                                         {"_id": 0, "tenant_id": 1}):
        try:
            made = prepare(doc["tenant_id"], now)
            out["tenants"] += 1
            out["prepared"] += sum(1 for m in made if m.get("status") == "pending")
        except Exception as exc:
            print(f"autopilot: {doc['tenant_id']} failed ({exc})")
    return out


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _view(p: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    send_at, expires = _aware(p.get("send_at")), _aware(p.get("expires_at"))
    status = p.get("status")
    if status == "pending" and expires and expires < now:
        status = "expired"
    return {k: p.get(k) for k in ("id", "kind", "for_date", "title", "message", "written_by", "segment",
                                  "audience_label", "audience_count", "left_out", "reasons", "advice",
                                  "campaign_id")} | {
        "status": status, "send_at": send_at.isoformat() if send_at else None,
        "expires_at": expires.isoformat() if expires else None,
        "customer_ids": p.get("customer_ids") if status == "pending" else None}


def pending(tid: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or _now()
    return [_view(p, now) for p in _db.autopilot_proposals.find(
        {"tenant_id": tid, "status": "pending", "expires_at": {"$gte": now}}, {"_id": 0}).sort("send_at", 1)]


def alerts(tid: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """What the bell says."""
    out = []
    for p in pending(tid, now):
        what = "du jour" if p["kind"] == "daily" else "de la semaine"
        # « warning »: waiting for the owner, it sorts with what needs doing.
        out.append({"id": f"autopilot:{p['id']}", "severity": "warning",
                    "title": f"Autopilot : votre campagne {what} est prête",
                    "body": f"« {p['title']} » pour {p['audience_count']} clients ({p['audience_label']}). "
                            "Rien ne part sans votre validation.",
                    "metric": str(p["audience_count"]),
                    "action": {"href": "/dashboard/automations#autopilot", "label": "Voir et valider"}})
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/api/owner/autopilot")
def get_autopilot(token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    tid = token_data.tenant_id
    now = _now()
    expire(now)
    history = [_view(p, now) for p in _db.autopilot_proposals.find(
        {"tenant_id": tid, "status": {"$ne": "pending"}}, {"_id": 0}).sort("for_date", -1).limit(10)]
    return {"plan_ok": plan_ok(tid), "settings": settings(tid), "pending": pending(tid, now),
            "history": history, "precise": precise(), "valid_hours": VALID_HOURS,
            "can_edit": token_data.role == "business_owner", "days": DAYS_FR}


class Rhythm(BaseModel):
    enabled: bool = False
    hour: int = Field(11, ge=0, le=23)
    minute: int = Field(0, ge=0, le=59)
    weekday: Optional[int] = Field(None, ge=0, le=6)


class Settings(BaseModel):
    daily: Optional[Rhythm] = None
    weekly: Optional[Rhythm] = None


def _require_plan(tid: str):
    if not plan_ok(tid):
        raise HTTPException(status_code=403, detail={
            "code": "PLAN_LOCKED", "feature": "autopilot",
            "message": "L'Autopilot est inclus dans l'offre Pro AI."})


@router.put("/api/owner/autopilot")
def put_autopilot(body: Settings, token_data: TokenData = Depends(require_role(OWNER))):
    tid = token_data.tenant_id
    _require_plan(tid)
    cur = settings(tid)
    sets: Dict[str, Any] = {"tenant_id": tid, "updated_at": _now(), "updated_by": token_data.email}
    if body.daily:
        sets["daily"] = {**cur["daily"], "enabled": body.daily.enabled, "hour": body.daily.hour, "minute": body.daily.minute}
    if body.weekly:
        sets["weekly"] = {**cur["weekly"], "enabled": body.weekly.enabled, "hour": body.weekly.hour,
                          "minute": body.weekly.minute,
                          "weekday": cur["weekly"]["weekday"] if body.weekly.weekday is None else body.weekly.weekday}
    _db.autopilot_config.update_one({"tenant_id": tid}, {"$set": sets}, upsert=True)
    return get_autopilot(token_data=token_data)


@router.post("/api/owner/autopilot/prepare")
def prepare_now(token_data: TokenData = Depends(require_role(OWNER))):
    tid = token_data.tenant_id
    _require_plan(tid)
    made = prepare(tid)
    return {"prepared": sum(1 for m in made if m.get("status") == "pending"),
            "empty": sum(1 for m in made if m.get("status") == "empty"), **get_autopilot(token_data=token_data)}


class Approve(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    exclude_ids: Optional[List[str]] = None


@router.post("/api/owner/autopilot/{proposal_id}/approve")
def approve(proposal_id: str, body: Approve = None, request: Request = None,
            token_data: TokenData = Depends(require_role(OWNER))):
    from features import campaigns_page as C
    tid = token_data.tenant_id
    _require_plan(tid)
    body = body or Approve()
    now = _now()
    p = _db.autopilot_proposals.find_one({"tenant_id": tid, "id": proposal_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Proposition introuvable")
    if p.get("status") != "pending":
        raise HTTPException(status_code=409, detail="Cette proposition a déjà été traitée.")
    if (_aware(p.get("expires_at")) or now) < now:
        _db.autopilot_proposals.update_one({"id": proposal_id}, {"$set": {"status": "expired"}})
        raise HTTPException(status_code=410, detail="Cette proposition a expiré : elle n'est plus envoyée.")
    # Claim it: two clicks must not send twice.
    claimed = _db.autopilot_proposals.update_one({"id": proposal_id, "status": "pending"}, {"$set": {"status": "sending"}})
    if not getattr(claimed, "modified_count", 1):
        raise HTTPException(status_code=409, detail="Cette proposition a déjà été traitée.")
    send_at = _aware(p.get("send_at"))
    # When it leaves: at the owner's time with a cron every 15 min; on the
    # daily cron, right away on its day — or, validated the day before, on the
    # morning run of its day (never a day early).
    go_at = None
    if send_at and precise() and send_at > now:
        go_at = send_at
    elif send_at and not precise() and send_at.astimezone(PARIS).date() > now.astimezone(PARIS).date():
        day = send_at.astimezone(PARIS).date()
        go_at = datetime(day.year, day.month, day.day, MORNING_UTC, tzinfo=timezone.utc)
    later = go_at is not None
    try:
        res = C.compose(C.Compose(
            title=(body.title or p["title"]).strip(), message=(body.message or p["message"]).strip(),
            segment="all", customer_ids=list(p.get("customer_ids") or []), exclude_ids=body.exclude_ids,
            schedule_at=go_at.isoformat() if later else None,
            template=f"autopilot_{p['kind']}", push=True, wallet=True), request=request, token_data=token_data)
    except HTTPException:
        _db.autopilot_proposals.update_one({"id": proposal_id}, {"$set": {"status": "pending"}})
        raise
    _db.campaigns.update_one({"id": res["id"]}, {"$set": {"autopilot_id": proposal_id,
                                                         "segment": p.get("segment") or "custom"}})
    status = "scheduled" if res.get("status") == "scheduled" else "sent"
    _db.autopilot_proposals.update_one({"id": proposal_id}, {"$set": {
        "status": status, "campaign_id": res["id"], "decided_by": token_data.email, "decided_at": now,
        "edited": bool(body.title or body.message),
        # What actually left — the history shows the owner's words.
        "title": (body.title or p["title"]).strip(), "message": (body.message or p["message"]).strip()}})
    return {"status": status, "campaign_id": res["id"], "audience": res.get("audience")}


@router.post("/api/owner/autopilot/{proposal_id}/skip")
def skip(proposal_id: str, token_data: TokenData = Depends(require_role(OWNER))):
    r = _db.autopilot_proposals.update_one(
        {"tenant_id": token_data.tenant_id, "id": proposal_id, "status": "pending"},
        {"$set": {"status": "skipped", "decided_by": token_data.email, "decided_at": _now()}})
    if not getattr(r, "modified_count", 1):
        raise HTTPException(status_code=409, detail="Cette proposition a déjà été traitée.")
    return {"status": "skipped"}
