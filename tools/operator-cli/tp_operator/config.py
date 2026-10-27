"""Config discovery — find the right .env.operator for the current command.

Priority order (per Operator_CLI_Strategy.md §4.1):
  1. --config PATH (explicit)
  2. --operator NAME → resolved via naming primitives
  3. $TP_OPERATOR_HOME/.env.operator
  4. ./.env.operator (PWD)
  5. /opt/theprotocol/stack/cloud-op-* (enumerate; exactly one match wins)
  6. ~/.tp-operator/config.yaml profile (deferred to v1.1)

The CLI's resolver MUST agree with mainframe primitives — see naming.py.
"""
from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .naming import safe_name

CLOUD_OP_PREFIX = "/opt/theprotocol/stack/cloud-op-"
DEFAULT_BASE = "/opt/theprotocol/stack"


class OperatorNotFound(Exception):
    """Raised when --operator NAME doesn't match any directory."""
    def __init__(self, name: str, searched: List[Path]):
        self.name = name
        self.searched = searched
        super().__init__(
            f"Operator '{name}' not found. Searched: " + ", ".join(str(p) for p in searched)
        )


class AmbiguousOperator(Exception):
    """Raised when discovery finds multiple operator directories with no selector."""
    def __init__(self, candidates: List[Path]):
        self.candidates = candidates
        super().__init__(
            "Multiple operator directories found: "
            + ", ".join(str(c) for c in candidates)
            + ". Use --operator NAME or --all-operators."
        )


