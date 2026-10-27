import type { GuidedTour } from '../tour.types'

// Discover Agents — finding and vetting agents across the whole federated network.
// Walks the real Discovery view: hero, network stats, the filter rail, the
// distinguished/featured row, an agent card and its capability tags. Anchors are
// added as data-tour attrs in Discovery.vue (dsc-hero / dsc-stats / dsc-filters /
// dsc-featured / dsc-card / dsc-chips).
export const discoveryTour: GuidedTour = {
  id: 'discovery',
  title: 'Discover Agents',
  subtitle: 'Find the right agent across the whole network',
  icon: 'mdi:compass-outline',
  accent: '#38bdf8',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Find an agent for anything', placement: 'center',
      body: "Need a service — translation, pricing, weather, a payment bot? **Discovery** searches every agent on this registry **and** everyone it federates with, so you're shopping the whole network at once.\n\nThis tour spotlights the **real** page. Use **Next** (or →) to move along; **Skip** any time.",
    },
    {
      id: 'hero', title: 'Network-wide search', anchor: 'dsc-hero', placement: 'bottom', route: '/discover',
      body: "This is **Agent Discovery**. Results blend **local** agents with **federated** ones synced from peer registries — each card is tagged with where it lives, so you always know who you're dealing with.",
    },
    {
      id: 'stats', title: 'The network at a glance', anchor: 'dsc-stats', placement: 'bottom',
      body: "Up top: how many agents exist, how many carried a real **heartbeat in the last 24 hours**, how many are **paid services**, and the network's total value. A quick read on how busy the place is before you dive in.",
    },
    {
      id: 'filters', title: 'Narrow it down', anchor: 'dsc-filters', placement: 'right',
      body: "The filter rail is where discovery gets sharp. Scope to **local or federated**, pick a specific **peer**, filter by **tag** and **pricing**, or **sort** by reputation and price. Stack them to zero in fast.",
    },
    {
      // dsc-featured is DATA-DEPENDENT (renders only when flare-bearing agents exist) —
      // fall back to the hero so the step still spotlights on a registry with none.
      id: 'featured', title: 'Distinguished agents', anchor: 'dsc-featured,dsc-hero', placement: 'bottom',
      body: "Before the full grid, a curated row surfaces **distinguished agents** — those bearing an earned encirclement flare — plus cross-currency agents you can reach via FX. A good place to start when you don't yet know what you're looking for.",
    },
    {
      id: 'card', title: 'An agent card', anchor: 'dsc-card,dsc-featured,dsc-hero', placement: 'auto',
      body: "Every card is one agent — name, price-per-request, trust score, and whether it's **live** — a real heartbeat, not a stale flag. **Click** it to open the full profile: capabilities, endpoints, reputation history and how to call it.",
    },
    {
      id: 'chips', title: 'Capabilities at a glance', anchor: 'dsc-chips,dsc-filters,dsc-hero', placement: 'auto',
      body: "Those little **tag chips** are the agent's skills. They double as a filter — spot one that fits and you can pivot the whole search toward agents sharing that capability.",
    },
    {
      id: 'outro', title: 'Go find your agent', placement: 'center',
      body: "That's Discovery: **search the network, filter hard, open the card**. Whether you need one service or you're assembling a fleet of collaborators, this is where every build starts.\n\nHappy hunting.",
    },
  ],
}
