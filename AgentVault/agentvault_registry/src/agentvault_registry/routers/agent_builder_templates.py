"""
Agent Builder Templates — Per-Agent MCP Server Bundle Generator
OWL-22 | 2026-03-10

Generates downloadable ZIP bundles containing:
  - Agent-specific MCP server (Node.js, SSE transport)
  - ZKP-enabled Dockerfile (nargo + bb pre-installed)
  - docker-compose.yml
  - Python FastAPI agent source (template-specific)
  - Pre-bundled ZKP circuits
  - README, CREDENTIALS, SETUP guides

Security note:
  - client_secret is NEVER in the ZIP — user fills .env.secret manually
  - agent_did and client_id are in .env (non-secret config)
  - ZIP is generated fresh per request; no caching of credentials
"""
import io
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

import jinja2
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from agentvault_registry import schemas, models, security
from agentvault_registry.core import zkp_verifier as _zkp

logger = logging.getLogger(__name__)

# ─── Template directories ──────────────────────────────────────────────────

TEMPLATE_ROOT = Path(__file__).parent.parent / "agent_templates"
COMMON_ZKP_DIR = TEMPLATE_ROOT / "common_zkp"
MCP_SERVER_DIR = TEMPLATE_ROOT / "mcp_server"

# Per-template source directories (Python agent code)
TEMPLATE_DIRS = {
    "sovereign-marketplace": TEMPLATE_ROOT / "sovereign-marketplace",
    "trading-sentinel":      TEMPLATE_ROOT / "trading-sentinel",
    "data-oracle":           TEMPLATE_ROOT / "data-oracle",
    "senate-delegate":       TEMPLATE_ROOT / "senate-delegate",
    # GÖDEL FORGE (2026-07-19) — the seed self-improving coding harness (OSS flagship):
    # Darwin-Gödel loop against the Forge arena (fork→spawn→commit→quorum-eval→adopt).
    "self-improving-coder":  TEMPLATE_ROOT / "self-improving-coder",
}

# ZKP circuit registry: the root the verifier reads (CIRCUIT_REGISTRY_PATH, else the image path)
CIRCUIT_REGISTRY_PATH = _zkp._CIRCUIT_REGISTRY_ROOT / "policies"

# What a bundled circuit directory carries: the files a prover and an offline
# verifier need. Build output (target/), editor and cache files stay behind.
_BUNDLED_CIRCUIT_FILES = (
    "Nargo.toml",
    "Prover.toml",
    "src/main.nr",
    "circuit.json",
    "metadata.json",
    "verification_key.bin",
)

# Verified versions from `docker exec agentvault_registry_a nargo/bb --version`
NARGO_VERSION = "1.0.0-beta.3"
BB_VERSION = "0.82.2"

# Default MCP ports per template
TEMPLATE_DEFAULTS = {
    "sovereign-marketplace": {"mcp_port": 3100, "agent_api_port": 8010, "agent_metrics_port": 8011},
    "trading-sentinel":      {"mcp_port": 3101, "agent_api_port": 8012, "agent_metrics_port": 8013},
    "data-oracle":           {"mcp_port": 3102, "agent_api_port": 8014, "agent_metrics_port": 8015},
    "senate-delegate":       {"mcp_port": 3103, "agent_api_port": 8016, "agent_metrics_port": 8017},
    "self-improving-coder":  {"mcp_port": 3104, "agent_api_port": 8018, "agent_metrics_port": 8019},
}

# ─── Router ────────────────────────────────────────────────────────────────

router = APIRouter(
    prefix="/agent-builder",
    tags=["Agent Builder Templates"],
    dependencies=[Depends(security.get_current_developer)],
)


# ─── Jinja2 helpers ────────────────────────────────────────────────────────

def _make_jinja_env(*template_dirs: Path) -> jinja2.Environment:
    """Create a Jinja2 environment from multiple template search paths."""
    existing = [str(d) for d in template_dirs if d.is_dir()]
    if not existing:
        raise RuntimeError(f"No template directories found: {template_dirs}")
    loader = jinja2.FileSystemLoader(existing)
    return jinja2.Environment(loader=loader, autoescape=False, keep_trailing_newline=True)


def _render(env: jinja2.Environment, template_name: str, ctx: dict) -> str:
    """Render a single Jinja2 template; log and re-raise on error."""
    try:
        return env.get_template(template_name).render(ctx)
    except jinja2.TemplateNotFound:
        logger.error(f"Template not found: {template_name}")
        raise HTTPException(
            status_code=500,
            detail=f"Template file missing: {template_name}. Backend configuration incomplete."
        )
    except jinja2.TemplateError as e:
        logger.error(f"Template render error [{template_name}]: {e}")
        raise HTTPException(status_code=500, detail=f"Template render error: {e}")


