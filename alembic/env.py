"""
Alembic Environment Script
===========================

This script configures Alembic to:
1. Use your app's DATABASE_URL (from .env via app.config)
2. Read your SQLAlchemy models from app.models
3. Auto-detect schema changes for migration generation

HOW IT WORKS:
- When you run 'alembic revision --autogenerate',
  this file compares your models to the current database state
- When you run 'alembic upgrade head', 
  this applies all pending migrations
"""
from logging.config import fileConfig
import sys
import os

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# ============================================================
# Add project root to Python path so we can import app.*
# ============================================================
# Alembic runs from project root, so we add current dir
sys.path.insert(0, os.path.abspath(os.getcwd()))

# ============================================================
# Import your app's configuration and models
# ============================================================
from app.config import settings
from app.database import Base

# Import ALL models so Alembic sees them
# IMPORTANT: Must import every model file here
import app.models  # This triggers all model imports via app/models/__init__.py

# ============================================================
# Alembic config object
# ============================================================
config = context.config

# Set the database URL from your app settings (not from alembic.ini)
# This ensures we always use the same DB as the rest of your app
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ============================================================
# Target metadata - this is what Alembic compares against
# ============================================================
# Base.metadata contains ALL tables defined in your models
target_metadata = Base.metadata


# ============================================================
# OFFLINE MIGRATIONS (generates SQL without connecting to DB)
# ============================================================

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well. By skipping the Engine
    creation we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Include object changes (not just schema) for complete migrations
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ============================================================
# ONLINE MIGRATIONS (connects to DB and runs migrations)
# ============================================================

def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Important settings for catching ALL schema changes
            compare_type=True,              # Detect column type changes
            compare_server_default=True,    # Detect default value changes
            include_schemas=False,          # We only use public schema
        )

        with context.begin_transaction():
            context.run_migrations()


# ============================================================
# RUN THE APPROPRIATE MIGRATION MODE
# ============================================================

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()