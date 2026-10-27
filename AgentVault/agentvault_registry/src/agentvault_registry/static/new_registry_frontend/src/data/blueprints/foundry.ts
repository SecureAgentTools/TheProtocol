import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'A machine is a workload', primitive: 'SPIFFE identity, short-lived SVIDs, mTLS peer to peer', railStatus: 'LIVE' as const },
  { step: 'A shift is a permit', primitive: 'IRONKEY L4: one cell, one shift, a parts budget', railStatus: 'LIVE' as const },
  { step: 'The rails are proven, not assumed', primitive: 'Canary transactions on live paths, judged end to end', railStatus: 'LIVE' as const },
  { step: 'Emergency stop for money', primitive: 'READONLY_MODE freeze + coordinated suspension', railStatus: 'LIVE' as const },
  { step: 'Inter-cell settlement', primitive: 'A2A payment with exactly-once idempotency', railStatus: 'LIVE' as const },
]

export const foundry: Blueprint = {
  id: 'foundry',
  tier: 2,
  rank: 9,
  industry: 'Manufacturing and Robotics Fleets',
  systemName: 'FOUNDRY LINE',
  promise: 'Robot cells that buy tooling, sell capacity, and hold authority one shift at a time.',
  cases: [
    { role: 'Contract manufacturer', line: 'Sixty cells trading capacity inside shift-scoped budgets.' },
    { role: 'Robotics fleet operator', line: 'A kill switch that also freezes the money.' },
    { role: 'Tooling supplier', line: 'Consignment stock that bills itself per insert.' },
    { role: 'Maintenance as a service', line: 'Machines buying their own repairs, within ceilings.' },
  ],
  problem:
    'A production line already negotiates: cells trade capacity, tooling moves between stations, maintenance is bought from whoever is free. All of it runs on a scheduler that pretends to be a market and a permissions model that pretends not to exist.',
  system: [
    'FOUNDRY LINE runs a contract manufacturer’s 60 cells as economic actors. A milling cell that finishes early sells the slack to the neighbouring line; a tool changer buys inserts against a parts budget that dies at shift end; every machine identity is a workload certificate that renews itself and revokes in under a second. Authority is per cell, per shift, and the night shift’s permits cannot spend the morning’s budget by construction.',
    'Because a robot cannot eyeball whether the payment rail is healthy before committing a job, the network proves it continuously: synthetic canary transactions run the same paths real money takes and are judged end to end, so a degraded rail is a red light on a board, not a surprise in a settlement.',
    'And when something is wrong, the response is wired for machines. One action freezes settlement plant-wide while the cells keep machining, because the kill switch here stops the money, not the motion. The safety interlocks that stop motion never meet this network at all; the emergency stop stays exactly where machine safety law put it.',
  ],
  cast: [
    { agent: 'mill-cell-12', role: 'Machines parts, sells slack capacity', ceiling: 'One shift permit: a parts budget that dies at shift end.' },
    { agent: 'tooling-supplier', role: 'Consignment stock, bills per insert', ceiling: 'Paid exactly once per use. Cannot touch the capacity market.' },
    { agent: 'maintenance-svc', role: 'Sells repairs to whoever is down', ceiling: 'Quotes and settles within the buying cell’s ceiling, never its own.' },
    { agent: 'canary-runner', role: 'Proves the rails continuously', ceiling: 'Spends synthetic units on real paths. Can never hold a shift budget.' },
  ],
  loom: {
    nodes: [
      { id: 'cell', label: 'mill-cell-12', sub: 'SPIFFE workload', kind: 'agent', x: 118, y: 110 },
      { id: 'gate', label: 'Shift authority', sub: 'one cell, one shift', kind: 'gate', x: 336, y: 110 },
      { id: 'market', label: 'Capacity market', sub: 'A2A, exactly-once', kind: 'teg', x: 560, y: 110 },
      { id: 'supplier', label: 'tooling-supplier', sub: 'consignment stock', kind: 'agent', x: 764, y: 110 },
      { id: 'operator', label: 'line operator', sub: 'freeze + suspend', kind: 'human', x: 118, y: 330 },
      { id: 'canary', label: 'canary-runner', sub: 'synthetic, judged', kind: 'agent', x: 336, y: 330 },
      { id: 'ledger', label: 'Event ledger', sub: 'append-only', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-scope', from: 'cell', to: 'gate', label: 'permit' },
      { id: 'e-trade', from: 'gate', to: 'market', label: 'slack sold' },
      { id: 'e-buy', from: 'market', to: 'supplier' },
      { id: 'e-emit', from: 'market', to: 'ledger' },
      { id: 'e-canary', from: 'canary', to: 'market', label: 'same rails' },
      { id: 'e-freeze', from: 'operator', to: 'gate', label: 'freeze, one action' },
      { id: 'a-night', from: 'cell', to: 'market', attackOnly: true, curve: -70, label: 'an hour after shift end' },
    ],
    script: [
      { edge: 'e-scope', state: 'active', dwellMs: 1400, caption: 'The cell’s authority is a capability permit: one cell, one shift, a parts budget that dies at shift end.' },
      { edge: 'e-trade', state: 'active', dwellMs: 1400, caption: 'Mill-cell-12 finishes early and sells the slack to the neighbouring line, inside the clamp.' },
      { edge: 'e-buy', state: 'active', dwellMs: 1400, caption: 'The tool changer buys inserts against the shift budget. Consignment stock bills itself.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'Every trade lands on the ledger, append-only.' },
      { edge: 'e-canary', state: 'active', dwellMs: 1400, caption: 'Canaries run the same paths real money takes, judged end to end. A degraded rail is a red light, not a surprise.' },
      { edge: 'e-freeze', state: 'active', dwellMs: 1500, caption: 'And one action freezes the money plant-wide. The safety systems that stop motion never met this network.' },
    ],
  },
  attacks: [
    {
      title: 'The expired shift',
      attack: 'A compromised cell holds on to its shift permit and tries to keep buying inserts an hour after shift end, against the morning’s budget.',
      mechanism: 'The permit is an L4 capability: its caveats are intersected with the issuer’s current authority at the moment of use, and at shift end both the permit and the budget it named are gone. There is nothing left to spend and no authority left to spend it with, so the attempt dies before any escrow exists to unwind.',
      rail: 'S03',
      consequence: 'The morning budget opens untouched. The denied attempts sit on the ledger timestamped an hour past shift end, which is how the plant finds the compromised cell.',
      script: [
        { edge: 'a-night', state: 'denied', dwellMs: 1900, stopAt: 0.6, flashNode: 'gate', caption: 'S03. The shift ended, so the permit’s budget no longer exists. The night shift cannot spend the morning, by construction.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Incident Response (the P1 clock)', href: '/compliance/doc/incident-response-procedures' },
  ],
  rails: ['S02', 'S03', 'S07', 'S09', 'S15', 'S18'],
  standup: {
    infra: 'One registry per plant. The cells enroll through the identity fabric.',
    agents: 'Cell, tooling and maintenance roles; ceilings mirror the shift plan.',
    integration: 'The MES and the scheduler. Safety systems stay air-gapped and out of scope.',
  },
  nonClaims: [
    'FOUNDRY LINE moves authority and money, not motion. No safety function, no real-time control, no OT network claims.',
  ],
  mermaid: `flowchart LR
  MES["MES / scheduler"] -.->|"jobs in"| C["mill-cell-12<br/>SPIFFE workload"]
  C -->|"shift permit: one cell, one shift"| G{"shift authority"}
  G -->|"clamped"| M["capacity market<br/>A2A, exactly-once"]
  M -->|"inserts, per use"| Sup["tooling-supplier"]
  M --> L[("event ledger")]
  K["canary-runner"] -.->|"synthetic, same rails"| M
  Op["line operator"] -.->|"freeze, one action"| G`,
  legacy: [
    { system: 'MES and the scheduler', connect: 'Work orders stay in the MES. Cells buy tooling and sell capacity against them with shift-scoped authority.' },
    { system: 'ERP purchasing', connect: 'Consumable purchases settle agent to agent and post back as goods receipts.' },
    { system: 'Safety and OT systems', connect: 'Air-gapped and out of scope, stated as design. This layer never actuates.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
