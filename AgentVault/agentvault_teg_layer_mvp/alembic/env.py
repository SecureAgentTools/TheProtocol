"""Alembic environment configuration for TEG Layer MVP."""
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import sys
from pathlib import Path

# Add src to path so we can import our models
sys.path.append(str(Path(__file__).parent.parent))

# Import the Base and all models
from src.teg_core_service.database.models import Base
from src.teg_core_service.core.config import get_settings
from src.teg_core_service.core.db_url import sync_engine_url

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Get database URL from application settings
settings = get_settings()
# §DEPS sqla-driver-pin: the sync driver is NAMED (psycopg2); a plain postgresql:// is psycopg 3 on SQLAlchemy 2.1
config.set_main_option("sqlalchemy.url", sync_engine_url(settings.database_url))

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
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
    # Handle both PostgreSQL and SQLite
    configuration = config.get_section(config.config_ini_section)
    configuration['sqlalchemy.url'] = sync_engine_url(settings.database_url)
    
    # Special handling for SQLite
    if settings.database_url.startswith('sqlite'):
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
            connect_args={"check_same_thread": False}
        )
    else:
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            compare_type=True,  # Detect column type changes
            compare_server_default=True,  # Detect server default changes
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
