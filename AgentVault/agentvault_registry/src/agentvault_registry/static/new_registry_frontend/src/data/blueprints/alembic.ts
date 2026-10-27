import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// ALEMBIC: self-driving wet labs (§BPFRONTIER 2026-09-25, his words "i want wetlebs use case in too and such
// cool cases. future cases."). A frontier chamber: the sector is arriving now; the rails are the live ones.

const primitives = [
  { step: 'A named scientist behind every spend', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Budgets, suppliers and instruments as bounds', primitive: 'IRONKEY L4 capability caveats: counterparty allowlist, atomic budget debit', railStatus: 'LIVE' as const, href: '/docs/24' },
  { step: 'Robot time booked and paid per run', primitive: 'Contract spine: escrow at booking, released per attested run', railStatus: 'LIVE' as const },
  { step: 'Each instrument its own identity', primitive: 'SPIFFE identity per instrument agent, short-lived certificates', railStatus: 'LIVE' as const, href: '/docs/08' },
  { step: 'Runs that sign themselves', primitive: 'Signed attestations from identified parties, append-only', railStatus: 'LIVE' as const },
  { step: 'Paid exactly once, whatever retries', primitive: 'Idempotency keys, two-layer dedup (cache + ledger unique)', railStatus: 'LIVE' as const },
  { step: 'Labs in different currencies', primitive: 'Cross-registry transfer and FX pools across sovereign frames', railStatus: 'LIVE' as const },
  { step: 'A campaign anyone can replay', primitive: 'Immutable event ledger; a run is replayable evidence', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'A failed run, contested', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
]

export const alembic: Blueprint = {
  id: 'alembic',
  tier: 2,
  frontier: true,
  rank: 22,
  industry: 'Self-Driving Labs and Wet-Lab Automation',
  systemName: 'ALEMBIC',
  promise: 'Self-driving labs that book another lab’s robots, order reagents inside a named scientist’s mandate, and pay per run on the instrument’s own signature.',
  cases: [
    { role: 'Self-driving lab team', line: 'Closed-loop campaigns with a named PI behind every unit spent.' },
    { role: 'Cloud lab operator', line: 'Robot time sold per run and paid on the instrument’s own signature.' },
    { role: 'University core facility', line: 'Bookings, recharges and provenance in one record instead of three.' },
    { role: 'Materials or biotech sponsor', line: 'Fund a campaign at a partner lab without handing over the keys.' },
  ],
  problem:
    'Autonomous experimentation has outgrown its paperwork. A planning model proposes a hundred experiments overnight, but booking another lab’s robots, ordering reagents and paying per run still wait for a person with a purchase card, and when a result is questioned nobody can show which instrument ran it, from which reagent lot, under whose authority.',
  system: [
    'ALEMBIC is a self-driving laboratory network for battery materials: a campaign planner in Singapore, a robotic liquid-handling lab in Leuven and a cell-cycling lab in Basel, each on its own frame. At 02:10 on a Tuesday, campaign 17 closes its eleventh round. The planner reads the capacity fade of the last 24 cells, proposes the next 24 electrolyte formulations and books four hours of the Leuven handler at 60 units a run. Each run is escrowed at booking and released on one thing only: the handler’s own signed attestation of what it mixed, from which reagent lot, under which protocol version.',
    'Dr Amara Okafor, the principal investigator, never touches a purchase card. She funds campaign 17’s purse with 12,000 units and underwrites it with one mandate for ninety days, confirmed on her phone. The planner is the campaign’s own sub-agent: it holds no wallet, spends the campaign’s purse, and every run it books is checked against her mandate as it stands at that moment. The procurement desk orders on a capability permit cut from the campaign’s authority, naming three approved suppliers, and a permit can only narrow what its issuer holds. When the planner, working from a mislabelled paper, has the desk reach for a precursor from a supplier outside the list, the order is refused before a unit moves, and the refusal is recorded for her to read in the morning.',
    'The results land where they cannot be edited. A negative round is as durable as a positive one, every data point traces back to an instrument identity and a paid run, and a reviewer can replay the campaign from its references. A result that no instrument signed never reaches the ledger, and a run that never happened cannot be paid.',
  ],
  cast: [
    { agent: 'campaign-planner', role: 'Proposes each round, books the runs', ceiling: 'The campaign’s sub-agent, with no wallet of its own. Every booking is checked against Dr Okafor’s mandate as it stands, so revoking it stops the next one.' },
    { agent: 'procurement-desk', role: 'Orders reagents', ceiling: 'A permit cut from the campaign’s authority: three suppliers, a budget, ninety days. Cannot widen any of them.' },
    { agent: 'handler-LEU-3', role: 'Runs the formulations, signs each run', ceiling: 'Attests its own runs. Holds no budget and releases nothing.' },
    { agent: 'cycler-BAS-7', role: 'Cycles the cells, signs the results', ceiling: 'Attests results for runs it received. Cannot book, order or pay.' },
  ],
  loom: {
    nodes: [
      { id: 'pi', label: 'Dr Okafor', sub: 'the mandate, one tap', kind: 'human', x: 118, y: 110 },
      { id: 'planner', label: 'campaign-planner', sub: 'proposes the next 24', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Campaign gate', sub: 'budget, suppliers, instruments', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Run escrow', sub: 'paid per signed run', kind: 'teg', x: 560, y: 110 },
      { id: 'handler', label: 'handler-LEU-3', sub: 'signs each run', kind: 'agent', x: 560, y: 330 },
      { id: 'supplier', label: 'approved suppliers', sub: 'three, allowlisted', kind: 'external', x: 336, y: 450 },
      { id: 'ledger', label: 'Result ledger', sub: 'each run, replayable', kind: 'ledger', x: 764, y: 110 },
      { id: 'cycler', label: 'cycler-BAS-7', sub: 'signs the results', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-mandate', from: 'pi', to: 'gate', label: 'scope, signed' },
      { id: 'e-propose', from: 'planner', to: 'gate', label: '24 formulations', labelT: 0.3 },
      { id: 'e-book', from: 'gate', to: 'escrow', label: 'robot time' },
      { id: 'e-order', from: 'gate', to: 'supplier', label: 'reagents' },
      { id: 'e-run', from: 'handler', to: 'escrow', label: 'run, signed', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-cycle', from: 'cycler', to: 'ledger', label: 'results, signed' },
      { id: 'a-offlist', from: 'planner', to: 'gate', attackOnly: true, curve: 70, labelT: 0.5, label: 'off-list order' },
      { id: 'a-replay', from: 'handler', to: 'escrow', attackOnly: true, curve: 90, labelT: 0.3, label: 'same run, again' },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Dr Okafor underwrites campaign 17 once: a budget, three suppliers, two instruments, ninety days.' },
      { edge: 'e-propose', state: 'active', dwellMs: 1400, caption: 'The planner reads the last round and proposes the next 24 formulations.' },
      { edge: 'e-book', state: 'active', dwellMs: 1400, caption: 'Inside the mandate, robot time in Leuven is booked and escrowed run by run.' },
      { edge: 'e-order', state: 'active', dwellMs: 1300, caption: 'Reagents go only to the suppliers on the list. Their own screening still applies.' },
      { edge: 'e-run', state: 'active', dwellMs: 1500, caption: 'The handler signs each run: what it mixed, from which lot, under which protocol version.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'Each signed run releases its payment exactly once and lands on the ledger with its provenance.' },
      { edge: 'e-cycle', state: 'active', dwellMs: 1500, caption: 'In Basel the cycler signs the cells’ results. A result no instrument signed never reaches the ledger.' },
    ],
  },
  attacks: [
    {
      title: 'The mislabelled precursor',
      attack: 'Working from a mislabelled paper, the planner has the procurement desk order a precursor from a supplier that is not on the campaign’s list.',
      mechanism: 'The procurement desk acts on a capability permit cut from the campaign’s authority, and its caveats name the three suppliers. The payment is checked against those caveats and against the issuer’s authority as it stands now, before any escrow is touched. A permit can narrow what its issuer holds; it cannot add a counterparty.',
      rail: 'S03',
      consequence: 'No order, no escrow movement, nothing to unwind. The refusal is recorded, waiting for the PI.',
      script: [
        { edge: 'a-offlist', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S03. The permit names its suppliers. An order to anyone else is refused before a unit moves.' },
      ],
    },
    {
      title: 'The run paid twice',
      attack: 'A faulty driver on the handler retries its attestation after a crash, and a second copy of the same run arrives asking to be paid.',
      mechanism: 'Each run is its own milestone on the booking, and a milestone releases once: the first signed report claims it, and its payout carries a key made from the booking and the milestone. The copy of the same run finds nothing left to release, and a retried release replays under the same key and moves nothing.',
      rail: 'S15',
      consequence: 'The lab is paid once for one run. The duplicate is visible, not profitable.',
      script: [
        { edge: 'a-replay', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'escrow', caption: 'S15. This run’s key was already paid. A retry, a crash or a replay moves the money exactly once.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'AI System Lifecycle', href: '/compliance/doc/ai-system-lifecycle' },
    { label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' },
  ],
  rails: ['S01', 'S03', 'S05', 'S06', 'S07', 'S14', 'S15', 'S16'],
  standup: {
    infra: 'A consortium frame, or each lab on a frame of its own, federated, booted from the free licence and pre-built images.',
    agents: 'Planner, procurement desk and one agent per instrument. The campaign logic is the lab’s own; the SDK carries identity, payment and attestation.',
    integration: 'Instrument drivers, the LIMS and the purchasing system. This is where the real time goes, and it stays the lab’s.',
  },
  nonClaims: [
    'ALEMBIC carries identity, authority, money and evidence for lab work. It does not run instruments, write protocols, or judge whether an experiment is safe, sound or worth doing.',
    'Supplier screening, biosafety review and every regulatory approval stay with the suppliers and institutions that own them today. A caveat narrows what an agent may order; it does not replace a safety committee.',
    'No claim of GLP, GMP or ISO/IEC 17025 conformity is made or implied.',
  ],
  mermaid: `flowchart LR
  PI(["Dr Okafor<br/>mandate"]) -->|"scope"| G{"campaign gate<br/>budget, suppliers,<br/>instruments"}
  P["campaign-planner"] -->|"next 24"| G
  G -->|"robot time, escrowed"| E["run escrow"]
  G -->|"reagents, allowlisted"| S["approved suppliers"]
  H["handler-LEU-3"] -->|"run, signed"| E
  E --> L[("result ledger<br/>provenance")]
  C["cycler-BAS-7"] -->|"results, signed"| L`,
  legacy: [
    { system: 'LIMS and electronic lab notebooks', connect: 'Run attestations carry the LIMS sample and protocol references. The notebook stays the scientist’s working view.' },
    { system: 'Instrument schedulers', connect: 'A booking becomes an escrowed contract. The scheduler still owns the calendar.' },
    { system: 'Purchasing and recharge systems', connect: 'Orders settle on the rails inside the mandate; finance reads settlement instead of chasing receipts.' },
    { system: 'Biosafety and ethics committees', connect: 'Their approvals become the scope a mandate may cover. The committee keeps the decision.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
