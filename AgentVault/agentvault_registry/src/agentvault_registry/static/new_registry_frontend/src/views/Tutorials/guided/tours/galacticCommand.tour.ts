import type { GuidedTour } from '../tour.types'

// §TOURGAP (2026-08-04) — Galactic Command had no tour. It LOOKED covered because the
// opWatchtower tour visits /command-center, but that is a DIFFERENT view: CommandCenter.vue
// (the admin overview) vs GalacticCommand.vue (the fleet cockpit). This covers the cockpit.
export const galacticCommandTour: GuidedTour = {
  id: 'galactic-command',
  title: 'Operator: Galactic Command',
  subtitle: 'One cockpit for the whole fleet, and what it deliberately cannot do',
  icon: 'mdi:radar',
  accent: '#f472b6',
  estMinutes: 4,
  requireAdmin: true,
  requireFlag: 'platform',
  steps: [
    {
      id: 'intro', title: 'A cockpit, not a back door', placement: 'center',
      body: 'Running a federation means answering questions that span every node at once: is ' +
        'anything unhealthy, is supply still conserved everywhere, which operator needs ' +
        'attention.\n\nGalactic Command puts those in one place. It is worth saying plainly what ' +
        'it does **not** do: nothing in this cockpit can issue a unit. Every action it offers ' +
        'runs through the same audited rails as the rest of the product.',
    },
    {
      id: 'stage', title: 'The targeting surface', anchor: 'gcc-stage', placement: 'center',
      route: '/galactic-command',
      body: 'The map is not a picture here — it is how you **select**. Click a registry or an ' +
        'agent and the panel on the right rebinds to it. Right-click opens a context menu on ' +
        'the node under your cursor.',
    },
    {
      id: 'hud', title: 'Surface toggle and the Δ strip', anchor: 'gcc-hud', placement: 'bottom',
      body: 'The toggle swaps the targeting surface between the **galactic** star map and the ' +
        '**planetary** globe. Same selection handlers underneath, so pick whichever you think in.\n\n' +
        'Beside it sits the Δ strip: the live supply delta for each frame. **Δ 0 is the whole ' +
        'game** — it means issued minus destroyed still equals what is in circulation. If one of ' +
        'those chips is not zero, stop reading this tour and go find out why.',
    },
    {
      id: 'bridge', title: 'The bridge', anchor: 'gcc-bridge', placement: 'left',
      body: 'Everything you can act on for the current target. With nothing selected it shows ' +
        'the fleet; select a registry and it becomes that registry\'s console; select an agent ' +
        'and it becomes that agent\'s.',
    },
    {
      id: 'fleet', title: 'The fleet at rest', anchor: 'gcc-fleet', placement: 'left',
      body: 'Every node in the directory with its health probe and canary state. This is the ' +
        'default view for a reason — most sessions start with **"is anything wrong?"** rather ' +
        'than with a specific node in mind.\n\nActions against a node you do not own require a ' +
        'connected relay session, which is why a foreign frame shows as observable before it ' +
        'shows as operable.',
    },
    {
      id: 'log', title: 'What you just did', anchor: 'gcc-log', placement: 'top',
      body: 'A running log of the actions this session fired, so a long night of operations ' +
        'leaves a trail you can read back. The authoritative record is still the audit log and ' +
        'the event ledger — this is the convenience copy.',
    },
    {
      id: 'outro', title: 'The daily sweep', placement: 'center',
      body: 'Open it, read the Δ strip, scan the fleet for a node that has gone quiet, act if ' +
        'you must, close it.\n\nFor the deeper admin views behind each node, take **Operator: ' +
        'Watchtower Basics**. For the ledger those Δ numbers are computed from, take **The Event ' +
        'Ledger**.',
    },
  ],
}
