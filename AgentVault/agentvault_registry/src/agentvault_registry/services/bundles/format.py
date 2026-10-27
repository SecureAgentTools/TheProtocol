"""§pass51 Block 2 — .tpb file format: pack/unpack + manifest + README gen.

Per PLAN §2. A Bundle is a gzipped tarball with this layout:

    manifest.json              ← canonical schema
    README.md                  ← auto-generated, human-readable
    signature.jws              ← OPTIONAL (Tier 1+ only)
    agents/<slug>.json         ← one file per agent payload
    cicd/<slug>.yaml           ← OPTIONAL pipeline templates

Public helpers:
    build_agent_payload(agent_full) → dict — what goes in agents/<slug>.json
    pack_bundle(manifest, agent_payloads, signature_jws=None, cicd_payloads=None)
        → bytes (gzipped tar)
    unpack_bundle(data) → (manifest, agent_payloads, signature_jws, cicd_payloads)
    render_readme(manifest) → str
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import re
import tarfile
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

BUNDLE_VERSION = "1.0"


# ── Agent payload construction ──────────────────────────────────────────────

def build_agent_payload(*,
                        agent_row: dict,
                        agent_card_row: Optional[dict],
                        capabilities: list[dict],
                        endpoints: list[dict],
                        tags: list[str],
                        cicd_pipeline_yaml: Optional[str] = None) -> dict:
    """Produce the canonical agent JSON for the bundle.

    `agent_row` shape: {did, name, status, public_key_jwk}.
    `agent_card_row` shape: full card_data dict OR None.
    NEVER includes: client_id, hashed_client_secret, liquid_balance,
    staked_balance, reputation_score, creator_developer_id.
    """
    payload = {
        "did": agent_row["did"],
        "name": agent_row.get("name") or "Unnamed Agent",
        "status": agent_row.get("status") or "active",
        "public_key_jwk": agent_row.get("public_key_jwk"),
        "capabilities": capabilities or [],
        "endpoints": endpoints or [],
        "tags": tags or [],
    }
    if agent_card_row:
        payload["agent_card"] = agent_card_row
    if cicd_pipeline_yaml:
        payload["has_cicd"] = True
    # §pass51 P37 — pipelines are added to payload by the caller; keep this
    # helper agnostic so it's reusable without coupling.
    return payload


# ── Manifest construction ──────────────────────────────────────────────────

def build_manifest(*,
                   bundle_id: str,
                   bundle_kind: str,
                   name: str,
                   description: str,
                   purpose_hint: str,
                   exporter: dict,
                   contents_summary: dict,
                   restore_compatible: list[str],
                   audit_block: Optional[dict] = None) -> dict:
    """Construct the manifest.json dict.

    `exporter` shape: {developer_id, developer_name, developer_email_redacted,
                       registry_origin, frame, exported_at}.
    `contents_summary`: {agents: [...], total_agents, total_cicd_pipelines}.
    `audit_block`: optional — economic state snapshot etc.
    """
    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "bundle_id": bundle_id,
        "bundle_kind": bundle_kind,
        "name": name,
        "description": description or "",
        "purpose_hint": purpose_hint,
        "exporter": exporter,
        "contents": contents_summary,
        "instructions": {
            "restore_compatible": restore_compatible,
            "fork_safe": True,
            "credentials": "regenerated_on_restore",
            "balance_state": "NOT_INCLUDED",
            "signing_keys": "REGENERATED_OR_PULL_SYNC",
        },
        "audit": audit_block or {},
    }
    return manifest


# ── README generation ───────────────────────────────────────────────────────

def render_readme(manifest: dict) -> str:
    """Human-readable README.md from the manifest.

    Designed so a user 6 months later opens this file and instantly knows
    what they have without running any code.
    """
    exporter = manifest.get("exporter", {})
    contents = manifest.get("contents", {})
    agents = contents.get("agents", [])
    kind_label = {
        "snapshot":  "Snapshot (private backup)",
        "template":  "Template (shareable blueprint)",
        "migration": "Migration archive (one-shot move)",
    }.get(manifest.get("bundle_kind"), "Bundle")

    lines = [
        f"# {manifest.get('name', 'Agent Bundle')}",
        "",
        f"**Bundle ID:** `{manifest.get('bundle_id')}`",
        f"**Kind:** {kind_label}",
        f"**Created by:** {exporter.get('developer_name', '?')} "
        f"({exporter.get('frame', '?')}, {exporter.get('registry_origin', '?')})",
        f"**Created at:** {exporter.get('exported_at', '?')}",
    ]
    if manifest.get("description"):
        lines += ["", manifest["description"]]

    lines += ["", "## Contents", ""]
    if not agents:
        lines += ["_(no agents — empty bundle)_"]
    else:
        lines += [f"**{len(agents)} agent(s):**", ""]
        for a in agents:
            cicd_line = "No CI/CD pipeline"
            if a.get('has_cicd'):
                pc = a.get('pipeline_count', 1)
                cicd_line = f"{pc} CI/CD pipeline{'s' if pc != 1 else ''} included"
            lines += [
                f"- **{a.get('name', '?')}** (`{a.get('source_did', '?')}`)",
                f"  - A2A v{a.get('a2a_version', '?')} compliant" if a.get('a2a_version') else "",
                f"  - {cicd_line}",
                f"  - Flare tier: {a.get('flare_tier') or 'none'}" if 'flare_tier' in a else "",
            ]
    lines = [ln for ln in lines if ln is not None and ln != ""]

    lines += [
        "",
        "## How to restore",
        "",
        "On a TheProtocol registry web UI:",
        "1. Go to **/bundles** → **Restore from File** tab",
        "2. Drop this `.tpb` file or click Browse",
        "3. Pick conflict mode (rename / overwrite / skip)",
        "4. Confirm",
        "",
        "## What restore WILL do",
        "- Create new agent row(s) with the same name + capabilities + A2A card",
        "- Generate fresh `client_id` + `client_secret` (shown ONCE)",
        "- Install attached CI/CD pipelines (if any, opt-in)",
        "",
        "## What restore WILL NOT do",
        "- Restore any AVT balance (audit-only; see `manifest.audit`)",
        "- Restore the original signing key (regenerated)",
        "- Restore federation lineage (run pull-sync after restore to re-attach)",
        "- Carry over reputation score",
    ]
    audit = manifest.get("audit", {}).get("economic_state_snapshot_at_export")
    if audit:
        lines += [
            "",
            "## Audit-only economic snapshot (at export time)",
            "",
            f"- liquid balance: {audit.get('liquid_balance', 0)}",
            f"- staked balance: {audit.get('staked_balance', 0)}",
            f"- reputation score: {audit.get('reputation_score', 0)}",
            "",
            f"_{audit.get('note', '')}_",
        ]
    return "\n".join(lines) + "\n"


# ── Tar pack/unpack ─────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", (s or "").lower()).strip("-")
    return s or "agent"


def pack_bundle(*,
                manifest: dict,
                agent_payloads: list[dict],
                signature_jws: Optional[str] = None,
                cicd_payloads: Optional[dict[str, str]] = None) -> bytes:
    """Build .tpb gzipped tarball.

    `agent_payloads` is a list of dicts (one per agent), each as built by
    build_agent_payload().
    `cicd_payloads` is dict {slug: yaml_text}.
    Returns the bundle bytes.
    """
    readme = render_readme(manifest)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:
            def _add(name: str, content: bytes):
                ti = tarfile.TarInfo(name=name)
                ti.size = len(content)
                ti.mtime = 0  # reproducibility — drops mtime variability
                tar.addfile(ti, io.BytesIO(content))

            _add("manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode())
            _add("README.md", readme.encode())
            if signature_jws:
                _add("signature.jws", signature_jws.encode())
            for ap in agent_payloads:
                slug = _slugify(ap.get("name", "agent")) + "-" + (ap.get("did", "")[-12:] or "x")
                _add(f"agents/{slug}.json", json.dumps(ap, indent=2, sort_keys=True).encode())
            for slug, yaml_text in (cicd_payloads or {}).items():
                _add(f"cicd/{slug}.yaml", yaml_text.encode())
    return buf.getvalue()


def unpack_bundle(data: bytes) -> tuple[dict, list[dict], Optional[str], dict[str, str]]:
    """Parse .tpb bytes into (manifest, agent_payloads, signature_jws, cicd_payloads)."""
    manifest = None
    agent_payloads = []
    signature_jws = None
    cicd_payloads = {}

    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
        with tarfile.open(fileobj=gz, mode="r") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                f = tar.extractfile(member)
                if not f:
                    continue
                content = f.read()
                name = member.name
                if name == "manifest.json":
                    manifest = json.loads(content.decode())
                elif name == "signature.jws":
                    signature_jws = content.decode()
                elif name.startswith("agents/") and name.endswith(".json"):
                    agent_payloads.append(json.loads(content.decode()))
                elif name.startswith("cicd/") and name.endswith(".yaml"):
                    slug = name[len("cicd/"):-len(".yaml")]
                    cicd_payloads[slug] = content.decode()
                # README.md and other files are passthrough; ignored
    if not manifest:
        raise ValueError("Bundle missing required manifest.json")
    return manifest, agent_payloads, signature_jws, cicd_payloads


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Convenience: build canonical signing payload from manifest ──────────────

def canonical_signing_payload(manifest: dict, agent_payloads: list[dict]) -> bytes:
    """Bytes that get signed in the JWS.

    Per PLAN §14.2: signature covers manifest + Merkle root of artifact
    checksums. We simplify: sign over `{manifest_json, agent_payload_sha256_list}`
    canonical JSON. Re-computable at verify time from the bundle contents.
    """
    agent_hashes = [
        compute_sha256(json.dumps(ap, indent=2, sort_keys=True).encode())
        for ap in agent_payloads
    ]
    canon = json.dumps(
        {"manifest": manifest, "agent_payload_sha256": sorted(agent_hashes)},
        sort_keys=True, separators=(",", ":")
    )
    return canon.encode()
