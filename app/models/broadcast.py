import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class BroadcastTemplate(Base):
    __tablename__ = "broadcast_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=True)
    body_text = Column(Text, nullable=False)
    variables = Column(JSONB, nullable=True)
    meta_template_name = Column(String(255), nullable=True)
    meta_status = Column(String(50), default="pending")
    meta_rejection_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    business = relationship("Business")
    broadcasts = relationship("Broadcast", back_populates="template")


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    template_id = Column(UUID(as_uuid=True), ForeignKey("broadcast_templates.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="draft")
    audience_filter = Column(JSONB, nullable=True)
    recipient_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    delivered_count = Column(Integer, default=0)
    read_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    business = relationship("Business")
    template = relationship("BroadcastTemplate", back_populates="broadcasts")
    creator = relationship("User", foreign_keys=[created_by])
    recipients = relationship("BroadcastRecipient", back_populates="broadcast")


class BroadcastRecipient(Base):
    __tablename__ = "broadcast_recipients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    broadcast_id = Column(UUID(as_uuid=True), ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False)
    lead_id = Column(UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    phone = Column(String(50), nullable=True)
    status = Column(String(50), default="pending")
    meta_message_id = Column(String(255), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)

    broadcast = relationship("Broadcast", back_populates="recipients")
