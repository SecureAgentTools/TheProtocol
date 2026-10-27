<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * CommandPalette.vue — global Cmd-K / Ctrl-K palette (Build #16, 2026-05-08).
 *
 * Mounted once at the App.vue root. Bound to the window-level keydown so it
 * works from anywhere. Rendered via Teleport to body so the modal escapes any
 * stacking context (matches the ConfirmActionModal z-index 10100 pattern).
 *
 * Commands surface:
 *  - Navigate (every sidebar route)
 *  - Theme (switch + cycle + open Theme Studio)
 *  - Action (reload, toggle sidebar, log out)
 *  - Lookup (DID-shaped or hex-shaped query → drilldown into agent/EventStore)
 *  - Recent (last 5 navigations, persisted in localStorage)
 *
 * Keyboard:
 *  - Cmd-K / Ctrl-K     toggle open
 *  - /                   open (when not typing in another input)
 *  - Escape              close
 *  - ↑ / ↓               select prev/next
 *  - Enter               run selected
 *
 * Defers on /oracle (OracleView has its own scoped Cmd-K palette for docs).
 */
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { usePermissions } from '@/composables/usePermissions'
import { feeCollectorAdminService } from '@/services/api/feeCollectorAdmin'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { useLogger } from '@/composables/useLogger'
import { useRegistryConfig } from '@/composables/useRegistryConfig'

const router = useRouter()
const route = useRoute()
const ui = useUIStore()
const auth = useAuthStore()
const perms = usePermissions()
// a door opens only where the registry says the room is there: the lock page only where staking_enabled is true
const { config: registryConfig, localCurrency } = useRegistryConfig()   // D6-835: /mint and /distribute move this frame's unit
const log = useLogger('CommandPalette')

interface CommandDef {
  id: string
  title: string
  description?: string
  icon?: string
  group: 'Recent' | 'Navigate' | 'Theme' | 'Action' | 'Lookup' | 'Slash'
  keywords?: string[]
  requiresAdmin?: boolean
  /** Optional path used by Recent + nav-direct-route shortcut. */
  path?: string
  run: () => void
}

// #7 (2026-05-08): slash-command pending state. The ConfirmActionModal is
// rendered from this component (not from AdminTreasury) so the slash flow
// stays self-contained — no navigation, no view-mounted modal hand-off.
type SlashKind = 'mint' | 'distribute'
interface PendingSlash {
  kind: SlashKind
  amount: string         // string for Decimal precision (passed straight to API)
  targetDid: string      // for mint + distribute
  reason: string         // mint: admin_grant by default; distribute: required positional
  preview: string        // human-readable summary for the modal body
}
const pendingSlash = ref<PendingSlash | null>(null)
const slashBusy = ref(false)

const open = ref(false)
const query = ref('')
const selectedIdx = ref(0)
const inputRef = ref<HTMLInputElement | null>(null)

const RECENT_KEY = 'theprotocol:cmdk:recent'
const recent = ref<string[]>([])

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (raw) recent.value = JSON.parse(raw)
  } catch { /* non-fatal */ }
}
function pushRecent(id: string) {
  recent.value = [id, ...recent.value.filter(x => x !== id)].slice(0, 5)
  try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent.value)) } catch { /* non-fatal */ }
}

