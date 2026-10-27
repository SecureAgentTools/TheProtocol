import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — OPERATOR SERIES 6/6: connect an AI assistant over MCP.
//
// Mirrors operator docs chapter 13. Reuses the settings tour's API-tab anchors
// (set-tab-api, set-create-key, set-key-list). The Operator Docs view lives OUTSIDE
// DashboardLayout — routing there would unmount the tour overlay (§OPGUIDE-7 class), so
// the docs are referenced by URL in text, never navigated to.
export const opAssistantTour: GuidedTour = {
  id: 'op-assistant',
  title: 'Operator: Connect Your Assistant',
  subtitle: 'Your registry speaks MCP — wire up Claude in five minutes',
  icon: 'mdi:robot-outline',
  accent: '#34d399',
  estMinutes: 4,
  requireAdmin: true,
  steps: [
    {
      id: 'intro', title: 'The registry documents itself', placement: 'center',
      body: 'Every registry ships its own **MCP server** and a manual written for machines:\n\n' +
        '`GET /api/v1/downloads/CLAUDE.md`\n\nreturns an operator manual with **this** ' +
        'deployment\'s URL, name, role and currency already filled in. Paste it into any ' +
        'assistant and it knows your node without guessing. This tour creates the credential ' +
        'and points at the wiring.',
    },
    {
      id: 'api-tab', title: 'The credential is an API key', anchor: 'set-tab-api', placement: 'bottom', route: '/settings',
      body: 'MCP authenticates with a **developer API key** (`avreg_…`), created here in ' +
        'Settings. The key acts as **you**: your tier, your admin areas. Treat it like a ' +
        'password — and scope or expire it if the assistant does not need everything.',
    },
    {
      id: 'mint', title: 'Create it once, shown once', anchor: 'set-create-key,set-tab-api', placement: 'bottom',
      body: 'Name the key for its purpose ("claude bridge") and create it. The plaintext is shown ' +
        '**exactly once** — it is stored hashed. Defaults are full scopes and a one-year ' +
        'expiry; both can be narrowed at creation time.',
    },
    {
      id: 'wire', title: 'Wire up Claude Code or Desktop', placement: 'center',
      body: 'Download the bridge **from your own registry** — ' +
        '`/api/v1/downloads/mcp-stdio-bridge.js` — and register it in `.mcp.json` with two ' +
        'env vars: `THEPROTOCOL_API_URL` (your registry) and `THEPROTOCOL_API_KEY` (the key ' +
        'you just created).\n\nThe admin surface has its own bridge file; the code is public ' +
        'on purpose — all authority lives in the key.',
    },
    {
      id: 'catalog', title: 'Keep the catalog small', placement: 'center',
      body: 'The full tool catalog is **hundreds of tools**. Clients with limited context ' +
        'can append `?mode=gateway` to the MCP endpoint: the server then lists a compact ' +
        'core plus search/describe/invoke tools, and the assistant discovers the rest on ' +
        'demand. `?toolsets=wallet,discovery` narrows to named buckets instead.',
    },
    {
      id: 'audit', title: 'Watch what it does', anchor: 'audit-hero', placement: 'bottom', route: '/admin/audit-logs',
      body: 'With `MCP_AUDIT_LOGGING_ENABLED=true` in your env file, **every tool call** an ' +
        'assistant makes writes a security-audit row here — as traceable as a human click. ' +
        'The flag ships off; turn it on before handing keys to automation you do not fully ' +
        'control.',
    },
    {
      id: 'outro', title: 'Assistant, connected', placement: 'center',
      body: 'Manual served, key created, bridge wired, audit on.\n\nThe full walkthrough — ' +
        'including `tp mcp serve` for **host** operations and the resources/prompts the ' +
        'server publishes — is **Operator Docs, chapter 13** (menu → Operator Docs).',
    },
  ],
}
