import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Funds held, not wired', primitive: 'Escrowed tranches, released per attested delivery', railStatus: 'LIVE' as const },
  { step: 'Delivery attested at the edge', primitive: 'Signed attestations from field agents with SPIFFE identity', railStatus: 'LIVE' as const },
  { step: 'Every unit accounted', primitive: 'Delta = 0 supply invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Diversion ends participation', primitive: 'Licence revocation: economic quarantine, records survive', railStatus: 'LIVE' as const },
  { step: 'Local partners stay sovereign', primitive: 'Own registries, bilateral federation, declared profiles', railStatus: 'LIVE' as const },
  { step: 'Donor-readable trail', primitive: 'Immutable ledger, forensic search per grant', railStatus: 'LIVE' as const },
]

export const lifeline: Blueprint = {
  id: 'lifeline',
  tier: 2,
  vault: true,
  rank: 13,
  industry: 'Humanitarian Aid Distribution',
  systemName: 'LIFELINE',
  promise: 'Aid money that cannot vanish between the donor and the delivery, on rails everyone can audit.',
  cases: [
    { role: 'International NGO', line: 'Tranches release on attested delivery, not on invoices.' },
    { role: 'Donor government', line: 'A ledger you can read instead of a report you must trust.' },
    { role: 'Local implementing partner', line: 'Your own registry, your own sovereignty, paid on proof.' },
    { role: 'Field logistics', line: 'Trucks and warehouses attest handoffs with signed identities.' },
  ],
  problem:
    'Between a donor and a delivered sack of grain sit four intermediaries, three currencies, and a reporting chain built from photographed receipts. Diversion is discovered in audits a year later, if at all, and the honest majority of implementers pays the reputational bill for the dishonest few.',
  system: [
    'LIFELINE moves a 2.4 million unit drought response through registries run by the donor, two NGOs, and nine local implementing partners, each sovereign, each federated bilaterally. The grant is a contract with escrowed tranches. Nothing is wired ahead: tranche three exists on the ledger, visible to every party, and releases only when field agents holding their own signed identities attest that distribution eleven actually happened, at the site, on the day.',
    'In week six a partner’s numbers stop matching its attestations. Nobody files a lawsuit first. Its licence suspends, its ability to receive further tranches ends within a sync cycle, and every unit it already touched remains on a ledger the donor, the auditor and the press can read. The remaining partners keep operating uninterrupted, because quarantine here is per-participant, economic, and reversible on evidence. The final report to the donor is not a PDF of claims. It is a query.',
  ],
  cast: [
    { agent: 'grant-desk', role: 'Funds tranches, sets milestones', ceiling: 'Fund and structure. Cannot attest delivery.' },
    { agent: 'partner-ops', role: 'Runs distributions, claims tranches', ceiling: 'Claim only, against its own attested deliveries.' },
    { agent: 'field-attestor', role: 'Attests handoffs on site', ceiling: 'Signed attestations, one distribution at a time. No release authority.' },
    { agent: 'donor-watch', role: 'Reads everything', ceiling: 'Read-only across the grant, by design.' },
  ],
  loom: {
    nodes: [
      { id: 'donor', label: 'donor', sub: 'funds the grant', kind: 'external', x: 118, y: 110 },
      { id: 'escrow', label: 'Tranche escrow', sub: 'held, visible', kind: 'teg', x: 764, y: 110 },
      { id: 'gate', label: 'Delivery gate', sub: 'attested only', kind: 'gate', x: 560, y: 220 },
      { id: 'field', label: 'field-attestor', sub: 'on site, signed', kind: 'agent', x: 118, y: 330 },
      { id: 'partner', label: 'partner-ops', sub: 'local, sovereign', kind: 'agent', x: 336, y: 220 },
      { id: 'release', label: 'Release', sub: 'tranche three', kind: 'teg', x: 764, y: 220 },
      { id: 'ledger', label: 'Grant ledger', sub: 'donor-readable', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-fund', from: 'donor', to: 'escrow', label: '2.4M, escrowed' },
      { id: 'e-attest', from: 'field', to: 'gate', label: 'distribution 11, signed', curve: 10 },
      { id: 'e-claim', from: 'partner', to: 'gate', label: 'claims tranche', labelT: 0.55 },
      { id: 'e-release', from: 'gate', to: 'release' },
      { id: 'e-emit', from: 'release', to: 'ledger' },
      { id: 'a-divert', from: 'partner', to: 'release', attackOnly: true, label: 'claim without delivery', curve: -100 },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'The grant funds as escrow. Nothing is wired ahead of proof.' },
      { edge: 'e-attest', state: 'active', dwellMs: 1500, caption: 'Field agents attest the distribution with their own signed identities.' },
      { edge: 'e-claim', state: 'active', dwellMs: 1300, caption: 'The partner claims against its attested delivery.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'Tranche three releases on evidence, not on invoices.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'The donor reads a ledger, not a report.' },
    ],
  },
  attacks: [
    {
      title: 'The paper distribution',
      attack: 'A partner claims tranche four for a distribution that never happened, backed by nothing but its own report.',
      mechanism: 'The delivery gate accepts attestations, not reports, and the attestors are separate identities the partner does not control. A claim without matching attestations never reaches the escrow, and a partner whose numbers drift from its attestations is quarantined economically within a sync cycle.',
      rail: 'S11',
      consequence: 'The tranche stays in escrow for a partner who can prove delivery. Every unit the diverting partner already touched stays on a ledger the donor and the press can read.',
      script: [
        { edge: 'a-divert', state: 'denied', dwellMs: 1900, stopAt: 0.62, flashNode: 'gate', caption: 'S11. A claim without attestation never reaches the money, and drift ends participation.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Jurisdiction Profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S02', 'S11', 'S13', 'S14', 'S16'],
  standup: {
    infra: 'One registry per implementing partner, free licence, federated with the donor frame.',
    agents: '4 roles. The field attestors are the design work, and phones can carry them.',
    integration: 'Beneficiary registration and last-mile logistics stay with the humanitarian systems built for them.',
  },
  nonClaims: [
    'LIFELINE moves and audits the money. It does not verify need, select beneficiaries, or replace humanitarian coordination.',
    'No sanctions-screening claim: screening obligations remain with the transacting organisations and their own counsel.',
  ],
  mermaid: `flowchart LR
  D["donor frame"] -->|"fund grant contract"| CS["contract spine<br/>escrowed tranches"]
  F["field attestors<br/>SPIFFE identities"] -->|"signed delivery attestations"| G{"delivery gate"}
  P["partner registry<br/>sovereign, licensed"] -->|"tranche claim"| G
  G -->|"release on evidence"| TEG["TEG escrow mover"]
  TEG --> ES[("grant ledger<br/>donor-readable")]
  Q["licence drift"] -.->|"economic quarantine"| P`,
  legacy: [
    { system: 'Beneficiary registration systems', connect: 'Registration stays in the humanitarian systems built for it. The rails carry tranches, attestations and the public mirror.' },
    { system: 'Donor grant management', connect: 'The grant contract mirrors the award letter. Every release is a signed public event.' },
    { system: 'Field logistics and last-mile tools', connect: 'Delivery confirmations become field attestations. The trucks and the apps stay as they are.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
