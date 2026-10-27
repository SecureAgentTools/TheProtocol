#!/bin/bash
# build.sh: build TheProtocol's six application images from this repository, then prove each one boots.
#
#   ./build.sh [--version X] [--registry PREFIX] [--push]
#
# Images: PREFIX/registry, PREFIX/teg-layer, PREFIX/event-store, PREFIX/auditor and PREFIX/directory (the last two are
# the frame kit, §SOVKIT 2026-09-14) and PREFIX/cert-writer (the SVID writer every mTLS terminator of a federated frame
# runs beside it, §HELLOFRAME 2026-09-18), each tagged :VERSION, :latest and :stable (a tree that differs from the
# release it was downloaded as takes :VERSION only, see the provenance block).
# PREFIX is --registry, else $IMAGE_REGISTRY, else "theprotocol": a LOCAL name, so by default nothing is pulled from or
# pushed to anyone's image registry. docker-compose.standalone.yml defaults to the same prefix and to :stable, so
#
#   ./build.sh && docker compose -f docker-compose.standalone.yml --env-file .env.operator up -d
#
# runs exactly what was just built. --push needs an explicit --registry (or IMAGE_REGISTRY) you are logged in to.
#
# The registry image builds the web frontend itself (stage `frontend` in Dockerfile.registry.dist), so Docker with
# BuildKit is the only requirement (the default builder since Docker 23). Extra flags for every `docker build` can be
# passed in DOCKER_BUILD_FLAGS, for example DOCKER_BUILD_FLAGS="--cgroup-parent=ci.slice".
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

PUSH=false
VERSION=""
REGISTRY="${IMAGE_REGISTRY:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --push)     PUSH=true; shift ;;
        --version)  VERSION="$2"; shift 2 ;;
        --registry) REGISTRY="$2"; shift 2 ;;
        *)          echo "Unknown argument: $1"; exit 1 ;;
    esac
done
if $PUSH && [[ -z "${REGISTRY}" ]]; then
    echo "ERROR: --push needs --registry <host/namespace> (or IMAGE_REGISTRY). The default prefix is a local name."
    exit 1
fi
REGISTRY="${REGISTRY:-theprotocol}"
VERSION="${VERSION:-$(cat "${SCRIPT_DIR}/VERSION" 2>/dev/null || echo 'dev')}"
read -r -a EXTRA_FLAGS <<< "${DOCKER_BUILD_FLAGS:-}"

export DOCKER_BUILDKIT=1
if ! docker buildx version >/dev/null 2>&1; then
    echo "WARNING: docker buildx (BuildKit) was not found. The registry build needs its Dockerfile-specific"
    echo "         .dockerignore; the classic builder would hide the frontend source and stage 'frontend' would fail."
fi

echo "============================================"
echo "  TheProtocol Distribution Build"
echo "  Images:  ${REGISTRY}/{registry,teg-layer,event-store,auditor,directory,cert-writer}:${VERSION}"
echo "  Push:    ${PUSH}"
echo "============================================"
echo ""

cd "${PROJECT_ROOT}"
# §TESTBED P5 (2026-09-19): what this build was built FROM (kit_provenance.py): the tree's digest, and whether and how
# much it differs from the release it came from (KIT_FILES.sha256). Every image carries it as labels; the registry also
# as /app/BUILD_INFO.json, which /health shows, so a report can say which code a run measured.
BUILD_INFO_FILE="${PROJECT_ROOT}/dist/build-info.json"
python3 "${SCRIPT_DIR}/kit_provenance.py" --root "${PROJECT_ROOT}" --version "${VERSION}" --out "${BUILD_INFO_FILE}" >/dev/null
bi() { python3 -c 'import json,sys; v=json.load(open(sys.argv[1])).get(sys.argv[2]); print("unknown" if v is None else str(v).lower())' "${BUILD_INFO_FILE}" "$1"; }
KIT_TREE="$(bi tree_digest)"; KIT_MODIFIED="$(bi modified)"; KIT_CHANGED="$(bi changed_files)"
# OCI labels (REVIEW_2026-09-30_LICENSING.md): licence scanners read org.opencontainers.image.licenses, and source +
# revision tie each image to the exact code it was built from (the export's own commit, when the tree is a git checkout).
KIT_REVISION="$(git -C "${PROJECT_ROOT}" rev-parse HEAD 2>/dev/null || echo unknown)"
PROV_LABELS=(--label "org.theprotocol.kit.version=${VERSION}" --label "org.theprotocol.kit.tree=${KIT_TREE}"
             --label "org.theprotocol.kit.modified=${KIT_MODIFIED}" --label "org.theprotocol.kit.changed_files=${KIT_CHANGED}"
             --label "org.opencontainers.image.source=https://github.com/SecureAgentTools/TheProtocol"
             --label "org.opencontainers.image.url=https://theprotocol.cloud"
             --label "org.opencontainers.image.version=${VERSION}" --label "org.opencontainers.image.revision=${KIT_REVISION}")
