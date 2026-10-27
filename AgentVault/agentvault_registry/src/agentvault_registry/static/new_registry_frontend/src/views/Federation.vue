<script setup lang="ts">
// Federation view (rewritten 2026-04-21 — WS2 polish pass).
//
// Tier-bucketed federation topology with drawer-based detail. Mirrors the
// neural-command pattern shipped in AdminDevelopers / AdminAgents /
// OperatorManagement: .hm-module wrapper, .fed-* scoped CSS, hero + KPI row
// + filter-bar + tier sections + Teleport drawer.
//
// Data path:
//   admin   → GET /api/v1/admin/federation/topology-overview (drift, license, trust)
//   public  → GET /api/v1/public/topology                    (tier buckets only)
//
// Network tab preserves the original force-style topology graph using the
// /public/topology edges. Filter bar switches the active tier focus.
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import FederationOperationsPanel from '@/components/federation/FederationOperationsPanel.vue'
import FederationDirectoryPanel from '@/components/federation/FederationDirectoryPanel.vue'
// §pass-N (2026-05-21) — flagship polish pass for Network tab.
import PeerHoverPopover from '@/components/federation/PeerHoverPopover.vue'
import PeerOrb from '@/components/federation/PeerOrb.vue'
import LiveFederationFeed, { type FeedEvent } from '@/components/federation/LiveFederationFeed.vue'
import PeerDetailDrawer from '@/components/federation/PeerDetailDrawer.vue'
import { useViewport } from '@/composables/useViewport'
import { Teleport } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiClient } from '@/services/api/client'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useFederationEvents, FEDERATION_EVENT_TYPES } from '@/composables/useFederationEvents'
import { usePermissions } from '@/composables/usePermissions'
import { useI18n } from '@/composables/useI18n'
import { useLiveRefresh } from '@/composables/useLiveRefresh'
import { useAlive } from '@/composables/useAlive'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const { t, tp } = useI18n()

const authStore = useAuthStore()
// RBAC §65 (2026-05-08): migrated from `authStore.isAdmin` (super-flag only)
// to `permissions.canFederation` (sub-flag aware) so admin_federation-only
// admins see Operations tab + Add Peer CTAs + Force re-key buttons. Super-flag
// continues to pass via usePermissions short-circuit (no regression).
const { canFederation } = usePermissions()
const uiStore = useUIStore()

// ── Types ───────────────────────────────────────────────────
interface PeerBase {
  id: number
  name: string
  base_url: string
  status: string
  peer_type: string
  hop_distance: number | null
  discovered_at: string | null
  registered_at: string | null
  approved_at: string | null
  last_synced_at: string | null
  operator_did: string | null
  trust_domain: string | null
  parent_registry_id: number | null
  parent_name?: string | null
  last_seen_in_topology_at?: string | null
  bfs_reachable?: boolean
  // Admin fields (only present in admin response)
  license_id?: string | null
  license_status?: string | null
  license_key_prefix?: string | null
  license_suspended_at?: string | null
  license_suspended_reason?: string | null
  license_revoked_at?: string | null
  license_revoked_reason?: string | null
  federation_tier?: string | null
  application_id?: string | null
  application_status?: string | null
  cloud_hosted?: boolean
  cloud_url?: string | null
  cloud_provisioned_at?: string | null
  cloud_torn_down_at?: string | null
  health_check_failure_count?: number
  last_health_check_attempt_at?: string | null
  healthy?: boolean
  total_interactions?: number
  disputes_lost_with?: number
  bayesian_discount?: number
  last_interaction_at?: string | null
  drift_flags?: string[]
  has_drift?: boolean
  // §pass54: bundle freshness (frame peers only).
  bundle_freshness?: {
    trust_domain: string
    not_before: string | null
    not_after: string | null
    age_seconds: number | null
    expires_in_seconds: number | null
    refresh_overdue: boolean
    refresh_critical: boolean
    error: string | null
  } | null
  // §pass60-60.2 Registry Card v0.3 fields (visual identity + signature trust + fees).
  // Present in topology-overview admin response + /public/topology since 2026-05-21.
  visual?: PeerVisual | null
  fees?: PeerFees | null
  fees_summary?: PeerFees | null
  lifecycle?: {
    status?: string | null
    card_etag?: string | null
    card_updated_at?: string | null
    quarantine_reason?: string | null
  } | null
  card_etag?: string | null
  card_signature_verified?: boolean
  card_signature_kid?: string | null
  card_last_pulled_at?: string | null
}

// Registry Card v0.3 visual identity (§pass60 schema).
// Mirrors backend `core/registry_identity.py:RegistryCardVisual` shape.
interface PeerVisual {
  theme?: string | null
  icon_url?: string | null
  icon_etag?: string | null
  icon_size_bytes?: number | null
  orb_color?: string | null
  orb_glow_color?: string | null
  orb_pulse_speed_hz?: number | null
  orb_size_px?: number | null
  halo_enabled?: boolean | null
  halo_thickness?: number | null
  sovereign_variant?: string | null
  flare_corner_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  schema_compat?: string | null
}

interface PeerFees {
  intra_registry?: number | null
  cross_registry?: number | null
  hosting_enabled?: boolean | null
  hosting_rate?: number | null
}

interface TopologyResponse {
  frames: PeerBase[]
  direct_peers: PeerBase[]
  discovered: PeerBase[]
  cloud_operators: PeerBase[]
  summary?: {
    total_peers: number
    peers_by_type: Record<string, number>
    license_status_breakdown: Record<string, number>
    drift_count: number
    oldest_discovered_at: string | null
    healthy_count: number
    // §pass54 bundle freshness rollup
    bundles_fresh?: number
    bundles_overdue?: number
    bundles_critical?: number
    bundles_unknown?: number
    oldest_bundle_age_seconds?: number | null
  }
  // Public-only legacy keys (preserved for the Network graph tab).
  // §pass60.2 added visual/fees/etag/signature on __local__ entry (and
  // progressively on peers via federation_sync card-pull). Optional everywhere
  // — Pass 1+ readers must handle absence gracefully.
  registries?: Array<{
    name: string
    publicUrl: string
    domain: string
    hopDepth: number
    trust_domain?: string | null
    visual?: PeerVisual | null
    fees_summary?: PeerFees | null
    card_etag?: string | null
    card_signature_verified?: boolean | null
  }>
  edges?: string[]
  topology_version?: number
}

type TierKey = 'all' | 'frame' | 'direct_peer' | 'discovered' | 'cloud_operator'
type DrawerTab = 'overview' | 'health' | 'lifecycle' | 'trust' | 'agents' | 'events'

const DRIFT_LABELS: Record<string, string> = {
  license_revoked_operator_active: 'License revoked — operator still active',
  operator_revoked_license_active: 'Operator revoked — license still active',
  peer_inactive_license_active: 'Peer unreachable — direct peering INACTIVE and no chain connection',
  frame_bundle_stale: 'Frame trust bundle stale — SPIRE federation relationship or bundle missing',
  frame_bundle_expired: 'Frame trust bundle EXPIRED — every root is past not_after. SPIRE cannot self-heal this: the refresh authenticates against this very bundle',
  frame_bundle_expiring: 'Frame trust bundle expires soon — SPIRE should refresh before then; if it does not, it becomes unrecoverable',
  frame_bundle_refresh_overdue: 'Frame trust bundle refresh OVERDUE — bundle older than 5 days (>120h since cert NotBefore)',
  frame_bundle_refresh_critical: 'Frame trust bundle refresh CRITICAL — bundle older than 6 days OR expires within 24h',
  peer_url_misconfigured: 'Peer URL misconfigured — base_url likely missing the :8443 mTLS federation port',
  operator_network_topology: 'Operator Docker network drift — missing identity_network attachment or wrong per-frame alias',
}

// 2026-05-06 audit T7 — drift remediation hints. Per-drift-type structured
// guidance shown alongside the flag in drawer Lifecycle. Goal: Commander sees
// the drift AND knows what to do without leaving the view.
type DriftHint = {
  cause: string         // root cause in one sentence
  remediation: string   // what to do
  cli?: string          // optional shell command to copy
  autoHeal?: string     // note about reactor that may auto-fix
}
const DRIFT_HINTS: Record<string, DriftHint> = {
  license_revoked_operator_active: {
    cause: 'The operator\'s federation license is revoked but the OperatorApplication is still in approved/suspended state.',
    remediation: 'Reconcile via /admin/operators/{id}/revoke OR reinstate the license if revocation was accidental.',
  },
  operator_revoked_license_active: {
    cause: 'The OperatorApplication is revoked but the FederationLicense is still active. Legacy pre-D2 cascade gap.',
    remediation: 'Revoke the license via /admin/federation/licenses/{id}/revoke to bring states in sync.',
  },
  peer_inactive_license_active: {
    cause: 'peer_registries.status=INACTIVE but the operator\'s license is active AND the peer is NOT chain-reachable via BFS.',
    remediation: 'Either reactivate the peer (admin action), reinstate the license, OR confirm the operator is decommissioned and revoke the license.',
  },
  frame_bundle_stale: {
    cause: 'SPIRE-server lacks either the federation relationship OR the trust bundle for this frame. Cross-frame mTLS will fail.',
    remediation: 'Use Frame Management → "Resync EventStore" on this frame, OR re-import the bundle via FrameTrustManager.add_peer_bundle().',
  },
  frame_bundle_expired: {
    cause: 'Every root in this frame\'s trust bundle is past not_after. The bundle is PRESENT, so every existence check passes, and cross-frame mTLS fails on "unable to get local issuer certificate".',
    remediation: 'Manual bootstrap, and it is the only way out: `docker exec <peer-spire> spire-server bundle show -format pem > b.pem`, copy it in, `spire-server bundle set -id spiffe://<td> -path b.pem`, then restart this frame\'s cert-writer so /certs re-renders. Confirm recovery by the words "Bundle refreshed" in the spire-server log, not by the absence of errors.',
    autoHeal: 'NONE, by construction. The https_spiffe profile authenticates the peer bundle endpoint AGAINST THE BUNDLE THE CALLER ALREADY HOLDS, so once it expires the fetch that would replace it can never be verified. A frame stopped across its peer\'s CA rotation lands here and stays. Measured 2026-09-09 on frame-b and frame-c.',
  },
  frame_bundle_expiring: {
    cause: 'The bundle is still valid but inside the warning window (FEDERATION_BUNDLE_EXPIRY_WARN_SECONDS, default 72h).',
    remediation: 'Usually none — SPIRE refreshes on its own well before this. If the window keeps shrinking cycle over cycle, the refresh is failing: read the spire-server log for "Error updating bundle" and fix that BEFORE it expires, because after expiry only a manual bundle set can recover it.',
    autoHeal: 'Yes, while it is still valid. That is the whole reason this warning exists separately from frame_bundle_expired.',
  },
  frame_bundle_refresh_overdue: {
    cause: 'Federated trust bundle has not been refreshed in >120h (5d). SPIRE federation auto-refresh is silently failing — bundle is still trusted, but the next rotation will leave us without a valid chain.',
    remediation: 'Check SPIRE server logs for `federation` errors. Manually refresh: `docker exec <peer-spire> bundle show -format pem | docker exec -i <our-spire> bundle set -id spiffe://<td> -format pem`.',
    autoHeal: 'SPIRE\'s built-in federation refresh runs every refresh_hint (default ~84h). If it\'s overdue, the federation_relationship config or DNS to the peer\'s bundle endpoint is broken.',
  },
  frame_bundle_refresh_critical: {
    cause: 'Trust bundle is >6d old OR expires in <24h. Cross-frame mTLS will start failing within hours.',
    remediation: 'URGENT: Manual bundle exchange via FrameTrustManager.add_peer_bundle(). Investigate why federation auto-refresh stopped (network path? federation relationship deleted?).',
  },
  peer_url_misconfigured: {
    cause: 'ACTIVE peer has no successful sync in 30+ min. Most common cause: peer.base_url missing the mTLS federation port (:8443 / :27N43).',
    remediation: 'The reactor_peer_url_self_heal worker auto-fixes this within ~5 min by probing alternate ports. Check back, or run drift-scan to retrigger.',
    autoHeal: 'reactor_peer_url_self_heal — usually auto-resolves within one drift cycle',
  },
  operator_network_topology: {
    cause: 'cloud-op-* nginx-federation container is missing one of the identity_networks (agentvault_identity_network, frame_b_identity_network) OR has the wrong per-frame Docker alias.',
    remediation: 'Run the network-topology repair script on the operator host. Sandbox operators are skipped by design.',
    cli: 'bash scripts/fix-operator-networks.sh <operator-name>',
  },
}

// ── State ───────────────────────────────────────────────────
const loading = ref(true)
const error = ref<string | null>(null)
const topology = ref<TopologyResponse | null>(null)
const filter = ref<TierKey>('all')
const search = ref('')
// 2026-05-08 polish round 3: 'operations' tab added — admin-gated panel
// merged from the standalone /admin/peers view. Existing tabs untouched.
// §FEDDIR (2026-09-09) — ONE list, because there were two and they disagreed. `hydrateFromUrl`
// hard-coded its own idea of the valid tabs and silently coerced everything else to 'tiers', so
// `/federation?tab=operations` (the redirect at router/index.ts:1009) has been landing on the
// wrong tab: the `'operations'` arm of its own `if` was unreachable. A fourth tab would have
// inherited that on day one. The membership test below reads from this constant.
const TOP_TABS = ['tiers', 'network', 'operations', 'directory'] as const
type TopTab = typeof TOP_TABS[number]
const activeTopTab = ref<TopTab>('tiers')

// Drawer
const drawerOpen = ref(false)
const drawerPeer = ref<PeerBase | null>(null)
const drawerTab = ref<DrawerTab>('overview')
const drawerEvents = ref<any[]>([])
const drawerEventsLoading = ref(false)
const drawerHealthProbe = ref<any>(null)
const drawerHealthProbing = ref(false)

// Add-direct-peer modal
const addOpen = ref(false)
const addForm = ref({ name: '', base_url: '', admin_contact_email: '', description: '' })
const addSubmitting = ref(false)

// Drift scan
const driftScanning = ref(false)

// 2026-05-06 audit T1 — last-refreshed indicator: tracks when topology was last
// successfully fetched so the user can see staleness without inferring from polling.
// Pairs with countdown to next auto-poll (60s loadTopology cycle, 90s invitations).
// §FEDCLOCK (2026-09-09) — this readout is now `composables/useLiveRefresh.ts`, lifted verbatim
// from here so /admin/compliance could carry the identical clock instead of a second copy. The
// declaration stays at this line because `showLiveBadge` below reads `nowTick`; the composable
// also adds the pause-on-hidden guard this page never had (a background tab polled forever).
// ⚠ DECLARED ABOVE THE CALL ON PURPOSE. `intervalMs` is evaluated the instant this composable is
// constructed, so a `const` declared further down the file is a TDZ ReferenceError — which blanks
// the whole view with no 4xx and no pageerror (§HIRECOHERE). `loadTopology` and `hoverVisible`
// below are safe at any position: they are only ever CALLED from the interval, after setup.
const POLL_INTERVAL_MS = 60_000
const live = useLiveRefresh(() => { void loadTopology() }, {
  intervalMs: POLL_INTERVAL_MS,
  // §pass61.3 (2026-05-21) — sticky hover gate on the polling tick, preserved exactly.
  shouldSkip: () => hoverVisible.value,
})
const lastFetchedAt = live.lastFetchedAt
const nowTick = live.nowTick
const lastRefreshedLabel = live.lastRefreshedLabel
const nextRefreshInSeconds = live.nextRefreshInSeconds

// 2026-05-06 audit T6 — WebSocket-driven federation event subscriptions.
// Replaces 60s polling latency with sub-second push updates from EventStore.
// Polling stays in place as the safety net when WS is disconnected.
const wsEvents = useFederationEvents({
  // §pass61.3 (2026-05-21) — sticky hover: skip refresh while popover is
  // visible. SVG re-render due to topology.value reassign was firing
  // mouseleave on the hovered <g> (DOM patch invalidates the hover state),
  // making the popover vanish mid-hover. Once the user moves the mouse away,
  // the next refresh tick catches up.
  onRefresh: () => {
    if (hoverVisible.value) return
    loadTopology()
  },
  onLiveEvent: (evtType, payload) => {
    // Surface arrival of a federation event in the corner so the operator
    // knows fresh data is incoming, without spamming a toast per event.
    lastWsEventLabel.value = evtType
    lastWsEventAt.value = Date.now()
    // §pass-N Pass 4: edge-flash on PeerRegistryUrlAutoCorrected — visual
    // indicator that the reactor just self-healed a stale peer URL. Edges
    // incident to the healed peer briefly pulse cyan.
    if (evtType === 'PeerRegistryUrlAutoCorrected' && payload) {
      const peerId = payload?.peer_id ?? payload?.data?.peer_id
      if (peerId != null) flashEdgesForPeer(peerId)
    }
    // §pass-N Pass 5: push event onto the live feed sidebar (capped at 30).
    pushLiveFeedEvent(evtType, payload)
  },
  debounceMs: 500,
})
const lastWsEventLabel = ref<string>('')
const lastWsEventAt = ref<number>(0)

// §pass-N Pass 4 — edge-flash state. Keyed by graphEdge.key
// (`<parentKey>::<childKey>` format). Cleared after 2500ms.
const flashingEdges = ref<Set<string>>(new Set())
function flashEdgesForPeer(peerId: number, durationMs = 2500) {
  // Look up the peer's node key by id (peersById → name → graphNode)
  const peer = peersById.value.get(peerId)
  if (!peer) return
  // Find the node matching this peer via url-hostname OR name
  const targetNode = graphNodes.value.find(n => {
    if (!n.peer) return false
    if (n.peer.id === peerId) return true
    return false
  })
  if (!targetNode) return
  // Mark all edges whose key includes this node's key as flashing
  const key = targetNode.key
  const fresh = new Set(flashingEdges.value)
  for (const edge of graphEdges.value) {
    const [from, to] = (edge.key || '').split('::')
    if (from === key || to === key) fresh.add(edge.key)
  }
  flashingEdges.value = fresh
  setTimeout(() => {
    const after = new Set(flashingEdges.value)
    for (const edge of graphEdges.value) {
      const [from, to] = (edge.key || '').split('::')
      if (from === key || to === key) after.delete(edge.key)
    }
    flashingEdges.value = after
  }, durationMs)
}

// ── Pass 7: Network stress signaling (chromatic aberration) ──
// When the network has visible stress (drift count, critical/overdue bundles),
// apply a subtle red/cyan chromatic-aberration filter to the panel — instant
// at-a-glance signal of system stress, even before reading pill counts.
// Mirrors GlitchOverlay.vue's offset-via-CSS-var pattern (no new colors).
const networkStressLevel = computed<number>(() => {
  const s = topology.value?.summary
  if (!s) return 0
  let stress = 0
  if (typeof s.drift_count === 'number' && s.drift_count > 0) {
    stress += Math.min(s.drift_count / 5, 0.4)  // saturate at 5 drifts
  }
  if (typeof s.bundles_critical === 'number' && s.bundles_critical > 0) stress += 0.35
  if (typeof s.bundles_overdue === 'number' && s.bundles_overdue > 0) stress += 0.15
  return Math.min(stress, 1)
})
const showNetworkStress = computed(() => networkStressLevel.value > 0.05)
// Label summarizing the stress cause for the inline pill.
const networkStressLabel = computed(() => {
  const s = topology.value?.summary
  if (!s) return ''
  const parts: string[] = []
  if (s.drift_count && s.drift_count > 0) parts.push(`${s.drift_count} drift`)
  if (s.bundles_critical && s.bundles_critical > 0) parts.push(`${s.bundles_critical} critical`)
  if (s.bundles_overdue && s.bundles_overdue > 0) parts.push(`${s.bundles_overdue} overdue`)
  return parts.join(' · ')
})

// ── Pass 6: Viewport + mobile fallback ───────────────────────
const vp = useViewport()
const showNetworkGraphSvg = computed(() => !vp.isMobile.value)
// On mobile: sort peers by hop_distance then name for a clean linear list.
const sortedPeersForMobile = computed<PeerBase[]>(() => {
  if (!topology.value) return []
  const all = [
    ...(topology.value.frames || []),
    ...(topology.value.direct_peers || []),
    ...(topology.value.discovered || []),
    ...(topology.value.cloud_operators || []),
  ]
  return all.slice().sort((a, b) => {
    const ha = a.hop_distance ?? 999
    const hb = b.hop_distance ?? 999
    if (ha !== hb) return ha - hb
    return (a.name || '').localeCompare(b.name || '')
  })
})

// ── Pass 5: Live federation feed sidebar ─────────────────────
// §pass62.1 (2026-05-21) — Per-view localStorage key (`:network` suffix) so
// collapse state doesn't fight with Federation Peers view (which uses
// `:discovery` suffix). Backfill on mount via /admin/events to populate feed
// with last 20 federation events — closes the "empty feed on healthy
// federation" perception bug Commander flagged.
const LIVE_FEED_COLLAPSED_KEY = 'theprotocol:federation:network:liveFeed:collapsed'
const LIVE_FEED_MAX = 20  // §pass61.1 reduced from 30 — display max ~10 visible
const liveFeedEvents = ref<FeedEvent[]>([])
const liveFeedCollapsed = ref<boolean>(
  (typeof localStorage !== 'undefined' && localStorage.getItem(LIVE_FEED_COLLAPSED_KEY) === 'true')
)
const lastFederationEventIso = ref<string | null>(null)
// §pass61.1 — track recent event IDs to dedup EventStore's 15-event backlog
// replay (fires every WS subscribe — was creating duplicate feed entries).
const _seenEventIds = new Set<string>()
const _SEEN_EVENT_CAP = 200
function pushLiveFeedEvent(eventType: string, payload?: any, opts?: { historical?: boolean }) {
  // Dedup by EventStore event.id when present (drops backlog-replay dupes).
  const evtId = payload?.id || payload?.event_id || payload?.data?.id
  if (evtId && _seenEventIds.has(evtId)) return
  if (evtId) {
    _seenEventIds.add(evtId)
    if (_seenEventIds.size > _SEEN_EVENT_CAP) {
      // FIFO trim — drop oldest 50 when we hit the cap
      const arr = Array.from(_seenEventIds)
      _seenEventIds.clear()
      arr.slice(50).forEach(id => _seenEventIds.add(id))
    }
  }
  // §pass61.1 — also dedup by (type + 2s window) for events without IDs
  // (catches WS reconnect storms where the same type fires repeatedly).
  const now = Date.now()
  const recent = liveFeedEvents.value[0]
  if (recent && recent.type === eventType && (now - recent.ts) < 2000 && !evtId) return
  const id = `${eventType}-${now}-${Math.random().toString(36).slice(2, 8)}`
  liveFeedEvents.value.unshift({ id, type: eventType, ts: now, payload, historical: !!opts?.historical })
  if (liveFeedEvents.value.length > LIVE_FEED_MAX) {
    liveFeedEvents.value.length = LIVE_FEED_MAX
  }
}
function toggleLiveFeed() {
  liveFeedCollapsed.value = !liveFeedCollapsed.value
  try {
    localStorage.setItem(LIVE_FEED_COLLAPSED_KEY, liveFeedCollapsed.value ? 'true' : 'false')
  } catch { /* ignore — private browsing etc. */ }
}

