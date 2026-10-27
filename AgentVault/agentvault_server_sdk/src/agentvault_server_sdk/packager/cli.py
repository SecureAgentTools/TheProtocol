"""
Command-line interface for the AgentVault Server SDK utilities,
starting with the agent packager.
"""

import typer
import logging
import shutil # Import shutil for file copying
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Create the Typer application
app = typer.Typer(
    name="agentvault-sdk",
    help="Utilities for building and packaging AgentVault A2A agents.",
    add_completion=False # Disable shell completion for now
)

# --- Dockerfile Templates ---
# Basic multi-stage Dockerfile (no ZKP)
DOCKERFILE_TEMPLATE = """\
# Stage 1: Build environment with dependencies
FROM python:{PYTHON_VERSION_TAG} as builder

WORKDIR /opt/builder

# Install build tools if needed (example for packages needing compilation)
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential gcc

# Copy requirements first to leverage Docker cache
COPY {REQUIREMENTS_FILE} ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r {REQUIREMENTS_FILE}

# Stage 2: Final application image
FROM python:{PYTHON_VERSION_TAG}

# Set working directory
WORKDIR {APP_DIR}

# Create a non-root user and group
RUN groupadd -r appgroup && useradd --no-log-init -r -g appgroup appuser

# Copy installed dependencies from builder stage
COPY --from=builder /usr/local/lib/python{PYTHON_MAJOR_MINOR}/site-packages /usr/local/lib/python{PYTHON_MAJOR_MINOR}/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Change ownership to non-root user
RUN chown -R appuser:appgroup {APP_DIR}

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE {PORT}

# Command to run the application
CMD ["uvicorn", "{ENTRYPOINT_MODULE_PATH}", "--host", "0.0.0.0", "--port", "{PORT}"]
"""

# --- .dockerignore Content ---
DOCKERIGNORE_CONTENT = """\
# Git
.git
.gitignore

# Python cache/build artifacts
__pycache__/
*.py[cod]
*$py.class
build/
dist/
*.egg-info/
*.egg

# Virtual environments
.venv/
venv/
ENV/
env/

# OS generated files
.DS_Store
Thumbs.db

# Test artifacts
.pytest_cache/
htmlcov/
.coverage*

# Secrets / Config
.env*
!/.env.example

# Logs / Temp
*.log
logs/
*.log.*
*.tmp
tmp/
temp/

# IDE files
.vscode/
.idea/
*.sublime-*
"""


