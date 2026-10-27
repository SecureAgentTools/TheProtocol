FROM python:3.14-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 agentvault

# Set working directory
WORKDIR /app

# Copy requirements and the constraints that pin everything they pull in
# §DEPS (2026-09-27): constraints.txt is the built image's own `pip freeze --all`, so a rebuild installs exactly
# the set the last one did (the registry's §TESTBED P0 b pattern). Before it, every rebuild floated the TEG's
# indirect dependencies, and FastAPI's open-ended starlette range would have let a new starlette in unseen.
COPY requirements.txt constraints.txt ./

# pip, setuptools and wheel first, to the versions the constraints name (the base image ships older ones)
RUN pip install --no-cache-dir -c constraints.txt --upgrade pip setuptools wheel

# Install dependencies
RUN pip install --no-cache-dir -c constraints.txt -r requirements.txt

# Process supervisor: run the Uvicorn ASGI workers under gunicorn's arbiter
# instead of uvicorn's self-supervisor (avoids the hardcoded-5s-ping respawn storm
# under CPU oversubscription). See gunicorn_conf.py. Kept as a dedicated layer so
# it survives requirements.txt edits.
# §DEPS (2026-09-27): uvicorn moves to 0.54 with the rest of the set, so uvicorn-worker follows to 0.4.0 (it needs
# uvicorn >= 0.36). Until V0473 both were held (0.30.0 / 0.2.0) to keep the ASGI server byte-identical across the
# move to gunicorn; that move is long proven.
RUN pip install --no-cache-dir -c constraints.txt gunicorn==26.2.0 uvicorn-worker==0.4.0

# pip check must be CLEAN: a conflict fails the build the day a constraint drifts
RUN pip check > /tmp/pipcheck.txt 2>&1; \
    if grep -vxF -e "No broken requirements found." /tmp/pipcheck.txt; then \
      echo "pip check reports a conflict (above)"; exit 1; fi; \
    rm -f /tmp/pipcheck.txt

# Copy application code
COPY . .
# §MONEY-M3a (R32): belt and braces to .dockerignore — the image never carries an env file.
RUN rm -f /app/.env /app/.env.enhanced /app/.env.local

# Change ownership to non-root user
RUN chown -R agentvault:agentvault /app

# Switch to non-root user
USER agentvault

# Add label for SPIRE workload attestation
LABEL com.agentvault.service="teg-core"
# OCI image labels (REVIEW_2026-09-30_LICENSING.md, A2): scanners read the licence here, and source + revision tie the
# image to the exact code it was built from. The build passes VCS_REF and IMAGE_VERSION; "unknown" means it did not.
ARG VCS_REF=unknown
ARG IMAGE_VERSION=unknown
LABEL org.opencontainers.image.title="TheProtocol TEG layer" \
      org.opencontainers.image.description="The token exchange gateway of a TheProtocol frame: balances, transfers and settlement." \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/SecureAgentTools/TheProtocol" \
      org.opencontainers.image.url="https://theprotocol.cloud" \
      org.opencontainers.image.vendor="Raphael Zbigniew Jeziorny" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

# Expose the internal port
EXPOSE 8080

# Add health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=40s --retries=3 \
  CMD curl -f --max-time 25 http://localhost:8080/health || exit 1

# Run the service using uvicorn on port 8080
# Use shell form to ensure environment variables are expanded
CMD ["sh", "-c", "cd /app && python -m uvicorn src.teg_core_service.main:app --host 0.0.0.0 --port 8080"]

