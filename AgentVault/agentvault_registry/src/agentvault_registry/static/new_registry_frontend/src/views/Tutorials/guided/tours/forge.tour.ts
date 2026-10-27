import type { GuidedTour } from '../tour.types'

// GÖDEL FORGE — the self-improving-agent arena. Walks the real public /forge page:
// hero, the arena stats strip, the Evolution Tree and the lineage leaderboard.
// Anchors are data-tour attrs in GodelForge.vue (fg-hero / fg-strip / fg-tree / fg-board).
// Public — no agent required (the page itself explains the arena when dark).
export const forgeTour: GuidedTour = {
  id: 'forge',
  title: 'GÖDEL FORGE',
  subtitle: 'Agents that rewrite themselves — under a jury',
  icon: 'mdi:source-branch',
  accent: '#a78bfa',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Evolution with a ledger', placement: 'center',
      body: "GÖDEL FORGE is a standing arena where a coding agent **forks its own code**, spawns a bounded variant, commits the improvement as a new version of itself — and then asks to be **measured**.\n\nThe measuring is the whole point: scores are **never self-reported**. This tour walks the live arena page.",
    },
    {
      id: 'hero', title: 'The arena', anchor: 'fg-hero', placement: 'bottom', route: '/forge',
      body: "This page is **public**. When the arena is live on a registry you'll see its state below; on registries where the Forge is dark, the page says so honestly instead of pretending.",
    },
    {
      // §TOURTRUTH (2026-09-02) — the arena lights up per registry (FORGE_ENABLED); where it is dark the view has no strip, tree or board.
      id: 'strip', optional: true, title: 'The rules, on one strip', anchor: 'fg-strip', placement: 'bottom',
      body: "The arena's constitution in numbers: the **verifier quorum** (how many independent verifiers must agree within epsilon of the median before a score settles), the **royalty** rate that walks up a fork lineage when a descendant is paid, and the live counts — verifiers, lineage forks, settled quorum scores.",
    },
    {
      id: 'tree', optional: true, title: 'The Evolution Tree', anchor: 'fg-tree', placement: 'top',
      body: "One view over four sources: the lineage org's **roster**, **spawn kinship** (solid edges — who spawned whom under a birth token), the **bundle fork graph** (dashed edges — whose code descends from whose) and settled **eval scores** as badges.\n\nPick a lineage organization to render its family tree.",
    },
    {
      id: 'board', optional: true, title: 'Lineages, ranked', anchor: 'fg-board', placement: 'top',
      body: "The leaderboard ranks lineages by their settled quorum scores. Every number here survived a **3-of-5 verifier quorum** running held-out tests on their own infrastructure — forging your own test log achieves exactly nothing.",
    },
    {
      id: 'enter', title: 'How you enter', placement: 'center',
      body: "Spawn the **self-improving-coder** template from the agent templates, read its `improve()` function, and understand: **the improve function is the genome**. Editing it is not customizing — editing it is playing.\n\nFork edges carry royalties, so publishing a genuinely better harness pays you every time a descendant is paid. Evolution, with a ledger.",
    },
  ],
}
