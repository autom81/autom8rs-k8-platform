"""
Admin API Routes — Phase 7A Step 5
====================================
Platform-owner-only routes for managing all client accounts.

Auth: requires a valid JWT cookie WHERE role='owner' AND business_id matches
AUTOM8RS_MASTER_BUSINESS_ID from config (set in .env). Raises 403 otherwise.

Endpoints:
  GET  /admin/clients              — list all businesses with monthly stats
  POST /admin/clients              — create new business + owner user account
  GET  /admin/clients/{id}         — full detail: settings, prompt, token usage, stats
  PATCH /admin/clients/{id}/prompt — update base_prompt + bust cache
  PATCH /admin/clients/{id}/tier   — change tier
  GET  /admin/system/health        — API / DB / Redis status + migration version
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.database import get_db
from app.models.business import Business, TierEnum
from app.models.conversation import Conversation, Message
from app.models.lead import Lead, Order, OrderStatusEnum
from app.models.user import User
from app.routes.dashboard import get_current_user
from app.services.auth_service import hash_password
from app.services.cache import BusinessCache, cache_health_check, redis_client, REDIS_AVAILABLE

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ═══════════════════════════════════════════════════════════════════
# ADMIN AUTH DEPENDENCY
# ═══════════════════════════════════════════════════════════════════

def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Extends get_current_user with two additional checks:
      1. role must be 'owner'
      2. business_id must match AUTOM8RS_MASTER_BUSINESS_ID (when configured)
    Raises 403 for anything that doesn't pass.
    """
    if current_user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Admin access required")

    master_id = app_settings.AUTOM8RS_MASTER_BUSINESS_ID
    if master_id and current_user.get("business_id") != master_id:
        raise HTTPException(status_code=403, detail="Admin access required")

    return current_user


# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def _month_start() -> datetime:
    n = datetime.now(timezone.utc)
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def _seat_count(db: Session, business_id: uuid.UUID) -> int:
    return db.query(User).filter(
        User.business_id == business_id,
        User.is_active == True,
    ).count()


_TIER_COST_PER_CONVO_USD = {
    "starter": 0.0,    # Gemma is free
    "pro": 0.0,        # Gemma is free
    "ultra": 0.005,    # Rough Claude Sonnet blended cost per conversation
    "custom": 0.005,
}


def _estimate_monthly_cost(tier: str, conversations: int) -> float:
    rate = _TIER_COST_PER_CONVO_USD.get(tier, 0.0)
    return round(rate * conversations, 4)


def _tier_val(biz: Business) -> str:
    return biz.tier.value if biz.tier and hasattr(biz.tier, "value") else str(biz.tier)


def _serialize_client_summary(biz: Business, db: Session) -> dict:
    month = _month_start()
    tier = _tier_val(biz)

    convos_this_month = db.query(func.count(Conversation.id)).filter(
        Conversation.business_id == biz.id,
        Conversation.started_at >= month,
    ).scalar() or 0

    orders_this_month = db.query(func.count(Order.id)).filter(
        Order.business_id == biz.id,
        Order.created_at >= month,
        Order.status != OrderStatusEnum.cancelled,
    ).scalar() or 0

    return {
        "id": str(biz.id),
        "business_name": biz.name,
        "tier": tier,
        "seat_count": _seat_count(db, biz.id),
        "conversations_this_month": convos_this_month,
        "orders_this_month": orders_this_month,
        "estimated_monthly_cost_usd": _estimate_monthly_cost(tier, convos_this_month),
        "created_at": biz.created_at.isoformat() if biz.created_at else None,
    }


