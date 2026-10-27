"""
Database verification helper for API tests

Provides direct database access to verify test accounts after registration.
"""

import subprocess
import os
import logging
import json
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DatabaseVerifier:
    """Helper class to verify test accounts directly in the database"""
    
    def __init__(self, container_name: str = None):
        # ⚠ THIS USED TO GUESS, AND ONE OF ITS GUESSES WAS PRODUCTION.
        # The old body picked `agentvault_registry_test` when the target URL
        # said "registry-test" and otherwise fell through to
        # `agentvault_registry_a` — the Frame-A PRODUCTION registry — then ran
        # `docker exec` against it. It was inert only by accident: the shell-out
        # needs a `docker` binary the registry image does not ship, so every
        # call failed into a logger.error and returned None. Route it through
        # docker-py (as the rest of api_tests does) and that latent path becomes
        # a live write against prod.
        #
        # So: no guessing. The DB container is named by env, defaulting to the
        # historical sandbox value, and an unset/absent container refuses rather
        # than falls back to anything.
        #
        # The DATABASE is never named either — `run_psql_in_db_container`
        # resolves $POSTGRES_DB inside the container, which is correct on every
        # tier. The literal it replaced (`agentvault_registry_test`) does not
        # exist on the current sandbox, where the database is `frame_test_registry`;
        # psql answered FATAL and the caller read it as "not verified".
        self.db_container = container_name or os.environ.get(
            "API_TEST_REG_DB_CONTAINER", "agentvault_registry_db_test"
        )
        self.db_name = None          # None ⇒ the container's own $POSTGRES_DB
        # Kept for callers/log lines that still read them.
        self.container_name = self.db_container
        self.db_host = None
        
    def execute_sql(self, query: str) -> Optional[str]:
        """Execute SQL in the registry's DB container via docker-py.

        Was `subprocess.run(["docker", "exec", ...])`, which cannot work from
        inside the registry image (no docker CLI) — every call returned None
        through a logger.error, so this helper had been silently dead. The rest
        of api_tests reaches containers through `exec_in_container` (docker-py
        over the mounted socket); use the same road.
        """
        from agentvault_registry.api_tests.multiframe_helpers import (
            run_psql_in_db_container,
        )
        rc, out = run_psql_in_db_container(self.db_container, query, db_name=self.db_name)
        # An absent container surfaces here as a docker exception folded into
        # rc=-1 by exec_in_container. Say WHICH container, so the next reader
        # fixes the env instead of re-deriving this.
        if rc == -1 and "exec exception" in (out or ""):
            logger.error(
                f"DatabaseVerifier: cannot reach DB container "
                f"{self.db_container!r} — refusing to guess another. Set "
                f"API_TEST_REG_DB_CONTAINER to this tier's registry DB. ({out[:160]})"
            )
            return None
        if rc != 0:
            logger.error(f"SQL execution failed (rc={rc}) on "
                         f"{self.db_container}: {out[:300]}")
            return None
        return (out or "").strip()
    
    @staticmethod
    def _escape_sql_param(value: str) -> str:
        """Escape single quotes in SQL parameters to prevent injection."""
        if not isinstance(value, str):
            raise ValueError("SQL parameter must be a string")
        # Reject obviously malicious input
        if any(c in value for c in [";", "--", "/*", "*/", "\x00"]):
            raise ValueError("SQL parameter contains forbidden characters")
        # Escape single quotes (standard SQL escaping)
        return value.replace("'", "''")

    def verify_developer_account(self, email: str) -> bool:
        """Verify a developer account by email"""
        logger.info(f"Verifying developer account: {email}")

        safe_email = self._escape_sql_param(email)
        query = f"UPDATE developers SET is_verified = true WHERE email = '{safe_email}' RETURNING id;"
        result = self.execute_sql(query)

        if result:
            logger.info(f"Successfully verified account {email}")
            return True
        else:
            logger.warning(f"Failed to verify account {email}")
            return False

    def check_developer_exists(self, email: str) -> bool:
        """Check if a developer exists by email"""
        safe_email = self._escape_sql_param(email)
        query = f"SELECT id FROM developers WHERE email = '{safe_email}';"
        result = self.execute_sql(query)
        return bool(result and result.strip())

    def get_developer_info(self, email: str) -> Optional[Dict[str, Any]]:
        """Get developer information"""
        safe_email = self._escape_sql_param(email)
        query = f"SELECT id, name, is_verified, is_admin FROM developers WHERE email = '{safe_email}';"
        result = self.execute_sql(query)
        
        if result:
            parts = result.strip().split('|')
            if len(parts) >= 4:
                return {
                    "id": parts[0].strip(),
                    "name": parts[1].strip(),
                    "is_verified": parts[2].strip() == 't',
                    "is_admin": parts[3].strip() == 't'
                }
        return None
    
    def cleanup_test_accounts(self, email_pattern: str = "test%@example.com"):
        """Clean up old test accounts"""
        logger.info(f"Cleaning up test accounts matching: {email_pattern}")

        safe_pattern = self._escape_sql_param(email_pattern)
        # Delete agents first (foreign key constraint)
        query1 = f"DELETE FROM agents WHERE developer_id IN (SELECT id FROM developers WHERE email LIKE '{safe_pattern}');"
        self.execute_sql(query1)

        # Then delete developers
        query2 = f"DELETE FROM developers WHERE email LIKE '{safe_pattern}';"
        result = self.execute_sql(query2)
        
        if result:
            logger.info("Test accounts cleaned up")


# Singleton instance
db_verifier = DatabaseVerifier()
