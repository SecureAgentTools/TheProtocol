import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// COLLEGIUM: research allocation networks (V0660 (f)). A frontier chamber on the live rails. What is
// quantum here is the workload; what carries it is the allocation, authority, money and evidence
// machinery that already runs. Every figure in this chamber is one the code supports: the allocation
// profile, its caps held before the treasury is called, and the grant memo on the ledger.

const primitives = [
  { step: 'A named allocation behind every grant', primitive: 'Allocation profile declared by the centre’s frame: id, holder, cap', railStatus: 'LIVE (gated)' as const },
  { step: 'The cap is checked before any unit moves', primitive: 'Allocation hold ahead of the treasury call; a grant past the cap is refused', railStatus: 'LIVE (gated)' as const },
  { step: 'The room left can only shrink', primitive: 'Each grant counted against its allocation; the count never reopens', railStatus: 'LIVE (gated)' as const },
  { step: 'A project agent starts able to do nothing', primitive: 'IRONKEY deny-by-default: two permissions until a role is granted', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'The planner spends the project’s purse, not its own', primitive: 'Anchored spawn: a sub-agent with no wallet, checked against the mandate as it stands', railStatus: 'LIVE' as const },
  { step: 'Any holder of the profile can audit a cap', primitive: 'Grant memo on the immutable ledger, one line per allocation', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'Granted exactly once, whatever retries', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'Shots reported match a committed meter log', primitive: 'accurateResourceUsagePolicy/v2.0.0, a published circuit with its verification key', railStatus: 'LIVE' as const, href: '/docs/10' },
  { step: 'Each backend states its own facts', primitive: 'Quantum workload card extension: qubits, gates, limits, queue, each with its as_of', railStatus: 'LIVE (gated)' as const },
  { step: 'Centres in different units', primitive: 'Cross-registry transfer between sovereign frames', railStatus: 'LIVE' as const },
  { step: 'Time on a real QPU, inside the allocation', primitive: 'A provider’s own hardware run, booked and attested like any other service', railStatus: 'DESIGNED' as const },
]

