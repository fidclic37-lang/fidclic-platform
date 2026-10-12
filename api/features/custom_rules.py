"""
« Nouvelle automatisation » (user's 29 mockups, 2026-10-11): the owner's own
automation, apart from the saved scenarios. Seven déclencheurs, each with its
own rule here (scenario "custom" in features/automations):

  on_date    Date spécifique — one day, one hour
  recurring  Récurrent — hebdomadaire / mensuelle / annuelle (date fixe,
             anniversaire du client, anniversaire d'inscription; rappel avant
             with its own texte) / personnalisée (tous les N jours, N fois
             par mois, jours ouvrés)
  action     Après une action client — achat, visite, inscription, offre
             utilisée (the till's « Offre utilisée »), palier de points atteint
  loyalty    Conditions sur la fidélité — points / visites / montant
  behavior   Comportement client — inactif or actif depuis N jours
  geo        Géolocalisation — ANY address (api-adresse) and its rayon
  other      Autre — a fixed list of rules the engine really checks

Planification + Règles d'envoi (step 5): the time zone (selectable), the
moment (immédiat / à une date-heure), the plage horaire, a limit per client,
« éviter les doublons » (a gap), the période d'activation / expiration, and a
note the engine never reads. Older « Personnalisée » rows (visits,
after_signup, after_visit, date) keep their rules in features/automations.
"""
from __future__ import annotations

import calendar
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from features import store_cards as _SC  # one card per establishment (multi-store)

_db = None


def init(db) -> None:
    global _db
    _db = db


V2 = ("on_date", "recurring", "action", "loyalty", "behavior", "geo", "other")
TIMED = ("on_date", "recurring", "behavior")
ACTIONS = {
    "purchase": "Achat effectué", "visit": "Visite en magasin", "signup": "Inscription au programme de fidélité",
    "offer_used": "Utilisation d'une offre", "tier_reached": "Atteinte d'un palier de points",
}
ACTION_EVENT = {"purchase": "visit", "visit": "visit", "signup": "signup", "offer_used": "offer_used",
                "tier_reached": "visit"}
REPEATS = ("once", "every", "gap")             # une seule fois / à chaque fois / au plus tous les N jours
PERIODS = ("weekly", "monthly", "yearly", "custom")
DATE_KINDS = ("fixed", "birthday", "signup")
OTHER_RULES = {
    "visits_in_days": ("visit", "X visites en Y jours"),
    "spent_in_days": ("purchase", "X € dépensés en Y jours"),
    "no_visit_days": ("inactivity", "Aucune visite depuis X jours"),
    "signup_anniversary": ("signup", "Anniversaire d'inscription"),
    "days_after_first_visit": ("visit", "X jours après la 1re visite"),
}
OTHER_EVENTS = {"visit": "Visite", "purchase": "Achat", "inactivity": "Inactivité client", "signup": "Inscription"}
OTHER_TIMED = ("no_visit_days", "signup_anniversary", "days_after_first_visit")
LIMIT_PER = {"trigger": "par déclenchement", "day": "par jour", "week": "par semaine", "month": "par mois",
             "ever": "au total"}
TIMEZONES = [
    ("Europe/Paris", "Paris"), ("Europe/Brussels", "Bruxelles"), ("Europe/Luxembourg", "Luxembourg"),
    ("Europe/Zurich", "Genève / Zurich"), ("Europe/Monaco", "Monaco"), ("Europe/London", "Londres"),
    ("America/Guadeloupe", "Guadeloupe"), ("America/Martinique", "Martinique"), ("America/Cayenne", "Guyane"),
    ("Indian/Reunion", "La Réunion"), ("Indian/Mayotte", "Mayotte"), ("America/Miquelon", "Saint-Pierre-et-Miquelon"),
    ("Pacific/Noumea", "Nouvelle-Calédonie"), ("Pacific/Tahiti", "Polynésie française"),
    ("Pacific/Wallis", "Wallis-et-Futuna"), ("America/Montreal", "Montréal"),
]
TZ_KEYS = {k for k, _ in TIMEZONES}
GEO_RADII = (50, 1000)
WEEKDAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
          "novembre", "décembre"]
HM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, date) and not isinstance(v, datetime):
        v = datetime(v.year, v.month, v.day)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# time zones
# ---------------------------------------------------------------------------
def tz_of(sched: Optional[Dict[str, Any]]):
    from zoneinfo import ZoneInfo
    key = (sched or {}).get("tz")
    return ZoneInfo(key if key in TZ_KEYS else "Europe/Paris")


def local(at: datetime, sched: Optional[Dict[str, Any]]) -> datetime:
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(tz_of(sched))


def from_local(d: date, hh: int, mm: int, sched: Optional[Dict[str, Any]]) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz_of(sched)).astimezone(timezone.utc)


def _hm(v: Any, default: Tuple[int, int] = (10, 0)) -> Tuple[int, int]:
    m = HM.fullmatch(str(v or "").strip())
    return (int(m.group(1)), int(m.group(2))) if m else default


def is_v2(row: Dict[str, Any]) -> bool:
    return row.get("scenario") == "custom" and (row.get("trigger") or {}).get("type") in V2


