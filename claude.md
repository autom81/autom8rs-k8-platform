# AutoM8rs K8 Platform — Backend

## What This Project Is

AutoM8rs is an AI-powered WhatsApp/Instagram/Facebook chatbot platform for Trinidad & Caribbean businesses. The backend is a FastAPI application that:

- Receives webhooks from Meta (WhatsApp, Instagram, Facebook Messenger)
- Processes messages using OpenRouter LLM (Gemma 4 free tier for Starter/Pro, Claude Sonnet for Ultra complex tasks)
- Executes function calling tools (place orders, capture leads, escalate to humans, check stock)
- Stores all data in PostgreSQL via SQLAlchemy ORM
- Caches frequently-accessed data in Redis
- Sends replies back via Meta Cloud API

**Live URL:** https://api.autom8rs.com  
**GitHub:** autom81/autom8rs-k8-platform  
**Deployment:** Coolify on VPS 76.13.25.66

---

## Infrastructure

```
VPS:          76.13.25.66 (Ubuntu 24)
App Container: kql3067wyncmoyov3r9tnbld-XXXXXXXXXX (changes on each deploy)
DB Container:  k10946z9tsdcz0abbdw4d74i (PostgreSQL 18, stable ID)
Redis:         kxypsxqnx5ki0mnjwr12wbqc (Redis 7.2, stable ID)
n8n:           n8n-ick8sg44s8o4w80wg0wckssg
```

**To get current app container name:**
```bash
docker ps | grep uvicorn
```

**To connect to PostgreSQL:**
```bash
docker exec -it k10946z9tsdcz0abbdw4d74i psql -U postgres -d postgres
```

**To view app logs:**
```bash
docker logs <container-name> --tail 50
```

---

## Project Structure

```
autom8rs-k8-platform/
├── alembic/
│   ├── env.py                    # Alembic environment (reads DATABASE_URL from app.config)
│   ├── script.py.mako            # Migration template
│   └── versions/
│       ├── 0001_phase6_initial.py  # Phase 6 migrations (COMPLETED)
│       └── 0002_phase7_dashboard.py  # Phase 7 migrations (TODO)
├── alembic.ini                   # Alembic config
├── app/
│   ├── models/
│   │   ├── __init__.py           # Imports ALL models (critical for Alembic)
│   │   ├── business.py           # Business, Product, N8nWorkflow
│   │   ├── conversation.py       # Conversation, Message
│   │   ├── lead.py               # Lead, Order
│   │   ├── appointment.py        # Appointment (Phase 6)
│   │   ├── media.py              # MediaLibrary (Phase 6)
│   │   ├── template_tracking.py  # TemplateSend
│   │   └── user.py               # User (Phase 7 - TODO)
│   ├── routes/
│   │   ├── webhooks.py           # Meta webhook handler (/api/meta/webhook)
│   │   ├── admin.py              # Admin routes (/admin/*)
│   │   ├── auth.py               # Auth routes (/auth/*) (Phase 7 - TODO)
│   │   ├── dashboard.py          # Dashboard API (/api/*) (Phase 7 - TODO)
│   │   ├── analytics.py          # Analytics API (/api/analytics/*) (Phase 7 - TODO)
│   │   ├── settings.py           # Settings API (/api/settings/*) (Phase 7 - TODO)
│   │   ├── team.py               # Team API (/api/team/*) (Phase 7B - TODO)
│   │   └── broadcasts.py         # Broadcasts API (/api/broadcasts/*) (Phase 7C - TODO)
│   ├── services/
│   │   ├── llm.py                # OpenRouter LLM integration + model selection
│   │   ├── message_handler.py    # Core message processing + tool execution loop
│   │   ├── prompt_builder.py     # Dynamic system prompt assembly
│   │   ├── meta.py               # Meta Cloud API (send/receive WhatsApp/IG/FB)
│   │   ├── cache.py              # Redis caching (BusinessCache, ProductCache)
│   │   ├── whisper.py            # OpenAI Whisper voice transcription
│   │   ├── instagram_sync.py     # Instagram #AutoM8 post ingestion
│   │   └── auth_service.py       # Password hashing + JWT (Phase 7 - TODO)
│   ├── tools/
│   │   ├── __init__.py           # TOOL_EXECUTORS registry
│   │   ├── schemas.py            # OpenRouter tool JSON schemas
│   │   ├── lead_capture.py       # capture_lead(), update_lead_status()
│   │   ├── escalation.py         # escalate_to_human()
│   │   ├── ordering.py           # check_stock(), calculate_total(), place_order(), cancel_order()
│   │   ├── scheduling.py         # schedule_appointment()
│   │   └── media.py              # send_product_media()
│   ├── utils/
│   │   └── tokens.py             # Token counting (tiktoken)
│   ├── config.py                 # Settings from .env (Pydantic BaseSettings)
│   ├── database.py               # SQLAlchemy engine + SessionLocal + Base
│   └── main.py                   # FastAPI app + Alembic auto-migration on startup
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

---

## Database Patterns — CRITICAL

### ORM Style
This project uses **synchronous SQLAlchemy ORM**. Do NOT use asyncpg, do NOT use raw SQL strings in Python code (SQL only in Alembic migrations).

```python
# CORRECT - sync SQLAlchemy ORM
from sqlalchemy.orm import Session
from app.models.business import Business

