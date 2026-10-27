"""tp-operator update: check, schedule, apply or roll back a new release.

--check-only (the default) reads the SIGNED release channel (§RELEASECHANNEL, 2026-09-21): one JSON document at
RELEASE_CHANNEL_URL (default https://theprotocol.cloud/downloads/frame-kit/latest.json), verified against the public
key this CLI carries (tp_operator/release_channel.py) before a byte of it is trusted. An unsigned, altered or missing
document reads "channel unreachable" and nothing else happens. The local VERSION line is compared like with like: a
kit version (1.0.0-beta.11, the public lineage) against the release versions, a software version string (...V0416,
the author's own lineage) against each release's registry_software_version.

--schedule <ISO 8601> records the window YOU chose on this host: a transient systemd timer that runs
`tp-operator --yes update --apply --to-version <v>` at that time (--cancel-schedule removes it). The registry's own
admin page schedules the same window on the registry side and reminds you; only this command moves anything.

--apply runs the full flow:
  1. Pre-snapshot via tp-operator backup (per §6.6 "snapshot-before-anything")
  2. The release's images onto this host: a release the verified channel lists is pulled BY DIGEST from the prefix it
     names and tagged <prefix>/<name>:<tag> (as frame-update.py does); without a verified channel, --to-version is a
     tag you vouch for (a local build is used as it is, anything else is pulled by that tag)
  3. .env.operator names them: the compose's tag variable (VERSION), its image prefix for a channel release, and
     IMAGE_TAG kept equal to the tag where the env has one (the version the registry reports)
  4. docker compose up -d --remove-orphans, then wait for healthchecks; VERSION records the target only then
  5. If healthcheck fails: auto-rollback, previous backup (the env included) restored + up -d
"""
from __future__ import annotations

import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
import typer

from .. import release_channel as rcm

from .. import __schema_version__
from ..config import OperatorContext
from ..http_client import event_hooks, timeout_or
from ..docker_runner import (
    _compose_cmd,
    compose_pull,
    compose_ps_json,
    compose_up,
    docker_info_ok,
    run,
)
from ..output import Output, detect_output_mode
from ..pidlock import LockAcquireError, acquire_lock

BUNDLE_INDEX_URL = os.getenv("RELEASE_CHANNEL_URL", rcm.DEFAULT_URL)


