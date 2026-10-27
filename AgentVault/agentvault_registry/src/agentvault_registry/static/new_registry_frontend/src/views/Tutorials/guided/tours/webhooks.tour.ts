import type { GuidedTour } from '../tour.types'

// §TOURGAP-2 (2026-08-05) — the webhook surface was rebuilt in §FEPARITY R4 (live event
// catalog, redeliver, canonical router) and had no tour. Developer-tier: no admin lock.
export const webhooksTour: GuidedTour = {
  id: 'webhooks',
  title: 'Webhooks',
  subtitle: 'Get told when something happens, and re-send it when your endpoint was down',
  icon: 'mdi:webhook',
  accent: '#34d399',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Push, instead of polling', placement: 'center',
      body: 'Polling an API to find out whether anything happened is wasteful for you and for ' +
        'the registry. A webhook inverts it: you give us a URL, we POST to it when something ' +
        'you care about occurs.\n\nEvery delivery is **signed**, so your endpoint can verify the ' +
        'call really came from this registry and not from someone who guessed your URL.',
    },
    {
      id: 'hero', title: 'Your callbacks', anchor: 'wh-hero', placement: 'bottom', route: '/webhooks',
      body: 'Everything registered under your developer account. Webhooks belong to **you**, not ' +
        'to an individual agent, so one endpoint can cover your whole fleet.',
    },
    {
      id: 'stats', title: 'Health at a glance', anchor: 'wh-stats', placement: 'bottom',
      body: 'Total, active, and how many deliveries have failed. A webhook that keeps failing ' +
        'gets deactivated rather than retried forever, so a dead endpoint of yours cannot ' +
        'become a load problem for the network.',
    },
    {
      id: 'add', title: 'Register one', anchor: 'wh-add', placement: 'bottom',
      cta: { label: 'Open the form', do: 'click-anchor' },
      body: 'A URL and a set of events. The secret is generated for you and **shown exactly ' +
        'once** — it is stored hashed, so if you lose it you rotate rather than recover it.',
    },
    {
      id: 'events', title: 'The event catalog is live', anchor: 'wh-events-grid', placement: 'left',
      body: 'This list is fetched from the server, not baked into the page. That matters more ' +
        'than it sounds: it used to be a hand-maintained list that had drifted to **22 of the ' +
        '49** real events, so things like `agent.slashed`, `agent.suspended` and ' +
        '`supply.invariant_breach` fired on the server and could not be subscribed to here at ' +
        'all.\n\nNow a new backend event appears in this picker automatically, grouped by its ' +
        'own prefix.',
    },
    {
      // Comma fallback: the list only renders when webhooks EXIST. On a registry with none
      // the empty state is what is on screen, and that is the correct thing to spotlight.
      id: 'list', title: 'Your endpoints', anchor: 'wh-list,wh-empty', placement: 'top',
      body: 'Once you have registered one, each row here can be tested, paused, edited, or ' +
        'opened for its delivery history. **HISTORY** is the one you will use in anger.\n\n' +
        'If this is empty, that is simply where you are: nothing is subscribed on this ' +
        'registry yet.',
    },
    {
      id: 'deliveries', title: 'Every attempt is kept', placement: 'center',
      body: 'The delivery log records the request payload, the response status, the response ' +
        'body and the retry count for each attempt. You can filter to just the failures.\n\n' +
        'When an attempt did not succeed you get a **REDELIVER** button: it replays that exact ' +
        'payload through the live delivery path and records a **new** attempt, leaving the ' +
        'original row untouched for audit. That is the difference between a log and a tool.',
    },
    {
      id: 'outro', title: 'The habit', placement: 'center',
      body: 'Subscribe narrowly, verify the signature on your side, and when your endpoint has ' +
        'an outage, come back here and redeliver the window you missed instead of asking us to ' +
        'replay it.\n\nNext: the **Event Ledger** tour, if you want the full record rather than ' +
        'a push notification about part of it.',
    },
  ],
}
