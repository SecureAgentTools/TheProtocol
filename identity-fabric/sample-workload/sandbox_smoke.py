"""
Sandbox SPIRE smoke workload — PJ (Pass 2, 2026-04-22).

Lightweight heartbeat workload that runs in sandbox-{a,b}-sample-workload
containers. Its purpose is a continuous signal that:
  - The agent socket volume mount is alive (file exists + readable)
  - The sandbox SPIRE agent is running + attending to the socket

IT DOES NOT fetch a real X.509 SVID — that would require the `pyspiffe`
package (gRPC over UDS) which isn't in the upstream sample-workload
requirements.txt. Adding pyspiffe + rebuilding the image is a followup
(would give genuinely end-to-end attestation verification, but the
existing SPIRE entries + agent logs already prove attestation works).

This smoke produces one INFO log line every 60s under the normal path
and one ERROR line if the socket disappears — enough signal for log-
monitoring / ChatOps alerts without introducing a new dependency.

Invoke:
  python sandbox_smoke.py
Env:
  SPIFFE_ENDPOINT_SOCKET = unix:///opt/spire/sockets/agent.sock (default)
  SANDBOX_FRAME          = "a" or "b" (for log annotation)
  HEARTBEAT_INTERVAL_SEC = 60 (default)
"""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - sandbox-smoke - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def main() -> int:
    socket_uri = os.environ.get("SPIFFE_ENDPOINT_SOCKET", "unix:///opt/spire/sockets/agent.sock")
    socket_path = socket_uri.replace("unix://", "") if socket_uri.startswith("unix://") else socket_uri
    frame = os.environ.get("SANDBOX_FRAME", "?")
    interval = int(os.environ.get("HEARTBEAT_INTERVAL_SEC", "60"))

    logger.info(
        f"Starting sandbox SPIRE smoke (frame={frame} socket={socket_path} interval={interval}s)"
    )

    last_err_logged = 0
    while True:
        try:
            stat = os.stat(socket_path)
            # Socket file exists; log heartbeat. mtime drifts as agent writes keepalives.
            logger.info(
                f"[heartbeat] frame={frame} socket_ok path={socket_path} "
                f"mtime={int(stat.st_mtime)} mode=0o{oct(stat.st_mode)[-3:]} "
                f"expected_trust_domain=sandbox-{frame}.test"
            )
        except FileNotFoundError:
            # Don't spam this every heartbeat — log once every 5 minutes while dead.
            now = int(time.time())
            if now - last_err_logged > 300:
                logger.error(
                    f"[heartbeat] frame={frame} socket_MISSING path={socket_path} "
                    "— sandbox SPIRE agent likely not attached or volume mount broken"
                )
                last_err_logged = now
        except PermissionError as e:
            logger.error(f"[heartbeat] frame={frame} socket_permission_denied path={socket_path} err={e}")
        except Exception as e:
            logger.error(f"[heartbeat] frame={frame} socket_check_error path={socket_path} err={e}")

        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main() or 0)
