import type { GuidedTour } from '../tour.types'

/**
 * §BRIDGE R8 (2026-08-19) — Mission Control is not the dashboard it was.
 *
 * The Commander: *"also update the mission control tutorial afterwards. because
 * it's a whole new site."* He is right, and `firstSteps` cannot carry it: that
 * tour is onboarding and only PASSES THROUGH this view on its way to creating an
 * agent. What the bridge needed was its own walkthrough — the stage, the seal,
 * the rails, the quick actions, the lens, replay — for someone who already has a
 * fleet and wants to actually operate from here.
 *
 * ANCHORS ARE THE WHOLE RISK. §OPGUIDE-7: a step whose `data-tour` no longer
 * exists does not fail loudly — it degrades to a centred card and quietly
 * describes furniture that is gone, which is exactly what #B21 caught when
 * `mc-pulse` outlived the bars it pointed at. Every anchor below is one of the
 * eleven that exist on this view today, and the R8 battery drives the tour in a
 * real browser and asserts each one resolves.
 */
export const missionControlTour: GuidedTour = {
  id: 'mission-control',
  title: 'The Bridge',
  subtitle: 'Operate the network from one screen',
  icon: 'mdi:radar',
  accent: '#22d3ee',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'This is the bridge', placement: 'center', route: '/bridge',
      body: 'Mission Control is not a page of tiles any more. It is a **stage** with instruments ' +
        'around it: the starmap behind everything is live ledger traffic, and the panels are ' +
        'readouts on it.\n\nEverything here reports what it actually saw. Where it cannot know ' +
        'something, it says so rather than drawing a comforting zero.',
    },
    {
      /*
       * §LITEBRIDGE — this step exists so the NEXT one is not a lie.
       *
       * Every remaining anchor in this tour belongs to the full bridge, and
       * `bridge-stage` does not exist at all in light mode. A reader who is in
       * light mode (or whose machine was auto-dropped into it) would get eight
       * centred cards describing a starmap that is not on their screen — the
       * §OPGUIDE-7 defect, self-inflicted. The CTA is optional: someone who
       * genuinely cannot run the stage should take the light bridge tour
       * instead, and this says so.
       */
      id: 'view', title: 'Two ways to run this view', anchor: 'mc-gfx-full,mc-gfx', placement: 'bottom',
      body: 'The stage is the only part of Mission Control that needs a graphics card, so there ' +
        'are two ways to run the bridge: **FULL** with the starmap, and **LIGHT** with a board in ' +
        'its place. Every other instrument is identical.\n\nThis tour is about the full one. If ' +
        'your machine cannot run it — or **AUTO** already put you in the light bridge — take ' +
        '**The Light Bridge** tour instead; nothing there is a downgrade of the truth.',
      cta: { label: 'Show me the stage', do: 'click-anchor' },
    },
    {
      id: 'stage', title: 'Every light is a real event', anchor: 'bridge-stage', placement: 'center',
      body: 'Each **arc** is value moving between two parties. A **flicker** is a trade, a **bloom** ' +
        'is an agent being born, a **thread** is an engagement in the Guild.\n\nNothing here is ' +
        'ambient animation: if a light moves, an event was emitted. **Click any moving light** to ' +
        'open its receipt — type, amount, frame and time.',
    },
    {
      id: 'seal', title: 'The prime directive, always on screen', anchor: 'mc-seal', placement: 'bottom',
      body: 'Δ is the **supply invariant**: units issued minus destroyed, against units in ' +
        'circulation. It must be **0.00**, and an independent auditor verifies it continuously.\n\n' +
        'It is stamped once when you arrive rather than ticking — a number that re-reads itself ' +
        'every minute invites you to stop reading it. **Click it** to check again on demand.',
    },
    {
      id: 'vitals', title: 'The network, honestly counted', anchor: 'mc-vitals', placement: 'left',
      body: 'Registries up, supply, agents, events, latency — across all three sovereign frames.\n\n' +
        'The sandbox tier is **off by design**, so it is excluded from the health score instead of ' +
        'being counted as five things down.',
    },
    {
      id: 'quick', title: 'Act without leaving', anchor: 'mc-quick-actions', placement: 'left',
      body: 'The most common actions run **from here**, in a dialog, on the same rails the full ' +
        'views use — no new money path, nothing that is not already possible elsewhere.\n\n' +
        'They act on the agent you are **following**, so what you are watching and what you are ' +
        'about to move money to are the same thing. Every dialog names **both sides** before you ' +
        'commit, and a large amount has to be typed again.',
    },
    {
      id: 'fleetlog', title: 'Your agents, live', anchor: 'bridge-fleet-log', placement: 'right',
      body: 'The **fleet log** is only your own agents, in sentences rather than event names. ' +
        'Click a row to open that agent; click **follow** and the camera pins to its star and ' +
        'stays with it.\n\nIf it cannot place an agent on the map it refuses and says so, rather ' +
        'than pointing the camera at nothing.',
    },
    {
      id: 'ledger', title: 'The ledger counts what the stage cannot draw', anchor: 'bridge-ledger', placement: 'left',
      body: 'The live ledger opens on **your own** traffic so it stays readable — **ALL** widens it ' +
        'to the whole federation.\n\nAbout seven in ten events are `LedgerBalanceChanged`, the ' +
        'accounting shadow of movements already listed under their own names. Those are **counted, ' +
        'not listed**; **SHADOW** shows the raw wire. The counters always count everything, and the ' +
        'panel tells you how much it is not showing you.',
    },
    {
      id: 'pulse', title: 'The last hour, and the parts it did not see', anchor: 'bridge-pulse', placement: 'top',
      body: 'One bar per minute for the last hour. Minutes from **before you opened the page** are ' +
        'drawn as **absence**, not as quiet — this page reports what it witnessed, and a stream has ' +
        'no past.\n\nThat rule is why the strip can be trusted: it never fills a gap it cannot account for.',
    },
    {
      id: 'doors', title: 'Panels, lenses and replay', anchor: 'mc-doors', placement: 'left',
      body: '**DISCOVERY**, **LOCKS** and **AGORA** open a terminal **in place** rather than ' +
        'navigating away — each keeps a link to its full view for anything it does not carry. ' +
        '**MAP** clears the panels so you can see the stage you are already on. **REPLAY** plays ' +
        'back what this session witnessed.\n\nPress **F** for the fleet lens: everything that is not ' +
        'yours eases back, still drawn and still counted, just quiet. **Esc** restores it.',
    },
    {
      id: 'outro', title: "That's the bridge", placement: 'center',
      body: 'Watch the stage, read the ledger, act from the rail. If it ever costs your machine ' +
        'too much, the bridge will say so and offer you the light one — measured off its own ' +
        'draw timer, never a guess, and never switched behind your back.\n\nIf something here ever looks ' +
        'like it is inventing data — a light with no event, a count that does not match the ledger, ' +
        'a minute drawn as quiet when nobody was watching — that is a bug, not a flourish. This ' +
        'view is meant to be trustable at a glance.',
    },
  ],
}
