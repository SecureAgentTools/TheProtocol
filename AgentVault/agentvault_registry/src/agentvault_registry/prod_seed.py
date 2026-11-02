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
#   FIRST_ADMIN_PASSWORD — if unset, a random password is generated and written to FIRST_ADMIN_PASSWORD_FILE
#                          (mode 600, before the account exists); the log names the file, never the password.
#                          V0653 (am) item 4: it used to be printed to stdout, which is the container's log.
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


FIRST_PASSWORD_FILE_DEFAULT = "/app/data/first-boot-admin-password"


def write_first_password(path: str, password: str) -> str:
    """The generated first-boot password in a file only its owner reads: created 0600 (never wider for a moment),
    written whole, its directory made if missing. Raises when it cannot be written: the caller then creates no
    account (persist first, like a rotation), so a password nobody holds never exists."""
    from pathlib import Path
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(password + "\n")
    os.chmod(str(target), 0o600)
    return str(target)


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
        password_file = None
        if not env_password:
            # V0653 (am) item 4: persisted BEFORE the account exists; a write that fails leaves no account behind
            password_file = write_first_password(
                os.environ.get("FIRST_ADMIN_PASSWORD_FILE") or FIRST_PASSWORD_FILE_DEFAULT, password)

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
        from agentvault_registry.core.log_identity import email_for_log   # V0653 (am) item 7: not the address
        logger.info(f"prod_seed: ✓ admin account created (id={commander.id}, {email_for_log(commander.email)})")
        if password_file:
            print("\n" + "=" * 60)
            print(f"  FIRST-BOOT ADMIN PASSWORD: in {password_file} (mode 600), inside the registry's container")
            print(f"  Email: {COMMANDER['email']}")
            print("  Read it once, CHANGE IT BEFORE EXPOSING THE REGISTRY, then delete the file")
            print("=" * 60 + "\n")

    await engine.dispose()


def main():
    asyncio.run(seed())


if __name__ == "__main__":
    main()
