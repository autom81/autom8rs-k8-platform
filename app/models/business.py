"""
Business Model - UPDATED for Phase 6
=====================================
Adds:
- features JSONB (feature flags for tool enablement per business)
- order_prefix (for custom order ID format like 'TPT-260417-001')
- category (business category for context)
- brand_voice (custom personality text)
"""
import uuid
import enum
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base
 
 
class TierEnum(str, enum.Enum):
    starter = "starter"
    pro = "pro"
    ultra = "ultra"
    custom = "custom"
 
 
class ProductStatusEnum(str, enum.Enum):
    active = "active"
    out_of_stock = "out_of_stock"
    discontinued = "discontinued"
    pending_review = "pending_review"  # NEW: For Instagram-ingested products
 
 
class ProductSourceEnum(str, enum.Enum):
    manual = "manual"
    instagram = "instagram"
    facebook = "facebook"
    api = "api"
 
 
class Business(Base):
    __tablename__ = "businesses"
 
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255))
    owner_name = Column(String(255))
    owner_email = Column(String(255))
    owner_phone = Column(String(50))
    tier = Column(SAEnum(TierEnum))
    base_prompt = Column(Text)
    notification_channels = Column(JSONB)
    escalation_timeout_hours = Column(Integer, default=2)
    
    # Meta integrations
    meta_phone_number_id = Column(String)
    meta_waba_id = Column(String)
    meta_page_access_token = Column(Text, nullable=True)
    instagram_account_id = Column(String, nullable=True)
    
    # Product limits
    max_products = Column(Integer, nullable=True)
    
    # ========== PHASE 6 ADDITIONS ==========
    
    # Feature flags for per-business tool enablement
    # Example: {"ecommerce_enabled": true, "scheduling_enabled": false, "media_sync_enabled": true}
    features = Column(JSONB, nullable=True, default=lambda: {
        "ecommerce_enabled": True,
        "scheduling_enabled": False,
        "media_sync_enabled": True
    })
    
    # Order ID prefix (e.g., 'TPT' for TrendyProductsTT)
    # Used to generate order numbers like TPT-260417-001
    order_prefix = Column(String(10), default="ORD")
    
    # Business category for context
    # Examples: 'retail', 'beauty', 'food', 'services', 'real_estate', etc.
    category = Column(String(100), nullable=True)
    
    # Custom brand voice/personality for system prompt
    brand_voice = Column(Text, nullable=True)

    # Integration config for external inventory sync
    # Examples: WooCommerce API keys, sync intervals, last sync time
    # {"type": "woocommerce", "store_url": "...", "consumer_key": "...", 
    #  "consumer_secret": "...", "sync_interval_minutes": 15, "last_synced": null}
    integration_config = Column(JSONB, nullable=True)
    
    # Website URL for directing customers to website
    website_url = Column(String, nullable=True)
    
    # ========== END PHASE 6 ADDITIONS ==========
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
 
 
class Product(Base):
    __tablename__ = "products"
 
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    name = Column(String(255))
    description = Column(Text)
    category = Column(String(100))
    price = Column(Numeric(10, 2))
    currency = Column(String(3))
    variants = Column(JSONB, nullable=True)
    quantity = Column(Integer)
    status = Column(SAEnum(ProductStatusEnum))
    
    # Direct link to product page on business website
    # Used when bot directs customer to purchase online
    product_url = Column(String, nullable=True)
    
    # ========== PHASE 6 ADDITIONS ==========
    
    # Where did this product come from?
    source = Column(SAEnum(ProductSourceEnum), default=ProductSourceEnum.manual)
    
    # For Instagram-ingested products, when were they imported?
    ingested_at = Column(DateTime(timezone=True), nullable=True)
    
    # When were they approved for use (for pending_review status)?
    approved_at = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(Uuid(as_uuid=True), nullable=True)
    
    # ========== END PHASE 6 ADDITIONS ==========
    
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
 
 
class N8nWorkflow(Base):
    __tablename__ = "n8n_workflows"
 
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    workflow_name = Column(String(100))
    webhook_url = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
 