// ── Navigation entries ─────────────────────────────────────────────────────
// Routes derived from router/index.ts. requiresAdmin=true means is_admin OR
// any admin sub-flag (server still enforces; this is just for visibility).
const NAV_DEFS: { id: string; title: string; description?: string; icon: string; path: string; requiresAdmin?: boolean; requiresRegistryFlag?: 'staking_enabled'; keywords?: string[] }[] = [
  { id: 'nav:dashboard',   title: 'Dashboard',           description: 'Mission Control overview',   icon: 'mdi:view-grid', path: '/mission-control' },
  { id: 'nav:my-agents',   title: 'My Agents',           description: 'Your agents · balance · statement · payment authorizations', icon: 'mdi:robot', path: '/my-agents', keywords: ['balance', 'statement', 'a2a'] },
  { id: 'nav:discover',    title: 'Discover Agents',     description: 'Search the federation',      icon: 'mdi:magnify', path: '/discover' },
  { id: 'nav:contracts',   title: 'Contracts',           description: 'Service contracts',          icon: 'mdi:scroll-text', path: '/contracts' },
  { id: 'nav:disputes',    title: 'Disputes',            description: 'File or respond',            icon: 'mdi:scale-balance', path: '/disputes' },
  { id: 'nav:settlements', title: 'Settlements',         description: 'Cross-registry compensation',icon: 'mdi:cash-multiple', path: '/settlements' },
  { id: 'nav:exchange',    title: 'AGORA Desk',       description: 'AGORA: trade org points',   icon: 'mdi:chart-candlestick', path: '/agora', keywords: ['trade', 'candles', 'order book', 'stocks', 'exchange', 'agora', 'shares', 'ipo', 'dividends', 'points', 'launch', 'distributions', 'agora desk'] },
  { id: 'nav:exchange-admin', title: 'AGORA Admin',   description: 'AGORA market command: invariants, listings, halt', icon: 'mdi:scale-balance', path: '/admin/agora', keywords: ['agora', 'venue', 'exchange admin', 'halt', 'invariant', 'listings', 'compliance', 'admin', 'market', 'agora admin'] },
  { id: 'nav:stocks',      title: 'AGORA Listings',     description: 'Federation listings screener: take part across markets', icon: 'mdi:telescope', path: '/agora/listings', keywords: ['stocks', 'equities', 'invest', 'screener', 'passport', 'agora', 'shares', 'points', 'launch', 'market', 'listings', 'agora listings'] },
  { id: 'nav:federation',  title: 'Federation',          description: 'Tiers + topology + ops',     icon: 'mdi:web', path: '/federation', keywords: ['peers', 'topology', 'tiers'] },
  { id: 'nav:webhooks',    title: 'Webhooks',            description: 'Manage your endpoints',      icon: 'mdi:webhook', path: '/webhooks', keywords: ['delivery', 'webhook'] },
  { id: 'nav:agent-builder', title: 'Agent Builder',     description: 'Scaffold a new agent',       icon: 'mdi:tools', path: '/agent-builder' },
  { id: 'nav:tutorials',   title: 'Tutorials',           description: 'Guided tracks',              icon: 'mdi:book-open-variant', path: '/tutorials' },
  { id: 'nav:onboarding',  title: 'Quick onboarding',    description: 'Issue an agent identity',    icon: 'mdi:creation', path: '/onboarding', keywords: ['identity', 'did', 'agent card', 'credentials', 'reset', 'client secret', 'new agent'] },
  { id: 'nav:settings',    title: 'Settings',            description: 'Profile, security, theme',   icon: 'mdi:cog', path: '/settings', keywords: ['theme', 'preferences', 'api keys'] },
  { id: 'nav:api-keys',    title: 'API Keys',            description: 'Generate + revoke keys',     icon: 'mdi:key', path: '/api-keys' },
  { id: 'nav:staking',     title: 'Locks',               description: 'Lock positions and governance weight', icon: 'mdi:wallet', path: '/locks', requiresRegistryFlag: 'staking_enabled' },
  { id: 'nav:senate',      title: 'Governance',          description: 'Proposals · votes',          icon: 'mdi:bank', path: '/senate', keywords: ['governance', 'proposals'] },
  { id: 'nav:command-center', title: 'Command Center',   description: 'Diagnostics and remediation', icon: 'mdi:radar', path: '/command-center', requiresAdmin: true },
  { id: 'nav:galactic-command', title: 'Galactic Command', description: 'Fleet map cockpit — command any registry', icon: 'mdi:crosshairs-gps', path: '/galactic-command', requiresAdmin: true, keywords: ['gcc', 'bridge', 'fleet', 'galactic'] },
  { id: 'nav:health',      title: 'Health Monitor',      description: 'Cluster health',             icon: 'mdi:heart-pulse', path: '/health-monitor' },
  { id: 'nav:eigentrust',  title: 'EigenTrust Command',  description: 'Reputation graph',           icon: 'mdi:brain', path: '/eigentrust-command' },
  { id: 'nav:leaderboard', title: 'Reputation Leaderboard', description: 'Top agents (public)',     icon: 'mdi:trophy', path: '/leaderboard', keywords: ['top', 'reputation'] },
  { id: 'nav:galactic-map',title: 'Galactic Map',        description: 'Federation 3D',              icon: 'mdi:telescope', path: '/galactic-map' },
  { id: 'nav:agentworld',  title: 'AgentWorld',          description: 'Geo-located agents',         icon: 'mdi:map', path: '/agentworld' },

  // ── Admin watchtower views (gated) ──
  { id: 'nav:admin-events',     title: 'Event Ledger',          description: 'EventStore Explorer (Frame A/B)', icon: 'mdi:scroll-text', path: '/admin/events',  requiresAdmin: true, keywords: ['eventstore', 'events', 'ledger'] },
  { id: 'nav:admin-treasury',   title: 'Treasury & Fee Audit',  description: 'Issuance · fees · supply Δ',           icon: 'mdi:diamond-stone', path: '/admin/treasury', requiresAdmin: true, keywords: ['issue', 'mint', 'fee collector', 'supply'] },
  { id: 'nav:admin-webhooks',   title: 'Webhook Health',        description: 'Cluster webhook deliveries',       icon: 'mdi:sync', path: '/admin/webhooks-cluster', requiresAdmin: true },
  { id: 'nav:admin-bridge',     title: 'Cross-Frame Bridge',    description: 'Async + SF-3 transfers',           icon: 'mdi:swap-horizontal', path: '/admin/bridge', requiresAdmin: true },
  { id: 'nav:admin-email',      title: 'Email Studio',          description: 'Browse + preview templates',       icon: 'mdi:email-outline', path: '/admin/email', requiresAdmin: true },
  { id: 'nav:admin-settlements',title: 'Settlements Watchtower',description: 'Slash + payment settlements',         icon: 'mdi:cash-multiple', path: '/admin/settlements', requiresAdmin: true },
  { id: 'nav:admin-fed-ops',    title: 'Federation Ops',        description: 'Peer health + drift',              icon: 'mdi:radio-tower', path: '/federation?tab=operations', requiresAdmin: true, keywords: ['peers', 'drift'] },
  { id: 'nav:admin-attest',     title: 'Att. Analytics',        description: 'ZKP attestation analytics',        icon: 'mdi:shield-lock', path: '/admin/attestation-analytics', requiresAdmin: true, keywords: ['zkp', 'attestation'] },
  { id: 'nav:admin-canaries',   title: 'Canaries',              description: 'Synthetic-tx monitor',             icon: 'mdi:radar', path: '/admin/canaries', requiresAdmin: true },
  { id: 'nav:admin-reactors',   title: 'Reactors & Workers',    description: 'Background workers + reactors',    icon: 'mdi:radioactive', path: '/admin/reactors', requiresAdmin: true, keywords: ['workers', 'reactors'] },
  { id: 'nav:admin-mcp-tester', title: 'MCP Tester',            description: 'Full-surface regression sweep',    icon: 'mdi:test-tube', path: '/admin/mcp-tester', requiresAdmin: true, keywords: ['mcp', 'tester', 'sweep', 'regression', 'tools'] },
  { id: 'nav:admin-console-suite', title: 'Console Suite',       description: 'Browser lifecycle runs',           icon: 'mdi:monitor-cellphone', path: '/admin/console-suite', requiresAdmin: true, keywords: ['console', 'suite', 'playwright', 'browser', 'frontend', 'lifecycle'] },
  { id: 'nav:admin-developers', title: 'Developers',            description: 'Developer mgmt + funding triage',  icon: 'mdi:account-group', path: '/admin/developers', requiresAdmin: true },
  { id: 'nav:admin-agents',     title: 'Agent Roster',          description: 'All agents across cluster',        icon: 'mdi:shield-check', path: '/admin/agents', requiresAdmin: true },
  { id: 'nav:admin-ironhand',   title: 'IRONHAND',              description: 'Agent mTLS enrollment',            icon: 'mdi:wrench', path: '/admin/ironhand', requiresAdmin: true },
  { id: 'nav:admin-compliance', title: 'CONSUL',                description: 'Federation compliance',               icon: 'mdi:clipboard', path: '/admin/compliance', requiresAdmin: true },
  { id: 'nav:admin-operators',  title: 'Operator Management',   description: 'Cloud-host applications',          icon: 'mdi:web', path: '/operator-management', requiresAdmin: true },
  { id: 'nav:admin-frames',     title: 'Frame Management',      description: 'Sovereign frame config',           icon: 'mdi:office-building', path: '/frame-management', requiresAdmin: true },
]

