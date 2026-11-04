"""
What an AI answer is checked against: the same words and figures for the
Golden set's grader (features/golden_set) and for the live answers
(features/ai_routing), so the two can never disagree on what a phone number,
a French sentence or a figure « read somewhere » is.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, List


def fold(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).replace("’", "'")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


MONTHS = ["janvier", "fevrier", "mars", "avril", "mai", "juin", "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{1,2}(?:er)?\s+(?:"
                   + "|".join(MONTHS) + r")(?:\s+\d{4})?\b|\b(?:19|20)\d{2}\b")
_HOUR = re.compile(r"\b\d{1,2}\s?h(?:\s?\d{2})?\b|\b\d{1,2}:\d{2}\b")
_NUM = re.compile(r"(?<![\d,.])(\d{1,3}(?: \d{3})+|\d+)(?:([,.])(\d+))?(?!\d)")
_PHONE = re.compile(r"(?:\+33\s?|\b0)[1-9](?:[\s.-]?\d{2}){4}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_FR = {"le", "la", "les", "de", "des", "du", "vous", "votre", "vos", "est", "et", "pour", "un", "une", "sur", "avec", "pas",
       "en", "au", "aux", "ce", "cette", "que", "qui", "nous", "a", "il", "elle", "dans", "par", "ne", "plus"}
_EN = {"the", "and", "you", "your", "is", "of", "with", "for", "this", "are", "was", "were", "have", "has", "visits", "revenue"}


def _plain(text: str) -> str:
    return (text or "").replace(" ", " ").replace(" ", " ").replace("−", "-")


def numbers_in(text: str) -> List[float]:
    t = _HOUR.sub(" ; ", _DATE.sub(" ; ", fold(_plain(text))))
    out = []
    for m in _NUM.finditer(t):
        try:
            whole = int(m.group(1).replace(" ", ""))
            if m.group(3):
                out.append(float(f"{whole}.{m.group(3)}"))
                if m.group(2) == "." and len(m.group(3)) == 3:
                    out.append(float(whole * 1000 + int(m.group(3))))
            else:
                out.append(float(whole))
        except (OverflowError, ValueError):    # a run of digits too long to be a figure
            continue
    return out


def _euros_in(text: str) -> List[float]:
    out = []
    for m in re.finditer(r"(\d{1,3}(?: \d{3})+|\d+)(?:[,.](\d{1,2}))?\s?(?:€|euros?\b)", _plain(text)):
        try:
            out.append(float(f"{int(m.group(1).replace(' ', ''))}.{m.group(2) or 0}"))
        except ValueError:                     # a run of digits too long to be an amount
            continue
    return out


def unread_amounts(text: str, seen: List[float], min_eur: float = 1) -> List[float]:
    """The € amounts of `text` that are neither a figure of `seen` nor the sum
    or difference of two of them."""
    pool = [s for s in seen if s >= 1]
    sums = set()
    for i, x in enumerate(pool[:400]):
        for y in pool[i:400]:
            sums.add(round(x + y, 2))
            sums.add(round(abs(x - y), 2))
    return [x for x in _euros_in(text)
            if x >= max(min_eur, 1) and not any(abs(x - s) <= 0.5 for s in pool) and not any(abs(x - s) <= 0.5 for s in sums)]
