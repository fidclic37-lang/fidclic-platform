"""Géolocalisation automation — what the user's mockups added (2026-10-11).

How a passer-by hears from the shop:
  • Apple Wallet and Google Wallet raise the card on the lock screen by
    themselves when the client comes near one of the pass's locations — no
    app open, no server call. Apple shows OUR text (relevantText); Google
    shows its own (« Nearby passes »). The phone decides the distance
    (about 100 m) and how often. So the server decides, client by client,
    WHETHER their pass carries the locations right now: targeting, days,
    hours, period, public holidays, weather and the per-client gap all
    switch the locations on and off (sync_passes — the daily cron, and the
    15-minute tick once Vercel Pro is on).
  • The client's own card page, when opened near a shop, asks the server
    (server.proximity_ping): that message follows every rule, with its
    button, and the detection is kept (rounded) for the owner's map.

Nothing here invents numbers: the owner sees clients actually detected,
clients actually reachable, and what was actually sent.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from features import store_cards as _SC  # one card per establishment (multi-store)

_db = None

WEATHER = {"sun": "Ensoleillé", "clouds": "Nuageux", "rain": "Pluie", "cold": "Froid", "hot": "Chaud"}
COLD_BELOW = 10.0           # °C — « Froid »
HOT_FROM = 25.0             # °C — « Chaud »
WEATHER_TTL = timedelta(minutes=20)
DETECTION_DAYS = 30         # the owner's map keeps a month, then forgets
RADII_M = (50, 100, 200, 500)
MAX_SPOTS = 10              # Apple and Google take ten locations per pass


def init(db) -> None:
    global _db
    _db = db
    try:
        _db.geo_detections.create_index([("tenant_id", 1), ("at", -1)])
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return None


# ---------------------------------------------------------------------------
# the weather (Open-Meteo: free, no key)
# ---------------------------------------------------------------------------
def _open_meteo(lat: float, lng: float) -> Optional[Dict[str, Any]]:
    import urllib.request
    url = ("https://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
           "&current=temperature_2m,weather_code&timezone=Europe%%2FParis" % (lat, lng))
    with urllib.request.urlopen(url, timeout=4) as r:          # noqa: S310 — fixed https host
        cur = (json.loads(r.read().decode("utf-8")) or {}).get("current") or {}
    if cur.get("weather_code") is None or cur.get("temperature_2m") is None:
        return None
    return {"code": int(cur["weather_code"]), "temp": float(cur["temperature_2m"])}


fetch_weather: Callable[[float, float], Optional[Dict[str, Any]]] = _open_meteo   # tests swap it


def classify(code: int, temp: float) -> List[str]:
    """WMO weather code + temperature → the owner's conditions."""
    tags = []
    if code in (0, 1):
        tags.append("sun")
    elif code in (2, 3, 45, 48):
        tags.append("clouds")
    else:                                   # drizzle, rain, snow, showers, storms
        tags.append("rain")
    if temp < COLD_BELOW:
        tags.append("cold")
    if temp >= HOT_FROM:
        tags.append("hot")
    return tags


def weather_now(tid: str, lat: Optional[float], lng: Optional[float],
                at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The shop's weather now, kept 20 minutes. None when unknown."""
    at = at or _now()
    if lat is None or lng is None:
        return None
    row = _db.geo_weather.find_one({"_id": tid}) or {}
    seen = _aware(row.get("at"))
    if seen and at - seen < WEATHER_TTL and row.get("code") is not None:
        return {"code": row["code"], "temp": row["temp"], "tags": classify(row["code"], row["temp"]), "at": seen}
    try:
        got = fetch_weather(float(lat), float(lng))
    except Exception as exc:
        print(f"geo: weather unavailable ({exc})")
        got = None
    if not got:
        return None
    _db.geo_weather.update_one({"_id": tid}, {"$set": {"code": got["code"], "temp": got["temp"], "at": at}},
                               upsert=True)
    return {**got, "tags": classify(got["code"], got["temp"]), "at": at}


def weather_ok(tid: str, trigger: Dict[str, Any], spot: Optional[Dict[str, Any]], at: datetime) -> bool:
    """« Météo » ticked: one of them must be true now. Unknown weather with a
    condition asked = not sent (the owner asked for that weather)."""
    wanted = [w for w in (trigger.get("weather") or []) if w in WEATHER]
    if not wanted:
        return True
    w = weather_now(tid, (spot or {}).get("lat"), (spot or {}).get("lng"), at)
    return bool(w and set(wanted) & set(w["tags"]))


# ---------------------------------------------------------------------------
# public holidays (France)
# ---------------------------------------------------------------------------
def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def holidays(year: int) -> set:
    e = _easter(year)
    fixed = [(1, 1), (5, 1), (5, 8), (7, 14), (8, 15), (11, 1), (11, 11), (12, 25)]
    return {date(year, m, d) for m, d in fixed} | {e + timedelta(days=1), e + timedelta(days=39),
                                                   e + timedelta(days=50)}


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)


