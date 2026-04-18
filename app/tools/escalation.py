"""
Escalation Tool - Phase 6
==========================

Handles transferring conversations to human agents.

Triggers:
- Customer asks to speak to a human
- Customer is frustrated/angry
- Complex request beyond AI capability
- Complaint or refund request
- Shipped order cancellation

Effects:
- Sets conversation.status = 'escalated' (existing flow respects this)
- Saves system message for audit trail
- Can trigger n8n webhook notification (Phase 8 integration point)
"""
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, ConvoStatusEnum, RoleEnum

logger = logging.getLogger(__name__)


def escalate_to_human(
    db: Session,
    conversation: Conversation,
    reason: str,
    urgency: str = "normal",
) -> dict:
    """
    TOOL: Transfer conversation to a human agent.
    
    Called by LLM when it determines human intervention is needed.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        reason: Why escalation is needed (e.g., "Angry customer", "Refund request")
        urgency: "low", "normal", or "high"
    
    Returns:
        dict with success status and user-facing message
    """
    try:
        # Validate urgency
        if urgency not in ("low", "normal", "high"):
            urgency = "normal"
        
        # Check if already escalated
        if conversation.status == ConvoStatusEnum.escalated:
            logger.info(
                f"Conversation {conversation.id} already escalated, "
                f"adding additional reason"
            )
            # Append to existing reason rather than overwriting
            if conversation.escalation_reason:
                conversation.escalation_reason = (
                    f"{conversation.escalation_reason} | "
                    f"[{urgency}] {reason}"
                )
            else:
                conversation.escalation_reason = f"[{urgency}] {reason}"
            
            db.commit()
            
            return {
                "success": True,
                "already_escalated": True,
                "message": (
                    "Your message has been added to the existing escalation. "
                    "Someone from our team will be with you shortly."
                ),
                "urgency": urgency,
            }
        
        # Update conversation status
        conversation.status = ConvoStatusEnum.escalated
        conversation.escalation_reason = f"[{urgency}] {reason}"
        
        # Save a system message for audit trail
        system_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            role=RoleEnum.system,
            content=f"[ESCALATED - {urgency.upper()}] {reason}",
        )
        db.add(system_msg)
        
        db.commit()
        db.refresh(conversation)
        
        logger.info(
            f"Conversation escalated: id={conversation.id}, "
            f"urgency={urgency}, reason={reason}"
        )
        
        # Prepare user-facing message based on urgency
        if urgency == "high":
            user_message = (
                "I understand this is urgent. I've notified our team immediately "
                "and someone will be with you very soon. I apologize for any inconvenience."
            )
        elif urgency == "low":
            user_message = (
                "I've passed your request along to our team. "
                "Someone will follow up with you when they're available."
            )
        else:
            user_message = (
                "I've escalated this to our team and someone will be with you shortly. "
                "Thanks for your patience!"
            )
        
        # TODO Phase 8: Trigger n8n webhook for team notification
        # This is where we'd send a Slack/email alert to the business owner
        
        return {
            "success": True,
            "escalated": True,
            "urgency": urgency,
            "reason": reason,
            "conversation_id": str(conversation.id),
            "message": user_message,
        }
        
    except Exception as e:
        logger.error(f"Error escalating conversation: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": (
                "I'm trying to connect you with our team. "
                "Please try again in a moment or message us directly."
            )
        }