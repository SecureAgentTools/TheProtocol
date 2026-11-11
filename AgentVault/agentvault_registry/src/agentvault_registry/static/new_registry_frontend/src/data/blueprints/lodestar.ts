import type { Blueprint } from './types'
import { liveRatioOf } from './types'

// LODESTAR: optimisation (V0660 (f)). The honest centre of this chamber is that the ANSWER IS CHECKABLE
// WITHOUT TRUSTING THE METHOD. A route or a schedule is scored by the buyer's own objective function, so
// the sale rests on a number the buyer computes, and no claim about the hardware is needed anywhere.

const primitives = [
  { step: 'The objective is the buyer’s, and it scores the answer', primitive: 'Acceptance template rung 1: the answer is checked, not the method', railStatus: 'LIVE' as const },
  { step: 'The incumbent’s score is the bar, set before the run', primitive: 'The order carries the score to beat and the tolerance', railStatus: 'LIVE' as const },
  { step: 'Escrow opens on the score', primitive: 'Contract spine: escrow at order, released per attested milestone', railStatus: 'LIVE' as const },
  { step: 'Each answer carries what produced it', primitive: 'Receipt chain: problem digest, backend, shots, the answer itself', railStatus: 'LIVE' as const },
  { step: 'Several sellers answer the same problem', primitive: 'Guild work orders: bids, award, verify, paid on the agreed test', railStatus: 'LIVE' as const },
  { step: 'Shots reported match a committed meter log', primitive: 'accurateResourceUsagePolicy/v2.0.0, a published circuit with its verification key', railStatus: 'LIVE' as const, href: '/docs/10' },
  { step: 'The ledger keeps hashes, never the problem', primitive: 'Immutable ledger of digests and scores; the network stays the buyer’s', railStatus: 'LIVE' as const, href: 'https://auditor.theprotocol.cloud' },
  { step: 'A named planner behind every spend', primitive: 'Cockpit Card mandate, scope-clamped, re-derived per request', railStatus: 'LIVE (gated)' as const, href: '/docs/30' },
  { step: 'Each backend states its own facts', primitive: 'Quantum workload card extension: qubits, gates, limits, queue, each with its as_of', railStatus: 'LIVE (gated)' as const },
  { step: 'A disputed score, ruled on', primitive: 'Four-phase dispute; the ruling drives the escrow split', railStatus: 'LIVE' as const },
  { step: 'The anneal run on real hardware', primitive: 'A provider’s own device, booked and attested like any other service', railStatus: 'DESIGNED' as const },
]

