import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Carrier equals sovereign registry', primitive: 'Bilateral federation, mTLS, per-peer licences', railStatus: 'LIVE' as const },
  { step: 'Per-event settlement', primitive: 'Cross-registry transfer with receiver-side fee', railStatus: 'LIVE' as const },
  { step: 'Exactly-once across retries', primitive: 'Idempotency keys, two-layer dedup', railStatus: 'LIVE' as const },
  { step: 'A shared, signed record', primitive: 'Both sides emit; the ledger deduplicates', railStatus: 'LIVE' as const },
  { step: 'Misbehaving peer contained', primitive: 'Licence suspension, economic quarantine', railStatus: 'LIVE' as const },
]

export const trunk: Blueprint = {
  id: 'trunk',
  tier: 2,
  rank: 11,
  industry: 'Telecom and Inter-Carrier Settlement',
  systemName: 'TRUNK',
  promise: 'Inter-carrier settlement per event instead of per quarter, on a record neither side can edit.',
  cases: [
    { role: 'Interconnect carrier', line: 'Per-event settlement instead of quarter-end reconciliation warfare.' },
    { role: 'MVNO', line: 'Wholesale reconciliation that arrives already reconciled.' },
    { role: 'Roaming clearing', line: 'Both sides sign the same entry, and the ledger deduplicates.' },
    { role: 'A2P and SMS aggregation', line: 'Inflated counters end in quarantine, not in court first.' },
  ],
  problem:
    'Two carriers terminate each other’s traffic all month, then spend the next quarter disputing whose counters are right. The settlement is a negotiation because the record is two records.',
  system: [
    'TRUNK is a settlement mesh of 14 carrier registries. Each interconnect event settles as it happens: the terminating side is paid per event, the fee lands with the receiver, and the same signed entry exists on both frames because both emit it and the ledger deduplicates on an idempotency key. There is no month-end file exchange, because there is no month-end state to reconcile.',
    'A carrier that starts inflating counters is not sued first; it is contained first. Its licence suspends, its ability to move value in the mesh ends within a sync cycle, and every historical entry it ever signed stays intact for the lawyers.',
  ],
  cast: [
    { agent: 'metering-a', role: 'Turns CDRs into per-event settlements', ceiling: 'Settles what mediation metered. Cannot invent an event.' },
    { agent: 'metering-b', role: 'Their side of the same call', ceiling: 'Emits the same signed entry from their own counters.' },
    { agent: 'interconnect-desk', role: 'Manages peers and licences', ceiling: 'Holds the licence lever. Cannot touch a settlement entry.' },
    { agent: 'assurance-watch', role: 'Revenue assurance, reading both totals', ceiling: 'Read-only across the interconnect, by design.' },
  ],
  loom: {
    nodes: [
      { id: 'mediation', label: 'mediation layer', sub: 'CDRs, as today', kind: 'external', x: 118, y: 110 },
      { id: 'meter', label: 'metering-a', sub: 'per event', kind: 'agent', x: 336, y: 110 },
      { id: 'settle', label: 'Per-event settle', sub: 'receiver-side fee', kind: 'teg', x: 560, y: 110 },
      { id: 'tegb', label: 'Their TEG', sub: 'paid per event', kind: 'teg', x: 764, y: 110 },
      { id: 'desk', label: 'interconnect-desk', sub: 'licence lever', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Quarantine gate', sub: 'containment first', kind: 'gate', x: 336, y: 330 },
      { id: 'ledgers', label: 'Both ledgers', sub: 'one entry, dedup', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-cdr', from: 'mediation', to: 'meter', label: 'CDRs in' },
      { id: 'e-settle', from: 'meter', to: 'settle', label: 'per event' },
      { id: 'e-credit', from: 'settle', to: 'tegb' },
      { id: 'e-emit', from: 'settle', to: 'ledgers', label: 'both emit', labelT: 0.4 },
      { id: 'e-dedup', from: 'tegb', to: 'ledgers' },
      { id: 'e-lever', from: 'desk', to: 'gate', label: 'suspend' },
      { id: 'a-inflate', from: 'tegb', to: 'settle', attackOnly: true, curve: -70, label: 'inflated counters' },
    ],
    script: [
      { edge: 'e-cdr', state: 'active', dwellMs: 1400, caption: 'CDRs arrive from mediation, exactly as they already do. The switches never see the ledger.' },
      { edge: 'e-settle', state: 'active', dwellMs: 1400, caption: 'Each interconnect event settles as it happens. Not a file. Not a quarter.' },
      { edge: 'e-credit', state: 'active', dwellMs: 1400, caption: 'The terminating side is paid per event, and the fee lands with the receiver.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1400, caption: 'Both sides emit the same signed entry.' },
      { edge: 'e-dedup', state: 'active', dwellMs: 1400, caption: 'The ledger deduplicates on the idempotency key. Two frames, one record, nothing left to reconcile.' },
      { edge: 'e-lever', state: 'active', dwellMs: 1500, caption: 'And the relationship itself is a bilateral licence: revocable in one action, without a lawsuit.' },
    ],
  },
  attacks: [
    {
      title: 'The inflated counter',
      attack: 'In March a peer’s counters start growing three percent faster than its traffic. Nothing dramatic; just enough to be worth it at quarter scale.',
      mechanism: 'There is no quarter to hide in. Every event settles alone, both sides emit the same signed entry, and the ledger deduplicates on the idempotency key, so a claimed event with no twin is visible the day it is claimed, attributable to a named counter. The desk suspends the licence, and the peer’s ability to move value in the mesh ends within a sync cycle.',
      rail: 'S11',
      consequence: 'Containment arrives before the lawyers do, and every entry the peer ever signed stays intact for them. The mesh’s other corridors settle through the incident untouched.',
      script: [
        { edge: 'a-inflate', state: 'denied', dwellMs: 1900, stopAt: 0.55, flashNode: 'gate', caption: 'S11. A claimed event with no twin is visible the day it is claimed. The licence suspends; the history survives.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance Audit Procedures', href: '/compliance/doc/compliance-audit-procedures' },
  ],
  rails: ['S01', 'S11', 'S13', 'S14', 'S15'],
  standup: {
    infra: 'One registry per carrier. Interconnect partners federate bilaterally.',
    agents: 'Metering and settlement roles per interconnect.',
    integration: 'The mediation layer. The switches never see the ledger.',
  },
  nonClaims: [
    'TRUNK settles between machines that already trust their own metering. It does not arbitrate radio truth, and it is not a clearing house licence.',
  ],
  mermaid: `flowchart LR
  Med["mediation layer"] -.->|"CDRs, as today"| MA["metering-a"]
  MA -->|"settle per event"| T["per-event settle<br/>receiver-side fee"]
  T -->|"terminating side paid"| TB["their TEG"]
  T -->|"signed entry"| L[("both ledgers<br/>dedup on key")]
  TB -->|"the same entry"| L
  D["interconnect-desk"] -.->|"licence suspend"| Q{"economic quarantine"}
  Q -.->|"value stops, history survives"| TB`,
  legacy: [
    { system: 'The mediation layer', connect: 'CDRs flow exactly as today. Metering agents consume mediation output, and the switches never see the ledger.' },
    { system: 'Interconnect billing systems', connect: 'Run in parallel through a full cycle. Per-event settlement and the quarterly statement reconcile against each other until the statement is redundant.' },
    { system: 'OSS and BSS inventories', connect: 'Trunk and route identities map onto agent identities. Provisioning stays in the OSS.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