// §pass62.1 — backfill last 20 federation events on mount.
// §pass71.6 (2026-05-25) — fixed endpoint mismatch surfaced by the autonomous
// audit: was calling /admin/events (404 — doesn't exist) with param event_types
// (also wrong — backend takes singular event_type). Real endpoint is
// /admin/events/search per openapi spec, with comma-separated `event_type`.
// Pre-fix: federation events feed was silently empty on every page load —
// only realtime WS events showed up; the 20-event historical backfill never
// landed. Best-effort — silent on 403/network errors.
async function backfillFederationEvents() {
  // §FINDFIX F3 — /admin/events/search is admin-gated; for every non-admin the
  // call was a guaranteed 403 console error per page load. Gate on the same
  // permission the view already uses for its admin surfaces.
  if (!canFederation.value) return
  try {
    const types = Array.from(FEDERATION_EVENT_TYPES).join(',')
    const r = await apiClient.get('/admin/events/search', { params: { limit: 20, event_type: types } })
    const body = r.data
    const items: any[] = Array.isArray(body) ? body : (body?.items || body?.events || [])
    if (!items.length) return
    items.sort((a, b) => {
      const ta = new Date(a.timestamp || a.event_timestamp || 0).getTime()
      const tb = new Date(b.timestamp || b.event_timestamp || 0).getTime()
      return ta - tb
    })
    let mostRecent: string | null = null
    for (const ev of items) {
      const evtType = ev.event_type || ev.type
      const tsIso = ev.timestamp || ev.event_timestamp
      if (!evtType) continue
      const ts = tsIso ? new Date(tsIso).getTime() : Date.now()
      const evtId = ev.id || ev.event_id
      if (evtId && _seenEventIds.has(evtId)) continue
      if (evtId) _seenEventIds.add(evtId)
      liveFeedEvents.value.unshift({
        id: evtId || `bf-${evtType}-${ts}-${Math.random().toString(36).slice(2, 8)}`,
        type: evtType, ts, payload: ev, historical: true,
      })
      if (!mostRecent || (tsIso && tsIso > mostRecent)) mostRecent = tsIso
    }
    if (liveFeedEvents.value.length > LIVE_FEED_MAX) liveFeedEvents.value.length = LIVE_FEED_MAX
    if (mostRecent) lastFederationEventIso.value = mostRecent
  } catch { /* backfill is best-effort; ignore */ }
}
// When a feed item is clicked, flash the edges of the relevant peer (if payload
// contains a peer_id) AND open the drawer for that peer if found.
function onFeedHighlight(evt: FeedEvent) {
  const peerId = evt.payload?.peer_id ?? evt.payload?.data?.peer_id
  if (peerId != null) {
    flashEdgesForPeer(peerId)
    const peer = peersById.value.get(peerId)
    if (peer) openDrawer(peer)
  }
}
// Show "Live • <event>" indicator for 4s after each event arrival.
const showLiveBadge = computed(() => {
  if (!lastWsEventAt.value) return false
  return (nowTick.value - lastWsEventAt.value) < 4000
})

// 2026-05-06 audit T4 — URL-state for shareable/persistent filter+drawer state.
// Query params: ?tab=tiers|network, ?filter=all|frame|..., ?q=search,
// ?peer=<id>, ?dt=overview|health|... — hydrated on mount, pushed on change
// (replace, not push — no history pollution).
const route = useRoute()
const router = useRouter()
let _hydratingFromUrl = true  // guard: don't push during initial hydration

// 2026-05-06 audit T7 — copy-to-clipboard helper for drift CLI hints.
const copiedHint = ref<string>('')
async function copyHintCli(cli: string) {
  try {
    await navigator.clipboard.writeText(cli)
    copiedHint.value = cli
    setTimeout(() => { if (copiedHint.value === cli) copiedHint.value = '' }, 1800)
  } catch {
    uiStore.showError?.('Copy failed', 'Clipboard write was blocked. Copy manually.')
  }
}

// 2026-05-06 audit T2 — keyboard handler: Esc closes whichever modal/drawer is
// most-recently-opened (z-stack order). Standard a11y pattern; without this
// the drawer is mouse-only.
function onGlobalKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (showRevokeFrameModal.value) { showRevokeFrameModal.value = false; e.preventDefault(); return }
  if (addOpen.value) { addOpen.value = false; e.preventDefault(); return }
  if (showInvitationsModal.value) { closeInvitationsModal(); e.preventDefault(); return }
  if (showInviteHelp.value) { showInviteHelp.value = false; e.preventDefault(); return }
  if (drawerOpen.value) { closeDrawer(); e.preventDefault(); return }
}

// Frame invitations (f058 WS3)
interface FrameInvitation {
  id: string
  initiator_trust_domain: string
  initiator_bundle_endpoint_url: string
  initiator_federation_endpoint_url: string
  initiator_name: string
  initiator_contact_email: string
  initiator_description?: string | null
  initiator_ip?: string | null
  status: string
  reviewed_by?: number | null
  reviewed_at?: string | null
  review_notes?: string | null
  rejection_reason?: string | null
  completed_at?: string | null
  peer_registry_id?: number | null
  spire_bundle_imported_at?: string | null
  revoked_by?: number | null
  revoked_at?: string | null
  revoked_reason?: string | null
  created_at: string
  updated_at: string
}
const pendingInvitations = ref<FrameInvitation[]>([])
const invitationsLoading = ref(false)
const showInvitationsModal = ref(false)
const selectedInvitation = ref<FrameInvitation | null>(null)
const approveNotes = ref('')
const rejectReason = ref('')
const invitationActionBusy = ref(false)
const showInviteHelp = ref(false)
// §HELLOFRAME: the invitation endpoint the help names is THIS frame's (it said api.theprotocol.cloud on every frame)
const consoleOrigin = typeof window !== 'undefined' ? window.location.origin : ''

// Frame revoke (drawer action)
const showRevokeFrameModal = ref(false)
const revokeReason = ref('')
const revokingFrame = ref(false)

// ── Computed ────────────────────────────────────────────────
const allPeers = computed<PeerBase[]>(() => {
  if (!topology.value) return []
  return [
    ...topology.value.frames || [],
    ...topology.value.direct_peers || [],
    ...topology.value.discovered || [],
    ...topology.value.cloud_operators || [],
  ]
})

function _matchSearch(p: PeerBase, q: string): boolean {
  if (!q) return true
  const ql = q.toLowerCase()
  return (
    (p.name || '').toLowerCase().includes(ql) ||
    (p.base_url || '').toLowerCase().includes(ql) ||
    (p.operator_did || '').toLowerCase().includes(ql) ||
    (p.trust_domain || '').toLowerCase().includes(ql)
  )
}

// 2026-05-06 audit T9 — re-bucket peers by chain semantics (parent_registry_id)
// instead of literal peer_type. Backend tier-overview groups by peer_type which
// mis-categorizes:
//   - cloud_operator with parent=null   ← these ARE direct peers (chain roots)
//   - cloud_operator with parent!=null  ← these are chain children
// Without this re-bucket, "Direct Peers" KPI shows 0 because no row literally
// has peer_type='direct_peer'. The chain root op-berlin gets buried in
// "Cloud Operators" alongside its chain descendants.
//
// 2026-05-06 T11 (Commander correction): a cloud-operator chain root is BOTH
// a direct peer AND a cloud operator. Show op-berlin in both buckets — direct
// peer (relationship) and cloud operator (licensing). Cloud Operators count
// becomes the FULL cloud_op set (4), Direct Peers carries the chain-root
// subset (1) for the relationship-level view.
const cloudDirect = computed(() => (topology.value?.cloud_operators || [])
  .filter(p => p.parent_registry_id == null))

// "Direct Peers" tier = legacy direct_peer rows + cloud_operator chain roots.
// "Cloud Operators" tier = ALL cloud_operators (chain roots intentionally
// duplicated in Direct Peers for clarity — different relationship dimensions).
const directBucket = computed<PeerBase[]>(() => [
  ...(topology.value?.direct_peers || []),
  ...cloudDirect.value,
])
const cloudBucket = computed<PeerBase[]>(() => topology.value?.cloud_operators || [])

const filteredFrames = computed(() => (topology.value?.frames || []).filter(p => _matchSearch(p, search.value)))
const filteredDirect = computed(() => directBucket.value.filter(p => _matchSearch(p, search.value)))
const filteredDiscovered = computed(() => (topology.value?.discovered || []).filter(p => _matchSearch(p, search.value)))
const filteredCloud = computed(() => cloudBucket.value.filter(p => _matchSearch(p, search.value)))

// T4 — total filtered count + active-filter detection (drives empty-state + clear-all).
// Only counts tiers VISIBLE under the current `filter` selection — otherwise a
// search that matches only a tier hidden by tier-filter would falsely suppress
// the empty state.
const totalFilteredVisible = computed(() =>
  (showFrames.value ? filteredFrames.value.length : 0)
  + (showDirect.value ? filteredDirect.value.length : 0)
  + (showDiscovered.value ? filteredDiscovered.value.length : 0)
  + (showCloud.value ? filteredCloud.value.length : 0)
)
const hasActiveFilter = computed(() => filter.value !== 'all' || !!search.value)

// 2026-05-06 audit T8 — sort options. Default 'natural' preserves backend order
// (insertion / DB order). Other modes give Commander rapid sort by name (alpha),
// hop_distance (chain depth), last_synced_at (staleness), or has_drift (issues
// first). Applied AFTER tier filtering so the tier sections re-sort independently.
type SortKey = 'natural' | 'name' | 'hop' | 'last_synced' | 'drift'
const sortKey = ref<SortKey>('natural')
function applySort<T extends PeerBase>(arr: T[]): T[] {
  if (sortKey.value === 'natural' || arr.length < 2) return arr
  const copy = [...arr]
  switch (sortKey.value) {
    case 'name':
      copy.sort((a, b) => (a.name || '').localeCompare(b.name || ''))
      break
    case 'hop':
      copy.sort((a, b) => (a.hop_distance ?? 99) - (b.hop_distance ?? 99) || (a.name || '').localeCompare(b.name || ''))
      break
    case 'last_synced':
      copy.sort((a, b) => {
        const ta = a.last_synced_at ? Date.parse(a.last_synced_at) : 0
        const tb = b.last_synced_at ? Date.parse(b.last_synced_at) : 0
        return tb - ta  // freshest first
      })
      break
    case 'drift':
      copy.sort((a, b) => Number(!!b.has_drift) - Number(!!a.has_drift) || (a.name || '').localeCompare(b.name || ''))
      break
  }
  return copy
}
const sortedFrames = computed(() => applySort(filteredFrames.value))
const sortedDirect = computed(() => applySort(filteredDirect.value))
const sortedDiscovered = computed(() => applySort(filteredDiscovered.value))
const sortedCloud = computed(() => applySort(filteredCloud.value))
function clearAllFilters() {
  filter.value = 'all'
  search.value = ''
}

const showFrames = computed(() => filter.value === 'all' || filter.value === 'frame')
const showDirect = computed(() => filter.value === 'all' || filter.value === 'direct_peer')
const showDiscovered = computed(() => filter.value === 'all' || filter.value === 'discovered')
const showCloud = computed(() => filter.value === 'all' || filter.value === 'cloud_operator')

const kpis = computed(() => {
  const t = topology.value
  if (!t) return { frames: 0, direct: 0, discovered: 0, cloud: 0, drift: 0, total: 0, healthy: 0 }
  const sum = t.summary || {
    peers_by_type: {},
    drift_count: 0,
    total_peers: 0,
    healthy_count: 0,
    license_status_breakdown: {},
    oldest_discovered_at: null,
  }
  // T9 — KPI counts derived from chain-aware buckets (directBucket / cloudBucket)
  // instead of backend's literal peer_type sum. See cloudDirect/cloudChild above.
  return {
    frames: t.frames?.length || 0,
    direct: directBucket.value.length,         // includes cloud_operator with parent=null
    discovered: t.discovered?.length || 0,
    cloud: cloudBucket.value.length,            // chain children only
    drift: sum.drift_count ?? 0,
    total: sum.total_peers ?? allPeers.value.length,
    healthy: sum.healthy_count ?? 0,
    // §pass54 bundle freshness rollup
    bundlesFresh: sum.bundles_fresh ?? 0,
    bundlesOverdue: sum.bundles_overdue ?? 0,
    bundlesCritical: sum.bundles_critical ?? 0,
    bundlesUnknown: sum.bundles_unknown ?? 0,
    oldestBundleAgeSeconds: sum.oldest_bundle_age_seconds ?? null,
  }
})

const driftPeers = computed(() => allPeers.value.filter(p => p.has_drift))
// §pass54 — true when any frame has overdue OR critical bundle freshness.
const hasBundleFreshnessAlert = computed(() =>
  (kpis.value.bundlesOverdue || 0) > 0 || (kpis.value.bundlesCritical || 0) > 0
)

// ── Network graph layout ────────────────────────────────
// Concentric-ring layout by hop depth. Each ring gets its peers spread evenly
// around a circle. Local registry sits at the center. Mirrors the Tiers view's
// color scheme so the Network tab feels like the same object viewed differently.
interface GraphNode {
  key: string
  name: string
  x: number
  y: number
  r: number
  tier: string
  hop: number
  peer?: PeerBase
  isLocal?: boolean
}
interface GraphEdge {
  key: string
  x1: number; y1: number; x2: number; y2: number
  tier: string
}

const CANVAS = { w: 1000, h: 720, cx: 500, cy: 360 }
const RING_RADII = [0, 130, 220, 290, 345]   // hop 0..4+ (chain can reach 4 with Frame-B → op-tokyo → op-seoul → leaves)

function tierOfTopoRegistry(domain: string, name: string): { tier: string; peer?: PeerBase } {
  if (domain === '__local__') return { tier: 'local' }
  for (const p of allPeers.value) {
    try {
      const u = new URL(p.base_url)
      if (u.hostname.toLowerCase() === domain.toLowerCase()) return { tier: p.peer_type, peer: p }
    } catch { /* invalid URL — fall back to name */ }
    if ((p.name || '').toLowerCase() === (name || '').toLowerCase()) {
      return { tier: p.peer_type, peer: p }
    }
  }
  return { tier: 'unknown' }
}

// 2026-05-06 audit T9 — chain-aware hop computation. Backend `hop_distance`
// is 1 for ALL Frame A cloud_operator peers because BFS seeds from any
// peer_type != 'discovered', so chain children look identical to chain roots
// at that level. Walk parent_registry_id from the peer up to root to derive
// the TRUE chain depth used by the Network tab radial layout.
const peersById = computed(() => {
  const map = new Map<number, PeerBase>()
  for (const p of allPeers.value) map.set(p.id, p)
  return map
})

// §FEDDIR-HOP (2026-09-10, his report: "the hops are wrong. wrong count ... but correct on
// federation network view"). The Directory tab was rendering the INDEX's own crawl depth — BFS
// from the anchor SET — so two anchored frames both read h0 and every operator read h1 whoever
// its parent was: on EU's page ASIA read h0 (it is one hop out) and ASIA's operators read h1
// (they are two). The index's number is right about the index and wrong about the reader.
// The fix is not a second derivation: this map is keyed on `chainHopOf`, the very function the
// Network rings are laid out from, so the two tabs cannot disagree by construction.
// Name-keyed and lowercased on purpose — the index publishes `ASIA` where the peer row says
// `asia` (§SLUGCONVERGE's uppercase ghost), and a case-sensitive match would silently answer
// "not a peer of ours" about our own peer frame.
const hopByPeerName = computed<Map<string, number>>(() => {
  const m = new Map<string, number>()
  for (const p of allPeers.value) {
    const n = (p.name || '').trim().toLowerCase()
    if (n && !m.has(n)) m.set(n, chainHopOf(p))
  }
  return m
})
function chainHopOf(peer: PeerBase | undefined): number {
  if (!peer) return 1
  if (peer.peer_type === 'frame') return 1   // cross-frame bridge is hop=1
  let depth = 1
  let cursor: PeerBase | undefined = peer
  const seen = new Set<number>()
  while (cursor && cursor.parent_registry_id != null && !seen.has(cursor.id)) {
    seen.add(cursor.id)
    cursor = peersById.value.get(cursor.parent_registry_id)
    if (cursor) depth++
    else break
    if (depth > 10) break  // hard cap to prevent runaway
  }
  return depth
}

// 2026-05-06 audit T10 — parent-clustered tree layout. Replaces uniform
// angular placement (which caused crossing edges: parent at south, child
// going north because the ring spread is independent of branch). Each peer
// occupies a sub-wedge of its parent's angular space; chain branches stay
// on the same side of the canvas, edges never cross.
//
// Algorithm:
//   1. Group peers by parent (frames + parent=null go under '__local__').
//   2. Layout root: split 2π evenly across local's children, starting at -π/2.
//   3. For each child, allocate its sub-wedge proportional to its descendant
//      count (so a 4-leaf branch gets more angular space than a 1-leaf branch).
//   4. Place child at the wedge midpoint at its hop's ring radius.
//   5. Recurse on grandchildren within child's wedge.
//
// Falls back to uniform layout for topology entries without a peer_registries
// row (purely-BFS-discovered, no parent_registry_id).
const childrenByParent = computed(() => {
  const m = new Map<string, PeerBase[]>()
  m.set('__local__', [])
  for (const p of allPeers.value) {
    const isRoot = p.peer_type === 'frame' || p.parent_registry_id == null
    const key = isRoot ? '__local__' : String(p.parent_registry_id)
    if (!m.has(key)) m.set(key, [])
    m.get(key)!.push(p)
  }
  return m
})

// Count descendants (including self) for proportional wedge allocation.
function descendantCount(peerId: number, depth = 0): number {
  if (depth > 10) return 1  // safety guard
  const kids = childrenByParent.value.get(String(peerId)) || []
  if (kids.length === 0) return 1
  let sum = 1
  for (const k of kids) sum += descendantCount(k.id, depth + 1)
  return sum
}

const graphNodes = computed<GraphNode[]>(() => {
  if (!topology.value?.registries?.length) return []
  const regs = topology.value.registries
  // Build domain → reg lookup (so we can stamp the GraphNode with the BFS reg)
  const regByPeerName = new Map<string, any>()
  for (const reg of regs) {
    if (reg.domain === '__local__') continue
    const { peer } = tierOfTopoRegistry(reg.domain, reg.name)
    if (peer) regByPeerName.set(peer.name.toLowerCase(), reg)
  }
  // Find local registry for the center node
  const localReg = regs.find(r => r.domain === '__local__')

  const nodes: GraphNode[] = []

  // Place center
  if (localReg) {
    nodes.push({
      key: '__local__',
      name: localReg.name,
      x: CANVAS.cx, y: CANVAS.cy, r: 30,
      tier: 'local', hop: 0,
      peer: undefined,
      isLocal: true,
    })
  }

  // T10 — recursive tree placement starting at local
  function placeSubtree(peer: PeerBase, angle: number, wedge: number, hop: number) {
    const safeHop = Math.min(4, Math.max(1, hop))
    const radius = RING_RADII[safeHop]
    const x = CANVAS.cx + Math.cos(angle) * radius
    const y = CANVAS.cy + Math.sin(angle) * radius
    const r = safeHop === 1 ? 22 : safeHop === 2 ? 17 : safeHop === 3 ? 14 : 11
    const reg = regByPeerName.get((peer.name || '').toLowerCase())
    nodes.push({
      key: reg?.domain || (peer.base_url ? new URL(peer.base_url).hostname.toLowerCase() : peer.name),
      name: peer.name,
      x, y, r,
      tier: peer.peer_type,
      hop: safeHop,
      peer,
      isLocal: false,
    })
    const kids = childrenByParent.value.get(String(peer.id)) || []
    if (!kids.length) return
    // Allocate child wedge proportional to descendant count → balanced layout
    const totalWeight = kids.reduce((s, k) => s + descendantCount(k.id), 0) || 1
    let cursor = angle - wedge / 2
    for (const child of kids) {
      const w = descendantCount(child.id) / totalWeight
      const childWedgeWidth = wedge * w
      const childAngle = cursor + childWedgeWidth / 2
      placeSubtree(child, childAngle, childWedgeWidth, hop + 1)
      cursor += childWedgeWidth
    }
  }

  const rootKids = childrenByParent.value.get('__local__') || []
  if (rootKids.length > 0) {
    // Distribute the full 2π proportional to each branch's descendant count.
    // Start at top (-π/2). Branches get angular space ∝ subtree size, so a
    // chain of 5 (Frame B) sits next to a chain of 4 (Frame A) without
    // feeling cramped on the smaller side.
    const totalWeight = rootKids.reduce((s, k) => s + descendantCount(k.id), 0) || 1
    let cursor = -Math.PI / 2
    for (const child of rootKids) {
      const w = descendantCount(child.id) / totalWeight
      const wedgeWidth = 2 * Math.PI * w
      const angle = cursor + wedgeWidth / 2
      placeSubtree(child, angle, wedgeWidth, 1)
      cursor += wedgeWidth
    }
  }

  // Fallback: any topology entry without a peer_registries row (purely BFS-
  // discovered) gets placed on the outermost ring at uniform angles to avoid
  // disappearing entirely. Rare in practice (we own the cluster).
  const placedNames = new Set(nodes.map(n => (n.name || '').toLowerCase()))
  const orphans = regs.filter(r => r.domain !== '__local__' && !placedNames.has((r.name || '').toLowerCase()))
  if (orphans.length) {
    const radius = RING_RADII[4]
    for (let i = 0; i < orphans.length; i++) {
      const angle = (i / orphans.length) * 2 * Math.PI
      nodes.push({
        key: orphans[i].domain,
        name: orphans[i].name,
        x: CANVAS.cx + Math.cos(angle) * radius,
        y: CANVAS.cy + Math.sin(angle) * radius,
        r: 10,
        tier: 'unknown', hop: 4,
        peer: undefined, isLocal: false,
      })
    }
  }

  return nodes
})

