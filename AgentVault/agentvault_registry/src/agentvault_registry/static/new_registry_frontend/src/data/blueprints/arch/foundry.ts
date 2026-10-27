import type { BlueprintDeep } from '../types'

// FOUNDRY LINE deep architecture (§18) — cells as economic actors, canaries
// proving the rails, and safety systems that never meet this network.

export const deep: BlueprintDeep = {
  intro:
    'FOUNDRY LINE deployed: the plant’s frame runs the capacity market, the shift authority and the kill switch; tooling and maintenance suppliers settle from their own registries; the MES keeps scheduling, and the safety systems stay air-gapped on their own island of this drawing, connected to nothing here on purpose. The trace replays one shift, slack sold to money frozen.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE PLANT’S FRAME', sub: 'one registry per plant, cells enrolled', x: 30, y: 50, w: 440, h: 390, kind: 'frame' },
      { id: 'zp', label: 'SUPPLIER REGISTRIES', sub: 'tooling and maintenance, their law', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'consignment settles here', x: 530, y: 440, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE SHOP FLOOR', sub: 'MES in. Safety systems: air-gapped, no edges, by design', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'operator', label: 'line operator', sub: 'freeze + suspend', kind: 'human', x: 140, y: 255 },
      { id: 'canary', label: 'canary runner', sub: 'proves the rails', kind: 'agent', x: 140, y: 135 },
      { id: 'teg', label: 'capacity market', sub: 'A2A, exactly-once', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'event ledger', sub: 'append-only', kind: 'ledger', x: 310, y: 135 },
      { id: 'cell', label: 'mill-cell-12', sub: 'SPIFFE workload', kind: 'agent', x: 310, y: 375 },
      { id: 'gate', label: 'shift authority', sub: 'L4: one cell, one shift', kind: 'gate', x: 140, y: 375 },
      { id: 'tool', label: 'tooling-supplier', sub: 'consignment stock', kind: 'agent', x: 860, y: 135 },
      { id: 't-reg', label: 'registry', sub: 'signed card', kind: 'registry', x: 860, y: 375 },
      { id: 'maint', label: 'maintenance-svc', sub: 'sells repairs', kind: 'agent', x: 690, y: 255 },
      { id: 't-es', label: 'their ledger', sub: 'same settlements', kind: 'ledger', x: 690, y: 135 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 700, y: 525 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 850, y: 525 },
      { id: 'mes', label: 'MES / scheduler', sub: 'work orders in', kind: 'external', x: 390, y: 692 },
      { id: 'safety', label: 'safety systems', sub: 'no link, by design', kind: 'external', x: 150, y: 692 },
    ],
    edges: [
      { id: 'e-mes', from: 'mes', to: 'cell', label: 'jobs in', dashed: true },
      { id: 'e-scope', from: 'cell', to: 'gate', label: 'L4: one shift', dashed: true, curve: 36, labelT: 0.4 },
      { id: 'e-sell', from: 'cell', to: 'teg', label: 'sells slack', curve: -12, labelT: 0.6 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true },
      { id: 'e-order', from: 'teg', to: 'xfer', label: 'inserts, per use', curve: 20, labelT: 0.6 },
      { id: 'e-credit', from: 'xfer', to: 'tool', label: 'credit exactly once' },
      { id: 'e-mcredit', from: 'xfer', to: 'maint', label: 'repairs paid', labelT: 0.55 },
      { id: 'e-temit', from: 'maint', to: 't-es', dashed: true },
      { id: 'e-treg', from: 'tool', to: 't-reg', dashed: true },
      { id: 'e-card', from: 't-reg', to: 'mesh', label: 'signed card', dashed: true, curve: -12, labelT: 0.4 },
      { id: 'e-canary', from: 'canary', to: 'teg', label: 'synthetic, same rails' },
      { id: 'e-judge', from: 'canary', to: 'es', label: 'judged end to end', dashed: true, curve: -30 },
      { id: 'e-freeze', from: 'operator', to: 'teg', dashed: true },
    ],
    script: [
      { edge: 'e-mes', dwellMs: 1300, caption: 'Jobs arrive from the MES. The scheduler still schedules; it just stops pretending to be a market.' },
      { edge: 'e-scope', dwellMs: 1400, caption: 'The cell’s authority is a capability permit: one cell, one shift, a parts budget that dies at shift end.' },
      { edge: 'e-sell', dwellMs: 1400, caption: 'Mill-cell-12 finishes early and sells the slack to the neighbouring line.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'The trade lands on the ledger, append-only.' },
      { edge: 'e-order', dwellMs: 1400, caption: 'The tool changer buys inserts against the shift budget. Consignment stock bills itself.' },
      { edge: 'e-credit', dwellMs: 1300, caption: 'The supplier’s frame credits exactly once, across any number of retries.' },
      { edge: 'e-mcredit', dwellMs: 1300, caption: 'A repair is bought from whoever is free, inside declared ceilings.' },
      { edge: 'e-temit', dwellMs: 1200, caption: 'Their ledgers write the same settlements.' },
      { edge: 'e-canary', dwellMs: 1400, caption: 'A robot cannot eyeball a payment rail, so canaries run the same paths real money takes.' },
      { edge: 'e-judge', dwellMs: 1300, caption: 'Judged end to end. A degraded rail is a red light on a board, not a surprise in a settlement.' },
      { edge: 'e-freeze', dwellMs: 1500, caption: 'And when something is wrong: one action freezes the money plant-wide. The safety systems, air-gapped below, never met this network.' },
    ],
    traceLabel: 'One shift: slack sold, inserts bought, rails proven, money freezable.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'The line as a market, on paper.',
      runs: 'Nothing. One line’s shift plan redrawn as budgets, ceilings and trades.',
      agents: 'None. Production engineering argues about the ceilings; the argument surfaces what the scheduler has been hiding.',
      integrates: 'Nothing. The MES, the scheduler and every safety system stay exactly as they are.',
      notYet: 'No cell holds an identity. Nothing settles.',
      proof: 'One week of the scheduler’s decisions re-told as trades between cells, and the plan agrees with what actually ran.',
    },
    {
      name: 'Pilot',
      headline: 'Six cells, one market, pocket budgets.',
      runs: 'A single-VM frame at the plant. Six cells enroll through the identity fabric.',
      agents: 'Cell and tooling roles under shift permits; the line operator holds freeze and suspend; canaries run from day one.',
      integrates: 'The MES feeds jobs read-side. Consignment billing is shadowed against the old process.',
      notYet: 'Pocket budgets. No external suppliers settle yet. Safety systems untouched, forever.',
      proof: 'A month of pilot trades in which the shift-end permit expiry is proven: the night shift demonstrably cannot spend the morning’s budget.',
    },
    {
      name: 'Production',
      headline: 'Sixty cells, suppliers settling, kill switch armed.',
      runs: 'One sovereign frame per plant: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast; every machine identity renews itself and revokes in under a second; canaries judge every live path continuously.',
      integrates: 'MES and scheduler in production; tooling and maintenance suppliers federate bilaterally.',
      notYet: 'Cross-plant capacity trading. Each plant’s market stands alone first.',
      proof: 'A freeze drill stops all settlement plant-wide in one action, and the resumed ledger shows a clean gap, not a mess.',
    },
    {
      name: 'Federation',
      headline: 'Plants trade capacity like cells do.',
      runs: 'Unchanged. Plant frames peer bilaterally.',
      agents: 'Per-corridor policies bound what each plant can buy from another.',
      integrates: 'Each new plant or supplier is a signed card and a license.',
      notYet: 'Nothing on this path requires new software.',
      proof: 'Two plants balance a capacity crunch across sites with settlements their controllers reconcile from the ledger alone.',
    },
  ],
  sequenceTitle: 'One insert, consignment to credit',
  sequence: `sequenceDiagram
  participant Cell as mill-cell-12
  participant Gate as shift authority (L4)
  participant TEG as plant TEG
  participant XT as cross-registry pay
  participant Sup as tooling supplier (their frame)
  participant ES as event ledger
  Cell->>Gate: buy inserts (permit: one cell, one shift)
  Gate-->>Cell: clamped approval, budget debits
  Cell->>TEG: A2A payment, per insert
  TEG-->>ES: settlement, append-only
  TEG->>XT: pay supplier (idempotency key)
  XT->>Sup: their TEG credits, exactly once
  Note over Gate: at shift end the permit dies#59; the budget dies with it
  Note over TEG: canaries run this same path continuously and are judged`,
  sizing: [
    { level: 'L1', what: 'Suppliers join with accounts and agents only', containers: '0 of theirs' },
    { level: 'L2', what: 'The plant runs cell agents against a hosted registry seat', containers: 'agents only' },
    { level: 'L3', what: 'A sovereign frame per plant, cells enrolled through the fabric', containers: 'one frame per plant' },
  ],
}