// Build full command list reactively
const commands = computed<CommandDef[]>(() => {
  const list: CommandDef[] = []

  // Recent (top of list)
  for (const id of recent.value) {
    const def = NAV_DEFS.find(d => d.id === id)
    if (!def) continue
    if (def.requiresAdmin && !auth.isAdmin) continue
    if (def.requiresRegistryFlag && registryConfig.value?.[def.requiresRegistryFlag] !== true) continue
    list.push({
      id: 'recent:' + def.id, title: def.title, description: def.description,
      icon: def.icon, group: 'Recent', path: def.path,
      run: () => goto(def.path, def.id),
    })
  }

  // Navigate
  for (const def of NAV_DEFS) {
    if (def.requiresAdmin && !auth.isAdmin) continue
    if (def.requiresRegistryFlag && registryConfig.value?.[def.requiresRegistryFlag] !== true) continue
    list.push({
      id: def.id, title: def.title, description: def.description,
      icon: def.icon, group: 'Navigate', path: def.path, keywords: def.keywords,
      run: () => goto(def.path, def.id),
    })
  }

  // Theme
  list.push(
    { id: 'theme:neural',    title: 'Apply Neural theme',    description: 'Cyan accent (built-in)',   icon: '🟦', group: 'Theme', run: () => ui.setBrandTheme('neural'),    keywords: ['cyan', 'theme'] },
    { id: 'theme:sovereign', title: 'Apply Sovereign theme', description: 'Red accent (built-in)',    icon: '🟥', group: 'Theme', run: () => ui.setBrandTheme('sovereign'), keywords: ['red', 'theme'] },
  )
  if (ui.customThemeHex) {
    list.push({ id: 'theme:custom', title: 'Apply Custom theme', description: ui.customThemeHex, icon: '🎨', group: 'Theme', run: () => ui.setBrandTheme('custom'), keywords: ['theme', 'custom'] })
  }
  list.push(
    { id: 'theme:cycle',     title: 'Cycle brand theme',     description: 'Next preset in rotation',  icon: '🔄', group: 'Theme', run: () => ui.cycleBrandTheme(), keywords: ['theme', 'switch'] },
    { id: 'theme:studio',    title: 'Open Theme Studio',     description: 'Customize the brand color',icon: '🎨', group: 'Theme', run: () => goto('/settings'), keywords: ['theme', 'color', 'custom', 'studio'] },
  )

  // Action
  list.push(
    { id: 'action:sidebar',  title: 'Cycle sidebar',         description: 'Expanded → icons → hidden',icon: '◧', group: 'Action', run: () => ui.cycleSidebar(), keywords: ['sidebar', 'collapse'] },
    { id: 'action:reload',   title: 'Reload page',           description: 'Hard refresh (Ctrl-R)',    icon: '↻', group: 'Action', run: () => location.reload() },
  )
  if (auth.isAuthenticated) {
    list.push({ id: 'action:logout', title: 'Log out', description: 'End session and return to login', icon: '🚪', group: 'Action', run: () => { auth.logout(); router.push('/login') }, keywords: ['logout', 'sign out'] })
  }

  // §FEDEVENTS-4: the hardcoded "Switch to Frame A/B" actions are gone — the
  // frame-aware views (Event Ledger, Treasury, FX, Forensics) now offer only
  // the LOCAL frame plus live Multi-Frame Console sessions, so a blind
  // setActiveFrame('B') from the palette was a no-op on most deployments and
  // a wrong-frame surprise on the rest. Frame switching lives in the views'
  // own pickers, scoped to what is actually reachable.

  // ── Slash-commands (#7, 2026-05-08) ──
  // Parsed live from the query so the user sees a typed preview as they go.
  // /mint <amount> to <did:…>
  // /distribute <amount> <reason> to <did:…>
  // /refresh-policy
  // Treasury verbs gated by usePermissions().can('treasury'); no-op (and
  // hidden from the surface) for non-treasury admins.
  const qRaw = query.value.trim()
  const slash = parseSlash(qRaw)
  if (slash) {
    if (slash.kind === 'mint' && perms.can('treasury')) {
      list.push({
        id: 'slash:mint',
        title: `/mint ${slash.amount} ${localCurrency.value} → ${shortDid(slash.targetDid)}`,
        description: `Reason: ${slash.reason} · type the amount in the next step to confirm`,
        icon: '✦',
        group: 'Slash',
        run: () => requestMint(slash.amount, slash.targetDid, slash.reason),
      })
    } else if (slash.kind === 'distribute' && perms.can('treasury')) {
      list.push({
        id: 'slash:distribute',
        title: `/distribute ${slash.amount} ${localCurrency.value} → ${shortDid(slash.targetDid)}`,
        description: `Reason: ${slash.reason} · drains fee_collector first per active waterfall`,
        icon: '⤳',
        group: 'Slash',
        run: () => requestDistribute(slash.amount, slash.targetDid, slash.reason),
      })
    } else if (slash.kind === 'refresh-policy') {
      list.push({
        id: 'slash:refresh-policy',
        title: '/refresh-policy',
        description: 'Re-fetch the payout funding waterfall from /admin/fee-collector/policy',
        icon: '↻',
        group: 'Slash',
        run: () => doRefreshPolicy(),
      })
    }
  }

  // Lookups based on query pattern
  const q = query.value.trim()
  if (q.startsWith('did:')) {
    const short = q.length > 30 ? q.slice(0, 30) + '…' : q
    list.push(
      { id: 'lookup:agent-profile',  title: 'Open agent profile',           description: short, icon: 'mdi:magnify', group: 'Lookup', run: () => goto('/agent-profile/' + encodeURIComponent(q)) },
      { id: 'lookup:agent-events',   title: 'Find aggregate in EventStore', description: short, icon: '🔎', group: 'Lookup', run: () => router.push({ path: '/admin/events', query: { aggregate_id: q } }).catch(() => {}) },
    )
  } else if (q.length >= 8 && /^[0-9a-fA-F-]+$/.test(q) && q.replace(/-/g, '').length >= 16) {
    // UUID-shaped or longer hex — likely a tx id / agg id
    list.push({
      id: 'lookup:eventstore-aggregate',
      title: 'Find aggregate in EventStore',
      description: q.slice(0, 30) + (q.length > 30 ? '…' : ''),
      icon: '🔎',
      group: 'Lookup',
      run: () => router.push({ path: '/admin/events', query: { aggregate_id: q } }).catch(() => {}),
    })
  }

  return list
})

