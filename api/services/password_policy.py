"""
Password policy — one rule set, enforced everywhere (S3).

Status: 🟢 Core security.

WHY THIS EXISTS
    A single cabinet login can reach 45 businesses' financial data. A 6-character
    password on that account is not a small risk — it is the whole product's risk.
    The policy lives in ONE module so it cannot drift between the signup form,
    staff creation, password reset and the cabinet invite flow.

RULE (v1)
    - minimum 10 characters
    - at least one lowercase, one uppercase, one digit, one special character
    - not one of the obvious dictionary passwords

WHY THESE FOUR CLASSES
    Length is what actually defeats brute force; the character classes mostly
    defeat the "Password1" reflex. Both are cheap for a legitimate user (a
    passphrase like `Cafe-Lumiere-2026!` passes) and expensive for an attacker.

NOTE ON EXISTING USERS
    This is enforced on CREATION and CHANGE only. Existing accounts keep working
    until they next set a password — locking people out of live data to enforce
    a new rule would be worse than the risk it removes.
"""
from __future__ import annotations

import re
import secrets
import string
from typing import List, Tuple

MIN_LENGTH = 10

SPECIALS = "!@#$%^&*()_+-=[]{}|;:,.<>?/~`'\"\\"

#: Passwords so common that length and classes do not save them.
_BLOCKLIST = {
    "password", "motdepasse", "azerty", "qwerty", "123456", "123456789",
    "azertyuiop", "qwertyuiop", "admin", "administrateur", "welcome",
    "bienvenue", "letmein", "iloveyou", "fidelitour", "fidclic",
}


def check(password: str) -> Tuple[bool, List[str]]:
    """Return (ok, [french error messages]).

    Returns EVERY failing rule, not just the first, so the user can fix the
    password in one go instead of playing whack-a-mole.
    """
    pw = password or ""
    errors: List[str] = []

    if len(pw) < MIN_LENGTH:
        errors.append(f"Le mot de passe doit contenir au moins {MIN_LENGTH} caractères.")
    if not re.search(r"[a-z]", pw):
        errors.append("Il doit contenir au moins une lettre minuscule.")
    if not re.search(r"[A-Z]", pw):
        errors.append("Il doit contenir au moins une lettre majuscule.")
    if not re.search(r"[0-9]", pw):
        errors.append("Il doit contenir au moins un chiffre.")
    if not any(ch in SPECIALS for ch in pw):
        errors.append("Il doit contenir au moins un caractère spécial (ex. ! ? @ # -).")

    lowered = pw.lower()
    if lowered in _BLOCKLIST or any(b in lowered for b in _BLOCKLIST if len(b) >= 6):
        errors.append("Ce mot de passe est trop courant. Choisissez-en un autre.")

    # it was published (incident 2026-10-27): it would never sign in on Vercel
    from services import published_passwords
    if published_passwords.blocked(pw):
        errors.append("Ce mot de passe a été rendu public. Choisissez-en un autre.")

    return (len(errors) == 0), errors


def assert_valid(password: str) -> None:
    """Raise HTTP 422 with all failing rules joined — for use inside endpoints."""
    ok, errors = check(password)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(422, " ".join(errors))


def generate(length: int = 14) -> str:
    """Generate a policy-compliant password (for admin-created accounts).

    Built class-by-class then shuffled, so it is guaranteed to satisfy the rules
    rather than looping until a random string happens to pass.
    """
    length = max(length, MIN_LENGTH)
    pools = [string.ascii_lowercase, string.ascii_uppercase, string.digits, SPECIALS]
    chars = [secrets.choice(p) for p in pools]
    everything = "".join(pools)
    chars += [secrets.choice(everything) for _ in range(length - len(chars))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
