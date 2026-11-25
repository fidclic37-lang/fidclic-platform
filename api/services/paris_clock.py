"""Days counted on the Paris clock (user, 2026-11-25).

« Pas venu depuis N jours » means: N calendar days later, at the same time on
the shop's clock. Counting 24-hour blocks instead put a client in « Clients
inactifs » an hour early after the October clock change (and an hour late
after the March one): the night of the change has 25 hours (or 23).

`days_between(a, b)` reads both instants on the Paris wall clock and returns
the days between them as a float — 36.0 from 20 Oct 12:22 to 25 Nov 12:22,
whatever happened to the clocks in between. A naive datetime is UTC (that is
how Mongo hands dates back); an ISO string is parsed; anything else is None.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _wall(d: datetime) -> datetime:
    """The Paris clock reading: the instant moved by Paris' offset at that
    instant (the difference of two of these is the wall-clock difference).
    Four times faster than building a naive Paris datetime — this runs once
    per client on every list, count and relance tick. A date at the edge of
    the calendar (year 9999 from a broken import) stays as it is rather than
    taking the whole Clients page down."""
    try:
        return d + d.astimezone(PARIS).utcoffset()
    except (OverflowError, ValueError):
        return d


def days_between(start: Any, end: Any) -> Optional[float]:
    a, b = _aware(start), _aware(end)
    if a is None or b is None:
        return None
    return (_wall(b) - _wall(a)).total_seconds() / 86400.0
