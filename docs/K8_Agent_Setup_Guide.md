# AutoM8rs K8 Agent — Complete Setup & Progress Guide

**Last Updated: April 2026 | First Client: TrendyProductsTT (Ultra)**

---

## Platform Status Overview

| Phase | Description | Status |
|---|---|---|
| 1 | Infrastructure (VPS, Coolify, PostgreSQL, Redis) | ✅ COMPLETE |
| 2 | Platform Core (FastAPI, SQLAlchemy, OpenRouter) | ✅ COMPLETE |
| 3 | Meta Integration (WhatsApp, Messenger, Instagram DM webhooks) | ✅ COMPLETE (dev mode) |
| 4 | First Client — TrendyProductsTT registered & configured | ✅ COMPLETE |
| 5 | Channel Testing (WhatsApp live, Messenger/IG DM working) | ✅ COMPLETE |
| 6 | Function Calling Tools (9 tools, Instagram sync, Whisper) | ✅ COMPLETE |
| 7 | Dashboard (all 12 pages live at dashboard.autom8rs.com) | ✅ COMPLETE |
| 8 | Native Workflow Engine (replaced n8n — 10 triggers, 8 actions) | ✅ COMPLETE |
| 9 | Broadcasts Backend (templates, campaigns, scheduling, send) | ✅ COMPLETE |
| 10 | Meta App Review (go live outside dev mode) | 🔴 NEXT — BLOCKER |
| 11 | Instagram Comment Automation (reply to comments, DM commenters) | ✅ CODE BUILT — needs Phase 10 live |
| 12 | Telegram + Website Widget | ⏳ FUTURE |
| 13 | WooCommerce Sync + Shopify | ⏳ FUTURE |

---

## Infrastructure

```
VPS:            76.13.25.66 (Ubuntu 24, Hostinger)
Backend:        https://api.autom8rs.com  (FastAPI, Coolify auto-deploy)
Dashboard:      https://dashboard.autom8rs.com (Next.js, Coolify)
Database:       PostgreSQL 18 container (Coolify internal, k10946z9tsdcz0abbdw4d74i)
Cache:          Redis 7.2 container (Coolify internal, kxypsxqnx5ki0mnjwr12wbqc)
GitHub (BE):    autom81/autom8rs-k8-platform
GitHub (FE):    autom81/autom8rs-dashboard-
Deployment:     git push → Coolify auto-deploys via webhook
```

**Connect to DB:**
```bash
docker exec -it k10946z9tsdcz0abbdw4d74i psql -U postgres -d postgres
```

**View logs:**
```bash
docker ps | grep uvicorn   # get current container name
docker logs <container-name> --tail 100
```

---

## Phase 1–9: What Was Built (Complete)

### Backend (`autom8rs-k8-platform/app/`)

**Routes:**
- `auth.py` — JWT cookie auth: login, logout, /me, token refresh
- `dashboard.py` — Conversations, messages, leads, products, orders, reply, resolve, pin, pause-bot, tags
- `broadcasts.py` — Templates (CRUD + Meta approval tracking), campaigns (create/send/schedule), recipient-count, per-campaign stats
- `workflows.py` — Workflow CRUD, toggle active/draft, execution history
- `analytics.py` — Overview, conversations, leads, orders, heatmap, channel breakdown
- `settings.py` — Business settings, AI prompt editor, integrations config
- `tags.py` — Tag CRUD, apply/remove tag from lead
- `admin.py` — Multi-tenant client management, system health, prompt editor
- `webhooks.py` — Meta webhook handler: WhatsApp, Instagram DM, Facebook Messenger, **Instagram comments (Phase 11)**, data deletion callback

**Services:**
- `workflow_engine.py` — 10 trigger types, 8 action types, 5 wait step types. APScheduler polls every 5 min.
- `meta.py` — send_whatsapp_message, send_messenger_message, reply_to_instagram_comment, send_instagram_dm_to_commenter, send_reply (unified), download_whatsapp_media
- `llm.py` — OpenRouter, model routing (Gemma default / Claude Sonnet for Ultra complex), tool calling, Gemma thought-stripping
- `message_handler.py` — Tool execution loop (5 iterations max), auto lead capture, Whisper voice transcription, Redis caching, **handle_instagram_comment (Phase 11)**
- `prompt_builder.py` — Dynamic system prompt with live inventory, customer context, ad-aware behavior
- `cache.py` — BusinessCache (1hr TTL), ProductCache (5min), ConversationCache (1min)
- `whisper.py` — OpenAI Whisper voice transcription
- `instagram_sync.py` — #AutoM8 caption parser, post ingestion, product creation

**Tools (Function Calling):**
- `capture_lead()` — auto-called on first message
- `update_lead_status()` — LLM calls as conversation progresses
- `escalate_to_human()` — transfers to human, blocks auto-reply
- `check_stock()`, `calculate_total()`, `place_order()`, `cancel_order()` — full order flow
- `schedule_appointment()` — built, off by default
- `send_product_media()` — serves Instagram media from media_library