// Toggle for edge density. Default: tree only (siblings filtered) — cleanest
// visual. Turn on to see the full federation mesh (siblings federate via their
// parent, creating cluttery edges between same-hop peers).
const showMeshEdges = ref(false)

// T9 — derive chain edges from parent_registry_id, not BFS topology.edges.
// BFS edges include spurious `__local__::<chain-grandchild>` because every
// cloud_operator is a BFS seed (regardless of parent), so Registry-A → op-paris
// shows up even though the actual chain is Registry-A → op-berlin → op-london
// → op-paris. parent_registry_id is the ground truth for the topology tree.
//
// Edge rules:
//   - peer.peer_type='frame'         → edge __local__ → peer (cross-frame bridge)
//   - peer.parent_registry_id IS NULL→ edge __local__ → peer (direct chain root)
//   - peer.parent_registry_id != null→ edge parent → peer (chain child)
//
// Mesh toggle still works: when ON, additionally include any topology.edges
// not already represented (covers ad-hoc operator-to-operator federation
// outside the chain).
const graphEdges = computed<GraphEdge[]>(() => {
  if (graphNodes.value.length === 0) return []
  const byKey = new Map<string, GraphNode>(graphNodes.value.map(n => [n.key, n]))
  const edges: GraphEdge[] = []
  const seen = new Set<string>()
  // Domain-key resolver: try peer.base_url hostname first; fall back to name match.
  function nodeForPeer(peer: PeerBase): GraphNode | undefined {
    try {
      const u = new URL(peer.base_url)
      const byHost = byKey.get(u.hostname.toLowerCase())
      if (byHost) return byHost
    } catch { /* fall through */ }
    return graphNodes.value.find(n => (n.name || '').toLowerCase() === (peer.name || '').toLowerCase())
  }
  const localNode = graphNodes.value.find(n => n.isLocal)
  if (!localNode) return []

  // Chain edges from parent_registry_id
  for (const peer of allPeers.value) {
    const childNode = nodeForPeer(peer)
    if (!childNode) continue
    let parentNode: GraphNode | undefined
    if (peer.peer_type === 'frame') {
      parentNode = localNode
    } else if (peer.parent_registry_id == null) {
      parentNode = localNode
    } else {
      const parentPeer = peersById.value.get(peer.parent_registry_id)
      if (parentPeer) parentNode = nodeForPeer(parentPeer)
    }
    if (!parentNode || parentNode === childNode) continue
    const key = `${parentNode.key}::${childNode.key}`
    if (seen.has(key)) continue
    seen.add(key)
    // Color edge by the child tier (the "deeper" side of the relationship)
    edges.push({
      key,
      x1: parentNode.x, y1: parentNode.y, x2: childNode.x, y2: childNode.y,
      tier: childNode.tier,
    })
  }

  // Optional mesh: add BFS-derived edges that aren't already in the chain
  // (sibling federation, ad-hoc operator peering). Keeps the toggle useful.
  if (showMeshEdges.value && topology.value?.edges?.length) {
    for (const raw of topology.value.edges) {
      const [a, b] = raw.split('::')
      const na = byKey.get(a); const nb = byKey.get(b)
      if (!na || !nb) continue
      const k1 = `${a}::${b}`, k2 = `${b}::${a}`
      if (seen.has(k1) || seen.has(k2)) continue
      seen.add(k1)
      const tier = na.hop >= nb.hop ? na.tier : nb.tier
      edges.push({ key: k1, x1: na.x, y1: na.y, x2: nb.x, y2: nb.y, tier })
    }
  }
  return edges
})

function onNodeClick(node: GraphNode) {
  // §pass61.5 (2026-05-21) — local node has no peer_registries row, but we
  // can still open the drawer using a constructed local pseudo-peer (mirrors
  // buildLocalPseudoPeer used by the hover popover). Without this, clicking
  // Local Registry was a silent no-op (Commander caught 2026-05-21).
  if (node.peer) {
    openDrawer(node.peer)
  } else if (node.isLocal) {
    const pseudo = buildLocalPseudoPeer(node)
    if (pseudo) openDrawer(pseudo)
  }
}

// ── Data Fetch ──────────────────────────────────────────────
// §pass61.1 (2026-05-21) — admin topology-overview does NOT include
// visual/fees_summary/card_etag/card_signature_verified per peer (those live
// in the public /topology registries[] array). When we load admin, merge the
// public registries' v0.3 fields by name match so PeerOrb + tooltip can read
// them. Without this, all peers fall back to tier colors and have no flares.
function mergeV03IntoBuckets(admin: any, pub: any): any {
  if (!admin || !pub?.registries) return admin
  const v03ByName: Record<string, any> = {}
  for (const reg of pub.registries) {
    if (!reg?.name) continue
    v03ByName[reg.name.toLowerCase()] = {
      visual: reg.visual ?? null,
      fees_summary: reg.fees_summary ?? null,
      card_etag: reg.card_etag ?? null,
      card_signature_verified: reg.card_signature_verified ?? null,
      trust_domain: reg.trust_domain ?? null,
    }
  }
  function enrich(peer: any) {
    if (!peer?.name) return peer
    const v = v03ByName[peer.name.toLowerCase()]
    if (!v) return peer
    return {
      ...peer,
      visual: peer.visual ?? v.visual,
      fees_summary: peer.fees_summary ?? v.fees_summary,
      card_etag: peer.card_etag ?? v.card_etag,
      card_signature_verified: peer.card_signature_verified ?? v.card_signature_verified,
      trust_domain: peer.trust_domain ?? v.trust_domain,
    }
  }
  return {
    ...admin,
    frames: (admin.frames || []).map(enrich),
    direct_peers: (admin.direct_peers || []).map(enrich),
    discovered: (admin.discovered || []).map(enrich),
    cloud_operators: (admin.cloud_operators || []).map(enrich),
  }
}

async function loadTopology() {
  loading.value = true
  error.value = null
  try {
    if (canFederation.value) {
      const res = await apiClient.get('/admin/federation/topology-overview')
      // Layer in legacy /public/topology edges for the Network tab AND merge
      // v0.3 visual/fees/etag/signature fields into admin tier buckets.
      try {
        const pub = await apiClient.get('/public/topology')
        const merged = mergeV03IntoBuckets(res.data, pub.data)
        topology.value = { ...merged, registries: pub.data?.registries, edges: pub.data?.edges }
      } catch {
        topology.value = res.data
      }
    } else {
      const res = await apiClient.get('/public/topology')
      topology.value = res.data
    }
    live.markFetched()
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load topology'
    uiStore.showError?.('Federation', error.value || 'Load failed')
  } finally {
    loading.value = false
  }
}

async function runDriftScan() {
  if (driftScanning.value) return
  driftScanning.value = true
  try {
    await apiClient.post('/admin/federation/drift-scan', {})
    uiStore.showSuccess?.('Drift Scan', 'Scan complete — refreshing topology…')
    await loadTopology()
  } catch (e: any) {
    uiStore.showError?.('Drift Scan', e?.response?.data?.detail || e?.message || 'Scan failed')
  } finally {
    driftScanning.value = false
  }
}

// ── Frame invitations (f058 WS3) ───────────────────────────
async function fetchPendingInvitations() {
  if (!canFederation.value) return
  invitationsLoading.value = true
  try {
    const res = await apiClient.get('/admin/federation/frame-invitations', {
      params: { status: 'pending', limit: 50 },
    })
    pendingInvitations.value = res.data?.invitations || []
  } catch (e: any) {
    // Silent on missing endpoint (backend not yet deployed in some envs)
    pendingInvitations.value = []
  } finally {
    invitationsLoading.value = false
  }
}

function openInvitationsModal() {
  selectedInvitation.value = null
  approveNotes.value = ''
  rejectReason.value = ''
  showInvitationsModal.value = true
}

function closeInvitationsModal() {
  showInvitationsModal.value = false
  selectedInvitation.value = null
  approveNotes.value = ''
  rejectReason.value = ''
}

// FED1 (audit 2026-05-07): replaced native confirm() with themed ConfirmActionModal.
// Approving a frame federation imports a SPIRE bundle + inserts a peer_registries
// row + POSTs back to the remote frame's /finalize endpoint — irreversible except
// via revoke. The native confirm() bypassed every theme rule and stacked weirdly
// on top of the invitations dialog. ConfirmActionModal z-index was bumped to
// 10100 to stack cleanly above the fed-drawer-overlay (9999).
const showApproveConfirm = ref(false)
const pendingApproveInvitation = ref<FrameInvitation | null>(null)

function approveInvitation(inv: FrameInvitation) {
  if (invitationActionBusy.value) return
  pendingApproveInvitation.value = inv
  showApproveConfirm.value = true
}

