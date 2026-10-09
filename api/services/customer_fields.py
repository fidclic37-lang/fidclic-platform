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


def phone(v: Optional[str]) -> str:
    raw = (v or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not re.fullmatch(r"[\d\s().+\-]{6,25}", raw) or not 9 <= len(digits) <= 15:
        raise _bad("Numéro de téléphone invalide (par exemple 06 12 34 56 78).")
    return raw


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
    return re.sub(r"\D", "", v or "")
