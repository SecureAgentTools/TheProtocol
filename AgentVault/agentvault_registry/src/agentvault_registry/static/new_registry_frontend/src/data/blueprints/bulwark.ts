import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Freeze without falling over', primitive: 'READONLY_MODE break-glass: writes halt, reads and audit continue', railStatus: 'LIVE' as const },
  { step: 'The freeze cannot be flipped off remotely', primitive: 'Env-only switch; no API can lift it, by design', railStatus: 'LIVE' as const },
  { step: 'Rails proven continuously', primitive: 'Canary transactions on live paths, judged end to end', railStatus: 'LIVE' as const },
  { step: 'Island mode exists', primitive: 'Standalone air-gapped deployment: local ledger, no federation', railStatus: 'LIVE' as const },
  { step: 'Containment in one action', primitive: 'Coordinated suspension across identity, account and receipt', railStatus: 'LIVE' as const },
  { step: 'Recovery re-verified', primitive: 'Supply invariant re-checked after any restore', railStatus: 'LIVE' as const },
]

export const bulwark: Blueprint = {
  id: 'bulwark',
  tier: 2,
  vault: true,
  rank: 17,
  industry: 'Critical Infrastructure Resilience',
  systemName: 'BULWARK',
  promise: 'Civilian infrastructure coordination that degrades on purpose instead of failing by surprise.',
  cases: [
    { role: 'Water and power utilities', line: 'Inter-utility settlement that can freeze without going dark.' },
    { role: 'Civil protection agency', line: 'A coordination layer with an island mode for the bad week.' },
    { role: 'Municipal operations', line: 'One switch halts every write while the auditors keep seeing.' },
    { role: 'Regional mutual aid', line: 'Resource sharing between authorities, settled and attested.' },
  ],
  problem:
    'Civilian infrastructure coordination fails in one of two ways: systems so interconnected that one compromise cascades, or systems so isolated that nothing coordinates at all. The missing shape is a network that can voluntarily degrade, freeze, island itself, and come back with its books intact.',
  system: [
    'BULWARK is the settlement and coordination layer for a region’s civilian utilities: water, power distribution, municipal services, sharing crews, equipment and capacity through escrowed agreements between sovereign deployments. On the good days it is unremarkable, which is the point. Synthetic canary transactions run the live paths continuously, so "the rails work" is a measured fact on a board rather than an assumption in a binder.',
    'On the bad day, the shape changes deliberately. A suspected compromise at one utility triggers the break-glass: a single switch freezes every state-changing request and every scheduled job on that deployment while reads, sign-in and the ledger auditor keep working, because an operator who freezes a system must not go blind inside it. There is no API to lift the freeze, on purpose; a switch a compromised credential can flip off is not a safety mechanism. If the region’s links look wrong, a deployment islands itself and runs standalone, and when it rejoins, recovery is not declared but re-verified: the supply invariant is checked before anyone trusts the books again.',
  ],
  cast: [
    { agent: 'utility-ops (per utility)', role: 'Shares crews and capacity', ceiling: 'Escrowed agreements within declared limits.' },
    { agent: 'region-coordinator', role: 'Structures mutual aid', ceiling: 'Proposes and funds. Cannot force a peer’s books.' },
    { agent: 'canary-fleet', role: 'Proves the rails hourly', ceiling: 'Synthetic transactions only, self-cleaning.' },
    { agent: 'duty-officer (human)', role: 'Holds the break-glass', ceiling: 'Freeze and suspend. Cannot issue, transfer, or lift the freeze remotely.' },
  ],
  loom: {
    nodes: [
      { id: 'utilA', label: 'utility A', sub: 'sovereign deployment', kind: 'registry', x: 118, y: 110 },
      { id: 'aid', label: 'Mutual aid escrow', sub: 'crews + capacity', kind: 'teg', x: 336, y: 220 },
      { id: 'utilB', label: 'utility B', sub: 'sovereign deployment', kind: 'registry', x: 560, y: 110 },
      { id: 'canary', label: 'Canary fleet', sub: 'rails proven hourly', kind: 'gate', x: 336, y: 330 },
      { id: 'officer', label: 'duty-officer', sub: 'holds the break-glass', kind: 'human', x: 118, y: 450 },
      { id: 'freeze', label: 'READONLY freeze', sub: 'no API lifts it', kind: 'gate', x: 560, y: 450 },
      { id: 'ledger', label: 'Region ledger', sub: 'auditor never blinded', kind: 'ledger', x: 764, y: 220 },
    ],
    edges: [
      { id: 'e-share', from: 'utilA', to: 'aid', label: 'crew capacity, escrowed' },
      { id: 'e-settle', from: 'aid', to: 'utilB', label: 'settled, attested' },
      { id: 'e-canary', from: 'canary', to: 'aid', label: 'synthetic proof' },
      { id: 'e-emit', from: 'utilB', to: 'ledger' },
      { id: 'e-glass', from: 'officer', to: 'freeze', label: 'one switch' },
      { id: 'a-thaw', from: 'utilB', to: 'freeze', attackOnly: true, label: 'lift the freeze via API' },
    ],
    script: [
      { edge: 'e-share', state: 'active', dwellMs: 1400, caption: 'Utilities share crews and capacity through escrowed agreements.' },
      { edge: 'e-canary', state: 'active', dwellMs: 1400, caption: 'Canaries run the same rails real value takes. Health is measured, not assumed.' },
      { edge: 'e-settle', state: 'active', dwellMs: 1400, caption: 'Mutual aid settles and attests between sovereign peers.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'The region ledger keeps the books.' },
      { edge: 'e-glass', state: 'active', dwellMs: 1600, caption: 'On the bad day, one switch freezes writes. Reads and the auditor keep working.' },
    ],
  },
  attacks: [
    {
      title: 'The remote thaw',
      attack: 'The attacker who prompted the freeze uses a captured admin token to switch the deployment back to writable.',
      mechanism: 'The freeze is environment-only and has no lifting API. Turning it off requires deliberate action on the host by someone with hands on the deployment, which is exactly the property a safety switch needs.',
      rail: 'S09',
      consequence: 'The deployment stays frozen, the operator keeps reading, the auditor keeps auditing, and the attacker holds an admin token to a system that will not write.',
      script: [
        { edge: 'a-thaw', state: 'denied', dwellMs: 1900, stopAt: 0.68, flashNode: 'freeze', caption: 'S09. There is no API to lift the freeze. That is the mechanism, not a gap in it.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Incident Response (the P1 clock)', href: '/compliance/doc/incident-response-procedures' },
  ],
  rails: ['S01', 'S08', 'S09', 'S11', 'S15', 'S18'],
  standup: {
    infra: 'One sovereign deployment per utility; island-capable standalone mode is standard.',
    agents: '4 roles per utility, plus the canary fleet the platform already ships.',
    integration: 'OT and SCADA remain air-gapped and out of scope. This layer coordinates and settles; it never actuates.',
  },
  nonClaims: [
    'BULWARK is civilian coordination and settlement. It controls no physical process, touches no OT network, and carries no safety-instrumented function.',
    'Defence and military applications are deliberately out of scope for this catalogue.',
  ],
  mermaid: `flowchart LR
  UA["utility A frame"] -->|"escrowed mutual aid"| TEG["TEG escrow"]
  TEG -->|"settle + attest"| UB["utility B frame"]
  CAN["canary fleet"] -.->|"synthetic transactions hourly"| TEG
  DO["duty officer"] -->|"break-glass"| RO["READONLY_MODE<br/>env-only, no lifting API"]
  RO -.->|"writes halt, reads live"| UB
  UB --> ES[("region ledger<br/>auditor exempted from freeze")]`,
  legacy: [
    { system: 'OT and SCADA', connect: 'Air-gapped and out of scope, stated as design. This layer coordinates and settles; it never actuates.' },
    { system: 'Emergency management platforms', connect: 'Mutual-aid agreements become escrowed contracts. The coordination room keeps its tools.' },
    { system: 'Utility billing and ERP', connect: 'Aid settlements post back as ordinary receivables once delivered.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
