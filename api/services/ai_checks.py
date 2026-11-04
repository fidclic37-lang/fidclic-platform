"""
What an AI answer is checked against: the same words and figures for the
Golden set's grader (features/golden_set) and for the live answers
(features/ai_routing), so the two can never disagree on what a phone number,
a French sentence or a figure « read somewhere » is.
"""
from __future__ import annotations

import contextlib
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


_MONEY_KEY = re.compile(r'"[a-z0-9_]*_eur"\s*:\s*(-?\d+(?:\.\d+)?)')
_EURO = re.compile(r"(\d{1,3}(?: \d{3})+|\d+)(?:[,.](\d{1,2}))?\s?(k€|€|euros?\b|EUR\b)")
# Near an amount, these make it an idea to try (« une remise de 20 € »)…
_IDEA = re.compile(r"remise|reduction|offr|offert|\bbons?\b|cadeau|coupon|promo")
# …unless it says what that brought in (« vos remises ont rapporté 900 € »).
_CLAIM = re.compile(r"\bca\b|chiffre|rapport|gener|gagn|recette|vendu|depens|revenu")
_ROUGHLY = re.compile(r"environ|pres de|presque|autour de")
ROUGH_SHARE = 0.03


def money_in(text: str) -> List[float]:
    """The amounts of a prompt: JSON fields named *_eur and anything written in
    euros. Never a count, a date or a percentage."""
    out = []
    for m in _MONEY_KEY.finditer(text or ""):
        with contextlib.suppress(OverflowError, ValueError):
            out.append(abs(float(m.group(1))))
    return out + _euros_in(text or "")


def unread_amounts(text: str, seen: List[float], min_eur: float = 1) -> List[float]:
    """The € amounts of `text` that are neither an amount of `seen` nor the sum
    or difference of two of them. An offer to try is not a claim about the
    shop; « environ » may round to within 3 %."""
    pool = [s for s in seen if s >= 1]
    known = set(pool)
    for i, x in enumerate(pool[:400]):
        for y in pool[i:400]:
            known.add(round(x + y, 2))
            known.add(round(abs(x - y), 2))
    known_list = list(known)
    plain = _plain(text or "")
    out = []
    for m in _EURO.finditer(plain):
        try:
            x = float(f"{int(m.group(1).replace(' ', ''))}.{m.group(2) or 0}") * (1000 if m.group(3) == "k€" else 1)
        except ValueError:                     # a run of digits too long to be an amount
            continue
        if x < max(min_eur, 1) or any(abs(x - k) <= 0.5 for k in known_list):
            continue
        before = fold(re.split(r"[.!?;\n]", plain[max(0, m.start() - 30):m.start()])[-1])
        after = fold(re.split(r"[.!?;\n]", plain[m.end():m.end() + 20])[0])
        if _ROUGHLY.search(before) and any(abs(x - k) <= ROUGH_SHARE * k for k in known_list):
            continue
        if (_IDEA.search(before) or _IDEA.search(after)) and not _CLAIM.search(before):
            continue
        out.append(x)
    return out
