import type { BlueprintDeep } from '../types'

// BULWARK deep architecture (§18) — utilities that coordinate through
// escrow, prove their rails hourly, and degrade on purpose.

export const deep: BlueprintDeep = {
  intro:
    'BULWARK deployed: one utility’s sovereign deployment on the left, the region’s peers on the right, mutual aid settling between them through escrowed agreements. The canary fleet proves the rails continuously, the duty officer holds a break-glass no API can lift, and OT sits below with no wires into any of it, because this layer coordinates and settles and never actuates. The trace replays a good week and the start of a bad day.',
  arch: {
    zones: [
      { id: 'zf', label: 'ONE UTILITY’S DEPLOYMENT', sub: 'water board: sovereign, island-capable', x: 30, y: 50, w: 440, h: 460, kind: 'frame' },
      { id: 'zp', label: 'THE REGION’S PEERS', sub: 'power, municipal, each sovereign', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'mutual aid settles here', x: 530, y: 455, w: 440, h: 115, kind: 'fabric' },
      { id: 'ze', label: 'THE PHYSICAL NETWORKS', sub: 'OT and SCADA: air-gapped, no edges, by design', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'duty', label: 'duty-officer', sub: 'holds break-glass', kind: 'human', x: 140, y: 135 },
      { id: 'breaker', label: 'break-glass', sub: 'no API to lift it', kind: 'gate', x: 310, y: 133 },
      { id: 'es', label: 'utility ledger', sub: 'auditor still reads', kind: 'ledger', x: 140, y: 255 },
      { id: 'teg', label: 'aid escrow', sub: 'agreements, funded', kind: 'teg', x: 310, y: 255 },
      { id: 'canary', label: 'canary fleet', sub: 'proves the rails', kind: 'agent', x: 140, y: 470 },
      { id: 'aiddesk', label: 'mutual-aid desk', sub: 'crews and capacity', kind: 'agent', x: 310, y: 375 },
      { id: 'power', label: 'power-grid ops', sub: 'neighbour utility', kind: 'agent', x: 690, y: 135 },
      { id: 'p-reg', label: 'their deployment', sub: 'signed card', kind: 'registry', x: 775, y: 375 },
      { id: 'coord', label: 'coordinator', sub: 'proposes only', kind: 'agent', x: 860, y: 255 },
      { id: 'p-es', label: 'their ledger', sub: 'same settlements', kind: 'ledger', x: 860, y: 135 },
      { id: 'xfer', label: 'cross-frame pay', sub: 'idempotency-keyed', kind: 'teg', x: 680, y: 527 },
      { id: 'mesh', label: 'federation mesh', sub: 'a frame can island', kind: 'registry', x: 900, y: 527 },
      { id: 'ot', label: 'OT / SCADA', sub: 'never actuated here', kind: 'external', x: 150, y: 692 },
      { id: 'crews', label: 'crews, equipment', sub: 'the real work', kind: 'external', x: 330, y: 692 },
    ],
    edges: [
      { id: 'e-crew', from: 'crews', to: 'aiddesk', label: 'the real work', dashed: true, labelT: 0.45 },
      { id: 'e-claim', from: 'aiddesk', to: 'teg', label: 'on delivery', labelT: 0.5 },
      { id: 'e-fund', from: 'duty', to: 'teg', label: 'escrowed aid', curve: 22, labelT: 0.4 },
      { id: 'e-propose', from: 'coord', to: 'mesh', label: 'proposes aid', dashed: true, labelT: 0.55 },
      { id: 'e-canary', from: 'canary', to: 'xfer', label: 'live paths, hourly', labelT: 0.5 },
      { id: 'e-judge', from: 'canary', to: 'es', label: 'judged', dashed: true, labelT: 0.5 },
      { id: 'e-xset', from: 'teg', to: 'xfer', label: 'settle, keyed', curve: 26, labelT: 0.63 },
      { id: 'e-credit', from: 'xfer', to: 'power', label: 'credit exactly once', curve: 4, labelT: 0.5 },
      { id: 'e-pemit', from: 'power', to: 'p-es', dashed: true },
      { id: 'e-card', from: 'p-reg', to: 'mesh', label: 'signed card', dashed: true, labelT: 0.5 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 20 },
      { id: 'e-freeze', from: 'duty', to: 'breaker', label: 'one switch', dashed: true },
      { id: 'e-frozen', from: 'breaker', to: 'teg', label: 'writes stop', labelT: 0.78 },
    ],
    script: [
      { edge: 'e-propose', dwellMs: 1400, caption: 'The region coordinator structures mutual aid. It proposes and funds; it cannot force a peer’s books.' },
      { edge: 'e-fund', dwellMs: 1400, caption: 'The water board escrows the agreement: crews and capacity, within declared limits.' },
      { edge: 'e-crew', dwellMs: 1300, caption: 'The real work happens with real crews. This layer never touches a valve.' },
      { edge: 'e-claim', dwellMs: 1300, caption: 'The aid desk claims on delivery, against the escrow.' },
      { edge: 'e-xset', dwellMs: 1400, caption: 'Settlement crosses to the neighbour with an idempotency key.' },
      { edge: 'e-credit', dwellMs: 1300, caption: 'The power utility’s deployment credits exactly once, under its own governance.' },
      { edge: 'e-pemit', dwellMs: 1200, caption: 'Their ledger writes the same settlement.' },
      { edge: 'e-canary', dwellMs: 1400, caption: 'On the good days, canaries run the live paths hourly. "The rails work" is a measurement, not a binder.' },
      { edge: 'e-judge', dwellMs: 1300, caption: 'Judged end to end, on a board someone actually watches.' },
      { edge: 'e-freeze', dwellMs: 1500, caption: 'The bad day: a suspected compromise. The duty officer flips the break-glass, once.' },
      { edge: 'e-frozen', dwellMs: 1600, caption: 'Every write and every scheduled job freezes; reads, sign-in and the ledger auditor keep working, because an operator who freezes a system must not go blind inside it. There is no API to lift the freeze, on purpose.' },
      { edge: 'e-card', dwellMs: 1500, caption: 'If the region’s links look wrong, a deployment islands itself and runs standalone. Rejoining is not declared but re-verified: the supply invariant is checked before anyone trusts the books again.' },
    ],
    traceLabel: 'A good week, then the break-glass: aid settled, rails proven, freeze held.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Mutual aid, re-read as agreements.',
      runs: 'Nothing. Last storm season’s mutual aid redrawn as escrowed agreements and delivery attestations.',
      agents: 'None. Emergency managers define what counts as delivered aid in daylight, before the storm asks.',
      integrates: 'Nothing. OT, SCADA and the radio room stay exactly as they are, in this phase and all others.',
      notYet: 'No deployment, no escrow, no canaries.',
      proof: 'One historical aid event re-expressed as agreements and settlements, and both utilities agree the telling matches what was owed.',
    },
    {
      name: 'Pilot',
      headline: 'Two utilities, one corridor, drills only.',
      runs: 'A single-VM deployment at each of two utilities, federated bilaterally. Island mode exercised monthly.',
      agents: 'utility-ops and the aid desk on each side; the canary fleet from day one; each duty officer holds a drilled break-glass.',
      integrates: 'Crew rosters and equipment lists read-side. Nothing actuates, ever.',
      notYet: 'Pocket settlements. The region coordinator observes rather than structures.',
      proof: 'A freeze drill on one deployment stops its writes in one action while its auditor keeps reading, and the partner utility’s operations never notice.',
    },
    {
      name: 'Production',
      headline: 'The region’s utilities, coordinated and freezable.',
      runs: 'One sovereign deployment per utility, island-capable standalone mode standard.',
      agents: 'The full cast per utility; canaries prove every corridor hourly; break-glass procedures on the wall, not in a wiki.',
      integrates: 'Mutual aid, equipment sharing and capacity settle from escrow; OT remains air-gapped and out of scope.',
      notYet: 'Wide-area automation. This layer coordinates and settles; it never actuates, and that is permanent.',
      proof: 'A regional exercise runs aid across three utilities with one deliberately islanded mid-exercise, and its rejoin passes supply re-verification before any settlement resumes.',
    },
    {
      name: 'Federation',
      headline: 'A region that degrades on purpose.',
      runs: 'Unchanged. More utilities, more corridors.',
      agents: 'Per-corridor limits bound every relationship; the coordinator proposes across all of them.',
      integrates: 'Each new utility is a signed card and a licence.',
      notYet: 'Defence and military applications, deliberately and permanently out of scope for this catalogue.',
      proof: 'The region’s resilience report cites measured canary uptime and drill outcomes from the ledgers, not attestations from memory.',
    },
  ],
  sequenceTitle: 'One aid settlement, and the freeze that outranks it',
  sequence: `sequenceDiagram
  participant Co as region-coordinator
  participant WU as water utility (its own frame)
  participant TEG as mutual-aid escrow
  participant XT as cross-registry settle
  participant PU as power utility (frame B)
  participant Duty as duty-officer
  Co->>WU: proposes aid (cannot force)
  WU->>TEG: escrow the agreement
  TEG->>XT: settle on delivery (idempotency key)
  XT->>PU: credited exactly once
  Duty->>WU: break-glass, one switch
  Note over WU: writes freeze#59; reads and the auditor keep working
  Note over WU: no API lifts the freeze#59; rejoin is re-verified, not declared`,
  sizing: [
    { level: 'L1', what: 'A small district joins a host utility’s deployment', containers: '0 of theirs' },
    { level: 'L2', what: 'A utility runs its desks against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'One island-capable sovereign deployment per utility', containers: 'one frame per utility' },
  ],
}
