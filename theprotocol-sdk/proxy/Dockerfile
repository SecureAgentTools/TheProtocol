# SPDX-License-Identifier: Apache-2.0
# TheProtocol Proxy: the tp-proxy command in a small image, for amd64 and arm64 (a server room or a Raspberry Pi).
# Built from theprotocol-sdk/ (the build context), for both platforms:
#   docker buildx build --platform linux/amd64,linux/arm64 -f proxy/Dockerfile -t theprotocol-proxy:dev .
# An evidence export mirrored to SFTP or S3 needs its client in the image: --build-arg EXTRAS=proxy,proxy-sftp,proxy-s3
# `tp-proxy migrate` is in every image; a migration needs the drivers of the systems it reads and writes:
#   --build-arg EXTRAS=proxy,proxy-sql,proxy-sftp   (PostgreSQL, MySQL, SQL Server, SFTP; see compose.migrate.yaml)
ARG EXTRAS=proxy
FROM python:3.12-slim AS build
ARG EXTRAS
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-cache-dir --wheel-dir /wheels ".[${EXTRAS}]"

FROM python:3.12-slim
ARG EXTRAS
RUN useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin tpproxy \
 && mkdir -p /data /config && chown tpproxy:tpproxy /data
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels "theprotocol-sdk[${EXTRAS}]" && rm -rf /wheels
USER tpproxy
WORKDIR /data
# the spec is mounted read-only at /config/proxy.yaml; the outbox and the SVID live in /data (a volume)
ENV TP_PROXY_SPEC=/config/proxy.yaml PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 9108
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9108/health', timeout=4)" || exit 1
ENTRYPOINT ["tp-proxy"]
CMD ["run"]
