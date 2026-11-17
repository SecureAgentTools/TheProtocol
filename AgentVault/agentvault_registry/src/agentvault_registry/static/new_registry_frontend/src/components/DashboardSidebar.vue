<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import WornTitle from '@/components/contributor/WornTitle.vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useViewport } from '@/composables/useViewport'
import { hasAdminFlag, type AdminAction } from '@/composables/usePermissions'
import { NAV_GROUPS, NAV_ITEMS, navItemByPath, type NavItem, type NavGroup } from '@/services/nav/navTable'
import { navItemState, routeRule, adminSubgroups, type NavCtx, type RouteRule } from '@/services/nav/navAccess'
import { useNavPins } from '@/services/nav/navPins'
import { rememberUiMode } from '@/services/uiMode'
import { useMainframe } from '@/composables/useMainframe'
import { isMainframeOnlyPath } from '@/composables/mainframeOnlyPaths'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useI18n } from '@/composables/useI18n'
import { apiClient } from '@/services/api/client'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'
import PublicAnnouncementsStrip from '@/components/PublicAnnouncementsStrip.vue'

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
const { t, tp } = useI18n()

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

// V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the table (his task groups) and the one rule for who sees an
// entry live in services/nav (navTable, navAccess), shared with the search and the palette; the rule is read from the
// route each entry opens, the meta the router's guard enforces. No hand list of public paths, no admin flag of our own.
const navGroups: NavGroup[] = NAV_GROUPS
const _rules = new Map<string, RouteRule>()
function ruleOf(path: string): RouteRule {
  let r = _rules.get(path)
  if (!r) { r = routeRule(router, path); _rules.set(path, r) }
  return r
}
const ADMIN_FLAGS: AdminAction[] = ['platform', 'federation', 'enforcement', 'treasury', 'support']
const navCtx = computed<NavCtx>(() => ({
  signedIn: !!authStore.isAuthenticated,
  legacyAdmin: (authStore.user as any)?.is_admin === true,
  flags: ADMIN_FLAGS.filter((f) => hasAdminFlag(authStore.user, f)),
  hasAgent: !!authStore.agentToken,
  isMainframe: !!_localIsMainframe.value,
  fiatEnabled: _fiatEnabled.value,
  registryCfg: _registryCfg.value,
  flareTier: (authStore.user as any)?.flare_tier ?? null,
}))
function itemState(item: NavItem) { return navItemState(item, ruleOf(item.path), navCtx.value) }
function visibleItems(group: NavGroup): NavItem[] { return group.items.filter((i) => itemState(i) !== 'hide') }
/** a group with nothing this person sees is not drawn (Administration for a member; most groups for a visitor) */
const visibleGroups = computed(() => navGroups.filter((g) => visibleItems(g).length > 0))
function adminGroups(group: NavGroup) { return adminSubgroups(group.items, ruleOf, navCtx.value) }
// each key spelled out, so the raw-key gate reads all five (a key built from a template read as one it could not find)
const ADMIN_GROUP_LABEL: Record<AdminAction, () => string> = {
  platform: () => t('nav.adminGroups.platform', 'Platform'),
  federation: () => t('nav.adminGroups.federation', 'Federation'),
  enforcement: () => t('nav.adminGroups.enforcement', 'Enforcement'),
  treasury: () => t('nav.adminGroups.treasury', 'Treasury'),
  support: () => t('nav.adminGroups.support', 'Support'),
}
function adminGroupLabel(flag: AdminAction): string { return ADMIN_GROUP_LABEL[flag]() }

// ── The Pinned block (his 2026-11-13 word: defaults Mission Control, OurChat, Pocket mode; pin any item from its
// category; drag to reorder; its own prefs key). services/nav/navPins: read the server, change, write back. ──
const navPins = useNavPins()
onMounted(() => { if (authStore.isAuthenticated) void navPins.load() })
watch(() => authStore.isAuthenticated, (now, before) => { if (now && !before) void navPins.load(true) })
const pinnedItems = computed<NavItem[]>(() => navPins.pins.value
  .map((p) => navItemByPath(p))
  .filter((i): i is NavItem => !!i && itemState(i) !== 'hide'))
