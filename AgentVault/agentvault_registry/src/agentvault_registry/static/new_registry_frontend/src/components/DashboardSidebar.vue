<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useViewport } from '@/composables/useViewport'
import { usePermissions, type AdminAction } from '@/composables/usePermissions'
import { useMainframe } from '@/composables/useMainframe'
import { isMainframeOnlyPath } from '@/composables/mainframeOnlyPaths'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

// §CHATPOLISH — unread chat, for the OurChat nav badge. Polled, not pushed: the
// shell must not hold a socket of its own, and a 60s chip is the right fidelity
// for "something is waiting" (the thread itself is live once you are in it).
// Muted threads are excluded server-side. Every failure is silent: a badge that
// renders an error is worse than a badge that renders nothing.
const chatUnread = ref(0)
let unreadTimer: ReturnType<typeof setInterval> | null = null
async function refreshChatUnread() {
  if (!authStore.isAuthenticated) { chatUnread.value = 0; return }
  try {
    const r = await apiClient.get('/chat/unread-count')
    chatUnread.value = Number(r?.data?.messages || 0)
  } catch { /* absence, never a visible error */ }
}
function badgeCount(item: NavItem): number {
  return item.badgeKey === 'chat' ? chatUnread.value : 0
}
const permissions = usePermissions()
const { t } = useI18n()

// 2026-05-11: resolves an item's display label through vue-i18n when
// item.i18nKey is set; otherwise returns the literal `name` field.
// Keeps the migration additive — un-keyed items render unchanged.
function itemLabel(item: NavItem): string {
  return item.i18nKey ? t(item.i18nKey, item.name) : item.name
}

function groupLabel(group: NavGroup): string {
  return group.i18nKey ? t(group.i18nKey, group.label) : group.label
}

function bottomItemLabel(item: { name: string; i18nKey?: string }): string {
  return item.i18nKey ? t(item.i18nKey, item.name) : item.name
}
const uiStore = useUIStore()
const viewport = useViewport()

// Read sidebar mode from the UI store. Three states:
//   expanded → 256px with labels    (default)
//   icons    → 64px icon-only strip
//   hidden   → off-screen (showcase mode; reveal button lives in DashboardLayout)
//
// Mobile-pass 2026-05-08: at <1024px the sidebar always renders in
// EXPANDED layout (full labels, full width — easier to tap), but is
// translated off-screen unless mobileDrawerOpen is true. The desktop
// modes (icons/hidden) only apply ≥1024px.
const isCollapsed = computed(() => !viewport.isMobile.value && uiStore.sidebarMode === 'icons')
const isHidden = computed(() => {
  if (viewport.isMobile.value) {
    // On mobile, the sidebar is hidden whenever the drawer is closed.
    return !uiStore.mobileDrawerOpen
  }
  return uiStore.sidebarMode === 'hidden'
})
// §FESUITE (2026-10-04): the sidebar mounts once per session, and its three snapshots of the config (this flag, the fiat
// gate, the per-registry flags) kept a failed read's `{}` for the session: doors stayed hidden after the API came back.
// All three follow the ONE shared config now (useRegistryConfig reads again after a failure).
const { config: _sharedCfg } = useRegistryConfig()
const isFederatedOperator = computed(() => _sharedCfg.value.is_federated_operator ?? false)

// Auth requirement types
interface NavItem {
  name: string
  // 2026-05-11: optional i18n key. If set, item label resolves through t(),
  // falling back to `name` when key is missing/untranslated. Migration is
  // §NAVI18N (2026-08-31): every entry carries one now. An entry WITHOUT a key renders
  // `name` literally in all nine locales — which is what seven of them silently did.
  i18nKey?: string
  path: string
  icon: string
  color: string
  requiresAgent?: boolean
  requiresAdmin?: boolean
  // P3.1 (2026-05-08): when set, requires the user to have either is_admin
  // (super-flag) OR the specific admin sub-flag. Pairs with backend RBAC.
  requiredSubFlag?: AdminAction
  authHint?: string
  // §CHATPOLISH (2026-08-30) — an optional live counter beside the label. §CHATDESK
  // C2 specified "nav entry … with unread badge" and shipped the entry without
  // one, so the desktop shell had no way to say a message had arrived. Kept as a
  // KEY rather than a number: the item table is static config, the count is not.
  badgeKey?: 'chat'
  mainframeOnly?: boolean
  // PB-1 (2026-05-09): if true, item is hidden entirely unless the user
  // owns a backer flare (auth.user.flare_tier is non-null). Used for
  // "My Flare" — the FlareManager view only matters once you've earned one.
  requiresFlare?: boolean
  // §FLARESHOP (2026-08-16): if true, the item needs the EURO on-ramp to be
  // live on this registry. It is off on every frame in this fleet, which left
  // "Become a Backer" advertising a lane with nothing behind it. The item STAYS
  // in the sidebar (Commander's call) but locks, with a tooltip pointing at the
  // local-currency shop — the same treatment Disputes/Staking already get.
  // §BAFIN (2026-10-02, his words "there is no fiat lane anymore"; the letter: the euro lane and its public price list
  // are off): "Become a Backer" is no longer locked but HIDDEN where the euro lane is off (requiresRegistryFlag
  // 'fiat_onramp_enabled', the read the router guard uses), so no page advertises a euro door that is closed.
  requiresFiat?: boolean
  // §COCKPIT P1 (2026-08-31): the item exists only where the REGISTRY serves the
  // feature. HIDDEN, not locked — a lock says "you may not", and the honest thing
  // to say about a surface this deployment does not run is nothing at all. Read
  // from the shared public-config composable, the same one the router guard uses,
  // so the nav and the guard cannot disagree.
  requiresRegistryFlag?: 'cockpit_desk_enabled' | 'frame_kit_enabled' | 'staking_enabled' | 'fiat_onramp_enabled'
  /** §FEFRAME W3: hidden only when the registry says this flag is FALSE (an older registry that does not say keeps it) */
  hiddenWhenRegistryFlagFalse?: 'simulation_enabled'
}

interface NavGroup {
  label: string
  // 2026-05-11: optional i18n key for the group header. Falls back to `label`.
  i18nKey?: string
  icon: string
  items: NavItem[]
}

// Top-level items (always visible, no group)
const topItems: NavItem[] = [
  { name: 'Mission Control', i18nKey: 'nav.items.missionControl', path: '/mission-control', icon: 'mdi:view-grid', color: 'text-blue-600' },
  // §DASHRESTORE (2026-09-02) — the 3D bridge kept its view and gained its own
  // entry on his word ("bridge gets bridge menu item button"). data-tour is
  // DERIVED from path in the template, so this row is also `nav-bridge` for free.
  { name: 'Bridge', i18nKey: 'nav.items.bridge', path: '/bridge', icon: 'mdi:telescope', color: 'text-indigo-400' },
  // POCKET mode (2026-07-07) — a peer of Mission Control: the simplified consumer shell.
  // Top-level (not buried in a collapsed group) so it's instantly discoverable; this
  // cockpit is "Advanced mode".
  { name: 'Pocket mode', i18nKey: 'nav.items.pocketMode', path: '/pocket/home', icon: 'mdi:cellphone', color: 'text-cyan-400' },
  // 2026-07-20 Commander: keep top-level to the two shells — The Guild lives in AGENTS,
  // GÖDEL FORGE in COMMUNITY (a crowded top level stops being a top level).
]

