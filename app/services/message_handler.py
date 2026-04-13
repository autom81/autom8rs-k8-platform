import logging

logger = logging.getLogger(__name__)

# ==========================================
# PLACEHOLDER HELPERS (To be built in Phase 3/4)
# ==========================================
class MockResult:
    def __init__(self):
        self.reply = "This is a placeholder reply."

class MockBusiness:
    tier = "pro"

async def get_or_create_conversation(business_id, external_user_id, channel, metadata): 
    # Mocks a conversation object so the status check works
    return type('obj', (object,), {'id': '123', 'status': 'active'})()

async def save_message(conv_id, role, text): pass
async def notify_owner_of_new_message(conv): pass
async def transcribe_voice(url): return "Transcribed text"
async def build_system_prompt(biz_id, user_id, meta): return "You are a helpful AI."
async def get_recent_messages(conv_id, limit=10): return []
async def select_model(biz_id, text): return "openrouter-model"
async def get_tools_for_tier(tier): return []
async def process_llm_response(resp, conv, biz_id): return MockResult()
async def send_reply(channel, user_id, reply): pass


# ==========================================
# 2.4 CORE MESSAGE HANDLER
# ==========================================
async def handle_message(
    business_id: str,
    channel: str,
    external_user_id: str,
    message_text: str,
    media_url: str = None,
    media_type: str = None,
    message_metadata: dict = None  # Contains ad source, etc.
):
    # 1. Get or create conversation
    conversation = await get_or_create_conversation(
        business_id, external_user_id, channel, message_metadata
    )

    # 2. Check if escalated — if so, don’t auto-reply
    if conversation.status == "escalated":
        await save_message(conversation.id, "user", message_text)
        await notify_owner_of_new_message(conversation)
        return  # Human is handling this conversation

    # 3. Handle voice notes (Pro+)
    if media_type == "audio":
        message_text = await transcribe_voice(media_url)

    # 4. Build dynamic system prompt
    system_prompt = await build_system_prompt(
        business_id, external_user_id, message_metadata
    )

    # 5. Load conversation history (last 10 messages)
    history = await get_recent_messages(conversation.id, limit=10)

    # 6. Build messages array for LLM
    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": message_text}
    ]

    # 7. Select model based on tier + complexity
    model = await select_model(business_id, message_text)

    # 8. Call OpenRouter with function calling tools
    business = MockBusiness() # Mocked for now
    tools = await get_tools_for_tier(business.tier)
    
    # Placeholder for the actual OpenRouter API call
    response = {"status": "mock_response"} 

    # 9. Process response — may include function calls
    result = await process_llm_response(
        response, conversation, business_id
    )

    # 10. Save messages to DB
    await save_message(conversation.id, "user", message_text)
    await save_message(conversation.id, "assistant", result.reply)

    # 11. Send reply via same channel
    await send_reply(channel, external_user_id, result.reply)
    
    return result.reply