# ---------------------------------------------------------------------------
# where: the shop's establishments
# ---------------------------------------------------------------------------
def anchors(tid: str) -> List[Dict[str, Any]]:
    """Every open establishment with a position — the same ids as
    team_access.stores, so an automation's « établissements » match."""
    from features import team_access as T
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    out = []
    branches = [b for b in t.get("branches") or [] if b.get("id") and b.get("status") != "closed"]
    for b in branches:
        lat, lng = b.get("latitude"), b.get("longitude")
        if lat is None or lng is None:
            try:
                import server as core
                lat, lng = core.get_postal_coords(b.get("postal_code") or "")
            except Exception:
                lat, lng = None, None
        out.append({"id": b["id"], "name": b.get("name") or "Établissement",
                    "address": ", ".join(x for x in (b.get("address"), b.get("postal_code"), b.get("city")) if x),
                    "lat": float(lat) if lat is not None else None, "lng": float(lng) if lng is not None else None})
    if not branches:
        from features import geolocation as G
        lat, lng, _ = G._shop_position(t)
        out.append({"id": T.MAIN, "name": t.get("name") or "Mon établissement",
                    "address": t.get("address") or ", ".join(x for x in (t.get("postal_code"), t.get("city")) if x),
                    "lat": lat, "lng": lng})
    return out


