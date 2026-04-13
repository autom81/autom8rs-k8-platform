import uuid
import enum
from sqlalchemy import Column, String, ForeignKey, DateTime, Numeric
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base

class TemplateCategoryEnum(str, enum.Enum):
    utility = "utility"
    marketing = "marketing"

class TemplateSend(Base):
    __tablename__ = "template_sends"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    template_category = Column(SAEnum(TemplateCategoryEnum))
    recipient_phone = Column(String)
    meta_message_id = Column(String)
    cost_estimate = Column(Numeric(6, 4))
    sent_at = Column(DateTime(timezone=True), server_default=func.now())