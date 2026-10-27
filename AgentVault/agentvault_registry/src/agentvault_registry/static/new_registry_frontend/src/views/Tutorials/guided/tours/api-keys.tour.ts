import type { GuidedTour } from '../tour.types'

// API Keys — "A Bearer token for your scripts". Walks the real API Keys page: existing keys
// (+ revoke), the MCP-bridge usage, then minting a new one (click-anchor opens the create
// modal so the description field spotlights for real). The one-time secret only renders after
// an actual create, so that step gracefully falls back to a centered card. The page-level
// stops come BEFORE the modal opens so the modal never occludes a later spotlight.
// `/api-keys` isn't in the sidebar, so the first stop relies on route navigation.
// Anchors are added as data-tour attrs in ApiKeys.vue.
export const apiKeysTour: GuidedTour = {
  id: 'api-keys',
  title: 'API Keys',
  subtitle: 'Long-lived credentials for scripts, CI and the MCP bridge',
  icon: 'mdi:key',
  accent: '#eab308',
  estMinutes: 3,
  steps: [
    {
      id: 'intro', title: 'What is an API key?', placement: 'center',
      body: 'An **API key** is a long-lived credential for programmatic access — you send it as `Authorization: Bearer avreg_…` and the registry knows it\'s you. Keys act with **your developer permissions**, so treat them like passwords.\n\nThis tour walks the real **API Keys** page. **Next** to begin.',
    },
    {
      id: 'hero', title: 'Your API keys', anchor: 'key-hero', placement: 'bottom', route: '/api-keys',
      body: 'This is the **API Keys** page. Keys let scripts, CI jobs and the **MCP bridge** talk to the registry on your behalf — no interactive login, no password baked into your code.',
    },
    {
      id: 'list', title: 'Existing keys & revoking', anchor: 'key-list', placement: 'auto',
      body: 'Your keys live here — each shows its **prefix** (`avreg_…`), when it was **created** and **last used**, and an **active** badge. The full secret is never shown again. To retire one, hit the **trash** icon — revoking is instant and permanent. *(No keys yet? You\'ll create one in a moment.)*',
    },
    {
      id: 'usage', title: 'Using a key', anchor: 'key-usage', placement: 'top',
      body: 'Below the list is the **MCP Bridge** card — paste-ready config to plug TheProtocol into **Claude Code** or **Claude Desktop**. Download the bridge, drop your key into `THEPROTOCOL_API_KEY`, and your client gets the tool suite. Anywhere else, just send the key as an `Authorization: Bearer` header.',
    },
    {
      id: 'new', title: 'Create a new key', anchor: 'key-new', placement: 'left',
      body: 'Let\'s create one. **Create New Key** opens a short form. *(The **API Documentation** link below has the full request reference.)*',
      cta: { label: 'Open the form →', do: 'click-anchor' },
    },
    {
      id: 'name', title: 'Describe it', anchor: 'key-name', placement: 'bottom',
      body: 'Give the key a **description** — something like **"CI deploy bot"** or **"laptop MCP bridge"** — so you can recognise it later in the list. Then **Create API Key**.',
    },
    {
      // key-reveal is DATA-DEPENDENT (renders only right after a key is actually minted;
      // the tour deliberately never mints a real credential) — fall back to the form.
      id: 'reveal', title: 'Copy it — once', anchor: 'key-reveal,key-name', placement: 'bottom',
      body: 'The instant you create it, the full key — `avreg_…` — is shown **exactly once**. **Copy it immediately**: it\'s stored only as a hash, so if you lose it you must revoke and create a new one. Right after, it appears in your list above (prefix only).',
    },
    {
      id: 'outro', title: 'Keys, handled', placement: 'center',
      body: 'That\'s API keys end-to-end: **create → copy once → use as a Bearer token → revoke when done**. Keep them secret, give each integration its own, and rotate freely.\n\nClose the form and create your first key whenever you\'re ready.',
    },
  ],
}