**All 10 Workflow Triggers Wired:**
- `new_lead` — fires in capture_lead() on first message
- `hot_lead_detected` — fires in update_lead_status() when classification→hot
- `lead_tag_applied` — fires in tag_service.py after tag applied
- `appointment_booked` — fires in schedule_appointment() after commit
- `order_placed` — fires in place_order() after commit
- `order_cancelled` — fires in cancel_order() after commit
- `order_shipped` — fires in PATCH /api/orders/{id}/status when new_status=shipped
- `order_delivered` — fires in PATCH /api/orders/{id}/status when new_status=delivered
- `escalation_created` — fires in escalate_to_human() after commit
- `conversation_resolved` — fires in resolve_conversation() after commit

**Models:**
Business, User, Conversation, Message, Lead, Order, Product, Appointment, Tag, LeadTag, Workflow, WorkflowExecution, Broadcast, BroadcastTemplate, BroadcastRecipient, MediaLibrary, TemplateSend

### Frontend (`autom8rs-dashboard/app/(dashboard)/dashboard/`)

All pages live and deployed:
- `/` — Overview: KPIs, recent orders, recent escalations
- `/inbox` — Multi-panel inbox with channel icon strip (left), status filter pills (top), conversation thread, customer detail sidebar
- `/contacts` — Lead CRM with classification, status, tags, follow-up scheduling
- `/products` — Product catalog with approval workflow
- `/orders` — Order management with status tracking
- `/appointments` — Appointment scheduling
- `/broadcasts` — 4-step campaign wizard + live stats sheet
- `/broadcasts/templates` — Template library with Meta approval status tracking
- `/workflows` — Workflow builder: trigger → steps → actions → waits
- `/workflows/[id]` — Detail view with execution history
- `/reports` — Analytics: charts, heatmaps, channel breakdown
- `/settings` — Business config, prompt editor, integrations, **Instagram comment toggles (Phase 11)**

**Tier Gates:**
- Broadcasts: Ultra/Custom only
- Workflows: Pro/Ultra/Custom
- Analytics/Reports: Ultra/Custom

---

## Phase 10: Meta App Review (REQUIRED TO GO LIVE)

### Why This Is a Hard Blocker

The Meta app is currently in **Development Mode**. In this mode:
- Only accounts explicitly added as Test Users in the app dashboard can receive messages
- No real Instagram or Messenger users can interact with the bot
- WhatsApp is limited to ~5 approved test recipient numbers

To accept live traffic from any user, the app must pass Meta's App Review and switch to **Live Mode**.

### Permissions Required

| Permission | Enables | Review Required |
|---|---|---|
| `whatsapp_business_messaging` | Send/receive WhatsApp messages | Managed via WhatsApp Business Manager (separate) |
| `pages_messaging` | Send/receive Facebook Messenger messages | Yes — App Review |
| `instagram_manage_messages` | Send/receive Instagram DMs | Yes — App Review |
| `instagram_manage_comments` | Read/reply to Instagram comments, DM commenters | Yes — App Review |
| `pages_manage_metadata` | Subscribe to page webhooks | Yes — App Review |
| `pages_read_engagement` | Read comments/reactions on page posts | Yes — App Review |

### Pre-Submission Checklist

Before submitting for review, ALL of these must be in place:

**1. Privacy Policy URL (REQUIRED)**
- Must be publicly accessible — not a placeholder
- Must describe: what data you collect, how you use it (AI responses, CRM, orders), how users request deletion, third parties (OpenRouter/OpenAI)
- Host at: `https://autom8rs.com/privacy`
- Add at: App Settings → Basic → Privacy Policy URL

**2. Terms of Service URL (Strongly Recommended)**
- Host at: `https://autom8rs.com/terms`
- Add at: App Settings → Basic → Terms of Service URL

**3. Data Deletion Callback URL (REQUIRED)**
- Already implemented: `POST https://api.autom8rs.com/api/meta/data-deletion`
- Register at: App Settings → Basic → Data Deletion Instructions URL

**4. App Icon**
- 1024×1024px PNG
- Upload at: App Settings → Basic → App Icon

**5. Business Verification (may be required)**
- Go to Business Settings → Business Info → Start Verification
- Requires: name, address, phone, website — may need a business document

### How to Record Screencasts Without Prior Approval

Meta requires a screencast for each permission, but you **do not need the permission approved first**. The order is:

1. Add your personal Instagram/Facebook account as a **Test User** in: App Dashboard → Roles → Test Users
2. Test Users in Development Mode get **all permissions automatically** — no review needed
3. Build + test the Instagram comment feature against your own test account
4. Record the screencast showing the full flow: comment → webhook received → bot replies → DM sent
5. Submit the screencast with the permission review request

