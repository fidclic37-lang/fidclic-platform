"""
La recommandation qui apprend (user, 2026-10-29/30 — PR-B of « salaah ka
record + seekhti ranking », after the journal of ideas, features/reco_journal).

Each idea keeps the estimate its surface gives it (€ on the Copilote and
Insights, the order on the Tableau de bord, the clients' basket on « a
repéré ») and is multiplied by what was learned, ×0.25 to ×4:

    taken       how often the owner opens it when shown — a Beta posterior,
                the network's rate for that idea as its prior (8 views' worth)
    paid        € per measured send (groupe témoin, 15 days, final results
                only) — the shop's own, pulled toward the network's until it
                has 3 sends of its own
    pushed back « Pas pertinent » and « Plus tard » lower it

« Har cheez se seekhe » (user): ideas with little data get their chance —
Thompson sampling: the rate and the € are DRAWN from what is known, not
read off it; the more data, the narrower the draw. One draw per shop ×
idea × Paris day, so the owner sees one order all day.

THE NETWORK (user: every shop weighs the same — one shop cannot bend it,
audit of #400): each shop's own rate and € per send first, then the middle
shop's (median, user 2026-10-30: one odd shop — a typo at the till or fake
sends — moved the average 93 → 3 215 €, it does not move the median); by activité (Barbier, CBD…), then secteur — never another trade's,
and only from 3 shops (fewer would show one competitor's own figure). Relearned
once a day by the tick; it keeps counts, never a shop id.

Nothing here may break a page: on any failure the surface keeps its own order.
"""
from __future__ import annotations

import math
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median, pstdev
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from features import reco_journal as RJ

_db = None
PRIOR_VIEWS = 8.0          # the network's open rate weighs as many views of one's own
VALUE_K = 3.0              # own € per send outweighs the network's from 3 sends
EUR_SMOOTH = 50.0          # € — keeps a small difference from looking huge
CLIP = (0.25, 4.0)
DEFAULT_OPEN = 0.2         # before the network knows anything: one idea in five is taken
HORIZON = timedelta(days=180)
RESULTS_HORIZON = timedelta(days=365)
LEARN_EVERY = timedelta(hours=24)
CACHE_TTL_S = 600
NET_KEY = "reco_network"
NET_MIN_SHOPS = 3          # fewer: a « network » figure would be one competitor's own


def init(db):
    global _db
    _db = db


def NOW() -> datetime:                      # the clock (tests set it)
    return datetime.now(timezone.utc)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return x if x == x and abs(x) != float("inf") else default


