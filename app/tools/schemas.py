"""
OpenRouter Function Calling Tool Schemas - Phase 6
====================================================

JSON schemas for all 9 function calling tools.
These tell the LLM what tools are available and how to use them.

The LLM uses these schemas to decide when to call functions and
what parameters to pass.
"""

# ============================================================
# LEAD MANAGEMENT TOOLS
# ============================================================

UPDATE_LEAD_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "update_lead_status",
        "description": (
            "Update the classification of the current conversation. "
            "Call this when the customer's intent becomes clearer. "
            "Classifications: "
            "'hot' = ready to buy or placed order, "
            "'warm' = asking about specific products, "
            "'cold' = general inquiry or browsing, "
            "'post_purchase' = asking about existing order, "
            "'support' = has a problem or complaint, "
            "'spam' = irrelevant/abusive/bot messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "classification": {
                    "type": "string",
                    "enum": ["hot", "warm", "cold", "post_purchase", "support", "spam"],
                    "description": "New classification for the conversation"
                },
                "interest_area": {
                    "type": "string",
                    "description": "What product/service they're interested in (e.g., 'Portable Blender')"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional context about why classification was updated"
                }
            },
            "required": ["classification"]
        }
    }
}


# ============================================================
# ESCALATION TOOL
# ============================================================

ESCALATE_TO_HUMAN_TOOL = {
    "type": "function",
    "function": {
        "name": "escalate_to_human",
        "description": (
            "Transfer the conversation to a human agent. Call when: "
            "(1) Customer explicitly asks to speak to a person/manager, "
            "(2) Customer is frustrated, angry, or upset, "
            "(3) Request is too complex for you to handle, "
            "(4) Customer has a refund request or complaint, "
            "(5) Customer wants to cancel a SHIPPED order, "
            "(6) You genuinely cannot help with their specific need. "
            "After calling this, acknowledge the transfer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for escalation (e.g., 'Refund request', 'Angry customer')"
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "description": "Urgency: 'high' for angry/time-sensitive, 'low' for general inquiries, 'normal' otherwise"
                }
            },
            "required": ["reason"]
        }
    }
}


# ============================================================
# INVENTORY TOOLS
# ============================================================

CHECK_STOCK_TOOL = {
    "type": "function",
    "function": {
        "name": "check_stock",
        "description": (
            "Check if a specific product is in stock and get its details. "
            "Returns price, quantity available, and product information. "
            "Call when customer asks: 'Do you have X?', 'Is X available?', 'How much is Y?'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Product name to check (can be partial, will find closest match)"
                }
            },
            "required": ["product_name"]
        }
    }
}


CALCULATE_TOTAL_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate_total",
        "description": (
            "Calculate the total price for a list of items. "
            "Call when customer wants to know the total before ordering, "
            "or when confirming multiple items. "
            "Returns itemized breakdown including FREE delivery."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "List of items to calculate total for",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_name": {
                                "type": "string",
                                "description": "Name of the product"
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Quantity (default: 1)",
                                "minimum": 1,
                                "default": 1
                            }
                        },
                        "required": ["product_name"]
                    }
                }
            },
            "required": ["items"]
        }
    }
}


# ============================================================
# ORDERING TOOLS
# ============================================================

PLACE_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "place_order",
        "description": (
            "Place an order IMMEDIATELY when customer provides ALL required information: "
            "(1) customer_name, (2) delivery_address, (3) customer_phone, (4) product items. "
            "\n\nCRITICAL RULES:\n"
            "- Place order IMMEDIATELY when all 4 are provided. Do NOT ask for confirmation.\n"
            "- If customer responds to an ad with all info, place order right away.\n"
            "- Missing info? Ask only for the specific missing piece (just name, just address, or just phone).\n"
            "- NEVER ask 'are you sure?' - customers hate extra steps.\n"
            "- After placing, send the confirmation_message from the result as your reply."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Customer's full name (required)"
                },
                "delivery_address": {
                    "type": "string",
                    "description": "Full delivery address in Trinidad (street, area, city/town)"
                },
                "customer_phone": {
                    "type": "string",
                    "description": "Customer's contact number for delivery coordination"
                },
                "items": {
                    "type": "array",
                    "description": "List of items to order",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_name": {
                                "type": "string",
                                "description": "Name of the product from inventory"
                            },
                            "quantity": {
                                "type": "integer",
                                "description": "Quantity to order",
                                "minimum": 1,
                                "default": 1
                            }
                        },
                        "required": ["product_name"]
                    }
                },
                "special_instructions": {
                    "type": "string",
                    "description": "Any special delivery or order instructions (optional)"
                }
            },
            "required": ["customer_name", "delivery_address", "customer_phone", "items"]
        }
    }
}


