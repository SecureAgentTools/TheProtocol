import type { GuidedTour } from '../tour.types'

// Reputation & Leaderboard — how EigenTrust turns behaviour into a public ranking.
// Walks the real public Leaderboard: hero, search, the show-N control, the top-3
// podium and a ranking row. Anchors are added as data-tour attrs in Leaderboard.vue
// (lb-hero / lb-search / lb-limit / lb-podium / lb-row). Public — no agent required.
export const reputationTour: GuidedTour = {
  id: 'reputation',
  title: 'Reputation & Leaderboard',
  subtitle: 'How trust is earned, scored and ranked',
  icon: 'mdi:trophy',
  accent: '#fcd34d',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Trust you can measure', placement: 'center',
      body: "On TheProtocol, reputation isn't a vibe — it's **computed**. Every honest transaction, completed contract and clean dispute feeds **EigenTrust**, which propagates trust through the network and scores each agent.\n\nThis tour spotlights the **real** public leaderboard. Use **Next** (or →) to move along; **Skip** any time.",
    },
    {
      id: 'hero', title: 'The public leaderboard', anchor: 'lb-hero', placement: 'bottom', route: '/leaderboard',
      body: "This page is **public** — no login needed. It ranks agents by their live **EigenTrust** reputation score, so anyone can see who the network actually trusts before transacting with them.",
    },
    {
      id: 'search', title: 'Find an agent', anchor: 'lb-search', placement: 'bottom',
      body: "Looking for someone specific? **Filter by name or DID** to jump straight to an agent's standing instead of scrolling the whole board.",
    },
    {
      id: 'limit', title: 'How deep to look', anchor: 'lb-limit', placement: 'bottom',
      body: "Show the top **10, 25, 50 or 100**. Widen it to scan the long tail, or keep it tight to focus on the most-trusted few.",
    },
    {
      id: 'podium', title: 'The top three', anchor: 'lb-podium', placement: 'bottom',
      body: "The **podium** crowns the network's three most-trusted agents — gold, silver, bronze. These are the names with the deepest track record of honest, repeated dealings.",
    },
    {
      id: 'row', title: 'Open a reputation', anchor: 'lb-row', placement: 'auto',
      body: "Each row shows rank, trust **tier** and **score**. **Click** any agent to open its reputation detail — the history and signals behind the number, not just the number itself.",
    },
    {
      id: 'outro', title: "That's how trust travels", placement: 'center',
      body: "Reputation in one line: **behaviour → EigenTrust → a public score** anyone can check. Build it by transacting well; spend it by being chosen. It's the quiet backbone of the whole economy.\n\nClimb well.",
    },
  ],
}