def _write(path: Path, content: str) -> None:
    """Write rendered content to path, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ─── Bundle generation ─────────────────────────────────────────────────────

def _build_context(cfg: schemas.TemplateDownloadConfig) -> dict:
    """Build the Jinja2 render context from config."""
    slug = cfg.human_readable_id
    package_name = slug.replace("-", "_")
    defaults = TEMPLATE_DEFAULTS.get(cfg.template_id, {})
    return {
        # Identity
        "agent_name":        cfg.agent_name,
        "human_readable_id": slug,
        "agent_did":         cfg.agent_did,
        "client_id":         cfg.client_id,
        "template_id":       cfg.template_id,
        # Connectivity
        "registry_url":      cfg.registry_url,
        "teg_url":           cfg.teg_url,
        # Ports
        "mcp_port":          cfg.mcp_port or defaults.get("mcp_port", 3100),
        "agent_api_port":    cfg.agent_api_port or defaults.get("agent_api_port", 8020),
        "agent_metrics_port": cfg.agent_metrics_port or defaults.get("agent_metrics_port", 9020),
        # Derived
        "container_name":    f"{slug}-agent",
        "package_name":      package_name,
        # ZKP versions (live-verified from container)
        "nargo_version":     NARGO_VERSION,
        "bb_version":        BB_VERSION,
    }


def _bundle_circuits(zip_file: zipfile.ZipFile, base_path: str) -> None:
    """
    Bundle the circuits this registry verifies (v2.0.0) into the ZIP, as
    circuits/<name>_v2.0.0/ with their source, Nargo.toml, example Prover.toml,
    compiled circuit.json, metadata.json and verification key. The retired
    v1.0.0 circuits and any build output (target/) are left out.
    Skips with a warning when the circuit registry is not on disk.
    """
    if not CIRCUIT_REGISTRY_PATH.exists():
        logger.warning(f"Circuit registry path not found: {CIRCUIT_REGISTRY_PATH}; skipping circuit bundling")
        return

    bundled = 0
    for circuit_id in _zkp._V2_CIRCUITS:
        name, version = circuit_id.split("/")
        circuit_dir = CIRCUIT_REGISTRY_PATH / name / version
        circuit_name = f"{name}_{version}"
        for rel in _BUNDLED_CIRCUIT_FILES:
            f = circuit_dir / rel
            if not f.is_file():
                logger.warning(f"Circuit file missing, not bundled: {f}")
                continue
            zip_file.write(f, f"{base_path}/circuits/{circuit_name}/{rel}")
            bundled += 1

    logger.info(f"Bundled {bundled} circuit files")


def _generate_bundle(cfg: schemas.TemplateDownloadConfig) -> bytes:
    """
    Generate the complete agent bundle ZIP and return raw bytes.
    Structure: {human_readable_id}/ at root of ZIP.
    """
    ctx = _build_context(cfg)
    slug = cfg.human_readable_id
    template_dir = TEMPLATE_DIRS.get(cfg.template_id)

    if not template_dir or not template_dir.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Template '{cfg.template_id}' is not yet available on this server. "
                   f"Available templates will be listed at /api/v1/agent-builder/templates."
        )

    # Jinja2 env: search common_zkp + mcp_server + template-specific
    env = _make_jinja_env(COMMON_ZKP_DIR, MCP_SERVER_DIR, template_dir,
                          MCP_SERVER_DIR / "tools", MCP_SERVER_DIR / "lib",
                          template_dir / "mcp_tools", template_dir / "src")

    buf = io.BytesIO()

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        base = slug  # root dir inside zip

        # ── Root files ─────────────────────────────────────────────────────
        zf.writestr(f"{base}/.gitignore",      _render(env, ".gitignore.j2", ctx))
        # §SUITES1018: the env templates are named dotenv*.j2 in the tree (a file named .env* never reaches git: the
        # .gitignore and the pre-commit hook refuse env files), and rendered under their .env names in the bundle
        zf.writestr(f"{base}/.env",            _render(env, "dotenv.j2", ctx))
        zf.writestr(f"{base}/.env.secret.example", _render(env, "dotenv.secret.example.j2", ctx))
        zf.writestr(f"{base}/CREDENTIALS.md",  _render(env, "CREDENTIALS.md.j2", ctx))
        zf.writestr(f"{base}/README.md",       _render(env, "README.md.j2", ctx))
        zf.writestr(f"{base}/Dockerfile",      _render(env, "Dockerfile.zkp.j2", ctx))
        zf.writestr(f"{base}/docker-compose.yml", _render(env, "docker-compose.j2", ctx))

        # ── MCP server ─────────────────────────────────────────────────────
        zf.writestr(f"{base}/mcp/server.js",     _render(env, "server.js.j2", ctx))
        zf.writestr(f"{base}/mcp/package.json",  _render(env, "package.json.j2", ctx))
        zf.writestr(f"{base}/mcp/SETUP.md",      _render(env, "SETUP.md.j2", ctx))

        # MCP lib
        zf.writestr(f"{base}/mcp/lib/auth.js",        _render(env, "auth.js.j2", ctx))
        zf.writestr(f"{base}/mcp/lib/config.js",       _render(env, "config.js.j2", ctx))
        zf.writestr(f"{base}/mcp/lib/http_client.js",  _render(env, "http_client.js.j2", ctx))

        # MCP universal tools
        zf.writestr(f"{base}/mcp/tools/registry_api.js",    _render(env, "registry_api.js.j2", ctx))
        zf.writestr(f"{base}/mcp/tools/local_state.js",     _render(env, "local_state.js.j2", ctx))
        zf.writestr(f"{base}/mcp/tools/agent_lifecycle.js", _render(env, "agent_lifecycle.js.j2", ctx))
        zf.writestr(f"{base}/mcp/tools/attestation.js",     _render(env, "attestation.js.j2", ctx))

        # Template-specific MCP tools (optional — skip if not present)
        specific_tools_dir = template_dir / "mcp_tools"
        if specific_tools_dir.is_dir():
            for tool_file in specific_tools_dir.glob("*.js.j2"):
                tool_name = tool_file.name[:-3]  # strip .j2
                zf.writestr(f"{base}/mcp/tools/{tool_name}", _render(env, tool_file.name, ctx))

        # ── Python agent source ────────────────────────────────────────────
        src_dir = template_dir / "src"
        if src_dir.is_dir():
            pkg = ctx["package_name"]
            for src_file in src_dir.rglob("*"):
                if src_file.is_file() and src_file.suffix in (".py", ".txt", ".toml", ".j2", ".cfg"):
                    rel = src_file.relative_to(src_dir)
                    arc_name = str(rel)
                    if src_file.suffix == ".j2":
                        # Render Jinja2 templates; strip .j2 extension
                        content = _render(env, src_file.name, ctx)
                        arc_name = arc_name[:-3]
                    else:
                        content = src_file.read_text(encoding="utf-8")
                    zf.writestr(f"{base}/src/{pkg}/{arc_name}", content)

        # Common attestation_client.py
        zf.writestr(
            f"{base}/src/{ctx['package_name']}/attestation_client.py",
            _render(env, "attestation_client.py.j2", ctx)
        )

        # ── ZKP circuits ───────────────────────────────────────────────────
        if cfg.include_circuits:
            _bundle_circuits(zf, base)

        # ── Gitkeep stubs ──────────────────────────────────────────────────
        zf.writestr(f"{base}/data/.gitkeep", "")
        zf.writestr(f"{base}/logs/.gitkeep", "")

    buf.seek(0)
    return buf.read()


# ─── Endpoint ──────────────────────────────────────────────────────────────

@router.post(
    "/generate-template",
    summary="Generate Agent Bundle with MCP Server",
    description=(
        "Generates a downloadable ZIP bundle for the specified template agent. "
        "The bundle contains: Node.js MCP server (Claude Desktop integration), "
        "ZKP-enabled Dockerfile, docker-compose.yml, Python FastAPI agent source, "
        "pre-bundled ZKP circuits, and full setup documentation. "
        "NOTE: client_secret is NOT included: users fill .env.secret manually after extraction."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "ZIP archive containing the complete agent bundle",
        },
        400: {"description": "Template not available or invalid configuration"},
        422: {"description": "Validation error"},
        500: {"description": "Bundle generation failed"},
    },
)
async def generate_template_bundle(
    cfg: schemas.TemplateDownloadConfig,
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """Generate and stream the agent bundle ZIP."""
    logger.info(
        f"Bundle request: developer={current_developer.id} "
        f"template={cfg.template_id} slug={cfg.human_readable_id}"
    )

    try:
        bundle_bytes = _generate_bundle(cfg)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Bundle generation failed for {cfg.human_readable_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Bundle generation failed: {type(e).__name__}: {e}"
        )

    filename = f"{cfg.human_readable_id}.zip"
    return StreamingResponse(
        io.BytesIO(bundle_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/templates",
    summary="List available agent templates",
)
async def list_templates(
    current_developer: models.Developer = Depends(security.get_current_developer),
):
    """Return list of available template IDs and their readiness status."""
    result = []
    for tid, tdir in TEMPLATE_DIRS.items():
        result.append({
            "template_id": tid,
            "available": tdir.is_dir(),
            **TEMPLATE_DEFAULTS.get(tid, {}),
        })
    return {"templates": result}
