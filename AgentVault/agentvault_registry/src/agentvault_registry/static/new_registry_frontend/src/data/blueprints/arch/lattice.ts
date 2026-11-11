import type { BlueprintDeep } from '../types'

// LATTICE deep architecture (§18, V0660 (f)): a screening campaign whose estimates are bought against a
// test set before the run. The geometry follows COLLEGIUM's, which the drawing check passes.

export const deep: BlueprintDeep = {
  intro:
    'LATTICE deployed: the group’s frame holds the mandate, the run escrow and the evidence ledger; the sellers sit on their own frames with their backends; the structure database, the incumbent solvers and the reference values stay where they are. The trace replays one batch, from the test being set to the verdict that opens the escrow.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE GROUP FRAME', sub: 'mandate and escrow', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE SELLERS', sub: 'their own frames', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'THE FABRIC', sub: 'runs, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE LAB', sub: 'data, solvers', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'screener', label: 'screening-agent', sub: 'orders the batch', kind: 'agent', x: 140, y: 135 },
      { id: 'order', label: 'acceptance gate', sub: 'the test, set first', kind: 'gate', x: 310, y: 133 },
      { id: 'chemist', label: 'Dr Lindqvist', sub: 'mandate, device key', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'run escrow', sub: 'opens on a verdict', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'evidence ledger', sub: 'digests, verdicts', kind: 'ledger', x: 140, y: 375 },
      { id: 'desk', label: 'acceptance-desk', sub: 'checks the answer', kind: 'agent', x: 310, y: 375 },
      { id: 'sell', label: 'seller-UPP-1', sub: 'signs each estimate', kind: 'agent', x: 690, y: 135 },
      { id: 's-es', label: 'seller ledger', sub: 'same runs, same keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'backend', label: 'sim-UPP-9', sub: 'runs the circuits', kind: 'agent', x: 655, y: 300 },
      { id: 'calib', label: 'calib-assistant', sub: 'the device, as read', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'report relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, own units', kind: 'teg', x: 880, y: 490 },
      { id: 'db', label: 'structure data', sub: 'references', kind: 'external', x: 195, y: 692 },
      { id: 'solver', label: 'classical solver', sub: 'the incumbent', kind: 'external', x: 375, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'chemist', to: 'order', label: 'mandate', curve: -20, labelT: 0.6 },
      { id: 'e-place', from: 'screener', to: 'order' },
      { id: 'e-buy', from: 'order', to: 'sell', label: 'batch, with its test' },
      { id: 'e-fund', from: 'order', to: 'teg' },
      { id: 'e-check', from: 'desk', to: 'es', dashed: true, curve: 30 },
      { id: 'e-run', from: 'backend', to: 'relay', label: 'estimate', labelT: 0.5 },
      { id: 'e-calib', from: 'calib', to: 'relay', label: 'snapshot, dated', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'sell', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-semit', from: 'sell', to: 's-es', dashed: true, curve: 26 },
      { id: 'e-db', from: 'db', to: 'es', label: 'refs in every run', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Dr Lindqvist underwrites the campaign once: a budget, a tolerance, a quarter.' },
      { edge: 'e-buy', dwellMs: 1400, caption: 'The batch goes out with its acceptance test attached, before any money moves.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Each run is escrowed at order, and the escrow opens on a verdict rather than a report.' },
      { edge: 'e-run', dwellMs: 1500, caption: 'The backend signs each estimate: the circuit’s digest, the shots, the device.' },
      { edge: 'e-calib', dwellMs: 1300, caption: 'The calibration summary travels with it, dated to the hour it was read.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The relay carries the report and nothing else. The principal must be party to the contract.' },
      { edge: 'e-check', dwellMs: 1500, caption: 'The acceptance desk checks the known molecules and publishes the verdict either way.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'A passing milestone releases once, under a key made from the order and the run.' },
    ],
    traceLabel: 'One batch of forty: the test set first, the estimates signed, the verdict published, the escrow opened once.',
  },
  plan: [
    {
      name: 'Phase 1',
      headline: 'One group, one seller, rung 1 only',
      runs: 'A single frame from the free licence and pre-built images, with quantum workloads in shadow so every decision is made and reported and nothing is refused yet.',
      agents: 'A screening agent, an acceptance desk, one simulator backend agent.',
      integrates: 'The structure database read-only, and the reference values the rung 1 test is built from.',
      notYet: 'No hidden test circuits, no second seller, no real device. Shadow mode reports a refusal and allows it.',
      proof: 'A batch with a deliberately wrong reference answer is reported as failing rung 1, with the digests and shots already in the record.',
    },
    {
      name: 'Phase 2',
      headline: 'Rung 2, and the escrow opens on the verdict',
      runs: 'The same frame with quantum workloads on. A report that does not carry its receipt fails the template before the verdict.',
      agents: 'A calibration assistant beside each device, publishing the device’s own snapshots with their hour.',
      integrates: 'The incumbent solver runs beside the order as the comparison the test is set against.',
      notYet: 'Still no real device, and the metering proof is produced by the seller. A seller without a prover reports its shots unproven and says so.',
      proof: 'A seller that misses a known answer outside the tolerance is unpaid, and the dispute opens on evidence nobody had to gather.',
    },
    {
      name: 'Phase 3',
      headline: 'Several sellers, each in its own unit',
      runs: 'Sellers on their own frames, federated. Only the frame holding the escrow releases it.',
      agents: 'A seller agent per frame, each with its own backends and its own calibration assistant.',
      integrates: 'Grant accounting reads settlement. A campaign’s negative results are as durable as its positive ones.',
      notYet: 'Real hardware stays specified and marked DESIGNED until a provider brings its own device and account.',
      proof: 'Two sellers answer the same batch under the same test, and both ledgers show the same runs under the same keys.',
    },
  ],
  sequence: `sequenceDiagram
  participant C as Dr Lindqvist
  participant G as Acceptance gate
  participant S as seller-UPP-1
  participant T as Run escrow
  participant D as acceptance-desk
  participant L as Evidence ledger
  C->>G: mandate: budget, tolerance, quarter
  G->>S: the batch, with its test attached
  G->>T: escrow per run
  S->>T: estimate, signed, with its receipt
  D->>L: verdict on the known answers
  T->>L: release once, on the verdict
  Note over L: digests and verdicts, never the molecules`,
  sequenceTitle: 'One batch, from the test set first to the escrow opened once',
  sizing: [
    { level: 'L1', what: 'One group, one seller, simulators; one frame carries registry, TEG, ledger and identity', containers: 'nine, from the kit' },
    { level: 'L2', what: 'A group buying from several sellers, an agent per backend, a calibration assistant beside each device', containers: 'the same frame' },
    { level: 'L3', what: 'A market of sellers in their own units, federated with cross-registry settlement', containers: 'one frame per seller' },
  ],
}
