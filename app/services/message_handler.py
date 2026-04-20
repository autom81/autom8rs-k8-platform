"""
Core Message Handler - UPDATED for Phase 6
===========================================

Changes from original:
- Auto-captures lead on first message
- Passes tools to LLM call
- Tool execution loop (LLM → call tool → feed result back → repeat)
- Voice note transcription via Whisper
- Uses Redis caching for business + products
- Increments conversation message_count
"""
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.conversation import Conversation, Message, ConvoStatusEnum
from app.models.business import Business
from app.services.llm import call_llm, extract_reply, select_model
from app.services.prompt_builder import build_system_prompt
from app.services.meta import send_reply, download_whatsapp_media
from app.services.cache import BusinessCache, ProductCache
from app.services.whisper import transcribe_voice_note
from app.tools.schemas import get_available_tools
from app.tools import TOOL_EXECUTORS
from app.tools.lead_capture import capture_lead

logger = logging.getLogger(__name__)

# Max number of tool call rounds before forcing a text response
MAX_TOOL_ITERATIONS = 5


# ============================================================
# DATABASE HELPERS (unchanged from original)
# ============================================================

def _get_db():
    return SessionLocal()


def get_or_create_conversation(
    db: Session,
    business_id: str,
    external_user_id: str,
    channel: str,
    metadata: dict = None,
) -> Conversation:
    convo = (
        db.query(Conversation)
        .filter(
            Conversation.business_id == uuid.UUID(business_id),
            Conversation.external_user_id == external_user_id,
            Conversation.channel == channel,
            Conversation.status.in_(["active", "escalated"]),
        )
        .first()
    )

    if convo:
        convo.last_message_at = datetime.now(timezone.utc)
        db.commit()
        return convo

    # Reopen the most recent resolved/closed conversation instead of creating a new one.
    # This keeps chat history in one continuous thread per contact.
    resolved_convo = (
        db.query(Conversation)
        .filter(
            Conversation.business_id == uuid.UUID(business_id),
            Conversation.external_user_id == external_user_id,
            Conversation.channel == channel,
            Conversation.status.in_(["resolved", "closed"]),
        )
        .order_by(Conversation.last_message_at.desc())
        .first()
    )

    if resolved_convo:
        resolved_convo.status = "active"
        resolved_convo.last_message_at = datetime.now(timezone.utc)
        db.commit()
        return resolved_convo

    source = "organic"
    if metadata and metadata.get("source") == "ctwa_ad":
        source = "ctwa_ad"

    convo = Conversation(
        id=uuid.uuid4(),
        business_id=uuid.UUID(business_id),
        external_user_id=external_user_id,
        channel=channel,
        status="active",
        source=source,
        message_count=0,
    )
    db.add(convo)
    db.commit()
    db.refresh(convo)
    return convo


def save_message(
    db: Session,
    conversation_id,
    role: str,
    content: str,
    media_url: str = None,
    media_type: str = None,
    was_voice_note: bool = False,
    original_transcript: str = None,
):
    msg = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        media_url=media_url,
        media_type=media_type,
        was_voice_note=was_voice_note,
        original_transcript=original_transcript,
    )
    db.add(msg)
    db.commit()
    return msg


def get_recent_messages(db: Session, conversation_id, limit: int = 10) -> list[dict]:
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(messages)]


def get_business(db: Session, business_id: str) -> Business:
    return db.query(Business).filter(
        Business.id == uuid.UUID(business_id)
    ).first()


# ============================================================
# TOOL EXECUTION
# ============================================================

def execute_tool(
    db: Session,
    conversation: Conversation,
    tool_name: str,
    tool_args: dict,
) -> str:
    """
    Execute a single tool call and return the result as a JSON string.
    This result gets fed back to the LLM so it can formulate a response.
    """
    executor = TOOL_EXECUTORS.get(tool_name)

    if not executor:
        logger.warning(f"Unknown tool called: {tool_name}")
        return json.dumps({
            "success": False,
            "error": f"Unknown tool: {tool_name}"
        })

    try:
        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
        result = executor(db=db, conversation=conversation, **tool_args)
        logger.info(f"Tool result: {tool_name} → {str(result)[:100]}")
        return json.dumps(result)

    except TypeError as e:
        # Wrong arguments passed to tool
        logger.error(f"Tool {tool_name} called with wrong args: {e}")
        return json.dumps({
            "success": False,
            "error": f"Invalid arguments for {tool_name}: {str(e)}"
        })
    except Exception as e:
        logger.error(f"Tool {tool_name} execution error: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Tool execution failed: {str(e)}"
        })


