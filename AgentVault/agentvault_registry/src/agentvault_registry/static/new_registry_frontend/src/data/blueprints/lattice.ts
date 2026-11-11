import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// LATTICE: chemistry and materials (V0660 (f)). The honest centre of this chamber is ACCEPTANCE: a
// buyer pays for an estimate that passes a test agreed before the run, on a molecule whose answer is
// already known. That makes the sale checkable without anyone claiming what the hardware is worth.

const primitives = [
  { step: 'The test is agreed before the run', primitive: 'Acceptance template on the work order: rung 1 checks the answer', railStatus: 'LIVE' as const },
  { step: 'A hidden reference the seller cannot read', primitive: 'Rung 2: test circuits with stated false-accept and false-reject rates', railStatus: 'LIVE' as const },
  { step: 'Escrow released on the verdict, not the invoice', primitive: 'Contract spine: escrow at order, released per attested milestone', railStatus: 'LIVE' as const },
  { step: 'Each estimate carries what produced it', primitive: 'Receipt chain: circuit digest, backend, calibration snapshot, shots, counts', railStatus: 'LIVE' as const },
  { step: 'Shots reported match a committed meter log', primitive: 'accurateResourceUsagePolicy/v2.0.0, a published circuit with its verification key', railStatus: 'LIVE' as const, href: '/docs/10' },
  { step: 'The ledger keeps hashes, never the circuit', primitive: 'Immutable ledger of digests and verdicts; the molecule stays the buyer’s', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'A named chemist behind every spend', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Each backend states its own facts', primitive: 'Quantum workload card extension: qubits, gates, limits, queue, each with its as_of', railStatus: 'LIVE (gated)' as const },
  { step: 'A calibration assistant beside the device', primitive: 'An agent that reads the device’s own snapshots and publishes a summary', railStatus: 'LIVE (gated)' as const },
  { step: 'The estimate run on real hardware', primitive: 'A provider’s own device, booked and attested like any other service', railStatus: 'DESIGNED' as const },
  { step: 'A disputed estimate, ruled on', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
]

export const lattice: Blueprint = {
  id: 'lattice',
  tier: 2,
  frontier: true,
  rank: 30,
  industry: 'Computational Chemistry and Materials',
  systemName: 'LATTICE',
  promise: 'An estimate is bought against a test agreed before the run, and the escrow opens on the verdict rather than on the seller’s word.',
  cases: [
    { role: 'Computational chemist', line: 'Buy a run from a group you have never met, on a test you set yourself.' },
    { role: 'Materials group lead', line: 'Every estimate arrives with the device, the calibration and the shots that produced it.' },
    { role: 'Quantum software vendor', line: 'Sell estimates on acceptance instead of on reputation.' },
    { role: 'Battery or catalyst programme', line: 'A screening campaign whose negative results are as durable as its positive ones.' },
  ],
  problem:
    'Buying a computational estimate from a stranger is an act of faith. The seller reports a number, the buyer cannot see the device, the circuit or the shots behind it, and the invoice arrives whatever the number was worth. When the result is later questioned, nobody can show which machine ran it, in what state, or how many times.',
  system: [
    'LATTICE is a materials screening network: a battery group in Uppsala that needs ground-state energies for forty candidate electrolytes, and three sellers on their own frames, each with simulator backends and one with a hardware partner. The group’s work order carries its acceptance test before any money moves: rung 1 names two molecules whose energies are already published, and the seller’s estimates have to land inside the stated tolerance. Rung 2 adds test circuits the seller cannot tell from the real ones, with the false-accept and false-reject rates written into the order.',
    'Dr Sofia Lindqvist underwrites the campaign with one mandate for the quarter. Her screening agent holds no wallet and spends the campaign purse, and every order it places is checked against her mandate as it stands at that moment. A seller returns forty estimates, each with its receipt: the circuit’s digest, the backend that ran it, the calibration snapshot as of that hour, the shots and the counts. The escrow opens on the verdict of the agreed test, not on the arrival of the report.',
    'One seller fails rung 1 on the second known molecule. Nothing is paid, the order moves to its dispute phase, and the evidence is already in the record: the digests, the device, the shots. A calibration assistant beside each device reads the device’s own snapshots and publishes a summary with the hour it was taken, so a buyer can see the state the machine was in rather than ask. What the ledger keeps is hashes and verdicts; the molecules stay the buyer’s own.',
  ],
  cast: [
    { agent: 'screening-agent', role: 'Places the orders, reads the verdicts', ceiling: 'The campaign’s sub-agent, with no wallet of its own. Every order is checked against Dr Lindqvist’s mandate as it stands.' },
    { agent: 'seller-UPP-1', role: 'Returns the estimates with their receipts', ceiling: 'Attests its own runs. Cannot release its own escrow or set the test it is judged by.' },
    { agent: 'acceptance-desk', role: 'Runs the agreed test, publishes the verdict', ceiling: 'Checks answers against the order’s template. Holds no budget and cannot order.' },
    { agent: 'calib-assistant', role: 'Publishes each device’s calibration summary', ceiling: 'Reads the device’s own snapshots. Writes no estimate and signs no run.' },
  ],
  loom: {
    nodes: [
      { id: 'chemist', label: 'Dr Lindqvist', sub: 'the mandate, one tap', kind: 'human', x: 118, y: 110 },
      { id: 'screener', label: 'screening-agent', sub: 'orders forty runs', kind: 'agent', x: 118, y: 330 },
      { id: 'order', label: 'Acceptance gate', sub: 'the test, set first', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Run escrow', sub: 'opens on the verdict', kind: 'teg', x: 560, y: 110 },
      { id: 'seller', label: 'seller-UPP-1', sub: 'signs each estimate', kind: 'agent', x: 560, y: 330 },
      { id: 'calib', label: 'calib-assistant', sub: 'the device, as read', kind: 'agent', x: 336, y: 450 },
      { id: 'ledger', label: 'Evidence ledger', sub: 'digests and verdicts', kind: 'ledger', x: 764, y: 110 },
      { id: 'desk', label: 'acceptance-desk', sub: 'checks the answer', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-mandate', from: 'chemist', to: 'order', label: 'scope, signed' },
      { id: 'e-order', from: 'screener', to: 'order', label: 'forty candidates', labelT: 0.3 },
      { id: 'e-escrow', from: 'order', to: 'escrow', label: 'escrowed per run' },
      { id: 'e-calib', from: 'order', to: 'calib', label: 'device state' },
      { id: 'e-estimate', from: 'seller', to: 'escrow', label: 'estimate, signed', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-verdict', from: 'desk', to: 'ledger', label: 'verdict, published' },
      { id: 'a-unsigned', from: 'screener', to: 'order', attackOnly: true, curve: 70, labelT: 0.5, label: 'no receipt' },
      { id: 'a-fail', from: 'seller', to: 'escrow', attackOnly: true, curve: 90, labelT: 0.3, label: 'failed the test' },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Dr Lindqvist underwrites the campaign once: a budget, a tolerance, a quarter.' },
      { edge: 'e-order', state: 'active', dwellMs: 1400, caption: 'The screening agent orders forty candidates, with the acceptance test written into the order.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'Each run is escrowed at order. Nothing opens on the report arriving.' },
      { edge: 'e-calib', state: 'active', dwellMs: 1300, caption: 'The calibration assistant publishes the device’s own snapshot, with the hour it was taken.' },
      { edge: 'e-estimate', state: 'active', dwellMs: 1500, caption: 'The seller signs each estimate: the circuit’s digest, the backend, the shots, the counts.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'A passing run releases its payment exactly once and lands on the ledger as a digest and a verdict.' },
      { edge: 'e-verdict', state: 'active', dwellMs: 1500, caption: 'The acceptance desk checks the known molecules and publishes the verdict either way.' },
    ],
  },
  attacks: [
    {
      title: 'The estimate with no device behind it',
      attack: 'A seller returns a plausible number with no receipt: no circuit digest, no backend, no shots.',
      mechanism: 'A milestone releases on an attested report, and the acceptance template names what a report carries. A report without its receipt fails the template before the verdict is reached, and the escrow stays shut. The gate sits in front of the money, so the refusal needs no unwind.',
      rail: 'S16',
      consequence: 'Nothing is paid and nothing is reversed. The missing receipt is what the record shows.',
      script: [
        { edge: 'a-unsigned', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'order', caption: 'S16. The order says what a report must carry. One without it never reaches the verdict.' },
      ],
    },
    {
      title: 'The failed reference, invoiced anyway',
      attack: 'A seller misses the published energy of the second known molecule by four times the stated tolerance, and asks to be paid for the batch.',
      mechanism: 'The test was agreed before the run and the escrow opens on its verdict. The acceptance desk checks the known answers, publishes the failure, and the milestone stays unreleased. The dispute phase starts with the digests, the device and the shots already in the record.',
      rail: 'S12',
      consequence: 'The batch is unpaid and the evidence for the dispute exists without anyone gathering it.',
      script: [
        { edge: 'a-fail', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'escrow', caption: 'S12. Only the frame holding the escrow releases it, and it releases on the verdict.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [{ label: 'AI System Lifecycle', href: '/compliance/doc/ai-system-lifecycle' }],
  rails: ['S01', 'S05', 'S12', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'A group frame, or each seller on a frame of its own, federated, booted from the free licence and pre-built images. Quantum workloads are one frame switch, off by default.',
    agents: 'A screening agent, an acceptance desk, one agent per backend and a calibration assistant beside each device. The chemistry is the group’s own.',
    integration: 'The structure database, the existing solvers and the reference values the tests are built from. This is where the real time goes, and it stays the group’s.',
  },
  nonClaims: [
    'LATTICE carries identity, authority, money and evidence for computational work. It does not compute, compile, or judge whether an estimate is scientifically sound.',
    'An acceptance test says the seller matched known answers inside a stated tolerance. It does not say the method generalises, and no rate in a template is a guarantee.',
    'The backends in this chamber are simulators. A run on real hardware is specified and marked DESIGNED. Nothing here measures what such a run produces, and this chamber makes no claim about it.',
    'The calibration assistant publishes what a device reports about itself. It does not verify the device, a model running behind it is the provider’s own, and TheProtocol hosts neither. Over a simulator such a summary is a demonstration: it means something over a real device’s measurements, which ANCILLA marks DESIGNED.',
  ],
  mermaid: `flowchart LR
  C(["Dr Lindqvist<br/>mandate"]) -->|"scope"| G{"acceptance gate<br/>the test, set first"}
  S["screening-agent"] -->|"forty candidates"| G
  G -->|"escrowed per run"| E["run escrow"]
  G -->|"device state"| K["calib-assistant"]
  V["seller-UPP-1"] -->|"estimate, signed"| E
  E --> L[("evidence ledger<br/>digests and verdicts")]
  D["acceptance-desk"] -->|"verdict"| L`,
  legacy: [
    { system: 'Structure and property databases', connect: 'A receipt carries the database reference. The database stays the source of record.' },
    { system: 'Existing classical solvers', connect: 'They run beside the order as the incumbent, and their answer is what a test is set against.' },
    { system: 'Quantum SDKs and cloud consoles', connect: 'A backend joins as an agent with its own card. The circuits and the compiler stay the seller’s.' },
    { system: 'Procurement and grant accounting', connect: 'Orders settle on the rails under the mandate; finance reads settlement instead of chasing invoices.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
