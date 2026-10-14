"""
Géolocalisation clients — where your clients come from, and how far out you reach.

Status: 🟢 Core.
Mounts at:
    GET /api/owner/geo/catchment  → zones, time bands, communes, the map points
    GET /api/owner/geo/export     → the same breakdown as CSV

TWO DIFFERENT QUESTIONS, TWO DIFFERENT SLICES
    "Zone de chalandise" answers *d'où viennent vos clients* — the clients you
    already have, grouped into distance rings around the shop.
    "Isochrones" answers *qui peut venir en 5, 15, 25, 35 minutes* — the same
    clients, grouped by how long the trip takes by car, bike or on foot.

    They are two readings of one client base, so the combined view's overlap is
    computed for real (a client counted in ring 2 and in the 15-minute band is
    in both), never assumed.

HOW HONEST ARE THE NUMBERS
    Two approximations, both surfaced to the merchant rather than hidden:

    1. POSITION. A client is placed at their captured GPS point when the card
       has one, otherwise at the centre of their postal code (with a stable
       per-client jitter so a hundred clients in one postal code do not stack
       into a single dot). `precision` in the response says how many clients
       fall in each case, and the page prints it under the map.

    2. TRAVEL TIME. A real isochrone is a road-network computation and needs a
       routing provider, which this deployment does not have. The bands here
       are straight-line distance at the mode's average urban speed — good
       enough to target a campaign, and labelled "estimation" everywhere it
       shows, so nobody reads it as a routed travel time.

    Everything else — who is in which ring, which communes they live in, how
    many of them there are — is counted from real rows.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from auth import require_role, TokenData
from features import store_scope as S

# Read by the owner, administrateurs and managers — each on the establishments
# it may see. (Not to be confused with `scope` below: local / régional.)
READERS = ["business_owner", "administrateur", "manager"]

router = APIRouter(tags=["geolocation"])
_db = None

EARTH_R_KM = 6371.0
MAX_MAP_POINTS = 1500       # more than this and the map is a blob, not a map

# Distance rings, in km from the shop. Three zones, as in the approved design.
ZONES: List[Dict[str, Any]] = [
    {"key": "z1", "label": "Zone 1", "from_km": 0.0,  "to_km": 5.0,  "tone": "rose"},
    {"key": "z2", "label": "Zone 2", "from_km": 5.0,  "to_km": 15.0, "tone": "amber"},
    {"key": "z3", "label": "Zone 3", "from_km": 15.0, "to_km": 30.0, "tone": "blue"},
]

# Travel-time bands, in minutes. Cumulative in meaning ("à moins de N min"),
# exclusive in counting, so a client lands in exactly one band.
BANDS_MIN = [5, 15, 25, 35]
BAND_TONES = {5: "rose", 15: "amber", 25: "blue", 35: "violet"}

# Average urban speeds, km/h. Door-to-door including stops and lights — not the
# speed limit. These are what turn a minute into a kilometre.
MODES: Dict[str, Dict[str, Any]] = {
    "car":  {"label": "Voiture", "speed_kmh": 30.0},
    "bike": {"label": "Vélo",    "speed_kmh": 15.0},
    "walk": {"label": "Marche",  "speed_kmh": 4.5},
}

SCOPES = {
    # « local » is named after the shop's own town (QA UX07: every shop read
    # « Tours et alentours »)
    "local":  {"label": "Autour de votre commerce", "max_km": 35.0},
    "region": {"label": "Toute la région",    "max_km": 120.0},
    "france": {"label": "Toute la France",    "max_km": None},
}

# Beyond the last ring / band, for the wider scopes (QA F11: « Toute la
# France » still dropped every client further than 30 km).
FAR_ZONE = {"key": "far", "label": "Au-delà", "from_km": 30.0, "to_km": None, "tone": "slate", "far": True}
FAR_BAND = "far"

# Positions looked up per request at most (BAN, cached for good once found):
# the rest use their department until the next load.
POSTAL_FETCH_MAX = 12

# « Clients » shown: those who came or joined in the period (default), or all.
POPULATIONS = {"periode": "Clients de la période", "tous": "Tous les clients"}


def init(db):
    global _db
    _db = db
    try:
        _db.visits.create_index([("tenant_id", 1), ("visit_time", -1)])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def _jitter(customer_id: str) -> Tuple[float, float]:
    """A stable offset of up to ~±1.2 km, derived from the client's id. Without
    it every client in one postal code lands on the exact same pixel; with it
    the same client sits in the same place on every reload."""
    h = int(hashlib.md5((customer_id or "").encode()).hexdigest(), 16)
    return (((h % 200) - 100) / 8000.0, (((h // 200) % 200) - 100) / 8000.0)


# ---------------------------------------------------------------------------
# positions
# ---------------------------------------------------------------------------
def _shop_position(tenant: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], str]:
    """The shop's point, and how we know it. Three sources, best first."""
    for lat_key, lng_key in (("lat", "lng"), ("latitude", "longitude")):
        lat, lng = tenant.get(lat_key), tenant.get(lng_key)
        if lat is not None and lng is not None:
            return float(lat), float(lng), "gps"
    postal = _postal_from(tenant)
    if postal:
        pos = _postal_position(postal, tenant.get("city"))
        if pos:
            return pos[0], pos[1], "postal"
        from server import get_postal_coords
        lat, lng = get_postal_coords(postal)
        return lat, lng, "postal"
    # A multi-branch merchant may carry the address on the branch rather than on
    # the tenant — the proximity endpoint resolves it the same way.
    for branch in tenant.get("branches") or []:
        blat, blng = branch.get("latitude"), branch.get("longitude")
        if blat is not None and blng is not None:
            return float(blat), float(blng), "gps"
        bpostal = _postal_from(branch)
        if bpostal:
            from server import get_postal_coords
            lat, lng = get_postal_coords(bpostal)
            return lat, lng, "postal"
    return None, None, "unknown"


