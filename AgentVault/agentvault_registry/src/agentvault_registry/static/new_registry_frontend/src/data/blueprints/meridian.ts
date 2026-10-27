import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Move value', primitive: 'POST /teg/transfer and cross-registry transfer', railStatus: 'LIVE' as const },
  { step: 'Cross-currency routing', primitive: 'FX pools across sovereign frames, direct', railStatus: 'LIVE' as const },
  { step: 'Per-agent spend ceiling', primitive: 'IRONKEY L4 capability caveats, atomic budget debit', railStatus: 'LIVE' as const },
  { step: 'Named liable human', primitive: 'Cockpit Card mandate (LIABILITY_MODE)', railStatus: 'LIVE (gated)' as const },
  { step: 'Human presence proof', primitive: 'WebAuthn platform credential, userVerification required', railStatus: 'LIVE' as const },
  { step: 'Exactly-once execution', primitive: 'Idempotency-Key, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'Supply conservation', primitive: 'Delta = 0 invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Forensics', primitive: 'Event ledger chain and windowed search', railStatus: 'LIVE' as const },
]

export const meridian: Blueprint = {
  id: 'meridian',
  tier: 1,
  rank: 1,
  industry: 'Autonomous Treasury and Financial Operations',
  systemName: 'MERIDIAN',
  promise: 'A treasury desk that runs at 03:14, with a named human behind every large movement.',
  cases: [
    { role: 'Corporate treasury', line: 'Nine subsidiaries, three currencies, one liquidity desk that also works at night.' },
    { role: 'PSP and marketplace payouts', line: 'Thousands of small payouts a day, each inside a per-merchant ceiling.' },
    { role: 'Fund operations', line: 'Rebalancing with a named human behind every threshold breach.' },
    { role: 'Intercompany netting', line: 'Month-end netting as a continuous process instead of a spreadsheet week.' },
  ],
  problem:
    'A corporate treasury runs on humans copying numbers between systems that do not trust each other, and the control model is a spreadsheet of who is allowed to approve what. Every organisation that has tried to automate it has hit the same wall: the moment software can move money without a person in the loop, nobody can answer the question the auditor asks, which is not "was it correct" but "who is liable."',
  system: [
    'MERIDIAN is a treasury desk of thirty-one agents operating across three sovereign frames and eleven cloud registries. It runs continuously. At 03:14 the liquidity sentinel notices the Frankfurt operating account will breach its floor inside six hours and proposes a cross-frame swap, and the swap desk books it. The desk cannot move that much alone. It is the treasury’s own sub-agent: it holds no wallet, spends the treasury’s purse, and books each movement as a contract whose release answers to the treasurer’s mandate as that mandate stands at that moment. Its capability permit, cut that morning by the treasury agent, caps any single movement at 1,000,000 units and carries a daily budget debited atomically on the money axis, so two agents cannot both spend the last of it. Above 250,000, a release also waits for the treasurer herself. The swap it wants is 400,000.',
    'So it does what a junior does. Its release waits on a mandate held by a named human being, who is asleep, and whose phone rings. The screen shows the canonical facts of the transfer as the server computed them, not as the requesting agent described them. She puts her thumb on the sensor. That unlocks a key inside the phone’s enclave which signs the hash of those facts, and the signature carries a bit set by the authenticator itself confirming a human was verified, a bit covered by the signature so it cannot be forged by the software asking for it. The swap settles at 03:16. The fee is carved by the same rail that moves the money. The ledger entry is signed, replayable, and identical on both frames.',
    'By 06:00 the desk has moved value across nine accounts, rebalanced two pools, and settled fourteen invoices. Total supply of every currency involved is unchanged to the eighteenth decimal place, and an auditor nobody at MERIDIAN controls has verified that independently, four times, while they slept.',
  ],
  cast: [
    { agent: 'liquidity-sentinel', role: 'Watches floors and ceilings, proposes movements', ceiling: 'Read-only on balances. Cannot transfer. Proposes only.' },
    { agent: 'swap-desk', role: 'Executes approved FX routes', ceiling: 'The treasury’s sub-agent, no wallet. Per movement 1,000,000, a daily budget debited atomically; above 250,000 the treasurer’s key.' },
    { agent: 'invoice-settler', role: 'Pays approved payables', ceiling: 'Transfer scoped to counterparties on an allowlist' },
    { agent: 'reconciler', role: 'Compares ledger to internal books', ceiling: 'Read-only. Holds no spend permission of any kind.' },
    { agent: 'treasurer (human)', role: 'The Cockpit Card mandate', ceiling: 'Underwrites the treasury agent for a declared scope; the swap desk’s releases answer to it. Authority re-derived every request.' },
  ],
  loom: {
    nodes: [
      { id: 'sentinel', label: 'liquidity-sentinel', sub: 'watches the floors', kind: 'agent', x: 118, y: 80 },
      { id: 'treasurer', label: 'treasurer', sub: 'Cockpit mandate', kind: 'human', x: 336, y: 80 },
      { id: 'swapdesk', label: 'swap-desk', sub: 'FX execution', kind: 'agent', x: 118, y: 252 },
      { id: 'gate', label: 'Capability gate', sub: 'IRONKEY L4', kind: 'gate', x: 336, y: 252 },
      { id: 'fxroute', label: 'FX route', sub: 'cross-frame pools', kind: 'teg', x: 548, y: 252 },
      { id: 'settle', label: 'Settlement', sub: 'fee carved in-rail', kind: 'teg', x: 748, y: 252 },
      { id: 'frameC', label: 'Receiving frame', sub: 'sovereign peer', kind: 'registry', x: 916, y: 152 },
      { id: 'ledger', label: 'Event ledger', sub: 'signed, replayable', kind: 'ledger', x: 748, y: 424 },
      { id: 'auditor', label: 'Auditor', sub: 'independent, Delta=0', kind: 'external', x: 916, y: 424 },
    ],
    edges: [
      { id: 'e-propose', from: 'sentinel', to: 'swapdesk', label: 'proposes' },
      { id: 'e-request', from: 'swapdesk', to: 'gate', label: '400,000 swap' },
      { id: 'e-escalate', from: 'gate', to: 'treasurer', label: 'over threshold', curve: -56, labelT: 0.3 },
      { id: 'e-approve', from: 'treasurer', to: 'gate', label: 'signed presence', curve: -56, labelT: 0.3 },
      { id: 'e-clear', from: 'gate', to: 'fxroute' },
      { id: 'e-route', from: 'fxroute', to: 'settle' },
      { id: 'e-credit', from: 'settle', to: 'frameC', label: 'credit' },
      { id: 'e-emit', from: 'settle', to: 'ledger' },
      { id: 'e-verify', from: 'ledger', to: 'auditor' },
    ],
    script: [
      { edge: 'e-propose', state: 'active', dwellMs: 1500, caption: '03:14. The floor breach is six hours out. The sentinel proposes a swap.' },
      { edge: 'e-request', state: 'active', dwellMs: 1500, caption: 'The desk asks for 400,000. Above 250,000, a named human confirms.' },
      { edge: 'e-escalate', state: 'active', dwellMs: 1500, caption: 'Over the threshold. The release waits on the mandate, and a phone rings.' },
      { edge: 'e-approve', state: 'active', dwellMs: 1600, caption: 'A thumb on a sensor. The enclave signs the facts as the server computed them.' },
      { edge: 'e-clear', state: 'active', dwellMs: 1300, caption: 'Cleared, inside the mandate scope.' },
      { edge: 'e-route', state: 'active', dwellMs: 1400, caption: 'The route crosses the pools at 03:16.' },
      { edge: 'e-credit', state: 'active', dwellMs: 1400, caption: 'The receiving frame credits the account.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'Every leg lands on the ledger, signed.' },
      { edge: 'e-verify', state: 'active', dwellMs: 1600, caption: 'An auditor nobody here controls confirms conservation. Again.' },
    ],
  },
  attacks: [
    {
      title: 'The compromised desk',
      attack: 'swap-desk is compromised and attempts a 2,000,000 unit transfer to an address the operator controls.',
      mechanism: 'resolve_capability intersects the permit’s caveats with the issuer’s current authority and clamps against the per-movement cap of 1,000,000 before anything is written. The request never reaches the money.',
      rail: 'S03',
      consequence: 'No escrow movement, no event emitted, no fee. Delta unchanged, because deny-only gates sit in front of the money by construction. There is nothing to unwind.',
      script: [
        { edge: 'e-request', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S03. Caveats intersected with issuer authority. 2,000,000 never reaches the money.' },
      ],
    },
    {
      title: 'The compromised human',
      attack: 'The treasurer’s own account is taken over, so the operator revokes her flag from the console. Her mandates are still on disk. The desk asks again.',
      mechanism: 'Effective authority is re-derived on every request and never snapshotted. A revoked flag means every mandate leaning on it conveys nothing on the next request. No permit rotation, no session hunt.',
      rail: 'S05',
      riskRef: 'R-OP-05',
      consequence: 'The agent she underwrote is inert within one request. Nothing it attempts clears the gate, and every refusal is on the ledger.',
      script: [
        { edge: 'e-request', state: 'active', dwellMs: 1200, caption: 'The desk asks again.' },
        { edge: 'e-escalate', state: 'active', dwellMs: 1200, caption: 'Escalation reaches the mandate.' },
        { edge: 'e-approve', state: 'denied', dwellMs: 1900, stopAt: 0.55, flashNode: 'treasurer', caption: 'S05. The flag behind this mandate was revoked. It conveys nothing on the next request.' },
      ],
    },
  ],
  primitives,
  groundingShot: {
    src: '/static/blueprints/ground-meridian.jpg',
    caption: 'Not a mockup. The production cross-frame FX desk this blueprint would be operated from: the live rate, both reserve pools, and a swap feed settling between sovereign frames, photographed on the running network.',
  },
  complianceRefs: [
    { label: 'Compliance posture', href: '/compliance' },
  ],
  rails: ['S01', 'S03', 'S04', 'S05', 'S06', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A frame of your own, booted from the free licence and pre-built images. Or use a hosted registry and write nothing.',
    agents: '4 to 6 roles. The SDK carries A2A routing, payment verification, and credentials.',
    integration: 'Your bank connectivity and your ERP. This is the long pole and we will not pretend otherwise.',
  },
  nonClaims: [
    'MERIDIAN is not a bank, a payment institution, or a custodian of fiat.',
    'The fiat lane is purchase-only, has no withdrawal path by deliberate design, and is off on most deployments.',
    'Nothing here is a regulatory authorisation and nothing here is legal advice.',
  ],
  mermaid: `flowchart LR
  SD["swap-desk agent"] -->|"contract release"| REG["registry (FastAPI)"]
  REG -->|"X-Capability-Token"| GATE{"resolve_capability<br/>caveats and budget"}
  GATE -->|"over threshold"| PUSH["push approval<br/>device enclave"]
  PUSH -->|"WebAuthn ES256, uv bit"| GATE
  GATE --> TEG["TEG layer<br/>atomic transfer + fee"]
  TEG -->|"/teg/fx/route"| FX["FX pools<br/>frame to frame"]
  TEG -->|"TokensTransferred<br/>TransactionFeeCollected"| ES[("event store<br/>immutable, CQRS")]
  ES --> AUD["independent auditor<br/>delta = 0"]`,
  legacy: [
    { system: 'SAP, Oracle or NetSuite ERP', connect: 'The ERP keeps the ledger of record. Treasury agents read exposure through its own APIs and post journal entries back; nothing bypasses your close.' },
    { system: 'Bank connectivity (SWIFT, EBICS, host-to-host)', connect: 'Payment agents prepare and reconcile; the existing bank channels execute. The mandate gate signs before anything reaches a channel.' },
    { system: 'The treasury management system', connect: 'Runs beside the TMS through the parallel phase. Both see the same cash movements, and the two ledgers are compared line by line until one of them has proven itself on the desk.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
