#!/bin/bash
# =============================================================================
# Regenerate the v2.0.0 circuit artifacts (maintainers only)
# =============================================================================
# Toolchain: nargo 1.0.0-beta.3, bb 0.82.2 (the pair in the registry image).
#
# For each v2.0.0 circuit (or the ones named as arguments), in a temporary
# copy of the circuit so no target/ directory is left in the registry:
#   1. nargo test     the circuit's own tests must pass
#   2. nargo compile  -> circuit.json (debug_symbols and file_map removed)
#   3. bb write_vk    -> verification_key.bin
#   4. metadata.json  Artifacts.verification_key_sha256 updated
#   5. nargo execute + bb prove + bb verify on the example Prover.toml
#
# Usage (inside the registry image, or anywhere nargo and bb are installed):
#   bash agentvault_circuit_registry/generate_zkp_keys.sh
#   bash agentvault_circuit_registry/generate_zkp_keys.sh fairMarkupPolicy accurateResourceUsagePolicy
#   docker run --rm --network none --user 0 -v "$PWD/agentvault_circuit_registry:/app/agentvault_circuit_registry" \
#       --entrypoint bash agentvault2-registry-a:v0609 /app/agentvault_circuit_registry/generate_zkp_keys.sh
#
# bb reads its reference string from $HOME/.bb-crs (BB_HOME overrides HOME for
# bb) and downloads whatever is missing. Without network access it needs
# bn254_g1.dat (8,193 points cover all four circuits), bn254_g2.dat, and for
# proving grumpkin_g1.dat with grumpkin_size (65,537 points). crs/ in this
# directory holds all of them: copy them into $BB_HOME/.bb-crs (or
# $HOME/.bb-crs) and the script runs with no network.
#
# NEW KEYS NEED NEW TEST FIXTURES. When the script reports a changed
# verification key, every proof made under the old key stops verifying:
# regenerate agentvault_registry/tests/fixtures/zkp_v2_proofs.json (one real
# proof per circuit, with its public inputs and commitment) and run
# agentvault_registry/tests/test_zkp_v2.py before committing. Attestations
# already stored keep their old proofs; re-verifying them under a new key fails.
# =============================================================================

set -euo pipefail

REGISTRY_DIR="${CIRCUIT_REGISTRY_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
POLICY_DIR="${REGISTRY_DIR}/policies"
BB_ENV_HOME="${BB_HOME:-${HOME}}"

ALL_CIRCUITS=(
    fairMarkupPolicy
    accurateResourceUsagePolicy
    fairCrossRegistryFee
    contentSafetyAttestation
)
if [ "$#" -gt 0 ]; then
    CIRCUITS=("$@")
else
    CIRCUITS=("${ALL_CIRCUITS[@]}")
fi

for tool in nargo bb python3; do
    if ! command -v "$tool" > /dev/null 2>&1; then
        echo "ERROR: $tool not found" >&2
        exit 1
    fi
done
echo "nargo: $(nargo --version | head -1)"
echo "bb:    $(bb --version)"
echo "registry: ${REGISTRY_DIR}"
echo ""

WORK_ROOT="$(mktemp -d)"
trap 'rm -rf "${WORK_ROOT}"' EXIT

CHANGED=()

for NAME in "${CIRCUITS[@]}"; do
    CIRCUIT_DIR="${POLICY_DIR}/${NAME}/v2.0.0"
    echo "------------------------------------------------------------"
    echo " ${NAME}/v2.0.0"
    echo "------------------------------------------------------------"
    for f in Nargo.toml Prover.toml src/main.nr metadata.json; do
        if [ ! -f "${CIRCUIT_DIR}/${f}" ]; then
            echo "ERROR: ${CIRCUIT_DIR}/${f} not found" >&2
            exit 1
        fi
    done
    PACKAGE="$(sed -n 's/^name *= *"\(.*\)"/\1/p' "${CIRCUIT_DIR}/Nargo.toml" | head -1)"

    WORK="${WORK_ROOT}/${NAME}"
    mkdir -p "${WORK}/src"
    cp "${CIRCUIT_DIR}/Nargo.toml" "${CIRCUIT_DIR}/Prover.toml" "${WORK}/"
    cp "${CIRCUIT_DIR}/src/main.nr" "${WORK}/src/"
    cd "${WORK}"

    echo "  [1/5] nargo test"
    nargo test > "${WORK}/test.log" 2>&1 || { cat "${WORK}/test.log" >&2; exit 1; }
    tail -1 "${WORK}/test.log"

    echo "  [2/5] nargo compile -> circuit.json"
    nargo compile > /dev/null
    python3 - "${WORK}/target/${PACKAGE}.json" "${WORK}/circuit.json" "${WORK}/${PACKAGE}.bin" <<'PYEOF'
