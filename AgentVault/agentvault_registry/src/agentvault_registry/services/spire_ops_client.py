"""The frame runner's identity ops, from the registry's side (§F6 WP6.1, 2026-09-26, his words "approved ... do it fully
autonomously").

What the registry did against its OWN SPIRE server through the Docker socket (the frame-invitation rail's bundle and
federation steps, the workload entries' -federatesWith, IRONHAND's entries, SVID mint and node list) can instead be
asked of the frame runner, on its OPERATOR socket: closed ops the runner validates argument by argument and binds to the
calling frame (tools/frame-runner/frame_runner.py, IDENTITY_OPS). Each rail chooses per its own flag:

  FRAME_TRUST_SPIRE_VIA   local (default) | runner   the invitation rail (bundles, federation) and the entries' federation
  IRONHAND_SPIRE_MODE     unset (auto) | local | proxy | runner   IRONHAND (services/agent_spire.py)

A rail set to runner FAILS CLOSED: a missing socket, an unanswered call or a refusal raises SpireOpsUnavailable with the
runner's own sentence, and nothing falls back to the Docker socket, which is exactly what F6 takes away.
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Optional, Tuple

from agentvault_registry.services import frame_runner_client as _frc

OPERATOR_SOCKET_ENV = "FRAME_RUNNER_OPERATOR_SOCKET"
# a frame that mounts the runner's whole directory (EU, sbx-alpha) sees the operator socket in its subdirectory; a frame
# that mounts the operator directory alone (the kit template, ASIA and sbx-beta since §F6 WP6.0) sees it at the top
_OPERATOR_SUBDIR_SOCKET = "/run/theprotocol/operator/frame-runner.sock"
_OPERATOR_TOP_SOCKET = "/run/theprotocol/frame-runner.sock"
SPIRE_BIN = "/opt/spire/bin/spire-server"
TRUST_VIA_ENV = "FRAME_TRUST_SPIRE_VIA"


class SpireOpsUnavailable(RuntimeError):
    """The runner could not do the identity op: no socket, no answer, or a refusal (its sentence is the message)."""


def operator_socket_path() -> str:
    explicit = os.getenv(OPERATOR_SOCKET_ENV, "").strip()
    if explicit:
        return explicit
    return _OPERATOR_SUBDIR_SOCKET if os.path.exists(_OPERATOR_SUBDIR_SOCKET) else _OPERATOR_TOP_SOCKET


def trust_via() -> str:
    """The frame-invitation rail's SPIRE route: "local" or "runner". Any other value raises: a flag this code does not
    understand is refused, never guessed."""
    v = (os.getenv(TRUST_VIA_ENV) or "local").strip().lower()
    if v not in ("local", "runner"):
        raise SpireOpsUnavailable(f"{TRUST_VIA_ENV}={v!r} is neither 'local' nor 'runner'")
    return v


def call(op: str, *, timeout: float = 30.0, **fields) -> dict:
    """One identity op on the runner's operator socket; the op's result ({rc, stdout, stderr, ...}) or a raise."""
    path = operator_socket_path()
    if not os.path.exists(path):
        raise SpireOpsUnavailable(f"no frame runner operator socket at {path}")
    try:
        envelope = _frc._exchange(path, {"op": op, **fields}, timeout)
    except Exception as exc:  # noqa: BLE001 — the class is the finding; the caller fails closed with it
        raise SpireOpsUnavailable(f"the frame runner at {path} did not answer {op} ({type(exc).__name__})") from exc
    if isinstance(envelope, dict) and envelope.get("ok") is True and isinstance(envelope.get("result"), dict):
        return envelope["result"]
    reason = (envelope or {}).get("refused") or (envelope or {}).get("error") or "no reason given"
    raise SpireOpsUnavailable(f"the frame runner refused {op}: {reason}")


async def acall(op: str, *, timeout: float = 30.0, **fields) -> dict:
    return await asyncio.to_thread(lambda: call(op, timeout=timeout, **fields))


def triple(result: dict) -> Tuple[int, str, str]:
    """The (rc, stdout, stderr) shape every SPIRE call site in the registry already reads."""
    return int(result.get("rc", 1)), str(result.get("stdout") or ""), str(result.get("stderr") or "")


def _strip_spiffe(value: str) -> str:
    v = (value or "").strip()
    return v[len("spiffe://"):].rstrip("/") if v.startswith("spiffe://") else v.rstrip("/")


# The argv shapes the registry's SPIRE code builds, each mapped to its runner op. A shape not listed here has no op, and
# asking for it raises: the registry never widens what it asks the runner for by accident.
_FLAG_FIELDS = {
    ("bundle", "list"): {"-id": "trust_domain", "-format": "format"},
    ("bundle", "show"): {"-format": "format"},
    ("bundle", "delete"): {"-mode": "mode", "-id": "trust_domain"},
    ("federation", "list"): {},
    ("federation", "delete"): {"-id": "trust_domain"},     # §F6 WP6.2: a revoke ends the relationship too
    ("federation", "create"): {"-trustDomain": "trust_domain", "-bundleEndpointURL": "bundle_endpoint_url",
                               "-bundleEndpointProfile": "profile", "-endpointSpiffeID": "endpoint_spiffe_id"},
    ("federation", "update"): {"-trustDomain": "trust_domain", "-bundleEndpointURL": "bundle_endpoint_url",
                               "-bundleEndpointProfile": "profile", "-endpointSpiffeID": "endpoint_spiffe_id"},
    ("entry", "show"): {"-entryID": "entry_id", "-spiffeID": "spiffe_id", "-parentID": "parent_id"},
    ("entry", "count"): {},
    ("agent", "list"): {},
}


def op_for_argv(argv: List[str]) -> Tuple[str, dict]:
    """(runner op, its fields) for one spire-server argv, or SpireOpsUnavailable for a shape that has no op."""
    args = list(argv)
    if args and args[0] == SPIRE_BIN:
        args = args[1:]
    key = tuple(args[:2])
    flags = _FLAG_FIELDS.get(key)
    rest = args[2:]
    if flags is None or len(rest) % 2:
        raise SpireOpsUnavailable(f"no runner op for `spire-server {' '.join(args[:2])}` with these arguments")
    fields = {}
    for flag, value in zip(rest[0::2], rest[1::2]):
        name = flags.get(flag)
        if name is None:
            raise SpireOpsUnavailable(f"no runner op for `spire-server {' '.join(args[:2])}` with {flag}")
        fields[name] = _strip_spiffe(value) if name == "trust_domain" else value
    return f"spire_{key[0]}_{key[1]}", fields


def run_argv(argv: List[str], *, timeout: float = 30.0) -> Tuple[int, str, str]:
    op, fields = op_for_argv(argv)
    return triple(call(op, timeout=timeout, **fields))


async def arun_argv(argv: List[str], *, timeout: float = 30.0) -> Tuple[int, str, str]:
    return await asyncio.to_thread(lambda: run_argv(argv, timeout=timeout))


def bundle_set(trust_domain: str, bundle: str, fmt: str) -> Tuple[int, str, str]:
    return triple(call("spire_bundle_set", trust_domain=_strip_spiffe(trust_domain), bundle=bundle, format=fmt))


def entry_update_federates(entry_id: str, add: List[str]) -> dict:
    return call("spire_entry_update_federates", entry_id=entry_id, add=[_strip_spiffe(td) for td in add])


def entry_create(*, spiffe_id: str, parent_id: str, selectors: List[str], ttl: int, dns: Optional[List[str]] = None,
                 federates_with: Optional[List[str]] = None) -> Tuple[int, str, str]:
    return triple(call("spire_entry_create", spiffe_id=spiffe_id, parent_id=parent_id, selectors=list(selectors),
                       ttl=int(ttl), dns=list(dns or []), federates_with=list(federates_with or [])))


def entry_delete(entry_id: str) -> Tuple[int, str, str]:
    return triple(call("spire_entry_delete", entry_id=entry_id))


def x509_mint(*, spiffe_id: str, ttl: int, dns: Optional[List[str]] = None) -> Tuple[int, str, str]:
    return triple(call("spire_x509_mint", spiffe_id=spiffe_id, ttl=int(ttl), dns=list(dns or [])))