// Grouped navigation
const navGroups: NavGroup[] = [
  {
    label: 'AGENTS',
    i18nKey: 'nav.groups.agents',
    icon: 'mdi:robot',
    items: [
      // THE GUILD (moved from top level 2026-07-20) — agent work exchange; literal brand name.
      { name: 'The Guild', i18nKey: 'nav.items.guild', path: '/guild', icon: 'mdi:briefcase', color: 'text-yellow-400', authHint: 'Agent work exchange — escrowed bounties, bids, verified pay' },
      { name: 'Onboarding', i18nKey: 'nav.items.onboarding', path: '/onboarding', icon: 'mdi:rocket-launch', color: 'text-teal-600' },
      { name: 'Agent Builder', i18nKey: 'nav.items.agentBuilder', path: '/agent-builder', icon: 'mdi:wrench', color: 'text-orange-600' },
      { name: 'My Agents', i18nKey: 'nav.items.myAgents', path: '/my-agents', icon: 'mdi:robot', color: 'text-green-600' },
      { name: 'Agent Discovery', i18nKey: 'nav.items.agentDiscovery', path: '/discover', icon: 'mdi:magnify', color: 'text-purple-600' },
      // §pass62 (2026-05-21) — Federation peer browse view (parallel to Agent Discovery).
      // §pass62.1 (2026-05-21) — Renamed "Federation Discovery" → "Federation Peers" (16 chars
      // matches sibling "Agent Discovery"=15; longer name was wrapping on 2 lines in sidebar).
      { name: 'Federation Peers', i18nKey: 'nav.items.federationPeers', path: '/federation-discover', icon: 'mdi:source-branch', color: 'text-cyan-500', authHint: 'Browse + drill into federation peers, frames, cloud operators' },
      { name: 'Leaderboard', i18nKey: 'nav.items.leaderboard', path: '/leaderboard', icon: 'mdi:trophy', color: 'text-yellow-500', authHint: 'Public top-ranked agents by EigenTrust score' },
      // POCKET FRAME (2026-07-07) — mobile pairing + push devices, and IRONKEY approvals/panic.
      { name: 'POCKET FRAME', i18nKey: 'nav.items.pocketFrame', path: '/pocket-frame', icon: 'mdi:cellphone-link', color: 'text-cyan-400', authHint: 'Pair your phone + manage push notifications' },
      { name: 'Approvals', i18nKey: 'nav.items.pocketApprovals', path: '/pocket-approvals', icon: 'mdi:shield-key', color: 'text-emerald-400', authHint: 'IRONKEY delegations, capability permits, panic revoke' },
      // COCKPIT CARD (2026-07-25) — liable hybrid identity: human-underwritten agent mandates.
      { name: 'Cockpit Card', i18nKey: 'nav.items.cockpitCard', path: '/cockpit', icon: 'mdi:card-account-details', color: 'text-rose-400', authHint: 'Underwrite an agent — liability mandates, evidence chain, phone confirms' },
      // §COCKPIT P1 (2026-08-31) — the DESK: a modular read-only working surface
      // for the liable human. Hidden unless COCKPIT_DESK_ENABLED is true here.
      { name: 'Cockpit Desk', i18nKey: 'nav.items.cockpitDesk', path: '/desk', icon: 'mdi:view-dashboard-variant-outline', color: 'text-rose-300', requiresRegistryFlag: 'cockpit_desk_enabled', authHint: 'Your decisions, agents, denials and conservation on one savable desk' },
      // PHONE FABRIC console (2026-07-07) — oversight for capability-gated agent computer-use.
      { name: 'Phone Fabric', i18nKey: 'nav.items.phoneFabric', path: '/phone-fabric', icon: 'mdi:monitor-cellphone', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Watch + kill agent phone sessions (computer-use)' },
    ]
  },
  {
    label: 'ECONOMY',
    i18nKey: 'nav.groups.economy',
    icon: 'mdi:currency-usd',
    items: [
      { name: 'Become a Backer', i18nKey: 'nav.items.becomeBacker', path: '/become-a-backer', icon: 'mdi:hand-coin-outline', color: 'text-emerald-500', mainframeOnly: true, requiresRegistryFlag: 'fiat_onramp_enabled', authHint: 'Back TheProtocol — receive this frame\'s units + a supporter flare' },
      { name: 'Flare Shop', i18nKey: 'nav.items.flareShop', path: '/flare-shop', icon: 'mdi:store-outline', color: 'text-violet-400', authHint: 'Buy encirclements + broken-machine overlays with this frame\'s own currency' },
      { name: 'My Flare', i18nKey: 'nav.items.myFlare', path: '/flare-manager', icon: 'mdi:shield-star', color: 'text-amber-500', requiresFlare: true, authHint: 'Manage your backer flare — profile + agent assignment' },
      { name: 'Founders Wall', i18nKey: 'nav.items.foundersWall', path: '/founders-wall', icon: 'mdi:trophy-variant', color: 'text-yellow-400', requiresRegistryFlag: 'fiat_onramp_enabled', authHint: 'See the backers powering TheProtocol\'s genesis chapter' },
      // 2026-07-25: requiresAgent DROPPED — Contracts is dual-auth since X34 (browse/analytics/
      // templates work on a developer JWT; mutations mint an agent JWT per-action inside the view).
      { name: 'Contracts', i18nKey: 'nav.items.contracts', path: '/contracts', icon: 'mdi:file-document-edit', color: 'text-indigo-600' },
      { name: 'Settlements', i18nKey: 'nav.items.settlements', path: '/settlements', icon: 'mdi:scale-balance', color: 'text-cyan-600', mainframeOnly: true },
      { name: 'Disputes', i18nKey: 'nav.items.disputes', path: '/disputes', icon: 'mdi:gavel', color: 'text-red-600', requiresAgent: true, authHint: 'Requires active agent authentication' },
      { name: 'Locks', i18nKey: 'nav.items.staking', path: '/locks', icon: 'mdi:lock', color: 'text-amber-600', requiresAgent: true, requiresRegistryFlag: 'staking_enabled', authHint: 'Requires active agent authentication' },
      { name: 'Forex Desk', i18nKey: 'nav.items.forex', path: '/forex', icon: 'mdi:swap-horizontal', color: 'text-cyan-400', requiresAgent: true, authHint: 'Move value between your agents — local, cross-registry & cross-frame FX' },
      { name: 'AGORA Desk', i18nKey: 'nav.items.exchange', path: '/agora', icon: 'mdi:chart-candlestick', color: 'text-emerald-400', requiresAgent: true, authHint: 'AGORA: trade org points via order book, launches and distributions' },
      { name: 'AGORA Listings', i18nKey: 'nav.items.stocks', path: '/agora/listings', icon: 'mdi:telescope', color: 'text-emerald-300', authHint: 'Federation listings screener: every market, passport buys on foreign books' },
    ]
  },
  {
    // 2026-05-11 PB-1 §67 (Round 2) — dedicated OPERATOR category. Sits between
    // ECONOMY and GOVERNANCE. Public pitch + owner portal + frame request form.
    label: 'OPERATOR',
    i18nKey: 'nav.groups.operator',
    icon: 'mdi:server-network',
    items: [
      { name: 'Operator', i18nKey: 'nav.items.operatorPitch', path: '/operator', icon: 'mdi:server', color: 'text-cyan-500', mainframeOnly: true, authHint: 'Run a registry — backed devs unlock self-service cloud-op provisioning. Sovereign frames request-only.' },
      { name: 'Operator Portal', i18nKey: 'nav.items.operatorPortal', path: '/operator-portal', icon: 'mdi:server-network', color: 'text-cyan-400', mainframeOnly: true, authHint: 'Owner console — your eligibility, your operators, your bundle + credentials' },
      { name: 'Frame Commander', i18nKey: 'nav.items.frameCommander', path: '/frame-commander', icon: 'mdi:globe-model', color: 'text-amber-400', mainframeOnly: true, authHint: 'Request a sovereign frame — your own digital nation under TheProtocol' },
      { name: 'Your frame', i18nKey: 'nav.items.frameKit', path: '/frame-kit', icon: 'mdi:package', color: 'text-amber-300', mainframeOnly: true, requiresRegistryFlag: 'frame_kit_enabled', authHint: 'Follow your frame request and download the frame kit' },
    ]
  },
  {
    label: 'GOVERNANCE',
    i18nKey: 'nav.groups.governance',
    icon: 'mdi:bank',
    items: [
      { name: 'Senate Floor', i18nKey: 'nav.items.senateFloor', path: '/senate', icon: 'mdi:bank', color: 'text-yellow-600', requiresAgent: true, authHint: 'Requires active agent authentication' },
      { name: 'Attestations', i18nKey: 'nav.items.attestations', path: '/attestations', icon: 'mdi:certificate', color: 'text-emerald-500', authHint: 'Your ZKP attestations: lifecycle + signed bundles + schedules' },
      { name: 'Organizations', i18nKey: 'nav.items.organizations', path: '/organization', icon: 'mdi:office-building', color: 'text-blue-600' },
      { name: 'Federation', i18nKey: 'nav.items.federation', path: '/federation', icon: 'mdi:server-network', color: 'text-indigo-600' },
      { name: 'Galactic Map', i18nKey: 'nav.items.galacticMap', path: '/galactic-map', icon: 'mdi:map', color: 'text-purple-600' },
      { name: 'AgentWorld', i18nKey: 'nav.items.agentWorld', path: '/agentworld', icon: 'mdi:globe-model', color: 'text-cyan-500' },
      { name: 'Universe', i18nKey: 'nav.items.universe', path: '/universe', icon: 'mdi:creation', color: 'text-indigo-400' },
    ]
  },
  {
    label: 'DEVELOPER',
    i18nKey: 'nav.groups.developer',
    icon: 'mdi:code-braces',
    items: [
      { name: 'API Tutorials', i18nKey: 'nav.items.apiTutorials', path: '/tutorials', icon: 'mdi:book-open-variant', color: 'text-violet-600' },
      { name: 'API Tester', i18nKey: 'nav.items.apiTester', path: '/api-tester', icon: 'mdi:test-tube', color: 'text-cyan-600', requiresAdmin: true, requiredSubFlag: 'platform' },
      { name: 'Webhooks', i18nKey: 'nav.items.webhooks', path: '/webhooks', icon: 'mdi:webhook', color: 'text-orange-600' },
      { name: 'CI/CD Pipelines', i18nKey: 'nav.items.cicd', path: '/ci-cd', icon: 'mdi:source-branch', color: 'text-green-600' },
      { name: 'Bundles', i18nKey: 'nav.items.bundles', path: '/bundles', icon: 'mdi:archive-outline', color: 'text-indigo-600' },
    ]
  },
  {
    label: 'COMMUNITY',
    i18nKey: 'nav.groups.community',
    icon: 'mdi:account-group',
    items: [
      // §CHATDESK C2 (2026-08-28) — OurChat reaches the desktop shell. This entry
      // is the DESKTOP mount (/ourchat, two-pane); Pocket keeps /pocket/ourchat.
      // Grouped, not top-level: the 2026-07-20 order keeps top level to the two shells.
      { name: 'OurChat', i18nKey: 'nav.items.ourchat', path: '/ourchat', icon: 'mdi:chat', color: 'text-emerald-400', badgeKey: 'chat', authHint: 'Threads, org rooms and the support desk — receipts included' },
      // GÖDEL FORGE (moved from top level 2026-07-20) — the community's self-improving arena.
      { name: 'GÖDEL FORGE', i18nKey: 'nav.items.godelForge', path: '/forge', icon: 'mdi:source-branch', color: 'text-purple-400', authHint: 'Self-improving-agent arena — Evolution Tree, verifier quorums, royalties' },
      { name: 'Community Hub', i18nKey: 'nav.items.communityHub', path: '/community', icon: 'mdi:account-group', color: 'text-violet-500' },
      { name: 'Support', i18nKey: 'nav.items.support', path: '/support', icon: 'mdi:lifebuoy', color: 'text-amber-500' },
      { name: 'Game Arena', i18nKey: 'nav.items.gameArena', path: '/games', icon: 'mdi:gamepad-variant', color: 'text-red-500' },
      // §pass63 (2026-05-22) — Astraeus item removed with rip.
    ]
  },
  {
    label: 'ADMINISTRATION',
    i18nKey: 'nav.groups.administration',
    icon: 'mdi:shield-account',
    items: [
      { name: 'Developers', i18nKey: 'nav.items.developersAdmin', path: '/admin/developers', icon: 'mdi:account-plus', color: 'text-blue-500', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Developer account management' },
      { name: 'Registry Card', i18nKey: 'nav.items.registryCard', path: '/admin/registry-card', icon: 'mdi:radio-tower', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Edit this registry\'s v0.3 self-describing federation card' },
      { name: 'Agent Roster', i18nKey: 'nav.items.agentRoster', path: '/admin/agents', icon: 'mdi:account', color: 'text-violet-500', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Agent identity and ownership' },
      { name: 'Enforcement', i18nKey: 'nav.items.enforcement', path: '/admin/enforcement', icon: 'mdi:gavel', color: 'text-rose-400', requiresAdmin: true, requiredSubFlag: 'enforcement', authHint: 'Per-agent economic levers — slashing locked units, offense ladder, suspension, policy + two-man queue' },
      { name: 'Jurisdiction', i18nKey: 'nav.items.jurisdiction', path: '/admin/jurisdiction', icon: 'mdi:scale-balance', color: 'text-teal-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Declare regulated lifecycle acts and record the state authorizations that unlock them' },
      { name: 'Frame Management', i18nKey: 'nav.items.frameManagement', path: '/frame-management', icon: 'mdi:source-branch', color: 'text-violet-600', requiresAdmin: true, requiredSubFlag: 'federation', mainframeOnly: true, authHint: 'Sovereign frame federation + SF-4/5 data planes' },
      { name: 'OP Management', i18nKey: 'nav.items.opManagement', path: '/operator-management', icon: 'mdi:shield-account', color: 'text-amber-600', requiresAdmin: true, requiredSubFlag: 'federation', mainframeOnly: true, authHint: 'Operator onboarding and lifecycle' },
      { name: 'Federation Tests', i18nKey: 'nav.items.federationTests', path: '/federation-test', icon: 'mdi:server-network', color: 'text-purple-600', requiresAdmin: true, requiredSubFlag: 'federation', mainframeOnly: true, authHint: 'Federation conformance testing' },
      { name: 'Health Monitor', i18nKey: 'nav.items.healthMonitor', path: '/health-monitor', icon: 'mdi:heart-pulse', color: 'text-red-600', requiresAdmin: true, requiredSubFlag: 'platform' },
      { name: 'Command Center', i18nKey: 'nav.items.commandCenter', path: '/command-center', icon: 'mdi:radar', color: 'text-emerald-500', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Operator diagnostics & remediation' },
      { name: 'Galactic Command', i18nKey: 'nav.items.galacticCommand', path: '/galactic-command', icon: 'mdi:crosshairs-gps', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Fleet cockpit — click a registry on the map, command it' },
      { name: 'EigenTrust', i18nKey: 'nav.items.eigenTrust', path: '/eigentrust-command', icon: 'mdi:brain', color: 'text-purple-500', requiresAdmin: true, requiredSubFlag: 'platform', hiddenWhenRegistryFlagFalse: 'simulation_enabled', authHint: 'Simulation & reputation command center' },
      { name: 'IRONHAND', i18nKey: 'nav.items.ironhand', path: '/admin/ironhand', icon: 'mdi:shield-lock', color: 'text-cyan-600', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Agent mTLS identity monitor' },
      { name: 'mTLS Theatre', i18nKey: 'nav.items.ironhandTheatre', path: '/ironhand/theatre', icon: 'mdi:map-marker-path', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Live cross-frame mTLS identity-travel theatre' },
      { name: 'CONSUL', i18nKey: 'nav.items.consul', path: '/admin/compliance', icon: 'mdi:shield-search', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', mainframeOnly: true, authHint: 'Federation compliance monitor + kill switch' },
      { name: 'OPA Policy', i18nKey: 'nav.items.opaConsole', path: '/admin/opa', icon: 'mdi:shield-search', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Policy decision evidence + enforce-impact simulator' },
      { name: 'Reactors', i18nKey: 'nav.items.reactors', path: '/admin/reactors', icon: 'mdi:radioactive', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Event-driven reactor framework status' },
      { name: 'Releases', i18nKey: 'nav.items.releaseChannel', path: '/admin/release-channel', icon: 'mdi:package', color: 'text-amber-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Signed release channel: stable releases and hotfixes, the rollout window you schedule' },
      { name: 'Agent Evals', i18nKey: 'nav.items.agentEvals', path: '/admin/evals', icon: 'mdi:clipboard-check-multiple-outline', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Scored task batteries for agents — results fold into reputation' },
      { name: 'MCP Tester', i18nKey: 'nav.items.mcpTester', path: '/admin/mcp-tester', icon: 'mdi:bug-check-outline', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Full-surface MCP regression sweep — sandbox-only proxy' },
      { name: 'Console Suite', i18nKey: 'nav.items.consoleSuite', path: '/admin/console-suite', icon: 'mdi:monitor-cellphone', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'The console lifecycle suite: browser runs on a desktop and a phone screen against a sandbox frame' },
      { name: 'Event Ledger', i18nKey: 'nav.items.eventLedger', path: '/admin/events', icon: 'mdi:database-search', color: 'text-violet-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'EventStore explorer — browse the immutable ledger' },
      { name: 'Ledger Forensics', i18nKey: 'nav.items.ledgerForensics', path: '/admin/forensics', icon: 'mdi:shield-search', color: 'text-amber-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Stuck-funds tracer + AGORA/supply invariants + emission policy console' },
      { name: 'Emission Policy', i18nKey: 'nav.items.emissionPolicy', path: '/admin/emission-policy', icon: 'mdi:database-search', color: 'text-violet-400', requiresAdmin: true, requiredSubFlag: 'treasury', authHint: 'Which side may write each event type to the ledger, what the projection counts, and what is wrong' },
      { name: 'CI/CD Fleet', i18nKey: 'nav.items.cicdFleet', path: '/admin/cicd', icon: 'mdi:source-branch', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Fleet-wide CI/CD: pipelines, deployments, flags' },
      { name: 'Audit Logs', i18nKey: 'nav.items.auditLogs', path: '/admin/audit-logs', icon: 'mdi:shield-search', color: 'text-amber-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'security_audit_logs — admin action history' },
      { name: 'Marketplace', i18nKey: 'nav.items.adminMarketplace', path: '/admin/marketplace', icon: 'mdi:flag-outline', color: 'text-rose-400', requiresAdmin: true, requiredSubFlag: 'enforcement', authHint: 'Bundle moderation queue + hide/unhide actions' },
      { name: 'Treasury', i18nKey: 'nav.items.treasury', path: '/admin/treasury', icon: 'mdi:bank', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'treasury', authHint: 'Treasury balance, supply invariant, issuance + fees' },
      { name: 'Fiat Operations', i18nKey: 'nav.items.fiatOps', path: '/admin/fiat-ops', icon: 'mdi:credit-card-settings', color: 'text-emerald-500', requiresAdmin: true, requiredSubFlag: 'treasury', mainframeOnly: true, requiresFiat: true, authHint: 'Fiat ops console — overview, pricing, simulator, purchase explorer, manual recovery' },
      { name: 'FX Desk', i18nKey: 'nav.items.fxDesk', path: '/admin/fx', icon: 'mdi:swap-horizontal-bold', color: 'text-amber-400', requiresAdmin: true, requiredSubFlag: 'treasury', mainframeOnly: true, authHint: 'Cross-frame FX desk — the pool between the frames\' units, live rate, swap feed + quote simulator' },
      { name: 'AGORA Admin', i18nKey: 'nav.items.exchangeAdmin', path: '/admin/agora', icon: 'mdi:scale-balance', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'federation', authHint: 'AGORA market command: listings lifecycle, I-X invariants, compliance registry, global halt' },
      { name: 'Webhook Health', i18nKey: 'nav.items.webhookHealth', path: '/admin/webhooks-cluster', icon: 'mdi:webhook', color: 'text-orange-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Cluster-wide webhook delivery health + failures' },
      { name: 'X-Frame Bridge', i18nKey: 'nav.items.xframeBridge', path: '/admin/bridge', icon: 'mdi:bank-transfer', color: 'text-violet-400', requiresAdmin: true, requiredSubFlag: 'federation', authHint: 'Async + SF-3 cross-frame transfer health' },
      { name: 'Email Studio', i18nKey: 'nav.items.emailStudio', path: '/admin/email', icon: 'mdi:email-outline', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Preview transactional + reactor email templates' },
      { name: 'Mail Console', i18nKey: 'nav.items.mailConsole', path: '/admin/mail-fleet', icon: 'mdi:email-fast', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Fleet-wide mail posture: who verifies, who can actually send' },
      { name: 'Broadcasts', i18nKey: 'nav.items.broadcasts', path: '/admin/broadcasts', icon: 'mdi:bullhorn', color: 'text-amber-400', requiresAdmin: true, requiredSubFlag: 'support', mainframeOnly: false, authHint: 'Compose, edit, retract admin broadcasts; read-tracking + WS recipient stats' },
      // §ADMINDESK (2026-08-29) — operator chat desk: two lanes, fully audited.
      { name: 'Chat Desk', i18nKey: 'nav.items.chatDesk', path: '/admin/chatdesk', icon: 'mdi:chat', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'support', mainframeOnly: false, authHint: 'Support threads + customer-granted reviews; every transcript open is audited' },
      { name: 'Settlements', i18nKey: 'nav.items.settlementsAdmin', path: '/admin/settlements', icon: 'mdi:scale-balance', color: 'text-violet-400', requiresAdmin: true, requiredSubFlag: 'enforcement', mainframeOnly: true, authHint: 'Cross-registry dispute compensation slash + payment flows' },
      { name: 'Federation Ops', i18nKey: 'nav.items.federationOps', path: '/federation?tab=operations', icon: 'mdi:server-network', color: 'text-indigo-400', requiresAdmin: true, requiredSubFlag: 'federation', authHint: 'Federation Operations tab — drift remediation, license state, BFS reachability' },
      { name: 'Att. Analytics', i18nKey: 'nav.items.attAnalytics', path: '/admin/attestation-analytics', icon: 'mdi:shield-star', color: 'text-emerald-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'ZKP attestation distribution, lifecycle, cadence' },
      { name: 'Canaries', i18nKey: 'nav.items.canaries', path: '/admin/canaries', icon: 'mdi:heart-pulse', color: 'text-cyan-400', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Continuous synthetic-transaction monitor' },
      { name: 'ZKP Audit', i18nKey: 'nav.items.zkpAudit', path: '/admin/attestations', icon: 'mdi:shield-check', color: 'text-emerald-500', requiresAdmin: true, requiredSubFlag: 'platform', authHint: 'Cross-platform ZKP attestation audit + force-revoke' },
    ]
  },
]

// Track which groups are open (persisted in localStorage)
const openGroups = ref<Set<string>>(new Set())

onMounted(async () => {
  try {
    const saved = localStorage.getItem('sidebar_open_groups')
    if (saved) openGroups.value = new Set(JSON.parse(saved))
  } catch { /* expected */ }
  revealActiveGroup()
  // registry mode (operator vs mainframe) hides mainframe-only items: isFederatedOperator follows the shared config
})

/**
 * Open the nav group that contains the active route.
 *
 * §OPGUIDE-7 (2026-07-31): this used to run ONLY inside onMounted. The sidebar lives in
 * DashboardLayout and mounts exactly once, so every later navigation — a deep link, the
 * quick-search, a guided tour, a router.push from anywhere — left the containing group
 * collapsed. Two consequences:
 *   1. UX: you could be on /my-agents with the AGENTS group shut, so the sidebar never
 *      showed you where you were.
 *   2. Guided tours broke visibly. Grouped items are `v-if`'d on the group being open
 *      (see the template), so `[data-tour="nav-my-agents"]` did not EXIST in the DOM.
 *      The tour navigated correctly, then spent its 12s anchor budget polling for an
 *      element that could never appear and fell back to the centred "this element isn't
 *      on screen" card — which reads as "the tutorial didn't change page properly".
 * Deliberately does NOT persist to localStorage: following a link should reveal where you
 * are, not permanently rewrite the group layout the user chose.
 */
function revealActiveGroup() {
  for (const group of navGroups) {
    if (group.items.some(item => isActive(item.path)) && !openGroups.value.has(group.label)) {
      openGroups.value = new Set(openGroups.value).add(group.label)
    }
  }
}

watch(() => route.path, () => revealActiveGroup())

function toggleGroup(label: string) {
  const next = new Set(openGroups.value)
  if (next.has(label)) next.delete(label); else next.add(label)
  openGroups.value = next
  try { localStorage.setItem('sidebar_open_groups', JSON.stringify([...next])) } catch { /* expected */ }
}

function isGroupOpen(label: string): boolean {
  return openGroups.value.has(label)
}

function groupHasActive(group: NavGroup): boolean {
  return group.items.some(item => isActive(item.path))
}

// Flat list for backward compat (used by isActive, isItemLocked)
const navigationItems = computed(() => [
  ...topItems,
  ...navGroups.flatMap(g => g.items)
])

// ─────────────────────────────────────────────────────────────────────────
// Quick-search (QOL) — a near-invisible nav filter under the identity block.
// Blends into the sidebar at rest; reveals on focus. `/` or Ctrl/⌘-K focuses
// it from anywhere; ↑/↓ move, Enter opens, Esc clears. Fuzzy substring match
// across every nav item's label (respecting hidden/gated items). 2026-07-05.
// ─────────────────────────────────────────────────────────────────────────
const searchQuery = ref('')
const searchActiveIndex = ref(0)
const searchInputRef = ref<HTMLInputElement | null>(null)
const searchFocused = ref(false)

interface SearchHit { item: NavItem; group: string | null }

const searchResults = computed<SearchHit[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return []
  const hits: Array<SearchHit & { score: number }> = []
  const consider = (item: NavItem, group: string | null) => {
    if (isItemHidden(item)) return
    const label = itemLabel(item).toLowerCase()
    const idx = label.indexOf(q)
    if (idx === -1) return
    // Prefer prefix matches, then group-header matches, then earliest position.
    const score = (idx === 0 ? 0 : 100) + idx
    hits.push({ item, group, score })
  }
  for (const item of topItems) consider(item, null)
  for (const group of navGroups) {
    const gl = groupLabel(group)
    for (const item of group.items) consider(item, gl)
  }
  hits.sort((a, b) => a.score - b.score)
  return hits.slice(0, 8).map(({ item, group }) => ({ item, group }))
})

// Split a label into [before, match, after] for highlight rendering.
function searchHighlight(label: string): [string, string, string] {
  const q = searchQuery.value.trim()
  if (!q) return [label, '', '']
  const i = label.toLowerCase().indexOf(q.toLowerCase())
  if (i === -1) return [label, '', '']
  return [label.slice(0, i), label.slice(i, i + q.length), label.slice(i + q.length)]
}

function clearSearch() {
  searchQuery.value = ''
  searchActiveIndex.value = 0
}

function focusSearch() {
  nextTick(() => searchInputRef.value?.focus())
}

function onSearchInput() {
  searchActiveIndex.value = 0
}

function openSearchHit(hit: SearchHit | undefined) {
  if (!hit) return
  // 2026-07-25 (Commander bug report: search → "Contracts" landed on ONBOARDING): search hits
  // used to call navigate() directly, bypassing the locked-item handling the normal click path
  // has — so a gated item's router guard bounced the user elsewhere with no explanation. Route
  // locked hits through the SAME handler as sidebar clicks (opens the AgentSwitcher / login).
  if (isItemLocked(hit.item)) {
    handleLockedClick(hit.item)
  } else {
    navigate(hit.item.path)
  }
  clearSearch()
  searchInputRef.value?.blur()
}

function onSearchKeydown(e: KeyboardEvent) {
  const n = searchResults.value.length
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (n) searchActiveIndex.value = (searchActiveIndex.value + 1) % n
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    if (n) searchActiveIndex.value = (searchActiveIndex.value - 1 + n) % n
  } else if (e.key === 'Enter') {
    e.preventDefault()
    openSearchHit(searchResults.value[searchActiveIndex.value])
  } else if (e.key === 'Escape') {
    e.preventDefault()
    if (searchQuery.value) clearSearch()
    else searchInputRef.value?.blur()
  }
}

// Global shortcut: `/` or Ctrl/⌘-K focuses the quick-search (unless the user is
// already typing in a field). Only active for logged-in users with the sidebar
// expanded (the search input isn't rendered otherwise).
function onGlobalKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null
  const typing = !!target && (
    target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable
  )
  const isSlash = e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey
  const isCmdK = (e.key === 'k' || e.key === 'K') && (e.metaKey || e.ctrlKey)
  if ((isSlash && !typing) || isCmdK) {
    if (isCollapsed.value || !currentUser.value) return
    e.preventDefault()
    focusSearch()
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => window.removeEventListener('keydown', onGlobalKeydown))

// §CHATPOLISH — the unread poller's whole lifecycle, in one place next to the
// only other listener this component owns. Cleared on unmount: the shell is
// mounted once, but a leaked interval across a hot reload polls forever.
onMounted(() => {
  void refreshChatUnread()
  unreadTimer = setInterval(() => { void refreshChatUnread() }, 60000)
})
onUnmounted(() => { if (unreadTimer) { clearInterval(unreadTimer); unreadTimer = null } })

// Paths that work for anonymous (logged-out) visitors. When the user is
// not authenticated, every other nav item appears locked with a "Sign in
// to access" tooltip. Added 2026-05-08 alongside Leaderboard sidebar fix
// (P2.1) so anonymous visitors get the chrome but can't activate gated
// areas. Keep this set small — only routes whose backend allows public
// access AND whose UX makes sense without auth.
const PUBLIC_PATHS = new Set<string>([
  '/leaderboard',
  '/become-a-backer',           // PB-1: anonymous flow supported (Stripe Checkout w/ email)
  '/become-a-backer/success',
  // 2026-05-10 — Founders Wall is a public read-only view of all backers
  // (anonymized aggregate stats endpoint, no PII). The sidebar was locking
  // it for anonymous visitors even though the route + backend are public.
  '/founders-wall',
  // 2026-05-11 PB-1 §67 — Operator category public pages. /operator is the
  // unified 4-tab pitch; /frame-commander is the standalone sovereign-frame
  // request surface. /operator-portal stays gated (owner console). Both
  // public surfaces are anon-visitor-safe via DashboardLayout child + allowAnonymous.
  '/operator',
  '/frame-commander',
  '/operator/request-frame',  // legacy alias → redirects to /frame-commander
  // 2026-06-17 — Discover Stocks is the PUBLIC network-wide AGORA equity
  // screener (route is allowAnonymous; browse needs no auth, passport-buy
  // self-disables for guests). Was struck-through for anonymous visitors.
  '/stocks',
  '/agora/listings',  // §AGORAWORDS (V0419): the listings page's new path; /stocks redirects here
  // 2026-07-20 — both moved into groups; each is a public read surface
  // (the Guild board and the Forge arena browse anonymously; acting needs auth).
  '/guild',
  '/forge',
])

// Determine if a nav item should be hidden ENTIRELY (not just locked).
// Currently only used by `requiresFlare` — showing a "My Flare" item to
// someone who has no flare is noise. PB-1, 2026-05-09.
const isItemHidden = (item: NavItem): boolean => {
  if (item.requiresFlare && !authStore.user?.flare_tier) return true
  if (item.requiresRegistryFlag && !_registryCfg.value[item.requiresRegistryFlag]) return true
  if (item.hiddenWhenRegistryFlagFalse && (_registryCfg.value as any)[item.hiddenWhenRegistryFlagFalse] === false) return true
  return false
}

// §pass66 — mainframe-only gate uses the LOCAL registry's `identity.tier`
// (via useMainframe). Single source of truth: `mainframeOnlyPaths` Set.
// The legacy per-item `mainframeOnly: true` flag is now decorative — adding
// a new gate means adding a path to the Set (1 line, 1 file).
const { isMainframe: _localIsMainframe } = useMainframe()

// §FLARESHOP (2026-08-16) — is the EURO on-ramp live here? Read once from the
// public registry-config (the same channel fx_enabled uses). Defaults to FALSE
// while the fetch is in flight, which is the honest assumption on this fleet
// and means a deep-linked backer page never flashes as available.
const _fiatEnabled = computed(() => !!_sharedCfg.value.fiat_onramp_enabled)   // false while unread: locked, the safe direction

// §COCKPIT P1 — registry feature flags, through the SHARED cached read (one
// request for N callers, and the same answer the router guard gets). Empty until
// it resolves, so a flagged item never flashes into the nav before we know.
const _registryCfg = computed(() => _sharedCfg.value as Record<string, any>)

// Determine if a nav item is locked due to missing auth
const isItemLocked = (item: NavItem): boolean => {
  if (isMainframeOnlyPath(item.path) && !_localIsMainframe.value) return true
  if (item.requiresFiat && !_fiatEnabled.value) return true
  if (item.requiresAgent && !authStore.agentToken) return true
  // P3.1 (2026-05-08): if a specific admin sub-flag is required, check it
  // via usePermissions (which honors is_admin super-flag). Falls back to
  // legacy `requiresAdmin` for items not yet annotated with a sub-flag.
  if (item.requiredSubFlag) {
    if (!permissions.can(item.requiredSubFlag)) return true
  } else if (item.requiresAdmin && !authStore.isAdmin) {
    return true
  }
  // Anonymous user: lock everything outside the public-safe set.
  if (!authStore.isAuthenticated && !PUBLIC_PATHS.has(item.path)) return true
  return false
}

// RBAC §66 (2026-05-08): floating locked-item tooltip — replaces the
// pre-§66 inline tooltip that lived inside each <li> with `position:
// absolute; top: 100%`. The pre-§66 tooltip was clipped by the sidebar's
// scrollable nav (and the parent <li> had no `position: relative`, so it
// sometimes anchored against an unrelated ancestor — visible at the
// BOTTOM of the sidebar instead of next to the hovered item, see
// `Screenshot 2026-05-08 221031.png`).
//
// New design: ONE Teleport-to-body floating tooltip with a dynamic
// position computed from the hovered button's `getBoundingClientRect()`.
// Anchors to the right edge of the sidebar item with a small left-pointing
// arrow + a kind-specific accent colour + a 2-line message (title + sub).
type LockKind = 'auth' | 'mainframe' | 'agent' | 'subflag' | 'admin' | 'fiat' | 'unknown'
interface LockReason {
  kind: LockKind
  title: string
  sub: string
  icon: string
}
const hoveredItem = ref<NavItem | null>(null)
const tooltipPos = ref<{ top: number; left: number } | null>(null)
let lastHoveredButton: HTMLElement | null = null

function handleItemHover(item: NavItem, event: MouseEvent) {
  if (!isItemLocked(item)) return
  const btn = event.currentTarget as HTMLElement
  lastHoveredButton = btn
  const btnRect = btn.getBoundingClientRect()
  // Anchor to the sidebar's right edge with an 8px gap (cleaner than
  // anchoring to the button itself — the button's right edge is inset
  // from the sidebar by group padding, so its rect would put the tooltip
  // partially over the sidebar).
  const aside = btn.closest('aside.sidebar-shell') as HTMLElement | null
  const asideRect = aside?.getBoundingClientRect()
  hoveredItem.value = item
  tooltipPos.value = {
    top: btnRect.top + btnRect.height / 2,
    left: (asideRect?.right ?? btnRect.right) + 8,
  }
  // §66.1 (2026-05-08): for agent-required locked items, the AgentSwitcher
  // in the top-right also glows continuously while the user hovers — same
  // affordance as the floating tooltip. Mirrors Commander's "blinking on
  // hover, not on click" feedback.
  if (item.requiresAgent && !authStore.agentToken) {
    uiStore.setAgentSwitcherAttention(true)
  }
}
function clearItemHover() {
  hoveredItem.value = null
  tooltipPos.value = null
  lastHoveredButton = null
  // Stop the AgentSwitcher glow as soon as the user moves off. Any toggle
  // here is a no-op when attention was already false (e.g., admin items).
  uiStore.setAgentSwitcherAttention(false)
}

const lockReason = computed<LockReason | null>(() => {
  const item = hoveredItem.value
  if (!item) return null
  // Anonymous (and the path isn't one of the public-safe set)
  if (!authStore.isAuthenticated && !PUBLIC_PATHS.has(item.path)) {
    return { kind: 'auth', title: 'Sign in to unlock', sub: 'Click to go to login →', icon: 'mdi:account-question-outline' }
  }
  // §pass66 — Mainframe-only path on a non-mainframe registry
  if (isMainframeOnlyPath(item.path) && !_localIsMainframe.value) {
    return { kind: 'mainframe', title: 'Mainframe-only feature', sub: 'Federate with the mainframe for this — not available on cloud-ops', icon: 'mdi:server-off' }
  }
  // §FLARESHOP — the euro lane is not enabled on this registry
  if (item.requiresFiat && !_fiatEnabled.value) {
    // D6-836 (agentvault2-d6, 2026-10-25, his word through agentvault2-69: "greyed out so you cant use it"): Fiat
    // Operations is the one item that asks; Become a Backer HIDES where the lane is off (requiresRegistryFlag)
    return { kind: 'fiat', title: 'Euro on-ramp off here', sub: 'FIAT_ONRAMP_ENABLED is off on this registry', icon: 'mdi:currency-eur-off' }
  }
  // Agent-required without an active agent
  if (item.requiresAgent && !authStore.agentToken) {
    return { kind: 'agent', title: 'Active agent required', sub: 'Pick one from the top-right →', icon: 'mdi:robot-confused-outline' }
  }
  // Sub-flag mismatch
  if (item.requiredSubFlag && !permissions.can(item.requiredSubFlag)) {
    return { kind: 'subflag', title: `Requires admin_${item.requiredSubFlag}`, sub: 'Ask Commander to grant the flag', icon: 'mdi:shield-lock-outline' }
  }
  // Legacy super-flag check
  if (item.requiresAdmin && !authStore.isAdmin) {
    return { kind: 'admin', title: 'Admin only', sub: 'Ask Commander to grant admin', icon: 'mdi:shield-account-outline' }
  }
  // Fallback — show authHint if present, otherwise generic
  return { kind: 'unknown', title: item.authHint || 'Locked', sub: '', icon: 'mdi:information-outline' }
})

const bottomItems = [
  {
    name: 'Settings',
    i18nKey: 'nav.bottom.settings',
    icon: 'mdi:cog',
    action: () => router.push('/settings')
  },
  {
    name: 'Documentation',
    i18nKey: 'nav.bottom.documentation',
    icon: 'mdi:book',
    action: () => router.push('/docs')
  },
  {
    name: 'Legal',
    i18nKey: 'nav.bottom.legal',
    icon: 'mdi:scroll-text',
    action: () => router.push('/legal/terms')
  }
]

const currentUser = computed(() => authStore.user)
function retryAccount() { return authStore.refreshProfile() }

// Extended profile (display_name + avatar_url from /developers/me)
const profileDisplayName = ref('')
const profileAvatarUrl   = ref('')

const sidebarName = computed(() =>
  profileDisplayName.value || currentUser.value?.name || currentUser.value?.email || ''
)
const sidebarInitials = computed(() => {
  const src = sidebarName.value
  if (!src) return '?'
  return src.split(/\s+/).map((w: string) => w[0]).join('').slice(0, 2).toUpperCase()
})

onMounted(async () => {
  // Skip /developers/me for anonymous visitors (Leaderboard public route).
  // Without this guard, anonymous would 401 on every sidebar mount.
  if (!authStore.isAuthenticated) return
  try {
    const res = await apiClient.get('/developers/me')
    profileDisplayName.value = res.data.display_name || ''
    profileAvatarUrl.value   = res.data.avatar_url   || ''
  } catch { /* expected */ }
})

const isActive = (path: string) => {
  if (path === '/games') {
    return ['/games', '/arena', '/tower-defense', '/snake-arena', '/trading'].some(p => route.path === p || route.path.startsWith(p + '/'))
  }
  const hit = route.path === path || route.path.startsWith(path + '/')
  if (!hit) return false
  // §AGORAWORDS (V0419): '/agora' (the desk) is a prefix of '/agora/listings'. An item is active only when no LONGER
  // item also matches the route, so the listings page lights up once, not twice.
  return !navigationItems.value.some(i => typeof i.path === 'string' && i.path !== path && i.path.startsWith(path + '/')
    && (route.path === i.path || route.path.startsWith(i.path + '/')))
}

const navigate = (path: string) => {
  import.meta.env.DEV && console.log('DashboardSidebar: Navigating to', path)
  router.push(path).catch(err => {
    console.error('Navigation error:', err)
  })
}

// Click handler for locked items.
//
// §66.1 (2026-05-08): the click handler is intentionally minimal. The
// hover-driven AgentSwitcher glow + tooltip already explain WHAT is
// missing and WHERE the user needs to go. On click we just OPEN the
// dropdown — no extra pulse, no toast, no double signal. (Commander
// feedback: "all actions happen on click — should happen on hover".)
//
// Branches:
//  - Anonymous: send to /login (the tooltip says "Click to go to login").
//  - Agent-required: open the AgentSwitcher dropdown via pulseAgentSwitcher
//    (autoOpen=true). The dropdown's "Deploy New Agent" link auto-pulses
//    when 0 agents exist (handled in AgentSwitcher.vue).
//  - Sub-flag / admin / mainframe: tooltip already explains; click no-op.
const handleLockedClick = (item: NavItem) => {
  if (!authStore.isAuthenticated) {
    router.push({ path: '/login', query: { returnTo: item.path } })
    return
  }
  if (item.requiresAgent && !authStore.agentToken) {
    authStore.showAgentSelector = true
    uiStore.pulseAgentSwitcher({ autoOpen: true })
    clearItemHover()
    return
  }
  // Other lock kinds: tooltip is the affordance; click stays silent.
}

const logout = async () => {
  await authStore.logout()
  router.push('/login')
}

// Cycle through expanded → icons → hidden → expanded.
// The header button advances through all three states; the floating reveal
// button in DashboardLayout brings a hidden sidebar straight back to expanded.
const toggleSidebar = () => {
  uiStore.cycleSidebar()
}
</script>

<template>
  <aside
    :class="[
      'sidebar-shell fixed left-0 top-0 h-full text-white transition-all duration-300',
      isCollapsed ? 'w-16' : 'w-64',
      isHidden && 'sidebar-hidden',
    ]"
  >
    <div class="flex flex-col h-full">
      <!-- Header -->
      <div class="flex items-center justify-between p-4 sidebar-border-b">
        <div class="flex items-center space-x-3">
          <div class="sidebar-logo-box w-10 h-10 shrink-0 flex items-center justify-center">
            <ProtocolMark :size="36" />
          </div>
          <div v-if="!isCollapsed" class="sidebar-brand">
            <span class="sidebar-brand-main">THEPROTOCOL</span>
            <span class="sidebar-brand-sub">{{ t('sidebar.brandSub', 'REGISTRY') }}</span>
          </div>
        </div>
        <!-- Header toggle — only shown in EXPANDED mode. In icons mode the
             vertically-centered floating tab in DashboardLayout takes over
             (matching the fully-hidden mode pattern; user-feedback 2026-05-07).
             Keyboard shortcut \ still cycles all 3 modes. -->
        <button
          v-if="!isCollapsed"
          @click="toggleSidebar"
          class="p-1.5 sidebar-toggle-btn rounded-lg transition-colors inline-flex items-center justify-center"
          title="Collapse to icons — press \\ to toggle"
          aria-label="Toggle sidebar"
        >
          <Icon
            icon="mdi:menu-open"
            class="w-5 h-5"
          />
        </button>
      </div>

      <!-- User Info — UserAvatar resolves dual-slot flare (encirclement +
           corner) without per-surface logic. Click jumps to settings, mirroring
           the header avatar UX. -->
      <div v-if="currentUser && !isCollapsed" class="p-4 sidebar-border-b">
        <div class="flex items-center space-x-3">
          <UserAvatar
            :user="currentUser"
            :avatar-url="profileAvatarUrl || null"
            :display-name="sidebarName"
            :initials="sidebarInitials"
            :granted-at="currentUser.flare_granted_at"
            size="md"
            clickable
            @click="router.push('/settings')"
          />
          <div class="flex-1 min-w-0">
            <p class="sidebar-user-name truncate">
              {{ sidebarName }}
            </p>
            <p class="sidebar-user-role">
              {{ currentUser.role }}
            </p>
          </div>
        </div>
      </div>

      <!-- Quick-search — near-invisible nav filter. Blends into the sidebar at
           rest; reveals on focus. `/` or Ctrl/⌘-K to focus; ↑/↓/Enter/Esc. -->
      <div
        v-if="currentUser && !isCollapsed"
        class="sidebar-qs"
        :class="{ 'sidebar-qs--active': searchFocused || searchQuery }"
      >
        <div class="sidebar-qs-field">
          <Icon icon="mdi:magnify" class="sidebar-qs-icon" />
          <input
            ref="searchInputRef"
            v-model="searchQuery"
            type="text"
            class="sidebar-qs-input"
            :placeholder="searchFocused ? 'Jump to…  (↑↓ · Enter)' : 'Search  /'"
            autocomplete="off"
            spellcheck="false"
            aria-label="Search navigation"
            @focus="searchFocused = true"
            @blur="searchFocused = false"
            @input="onSearchInput"
            @keydown="onSearchKeydown"
          />
          <kbd v-if="!searchFocused && !searchQuery" class="sidebar-qs-kbd">/</kbd>
          <button
            v-else-if="searchQuery"
            class="sidebar-qs-clear"
            aria-label="Clear search"
            @mousedown.prevent="clearSearch()"
          >
            <Icon icon="mdi:close" class="w-3.5 h-3.5" />
          </button>
        </div>

        <ul v-if="searchQuery && searchResults.length" class="sidebar-qs-results">
          <li v-for="(hit, i) in searchResults" :key="hit.item.path">
            <button
              class="sidebar-qs-hit"
              :class="{ 'sidebar-qs-hit--active': i === searchActiveIndex }"
              @mouseenter="searchActiveIndex = i"
              @mousedown.prevent="openSearchHit(hit)"
            >
              <Icon :icon="hit.item.icon" class="sidebar-qs-hit-icon" />
              <span class="sidebar-qs-hit-label">
                <template v-for="(part, pi) in [searchHighlight(itemLabel(hit.item))]" :key="pi">
                  {{ part[0] }}<mark>{{ part[1] }}</mark>{{ part[2] }}
                </template>
              </span>
              <span v-if="hit.group" class="sidebar-qs-hit-group">{{ hit.group }}</span>
            </button>
          </li>
        </ul>
        <div v-else-if="searchQuery" class="sidebar-qs-empty">No matches</div>
      </div>

      <!-- Anonymous CTA — shown when no logged-in user (e.g., visiting
           /leaderboard without auth). Replaces the User Info block; same
           padding + border-bottom for visual continuity. P2.1, 2026-05-08. -->
      <!-- §LEDGERGATE (V0601): a session whose account could not be read is not a guest. With /developers/me unanswered
           the sidebar said VIEWING AS GUEST and offered Sign in to a person signed in all along (journal 51's figures). -->
      <div v-else-if="!currentUser && authStore.isAuthenticated && !isCollapsed" class="p-4 sidebar-border-b" data-testid="sidebar-account-unread">
        <ReadFailedNotice dense :text="t('nav.accountUnread', 'Your account could not be read just now.')" :retry="retryAccount" />
      </div>
      <div v-else-if="!currentUser && !authStore.isAuthenticated && !isCollapsed" class="p-4 sidebar-border-b sidebar-anon-cta">
        <div class="sidebar-anon-cta-title">{{ t('nav.anon.viewingAsGuest', 'VIEWING AS GUEST') }}</div>
        <p class="sidebar-anon-cta-text">
          {{ t('nav.anon.tagline', 'Browse public views. Sign in to act.') }}
        </p>
        <div class="sidebar-anon-cta-row">
          <button class="sidebar-anon-btn sidebar-anon-btn--primary" @click="router.push('/login')">
            {{ t('cta.signIn', 'Sign In') }}
          </button>
          <button class="sidebar-anon-btn sidebar-anon-btn--ghost" @click="router.push('/register')">
            {{ t('cta.signUp', 'Sign Up') }}
          </button>
        </div>
      </div>

      <!-- Navigation -->
      <!-- overflow-x-hidden kills the 1-2px horizontal scrollbar that appeared
           in icons-only mode where button paddings sum slightly above 4rem
           (user-feedback 2026-05-07). -->
      <nav class="flex-1 overflow-y-auto overflow-x-hidden p-4">
        <!-- Top-level items (always visible) -->
        <ul class="space-y-1 mb-3">
          <li v-for="item in topItems" :key="item.path">
            <button
              @click="navigate(item.path)"
              :data-tour="'nav-' + item.path.replace(/^\//,'').replace(/\//g,'-')"
              :class="['sidebar-nav-item w-full flex items-center px-3 py-2 rounded-lg transition-all', isActive(item.path) ? 'sidebar-nav-active' : 'sidebar-nav-inactive']"
              :title="isCollapsed ? itemLabel(item) : undefined"
            >
              <Icon :icon="item.icon" :class="`w-5 h-5 shrink-0 ${isActive(item.path) ? 'sidebar-icon-active' : 'sidebar-icon-inactive'}`" />
              <span v-if="!isCollapsed" class="sidebar-nav-label ml-3">{{ itemLabel(item) }}</span>
            </button>
          </li>
        </ul>

        <!-- Grouped navigation -->
        <div v-for="group in navGroups" :key="group.label" class="mb-1">
          <!-- Group header -->
          <button
            @click="isCollapsed ? undefined : toggleGroup(group.label)"
            :class="['sidebar-group-header w-full flex items-center px-3 py-1.5 rounded-md transition-all', groupHasActive(group) ? 'sidebar-group-active' : '']"
            :title="isCollapsed ? groupLabel(group) : undefined"
          >
            <Icon :icon="group.icon" :class="`w-4 h-4 shrink-0 ${groupHasActive(group) ? 'sidebar-icon-active' : 'sidebar-group-icon'}`" />
            <span v-if="!isCollapsed" class="sidebar-group-label ml-3 flex-1 text-left">{{ groupLabel(group) }}</span>
            <Icon v-if="!isCollapsed" icon="mdi:chevron-down" :class="['w-4 h-4 sidebar-group-chevron transition-transform', isGroupOpen(group.label) ? 'rotate-180' : '']" />
          </button>

          <!-- Group items (collapsible) -->
          <ul v-if="!isCollapsed && isGroupOpen(group.label)" class="space-y-0.5 mt-0.5 ml-2 pl-2 sidebar-group-items">
            <li v-for="item in group.items" :key="item.path" v-show="!isItemHidden(item)">
              <button
                @click="isItemLocked(item) ? handleLockedClick(item) : navigate(item.path)"
                :data-tour="'nav-' + item.path.replace(/^\//,'').replace(/\//g,'-')"
                @mouseenter="(e) => handleItemHover(item, e)"
                @mouseleave="clearItemHover"
                @focus="(e) => handleItemHover(item, e)"
                @blur="clearItemHover"
                :class="['sidebar-nav-item w-full flex items-center px-3 py-1.5 rounded-lg transition-all text-sm', isItemLocked(item) ? 'sidebar-nav-locked' : (isActive(item.path) ? 'sidebar-nav-active' : 'sidebar-nav-inactive')]"
                :style="isItemLocked(item) ? 'cursor: not-allowed;' : ''"
                :aria-describedby="isItemLocked(item) && hoveredItem?.path === item.path ? 'sff-tooltip' : undefined"
              >
                <Icon :icon="isItemLocked(item) ? 'mdi:shield-lock' : item.icon" :class="`w-4 h-4 shrink-0 ${isItemLocked(item) ? 'sidebar-icon-locked' : (isActive(item.path) ? 'sidebar-icon-active' : 'sidebar-icon-inactive')}`" />
                <span class="sidebar-nav-label ml-2.5" :class="{ 'sidebar-label-locked': isItemLocked(item) }">{{ itemLabel(item) }}</span>
                <span v-if="badgeCount(item) > 0" class="sidebar-badge" data-testid="nav-badge-chat"
                      :aria-label="String(badgeCount(item))">{{ badgeCount(item) > 99 ? '99+' : badgeCount(item) }}</span>
              </button>
            </li>
          </ul>

          <!-- Collapsed: show group icon only, auto-expand on hover could be added later -->
          <ul v-if="isCollapsed" class="space-y-0.5 mt-0.5">
            <!-- §COCKPIT P1: the collapsed rail had NO hidden-guard, so every
                 `isItemHidden` item (My Flare, and now the desk) rendered here for
                 users it is hidden from. One predicate, both mounts. -->
            <li v-for="item in group.items" :key="item.path" v-show="!isItemHidden(item)">
              <button
                @click="isItemLocked(item) ? handleLockedClick(item) : navigate(item.path)"
                :data-tour="'nav-' + item.path.replace(/^\//,'').replace(/\//g,'-')"
                :class="['sidebar-nav-item w-full flex items-center justify-center py-1.5 rounded-lg transition-all', isActive(item.path) ? 'sidebar-nav-active' : 'sidebar-nav-inactive']"
                :title="itemLabel(item)"
              >
                <Icon :icon="item.icon" :class="`w-4 h-4 ${isActive(item.path) ? 'sidebar-icon-active' : 'sidebar-icon-inactive'}`" />
                <span v-if="badgeCount(item) > 0" class="sidebar-badge-dot" data-testid="nav-badge-chat-dot" />
              </button>
            </li>
          </ul>
        </div>
      </nav>

      <!-- Bottom Section -->
      <div class="p-4 sidebar-border-t space-y-1">
        <button
          v-for="item in bottomItems"
          :key="item.name"
          @click="item.action"
          class="sidebar-nav-item sidebar-nav-inactive w-full flex items-center px-3 py-2 rounded-lg transition-all"
          :title="isCollapsed ? bottomItemLabel(item) : undefined"
        >
          <Icon :icon="item.icon" class="w-5 h-5 shrink-0 sidebar-icon-inactive" />
          <span v-if="!isCollapsed" class="sidebar-nav-label ml-3">{{ bottomItemLabel(item) }}</span>
        </button>
        
        <!-- Theme cycle button (aggressive red / neural cyan / …future themes) -->
        <button
          @click="uiStore.cycleBrandTheme"
          class="w-full flex items-center px-3 py-2 sidebar-theme-cycle rounded-lg transition-all"
          :title="isCollapsed ? t('sidebar.themeLabel', { theme: uiStore.brandTheme }) : t('sidebar.themeCycleHint', { theme: uiStore.brandTheme })"
        >
          <span class="theme-dot" aria-hidden="true"></span>
          <span v-if="!isCollapsed" class="sidebar-nav-label ml-3">{{ t('sidebar.themeLabel', { theme: uiStore.brandTheme }) }}</span>
        </button>

        <!-- a guest has no session to end: Logout under "VIEWING AS GUEST" beside Sign in (the camera, 2026-10-13) -->
        <button
          v-if="authStore.isAuthenticated"
          @click="logout"
          class="w-full flex items-center px-3 py-2 sidebar-logout rounded-lg transition-all"
          :title="isCollapsed ? t('auth.logout', 'Logout') : undefined"
        >
          <Icon icon="mdi:logout" class="w-5 h-5 shrink-0" />
          <span v-if="!isCollapsed" class="sidebar-nav-label ml-3">{{ t('auth.logout', 'Logout') }}</span>
        </button>
      </div>
    </div>
  </aside>

  <!--
    RBAC §66 (2026-05-08): floating locked-item tooltip — Teleport-to-body
    so it escapes the sidebar's overflow context (the pre-§66 inline
    tooltip clipped at the bottom of the nav, see audit screenshot).
    Single instance, dynamic position, kind-coloured accent.
  -->
  <Teleport to="body">
    <Transition name="sff">
      <div
        v-if="!isCollapsed && lockReason && tooltipPos && hoveredItem"
        id="sff-tooltip"
        class="sff"
        :class="`sff--${lockReason.kind}`"
        :style="{ top: tooltipPos.top + 'px', left: tooltipPos.left + 'px' }"
        role="tooltip"
      >
        <span class="sff-arrow" aria-hidden="true"></span>
        <Icon :icon="lockReason.icon" class="sff-icon" />
        <div class="sff-body">
          <div class="sff-title">{{ lockReason.title }}</div>
          <div v-if="lockReason.sub" class="sff-sub">{{ lockReason.sub }}</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ─── Quick-search (near-invisible nav filter) ─── */
/* At rest it all but disappears into the sidebar: no fill, a hairline border at
   ~6% primary, a faint magnifier + placeholder. On focus/active it surfaces —
   subtle fill, brighter border, a soft primary glow. Theme-aware via --nc-primary-rgb
   (cyan on neural, red on sovereign). */
.sidebar-qs {
  padding: 0.5rem 1rem 0.35rem;
  position: relative;
}
.sidebar-qs-field {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.55rem;
  border-radius: 0.55rem;
  /* At rest: essentially invisible — a hairline at ~3% that reads as part of
     the sidebar's own grain, no fill. It only becomes a "field" on interaction. */
  border: 1px solid rgba(var(--nc-primary-rgb), 0.03);
  background: transparent;
  transition: border-color 0.22s ease, background 0.22s ease, box-shadow 0.22s ease;
}
.sidebar-qs-field:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.12);
  background: rgba(var(--nc-primary-rgb), 0.025);
}
.sidebar-qs--active .sidebar-qs-field {
  border-color: rgba(var(--nc-primary-rgb), 0.28);
  background: rgba(var(--nc-primary-rgb), 0.05);
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.05),
              0 4px 16px -8px rgba(var(--nc-primary-rgb), 0.35);
}
.sidebar-qs-icon {
  width: 0.95rem;
  height: 0.95rem;
  flex-shrink: 0;
  color: rgba(var(--nc-primary-rgb), 0.20);
  transition: color 0.22s ease;
}
.sidebar-qs-field:hover .sidebar-qs-icon { color: rgba(var(--nc-primary-rgb), 0.42); }
.sidebar-qs--active .sidebar-qs-icon { color: rgba(var(--nc-primary-rgb), 0.78); }
.sidebar-qs-input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: none;
  outline: none;
  color: rgb(var(--nc-primary-rgb));
  font-size: 0.78rem;
  letter-spacing: 0.01em;
  padding: 0;
}
.sidebar-qs-input::placeholder {
  color: rgba(var(--nc-primary-rgb), 0.20);
  letter-spacing: 0.04em;
  transition: color 0.22s ease;
}
.sidebar-qs-field:hover .sidebar-qs-input::placeholder { color: rgba(var(--nc-primary-rgb), 0.34); }
.sidebar-qs--active .sidebar-qs-input::placeholder { color: rgba(var(--nc-primary-rgb), 0.45); }
.sidebar-qs-kbd {
  font-size: 0.62rem;
  line-height: 1;
  padding: 0.12rem 0.32rem;
  border-radius: 0.3rem;
  color: rgba(var(--nc-primary-rgb), 0.22);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  transition: color 0.22s ease, border-color 0.22s ease;
}
.sidebar-qs-field:hover .sidebar-qs-kbd { color: rgba(var(--nc-primary-rgb), 0.4); border-color: rgba(var(--nc-primary-rgb), 0.16); }
.sidebar-qs-clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: rgba(var(--nc-primary-rgb), 0.5);
  border-radius: 0.3rem;
  padding: 0.1rem;
  transition: color 0.15s ease, background 0.15s ease;
}
.sidebar-qs-clear:hover { color: rgb(var(--nc-primary-rgb)); background: rgba(var(--nc-primary-rgb), 0.1); }
.sidebar-qs-results {
  margin-top: 0.35rem;
  border-radius: 0.55rem;
  overflow: hidden;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  background: rgba(var(--nc-primary-rgb), 0.03);
}
.sidebar-qs-hit {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  padding: 0.4rem 0.6rem;
  text-align: left;
  transition: background 0.12s ease;
}
.sidebar-qs-hit--active { background: rgba(var(--nc-primary-rgb), 0.13); }
.sidebar-qs-hit-icon {
  width: 0.95rem;
  height: 0.95rem;
  flex-shrink: 0;
  color: rgba(var(--nc-primary-rgb), 0.6);
}
.sidebar-qs-hit--active .sidebar-qs-hit-icon { color: rgb(var(--nc-primary-rgb)); }
.sidebar-qs-hit-label {
  flex: 1;
  min-width: 0;
  font-size: 0.76rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sidebar-qs-hit-label mark {
  background: transparent;
  color: rgb(var(--nc-primary-rgb));
  font-weight: 700;
}
.sidebar-qs-hit-group {
  font-size: 0.56rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.4);
  flex-shrink: 0;
}
.sidebar-qs-empty {
  margin-top: 0.35rem;
  padding: 0.5rem 0.6rem;
  font-size: 0.72rem;
  color: rgba(var(--nc-primary-rgb), 0.4);
  text-align: center;
}

/* ─── Shell ─── */
/* 2026-05-08 polish: subtle vertical gradient + ambient scan-line for
   sci-fi feel without being distracting. Right edge gets a gradient
   fade instead of flat 1px border. */
.sidebar-shell {
  background:
    linear-gradient(180deg, #0a0d16 0%, #060a14 50%, #080b15 100%);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  /* Above the sticky beta banner (z-index: 9999) so toggle buttons
     in the sidebar header remain clickable even when the banner
     is showing. */
  z-index: 10000;
  /* Suppress horizontal scroll arrows in icons-only mode (user-feedback
     2026-05-07). Default browser scrollbars otherwise expose the few-pixel
     overflow that comes from the inner buttons' padding sums. */
  overflow-x: hidden;
  position: fixed;
}
/* Right-edge gradient fade — replaces flat 1px border for softer
   transition into the main canvas. */
.sidebar-shell::after {
  content: '';
  position: absolute;
  top: 0; right: 0; bottom: 0;
  width: 1px;
  background: linear-gradient(180deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb), 0.08) 12%,
    rgba(var(--nc-primary-rgb), 0.18) 50%,
    rgba(var(--nc-primary-rgb), 0.08) 88%,
    transparent 100%
  );
  pointer-events: none;
}
/* Optional: extremely faint horizontal scan-line for life — uses the
   accent token so it cycles with theme. */
.sidebar-shell::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    transparent 0%,
    transparent calc(100% - 1px),
    rgba(var(--nc-primary-rgb), 0.025) calc(100% - 1px),
    transparent 100%
  );
  background-size: 100% 4px;
  pointer-events: none;
  opacity: 0.5;
  mask-image: linear-gradient(180deg, transparent 0, black 80px, black calc(100% - 80px), transparent 100%);
}

/* Showcase mode — slide entire sidebar off the left edge.
   Tailwind's `transition-all duration-300` on the <aside> handles the easing.
   pointer-events:none + opacity:0 prevent ghost-clicks while sliding out. */
.sidebar-shell.sidebar-hidden {
  transform: translateX(-100%);
  opacity: 0;
  pointer-events: none;
}

/* ─── Separators ─── */
/* Gradient fade at the edges so the divider feels like a beam, not a wall.
   The dim center → bright middle → dim center pattern echoes the right-edge fade. */
.sidebar-border-b {
  border-bottom: 1px solid transparent;
  background-image: linear-gradient(90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb), 0.04) 10%,
    rgba(var(--nc-primary-rgb), 0.16) 50%,
    rgba(var(--nc-primary-rgb), 0.04) 90%,
    transparent 100%
  );
  background-position: bottom;
  background-size: 100% 1px;
  background-repeat: no-repeat;
}
.sidebar-border-t {
  border-top: 1px solid transparent;
  background-image: linear-gradient(90deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb), 0.04) 10%,
    rgba(var(--nc-primary-rgb), 0.16) 50%,
    rgba(var(--nc-primary-rgb), 0.04) 90%,
    transparent 100%
  );
  background-position: top;
  background-size: 100% 1px;
  background-repeat: no-repeat;
}

/* ─── Logo box ─── */
/* Polished holographic surface — radial accent + soft edge glow + slow
   shimmer to suggest a live signal. */
.sidebar-logo-box {
  background:
    radial-gradient(circle at 30% 30%, rgba(var(--nc-primary-rgb), 0.18) 0%, transparent 60%),
    rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  border-radius: 5px;
  box-shadow:
    0 0 0 1px rgba(var(--nc-primary-rgb), 0.08),
    0 0 14px rgba(var(--nc-primary-rgb), 0.18) inset,
    0 0 8px rgba(var(--nc-primary-rgb), 0.12);
  position: relative;
  overflow: hidden;
}
.sidebar-logo-box::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent 30%, rgba(var(--nc-primary-rgb), 0.10) 50%, transparent 70%);
  background-size: 200% 200%;
  animation: sidebar-logo-shimmer 6s ease-in-out infinite;
  pointer-events: none;
}
@keyframes sidebar-logo-shimmer {
  0%, 100% { background-position: 200% 200%; opacity: 0.5; }
  50%      { background-position: 0% 0%;     opacity: 0.9; }
}
/* Hexagon SVG glyph */
.sidebar-logo-svg { display: block; }
.sidebar-hex      { stroke: rgba(var(--nc-primary-rgb),0.7); }
.sidebar-hex-inner { stroke: rgba(var(--nc-primary-rgb),0.35); }
.sidebar-hex-core  { fill: rgba(var(--nc-primary-rgb),0.9); }

/* ─── Brand stacked text ─── */
.sidebar-brand {
  display: flex; flex-direction: column; gap: 1px;
  min-width: 0; overflow: hidden;
}
.sidebar-brand-main {
  font-size: 0.74rem; font-weight: 700; letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.95);
  white-space: nowrap;
  font-family: 'IBM Plex Mono', monospace;
  text-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.45);
}
.sidebar-brand-sub {
  font-size: 0.55rem; font-weight: 500; letter-spacing: 0.32em;
  color: rgba(var(--nc-primary-rgb), 0.42); white-space: nowrap;
  font-family: 'IBM Plex Mono', monospace;
}

