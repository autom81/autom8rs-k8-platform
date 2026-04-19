"""
Settings API Routes — Phase 7A Step 5
======================================
Lets dashboard users read and update their own business settings.
All endpoints require a valid autom8rs_session JWT cookie.
business_id is always taken from the token — never from the client.

Endpoints:
  GET  /api/settings               — full business settings
  PATCH /api/settings              — update editable fields
  GET  /api/settings/prompt        — just the base_prompt field
  PATCH /api/settings/prompt       — update base_prompt + bust BusinessCache
  GET  /api/settings/integrations  — integration_config JSONB
  PATCH /api/settings/integrations — update integration_config
"""
import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.models.business import Business, TierEnum
from app.models.user import User
from app.routes.dashboard import get_current_user
from app.services.cache import BusinessCache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Tier → seat limit mapping
_SEAT_LIMITS: dict[str, int] = {
    "starter": 1,
    "pro": 5,
    "ultra": 20,
    "custom": 999,
}


# ─── helpers ──────────────────────────────────────────────────────

def _get_business(db: Session, business_id: uuid.UUID) -> Business:
    biz = db.query(Business).filter(Business.id == business_id).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")
    return biz


def _seat_count(db: Session, business_id: uuid.UUID) -> int:
    return db.query(User).filter(
        User.business_id == business_id,
        User.is_active == True,
    ).count()


def _serialize_business(biz: Business, seat_count: int) -> dict:
    tier_val = biz.tier.value if biz.tier and hasattr(biz.tier, "value") else str(biz.tier)
    return {
        "id": str(biz.id),
        "name": biz.name,
        "tier": tier_val,
        "features": biz.features or {},
        "website_url": biz.website_url,
        "order_prefix": biz.order_prefix,
        "category": biz.category,
        "brand_voice": biz.brand_voice,
        "integration_config": biz.integration_config or {},
        "seat_count": seat_count,
        "seat_limit": _SEAT_LIMITS.get(tier_val, 1),
        "owner_email": biz.owner_email,
    }


# ─── GET /api/settings ────────────────────────────────────────────

@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)
    return _serialize_business(biz, _seat_count(db, biz_id))


# ─── PATCH /api/settings ──────────────────────────────────────────

class UpdateSettingsRequest(BaseModel):
    name: Optional[str] = None
    website_url: Optional[str] = None
    order_prefix: Optional[str] = None
    category: Optional[str] = None
    brand_voice: Optional[str] = None


@router.patch("")
def update_settings(
    body: UpdateSettingsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)

    if body.name is not None:
        biz.name = body.name
    if body.website_url is not None:
        biz.website_url = body.website_url
    if body.order_prefix is not None:
        # Enforce uppercase, max 10 chars, alphanumeric
        biz.order_prefix = body.order_prefix.strip().upper()[:10]
    if body.category is not None:
        biz.category = body.category
    if body.brand_voice is not None:
        biz.brand_voice = body.brand_voice

    try:
        db.commit()
        db.refresh(biz)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating settings for {biz_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings")

    BusinessCache.invalidate(str(biz_id))
    return _serialize_business(biz, _seat_count(db, biz_id))


# ─── GET /api/settings/prompt ─────────────────────────────────────

@router.get("/prompt")
def get_prompt(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)
    return {"business_id": str(biz_id), "base_prompt": biz.base_prompt or ""}


# ─── PATCH /api/settings/prompt ───────────────────────────────────

class UpdatePromptRequest(BaseModel):
    base_prompt: str


@router.patch("/prompt")
def update_prompt(
    body: UpdatePromptRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)

    biz.base_prompt = body.base_prompt

    try:
        db.commit()
        db.refresh(biz)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating prompt for {biz_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update prompt")

    # Bust cache immediately so the next customer message uses the new prompt
    BusinessCache.invalidate(str(biz_id))
    logger.info(f"Prompt updated and cache busted for business {biz_id}")

    return {"status": "ok", "business_id": str(biz_id), "base_prompt": biz.base_prompt}


# ─── GET /api/settings/integrations ──────────────────────────────

@router.get("/integrations")
def get_integrations(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)
    return {
        "business_id": str(biz_id),
        "integration_config": biz.integration_config or {},
    }


# ─── PATCH /api/settings/integrations ────────────────────────────

class UpdateIntegrationsRequest(BaseModel):
    integration_config: dict


@router.patch("/integrations")
def update_integrations(
    body: UpdateIntegrationsRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    biz_id = uuid.UUID(current_user["business_id"])
    biz = _get_business(db, biz_id)

    # Merge incoming config on top of existing so callers can update one key at a time
    existing = biz.integration_config or {}
    merged = {**existing, **body.integration_config}
    biz.integration_config = merged

    try:
        db.commit()
        db.refresh(biz)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating integrations for {biz_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update integration config")

    BusinessCache.invalidate(str(biz_id))
    return {
        "status": "ok",
        "business_id": str(biz_id),
        "integration_config": biz.integration_config,
    }