async function executeApproveInvitation() {
  const inv = pendingApproveInvitation.value
  if (!inv) return
  invitationActionBusy.value = true
  try {
    const res = await apiClient.post(
      `/admin/federation/frame-invitations/${inv.id}/approve`,
      { notes: approveNotes.value || '' },
    )
    const completed = res.data?.completed
    const warning = res.data?.warning
    if (completed) {
      uiStore.showSuccess?.('Frame Federated', `Bilateral handshake completed with ${inv.initiator_name}.`)
    } else {
      uiStore.showError?.('Partial Approval', warning || 'Local side approved; remote /finalize pending. Use finalize-retry.')
    }
    showApproveConfirm.value = false
    pendingApproveInvitation.value = null
    await fetchPendingInvitations()
    await loadTopology()
  } catch (e: any) {
    uiStore.showError?.('Approve failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    invitationActionBusy.value = false
  }
}

async function rejectInvitation(inv: FrameInvitation) {
  if (invitationActionBusy.value) return
  const reason = rejectReason.value.trim()
  if (!reason) {
    uiStore.showError?.('Reject', 'Rejection reason is required.')
    return
  }
  invitationActionBusy.value = true
  try {
    await apiClient.post(
      `/admin/federation/frame-invitations/${inv.id}/reject`,
      { reason },
    )
    uiStore.showSuccess?.('Invitation Rejected', `Notified ${inv.initiator_contact_email}.`)
    rejectReason.value = ''
    selectedInvitation.value = null
    await fetchPendingInvitations()
  } catch (e: any) {
    uiStore.showError?.('Reject failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    invitationActionBusy.value = false
  }
}

async function revokeFrame() {
  if (!drawerPeer.value || revokingFrame.value) return
  const reason = revokeReason.value.trim()
  if (!reason) {
    uiStore.showError?.('Revoke', 'Reason is required.')
    return
  }
  revokingFrame.value = true
  try {
    await apiClient.post(
      `/admin/federation/frames/${drawerPeer.value.id}/revoke`,
      { reason },
    )
    uiStore.showSuccess?.('Frame Revoked', `${drawerPeer.value.name} removed from our SPIRE trust bundle.`)
    showRevokeFrameModal.value = false
    revokeReason.value = ''
    closeDrawer()
    await loadTopology()
  } catch (e: any) {
    uiStore.showError?.('Revoke failed', e?.response?.data?.detail || e?.message || 'Unknown error')
  } finally {
    revokingFrame.value = false
  }
}

// ── Drawer ──────────────────────────────────────────────────
function openDrawer(peer: PeerBase) {
  drawerPeer.value = peer
  drawerTab.value = 'overview'
  drawerOpen.value = true
  drawerEvents.value = []
  drawerHealthProbe.value = null
}

function closeDrawer() {
  drawerOpen.value = false
}

watch(drawerTab, async (tab) => {
  if (!drawerPeer.value) return
  if (tab === 'events') await fetchDrawerEvents()
  if (tab === 'health') await probeDrawerHealth()
})

async function fetchDrawerEvents() {
  if (!drawerPeer.value) return
  drawerEventsLoading.value = true
  drawerEvents.value = []
  try {
    const res = await apiClient.get(`/admin/federation/topology/peers/${drawerPeer.value.id}/events`, {
      params: { limit: 20 },
    })
    drawerEvents.value = res.data?.events || []
  } catch {
    drawerEvents.value = []
  } finally {
    drawerEventsLoading.value = false
  }
}

async function probeDrawerHealth() {
  if (!drawerPeer.value) return
  drawerHealthProbing.value = true
  try {
    const res = await apiClient.post(`/admin/federation/topology/peers/${drawerPeer.value.id}/probe`, {})
    drawerHealthProbe.value = res.data
  } catch (e: any) {
    drawerHealthProbe.value = { ok: false, error: e?.response?.data?.detail || e?.message }
  } finally {
    drawerHealthProbing.value = false
  }
}

// ── Add direct peer ─────────────────────────────────────────
function openAddPeer() {
  addForm.value = { name: '', base_url: '', admin_contact_email: '', description: '' }
  addOpen.value = true
}

// 2026-05-06 audit T5 — Add Peer form validation. Catches typos client-side
// instead of round-tripping to backend for a generic 400.
const URL_REGEX = /^https?:\/\/[a-z0-9][a-z0-9.-]*[a-z0-9](:\d+)?(\/[^\s]*)?$/i
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

async function submitAddPeer() {
  if (addSubmitting.value) return
  const name = addForm.value.name.trim()
  const baseUrl = addForm.value.base_url.trim()
  const email = addForm.value.admin_contact_email.trim()
  if (!name || !baseUrl || !email) {
    uiStore.showError?.('Add Peer', 'Name, base URL, and admin email are required.')
    return
  }
  // T5 — client-side regex validation
  if (!URL_REGEX.test(baseUrl)) {
    uiStore.showError?.('Add Peer', 'Base URL must be http(s)://hostname[:port][/path].')
    return
  }
  if (!EMAIL_REGEX.test(email)) {
    uiStore.showError?.('Add Peer', 'Admin email format is invalid.')
    return
  }
  // T5 — duplicate-name check against currently-known peers (best-effort; backend re-validates)
  const dupe = allPeers.value.find(p => (p.name || '').toLowerCase() === name.toLowerCase())
  if (dupe) {
    uiStore.showError?.('Add Peer', `A peer named "${dupe.name}" already exists (id ${dupe.id}, ${dupe.peer_type}). Pick a different name.`)
    return
  }
  addSubmitting.value = true
  try {
    await apiClient.post('/federation/peers/', {
      name: addForm.value.name,
      base_url: addForm.value.base_url,
      admin_contact_email: addForm.value.admin_contact_email,
      description: addForm.value.description || null,
      discovery_auth_info: {},
    })
    uiStore.showSuccess?.('Add Peer', 'Direct peer registered. Awaiting admin approval if not auto-approved.')
    addOpen.value = false
    await loadTopology()
  } catch (e: any) {
    uiStore.showError?.('Add Peer', e?.response?.data?.detail || e?.message || 'Failed')
  } finally {
    addSubmitting.value = false
  }
}

// ── Helpers ─────────────────────────────────────────────────
function tierIcon(tier: string): string {
  return ({
    frame: 'mdi:server-network',
    direct_peer: 'mdi:connection',
    discovered: 'mdi:radar',
    cloud_operator: 'mdi:cloud-upload-outline',
  } as Record<string, string>)[tier] || 'mdi:server'
}

function tierLabel(tier: string): string {
  return ({
    frame: 'Frame',
    direct_peer: 'Direct Peer',
    discovered: 'Discovered',
    cloud_operator: 'Cloud Operator',
  } as Record<string, string>)[tier] || tier
}

function statusClass(status: string | undefined | null): string {
  const s = (status || '').toUpperCase()
  if (s === 'ACTIVE') return 'fed-sb-ok'
  if (s === 'INACTIVE') return 'fed-sb-warn'
  if (s === 'PENDING_APPROVAL' || s === 'PENDING') return 'fed-sb-pending'
  if (s === 'REJECTED' || s === 'REVOKED') return 'fed-sb-bad'
  return 'fed-sb-muted'
}

function licenseClass(status: string | undefined | null): string {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'fed-sb-ok'
  if (s === 'suspended') return 'fed-sb-warn'
  if (s === 'revoked') return 'fed-sb-bad'
  return 'fed-sb-muted'
}

function timeAgo(ts: string | undefined | null): string {
  if (!ts) return '—'
  try { return dayjs(ts).fromNow() } catch { return ts }
}

function shortId(id: string | number | null | undefined, n = 8): string {
  if (id == null) return '—'
  const s = String(id)
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function summaryFromPeer(peer: PeerBase): string {
  const bits: string[] = []
  // Frames: show trust_domain + chain-reachability hint.
  // §pass55: renamed from "bundle fresh/stale/unseen" — that label was
  // sourcing peer.bfs_reachable (BFS chain visibility), NOT the SPIRE bundle
  // freshness, and collided with the new fed-card-bundle-age pill which
  // reads the actual cert NotBefore/NotAfter via bundle_freshness.
  if (peer.peer_type === 'frame') {
    if (peer.trust_domain) bits.push(peer.trust_domain)
    if (peer.bfs_reachable) bits.push('chain-reachable')
    else if (peer.last_seen_in_topology_at) bits.push('chain-stale')
    else bits.push('chain-unseen')
    return bits.join(' · ')
  }
  // §pass62.8 (2026-05-21) — `hop X` + `via Y` removed from text summary.
  // Now rendered as dedicated pills (.fed-card-hop / .fed-card-via) at the
  // tier-bucket card meta row using the tree-walk derivation (chainHopOf).
  // Including them in this text string caused duplicate display:
  //   "hop 1 · via op-london"   (raw, here)
  //   "hop 2"                    (derived, separate pill — what user sees as right)
  // Chain-federated: peer row inactive but BFS still finds it via another peer.
  // This is the legitimate topology shape — not drift, not partial teardown.
  if (peer.bfs_reachable && peer.status === 'INACTIVE' && (peer.hop_distance ?? 0) > 1) {
    bits.push('chain-federated')
  }
  if (peer.license_status) bits.push(`license ${peer.license_status}`)
  if (peer.cloud_url && peer.peer_type === 'cloud_operator') bits.push('cloud')
  return bits.join(' · ')
}

// §pass54 bundle freshness UI helpers — frame cards only.
type BundleFreshness = NonNullable<PeerBase['bundle_freshness']>

function bundleAgeClass(fr: BundleFreshness): string {
  if (fr.error) return 'fed-card-bundle-age--unknown'
  if (fr.refresh_critical) return 'fed-card-bundle-age--critical'
  if (fr.refresh_overdue) return 'fed-card-bundle-age--overdue'
  return 'fed-card-bundle-age--fresh'
}

function bundleAgeIcon(fr: BundleFreshness): string {
  if (fr.error) return 'mdi:help-circle-outline'
  if (fr.refresh_critical) return 'mdi:alert-octagon'
  if (fr.refresh_overdue) return 'mdi:clock-alert'
  return 'mdi:clock-check-outline'
}

function bundleAgeLabel(fr: BundleFreshness): string {
  if (fr.error) return `bundle freshness unknown (${fr.error.slice(0, 40)})`
  const ageH = (fr.age_seconds || 0) / 3600
  const expH = (fr.expires_in_seconds || 0) / 3600
  const ageStr = ageH < 24 ? `${ageH.toFixed(1)}h` : `${(ageH / 24).toFixed(1)}d`
  const expStr = expH < 24 ? `${expH.toFixed(1)}h` : `${(expH / 24).toFixed(1)}d`
  if (fr.refresh_critical) return `bundle CRITICAL — age ${ageStr}, expires in ${expStr}`
  if (fr.refresh_overdue) return `bundle OVERDUE — age ${ageStr}, expires in ${expStr}`
  return `bundle fresh — age ${ageStr}, expires in ${expStr}`
}

// ── Registry Card v0.3 helpers (§pass60-60.2 wired into Federation.vue 2026-05-21) ──
// Extract visual identity, signature trust, and fees from peer.visual / peer.card_* /
// peer.fees{_summary}, with sane fallbacks. Used by PeerOrb (Pass 3),
// PeerHoverPopover (Pass 2), and the Live Feed (Pass 5).

// Match the local-registry entry by stable identifier, NOT by name (memory:
// feedback_topology_local_entry_name_mismatch — name varies per REGISTRY_NAME
// env, only domain='__local__' OR hopDepth===0 is stable across deployments).
const localRegistry = computed(() => {
  return topology.value?.registries?.find(r => r.domain === '__local__' || r.hopDepth === 0) || null
})

// Tier fallback colors (mirror --fed-* CSS palette; used when peer has no
// orb_color from a v0.3 registry card yet — most peers today).
function tierFallbackColor(tier: string | undefined): string {
  switch (tier) {
    case 'frame': return '#a855f7'           // violet (--fed-frame)
    case 'direct_peer': return '#00d2d2'     // cyan (--fed-direct fallback)
    case 'discovered': return '#f59e0b'      // amber (--fed-discovered)
    case 'cloud_operator': return '#22c55e'  // green (--fed-cloud)
    case 'local': return '#e8eaed'           // text-primary
    default: return '#94a3b8'                // text-muted
  }
}

function peerOrbColor(peer: PeerBase | undefined): string {
  return peer?.visual?.orb_color || tierFallbackColor(peer?.peer_type)
}
function peerOrbGlow(peer: PeerBase | undefined): string {
  return peer?.visual?.orb_glow_color
    || peer?.visual?.orb_color
    || tierFallbackColor(peer?.peer_type)
}
function peerPulseHz(peer: PeerBase | undefined): number | null {
  const hz = peer?.visual?.orb_pulse_speed_hz
  return typeof hz === 'number' && hz > 0 ? hz : null
}
function peerSizePx(peer: PeerBase | undefined): number | null {
  const px = peer?.visual?.orb_size_px
  return typeof px === 'number' && px > 0 ? px : null
}
function peerHaloEnabled(peer: PeerBase | undefined): boolean {
  return peer?.visual?.halo_enabled !== false  // default true when undefined
}
// Memory feedback_flare_encirclement_tier_required: tier MUST be set or
// FlareEncirclement.visible computed returns false (silent no-render).
function peerFlareTier(peer: PeerBase | undefined): 'sovereign' | 'shadow_chancellor' {
  return peer?.visual?.sovereign_variant ? 'sovereign' : 'shadow_chancellor'
}
function peerFlareVariant(peer: PeerBase | undefined): string | null {
  return peer?.visual?.sovereign_variant
    || peer?.visual?.flare_encirclement_variant
    || null
}
function peerFlareOverlay(peer: PeerBase | undefined): string | null {
  return peer?.visual?.flare_encirclement_overlay || null
}
function peerFeesIntra(peer: PeerBase | undefined): number | null {
  const v = peer?.fees_summary?.intra_registry ?? peer?.fees?.intra_registry
  return typeof v === 'number' ? v : null
}
function peerFeesCross(peer: PeerBase | undefined): number | null {
  const v = peer?.fees_summary?.cross_registry ?? peer?.fees?.cross_registry
  return typeof v === 'number' ? v : null
}
type SignatureBadge = 'verified' | 'unsigned' | 'unknown'
function peerSignatureBadge(peer: PeerBase | undefined): SignatureBadge {
  if (peer?.card_signature_verified === true) return 'verified'
  if (peer?.card_signature_verified === false) return 'unsigned'
  return 'unknown'
}
function peerEtagShort(peer: PeerBase | undefined): string | null {
  const e = peer?.card_etag || peer?.lifecycle?.card_etag
  if (!e) return null
  const stripped = e.startsWith('sha256:') ? e.slice(7) : e
  return `${stripped.slice(0, 16)}…`
}
function peerBundleAgeSec(peer: PeerBase | undefined): number | null {
  return peer?.bundle_freshness?.age_seconds ?? null
}
// Human-readable age — '12s', '3m', '4h', '2d 6h'.
function humanizeAge(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return '—'
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  const rh = h % 24
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`
}
// Humanize a timestamp into 'just now' / '3s ago' / '5m ago' / '2h ago'.
function humanizeAgo(ts: number | null | undefined): string {
  if (!ts) return ''
  return humanizeAge(Math.floor((Date.now() - ts) / 1000)) + ' ago'
}

// ── Hover popover state (Pass 2) ────────────────────────────
// Floating Vue popover replaces the SVG native <title> tooltip on Network-tab
// nodes. Shows Card v0.3 visual + trust + fees + bundle age + ETag.
const hoverPeer = ref<PeerBase | null>(null)
const hoverX = ref(0)
const hoverY = ref(0)
const hoverVisible = ref(false)
let hoverShowTimer: ReturnType<typeof setTimeout> | null = null

function onNodeMouseEnter(node: GraphNode, ev: MouseEvent) {
  hoverX.value = ev.clientX
  hoverY.value = ev.clientY
  // 200ms debounce — prevents flicker on rapid mouseover across many nodes
  if (hoverShowTimer) clearTimeout(hoverShowTimer)
  hoverShowTimer = setTimeout(() => {
    hoverPeer.value = node.peer ?? buildLocalPseudoPeer(node)
    hoverVisible.value = true
  }, 180)
}
function onNodeMouseMove(ev: MouseEvent) {
  if (!hoverVisible.value) {
    // Update cursor position even before debounce fires
    hoverX.value = ev.clientX
    hoverY.value = ev.clientY
    return
  }
  hoverX.value = ev.clientX
  hoverY.value = ev.clientY
}
function onNodeMouseLeave() {
  if (hoverShowTimer) { clearTimeout(hoverShowTimer); hoverShowTimer = null }
  hoverVisible.value = false
  // keep hoverPeer for the fade-out (animation reads .visible)
}

// Build a pseudo-peer object for the local-registry node (no peer_registries row).
// Pulls visual + fees + signature from the localRegistry computed (which reads
// from topology.registries[].domain==='__local__').
function buildLocalPseudoPeer(node: GraphNode): PeerBase | null {
  if (!node.isLocal) return null
  const lr = localRegistry.value
  if (!lr) {
    // Fall back to minimal stub so the popover at least renders the name
    return {
      id: 0,
      name: node.name,
      base_url: '',
      status: 'ACTIVE',
      peer_type: 'local',
      hop_distance: 0,
      discovered_at: null,
      registered_at: null,
      approved_at: null,
      last_synced_at: null,
      operator_did: null,
      trust_domain: null,
      parent_registry_id: null,
    } as PeerBase
  }
  return {
    id: 0,
    name: lr.name,
    base_url: lr.publicUrl || '',
    status: 'ACTIVE',
    peer_type: 'local',
    hop_distance: 0,
    discovered_at: null,
    registered_at: null,
    approved_at: null,
    last_synced_at: null,
    operator_did: null,
    trust_domain: lr.trust_domain ?? null,
    parent_registry_id: null,
    visual: lr.visual ?? null,
    fees_summary: lr.fees_summary ?? null,
    card_etag: lr.card_etag ?? null,
    card_signature_verified: lr.card_signature_verified ?? undefined,
  } as PeerBase
}

// ── Lifecycle ───────────────────────────────────────────────
// §FEDCLOCK — the poll tick, the 1Hz display tick and the two countdown computeds moved to
// `useLiveRefresh` (declared near the top, beside the state it replaced). Only the invitations
// cycle is still hand-rolled here: it is a different cadence with a different gate.
let invitationsPollTimer: ReturnType<typeof setInterval> | null = null

// T4 — hydrate filter/search/tab/drawer state from URL query params.
function hydrateFromUrl() {
  const q = route.query
  const tab = (q.tab as string) || 'tiers'
  if ((TOP_TABS as readonly string[]).includes(tab)) {
    activeTopTab.value = tab as TopTab
  }
  const f = (q.filter as string) || 'all'
  if (['all', 'frame', 'direct_peer', 'discovered', 'cloud_operator'].includes(f)) {
    filter.value = f as TierKey
  }
  const qStr = (q.q as string) || ''
  if (qStr) search.value = qStr
  const s = (q.sort as string) || 'natural'
  if (['natural','name','hop','last_synced','drift'].includes(s)) sortKey.value = s as SortKey
}

// T4 — push current state to URL (replace mode, no history entry per change).
let _pushUrlPending: ReturnType<typeof setTimeout> | null = null
function pushStateToUrl() {
  if (_hydratingFromUrl) return
  if (_pushUrlPending) clearTimeout(_pushUrlPending)
  _pushUrlPending = setTimeout(() => {
    const next: Record<string, string> = {}
    if (activeTopTab.value !== 'tiers') next.tab = activeTopTab.value
    if (filter.value !== 'all') next.filter = filter.value
    if (search.value) next.q = search.value
    if (sortKey.value !== 'natural') next.sort = sortKey.value
    if (drawerOpen.value && drawerPeer.value?.id) {
      next.peer = String(drawerPeer.value.id)
      if (drawerTab.value !== 'overview') next.dt = drawerTab.value
    }
    _lastPushedQuery = JSON.stringify(next)
    router.replace({ query: next }).catch(() => {})  // ignore NavigationDuplicated
    _pushUrlPending = null
  }, 250)  // T4 — debounce 250ms so rapid search keystrokes don't spam history
}

// T4 — watchers that mirror state to URL.
watch([activeTopTab, filter, search, sortKey, drawerOpen, drawerTab], pushStateToUrl)
watch(drawerPeer, () => pushStateToUrl())

// T4 fix — also hydrate from URL when route.query changes externally
// (e.g., browser back/forward, in-app navigation with new query, or shared
// link opened with same view already mounted). Without this, only the FIRST
// mount reads the URL; subsequent ?sort=drift via in-app router is ignored.
// Guarded by `_hydratingFromUrl` so the round-trip from pushStateToUrl back
// through this watcher doesn't loop.
let _lastPushedQuery = ''
watch(() => route.query, (newQ) => {
  const serialized = JSON.stringify(newQ)
  if (serialized === _lastPushedQuery) return  // we just pushed this; skip
  _hydratingFromUrl = true
  hydrateFromUrl()
  // Allow watcher microtask to settle before re-arming.
  Promise.resolve().then(() => { _hydratingFromUrl = false })
}, { deep: true })

// §FESUITE (the leave sweep): a page left during its first reads starts no timer and adds no key listener when they land
const alive = useAlive()
onMounted(async () => {
  // T4 — hydrate from URL BEFORE loadTopology so search filter applies on first render.
  hydrateFromUrl()
  await loadTopology()
  if (!alive()) return
  // T4 — open drawer for ?peer=<id> after topology loads.
  const peerId = route.query.peer ? Number(route.query.peer) : null
  if (peerId && topology.value) {
    const match = allPeers.value.find(p => p.id === peerId)
    if (match) {
      const dt = (route.query.dt as string) || 'overview'
      if (['overview','health','lifecycle','trust','agents','events'].includes(dt)) {
        drawerTab.value = dt as DrawerTab
      }
      openDrawer(match)
    }
  }
  // Hydration complete — subsequent state changes push to URL.
  _hydratingFromUrl = false
  // §pass62.1 — backfill LiveFederationFeed with last 20 federation events.
  backfillFederationEvents()
  // Frame invitations refresh on 90s cycle (admin-only; inline gate in fetch).
  await fetchPendingInvitations()
  if (!alive()) return
  invitationsPollTimer = setInterval(fetchPendingInvitations, 90_000)
  // T2 — global Esc handler for modal/drawer dismissal.
  window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
  if (invitationsPollTimer) clearInterval(invitationsPollTimer)
  window.removeEventListener('keydown', onGlobalKeydown)
})

function drawerTabLabel(key: string): string {
  const map: Record<string, string> = {
    overview: t('federationView.drawerTabs.overview'),
    health: t('federationView.drawerTabs.health'),
    lifecycle: t('federationView.drawerTabs.lifecycle'),
    trust: t('federationView.drawerTabs.trust'),
    agents: t('federationView.drawerTabs.agents'),
    events: t('federationView.drawerTabs.events'),
  }
  return map[key] || key
}
</script>

<template>
  <div class="fed hm-module">
    <!-- Background grid + glows -->
    <div class="fed-bg">
      <div class="fed-grid"></div>
      <div class="fed-glow fed-glow-1"></div>
      <div class="fed-glow fed-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="fed-hero">
      <div class="fed-hero-inner">
        <div class="fed-chip">
          <Icon name="mdi:server-network" :size="14" />
          {{ t('federationView.hero.chip') }}
        </div>
        <h1 class="fed-h1" data-tour="fed-hero">
          {{ t('federationView.hero.h1a') }}<span class="fed-accent">{{ t('federationView.hero.h1Accent') }}</span>
          <span class="fed-h1-suffix" v-if="kpis.total > 0">· {{ kpis.total }} peers</span>
        </h1>
        <p class="fed-lead">
          {{ t('federationView.hero.lead') }}
          <!-- §LOCTRUTH class: this line named ONE frame, hardcoded, on every frame in the
               federation, which is a claim about WHOSE view this is and it was wrong everywhere
               but one node. The page already knows its own registry (it draws it at the centre
               of the graph); say that, and fall back to the generic phrasing only when the card
               has not loaded yet. -->
          <span class="fed-lead-dim">· {{ localRegistry?.name
              ? tp('federationView.viewingFromNamed', 'Viewing from {name}', { name: localRegistry.name })
              : t('federationView.viewingFromLocal') }}</span>
        </p>
      </div>
    </section>

    <!-- Frame invitations banner (admin-only, shows pending count) -->
    <!-- WS3.5: Review now navigates to /frame-management; inline modal kept for back-compat -->
    <div
      v-if="canFederation && pendingInvitations.length > 0"
      class="fed-drift-banner fed-invites-banner"
    >
      <Icon name="mdi:inbox" :size="16" />
      {{ t('federationView.invitesBanner', { count: pendingInvitations.length }) }}
      <router-link to="/frame-management" class="fed-drift-action">{{ t('federationView.openFrameManagement') }}</router-link>
      <button class="fed-drift-action" @click="openInvitationsModal">{{ t('federationView.quickReview') }}</button>
    </div>

    <!-- Drift banner — T2 a11y: role=status + aria-live=polite so screen readers announce drift count changes -->
    <div
      v-if="kpis.drift > 0 && canFederation"
      class="fed-drift-banner"
      role="status"
      aria-live="polite"
    >
      <Icon name="mdi:alert-circle" :size="16" aria-hidden="true" />
      {{ t('federationView.driftBanner', { count: kpis.drift }) }}
      <button class="fed-drift-action" @click="filter = 'direct_peer'">{{ t('federationView.inspect') }}</button>
      <button class="fed-drift-action" :disabled="driftScanning" @click="runDriftScan">
        {{ driftScanning ? t('federationView.scanning') : t('federationView.rescan') }}
      </button>
    </div>
    <div
      v-else-if="canFederation && topology"
      class="fed-drift-banner fed-drift-banner--ok"
      role="status"
      aria-live="polite"
    >
      <Icon name="mdi:check-circle" :size="14" aria-hidden="true" />
      {{ t('federationView.driftClean') }}
    </div>

    <!-- §pass54 — SPIRE federation bundle freshness banner. Surfaces the
         silent-drift failure mode that escaped detection for 4 days. -->
    <div
      v-if="hasBundleFreshnessAlert && canFederation"
      class="fed-drift-banner"
      :class="kpis.bundlesCritical > 0 ? 'fed-drift-banner--critical' : 'fed-drift-banner--overdue'"
      role="alert"
      aria-live="assertive"
    >
      <Icon :name="kpis.bundlesCritical > 0 ? 'mdi:alert-octagon' : 'mdi:clock-alert'" :size="16" aria-hidden="true" />
      <span v-if="kpis.bundlesCritical > 0">
        {{ kpis.bundlesCritical }} federated SPIRE bundle(s) CRITICAL — refresh chain broken or expiring within 24h
      </span>
      <span v-else>
        {{ kpis.bundlesOverdue }} federated SPIRE bundle(s) OVERDUE — auto-refresh has not run in &gt;120h
      </span>
      <button class="fed-drift-action" @click="filter = 'frame'">Inspect frames</button>
    </div>

    <!-- KPI row -->
    <!-- §FESUITE (the loading sweep): the figures wait for the topology's own read; a 0 says "none". -->
    <div class="fed-stats-row">
      <div class="fed-stat fed-stat--frame">
        <span class="fed-stat-label">{{ t('federationView.kpi.frames') }}</span>
        <span class="fed-stat-value">{{ topology ? kpis.frames : '—' }}</span>
      </div>
      <div class="fed-stat fed-stat--direct">
        <span class="fed-stat-label">{{ t('federationView.kpi.directPeers') }}</span>
        <span class="fed-stat-value">{{ topology ? kpis.direct : '—' }}</span>
      </div>
      <div class="fed-stat fed-stat--discovered">
        <span class="fed-stat-label">{{ t('federationView.kpi.discovered') }}</span>
        <span class="fed-stat-value">{{ topology ? kpis.discovered : '—' }}</span>
      </div>
      <div class="fed-stat fed-stat--cloud">
        <span class="fed-stat-label">{{ t('federationView.kpi.cloudOps') }}</span>
        <span class="fed-stat-value">{{ topology ? kpis.cloud : '—' }}</span>
      </div>
      <div class="fed-stat" :class="kpis.drift > 0 ? 'fed-stat--bad' : 'fed-stat--muted'">
        <span class="fed-stat-label">{{ t('federationView.kpi.drift') }}</span>
        <span class="fed-stat-value">{{ topology ? kpis.drift : '—' }}</span>
      </div>
      <div class="fed-stat fed-stat--ok" v-if="kpis.healthy > 0">
        <span class="fed-stat-label">{{ t('federationView.kpi.healthy') }}</span>
        <span class="fed-stat-value">{{ kpis.healthy }}</span>
      </div>
    </div>

    <!-- Top-level tab switch (Tiers vs Network vs Operations[admin]) -->
    <nav class="fed-tab-bar" data-tour="fed-tabs">
      <button class="fed-tab" :class="{ 'fed-tab-active': activeTopTab === 'tiers' }" @click="activeTopTab = 'tiers'">
        <Icon name="mdi:view-grid" :size="14" /> {{ t('federationView.tabs.tiers') }}
      </button>
      <button class="fed-tab" :class="{ 'fed-tab-active': activeTopTab === 'network' }" @click="activeTopTab = 'network'">
        <Icon name="mdi:source-branch" :size="14" /> {{ t('federationView.tabs.network') }}
      </button>
      <!-- 2026-05-08: Operations tab — admin-gated. Drift remediation +
           license breakdown + BFS reachability via the canonical
           topology-overview endpoint. Existing tabs untouched. -->
      <button v-if="canFederation" class="fed-tab" data-tour="fed-ops-tab" :class="{ 'fed-tab-active': activeTopTab === 'operations' }" @click="activeTopTab = 'operations'">
        <Icon name="mdi:cog" :size="14" /> {{ t('federationView.tabs.operations') }}
      </button>
      <!-- §FEDDIR (2026-09-09), his word: the federated index belongs here, "since its federation
           related". NOT admin-gated: the index is read through the registry's own public proxy and
           the same content already renders on /explore for a visitor. Gating it here would hide a
           public fact from a signed-in operator. -->
      <button class="fed-tab" data-tour="fed-dir-tab" :class="{ 'fed-tab-active': activeTopTab === 'directory' }" @click="activeTopTab = 'directory'">
        <Icon name="mdi:book-open-variant" :size="14" /> {{ t('federationView.tabs.directory') }}
      </button>
    </nav>

    <!-- ============================================ OPERATIONS VIEW (admin-only) ============================================ -->
    <FederationOperationsPanel v-if="activeTopTab === 'operations' && canFederation" />

    <!-- ============================================ DIRECTORY VIEW ============================================ -->
    <!-- own v-if sibling, like the Operations panel, so the tiers/network v-if/v-else-if chain
         below is untouched -->
    <FederationDirectoryPanel v-if="activeTopTab === 'directory'" :hop-by-name="hopByPeerName" />

    <!-- ============================================ TIERS VIEW ============================================ -->
    <div v-if="activeTopTab === 'tiers'">
      <div class="fed-toolbar">
        <div class="fed-filter-bar" data-tour="fed-filters">
          <button class="fed-fb-btn" :class="{ 'fed-fb-active': filter === 'all' }" @click="filter = 'all'">{{ t('federationView.filters.all') }}</button>
          <button class="fed-fb-btn" :class="{ 'fed-fb-active': filter === 'frame' }" @click="filter = 'frame'">
            <Icon name="mdi:server-network" :size="12" /> {{ t('federationView.filters.frames') }}
          </button>
          <button class="fed-fb-btn" :class="{ 'fed-fb-active': filter === 'direct_peer' }" @click="filter = 'direct_peer'">
            <Icon name="mdi:connection" :size="12" /> {{ t('federationView.filters.direct') }}
          </button>
          <button class="fed-fb-btn" :class="{ 'fed-fb-active': filter === 'discovered' }" @click="filter = 'discovered'">
            <Icon name="mdi:radar" :size="12" /> {{ t('federationView.filters.discovered') }}
          </button>
          <button class="fed-fb-btn" :class="{ 'fed-fb-active': filter === 'cloud_operator' }" @click="filter = 'cloud_operator'">
            <Icon name="mdi:cloud-upload-outline" :size="12" /> {{ t('federationView.filters.cloudOps') }}
          </button>
        </div>
        <div class="fed-search-wrap">
          <Icon name="mdi:magnify" :size="14" class="fed-search-icon" aria-hidden="true" />
          <input
            v-model="search"
            class="fed-search"
            placeholder="Search name, URL, DID, trust domain"
            aria-label="Search peers by name, URL, DID, or trust domain"
          />
          <button
            v-if="search"
            class="fed-search-clear"
            aria-label="Clear search query"
            @click="search = ''"
          >×</button>
        </div>
        <button
          v-if="hasActiveFilter"
          class="fed-action-btn fed-action-btn--ghost fed-clear-filters"
          aria-label="Clear all filters"
          @click="clearAllFilters"
        >
          <Icon name="mdi:close" :size="12" aria-hidden="true" />
          {{ t('federationView.clearFilters') }}
        </button>
        <!-- T8 — sort picker. Lets Commander reorder cards within each tier. -->
        <label class="fed-sort-wrap" aria-label="Sort peers within each tier">
          <span class="fed-sort-label">{{ t('federationView.sort.label') }}</span>
          <select v-model="sortKey" class="fed-sort-select">
            <option value="natural">{{ t('federationView.sort.default') }}</option>
            <option value="name">{{ t('federationView.sort.name') }}</option>
            <option value="hop">{{ t('federationView.sort.hop') }}</option>
            <option value="last_synced">{{ t('federationView.sort.lastSynced') }}</option>
            <option value="drift">{{ t('federationView.sort.driftFirst') }}</option>
          </select>
        </label>
        <button v-if="canFederation" class="fed-action-btn" @click="openAddPeer">
          <Icon name="mdi:plus" :size="14" /> {{ t('federationView.addDirectPeer') }}
        </button>
        <button
          class="fed-action-btn fed-action-btn--ghost"
          :title="lastFetchedAt ? `Last refreshed ${lastRefreshedLabel}; next auto-refresh in ${nextRefreshInSeconds}s` : 'Refresh now'"
          @click="loadTopology"
          :disabled="loading"
        >
          <Icon name="mdi:refresh" :size="14" />
          {{ loading ? t('federationView.refreshing') : t('federationView.refresh') }}
        </button>
        <div v-if="lastFetchedAt" class="fed-refresh-meta" aria-live="polite">
          <!-- T6 — live WS pulse: shows when a federation event just arrived.
               Replaces the static refresh metadata briefly to confirm push update. -->
          <span
            v-if="showLiveBadge"
            class="fed-refresh-meta-live"
            :title="`Live event: ${lastWsEventLabel}`"
          >
            <span class="fed-refresh-meta-live-dot"></span>
            LIVE · {{ lastWsEventLabel }}
          </span>
          <template v-else>
            <span class="fed-refresh-meta-label">{{ t('federationView.refreshed') }}</span>
            <span class="fed-refresh-meta-value">{{ lastRefreshedLabel }}</span>
            <span class="fed-refresh-meta-sep">·</span>
            <span class="fed-refresh-meta-label">{{ t('federationView.next') }}</span>
            <span class="fed-refresh-meta-value">{{ nextRefreshInSeconds }}s</span>
            <!-- T6 — discreet connection indicator. Green dot = WS connected
                 (push enabled); grey dot = polling-only fallback. -->
            <span
              class="fed-refresh-meta-ws"
              :class="{ 'fed-refresh-meta-ws--up': wsEvents.isConnected.value }"
              :title="wsEvents.isConnected.value
                ? `Real-time updates connected · ${wsEvents.eventCount.value} federation events received`
                : 'Real-time updates disconnected — falling back to 60s polling'"
              :aria-label="wsEvents.isConnected.value ? 'Real-time updates active' : 'Real-time updates inactive'"
            >
              <span class="fed-refresh-meta-ws-dot"></span>
              <span class="fed-refresh-meta-ws-label">{{ wsEvents.isConnected.value ? 'live' : 'polling' }}</span>
            </span>
          </template>
        </div>
      </div>

      <div v-if="loading && !topology" class="fed-center"><div class="fed-spinner"></div></div>
      <div v-else-if="error" class="fed-error">{{ error }}</div>

      <!-- T4 — explicit empty state when filters/search exclude every peer. Distinguishes from "no peers exist". -->
      <div
        v-else-if="hasActiveFilter && totalFilteredVisible === 0 && allPeers.length > 0"
        class="fed-empty fed-empty--filtered"
        role="status"
      >
        <Icon name="mdi:magnify" :size="32" aria-hidden="true" />
        <p>{{ t('federationView.noMatchFilter') }}</p>
        <button class="fed-action-btn fed-action-btn--ghost" @click="clearAllFilters">
          <Icon name="mdi:close" :size="12" aria-hidden="true" /> {{ t('federationView.clearFilters') }}
        </button>
      </div>

      <div v-else>
        <!-- Frames tier -->
        <section v-if="showFrames && filteredFrames.length" class="fed-tier fed-tier--frame">
          <header class="fed-tier-head">
            <h2 class="fed-tier-title" data-tour="fed-frames">
              <Icon name="mdi:server-network" :size="16" /> {{ t('federationView.tiers.frames') }}
              <span class="fed-tier-count">({{ filteredFrames.length }})</span>
            </h2>
            <span class="fed-tier-sub">{{ t('federationView.tiers.framesSub') }}</span>
          </header>
          <div class="fed-tier-grid">
            <article v-for="p in sortedFrames" :key="p.id" class="fed-card fed-card--frame" data-tour="fed-peer" @click="openDrawer(p)">
              <div class="fed-card-head">
                <div class="fed-card-title-wrap">
                  <span class="fed-card-tier-pill fed-card-tier-pill--frame">{{ t('federationView.pill.frame') }}</span>
                  <h3 class="fed-card-title">{{ p.name }}</h3>
                </div>
                <span class="fed-sb" :class="statusClass(p.status)">{{ p.status }}</span>
              </div>
              <p class="fed-card-url">{{ p.base_url }}</p>
              <p v-if="p.trust_domain" class="fed-card-trust">
                <Icon name="mdi:shield-lock" :size="12" />
                {{ p.trust_domain }}
              </p>
              <!-- §pass54 bundle freshness — surfaces the 4d silent-drift gap -->
              <p v-if="p.bundle_freshness" class="fed-card-bundle-age" :class="bundleAgeClass(p.bundle_freshness)">
                <Icon :name="bundleAgeIcon(p.bundle_freshness)" :size="12" />
                {{ bundleAgeLabel(p.bundle_freshness) }}
              </p>
              <div class="fed-card-meta">
                <span>{{ summaryFromPeer(p) || 'sovereign frame' }}</span>
                <!-- §pass62.7 (2026-05-21) — tree-walk hop on tier-bucket card -->
                <span class="fed-card-hop" :title="`Local → ${p.name}`">hop {{ chainHopOf(p) }}</span>
                <span v-if="p.has_drift" class="fed-drift-pill">
                  <Icon name="mdi:alert-circle" :size="11" />
                  drift
                </span>
              </div>
            </article>
          </div>
        </section>

        <!-- Direct peers tier -->
        <section v-if="showDirect && filteredDirect.length" class="fed-tier fed-tier--direct">
          <header class="fed-tier-head">
            <h2 class="fed-tier-title">
              <Icon name="mdi:connection" :size="16" /> {{ t('federationView.tiers.direct') }}
              <span class="fed-tier-count">({{ filteredDirect.length }})</span>
            </h2>
            <span class="fed-tier-sub">{{ t('federationView.tiers.directSub') }}</span>
          </header>
          <div class="fed-tier-grid">
            <article v-for="p in sortedDirect" :key="p.id" class="fed-card fed-card--direct" @click="openDrawer(p)">
              <div class="fed-card-head">
                <div class="fed-card-title-wrap">
                  <span class="fed-card-tier-pill fed-card-tier-pill--direct">{{ t('federationView.pill.direct') }}</span>
                  <h3 class="fed-card-title">{{ p.name }}</h3>
                </div>
                <span class="fed-sb" :class="statusClass(p.status)">{{ p.status }}</span>
              </div>
              <p class="fed-card-url">{{ p.base_url }}</p>
              <p v-if="p.trust_domain" class="fed-card-trust">
                <Icon name="mdi:shield-lock" :size="12" />
                {{ p.trust_domain }}
              </p>
              <!-- §pass55: bundle freshness pill also on direct_peer cards
                   when a cross-trust-domain bundle is being tracked
                   (e.g. Frame B → Registry-A bilateral). -->
              <p v-if="p.bundle_freshness" class="fed-card-bundle-age" :class="bundleAgeClass(p.bundle_freshness)">
                <Icon :name="bundleAgeIcon(p.bundle_freshness)" :size="12" />
                {{ bundleAgeLabel(p.bundle_freshness) }}
              </p>
              <div class="fed-card-meta">
                <span>{{ summaryFromPeer(p) || 'directly configured' }}</span>
                <!-- §pass62.7 — tree-walk hop -->
                <span class="fed-card-hop">hop {{ chainHopOf(p) }}</span>
                <span v-if="p.license_status" class="fed-sb fed-sb-sm" :class="licenseClass(p.license_status)">
                  license: {{ p.license_status }}
                </span>
                <span v-if="p.has_drift" class="fed-drift-pill">
                  <Icon name="mdi:alert-circle" :size="11" /> drift
                </span>
              </div>
            </article>
          </div>
        </section>

        <!-- Discovered tier -->
        <section v-if="showDiscovered && filteredDiscovered.length" class="fed-tier fed-tier--discovered">
          <header class="fed-tier-head">
            <h2 class="fed-tier-title">
              <Icon name="mdi:radar" :size="16" /> {{ t('federationView.tiers.discovered') }}
              <span class="fed-tier-count">({{ filteredDiscovered.length }})</span>
            </h2>
            <span class="fed-tier-sub">{{ t('federationView.tiers.discoveredSub') }}</span>
          </header>
          <div class="fed-tier-grid">
            <article v-for="p in sortedDiscovered" :key="p.id" class="fed-card fed-card--discovered" @click="openDrawer(p)">
              <div class="fed-card-head">
                <div class="fed-card-title-wrap">
                  <span class="fed-card-tier-pill fed-card-tier-pill--discovered">{{ t('federationView.pill.discovered') }}</span>
                  <h3 class="fed-card-title">{{ p.name }}</h3>
                </div>
                <span class="fed-sb" :class="statusClass(p.status)">{{ p.status }}</span>
              </div>
              <p class="fed-card-url">{{ p.base_url }}</p>
              <p class="fed-card-trust" v-if="p.parent_name">
                <Icon name="mdi:source-branch" :size="12" />
                via {{ p.parent_name }}
              </p>
              <div class="fed-card-meta">
                <span>{{ summaryFromPeer(p) || 'BFS-discovered' }}</span>
                <!-- §pass62.7 — tree-walk hop -->
                <span class="fed-card-hop">hop {{ chainHopOf(p) }}</span>
                <span v-if="p.discovered_at" class="fed-card-when">first seen {{ timeAgo(p.discovered_at) }}</span>
              </div>
            </article>
          </div>
        </section>

        <!-- Cloud operators tier -->
        <section v-if="showCloud && filteredCloud.length" class="fed-tier fed-tier--cloud">
          <header class="fed-tier-head">
            <h2 class="fed-tier-title">
              <Icon name="mdi:cloud-upload-outline" :size="16" /> {{ t('federationView.tiers.cloud') }}
              <span class="fed-tier-count">({{ filteredCloud.length }})</span>
            </h2>
            <span class="fed-tier-sub">{{ t('federationView.tiers.cloudSub') }}</span>
          </header>
          <div class="fed-tier-grid">
            <article v-for="p in sortedCloud" :key="p.id" class="fed-card fed-card--cloud" @click="openDrawer(p)">
              <div class="fed-card-head">
                <div class="fed-card-title-wrap">
                  <span class="fed-card-tier-pill fed-card-tier-pill--cloud">{{ t('federationView.pill.cloud') }}</span>
                  <h3 class="fed-card-title">{{ p.name }}</h3>
                </div>
                <span class="fed-sb" :class="statusClass(p.status)">{{ p.status }}</span>
              </div>
              <p class="fed-card-url">{{ p.cloud_url || p.base_url }}</p>
              <p v-if="p.operator_did" class="fed-card-trust">
                <Icon name="mdi:shield-lock" :size="12" /> {{ p.operator_did }}
              </p>
              <div class="fed-card-meta">
                <span>{{ summaryFromPeer(p) }}</span>
                <!-- §pass62.7 — tree-walk hop + via for cloud-op tier (chain-children get via parent) -->
                <span class="fed-card-hop">hop {{ chainHopOf(p) }}</span>
                <span v-if="p.parent_name" class="fed-card-via" :title="`via ${p.parent_name}`">via {{ p.parent_name }}</span>
                <span v-if="p.cloud_provisioned_at" class="fed-card-when">provisioned {{ timeAgo(p.cloud_provisioned_at) }}</span>
                <span v-if="p.has_drift" class="fed-drift-pill">
                  <Icon name="mdi:alert-circle" :size="11" /> drift
                </span>
              </div>
            </article>
          </div>
        </section>

        <!-- Empty state -->
        <div v-if="!loading && allPeers.length === 0" class="fed-empty">
          <Icon name="mdi:server-network" :size="32" />
          <p>{{ t('federationView.empty') }}</p>
          <button v-if="canFederation" class="fed-action-btn" @click="openAddPeer">{{ t('federationView.addFirst') }}</button>
        </div>
      </div>
    </div>

    <!-- ============================================ NETWORK GRAPH VIEW ============================================ -->
    <div v-else-if="activeTopTab === 'network'" class="fed-network-wrap">
      <!-- §FESUITE (V0576): the peers tab shows a failed topology read; this tab drew "Loading topology…" for good and
           "No peers discovered yet." over it -->
      <ReadFailedNotice v-if="error && !topology" :retry="loadTopology" data-testid="fed-network-failed" />
      <div v-else class="fed-network-card fed-network-card--holographic"
        :class="{ 'fed-network-card--stressed': showNetworkStress }"
        :style="{ position: 'relative', '--fed-chroma-intensity': networkStressLevel.toFixed(2) }">
        <!-- §pass-N Pass 7: Stress pill (visible when drift > 0 OR critical bundles) -->
        <div v-if="showNetworkStress" class="fed-network-stress-pill" :title="`Network stress: ${networkStressLabel}`">
          <Icon name="mdi:alert-octagon" :size="11" />
          STRESS · {{ networkStressLabel }}
        </div>
        <!-- §pass-N Pass 5: Live federation event feed sidebar (desktop only, ≥1024px).
             §pass62.1: backfill + per-view localStorage key + improved empty-state. -->
        <LiveFederationFeed
          :events="liveFeedEvents"
          :collapsed="liveFeedCollapsed"
          :last-event-iso="lastFederationEventIso"
          :ws-connected="wsEvents.isConnected.value === true"
          @toggle="toggleLiveFeed"
          @highlight="onFeedHighlight"
        />
        <header class="fed-network-head">
          <div>
            <h2 class="fed-tier-title">
              <Icon name="mdi:source-branch" :size="16" /> {{ t('federationView.tiers.topology') }}
              <span class="fed-tier-count">({{ graphNodes.length }} nodes · {{ graphEdges.length }} edges)</span>
            </h2>
            <span class="fed-tier-sub">{{ t('federationView.tiers.topologySub') }}</span>
          </div>
          <label class="fed-mesh-toggle">
            <input type="checkbox" v-model="showMeshEdges" />
            <span>{{ t('federationView.showMesh') }}</span>
            <span class="fed-mesh-hint">{{ t('federationView.meshHint') }}</span>
          </label>
        </header>
        <div class="fed-network-canvas">
          <!-- §pass-N Pass 6: mobile fallback — graph SVG doesn't work well on
               narrow viewports. Replace with sorted peer list on <1024px. -->
          <template v-if="!showNetworkGraphSvg">
            <div class="fed-mobile-peer-list">
              <p class="fed-mobile-peer-list-hint">
                <Icon name="mdi:information-outline" :size="14" />
                Graph view is desktop-only — showing peers sorted by hop distance.
              </p>
              <div v-for="peer in sortedPeersForMobile" :key="peer.id"
                class="fed-mobile-peer-row"
                tabindex="0"
                @click="openDrawer(peer)"
                @keyup.enter="openDrawer(peer)">
                <svg width="44" height="44" viewBox="0 0 44 44" overflow="visible" class="fed-mobile-peer-orb-svg">
                  <g :transform="`translate(22, 22)`">
                    <PeerOrb
                      :peer="peer"
                      :radius="14"
                      :is-local="false"
                      :tier="peer.peer_type"
                      :tier-fallback="peer.peer_type || 'unknown'"
                    />
                  </g>
                </svg>
                <div class="fed-mobile-peer-meta">
                  <strong class="fed-mobile-peer-name">{{ peer.name }}</strong>
                  <div class="fed-mobile-peer-sub">
                    <span :class="`fed-mobile-peer-tier-pill fed-mobile-peer-tier-pill--${peer.peer_type}`">{{ tierLabel(peer.peer_type) }}</span>
                    <!-- §pass62.6 — tree-walk hop, same source of truth as Network tab SVG -->
                    <span class="fed-mobile-peer-hop">hop {{ chainHopOf(peer) }}</span>
                  </div>
                </div>
                <Icon name="mdi:chevron-right" :size="14" class="fed-mobile-peer-arrow" />
              </div>
              <div v-if="sortedPeersForMobile.length === 0" class="fed-empty">
                <Icon name="mdi:server-network" :size="28" />
                <p>No peers discovered yet.</p>
              </div>
            </div>
          </template>
          <svg v-else-if="graphNodes.length" class="fed-svg" :viewBox="`0 0 ${CANVAS.w} ${CANVAS.h}`" preserveAspectRatio="xMidYMid meet">
            <!-- Ring guides (subtle). T9 — added ring 4 to accommodate chain-leaf
                 hop=4 (e.g., op-singapore via Frame-B → op-tokyo → op-seoul). -->
            <g class="fed-svg-rings">
              <circle v-for="hop in [1, 2, 3, 4]" :key="`ring-${hop}`"
                :cx="CANVAS.cx" :cy="CANVAS.cy"
                :r="RING_RADII[hop]"
                class="fed-svg-ring"
              />
              <text v-for="hop in [1, 2, 3, 4]" :key="`ring-label-${hop}`"
                :x="CANVAS.cx + RING_RADII[hop] + 8" :y="CANVAS.cy + 4"
                class="fed-svg-ring-label"
              >hop {{ hop }}</text>
            </g>

            <!-- Edges -->
            <g class="fed-svg-edges">
              <line
                v-for="edge in graphEdges" :key="edge.key"
                :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2"
                :class="[
                  'fed-svg-edge',
                  `fed-svg-edge--${edge.tier}`,
                  'fed-svg-edge--stream',
                  { 'fed-svg-edge--flashing': flashingEdges.has(edge.key) }
                ]"
                :data-edge-key="edge.key"
              />
            </g>

            <!-- Nodes -->
            <g class="fed-svg-nodes">
              <g v-for="node in graphNodes" :key="node.key"
                :transform="`translate(${node.x}, ${node.y})`"
                :class="['fed-svg-node-group', { 'fed-svg-node-group--clickable': !!node.peer || node.isLocal }]"
                :data-peer-id="node.peer?.id || (node.isLocal ? '__local__' : '')"
                :data-peer-domain="node.key"
                :data-peer-name="node.name"
                :data-tier="node.tier"
                @click="onNodeClick(node)"
                @mouseenter="onNodeMouseEnter(node, $event)"
                @mousemove="onNodeMouseMove($event)"
                @mouseleave="onNodeMouseLeave"
              >
                <!-- §pass-N Pass 3: replaces flat halo+circle+glyph with PeerOrb
                     SVG primitive (orb_color / orb_glow / pulse_hz from Registry
                     Card v0.3 + bundle freshness ring + drift dashed ring). -->
                <PeerOrb
                  :peer="node.peer || (node.isLocal ? buildLocalPseudoPeer(node) : null)"
                  :radius="node.r"
                  :is-local="!!node.isLocal"
                  :tier="node.tier"
                  :tier-fallback="node.tier || 'unknown'"
                />
                <!-- Node label (below circle) -->
                <text
                  :y="node.r + 16"
                  text-anchor="middle"
                  :class="['fed-svg-label', `fed-svg-label--${node.tier}`]"
                >{{ node.name }}</text>
                <!-- Hop badge (small) -->
                <text v-if="!node.isLocal"
                  :y="node.r + 28"
                  text-anchor="middle"
                  class="fed-svg-hop"
                >hop {{ node.hop }}</text>
                <!-- Accessible fallback (browser native — invisible since hover popover takes over) -->
                <title>{{ node.name }} · {{ tierLabel(node.tier) }}{{ node.peer ? ` · ${node.peer.base_url}` : '' }}</title>
              </g>
            </g>
          </svg>
          <div v-else class="fed-empty">
            <Icon name="mdi:source-branch" :size="28" />
            <p>{{ t('federationView.topologyLoading') }}</p>
          </div>
        </div>
        <div class="fed-network-legend">
          <span class="fed-legend-item"><span class="fed-legend-dot fed-legend-dot--local"></span>{{ t('federationView.legend.thisRegistry') }}</span>
          <span class="fed-legend-item"><span class="fed-legend-dot fed-legend-dot--frame"></span>{{ t('federationView.legend.frame') }}</span>
          <span class="fed-legend-item"><span class="fed-legend-dot fed-legend-dot--direct_peer"></span>{{ t('federationView.legend.directPeer') }}</span>
          <span class="fed-legend-item"><span class="fed-legend-dot fed-legend-dot--discovered"></span>{{ t('federationView.legend.discovered') }}</span>
          <span class="fed-legend-item"><span class="fed-legend-dot fed-legend-dot--cloud_operator"></span>{{ t('federationView.legend.cloudOp') }}</span>
          <span class="fed-legend-item fed-legend-item--right">
            <span class="fed-legend-dot fed-legend-dot--drift"></span>{{ t('federationView.legend.hasDrift') }}
          </span>
        </div>
      </div>
    </div>

    <!-- ════════════════════════ DRAWER (§pass62 — shared PeerDetailDrawer) ════════════════════════ -->
    <!-- §pass62.6 — pass peersById + localName for tree-walk hop derivation -->
    <PeerDetailDrawer
      :open="drawerOpen"
      :peer="(drawerPeer as any)"
      :peers-by-id="(peersById as any)"
      :local-name="localRegistry?.name || 'Local'"
      @close="closeDrawer"
    />

    <!-- legacy inline drawer disabled by §pass62 — kept for grep history below as v-if=false -->
    <Teleport to="body">
      <div v-if="false && drawerOpen" class="fed-drawer-overlay" @click.self="closeDrawer">
        <aside class="fed-drawer" role="dialog" aria-modal="true" aria-labelledby="fed-drawer-title">
          <header class="fed-drawer-head">
            <div>
              <div class="fed-drawer-label">
                {{ tierLabel(drawerPeer?.peer_type || '') }} · ID {{ drawerPeer?.id }}
              </div>
              <h2 class="fed-drawer-title" id="fed-drawer-title">{{ drawerPeer?.name }}</h2>
              <div class="fed-drawer-sub">{{ drawerPeer?.base_url }}</div>
            </div>
            <button class="fed-drawer-close" aria-label="Close peer detail drawer" @click="closeDrawer">
              <Icon name="mdi:close" :size="18" aria-hidden="true" />
            </button>
          </header>

          <nav class="fed-drawer-tabs" aria-label="Peer detail sections">
            <button v-for="tabKey in (['overview','health','lifecycle','trust','agents','events'] as DrawerTab[])"
              :key="tabKey" class="fed-drawer-tab" :class="{ 'fed-drawer-tab-active': drawerTab === tabKey }"
              @click="drawerTab = tabKey">
              {{ drawerTabLabel(tabKey) }}
            </button>
          </nav>

          <div v-if="!drawerPeer" class="fed-center"><div class="fed-spinner"></div></div>
          <div v-else class="fed-drawer-body">
            <!-- Overview -->
            <section v-if="drawerTab === 'overview'" class="fed-tab-pane">
              <dl class="fed-kv">
                <dt>{{ t('federationView.drawer.tier') }}</dt><dd>
                  <Icon :name="tierIcon(drawerPeer.peer_type)" :size="14" />
                  {{ tierLabel(drawerPeer.peer_type) }}
                </dd>
                <dt>{{ t('federationView.drawer.status') }}</dt><dd><span class="fed-sb" :class="statusClass(drawerPeer.status)">{{ drawerPeer.status }}</span></dd>
                <dt>{{ t('federationView.drawer.baseUrl') }}</dt><dd class="fed-mono">{{ drawerPeer.base_url }}</dd>
                <dt v-if="drawerPeer.trust_domain">{{ t('federationView.drawer.trustDomain') }}</dt>
                <dd v-if="drawerPeer.trust_domain" class="fed-mono">{{ drawerPeer.trust_domain }}</dd>
                <dt v-if="drawerPeer.operator_did">{{ t('federationView.drawer.operatorDid') }}</dt>
                <dd v-if="drawerPeer.operator_did" class="fed-mono">{{ drawerPeer.operator_did }}</dd>
                <dt v-if="drawerPeer.license_key_prefix">{{ t('federationView.drawer.licensePrefix') }}</dt>
                <dd v-if="drawerPeer.license_key_prefix" class="fed-mono">{{ drawerPeer.license_key_prefix }}</dd>
                <dt v-if="drawerPeer.federation_tier">{{ t('federationView.drawer.federationTier') }}</dt>
                <dd v-if="drawerPeer.federation_tier">{{ drawerPeer.federation_tier }}</dd>
                <dt>{{ t('federationView.drawer.hopDistance') }}</dt><dd>{{ drawerPeer.hop_distance ?? '—' }}</dd>
                <dt v-if="drawerPeer.parent_name">{{ t('federationView.drawer.parent') }}</dt>
                <dd v-if="drawerPeer.parent_name">{{ drawerPeer.parent_name }}</dd>
                <dt>{{ t('federationView.drawer.registered') }}</dt><dd>{{ timeAgo(drawerPeer.registered_at) }}</dd>
                <dt v-if="drawerPeer.approved_at">{{ t('federationView.drawer.approved') }}</dt>
                <dd v-if="drawerPeer.approved_at">{{ timeAgo(drawerPeer.approved_at) }}</dd>
                <dt v-if="drawerPeer.discovered_at">{{ t('federationView.drawer.firstDiscovered') }}</dt>
                <dd v-if="drawerPeer.discovered_at">{{ timeAgo(drawerPeer.discovered_at) }}</dd>
              </dl>
            </section>

            <!-- Health -->
            <section v-if="drawerTab === 'health'" class="fed-tab-pane">
              <dl class="fed-kv">
                <dt>{{ t('federationView.drawer.healthFailed') }}</dt><dd>{{ drawerPeer.health_check_failure_count ?? 0 }}</dd>
                <dt>{{ t('federationView.drawer.lastHealthCheck') }}</dt><dd>{{ timeAgo(drawerPeer.last_health_check_attempt_at) }}</dd>
                <dt>{{ t('federationView.drawer.lastSynced') }}</dt><dd>{{ timeAgo(drawerPeer.last_synced_at) }}</dd>
                <dt>{{ t('federationView.drawer.healthy') }}</dt>
                <dd>
                  <span class="fed-sb" :class="drawerPeer.healthy ? 'fed-sb-ok' : 'fed-sb-warn'">
                    {{ drawerPeer.healthy ? t('common.yes') : t('common.no') }}
                  </span>
                </dd>
              </dl>
              <div class="fed-health-probe">
                <button class="fed-action-btn" :disabled="drawerHealthProbing" @click="probeDrawerHealth">
                  <Icon name="mdi:heart-pulse" :size="14" />
                  {{ drawerHealthProbing ? t('federationView.drawer.probing') : t('federationView.drawer.probeConnection') }}
                </button>
                <pre v-if="drawerHealthProbe" class="fed-pre">{{ JSON.stringify(drawerHealthProbe, null, 2) }}</pre>
              </div>
            </section>

            <!-- Lifecycle (4-layer stack) -->
            <section v-if="drawerTab === 'lifecycle'" class="fed-tab-pane">
              <div v-if="drawerPeer.has_drift" class="fed-drift-pane" role="region" aria-label="Drift flags and remediation">
                <Icon name="mdi:alert-circle" :size="16" aria-hidden="true" />
                <div class="fed-drift-pane-body">
                  <div class="fed-drift-pane-title">{{ (drawerPeer.drift_flags || []).length }} drift flag(s) detected</div>
                  <!-- T7 — rich remediation hints per drift type -->
                  <div class="fed-drift-hints">
                    <article
                      v-for="flag in (drawerPeer.drift_flags || [])"
                      :key="flag"
                      class="fed-drift-hint"
                    >
                      <header class="fed-drift-hint-head">
                        <Icon name="mdi:alert-triangle" :size="13" aria-hidden="true" />
                        <span class="fed-drift-hint-label">{{ DRIFT_LABELS[flag] || flag }}</span>
                        <code class="fed-drift-hint-flag">{{ flag }}</code>
                      </header>
                      <div v-if="DRIFT_HINTS[flag]" class="fed-drift-hint-body">
                        <p class="fed-drift-hint-row">
                          <span class="fed-drift-hint-key">{{ t('federationView.drawer.driftCause') }}</span>
                          <span class="fed-drift-hint-val">{{ DRIFT_HINTS[flag].cause }}</span>
                        </p>
                        <p class="fed-drift-hint-row">
                          <span class="fed-drift-hint-key">{{ t('federationView.drawer.driftFix') }}</span>
                          <span class="fed-drift-hint-val">{{ DRIFT_HINTS[flag].remediation }}</span>
                        </p>
                        <div v-if="DRIFT_HINTS[flag].cli" class="fed-drift-hint-cli">
                          <code>{{ DRIFT_HINTS[flag].cli }}</code>
                          <button
                            class="fed-drift-hint-copy"
                            :aria-label="`Copy command: ${DRIFT_HINTS[flag].cli}`"
                            @click="copyHintCli(DRIFT_HINTS[flag].cli!)"
                          >
                            <Icon
                              :name="copiedHint === DRIFT_HINTS[flag].cli ? 'mdi:check-circle' : 'mdi:content-copy'"
                              :size="12"
                              aria-hidden="true"
                            />
                            {{ copiedHint === DRIFT_HINTS[flag].cli ? t('federationView.drawer.copied') : t('federationView.drawer.copy') }}
                          </button>
                        </div>
                        <p v-if="DRIFT_HINTS[flag].autoHeal" class="fed-drift-hint-auto">
                          <Icon name="mdi:autorenew" :size="11" aria-hidden="true" />
                          {{ DRIFT_HINTS[flag].autoHeal }}
                        </p>
                      </div>
                      <p v-else class="fed-drift-hint-row">
                        <span class="fed-drift-hint-val fed-drift-hint-unknown">{{ t('federationView.drawer.noRemediation') }}</span>
                      </p>
                    </article>
                  </div>
                </div>
              </div>
              <div class="fed-lifecycle-stack">
                <div class="fed-lc-layer">
                  <header><span class="fed-lc-tag">APPLICATION</span> <span class="fed-lc-status" v-if="drawerPeer.application_status">{{ drawerPeer.application_status }}</span></header>
                  <div class="fed-lc-body" v-if="drawerPeer.application_id">
                    <code>{{ shortId(drawerPeer.application_id, 12) }}</code>
                    <span v-if="drawerPeer.cloud_hosted">cloud-hosted</span>
                  </div>
                  <div class="fed-lc-body" v-else><em>no application record</em></div>
                </div>
                <div class="fed-lc-layer">
                  <header><span class="fed-lc-tag">LICENSE</span> <span class="fed-lc-status" v-if="drawerPeer.license_status" :class="licenseClass(drawerPeer.license_status)">{{ drawerPeer.license_status }}</span></header>
                  <div class="fed-lc-body" v-if="drawerPeer.license_id">
                    <code>{{ drawerPeer.license_key_prefix }} · {{ shortId(drawerPeer.license_id, 12) }}</code>
                    <span v-if="drawerPeer.license_suspended_reason"><Icon name="mdi:alert" /> {{ drawerPeer.license_suspended_reason }}</span>
                    <span v-if="drawerPeer.license_revoked_reason"><Icon name="mdi:close-circle" /> {{ drawerPeer.license_revoked_reason }}</span>
                  </div>
                  <div class="fed-lc-body" v-else><em>no license record</em></div>
                </div>
                <div class="fed-lc-layer">
                  <header><span class="fed-lc-tag">PEER REGISTRY</span> <span class="fed-lc-status" :class="statusClass(drawerPeer.status)">{{ drawerPeer.status }}</span></header>
                  <div class="fed-lc-body">
                    <code>peer:{{ drawerPeer.id }}</code>
                    <!-- §pass62.6 — tree-walk hop in legacy drawer (kept under v-if=false but corrected) -->
                    <span>hop {{ chainHopOf(drawerPeer) }}</span>
                    <span v-if="drawerPeer.parent_name">via {{ drawerPeer.parent_name }}</span>
                  </div>
                </div>
                <div class="fed-lc-layer" v-if="drawerPeer.cloud_hosted">
                  <header><span class="fed-lc-tag">CLOUD STACK</span> <span class="fed-lc-status fed-sb-ok" v-if="!drawerPeer.cloud_torn_down_at">live</span><span class="fed-lc-status fed-sb-bad" v-else>torn down</span></header>
                  <div class="fed-lc-body">
                    <code>{{ drawerPeer.cloud_url }}</code>
                    <span v-if="drawerPeer.cloud_provisioned_at">provisioned {{ timeAgo(drawerPeer.cloud_provisioned_at) }}</span>
                  </div>
                </div>
                <!-- f058 WS3: SPIRE bundle info + revoke for frame peers -->
                <div class="fed-lc-layer" v-if="drawerPeer.peer_type === 'frame'">
                  <header>
                    <span class="fed-lc-tag">SPIRE TRUST BUNDLE</span>
                    <span class="fed-lc-status fed-sb-ok" v-if="drawerPeer.bfs_reachable">fresh</span>
                    <span class="fed-lc-status fed-sb-bad" v-else>stale</span>
                  </header>
                  <div class="fed-lc-body">
                    <code v-if="drawerPeer.trust_domain">spiffe://{{ drawerPeer.trust_domain }}</code>
                    <span v-if="drawerPeer.last_seen_in_topology_at">last seen {{ timeAgo(drawerPeer.last_seen_in_topology_at) }}</span>
                    <span v-else>never seen in topology</span>
                  </div>
                </div>
              </div>
              <!-- Revoke action for admin on frame peers -->
              <div
                v-if="canFederation && drawerPeer.peer_type === 'frame' && drawerPeer.status === 'ACTIVE'"
                class="fed-lc-danger-zone"
              >
                <button
                  class="fed-action-btn fed-action-btn--danger"
                  @click="revokeReason = ''; showRevokeFrameModal = true"
                >
                  <Icon name="mdi:shield-account" :size="14" />
                  {{ t('federationView.drawer.revokeFederation') }}
                </button>
                <span class="fed-help-footnote">
                  {{ t('federationView.drawer.revokeHint') }}
                </span>
              </div>
            </section>

            <!-- Trust -->
            <section v-if="drawerTab === 'trust'" class="fed-tab-pane">
              <dl class="fed-kv">
                <dt>{{ t('federationView.drawer.totalInteractions') }}</dt><dd>{{ drawerPeer.total_interactions ?? 0 }}</dd>
                <dt>{{ t('federationView.drawer.disputesLost') }}</dt><dd>{{ drawerPeer.disputes_lost_with ?? 0 }}</dd>
                <dt>{{ t('federationView.drawer.bayesianDiscount') }}</dt>
                <dd>
                  <span class="fed-trust-bar">
                    <span class="fed-trust-bar-fill" :style="{ width: `${Math.round((drawerPeer.bayesian_discount ?? 1) * 100)}%` }"></span>
                  </span>
                  <span class="fed-trust-pct">{{ ((drawerPeer.bayesian_discount ?? 1) * 100).toFixed(1) }}%</span>
                </dd>
                <dt>{{ t('federationView.drawer.lastInteraction') }}</dt><dd>{{ timeAgo(drawerPeer.last_interaction_at) }}</dd>
              </dl>
              <p class="fed-tab-hint">{{ t('federationView.drawer.bayesianHint') }}</p>
            </section>

            <!-- Agents (placeholder — DEAD BLOCK under v-if=false drawer, kept for grep history; §pass62.1 corrected link target so future re-enable works) -->
            <section v-if="drawerTab === 'agents'" class="fed-tab-pane">
              <p class="fed-tab-hint">{{ t('federationView.drawer.agentsHint') }}</p>
              <a :href="`/ui#/discover?frames=${encodeURIComponent(drawerPeer.name)}`" class="fed-action-btn">
                <Icon name="mdi:radar" :size="14" /> {{ t('federationView.drawer.openAgents') }}
              </a>
            </section>

            <!-- Events -->
            <section v-if="drawerTab === 'events'" class="fed-tab-pane">
              <div v-if="drawerEventsLoading" class="fed-center"><div class="fed-spinner"></div></div>
              <div v-else-if="drawerEvents.length === 0" class="fed-empty fed-empty--inline">
                <Icon name="mdi:history" :size="20" />
                <p>{{ t('federationView.drawer.noEvents') }}</p>
              </div>
              <ul v-else class="fed-event-list">
                <li v-for="e in drawerEvents" :key="(e.id || e.event_id || (e.event_type + e.timestamp))" class="fed-event">
                  <span class="fed-event-type">{{ e.event_type }}</span>
                  <span class="fed-event-when">{{ timeAgo(e.timestamp) }}</span>
                  <span v-if="e.data?.reason" class="fed-event-detail">{{ e.data.reason }}</span>
                </li>
              </ul>
            </section>
          </div>
        </aside>
      </div>
    </Teleport>

    <!-- ════════════════════════ ADD-PEER MODAL ════════════════════════ -->
    <Teleport to="body">
      <div v-if="addOpen" class="fed-drawer-overlay" role="dialog" aria-modal="true" aria-labelledby="fed-add-peer-title" @click.self="addOpen = false">
        <div class="fed-modal">
          <header class="fed-drawer-head">
            <h2 class="fed-drawer-title" id="fed-add-peer-title">{{ t('federationView.addPeer.title') }}</h2>
            <button class="fed-drawer-close" aria-label="Close dialog" @click="addOpen = false"><Icon name="mdi:close" :size="18" aria-hidden="true" /></button>
          </header>
          <div class="fed-modal-body">
            <label class="fed-field">
              <span class="fed-field-label">{{ t('federationView.addPeer.name') }}</span>
              <input
                v-model="addForm.name"
                class="fed-input"
                type="text"
                required
                pattern="[A-Za-z0-9_-]{2,64}"
                title="Letters, digits, dashes/underscores. 2-64 chars."
                placeholder="e.g. registry-c"
              />
            </label>
            <label class="fed-field">
              <span class="fed-field-label">{{ t('federationView.addPeer.baseUrl') }}</span>
              <input
                v-model="addForm.base_url"
                class="fed-input"
                type="url"
                required
                placeholder="https://registry-c.example.com:8443"
                title="Full federation base URL incl. protocol + mTLS port (typically :8443)"
              />
            </label>
            <label class="fed-field">
              <span class="fed-field-label">{{ t('federationView.addPeer.adminEmail') }}</span>
              <input
                v-model="addForm.admin_contact_email"
                class="fed-input"
                type="email"
                required
                placeholder="admin@registry-c.example.com"
              />
            </label>
            <label class="fed-field">
              <span class="fed-field-label">{{ t('federationView.addPeer.description') }}</span>
              <input v-model="addForm.description" class="fed-input" />
            </label>
            <div class="fed-modal-actions">
              <button class="fed-action-btn fed-action-btn--ghost" @click="addOpen = false">{{ t('common.cancel') }}</button>
              <button class="fed-action-btn" @click="submitAddPeer" :disabled="addSubmitting">
                {{ addSubmitting ? t('federationView.addPeer.submitting') : t('federationView.addPeer.submit') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- f058 WS3: Pending Frame Invitations Modal -->
    <Teleport to="body">
      <div v-if="showInvitationsModal" class="fed-drawer-overlay" role="dialog" aria-modal="true" aria-label="Frame federation invitations review" @click.self="closeInvitationsModal">
        <div class="fed-modal fed-modal--wide">
          <header class="fed-drawer-head">
            <h2 class="fed-drawer-title">
              {{ t('federationView.invitations.title') }}
              <span class="fed-pill fed-pill--amber">{{ t('federationView.invitations.pending', { count: pendingInvitations.length }) }}</span>
            </h2>
            <button class="fed-drawer-close" aria-label="Close invitations dialog" @click="closeInvitationsModal">
              <Icon name="mdi:close" :size="18" aria-hidden="true" />
            </button>
          </header>
          <div class="fed-modal-body">
            <div v-if="pendingInvitations.length === 0" class="fed-empty">
              <Icon name="mdi:inbox" :size="28" />
              <p>{{ t('federationView.invitations.noInvitations') }}</p>
            </div>
            <div v-else class="fed-invite-list">
              <div
                v-for="inv in pendingInvitations"
                :key="inv.id"
                class="fed-invite-row"
                :class="{ 'fed-invite-row--active': selectedInvitation?.id === inv.id }"
                @click="selectedInvitation = inv; approveNotes = ''; rejectReason = ''"
              >
                <div class="fed-invite-head">
                  <strong>{{ inv.initiator_name }}</strong>
                  <span class="fed-pill fed-pill--frame">frame</span>
                  <span class="fed-invite-when">{{ timeAgo(inv.created_at) }}</span>
                </div>
                <div class="fed-invite-meta">
                  <span><Icon name="mdi:shield-lock" :size="12" /> {{ inv.initiator_trust_domain }}</span>
                  <span><Icon name="mdi:connection" :size="12" /> {{ inv.initiator_federation_endpoint_url }}</span>
                  <span><Icon name="mdi:information" :size="12" /> {{ inv.initiator_contact_email }}</span>
                  <span v-if="inv.initiator_ip">IP {{ inv.initiator_ip }}</span>
                </div>
                <p v-if="inv.initiator_description" class="fed-invite-desc">
                  {{ inv.initiator_description }}
                </p>
                <div class="fed-invite-bundle">
                  <span class="fed-field-label">{{ t('federationView.invitations.bundleEndpoint') }}</span>
                  <code>{{ inv.initiator_bundle_endpoint_url }}</code>
                </div>
              </div>
            </div>

            <!-- Action panel for selected invitation -->
            <div v-if="selectedInvitation" class="fed-invite-actions">
              <label class="fed-field">
                <span class="fed-field-label">{{ t('federationView.invitations.approvalNotes') }}</span>
                <input
                  v-model="approveNotes"
                  class="fed-input"
                  placeholder="e.g. Verified by phone call 2026-04-21"
                />
              </label>
              <button
                class="fed-action-btn fed-action-btn--primary"
                :disabled="invitationActionBusy"
                @click="approveInvitation(selectedInvitation)"
              >
                <Icon name="mdi:check-circle" :size="14" />
                {{ invitationActionBusy ? t('federationView.invitations.approving') : t('federationView.invitations.approveFederate') }}
              </button>
              <label class="fed-field fed-field--reject">
                <span class="fed-field-label">{{ t('federationView.invitations.rejectReason') }}</span>
                <input
                  v-model="rejectReason"
                  class="fed-input"
                  placeholder="e.g. Trust domain format invalid; please reapply"
                />
              </label>
              <button
                class="fed-action-btn fed-action-btn--danger"
                :disabled="invitationActionBusy || !rejectReason.trim()"
                @click="rejectInvitation(selectedInvitation)"
              >
                <Icon name="mdi:close" :size="14" />
                {{ invitationActionBusy ? t('federationView.invitations.rejecting') : t('federationView.invitations.reject') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- f058 WS3: How Frame Federation Works (help modal) -->
    <Teleport to="body">
      <div v-if="showInviteHelp" class="fed-drawer-overlay" role="dialog" aria-modal="true" aria-label="How frame federation works" @click.self="showInviteHelp = false">
        <div class="fed-modal fed-modal--wide">
          <header class="fed-drawer-head">
            <h2 class="fed-drawer-title">{{ t('federationView.help.title') }}</h2>
            <button class="fed-drawer-close" aria-label="Close help" @click="showInviteHelp = false">
              <Icon name="mdi:close" :size="18" aria-hidden="true" />
            </button>
          </header>
          <div class="fed-modal-body fed-help-body">
            <p>
              <strong>Sovereign frames</strong> federate with us through a bilateral SPIRE trust bundle exchange. Trust
              is granted by installing each other's bundle; approving an invitation also issues the joining frame a
              federation licence. Each frame stays sovereign over its own economy, governance and identity.
            </p>
            <h3>{{ t('federationView.help.inviteFrame') }}</h3>
            <p>They POST to our public endpoint with their frame details and a fresh nonce:</p>
            <pre class="fed-code"><code>POST {{ consoleOrigin }}/api/v1/federation/frame-invitations
Content-Type: application/json

{
  "trust_domain": "frame.example.org",
  "bundle_endpoint_url": "https://frame.example.org:8444/",
  "federation_endpoint_url": "https://frame.example.org:8443",
  "event_store_url": "https://frame.example.org:8445",
  "name": "Example Frame",
  "contact_email": "admin@example.org",
  "description": "Research network, 50 agents.",
  "initiator_nonce": "<32 hex chars, stored locally>"
}</code></pre>
            <h3>{{ t('federationView.help.whenApprove') }}</h3>
            <ol>
              <li>We fetch their SPIRE bundle and import it into our trust store</li>
              <li>We create a <code>peer_registries</code> row (peer_type=frame)</li>
              <li>We issue their federation licence and POST back to their <code>/finalize</code> endpoint with OUR bundle, their nonce and the licence</li>
              <li>They verify the nonce, import our bundle (a frame that trusted it before inviting skips this), keep the licence for their admin, and complete the handshake</li>
            </ol>
            <h3>{{ t('federationView.help.securityNotes') }}</h3>
            <ul>
              <li>Public endpoint is rate-limited (5/hour per IP)</li>
              <li>Bundle endpoint is probed before accepting (blocks typos/spam)</li>
              <li>Nonce is single-use — replays are rejected</li>
              <li>Revocation is irreversible (re-federate via new invitation)</li>
            </ul>
            <p class="fed-help-footnote">
              To ask another frame instead, this frame first trusts that frame's bundle and then calls
              <code>POST /api/v1/admin/federation/frame-invitations/outbound</code>; a frame stood up from the frame kit
              does both with <code>frame-federate.py</code> (its <code>PUBLIC_DOCS/FRAME_FEDERATION.md</code> lists every call).
            </p>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- f058 WS3: Revoke Frame Confirmation Modal -->
    <Teleport to="body">
      <div v-if="showRevokeFrameModal" class="fed-drawer-overlay" role="alertdialog" aria-modal="true" aria-label="Revoke frame federation — confirm" @click.self="showRevokeFrameModal = false">
        <div class="fed-modal">
          <header class="fed-drawer-head">
            <h2 class="fed-drawer-title">{{ t('federationView.revoke.title') }}</h2>
            <button class="fed-drawer-close" aria-label="Close revoke confirmation" @click="showRevokeFrameModal = false">
              <Icon name="mdi:close" :size="18" aria-hidden="true" />
            </button>
          </header>
          <div class="fed-modal-body">
            <div class="fed-danger-banner">
              <Icon name="mdi:alert-triangle" :size="16" />
              <strong>{{ t('federationView.revoke.warning') }}</strong>
              <br />{{ t('federationView.revoke.coordinate') }}
            </div>
            <p v-if="drawerPeer">
              Revoking: <strong>{{ drawerPeer.name }}</strong> (trust domain
              <code>{{ drawerPeer.trust_domain }}</code>)
            </p>
            <label class="fed-field">
              <span class="fed-field-label">{{ t('federationView.revoke.reason') }}</span>
              <input
                v-model="revokeReason"
                class="fed-input"
                placeholder="e.g. Operator confirmed decommissioning 2026-04-21"
              />
            </label>
            <div class="fed-modal-actions">
              <button class="fed-action-btn fed-action-btn--ghost" @click="showRevokeFrameModal = false">
                {{ t('common.cancel') }}
              </button>
              <button
                class="fed-action-btn fed-action-btn--danger"
                :disabled="revokingFrame || !revokeReason.trim()"
                @click="revokeFrame"
              >
                {{ revokingFrame ? t('federationView.revoke.revoking') : t('federationView.revoke.revoke') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- FED1 (audit 2026-05-07): themed approve-frame-federation confirm.
         Stacks above fed-drawer-overlay via ca-overlay z-index 10100. -->
    <ConfirmActionModal
      :show="showApproveConfirm"
      title="// APPROVE FRAME FEDERATION"
      :message="pendingApproveInvitation
        ? `Approve frame federation with <strong>${pendingApproveInvitation.initiator_name}</strong> (trust domain <code>${pendingApproveInvitation.initiator_trust_domain}</code>)?<br><br>This will:<br>&nbsp;&nbsp;• Import their SPIRE bundle into our trust store<br>&nbsp;&nbsp;• Insert a <code>peer_registries</code> row<br>&nbsp;&nbsp;• POST back to their <code>/finalize</code> endpoint with our bundle`
        : ''"
      tone="warn"
      warning="Irreversible except via revoke. Make sure you've verified the initiator out-of-band."
      warning-title="⚠ Bilateral handshake"
      confirm-text="Approve + Federate"
      busy-text="Federating…"
      :busy="invitationActionBusy"
      @close="showApproveConfirm = false; pendingApproveInvitation = null"
      @confirm="executeApproveInvitation"
    />

    <!-- §pass-N (2026-05-21) — Network-tab hover popover (Teleport to body inside component) -->
    <PeerHoverPopover
      :peer="hoverPeer"
      :px="hoverX"
      :py="hoverY"
      :visible="hoverVisible"
      :peers-by-id="(peersById as any)"
      :local-name="localRegistry?.name || 'Local'"
    />
  </div>
</template>

<style scoped>
/* ── Tier color tokens (T3 — alias to project theme tokens with fallbacks) ──
 * Tier colors are tier-semantic (frame=violet, direct=accent, etc.) — kept
 * locally. The "direct" tier maps to the theme accent so it auto-shifts when
 * the user toggles between neural (cyan --nc-primary) and sovereign (red, which
 * aliases --nc-primary). Other tiers stay tier-stable.
 */
.fed {
  --fed-frame: #a855f7;                                 /* violet — sovereignty */
  --fed-direct: var(--nc-primary, #00d2d2);             /* theme accent */
  --fed-direct-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --fed-discovered: var(--nc-warning, #f59e0b);         /* amber */
  --fed-cloud: #22c55e;                                 /* green — kept stable for cloud-op tier */
  --fed-bad: var(--nc-danger, #ef4444);
  --fed-warn: var(--nc-warning, #fb923c);
  --fed-muted: var(--nc-text-muted, #94a3b8);
  --fed-ok: var(--nc-success-bright, #4ade80);
  position: relative;
  padding: 24px;
  color: var(--nc-text-primary, #e2e8f0);
  min-height: 100vh;
}

/* ── Background grid + glows ───────────────────────────── */
.fed-bg { position: absolute; inset: 0; pointer-events: none; overflow: hidden; }
.fed-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--fed-direct-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--fed-direct-rgb), 0.03) 1px, transparent 1px);
  background-size: 40px 40px;
}
.fed-glow { position: absolute; width: 600px; height: 600px; border-radius: 50%; filter: blur(120px); opacity: 0.15; }
.fed-glow-1 { top: -100px; right: -200px; background: radial-gradient(circle, var(--fed-frame) 0%, transparent 70%); }
.fed-glow-2 { bottom: -200px; left: -200px; background: radial-gradient(circle, var(--fed-direct) 0%, transparent 70%); }

/* ── Hero ──────────────────────────────────────────────── */
.fed-hero { position: relative; z-index: 1; margin-bottom: 18px; }
.fed-chip {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--fed-direct);
  padding: 4px 10px; border: 1px solid rgba(var(--fed-direct-rgb), 0.3);
  border-radius: 4px; margin-bottom: 10px;
}
.fed-h1 { font-size: 28px; font-weight: 700; margin: 0 0 4px 0; letter-spacing: -0.02em; color: #f1f5f9; }
.fed-accent { color: var(--fed-direct); }
.fed-h1-suffix { font-size: 16px; color: var(--fed-muted); font-weight: 500; margin-left: 8px; }
.fed-lead { color: #94a3b8; font-size: 13px; margin: 0; }
.fed-lead-dim { color: #64748b; }

/* ── Drift banner ──────────────────────────────────────── */
.fed-drift-banner {
  position: relative; z-index: 1;
  display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; margin-bottom: 16px;
  background: rgba(245, 158, 11, 0.1);
  border: 1px solid rgba(245, 158, 11, 0.3);
  border-radius: 6px; color: var(--fed-discovered);
  font-size: 13px;
}
.fed-drift-banner--ok {
  background: rgba(34, 197, 94, 0.08);
  border-color: rgba(34, 197, 94, 0.25);
  color: var(--fed-ok);
}
/* §pass54 — bundle freshness banner variants */
.fed-drift-banner--overdue {
  background: rgba(250, 204, 21, 0.10);
  border-color: rgba(250, 204, 21, 0.40);
  color: #facc15;
}
.fed-drift-banner--critical {
  background: rgba(248, 113, 113, 0.12);
  border-color: rgba(248, 113, 113, 0.50);
  color: #f87171;
  animation: bundlePulseRed 1.4s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) { .fed-drift-banner--critical { animation: none; } }
.fed-drift-action {
  margin-left: auto;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: var(--fed-discovered);
  padding: 4px 10px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  cursor: pointer;
}
.fed-drift-action + .fed-drift-action { margin-left: 6px; }
.fed-drift-action:hover:not(:disabled) { background: rgba(245, 158, 11, 0.2); }
.fed-drift-action:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── KPI Stats row ─────────────────────────────────────── */
.fed-stats-row {
  position: relative; z-index: 1;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 10px; margin-bottom: 18px;
}
.fed-stat {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-top: 2px solid rgba(148, 163, 184, 0.3);
  border-radius: 8px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 4px;
}
.fed-stat--frame      { border-top-color: var(--fed-frame); }
.fed-stat--direct     { border-top-color: var(--fed-direct); }
.fed-stat--discovered { border-top-color: var(--fed-discovered); }
.fed-stat--cloud      { border-top-color: var(--fed-cloud); }
.fed-stat--ok         { border-top-color: var(--fed-ok); }
.fed-stat--bad        { border-top-color: var(--fed-bad); }
.fed-stat--muted      { border-top-color: rgba(148, 163, 184, 0.3); }
.fed-stat-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: #64748b; }
.fed-stat-value { font-family: 'IBM Plex Mono', monospace; font-size: 22px; font-weight: 700; color: #e2e8f0; }

/* ── Top tab bar (Tiers/Network) ───────────────────────── */
.fed-tab-bar {
  position: relative; z-index: 1;
  display: flex; gap: 4px; margin-bottom: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.fed-tab {
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--fed-muted);
  padding: 8px 12px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 12px;
  cursor: pointer;
  display: inline-flex; align-items: center; gap: 6px;
  transition: all 120ms;
}
.fed-tab:hover { color: #e2e8f0; }
.fed-tab-active { color: var(--fed-direct); border-bottom-color: var(--fed-direct); }

/* ── Toolbar ──────────────────────────────────────────── */
.fed-toolbar {
  position: relative; z-index: 1;
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  margin-bottom: 16px;
}
.fed-filter-bar { display: flex; gap: 4px; flex-wrap: wrap; }
.fed-fb-btn {
  background: rgba(15, 23, 42, 0.6); color: #94a3b8;
  border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  padding: 6px 10px; cursor: pointer; transition: all 120ms;
  display: inline-flex; align-items: center; gap: 4px;
}
.fed-fb-btn:hover { border-color: rgba(var(--fed-direct-rgb), 0.4); color: #e2e8f0; }
.fed-fb-active {
  background: rgba(var(--fed-direct-rgb), 0.15); border-color: var(--fed-direct); color: var(--fed-direct);
}
.fed-search-wrap { position: relative; flex: 1; min-width: 240px; max-width: 360px; }
.fed-search {
  width: 100%; padding: 6px 28px 6px 28px;
  background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; color: #e2e8f0; font-size: 12px;
  font-family: 'IBM Plex Mono', monospace;
}
.fed-search:focus { outline: none; border-color: var(--fed-direct); }
.fed-search-icon {
  position: absolute; left: 8px; top: 50%; transform: translateY(-50%);
  color: var(--fed-muted);
}
.fed-search-clear {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  background: none; border: none; color: var(--fed-muted); cursor: pointer; font-size: 16px;
}
.fed-action-btn {
  background: rgba(var(--fed-direct-rgb), 0.1);
  border: 1px solid rgba(var(--fed-direct-rgb), 0.3);
  color: var(--fed-direct);
  padding: 6px 12px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  cursor: pointer; transition: all 120ms;
  display: inline-flex; align-items: center; gap: 6px;
  text-decoration: none;
}
.fed-action-btn:hover:not(:disabled) { background: rgba(var(--fed-direct-rgb), 0.18); }
.fed-action-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.fed-action-btn--ghost { background: transparent; color: var(--fed-muted); border-color: rgba(255, 255, 255, 0.1); }
.fed-action-btn--ghost:hover:not(:disabled) { color: #e2e8f0; border-color: rgba(255, 255, 255, 0.2); background: rgba(255, 255, 255, 0.05); }

/* T1 — last-refreshed indicator: subtle metadata next to the refresh button. */
.fed-refresh-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--fed-muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}
.fed-refresh-meta-label { opacity: 0.7; }
.fed-refresh-meta-value { color: rgba(226, 232, 240, 0.85); font-weight: 500; }
.fed-refresh-meta-sep { opacity: 0.45; padding: 0 2px; }

/* T6 — WS connection indicator + live event badge */
.fed-refresh-meta-ws {
  display: inline-flex; align-items: center; gap: 4px;
  margin-left: 6px; padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--fed-muted);
}
.fed-refresh-meta-ws-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--fed-muted);
}
.fed-refresh-meta-ws--up {
  border-color: rgba(var(--fed-direct-rgb), 0.3);
  color: var(--fed-direct);
}
.fed-refresh-meta-ws--up .fed-refresh-meta-ws-dot {
  background: var(--fed-ok);
  box-shadow: 0 0 4px var(--fed-ok);
  animation: fed-ws-pulse 2.4s ease-in-out infinite;
}
@keyframes fed-ws-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.45; }
}
.fed-refresh-meta-live {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 8px;
  border-radius: 3px;
  background: rgba(var(--fed-direct-rgb), 0.14);
  border: 1px solid rgba(var(--fed-direct-rgb), 0.4);
  color: var(--fed-direct);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  animation: fed-live-flash 4s ease-out;
}
.fed-refresh-meta-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--fed-direct);
  box-shadow: 0 0 6px var(--fed-direct);
  animation: fed-ws-pulse 0.8s ease-in-out infinite;
}
@keyframes fed-live-flash {
  0%   { background: rgba(var(--fed-direct-rgb), 0.35); }
  100% { background: rgba(var(--fed-direct-rgb), 0.14); }
}

/* ── Tier sections ────────────────────────────────────── */
.fed-tier { position: relative; z-index: 1; margin-bottom: 24px; }
.fed-tier-head { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; margin-bottom: 10px; }
.fed-tier-title {
  font-family: 'IBM Plex Mono', monospace; font-size: 13px;
  letter-spacing: 0.1em; text-transform: uppercase;
  color: #e2e8f0; margin: 0;
  display: inline-flex; align-items: center; gap: 8px;
}
.fed-tier-count { color: var(--fed-muted); font-weight: 400; font-size: 12px; }
.fed-tier-sub { color: #64748b; font-size: 11px; }

.fed-tier--frame .fed-tier-title { color: var(--fed-frame); }
.fed-tier--direct .fed-tier-title { color: var(--fed-direct); }
.fed-tier--discovered .fed-tier-title { color: var(--fed-discovered); }
.fed-tier--cloud .fed-tier-title { color: var(--fed-cloud); }

.fed-tier-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 10px; }

/* ── Cards ──────────────────────────────────────────────── */
.fed-card {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-left: 3px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px; padding: 12px 14px;
  cursor: pointer; transition: all 140ms;
}
.fed-card:hover { background: rgba(15, 23, 42, 0.8); transform: translateY(-1px); }
.fed-card--frame      { border-left-color: var(--fed-frame); }
.fed-card--direct     { border-left-color: var(--fed-direct); }
.fed-card--discovered { border-left-color: var(--fed-discovered); }
.fed-card--cloud      { border-left-color: var(--fed-cloud); }

.fed-card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 6px; }
.fed-card-title-wrap { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fed-card-tier-pill {
  font-family: 'IBM Plex Mono', monospace; font-size: 9px;
  letter-spacing: 0.08em; text-transform: uppercase;
  padding: 2px 6px; border-radius: 3px;
}
.fed-card-tier-pill--frame      { background: rgba(168, 85, 247, 0.15); color: var(--fed-frame); }
.fed-card-tier-pill--direct     { background: rgba(var(--fed-direct-rgb), 0.15); color: var(--fed-direct); }
.fed-card-tier-pill--discovered { background: rgba(245, 158, 11, 0.15); color: var(--fed-discovered); }
.fed-card-tier-pill--cloud      { background: rgba(34, 197, 94, 0.15); color: var(--fed-cloud); }
.fed-card-title { margin: 0; font-size: 14px; font-weight: 600; color: #f1f5f9; }
.fed-card-url { margin: 0 0 4px 0; color: #94a3b8; font-family: 'IBM Plex Mono', monospace; font-size: 11px; word-break: break-all; }
.fed-card-trust { margin: 0 0 4px 0; color: var(--fed-muted); font-family: 'IBM Plex Mono', monospace; font-size: 10px; display: inline-flex; align-items: center; gap: 4px; }
/* §pass54: bundle freshness pill on Frame cards */
.fed-card-bundle-age { margin: 0 0 6px 0; font-family: 'IBM Plex Mono', monospace; font-size: 10px; display: inline-flex; align-items: center; gap: 4px; padding: 2px 6px; border-radius: 4px; border: 1px solid transparent; }
.fed-card-bundle-age--fresh { color: #4ade80; border-color: rgba(74, 222, 128, 0.25); background: rgba(74, 222, 128, 0.06); }
.fed-card-bundle-age--overdue { color: #facc15; border-color: rgba(250, 204, 21, 0.35); background: rgba(250, 204, 21, 0.08); animation: bundlePulseAmber 2.4s ease-in-out infinite; }
.fed-card-bundle-age--critical { color: #f87171; border-color: rgba(248, 113, 113, 0.45); background: rgba(248, 113, 113, 0.10); animation: bundlePulseRed 1.4s ease-in-out infinite; font-weight: 600; }
.fed-card-bundle-age--unknown { color: #94a3b8; border-color: rgba(148, 163, 184, 0.25); background: rgba(148, 163, 184, 0.06); }
@keyframes bundlePulseAmber { 0%,100% { box-shadow: 0 0 0 0 rgba(250, 204, 21, 0.0); } 50% { box-shadow: 0 0 0 3px rgba(250, 204, 21, 0.15); } }
@keyframes bundlePulseRed { 0%,100% { box-shadow: 0 0 0 0 rgba(248, 113, 113, 0.0); } 50% { box-shadow: 0 0 0 4px rgba(248, 113, 113, 0.20); } }
@media (prefers-reduced-motion: reduce) { .fed-card-bundle-age--overdue, .fed-card-bundle-age--critical { animation: none; } }
.fed-card-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 11px; color: var(--fed-muted); margin-top: 6px; }
.fed-card-when { color: #64748b; font-family: 'IBM Plex Mono', monospace; font-size: 10px; }
/* §pass62.7 (2026-05-21) — tree-walk hop pill on tier-bucket cards.
   Matches the Federation Network tab SVG node labels' source of truth. */
.fed-card-hop {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--fed-muted);
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
}
.fed-card-via {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: rgba(0, 229, 229, 0.78);
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(0, 229, 229, 0.18);
  background: rgba(0, 229, 229, 0.05);
  cursor: help;
}

/* Status badges */
.fed-sb {
  display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;
}
.fed-sb-sm { padding: 1px 6px; font-size: 9px; }
.fed-sb-ok { background: rgba(34, 197, 94, 0.15); color: var(--fed-ok); border: 1px solid rgba(34, 197, 94, 0.3); }
.fed-sb-warn { background: rgba(245, 158, 11, 0.15); color: var(--fed-discovered); border: 1px solid rgba(245, 158, 11, 0.3); }
.fed-sb-bad { background: rgba(239, 68, 68, 0.15); color: var(--fed-bad); border: 1px solid rgba(239, 68, 68, 0.3); }
.fed-sb-pending { background: rgba(96, 165, 250, 0.15); color: #60a5fa; border: 1px solid rgba(96, 165, 250, 0.3); }
.fed-sb-muted { background: rgba(148, 163, 184, 0.15); color: var(--fed-muted); border: 1px solid rgba(148, 163, 184, 0.3); }

.fed-drift-pill {
  display: inline-flex; align-items: center; gap: 3px;
  background: rgba(239, 68, 68, 0.15); color: var(--fed-bad);
  border: 1px solid rgba(239, 68, 68, 0.4);
  padding: 1px 6px; border-radius: 3px;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em;
}

/* ── Empty / spinner / error ──────────────────────────── */
.fed-empty { padding: 40px; text-align: center; color: var(--fed-muted); display: flex; flex-direction: column; align-items: center; gap: 10px; }
.fed-empty--inline { padding: 20px; }
.fed-empty--filtered { padding: 60px 24px; }
.fed-empty--filtered p { margin: 0; font-size: 13px; }
/* T4 — clear-all-filters chip slots into the filter bar */
.fed-clear-filters { font-size: 11px; padding: 4px 10px; gap: 4px; }

/* T8 — sort picker */
.fed-sort-wrap {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 11px; color: var(--fed-muted);
}
.fed-sort-label { font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.7; }
.fed-sort-select {
  background: var(--nc-elevated, rgba(255, 255, 255, 0.04));
  border: 1px solid var(--nc-border, rgba(255, 255, 255, 0.1));
  color: var(--nc-text-primary, #e2e8f0);
  border-radius: 4px;
  padding: 4px 8px;
  font-size: 12px;
  cursor: pointer;
}
.fed-sort-select:focus { outline: none; border-color: var(--fed-direct); }
.fed-center { display: flex; justify-content: center; align-items: center; padding: 60px; }
.fed-spinner { width: 28px; height: 28px; border: 3px solid rgba(var(--fed-direct-rgb), 0.2); border-top-color: var(--fed-direct); border-radius: 50%; animation: fed-spin 1s linear infinite; }
@keyframes fed-spin { to { transform: rotate(360deg); } }
.fed-error { padding: 14px; background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; color: #fca5a5; }

/* ── Network graph (SVG) ───────────────────────────────── */
.fed-network-wrap { position: relative; z-index: 1; }
.fed-network-card {
  background: rgba(15, 23, 42, 0.5); border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 8px; padding: 16px; overflow: hidden;
}
.fed-network-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
.fed-mesh-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  color: var(--fed-muted); cursor: pointer;
  user-select: none;
}
.fed-mesh-toggle input[type="checkbox"] { accent-color: var(--fed-direct); }
.fed-mesh-hint { color: #64748b; font-size: 10px; }
.fed-network-canvas {
  background:
    radial-gradient(circle at center, rgba(var(--fed-direct-rgb), 0.04), transparent 60%),
    rgba(0, 0, 0, 0.25);
  border-radius: 6px; padding: 12px; min-height: 520px;
  display: flex; align-items: center; justify-content: center;
}
.fed-svg { width: 100%; max-width: 100%; height: 100%; min-height: 520px; }

/* Rings (hop guides) */
.fed-svg-ring {
  fill: none;
  stroke: rgba(255, 255, 255, 0.06);
  stroke-width: 1;
  stroke-dasharray: 2 4;
}
.fed-svg-ring-label {
  fill: rgba(148, 163, 184, 0.5);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

/* Edges (tier-colored) */
.fed-svg-edge {
  stroke-width: 1.2;
  opacity: 0.55;
  transition: opacity 200ms;
}
/* §pass-N Pass 6: mobile peer list (replaces SVG graph on <1024px) */
.fed-mobile-peer-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 4px;
}
.fed-mobile-peer-list-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--nc-text-muted, #94a3b8);
  font-size: 0.72rem;
  text-align: center;
  justify-content: center;
  margin: 0 0 8px;
  padding: 8px;
  border-radius: 4px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.04);
  border: 1px dashed rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
}
.fed-mobile-peer-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--nc-surface, #131825);
  border: 1px solid var(--nc-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: 6px;
  cursor: pointer;
  transition: background 200ms cubic-bezier(0.4, 0, 0.2, 1), border-color 200ms;
}
.fed-mobile-peer-row:hover,
.fed-mobile-peer-row:focus {
  background: var(--nc-elevated, #181f2e);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  outline: none;
}
.fed-mobile-peer-orb-svg { flex-shrink: 0; }
.fed-mobile-peer-meta { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fed-mobile-peer-name {
  font-size: 0.86rem;
  color: var(--nc-text-primary, #e8eaed);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fed-mobile-peer-sub { display: flex; gap: 8px; align-items: center; }
.fed-mobile-peer-tier-pill {
  display: inline-flex;
  align-items: center;
  font-size: 0.6rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.fed-mobile-peer-tier-pill--frame { color: var(--fed-frame, #a855f7); border-color: rgba(168, 85, 247, 0.35); }
.fed-mobile-peer-tier-pill--direct_peer { color: var(--fed-direct, var(--nc-primary, #00d2d2)); border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35); }
.fed-mobile-peer-tier-pill--discovered { color: var(--fed-discovered, #f59e0b); border-color: rgba(245, 158, 11, 0.35); }
.fed-mobile-peer-tier-pill--cloud_operator { color: var(--fed-cloud, #22c55e); border-color: rgba(34, 197, 94, 0.35); }
.fed-mobile-peer-hop {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.62rem;
  color: var(--nc-text-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}
.fed-mobile-peer-arrow { color: var(--nc-text-muted, #94a3b8); flex-shrink: 0; }

.fed-svg-edge--frame { stroke: var(--fed-frame); }
.fed-svg-edge--direct_peer { stroke: var(--fed-direct); }
.fed-svg-edge--discovered { stroke: var(--fed-discovered); opacity: 0.45; }
.fed-svg-edge--cloud_operator { stroke: var(--fed-cloud); }
.fed-svg-edge--local { stroke: var(--fed-direct); }
.fed-svg-edge--unknown { stroke: var(--fed-muted); opacity: 0.3; }

/* §pass-N Pass 4: data-stream marching-dashed pattern on BFS edges +
   edge-flash on PeerRegistryUrlAutoCorrected event arrival.
   Mirrors `--nc-data-stream` semantic intent + `pulse-glow` keyframe family
   from neural-command.css — no new ad-hoc colors. */
.fed-svg-edge--stream {
  stroke-dasharray: 4 7;
  animation: fed-svg-edge-stream 14s linear infinite;
}
@keyframes fed-svg-edge-stream {
  0%   { stroke-dashoffset: 0; }
  100% { stroke-dashoffset: -220; }
}
.fed-svg-edge--flashing {
  animation: fed-svg-edge-flash 2.5s ease-out;
  filter: drop-shadow(0 0 8px rgba(74, 222, 128, 0.55));
}
@keyframes fed-svg-edge-flash {
  0%   { stroke: var(--fed-ok); stroke-width: 5; opacity: 1; }
  35%  { stroke: var(--fed-ok); stroke-width: 4; opacity: 1; }
  70%  { stroke: var(--fed-ok); stroke-width: 3; opacity: 0.9; }
  100% { stroke-width: 2; opacity: 0.7; }
}
@media (prefers-reduced-motion: reduce) {
  .fed-svg-edge--stream { animation: none; stroke-dasharray: none; }
  .fed-svg-edge--flashing { animation: none; stroke: var(--fed-ok); filter: none; }
}

/* §pass-N Pass 7: Network stress chromatic aberration. Filter intensity is
   driven by the --fed-chroma-intensity CSS var, set by networkStressLevel
   computed. Red/cyan drop-shadow ghosts on either side (red=danger, cyan=primary)
   evoke the GlitchOverlay.vue pattern. Transition smoothly. */
.fed-network-card--stressed {
  filter:
    drop-shadow(calc(var(--fed-chroma-intensity, 0) *  1.5px) 0 0 rgba(255, 51, 102, calc(var(--fed-chroma-intensity, 0) * 0.36)))
    drop-shadow(calc(var(--fed-chroma-intensity, 0) * -1.5px) 0 0 rgba(0, 210, 210, calc(var(--fed-chroma-intensity, 0) * 0.32)));
  transition: filter 900ms cubic-bezier(0.4, 0, 0.2, 1);
}
.fed-network-stress-pill {
  position: absolute;
  top: 8px;
  right: 14px;
  z-index: 7;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  background: rgba(255, 51, 102, 0.12);
  color: var(--nc-danger, #ff3366);
  border: 1px solid rgba(255, 51, 102, 0.35);
  text-transform: uppercase;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  animation: fed-network-stress-pulse 1.6s ease-in-out infinite;
  pointer-events: none;
}
@keyframes fed-network-stress-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 51, 102, 0); }
  50%      { box-shadow: 0 0 0 6px rgba(255, 51, 102, 0.08); }
}
@media (prefers-reduced-motion: reduce) {
  .fed-network-card--stressed { filter: none; transition: none; }
  .fed-network-stress-pill { animation: none }
}

/* §pass-N Pass 4: hologram stripe on Network panel — canonical .nc-card::before
   pattern recreated here (scoped). Subtle top-edge sweep at 3s cadence. */
.fed-network-card--holographic { position: relative; overflow: hidden; }
.fed-network-card--holographic::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: var(--nc-hologram, linear-gradient(90deg, #00e5e5 0%, #00ff88 50%, #00e5e5 100%));
  background-size: 200% 100%;
  animation: fed-network-card-holo-shift 3.2s linear infinite;
  z-index: 4;
  pointer-events: none;
}
@keyframes fed-network-card-holo-shift {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}
@media (prefers-reduced-motion: reduce) {
  .fed-network-card--holographic::before { animation: none }
}

/* Nodes */
.fed-svg-node-group { transition: transform 180ms ease; }
.fed-svg-node-group--clickable { cursor: pointer; }
.fed-svg-node-group--clickable:hover { transform-origin: center; }
.fed-svg-node-group--clickable:hover .fed-svg-node { stroke-width: 3; filter: brightness(1.2); }

.fed-svg-node {
  stroke: rgba(15, 23, 42, 0.9); stroke-width: 2;
  transition: all 220ms;
}
.fed-svg-node--local         { fill: var(--fed-direct); stroke: #fff; }
.fed-svg-node--frame         { fill: var(--fed-frame); }
.fed-svg-node--direct_peer   { fill: var(--fed-direct); }
.fed-svg-node--discovered    { fill: var(--fed-discovered); }
.fed-svg-node--cloud_operator { fill: var(--fed-cloud); }
.fed-svg-node--unknown       { fill: var(--fed-muted); }

.fed-svg-halo { fill: none; stroke-width: 2; }
.fed-svg-halo--local { stroke: var(--fed-direct); opacity: 0.4; animation: fed-pulse 2.5s ease-in-out infinite; }
.fed-svg-halo--drift { stroke: var(--fed-bad); opacity: 0.6; stroke-dasharray: 3 3; }
@keyframes fed-pulse {
  0%, 100% { opacity: 0.25; r: var(--r0); }
  50% { opacity: 0.55; }
}

.fed-svg-node-icon {
  fill: rgba(15, 23, 42, 0.95);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 14px; font-weight: 700;
  pointer-events: none; user-select: none;
}

.fed-svg-label {
  fill: #e2e8f0; font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  pointer-events: none; user-select: none;
  paint-order: stroke fill;
  stroke: rgba(15, 23, 42, 0.85); stroke-width: 3;
}
.fed-svg-label--frame { fill: var(--fed-frame); }
.fed-svg-label--direct_peer { fill: var(--fed-direct); }
.fed-svg-label--discovered { fill: var(--fed-discovered); }
.fed-svg-label--cloud_operator { fill: var(--fed-cloud); }
.fed-svg-label--local { fill: #fff; font-size: 12px; font-weight: 700; }

.fed-svg-hop {
  fill: rgba(148, 163, 184, 0.7);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  pointer-events: none;
}

/* Legend */
.fed-network-legend { display: flex; flex-wrap: wrap; gap: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.06); margin-top: 8px; font-size: 11px; color: var(--fed-muted); }
.fed-legend-item { display: inline-flex; align-items: center; gap: 5px; }
.fed-legend-item--right { margin-left: auto; }
.fed-legend-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.fed-legend-dot--local          { background: var(--fed-direct); border: 1px solid #fff; }
.fed-legend-dot--frame          { background: var(--fed-frame); }
.fed-legend-dot--direct_peer    { background: var(--fed-direct); }
.fed-legend-dot--discovered     { background: var(--fed-discovered); }
.fed-legend-dot--cloud_operator { background: var(--fed-cloud); }
.fed-legend-dot--drift          { background: var(--fed-bad); border: 1px dashed var(--fed-bad); }

/* ── Drawer ────────────────────────────────────────────── */
.fed-drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: flex; justify-content: flex-end;
  animation: fed-fade 160ms ease-out;
}
@keyframes fed-fade { from { opacity: 0; } to { opacity: 1; } }
.fed-drawer {
  width: min(560px, 100%); height: 100vh;
  background: #0f172a;
  border-left: 1px solid rgba(var(--fed-direct-rgb), 0.25);
  display: flex; flex-direction: column;
  animation: fed-slide 180ms ease-out;
  overflow: hidden;
}
@keyframes fed-slide { from { transform: translateX(100%); } to { transform: translateX(0); } }
.fed-drawer-head {
  padding: 16px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
}
.fed-drawer-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--fed-direct); margin-bottom: 4px; }
.fed-drawer-title { margin: 0; font-size: 18px; font-weight: 700; color: #f1f5f9; }
.fed-drawer-sub { color: var(--fed-muted); font-size: 12px; font-family: 'IBM Plex Mono', monospace; word-break: break-all; }
.fed-drawer-close {
  background: none; border: none; color: var(--fed-muted); cursor: pointer;
  padding: 4px; border-radius: 4px;
}
.fed-drawer-close:hover { color: #f1f5f9; background: rgba(255, 255, 255, 0.05); }
.fed-drawer-tabs {
  display: flex; gap: 2px; padding: 0 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  overflow-x: auto;
}
.fed-drawer-tab {
  background: transparent; border: none;
  color: var(--fed-muted);
  padding: 10px 12px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  white-space: nowrap;
  transition: all 120ms;
}
.fed-drawer-tab:hover { color: #cbd5e1; }
.fed-drawer-tab-active { color: var(--fed-direct); border-bottom-color: var(--fed-direct); }
.fed-drawer-body { padding: 16px 18px; overflow-y: auto; flex: 1; }

.fed-tab-pane { color: #cbd5e1; font-size: 13px; }
.fed-kv { display: grid; grid-template-columns: 140px 1fr; gap: 6px 14px; margin: 0; }
.fed-kv dt { color: var(--fed-muted); font-family: 'IBM Plex Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.fed-kv dd { margin: 0; color: #e2e8f0; font-size: 12px; word-break: break-word; }
.fed-mono { font-family: 'IBM Plex Mono', monospace; font-size: 11px; }
.fed-tab-hint { color: var(--fed-muted); font-size: 12px; margin-top: 14px; line-height: 1.5; }

/* Health */
.fed-health-probe { margin-top: 18px; }
.fed-pre {
  background: rgba(0, 0, 0, 0.4); padding: 10px; border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace; font-size: 10px;
  color: #cbd5e1; overflow: auto; max-height: 280px; margin-top: 10px;
}

/* Lifecycle stack */
.fed-drift-pane {
  display: flex; gap: 10px; padding: 12px;
  background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3);
  color: var(--fed-bad); border-radius: 6px; margin-bottom: 14px;
  font-size: 12px;
}
.fed-drift-pane-body { flex: 1; min-width: 0; }
.fed-drift-pane-title { font-weight: 700; margin-bottom: 8px; }
.fed-drift-list { margin: 0; padding-left: 20px; color: #fecaca; }

/* T7 — drift remediation hint cards */
.fed-drift-hints { display: flex; flex-direction: column; gap: 8px; }
.fed-drift-hint {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: 6px;
  padding: 10px 12px;
  color: var(--nc-text-primary, #e2e8f0);
}
.fed-drift-hint-head {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-bottom: 6px; font-weight: 600;
  color: var(--fed-bad);
}
.fed-drift-hint-label { flex: 1; min-width: 0; font-size: 12px; }
.fed-drift-hint-flag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  background: rgba(239, 68, 68, 0.12);
  color: #fecaca;
  padding: 1px 6px;
  border-radius: 3px;
  letter-spacing: 0.02em;
}
.fed-drift-hint-body { display: flex; flex-direction: column; gap: 4px; font-size: 11.5px; line-height: 1.5; }
.fed-drift-hint-row { margin: 0; display: flex; gap: 6px; align-items: baseline; }
.fed-drift-hint-key {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: var(--fed-muted);
  letter-spacing: 0.05em;
  min-width: 38px;
  flex-shrink: 0;
}
.fed-drift-hint-val { color: var(--nc-text-primary, #e2e8f0); }
.fed-drift-hint-unknown { font-style: italic; color: var(--fed-muted); }
.fed-drift-hint-cli {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 4px;
  padding: 6px 8px;
  margin-top: 2px;
}
.fed-drift-hint-cli code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  color: var(--fed-direct);
  flex: 1;
  word-break: break-all;
}
.fed-drift-hint-copy {
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10px; padding: 3px 8px;
  background: rgba(var(--fed-direct-rgb), 0.12);
  color: var(--fed-direct);
  border: 1px solid rgba(var(--fed-direct-rgb), 0.3);
  border-radius: 3px;
  cursor: pointer;
  transition: background 0.15s;
}
.fed-drift-hint-copy:hover { background: rgba(var(--fed-direct-rgb), 0.22); }
.fed-drift-hint-auto {
  margin: 4px 0 0 0;
  display: inline-flex; align-items: center; gap: 4px;
  font-size: 10.5px;
  font-style: italic;
  color: var(--fed-ok);
}
.fed-lifecycle-stack { display: flex; flex-direction: column; gap: 8px; }
.fed-lc-layer { background: rgba(15, 23, 42, 0.8); border: 1px solid rgba(255, 255, 255, 0.06); border-radius: 6px; padding: 10px 12px; }
.fed-lc-layer header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.fed-lc-tag { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.1em; color: var(--fed-direct); }
.fed-lc-status { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: rgba(148, 163, 184, 0.15); color: var(--fed-muted); border: 1px solid rgba(148, 163, 184, 0.25); font-family: 'IBM Plex Mono', monospace; }
.fed-lc-body { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 11px; color: #cbd5e1; }
.fed-lc-body code { background: rgba(0, 0, 0, 0.3); padding: 2px 6px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 10px; }
.fed-lc-body em { color: var(--fed-muted); }

/* Trust */
.fed-trust-bar { display: inline-block; width: 120px; height: 6px; background: rgba(255, 255, 255, 0.1); border-radius: 3px; overflow: hidden; vertical-align: middle; margin-right: 6px; }
.fed-trust-bar-fill { display: block; height: 100%; background: linear-gradient(90deg, var(--fed-cloud), var(--fed-direct)); }
.fed-trust-pct { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #cbd5e1; }

/* Events */
.fed-event-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.fed-event { display: flex; align-items: center; gap: 10px; padding: 8px 10px; background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(255, 255, 255, 0.05); border-radius: 4px; font-size: 12px; }
.fed-event-type { font-family: 'IBM Plex Mono', monospace; color: var(--fed-direct); font-weight: 600; }
.fed-event-when { color: var(--fed-muted); font-size: 11px; }
.fed-event-detail { color: #cbd5e1; font-size: 11px; margin-left: auto; }

/* Modal (add direct peer) */
.fed-modal {
  width: min(480px, 92vw); margin: auto;
  background: #0f172a; border: 1px solid rgba(var(--fed-direct-rgb), 0.25);
  border-radius: 10px; box-shadow: 0 20px 60px rgba(0, 0, 0, 0.6);
  display: flex; flex-direction: column;
  align-self: center;
}
.fed-modal-body { padding: 18px; display: flex; flex-direction: column; gap: 12px; }
.fed-field { display: flex; flex-direction: column; gap: 4px; }
.fed-field-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.05em; color: var(--fed-muted); text-transform: uppercase; }
.fed-input {
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; padding: 8px 10px;
  color: #e2e8f0; font-size: 13px;
  font-family: 'IBM Plex Mono', monospace;
}
.fed-input:focus { outline: none; border-color: var(--fed-direct); }
.fed-modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }

/* f058 WS3: Frame invitations UI */
.fed-modal--wide { width: min(900px, 95vw); max-height: 85vh; }
.fed-modal--wide .fed-modal-body { overflow-y: auto; max-height: calc(85vh - 60px); }

.fed-invites-banner { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.3); color: #fcd34d; }

.fed-pill { display: inline-flex; align-items: center; gap: 3px; padding: 2px 8px; border-radius: 10px; font-size: 10px; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.05em; margin-left: 8px; }
.fed-pill--amber { background: rgba(245, 158, 11, 0.15); color: var(--fed-discovered); border: 1px solid rgba(245, 158, 11, 0.3); }
.fed-pill--frame { background: rgba(168, 85, 247, 0.15); color: var(--fed-frame); border: 1px solid rgba(168, 85, 247, 0.3); }

.fed-invite-list { display: flex; flex-direction: column; gap: 8px; }
.fed-invite-row {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-left: 3px solid var(--fed-discovered);
  border-radius: 6px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.fed-invite-row:hover { background: rgba(15, 23, 42, 0.9); }
.fed-invite-row--active { border-left-color: var(--fed-direct); background: rgba(var(--fed-direct-rgb), 0.05); }
.fed-invite-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.fed-invite-head strong { color: #f1f5f9; font-size: 14px; }
.fed-invite-when { margin-left: auto; font-size: 11px; color: var(--fed-muted); font-family: 'IBM Plex Mono', monospace; }
.fed-invite-meta { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: #cbd5e1; margin-bottom: 4px; }
.fed-invite-meta span { display: inline-flex; align-items: center; gap: 4px; }
.fed-invite-desc { margin: 6px 0; font-size: 12px; color: #94a3b8; font-style: italic; }
.fed-invite-bundle { font-size: 10px; color: var(--fed-muted); display: flex; gap: 6px; align-items: center; }
.fed-invite-bundle code { background: rgba(0, 0, 0, 0.3); padding: 1px 5px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; word-break: break-all; }

.fed-invite-actions {
  margin-top: 12px; padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex; flex-direction: column; gap: 10px;
}
.fed-field--reject { margin-top: 6px; }

.fed-action-btn--primary { background: rgba(34, 197, 94, 0.14); color: var(--fed-cloud); border-color: rgba(34, 197, 94, 0.3); }
.fed-action-btn--primary:hover:not(:disabled) { background: rgba(34, 197, 94, 0.22); }
.fed-action-btn--danger { background: rgba(239, 68, 68, 0.12); color: #f87171; border-color: rgba(239, 68, 68, 0.3); }
.fed-action-btn--danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.2); }

.fed-help-body { font-size: 13px; color: #cbd5e1; line-height: 1.55; }
.fed-help-body h3 { font-size: 13px; font-family: 'IBM Plex Mono', monospace; color: var(--fed-direct); letter-spacing: 0.05em; margin: 16px 0 6px; text-transform: uppercase; }
.fed-help-body code { background: rgba(0, 0, 0, 0.3); padding: 1px 5px; border-radius: 3px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
.fed-help-body ol, .fed-help-body ul { padding-left: 20px; margin: 6px 0; }
.fed-help-body li { margin: 4px 0; }
.fed-help-footnote { margin-top: 12px; font-size: 11px; color: var(--fed-muted); font-style: italic; }
.fed-code {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px; padding: 10px 12px;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: #cbd5e1;
  overflow-x: auto; white-space: pre;
}

.fed-danger-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 6px;
  padding: 10px 12px;
  font-size: 12px;
  color: #fca5a5;
  display: flex; gap: 8px; align-items: flex-start;
  margin-bottom: 8px;
}
.fed-lc-danger-zone { margin-top: 12px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

/* Responsive */
@media (max-width: 600px) {
  .fed { padding: 16px 14px; }
  .fed-h1 { font-size: 22px; }
  .fed-tier-grid { grid-template-columns: 1fr; }
  .fed-drawer { width: 100%; border-left: none; }
  .fed-kv { grid-template-columns: 1fr; gap: 2px; }
  .fed-kv dd { margin-bottom: 8px; }
}
</style>
