"""
Super admin › Suivi d'équipe — FidClic's own team tasks (user, 2026-10-08:
« this is for us for planning the tasks related to fidclic »).

DECIDED WITH THE USER
    • The team is FidClic's team users (Sécurité › Utilisateurs). « Équipe »
      lists the ones on the board; a task goes to one or more of them, and
      any one of them ticking it finishes it.
    • Access is the « Suivi d'équipe » module of Sécurité › Rôles: Voir to
      see the board and the history, Modifier to add, tick, change, delete,
      comment and manage the team and the types.
    • A deadline is a day AND an hour (Paris time), always.
    • The status is never chosen, the platform reads it from the clock:
          à faire          not finished, deadline still ahead
          en retard        not finished, deadline passed
          terminée         finished before its deadline
          terminée en retard  finished after its deadline
      « En retard » counts both late kinds, shown apart. A person only
      ticks « Terminée » (and may untick a mistake), changes the day / hour /
      people, or deletes.
    • Types are a list the team edits (seven to start with), each a colour.
    • Description, comments, a per-task history, repeating tasks, and an
      « Historique » of every task ever made.
    • Bell (no e-mail): a task given to you, one hour before its deadline,
      and when it goes late (to its people and to the super admins).
      Computed when the bell or the page is read — no cron needed.
    • No limit on tasks per day; the week runs Monday → Sunday.
"""
from __future__ import annotations

import calendar
import csv
import io
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from models import TokenData
from features.platform_access import require_admin, TEAM_ROLES

router = APIRouter(tags=["admin"])
_db = None
PARIS = ZoneInfo("Europe/Paris")
MODULE = "equipe"

PRIORITIES = {"haute": "Haute", "moyenne": "Moyenne", "basse": "Basse"}
STATUS_LABELS = {"a_faire": "À faire", "en_retard": "En retard", "terminee": "Terminée",
                 "terminee_retard": "Terminée en retard", "supprimee": "Supprimée"}
DEFAULT_TYPES = [("marketing", "Marketing", "#2F6BFF"), ("operations", "Opérations", "#0EA5E9"),
                 ("stock", "Stock", "#14B8A6"), ("commercial", "Commercial", "#6366F1"),
                 ("support", "Support", "#F59E0B"), ("rh", "RH", "#A855F7"),
                 ("administratif", "Administratif", "#64748B")]
FREQS = {"daily": "Chaque jour", "weekdays": "Chaque jour ouvré (lun–ven)",
         "weekly": "Chaque semaine", "monthly": "Chaque mois"}
DAYS_FR = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]
HORIZON_MAX_DAYS = 400          # repeating tasks are written this far ahead at most


