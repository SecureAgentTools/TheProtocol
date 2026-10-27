import type { GuidedTour } from '../tour.types'

// §TOURGAP (2026-08-04) — the Event Ledger and Ledger Forensics shipped in §FEDEVENTS with
// no tour and no API track. This is the missing walkthrough: the append-only ledger, how to
// trace one identity's whole money path through it, and the five forensic lenses on top.
//
// Anchors are hero/sidebar/toolbar elements that render regardless of query results, so the
// tour never strands on an empty search. The chain window controls (older / newer) only
// exist in aggregate mode, so they are DESCRIBED at the aggregate step rather than anchored.
export const eventLedgerTour: GuidedTour = {
  id: 'event-ledger',
  title: 'The Event Ledger',
  subtitle: 'Where every movement is written down, and how to read it back',
  icon: 'mdi:database-search',
  accent: '#22d3ee',
  estMinutes: 6,
  requireAdmin: true,
  requireFlag: 'platform',
  steps: [
    {
      id: 'intro', title: 'The ledger under everything', placement: 'center',
      body: 'Every balance in this network is a **replay of events**, not a number someone ' +
        'edited. Mints, transfers, locks, fees, escrow legs and cross-frame hops are all ' +
        'appended to an immutable log, and the balances you see elsewhere are derived from it.\n\n' +
        'That is why the supply invariant can be checked at all: there is a single written ' +
        'record to check against. This tour shows you how to read it.',
    },
    {
      id: 'hero', title: 'EventStore Explorer', anchor: 'events-hero', placement: 'bottom', route: '/admin/events',
      body: 'The raw log, newest first. Nothing here is editable — the ledger is **append-only** ' +
        'by design, so this view is a reading instrument, not a control panel.',
    },
    {
      id: 'frame', title: 'Which ledger you are reading', anchor: 'events-frame', placement: 'right',
      body: 'Every sovereign frame keeps its **own** EventStore. This picker shows your local ' +
        'registry plus any sibling frame whose admin you have connected in the Multi-Frame ' +
        'Console.\n\nThere are no hardcoded frame letters here: a single-frame deployment sees ' +
        'exactly one entry, correctly labelled with its own name.',
    },
    {
      id: 'toolbar', title: 'What you are looking at', anchor: 'events-toolbar', placement: 'bottom',
      body: 'The strip states the query in words: how many rows, out of how many total, from ' +
        'which frame, under which filters. When a result set is capped for responsiveness it ' +
        'says so with an amber pill rather than quietly truncating.',
    },
    {
      id: 'aggregate', title: 'Follow one identity', anchor: 'events-aggregate', placement: 'right',
      body: 'Paste an agent DID here and you get that identity\'s **entire money path** — every ' +
        'event it was ever party to, in order.\n\nChains are fetched in bounded windows of about ' +
        '30 days, because real aggregates reach into the **millions** of events. Once you are in ' +
        'a chain the toolbar grows `older` / `newer` / `latest` controls to step through history, ' +
        'and it tells you when a window was capped or when it skipped ahead to the last window ' +
        'that actually had activity.',
    },
    {
      id: 'results', title: 'The rows themselves', anchor: 'events-results', placement: 'left',
      body: 'Each row carries its type, aggregate, timestamp and payload. Financial events also ' +
        'carry the **idempotency key** the emitter used, which is how the same logical transfer ' +
        'emitted from two registries is deduplicated into exactly one ledger entry.',
    },
    {
      id: 'saved', title: 'Saved searches', anchor: 'events-saved', placement: 'right',
      body: 'Investigations repeat. Save the query you had to build at 2am and it is one click ' +
        'next time.',
    },
    {
      id: 'export', title: 'Take it away', anchor: 'events-export', placement: 'right',
      body: 'Export the current result set as JSON — for a spreadsheet, a regulator, or a diff ' +
        'against another frame.',
    },
    {
      id: 'forensics', title: 'Forensics: questions, not rows', anchor: 'forensics-hero', placement: 'bottom',
      route: '/admin/forensics',
      body: 'The Explorer answers **"what happened?"**. Forensics answers the questions you ' +
        'actually arrive with: where is money stuck, what path did this take, what is this node ' +
        'allowed to emit.',
    },
    {
      id: 'tabs', title: 'Five lenses', anchor: 'forensics-tabs', placement: 'bottom',
      body: 'Stuck Funds, Query, Trace, Findings and Emission Policy. Each loads its own data ' +
        'only when you open it, so the page stays quick on a ledger with tens of millions of rows.',
    },
    {
      id: 'stuck', title: 'Stuck funds', anchor: 'forensics-tab-stuck', placement: 'bottom',
      cta: { label: 'Open Stuck Funds', do: 'click-anchor' },
      body: 'The most useful tab, and the least obvious.\n\nMoney can be **parked** without being ' +
        'lost: a cross-frame transfer whose final leg failed leaves funds sitting in a router ' +
        'account. The supply invariant stays perfectly at zero, because parked is not burned — ' +
        'which means **nothing alerts**. This tab is how that class becomes visible instead of ' +
        'silently ageing.',
    },
    {
      id: 'trace', title: 'Trace a path', anchor: 'forensics-tab-trace', placement: 'bottom',
      cta: { label: 'Open Trace', do: 'click-anchor' },
      body: 'Give it an aggregate and it reconstructs the route the money took, hop by hop, ' +
        'including the cross-frame legs that live in a different frame\'s ledger entirely.',
    },
    {
      id: 'policy', title: 'Who may write what', anchor: 'forensics-tab-policy', placement: 'bottom',
      cta: { label: 'Open Emission Policy', do: 'click-anchor' },
      body: 'Each financial event type declares which layer is allowed to emit it. The registry ' +
        'and the TEG deliberately fail in **opposite directions** — the registry defaults to ' +
        'allow, the TEG defaults to deny — so this table is best read as a partition of ' +
        'responsibility, not a complete inventory of events.\n\nChanging a row changes what the ' +
        'ledger records, so treat it as a supply-affecting edit.',
    },
    {
      id: 'outro', title: 'The habit worth forming', placement: 'center',
      body: 'When a number looks wrong anywhere in the product, the answer is in here — because ' +
        'this is the thing the number was derived from.\n\nNext: the **API tutorial track** for ' +
        'the same ground, if you would rather query the ledger from code than from a page.',
    },
  ],
}
