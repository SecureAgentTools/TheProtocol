import type { GuidedTour } from '../tour.types'

// The Federation — how sovereign registries peer into one network. Walks the real
// Federation view: the hero, the Tiers/Network/Operations tabs, the tier filter,
// the sovereign frames, and a single peer card. Anchors are added as data-tour
// attrs in Federation.vue (fed-hero / fed-tabs / fed-filters / fed-frames / fed-peer).
export const federationTour: GuidedTour = {
  id: 'federation',
  title: 'The Federation',
  subtitle: 'How sovereign registries peer into one network',
  icon: 'mdi:server-network',
  accent: '#7376f2', // §FESUITE: 4.78:1 as the hub's Start label, 5.0:1 as the coach's kicker and under its button text (#6366f1 was 4.0-4.25:1)
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Welcome to the Federation', placement: 'center',
      body: "No registry is an island. TheProtocol is a **federation** — independent, sovereign registries that **bilaterally peer** to share agents, trust and discovery, while each stays in full control of its own economy.\n\nThis tour spotlights the **real** Federation view. Use **Next** (or →) to move along; **Skip** any time.",
    },
    {
      id: 'hero', title: 'The federation map', anchor: 'fed-hero', placement: 'bottom', route: '/federation',
      body: "You're looking at the network **from this registry's vantage point**. Every peer shown here has a signed agreement with us — federation is **bilateral**, so trust is always mutual and explicit, never assumed.",
    },
    {
      id: 'tabs', title: 'Three ways to look', anchor: 'fed-tabs', placement: 'bottom',
      body: "**Tiers** groups peers by relationship. **Network** draws the live topology graph — the actual chain of who-peers-with-whom. (Operators also get an **Operations** tab for drift + licensing.)",
    },
    {
      id: 'filters', title: 'Peers come in tiers', anchor: 'fed-filters', placement: 'bottom',
      body: "Filter the roster by tier: **Frames** (sovereign peer networks), **Direct Peers** (registries you peer with hands-on), **Discovered** (reached transitively through a peer), and **Cloud-Ops** (operator-run registries homed under a frame).",
    },
    {
      id: 'frames', title: 'The sovereign frames', anchor: 'fed-frames', placement: 'bottom',
      body: "At the top sit the **sovereign frames** — the independent mainframes (**A**, **B**, **C**), each with its **own currency** and governance. They bridge to one another as equals, which is what lets value and reputation cross the whole network.",
    },
    {
      id: 'peer', title: 'Inspect a peer', anchor: 'fed-peer', placement: 'auto',
      body: "Each card is one peer — its address, trust domain and live status. **Click** a card to open its drawer: health probes, lifecycle, the trust relationship and the agents it hosts. Cloud-ops are the same idea, just homed under a frame rather than standing alone.",
    },
    {
      id: 'outro', title: "That's the network", placement: 'center',
      body: "Federation in one breath: **sovereign registries, bilaterally peered, into one searchable network**. Open the Network tab to watch it live, or click a peer to see the trust behind the link.\n\nYou now know how the pieces connect.",
    },
  ],
}
