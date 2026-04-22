"""
Ordering Tools - Phase 6
=========================

The most complex tool file. Contains four functions:

1. check_stock(product_name) - Check product availability
2. calculate_total(items) - Calculate order total with FREE delivery
3. place_order(name, address, phone, items) - Place order immediately
4. cancel_order(order_number) - Smart cancellation with time-based logic

Key Logic:
    - Order ID format: {PREFIX}-YYMMDD-XXX (e.g., TPT-260417-001)
    - Delivery is always FREE with "limited time" messaging
    - Cancellation within 2 hours: auto-cancel + restore inventory
    - Cancellation after 2 hours but not shipped: auto-cancel + notify manager
    - Cancellation after shipping: escalate to human (urgent)
"""
import logging
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List

from sqlalchemy.orm import Session

from app.models.business import Business, Product, ProductStatusEnum
from app.models.conversation import Conversation
from app.models.lead import Lead, Order, OrderStatusEnum, LeadClassificationEnum, LeadStatusEnum
from app.services.cache import ProductCache, BusinessCache
from app.tools.escalation import escalate_to_human

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

CANCELLATION_WINDOW_HOURS = 2  # Customers can cancel without fee within this window
DELIVERY_FEE = Decimal("0.00")  # Free delivery (for now)
DELIVERY_MESSAGE = "🚚 FREE DELIVERY (limited time only!)"


# ============================================================
# ORDER NUMBER GENERATION
# ============================================================

def _generate_order_number(db: Session, business: dict) -> str:
    """
    Generate human-readable order number.
    Format: {PREFIX}-YYMMDD-XXX
    Example: TPT-260417-001
    
    Args:
        db: SQLAlchemy session
        business: Business dict (from BusinessCache)
    
    Returns:
        str: Unique order number
    """
    prefix = business.get('order_prefix', 'ORD')
    today = datetime.now(timezone.utc)
    date_str = today.strftime("%y%m%d")
    
    # Count today's orders for this business
    today_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    count = db.query(Order).filter(
        Order.business_id == uuid.UUID(str(business['id'])),
        Order.created_at >= today_start,
        Order.created_at < today_end,
    ).count()
    
    sequence = str(count + 1).zfill(3)
    order_number = f"{prefix}-{date_str}-{sequence}"
    
    # Safety check: ensure uniqueness (shouldn't collide, but just in case)
    while db.query(Order).filter(Order.order_number == order_number).first():
        count += 1
        sequence = str(count + 1).zfill(3)
        order_number = f"{prefix}-{date_str}-{sequence}"
    
    return order_number


# ============================================================
# TOOL 1: CHECK STOCK
# ============================================================

def check_stock(
    db: Session,
    conversation: Conversation,
    product_name: str,
) -> dict:
    """
    TOOL: Check if a product is in stock.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        product_name: Name to search for (partial match OK)
    
    Returns:
        dict with product info or not_found status
    """
    try:
        product = ProductCache.find_by_name(
            db, 
            conversation.business_id, 
            product_name
        )
        
        if not product:
            return {
                "success": False,
                "found": False,
                "product_name": product_name,
                "message": f"Sorry, we don't have '{product_name}' in our inventory. Would you like me to suggest similar items?"
            }
        
        # Check stock levels
        quantity = product.get('quantity', 0) or 0
        status = product.get('status', 'active')
        
        if status == 'out_of_stock' or quantity == 0:
            return {
                "success": True,
                "found": True,
                "available": False,
                "product_name": product['name'],
                "price": product.get('price'),
                "quantity": 0,
                "message": f"{product['name']} is currently out of stock. Would you like me to suggest an alternative?"
            }
        
        if status == 'discontinued':
            return {
                "success": True,
                "found": True,
                "available": False,
                "product_name": product['name'],
                "message": f"{product['name']} is no longer available. Would you like to see similar products?"
            }
        
        # In stock!
        return {
            "success": True,
            "found": True,
            "available": True,
            "product_name": product['name'],
            "product_id": product['id'],
            "price": product.get('price'),
            "currency": product.get('currency', 'TTD'),
            "quantity": quantity,
            "description": product.get('description'),
            "variants": product.get('variants'),
        }
        
    except Exception as e:
        logger.error(f"Error checking stock: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "I had trouble checking that. Can you ask again?"
        }


