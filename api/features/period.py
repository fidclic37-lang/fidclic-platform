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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
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


def hourly(days: int) -> bool:
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