/* ─── Toggle button ─── */
.sidebar-toggle-btn {
  color: rgba(var(--nc-primary-rgb), 0.4);
  transition: color 0.2s, background 0.2s;
}
.sidebar-toggle-btn:hover { color: rgba(var(--nc-primary-rgb), 0.9); background: rgba(var(--nc-primary-rgb), 0.08); }

/* ─── User info ─── */
.sidebar-avatar {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.06), 0 0 12px rgba(var(--nc-primary-rgb), 0.12);
  transition: box-shadow 0.25s ease, border-color 0.25s ease;
}
.sidebar-avatar-wrap { position: relative; }
.sidebar-avatar-flare {
  position: absolute;
  bottom: -4px;
  right: -4px;
  pointer-events: none;
  z-index: 2;
}
.sidebar-avatar:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb), 0.18), 0 0 18px rgba(var(--nc-primary-rgb), 0.25);
}
.sidebar-avatar-icon     { color: rgba(var(--nc-primary-rgb), 0.7); }
.sidebar-avatar-initials {
  color: rgba(var(--nc-primary-rgb), 0.95);
  letter-spacing: 0.05em;
  text-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.5);
}
.sidebar-user-name {
  font-size: 0.74rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.88);
  letter-spacing: 0.01em;
}
.sidebar-user-role {
  font-size: 0.6rem;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb), 0.55);
  text-transform: uppercase;
  font-weight: 600;
}

