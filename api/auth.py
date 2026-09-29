import os
import bcrypt
import jwt
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import Request, HTTPException, Depends
from models import TokenData

# ─────────────────────────────────────────────────────────────────────
# JWT signing key.
#
# This used to be a hardcoded constant — in a PUBLIC GitHub repo. HS256 is
# symmetric, so that constant is all anyone needs to mint a valid token for
# any email and any role, including super_admin: full admin console, every
# tenant, every customer record, no password required.
#
# It now reads JWT_SECRET from the environment. The old constant remains
# ONLY as a fallback so that a deploy without the env var doesn't lock
# every existing user out mid-session — but it is a hole, not a default.
#
# TO CLOSE IT: set JWT_SECRET in Vercel (e.g. `openssl rand -hex 32`) and
# redeploy. Every current session is invalidated by the change, so users
# log in once more. That is the entire cost.
# ─────────────────────────────────────────────────────────────────────
_LEGACY_INSECURE_SECRET = "a3f8b2c1d4e5f67890abcdef12345678abcdef9087654321fedcba0987654321"
SECRET_KEY = os.environ.get("JWT_SECRET", "").strip() or _LEGACY_INSECURE_SECRET
if SECRET_KEY == _LEGACY_INSECURE_SECRET:
    print(
        "SECURITY WARNING: JWT_SECRET is not set — falling back to the secret "
        "committed to the public repository. Anyone can forge a super_admin "
        "token until this env var is set. Fix: openssl rand -hex 32 -> Vercel "
        "env JWT_SECRET -> redeploy."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 24 * 60

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

_session_check = None
_tenant_check = None
SUSPENDABLE = {"business_owner", "administrateur", "manager", "staff"}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def set_session_check(fn):
    global _session_check
    _session_check = fn


def set_tenant_check(fn):
    """features/admin_commerces.py: is this business suspended?"""
    global _tenant_check
    _tenant_check = fn


def _view_token(request: Request) -> Optional[str]:
    """« Accéder au compte » runs in its own tab with a read-only token in the
    Authorization header, while the super admin's own cookie still rides
    along: that header must win, or the tab would act as the super admin."""
    h = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not h.startswith("Bearer "):
        return None
    try:
        p = jwt.decode(h[7:], SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return h[7:] if p.get("view_only") else None


async def get_current_user_data(request: Request) -> TokenData:
    # Try cookie first (browser-based auth), then Authorization: Bearer header
    # (mobile / API clients). This makes the auth path more forgiving when
    # the browser refuses to send the cookie on a JSON POST.
    token = _view_token(request) or request.cookies.get("access_token")
    if not token:
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    if not token:
        # Verbose diagnostic so the staff workspace can show us EXACTLY what's
        # missing on a failed scan. Lists which cookies / headers came through.
        cookie_keys = list(request.cookies.keys())
        has_auth_hdr = bool(request.headers.get("authorization") or request.headers.get("Authorization"))
        raise HTTPException(
            status_code=401,
            detail=(
                "Not authenticated — no access_token cookie or Authorization header. "
                f"cookies_received={cookie_keys} · auth_header_present={has_auth_hdr} · "
                f"path={request.url.path}"
            ),
        )
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("role")
        tenant_id: str = payload.get("tenant_id")
        sid = payload.get("sid")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid auth credentials (no sub claim)")
        if payload.get("purpose"):
            # A 2FA challenge is not a login.
            raise HTTPException(status_code=401, detail="Invalid auth credentials")
        # « Déconnecter » on Paramètres › Sécurité ends a device at once.
        if _session_check is not None and not _session_check(email, sid):
            raise HTTPException(status_code=401, detail="Session terminée. Reconnectez-vous.")
        view_by = payload.get("view_by") if payload.get("view_only") else None
        if payload.get("view_only") and request.method not in READ_METHODS:
            raise HTTPException(status_code=403, detail="Mode lecture seule : aucune modification possible depuis cette vue.")
        if (not view_by and role in SUSPENDABLE and tenant_id and _tenant_check is not None
                and _tenant_check(tenant_id)):
            raise HTTPException(status_code=403, detail="Ce compte est suspendu. Contactez FidClic.")
        return TokenData(email=email, role=role, tenant_id=tenant_id, sid=sid, view_by=view_by)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {str(e)[:80]}")

# ─────────────────────────────────────────────────────────────────────
# Team accounts — administrateur, manager, staff — belong to a responsable
# who can switch them off, and each one only sees the establishments it was
# given. Both are read live on every call (features/team_access.py registers
# the lookup), so switching an account off or moving it to another shop takes
# effect at once, not when its 24-hour token runs out.
#
# "partial" scope = an account that covers only some of the shop's
# establishments. Until every data page filters by establishment, such an
# account is kept out of the data endpoints (SCOPE_PENDING) rather than
# shown the whole franchise. Endpoints that are safe for it opt in with
# partial_ok=True (the team page); endpoints open to staff (scan, the
# catalogue picker) act on one shop by nature and stay open.
# ─────────────────────────────────────────────────────────────────────
TEAM_ROLES = {"administrateur", "manager", "staff"}
_team_status = None


def set_team_status_lookup(fn):
    global _team_status
    _team_status = fn


def require_role(roles: list[str], partial_ok: bool = False):
    async def role_checker(token_data: TokenData = Depends(get_current_user_data)):
        if token_data.role not in roles:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        if token_data.role in TEAM_ROLES and _team_status is not None:
            status = _team_status(token_data.email) or {}
            if not status or status.get("active") is False:
                raise HTTPException(status_code=401, detail="Ce compte a été désactivé.")
            if (not partial_ok and "staff" not in roles
                    and status.get("scope") == "partial"):
                raise HTTPException(status_code=403, detail={
                    "code": "SCOPE_PENDING",
                    "message": "L'accès aux données de vos établissements arrive bientôt.",
                })
        return token_data
    return role_checker

def check_plan_feature(tenant_plan: str, feature_key: str):
    from models import PLAN_FEATURES
    features = PLAN_FEATURES.get(tenant_plan, {})
    if feature_key in ["csv_export", "geo_proximity"]:
        if not features.get(feature_key, False):
            raise HTTPException(status_code=403, detail="PLAN_FEATURE_DISABLED")
