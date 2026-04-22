import uuid
import enum
from sqlalchemy import Column, String, ForeignKey, DateTime, UniqueConstraint, Boolean
from sqlalchemy import Uuid, Enum as SAEnum
from sqlalchemy.sql import func
from app.database import Base


class TagTypeEnum(str, enum.Enum):
    auto = "auto"
    manual = "manual"


# Fixed colors for auto-generated tags
AUTO_TAG_COLORS = {
    "ordered":            "#F97316",  # orange
    "cancelled":          "#EF4444",  # red
    "escalated":          "#EF4444",  # red
    "returning-customer": "#8B5CF6",  # violet
    "hot-lead":           "#EAB308",  # yellow
}

# Preset palette that owners pick from (12 options)
TAG_PALETTE = [
    "#6B7280",  # gray (default)
    "#EF4444",  # red
    "#F97316",  # orange
    "#EAB308",  # yellow
    "#22C55E",  # green
    "#14B8A6",  # teal
    "#3B82F6",  # blue
    "#8B5CF6",  # violet
    "#EC4899",  # pink
    "#F59E0B",  # amber
    "#10B981",  # emerald
    "#6366F1",  # indigo
]


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"), nullable=False)
    name = Column(String(30), nullable=False)
    color = Column(String(7), nullable=False, default="#6B7280")
    tag_type = Column(SAEnum(TagTypeEnum), nullable=False, default=TagTypeEnum.manual)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_tags_business_name"),
    )


class LeadTag(Base):
    __tablename__ = "lead_tags"

    lead_id = Column(Uuid(as_uuid=True), ForeignKey("leads.id"), primary_key=True)
    tag_id = Column(Uuid(as_uuid=True), ForeignKey("tags.id"), primary_key=True)
    applied_at = Column(DateTime(timezone=True), server_default=func.now())
    applied_by = Column(String(50), nullable=True)  # "bot" or user id string
