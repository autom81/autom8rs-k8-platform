"""
Models Package Init
====================
 
Imports all models so Alembic can detect schema changes.
IMPORTANT: Every model file must be imported here, or Alembic
won't see it and won't generate migrations for it.
"""
 
# Business and product models
from app.models.business import (
    Business,
    Product,
    N8nWorkflow,
    TierEnum,
    ProductStatusEnum,
    ProductSourceEnum,  # New in Phase 6
)
 
# Conversation and messaging
from app.models.conversation import (
    Conversation,
    Message,
    ChannelEnum,
    ConvoStatusEnum,
    RoleEnum,
)
 
# Lead and order models
from app.models.lead import (
    Lead,
    Order,
    LeadStatusEnum,
    LeadClassificationEnum,  # New in Phase 6
    OrderStatusEnum,
)
 
# Template tracking
from app.models.template_tracking import (
    TemplateSend,
    TemplateCategoryEnum,
)
 
# Phase 6: New models
from app.models.appointment import (
    Appointment,
    AppointmentStatusEnum,
)
 
from app.models.media import (
    MediaLibrary,
    MediaTypeEnum,
    MediaStatusEnum,
    SourcePlatformEnum,
)

# Phase 7: Dashboard models
from app.models.user import User
from app.models.broadcast import BroadcastTemplate, Broadcast, BroadcastRecipient

# Tags system
from app.models.tag import Tag, LeadTag, TagTypeEnum


__all__ = [
    # Business
    "Business",
    "Product",
    "N8nWorkflow",
    "TierEnum",
    "ProductStatusEnum",
    "ProductSourceEnum",
    
    # Conversation
    "Conversation",
    "Message",
    "ChannelEnum",
    "ConvoStatusEnum",
    "RoleEnum",
    
    # Lead
    "Lead",
    "Order",
    "LeadStatusEnum",
    "LeadClassificationEnum",
    "OrderStatusEnum",
    
    # Template
    "TemplateSend",
    "TemplateCategoryEnum",
    
    # Phase 6
    "Appointment",
    "AppointmentStatusEnum",
    "MediaLibrary",
    "MediaTypeEnum",
    "MediaStatusEnum",
    "SourcePlatformEnum",

    # Phase 7
    "User",
    "BroadcastTemplate",
    "Broadcast",
    "BroadcastRecipient",

    # Tags
    "Tag",
    "LeadTag",
    "TagTypeEnum",
]
 