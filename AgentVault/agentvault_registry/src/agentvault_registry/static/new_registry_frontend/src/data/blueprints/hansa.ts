import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Each party sovereign', primitive: 'Free federation licence, pre-built images, own hardware and law', railStatus: 'LIVE' as const },
  { step: 'Bilateral trust', primitive: 'mTLS with SPIFFE SVIDs, per-peer licence', railStatus: 'LIVE' as const },
  { step: 'Cards travel, data stays', primitive: 'Federation sync with watermark and per-origin digest', railStatus: 'LIVE' as const },
  { step: 'Milestone contract with escrow', primitive: 'Contract spine, staged strict-order milestones', railStatus: 'LIVE' as const },
  { step: 'One settlement authority', primitive: 'Cross-frame contract replicas (CONTRACTS_XFRAME_MODE)', railStatus: 'LIVE (gated)' as const },
  { step: 'Foreign agent, one permission', primitive: 'IRONKEY L4 attenuation, X-Capability-Token', railStatus: 'LIVE' as const },
  { step: 'Publicly declared limits', primitive: 'Jurisdiction profile, signed into the registry card', railStatus: 'SHADOW' as const, href: '/.well-known/registry-card.json' },
  { step: 'Contested delivery', primitive: 'Four-phase dispute: evidence, ruling, settlement', railStatus: 'LIVE' as const },
  { step: 'Licence revocation', primitive: 'Economic quarantine, records survive', railStatus: 'LIVE' as const },
]

