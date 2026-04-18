"""
Redis Caching Layer - Phase 6
==============================

Caches frequently-accessed data to reduce database load and improve
response times. Uses the Redis instance already deployed via Coolify.

Cache TTLs:
- Business info: 1 hour (rarely changes)
- Products: 5 minutes (changes occasionally)
- Conversations: 1 minute (frequently changes)

Usage:
    from app.services.cache import BusinessCache, ProductCache
    
    # In message_handler:
    business_dict = BusinessCache.get(db, business_id)
    products = ProductCache.get_products(db, business_id)
    
    # On updates:
    BusinessCache.invalidate(business_id)
    ProductCache.invalidate(business_id)

Note: This is SYNCHRONOUS to match your SQLAlchemy pattern.
Uses standard redis-py (not asyncio) for simplicity.
"""
import json
import logging
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, Any

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.models.business import Business, Product
from app.models.conversation import Conversation

logger = logging.getLogger(__name__)

# Initialize Redis client (synchronous to match existing pattern)
try:
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis cache connected successfully")
    REDIS_AVAILABLE = True
except Exception as e:
    logger.warning(f"Redis unavailable, caching disabled: {e}")
    redis_client = None
    REDIS_AVAILABLE = False


# ============================================================
# JSON SERIALIZATION HELPERS
# Handle UUID, datetime, Decimal, etc. for Redis storage
# ============================================================

def _serialize(obj: Any) -> str:
    """Convert SQLAlchemy objects or dicts to JSON string."""
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, uuid.UUID):
            return str(o)
        if hasattr(o, '__dict__'):
            # Handle SQLAlchemy models
            return {
                k: v for k, v in o.__dict__.items()
                if not k.startswith('_')
            }
        raise TypeError(f"Type {type(o)} not serializable")
    
    return json.dumps(obj, default=default)


def _deserialize(data: str) -> Any:
    """Parse JSON string back to Python dict."""
    return json.loads(data)


def _business_to_dict(business: Business) -> dict:
    """Convert Business ORM object to a cacheable dict."""
    return {
        "id": str(business.id),
        "name": business.name,
        "owner_name": business.owner_name,
        "owner_email": business.owner_email,
        "owner_phone": business.owner_phone,
        "tier": business.tier.value if business.tier else None,
        "base_prompt": business.base_prompt,
        "notification_channels": business.notification_channels,
        "escalation_timeout_hours": business.escalation_timeout_hours,
        "meta_phone_number_id": business.meta_phone_number_id,
        "meta_waba_id": business.meta_waba_id,
        "meta_page_access_token": business.meta_page_access_token,
        "instagram_account_id": business.instagram_account_id,
        "max_products": business.max_products,
        # Phase 6 additions
        "features": business.features if hasattr(business, 'features') else {},
        "order_prefix": business.order_prefix if hasattr(business, 'order_prefix') else "ORD",
        "category": business.category if hasattr(business, 'category') else None,
        "brand_voice": business.brand_voice if hasattr(business, 'brand_voice') else None,
    }


def _product_to_dict(product: Product) -> dict:
    """Convert Product ORM object to a cacheable dict."""
    return {
        "id": str(product.id),
        "business_id": str(product.business_id),
        "name": product.name,
        "description": product.description,
        "category": product.category,
        "price": str(product.price) if product.price else None,
        "currency": product.currency,
        "variants": product.variants,
        "quantity": product.quantity,
        "status": product.status.value if product.status else None,
    }


# ============================================================
# BUSINESS CACHE
# 1 hour TTL - rarely changes
# ============================================================

class BusinessCache:
    """Cache for business records - rarely changes."""
    
    TTL = 3600  # 1 hour
    
    @staticmethod
    def _key(business_id) -> str:
        return f"business:{business_id}"
    
    @staticmethod
    def get(db: Session, business_id) -> Optional[dict]:
        """
        Get business as a dict from cache or database.
        Returns None if business doesn't exist.
        
        Note: Returns dict, not ORM object (dicts cache better).
        Use get_orm() if you need the ORM object.
        """
        if not REDIS_AVAILABLE:
            # Fall back to direct DB query
            business = db.query(Business).filter(
                Business.id == uuid.UUID(str(business_id))
            ).first()
            return _business_to_dict(business) if business else None
        
        cache_key = BusinessCache._key(business_id)
        
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug(f"Cache HIT: {cache_key}")
                return _deserialize(cached)
            
            logger.debug(f"Cache MISS: {cache_key}")
            business = db.query(Business).filter(
                Business.id == uuid.UUID(str(business_id))
            ).first()
            
            if business:
                business_dict = _business_to_dict(business)
                redis_client.setex(
                    cache_key,
                    BusinessCache.TTL,
                    _serialize(business_dict)
                )
                return business_dict
            
            return None
            
        except Exception as e:
            logger.error(f"BusinessCache error: {e}")
            # Fall back to direct DB query on cache failure
            business = db.query(Business).filter(
                Business.id == uuid.UUID(str(business_id))
            ).first()
            return _business_to_dict(business) if business else None
    
    @staticmethod
    def get_orm(db: Session, business_id) -> Optional[Business]:
        """
        Get business as ORM object (direct DB query, no cache).
        Use when you need to modify the object.
        """
        return db.query(Business).filter(
            Business.id == uuid.UUID(str(business_id))
        ).first()
    
    @staticmethod
    def invalidate(business_id) -> None:
        """Remove business from cache. Call when business info updates."""
        if not REDIS_AVAILABLE:
            return
        try:
            redis_client.delete(BusinessCache._key(business_id))
            logger.info(f"Invalidated business cache: {business_id}")
        except Exception as e:
            logger.error(f"Error invalidating business cache: {e}")


