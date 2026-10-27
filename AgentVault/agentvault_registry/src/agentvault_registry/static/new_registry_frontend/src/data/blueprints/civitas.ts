import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'The city is not a tenant', primitive: 'Sovereign frame: own hardware, own unit of account, own governance', railStatus: 'LIVE' as const },
  { step: 'What we will not run, in public', primitive: 'Jurisdiction profile signed into the registry card', railStatus: 'SHADOW' as const, href: '/.well-known/registry-card.json' },
  { step: 'Procurement on milestones', primitive: 'Contract spine: escrow at award, staged releases', railStatus: 'LIVE' as const },
  { step: 'No single officer acts alone', primitive: 'Two-man enforcement: approval is the execution', railStatus: 'LIVE' as const },
  { step: 'Citizen-readable trail', primitive: 'Immutable event ledger, forensic search', railStatus: 'LIVE' as const },
  { step: 'Rule changes with quorum', primitive: 'Governance: member votes, quorum, veto', railStatus: 'LIVE' as const },
]

export const civitas: Blueprint = {
  id: 'civitas',
  tier: 2,
  rank: 6,
  industry: 'Public Sector, Procurement and Civic Infrastructure',
  systemName: 'CIVITAS',
  promise: 'A city that runs its own frame, publishes what it will not do, and pays vendors out of visible escrow.',
  cases: [
    { role: 'City procurement office', line: 'Vendors paid from escrow the council can see.' },
    { role: 'Public works department', line: 'Sensor-evidenced milestones on road and rail contracts.' },
    { role: 'Grants administration', line: 'Disbursement where no single officer can act alone.' },
    { role: 'Municipal utility', line: 'A sovereign frame under local law, federated with the region.' },
  ],
  problem:
    'Government cannot be a tenant in a vendor’s database, and every automation proposal eventually founders on that. The second blocker is quieter: a civil service cannot adopt a system in which one compromised account can move public money alone.',
  system: [
    'CIVITAS is a city of 400,000 running its own sovereign frame in its own datacenter, under its own law, with its own unit of account for internal settlement. It federates with the regional government’s frame and with its vendors’ registries bilaterally, and it has published, in a cryptographically signed declaration anyone can fetch, the list of features this deployment will never run. The declaration is not a policy PDF. It travels inside the registry card, signed, and peers can detect drift from it.',
    'A road resurfacing contract is awarded on a Tuesday: the budget enters escrow at award, visible to the council and to anyone else who cares to look. The vendor’s paving agents submit each section with sensor evidence; an inspection agent verifies; releases follow the milestones. When an officer moves to debar a supplier in November, the action does not execute. It queues, and a second officer’s approval is the execution, because in this design no enforcement is a single identity’s act.',
  ],
  cast: [
    { agent: 'procurement-desk', role: 'Awards contracts, funds escrow', ceiling: 'Award and fund within budget lines. Cannot release to itself.' },
    { agent: 'vendor-paving', role: 'Submits milestones with evidence', ceiling: 'Submit only, on its own contracts.' },
    { agent: 'inspection-3', role: 'Verifies delivered work', ceiling: 'Verify. Holds no release authority.' },
    { agent: 'officer, second officer (humans)', role: 'Enforcement, two identities', ceiling: 'File and approve are different people. Approval is the execution.' },
  ],
  loom: {
    nodes: [
      { id: 'authority', label: 'City frame', sub: 'sovereign deployment', kind: 'registry', x: 118, y: 110 },
      { id: 'decl', label: 'Public declaration', sub: 'signed into the card', kind: 'external', x: 560, y: 110 },
      { id: 'officer', label: 'officer', sub: 'files the action', kind: 'human', x: 764, y: 110 },
      { id: 'vendor', label: 'vendor-paving', sub: 'submits sections', kind: 'agent', x: 118, y: 220 },
      { id: 'pgate', label: 'Procurement gate', sub: 'milestones, verified', kind: 'gate', x: 336, y: 330 },
      { id: 'pay', label: 'Milestone release', sub: 'from visible escrow', kind: 'teg', x: 560, y: 330 },
      { id: 'ledger', label: 'Audit trail', sub: 'citizen-readable', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-declare', from: 'authority', to: 'decl', label: 'what we will not run' },
      { id: 'e-bid', from: 'vendor', to: 'pgate', label: 'section + evidence' },
      { id: 'e-pay', from: 'pgate', to: 'pay' },
      { id: 'e-emit', from: 'pay', to: 'ledger' },
      { id: 'a-solo', from: 'officer', to: 'pay', attackOnly: true, label: 'debar and seize, alone' },
    ],
    script: [
      { edge: 'e-declare', state: 'active', dwellMs: 1600, caption: 'The deployment declares, in a signed public document, what it will never run.' },
      { edge: 'e-bid', state: 'active', dwellMs: 1400, caption: 'The vendor submits a section with sensor evidence. Inspection verifies.' },
      { edge: 'e-pay', state: 'active', dwellMs: 1300, caption: 'Release follows the milestone, out of escrow the council can see.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1500, caption: 'Every award, release and refusal is on a ledger citizens can read.' },
    ],
  },
  attacks: [
    {
      title: 'The single-officer seizure',
      attack: 'One compromised officer account files a debarment against a vendor and tries to execute it in the same breath.',
      mechanism: 'Enforcement actions queue for a second approver, and the approval is the execution. There is no code path in which filing and executing are the same identity.',
      rail: 'S17',
      riskRef: 'R-OP-05',
      consequence: 'The action sits visibly in the pending queue. The vendor’s escrow does not move, and the attempt itself is on the ledger.',
      script: [
        { edge: 'a-solo', state: 'denied', dwellMs: 1900, stopAt: 0.6, flashNode: 'pgate', caption: 'S17. Filing is not executing. A second identity’s approval is the execution.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Jurisdiction Profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S10', 'S11', 'S14', 'S16', 'S17'],
  standup: {
    infra: 'The city’s own frame on municipal hardware, federated bilaterally.',
    agents: '4 to 6 roles across procurement, inspection and enforcement.',
    integration: 'The ERP and the tender platform. Procurement law stays with the lawyers.',
  },
  nonClaims: [
    'Jurisdiction profiles are operator-declared. We publish mechanism and neutral examples, never per-country legal conclusions.',
    'CIVITAS does not conduct tenders and does not replace procurement law or review bodies.',
  ],
  mermaid: `flowchart LR
  CF["city frame<br/>sovereign, own unit"] -->|"jurisdiction profile<br/>EdDSA-signed"| CARD["registry card<br/>/.well-known/registry-card.json"]
  V["vendor agents"] -->|"milestone submit + evidence"| CS["contract spine<br/>escrow at award"]
  CS -->|"verified release"| TEG["TEG escrow mover"]
  OFF["officer"] -->|"enforcement files"| Q{"pending queue<br/>two-man rule"}
  Q -->|"second identity approves = executes"| ENF["coordinated action"]
  TEG --> ES[("event ledger<br/>citizen-readable")]`,
  legacy: [
    { system: 'The city ERP and finance system', connect: 'Budgets and appropriations stay in the ERP. Vendor payments settle from visible escrow and post back as paid invoices.' },
    { system: 'Tender and e-procurement platforms', connect: 'Tenders publish where they always did. Awards become contracts with escrow at agreement.' },
    { system: 'Open data portals', connect: 'The ledger\'s public read side feeds the portal. Citizens read the same record the auditor does.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
