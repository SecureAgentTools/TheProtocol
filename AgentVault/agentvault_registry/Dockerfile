# ── Docker CLI (client only) ────────────────────────────────────────────────
# §2026-07-27 — `services/cloud_provisioner.py` shells out to `docker` for THREE
# things during cloud-operator provisioning: `docker compose up -d` (via a
# docker:cli sidecar), the nginx vhost reload, and the stream-SNI map reload
# (both `docker run --privileged alpine nsenter … nginx -s reload`). Its own
# comment asserts "the registry image DOES have `docker` available on $PATH" —
# it did NOT. Measured in BOTH registry-a and a fresh frame registry:
#   /bin/sh: 1: docker: not found
# Because `_run()` only WARNS on failure, provisioning looked like it half-worked:
# the stack dir, vhost and SNI entry were written, but no container ever started
# and nginx was never reloaded, so the operator's public URL stayed dead until
# something else reloaded nginx. Provisioning an operator from a registry UI was
# therefore broken end-to-end; only a host-side `compose up` rescued it.
# Client binary only (it drives the mounted /var/run/docker.sock) — copied from
# the official image so there is no apt repo/key to maintain.
# §DEPS V0494 (2026-09-29): the major pinned (docker:cli floated; the same image today, 29.8.1).
FROM docker:29-cli AS dockercli

FROM python:3.14-slim

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    postgresql-client \
    curl \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ── ZKP: Nargo (Noir compiler) + Barretenberg (bb) for ZKP verification ──
#
# Versions: nargo 1.0.0-beta.3 / bb 0.82.2
# Confirmed compatible pair from bb-versions.json:
#   https://raw.githubusercontent.com/AztecProtocol/aztec-packages/next/barretenberg/bbup/bb-versions.json
#
# URL format (>=0.77.0): v{VERSION}/barretenberg-{amd64|arm64}-{linux|darwin}.tar.gz
# URL format (>=1.0.0-beta.3 nargo): v{VERSION}/nargo-{x86_64|aarch64}-unknown-linux-gnu.tar.gz
#
# Circuits in agentvault_circuit_registry use Noir 1.0.0-beta.3 syntax (updated 2026-03-07).
# If you upgrade these versions, run generate_zkp_keys.sh again to regenerate keys.

ARG NARGO_VERSION=1.0.0-beta.3
ARG BB_VERSION=0.82.2

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
    \
    # ── Install nargo ────────────────────────────────────────────────────
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then NARGO_ARCH="x86_64-unknown-linux-gnu"; \
    elif [ "$ARCH" = "aarch64" ]; then NARGO_ARCH="aarch64-unknown-linux-gnu"; \
    else echo "Unsupported arch: $ARCH" && exit 1; fi && \
    NARGO_URL="https://github.com/noir-lang/noir/releases/download/v${NARGO_VERSION}/nargo-${NARGO_ARCH}.tar.gz" && \
    echo "Installing nargo ${NARGO_VERSION} from ${NARGO_URL}" && \
    curl -fsSL --retry 3 "${NARGO_URL}" | tar -xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/nargo && \
    nargo --version && \
    \
    # ── Install bb ───────────────────────────────────────────────────────
    # >=0.77.0 uses: v{VERSION} tag, amd64/arm64, linux/darwin naming
    BBARCH=$(uname -m) && \
    if [ "$BBARCH" = "x86_64" ]; then BB_ARCH="amd64"; \
    elif [ "$BBARCH" = "aarch64" ]; then BB_ARCH="arm64"; \
    else echo "Unsupported arch: $BBARCH" && exit 1; fi && \
    BB_URL="https://github.com/AztecProtocol/aztec-packages/releases/download/v${BB_VERSION}/barretenberg-${BB_ARCH}-linux.tar.gz" && \
    echo "Installing bb ${BB_VERSION} from ${BB_URL}" && \
    curl -fsSL --retry 3 "${BB_URL}" | tar -xz -C /usr/local/bin && \
    chmod +x /usr/local/bin/bb && \
    bb --version && \
    \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 agentvault

# Set working directory
WORKDIR /app

# Copy project files. §LAYERORDER (2026-09-03): the source tree is NOT copied here — nothing below
# needs it before the final `COPY ./agentvault_registry/ .`, and copying it first invalidated every
# pip layer on every source change (a ten-minute rebuild per canary bake, measured 2026-09-03).
COPY ./agentvault_registry/pyproject.toml ./

# Upgrade pip and setuptools first, to the versions the constraints name (pip, setuptools and wheel are pinned there too)
COPY ./agentvault_registry/constraints-network.txt /tmp/constraints.txt
RUN pip install --no-cache-dir -c /tmp/constraints.txt --upgrade pip setuptools wheel

