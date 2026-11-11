import type { BlueprintDeep } from '../types'

// ALEA deep architecture (§18, V0660 (f)): a sampling beacon whose draws are committed before use and
// checked offline afterwards. The geometry follows COLLEGIUM's, which the drawing check passes. Two nodes
// here are deliberately marked as specified rather than running: the device and its certifier.

export const deep: BlueprintDeep = {
  intro:
    'ALEA deployed: the authority’s frame holds the mandate, the commit log, the draw escrow and the beacon ledger; the source sits on its own frame with its device; the certifier, the publication channel and the municipalities’ systems stay where they are. The trace replays one day, from the commitment to the offline check a member runs without asking anyone.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE AUTHORITY', sub: 'mandate and commits', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE SOURCE', sub: 'its own frame', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'THE FABRIC', sub: 'draws, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE PUBLIC SIDE', sub: 'members, certifier', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'beacon', label: 'beacon-agent', sub: 'publishes a draw', kind: 'agent', x: 140, y: 135 },
      { id: 'gate', label: 'draw gate', sub: 'who, how often', kind: 'gate', x: 310, y: 133 },
      { id: 'operator', label: 'Ms Castellan', sub: 'mandate, device key', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'draw escrow', sub: 'one draw, once', kind: 'teg', x: 310, y: 255 },
      { id: 'commit', label: 'commit log', sub: 'before any use', kind: 'ledger', x: 310, y: 375 },
      { id: 'es', label: 'beacon ledger', sub: 'draws and proofs', kind: 'ledger', x: 140, y: 375 },
      { id: 'src', label: 'source-GEN-1', sub: 'signs each draw', kind: 'agent', x: 690, y: 135 },
      { id: 's-es', label: 'source ledger', sub: 'same draws, keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'device', label: 'the device', sub: 'specified, not built', kind: 'external', x: 655, y: 300 },
      { id: 'decode', label: 'decode-assistant', sub: 'batches, not a loop', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'draw relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, own units', kind: 'teg', x: 880, y: 490 },
      { id: 'member', label: 'a municipality', sub: 'verifies offline', kind: 'external', x: 195, y: 692 },
      { id: 'certifier', label: 'the certifier', sub: 'specified, not built', kind: 'external', x: 380, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'operator', to: 'gate', label: 'mandate', curve: -20, labelT: 0.6 },
      { id: 'e-ask', from: 'beacon', to: 'gate' },
      { id: 'e-order', from: 'gate', to: 'src', label: 'today’s draw' },
      { id: 'e-pay', from: 'gate', to: 'teg' },
      // No label: the commit log and the ledger are adjacent, so the gap between their boxes is narrower
      // than the shortest honest label. The trace caption carries it, which is what a caption is for.
      { id: 'e-commit', from: 'commit', to: 'es', dashed: true, curve: 30 },
      { id: 'e-draw', from: 'device', to: 'relay', label: 'outcomes', labelT: 0.5 },
      { id: 'e-decode', from: 'decode', to: 'relay', label: 'corrections', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'src', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-semit', from: 'src', to: 's-es', dashed: true, curve: 26 },
      { id: 'e-check', from: 'member', to: 'es', label: 'checked offline', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Ms Castellan underwrites the beacon once: its consumers, their caps, a year.' },
      { edge: 'e-commit', dwellMs: 1500, caption: 'The commitment lands first. Everything after it is in the record in that order.' },
      { edge: 'e-order', dwellMs: 1300, caption: 'The source is asked for today’s draw, under the beacon’s own mandate.' },
      { edge: 'e-draw', dwellMs: 1500, caption: 'The device’s outcomes are signed by the source. The device itself is specified and not built.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The relay carries the draw and nothing else. The principal must be party to the contract.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'The draw is paid once, under a key made from the draw and the consumer.' },
      { edge: 'e-emit', dwellMs: 1400, caption: 'The reveal follows the commitment on a ledger nobody can edit.' },
      { edge: 'e-check', dwellMs: 1500, caption: 'A municipality checks the chain and its manifest offline, without asking the authority.' },
    ],
    traceLabel: 'One day: committed first, drawn and signed, paid once, checked offline by whoever relied on it.',
  },
  plan: [
    {
      name: 'Phase 1',
      headline: 'The discipline, with a software source',
      runs: 'A single frame from the free licence and pre-built images, with quantum workloads in shadow. The source is software and the chamber says so on its face.',
      agents: 'A beacon agent, one consumer desk, one source agent.',
      integrates: 'The publication channel reads the reveal. The sampling procedure stays the authority’s.',
      notYet: 'No quantum device, no certification, and nothing here is certified randomness. Shadow mode reports a refusal and allows it.',
      proof: 'A commitment and its reveal sit in the ledger in that order, and an offline check of the chain passes on a member’s own machine.',
    },
    {
      name: 'Phase 2',
      headline: 'Consumers capped, draws paid once',
      runs: 'The same frame with quantum workloads on. A consumer past its cap is refused before any payment, and a repeat is answered from the record.',
      agents: 'A consumer desk per member, each allowlisted and capped.',
      integrates: 'Members verify offline as a matter of course rather than on request.',
      notYet: 'Still no device and no certifier. The metering proof is produced by the source, and a source without a prover reports its shots unproven and says so.',
      proof: 'A member asking twice is billed once, and the second answer comes from the record with the same key.',
    },
    {
      name: 'Phase 3',
      headline: 'A provider’s device, and a certifier',
      runs: 'The source on its own frame with its own hardware. Only the frame holding the escrow releases it.',
      agents: 'A decoding assistant beside the device, in batches, and a certifier that publishes its own test results.',
      integrates: 'The certifier’s protocol and its statistical test, both of them its own.',
      notYet: 'This phase is the DESIGNED part of the chamber. Until a provider brings a device and a certifier brings a protocol, the word certified stays off every page.',
      proof: 'A draw carries the device’s attestation and a certifier’s published test result, and a member checks both offline.',
    },
  ],
  sequence: `sequenceDiagram
  participant M as Ms Castellan
  participant G as Draw gate
  participant K as Commit log
  participant S as source-GEN-1
  participant T as Draw escrow
  participant L as Beacon ledger
  M->>G: mandate: consumers, caps, a year
  G->>K: commitment, before any read
  G->>S: today's draw
  S->>T: draw, signed, with its shots
  T->>L: release once, reveal after the commitment
  Note over L: a member checks the chain offline, asking nobody`,
  sequenceTitle: 'One day, from the commitment to the offline check',
  sizing: [
    { level: 'L1', what: 'One authority, a software source; one frame carries registry, TEG, ledger and identity', containers: 'nine, from the kit' },
    { level: 'L2', what: 'An authority with capped members, a consumer desk per member, the commit log beside the ledger', containers: 'the same frame' },
    { level: 'L3', what: 'A provider’s device on its own frame, federated with cross-registry settlement, a decoding assistant beside the device', containers: 'one frame per source' },
  ],
}