export const lodestar: Blueprint = {
  id: 'lodestar',
  tier: 2,
  frontier: true,
  rank: 31,
  industry: 'Optimisation and Scheduling',
  systemName: 'LODESTAR',
  promise: 'A schedule is bought on the score your own objective gives it, against the bar your incumbent set, so the method never has to be taken on trust.',
  cases: [
    { role: 'Logistics planner', line: 'Buy a better round of routes on the score your own model gives them.' },
    { role: 'Grid or fleet scheduler', line: 'Put tonight’s problem to several sellers and pay the one that beats your bar.' },
    { role: 'Optimisation vendor', line: 'Sell answers on a score the buyer computes, not on a benchmark you publish.' },
    { role: 'Operations research team', line: 'Your incumbent stays the bar, and every answer is scored against it.' },
  ],
  problem:
    'Optimisation is sold on benchmarks that nobody can reproduce. A vendor reports a result on an instance of its choosing, the buyer cannot tell whether the same method helps their own problem, and the invoice does not depend on the answer being any good. The buyer already owns the only measure that matters, their own objective function, and it plays no part in the purchase.',
  system: [
    'LODESTAR is a scheduling market: a distribution operator in Lyon with 240 vehicles and a nightly routing problem, and four sellers on their own frames, two with simulator backends and one with an annealer partner. The operator posts tonight’s problem as a work order with its own objective attached, the score its incumbent reached, and a tolerance. Sellers bid, two are awarded, and each returns a candidate schedule with its receipt: the problem’s digest, the backend, the shots, the answer.',
    'Ravi Menon runs the night desk. He underwrites the desk once with a mandate for the month, and the dispatch agent that posts the orders holds no wallet of its own. When the answers arrive, the scoring desk runs the operator’s objective over each one and publishes the number. One seller beats the bar by four per cent and is paid; the other lands below it and is not. Neither outcome needs anyone to agree about what the hardware did, because the score is computed by the buyer from the answer itself.',
    'What the ledger keeps is the problem’s digest, the score and the verdict. The network, the demands and the costs stay the operator’s own. A seller’s shots are proven against a log committed as the work ran, on a circuit anyone can verify, and a seller with no prover reports its shots unproven and says so. A run on a real annealer is booked and attested the same way; that part is specified and not yet built, and the chamber marks it so.',
  ],
  cast: [
    { agent: 'dispatch-agent', role: 'Posts the nightly order, reads the scores', ceiling: 'The desk’s sub-agent, with no wallet of its own. Every order is checked against Mr Menon’s mandate as it stands.' },
    { agent: 'solver-SIN-4', role: 'Returns a candidate schedule with its receipt', ceiling: 'Attests its own runs. Cannot score its own answer or release its own escrow.' },
    { agent: 'scoring-desk', role: 'Runs the operator’s objective, publishes the score', ceiling: 'Computes the buyer’s own measure. Holds no budget and cannot order.' },
    { agent: 'decode-assistant', role: 'Decodes syndromes for a hardware seller, in batches', ceiling: 'A classical service beside the device: syndromes in, corrections out. Books nothing and signs no schedule.' },
  ],
  loom: {
    nodes: [
      { id: 'planner', label: 'Ravi Menon', sub: 'the mandate, one tap', kind: 'human', x: 118, y: 110 },
      { id: 'dispatch', label: 'dispatch-agent', sub: 'posts tonight’s order', kind: 'agent', x: 118, y: 330 },
      { id: 'gate', label: 'Scoring gate', sub: 'your objective, first', kind: 'gate', x: 336, y: 220 },
      { id: 'escrow', label: 'Run escrow', sub: 'opens on the score', kind: 'teg', x: 560, y: 110 },
      { id: 'seller', label: 'solver-SIN-4', sub: 'signs each answer', kind: 'agent', x: 560, y: 330 },
      { id: 'incumbent', label: 'incumbent solver', sub: 'the bar to beat', kind: 'external', x: 336, y: 450 },
      { id: 'ledger', label: 'Score ledger', sub: 'digests and scores', kind: 'ledger', x: 764, y: 110 },
      { id: 'desk', label: 'scoring-desk', sub: 'runs your objective', kind: 'agent', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-mandate', from: 'planner', to: 'gate', label: 'scope, signed' },
      { id: 'e-post', from: 'dispatch', to: 'gate', label: 'tonight’s problem', labelT: 0.3 },
      { id: 'e-escrow', from: 'gate', to: 'escrow', label: 'escrowed per bid' },
      { id: 'e-bar', from: 'gate', to: 'incumbent', label: 'the score to beat' },
      { id: 'e-answer', from: 'seller', to: 'escrow', label: 'answer', labelT: 0.62 },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-score', from: 'desk', to: 'ledger', label: 'score, published' },
      { id: 'a-nobar', from: 'dispatch', to: 'gate', attackOnly: true, curve: 70, labelT: 0.5, label: 'no bar set' },
      { id: 'a-below', from: 'seller', to: 'escrow', attackOnly: true, curve: 90, labelT: 0.3, label: 'below the bar' },
    ],
    script: [
      { edge: 'e-mandate', state: 'active', dwellMs: 1500, caption: 'Mr Menon underwrites the night desk once: a budget, a scope, a month.' },
      { edge: 'e-post', state: 'active', dwellMs: 1400, caption: 'The dispatch agent posts tonight’s problem with the operator’s own objective attached.' },
      { edge: 'e-escrow', state: 'active', dwellMs: 1400, caption: 'Each awarded bid is escrowed. Nothing opens on an answer arriving.' },
      { edge: 'e-bar', state: 'active', dwellMs: 1300, caption: 'The incumbent’s score goes into the order as the bar, with its tolerance.' },
      { edge: 'e-answer', state: 'active', dwellMs: 1500, caption: 'A seller signs its candidate: the problem’s digest, the backend, the shots, the answer.' },
      { edge: 'e-emit', state: 'settled', dwellMs: 1400, caption: 'A passing answer releases its payment exactly once and lands as a digest and a score.' },
      { edge: 'e-score', state: 'active', dwellMs: 1500, caption: 'The scoring desk runs the operator’s objective and publishes the number either way.' },
    ],
  },
  attacks: [
    {
      title: 'The order with no bar',
      attack: 'A seller asks for the order to be posted without the incumbent’s score, so any answer counts as an improvement.',
      mechanism: 'The acceptance template is part of the order and the gate sits in front of the escrow: an order whose template names no score and no tolerance is refused at posting. The bar is set by the buyer, before bids are read.',
      rail: 'S16',
      consequence: 'No order, no escrow, nothing to unwind. The refusal names the missing bar.',
      script: [
        { edge: 'a-nobar', state: 'denied', dwellMs: 1900, stopAt: 0.82, flashNode: 'gate', caption: 'S16. An order with no score to beat is refused before any value is committed.' },
      ],
    },
    {
      title: 'The answer that scores worse',
      attack: 'A seller returns a schedule that is below the bar and asks to be paid for the compute it spent.',
      mechanism: 'The escrow opens on the verdict of the agreed test, and the test is the buyer’s own objective run over the returned answer. The scoring desk publishes the number, the milestone stays unreleased, and the dispute phase begins with the digest, the answer and the score already recorded.',
      rail: 'S12',
      consequence: 'The compute is the seller’s cost, not the buyer’s. The score is in the record either way.',
      script: [
        { edge: 'a-below', state: 'denied', dwellMs: 1900, stopAt: 0.74, flashNode: 'escrow', caption: 'S12. Only the frame holding the escrow releases it, and it releases on the score.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [{ label: 'Risk Assessment Framework', href: '/compliance/doc/risk-assessment-framework' }],
  rails: ['S01', 'S05', 'S12', 'S14', 'S15', 'S16', 'S19'],
  standup: {
    infra: 'An operator frame, or each seller on a frame of its own, federated, booted from the free licence and pre-built images. Quantum workloads are one frame switch, off by default.',
    agents: 'A dispatch agent, a scoring desk, one agent per seller backend. The objective function is the operator’s own and never leaves its frame.',
    integration: 'The planning system, the incumbent solver and the demand data. This is where the real time goes, and it stays the operator’s.',
  },
  nonClaims: [
    'LODESTAR carries identity, authority, money and evidence for optimisation work. It does not solve, schedule, or judge whether an objective function is the right one.',
    'A score says one answer beat another answer on the buyer’s own measure, on one problem, on one night. It says nothing about any other problem and nothing about the method that produced it.',
    'The backends in this chamber are simulators. A run on real hardware is specified and marked DESIGNED. Nothing here measures what such a run produces, and this chamber makes no claim about it.',
    'The decoding assistant is a classical service beside a device. It runs in batches on the provider’s own hardware, never as a live loop inside an error-correction cycle, which has to sit next to the device in microseconds.',
  ],
  mermaid: `flowchart LR
  R(["Ravi Menon<br/>mandate"]) -->|"scope"| G{"scoring gate<br/>your objective, first"}
  D["dispatch-agent"] -->|"tonight’s problem"| G
  G -->|"escrowed per bid"| E["run escrow"]
  G -->|"score to beat"| I["incumbent solver"]
  S["solver-SIN-4"] -->|"answer, signed"| E
  E --> L[("score ledger<br/>digests and scores")]
  K["scoring-desk"] -->|"score"| L`,
  legacy: [
    { system: 'Planning and dispatch systems', connect: 'An order carries the problem’s digest and the plan’s references. The planner still owns the night.' },
    { system: 'The incumbent solver', connect: 'It runs as it does today and its score becomes the bar in the order.' },
    { system: 'Fleet telematics and demand feeds', connect: 'They stay where they are; what travels is a digest, never the network.' },
    { system: 'Procurement', connect: 'Orders settle on the rails under the mandate; finance reads settlement instead of benchmark claims.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