def get_business(db: Session, business_id: str) -> Business:
    return db.query(Business).filter(
        Business.id == uuid.UUID(business_id)
    ).first()

# WRONG - do not do this
import asyncpg
conn = await asyncpg.connect(...)
```

### Session Management
Background tasks create their own sessions:

```python
from app.database import SessionLocal

def _get_db():
    return SessionLocal()

# In background task:
db = _get_db()
try:
    # do work
    db.commit()
finally:
    db.close()
```

Route handlers use FastAPI dependency injection:

```python
from app.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

@router.get("/something")
def my_route(db: Session = Depends(get_db)):
    ...
```

### UUID Handling
All IDs are UUID objects. Always convert string to UUID when querying:

```python
Business.id == uuid.UUID(business_id)  # CORRECT
Business.id == business_id             # WRONG - will fail
```

### Creating Records
```python
record = Model(
    id=uuid.uuid4(),
    field=value,
)
db.add(record)
db.commit()
db.refresh(record)
return record
```

---

## Migrations — CRITICAL

**We use Alembic. Do NOT use `Base.metadata.create_all()` for schema changes.**

`main.py` runs `alembic upgrade head` automatically on startup. Any new migration file committed to the repo will be applied on next deploy.

### Creating a New Migration
```bash
# Inside the app container:
docker exec -it <container-name> bash
alembic revision --autogenerate -m "description_of_change"
# Review the generated file, then commit it to git
```

### Applying Migrations Manually
```bash
docker exec -it <container-name> bash
alembic upgrade head
alembic current  # verify
```

### Migration File Rules
- Every new model or column change needs a migration
- Always include both `upgrade()` and `downgrade()` functions
- Use `IF NOT EXISTS` patterns for safety
- New enum types: use `DO $$ BEGIN IF NOT EXISTS ... END $$` pattern
- File naming: `NNNN_description.py` (e.g. `0002_phase7_dashboard.py`)

### Important: Adding New Models
Every new model file MUST be imported in `app/models/__init__.py` or Alembic won't detect it.

---

## Environment Variables

All environment variables are in `.env` (not committed to git). Accessed via `app.config.settings`:

```python
from app.config import settings

settings.DATABASE_URL          # PostgreSQL connection string
settings.REDIS_URL             # Redis connection string
settings.OPENROUTER_API_KEY    # OpenRouter API key
settings.META_VERIFY_TOKEN     # Meta webhook verify token
settings.META_ACCESS_TOKEN     # Meta API access token
settings.META_APP_SECRET       # Meta app secret for signature verification
settings.META_IG_APP_SECRET    # Instagram app secret
settings.WHISPER_API_KEY       # OpenAI Whisper API key (optional)
settings.JWT_SECRET            # JWT signing secret
settings.JWT_ALGORITHM         # "HS256"
settings.JWT_EXPIRY_HOURS      # 24
```

**To add a new environment variable:**
1. Add to `app/config.py` Settings class
2. Add to `.env` file on the server
3. Add to Coolify environment variables in the dashboard

---

## LLM Integration

**OpenRouter** is used for all LLM calls via OpenAI-compatible API.

```
Base URL: https://openrouter.ai/api/v1
Models:
  Gemma (Starter/Pro): google/gemma-4-26b-a4b-it
  Claude (Ultra complex): anthropic/claude-sonnet-4-5