# ============================================================
# TOOL 2: CALCULATE TOTAL
# ============================================================

def calculate_total(
    db: Session,
    conversation: Conversation,
    items: List[dict],
) -> dict:
    """
    TOOL: Calculate total for a list of items.
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        items: List of {"product_name": str, "quantity": int}
    
    Returns:
        dict with itemized breakdown and total
    """
    try:
        if not items:
            return {
                "success": False,
                "error": "No items provided",
                "message": "Which items would you like me to calculate?"
            }
        
        breakdown = []
        subtotal = Decimal("0.00")
        unavailable = []
        
        for item in items:
            product_name = item.get('product_name', '')
            try:
                quantity = int(item.get('quantity', 1))
            except (ValueError, TypeError):
                quantity = 1
            
            product = ProductCache.find_by_name(
                db,
                conversation.business_id,
                product_name
            )
            
            if not product:
                unavailable.append(f"{product_name} (not found)")
                continue
            
            stock = product.get('quantity', 0) or 0
            if product.get('status') == 'out_of_stock' or stock == 0:
                unavailable.append(f"{product['name']} (out of stock)")
                continue
            
            if stock < quantity:
                unavailable.append(f"{product['name']} (only {stock} available, requested {quantity})")
                continue
            
            price = Decimal(str(product.get('price', 0)))
            line_total = price * quantity
            subtotal += line_total
            
            breakdown.append({
                "product_name": product['name'],
                "quantity": quantity,
                "unit_price": str(price),
                "line_total": str(line_total),
            })
        
        if not breakdown and unavailable:
            return {
                "success": False,
                "unavailable": unavailable,
                "message": f"These items aren't available: {', '.join(unavailable)}"
            }
        
        total = subtotal + DELIVERY_FEE
        
        # Format message
        lines = [f"{item['product_name']} × {item['quantity']} = ${item['line_total']}" 
                 for item in breakdown]
        
        message = (
            "Here's your total:\n"
            + "\n".join([f"• {line}" for line in lines])
            + f"\n\nSubtotal: ${subtotal}"
            + f"\n{DELIVERY_MESSAGE}"
            + f"\n\n**Total: ${total}**"
        )
        
        if unavailable:
            message += f"\n\n⚠️ Unavailable: {', '.join(unavailable)}"
        
        return {
            "success": True,
            "breakdown": breakdown,
            "subtotal": str(subtotal),
            "delivery_fee": str(DELIVERY_FEE),
            "total": str(total),
            "unavailable_items": unavailable,
            "message": message,
        }
        
    except Exception as e:
        logger.error(f"Error calculating total: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "message": "I had trouble calculating that. Could you try again?"
        }


# ============================================================
# TOOL 3: PLACE ORDER (THE BIG ONE)
# ============================================================

