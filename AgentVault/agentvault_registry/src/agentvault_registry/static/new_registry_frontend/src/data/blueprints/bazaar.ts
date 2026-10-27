import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Agents buy from agents', primitive: 'A2A payment authorization: authorize, verify, settle', railStatus: 'LIVE' as const },
  { step: 'Discovery with reputation', primitive: 'Federated discovery, trust scores built on settled work', railStatus: 'LIVE' as const },
  { step: 'Charged exactly once', primitive: 'Idempotent settlement across retries and crashes', railStatus: 'LIVE' as const },
  { step: 'Disputes with teeth', primitive: 'Four-phase dispute over any paid call', railStatus: 'LIVE' as const },
  { step: 'A storefront in an afternoon', primitive: 'SDK payment middleware: enforcement is automatic', railStatus: 'LIVE' as const },
]

export const bazaar: Blueprint = {
  id: 'bazaar',
  tier: 2,
  rank: 12,
  industry: 'Retail and Autonomous Commerce',
  systemName: 'BAZAAR',
  promise: 'Shopping agents paying merchant agents per call, with the refusal rails ready before the first sale.',
  cases: [
    { role: 'B2B wholesale', line: 'Procurement agents restocking against escrowed contracts.' },
    { role: 'API marketplace', line: 'Meter every call through a rail with disputes built in.' },
    { role: 'Dropship network', line: 'Merchant agents paid exactly once across retries.' },
    { role: 'Autonomous procurement', line: 'Shopping bots with budgets instead of card numbers.' },
  ],
  problem:
    'Agent commerce is arriving as ten thousand bots with someone’s credit card. What is missing is not the shopping agent; it is the settlement layer where software pays software in amounts too small for card rails, with disputes that do not require a human in a call centre.',
  system: [
    'BAZAAR is a merchant network where a procurement agent restocks a kitchen by calling a wholesaler’s agent, paying per order message, and escalating to escrowed contracts for anything above a threshold. Reputation is built on settled work and travels with the agent across registries. The first calls are cheap enough to be free mistakes; the large ones ride escrow and a dispute process with slashing behind it.',
    'When a merchant ships nothing, the buyer does not open a ticket with a platform; it opens a dispute that binds the payment itself. Four phases, evidence on the ledger, an outcome that can reach a bond, and a reputation that is arithmetic over settled work rather than a star rating. A merchant that cheats is not reviewed poorly. It is poorer.',
    'One caveat is printed here on purpose, because the platform documents it: a payment authorization that was already consumed reports valid on a repeated verify. A merchant agent must treat verification as a receipt check, not a work order, and never re-perform paid work on a re-verify. A commerce page that hides its sharp edge is exactly the kind of page this network does not run.',
  ],
  cast: [
    { agent: 'storefront-agent', role: 'Prices, verifies, fulfils per call', ceiling: 'The SDK middleware gates work behind settled payment. Verify is a receipt check.' },
    { agent: 'procurement-agent', role: 'Restocks against declared budgets', ceiling: 'A budget, not a card number. Above threshold it must escrow.' },
    { agent: 'dispute-desk', role: 'Runs the four phases over paid calls', ceiling: 'Binds payments and bonds. Cannot touch an unrelated balance.' },
  ],
  loom: {
    nodes: [
      { id: 'buyer', label: 'procurement-agent', sub: 'budget, not a card', kind: 'agent', x: 118, y: 110 },
      { id: 'pgate', label: 'Payment gate', sub: 'verify = receipt', kind: 'gate', x: 336, y: 110 },
      { id: 'settle', label: 'Settle once', sub: 'idempotency key', kind: 'teg', x: 560, y: 110 },
      { id: 'store', label: 'storefront-agent', sub: 'works once', kind: 'agent', x: 764, y: 110 },
      { id: 'spine', label: 'Escrow contracts', sub: 'above threshold', kind: 'gate', x: 118, y: 330 },
      { id: 'dispute', label: 'dispute-desk', sub: 'four phases', kind: 'agent', x: 336, y: 450 },
      { id: 'ledger', label: 'Event ledger', sub: 'every paid call', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-order', from: 'buyer', to: 'pgate', label: 'paid order' },
      { id: 'e-verify', from: 'pgate', to: 'settle', label: 'verify, settle' },
      { id: 'e-work', from: 'settle', to: 'store' },
      { id: 'e-emit', from: 'settle', to: 'ledger', labelT: 0.4 },
      { id: 'e-escrow', from: 'buyer', to: 'spine' },
      { id: 'e-milestone', from: 'spine', to: 'settle', label: 'milestones', curve: 55 },
      { id: 'e-dispute', from: 'dispute', to: 'ledger', label: 'evidence, binding' },
      { id: 'a-double', from: 'store', to: 'settle', attackOnly: true, curve: 70, label: 'settle again' },
    ],
    script: [
      { edge: 'e-order', state: 'active', dwellMs: 1400, caption: 'A procurement agent orders a restock, carrying a payment authorization that lives fifteen minutes.' },
      { edge: 'e-verify', state: 'active', dwellMs: 1500, caption: 'The storefront verifies, then settles. A consumed authorization still reports valid on a repeat verify, so verification is a receipt check, never a work order.' },
      { edge: 'e-work', state: 'active', dwellMs: 1300, caption: 'The work happens once, after the money is real.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'Order and settlement land on the ledger.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'Anything above threshold rides an escrowed contract instead of a bare call.' },
      { edge: 'e-milestone', state: 'active', dwellMs: 1300, caption: 'Milestones release from escrow as the order completes.' },
      { edge: 'e-dispute', state: 'active', dwellMs: 1500, caption: 'And a four-phase dispute binds any paid call. No call centre appears in this drawing.' },
    ],
  },
  attacks: [
    {
      title: 'The second settlement',
      attack: 'A merchant’s crashed process comes back up and replays the settlement call for an order it already settled. A less honest merchant replays it on purpose.',
      mechanism: 'Settlement is idempotent under a key derived from the order and enforced in two layers, so the replay returns the original result instead of moving money again. Crash, retry and malice collapse into the same outcome: charged exactly once.',
      rail: 'S15',
      consequence: 'The buyer’s budget shows one debit and the ledger shows one settlement, however many times the call arrived.',
      script: [
        { edge: 'a-double', state: 'denied', dwellMs: 1900, stopAt: 0.55, flashNode: 'settle', caption: 'S15. The idempotency key answers with the first result. Money moves once, across crashes, retries and intent.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Compliance posture', href: '/compliance' },
  ],
  rails: ['S01', 'S02', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'Hosted registries are enough for both sides.',
    agents: 'A storefront role and a buyer role. The SDK middleware does the enforcement.',
    integration: 'Inventory and fulfilment. The cart was never the hard part.',
  },
  nonClaims: [
    'BAZAAR moves network units between agents. Fiat enters purchase-only where a deployment enables it, with no withdrawal path by design, and most deployments run without it.',
    'No consumer-protection regime is claimed. Disputes here bind agents and their operators, not statutory rights.',
  ],
  mermaid: `flowchart LR
  B["procurement-agent<br/>a budget, not a card"] -->|"order + apt_ authorization"| G{"payment gate"}
  G -->|"verify, then settle"| T["settle exactly-once<br/>idempotency key"]
  T -->|"work performed once"| S["storefront-agent"]
  T --> L[("event ledger<br/>every paid call")]
  B -->|"above threshold"| E{"escrow contracts"}
  E -->|"milestones"| T
  D["dispute-desk<br/>four phases"] -.->|"binds any paid call"| L`,
  legacy: [
    { system: 'Inventory and order management', connect: 'Stock truth stays in the OMS. Merchant agents quote from it and orders post back.' },
    { system: 'Payment service providers', connect: 'Card rails keep serving humans. Agent-to-agent calls settle on the protocol beside them.' },
    { system: 'Fulfilment and 3PL systems', connect: 'Fulfilment events become signed attestations that release escrow milestones.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
