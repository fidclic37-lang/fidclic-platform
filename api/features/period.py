"""
The period a merchant reads their figures over — shared by the Tableau de bord
and Analyses so both pages cut the same days the same way.

A DAY IS A PARIS DAY
    « Aujourd'hui » starts at midnight in the shop, not at midnight UTC (which
    is 1h or 2h in France): a visit at 00:30 belongs to today, and the hour a
    client came is the hour on the shop's clock.

« AUJOURD'HUI » IS DRAWN HOUR BY HOUR
    One point per day would draw a single dot. With `days == 1` the series are
    cut by hour instead, from midnight to the current hour.

HOW FAR BACK
    The merchant may type their own period, in days or months, up to two years.

A CALENDAR PERIOD (user, 2026-11-03)
    A whole month, one date, a from–to range, « Ce mois-ci »: `span(date_from,
    date_to)` cuts Paris days, the start of the first to the end of the last —
    a period that reaches today ends now. The period it is compared with is the
    same slice one month earlier (a month → the month before, 1–15 → 1–15, a
    date → that date last month), the day clamped to the month's length.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
MAX_DAYS = 730


def clamp_days(value: Any, fallback: int = 30) -> int:
    """FastAPI hands over an int; a test or a cron may hand the Query default
    object instead. Coerce rather than fail on a page that is only read."""
    try:
        return max(1, min(MAX_DAYS, int(value)))
    except (TypeError, ValueError):
        return fallback


def local(dt: datetime) -> datetime:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(PARIS)


def window(days: int, now: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """From midnight (Paris) `days - 1` days ago until now, in UTC."""
    end = now or datetime.now(timezone.utc)
    first = local(end) - timedelta(days=clamp_days(days) - 1)
    start = datetime(first.year, first.month, first.day, tzinfo=PARIS)
    return start.astimezone(timezone.utc), end


@dataclass(frozen=True)
class Span:
    """The period read and the one it is compared with, in UTC."""
    start: datetime
    end: datetime
    prev_start: datetime
    prev_end: datetime
    days: int                           # Paris days covered (today included)
    date_from: Optional[str] = None     # the calendar dates asked, when they were
    date_to: Optional[str] = None

    @property
    def hourly(self) -> bool:
        return self.days == 1


def _refuse(msg: str):
    from fastapi import HTTPException
    raise HTTPException(status_code=422, detail=msg)


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        _refuse("Date invalide : attendu AAAA-MM-JJ.")


def _month_back(d: date) -> date:
    """The same date one month earlier, clamped (31 mars → 28 février); the
    last day of a month stays the last day of the month before."""
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    last = calendar.monthrange(y, m)[1]
    if d.day == calendar.monthrange(d.year, d.month)[1]:
        return date(y, m, last)
    return date(y, m, min(d.day, last))


def _midnight(d: date) -> datetime:
    return datetime.combine(d, time(0), PARIS).astimezone(timezone.utc)


def _last_instant(d: date) -> datetime:
    return _midnight(d + timedelta(days=1)) - timedelta(microseconds=1)


def span(days: Any = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
         now: Optional[datetime] = None) -> Span:
    """The period of a page: `days` back from today as before, or the Paris
    calendar dates date_from → date_to (both, inclusive). A future day, from
    after to, a date further back than two years: 422."""
    now = now or datetime.now(timezone.utc)
    if not date_from and not date_to:
        start, end = window(days if days is not None else 30, now)
        prev_end = start - timedelta(microseconds=1)
        return Span(start, end, prev_end - (end - start), prev_end, clamp_days(days if days is not None else 30))
    if not (date_from and date_to):
        _refuse("Une période demande une date de début et une date de fin.")
    a, b = _day(date_from), _day(date_to)
    today = local(now).date()
    if a > b:
        _refuse("La date de début est après la date de fin.")
    if a > today:
        _refuse("Cette période n'a pas encore commencé.")
    if (today - a).days >= MAX_DAYS:
        _refuse("Deux ans en arrière au maximum.")
    live = b >= today
    b = min(b, today)
    start = _midnight(a)
    end = now if live else _last_instant(b)
    pa = _month_back(a)
    if live:
        # until now: the month before, until the same hour of the same day
        clock = local(now)
        pm = _month_back(date(b.year, b.month, 1))
        pb = date(pm.year, pm.month, min(b.day, calendar.monthrange(pm.year, pm.month)[1]))
        prev_end = datetime.combine(pb, clock.timetz().replace(tzinfo=None), PARIS).astimezone(timezone.utc)
    else:
        prev_end = _last_instant(_month_back(b))
    return Span(start, end, _midnight(pa), prev_end, (b - a).days + 1, a.isoformat(), b.isoformat())


def hourly(days: Union[int, Span]) -> bool:
    if isinstance(days, Span):
        return days.hourly
    return clamp_days(days) == 1


def key_of(dt: datetime, days: int) -> str:
    t = local(dt)
    return f"{t.date().isoformat()}T{t.hour:02d}:00" if hourly(days) else t.date().isoformat()


def slots(start: datetime, end: datetime, days: int) -> List[Dict[str, Any]]:
    """Every bucket of the period, oldest first: {"date", "label"?}."""
    a, b = local(start), local(end)
    if hourly(days):
        return [{"date": f"{a.date().isoformat()}T{h:02d}:00", "label": f"{h}h"}
                for h in range(0, b.hour + 1)]
    return [{"date": (a.date() + timedelta(days=i)).isoformat()}
            for i in range((b.date() - a.date()).days + 1)]
