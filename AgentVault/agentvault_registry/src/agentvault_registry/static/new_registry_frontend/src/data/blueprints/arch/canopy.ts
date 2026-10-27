import type { BlueprintDeep } from '../types'

// CANOPY deep architecture (§18, frontier wave 2026-09-25): one quarter of carbon removal at Ember Hollow,
// escrowed by a buyer on another frame, released on an accredited verifier's signature, retired in the open.

export const deep: BlueprintDeep = {
  intro:
    'CANOPY deployed: the project registry’s frame holds the offtake contract, its escrow and the tonne ledger; the buyer acts from its own frame and currency, and the verifier signs from its own; the kilns, the sensors and the MRV platform stay where they are, signed at the edges. The trace replays one quarter at Ember Hollow, from the buyer’s mandate to the retired tonne.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE PROJECT REGISTRY', sub: 'offtake, escrow, tonne ledger', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE BUYER’S FRAME', sub: 'its own currency, its own law', x: 530, y: 50, w: 440, h: 300, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'money, signatures', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE FIELD', sub: 'kilns, sensors, MRV', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
      { id: 'zv', label: 'THE VERIFIER’S FRAME', sub: 'accredited, independent', x: 530, y: 625, w: 440, h: 100, kind: 'frame' },
    ],
    nodes: [
      { id: 'coop', label: 'coop-desk', sub: 'claims each quarter', kind: 'agent', x: 140, y: 135 },
      { id: 'offtake', label: 'offtake contract', sub: 'four quarters, in order', kind: 'gate', x: 310, y: 133 },
      { id: 'es', label: 'tonne ledger', sub: 'append-only', kind: 'ledger', x: 140, y: 255 },
      { id: 'teg', label: 'offtake escrow', sub: 'held on this frame', kind: 'teg', x: 310, y: 255 },
      { id: 'probes', label: 'kiln-probes', sub: 'sign every reading', kind: 'agent', x: 140, y: 375 },
      { id: 'treasury', label: 'co-op treasury', sub: 'members vote it', kind: 'teg', x: 310, y: 375 },
      { id: 'c-es', label: 'claims ledger', sub: 'mirrored entries', kind: 'ledger', x: 690, y: 135 },
      { id: 'varga', label: 'Sana Varga', sub: 'mandate, one tap', kind: 'human', x: 860, y: 135 },
      { id: 'claims', label: 'claims-desk', sub: 'signs retirements', kind: 'agent', x: 690, y: 255 },
      { id: 'desk', label: 'offtake-desk', sub: 'no wallet, a permit', kind: 'agent', x: 860, y: 255 },
      { id: 'relay', label: 'fabric relay', sub: 'a courier only', kind: 'registry', x: 750, y: 540 },
      { id: 'fx', label: 'FX pool', sub: 'frame to frame, once', kind: 'teg', x: 880, y: 484 },
      { id: 'kilns', label: 'kilns + sensors', sub: 'temperature, mass', kind: 'external', x: 150, y: 692 },
      { id: 'mrv', label: 'MRV platform', sub: 'the verifier’s bench', kind: 'external', x: 360, y: 692 },
      { id: 'verifier', label: 'verifier-07', sub: 'signs each batch', kind: 'agent', x: 750, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'varga', to: 'desk', label: 'mandate' },
      { id: 'e-fund', from: 'desk', to: 'fx', label: 'funds the year' },
      { id: 'e-land', from: 'fx', to: 'teg', label: 'held up front', curve: 22, labelT: 0.45 },
      { id: 'e-raw', from: 'kilns', to: 'probes', label: 'raw telemetry', dashed: true, labelT: 0.45 },
      { id: 'e-readings', from: 'probes', to: 'es', label: 'readings, signed', dashed: true },
      { id: 'e-claim', from: 'coop', to: 'offtake', label: 'claims Q3' },
      { id: 'e-bench', from: 'mrv', to: 'verifier', dashed: true },
      { id: 'e-attest', from: 'verifier', to: 'relay', label: 'batch Q3, signed' },
      { id: 'e-retire', from: 'claims', to: 'relay', label: 'retire 1,240 t', labelT: 0.6 },
      { id: 'e-relay', from: 'relay', to: 'offtake', label: 'principal checked', labelT: 0.4 },
      { id: 'e-release', from: 'offtake', to: 'teg', label: 'release Q3', labelT: 0.78 },
      { id: 'e-pay', from: 'teg', to: 'treasury', label: '22,320 units' },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 28 },
      { id: 'e-record', from: 'offtake', to: 'es', label: 'retired', labelT: 0.65 },
      { id: 'e-mirror', from: 'claims', to: 'c-es', dashed: true },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Sana Varga underwrites the buyer’s treasury for twelve months. Its offtake desk carries a permit: three projects, 120,000 units.' },
      { edge: 'e-fund', dwellMs: 1400, caption: 'In January the desk funds the year from the buyer’s frame: 4,800 tonnes at 18 units a tonne.' },
      { edge: 'e-land', dwellMs: 1400, caption: 'The FX pool carries it across frames. The escrow lands on the project registry, exactly once.' },
      { edge: 'e-readings', dwellMs: 1400, caption: 'All quarter the probe gateways sign every reading, under certificates that live hours, not years.' },
      { edge: 'e-claim', dwellMs: 1300, caption: 'In October the co-op desk claims the third quarter: 1,240 tonnes.' },
      { edge: 'e-bench', dwellMs: 1300, caption: 'The verifier works the batch on its own bench, over the signed readings.' },
      { edge: 'e-attest', dwellMs: 1500, caption: 'At 07:40 verifier-07 signs batch Q3: one attestation, under its own identity.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The signature crosses the fabric; the relaying peer is a courier, never the principal.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'The offtake contract releases the third-quarter tranche, and only that one.' },
      { edge: 'e-pay', dwellMs: 1400, caption: '22,320 units land in the co-op treasury, where the members vote what happens next.' },
      { edge: 'e-retire', dwellMs: 1400, caption: 'The buyer’s claims desk retires the 1,240 tonnes, couriered home the same way.' },
      { edge: 'e-record', dwellMs: 1500, caption: 'The retirement lands beside the attestation it cites. A second claim on the same batch is plain to see.' },
    ],
    traceLabel: 'One quarter: funded, measured, signed, released, retired in the open.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One past year, re-read as signed entries.',
      runs: 'Nothing. Last year’s offtake redrawn as four milestones, four attestations, four releases and the retirements behind them.',
      agents: 'None. The project, the verifier and the buyer agree what a batch attestation must reference before anyone signs one.',
      integrates: 'Nothing. The sensors, the MRV platform and the carbon registry stay exactly as they are.',
      notYet: 'No escrow and no signatures.',
      proof: 'Last year’s four batches re-expressed as milestones and attestations, and all three parties sign off on the tonnes each one covers.',
    },
    {
      name: 'Pilot',
      headline: 'One project, one quarter, a small offtake.',
      runs: 'A hosted registry seat for the project. The buyer and the verifier join as accounts, in one currency.',
      agents: 'Probe gateways on four kilns, verifier-07, the co-op desk, and an offtake desk and a claims desk for the buyer.',
      integrates: 'Kiln telemetry feeds the gateways; the MRV report’s references ride in the attestation.',
      notYet: 'No second frame and no FX pool. Retirements are copied to the carbon registry by hand.',
      proof: 'One quarter settles from escrow on the verifier’s signature, and a deliberate second presentation of the same batch moves nothing.',
    },
    {
      name: 'Production',
      headline: 'The registry runs its own frame.',
      runs: 'The project registry’s frame: registry, TEG, event store, identity fabric, on the registry operator’s hardware.',
      agents: 'Probe gateways on all 38 kilns, the verifier agents of each accredited firm, and the co-op desk with the members’ treasury votes live.',
      integrates: 'MRV report references in every attestation; carbon registry serial numbers in every retirement.',
      notYet: 'Buyers on other frames. One registry proves a full year first.',
      proof: 'An audit replays the year from the ledger: every unit released matches a signed batch, and every retirement cites exactly one attestation.',
    },
    {
      name: 'Federation',
      headline: 'Buyers and registries bring their own frames.',
      runs: 'Unchanged. Buyers run frames in their own currencies; registries in other countries federate bilaterally.',
      agents: 'Offtake desks under named mandates; verifiers’ track records travel with their identities.',
      integrates: 'Each new buyer or registry is a signed card and a licence, and money crosses through FX pools between sovereign frames.',
      notYet: 'The private-threshold circuit is designed, not written. Batches settle on signed readings without it.',
      proof: 'A buyer on another continent funds, receives and retires its first batch in its own currency, and the ledger shows one attestation per batch across both frames.',
    },
  ],
  sequenceTitle: 'One batch, signature to retirement',
  sequence: `sequenceDiagram
  participant Buy as buyer desks (their frame)
  participant Ver as verifier-07 (its frame)
  participant Off as offtake contract
  participant TEG as offtake escrow
  participant Co as co-op treasury
  participant ES as tonne ledger
  Buy->>TEG: the year funded via the FX pool, 4,800 t at 18
  Ver->>Off: batch Q3 attested, 1,240 t, signed
  Off->>TEG: release the Q3 milestone
  TEG-->>Co: 22,320 units, exactly once
  TEG-->>ES: the release, beside the attestation
  Buy->>Off: retirement of 1,240 t, signed, citing the attestation
  Off-->>ES: the retirement, append-only
  Note over Off: the Q3 milestone releases once#59; a retry moves nothing
  Note over ES: a failed batch stays#59; its correction sits beside it`,
  sizing: [
    { level: 'L1', what: 'Projects, verifiers and buyers join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A project runs its probe gateways and desks against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A national registry’s own frame, and each buyer’s, federated', containers: 'a full frame each' },
  ],
}