const pinBusy = ref(false)
async function togglePinFor(item: NavItem) {
  if (pinBusy.value) return
  pinBusy.value = true
  try {
    const r = await navPins.toggle(item.path)
    if (r === 'failed') uiStore.showError(t('nav.pins.failedTitle', 'Pin not saved'), t('nav.pins.failed', 'The server did not take the change; the pins are as they were.'))
  } finally { pinBusy.value = false }
}
function pinLabel(item: NavItem): string {
  return navPins.isPinned(item.path)
    ? tp('nav.pins.unpin', 'Unpin {name}', { name: itemLabel(item) })
    : tp('nav.pins.pin', 'Pin {name}', { name: itemLabel(item) })
}
const dragPath = ref<string | null>(null)
function onPinDragStart(item: NavItem, e: DragEvent) {
  dragPath.value = item.path
  try { e.dataTransfer?.setData('text/plain', item.path); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move' } catch { /* old browsers */ }
}
async function onPinDrop(index: number) {
  const path = dragPath.value
  dragPath.value = null
  if (!path) return
  const r = await navPins.move(path, index)
  if (r === 'failed') uiStore.showError(t('nav.pins.failedTitle', 'Pin not saved'), t('nav.pins.failed', 'The server did not take the change; the pins are as they were.'))
}
/** the keyboard's way to reorder: Alt+ArrowUp / Alt+ArrowDown on a pinned entry */
function onPinKeydown(e: KeyboardEvent, item: NavItem, index: number) {
  if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return
  e.preventDefault()
  void navPins.move(item.path, e.key === 'ArrowUp' ? index - 1 : index + 1)
}

// Pocket mode, also a switch in the footer (the sidebar design): the same door the entry opens, and the mode remembered
function switchToPocket() {
  rememberUiMode('pocket')
  navigate('/pocket/home')
}

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
    if (group.items.some(item => isActive(item.path)) && !openGroups.value.has(group.id)) {
      openGroups.value = new Set(openGroups.value).add(group.id)
    }
    if (group.id === 'administration') {
      for (const sg of adminGroups(group)) {
        const key = `administration:${sg.flag}`
        if (sg.items.some(item => isActive(item.path)) && !openGroups.value.has(key)) openGroups.value = new Set(openGroups.value).add(key)
      }
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
const navigationItems = computed(() => NAV_ITEMS)

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
  } else if (e.altKey && (e.key === 'p' || e.key === 'P')) {
    e.preventDefault()
    const hit = searchResults.value[searchActiveIndex.value]
    if (hit) void togglePinFor(hit.item)
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

// V0662: who sees an entry is ONE rule (services/nav/navAccess, read from the route the entry opens): a visitor sees
// only what a visitor can open (the routes' requiresAuth false / allowAnonymous: the list this file kept by hand),
// an admin entry only an admin holding its flag. Hidden, not locked; a member's entry that needs an agent, the
// mainframe or the euro lane stays locked and says why.
const isItemHidden = (item: NavItem): boolean => itemState(item) === 'hide'

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

const isItemLocked = (item: NavItem): boolean => itemState(item) === 'lock'

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
type LockKind = 'auth' | 'mainframe' | 'agent' | 'fiat' | 'unknown'
interface LockReason {
  kind: LockKind
  title: string
  sub: string
  icon: string
}
const hoveredItem = ref<NavItem | null>(null)
const tooltipPos = ref<{ top: number; left: number } | null>(null)
let lastHoveredButton: HTMLElement | null = null

function handleItemHover(item: NavItem, event: MouseEvent | FocusEvent) {
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
  // §pass66 — Mainframe-only path on a non-mainframe registry
  if ((item.mainframeOnly || isMainframeOnlyPath(item.path)) && !_localIsMainframe.value) {
    return { kind: 'mainframe', title: 'Mainframe-only feature', sub: 'Federate with the mainframe for this — not available on cloud-ops', icon: 'mdi:server-off' }
  }
  // §FLARESHOP — the euro lane is not enabled on this registry
  if (item.requiresFiat && !_fiatEnabled.value) {
    // D6-836 (agentvault2-d6, 2026-10-25: greyed out, so it cannot be used): Fiat
    // Operations is the one item that asks; Become a Backer HIDES where the lane is off (requiresRegistryFlag)
    return { kind: 'fiat', title: 'Euro on-ramp off here', sub: 'FIAT_ONRAMP_ENABLED is off on this registry', icon: 'mdi:currency-eur-off' }
  }
  // Agent-required without an active agent
  if (item.requiresAgent && !authStore.agentToken) {
    return { kind: 'agent', title: 'Active agent required', sub: 'Pick one from the top-right →', icon: 'mdi:robot-confused-outline' }
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
const profileTitle       = ref('')   // V0665: the contributor title worn (from /developers/me)

const sidebarName = computed(() =>
  profileDisplayName.value || currentUser.value?.name || currentUser.value?.email || ''
)
const sidebarInitials = computed(() => {
  const src = sidebarName.value
  if (!src) return '?'
  return src.split(/\s+/).map((w: string) => w[0]).join('').slice(0, 2).toUpperCase()
})

// V0665: wearing a title elsewhere (the track, the flare manager) updates the line under the name at once
function onTitle(e: Event) { profileTitle.value = String((e as CustomEvent).detail || '') }
onMounted(() => window.addEventListener('ct:title', onTitle))
onUnmounted(() => window.removeEventListener('ct:title', onTitle))
onMounted(async () => {
  // Skip /developers/me for anonymous visitors (Leaderboard public route).
  // Without this guard, anonymous would 401 on every sidebar mount.
  if (!authStore.isAuthenticated) return
  try {
    const res = await apiClient.get('/developers/me')
    profileDisplayName.value = res.data.display_name || ''
    profileAvatarUrl.value   = res.data.avatar_url   || ''
    profileTitle.value       = res.data.flare_title   || ''
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
            <!-- V0665 the contributor track: the title worn under the name (the plate at the size drawn for this block) -->
            <WornTitle :title="profileTitle" :flare-tier="currentUser?.flare_tier" size="sidebar" class="sidebar-user-title" data-testid="sidebar-title" />
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
          <li v-for="(hit, i) in searchResults" :key="hit.item.path" class="sidebar-row">
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
            <!-- V0662: the search finds and pins every item; Alt+P pins the highlighted one -->
            <button type="button" class="sidebar-pin" :class="{ 'sidebar-pin--on': navPins.isPinned(hit.item.path) }"
                    data-testid="nav-pin-toggle" :aria-pressed="navPins.isPinned(hit.item.path)" :aria-label="pinLabel(hit.item)"
                    :title="pinLabel(hit.item)" :disabled="pinBusy" @mousedown.prevent="togglePinFor(hit.item)">
              <Icon :icon="navPins.isPinned(hit.item.path) ? 'mdi:pin' : 'mdi:pin-outline'" class="w-3.5 h-3.5" />
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
        <!-- V0662: the Pinned block (defaults Mission Control, OurChat, Pocket mode; drag to reorder, or
             Alt+Arrow keys; the pins follow the account). A visitor has no account and no pins. -->
        <ul v-if="pinnedItems.length" class="space-y-1 mb-3 sidebar-pinned" data-testid="nav-pinned"
            :aria-label="t('nav.pins.title', 'Pinned')">
          <li v-for="(item, index) in pinnedItems" :key="'pin:' + item.path" class="sidebar-row"
              :class="{ 'sidebar-row--drag': dragPath === item.path }"
              :draggable="!isCollapsed" @dragstart="(e) => onPinDragStart(item, e)" @dragover.prevent @drop.prevent="onPinDrop(index)">
            <button
              @click="isItemLocked(item) ? handleLockedClick(item) : navigate(item.path)"
              @keydown="(e) => onPinKeydown(e, item, index)"
              :data-tour="'nav-' + item.path.replace(/^\//,'').replace(/\//g,'-')"
              :class="['sidebar-nav-item w-full flex items-center px-3 py-2 rounded-lg transition-all', isItemLocked(item) ? 'sidebar-nav-locked' : (isActive(item.path) ? 'sidebar-nav-active' : 'sidebar-nav-inactive')]"
              :title="isCollapsed ? itemLabel(item) : undefined"
            >
              <Icon :icon="item.icon" :class="`w-5 h-5 shrink-0 ${isActive(item.path) ? 'sidebar-icon-active' : 'sidebar-icon-inactive'}`" />
              <span v-if="!isCollapsed" class="sidebar-nav-label ml-3">{{ itemLabel(item) }}</span>
              <span v-if="!isCollapsed && badgeCount(item) > 0" class="sidebar-badge" data-testid="nav-badge-chat"
                    :aria-label="String(badgeCount(item))">{{ badgeCount(item) > 99 ? '99+' : badgeCount(item) }}</span>
              <span v-else-if="isCollapsed && badgeCount(item) > 0" class="sidebar-badge-dot" data-testid="nav-badge-chat-dot" />
            </button>
            <button v-if="!isCollapsed" type="button" class="sidebar-pin sidebar-pin--on" data-testid="nav-pin-toggle"
                    :aria-pressed="true" :aria-label="pinLabel(item)" :title="pinLabel(item)" :disabled="pinBusy"
                    @click.stop="togglePinFor(item)">
              <Icon icon="mdi:pin" class="w-3.5 h-3.5" />
            </button>
          </li>
        </ul>

        <!-- Grouped navigation -->
        <div v-for="group in visibleGroups" :key="group.id" class="mb-1" :data-nav-group="group.id">
          <!-- Group header -->
          <button
            @click="isCollapsed ? undefined : toggleGroup(group.id)"
            :class="['sidebar-group-header w-full flex items-center px-3 py-1.5 rounded-md transition-all', groupHasActive(group) ? 'sidebar-group-active' : '']"
            :title="isCollapsed ? groupLabel(group) : undefined"
          >
            <Icon :icon="group.icon" :class="`w-4 h-4 shrink-0 ${groupHasActive(group) ? 'sidebar-icon-active' : 'sidebar-group-icon'}`" />
            <span v-if="!isCollapsed" class="sidebar-group-label ml-3 flex-1 text-left">{{ groupLabel(group) }}</span>
            <Icon v-if="!isCollapsed" icon="mdi:chevron-down" :class="['w-4 h-4 sidebar-group-chevron transition-transform', isGroupOpen(group.id) ? 'rotate-180' : '']" />
          </button>

          <!-- Group items (collapsible). V0662: Administration in collapsible sub-groups, one per admin flag; each entry
               has a pin toggle (pin any item from its category). -->
          <template v-if="!isCollapsed && isGroupOpen(group.id)">
            <div v-if="group.id === 'administration'" class="mt-0.5 ml-2 pl-2 sidebar-group-items">
              <div v-for="sg in adminGroups(group)" :key="sg.flag" class="sidebar-subgroup" data-testid="nav-admin-subgroup" :data-flag="sg.flag">
                <button type="button" class="sidebar-subgroup-header w-full flex items-center px-2 py-1 rounded-md"
                        :aria-expanded="isGroupOpen('administration:' + sg.flag)" @click="toggleGroup('administration:' + sg.flag)">
                  <span class="flex-1 text-left">{{ adminGroupLabel(sg.flag) }}</span>
                  <span class="sidebar-subgroup-count">{{ sg.items.length }}</span>
                  <Icon icon="mdi:chevron-down" :class="['w-3.5 h-3.5 sidebar-group-chevron transition-transform', isGroupOpen('administration:' + sg.flag) ? 'rotate-180' : '']" />
                </button>
                <ul v-if="isGroupOpen('administration:' + sg.flag)" class="space-y-0.5 mt-0.5">
                  <li v-for="item in sg.items" :key="item.path" class="sidebar-row">
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
                    </button>
                    <button type="button" class="sidebar-pin" :class="{ 'sidebar-pin--on': navPins.isPinned(item.path) }" data-testid="nav-pin-toggle"
                            :aria-pressed="navPins.isPinned(item.path)" :aria-label="pinLabel(item)" :title="pinLabel(item)" :disabled="pinBusy"
                            @click.stop="togglePinFor(item)">
                      <Icon :icon="navPins.isPinned(item.path) ? 'mdi:pin' : 'mdi:pin-outline'" class="w-3.5 h-3.5" />
                    </button>
                  </li>
                </ul>
              </div>
            </div>
            <ul v-else class="space-y-0.5 mt-0.5 ml-2 pl-2 sidebar-group-items">
              <li v-for="item in group.items" :key="item.path" v-show="!isItemHidden(item)" class="sidebar-row">
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
                <button v-if="authStore.isAuthenticated" type="button" class="sidebar-pin" :class="{ 'sidebar-pin--on': navPins.isPinned(item.path) }"
                        data-testid="nav-pin-toggle" :aria-pressed="navPins.isPinned(item.path)" :aria-label="pinLabel(item)" :title="pinLabel(item)"
                        :disabled="pinBusy" @click.stop="togglePinFor(item)">
                  <Icon :icon="navPins.isPinned(item.path) ? 'mdi:pin' : 'mdi:pin-outline'" class="w-3.5 h-3.5" />
                </button>
              </li>
            </ul>
          </template>

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

        <!-- V0664: the newest public announcements, where a visitor has only a sign-in line (nothing when there are none) -->
        <PublicAnnouncementsStrip v-if="!authStore.isAuthenticated && !isCollapsed" />

        <!-- V0662: a visitor sees only what a visitor can open, and one line for the rest -->
        <button v-if="!authStore.isAuthenticated && !isCollapsed" type="button" class="sidebar-guest-line w-full text-left px-3 py-2 mt-2"
                data-testid="nav-guest-signin" @click="router.push('/login')">
          <Icon icon="mdi:login" class="w-4 h-4 shrink-0" />
          <span>{{ t('nav.anon.signInLine', 'Sign in for your agents, OurChat and the rest') }}</span>
        </button>
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
        
        <!-- V0662: Pocket mode, also a switch in the footer; the desktop shell is the "off" side -->
        <button
          v-if="authStore.isAuthenticated"
          type="button"
          role="switch"
          :aria-checked="false"
          data-testid="nav-pocket-switch"
          class="sidebar-nav-item sidebar-nav-inactive w-full flex items-center px-3 py-2 rounded-lg transition-all"
          :title="isCollapsed ? t('nav.items.pocketMode', 'Pocket mode') : undefined"
          @click="switchToPocket"
        >
          <Icon icon="mdi:cellphone" class="w-5 h-5 shrink-0 sidebar-icon-inactive" />
          <span v-if="!isCollapsed" class="sidebar-nav-label ml-3 flex-1 text-left">{{ t('nav.items.pocketMode', 'Pocket mode') }}</span>
          <span v-if="!isCollapsed" class="sidebar-switch" aria-hidden="true"><span class="sidebar-switch-knob" /></span>
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
.sidebar-user-title { margin-top: 4px; }
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

/* ─── V0662 sidebar: pins, admin sub-groups, the visitor's line, the Pocket switch ─── */
.sidebar-row { position: relative; }
.sidebar-row > .sidebar-nav-item, .sidebar-row > .sidebar-qs-hit { padding-right: 1.9rem; }
.sidebar-pin {
  position: absolute; top: 50%; right: 4px; transform: translateY(-50%);
  width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 6px; border: 1px solid transparent; background: transparent;
  color: rgba(var(--nc-primary-rgb), 0.55); opacity: 0; cursor: pointer;
  transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
}
/* shown on the row's hover and to the keyboard; a pinned entry always says so */
.sidebar-row:hover .sidebar-pin, .sidebar-pin:focus-visible, .sidebar-pin--on { opacity: 1; }
.sidebar-pin:hover { background: rgba(var(--nc-primary-rgb), 0.12); color: rgb(var(--nc-primary-rgb)); }
.sidebar-pin:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.85); outline-offset: 1px; }
.sidebar-pin--on { color: rgb(var(--nc-primary-rgb)); }
.sidebar-pin:disabled { cursor: progress; }
@media (hover: none) { .sidebar-pin { opacity: 1; } }
.sidebar-pinned { padding-bottom: 0.5rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); }
.sidebar-pinned .sidebar-row[draggable="true"] { cursor: grab; }
.sidebar-row--drag { opacity: 0.5; }
.sidebar-subgroup + .sidebar-subgroup { margin-top: 0.15rem; }
.sidebar-subgroup-header {
  font-size: 0.68rem; letter-spacing: 0.04em; color: rgba(255, 255, 255, 0.62);
  background: transparent; border: 0; cursor: pointer; gap: 0.4rem;
}
.sidebar-subgroup-header:hover { color: rgb(var(--nc-primary-rgb)); }
.sidebar-subgroup-header:focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.85); outline-offset: 1px; }
.sidebar-subgroup-count { font-size: 0.6rem; opacity: 0.6; font-variant-numeric: tabular-nums; }
.sidebar-guest-line {
  display: flex; align-items: center; gap: 0.5rem; font-size: 0.74rem; border-radius: 8px;
  color: rgba(var(--nc-primary-rgb), 0.85); background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.3); cursor: pointer;
}
.sidebar-guest-line:hover { background: rgba(var(--nc-primary-rgb), 0.12); }
.sidebar-switch {
  position: relative; width: 26px; height: 14px; border-radius: 999px; flex: 0 0 auto;
  background: rgba(255, 255, 255, 0.12); border: 1px solid rgba(255, 255, 255, 0.2);
}
.sidebar-switch-knob {
  position: absolute; top: 1px; left: 1px; width: 10px; height: 10px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
}
</style>
