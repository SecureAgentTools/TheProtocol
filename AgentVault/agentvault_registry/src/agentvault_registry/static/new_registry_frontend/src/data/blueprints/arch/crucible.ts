import type { BlueprintDeep } from '../types'

// CRUCIBLE FIELD deep architecture (§18) — bonded evaluation with results
// that cannot be edited, on machinery the network already runs on itself.

export const deep: BlueprintDeep = {
  intro:
    'CRUCIBLE FIELD deployed: the consortium frame holds the arena, the escrow and the result ledger; labs, evaluators and jurors act from their own registries; the compute stays wherever it already lives. None of this machinery is speculative: the network’s own evolution arenas run the same fork, quorum and lineage rails in production. The trace replays one evaluation, submission to preserved verdict.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE CONSORTIUM FRAME', sub: 'arena, escrow, results: neutral ground', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'LABS, EVALUATORS, JURORS', sub: 'their registries, their bonds', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'verdicts and money cross here', x: 530, y: 445, w: 440, h: 165, kind: 'fabric' },
      { id: 'ze', label: 'THE COMPUTE', sub: 'runs stay where the GPUs are', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'rubric', label: 'rubric registry', sub: 'published, versioned', kind: 'registry', x: 110, y: 135 },
      { id: 'arena', label: 'eval arena', sub: 'bonded quorum', kind: 'gate', x: 330, y: 135 },
      { id: 'es', label: 'result ledger', sub: 'dissent preserved', kind: 'ledger', x: 110, y: 255 },
      { id: 'teg', label: 'review escrow', sub: 'pay per verdict', kind: 'teg', x: 330, y: 255 },
      { id: 'marshal', label: 'run marshal', sub: 'collects outputs', kind: 'agent', x: 110, y: 375 },
      { id: 'lineage', label: 'forge lineage', sub: 'ancestors credited', kind: 'registry', x: 330, y: 375 },
      { id: 'lab', label: 'lab-desk', sub: 'submits variants', kind: 'agent', x: 610, y: 135 },
      { id: 'l-es', label: 'lab ledger', sub: 'same verdicts', kind: 'ledger', x: 750, y: 135 },
      { id: 'evaluator', label: 'evaluator-9', sub: 'bids for runs', kind: 'agent', x: 890, y: 255 },
      { id: 'juror', label: 'juror pool', sub: 'bond behind votes', kind: 'agent', x: 750, y: 255 },
      { id: 'relay', label: 'verdict relay', sub: 'signed, checked', kind: 'registry', x: 860, y: 500 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 700, y: 590 },
      { id: 'compute', label: 'GPU / HPC', sub: 'runs stay here', kind: 'external', x: 200, y: 692 },
      { id: 'repo', label: 'code, data repos', sub: 'pinned by reference', kind: 'external', x: 400, y: 692 },
    ],
    edges: [
      { id: 'e-submit', from: 'lab', to: 'arena', label: 'model variant', curve: -6 },
      { id: 'e-rubric', from: 'rubric', to: 'arena', dashed: true, curve: -6 },
      { id: 'e-fund', from: 'lab', to: 'xfer', label: 'funds the run', curve: -27, labelT: 0.4 },
      { id: 'e-land', from: 'xfer', to: 'teg', label: 'escrow lands home', curve: -48 },
      { id: 'e-bid', from: 'evaluator', to: 'relay', label: 'bids for runs', labelT: 0.31, curve: -9 },
      { id: 'e-outputs', from: 'compute', to: 'marshal', label: 'outputs, signed', dashed: true, labelT: 0.35 },
      { id: 'e-evidence', from: 'marshal', to: 'es', label: 'evidence in', dashed: true },
      { id: 'e-repo', from: 'repo', to: 'lineage', label: 'pinned by reference', dashed: true, labelT: 0.4 },
      { id: 'e-verdict', from: 'juror', to: 'relay', label: 'bonded verdicts', curve: -9, labelT: 0.49 },
      { id: 'e-tally', from: 'relay', to: 'arena', label: 'tally, checked', labelT: 0.59, curve: 18 },
      { id: 'e-verdictout', from: 'arena', to: 'teg', label: 'release', labelT: 0.8 },
      { id: 'e-emit', from: 'teg', to: 'es', label: 'one event', dashed: true, labelT: 0.5, curve: 3 },
      { id: 'e-pay', from: 'teg', to: 'xfer', curve: 6 },
      { id: 'e-jcredit', from: 'xfer', to: 'juror', curve: 27 },
      { id: 'e-lemit', from: 'lab', to: 'l-es', dashed: true },
      { id: 'e-lin', from: 'lineage', to: 'teg', label: 'royalties up' },
    ],
    script: [
      { edge: 'e-submit', dwellMs: 1400, caption: 'A lab submits a model variant to the arena. The submission is signed; the terms are public.' },
      { edge: 'e-rubric', dwellMs: 1300, caption: 'The rubric is versioned and published before anyone runs anything.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'The lab funds the evaluation up front.' },
      { edge: 'e-land', dwellMs: 1300, caption: 'The review escrow lands on the consortium frame, exactly once.' },
      { edge: 'e-bid', dwellMs: 1300, caption: 'Independent evaluators bid for the run, from their own registries.' },
      { edge: 'e-outputs', dwellMs: 1400, caption: 'The runs execute wherever the compute already lives. Outputs come back signed.' },
      { edge: 'e-evidence', dwellMs: 1300, caption: 'The evidence enters the record before anyone votes on it.' },
      { edge: 'e-verdict', dwellMs: 1400, caption: 'The jurors vote, with a bond behind every verdict.' },
      { edge: 'e-tally', dwellMs: 1300, caption: 'The tally crosses the fabric; the relaying peer is never the principal.' },
      { edge: 'e-verdictout', dwellMs: 1400, caption: 'Quorum. Reviewers are paid per verdict, and a juror who voted against the evidence answers to the slash rail instead.' },
      { edge: 'e-emit', dwellMs: 1500, caption: 'Verdict and dissent land together, append-only. A negative result is as durable as a positive one; the ledger does not know the difference.' },
      { edge: 'e-lin', dwellMs: 1400, caption: 'And when a descendant of this model is paid, the lineage machinery credits its ancestors automatically.' },
    ],
    traceLabel: 'One evaluation: bonded, escrowed, judged, preserved.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One benchmark, re-read as a market.',
      runs: 'Nothing. One existing benchmark redrawn as rubric, jury economics and escrow.',
      agents: 'None. The methodology board fights over the rubric, which is exactly where the fight belongs.',
      integrates: 'Nothing. The compute and the repos stay exactly as they are.',
      notYet: 'No bond exists. No verdict binds anyone.',
      proof: 'One past evaluation replayed against the drafted rubric, and the board agrees where every verdict and every dissent would have landed.',
    },
    {
      name: 'Pilot',
      headline: 'One track, bonded jury, small purses.',
      runs: 'A consortium registry seat, single VM. One evaluation track.',
      agents: 'Submitter, three evaluators, a five-juror pool with pilot bonds. The run marshal collects signed outputs.',
      integrates: 'Repos pinned by reference; runs execute on the labs’ own compute.',
      notYet: 'Pocket-sized bonds. One track. Lineage royalties are recorded, not yet paid.',
      proof: 'Three evaluations run submission-to-verdict with every dissent preserved on the ledger and every juror paid per verdict.',
    },
    {
      name: 'Production',
      headline: 'The commons, with slashing live.',
      runs: 'The consortium frame: registry, TEG, EventStore, identity fabric, held by no single lab.',
      agents: 'The full cast; bonds at meaningful size; the slash rail live for verdicts against the evidence.',
      integrates: 'Institutional repos and compute quotas; results feed member dashboards from the ledger, not from PDFs.',
      notYet: 'Cross-consortium federation. One commons proves itself first.',
      proof: 'A contested verdict survives an appeal because the run replays byte-identically from the pinned references and the ledger.',
    },
    {
      name: 'Federation',
      headline: 'Institutions bring their own frames.',
      runs: 'Unchanged. Member institutions federate their registries bilaterally.',
      agents: 'Juror reputations travel with DIDs; evaluator track records are portable and provable.',
      integrates: 'Each new institution is a signed card and a license, not a memorandum of understanding about data handling.',
      notYet: 'Nothing structural. Growth is tracks and members.',
      proof: 'A new member institution submits, evaluates and judges in its first week without a single bilateral integration meeting.',
    },
  ],
  sequenceTitle: 'One verdict, submission to preserved dissent',
  sequence: `sequenceDiagram
  participant Lab as lab-desk (their frame)
  participant Are as eval arena
  participant Mar as run marshal
  participant Jur as juror pool (bonded)
  participant TEG as review escrow
  participant ES as result ledger
  Lab->>Are: model variant + funded escrow
  Are-->>Lab: run opened, rubric pinned
  Mar->>ES: signed outputs as evidence
  Jur->>Are: verdicts, a bond behind each
  Are->>TEG: quorum: pay per verdict
  TEG-->>ES: verdict + dissent, append-only
  Note over Jur: voting against the evidence answers to the slash rail
  Note over ES: negative results persist#59; the ledger does not know the difference`,
  sizing: [
    { level: 'L1', what: 'Labs and jurors join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'The consortium runs the arena against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A neutral consortium frame, or one per institution, federated', containers: 'a full frame each' },
  ],
}
