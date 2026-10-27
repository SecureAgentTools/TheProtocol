"""tp-operator backup — pg_dump + tar configs + manifest.

Atomic single-archive backup: every dump must succeed, and the archive (mode 0600) appears under its name only when
it is complete. Never includes prod/sandbox secrets in logs.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import typer

from ..config import OperatorContext
from ..docker_runner import _compose_cmd, docker_info_ok
from ..output import Output, detect_output_mode
from ..pidlock import LockAcquireError, acquire_lock


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pg_dump(ctx: OperatorContext, service: str, user: str, db: str, out_path: Path) -> int:
    cmd = _compose_cmd(ctx, "exec", "-T", service, "pg_dump", "-U", user, "-Fc", db)
    with out_path.open("wb") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, timeout=600)
    return r.returncode


FRAME_SKIP_SUFFIXES = (".tmp",)
FRAME_SKIP_PARTS = (".bak-",)


def _copy_tree(src: Path, dst: Path, *, skip=lambda p: False) -> int:
    n = 0
    for child in sorted(src.rglob("*")):
        rel = child.relative_to(src)
        if any(skip(part) for part in rel.parts):
            continue
        target = dst / rel
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif child.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(child.read_bytes()); n += 1
    return n


def _volume_tar(volume: str, out_path: Path, helper_image: str) -> int:
    """tar a named volume through a throwaway container (the volume's own consumer may be running: a
    backup is a point-in-time copy of files, which is what these two volumes hold — a key, a CA, entries)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["docker", "run", "--rm", "-v", f"{volume}:/v:ro", "-v", f"{out_path.parent}:/out", "--entrypoint", "sh", helper_image,
           "-c", f"tar czf /out/{out_path.name} -C /v ."]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    return r.returncode


