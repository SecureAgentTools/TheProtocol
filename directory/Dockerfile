# THE DIRECTORY (trial, §DIDWIDEN-1 item 5 / his option C) — a read-only, signed-feed index with GraphQL on top.
# Built FROM the registry image so it reuses the ONE signature verifier, the ONE card-extension readers and the ONE DID
# parser instead of re-implementing them (his rule: one rule at the source). It never writes to a registry.
# §SOVKIT T4 (2026-09-14): BASE_IMAGE has NO default. The old default named `agentvault2-registry-a:dirfeed`, a tag
# that no longer existed, and a tag is a moving name anyway. Point a tag of your own at the registry image id whose
# code the index must verify cards with (`docker tag <id> agentvault2-registry-a:dirbase-<id12>`) and pass it:
# `--build-arg BASE_IMAGE=agentvault2-registry-a:dirbase-<id12>`. A build without the arg fails at FROM, loudly.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
RUN pip install --no-cache-dir "strawberry-graphql[fastapi]==0.327.3" && mkdir -p /data && chown agentvault:agentvault /data
COPY --chmod=644 directory /app/directory
RUN chmod 755 /app/directory
ENV PYTHONPATH=/app/src:/app
USER agentvault
EXPOSE 8600
ENTRYPOINT []
CMD ["uvicorn", "directory.app:app", "--host", "0.0.0.0", "--port", "8600"]

# OCI image labels (REVIEW_2026-09-30_LICENSING.md): the licence scanners read, and where the source is
LABEL org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/SecureAgentTools/TheProtocol" \
      org.opencontainers.image.url="https://theprotocol.cloud"
