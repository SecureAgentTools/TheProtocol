"""
Agent bundle download — generates a ready-to-run agent package.

POST /api/v1/onboard/download-bundle
Authorization: Bearer {devJwt}
Body: { "agent_did": "did:theprotocol:...", "client_id": "agent-...", "client_secret": "tp_secret_...", "template_type": "minimal" }
Returns: ZIP file stream containing a configured agent: the starter ("minimal", Agent Forge's featured default: an
external agent on the SDK) or the PPAO orchestrator ("ppao").
"""
import io
import json
import logging
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Agent, AgentCard, Developer
from ..core.frame_currency import frame_currency
from ..core.public_url import credential_home_url
from ..security import get_current_developer_unified, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboard", tags=["Onboarding"])

# Path to agent templates (both ship in the image)
PPAO_TEMPLATE_DIR = Path(os.getenv("PPAO_TEMPLATE_DIR", "/app/ppao-template"))
MINIMAL_TEMPLATE_DIR = Path(os.getenv("MINIMAL_TEMPLATE_DIR", "/app/minimal-template"))


# §MCPTEST30 (V0640): the templates a bundle can be built from, in the order Agent Forge offers them; one is available
# where its directory exists. V0658 (b): the starter (id "minimal": an external agent on the SDK, the image's
# minimal-template) is Agent Forge's featured default; "full-capacity" (D6-822: a host bind mount on retired Frame A, on
# no frame since 2026-09-07) is gone from the catalogue.
def _template_dirs() -> List[Tuple[str, Path]]:
    return [("minimal", MINIMAL_TEMPLATE_DIR), ("ppao", PPAO_TEMPLATE_DIR)]


def available_templates() -> List[str]:
    """The template ids this registry can build a bundle from, in _template_dirs' order (minimal, ppao). Agent Forge
    shows them in its own catalogue's order; a download without a pick takes the first one listed here."""
    return [tid for tid, d in _template_dirs() if d.exists()]

# Directories and patterns to skip when building the ZIP
SKIP_DIRS = {
    "__pycache__",
    ".git",
    "node_modules",
    "screenshots",
    ".mypy_cache",
    ".pytest_cache",
}

# Files to skip
SKIP_FILES = {
    ".pyc",
    ".pyo",
    "gg_screenshot.mjs",
    "gg_verify.mjs",
    "GLASS_GERALD_IMPLEMENTATION_STRATEGY.md",
    "FRONTEND_UPGRADE_PLAN.md",
    "AGENT_ARCHITECTURE.md",
    "CREDENTIALS.md",
}

# Directories whose contents we skip (but keep .gitkeep)
EMPTY_VOLUME_DIRS = {"data", "logs", "circuits"}


class BundleRequest(BaseModel):
    agent_did: str = Field(..., description="The agent's DID (did:theprotocol:...)")
    client_id: str = Field(..., description="The agent's client_id (agent-...)")
    client_secret: str = Field(..., description="The agent's client_secret (tp_secret_...)")
    template_type: str = Field("minimal", description="Template type: minimal (the starter: an external agent on the SDK) or ppao (orchestrator)")


