import type { BlueprintDeep } from '../types'

// TRUNK deep architecture (§18) — two carriers, one signed record, and a
// quarantine that arrives before the lawyers do.

export const deep: BlueprintDeep = {
  intro:
    'TRUNK at deployment scale: carrier A’s frame on the left, carrier B’s on the right, and the interconnect between them reduced to a fabric that settles per event. The mediation layer keeps feeding CDRs exactly as it does today; the switches never see the ledger. What disappears is the month-end file exchange, because there is no month-end state to reconcile. The trace replays one interconnect month that never needed one.',
  arch: {
    zones: [
      { id: 'zf', label: 'CARRIER A’S FRAME', sub: 'your registry, your counters', x: 30, y: 50, w: 360, h: 480, kind: 'frame' },
      { id: 'zp', label: 'CARRIER B’S FRAME', sub: 'their registry, their counters', x: 640, y: 50, w: 330, h: 480, kind: 'frame' },
      { id: 'zx', label: 'THE INTERCONNECT', sub: 'bilateral licence, per-event settle', x: 410, y: 50, w: 210, h: 480, kind: 'fabric' },
      { id: 'ze', label: 'THE NETWORK ESTATE', sub: 'mediation in; switches never see the ledger', x: 30, y: 580, w: 440, h: 110, kind: 'external' },
    ],
    nodes: [
      { id: 'ops', label: 'carrier-ops-a', sub: 'holds licence lever', kind: 'human', x: 110, y: 135 },
      { id: 'qgate', label: 'quarantine gate', sub: 'licence suspends', kind: 'gate', x: 300, y: 133 },
      { id: 'es', label: 'ledger A', sub: 'dedup on key', kind: 'ledger', x: 300, y: 375 },
      { id: 'teg', label: 'per-event settle', sub: 'receiver-side fee', kind: 'teg', x: 110, y: 255 },
      { id: 'meter', label: 'metering-a', sub: 'from mediation', kind: 'agent', x: 110, y: 375 },
      { id: 'desk', label: 'interconnect', sub: 'manages the peer', kind: 'agent', x: 300, y: 495 },
      { id: 'meter-b', label: 'metering-b', sub: 'their counters', kind: 'agent', x: 720, y: 135 },
      { id: 'es-b', label: 'ledger B', sub: 'same entry, signed', kind: 'ledger', x: 890, y: 255 },
      { id: 'teg-b', label: 'their TEG', sub: 'paid per event', kind: 'teg', x: 720, y: 375 },
      { id: 'reg-b', label: 'their registry', sub: 'signed card', kind: 'registry', x: 720, y: 495 },
      { id: 'xfer', label: 'cross-registry', sub: 'idempotency-keyed', kind: 'teg', x: 515, y: 255 },
      { id: 'mesh', label: 'federation mesh', sub: 'licences, bilateral', kind: 'registry', x: 515, y: 375 },
      { id: 'mediation', label: 'mediation layer', sub: 'CDRs as today', kind: 'external', x: 330, y: 647 },
      { id: 'switches', label: 'switches', sub: 'never see the ledger', kind: 'external', x: 150, y: 647 },
    ],
    edges: [
      { id: 'e-sw', from: 'switches', to: 'mediation', dashed: true },
      { id: 'e-cdr', from: 'mediation', to: 'meter', label: 'CDRs in', dashed: true, curve: -28 },
      { id: 'e-meter', from: 'meter', to: 'teg', label: 'per event' },
      { id: 'e-emit', from: 'teg', to: 'es', label: 'one event', dashed: true, labelT: 0.55 },
      { id: 'e-xset', from: 'teg', to: 'xfer', label: 'settle, keyed', curve: 20, labelT: 0.55 },
      { id: 'e-bcredit', from: 'xfer', to: 'teg-b', label: 'terminating side paid', labelT: 0.55 },
      { id: 'e-bmeter', from: 'meter-b', to: 'teg-b' },
      { id: 'e-bemit', from: 'teg-b', to: 'es-b', label: 'same entry', dashed: true },
      { id: 'e-lic', from: 'desk', to: 'mesh', label: 'bilateral licence', dashed: true },
      { id: 'e-card', from: 'reg-b', to: 'mesh', label: 'signed card', dashed: true },
      { id: 'e-qgate', from: 'ops', to: 'qgate', label: 'suspend', dashed: true },
      { id: 'e-quar', from: 'qgate', to: 'xfer', label: 'value stops', dashed: true, curve: 20 },
    ],
    script: [
      { edge: 'e-sw', dwellMs: 1300, caption: 'Traffic terminates all month. The switches never see the ledger; mediation is where the counters live.' },
      { edge: 'e-cdr', dwellMs: 1300, caption: 'CDRs arrive from the mediation layer, exactly as they already do.' },
      { edge: 'e-meter', dwellMs: 1400, caption: 'Each interconnect event settles as it happens. Not a file. Not a quarter.' },
      { edge: 'e-emit', dwellMs: 1400, caption: 'Both sides emit the same signed entry, and the ledger deduplicates on the idempotency key.' },
      { edge: 'e-xset', dwellMs: 1400, caption: 'Settlement crosses the interconnect under the same key. A retry can never double it.' },
      { edge: 'e-bcredit', dwellMs: 1400, caption: 'The terminating side is paid per event, and the fee lands with the receiver.' },
      { edge: 'e-bmeter', dwellMs: 1200, caption: 'Their counters metered the same call.' },
      { edge: 'e-bemit', dwellMs: 1400, caption: 'Their ledger holds the same entry. Two frames, one record, nothing left to reconcile.' },
      { edge: 'e-lic', dwellMs: 1300, caption: 'The relationship itself is a bilateral licence on the mesh, revocable without a lawsuit.' },
      { edge: 'e-qgate', dwellMs: 1400, caption: 'In March, a peer starts inflating counters. The desk moves to suspend its licence.' },
      { edge: 'e-quar', dwellMs: 1500, caption: 'The quarantine bites within a sync cycle: its ability to move value ends, and every entry it ever signed stays intact for the lawyers.' },
    ],
    traceLabel: 'One interconnect month with no month-end: settle, dedup, quarantine.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One interconnect, re-read per event.',
      runs: 'Nothing. One month of CDRs from one interconnect, replayed as per-event settlements.',
      agents: 'None. Wholesale and revenue assurance compare the replay to the invoice they actually argued about.',
      integrates: 'Nothing. Mediation and switching are untouched.',
      notYet: 'No registry, no licence, no settlement.',
      proof: 'The replayed month lands within reconciliation tolerance of the settled invoice, and both teams can name where every difference comes from.',
    },
    {
      name: 'Pilot',
      headline: 'One peer, shadow settlement.',
      runs: 'One registry per carrier, single VM each, federated bilaterally for this interconnect only.',
      agents: 'Metering and settlement roles on both sides. The licence lever exists and is drilled.',
      integrates: 'Mediation feeds both sides live; settlement runs in shadow beside the existing process.',
      notYet: 'No real money. The quarterly process still runs, now with a rival it has to match.',
      proof: 'A full billing cycle in which the shadow ledger and the legacy reconciliation agree, or every disagreement is attributed to a named counter.',
    },
    {
      name: 'Production',
      headline: 'The interconnect settles itself.',
      runs: 'Sovereign frames at both carriers, beside the mediation layer.',
      agents: 'The full cast; both sides emit; the ledger deduplicates; fees land receiver-side by construction.',
      integrates: 'Mediation in production; finance reads the ledger instead of exchanging files.',
      notYet: 'The rest of the interconnect estate. One peer at production proves the pattern.',
      proof: 'A quarter closes with zero reconciliation files exchanged on this interconnect and an auditor reading both frames to the same total.',
    },
    {
      name: 'Federation',
      headline: 'Fourteen carriers, one mesh, no clearing house.',
      runs: 'Unchanged. Each new peer is a bilateral federation.',
      agents: 'Per-peer licences bound exposure; quarantine is the containment, courts are the appeal.',
      integrates: 'Each new interconnect is a signed card and a licence, not a project.',
      notYet: 'Nothing structural. Growth is peers.',
      proof: 'A misbehaving peer is quarantined within a sync cycle, and the mesh’s other thirteen corridors settle through the incident untouched.',
    },
  ],
  sequenceTitle: 'One terminated call, CDR to both ledgers',
  sequence: `sequenceDiagram
  participant Med as mediation (A)
  participant MA as metering-a
  participant TEGA as TEG A
  participant XT as cross-registry settle
  participant TEGB as TEG B (their frame)
  participant ESA as ledger A
  participant ESB as ledger B
  Med-->>MA: CDR, as today
  MA->>TEGA: settle per event (receiver-side fee)
  TEGA->>XT: cross-frame leg (idempotency key)
  XT->>TEGB: terminating side credited, exactly once
  TEGA-->>ESA: signed entry
  TEGB-->>ESB: the same signed entry
  Note over ESA,ESB: both sides emit#59; dedup on the key#59; nothing to reconcile
  Note over XT: an inflating peer is licence-suspended within a sync cycle`,
  sizing: [
    { level: 'L1', what: 'An MVNO settles through its host’s frame with agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A carrier runs metering agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'One sovereign frame per carrier, federated per interconnect', containers: 'one frame per carrier' },
  ],
}
