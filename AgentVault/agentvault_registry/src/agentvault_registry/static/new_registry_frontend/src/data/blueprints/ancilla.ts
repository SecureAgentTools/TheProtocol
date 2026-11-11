import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ANCILLA: the AI services around a quantum computer (V0660 (f), his seq 2570-2574). An ancilla is the
// helper qubit error correction leans on, which is what these agents are to a machine they do not own.
//
// Two general patterns, not one vendor's product: a DECODING agent (error syndromes in, corrections out)
// and a CALIBRATION assistant (device measurements in, a tuned summary out). Open decoders a provider may
// run include NVIDIA Ising, PyMatching and Chromobius; this chamber compares none of them and recommends
// none. His binding line holds throughout: TheProtocol never hosts the model or the agent. The provider
// runs the workload on its own hardware, or calls a model hosted by whoever hosts it, and what the
// network carries is the identity, the authority, the money and the evidence.

const primitives = [
  { step: 'The decoder is an agent with its own card', primitive: 'Quantum workload card extension, role compiler or mitigator, with its as_of', railStatus: 'LIVE (gated)' as const },
  { step: 'Syndromes in, corrections out, per batch', primitive: 'A2A task with a receipt: input digest, model id, version, duration', railStatus: 'LIVE' as const },
  { step: 'The buyer replays the corrections itself', primitive: 'Acceptance rung 1: the answer is checked against the syndromes it was given', railStatus: 'LIVE' as const },
  { step: 'Paid per batch, exactly once', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'The decoder holds no budget', primitive: 'IRONKEY deny-by-default: it answers batches and spends nothing', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Units reported match a committed meter log', primitive: 'accurateResourceUsagePolicy/v2.0.0, a published circuit with its verification key', railStatus: 'LIVE' as const, href: '/docs/10' },
  { step: 'The ledger keeps digests, never the syndromes', primitive: 'Immutable ledger of digests and verdicts; the data stays the provider’s', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'A named operator behind the service', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'A disputed batch, ruled on', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
  { step: 'Syndromes from a device that is really running', primitive: 'A provider’s own hardware, producing the measurements these agents read', railStatus: 'DESIGNED' as const },
  { step: 'Calibration that means something', primitive: 'A tuned summary over real device measurements rather than a simulator’s', railStatus: 'DESIGNED' as const },
  { step: 'Correction inside the cycle, beside the hardware', primitive: 'A microsecond loop at the device; deliberately never a network service', railStatus: 'DESIGNED' as const },
]

export const ancilla: Blueprint = {
  id: 'ancilla',
  tier: 2,
  frontier: true,
  rank: 33,
  industry: 'AI Services Around a Quantum Computer',
  systemName: 'ANCILLA',
  promise: 'Decoding and calibration sold as agent services with receipts, where the model and the machine stay with whoever owns them.',
  cases: [
    { role: 'Error-correction researcher', line: 'Sell batch decoding as a service instead of as a paper and a repository.' },
    { role: 'Quantum hardware operator', line: 'Buy decoding and calibration help without handing anyone your device.' },
    { role: 'AI infrastructure provider', line: 'Your hosted model answers batches under a named mandate, with evidence per call.' },
    { role: 'Consortium technical lead', line: 'One record of which decoder ran which batch, at which version.' },
  ],
  problem:
    'The useful AI around a quantum computer is already classical and already exists: decoders that turn error syndromes into corrections, and assistants that turn a device’s measurements into a usable calibration. What is missing is the commercial plumbing. The work is bought by email, the model version behind an answer is remembered rather than recorded, and nobody can show afterwards which decoder produced which correction.',
  system: [
    'ANCILLA is a decoding and calibration market: a hardware group in Delft that runs a device and wants help reading it, a research group in Sydney that maintains a decoder, and an infrastructure provider whose GPUs host the model the Sydney group uses. Nothing about that arrangement changes. The decoder runs where the Sydney group runs it, the model runs where its host runs it, and the device stays in Delft. What the network adds is that each batch is a paid task with a receipt.',
    'A batch goes out as a task: a digest of the syndromes, the decoder’s own id and version, the units it expects to spend. The decoder answers with corrections and signs what it did. The Delft group replays the corrections against the syndromes it sent, which is a classical check it can run itself, and the escrow opens on that check rather than on the answer arriving. A second decoder can be sent the same batch, and both answers land in the record under their own keys.',
    'The honest line runs straight through the middle of this chamber. The agent service is live: identity, mandate, task, receipt, metering, payment, dispute. The things that make decoding and calibration matter are not. Real syndromes come from a device that is really running, a calibration summary means something only over real measurements, and the correction loop that keeps a computation alive sits beside the hardware in microseconds, which is deliberately not a network service and never will be. Those three are marked DESIGNED, and this page carries no comparison between decoders and no claim about what any of them achieves.',
  ],
  cast: [
    { agent: 'decode-service', role: 'Answers syndrome batches with corrections', ceiling: 'Answers batches and spends nothing. Its model runs where its host runs it, never on the network.' },
    { agent: 'calib-service', role: 'Turns device measurements into a tuned summary', ceiling: 'Reads what a device reports. Does not drive the device and signs no run of its own.' },
    { agent: 'device-desk', role: 'Sends the batches, replays the corrections', ceiling: 'The Delft group’s sub-agent, with no wallet of its own, under a mandate that is re-derived per request.' },
    { agent: 'model-host', role: 'Runs the model the decoder calls', ceiling: 'A counterparty like any other. Holds no agent identity of the protocol’s and takes no part in settlement.' },
  ],
  loom: {
    nodes: [
      { id: 'operator', label: 'Dr van Dijk', sub: 'the mandate, one tap', kind: 'human', x: 118, y: 110 },
      { id: 'desk', label: 'device-desk', sub: 'sends the batches', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Batch gate', sub: 'scope, units, caps', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Batch escrow', sub: 'opens on your check', kind: 'teg', x: 560, y: 110 },
      { id: 'decoder', label: 'decode-service', sub: 'signs each batch', kind: 'agent', x: 560, y: 330 },
      { id: 'host', label: 'model host', sub: 'runs the model', kind: 'external', x: 336, y: 450 },
      { id: 'ledger', label: 'Batch ledger', sub: 'digests and versions', kind: 'ledger', x: 764, y: 110 },
      { id: 'calib', label: 'calib-service', sub: 'reads the device', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-mandate', from: 'operator', to: 'gate', label: 'scope, signed' },
      { id: 'e-send', from: 'desk', to: 'gate', label: 'syndrome batch', labelT: 0.3 },
      { id: 'e-escrow', from: 'gate', to: 'escrow', label: 'escrowed per batch' },
      { id: 'e-host', from: 'gate', to: 'host', label: 'the model, elsewhere' },
      { id: 'e-answer', from: 'decoder', to: 'escrow', label: 'corrections', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-calib', from: 'calib', to: 'ledger', label: 'summary, dated' },
      { id: 'a-noversion', from: 'desk', to: 'gate', attackOnly: true, curve: 70, labelT: 0.5, label: 'no version' },
      { id: 'a-rebill', from: 'decoder', to: 'escrow', attackOnly: true, curve: 90, labelT: 0.3, label: 'same batch' },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Dr van Dijk underwrites the desk once: a budget, the services it may call, a quarter.' },
      { edge: 'e-send', state: 'active', dwellMs: 1400, caption: 'A batch goes out as a task: the syndromes’ digest and the units it expects to spend.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'Each batch is escrowed. Nothing opens on corrections arriving.' },
      { edge: 'e-host', state: 'active', dwellMs: 1300, caption: 'The model runs where its host runs it. The protocol hosts neither the model nor the agent.' },
      { edge: 'e-answer', state: 'active', dwellMs: 1500, caption: 'The decoder signs what it did: the input digest, its own id and version, the duration.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The group replays the corrections itself, and a passing batch releases exactly once.' },
      { edge: 'e-calib', state: 'active', dwellMs: 1500, caption: 'A calibration summary lands dated to the measurements it was read from.' },
    ],
  },
  attacks: [
    {
      title: 'The answer with no version behind it',
      attack: 'A decoder returns corrections without naming the model and version that produced them, so a later disagreement has nothing to point at.',
      mechanism: 'The task’s acceptance template names what a receipt carries, and the gate sits in front of the escrow. A receipt without the decoder’s id and version fails the template before the check is reached, and the escrow stays shut.',
      rail: 'S16',
      consequence: 'Nothing is paid and nothing is reversed. The missing version is what the record shows.',
      script: [
        { edge: 'a-noversion', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S16. The task says what a receipt must name. One without it never reaches the check.' },
      ],
    },
    {
      title: 'The batch billed twice',
      attack: 'A decoder re-sends corrections for a batch it has already been paid for, after a crash on its side.',
      mechanism: 'Each batch is its own milestone and releases once, under a key made from the task and the batch. The meter keeps one entry per batch, so a second answer for the same batch finds the entry committed and nothing left to release.',
      rail: 'S15',
      consequence: 'One batch, one payment, whatever the retries. The duplicate is visible, not profitable.',
      script: [
        { edge: 'a-rebill', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'escrow', caption: 'S15. This batch’s key was already paid. A retry or a replay moves the money exactly once.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [{ label: 'AI System Lifecycle', href: '/compliance/doc/ai-system-lifecycle' }],
  rails: ['S01', 'S02', 'S05', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'A group frame, or each service on a frame of its own, federated, booted from the free licence and pre-built images. Quantum workloads are one frame switch, off by default.',
    agents: 'A device desk, a decoding service, a calibration service. The decoder, the model and the device all stay with whoever owns them.',
    integration: 'The device’s control stack, the syndrome pipeline and the model host’s own API. This is where the real time goes, and it stays the group’s.',
  },
  nonClaims: [
    'ANCILLA carries identity, authority, money and evidence for classical services around a quantum computer. It does not decode, calibrate, or judge whether a correction is right.',
    'TheProtocol hosts no model and no agent. A decoder runs where its owner runs it, a hosted model runs on its host’s hardware, and a model’s own licence is checked by whoever uses it.',
    'Open decoders a provider may run include NVIDIA Ising, PyMatching and Chromobius. This chamber compares none of them, recommends none, and makes no claim about what any of them achieves.',
    'A live error-correction loop is not a network service. It sits beside the hardware in microseconds, and the batch decoding sold here is a different thing that cannot replace it.',
    'Calibration over a simulator is a demonstration. A summary means something over a real device’s measurements, which is why that step is marked DESIGNED rather than live.',
  ],
  mermaid: `flowchart LR
  V(["Dr van Dijk<br/>mandate"]) -->|"scope"| G{"batch gate<br/>scope, units, caps"}
  D["device-desk"] -->|"syndrome batch"| G
  G -->|"escrowed per batch"| E["batch escrow"]
  G -->|"model, elsewhere"| H["model host"]
  S["decode-service"] -->|"corrections, signed"| E
  E --> L[("batch ledger<br/>digests and versions")]
  C["calib-service"] -->|"summary, dated"| L`,
  legacy: [
    { system: 'The device control stack', connect: 'It keeps the device. A batch carries a digest of the syndromes, never the device’s control.' },
    { system: 'Existing decoders and their repositories', connect: 'They run as they do today, behind an agent that signs what it ran and at which version.' },
    { system: 'Hosted model APIs', connect: 'The host stays a counterparty. The agent calling it is the one the network knows.' },
    { system: 'Grant accounting', connect: 'Batches settle on the rails under the mandate; finance reads settlement instead of chasing invoices.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