**What each screencast must show:**
- The triggering action (comment on post, or message sent)
- Your app receiving the event (Coolify logs or dashboard inbox)
- The bot's response appearing (comment reply or DM)
- Under 5 minutes, no music — narration or on-screen labels

**Also provide:** A dedicated test Facebook/Instagram account with credentials for Meta reviewers to test the app themselves.

### Submission Order

1. Submit `pages_messaging` + `pages_manage_metadata` + `pages_read_engagement` together (simpler, faster)
2. After those approve, submit `instagram_manage_messages` + `instagram_manage_comments` together

**Review timeline:** Typically 3–7 business days per batch.

### After Approval

1. Switch app to Live Mode: App Dashboard → top toggle → Development → Live
2. Subscribe to the `comments` webhook field in Meta App Dashboard → Webhooks → Instagram
3. Enable "Auto-reply to comments" and/or "DM commenters" in Settings → Integrations on the dashboard
4. Test with a real comment on TrendyProductsTT's Instagram post

---

## Phase 11: Instagram Comment Automation (Code Complete)

The code is built and deployed. It activates as soon as the `instagram_manage_comments` permission is approved (Phase 10).

### What It Does

- Receives Instagram comment webhook events on the connected page's posts
- Generates a short, natural reply using the same LLM pipeline
- Optionally replies publicly under the comment (configurable)
- Optionally sends a DM to the commenter (configurable — commenting counts as user-initiated so 24hr window doesn't apply)
- Creates a conversation record in the inbox so comments are visible alongside DMs

### Configuration

In dashboard Settings → Integrations → Instagram Comment Automation:
- **Auto-reply to comments** toggle — bot replies publicly under each comment
- **DM commenters** toggle — bot sends a private DM to users who comment

### Files Modified

- `app/services/meta.py` — `reply_to_instagram_comment()`, `send_instagram_dm_to_commenter()`
- `app/services/message_handler.py` — `handle_instagram_comment()`
- `app/routes/webhooks.py` — Instagram `comments` webhook field parsing + data deletion callback
- `app/(dashboard)/dashboard/settings/page.tsx` — Instagram automation toggles

---

## Phase 12–13: Future Work

### Telegram Integration
- `app/routes/telegram.py` — currently empty stub
- Add Telegram Bot API webhook handler
- No Meta involvement — simpler to implement

### Website Chat Widget
- `app/routes/widget.py` — currently empty stub
- WebSocket or polling-based chat
- Embeddable `<script>` tag

### WooCommerce Sync
- `GET {store}/wp-json/wc/v3/products` every 15 minutes (APScheduler)
- Store WooCommerce API key in `businesses.integration_config`
- Update product quantities in DB

### Shopify
- Shopify Webhooks: `products/update`, `inventory_levels/update`
- Lower priority — few Caribbean clients on Shopify

---

## Onboarding a New Client (After Platform Build)

| Step | Action | Time |
|---|---|---|
| 1 | Automation Audit — business info, FAQs, products, escalation rules | 1–2 hrs |
| 2 | Create business record in admin dashboard | 10 min |
| 3 | Write base_prompt using template | 2–4 hrs |
| 4 | Connect Meta accounts (Embedded Signup) | 30–60 min |
| 5 | Load product catalog | 30–60 min |
| 6 | Configure tier features + workflow templates | 1–2 hrs |
| 7 | Run test battery (15 scenarios) | 1–2 hrs |
| 8 | Create dashboard login + client training | 1 hr |

**Total: Starter ~4–6 hrs | Pro ~8–12 hrs | Ultra ~15–20 hrs**

---

## Key Architecture Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Workflow engine | Native (Python + APScheduler) | Replaces n8n — fully integrated with DB, no external dependency |
| LLM routing | Gemma default, Claude Sonnet for Ultra complex | Cost control — Gemma handles tools fine; Claude for nuanced reasoning |
| Auth | JWT in HTTP-only cookie | XSS-resistant; works cross-subdomain with `domain=.autom8rs.com` |
| CORS | Explicit middleware outermost layer | Guarantees headers on all responses including error paths |
| Migrations | Alembic + startup ensure_schema safety net | `ensure_schema` catches edge cases where Alembic records migration before DDL commits |
| Comment automation | DM allowed regardless of 24hr window | Instagram treats commenter DMs as user-initiated (comment = opt-in) |
| Broadcast send | Background task, max 500 recipients | Avoids timeout; enforces rate limit per business per broadcast |

---

## Deployment Workflow

```bash
# Backend
cd autom8rs-k8-platform
git add . && git commit -m "message" && git push
# Coolify auto-deploys → runs Alembic migrations on startup

# Frontend
cd autom8rs-dashboard
git add . && git commit -m "message" && git push
# Coolify auto-deploys → builds Next.js → serves static

# Verify after deploy
curl https://api.autom8rs.com/health
```
