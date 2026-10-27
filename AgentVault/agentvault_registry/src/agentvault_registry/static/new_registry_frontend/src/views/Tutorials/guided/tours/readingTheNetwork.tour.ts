import type { GuidedTour } from '../tour.types'

// §TOURGAP (2026-08-04) — the three spatial views (Galactic Map, Universe, AgentWorld) had
// no tour and no dedicated blog post, despite AgentWorld being the LARGEST view in the app.
// They are three lenses on one dataset, so they get ONE tour rather than three that repeat
// each other. Deliberately NOT admin-locked: all three are reachable by any logged-in
// developer, which is exactly who has never been shown them.
export const readingTheNetworkTour: GuidedTour = {
  id: 'reading-the-network',
  title: 'Reading the Network',
  subtitle: 'Three ways of seeing the same federation',
  icon: 'mdi:telescope',
  accent: '#a78bfa',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'Three lenses, one dataset', placement: 'center',
      body: 'A federation of registries is hard to hold in your head as a list. So the same ' +
        'live data is drawn three ways: a **star map** for structure, a **galaxy** for scale, ' +
        'and a **globe** for geography.\n\nNone of them is decoration. Each answers a question ' +
        'the other two answer badly.',
    },
    {
      id: 'gmap', title: 'The star map', anchor: 'gmap-hero', placement: 'bottom', route: '/galactic-map',
      body: 'Structure. Which registries exist, which agents live on them, and who is federated ' +
        'with whom. This is the view for **"how is this network wired?"**',
    },
    {
      id: 'gmap-canvas', title: 'Every node is real', anchor: 'gmap-canvas', placement: 'left',
      waitFor: 'gmap-canvas',
      body: 'Drag to rotate, scroll to zoom, click a node to open it. Agents are positioned by ' +
        'their home registry and coloured by **reputation**, so a healthy registry looks ' +
        'different from a struggling one before you read a single number.\n\nClicking through ' +
        'lands on the real agent or registry card — the map is a navigation surface, not a picture.',
    },
    {
      id: 'gmap-hud', title: 'What the legend tells you', anchor: 'gmap-hud', placement: 'right',
      body: 'Colour and size both carry meaning here. The panel tells you which is which, and ' +
        'the search and filter overlay narrows thousands of agents down to the ones you care ' +
        'about — by frame, by registry, by capability.',
    },
    {
      id: 'universe', title: 'The galaxy', anchor: 'universe-root', placement: 'center', route: '/universe',
      body: 'Scale. Where the star map shows you wiring, this shows you **proportion**: how much ' +
        'of the network lives on each sovereign frame, and how the frames relate.\n\n' +
        'Give it a moment — this view walks the federation to a depth of six before it draws, so ' +
        'the counts along the top (frames, registries, agents) are a **live crawl**, not a figure ' +
        'baked into the page. On a fresh single-frame deployment it honestly shows one frame.',
    },
    {
      // Anchor on the canvas, which is in the DOM within ~2s. Waiting on `aw-hud` here
      // would have parked this step for the ~43s Cesium takes to finish initialising.
      id: 'globe', title: 'The globe', anchor: 'aw-globe', placement: 'center', route: '/agentworld',
      body: 'Geography. Registries sit where their operators actually are, and transfers are ' +
        'drawn as **beams between real places**.\n\nThis takes a moment to load — it is a genuine ' +
        '3D globe, not an image.',
    },
    {
      id: 'globe-hud', title: 'The controls, once the globe settles', anchor: 'aw-hud', placement: 'right',
      waitMs: 50000,
      body: 'Search by name, filter by registry. Selecting an agent flies the camera to its home ' +
        'and opens its card, so you can go from "somewhere in the federation" to one identity in ' +
        'about two seconds.\n\nBelow it sits the legend, and it is worth reading once: beam ' +
        'colour and thickness encode the **kind** of movement — local transfer, cross-registry ' +
        'within one frame, or cross-frame between sovereign currencies. The cross-frame beam is ' +
        'the loudest because it is the one that crossed a monetary border and had to settle on ' +
        'both sides.',
    },
    {
      id: 'outro', title: 'When to reach for which', placement: 'center',
      body: 'Wiring question, open the **star map**. Proportion question, open the **galaxy**. ' +
        '"Where is this actually happening", open the **globe**.\n\nAll three read the same live ' +
        'ledger, so if they ever disagree with each other, one of them has a bug worth reporting.',
    },
  ],
}