def _estimate_token_usage(db: Session, business_id: uuid.UUID) -> dict:
    """
    Approximate token usage this month from message content lengths.
    Tokens ≈ characters / 4  (rough but standard rule-of-thumb).
    Cost only applies to Ultra/Custom (Claude Sonnet); others use free Gemma.
    """
    month = _month_start()

    # Total chars in all messages this month for this business
    total_chars = db.query(func.sum(func.length(Message.content))).join(
        Conversation, Message.conversation_id == Conversation.id
    ).filter(
        Conversation.business_id == business_id,
        Message.timestamp >= month,
    ).scalar() or 0

    assistant_chars = db.query(func.sum(func.length(Message.content))).join(
        Conversation, Message.conversation_id == Conversation.id
    ).filter(
        Conversation.business_id == business_id,
        Message.timestamp >= month,
        Message.role == "assistant",
    ).scalar() or 0

    prompt_tokens = int(total_chars / 4)
    completion_tokens = int(assistant_chars / 4)

    # Cost only meaningful for ultra/custom tiers (Claude usage)
    # Claude Sonnet 4.5: ~$3/MTok input, ~$15/MTok output
    biz = db.query(Business).filter(Business.id == business_id).first()
    tier = _tier_val(biz) if biz else "starter"
    if tier in ("ultra", "custom"):
        cost = (prompt_tokens / 1_000_000 * 3.0) + (completion_tokens / 1_000_000 * 15.0)
    else:
        cost = 0.0

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": round(cost, 6),
    }


