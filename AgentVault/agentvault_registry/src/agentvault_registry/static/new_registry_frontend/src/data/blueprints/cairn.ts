import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// CAIRN: off-world sites beyond live contact (agentvault2-69, 2026-10-26, on his word). A frontier chamber: the rails
// are the live ones, carried to a site that runs its own frame through two weeks without a link. Machines from several
// companies work there, each frame sovereign; the protocol carries authority, payment and evidence, never a command.

const primitives = [
  { step: 'A named mission director behind every spend', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request on the site’s own frame', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Budgets, scopes and expiries as bounds', primitive: 'IRONKEY L4 capability caveats: atomic budget debit, expiry, attenuation only', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Work escrowed at posting', primitive: 'Contract spine: escrow at posting, released on the named attester’s signature', railStatus: 'LIVE' as const, href: '/docs/04' },
  { step: 'Each machine its own identity', primitive: 'SPIFFE identity per machine agent, short-lived certificates issued on site', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Power and drill time, priced', primitive: 'Agent-to-agent payments in units, exactly-once, under the site’s own supply invariant', railStatus: 'LIVE' as const },
  { step: 'Tested before it flies', primitive: 'Evals against scenarios, and a version lineage that travels with each agent', railStatus: 'LIVE (gated)' as const, href: '/docs/27' },
  { step: 'A machine that drifts, restricted', primitive: 'EigenTrust track records and the frame’s trust policy, restricting below its threshold', railStatus: 'LIVE' as const },
  { step: 'A key in hand above 500 units', primitive: 'WebAuthn presence proof; an unanswered request is a recorded denial', railStatus: 'LIVE' as const, href: '/docs/30' },
  { step: 'A compromised machine, cut off', primitive: 'IRONHAND identity revocation over the event stream, under 500ms', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Three parties, three frames', primitive: 'Cross-registry transfer, exactly-once, across sovereign frames', railStatus: 'LIVE' as const, href: '/docs/18' },
  { step: 'A fortnight anyone can replay', primitive: 'Immutable event ledger, replayable in order, forensically searchable', railStatus: 'LIVE' as const },
  { step: 'A link that is slow, or gone', primitive: 'Federation over a delay-tolerant link: the site’s ledger stored, forwarded and replayed on Earth on contact', railStatus: 'DESIGNED' as const },
]

export const cairn: Blueprint = {
  id: 'cairn',
  tier: 2,
  frontier: true,
  rank: 28,
  industry: 'Deep Space and Off-World Sites',
  systemName: 'CAIRN',
  promise: 'An uncrewed site that keeps working through two weeks without a link: every machine under a mandate signed before the silence, every unit of power paid for, and the whole fortnight replayable when contact returns.',
  cases: [
    { role: 'Off-world site operator', line: 'Machines that dig, mine and build through a solar conjunction, inside budgets signed before it.' },
    { role: 'Space agency or research consortium', line: 'Robotic precursors whose every decision replays on Earth, in order, when contact returns.' },
    { role: 'Robotics contractor', line: 'Paid per section on another machine’s signature, with a track record that travels to the next site.' },
    { role: 'Deep-sea and polar stations', line: 'The same grammar wherever a link is slow, rare or gone for months.' },
  ],
  problem:
    'Beyond the Moon, a question to Earth takes minutes to answer, and during a solar conjunction it takes two weeks. A robotic site cannot wait that long to decide who digs, who charges and who stops. It cannot be left to decide alone either, unless every decision carries the authority it was given, pays for what it uses, and leaves a record that Earth can replay.',
  system: [
    'CAIRN runs Site Corvus, an uncrewed construction site in Utopia Planitia on Mars that prepares a landing field and an ice mine for a crew due in four years. Two companies’ machines share one power plant: the mission’s own site-steward, power-steward, ice drill and tank meter, and an excavation contractor’s four excavators and two survey drones. Each company runs its own frame on site, with its own identities, its own ledger and its own supply invariant, and Earth runs a third, between three and twenty-two light-minutes away. Power and drill time are scarce, so agents pay for them in units from the budgets in their mandates, and the units are a budget for the site’s own work, not money.',
    'Elif Brandt, the mission director, signs once before the silence: a mandate of 6,000 units for the fortnight, a scope of named jobs, an expiry on day 18, and no single spend above 500 units without her device key. The site-steward cuts each job a permit from it, and a permit can only narrow what its issuer holds. Every agent version on site ran 400 hours against the site’s twin on Earth before it flew, and the eval agent signed the results she read before she signed anything. On day 1 the Sun passes between the planets and the link goes quiet for fourteen days. Nothing on site asks Earth for anything.',
    'Section 14 of the landing-field trench is posted at 80 units, escrowed at posting, and released on one thing only: the scan signed by survey-drone-2, the attesting party the contract names. On day 6 excavator-3’s lidar fouls with dust and it reports section 15 graded; the drone’s scan shows a ridge 30 centimetres high. The report is refused, because a worker never attests its own work, and the disagreement lands on excavator-3’s track record. When its trust falls below the site policy’s threshold, the frame restricts it and its jobs go back to the board, with nobody on Earth awake to ask. On day 15 the link returns, and Earth replays the fortnight from the ledger in order: every payment, every refusal, the restriction and why. The protocol never drives a motor; the machines’ own controllers do.',
  ],
  cast: [
    { agent: 'mission director (human)', role: 'Elif Brandt. Signs the fortnight’s mandate before the silence', ceiling: 'One mandate: 6,000 units, named jobs, an expiry on day 18. Any spend above 500 units waits for her device key.' },
    { agent: 'site-steward', role: 'Posts the work and cuts each job its permit', ceiling: 'Spends inside her mandate, re-derived on every request on the site’s frame. Cannot raise its own budget.' },
    { agent: 'power-steward', role: 'Sells the battery hours the plant can spare', ceiling: 'Sells spare hours only. Cannot sell the reserve that keeps the site warm through the night.' },
    { agent: 'excavator-1 to -4, ice-drill-1', role: 'Dig, grade and mine', ceiling: 'Paid per section on another machine’s signature. Never attest their own work.' },
    { agent: 'survey-drone-2, tank-meter-1', role: 'Sign the scans and readings that release payment', ceiling: 'Attest what they measure. Hold no budget and release nothing.' },
    { agent: 'forge-evals (Earth)', role: 'Runs every agent version against the site’s twin before it flies', ceiling: 'Signs eval results. Holds no authority on the site’s frame.' },
  ],
  loom: {
    nodes: [
      { id: 'md', label: 'Elif Brandt', sub: 'mission director', kind: 'human', x: 118, y: 110 },
      { id: 'evals', label: 'forge-evals', sub: 'tests every version', kind: 'agent', x: 336, y: 110 },
      { id: 'escrow', label: 'Section escrow', sub: 'held from posting', kind: 'teg', x: 560, y: 110 },
      { id: 'ledger', label: 'Site ledger', sub: 'replays on Earth', kind: 'ledger', x: 764, y: 110 },
      { id: 'steward', label: 'site-steward', sub: 'posts on a permit', kind: 'agent', x: 118, y: 330 },
      { id: 'mgate', label: 'Mandate gate', sub: 'budget, scope, expiry', kind: 'gate', x: 336, y: 330 },
      { id: 'sgate', label: 'Section contract', sub: 'names its surveyor', kind: 'gate', x: 560, y: 330 },
      { id: 'drone', label: 'survey-drone-2', sub: 'signs the scan', kind: 'agent', x: 764, y: 330 },
      { id: 'excavator', label: 'excavator-3', sub: 'its own report', kind: 'agent', x: 336, y: 450 },
    ],
    edges: [
      { id: 'e-post', from: 'steward', to: 'mgate', label: 'section 14' },
      { id: 'e-escrow', from: 'mgate', to: 'escrow', label: '80 units' },
      { id: 'e-scan', from: 'drone', to: 'sgate', label: 'signed' },
      { id: 'e-release', from: 'sgate', to: 'escrow' },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-evals', from: 'evals', to: 'md' },
      { id: 'e-key', from: 'md', to: 'mgate', label: 'key above 500' },
      { id: 'a-burst', from: 'steward', to: 'mgate', attackOnly: true, curve: 46, label: '300 postings' },
      { id: 'a-self', from: 'excavator', to: 'sgate', attackOnly: true, curve: 44, label: 'section 15, mine' },
    ],
    script: [
      { edge: 'e-post', state: 'active', dwellMs: 1500, caption: 'Day 1 of the silence. The site-steward posts section 14 of the landing-field trench: 40 metres, 80 units, inside its permit.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'A named job, inside the fortnight’s budget and before the expiry: the 80 units are escrowed at posting. Nothing is paid yet.' },
      { edge: 'e-scan', state: 'active', dwellMs: 1500, caption: 'Six hours later survey-drone-2 flies the section and signs its scan: 40.2 metres, graded to tolerance.' },
      { edge: 'e-release', state: 'active', dwellMs: 1400, caption: 'The contract names survey-drone-2 as its only attesting party. The signature is its own, so the escrow releases.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The contractor is paid exactly once, on the site’s own ledger. Earth reads it in order when the link returns.' },
      { edge: 'e-evals', state: 'active', dwellMs: 1500, caption: 'Before the silence, every agent version ran 400 hours against the site’s twin, and the eval agent signed the results she read.' },
      { edge: 'e-key', state: 'active', dwellMs: 1600, caption: 'Above 500 units nothing moves without her key, so during the silence such spends wait. Everything smaller runs on what she signed.' },
    ],
  },
  attacks: [
    {
      title: 'The excavator that vouches for itself',
      attack: 'On day 6 excavator-3’s lidar fouls with dust, and it signs a report that section 15 is graded to tolerance, to release the section’s escrow. The drone’s scan shows a ridge 30 centimetres high.',
      mechanism: 'The section contract names survey-drone-2, by its identity on the contractor’s frame, as the one party whose scan releases it. The report arrives over a valid channel and carries excavator-3’s own signature, and the channel proves only which machine sent it. A worker is never the party that attests its own work, so the contract checks the principal against the party it names before any release is considered.',
      rail: 'S13',
      consequence: 'The escrow does not move. Section 15 stays open until the drone scans it again, the refused report is recorded beside the scan that contradicts it, and when excavator-3’s trust falls below the site policy’s threshold, the frame restricts it until its record recovers or Earth lifts the restriction.',
      script: [
        { edge: 'a-self', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'sgate', caption: 'S13. The channel is valid and proves only the sender. The contract names survey-drone-2, and excavator-3 does not attest its own work.' },
      ],
    },
    {
      title: 'The runaway steward',
      attack: 'On day 9 a radiation upset corrupts the site-steward’s planner, and it posts 300 sections in an hour, each kept under the 500 units at which the mission director’s key is required.',
      mechanism: 'The steward never holds the site’s budget. It posts on a capability permit cut from the mandate, whose caveats carry the named jobs, the expiry and the fortnight’s budget, debited atomically with each posting. Every posting is checked against those caveats and the issuer’s authority as it stands now, before any escrow is touched. Her key does not stop this burst, because each posting stays under her threshold; the permit does, because its budget travels with the permit and not with the planner’s state.',
      rail: 'S03',
      consequence: 'The burst commits no more than what is left of the fortnight’s budget, every unit escrowed against a named job and released only on a signed scan. Everything past the budget is refused before a unit moves, and Earth reads each refusal in order when the link returns.',
      script: [
        { edge: 'a-burst', state: 'denied', dwellMs: 1900, stopAt: 0.8, flashNode: 'mgate', caption: 'S03. Each posting debits the permit’s budget for the fortnight, atomically. Past it, the burst is refused before a unit moves.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' },
    { label: 'Incident Response (the P1 clock)', href: '/compliance/doc/incident-response-procedures' },
    { label: 'Jurisdiction profiles', href: '/compliance/doc/jurisdiction-profiles' },
  ],
  rails: ['S01', 'S03', 'S05', 'S06', 'S07', 'S13', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A frame for the mission and one for each contractor on the site’s own computers, and one at mission control on Earth, each booted from the free licence and pre-built images. Nothing to write.',
    agents: 'One agent per machine, a steward for the work and one for power, an eval agent on Earth. Motion control, autonomy and science stay the vendors’ and the mission’s; the SDK carries identity, payment and attestation.',
    integration: 'The machines’ controllers, the twin and the link. This is where the real time goes, and it stays with the teams that build those systems.',
  },
  nonClaims: [
    'CAIRN does not drive machines, plan trajectories or run autonomy. It carries identity, authority, payment and evidence for the systems that do.',
    'The units on the site are a budget for its own work and its scarce power, not money.',
    'Federation over a delay-tolerant link is designed, not built: today two frames catch up when a link is up.',
    'Launch, planetary protection and space-object registration stay with the agencies and operators that hold them. No conformity with any national space law or international space treaty is claimed or implied.',
  ],
  mermaid: `flowchart LR
  MD(["Elif Brandt<br/>mission director"]) -->|"key above 500"| G{"mandate gate<br/>budget, scope, expiry"}
  S["site-steward"] -->|"section 14"| G
  G -->|"80 units, escrowed"| E["section escrow"]
  D["survey-drone-2<br/>contractor frame"] -->|"scan, signed"| C{"section contract<br/>names its surveyor"}
  C -->|"release, once"| E
  E --> L[("site ledger<br/>replays on Earth")]
  X["excavator-3"] -.->|"its own report: refused"| C`,
  legacy: [
    { system: 'Machine controllers and autonomy stacks', connect: 'Motion, navigation and safety stay where they run. An agent stands beside each controller and carries its identity, its permit and its signed reports.' },
    { system: 'The digital twin', connect: 'Every agent version runs against the twin before it flies; the eval results travel with the version as a signed record.' },
    { system: 'The link and its schedule', connect: 'The ledger catches up when the link is up, in order. Nothing on the site waits for it.' },
    { system: 'Mission planning on Earth', connect: 'Planners read the replayed fortnight instead of reconstructing it from telemetry, and write the next mandate before the next silence.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
