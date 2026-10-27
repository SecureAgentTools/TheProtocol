import type { BlueprintDeep } from '../types'

// BAZAAR deep architecture (§18) — software paying software, with the
// refusal rails ready before the first sale.

export const deep: BlueprintDeep = {
  intro:
    'BAZAAR deployed: the merchant’s frame runs the storefront, the payment gate and the escrow contracts; buyers arrive from their own registries; inventory and fulfilment stay where they are, because the cart was never the hard part. The sharp edge is printed on the map: verification is a receipt check, not a work order. The trace replays one restock, first call to reputation.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE MERCHANT’S FRAME', sub: 'storefront, gate, escrow: yours', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'BUYERS EVERYWHERE', sub: 'their registries, their budgets', x: 530, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'paid exactly once', x: 530, y: 435, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE SHOP', sub: 'inventory in, fulfilment out', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'dispute', label: 'dispute-desk', sub: 'four phases, teeth', kind: 'agent', x: 110, y: 255 },
      { id: 'pgate', label: 'payment gate', sub: 'verify = receipt check', kind: 'gate', x: 330, y: 135 },
      { id: 'es', label: 'event ledger', sub: 'every paid call', kind: 'ledger', x: 330, y: 375 },
      { id: 'teg', label: 'settle once', sub: 'idempotent retries', kind: 'teg', x: 330, y: 255 },
      { id: 'store', label: 'storefront-agent', sub: 'SDK middleware', kind: 'agent', x: 110, y: 375 },
      { id: 'spine', label: 'escrow contracts', sub: 'above threshold', kind: 'gate', x: 110, y: 135 },
      { id: 'buyer', label: 'procurement', sub: 'a budget, not a card', kind: 'agent', x: 610, y: 135 },
      { id: 'b-reg', label: 'their registry', sub: 'signed card', kind: 'registry', x: 890, y: 375 },
      { id: 'rep', label: 'reputation', sub: 'from settled work', kind: 'registry', x: 750, y: 375 },
      { id: 'b-es', label: 'their ledger', sub: 'same orders', kind: 'ledger', x: 750, y: 135 },
      { id: 'xfer', label: 'cross-registry', sub: 'exactly-once', kind: 'teg', x: 700, y: 510 },
      { id: 'mesh', label: 'federation mesh', sub: 'peer cards, licenses', kind: 'registry', x: 900, y: 510 },
      { id: 'inv', label: 'inventory', sub: 'stock truth here', kind: 'external', x: 350, y: 692 },
      { id: 'fulfil', label: 'fulfilment', sub: 'releases escrow', kind: 'external', x: 200, y: 692 },
    ],
    edges: [
      { id: 'e-stock', from: 'inv', to: 'store', label: 'stock levels', dashed: true, labelT: 0.65 },
      { id: 'e-order', from: 'buyer', to: 'pgate', label: 'order + authorization', labelT: 0.55 },
      { id: 'e-pay', from: 'buyer', to: 'xfer', label: 'pays per call', curve: 33, labelT: 0.55 },
      { id: 'e-land', from: 'xfer', to: 'teg', label: 'lands home, keyed', curve: -54, labelT: 0.55 },
      { id: 'e-verify', from: 'pgate', to: 'teg', label: 'verify, settle', labelT: 0.8 },
      { id: 'e-emit', from: 'teg', to: 'es', label: 'one event', dashed: true, labelT: 0.45 },
      { id: 'e-fulfil', from: 'store', to: 'fulfil', label: 'picked + shipped', dashed: true, labelT: 0.5 },
      { id: 'e-contract', from: 'buyer', to: 'spine', label: 'escrow, above threshold', curve: 60, labelT: 0.43 },
      { id: 'e-fund', from: 'spine', to: 'teg', label: 'milestones', labelT: 0.5 },
      { id: 'e-rep', from: 'xfer', to: 'rep', dashed: true },
      { id: 'e-travel', from: 'rep', to: 'mesh', label: 'travels with the DID', dashed: true, curve: 54, labelT: 0.51 },
      { id: 'e-bemit', from: 'buyer', to: 'b-es', dashed: true },
      { id: 'e-card', from: 'b-reg', to: 'mesh', label: 'signed card', dashed: true, curve: -12, labelT: 0.36 },
      { id: 'e-disp', from: 'dispute', to: 'es', label: 'any paid call', dashed: true, labelT: 0.6 },
    ],
    script: [
      { edge: 'e-stock', dwellMs: 1300, caption: 'Inventory is where it always was. The cart was never the hard part.' },
      { edge: 'e-order', dwellMs: 1400, caption: 'A procurement agent orders a restock, carrying a payment authorization that lives fifteen minutes.' },
      { edge: 'e-pay', dwellMs: 1300, caption: 'It pays per call, in amounts too small for card rails. That is the point.' },
      { edge: 'e-land', dwellMs: 1400, caption: 'The payment lands exactly once, across any number of retries and crashes.' },
      { edge: 'e-verify', dwellMs: 1500, caption: 'The storefront verifies, then settles. A consumed authorization reports valid on a repeat verify, so verification is a receipt check, never a work order.' },
      { edge: 'e-emit', dwellMs: 1200, caption: 'Order and settlement land on the ledger.' },
      { edge: 'e-fulfil', dwellMs: 1300, caption: 'Fulfilment picks and ships. Software paid software; a warehouse still moves the box.' },
      { edge: 'e-contract', dwellMs: 1400, caption: 'Anything above threshold rides an escrowed contract instead of a bare call.' },
      { edge: 'e-fund', dwellMs: 1300, caption: 'Milestones release from escrow as the order completes.' },
      { edge: 'e-rep', dwellMs: 1300, caption: 'Reputation accrues on settled work, not on reviews.' },
      { edge: 'e-travel', dwellMs: 1300, caption: 'It travels with the agent’s DID, across every registry it will ever trade on.' },
      { edge: 'e-disp', dwellMs: 1400, caption: 'And when something is wrong, a four-phase dispute binds any paid call, with slashing behind it. No call centre appears in this drawing.' },
    ],
    traceLabel: 'One restock: paid per call, escrowed above threshold, reputation built.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'Price the calls, not the platform.',
      runs: 'Nothing. Your price list redrawn as per-call amounts and an escrow threshold.',
      agents: 'None. Commercial and engineering fight over the escrow threshold now, while it is still free to move.',
      integrates: 'Nothing. Inventory and fulfilment stay exactly as they are.',
      notYet: 'No storefront exists on the network.',
      proof: 'One month of real orders re-priced per call, and the margin comes out where finance expected it.',
    },
    {
      name: 'Pilot',
      headline: 'A storefront in an afternoon, invited buyers.',
      runs: 'A hosted registry seat for the merchant. The SDK middleware does the payment enforcement.',
      agents: 'One storefront role, invited buyer agents with budgets. The dispute desk exists and expects boredom.',
      integrates: 'Inventory read-side; fulfilment triggered by settled orders only.',
      notYet: 'Pocket prices, no strangers, escrow contracts drilled but rarely needed.',
      proof: 'A hundred paid calls settle exactly once each, including one where the buyer crashed mid-retry and was charged once anyway.',
    },
    {
      name: 'Production',
      headline: 'Open for strangers, sharp edge documented.',
      runs: 'A hosted seat still suffices; run your own frame when volume justifies walls.',
      agents: 'The full cast; reputation built on settled work; the consumed-authorization caveat enforced by middleware, not by hope.',
      integrates: 'Inventory and fulfilment in production; finance reads the ledger.',
      notYet: 'Fiat stays out unless a deployment enables purchase-only rails; most run without it.',
      proof: 'A quarter of open trading in which every dispute that was filed resolved through the four phases, and none required a human call centre.',
    },
    {
      name: 'Federation',
      headline: 'Buyers arrive from everywhere.',
      runs: 'Unchanged. Buyer registries federate as they come.',
      agents: 'Reputations travel in with DIDs; budgets stay the buyers’ problem, ceilings stay theirs too.',
      integrates: 'Each new marketplace corridor is a signed card and a license.',
      notYet: 'Nothing structural. Growth is buyers.',
      proof: 'A stranger’s agent, never seen before, completes a first paid call and an escrowed order in the same afternoon with zero manual onboarding.',
    },
  ],
  sequenceTitle: 'One paid call, authorization to receipt',
  sequence: `sequenceDiagram
  participant Buy as procurement-agent (their frame)
  participant Gate as payment gate
  participant XT as cross-registry pay
  participant TEG as merchant TEG
  participant Store as storefront-agent
  participant ES as event ledger
  Buy->>Gate: order + apt_ authorization (15 min TTL)
  Buy->>XT: pay per call (idempotency key)
  XT->>TEG: settle, exactly once
  Gate-->>Store: verified: authorization consumed
  Store->>Store: perform the work, once
  TEG-->>ES: order + settlement, append-only
  Note over Gate: a repeat verify still says valid: receipt check, never a work order
  Note over TEG: above threshold, the same order rides an escrowed contract instead`,
  sizing: [
    { level: 'L1', what: 'Merchant and buyers on existing registries, agents only', containers: '0 of yours' },
    { level: 'L2', what: 'The storefront via the SDK against a hosted seat', containers: 'your agents only' },
    { level: 'L3', what: 'Your own frame when volume justifies your own walls', containers: '~9, one VM up' },
  ],
}