# Install critical dependencies first
# OWL24: bumped grpcio to satisfy spiffe>=1.78.0 requirement
# §TESTBED P0 b (2026-09-19): every install below resolves against the image's own pip freeze, so a rebuild
# installs exactly what the last one did. The version specs are QUOTED: a bare `pkg>=1.2` in a RUN is a shell
# redirect (the package went in unpinned and pip's output landed in files named /app/=1.2).
RUN pip install --no-cache-dir -c /tmp/constraints.txt \
    "grpcio>=1.78.0" \
    "grpcio-tools>=1.78.0"

# Install spiffe for mTLS support.
# §DEPS (2026-09-27): spiffe 0.3.1 declared cryptography>=46 and pyjwt<2.14; since V0647 spiffe 0.3.2 (pyjwt>=2,<3) and
# PyJWT 2.15.1, with cryptography 50, so spiffe installs WITH its dependency check. (Until V0473 it went in with --no-deps because the registry
# held cryptography at 41.0.7, and every image carried that one known conflict; the pip check below now allows none.)
RUN pip install --no-cache-dir -c /tmp/constraints.txt spiffe cryptography PyJWT

# Install remaining dependencies
# §DEPS (2026-09-27, his words "would be cool if we get everything to the newest stable version that runs with us"):
# the newest stable release of each, resolved together on this base. Held back, each for a reason a gate cannot see:
# stripe 15 (§DEPS stripe15, 2026-09-29) is no longer held: 15.0 made StripeObject a non-dict (no .get()/.items()), so
# the one module that talks to the SDK hands out plain dicts (.to_dict() on the webhook event, the created and the
# retrieved Checkout Session and the refund), and 15.6.1 pins API 2026-08-26.dahlia (was 2025-08-27.basil); the
# clover/dahlia breaking changes touch none of our Session.create kwargs or Refund.create. The fiat lane is off, so
# Stripe's test mode itself is still unproven from here.
# (numpy/scipy/networkx were held at the newest for Python 3.11 until V0479; since then the images run Python 3.14
#  and take their newest releases: numpy 2.5.3, scipy 1.18.1, networkx 3.7.)
# SQLAlchemy 2.1 (§DEPS sqla21, 2026-09-29) is no longer held: 2.1 makes psycopg (3) the driver behind a plain
# postgresql:// URL, and here both drivers are installed, so every SYNC engine names psycopg2 itself
# (core/dsn.sync_engine_url: the migration bridge, alembic offline and online); the async engine names asyncpg.
# §DEPS (2026-09-28): python-jose is gone (JWTs are PyJWT's, the version spiffe needs; jose pulled ecdsa, whose P-256
# timing flaw CVE-2024-23342 will never be fixed upstream, and rsa and six with it). passlib 1.7.4 (unmaintained since
# 2020, it held bcrypt at 4.0.1) is gone; bcrypt 5 is called in
# one place, core/secret_hash.py, with passlib's rules kept byte for byte (a secret's first 72 bytes count; bcrypt 5
# raises past them where bcrypt 4 cut silently, and every agent client secret is 74 bytes).
# ⚠ FastAPI since 0.112 no longer installs python-multipart (it moved to the `fastapi[standard]` extra): without it
# every Form(...) route, the login among them, refuses to even register ("Form data requires python-multipart").
RUN pip install --no-cache-dir -c /tmp/constraints.txt \
    fastapi==0.141.1 \
    python-multipart==0.0.32 \
    "uvicorn[standard]==0.54.0" \
    "sqlalchemy[asyncio]==2.1.1" \
    asyncpg==0.31.0 \
    alembic==1.20.0 \
    pydantic==2.13.5 \
    pydantic-settings==2.15.0 \
    python-dotenv==1.2.3 \
    slowapi==0.1.10 \
    "psycopg[binary]==3.3.6" \
    psycopg2-binary==2.9.13 \
    fastapi-mail==1.6.8 \
    "premailer>=3.10,<4.0" \
    "beautifulsoup4>=4.12,<5.0" \
    aiosmtplib==5.1.3 \
    bcrypt==5.0.0 \
    "redis[hiredis]==8.1.0" \
    cryptography==50.0.1 \
    structlog==26.1.0 \
    prometheus-client==0.26.0 \
    prometheus-fastapi-instrumentator==8.1.0 \
    httpx==0.28.1 \
    aiohttp==3.14.5 \
    pyotp==2.10.0 \
    "qrcode[pil]==8.2" \
    Pillow==13.0.0 \
    docker==7.2.0 \
    psutil==7.2.2 \
    "numpy>=1.24.0" \
    "scipy>=1.10.0" \
    "networkx>=3.0.0" \
    stripe==15.6.1 \
    gunicorn==26.2.0 \
    uvicorn-worker==0.4.0 \
    jsonschema==4.26.0 \
    pywebpush==2.5.0
# ^ CONTRACT SPINE P4 (2026-07-25): contract-template `terms_schema` FORM validation. NOTE the
# image installs from THIS pin list, NOT requirements.txt — adding a dep there alone is a no-op
# (that is exactly how the institutional form shipped with only the presence-only fallback).

