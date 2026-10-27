"""tp-operator license — show / rotate / verify."""
from __future__ import annotations

import datetime
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import typer

from .. import __schema_version__
from ..audit import write_audit
from ..config import OperatorContext
from ..http_client import fresh_idempotency_key, timeout_or
from ..output import Output, detect_output_mode
from ..pidlock import LockAcquireError, acquire_lock


def _show_local(ctx: OperatorContext) -> Dict[str, Any]:
    key = ctx.federation_license
    return {
        "schema_version": __schema_version__,
        "operator": ctx.name,
        "operator_did": ctx.env.get("OPERATOR_DID", "(unset)"),
        "federation_operator_did": ctx.env.get("FEDERATION_OPERATOR_DID", "(unset)"),
        "license_present": bool(key),
        "license_key_prefix": (key[:12] + "...") if key else None,
        "mainframe_url": ctx.mainframe_url,
        "is_standalone": ctx.is_standalone,
    }


# CB-228 (2026-10-16): `license verify` asked GET /api/v1/federation/info, a public route that checks no credential, and
# called any 2xx verified, so a revoked, suspended or wrong key read as verified. It now asks a route of the parent that
# checks the licence before it answers anything: the operator's own self-logs (one line of tail is the least it serves),
# on the parent's federation lane with the operator's certificate, the way the operator's registry makes that call
# (parent_call). The parent checks the licence first: 403 when it is revoked, suspended or unknown, 404 when no operator
# of this parent holds it, and only then reads the logs.
LICENCE_PROBE = ("GET", "/api/v1/admin/cloud-operators/self-logs", "/api/v1/federation/operator-self/logs",
                 {"service": "registry", "tail": 10})


def licence_verdict(answer: Dict[str, Any]) -> Dict[str, Any]:
    """The parent's answer to the probe, as `license verify` reports it. Verified only when the parent checked the
    licence and found it active; any refusal, and any answer that is not the parent's, is unverified with its reason."""
    from ..parent_call import answer_detail

    if answer.get("error"):
        return {"verified": False, "status_code": 0, "lane": None,
                "reason": f"{answer['error']}: {answer.get('detail') or ''}".strip()[:300]}
    status = int(answer.get("status") or 0)
    lane = answer.get("lane")
    detail = answer_detail(answer)
    out = {"status_code": status, "lane": lane}
    if status == 200:
        return {**out, "verified": True, "reason": "the parent checked the licence: active"}
    if status >= 500 and detail.startswith("Logs fetch failed"):
        # The handler reads the logs only after the licence and its operator passed: the licence is active.
        return {**out, "verified": True, "reason": "the parent checked the licence: active (its probe read failed)"}
    if status == 403:
        why = "the parent refused the licence"
    elif status == 401:
        why = ("the parent did not receive the licence (its console clears it; the federation lane was not "
               "reachable from this registry)")
    elif status == 404:
        why = "no operator of the parent holds this licence"
    else:
        why = f"the parent answered {status}"
    return {**out, "verified": False, "reason": f"{why}: {detail}".rstrip(": ")[:300]}


def _verify_remote(ctx: OperatorContext) -> Dict[str, Any]:
    if not ctx.federation_license:
        return {"verified": False, "status_code": 0, "lane": None, "reason": "no_local_license"}
    from ..parent_call import call_parent

    method, console_path, lane_path, params = LICENCE_PROBE
    # SEC-17: the global --timeout, else the probe's own 20 s
    return licence_verdict(call_parent(ctx, method, console_path, lane_path, params=params, timeout=timeout_or(20.0)))


# SEC-08 (2026-10-17): `license rotate` POSTed the licence to the parent URL from the host. A frame's public console clears
# X-Federation-License (every template frame, EU and ASIA among them), so the parent answered "X-Federation-License
# header required" and nothing rotated. It now asks the way `license verify` does (parent_call): through the operator's
# registry, on the parent's federation lane, which forwards /api/v1/federation/ with the licence and the idempotency key
# the route requires; the console path stays the fallback when the lane is unknown.
ROTATE = "/api/v1/federation/license/rotate-self"
# an error that leaves the outcome unknown (the call may have reached the parent): the rest never sent the rotation
_ROTATE_OUTCOME_UNKNOWN = ("call_failed", "no_answer", "exec_failed")


