import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'A vessel is an identity, not an email thread', primitive: 'DIDs with mTLS certificates per vessel and agent', railStatus: 'LIVE' as const },
  { step: 'Port-call money set aside before arrival', primitive: 'Escrowed disbursement accounts with staged release', railStatus: 'LIVE' as const },
  { step: 'Laytime is a clock both sides read', primitive: 'Signed port attestations: NOR, berthing, completion', railStatus: 'LIVE' as const },
  { step: 'Demurrage disputes with evidence', primitive: 'Four-phase dispute over the attested timeline', railStatus: 'LIVE' as const },
  { step: 'Each port under its own law', primitive: 'Sovereign registries, jurisdiction profiles declared', railStatus: 'LIVE' as const },
  { step: 'Cross-border settlement', primitive: 'Cross-registry transfer, exactly-once, fees explicit', railStatus: 'LIVE' as const },
]

export const admiralty: Blueprint = {
  id: 'admiralty',
  tier: 2,
  vault: true,
  rank: 21,
  industry: 'Maritime and Port Operations',
  systemName: 'ADMIRALTY',
  promise: 'Port calls that settle from escrow on signed events, and demurrage decided on an attested clock instead of competing spreadsheets.',
  cases: [
    { role: 'Ship operator', line: 'Disbursements escrowed per call, released on signed events.' },
    { role: 'Port agent', line: 'Paid from escrow at completion, not chased for ninety days.' },
    { role: 'Charterer', line: 'Laytime on an attested timeline both sides already signed.' },
    { role: 'Port authority', line: 'A sovereign registry under your law, federated with the fleet’s.' },
  ],
  problem:
    'A single port call scatters money across agency fees, pilotage, towage and dues, settled by invoice weeks later; and when the ship overstays her laytime, the demurrage claim is two spreadsheets disagreeing about when the clock started, argued by email for a year. The industry that standardised the container never standardised the handshake.',
  system: [
    'ADMIRALTY gives the vessel an identity and the port call an escrow. Before MV Kestrel arrives, her operator funds the call: agency, pilotage, towage, dues, one escrowed disbursement account the port agent can see but not raid. The call then settles itself off signed events, because the events are attestations, not emails: notice of readiness signed by the master’s agent, berthing signed by the port, completion signed by both. Each service releases its slice at its trigger, and the agent who used to finance the ship’s costs and chase reimbursement for a quarter is simply paid at completion.',
    'The same attested timeline is what kills the demurrage fight. Laytime runs from the signed NOR to the signed completion; the clock is not a claim either side makes but a record both already signed at the time. When there is still a genuine dispute, the weather clause, the excepted period, it goes through a dispute with the timeline as shared evidence and the disputed amount held until ruling. Ports run sovereign registries under their own law with their jurisdiction profiles declared, the fleet federates across them, and a voyage across four jurisdictions settles in each one without anyone wiring money on faith.',
  ],
  cast: [
    { agent: 'vessel-kestrel', role: 'The ship’s transacting identity', ceiling: 'Funds its own calls; spend policy per voyage.' },
    { agent: 'port-agent-piraeus', role: 'Coordinates the call, signs events', ceiling: 'Attests and claims its own service. Cannot touch other slices.' },
    { agent: 'port-authority', role: 'Signs berthing, levies dues', ceiling: 'Its own attestations and its own tariff.' },
    { agent: 'charter-desk', role: 'Runs laytime and demurrage', ceiling: 'Reads the timeline; disputes with evidence.' },
  ],
  loom: {
    nodes: [
      { id: 'operator', label: 'ship operator', sub: 'funds the call', kind: 'external', x: 118, y: 220 },
      { id: 'escrow', label: 'Call escrow', sub: 'agency, dues, towage', kind: 'teg', x: 336, y: 110 },
      { id: 'gate', label: 'Event gate', sub: 'signed NOR, berth', kind: 'gate', x: 560, y: 110 },
      { id: 'agent', label: 'port-agent', sub: 'signs the events', kind: 'agent', x: 336, y: 330 },
      { id: 'authority', label: 'port authority', sub: 'sovereign registry', kind: 'registry', x: 118, y: 330 },
      { id: 'payout', label: 'Staged release', sub: 'per service event', kind: 'teg', x: 764, y: 110 },
      { id: 'ledger', label: 'Voyage ledger', sub: 'the attested clock', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-fund', from: 'operator', to: 'escrow', label: 'call funded pre-arrival' },
      { id: 'e-nor', from: 'agent', to: 'gate', label: 'NOR, signed' },
      { id: 'e-berth', from: 'authority', to: 'gate', label: 'berthing, signed', curve: -24 },
      { id: 'e-release', from: 'gate', to: 'payout' },
      { id: 'e-emit', from: 'payout', to: 'ledger' },
      { id: 'a-clock', from: 'agent', to: 'ledger', attackOnly: true, label: 'rewrite the laytime clock' },
    ],
    script: [
      { edge: 'e-fund', state: 'active', dwellMs: 1400, caption: 'The disbursement account escrows before arrival. Visible, not raidable.' },
      { edge: 'e-nor', state: 'active', dwellMs: 1400, caption: 'Notice of readiness is a signed attestation. The clock starts on record.' },
      { edge: 'e-berth', state: 'active', dwellMs: 1400, caption: 'The port signs berthing under its own sovereign registry.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'Each service releases its slice at its trigger.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'The voyage ledger holds the timeline both sides signed at the time.' },
    ],
  },
  attacks: [
    {
      title: 'The retroactive clock',
      attack: 'Facing a six-figure demurrage claim, a party submits a corrected timeline moving the notice of readiness eleven hours later.',
      mechanism: 'The NOR is an attestation signed by identified parties at the time, on an append-only ledger; there is no rail that rewrites a signed event, only one that adds a later, visibly later, statement. A demurrage case argues the clauses, not the clock.',
      rail: 'S14',
      consequence: 'The original timestamp stands, the correction attempt is itself on the record, and the dispute proceeds over the signed timeline with the disputed amount held until ruling.',
      script: [
        { edge: 'a-clock', state: 'denied', dwellMs: 1900, stopAt: 0.68, flashNode: 'ledger', caption: 'S14. Signed events do not move. Argue the clauses, not the clock.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Jurisdiction profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S02', 'S13', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A sovereign registry per port authority; operators and charterers federate in from their own.',
    agents: '4 to 6 roles per port; the vessel identity travels with the ship across all of them.',
    integration: 'AIS, terminal systems and the ship’s agent workflow feed the attestors; navigation and cargo operations stay where they are.',
  },
  nonClaims: [
    'ADMIRALTY settles money and evidences timelines; charterparty law, general average and the law of the sea remain with the contracts and tribunals that own them.',
    'A signed timeline is evidence, not a verdict: excepted periods and weather clauses are still argued by humans, just over a record instead of against one.',
  ],
  mermaid: `flowchart LR
  OP["ship operator"] -->|"fund the call pre-arrival"| TEG["call escrow<br/>agency + dues + towage"]
  PA["port agent"] -->|"NOR, completion signed"| G{"event gate"}
  AUTH["port authority<br/>sovereign registry"] -->|"berthing signed"| G
  G -->|"staged release per service"| TEG
  CH["charter desk"] -.->|"demurrage dispute<br/>over attested timeline"| DS["dispute, amount held"]
  TEG --> ES[("voyage ledger<br/>the clock both sides signed")]`,
  legacy: [
    { system: 'AIS and terminal operating systems', connect: 'Port events feed the attestors. Navigation and cargo operations stay where they are.' },
    { system: 'Ship agency workflows', connect: 'The disbursement account becomes one escrowed, visible account. The agent\'s tools keep producing the events.' },
    { system: 'Port community systems', connect: 'The attested timeline mirrors into the PCS. Demurrage argues over a record, not against one.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
