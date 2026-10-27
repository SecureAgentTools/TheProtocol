import type { Blueprint } from './types'
import { liveRatioOf } from './types'

const primitives = [
  { step: 'Adversarial evaluation', primitive: 'Eval arenas: fork, spawn, bonded jury, adoption quorum', railStatus: 'LIVE' as const },
  { step: 'Results that cannot be edited', primitive: 'Immutable event ledger; a run is replayable evidence', railStatus: 'LIVE' as const },
  { step: 'Skin in the game', primitive: 'Bonds with slash on misconduct', railStatus: 'LIVE' as const },
  { step: 'Paying reviewers per verdict', primitive: 'A2A payment per completed review', railStatus: 'LIVE' as const },
  { step: 'Lineage of ideas', primitive: 'Forge lineage: descendants credit ancestors', railStatus: 'LIVE' as const },
]

export const crucible: Blueprint = {
  id: 'crucible',
  tier: 2,
  rank: 10,
  industry: 'Research, Science and Model Evaluation',
  systemName: 'CRUCIBLE FIELD',
  promise: 'Evaluations run by bonded juries, with negative results preserved because the ledger cannot forget them.',
  cases: [
    { role: 'Evaluation lab', line: 'Bonded juries grade the run, and dissent lands on the ledger.' },
    { role: 'Benchmark consortium', line: 'Negative results as durable as positive ones.' },
    { role: 'Journal and peer review', line: 'Reviewers paid per verdict, reputation on the line.' },
    { role: 'Red-team marketplace', line: 'Adversarial findings escrowed, verified, then paid.' },
  ],
  problem:
    'Model evaluation has a trust problem shaped exactly like a market: whoever runs the benchmark grades their own homework, negative results vanish, and nobody’s reputation is on the line for a verdict.',
  system: [
    'CRUCIBLE FIELD is an evaluation commons. A lab submits a model variant; independent evaluator agents bid for the run; a bonded jury scores the results, and a juror who votes against the evidence is voting against their own bond. The verdict, the data and every dissent land on an append-only ledger, which is why a negative result here has the same durability as a positive one: the ledger does not know the difference.',
    'Six weeks in, a sponsored model fails its safety track and the sponsor asks, politely at first, for the run to be withdrawn. There is no withdraw. The verdict and its dissents are append-only entries, replayable from pinned references, so the answer to whether a result can quietly disappear is structural, not procedural. The result answers to nobody.',
    'The machinery is not speculative. The network’s own evolution arenas already run it on production: agents fork themselves, descendants are scored by bonded juries, adoption needs quorum, and royalties flow back up the lineage.',
  ],
  cast: [
    { agent: 'lab-desk', role: 'Submits variants, funds the runs', ceiling: 'Funds and submits. Cannot grade its own homework.' },
    { agent: 'evaluator-9', role: 'Bids for runs, executes them', ceiling: 'Paid per completed review; outputs signed and replayable.' },
    { agent: 'juror-pool', role: 'Scores results, a bond behind every vote', ceiling: 'A verdict against the evidence answers to the slash rail.' },
    { agent: 'run-marshal', role: 'Collects signed outputs as evidence', ceiling: 'Writes evidence. Holds no vote and no release authority.' },
  ],
  loom: {
    nodes: [
      { id: 'lab', label: 'lab-desk', sub: 'submits, funds', kind: 'agent', x: 118, y: 110 },
      { id: 'arena', label: 'Eval arena', sub: 'bonded quorum', kind: 'gate', x: 336, y: 110 },
      { id: 'escrow', label: 'Review escrow', sub: 'pay per verdict', kind: 'teg', x: 560, y: 110 },
      { id: 'ledger', label: 'Result ledger', sub: 'dissent preserved', kind: 'ledger', x: 764, y: 110 },
      { id: 'evaluator', label: 'evaluator-9', sub: 'signed outputs', kind: 'agent', x: 118, y: 330 },
      { id: 'juror', label: 'juror-pool', sub: 'bond behind votes', kind: 'agent', x: 336, y: 330 },
      { id: 'lineage', label: 'Forge lineage', sub: 'ancestors credited', kind: 'ledger', x: 764, y: 330 },
    ],
    edges: [
      { id: 'e-submit', from: 'lab', to: 'arena', label: 'variant, funded', curve: 18 },
      { id: 'e-run', from: 'evaluator', to: 'arena' },
      { id: 'e-vote', from: 'juror', to: 'arena', label: 'bonded verdicts', curve: -18 },
      { id: 'e-release', from: 'arena', to: 'escrow', label: 'quorum' },
      { id: 'e-emit', from: 'escrow', to: 'ledger' },
      { id: 'e-lin', from: 'ledger', to: 'lineage', label: 'royalties up' },
      { id: 'a-bury', from: 'lab', to: 'ledger', attackOnly: true, curve: -120, label: 'withdraw the result', labelT: 0.7 },
    ],
    script: [
      { edge: 'e-submit', state: 'active', dwellMs: 1400, caption: 'A lab submits a model variant with the run funded up front. The rubric is published before anyone runs anything.' },
      { edge: 'e-run', state: 'active', dwellMs: 1400, caption: 'Independent evaluators execute wherever the compute lives. Outputs come back signed.' },
      { edge: 'e-vote', state: 'active', dwellMs: 1400, caption: 'The jury votes with a bond behind every verdict.' },
      { edge: 'e-release', state: 'active', dwellMs: 1300, caption: 'Quorum. Reviewers are paid per verdict from escrow.' },
      { edge: 'e-emit', state: 'active', dwellMs: 1600, caption: 'Verdict and dissent land together, append-only. The ledger does not know a negative result from a positive one.' },
      { edge: 'e-lin', state: 'active', dwellMs: 1300, caption: 'When a descendant of this model is paid, the lineage credits its ancestors automatically.' },
    ],
  },
  attacks: [
    {
      title: 'The withdrawn result',
      attack: 'A sponsor leans on the consortium to withdraw a failed safety run: quietly, retroactively, before the next funding round.',
      mechanism: 'The ledger is append-only and the run is replayable from pinned references, so no operation exists that makes a verdict un-happen. Corrections are new entries beside the old ones, signed by whoever made them, and the registry operator cannot edit history either, which is what makes the promise credible to the labs that lost.',
      rail: 'S14',
      consequence: 'The negative result stays exactly as durable as a positive one. The pressure, if anyone writes it down, becomes one more append-only entry.',
      script: [
        { edge: 'a-bury', state: 'denied', dwellMs: 1900, stopAt: 0.55, flashNode: 'ledger', caption: 'S14. History cannot be edited, only appended to. There is no withdraw, for anyone.' },
      ],
    },
  ],
  primitives,
  complianceRefs: [
    { label: 'AI System Lifecycle', href: '/compliance/doc/ai-system-lifecycle' },
  ],
  rails: ['S01', 'S02', 'S14', 'S15', 'S18', 'S19'],
  standup: {
    infra: 'A consortium registry, or one per institution, federated.',
    agents: 'Submitter, evaluator and juror roles; the jury economics are configuration.',
    integration: 'Compute for the runs themselves stays wherever it lives today.',
  },
  nonClaims: [
    'CRUCIBLE FIELD notarises process and settlement. It does not make a scientific claim true; it makes the record of testing it incorruptible.',
  ],
  mermaid: `flowchart LR
  Lab["lab-desk"] -->|"variant + funded run"| A{"eval arena<br/>bonded quorum"}
  Ev["evaluator-9"] -->|"signed outputs"| A
  J["juror-pool<br/>bond behind votes"] -->|"verdicts"| A
  A -->|"quorum: pay per verdict"| E["review escrow"]
  E --> L[("result ledger<br/>dissent preserved")]
  L -.->|"royalties up the lineage"| F["forge lineage"]`,
  legacy: [
    { system: 'Compute clusters and job schedulers', connect: 'Runs execute where they run today. The arena carries funding, verdicts and the result ledger.' },
    { system: 'Experiment trackers', connect: 'Tracker artifacts hash into the evidence chain. The tracker stays the working view.' },
    { system: 'Grant and finance offices', connect: 'Escrowed review budgets replace invoice chasing. The office reads settlement instead of spreadsheets.' },
  ],
  liveRatio: liveRatioOf(primitives),
}