function goto(path: string, recentId?: string) {
  if (recentId) pushRecent(recentId)
  // Special: paths with ?tab=... need router.push with object form to preserve query
  const [base, qstr] = path.split('?')
  if (qstr) {
    const q: Record<string, string> = {}
    qstr.split('&').forEach(kv => { const [k, v] = kv.split('='); q[k] = v ?? '' })
    router.push({ path: base, query: q }).catch(() => {})
  } else {
    router.push(base).catch(() => {})
  }
}

// ── Filtering / scoring ────────────────────────────────────────────────────
function score(cmd: CommandDef, q: string): number {
  // Lookup + Slash commands are SYNTHESIZED in response to the query.
  // They're already relevance-gated by their existence — give them a high
  // baseline so they always surface above title-matched items.
  if (cmd.group === 'Slash') return 250
  if (cmd.group === 'Lookup') return 200
  if (!q) return 1
  const ql = q.toLowerCase()
  const tl = cmd.title.toLowerCase()
  const dl = (cmd.description || '').toLowerCase()
  if (tl.startsWith(ql)) return 100
  if (tl.split(/\s+/).some(w => w.startsWith(ql))) return 70
  if (tl.includes(ql)) return 40
  if ((cmd.keywords || []).some(k => k.toLowerCase().includes(ql))) return 35
  if (dl.includes(ql)) return 20
  return 0
}

