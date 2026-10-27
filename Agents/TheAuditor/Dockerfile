# §DEPS 2c (2026-09-29): Python 3.14.7 by digest; every dependency pinned by the shared constraints
# (Agents/_constraints/py314.txt, the compose's additional build context "constraints"), wheels only.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY src/auditor/requirements.txt ./requirements.txt
COPY --from=constraints py314.txt /tmp/py314.txt
RUN pip install --no-cache-dir --only-binary=:all: -c /tmp/py314.txt -r requirements.txt
COPY src/ ./src/
COPY frontend/ ./frontend/
RUN mkdir -p /app/data /app/frontend
EXPOSE 8045
CMD ["uvicorn", "src.auditor.main:app", "--host", "0.0.0.0", "--port", "8045", "--log-level", "info"]

# OCI image labels (REVIEW_2026-09-30_LICENSING.md): the licence scanners read, and where the source is
LABEL org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/SecureAgentTools/TheProtocol" \
      org.opencontainers.image.url="https://theprotocol.cloud"
