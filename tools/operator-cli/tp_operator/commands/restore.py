"""tp-operator restore — atomic restore from a backup archive.

Inverse of backup. Per Operator_CLI_Strategy.md §6.6 three-layer safety net:
  1. Snapshot the current state BEFORE restoring (so a botched restore is recoverable)
  2. Verify the archive manifest's SHA-256 entries before touching anything
  3. Refuse to proceed if archive's operator_did doesn't match destination
     (unless --force-cross-operator)

Restore order matches backup's manifest:
  - stop the stack
  - restore .env.operator + configs
  - bring DBs only (db + teg-db) up; wait for healthy
  - psql -d <db> <registry.dump>  and teg.dump via docker compose exec
  - bring the rest of the stack up
  - wait for /health 200
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

import typer

from ..config import OperatorContext
from ..docker_runner import (
    _compose_cmd,
    compose_down,
    compose_ps_json,
    compose_up,
    docker_info_ok,
)
from ..output import Output, detect_output_mode
from ..pidlock import LockAcquireError, acquire_lock


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _wait_for_db(ctx: OperatorContext, service: str, *, timeout_s: int = 60) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        services = compose_ps_json(ctx)
        for s in services:
            if s.get("Service") == service:
                if (s.get("State") or "").lower() == "running" and (s.get("Health") or "").lower() in ("healthy", "none", ""):
                    return True
        time.sleep(2)
    return False


def _verify_manifest(td_p: Path) -> Dict[str, Any]:
    manifest_path = td_p / "MANIFEST.json"
    if not manifest_path.exists():
        raise RuntimeError("archive missing MANIFEST.json")
    manifest = json.loads(manifest_path.read_text())
    errors = []
    for entry in manifest.get("entries", []):
        p = td_p / entry["path"]
        if not p.exists():
            errors.append(f"missing entry: {entry['path']}")
            continue
        expected = entry["sha256"]
        got = _sha256_file(p)
        if expected != got:
            errors.append(f"sha mismatch {entry['path']}: expected={expected} got={got}")
    if errors:
        raise RuntimeError("manifest verification failed: " + "; ".join(errors[:5]))
    return manifest


def _http_code(url: str, timeout: float = 5.0) -> int:
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


def _volume_untar(volume: str, tgz: Path, helper_image: str) -> int:
    """Replace a volume's content with the archive's (the consumer is stopped by the caller)."""
    cmd = ["docker", "run", "--rm", "-v", f"{volume}:/v", "-v", f"{tgz.parent}:/in:ro", "--entrypoint", "sh", helper_image,
           "-c", f"find /v -mindepth 1 -delete && tar xzf /in/{tgz.name} -C /v"]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    return r.returncode


def _do_frame_restore(ctx: OperatorContext, out: Output, archive: Path, *, snapshot_first: bool = True,
                      force_cross_frame: bool = False, allow_production: bool = False) -> Dict[str, Any]:
    """§FRAMEKIT P3.2 (2026-09-12) — restore a FRAME from `tp backup --frame`. Order: verify every SHA-256 ·
    refuse another frame's archive (trust domain) · refuse a production frame unless said so · snapshot first ·
    stop everything that holds a database or a volume open (registry, TEG, event store, pgbouncer, cert-writer,
    SPIRE agent + server) · restore the EVENT STORE first (the ledger the registry's balance sync reads), then
    the TEG, then the registry · the two volumes · start the stack · wait for the registry's /health."""
    if not archive.exists():
        raise RuntimeError(f"archive not found: {archive}")
    from .backup import _do_frame_backup
    with tempfile.TemporaryDirectory(prefix="tp-frame-restore-") as td:
        td_p = Path(td)
        out.line("[dim]Extracting archive...[/]")
        with tarfile.open(archive, "r:gz") as tar:
            try:
                tar.extractall(td_p, filter="data")
            except TypeError:
                tar.extractall(td_p)
        out.line("[dim]Verifying manifest checksums...[/]")
        manifest = _verify_manifest(td_p)
        if manifest.get("kind") != "frame":
            raise RuntimeError(f"this archive is not a frame backup (kind={manifest.get('kind')!r}); use `tp restore` without --frame for an operator archive")
        atd, ctd = manifest.get("trust_domain") or "", ctx.frame_trust_domain
        if atd and ctd and atd != ctd and not force_cross_frame:
            raise RuntimeError(f"archive trust_domain={atd} != this frame's {ctd}; pass --force-cross-frame to override "
                               f"(a frame restored under another frame's SPIRE root is a new trust root for every peer)")
        if ctx.frame_env_label == "prod" and not allow_production:
            raise RuntimeError(f"{ctx.name} is a PRODUCTION frame (env_label=prod): a restore replaces its ledger — pass "
                               f"--i-mean-production to proceed (never over a production database by accident)")
        pre = None
        if snapshot_first:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            pre = ctx.dir / f"pre-restore-{ts}.tar.gz"
            out.line(f"[dim]Pre-restore snapshot → {pre}[/]")
            _do_frame_backup(ctx, out, pre)
        stop = ctx.frame_app_services()
        out.line(f"[dim]stopping {', '.join(stop)}...[/]")
        r = subprocess.run(_compose_cmd(ctx, "stop", *stop), capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"compose stop failed: {(r.stderr or '')[-300:]}")
        for d in ctx.frame_db_services():
            if not _wait_for_db(ctx, d["service"], timeout_s=60):
                raise RuntimeError(f"{d['service']} is not running: cannot restore into it")
        # the ledger first, then the TEG, then the registry (the manifest's order is registry/teg/eventstore)
        order = {"eventstore.dump": 0, "teg.dump": 1, "registry.dump": 2}
        restored = []
        for d in sorted(manifest.get("databases", []), key=lambda x: order.get(x["dump"], 9)):
            dump = td_p / "db" / d["dump"]
            if not dump.exists():
                raise RuntimeError(f"archive has no {d['dump']}")
            out.line(f"[dim]pg_restore {d['service']} ({d['db']}) ← {d['dump']}...[/]")
            with dump.open("rb") as f:
                cmd = _compose_cmd(ctx, "exec", "-T", d["service"], "pg_restore", "-U", d["user"], "-d", d["db"],
                                   "--clean", "--if-exists", "--no-owner", "--single-transaction")
                rr = subprocess.run(cmd, stdin=f, capture_output=True, timeout=900)
            if rr.returncode != 0:
                # pg_restore --clean on an existing schema warns per object it drops; only a real ERROR aborts
                err = rr.stderr.decode(errors="replace")
                if "ERROR" in err:
                    raise RuntimeError(f"pg_restore {d['service']} failed: {err[-400:]}")
                out.warn(f"pg_restore {d['service']} had warnings (continuing): {err[-200:]}")
            restored.append(d["dump"])
        vols_done = []
        helper = manifest.get("volume_helper_image") or "alpine:3"
        for v in manifest.get("volumes", []):
            tgz = td_p / "volumes" / f"{v}.tgz"
            if not tgz.exists():
                raise RuntimeError(f"archive has no volume tar for {v}")
            if subprocess.run(["docker", "volume", "inspect", v], capture_output=True).returncode != 0:
                raise RuntimeError(f"volume {v} does not exist on this host — the archive belongs to a stack this host has not created")
            out.line(f"[dim]volume {v} ← {tgz.name}...[/]")
            rc = _volume_untar(v, tgz, helper)
            if rc != 0:
                raise RuntimeError(f"restore of volume {v} failed (rc={rc})")
            vols_done.append(v)
        out.line("[dim]starting the stack...[/]")
        r = subprocess.run(_compose_cmd(ctx, "up", "-d"), capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"compose up failed: {(r.stderr or '')[-300:]}")
        port = ctx.frame_registry_port
        code, waited = 0, 0
        if port:
            deadline = time.monotonic() + 420
            while time.monotonic() < deadline:
                code = _http_code(f"http://127.0.0.1:{port}/health")
                if code == 200:
                    break
                time.sleep(5); waited += 5
        return {"kind": "frame", "frame": ctx.name, "archive_path": str(archive), "pre_restore_snapshot": str(pre) if pre else None,
                "restored_databases": restored, "restored_volumes": vols_done, "registry_health": code, "waited_s": waited,
                "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def _do_restore(
    ctx: OperatorContext,
    out: Output,
    archive: Path,
    *,
    snapshot_first: bool = True,
    force_cross_operator: bool = False,
) -> Dict[str, Any]:
    if not archive.exists():
        raise RuntimeError(f"archive not found: {archive}")

    with tempfile.TemporaryDirectory(prefix="tp-op-restore-") as td:
        td_p = Path(td)

        out.line(f"[dim]Extracting archive...[/]")
        with tarfile.open(archive, "r:gz") as tar:
            # Python 3.12+ requires filter=; older just allows it
            try:
                tar.extractall(td_p, filter="data")
            except TypeError:
                tar.extractall(td_p)

        out.line(f"[dim]Verifying manifest checksums...[/]")
        manifest = _verify_manifest(td_p)

        # operator_did binding (refuse cross-operator restore by default)
        archive_did = manifest.get("operator_did")
        current_did = ctx.env.get("OPERATOR_DID")
        if archive_did and current_did and archive_did != current_did and not force_cross_operator:
            raise RuntimeError(
                f"archive operator_did={archive_did} != destination={current_did}; "
                f"pass --force-cross-operator to override"
            )

        # 1. Snapshot first
        if snapshot_first:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            pre = ctx.dir / f"pre-restore-{ts}.tar.gz"
            out.line(f"[dim]Pre-restore snapshot → {pre}[/]")
            from .backup import _do_backup
            _do_backup(ctx, out, pre)
        else:
            pre = None

        # 2. Stop stack
        out.line(f"[dim]docker compose down...[/]")
        compose_down(ctx)

        # 3. Restore .env.operator + configs (BEFORE bringing anything up)
        for f in (".env.operator", "pgbouncer.ini", "userlist.txt", "docker-compose.operator.yml",
                  "docker-compose.standalone.yml", "VERSION"):
            src = td_p / f
            if src.exists():
                (ctx.dir / f).write_bytes(src.read_bytes())
                if f in (".env.operator", "pgbouncer.ini", "userlist.txt"):
                    # they carry database passwords: 0600, whatever mode a fresh file was created with
                    (ctx.dir / f).chmod(0o600)
                if f in ("pgbouncer.ini", "userlist.txt") and os.geteuid() == 0:
                    # the compose runs pgbouncer as uid 1000, which must still be able to read them
                    os.chown(ctx.dir / f, 1000, 1000)
        for sub in ("spire", "nginx"):
            src = td_p / sub
            if src.exists():
                dst = ctx.dir / sub
                dst.mkdir(parents=True, exist_ok=True)
                for child in src.rglob("*"):
                    if child.is_file():
                        rel = child.relative_to(src)
                        target = dst / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(child.read_bytes())

        # 4. Bring DBs up
        out.line(f"[dim]Bringing DBs up...[/]")
        subprocess.run(_compose_cmd(ctx, "up", "-d", "db", "teg-db"), timeout=60)
        if not _wait_for_db(ctx, "db", timeout_s=60):
            raise RuntimeError("registry db never came healthy")
        if not _wait_for_db(ctx, "teg-db", timeout_s=60):
            raise RuntimeError("teg-db never came healthy")

        # 5. Restore SQL dumps via docker compose exec
        reg_dump = td_p / "registry.dump"
        teg_dump = td_p / "teg.dump"
        if reg_dump.exists():
            out.line(f"[dim]pg_restore registry...[/]")
            with reg_dump.open("rb") as f:
                cmd = _compose_cmd(ctx, "exec", "-T", "db", "pg_restore",
                                   "-U", "registry", "-d", "agentvault_registry",
                                   "--clean", "--if-exists", "--no-owner")
                r = subprocess.run(cmd, stdin=f, capture_output=True, timeout=600)
            if r.returncode != 0:
                # pg_restore exits non-zero on minor issues (extension warnings); only abort on stderr.match("ERROR")
                if b"ERROR" in r.stderr and b"WARNING" not in r.stderr:
                    raise RuntimeError(f"pg_restore registry failed: {r.stderr.decode()[:300]}")
                out.warn(f"pg_restore registry had warnings (continuing): {r.stderr.decode()[:200]}")

        if teg_dump.exists():
            out.line(f"[dim]pg_restore teg...[/]")
            with teg_dump.open("rb") as f:
                cmd = _compose_cmd(ctx, "exec", "-T", "teg-db", "pg_restore",
                                   "-U", "teg", "-d", "teg_layer",
                                   "--clean", "--if-exists", "--no-owner")
                r = subprocess.run(cmd, stdin=f, capture_output=True, timeout=600)
            if r.returncode != 0 and b"ERROR" in r.stderr and b"WARNING" not in r.stderr:
                raise RuntimeError(f"pg_restore teg failed: {r.stderr.decode()[:300]}")

        # 6. Bring rest up
        out.line(f"[dim]Bringing rest of stack up...[/]")
        compose_up(ctx)

        return {
            "archive_path": str(archive),
            "pre_restore_snapshot": str(pre) if pre else None,
            "archive_operator_did": archive_did,
            "manifest_entries": len(manifest.get("entries", [])),
            "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="restore", help="Atomic restore from a backup archive.")
    def restore_cmd(
        archive: Path = typer.Argument(..., help="Path to backup archive (.tar.gz)"),
        rebuild_volumes: bool = typer.Option(False, "--rebuild-volumes"),
        skip_env_restore: bool = typer.Option(False, "--skip-env-restore"),
        force_cross_operator: bool = typer.Option(False, "--force-cross-operator"),
        force_cross_frame: bool = typer.Option(False, "--force-cross-frame", help="Frames: accept an archive of another trust domain"),
        i_mean_production: bool = typer.Option(False, "--i-mean-production", help="Frames: allow a restore over a frame whose env_label is prod"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)

        contexts = load_contexts()
        if len(contexts) != 1:
            out.error("`restore` operates on a single operator.")
            raise typer.Exit(code=1)
        ctx = contexts[0]

        if not state.yes:
            out.warn(f"This will STOP {ctx.name} and replace {'its three databases and two volumes' if ctx.is_frame else 'DBs + configs'} from {archive}.")
            out.warn(f"A pre-restore snapshot will be taken first.")
            answer = typer.prompt("Type CONFIRM-RESTORE to proceed", default="", show_default=False)
            if answer.strip() != "CONFIRM-RESTORE":
                out.warn("Aborted.")
                raise typer.Exit(code=2)

        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would restore {ctx.name} from {archive}")
            raise typer.Exit(code=0)

        try:
            with acquire_lock(ctx.name):
                def _do():
                    try:
                        if ctx.is_frame:
                            result = _do_frame_restore(ctx, out, archive, force_cross_frame=force_cross_frame, allow_production=i_mean_production)
                        else:
                            result = _do_restore(ctx, out, archive, force_cross_operator=force_cross_operator)
                    except RuntimeError as e:
                        out.error(str(e))
                        return 2
                    if out.mode == "json":
                        out.emit_json(result)
                    else:
                        out.success(f"Restore complete. Pre-restore snapshot: {result['pre_restore_snapshot']}")
                    return 0

                rc = run_with_audit("restore", ctx.name, _do)
                raise typer.Exit(code=rc)
        except LockAcquireError as e:
            out.error(str(e))
            raise typer.Exit(code=1)