// ── Slash-command parser (#7, 2026-05-08) ──────────────────────────────────
// Forms accepted:
//   /mint <amount> to <did:…>
//   /distribute <amount> <reason> to <did:…>
//   /refresh-policy
// Reason on /mint is optional (defaults to 'admin_grant'); /distribute requires
// it because the waterfall lookup is keyed by reason. Returns null when the
// query isn't slash-shaped or fails to parse — the surface stays out of the
// palette unless the slash is recognizable.
type ParsedSlash =
  | { kind: 'mint';  amount: string; targetDid: string; reason: string }
  | { kind: 'distribute'; amount: string; targetDid: string; reason: string }
  | { kind: 'refresh-policy' }
  | null

const SLASH_NUM = '[0-9]+(?:\\.[0-9]+)?'
const SLASH_DID = 'did:[a-zA-Z0-9_:-]+'

function parseSlash(input: string): ParsedSlash {
  if (!input.startsWith('/')) return null
  const text = input.trim()

  if (/^\/refresh-policy$/i.test(text)) return { kind: 'refresh-policy' }

  // /mint <amount> to <did:…>           → reason defaults to admin_grant
  // /mint <amount> <reason> to <did:…>  → explicit reason
  let m = text.match(new RegExp(`^/mint\\s+(${SLASH_NUM})\\s+(?:([a-z_]+)\\s+)?to\\s+(${SLASH_DID})$`, 'i'))
  if (m) {
    return {
      kind: 'mint',
      amount: m[1],
      reason: (m[2] || 'admin_grant').toLowerCase(),
      targetDid: m[3],
    }
  }

  // /distribute <amount> <reason> to <did:…>
  m = text.match(new RegExp(`^/distribute\\s+(${SLASH_NUM})\\s+([a-z_]+)\\s+to\\s+(${SLASH_DID})$`, 'i'))
  if (m) {
    return {
      kind: 'distribute',
      amount: m[1],
      reason: m[2].toLowerCase(),
      targetDid: m[3],
    }
  }

  return null
}

function shortDid(did: string): string {
  if (!did) return ''
  return did.length > 28 ? did.slice(0, 14) + '…' + did.slice(-10) : did
}

function requestMint(amount: string, targetDid: string, reason: string) {
  pendingSlash.value = {
    kind: 'mint',
    amount,
    targetDid,
    reason,
    preview: `Issue <strong>${amount} ${localCurrency.value}</strong> from void → ${shortDid(targetDid)} · reason: <code>${reason}</code>. Registry emits <code>TokensIssued</code>. To confirm, type the amount.`,
  }
  // Close the palette so the modal owns focus
  closePalette()
}