def _psql_scalar(ctx: OperatorContext, service: str, user: str, db: str, sql: str) -> str:
    r = subprocess.run(_compose_cmd(ctx, "exec", "-T", service, "psql", "-U", user, "-d", db, "-tAc", sql),
                       capture_output=True, text=True, timeout=60)
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _do_frame_backup(ctx: OperatorContext, out: Output, archive_path: Path, *, include_volumes: bool = True) -> Dict[str, Any]:
    """§FRAMEKIT P3.2 (2026-09-12) — a FRAME's backup: the stack dir (env, compose, meta, SPIRE confs, x509pop
    certs, nginx confs, operator bundles), THREE database dumps (registry, TEG and the EVENT STORE — the ledger,
    which the operator backup never dumped), the two load-bearing volumes (signer key, SPIRE data), and a
    manifest with a SHA-256 per entry plus each database's migration head. The archive carries secrets: 600."""
    helper = ""
    with tempfile.TemporaryDirectory(prefix="tp-frame-backup-") as td:
        td_p = Path(td)
        n_files = _copy_tree(ctx.dir, td_p / "stack",
                             skip=lambda part: part.endswith(FRAME_SKIP_SUFFIXES) or any(x in part for x in FRAME_SKIP_PARTS))
        out.line(f"[dim]stack dir: {n_files} file(s) copied (baks and temp files skipped)[/]")
        dbs = ctx.frame_db_services()
        if len(dbs) != 3:
            raise RuntimeError(f"the frame env names {len(dbs)} of 3 databases (FT_DB_/FT_TEGDB_/FT_ESDB_ POSTGRES_USER+DB): refusing a partial backup")
        heads: Dict[str, str] = {}
        (td_p / "db").mkdir(exist_ok=True)
        for d in dbs:
            out.line(f"[dim]pg_dump {d['service']} ({d['db']})...[/]")
            rc = _pg_dump(ctx, d["service"], d["user"], d["db"], td_p / "db" / d["dump"])
            if rc != 0:
                raise RuntimeError(f"pg_dump of {d['service']} failed (rc={rc}): a frame backup without its {d['dump']} is not a backup")
            heads[d["dump"]] = _psql_scalar(ctx, d["service"], d["user"], d["db"], "SELECT version_num FROM alembic_version") or "none"
        vols = ctx.frame_volumes() if include_volumes else []
        missing = [k for k in ("spire_data", "registry_data") if not any(f"_{k}_" in v for v in vols)] if include_volumes else []
        if include_volumes and not vols:
            raise RuntimeError("the compose names neither load-bearing volume (spire_data, registry_data): is this a frame the standup driver built?")
        if missing:
            # a frame stood up before rule R7 (§PEERKEYROT) keeps its signer key in the container layer: nothing
            # to back up, and a restore elsewhere rotates it — said here, never silently omitted
            out.warn(f"no named volume for {', '.join(missing)} on this frame (pre-R7 stack): that state lives in a container layer and is NOT in this backup")
        if vols:
            r = subprocess.run(["docker", "inspect", f"{ctx.name}-db", "--format", "{{.Config.Image}}"], capture_output=True, text=True)
            helper = (r.stdout or "").strip() or "alpine:3"
            for v in vols:
                out.line(f"[dim]volume {v}...[/]")
                rc = _volume_tar(v, td_p / "volumes" / f"{v}.tgz", helper)
                if rc != 0:
                    raise RuntimeError(f"tar of volume {v} failed (rc={rc})")
        entries = []
        for entry in sorted(td_p.rglob("*")):
            if entry.is_file():
                entries.append({"path": str(entry.relative_to(td_p)), "size": entry.stat().st_size, "sha256": _sha256_file(entry)})
        manifest = {
            "schema_version": "2.0", "kind": "frame", "frame": ctx.name, "trust_domain": ctx.frame_trust_domain,
            "env_label": ctx.frame_env_label, "stack_dir": str(ctx.dir),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "databases": [{**{k: d[k] for k in ("service", "user", "db", "dump")}, "alembic_head": heads.get(d["dump"], "none")} for d in dbs],
            "volumes": vols, "volumes_missing": missing, "volume_helper_image": helper, "entries": entries,
        }
        (td_p / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = archive_path.with_name(archive_path.name + ".tmp")
        with tarfile.open(tmp, "w:gz") as tar:
            for entry in sorted(td_p.iterdir()):
                tar.add(entry, arcname=entry.name)
        os.chmod(tmp, 0o600); os.replace(tmp, archive_path)
        return {"kind": "frame", "frame": ctx.name, "archive_path": str(archive_path), "size_bytes": archive_path.stat().st_size,
                "sha256": _sha256_file(archive_path), "manifest_entries": len(entries), "databases": manifest["databases"],
                "volumes": vols, "volumes_missing": missing, "mode": "0600"}


def _do_backup(ctx: OperatorContext, out: Output, archive_path: Path, include_volumes: bool = False) -> Dict[str, Any]:
    if ctx.is_frame:
        return _do_frame_backup(ctx, out, archive_path, include_volumes=True if include_volumes is None else (include_volumes or True))
    with tempfile.TemporaryDirectory(prefix="tp-op-backup-") as td:
        td_p = Path(td)

        # 1. .env.operator
        env_dst = td_p / ".env.operator"
        env_dst.write_bytes(ctx.env_path.read_bytes())

        # 2. configs
        for sub in ("spire", "nginx"):
            src = ctx.dir / sub
            if src.exists():
                dst = td_p / sub
                # naive recursive copy
                for child in src.rglob("*"):
                    rel = child.relative_to(src)
                    target = dst / rel
                    if child.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(child.read_bytes())
        for f in ("pgbouncer.ini", "userlist.txt", "docker-compose.operator.yml", "docker-compose.standalone.yml", "VERSION"):
            src = ctx.dir / f
            if src.exists():
                (td_p / f).write_bytes(src.read_bytes())

        # 3. DB dumps, registry + teg-layer. A failed dump fails the backup (CB-293): an archive without one of the two
        # databases restores a stack that has lost its ledger of record, and `update` takes this as its pre-snapshot.
        out.line(f"[dim]Dumping registry DB...[/]")
        reg_dump = td_p / "registry.dump"
        rc = _pg_dump(ctx, "db", "registry", "agentvault_registry", reg_dump)
        if rc != 0:
            raise RuntimeError(f"pg_dump of the registry database failed (rc={rc}): an operator backup without "
                               f"registry.dump is not a backup")
        out.line(f"[dim]Dumping TEG DB...[/]")
        teg_dump = td_p / "teg.dump"
        rc = _pg_dump(ctx, "teg-db", "teg", "teg_layer", teg_dump)
        if rc != 0:
            raise RuntimeError(f"pg_dump of the TEG database failed (rc={rc}): an operator backup without teg.dump "
                               f"is not a backup")

        # 4. manifest
        manifest_entries = []
        for entry in sorted(td_p.rglob("*")):
            if entry.is_file():
                rel = entry.relative_to(td_p)
                manifest_entries.append({
                    "path": str(rel),
                    "size": entry.stat().st_size,
                    "sha256": _sha256_file(entry),
                })
        manifest = {
            "schema_version": "1.0",
            "operator": ctx.name,
            "operator_did": ctx.env.get("OPERATOR_DID"),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "entries": manifest_entries,
        }
        manifest_path = td_p / "MANIFEST.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

        # 5. tar, as the frame backup does: beside the target, 0600 (it carries .env.operator and both dumps), then
        # renamed over it, so a failed or interrupted write never leaves a partial archive under the archive's name
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = archive_path.with_name(archive_path.name + ".tmp")
        try:
            with tarfile.open(tmp, "w:gz") as tar:
                for entry in sorted(td_p.iterdir()):
                    tar.add(entry, arcname=entry.name)
            os.chmod(tmp, 0o600)
            os.replace(tmp, archive_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        return {
            "archive_path": str(archive_path),
            "size_bytes": archive_path.stat().st_size,
            "sha256": _sha256_file(archive_path),
            "manifest_entries": len(manifest_entries),
            "mode": "0600",
        }


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="backup", help="Atomic backup: pg_dump + configs + manifest (a --frame: three dumps incl. the ledger, the signer and SPIRE volumes, 600).")
    def backup_cmd(
        out_path: Path = typer.Option(None, "--out", help="Output archive path"),
        include_volumes: bool = typer.Option(False, "--include-volumes", help="Frames: always on (the signer key and SPIRE data are the frame's identity); operators: reserved"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)
        contexts = load_contexts()
        results = []
        for ctx in contexts:
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            ap = out_path or Path.cwd() / (f"frame-backup-{ctx.name}-{ts}.tar.gz" if ctx.is_frame else f"operator-backup-{ctx.name}-{ts}.tar.gz")
            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would back up {ctx.name} → {ap}")
                continue
            try:
                with acquire_lock(ctx.name):
                    res = run_with_audit("backup", ctx.name, _do_backup, ctx, out, ap, include_volumes)
                    results.append({"operator": ctx.name, **res})
                    out.success(f"Backed up {ctx.name} → {ap} ({res['size_bytes']} bytes)")
            except LockAcquireError as e:
                out.error(str(e))
                raise typer.Exit(code=1)
            except RuntimeError as e:   # a refusal is a sentence, not a traceback
                out.error(str(e))
                raise typer.Exit(code=2)

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        raise typer.Exit(code=0)