# ============================================================
# CORE MESSAGE HANDLER
# ============================================================

async def handle_message(
    business_id: str,
    channel: str,
    external_user_id: str,
    message_text: str,
    media_url: str = None,
    media_type: str = None,
    message_metadata: dict = None,
    phone_number_id: str = None,
    db: Session = None,
):
    """
    Process an incoming message from any channel.
    Called as a background task from the webhook handler.

    Phase 6 additions:
    - Auto-captures lead on first message
    - Builds tools list from business features
    - Tool execution loop (up to MAX_TOOL_ITERATIONS rounds)
    - Voice transcription via Whisper
    - Caching for business + product data
    """
    own_db = False
    if db is None:
        db = _get_db()
        own_db = True

    try:
        # 1. Load business (cached)
        business_dict = BusinessCache.get(db, business_id)
        if not business_dict:
            logger.error(f"Business not found: {business_id}")
            return

        # Also get ORM object for things that need it
        business = get_business(db, business_id)
        if not business:
            return

        # 2. Get or create conversation
        conversation = get_or_create_conversation(
            db, business_id, external_user_id, channel, message_metadata
        )

        # 3. If escalated, save message but don't auto-reply
        if conversation.status == ConvoStatusEnum.escalated:
            save_message(db, conversation.id, "user", message_text,
                        media_url=media_url, media_type=media_type)
            logger.info(f"Conversation {conversation.id} escalated — skipping auto-reply")
            return

        # 4. Handle voice notes via Whisper
        voice_transcript = None
        if media_type == "audio" and media_url:
            if channel == "whatsapp":
                audio_bytes = await download_whatsapp_media(media_url)
                if audio_bytes:
                    voice_transcript = await transcribe_voice_note(audio_bytes)
                    if voice_transcript:
                        message_text = voice_transcript
                        logger.info(f"Voice note transcribed: {voice_transcript[:50]}")
                    else:
                        message_text = "[Voice note received — could not transcribe]"
                else:
                    message_text = "[Voice note — could not download]"
            else:
                message_text = "[Voice note received]"

        # 5. Save user message
        save_message(
            db, conversation.id, "user", message_text,
            media_url=media_url, media_type=media_type,
            was_voice_note=(media_type == "audio"),
            original_transcript=voice_transcript,
        )

        # 6. Increment message count
        if conversation.message_count is None:
            conversation.message_count = 0
        is_first_message = conversation.message_count == 0
        conversation.message_count += 1
        db.commit()

        # 7. Auto-capture lead on first message
        if is_first_message:
            capture_lead(
                db=db,
                conversation=conversation,
                customer_phone=external_user_id if channel == "whatsapp" else None,
                initial_interest=message_text[:200] if message_text else None,
            )

        # 8. Build system prompt
        system_prompt = await build_system_prompt(
            db, business_id, external_user_id, message_metadata
        )

        # 9. Get available tools for this business
        tools = get_available_tools(business_dict)

        # 10. Load conversation history
        history = get_recent_messages(db, conversation.id, limit=10)

        # 11. Select model (prefer Claude for Ultra tier with tools)
        model = await select_model(
            business_id,
            message_text,
            db,
            needs_tools=bool(tools)
        )

        # 12. Build initial messages for LLM
        llm_messages = [
            {"role": "system", "content": system_prompt},
            *history,
        ]

        # ============================================================
        # 13. TOOL EXECUTION LOOP
        # LLM can call multiple tools before giving final response
        # Max MAX_TOOL_ITERATIONS rounds to prevent infinite loops
        # ============================================================

        reply_text = None
        media_to_send = None  # For send_product_media tool results

        for iteration in range(MAX_TOOL_ITERATIONS):

            # Call LLM
            response = await call_llm(model, llm_messages, tools=tools)
            result = extract_reply(response)

            if result["type"] == "text":
                # Strip Gemma's chain-of-thought prefix
                reply_text = result["content"]
                if reply_text.lower().startswith("thought"):
                    lines = reply_text.split("\n")
                    # Remove lines until we hit actual content
                    for i, line in enumerate(lines):
                        if line.strip() and not line.lower().startswith("thought"):
                            reply_text = "\n".join(lines[i:]).strip()
                            break
                break

            if result["type"] == "tool_use" and result["tool_calls"]:
                # LLM wants to call tools
                # Add assistant's tool call message to history
                llm_messages.append({
                    "role": "assistant",
                    "content": result.get("content") or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            }
                        }
                        for tc in result["tool_calls"]
                    ]
                })

                # Execute each tool and collect results
                tool_results = []
                for tool_call in result["tool_calls"]:
                    tool_name = tool_call["name"]

                    # Parse arguments (they come as JSON string)
                    try:
                        tool_args = json.loads(tool_call["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    # Execute the tool
                    tool_result_str = execute_tool(
                        db, conversation, tool_name, tool_args
                    )

                    # If this was send_product_media, capture the media URL
                    if tool_name == "send_product_media":
                        try:
                            media_result = json.loads(tool_result_str)
                            if media_result.get("success") and media_result.get("media_url"):
                                media_to_send = media_result
                        except Exception:
                            pass

                    tool_results.append({
                        "tool_call_id": tool_call["id"],
                        "role": "tool",
                        "content": tool_result_str,
                    })

                # Add tool results to message history for next LLM call
                llm_messages.extend(tool_results)

                # Continue loop - LLM will now respond with tool results in context
                logger.info(
                    f"Tool iteration {iteration + 1}: "
                    f"executed {[tc['name'] for tc in result['tool_calls']]}"
                )
                continue

            # Unexpected response type
            reply_text = "I'm having a little trouble right now. Please try again in a moment."
            break

        # Safety fallback if loop exhausted without text response
        if reply_text is None:
            reply_text = "I'm having a little trouble right now. Please try again in a moment."
            logger.warning(f"Tool loop exhausted after {MAX_TOOL_ITERATIONS} iterations")

        # 14. Save assistant reply
        save_message(db, conversation.id, "assistant", reply_text)

        # 15. Send reply to customer
        ig_page_id = None
        if channel == "instagram":
            ig_page_id = business.instagram_account_id

        await send_reply(
            channel=channel,
            sender_id=external_user_id,
            text=reply_text,
            phone_number_id=phone_number_id or business.meta_phone_number_id,
            page_access_token=business.meta_page_access_token,
            page_id=ig_page_id if channel == "instagram" else business.meta_waba_id,
        )

        # 16. Send media if send_product_media tool was called
        if media_to_send:
            await _send_media_message(
                channel=channel,
                sender_id=external_user_id,
                media_data=media_to_send,
                business=business,
                phone_number_id=phone_number_id,
            )

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
    finally:
        if own_db:
            db.close()


# ============================================================
# MEDIA SENDING HELPER
# ============================================================

async def _send_media_message(
    channel: str,
    sender_id: str,
    media_data: dict,
    business: Business,
    phone_number_id: str = None,
):
    """
    Send a media message (image or video) via the appropriate channel.
    Called after send_product_media tool returns a media URL.
    """
    from app.services.meta import send_whatsapp_message

    media_url = media_data.get("media_url")
    media_type = media_data.get("media_type", "image")
    caption = media_data.get("caption", "")

    if not media_url:
        return

    try:
        if channel == "whatsapp":
            import httpx
            from app.config import settings

            pid = phone_number_id or business.meta_phone_number_id
            msg_type = "video" if media_type == "video" else "image"

            async with httpx.AsyncClient() as http:
                await http.post(
                    f"https://graph.facebook.com/v21.0/{pid}/messages",
                    headers={
                        "Authorization": f"Bearer {settings.META_ACCESS_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "messaging_product": "whatsapp",
                        "to": sender_id,
                        "type": msg_type,
                        msg_type: {
                            "link": media_url,
                            "caption": caption,
                        },
                    },
                )
        # Instagram/Facebook: caption was already sent as text reply
        # Media sending via Messenger API requires different flow (TODO Phase 7)

    except Exception as e:
        logger.error(f"Error sending media message: {e}", exc_info=True)