function requestDistribute(amount: string, targetDid: string, reason: string) {
  pendingSlash.value = {
    kind: 'distribute',
    amount,
    targetDid,
    reason,
    preview: `Distribute <strong>${amount} ${localCurrency.value}</strong> → ${shortDid(targetDid)} · reason: <code>${reason}</code>. Active waterfall drains fee_collector first, then treasury. To confirm, type the amount.`,
  }
  closePalette()
}

function closeSlashModal() {
  if (slashBusy.value) return
  pendingSlash.value = null
}

async function executeSlash() {
  const ps = pendingSlash.value
  if (!ps || slashBusy.value) return
  slashBusy.value = true
  try {
    if (ps.kind === 'mint') {
      const result = await feeCollectorAdminService.mint({
        target_agent_did: ps.targetDid,
        amount: ps.amount,
        reason: ps.reason,
      })
      ui.showSuccess?.(
        'Issuance complete',
        `${ps.amount} ${localCurrency.value} → ${shortDid(ps.targetDid)} · tx ${result.transaction_id}`,
      )
    } else if (ps.kind === 'distribute') {
      const result = await feeCollectorAdminService.distribute({
        target_agent_did: ps.targetDid,
        amount: ps.amount,
        reason: ps.reason,
      })
      ui.showSuccess?.(
        'Distribute complete',
        `${ps.amount} ${localCurrency.value} → ${shortDid(ps.targetDid)} · fee_collector now ${result.new_fee_collector_balance}`,
      )
    }
    pendingSlash.value = null
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    const msg = err?.response?.data?.detail || err?.message || 'Slash command failed'
    ui.showError?.('Slash command failed', msg)
    log.warn('executeSlash failed', e)
  } finally {
    slashBusy.value = false
  }
}

async function doRefreshPolicy() {
  try {
    const policy = await feeCollectorAdminService.getPolicy()
    const reasonCount = Object.keys(policy.policy || {}).length
    ui.showSuccess?.(
      'Funding policy refreshed',
      `${reasonCount} reason${reasonCount === 1 ? '' : 's'} · default ${policy.default_waterfall.join(' → ')}`,
    )
    closePalette()
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    ui.showError?.('Refresh failed', err?.response?.data?.detail || err?.message || 'Failed to refresh the funding policy')
  }
}

const filteredCommands = computed(() => {
  const q = query.value.trim()
  if (!q) return commands.value.slice(0, 30)
  return commands.value
    .map(c => ({ c, s: score(c, q) }))
    .filter(x => x.s > 0)
    .sort((a, b) => b.s - a.s)
    .slice(0, 30)
    .map(x => x.c)
})

const groupedFiltered = computed(() => {
  const out: { group: string; items: CommandDef[]; firstIdx: number }[] = []
  let idx = 0
  for (const c of filteredCommands.value) {
    let g = out.find(x => x.group === c.group)
    if (!g) { g = { group: c.group, items: [], firstIdx: idx }; out.push(g) }
    g.items.push(c)
    idx++
  }
  return out
})

// ── Keyboard ───────────────────────────────────────────────────────────────
function isTypingTarget(t: EventTarget | null): boolean {
  if (!t || !(t instanceof HTMLElement)) return false
  return t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable
}

function onKeyDown(e: KeyboardEvent) {
  // Defer global Cmd-K on /oracle (its scoped palette overrides global for docs).
  if (route.path.startsWith('/oracle')) return

  // Cmd-K / Ctrl-K toggles
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    if (open.value) closePalette()
    else openPalette()
    return
  }

  // '/' opens (when not typing in another input)
  if (!open.value && e.key === '/' && !isTypingTarget(e.target) && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    openPalette()
    return
  }

  if (!open.value) return

  if (e.key === 'Escape') {
    e.preventDefault(); closePalette(); return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    selectedIdx.value = Math.min(selectedIdx.value + 1, filteredCommands.value.length - 1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    selectedIdx.value = Math.max(selectedIdx.value - 1, 0)
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    runSelected()
    return
  }
}

function openPalette() {
  open.value = true
  query.value = ''
  selectedIdx.value = 0
  loadRecent()
  nextTick(() => inputRef.value?.focus())
}

function closePalette() {
  open.value = false
}

function runSelected() {
  const cmd = filteredCommands.value[selectedIdx.value]
  if (!cmd) return
  cmd.run()
  closePalette()
}

function runCommand(cmd: CommandDef) {
  cmd.run()
  closePalette()
}