def init(db):
    global _db
    _db = db
    try:
        db.team_tasks.create_index("id", unique=True)
        db.team_tasks.create_index([("due_at", 1)])
        db.team_tasks.create_index([("series_id", 1), ("occurrence", 1)])
        db.team_task_events.create_index([("task_id", 1), ("at", 1)])
        db.team_task_comments.create_index([("task_id", 1), ("at", 1)])
        db.team_task_alerts.create_index([("to", 1), ("at", -1)])
        db.team_task_types.create_index("id", unique=True)
        db.team_board_members.create_index("email", unique=True)
    except Exception:
        pass
    if not db.team_task_types.count_documents({}):
        for i, (tid, name, color) in enumerate(DEFAULT_TYPES):
            db.team_task_types.insert_one({"id": tid, "name": name, "color": color, "order": i,
                                           "created_at": _now()})


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return _aware(datetime.fromisoformat(v.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _iso(v: Any) -> Optional[str]:
    d = _aware(v)
    return d.isoformat() if d else None


def _parse_day(s: Optional[str]) -> date:
    try:
        return date.fromisoformat(str(s or "")[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide (AAAA-MM-JJ).")


def _parse_time(s: Optional[str]) -> time:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (s or "").strip())
    if not m:
        raise HTTPException(status_code=400, detail="Heure obligatoire (HH:MM).")
    return time(int(m.group(1)), int(m.group(2)))


def _due(day: date, t: time) -> datetime:
    """A Paris day and hour → the UTC instant."""
    return datetime.combine(day, t, tzinfo=PARIS).astimezone(timezone.utc)


def _paris(d: datetime) -> datetime:
    return _aware(d).astimezone(PARIS)


def _today() -> date:
    return _now().astimezone(PARIS).date()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_label(mon: date) -> str:
    sun = mon + timedelta(days=6)
    if mon.month == sun.month:
        return f"Semaine du {mon.day} – {sun.day} {MONTHS_FR[sun.month - 1].capitalize()} {sun.year}"
    return (f"Semaine du {mon.day} {MONTHS_FR[mon.month - 1]} – {sun.day} {MONTHS_FR[sun.month - 1]} {sun.year}")


# ---------------------------------------------------------------------------
# Status — read from the clock, never chosen
# ---------------------------------------------------------------------------
def status_of(t: Dict[str, Any], now: Optional[datetime] = None) -> str:
    if t.get("deleted_at"):
        return "supprimee"
    now = now or _now()
    due = _aware(t.get("due_at"))
    done = _aware(t.get("completed_at"))
    if done:
        return "terminee_retard" if due and done > due else "terminee"
    return "en_retard" if due and now > due else "a_faire"


def _filter_keys(st: str) -> Set[str]:
    """The board's three status boxes: « Terminée » holds every finished
    task, « En retard » the late ones, finished or not."""
    return {"a_faire": {"a_faire"}, "en_retard": {"en_retard"}, "terminee": {"terminee"},
            "terminee_retard": {"terminee", "en_retard"}}.get(st, set())


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
def _users_by_email(emails: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    rows = _db.users.find({"email": {"$in": list(set(emails))}},
                          {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "role": 1,
                           "platform_role": 1, "active": 1})
    return {u["email"]: u for u in rows}


def _name(u: Optional[Dict[str, Any]], email: str) -> str:
    u = u or {}
    return " ".join(x for x in (u.get("first_name"), u.get("last_name")) if x) or email.split("@")[0]


def _role_name(u: Dict[str, Any]) -> str:
    from features.platform_access import role_id_of
    rid = role_id_of(u) if u else None
    r = _db.platform_roles.find_one({"id": rid}, {"_id": 0, "name": 1}) if rid else None
    return (r or {}).get("name") or ""


def _has_access(u: Optional[Dict[str, Any]]) -> bool:
    """Can this person open Suivi d'équipe (Voir)? Told on the board so the
    super admin knows who will not see their tasks."""
    if not u or u.get("active") is False:
        return False
    if u.get("role") == "super_admin":
        return True
    from features.platform_access import perms_for
    return bool(((perms_for(u["email"]) or {}).get(MODULE) or {}).get("view"))


def _board_emails() -> List[str]:
    return [m["email"] for m in _db.team_board_members.find({}, {"_id": 0, "email": 1}).sort("order", 1)]


def _person(email: str, users: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    u = users.get(email)
    return {"email": email, "name": _name(u, email)}


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
def _types() -> List[Dict[str, Any]]:
    return [{"id": t["id"], "name": t["name"], "color": t.get("color") or "#64748B"}
            for t in _db.team_task_types.find({}, {"_id": 0}).sort("order", 1)]


# ---------------------------------------------------------------------------
# Repeating tasks — a series writes its tasks ahead, lazily, as far as anyone
# looks (the week shown, the history asked, tomorrow for the bell).
# ---------------------------------------------------------------------------
def _occurs(series: Dict[str, Any], d: date) -> bool:
    start = date.fromisoformat(series["start"])
    if d < start:
        return False
    every = max(1, int(series.get("interval") or 1))
    f = series["freq"]
    if f == "daily":
        return (d - start).days % every == 0
    if f == "weekdays":
        return d.weekday() < 5
    if f == "weekly":
        days = series.get("weekdays") or [start.weekday()]
        weeks = (_monday(d) - _monday(start)).days // 7
        return d.weekday() in days and weeks % every == 0
    if f == "monthly":
        months = (d.year - start.year) * 12 + d.month - start.month
        if months % every:
            return False
        last = calendar.monthrange(d.year, d.month)[1]
        return d.day == min(start.day, last)            # the 31st falls on the month's last day
    return False


def _extend(series: Dict[str, Any], up_to: date) -> None:
    if not series.get("active", True):
        return
    up_to = min(up_to, _today() + timedelta(days=HORIZON_MAX_DAYS))
    end = series.get("end") or {}
    if end.get("until"):
        up_to = min(up_to, date.fromisoformat(end["until"]))
    done_until = date.fromisoformat(series["generated_until"]) if series.get("generated_until") else None
    d = (done_until + timedelta(days=1)) if done_until else date.fromisoformat(series["start"])
    if d > up_to:
        return
    count_max = int(end.get("count") or 0)
    made = _db.team_tasks.count_documents({"series_id": series["id"]}) if count_max else 0
    tpl = series["template"]
    hhmm = _parse_time(tpl["time"])
    now = _now()
    while d <= up_to:
        if count_max and made >= count_max:
            break
        if _occurs(series, d) and not _db.team_tasks.find_one({"series_id": series["id"], "occurrence": d.isoformat()},
                                                             {"_id": 1}):
            due = _due(d, hhmm)
            task = _new_task(tpl, due, series.get("created_by"), series_id=series["id"], occurrence=d.isoformat())
            # an occurrence written after its time is late, but not news
            if due <= now:
                task["late_sent"] = True
                task["reminder_sent"] = True
            _db.team_tasks.insert_one(task)
            made += 1
        d += timedelta(days=1)
    _db.team_task_series.update_one({"id": series["id"]}, {"$set": {"generated_until": min(d - timedelta(days=1), up_to).isoformat()}})


def _extend_all(up_to: date) -> None:
    for s in list(_db.team_task_series.find({"active": {"$ne": False}}, {"_id": 0})):
        try:
            _extend(s, up_to)
        except Exception as exc:                 # one bad series must not stop the board
            print(f"suivi d'équipe: series {s.get('id')} not extended ({exc})")


def _recurrence_label(series: Optional[Dict[str, Any]]) -> Optional[str]:
    if not series:
        return None
    every = max(1, int(series.get("interval") or 1))
    f = series["freq"]
    if f == "weekly":
        days = ", ".join(DAYS_FR[i].lower() for i in sorted(series.get("weekdays") or []))
        base = ("Chaque semaine" if every == 1 else f"Toutes les {every} semaines") + (f" ({days})" if days else "")
    elif f == "daily":
        base = "Chaque jour" if every == 1 else f"Tous les {every} jours"
    elif f == "monthly":
        base = "Chaque mois" if every == 1 else f"Tous les {every} mois"
    else:
        base = FREQS.get(f, f)
    end = series.get("end") or {}
    if end.get("until"):
        u = date.fromisoformat(end["until"])
        base += f", jusqu'au {u.day:02d}/{u.month:02d}/{u.year}"
    elif end.get("count"):
        base += f", {end['count']} fois"
    return base


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def _new_task(fields: Dict[str, Any], due: datetime, actor: Optional[str], series_id: Optional[str] = None,
              occurrence: Optional[str] = None) -> Dict[str, Any]:
    at = _now()
    return {
        "id": str(uuid.uuid4()),
        "title": fields["title"], "description": fields.get("description") or "",
        "type_id": fields.get("type_id"), "priority": fields.get("priority") or "moyenne",
        "assignees": list(fields.get("assignees") or []),
        "due_at": due, "created_at": at, "created_by": actor, "updated_at": at,
        "completed_at": None, "completed_by": None, "deleted_at": None, "deleted_by": None,
        "series_id": series_id, "occurrence": occurrence,
        "reminder_sent": False, "late_sent": False,
    }


def _event(task_id: str, actor: Optional[str], kind: str, text: str) -> None:
    _db.team_task_events.insert_one({"id": str(uuid.uuid4()), "task_id": task_id, "at": _now(),
                                     "actor": actor, "kind": kind, "text": text})


def _alert(to: Iterable[str], kind: str, task: Dict[str, Any], text: str, skip: Optional[str] = None) -> None:
    for email in set(to):
        if email and email != skip:
            _db.team_task_alerts.insert_one({"id": str(uuid.uuid4()), "to": email, "kind": kind,
                                             "task_id": task["id"], "text": text, "at": _now()})


def _due_text(due: datetime) -> str:
    p = _paris(due)
    return f"{DAYS_FR[p.weekday()].lower()} {p.day:02d}/{p.month:02d} à {p.hour:02d}:{p.minute:02d}"


def _view(t: Dict[str, Any], users: Dict[str, Dict[str, Any]], types: Dict[str, Dict[str, Any]],
          now: datetime, series: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    due = _aware(t.get("due_at"))
    p = _paris(due) if due else None
    ty = types.get(t.get("type_id") or "")
    st = status_of(t, now)
    s = (series or {}).get(t.get("series_id") or "")
    return {
        "id": t["id"], "title": t.get("title") or "", "description": t.get("description") or "",
        "type": {"id": ty["id"], "name": ty["name"], "color": ty["color"]} if ty else None,
        "priority": t.get("priority") or "moyenne", "priority_label": PRIORITIES.get(t.get("priority") or "moyenne"),
        "assignees": [_person(e, users) for e in t.get("assignees") or []],
        "due_at": _iso(due), "due_date": p.date().isoformat() if p else None,
        "due_time": f"{p.hour:02d}:{p.minute:02d}" if p else None,
        "status": st, "status_label": STATUS_LABELS[st],
        "completed_at": _iso(t.get("completed_at")),
        "completed_by": _person(t["completed_by"], users) if t.get("completed_by") else None,
        "late_by_minutes": int(((now if not t.get("completed_at") else _aware(t["completed_at"])) - due).total_seconds() // 60)
        if due and st in ("en_retard", "terminee_retard") else 0,
        "created_at": _iso(t.get("created_at")),
        "created_by": _person(t["created_by"], users) if t.get("created_by") else None,
        "deleted_at": _iso(t.get("deleted_at")),
        "repeat": _recurrence_label(s) if s else None,
        "series_id": t.get("series_id"),
        "comments": int(t.get("comments") or 0),
    }


def _ctx(tasks: List[Dict[str, Any]]):
    emails: Set[str] = set()
    for t in tasks:
        emails.update(t.get("assignees") or [])
        for k in ("completed_by", "created_by"):
            if t.get(k):
                emails.add(t[k])
    users = _users_by_email(emails)
    types = {x["id"]: x for x in _types()}
    sids = {t["series_id"] for t in tasks if t.get("series_id")}
    series = {s["id"]: s for s in _db.team_task_series.find({"id": {"$in": list(sids)}}, {"_id": 0})} if sids else {}
    return users, types, series


def _sweep(now: Optional[datetime] = None) -> None:
    """The bell's two clock alerts: one hour before, and once late."""
    now = now or _now()
    _extend_all((now + timedelta(days=1)).astimezone(PARIS).date())
    for t in list(_db.team_tasks.find({"completed_at": None, "deleted_at": None, "reminder_sent": {"$ne": True},
                                       "due_at": {"$gt": now, "$lte": now + timedelta(hours=1)}}, {"_id": 0})):
        if _db.team_tasks.update_one({"id": t["id"], "reminder_sent": {"$ne": True}},
                                     {"$set": {"reminder_sent": True}}).modified_count:
            _alert(t.get("assignees") or [], "reminder", t,
                   f"Échéance dans moins d'une heure : « {t['title']} » ({_due_text(_aware(t['due_at']))})")
    supers = [u["email"] for u in _db.users.find({"role": "super_admin", "active": {"$ne": False}}, {"_id": 0, "email": 1})]
    for t in list(_db.team_tasks.find({"completed_at": None, "deleted_at": None, "late_sent": {"$ne": True},
                                       "due_at": {"$lte": now}}, {"_id": 0})):
        if _db.team_tasks.update_one({"id": t["id"], "late_sent": {"$ne": True}},
                                     {"$set": {"late_sent": True}}).modified_count:
            _alert(list(t.get("assignees") or []) + supers, "late", t,
                   f"Tâche en retard : « {t['title']} » (échéance {_due_text(_aware(t['due_at']))})")


def _task_or_404(task_id: str) -> Dict[str, Any]:
    t = _db.team_tasks.find_one({"id": task_id}, {"_id": 0})
    if not t or t.get("deleted_at"):
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    return t


# ---------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------
def _week_tasks(mon: date) -> List[Dict[str, Any]]:
    start, end = _due(mon, time(0, 0)), _due(mon + timedelta(days=7), time(0, 0))
    return list(_db.team_tasks.find({"deleted_at": None, "due_at": {"$gte": start, "$lt": end}}, {"_id": 0}))


def _counts(tasks: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    c = {"total": len(tasks), "a_faire": 0, "en_retard": 0, "terminee": 0, "terminee_retard": 0}
    for t in tasks:
        c[status_of(t, now)] += 1
    c["done"] = c["terminee"] + c["terminee_retard"]
    c["late"] = c["en_retard"] + c["terminee_retard"]
    return c


def _pct(a: int, b: int) -> int:
    return round(a * 100 / b) if b else 0


def _member_rows(tasks: List[Dict[str, Any]], users: Dict[str, Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
    members = list(_db.team_board_members.find({}, {"_id": 0}).sort("order", 1))
    allu = _users_by_email([m["email"] for m in members])
    out = []
    for m in members:
        mine = [t for t in tasks if m["email"] in (t.get("assignees") or [])]
        c = _counts(mine, now)
        u = allu.get(m["email"])
        out.append({"email": m["email"], "name": _name(u, m["email"]),
                    "fonction": m.get("fonction") or (_role_name(u) if u else ""),
                    "assigned": c["total"], "done": c["done"], "pct": _pct(c["done"], c["total"]),
                    "late": c["en_retard"], "access": _has_access(u), "active": bool(u) and u.get("active") is not False})
    return out


@router.get("/api/admin/equipe/board")
def board(week: Optional[str] = None, token_data: TokenData = Depends(require_admin(MODULE))):
    now = _now()
    mon = _monday(_parse_day(week) if week else _today())
    _extend_all(mon + timedelta(days=6))
    _sweep(now)
    tasks = _week_tasks(mon)
    prev = _week_tasks(mon - timedelta(days=7))
    users, types, series = _ctx(tasks)
    c = _counts(tasks, now)
    views = [_view(t, users, types, now, series) for t in tasks]
    pr_rank = {"haute": 0, "moyenne": 1, "basse": 2}
    views.sort(key=lambda v: (v["due_at"] or "", pr_rank.get(v["priority"], 1), v["title"].lower()))
    days = []
    for i in range(7):
        d = mon + timedelta(days=i)
        rows = [v for v in views if v["due_date"] == d.isoformat()]
        done = sum(1 for v in rows if v["status"] in ("terminee", "terminee_retard"))
        days.append({"date": d.isoformat(), "name": DAYS_FR[i], "label": f"{d.day} {MONTHS_FR[d.month - 1][:3].capitalize()}.",
                     "short": f"{d.day} {['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin', 'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc'][d.month - 1]}",
                     "today": d == _today(), "tasks": rows, "total": len(rows), "done": done, "pct": _pct(done, len(rows))})
    status_counts = {k: sum(1 for v in views if k in _filter_keys(v["status"])) for k in ("a_faire", "terminee", "en_retard")}
    prio_counts = {k: sum(1 for v in views if v["priority"] == k) for k in PRIORITIES}
    type_counts = {}
    for v in views:
        key = v["type"]["id"] if v["type"] else ""
        type_counts[key] = type_counts.get(key, 0) + 1
    p = len(prev)
    return {
        "week": {"start": mon.isoformat(), "end": (mon + timedelta(days=6)).isoformat(), "label": _week_label(mon),
                 "is_current": mon == _monday(_today())},
        "kpis": {
            "total": c["total"], "total_delta": round((c["total"] - p) * 100 / p) if p else None,
            "done": c["done"], "done_pct": _pct(c["done"], c["total"]),
            "todo": c["a_faire"], "todo_pct": _pct(c["a_faire"], c["total"]),
            # « En retard »: still open past the deadline, and finished after it — apart
            "late_open": c["en_retard"], "late_done": c["terminee_retard"], "late": c["late"],
            "late_pct": _pct(c["late"], c["total"]),
        },
        "progress": {"done": c["done"], "total": c["total"], "pct": _pct(c["done"], c["total"])},
        "days": days,
        "members": _member_rows(tasks, users, now),
        "types": _types(),
        "priorities": [{"id": k, "name": v} for k, v in PRIORITIES.items()],
        "freqs": [{"id": k, "name": v} for k, v in FREQS.items()],
        "counts": {"status": status_counts, "priority": prio_counts, "type": type_counts},
        "now": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Create · change · tick · delete
# ---------------------------------------------------------------------------
class Recurrence(BaseModel):
    freq: str
    interval: int = Field(1, ge=1, le=52)
    weekdays: Optional[List[int]] = None
    until: Optional[str] = None
    count: Optional[int] = Field(None, ge=1, le=500)


class TaskIn(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = Field("", max_length=5000)
    type_id: Optional[str] = None
    priority: str = "moyenne"
    assignees: List[str]
    due_date: str
    due_time: str
    recurrence: Optional[Recurrence] = None


def _clean_fields(b: Any, partial: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if not partial or b.title is not None:
        title = re.sub(r"\s+", " ", (b.title or "").strip())
        if not title:
            raise HTTPException(status_code=400, detail="Donnez un titre à la tâche.")
        out["title"] = title[:200]
    if not partial or b.description is not None:
        out["description"] = (b.description or "").strip()[:5000]
    if not partial or b.type_id is not None:
        if b.type_id and not _db.team_task_types.find_one({"id": b.type_id}):
            raise HTTPException(status_code=400, detail="Type de tâche inconnu.")
        out["type_id"] = b.type_id or None
    if not partial or b.priority is not None:
        if b.priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail="Priorité inconnue.")
        out["priority"] = b.priority
    if not partial or b.assignees is not None:
        people = list(dict.fromkeys(e.strip().lower() for e in (b.assignees or []) if e and e.strip()))
        if not people:
            raise HTTPException(status_code=400, detail="Assignez la tâche à au moins une personne.")
        board_people = set(_board_emails())
        unknown = [e for e in people if e not in board_people]
        if unknown:
            raise HTTPException(status_code=400, detail="Assignez la tâche à des membres de l'équipe.")
        out["assignees"] = people[:20]
    return out


@router.post("/api/admin/equipe/tasks")
def create_task(body: TaskIn, token_data: TokenData = Depends(require_admin(MODULE))):
    actor = token_data.email
    fields = _clean_fields(body)
    day, hhmm = _parse_day(body.due_date), _parse_time(body.due_time)
    if body.recurrence:
        r = body.recurrence
        if r.freq not in FREQS:
            raise HTTPException(status_code=400, detail="Répétition inconnue.")
        days = sorted({int(x) for x in (r.weekdays or []) if 0 <= int(x) <= 6}) or [day.weekday()]
        until = _parse_day(r.until).isoformat() if r.until else None
        if until and until < day.isoformat():
            raise HTTPException(status_code=400, detail="La fin de la répétition est avant la première tâche.")
        series = {"id": str(uuid.uuid4()), "freq": r.freq, "interval": r.interval if r.freq in ("daily", "weekly", "monthly") else 1,
                  "weekdays": days if r.freq == "weekly" else None, "start": day.isoformat(),
                  "end": {"until": until, "count": r.count if not until else None},
                  "template": {**fields, "time": f"{hhmm.hour:02d}:{hhmm.minute:02d}"},
                  "generated_until": None, "active": True, "created_by": actor, "created_at": _now()}
        _db.team_task_series.insert_one(dict(series))
        _extend(series, max(day, _today()) + timedelta(days=14))
        first = _db.team_tasks.find_one({"series_id": series["id"]}, {"_id": 0}, sort=[("due_at", 1)])
        if not first:
            raise HTTPException(status_code=400, detail="Cette répétition ne tombe sur aucun jour : vérifiez les jours choisis.")
        for t in _db.team_tasks.find({"series_id": series["id"]}, {"_id": 0, "id": 1}):
            _event(t["id"], actor, "created", f"Tâche créée ({_recurrence_label(series).lower()})")
        _alert(fields["assignees"], "assigned", first,
               f"Nouvelle tâche répétée pour vous : « {fields['title']} » ({_recurrence_label(series).lower()})", skip=actor)
        return {"id": first["id"], "series_id": series["id"]}
    task = _new_task(fields, _due(day, hhmm), actor)
    if task["due_at"] <= _now():
        task["reminder_sent"] = True
    _db.team_tasks.insert_one(dict(task))
    _event(task["id"], actor, "created", "Tâche créée")
    _alert(fields["assignees"], "assigned", task,
           f"Nouvelle tâche pour vous : « {task['title']} » (échéance {_due_text(task['due_at'])})", skip=actor)
    return {"id": task["id"]}


class TaskEdit(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = Field(None, max_length=5000)
    type_id: Optional[str] = None
    priority: Optional[str] = None
    assignees: Optional[List[str]] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    apply_to: str = "this"            # « following »: the repeats after this one too


def _describe_changes(old: Dict[str, Any], new: Dict[str, Any], users: Dict[str, Dict[str, Any]]) -> List[str]:
    out = []
    types = {x["id"]: x["name"] for x in _types()}
    if new.get("title") is not None and new["title"] != old.get("title"):
        out.append(f"titre : « {new['title']} »")
    if new.get("description") is not None and new["description"] != (old.get("description") or ""):
        out.append("description modifiée")
    if "type_id" in new and new["type_id"] != old.get("type_id"):
        out.append(f"type : {types.get(new['type_id'], 'Sans type')}")
    if new.get("priority") and new["priority"] != old.get("priority"):
        out.append(f"priorité : {PRIORITIES[new['priority']]}")
    if new.get("assignees") is not None and set(new["assignees"]) != set(old.get("assignees") or []):
        out.append("assignée à " + ", ".join(_name(users.get(e), e) for e in new["assignees"]))
    if new.get("due_at") and _aware(new["due_at"]) != _aware(old.get("due_at")):
        out.append(f"échéance : {_due_text(new['due_at'])}")
    return out


@router.put("/api/admin/equipe/tasks/{task_id}")
def edit_task(task_id: str, body: TaskEdit, token_data: TokenData = Depends(require_admin(MODULE))):
    actor = token_data.email
    old = _task_or_404(task_id)
    fields = _clean_fields(body, partial=True)
    p = _paris(old["due_at"])
    day = _parse_day(body.due_date) if body.due_date else p.date()
    hhmm = _parse_time(body.due_time) if body.due_time else time(p.hour, p.minute)
    new_due = _due(day, hhmm)
    upd = {**fields, "due_at": new_due, "updated_at": _now()}
    if new_due != _aware(old["due_at"]):
        # a new deadline: the bell may speak again for it
        upd.update({"reminder_sent": new_due <= _now(), "late_sent": new_due <= _now() and bool(old.get("late_sent"))})
    users = _users_by_email(list(fields.get("assignees") or []) + list(old.get("assignees") or []))
    changes = _describe_changes(old, upd, users)
    _db.team_tasks.update_one({"id": task_id}, {"$set": upd})
    if changes:
        _event(task_id, actor, "updated", "Modifiée : " + " · ".join(changes))
    added = set(fields.get("assignees") or []) - set(old.get("assignees") or [])
    if added:
        _alert(added, "assigned", {**old, **upd}, f"Nouvelle tâche pour vous : « {upd.get('title') or old['title']} » "
                                                  f"(échéance {_due_text(new_due)})", skip=actor)
    touched = 1
    if body.apply_to == "following" and old.get("series_id"):
        # the repeats after this one take the same text, people and hour (their own day stays)
        series = _db.team_task_series.find_one({"id": old["series_id"]}, {"_id": 0})
        if series:
            tpl = {**series["template"], **fields, "time": f"{hhmm.hour:02d}:{hhmm.minute:02d}"}
            _db.team_task_series.update_one({"id": series["id"]}, {"$set": {"template": tpl}})
            for t in list(_db.team_tasks.find({"series_id": series["id"], "deleted_at": None, "completed_at": None,
                                               "occurrence": {"$gt": old.get("occurrence") or ""}}, {"_id": 0})):
                d2 = _due(date.fromisoformat(t["occurrence"]), hhmm)
                u2 = {**fields, "due_at": d2, "updated_at": _now()}
                ch = _describe_changes(t, u2, users)
                _db.team_tasks.update_one({"id": t["id"]}, {"$set": u2})
                if ch:
                    _event(t["id"], actor, "updated", "Modifiée avec la série : " + " · ".join(ch))
                touched += 1
    return {"id": task_id, "updated": touched}


class Done(BaseModel):
    done: bool = True


@router.post("/api/admin/equipe/tasks/{task_id}/complete")
def complete_task(task_id: str, body: Done, token_data: TokenData = Depends(require_admin(MODULE))):
    actor = token_data.email
    t = _task_or_404(task_id)
    if body.done:
        if t.get("completed_at"):
            return {"id": task_id, "status": status_of(t)}
        at = _now()
        _db.team_tasks.update_one({"id": task_id, "completed_at": None}, {"$set": {"completed_at": at, "completed_by": actor}})
        late = at > _aware(t["due_at"])
        _event(task_id, actor, "completed", "Marquée terminée" + (" (après l'échéance)" if late else ""))
    else:
        if not t.get("completed_at"):
            return {"id": task_id, "status": status_of(t)}
        _db.team_tasks.update_one({"id": task_id}, {"$set": {"completed_at": None, "completed_by": None}})
        _event(task_id, actor, "reopened", "Remise à faire (« Terminée » décochée)")
    return {"id": task_id, "status": status_of(_db.team_tasks.find_one({"id": task_id}, {"_id": 0}))}


@router.delete("/api/admin/equipe/tasks/{task_id}")
def delete_task(task_id: str, scope: str = "this", token_data: TokenData = Depends(require_admin(MODULE))):
    """Deleted tasks leave the board but stay in the Historique (« Supprimée »)."""
    actor = token_data.email
    t = _task_or_404(task_id)
    ids = [task_id]
    if scope == "following" and t.get("series_id"):
        # the series stops before this one; the open repeats after it go too
        until = (date.fromisoformat(t["occurrence"]) - timedelta(days=1)).isoformat()
        _db.team_task_series.update_one({"id": t["series_id"]}, {"$set": {"end.until": until, "end.count": None}})
        ids += [x["id"] for x in _db.team_tasks.find({"series_id": t["series_id"], "deleted_at": None, "completed_at": None,
                                                      "occurrence": {"$gt": t["occurrence"]}}, {"_id": 0, "id": 1})]
    at = _now()
    for i in ids:
        _db.team_tasks.update_one({"id": i, "deleted_at": None}, {"$set": {"deleted_at": at, "deleted_by": actor}})
        _event(i, actor, "deleted", "Supprimée" + (" (avec la suite de la série)" if len(ids) > 1 else ""))
    return {"deleted": len(ids)}


@router.post("/api/admin/equipe/tasks/{task_id}/stop-series")
def stop_series(task_id: str, token_data: TokenData = Depends(require_admin(MODULE))):
    """« Arrêter la répétition après cette tâche »."""
    t = _task_or_404(task_id)
    if not t.get("series_id"):
        raise HTTPException(status_code=400, detail="Cette tâche ne se répète pas.")
    _db.team_task_series.update_one({"id": t["series_id"]}, {"$set": {"end.until": t["occurrence"], "end.count": None}})
    later = [x["id"] for x in _db.team_tasks.find({"series_id": t["series_id"], "deleted_at": None, "completed_at": None,
                                                   "occurrence": {"$gt": t["occurrence"]}}, {"_id": 0, "id": 1})]
    at = _now()
    for i in later:
        _db.team_tasks.update_one({"id": i}, {"$set": {"deleted_at": at, "deleted_by": token_data.email}})
        _event(i, token_data.email, "deleted", "Supprimée (répétition arrêtée)")
    _event(task_id, token_data.email, "updated", "Répétition arrêtée après cette tâche")
    return {"removed": len(later)}


# ---------------------------------------------------------------------------
# One task: details, comments, history
# ---------------------------------------------------------------------------
@router.get("/api/admin/equipe/tasks/{task_id}")
def task_detail(task_id: str, token_data: TokenData = Depends(require_admin(MODULE))):
    t = _db.team_tasks.find_one({"id": task_id}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Tâche introuvable.")
    comments = list(_db.team_task_comments.find({"task_id": task_id, "deleted_at": None}, {"_id": 0}).sort("at", 1))
    events = list(_db.team_task_events.find({"task_id": task_id}, {"_id": 0}).sort("at", 1))
    users, types, series = _ctx([t])
    more = _users_by_email([c["author"] for c in comments] + [e["actor"] for e in events if e.get("actor")])
    users.update(more)
    return {
        "task": _view(t, users, types, _now(), series),
        "comments": [{"id": c["id"], "text": c["text"], "at": _iso(c["at"]), "author": _person(c["author"], users),
                      "mine": c["author"] == token_data.email} for c in comments],
        "events": [{"at": _iso(e["at"]), "text": e["text"], "kind": e["kind"],
                    "actor": _person(e["actor"], users) if e.get("actor") else None} for e in events],
    }


class CommentIn(BaseModel):
    text: str = Field(..., max_length=3000)


@router.post("/api/admin/equipe/tasks/{task_id}/comments")
def add_comment(task_id: str, body: CommentIn, token_data: TokenData = Depends(require_admin(MODULE))):
    t = _task_or_404(task_id)
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Le commentaire est vide.")
    c = {"id": str(uuid.uuid4()), "task_id": task_id, "author": token_data.email, "text": text[:3000],
         "at": _now(), "deleted_at": None}
    _db.team_task_comments.insert_one(dict(c))
    _db.team_tasks.update_one({"id": task_id}, {"$inc": {"comments": 1}})
    _alert(t.get("assignees") or [], "comment", t, f"Nouveau commentaire sur « {t['title']} »", skip=token_data.email)
    return {"id": c["id"]}


@router.delete("/api/admin/equipe/comments/{comment_id}")
def delete_comment(comment_id: str, token_data: TokenData = Depends(require_admin(MODULE))):
    c = _db.team_task_comments.find_one({"id": comment_id, "deleted_at": None}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Commentaire introuvable.")
    if c["author"] != token_data.email and token_data.role != "super_admin":
        raise HTTPException(status_code=403, detail="Seul son auteur peut supprimer ce commentaire.")
    _db.team_task_comments.update_one({"id": comment_id}, {"$set": {"deleted_at": _now()}})
    _db.team_tasks.update_one({"id": c["task_id"]}, {"$inc": {"comments": -1}})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Historique — every task ever made
# ---------------------------------------------------------------------------
def _history_rows(date_from: Optional[str], date_to: Optional[str], member: str, type_id: str,
                  status: str, priority: str, q: str) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    rng: Dict[str, Any] = {}
    if date_from:
        rng["$gte"] = _due(_parse_day(date_from), time(0, 0))
    if date_to:
        to = _parse_day(date_to)
        _extend_all(to)
        rng["$lt"] = _due(to + timedelta(days=1), time(0, 0))
    else:
        rng["$lt"] = _due(_today() + timedelta(days=1), time(0, 0))     # what has come due, by default
    query["due_at"] = rng
    if member:
        query["assignees"] = member
    if type_id:
        query["type_id"] = None if type_id == "none" else type_id
    if priority:
        query["priority"] = priority
    if status != "supprimee" and status != "toutes":
        query["deleted_at"] = None
    rows = list(_db.team_tasks.find(query, {"_id": 0}).sort("due_at", -1))
    now = _now()
    if status and status != "toutes":
        rows = [t for t in rows if status_of(t, now) == status
                or (status == "terminee" and status_of(t, now) == "terminee_retard")
                or (status == "en_retard" and status_of(t, now) == "terminee_retard")]
    if q:
        f = q.strip().lower()
        rows = [t for t in rows if f in (t.get("title") or "").lower() or f in (t.get("description") or "").lower()]
    return rows


@router.get("/api/admin/equipe/history")
def history(date_from: Optional[str] = None, date_to: Optional[str] = None, member: str = "", type_id: str = "",
            status: str = "", priority: str = "", q: str = "", page: int = 1, per_page: int = 25,
            token_data: TokenData = Depends(require_admin(MODULE))):
    rows = _history_rows(date_from, date_to, member, type_id, status, priority, q)
    per_page = max(10, min(int(per_page or 25), 100))
    pages = max(1, -(-len(rows) // per_page))
    page = max(1, min(int(page or 1), pages))
    chunk = rows[(page - 1) * per_page: page * per_page]
    users, types, series = _ctx(chunk)
    now = _now()
    c = _counts([t for t in rows if not t.get("deleted_at")], now)
    return {"rows": [_view(t, users, types, now, series) for t in chunk], "total": len(rows), "page": page,
            "pages": pages, "per_page": per_page, "summary": c,
            "members": [{"email": e, "name": _name(u, e)} for e, u in
                        ((e, _users_by_email([e]).get(e)) for e in _history_people())],
            "types": _types()}


def _history_people() -> List[str]:
    people = set(_board_emails())
    for t in _db.team_tasks.find({}, {"_id": 0, "assignees": 1}):
        people.update(t.get("assignees") or [])
    return sorted(people)


@router.get("/api/admin/equipe/history/export")
def history_export(date_from: Optional[str] = None, date_to: Optional[str] = None, member: str = "", type_id: str = "",
                   status: str = "", priority: str = "", q: str = "",
                   token_data: TokenData = Depends(require_admin(MODULE))):
    rows = _history_rows(date_from, date_to, member, type_id, status, priority, q)
    users, types, series = _ctx(rows)
    now = _now()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Tâche", "Description", "Type", "Priorité", "Assignée à", "Échéance", "Statut",
                "Terminée le", "Terminée par", "Retard (min)", "Répétition", "Créée le", "Créée par"])

    def fr(iso: Optional[str]) -> str:
        if not iso:
            return ""
        p = _paris(_aware(iso))
        return f"{p.day:02d}/{p.month:02d}/{p.year} {p.hour:02d}:{p.minute:02d}"
    for t in rows:
        v = _view(t, users, types, now, series)
        w.writerow([v["title"], v["description"], (v["type"] or {}).get("name", ""), v["priority_label"],
                    ", ".join(a["name"] for a in v["assignees"]), fr(v["due_at"]), v["status_label"],
                    fr(v["completed_at"]), (v["completed_by"] or {}).get("name", ""), v["late_by_minutes"] or "",
                    v["repeat"] or "", fr(v["created_at"]), (v["created_by"] or {}).get("name", "")])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="suivi-equipe-{_today().isoformat()}.csv"'})


# ---------------------------------------------------------------------------
# Équipe — who is on the board, and one person's breakdown
# ---------------------------------------------------------------------------
@router.get("/api/admin/equipe/members/candidates")
def candidates(token_data: TokenData = Depends(require_admin(MODULE))):
    """FidClic team users not on the board yet (Sécurité › Utilisateurs)."""
    on = set(_board_emails())
    rows = []
    for u in _db.users.find({"role": {"$in": list(TEAM_ROLES)}, "active": {"$ne": False}},
                            {"_id": 0, "email": 1, "first_name": 1, "last_name": 1, "role": 1, "platform_role": 1, "active": 1}):
        if u["email"] in on:
            continue
        rows.append({"email": u["email"], "name": _name(u, u["email"]), "role": _role_name(u), "access": _has_access(u)})
    rows.sort(key=lambda r: r["name"].lower())
    return {"rows": rows}


class MemberIn(BaseModel):
    email: str
    fonction: Optional[str] = Field("", max_length=60)


@router.post("/api/admin/equipe/members")
def add_member(body: MemberIn, token_data: TokenData = Depends(require_admin(MODULE))):
    email = (body.email or "").strip().lower()
    u = _db.users.find_one({"email": email, "role": {"$in": list(TEAM_ROLES)}}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=400, detail="Cette personne n'est pas un utilisateur de l'équipe FidClic.")
    if _db.team_board_members.find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Déjà dans l'équipe.")
    order = _db.team_board_members.count_documents({})
    _db.team_board_members.insert_one({"email": email, "fonction": (body.fonction or "").strip()[:60], "order": order,
                                       "added_at": _now(), "added_by": token_data.email})
    return {"email": email, "access": _has_access(u)}


@router.put("/api/admin/equipe/members/{email}")
def edit_member(email: str, body: MemberIn, token_data: TokenData = Depends(require_admin(MODULE))):
    r = _db.team_board_members.update_one({"email": email.lower()}, {"$set": {"fonction": (body.fonction or "").strip()[:60]}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Membre introuvable.")
    return {"email": email.lower()}


@router.delete("/api/admin/equipe/members/{email}")
def remove_member(email: str, token_data: TokenData = Depends(require_admin(MODULE))):
    """Off the board; their tasks and history stay as they are."""
    email = email.lower()
    open_tasks = _db.team_tasks.count_documents({"assignees": email, "deleted_at": None, "completed_at": None})
    _db.team_board_members.delete_one({"email": email})
    return {"removed": True, "open_tasks": open_tasks}


@router.get("/api/admin/equipe/members/{email}/breakdown")
def member_breakdown(email: str, week: Optional[str] = None, scope: str = "week",
                     token_data: TokenData = Depends(require_admin(MODULE))):
    """Click on a person: their tasks, by status, for the week or all time."""
    email = email.lower()
    now = _now()
    q: Dict[str, Any] = {"assignees": email, "deleted_at": None}
    if scope != "all":
        mon = _monday(_parse_day(week) if week else _today())
        _extend_all(mon + timedelta(days=6))
        q["due_at"] = {"$gte": _due(mon, time(0, 0)), "$lt": _due(mon + timedelta(days=7), time(0, 0))}
    # « Depuis le début »: every task they ever had, the planned ones included
    tasks = list(_db.team_tasks.find(q, {"_id": 0}).sort("due_at", 1))
    users, types, series = _ctx(tasks)
    u = _users_by_email([email]).get(email)
    c = _counts(tasks, now)
    views = [_view(t, users, types, now, series) for t in tasks]
    late_minutes = [v["late_by_minutes"] for v in views if v["status"] == "terminee_retard"]
    return {"email": email, "name": _name(u, email), "scope": scope,
            "counts": {**c, "pct": _pct(c["done"], c["total"]), "on_time_pct": _pct(c["terminee"], c["done"])},
            "avg_late_minutes": round(sum(late_minutes) / len(late_minutes)) if late_minutes else 0,
            "groups": [{"key": k, "label": STATUS_LABELS[k], "tasks": [v for v in views if v["status"] == k]}
                       for k in ("en_retard", "a_faire", "terminee_retard", "terminee")]}


# ---------------------------------------------------------------------------
# Types de tâches — the team's own list
# ---------------------------------------------------------------------------
class TypeIn(BaseModel):
    name: str = Field(..., max_length=40)
    color: Optional[str] = "#64748B"


def _color(c: Optional[str]) -> str:
    return c if c and re.fullmatch(r"#[0-9A-Fa-f]{6}", c) else "#64748B"


@router.post("/api/admin/equipe/types")
def add_type(body: TypeIn, token_data: TokenData = Depends(require_admin(MODULE))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom au type.")
    if _db.team_task_types.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
        raise HTTPException(status_code=409, detail="Ce type existe déjà.")
    tid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] + "-" + uuid.uuid4().hex[:4]
    _db.team_task_types.insert_one({"id": tid, "name": name, "color": _color(body.color),
                                    "order": _db.team_task_types.count_documents({}), "created_at": _now()})
    return {"id": tid}


@router.put("/api/admin/equipe/types/{type_id}")
def edit_type(type_id: str, body: TypeIn, token_data: TokenData = Depends(require_admin(MODULE))):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Donnez un nom au type.")
    clash = _db.team_task_types.find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "id": {"$ne": type_id}})
    if clash:
        raise HTTPException(status_code=409, detail="Ce type existe déjà.")
    r = _db.team_task_types.update_one({"id": type_id}, {"$set": {"name": name, "color": _color(body.color)}})
    if not r.matched_count:
        raise HTTPException(status_code=404, detail="Type introuvable.")
    return {"id": type_id}


@router.delete("/api/admin/equipe/types/{type_id}")
def delete_type(type_id: str, token_data: TokenData = Depends(require_admin(MODULE))):
    """Its tasks stay, « Sans type »."""
    if not _db.team_task_types.find_one({"id": type_id}):
        raise HTTPException(status_code=404, detail="Type introuvable.")
    moved = _db.team_tasks.update_many({"type_id": type_id}, {"$set": {"type_id": None}}).modified_count
    _db.team_task_series.update_many({"template.type_id": type_id}, {"$set": {"template.type_id": None}})
    _db.team_task_types.delete_one({"id": type_id})
    return {"deleted": True, "tasks": moved}


# ---------------------------------------------------------------------------
# The bell
# ---------------------------------------------------------------------------
@router.get("/api/admin/equipe/alerts")
def alerts(token_data: TokenData = Depends(require_admin(MODULE))):
    _sweep()
    rows = list(_db.team_task_alerts.find({"to": token_data.email, "at": {"$gte": _now() - timedelta(days=14)}},
                                          {"_id": 0}).sort("at", -1).limit(40))
    sev = {"late": "critical", "reminder": "warning", "assigned": "info", "comment": "info"}
    body = {"late": "Suivi d'équipe · en retard", "reminder": "Suivi d'équipe · échéance proche",
            "assigned": "Suivi d'équipe · nouvelle tâche", "comment": "Suivi d'équipe · commentaire"}
    return {"alerts": [{"id": f"task-{a['id']}", "severity": sev.get(a["kind"], "info"), "title": a["text"],
                        "body": body.get(a["kind"], "Suivi d'équipe"), "created_at": _iso(a["at"]),
                        "action": {"label": "Voir la tâche", "href": f"/admin/equipe?tache={a['task_id']}"}}
                       for a in rows]}
