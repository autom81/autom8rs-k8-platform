"""
Media Tool - Phase 6
=====================

Sends product images/videos from the media library to customers.
Used when customer asks things like:
- "Do you have a video of the blender?"
- "Send me a picture of X"
- "What does it look like?"

The media library is populated by Instagram posts with #AutoM8 hashtag.

Preference order:
1. Video (if available and requested)
2. Image (fallback or if specifically requested)
3. None (inform customer no media available)
"""
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.media import MediaLibrary, MediaTypeEnum, MediaStatusEnum
from app.models.business import Product
from app.services.cache import ProductCache

logger = logging.getLogger(__name__)


def send_product_media(
    db: Session,
    conversation: Conversation,
    product_name: str,
    media_type: str = "any",
) -> dict:
    """
    TOOL: Get media for a product to send to customer.
    
    Returns media URL which message_handler will send via Meta API.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        product_name: Name of product to get media for
        media_type: "image", "video", or "any" (default)
    
    Returns:
        dict with media_url, media_type, caption, or not_found status
    """
    try:
        # Find the product first
        product = ProductCache.find_by_name(
            db,
            conversation.business_id,
            product_name
        )
        
        if not product:
            return {
                "success": False,
                "found": False,
                "message": (
                    f"I couldn't find '{product_name}' in our inventory. "
                    f"Can you check the product name?"
                )
            }
        
        # Query media library for linked media
        query = db.query(MediaLibrary).filter(
            MediaLibrary.business_id == conversation.business_id,
            MediaLibrary.linked_product_id == uuid.UUID(product['id']),
            MediaLibrary.status == MediaStatusEnum.active,
        )
        
        # Filter by media type if specified
        if media_type == "video":
            query = query.filter(MediaLibrary.media_type == MediaTypeEnum.video)
        elif media_type == "image":
            query = query.filter(MediaLibrary.media_type == MediaTypeEnum.image)
        
        # Get all matching media
        all_media = query.order_by(MediaLibrary.posted_at.desc().nullslast()).all()
        
        if not all_media:
            return {
                "success": False,
                "found": False,
                "product_name": product['name'],
                "message": (
                    f"I don't have a photo or video of the {product['name']} to share right now. "
                    f"Would you like me to describe it instead?"
                )
            }
        
        # Preference: videos first (if media_type is "any"), then images
        if media_type == "any":
            # Try to find a video first
            video = next((m for m in all_media if m.media_type == MediaTypeEnum.video), None)
            if video:
                selected = video
            else:
                selected = all_media[0]
        else:
            selected = all_media[0]
        
        logger.info(
            f"Sending {selected.media_type.value} for {product['name']} "
            f"(media_id={selected.id})"
        )
        
        # Format caption
        caption = selected.caption or f"Here's our {product['name']}!"
        
        return {
            "success": True,
            "found": True,
            "product_name": product['name'],
            "media_id": str(selected.id),
            "media_type": selected.media_type.value,
            "media_url": selected.media_url,
            "thumbnail_url": selected.thumbnail_url,
            "caption": caption,
            "source_platform": selected.source_platform.value if selected.source_platform else None,
            "source_url": selected.source_url,
            # The message_handler will send the media via Meta API
            # This message is a fallback text response for the LLM
            "message": f"Here's the {selected.media_type.value} of our {product['name']}! 📸"
        }
        
    except Exception as e:
        logger.error(f"Error getting product media: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": (
                "I had trouble pulling up that media. "
                "Can I describe the product in text instead?"
            )
        }