import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Every actor identified', primitive: 'SPIFFE identity per workload, mTLS between all of them', railStatus: 'LIVE' as const },
  { step: 'Scoped, revocable authority', primitive: 'IRONKEY roles and L4 capability permits', railStatus: 'LIVE' as const },
  { step: 'A named clinician behind escalations', primitive: 'Cockpit Card mandate with presence proof', railStatus: 'LIVE (gated)' as const },
  { step: 'Vendor settlement', primitive: 'Milestone contracts with escrow', railStatus: 'LIVE' as const },
  { step: 'Who did what, provably', primitive: 'Immutable ledger, authority snapshot per event', railStatus: 'LIVE' as const },
  { step: 'Prove compliance over data the protocol never sees', primitive: 'ZK attestations: UltraHonk verification over published circuits and keys', railStatus: 'LIVE (gated)' as const },
]

export const vigil: Blueprint = {
  id: 'vigil',
  tier: 2,
  rank: 8,
  industry: 'Healthcare and Clinical Operations',
  systemName: 'VIGIL',
  promise: 'Identity, authority and settlement for clinical operations. The records stay in the EHR, on purpose.',
  cases: [
    { role: 'Hospital group operations', line: 'Scheduling and logistics agents with declared authority ceilings.' },
    { role: 'Locum and staffing agency', line: 'Escrowed shifts, presence-signed approvals above threshold.' },
    { role: 'Medical logistics', line: 'Cold-chain attestations without ever touching a patient record.' },
    { role: 'Claims clearing', line: 'An authority snapshot on every automated claim file.' },
  ],
  problem:
    'Hospitals want autonomous scheduling, logistics and claims agents, and cannot deploy them, because nobody can say precisely what such an agent is allowed to do, who is liable when it acts, and how to switch one off in seconds. The blocker is not intelligence. It is authority.',
  system: [
    'VIGIL is the operations layer of a hospital group: scheduling agents that fill theatre slots, logistics agents that keep consumables ahead of demand, claims agents that assemble reimbursement files. Every one of them holds a scoped identity and a bounded permit, and the ones that book are the group’s own sub-agents, with no wallet of their own, so each booking answers to a named clinician’s mandate. Above the threshold the clinician’s presence signs it, and a compromised agent is revocable in under half a second.',
    'When a scheduling agent misbehaves, the response is not a meeting. Its authority is re-derived on the very request, so a booking above the threshold never reaches money without the clinician’s presence, and one coordinated action ends the identity itself in under half a second. Every gated request it made sits on the mandate’s evidence chain with an authority snapshot, which is what the incident review reads instead of reconstructing.',
    'The load-bearing sentence is the one about what VIGIL does not carry: no clinical records, no diagnoses, no patient data of any kind. The protocol moves identity, authority and money. The EHR stays the EHR, and that boundary is the design, not a limitation of it.',
  ],
  cast: [
    { agent: 'scheduling-agent', role: 'Fills theatre and locum gaps', ceiling: 'A sub-agent with no wallet: every booking answers to the clinician’s mandate. Above the threshold, nothing proceeds without the clinician’s presence.' },
    { agent: 'logistics-agent', role: 'Keeps consumables ahead of demand', ceiling: 'A budget a human declared. Reads stock levels; writes nothing clinical.' },
    { agent: 'claims-agent', role: 'Assembles reimbursement files', ceiling: 'Submits files that carry authority snapshots. Cannot approve what it assembled.' },
    { agent: 'agency-desk', role: 'The staffing agency’s counterpart', ceiling: 'Sees escrow exist before anyone travels. Paid exactly once, cross-frame.' },
  ],
  loom: {
    nodes: [
      { id: 'roster', label: 'rostering system', sub: 'read-side only', kind: 'external', x: 118, y: 110 },
      { id: 'gate', label: 'Authority gate', sub: 'ceiling, re-derived', kind: 'gate', x: 336, y: 110 },
      { id: 'escrow', label: 'Shift escrow', sub: 'funded, visible', kind: 'teg', x: 560, y: 110 },
      { id: 'settle', label: 'Settlement', sub: 'agency paid once', kind: 'teg', x: 764, y: 110 },
      { id: 'sched', label: 'scheduling-agent', sub: 'fills the gap', kind: 'agent', x: 118, y: 330 },
      { id: 'clin', label: 'named clinician', sub: 'presence signs', kind: 'human', x: 336, y: 450 },
      { id: 'ledger', label: 'Event ledger', sub: 'authority snapshots', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-gap', from: 'roster', to: 'sched' },
      { id: 'e-ask', from: 'sched', to: 'gate', label: 'book locum shift' },
      { id: 'e-mandate', from: 'clin', to: 'gate' },
      { id: 'e-escrow', from: 'gate', to: 'escrow' },
      { id: 'e-settle', from: 'escrow', to: 'settle' },
      { id: 'e-emit', from: 'settle', to: 'ledger' },
      { id: 'a-rogue', from: 'sched', to: 'escrow', attackOnly: true, label: 'phantom shifts, 02:00', curve: 32, labelT: 0.2 },
    ],
    script: [
      { edge: 'e-gap', state: 'active', dwellMs: 1400, caption: 'The rostering system shows a theatre gap. The protocol reads; it never writes.' },
      { edge: 'e-ask', state: 'active', dwellMs: 1400, caption: 'The scheduling agent moves to book a locum. Its ceiling is re-derived on this very request.' },
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'The shift is above the ceiling, so a named clinician’s presence-signed mandate stands behind it.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1300, caption: 'The shift escrows. The agency watches the money exist before anyone travels.' },
      { edge: 'e-settle', state: 'active', dwellMs: 1300, caption: 'The shift is worked; settlement crosses frames exactly once.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1500, caption: 'Every event lands with an authority snapshot. No patient record exists on this path, by design.' },
    ],
  },
  attacks: [
    {
      title: 'The stolen scheduler',
      attack: 'An attacker takes the scheduling agent’s credentials at 02:00 and tries to escrow a week of phantom locum shifts, each priced just under what a human would glance at.',
      mechanism: 'The ceiling is not a cached property of the agent; it is re-derived on the very request, and above it nothing proceeds without a presence-signed mandate from a named clinician. The phantom shifts never reach escrow, and coordinated suspension ends the stolen identity in under half a second: mTLS revoked, account suspended, cross-frame receipt blocklisted, one action.',
      rail: 'S05',
      consequence: 'No money moved and no shift ever existed. The ledger keeps every denied attempt with an authority snapshot, which is exactly the evidence the incident review wants.',
      script: [
        { edge: 'a-rogue', state: 'denied', dwellMs: 1900, stopAt: 0.6, flashNode: 'gate', caption: 'S05. The ceiling is re-derived on this request; above it, only presence signs. The identity dies in half a second.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Data Protection Policy', href: '/compliance/doc/data-protection-policy' },
  ],
  rails: ['S02', 'S03', 'S05', 'S07', 'S08', 'S14', 'S19'],
  standup: {
    infra: 'A group-run registry, federated with vendors bilaterally.',
    agents: 'Scheduling, logistics and claims roles; the ceilings are the design work.',
    integration: 'The EHR and the rostering system, read-side only. That boundary is deliberate.',
  },
  nonClaims: [
    'VIGIL stores and processes no clinical records and no patient data. That is the headline, not a footnote.',
    'No assertion of conformance with any health-data regulation; the protocol never sees the data such regulation governs.',
  ],
  mermaid: `flowchart LR
  Ros["rostering system<br/>read-side only"] -.->|"theatre gap"| S["scheduling-agent"]
  S -->|"book shift (ceiling re-derived)"| G{"authority gate"}
  Doc["named clinician"] -.->|"presence-signed mandate"| G
  G -->|"within mandate"| E["shift escrow"]
  E -->|"worked, settle exactly once"| X["cross-registry pay"]
  X --> L[("event ledger<br/>authority snapshots")]`,
  legacy: [
    { system: 'The EHR', connect: 'Read-side only, by design. No PHI crosses; the protocol carries identity, authority and settlement.' },
    { system: 'Rostering and workforce systems', connect: 'The roster stays the source of shifts. Fills, approvals and pay ride the rails.' },
    { system: 'Agency and locum platforms', connect: 'Agencies keep their own frame and are paid cross-registry, exactly once.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