def is_timed(tr: Dict[str, Any]) -> bool:
    t = tr.get("type")
    return t in TIMED or (t == "other" and tr.get("rule") in OTHER_TIMED)


# ---------------------------------------------------------------------------
# checking what the editor sends
# ---------------------------------------------------------------------------
def _bad(msg: str):
    raise HTTPException(status_code=400, detail=msg)


def _int(v: Any, lo: int, hi: int, label: str) -> int:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        _bad(f"{label} : nombre invalide.")
    if n < lo or n > hi:
        _bad(f"{label} : entre {lo} et {hi}.")
    return n


def _num(v: Any, lo: float, hi: float, label: str) -> float:
    try:
        n = float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        _bad(f"{label} : nombre invalide.")
    if n < lo or n > hi:
        _bad(f"{label} : entre {lo:g} et {hi:g}.")
    return round(n, 2)


def _day(v: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        _bad(f"Choisissez {label}.")


def clean_trigger(tid: str, tr_in: Dict[str, Any], draft: bool, today: date) -> Dict[str, Any]:
    t = tr_in.get("type")
    if t not in V2:
        _bad("Choisissez un déclencheur.")
    tr: Dict[str, Any] = {"type": t}
    if t == "on_date":
        d = _day(tr_in.get("date"), "la date d'envoi")
        if not draft and d < today:
            _bad("Cette date est déjà passée.")
        tr["date"] = d.isoformat()
    elif t == "recurring":
        p = tr_in.get("period")
        if p not in PERIODS:
            _bad("Choisissez une périodicité.")
        tr["period"] = p
        if p == "weekly":
            tr["every_weeks"] = _int(tr_in.get("every_weeks", 1), 1, 4, "Fréquence d'envoi")
            days = sorted({_int(x, 0, 6, "Jour") for x in tr_in.get("weekdays") or []})
            if not days:
                _bad("Cochez au moins un jour d'envoi.")
            tr["weekdays"] = days
        elif p == "monthly":
            days = sorted({_int(x, 1, 31, "Jour du mois") for x in tr_in.get("monthdays") or []})
            if not days:
                _bad("Choisissez au moins un jour du mois.")
            if len(days) > 4:
                _bad("4 envois par mois au maximum.")
            tr["monthdays"] = days
        elif p == "yearly":
            kind = tr_in.get("date_kind") or "fixed"
            if kind not in DATE_KINDS:
                _bad("Date d'envoi inconnue.")
            tr["date_kind"] = kind
            if kind == "fixed":
                d = _day(tr_in.get("date"), "la date d'envoi")
                tr["date"] = d.isoformat()
            rem = tr_in.get("reminder") or {}
            tr["reminder"] = {"enabled": bool(rem.get("enabled")),
                              "days_before": _int(rem.get("days_before", 7), 1, 60, "Rappel avant la date")}
        else:
            mode = tr_in.get("rule") or "every_days"
            if mode not in ("every_days", "per_month"):
                _bad("Règle personnalisée inconnue.")
            tr["rule"] = mode
            if mode == "every_days":
                tr["every_days"] = _int(tr_in.get("every_days", 10), 1, 365, "Tous les … jours")
            else:
                tr["per_month"] = _int(tr_in.get("per_month", 2), 1, 10, "Fois par mois")
            tr["workdays_only"] = bool(tr_in.get("workdays_only"))
    elif t == "action":
        a = tr_in.get("action")
        if a not in ACTIONS:
            _bad("Choisissez l'action du client.")
        tr["action"] = a
        tr["repeat"] = tr_in.get("repeat") if tr_in.get("repeat") in REPEATS else "once"
        if tr["repeat"] == "gap":
            tr["every_days"] = _int(tr_in.get("every_days", 30), 1, 365, "Au plus une fois tous les")
        crit = tr_in.get("criteria") or {}
        tr["criteria"] = {"enabled": bool(crit.get("enabled")), "min_amount": None, "stores": []}
        if crit.get("enabled"):
            if crit.get("min_amount") not in (None, ""):
                tr["criteria"]["min_amount"] = _num(crit["min_amount"], 0, 100000, "Montant minimum d'achat")
            tr["criteria"]["stores"] = [str(x) for x in crit.get("stores") or [] if x][:50]
            if a == "offer_used" and crit.get("offer_id"):
                tr["criteria"]["offer_id"] = str(crit["offer_id"])
    elif t == "loyalty":
        tr["match"] = "all" if tr_in.get("match") == "all" else "any"
        tr["repeat"] = "each" if tr_in.get("repeat") == "each" else "once"
        got = 0
        for k, label, hi in (("points", "Nombre de points", 1000000), ("visits", "Nombre de visites", 100000),
                             ("amount", "Montant d'achats", 10000000)):
            v = tr_in.get(k)
            if v in (None, ""):
                tr[k] = None
                continue
            tr[k] = _num(v, 1, hi, label) if k == "amount" else _int(v, 1, hi, label)
            got += 1
        if not got:
            _bad("Indiquez au moins une condition : points, visites ou montant.")
    elif t == "behavior":
        tr["client_status"] = tr_in.get("client_status") if tr_in.get("client_status") in ("all", "existing", "new") \
            else "existing"
        tr["activity"] = "active" if tr_in.get("activity") == "active" else "inactive"
        unit = tr_in.get("unit") if tr_in.get("unit") in ("days", "weeks", "months") else "days"
        tr["unit"] = unit
        tr["value"] = _int(tr_in.get("value", 30), 1, 365 if unit == "days" else (52 if unit == "weeks" else 24),
                           "Délai depuis la dernière visite")
        tr["segment"] = str(tr_in.get("segment")) if tr_in.get("segment") else None
    elif t == "geo":
        addr = re.sub(r"\s+", " ", str(tr_in.get("address") or "")).strip()[:200]
        try:
            lat, lng = float(tr_in.get("lat")), float(tr_in.get("lng"))
        except (TypeError, ValueError):
            lat = lng = None
        if lat is None or not (-90 <= lat <= 90 and -180 <= lng <= 180):
            if not draft:
                _bad("Choisissez une adresse ou un établissement.")
            lat = lng = None
        tr.update({"address": addr, "lat": lat, "lng": lng,
                   "radius_m": _int(tr_in.get("radius_m", 300), GEO_RADII[0], GEO_RADII[1], "Rayon de détection"),
                   "new_only": bool(tr_in.get("new_only"))})
        days = tr_in.get("days") if tr_in.get("days") in ("all", "weekdays", "weekend") else "all"
        f, to = str(tr_in.get("from") or "09:00"), str(tr_in.get("to") or "22:00")
        if not HM.fullmatch(f) or not HM.fullmatch(to):
            _bad("Plage d'activation invalide.")
        if to <= f:
            _bad("La fin de la plage d'activation doit être après son début.")
        tr.update({"days": days, "from": f, "to": to})
    else:  # other
        rule = tr_in.get("rule")
        if rule not in OTHER_RULES:
            _bad("Choisissez une condition.")
        name = re.sub(r"\s+", " ", str(tr_in.get("rule_name") or "")).strip()
        if not name and not draft:
            _bad("Donnez un nom à la règle.")
        if len(name) > 60:
            _bad("Nom de la règle : 60 caractères au maximum.")
        tr.update({"rule": rule, "rule_name": name, "event": OTHER_RULES[rule][0]})
        if rule in ("visits_in_days", "spent_in_days"):
            tr["x"] = _num(tr_in.get("x", 3), 1, 100000, "Montant") if rule == "spent_in_days" else \
                _int(tr_in.get("x", 3), 1, 1000, "Nombre de visites")
            tr["y"] = _int(tr_in.get("y", 60), 1, 365, "Période (jours)")
        elif rule in ("no_visit_days", "days_after_first_visit"):
            tr["x"] = _int(tr_in.get("x", 30), 1, 365, "Nombre de jours")
        tr["delay_days"] = _int(tr_in.get("delay_days", 0), 0, 365, "Délai d'envoi")
        notes = str(tr_in.get("notes") or "").strip()
        if len(notes) > 500:
            _bad("Notes internes : 500 caractères au maximum.")
        tr["notes"] = notes
    if t == "action":
        tr["delay_value"] = _int(tr_in.get("delay_value", 0), 0, 365, "Délai après l'action")
        tr["delay_unit"] = tr_in.get("delay_unit") if tr_in.get("delay_unit") in ("minutes", "hours", "days") else "days"
    elif t == "other" and tr["rule"] not in OTHER_TIMED:
        tr["delay_value"], tr["delay_unit"] = tr["delay_days"], "days"
    else:
        tr["delay_value"], tr["delay_unit"] = 0, "hours"
    return tr


def clean_schedule(s: Any, tr: Dict[str, Any], draft: bool, status: str, today: date) -> Dict[str, Any]:
    """Step 5: Planification + Règles d'envoi."""
    g = (lambda k, d=None: getattr(s, k, d)) if not isinstance(s, dict) else (lambda k, d=None: s.get(k, d))
    tz = g("tz") or "Europe/Paris"
    if tz not in TZ_KEYS:
        _bad("Fuseau horaire inconnu.")
    hour = None
    if is_timed(tr):
        m = HM.fullmatch(str(g("hour") or "10:00").strip())
        if not m:
            _bad("Heure d'envoi invalide.")
        hour = m.group(0)
    window = bool(g("window"))
    wf, wt = str(g("window_from") or "09:00").strip(), str(g("window_to") or "20:00").strip()
    if window:
        if not HM.fullmatch(wf) or not HM.fullmatch(wt):
            _bad("Plage horaire invalide.")
        if wt <= wf:
            _bad("La fin de la plage horaire doit être après son début.")
        if hour and not (wf <= hour < wt):
            _bad(f"L'heure d'envoi ({hour}) doit être comprise dans la plage horaire ({wf} – {wt}).")
    send_mode = "at" if g("send_mode") == "at" and not is_timed(tr) and tr.get("type") != "geo" else "immediate"
    send_at = None
    if send_mode == "at":
        raw = str(g("send_at") or "").strip()
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})T([01]\d|2[0-3]):([0-5]\d)", raw[:16])
        if not m:
            _bad("Choisissez la date et l'heure d'envoi.")
        send_at = raw[:16]
        if not draft and status == "active" and date.fromisoformat(m.group(1)) < today:
            _bad("La date d'envoi est déjà passée.")
    lim = g("limit") or {}
    per = lim.get("per") if lim.get("per") in LIMIT_PER else "trigger"
    count = _int(lim.get("count", 1), 1, 10, "Limite par client")
    dedupe = bool(g("dedupe"))
    gap = _int(g("min_gap_days", 7) if g("min_gap_days") is not None else 7, 1, 365, "Délai minimum entre deux envois")
    valid = {}
    for key, label in (("valid_from", "Date de début"), ("valid_to", "Date de fin")):
        raw = str(g(key) or "").strip()
        valid[key] = _day(raw, label.lower()).isoformat() if raw else None
    if valid["valid_from"] and valid["valid_to"] and valid["valid_to"] < valid["valid_from"]:
        _bad("La date de fin doit être après la date de début.")
    if not draft and status == "active" and valid["valid_to"] and valid["valid_to"] < today.isoformat():
        _bad("La date de fin est déjà passée : choisissez une nouvelle date pour l'activer.")
    if tr.get("type") == "on_date" and valid["valid_to"] and valid["valid_to"] < tr["date"]:
        _bad("La date d'expiration est avant la date d'envoi : le message ne partirait jamais.")
    note = str(g("rules_note") or "").strip()
    if len(note) > 500:
        _bad("Conditions supplémentaires : 500 caractères au maximum.")
    return {"tz": tz, "hour": hour, "window": window, "window_from": wf, "window_to": wt,
            "send_mode": send_mode, "send_at": send_at, "limit": {"count": count, "per": per},
            "dedupe": dedupe, "min_gap_days": gap, "rules_note": note, **valid,
            # read by the shared helpers (days / holidays): every day, holidays included
            "days": "all", "weekdays": [0, 1, 2, 3, 4, 5, 6], "holidays": True, "smart": False, "slots": [],
            "daily_limit": None}