CANCEL_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel_order",
        "description": (
            "Cancel a customer's order. Call when customer says 'cancel my order', 'I don't want it', etc. "
            "The tool handles time-based logic automatically: "
            "(1) Within 2 hours: auto-cancels + restores inventory. "
            "(2) After 2 hours but not shipped: auto-cancels + notifies manager. "
            "(3) Already shipped: escalates to human for manual handling. "
            "If order_number not provided, will cancel customer's most recent order."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "order_number": {
                    "type": "string",
                    "description": "Order number (e.g., 'TPT-260417-001'). If not provided, cancels most recent order."
                },
                "reason": {
                    "type": "string",
                    "description": "Customer's reason for cancellation (optional)"
                }
            }
        }
    }
}


# ============================================================
# SCHEDULING TOOL (built but not enabled for TrendyProductsTT)
# ============================================================

SCHEDULE_APPOINTMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "schedule_appointment",
        "description": (
            "Book an appointment for the customer. Call when customer wants to schedule "
            "a service like consultation, plumbing visit, hair appointment, etc. "
            "Required: customer name, phone, service type, date, time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "customer_name": {
                    "type": "string",
                    "description": "Customer's full name"
                },
                "customer_phone": {
                    "type": "string",
                    "description": "Customer's contact number"
                },
                "service_type": {
                    "type": "string",
                    "enum": [
                        "consultation", "beautician", "esthetician", "therapy", "medical",
                        "real_estate_viewing", "real_estate_consultation",
                        "construction_quote", "plumbing", "electrical", "carpentry",
                        "pickup", "installation", "demo", "other"
                    ],
                    "description": "Type of service being booked"
                },
                "preferred_date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format (e.g., '2026-04-25')"
                },
                "preferred_time": {
                    "type": "string",
                    "description": "Time in HH:MM format, 24-hour (e.g., '14:00' for 2pm)"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional notes or special requests (optional)"
                }
            },
            "required": ["customer_name", "customer_phone", "service_type", "preferred_date", "preferred_time"]
        }
    }
}


# ============================================================
# MEDIA TOOL
# ============================================================

SEND_PRODUCT_MEDIA_TOOL = {
    "type": "function",
    "function": {
        "name": "send_product_media",
        "description": (
            "Send customer a photo or video of a product from Instagram posts. "
            "Call when customer asks: 'Do you have a video of X?', 'Send me a picture of X', "
            "'What does X look like?', 'Can I see it?' "
            "Prefers videos if available, falls back to images."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Name of the product to send media for"
                },
                "media_type": {
                    "type": "string",
                    "enum": ["image", "video", "any"],
                    "default": "any",
                    "description": "Preferred media type"
                }
            },
            "required": ["product_name"]
        }
    }
}


# ============================================================
# TOOL REGISTRY
# ============================================================

# Master dictionary of all tools by name
ALL_TOOLS = {
    "update_lead_status": UPDATE_LEAD_STATUS_TOOL,
    "escalate_to_human": ESCALATE_TO_HUMAN_TOOL,
    "check_stock": CHECK_STOCK_TOOL,
    "calculate_total": CALCULATE_TOTAL_TOOL,
    "place_order": PLACE_ORDER_TOOL,
    "cancel_order": CANCEL_ORDER_TOOL,
    "schedule_appointment": SCHEDULE_APPOINTMENT_TOOL,
    "send_product_media": SEND_PRODUCT_MEDIA_TOOL,
}


def get_available_tools(business_dict: dict) -> list:
    """
    Returns list of tool schemas available to this business
    based on their feature flags.
    
    Args:
        business_dict: Business dict (from BusinessCache or ORM)
                      with 'features' key containing feature flags
    
    Returns:
        List of tool schema dicts ready to send to OpenRouter
    """
    features = business_dict.get('features') or {}
    
    # Core tools - all businesses get these
    tools = [
        UPDATE_LEAD_STATUS_TOOL,
        ESCALATE_TO_HUMAN_TOOL,
    ]
    
    # E-commerce tools
    if features.get('ecommerce_enabled', True):
        tools.extend([
            CHECK_STOCK_TOOL,
            CALCULATE_TOTAL_TOOL,
            PLACE_ORDER_TOOL,
            CANCEL_ORDER_TOOL,
        ])
    
    # Scheduling tool (built but not enabled for TrendyProductsTT)
    if features.get('scheduling_enabled', False):
        tools.append(SCHEDULE_APPOINTMENT_TOOL)
    
    # Media sync tool
    if features.get('media_sync_enabled', True):
        tools.append(SEND_PRODUCT_MEDIA_TOOL)
    
    return tools


def get_tool_names(business_dict: dict) -> list:
    """Returns just the names of tools available to this business."""
    tools = get_available_tools(business_dict)
    return [t['function']['name'] for t in tools]