# ---------------------------------------------------------------------------
# the multiplier — pure
# ---------------------------------------------------------------------------
def factor(own: Dict[str, Any], net: Optional[Dict[str, Any]], ref: Dict[str, Any],
           seed: Optional[Tuple[str, str, str]]) -> Tuple[float, Dict[str, Any]]:
    """(multiplier, the parts it was made of). `seed` = (shop, idea, day): a
    draw (Thompson); None: the expected value (no exploration)."""
    rng = random.Random(":".join(map(str, seed))) if seed else None
    opened = max(0.0, _f(own.get("opened")))
    shown = max(opened, _f(own.get("shown")))          # taken is at least seen
    dismissed = max(0.0, _f(own.get("dismissed")))
    later = max(0.0, _f(own.get("later")))
    results = [_f(r, None) for r in own.get("results") or []]
    results = [r for r in results if r is not None]
    net = net if isinstance(net, dict) else None
    ref_open = _f(ref.get("open"), 0.0) if isinstance(ref, dict) else 0.0
    ref_open = ref_open if 0.0 < ref_open <= 1.0 else DEFAULT_OPEN
    ref_eur = _f(ref.get("eur"), 0.0) if isinstance(ref, dict) else 0.0
    net_open = _f(net.get("open"), -1.0) if net else -1.0
    net_eur = _f(net.get("eur"), None) if net and net.get("eur") is not None else None
    parts: Dict[str, Any] = {"shown": int(shown), "opened": int(opened), "dismissed": int(dismissed),
                             "later": int(later), "sends": len(results)}

    # taken: Beta(opened + prior, not opened + prior)
    act = 1.0
    p0 = net_open if 0.0 <= net_open <= 1.0 else ref_open
    if shown > 0 or net:
        a = opened + PRIOR_VIEWS * max(p0, 0.01)
        b = (shown - opened) + PRIOR_VIEWS * max(1.0 - p0, 0.01)
        p = rng.betavariate(a, b) if rng else a / (a + b)
        act = p / ref_open
        parts["open_rate"] = round(a / (a + b), 3)

    # paid: own € per send, pulled toward the network's
    val = 1.0
    n = len(results)
    own_mean = mean(results) if results else None
    if own_mean is not None or net_eur is not None:
        if own_mean is not None and net_eur is not None:
            ev = (n * own_mean + VALUE_K * net_eur) / (n + VALUE_K)
        elif own_mean is not None:
            ev = (n * own_mean + VALUE_K * ref_eur) / (n + VALUE_K)
        else:
            ev = net_eur
        if rng:
            # how far one send is from another (its spread), over what is known
            spread = pstdev(results) if n >= 2 else abs(ev)
            sd = max(EUR_SMOOTH, spread) / math.sqrt(n + 1 + (VALUE_K if net_eur is not None else 0))
            ev = rng.gauss(ev, sd)
        val = (max(ev, -EUR_SMOOTH) + 2 * EUR_SMOOTH) / (max(ref_eur, 0.0) + 2 * EUR_SMOOTH)
        parts["eur"] = round(own_mean, 2) if own_mean is not None else None
        parts["net_eur"] = round(net_eur, 2) if net_eur is not None else None

    pen = 1.0 - min(0.5, (dismissed + 0.3 * later) / (shown + 5.0))
    m = act * val * pen
    m = min(CLIP[1], max(CLIP[0], m if m == m else 1.0))
    parts["m"] = round(m, 3)
    return round(m, 6), parts


# ---------------------------------------------------------------------------
# what is known: the shop's own, and the network's
# ---------------------------------------------------------------------------
def _since(now: datetime, span: timedelta) -> str:
    return RJ.day_of(now - span)


def _counts(match: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, float]]:
    """(shop, idea) → DAYS by kind: seen twice in a day (two surfaces, two
    stores, two visits) is one day."""
    out: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for g in _db.reco_events.aggregate([{"$match": match},
                                        {"$group": {"_id": {"t": "$tenant_id", "k": "$key", "kind": "$kind", "d": "$day"}}},
                                        {"$group": {"_id": {"t": "$_id.t", "k": "$_id.k", "kind": "$_id.kind"},
                                                    "rows": {"$sum": 1}}}]):
        i = g.get("_id") or {}
        k = RJ.clean(i.get("k"))
        if isinstance(i.get("t"), str) and k and i.get("kind") in ("shown", "opened", "accepted", "dismissed", "later"):
            kind = "opened" if i["kind"] == "accepted" else i["kind"]
            out[(i["t"], k)][kind] += _f(g.get("rows"))
    return out


def _results(match: Dict[str, Any]) -> Dict[Tuple[str, str], List[float]]:
    """(shop, idea) → € of each finished, measured send (enough témoin)."""
    out: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for c in _db.campaigns.find({**match, "reco_result.measured": True},
                                {"_id": 0, "tenant_id": 1, "reco_key": 1, "template": 1, "reco_result": 1}):
        r = c.get("reco_result") or {}
        k = RJ.reco_of(c)
        e = _f(r.get("extra_revenue"), None) if r.get("extra_revenue") is not None else None
        if k and isinstance(c.get("tenant_id"), str) and r.get("enough") is True and not r.get("pending") and e is not None:
            out[(c["tenant_id"], k)].append(e)
    return out


_cache: Dict[str, Tuple[float, Any]] = {}


def forget(tid: Optional[str]) -> None:
    """The owner just answered an idea: the next page reads it at once."""
    _cache.pop(f"own:{tid}", None)