def _read_local_version(ctx_dir: Path) -> Optional[str]:
    """The VERSION file the last apply wrote, else the VERSION= line of the operator's env."""
    v = ctx_dir / "VERSION"
    if v.exists():
        return v.read_text().strip()
    for name in (".env.operator", ".env.frame-test"):
        env = ctx_dir / name
        if env.exists():
            for line in env.read_text(errors="replace").splitlines():
                if line.startswith("VERSION="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# CB-295 / CB-338: the apply has to MOVE the stack to the release it names. It used to pull and recreate whatever
# ${VERSION} .env.operator already named, then write the target into the VERSION file, so nothing moved unless the
# operator had edited the env first, while every later check read the target as the running version.
_IMAGE_LINE = re.compile(
    r"^\s*image:\s*\$\{(?P<pvar>[A-Z_][A-Z0-9_]*)(?::-(?P<pdef>[^}]*))?\}/(?P<name>[a-z0-9][a-z0-9._-]*)"
    r":\$\{(?P<tvar>[A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}\s*$", re.M)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def release_image_vars(compose_text: str) -> Optional[dict]:
    """How a compose names the images a release replaces, from its `image: ${PREFIX:-default}/<name>:${TAG:-default}`
    lines: the operator bundle's IMAGES_PREFIX and VERSION, the standalone kit's IMAGE_REGISTRY and VERSION. None when
    it names them another way (a frame's FT_*_IMAGE lines: frame-update.py applies a release to a frame)."""
    found = list(_IMAGE_LINE.finditer(compose_text))
    if not found or len({m.group("pvar") for m in found}) != 1 or len({m.group("tvar") for m in found}) != 1:
        return None
    return {"prefix_var": found[0].group("pvar"), "prefix_default": found[0].group("pdef") or "",
            "tag_var": found[0].group("tvar"), "names": sorted({m.group("name") for m in found})}


def upsert_env(path: Path, pairs: dict) -> None:
    """Set each KEY=value in an env file: every line naming the key is rewritten (compose reads the last one), a key
    the file lacks is appended. Written beside the file and renamed over it, with the file's own mode."""
    text = path.read_text()
    for key, value in pairs.items():
        line = f"{key}={value}"
        if re.search(rf"(?m)^{re.escape(key)}=.*$", text):
            text = re.sub(rf"(?m)^{re.escape(key)}=.*$", lambda _m: line, text)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    mode = path.stat().st_mode & 0o777
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _release_images(ctx: OperatorContext, image_vars: dict, rel: Optional[dict], target: str, out) -> Optional[dict]:
    """The target's images onto this host; returns the env lines that name them, or None once it has said why."""
    names, tag_var, prefix_var = image_vars["names"], image_vars["tag_var"], image_vars["prefix_var"]
    if rel is not None:
        images = rel.get("images") or {}
        prefix, tag, digests = images.get("prefix"), images.get("tag") or target, images.get("digests") or {}
        missing = [n for n in names if not _DIGEST.fullmatch(str(digests.get(n) or ""))]
        if not prefix or missing:
            out.error(f"the channel's entry for {target} names "
                      + ("no image prefix" if not prefix else f"no digest for {', '.join(missing)}"))
            return None
        for name in names:
            src = f"{prefix}/{name}@{digests[name]}"
            out.line(f"[dim]docker pull {src}...[/]")
            p = run(["docker", "pull", src], timeout=1800)
            if p.returncode != 0 or run(["docker", "tag", src, f"{prefix}/{name}:{tag}"]).returncode != 0:
                out.error(f"pull of {src} failed: {((p.stderr or p.stdout) or '').strip()[-300:]}")
                return None
        return {prefix_var: prefix, tag_var: tag}
    prefix = ctx.env.get(prefix_var) or image_vars["prefix_default"]
    if not all(run(["docker", "image", "inspect", f"{prefix}/{n}:{target}"]).returncode == 0 for n in names):
        out.line(f"[dim]docker compose pull ({tag_var}={target})...[/]")
        rc, output_str = compose_pull(ctx, env={tag_var: target})
        if rc != 0:
            out.error(f"Pull failed: {output_str[:200]}")
            return None
    return {tag_var: target}


def _fetch_channel() -> tuple[Optional[dict], str]:
    """(verified document, reason). A document is returned ONLY when its signature verifies; every other outcome is
    (None, why): not published, unreachable, too large, not JSON, unsigned or altered."""
    try:
        with httpx.Client(timeout=timeout_or(15.0), follow_redirects=False, event_hooks=event_hooks(),
                          headers={"User-Agent": "tp-operator-release-channel/1"}) as c:
            r = c.get(BUNDLE_INDEX_URL)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} (not published yet, or the URL moved)"
        if len(r.content) > rcm.MAX_BYTES:
            return None, "document larger than 1 MB"
        doc = r.json()
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"
    ok, reason = rcm.verify(doc, os.getenv("RELEASE_CHANNEL_PUBKEY_B64") or None)
    if not ok:
        return None, f"NOT VERIFIED: {reason}"
    return doc, "ok"


def _fetch_latest() -> Optional[dict]:
    """Kept for callers of the old name: the newest verified release as a flat dict, or None."""
    doc, _ = _fetch_channel()
    if not doc:
        return None
    rel = (doc.get("releases") or [None])[0]
    return {"version": rel.get("version"), **rel} if isinstance(rel, dict) else None


_TIMER_UNIT = "tp-update-{name}"


def _schedule_timer(ctx_name: str, when: datetime.datetime, version: str, out) -> int:
    """A transient systemd timer on this host for the window the operator chose; refuses without systemd-run."""
    if not shutil.which("systemd-run"):
        out.error("systemd-run is not available on this host; run `tp-operator --yes update --apply --to-version "
                  f"{version}` yourself at {when.isoformat()}.")
        return 5
    unit = _TIMER_UNIT.format(name=ctx_name)
    exe = os.path.abspath(sys.argv[0])
    cmd = ["systemd-run", f"--unit={unit}", f"--on-calendar={when.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
           "--timer-property=AccuracySec=1min", f"--description=TheProtocol rollout of {ctx_name} to {version}",
           exe, "--yes", "update", "--apply", "--to-version", version]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        out.error(f"systemd-run refused: {(r.stderr or r.stdout).strip()[:300]}")
        return 5
    out.success(f"Scheduled: {unit}.timer runs `{' '.join(cmd[-5:])}` at {when.isoformat()} (cancel with --cancel-schedule).")
    return 0


def _cancel_timer(ctx_name: str, out) -> int:
    unit = _TIMER_UNIT.format(name=ctx_name)
    r = subprocess.run(["systemctl", "stop", f"{unit}.timer"], capture_output=True, text=True)
    if r.returncode != 0:
        out.warn(f"no scheduled rollout for {ctx_name} ({(r.stderr or '').strip()[:120]})")
        return 1
    out.success(f"Cancelled {unit}.timer.")
    return 0


