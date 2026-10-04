"""
Remise à zéro de la plateforme — Super admin › Sécurité › Paramètres.
Status: 🟢 Core (user, 2026-10-04: « sab saaf … brand new fresh start »).

WHAT IT DOES
    Deletes every business and everything attached to it (customers, visits,
    campaigns, Wallet passes, invoices, tickets, logs…), every login except
    the super admin running it and the other super admins ticked to stay,
    and — if ticked — FidClic's own prospecting
    CRM. Platform SETTINGS stay: plan prices and limits, roles, security
    settings, invoice issuer details, canned replies, email/task templates.

THE THREE GATES (nothing is deleted by accident)
    1. GET  /api/admin/reset/preview  → what would go, counted per collection.
    2. GET  /api/admin/reset/backup   → the whole of it as a .json.gz download,
                                        and a one-time token (30 min) proving
                                        the backup was taken in this session.
       MongoDB Atlas backups are OFF on this cluster: this file is the only
       way back.
    3. POST /api/admin/reset          → needs that token AND « SUPPRIMER ».
    Super admin only (role super_admin), never a team member.

Seeding stays off on Vercel (server.SEED_DISABLED), so the demo data does not
come back on the next cold start.
"""
from __future__ import annotations

import gzip
import io
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import TokenData
from features.platform_access import require_super

router = APIRouter(tags=["platform-reset"])
_db = None

# Platform configuration — never touched.
KEEP = {
    "platform_settings", "platform_roles", "plan_settings", "plan_catalog",
    "crm_email_templates", "crm_task_templates", "support_replies",
    "commune_cache", "system_jobs", "platform_reset_tokens",
}
# FidClic's own sales data — deleted only when « CRM de prospection » is ticked.
CRM = {
    "crm_prospects", "crm_sequences", "crm_calls", "crm_tasks", "crm_email_sends",
    "crm_enrollments", "crm_activities", "crm_call_recordings", "crm_counters", "crm_goals",
}
TOKEN_TTL = timedelta(minutes=30)
PHRASE = "SUPPRIMER"


def init(db):
    global _db
    _db = db


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _scope(include_crm: bool) -> List[str]:
    names = [n for n in _db.list_collection_names() if not n.startswith("system.")]
    return sorted(n for n in names if n not in KEEP and (include_crm or n not in CRM))


# The super admin running the reset keeps their login AND their open
# sessions — deleting the session signed them out mid-reset (local run).
OWN = {"users", "user_sessions"}


def _kept(runner: str, extra: List[str]) -> List[str]:
    """The super admins who stay: the one running it, always, plus the other
    super admin logins ticked in the tool (user, 2026-10-04: keep
    akshanshshukla963@ and admin@fidelitour.com, delete demo.admin@). Only
    existing super admin accounts can be kept — never a merchant login."""
    extra = extra if isinstance(extra, (list, tuple)) else []      # direct calls get Query()'s default
    supers = {u["email"] for u in _db.users.find({"role": "super_admin"}, {"email": 1})}
    return sorted({runner} | {e.strip().lower() for e in (extra or []) if e.strip().lower() in supers})


def _filter(name: str, keep: List[str]) -> Dict[str, Any]:
    """Everything — except the kept super admins' accounts and sessions."""
    return {"email": {"$nin": keep}} if name in OWN else {}


def _counts(include_crm: bool, keep: List[str]) -> Dict[str, int]:
    out = {}
    for n in _scope(include_crm):
        c = _db[n].count_documents(_filter(n, keep))
        if c:
            out[n] = c
    return out


@router.get("/api/admin/reset/preview")
def preview(include_crm: bool = True, keep: List[str] = Query(default=[]),
            token_data: TokenData = Depends(require_super())):
    kept = _kept(token_data.email, keep)
    counts = _counts(include_crm, kept)
    return {
        "collections": counts,
        "total": sum(counts.values()),
        "businesses": _db.tenants.count_documents({}),
        "customers": _db.customers.count_documents({}),
        "logins_deleted": counts.get("users", 0),
        "kept_login": token_data.email,
        "kept_logins": kept,
        "super_admins": [{"email": u["email"], "you": u["email"] == token_data.email, "kept": u["email"] in kept}
                         for u in _db.users.find({"role": "super_admin"}, {"email": 1}).sort("email", 1)],
        "kept_settings": sorted(KEEP - {"platform_reset_tokens", "commune_cache", "system_jobs"}),
        "crm_included": include_crm,
        "crm": {n: _db[n].count_documents({}) for n in sorted(CRM) if _db[n].count_documents({})},
        "phrase": PHRASE,
    }


