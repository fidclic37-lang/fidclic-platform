"""
Seeds and migrations once per DEPLOYMENT, not once per instance (2026-11-12
outage: while MongoDB was saturated, every new Vercel instance asked it 15+
questions — team roles, CRM templates, task types, old migrations — before
serving anyone, exactly when there was no room left; several of those inits
failed with « SSL handshake failed » in the logs).

The first instance of a deployment runs everything (idempotent, as before)
and `mark()` writes the build id in platform_settings. Every other instance
calls `seeded()` — ONE find_one, then answered from memory — and each seed
site skips its reads and writes. Locally and in tests there is no build id:
`seeded()` is always False and nothing changes.

A new deployment has a new build id, so its first instance seeds again —
exactly like the index fingerprint (features/_loader).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

KEY = "boot_seeds"
_cache: dict = {}


def _build() -> str:
    return os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("VERCEL_DEPLOYMENT_ID") or ""


def forget() -> None:
    _cache.clear()


def seeded(db: Any) -> bool:
    """True when another instance of THIS deployment already ran the seeds."""
    build = _build()
    if not build or db is None:
        return False
    if _cache.get("build") == build:
        return _cache["seeded"]
    try:
        doc = db.platform_settings.find_one({"key": KEY}, {"_id": 0, "value": 1})
        done = bool(doc and doc.get("value") == build)
    except Exception:                              # noqa: BLE001 — unreadable = seed, as before
        return False
    _cache.update(build=build, seeded=done)
    return done


def mark(db: Any) -> None:
    """The deployment's seeds ran: written by the instance that ran them."""
    build = _build()
    if not build or db is None:
        return
    if _cache.get("build") == build and _cache.get("seeded"):
        return                                      # another start of this process already wrote it
    try:
        db.platform_settings.update_one({"key": KEY}, {"$set": {"key": KEY, "value": build,
                                                                "at": datetime.now(timezone.utc)}}, upsert=True)
        _cache.update(build=build, seeded=True)
    except Exception:                              # noqa: BLE001 — the next instance seeds again, no harm
        pass