@dataclass
class OperatorContext:
    """Resolved operator context — one per CLI invocation (or one per --all-operators iteration).

    §FRAMEKIT P3.2 (2026-09-12): `kind="frame"` is a FRAME stack dir the standup driver built
    (`.env.frame-test` + `docker-compose.frame-test.yml` + `hetzner-demo-run.json`): three databases, its
    own SPIRE server and signer key. Selected with `--frame <stack dir>`; every verb that takes a context
    works on it, and backup/restore know its shape (three dumps, two load-bearing volumes)."""
    name: str                    # canonical safe-name slug (operator) · the frame's slug (frame)
    dir: Path                    # operator directory · the frame's stack dir
    env_path: Path               # .env.operator path · .env.frame-test
    env: Dict[str, str]          # parsed env (last-value-wins on duplicate keys)
    is_archived: bool = False
    kind: str = "operator"       # "operator" | "frame"
    meta: Optional[Dict[str, str]] = None   # frame: hetzner-demo-run.json

    @property
    def compose_file(self) -> Path:
        """Detect operator vs standalone compose file. Operator wins if both present."""
        if self.kind == "frame":
            return self.dir / "docker-compose.frame-test.yml"
        op = self.dir / "docker-compose.operator.yml"
        if op.exists():
            return op
        return self.dir / "docker-compose.standalone.yml"

    # ── frame shape (kind == "frame") ─────────────────────────────────────────────
    @property
    def is_frame(self) -> bool:
        return self.kind == "frame"

    @property
    def frame_env_label(self) -> str:
        """prod | sandbox — the standup's --env-label, from the meta; a frame with no meta says 'unknown'."""
        return str((self.meta or {}).get("env_label") or "unknown")

    @property
    def frame_trust_domain(self) -> str:
        return (self.env.get("SPIRE_TRUST_DOMAIN") or self.env.get("FT_SPIRE_TRUST_DOMAIN")
                or str((self.meta or {}).get("trust_domain") or ""))

    def frame_db_services(self, inspect=None) -> List[Dict[str, str]]:
        """The three databases: compose service, user, db, dump name. The user and db come from the frame's
        OWN env (FT_DB_/FT_TEGDB_/FT_ESDB_ POSTGRES_USER+DB, the D12 template) and, for a frame stood up before
        those keys existed (the 2026-09-03 sandbox pair carries neither), from the DB CONTAINER's own
        POSTGRES_USER/POSTGRES_DB — the same source the auditor slot reads. Never a literal."""
        out = []
        for svc, key, dump in (("db", "FT_DB", "registry"), ("teg-db", "FT_TEGDB", "teg"), ("es-db", "FT_ESDB", "eventstore")):
            user = self.env.get(f"{key}_POSTGRES_USER", ""); db = self.env.get(f"{key}_POSTGRES_DB", "")
            if not (user and db):
                cenv = (inspect or _container_env)(f"{self.name}-{svc}")
                user, db = cenv.get("POSTGRES_USER", ""), cenv.get("POSTGRES_DB", "")
            if user and db:
                out.append({"service": f"{self.name}-{svc}", "user": user, "db": db, "dump": f"{dump}.dump"})
        return out

    def frame_volumes(self) -> List[str]:
        """The two load-bearing named volumes: the registry's signer key (/app/data — §PEERKEYROT: a restore
        without it rotates the frame's credentials under every peer) and the SPIRE server's CA + entries
        (/opt/spire/data — a new CA is a new trust root for every federated peer). Read from the compose."""
        try:
            comp = self.compose_file.read_text()
        except OSError:
            return []
        return [m.group(1) for m in re.finditer(r"^\s+name:\s*(\S+_(?:registry_data|spire_data)_\d+)\s*$", comp, re.M)]

    def frame_app_services(self) -> List[str]:
        """The services that hold the databases and the volumes open; stopped for a restore, in this order."""
        n = self.name
        return [f"{n}-registry", f"{n}-teg", f"{n}-event-store", f"{n}-pgbouncer", f"{n}-cert-writer", f"{n}-spire-agent", f"{n}-spire-server"]

    @property
    def frame_registry_port(self) -> Optional[int]:
        m = re.search(r'127\.0\.0\.1:(\d+):8000', self.compose_file.read_text()) if self.compose_file.exists() else None
        return int(m.group(1)) if m else None

    @property
    def frame_es_port(self) -> Optional[int]:
        m = re.search(r'127\.0\.0\.1:(\d+):8200', self.compose_file.read_text()) if self.compose_file.exists() else None
        return int(m.group(1)) if m else None

    @property
    def is_standalone(self) -> bool:
        return (
            self.env.get("MINTING_AUTHORITY", "").lower() in ("teg-layer", "")
            and not self.env.get("FEDERATION_LICENSE_KEY")
        )

    @property
    def federation_license(self) -> Optional[str]:
        v = self.env.get("FEDERATION_LICENSE_KEY", "").strip()
        return v if v else None

    @property
    def mainframe_url(self) -> str:
        # Host-side override — useful when running the CLI on the same host
        # that runs the mainframe (sandbox dev, GitOps-Ginny multi-op hoster).
        # Operator's .env may point at a docker-internal hostname not resolvable
        # from the host; this lets the operator (or test harness) override.
        override = os.environ.get("TP_OPERATOR_MAINFRAME_URL")
        if override:
            return override.rstrip("/")
        return (
            self.env.get("CENTRAL_REGISTRY_URL")
            or self.env.get("MAINFRAME_PROXY_URL")
            or "https://api.theprotocol.cloud"
        ).rstrip("/")

    @property
    def registry_url(self) -> str:
        """This stack's OWN registry, where its developers, agents and bundles live: the base of the developer-API
        commands (bundle). Not mainframe_url: a developer key is per registry, so the parent refuses an operator's key
        and holds none of its agents (CB-298). TP_OPERATOR_REGISTRY_URL when set, else the host port the compose
        publishes the registry's 8000 on, on this host (so the key never leaves the machine)."""
        override = os.environ.get("TP_OPERATOR_REGISTRY_URL")
        if override:
            return override.rstrip("/")
        text = self.compose_file.read_text() if self.compose_file.exists() else ""
        m = re.search(r'"(?:(?P<addr>[0-9.]+):)?(?:(?P<port>\d+)|\$\{(?P<var>[A-Z_][A-Z0-9_]*):-(?P<dflt>\d+)\}):8000"',
                      text)
        if not m:
            return "http://127.0.0.1:8000"
        port = m.group("port") or self.env.get(m.group("var") or "") or m.group("dflt")
        addr = m.group("addr") if m.group("addr") not in (None, "0.0.0.0") else "127.0.0.1"
        return f"http://{addr}:{port}"


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a .env-style file. Last value wins on duplicate keys (matches
    Docker Compose's behavior — cloud_provisioner's _generate_env_file appends
    overrides after the initial generate-operator-env.sh output)."""
    if not path.exists():
        return {}
    env: Dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # Strip surrounding quotes (single or double)
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        env[key] = val
    return env


def _container_env(container: str) -> Dict[str, str]:
    """A container's env as a dict (docker inspect); {} when it does not exist. Values are never logged."""
    import subprocess
    r = subprocess.run(["docker", "inspect", container, "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    return dict(line.split("=", 1) for line in r.stdout.splitlines() if "=" in line)


class FrameNotFound(Exception):
    """Raised when --frame PATH is not a stack dir the standup driver built."""


def frame_context(stack_dir: Path) -> OperatorContext:
    """§FRAMEKIT P3.2 — the context of a FRAME stack dir (`--frame`). Refuses with a sentence naming what is
    missing: the env, the compose or the meta (a directory with two of the three is not a frame)."""
    d = Path(stack_dir).expanduser().resolve()
    env_p = d / ".env.frame-test"; comp = d / "docker-compose.frame-test.yml"; meta_p = d / "hetzner-demo-run.json"
    missing = [str(x.name) for x in (env_p, comp, meta_p) if not x.exists()]
    if missing:
        raise FrameNotFound(f"{d} is not a frame stack dir the standup driver built: missing {', '.join(missing)}")
    import json as _json
    try:
        meta = _json.loads(meta_p.read_text())
    except ValueError as e:
        raise FrameNotFound(f"{meta_p} is not valid JSON: {e}")
    name = str(meta.get("name") or "").strip()
    if not name:
        raise FrameNotFound(f"{meta_p} names no frame (`name`)")
    return OperatorContext(name=name, dir=d, env_path=env_p, env=parse_env_file(env_p), kind="frame", meta=meta)


def discover_all_operators() -> List[Path]:
    """List every cloud-op-* directory with a .env.operator (excluding archived)."""
    results: List[Path] = []
    for raw in sorted(glob.glob(f"{CLOUD_OP_PREFIX}*")):
        p = Path(raw)
        if "archived" in p.name:
            continue
        if (p / ".env.operator").exists():
            results.append(p)
    return results


def resolve_operator_dir(name: str) -> Path:
    """Resolve --operator NAME to an operator directory via canonical _safe_name.

    Accepts: bare slug ('london'), full slug ('op-london'), full dir name
    ('cloud-op-op-london'), display name with spaces ('Sandbox Alpha'),
    or absolute path.
    """
    p = Path(name)
    if p.is_absolute() and (p / ".env.operator").exists():
        return p

    safe = safe_name(name)
    candidates = [
        Path(f"{CLOUD_OP_PREFIX}{safe}"),
        Path(f"{CLOUD_OP_PREFIX}op-{safe}"),
    ]
    # Allow operators whose dir embeds the slug with a hyphenated form (e.g.,
    # "sandbox-alpha" input → "sandboxalpha" safe_name → cloud-op-sandboxalpha)
    safe_no_hyphen = safe.replace("-", "")
    if safe_no_hyphen != safe:
        candidates.append(Path(f"{CLOUD_OP_PREFIX}{safe_no_hyphen}"))

    for c in candidates:
        if (c / ".env.operator").exists():
            return c

    # Last-ditch: scan cloud-op-* and compare each env's REGISTRY_NAME / OPERATOR_REGISTRY_NAME
    for d in discover_all_operators():
        env = parse_env_file(d / ".env.operator")
        reg_safe = safe_name(env.get("REGISTRY_NAME", ""))
        op_safe = safe_name(env.get("OPERATOR_REGISTRY_NAME", ""))
        reg_stripped = reg_safe.removeprefix("cloud-op-")
        if safe in {reg_safe, op_safe, reg_stripped}:
            return d
        if safe_no_hyphen in {reg_safe, op_safe, reg_stripped}:
            return d

    raise OperatorNotFound(name, candidates)


def resolve_context(
    config_path: Optional[Path] = None,
    operator_name: Optional[str] = None,
) -> OperatorContext:
    """Resolve a single OperatorContext from CLI flags + env + cwd discovery."""
    # 1. Explicit --config wins
    if config_path is not None:
        cp = Path(config_path).expanduser()
        if not cp.exists():
            raise FileNotFoundError(f"--config path does not exist: {cp}")
        env = parse_env_file(cp)
        return OperatorContext(
            name=safe_name(env.get("REGISTRY_NAME", cp.parent.name)),
            dir=cp.parent,
            env_path=cp,
            env=env,
        )

    # 2. --operator NAME
    if operator_name:
        d = resolve_operator_dir(operator_name)
        env_path = d / ".env.operator"
        env = parse_env_file(env_path)
        return OperatorContext(
            name=safe_name(env.get("REGISTRY_NAME", d.name)),
            dir=d,
            env_path=env_path,
            env=env,
        )

    # 3. $TP_OPERATOR_HOME
    tp_home = os.environ.get("TP_OPERATOR_HOME")
    if tp_home:
        env_path = Path(tp_home) / ".env.operator"
        if env_path.exists():
            env = parse_env_file(env_path)
            return OperatorContext(
                name=safe_name(env.get("REGISTRY_NAME", Path(tp_home).name)),
                dir=Path(tp_home),
                env_path=env_path,
                env=env,
            )

    # 4. ./.env.operator
    cwd = Path.cwd()
    env_path = cwd / ".env.operator"
    if env_path.exists():
        env = parse_env_file(env_path)
        return OperatorContext(
            name=safe_name(env.get("REGISTRY_NAME", cwd.name)),
            dir=cwd,
            env_path=env_path,
            env=env,
        )

    # 5. /opt/theprotocol/stack/cloud-op-* — auto-discover ONE
    candidates = discover_all_operators()
    if len(candidates) == 1:
        d = candidates[0]
        env_path = d / ".env.operator"
        env = parse_env_file(env_path)
        return OperatorContext(
            name=safe_name(env.get("REGISTRY_NAME", d.name)),
            dir=d,
            env_path=env_path,
            env=env,
        )
    elif len(candidates) > 1:
        raise AmbiguousOperator(candidates)

    raise OperatorNotFound("(discovery)", [Path(CLOUD_OP_PREFIX + "*")])


def resolve_all_contexts() -> List[OperatorContext]:
    """For --all-operators bulk mode."""
    contexts: List[OperatorContext] = []
    for d in discover_all_operators():
        env_path = d / ".env.operator"
        env = parse_env_file(env_path)
        contexts.append(
            OperatorContext(
                name=safe_name(env.get("REGISTRY_NAME", d.name)),
                dir=d,
                env_path=env_path,
                env=env,
            )
        )
    return contexts