def _wait_healthy(ctx: OperatorContext, *, timeout_s: int = 120) -> bool:
    """Poll docker compose ps until all 9 services are healthy or healthcheck-less + running."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        services = compose_ps_json(ctx)
        if services:
            all_ok = all(
                (s.get("State") or "").lower() == "running"
                and (s.get("Health") or "").lower() in ("healthy", "", "none")
                for s in services
            )
            if all_ok:
                return True
        time.sleep(3)
    return False


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="update", help="Check for / apply a new operator bundle.")
    def update_cmd(
        check_only: bool = typer.Option(True, "--check-only/--apply", help="Default is --check-only."),
        to_version: Optional[str] = typer.Option(None, "--to-version"),
        allow_major: bool = typer.Option(False, "--allow-major"),
        schedule: Optional[str] = typer.Option(None, "--schedule", help="ISO 8601 date-time: a transient systemd timer "
                                               "runs the apply on this host then (the window you chose)."),
        cancel_schedule: bool = typer.Option(False, "--cancel-schedule", help="Remove the scheduled rollout timer."),
        auto_rollback: bool = typer.Option(True, "--auto-rollback/--no-auto-rollback",
                                            help="Auto-rollback if post-apply healthcheck fails (default ON)."),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))

        if not check_only and not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)

        contexts = load_contexts()
        results = []

        doc, channel_reason = _fetch_channel()

        for ctx in contexts:
            local = _read_local_version(ctx.dir)
            verdict = rcm.assess(doc, rcm.running_from_version_string(local)) if doc else None
            latest = (verdict["latest"] or {}).get("version") if verdict and verdict.get("latest") else None
            update_available = bool(verdict and verdict["update_available"])

            row = {
                "schema_version": __schema_version__,
                "operator": ctx.name,
                "current_version": local,
                "latest_version": latest,
                "update_available": update_available,
                "kind": verdict.get("kind") if verdict else None,
                "comparable": verdict.get("comparable") if verdict else None,
                "channel": BUNDLE_INDEX_URL,
                "channel_status": channel_reason,
                "newer": [r.get("version") for r in verdict["newer"]] if verdict else [],
                "applied": False,
                "rolled_back": False,
            }

            if cancel_schedule:
                row["cancelled"] = _cancel_timer(ctx.name, out) == 0
                results.append(row)
                continue

            if schedule:
                target = to_version or latest
                if not target:
                    out.error("nothing to schedule: the channel lists no release (or could not be verified); "
                              f"channel: {channel_reason}")
                    raise typer.Exit(code=1)
                if doc and not rcm.find_release(doc, target):
                    out.error(f"{target} is not a release the verified channel lists")
                    raise typer.Exit(code=1)
                try:
                    when = datetime.datetime.fromisoformat(schedule.replace("Z", "+00:00"))
                except ValueError:
                    out.error("--schedule takes an ISO 8601 date-time, e.g. 2026-09-23T02:00:00+02:00")
                    raise typer.Exit(code=1)
                if when.tzinfo is None:
                    when = when.astimezone()
                if when <= datetime.datetime.now(datetime.timezone.utc):
                    out.error("--schedule must be in the future")
                    raise typer.Exit(code=1)
                rc_sched = _schedule_timer(ctx.name, when, target, out)
                row["scheduled"] = rc_sched == 0
                row["scheduled_at"] = when.isoformat()
                row["scheduled_version"] = target
                results.append(row)
                if rc_sched != 0:
                    raise typer.Exit(code=rc_sched)
                continue

            if check_only:
                results.append(row)
                continue

            if doc is None and not to_version:
                out.error(f"the release channel could not be verified ({channel_reason}); pass --to-version to apply "
                          "a version you verified yourself")
                raise typer.Exit(code=1)

            # ── APPLY PATH ─────────────────────────────────
            if not update_available and not to_version:
                row["note"] = "no update available — pass --to-version to force"
                results.append(row)
                continue

            target = to_version or latest
            rel = rcm.find_release(doc, target) if doc else None
            if doc is not None and rel is None:
                out.error(f"{target} is not a release the verified channel lists")
                raise typer.Exit(code=1)
            image_vars = release_image_vars(ctx.compose_file.read_text()) if ctx.compose_file.exists() else None
            if image_vars is None:
                out.error(f"{ctx.compose_file.name} does not name its images as ${{PREFIX}}/<name>:${{TAG}}, so this "
                          f"command cannot point it at {target} (a frame takes a release with frame-update.py)")
                raise typer.Exit(code=2)
            if local and target:
                local_major = local.split(".")[0]
                target_major = target.split(".")[0]
                if local_major != target_major and not allow_major:
                    out.error(f"Refusing major-version cross {local} → {target}; pass --allow-major.")
                    raise typer.Exit(code=1)

            if not state.yes:
                out.warn(f"Will pre-snapshot, then pull {target}'s images, name them in {ctx.env_path.name} and "
                         f"up -d on {ctx.name}.")
                answer = typer.prompt("Type CONFIRM-UPDATE to proceed", default="", show_default=False)
                if answer.strip() != "CONFIRM-UPDATE":
                    out.warn("Aborted.")
                    raise typer.Exit(code=2)

            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would update {ctx.name} {local or '?'} → {target}")
                results.append(row)
                continue

            try:
                with acquire_lock(ctx.name):
                    def _do(c=ctx, target=target, r=row, rel=rel, image_vars=image_vars):
                        # 1. Pre-snapshot
                        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                        snapshot = c.dir / f"pre-update-{ts}.tar.gz"
                        out.line(f"[dim]Pre-snapshot to {snapshot}...[/]")
                        from .backup import _do_backup
                        try:
                            _do_backup(c, out, snapshot)
                        except Exception as e:
                            out.error(f"Pre-snapshot failed: {e}. Refusing to update.")
                            return 2
                        r["pre_snapshot"] = str(snapshot)

                        # 2. The release's images, then the env that names them (an env is only written once its
                        #    images are on this host; the snapshot above holds the previous one for the rollback)
                        pairs = _release_images(c, image_vars, rel, target, out)
                        if pairs is None:
                            return 6
                        if "IMAGE_TAG" in c.env:
                            pairs["IMAGE_TAG"] = pairs[image_vars["tag_var"]]
                        upsert_env(c.env_path, pairs)
                        r["env_set"] = dict(pairs)

                        # 3. Apply (force-recreate)
                        out.line(f"[dim]docker compose up -d --remove-orphans...[/]")
                        rc, output_str = subprocess.run(
                            _compose_cmd(c, "up", "-d", "--remove-orphans"),
                            capture_output=True, text=True, timeout=300,
                        ).returncode, ""

                        # 4. Wait for healthy
                        out.line(f"[dim]Waiting for healthchecks...[/]")
                        if _wait_healthy(c, timeout_s=120):
                            r["applied"] = True
                            # 5. Write VERSION
                            try:
                                (c.dir / "VERSION").write_text(target + "\n")
                            except OSError:
                                pass
                            out.success(f"Updated {c.name} to {target}.")
                            return 0
                        # 6. Auto-rollback
                        if auto_rollback:
                            out.warn("Post-update healthcheck FAILED. Rolling back...")
                            from .restore import _do_restore
                            try:
                                _do_restore(c, out, snapshot, snapshot_first=False)
                                r["rolled_back"] = True
                                out.warn(f"Rolled back to pre-update state. Investigate; pre-snapshot kept at {snapshot}.")
                                return 1
                            except Exception as e:
                                out.error(f"Rollback failed: {e}. Manual recovery needed; snapshot at {snapshot}.")
                                return 2
                        return 1

                    rc = run_with_audit("update", ctx.name, _do)
                    if rc != 0:
                        out.error(f"Update returned non-zero exit: {rc}")
                        results.append(row)
                        raise typer.Exit(code=rc)
            except LockAcquireError as e:
                out.error(str(e))
                raise typer.Exit(code=1)

            results.append(row)

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                if r.get("latest_version") is None:
                    badge = "[dim]CHANNEL UNAVAILABLE[/]"
                elif r.get("comparable") is False:
                    badge = "[yellow]CANNOT COMPARE[/]"
                elif r["update_available"]:
                    badge = f"[yellow]UPDATE AVAILABLE ({r.get('kind') or 'stable'})[/]"
                else:
                    badge = "[green]UP-TO-DATE[/]"
                out.line(f"\n[bold]{r['operator']}[/]: {badge}")
                out.line(f"  current: {r['current_version'] or '(unknown)'}")
                out.line(f"  latest:  {r['latest_version'] or '(channel unreachable)'}")
                out.line(f"  channel: {r['channel']} ({r.get('channel_status')})")
                if r.get("newer"):
                    out.line(f"  newer:   {', '.join(r['newer'])}")
                if r.get("scheduled"):
                    out.line(f"  scheduled: {r['scheduled_version']} at {r['scheduled_at']}")
                if r.get("applied"):
                    out.line(f"  applied: yes")
                if r.get("rolled_back"):
                    out.line(f"  rolled_back: yes")
        raise typer.Exit(code=0)
