"""
Sign in with Google / Sign in with Apple.
Status: 🟢 Core (boots as "not configured" until the env vars are set).
Mounts at: /api/auth/oauth/config, /api/auth/oauth/google, /api/auth/oauth/apple

HOW IT WORKS (no redirect dance, no server-side OAuth secret)
    Both providers can hand the BROWSER a signed ID token:
      - Google Identity Services → `credential` (a JWT) in the button callback
      - Apple JS SDK (usePopup)  → `authorization.id_token` (a JWT)
    The browser POSTs that JWT here. We verify the signature against the
    provider's public JWKS, check issuer / audience / expiry, and only then
    trust the email inside. Same session cookie as password login afterwards.

    Verification uses PyJWT's PyJWKClient (already a dependency, with
    `cryptography` for RS256). Keys are cached per process; Vercel functions
    are warm for minutes, so this is one network call per cold start.

ACCOUNT RULES
    - Email is the identity. An existing password account with the same
      (verified) email is LINKED, not duplicated: we record the provider `sub`
      and let both methods log in. Google marks email_verified; Apple emails
      are verified by construction (or a private relay we still trust).
    - A brand-new user becomes a business_owner with a tenant stub and
      onboarding_status="company", exactly like /api/auth/register — but
      terms_accepted_at stays empty: the CGU/DPA consent is collected on the
      company step, which refuses to complete without it.
    - Apple only sends the name on the FIRST authorisation. The frontend
      forwards it; we store it if we have nothing better.

ENV
    GOOGLE_CLIENT_ID   OAuth 2.0 Web client ID (console.cloud.google.com)
    APPLE_CLIENT_ID    Services ID (developer.apple.com → Identifiers → Services IDs)
                       e.g. "com.fidclic.web" — NOT the App ID.
    APPLE_REDIRECT_URI Must match the Services ID "Return URLs" exactly,
                       e.g. https://app.fidclic.com/login  (popup flow still needs it)
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(tags=["oauth"])
_db = None

GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
APPLE_JWKS = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"

_jwk_clients: Dict[str, PyJWKClient] = {}


def init(db):
    global _db
    _db = db
    try:
        _db.users.create_index([("oauth.google", 1)], sparse=True)
        _db.users.create_index([("oauth.apple", 1)], sparse=True)
    except Exception:
        pass


def _google_client_id() -> str:
    return os.getenv("GOOGLE_CLIENT_ID", "").strip()


def _apple_client_id() -> str:
    return os.getenv("APPLE_CLIENT_ID", "").strip()


def _jwks(url: str) -> PyJWKClient:
    if url not in _jwk_clients:
        _jwk_clients[url] = PyJWKClient(url, cache_keys=True)
    return _jwk_clients[url]


def _verify(token: str, jwks_url: str, audience: str, issuers) -> Dict[str, Any]:
    try:
        key = _jwks(jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audience,
                            options={"require": ["exp", "iat", "sub"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Jeton expiré — réessayez.")
    except Exception as e:  # noqa: BLE001 — any verification failure is a 401, never a 500
        raise HTTPException(status_code=401, detail=f"Jeton invalide ({type(e).__name__}).")
    if claims.get("iss") not in issuers:
        raise HTTPException(status_code=401, detail="Émetteur du jeton inattendu.")
    return claims


class GoogleLogin(BaseModel):
    credential: Optional[str] = None     # ID token (Google-rendered button / One Tap)
    access_token: Optional[str] = None   # OAuth2 token client (our own styled button)


class AppleLogin(BaseModel):
    id_token: str
    first_name: Optional[str] = None   # only present on the very first Apple authorisation
    last_name: Optional[str] = None


@router.get("/api/auth/oauth/config")
def oauth_config():
    """Public IDs the frontend needs to initialise the provider SDKs.
    A missing ID hides that button — the page never shows a dead control."""
    return {
        "google_client_id": _google_client_id() or None,
        "apple_client_id": _apple_client_id() or None,
        "apple_redirect_uri": os.getenv("APPLE_REDIRECT_URI", "").strip() or None,
    }


def _upsert_user(provider: str, sub: str, email: str, first_name: Optional[str],
                 last_name: Optional[str], request: Request, response: Response) -> Dict[str, Any]:
    import server as core

    email = email.strip().lower()
    now = datetime.now(timezone.utc)
    user = _db.users.find_one({"email": email})
    is_new = user is None
    if user:
        # Link (or re-link) the provider on an existing account. Never touch
        # the password, role or tenant of an account that already exists.
        patch: Dict[str, Any] = {f"oauth.{provider}": sub}
        if first_name and not user.get("first_name"):
            patch["first_name"] = first_name
        if last_name and not user.get("last_name"):
            patch["last_name"] = last_name
        _db.users.update_one({"email": email}, {"$set": patch})
        user = _db.users.find_one({"email": email})
    else:
        tenant_id = str(uuid.uuid4())
        display = " ".join(x for x in [first_name, last_name] if x).strip() or email.split("@")[0]
        tenant = core.Tenant(
            id=tenant_id, slug=core._unique_slug(display), name=display, plan="silver",
            address="", onboarding_status="company",
        ).model_dump()
        tenant["subscription_status"] = "onboarding"
        tenant["owner_name"] = display
        _db.tenants.insert_one(tenant)
        user = core.UserInDB(
            email=email, role="business_owner", tenant_id=tenant_id,
            hashed_password=None, first_name=first_name, last_name=last_name,
            auth_provider=provider,
        ).model_dump()
        user["oauth"] = {provider: sub}
        _db.users.insert_one(user)

    core.log_audit("auth.oauth_login", actor=email, actor_type="user",
                   tenant_id=user.get("tenant_id"), request=request,
                   meta={"provider": provider, "new_account": is_new, "role": user["role"]})
    session = core._issue_session(response, user)
    return {**session, "is_new": is_new, "terms_accepted": bool(user.get("terms_accepted_at"))}


@router.post("/api/auth/oauth/google")
def google_login(body: GoogleLogin, request: Request, response: Response):
    cid = _google_client_id()
    if not cid:
        raise HTTPException(status_code=503, detail="Connexion Google non configurée (GOOGLE_CLIENT_ID).")
    if body.access_token:
        claims = _google_claims_from_access_token(body.access_token, cid)
    elif body.credential:
        claims = _verify(body.credential, GOOGLE_JWKS, cid, GOOGLE_ISSUERS)
    else:
        raise HTTPException(status_code=400, detail="credential ou access_token requis.")
    if not claims.get("email") or not claims.get("email_verified", False):
        raise HTTPException(status_code=401, detail="Adresse email Google non vérifiée.")
    return _upsert_user("google", claims["sub"], claims["email"],
                        claims.get("given_name"), claims.get("family_name"), request, response)


def _google_claims_from_access_token(token: str, cid: str) -> Dict[str, Any]:
    """Our own 'Continuer avec Google' button uses the OAuth2 token client
    (google.accounts.oauth2.initTokenClient) because Google's ID-token flow
    only works through Google's rendered button. An access token is opaque,
    so we ask Google two things: tokeninfo (is it ours? → aud must be OUR
    client id, otherwise any site's Google token could log into FidClic)
    and userinfo (who is it?)."""
    import urllib.request, urllib.parse, json
    try:
        with urllib.request.urlopen(
            "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"access_token": token}), timeout=8
        ) as r:
            info = json.load(r)
        if info.get("aud") != cid:
            raise HTTPException(status_code=401, detail="Jeton Google émis pour une autre application.")
        req = urllib.request.Request("https://www.googleapis.com/oauth2/v3/userinfo",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            u = json.load(r)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail=f"Jeton Google invalide ({type(e).__name__}).")
    return {"sub": u.get("sub"), "email": u.get("email"), "email_verified": bool(u.get("email_verified")),
            "given_name": u.get("given_name"), "family_name": u.get("family_name")}


@router.post("/api/auth/oauth/apple")
def apple_login(body: AppleLogin, request: Request, response: Response):
    cid = _apple_client_id()
    if not cid:
        raise HTTPException(status_code=503, detail="Connexion Apple non configurée (APPLE_CLIENT_ID).")
    claims = _verify(body.id_token, APPLE_JWKS, cid, {APPLE_ISSUER})
    email = claims.get("email")
    if not email:
        # Happens if the user hid their email AND revoked the relay — rare.
        raise HTTPException(status_code=401, detail="Apple n'a pas transmis d'adresse email.")
    return _upsert_user("apple", claims["sub"], email, body.first_name, body.last_name,
                        request, response)
