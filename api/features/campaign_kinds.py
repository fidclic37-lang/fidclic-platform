"""
Campagnes › the four kinds of campaign, their offer window, their status and
their audience (redesign from the user's mockups, 2026-10-10).

    offre       Offre spéciale — « -20 % » or « -5 € », from a day to a day,
                all day or between two hours (happy hours).
    nouveaute   Nouveauté — a title, a description and a photo.
    evenement   Événement — a day, an hour, a place.
    defi        Défi — N visits before a day wins a reward (features/defis.py).

A campaign is LIVE on the customer's card from its send until its end: the
offer's last day, the event's day, the défi's last day — or, without dates,
30 days after the send (as before). Its status in « Vos campagnes récentes »
follows: « En cours » while live, « Terminée » after.

Everything here is in Paris time: « jusqu'au 17 octobre » ends at 23:59:59 in
Paris, and a happy hour « 17:00–19:00 » is the shop's clock.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel

PARIS = ZoneInfo("Europe/Paris")
# A campaign stays on the card until the date the owner chose (« Sur la carte
# jusqu'au », asked for every campaign since 2026-10-20). Without one — sent
# before that, or by FidClic IA — a week, never the hidden 30 days that kept a
# one-client message live for a month and brought it back (user: « campaign
# chala gya and expire ho gya toh hatao »).
DEFAULT_LIVE_DAYS = 7

KINDS = {"offre": "Offre spéciale", "nouveaute": "Nouveauté", "evenement": "Événement", "defi": "Défi",
         "configurer": "Configurer une offre"}
# « Configurer une offre » = any other message (user, 2026-10-10): a title, a
# description and optional dates/hours, shown on the card like an offer, with
# no discount.
OFFER_KINDS = ("offre", "configurer")
LEGACY_LABEL = "Notification"

STATUS_LABELS = {"draft": "Brouillon", "scheduled": "Programmée", "sending": "En cours d'envoi",
                 "cancelled": "Annulée", "live": "En cours", "ended": "Terminée"}
TABS = {"all", "live", "scheduled", "ended", "cancelled"}


class OfferIn(BaseModel):
    discount_type: Optional[str] = None       # percent · amount · None
    discount_value: Optional[float] = None
    start_date: Optional[str] = None          # YYYY-MM-DD (Paris)
    end_date: Optional[str] = None
    all_day: bool = True
    time_from: Optional[str] = None           # HH:MM
    time_to: Optional[str] = None


class EventIn(BaseModel):
    date: Optional[str] = None
    time: Optional[str] = None
    place: Optional[str] = None


class DefiIn(BaseModel):
    # Any: checked by clean_defi (pydantic would turn `true` into 1)
    target: Optional[Any] = None
    end_date: Optional[str] = None
    count_mode: str = "per_day"               # per_day · per_scan (the owner chooses)
    reward: Optional[str] = None
    reward_valid_days: Optional[Any] = None


def _whole(v: Any) -> Optional[int]:
    """A whole number, as a number or its digits — never true/false, 2.5 or text."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


class FiltersIn(BaseModel):
    active: bool = False
    inactive: bool = False
    new: bool = False
    min_points: Optional[int] = None


class AudienceIn(BaseModel):
    mode: str = "all"                         # all · segment · custom · zone
    segment: Optional[str] = None
    customer_ids: Optional[List[str]] = None
    km: Optional[float] = None
    filters: Optional[FiltersIn] = None


# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _day(text: Optional[str], what: str) -> Optional[date]:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{what} : date invalide.")


_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _hhmm(text: Optional[str], what: str) -> Optional[str]:
    if not text:
        return None
    s = str(text).strip()
    if not _HHMM.match(s):
        raise HTTPException(status_code=400, detail=f"{what} : heure invalide (HH:MM).")
    return s


def start_of(d: date) -> datetime:
    return datetime.combine(d, dtime(0, 0), PARIS).astimezone(timezone.utc)


