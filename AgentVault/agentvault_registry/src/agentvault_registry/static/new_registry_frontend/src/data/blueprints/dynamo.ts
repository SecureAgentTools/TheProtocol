import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Every device an identity', primitive: 'SPIFFE workload identity, short-lived SVIDs', railStatus: 'LIVE' as const },
  { step: 'Per-reading settlement', primitive: 'A2A payment authorization, settle via /teg/transfer', railStatus: 'LIVE' as const },
  { step: 'Shift-scoped authority', primitive: 'IRONKEY L4 permits: one substation, one shift, a budget', railStatus: 'LIVE' as const },
  { step: 'Sub-second revocation', primitive: 'IRONHAND revocation over the event stream, under 500ms', railStatus: 'LIVE' as const },
  { step: 'One-action containment', primitive: 'Coordinated suspension: mTLS, account, cross-frame receipt', railStatus: 'LIVE' as const },
  { step: 'Site-wide freeze', primitive: 'READONLY_MODE break-glass, env-only', railStatus: 'LIVE' as const },
]

export const dynamo: Blueprint = {
  id: 'dynamo',
  tier: 2,
  rank: 4,
  industry: 'Energy, Grid and Industrial M2M',
  systemName: 'DYNAMO',
  promise: 'A hundred thousand devices with economic identities, each one revocable in under half a second.',
  cases: [
    { role: 'Distribution system operator', line: 'A hundred thousand meters, each one revocable in half a second.' },
    { role: 'Battery and VPP operator', line: 'Sell the evening peak per reading, per device, per shift.' },
    { role: 'EV charging network', line: 'Roaming settlement between operators without a clearing house.' },
    { role: 'Factory microgrid', line: 'Machines buying power from the roof next door, inside declared ceilings.' },
  ],
  problem:
    'A distributed grid has hundreds of thousands of devices that need to transact in fractions of a cent and be individually revocable within seconds. TLS gives you a channel. It does not give you an identity with an economic ceiling and a kill switch.',
  system: [
    'DYNAMO is a distribution operator running 118,000 inverters, meters and batteries as economic actors. Every device is a workload with a SPIFFE identity and a short-lived certificate that renews itself. A rooftop battery in Aarhus sells 3.1 kWh into the evening peak and is paid per reading, in fractions of a cent, with the fee carved by the rail that moves the money. The site operator’s agents hold capability permits scoped to one substation for one shift, so the blast radius of any single compromise is a data structure, not a hope.',
    'At 17:42 a meter starts reporting impossible numbers. The operator revokes it. The revocation travels over the event stream and the device’s identity is dead in under half a second: its next reading has no one to be. The same action suspends its account and blocklists cross-frame receipt, so the value it holds is frozen in place. Every reading it ever signed is still on the ledger, which is how the forensics team finds the firmware bug by Thursday.',
  ],
  cast: [
    { agent: 'inverter-7741', role: 'Sells generation per reading', ceiling: 'Signed readings only. Budget per shift. No transfer authority beyond settlement.' },
    { agent: 'substation-ops', role: 'Aggregates and bids the site', ceiling: 'L4 permit: one substation, one shift.' },
    { agent: 'grid-settlement', role: 'Pays per accepted reading', ceiling: 'Settle only, allowlisted counterparties.' },
    { agent: 'site operator (human)', role: 'Holds the kill switch', ceiling: 'Revocation and suspension. Cannot issue, cannot transfer.' },
  ],
  loom: {
    nodes: [
      { id: 'inverter', label: 'inverter-7741', sub: 'SPIFFE workload', kind: 'external', x: 118, y: 110 },
      { id: 'svid', label: 'Identity gate', sub: 'short-lived SVID', kind: 'gate', x: 336, y: 220 },
      { id: 'settle', label: 'Per-reading settle', sub: 'fractions of a cent', kind: 'teg', x: 560, y: 220 },
      { id: 'ledger', label: 'Event ledger', sub: 'every reading, signed', kind: 'ledger', x: 764, y: 220 },
      { id: 'operator', label: 'site operator', sub: 'named human', kind: 'human', x: 118, y: 220 },
      { id: 'revoke', label: 'Revocation', sub: 'under 500ms', kind: 'gate', x: 118, y: 330 },
    ],
    edges: [
      { id: 'e-read', from: 'inverter', to: 'svid', label: 'signed reading' },
      { id: 'e-settle', from: 'svid', to: 'settle' },
      { id: 'e-emit', from: 'settle', to: 'ledger' },
      { id: 'e-rev', from: 'operator', to: 'revoke', label: 'one action' },
      { id: 'e-kill', from: 'revoke', to: 'svid', label: 'identity dies' },
    ],
    script: [
      { edge: 'e-read', state: 'active', dwellMs: 1400, caption: '17:41. A reading arrives, signed by the device’s own identity.' },
      { edge: 'e-settle', state: 'active', dwellMs: 1300, caption: 'Settlement in fractions of a cent, fee carved in-rail.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'The reading is on the ledger forever.' },
      { edge: 'e-rev', state: 'active', dwellMs: 1400, caption: '17:42. Impossible numbers. The operator acts once.' },
      { edge: 'e-kill', state: 'active', dwellMs: 1500, caption: 'Revocation rides the event stream. Under half a second.' },
    ],
  },
  attacks: [
    {
      title: 'The compromised meter, one second later',
      attack: 'The revoked meter, still running hostile firmware, submits its next reading.',
      mechanism: 'IRONHAND revocation propagated over the event stream and the SVID is dead. The reading arrives with no identity to be, and clamping the issuer has already emptied every capability permit the site desk issued through it.',
      rail: 'S07',
      riskRef: 'R-OP-02',
      consequence: 'Nothing settles, nothing emits, and the frozen balance waits for forensics. The ledger keeps every reading the device ever signed.',
      script: [
        { edge: 'e-read', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'svid', caption: 'S07. The SVID died 400ms ago. This reading has no one to be.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Incident Response (the P1 clock)', href: '/compliance/doc/incident-response-procedures' },
  ],
  rails: ['S02', 'S03', 'S04', 'S07', 'S08', 'S09', 'S15'],
  standup: {
    infra: 'One registry per operator region, booted from the free licence.',
    agents: '3 to 4 roles; the device fleet enrolls through the identity fabric, not hand-provisioning.',
    integration: 'Metering heads and the market operator interface. The long pole is device firmware, not the network.',
  },
  nonClaims: [
    'DYNAMO carries identity, authority and settlement. It is not SCADA and controls no safety-instrumented function.',
    'No assertion of IEC 62443 conformance.',
  ],
  mermaid: `flowchart LR
  DEV["device workload<br/>SPIFFE SVID, short TTL"] -->|"signed reading"| REG["registry identity gate"]
  REG -->|"A2A payment authorize"| TEG["TEG settle per reading"]
  TEG --> ES[("event store")]
  OP["site operator"] -->|"coordinated suspension"| REV["IRONHAND revoke<br/>WS, under 500ms"]
  REV -.->|"SVID dead, permits emptied"| REG`,
  legacy: [
    { system: 'SCADA and metering heads', connect: 'Read-side only. Meter reads become signed attestations; control stays in the control system.' },
    { system: 'Market operator interfaces', connect: 'The desk agent files the same positions to the operator while escrow settles the bilateral side.' },
    { system: 'Device fleet management', connect: 'Device identities enroll through the existing fleet manager. Revocation on the protocol side propagates in under half a second.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