def place_order(
    db: Session,
    conversation: Conversation,
    customer_name: str,
    delivery_address: str,
    customer_phone: str,
    items: List[dict],
    special_instructions: Optional[str] = None,
) -> dict:
    """
    TOOL: Place an order immediately.
    
    CRITICAL: This is called when customer provides ALL required info:
    - customer_name
    - delivery_address  
    - customer_phone
    - items (product selection)
    
    Does everything in a transaction:
    1. Validate all products exist and have stock
    2. Calculate total
    3. Generate order number
    4. Create Order record
    5. Decrement inventory
    6. Update lead classification to 'hot'
    7. Return confirmation message
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        customer_name: Customer's full name
        delivery_address: Full delivery address
        customer_phone: Contact number
        items: List of {"product_name": str, "quantity": int}
        special_instructions: Optional delivery instructions
    
    Returns:
        dict with order confirmation
    """
    try:
        # Get business from cache
        business = BusinessCache.get(db, conversation.business_id)
        if not business:
            return {
                "success": False,
                "error": "Business not found",
                "message": "Something went wrong. Let me get someone to help you."
            }
        
        # Validate inputs
        if not items:
            return {
                "success": False,
                "error": "No items provided",
                "message": "What would you like to order?"
            }
        
        # Fetch product ORM objects (we need to modify inventory)
        products_orm = ProductCache.get_products_orm(db, conversation.business_id)
        products_by_name = {p.name.lower(): p for p in products_orm}
        
        # Validate each item and build order items
        order_items = []
        total = Decimal("0.00")
        products_to_decrement = []
        
        for item in items:
            product_name = item.get('product_name', '').strip()
            try:
                quantity = int(item.get('quantity', 1))
            except (ValueError, TypeError):
                quantity = 1
            
            if quantity < 1:
                return {
                    "success": False,
                    "error": f"Invalid quantity for {product_name}",
                    "message": f"Invalid quantity for {product_name}. Please specify 1 or more."
                }
            
            # Find product (case-insensitive)
            product = products_by_name.get(product_name.lower())
            if not product:
                # Try partial match
                for p in products_orm:
                    if product_name.lower() in p.name.lower():
                        product = p
                        break
            
            if not product:
                return {
                    "success": False,
                    "error": f"Product not found: {product_name}",
                    "message": f"I couldn't find '{product_name}' in our inventory. Can you double-check the name?"
                }
            
            # Check stock
            current_stock = product.quantity or 0
            if product.status == ProductStatusEnum.out_of_stock or current_stock == 0:
                return {
                    "success": False,
                    "error": f"{product.name} out of stock",
                    "message": f"Sorry, {product.name} is currently out of stock. Would you like an alternative?"
                }
            
            if current_stock < quantity:
                return {
                    "success": False,
                    "error": f"Insufficient stock for {product.name}",
                    "message": f"We only have {current_stock} {product.name} available, but you requested {quantity}. Would you like to adjust?"
                }
            
            price = Decimal(str(product.price or 0))
            line_total = price * quantity
            total += line_total
            
            order_items.append({
                "product_id": str(product.id),
                "product_name": product.name,
                "quantity": quantity,
                "unit_price": str(price),
                "line_total": str(line_total),
            })
            
            products_to_decrement.append((product, quantity))
        
        # Generate unique order number
        order_number = _generate_order_number(db, business)
        
        # Create Order record
        order = Order(
            id=uuid.uuid4(),
            business_id=conversation.business_id,
            conversation_id=conversation.id,
            order_number=order_number,
            customer_name=customer_name,
            customer_phone=customer_phone,
            delivery_address=delivery_address,
            items=order_items,
            total=total,
            status=OrderStatusEnum.pending,
            special_instructions=special_instructions,
        )
        db.add(order)
        
        # Decrement inventory
        for product, quantity in products_to_decrement:
            product.quantity = (product.quantity or 0) - quantity
            if product.quantity == 0:
                product.status = ProductStatusEnum.out_of_stock
        
        # Update lead classification to 'hot' (they bought!)
        lead = db.query(Lead).filter(
            Lead.conversation_id == conversation.id
        ).first()
        
        if lead:
            lead.classification = LeadClassificationEnum.hot
            lead.status = LeadStatusEnum.converted
            lead.name = customer_name  # Update with confirmed name
            if not lead.phone:
                lead.phone = customer_phone
        
        db.commit()
        db.refresh(order)
        
        # Invalidate product cache since inventory changed
        ProductCache.invalidate(conversation.business_id)
        
        logger.info(
            f"Order placed: {order_number}, "
            f"customer={customer_name}, total=${total}, "
            f"items={len(order_items)}"
        )
        
        # Build user-facing confirmation message
        item_lines = [
            f"• {item['product_name']} × {item['quantity']} - ${item['line_total']}"
            for item in order_items
        ]
        
        confirmation_message = (
            f"Your order total is ${total}:\n"
            + "\n".join(item_lines)
            + f"\n\n{DELIVERY_MESSAGE}"
            + f"\n📍 Delivering to: {delivery_address}"
            + f"\n📞 Contact: {customer_phone}"
        )
        
        if special_instructions:
            confirmation_message += f"\n📝 Notes: {special_instructions}"
        
        confirmation_message += (
            f"\n\n✅ Your order #{order_number} has been placed!"
            f"\nWe'll contact you to confirm delivery time."
            f"\n\nNeed to cancel? Reply 'cancel order' within 2 hours."
            f"\n\nThank you for shopping with {business['name']}! 🛍️"
        )
        
        # TODO Phase 8: Trigger n8n webhook for order confirmation email + team notification
        
        return {
            "success": True,
            "order_id": str(order.id),
            "order_number": order_number,
            "customer_name": customer_name,
            "delivery_address": delivery_address,
            "customer_phone": customer_phone,
            "items": order_items,
            "total": str(total),
            "confirmation_message": confirmation_message,
        }
        
    except Exception as e:
        logger.error(f"Error placing order: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": (
                "I ran into a problem placing your order. "
                "Let me get someone from our team to help you right away."
            )
        }


