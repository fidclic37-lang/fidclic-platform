"""
A customer's own details, checked the same way wherever they are typed: the
signup form (/api/join) and the shop's « Modifier la fiche » (user,
2026-10-08). Each function returns the clean value or raises a 400 with a
French sentence naming the field.
"""
from __future__ import annotations

import calendar
import re
from typing import Optional

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


def birthday(v: Optional[str]) -> str:
    """MM-DD. Also reads « 25/12 » (day/month) and « 1990-12-25 »."""
    b = (v or "").strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", b)
    if m:
        b = f"{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.fullmatch(r"(?:\d{4}-)?(\d{2})-(\d{2})", b)
    if not m or not 1 <= int(m.group(1)) <= 12 or not 1 <= int(m.group(2)) <= calendar.monthrange(2024, int(m.group(1)))[1]:
        raise _bad("Date d'anniversaire invalide : choisissez le jour et le mois.")
    return f"{m.group(1)}-{m.group(2)}"


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