def _postal_from(tenant: Dict[str, Any]) -> str:
    """A French postal code is five digits; pull the first one out of whatever
    the merchant typed as their address."""
    for field in ("postal_code", "code_postal", "address", "adresse"):
        value = str(tenant.get(field) or "")
        for token in value.replace(",", " ").split():
            digits = "".join(c for c in token if c.isdigit())
            if len(digits) == 5:
                return digits
    return ""


def _postal_position(postal: str, city: Any = "", fetch: bool = True) -> Optional[Tuple[float, float]]:
    """The centre of the postal code (BAN, cached), or None."""
    from server import POSTAL_CODE_OVERRIDES
    if postal in POSTAL_CODE_OVERRIDES:
        return POSTAL_CODE_OVERRIDES[postal]
    try:
        from services import communes
        return communes.position_for(postal, city, fetch=fetch)
    except Exception:
        return None


def _resolve_postals(clients: List[Dict[str, Any]]) -> Dict[str, Optional[Tuple[float, float]]]:
    """Every postal code of the clients without GPS → its centre (QA F11: a
    code unknown to the small built-in table fell back to its DEPARTMENT's
    centre — a client of La Colle-sur-Loup landed 28 km off in the hills and
    left the map). Known ones come from the cache; a few unknown ones are
    looked up now, in parallel; the rest use the department until next time."""
    codes = sorted({str(c.get("postal_code") or "").strip() for c in clients
                    if c.get("latitude") is None and str(c.get("postal_code") or "").strip()})
    out = {c: _postal_position(c, fetch=False) for c in codes}
    missing = [c for c in codes if out[c] is None][:POSTAL_FETCH_MAX]
    if missing:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=6) as pool:
                for code, pos in zip(missing, pool.map(lambda c: _postal_position(c, fetch=True), missing)):
                    out[code] = pos
        except Exception:
            pass
    return out


def _client_position(cust: Dict[str, Any], known: Optional[Dict[str, Any]] = None) -> Tuple[Optional[float], Optional[float], str]:
    lat, lng = cust.get("latitude"), cust.get("longitude")
    if lat is not None and lng is not None:
        return float(lat), float(lng), "gps"
    postal = str(cust.get("postal_code") or "").strip()
    if postal:
        dlat, dlng = _jitter(cust.get("id", ""))
        pos = (known or {}).get(postal) if known is not None else _postal_position(postal, fetch=False)
        if pos:
            return pos[0] + dlat, pos[1] + dlng, "postal"
        # not found yet: the department's centre, far coarser — and said so
        from server import get_postal_coords
        base_lat, base_lng = get_postal_coords(postal)
        return base_lat + dlat, base_lng + dlng, "department"
    return None, None, "unknown"


def _commune(cust: Dict[str, Any]) -> Tuple[str, str]:
    """(label, postal code) for where a client lives.

    The postal code leads, because it is finer than the town: 37000, 37100 and
    37200 are all Tours, and a campaign aimed at the centre should not pay to
    reach the north. services.communes turns the code into the most precise
    name it can stand behind — a known district, an arrondissement, the
    commune, and only then the bare code.

    The client's own `city`, where an import or an older signup left one, is the
    fallback rather than the lead: it says "Tours" where the code says "Tours
    Nord".
    """
    postal = str(cust.get("postal_code") or "").strip()
    if postal:
        try:
            from services import communes
            label = communes.label_for(postal)
            if label:
                return label, postal
        except Exception:
            pass        # a missing name must never cost the merchant the page
    city = str(cust.get("city") or "").strip()
    if city:
        return city, postal
    return (postal or "Non renseigné"), postal