# Copy and install the agentvault_library in editable mode (copied HERE, after the pinned pip
# layers, so a library change re-runs only this layer)
COPY ./agentvault_library ./agentvault_library
RUN pip install -c /tmp/constraints.txt -e ./agentvault_library

# Install test dependencies
RUN pip install --no-cache-dir -c /tmp/constraints.txt \
    pytest==9.1.1 \
    pytest-asyncio==1.4.0 \
    pytest-cov==7.1.0 \
    pytest-mock==3.16.0 \
    pytest-json-report==1.5.0 \
    pytest-metadata==3.1.1 \
    Faker==40.40.0 \
    factory-boy==3.3.3

# §TESTBED P0 b (2026-09-19, the gate agentvault2-f5 proposed), tightened by §DEPS (2026-09-27): pip check must be CLEAN.
# The one conflict every image used to carry (spiffe 0.3.1 over cryptography 41.0.7) is gone with cryptography 50, so
# any line other than "No broken requirements found." fails the build the day a constraint drifts.
RUN pip check > /tmp/pipcheck.txt 2>&1; \
    if grep -vxF -e "No broken requirements found." /tmp/pipcheck.txt; then \
      echo "pip check reports a conflict (above)"; exit 1; fi; \
    rm -f /tmp/pipcheck.txt

# Copy the rest of the application
COPY ./agentvault_registry/ .

# §MONEY-R37: belt and braces with .dockerignore, exactly as R32 did for the TEG
# (agentvault_teg_layer_mvp/Dockerfile:34). A .dockerignore rule is one edit away
# from being lost; this line makes the absence a property of the IMAGE rather
# than of the build context.
# Measured before removing: 9 baked keys, 5 not overridden by any container env,
# and all 5 inert — four feed RATE_LIMITS, which has zero consumers, and
# RATE_LIMIT_BYPASS_KEYS parses to empty.
# ⚠ Deliberately NOT a wildcard: config/network_profile.*.env must survive.
RUN rm -f /app/.env /app/.env.local

# ── ZKP: Bake circuit registry into image ───────────────────────────
# This gives every registry container access to circuits even without a volume mount.
# The docker-compose volume mount (./AgentVault/agentvault_circuit_registry) will
# OVERRIDE this at runtime, enabling key updates without a rebuild.
# Note: .bin keys are PLACEHOLDERS until generate_zkp_keys.sh is run inside container.
COPY ./agentvault_circuit_registry /app/agentvault_circuit_registry

# §AGENTDISC (2026-08-16) — /app/data must EXIST in the image with app ownership:
# it is the durable home of the Ed25519 bundle-signing key (attestation_signer),
# and a named volume mounted over a path ABSENT from the image gets a root-owned
# mountpoint the uid-1000 app cannot write (the key then lives in-memory and
# rotates on every restart — the exact defect the volume exists to fix).
RUN mkdir -p /app/data

# Change ownership to non-root user
RUN chown -R agentvault:agentvault /app

# Switch to non-root user
USER agentvault

# Docker CLI — see the `dockercli` stage at the top of this file for WHY.
# Deliberately placed LAST: a COPY near the top invalidates every cached layer
# below it (nargo + barretenberg downloads, apt, pip install), turning a ~1 min
# rebuild into a full one. The binary is statically linked, so an Alpine-built
# client runs fine on this Debian base (verified: `docker --version`, socket
# access, and the privileged `alpine nsenter … nginx -s reload` path all work).
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
# ⚠ AND THE COMPOSE PLUGIN. `docker` alone answers "unknown command: docker compose", and host_work's stack phase
# runs `docker compose up` itself — so the one-shot could bundle and never bring a stack up (agentvault2-6a
# measured it in V0385 as uid 1000). The CLI finds a plugin by this path; copying the binary anywhere else is a
# binary nothing looks for.
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

# Add label for SPIRE workload attestation
LABEL com.agentvault.service="registry-backend"
# OCI image labels (REVIEW_2026-09-30_LICENSING.md, A2): scanners read the licence here, and source + revision tie the
# image to the exact code it was built from. The build passes VCS_REF and IMAGE_VERSION; "unknown" means it did not.
ARG VCS_REF=unknown
ARG IMAGE_VERSION=unknown
LABEL org.opencontainers.image.title="TheProtocol registry" \
      org.opencontainers.image.description="The registry of a TheProtocol frame: identity, agent cards, federation, the economy rails and the console." \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/SecureAgentTools/TheProtocol" \
      org.opencontainers.image.url="https://theprotocol.cloud" \
      org.opencontainers.image.vendor="Raphael Zbigniew Jeziorny" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

# Expose port
EXPOSE 8000

# Default command
# §XFFTRUST: not "*" — that makes uvicorn take the FIRST X-Forwarded-For element,
# which the caller writes. See gunicorn_worker.py. (This CMD is the non-gunicorn
# fallback path; prod runs the RegistryWorker.)
CMD ["uvicorn", "agentvault_registry.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"]
