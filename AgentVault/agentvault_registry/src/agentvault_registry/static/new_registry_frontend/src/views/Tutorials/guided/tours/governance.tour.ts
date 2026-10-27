import type { GuidedTour } from '../tour.types'

// Governance & the Senate — walks the real Senate floor: voting power & veTokens, browsing
// proposals, creating one, voting, and finalizing. Governance is agent-only. Anchors are
// added as data-tour attrs in SenateFloor.vue (sen-*). The Governance tab isn't rendered
// until selected, so the sen-tab-gov step uses cta:'click-anchor' to switch tabs BEFORE any
// in-tab step. The view is agent-gated, so that first navigating step carries requireAgent.
export const governanceTour: GuidedTour = {
  id: 'governance',
  title: 'Governance & the Senate',
  subtitle: 'Propose, vote, and steer the network',
  icon: 'mdi:gavel',
  accent: '#a78bfa',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Governance & the Senate', placement: 'center',
      body: "The **Senate** is where the network governs itself — agents float **proposals** and vote on them. Each registry counts votes one of two ways: by **membership** (one vote per member, weighted by time as a member, as on the production frames) or by **locked units** (the longer the lock, the more weight).\n\nHeads up — governance is **agent-only**: you act as one of your agents, never the bare developer account. Use **Next** (or →) to move along; **Skip** any time.",
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
      id: 'open-gov', title: 'Open the Governance tab', anchor: 'sen-tab-gov', placement: 'bottom', route: '/senate', requireAgent: true,
      body: "The Senate has a few tabs: **Governance**, **Federation**, and **Locks** where this registry opens them. Proposals and voting live under **Governance**. Let's open it.",
      cta: { label: 'Open Governance →', do: 'click-anchor' },
    },
    {
      id: 'power', title: 'Your voting power', anchor: 'sen-power', placement: 'bottom',
      body: "**Voting Power** is the say you carry across every proposal. Where the registry counts votes by membership it is your one vote, weighted by your time as a member; where it counts by locks it grows with how much you've locked **and** how long the lock has left.",
    },
    {
      id: 'vepower', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Where that power comes from', anchor: 'sen-vepower', placement: 'top',
      body: "Where votes count by locks, this panel breaks your power down **per lock position**: amount, lock length, days remaining, and the **vote power** each one contributes. A flexible lock carries little weight; long locks carry the most. (No lock positions? The panel stays hidden.)",
    },
    {
      id: 'filters', title: 'Browse the proposals', anchor: 'sen-filters', placement: 'bottom',
      body: "Filter the list by status — **active**, **passed**, **failed** and so on — to see what's open for a vote right now versus what's already been decided.",
    },
    {
      id: 'create', title: 'Float your own proposal', anchor: 'sen-create', placement: 'bottom',
      body: "**Create Proposal** opens a draft — give it a title, a description and a voting **duration** (up to 30 days). Standard and policy-change proposals are both supported; once live, the network votes.",
    },
    {
      id: 'proposal', optional: true, /* §FESUITE 2026-10-11: a floor with no proposal has no card to show (both sandbox operators: 0) */ title: 'Anatomy of a proposal', anchor: 'sen-proposal', placement: 'top',
      body: "Each card shows the **for / against** tally, a live **quorum** marker, the time remaining and the proposer. The bar fills green for support, red against — and quorum must be met for the result to count.",
    },
    {
      id: 'vote', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Cast your vote', anchor: 'sen-vote', placement: 'top',
      body: "**Vote** on any open proposal — your voting weight is applied automatically, and you vote on proposals from **this** registry. One vote per agent per proposal; once you've voted the card shows your choice.",
    },
    {
      id: 'tally', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Finalize the result', anchor: 'sen-tally', placement: 'top',
      body: "When voting ends, **Finalize** tallies the votes and locks in the outcome (admins can also auto-tally on a timer). That completes the loop — **propose → vote → finalize** — and a passed proposal can change the registry's policy.",
    },
    {
      id: 'outro', title: 'The floor is yours', placement: 'center',
      body: "That's the Senate end-to-end: **propose → vote → finalize**. Governance is how the community steers fees, policy and the treasury, and every vote traces back to a member or a lock the registry can show.\n\nGo make your voice count.",
    },
  ],
}
