import type { BlueprintDeep } from '../types'

// OUROBOROS deep architecture (§18) — deposit loops that close themselves,
// custody that signs, and recovery figures that survive an audit.

export const deep: BlueprintDeep = {
  intro:
    'OUROBOROS deployed: the scheme’s frame holds the deposit escrow, the refund gate and the custody ledger; return points, haulers and processors act from their side of the fabric; the weighbridges feed the round settlements. What never comes back stays visible as unredeemed escrow instead of vanishing, and the quarterly recovery answer is a query. The trace replays one container and one collection round.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE SCHEME’S FRAME', sub: 'deposits, refunds, custody', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE LOOP OUTSIDE', sub: 'return points, haulers, processors', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'attestations and refunds cross here', x: 530, y: 435, w: 440, h: 165, kind: 'fabric' },
      { id: 'ze', label: 'THE PHYSICAL LOOP', sub: 'machines verify; scales attest', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'scheme', label: 'scheme-treasury', sub: 'refunds, issues none', kind: 'agent', x: 140, y: 135 },
      { id: 'dedup', label: 'refund gate', sub: 'one per container identity', kind: 'gate', x: 310, y: 135 },
      { id: 'es', label: 'custody ledger', sub: 'quarter is a query', kind: 'ledger', x: 310, y: 255 },
      { id: 'teg', label: 'deposit escrow', sub: 'escrowed at shipment', kind: 'teg', x: 140, y: 255 },
      { id: 'unred', label: 'unredeemed watch', sub: 'what never came back', kind: 'agent', x: 140, y: 375 },
      { id: 'round', label: 'round settlement', sub: 'paid on weight', kind: 'teg', x: 310, y: 375 },
      { id: 'retail', label: 'return-points', sub: 'verify and sign', kind: 'agent', x: 750, y: 135 },
      { id: 'r-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 890, y: 135 },
      { id: 'hauler', label: 'hauler-fleet', sub: 'signs custody', kind: 'agent', x: 750, y: 375 },
      { id: 'proc', label: 'processor-intake', sub: 'signs the gates', kind: 'agent', x: 890, y: 255 },
      { id: 'relay', label: 'custody relay', sub: 'signed handoffs in', kind: 'registry', x: 900, y: 510 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 640, y: 570 },
      { id: 'rvm', label: 'reverse vending', sub: 'returns attest', kind: 'external', x: 400, y: 692 },
      { id: 'weigh', label: 'weighbridges', sub: 'attested weight in', kind: 'external', x: 250, y: 692 },
    ],
    edges: [
      { id: 'e-rvm', from: 'rvm', to: 'relay', label: 'returns, attested', dashed: true, labelT: 0.38, curve: 66 },
      { id: 'e-deposit', from: 'scheme', to: 'teg', label: 'deposits in', labelT: 0.55 },
      { id: 'e-return', from: 'retail', to: 'relay', label: 'verified returns', labelT: 0.45 },
      { id: 'e-custody', from: 'hauler', to: 'relay', label: 'signs custody', labelT: 0.55 },
      { id: 'e-intake', from: 'proc', to: 'relay', label: 'signs intake', dashed: true, labelT: 0.4 },
      { id: 'e-relay', from: 'relay', to: 'dedup', label: 'principal checked', labelT: 0.61, curve: 33 },
      { id: 'e-refund', from: 'dedup', to: 'teg', label: 'refund, once', labelT: 0.64 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-unred', from: 'teg', to: 'unred', label: 'stays visible', dashed: true, labelT: 0.6 },
      { id: 'e-weigh', from: 'weigh', to: 'round', label: 'attested weight', dashed: true, labelT: 0.45 },
      { id: 'e-round', from: 'round', to: 'xfer', label: 'round, keyed', labelT: 0.55 },
      { id: 'e-hcredit', from: 'xfer', to: 'hauler', curve: 45 },
      { id: 'e-remit', from: 'retail', to: 'r-reg', dashed: true },
    ],
    script: [
      { edge: 'e-deposit', dwellMs: 1400, caption: 'A container ships and its deposit enters escrow. Not a liability line: escrow, on the ledger.' },
      { edge: 'e-return', dwellMs: 1400, caption: 'The container comes back. A registered return point verifies and signs.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The attestation couriers in through the fabric.' },
      { edge: 'e-refund', dwellMs: 1500, caption: 'One refund per container identity. The double-claim arrives as a refused duplicate, not a quiet loss.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'The loop closes on the ledger, append-only.' },
      { edge: 'e-unred', dwellMs: 1400, caption: 'What never returns stays visible as unredeemed escrow instead of vanishing into a reconciliation.' },
      { edge: 'e-custody', dwellMs: 1400, caption: 'Downstream, the collection round signs, the transfer station weighs and signs, the processor signs intake.' },
      { edge: 'e-weigh', dwellMs: 1300, caption: 'The weighbridge attests the tonnage. The invoice does not.' },
      { edge: 'e-round', dwellMs: 1400, caption: 'The municipal payment for the round releases against the attested weight.' },
      { edge: 'e-hcredit', dwellMs: 1300, caption: 'The hauler is credited exactly once, and the hauler who reliably delivers what it collects carries that record to the next tender.' },
      { edge: 'e-intake', dwellMs: 1300, caption: 'The processor’s intake closes the custody chain.' },
    ],
    traceLabel: 'One container and one round: refunded once, weighed honestly, visible forever.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'The loop, re-read as escrow.',
      runs: 'Nothing. One material stream redrawn as deposits, returns, custody handoffs and round payments.',
      agents: 'None. The scheme operator pins down what a verified return requires, before hardware is bought around the wrong answer.',
      integrates: 'Nothing. RVMs, scales and routes stay exactly as they are.',
      notYet: 'No escrow, no gate, no chain.',
      proof: 'One quarter’s reconciliation re-expressed as escrow flows, and the unexplained gap in the spreadsheet appears as a named, sized unredeemed balance.',
    },
    {
      name: 'Pilot',
      headline: 'One municipality, real refunds, small deposits.',
      runs: 'A single-VM frame for the scheme. Return points join with seats; one hauler enrolls.',
      agents: 'scheme-treasury, the refund gate, return-point attestors, one hauler signing custody.',
      integrates: 'RVMs feed the return points; one weighbridge feeds the round settlement.',
      notYet: 'One municipality. Processors still invoice in parallel. The PRO reads reports, not the ledger.',
      proof: 'A month of returns refunds exactly once per container identity, with every staged double-claim refused and logged.',
    },
    {
      name: 'Production',
      headline: 'The scheme at scale, the quarter as a query.',
      runs: 'One registry per scheme or authority, beside the systems that already run the routes.',
      agents: 'The full cast; haulers paid on attested weight; unredeemed escrow visible as a standing figure.',
      integrates: 'RVMs, weighbridges and route scanners feed attestors; producer responsibility reporting reads the ledger.',
      notYet: 'Environmental certification. The ledger proves custody and payment, and the regulator’s standards remain the regulator’s test.',
      proof: 'The quarterly recovery report to the PRO is produced as a query over the ledger, and an auditor reproduces it independently to the tonne.',
    },
    {
      name: 'Federation',
      headline: 'Schemes and processors as peers.',
      runs: 'Unchanged. Neighbouring schemes and large processors bring frames or seats.',
      agents: 'Hauler records travel with DIDs to the next tender; cross-scheme material flows settle like everything else.',
      integrates: 'Each new participant is a signed card and a licence.',
      notYet: 'A corrupt scale is a physical-world problem the ledger records but cannot prevent, in every phase.',
      proof: 'Material crossing two schemes settles both sides from one custody chain, with no reconciliation meeting between the operators.',
    },
  ],
  sequenceTitle: 'One container, shipment to refused double-claim',
  sequence: `sequenceDiagram
  participant Sch as scheme-treasury
  participant TEG as deposit escrow
  participant RP as return point (their frame)
  participant Fab as federation fabric
  participant Gate as refund gate
  participant ES as custody ledger
  Sch->>TEG: deposit escrowed at shipment
  RP->>Fab: return verified, signed
  Fab->>Gate: relayed, principal checked
  Gate->>TEG: refund, one per container identity
  TEG-->>ES: loop closed, append-only
  RP->>Fab: the same container, claimed again
  Fab->>Gate: relayed
  Gate-->>RP: refused duplicate, on the record
  Note over ES: what never returns stays visible as unredeemed escrow`,
  sizing: [
    { level: 'L1', what: 'Return points and small haulers join with accounts', containers: '0 of theirs' },
    { level: 'L2', what: 'A processor runs intake agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'One frame per scheme or authority', containers: '~9, one VM up' },
  ],
}