@router.get("/api/admin/reset/backup")
def backup(include_crm: bool = True, keep: List[str] = Query(default=[]),
           token_data: TokenData = Depends(require_super())):
    """Everything the reset would delete, as gzip'd extended JSON (bson
    json_util: dates and ids round-trip). The response carries the one-time
    token the reset asks for."""
    from bson import json_util
    kept = _kept(token_data.email, keep)
    data = {n: list(_db[n].find(_filter(n, kept))) for n in _scope(include_crm)}
    data = {k: v for k, v in data.items() if v}
    meta = {"made_at": _now().isoformat(), "by": token_data.email, "include_crm": include_crm, "kept": kept,
            "counts": {k: len(v) for k, v in data.items()}}
    raw = json_util.dumps({"meta": meta, "collections": data}, ensure_ascii=False).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(raw)
    token = secrets.token_urlsafe(24)
    _db.platform_reset_tokens.insert_one({"token": token, "email": token_data.email, "include_crm": include_crm, "kept": kept,
                                          "expires_at": _now() + TOKEN_TTL, "backup_bytes": buf.tell()})
    name = f"fidclic-sauvegarde-{_now().strftime('%Y%m%d-%H%M')}.json.gz"
    return StreamingResponse(io.BytesIO(buf.getvalue()), media_type="application/gzip", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Reset-Token": token, "Access-Control-Expose-Headers": "X-Reset-Token",
        "Cache-Control": "no-store"})


class ResetIn(BaseModel):
    token: str
    confirm: str
    include_crm: bool = True
    keep: List[str] = []


@router.post("/api/admin/reset")
def reset(body: ResetIn, request: Request, token_data: TokenData = Depends(require_super())):
    # The account itself, read from the database — not only the token's claim.
    me = _db.users.find_one({"email": token_data.email}) or {}
    if me.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Réservé au Super Admin.")
    if (body.confirm or "").strip() != PHRASE:
        raise HTTPException(status_code=400, detail=f"Tapez « {PHRASE} » pour confirmer.")
    tok = _db.platform_reset_tokens.find_one({"token": body.token, "email": token_data.email})
    exp = tok.get("expires_at") if tok else None
    if exp is not None and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if not tok or tok.get("used_at") or not exp or exp < _now():
        raise HTTPException(status_code=400, detail="Téléchargez d'abord la sauvegarde (valable 30 minutes), puis recommencez.")
    kept = _kept(token_data.email, body.keep)
    if bool(tok.get("include_crm")) != bool(body.include_crm) or sorted(tok.get("kept") or []) != kept:
        raise HTTPException(status_code=400, detail="La sauvegarde ne couvre pas le même périmètre : téléchargez-la à nouveau.")
    deleted: Dict[str, int] = {}
    for n in _scope(body.include_crm):
        r = _db[n].delete_many(_filter(n, kept))
        if r.deleted_count:
            deleted[n] = r.deleted_count
    # The kept super admins keep clean accounts: no shop attached.
    _db.users.update_many({"email": {"$in": kept}}, {"$set": {"tenant_id": None}})
    _db.platform_reset_tokens.update_one({"token": body.token}, {"$set": {"used_at": _now()}})
    # First line of the new journal: who wiped what, and when.
    try:
        import server as core
        core.log_audit("platform.reset", actor=token_data.email, actor_type="user", request=request,
                       meta={"deleted": deleted, "include_crm": body.include_crm, "kept": kept})
    except Exception:
        pass
    return {"ok": True, "deleted": deleted, "total": sum(deleted.values()), "kept_login": token_data.email,
            "kept_logins": kept}