def _display_names(seen: Dict[str, set]) -> Dict[str, str]:
    """(label, code) key → what the merchant reads.

    Two postal codes that resolve to the same name are two different places.
    The curated districts and the arrondissements already tell themselves apart;
    everywhere else "Tours" would silently merge 37000 and 37100. Rather than
    invent a district name that cannot be verified, the code is appended —
    "Tours (37100)" — and only where it is needed, so a commune with a single
    code stays plain.
    """
    names: Dict[str, str] = {}
    for label, codes in seen.items():
        if len(codes) <= 1:
            for code in codes or {""}:
                names[f"{label}|{code}"] = label
        else:
            for code in codes:
                names[f"{label}|{code}"] = f"{label} ({code})" if code else label
    return names


# ---------------------------------------------------------------------------
# the client set
# ---------------------------------------------------------------------------
def _window(date_from: Optional[str], date_to: Optional[str]) -> Tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    def parse(value, fallback):
        try:
            return datetime.fromisoformat((value or "").replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except Exception:
            return fallback
    end = parse(date_to, now).replace(hour=23, minute=59, second=59, microsecond=999999)
    start = parse(date_from, end - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    if start > end:
        start, end = end.replace(hour=0, minute=0, second=0, microsecond=0), start
    return start, end


def _clients_in_period(tid: str, start: datetime, end: datetime,
                       store_scope: Optional["S.Scope"] = None, population: str = "periode") -> List[Dict[str, Any]]:
    """The clients who actually came during the period — that is what makes the
    date range mean something on a catchment map. A shop with no visits logged
    in the window falls back to everyone on the books, so a new merchant sees
    their base rather than an empty map.
    """
    tills = S.visit_filter(store_scope) if store_scope else {}
    base = S.customer_filter(store_scope) if store_scope else {"tenant_id": tid}
    fields = {"_id": 0, "id": 1, "name": 1, "city": 1, "postal_code": 1,
              "latitude": 1, "longitude": 1, "tier": 1, "visits": 1}
    if population == "tous":
        return list(_db.customers.find(base, fields))
    ids = set(_db.visits.distinct("customer_id", {"tenant_id": tid, "visit_time": {"$gte": start, "$lte": end}, **tills}))
    # …and those who joined in the period (QA F11: 100 imported clients never
    # showed, the map only counted visits)
    ids |= {c["id"] for c in _db.customers.find({**base, "created_at": {"$gte": start, "$lte": end}}, {"_id": 0, "id": 1})}
    query = {"tenant_id": tid, "id": {"$in": list(ids)}} if ids else base
    return list(_db.customers.find(query, fields))


def _local_label(tenant: Dict[str, Any]) -> str:
    """« Nice et alentours » — the shop's own town."""
    city = str(tenant.get("city") or tenant.get("ville") or "").strip()
    if not city:
        postal = _postal_from(tenant)
        if postal:
            try:
                from services import communes
                city = communes.city_for(postal) or ""
            except Exception:
                city = ""
    return f"{city} et alentours" if city else SCOPES["local"]["label"]


# ---------------------------------------------------------------------------
# the computation
# ---------------------------------------------------------------------------
def _zone_of(distance_km: float) -> Optional[str]:
    for z in ZONES:
        if z["from_km"] <= distance_km < z["to_km"]:
            return z["key"]
    return None


def _band_of(distance_km: float, speed_kmh: float) -> Optional[int]:
    minutes = (distance_km / speed_kmh) * 60 if speed_kmh else 1e9
    for m in BANDS_MIN:
        if minutes <= m:
            return m
    return None


def _top(counter: Dict[str, int], names: Dict[str, str], limit: int = 5) -> List[Dict[str, Any]]:
    """Counters are keyed "label|code"; the merchant reads the display name."""
    return [{"name": names.get(key, key.split("|")[0]), "clients": n}
            for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _pct(part: int, whole: int) -> int:
    return round(part / whole * 100) if whole else 0


def compute(tid: str, start: datetime, end: datetime, mode: str, scope: str,
            store_scope: Optional["S.Scope"] = None, population: str = "periode") -> Dict[str, Any]:
    tenant = (_db.tenants.find_one({"id": tid}) or {}) if _db is not None else {}
    shop_lat, shop_lng, shop_src = _shop_position(tenant)
    # One establishment chosen: the map is centred on it, when its address is known.
    one = store_scope.single if store_scope is not None else None
    branch = next((b for b in tenant.get("branches") or [] if b.get("id") == one), None) if one else None
    if branch:
        blat, blng, bsrc = _shop_position({k: v for k, v in branch.items() if k != "branches"})
        if blat is not None:
            shop_lat, shop_lng, shop_src = blat, blng, bsrc
    speed = MODES.get(mode, MODES["car"])["speed_kmh"]
    max_km = SCOPES.get(scope, SCOPES["local"])["max_km"]
    wide = scope in ("region", "france")          # beyond the rings is counted, not dropped
    zones_used = ZONES + ([FAR_ZONE] if wide else [])
    population = population if population in POPULATIONS else "periode"

    # …and named after it: its name, its town, « Lyon et alentours » (QA F35:
    # Paris and Lyon both read the main shop's « La Colle-sur-Loup »)
    here = branch or tenant
    result: Dict[str, Any] = {
        "shop": {"name": here.get("name") or tenant.get("name") or "Votre établissement",
                 "city": here.get("city") or "", "lat": shop_lat, "lng": shop_lng,
                 "position_source": shop_src},
        "mode": mode if mode in MODES else "car",
        "speed_kmh": speed,
        "scope": scope if scope in SCOPES else "local",
        "population": population,
        "local_label": _local_label(here),
        "from": start.isoformat(), "to": end.isoformat(),
    }
    if shop_lat is None:
        # No address, no map. Say so instead of drawing rings around Paris.
        result.update({
            "positioned": False, "reason": "no_shop_position",
            "catchment": {"zones": [], "total": 0},
            "isochrones": {"bands": [], "total": 0},
            "communes": {"zones": {}, "bands": {}, "combined": []},
            "commune_pins": [],
            "combined": {"catchment_total": 0, "isochrone_total": 0, "both": 0},
            "points": [], "precision": {}, "clients_total": 0, "out_of_range": 0,
        })
        return result

    clients = _clients_in_period(tid, start, end, store_scope, population)
    known = _resolve_postals(clients)
    band_keys: List[Any] = BANDS_MIN + ([FAR_BAND] if wide else [])
    zone_counts = {z["key"]: 0 for z in zones_used}
    band_counts = {m: 0 for m in band_keys}
    zone_communes: Dict[str, Dict[str, int]] = {z["key"]: {} for z in zones_used}
    band_communes: Dict[Any, Dict[str, int]] = {m: {} for m in band_keys}
    all_communes: Dict[str, int] = {}
    # A commune's point on the map is the average of its own clients' points —
    # no gazetteer needed, and it lands where the clients actually are.
    commune_sum: Dict[str, List[float]] = {}
    # Counted against "label|code" so two codes sharing a name stay apart until
    # the display pass decides whether they need telling apart.
    seen_codes: Dict[str, set] = {}
    precision = {"gps": 0, "postal": 0, "department": 0, "unknown": 0}
    points: List[Dict[str, Any]] = []
    in_zone = in_band = in_both = 0
    out_of_range = 0

    for cust in clients:
        lat, lng, how = _client_position(cust, known)
        precision[how] = precision.get(how, 0) + 1
        if lat is None:
            continue
        km = _haversine_km(shop_lat, shop_lng, lat, lng)
        if max_km is not None and km > max_km:
            out_of_range += 1
            continue

        zone = _zone_of(km)
        band = _band_of(km, speed)
        if wide:
            zone = zone or "far"
            band = band or FAR_BAND
        if zone is None and band is None:
            out_of_range += 1
            continue

        label, postal = _commune(cust)
        commune = f"{label}|{postal}"
        seen_codes.setdefault(label, set()).add(postal)
        all_communes[commune] = all_communes.get(commune, 0) + 1
        acc = commune_sum.setdefault(commune, [0.0, 0.0, 0.0])
        acc[0] += lat; acc[1] += lng; acc[2] += 1
        if zone:
            in_zone += 1
            zone_counts[zone] += 1
            zone_communes[zone][commune] = zone_communes[zone].get(commune, 0) + 1
        if band:
            in_band += 1
            band_counts[band] += 1
            band_communes[band][commune] = band_communes[band].get(commune, 0) + 1
        if zone and band:
            in_both += 1

        if len(points) < MAX_MAP_POINTS:
            points.append({"lat": round(lat, 5), "lng": round(lng, 5),
                           "zone": zone, "band": band, "precise": how == "gps"})

    display = _display_names(seen_codes)
    result.update({
        "positioned": True,
        "clients_total": len(clients),
        "out_of_range": out_of_range,
        "precision": precision,
        "catchment": {
            "total": in_zone,
            "zones": [{
                "key": z["key"], "label": z["label"], "tone": z["tone"],
                "from_km": z["from_km"], "to_km": z["to_km"],
                "radius_km": z["to_km"], "far": bool(z.get("far")),
                # The same ring, read as a travel time for the chosen mode.
                "minutes_to": round(z["to_km"] / speed * 60) if z["to_km"] else None,
                "clients": zone_counts[z["key"]],
                "pct": _pct(zone_counts[z["key"]], in_zone),
            } for z in zones_used],
        },
        "isochrones": {
            "total": in_band,
            "estimated": True,           # straight-line, not routed — say it
            "bands": [{
                "minutes": m, "tone": BAND_TONES[m],
                "radius_km": round(speed * m / 60, 2),
                "clients": band_counts[m],
                "pct": _pct(band_counts[m], in_band),
            } for m in BANDS_MIN] + ([{
                "minutes": FAR_BAND, "far": True, "after": BANDS_MIN[-1], "tone": "slate", "radius_km": None,
                "clients": band_counts[FAR_BAND], "pct": _pct(band_counts[FAR_BAND], in_band),
            }] if wide else []),
        },
        "communes": {
            "zones": {k: _top(v, display) for k, v in zone_communes.items()},
            "bands": {str(k): _top(v, display) for k, v in band_communes.items()},
            "combined": _top(all_communes, display, 15),
        },
        "combined": {"catchment_total": in_zone, "isochrone_total": in_band, "both": in_both},
        "commune_pins": [{
            "name": display.get(name, name.split("|")[0]),
            "clients": all_communes[name],
            "lat": round(commune_sum[name][0] / commune_sum[name][2], 5),
            "lng": round(commune_sum[name][1] / commune_sum[name][2], 5),
        } for name, _ in sorted(all_communes.items(), key=lambda kv: -kv[1])[:10]
            if commune_sum.get(name, [0, 0, 0])[2]],
        "points": points,
    })
    return result


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
@router.get("/api/owner/geo/catchment")
def catchment(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    mode: str = "car",
    scope: str = "local",
    population: str = "periode",
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    start, end = _window(date_from, date_to)
    data = compute(token_data.tenant_id, start, end, mode, scope, S.resolve(token_data, request), population)
    data["modes"] = [{"key": k, "label": v["label"], "speed_kmh": v["speed_kmh"]} for k, v in MODES.items()]
    data["scopes"] = [{"key": k, "label": data.get("local_label") if k == "local" else v["label"], "max_km": v["max_km"]}
                      for k, v in SCOPES.items()]
    data["populations"] = [{"key": k, "label": v} for k, v in POPULATIONS.items()]
    return data


@router.get("/api/owner/geo/export")
def export_csv(
    date_from: Optional[str] = Query(None, alias="from"),
    date_to: Optional[str] = Query(None, alias="to"),
    mode: str = "car",
    scope: str = "local",
    population: str = "periode",
    request: Request = None,
    token_data: TokenData = Depends(require_role(READERS, partial_ok=True)),
):
    """The breakdown behind the map — zones, bands and communes — as one CSV."""
    start, end = _window(date_from, date_to)
    d = compute(token_data.tenant_id, start, end, mode, scope, S.resolve(token_data, request), population)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Section", "Libellé", "Détail", "Clients", "Part (%)"])
    for z in d["catchment"]["zones"]:
        w.writerow(["Zone de chalandise", z["label"],
                    f"plus de {z['from_km']:.0f} km" if z.get("far") else f"{z['from_km']:.0f}–{z['to_km']:.0f} km",
                    z["clients"], z["pct"]])
    for b in d["isochrones"]["bands"]:
        w.writerow(["Isochrone (estimation)", f"plus de {b['after']} min" if b.get("far") else f"{b['minutes']} min",
                    "" if b.get("far") else f"≈ {b['radius_km']:.1f} km", b["clients"], b["pct"]])
    for z in d["catchment"]["zones"]:
        for row in d["communes"]["zones"].get(z["key"], []):
            w.writerow([f"Communes · {z['label']}", row["name"], "", row["clients"], ""])
    for b in d["isochrones"]["bands"]:
        for row in d["communes"]["bands"].get(str(b["minutes"]), []):
            lab = f"plus de {b['after']} min" if b.get("far") else f"{b['minutes']} min"
            w.writerow([f"Communes · {lab}", row["name"], "", row["clients"], ""])
    data = "﻿" + buf.getvalue()
    name = f"fidclic-geolocalisation-{start:%Y%m%d}-{end:%Y%m%d}.csv"
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