def end_of(d: date) -> datetime:
    return datetime.combine(d, dtime(23, 59, 59), PARIS).astimezone(timezone.utc)


def paris_today(at: Optional[datetime] = None) -> date:
    return (at or _now()).astimezone(PARIS).date()


def month_bounds(at: Optional[datetime] = None) -> Tuple[datetime, datetime, datetime]:
    """This calendar month's start (Paris), the previous month's start, and now
    — the five figures read « ce mois-ci vs. mois précédent » (user's choice)."""
    at = at or _now()
    local = at.astimezone(PARIS)
    first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = (first - timedelta(days=1)).replace(day=1)
    return first.astimezone(timezone.utc), prev.astimezone(timezone.utc), at


# ---------------------------------------------------------------------------
# validation — what the wizard's step 1 sends
# ---------------------------------------------------------------------------
def clean_kind(kind: Optional[str]) -> Optional[str]:
    if kind in (None, ""):
        return None
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Type de campagne inconnu.")
    return kind


def clean_offer(o: Optional[OfferIn], send_at: datetime) -> Optional[Dict[str, Any]]:
    """An Offre spéciale's terms. Everything optional but coherent."""
    if o is None:
        return None
    out: Dict[str, Any] = {"discount_type": None, "discount_value": None}
    if o.discount_type not in (None, "", "percent", "amount"):
        raise HTTPException(status_code=400, detail="Type de réduction invalide.")
    if o.discount_type:
        v = o.discount_value
        if v is None or not isinstance(v, (int, float)) or v != v or v <= 0:
            raise HTTPException(status_code=400, detail="Indiquez la valeur de la réduction.")
        if o.discount_type == "percent" and v > 100:
            raise HTTPException(status_code=400, detail="Une réduction en pourcentage ne dépasse pas 100 %.")
        if o.discount_type == "amount" and v > 10000:
            raise HTTPException(status_code=400, detail="Montant de réduction trop élevé.")
        out.update(discount_type=o.discount_type, discount_value=round(float(v), 2))
    start, end = _day(o.start_date, "Date de début"), _day(o.end_date, "Date de fin")
    today = paris_today(send_at)
    if end and not start:
        start = today
    if start and not end:
        raise HTTPException(status_code=400, detail="Indiquez aussi la date de fin de l'offre.")
    if start and end:
        if end < start:
            raise HTTPException(status_code=400, detail="La date de fin est avant la date de début.")
        if end_of(end) < send_at:
            raise HTTPException(status_code=400, detail="L'offre serait déjà terminée à l'envoi : choisissez une date de fin plus tardive.")
    out.update(start_date=start.isoformat() if start else None, end_date=end.isoformat() if end else None)
    out["all_day"] = bool(o.all_day)
    if not o.all_day:
        a, b = _hhmm(o.time_from, "Heure de début"), _hhmm(o.time_to, "Heure de fin")
        if not a or not b:
            raise HTTPException(status_code=400, detail="Indiquez l'heure de début et l'heure de fin, ou choisissez « Toute la journée ».")
        if b <= a:
            raise HTTPException(status_code=400, detail="L'heure de fin doit être après l'heure de début.")
        out.update(time_from=a, time_to=b)
    else:
        out.update(time_from=None, time_to=None)
    return out


def clean_event(e: Optional[EventIn], send_at: datetime) -> Optional[Dict[str, Any]]:
    if e is None:
        return None
    d = _day(e.date, "Date de l'événement")
    if not d:
        raise HTTPException(status_code=400, detail="Indiquez la date de l'événement.")
    if end_of(d) < send_at:
        raise HTTPException(status_code=400, detail="L'événement serait déjà passé à l'envoi.")
    place = re.sub(r"\s+", " ", (e.place or "").strip())[:120] or None
    return {"date": d.isoformat(), "time": _hhmm(e.time, "Heure de l'événement"), "place": place}


