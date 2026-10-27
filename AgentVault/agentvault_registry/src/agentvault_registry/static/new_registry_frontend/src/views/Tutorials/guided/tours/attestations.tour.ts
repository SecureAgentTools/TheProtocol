import type { GuidedTour } from '../tour.types'

// Attestations & Compliance — "Prove it, verifiably". Walks the real Attestations console:
// the attestations table (status / circuit / expiry), the verifiable bundle (view + download),
// revoking a claim, and putting re-attestation on a recurring schedule. The view is agent-gated
// (the route guard sends agent-less developers to the picker), so the first stop sets
// requireAgent. Anchors are added as data-tour attrs in AgentAttestations.vue.
export const attestationsTour: GuidedTour = {
  id: 'attestations',
  title: 'Attestations & Compliance',
  subtitle: 'Carry portable, verifiable proofs about your agent',
  icon: 'mdi:certificate',
  accent: '#3b82f6',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'What is an attestation?', placement: 'center',
      body: 'An **attestation** is a zero-knowledge proof your agent submits about itself: that a public policy limit held (a markup cap, a usage tolerance, a fee rate, a moderation share) for a private figure, **without** revealing that figure. The figure is bound to a commitment the agent can open to an auditor; the proof does not show the figure is true. The registry checks the proof, time-stamps it, and signs a bundle anyone can check.\n\nThis tour walks the real **Attestations & Compliance** console. **Next** to begin; **Skip** any time.',
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
      id: 'hero', title: 'The compliance console', anchor: 'att-hero', placement: 'bottom', route: '/attestations', requireAgent: true,
      body: 'This is **Attestations & Compliance**. The tiles up top count your proofs by state — **verified**, **expired**, **revoked** — and the toolbar lets you switch agent and filter by circuit. Everything below is scoped to the agent you pick.',
    },
    {
      id: 'list', title: 'Your attestations', anchor: 'att-list', placement: 'top',
      body: 'Each row is one **attestation**: its verification **status**, the **circuit** that produced it, when it was **submitted**, and when it **expires**. A green **verified** badge means the proof checked out; an **expired** one simply needs re-attesting.',
    },
    {
      id: 'bundle', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'The verifiable bundle', anchor: 'att-bundle', placement: 'left',
      body: '**Bundle** opens the full proof package: the proof, the public inputs and the registry\'s signature. **Download** saves it as JSON. With the bundle and the circuit\'s public verification key (`/circuits/{id}/vk`), anyone can check the proof themselves, offline, with `bb verify`, **without trusting this registry**.',
    },
    {
      id: 'revoke', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Revoking a claim', anchor: 'att-revoke', placement: 'left',
      body: 'Need to retract a proof? **Revoke** marks it invalid from now on (optionally with a reason). Anyone re-verifying it afterwards sees the revocation, which helps when the underlying fact no longer holds.',
    },
    {
      id: 'schedules', title: 'Stay verified automatically', anchor: 'att-schedules', placement: 'top',
      body: 'Attestations expire (90 days by default). The **Schedules** card lists the cadence you declared per circuit: when one is overdue, the registry sends a reminder to the agent\'s owner. Proving again is up to the agent.',
    },
    {
      id: 'create', title: 'Schedule a re-attestation', anchor: 'att-create', placement: 'top',
      body: 'Pick a **circuit** and an **interval** (in hours), then **Add schedule**. An hourly job sends a reminder (the `attestation.due_reminder` webhook, to the agent\'s owner) when a schedule is overdue; it does not prove anything itself. Each new proof moves the schedule forward. You can **disable** any schedule from the table whenever you like.',
    },
    {
      id: 'outro', title: 'Provably yours', placement: 'center',
      body: 'That\'s the attestation loop: **prove → verify → bundle → schedule → revoke**. Your agent can now carry portable, independently checkable proofs about itself across the network.\n\nSet up a schedule whenever you\'re ready: the reminder tells you when your agent should prove again.',
    },
  ],
}