def _slugify(name: str) -> str:
    """Convert agent name to a filesystem-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "my-agent"


def _should_skip(rel_path: Path) -> bool:
    """Check if a file/directory should be excluded from the ZIP."""
    parts = rel_path.parts

    # Skip hidden dirs/files (except .env, .env.secret, .gitkeep, .gitignore, .dockerignore)
    for part in parts:
        if part.startswith(".") and part not in {
            ".env", ".env.secret", ".gitkeep", ".gitignore", ".dockerignore",
        }:
            return True

    # Skip blacklisted directories
    for part in parts:
        if part in SKIP_DIRS:
            return True

    # Skip frontend-src/node_modules specifically
    if len(parts) >= 2 and parts[0] == "frontend-src" and parts[1] == "node_modules":
        return True

    # Skip files by extension or name
    filename = parts[-1]
    if filename.endswith((".pyc", ".pyo")):
        return True
    if filename in SKIP_FILES:
        return True

    # Skip volume dir contents (except .gitkeep)
    if len(parts) >= 2 and parts[0] in EMPTY_VOLUME_DIRS:
        if filename != ".gitkeep":
            return True

    return False


def _generate_readme(agent_name: str, agent_did: str, template_readme: str) -> str:
    """Fill in agent name and DID in the README."""
    text = template_readme
    text = text.replace(
        "- **Name**: (pre-filled from your agent card)",
        f"- **Name**: {agent_name}",
    )
    text = text.replace(
        "- **DID**: (pre-filled)",
        f"- **DID**: `{agent_did}`",
    )
    return text


# V0658 (b): the starter's .env names its registry, its unit and its public address; the download fills them in from
# what this registry knows, and a value it does not know stays empty (the agent then says what to set).
def _public_origin(card_data: Dict[str, Any]) -> str:
    """The scheme and host of the endpoint the card declares (supportedInterfaces[0].url, else the A2A v0.3 `url`),
    the address the registry reads the agent's card from; "" when the card declares none."""
    from urllib.parse import urlsplit
    ifaces = card_data.get("supportedInterfaces") if isinstance(card_data, dict) else None
    url = ""
    if isinstance(ifaces, list) and ifaces and isinstance(ifaces[0], dict):
        url = str(ifaces[0].get("url") or "")
    if not url and isinstance(card_data, dict):
        url = str(card_data.get("url") or "")
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}" if p.scheme in ("http", "https") and p.netloc else ""


def _render_starter_env(template_env: str, values: Dict[str, str]) -> str:
    """The starter's .env with each key of `values` set to its value; every other line as the template has it."""
    out = []
    for line in template_env.splitlines():
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        out.append(f"{key}={values[key]}" if key in values else line)
    return "\n".join(out) + "\n"


@router.get("/bundle-templates")
async def bundle_templates(current_developer: Developer = Depends(get_current_developer_unified)) -> Dict[str, Any]:
    """The bundle templates this registry can build (§MCPTEST30, V0640): Agent Forge offers these, and a download
    without a pick takes the first."""
    have = available_templates()
    return {"templates": have, "default": have[0] if have else None}


