import type { GuidedTour } from '../tour.types'

// §TOURGAP-2 (2026-08-05) — the FX Desk gained the keeper panels and the parked-route queue in
// §FEPARITY R3 and had no tour. The opTreasury tour covers /admin/treasury and
// /admin/settlements, not this. Operator series: admin + admin_treasury.
export const fxDeskTour: GuidedTour = {
  id: 'op-fx-desk',
  title: 'Operator: The FX Desk',
  subtitle: 'Three currencies, two keepers, and the queue that holds money nobody lost',
  icon: 'mdi:swap-horizontal-bold',
  accent: '#38bdf8',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'admin_treasury',
  steps: [
    {
      id: 'intro', title: 'Why a desk exists at all', placement: 'center',
      body: 'Each sovereign frame runs its own currency. An agent on one frame paying an agent ' +
        'on another is therefore a **currency conversion plus a settlement on both sides**, not ' +
        'a transfer.\n\nThe FX Desk is where that machinery is visible: the pools, the rate, the ' +
        'two background keepers that maintain it, and the failures.',
    },
    {
      id: 'keepers', title: 'The two keepers', anchor: 'fx-keepers', placement: 'bottom',
      route: '/admin/fx',
      body: 'The **router float keeper** makes sure the routing account holds enough of each ' +
        'currency to service hops. The **reserve peg keeper** holds the reserve near its target.\n\n' +
        'Both are live and configurable from here. Until recently they were not reachable from ' +
        'the app at all: the client was treating every `/teg/` URL as an agent-authenticated ' +
        'call, so these admin paths went out with no credentials and answered 401. The panels ' +
        'existed in the API and nowhere else.',
    },
    {
      id: 'parked', title: 'Money that is not lost and not delivered', anchor: 'fx-deadletters',
      placement: 'top',
      body: 'This queue is the one worth understanding properly.\n\nA cross-frame transfer ' +
        'converts first and delivers second. When the delivery leg fails, the converted funds ' +
        'sit in the **destination** frame\'s router account. The sender was debited. The ' +
        'recipient was never paid. And the supply invariant stays perfectly at **zero**, because ' +
        'parked is not burned.\n\nSo nothing alerts. We found **44** of these, the oldest about ' +
        'a week old, only because this queue was built.',
    },
    {
      id: 'notretryable', title: 'Read the "not retryable here" honestly', placement: 'center',
      body: 'Rows are marked with whether they can be recovered **from this node**. Most cannot, ' +
        'and that is by design rather than a limitation: the funds are physically on the other ' +
        'frame, so recovery has to be driven there.\n\nThe server computes that flag per row ' +
        'rather than letting the page guess, precisely so the UI can never imply that a button ' +
        'here would fix something sitting somewhere else.',
    },
    {
      id: 'recovery', title: 'How a recovery actually goes', placement: 'center',
      body: 'One route at a time, on the frame holding the funds, using the ordinary sweep rail. ' +
        'The memo carries the route id so a retry deduplicates at the ledger instead of paying ' +
        'twice, and the origin row is marked immediately afterwards.\n\nThat marking is the ' +
        '**only** double-pay guard, because the sweep rail has no per-route idempotency of its ' +
        'own. If you ever do this by hand: mark the row, or do not start.',
    },
    {
      id: 'outro', title: 'What to watch', placement: 'center',
      body: 'Keepers green, pool depth sane, and this queue **empty**. A number here that is not ' +
        'zero is someone waiting for money, and it will not show up in any invariant you are ' +
        'currently proud of.\n\nNext: **Operator: Treasury** for the funds this desk draws on.',
    },
  ],
}