AGPL_LABEL=(--label "org.opencontainers.image.licenses=AGPL-3.0-or-later")
echo "Provenance: tree ${KIT_TREE:0:16}, modified=${KIT_MODIFIED}, changed files ${KIT_CHANGED} (dist/build-info.json)"
# A CHANGED kit tree builds under its own version only: :latest and :stable are the release's tags, and
# docker-compose.standalone.yml runs :stable, so a contributor's experiment must never become what a restart runs.
if [ "${KIT_MODIFIED}" = "true" ]; then
    RELEASE_TAGS=()
    echo "This tree differs from the release (${KIT_CHANGED} changed files): the images take only :${VERSION}; :latest and :stable stay where they are"
else
    RELEASE_TAGS=(latest stable)
fi
echo ""

build_image() {  # build_image <name> <dockerfile> <context> [extra docker build flags, e.g. --build-arg K=V]
    local name="$1" dockerfile="$2" context="$3"; shift 3
    echo "Building ${REGISTRY}/${name}:${VERSION} (context ${context})"
    local tags=(-t "${REGISTRY}/${name}:${VERSION}") t
    for t in ${RELEASE_TAGS[@]+"${RELEASE_TAGS[@]}"}; do tags+=(-t "${REGISTRY}/${name}:${t}"); done
    docker build ${EXTRA_FLAGS[@]+"${EXTRA_FLAGS[@]}"} "${PROV_LABELS[@]}" "$@" -f "${dockerfile}" "${tags[@]}" \
        "${context}"
    echo "  Done: ${REGISTRY}/${name}:${VERSION}"
    echo ""
}

# boot_gate <name> <route floor> <docker run arguments...>
# The image must import its application and mount at least <floor> routes. The dummy settings prove the import
# chain inside the image's own dependency set, not a configuration.
boot_gate() {
    local name="$1" floor="$2"; shift 2
    local out routes
    out=$(docker run --rm "$@" 2>&1) || true
    routes=$(printf '%s\n' "${out}" | grep -E '^routes=[0-9]+$' | tail -1 | cut -d= -f2 || true)
    if [[ -z "${routes}" || "${routes}" -lt "${floor}" ]]; then
        printf '%s\n' "${out}" | tail -20
        echo "FATAL: ${name} did not boot (routes=${routes:-none}, floor ${floor})"
        exit 1
    fi
    echo "  boot gate ${name}: routes=${routes} (floor ${floor})"
}

echo "[1/6] registry"
build_image registry scripts/distribution/Dockerfile.registry.dist ./AgentVault "${AGPL_LABEL[@]}" \
    --build-arg "KIT_BUILD_INFO_B64=$(base64 -w0 < "${BUILD_INFO_FILE}")"
echo "[2/6] teg-layer"
build_image teg-layer scripts/distribution/Dockerfile.teg.dist ./AgentVault/agentvault_teg_layer_mvp "${AGPL_LABEL[@]}"
echo "[3/6] event-store"
build_image event-store scripts/distribution/Dockerfile.eventstore.dist ./agentvault-event-store "${AGPL_LABEL[@]}"
# §SOVKIT: the frame kit. The solo auditor is an independent verifier of the ledger's supply invariant (delta 0); the
# Directory is the frame's own federated index and is built FROM the registry image just built, so it verifies card
# signatures with the same code the federation uses (its Dockerfile takes BASE_IMAGE with no default, on purpose).
echo "[4/6] auditor"
# §DEPS: the auditor takes its Python 3.14 pins from a second build context (Agents/_constraints/py314.txt)
# the auditor is Apache-2.0 (Agents/TheAuditor/LICENSE)
build_image auditor Agents/TheAuditor/Dockerfile ./Agents/TheAuditor --build-context "constraints=./Agents/_constraints" \
    --label "org.opencontainers.image.licenses=Apache-2.0"