def own_stats(tid: str, now: datetime) -> Dict[str, Dict[str, Any]]:
    hit = _cache.get(f"own:{tid}")
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    counts = _counts({"tenant_id": tid, "day": {"$gte": _since(now, HORIZON)}})
    res = _results({"tenant_id": tid})
    out: Dict[str, Dict[str, Any]] = {}
    for (t, k), c in counts.items():
        out[k] = {"shown": c.get("shown", 0), "opened": c.get("opened", 0), "dismissed": c.get("dismissed", 0),
                  "later": c.get("later", 0), "results": []}
    for (t, k), r in res.items():
        out.setdefault(k, {"shown": 0, "opened": 0, "dismissed": 0, "later": 0, "results": []})["results"] = r
    _cache[f"own:{tid}"] = (time.monotonic(), out)
    return out


def _groups(tenant: Dict[str, Any]) -> List[str]:
    from services import activities as A
    from features import client_brain as CB
    act = A.of(tenant)["key"]
    sector = CB.sector_key(tenant.get("sector"))
    return [f"a:{act}", f"s:{sector}"]           # never another trade's figures


def learn(now: Optional[datetime] = None) -> Dict[str, Any]:
    """The network, every shop weighing the same — the middle shop's figure,
    so one odd shop cannot pull it. Stored, never a shop id."""
    now = now or NOW()
    counts = _counts({"day": {"$gte": _since(now, HORIZON)}})
    res = _results({})
    shops = {t for t, _k in counts} | {t for t, _k in res}
    tenants = {t["id"]: t for t in _db.tenants.find({"id": {"$in": list(shops)}},
                                                     {"_id": 0, "id": 1, "sector": 1, "activity_key": 1})}
    # per group × idea: each shop's own rate / € per send
    rates: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    euros: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    all_rates: List[float] = []
    all_eur: List[float] = []
    for (t, k), c in counts.items():
        if c.get("shown", 0) > 0 and t in tenants:
            r = min(1.0, c.get("opened", 0) / c["shown"])
            for g in _groups(tenants[t]):
                rates[(g, k)].append(r)
            all_rates.append(r)
    for (t, k), r in res.items():
        if r and t in tenants:
            e = mean(r)
            for g in _groups(tenants[t]):
                euros[(g, k)].append(e)
            all_eur.append(e)
    by: Dict[str, Dict[str, Any]] = {}
    for gk in set(rates) | set(euros):
        g, k = gk
        rr, ee = rates.get(gk, []), euros.get(gk, [])
        rr = rr if len(rr) >= NET_MIN_SHOPS else []
        ee = ee if len(ee) >= NET_MIN_SHOPS else []
        if not rr and not ee:
            continue
        by[f"{g}|{k}"] = {"open": round(median(rr), 6) if rr else None, "eur": round(median(ee), 2) if ee else None,
                          "shops": max(len(rr), len(ee)), "shops_open": len(rr), "shops_eur": len(ee)}
    doc = {"key": NET_KEY, "at": now, "by": by,
           "ref": {"open": round(median(all_rates), 6) if all_rates else None,
                   "eur": round(median(all_eur), 2) if all_eur else None, "shops": len(shops)}}
    _db.platform_settings.update_one({"key": NET_KEY}, {"$set": doc}, upsert=True)
    _cache.pop("net", None)
    return {"ideas": len(by), "shops": len(shops)}


