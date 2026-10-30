"""
« Plusieurs personnes » — one client pays for several people at one visit.

User, 2026-10-30: at the hairdresser, the spa, the institut, a mother brings
her three children and pays for all of them; « they should get it ». The till
picks « Plusieurs personnes » and how many, then the services as usual; the
card gets what each person would have earned. « bina kisi fail k ».

THE RULES (decided with the user)
    · ON by default for the service trades — the activités of the « salon »
      and « spa » sectors (coiffure, barbier, institut, onglerie, spa /
      massage). Any shop switches it on or off on its card's settings
      (`multi_person`), and sets the most people one visit may have
      (`multi_person_max`, 2–20, default 6).
    · It is ONE visit: visits, palier and the shop's figures count 1.
    · × the number of people the till entered: the tampons (the card's meter
      gets one visit-unit per person) and the points of a « points par
      visite » card. « Points par euro » and the cagnotte follow the amount,
      which already pays for everyone.

server._scan_visit_impl asks `persons()` before anything is written: a
refused number refuses the whole scan, so the till corrects and resends.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from fastapi import HTTPException

SERVICE_SECTORS = {"salon", "spa"}
DEFAULT_MAX = 6
LOWEST_MAX, HIGHEST_MAX = 2, 20


def default_on(tenant: Optional[Dict[str, Any]]) -> bool:
    from services import activities as A
    try:
        return A.of(tenant or {}).get("sector") in SERVICE_SECTORS
    except Exception:
        return False


def _whole(value: Any) -> Optional[int]:
    """A whole number sent by a page (3, 3.0, "3"), else None. A bool is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        return int(value.strip()) if value.strip().isdigit() else None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    return None


def clean_max(value: Any) -> Optional[int]:
    """The shop's own most, or None when it is not a whole number in range."""
    n = _whole(value)
    return n if n is not None and LOWEST_MAX <= n <= HIGHEST_MAX else None


def settings(tenant: Optional[Dict[str, Any]], tpl: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """{"enabled", "max", "default"} for this shop's card."""
    tpl = tpl or {}
    default = default_on(tenant)
    own = tpl.get("multi_person")
    return {"enabled": default if own is None else bool(own),
            "max": clean_max(tpl.get("multi_person_max")) or DEFAULT_MAX,
            "default": default}


def persons(value: Any, tenant: Optional[Dict[str, Any]], tpl: Optional[Dict[str, Any]]) -> int:
    """How many people this visit is for — 1 when none is said. Raises 400
    for anything a till should not send."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 1
    n = _whole(value)
    if n is None or n < 1:
        raise HTTPException(status_code=400, detail="Nombre de personnes invalide.")
    if n == 1:
        return 1
    s = settings(tenant, tpl)
    if not s["enabled"]:
        raise HTTPException(status_code=400,
                            detail="La visite à plusieurs personnes n'est pas activée pour ce commerce "
                                   "(Carte de fidélité › Paramètres de la carte).")
    if n > s["max"]:
        raise HTTPException(status_code=400, detail=f"{s['max']} personnes au maximum par visite.")
    return n
