"""Federation test agent — long-running container that onboards itself to a
sandbox registry, enrolls for IRONHAND mTLS, and stays alive as a stable
fixture for federation-suite tests.

First boot:
  1. Login as sandbox commander (admin@test.sandbox / TestAdmin123!)
  2. Request bootstrap-token
  3. Create agent via /onboard/create_agent
  4. Save DID + client_id + client_secret to /var/lib/agent/creds.json
  5. Issue agent JWT via /auth/agent/token
  6. POST /agent/enable-mtls (registers SPIRE entry, sets mtls_enabled=true,
     patches agent_card with mTLS metadata)
  7. Heartbeat loop — refresh JWT every 9min, log alive every 60s

Subsequent boots:
  1. Read creds.json from volume
  2. Issue fresh JWT
  3. Heartbeat loop
  4. (enable-mtls is idempotent — re-runs return status='already_enrolled')

Skipping client-side SVID fetch from SPIFFE socket — that requires a docker
label that depends on the server-generated DID (chicken-and-egg). The
registry-side mTLS enrollment + agent_card patching is still tested.

Env:
  REGISTRY_URL          — e.g. http://registry-test:8000
  SANDBOX_ADMIN_EMAIL   — defaults to admin@test.sandbox
  SANDBOX_ADMIN_PASSWORD — defaults to TestAdmin123!
  AGENT_LABEL           — short name used in humanReadableId + logs (e.g. "a", "b")
  SPIFFE_ENDPOINT_SOCKET — unused currently but mounted for future SVID fetch
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Dict, Optional

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - fed-test-agent - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

REGISTRY_URL = os.environ.get("REGISTRY_URL", "http://registry-test:8000").rstrip("/")
ADMIN_EMAIL = os.environ.get("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox")
ADMIN_PASSWORD = os.environ.get("SANDBOX_ADMIN_PASSWORD", "TestAdmin123!")
AGENT_LABEL = os.environ.get("AGENT_LABEL", "a")
CREDS_PATH = pathlib.Path(os.environ.get("CREDS_PATH", "/var/lib/agent/creds.json"))
HEARTBEAT_SEC = int(os.environ.get("HEARTBEAT_INTERVAL_SEC", "60"))
JWT_REFRESH_SEC = int(os.environ.get("JWT_REFRESH_INTERVAL_SEC", "540"))  # 9 min


def _login_admin(client: httpx.Client) -> str:
    r = client.post(
        f"{REGISTRY_URL}/api/v1/auth/login",
        data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _bootstrap_token(client: httpx.Client, dev_jwt: str) -> str:
    r = client.post(
        f"{REGISTRY_URL}/api/v1/onboard/bootstrap/request-token",
        json={
            "agent_type_hint": "federation_test_agent",
            "requested_by": f"sandbox_fed_test_agent_{AGENT_LABEL}",
        },
        headers={
            "Authorization": f"Bearer {dev_jwt}",
            "Content-Type": "application/json",
        },
        timeout=15.0,
    )
    r.raise_for_status()
    tok = r.json().get("bootstrap_token")
    if not tok:
        raise RuntimeError(f"bootstrap-token missing in response: {r.text[:200]}")
    return tok


def _create_agent(client: httpx.Client, bootstrap_tok: str) -> Dict[str, Any]:
    ts = int(time.time())
    card = {
        "humanReadableId": f"federation-test-agent-{AGENT_LABEL}-{ts}",
        "name": f"Federation Test Agent ({AGENT_LABEL})",
        "description": (
            f"Long-running test agent — onboarded by sandbox-{AGENT_LABEL}-fed-test-agent. "
            "Stable fixture for federation-suite tests covering agent_card pull-sync, "
            "IRONHAND mTLS enrollment, JWS signature verification, and W3 echo prevention."
        ),
        "agentVersion": "1.0",
        "schemaVersion": "1.0",
        "url": f"https://federation-test.sandbox/{AGENT_LABEL}",
        "provider": {
            "name": "Federation Test Suite",
            "url": "https://sandbox.theprotocol.cloud",
        },
        "capabilities": {
            "a2aVersion": "1.0",
            "supportedMessageParts": ["text"],
            "supportsPushNotifications": False,
        },
        "authSchemes": [
            {
                "scheme": "oauth2",
                "tokenUrl": f"{REGISTRY_URL}/api/v1/auth/agent/token",
            },
        ],
    }
    r = client.post(
        f"{REGISTRY_URL}/api/v1/onboard/create_agent",
        json={"agent_did_method": "theprotocol", "agent_card": card},
        headers={
            "Bootstrap-Token": bootstrap_tok,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"create_agent {r.status_code}: {r.text[:300]}")
    return r.json()


def _mint_agent_jwt(client: httpx.Client, client_id: str, client_secret: str) -> str:
    r = client.post(
        f"{REGISTRY_URL}/api/v1/auth/agent/token",
        data={
            "grant_type": "password",
            "username": client_id,
            "password": client_secret,
            "scope": "",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _enable_mtls(client: httpx.Client, agent_jwt: str) -> Dict[str, Any]:
    r = client.post(
        f"{REGISTRY_URL}/api/v1/agent/enable-mtls",
        headers={"Authorization": f"Bearer {agent_jwt}"},
        timeout=30.0,
    )
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 409:
        return {"status": "already_enrolled", "http_409": True}
    raise RuntimeError(f"enable-mtls {r.status_code}: {r.text[:300]}")


def _onboard_and_save(client: httpx.Client) -> Dict[str, Any]:
    """First-boot path: full onboarding flow → save creds → enable mTLS."""
    log.info(f"first boot — onboarding {AGENT_LABEL} against {REGISTRY_URL}")
    dev_jwt = _login_admin(client)
    log.info("admin login OK")
    bt = _bootstrap_token(client, dev_jwt)
    log.info("bootstrap-token OK")
    creds = _create_agent(client, bt)
    log.info(f"agent created: did={creds.get('agent_did')[:40]}... client_id={creds.get('client_id')}")
    # Persist to volume so a container restart doesn't re-create
    CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDS_PATH.write_text(json.dumps(creds))
    log.info(f"creds persisted to {CREDS_PATH}")
    return creds


def main() -> int:
    log.info("=" * 60)
    log.info(f"Federation Test Agent starting — label={AGENT_LABEL}")
    log.info(f"REGISTRY_URL={REGISTRY_URL}")
    log.info(f"CREDS_PATH={CREDS_PATH}")
    log.info(f"SPIFFE_ENDPOINT_SOCKET={os.environ.get('SPIFFE_ENDPOINT_SOCKET', '(unset)')}")
    log.info("=" * 60)

    # Wait briefly for registry to come up (compose depends_on isn't always sufficient)
    for attempt in range(60):
        try:
            with httpx.Client() as c:
                r = c.get(f"{REGISTRY_URL}/.well-known/registry-card.json", timeout=5.0)
                if r.status_code == 200:
                    log.info("registry reachable")
                    break
        except Exception:
            pass
        log.info(f"waiting for registry... (attempt {attempt + 1})")
        time.sleep(5)
    else:
        log.error("registry never came up — exiting")
        return 1

    with httpx.Client() as client:
        # Load or create creds
        if CREDS_PATH.exists():
            try:
                creds = json.loads(CREDS_PATH.read_text())
                log.info(f"loaded persisted creds: did={creds.get('agent_did')[:40]}...")
            except Exception as e:
                log.warning(f"creds.json corrupted ({e!r}) — re-onboarding")
                creds = _onboard_and_save(client)
        else:
            creds = _onboard_and_save(client)

        # Issue first agent JWT + enable mTLS
        agent_jwt = ""
        for attempt in range(3):
            try:
                agent_jwt = _mint_agent_jwt(client, creds["client_id"], creds["client_secret"])
                log.info("agent JWT issued")
                break
            except Exception as e:
                log.warning(f"mint_jwt attempt {attempt + 1} failed: {e!r}")
                time.sleep(5)
        if not agent_jwt:
            log.error("issuing the agent JWT failed after 3 attempts — exiting")
            return 1
        last_jwt_mint = time.time()

        try:
            mtls_resp = _enable_mtls(client, agent_jwt)
            log.info(f"IRONHAND enrollment: {json.dumps(mtls_resp)[:300]}")
        except Exception as e:
            log.error(f"enable-mtls failed (non-fatal — will retry next loop): {e!r}")

        # Heartbeat loop
        log.info(f"entering heartbeat loop — interval={HEARTBEAT_SEC}s, jwt-refresh={JWT_REFRESH_SEC}s")
        loop_iter = 0
        while True:
            loop_iter += 1
            try:
                if time.time() - last_jwt_mint > JWT_REFRESH_SEC:
                    agent_jwt = _mint_agent_jwt(client, creds["client_id"], creds["client_secret"])
                    last_jwt_mint = time.time()
                    log.info(f"agent JWT refreshed (loop #{loop_iter})")
                log.info(f"alive #{loop_iter} — did={creds['agent_did'][:40]}...")
            except Exception as e:
                log.error(f"heartbeat error: {e!r}")
            time.sleep(HEARTBEAT_SEC)


if __name__ == "__main__":
    sys.exit(main())
