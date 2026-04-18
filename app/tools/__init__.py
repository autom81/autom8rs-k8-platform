"""
AutoM8rs Tools Package - Phase 6
==================================

Exports all function calling tools for use by the message handler.

Architecture:
    - schemas.py: JSON schemas sent to LLM
    - lead_capture.py: capture_lead, update_lead_status
    - escalation.py: escalate_to_human
    - ordering.py: check_stock, calculate_total, place_order, cancel_order
    - scheduling.py: schedule_appointment
    - media.py: send_product_media

Usage:
    from app.tools import TOOL_EXECUTORS
    
    result = await TOOL_EXECUTORS['place_order'](db, conversation, **args)
"""

from app.tools.lead_capture import capture_lead, update_lead_status
from app.tools.escalation import escalate_to_human
from app.tools.ordering import (
    check_stock,
    calculate_total,
    place_order,
    cancel_order,
)
from app.tools.scheduling import schedule_appointment
from app.tools.media import send_product_media


# ============================================================
# TOOL EXECUTOR REGISTRY
# Maps tool name (from LLM response) to Python function
# ============================================================

TOOL_EXECUTORS = {
    # Lead management
    "update_lead_status": update_lead_status,
    
    # Escalation
    "escalate_to_human": escalate_to_human,
    
    # Inventory
    "check_stock": check_stock,
    "calculate_total": calculate_total,
    
    # Ordering
    "place_order": place_order,
    "cancel_order": cancel_order,
    
    # Scheduling (built but only enabled per-business)
    "schedule_appointment": schedule_appointment,
    
    # Media
    "send_product_media": send_product_media,
    
    # Note: capture_lead is NOT in executors - it's called automatically
    # by message_handler on first message, not triggered by LLM
}


__all__ = [
    "TOOL_EXECUTORS",
    "capture_lead",
    "update_lead_status",
    "escalate_to_human",
    "check_stock",
    "calculate_total",
    "place_order",
    "cancel_order",
    "schedule_appointment",
    "send_product_media",
]