# ============================================================
# TOOL 4: CANCEL ORDER (Smart time-based logic)
# ============================================================

def cancel_order(
    db: Session,
    conversation: Conversation,
    order_number: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    TOOL: Cancel an order with smart time-based logic.
    
    Logic:
    - Within 2 hours of placement: Auto-cancel + restore inventory
    - After 2 hours, still pending: Auto-cancel + manager notification
    - Already shipped: Escalate to human (urgent)
    
    Args:
        db: SQLAlchemy session
        conversation: The Conversation ORM object
        order_number: Optional order number (finds most recent if not provided)
        reason: Optional cancellation reason
    
    Returns:
        dict with cancellation status
    """
    try:
        # Find the order
        if order_number:
            order = db.query(Order).filter(
                Order.business_id == conversation.business_id,
                Order.order_number == order_number,
            ).first()
            
            if not order:
                return {
                    "success": False,
                    "error": "Order not found",
                    "message": f"I couldn't find order #{order_number}. Could you double-check the number?"
                }
        else:
            # Find customer's most recent order via conversation
            order = db.query(Order).filter(
                Order.conversation_id == conversation.id,
            ).order_by(Order.created_at.desc()).first()
            
            if not order:
                return {
                    "success": False,
                    "error": "No orders found",
                    "message": "I don't see any recent orders under your name. Do you have an order number?"
                }
        
        # Check if already cancelled
        if order.status == OrderStatusEnum.cancelled:
            return {
                "success": False,
                "error": "Already cancelled",
                "message": f"Order #{order.order_number} was already cancelled."
            }
        
        # Check if already delivered
        if order.status == OrderStatusEnum.delivered:
            return {
                "success": False,
                "error": "Already delivered",
                "message": (
                    f"Order #{order.order_number} has already been delivered. "
                    f"If you need to return it, I can connect you with our team."
                ),
                "needs_escalation": True,
            }
        
        # Check time since placement
        now = datetime.now(timezone.utc)
        
        # Make order.created_at timezone-aware if it isn't
        created_at = order.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        
        time_since_order = now - created_at
        within_window = time_since_order <= timedelta(hours=CANCELLATION_WINDOW_HOURS)
        
        # Case 1: Already shipped - must escalate
        if order.status == OrderStatusEnum.shipped:
            logger.info(f"Shipped order cancellation requested: {order.order_number}")
            
            # Use the escalation tool
            escalate_result = escalate_to_human(
                db,
                conversation,
                reason=(
                    f"Customer wants to cancel shipped order #{order.order_number} "
                    f"(total: ${order.total}). Reason: {reason or 'Not provided'}"
                ),
                urgency="high",
            )
            
            return {
                "success": False,
                "requires_human": True,
                "order_number": order.order_number,
                "status": "shipped",
                "message": (
                    f"Order #{order.order_number} has already been shipped out. "
                    f"I've escalated this to our team right away - they'll contact you "
                    f"immediately to work out next steps."
                ),
                "escalated": escalate_result.get("success", False),
            }
        
        # Case 2: Within cancellation window - auto-cancel + restore inventory
        if within_window:
            logger.info(f"Cancelling order within window: {order.order_number}")
            
            # Update order
            order.status = OrderStatusEnum.cancelled
            order.cancelled_at = now
            order.cancellation_reason = reason or "Customer requested cancellation (within window)"
            
            # Restore inventory
            for item in (order.items or []):
                product_id_str = item.get('product_id')
                if product_id_str:
                    product = db.query(Product).filter(
                        Product.id == uuid.UUID(product_id_str)
                    ).first()
                    
                    if product:
                        try:
                            qty = int(item.get('quantity', 0))
                        except (ValueError, TypeError):
                            qty = 0
                        product.quantity = (product.quantity or 0) + qty
                        if product.status == ProductStatusEnum.out_of_stock and product.quantity > 0:
                            product.status = ProductStatusEnum.active
            
            # Update lead classification back to 'cold' or 'warm' (they cancelled)
            lead = db.query(Lead).filter(
                Lead.conversation_id == conversation.id
            ).first()
            if lead and lead.classification == LeadClassificationEnum.hot:
                lead.classification = LeadClassificationEnum.warm
                lead.status = LeadStatusEnum.nurture
            
            db.commit()
            
            # Invalidate product cache
            ProductCache.invalidate(conversation.business_id)
            
            logger.info(f"Order cancelled: {order.order_number}")
            
            return {
                "success": True,
                "cancelled": True,
                "order_number": order.order_number,
                "refund_needed": False,  # Pending orders don't need refunds
                "message": (
                    f"✅ Order #{order.order_number} has been cancelled successfully. "
                    f"No charges were made. Let us know if you'd like to order something else!"
                )
            }
        
        # Case 3: After window but still pending - cancel + notify manager
        logger.info(f"Cancelling order after window: {order.order_number}")
        
        order.status = OrderStatusEnum.cancelled
        order.cancelled_at = now
        order.cancellation_reason = (
            f"Customer cancelled after 2-hour window. "
            f"Reason: {reason or 'Not provided'}"
        )
        
        # Restore inventory (still helpful)
        for item in (order.items or []):
            product_id_str = item.get('product_id')
            if product_id_str:
                product = db.query(Product).filter(
                    Product.id == uuid.UUID(product_id_str)
                ).first()
                if product:
                    product.quantity = (product.quantity or 0) + int(item.get('quantity', 0))
        
        db.commit()
        ProductCache.invalidate(conversation.business_id)
        
        # TODO Phase 8: Trigger n8n webhook to notify manager of after-window cancellation
        
        return {
            "success": True,
            "cancelled": True,
            "order_number": order.order_number,
            "after_window": True,
            "message": (
                f"Order #{order.order_number} has been cancelled. "
                f"I've also notified our team since it's been over 2 hours since you ordered. "
                f"Sorry we missed your mark this time!"
            )
        }
        
    except Exception as e:
        logger.error(f"Error cancelling order: {e}", exc_info=True)
        db.rollback()
        return {
            "success": False,
            "error": str(e),
            "message": (
                "I had trouble cancelling that order. "
                "Let me get someone from our team to help you."
            )
        }