/* ─── Anonymous-visitor CTA (P2.1, 2026-05-08) ─── */
.sidebar-anon-cta-title {
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb), 0.65);
  text-transform: uppercase;
  margin-bottom: 6px;
}
.sidebar-anon-cta-text {
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.6);
  line-height: 1.45;
  margin: 0 0 12px 0;
}
.sidebar-anon-cta-row {
  display: flex;
  gap: 8px;
}
.sidebar-anon-btn {
  flex: 1;
  padding: 7px 10px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  border-radius: 6px;
  cursor: pointer;
  transition: all 150ms ease;
  border: 1px solid;
  font-family: inherit;
}
.sidebar-anon-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.95);
  border-color: rgba(var(--nc-primary-rgb), 1);
  color: #06141a;
}
.sidebar-anon-btn--primary:hover {
  background: var(--nc-primary-bright, rgba(var(--nc-primary-rgb), 1));
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.5);
}
.sidebar-anon-btn--ghost {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.75);
}
.sidebar-anon-btn--ghost:hover {
  border-color: rgba(255, 255, 255, 0.45);
  color: rgba(255, 255, 255, 1);
}

/* ─── Group headers ─── */
.sidebar-group-header {
  cursor: pointer;
  margin-top: 0.5rem;
  position: relative;
  transition: background 0.18s ease;
}
.sidebar-group-header:hover {
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.04) 0%,
    rgba(var(--nc-primary-rgb), 0.06) 50%,
    transparent 100%
  );
}
.sidebar-group-active { }
.sidebar-group-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  color: rgba(255, 255, 255, 0.35);
  text-transform: uppercase;
  transition: color 0.18s ease, text-shadow 0.18s ease;
}
.sidebar-group-header:hover .sidebar-group-label {
  color: rgba(255, 255, 255, 0.6);
}
.sidebar-group-active .sidebar-group-label {
  color: rgba(var(--nc-primary-rgb), 0.75);
  text-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.3);
}
.sidebar-group-icon {
  color: rgba(255, 255, 255, 0.32);
  transition: color 0.18s ease, transform 0.2s ease;
}
.sidebar-group-header:hover .sidebar-group-icon {
  color: rgba(var(--nc-primary-rgb), 0.6);
}
.sidebar-group-chevron {
  color: rgba(255, 255, 255, 0.2);
  /* Tailwind 4: rotate-180 sets the `rotate` property, not `transform`; list both so the chevron still turns */
  transition: color 0.18s ease, transform 0.2s ease, rotate 0.2s ease;
}
.sidebar-group-header:hover .sidebar-group-chevron {
  color: rgba(var(--nc-primary-rgb), 0.5);
}
.sidebar-group-items {
  /* Tapered gradient instead of flat border-left — fades out at the bottom
     so the nesting line doesn't feel walled off. */
  border-left: 1px solid transparent;
  background-image: linear-gradient(180deg,
    rgba(var(--nc-primary-rgb), 0.16) 0%,
    rgba(var(--nc-primary-rgb), 0.08) 60%,
    transparent 100%
  );
  background-position: left;
  background-size: 1px 100%;
  background-repeat: no-repeat;
}

