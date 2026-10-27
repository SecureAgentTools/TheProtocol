import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'A lot is a chain of attested handoffs', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'Offtake money held ahead of harvest', primitive: 'Escrowed forward agreements with staged release', railStatus: 'LIVE' as const },
  { step: 'Weather and price triggers', primitive: 'Oracle agents with signed readings at contract gates', railStatus: 'LIVE' as const },
  { step: 'Cooperatives with real books', primitive: 'Organizations: shared treasuries, member votes, distributions', railStatus: 'LIVE' as const },
  { step: 'Cross-border settlement', primitive: 'Cross-registry transfer with exactly-once semantics', railStatus: 'LIVE' as const },
  { step: 'Disputes with evidence', primitive: 'Four-phase dispute over any contested lot', railStatus: 'LIVE' as const },
]

export const demeter: Blueprint = {
  id: 'demeter',
  tier: 2,
  vault: true,
  rank: 18,
  industry: 'Agriculture and Food Provenance',
  systemName: 'DEMETER',
  promise: 'From field to shelf as a chain of signed handoffs, with the farmer paid from escrow, not from patience.',
  cases: [
    { role: 'Grower cooperative', line: 'A shared treasury with member votes.' },
    { role: 'Commodity buyer', line: 'Forward agreements escrowed before planting, released on delivery.' },
    { role: 'Food brand and retailer', line: 'Provenance as verifiable handoffs, not a printed story.' },
    { role: 'Rainfall and weather services', line: 'Signed readings that a drought clause reads, under their own identity.' },
  ],
  problem:
    'The farmer sells at harvest for whatever the day offers, waits months for payment, and the provenance story on the package is marketing. Every certification scheme bolts paper onto a supply chain that has no shared record, so fraud costs pennies and trust costs audits.',
  system: [
    'DEMETER follows lot 88-K, four tonnes of coffee, from a cooperative in the highlands to a roaster in Hamburg. The forward agreement was escrowed before planting: the buyer’s money sat visible to the cooperative all season, releasing in stages as signed handoffs accumulated: the wet mill weighs and signs, the dry mill signs, the exporter signs, the container attests its seal, the roaster signs receipt. The lot’s provenance is not a claim printed on the bag. It is the chain itself, replayable by anyone the roaster hands the reference to.',
    'The cooperative is an organization with a treasury its members vote, so the season’s premium lands as a recorded distribution rather than a promise from the chairman. When the drought year comes, the forward agreement’s drought clause reads the oracle’s signed rainfall against its frozen terms, and the buyer’s advance reaches the growers from the season escrow before a bank would have finished asking for collateral. Every unit of all of it is conserved, on a ledger where an audit is a query.',
  ],
  cast: [
    { agent: 'coop-treasury', role: 'Holds and distributes the cooperative’s funds', ceiling: 'Org treasury rails; members vote distributions.' },
    { agent: 'buyer-desk', role: 'Escrows forward agreements', ceiling: 'Fund and claim delivery on its own contracts.' },
    { agent: 'handoff-attestors', role: 'Mill, exporter, container, roaster', ceiling: 'Sign their own handoff, nothing else.' },
    { agent: 'oracle-weather', role: 'Signs rainfall readings', ceiling: 'Attestations only. No release authority.' },
  ],
  loom: {
    nodes: [
      { id: 'coop', label: 'cooperative', sub: 'org with a treasury', kind: 'agent', x: 118, y: 220 },
      { id: 'escrow', label: 'Forward escrow', sub: 'funded pre-planting', kind: 'teg', x: 336, y: 110 },
      { id: 'gate', label: 'Handoff gate', sub: 'signed chain', kind: 'gate', x: 560, y: 110 },
      { id: 'mill', label: 'wet mill', sub: 'weighs and signs', kind: 'agent', x: 336, y: 330 },
      { id: 'roaster', label: 'roaster', sub: 'signs receipt', kind: 'external', x: 118, y: 330 },
      { id: 'release', label: 'Staged release', sub: 'to the growers', kind: 'teg', x: 764, y: 110 },
      { id: 'ledger', label: 'Provenance chain', sub: 'lot 88-K, replayable', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-fund', from: 'coop', to: 'escrow', label: 'agreement, escrowed' },
      { id: 'e-mill', from: 'mill', to: 'gate', label: 'weighed, signed' },
      { id: 'e-receipt', from: 'roaster', to: 'gate', label: 'receipt, signed', curve: -24 },
      { id: 'e-release', from: 'gate', to: 'release' },
      { id: 'e-emit', from: 'release', to: 'ledger' },
      { id: 'a-story', from: 'roaster', to: 'ledger', attackOnly: true, label: 'invent a provenance', curve: 108 },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'The forward agreement escrows before planting. The money is visible all season.' },
      { edge: 'e-mill', state: 'active', dwellMs: 1400, caption: 'Each handoff signs: wet mill, dry mill, exporter, container.' },
      { edge: 'e-receipt', state: 'active', dwellMs: 1400, caption: 'The roaster signs receipt in Hamburg.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'Stages release as the chain accumulates.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'Provenance is the chain itself, replayable by anyone.' },
    ],
  },
  attacks: [
    {
      title: 'The invented single-origin',
      attack: 'A trader relabels bulk commodity as lot 88-K single-origin and offers the story to a premium buyer.',
      mechanism: 'Lot 88-K’s chain names its signers, and the trader is not one of them. A provenance here is not a narrative attached to goods; it is a set of signatures the goods either carry or do not, checkable in seconds from the reference.',
      rail: 'S14',
      consequence: 'The premium buyer replays the real chain, the invented story matches nothing, and the cooperative’s premium stays attached to the beans it was paid for.',
      script: [
        { edge: 'a-story', state: 'denied', dwellMs: 1900, stopAt: 0.7, flashNode: 'ledger', caption: 'S14. A provenance is signatures, not a story. This lot carries none of yours.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
  ],
  rails: ['S01', 'S02', 'S13', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A registry per exporter or cooperative federation; buyers connect from theirs.',
    agents: '4 to 6 roles; the attestors follow the physical handoffs that already exist.',
    integration: 'Scales, moisture meters and cold chain feed the attestors. Agronomy stays in the field.',
  },
  nonClaims: [
    'DEMETER records signed handoffs; it does not certify organic, fair-trade or any labelling regime, and it replaces no food-safety authority.',
    'A chain proves custody as signed. What was true before the first signature remains a physical-world question.',
  ],
  mermaid: `flowchart LR
  B["buyer registry"] -->|"forward agreement, escrowed"| CS["contract spine<br/>staged releases"]
  M["mill / exporter / container<br/>signed handoffs"] -->|"attestations"| G{"handoff gate"}
  G -->|"stage release"| TEG["TEG escrow mover"]
  TEG -->|"distribution to members"| ORG["cooperative org<br/>treasury + votes"]
  O["weather oracle"] -.->|"signed readings"| CS
  TEG --> ES[("provenance chain<br/>lot 88-K, replayable")]`,
  legacy: [
    { system: 'Farm management systems', connect: 'Agronomy stays in the field tools. Handoffs and payment ride the rails.' },
    { system: 'Scales, moisture meters and cold chain', connect: 'Instrument reads become the signed attestations escrow releases against.' },
    { system: 'Commodity buyer ERPs', connect: 'Buyers keep purchasing in their ERP. The farmer is paid from escrow at the evidenced handoff.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
