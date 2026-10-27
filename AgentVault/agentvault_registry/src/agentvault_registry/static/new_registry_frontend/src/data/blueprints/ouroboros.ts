import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Deposits held, not pooled away', primitive: 'Escrow per deposit; refund on verified return', railStatus: 'LIVE' as const },
  { step: 'Custody as signed handoffs', primitive: 'Attested chain from bin to processor', railStatus: 'LIVE' as const },
  { step: 'Verified processing gates payout', primitive: 'Milestone contracts: weighbridge attestation releases', railStatus: 'LIVE' as const },
  { step: 'Municipal books in public', primitive: 'Immutable ledger; an audit is a query', railStatus: 'LIVE' as const },
  { step: 'Haulers with reputations', primitive: 'Trust scores on verified delivery, not tender prose', railStatus: 'LIVE' as const },
  { step: 'Fraud rings surface', primitive: 'Collusion detection over the refund graph', railStatus: 'LIVE' as const },
]

export const ouroboros: Blueprint = {
  id: 'ouroboros',
  tier: 2,
  vault: true,
  rank: 20,
  industry: 'Waste and Circular Economy',
  systemName: 'OUROBOROS',
  promise: 'Deposit-refund loops that close, custody chains that sign, and recycling claims that survive an audit.',
  cases: [
    { role: 'Deposit scheme operator', line: 'Every deposit escrowed, every refund against a verified return.' },
    { role: 'Municipal waste authority', line: 'Hauler payments released on weighbridge attestations.' },
    { role: 'Recycler and processor', line: 'Inbound custody signed; your output claims carry proof.' },
    { role: 'Producer responsibility org', line: 'Recovery targets measured on a ledger, not on self-reports.' },
  ],
  problem:
    'The circular economy runs on claims nobody can check: deposit schemes leak refunds to fraud, recovery rates are self-reported, and the custody chain between the bin and the processor is a stack of paper the auditor samples once a year. Money moves on trust in an industry priced by the tonne.',
  system: [
    'OUROBOROS runs a deposit-refund scheme the way an engineer would: every deposit sits in escrow when the container ships, and the refund releases when the return is verified at a registered point, one refund per container identity, with the double-claim arriving as a refused duplicate rather than a quiet loss. The scheme operator stops reconciling spreadsheets against warehouses; the loop closes itself, and what does not return stays visible as unredeemed escrow rather than vanishing.',
    'Downstream, custody is a chain of signed handoffs: the collection round signs, the transfer station weighs and signs, the processor signs intake, and the municipal payment for the round releases against the weighbridge attestation instead of the invoice. When the producer responsibility organization asks what was actually recovered this quarter, the answer is a query over the ledger, and the hauler who reliably delivers what they collect carries that record as a score the next tender can read.',
  ],
  cast: [
    { agent: 'scheme-treasury', role: 'Holds deposit escrows', ceiling: 'Refund on verified return only. Cannot mint.' },
    { agent: 'return-points', role: 'Verify and sign returns', ceiling: 'Attest returns at their own location, nothing else.' },
    { agent: 'hauler-fleet', role: 'Moves material, signs custody', ceiling: 'Its own handoffs; paid on attested weight.' },
    { agent: 'processor-intake', role: 'Signs intake and output', ceiling: 'Attestations on its own gates.' },
  ],
  loom: {
    nodes: [
      { id: 'producer', label: 'producer', sub: 'ships, deposits', kind: 'external', x: 118, y: 220 },
      { id: 'escrow', label: 'Deposit escrow', sub: 'one per container', kind: 'teg', x: 336, y: 110 },
      { id: 'gate', label: 'Return gate', sub: 'verified, once', kind: 'gate', x: 560, y: 110 },
      { id: 'point', label: 'return-point', sub: 'signs the return', kind: 'agent', x: 336, y: 330 },
      { id: 'hauler', label: 'hauler', sub: 'signed custody', kind: 'agent', x: 118, y: 450 },
      { id: 'refund', label: 'Refund release', sub: 'loop closed', kind: 'teg', x: 764, y: 110 },
      { id: 'ledger', label: 'Recovery ledger', sub: 'audit is a query', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-deposit', from: 'producer', to: 'escrow', label: 'deposit, escrowed' },
      { id: 'e-return', from: 'point', to: 'gate', label: 'return, signed' },
      { id: 'e-custody', from: 'hauler', to: 'point', label: 'custody handoff' },
      { id: 'e-refund', from: 'gate', to: 'refund' },
      { id: 'e-emit', from: 'refund', to: 'ledger' },
      { id: 'a-double', from: 'point', to: 'refund', attackOnly: true, label: 'claim the refund twice', curve: 60 },
    ],
    script: [
      { edge: 'e-deposit', state: 'active', dwellMs: 1400, caption: 'The deposit escrows when the container ships. It is visible, not pooled away.' },
      { edge: 'e-custody', state: 'active', dwellMs: 1400, caption: 'Custody is signed handoffs: round, station, processor.' },
      { edge: 'e-return', state: 'active', dwellMs: 1400, caption: 'A registered return point verifies and signs the return.' },
      { edge: 'e-refund', state: 'active', dwellMs: 1300, caption: 'The refund releases. One container, one refund.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'Recovery is a ledger fact. The quarterly report is a query.' },
    ],
  },
  attacks: [
    {
      title: 'The container that returned twice',
      attack: 'A fraud ring re-presents redeemed container identities across different return points to drain the deposit pool a second time.',
      mechanism: 'A refund is keyed to the container identity and released from its own escrow exactly once; the second claim finds the escrow already settled. The idempotency machinery that absorbs honest retries is the same machinery that refuses dishonest ones, and the ring’s correlated claims are a shape the daily graph sweep reads.',
      rail: 'S06',
      consequence: 'The duplicate claims refuse cleanly, the pool never drains, and the correlated return-point pattern lands on the fraud desk as a flagged set.',
      script: [
        { edge: 'a-double', state: 'denied', dwellMs: 1900, stopAt: 0.68, flashNode: 'gate', caption: 'S06. One container, one refund. The second claim finds the escrow already settled.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
  ],
  rails: ['S01', 'S02', 'S06', 'S08', 'S14', 'S16'],
  standup: {
    infra: 'One registry per scheme or authority; processors and haulers connect as agents.',
    agents: '4 to 6 roles; return points are the widest tier and the cheapest to run.',
    integration: 'Weighbridges, reverse vending machines and route scanners feed the attestors; the physical logistics stay as they are.',
  },
  nonClaims: [
    'OUROBOROS proves custody and closes payment loops; it does not certify that processing met any environmental standard, which remains the regulator’s test.',
    'Recovery figures are as honest as the attested weights behind them; a corrupt scale is a physical-world problem the ledger records but cannot prevent.',
  ],
  mermaid: `flowchart LR
  P["producer"] -->|"deposit per container"| TEG["deposit escrow<br/>one refund each"]
  H["hauler custody<br/>signed handoffs"] --> RP["return point<br/>verifies + signs"]
  RP -->|"verified return"| G{"return gate<br/>idempotent"}
  G -->|"release refund"| TEG
  W["weighbridge attestation"] -.->|"gates hauler payment"| CS["milestone contract"]
  TEG --> ES[("recovery ledger<br/>audit = query")]`,
  legacy: [
    { system: 'Weighbridges and route scanners', connect: 'Instrument reads become signed custody events. The trucks keep their telematics.' },
    { system: 'Deposit scheme back offices', connect: 'Refund loops settle from escrow. The back office reconciles against a ledger that cannot fork.' },
    { system: 'Municipal billing', connect: 'Collection settlements post back as ordinary invoices while the parallel run proves the loop.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
