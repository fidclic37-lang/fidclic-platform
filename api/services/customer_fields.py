"""
A customer's own details, checked the same way wherever they are typed: the
signup form (/api/join) and the shop's « Modifier la fiche » (user,
2026-10-08). Each function returns the clean value or raises a 400 with a
French sentence naming the field.
"""
from __future__ import annotations

import calendar
import re
from typing import Dict, Optional

from fastapi import HTTPException


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=400, detail=msg)


def name(v: Optional[str]) -> str:
    s = re.sub(r"\s+", " ", (v or "").strip())
    if not s or len(s) > 80:
        raise _bad("Indiquez le nom (80 caractères au plus).")
    return s


FR_PHONE_MESSAGE = "Numéro de téléphone français : 0 suivi de 9 chiffres (par exemple 06 12 34 56 78)."


def phone(v: Optional[str]) -> str:
    """Digits only (user, 2026-10-09: « # », « * » and letters got through).

    France: 0 then exactly 9 digits — returned as « 0612345678 ». « +33 6 … »
    is the same number and comes back in that form too.
    Abroad: « + », a country code from the list (services/dial_codes, the
    same as the forms' list), then the number — returned as « +447700900123 ».
    Spaces, dots and dashes between digits are tolerated (a pasted number),
    anything else is refused."""
    from services.dial_codes import DIAL_CODES
    raw = (v or "").strip()
    if not raw:
        raise _bad("Indiquez le numéro de téléphone.")
    if re.search(r"[^\d\s().+\-]", raw) or "+" in raw[1:]:
        raise _bad("Le téléphone ne peut contenir que des chiffres.")
    digits = re.sub(r"\D", "", raw)
    international = raw.startswith("+") or digits.startswith("00")
    if international:
        if digits.startswith("00"):
            digits = digits[2:]
        if digits.startswith("33"):                       # France written abroad-style
            national = digits[2:]
            national = national if national.startswith("0") else "0" + national
            if re.fullmatch(r"0[1-9]\d{8}", national):
                return national
            raise _bad(FR_PHONE_MESSAGE)
        code = next((digits[:n] for n in (3, 2, 1) if digits[:n] in DIAL_CODES), None)
        if not code:
            raise _bad("Indicatif pays inconnu : choisissez le pays dans la liste.")
        if len(digits) - len(code) < 4 or len(digits) > 15:
            raise _bad("Numéro de téléphone invalide pour ce pays.")
        return "+" + digits
    if not re.fullmatch(r"0[1-9]\d{8}", digits):
        raise _bad(FR_PHONE_MESSAGE)
    return digits


def postal_code(v: Optional[str]) -> str:
    s = (v or "").strip()
    if not re.fullmatch(r"\d{5}", s):
        raise _bad("Code postal invalide : 5 chiffres (par exemple 37000).")
    return s


def birth(v: Optional[str], need_year: bool = False) -> Dict[str, Optional[str]]:
    """The date of birth (user, 2026-10-09: the full date, so the age shows in
    Clients). Reads « 25/12/1990 », « 1990-12-25 », and the older « 25/12 » /
    « 12-25 » without a year. Returns {"birthday": "MM-DD" (the birthday
    automations' key, as before), "birth_date": "YYYY-MM-DD" or None}.
    `need_year`: the signup form asks for the year."""
    b = (v or "").strip()
    year = None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", b)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", b)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", b) or None
            if m:
                day, month = int(m.group(1)), int(m.group(2))
            else:
                m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", b)
                if not m:
                    raise _bad("Date de naissance invalide : JJ/MM/AAAA, par exemple 25/12/1990.")
                month, day = int(m.group(1)), int(m.group(2))
    if year is None and need_year:
        raise _bad("Date de naissance complète : JJ/MM/AAAA, par exemple 25/12/1990.")
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(year or 2024, month)[1]:
        raise _bad("Date de naissance invalide : ce jour n'existe pas.")
    iso = None
    if year is not None:
        today = _paris_today()
        if year < 1900 or (year, month, day) > (today.year, today.month, today.day):
            raise _bad("Date de naissance invalide : vérifiez l'année.")
        iso = f"{year:04d}-{month:02d}-{day:02d}"
    return {"birthday": f"{month:02d}-{day:02d}", "birth_date": iso}


def birthday(v: Optional[str]) -> str:
    """MM-DD — the birthday automations' key (see birth for the full date)."""
    return birth(v)["birthday"]


def _paris_today():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Europe/Paris")).date()


def age_of(birth_date: Optional[str], today=None) -> Optional[int]:
    """Whole years on the shop's calendar (Paris). A 29 February birthday
    turns a year older on 1 March in a common year."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", str(birth_date or ""))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    t = today or _paris_today()
    return t.year - y - ((t.month, t.day) < (mo, d))

def email(v: Optional[str]) -> str:
    """Optional: « » stays « »."""
    s = (v or "").strip()
    if s and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s):
        raise _bad("Adresse e-mail invalide.")
    return s


def phone_digits(v: Optional[str]) -> str:
    """The comparison key of a phone — the same person whatever the writing:
    « 06 12 34 56 78 », « +33 6 12 34 56 78 » and « 0033612345678 » all give
    « 0612345678 »."""
    raw = (v or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0033"):
        digits = digits[4:]
        return digits if digits.startswith("0") else "0" + digits
    if raw.startswith("+") and digits.startswith("33"):
        rest = digits[2:]
        return rest if rest.startswith("0") else "0" + rest
    return digits
