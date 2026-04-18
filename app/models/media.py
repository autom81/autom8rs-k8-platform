"""
Media Library Model
====================
Stores media (images/videos) linked to products from Instagram, Facebook, etc.
Enables bot to send actual product videos/photos when customers ask.
"""
import uuid
import enum
from sqlalchemy import Column, String, Text, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy import Uuid, Enum as SAEnum
from app.database import Base


class MediaTypeEnum(str, enum.Enum):
    image = "image"
    video = "video"
    carousel = "carousel"


class MediaStatusEnum(str, enum.Enum):
    active = "active"
    pending = "pending"
    rejected = "rejected"


class SourcePlatformEnum(str, enum.Enum):
    instagram = "instagram"
    facebook = "facebook"
    manual = "manual"


class MediaLibrary(Base):
    __tablename__ = "media_library"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    business_id = Column(Uuid(as_uuid=True), ForeignKey("businesses.id"))
    
    # Source tracking
    source_platform = Column(SAEnum(SourcePlatformEnum))
    source_post_id = Column(String(255), nullable=True)
    source_url = Column(Text, nullable=True)
    
    # Media details
    media_type = Column(SAEnum(MediaTypeEnum))
    media_url = Column(Text, nullable=False)
    thumbnail_url = Column(Text, nullable=True)
    caption = Column(Text, nullable=True)
    
    # Product linkage
    linked_product_id = Column(Uuid(as_uuid=True), ForeignKey("products.id"), nullable=True)
    auto_linked = Column(Boolean, default=False)
    
    # Moderation status
    status = Column(SAEnum(MediaStatusEnum), default=MediaStatusEnum.active)
    
    # Timestamps
    posted_at = Column(DateTime(timezone=True), nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())