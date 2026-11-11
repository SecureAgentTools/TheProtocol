import type { BlueprintDeep } from '../types'

// COLLEGIUM deep architecture (§18, V0660 (f)): a consortium whose allocations are declared by the
// centre's frame and spent by project agents to a cap the rails hold. The quantum part is the backend;
// everything load-bearing here is the allocation, authority, money and evidence machinery.

export const deep: BlueprintDeep = {
  intro:
    'COLLEGIUM deployed: the centre’s frame declares the allocations, holds the project purses and keeps the grant ledger; the member groups sit on their own frames; the backends, the scheduler and the proposal system stay where they are, signed at the edges. The trace replays one overnight round of proj-017, from the declared allocation to the proven shot count.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE CENTRE FRAME', sub: 'allocations, purses', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE MEMBERS', sub: 'their own frames', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'THE FABRIC', sub: 'jobs, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE MACHINE ROOM', sub: 'backends, schedulers', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'desk', label: 'centre-desk', sub: 'grants from profile', kind: 'agent', x: 140, y: 135 },
      { id: 'profile', label: 'allocation doc', sub: 'id, holder, cap', kind: 'gate', x: 310, y: 133 },
      { id: 'committee', label: 'Prof. Haas', sub: 'chairs the panel', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'project purse', sub: 'funded under the cap', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'grant ledger', sub: 'one line per grant', kind: 'ledger', x: 140, y: 375 },
      { id: 'meter', label: 'shot meter', sub: 'committed at run', kind: 'agent', x: 310, y: 375 },
      { id: 'planner', label: 'proj-017-planner', sub: 'no wallet of its own', kind: 'agent', x: 690, y: 135 },
      { id: 'g-es', label: 'group ledger', sub: 'same jobs, same keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'backend', label: 'sim-JUW-2', sub: 'signs each job', kind: 'agent', x: 655, y: 300 },
      { id: 'proof', label: 'proof-desk', sub: 'checks the shots', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'job relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, own units', kind: 'teg', x: 880, y: 490 },
      { id: 'sched', label: 'scheduler', sub: 'the centre’s own', kind: 'external', x: 195, y: 692 },
      { id: 'device', label: 'a real device', sub: 'specified, not built', kind: 'external', x: 360, y: 692 },
    ],
    edges: [
      { id: 'e-declare', from: 'committee', to: 'profile', label: 'allocation', curve: -20, labelT: 0.6 },
      { id: 'e-grant', from: 'desk', to: 'profile' },
      { id: 'e-ask', from: 'profile', to: 'planner', label: 'room left, checked' },
      { id: 'e-fund', from: 'profile', to: 'teg' },
      // No label: the meter and the ledger are adjacent, so the gap between their boxes is 42 logical px
      // and the shortest honest label needs more. Bowing it put the label on the release edge instead.
      // The trace caption carries this line's meaning, which is what a caption is for.
      { id: 'e-meter', from: 'meter', to: 'es', dashed: true, curve: 30 },
      { id: 'e-run', from: 'backend', to: 'relay', label: 'job, signed', labelT: 0.5 },
      { id: 'e-proof', from: 'proof', to: 'relay', label: 'proof, published circuit', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'planner', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-gemit', from: 'planner', to: 'g-es', dashed: true, curve: 26 },
      { id: 'e-sched', from: 'sched', to: 'es', label: 'queue refs in every job', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-declare', dwellMs: 1500, caption: 'The panel’s decision becomes a declared allocation: an id, one named holder, a cap, in the centre’s unit.' },
      { edge: 'e-ask', dwellMs: 1400, caption: 'At 03:40 the planner asks for the next batch. The room left is checked before anything is funded.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Inside the cap, the project purse is funded and the allocation’s room counts down.' },
      { edge: 'e-run', dwellMs: 1500, caption: 'The backend signs each job: the circuit’s digest, the shots, the device that ran it.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The relay carries the job and nothing else. The principal must be party to the contract.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'The purse releases once, under a key made from the booking and the job.' },
      { edge: 'e-emit', dwellMs: 1400, caption: 'The grant lands on the ledger with its allocation named, so a holder of the profile can audit the cap.' },
      { edge: 'e-proof', dwellMs: 1500, caption: 'The reported shots are proven against the log the meter committed to, on a circuit anyone can verify.' },
    ],
    traceLabel: 'One overnight round of proj-017: declared allocation, checked room, signed jobs, proven shots.',
  },
  plan: [
    {
      name: 'Phase 1',
      headline: 'One centre, one allocation, simulators only',
      runs: 'A single frame from the free licence and pre-built images. Quantum workloads switched to shadow, so every allocation decision is made and reported and nothing is refused yet.',
      agents: 'A centre desk, one project planner, one simulator backend agent.',
      integrates: 'Read-only against the proposal system: the allocation document is written by hand from an approved proposal.',
      notYet: 'No real device, no second centre, no cross-unit settlement. Shadow mode means a grant past the cap is reported and allowed.',
      proof: 'The shadow report names a grant that on refuses, with the cap it crosses and the holder it was granted to, while the grant itself still lands on the ledger.',
    },
    {
      name: 'Phase 2',
      headline: 'The cap holds, in front of the money',
      runs: 'The same frame with quantum workloads on. A grant past the cap, for an undeclared allocation or for another holder is refused before the treasury is called.',
      agents: 'A planner per project, each a sub-agent with no wallet, spending its project’s purse under a mandate.',
      integrates: 'The scheduler’s queue references travel in each job attestation. The proposal system still owns approval.',
      notYet: 'Still no real device. The metering proof is carried but produced by the provider, and a provider without a prover reports its shots unproven and says so.',
      proof: 'An overnight batch past the remaining room is refused with no treasury movement to unwind, and the ledger shows the grants that did land, each naming its allocation.',
    },
    {
      name: 'Phase 3',
      headline: 'A consortium, each centre in its own unit',
      runs: 'Member centres on their own frames, federated. Jobs cross frames; only the frame holding the escrow releases it.',
      agents: 'A desk per centre, a proof desk that checks reported shot counts against committed logs.',
      integrates: 'Recharge and finance read settlement. Caps are audited from the ledger rather than from a quarterly report.',
      notYet: 'Real hardware stays specified and marked DESIGNED on every chamber page until a provider brings its own device and account.',
      proof: 'A project at one centre spends an allocation granted by another, in that centre’s unit, and both ledgers show the same job under the same key.',
    },
  ],
  sequence: `sequenceDiagram
  participant C as Allocation committee
  participant F as Allocation profile
  participant P as proj-017-planner
  participant T as Project purse
  participant B as sim-JUW-2
  participant L as Grant ledger
  C->>F: declare proj-017, one holder, a cap
  P->>F: ask for the next batch
  F->>F: holder and room left, checked
  F->>T: fund under the cap
  B->>T: job, signed, shots metered
  T->>L: grant and release, allocation named
  Note over L: a holder of the profile audits the cap from here`,
  sequenceTitle: 'One round, from the declared allocation to the audited cap',
  sizing: [
    { level: 'L1', what: 'One centre, one project, simulators; one frame carries registry, TEG, ledger and identity', containers: 'nine, from the kit' },
    { level: 'L2', what: 'A centre with several projects and backends, an agent per backend and per project, the meter beside each backend', containers: 'the same frame' },
    { level: 'L3', what: 'A consortium of centres, each in its own unit, federated with cross-registry settlement', containers: 'one frame per centre' },
  ],
}