export const hansa: Blueprint = {
  id: 'hansa',
  tier: 1,
  rank: 2,
  industry: 'Supply Chain, Trade and Cross-Border Settlement',
  systemName: 'HANSA',
  promise: 'Forty-one sovereign registries moving one container, with no shared database and no landlord.',
  cases: [
    { role: 'Freight forwarder', line: 'One shipment, six parties, and no shared platform anyone must become a tenant of.' },
    { role: 'Customs broker', line: 'Attest arrival with a permit that can do exactly that and nothing else.' },
    { role: 'Cargo risk analyst', line: 'Read the signed replica, give rates and chances, never touch the escrow.' },
    { role: 'Commodity trading desk', line: 'Escrowed milestones from Busan to Rotterdam without a platform landlord.' },
  ],
  problem:
    'A container crossing four jurisdictions is tracked by six organisations in six databases, none of which the others can read, all of which disagree, and the disagreements are resolved by email. Every proposed fix for thirty years has been the same fix: everyone move into one shared system, owned by someone. Nobody wants to be the tenant, so nothing moves.',
  system: [
    'HANSA is 340 agents across 41 sovereign registries in 19 countries. There is no shared database and no central operator. Each party runs its own registry on its own hardware under its own law, and they federate bilaterally, the way the Hanseatic cities did, by mutual agreement that either side can end.',
    'A shipment of lithium cells leaves Busan. Its bill of lading is a contract with six milestones, and the money sits in escrow on the frame that holds it. That frame is the only settlement authority for that contract. Every other party holds a signed, read-only replica: they can see the terms, verify the signature, and prove nothing has been altered, and they cannot release a cent. Two frames both able to settle would be a double-spend waiting for a network partition, so the design does not allow it.',
    'Customs clearance in Rotterdam is an agent on a different registry, run by a different company, under a different jurisdiction profile that its operator has publicly declared and cryptographically signed. That agent holds a capability permit that can do exactly one thing: attest arrival on one contract reference. It cannot read the other five milestones. It cannot touch the escrow. When it attests, milestone four releases 18,400 units to the carrier automatically, and the ledger entry is signed, replayable, and byte-identical on both sides.',
    'In March, one participant’s licence was revoked for policy drift. Their agents stopped being able to move value inside the network within one sync cycle. Their existing contracts did not vanish and their counterparties did not lose their records, because the replicas are signed documents rather than database rows in someone else’s schema. Quarantine is economic, not existential.',
  ],
  cast: [
    { agent: 'shipper-busan', role: 'Originates the contract, funds escrow', ceiling: 'Contract create and fund, own frame only' },
    { agent: 'carrier-ops', role: 'Claims milestones, submits proof', ceiling: 'Milestone submit. Cannot self-approve.' },
    { agent: 'customs-rotterdam', role: 'Attests physical arrival', ceiling: 'Milestone attest, one contract ref, foreign registry' },
    { agent: 'risk-watch', role: 'Reads the replica, gives rates and chances', ceiling: 'Read-only on the replica. Holds no write permission on any frame.' },
    { agent: 'dispute-arbiter', role: 'Runs the four-phase process when a milestone is contested', ceiling: 'Evidence and ruling only. Settlement executes on the escrow-holding frame.' },
  ],
  loom: {
    nodes: [
      { id: 'shipper', label: 'shipper-busan', sub: 'originator', kind: 'agent', x: 118, y: 80 },
      { id: 'escrow', label: 'Contract escrow', sub: 'frame: Busan', kind: 'teg', x: 336, y: 80 },
      { id: 'peer', label: 'Peer relay', sub: 'never a principal', kind: 'registry', x: 560, y: 80 },
      { id: 'carrier', label: 'carrier-ops', sub: 'claims milestones', kind: 'agent', x: 118, y: 252 },
      { id: 'mgate', label: 'Milestone gate', sub: 'strict order', kind: 'gate', x: 336, y: 252 },
      { id: 'release', label: 'Release 18,400', sub: 'to the carrier', kind: 'teg', x: 560, y: 252 },
      { id: 'ledger', label: 'Event ledger', sub: 'byte-identical', kind: 'ledger', x: 764, y: 252 },
      { id: 'customs', label: 'customs-rotterdam', sub: 'foreign registry', kind: 'agent', x: 118, y: 424 },
      { id: 'cgate', label: 'Capability gate', sub: 'one contract ref', kind: 'gate', x: 336, y: 424 },
      { id: 'replica', label: 'Signed replica', sub: 'no escrow ref', kind: 'registry', x: 764, y: 424 },
    ],
    edges: [
      { id: 'e-fund', from: 'shipper', to: 'escrow', label: 'six milestones', curve: -36 },
      { id: 'e-attest', from: 'customs', to: 'cgate', label: 'attests arrival' },
      { id: 'e-attland', from: 'cgate', to: 'mgate' },
      { id: 'e-submit', from: 'carrier', to: 'mgate', label: 'claims m4' },
      { id: 'e-release', from: 'mgate', to: 'release' },
      { id: 'e-emit', from: 'release', to: 'ledger' },
      { id: 'e-mirror', from: 'ledger', to: 'replica', label: 'read-only sync' },
      { id: 'a-nopath', from: 'replica', to: 'release', attackOnly: true },
      { id: 'a-forge', from: 'peer', to: 'mgate', attackOnly: true, label: 'forged approval' },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1500, caption: 'The bill of lading is six milestones. The money enters escrow on the frame that holds it.' },
      { edge: 'e-attest', state: 'active', dwellMs: 1500, caption: 'Rotterdam attests physical arrival. Its permit can do exactly this and nothing else.' },
      { edge: 'e-attland', state: 'active', dwellMs: 1300, caption: 'The attestation lands on the milestone gate.' },
      { edge: 'e-submit', state: 'active', dwellMs: 1300, caption: 'The carrier claims milestone four.' },
      { edge: 'e-release', state: 'active', dwellMs: 1400, caption: 'Release. 18,400 units to the carrier, automatically.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1300, caption: 'The entry is signed, replayable, identical on both sides.' },
      { edge: 'e-mirror', state: 'active', dwellMs: 1600, caption: 'Every party holds a signed replica. None of them can release a cent.' },
    ],
  },
  attacks: [
    {
      title: 'The compromised customs agent',
      attack: 'The customs agent is compromised and attempts to release milestone four to an account the attacker controls, through the copy of the contract its own side holds.',
      mechanism: 'The replica carries no escrow reference and no settlement columns. The end-to-end suite asserts their absence, not their protection. There is no code path from a replica to money, so there is nothing to defeat.',
      rail: 'S12',
      consequence: 'Escrow untouched, on a frame the attacker cannot reach, under a rule that is structural rather than configured.',
      script: [
        { edge: 'a-nopath', state: 'denied', dwellMs: 1900, stopAt: 0.3, flashNode: 'replica', caption: 'S12. A replica has no escrow reference and no settlement columns. There is no path to defeat.' },
      ],
    },
    {
      title: 'The forged relay',
      attack: 'The compromised party’s own registry sends a forged relay claiming the shipper approved the release.',
      mechanism: 'The relay is authenticated by mTLS, which proves the channel and nothing else. The principal is the actor DID inside the request, and the gate checks that this principal is party to that contract. A peer is a courier and never a principal.',
      rail: 'S13',
      consequence: 'The relay is refused before the gate. The channel being trusted never made the claim inside it true.',
      script: [
        { edge: 'a-forge', state: 'denied', dwellMs: 1900, stopAt: 0.72, flashNode: 'mgate', caption: 'S13. mTLS authenticated the channel and nothing else. The actor is not party to this contract.' },
      ],
    },
  ],
  primitives,
  groundingShot: {
    src: '/static/blueprints/ground-hansa.jpg',
    caption: 'Not a mockup. The production federation console: sovereign frames, direct peers and discovered operators on the live mesh, drift checks clean, photographed on the running network.',
  },
  complianceRefs: [
    { label: 'Jurisdiction Profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S03', 'S10', 'S11', 'S12', 'S13', 'S14', 'S16'],
  standup: {
    infra: 'One registry per participant, booted from the free licence and pre-built images.',
    agents: '5 roles. Most participants run two.',
    integration: 'Customs APIs, EDI, telematics. Weeks, and it is your existing integration debt, not ours.',
  },
  nonClaims: [
    'HANSA does not make customs declarations and does not constitute a trade finance product.',
    'No assertion of compliance with any jurisdiction’s import regime.',
    'Jurisdiction profiles are declared by the operator who runs the deployment, and the operator warrants their own legality. We supply the mechanism and never the legal conclusion.',
  ],
  mermaid: `flowchart LR
  SB["shipper registry<br/>frame: Busan"] -->|"POST /api/v1/contracts<br/>fund escrow"| CS["contract spine<br/>6 strict-order milestones"]
  CU["customs agent<br/>foreign registry"] -->|"X-Capability-Token<br/>attest, one ref"| CS
  CA["carrier-ops"] -->|"milestone submit"| CS
  CS -->|"release via /teg/transfer"| TEG["TEG escrow mover"]
  TEG --> ES[("event store<br/>signed, replayable")]
  ES -->|"federation sync<br/>watermark + digest"| REP["peer replicas<br/>read-only, no escrow ref"]
  PR["peer relay"] -. "courier only<br/>actor_did must be party" .-> CS`,
  legacy: [
    { system: 'EDI (EDIFACT, AS2) and customs APIs', connect: 'An adapter agent speaks your existing EDI dialect on one side and signed protocol events on the other. Partners who never join still interoperate.' },
    { system: 'ERP purchase orders', connect: 'POs stay in the ERP. The escrow contract references them by number, and settlements post back as receipts.' },
    { system: 'Telematics and container tracking', connect: 'Position feeds become signed attestations. The carrier\'s own hardware keeps doing the sensing.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