/* §CHATPOLISH — the unread chip (expanded) and its dot (icons rail, where a
   number is unreadable at 64px). `.sidebar-nav-item` is already position:
   relative, which is what the dot anchors to. */
.sidebar-badge {
  margin-left: auto;
  min-width: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: rgba(52, 211, 153, 0.18);
  border: 1px solid rgba(52, 211, 153, 0.45);
  color: rgb(52, 211, 153);
  font-size: 0.62rem;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.sidebar-badge-dot {
  position: absolute;
  top: 4px;
  right: 10px;
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: rgb(52, 211, 153);
}

/* ─── Nav items ─── */
.sidebar-nav-item {
  position: relative;
  transition: transform 0.15s ease, background 0.18s ease, color 0.18s ease;
}
.sidebar-nav-label {
  font-size: 0.78rem;
  letter-spacing: 0.03em;
  transition: color 0.18s ease, text-shadow 0.18s ease;
  /* §pass62.1 (2026-05-21) — defense in depth against multi-line nav labels.
     Trade-off: a too-long item gets truncated with `…` instead of wrapping.
     Pair with a sensible item name; if you see the ellipsis, rename the item. */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0; /* flex children with overflow:hidden need this */
}

.sidebar-nav-inactive { color: rgba(255, 255, 255, 0.45); }
.sidebar-nav-inactive:hover {
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.07) 0%,
    rgba(var(--nc-primary-rgb), 0.04) 70%,
    transparent 100%
  );
  color: rgba(var(--nc-primary-rgb), 0.9);
  transform: translateX(2px);
}
.sidebar-nav-inactive:hover .sidebar-nav-label {
  color: rgba(var(--nc-primary-rgb), 0.95);
}

