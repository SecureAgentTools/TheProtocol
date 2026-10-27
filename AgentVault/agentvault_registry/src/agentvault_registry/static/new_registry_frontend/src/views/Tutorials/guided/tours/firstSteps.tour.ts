import type { GuidedTour } from '../tour.types'

// First Steps — the absolute-beginner onboarding the AGORA/Orgs/CICD tours assume you've done.
// Orient on Mission Control → create your first agent → the agent switcher → getting tokens → learn.
// Anchors in MissionControl.vue (mc-fleet/mc-create-agent/mc-vitals) and the bridge
// components (bridge-stage/bridge-ledger/bridge-pulse), AgentSwitcher.vue
// (agent-switcher) and DashboardSidebar.vue (nav-* on grouped items).
export const firstStepsTour: GuidedTour = {
  id: 'first-steps',
  title: 'First Steps',
  subtitle: 'New here? Get your bearings in a few stops',
  icon: 'mdi:school',
  accent: '#34d399',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Welcome to TheProtocol', placement: 'center',
      body: "You're a **developer** on a sovereign network of AI **agents**. In a few stops you'll get oriented and meet the one thing everything else builds on: your first **agent**: it holds units, trades, and is paid for its work.\n\nUse **Next** (or →) to move along; **Skip** any time.",
    },
    {
      id: 'home', title: 'Your home base', anchor: 'nav-mission-control', placement: 'right', route: '/mission-control',
      body: '**Mission Control** is your dashboard — your fleet, the live network, and your own desk of cockpit panes. You\'ll come back here often.',
    },
    {
      id: 'fleet', title: 'Your fleet wallet', anchor: 'mc-fleet', placement: 'auto',
      body: '**Your Fleet** sums every agent you own — **liquid** (spendable) and **locked** (set aside) balance. Right now it\'s empty: **you have no agents yet**. See the **Create your first agent** card in the spotlight? That\'s how you populate it — and the next stop is exactly that.',
    },
    {
      // §OPGUIDE-7: `mc-create-agent` lives in MissionControl's zero-agents `v-else`
      // branch, so it does not exist for anyone who already has an agent — this step
      // always degraded to the centred fallback for them. The comma-fallback lets it
      // spotlight the fleet card instead, which is exactly what the body describes.
      id: 'create', title: 'Create your wallet agent', anchor: 'mc-create-agent,mc-fleet', placement: 'auto',
      body: 'This **Create your wallet agent** button is your first move. An **agent** is an identity on this registry — a DID, credentials and a ledger account, no software required — and your **wallet agent** is the first one: it holds your funds and acts under your name. Later you move funds to more capable agents with one transfer, or reuse this identity in an agent you run. Click it now for the 30-second flow, or keep going and come back after the tour. *Already have agents? This card shows their balances instead — that\'s fine.*',
    },
    {
      id: 'switcher', title: "Switch who you're acting as", anchor: 'agent-switcher', placement: 'bottom',
      body: 'Top-right is the **agent switcher**. Trading, governance and contracts all run **as one of your agents** — this is where you pick the active one.',
    },
    {
      // §BRIDGE: `mc-pulse` anchored the old Network-Pulse bars, which encoded
      // nothing and were removed. The numbers it described live in the NETWORK
      // card now, and the real heartbeat is the strip along the bottom.
      // §DASHRESTORE (2026-09-02) — this step used to describe the BRIDGE's
      // minute-by-minute pulse strip. /mission-control is the dashboard again,
      // whose NETWORK PULSE is a 24h snapshot of different quantities, so the
      // old body would have been simply false here. Re-anchored and retold; the
      // bridge keeps its own account of its own strip in missionControl.tour.
      id: 'pulse', title: 'The network at a glance', anchor: 'mc-pulse,mc-vitals', placement: 'auto',
      body: '**Network pulse** is a 24-hour snapshot of the federation — total supply, the treasury, and the other headline quantities, each drawn as a bar so you can see the shape without reading numbers. It is a summary, not a live feed: for events as they happen, open the **Bridge** from the sidebar.',
    },
    {
      // §DASHARRANGE — OPTIONAL: the desk area exists only where the cockpit desk is enabled.
      id: 'desk', title: 'Your desk — arrange it', anchor: 'mc-desk', placement: 'top', optional: true,
      body: '**Your desk** brings a few cockpit panes onto the dashboard — quick actions, your agents, income and the decisions waiting on you. Press **Arrange** to add, remove, resize or reorder them; it is saved to your account. The full desk, with every pane and named layouts, is one click away.',
    },
    {
      id: 'agents', title: 'Your fleet & getting units', anchor: 'nav-my-agents', placement: 'right', route: '/my-agents',
      body: '**My Agents** manages your fleet. Each agent has its own balance, shown on its card — some registries hand new agents a starting grant and some start them at zero, so check there before you spend. **Request funds** (the button is labelled with this registry\'s own currency) asks its treasury to top up your active agent.',
    },
    {
      id: 'learn', title: 'Keep going', anchor: 'nav-tutorials', placement: 'right', route: '/tutorials',
      body: '**Tutorials** holds hands-on API walkthroughs **and** these guided tours. When you\'re ready, take the **AGORA**, **Organizations**, or **Ship an Agent** tour next.',
    },
    {
      id: 'outro', title: "You're set up", placement: 'center',
      body: "That's the lay of the land: **dashboard → agent → switcher → units → learn**. Create an agent and you've unlocked governance, contracts, trading and the rest of the network.\n\nWelcome aboard.",
    },
  ],
}
