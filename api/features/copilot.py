"""
FidClic IA Copilote — the strategic assistant, built to the approved mockup.

ONE BRAIN
    The Copilote does not have opinions of its own. Its groups of clients —
    inactive, at risk, one-time, students, birthdays, local — and its campaign
    copy come from the same engine as the Insights page (features.insights_
    page), so the two pages can never give a merchant different advice about
    the same shop.

EVERY NUMBER IS COMPUTED — OR IT IS NOT SHOWN
    Unlike Insights, the Copilote shows no sector estimates at all. Each figure
    on this page is derived from the shop's own rows:

      · a campaign's worth uses the merchant's own response model — each
        client's average basket × a probability of coming back read from their
        recency (the midpoint of 25–35 % / 15–20 % / 10–15 % / 5–10 %);
      · a group's worth counts every client ONCE, at their best probability,
        so the growth potential is never the sum of overlapping campaigns;
      · where a figure cannot be derived (a shop with no visits, a day with no
        history) the page shows "—", never a placeholder.

THE FORECAST
    "Forte affluence prévue" is the shop's own weekday pattern over eight
    weeks, adjusted by the shop's OWN measured sensitivity to rain — learned
    by joining its past visits with the weather that fell on those days
    (Open-Meteo archive, free, no key). A shop without enough rainy days to
    learn from gets no weather adjustment rather than an invented one.
    Local events come from PredictHQ once PREDICTHQ_TOKEN is set; until then
    the source says "Météo + historique", not "événement".

AUTOPILOT PREPARES, THE MERCHANT DECIDES
    There is one Autopilot (features/autopilot.py, user 2026-10-02): a daily
    and a weekly campaign, prepared for the owner's OK. This page's « Mode
    Autopilot » switch is that one. The 7-day plan stays, and its steps are
    prepared when the owner asks (« Préparer les étapes ») or approves one.
    Nothing reaches a customer until the merchant approves: today's step is
    sent, a future one is scheduled for its day.

THE CHAT ANSWERS, IT NEVER ACTS
    Answers are grounded on the shop's computed facts; the model is told to
    use nothing else. Action buttons are attached by the server from the
    detected intent — never by the model — and every button opens something
    the merchant confirms. If the model is unavailable, the Copilote still
    answers from the facts.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from urllib.parse import quote
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import require_role
from features import copilot_memory as CM
from features import store_scope as S
from models import TokenData
from services import playbooks as PB

router = APIRouter(tags=["copilot"])
_db = None

HORIZONS = (7, 30, 90)
ACTIVITY_WINDOWS = (7, 30, 90)
TIERS = [("bronze", 0), ("silver", 10), ("gold", 20), ("vip", 40)]   # lifetime visits
NEAR_TIER = 3              # "within reach" of the next tier
RAINY_MM = 2.0             # a day with at least this much rain is a rainy day
AFFLUENCE_LIFT = 0.20      # a forecast day this far above the mean is worth saying
SEND_HOUR_UTC = 7          # scheduled steps go just before the 08:00 UTC daily cron
FEEDBACK_DAYS = {"not_relevant": 90, "later": 7}
# Who opens the page. Every figure, the chat and the "pas pertinent" follow
# the establishment menu (features/store_scope.py); the 7-day plan and
# Autopilot send to the whole shop and stay with the owner.
READERS = ["business_owner", "administrateur", "manager"]


def init(db):
    global _db
    _db = db
    try:
        db.copilot_plans.create_index("tenant_id", unique=True)
        db.copilot_feedback.create_index([("tenant_id", 1), ("key", 1)])
        db.copilot_chats.create_index([("tenant_id", 1), ("at", -1)])
        db.copilot_cache.create_index("key", unique=True)
    except Exception:
        pass


def _engine():
    from features import insights_page as E
    return E


# ---------------------------------------------------------------------------
# Small shapes
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _money(n: float) -> float:
    return round(n + 1e-9, 2)


def _fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(ch) != "Mn")


def _eur(n: float) -> str:
    return f"{round(n):,}".replace(",", " ") + " €"


def _eur_exact(n: float) -> str:
    """12,50 € — the chat says the real amount (QA F05: 12,50 € read « 12 € »)."""
    txt = f"{_money(n):,.2f}".replace(",", " ").replace(".", ",")
    return f"{txt} €"


def _pl(n: int, one: str, many: str) -> str:
    """« 1 visite », « 2 visites » (QA F05: « 1 visites »)."""
    return f"{n} {one if abs(n) <= 1 else many}"


# ---------------------------------------------------------------------------
# The period a question is about (QA F05, 2026-10-08: « aujourd'hui ? » and
# « les 7 derniers jours ? » were both answered « Sur 30 jours »).
# ---------------------------------------------------------------------------
PARIS = ZoneInfo("Europe/Paris")
_UNITS = {"jour": 1, "jours": 1, "j": 1, "semaine": 7, "semaines": 7, "mois": 30, "an": 365, "ans": 365,
          "annee": 365, "annees": 365}


def period_of(message: str, at: datetime) -> Dict[str, Any]:
    """{label, start, end, prev_start, prev_end, explicit}: the window the
    merchant asked about, and the same length just before it to compare."""
    m = _fold(message)
    local = at.astimezone(PARIS)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)

    def out(label, start, end, prev_start=None, prev_end=None, explicit=True):
        span = end - start
        return {"label": label, "start": start.astimezone(timezone.utc), "end": end.astimezone(timezone.utc),
                "prev_start": (prev_start or (start - span)).astimezone(timezone.utc),
                "prev_end": (prev_end or start).astimezone(timezone.utc), "explicit": explicit}

    if re.search(r"aujourd|\bce jour\b|\btoday\b|\bce matin\b|\bce soir\b", m):
        # today so far, against yesterday at the same hour
        return out("aujourd'hui", midnight, local, midnight - timedelta(days=1), local - timedelta(days=1))
    if re.search(r"avant[- ]hier", m):
        d = midnight - timedelta(days=2)
        return out("avant-hier", d, d + timedelta(days=1))
    if re.search(r"\bhier\b", m):
        return out("hier", midnight - timedelta(days=1), midnight)
    hit = re.search(r"(\d{1,3})\s*(?:(?:derniers?|dernieres?|passes?|precedents?)\s+)?(jours?|j|semaines?|mois|ans?|annees?)\b", m)
    if hit:
        n = max(1, int(hit.group(1)))
        days = min(365 * 2, n * _UNITS[hit.group(2)])
        unit = {"j": "jour", "jours": "jour", "semaines": "semaine", "ans": "an", "annees": "an", "annee": "an"}.get(hit.group(2), hit.group(2))
        word = {"jour": ("jour", "jours"), "semaine": ("semaine", "semaines"), "mois": ("mois", "mois"),
                "an": ("an", "ans")}[unit]
        label = f"les {n} derniers {word[1]}" if n > 1 else f"le dernier {word[0]}"
        if unit == "semaine":
            label = f"les {n} dernières semaines" if n > 1 else "la dernière semaine"
        return out(label, local - timedelta(days=days), local)
    if re.search(r"semaine (derniere|passee|precedente)", m):
        mon = midnight - timedelta(days=local.weekday())
        return out("la semaine dernière", mon - timedelta(days=7), mon)
    if re.search(r"cette semaine|la semaine en cours", m):
        mon = midnight - timedelta(days=local.weekday())
        return out("cette semaine", mon, local, mon - timedelta(days=7), local - timedelta(days=7))
    if re.search(r"mois (dernier|passe|precedent)", m):
        first = midnight.replace(day=1)
        prev_first = (first - timedelta(days=1)).replace(day=1)
        before = (prev_first - timedelta(days=1)).replace(day=1)
        return out("le mois dernier", prev_first, first, before, prev_first)
    if re.search(r"ce mois|mois en cours", m):
        # this month so far, against the same days of last month
        first = midnight.replace(day=1)
        prev_first = (first - timedelta(days=1)).replace(day=1)
        return out("ce mois-ci", first, local, prev_first, min(prev_first + (local - first), first))
    if re.search(r"\bsemaine\b", m):
        return out("les 7 derniers jours", local - timedelta(days=7), local)
    if re.search(r"\bannee\b|\b12 mois\b", m):
        return out("les 12 derniers mois", local - timedelta(days=365), local)
    return out("les 30 derniers jours", local - timedelta(days=30), local, explicit=False)


def period_figures(tid: str, per: Dict[str, Any], scope: Optional["S.Scope"] = None) -> Dict[str, Any]:
    def figs(rows):
        rev = sum(_num(v.get("amount_paid")) for v in rows)
        return {"visits": len(rows), "revenue": _money(rev),
                "clients": len({v.get("customer_id") for v in rows if v.get("customer_id")}),
                "basket": _money(rev / len(rows)) if rows else 0.0}
    a = figs(_visits_between(tid, per["start"], per["end"], scope))
    b = figs(_visits_between(tid, per["prev_start"], per["prev_end"], scope))
    delta = lambda k: round((a[k] - b[k]) / b[k] * 100) if b[k] else None    # noqa: E731
    return {**a, "delta_visits": delta("visits"), "delta_revenue": delta("revenue"), "previous": b}


def _p_mid(c: Dict[str, Any], at: datetime) -> float:
    lo, hi = _engine()._p_range(c, at)
    return (lo + hi) / 2


def _basket(c: Dict[str, Any], shop_avg: float) -> float:
    b = _engine()._avg_basket(c)
    return b if b is not None else shop_avg


def _worth(people: List[Dict[str, Any]], shop) -> Tuple[float, float]:
    """(expected visits, expected euros) of one campaign at these people."""
    visits = euros = 0.0
    for c in people:
        p = _p_mid(c, shop.at)
        visits += p
        euros += _basket(c, shop.shop_avg) * p
    return visits, euros


def _visits_between(tid: str, a: datetime, b: datetime,
                    scope: Optional["S.Scope"] = None) -> List[Dict[str, Any]]:
    return list(_db.visits.find({"tenant_id": tid, "visit_time": {"$gte": a, "$lte": b},
                                 **(S.visit_filter(scope) if scope else {})},
                                {"_id": 0, "amount_paid": 1, "visit_time": 1, "customer_id": 1}))


def _base_visits(shop) -> int:
    """Visits in the last 30 days — what a "+x % visites" is measured against."""
    return shop.tot["d30"].n


# ---------------------------------------------------------------------------
# External context — cached, bounded, and never fatal
# ---------------------------------------------------------------------------
def _http_json(url: str, headers: Optional[Dict[str, str]] = None,
               timeout: float = 4.0) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "FidClic/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except Exception as exc:
        print(f"copilot: external call failed ({url.split('?')[0]}): {exc}")
        return None


def _cached(key: str, max_age: timedelta, fetch) -> Any:
    row = _db.copilot_cache.find_one({"key": key})
    at = row.get("at") if row else None
    if isinstance(at, datetime) and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if row and at and _now() - at < max_age:
        return row.get("data")
    data = fetch()
    if data is not None:
        _db.copilot_cache.update_one({"key": key}, {"$set": {"key": key, "at": _now(), "data": data}},
                                     upsert=True)
        return data
    return row.get("data") if row else None       # stale beats nothing when the network is down


def _shop_position(tenant: Dict[str, Any], scope: Optional["S.Scope"] = None) -> Optional[Tuple[float, float]]:
    try:
        from features import geolocation as geo
        lat, lng, _ = geo._shop_position(tenant)
        # One establishment chosen: its weather, when its address is known.
        one = scope.single if scope is not None else None
        branch = next((b for b in tenant.get("branches") or [] if b.get("id") == one), None) if one else None
        if branch:
            blat, blng, _ = geo._shop_position({k: v for k, v in branch.items() if k != "branches"})
            if blat is not None:
                lat, lng = blat, blng
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    except Exception:
        pass
    return None


def weather_forecast(pos: Tuple[float, float]) -> Optional[Dict[str, Dict[str, float]]]:
    lat, lng = pos
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": round(lat, 3), "longitude": round(lng, 3),
        "daily": "precipitation_sum,temperature_2m_max", "timezone": "Europe/Paris",
        "forecast_days": 7}))

    def fetch():
        d = _http_json(url)
        if not d or "daily" not in d:
            return None
        daily = d["daily"]
        return {t: {"rain": _num(r), "tmax": _num(m)}
                for t, r, m in zip(daily.get("time", []), daily.get("precipitation_sum", []),
                                   daily.get("temperature_2m_max", []))}
    return _cached(f"wx:fc:{round(lat, 2)}:{round(lng, 2)}", timedelta(hours=3), fetch)


def weather_history(pos: Tuple[float, float], start: date, end: date) -> Optional[Dict[str, float]]:
    lat, lng = pos
    url = ("https://archive-api.open-meteo.com/v1/archive?" + urllib.parse.urlencode({
        "latitude": round(lat, 3), "longitude": round(lng, 3),
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "precipitation_sum", "timezone": "Europe/Paris"}))

    def fetch():
        d = _http_json(url, timeout=6.0)
        if not d or "daily" not in d:
            return None
        daily = d["daily"]
        return {t: _num(r) for t, r in zip(daily.get("time", []), daily.get("precipitation_sum", []))
                if r is not None}
    return _cached(f"wx:hist:{round(lat, 2)}:{round(lng, 2)}:{start}:{end}", timedelta(hours=24), fetch)


def events_configured() -> bool:
    return bool((os.getenv("PREDICTHQ_TOKEN") or "").strip())


def events_nearby(pos: Tuple[float, float], start: date, end: date) -> Dict[str, List[Dict[str, Any]]]:
    """Local events by day, from PredictHQ — empty until its token is set.

    Only events that draw a crowd (rank ≥ 40) within 3 km are kept; a small
    meetup down the road is not "un événement dans la zone".
    """
    token = (os.getenv("PREDICTHQ_TOKEN") or "").strip()
    if not token:
        return {}
    lat, lng = pos
    url = ("https://api.predicthq.com/v1/events/?" + urllib.parse.urlencode({
        "within": f"3km@{lat},{lng}", "active.gte": start.isoformat(), "active.lte": end.isoformat(),
        "category": "concerts,festivals,sports,community,performing-arts,expos",
        "rank.gte": 40, "sort": "rank", "limit": 20}))

    def fetch():
        d = _http_json(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if not d:
            return None
        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for ev in d.get("results") or []:
            day = str(ev.get("start") or "")[:10]
            if day:
                out[day].append({"title": ev.get("title"), "category": ev.get("category"),
                                 "rank": ev.get("rank")})
        return dict(out)
    return _cached(f"ev:{round(lat, 2)}:{round(lng, 2)}:{start}", timedelta(hours=6), fetch) or {}


# ---------------------------------------------------------------------------
# The forecast
# ---------------------------------------------------------------------------
def _daily_counts(tid: str, days: int, at: datetime, scope: Optional["S.Scope"] = None) -> Dict[date, int]:
    counts: Dict[date, int] = defaultdict(int)
    for v in _visits_between(tid, at - timedelta(days=days), at, scope):
        t = v.get("visit_time")
        if isinstance(t, datetime):
            counts[(t if t.tzinfo else t.replace(tzinfo=timezone.utc)).date()] += 1
    return counts


def rain_sensitivity(tid: str, pos: Optional[Tuple[float, float]], at: datetime,
                     scope: Optional["S.Scope"] = None) -> Optional[float]:
    """How much THIS shop's traffic moves on a rainy day — learned, not assumed.

    Each past day's visits are divided by that weekday's average, so a rainy
    Saturday is compared with Saturdays, not with Mondays. The factor is the
    mean ratio on rainy days over the mean ratio on dry days. Without at least
    8 rainy and 20 dry days of history there is nothing to learn from, and the
    forecast is left unadjusted.
    """
    if not pos:
        return None
    counts = _daily_counts(tid, 90, at, scope)
    if len(counts) < 30:
        return None
    start, end = (at - timedelta(days=90)).date(), (at - timedelta(days=1)).date()
    rain = weather_history(pos, start, end)
    if not rain:
        return None
    by_wd: Dict[int, List[int]] = defaultdict(list)
    for d, n in counts.items():
        by_wd[d.weekday()].append(n)
    mean_wd = {w: sum(v) / len(v) for w, v in by_wd.items() if v}
    wet, dry = [], []
    for d, n in counts.items():
        mm = rain.get(d.isoformat())
        base = mean_wd.get(d.weekday())
        if mm is None or not base:
            continue
        (wet if mm >= RAINY_MM else dry).append(n / base)
    if len(wet) < 8 or len(dry) < 20:
        return None
    factor = (sum(wet) / len(wet)) / (sum(dry) / len(dry))
    return round(max(0.5, min(1.5, factor)), 3)


def forecast_week(shop) -> Dict[str, Any]:
    """The next seven days: expected visits, and what the expectation rests on."""
    at = shop.at
    scope = getattr(shop, "scope", None)
    counts = _daily_counts(shop.tid, 56, at, scope)
    by_wd: Dict[int, List[int]] = defaultdict(list)
    # Fill silent days with zero so an occasional busy Monday is not a pattern.
    for i in range(1, 57):
        d = (at - timedelta(days=i)).date()
        by_wd[d.weekday()].append(counts.get(d, 0))
    base = {w: sum(v) / len(v) for w, v in by_wd.items() if len([x for x in v if x]) >= 3}
    if len(base) < 3:
        return {"days": [], "mean": None, "sources": []}

    pos = _shop_position(shop.tenant, scope)
    wx = weather_forecast(pos) if pos else None
    factor = rain_sensitivity(shop.tid, pos, at, scope) if wx else None
    today = at.date()
    ev = events_nearby(pos, today, today + timedelta(days=6)) if pos else {}

    days = []
    for i in range(7):
        d = today + timedelta(days=i)
        b = base.get(d.weekday())
        if b is None:
            continue
        w = (wx or {}).get(d.isoformat())
        rainy = bool(w and w["rain"] >= RAINY_MM)
        pred = b * (factor if (rainy and factor) else 1.0)
        days.append({"date": d.isoformat(), "weekday": d.weekday(), "base": round(b, 1),
                     "predicted": round(pred, 1), "rain_mm": w["rain"] if w else None,
                     "tmax": w["tmax"] if w else None, "weather_applied": bool(rainy and factor),
                     "events": ev.get(d.isoformat(), [])})
    mean = sum(base.values()) / len(base)
    sources = ["historique"]
    if wx:
        sources.insert(0, "météo")
    if events_configured():
        sources.append("événements")
    return {"days": days, "mean": round(mean, 1), "rain_factor": factor, "sources": sources}


def _affluence(shop, fc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    E = _engine()
    if not fc["days"] or not fc["mean"]:
        return None
    peak = max(fc["days"], key=lambda d: d["predicted"])
    if peak["predicted"] < fc["mean"] * (1 + AFFLUENCE_LIFT):
        return None
    extra = peak["predicted"] - fc["mean"]
    day = E.WEEKDAY_FR[peak["weekday"]]
    has_event = bool(peak["events"])
    if has_event and "météo" in fc["sources"]:
        why = "Météo + événement dans la zone."
    elif has_event:
        why = "Événement dans la zone + historique."
    elif "météo" in fc["sources"]:
        why = "Météo + historique de vos visites."
    else:
        why = "D'après l'historique de vos visites."
    return {"key": "affluence", "icon": "sun", "tone": "green",
            "title": f"Forte affluence prévue ce {day}",
            "body": why, "potential": _money(extra * shop.shop_avg),
            "detail": peak,
            "cta": {"kind": "template", "template": "offre_jour", "day": peak["weekday"],
                    "label": "Préparer une offre"}}


# ---------------------------------------------------------------------------
# Recommendations — every metric computed
# ---------------------------------------------------------------------------
def _metrics_campaign(people, shop) -> Tuple[List[Dict[str, str]], float, float]:
    """Two figures a merchant reads at a glance: visits and euros, as numbers.

    Small groups say so rather than rounding to zero: "< 1 visite" means the
    campaign is worth little, which is itself worth knowing.
    """
    v, e = _worth(people, shop)
    if v >= 0.5:
        visits = f"+{round(v)} visite{'s' if round(v) > 1 else ''}"
    else:
        visits = "< 1 visite"
    return ([{"icon": "chart", "label": visits}, {"icon": "euro", "label": f"+{_eur(e)} CA"}], v, e)


def _next_tier(visits: int, tid: Optional[str] = None) -> Optional[Tuple[str, int]]:
    """The next palier in visits — the shop's own ladder on a stamp card
    (features/loyalty_card), the default one otherwise."""
    ladder = TIERS
    if tid:
        try:
            from features import loyalty_card as LC
            if not LC._is_points(LC._programme(LC._template(tid))):
                ladder = [(r["key"], r["min"]) for r in LC.tiers_for(tid)]
        except Exception:
            ladder = TIERS
    for name, threshold in ladder:
        if visits < threshold:
            return name, threshold
    return None


def _library(shop) -> List[Dict[str, Any]]:
    E = _engine()
    out: List[Dict[str, Any]] = []

    def campaign(key, chip, tone, icon, title, body, people, template, button, extra=None):
        if not people:
            return
        metrics, v, e = _metrics_campaign(people, shop)
        if e <= 0 and v <= 0:
            return
        item = {"key": key, "kind": "campaign", "chip": chip, "tone": tone, "icon": icon,
                "title": title, "body": body, "metrics": metrics,
                "cta": {"kind": "template", "template": template, "label": button},
                "audience": len(people), "worth": {"visits": round(v, 1), "euros": _money(e)},
                "score": e, "ids": [c["id"] for c in people]}
        if extra:
            item["cta"].update(extra)
        out.append(item)

    dormant = E._inactive(shop)
    campaign("relance_inactifs", "Clients inactifs", "rose", "users",
             f"Relancer {len(dormant)} clients inactifs",
             "Ces clients n'ont pas visité votre commerce depuis 30 jours.",
             dormant, "relance_inactifs", "Lancer la campagne")

    best = E._best_weekday(shop)
    if best and best["lift"] >= 10:
        day = E.WEEKDAY_FR[best["weekday"]]
        active = [c for c in shop.people
                  if (d := E._aware(c.get("last_visit_date"))) and (shop.at - d).days <= 60]
        campaign("offre_jour", "Week-end" if best["weekday"] >= 4 else day.capitalize(), "amber",
                 "gift", f"Créer une offre spéciale {day}",
                 f"Le {day} est {best['lift']}% plus performant. Profitez de cette forte affluence.",
                 active, "offre_jour", "Créer l'offre", {"day": best["weekday"]})

    risk = E._at_risk(shop)
    campaign("a_risque", "Clients à risque", "rose", "alert",
             f"Reconquérir {len(risk)} habitué{'s' if len(risk) > 1 else ''}",
             "Ils venaient régulièrement mais ne viennent plus depuis plus de 45 jours.",
             risk, "a_risque", "Lancer la campagne")

    bdays = E._birthdays(shop, 7)
    campaign("anniversaires", "Anniversaires", "violet", "cake",
             f"Souhaiter {len(bdays)} anniversaire{'s' if len(bdays) > 1 else ''}",
             "Un message le jour J, avec une attention, fait revenir.",
             bdays, "anniversaires_semaine", "Lancer la campagne")

    once = E._one_timers(shop)
    campaign("seconde_visite", "Nouveaux clients", "blue", "repeat",
             f"Faire revenir {len(once)} nouveau{'x' if len(once) > 1 else ''} client{'s' if len(once) > 1 else ''}",
             "Ils ne sont venus qu'une fois : une offre pour la deuxième visite les fidélise.",
             once, "seconde_visite", "Lancer la campagne")

    students = E._students(shop)
    campaign("etudiants", "Étudiants", "blue", "graduation",
             f"Offre pour {len(students)} étudiant{'s' if len(students) > 1 else ''}",
             "Des clients déclarés étudiants : une offre dédiée les fait revenir.",
             students, "etudiants", "Créer l'offre")

    near = E._locals(shop) or []
    campaign("proximite", "Clients locaux", "green", "pin",
             f"Cibler {len(near)} clients à moins de 2 km",
             "Ils habitent à deux pas : une offre de proximité les fait passer plus souvent.",
             near, "offre_locale", "Créer la campagne")

    # Programme fidélité — clients within reach of their next tier.
    reach = []
    for c in shop.people:
        v = int(_num(c.get("visits")))
        nxt = _next_tier(v, shop.tid)
        if v > 0 and nxt and 0 < nxt[1] - v <= NEAR_TIER:
            reach.append(c)
    active_n = len([c for c in shop.people
                    if (d := E._aware(c.get("last_visit_date"))) and (shop.at - d).days <= 60])
    if reach and active_n:
        vip_share = round(len(reach) / active_n * 100)
        v, e = _worth(reach, shop)
        out.append({"key": "palier_vip", "kind": "suggestion", "chip": "Programme fidélité",
                    "tone": "amber", "icon": "star", "title": "Mettre en avant un palier VIP",
                    "body": "Vos meilleurs clients réagissent bien aux récompenses exclusives.",
                    "metrics": [{"icon": "star", "label": f"+{vip_share}% fidélisation"},
                                {"icon": "users", "label": f"+{len(reach)} clients"}],
                    "detail": (f"{len(reach)} clients sont à {NEAR_TIER} visites ou moins de leur "
                               "prochain palier. Annoncez une récompense exclusive à ce palier : "
                               "c'est la raison de revenir qui leur manque."),
                    "cta": {"kind": "suggestion", "label": "Voir la suggestion", "to": "/dashboard/card"},
                    "audience": len(reach), "worth": {"visits": round(v, 1), "euros": _money(e)},
                    "score": e * 0.8, "ids": [c["id"] for c in reach]})

    # Setup steps — computed impacts only.
    happy = E._satisfied(shop)
    if happy and not E._google_on(shop.tenant):
        low = max(1, round(happy * 0.2))
        out.append({"key": "avis_google", "kind": "setup", "chip": "Avis clients", "tone": "green",
                    "icon": "star", "title": "Collecter des avis Google",
                    "body": "Invitez vos clients satisfaits à laisser un avis sur votre fiche Google.",
                    "metrics": [{"icon": "star", "label": f"+{low} à {happy} avis"},
                                {"icon": "users", "label": f"{happy} clients satisfaits"}],
                    "cta": {"kind": "google_review", "label": "Configurer"},
                    "audience": happy, "worth": {"visits": 0, "euros": 0},
                    "score": happy * shop.shop_avg * 0.1, "ids": []})
    if bdays and not E._birthday_on(shop.tid):
        v, e = _worth(E._birthdays(shop, 30), shop)
        out.append({"key": "anniversaire_auto", "kind": "setup", "chip": "Automatisation",
                    "tone": "violet", "icon": "cake", "title": "Activer l'offre anniversaire",
                    "body": "Chaque client reçoit automatiquement un message le jour de son anniversaire.",
                    "metrics": [{"icon": "users", "label": f"{len(E._birthdays(shop, 30))} ce mois-ci"},
                                {"icon": "euro", "label": f"+{_eur(e)} CA"}],
                    "cta": {"kind": "activate", "action": "birthday", "label": "Activer"},
                    "audience": len(bdays), "worth": {"visits": round(v, 1), "euros": _money(e)},
                    "score": e * 0.9, "ids": []})

    # The trade's own advice (services/playbooks.py) — the same levers as
    # Insights, as suggestions: no number unless the playbook has a sourced one.
    for lv in E.sector_levers(shop, "opportunite") + E.sector_levers(shop, "idee"):
        imp = E._figure(shop, lv["key"], lv)
        detail = lv["body"] + (f" {imp['text']} (Source : {imp['basis']}.)" if imp["kind"] == "source" else "")
        to = lv.get("to") or f"/dashboard/campaigns?template={quote(lv['template']['key'], safe='')}"
        out.append({"key": f"pb_{lv['key']}", "kind": "suggestion", "chip": shop.play["label"],
                    "tone": "blue", "icon": "star", "title": lv["title"], "body": lv["body"],
                    "metrics": [], "detail": detail,
                    "cta": {"kind": "suggestion", "label": "Voir la suggestion", "to": to,
                            "button": lv["label"]},
                    "audience": 0, "worth": {"visits": 0, "euros": 0},
                    "score": shop.monthly * 0.01, "ids": []})
    return out


def _feedback(tid: str, at: datetime, store_key: str = S.ALL) -> Tuple[set, Dict[str, int]]:
    """(hidden keys, how often each key's CTA was followed) — what the page learns.

    The owner's answers (given on the whole shop) hold everywhere; an answer
    given on some establishments holds for that same choice only, so an
    administrateur's "pas pertinent" never hides an idea from the owner.
    """
    hidden, accepted = set(), defaultdict(int)
    for row in _db.copilot_feedback.find({"tenant_id": tid}, {"_id": 0}):
        if row.get("store_key", S.ALL) not in (S.ALL, store_key):
            continue
        until = row.get("until")
        if isinstance(until, datetime) and until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if row.get("kind") in FEEDBACK_DAYS and until and until > at:
            hidden.add(row["key"])
        elif row.get("kind") == "accepted":
            accepted[row["key"]] += 1
    return hidden, dict(accepted)


def recommendations(shop) -> List[Dict[str, Any]]:
    """Ranked, minus what the merchant dismissed and what was just used.

    A recommendation whose campaign went out in the last two weeks makes way
    for the next one — the same rule as Insights, read from the same campaigns.
    """
    scope = getattr(shop, "scope", None)
    hidden, accepted = _feedback(shop.tid, shop.at, scope.key if scope is not None else S.ALL)
    used = getattr(shop, "used", None) or _engine().used_templates(shop.tid, shop.at, scope=scope)
    items = [i for i in _library(shop) if i["key"] not in hidden
             and (i.get("cta") or {}).get("template") not in used]
    items = sorted(items, key=lambda i: -i["score"])
    # the ranking that learns (2026-10-30): the estimate × what every shown,
    # opened, pushed-back and measured idea taught (features/reco_ranking)
    from features import reco_ranking as RR
    return RR.rank(shop.tid, items, lambda i, _n: i["score"])


def _public(i: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in i.items() if k not in ("score", "ids")}


# ---------------------------------------------------------------------------
# Growth potential
# ---------------------------------------------------------------------------
def growth(shop, recs: List[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    """What the next `horizon` days could add — every client counted once.

    The campaign part runs the plan once: the top 3 campaigns for a week, 6 for
    a month, all of them for a quarter. A client targeted by two campaigns is
    counted once, at their best probability. New clients continue at the pace
    of the last 30 days.
    """
    E = _engine()
    n = {7: 3, 30: 6}.get(horizon, 99)
    chosen = [r for r in recs if r["kind"] == "campaign"][:n]
    ids = {i for r in chosen for i in r["ids"]}
    by_id = {c["id"]: c for c in shop.people}
    people = [by_id[i] for i in ids if i in by_id]
    visits, euros = _worth(people, shop)

    inactive = {c["id"] for c in E._inactive(shop)}
    reactivated = sum(_p_mid(c, shop.at) for c in people if c["id"] in inactive)

    signups = [c for c in shop.people
               if (d := E._aware(c.get("created_at"))) and (shop.at - d).days <= 30]
    new_clients = round(len(signups) * horizon / 30)

    total = len(shop.people)
    returning = len([c for c in shop.people if int(_num(c.get("visits"))) >= 2])
    second = sum(_p_mid(c, shop.at) for c in people if int(_num(c.get("visits"))) == 1)
    retention = (round(second / returning * 100) if returning else None)

    baseline = shop.monthly * horizon / 30
    pct = round(euros / baseline * 100) if baseline > 0 else None
    return {
        "horizon": horizon, "pct": pct, "euros": _money(euros),
        "rows": [
            {"key": "visits", "icon": "visits", "value": round(visits), "label": "visites estimées"},
            {"key": "new", "icon": "users", "value": new_clients, "label": "nouveaux clients"},
            {"key": "reactivated", "icon": "reactivated", "value": round(reactivated),
             "label": "clients réactivés"},
            {"key": "retention", "icon": "bolt", "value": retention, "unit": "%",
             "label": "taux de fidélisation"},
        ],
        "campaigns": [r["key"] for r in chosen],
        "clients_targeted": len(people),
        "note": ("Estimation : chaque client ciblé une seule fois, à sa probabilité de retour selon sa "
                 "dernière visite ; nouveaux clients au rythme des 30 derniers jours."),
    }


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------
def activity(tid: str, days: int, at: datetime, scope: Optional["S.Scope"] = None) -> Dict[str, Any]:
    """Four figures, their change, and the bars under them."""
    now_rows = _visits_between(tid, at - timedelta(days=days), at, scope)
    prev_rows = _visits_between(tid, at - timedelta(days=2 * days), at - timedelta(days=days), scope)

    def figs(rows):
        rev = sum(_num(v.get("amount_paid")) for v in rows)
        return {"visits": len(rows), "revenue": rev,
                "active": len({v.get("customer_id") for v in rows if v.get("customer_id")}),
                "basket": rev / len(rows) if rows else 0.0}

    a, b = figs(now_rows), figs(prev_rows)
    delta = lambda k: round((a[k] - b[k]) / b[k] * 100) if b[k] else None

    buckets = {7: 7, 30: 10, 90: 13}[days]
    width = days / buckets
    series = {k: [0.0] * buckets for k in ("visits", "revenue", "active", "basket")}
    groups: List[List[Dict[str, Any]]] = [[] for _ in range(buckets)]
    start = at - timedelta(days=days)
    for v in now_rows:
        t = v.get("visit_time")
        if not isinstance(t, datetime):
            continue
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        idx = min(buckets - 1, int((t - start).total_seconds() / 86400 / width))
        groups[idx].append(v)
    for i, g in enumerate(groups):
        f = figs(g)
        for k in series:
            series[k][i] = round(f[k], 2)

    return {"days": days, "cards": [
        {"key": "visits", "label": "Visites", "value": a["visits"], "delta": delta("visits"),
         "series": series["visits"], "tone": "blue"},
        {"key": "revenue", "label": "Chiffre d'affaires", "value": _money(a["revenue"]), "unit": "€",
         "delta": delta("revenue"), "series": series["revenue"], "tone": "green"},
        {"key": "active", "label": "Clients actifs", "value": a["active"], "delta": delta("active"),
         "series": series["active"], "tone": "violet"},
        {"key": "basket", "label": "Panier moyen", "value": _money(a["basket"]), "unit": "€",
         "delta": delta("basket"), "series": series["basket"], "tone": "amber"},
    ]}


# ---------------------------------------------------------------------------
# Opportunities detected
# ---------------------------------------------------------------------------
def opportunities(shop, fc: Dict[str, Any]) -> List[Dict[str, Any]]:
    E = _engine()
    out: List[Dict[str, Any]] = []

    risk = E._at_risk(shop)
    if risk:
        _, e = _worth(risk, shop)
        out.append({"key": "a_risque", "icon": "alert", "tone": "rose",
                    "title": f"{len(risk)} client{'s' if len(risk) > 1 else ''} à risque de partir",
                    "body": "Ils venaient régulièrement mais n'ont pas visité depuis 45 jours.",
                    "potential": _money(e),
                    "cta": {"kind": "template", "template": "a_risque"}})

    aff = _affluence(shop, fc)
    if aff:
        out.append(aff)

    last15, prev15 = shop.tot["d15"], shop.tot["p15"]
    if last15.n >= 10 and prev15.n >= 10:
        cur = last15.revenue / last15.n
        was = prev15.revenue / prev15.n
        drop = round((cur - was) / was * 100) if was else 0
        if drop <= -5:
            out.append({"key": "panier", "icon": "bag", "tone": "violet",
                        "title": "Panier moyen en baisse",
                        "body": f"{drop}% sur les 15 derniers jours.",
                        "potential": _money((was - cur) * last15.n),
                        "cta": {"kind": "navigate", "to": "/dashboard/insights"}})

    bdays = E._birthdays(shop, 7)
    if bdays:
        _, e = _worth(bdays, shop)
        out.append({"key": "anniversaires", "icon": "gift", "tone": "amber",
                    "title": "Anniversaires cette semaine",
                    "body": f"{len(bdays)} client{'s' if len(bdays) > 1 else ''} à souhaiter.",
                    "potential": _money(e),
                    "cta": {"kind": "template", "template": "anniversaires_semaine"}})

    students = E._students(shop)
    if students:
        _, e = _worth(students, shop)
        out.append({"key": "etudiants", "icon": "graduation", "tone": "blue",
                    "title": f"{len(students)} étudiant{'s' if len(students) > 1 else ''} dans votre base",
                    "body": "Une offre étudiante dédiée les fait revenir.",
                    "potential": _money(e), "cta": {"kind": "template", "template": "etudiants"}})

    once = E._one_timers(shop)
    if once:
        _, e = _worth(once, shop)
        out.append({"key": "seconde_visite", "icon": "repeat", "tone": "blue",
                    "title": f"{len(once)} nouveau{'x' if len(once) > 1 else ''} client{'s' if len(once) > 1 else ''} à fidéliser",
                    "body": "Ils ne sont venus qu'une seule fois ce mois-ci.",
                    "potential": _money(e), "cta": {"kind": "template", "template": "seconde_visite"}})
    return out


# ---------------------------------------------------------------------------
# The 7-day plan
# ---------------------------------------------------------------------------
SHORT = {"relance_inactifs": "Relance inactifs", "offre_jour": "Offre spéciale",
         "a_risque": "Reconquête habitués", "anniversaires": "Anniversaires",
         "seconde_visite": "2e visite", "etudiants": "Offre étudiants",
         "proximite": "Offre locale", "palier_vip": "Palier VIP",
         "avis_google": "Demande d'avis", "anniversaire_auto": "Push Wallet anniversaire",
         "analyse": "Analyse résultats"}


def _build_plan(shop, recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    campaigns = [r for r in recs if r["kind"] == "campaign"][:3]
    setups = [r for r in recs if r["kind"] == "setup"][:1]
    steps, taken = [], set()
    # An offer for a given weekday goes out the day before it — "ce lundi
    # seulement" sent on a Saturday is read and forgotten. Everything else
    # takes the first free day, most valuable first.
    for r in campaigns:
        day = r["cta"].get("day")
        if day is not None:
            want = (int(day) - shop.at.weekday() - 1) % 7
            steps.append({"r": r, "offset": want})
            taken.add(want)
    nxt = 0
    for r in campaigns:
        if r["cta"].get("day") is not None:
            continue
        while nxt in taken:
            nxt += 1
        steps.append({"r": r, "offset": nxt})
        taken.add(nxt)
    steps = [{"id": str(uuid.uuid4()), "offset": x["offset"], "key": x["r"]["key"], "kind": "campaign",
              "template": x["r"]["cta"]["template"], "day": x["r"]["cta"].get("day"),
              "campaign_id": None} for x in sorted(steps, key=lambda x: x["offset"])]
    for r in setups:
        free = next(i for i in range(7) if i not in taken)
        taken.add(free)
        steps.append({"id": str(uuid.uuid4()), "offset": free, "key": r["key"], "kind": "setup",
                      "campaign_id": None})
    last = max([s["offset"] for s in steps] or [0])
    steps.append({"id": str(uuid.uuid4()), "offset": min(6, max(4, last + 2)), "key": "analyse",
                  "kind": "analysis", "campaign_id": None})
    steps.sort(key=lambda s: s["offset"])
    return {"tenant_id": shop.tid, "start": shop.at.date().isoformat(), "steps": steps,
            "updated_at": shop.at}


def _plan(shop, recs: List[Dict[str, Any]], rebuild: bool = False) -> Dict[str, Any]:
    doc = _db.copilot_plans.find_one({"tenant_id": shop.tid}, {"_id": 0})
    expired = doc and date.fromisoformat(doc["start"]) + timedelta(days=7) <= shop.at.date()
    if not doc or expired or rebuild:
        fresh = _build_plan(shop, recs)
        fresh["autopilot"] = bool(doc and doc.get("autopilot"))
        _db.copilot_plans.update_one({"tenant_id": shop.tid}, {"$set": fresh}, upsert=True)
        doc = _db.copilot_plans.find_one({"tenant_id": shop.tid}, {"_id": 0})
    return doc


def _step_date(doc: Dict[str, Any], step: Dict[str, Any]) -> date:
    return date.fromisoformat(doc["start"]) + timedelta(days=int(step["offset"]))


def _step_view(shop, doc: Dict[str, Any], step: Dict[str, Any], recs_by_key: Dict[str, Any]) -> Dict[str, Any]:
    E = _engine()
    d = _step_date(doc, step)
    today = shop.at.date()
    when = ("Aujourd'hui" if d == today else "Demain" if d == today + timedelta(days=1)
            else f"{d.day} {['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'][d.month - 1]}")
    status, tone = "Planifiée", "slate"
    camp = _db.campaigns.find_one({"id": step.get("campaign_id")}, {"_id": 0, "status": 1,
                                                                    "targeted_count": 1}) \
        if step.get("campaign_id") else None
    if step["kind"] == "campaign":
        if camp and camp.get("status") == "sent":
            status, tone = "Envoyée", "green"
        elif camp and camp.get("status") in ("scheduled", "sending"):
            status, tone = "Programmée", "blue"
        elif camp:
            status, tone = "Préparée", "green"
        elif d <= today:
            status, tone = "À faire", "violet"
    elif step["kind"] == "setup":
        done = (E._google_on(shop.tenant) if step["key"] == "avis_google"
                else E._birthday_on(shop.tid) if step["key"] == "anniversaire_auto" else False)
        status, tone = ("Activée", "green") if done else ("À configurer", "blue")
    else:
        sent = any(s.get("campaign_id") and (_db.campaigns.find_one(
            {"id": s["campaign_id"], "status": "sent"}) is not None) for s in doc["steps"])
        status, tone = ("À suivre", "blue") if sent else ("Après les envois", "slate")
    rec = recs_by_key.get(step["key"])
    return {"id": step["id"], "date": d.isoformat(), "when": when, "key": step["key"],
            "kind": step["kind"], "title": SHORT.get(step["key"], step["key"]),
            "status": status, "tone": tone,
            "audience": (camp or {}).get("targeted_count") or (rec or {}).get("audience"),
            "can_approve": step["kind"] == "campaign" and status in ("Préparée", "À faire"),
            "cta": (rec or {}).get("cta") or ({"kind": "navigate", "to": "/dashboard/analytics"}
                                              if step["kind"] == "analysis" else None)}


def _prepare_step(shop, step: Dict[str, Any]) -> Optional[str]:
    """Draft the campaign behind a plan step — audience resolved, copy written.

    Returns the draft's id. Nothing is sent: a draft is exactly what a merchant
    would have saved from the composer.
    """
    from features import campaigns_page as C
    E = _engine()
    tpl = E.template(step["template"], day=step.get("day"),
                     token_data=type("T", (), {"tenant_id": shop.tid})())
    body = C.Compose(title=tpl["title"], message=tpl["message"],
                     segment=tpl.get("segment") or "all",
                     customer_ids=(tpl.get("audience") or {}).get("ids") or None,
                     draft=True, push=True, wallet=True)
    if body.customer_ids is not None and not body.customer_ids:
        return None
    res = C.compose(body, token_data=type("T", (), {"tenant_id": shop.tid})())
    _db.campaigns.update_one({"id": res["id"]}, {"$set": {"copilot_step": step["id"],
                                                          "template": step["template"],
                                                          # the journal of ideas: what the Autopilot sent
                                                          "reco_key": step["template"], "reco_surface": "autopilot"}})
    return res["id"]


def autopilot_prepare(tid: str, at: Optional[datetime] = None, force: bool = False) -> int:
    """Prepare every campaign step of the plan that has no draft yet — when
    the owner asks (`force`), or for a plan still flagged by the old switch."""
    E = _engine()
    shop = E.Shop(tid, at or _now())
    doc = _plan(shop, recommendations(shop))
    if not force and not doc.get("autopilot"):
        return 0
    made = 0
    for step in doc["steps"]:
        if step["kind"] == "campaign" and not step.get("campaign_id") \
                and _step_date(doc, step) >= shop.at.date():
            cid = _prepare_step(shop, step)
            if cid:
                step["campaign_id"] = cid
                made += 1
    if made:
        _db.copilot_plans.update_one({"tenant_id": tid}, {"$set": {"steps": doc["steps"]}})
    return made


def run_autopilot(now: Optional[datetime] = None) -> Dict[str, int]:
    """Daily: prepare the week for every shop that switched Autopilot on."""
    out = {"tenants": 0, "prepared": 0}
    for doc in _db.copilot_plans.find({"autopilot": True}, {"_id": 0, "tenant_id": 1}):
        try:
            out["prepared"] += autopilot_prepare(doc["tenant_id"], now)
            out["tenants"] += 1
        except Exception as exc:
            print(f"copilot: autopilot failed for {doc['tenant_id']}: {exc}")
    return out


def pending_alerts(tid: str, now: datetime) -> List[Dict[str, Any]]:
    """What the bell says: prepared steps due today or overdue, waiting for an OK."""
    doc = _db.copilot_plans.find_one({"tenant_id": tid}, {"_id": 0})
    if not doc:
        return []
    out = []
    for step in doc.get("steps") or []:
        if not step.get("campaign_id") or _step_date(doc, step) > now.date():
            continue
        camp = _db.campaigns.find_one({"id": step["campaign_id"]}, {"_id": 0, "status": 1,
                                                                    "targeted_count": 1})
        if camp and camp.get("status") == "draft":
            out.append({"id": f"copilot:{step['id']}", "severity": "warning",
                        "title": f"FidClic IA : « {SHORT.get(step['key'], step['key'])} » prête",
                        "body": f"Campagne préparée pour {camp.get('targeted_count') or 0} clients. "
                                "Validez-la pour l'envoyer.",
                        "metric": str(camp.get("targeted_count") or 0),
                        "action": "/dashboard/ai-assistant#plan"})
    return out


# ---------------------------------------------------------------------------
# Endpoints — page, feedback, autopilot, plan
# ---------------------------------------------------------------------------
LEARNING = ["Analyse vos ventes en temps réel", "Comprend le comportement de vos clients",
            "Identifie les meilleures opportunités", "Améliore ses recommandations en continu"]


def _llm_ready() -> bool:
    try:
        from services import llm
        return bool(llm._force_complete) or llm.is_configured()
    except Exception:
        return False


def _is_owner(token_data: TokenData) -> bool:
    return getattr(token_data, "role", None) == "business_owner"


def _for(token_data: TokenData, recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Activating an automation or the Google review link changes the shop's
    settings: those ideas are the owner's to act on."""
    return recs if _is_owner(token_data) else [r for r in recs if r["kind"] != "setup"]


def _plan_view(shop, token_data: TokenData, recs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The 7-day plan sends to the whole shop: it is shown on the whole shop,
    to the owner. Anywhere else the page says where it lives."""
    if not _is_owner(token_data) or not shop.scope.is_all:
        return {"available": False, "autopilot": False, "steps": [],
                "note": ("Le plan d'action sur 7 jours concerne tout le commerce : "
                         "choisissez « Toutes les branches » pour le voir."
                         if _is_owner(token_data) else
                         "Le plan d'action sur 7 jours et l'Autopilot sont gérés par le propriétaire "
                         "pour tout le commerce.")}
    doc = _plan(shop, recs)
    by_key = {r["key"]: r for r in recs}
    from features import autopilot as AP
    return {"available": True, "autopilot": AP.any_on(shop.tid), "autopilot_plan_ok": AP.plan_ok(shop.tid),
            "start": doc["start"],
            "steps": [_step_view(shop, doc, s, by_key) for s in doc["steps"]]}


@router.get("/api/owner/copilot/page")
def page(horizon: int = 30, days: int = 7, request: Request = None,
         token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    E = _engine()
    horizon = horizon if horizon in HORIZONS else 30
    days = days if days in ACTIVITY_WINDOWS else 7
    scope = S.resolve(token_data, request)
    shop = E.Shop(token_data.tenant_id, _now(), scope)
    recs = _for(token_data, recommendations(shop))
    from features import plan_limits                      # « Analyses de base »: a few recommendations
    cap = plan_limits.ai_recommendation_limit(token_data.tenant_id)
    if cap is not None:
        recs = recs[:cap]
    fc = forecast_week(shop)
    opps = opportunities(shop, fc)
    # the journal of ideas (2026-10-29): shown, and what each brought last time
    from features import reco_journal as RJ
    RJ.shown(shop.tid, "copilote", recs, scope.key)
    RJ.attach(shop.tid, recs)
    return {
        "shop": {"name": shop.tenant.get("name") or "votre commerce", "sector": shop.sector},
        "scope": scope.describe(),
        "growth": growth(shop, recs, horizon),
        "recommendations": {"top": [_public(r) for r in recs[:3]],
                            "all": [_public(r) for r in recs], "total": len(recs)},
        "activity": activity(shop.tid, days, shop.at, scope),
        "opportunities": {"top": opps[:4], "all": opps, "total": len(opps)},
        "forecast": fc,
        "plan": _plan_view(shop, token_data, recs),
        "learning": LEARNING,
        "assistant": {"online": _llm_ready(),
                      "prompts": ["Augmenter mes ventes ce week-end", "Relancer mes clients inactifs",
                                  "Créer une campagne pour les étudiants",
                                  "Analyser mes derniers résultats",
                                  "Proposer une offre pour les anniversaires", "Autre demande…"]},
        "events_configured": events_configured(),
    }


class Feedback(BaseModel):
    kind: str


@router.post("/api/owner/copilot/recommendations/{key}/feedback")
def feedback(key: str, body: Feedback, request: Request = None,
             token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """"Pas pertinent", "Plus tard" or "accepted" — what the ranking learns from.
    Kept for the establishments it was given on (see _feedback)."""
    if body.kind not in (*FEEDBACK_DAYS, "accepted"):
        raise HTTPException(status_code=400, detail="Retour inconnu")
    at = _now()
    row = {"tenant_id": token_data.tenant_id, "key": key, "kind": body.kind, "at": at,
           # The owner's answer holds for every establishment.
           "store_key": S.ALL if _is_owner(token_data) else S.resolve(token_data, request).key}
    if body.kind in FEEDBACK_DAYS:
        row["until"] = at + timedelta(days=FEEDBACK_DAYS[body.kind])
    _db.copilot_feedback.insert_one(row)
    from features import reco_journal as RJ
    RJ.event(token_data.tenant_id, key, {"not_relevant": "dismissed"}.get(body.kind, body.kind), "copilote",
             row["store_key"], at)
    return {"ok": True}


class Autopilot(BaseModel):
    enabled: bool


@router.put("/api/owner/copilot/autopilot")
def set_autopilot(body: Autopilot, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """The Copilote's switch drives the one Autopilot (features/autopilot.py):
    on = its daily and weekly campaigns, at their current times; off = both off."""
    from features import autopilot as AP
    tid = token_data.tenant_id
    AP._require_plan(tid)
    cur = AP.settings(tid)
    on = bool(body.enabled)
    AP._db.autopilot_config.update_one({"tenant_id": tid}, {"$set": {
        "tenant_id": tid, "daily": {**cur["daily"], "enabled": on}, "weekly": {**cur["weekly"], "enabled": on},
        "updated_at": _now(), "updated_by": token_data.email}}, upsert=True)
    _db.copilot_plans.update_one({"tenant_id": tid}, {"$set": {"autopilot": False}})
    made = AP.prepare(tid) if on else []
    return {"autopilot": on, "prepared": sum(1 for m in made if m.get("status") == "pending")}


@router.post("/api/owner/copilot/plan/prepare")
def prepare_plan(token_data: TokenData = Depends(require_role(["business_owner"]))):
    """« Préparer les étapes » — drafts for the plan's campaign steps, sent by nobody."""
    return {"prepared": autopilot_prepare(token_data.tenant_id, force=True)}


class PlanEdit(BaseModel):
    steps: List[Dict[str, Any]]


@router.put("/api/owner/copilot/plan")
def edit_plan(body: PlanEdit, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """"Modifier le plan": keep, drop, re-day or add steps from the recommendations.

    Only keys the Copilote actually recommends today are accepted, each at most
    once, on a day inside the week.
    """
    E = _engine()
    tid = token_data.tenant_id
    shop = E.Shop(tid, _now())
    recs = {r["key"]: r for r in recommendations(shop)}
    doc = _plan(shop, list(recs.values()))
    old = {s["key"]: s for s in doc["steps"]}
    steps, seen = [], set()
    for s in body.steps:
        key, offset = str(s.get("key") or ""), int(_num(s.get("offset")))
        if key in seen or not (0 <= offset <= 6) or (key not in recs and key != "analyse"):
            continue
        seen.add(key)
        prev = old.get(key, {})
        r = recs.get(key, {})
        kind = "analysis" if key == "analyse" else r.get("kind", "campaign")
        if kind == "suggestion":
            continue
        steps.append({"id": prev.get("id") or str(uuid.uuid4()), "offset": offset, "key": key,
                      "kind": kind, "template": (r.get("cta") or {}).get("template"),
                      "day": (r.get("cta") or {}).get("day"),
                      "campaign_id": prev.get("campaign_id")})
    if not steps:
        raise HTTPException(status_code=400, detail="Le plan doit contenir au moins une étape.")
    steps.sort(key=lambda s: s["offset"])
    _db.copilot_plans.update_one({"tenant_id": tid}, {"$set": {"steps": steps, "updated_at": _now()}})
    if doc.get("autopilot"):
        autopilot_prepare(tid)
    return {"steps": len(steps)}


@router.post("/api/owner/copilot/plan/rebuild")
def rebuild_plan(token_data: TokenData = Depends(require_role(["business_owner"]))):
    E = _engine()
    shop = E.Shop(token_data.tenant_id, _now())
    _plan(shop, recommendations(shop), rebuild=True)
    if (_db.copilot_plans.find_one({"tenant_id": shop.tid}) or {}).get("autopilot"):
        autopilot_prepare(shop.tid)
    return {"ok": True}


@router.post("/api/owner/copilot/plan/steps/{step_id}/approve")
def approve(step_id: str, token_data: TokenData = Depends(require_role(["business_owner"]))):
    """The merchant's OK. Today's step is sent now; a later one is scheduled for
    its day, just before the daily run that will send it."""
    from features import campaigns_page as C
    E = _engine()
    tid = token_data.tenant_id
    shop = E.Shop(tid, _now())
    doc = _plan(shop, recommendations(shop))
    step = next((s for s in doc["steps"] if s["id"] == step_id), None)
    if not step or step["kind"] != "campaign":
        raise HTTPException(status_code=404, detail="Étape introuvable")
    if not step.get("campaign_id"):
        step["campaign_id"] = _prepare_step(shop, step)
        if not step["campaign_id"]:
            raise HTTPException(status_code=409, detail="Aucun client ne correspond à cette étape aujourd'hui.")
        _db.copilot_plans.update_one({"tenant_id": tid}, {"$set": {"steps": doc["steps"]}})
    camp = _db.campaigns.find_one({"id": step["campaign_id"], "tenant_id": tid}, {"_id": 0})
    if not camp or camp.get("status") != "draft":
        raise HTTPException(status_code=409, detail="Cette étape a déjà été validée.")

    day = _step_date(doc, step)
    if day <= shop.at.date():
        people = list(_db.customers.find({"tenant_id": tid, "id": {"$in": camp.get("recipient_ids") or []}},
                                         {"_id": 0}))
        camp["sent_at"] = shop.at
        camp.setdefault("channels", {"push": True, "wallet": True})
        # saved as sent, its delivery « pending », before delivering: a send cut
        # half-way is finished by the tick (campaigns_page.resume_due)
        _db.campaigns.update_one({"id": camp["id"]}, {"$set": {
            "status": "sent", "sent_at": shop.at, "channels": camp["channels"],
            "delivery": {"done": False, "at": shop.at}}})
        res = C._deliver(tid, camp, people)
        C.finish(camp["id"], res, shop.at)
        return {"status": "sent", "audience": len(people)}
    when = datetime(day.year, day.month, day.day, SEND_HOUR_UTC, 55, tzinfo=timezone.utc)
    _db.campaigns.update_one({"id": camp["id"]}, {"$set": {"status": "scheduled", "scheduled_for": when}})
    return {"status": "scheduled", "scheduled_for": when.isoformat()}


# ---------------------------------------------------------------------------
# The chat
# ---------------------------------------------------------------------------
INTENTS: List[Tuple[str, Tuple[str, ...]]] = [
    ("relance_inactifs", ("inactif", "relanc", "revenir", "reviennent")),
    ("offre_jour", ("week-end", "weekend", "vendredi", "samedi", "dimanche", "ventes")),
    ("etudiants", ("etudiant",)),
    ("anniversaires", ("anniversaire",)),
    ("a_risque", ("risque", "partir", "perdre", "habitue")),
    ("proximite", ("local", "proximite", "quartier", "a cote")),
    ("seconde_visite", ("nouveau", "deuxieme", "seconde", "2e visite")),
    ("avis_google", ("avis", "google")),
    ("resultats", ("resultat", "analyse", "performance", "statistique", "chiffre")),
]


def _intents(message: str) -> List[str]:
    m = _fold(message)
    return [key for key, words in INTENTS if any(w in m for w in words)]


def _facts(shop, recs: List[Dict[str, Any]], fc: Dict[str, Any],
           per: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    E = _engine()
    act = activity(shop.tid, 30, shop.at, getattr(shop, "scope", None))
    cards = {c["key"]: c for c in act["cards"]}
    best = E._best_weekday(shop)
    return {
        "commerce": shop.tenant.get("name"), "secteur": shop.sector,
        "metier": PB.prompt_context(shop.play, PB.paris_month(shop.at)),
        "clients_total": len(shop.people),
        "clients_inactifs_30j": len(E._inactive(shop)),
        "clients_a_risque": len(E._at_risk(shop)),
        "anniversaires_7j": len(E._birthdays(shop, 7)),
        "etudiants": len(E._students(shop)),
        "nouveaux_une_visite": len(E._one_timers(shop)),
        "visites_30j": cards["visits"]["value"], "evolution_visites_pct": cards["visits"]["delta"],
        "ca_30j_eur": cards["revenue"]["value"], "evolution_ca_pct": cards["revenue"]["delta"],
        "panier_moyen_eur": cards["basket"]["value"],
        "meilleur_jour": E.WEEKDAY_FR[best["weekday"]] if best else None,
        "meilleur_jour_ecart_pct": best["lift"] if best else None,
        "produit_star": E._top_product(shop),
        "prevision_affluence": ({"jour": E.WEEKDAY_FR[p["weekday"]], "visites": p["predicted"],
                                 "moyenne": fc["mean"]}
                                if (p := max(fc["days"], key=lambda d: d["predicted"], default=None))
                                else None),
        "recommandations": [{"cle": r["key"], "titre": r["title"], "clients": r.get("audience"),
                             "impact": [m["label"] for m in r["metrics"]]} for r in recs[:6]],
        **({"periode_demandee": _period_facts(shop, per)} if per else {}),
    }


def _period_facts(shop, per: Dict[str, Any]) -> Dict[str, Any]:
    f = period_figures(shop.tid, per, getattr(shop, "scope", None))
    loc = lambda d: d.astimezone(PARIS).strftime("%d/%m/%Y %H:%M")   # noqa: E731
    return {"libelle": per["label"], "du": loc(per["start"]), "au": loc(per["end"]),
            "visites": f["visits"], "chiffre_affaires_eur": f["revenue"], "panier_moyen_eur": f["basket"],
            "clients_venus": f["clients"], "evolution_visites_pct": f["delta_visits"],
            "evolution_ca_pct": f["delta_revenue"],
            "periode_precedente": {"visites": f["previous"]["visits"], "chiffre_affaires_eur": f["previous"]["revenue"]}}


_SYSTEM = (
    "Tu es FidClic IA Copilote, l'assistant stratégique d'un commerçant français. "
    "Réponds en français, en 120 mots maximum, de façon concrète et chaleureuse. "
    "La question porte sur la période de « periode_demandee » (aujourd'hui, 7 jours, ce mois…) : donne "
    "ses chiffres à elle et nomme-la ; les champs « _30j » ne servent que de contexte. Écris les montants "
    "au centime près à la française (12,50 €) et accorde les pluriels (1 visite, 2 visites). "
    "Appuie-toi UNIQUEMENT sur les données JSON fournies : n'invente aucun chiffre, aucun client, "
    "aucun produit. Si une donnée manque, dis-le simplement. Ne promets jamais un résultat : parle "
    "d'estimations. Ne dis jamais que tu as envoyé ou créé quelque chose : le commerçant agit lui-même "
    "grâce aux boutons proposés sous ta réponse. Le champ « metier » décrit son métier et ses règles : "
    "tes conseils restent dans ce métier et les respectent. "
    "Tu disposes aussi de la conversation récente, d'un résumé des échanges plus anciens et de « Ce que "
    "FidClic IA retient » (ce que le commerçant t'a dit de lui) : sers-t'en pour comprendre une question "
    "de suite (« et la semaine dernière ? ») et respecte ce qu'il t'a dit ; les chiffres viennent "
    "toujours des données JSON."
)


def _fallback(intents: List[str], facts: Dict[str, Any], recs_by_key: Dict[str, Any]) -> str:
    """An answer from the facts alone, when the model cannot be reached."""
    parts = []
    for key in intents:
        r = recs_by_key.get(key)
        if key == "resultats":
            p = facts.get("periode_demandee") or {}
            label = p.get("libelle") or "les 30 derniers jours"
            n = int(p.get("visites", facts.get("visites_30j") or 0))
            ca = p.get("chiffre_affaires_eur", facts.get("ca_30j_eur") or 0)
            ev = p.get("evolution_ca_pct") if p else facts.get("evolution_ca_pct")
            line = f"{label[0].upper()}{label[1:]} : {_pl(n, 'visite', 'visites')} et {_eur_exact(ca)} de chiffre d'affaires"
            if n:
                line += f", panier moyen {_eur_exact(p.get('panier_moyen_eur', facts.get('panier_moyen_eur') or 0))}"
            parts.append(line + (f" ({'+' if ev >= 0 else ''}{ev} % vs la période précédente)." if ev is not None else "."))
        elif r:
            parts.append(f"{r['title']} : impact estimé {', '.join(m['label'] for m in r['metrics'])}.")
    if not parts:
        top = list(recs_by_key.values())[:2]
        parts = ([f"Ma priorité pour vous : {top[0]['title'].lower()}."] if top else
                 ["Je n'ai pas encore assez de données sur votre commerce pour vous conseiller précisément."])
    return " ".join(parts)


def _actions(intents: List[str], recs_by_key: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for key in intents:
        if key == "resultats":
            out.append({"label": "Ouvrir les analyses", "kind": "navigate", "to": "/dashboard/analytics"})
            continue
        r = recs_by_key.get(key)
        if r:
            out.append({"key": r["key"], **r["cta"]})
    return out[:3]


class ChatIn(BaseModel):
    message: str


def _mine(token_data: TokenData) -> Dict[str, Any]:
    """Each account keeps its own conversation. Messages from before accounts
    were told apart belong to the owner."""
    q: Dict[str, Any] = {"tenant_id": token_data.tenant_id}
    email = getattr(token_data, "email", None)
    if _is_owner(token_data):
        q["$or"] = [{"by": email}, {"by": {"$exists": False}}]
    else:
        q["by"] = email
    return q


HISTORY_PAGE = 20


@router.get("/api/owner/copilot/chat")
def chat_history(before: Optional[str] = None,
                 token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    """The whole conversation is kept (user: « max yaad »): a page of it,
    older pages with `before`."""
    q = _mine(token_data)
    if before:
        try:
            b = datetime.fromisoformat(before.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Date invalide.")
        q = {"$and": [q, {"at": {"$lt": b if b.tzinfo else b.replace(tzinfo=timezone.utc)}}]}
    rows = list(_db.copilot_chats.find(q, {"_id": 0}).sort("at", -1).limit(HISTORY_PAGE + 1))
    more = len(rows) > HISTORY_PAGE
    rows = rows[:HISTORY_PAGE]
    oldest = rows[-1]["at"] if rows else None
    if isinstance(oldest, datetime) and oldest.tzinfo is None:
        oldest = oldest.replace(tzinfo=timezone.utc)
    return {"messages": [{"role": r["role"], "text": r["text"], "actions": r.get("actions") or []}
                         for r in reversed(rows)],
            "has_more": more, "before": oldest.isoformat() if isinstance(oldest, datetime) else None}


@router.post("/api/owner/copilot/chat")
def chat(body: ChatIn, request: Request = None,
         token_data: TokenData = Depends(require_role(READERS, partial_ok=True))):
    E = _engine()
    message = re.sub(r"\s+", " ", (body.message or "").strip())[:500]
    if not message:
        raise HTTPException(status_code=400, detail="Posez votre question.")
    tid = token_data.tenant_id
    scope = S.resolve(token_data, request)
    shop = E.Shop(tid, _now(), scope)
    recs = _for(token_data, recommendations(shop))
    # What the merchant asks for directly is always available — even a
    # recommendation resting after recent use or one they dismissed. The
    # shelves step aside; the chat does not refuse.
    by_key = {r["key"]: r for r in _for(token_data, _library(shop))}
    fc = forecast_week(shop)
    per = period_of(message, shop.at)
    facts = _facts(shop, recs, fc, per)
    used = shop.used
    if scope.ids is not None:
        facts["etablissements"] = scope.describe()["label"]
    facts["campagnes_recentes"] = [{"modele": k, "le": v["at"].date().isoformat(), "statut": v["status"]}
                                   for k, v in used.items()]
    intents = _intents(message)
    # « et aujourd'hui ? » asks for the figures even without « chiffres »
    if per["explicit"] and "resultats" not in intents:
        intents.insert(0, "resultats")

    email = getattr(token_data, "email", None)
    remembered = CM.explicit(message)            # « Retiens que… »: kept at once
    if remembered:
        CM.add(tid, email, remembered, "chat")

    reply, source = None, "model"
    if _llm_ready():
        try:
            from services import llm
            try:
                memory = CM.context(tid, email, _is_owner(token_data))
            except Exception as exc:              # the memory never stops an answer
                print(f"copilot: memory unavailable ({exc})")
                memory = ""
            reply = llm.complete(_SYSTEM, (f"{memory}\n\n" if memory else "")
                                 + f"Données du commerce (JSON) :\n{json.dumps(facts, ensure_ascii=False)}"
                                   f"\n\nQuestion du commerçant : {CM.scrub(message)}",
                                 max_tokens=320, temperature=0.4)
        except Exception as exc:
            print(f"copilot: chat model failed ({exc})")
            reply = None
    if not (reply or "").strip():
        reply, source = _fallback(intents, facts, by_key), "facts"
        if remembered:
            reply = f"C'est noté : « {CM.scrub(remembered)} ». Vous le retrouvez dans « Ce que FidClic IA retient ». {reply}"
    actions = _actions(intents, by_key)

    at = _now()
    _db.copilot_chats.insert_many([
        {"tenant_id": tid, "by": email, "role": "user", "text": message, "at": at,
         **({"memo": True} if remembered else {})},
        {"tenant_id": tid, "by": email, "role": "assistant", "text": reply.strip(),
         "actions": actions, "source": source, "at": at + timedelta(milliseconds=1)},
    ])
    return {"reply": reply.strip(), "actions": actions, "source": source}
