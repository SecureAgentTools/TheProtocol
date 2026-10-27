# AgentVault Circuit Registry

The zero-knowledge circuits a registry verifies attestations against: Noir
source, the compiled circuit, its verification key, its metadata and policy
defaults, and the reference string `bb` needs. This is not a service. The
registry image copies the directory to `/app/agentvault_circuit_registry`
(`CIRCUIT_REGISTRY_PATH` overrides the location), where three parts of the
registry read it:

- `core/zkp_verifier.py` verifies every proof submitted to
  `POST /api/v1/attestations/submit` and re-verifies stored ones
  (`GET /api/v1/attestations/{id}/verify`);
- the circuits API (`/api/v1/circuits/...`) serves each circuit's bytecode,
  source, `Nargo.toml`, verification key and metadata, so a prover can build
  a proof and anyone can check one offline;
- the tutorial prover (`POST /api/v1/admin/tutorial/generate-proof`) proves
  any of the four v2.0.0 circuits with fixed example figures, for the agent
  named in its required `agent_did`.

Toolchain: Noir (`nargo`) 1.0.0-beta.3 and Barretenberg (`bb`) 0.82.2, the
pair installed in the registry image. Proving system: UltraHonk. UltraHonk
needs no per-circuit trusted setup; it uses the universal reference string of
the Aztec Ignition ceremony (see [The reference string](#the-reference-string)).

## Layout

```
agentvault_circuit_registry/
├── README.md
├── LICENSE
├── generate_zkp_keys.sh            regenerates the v2.0.0 artifacts (maintainers)
├── crs/
│   ├── bn254_g1.dat                first 8,193 BN254 G1 points (Aztec Ignition)
│   ├── bn254_g2.dat                the G2 point
│   ├── grumpkin_g1.dat             65,537 Grumpkin points (bb loads them before proving)
│   └── grumpkin_size               the Grumpkin point count
├── policies/
│   ├── fairMarkupPolicy/
│   │   ├── v2.0.0/                 active
│   │   │   ├── Nargo.toml          package fair_markup
│   │   │   ├── Prover.toml         example inputs (the regeneration script proves them)
│   │   │   ├── src/main.nr         the circuit and its Noir tests
│   │   │   ├── circuit.json        compiled circuit (ACIR bytecode and ABI)
│   │   │   ├── verification_key.bin
│   │   │   └── metadata.json       statement, inputs, output, policy default, key digest
│   │   └── v1.0.0/                 retired, kept to re-read old attestations
│   ├── accurateResourceUsagePolicy/  (same shape, package accurate_resource_usage)
│   ├── fairCrossRegistryFee/         (same shape, package fair_cross_registry_fee)
│   └── contentSafetyAttestation/     (same shape, package content_safety_attestation)
└── circuits/
    └── proof_of_reputation/v1.0/circuit.json   a description, not a circuit
```

`circuit.json`, `verification_key.bin` and `metadata.json` are tracked, so a
clean checkout (and every image built from one) carries everything the
verifier and the circuits API read. `metadata.json` records the key's SHA-256
(`Artifacts.verification_key_sha256`); the verifier refuses to use a key that
does not match it.

## The four v2.0.0 circuits

Every v2.0.0 circuit takes its policy limit as a **public** input, names what
the proof is about with a non-zero public reference, and outputs one public
Field: a Poseidon2 commitment (with a per-circuit domain tag and a random
salt) to the private figures. A circuit id is `<name>/v2.0.0`. Limits are in
basis points (1 bps = 0.01 %).

The reference (`context`, `transaction_ref` or `window_ref`) also names the
agent. The registry requires it to equal `derive_reference(agent_did, label)`
(`core/zkp_verifier.py`): the first 31 bytes of
`SHA-256("tp.attestation.ref.v1|" + agent DID + "|" + label)`, read as a
big-endian integer. The label (1 to 200 characters) names the offer,
transaction or window, for example a quote id, and is stated with the
submission as `public_inputs.reference_label`. A proof made for one agent
cannot be submitted by another.

| Circuit | Public inputs | Private inputs | Public output | Statement | Policy default |
|---|---|---|---|---|---|
| `fairMarkupPolicy/v2.0.0` | `max_markup_bps` (u32), `offered_price` (u64), `context` (Field, the offer) | `total_cost` (u64), `salt` | `cost_commitment` = H(DOMAIN, total_cost, salt) | `offered_price * 10000 <= total_cost * (10000 + max_markup_bps)` | `max_markup_bps` at most 3000 |
| `accurateResourceUsagePolicy/v2.0.0` | `max_discrepancy_bps` (u32), `transaction_ref` (Field), `reported_units` (u64) | `logged_units` (u64), `salt` | `log_commitment` = H(DOMAIN, transaction_ref, logged_units, salt) | `abs(reported_units - logged_units) * 10000 <= logged_units * max_discrepancy_bps` | `max_discrepancy_bps` at most 100 |
| `fairCrossRegistryFee/v2.0.0` | `max_fee_bps` (u32), `window_ref` (Field), `total_volume` (u64), `total_fees` (u64) | `amounts[16]`, `fees[16]` (u64, unused slots zero), `salt` | `batch_commitment` = H(DOMAIN, window_ref, salt, amounts[0], fees[0], ...) | for every transfer `fees[i] * 10000 <= amounts[i] * max_fee_bps`; `sum(amounts) == total_volume`; `sum(fees) == total_fees` | `max_fee_bps` at most 50 |
| `contentSafetyAttestation/v2.0.0` | `min_rejection_bps` (u32), `window_ref` (Field), `total_samples` (u32, 1 to 64) | `sample_hashes[64]` (Field), `rejected[64]` (bool), `salt` | `log_commitment` = H(DOMAIN, window_ref, total_samples, salt, sample_hash[0], rejected[0], ...) | `rejected * 10000 >= total_samples * min_rejection_bps`; every sample in the window has a hash; unused slots are empty and not rejected | `min_rejection_bps` at least 9000 |

Circuit sizes (gates): fairMarkupPolicy 2,944; accurateResourceUsagePolicy
3,026; fairCrossRegistryFee 4,503; contentSafetyAttestation 7,511.

### What a v2.0.0 proof shows, and what it does not

A verified proof shows that the prover knows private figures that satisfy the
statement under the stated public inputs, that the policy limit in the proof
is the one the registry accepted, that the proof is about the stated offer,
transaction or window, and that the prover is bound to the figures behind the
output commitment.

It does **not** show that the private figures are true. A cost, a meter log
or a moderation log is whatever the prover put in. The commitment is what
makes the figures checkable afterwards: an auditor can ask the prover to open
it (reveal the figures and the salt), and a meter can publish a log
commitment when the work runs, which a verifier then compares with the one in
the proof. No proof here shows which model made a moderation decision.

## How the registry verifies a proof

A submission is `{circuit_id, proof_data: {"proof_bytes": "<base64 of the bb
proof file>", "format": "ultra_honk"}, public_inputs: {...}}`, with every
public input stated by its ABI name as a decimal or `0x` string. The
verifier, in order:

1. reads the public values the proof carries. A `bb` 0.82.2 proof file starts
   with a 4-byte big-endian count of 32-byte field elements, then the public
   inputs in ABI order, then the circuit's public output, then the proof
   proper;
2. refuses any stated public input that differs from the value the proof was
   made for (a missing one is refused too; the output commitment may be
   stated and is compared the same way);
3. refuses a policy limit looser than this registry's policy (`at_most`: the
   proof's limit must not be above the registry's; `at_least`: not below);
4. compares any values the calling code requires (`expected`). The submit
   and re-verify endpoints require the reference to be
   `derive_reference(<submitting agent's DID>, reference_label)`: submit
   answers HTTP 422 without a `reference_label`, and `failed` (the reference
   was made for another agent or another label) when it does not match. Any
   other value, such as a commitment a meter published, a relying party
   compares itself;
5. checks the verification key against its digest, then runs
   `bb verify -s ultra_honk -k verification_key.bin -p <proof>`.

Every element of the proof must also be a canonical field element (below
the BN254 field order), or the proof is refused. The answer is `verified`
only when all five pass; otherwise it is `failed`
with the reason, and the public values the proof carries are reported either
way.

## Policy defaults and `ZKP_POLICY_JSON`

The default limit of each circuit is its `metadata.json` `Policy` entry
(`{"rule": "at_most" | "at_least", "default": <bps>}`). A registry sets its
own limits with the environment variable `ZKP_POLICY_JSON`, a JSON object
keyed by circuit name or by full circuit id, the id winning over the name:

```
ZKP_POLICY_JSON='{"fairMarkupPolicy": {"max_markup_bps": 2500}, "contentSafetyAttestation/v2.0.0": {"min_rejection_bps": 9500}}'
```

If the variable is set but cannot be read, verification fails closed (status
`error`) rather than falling back to the defaults. The limits in force are
published: `GET /api/v1/circuits/` lists them per circuit and
`GET /api/v1/circuits/{id}/metadata` adds them as `policy_in_force`.

## Proving

The recipe the tutorial prover follows, which any prover can repeat with the
public files:

1. Fetch `src/main.nr` and `Nargo.toml` (`GET /api/v1/circuits/{id}/source`,
   `/nargo-toml`) into a Nargo project.
2. Write `Prover.toml` with every public and private input, a random salt
   (the tutorial prover draws 248 bits) and the reference
   `derive_reference(<agent DID>, <label>)` for the agent that will submit
   (the tutorial prover draws a random label).
3. `nargo execute witness` writes `target/witness.gz`.
4. The bytecode is the base64-decoded `"bytecode"` of
   `target/<package>.json` written to a `.bin` file (or
   `GET /api/v1/circuits/{id}/acir`).
5. `mkdir <out>` then
   `bb prove -s ultra_honk -b <bytecode.bin> -w target/witness.gz -o <out>`;
   the proof is `<out>/proof`.

Submit its base64 with the public inputs and `reference_label`, from that
agent. While the registry keeps attestation rows (`ZKP_PHASE_1_ENABLED`), it
accepts one verified attestation per circuit and reference, and per proof
bytes: a second answers HTTP 409, so every attestation needs a fresh proof
with a new label (and a fresh salt). With persistence off nothing is stored
and no replay is refused.

To check a proof offline, fetch the key from `GET /api/v1/circuits/{id}/vk`
and run `bb verify -s ultra_honk -k <vk> -p <proof>`.

## The reference string

`bb` reads its reference string from `$HOME/.bb-crs` and downloads whatever is
missing. `crs/` ships the first 8,193 BN254 G1 points and the G2 point of the
Aztec Ignition setup, and the 65,537-point Grumpkin file (`grumpkin_g1.dat`
with `grumpkin_size`) that `bb prove` loads before proving.
`core/zkp_verifier.py` pins all four files by SHA-256 and writes them to the
`HOME` it gives `bb`. With them:

- the registry verifies any of these proofs without reaching the network
  (without a reference string `bb` 0.82.2 has nothing to verify against and
  exits on a segmentation fault);
- the registry proves all four circuits without reaching the network: the
  BN254 points suffice for circuits of up to 8,192 gates, and the largest
  here, contentSafetyAttestation, has 7,511.

A prover elsewhere can copy these files into its own `$HOME/.bb-crs` and
prove offline too.

## Regenerating the artifacts

`generate_zkp_keys.sh` regenerates the v2.0.0 artifacts, for all four
circuits or the ones named as arguments, in a temporary copy so no `target/`
directory is left behind: it runs the circuit's Noir tests, compiles
`circuit.json`, writes `verification_key.bin`, updates the key digest in
`metadata.json`, and proves and verifies the example `Prover.toml`. Run it
where `nargo` and `bb` are installed, for example in the registry image; the
script's header lists the reference-string files it needs without network
access.

A changed verification key invalidates every proof made under the old one:
regenerate `agentvault_registry/tests/fixtures/zkp_v2_proofs.json` and run
`agentvault_registry/tests/test_zkp_v2.py` before committing. Stored
attestations keep their old proofs, and re-verifying them under a new key
fails.

## Retired: the v1.0.0 circuits

`fairMarkupPolicy/v1.0.0`, `accurateResourceUsagePolicy/v1.0.0`,
`fairCrossRegistryFee/v1.0.0` and `contentSafetyAttestation/v1.0.0` took
their policy limits (markup cap, usage tolerance, fee cap, rejection count)
as private inputs that nothing bound, and the registry did not compare stated
public inputs with the proof. A v1 proof therefore says nothing about the
policy it names. The verifier refuses v1 ids as retired unless the registry
sets `ZKP_ACCEPT_V1_CIRCUITS=true` (kept only to re-read old attestations);
the circuits API lists them as `retired` with `superseded_by` and serves no
key or metadata for them; a schedule for a v1 id is refused.

## Not a circuit: `proof_of_reputation`

`circuits/proof_of_reputation/v1.0/circuit.json` describes an intended
circuit; there is no Noir source and no key, and no code reads the file. A
submission under `proof_of_reputation/v1.0` (or `ProofOfGoodReputation`) is
checked for its inputs only and reported as `not_a_proof`: the submit answer
is `failed` and the attestation is never counted as verified. Check an
agent's reputation against the registry instead.

## Security notes

- The circuits have Noir tests (`nargo test`) and the registry has tests with
  real proofs (`agentvault_registry/tests/test_zkp_v2.py`); they have not been
  formally audited.
- Figures are integers (prices, units and fees in the smallest unit; limits in
  basis points); products are taken in u128, so they cannot overflow.
- The commitments are Poseidon2 hashes with a per-circuit domain tag. They
  hide the figures only as well as the salt is random: use a fresh random
  salt for every proof.
