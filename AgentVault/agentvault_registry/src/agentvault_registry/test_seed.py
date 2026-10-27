"""
OWL29/P8.26g: Test Sandbox Seed Data (Developer Accounts Only)
===============================================================
Creates deterministic DEVELOPER accounts for the API Tester sandbox.
Runs once at container startup after Alembic migration.

IMPORTANT: This seed ONLY creates admin + developer accounts via SQL INSERT.
Agent onboarding MUST happen via the API after the server is running:
  → Run: python test_proper_onboard.py (from project root)
  → Uses bootstrap token → /onboard/create_agent → fund → stake
  → This ensures agents exist in BOTH registry DB and TEG layer

P8.26g Discovery: Previous seed did SQL INSERT for agents directly into the
registry agents table. This created "ghost" agents that existed in the registry
but NOT in the TEG layer — causing 404s on all TEG endpoints (reputation,
balance, transfer, disputes). The fix is proper API onboarding.

Usage: PYTHONPATH=/app/src python -m agentvault_registry.test_seed

Sandbox account passwords come from the ENVIRONMENT, never from this file
(2026-07-29). They used to be hardcoded literals, which meant a public checkout
published working ADMIN credentials for every deployment that runs this seed —
and the frame-test template had already carried two of them onto an
internet-facing frame. Set these in the deployment env (they live in
.env.production, which is not committed):

  SANDBOX_ADMIN_PASSWORD       -> admin@test.sandbox               (is_admin)
  SANDBOX_DEVELOPER_PASSWORD   -> developer@test.sandbox
  SANDBOX_TUTORIAL_PASSWORD    -> tutorial-admin@theprotocol.cloud (is_admin)
  SANDBOX_NON_ADMIN_PASSWORD   -> non_admin_dev@test.sandbox

Any unset variable gets a RANDOM password that is never logged (set the
variable to use that account). A random value is deliberately preferred over
a convenient default: a default in source is the bug this replaced.

Agent credentials are generated dynamically by test_proper_onboard.py
and saved to sessionlogs2026/ONBOARDED_AGENTS.json
"""

import asyncio
import logging
import secrets
import sys
import os

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("test_seed")

# ===== SANDBOX TEST CREDENTIALS (passwords from the ENVIRONMENT) =====
# 2026-07-29: these were hardcoded literals. That published working ADMIN
# credentials in every checkout, and the frame-test template had already seeded
# two of them onto an internet-facing frame. See the module docstring.

def _seed_password(env_name: str, account: str) -> str:
    """Password for a seeded sandbox account: the env's, or a random one nobody is told.

    Deliberately no in-source default: a default IS the vulnerability this
    replaced. The value is never logged (§TESTBED 2026-09-19: the random one
    used to be written into the container log, and the first seed logged the
    env-supplied ones too; a log is read by more people and kept longer than a
    secrets file). Set the variable to log in as the account.
    """
    v = os.environ.get(env_name)
    if v:
        return v
    generated = secrets.token_urlsafe(18) + "aA1!"
    logger.warning(
        f"[test_seed] {env_name} is not set: {account} gets a random password that is not "
        f"logged; set {env_name} to log in as it"
    )
    return generated


TEST_ADMIN = {
    "name": "Test Admin",
    "email": "admin@test.sandbox",
    "password": _seed_password("SANDBOX_ADMIN_PASSWORD", "admin@test.sandbox"),
    "is_admin": True,
    "is_verified": True,
}

TEST_DEVELOPER = {
    "name": "Test Developer",
    "email": "developer@test.sandbox",
    "password": _seed_password("SANDBOX_DEVELOPER_PASSWORD", "developer@test.sandbox"),
    "is_admin": False,
    "is_verified": True,
}

TUTORIAL_ADMIN = {
    "name": "Tutorial Developer",
    "email": "tutorial-admin@theprotocol.cloud",
    "password": _seed_password("SANDBOX_TUTORIAL_PASSWORD", "tutorial-admin@theprotocol.cloud"),
    "is_admin": True,
    "is_verified": True,
}

# §pass73 task B (2026-05-26): dedicated non-admin fixture for MCP-tester F.1.
# Fresh email to avoid collision with `developer@test.sandbox` which has been
# soft-deleted (anonymized hashed_password) in some sandbox states by prior
# anonymize-test flows. Self-heals on each boot: if the row exists but has the
# `!deleted!` marker, the password gets reset.
NON_ADMIN_DEV = {
    "name": "Non-Admin MCP Tester Fixture",
    "email": "non_admin_dev@test.sandbox",
    "password": _seed_password("SANDBOX_NON_ADMIN_PASSWORD", "non_admin_dev@test.sandbox"),
    "is_admin": False,
    "is_verified": True,
}