/* Active item — gradient surface + animated left bar that pulses gently. */
.sidebar-nav-active {
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.16) 0%,
    rgba(var(--nc-primary-rgb), 0.08) 50%,
    rgba(var(--nc-primary-rgb), 0.02) 100%
  );
  color: rgba(var(--nc-primary-rgb), 0.98);
  position: relative;
  border-left: 2px solid transparent;
  padding-left: calc(0.75rem - 2px); /* compensate for border placeholder */
  box-shadow: inset 0 0 18px rgba(var(--nc-primary-rgb), 0.06);
}
.sidebar-nav-active::before {
  content: '';
  position: absolute;
  left: 0; top: 4px; bottom: 4px;
  width: 2px;
  border-radius: 1px;
  background: linear-gradient(180deg,
    transparent 0%,
    rgba(var(--nc-primary-rgb), 0.95) 25%,
    var(--nc-primary) 50%,
    rgba(var(--nc-primary-rgb), 0.95) 75%,
    transparent 100%
  );
  box-shadow: 0 0 8px var(--nc-primary), 0 0 14px rgba(var(--nc-primary-rgb), 0.5);
  animation: sidebar-active-pulse 2.4s ease-in-out infinite;
}
.sidebar-nav-active .sidebar-nav-label {
  text-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.45);
}
@keyframes sidebar-active-pulse {
  0%, 100% { opacity: 0.85; }
  50%      { opacity: 1; }
}

