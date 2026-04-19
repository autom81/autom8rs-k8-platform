"""
Auth Service
============
Password hashing (bcrypt via passlib) and JWT creation/validation (python-jose).

JWT payload shape matches what the Next.js dashboard expects:
  user_id, business_id, email, full_name, business_name,
  role, tier, scheduling_enabled, permissions
"""
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.business import Business

# ── Password hashing ──────────────────────────────────────────────

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── JWT ───────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """Low-level: encode any dict into a signed JWT with expiry."""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.JWT_EXPIRY_HOURS)
    payload["exp"] = expire
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_user_token(user: "User", business: "Business") -> str:
    """
    Build the full JWT payload for a dashboard login and sign it.

    The dashboard JWTPayload interface expects exactly these fields:
      user_id, business_id, email, full_name, business_name,
      role, tier, scheduling_enabled, permissions
    """
    features: dict = business.features or {}
    tier_value = business.tier.value if hasattr(business.tier, "value") else str(business.tier)

    payload = {
        "user_id": str(user.id),
        "business_id": str(user.business_id),
        "email": user.email,
        "full_name": user.full_name or "",
        "business_name": business.name or "",
        "role": user.role,
        "tier": tier_value,
        "scheduling_enabled": bool(features.get("scheduling_enabled", False)),
        "permissions": user.permissions or {
            "can_reply": True,
            "can_manage_products": False,
            "can_manage_orders": False,
            "can_view_analytics": False,
            "can_edit_settings": False,
        },
    }
    return create_access_token(payload)


def decode_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT. Returns None on any error."""
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
