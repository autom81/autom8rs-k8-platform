"""
Instagram Sync Service - Phase 6
==================================
Processes Instagram posts tagged with #AutoM8 and ingests them
into the products and media_library tables.

How it works:
1. Business owner posts to Instagram with #AutoM8 in caption
2. Instagram webhook fires to /api/meta/webhook
3. webhooks.py calls process_instagram_post() here
4. Caption is parsed for product name + price
5. Product created (pending_review) or media added to existing product

Caption format business owners must use:
    Product Name
    Price: $XX.XX
    Description here

    #AutoM8 #OptionalProductTag

On first setup, call initial_instagram_scrape() to backfill existing posts.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.business import Business, Product, ProductStatusEnum, ProductSourceEnum
from app.models.media import MediaLibrary, MediaTypeEnum, MediaStatusEnum, SourcePlatformEnum
from app.services.cache import ProductCache

logger = logging.getLogger(__name__)

META_GRAPH_URL = "https://graph.facebook.com/v21.0"


# ============================================================
# CAPTION PARSER
# ============================================================

def parse_product_caption(caption: str) -> dict:
    """
    Extract product info from a structured Instagram caption.

    Expected format:
        Product Name
        Price: $XX.XX
        Description text here

        #AutoM8 #ProductTag

    Args:
        caption: Raw Instagram post caption

    Returns:
        dict with name, price, description, hashtags
    """
    if not caption:
        return {}

    lines = [line.strip() for line in caption.strip().split('\n') if line.strip()]

    if not lines:
        return {}

    # Line 1: Product name
    name = lines[0].strip()

    # Extract price (e.g., "Price: $65.99" or "Price: 65.99")
    price = None
    price_match = re.search(r'[Pp]rice:\s*\$?([\d,]+\.?\d*)', caption)
    if price_match:
        try:
            price = float(price_match.group(1).replace(',', ''))
        except ValueError:
            price = None

    # Extract hashtags
    hashtags = re.findall(r'#(\w+)', caption)

    # Description: lines after name+price, before hashtags
    description_lines = []
    for line in lines[1:]:
        if line.startswith('#'):
            break
        if re.match(r'[Pp]rice:', line):
            continue
        description_lines.append(line)

    description = ' '.join(description_lines).strip() or None

    return {
        "name": name,
        "price": price,
        "description": description,
        "hashtags": [h.lower() for h in hashtags],
    }


# ============================================================
# FETCH INSTAGRAM POST DETAILS
# ============================================================

async def fetch_instagram_post(post_id: str, access_token: str) -> Optional[dict]:
    """
    Fetch full post details from Instagram Graph API.

    Args:
        post_id: Instagram media ID
        access_token: Page access token for this business

    Returns:
        dict with media_type, media_url, caption, permalink, etc.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            response = await http.get(
                f"{META_GRAPH_URL}/{post_id}",
                params={
                    "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
                    "access_token": access_token,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to fetch Instagram post {post_id}: {response.text}")
                return None

            return response.json()

    except Exception as e:
        logger.error(f"Error fetching Instagram post {post_id}: {e}")
        return None


# ============================================================
# PROCESS INSTAGRAM POST
# ============================================================

def process_instagram_post(
    db: Session,
    business: Business,
    post_data: dict,
) -> dict:
    """
    Process an Instagram post with #AutoM8 hashtag.

    Logic:
    - If product with same name exists: add media to media_library
    - If new product: create with status='pending_review', add media
    - Invalidate product cache

    Args:
        db: SQLAlchemy session
        business: Business ORM object
        post_data: Post data from Instagram Graph API

    Returns:
        dict with result status
    """
    try:
        caption = post_data.get('caption', '')
        post_id = post_data.get('id', '')
        media_url = post_data.get('media_url', '')
        media_type_raw = post_data.get('media_type', 'IMAGE').upper()
        thumbnail_url = post_data.get('thumbnail_url')
        permalink = post_data.get('permalink')
        timestamp_str = post_data.get('timestamp')

        if not media_url:
            return {"success": False, "error": "No media_url in post data"}

        # Parse caption for product info
        parsed = parse_product_caption(caption)
        if not parsed.get('name'):
            return {"success": False, "error": "Could not parse product name from caption"}

        # Map Instagram media type to our enum
        if media_type_raw == 'VIDEO':
            media_type = MediaTypeEnum.video
        elif media_type_raw == 'CAROUSEL_ALBUM':
            media_type = MediaTypeEnum.carousel
        else:
            media_type = MediaTypeEnum.image

        # Parse posted_at timestamp
        posted_at = None
        if timestamp_str:
            try:
                posted_at = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except Exception:
                posted_at = datetime.now(timezone.utc)

        # Check if product already exists
        existing_product = db.query(Product).filter(
            Product.business_id == business.id,
            Product.name.ilike(parsed['name']),
        ).first()

        if existing_product:
            # Product exists - just add media
            media = MediaLibrary(
                id=uuid.uuid4(),
                business_id=business.id,
                source_platform=SourcePlatformEnum.instagram,
                source_post_id=post_id,
                source_url=permalink,
                media_type=media_type,
                media_url=media_url,
                thumbnail_url=thumbnail_url,
                caption=caption,
                linked_product_id=existing_product.id,
                auto_linked=True,
                status=MediaStatusEnum.active,
                posted_at=posted_at,
            )
            db.add(media)
            db.commit()

            logger.info(
                f"Instagram media added to existing product: "
                f"{existing_product.name} (post_id={post_id})"
            )

            return {
                "success": True,
                "action": "media_added",
                "product_name": existing_product.name,
                "product_id": str(existing_product.id),
                "media_id": str(media.id),
            }

        else:
            # New product - create as pending_review
            new_product = Product(
                id=uuid.uuid4(),
                business_id=business.id,
                name=parsed['name'],
                description=parsed.get('description'),
                price=parsed.get('price'),
                currency='TTD',
                quantity=0,  # Owner must set quantity via dashboard
                status=ProductStatusEnum.pending_review,
                source=ProductSourceEnum.instagram,
                ingested_at=datetime.now(timezone.utc),
            )
            db.add(new_product)
            db.flush()  # Get the ID without committing

            # Add media linked to new product
            media = MediaLibrary(
                id=uuid.uuid4(),
                business_id=business.id,
                source_platform=SourcePlatformEnum.instagram,
                source_post_id=post_id,
                source_url=permalink,
                media_type=media_type,
                media_url=media_url,
                thumbnail_url=thumbnail_url,
                caption=caption,
                linked_product_id=new_product.id,
                auto_linked=True,
                status=MediaStatusEnum.active,
                posted_at=posted_at,
            )
            db.add(media)
            db.commit()

            # Invalidate product cache so next request sees new product
            ProductCache.invalidate(business.id)

            logger.info(
                f"New product created from Instagram: "
                f"{new_product.name} (pending_review, post_id={post_id})"
            )

            return {
                "success": True,
                "action": "product_created",
                "product_name": new_product.name,
                "product_id": str(new_product.id),
                "media_id": str(media.id),
                "status": "pending_review",
                "note": "Product needs quantity set + approval in dashboard before going live",
            }

    except Exception as e:
        logger.error(f"Error processing Instagram post: {e}", exc_info=True)
        db.rollback()
        return {"success": False, "error": str(e)}


# ============================================================
# INITIAL SCRAPE (one-time onboarding)
# ============================================================

async def initial_instagram_scrape(db: Session, business: Business) -> dict:
    """
    One-time scrape of existing Instagram posts with #AutoM8.
    Call this when onboarding a new client to backfill their catalog.

    Fetches last 50 posts and processes any with #AutoM8.

    Args:
        db: SQLAlchemy session
        business: Business ORM object

    Returns:
        dict with count of products/media created
    """
    if not business.instagram_account_id or not business.meta_page_access_token:
        return {
            "success": False,
            "error": "Business missing instagram_account_id or meta_page_access_token"
        }

    try:
        processed = 0
        products_created = 0
        media_added = 0

        async with httpx.AsyncClient(timeout=30.0) as http:
            # Fetch recent media from Instagram account
            response = await http.get(
                f"{META_GRAPH_URL}/{business.instagram_account_id}/media",
                params={
                    "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp",
                    "limit": 50,
                    "access_token": business.meta_page_access_token,
                },
            )

            if response.status_code != 200:
                return {
                    "success": False,
                    "error": f"Instagram API error: {response.text}"
                }

            data = response.json()
            posts = data.get('data', [])

        for post in posts:
            caption = post.get('caption', '')
            if '#autom8' not in caption.lower():
                continue

            result = process_instagram_post(db, business, post)
            processed += 1

            if result.get('action') == 'product_created':
                products_created += 1
            elif result.get('action') == 'media_added':
                media_added += 1

        logger.info(
            f"Instagram initial scrape complete for {business.name}: "
            f"processed={processed}, products_created={products_created}, "
            f"media_added={media_added}"
        )

        return {
            "success": True,
            "posts_processed": processed,
            "products_created": products_created,
            "media_added": media_added,
        }

    except Exception as e:
        logger.error(f"Error during Instagram scrape: {e}", exc_info=True)
        return {"success": False, "error": str(e)}