echo "[5/6] directory"
build_image directory directory/Dockerfile ./directory "${AGPL_LABEL[@]}" --build-arg "BASE_IMAGE=${REGISTRY}/registry:${VERSION}"
# §HELLOFRAME: the cert-writer fetches each sidecar's X.509 SVID from the SPIRE Workload API and writes it for nginx;
# a federated frame runs six of them (three mTLS terminators, the kit, the directory, the data identity).
echo "[6/6] cert-writer"
build_image cert-writer nginx/Dockerfile.cert-writer ./nginx "${AGPL_LABEL[@]}"

echo "Boot gates"
# §DEPS (2026-09-27): FastAPI 0.14x keeps an included router as ONE lazy entry in app.routes (the registry reads 226
# there, not its 1432 routes), so each gate counts through fastapi.routing.iter_route_contexts where it exists and falls
# back to len(app.routes) on an older FastAPI (measured: V0473 len 1432 = V0474 flattened 1432). The floors are unchanged.
boot_gate registry 1000 -w /app -e PYTHONPATH=/app/src \
    -e DATABASE_URL='postgresql+asyncpg://build:build@localhost:5432/build' -e API_KEY_SECRET=build-dummy-secret \
    --entrypoint python "${REGISTRY}/registry:${VERSION}" \
    -c 'import agentvault_registry.main as m, fastapi.routing as fr; rs = m.app.routes; print("routes=%d" % (sum(1 for _ in fr.iter_route_contexts(rs)) if hasattr(fr, "iter_route_contexts") else len(rs)))'
boot_gate teg-layer 100 -w /app \
    -e DATABASE_URL='postgresql+asyncpg://build:build@localhost:5432/build' \
    -e AVTP_SYSTEM_API_KEY=build-dummy-0123456789abcdef0123456789abcdef \
    -e TEG_TOKEN_SIGNING_KEY=build-dummy-0123456789abcdef0123456789abcdef \
    --entrypoint python "${REGISTRY}/teg-layer:${VERSION}" \
    -c 'import src.teg_core_service.main as m, fastapi.routing as fr; rs = m.app.routes; print("routes=%d" % (sum(1 for _ in fr.iter_route_contexts(rs)) if hasattr(fr, "iter_route_contexts") else len(rs)))'
boot_gate event-store 40 -w /app \
    -e DATABASE_URL='postgresql+asyncpg://build:build@localhost:5432/build' -e INTERNAL_API_KEY=build-dummy-secret \
    --entrypoint python "${REGISTRY}/event-store:${VERSION}" \
    -c 'import src.main as m, fastapi.routing as fr; rs = m.app.routes; print("routes=%d" % (sum(1 for _ in fr.iter_route_contexts(rs)) if hasattr(fr, "iter_route_contexts") else len(rs)))'
boot_gate auditor 20 -w /app -e AUDITOR_SOLO=true -e AUDITOR_EXTRA_FRAMES_JSON='[]' -e EVENT_STORE_URL=http://build-dummy:8200 \
    --entrypoint python "${REGISTRY}/auditor:${VERSION}" \
    -c 'import src.auditor.main as m, fastapi.routing as fr; rs = m.app.routes; print("routes=%d" % (sum(1 for _ in fr.iter_route_contexts(rs)) if hasattr(fr, "iter_route_contexts") else len(rs)))'
boot_gate directory 5 -w /app -e DIRECTORY_ANCHORS=http://build-dummy:8000 -e DIRECTORY_DB=/tmp/build.db \
    -e DATABASE_URL='postgresql+asyncpg://build:build@localhost:5432/build' -e API_KEY_SECRET=build-dummy-secret \
    -e DIRECTORY_READERS=spiffe://build.invalid/service/registry \
    -e DIRECTORY_PROXY_TRUST_SECRET=build-dummy-0123456789abcdef0123456789abcdef \
    --entrypoint python "${REGISTRY}/directory:${VERSION}" \
    -c 'import directory.app as m, fastapi.routing as fr; rs = m.app.routes; print("routes=%d" % (sum(1 for _ in fr.iter_route_contexts(rs)) if hasattr(fr, "iter_route_contexts") else len(rs)))'
# the cert-writer has no app to import: its gate is the script parsing and the spire-agent binary answering
cw_out=$(docker run --rm --entrypoint sh "${REGISTRY}/cert-writer:${VERSION}" -c 'sh -n /opt/cert-writer.sh && /opt/spire/bin/spire-agent --version' 2>&1) || true
if ! printf '%s\n' "${cw_out}" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
    printf '%s\n' "${cw_out}" | tail -5
    echo "FATAL: cert-writer did not boot (the script does not parse or spire-agent does not answer)"
    exit 1
