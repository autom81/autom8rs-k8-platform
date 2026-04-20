import uuid
import enum
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, DateTime, Integer
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base

class ChannelEnum(str, enum.Enum):
    whatsapp = "whatsapp"
    instagram = "instagram"
    facebook = "facebook"
    telegram = "telegram"
    website = "website"

class ConvoStatusEnum(str, enum.Enum):
    active = "active"
    escalated = "escalated"
    resolved = "resolved"
    closed = "closed"

class RoleEnum(str, enum.Enum):
    user = "user"
    assistant = "assistant"
    system = "system"

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    external_user_id = Column(String)
    channel = Column(SAEnum(ChannelEnum))
    status = Column(SAEnum(ConvoStatusEnum))
    escalation_reason = Column(Text, nullable=True)
    source = Column(String(50))
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    last_message_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    message_count = Column(Integer, nullable=True, default=0)
    pinned = Column(Boolean, default=False, nullable=True)

class Message(Base):
    __tablename__ = "messages"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(Uuid(as_uuid=True), ForeignKey("conversations.id"))
    role = Column(SAEnum(RoleEnum))
    content = Column(Text)
    media_url = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    was_voice_note = Column(Boolean, default=False)
    original_transcript = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())