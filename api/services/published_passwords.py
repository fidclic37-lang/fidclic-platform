"""
Passwords that were published, and never work on Vercel.

Security incident 2026-10-27: the repository was public from 2026-09-18. No
key or connection string was ever committed, but account passwords were — the
seed (super admins among them; it ran on production from 2026-04-20 until
2026-10-01, when it was turned off on Vercel), an old handoff table, the
tests. Every password found in the repository's history is listed here (the
list itself publishes nothing new).

    · blocked(): on Vercel (production and preview — they share the data), a
      password on this list signs no one in, whatever the account, and is
      refused wherever a password is checked (auth.verify_password). Locally
      the seed's passwords keep working (tests, e2e).
    · lock_due(): the tick, once per version of the list — every seeded
      account still holding its published password gets a random one and its
      sessions are ended; « Mot de passe oublié » sets a new one.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List

# every password literal in the repository's history (scan of 2026-10-27)
PUBLISHED = frozenset({
    "Admin!Demo2026", "AkshFT!2026", "Ancien-Pass2026!", "Autre-Chose2026!", "Autre-Pass2026!", "Bon!Motdepasse1",
    "Boss!2026x", "Boulang!2026", "Business2026!Xy", "Cafe-Lumiere2026!", "CafeLum!2026", "Caisse!Royal2026",
    "Chef!Royal2026", "Choisi-Par-Lea26!", "Commis!Royal2026", "Corner!Secret-2026", "Demo!2026", "Encore-Un2026!",
    "Fidelit0ur!Adm", "Lea-Nouveau2026!", "Manager!Royal2026", "Nouveau-Pass2026!", "Old-Shop2026!!", "Owner!2026x",
    "Owner!Demo2026", "Password", "Sofia!2026x", "Staff!Demo2026", "Temp-Pass2026!", "whatever",
})
VERSION = hashlib.sha256("|".join(sorted(PUBLISHED)).encode()).hexdigest()[:12]

# the accounts the seed created, and the password it gave them
SEEDED = {
    "admin@fidelitour.com": "Fidelit0ur!Adm",
    "akshanshshukla963@gmail.com": "AkshFT!2026",
    "demo.admin@fidelitour.com": "Admin!Demo2026",
    "demo.owner@fidelitour.com": "Owner!Demo2026",
    "demo.staff@fidelitour.com": "Staff!Demo2026",
    "owner@cafelumiere.fr": "CafeLum!2026",
    "owner@boulangerie-sm.fr": "Boulang!2026",
    "business@test-fidclic.fr": "Business2026!Xy",
}
SEEDED_PATTERNS = [(re.compile(r"^owner\+[a-z0-9-]+@fidclic\.com$"), "Demo!2026")]   # the seed's demo shops


def on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def blocked(plain: str) -> bool:
    return on_vercel() and (plain or "") in PUBLISHED


def _seeded_password(email: str):
    e = (email or "").strip().lower()
    if e in SEEDED:
        return SEEDED[e]
    for rx, pw in SEEDED_PATTERNS:
        if rx.match(e):
            return pw
    return None


def lock_due(db) -> Dict[str, Any]:
    """The tick: seeded accounts still on their published password are locked
    (random password, sessions ended), once per version of the list."""
    if not on_vercel() and not os.environ.get("FIDCLIC_LOCK_PUBLISHED"):
        return {"skipped": "local"}
    key = "published_password_lock"
    if (db.platform_settings.find_one({"key": key}) or {}).get("version") == VERSION:
        return {"locked": 0}
    import bcrypt
    import auth
    now = datetime.now(timezone.utc)
    locked: List[str] = []
    q = {"$or": [{"email": {"$in": list(SEEDED)}}, {"email": {"$regex": r"^owner\+[a-z0-9-]+@fidclic\.com$"}}]}
    for u in db.users.find(q, {"_id": 0, "email": 1, "hashed_password": 1}):
        pw, h = _seeded_password(u.get("email")), u.get("hashed_password")
        if not pw or not h:
            continue
        try:
            still = bcrypt.checkpw(pw.encode(), h.encode())
        except Exception:
            still = False
        if not still:
            continue                                    # changed since the seed: theirs now
        db.users.update_one({"email": u["email"]}, {"$set": {
            "hashed_password": auth.hash_password(secrets.token_urlsafe(32)),
            "password_locked_at": now, "password_lock_reason": "published"}})
        db.user_sessions.update_many({"email": u["email"], "revoked_at": None}, {"$set": {"revoked_at": now}})
        locked.append(u["email"])
    for email in locked:
        try:
            db.audit_logs.insert_one({"action": "security.published_password_locked", "actor": "system",
                                      "actor_type": "system", "target": email, "at": now, "timestamp": now})
        except Exception:
            pass
    db.platform_settings.update_one({"key": key}, {"$set": {"key": key, "version": VERSION, "at": now,
                                                            "locked": locked}}, upsert=True)
    return {"locked": len(locked)}