.sidebar-icon-inactive {
  color: rgba(255, 255, 255, 0.4);
  transition: color 0.18s ease, transform 0.2s ease, filter 0.18s ease;
}
.sidebar-icon-active {
  color: rgba(var(--nc-primary-rgb), 0.95);
  filter: drop-shadow(0 0 5px rgba(var(--nc-primary-rgb), 0.55));
}
.sidebar-nav-inactive:hover .sidebar-icon-inactive {
  color: rgba(var(--nc-primary-rgb), 0.85);
  transform: scale(1.05);
}

.sidebar-active-bar { background: rgba(var(--nc-primary-rgb), 0.8); }

/* ─── Locked / auth-gated items ─── */
.sidebar-nav-locked {
  color: rgba(255,255,255,0.15);
  pointer-events: auto;
}
.sidebar-nav-locked:hover {
  background: rgba(100,100,120,0.06);
  color: rgba(255,255,255,0.2);
}
.sidebar-icon-locked   { color: rgba(255,255,255,0.12); }
.sidebar-label-locked  { text-decoration: line-through; text-decoration-color: rgba(255,255,255,0.1); }

/* RBAC §66 (2026-05-08): floating locked-item tooltip ("sff" = sidebar
   floating tooltip). Replaces `.sidebar-auth-tooltip` which was clipped
   by the sidebar's overflow context. Teleported to body, dynamic
   position computed in script-setup, kind-coloured accent.
   Style is unscoped so it works after Teleport. */
