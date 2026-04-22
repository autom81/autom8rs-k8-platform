import logging
import subprocess
import os

from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response as FastAPIResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import engine, get_db
import app.models  # noqa: F401 — forces all models to register with SQLAlchemy

from app.routes.webhooks import router as webhooks_router
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.dashboard import router as dashboard_router
from app.routes.analytics import router as analytics_router
from app.routes.settings import router as settings_router
from app.routes.tags import router as tags_router
from app.routes.workflows import router as workflows_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# SCHEDULER
# ============================================================

def _start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from app.services.workflow_engine import resume_waiting_executions

        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            resume_waiting_executions,
            trigger="interval",
            minutes=5,
            id="resume_workflows",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("✅ APScheduler started — workflows will resume every 5 minutes")
        return scheduler
    except Exception as e:
        logger.error(f"Failed to start APScheduler: {e}", exc_info=True)
        return None


# ============================================================
# MIGRATIONS
# ============================================================

def run_migrations():
    """Run pending Alembic migrations on startup."""
    try:
        logger.info("Running database migrations...")
        alembic_dir = os.path.join(os.getcwd(), "alembic")
        if not os.path.exists(alembic_dir):
            logger.warning("Alembic directory not found — skipping migrations.")
            return

        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            logger.info("✅ Database migrations applied successfully")
            if result.stdout:
                logger.info(f"Alembic output: {result.stdout.strip()}")
        else:
            logger.error(f"❌ Alembic migration failed: {result.stderr}")

    except FileNotFoundError:
        logger.error("Alembic not installed.")
    except Exception as e:
        logger.error(f"Error running migrations: {e}", exc_info=True)


# Schema guard: columns that MUST exist, verified on every startup.
# This is the safety net for the known failure mode where Alembic records a
# migration as applied before the DDL actually commits — leaving the column
# missing and crashing every query on that table.
#
# Rule: whenever you add a column to a model, add a row here too.
_REQUIRED_COLUMNS: list[tuple[str, str, str]] = [
    # (table, column_name, postgres_column_definition)
    ("conversations", "pinned",      "BOOLEAN NOT NULL DEFAULT false"),
    ("conversations", "bot_paused",  "BOOLEAN NOT NULL DEFAULT false"),
    ("orders",        "confirmed_at", "TIMESTAMPTZ NULL"),
    ("orders",        "delivered_at", "TIMESTAMPTZ NULL"),
    ("leads",         "follow_up_at", "TIMESTAMPTZ NULL"),
]


def ensure_schema():
    """Add any missing columns that Alembic may have failed to create."""
    try:
        from sqlalchemy import inspect as sa_inspect
        with engine.connect() as conn:
            inspector = sa_inspect(conn)
            for table, col_name, col_def in _REQUIRED_COLUMNS:
                existing = {c["name"] for c in inspector.get_columns(table)}
                if col_name not in existing:
                    logger.warning(f"⚠️  Column {table}.{col_name} missing — adding now")
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}"))
                    conn.commit()
                    logger.info(f"✅  Added {table}.{col_name}")
    except Exception as e:
        logger.error(f"ensure_schema failed: {e}", exc_info=True)


# Run migrations then verify schema before the app accepts any traffic.
run_migrations()
ensure_schema()
_scheduler = _start_scheduler()


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(title="K8 Agent Platform", version="0.2.0")

# ── CORS ──────────────────────────────────────────────────────────
# ExplicitCORSMiddleware is added LAST so it becomes the outermost layer
# and guarantees CORS headers on every response including preflight.

_ALLOWED_ORIGIN = "https://dashboard.autom8rs.com"
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": _ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept, Cookie, X-Requested-With",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Max-Age": "3600",
    "Access-Control-Expose-Headers": "Set-Cookie",
}


class ExplicitCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin", "")

        if request.method == "OPTIONS" and origin == _ALLOWED_ORIGIN:
            return FastAPIResponse(status_code=200, headers=_CORS_HEADERS)

        response = await call_next(request)

        if origin == _ALLOWED_ORIGIN:
            for key, value in _CORS_HEADERS.items():
                response.headers[key] = value

        return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[_ALLOWED_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "Cookie", "X-Requested-With"],
    expose_headers=["Set-Cookie"],
    max_age=3600,
)
app.add_middleware(ExplicitCORSMiddleware)

# Catch-all OPTIONS handler so no preflight ever hits a 405 at the router level
@app.options("/{rest_of_path:path}")
async def preflight_handler(rest_of_path: str, request: Request):
    return FastAPIResponse(status_code=200)

app.include_router(webhooks_router)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(analytics_router)
app.include_router(settings_router)
app.include_router(tags_router)
app.include_router(workflows_router)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
async def root():
    return {
        "status": "online",
        "platform": "K8 Agent Platform",
        "version": "0.2.0",
        "message": "Hello from api.autom8rs.com",
    }


@app.get("/health")
async def health_check(db: Session = Depends(get_db)):
    """Comprehensive health check — database + cache + migration state."""
    from app.services.cache import cache_health_check

    try:
        db.execute(text("SELECT 1"))
        result = db.execute(
            text("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        )
        db_status = {"status": "healthy", "tables": result.scalar()}
    except Exception as e:
        db_status = {"status": "unhealthy", "error": str(e)}

    cache_status = cache_health_check()

    try:
        result = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))
        current_version = result.scalar()
        migration_status = {
            "current_revision": current_version,
            "status": "up_to_date" if current_version else "no_migrations_applied",
        }
    except Exception:
        migration_status = {"status": "alembic_not_initialized"}

    return {
        "api": "online",
        "database": db_status,
        "cache": cache_status,
        "migrations": migration_status,
    }
