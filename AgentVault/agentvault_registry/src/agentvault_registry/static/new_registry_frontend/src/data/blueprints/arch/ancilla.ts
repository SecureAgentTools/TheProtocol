import type { BlueprintDeep } from '../types'

// ANCILLA deep architecture (§18, V0660 (f)): the classical AI services around a quantum computer, each
// one an agent with receipts, with the model and the device staying where they already are. The geometry
// follows COLLEGIUM's, which the drawing check passes.

export const deep: BlueprintDeep = {
  intro:
    'ANCILLA deployed: the hardware group’s frame holds the mandate, the batch escrow and the batch ledger; the services sit on their own frames; the device, the decoder’s own code and the hosted model stay exactly where they are. The trace replays one batch, from the task going out to the correction the group replays itself.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE DEVICE GROUP', sub: 'mandate and escrow', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE SERVICES', sub: 'their own frames', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'THE FABRIC', sub: 'batches, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'OFF THE NETWORK', sub: 'device, model host', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'desk', label: 'device-desk', sub: 'sends the batches', kind: 'agent', x: 140, y: 135 },
      { id: 'gate', label: 'batch gate', sub: 'scope, units, caps', kind: 'gate', x: 310, y: 133 },
      { id: 'operator', label: 'Dr van Dijk', sub: 'mandate, device key', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'batch escrow', sub: 'opens on a check', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'batch ledger', sub: 'digests, versions', kind: 'ledger', x: 140, y: 375 },
      { id: 'replay', label: 'replay check', sub: 'the group’s own', kind: 'agent', x: 310, y: 375 },
      { id: 'decode', label: 'decode-service', sub: 'signs each batch', kind: 'agent', x: 690, y: 135 },
      { id: 'd-es', label: 'service ledger', sub: 'same batches, keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'calib', label: 'calib-service', sub: 'reads the device', kind: 'agent', x: 655, y: 300 },
      { id: 'meter', label: 'unit meter', sub: 'committed at run', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'batch relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, own units', kind: 'teg', x: 880, y: 490 },
      { id: 'device', label: 'the device', sub: 'stays in the lab', kind: 'external', x: 195, y: 692 },
      { id: 'host', label: 'model host', sub: 'runs the model', kind: 'external', x: 375, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'operator', to: 'gate', label: 'mandate', curve: -20, labelT: 0.6 },
      { id: 'e-send', from: 'desk', to: 'gate' },
      { id: 'e-task', from: 'gate', to: 'decode', label: 'batch, with its terms' },
      { id: 'e-fund', from: 'gate', to: 'teg' },
      { id: 'e-replay', from: 'replay', to: 'es', dashed: true, curve: 30 },
      { id: 'e-answer', from: 'calib', to: 'relay', label: 'summary', labelT: 0.5 },
      { id: 'e-meter', from: 'meter', to: 'relay', label: 'units, committed', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'decode', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-demit', from: 'decode', to: 'd-es', dashed: true, curve: 26 },
      { id: 'e-dev', from: 'device', to: 'es', label: 'digests only', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Dr van Dijk underwrites the desk once: a budget, the services it may call, a quarter.' },
      { edge: 'e-task', dwellMs: 1400, caption: 'A batch goes out with its terms: the syndromes’ digest, the units, what a receipt must name.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Each batch is escrowed, and the escrow opens on the group’s own replay rather than on the answer.' },
      { edge: 'e-meter', dwellMs: 1400, caption: 'The service’s units are committed as the work runs, not when the invoice is written.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The relay carries the batch and nothing else. The principal must be party to the contract.' },
      { edge: 'e-replay', dwellMs: 1500, caption: 'The group replays the corrections against the syndromes it sent. That check is classical and its own.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'A passing batch releases once, under a key made from the task and the batch.' },
      { edge: 'e-emit', dwellMs: 1400, caption: 'The ledger keeps the digest, the decoder’s version and the verdict. The syndromes stay in the lab.' },
    ],
    traceLabel: 'One batch: the task priced, the units committed, the corrections replayed by the buyer, paid once.',
  },
  plan: [
    {
      name: 'Phase 1',
      headline: 'One service, batches with receipts',
      runs: 'A single frame from the free licence and pre-built images, with quantum workloads in shadow so every decision is made and reported and nothing is refused yet.',
      agents: 'A device desk and one decoding service. The decoder runs where its owner runs it.',
      integrates: 'The syndrome pipeline, read-only, on simulated syndromes from the group’s own simulator.',
      notYet: 'No real device, no calibration that means anything, no live loop. Shadow mode reports a refusal and allows it.',
      proof: 'A batch answered without its decoder version is reported as failing the template, with the digests already in the record.',
    },
    {
      name: 'Phase 2',
      headline: 'The buyer’s own replay opens the escrow',
      runs: 'The same frame with quantum workloads on. A receipt that does not name the model and version fails before the check.',
      agents: 'A second decoding service answering the same batches, each signing its own work.',
      integrates: 'A hosted model behind one of the services, called by that service and never by the network.',
      notYet: 'Still simulated syndromes. The unit proof is produced by the service, and a service without a prover reports its units unproven and says so.',
      proof: 'Two services answer one batch, the group replays both, and the ledger shows two receipts under their own keys with one release.',
    },
    {
      name: 'Phase 3',
      headline: 'A device that is really running',
      runs: 'The hardware group’s own device producing real syndromes, with the services on their own frames, federated.',
      agents: 'A calibration service reading real measurements, which is the first point at which its summary means anything.',
      integrates: 'The device control stack stays the group’s, and the live correction loop stays beside the hardware.',
      notYet: 'This phase is the DESIGNED part of the chamber. The microsecond loop is not a network service and is not becoming one.',
      proof: 'A calibration summary is dated to real device measurements, and a decoding batch on real syndromes is replayed and paid once.',
    },
  ],
  sequence: `sequenceDiagram
  participant V as Dr van Dijk
  participant G as Batch gate
  participant S as decode-service
  participant T as Batch escrow
  participant R as replay check
  participant L as Batch ledger
  V->>G: mandate: budget, services, a quarter
  G->>S: batch, with its terms
  G->>T: escrow per batch
  S->>T: corrections, signed, with model and version
  R->>L: the group replays them itself
  T->>L: release once, on the replay
  Note over L: digests and versions, never the syndromes`,
  sequenceTitle: 'One batch, from the task priced to the buyer’s own replay',
  sizing: [
    { level: 'L1', what: 'One group, one service, simulated syndromes; one frame carries registry, TEG, ledger and identity', containers: 'nine, from the kit' },
    { level: 'L2', what: 'Several services answering the same batches, an agent per service, the meter beside each one', containers: 'the same frame' },
    { level: 'L3', what: 'Services in their own units, a real device, federated with cross-registry settlement', containers: 'one frame per service' },
  ],
}