def _atomic_replace_license_in_env(env_path: Path, new_key: str) -> Path:
    """Atomically rewrite .env.operator's FEDERATION_LICENSE_KEY line.

    Backs up to .env.operator.bak-pre-rotate-<ts>. The line replaced is the
    LAST occurrence (matches Docker Compose's last-wins behavior).
    """
    if not env_path.exists():
        raise FileNotFoundError(env_path)
    backup = env_path.with_name(
        f".env.operator.bak-pre-rotate-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    shutil.copy2(env_path, backup)

    content = env_path.read_text()
    lines = content.splitlines()

    # Find the LAST FEDERATION_LICENSE_KEY=... line; replace it.
    last_idx = -1
    pattern = re.compile(r"^\s*FEDERATION_LICENSE_KEY\s*=", re.IGNORECASE)
    for i, line in enumerate(lines):
        if pattern.match(line):
            last_idx = i
    if last_idx >= 0:
        lines[last_idx] = f"FEDERATION_LICENSE_KEY={new_key}"
    else:
        lines.append(f"FEDERATION_LICENSE_KEY={new_key}")

    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    tmp = env_path.with_suffix(".operator.tmp")
    tmp.write_text(new_content)
    try:
        os.fsync(tmp.open("rb").fileno())
    except OSError:
        pass
    tmp.replace(env_path)
    return backup


def register(app, state, load_contexts, run_with_audit):
    sub = typer.Typer(help="Manage the federation license for this operator.")
    app.add_typer(sub, name="license")

    @sub.command(name="show", help="Print local license summary.")
    def show():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = [run_with_audit("license show", ctx.name, _show_local, ctx) for ctx in contexts]
        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                out.line(f"\nOperator: [bold]{r['operator']}[/]")
                out.line(f"  operator_did: {r['operator_did']}")
                out.line(f"  federation_operator_did: {r['federation_operator_did']}")
                out.line(f"  license_present: {r['license_present']}")
                if r["license_key_prefix"]:
                    out.line(f"  license_key_prefix: {r['license_key_prefix']}")
                out.line(f"  mainframe_url: {r['mainframe_url']}")
                out.line(f"  is_standalone: {r['is_standalone']}")
        raise typer.Exit(code=0)

    @sub.command(name="verify", help="Ask the parent frame to check this licence (through this operator's registry, "
                                      "on the parent's federation lane); exit 2 unless the parent found it active.")
    def verify():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = [run_with_audit("license verify", ctx.name, _verify_remote, ctx) for ctx in contexts]
        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r, ctx in zip(results, contexts):
                badge = "[green]VERIFIED[/]" if r["verified"] else "[red]UNVERIFIED[/]"
                via = f" via the {r['lane']}" if r.get("lane") else ""
                out.line(f"\n[bold]{ctx.name}[/]: {badge}{via}  ({r.get('reason', '')[:200]})")
        any_failed = any(not r["verified"] for r in results)
        raise typer.Exit(code=2 if any_failed else 0)

    @sub.command(name="rotate", help="Ask the parent frame for a new licence key (through this operator's registry, on "
                                      "the parent's federation lane) and write it into .env.operator; exit 3 when the "
                                      "parent refuses.")
    def rotate(
        reason: str = typer.Option("scheduled_rotation", "--reason",
                                   help="One of: leak_suspected, scheduled_rotation, post_incident"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        if len(contexts) != 1:
            out.error("`license rotate` operates on a single operator. Use --operator NAME.")
            raise typer.Exit(code=1)
        ctx = contexts[0]
        if ctx.is_frame:
            out.error("`license rotate` is an operator's command: a frame has no parent frame to ask.")
            raise typer.Exit(code=1)
        if not ctx.federation_license:
            out.error("No FEDERATION_LICENSE_KEY found in .env.operator.")
            raise typer.Exit(code=4)

        if not state.yes and not state.dry_run:
            out.warn(f"This will REVOKE the current key on {ctx.name}'s license and ISSUE a new one.")
            out.warn(f"The new key will be written to {ctx.env_path}.")
            answer = typer.prompt("Type CONFIRM-ROTATE to proceed", default="", show_default=False)
            if answer.strip() != "CONFIRM-ROTATE":
                out.warn("Aborted.")
                raise typer.Exit(code=2)

        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would ask {ctx.name}'s parent frame for a new key ({ROTATE}, through this "
                     f"operator's registry, on the parent's federation lane)")
            raise typer.Exit(code=0)

        idem_key = fresh_idempotency_key("rotate")

        def _do():
            from ..parent_call import answer_detail, call_parent

            try:
                with acquire_lock(ctx.name):
                    answer = call_parent(ctx, "POST", ROTATE, ROTATE, json_body={"reason": reason},
                                         headers={"X-Idempotency-Key": idem_key}, timeout=timeout_or(15.0))
                    if answer.get("error"):
                        out.error(f"No answer from the parent: {answer['error']}: {answer.get('detail') or ''}"[:400])
                        if answer["error"] in _ROTATE_OUTCOME_UNKNOWN:
                            out.warn("If the parent rotated the key before its answer was lost, the key in .env.operator "
                                     "no longer verifies: run `license verify` before trying again.")
                        return 3
                    status = int(answer.get("status") or 0)
                    if status != 200:
                        out.error(f"The parent refused the rotation: HTTP {status}: {answer_detail(answer)}")
                        return 3
                    data = answer.get("body") if isinstance(answer.get("body"), dict) else {}
                    new_key = data.get("license_key", "")
                    if not new_key:
                        out.error("The parent's answer carries no license_key.")
                        return 2
                    try:
                        backup = _atomic_replace_license_in_env(ctx.env_path, new_key)
                    except Exception as e:
                        out.error(f"Local write failed: {e}")
                        out.warn("PASTE THIS KEY MANUALLY into .env.operator (will NOT appear in logs):")
                        out.warn(new_key)
                        return 2
                    if out.mode == "json":
                        out.emit_json({
                            "rotation_id": data.get("rotation_id"),
                            "operator_did": data.get("operator_did"),
                            "license_key_prefix": new_key[:12] + "...",
                            "rotated_at": data.get("rotated_at"),
                            "idempotent_replay": data.get("idempotent_replay", False),
                            "env_backup": str(backup),
                            "lane": answer.get("lane"),
                        })
                    else:
                        out.success(f"Rotated. New key prefix: {new_key[:12]}...")
                        out.line(f"  rotation_id: {data.get('rotation_id')}")
                        out.line(f"  rotated_at:  {data.get('rotated_at')}")
                        out.line(f"  env backup:  {backup}")
                        out.line(f"  asked via:   the {answer.get('lane')}")
                    return 0
            except LockAcquireError as e:
                out.error(str(e))
                return 1

        rc = run_with_audit("license rotate", ctx.name, _do)
        raise typer.Exit(code=rc)