// Reset selection when filter shrinks
watch(filteredCommands, (list) => {
  if (selectedIdx.value >= list.length) selectedIdx.value = Math.max(0, list.length - 1)
})

// Hotkey listener (window-level so it works from anywhere)
onMounted(() => {
  window.addEventListener('keydown', onKeyDown)
  loadRecent()
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeyDown)
})

// ── Mouse helpers ───────────────────────────────────────────────────────────
function findFlatIndex(item: CommandDef): number {
  return filteredCommands.value.indexOf(item)
}
</script>

<template>
  <Teleport to="body">
    <transition name="cmdk-fade">
      <div v-if="open" class="cmdk-overlay" @click.self="closePalette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="cmdk-modal" :class="{ 'cmdk-modal--has-results': filteredCommands.length > 0 }">

          <!-- Search bar -->
          <div class="cmdk-search">
            <span class="cmdk-search-icon"><Icon name="mdi:magnify" /></span>
            <input
              ref="inputRef"
              v-model="query"
              type="text"
              class="cmdk-search-input"
              placeholder="Search · type a DID, transaction ID, or any feature…"
              autocomplete="off"
              spellcheck="false"
              aria-label="Command search"
            />
            <span class="cmdk-search-shortcut">esc</span>
          </div>

          <!-- Results -->
          <div v-if="filteredCommands.length > 0" class="cmdk-results" role="listbox">
            <div v-for="grp in groupedFiltered" :key="grp.group" class="cmdk-group">
              <div class="cmdk-group-label">{{ grp.group }}</div>
              <button
                v-for="(item, j) in grp.items"
                :key="item.id"
                type="button"
                class="cmdk-item"
                :class="{ active: findFlatIndex(item) === selectedIdx }"
                @click="runCommand(item)"
                role="option"
                :aria-selected="findFlatIndex(item) === selectedIdx"
              >
                <span class="cmdk-item-icon"><Icon v-if="item.icon" :name="item.icon" /><span v-else>·</span></span>
                <span class="cmdk-item-body">
                  <span class="cmdk-item-title">{{ item.title }}</span>
                  <span v-if="item.description" class="cmdk-item-desc">{{ item.description }}</span>
                </span>
                <span v-if="grp.group === 'Recent'" class="cmdk-item-tag">recent</span>
                <span v-else-if="grp.group === 'Lookup'" class="cmdk-item-tag cmdk-item-tag--cyan">jump</span>
              </button>
            </div>
          </div>

          <!-- Empty -->
          <div v-else class="cmdk-empty">
            <div class="cmdk-empty-icon">∅</div>
            <div class="cmdk-empty-text">No commands match "<strong>{{ query }}</strong>"</div>
            <div class="cmdk-empty-hint">Try a DID, a transaction ID, or one of: <code>treasury</code>, <code>events</code>, <code>theme</code>, <code>logout</code></div>
            <div v-if="perms.can('treasury')" class="cmdk-empty-hint">
              Slash: <code>/mint 100 to did:…</code> · <code>/distribute 50 staking_reward to did:…</code> · <code>/refresh-policy</code>
            </div>
          </div>

          <!-- Footer hints -->
          <div class="cmdk-foot">
            <span class="cmdk-foot-hint"><kbd>↑↓</kbd> navigate</span>
            <span class="cmdk-foot-hint"><kbd>↵</kbd> run</span>
            <span class="cmdk-foot-hint"><kbd>esc</kbd> close</span>
            <span class="cmdk-foot-hint cmdk-foot-tip">Tip: type <kbd>/</kbd> to open · <kbd>⌘K</kbd> to toggle</span>
          </div>
        </div>
      </div>
    </transition>

    <!-- Slash-command confirmation (#7, 2026-05-08).
         requiredMatch=amount enforces typed-confirmation (matches the
         high-blast-radius pattern used by mint elsewhere). -->
    <ConfirmActionModal
      :show="!!pendingSlash"
      :title="pendingSlash?.kind === 'mint' ? 'Confirm issuance via /mint' : 'Confirm distribute via /distribute'"
      :message="pendingSlash?.preview || ''"
      tone="warn"
      :confirm-text="pendingSlash?.kind === 'mint' ? ('Issue ' + localCurrency).trim() : 'Distribute'"
      cancel-text="Cancel"
      :busy="slashBusy"
      busy-text="Working…"
      :required-match="pendingSlash?.amount || ''"
      :reason-placeholder="pendingSlash?.amount || ''"
      @confirm="executeSlash"
      @close="closeSlashModal"
    />
  </Teleport>
</template>

<style scoped>
.cmdk-overlay {
  position: fixed;
  inset: 0;
  z-index: 10100;
  background: radial-gradient(ellipse at center top, rgba(0, 0, 0, 0.78) 0%, rgba(0, 0, 0, 0.92) 100%);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
}

.cmdk-modal {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  width: min(680px, 92vw);
  max-height: 70vh;
  background: linear-gradient(180deg, rgba(8, 12, 18, 0.96), rgba(4, 8, 14, 0.96));
  border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 14px;
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.6),
    0 0 0 1px rgba(var(--cyan-rgb), 0.12),
    0 0 40px rgba(var(--cyan-rgb), 0.18);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Search bar */
.cmdk-search {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.04), transparent);
}
.cmdk-search-icon {
  font-size: 16px;
  opacity: 0.7;
}
.cmdk-search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: #fff;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 14px;
  letter-spacing: 0.3px;
}
.cmdk-search-input::placeholder {
  color: rgba(255, 255, 255, 0.35);
}
.cmdk-search-shortcut {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  color: rgba(255, 255, 255, 0.45);
}

