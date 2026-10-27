import type { GuidedTour } from '../tour.types'

// Your Agent Fleet — walks the real My Agents board (fleet, request funds, open an agent,
// the table, funding history) then the Agent Forge (hero, stepper, next). Anchors are
// data-tour attrs in MyAgents.vue (mya-fund is SHARED with the Units, Fees & FX tour)
// and AgentForge.vue. Public — no agent required.
export const agentLifecycleTour: GuidedTour = {
  id: 'agent-lifecycle',
  title: 'Your Agent Fleet',
  subtitle: 'Manage what you have — and forge what comes next',
  icon: 'mdi:robot',
  accent: '#f472b6',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Your fleet HQ', placement: 'center',
      body: 'Every **agent** you own is an actor on the network — a DID, a wallet, credentials. This tour shows where you **manage** them and where you **build** the next one.\n\nUse **Next** (or →) to move along; **Skip** any time.',
    },
    {
      id: 'hero', title: 'My Agents', anchor: 'mya-hero', placement: 'bottom', route: '/my-agents',
      body: '**My Agents** is your roster — balances, health, credentials and quick actions for every agent in your fleet.',
    },
    {
      id: 'fund', title: 'Top up an agent', anchor: 'mya-fund', placement: 'bottom',
      body: '**Request {unit}** asks the treasury to fund your active agent — the simplest way to get units flowing without leaving this page.',
    },
    {
      id: 'open', title: 'Open an agent', anchor: 'mya-card,mya-hero', placement: 'auto',
      body: '**View** drills into a single agent — its profile, balance, signing keys, mTLS, and the controls to rotate or retire it.',
    },
    {
      id: 'table', title: 'The whole fleet', anchor: 'mya-table,mya-hero', placement: 'top',
      body: 'Prefer dense over pretty? The **table** view lists every agent, balance and status in one sortable scan — handy once your fleet grows.',
    },
    {
      id: 'funding', title: 'Funding history', anchor: 'mya-funding', placement: 'top',
      body: 'Every **Request {unit}** you file is tracked here — pending, approved or funded — so you always know where a top-up stands.',
    },
    {
      // ma-access-btn lives on the CARD view (the default); in table mode the chain
      // falls back to the table/hero and the CTA click is inert — graceful, not broken.
      id: 'access', title: 'The access panel', anchor: 'ma-access-btn,mya-table,mya-hero', placement: 'auto',
      body: 'Every agent has an **Access** panel — its roles, spend limits, delegation grants and capability permits, all in one slide-over. Let\'s open one.',
      cta: { label: 'Open the access panel →', do: 'click-anchor' },
    },
    {
      // Inside the modal just opened by the CTA — the panel fetches authz state first,
      // so give the anchors a long window before the background re-anchor gives up.
      id: 'delegate', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Spawn, issue, attenuate', anchor: 'aap-spawn,aap-issue,aap-attenuate', placement: 'auto', waitMs: 15000,
      body: 'Down here the agent becomes a **principal**: **Spawn a hand** creates a scoped sub-agent whose authority is always ≤ the parent, **Issue a permit** hands a slice of authority to another holder, and **attenuate** derives strictly-weaker child permits. Everything expires, everything is revocable — down to single MCP tools.\n\n*(Close the panel with ✕ whenever you\'re done exploring.)*',
    },
    {
      id: 'forge', title: 'Forge a new agent', anchor: 'forge-hero', placement: 'bottom', route: '/agent-forge',
      body: 'Ready for another? The **Agent Forge** is the guided build flow — name, capabilities, identity and deploy, all in one place.',
    },
    {
      id: 'stepper', title: 'A guided build', anchor: 'forge-stepper', placement: 'bottom',
      body: 'The **stepper** breaks creation into a few clear stages. Move back and forth freely — nothing is committed until the final deploy.',
    },
    {
      id: 'next', title: 'Step through it', anchor: 'forge-next', placement: 'top',
      body: '**Next** advances once the current step is valid. Work through to the end and your new agent is **forged, registered and live**.',
    },
    {
      id: 'outro', title: 'Fleet, handled', placement: 'center',
      body: "That's the lifecycle: **manage on My Agents → fund → open → forge the next one**. Build as many agents as you need — each gets its own wallet, identity and place in the economy.\n\nGo grow your fleet.",
    },
  ],
}
