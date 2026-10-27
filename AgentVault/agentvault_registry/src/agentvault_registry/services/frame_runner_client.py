"""§FRAMEPROV P3 (2026-09-13): the registry's half of the host frame runner.

His decision 2026-09-13: the registry never holds host root to stand a frame up. The runner
(`tools/frame-runner/frame_runner.py` in the stack repo) is a root service on the HOST with a closed job set; this
registry only speaks to its unix socket, one JSON object on one line in and one line out, then the connection closes.
The runner decides everything (protected names, host gates, one job at a time, the caller's uid by SO_PEERCRED), and a
refusal comes back as its own sentence.

A registry with no socket mounted (every node but the one a frame is provisioned from) answers "unavailable" and names
the path, never an empty list that reads as "no frames".
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from typing import Any

DEFAULT_SOCKET = "/run/theprotocol/frame-runner.sock"
# The runner's own plan ceiling is 300 s (`plan_timeout_s`), and a standup runs a plan before it starts.
LONG_TIMEOUT_S = 330.0
SHORT_TIMEOUT_S = 20.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class RunnerUnavailable(Exception):
    """The socket is missing, not ours to open, or silent. The request did not reach the runner, or got no answer."""


class RunnerRefused(Exception):
    """The runner's own sentence. Nothing was started."""


class RunnerError(Exception):
    """The runner failed inside a request, or answered something that is not its protocol."""


def socket_path() -> str:
    return os.getenv("FRAME_RUNNER_SOCKET", DEFAULT_SOCKET)


# §F6 on production (2026-09-30): the runner serves an operator's host work on a SECOND socket (its OPERATOR_OPS, which
# it deliberately never adds to the full socket's ops). A registry that mounts the runner's whole directory (EU,
# sbx-alpha) sees the FULL socket at the top and the operator socket in the operator subdirectory; a registry that mounts
# the operator directory alone (the kit template, ASIA and sbx-beta since §F6 WP6.0) sees the operator socket at the
# top. socket_path() answered the top for every op, so on EU operator_ping, provision, status and teardown reached the
# full socket and were refused, and HOST_REACH_PREFER=runner could only fail closed there; the identity and lifecycle
# calls already took the operator socket (spire_ops_client.operator_socket_path). One rule for every operator op now.
OPERATOR_SOCKET_ENV = "FRAME_RUNNER_OPERATOR_SOCKET"
OPERATOR_SUBDIR_SOCKET = "/run/theprotocol/operator/frame-runner.sock"


def operator_socket_path() -> str:
    """The socket an operator op goes to: FRAME_RUNNER_OPERATOR_SOCKET when set; else the operator subdirectory's
    socket when this registry sees one; else socket_path(), the top of a mount that IS the operator directory (so a
    frame without the subdirectory dials exactly what it dialled before)."""
    explicit = os.getenv(OPERATOR_SOCKET_ENV, "").strip()
    if explicit:
        return explicit
    return OPERATOR_SUBDIR_SOCKET if os.path.exists(OPERATOR_SUBDIR_SOCKET) else socket_path()


def path_for(op: str) -> str:
    """Which socket an op goes to. The runner's own partition decides: an op whose name starts with operator_ is an
    operator op and goes to the operator socket; every other op (a frame's standup, plan, list, status) to
    socket_path()."""
    return operator_socket_path() if str(op).startswith("operator_") else socket_path()


def _exchange(path: str, request: dict, timeout: float) -> dict:
    buf = b""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall((json.dumps(request) + "\n").encode("utf-8"))
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_RESPONSE_BYTES:
                    raise RunnerError(f"the frame runner's answer is larger than {MAX_RESPONSE_BYTES} bytes")
    except FileNotFoundError:
        raise RunnerUnavailable(f"no frame runner socket at {path} on this registry")
    except PermissionError:
        raise RunnerUnavailable(f"this registry's user may not open {path}")
    except ConnectionRefusedError:
        raise RunnerUnavailable(f"nothing is listening on {path}")
    except socket.timeout:
        raise RunnerUnavailable(f"the frame runner did not answer within {timeout:g} s")
    except OSError as exc:
        raise RunnerUnavailable(f"the frame runner socket failed ({type(exc).__name__})")
    try:
        envelope = json.loads(buf.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RunnerError("the frame runner's answer is not one JSON line")
    if not isinstance(envelope, dict):
        raise RunnerError("the frame runner's answer is not a JSON object")
    return envelope


def unwrap(envelope: dict) -> Any:
    if envelope.get("ok") is True:
        return envelope.get("result")
    if envelope.get("refused") is not None:
        raise RunnerRefused(str(envelope["refused"]))
    raise RunnerError(str(envelope.get("error") or "the frame runner answered neither a result nor a refusal"))


async def call(op: str, *, timeout: float = SHORT_TIMEOUT_S, **fields: Any) -> Any:
    """One request to the runner, off the event loop (a plan runs the standup driver)."""
    envelope = await asyncio.to_thread(_exchange, path_for(op), {"op": op, **fields}, timeout)
    return unwrap(envelope)