def learn_due(now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The tick's call: relearn once a day."""
    now = now or NOW()
    d = _db.platform_settings.find_one({"key": NET_KEY}, {"_id": 0, "at": 1}) or {}
    at = RJ._aware(d.get("at"))
    if at and now - at < LEARN_EVERY:
        return None
    return learn(now)


def _network_doc() -> Dict[str, Any]:
    hit = _cache.get("net")
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    d = _db.platform_settings.find_one({"key": NET_KEY}, {"_id": 0}) or {}
    _cache["net"] = (time.monotonic(), d)
    return d


def network_for(tenant: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The closest group that knows this idea: activité, then secteur."""
    by = _network_doc().get("by") or {}
    for g in _groups(tenant or {}):
        n = by.get(f"{g}|{key}")
        if n and (n.get("open") is not None or n.get("eur") is not None):
            return n
    return None


# ---------------------------------------------------------------------------
# « Pourquoi en premier ? »
# ---------------------------------------------------------------------------
def _eur(x: float) -> str:
    return f"{'+' if x > 0 else ''}{round(x):,} €".replace(",", " ")


def why(parts: Dict[str, Any], label: str) -> str:
    bits: List[str] = []
    if parts.get("eur") is not None:
        n = parts.get("sends") or 0
        bits.append(f"Chez vous : {_eur(parts['eur'])} par envoi en moyenne ({n} envoi{'s' if n > 1 else ''} mesuré{'s' if n > 1 else ''})")
    elif parts.get("net_eur") is not None:
        bits.append(f"Chez les {label} comme vous : {_eur(parts['net_eur'])} par envoi en général")
    if parts.get("shown", 0) >= 3 and parts.get("opened"):
        bits.append(f"Vous l'ouvrez {parts['opened']} fois sur {parts['shown']}")
    if parts.get("dismissed"):
        bits.append(f"écartée {parts['dismissed']} fois")
    if parts.get("shown", 0) < 3 and not parts.get("sends"):
        bits.append("Idée encore peu essayée chez vous : FidClic IA lui laisse sa chance")
    text = " · ".join(bits) if bits else "Classée selon l'estimation faite sur vos clients"
    return text[0].upper() + text[1:] + "."


# ---------------------------------------------------------------------------
# applying it
# ---------------------------------------------------------------------------
def rank(tid: Optional[str], items: List[Dict[str, Any]], base: Callable[[Dict[str, Any], int], float],
         now: Optional[datetime] = None, by: Optional[str] = None) -> List[Dict[str, Any]]:
    """The items, best first by base × learned × what the owner (and `by`,
    the account looking) told FidClic IA, each with `why_rank`. An advice for
    a day the shop is closed is left out. On any failure: the items as they
    came, untouched."""
    if not tid or not items:
        return items
    try:
        from features import copilot_memory as CM
        try:                                       # « Ce que FidClic IA retient » (2026-10-30)
            cons = CM.constraints(tid, by)
        except Exception as exc:
            print(f"reco_ranking: memory unavailable ({exc})")
            cons = {"closed": set(), "targets": set(), "avoid": set(), "said": {}}
        now = now or NOW()
        tenant = _db.tenants.find_one({"id": tid}, {"_id": 0, "sector": 1, "activity_key": 1}) or {}
        own = own_stats(tid, now)
        ref = _network_doc().get("ref") or {}
        day = RJ.day_of(now)
        try:
            from services import activities as A
            label = A.of(tenant).get("label", "commerces").lower()
            label = label if label.endswith("s") else f"{label}s"
        except Exception:
            label = "commerces"
        scored = []
        for i, item in enumerate(items):
            k = RJ.key_of(item)
            b = _f(base(item, i), 0.0)
            said_m, said = CM.item_effect(item, {k, item.get("key")}, cons)
            if said_m is None:                     # a closed day's advice
                continue
            if said:
                b = b * said_m if b > 0 else b
            if not k:
                scored.append((b, i, item, {"said": said} if said else None))
                continue
            m, parts = factor(own.get(k) or {}, network_for(tenant, k), ref, (tid, k, day))
            if said:
                parts = {**parts, "said": said}
            scored.append((b * m if b > 0 else b, i, item, parts))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for score, _i, item, parts in scored:
            item = dict(item)
            said = (parts or {}).get("said")
            text = why({k: v for k, v in (parts or {}).items() if k != "said"}, label)
            item["why_rank"] = {"text": f"{said}. {text}" if said else text, "m": (parts or {}).get("m", 1.0),
                                **({"selon": said} if said else {})}
            if "score" in item:                  # a surface that sorts again (Insights' shelves) keeps this order
                item["score"] = score
            out.append(item)
        return out
    except Exception as exc:
        print(f"reco_ranking: kept the surface's own order ({exc})")
        return items
