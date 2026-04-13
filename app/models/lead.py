import uuid
import enum
from sqlalchemy import Column, String, Text, ForeignKey, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base

class LeadStatusEnum(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    converted = "converted"
    lost = "lost"

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
    status = Column(SAEnum(LeadStatusEnum))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

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