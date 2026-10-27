"""
Production Seed — Commander Account Bootstrap
==============================================
Ensures the Commander admin account exists on every registry DB.
Safe to run on every container restart — fully idempotent.

Checks by EMAIL before inserting. Will NEVER overwrite or modify an
existing account. If commander@theprotocol.cloud already exists, exits silently.

Runs automatically as part of the registry startup command:
  alembic upgrade heads && python -m agentvault_registry.prod_seed && uvicorn ...

Usage (manual):
  docker exec agentvault-registry-a python -m agentvault_registry.prod_seed
  docker exec agentvault-registry-b python -m agentvault_registry.prod_seed
"""

import asyncio
import logging
import os
import secrets

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("prod_seed")

# First-admin identity is ENV-DRIVEN — no hardcoded credentials in source.
#   FIRST_ADMIN_EMAIL    — defaults to the canonical mainframe admin (Frame A unchanged).
#   FIRST_ADMIN_NAME     — display name.
#   FIRST_ADMIN_PASSWORD — if unset, a random password is generated and printed ONCE to the logs.
# §EXCISION — FIRST_ADMIN_EMAIL no longer defaults to the Commander's address.
# A fresh operator deploy that forgot the env var would otherwise seed its first
# admin under a personal identity on someone else's machine. The frame-c and
# Hetzner deployments already set it explicitly, so nothing live changes.
COMMANDER = {
    "name": os.environ.get("FIRST_ADMIN_NAME", "Registry Administrator"),
    "email": os.environ.get("FIRST_ADMIN_EMAIL", "admin@localhost"),
    "is_admin": True,
    "is_verified": True,
}


async def seed():
    """Inject Commander account if not present. Idempotent — never overwrites."""

    from agentvault_registry.config import settings
    from agentvault_registry.models import Developer
    from agentvault_registry.security import hash_password

    database_url = settings.DATABASE_URL
    from agentvault_registry.core.dsn import redact_dsn
    # The same line as operator_seed's, on EVERY frame's registry rather than only an operator's.
    logger.info(f"prod_seed: checking {redact_dsn(database_url)}")

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # ── Idempotent check — email is the stable key ──
        existing = await db.execute(
            select(Developer).where(Developer.email == COMMANDER["email"])
        )
        if existing.scalar_one_or_none():
            logger.info(f"prod_seed: Commander account already exists — skipping.")
            await engine.dispose()
            return

        # ── Resolve the first-admin password (env or random — never hardcoded) ──
        env_password = os.environ.get("FIRST_ADMIN_PASSWORD")
        password = env_password or secrets.token_urlsafe(20)

        # ── Insert ──
        commander = Developer(
            name=COMMANDER["name"],
            email=COMMANDER["email"],
            hashed_password=hash_password(password),
            is_admin=COMMANDER["is_admin"],
            is_verified=COMMANDER["is_verified"],
            # All other fields: NULL / server defaults — all nullable, no issues
        )
        db.add(commander)
        await db.commit()
        await db.refresh(commander)
        logger.info(f"prod_seed: ✓ admin account created (id={commander.id}, email={commander.email})")
        if not env_password:
            print("\n" + "=" * 60)
            print(f"  FIRST-BOOT ADMIN PASSWORD: {password}")
            print(f"  Email: {COMMANDER['email']}")
            print("  CHANGE THIS PASSWORD BEFORE EXPOSING THE REGISTRY")
            print("=" * 60 + "\n")

    await engine.dispose()


def main():
    asyncio.run(seed())


if __name__ == "__main__":
    main()
