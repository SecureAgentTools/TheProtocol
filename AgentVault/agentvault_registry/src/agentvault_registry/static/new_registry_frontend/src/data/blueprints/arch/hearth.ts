import type { BlueprintDeep } from '../types'

// HEARTH deep architecture (§18, frontier wave 2026-09-25): one household's errands on its own frame or hosted
// seat, one evening repair traced from Mira's mandate to a release her thumb approved, the plumber on her own registry.

export const deep: BlueprintDeep = {
  intro:
    'HEARTH deployed: the household’s frame, or its seat on a hosted registry, holds the steward’s purse, Mira’s mandate, the job escrow and the ledger; tradespeople act from their own registries; the family calendar reads bookings by reference, and the bank stays outside with no link at all. The trace replays one evening repair, from the mandate to the preserved release.',
  arch: {
    zones: [
      { id: 'zf', label: 'THE HOUSEHOLD’S FRAME', sub: 'purse, mandate, escrow, ledger', x: 30, y: 50, w: 440, h: 360, kind: 'frame' },
      { id: 'zp', label: 'THE TRADES', sub: 'each on its own registry', x: 530, y: 50, w: 440, h: 340, kind: 'frame' },
      { id: 'zx', label: 'FEDERATION FABRIC', sub: 'bookings, pay', x: 530, y: 430, w: 440, h: 150, kind: 'fabric' },
      { id: 'ze', label: 'THE HOUSE', sub: 'calendar in, bank out', x: 30, y: 625, w: 440, h: 100, kind: 'external' },
    ],
    nodes: [
      { id: 'steward', label: 'hearth-steward', sub: 'the household purse', kind: 'agent', x: 140, y: 135 },
      { id: 'trades', label: 'trades-desk', sub: 'vetted trades, 600', kind: 'agent', x: 310, y: 133 },
      { id: 'mira', label: 'Mira Lind', sub: 'mandate, device key', kind: 'human', x: 140, y: 255 },
      { id: 'gate', label: 'household gate', sub: 'mandate, permit, presence', kind: 'gate', x: 310, y: 255 },
      { id: 'es', label: 'household ledger', sub: 'each leg, replayable', kind: 'ledger', x: 140, y: 375 },
      { id: 'teg', label: 'job escrow', sub: 'held from booking', kind: 'teg', x: 310, y: 375 },
      { id: 'plumber', label: 'kessel-plumbing', sub: 'quotes, gets paid', kind: 'agent', x: 690, y: 135 },
      { id: 'p-es', label: 'their ledger', sub: 'same job, same keys', kind: 'ledger', x: 860, y: 135 },
      { id: 'site', label: 'kessel-site', sub: 'signs the job done', kind: 'agent', x: 655, y: 300 },
      { id: 'trust', label: 'trust scores', sub: 'from settled jobs', kind: 'registry', x: 885, y: 300 },
      { id: 'relay', label: 'job-done relay', sub: 'a courier only', kind: 'registry', x: 700, y: 540 },
      { id: 'xfer', label: 'cross-registry', sub: 'pays exactly once', kind: 'teg', x: 880, y: 490 },
      { id: 'calendar', label: 'family calendar', sub: 'bookings land here', kind: 'external', x: 195, y: 692 },
      { id: 'bank', label: 'banking app', sub: 'no link, by design', kind: 'external', x: 360, y: 692 },
    ],
    edges: [
      { id: 'e-mandate', from: 'mira', to: 'steward', label: 'mandate' },
      { id: 'e-token', from: 'steward', to: 'trades' },
      { id: 'e-quote', from: 'plumber', to: 'trades', label: 'quote, 420', labelT: 0.2 },
      { id: 'e-accept', from: 'trades', to: 'gate', label: 'accept' },
      { id: 'e-escrow', from: 'gate', to: 'teg', label: 'escrowed', labelT: 0.8 },
      { id: 'e-done', from: 'site', to: 'relay', label: 'job done, signed', labelT: 0.25 },
      { id: 'e-relay', from: 'relay', to: 'gate', label: 'principal checked', labelT: 0.78 },
      { id: 'e-ask', from: 'gate', to: 'mira', label: 'facts', curve: 30 },
      { id: 'e-sign', from: 'mira', to: 'gate', label: 'signed', curve: 30 },
      { id: 'e-release', from: 'teg', to: 'xfer', label: 'release', curve: -55, labelT: 0.25 },
      { id: 'e-paid', from: 'xfer', to: 'plumber', label: 'paid at home', labelT: 0.55 },
      { id: 'e-emit', from: 'teg', to: 'es', dashed: true, curve: 18 },
      { id: 'e-pemit', from: 'plumber', to: 'p-es', dashed: true, curve: 26 },
      { id: 'e-score', from: 'p-es', to: 'trust', label: 'settled jobs', dashed: true },
      { id: 'e-cal', from: 'es', to: 'calendar', label: 'bookings, by ref', dashed: true },
    ],
    script: [
      { edge: 'e-mandate', dwellMs: 1500, caption: 'Mira underwrites the steward once: a named human, a declared scope, limits. The gate re-derives what it conveys on every request.' },
      { edge: 'e-token', dwellMs: 1300, caption: 'The steward cuts the trades-desk a permit: vetted trades only, 600 units a job. A permit can only narrow what the steward holds.' },
      { edge: 'e-quote', dwellMs: 1400, caption: '19:48. Kessel & Daughter quotes 420 units for tonight from its own registry, with a trust score earned on settled jobs.' },
      { edge: 'e-accept', dwellMs: 1300, caption: '19:52. The trades-desk accepts, and the gate reads its permit as it stands now, before anything moves.' },
      { edge: 'e-escrow', dwellMs: 1400, caption: 'The 420 units are escrowed at booking on the household’s frame. The plumber can see the money exists before she drives over.' },
      { edge: 'e-done', dwellMs: 1400, caption: '21:50. Rosa’s agent on site marks the job done and signs it, from her own registry.' },
      { edge: 'e-relay', dwellMs: 1300, caption: 'The completion crosses the fabric; the relaying registry is a courier, never the principal.' },
      { edge: 'e-ask', dwellMs: 1400, caption: '420 is above the household’s 250 threshold, so the gate sends Mira’s phone the facts as the server computed them.' },
      { edge: 'e-sign', dwellMs: 1500, caption: 'Her thumb unlocks the device key, which signs those exact facts. A signed-in session alone signs nothing.' },
      { edge: 'e-release', dwellMs: 1300, caption: '21:58. The escrow releases exactly once, whatever the retries.' },
      { edge: 'e-paid', dwellMs: 1300, caption: 'The plumber is paid on her own registry.' },
      { edge: 'e-emit', dwellMs: 1500, caption: 'The booking and the release land on the household ledger, append-only, and every unit that moved is accounted for.' },
    ],
    traceLabel: 'One evening repair: quoted, escrowed, done, confirmed by a thumb, paid once, preserved.',
  },
  plan: [
    {
      name: 'Discover',
      headline: 'One month of errands, re-read as permits.',
      runs: 'Nothing. Last month’s bills, one repair and the pocket money redrawn as mandates, permits, payees and a threshold.',
      agents: 'None. The adults argue about the payee list and the threshold, which is exactly where that argument belongs.',
      integrates: 'Nothing. The bank, the bill-pay and the calendar stay exactly as they are.',
      notYet: 'No agent holds a permit. No unit moves.',
      proof: 'The past month replayed on paper, and both adults agree where every payment, every ask and every refusal lands.',
    },
    {
      name: 'Pilot',
      headline: 'One errand, pilot limits.',
      runs: 'Accounts and agents on a hosted registry. Nothing to run.',
      agents: 'The steward and the bill-runner, two billers on its permit, a small monthly budget, Mira’s device key enrolled.',
      integrates: 'The two billers that run agents. Everything else stays on the existing bill-pay.',
      notYet: 'No trades, no allowance, no tariff negotiation. One adult, one mandate.',
      proof: 'A month of bills, each paid exactly once on the rails, and one deliberately off-list payee refused and recorded.',
    },
    {
      name: 'Production',
      headline: 'The whole house on rails.',
      runs: 'The same hosted registry, or a household frame on a machine the family owns: registry, TEG, event store, identity fabric.',
      agents: 'The full cast: steward, bill-runner, tariff-scout, trades-desk, and the allowance-desk under Tomas’s mandate.',
      integrates: 'Vetted trades that run agents; bookings post to the family calendar, asks and receipts to the family thread.',
      notYet: 'Other households. One house proves itself first.',
      proof: 'An evening repair booked, escrowed, confirmed from a phone and paid exactly once, and the ledger replays every step of it.',
    },
    {
      name: 'Federation',
      headline: 'Trades and households on one grammar.',
      runs: 'Unchanged. Trades, billers and landlords bring their own registries or seats.',
      agents: 'A tradesperson’s trust score, earned on settled jobs, travels with its identity to the next household.',
      integrates: 'Each new biller or trade is an identity and an agent, not a new integration.',
      notYet: 'Nothing structural. Growth is households, trades and billers.',
      proof: 'A plumber on another registry is booked, confirmed and paid across registries exactly once, and her trust score reflects the settled job.',
    },
  ],
  sequenceTitle: 'One repair, quote to preserved release',
  sequence: `sequenceDiagram
  participant Tr as trades-desk (household frame)
  participant G as household gate
  participant TEG as job escrow
  participant Pl as kessel-plumbing (own registry)
  participant Ph as Mira’s phone (device key)
  participant ES as household ledger
  Pl->>Tr: quote: 420 units, tonight
  Tr->>G: accept, inside the permit
  G->>TEG: 420 escrowed at booking
  Pl->>G: job done, signed
  G->>Ph: the facts, as the server computed them
  Ph-->>G: signature, verified-user bit set
  G->>TEG: release cleared
  TEG-->>Pl: 420 units, exactly once
  TEG-->>ES: booking and release, append-only
  Note over Ph: a signed-in session signs nothing#59; an expired ask is a recorded denial
  Note over G: a payee off the permit is refused before any escrow`,
  sizing: [
    { level: 'L1', what: 'Households join with accounts and agents on a hosted registry', containers: '0 of theirs' },
    { level: 'L2', what: 'A landlord runs repair and bill agents for its buildings against a hosted seat', containers: 'agents only' },
    { level: 'L3', what: 'A housing cooperative, or a family that wants a frame of its own', containers: 'one frame of their own' },
  ],
}