# ---------------------------------------------------------------------------
# when a time déclencheur is due
# ---------------------------------------------------------------------------
def _month_day(d: date, want: int) -> int:
    return min(want, calendar.monthrange(d.year, d.month)[1])        # « le 31 » = last day


def _anchor(row: Dict[str, Any]) -> date:
    s = row.get("schedule") or {}
    try:
        return date.fromisoformat(str(s.get("valid_from") or "")[:10])
    except ValueError:
        c = _aware(row.get("created_at")) or _now()
        return local(c, s).date()


def per_month_days(d: date, n: int) -> List[int]:
    """« N fois par mois »: evenly through the month (2 → 1 and 16 on 31 days)."""
    last = calendar.monthrange(d.year, d.month)[1]
    return sorted({1 + (i * last) // n for i in range(n)})


def date_due(row: Dict[str, Any], d: date) -> bool:
    """Is the shop-wide date (not a per-client one) today, in the row's zone?"""
    tr = row.get("trigger") or {}
    t = tr.get("type")
    if t == "on_date":
        return tr.get("date") == d.isoformat()
    if t != "recurring":
        return False
    p = tr.get("period")
    if p == "weekly":
        if d.weekday() not in (tr.get("weekdays") or []):
            return False
        a = _anchor(row)
        a_monday = a - timedelta(days=a.weekday())
        weeks = ((d - timedelta(days=d.weekday())) - a_monday).days // 7
        return weeks >= 0 and weeks % max(1, int(tr.get("every_weeks") or 1)) == 0
    if p == "monthly":
        return d.day in {_month_day(d, int(x)) for x in tr.get("monthdays") or []}
    if p == "yearly":
        return False                                           # per client (fixed: see yearly_people)
    if p == "custom":
        if tr.get("workdays_only") and d.weekday() >= 5:
            return False
        if tr.get("rule") == "per_month":
            return d.day in per_month_days(d, int(tr.get("per_month") or 1))
        diff = (d - _anchor(row)).days
        return diff >= 0 and diff % max(1, int(tr.get("every_days") or 1)) == 0
    return False


def _md(d: date) -> str:
    return d.strftime("%m-%d")


def _yearly_match(md: str, d: date) -> bool:
    if md == "02-29" and not calendar.isleap(d.year):
        return _md(d) == "02-28"
    return md == _md(d)


def yearly_people(tid: str, row: Dict[str, Any], d: date, people: List[Dict[str, Any]]
                  ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Annuelle: the day itself, and its reminder N days before (own texte)."""
    tr = row.get("trigger") or {}
    kind = tr.get("date_kind") or "fixed"
    rem = tr.get("reminder") or {}
    want = [(d, False)]
    if rem.get("enabled"):
        want.append((d + timedelta(days=int(rem.get("days_before") or 7)), True))
    out = []
    for c in people:
        if kind == "fixed":
            md = str(tr.get("date") or "")[5:10]
        elif kind == "birthday":
            md = str(c.get("birthday") or "")[-5:]
        else:
            j = _aware(c.get("created_at"))
            md = _md(local(j, row.get("schedule")).date()) if j else ""
        if not re.fullmatch(r"\d{2}-\d{2}", md or ""):
            continue
        for day, is_rem in want:
            if _yearly_match(md, day):
                if kind == "signup":
                    j = _aware(c.get("created_at"))
                    if not j or local(j, row.get("schedule")).date().year >= day.year:
                        continue                                # the signup day itself is not an anniversary
                out.append((c, {"event": "date", "reminder": is_rem, "year": day.year}))
    return out


def _last_visit(c: Dict[str, Any]) -> Optional[datetime]:
    return _aware(c.get("last_visit_date"))


def behavior_people(tid: str, row: Dict[str, Any], at: datetime, people: List[Dict[str, Any]]
                    ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    tr = row.get("trigger") or {}
    days = int(tr.get("value") or 30) * {"days": 1, "weeks": 7, "months": 30}[tr.get("unit") or "days"]
    seg = None
    if tr.get("segment"):
        from features import automations as AU
        seg = AU._segment_ids(tid, tr["segment"], at) or set()
    out = []
    for c in people:
        n = int(c.get("visits") or 0)
        st = tr.get("client_status") or "existing"
        if (st == "existing" and n < 1) or (st == "new" and n > 0):
            continue
        if seg is not None and c["id"] not in seg:
            continue
        last = _last_visit(c) or _aware(c.get("created_at"))
        if not last:
            continue
        idle = (at - last).days
        q = {"tenant_id": tid, "automation_id": row["id"], "customer_id": c["id"]}
        if tr.get("activity") == "active":
            if idle > days:
                continue
            prev = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
            if prev and at - _aware(prev["sent_at"]) < timedelta(days=days):
                continue                                         # once per period while active
        else:
            if idle < days:
                continue
            if _db.automation_log.find_one({**q, "sent_at": {"$gte": last}}):
                continue                                         # once per absence; a visit starts a new one
        out.append((c, {"event": "date", "idle_days": idle}))
    return out


def _first_visit(c: Dict[str, Any]) -> Optional[datetime]:
    v = _db.visits.find_one({"customer_id": c["id"]}, {"_id": 0, "visit_time": 1}, sort=[("visit_time", 1)])
    return _aware((v or {}).get("visit_time")) or (_aware(c.get("created_at")) if int(c.get("visits") or 0) else None)


def other_timed_people(tid: str, row: Dict[str, Any], at: datetime, people: List[Dict[str, Any]]
                       ) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    tr = row.get("trigger") or {}
    sched = row.get("schedule") or {}
    today = local(at, sched).date()
    delay = int(tr.get("delay_days") or 0)
    out = []
    for c in people:
        q = {"tenant_id": tid, "automation_id": row["id"], "customer_id": c["id"]}
        rule = tr.get("rule")
        if rule == "no_visit_days":
            last = _last_visit(c)
            if not last or (at - last).days < int(tr.get("x") or 30) + delay:
                continue
            if _db.automation_log.find_one({**q, "sent_at": {"$gte": last}}):
                continue
        elif rule == "signup_anniversary":
            j = _aware(c.get("created_at"))
            if not j:
                continue
            day = today - timedelta(days=delay)
            jd = local(j, sched).date()
            if jd.year >= day.year or not _yearly_match(_md(jd), day):
                continue
            if _db.automation_log.find_one({**q, "year": day.year}):
                continue
            out.append((c, {"event": "date", "year": day.year}))
            continue
        elif rule == "days_after_first_visit":
            first = _first_visit(c)
            if not first or local(first, sched).date() + timedelta(days=int(tr.get("x") or 30) + delay) != today:
                continue
            if _db.automation_log.find_one(q):
                continue
        else:
            continue
        out.append((c, {"event": "date"}))
    return out


def due_people(tid: str, row: Dict[str, Any], at: datetime) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """A time déclencheur at its hour today: who gets it (before Ciblage)."""
    tr = row.get("trigger") or {}
    sched = row.get("schedule") or {}
    d = local(at, sched).date()
    people = list(_db.customers.find({"tenant_id": tid, "deleted_at": None}, {"_id": 0}))
    t = tr.get("type")
    if t == "recurring" and tr.get("period") == "yearly":
        return yearly_people(tid, row, d, people)
    if t in ("on_date", "recurring"):
        if not date_due(row, d):
            return []
        return [(c, {"event": "date", "day": d.isoformat()}) for c in people]
    if t == "behavior":
        return behavior_people(tid, row, at, people)
    if t == "other":
        return other_timed_people(tid, row, at, people)
    return []


def next_dates(row: Dict[str, Any], start: date, n: int = 5) -> List[str]:
    """« Prochaines dates d'envoi » (shop-wide dates only)."""
    tr = row.get("trigger") or {}
    out: List[str] = []
    if tr.get("type") == "recurring" and tr.get("period") == "yearly":
        if (tr.get("date_kind") or "fixed") != "fixed":
            return []
        md = str(tr.get("date") or "")[5:10]
        y = start.year
        while len(out) < n and md:
            try:
                d = date(y, int(md[:2]), int(md[3:]))
            except ValueError:
                d = date(y, 2, 28)
            if d >= start:
                out.append(d.isoformat())
            y += 1
        return out
    d = start
    for _ in range(800):
        if date_due(row, d):
            out.append(d.isoformat())
            if len(out) >= n or tr.get("type") == "on_date":
                break
        d += timedelta(days=1)
    s = row.get("schedule") or {}
    if s.get("valid_from"):
        out = [x for x in out if x >= s["valid_from"]]
    if s.get("valid_to"):
        out = [x for x in out if x <= s["valid_to"]]
    return out


# ---------------------------------------------------------------------------
# when an event déclencheur fires (visit, signup, offer used, geo)
# ---------------------------------------------------------------------------
def _state(row: Dict[str, Any], cust: Dict[str, Any], met: bool) -> bool:
    """Was the condition false at the last look? Keeps the new look."""
    key = {"automation_id": row["id"], "customer_id": cust["id"]}
    prev = _db.custom_state.find_one(key) or {}
    _db.custom_state.update_one(key, {"$set": {**key, "met": met, "at": _now()}}, upsert=True)
    return not prev.get("met")


def _visits_since(cid: str, since: datetime) -> List[Dict[str, Any]]:
    return list(_db.visits.find({"customer_id": cid, "visit_time": {"$gte": since}}, {"_id": 0, "amount_paid": 1}))


def tiers_crossed(tid: str, before: int, after: int) -> List[Dict[str, Any]]:
    from features import loyalty_card as LC
    return [t for t in LC.tiers_for(tid) if before < int(t.get("min") or 0) <= after]


@_SC.customer_store("cust")
def eligible(tid: str, row: Dict[str, Any], cust: Dict[str, Any], ctx: Dict[str, Any], at: datetime) -> bool:
    """The déclencheur's own rule for an event (Ciblage already holds)."""
    tr = row.get("trigger") or {}
    t = tr.get("type")
    ev = ctx.get("event")
    q = {"tenant_id": tid, "automation_id": row["id"], "customer_id": cust["id"]}
    if t == "action":
        a = tr.get("action")
        if ev != ACTION_EVENT.get(a):
            return False
        crit = tr.get("criteria") or {}
        amount = float(ctx.get("amount") or 0)
        if a == "purchase" and amount <= 0:
            return False                                        # a visit without a purchase
        if crit.get("enabled"):
            if crit.get("min_amount") and amount < float(crit["min_amount"]):
                return False
            if crit.get("stores") and ctx.get("branch_id") not in crit["stores"]:
                return False
            if a == "offer_used" and crit.get("offer_id") and ctx.get("offer_id") != crit["offer_id"]:
                return False
        if a == "tier_reached":
            # paliers are measured as loyalty_card.tier_of measures them: visits on a
            # stamps card, points otherwise
            from features import loyalty_card as LC
            tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
            stamps = LC._programme(tpl) == "stamps"
            key = "visits" if stamps else "points"
            if ctx.get(f"{key}_before") is None:
                return False
            crossed = tiers_crossed(tid, int(ctx[f"{key}_before"]), int(cust.get(key) or 0))
            if not crossed:
                return False
            ctx["palier"] = crossed[-1].get("label") or ""
        rep = tr.get("repeat") or "once"
        if rep == "once" and (_db.automation_log.find_one(q) or _db.automation_queue.find_one(q)):
            return False
        if rep == "gap":
            last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
            if last and at - _aware(last["sent_at"]) < timedelta(days=int(tr.get("every_days") or 30)):
                return False
        if _db.automation_queue.find_one(q):
            return False                                        # one waiting at a time per client
        return True
    if t == "loyalty":
        if ev != "visit":
            return False
        checks = []
        if tr.get("points") is not None:
            checks.append(int(cust.get("points") or 0) >= int(tr["points"]))
        if tr.get("visits") is not None:
            checks.append(int(cust.get("visits") or 0) >= int(tr["visits"]))
        if tr.get("amount") is not None:
            checks.append(float(cust.get("total_amount_paid") or 0) >= float(tr["amount"]))
        met = bool(checks) and (all(checks) if tr.get("match") == "all" else any(checks))
        newly = _state(row, cust, met)
        if not met:
            return False
        if tr.get("repeat") == "each":
            return newly                                         # each new time the conditions come true
        return not (_db.automation_log.find_one(q) or _db.automation_queue.find_one(q))
    if t == "other":
        rule = tr.get("rule")
        if rule in OTHER_TIMED or ev != "visit":
            return False
        since = at - timedelta(days=int(tr.get("y") or 60))
        vs = _visits_since(cust["id"], since)
        if rule == "visits_in_days":
            met = len(vs) >= int(tr.get("x") or 3)
        else:
            met = sum(float(v.get("amount_paid") or 0) for v in vs) >= float(tr.get("x") or 0)
        newly = _state(row, cust, met)
        return met and newly and not _db.automation_queue.find_one(q)
    if t == "geo":
        if ev != "geo" or tr.get("lat") is None:
            return False
        from features import geo_automation as GA
        if GA.distance_m(float(ctx["lat"]), float(ctx["lng"]), float(tr["lat"]), float(tr["lng"])) > int(tr.get("radius_m") or 300):
            return False
        loc = local(at, row.get("schedule"))
        days = tr.get("days") or "all"
        if (days == "weekdays" and loc.weekday() >= 5) or (days == "weekend" and loc.weekday() < 5):
            return False
        hm = loc.strftime("%H:%M")
        if not (str(tr.get("from") or "00:00") <= hm < str(tr.get("to") or "23:59")):
            return False
        if tr.get("new_only") and int(cust.get("visits") or 0) > 0:
            return False
        return True
    return False


def rules_ok(row: Dict[str, Any], cust: Dict[str, Any], at: datetime, ctx: Optional[Dict[str, Any]] = None) -> bool:
    """Règles d'envoi: the limit per client and « éviter les doublons »."""
    s = row.get("schedule") or {}
    q = {"tenant_id": row["tenant_id"], "automation_id": row["id"], "customer_id": cust["id"]}
    if s.get("dedupe"):
        last = _db.automation_log.find_one(q, sort=[("sent_at", -1)])
        if last and at - _aware(last["sent_at"]) < timedelta(days=int(s.get("min_gap_days") or 7)):
            return False
    lim = s.get("limit") or {}
    per = lim.get("per") or "trigger"
    if per != "trigger":
        count = int(lim.get("count") or 1)
        loc = local(at, s)
        if per == "ever":
            since = None
        elif per == "day":
            since = from_local(loc.date(), 0, 0, s)
        elif per == "week":
            since = from_local(loc.date() - timedelta(days=loc.weekday()), 0, 0, s)
        else:
            since = from_local(loc.date().replace(day=1), 0, 0, s)
        qq = dict(q, **({"sent_at": {"$gte": since}} if since else {}))
        if _db.automation_log.count_documents(qq) >= count:
            return False
    return True


def send_moment(row: Dict[str, Any], due: datetime) -> datetime:
    """« Moment d'envoi : à une date / heure spécifique » holds events until then."""
    s = row.get("schedule") or {}
    if s.get("send_mode") != "at" or not s.get("send_at"):
        return due
    try:
        d = date.fromisoformat(s["send_at"][:10])
        hh, mm = _hm(s["send_at"][11:16])
        return max(due, from_local(d, hh, mm, s))
    except ValueError:
        return due


# ---------------------------------------------------------------------------
# Géolocalisation: the card's position (and the Wallet pass)
# ---------------------------------------------------------------------------
def geo_rows(tid: str) -> List[Dict[str, Any]]:
    return [r for r in _db.automations.find({"tenant_id": tid, "scenario": "custom", "status": "active",
                                             "trigger.type": "geo"}, {"_id": 0})
            if (r.get("trigger") or {}).get("lat") is not None]


def geo_open(row: Dict[str, Any], at: datetime) -> bool:
    """Inside the déclencheur's « Plage d'activation » and the règles' plage horaire."""
    tr = row.get("trigger") or {}
    s = row.get("schedule") or {}
    loc = local(at, s)
    days = tr.get("days") or "all"
    if (days == "weekdays" and loc.weekday() >= 5) or (days == "weekend" and loc.weekday() < 5):
        return False
    hm = loc.strftime("%H:%M")
    if not (str(tr.get("from") or "00:00") <= hm < str(tr.get("to") or "23:59")):
        return False
    if s.get("window") and not (str(s.get("window_from") or "00:00") <= hm < str(s.get("window_to") or "23:59")):
        return False
    return True


@_SC.customer_store("cust")
def pass_geo(row: Dict[str, Any], cust: Dict[str, Any], at: datetime, cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What the Wallet pass carries for a custom géolocalisation (lock screen near the address)."""
    from features import automations as AU
    tid = row["tenant_id"]
    tr = row.get("trigger") or {}
    if not AU.running(row, at) or not geo_open(row, at) or not AU.matches(tid, row, cust, at, cache):
        return None
    if tr.get("new_only") and int(cust.get("visits") or 0) > 0:
        return None
    if not rules_ok(row, cust, at):
        return None
    tenant = _db.tenants.find_one({"id": tid}) or {}
    tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
    msg = row.get("message") or {}
    extra = AU._extra("custom", cust, {}, tpl)
    title = AU._render(msg.get("title") or "", cust, tenant, extra).strip()
    body = AU._render(msg.get("body") or "", cust, tenant, extra).strip()
    text = f"{title} — {body}" if title and body else (title or body)
    target = AU._target_url(tid, row, cust)
    btn = msg.get("button") or {}
    return {"automation_id": row["id"], "title": title, "body": body, "text": text[:150],
            "button_label": (btn.get("label") or "")[:30] if target else None, "button_url": target,
            "spots": [(float(tr["lat"]), float(tr["lng"]))], "radius": int(tr.get("radius_m") or 300)}


def near(tid: str, cust: Dict[str, Any], lat: float, lng: float, at: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """The card reported its position: the custom géolocalisations in range speak."""
    from features import automations as AU
    if not geo_rows(tid):
        return []
    return [x for x in AU.fire("custom", tid, cust, {"event": "geo", "lat": lat, "lng": lng}, at=at) if x.get("title")]


def offer_used(tid: str, cust: Dict[str, Any], offer: Dict[str, Any], by: Optional[str] = None,
               branch_id: Optional[str] = None) -> Dict[str, Any]:
    """The till's « Offre utilisée »: once per offer and client."""
    key = {"tenant_id": tid, "campaign_id": offer["id"], "customer_id": cust["id"]}
    if _db.offer_uses.find_one(key):
        raise HTTPException(status_code=409, detail="Cette offre a déjà été utilisée par ce client.")
    doc = {**key, "id": str(uuid.uuid4()), "offer_name": offer.get("name"), "used_at": _now(), "by": by,
           "branch_id": branch_id}
    _db.offer_uses.insert_one(dict(doc))
    from features import automations as AU
    fresh = _db.customers.find_one({"id": cust["id"]}, {"_id": 0}) or cust
    AU.fire("custom", tid, fresh, {"event": "offer_used", "offer_id": offer["id"], "offre": offer.get("name") or "",
                                   "branch_id": branch_id})
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# words for the page (Résumé, list)
# ---------------------------------------------------------------------------
def _fr_date(raw: Optional[str]) -> str:
    try:
        d = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return "—"
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def trigger_text(tr: Dict[str, Any], sched: Optional[Dict[str, Any]] = None) -> str:
    t = tr.get("type")
    hour = (sched or {}).get("hour") or "10:00"
    if t == "on_date":
        return f"Date spécifique · le {_fr_date(tr.get('date'))} à {hour}"
    if t == "recurring":
        p = tr.get("period")
        if p == "weekly":
            k = int(tr.get("every_weeks") or 1)
            days = ", ".join(WEEKDAYS[d] for d in tr.get("weekdays") or [])
            return f"{'Chaque semaine' if k == 1 else f'Toutes les {k} semaines'} · {days} à {hour}"
        if p == "monthly":
            days = " et ".join("le 1er" if d == 1 else f"le {d}" for d in tr.get("monthdays") or [])
            return f"Chaque mois · {days} à {hour}"
        if p == "yearly":
            kind = tr.get("date_kind") or "fixed"
            what = {"birthday": "à l'anniversaire du client", "signup": "à l'anniversaire d'inscription"}.get(kind)
            if not what:
                d = str(tr.get("date") or "")
                what = f"le {int(d[8:10])} {MONTHS[int(d[5:7]) - 1]}" if len(d) >= 10 else "—"
            rem = tr.get("reminder") or {}
            extra = f" · rappel {int(rem.get('days_before') or 7)} j avant" if rem.get("enabled") else ""
            return f"Chaque année · {what} à {hour}{extra}"
        if tr.get("rule") == "per_month":
            base = f"{int(tr.get('per_month') or 1)} fois par mois"
        else:
            base = f"Tous les {int(tr.get('every_days') or 1)} jours"
        return f"{base} à {hour}" + (" · jours ouvrés" if tr.get("workdays_only") else "")
    if t == "action":
        a = ACTIONS.get(tr.get("action"), "Action")
        n, unit = int(tr.get("delay_value") or 0), tr.get("delay_unit") or "days"
        u = {"minutes": "min", "hours": "h", "days": "jour" + ("s" if n > 1 else "")}[unit]
        when = "immédiatement" if not n else f"{n} {u} après"
        rep = {"once": "une seule fois", "every": "à chaque fois"}.get(tr.get("repeat"),
                                                                       f"au plus tous les {int(tr.get('every_days') or 30)} j")
        return f"{a} · {when} · {rep}"
    if t == "loyalty":
        parts = []
        if tr.get("points") is not None:
            parts.append(f"{int(tr['points'])} points")
        if tr.get("visits") is not None:
            parts.append(f"{int(tr['visits'])} visites")
        if tr.get("amount") is not None:
            parts.append(f"{float(tr['amount']):g} € d'achats")
        j = " et " if tr.get("match") == "all" else " ou "
        rep = "à chaque nouvelle atteinte" if tr.get("repeat") == "each" else "une seule fois"
        return f"Conditions sur la fidélité · {j.join(parts) or '—'} · {rep}"
    if t == "behavior":
        u = {"days": "jours", "weeks": "semaines", "months": "mois"}[tr.get("unit") or "days"]
        what = "Client inactif depuis" if tr.get("activity") != "active" else "Client actif dans les"
        return f"Comportement client · {what} {int(tr.get('value') or 30)} {u}"
    if t == "geo":
        return f"Géolocalisation · {int(tr.get('radius_m') or 300)} m autour de {tr.get('address') or '—'}"
    if t == "other":
        rule = tr.get("rule")
        x, y = tr.get("x"), tr.get("y")
        cond = {"visits_in_days": f"{x} visites en {y} jours", "spent_in_days": f"{x:g} € dépensés en {y} jours" if isinstance(x, (int, float)) else "—",
                "no_visit_days": f"aucune visite depuis {x} jours", "signup_anniversary": "anniversaire d'inscription",
                "days_after_first_visit": f"{x} jours après la 1re visite"}.get(rule, "—")
        name = tr.get("rule_name") or "Règle personnalisée"
        d = int(tr.get("delay_days") or 0)
        return f"{name} · {cond}" + (f" · {d} j après" if d else "")
    return "Déclencheur personnalisé"


def rules_text(s: Dict[str, Any]) -> str:
    lim = s.get("limit") or {}
    per = lim.get("per") or "trigger"
    out = [f"{s.get('window_from')} – {s.get('window_to')}" if s.get("window") else "Toute la journée"]
    if per != "trigger":
        out.append(f"{int(lim.get('count') or 1)} fois {LIMIT_PER[per]}")
    if s.get("dedupe"):
        out.append(f"pas 2 fois en {int(s.get('min_gap_days') or 7)} j")
    return " · ".join(out)
