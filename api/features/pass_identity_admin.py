"""
Super admin › a business's own Apple Pass Type ID (user, 2026-10-30: the
cards of every FidClic business sat in one stack in Apple Wallet).

    GET  /api/admin/commerces/{tid}/pass-identity          status (never the key)
    POST /api/admin/commerces/{tid}/pass-identity          manual upload — the
         fallback to the automatic creation by the App Store Connect API
    POST /api/admin/commerces/{tid}/pass-identity/active   on/off for NEW cards

Uploading or switching is the Super Admin's alone: a certificate signs every
card of the business.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth import TokenData
from features.platform_access import require_admin, require_super
from services import pass_identity as PI

router = APIRouter(tags=["admin"])
_db = None


def init(db):
    global _db
    _db = db
    PI.init(db)


class IdentityIn(BaseModel):
    pass_type_id: str
    certificate_pem: str
    key_pem: str


class ActiveIn(BaseModel):
    active: bool


def _tenant(tid: str) -> None:
    if not _db.tenants.find_one({"id": tid}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Commerce introuvable.")


def _audit(action: str, token_data: TokenData, tid: str, request: Optional[Request], meta: dict) -> None:
    try:
        import server as core
        core.log_audit(action, actor=token_data.email, actor_type="user", target=tid, tenant_id=tid,
                       request=request, meta=meta)
    except Exception as exc:                       # noqa: BLE001
        print(f"pass identity: audit not kept ({exc})")


@router.get("/api/admin/commerces/{tid}/pass-identity")
def identity_status(tid: str, token_data: TokenData = Depends(require_admin("commerces"))):
    _tenant(tid)
    return PI.status(tid)


@router.post("/api/admin/commerces/{tid}/pass-identity")
def identity_upload(tid: str, body: IdentityIn, request: Request = None,
                    token_data: TokenData = Depends(require_super())):
    _tenant(tid)
    try:
        st = PI.save(tid, body.pass_type_id, body.certificate_pem, body.key_pem, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit("admin.pass_identity.upload", token_data, tid, request,
           {"pass_type_id": st["pass_type_id"], "expires_at": st["expires_at"]})
    return st


@router.post("/api/admin/commerces/{tid}/pass-identity/active")
def identity_active(tid: str, body: ActiveIn, request: Request = None,
                    token_data: TokenData = Depends(require_super())):
    _tenant(tid)
    try:
        st = PI.set_active(tid, body.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    _audit("admin.pass_identity.active", token_data, tid, request, {"active": body.active})
    return st
