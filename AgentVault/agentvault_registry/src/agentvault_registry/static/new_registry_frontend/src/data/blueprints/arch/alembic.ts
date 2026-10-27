import type { BlueprintDeep } from '../types'

// ALEMBIC deep architecture (§18, frontier wave 2026-09-25): a self-driving lab campaign whose robot
// time is booked across labs on their own frames, paid per run on the instrument's own signature.

export const deep: BlueprintDeep = {
  intro:
    'ALEMBIC deployed: the campaign’s frame holds the PI’s mandate, the run escrow and the result ledger; the labs sell robot time from their own frames; the instruments, the reagents and the LIMS stay where they are, signed at the edges. The trace replays one round of campaign 17, from the mandate to the preserved result.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE CAMPAIGN FRAME', sub: 'mandate, escrow, results', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE LABS', sub: 'their own frames', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'runs, money', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE BENCH', sub: 'instruments, records', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'planner', label: 'campaign-planner', sub: 'proposes each round', kind: 'agent', x: 140, y: 135 },
      { id: 'mandate', label: 'campaign mandate', sub: 'scope, re-derived', kind: 'gate', x: 310, y: 133 },
      { id: 'pi', label: 'Dr Okafor', sub: 'PI, device key', kind: 'human', x: 140, y: 255 },
      { id: 'teg', label: 'run escrow', sub: 'paid per signed run', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'result ledger', sub: 'runs, replayable', kind: 'ledger', x: 140, y: 375 },
      { id: 'procure', label: 'procurement-desk', sub: 'three suppliers only', kind: 'agent', x: 310, y: 375 },
      { id: 'booking', label: 'booking desk', sub: 'Leuven, robot time', kind: 'agent', x: 690, y: 135 },
      { id: 'l-es', label: 'lab ledger', sub: 'same runs, same keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'handler', label: 'handler-LEU-3', sub: 'signs each run', kind: 'agent', x: 655, y: 300 },
      { id: 'cycler', label: 'cycler-BAS-7', sub: 'signs the results', kind: 'agent', x: 885, y: 300 },
      { id: 'relay', label: 'run relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pay once, with FX', kind: 'teg', x: 880, y: 490 },
      { id: 'lims', label: 'LIMS, notebooks', sub: 'sample and lot ids', kind: 'external', x: 195, y: 692 },
      { id: 'supplier', label: 'suppliers', sub: 'their own screening', kind: 'external', x: 360, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'pi', to: 'mandate', label: 'mandate', curve: -20, labelT: 0.6 },
      { id: 'e-propose', from: 'planner', to: 'mandate' },
      { id: 'e-book', from: 'mandate', to: 'booking', label: 'robot time, booked' },
      { id: 'e-fund', from: 'mandate', to: 'teg' },
      { id: 'e-order', from: 'procure', to: 'supplier', label: 'reagents, allowlisted', labelT: 0.55 },
      { id: 'e-run', from: 'handler', to: 'relay', label: 'run, signed', labelT: 0.5 },
      { id: 'e-results', from: 'cycler', to: 'relay', label: 'results, signed', labelT: 0.5 },
      { id: 'e-relay', from: 'relay', to: 'teg', label: 'principal checked', labelT: 0.62 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', labelT: 0.3 },
      { id: 'e-paid', from: 'xfer', to: 'booking', label: 'paid at home', labelT: 0.62 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-lemit', from: 'booking', to: 'l-es', dashed: true, curve: 26 },
      { id: 'e-lims', from: 'lims', to: 'es', label: 'refs in every run', dashed: true, labelT: 0.45 },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Dr Okafor funds campaign 17’s purse and underwrites it once, with her device key, for ninety days.' },
      { edge: 'e-propose', dwellMs: 1300, caption: 'The planner reads the last round and proposes the next 24 formulations.' },
      { edge: 'e-book', dwellMs: 1400, caption: 'The planner, the campaign’s sub-agent, books four hours of the Leuven handler, run by run, each booking checked against her mandate.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Each run is escrowed at booking, on the campaign’s frame.' },
      { edge: 'e-order', dwellMs: 1400, caption: 'The procurement desk orders reagents from the three listed suppliers only. Their own screening still applies.' },
      { edge: 'e-run', dwellMs: 1500, caption: 'The handler signs each run with its own identity: what it mixed, from which lot, under which protocol version.' },
      { edge: 'e-results', dwellMs: 1400, caption: 'In Basel the cycler signs the cells’ results.' },
      { edge: 'e-relay', dwellMs: 1400, caption: 'The signed runs cross the fabric; the relaying peer is a courier, never the principal.' },
      { edge: 'e-release', dwellMs: 1400, caption: 'Each signed run releases its payment exactly once.' },
      { edge: 'e-paid', dwellMs: 1300, caption: 'The lab is paid on its own frame, in its own currency.' },
      { edge: 'e-emit', dwellMs: 1500, caption: 'The ledger keeps every run, positive or negative, with its provenance. A result no instrument signed never arrives.' },
    ],
    traceLabel: 'One round: mandated, booked, run, signed, paid, preserved.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One past campaign, re-read as bookings.',
      runs: 'Nothing. One finished campaign redrawn as a mandate, bookings, run attestations and payments.',
      agents: 'None. The PI and the lab manager argue about what a run report must say, which is exactly where that argument belongs.',
      integrates: 'Nothing. The LIMS, the scheduler and purchasing stay exactly as they are.',
      notYet: 'No escrow exists. No instrument signs anything.',
      proof: 'The past campaign replayed on paper, and the PI and the lab agree where every run, every payment and every refusal would have landed.',
    },
    {
      name: 'Pilot',
      headline: 'One lab, one instrument, pilot budgets.',
      runs: 'A hosted registry seat. No frame of the campaign’s own yet.',
      agents: 'The planner, the lab’s booking desk and one instrument agent on the handler.',
      integrates: 'The handler’s driver emits a signed run report with the LIMS sample and protocol references.',
      notYet: 'One lab, one currency, a small mandate. The cycler still reports by spreadsheet.',
      proof: 'A week of runs, each paid once on the instrument’s signature, and one deliberately off-list order refused and recorded.',
    },
    {
      name: 'Production',
      headline: 'The campaign’s own frame.',
      runs: 'The campaign frame: registry, TEG, event store, identity fabric, on the institute’s hardware.',
      agents: 'The full cast: planner, procurement desk, one agent per instrument in both labs, the PI’s mandate live.',
      integrates: 'LIMS references in every attestation; purchasing reads settlement instead of receipts.',
      notYet: 'A lab in another currency. One campaign proves itself first.',
      proof: 'An audit replays the campaign from the ledger and the LIMS references, and every paid run matches an instrument signature.',
    },
    {
      name: 'Federation',
      headline: 'Labs bring their own frames.',
      runs: 'Unchanged. Labs federate their own frames bilaterally and sell robot time from them.',
      agents: 'Each lab’s booking desk and instruments act from home; their track records travel with their identities.',
      integrates: 'Each new lab is a signed card and a licence, not a master services agreement per campaign.',
      notYet: 'Nothing structural. Growth is labs, instruments and campaigns.',
      proof: 'A new lab sells its first run to the campaign in its first week without a bilateral integration project.',
    },
  ],
  sequenceTitle: 'One run, booking to preserved result',
  sequence: `sequenceDiagram
  participant PI as Dr Okafor (device key)
  participant Pl as campaign-planner
  participant Man as campaign mandate
  participant TEG as run escrow
  participant Lab as handler-LEU-3 (lab frame)
  participant ES as result ledger
  PI->>Man: mandate for campaign 17, ninety days
  Pl->>Man: book the next 24 runs
  Man->>TEG: escrow per run, inside the mandate
  Lab->>TEG: run 42 signed: mix, lot, protocol version
  TEG-->>Lab: release, exactly once
  TEG-->>ES: run and payment, append-only
  Note over Man: an off-list supplier is refused before any escrow
  Note over ES: a negative round is as durable as a positive one`,
  sizing: [
    { level: 'L1', what: 'Scientists join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'A lab runs its instrument agents against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'The campaign’s own frame, and each lab’s, federated', containers: 'a full frame each' },
  ],
}