# ============================================================
# PRODUCT CACHE
# 5 minute TTL - changes occasionally
# ============================================================

class ProductCache:
    """Cache for active product lists - changes occasionally."""
    
    TTL = 300  # 5 minutes
    
    @staticmethod
    def _key(business_id) -> str:
        return f"products:{business_id}"
    
    @staticmethod
    def get_products(db: Session, business_id, status: str = 'active') -> list:
        """
        Get active products from cache or database.
        Returns list of dicts (not ORM objects).
        """
        if not REDIS_AVAILABLE:
            products = db.query(Product).filter(
                Product.business_id == uuid.UUID(str(business_id)),
                Product.status != 'discontinued'
            ).all()
            return [_product_to_dict(p) for p in products]
        
        cache_key = ProductCache._key(business_id)
        
        try:
            cached = redis_client.get(cache_key)
            if cached:
                logger.debug(f"Cache HIT: {cache_key}")
                return _deserialize(cached)
            
            logger.debug(f"Cache MISS: {cache_key}")
            products = db.query(Product).filter(
                Product.business_id == uuid.UUID(str(business_id)),
                Product.status != 'discontinued'
            ).order_by(Product.name).all()
            
            products_list = [_product_to_dict(p) for p in products]
            
            redis_client.setex(
                cache_key,
                ProductCache.TTL,
                _serialize(products_list)
            )
            
            return products_list
            
        except Exception as e:
            logger.error(f"ProductCache error: {e}")
            # Fall back to direct DB query
            products = db.query(Product).filter(
                Product.business_id == uuid.UUID(str(business_id))
            ).all()
            return [_product_to_dict(p) for p in products]
    
    @staticmethod
    def get_products_orm(db: Session, business_id) -> list:
        """
        Get products as ORM objects (direct DB query, no cache).
        Use when you need to modify products.
        """
        return db.query(Product).filter(
            Product.business_id == uuid.UUID(str(business_id)),
            Product.status != 'discontinued'
        ).all()
    
    @staticmethod
    def invalidate(business_id) -> None:
        """Remove products from cache. Call when any product updates."""
        if not REDIS_AVAILABLE:
            return
        try:
            redis_client.delete(ProductCache._key(business_id))
            logger.info(f"Invalidated product cache: {business_id}")
        except Exception as e:
            logger.error(f"Error invalidating product cache: {e}")
    
    @staticmethod
    def find_by_name(db: Session, business_id, product_name: str) -> Optional[dict]:
        """
        Find a product by name (case-insensitive, partial match).
        Uses cached list for fast lookup.
        """
        products = ProductCache.get_products(db, business_id)
        search_term = product_name.lower().strip()
        
        # Try exact match first
        for product in products:
            if product['name'].lower() == search_term:
                return product
        
        # Fall back to partial match
        for product in products:
            if search_term in product['name'].lower():
                return product
        
        return None


# ============================================================
# CONVERSATION CACHE
# 1 minute TTL - frequently changes
# ============================================================

class ConversationCache:
    """Cache for conversation records - frequently changes."""
    
    TTL = 60  # 1 minute
    
    @staticmethod
    def _key(conversation_id) -> str:
        return f"conversation:{conversation_id}"
    
    @staticmethod
    def invalidate(conversation_id) -> None:
        """Remove conversation from cache. Call on status changes."""
        if not REDIS_AVAILABLE:
            return
        try:
            redis_client.delete(ConversationCache._key(conversation_id))
        except Exception as e:
            logger.error(f"Error invalidating conversation cache: {e}")


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def clear_all_caches() -> int:
    """
    Emergency: Clear all caches.
    Returns number of keys deleted.
    """
    if not REDIS_AVAILABLE:
        return 0
    
    try:
        keys = []
        for pattern in ["business:*", "products:*", "conversation:*"]:
            keys.extend(redis_client.keys(pattern))
        
        if keys:
            deleted = redis_client.delete(*keys)
            logger.warning(f"Cleared {deleted} cache keys")
            return deleted
        return 0
    except Exception as e:
        logger.error(f"Error clearing caches: {e}")
        return 0


def cache_health_check() -> dict:
    """Check Redis connectivity for monitoring."""
    if not REDIS_AVAILABLE:
        return {"status": "disabled", "reason": "Redis unavailable at startup"}
    
    try:
        redis_client.ping()
        info = redis_client.info('memory')
        return {
            "status": "healthy",
            "memory_used": info.get('used_memory_human', 'unknown'),
            "connected_clients": info.get('connected_clients', 0)
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }