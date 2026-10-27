import type { GuidedTour } from '../tour.types'

// Locks (his words 2026-10-25: "staking doesnt exist anymore in the way it did", "staking wroding fully gone") — walks
// the lock desk (StakingView, route /staking): what a lock is, the lock sheet, the tiers, the numbers, the positions and
// their lock, and the cross-registry transfer. Anchors are data-tour attrs in StakingView.vue (stk-*). The view is
// agent-gated (route meta requiresAgent), so the first navigating step carries requireAgent. The hub offers the tour only
// where the registry opens locks (staking_enabled); a payout on locked units shows only where the registry switches it on.
export const stakingTour: GuidedTour = {
  id: 'staking',
  title: 'Locks',
  subtitle: 'Lock units for voting weight, where this registry opens locks',
  icon: 'mdi:lock',
  accent: '#fbbf24',
  estMinutes: 4,
  requiresRegistryFlag: 'staking_enabled',
  steps: [
    {
      id: 'intro', title: 'Locks', placement: 'center',
      body: "A **lock** sets an agent's units aside for a period. Where this registry counts votes by locks, a lock is **voting weight** in governance: the longer the lock that remains, the more it weighs. Where the registry also switches on a payout on locked units, it is discretionary, paid in platform units, and shown on this desk.\n\nThis tour walks the **real** lock desk. Use **Next** (or →) to move along; **Skip** any time.",
    },
    {
      // §WALLETAGENT (2026-09-02) — HIS ask: the agent-gated tours start by guiding the creation of
      // the wallet agent and explain it short and analytical. `create-wallet` opens the quick
      // modal in wallet mode when no agent is active, and simply continues when one is.
      id: 'wallet', title: 'You act as your wallet agent here', placement: 'center',
      body: 'An **agent** is an identity on this registry: a DID, credentials and a ledger account. It does not have to be software.\n\n' +
        'Your **wallet agent** is your first identity: it holds your funds, pays and votes with its own address, under your name. ' +
        'Later you can create more capable agents and move funds to them with one transfer, or run your own agent with this identity\'s credentials — it becomes that agent, balance and history included.\n\n' +
        'If you have no agent yet, the button below creates your wallet agent; if you already act as one, just continue.',
      cta: { label: 'Create my wallet agent', do: 'create-wallet' },
    },
    {
      id: 'hero', title: 'The lock desk', anchor: 'stk-hero', placement: 'bottom', route: '/locks', requireAgent: true,
      body: "Everything here is in **your registry's own unit** (here **{unit}**). You lock **as one of your agents**: the switcher up top picks who is acting.",
    },
    {
      id: 'stake', title: 'Lock in one step', anchor: 'stk-stake-btn', placement: 'bottom',
      body: "The **Lock** button opens the lock sheet: pick an **amount** and a **lock period**, then confirm. **Flexible** has no lock period; a longer lock carries more voting weight.",
    },
    {
      id: 'stats', title: 'Your numbers at a glance', anchor: 'stk-stats', placement: 'bottom',
      body: "These cards track your **total locked** and, where this registry makes payouts on locked units, the **last payout** and the current **payout rate**, all live.",
    },
    {
      id: 'tiers', title: 'Lock tiers', anchor: 'stk-tiers', placement: 'top',
      body: "The tiers are the lock periods this registry offers: flexible, 30, 90, 180 and 365 days. Tiers you already hold are highlighted; click one to pre-fill the lock sheet at that period.",
    },
    {
      id: 'tabs', title: 'Positions and history', anchor: 'stk-tabs', placement: 'bottom',
      body: "These tabs hold the detail: **Positions** lists every open lock, and where payouts are switched on, **Automatic Relock**, **Payout History** and **Analytics** show what was paid on locked units.",
    },
    {
      id: 'positions', title: 'Your positions and their lock', anchor: 'stk-positions', placement: 'top',
      body: "Each position shows its amount and its **unlock date**. A position cannot be released before its own lock period ends, so the **Unlock** action lights up only once a position is unlocked.",
    },
    {
      id: 'xfer', title: 'Move units across registries', anchor: 'stk-xfer', placement: 'bottom',
      body: "**Cross-Registry Transfer** sends balance to another federated registry: a small fee goes to the receiver's treasury and the move is idempotent end to end. Handy when an agent needs liquidity on another frame.",
    },
    {
      id: 'outro', title: "You're ready to lock", placement: 'center',
      body: "That's the loop: **lock → vote with its weight, where votes count by locks → unlock after the period**.\n\nPick a period whenever you're ready.",
    },
  ],
}
