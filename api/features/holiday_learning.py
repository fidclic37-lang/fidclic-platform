"""
Les jours fériés, appris (user, 2026-10-30: « pichhle fériés se seekho and
also from other shops of same sectors, taaki learning ekdm robust ho »).

A holiday's effect on a shop open that day is its visits that day over the
usual visits of that weekday — the open days of the 8 weeks before, holidays
left out. Read from the daily register (features/visit_days), Paris days.

- The shop's own: every past holiday it was open (it had visits that day,
  and its Horaires do not say closed), over two years.
- The network: each shop's average for that holiday, then the middle shop's
  (median: one odd shop does not move it, as in features/reco_ranking) — by
  activité, then secteur, never another trade's, only from 3 shops; a figure
  for « any holiday » when that one holiday has too few. Relearned once a
  day by the tick; it keeps counts, never a shop id.
- The forecast's factor: the shop's own, pulled toward the network's (the
  network weighs as much as 2 holidays of its own); without a network, from
  2 of its own; else none — the day is only named.
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple

_db = None
NET_KEY = "holiday_network"
NET_MIN_SHOPS = 3
NET_WEIGHT = 2.0           # the network counts as this many holidays of one's own
OWN_MIN = 2                # without a network: this many of one's own
LOOKBACK_DAYS = 730
BASE_WEEKS = 8
BASE_MIN_DAYS = 3
CLIP = (0.2, 4.0)
LEARN_EVERY = timedelta(hours=24)
CACHE_TTL_S = 6 * 3600
_cache: Dict[str, Tuple[float, Any]] = {}
MASCULINE = {"jour_de_lan", "lundi_paques", "lundi_pentecote", "armistice", "noel"}


def init(db):
    global _db
    _db = db


def NOW() -> datetime:                      # the clock (tests set it)
    return datetime.now(timezone.utc)


def _paris_today(at: datetime) -> date:
    from features import visit_days as VD
    return date.fromisoformat(VD.day_of(at))


def holidays_between(a: date, b: date) -> List[Dict[str, Any]]:
    from features import business_hours as BH
    out = []
    for y in range(a.year, b.year + 1):
        for h in BH.french_public_holidays(y):
            d = date.fromisoformat(h["date"])
            if a <= d <= b:
                out.append({"date": d, "key": h["key"], "name": h["name"]})
    return out


def daily_counts(tid: str, scope, first: date, last: date, at: datetime) -> Dict[date, int]:
    """Visits per Paris day, from the register (today live)."""
    from features import visit_days as VD
    if last < first:
        return {}
    a = VD.day_start(first.isoformat())
    b = VD.day_start((last + timedelta(days=1)).isoformat()) - timedelta(microseconds=1)
    tot = VD.span_many(tid, scope, [(a, b)], at, judge=False)[0]
    out: Dict[date, int] = defaultdict(int)
    for (day, _h), (n, _r) in tot.hours.items():
        out[date.fromisoformat(day)] += n
    return dict(out)


def _closed_fn(tid: str):
    from features import business_hours as BH
    tenant = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    return lambda d: BH.closed_reason(tenant, d)


def ratios(tid: str, scope, at: datetime) -> Dict[str, List[float]]:
    """{holiday key: [visits that day / that weekday's usual]} — the shop's
    past holidays it was open, over two years."""
    today = _paris_today(at)
    hols = holidays_between(today - timedelta(days=LOOKBACK_DAYS), today - timedelta(days=1))
    if not hols:
        return {}
    first = min(h["date"] for h in hols) - timedelta(weeks=BASE_WEEKS)
    counts = daily_counts(tid, scope, first, today - timedelta(days=1), at)
    if not counts:
        return {}
    closed = _closed_fn(tid)
    hol_days = {h["date"] for h in hols}
    out: Dict[str, List[float]] = defaultdict(list)
    for h in hols:
        d = h["date"]
        n = counts.get(d, 0)
        if n <= 0 or closed(d):                  # no visits: closed that day — not a measure
            continue
        same = [counts.get(d - timedelta(weeks=k), 0) for k in range(1, BASE_WEEKS + 1)
                if (d - timedelta(weeks=k)) not in hol_days and not closed(d - timedelta(weeks=k))]
        same = [x for x in same if x > 0]
        if len(same) < BASE_MIN_DAYS:
            continue
        out[h["key"]].append(n / mean(same))
    return dict(out)


def own_ratios(tid: str, scope, at: datetime) -> Dict[str, List[float]]:
    key = f"{tid}|{getattr(scope, 'key', 'all')}|{_paris_today(at)}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    r = ratios(tid, scope, at)
    _cache[key] = (time.monotonic(), r)
    return r


def _groups(tenant: Dict[str, Any]) -> List[str]:
    from services import activities as A
    from features import client_brain as CB
    return [f"a:{A.of(tenant)['key']}", f"s:{CB.sector_key(tenant.get('sector'))}"]


def learn(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The network, each shop one vote, the middle shop's figure. Stored, never a shop id."""
    now = now or NOW()
    per: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    shops = 0
    for t in _db.tenants.find({"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "sector": 1, "activity_key": 1}):
        try:
            r = ratios(t["id"], None, now)
        except Exception as exc:                  # one shop never stops the network
            print(f"holiday_learning: {t.get('id')} skipped ({exc})")
            continue
        if not r:
            continue
        shops += 1
        overall = mean(x for v in r.values() for x in v)
        for g in _groups(t):
            for k, v in r.items():
                per[(g, k)].append(mean(v))
            per[(g, "*")].append(overall)
    by = {f"{g}|{k}": {"ratio": round(median(v), 2), "shops": len(v)}
          for (g, k), v in per.items() if len(v) >= NET_MIN_SHOPS}
    _db.platform_settings.update_one({"key": NET_KEY}, {"$set": {"key": NET_KEY, "at": now, "by": by}}, upsert=True)
    _cache.pop("net", None)
    return {"figures": len(by), "shops": shops}


def learn_due(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    now = now or NOW()
    d = _db.platform_settings.find_one({"key": NET_KEY}, {"_id": 0, "at": 1}) or {}
    at = d.get("at")
    if isinstance(at, datetime):
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        if now - at < LEARN_EVERY:
            return None
    return learn(now)


def _network() -> Dict[str, Any]:
    hit = _cache.get("net")
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    d = (_db.platform_settings.find_one({"key": NET_KEY}, {"_id": 0, "by": 1}) or {}).get("by") or {}
    _cache["net"] = (time.monotonic(), d)
    return d


def _label(tenant: Dict[str, Any]) -> str:
    try:
        from services import activities as A
        lab = A.of(tenant).get("label", "commerces").lower()
        return lab if lab.endswith("s") else f"{lab}s"
    except Exception:
        return "commerces"


def factor(tid: str, tenant: Dict[str, Any], scope, hol: Dict[str, Any], at: datetime) -> Optional[Dict[str, Any]]:
    """{factor, basis} for this holiday at this shop, or None (too little to say)."""
    own = own_ratios(tid, scope, at).get(hol["key"], [])
    net, n_shops = None, 0
    by = _network()
    for g in _groups(tenant):
        x = by.get(f"{g}|{hol['key']}") or by.get(f"{g}|*")
        if x:
            net, n_shops = float(x["ratio"]), int(x["shops"])
            break
    if net is not None:
        f = (sum(own) + NET_WEIGHT * net) / (len(own) + NET_WEIGHT)
    elif len(own) >= OWN_MIN:
        f = mean(own)
    else:
        return None
    f = round(max(CLIP[0], min(CLIP[1], f)), 2)
    passe = "passé" if hol["key"] in MASCULINE else "passée"
    bits = []
    if own:
        bits.append(f"Votre {hol['name']} {passe}" if len(own) == 1 else f"Vos {len(own)} {hol['name']} {passe}s")
    if net is not None:
        bits.append(f"{n_shops} {_label(tenant)} comme vous")
    return {"factor": f, "basis": " · ".join(bits)}
