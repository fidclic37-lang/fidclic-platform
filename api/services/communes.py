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
from typing import Dict, Optional

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
TIMEOUT_S = 4.0

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
