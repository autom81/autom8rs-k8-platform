from openai import AsyncOpenAI
from app.config import settings

# Initialize the OpenRouter client using the secure settings file
client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.OPENROUTER_API_KEY
)

# Placeholders for logic checks (To be built later)
async def get_business(business_id):
    return type('obj', (object,), {'tier': 'pro'})()

def has_image(text): return False
def needs_complex_reasoning(text): return False

# ==========================================
# 2.6 OPENROUTER INTEGRATION
# ==========================================
async def select_model(business_id, message_text):
    business = await get_business(business_id)
    
    if business.tier in ["starter", "pro"]:
        return "google/gemma-4-26b-a4b-it"
    
    # Ultra/Custom: route complex tasks to Claude
    if has_image(message_text):
        return "anthropic/claude-sonnet-4.5"
    if needs_complex_reasoning(message_text):
        return "anthropic/claude-sonnet-4.5"
    
    return "google/gemma-4-26b-a4b-it"  # Default to cheap model