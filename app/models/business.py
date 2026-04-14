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
    meta_phone_number_id = Column(String)
    meta_waba_id = Column(String)
    meta_page_access_token = Column(Text, nullable=True)
    max_products = Column(Integer, nullable=True)
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
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

class N8nWorkflow(Base):
    __tablename__ = "n8n_workflows"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    workflow_name = Column(String(100))
    webhook_url = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())