def clean_defi(x: Optional[DefiIn], send_at: datetime) -> Dict[str, Any]:
    if x is None:
        raise HTTPException(status_code=400, detail="Décrivez le défi.")
    target = _whole(x.target)
    if target is None or not 1 <= target <= 100:
        raise HTTPException(status_code=400, detail="Nombre de visites du défi : entre 1 et 100.")
    end = _day(x.end_date, "Date de fin du défi")
    if not end:
        raise HTTPException(status_code=400, detail="Indiquez la date de fin du défi.")
    if end_of(end) <= send_at:
        raise HTTPException(status_code=400, detail="Le défi serait déjà terminé à l'envoi : choisissez une date de fin plus tardive.")
    if x.count_mode not in ("per_day", "per_scan"):
        raise HTTPException(status_code=400, detail="Mode de comptage du défi invalide.")
    if x.count_mode == "per_day":
        days = (end - paris_today(send_at)).days + 1
        if target > days:
            raise HTTPException(status_code=400, detail=(
                f"Impossible : {target} visites à raison d'une par jour, mais le défi ne dure que "
                f"{days} jour{'s' if days > 1 else ''}. Reculez la date de fin ou comptez chaque passage."))
    reward = re.sub(r"\s+", " ", (x.reward or "").strip())[:80]
    if not reward:
        raise HTTPException(status_code=400, detail="Indiquez la récompense du défi.")
    valid = _whole(x.reward_valid_days)
    if valid is None or not 1 <= valid <= 365:
        raise HTTPException(status_code=400, detail="Validité de la récompense : entre 1 et 365 jours.")
    return {"target": target, "end_date": end.isoformat(), "count_mode": x.count_mode,
            "reward": reward, "reward_valid_days": valid}


