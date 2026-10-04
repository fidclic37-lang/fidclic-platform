"""
Verified addresses for the sign-up (user, 2026-10-04).

WHY
    Step 2 took the address, postal code, city and country as free text, so
    « 12 rue X · 75000 · Lyon · Belgique » went through. Now every address
    comes from an address service, inside the chosen country, and the server
    only trusts what that service returned.

WHERE ADDRESSES COME FROM
    France   → the Base Adresse Nationale (api-adresse.data.gouv.fr): the
               government's own address file, free, no key, no quota.
    Elsewhere → Photon (photon.komoot.io, OpenStreetMap data, free, no key).
               Results from another country are dropped, so a city can never
               belong to a different country than the one selected.

HOW THE SERVER TRUSTS IT (no second lookup at submit time)
    Every suggestion carries a `token`: an HMAC over its normalised fields
    (country, street, postcode, city, lat/lng). The form sends the token back;
    complete_company() takes the address FROM the token, never from the typed
    text, so an edited or invented address cannot get through and a slow
    geocoder at submit time cannot block a sign-up.

TWO KINDS
    "address" — a street address (house number or street) with its city.
    "city"    — the fallback when the exact address isn't listed (new
                building, small village): the city is verified, the street is
                typed by the owner.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
PHOTON_URL = "https://photon.komoot.io/api/"
TIMEOUT_S = 4.0
UA = "FidClic/1.0 (+https://www.fidclic.com)"

# Postal-code shapes, used when a city from Photon comes without one and the
# owner types it. Unknown countries accept 2–10 letters/digits.
POSTCODE_RE = {
    "FR": r"\d{5}", "MC": r"980\d{2}", "BE": r"\d{4}", "CH": r"\d{4}", "LU": r"(L-?)?\d{4}",
    "DE": r"\d{5}", "ES": r"\d{5}", "IT": r"\d{5}", "PT": r"\d{4}-?\d{3}", "NL": r"\d{4} ?[A-Za-z]{2}",
    "GB": r"[A-Za-z]{1,2}\d[A-Za-z\d]? ?\d[A-Za-z]{2}", "IE": r"[A-Za-z]\d[\dWw] ?[A-Za-z\d]{4}",
    "US": r"\d{5}(-\d{4})?", "CA": r"[A-Za-z]\d[A-Za-z] ?\d[A-Za-z]\d", "MA": r"\d{5}", "TN": r"\d{4}",
    "DZ": r"\d{5}", "SN": r"\d{5}", "CI": r"[\w ]{2,10}", "AT": r"\d{4}", "DK": r"\d{4}", "SE": r"\d{3} ?\d{2}",
    "NO": r"\d{4}", "FI": r"\d{5}", "PL": r"\d{2}-\d{3}", "GR": r"\d{3} ?\d{2}", "AE": r"[\w ]{0,10}",
}


def _secret() -> bytes:
    return (os.getenv("ADDRESS_TOKEN_SECRET") or os.getenv("JWT_SECRET") or "fidclic-address").encode()


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def postcode_ok(country: str, postcode: str) -> bool:
    pat = POSTCODE_RE.get((country or "").upper(), r"[A-Za-z0-9 -]{2,10}")
    return bool(re.fullmatch(pat, (postcode or "").strip()))


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------
_FIELDS = ("kind", "country", "street", "postcode", "city", "lat", "lng")


def sign(item: Dict[str, Any]) -> str:
    body = {k: item.get(k) for k in _FIELDS}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(_secret(), raw, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(raw).decode().rstrip("=") + "." + base64.urlsafe_b64encode(mac).decode().rstrip("=")


def verify(token: str) -> Optional[Dict[str, Any]]:
    """The signed fields, or None when the token was not made by us."""
    try:
        b64, mac_b64 = (token or "").split(".", 1)
        raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
        mac = base64.urlsafe_b64decode(mac_b64 + "=" * (-len(mac_b64) % 4))
    except Exception:
        return None
    good = hmac.new(_secret(), raw, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(mac, good):
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    import httpx
    with httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": UA}) as c:
        r = c.get(url, params=params)
        r.raise_for_status()
        return r.json()


def _item(kind: str, country: str, street: str, postcode: str, city: str, lat: Any, lng: Any, label: str) -> Dict[str, Any]:
    it = {"kind": kind, "country": country, "street": street or "", "postcode": postcode or "", "city": city or "",
          "lat": round(float(lat), 6) if lat is not None else None,
          "lng": round(float(lng), 6) if lng is not None else None}
    it["label"] = label
    it["token"] = sign(it)
    return it


def _ban(q: str, kind: str, limit: int) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"q": q, "limit": limit, "autocomplete": 1}
    if kind == "city":
        params["type"] = "municipality"
    out = []
    for f in (_get(BAN_URL, params).get("features") or []):
        p, (lng, lat) = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or (None, None)
        if kind == "address" and p.get("type") not in ("housenumber", "street"):
            continue
        city, pc = p.get("city") or "", p.get("postcode") or ""
        if not city or not pc:
            continue
        street = p.get("name") if kind == "address" else ""
        label = p.get("label") or f"{street} {pc} {city}".strip()
        out.append(_item(kind, "FR", street, pc, city, lat, lng, label))
    return out


def _photon(q: str, kind: str, country: str, limit: int) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"q": q, "limit": 15, "lang": "fr"}
    if kind == "city":
        params["layer"] = "city"
    out = []
    for f in (_get(PHOTON_URL, params).get("features") or []):
        p = f.get("properties") or {}
        lng, lat = ((f.get("geometry") or {}).get("coordinates") or [None, None])[:2]
        if (p.get("countrycode") or "").upper() != country:
            continue                                    # never a city of another country
        if kind == "address":
            street = " ".join(x for x in [p.get("housenumber"), p.get("street") or (p.get("name") if p.get("type") == "street" else None)] if x)
            city = p.get("city") or p.get("town") or p.get("village") or p.get("locality") or ""
            if not street or not city:
                continue
            pc = p.get("postcode") or ""
            label = f"{street}, {pc + ' ' if pc else ''}{city}"
        else:
            city = p.get("name") or p.get("city") or ""
            if not city:
                continue
            street, pc = "", p.get("postcode") or ""
            region = p.get("state") or p.get("county") or ""
            label = f"{city}{' ' + pc if pc else ''}{' · ' + region if region else ''}"
        out.append(_item(kind, country, street, pc, city, lat, lng, label))
        if len(out) >= limit:
            break
    return out


def search(q: str, country: str, kind: str = "address", limit: int = 6) -> List[Dict[str, Any]]:
    """Suggestions inside `country` (ISO-2). Raises on network errors so the
    endpoint can tell « service unavailable » from « nothing found »."""
    q = (q or "").strip()
    country = (country or "FR").strip().upper()[:2]
    kind = "city" if kind == "city" else "address"
    if len(q) < 3 and not (kind == "city" and q.isdigit() and len(q) >= 2):
        return []
    if country == "FR":
        return _ban(q, kind, limit)
    return _photon(q, kind, country, limit)