/* Results */
.cmdk-results {
  flex: 1;
  overflow-y: auto;
  padding: 6px 8px 10px;
}
.cmdk-results::-webkit-scrollbar { width: 6px; }
.cmdk-results::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, rgba(var(--cyan-rgb), 0.4), rgba(var(--cyan-rgb), 0.2));
  border-radius: 3px;
}
.cmdk-results::-webkit-scrollbar-track { background: transparent; }

.cmdk-group {
  padding: 6px 0 4px;
}
.cmdk-group-label {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: rgba(var(--cyan-rgb), 0.55);
  padding: 4px 12px 4px 12px;
  margin-top: 4px;
}
.cmdk-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 8px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  text-align: left;
  cursor: pointer;
  transition: all 100ms ease;
  font-family: inherit;
  color: inherit;
}
.cmdk-item:hover, .cmdk-item.active {
  background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.15), rgba(var(--cyan-rgb), 0.05));
  border-color: rgba(var(--cyan-rgb), 0.3);
  box-shadow: inset 0 0 0 1px rgba(var(--cyan-rgb), 0.18);
}
.cmdk-item-icon {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.cmdk-item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.cmdk-item-title {
  font-size: 13px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: 0.3px;
}
.cmdk-item-desc {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmdk-item-tag {
  flex-shrink: 0;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  text-transform: uppercase;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 100px;
  color: rgba(255, 255, 255, 0.45);
}
.cmdk-item-tag--cyan {
  background: rgba(var(--cyan-rgb), 0.12);
  border-color: rgba(var(--cyan-rgb), 0.4);
  color: var(--cyan);
}

/* Empty */
.cmdk-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 36px 18px;
  text-align: center;
}
.cmdk-empty-icon {
  font-size: 28px;
  opacity: 0.3;
}
.cmdk-empty-text {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.55);
}
.cmdk-empty-hint {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.35);
  max-width: 360px;
  line-height: 1.6;
}
.cmdk-empty-hint code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  padding: 1px 5px;
  background: rgba(var(--cyan-rgb), 0.1);
  border: 1px solid rgba(var(--cyan-rgb), 0.3);
  border-radius: 3px;
  color: var(--cyan);
}

/* Footer */
.cmdk-foot {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  background: rgba(0, 0, 0, 0.4);
  font-size: 10px;
  color: rgba(255, 255, 255, 0.4);
}
.cmdk-foot-hint kbd {
  font-family: 'JetBrains Mono', monospace;
  font-size: 9px;
  padding: 2px 6px;
  margin: 0 2px;
  background: rgba(var(--cyan-rgb), 0.1);
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 3px;
  color: rgba(255, 255, 255, 0.7);
}
.cmdk-foot-tip {
  margin-left: auto;
}

/* Transitions */
.cmdk-fade-enter-active,
.cmdk-fade-leave-active {
  transition: opacity 120ms ease;
}
.cmdk-fade-enter-from,
.cmdk-fade-leave-to {
  opacity: 0;
}
.cmdk-fade-enter-active .cmdk-modal,
.cmdk-fade-leave-active .cmdk-modal {
  transition: transform 160ms cubic-bezier(0.34, 1.56, 0.64, 1);
}
.cmdk-fade-enter-from .cmdk-modal {
  transform: translateY(-12px) scale(0.98);
}
.cmdk-fade-leave-to .cmdk-modal {
  transform: translateY(8px) scale(0.98);
}

/* Mobile */
@media (max-width: 600px) {
  .cmdk-overlay { padding-top: 8vh; }
  .cmdk-modal { width: 95vw; }
  .cmdk-foot { flex-wrap: wrap; gap: 10px; }
  .cmdk-foot-tip { margin-left: 0; flex-basis: 100%; }
}
</style>
