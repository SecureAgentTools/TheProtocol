import os
import sys
from logging.config import fileConfig

# --- MODIFICATION: Use the synchronous create_engine for migrations ---
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add project source directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..'))
src_path = os.path.join(project_root, 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Import application's configuration and models
# This is safe because we are only importing for metadata
from agentvault_registry.config import settings
from agentvault_registry.core.dsn import sync_engine_url
from agentvault_registry.database import Base

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- MODIFICATION: This is now the single source of truth for the target schema ---
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.
    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.
    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = sync_engine_url(settings.DATABASE_URL)  # the sync driver, named (psycopg2 on SQLAlchemy 2.0 and 2.1)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.
    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    # --- MODIFICATION: Use a synchronous engine for the migration process ---
    # Get the database URL from our settings
    db_url = settings.DATABASE_URL
    
    # IMPORTANT: Convert the async URL to a sync URL for Alembic's sync context, and NAME the sync driver:
    # a plain postgresql:// is psycopg2 on SQLAlchemy 2.0 but psycopg 3 on 2.1 (§DEPS sqla-driver-pin)
    sync_db_url = sync_engine_url(db_url)

    # Create a configuration dictionary for the synchronous engine
    connectable_config = config.get_section(config.config_ini_section)
    if connectable_config is None:
        connectable_config = {}
    connectable_config["sqlalchemy.url"] = sync_db_url
    
    # Create the synchronous engine
    connectable = engine_from_config(
        connectable_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()