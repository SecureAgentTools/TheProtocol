import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ZEPHYR: drone logistics and urban air mobility (frontier wave 2026-09-25). Every city runs its own frame,
// because airspace rules are local. A fleet books a corridor slot and a charging pad per flight, escrowed at
// booking and released on the pad's own signed arrival; a grounded drone's identity dies in under 500ms.
// A frontier chamber: the sector is arriving now; the rails are the live ones.

const primitives = [
  { step: 'Every drone its own identity', primitive: 'SPIFFE identity per drone agent, short-lived certificates', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Slot and pad escrowed at booking', primitive: 'Contract spine: escrow at booking, released on the signed arrival', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'Paid on the pad’s own signature', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'The pad signs from its own frame', primitive: 'Cross-frame contract replicas: the escrow stays home, the counterparty acts from its own frame', railStatus: 'LIVE (gated)' as const, href: '/docs/31' },
  { step: 'Only the cities on the permit', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, atomic budget debit, checked before escrow', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Grounded in under half a second', primitive: 'IRONHAND identity revocation over the event stream, under 500ms', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Account and receipts closed with it', primitive: 'Coordinated suspension: mTLS, account, cross-frame receipt', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Each payee paid on its own frame', primitive: 'Cross-registry transfer, exactly-once, idempotency-keyed', railStatus: 'LIVE' as const, href: '/docs/05' },
  { step: 'A flight that never lands', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'Every flight on a replayable record', primitive: 'Immutable event ledger, replayable, forensically searchable', railStatus: 'LIVE' as const, href: '/docs/07' },
  { step: 'Every unit accounted for', primitive: 'Delta = 0 supply invariant, independently audited', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
]

export const zephyr: Blueprint = {
  id: 'zephyr',
  tier: 2,
  frontier: true,
  rank: 24,
  industry: 'Drone Logistics and Urban Air Mobility',
  systemName: 'ZEPHYR',
  promise: 'Drone fleets that book a city’s corridor slot and a vertiport’s pad per flight, pay on the pad’s signed arrival, and are refused everywhere within half a second of being grounded.',
  cases: [
    { role: 'Delivery fleet operator', line: 'Slots and pads booked per flight, paid on arrival, only in the cities you hold permits for.' },
    { role: 'Vertiport operator', line: 'Pad time sold per landing and paid on your own pad’s signature.' },
    { role: 'City airspace office', line: 'Corridor slots sold from the city’s own frame, each one paid exactly once.' },
    { role: 'Hospital courier network', line: 'Lab samples across the city, every flight on a record an auditor can replay.' },
  ],
  problem:
    'Drone delivery is arriving one city at a time, and each city writes its own airspace rules. A fleet that flies three cities keeps three permit files, books corridor time and charging pads through as many portals, and settles by monthly invoice. When a drone fails an inspection it is grounded in the fleet’s own system, and the slot service and the vertiport across town find out when someone remembers to call.',
  system: [
    'ZEPHYR is a drone logistics network in which every city runs its own sovereign frame, because every city sets its own airspace rules: its corridors, its quiet hours, its closed days. A courier fleet of 140 drones works two of those cities for a hospital group and a parts distributor. At 06:52 on a Thursday the fleet’s dispatch agent books slot MH-C4-0710 in Marholm’s corridor 4 and charging pad 2 on the central laboratory’s roof for drone ZP-0419, which carries a cooler of blood samples from the north clinic: 4 units to the city’s slot service and 6 to the vertiport, both escrowed at booking. ZP-0419 lands at 07:23, and the pad agent, a party to the booking, signs the arrival with its own identity. The ten units release once, to two frames, on that signature and on nothing else.',
    'Every drone is its own agent with its own certificate, and certificates live hours, not years. Grounding one is a single action, whether the cause is a failed inspection or a report from a city. At 11:40 drone ZP-0388 fails its post-flight inspection with a cracked propeller hub, and Tove Nyland, the maintenance lead, grounds it. Its identity is revoked over the event stream in under 500ms, and the same coordinated suspension blocks its account and its cross-frame receipts. Its onboard agent, still working through the afternoon’s queue, keeps trying to book slots and pads. Its home frame no longer authenticates it, so no payment authorization is ever issued for it, and no slot service or pad holds anything without one.',
    'Dispatch books only where the fleet holds permits. Its capability permit names the slot services of Marholm and Ostervik, the vertiports the fleet may land at, and a budget debited atomically. Each drone’s own permit is cut from it, narrower still, because a permit can only narrow what its issuer holds. A booking addressed to Tallvik, where the fleet holds no permit, is refused before any escrow moves, and the refusal is recorded.',
  ],
  cast: [
    { agent: 'fleet-dispatch', role: 'Books a slot and a pad for every flight', ceiling: 'A permit naming two cities’ slot services, their vertiports and a budget. Cannot widen any of them.' },
    { agent: 'ZP-0419 and 139 more', role: 'Fly, land, rebook a slipped window', ceiling: 'Each holds a permit cut from dispatch’s, narrower still, and a certificate revocable in under 500ms.' },
    { agent: 'slots-marholm', role: 'Sells corridor slots from the city’s frame', ceiling: 'Sells and confirms slots. Paid on arrival, exactly once; it cannot draw on the escrow.' },
    { agent: 'pad-CL-2', role: 'Signs each arrival on pad 2', ceiling: 'Attests landings on its own pad. Holds no budget and releases nothing.' },
    { agent: 'maintenance lead (human)', role: 'Grounds a drone after a failed inspection', ceiling: 'Revocation and suspension, in one action. Cannot book, cannot pay.' },
  ],
  loom: {
    nodes: [
      { id: 'dispatch', label: 'fleet-dispatch', sub: 'books slot and pad', kind: 'agent', x: 118, y: 220 },
      { id: 'gate', label: 'Corridor gate', sub: 'two cities, one budget', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Flight escrow', sub: '10 units, at booking', kind: 'teg', x: 560, y: 110 },
      { id: 'ledger', label: 'Flight ledger', sub: 'flights, replayable', kind: 'ledger', x: 764, y: 110 },
      { id: 'slots', label: 'Marholm slots', sub: 'the city’s own frame', kind: 'registry', x: 560, y: 330 },
      { id: 'pad', label: 'pad-CL-2', sub: 'signs each arrival', kind: 'agent', x: 764, y: 330 },
      { id: 'lead', label: 'Tove Nyland', sub: 'maintenance lead', kind: 'human', x: 118, y: 450 },
      { id: 'ground', label: 'Grounding', sub: 'revoked in under 500ms', kind: 'gate', x: 336, y: 450 },
      { id: 'drones', label: 'drone agents', sub: 'one certificate each', kind: 'agent', x: 560, y: 450 },
    ],
    edges: [
      { id: 'e-book', from: 'dispatch', to: 'gate', label: 'slot + pad' },
      { id: 'e-escrow', from: 'gate', to: 'escrow', label: '10 units' },
      { id: 'e-hold', from: 'gate', to: 'slots', label: 'MH-C4-0710', labelT: 0.6 },
      { id: 'e-land', from: 'drones', to: 'pad' },
      { id: 'e-arrive', from: 'pad', to: 'escrow', label: 'arrival, signed' },
      { id: 'e-release', from: 'escrow', to: 'ledger' },
      { id: 'e-ground', from: 'lead', to: 'ground', label: 'one action' },
      { id: 'e-dead', from: 'ground', to: 'drones', label: 'identity dies' },
      { id: 'a-rebook', from: 'drones', to: 'slots', attackOnly: true, curve: 44, label: 'ZP-0388, again' },
      { id: 'a-tallvik', from: 'dispatch', to: 'gate', attackOnly: true, curve: 44, label: 'a Tallvik slot' },
    ],
    script: [
      { edge: 'e-book', state: 'active', dwellMs: 1500, caption: '06:52. fleet-dispatch books slot MH-C4-0710 and pad 2 on the central lab’s roof, for drone ZP-0419 and its samples.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'Marholm is on the permit. Four units for the slot and six for the pad are escrowed at booking, on the fleet’s frame.' },
      { edge: 'e-hold', state: 'active', dwellMs: 1300, caption: 'The city’s slot service, on Marholm’s own frame, holds corridor 4 for the 07:10 window.' },
      { edge: 'e-land', state: 'active', dwellMs: 1300, caption: '07:23. ZP-0419 lands on pad 2 with a cooler of blood samples from the north clinic.' },
      { edge: 'e-arrive', state: 'active', dwellMs: 1500, caption: 'The pad agent signs the arrival with its own identity. Nothing else can release the escrow.' },
      { edge: 'e-release', state: 'settled', dwellMs: 1400, caption: 'Ten units release exactly once, to the city’s frame and the vertiport’s, and the flight lands on the ledger.' },
      { edge: 'e-ground', state: 'active', dwellMs: 1500, caption: '11:40. ZP-0388 fails its post-flight inspection: a cracked propeller hub. The maintenance lead grounds it with one action.' },
      { edge: 'e-dead', state: 'active', dwellMs: 1500, caption: 'Its identity dies over the event stream in under 500ms. Its account and its cross-frame receipts are blocked with it.' },
    ],
  },
  attacks: [
    {
      title: 'The grounded drone that keeps asking',
      attack: 'ZP-0388 has been grounded since 11:40, but its onboard agent is still working through the afternoon’s queue and keeps trying to book slots and pads for flights it will not fly.',
      mechanism: 'The grounding was one coordinated suspension: the drone’s identity revoked over the event stream in under 500ms, its account suspended, its cross-frame receipts blocked. A slot or a pad is held only against a payment authorization, and the drone’s home frame refuses to authenticate a suspended agent, so no payment authorization is ever issued in its name.',
      rail: 'S08',
      consequence: 'No slot held, no pad reserved, no escrow touched. Every attempt is refused, and every flight ZP-0388 flew before its hub cracked stays on the ledger.',
      script: [
        { edge: 'a-rebook', state: 'denied', dwellMs: 1900, stopAt: 0.72, flashNode: 'slots', caption: 'S08. ZP-0388 was suspended at 11:40 in one action. No payment authorization is issued in its name, so no slot is held.' },
      ],
    },
    {
      title: 'The slot in a city without a permit',
      attack: 'A compromised dispatch agent books a corridor slot from Tallvik’s slot service, in a city where the fleet holds no permit.',
      mechanism: 'Dispatch acts on a capability permit whose caveats name its counterparties: the slot services of Marholm and Ostervik and their vertiports. The booking is checked against those caveats, intersected with the issuer’s authority as it stands now, before any escrow is touched. A permit can narrow what its issuer holds; it cannot add a city.',
      rail: 'S03',
      consequence: 'No slot, no escrow movement, nothing to unwind. The refusal is recorded for the operations desk.',
      script: [
        { edge: 'a-tallvik', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'gate', caption: 'S03. The permit names two cities’ slot services. A slot in Tallvik is refused before a unit moves.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Jurisdiction Profiles', href: '/compliance/doc/jurisdiction-profiles' },
    { label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' },
  ],
  rails: ['S01', 'S03', 'S07', 'S08', 'S13', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A frame for each city and one for the fleet, federated; vertiports on their own frame or a seat on the city’s. Each frame boots from the free licence and pre-built images.',
    agents: 'Dispatch, one agent per drone and one per pad. Routing and fleet logic stay the operator’s; the SDK carries identity, payment and attestation.',
    integration: 'The traffic management supplier, the fleet and maintenance systems, the vertiport’s pad calendar. This is where the real time goes, and it stays with the operators.',
  },
  nonClaims: [
    'ZEPHYR does not fly, route, deconflict or certify aircraft. Air traffic management, airworthiness and every permit stay with the authorities and operators that own them; ZEPHYR carries identity, authority and settlement for the services around the flight.',
    'A grounding ends a drone’s identity on the network. It does not stop a rotor, and it replaces no inspection, maintenance programme or safety decision.',
    'No claim of conformity with any aviation regulation, standard or certification scheme is made or implied.',
  ],
  mermaid: `flowchart LR
  D["fleet-dispatch"] -->|"slot + pad"| G{"corridor gate<br/>two cities, one budget"}
  G -->|"10 units, escrowed"| E["flight escrow"]
  G -->|"slot MH-C4-0710"| S["Marholm slots<br/>city frame"]
  Z["drone ZP-0419"] -->|"lands 07:23"| P["pad-CL-2"]
  P -->|"arrival, signed"| E
  E -->|"released once"| L[("flight ledger<br/>flights, replayable")]
  T(["Tove Nyland<br/>maintenance lead"]) -->|"one action"| R{"grounding<br/>under 500ms"}
  R -.->|"identity, account, receipts"| X["drone ZP-0388"]`,
  legacy: [
    { system: 'UAS traffic management service suppliers', connect: 'Flight plans, deconfliction and conformance stay with the supplier. Each booking carries the supplier’s flight reference, so the two records join up.' },
    { system: 'Fleet management and maintenance systems', connect: 'Inspections are recorded where they are recorded today. A failed one becomes one grounding action on the drone’s identity, account and cross-frame receipts.' },
    { system: 'Vertiport booking systems', connect: 'The pad calendar stays in the vertiport’s system. Each booking becomes an escrowed contract and each landing a signed attestation.' },
    { system: 'City permit systems', connect: 'Permits are issued where they are issued today. A permit becomes a city the dispatch permit may name, and the city keeps the decision.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
