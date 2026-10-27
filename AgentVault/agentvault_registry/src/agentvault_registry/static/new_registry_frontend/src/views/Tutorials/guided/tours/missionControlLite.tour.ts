import type { GuidedTour } from '../tour.types'

/**
 * §LITEBRIDGE (2026-08-21) — the walkthrough for the bridge without a GPU.
 *
 * His ask: *"build the low performance mission control for when people don't
 * have the compute to display the new bridge. also make tutorials for both."*
 *
 * TWO THINGS THIS TOUR HAS TO GET RIGHT.
 *
 * 1. **It must not read as an apology.** The light bridge is not a stripped
 *    view; it is the same instruments with the expensive one removed, and on
 *    one point it is strictly more accurate than the stage — the stage draws at
 *    most 240 stars out of a fleet that can be thousands, the board counts all
 *    of them. Someone who lands here because their laptop has no GPU should
 *    finish this tour knowing they are not missing information.
 *
 * 2. **It must put the view into the mode it is teaching.** §OPGUIDE-7: a step
 *    whose `data-tour` is absent does not fail loudly, it degrades to a centred
 *    card and describes furniture that is not on screen. Every board anchor
 *    below exists only in LIGHT mode, so step two switches the view — through
 *    the real control, with a real click, which is also how the reader learns
 *    where the switch is.
 */
export const missionControlLiteTour: GuidedTour = {
  id: 'mission-control-lite',
  title: 'The Light Bridge',
  subtitle: 'The whole bridge, without a GPU',
  icon: 'mdi:format-list-bulleted',   // present in the LOCAL map; an unknown name renders blank
  accent: '#8ab4f8',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'The bridge, minus the expensive part', placement: 'center', route: '/bridge',
      body: 'The stage — the live 3D starmap — is the one part of Mission Control that needs a ' +
        'graphics card. Everything else is text and numbers.\n\nSo there is a second way to run ' +
        'this view: **the light bridge**. No WebGL, no animation, no per-frame work at all. The ' +
        'fleet log, the ledger, the pulse, the vitals, the quick actions and every modal are the ' +
        '**same components on the same rails** — this is not a cut-down page.',
    },
    {
      id: 'switch', title: 'Where the switch lives', anchor: 'mc-gfx-lite,mc-gfx', placement: 'bottom',
      body: '**AUTO** lets the machine decide, and it only drops to the light bridge on a fact it ' +
        'can check: no WebGL context, or a device reporting two CPU cores or a single gigabyte ' +
        'of memory. It never downgrades you on a hunch, and it always tells you which fact made ' +
        'the choice.\n\n**FULL** and **LIGHT** are yours. A manual choice beats the guesswork — ' +
        'pick FULL on a modest machine and you get your starmap. It does not beat **impossibility**: ' +
        'where no WebGL context can be opened at all, FULL is offered greyed out, because ' +
        'honouring it would hand you a black rectangle where the stage should be.',
      cta: { label: 'Switch to the light bridge', do: 'click-anchor' },
    },
    {
      id: 'board', title: 'The board stands where the stage stood', anchor: 'bridge-board', placement: 'center',
      body: 'The starmap says three things by drawing them: which registries exist, which of them ' +
        'your agents live on, and where traffic is moving.\n\nNone of that actually needs a GPU. ' +
        'The board states them instead — one row per registry, sorted with your home first and ' +
        'then by how much of your fleet lives there.',
    },
    {
      id: 'exact', title: 'This is the more accurate of the two views', anchor: 'bridge-board-summary,bridge-board', placement: 'bottom',
      body: 'The stage is **bounded**: it draws at most 240 individual stars, because geometry is ' +
        'not free. On a fleet of several thousand agents that is a few percent of it, spread so ' +
        'every registry is represented.\n\nThese numbers are **exact**. Every agent you own, ' +
        'counted, on every registry you are signed in to. The line above says so rather than ' +
        'letting you assume the prettier view was the more truthful one.',
    },
    {
      id: 'why', title: 'It tells you why you are here', anchor: 'bridge-board-why,bridge-board', placement: 'bottom',
      body: 'If the machine chose this view, the reason is printed — the missing WebGL context, ' +
        'the core count, whichever fact it was.\n\nA view that quietly swaps itself for a lesser ' +
        'one is a view you cannot trust. This one always says whose decision it was.',
    },
    {
      id: 'focus', title: 'Click a registry to narrow everything', anchor: 'bridge-board-rows,bridge-board', placement: 'right',
      body: 'On the stage you follow an agent and the camera pins to it. Here you click a ' +
        '**registry**, and the fleet log and the live ledger both narrow to the agents you own ' +
        'there.\n\nIt is one predicate feeding both panels, so they can never disagree about what ' +
        'you are looking at. Click it again — or **SHOW ALL** — to go back to the whole fleet.',
    },
    {
      id: 'live', title: 'A dot, not an animation', anchor: 'bridge-board-rows,bridge-board', placement: 'right',
      body: 'The dot on the left lights when that registry has been part of one of your events in ' +
        'the last minute, and **LAST** says how long ago the most recent one was.\n\nThe ' +
        '**ACTIVE** window in the top bar works here too: on the stage it decides which agents ' +
        'are drawn, and here it decides which registries are listed. Your home registry is never ' +
        'hidden for being quiet — that is a fact about traffic, not about what you own.\n\nAll ' +
        'of it updates once a second from a counter that is already running. That is the entire ' +
        'moving-parts budget of this view.',
    },
    {
      id: 'rails', title: 'Every instrument still works', anchor: 'bridge-ledger', placement: 'left',
      body: 'The live ledger, the fleet log, the pulse strip, the Δ seal, the vitals, NEEDS YOU, ' +
        'the quick actions, the terminal — all of it is here and all of it is the same code.\n\n' +
        'The ledger still counts **everything** and still tells you what it is not listing. ' +
        'Nothing about the truth changes with the graphics setting.',
    },
    {
      id: 'pulse', title: 'And it is still honest about its own past', anchor: 'bridge-pulse', placement: 'top',
      body: 'One bar per minute for the last hour, and minutes from before you opened the page are ' +
        'drawn as **absence** rather than as quiet.\n\nThat rule is the same in both views, and it ' +
        'is the reason either of them can be trusted at a glance.',
    },
    {
      id: 'outro', title: 'Same bridge, different budget', placement: 'center',
      body: 'If your machine can run the stage, run it — it is a genuinely better way to feel the ' +
        'shape of the network.\n\nIf it cannot, you are not being shown less of the truth. You are ' +
        'being shown the same truth in a form that costs almost nothing to draw. Switch whenever ' +
        'you like: **VIEW** in the top bar, and the choice sticks.',
    },
  ],
}
