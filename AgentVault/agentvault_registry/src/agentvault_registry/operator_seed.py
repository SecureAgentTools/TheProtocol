"""
Operator Bootstrap Seed — Distribution Package First-Boot Admin
===============================================================
Creates a local admin account with a random password on first boot.
Safe to run on every container restart — fully idempotent.

Checks by EMAIL before inserting. Will NEVER overwrite or modify an
existing account. If the operator admin already exists, exits silently.
The must_change_password flag is ONLY set on initial creation.

Runs automatically as part of the registry startup command:
  alembic upgrade heads && python -m agentvault_registry.operator_seed && uvicorn ...

The frame kit's standup (agentvault2-56, 2026-10-22; his word: "make sure terms are accepted also on framekit standup.
because there an account is issued"): every other rail that issues an account records the documents its person
accepted (registration, an operator application, a frame request, a self-provision, a checkout); a frame stood up with
the kit's frame-up.py was issued its first admin here with none. frame-up.py now asks the person running it to accept the
Federation Operator Terms first (the prompt, or --accept-terms) and passes the acceptance in the env; this seed records it
with the account, in the same transaction, at the version this registry serves:
  FIRST_ADMIN_ACCEPTED      the documents accepted, comma-separated keys of core.legal_versions.ACCEPTABLE_DOCUMENTS
  FIRST_ADMIN_ACCEPTED_AT   when the person accepted (ISO 8601), as frame-up.py stamped it; unreadable or unset: now
  FIRST_ADMIN_ACCEPTED_BY   how (the tool and the kit version), kept as the record's user agent
Unset (a network-run frame, a cloud operator, an older kit) nothing is recorded, as before.

Usage (manual):
  docker exec <registry-container> python -m agentvault_registry.operator_seed
"""

import asyncio
import datetime
import logging
import os
import re
import secrets
from typing import List, Mapping, Optional, Tuple

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("operator_seed")


VIA_FRAME_STANDUP = "frame_standup"


def _accepted_at(value: Optional[str]) -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc)
    if not (value or "").strip():
        return now
    try:
        at = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        logger.warning("operator_seed: FIRST_ADMIN_ACCEPTED_AT is not an ISO 8601 time; the acceptance is stamped now")
        return now
    return at if at.tzinfo else at.replace(tzinfo=datetime.timezone.utc)


def standup_acceptances(env: Mapping[str, str] = os.environ) -> List[Tuple[str, str, datetime.datetime, Optional[str]]]:
    """(document, the version this registry serves, accepted at, by) for each document FIRST_ADMIN_ACCEPTED names;
    [] when it names none. A name this registry serves no version of is said and left out, never recorded."""
    from agentvault_registry.core.legal_versions import current_version
    names = [n.strip().lower() for n in (env.get("FIRST_ADMIN_ACCEPTED") or "").split(",") if n.strip()]
    if not names:
        return []
    at = _accepted_at(env.get("FIRST_ADMIN_ACCEPTED_AT"))
    by = (env.get("FIRST_ADMIN_ACCEPTED_BY") or "").strip()[:255] or None
    out = []
    for name in dict.fromkeys(names):
        version = current_version(name)
        if not version:
            logger.warning(f"operator_seed: FIRST_ADMIN_ACCEPTED names {name!r}, a document this registry does not "
                           f"serve: not recorded")
            continue
        out.append((name, version, at, by))
    return out


async def create_admin(db, admin, accepted) -> None:
    """Add the first admin and its standup acceptances in ONE transaction, the registration rail's shape: the
    account never exists without the record of what its person accepted."""
    from agentvault_registry.services.legal_acceptance import SUBJECT_DEVELOPER, record_acceptance
    db.add(admin)
    await db.flush()
    for document, version, at, by in accepted:
        await record_acceptance(db, document=document, subject_kind=SUBJECT_DEVELOPER, subject_id=str(admin.id),
                                via=VIA_FRAME_STANDUP, developer_id=admin.id, version=version, accepted_at=at,
                                user_agent=by)
        if document == "terms":
            admin.tos_accepted_version = version
            admin.tos_accepted_at = at
    await db.commit()
    await db.refresh(admin)


def slugify(name: str) -> str:
    """Convert a registry name to a safe email-local slug: lowercase, spaces to hyphens."""
    slug = name.strip().lower()
    slug = re.sub(r'\s+', '-', slug)
    slug = re.sub(r'[^a-z0-9\-]', '', slug)
    return slug or "my-registry"