:global(.sff) {
  position: fixed;
  transform: translateY(-50%);
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 14px 11px;
  border-radius: 10px;
  background: rgba(8, 12, 22, 0.96);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  box-shadow:
    0 12px 36px rgba(0, 0, 0, 0.55),
    0 0 0 1px rgba(var(--nc-primary-rgb), 0.06) inset,
    0 0 18px rgba(var(--nc-primary-rgb), 0.12);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem;
  line-height: 1.45;
  letter-spacing: 0.02em;
  color: rgba(226, 232, 240, 0.92);
  z-index: 9999;
  max-width: 280px;
  pointer-events: none;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}
:global(.sff-arrow) {
  position: absolute;
  left: -5px;
  top: 50%;
  width: 10px;
  height: 10px;
  background: rgba(8, 12, 22, 0.96);
  border-left: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  transform: translateY(-50%) rotate(45deg);
  pointer-events: none;
}
:global(.sff-icon) {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  margin-top: 1px;
  color: rgba(var(--nc-primary-rgb), 0.85);
}
:global(.sff-body) { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
:global(.sff-title) {
  color: rgba(var(--nc-primary-rgb), 1);
  font-weight: 500;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
:global(.sff-sub) {
  color: rgba(148, 163, 184, 0.78);
  font-size: 0.66rem;
  letter-spacing: 0.01em;
  /* §pass66.4 (2026-05-23) — was `nowrap`, causing the longer mainframe-only
     sub message ("Federate with the mainframe for this — not available on
     cloud-ops", ~62 chars) to overflow the 280px max-width container.
     `normal` lets it wrap to 2 lines naturally inside the box. */
  white-space: normal;
  word-break: break-word;
}

/* Per-kind colour accents — each lock category gets a distinctive hue */
:global(.sff--auth) { border-color: rgba(96, 165, 250, 0.55); }
:global(.sff--auth .sff-icon) { color: rgba(147, 197, 253, 0.95); }
:global(.sff--auth .sff-title) { color: rgba(191, 219, 254, 1); }
:global(.sff--auth .sff-arrow) { border-left-color: rgba(96, 165, 250, 0.55); border-bottom-color: rgba(96, 165, 250, 0.55); }

:global(.sff--mainframe) { border-color: rgba(168, 85, 247, 0.55); }
:global(.sff--mainframe .sff-icon) { color: rgba(196, 132, 252, 0.95); }
:global(.sff--mainframe .sff-title) { color: rgba(216, 180, 254, 1); }
:global(.sff--mainframe .sff-arrow) { border-left-color: rgba(168, 85, 247, 0.55); border-bottom-color: rgba(168, 85, 247, 0.55); }

:global(.sff--agent) { border-color: rgba(245, 158, 11, 0.6); box-shadow: 0 12px 36px rgba(0,0,0,0.55), 0 0 0 1px rgba(245,158,11,0.1) inset, 0 0 22px rgba(245, 158, 11, 0.18); }
:global(.sff--agent .sff-icon) { color: rgba(252, 211, 77, 1); }
:global(.sff--agent .sff-title) { color: rgba(253, 230, 138, 1); }
:global(.sff--agent .sff-arrow) { border-left-color: rgba(245, 158, 11, 0.6); border-bottom-color: rgba(245, 158, 11, 0.6); }

:global(.sff--subflag) { border-color: rgba(244, 63, 94, 0.55); }
:global(.sff--subflag .sff-icon) { color: rgba(251, 113, 133, 1); }
:global(.sff--subflag .sff-title) { color: rgba(252, 165, 165, 1); }
:global(.sff--subflag .sff-arrow) { border-left-color: rgba(244, 63, 94, 0.55); border-bottom-color: rgba(244, 63, 94, 0.55); }

:global(.sff--admin) { border-color: rgba(244, 63, 94, 0.55); }
:global(.sff--admin .sff-icon) { color: rgba(251, 113, 133, 1); }
:global(.sff--admin .sff-title) { color: rgba(252, 165, 165, 1); }
:global(.sff--admin .sff-arrow) { border-left-color: rgba(244, 63, 94, 0.55); border-bottom-color: rgba(244, 63, 94, 0.55); }

/* Transitions: slide in from the left + fade. The translateY(-50%) is
   needed for vertical centering, so the enter-from preserves it. */
:global(.sff-enter-active), :global(.sff-leave-active) {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
:global(.sff-enter-from), :global(.sff-leave-to) {
  opacity: 0;
  transform: translateY(-50%) translateX(-6px) scale(0.96);
}
:global(.sff-enter-to), :global(.sff-leave-from) {
  opacity: 1;
  transform: translateY(-50%) translateX(0) scale(1);
}

/* ─── Theme cycle ─── */
.sidebar-theme-cycle {
  color: rgba(255, 255, 255, 0.55);
  font-size: 0.72rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  transition: background 0.2s ease, color 0.2s ease;
}
.sidebar-theme-cycle:hover {
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.1) 0%,
    rgba(var(--nc-primary-rgb), 0.04) 80%,
    transparent 100%
  );
  color: var(--nc-primary);
}
.sidebar-theme-cycle:hover .theme-dot {
  animation: theme-dot-pulse 1.4s ease-in-out infinite;
  box-shadow: 0 0 16px var(--nc-primary), 0 0 24px rgba(var(--nc-primary-rgb), 0.6);
}
.theme-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: radial-gradient(circle at 30% 30%,
    rgba(255, 255, 255, 0.4) 0%,
    var(--nc-primary) 60%,
    rgba(var(--nc-primary-rgb), 0.7) 100%
  );
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.7);
  flex-shrink: 0;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}
@keyframes theme-dot-pulse {
  0%, 100% { transform: scale(1);    box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.7); }
  50%      { transform: scale(1.18); box-shadow: 0 0 18px var(--nc-primary), 0 0 28px rgba(var(--nc-primary-rgb), 0.5); }
}

/* ─── Logout ─── */
.sidebar-logout {
  color: rgba(248, 113, 113, 0.65);
  transition: background 0.18s ease, color 0.18s ease, transform 0.15s ease, box-shadow 0.18s ease;
}
.sidebar-logout:hover {
  background: linear-gradient(90deg,
    rgba(248, 113, 113, 0.10) 0%,
    rgba(248, 113, 113, 0.04) 80%,
    transparent 100%
  );
  color: rgba(248, 113, 113, 0.95);
  transform: translateX(2px);
  box-shadow: inset 0 0 14px rgba(248, 113, 113, 0.06);
}

/* ─── Scrollbar ─── */
nav::-webkit-scrollbar       { width: 4px; }
nav::-webkit-scrollbar-track { background: transparent; }
nav::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg,
    rgba(var(--nc-primary-rgb), 0.08) 0%,
    rgba(var(--nc-primary-rgb), 0.28) 50%,
    rgba(var(--nc-primary-rgb), 0.08) 100%
  );
  border-radius: 2px;
}
nav::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg,
    rgba(var(--nc-primary-rgb), 0.25) 0%,
    rgba(var(--nc-primary-rgb), 0.55) 50%,
    rgba(var(--nc-primary-rgb), 0.25) 100%
  );
}

/* ─── Reduced-motion respect — disable animations for users who prefer it. */
@media (prefers-reduced-motion: reduce) {
  .sidebar-shell::before,
  .sidebar-logo-box::after,
  .sidebar-nav-active::before,
  .sidebar-theme-cycle:hover .theme-dot {
    animation: none !important;
  }
  .sidebar-nav-inactive:hover,
  .sidebar-logout:hover { transform: none; }
}
</style>