fi
echo "  boot gate cert-writer: script parses, spire-agent $(printf '%s\n' "${cw_out}" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
# the registry's /app/data holds its durable signing key: it must exist in the image and be the app user's, or a named
# volume mounted there is root-owned and the key lives per worker (Dockerfile.registry.dist says why)
dd_out=$(docker run --rm --entrypoint sh "${REGISTRY}/registry:${VERSION}" -c \
    'test -d /app/data && test "$(stat -c %u /app/data)" = "$(id -u)" && test -w /app/data && echo data-dir-ok' 2>&1) || true
if ! printf '%s\n' "${dd_out}" | grep -qx 'data-dir-ok'; then
    printf '%s\n' "${dd_out}" | tail -3
    echo "FATAL: the registry image has no /app/data owned by its user (the signing key could not persist)"
    exit 1
fi
echo "  boot gate registry data dir: /app/data exists and is the app user's"
echo ""

# The licence scan and SBOM of what was just built (REVIEW_2026-09-30_LICENSING.md): one CycloneDX file per image plus
# the frontend's lockfile, and a summary. It stops the build when a component's licence cannot ship under the AGPL;
# components that need a person's look (REVIEW, e.g. elkjs, which the frontend stubs out) are listed, never passed silently.
echo "Licence scan and SBOM"
SBOM_ARGS=()
for name in registry teg-layer event-store auditor directory cert-writer; do SBOM_ARGS+=(--image "${REGISTRY}/${name}:${VERSION}"); done
python3 "${SCRIPT_DIR}/sbom.py" "${SBOM_ARGS[@]}" \
    --lockfile "${PROJECT_ROOT}/AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/package-lock.json" \
    --out "${PROJECT_ROOT}/dist/sbom" || { echo "FATAL: the licence scan found a component that cannot ship (dist/sbom)"; exit 1; }
echo ""

if $PUSH; then
    echo "Pushing to ${REGISTRY}..."
    for name in registry teg-layer event-store auditor directory cert-writer; do
        for tag in "${VERSION}" ${RELEASE_TAGS[@]+"${RELEASE_TAGS[@]}"}; do
            docker push "${REGISTRY}/${name}:${tag}"
        done
    done
    echo "  Push complete."
    echo ""
fi

# Package the operator kit: the standalone stack and its setup. A FEDERATED operator's stack is the bundle its frame
# provisions (nginx-templates: the compose, the env generator, the terminators' confs, with the frame's SPIRE material);
# the older docker-compose.operator.yml this package carried was retired (CB-112, CB-227: no nginx-teg, no proxy marker).
echo "Creating operator bundle..."
DIST_DIR="${PROJECT_ROOT}/dist"
BUNDLE_DIR="${DIST_DIR}/theprotocol-operator-${VERSION}"

rm -rf "${BUNDLE_DIR}"
mkdir -p "${BUNDLE_DIR}"

cp "${SCRIPT_DIR}/docker-compose.standalone.yml" "${BUNDLE_DIR}/"
cp "${SCRIPT_DIR}/docker-compose.monitoring.yml" "${BUNDLE_DIR}/"
cp "${SCRIPT_DIR}/generate-operator-env.sh" "${BUNDLE_DIR}/"
cp "${SCRIPT_DIR}/operator-setup.sh" "${BUNDLE_DIR}/"
echo "${VERSION}" > "${BUNDLE_DIR}/VERSION"

chmod +x "${BUNDLE_DIR}/generate-operator-env.sh"
chmod +x "${BUNDLE_DIR}/operator-setup.sh"

tar -czf "${DIST_DIR}/theprotocol-operator-${VERSION}.tar.gz" \
    -C "${DIST_DIR}" "theprotocol-operator-${VERSION}"

echo ""
echo "============================================"
echo "  Build complete"
echo "  Images:"
echo "    ${REGISTRY}/registry:${VERSION}"
echo "    ${REGISTRY}/teg-layer:${VERSION}"
echo "    ${REGISTRY}/event-store:${VERSION}"
echo "    ${REGISTRY}/auditor:${VERSION}"
echo "    ${REGISTRY}/directory:${VERSION}"
echo "    ${REGISTRY}/cert-writer:${VERSION}"
echo "  Bundle:"
echo "    ${DIST_DIR}/theprotocol-operator-${VERSION}.tar.gz"
echo "============================================"
