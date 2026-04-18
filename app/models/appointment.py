"""
Appointment Model
==================
Stores appointment bookings for businesses that have scheduling enabled.
Built for all clients but only exposed as a tool when
business.features['scheduling_enabled'] is True.
"""
import uuid
import enum
from sqlalchemy import Column, String, Text, ForeignKey, DateTime, Date, Time
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base


class AppointmentStatusEnum(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=True)
    
    # Customer details
    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(50))
    
    # Appointment details
    service_type = Column(String(100), nullable=False)
    # Values: consultation, beautician, esthetician, therapy, medical,
    #         real_estate_viewing, real_estate_consultation,
    #         construction_quote, plumbing, electrical, carpentry,
    #         pickup, installation, demo, other
    
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time, nullable=False)
    
    # Status tracking
    status = Column(SAEnum(AppointmentStatusEnum), default=AppointmentStatusEnum.pending)
    notes = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())