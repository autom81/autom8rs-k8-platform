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

from app.models.lead import Lead, LeadClassificationEnum, LeadStatusEnum, Order, OrderStatusEnum
from app.models.conversation import Conversation
from app.models.appointment import Appointment, AppointmentStatusEnum

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

        try:
            from app.services.workflow_engine import fire_trigger
            fire_trigger("new_lead", db, conversation.business_id, lead.id, {
                "lead_id": str(lead.id),
                "channel": str(conversation.channel),
                "name": lead.name,
                "phone": lead.phone,
            })
        except Exception:
            pass

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

        if classification == "hot":
            try:
                from app.services.workflow_engine import fire_trigger
                fire_trigger("hot_lead_detected", db, conversation.business_id, lead.id, {
                    "lead_id": str(lead.id),
                    "interest_area": interest_area,
                })
            except Exception:
                pass

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


# ============================================================
# LLM-CALLED TOOL
# Called by LLM when customer provides/corrects contact info
# ============================================================

def update_customer_info(
    db: Session,
    conversation: Conversation,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> dict:
    """
    TOOL: Update the customer's name, phone, or email.

    Syncs the change to both the Lead record AND any open orders
    so the dashboard always shows accurate contact details.
    """
    if not any([name, phone, email]):
        return {"success": False, "message": "No fields provided to update"}

    try:
        lead = db.query(Lead).filter(
            Lead.conversation_id == conversation.id
        ).first()

        if not lead:
            return {"success": False, "message": "No lead found for this conversation"}

        # Update lead fields
        if name:
            lead.name = name
        if phone:
            lead.phone = phone
        if email:
            lead.email = email

        open_order_statuses = [
            OrderStatusEnum.pending,
            OrderStatusEnum.confirmed,
            OrderStatusEnum.paid,
            OrderStatusEnum.shipped,
        ]
        open_appt_statuses = [
            AppointmentStatusEnum.pending,
            AppointmentStatusEnum.confirmed,
        ]

        # Resolve phone to use for fallback matching (before we overwrite lead.phone)
        match_phone = lead.phone

        # Sync to open orders
        open_orders = (
            db.query(Order)
            .filter(
                Order.business_id == conversation.business_id,
                Order.customer_phone == match_phone,
                Order.status.in_(open_order_statuses),
            )
            .all()
        ) if match_phone else []

        updated_orders = 0
        for order in open_orders:
            if name:
                order.customer_name = name
            if phone:
                order.customer_phone = phone
            updated_orders += 1

        # Sync to open appointments
        open_appts = (
            db.query(Appointment)
            .filter(
                Appointment.business_id == conversation.business_id,
                Appointment.customer_phone == match_phone,
                Appointment.status.in_(open_appt_statuses),
            )
            .all()
        ) if match_phone else []

        updated_appts = 0
        for appt in open_appts:
            if name:
                appt.customer_name = name
            if phone:
                appt.customer_phone = phone
            updated_appts += 1

        db.commit()

        updated = [f for f, v in [("name", name), ("phone", phone), ("email", email)] if v]
        logger.info(
            f"Customer info updated: fields={updated}, lead={lead.id}, "
            f"orders_synced={updated_orders}, appointments_synced={updated_appts}"
        )
        return {
            "success": True,
            "updated_fields": updated,
            "orders_synced": updated_orders,
            "appointments_synced": updated_appts,
            "message": f"Updated {', '.join(updated)} successfully"
        }

    except Exception as e:
        logger.error(f"Error updating customer info: {e}", exc_info=True)
        db.rollback()
        return {"success": False, "error": str(e), "message": "Failed to update customer info"}


def update_order_address(
    db: Session,
    conversation: Conversation,
    order_number: str,
    new_address: str,
) -> dict:
    """
    TOOL: Update the delivery address on a specific open order.

    Only works on pending/confirmed/paid orders — not shipped or delivered.
    """
    try:
        editable_statuses = [
            OrderStatusEnum.pending,
            OrderStatusEnum.confirmed,
            OrderStatusEnum.paid,
        ]
        order = (
            db.query(Order)
            .filter(
                Order.business_id == conversation.business_id,
                Order.order_number == order_number,
            )
            .first()
        )

        if not order:
            return {"success": False, "message": f"Order {order_number} not found"}

        if order.status not in editable_statuses:
            return {
                "success": False,
                "message": f"Order {order_number} is {order.status.value} — address can only be changed before shipping"
            }

        old_address = order.delivery_address
        order.delivery_address = new_address
        db.commit()

        logger.info(f"Delivery address updated: order={order_number}, old='{old_address}', new='{new_address}'")
        return {
            "success": True,
            "order_number": order_number,
            "new_address": new_address,
            "message": f"Delivery address updated for order {order_number}"
        }

    except Exception as e:
        logger.error(f"Error updating order address: {e}", exc_info=True)
        db.rollback()
        return {"success": False, "error": str(e), "message": "Failed to update delivery address"}