def _serialize_client_detail(biz: Business, db: Session) -> dict:
    month = _month_start()
    tier = _tier_val(biz)
    features = biz.features or {}

    stats = {
        "conversations": db.query(func.count(Conversation.id)).filter(
            Conversation.business_id == biz.id,
            Conversation.started_at >= month,
        ).scalar() or 0,
        "orders": db.query(func.count(Order.id)).filter(
            Order.business_id == biz.id,
            Order.created_at >= month,
            Order.status != OrderStatusEnum.cancelled,
        ).scalar() or 0,
        "leads": db.query(func.count(Lead.id)).filter(
            Lead.business_id == biz.id,
            Lead.created_at >= month,
        ).scalar() or 0,
    }

    return {
        "id": str(biz.id),
        "business_name": biz.name,
        "tier": tier,
        "seat_count": _seat_count(db, biz.id),
        "system_prompt": biz.base_prompt or "",
        "whatsapp_number": biz.meta_phone_number_id,
        "instagram_handle": biz.instagram_account_id,
        "facebook_page_id": biz.meta_waba_id,
        "website_url": biz.website_url,
        "order_prefix": biz.order_prefix,
        "features": {
            "ecommerce_enabled": bool(features.get("ecommerce_enabled", True)),
            "scheduling_enabled": bool(features.get("scheduling_enabled", False)),
            "media_sync_enabled": bool(features.get("media_sync_enabled", True)),
        },
        "token_usage": _estimate_token_usage(db, biz.id),
        "stats": stats,
        "created_at": biz.created_at.isoformat() if biz.created_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# GET /admin/clients
# ═══════════════════════════════════════════════════════════════════

@router.get("/clients")
def list_clients(
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    businesses = db.query(Business).order_by(Business.created_at.desc()).all()
    return {
        "clients": [_serialize_client_summary(b, db) for b in businesses],
        "total": len(businesses),
    }


# ═══════════════════════════════════════════════════════════════════
# POST /admin/clients
# ═══════════════════════════════════════════════════════════════════

class CreateClientRequest(BaseModel):
    business_name: str
    owner_email: str
    owner_password: str
    owner_full_name: Optional[str] = None
    tier: str = "starter"
    order_prefix: Optional[str] = None
    category: Optional[str] = None


@router.post("/clients", status_code=201)
def create_client(
    body: CreateClientRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    # Validate tier
    try:
        tier_enum = TierEnum(body.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {body.tier}")

    # Ensure email is unique across users
    existing = db.query(User).filter(User.email == body.owner_email.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="A user with that email already exists")

    biz_id = uuid.uuid4()
    user_id = uuid.uuid4()

    biz = Business(
        id=biz_id,
        name=body.business_name,
        owner_email=body.owner_email.lower().strip(),
        tier=tier_enum,
        order_prefix=(body.order_prefix or "ORD").upper()[:10],
        category=body.category,
        features={
            "ecommerce_enabled": True,
            "scheduling_enabled": False,
            "media_sync_enabled": True,
        },
    )
    db.add(biz)

    owner = User(
        id=user_id,
        business_id=biz_id,
        email=body.owner_email.lower().strip(),
        password_hash=hash_password(body.owner_password),
        full_name=body.owner_full_name,
        role="owner",
        permissions={
            "can_reply": True,
            "can_manage_products": True,
            "can_manage_orders": True,
            "can_view_analytics": True,
            "can_edit_settings": True,
        },
        is_active=True,
    )
    db.add(owner)

    try:
        db.commit()
        db.refresh(biz)
        db.refresh(owner)
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating client: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create client account")

    logger.info(f"Admin created new client: {biz.name} (id={biz_id})")
    return {
        "status": "created",
        "business": _serialize_client_detail(biz, db),
        "owner": {
            "id": str(owner.id),
            "email": owner.email,
            "full_name": owner.full_name,
            "role": owner.role,
        },
    }


# ═══════════════════════════════════════════════════════════════════
# GET /admin/clients/{client_id}
# ═══════════════════════════════════════════════════════════════════

@router.get("/clients/{client_id}")
def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client ID")

    biz = db.query(Business).filter(Business.id == cid).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Client not found")

    return _serialize_client_detail(biz, db)


# ═══════════════════════════════════════════════════════════════════
# PATCH /admin/clients/{client_id}/prompt
# ═══════════════════════════════════════════════════════════════════

class UpdatePromptRequest(BaseModel):
    system_prompt: str


@router.patch("/clients/{client_id}/prompt")
def update_client_prompt(
    client_id: str,
    body: UpdatePromptRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client ID")

    biz = db.query(Business).filter(Business.id == cid).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Client not found")

    biz.base_prompt = body.system_prompt

    try:
        db.commit()
        db.refresh(biz)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating prompt for {cid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update prompt")

    BusinessCache.invalidate(str(cid))
    logger.info(f"Admin updated prompt for business {cid}")
    return {"status": "ok", "business_id": client_id}


# ═══════════════════════════════════════════════════════════════════
# PATCH /admin/clients/{client_id}/tier
# ═══════════════════════════════════════════════════════════════════

class UpdateTierRequest(BaseModel):
    tier: str


@router.patch("/clients/{client_id}/tier")
def update_client_tier(
    client_id: str,
    body: UpdateTierRequest,
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    try:
        cid = uuid.UUID(client_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid client ID")

    try:
        tier_enum = TierEnum(body.tier)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {body.tier}")

    biz = db.query(Business).filter(Business.id == cid).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Client not found")

    old_tier = _tier_val(biz)
    biz.tier = tier_enum

    try:
        db.commit()
        db.refresh(biz)
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating tier for {cid}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update tier")

    BusinessCache.invalidate(str(cid))
    logger.info(f"Admin changed tier for {biz.name}: {old_tier} → {body.tier}")
    return {"status": "ok", "business_id": client_id, "tier": body.tier}


# ═══════════════════════════════════════════════════════════════════
# GET /admin/system/health
# ═══════════════════════════════════════════════════════════════════

@router.get("/system/health")
def system_health(
    db: Session = Depends(get_db),
    _admin: dict = Depends(get_admin_user),
):
    checked_at = datetime.now(timezone.utc).isoformat()

    # ── API ───────────────────────────────────────────────────────
    api_status = "ok"

    # ── Database ──────────────────────────────────────────────────
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
        db_status = "error"

    # ── Redis ─────────────────────────────────────────────────────
    if REDIS_AVAILABLE and redis_client:
        try:
            redis_client.ping()
            redis_status = "ok"
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            redis_status = "error"
    else:
        redis_status = "error"

    # ── Alembic migration version ─────────────────────────────────
    migration_version = "unknown"
    try:
        result = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        row = result.scalar()
        migration_version = row or "no_migrations_applied"
    except Exception:
        migration_version = "alembic_not_initialized"

    return {
        "api": api_status,
        "database": db_status,
        "redis": redis_status,
        "migration_version": migration_version,
        "checked_at": checked_at,
    }