def zone(tid: str, row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The establishments this automation watches (none ticked = all), with a position."""
    want = set((row.get("trigger") or {}).get("stores") or [])
    return [a for a in anchors(tid) if a["lat"] is not None and (not want or a["id"] in want)][:MAX_SPOTS]


def radius_of(tenant: Dict[str, Any]) -> int:
    """One radius for the shop (Paramètres › Établissement)."""
    try:
        return max(50, min(2000, int(tenant.get("geo_radius_meters") or 200)))
    except (TypeError, ValueError):
        return 200


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + \
        math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def live(tid: str) -> Dict[str, bool]:
    """What lets a geolocation message leave at all."""
    t = _db.tenants.find_one({"id": tid}, {"_id": 0}) or {}
    plan = True
    try:
        import server as core
        plan = bool(core.features_for(t).get("geo_proximity"))
    except Exception:
        pass
    try:
        from features.privacy_page import geo_allowed, marketing_allowed
        privacy, marketing = geo_allowed(tid), marketing_allowed(tid)
    except Exception:
        privacy, marketing = True, True
    return {"enabled": bool(t.get("geo_enabled")), "plan": plan, "privacy": privacy, "marketing": marketing,
            "ok": bool(t.get("geo_enabled")) and plan and privacy and marketing}


# ---------------------------------------------------------------------------
# the owner's map: clients detected near a shop (card opened), rounded
# ---------------------------------------------------------------------------
def _round(lat: float, lng: float) -> Tuple[float, float]:
    """About 50 m: never the client's exact spot."""
    step_lat = 0.00045
    step_lng = 0.00045 / max(0.2, math.cos(math.radians(lat)))
    return round(round(lat / step_lat) * step_lat, 5), round(round(lng / step_lng) * step_lng, 5)


def record(tid: str, cust: Dict[str, Any], anchor: Dict[str, Any], lat: float, lng: float,
           dist: float, at: Optional[datetime] = None) -> bool:
    """A card opened inside the zone. Kept only for a client who accepted
    the shop's terms at signup (position included) and a shop whose
    geolocation is allowed (Données & confidentialité)."""
    if not (cust.get("consent") or {}).get("accepted"):
        return False
    rl, rg = _round(lat, lng)
    _db.geo_detections.insert_one({"tenant_id": tid, "customer_id": cust["id"], "store_id": anchor.get("id"),
                                   "lat": rl, "lng": rg, "distance_m": int(dist), "at": at or _now()})
    return True


def purge(at: Optional[datetime] = None) -> int:
    at = at or _now()
    return _db.geo_detections.delete_many({"at": {"$lt": at - timedelta(days=DETECTION_DAYS)}}).deleted_count


def detections(tid: str, at: Optional[datetime] = None, days: int = 7) -> Dict[str, Any]:
    """Points (rounded) with how many detections, and the counts the panel shows."""
    at = at or _now()
    rows = list(_db.geo_detections.find({"tenant_id": tid, "at": {"$gte": at - timedelta(days=days)}},
                                        {"_id": 0, "lat": 1, "lng": 1, "customer_id": 1, "at": 1}))
    from features import period as P
    today = P.local(at).date()
    pts: Dict[Tuple[float, float], Dict[str, Any]] = {}
    for r in rows:
        k = (r["lat"], r["lng"])
        p = pts.setdefault(k, {"lat": r["lat"], "lng": r["lng"], "count": 0, "clients": set()})
        p["count"] += 1
        p["clients"].add(r["customer_id"])
    points = [{"lat": p["lat"], "lng": p["lng"], "count": p["count"], "clients": len(p["clients"])}
              for p in pts.values()]
    return {"points": points, "days": days,
            "clients_week": len({r["customer_id"] for r in rows}),
            "clients_today": len({r["customer_id"] for r in rows if P.local(_aware(r["at"])).date() == today})}


# ---------------------------------------------------------------------------
# the Wallet pass: locations on or off, client by client
# ---------------------------------------------------------------------------
@_SC.customer_store("cust")
def for_pass(cust: Dict[str, Any], at: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The geolocation message this client's pass carries now, or None.
    The first active automation (list order) whose every rule holds."""
    from features import automations as AU
    at = at or _now()
    tid = cust.get("tenant_id")
    if not tid or cust.get("deleted_at") or not live(tid)["ok"] or not AU._plan_ok(tid):
        return None
    try:
        from features import automations as _AU
        _AU.split_per_store(tid)                   # one establishment each (multi-store PR5)
    except Exception:
        pass
    rows = list(_db.automations.find({"tenant_id": tid, "scenario": "geo", "status": "active"},
                                     {"_id": 0}).sort("order", 1))
    from features import custom_rules as CR
    rows += CR.geo_rows(tid)                  # Nouvelle automatisation › Géolocalisation (its own address)
    tenant = None
    cache: Dict[str, Any] = {}
    for row in rows:
        if row.get("scenario") == "custom":
            try:
                got = CR.pass_geo(row, cust, at, cache)
                if got:
                    return got
            except Exception as exc:
                print(f"geo: custom pass rule {row.get('id')} failed ({exc})")
            continue
        try:
            if not AU.running(row, at) or not AU.in_window(row.get("schedule") or {}, at):
                continue
            if not AU.matches(tid, row, cust, at, cache):
                continue
            tr = row.get("trigger") or {}
            last = _db.automation_log.find_one({"tenant_id": tid, "automation_id": row["id"],
                                                "customer_id": cust["id"]}, sort=[("sent_at", -1)])
            if last and at - _aware(last["sent_at"]) < timedelta(days=max(1, int(tr.get("cooldown_days") or 7))):
                continue                     # told on the card lately: the pass stays quiet too
            spots = zone(tid, row)
            if not spots or not weather_ok(tid, tr, spots[0], at):
                continue
            tenant = tenant or (_db.tenants.find_one({"id": tid}) or {})
            tpl = _db.card_templates.find_one({"tenant_id": tid}, {"_id": 0}) or {}
            msg = row.get("message") or {}
            extra = AU._extra("geo", cust, {"store": spots[0]["name"]}, tpl)
            title = AU._render(msg.get("title") or "", cust, tenant, extra).strip()
            body = AU._render(msg.get("body") or "", cust, tenant, extra).strip()
            text = f"{title} — {body}" if title and body else (title or body)
            target = AU._target_url(tid, row, cust)      # the button, straight (no click count off-line)
            btn = (msg.get("button") or {})
            return {"automation_id": row["id"], "title": title, "body": body, "text": text[:150],
                    "button_label": (btn.get("label") or "")[:30] if target else None, "button_url": target,
                    "spots": [(s["lat"], s["lng"]) for s in spots], "radius": radius_of(tenant)}
        except Exception as exc:
            print(f"geo: pass rule {row.get('id')} failed ({exc})")
    return None


def governs(tid: str) -> bool:
    """An active geolocation automation decides the pass's locations; without
    one the card designer's own « rappel de proximité » stays as it was."""
    return bool(_db.automations.find_one({"tenant_id": tid, "scenario": "geo", "status": "active"}, {"_id": 1})) or \
        bool(_db.automations.find_one({"tenant_id": tid, "scenario": "custom", "status": "active",
                                       "trigger.type": "geo", "trigger.lat": {"$ne": None}}, {"_id": 1}))


def _key(state: Optional[Dict[str, Any]]) -> str:
    if not state:
        return "off"
    raw = json.dumps([state["automation_id"], state["text"], state["spots"], state["radius"]], default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def wallet_serials(tid: str) -> List[str]:
    s = set(_db.pass_registrations.distinct("serial", {"tenant_id": tid}))
    s |= set(_db.google_wallet_objects.distinct("serial", {"tenant_id": tid}))
    return [x for x in s if x]


def sync_passes(at: Optional[datetime] = None, tids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Wake every pass whose locations must change now (a window opened or
    closed, the weather turned, a client left the targeting…). A pass that
    stays the same is not touched."""
    at = at or _now()
    if tids is None:
        tids = set(_db.automations.distinct("tenant_id", {"scenario": "geo"}))
        tids |= set(_db.automations.distinct("tenant_id", {"scenario": "custom", "trigger.type": "geo"}))
        _recheck_once(tids)
        tids |= set(_db.customers.distinct("tenant_id", {"geo_pass_key": {"$nin": [None, "off"]}}))
    out = {"tenants": 0, "checked": 0, "changed": 0}
    for tid in tids:
        serials = wallet_serials(tid)
        if not serials:
            continue
        out["tenants"] += 1
        changed = []
        for c in _db.customers.find({"tenant_id": tid, "barcode_id": {"$in": serials}}, {"_id": 0}):
            out["checked"] += 1
            k = _key(for_pass(c, at))
            if (c.get("geo_pass_key") or "off") != k:
                _db.customers.update_one({"id": c["id"]}, {"$set": {"geo_pass_key": k}})
                changed.append(c["barcode_id"])
        if changed:
            out["changed"] += len(changed)
            try:
                from features.wallet_passes import notify_passes
                notify_passes(changed)
            except Exception as exc:
                print(f"geo: passes not woken ({exc})")
    return out


RECHECK_MARKER = "geo_pass_recheck"
RECHECK_VERSION = "2026-10-17"


def _recheck_once(tids: Iterable[str]) -> None:
    """Passes downloaded while a Géolocalisation was on kept the shop's
    locations after it was turned off: their state was never remembered
    (wallet_passes._note_geo now does). Once — approved by the owner,
    2026-10-17 — every client of a shop that has or had one is marked
    unknown, so the sync below wakes the passes that must lose them: a
    silent update, no message on the phone."""
    if _db.platform_settings.find_one({"key": RECHECK_MARKER, "value": RECHECK_VERSION}, {"_id": 1}):
        return
    tids = [t for t in tids if t]
    if tids:
        _db.customers.update_many({"tenant_id": {"$in": tids}}, {"$set": {"geo_pass_key": "unknown"}})
    _db.platform_settings.update_one({"key": RECHECK_MARKER}, {"$set": {
        "key": RECHECK_MARKER, "value": RECHECK_VERSION, "at": _now()}}, upsert=True)


def refresh_one(cust: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    """One client's pass, now (after a card-open message: the gap starts)."""
    k = _key(for_pass(cust, at))
    if (cust.get("geo_pass_key") or "off") == k:
        return False
    _db.customers.update_one({"id": cust["id"]}, {"$set": {"geo_pass_key": k}})
    if cust.get("barcode_id"):
        try:
            from features.wallet_passes import notify_passes
            notify_passes([cust["barcode_id"]])
        except Exception as exc:
            print(f"geo: pass not woken ({exc})")
    return True


# ---------------------------------------------------------------------------
# what really happened
# ---------------------------------------------------------------------------
def results(tid: str, aid: str) -> Dict[str, Any]:
    """Sent (card opened near a shop), clicks, and visits within 24 h of a message."""
    logs = list(_db.automation_log.find({"tenant_id": tid, "automation_id": aid, "status": {"$ne": "deferred"}},
                                        {"_id": 0, "customer_id": 1, "sent_at": 1, "clicked_at": 1}))
    visits = 0
    for r in logs:
        t0 = _aware(r["sent_at"])
        if t0 and _db.visits.find_one({"tenant_id": tid, "customer_id": r["customer_id"],
                                       "visit_time": {"$gte": t0, "$lte": t0 + timedelta(hours=24)}}, {"_id": 1}):
            visits += 1
    return {"sent": len(logs), "clicks": sum(1 for r in logs if r.get("clicked_at")), "visits_24h": visits}
