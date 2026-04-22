"""
Lead & Order Models - UPDATED for Phase 6 (v2)
================================================
 
Lead changes:
- Added LeadClassificationEnum (hot/warm/cold/post_purchase/support/spam)
  for quick bot-level filtering of conversations
- Expanded LeadStatusEnum to match HubSpot/Salesforce standard
  for proper CRM-style funnel tracking
- Added interest_area for what product/service they're interested in
- Added last_updated timestamp
 
Order changes:
- Added delivery_address, special_instructions
- Added order_number (human-readable ID like TPT-260417-001)
- Added shipped_at, cancelled_at, cancellation_reason
 
Why two enums on Lead?
- status = WHERE they are in sales funnel (CRM view)
- classification = WHAT KIND of conversation this is (bot's read)
 
Example: A customer can be status='qualified' + classification='warm'
meaning they fit buyer profile AND are currently asking about products.
"""
import uuid
import enum
from sqlalchemy import Column, String, Text, ForeignKey, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base
 
 
class LeadStatusEnum(str, enum.Enum):
    """
    CRM-style sales funnel status (HubSpot/Salesforce standard).
    Tracks where the lead is in the sales process.
    """
    new = "new"                              # Recently identified, not yet worked
    attempted_contact = "attempted_contact"  # Outreach has begun
    connected = "connected"                  # Communication established
    qualified = "qualified"                  # Fits criteria, moving toward transaction
    converted = "converted"                  # Became a customer (placed order)
    nurture = "nurture"                      # Good fit but not ready to buy
    unqualified = "unqualified"              # Not a fit
    lost = "lost"                            # Inactive/not interested
 
 
class LeadClassificationEnum(str, enum.Enum):
    """
    Phase 6: Bot-level classification for quick filtering.
    Updated by LLM as conversation progresses via update_lead_status tool.
    """
    hot = "hot"                      # Ready to buy / placed order
    warm = "warm"                    # Asking about specific products
    cold = "cold"                    # General inquiry, browsing
    post_purchase = "post_purchase"  # Asking about existing order
    support = "support"              # Has a problem or complaint
    spam = "spam"                    # Irrelevant/abusive
 
 
class OrderStatusEnum(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    paid = "paid"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"
 
 
class Lead(Base):
    __tablename__ = "leads"
 
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"))
    
    name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(50))
    interest = Column(Text)
    source_channel = Column(String(50))
    
    # CRM-style funnel status (HubSpot/Salesforce standard)
    status = Column(SAEnum(LeadStatusEnum), default=LeadStatusEnum.new)
    
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # ========== PHASE 6 ADDITIONS ==========
    
    # Bot-level classification for quick filtering
    # Every conversation auto-creates a lead with classification='cold'
    # LLM updates via update_lead_status tool as conversation progresses
    classification = Column(
        SAEnum(LeadClassificationEnum),
        default=LeadClassificationEnum.cold,
        nullable=True
    )
    
    # What is this lead interested in? (e.g., 'Portable Blender', 'Beauty Services')
    interest_area = Column(Text, nullable=True)
    
    # When was the classification last updated?
    last_updated = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )

    # CRM: scheduled follow-up date set by agents from the dashboard
    follow_up_at = Column(DateTime(timezone=True), nullable=True)

    # ========== END PHASE 6 ADDITIONS ==========
 
 
class Order(Base):
    __tablename__ = "orders"
 
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"))
    
    customer_name = Column(String(255))
    customer_phone = Column(String(50))
    items = Column(JSONB)
    total = Column(Numeric(10, 2))
    status = Column(SAEnum(OrderStatusEnum))
    payment_link = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # ========== PHASE 6 ADDITIONS ==========
    
    # Human-readable order ID (e.g., TPT-260417-001)
    # Generated using business.order_prefix + YYMMDD + daily counter
    order_number = Column(String(50), unique=True, nullable=True)
    
    # Delivery details (required for ordering)
    delivery_address = Column(Text, nullable=True)
    special_instructions = Column(Text, nullable=True)
    
    # Status tracking
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    shipped_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancellation_reason = Column(Text, nullable=True)

    # ========== END PHASE 6 ADDITIONS ==========