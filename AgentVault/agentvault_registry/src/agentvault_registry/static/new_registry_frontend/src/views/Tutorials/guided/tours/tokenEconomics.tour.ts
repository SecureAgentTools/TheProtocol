import type { GuidedTour } from '../tour.types'

// Units, Fees & FX — walks the real Forex Desk: header → source agent → live rates →
// amount/fee → send → recent, then a stop on My Agents showing where to get the frame's unit. Anchors
// are data-tour attrs in ForexDesk.vue and MyAgents.vue (mya-fund is SHARED with the
// Your Agent Fleet tour). The Desk steps need an active agent.
export const tokenEconomicsTour: GuidedTour = {
  id: 'token-economics',
  title: 'Units, Fees & FX',
  subtitle: '{unit}, fees, and moving value across frames',
  icon: 'mdi:swap-horizontal',
  accent: '#38bdf8',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'The unit layer', placement: 'center',
      body: "**{unit}** is this frame's unit — agents hold it, are paid in it, spend it. Every frame runs its own unit, and the **Forex Desk** moves value between them at live rates.\n\nUse **Next** (or →) to move along; **Skip** any time.",
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
      id: 'hero', title: 'The Forex Desk', anchor: 'fx-hero', placement: 'bottom', route: '/forex', requireAgent: true,
      body: 'You move money here **as one of your agents** (the switcher up top). Same-frame transfers are plain sends; cross-frame ones (**A↔B↔C**) route through the live FX corridor automatically.',
    },
    {
      id: 'from', title: 'Pick the source', anchor: 'fx-from', placement: 'right', requireAgent: true,
      body: 'Choose which **agent** is sending, and from which **currency** balance. Its home frame decides whether this becomes a local move or a cross-frame swap.',
    },
    {
      id: 'rate', title: 'Live exchange rates', anchor: 'fx-rate', placement: 'left', requireAgent: true,
      body: 'This panel shows the **live rate** for each pair. The triangle **A↔B↔C** stays near-arbitrage-free, so a loop around all three frames barely leaks value (~98.5% retained).',
    },
    {
      id: 'amount', title: 'Amount & fee', anchor: 'fx-amount', placement: 'top', requireAgent: true,
      body: "Pick the destination agent and the **amount**. A small fee (**~0.5%**) goes to the receiving frame's treasury — the preview shows exactly what lands on the other side before you commit.",
    },
    {
      id: 'send', title: 'Send it', anchor: 'fx-send', placement: 'top', requireAgent: true,
      body: '**Send** opens a confirmation, then moves the funds through one escrow mover — so the books always balance (**Δ=0**). Cross-frame settles in seconds.',
    },
    {
      id: 'recent', title: 'Your trail', anchor: 'fx-recent', placement: 'top', requireAgent: true,
      body: 'Every transfer for this agent lands here with its status — your running record of who paid whom, and when.',
    },
    {
      id: 'fund', title: 'Where {unit} comes from', anchor: 'mya-fund', placement: 'bottom', route: '/my-agents',
      body: 'Out of units to move? On **My Agents**, **Request {unit}** asks the treasury to top up your active agent (or buy some via the fiat on-ramp). Then head back to the Desk.',
    },
    {
      id: 'outro', title: 'Value, in motion', placement: 'center',
      body: "That's the economy in one screen: **hold {unit} → send it → pay a small fee → settle across frames**. Every cent rides one escrow mover, so supply is conserved end-to-end.\n\nFund an agent and try a transfer whenever you like.",
    },
  ],
}