async def seed():
    """Inject operator admin account if not present. Idempotent — never overwrites."""

    from agentvault_registry.config import settings
    from agentvault_registry.models import Developer
    from agentvault_registry.security import hash_password

    registry_name = os.environ.get("REGISTRY_NAME", "my-registry")
    slug = slugify(registry_name)
    # Optional chosen-admin overrides: FIRST_ADMIN_EMAIL / FIRST_ADMIN_PASSWORD / FIRST_ADMIN_NAME.
    # Unset → derived email + random password (the default self-serve behavior).
    admin_email = os.environ.get("FIRST_ADMIN_EMAIL") or f"admin@{slug}.dev"
    env_password = os.environ.get("FIRST_ADMIN_PASSWORD")
    password = env_password or secrets.token_urlsafe(20)
    accepted = standup_acceptances()

    database_url = settings.DATABASE_URL
    from agentvault_registry.core.dsn import redact_dsn
    # ⚠ `[:50]` REACHED INTO THE PASSWORD. This printed a live operator credential's prefix into the operator's
    # own log, where agentvault2-6a found it on 2026-09-16; that stack was torn down so the password died with
    # its volume. A truncation is the same secret with fewer characters, never a redaction.
    logger.info(f"operator_seed: checking {redact_dsn(database_url)}")

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # ── Idempotent check — email is the stable key ──
        existing = await db.execute(
            select(Developer).where(Developer.email == admin_email)
        )
        if existing.scalar_one_or_none():
            logger.info(f"operator_seed: Operator admin ({admin_email}) already exists — skipping.")
            await engine.dispose()
            return

        # ── Insert ──
        # §pass65 (2026-05-22) — set ALL admin sub-flags. is_admin=true alone
        # isn't enough since §pass47 introduced flag-gated endpoints; the
        # `require_admin_flag("admin_platform"|"admin_federation"|...)` check
        # reads the per-area sub-flag, not is_admin. Without these, the seeded
        # operator admin can NOT use Federation/Live/Treasury tabs of their
        # own portal nor reach /admin/* endpoints despite being is_admin=true.
        # All flags = true is right here because the operator OWNS this entire
        # registry — there's no separation-of-duties concern within a single
        # cloud-op (unlike the mainframe where Commander partitions admins).
        admin = Developer(
            name=os.environ.get("FIRST_ADMIN_NAME") or f"{registry_name}-admin",
            email=admin_email,
            hashed_password=hash_password(password),
            is_admin=True,
            is_verified=True,
            admin_treasury=True,
            admin_support=True,
            admin_enforcement=True,
            admin_federation=True,
            admin_platform=True,
        )
        await create_admin(db, admin, accepted)
        for document, version, at, by in accepted:
            logger.info(f"operator_seed: the admin's acceptance is recorded: {document} {version} at "
                        f"{at.isoformat()} ({VIA_FRAME_STANDUP}{', ' + by if by else ''})")

        # ── Print first-boot banner (only echo the password when it was randomly generated) ──
        if env_password:
            print(f"\noperator_seed: admin {admin_email} created with the password from FIRST_ADMIN_PASSWORD.\n")
        else:
            banner = "\n".join([
                "",
                "=" * 60,
                f"  FIRST-BOOT ADMIN PASSWORD: {password}",
                "",
                f"  Email:    {admin_email}",
                f"  Registry: {registry_name}",
                "",
                "  CHANGE THIS PASSWORD BEFORE CONNECTING TO THE INTERNET",
                "=" * 60,
                "",
            ])
            # Use print() so the banner is visible even if logging is filtered
            print(banner)
        logger.info(f"operator_seed: Operator admin created (id={admin.id}, email={admin_email})")

    await engine.dispose()


async def seed_emission_policies():
    """
    Seed event emission policies for standalone/operator deployments.

    On production, these are created by Alembic migrations. On operator/standalone
    deployments that use 'alembic stamp heads' (skip migrations), the table is empty.
    This seeds the essential policies so TEG event emission works correctly.

    Registry ALWAYS emits events. TEG NEVER emits directly. This is consistent
    across standalone and federated modes — all token operations route through
    the Registry which handles EventStore emission.
    """
    from agentvault_registry.config import settings

    database_url = settings.DATABASE_URL
    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Check if policies already exist
        result = await db.execute(select(1).select_from(
            __import__('sqlalchemy').text("event_emission_policies")
        ).limit(1))
        if result.scalar_one_or_none() is not None:
            logger.info("operator_seed: Emission policies already seeded — skipping.")
            await engine.dispose()
            return

        # Seed essential policies
        # Registry ALWAYS emits. TEG NEVER emits. This is consistent across
        # standalone and federated — all token operations go through the Registry.
        policies = [
            ("TokensIssued", False, True, False),
            ("TokensTransferred", False, True, False),
            ("TokensStaked", False, True, False),
            ("TokensUnstaked", False, True, False),
            ("TransactionFeeCollected", False, True, False),
            ("AgentCreated", False, True, False),
            ("AgentOnboarded", False, True, False),
            ("ReputationChanged", False, True, False),
            ("CrossRegistryTransferCompleted", False, True, True),
            ("RewardsDistributed", False, True, True),
            ("A2APaymentAuthorized", False, True, True),
            ("A2APaymentSettled", False, True, True),
        ]

        for event_type, emit_teg, emit_reg, skip_proj in policies:
            await db.execute(text(
                "INSERT INTO event_emission_policies "
                "(event_type, emit_from_teg, emit_from_registry, skip_in_projection) "
                "VALUES (:et, :teg, :reg, :skip) "
                "ON CONFLICT (event_type) DO NOTHING"
            ), {"et": event_type, "teg": emit_teg, "reg": emit_reg, "skip": skip_proj})

        await db.commit()
        logger.info(f"operator_seed: Seeded {len(policies)} emission policies")

    await engine.dispose()


def main():
    asyncio.run(seed())
    try:
        asyncio.run(seed_emission_policies())
    except Exception as e:
        logger.warning(f"operator_seed: Emission policy seeding failed (non-fatal): {e}")


if __name__ == "__main__":
    main()
