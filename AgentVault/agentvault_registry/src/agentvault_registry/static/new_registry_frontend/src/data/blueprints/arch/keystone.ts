import type { BlueprintDeep } from '../types'

// KEYSTONE deep architecture (§18) — a build as a tree of escrows, evidence
// driving draws, and retention that cannot be quietly forgotten.

export const deep: BlueprintDeep = {
  intro:
    'KEYSTONE deployed: the project frame holds the master contract, the draw escrow and the evidence chain; the trades and the arbiter act from their own registries; site hardware feeds the attestations. The subcontract tree is data on the same rails, which is why the concrete crew can watch its milestone money exist before the first pour. The trace replays draw twelve, evidence to credit, with the retention sitting where nobody can lose it.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE PROJECT’S FRAME', sub: 'master contract, escrows, evidence', x: 30, y: 50, w: 360, h: 480, kind: 'frame' },
      { id: 'zp', label: 'THE TRADES', sub: 'their registries, their law', x: 640, y: 50, w: 330, h: 480, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'claims and evidence cross here', x: 410, y: 50, w: 210, h: 480, kind: 'fabric' },
      { id: 'ze', label: 'THE SITE AND THE OFFICE', sub: 'BIM and scheduling stay where they are', x: 30, y: 580, w: 940, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'owner', label: 'owner-desk', sub: 'funds the master', kind: 'human', x: 300, y: 255 },
      { id: 'master', label: 'master contract', sub: 'escrow at award', kind: 'gate', x: 300, y: 375 },
      { id: 'es', label: 'evidence chain', sub: 'append-only', kind: 'ledger', x: 300, y: 495 },
      { id: 'teg', label: 'draw escrow', sub: 'retention held', kind: 'teg', x: 110, y: 375 },
      { id: 'engineer', label: 'engineer', sub: 'presence threshold', kind: 'human', x: 110, y: 495 },
      { id: 'subesc', label: 'sub-escrows x19', sub: 'mirrored obligations', kind: 'teg', x: 110, y: 135 },
      { id: 'sub', label: 'sub-crew-07', sub: 'the concrete crew', kind: 'agent', x: 720, y: 135 },
      { id: 'inspect', label: 'inspection-agent', sub: 'attests, no release', kind: 'agent', x: 890, y: 375 },
      { id: 'mirror', label: 'escrow mirror', sub: 'crew sees its money', kind: 'registry', x: 720, y: 495 },
      { id: 'arbiter', label: 'dispute-arbiter', sub: 'rules facade fight', kind: 'agent', x: 720, y: 255 },
      { id: 'relay', label: 'contract relay', sub: 'signed commands', kind: 'registry', x: 515, y: 375 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 515, y: 135 },
      { id: 'bim', label: 'BIM / scheduling', sub: 'programme, read-side', kind: 'external', x: 800, y: 647 },
      { id: 'sensors', label: 'sensors + photos', sub: 'evidence attests', kind: 'external', x: 330, y: 647 },
    ],
    edges: [
      { id: 'e-bim', from: 'bim', to: 'inspect', label: 'programme, read-side', dashed: true, labelT: 0.7 },
      { id: 'e-fund', from: 'owner', to: 'master', label: 'funds' },
      { id: 'e-master', from: 'master', to: 'teg', label: 'escrow', labelT: 0.45 },
      { id: 'e-tree', from: 'teg', to: 'subesc', label: 'mirrored, x19' },
      { id: 'e-sens', from: 'sensors', to: 'relay', label: 'feeds the attestor', dashed: true, curve: 16, labelT: 0.65 },
      { id: 'e-claim', from: 'sub', to: 'relay', label: 'claims draw twelve', curve: 24, labelT: 0.1 },
      { id: 'e-attest', from: 'inspect', to: 'relay', label: 'sensor + photo evidence', curve: 32 },
      { id: 'e-relay', from: 'relay', to: 'master', label: 'principal checked' },
      { id: 'e-sign', from: 'engineer', to: 'teg', label: 'presence signs', labelT: 0.7 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: -8 },
      { id: 'e-see', from: 'es', to: 'mirror', label: 'signed mirror', dashed: true, curve: 12, labelT: 0.6 },
      { id: 'e-pay', from: 'subesc', to: 'xfer', label: 'draw, keyed' },
      { id: 'e-payout', from: 'xfer', to: 'sub', label: 'their TEG credits', curve: -30 },
      { id: 'e-rule', from: 'arbiter', to: 'relay', label: 'ruling, evidenced', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-fund', dwellMs: 1400, caption: 'The owner funds the master contract. The budget is now a fact, not a promise.' },
      { edge: 'e-master', dwellMs: 1300, caption: 'Escrow at award, retention held as a final milestone that cannot be forgotten in a hallway.' },
      { edge: 'e-tree', dwellMs: 1400, caption: 'The general contractor mirrors its obligations down: nineteen subcontracts on the same rails.' },
      { edge: 'e-see', dwellMs: 1400, caption: 'The concrete crew watches its milestone money exist before the first pour.' },
      { edge: 'e-sens', dwellMs: 1300, caption: 'Draw twelve: the site hardware feeds the inspection agent.' },
      { edge: 'e-attest', dwellMs: 1400, caption: 'The inspection agent submits sensor and photo evidence. It attests; it cannot release.' },
      { edge: 'e-claim', dwellMs: 1300, caption: 'The crew claims the draw from its own registry.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The fabric couriers the signed commands home. The relaying peer is never the principal.' },
      { edge: 'e-sign', dwellMs: 1500, caption: 'Above the threshold, the supervising engineer signs: a named human, present, recorded.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'Evidence, approval and release land on the chain, append-only.' },
      { edge: 'e-pay', dwellMs: 1400, caption: 'The draw crosses registries with an idempotency key.' },
      { edge: 'e-payout', dwellMs: 1300, caption: 'The crew’s own TEG credits it, under its own law.' },
      { edge: 'e-rule', dwellMs: 1500, caption: 'Month fourteen: the facade dispute freezes that work’s money only. The ruling splits the escrow exactly once, and every other trade keeps getting paid on schedule.' },
    ],
    traceLabel: 'Draw twelve: evidence to credit, retention intact, one dispute contained.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One trade package, re-told as escrows.',
      runs: 'Nothing. One finished package redrawn as milestones, evidence rules and a retention schedule.',
      agents: 'None. The commercial team and the engineer set the evidence thresholds while nothing is owed yet.',
      integrates: 'Nothing. BIM, scheduling and the site stay untouched.',
      notYet: 'No escrow, no attestor, no tree.',
      proof: 'Last year’s most contested draw re-expressed as evidence plus release conditions, and both sides agree on where it would have settled.',
    },
    {
      name: 'Pilot',
      headline: 'One package, real money, small draws.',
      runs: 'A project registry on a single VM. One subcontract runs through it end to end.',
      agents: 'owner-desk, gc-ops, one sub-crew, the inspection agent. The engineer holds a pilot-ceiling mandate.',
      integrates: 'Site photos and sensor exports feed the attestor; the scheduler remains the scheduler.',
      notYet: 'One package only. Retention modelled, not yet at stake. The arbiter expects boredom.',
      proof: 'Five draws release on evidence with the engineer’s presence recorded on each, and zero payment-application emails.',
    },
    {
      name: 'Production',
      headline: 'The whole tree, retention on the ledger.',
      runs: 'One registry per project or per firm: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast; nineteen subcontracts as data; retention held as final milestones with release conditions.',
      integrates: 'Inspection hardware in production; the evidence chain feeds the office instead of a claims folder.',
      notYet: 'Cross-project reputation. Each project’s tree stands alone first.',
      proof: 'A completed project closes out with every retention released or disputed on the ledger, and none renegotiated in a hallway.',
    },
    {
      name: 'Federation',
      headline: 'Trades carry their record to the next site.',
      runs: 'Unchanged. Trades and owners bring frames or seats.',
      agents: 'Crew reputations travel with DIDs; the next tender can read settled outcomes, not references.',
      integrates: 'Each new trade is a signed card and a licence.',
      notYet: 'Nothing structural. Growth is projects.',
      proof: 'A trade wins a package on a new project and its first draw releases within the first month, with no bilateral setup.',
    },
  ],
  sequenceTitle: 'One draw, evidence to credit',
  sequence: `sequenceDiagram
  participant Ins as inspection-agent
  participant Crew as sub-crew-07 (their frame)
  participant Fab as federation fabric
  participant MC as master contract (project frame)
  participant Eng as supervising engineer
  participant TEG as draw escrow
  participant XT as cross-registry pay
  Ins->>Fab: sensor + photo evidence, signed
  Crew->>Fab: draw twelve claimed
  Fab->>MC: relayed commands (principal checked)
  MC->>Eng: above threshold: presence required
  Eng-->>MC: signed, present, recorded
  MC->>TEG: release the draw
  TEG->>XT: pay the crew (idempotency key)
  XT->>Crew: their TEG credits, exactly once
  Note over TEG: retention stays as a final milestone with a release condition`,
  sizing: [
    { level: 'L1', what: 'Trades join projects with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A GC runs its agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'A frame per project or per firm; the tree is data, not deployments', containers: '~9, one VM up' },
  ],
}