import base64, json, sys
compiled, out, bytecode = sys.argv[1:4]
artifact = json.load(open(compiled))
for key in ("debug_symbols", "file_map"):
    artifact.pop(key, None)
with open(out, "w") as f:
    json.dump(artifact, f, separators=(",", ":"))
with open(bytecode, "wb") as f:
    f.write(base64.b64decode(artifact["bytecode"]))
PYEOF

    echo "  [3/5] bb write_vk -> verification_key.bin"
    mkdir -p "${WORK}/vk_out"
    HOME="${BB_ENV_HOME}" bb write_vk -s ultra_honk -b "${WORK}/${PACKAGE}.bin" -o "${WORK}/vk_out" > /dev/null
    VK_SIZE="$(stat -c%s "${WORK}/vk_out/vk")"
    if [ "${VK_SIZE}" -lt 512 ]; then
        echo "ERROR: verification key is only ${VK_SIZE} bytes" >&2
        exit 1
    fi

    echo "  [4/5] prove and verify the example Prover.toml"
    nargo execute witness > /dev/null
    mkdir -p "${WORK}/proof_out"
    HOME="${BB_ENV_HOME}" bb prove -s ultra_honk -b "${WORK}/${PACKAGE}.bin" \
        -w "${WORK}/target/witness.gz" -o "${WORK}/proof_out" > /dev/null
    HOME="${BB_ENV_HOME}" bb verify -s ultra_honk -k "${WORK}/vk_out/vk" -p "${WORK}/proof_out/proof" > /dev/null
    echo "        example proof verifies"

    echo "  [5/5] write circuit.json, verification_key.bin, metadata.json"
    cp "${WORK}/circuit.json" "${CIRCUIT_DIR}/circuit.json"
    # bb 0.82.2 does not write the same key twice: bytes 33-96 hold the
    # pairing-point accumulator's public-input indices, which are unused when
    # byte 32 (has an accumulator) is 0 and are left uninitialised. A new key
    # that differs from the shipped one only there is the same key: the shipped
    # file is kept, so its pinned digest stays valid.
    STATUS="$(python3 - "${CIRCUIT_DIR}/metadata.json" "${CIRCUIT_DIR}/verification_key.bin" "${WORK}/vk_out/vk" <<'PYEOF'
import hashlib, json, os, shutil, sys
meta_path, shipped_path, new_path = sys.argv[1:4]
new = open(new_path, "rb").read()
old = open(shipped_path, "rb").read() if os.path.exists(shipped_path) else b""
same = (
    len(old) == len(new) and len(new) > 97 and old[32] == 0 and new[32] == 0
    and old[:33] == new[:33] and old[97:] == new[97:]
)
if not same:
    shutil.copyfile(new_path, shipped_path)
meta = json.load(open(meta_path))
digest = hashlib.sha256(open(shipped_path, "rb").read()).hexdigest()
pinned = meta.setdefault("Artifacts", {}).get("verification_key_sha256")
meta["Artifacts"]["verification_key_sha256"] = digest
with open(meta_path, "w") as f:
    f.write(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
print("unchanged" if same and pinned == digest else "CHANGED")
PYEOF
)"
    HOME="${BB_ENV_HOME}" bb verify -s ultra_honk -k "${CIRCUIT_DIR}/verification_key.bin" \
        -p "${WORK}/proof_out/proof" > /dev/null
    echo "        verification key ${STATUS} (${VK_SIZE} bytes); the example proof verifies under the written key"
    if [ "${STATUS}" = "CHANGED" ]; then
        CHANGED+=("${NAME}/v2.0.0")
    fi
    cd "${REGISTRY_DIR}"
    echo ""
done

echo "============================================================"
if [ "${#CHANGED[@]}" -gt 0 ]; then
    echo " Verification keys CHANGED: ${CHANGED[*]}"
    echo " Regenerate agentvault_registry/tests/fixtures/zkp_v2_proofs.json for these"
    echo " circuits and run agentvault_registry/tests/test_zkp_v2.py before committing."
else
    echo " Every verification key is unchanged."
fi
echo "============================================================"
