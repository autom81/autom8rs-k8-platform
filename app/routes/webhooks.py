"""
Meta Webhook Handler
Receives all incoming messages from WhatsApp, Instagram, and Facebook Messenger.
Routes them to the core message handler.
"""
import logging

from fastapi import APIRouter, Request, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.meta import (
    verify_webhook_signature,
    parse_whatsapp_webhook,
    parse_messenger_webhook,
)
from app.services.message_handler import handle_message
from app.models.business import Business

logger = logging.getLogger(__name__)

router = APIRouter()


def _lookup_business_by_phone_number_id(phone_number_id: str, db: Session):
    """Find the business that owns this WhatsApp phone number."""
    return db.query(Business).filter(
        Business.meta_phone_number_id == phone_number_id
    ).first()


def _lookup_business_by_page_id(page_id: str, db: Session):
    """
    Find the business that owns this Facebook Page.
    For now, we use meta_waba_id to also store the page ID.
    You may want a separate field or mapping table later.
    """
    return db.query(Business).filter(
        Business.meta_waba_id == page_id
    ).first()


# ============================================================
# WEBHOOK VERIFICATION (GET) — Meta sends this to confirm URL
# ============================================================

@router.get("/api/meta/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return int(challenge)

    logger.warning(f"Webhook verification failed: mode={mode}, token={token}")
    raise HTTPException(status_code=403, detail="Verification failed")


# ============================================================
# WEBHOOK RECEIVER (POST) — All incoming messages land here
# ============================================================

@router.post("/api/meta/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Read raw body for signature verification
    raw_body = await request.body()
    body = await request.json()

    # Verify signature (if META_APP_SECRET is set)
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.META_APP_SECRET and not verify_webhook_signature(raw_body, signature):
        logger.warning("Invalid webhook signature — rejecting")
        raise HTTPException(status_code=403, detail="Invalid signature")

    # Determine if this is WhatsApp or Messenger/Instagram
    # WhatsApp webhooks have "entry[].changes[].value.messaging_product"
    # Messenger/IG webhooks have "entry[].messaging[]"
    object_type = body.get("object", "")

    if object_type == "whatsapp_business_account":
        messages = parse_whatsapp_webhook(body)
        for msg in messages:
            business = _lookup_business_by_phone_number_id(
                msg["phone_number_id"], db
            )
            if not business:
                logger.warning(
                    f"No business found for phone_number_id={msg['phone_number_id']}"
                )
                continue

            # Build metadata
            metadata = {}
            if msg.get("referral"):
                metadata["source"] = "ctwa_ad"
                metadata["referral"] = msg["referral"]

            # Process in background so we return 200 to Meta quickly
            background_tasks.add_task(
                handle_message,
                business_id=str(business.id),
                channel="whatsapp",
                external_user_id=msg["sender_id"],
                message_text=msg["message_text"],
                media_url=msg.get("media_url"),
                media_type=msg.get("media_type"),
                message_metadata=metadata,
                phone_number_id=msg["phone_number_id"],
                db=db,
            )

    elif object_type == "page" or object_type == "instagram":
        messages = parse_messenger_webhook(body)
        for msg in messages:
            # Determine channel
            channel = "instagram" if object_type == "instagram" else "facebook"
            msg["channel"] = channel

            business = _lookup_business_by_page_id(
                msg.get("recipient_id", ""), db
            )
            if not business:
                logger.warning(
                    f"No business found for page_id={msg.get('recipient_id')}"
                )
                continue

            metadata = {}
            if msg.get("referral"):
                metadata["source"] = "ctwa_ad"
                metadata["referral"] = msg["referral"]

            background_tasks.add_task(
                handle_message,
                business_id=str(business.id),
                channel=channel,
                external_user_id=msg["sender_id"],
                message_text=msg["message_text"],
                media_url=msg.get("media_url"),
                media_type=msg.get("media_type"),
                message_metadata=metadata,
                phone_number_id=business.meta_phone_number_id,
                db=db,
            )

    else:
        logger.info(f"Unhandled webhook object type: {object_type}")

    # Always return 200 quickly — Meta will retry on non-200
    return {"status": "received"}