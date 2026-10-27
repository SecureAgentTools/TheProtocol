import type { GuidedTour } from '../tour.types'

// Agent Bundles — "Package, share, restore". Walks the real Bundles view: the New-bundle
// action, the three tabs, the official pattern library (forking), and importing a .tpb back.
// The Browse / Restore panels render only when their tab is active, so those steps click-anchor
// the tab buttons to switch the view in-place (then spotlight what they reveal). No agent needed.
// Anchors are added as data-tour attrs in BundlesView.vue.
export const bundlesTour: GuidedTour = {
  id: 'bundles',
  title: 'Agent Bundles',
  subtitle: 'Package an agent, share a template, restore anywhere',
  icon: 'mdi:package',
  accent: '#f472b6',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'What is a bundle?', placement: 'center',
      body: 'A **bundle** is a signed, portable archive of one or more agents — config, credentials manifest and CICD, all in one `.tpb` file. **Snapshot** for backup, **template** to share, **migration** to move an agent between registries.\n\nThis tour walks the real **Bundles** workspace. **Next** to begin.',
    },
    {
      id: 'hero', title: 'The bundles workspace', anchor: 'bdl-hero', placement: 'bottom', route: '/bundles',
      body: 'This is **Agent Bundles** — your library of packaged agents. Snapshot one for safekeeping, publish a template others can fork, or import a bundle someone shared with you.',
    },
    {
      id: 'new', title: 'Create a bundle', anchor: 'bdl-new', placement: 'left',
      body: '**New bundle** opens the builder — pick which agent(s) to include and the kind (**snapshot** / **template** / **migration**). The result is a signed `.tpb` you can download, share or fork.',
    },
    {
      id: 'tabs', title: 'Three tabs', anchor: 'bdl-tabs', placement: 'bottom',
      body: 'The workspace splits into three tabs: **My Bundles** (yours), **Browse Templates** (the public library) and **Restore from File** (import). Let\'s look at the library next.',
    },
    {
      id: 'browse', title: 'Browse the library', anchor: 'bdl-browse', placement: 'bottom',
      body: '**Browse Templates** is the public marketplace — official sovereign patterns plus community templates, all forkable. Open it to take a look.',
      cta: { label: 'Open the library →', do: 'click-anchor' },
    },
    {
      id: 'official', title: 'Official patterns', anchor: 'bdl-official,bdl-hero', placement: 'auto',
      body: '**✦ Official Sovereign Patterns** are vetted blueprints maintained by the platform. **Fork** one and you get a brand-new agent of your own, pre-wired from a known-good template — the fastest way to start.',
    },
    {
      id: 'restore', title: 'Restore from a file', anchor: 'bdl-restore', placement: 'bottom',
      body: 'Got a `.tpb` (or a legacy `.json`)? **Restore from File** drag-drops it back in and recreates the agents on **this** registry — fresh credentials and all. That\'s how a bundle becomes live agents again.',
      cta: { label: 'Open restore →', do: 'click-anchor' },
    },
    {
      id: 'outro', title: 'Portable by design', placement: 'center',
      body: 'That\'s bundles end-to-end: **package → share → fork → restore**. Your agents are never trapped — snapshot them for backup, hand a template to a teammate, or migrate to your own registry.\n\nSnapshot an agent whenever you\'re ready.',
    },
  ],
}