@router.post("/download-bundle")
async def download_bundle(
    req: BundleRequest,
    current_developer: Developer = Depends(get_current_developer_unified),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and download a ready-to-run agent bundle (ZIP).

    The bundle contains a configured agent template. Just `docker compose up -d` to run.
    Supports template_type: "minimal" (the starter, Agent Forge's default: an external agent on the SDK, its .env
    naming this registry, the agent's public address and the registry's unit, its card the agent's own) or "ppao"
    (orchestrator), where this registry has it (GET /onboard/bundle-templates).
    """
    # 1. Select and verify template directory. §MCPTEST30 (V0640): a template this registry does not have answers 404
    # naming the ones it has, never a 500 for the client's choice, and a name outside the catalogue is no longer read
    # as "full-capacity"
    active_template_dir = dict(_template_dirs()).get(req.template_type)
    if active_template_dir is None or not active_template_dir.exists():
        have = available_templates()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(f"Template '{req.template_type}' is not available on this registry; "
                    f"it has: {', '.join(have) if have else 'none'}"),
        )
    is_ppao = req.template_type == "ppao"
    is_minimal = req.template_type == "minimal"

    # 2. Look up the agent and verify ownership
    agent_result = await db.execute(
        select(Agent).where(Agent.did == req.agent_did)
    )
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {req.agent_did} not found",
        )

    if agent.creator_developer_id != current_developer.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only download bundles for your own agents",
        )

    # Verify client_id matches
    if agent.client_id != req.client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_id does not match the agent record",
        )
    # §MCPTEST30 (V0640): and the secret the bundle will carry is the agent's own. The bundle writes it into
    # .env.secret as given, so a mistyped secret built a bundle whose agent could never sign in, with no error
    # anywhere until it ran. Checked as POST /auth/agent/token checks it (the stored hash); nothing is built otherwise.
    if not verify_password(req.client_secret, agent.hashed_client_secret):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="client_secret does not match the agent record",
        )

    # 3. Get the agent's card data
    card_result = await db.execute(
        select(AgentCard).where(AgentCard.agent_did == req.agent_did)
    )
    card = card_result.scalar_one_or_none()

    agent_name = card.name if card else "My Agent"
    card_data = card.card_data if card else {"name": agent_name, "did": req.agent_did}

    slug = _slugify(agent_name)
    container_name = f"{slug}-agent"

    # 4. Build the ZIP in memory
    buf = io.BytesIO()

    # Read template files we'll modify. V0658 (b): the starter keeps its settings as .env.example (a tracked file may
    # not be named .env: the repository's ignore rules and pre-commit hook refuse one), and the bundle writes .env
    template_env_path = active_template_dir / (".env.example" if is_minimal else ".env")
    template_env = template_env_path.read_text() if template_env_path.exists() else ""

    template_readme_path = active_template_dir / "README.md"
    template_readme = template_readme_path.read_text() if template_readme_path.exists() else ""

    # V0658 (b): the starter's compose file is compose.yaml (the Compose specification's own name; the repository ignores
    # every docker-compose.yml, which is why the minimal template never shipped one)
    template_compose_path = active_template_dir / ("compose.yaml" if is_minimal else "docker-compose.yml")
    template_compose = template_compose_path.read_text() if template_compose_path.exists() else ""

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Walk the template directory
        for file_path in sorted(active_template_dir.rglob("*")):
            if file_path.is_dir():
                continue

            rel = file_path.relative_to(active_template_dir)

            if _should_skip(rel):
                continue

            rel_str = str(rel)

            # Replace specific files with generated versions
            if rel_str == ".env":
                zf.writestr(rel_str, template_env)
            elif rel_str == ".env.secret":
                # Skip — we generate our own below
                continue
            elif rel_str == "README.md":
                content = _generate_readme(agent_name, req.agent_did, template_readme)
                if is_minimal:
                    content = content.replace("my-agent", container_name)   # the compose service it names
                zf.writestr(rel_str, content)
            elif rel_str == template_compose_path.name:
                content = template_compose.replace("ppao-agent" if is_ppao else "my-agent", container_name)
                zf.writestr(rel_str, content)
            elif rel_str == "agent-card.json" and is_minimal:
                # the starter serves the agent's own card (card.py): the registry's copy, as it stands now
                zf.writestr(rel_str, json.dumps(card_data, indent=2) + "\n")
            else:
                # Copy file as-is
                zf.write(file_path, rel_str)

        # The starter's .env: its settings, with what this registry knows filled in (.env.example is not shipped)
        if is_minimal and template_env:
            zf.writestr(".env", _render_starter_env(template_env, {
                "AGENT_NAME": agent_name, "AGENT_DID": req.agent_did, "REGISTRY_URL": credential_home_url() or "",
                "PUBLIC_URL": _public_origin(card_data), "CURRENCY": frame_currency()}))

        # Add generated .env.secret with real credentials
        if is_ppao:
            secret_content = (
                f"# PPAO Agent Credentials — NEVER COMMIT THIS FILE\n"
                f"PPAO_AGENT_DID={req.agent_did}\n"
                f"PPAO_CLIENT_ID={req.client_id}\n"
                f"PPAO_CLIENT_SECRET={req.client_secret}\n"
            )
        else:
            secret_content = (
                f"# Agent Credentials — NEVER COMMIT THIS FILE\n"
                f"AGENT_DID={req.agent_did}\n"
                f"CLIENT_ID={req.client_id}\n"
                f"CLIENT_SECRET={req.client_secret}\n"
            )
        zf.writestr(".env.secret", secret_content)

    buf.seek(0)
    filename = f"agent-{slug}.zip"

    logger.info(
        f"Generated agent bundle for {req.agent_did} ({agent_name}) "
        f"by developer {current_developer.id} — {filename}"
    )

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(buf.getbuffer().nbytes),
        },
    )