async def seed():
    """Seed the test database with admin + developer accounts. Idempotent."""
    
    from agentvault_registry.config import settings
    from agentvault_registry.models import Developer
    from agentvault_registry.security import hash_password
    
    database_url = settings.DATABASE_URL
    logger.info(f"Seeding database: {database_url[:50]}...")
    
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # ─── §pass73 task B: always ensure NON_ADMIN_DEV exists with a usable
        #     password, even when the rest of the seed is idempotently skipped.
        #     Self-heals from the `!deleted!` anonymized state.
        non_admin_existing = (await db.execute(
            select(Developer).where(Developer.email == NON_ADMIN_DEV["email"])
        )).scalar_one_or_none()
        if non_admin_existing is None:
            db.add(Developer(
                name=NON_ADMIN_DEV["name"],
                email=NON_ADMIN_DEV["email"],
                hashed_password=hash_password(NON_ADMIN_DEV["password"]),
                is_admin=NON_ADMIN_DEV["is_admin"],
                is_verified=NON_ADMIN_DEV["is_verified"],
            ))
            await db.commit()
            logger.info(f"  ✓ Created non-admin fixture: {NON_ADMIN_DEV['email']}")
        else:
            # Always rewrite the password in case the row got anonymized.
            non_admin_existing.hashed_password = hash_password(NON_ADMIN_DEV["password"])
            non_admin_existing.is_admin = NON_ADMIN_DEV["is_admin"]
            non_admin_existing.is_verified = NON_ADMIN_DEV["is_verified"]
            await db.commit()
            logger.info(f"  ↻ Reset non-admin fixture password: {NON_ADMIN_DEV['email']}")

        # ─── Idempotent check ───
        existing = await db.execute(
            select(Developer).where(Developer.email == TEST_ADMIN["email"])
        )
        if existing.scalar_one_or_none():
            logger.info("✓ Test DB already seeded (admin + developer exist) — skipping.")
            await engine.dispose()
            return
        
        # ─── Create Admin Account ───
        admin = Developer(
            name=TEST_ADMIN["name"],
            email=TEST_ADMIN["email"],
            hashed_password=hash_password(TEST_ADMIN["password"]),
            is_admin=TEST_ADMIN["is_admin"],
            is_verified=TEST_ADMIN["is_verified"],
        )
        db.add(admin)
        await db.flush()
        logger.info(f"  ✓ Created admin: {admin.email} (id={admin.id})")
        
        # ─── Create Developer Account ───
        dev = Developer(
            name=TEST_DEVELOPER["name"],
            email=TEST_DEVELOPER["email"],
            hashed_password=hash_password(TEST_DEVELOPER["password"]),
            is_admin=TEST_DEVELOPER["is_admin"],
            is_verified=TEST_DEVELOPER["is_verified"],
        )
        db.add(dev)
        await db.flush()
        logger.info(f"  ✓ Created developer: {dev.email} (id={dev.id})")
        
        # ─── Create Tutorial Admin Account ───
        tutorial = Developer(
            name=TUTORIAL_ADMIN["name"],
            email=TUTORIAL_ADMIN["email"],
            hashed_password=hash_password(TUTORIAL_ADMIN["password"]),
            is_admin=TUTORIAL_ADMIN["is_admin"],
            is_verified=TUTORIAL_ADMIN["is_verified"],
        )
        db.add(tutorial)
        await db.flush()
        logger.info(f"  ✓ Created tutorial admin: {tutorial.email} (id={tutorial.id})")
        
        # ─── Commit developer accounts ───
        await db.commit()
        logger.info("✓ Test DB seeded with developer accounts!")
        # the accounts, never their passwords (§TESTBED 2026-09-19: these three lines printed them)
        logger.info(f"  Admin:     {TEST_ADMIN['email']}")
        logger.info(f"  Developer: {TEST_DEVELOPER['email']}")
        logger.info(f"  Tutorial:  {TUTORIAL_ADMIN['email']}")
        logger.info("")
        logger.info("  Sandbox Sentinel will be onboarded via API after server starts.")
    
    await engine.dispose()


if __name__ == "__main__":
    logger.info("═══ OWL29/P8.26g Test Sandbox Seed (Dev Accounts Only) ═══")
    asyncio.run(seed())
    logger.info("═══ Seed complete ═══")
