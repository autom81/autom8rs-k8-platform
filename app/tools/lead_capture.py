"""
Lead Management Tools - Phase 6
================================

Two functions:
- capture_lead(): Called AUTOMATICALLY on first message in any conversation.
                  Not triggered by LLM - the message_handler calls it.
                  Every conversation = a lead (cold by default).

- update_lead_status(): Called by LLM as conversation progresses to
                        update classification (cold → warm → hot, etc.)

Philosophy:
    Every conversation IS a lead. Capture first, classify later.
    This ensures we don't miss any potential customers.
"""
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadClassificationEnum, LeadStatusEnum
from app.models.conversation import Conversation

logger = logging.getLogger(__name__)


# ============================================================
# AUTO-CALLED (not an LLM tool)
# Called by message_handler on first message in conversation
# ============================================================

def capture_lead(
    db: Session,
    conversation: Conversation,
    customer_name: Optional[str] = None,
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None,
    initial_interest: Optional[str] = None,
) -> dict:
    """
    AUTOMATIC: Called by message_handler on first message.
    Creates a Lead record for every conversation.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        customer_name: Optional - often unknown initially
        customer_email: Optional - often unknown initially
        customer_phone: Often same as external_user_id for WhatsApp
        initial_interest: What they asked about (from first message)
    
    Returns:
        dict with lead_id and success status
    """
    try:
        # Check if lead already exists for this conversation
        existing = db.query(Lead).filter(
            Lead.conversation_id == conversation.id
        ).first()
        
        if existing:
            logger.debug(f"Lead already exists for conversation {conversation.id}")
            return {
                "success": True,
                "lead_id": str(existing.id),
                "created": False,
                "message": "Lead already exists for this conversation"
            }
        
        # Use external_user_id as phone for WhatsApp channel
        phone = customer_phone
        if not phone and conversation.channel == "whatsapp":
            phone = conversation.external_user_id
        
        # Create new lead
        lead = Lead(
            id=uuid.uuid4(),
            business_id=conversation.business_id,
            conversation_id=conversation.id,
            name=customer_name,
            email=customer_email,
            phone=phone,
            interest=initial_interest,
            source_channel=conversation.channel if hasattr(conversation.channel, 'value') 
                           else str(conversation.channel),
            status=LeadStatusEnum.new,
            classification=LeadClassificationEnum.cold,  # Default
            notes=f"Auto-captured from {conversation.channel} conversation",
        )
        
        db.add(lead)
        db.commit()
        db.refresh(lead)
        
        logger.info(
            f"Lead captured: id={lead.id}, "
            f"conversation={conversation.id}, "
            f"channel={conversation.channel}"
        )
        
        return {
            "success": True,
            "lead_id": str(lead.id),
            "created": True,
            "classification": "cold",
            "message": "Lead captured successfully"
        }
        
    except Exception as e:
        logger.error(f"Error capturing lead: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to capture lead"
        }


# ============================================================
# LLM-CALLED TOOL
# Called by LLM via function calling to update classification
# ============================================================

def update_lead_status(
    db: Session,
    conversation: Conversation,
    classification: str,
    interest_area: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """
    TOOL: Update the lead classification for a conversation.
    
    Called by LLM when it detects the conversation's nature has changed:
    - Customer asked about specific product → warm
    - Customer placed order → hot
    - Customer has existing order → post_purchase
    - Customer complaint → support
    - Spam/abuse → spam
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        classification: One of: hot, warm, cold, post_purchase, support, spam
        interest_area: What customer is interested in (e.g., "Portable Blender")
        notes: Optional context about why classification changed
    
    Returns:
        dict with updated lead info
    """
    try:
        # Validate classification
        valid_classifications = [c.value for c in LeadClassificationEnum]
        if classification not in valid_classifications:
            return {
                "success": False,
                "error": f"Invalid classification '{classification}'. "
                         f"Must be one of: {valid_classifications}"
            }
        
        # Find the lead for this conversation
        lead = db.query(Lead).filter(
            Lead.conversation_id == conversation.id
        ).first()
        
        if not lead:
            # Shouldn't happen since we auto-capture, but handle it
            logger.warning(
                f"No lead found for conversation {conversation.id}, "
                f"creating one now"
            )
            
            phone = conversation.external_user_id if conversation.channel == "whatsapp" else None
            lead = Lead(
                id=uuid.uuid4(),
                business_id=conversation.business_id,
                conversation_id=conversation.id,
                phone=phone,
                source_channel=str(conversation.channel),
                status=LeadStatusEnum.new,
                classification=LeadClassificationEnum(classification),
                interest_area=interest_area,
                notes=notes,
            )
            db.add(lead)
        else:
            # Update existing lead
            old_classification = lead.classification.value if lead.classification else "none"
            lead.classification = LeadClassificationEnum(classification)
            
            if interest_area:
                lead.interest_area = interest_area
                # Also update the legacy 'interest' field for consistency
                if not lead.interest:
                    lead.interest = interest_area
            
            if notes:
                # Append to existing notes
                if lead.notes:
                    lead.notes = f"{lead.notes}\n[{classification}] {notes}"
                else:
                    lead.notes = f"[{classification}] {notes}"
            
            # Auto-update CRM status based on classification
            # This bridges bot classification to sales funnel status
            if classification == "hot" and lead.status == LeadStatusEnum.new:
                lead.status = LeadStatusEnum.qualified
            elif classification == "warm" and lead.status == LeadStatusEnum.new:
                lead.status = LeadStatusEnum.connected
            elif classification == "spam":
                lead.status = LeadStatusEnum.unqualified
            
            logger.info(
                f"Lead classification updated: {old_classification} → {classification} "
                f"(lead_id={lead.id}, conversation={conversation.id})"
            )
        
        db.commit()
        db.refresh(lead)
        
        return {
            "success": True,
            "lead_id": str(lead.id),
            "classification": classification,
            "interest_area": interest_area,
            "message": f"Lead classified as '{classification}'"
        }
        
    except Exception as e:
        logger.error(f"Error updating lead status: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to update lead status"
        }