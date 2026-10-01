"""
Commune names for French postal codes.

WHY
    A postal code tells a merchant nothing. "37200 — 12 clients" is a number;
    "Tours — 12 clients" is a fact they can act on. The signup form now asks for
    the town, but every client who joined before it did has only a code, and
    those are the ones already on the Géolocalisation page.

WHERE THE NAMES COME FROM
    The Base Adresse Nationale — the French government's own address service at
    api-adresse.data.gouv.fr. It is the authoritative source for communes, it is
    free, it needs no key and it has no quota, which makes it a better fit here
    than a keyed maps API: nothing to provision, nothing to bill, and it knows
    French communes better than a global geocoder does.

    Lookups are by `postcode`, not free text: searching "37200" as a query
    returns nothing, while filtering on the postcode resolves it to Tours.

CACHING
    Every answer is written to `commune_cache` and read from there first, so a
    postal code is fetched once for the whole platform and the page never waits
    on the network twice for the same code. A failure caches nothing, so it is
    retried next time rather than being remembered as "unknown" for ever.

SAFETY
    Every entry point returns "" rather than raising. A commune name is a
    nicety; no page may fail because a lookup timed out.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
TIMEOUT_S = 4.0

# ---------------------------------------------------------------------------
# Districts inside one commune
#
# A postal code is finer than a commune, and that finer grain is what makes a
# campaign targetable: 37000, 37100 and 37200 are all "Tours", but they are the
# centre, the north and the south, and a café in the centre does not want to
# pay to reach all three.
#
# NOTE ON WHERE THESE COME FROM. No French dataset carries them. The Base
# Adresse Nationale and La Poste's own base officielle both answer "TOURS" for
# all three codes — the centre/nord/sud split is La Poste's delivery naming, not
# an INSEE division. So the named districts below are a curated list, verified
# city by city, and everything not on it falls back to something that is always
# true (see label_for). Adding a city is one line.
# ---------------------------------------------------------------------------
DISTRICTS: Dict[str, str] = {
    # Tours — the launch city.
    "37000": "Tours (centre)",
    "37100": "Tours Nord",
    "37200": "Tours Sud",
}

# The three cities whose postal codes ARE arrondissements. Here the district is
# arithmetic, not a guess: the last two digits are the arrondissement number.
ARRONDISSEMENT_CITIES = {"75": ("Paris", 20), "69": ("Lyon", 9), "13": ("Marseille", 16)}


def _arrondissement(postal: str) -> str:
    """"75003" → "Paris 3e". Exact, and free of any lookup."""
    prefix, rest = postal[:2], postal[2:]
    city_max = ARRONDISSEMENT_CITIES.get(prefix)
    if not city_max:
        return ""
    city, highest = city_max
    try:
        n = int(rest)
    except ValueError:
        return ""
    if not 1 <= n <= highest:
        return ""
    return f"{city} {n}er" if n == 1 else f"{city} {n}e"

_db = None
_memory: Dict[str, str] = {}      # process-local, in front of the Mongo cache


def init(db):
    global _db
    _db = db
    try:
        _db.commune_cache.create_index("postal_code", unique=True)
    except Exception:
        pass


def _clean(postal_code: object) -> str:
    digits = re.sub(r"\D", "", str(postal_code or ""))
    return digits if len(digits) == 5 else ""


def _from_cache(postal: str) -> Optional[str]:
    if postal in _memory:
        return _memory[postal]
    if _db is None:
        return None
    try:
        row = _db.commune_cache.find_one({"postal_code": postal}, {"_id": 0, "city": 1})
    except Exception:
        return None
    if row and row.get("city"):
        _memory[postal] = row["city"]
        return row["city"]
    return None


def _remember(postal: str, city: str) -> None:
    _memory[postal] = city
    if _db is None:
        return
    try:
        _db.commune_cache.update_one(
            {"postal_code": postal},
            {"$set": {"postal_code": postal, "city": city, "at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception:
        pass


def _fetch(postal: str) -> str:
    try:
        import httpx
    except ImportError:
        return ""
    try:
        r = httpx.get(BAN_URL, params={"q": postal, "postcode": postal, "limit": 1},
                      timeout=TIMEOUT_S)
        if r.status_code != 200:
            return ""
        features = (r.json() or {}).get("features") or []
        if not features:
            return ""
        return str((features[0].get("properties") or {}).get("city") or "").strip()
    except Exception:
        return ""


def city_for(postal_code: object) -> str:
    """The commune a postal code belongs to, or "" when we cannot say."""
    postal = _clean(postal_code)
    if not postal:
        return ""
    cached = _from_cache(postal)
    if cached is not None:
        return cached
    city = _fetch(postal)
    if city:
        _remember(postal, city)
    return city


def label_for(postal_code: object) -> str:
    """What to call the place a postal code covers, most precise first.

        1. a named district, where one is known for certain ("Tours Nord")
        2. an arrondissement, where the code is one ("Paris 3e")
        3. the commune ("Saint-Cyr-sur-Loire")
        4. the code itself, when nothing else can be established

    Steps 1 and 2 are what make two codes in one commune tell apart. Where they
    cannot — no curated name, no arrondissement — the caller disambiguates with
    the code rather than this inventing a district name it cannot verify.
    """
    postal = _clean(postal_code)
    if not postal:
        return ""
    named = DISTRICTS.get(postal)
    if named:
        return named
    arrondissement = _arrondissement(postal)
    if arrondissement:
        return arrondissement
    return city_for(postal) or postal


def cities_for(postal_codes) -> Dict[str, str]:
    """Resolve a batch, one network call per code we have never seen. Used by
    the pages that group a whole client base at once."""
    out: Dict[str, str] = {}
    for code in dict.fromkeys(postal_codes or []):
        postal = _clean(code)
        if not postal:
            continue
        city = city_for(postal)
        if city:
            out[postal] = city
    return out


# ---------------------------------------------------------------------------
# Positions (super admin › Analytics › « Carte des commerces », 2026-10-01):
# the centre of a postal code — or of a town when there is no code — from the
# same BAN service, kept in commune_cache so each place is asked once.
# ---------------------------------------------------------------------------
_positions: Dict[str, Any] = {}


def _fetch_position(q: str, postcode: str = "", kind: str = "municipality"):
    try:
        import httpx
    except ImportError:
        return None
    try:
        params = {"q": q, "limit": 1, "type": kind}
        if postcode:
            params["postcode"] = postcode
        r = httpx.get(BAN_URL, params=params, timeout=TIMEOUT_S)
        if r.status_code != 200:
            return None
        features = (r.json() or {}).get("features") or []
        coords = ((features[0] if features else {}).get("geometry") or {}).get("coordinates")
        if coords and len(coords) == 2:
            return float(coords[1]), float(coords[0])
    except Exception:
        return None
    return None


def position_for(postal_code: object = "", city: object = "", fetch: bool = True):
    """(lat, lng) of a postal code (or of a town), or None. `fetch=False` only
    reads what is already known (no network)."""
    postal = _clean(postal_code)
    town = str(city or "").strip()
    key = postal or (f"ville:{town.lower()}" if town else "")
    if not key:
        return None
    if key in _positions:
        return _positions[key]
    if _db is not None:
        try:
            row = _db.commune_cache.find_one({"postal_code": key}, {"_id": 0, "lat": 1, "lng": 1})
            if row and row.get("lat") is not None:
                _positions[key] = (row["lat"], row["lng"])
                return _positions[key]
        except Exception:
            pass
    if not fetch:
        return None
    pos = _fetch_position(postal or town, postal) if postal else _fetch_position(town)
    if pos:
        _positions[key] = pos
        if _db is not None:
            try:
                _db.commune_cache.update_one({"postal_code": key}, {"$set": {"postal_code": key, "lat": pos[0], "lng": pos[1],
                                                                            "at": datetime.now(timezone.utc)}}, upsert=True)
            except Exception:
                pass
    return pos
