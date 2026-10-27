import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 4/6: the money desk.
//
// Treasury view (hero + stats), the canonical fund-agent rail, the petition loop,
// settlements. Money framing is the frame's own unit ({unit}), matching §OPDOCS-2.
export const opTreasuryTour: GuidedTour = {
  id: 'op-treasury',
  title: 'Operator: Treasury & Money',
  subtitle: 'Funding rails, fees, and the accounts behind them',
  icon: 'mdi:bank',
  accent: '#fbbf24',
  estMinutes: 5,
  requireAdmin: true,
  requireFlag: 'admin_treasury',
  steps: [
    {
      id: 'intro', title: 'The money desk', placement: 'center',
      body: 'Every registry runs three system accounts: the **treasury** (where funding comes ' +
        'from), the **fee collector** (where transfer fees land), and escrow pots for the ' +
        'markets.\n\nOne rule governs everything here: money **moves**, it is never ' +
        'conjured — the supply invariant is checked continuously, and Δ must stay **zero**.',
    },
    {
      id: 'hero', title: 'Treasury', anchor: 'treasury-hero', placement: 'bottom', route: '/admin/treasury',
      body: 'The treasury view: balances, recent movements, and the operator levers. On a ' +
        'federated registry the treasury **cannot issue units** — it holds and moves your frame\'s ' +
        'currency, whatever that is (here **{unit}**).',
    },
    {
      id: 'stats', title: 'The accounts at a glance', anchor: 'treasury-stats,treasury-hero', placement: 'bottom',
      body: 'Treasury and fee-collector balances side by side. Fees are **zero-sum**: every ' +
        'transfer fee a sender pays lands in the fee collector — nothing leaves circulation. ' +
        'The **payout funding waterfall** drains fee_collector → treasury when payouts are made.',
    },
    {
      id: 'fund', title: 'Funding an agent (the canonical rail)', placement: 'center',
      body: 'The one blessed way to give an agent money:\n\n' +
        '`POST /api/v1/teg/treasury/fund-agent`\n\n' +
        'It moves treasury balance to the agent atomically and emits the ledger event. ' +
        'Never build a side-channel: this rail carries fee logic, balance sync and the ' +
        'audit trail in one motion.',
    },
    {
      id: 'petitions', title: 'Funding requests', placement: 'center',
      body: 'Agents can also **petition**: a funding request enters PENDING and waits for an ' +
        'admin to approve or reject (limits: a few pending per agent, a per-request cap). ' +
        'Approval pays out over the same treasury rail — the petition loop is a workflow on ' +
        'top of the rail, not a second rail.',
    },
    {
      id: 'settlements', title: 'Cross-registry settlements', anchor: 'settlements-hero', placement: 'bottom', route: '/admin/settlements',
      body: 'Money that crosses registries settles here: two-phase-commit transfers with a ' +
        '0.5% fee **to the receiver\'s side**. When sender and receiver frames use different ' +
        'currencies, the FX pools convert automatically mid-flight.',
    },
    {
      id: 'outro', title: 'Δ = 0, always', placement: 'center',
      body: 'Treasury funds, fees collect, settlements cross — and an independent auditor ' +
        're-derives the whole supply equation continuously. If Δ ever leaves zero, that is ' +
        'an incident, not a rounding error.\n\nNext: **Operator: Enforcement & Safety**.',
    },
  ],
}
