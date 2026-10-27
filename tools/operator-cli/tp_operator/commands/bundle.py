"""tp-operator bundle — §pass51 CLI surface for the Bundles feature.

Subcommands:
  list      — list visible bundles (own + public + official)
  create    — create a snapshot from one or more agent DIDs
  restore   — upload a local .tpb file and restore it
  download  — fetch a bundle's .tpb to disk
  verify    — check a local .tpb offline (layout, manifest, contents against what its signature covers)
  quota     — show current dev's bundle quota + usage

Each subcommand calls the stack's OWN registry (OperatorContext.registry_url: TP_OPERATOR_REGISTRY_URL, else the
port the compose publishes it on, on this host), where its developers and their agents live, with a developer API
key from that registry. --dry-run prints a write (create, restore, download) instead of making it.
API key resolution order:
  1. --api-key flag
  2. TP_BUNDLE_API_KEY env
  3. registry-auth/.api-key file in the operator dir
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path
from typing import Any, List, Optional

import httpx
import typer

from ..config import OperatorContext
from ..http_client import event_hooks, timeout_or
from ..output import Output, detect_output_mode


# ── Auth resolution ────────────────────────────────────────────────────────

def _resolve_api_key(ctx: OperatorContext, flag_key: Optional[str]) -> str:
    if flag_key:
        return flag_key.strip()
    env_key = os.environ.get("TP_BUNDLE_API_KEY", "").strip()
    if env_key:
        return env_key
    # Try operator-local file
    candidate = ctx.dir / "registry-auth" / ".api-key"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8").strip()
    raise typer.BadParameter(
        "No API key found. Use --api-key, TP_BUNDLE_API_KEY env, or "
        "place one in <operator-dir>/registry-auth/.api-key"
    )


def _client(ctx: OperatorContext, api_key: str, timeout: float = 30.0) -> httpx.Client:
    # CB-298: base_url was the PARENT frame (mainframe_url), where an operator's developer key means nothing and none
    # of its agents live. The stack's own registry is plain http on this host by default; an https override
    # (TP_OPERATOR_REGISTRY_URL) is verified like every other call this CLI makes.
    return httpx.Client(
        base_url=ctx.registry_url,
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_or(timeout),
        event_hooks=event_hooks(),
    )


# ── Subcommand implementations ─────────────────────────────────────────────

def _cmd_list(ctx: OperatorContext, api_key: str, kind: Optional[str],
              include_official: bool) -> dict:
    params = {"include_official": str(include_official).lower(), "limit": 100}
    if kind:
        params["kind"] = kind
    with _client(ctx, api_key) as c:
        r = c.get("/api/v1/bundles", params=params)
        r.raise_for_status()
        return r.json()


def _cmd_create(ctx: OperatorContext, api_key: str, *, agent_dids: List[str],
                kind: str, name: Optional[str], description: Optional[str],
                visibility: str, include_cicd: bool, sign: bool) -> dict:
    payload = {
        "agent_dids": agent_dids,
        "kind": kind,
        "visibility": visibility,
        "include_cicd": include_cicd,
        "sign": sign,
    }
    if name:
        payload["name"] = name
    if description:
        payload["description"] = description
    with _client(ctx, api_key) as c:
        r = c.post("/api/v1/bundles", json=payload)
        r.raise_for_status()
        return r.json()


def _cmd_download(ctx: OperatorContext, api_key: str, bundle_id: str,
                  out_path: Path) -> dict:
    with _client(ctx, api_key, timeout=120.0) as c:
        r = c.get(f"/api/v1/bundles/{bundle_id}/download")
        r.raise_for_status()
        out_path.write_bytes(r.content)
    sha256 = hashlib.sha256(out_path.read_bytes()).hexdigest()
    return {
        "bundle_id": bundle_id,
        "saved_to": str(out_path.resolve()),
        "size_bytes": out_path.stat().st_size,
        "sha256": sha256,
    }


def _cmd_restore(ctx: OperatorContext, api_key: str, file_path: Path,
                 conflict_resolution: str, mode: str, include_cicd: bool,
                 idempotency_key: Optional[str]) -> dict:
    files = {"file": (file_path.name, file_path.read_bytes(), "application/x-theprotocol-bundle")}
    data = {
        "conflict_resolution": conflict_resolution,
        "mode": mode,
        "include_cicd": str(include_cicd).lower(),
    }
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    with _client(ctx, api_key, timeout=120.0) as c:
        r = c.post("/api/v1/bundles/restore-from-upload", files=files, data=data, headers=headers)
        r.raise_for_status()
        return r.json()


def _signed_payload_covers(payload_b64: str, manifest: Optional[dict], agent_bytes: List[bytes]) -> bool:
    """Are the bundle's contents the ones its signature covers? The registry signs (attached, in the JWS payload)
    {"manifest": <manifest.json>, "agent_payload_sha256": the sorted sha256 of each agents/*.json as packed}
    (services/bundles/format.py canonical_signing_payload)."""
    try:
        signed = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)).decode())
    except (ValueError, UnicodeDecodeError):
        return False
    if not isinstance(signed, dict) or manifest is None:
        return False
    return (signed.get("manifest") == manifest
            and sorted(signed.get("agent_payload_sha256") or []) == sorted(hashlib.sha256(b).hexdigest()
                                                                           for b in agent_bytes))


def _cmd_verify(file_path: Path) -> dict:
    """Offline check of a local .tpb (it never calls a registry). Checks:
      - File is gzipped tar with expected layout (manifest.json, README.md, agents/*.json)
      - manifest.json parses
      - a signed bundle: the manifest and the agent files are the ones the signature covers (its attached payload
        names the manifest and each agent file's sha256), so a file changed after signing fails

    CB-299: it promised signature and checksum verification and checked neither. The signature ITSELF is still not
    verified here: that needs the signer's public key, which a bundle does not carry (iss names the developer it is
    published under), so the result says so rather than implying it.
    """
    data = file_path.read_bytes()
    result: dict = {
        "file": str(file_path.resolve()),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "structure": {},
        "manifest": {},
        "signature": {},
    }
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
            with tarfile.open(fileobj=gz, mode="r") as tar:
                members = {m.name: m for m in tar.getmembers() if m.isfile()}
                result["structure"]["members"] = sorted(list(members.keys()))
                result["structure"]["has_manifest"] = "manifest.json" in members
                result["structure"]["has_readme"] = "README.md" in members
                result["structure"]["has_signature"] = "signature.jws" in members
                agent_files = [n for n in members if n.startswith("agents/") and n.endswith(".json")]
                result["structure"]["agent_files"] = agent_files
                agent_bytes = [tar.extractfile(n).read() for n in sorted(agent_files)]
                manifest = None

                if "manifest.json" in members:
                    f = tar.extractfile("manifest.json")
                    manifest = json.loads(f.read().decode())
                    result["manifest"] = {
                        "bundle_id": manifest.get("bundle_id"),
                        "bundle_kind": manifest.get("bundle_kind"),
                        "name": manifest.get("name"),
                        "exporter": manifest.get("exporter", {}).get("developer_name"),
                        "registry_origin": manifest.get("exporter", {}).get("registry_origin"),
                        "exported_at": manifest.get("exporter", {}).get("exported_at"),
                        "total_agents": manifest.get("contents", {}).get("total_agents"),
                        "total_cicd_pipelines": manifest.get("contents", {}).get("total_cicd_pipelines"),
                    }
                if "signature.jws" in members:
                    sig_raw = tar.extractfile("signature.jws").read().decode()
                    parts = sig_raw.split(".")
                    result["signature"]["present"] = True
                    result["signature"]["parts_ok"] = len(parts) == 3
                    if len(parts) == 3:
                        try:
                            pad = lambda s: s + ("=" * ((4 - len(s) % 4) % 4))
                            header = json.loads(base64.urlsafe_b64decode(pad(parts[0])).decode())
                            result["signature"]["alg"] = header.get("alg")
                            result["signature"]["kid"] = header.get("kid")
                            result["signature"]["iss"] = header.get("iss")
                        except Exception:
                            result["signature"]["header_parse_error"] = True
                        result["signature"]["covers_contents"] = _signed_payload_covers(parts[1], manifest, agent_bytes)
                    result["signature"]["verified"] = False
                    result["signature"]["note"] = ("the signature itself is not checked here: that needs the signer's "
                                                   "public key, which a bundle does not carry")
                else:
                    result["signature"]["present"] = False
    except Exception as e:
        result["structure"]["error"] = f"{type(e).__name__}: {e}"
        result["valid"] = False
        return result
    result["valid"] = (
        result["structure"]["has_manifest"]
        and result["structure"]["has_readme"]
        and len(result["structure"]["agent_files"]) > 0
        and (not result["structure"]["has_signature"] or result["signature"].get("covers_contents") is True)
    )
    return result


# ── Typer wiring (matches the project's `register(app, ...)` pattern) ──────

def register(app, state, load_contexts, run_with_audit):
    bundle_app = typer.Typer(
        name="bundle",
        help="§pass51 — Bundles feature CLI surface (list/create/restore/download/verify/quota)",
        no_args_is_help=True,
    )

    @bundle_app.command("list")
    def bundle_list(
        api_key: Optional[str] = typer.Option(None, "--api-key", help="Developer API key"),
        kind: Optional[str] = typer.Option(None, help="Filter: snapshot|template|migration"),
        no_official: bool = typer.Option(False, "--no-official", help="Exclude is_official templates"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        for ctx in contexts:
            key = _resolve_api_key(ctx, api_key)
            try:
                data = run_with_audit("bundle.list", ctx.name, _cmd_list, ctx, key, kind, not no_official)
            except httpx.HTTPStatusError as e:
                out.line(f"[{ctx.name}] HTTP {e.response.status_code}: {e.response.text[:200]}")
                raise typer.Exit(code=2)
            if out.mode == "json":
                out.emit_json(data)
            else:
                out.line(f"\n[bold]{ctx.name}[/]  bundles: {data.get('total', 0)}")
                rows = [[b["kind"], "★" if b["is_official"] else " ", b["name"][:60], b["id"][:8], str(b.get("install_count", 0))] for b in data.get("bundles", [])]
                out.table("bundles", ["kind", "off", "name", "id", "installs"], rows)

    @bundle_app.command("create")
    def bundle_create(
        agent_did: List[str] = typer.Option(..., "--agent-did", help="Agent DID to include (repeatable)"),
        api_key: Optional[str] = typer.Option(None, "--api-key"),
        kind: str = typer.Option("snapshot", help="snapshot|template|migration"),
        name: Optional[str] = typer.Option(None),
        description: Optional[str] = typer.Option(None),
        visibility: str = typer.Option("private", help="private|org|public"),
        include_cicd: bool = typer.Option(True, "--include-cicd/--no-cicd"),
        sign: bool = typer.Option(True, "--sign/--no-sign"),
        out_file: Optional[Path] = typer.Option(None, "--out", help="Download .tpb after create"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        ctx = contexts[0]
        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would POST {ctx.registry_url}/api/v1/bundles ({kind}, "
                     f"{len(agent_did)} agent(s), {visibility})")
            raise typer.Exit(code=0)
        key = _resolve_api_key(ctx, api_key)
        try:
            data = run_with_audit(
                "bundle.create", ctx.name, _cmd_create, ctx, key,
                agent_dids=agent_did, kind=kind, name=name, description=description,
                visibility=visibility, include_cicd=include_cicd, sign=sign,
            )
        except httpx.HTTPStatusError as e:
            out.line(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            raise typer.Exit(code=2)
        if out_file:
            dl = _cmd_download(ctx, key, data["id"], out_file)
            data["downloaded"] = dl
        if out.mode == "json":
            out.emit_json(data)
        else:
            out.line(f"Created bundle [bold green]{data.get('bundle_id')}[/]")
            out.line(f"  kind: {data.get('kind')}  size: {data.get('size_bytes')} bytes  tier: {data.get('signature_tier')}")
            if out_file:
                out.line(f"  saved to: {out_file}")

    @bundle_app.command("download")
    def bundle_download(
        bundle_id: str = typer.Argument(..., help="Bundle UUID"),
        out_file: Path = typer.Option(Path("./bundle.tpb"), "--out"),
        api_key: Optional[str] = typer.Option(None, "--api-key"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        ctx = contexts[0]
        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would GET {ctx.registry_url}/api/v1/bundles/{bundle_id}/download "
                     f"into {out_file}")
            raise typer.Exit(code=0)
        key = _resolve_api_key(ctx, api_key)
        try:
            data = run_with_audit("bundle.download", ctx.name, _cmd_download, ctx, key, bundle_id, out_file)
        except httpx.HTTPStatusError as e:
            out.line(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
            raise typer.Exit(code=2)
        if out.mode == "json":
            out.emit_json(data)
        else:
            out.line(f"Downloaded [bold]{data['size_bytes']} bytes[/] → {data['saved_to']}")
            out.line(f"  sha256: {data['sha256'][:16]}…")

    @bundle_app.command("restore")
    def bundle_restore(
        file_path: Path = typer.Argument(..., help="Path to .tpb file"),
        api_key: Optional[str] = typer.Option(None, "--api-key"),
        conflict: str = typer.Option("rename", help="skip|rename|overwrite"),
        mode: str = typer.Option("copy", help="copy|mirror"),
        include_cicd: bool = typer.Option(True, "--include-cicd/--no-cicd"),
        idempotency_key: Optional[str] = typer.Option(None, "--idempotency-key"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not file_path.exists():
            out.line(f"File not found: {file_path}")
            raise typer.Exit(code=2)
        contexts = load_contexts()
        ctx = contexts[0]
        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would POST {file_path} to {ctx.registry_url}/api/v1/bundles/restore-from-upload "
                     f"({conflict}, {mode})")
            raise typer.Exit(code=0)
        key = _resolve_api_key(ctx, api_key)
        try:
            data = run_with_audit(
                "bundle.restore", ctx.name, _cmd_restore, ctx, key,
                file_path, conflict, mode, include_cicd, idempotency_key,
            )
        except httpx.HTTPStatusError as e:
            out.line(f"HTTP {e.response.status_code}: {e.response.text[:300]}")
            raise typer.Exit(code=2)
        if out.mode == "json":
            out.emit_json(data)
        else:
            success = data.get("success")
            out.line(f"Restore: [bold {'green' if success else 'red'}]{'success' if success else 'FAILED'}[/]")
            for a in data.get("produced_agents", []):
                out.line(f"  agent: {a['did']}")
                out.line(f"    client_id: {a['client_id']}")
                out.line(f"    client_secret: {a['client_secret']}    [yellow](shown ONCE — save this!)[/]")
            for w in data.get("warnings", []):
                out.line(f"  [yellow]warning:[/] {w}")
            for e in data.get("errors", []):
                out.line(f"  [red]error:[/] {e}")

    @bundle_app.command("verify")
    def bundle_verify(
        file_path: Path = typer.Argument(..., help="Path to .tpb file"),
    ):
        """Offline check of a local .tpb: layout, manifest and, when signed, that the contents are the ones the
        signature covers (the signature itself needs the signer's public key and is not verified here)."""
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not file_path.exists():
            out.line(f"File not found: {file_path}")
            raise typer.Exit(code=2)
        data = _cmd_verify(file_path)
        if out.mode == "json":
            out.emit_json(data)
        else:
            out.line(f"[bold]{file_path}[/]")
            out.line(f"  size: {data['size_bytes']} bytes  sha256: {data['sha256'][:16]}…")
            out.line(f"  valid: {'YES' if data.get('valid') else 'NO'}")
            mfst = data.get("manifest", {})
            if mfst:
                out.line(f"  manifest:")
                out.line(f"    bundle_id: {mfst.get('bundle_id')}")
                out.line(f"    kind: {mfst.get('bundle_kind')}")
                out.line(f"    name: {mfst.get('name')}")
                out.line(f"    exporter: {mfst.get('exporter')} on {mfst.get('registry_origin')}")
                out.line(f"    contents: {mfst.get('total_agents')} agent(s), {mfst.get('total_cicd_pipelines')} pipeline(s)")
            sig = data.get("signature", {})
            if sig.get("present"):
                out.line(f"  signature: alg={sig.get('alg')}  kid={(sig.get('kid') or '')[:16]}…  iss={sig.get('iss')}")
                out.line(f"    covers these contents: {'YES' if sig.get('covers_contents') else 'NO'}")
                out.line("    the signature itself: not verified here (needs the signer's public key)")
            else:
                out.line(f"  signature: NONE (unsigned bundle)")
        if not data.get("valid"):
            raise typer.Exit(code=2)

    @bundle_app.command("quota")
    def bundle_quota(
        developer_id: int = typer.Argument(..., help="Developer id"),
        api_key: Optional[str] = typer.Option(None, "--api-key", help="Must be admin_platform"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        ctx = contexts[0]
        key = _resolve_api_key(ctx, api_key)
        with _client(ctx, key) as c:
            try:
                r = c.get(f"/api/v1/admin/developers/{developer_id}/quota")
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                out.line(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
                raise typer.Exit(code=2)
            data = r.json()
        if out.mode == "json":
            out.emit_json(data)
        else:
            out.line(f"Developer #{developer_id} quota:")
            out.line(f"  max_bundle_count: {data.get('max_bundle_count')}")
            out.line(f"  max_total_bytes:  {data.get('max_bundle_total_bytes')}")
            out.line(f"  max_per_bundle:   {data.get('max_individual_bundle_bytes')}")
            out.line(f"  per_day_rate:     {data.get('bundle_create_rate_per_day')}")
            if data.get("current_usage"):
                u = data["current_usage"]
                out.line(f"  current usage:    {u.get('bundle_count')} bundles, {u.get('total_bytes')} bytes")
            if data.get("is_default"):
                out.line(f"  (showing defaults; no custom row set yet)")

    app.add_typer(bundle_app, name="bundle")
