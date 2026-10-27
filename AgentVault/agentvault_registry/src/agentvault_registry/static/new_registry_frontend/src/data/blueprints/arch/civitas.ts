import type { BlueprintDeep } from '../types'

// CIVITAS deep architecture (§18) — a city frame, visible escrow, and
// enforcement that no single identity can execute.

export const deep: BlueprintDeep = {
  intro:
    'CIVITAS at deployment scale: the city runs its own frame in its own datacenter, the vendors and the independent inspectorate act from their registries, and the regional government peers over the fabric instead of sharing a database. The ERP and the tender platform stay where they are; what changes is that the money sits in escrow everyone can see and no enforcement is a single identity’s act. The trace replays one road contract, award to release.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE CITY’S FRAME', sub: 'municipal hardware, municipal law', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'VENDORS AND THE REGION', sub: 'their registries, their law', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'courier, never principal', x: 530, y: 445, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'CITY BACK OFFICE', sub: 'the ERP and the tender platform', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'officer', label: 'officer', sub: 'cannot execute', kind: 'human', x: 110, y: 135 },
      { id: 'queue', label: 'two-man queue', sub: 'approval = execution', kind: 'gate', x: 370, y: 115 },
      { id: 'escrow', label: 'award escrow', sub: 'council-visible', kind: 'teg', x: 370, y: 255 },
      { id: 'es', label: 'audit trail', sub: 'citizen-readable', kind: 'ledger', x: 110, y: 255 },
      { id: 'procurement', label: 'procurement-desk', sub: 'awards, funds', kind: 'agent', x: 200, y: 375 },
      { id: 'spine', label: 'contract spine', sub: 'escrow at award', kind: 'gate', x: 370, y: 375 },
      { id: 'vendor', label: 'vendor-paving', sub: 'submits sections', kind: 'agent', x: 890, y: 375 },
      { id: 'inspect', label: 'inspection-3', sub: 'verifies, signed', kind: 'agent', x: 760, y: 135 },
      { id: 'v-es', label: 'vendor ledger', sub: 'same releases', kind: 'ledger', x: 890, y: 255 },
      { id: 'region', label: 'regional frame', sub: 'peer, not landlord', kind: 'registry', x: 620, y: 135 },
      { id: 'relay', label: 'contract relay', sub: 'signed commands', kind: 'registry', x: 700, y: 550 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 900, y: 510 },
      { id: 'erp', label: 'city ERP', sub: 'budgets stay here', kind: 'external', x: 250, y: 692 },
      { id: 'tender', label: 'tender platform', sub: 'awards flow in', kind: 'external', x: 400, y: 692 },
    ],
    edges: [
      { id: 'e-award', from: 'tender', to: 'procurement', label: 'award, Tuesday', dashed: true },
      { id: 'e-open', from: 'procurement', to: 'spine', label: 'milestones' },
      { id: 'e-fund', from: 'procurement', to: 'escrow', label: 'fund at award', labelT: 0.45 },
      { id: 'e-visible', from: 'escrow', to: 'es', dashed: true },
      { id: 'e-submit', from: 'vendor', to: 'relay', label: 'section + evidence', curve: 18, labelT: 0.39 },
      { id: 'e-verify', from: 'inspect', to: 'relay', label: 'verified, signed', curve: 12, labelT: 0.31 },
      { id: 'e-relay', from: 'relay', to: 'spine', label: 'principal checked', labelT: 0.55 },
      { id: 'e-release', from: 'spine', to: 'escrow', label: 'release', labelT: 0.6 },
      { id: 'e-pay', from: 'escrow', to: 'xfer', label: 'cross-registry pay', curve: 9, labelT: 0.37 },
      { id: 'e-payout', from: 'xfer', to: 'vendor', label: 'their TEG credits', curve: -18, labelT: 0.22 },
      { id: 'e-vemit', from: 'vendor', to: 'v-es', dashed: true },
      { id: 'e-fed', from: 'region', to: 'relay', label: 'signed cards', dashed: true, curve: -18, labelT: 0.41 },
      { id: 'e-erp', from: 'es', to: 'erp', label: 'evidence export', dashed: true, labelT: 0.37, curve: 33 },
      { id: 'e-file', from: 'officer', to: 'queue', label: 'files, alone', dashed: true, labelT: 0.4 },
      { id: 'e-exec', from: 'queue', to: 'escrow', label: 'second approval', dashed: true, labelT: 0.7 },
    ],
    script: [
      { edge: 'e-award', dwellMs: 1300, caption: 'A resurfacing contract awards on a Tuesday. The tender ran where tenders run; the award lands here.' },
      { edge: 'e-open', dwellMs: 1300, caption: 'The award becomes a contract: milestones, terms schema, the vendor named.' },
      { edge: 'e-fund', dwellMs: 1400, caption: 'The budget enters escrow at award.' },
      { edge: 'e-visible', dwellMs: 1300, caption: 'The escrow is visible to the council, and to anyone else who cares to look.' },
      { edge: 'e-submit', dwellMs: 1400, caption: 'The vendor’s paving agents submit each section with sensor evidence, from their own registry.' },
      { edge: 'e-verify', dwellMs: 1300, caption: 'The independent inspection agent verifies the work. Verification is signed, not minuted.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The fabric couriers the signed commands home. The relaying peer is never the principal.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'The contract spine, and only it, releases the milestone.' },
      { edge: 'e-pay', dwellMs: 1400, caption: 'Payment crosses registries with an idempotency key.' },
      { edge: 'e-payout', dwellMs: 1300, caption: 'The vendor’s own TEG credits it, under its own law.' },
      { edge: 'e-file', dwellMs: 1400, caption: 'In November, an officer moves to debar a supplier. The action files. It does not execute.' },
      { edge: 'e-exec', dwellMs: 1500, caption: 'A second identity approves, and the approval is the execution. No public money moves on one officer’s word.' },
    ],
    traceLabel: 'One road contract: award to release, and no officer alone.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One contract, re-told.',
      runs: 'Nothing in the city’s estate. One finished contract from last year and its paper trail.',
      agents: 'None. Procurement and the audit office read the model against their own file.',
      integrates: 'Nothing. The ERP and the tender platform are untouched.',
      notYet: 'No frame, no escrow, no declaration.',
      proof: 'One historical resurfacing contract re-expressed as milestones and releases, and the audit office confirms the telling matches the file.',
    },
    {
      name: 'Pilot',
      headline: 'One budget line, visible from day one.',
      runs: 'A single-VM frame in the city datacenter. One budget line flows through it.',
      agents: 'procurement-desk, one vendor agent, inspection-3. Two officers hold enforcement between them.',
      integrates: 'Tender results in via the SDK; the ERP receives evidence exports beside its own records.',
      notYet: 'One contract class. The public declaration is drafted, not yet published.',
      proof: 'A pilot contract runs award to final release with every release visible to the council the day it happens.',
    },
    {
      name: 'Production',
      headline: 'The city’s frame, the city’s law, in public.',
      runs: 'A sovereign frame on municipal hardware: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast. Enforcement is two-man across the board; the declaration of what this deployment will never run is signed into the registry card.',
      integrates: 'The ERP and the tender platform, continuously. Procurement law stays with the lawyers.',
      notYet: 'Regional federation. The neighbouring frames are known but not yet peered.',
      proof: 'The signed declaration is public and fetchable, and a deliberate test drift between config and declaration is detected by a peer within a day.',
    },
    {
      name: 'Federation',
      headline: 'The region reads the card, not the database.',
      runs: 'Unchanged. The regional frame and the large vendors peer bilaterally.',
      agents: 'Per-corridor casts; vendor reputations travel with their DIDs.',
      integrates: 'Each new vendor or authority is a signed card and a license, not an integration project.',
      notYet: 'No shared database is ever built. That is the point.',
      proof: 'A vendor onboards to a new tender without a bilateral integration meeting, and the region audits the city by reading its card and its ledger.',
    },
  ],
  sequenceTitle: 'One milestone, submission to credit',
  sequence: `sequenceDiagram
  participant Ven as vendor-paving (their frame)
  participant Ins as inspection-3 (inspectorate)
  participant Fab as federation fabric
  participant CS as contract spine (city frame)
  participant TEG as city escrow
  participant XT as cross-registry pay
  participant ES as audit trail
  Ven->>Fab: section submitted + sensor evidence
  Ins->>Fab: verification, signed
  Fab->>CS: relayed commands (principal checked)
  CS->>TEG: release milestone
  TEG-->>ES: release event, citizen-readable
  TEG->>XT: pay vendor (idempotency key)
  XT->>Ven: their TEG credits, exactly once
  Note over ES: enforcement, if any, files to a two-man queue first`,
  sizing: [
    { level: 'L1', what: 'Vendors join tenders with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A vendor or inspectorate runs its agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'The city runs its sovereign frame on municipal hardware', containers: '~9, one VM up' },
  ],
}
