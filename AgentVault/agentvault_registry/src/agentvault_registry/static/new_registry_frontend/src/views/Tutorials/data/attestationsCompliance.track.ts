import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 11: Attestations & Compliance — Real ZKP proof generation & verification
 *
 * 11 steps:
 * AUTH (1): Developer JWT
 * ONBOARD (2-5): Bootstrap → Create → Token → Fund
 * CIRCUITS (6): List available circuits
 * ZKP FAIR MARKUP (7-8): Generate proof → Submit attestation (verified!)
 * ZKP RESOURCE USAGE (9-10): Generate proof → Submit attestation (verified!)
 * REVIEW (11): Check reputation (should have +2 from verified attestations)
 *
 * This track uses REAL UltraHonk proof generation (Noir + Barretenberg) and verification.
 * Proofs are generated server-side (nargo execute + bb prove) and submitted to
 * the registry's /attestations/submit endpoint, which compares the stated public
 * inputs with the proof's own, checks the policy limit, then runs bb verify.
 *
 * Circuits (v2.0.0; the v1.0.0 circuits are retired):
 * - fairMarkupPolicy/v2.0.0: offered_price * 10000 <= total_cost * (10000 + max_markup_bps)
 * - accurateResourceUsagePolicy/v2.0.0: |reported - logged| * 10000 <= logged * max_discrepancy_bps
 *
 * The generate-proof steps send the agent DID captured at step 3: each proof's
 * reference is derived from that DID and a random label. The submit steps send
 * the circuit_id and public_inputs (reference_label included) the generate-proof
 * step returned (captured), never hard-coded ones, with that agent's token.
 *
 * Endpoint verification:
 * - admin_tutorial.py: POST /admin/tutorial/generate-proof (server-side nargo+bb; agent_did required)
 * - attestations.py: POST /attestations/submit (the reference must name the submitting agent,
 *   binding checks, bb verify, 409 on a proof or a circuit and reference already attested,
 *   reputation +1 for the first verified attestation per agent, circuit and UTC day)
 * - attestations.py: GET /circuits/ (list available circuits)
 * - agent_discovery.py: GET /agents/by-did/{did} (the registry's agent record, reputation_score)
 */
export const attestationsComplianceTrack: TutorialTrack = {
  id: 'attestations-compliance',
  title: 'Attestations & Compliance',
  subtitle: 'Real ZKP proof generation & verification',
  description: 'Generate real UltraHonk zero-knowledge proofs from Noir circuits and submit them for verification. Each proof shows a public policy limit held for a private figure the agent committed to; watch the reputation change as each one verifies.',
  icon: 'clipboard-check',
  color: 'emerald',
  gradientFrom: 'from-emerald-500',
  gradientTo: 'to-green-600',
  estimatedMinutes: 10,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Compliance Officer',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH + ONBOARD — Steps 1-5
    // ═══════════════════════════════════════════════════════
    {
      id: 'ac-authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT',
      explanation: `This track uses **real zero-knowledge proofs**: UltraHonk proofs from Noir circuits, made with Barretenberg on the server. Each proof shows that a public policy limit held for a private figure (a cost, a meter reading) without revealing the figure, and binds the figure to a commitment. You will then submit them for verification.

Let's start by authenticating.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox',
        body: { ...SANDBOX_TUTORIAL_LOGIN },
        authType: 'none'
      },
      captures: [
        { key: 'sandboxDevToken', responsePath: 'access_token', displayLabel: 'Developer JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] }
    },
    {
      id: 'ac-bootstrap',
      stepNumber: 2,
      title: 'Bootstrap Agent',
      subtitle: 'Request bootstrap token',
      explanation: `Get a bootstrap token to create our compliance agent.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Bootstrap token for compliance agent',
        body: { agent_type_hint: 'compliance_agent', requested_by: 'tutorial-attestations' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'bootstrapToken', responsePath: 'bootstrap_token', displayLabel: 'Bootstrap Token', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'ac-authenticate'
    },
    {
      id: 'ac-create-agent',
      stepNumber: 3,
      title: 'Create Compliance Agent',
      subtitle: 'Onboard an agent to submit ZKP attestations',
      explanation: `Create the agent that will generate and submit zero-knowledge proofs.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create compliance agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0', agentVersion: '1.0',
            name: 'ZKP Compliance Auditor',
            description: 'Tutorial agent: generates and submits UltraHonk ZKP attestations',
            url: 'http://localhost:8100/agents/zkp-auditor',
            humanReadableId: 'zkp-auditor',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1', 'avtp'], outbound_protocols: ['cosv1', 'avtp'], tags: ['tutorial', 'compliance', 'zkp', 'barretenberg'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/zkp-auditor' }],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken'
      },
      captures: [
        { key: 'agentDid', responsePath: 'agent_did', displayLabel: 'Agent DID' },
        { key: 'clientId', responsePath: 'client_id', displayLabel: 'Client ID' },
        { key: 'clientSecret', responsePath: 'client_secret', displayLabel: 'Client Secret', sensitive: true }
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did', 'client_id', 'client_secret'] },
      requiresStepId: 'ac-bootstrap'
    },
    {
      id: 'ac-agent-token',
      stepNumber: 4,
      title: 'Get Agent Token',
      subtitle: 'Authenticate as the compliance agent',
      explanation: `Get the agent JWT — needed to submit attestations for verification.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as compliance agent',
        body: { grant_type: 'password', username: '$clientId', password: '$clientSecret' },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'clientId' },
          { jsonPath: 'password', capturedKey: 'clientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        { key: 'agentToken', responsePath: 'access_token', displayLabel: 'Agent JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      requiresStepId: 'ac-create-agent'
    },
    {
      id: 'ac-fund-agent',
      stepNumber: 5,
      title: 'Fund Agent',
      subtitle: 'Give the agent a TEG balance',
      explanation: `Fund the agent so it has a TEG account.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund agent with 200 units',
        body: { target_agent_did: '$agentDid', amount: '200', reason: 'tutorial_grant', reference_id: 'tutorial-ac-fund' },
        bodyDynamic: [{ jsonPath: 'target_agent_did', capturedKey: 'agentDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'ac-agent-token'
    },

    // ═══════════════════════════════════════════════════════
    // CIRCUITS — Step 6
    // ═══════════════════════════════════════════════════════
    {
      id: 'ac-list-circuits',
      stepNumber: 6,
      title: 'List Available Circuits',
      subtitle: 'View the ZKP circuits on the network',
      explanation: `The registry serves its **Noir circuits** at \`/circuits/\`. Four are active, all at **v2.0.0**:

- **fairMarkupPolicy/v2.0.0**: the offered price is at most a committed cost plus the policy's maximum markup
- **accurateResourceUsagePolicy/v2.0.0**: the reported units are within the policy tolerance of a committed meter log
- **fairCrossRegistryFee/v2.0.0**: in a batch of up to 16 transfers every fee is within the policy rate and the totals are as stated
- **contentSafetyAttestation/v2.0.0**: in a log of up to 64 moderated samples, at least the policy share was rejected

Each active circuit lists its **public inputs**, the **commitment** it outputs and the **policy limit** this registry enforces, with links to its ACIR bytecode, Noir source, metadata and **verification key**. The keys are public: anyone can check a proof offline with \`bb verify\`.

The **v1.0.0** circuits are listed as **retired**, each naming its successor. They took their policy limits as private inputs that nothing bound, so a v1 proof said nothing about the policy; the registry refuses them.`,
      apiCall: {
        method: 'GET',
        path: '/circuits/',
        description: 'List all available ZKP circuits',
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'ac-fund-agent',
      notes: 'Look at "policy" on an active circuit: that is the limit a proof must meet on this registry. A retired circuit carries "superseded_by" instead.'
    },

    // ═══════════════════════════════════════════════════════
    // ZKP FAIR MARKUP — Steps 7-8
    // ═══════════════════════════════════════════════════════
    {
      id: 'ac-generate-fair-markup',
      stepNumber: 7,
      title: 'Generate Fair Markup Proof',
      subtitle: 'Run nargo + Barretenberg to create a real ZKP',
      explanation: `This step generates a real **UltraHonk zero-knowledge proof** for the Fair Markup circuit.

**The statement**: \`offered_price * 10000 <= total_cost * (10000 + max_markup_bps)\`
- Public: \`max_markup_bps = 2000\` (a 20% cap), \`offered_price = 720\`, and \`context\`, the reference naming the offer and this agent
- Private: \`total_cost = 600\` and a random \`salt\`
- Check: \`720 * 10000 = 7,200,000 <= 600 * 12,000 = 7,200,000\` ✓
- The circuit outputs \`cost_commitment\`, a Poseidon2 hash of the cost and the salt

**The reference names the agent**: \`context\` is derived from the agent's DID (captured at step 3) and a label, the first 31 bytes of SHA-256 over both. The answer carries the label as \`public_inputs.reference_label\`, and the registry derives the reference again from the DID of the agent that submits: a proof made for this agent is not verified for any other.

**How it runs** (server-side, for the tutorial):
1. \`nargo execute\` computes the witness from the public and private inputs
2. \`bb prove\` creates the proof (about 14 KB)
3. The answer carries the proof (base64), the \`circuit_id\`, the \`public_inputs\` and the commitment

**What it proves, and what it does not**: the cap is public, so a verifier sees which limit was proven and the registry refuses a cap looser than its policy (30% by default). The cost stays private, but it is bound to the commitment: the prover cannot later claim a different cost, and an auditor can ask it to open the commitment. The proof does **not** show that 600 is the real cost.

Here the server proves with demo inputs, so it sees them. A real agent proves in its own process and sends only the proof.`,
      apiCall: {
        method: 'POST',
        path: '/admin/tutorial/generate-proof',
        description: 'Generate an UltraHonk proof for fairMarkupPolicy/v2.0.0',
        body: { circuit_id: 'fairMarkupPolicy/v2.0.0', agent_did: '$agentDid' },
        bodyDynamic: [{ jsonPath: 'agent_did', capturedKey: 'agentDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'fairMarkupProof', responsePath: 'proof_bytes_base64', displayLabel: 'Fair Markup Proof (base64)', sensitive: true },
        { key: 'fairMarkupCircuitId', responsePath: 'circuit_id', displayLabel: 'Circuit' },
        { key: 'fairMarkupInputs', responsePath: 'public_inputs', displayLabel: 'Public Inputs' },
        { key: 'fairMarkupCommitment', responsePath: 'public_outputs.cost_commitment', displayLabel: 'Cost Commitment' },
        { key: 'proofGenTime', responsePath: 'generation_time_ms', displayLabel: 'Generation Time (ms)' }
      ],
      validation: { successStatusCodes: [200] },
      requiresStepId: 'ac-list-circuits',
      notes: 'Proof generated for this agent. The next step submits exactly the circuit_id and public_inputs (reference_label included) this answer returned, with the agent token: the registry compares each stated input with the value inside the proof.'
    },
    {
      id: 'ac-submit-fair-markup',
      stepNumber: 8,
      title: 'Submit Fair Markup Attestation',
      subtitle: 'Cryptographic verification: bb verify',
      explanation: `Submit the proof to the registry. \`/attestations/submit\`:

1. Reads the public values the proof carries and refuses any stated public input that differs
2. Derives the reference from the submitting agent's DID and \`reference_label\`: a proof whose \`context\` names another agent or another label is not verified (without a label the answer is **422**)
3. Refuses a policy limit looser than this registry's policy (here: a markup cap above its maximum)
4. Runs \`bb verify\` against the circuit's verification key
5. Verified: **status = "verified"**, and **reputation +1** for the first verified attestation of this agent, circuit and UTC day
6. Not verified: **status = "failed"**, with a **reason** saying which check failed

The answer also lists \`proof_public_values\`, the inputs and the commitment as the proof carries them.

One verified attestation per circuit and reference: submitting the same proof again, or another proof with the same reference, answers **409**. To attest again, generate a new proof (step 7): it gets a new label.`,
      apiCall: {
        method: 'POST',
        path: '/attestations/submit',
        description: 'Submit fair markup ZKP attestation for verification',
        body: {
          circuit_id: '$fairMarkupCircuitId',
          proof_data: { proof_bytes: '$fairMarkupProof', format: 'ultra_honk' },
          public_inputs: '$fairMarkupInputs'
        },
        bodyDynamic: [
          { jsonPath: 'circuit_id', capturedKey: 'fairMarkupCircuitId' },
          { jsonPath: 'proof_data.proof_bytes', capturedKey: 'fairMarkupProof' },
          { jsonPath: 'public_inputs', capturedKey: 'fairMarkupInputs' }
        ],
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        { key: 'fairMarkupAttestationId', responsePath: 'attestation_id', displayLabel: 'Attestation ID' },
        { key: 'fairMarkupStatus', responsePath: 'status', displayLabel: 'Verification Status' },
        { key: 'fairMarkupRepDelta', responsePath: 'reputation_delta', displayLabel: 'Reputation Delta' },
        { key: 'fairMarkupReason', responsePath: 'reason', displayLabel: 'Reason (when not verified)' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'ac-generate-fair-markup',
      notes: 'Check "status": "verified" means every binding check passed and bb accepted the proof. If it says "failed", "reason" names the check. The agent has proven that its price fits a cost it committed to, under a public 20% cap.'
    },

    // ═══════════════════════════════════════════════════════
    // ZKP RESOURCE USAGE — Steps 9-10
    // ═══════════════════════════════════════════════════════
    {
      id: 'ac-generate-resource-usage',
      stepNumber: 9,
      title: 'Generate Resource Usage Proof',
      subtitle: 'Second ZKP: accurate resource reporting',
      explanation: `A second proof, for the **Accurate Resource Usage** circuit.

**The statement**: \`|reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps\`
- Public: \`max_discrepancy_bps = 100\` (1% tolerance), \`reported_units = 1000\`, and \`transaction_ref\`, the reference naming the transaction and this agent
- Private: \`logged_units = 1000\` and a random \`salt\`
- Check: \`|1000 - 1000| * 10000 = 0 <= 1000 * 100 = 100,000\` ✓
- The circuit outputs \`log_commitment\`, a Poseidon2 hash of the reference, the logged units and the salt

**What it does not prove**: that the log is true. The log is only as trustworthy as whoever publishes its commitment. A meter that publishes \`log_commitment\` when the work runs, deriving \`transaction_ref\` from the agent's DID and the transaction id, lets a verifier compare it with the one in the proof.

Same pipeline: \`nargo execute\` → \`bb prove\` → base64 proof.`,
      apiCall: {
        method: 'POST',
        path: '/admin/tutorial/generate-proof',
        description: 'Generate an UltraHonk proof for accurateResourceUsagePolicy/v2.0.0',
        body: { circuit_id: 'accurateResourceUsagePolicy/v2.0.0', agent_did: '$agentDid' },
        bodyDynamic: [{ jsonPath: 'agent_did', capturedKey: 'agentDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'resourceProof', responsePath: 'proof_bytes_base64', displayLabel: 'Resource Usage Proof (base64)', sensitive: true },
        { key: 'resourceCircuitId', responsePath: 'circuit_id', displayLabel: 'Circuit' },
        { key: 'resourceInputs', responsePath: 'public_inputs', displayLabel: 'Public Inputs' },
        { key: 'resourceCommitment', responsePath: 'public_outputs.log_commitment', displayLabel: 'Log Commitment' }
      ],
      validation: { successStatusCodes: [200] },
      requiresStepId: 'ac-submit-fair-markup',
      notes: 'Second proof generated. The logged units stay private; the log commitment binds the prover to them.'
    },
    {
      id: 'ac-submit-resource-usage',
      stepNumber: 10,
      title: 'Submit Resource Usage Attestation',
      subtitle: 'Second cryptographic verification',
      explanation: `Submit the resource usage proof, with the \`circuit_id\` and \`public_inputs\` (\`reference_label\` included) the previous step returned. The same checks run: stated inputs against the proof, the reference against this agent's DID and the label, the tolerance against this registry's policy (1% by default), then \`bb verify\`.

A different circuit counts separately, so a verified proof here adds another reputation point for today.`,
      apiCall: {
        method: 'POST',
        path: '/attestations/submit',
        description: 'Submit resource usage ZKP attestation for verification',
        body: {
          circuit_id: '$resourceCircuitId',
          proof_data: { proof_bytes: '$resourceProof', format: 'ultra_honk' },
          public_inputs: '$resourceInputs'
        },
        bodyDynamic: [
          { jsonPath: 'circuit_id', capturedKey: 'resourceCircuitId' },
          { jsonPath: 'proof_data.proof_bytes', capturedKey: 'resourceProof' },
          { jsonPath: 'public_inputs', capturedKey: 'resourceInputs' }
        ],
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        { key: 'resourceAttestationId', responsePath: 'attestation_id', displayLabel: 'Attestation ID' },
        { key: 'resourceStatus', responsePath: 'status', displayLabel: 'Verification Status' },
        { key: 'resourceReason', responsePath: 'reason', displayLabel: 'Reason (when not verified)' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'ac-generate-resource-usage',
      notes: 'Two attestations on two policies: a price within a public markup cap over a committed cost, and a usage report within a public tolerance of a committed log.'
    },

    // ═══════════════════════════════════════════════════════
    // REVIEW — Step 11
    // ═══════════════════════════════════════════════════════
    {
      id: 'ac-check-reputation',
      stepNumber: 11,
      title: 'Check Reputation Impact',
      subtitle: 'See the trust added by verified attestations',
      explanation: `The first verified attestation per agent, circuit and UTC day adds **reputation +1**. Two circuits verified today: **+2** for this new agent. More proofs on the same circuit the same day add nothing, and revoking an attestation takes its point back only if it was the one that added it.

The point goes to the registry's own agent record: \`GET /agents/by-did/{did}\` answers it as \`reputation_score\`. (The TEG's \`/teg/agents/{id}/reputation\` is the TEG's own score, which attestations do not change.)

**Done**: you generated real UltraHonk proofs from Noir circuits and had the registry verify them. Each one proves a public policy limit held for a private figure the agent committed to. Whether that figure is true is a separate question, answered by opening the commitment to an auditor or by comparing it with one a meter published.`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/{did}',
        description: "Read the agent's registry record (reputation_score) after the ZKP attestations",
        pathParams: { did: '$agentDid' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'reputationScore', responsePath: 'reputation_score', displayLabel: 'Reputation Score' }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['reputation_score'] },
      requiresStepId: 'ac-submit-resource-usage',
      notes: 'Track complete. Two verified attestations: each one binds a public policy limit and a reference to a committed private figure.'
    }
  ]
}
