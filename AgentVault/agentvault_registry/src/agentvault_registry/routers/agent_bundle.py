"""
Agent bundle download — generates a ready-to-run agent package.

POST /api/v1/onboard/download-bundle
Authorization: Bearer {devJwt}
Body: { "agent_did": "did:theprotocol:...", "client_id": "agent-...", "client_secret": "tp_secret_..." }
Returns: ZIP file stream containing a configured GeraldShip agent.
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
from ..security import get_current_developer_unified, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboard", tags=["Onboarding"])

# Path to agent templates (mounted as read-only volumes in production)
TEMPLATE_DIR = Path(os.getenv("AGENT_TEMPLATE_DIR", "/app/agent-template"))
PPAO_TEMPLATE_DIR = Path(os.getenv("PPAO_TEMPLATE_DIR", "/app/ppao-template"))
MINIMAL_TEMPLATE_DIR = Path(os.getenv("MINIMAL_TEMPLATE_DIR", "/app/minimal-template"))


# §MCPTEST30 (V0640): the templates a bundle can be built from, in the order Agent Forge offers them; one is available
# where its directory exists. "full-capacity" was a host bind mount on Frame A (./Agents/GeraldShip as
# /app/agent-template), which no frame stood up since 2026-09-07 carries, so a request for it answered 500 everywhere.
# Whether to ship it in the image is his call (agentvault2-d6's decision list); until then the registry lists what it
# has.
def _template_dirs() -> List[Tuple[str, Path]]:
    return [("full-capacity", TEMPLATE_DIR), ("minimal", MINIMAL_TEMPLATE_DIR), ("ppao", PPAO_TEMPLATE_DIR)]


def available_templates() -> List[str]:
    """The template ids this registry can build a bundle from, in _template_dirs' order (full-capacity, minimal, ppao).
    Agent Forge shows them in its own catalogue's order; a download without a pick takes the first one listed here."""
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
    template_type: str = Field("full-capacity", description="Template type: full-capacity (GeraldShip), ppao (orchestrator), or minimal (SDK starter)")


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


def _generate_env(
    agent_did: str,
    client_id: str,
    agent_name: str,
    container_name: str,
    template_env: str,
) -> str:
    """Generate .env with agent-specific values filled in."""
    lines = []
    replacements = {
        "AGENT_DID": agent_did,
        "CLIENT_ID": client_id,
        "AGENT_NAME": agent_name,
        "CONTAINER_NAME": container_name,
        "TEMPLATE_ID": _slugify(agent_name),
    }

    for line in template_env.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in replacements:
            lines.append(f"{key}={replacements[key]}")
        else:
            lines.append(line)

    return "\n".join(lines) + "\n"


def _generate_env_secret(client_secret: str) -> str:
    """Generate .env.secret with the client secret."""
    return f"CLIENT_SECRET={client_secret}\n"


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


def _generate_docker_compose(agent_name: str, container_name: str, template: str) -> str:
    """Update docker-compose.yml with agent-specific container name."""
    text = template
    # Replace the service name and container_name
    text = text.replace("gerald-ship-agent", container_name)
    return text


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
    Supports template_type: "full-capacity" (GeraldShip), "minimal" (SDK starter) or "ppao" (orchestrator), where
    this registry has it (GET /onboard/bundle-templates).
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

    # Read template files we'll modify
    template_env_path = active_template_dir / ".env"
    template_env = template_env_path.read_text() if template_env_path.exists() else ""

    template_readme_path = active_template_dir / "README.md"
    template_readme = template_readme_path.read_text() if template_readme_path.exists() else ""

    template_compose_path = active_template_dir / "docker-compose.yml"
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
                if is_ppao:
                    content = template_env
                elif is_minimal:
                    # Minimal: inject agent name and DID
                    content = template_env.replace("AGENT_NAME=My Agent", f"AGENT_NAME={agent_name}")
                    content = content.replace("AGENT_DID=PLACEHOLDER_DID", f"AGENT_DID={req.agent_did}")
                else:
                    content = _generate_env(
                        agent_did=req.agent_did,
                        client_id=req.client_id,
                        agent_name=agent_name,
                        container_name=container_name,
                        template_env=template_env,
                    )
                zf.writestr(rel_str, content)
            elif rel_str == ".env.secret":
                # Skip — we generate our own below
                continue
            elif rel_str == "README.md":
                content = _generate_readme(agent_name, req.agent_did, template_readme)
                zf.writestr(rel_str, content)
            elif rel_str == "docker-compose.yml":
                if is_ppao:
                    content = template_compose.replace("ppao-agent", container_name)
                elif is_minimal:
                    content = template_compose.replace("my-agent", container_name)
                else:
                    content = _generate_docker_compose(agent_name, container_name, template_compose)
                zf.writestr(rel_str, content)
            else:
                # Copy file as-is
                zf.write(file_path, rel_str)

        # Add generated .env.secret with real credentials
        if is_ppao:
            secret_content = (
                f"# PPAO Agent Credentials — NEVER COMMIT THIS FILE\n"
                f"PPAO_AGENT_DID={req.agent_did}\n"
                f"PPAO_CLIENT_ID={req.client_id}\n"
                f"PPAO_CLIENT_SECRET={req.client_secret}\n"
            )
            zf.writestr(".env.secret", secret_content)
        elif is_minimal:
            secret_content = (
                f"# Agent Credentials — NEVER COMMIT THIS FILE\n"
                f"AGENT_DID={req.agent_did}\n"
                f"CLIENT_ID={req.client_id}\n"
                f"CLIENT_SECRET={req.client_secret}\n"
            )
            zf.writestr(".env.secret", secret_content)
        else:
            zf.writestr(".env.secret", _generate_env_secret(req.client_secret))
            zf.writestr("agent-card.json", json.dumps(card_data, indent=2) + "\n")

        # Ensure volume dirs have .gitkeep
        for d in EMPTY_VOLUME_DIRS:
            gitkeep = f"{d}/.gitkeep"
            try:
                zf.getinfo(gitkeep)
            except KeyError:
                zf.writestr(gitkeep, "")

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
