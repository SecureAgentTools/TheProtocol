import type { BlueprintDeep } from '../types'

// LODESTAR deep architecture (§18, V0660 (f)): a nightly scheduling market where the buyer's own
// objective scores every answer. The geometry follows COLLEGIUM's, which the drawing check passes.

export const deep: BlueprintDeep = {
  intro:
    'LODESTAR deployed: the operator’s frame holds the mandate, the run escrow, the scoring desk and the score ledger; the sellers sit on their own frames with their backends; the planning system, the incumbent solver and the demand data stay where they are. The trace replays one night, from the bar being set to the score that opens the escrow.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE OPERATOR', sub: 'mandate and escrow', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE SELLERS', sub: 'their own frames', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'THE FABRIC', sub: 'answers, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE NIGHT DESK', sub: 'planning, demand', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'dispatch', label: 'dispatch-agent', sub: 'posts the order', kind: 'agent', x: 140, y: 135 },
      { id: 'gate', label: 'scoring gate', sub: 'objective, first', kind: 'gate', x: 310, y: 133 },
      { id: 'planner', label: 'Ravi Menon', sub: 'mandate, device key', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'run escrow', sub: 'opens on a score', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'score ledger', sub: 'digests and scores', kind: 'ledger', x: 140, y: 375 },
      { id: 'desk', label: 'scoring-desk', sub: 'runs the objective', kind: 'agent', x: 310, y: 375 },
      { id: 'sell', label: 'solver-SIN-4', sub: 'signs each answer', kind: 'agent', x: 690, y: 135 },
      { id: 's-es', label: 'seller ledger', sub: 'same runs, same keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'backend', label: 'sim-SIN-2', sub: 'runs the circuits', kind: 'agent', x: 655, y: 300 },
      { id: 'decode', label: 'decode-assistant', sub: 'batches, not a loop', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'answer relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, own units', kind: 'teg', x: 880, y: 490 },
      { id: 'plan', label: 'planning system', sub: 'owns the night', kind: 'external', x: 195, y: 692 },
      { id: 'incumbent', label: 'incumbent', sub: 'the bar to beat', kind: 'external', x: 375, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'planner', to: 'gate', label: 'mandate', curve: -20, labelT: 0.6 },
      { id: 'e-post', from: 'dispatch', to: 'gate' },
      { id: 'e-order', from: 'gate', to: 'sell', label: 'problem, with its bar' },
      { id: 'e-fund', from: 'gate', to: 'teg' },
      { id: 'e-score', from: 'desk', to: 'es', dashed: true, curve: 30 },
      { id: 'e-answer', from: 'backend', to: 'relay', label: 'answer', labelT: 0.5 },
      { id: 'e-decode', from: 'decode', to: 'relay', label: 'corrections', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'sell', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-semit', from: 'sell', to: 's-es', dashed: true, curve: 26 },
      { id: 'e-bar', from: 'incumbent', to: 'es', label: 'the bar, recorded', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Mr Menon underwrites the night desk once: a budget, a scope, a month.' },
      { edge: 'e-order', dwellMs: 1400, caption: 'Tonight’s problem goes out with the operator’s objective and the incumbent’s score attached.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Each awarded bid is escrowed, and the escrow opens on a score rather than an answer.' },
      { edge: 'e-answer', dwellMs: 1500, caption: 'The backend signs its candidate: the problem’s digest, the shots, the answer.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The relay carries the answer and nothing else. The principal must be party to the contract.' },
      { edge: 'e-score', dwellMs: 1500, caption: 'The scoring desk runs the operator’s own objective and publishes the number either way.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'A passing answer releases once, under a key made from the order and the bid.' },
      { edge: 'e-emit', dwellMs: 1400, caption: 'The ledger keeps the digest, the score and the verdict. The network stays the operator’s.' },
    ],
    traceLabel: 'One night: the bar set first, answers signed, the buyer’s own objective scoring each one.',
  },
  plan: [
    {
      name: 'Phase 1',
      headline: 'One operator, one seller, the bar in the order',
      runs: 'A single frame from the free licence and pre-built images, with quantum workloads in shadow so every decision is made and reported and nothing is refused yet.',
      agents: 'A dispatch agent, a scoring desk, one simulator backend agent.',
      integrates: 'The planning system read-only, and the incumbent solver whose score becomes the bar.',
      notYet: 'No second seller, no bidding, no real device. Shadow mode reports a refusal and allows it.',
      proof: 'An order posted without a bar is reported as refused, and the ledger shows the orders that did carry one.',
    },
    {
      name: 'Phase 2',
      headline: 'The escrow opens on the score, and only on the score',
      runs: 'The same frame with quantum workloads on. An answer below the bar leaves its milestone unreleased.',
      agents: 'Several sellers bidding on the same nightly order, each signing its own answers.',
      integrates: 'The demand feed stays where it is; what travels is a digest, never the network.',
      notYet: 'Still no real device. A seller without a prover reports its shots unproven and says so.',
      proof: 'Two sellers answer the same night, one above the bar and one below it, and the ledger shows both scores with one release.',
    },
    {
      name: 'Phase 3',
      headline: 'A market, each seller in its own unit',
      runs: 'Sellers on their own frames, federated. Only the frame holding the escrow releases it.',
      agents: 'A decoding assistant beside a hardware seller, running in batches rather than inside a correction cycle.',
      integrates: 'Procurement reads settlement instead of benchmark claims.',
      notYet: 'Real hardware stays specified and marked DESIGNED until a provider brings its own device and account.',
      proof: 'A seller in another unit is paid at home for an answer that beat the bar, and both ledgers show the same bid under the same key.',
    },
  ],
  sequence: `sequenceDiagram
  participant R as Ravi Menon
  participant G as Scoring gate
  participant S as solver-SIN-4
  participant T as Run escrow
  participant D as scoring-desk
  participant L as Score ledger
  R->>G: mandate: budget, scope, month
  G->>S: tonight's problem, objective and bar attached
  G->>T: escrow per awarded bid
  S->>T: answer, signed, with its receipt
  D->>L: the buyer's own objective, scored
  T->>L: release once, on the score
  Note over L: digests and scores, never the network`,
  sequenceTitle: 'One night, from the bar set first to the escrow opened on a score',
  sizing: [
    { level: 'L1', what: 'One operator, one seller, simulators; one frame carries registry, TEG, ledger and identity', containers: 'nine, from the kit' },
    { level: 'L2', what: 'An operator buying from several sellers, an agent per seller backend, the scoring desk beside the planner', containers: 'the same frame' },
    { level: 'L3', what: 'A market of sellers in their own units, federated with cross-registry settlement', containers: 'one frame per seller' },
  ],
}
