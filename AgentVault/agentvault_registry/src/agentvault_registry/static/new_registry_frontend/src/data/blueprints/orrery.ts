import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ORRERY: space and satellite operations (§BPFRONTIER 2026-09-25). A frontier chamber: the sector is arriving now;
// the rails are the live ones. Operators, ground-station networks and space-traffic services each run a sovereign
// frame; the protocol carries identity, authority, money and evidence between them, and never a command.

const primitives = [
  { step: 'A named flight director behind every spend', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Networks and budgets as bounds', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, atomic budget debit', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Antenna time escrowed at booking', primitive: 'Contract spine: escrow at booking, released on the attested pass', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'Each antenna its own identity', primitive: 'SPIFFE identity per antenna agent, short-lived certificates', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'A pass report is a signature', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'Screenings paid once each', primitive: 'A2A payment authorization: single-use payment authorization, exactly-once settlement', railStatus: 'LIVE' as const, href: '/docs/09' },
  { step: 'A key in hand above 500 units', primitive: 'WebAuthn presence proof; an expired confirmation is a recorded denial', railStatus: 'LIVE' as const, href: '/docs/30' },
  { step: 'A breached station, cut off', primitive: 'IRONHAND identity revocation over the event stream, under 500ms', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Paid once, whatever the retries', primitive: 'Idempotency keys, two-layer dedup', railStatus: 'LIVE' as const },
  { step: 'Three parties, three frames', primitive: 'Cross-registry transfer, exactly-once, across sovereign frames', railStatus: 'LIVE' as const, href: '/docs/18' },
  { step: 'The network’s copy of each booking', primitive: 'Cross-frame contract replicas; a replica carries no path to money', railStatus: 'LIVE (gated)' as const, href: '/docs/31' },
  { step: 'A mission anyone can replay', primitive: 'Immutable event ledger, replayable, forensically searchable', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'A missed pass, contested', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const, href: '/docs/04' },
]

export const orrery: Blueprint = {
  id: 'orrery',
  tier: 2,
  frontier: true,
  rank: 23,
  industry: 'Space and Satellite Operations',
  systemName: 'ORRERY',
  promise: 'Downlink passes escrowed at booking and paid on the antenna’s own signed report, conjunction warnings bought per screening, and the manoeuvre left to a named flight director.',
  cases: [
    { role: 'Earth-observation operator', line: 'Passes booked and paid per pass, inside a flight director’s mandate.' },
    { role: 'Ground-station network', line: 'Antenna time sold per pass and paid on the antenna’s own signed report.' },
    { role: 'Space-traffic service', line: 'Screenings paid per screening, every warning signed and on the record.' },
    { role: 'Research payload team', line: 'Passes and screenings for one payload under its lead’s mandate, without a purchasing round trip.' },
  ],
  problem:
    'The ground segment still settles on paperwork. An operator books antenna time at another company’s station through a portal, the pass report comes back as a log file, and payment follows weeks later against a spreadsheet of passes that neither side can independently check. Conjunction warnings arrive by email, and when a manoeuvre is questioned afterwards, nobody can show which warning was read, who decided, or under whose authority the money moved.',
  system: [
    'ORRERY is where the ground segment settles: satellite operators, ground-station networks and space-traffic services, each on its own sovereign frame. At 22:10 UTC on a Thursday, Halcyon Imaging’s scheduling agent books pass 48213 for its earth-observation satellite HALCYON-7: the network’s antenna at Punta Clara, on a headland at the southern tip of South America, acquisition due at 04:17, 120 units. The 120 units are escrowed at booking and released on one thing only: the pass report signed by the station’s own antenna agent, under an identity its frame issues on a certificate that lives hours, not years. At 04:28 the report arrives: signal acquired at 04:17:06, lost at 04:27:51, 46.8 GB received. The pass is paid exactly once, and a pass that no antenna signed cannot be paid at all.',
    'Mara Lindqvist, Halcyon’s flight director, never fills in a purchase order. She underwrites the mission planner with one mandate, confirmed with her device key: four approved networks, one traffic service, and no single spend above 500 units without her key in hand. The planner’s purse is funded 9,000 units a month, and nothing spends what it does not hold. The scheduler is the planner’s own sub-agent: it holds no wallet, books against the planner’s purse, and every booking it makes is checked against her mandate as it stands at that moment. The planner cuts it a capability permit, and a permit can only narrow what its issuer holds. The traffic service screens the constellation twice a day, paid per screening through a single-use payment authorization, and signs every warning under its own identity. At 06:40 one lands: HALCYON-4 and a debris fragment, closest approach at 11:02 UTC. The decision to manoeuvre is hers alone. The priority pass that carries her burn plan up costs 900 units, so it waits on her phone until her key signs it, and a request left unanswered expires as a recorded denial.',
    'The protocol carries authority, money and evidence, and it never commands a spacecraft: the burn goes up through Halcyon’s own mission control, as it always has. What changes is the record. The warning, her signature, the pass that carries the burn plan and the antenna’s report are each kept on an append-only record, in the order they occur, for the network, Halcyon’s insurer or the traffic service to replay. When the network finds a breach at one of its stations, it revokes that antenna’s identity, which dies in under 500ms over the event stream. A report from a revoked antenna, or from anyone but the antenna a pass contract names, is refused before anything is released.',
  ],
  cast: [
    { agent: 'flight director (human)', role: 'Mara Lindqvist. Underwrites the planner, decides every manoeuvre', ceiling: 'One mandate: four networks, one traffic service. Any spend above 500 units waits for her device key.' },
    { agent: 'mission-planner', role: 'Plans each day’s passes and screenings', ceiling: 'Spends inside her mandate from a purse funded 9,000 units a month. Re-derived on every request, so revoking it stops the next booking.' },
    { agent: 'pass-scheduler', role: 'Books the passes', ceiling: 'The planner’s sub-agent, with no wallet of its own. A permit cut from the planner’s: four networks, this week’s budget. Cannot widen either.' },
    { agent: 'antenna-PCL-2', role: 'Tracks each pass at Punta Clara, signs the report', ceiling: 'Attests its own passes. Holds no budget and releases nothing.' },
    { agent: 'traffic-screener', role: 'Screens the constellation, signs each warning', ceiling: 'Paid per screening through a single-use payment authorization. Holds no authority over any spacecraft.' },
  ],
  loom: {
    nodes: [
      { id: 'fd', label: 'Mara Lindqvist', sub: 'flight director', kind: 'human', x: 118, y: 110 },
      { id: 'screener', label: 'traffic-screener', sub: 'signs each warning', kind: 'agent', x: 336, y: 110 },
      { id: 'escrow', label: 'Pass escrow', sub: 'held from booking', kind: 'teg', x: 560, y: 110 },
      { id: 'ledger', label: 'Mission ledger', sub: 'passes, replayable', kind: 'ledger', x: 764, y: 110 },
      { id: 'sched', label: 'pass-scheduler', sub: 'books on a permit', kind: 'agent', x: 118, y: 330 },
      { id: 'mgate', label: 'Mandate gate', sub: 'networks, budget, key', kind: 'gate', x: 336, y: 330 },
      { id: 'pgate', label: 'Pass contract', sub: 'names its antenna', kind: 'gate', x: 560, y: 330 },
      { id: 'antenna', label: 'antenna-PCL-2', sub: 'signs the report', kind: 'agent', x: 764, y: 330 },
      { id: 'peer', label: 'peer frame', sub: 'a valid channel', kind: 'registry', x: 336, y: 450 },
    ],
    edges: [
      { id: 'e-book', from: 'sched', to: 'mgate', label: 'pass 48213' },
      { id: 'e-escrow', from: 'mgate', to: 'escrow', label: '120 units' },
      { id: 'e-report', from: 'antenna', to: 'pgate', label: 'signed' },
      { id: 'e-release', from: 'pgate', to: 'escrow' },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-warn', from: 'screener', to: 'fd' },
      { id: 'e-key', from: 'fd', to: 'mgate', label: 'key above 500' },
      { id: 'a-burst', from: 'sched', to: 'mgate', attackOnly: true, curve: 46, label: '400 bookings' },
      { id: 'a-clone', from: 'peer', to: 'pgate', attackOnly: true, curve: 44, label: 'pass never taken' },
    ],
    script: [
      { edge: 'e-book', state: 'active', dwellMs: 1500, caption: 'At 22:10 UTC the scheduler books pass 48213: HALCYON-7 over Punta Clara at 04:17, 120 units, inside the mandate.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'An approved network, inside this week’s budget: the 120 units are escrowed at booking. Nothing is paid yet.' },
      { edge: 'e-report', state: 'active', dwellMs: 1500, caption: 'At 04:28 the antenna signs its report: signal acquired 04:17:06, lost 04:27:51, 46.8 GB received.' },
      { edge: 'e-release', state: 'active', dwellMs: 1400, caption: 'The contract names antenna-PCL-2 as its only attesting party. The signature is its own, so the escrow releases.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The network is paid exactly once, and the pass lands on the ledger beside its report.' },
      { edge: 'e-warn', state: 'active', dwellMs: 1500, caption: 'At 06:40 a signed warning reaches her, paid per screening: HALCYON-4 and a debris fragment, closest approach 11:02.' },
      { edge: 'e-key', state: 'active', dwellMs: 1600, caption: 'The manoeuvre is her decision. The 900-unit uplink pass waits for her key; a request left unanswered is a recorded denial.' },
    ],
  },
  attacks: [
    {
      title: 'The cloned antenna',
      attack: 'A copy of the antenna agent’s software, running on a peer frame with a valid federation channel, submits a signed report for pass 48219, a pass the Punta Clara antenna never took, to collect its escrow.',
      mechanism: 'The pass contract names antenna-PCL-2, by its identity on the network’s frame, as the one party whose report releases it. The report arrives over a valid mTLS channel, and the channel proves one thing: which frame couriered it. The principal inside the report is the copy, and copying an agent’s code does not copy its identity, which only its own frame issues. The contract checks the principal against the party it names before any release is considered.',
      rail: 'S13',
      consequence: 'The escrow does not move. Pass 48219 stays unpaid until the named antenna reports or Halcyon disputes the booking, and the refused report is recorded with the frame that couriered it.',
      script: [
        { edge: 'a-clone', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'pgate', caption: 'S13. The channel is valid and proves only the courier. The contract names antenna-PCL-2, and a copy is not the named antenna.' },
      ],
    },
    {
      title: 'The runaway scheduler',
      attack: 'A scheduler compromised through a build server tries to book 400 passes in an hour, 48,000 units of antenna time, each booking kept under the 500 units at which the flight director’s key is required.',
      mechanism: 'The scheduler never holds Halcyon’s budget. It books on a capability permit cut from the planner’s mandate, whose caveats carry the four approved networks and this week’s budget of 2,400 units, debited atomically with each booking. Every booking is checked against those caveats and the issuer’s authority as it stands now, before any escrow is touched. The flight director’s key does not stop this attack, because each booking stays under her threshold; the permit does, because its budget travels with the permit and not with the scheduler’s intentions.',
      rail: 'S03',
      consequence: 'The burst commits no more than what is left of this week’s 2,400 units, every unit escrowed at an approved network and released only on a signed pass report. Everything past the budget is refused before a unit moves, and each refusal is recorded.',
      script: [
        { edge: 'a-burst', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'mgate', caption: 'S03. Each booking debits the permit’s budget for the week, atomically. Past it, the burst is refused before a unit moves.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' },
    { label: 'Incident Response (the P1 clock)', href: '/compliance/doc/incident-response-procedures' },
    { label: 'Jurisdiction profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S03', 'S05', 'S06', 'S07', 'S13', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'Each operator, network and traffic service on its own frame, federated, booted from the free licence and pre-built images. Nothing to write.',
    agents: 'A planner and a scheduler per operator, one agent per antenna, one screener per traffic service. Scheduling logic and flight dynamics stay the operator’s; the SDK carries identity, payment and attestation.',
    integration: 'Mission control, the network’s scheduling interface and the traffic service’s tracking feeds. This is where the real time goes, and it stays with the teams that run those systems.',
  },
  nonClaims: [
    'ORRERY does not command spacecraft, compute orbits or screen conjunctions. It carries identity, authority, money and evidence for the services that do.',
    'Spectrum licensing, launch and space-object registration stay with the regulators and operators that hold them. A caveat narrows what an agent may book; it grants no licence to transmit.',
    'The decision to manoeuvre stays with the operator’s flight director. A signed warning proves who said what and when, not that the screening was right.',
    'No conformity with any national space law, spectrum rule or export-control regime is claimed or implied.',
  ],
  mermaid: `flowchart LR
  FD(["Mara Lindqvist<br/>flight director"]) -->|"key above 500"| G{"mandate gate<br/>networks, budget, key"}
  S["pass-scheduler"] -->|"pass 48213"| G
  G -->|"120 units, escrowed"| E["pass escrow"]
  A["antenna-PCL-2<br/>Punta Clara"] -->|"report, signed"| C{"pass contract<br/>names its antenna"}
  C -->|"release, once"| E
  E --> L[("mission ledger<br/>replayable")]
  T["traffic-screener"] -.->|"warning, signed"| FD`,
  legacy: [
    { system: 'Mission control software', connect: 'Commands, telemetry and flight dynamics stay where they run. A booked pass carries the mission control pass ID, and the burn goes up the way it always has.' },
    { system: 'Ground-station scheduling interfaces', connect: 'A booking made through the network’s interface becomes an escrowed pass contract. The network’s scheduler still owns the antenna calendar.' },
    { system: 'Space surveillance data feeds', connect: 'Screenings run on the traffic service’s own data. Each warning arrives signed and paid for, and stays on the record beside the decision it informed.' },
    { system: 'Billing and pass accounting', connect: 'Passes settle from escrow on the signed report. Finance reads settlement instead of reconciling pass logs against invoices.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