@app.command()
def package_agent(
    output_dir: Path = typer.Option(
        ...,
        "--output-dir",
        "-o",
        help="Directory to write Dockerfile and other artifacts.",
        file_okay=False,
        dir_okay=True,
        writable=True,
        resolve_path=True,
    ),
    python_version: str = typer.Option(
        "3.11",
        "--python",
        help="Python version for base image tag (e.g., 3.10, 3.11)."
    ),
    base_image_suffix: str = typer.Option(
        "slim-bookworm",
        "--suffix",
        help="Suffix for the python base image (e.g., slim-bookworm, alpine)."
    ),
    entrypoint_path: str = typer.Option(
        ...,
        "--entrypoint",
        "-e",
        help="Python import path to the FastAPI app (e.g., my_agent.main:app)."
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port the application will listen on inside the container."
    ),
    requirements_path: Optional[Path] = typer.Option(
        None,
        "--requirements",
        "-r",
        help="Path to the requirements.txt file (optional, defaults to './requirements.txt' relative to CWD).",
        exists=True, # Typer handles error if specified path doesn't exist
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    app_dir: str = typer.Option(
        "/app",
        "--app-dir",
        help="Directory inside the container where the application code will reside."
    ),
    # --- ADDED: agent-card argument ---
    agent_card_path: Optional[Path] = typer.Option(
        None,
        "--agent-card",
        "-c",
        help="Path to the agent-card.json file (optional, will be copied if provided).",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    )
    # --- END ADDED ---
):
    """
    Generates a Dockerfile, .dockerignore, and copies requirements/agent-card
    for packaging an AgentVault agent.
    """
    typer.echo(f"Starting Dockerfile generation for entrypoint '{entrypoint_path}'...")
    logger.info(f"Generating Dockerfile in output directory: {output_dir}")

    # --- Requirements File Handling ---
    source_req_path: Optional[Path] = None
    req_file_in_dockerfile = "requirements.txt" # Name used inside Dockerfile

    if requirements_path:
        source_req_path = requirements_path
        typer.echo(f"Using specified requirements file: {source_req_path}")
    else:
        default_req_path = Path("./requirements.txt").resolve()
        if default_req_path.is_file():
            source_req_path = default_req_path
            typer.echo(f"Using default requirements file: {source_req_path}")
        else:
            typer.echo(
                "Warning: Default './requirements.txt' not found. Docker build might fail if dependencies are needed."
            )
            logger.warning("Default requirements.txt not found, skipping copy.")

    # --- Ensure output directory exists ---
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Ensured output directory exists: {output_dir}")
    except OSError as e:
        typer.secho(f"Error creating output directory '{output_dir}': {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # --- Copy requirements file if source exists ---
    if source_req_path:
        dest_req_path = output_dir / req_file_in_dockerfile
        try:
            req_content = source_req_path.read_text(encoding="utf-8")
            if "agentvault-server-sdk" not in req_content and "agentvault " not in req_content: # Basic check
                 typer.echo(
                    f"Warning: '{source_req_path.name}' does not appear to include 'agentvault-server-sdk' or 'agentvault'. Ensure your agent's dependencies are listed."
                 )
                 logger.warning(f"SDK dependency possibly missing from {source_req_path}")

            shutil.copyfile(source_req_path, dest_req_path)
            typer.echo(f"Copied requirements file to: {dest_req_path}")
            logger.info(f"Copied {source_req_path} to {dest_req_path}")
        except Exception as e:
            typer.secho(f"Error copying requirements file from '{source_req_path}' to '{dest_req_path}': {e}", fg=typer.colors.RED)
            logger.exception(f"Failed to copy requirements file.")
            raise typer.Exit(code=1)

    # --- ADDED: Copy agent card if provided ---
    if agent_card_path:
        dest_card_path = output_dir / agent_card_path.name # Use original filename
        try:
            shutil.copyfile(agent_card_path, dest_card_path)
            typer.echo(f"Copied agent card file to: {dest_card_path}")
            logger.info(f"Copied {agent_card_path} to {dest_card_path}")
            # TODO: Add logic later to potentially *use* the card data during packaging?
        except Exception as e:
            typer.secho(f"Error copying agent card file from '{agent_card_path}' to '{dest_card_path}': {e}", fg=typer.colors.YELLOW)
            logger.warning(f"Failed to copy agent card file: {e}", exc_info=True)
            # Non-fatal, just warn if card copy fails
    # --- END ADDED ---


    # --- Dockerfile Generation ---
    python_version_tag = f"{python_version}-{base_image_suffix}"
    python_major_minor = ".".join(python_version.split('.')[:2])

    context = {
        "PYTHON_VERSION_TAG": python_version_tag,
        "APP_DIR": app_dir,
        "REQUIREMENTS_FILE": req_file_in_dockerfile,
        "ENTRYPOINT_MODULE_PATH": entrypoint_path,
        "PORT": str(port),
        "PYTHON_MAJOR_MINOR": python_major_minor,
    }

    try:
        dockerfile_content = DOCKERFILE_TEMPLATE.format(**context)
        logger.debug("Dockerfile template rendered successfully.")
    except KeyError as e:
        typer.secho(f"Error: Missing key in Dockerfile template context: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(f"Error rendering Dockerfile template: {e}", fg=typer.colors.RED)
        logger.exception("Dockerfile template rendering failed.")
        raise typer.Exit(code=1)

    dockerfile_path = output_dir / "Dockerfile"
    try:
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        typer.secho(f"Successfully generated Dockerfile: {dockerfile_path}", fg=typer.colors.GREEN)
    except IOError as e:
        typer.secho(f"Error writing Dockerfile to '{dockerfile_path}': {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # --- .dockerignore Generation ---
    dockerignore_path = output_dir / ".dockerignore"
    try:
        dockerignore_path.write_text(DOCKERIGNORE_CONTENT, encoding="utf-8")
        typer.echo(f"Successfully generated .dockerignore: {dockerignore_path}")
        logger.info(f"Generated .dockerignore at {dockerignore_path}")
    except IOError as e:
        typer.secho(f"Error writing .dockerignore to '{dockerignore_path}': {e}", fg=typer.colors.YELLOW)
        logger.warning(f"Failed to write .dockerignore file: {e}", exc_info=True)

    # TODO: Add optional docker build step (Task 2.2.A.7)


# ─────────────────────────────────────────────────────────────────────────────
# ZKP-enabled Dockerfile template extension
# Inserted just before the CMD line when --enable-zkp is passed.
# Copies nargo + bb from the registry-a image (pinned: 1.0.0-beta.3 / 0.82.2)
# so agent provers are version-locked to the same toolchain as the verifier.
# ─────────────────────────────────────────────────────────────────────────────

_ZKP_DOCKERFILE_SNIPPET = """
# ── ZKP Toolchain (TheProtocol self-attestation) ────────────────────────────
# Copies nargo and bb from the registry-a image.
# Version-locked to match the verifier: Nargo 1.0.0-beta.3 + bb 0.82.2
# The circuit source files (.nr) and compiled ACIR (.bin) are downloaded at
# runtime via GET /api/v1/circuits/{circuit_id}/source and /acir.
COPY --from=agentvault_registry_a:latest /usr/local/bin/nargo /usr/local/bin/nargo
COPY --from=agentvault_registry_a:latest /usr/local/bin/bb    /usr/local/bin/bb
RUN chmod +x /usr/local/bin/nargo /usr/local/bin/bb
# Circuit cache directory (ZKPAttestationClient downloads here on first run)
RUN mkdir -p /var/lib/zkp_circuits && chown appuser:appgroup /var/lib/zkp_circuits
# ─────────────────────────────────────────────────────────────────────────────
"""


@app.command()
def package_agent_zkp(
    output_dir: Path = typer.Option(
        ..., "--output-dir", "-o",
        help="Directory to write Dockerfile and other artifacts.",
        file_okay=False, dir_okay=True, writable=True, resolve_path=True,
    ),
    python_version: str = typer.Option("3.11", "--python"),
    base_image_suffix: str = typer.Option("slim-bookworm", "--suffix"),
    entrypoint_path: str = typer.Option(..., "--entrypoint", "-e"),
    port: int = typer.Option(8000, "--port", "-p"),
    requirements_path: Optional[Path] = typer.Option(
        None, "--requirements", "-r",
        exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True,
    ),
    app_dir: str = typer.Option("/app", "--app-dir"),
    agent_card_path: Optional[Path] = typer.Option(
        None, "--agent-card", "-c",
        exists=True, file_okay=True, dir_okay=False, readable=True, resolve_path=True,
    ),
):
    """
    Like package-agent but injects the ZKP toolchain (nargo + bb) into the
    generated Dockerfile.

    The resulting image can use ZKPAttestationClient for self-attestation.
    Requires that the agentvault_registry_a:latest image is present in the
    local Docker daemon when the agent image is built (COPY --from).
    """
    typer.echo("[ZKP] Generating ZKP-enabled Dockerfile ...")

    # Re-use the standard packager logic by forwarding to package_agent
    # We capture the Dockerfile it would write and inject the ZKP snippet.
    ensure_output_dir(output_dir)

    python_version_tag = f"{python_version}-{base_image_suffix}"
    python_major_minor = ".".join(python_version.split(".")[:2])

    context = {
        "PYTHON_VERSION_TAG": python_version_tag,
        "APP_DIR": app_dir,
        "REQUIREMENTS_FILE": "requirements.txt",
        "ENTRYPOINT_MODULE_PATH": entrypoint_path,
        "PORT": str(port),
        "PYTHON_MAJOR_MINOR": python_major_minor,
    }

    # Build base Dockerfile then inject ZKP snippet before CMD line
    base_dockerfile = DOCKERFILE_TEMPLATE.format(**context)
    cmd_line = f'CMD ["uvicorn", "{entrypoint_path}", "--host", "0.0.0.0", "--port", "{port}"]'
    zkp_dockerfile = base_dockerfile.replace(
        cmd_line,
        _ZKP_DOCKERFILE_SNIPPET.rstrip() + "\n" + cmd_line,
    )

    dockerfile_path = output_dir / "Dockerfile.zkp"
    dockerfile_path.write_text(zkp_dockerfile, encoding="utf-8")
    typer.secho(f"[ZKP] Generated Dockerfile.zkp: {dockerfile_path}", fg=typer.colors.GREEN)
    typer.echo("[ZKP] Build with: docker build -f Dockerfile.zkp -t your-agent:latest .")


def ensure_output_dir(output_dir: Path) -> None:
    """Ensure output directory exists."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        typer.secho(f"Error creating output directory '{output_dir}': {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
