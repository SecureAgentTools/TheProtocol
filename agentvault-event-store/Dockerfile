FROM python:3.14-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and the constraints that pin everything they pull in
# §DEPS (2026-09-27): constraints.txt is the built image's own `pip freeze --all`, so a rebuild installs exactly the
# set the last one did (the registry's §TESTBED P0 b pattern); before it, every rebuild floated the ledger's
# indirect dependencies.
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -c constraints.txt -r requirements.txt

# pip check must be CLEAN: a conflict fails the build the day a constraint drifts
RUN pip check > /tmp/pipcheck.txt 2>&1; \
    if grep -vxF -e "No broken requirements found." /tmp/pipcheck.txt; then \
      echo "pip check reports a conflict (above)"; exit 1; fi; \
    rm -f /tmp/pipcheck.txt

# Copy application
COPY . .

# Run the application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8200"]

# OCI image labels (REVIEW_2026-09-30_LICENSING.md): the licence scanners read, and where the source is
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/SecureAgentTools/TheProtocol" \
      org.opencontainers.image.url="https://theprotocol.cloud"