export const collegium: Blueprint = {
  id: 'collegium',
  tier: 2,
  frontier: true,
  rank: 29,
  industry: 'Research Allocation Networks',
  systemName: 'COLLEGIUM',
  promise: 'Centres grant compute time by proposal, in their own unit, and a project agent spends it to a declared cap that no retry, replay or busy night can widen.',
  cases: [
    { role: 'Computing centre director', line: 'Allocations granted by proposal and spent to the cap you declared, with nobody in the loop at 3am.' },
    { role: 'Principal investigator', line: 'One mandate for the project, and a planner that cannot spend past it.' },
    { role: 'Consortium administrator', line: 'Member centres in their own units, one record of who was granted what.' },
    { role: 'Research funder', line: 'Fund a project at a partner centre and audit the caps from the ledger, not from a report.' },
  ],
  problem:
    'Allocation is the oldest unsolved administrative problem in shared scientific computing. A committee grants a project 200,000 core hours or 5,000 units of quantum time, and from that moment the cap lives in a spreadsheet, a quota file and somebody’s memory. The project’s own software cannot read it, so a planner that runs overnight either stops short of the grant or sails past it, and the centre finds out at the end of the quarter.',
  system: [
    'COLLEGIUM is a quantum computing consortium: a centre in Jülich with two simulator backends and a hardware partner, a university group in Delft, and a funder that underwrites both. The centre’s frame declares its allocations as a signed document: proj-017 holds 5,000 units, granted to one named project agent, in the centre’s own unit. The document is published by hash, so a member can check that the profile they were shown is the profile the frame is running, and the holders and the caps themselves stay inside the frame.',
    'Dr Lena Fischer runs proj-017. She underwrites the project once with a mandate for the quarter and funds its purse from the allocation. Her planner is the project’s own sub-agent: it holds no wallet, it spends the project’s purse, and every request it makes is checked against her mandate as it stands at that moment. At 03:40 the planner closes a round, proposes the next forty circuits and asks for 1,200 units. The allocation has 900 left. The request is refused before the treasury is called, the refusal names the cap it crossed, and the planner takes the smaller batch instead of overdrawing a grant nobody was awake to defend.',
    'What the backends report is checked rather than believed. Each one states its own facts on its card, with the date each fact was read: qubits, native gates, shot limits, queue. Each job’s shots are metered as the work runs and committed then, so a report that does not match the committed log cannot be proven, and the proof is of a published circuit whose verification key anyone can fetch. A run on a real device is booked and attested the same way; that part is specified and not yet built, and the chamber says so.',
  ],
  cast: [
    { agent: 'proj-017-planner', role: 'Proposes each round, books the runs', ceiling: 'The project’s sub-agent, with no wallet of its own. Every request is checked against Dr Fischer’s mandate as it stands, and against the allocation’s remaining room.' },
    { agent: 'centre-desk', role: 'Grants from the allocation', ceiling: 'Grants only to the holder the profile names, only under the declared cap. Cannot create an allocation.' },
    { agent: 'sim-JUW-2', role: 'Runs the circuits, signs each job', ceiling: 'Attests its own jobs and meters its own shots. Holds no budget and releases nothing.' },
    { agent: 'proof-desk', role: 'Checks a reported shot count against its committed log', ceiling: 'Verifies proofs of a published circuit. Cannot grant, book or pay.' },
  ],
  loom: {
    nodes: [
      { id: 'committee', label: 'Prof. Haas', sub: 'chairs the panel', kind: 'human', x: 118, y: 110 },
      { id: 'planner', label: 'proj-017-planner', sub: 'proposes the next 40', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Allocation gate', sub: 'holder, cap, room', kind: 'gate', x: 336, y: 220 },
      { id: 'purse', label: 'Project purse', sub: 'funded under the cap', kind: 'teg', x: 560, y: 110 },
      { id: 'backend', label: 'sim-JUW-2', sub: 'signs each job', kind: 'agent', x: 560, y: 330 },
      { id: 'meter', label: 'Shot meter', sub: 'committed at run', kind: 'agent', x: 336, y: 450 },
      { id: 'ledger', label: 'Grant ledger', sub: 'one line per grant', kind: 'ledger', x: 764, y: 110 },
      { id: 'proof', label: 'proof-desk', sub: 'checks the shot count', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-grant', from: 'committee', to: 'gate', label: 'allocation, signed' },
      { id: 'e-ask', from: 'planner', to: 'gate', label: '1,200 units', labelT: 0.3 },
      { id: 'e-fund', from: 'gate', to: 'purse', label: 'under the cap' },
      { id: 'e-meter', from: 'gate', to: 'meter', label: 'shots metered' },
      { id: 'e-run', from: 'backend', to: 'purse', label: 'job, signed', labelT: 0.62 },
      { id: 'e-emit', from: 'purse', to: 'ledger' },
      { id: 'e-proof', from: 'proof', to: 'ledger', label: 'proof checked' },
      { id: 'a-overcap', from: 'planner', to: 'gate', attackOnly: true, curve: 70, labelT: 0.5, label: 'past the cap' },
      { id: 'a-replay', from: 'backend', to: 'purse', attackOnly: true, curve: 90, labelT: 0.3, label: 'same job, again' },
    ],
    script: [
      { edge: 'e-grant', state: 'active', dwellMs: 1500, caption: 'Prof. Haas’s panel grants proj-017 five thousand units, to one named holder, in the centre’s own unit.' },
      { edge: 'e-ask', state: 'active', dwellMs: 1400, caption: 'At 03:40 the planner closes a round and asks for the next batch.' },
      { edge: 'e-fund', state: 'active', dwellMs: 1400, caption: 'Inside the cap, the project purse is funded and the room left is counted down.' },
      { edge: 'e-meter', state: 'active', dwellMs: 1300, caption: 'The meter commits to the shots as the work runs, not when the invoice is written.' },
      { edge: 'e-run', state: 'active', dwellMs: 1500, caption: 'The backend signs each job: the circuit’s digest, the shots, the device that ran it.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'The grant lands on the ledger with its allocation named, so any holder of the profile can audit the cap.' },
      { edge: 'e-proof', state: 'active', dwellMs: 1500, caption: 'A reported shot count is proven against the committed log, on a published circuit.' },
    ],
  },
  attacks: [
    {
      title: 'The overnight overdraw',
      attack: 'The planner, working through the night with nobody watching, asks for 1,200 units against an allocation with 900 left.',
      mechanism: 'The allocation hold runs before the treasury is called: the grant’s reason names its allocation, the frame checks the holder and the room left against the declared profile, and refuses. The amount already granted under that allocation is counted and never reopened, so the room can shrink and cannot grow.',
      rail: 'S16',
      consequence: 'No grant, no treasury movement, nothing to claw back. The refusal names the cap it crossed.',
      script: [
        { edge: 'a-overcap', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S16. The cap is checked in front of the money, so a refusal needs no unwind.' },
      ],
    },
    {
      title: 'The job paid twice',
      attack: 'A crashed driver re-sends a finished job’s attestation, and a second copy arrives asking to be paid.',
      mechanism: 'A job is its own milestone, and a milestone releases once. The payout carries a key made from the booking and the milestone, and the shot meter keeps one entry per job id: a second report of the same job finds the entry already committed and nothing left to release.',
      rail: 'S15',
      consequence: 'The centre is paid once for one job. The duplicate is visible, not profitable.',
      script: [
        { edge: 'a-replay', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'purse', caption: 'S15. This job’s key was already paid. A retry, a crash or a replay moves the money exactly once.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [{ label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' }],
  rails: ['S01', 'S02', 'S05', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'A consortium frame, or each centre on a frame of its own, federated, booted from the free licence and pre-built images. Quantum workloads are one frame switch, off by default.',
    agents: 'A desk per centre, a planner per project, one agent per backend. The science is the group’s own; the SDK carries identity, allocation, payment and attestation.',
    integration: 'The scheduler, the proposal system and the existing quota files. This is where the real time goes, and it stays the centre’s.',
  },
  nonClaims: [
    'COLLEGIUM carries allocation, authority, money and evidence for computing time. It does not schedule jobs, compile circuits, or judge whether a proposal deserves its grant.',
    'Peer review, export control and every institutional approval stay with the committees and offices that hold them today. A cap narrows what an agent may spend; it does not review a proposal.',
    'The quantum backends in this chamber are simulators. A run on real hardware is specified and marked DESIGNED. Nothing here measures the worth of such a run, and this chamber makes no claim about it.',
    'The shot proof binds a reported figure to a log the provider committed to. It does not show the figure is true, and the provider runs its own prover.',
  ],
  mermaid: `flowchart LR
  C(["allocation committee"]) -->|"grant, signed"| G{"allocation gate<br/>holder, cap,<br/>room left"}
  P["proj-017-planner"] -->|"next batch"| G
  G -->|"under the cap"| E["project purse"]
  G -->|"shots metered"| M["shot meter"]
  B["sim-JUW-2"] -->|"job, signed"| E
  E --> L[("grant ledger<br/>one line per allocation")]
  V["proof-desk"] -->|"proof checked"| L`,
  legacy: [
    { system: 'Batch schedulers and quota files', connect: 'The allocation becomes the cap the rails hold. The scheduler still owns the queue.' },
    { system: 'Proposal and review systems', connect: 'An approved proposal becomes a declared allocation with a named holder. The committee keeps the decision.' },
    { system: 'Recharge and finance systems', connect: 'Grants settle on the rails under the cap; finance reads settlement instead of reconciling quarterly.' },
    { system: 'Quantum SDKs and cloud consoles', connect: 'A backend joins as an agent with its own card. The circuits and the compiler stay the group’s.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
