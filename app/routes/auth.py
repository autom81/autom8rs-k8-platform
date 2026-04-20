"""
Auth Routes — Phase 7A
======================
POST /auth/login    — email + password → JWT in httpOnly cookie
POST /auth/logout   — clear the cookie
GET  /auth/me       — decode cookie → return user + business info
POST /auth/refresh  — reissue JWT if current token is valid
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.business import Business
from app.services.auth_service import (
    verify_password,
    create_user_token,
    decode_token,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _preflight_response() -> Response:
    """Return a bare 200 for OPTIONS preflight — CORSMiddleware adds the headers."""
    return Response(status_code=200)

# ── Cookie helpers ────────────────────────────────────────────────

COOKIE_NAME = "autom8rs_session"
COOKIE_MAX_AGE = settings.JWT_EXPIRY_HOURS * 3600


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        secure=True,   # HTTPS only — set COOKIE_SECURE=false in .env for local dev if needed
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/", samesite="lax")


# ── Pydantic schemas ──────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    user_id: str
    business_id: str
    email: str
    full_name: Optional[str]
    business_name: Optional[str]
    role: str
    tier: str
    scheduling_enabled: bool
    permissions: dict


# ── Shared: resolve user from cookie token ────────────────────────

def _get_user_and_business(
    token: Optional[str],
    db: Session,
) -> tuple[User, Business]:
    """Decode token from cookie, validate, and return (User, Business)."""
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Malformed token")

    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Malformed token")

    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    business = db.query(Business).filter(Business.id == user.business_id).first()
    if not business:
        raise HTTPException(status_code=500, detail="Business record missing")

    return user, business


def _user_response(user: User, business: Business) -> dict:
    features: dict = business.features or {}
    tier_value = business.tier.value if hasattr(business.tier, "value") else str(business.tier)
    return {
        "user_id": str(user.id),
        "business_id": str(user.business_id),
        "email": user.email,
        "full_name": user.full_name,
        "business_name": business.name,
        "role": user.role,
        "tier": tier_value,
        "scheduling_enabled": bool(features.get("scheduling_enabled", False)),
        "permissions": user.permissions or {},
    }


# ── POST /auth/login ──────────────────────────────────────────────

@router.options("/login", include_in_schema=False)
def options_login():
    return _preflight_response()


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Validate email + password against the users table.
    On success: set JWT in httpOnly cookie and return user info.
    """
    email = body.email.lower().strip()

    user = db.query(User).filter(User.email == email).first()

    # Constant-time failure — always verify even when user not found
    dummy_hash = "$2b$12$KIXTlu8lmfAMwvYB/rFfB.zEFb/XFxTqFNZG8OLd0jI9dYmGTMpAe"
    password_to_check = user.password_hash if user else dummy_hash

    if not verify_password(body.password, password_to_check) or not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    business = db.query(Business).filter(Business.id == user.business_id).first()
    if not business:
        logger.error(f"Business missing for user {user.id}")
        raise HTTPException(status_code=500, detail="Account configuration error")

    token = create_user_token(user, business)
    _set_session_cookie(response, token)

    # Record login timestamp
    try:
        user.last_login = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()

    logger.info(f"User {user.email} logged in (business: {business.name})")
    return {"status": "ok", **_user_response(user, business)}


# ── POST /auth/logout ─────────────────────────────────────────────

@router.options("/logout", include_in_schema=False)
def options_logout():
    return _preflight_response()


@router.post("/logout")
def logout(response: Response):
    """Clear the session cookie."""
    _clear_session_cookie(response)
    return {"status": "ok", "message": "Logged out"}


# ── GET /auth/me ──────────────────────────────────────────────────

@router.options("/me", include_in_schema=False)
def options_me():
    return _preflight_response()


@router.get("/me", response_model=UserResponse)
def me(
    autom8rs_session: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Decode the session cookie and return fresh user + business info from DB.
    Used by the dashboard on every page load to confirm auth state.
    """
    user, business = _get_user_and_business(autom8rs_session, db)
    return _user_response(user, business)


# ── POST /auth/refresh ────────────────────────────────────────────

@router.options("/refresh", include_in_schema=False)
def options_refresh():
    return _preflight_response()


@router.post("/refresh")
def refresh(
    response: Response,
    autom8rs_session: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
):
    """
    Reissue a fresh JWT if the current token is valid.
    Called by the dashboard before expiry to extend the session.
    """
    user, business = _get_user_and_business(autom8rs_session, db)
    token = create_user_token(user, business)
    _set_session_cookie(response, token)
    logger.info(f"Token refreshed for {user.email}")
    return {"status": "ok", "message": "Session refreshed"}
