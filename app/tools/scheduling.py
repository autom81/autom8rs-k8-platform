"""
Scheduling Tool - Phase 6
==========================

Books appointments for businesses that have scheduling enabled.

Built for all clients but ONLY exposed when:
    business.features['scheduling_enabled'] = True

For TrendyProductsTT, scheduling_enabled=False so this tool isn't in their
bot's toolkit. But it's ready for beauty salons, plumbers, real estate, etc.

Service Types:
    - consultation, beautician, esthetician, therapy, medical
    - real_estate_viewing, real_estate_consultation
    - construction_quote, plumbing, electrical, carpentry
    - pickup, installation, demo, other
"""
import logging
import uuid
from datetime import datetime, date, time
from typing import Optional

from sqlalchemy.orm import Session

from app.models.appointment import Appointment, AppointmentStatusEnum
from app.models.conversation import Conversation


logger = logging.getLogger(__name__)


# ============================================================
# BOOKING REFERENCE GENERATION
# ============================================================

def _generate_booking_reference(db: Session, business_id, business_prefix: str = "APT") -> str:
    """
    Generate human-readable booking reference.
    Format: {PREFIX}-YYMMDD-XXX
    Example: APT-260420-001
    """
    today = datetime.now()
    date_str = today.strftime("%y%m%d")
    
    # Count today's appointments for this business
    today_start = datetime.combine(today.date(), time.min)
    today_end = datetime.combine(today.date(), time.max)
    
    count = db.query(Appointment).filter(
        Appointment.business_id == business_id,
        Appointment.created_at >= today_start,
        Appointment.created_at <= today_end,
    ).count()
    
    sequence = str(count + 1).zfill(3)
    return f"{business_prefix}-{date_str}-{sequence}"


# ============================================================
# SERVICE TYPE LABELS (for user-friendly messages)
# ============================================================

SERVICE_TYPE_LABELS = {
    "consultation": "General Consultation",
    "beautician": "Beauty Service",
    "esthetician": "Esthetic Treatment",
    "therapy": "Therapy Session",
    "medical": "Medical Appointment",
    "real_estate_viewing": "Property Viewing",
    "real_estate_consultation": "Real Estate Consultation",
    "construction_quote": "Construction Quote",
    "plumbing": "Plumbing Service",
    "electrical": "Electrical Service",
    "carpentry": "Carpentry Service",
    "pickup": "Store Pickup",
    "installation": "Product Installation",
    "demo": "Product Demonstration",
    "other": "Appointment",
}


# ============================================================
# SCHEDULE APPOINTMENT TOOL
# ============================================================

def schedule_appointment(
    db: Session,
    conversation: Conversation,
    customer_name: str,
    customer_phone: str,
    service_type: str,
    preferred_date: str,
    preferred_time: str,
    notes: Optional[str] = None,
) -> dict:
    """
    TOOL: Schedule an appointment.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        customer_name: Customer's full name
        customer_phone: Customer's contact number
        service_type: Type of service (see SERVICE_TYPE_LABELS)
        preferred_date: Date in YYYY-MM-DD format
        preferred_time: Time in HH:MM format (24-hour)
        notes: Optional additional notes
    
    Returns:
        dict with booking reference and confirmation message
    """
    try:
        # Validate service type
        if service_type not in SERVICE_TYPE_LABELS:
            return {
                "success": False,
                "error": f"Invalid service type '{service_type}'",
                "message": (
                    "I couldn't book that service type. Could you clarify what "
                    "kind of appointment you'd like?"
                )
            }
        
        # Parse date
        try:
            appointment_date = datetime.strptime(preferred_date, "%Y-%m-%d").date()
        except ValueError:
            return {
                "success": False,
                "error": "Invalid date format",
                "message": (
                    "I couldn't understand that date. Could you provide it like "
                    "'April 25' or 'tomorrow'?"
                )
            }
        
        # Parse time
        try:
            # Handle both "14:00" and "14:00:00"
            if len(preferred_time) == 5:
                appointment_time = datetime.strptime(preferred_time, "%H:%M").time()
            else:
                appointment_time = datetime.strptime(preferred_time, "%H:%M:%S").time()
        except ValueError:
            return {
                "success": False,
                "error": "Invalid time format",
                "message": (
                    "I couldn't understand that time. Could you provide it like "
                    "'2:00 PM' or '14:00'?"
                )
            }
        
        # Check if date is in the past
        if appointment_date < date.today():
            return {
                "success": False,
                "error": "Date is in the past",
                "message": (
                    "That date has already passed. Could you give me a future date?"
                )
            }
        
        # Generate booking reference
        booking_ref = _generate_booking_reference(db, conversation.business_id)
        
        # Create appointment
        appointment = Appointment(
            id=uuid.uuid4(),
            business_id=conversation.business_id,
            conversation_id=conversation.id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            service_type=service_type,
            scheduled_date=appointment_date,
            scheduled_time=appointment_time,
            status=AppointmentStatusEnum.pending,
            notes=notes,
        )
        
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        
        logger.info(
            f"Appointment booked: ref={booking_ref}, "
            f"date={appointment_date}, time={appointment_time}, "
            f"service={service_type}"
        )
        
        # Format confirmation message
        service_label = SERVICE_TYPE_LABELS[service_type]
        date_friendly = appointment_date.strftime("%A, %B %d, %Y")
        time_friendly = appointment_time.strftime("%-I:%M %p")
        
        confirmation_message = (
            f"Your {service_label} is scheduled for:\n"
            f"📅 {date_friendly}\n"
            f"🕐 {time_friendly}\n\n"
            f"Booking reference: {booking_ref}\n\n"
            f"We'll send you a reminder 24 hours before. "
            f"To reschedule or cancel, just let us know!"
        )
        
        # TODO Phase 8: Trigger n8n workflow for calendar invite + SMS reminder
        
        return {
            "success": True,
            "appointment_id": str(appointment.id),
            "booking_reference": booking_ref,
            "service_type": service_label,
            "date": date_friendly,
            "time": time_friendly,
            "confirmation_message": confirmation_message,
        }
        
    except Exception as e:
        logger.error(f"Error scheduling appointment: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": (
                "I ran into a problem booking that appointment. "
                "Let me get someone from our team to help you."
            )
        }