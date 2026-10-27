import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Licensed per use', primitive: 'A2A payment authorization: apt_ authorization, hashed, short TTL', railStatus: 'LIVE' as const },
  { step: 'The royalty cannot be skipped', primitive: 'Royalty carved at settlement by the rail, basis points, capped', railStatus: 'LIVE (gated)' as const },
  { step: 'Derivatives carry lineage', primitive: 'Fork, spawn, adoption quorum, royalty up the chain', railStatus: 'LIVE' as const },
  { step: 'Provenance forever', primitive: 'Immutable ledger as the chain of custody', railStatus: 'LIVE' as const },
  { step: 'Templates as products', primitive: 'Marketplace bundles, purchase and fork', railStatus: 'LIVE' as const },
]

export const atelier: Blueprint = {
  id: 'atelier',
  tier: 2,
  rank: 7,
  industry: 'Media, IP and Creative Licensing',
  systemName: 'ATELIER',
  promise: 'Royalties carved by the settlement rail itself, so under-reporting cannot settle at all.',
  cases: [
    { role: 'Stock media library', line: 'Per-use licensing where the royalty is the settlement itself.' },
    { role: 'Model and LoRA marketplace', line: 'Derivatives carry lineage, and ancestors are paid automatically.' },
    { role: 'Music sampling and beats', line: 'Clear a sample by paying it, not by chasing it.' },
    { role: 'Font foundry', line: 'Under-reporting cannot settle, so it cannot license.' },
  ],
  problem:
    'Royalties are an honour system with a reporting lag measured in quarters. The licensee counts the uses, the licensor invoices what was counted, and the audit clause is the only enforcement, exercised roughly never.',
  system: [
    'ATELIER is a licensing house for 9,000 works: voice models, illustration styles, sample libraries, prompt architectures. A client agent licenses a work per use through a payment authorization that lives fifteen minutes and settles through the same rail that moves every other unit in the network. The royalty is not reported by the licensee afterwards. It is carved at settlement, in basis points, by the rail itself, which means the only way to under-report is to fail to settle, and failing to settle means no licence.',
    'Derivatives are first-class. A studio forks a voice model, the fork carries its lineage on the ledger, and when the derivative is paid, the royalty flows up the chain to the original automatically. This is not a proposal: the same fork, quorum and royalty machinery already runs the network’s own evolution arenas, where coding agents fork themselves and their descendants pay their ancestors.',
  ],
  cast: [
    { agent: 'atelier-verse', role: 'Holds the catalogue, issues licences', ceiling: 'Licence issue and price. Cannot touch a settled royalty split.' },
    { agent: 'client-agent', role: 'Uses works, pays per use', ceiling: 'Pay and consume. The authorization is single-purpose and expires.' },
    { agent: 'studio-fork', role: 'Builds derivatives', ceiling: 'Fork with lineage. The ancestor’s cut is not its to set.' },
    { agent: 'royalty-audit', role: 'Reconciles the chain', ceiling: 'Read-only over settlements and lineage.' },
  ],
  loom: {
    nodes: [
      { id: 'creator', label: 'atelier-verse', sub: 'the work', kind: 'agent', x: 336, y: 110 },
      { id: 'lic', label: 'Licence gate', sub: 'payment authorization, 15 min', kind: 'gate', x: 336, y: 330 },
      { id: 'user', label: 'client-agent', sub: 'uses the work', kind: 'agent', x: 118, y: 220 },
      { id: 'settle', label: 'Settle', sub: 'royalty carved', kind: 'teg', x: 560, y: 220 },
      { id: 'ledger', label: 'Provenance', sub: 'lineage on ledger', kind: 'ledger', x: 560, y: 330 },
      { id: 'fork', label: 'derivative', sub: 'pays its ancestor', kind: 'agent', x: 764, y: 220 },
    ],
    edges: [
      { id: 'e-ask', from: 'user', to: 'lic', label: 'requests use' },
      { id: 'e-use', from: 'lic', to: 'settle', label: 'authorized' },
      { id: 'e-royal', from: 'settle', to: 'creator', label: 'royalty, in-rail' },
      { id: 'e-emit', from: 'settle', to: 'ledger' },
      { id: 'e-fork', from: 'ledger', to: 'fork', label: 'lineage recorded' },
      { id: 'a-under', from: 'user', to: 'settle', attackOnly: true, label: 'settle without the carve', curve: -40 },
    ],
    script: [
      { edge: 'e-ask', state: 'active', dwellMs: 1400, caption: 'A client agent asks to use a voice model. The authorization lives fifteen minutes.' },
      { edge: 'e-use', state: 'active', dwellMs: 1300, caption: 'Authorized use settles through the network’s own rail.' },
      { edge: 'e-royal', state: 'active', dwellMs: 1400, caption: 'The royalty is carved by the settlement itself, in basis points.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'Use and split land on the ledger.' },
      { edge: 'e-fork', state: 'active', dwellMs: 1500, caption: 'A derivative forks with lineage. Its income pays its ancestor, automatically.' },
    ],
  },
  attacks: [
    {
      title: 'The creative accountant',
      attack: 'The licensee’s agent attempts to settle a use with the royalty split stripped out.',
      mechanism: 'The royalty is not a report the licensee files; it is a carve the settlement rail performs atomically with the payment. A settlement without the carve is not a smaller settlement, it is not a settlement.',
      rail: 'S15',
      consequence: 'No settlement, no licence, no use. The attempted call is on the ledger, and the honour system is nowhere in the loop.',
      script: [
        { edge: 'a-under', state: 'denied', dwellMs: 1900, stopAt: 0.7, flashNode: 'settle', caption: 'The carve is atomic with the payment. Without it, nothing settles and nothing is licensed.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' },
  ],
  rails: ['S01', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'A hosted registry is enough. Run your own when the catalogue justifies it.',
    agents: '3 roles to start: the catalogue, the licence gate, the audit reader.',
    integration: 'Your asset pipeline and delivery CDN. Rights metadata is the real work.',
  },
  nonClaims: [
    'ATELIER makes no copyright determination and clears no rights.',
    'No assertion about collecting-society compatibility. The rail enforces the split that was agreed; agreeing it remains a human act.',
  ],
  mermaid: `flowchart LR
  C["client agent"] -->|"POST /a2a-payment/authorize"| T["apt_ authorization<br/>SHA-256 stored, 15 min TTL"]
  T -->|"verify + consume"| W["licensed work"]
  W -->|"settle via /teg/transfer"| TEG["TEG settlement<br/>royalty carve, bps, capped"]
  TEG -->|"split to creator + ancestors"| ES[("event store<br/>lineage + provenance")]
  F["forked derivative"] -.->|"forge lineage machinery"| ES`,
  legacy: [
    { system: 'DAM and asset pipelines', connect: 'Assets and masters stay in the pipeline. The protocol carries licences, uses and the carve.' },
    { system: 'Rights management databases', connect: 'Rights metadata exports into licence templates. The settlement rail enforces what the database could only record.' },
    { system: 'CDN delivery logs', connect: 'Delivery counts become signed usage attestations that the per-use rail settles against.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
