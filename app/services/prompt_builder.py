# Placeholders for DB calls (To be built later)
async def get_business(business_id):
    return type('obj', (object,), {'base_prompt': 'You are a helpful AI assistant for this business. '})()

async def get_active_products(business_id): return []
def format_inventory_section(products): return "\nInventory: [Available soon]"
async def get_customer_context(biz_id, cust_id): return None
def format_customer_context(customer): return ""
def get_ad_context_instructions(): return "\nContext: User clicked an ad."

# ==========================================
# 2.5 DYNAMIC PROMPT BUILDER
# ==========================================
async def build_system_prompt(business_id, customer_id, metadata):
    business = await get_business(business_id)
    
    # Start with static base prompt
    prompt = business.base_prompt
    
    # Add live inventory
    products = await get_active_products(business_id)
    prompt += format_inventory_section(products)
    
    # Add customer context if returning customer
    customer = await get_customer_context(business_id, customer_id)
    if customer:
        prompt += format_customer_context(customer)
    
    # Add ad context if from CTWA ad
    if metadata and metadata.get("source") == "ctwa_ad":
        prompt += get_ad_context_instructions()
    
    return prompt