#!/usr/bin/env python3
"""
GENESIS GRANT TEST - Seed a fresh beta tester account.
Run inside container: docker exec agentvault_registry_a python scripts/seed_beta_tester.py
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
import bcrypt
import asyncpg
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Beta Tester account details
TESTER_EMAIL = "genesis_tester@theprotocol.cloud"
TESTER_PASSWORD = "GenesisTest!2026"
TESTER_NAME = "Genesis Tester"


async def hash_password(password: str) -> str:
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


async def main():
    print("=" * 60)
    print("GENESIS GRANT TEST - SEEDING BETA TESTER ACCOUNT")
    print("=" * 60)
    print(f"Email: {TESTER_EMAIL}")
    print(f"Name:  {TESTER_NAME}")
    print("=" * 60)

    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        print("[X] DATABASE_URL not found in environment")
        sys.exit(1)

    if "+asyncpg" in database_url:
        database_url = database_url.replace("postgresql+asyncpg", "postgresql")

    try:
        conn = await asyncpg.connect(database_url)
        print("[+] Connected to database")

        # Check if account already exists
        existing = await conn.fetchrow(
            "SELECT id, email FROM developers WHERE email = $1",
            TESTER_EMAIL
        )

        if existing:
            print(f"[!] Account already exists with ID: {existing['id']}")
            # Make sure it's verified (handle schemas with/without is_active)
            try:
                await conn.execute("""
                    UPDATE developers SET is_verified = true, is_active = true, updated_at = $1
                    WHERE email = $2
                """, datetime.now(timezone.utc), TESTER_EMAIL)
            except asyncpg.UndefinedColumnError:
                await conn.execute("""
                    UPDATE developers SET is_verified = true, updated_at = $1
                    WHERE email = $2
                """, datetime.now(timezone.utc), TESTER_EMAIL)
            
            # CRITICAL: Delete any existing agents for this developer so they get genesis grant
            agent_count = await conn.fetchval(
                "SELECT count(*) FROM agents WHERE creator_developer_id = $1",
                existing['id']
            )
            if agent_count > 0:
                print(f"[!] Developer has {agent_count} existing agent(s) - deleting for clean test...")
                # Delete agent cards first (foreign key)
                await conn.execute("""
                    DELETE FROM agent_cards WHERE agent_id IN (
                        SELECT id FROM agents WHERE creator_developer_id = $1
                    )
                """, existing['id'])
                # Delete bootstrap tokens
                await conn.execute("""
                    DELETE FROM bootstrap_tokens WHERE creator_developer_id = $1
                """, existing['id'])
                # Delete agents
                await conn.execute(
                    "DELETE FROM agents WHERE creator_developer_id = $1",
                    existing['id']
                )
                print(f"[+] Cleaned {agent_count} agent(s) - developer now has 0 agents")
            
            print(f"[+] Account ready - ID: {existing['id']}")
        else:
            hashed_pw = await hash_password(TESTER_PASSWORD)
            # Check if is_active column exists
            cols = await conn.fetch("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'developers' AND column_name = 'is_active'
            """)
            has_is_active = len(cols) > 0

            if has_is_active:
                result = await conn.fetchrow("""
                    INSERT INTO developers (name, email, hashed_password, is_verified, is_active, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """,
                    TESTER_NAME, TESTER_EMAIL, hashed_pw,
                    True, True,
                    datetime.now(timezone.utc), datetime.now(timezone.utc)
                )
            else:
                result = await conn.fetchrow("""
                    INSERT INTO developers (name, email, hashed_password, is_verified, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                """,
                    TESTER_NAME, TESTER_EMAIL, hashed_pw,
                    True,
                    datetime.now(timezone.utc), datetime.now(timezone.utc)
                )
            print(f"[+] Account created with ID: {result['id']}")

        # Verify final state
        dev = await conn.fetchrow(
            "SELECT id, email, is_verified FROM developers WHERE email = $1",
            TESTER_EMAIL
        )
        agent_count = await conn.fetchval(
            "SELECT count(*) FROM agents WHERE creator_developer_id = $1",
            dev['id']
        )
        print(f"\n[FINAL STATE]")
        print(f"  Developer ID: {dev['id']}")
        print(f"  Email: {dev['email']}")
        print(f"  Verified: {dev['is_verified']}")
        print(f"  Agent Count: {agent_count}")
        print(f"\n[+] Ready for genesis grant test!")
        print(f"  Email: {TESTER_EMAIL}")
        print(f"  Password: {TESTER_PASSWORD}")

        await conn.close()

    except Exception as e:
        print(f"[X] ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
