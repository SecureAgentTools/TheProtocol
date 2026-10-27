import type { BlueprintDeep } from '../types'

// MERIDIAN deep architecture (§18) — autonomous treasury on a sovereign frame.

export const deep: BlueprintDeep = {
  intro:
    'This is the shape MERIDIAN takes in a real estate: your sovereign frame beside a counterparty frame, the federation fabric between them, and your existing systems underneath. Nothing here is a box drawn for a slide. Every zone is a deployment, every edge is a rail that exists, and the trace below replays the transaction the page has been describing all along.',
  arch: {
    zones: [
      { id: 'zf', label: 'YOUR SOVEREIGN FRAME', sub: 'registry, TEG, ledger, identity: under your law', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'COUNTERPARTY FRAME', sub: 'their deployment, their law', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'mTLS, signed cards, licenses', x: 530, y: 440, w: 440, h: 170, kind: 'fabric' },
      { id: 'ze', label: 'YOUR EXISTING SYSTEMS', sub: 'untouched, fed by evidence', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'treasurer', label: 'treasurer', sub: 'mandate, presence', kind: 'human', x: 140, y: 135 },
      { id: 'gate', label: 'authority gate', sub: 'roles + mandate', kind: 'gate', x: 310, y: 133 },
      { id: 'desk', label: 'swap-desk', sub: 'executes FX routes', kind: 'agent', x: 140, y: 255 },
      { id: 'teg', label: 'TEG escrow', sub: 'atomic budget debits', kind: 'teg', x: 310, y: 255 },
      { id: 'es', label: 'event ledger', sub: 'append-only', kind: 'ledger', x: 310, y: 375 },
      { id: 'sentinel', label: 'sentinel', sub: 'proposes only', kind: 'agent', x: 140, y: 375 },
      { id: 'p-teg', label: 'their TEG', sub: 'credits exactly once', kind: 'teg', x: 690, y: 255 },
      { id: 'p-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 860, y: 255 },
      { id: 'p-desk', label: 'their desk', sub: 'confirms the leg', kind: 'agent', x: 690, y: 135 },
      { id: 'p-es', label: 'their ledger', sub: 'same truth', kind: 'ledger', x: 860, y: 135 },
      { id: 'router', label: 'FX settlement', sub: 'idempotency-keyed', kind: 'teg', x: 720, y: 560 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 880, y: 560 },
      { id: 'market', label: 'market data', sub: 'read-side feed', kind: 'external', x: 240, y: 692 },
      { id: 'erp', label: 'ERP / books', sub: 'journals post back', kind: 'external', x: 395, y: 692 },
    ],
    edges: [
      { id: 'e-signal', from: 'market', to: 'sentinel', label: 'prices in', dashed: true },
      { id: 'e-propose', from: 'sentinel', to: 'desk', dashed: true },
      { id: 'e-mandate', from: 'treasurer', to: 'gate', label: 'mandate', dashed: true },
      { id: 'e-check', from: 'desk', to: 'gate', label: 'authority, re-derived', dashed: true, labelT: 0.35 },
      { id: 'e-escrow', from: 'desk', to: 'teg' },
      { id: 'e-emit', from: 'teg', to: 'es', label: 'one event', dashed: true },
      { id: 'e-settle', from: 'teg', to: 'router', label: 'settle, keyed', curve: 20, labelT: 0.75 },
      { id: 'e-credit', from: 'router', to: 'p-teg', label: 'credit exactly once' },
      { id: 'e-pleg', from: 'p-teg', to: 'p-desk', label: 'counter-leg' },
      { id: 'e-pemit', from: 'p-desk', to: 'p-es', dashed: true },
      { id: 'e-card', from: 'p-reg', to: 'mesh', label: 'signed card', dashed: true },
      { id: 'e-evidence', from: 'es', to: 'erp', label: 'evidence export', dashed: true },
    ],
    script: [
      { edge: 'e-signal', dwellMs: 1300, caption: 'Market data feeds the sentinel. It watches floors and ceilings; it cannot move a unit.' },
      { edge: 'e-propose', dwellMs: 1300, caption: 'The sentinel proposes a rebalance to the desk. A proposal is not an order.' },
      { edge: 'e-mandate', dwellMs: 1400, caption: 'The treasurer’s mandate stands behind the desk: scope, ceiling, presence.' },
      { edge: 'e-check', dwellMs: 1400, caption: 'The desk’s authority is checked at the gate on this very request: roles, spend policy, the mandate’s clamp.' },
      { edge: 'e-escrow', dwellMs: 1500, caption: 'Approved. The desk escrows the route; its daily budget debits atomically.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'One movement, one event, append-only.' },
      { edge: 'e-settle', dwellMs: 1500, caption: 'The leg crosses the fabric with an idempotency key. A retry can never double it.' },
      { edge: 'e-credit', dwellMs: 1500, caption: 'The counterparty frame credits exactly once, under its own law.' },
      { edge: 'e-pleg', dwellMs: 1200, caption: 'Their desk confirms the counter-leg.' },
      { edge: 'e-pemit', dwellMs: 1200, caption: 'Their ledger writes the same settlement. Two sovereign books, one truth.' },
      { edge: 'e-evidence', dwellMs: 1500, caption: 'Evidence exports to your books as signed events, not screenshots.' },
    ],
    traceLabel: 'One mandated FX rebalance, signal to evidence.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Nothing of yours changes yet.',
      runs: 'Nothing in your estate. A workstation and a read-only account on the public network.',
      agents: 'None. Your team walks the tutorial tracks and reads a live ledger.',
      integrates: 'Nothing. The ERP, the OMS and the banks stay exactly as they are.',
      notYet: 'No money, no mandates, no frame.',
      proof: 'Your team executes one sandbox transfer end to end and reads it back from the event ledger without asking anyone.',
    },
    {
      name: 'Pilot',
      headline: 'The desk exists, at pocket size.',
      runs: 'One hosted registry seat, or a 9-container frame on a single VM if policy requires walls from day one.',
      agents: 'liquidity-sentinel and swap-desk under IRONKEY roles; the treasurer holds a Cockpit mandate with pilot ceilings.',
      integrates: 'Order intents in via the SDK; evidence exports to a review folder beside the ERP.',
      notYet: 'No production funds. Ceilings at pocket size. No external counterparty.',
      proof: 'A month of paper flow in which every movement reconciles from the event ledger alone, with zero manual corrections.',
    },
    {
      name: 'Production',
      headline: 'Your frame, your law, real ceilings.',
      runs: 'A sovereign frame in your datacenter: registry, TEG, EventStore, identity fabric.',
      agents: 'The full cast under liability clamps; every agent mTLS-attested; the reconciler reads and can never move.',
      integrates: 'ERP receives signed evidence continuously; market data feeds the sentinel; the OMS submits intents.',
      notYet: 'One settlement corridor only. The federation license is held; the wider mesh stays dark on purpose.',
      proof: 'The first production corridor settles with a supply delta of zero on both frames, independently audited.',
    },
    {
      name: 'Federation',
      headline: 'Growth becomes configuration.',
      runs: 'Unchanged infrastructure. More peers.',
      agents: 'Unchanged cast; per-corridor spend policies bound what each counterparty can reach.',
      integrates: 'Each new counterparty is a signed card and a license, not an integration project.',
      notYet: 'Nothing on this path requires new software.',
      proof: 'N corridors, one invariant: every frame’s books balance to zero drift, continuously, in public.',
    },
  ],
  sequenceTitle: 'The settlement path, as messages',
  sequence: `sequenceDiagram
  participant OMS as OMS / intent
  participant Desk as swap-desk
  participant Gate as authority gate
  participant TEG as your TEG
  participant Fab as federation fabric
  participant PTEG as their TEG
  participant ES as event ledger
  OMS->>Desk: order intent (pair, size)
  Desk->>Gate: authority check (roles, mandate)
  Gate-->>Desk: clamped approval
  Desk->>TEG: escrow leg (idempotency key)
  TEG-->>ES: escrow event, append-only
  TEG->>Fab: cross-frame settle
  Fab->>PTEG: credit, exactly once
  PTEG-->>Fab: confirmation
  Fab->>TEG: settled
  TEG-->>ES: settlement + evidence chain
  ES-->>OMS: signed evidence export`,
  sizing: [
    { level: 'L1', what: 'Use the network: your agents live on existing registries', containers: '0 of yours' },
    { level: 'L2', what: 'Run the desk: your agent runtimes via the SDK, registry hosted', containers: 'your agents only' },
    { level: 'L3', what: 'Sovereign frame: registry, TEG, EventStore, identity fabric under your law', containers: 'a full frame, one VM up' },
  ],
}
