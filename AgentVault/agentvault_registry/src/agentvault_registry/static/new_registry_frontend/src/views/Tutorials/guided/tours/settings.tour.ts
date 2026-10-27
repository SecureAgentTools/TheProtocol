import type { GuidedTour } from '../tour.types'

// §OPGUIDE-8 (2026-07-31) — Settings: the two credentials you actually hand out.
//
// Commander asked for ONE tutorial covering both: minting an API key (a credential for
// yourself — scripts, CI, the MCP bridge) and minting an invitation code (a credential
// for someone else — how a new person gets an account at all). They live two tabs apart
// in Settings and were never taught together.
//
// Anchors: `set-tab-*` (Settings.vue tab strip, bound from tab.key), `set-create-key` /
// `set-key-list` (API tab), and `inv-*` (InvitationsPanel.vue).
//
// GRACEFUL BY DESIGN: the Invitations tab only exists where registration actually
// requires an invite code AND the viewer can administer them — true on the Hetzner frame
// and op-demo, false on registry-a today. Where it is absent those steps fall back to the
// centred explanation, so the bodies below are written to read correctly either way
// rather than promising a highlight that cannot appear.
export const settingsTour: GuidedTour = {
  id: 'settings',
  title: 'Keys & Invitations',
  subtitle: 'Create an API key for yourself, an invite code for someone else',
  icon: 'mdi:key-plus',
  accent: '#7dd3fc',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Two kinds of credential', placement: 'center',
      body: 'Settings holds the two credentials you hand out.\n\n' +
        '**An API key** is for **you** — a long-lived token so a script, a CI job or the MCP bridge ' +
        'can act as your developer account without your password.\n\n' +
        '**An invitation code** is for **someone else** — on a registry that gates registration, it is ' +
        'the only way a new person gets an account at all.\n\nThis tour creates one of each.',
    },
    {
      id: 'open', title: 'Settings', anchor: 'set-tab-profile', placement: 'bottom', route: '/settings',
      body: 'Everything about **your account** lives here, one tab per concern. We only need two of them.',
    },

    // ── API key ──────────────────────────────────────────────────────────
    {
      id: 'api-tab', title: 'API Keys', anchor: 'set-tab-api', placement: 'bottom',
      body: 'Open **API Keys**. The badge counts the keys you already hold.',
      cta: { label: 'Open API Keys', do: 'click-anchor' },
    },
    {
      id: 'api-create', title: 'Create a key', anchor: 'set-create-key', placement: 'left',
      body: 'One click creates a key. Give it a **description you will recognise months from now** ' +
        '("laptop MCP bridge", "nightly backup job") — that label is how you will know which one to ' +
        'revoke later.\n\n⚠️ The key is shown **once**, at creation. Copy it then; it is stored hashed ' +
        'and cannot be shown again. Lose it and you create a new one.',
    },
    {
      id: 'api-list', title: 'What you already hold', anchor: 'set-key-list,set-create-key', placement: 'auto',
      body: 'Every live key is listed with its prefix, description and last use. **Revoke** kills one ' +
        'instantly — do that the moment a laptop is lost or a job is retired, rather than rotating ' +
        'everything in a panic later.\n\nKeys default to full authority and a one-year expiry.',
    },

    // ── spend approvals (B3, RBAC plan) ──────────────────────────────────
    {
      id: 'appr-tab', title: 'Approvals', anchor: 'set-tab-approvals', placement: 'bottom',
      body: 'When one of your agents tries to spend **over its approval threshold**, the spend ' +
        'no longer just fails — it **parks here** and your phone gets a push. You are the step-up.',
      cta: { label: 'Open Approvals', do: 'click-anchor' },
    },
    {
      id: 'appr-queue', title: 'The step-up queue', anchor: 'spend-approvals-panel,set-tab-approvals', placement: 'auto',
      body: 'Each parked ask shows **who wants to spend what, to whom**. **Approve** arms a ' +
        'single-use authorization for 15 minutes — the agent\'s retry of that exact spend consumes ' +
        'it once. **Deny**, or 30 minutes of silence, keeps the block.\n\nSet the threshold ' +
        'per-agent in its Access panel ("Require approval above").',
    },

    // ── invitation codes ─────────────────────────────────────────────────
    {
      id: 'inv-tab', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Invitations', anchor: 'set-tab-invitations', placement: 'bottom',
      body: 'Now the other credential. **Invitations** appears only when this registry actually ' +
        'requires an invite code to register **and** your account may administer them.\n\n' +
        '*Not seeing the tab? Then registration here is open and there is nothing to gate — the rest ' +
        'of this tour still explains what it does.*',
      cta: { label: 'Open Invitations', do: 'click-anchor' },
    },
    {
      // §TOURTRUTH (2026-09-02) — the Invitations tab exists only where the registry requires invites AND the account may administer them; `inv-tab` keeps its honest centred card, the four behind it are skipped.
      id: 'inv-form', optional: true, title: 'Create a code', anchor: 'inv-form', placement: 'auto',
      body: 'Choose **how many** codes, **how many times each may be used** (1 = single-use, the safe ' +
        'default), an optional **expiry**, and a **note** for your own records — "Team Technik", ' +
        '"conference booth". The note is the only thing that will tell you later who a code was for.',
    },
    {
      id: 'inv-admin', optional: true, title: 'Administrator codes', anchor: 'inv-admin-toggle', placement: 'auto',
      body: 'This switch is the important one. Leave it **off** and the code creates an ordinary ' +
        'developer.\n\nTurn it **on** and whoever redeems the code becomes a **full administrator** the ' +
        'moment they register — `is_admin` plus all five granular admin flags. That is how you hand a ' +
        'registry its first administrator **without creating the account yourself**: they register, ' +
        'choose their own password and accept the terms, so no password ever travels and you never ' +
        'know their credentials.\n\nIt asks for confirmation before creating, on purpose.',
    },
    {
      id: 'inv-mint', optional: true, title: 'Create it', anchor: 'inv-mint', placement: 'top',
      body: 'Creating them shows the fresh codes with a **copy button for the code and for a ready-made ' +
        'registration link** — the link already carries the code, so the sign-up form pre-fills it. ' +
        'Send the link and nothing else needs explaining.',
    },
    {
      id: 'inv-list', optional: true, title: 'Who used what', anchor: 'inv-list,inv-filters', placement: 'auto',
      body: 'Every code is listed as **active**, **used** or **inactive** (expired), with when it was ' +
        'created, **by whom**, and **who redeemed it and when**. Filter by status along the top.\n\n' +
        '**Revoke** deletes an unused code permanently — anyone holding it can no longer register. ' +
        'A code that has already been redeemed is history, not a live grant, so it has no revoke button.',
    },
    {
      id: 'outro', title: 'Both credentials, handled', placement: 'center',
      body: 'You can now let a machine act as you (**API key**) and let a person in at all ' +
        '(**invitation code**).\n\nTwo habits worth keeping: describe every key so future-you knows what ' +
        'it is, and prefer **single-use** invite codes so one leaked link cannot become five accounts.\n\n' +
        'Everything here is also available over the API — see `/docs` on this registry.',
    },
  ],
}