```

### Model Selection Logic
- Starter/Pro tier: Always Gemma (free tier)
- Ultra/Custom: Gemma by default, Claude only for complex reasoning (not for all tool calls)

### Tool Calling
Tools are passed as JSON schemas to the LLM. The tool execution loop (max 5 iterations) is in `message_handler.py`. All tool functions are in `app/tools/`.

### Gemma Thought Stripping
Gemma leaks chain-of-thought text starting with "thought". The message handler strips this before sending to customers.

---

## Caching

Redis caching is in `app/services/cache.py`:

```python
from app.services.cache import BusinessCache, ProductCache

# Get (with DB fallback if cache miss)
business = BusinessCache.get(db, business_id)
products = ProductCache.get_products(db, business_id)

# Invalidate when data changes
BusinessCache.invalidate(business_id)
ProductCache.invalidate(business_id)
```

**TTLs:** Business=1hr, Products=5min, Conversations=1min

---

## Key Business Logic

### Ordering Flow
Orders require: `customer_name` + `delivery_address` + `customer_phone`. All three must be present before `place_order()` is called. The bot asks for missing pieces one at a time.

### Order Number Format
`{order_prefix}-YYMMDD-XXX` (e.g., `TPT-260418-001`)

### Cancellation Logic
- Within 2 hours: auto-cancel + restore inventory
- After 2 hours, pending: auto-cancel + notify manager (TODO: n8n webhook)
- Shipped: escalate_to_human(urgency="high")

### Lead Classification
Every conversation auto-captures a lead on first message with `classification='cold'`. LLM updates via `update_lead_status()` tool.

### Feature Flags
Per-business tool enablement via `business.features` JSONB:
```json
{
  "ecommerce_enabled": true,
  "scheduling_enabled": false,
  "media_sync_enabled": true
}
```

---

## First Client: TrendyProductsTT

```
business_id: d510b8d0-9316-4e34-8edb-bc07a7de7568
tier: ultra
order_prefix: TPT
founding_member: #1
features: ecommerce_enabled=true, scheduling_enabled=false, media_sync_enabled=true
```

---

## Deployment Workflow

```
1. Edit code in VS Code locally
2. git add . && git commit -m "message" && git push
3. Go to Coolify dashboard → Redeploy (or auto-deploys if webhook configured)
4. On container startup: Alembic migrations run automatically
5. Check logs: docker logs <new-container-name> --tail 50
```

**Get new container name after deploy:**
```bash
docker ps | grep uvicorn
# Output: <container-name>   "uvicorn app.main:app..."
```

---

## Coding Conventions

### Route Handlers
```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()

@router.get("/api/something")
def get_something(db: Session = Depends(get_db)):
    ...
```

### Background Tasks (for webhook handlers)
```python
from fastapi import BackgroundTasks

@router.post("/api/meta/webhook")
async def webhook(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    background_tasks.add_task(handle_message, business_id=..., db=db)
    return {"status": "received"}  # Return 200 immediately to Meta
```

### Error Handling
```python
import logging
logger = logging.getLogger(__name__)

try:
    # operation
    db.commit()
except Exception as e:
    logger.error(f"Error doing X: {e}", exc_info=True)
    db.rollback()
    raise HTTPException(status_code=500, detail="Internal error")
```

### Pydantic Models for Request/Response
```python
from pydantic import BaseModel
from typing import Optional

class UpdateProductRequest(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    quantity: Optional[int] = None
```

---

## What NOT To Do

- Do NOT use `Base.metadata.create_all()` for schema changes — use Alembic migrations
- Do NOT use asyncpg or raw database connections — use SQLAlchemy ORM
- Do NOT hardcode UUIDs or credentials in code
- Do NOT commit `.env` files
- Do NOT call `openrouter_client` directly from routes — use `app.services.llm`
- Do NOT modify existing enum values (can only add new values, not remove)
- Do NOT skip the `app/models/__init__.py` import when adding new models
- Do NOT send large payloads to LLM — use caching and condensed product formats

---

## Phase Status

- ✅ Phase 1-5: Basic bot functionality
- ✅ Phase 6: Function calling tools, caching, Alembic, Instagram sync, voice transcription
- 🔄 Phase 7: Dashboard (in progress)
- ⏳ Phase 8: n8n workflows (order notifications, escalation alerts)
- ⏳ Phase 9: WooCommerce sync integration
- ⏳ Phase 10: Shopify integration, custom webhook endpoint
