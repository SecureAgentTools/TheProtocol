import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Progress payments from escrow', primitive: 'Contract spine: staged strict-order milestones', railStatus: 'LIVE' as const },
  { step: 'Work evidenced, not invoiced', primitive: 'Signed attestations from inspection agents', railStatus: 'LIVE' as const },
  { step: 'Retention held honestly', primitive: 'A final milestone the ledger cannot forget', railStatus: 'LIVE' as const },
  { step: 'Contested work freezes', primitive: 'Four-phase dispute; the ruling drives the split, once', railStatus: 'LIVE' as const },
  { step: 'Subcontractor chains', primitive: 'Sub-agreements as contracts on the same rails', railStatus: 'LIVE' as const },
  { step: 'A named engineer behind sign-off', primitive: 'Cockpit Card mandate with presence proof', railStatus: 'LIVE (gated)' as const },
]

export const keystone: Blueprint = {
  id: 'keystone',
  tier: 2,
  vault: true,
  rank: 14,
  industry: 'Construction',
  systemName: 'KEYSTONE',
  promise: 'Progress payments that release on evidenced work, and retention money nobody can quietly forget.',
  cases: [
    { role: 'General contractor', line: 'Draws release on inspection evidence, not on chasing.' },
    { role: 'Subcontractor', line: 'Your milestone money is visible in escrow before you pour.' },
    { role: 'Project owner and lender', line: 'A draw schedule that is a ledger, not a spreadsheet.' },
    { role: 'Site inspection', line: 'Sign-offs from named engineers whose presence signs.' },
  ],
  problem:
    'Construction runs on progress payments that arrive late, retention money that arrives never, and a paper trail that turns adversarial exactly when it matters. The subcontractor three tiers down finances everyone above them, involuntarily.',
  system: [
    'KEYSTONE runs a 40-storey build as a tree of escrowed contracts. The owner funds the general contract; the general contractor mirrors its obligations down to nineteen subcontractors as contracts on the same rails, so the concrete crew can see its milestone money sitting in escrow before the first pour. Draw twelve releases when the inspection agent submits sensor and photo evidence and the owner’s draw agent releases it. That agent is a sub-agent of the owner’s account with no wallet of its own, and the supervising engineer, a named human, underwrites the account, so a release above the threshold waits for the engineer’s presence to sign.',
    'The retention is the design’s quiet victory: five percent sits as a final milestone that cannot be forgotten, renegotiated in a hallway, or lost in an acquisition, because it is not a promise in a PDF. It is value on a ledger with a release condition. When the facade dispute arrives in month fourteen, that work’s money freezes, the arbiter rules, the escrow splits per the ruling exactly once, and every other trade keeps getting paid on schedule.',
  ],
  cast: [
    { agent: 'owner-desk', role: 'Funds the master contract', ceiling: 'Fund and structure. Cannot self-release.' },
    { agent: 'gc-ops', role: 'Mirrors obligations to subcontracts', ceiling: 'Structure sub-escrows from funded milestones only.' },
    { agent: 'sub-crew (x19)', role: 'Delivers work, claims draws', ceiling: 'Claim against own evidenced milestones.' },
    { agent: 'inspection-agent', role: 'Submits site evidence', ceiling: 'Attest only. No release authority.' },
    { agent: 'engineer (human)', role: 'Signs off above threshold', ceiling: 'Cockpit mandate scoped to this project. Presence required.' },
  ],
  loom: {
    nodes: [
      { id: 'owner', label: 'owner', sub: 'funds the build', kind: 'external', x: 118, y: 110 },
      { id: 'escrow', label: 'Draw escrow', sub: 'visible to all tiers', kind: 'teg', x: 336, y: 110 },
      { id: 'gate', label: 'Draw gate', sub: 'evidence + engineer', kind: 'gate', x: 560, y: 220 },
      { id: 'inspect', label: 'inspection-agent', sub: 'site evidence', kind: 'agent', x: 118, y: 330 },
      { id: 'engineer', label: 'engineer', sub: 'presence signs', kind: 'human', x: 560, y: 110 },
      { id: 'sub', label: 'sub-crew', sub: 'the concrete pour', kind: 'agent', x: 336, y: 220 },
      { id: 'release', label: 'Draw 12', sub: 'to the crew', kind: 'teg', x: 764, y: 220 },
      { id: 'ledger', label: 'Project ledger', sub: 'retention lives here', kind: 'ledger', x: 764, y: 110 },
    ],
    edges: [
      { id: 'e-fund', from: 'owner', to: 'escrow' },
      { id: 'e-work', from: 'sub', to: 'gate', label: 'claims draw 12' },
      { id: 'e-evidence', from: 'inspect', to: 'gate', label: 'sensors + photos', curve: 16 },
      { id: 'e-sign', from: 'engineer', to: 'gate', label: 'presence sign-off' },
      { id: 'e-release', from: 'gate', to: 'release' },
      { id: 'e-emit', from: 'release', to: 'ledger' },
      { id: 'a-forget', from: 'owner', to: 'ledger', attackOnly: true, label: 'forget the retention', curve: -120, labelT: 0.3 },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'The build funds as escrow, mirrored down nineteen subcontracts.' },
      { edge: 'e-work', state: 'active', dwellMs: 1300, caption: 'The crew claims draw twelve. Their money was visible before the pour.' },
      { edge: 'e-evidence', state: 'active', dwellMs: 1400, caption: 'Inspection submits the site evidence.' },
      { edge: 'e-sign', state: 'active', dwellMs: 1400, caption: 'A named engineer signs, presence proven above the threshold.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'The draw releases on evidence, on schedule.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1500, caption: 'Retention sits as a final milestone the ledger cannot forget.' },
    ],
  },
  attacks: [
    {
      title: 'The forgotten retention',
      attack: 'Two years after handover, the owner’s new management declines to remember the five percent retention owed to nineteen trades.',
      mechanism: 'The retention is not an entry in the owner’s accounting; it is escrowed value on a shared ledger with a release condition. Forgetting it is not an available operation, and unwinding it would require the counterparties’ own contracts to agree.',
      rail: 'S14',
      consequence: 'The retention releases when its condition is met, to the trades it belongs to, regardless of who now sits at the owner’s desk.',
      script: [
        { edge: 'a-forget', state: 'denied', dwellMs: 1900, stopAt: 0.7, flashNode: 'ledger', caption: 'S14. Retention is escrowed value with a condition, not a memory. It cannot be forgotten.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
  ],
  rails: ['S01', 'S05', 'S06', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'One registry per project or per firm. The subcontract tree is data, not deployments.',
    agents: '5 roles; inspection hardware feeds the attestor.',
    integration: 'Scheduling and BIM stay where they are. The protocol carries agreement, evidence and money.',
  },
  nonClaims: [
    'KEYSTONE does not certify structural work and replaces no building authority or engineer-of-record duty.',
    'Lien law and statutory retention regimes vary; the escrow implements the agreement, and counsel maps it to the jurisdiction.',
  ],
  mermaid: `flowchart LR
  O["owner"] -->|"fund master contract"| CS["contract spine<br/>strict-order draws"]
  CS -->|"mirrored sub-escrows"| SUB["19 subcontracts<br/>same rails"]
  I["inspection agent"] -->|"signed site evidence"| G{"draw gate"}
  E["engineer mandate<br/>presence proof"] --> G
  G -->|"release draw"| TEG["TEG escrow mover"]
  TEG --> ES[("project ledger<br/>retention milestone")]
  DIS["dispute"] -.->|"ruling splits escrow once"| TEG`,
  legacy: [
    { system: 'Scheduling and BIM', connect: 'The model and the programme stay authoritative. Evidenced progress releases payments against them.' },
    { system: 'ERP and subcontractor ledgers', connect: 'Progress payments and retention settle from escrow and post back as certified.' },
    { system: 'Site verification (photo, drone, IoT)', connect: 'Site evidence lands as signed attestations tied to milestones.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
