import type { BlueprintDeep } from '../types'

// HANSA deep architecture (§18) — one container across sovereign registries.

export const deep: BlueprintDeep = {
  intro:
    'HANSA at deployment scale: the shipper’s frame holds the contract and the escrow, the carrier and the port authority act from their own registries, and the fabric between them carries signed commands without ever becoming a principal. A risk analyst reads a mirror nobody can rewrite. The trace replays one container, Busan to Rotterdam.',
  arch: {
    zones: [
      { id: 'zs', label: 'SHIPPER’S FRAME (BUSAN)', sub: 'the contract and its escrow live here', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zc', label: 'CARRIER + PORT REGISTRIES', sub: 'their frames, their law', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'courier, never principal', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'PHYSICAL WORLD SYSTEMS', sub: 'the port and the office', x: 30, y: 625, w: 490, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'shipper', label: 'shipper-busan', sub: 'creates, funds', kind: 'agent', x: 140, y: 135 },
      { id: 'contract', label: 'contract spine', sub: 'escrow at agreed', kind: 'gate', x: 140, y: 255 },
      { id: 'es', label: 'event ledger', sub: 'append-only', kind: 'ledger', x: 310, y: 135 },
      { id: 'teg', label: 'TEG escrow', sub: 'milestone tranches', kind: 'teg', x: 310, y: 255 },
      { id: 'arbiter', label: 'dispute-arbiter', sub: 'evidence, ruling', kind: 'agent', x: 140, y: 375 },
      { id: 'carrier', label: 'carrier-ops', sub: 'claims milestones', kind: 'agent', x: 860, y: 375 },
      { id: 'customs', label: 'port customs', sub: 'attests arrival', kind: 'agent', x: 860, y: 135 },
      { id: 'replica', label: 'signed replica', sub: 'read-only mirror', kind: 'registry', x: 690, y: 255 },
      { id: 'riskwatch', label: 'risk-watch', sub: 'reads, never writes', kind: 'agent', x: 690, y: 135 },
      { id: 'relay', label: 'contract relay', sub: 'signed commands', kind: 'registry', x: 700, y: 527 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'exactly-once credit', kind: 'teg', x: 900, y: 527 },
      { id: 'erp', label: 'shipper ERP', sub: 'POs stay here', kind: 'external', x: 410, y: 692 },
      { id: 'tos', label: 'terminal / TOS', sub: 'EDI adapter bridges', kind: 'external', x: 250, y: 692 },
    ],
    edges: [
      { id: 'e-erp', from: 'erp', to: 'teg', label: 'bookings, invoices', dashed: true, curve: -46, labelT: 0.49 },
      { id: 'e-create', from: 'shipper', to: 'contract', label: 'offer' },
      { id: 'e-fund', from: 'shipper', to: 'teg', label: 'fund milestones', labelT: 0.65 },
      { id: 'e-claim', from: 'carrier', to: 'relay', label: 'milestone claim, signed', curve: -30, labelT: 0.6 },
      { id: 'e-attest', from: 'customs', to: 'relay', label: 'arrival attestation', labelT: 0.49 },
      { id: 'e-relay', from: 'relay', to: 'contract', label: 'relayed, principal checked', curve: -50, labelT: 0.45 },
      { id: 'e-release', from: 'contract', to: 'teg', label: 'release', labelT: 0.49 },
      { id: 'e-pay', from: 'teg', to: 'xfer', label: 'cross-registry pay', curve: -22, labelT: 0.5 },
      { id: 'e-payout', from: 'xfer', to: 'carrier', label: 'their TEG credits', labelT: 0.7 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-mirror', from: 'es', to: 'replica', label: 'signed mirror', dashed: true, labelT: 0.19 },
      { id: 'e-watch', from: 'riskwatch', to: 'replica', dashed: true },
      { id: 'e-tos', from: 'tos', to: 'arbiter', label: 'gate records as evidence', dashed: true, labelT: 0.45 },
      { id: 'e-rule', from: 'arbiter', to: 'contract', label: 'ruling drives the split', dashed: true, labelT: 0.14 },
    ],
    script: [
      { edge: 'e-erp', dwellMs: 1300, caption: 'The booking and its documents arrive from the ERP. Logistics stays where it lives.' },
      { edge: 'e-create', dwellMs: 1400, caption: 'The shipper instantiates the contract: milestones, terms schema, annex references.' },
      { edge: 'e-fund', dwellMs: 1400, caption: 'Escrow funds at agreement. The carrier watches the money exist before the ship sails.' },
      { edge: 'e-claim', dwellMs: 1500, caption: 'Weeks later in Rotterdam, the carrier claims the arrival milestone from its own registry.' },
      { edge: 'e-attest', dwellMs: 1400, caption: 'The port authority attests the physical arrival, as itself, from a foreign frame.' },
      { edge: 'e-relay', dwellMs: 1500, caption: 'The fabric couriers the signed commands home. The relaying peer is never the principal.' },
      { edge: 'e-release', dwellMs: 1300, caption: 'The escrow-holding frame, and only it, releases the tranche.' },
      { edge: 'e-pay', dwellMs: 1500, caption: 'Payment crosses registries with an idempotency key.' },
      { edge: 'e-payout', dwellMs: 1300, caption: 'The carrier’s own TEG credits it, under its own law.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'One truth per tranche, on the home ledger, append-only.' },
      { edge: 'e-mirror', dwellMs: 1400, caption: 'A signed replica mirrors to every party. The risk analyst reads; nobody rewrites.' },
    ],
    traceLabel: 'One container, Busan to Rotterdam, contract to credit.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Map one lane, touch nothing.',
      runs: 'Nothing in your estate. One lane of your network drawn against the rails: who would sign what.',
      agents: 'None. The counterparties are named on paper, not enrolled.',
      integrates: 'Nothing. The TOS, the ERP and the carrier links stay untouched.',
      notYet: 'No contract, no escrow, no registry.',
      proof: 'One historical shipment re-told as milestones and attestations, and every party agrees the telling is correct.',
    },
    {
      name: 'Pilot',
      headline: 'One lane, real contract, small money.',
      runs: 'The shipper runs one hosted registry seat or a single-VM frame; counterparties join as L1 accounts.',
      agents: 'shipper agent, carrier-ops, one attestor; the arbiter exists but expects boredom.',
      integrates: 'ERP bookings in via SDK; terminal gate records photographed into evidence, not yet wired.',
      notYet: 'One lane only. No risk analyst reads it yet. Amounts are pocket-sized.',
      proof: 'Five consecutive shipments settle from escrow on attested milestones with zero settlement emails.',
    },
    {
      name: 'Production',
      headline: 'The lane goes to real volume; the port signs natively.',
      runs: 'Sovereign frame at the shipper; the port authority and large counterparties stand up their own or use hosted seats.',
      agents: 'Full cast per lane; customs attests from its own registry; risk-watch reads the replica and gives rates and chances.',
      integrates: 'TOS gate-out events feed attestations; ERP receives the evidence chain continuously.',
      notYet: 'Other lanes. Each lane onboards as configuration, not as a project.',
      proof: 'A disputed milestone resolves through the four-phase process with the ruling executing the split from held escrow.',
    },
    {
      name: 'Federation',
      headline: 'Forty-one registries, no landlord.',
      runs: 'Unchanged. New parties bring their own frames or seats.',
      agents: 'Per-lane casts; reputations travel with DIDs across the mesh.',
      integrates: 'Each new corridor is a signed card, a license, and a template instantiation.',
      notYet: 'No shared database is ever built. That is the point.',
      proof: 'A new counterparty ships on the network without a single bilateral integration meeting.',
    },
  ],
  sequenceTitle: 'One milestone, claim to credit',
  sequence: `sequenceDiagram
  participant Car as carrier-ops (their frame)
  participant Cus as customs (port frame)
  participant Fab as federation fabric
  participant CS as contract spine (home)
  participant TEG as home TEG escrow
  participant XT as cross-registry pay
  participant ES as home event ledger
  Car->>Fab: milestone claim, signed
  Cus->>Fab: arrival attestation, signed
  Fab->>CS: relayed commands (principal checked)
  CS->>TEG: release tranche
  TEG-->>ES: tranche event, append-only
  TEG->>XT: pay carrier (idempotency key)
  XT->>Car: their TEG credits, exactly once
  ES-->>Fab: signed replica update
  Fab-->>Cus: mirror (read-only)
`,
  sizing: [
    { level: 'L1', what: 'Counterparties join lanes with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A forwarder runs its agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'Shipper or port runs a sovereign frame for its own law', containers: 'a full frame each' },
  ],
}
