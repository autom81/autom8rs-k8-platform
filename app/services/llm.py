"""
OpenRouter LLM Integration - UPDATED for Phase 6
=================================================
Handles model selection and client initialization.

Phase 6 Changes:
- Added tool calling support via call_llm_with_tools()
- Updated extract_reply() to return both text and tool_calls
- Added model preference for tool calling (Claude Sonnet is better at it)
"""
import logging
import uuid
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.orm import Session

from app.config import settings
from app.models.business import Business

logger = logging.getLogger(__name__)

# Initialize the OpenRouter client
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY,
)

# Model constants
MODEL_GEMMA = "google/gemma-4-26b-a4b-it"
MODEL_CLAUDE = "anthropic/claude-sonnet-4-5-20250514"


def _has_image_indicator(text: str) -> bool:
    """Check if the message indicates an image was sent."""
    indicators = ["[Image]", "[Document]", "image", "photo", "picture", "screenshot"]
    return any(ind.lower() in text.lower() for ind in indicators)


def _needs_complex_reasoning(text: str) -> bool:
    """
    Simple heuristic for routing to Claude.
    Can be made more sophisticated over time.
    """
    complex_indicators = [
        "compare", "analyze", "calculate", "summarize this document",
        "what does this image show", "read this receipt",
        "create a detailed", "step by step plan",
    ]
    text_lower = text.lower()
    return any(ind in text_lower for ind in complex_indicators)


async def select_model(
    business_id: str,
    message_text: str,
    db: Session = None,
    needs_tools: bool = False
) -> str:
    """
    Select the appropriate model based on business tier and message content.
    
    Phase 6 Addition:
    - If needs_tools=True and business is Ultra tier, prefer Claude (better tool use)
    - Gemma handles tools but Claude is more reliable for complex tool chains
    
    Starter/Pro: Always Gemma (cheap/free)
    Ultra/Custom: Claude for complex tasks OR tool calling
    """
    if db:
        business = db.query(Business).filter(
            Business.id == uuid.UUID(business_id)
        ).first()
    else:
        business = None

    tier = business.tier if business else "pro"
    # Handle both enum and string
    tier_value = tier.value if hasattr(tier, 'value') else tier

    # Starter/Pro: Always use Gemma (free tier)
    if tier_value in ("starter", "pro"):
        return MODEL_GEMMA

    # Ultra/Custom: Route to Claude for complex scenarios
    if _has_image_indicator(message_text):
        logger.info(f"Routing to Claude (image detected) for business={business_id[:8]}")
        return MODEL_CLAUDE

    if _needs_complex_reasoning(message_text):
        logger.info(f"Routing to Claude (complex reasoning) for business={business_id[:8]}")
        return MODEL_CLAUDE
    
    # Phase 6: Only use Claude for Ultra when genuinely complex reasoning needed
    # Gemma handles tool calls fine for standard conversations
    if tier_value in ("ultra", "custom") and _needs_complex_reasoning(message_text):
        logger.info(f"Routing to Claude (complex reasoning) for business={business_id[:8]}")
        return MODEL_CLAUDE


# ============================================================
# LLM CALL FUNCTIONS
# ============================================================

async def call_llm(model: str, messages: list, tools: list = None) -> Optional[dict]:
    """
    Call OpenRouter and return the response.
    
    Args:
        model: OpenRouter model identifier
        messages: List of message dicts with role/content
        tools: Optional list of tool schemas (Phase 6)
    
    Returns:
        Response object with .choices[0].message or None on error
    """
    kwargs = {
        "model": model,
        "messages": messages,
    }
    
    if tools:
        kwargs["tools"] = tools
        # Allow the model to choose when to use tools (or just respond normally)
        kwargs["tool_choice"] = "auto"

    try:
        response = await client.chat.completions.create(**kwargs)
        return response
    except Exception as e:
        logger.error(f"OpenRouter API error: {e}")
        return None


def extract_reply(response) -> dict:
    """
    Extract reply information from an OpenRouter response.
    
    Phase 6 UPDATE: Now returns a dict with both text and tool_calls.
    
    Returns:
        {
            "type": "text" | "tool_use",
            "content": str,              # Text content (empty for tool_use)
            "tool_calls": list            # List of tool calls (empty for text)
        }
    """
    default_error = {
        "type": "text",
        "content": "I'm having a little trouble right now. Please try again in a moment.",
        "tool_calls": []
    }
    
    if not response:
        return default_error
    
    try:
        choice = response.choices[0]
        message = choice.message
        
        # Check if LLM wants to use tools
        if message.tool_calls:
            logger.info(
                f"LLM returned tool calls: "
                f"{[tc.function.name for tc in message.tool_calls]}"
            )
            
            # Parse tool calls into a structured format
            tool_calls = []
            for tc in message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,  # JSON string
                })
            
            return {
                "type": "tool_use",
                "content": message.content or "",  # Sometimes has text too
                "tool_calls": tool_calls,
            }
        
        # Normal text response
        if message.content:
            return {
                "type": "text",
                "content": message.content,
                "tool_calls": []
            }
        
        # Empty response - shouldn't happen but handle it
        return {
            "type": "text",
            "content": "I'm not sure how to respond to that. Let me escalate to the team.",
            "tool_calls": []
        }
        
    except Exception as e:
        logger.error(f"Error extracting reply: {e}", exc_info=True)
        return default_error


# ============================================================
# BACKWARDS COMPATIBILITY
# Keep old extract_reply signature available as extract_text_reply
# ============================================================

def extract_text_reply(response) -> str:
    """
    Legacy: Extract only text from response (for non-tool calls).
    Kept for backwards compatibility with existing code.
    """
    result = extract_reply(response)
    return result["content"] or "I'm having a little trouble right now."