# ---------------------------------------------------------------------------
# when a campaign is live
# ---------------------------------------------------------------------------
def window(c: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    """(from, until) a sent campaign stays on the card."""
    sent = aware(c.get("sent_at"))
    kind = c.get("kind")
    until = None
    start = sent
    if kind in OFFER_KINDS and (c.get("offer") or {}).get("end_date"):
        until = end_of(date.fromisoformat(c["offer"]["end_date"]))
        if c["offer"].get("start_date"):
            s = start_of(date.fromisoformat(c["offer"]["start_date"]))
            start = max(s, sent) if sent else s
    elif kind == "evenement" and (c.get("event") or {}).get("date"):
        until = end_of(date.fromisoformat(c["event"]["date"]))
    elif kind == "defi" and (c.get("defi") or {}).get("end_date"):
        until = end_of(date.fromisoformat(c["defi"]["end_date"]))
    elif c.get("visible_until"):                  # a Nouveauté: the day the owner chose
        until = end_of(date.fromisoformat(str(c["visible_until"])[:10]))
    if until is None and sent:
        until = sent + timedelta(days=DEFAULT_LIVE_DAYS)
    return start, until


def is_live(c: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    if c.get("status") != "sent":
        return False
    at = at or _now()
    sent = aware(c.get("sent_at"))
    _, until = window(c)
    return bool(sent and until and sent <= at <= until)


def active_now(c: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    """Valid at this very moment at the till: live, started, and inside its
    hours when it has some (happy hour)."""
    at = at or _now()
    if not is_live(c, at):
        return False
    start, _ = window(c)
    if start and at < start:
        return False
    o = c.get("offer") or {}
    if c.get("kind") in OFFER_KINDS and not o.get("all_day", True) and o.get("time_from") and o.get("time_to"):
        hm = at.astimezone(PARIS).strftime("%H:%M")
        return o["time_from"] <= hm < o["time_to"]
    return True


def status_of(c: Dict[str, Any], at: Optional[datetime] = None) -> str:
    st = c.get("status") or "draft"
    if st == "sent":
        return "live" if is_live(c, at) else "ended"
    return st if st in STATUS_LABELS else "draft"


def tab_of(st: str) -> str:
    return {"live": "live", "sending": "live", "scheduled": "scheduled", "ended": "ended",
            "cancelled": "cancelled"}.get(st, "all")


def _money(v: float) -> str:
    s = f"{v:,.2f}".replace(",", " ").replace(".", ",")
    return s[:-3] if s.endswith(",00") else s


def discount_label(o: Optional[Dict[str, Any]]) -> Optional[str]:
    if not o or not o.get("discount_type") or not o.get("discount_value"):
        return None
    v = float(o["discount_value"])
    return f"-{_money(v)} %" if o["discount_type"] == "percent" else f"-{_money(v)} €"


def _fr_day(d: date) -> str:
    months = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    return f"{d.day} {months[d.month - 1]}"


def _h(hm: str) -> str:
    """« 17:00 » → « 17h », « 17:30 » → « 17h30 »."""
    h, m = hm.split(":")
    return f"{int(h)}h" + ("" if m == "00" else m)


def hours_label(o: Optional[Dict[str, Any]]) -> Optional[str]:
    if not o or o.get("all_day", True) or not o.get("time_from"):
        return None
    return f"{_h(o['time_from'])}–{_h(o['time_to'])}"


def terms_label(c: Dict[str, Any]) -> Optional[str]:
    """One line for the card, the offers page and the till: what and when."""
    kind = c.get("kind")
    parts: List[str] = []
    if kind in OFFER_KINDS:
        o = c.get("offer") or {}
        if discount_label(o):
            parts.append(discount_label(o))
        if o.get("start_date") and o.get("end_date"):
            s, e = date.fromisoformat(o["start_date"]), date.fromisoformat(o["end_date"])
            parts.append(f"le {_fr_day(s)}" if s == e else f"du {_fr_day(s)} au {_fr_day(e)}")
        if hours_label(o):
            parts.append(hours_label(o))
    elif kind == "evenement":
        e = c.get("event") or {}
        if e.get("date"):
            parts.append(f"le {_fr_day(date.fromisoformat(e['date']))}"
                         + (f" à {_h(e['time'])}" if e.get("time") else ""))
        if e.get("place"):
            parts.append(e["place"])
    return " · ".join(parts) or None


# ---------------------------------------------------------------------------
# audience
# ---------------------------------------------------------------------------
NEW_DAYS = 30


def apply_filters(tid: str, people: List[Dict[str, Any]], f: Optional[FiltersIn],
                  at: datetime) -> List[Dict[str, Any]]:
    """The optional filters narrow the chosen group (AND)."""
    if not f:
        return people
    from features import clients_page as CP, customer_rules as R
    rules = R.load(tid) if (f.active or f.inactive) else None
    out = []
    for c in people:
        if f.inactive and not CP.is_inactive(c, at, rules):
            continue
        if f.active and (CP.is_inactive(c, at, rules) or int(c.get("visits") or 0) <= 0):
            continue
        if f.new:
            joined = aware(c.get("created_at"))
            if not joined or joined < at - timedelta(days=NEW_DAYS):
                continue
        if f.min_points is not None and int(c.get("points") or 0) < int(f.min_points):
            continue
        out.append(c)
    return out


def filters_label(f: Optional[FiltersIn]) -> str:
    if not f:
        return ""
    bits: List[str] = []
    if f.active:
        bits.append("actifs")
    if f.inactive:
        bits.append("inactifs")
    if f.new:
        bits.append("nouveaux")
    if f.min_points is not None:
        bits.append(f"≥ {int(f.min_points)} points")
    return (" · " + ", ".join(bits)) if bits else ""


def zone_people(tid: str, people: List[Dict[str, Any]], km: float) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
    from features import segmentation as SEG
    dist = SEG._distances(tid, people)
    if not dist:
        raise HTTPException(status_code=400, detail="La position de votre boutique est inconnue : "
                                                    "renseignez son adresse dans Paramètres › Établissement.")
    inside = [c for c in people if (d := dist.get(c["id"])) is not None and d <= km]
    return inside, dist
