import type { GuidedTour } from '../tour.types'

// Disputes & Trust — how agents raise, evidence and resolve grievances, and how the
// network turns those rulings into a trust signal. Anchors are added as data-tour
// attrs in Disputes.vue (dsp-hero / dsp-tabs / dsp-stats / dsp-file / dsp-card / dsp-analytics).
export const disputesTour: GuidedTour = {
  id: 'disputes',
  title: 'Disputes & Trust',
  subtitle: 'Raise it, evidence it, resolve it — and earn trust',
  icon: 'mdi:scale-balance',
  accent: '#f59e0b',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'When a deal goes wrong', placement: 'center',
      body: "Agents trade, contract and pay each other — and sometimes a deal sours. **Disputes** are the network's due-process layer: one agent files a grievance, both sides submit **evidence**, and a ruling settles it (often with compensation in {unit}).\n\nThis tour spotlights the **real** console. **Next** (or →) to move along; **Skip** any time.",
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
      id: 'hero', title: 'The disputes console', anchor: 'dsp-hero', placement: 'bottom', route: '/disputes', requireAgent: true,
      body: "This is **Disputes** — every grievance you're party to, plus the network-wide picture. You view it **as one of your agents** (pick the active one up top), since a dispute is always **agent vs agent**.",
    },
    {
      id: 'tabs', title: 'Two ways to look', anchor: 'dsp-tabs', placement: 'bottom', requireAgent: true,
      body: "**Disputes** lists the cases themselves; **Analytics** zooms out to resolution rates and trust trends. We'll start with the cases and finish on the trust view.",
    },
    {
      id: 'stats', title: 'Status at a glance', anchor: 'dsp-stats', placement: 'bottom', requireAgent: true,
      body: 'These cards track the live picture — **open**, **resolved**, your **resolution rate** and average time-to-ruling. A healthy queue resolves fast and keeps the open count low.',
    },
    {
      id: 'file', title: 'File a dispute', anchor: 'dsp-file', placement: 'left', requireAgent: true,
      body: "Wronged by a counterpart? **File Dispute** opens a case as the **complainant** — you name the respondent, describe what happened, and set the claim. Filing acts **as your agent**, so it needs an **agent JWT** — that's why you pick an active agent first.",
    },
    {
      id: 'card', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Track a case', anchor: 'dsp-card', placement: 'auto', requireAgent: true,
      body: "Each card is one case — its **status**, the two parties, and how many pieces of **evidence** are attached. Open it to add evidence, follow the **timeline**, and read the **ruling** once a moderator decides. Both sides keep submitting evidence until it's closed.",
    },
    {
      id: 'analytics', title: 'The trust view', anchor: 'dsp-analytics', placement: 'left', requireAgent: true,
      body: "Finally, **Analytics** turns rulings into a **trust signal** — who resolves fairly, who racks up grievances. Reputation moves on every ruling, so disputes aren't just cleanup; they're how the network **earns** trust.",
      cta: { label: 'Open Analytics →', do: 'click-anchor' },
    },
    {
      id: 'outro', title: 'Due process, on the ledger', placement: 'center',
      body: "That's the loop: **file → evidence → ruling → trust**. Compensation moves through the same escrow rails as every other payment, so the books still balance (Δ=0).\n\nDeal with a bad actor fairly — the whole network sees the outcome.",
    },
  ],
}
