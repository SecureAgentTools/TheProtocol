<script setup lang="ts">
import { resolvePeerAsset } from '@/services/peerAssets'
/**
 * Federation Discovery — flagship browse + filter + drill view for registry peers
 * §pass62 (2026-05-21) — Commander's request to make this BETTER than Agent Discovery.
 *
 * Mirrors Discovery.vue's overall structure (sidebar filters + grid/list results +
 * detail drill-down) but applies every §pass61 primitive: PeerOrb visual identity,
 * PeerHoverPopover, LiveFederationFeed, mobile fallback via useViewport, chromatic
 * aberration stress signaling. Shared topology fetch via useFederationTopology.
 *
 * Route: /federation-discover (sidebar entry under AGENTS category).
 * Pillars: visible visual identity · trust at a glance · hover beats click ·
 *          live federation pulse · mobile first · stress signaling.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  useFederationTopology,
  buildPeersById,
  deriveDisplayHop,
  deriveChainPath,
  type FederatedPeer,
} from '@/composables/useFederationTopology'
import { useFederationEvents, FEDERATION_EVENT_TYPES } from '@/composables/useFederationEvents'
import { apiClient } from '@/services/api/client'
import { usePermissions } from '@/composables/usePermissions'
import { useViewport } from '@/composables/useViewport'
import { useI18n } from '@/composables/useI18n'
import { useAlive } from '@/composables/useAlive'
import Icon from '@/components/Icon.vue'
import PeerOrb from '@/components/federation/PeerOrb.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import PeerHoverPopover from '@/components/federation/PeerHoverPopover.vue'
import LiveFederationFeed, { type FeedEvent } from '@/components/federation/LiveFederationFeed.vue'
import PeerDetailDrawer from '@/components/federation/PeerDetailDrawer.vue'

const { t, tp } = useI18n()

// ── Permissions + viewport ──────────────────────────────────
const { canFederation } = usePermissions()
const vp = useViewport()
const route = useRoute()
const router = useRouter()

// ── Topology data path (shared composable) ──────────────────
const { topology, isLoading, error, lastFetchedAt, allPeers, localRegistry, fetchTopology } =
  useFederationTopology({ admin: !!canFederation.value })

// ── Filter + search + sort state ────────────────────────────
type TierFilter = 'all' | 'frame' | 'direct_peer' | 'discovered' | 'cloud_operator'
type SortKey = 'name' | 'hop' | 'last_synced' | 'bayesian' | 'interactions' | 'fees_intra' | 'fees_cross' | 'random'

const tierFilter = ref<TierFilter>('all')
const search = ref('')
const sortKey = ref<SortKey>('name')
const sortDesc = ref(false)
const showOnlyDrift = ref(false)
const showOnlySigned = ref(false)
// §pass62.2 (2026-05-21) — Hide INACTIVE peers by default. On Frame B the
// admin topology returns ~10 legacy `Alpha-B / Beta-B / Delta-B / ...` peer
// rows from early federation tests that have status='INACTIVE' but were never
// hard-deleted; surfacing them clutters the view. Commander asked them gone.
// Toggle exposed in the sidebar so admins can still inspect if needed.
const showInactive = ref(false)
const showOnlySovereignPinned = ref(false)
const showOnlyCrossFrame = ref(false)
const trustDomainFilter = ref<string>('')  // empty = all
const bundleFreshnessFilter = ref<'all' | 'fresh' | 'overdue' | 'critical' | 'unknown'>('all')
const feesIntraMax = ref(5)  // %
const feesCrossMax = ref(5)
const viewMode = ref<'grid' | 'list'>('grid')

// ── Hover popover state ─────────────────────────────────────
const hoverPeer = ref<FederatedPeer | null>(null)
const hoverX = ref(0)
const hoverY = ref(0)
const hoverVisible = ref(false)
let hoverShowTimer: ReturnType<typeof setTimeout> | null = null

function onCardMouseEnter(peer: FederatedPeer, ev: MouseEvent) {
  hoverX.value = ev.clientX
  hoverY.value = ev.clientY
  if (hoverShowTimer) clearTimeout(hoverShowTimer)
  hoverShowTimer = setTimeout(() => {
    hoverPeer.value = peer
    hoverVisible.value = true
  }, 180)
}
function onCardMouseMove(ev: MouseEvent) {
  if (!hoverVisible.value) {
    hoverX.value = ev.clientX
    hoverY.value = ev.clientY
    return
  }
  hoverX.value = ev.clientX
  hoverY.value = ev.clientY
}
function onCardMouseLeave() {
  if (hoverShowTimer) { clearTimeout(hoverShowTimer); hoverShowTimer = null }
  hoverVisible.value = false
}

// ── Drawer state (tab state lives inside PeerDetailDrawer) ──
const drawerOpen = ref(false)
const drawerPeer = ref<FederatedPeer | null>(null)

function openDrawer(peer: FederatedPeer) {
  drawerPeer.value = peer
  drawerOpen.value = true
}
function closeDrawer() { drawerOpen.value = false }

// ── Build local pseudo-peer for the local registry card ─────
const localPseudoPeer = computed<FederatedPeer | null>(() => {
  const lr = localRegistry.value
  if (!lr) return null
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
  } as FederatedPeer
})

// §pass62.6 (2026-05-21) — Tree-walk derivation map (mirrors Network tab).
// Indexes ALL real peers (excludes the synthesized local pseudo-peer with id=0).
// Consumers call deriveDisplayHop(peer, peersById.value) / deriveChainPath(...)
// to get the same depth the Network tab computes via placeSubtree recursion.
const peersById = computed(() => buildPeersById(allPeers.value))

// Convenience wrapper — bakes localName from the live local registry.
function chainPathFor(peer: FederatedPeer): string[] {
  const localName = localRegistry.value?.name || t('federationDiscoveryView.localFallback')
  return deriveChainPath(peer, peersById.value, localName)
}
function displayHopFor(peer: FederatedPeer): number {
  return deriveDisplayHop(peer, peersById.value)
}
// Parent peer name (1 hop up) — for the "via X" pill.
function parentNameFor(peer: FederatedPeer): string | null {
  if (peer.parent_registry_id == null) return null
  const parent = peersById.value.get(peer.parent_registry_id)
  return parent?.name || null
}

// Peers + local prepended (local always first)
const allPeersWithLocal = computed<FederatedPeer[]>(() => {
  const list = allPeers.value.slice()
  if (localPseudoPeer.value) list.unshift(localPseudoPeer.value)
  return list
})

// ── Filtered + sorted ──────────────────────────────────────
const trustDomains = computed(() => {
  const set = new Set<string>()
  for (const p of allPeersWithLocal.value) if (p.trust_domain) set.add(p.trust_domain)
  return Array.from(set).sort()
})

function matchesFilters(p: FederatedPeer): boolean {
  if (tierFilter.value !== 'all' && p.peer_type !== tierFilter.value) return false
  if (search.value) {
    const q = search.value.toLowerCase()
    const haystack = `${p.name || ''} ${p.base_url || ''} ${p.trust_domain || ''} ${p.operator_did || ''}`.toLowerCase()
    if (!haystack.includes(q)) return false
  }
  // §pass62.2 — hide INACTIVE peers by default (Local pseudo-peer always shows).
  if (!showInactive.value && p.peer_type !== 'local' && (p.status || '').toUpperCase() === 'INACTIVE') return false
  if (showOnlyDrift.value && !p.has_drift) return false
  if (showOnlySigned.value && p.card_signature_verified !== true) return false
  if (showOnlySovereignPinned.value && !p.visual?.sovereign_variant) return false
  if (showOnlyCrossFrame.value && p.peer_type !== 'frame') return false
  if (trustDomainFilter.value && p.trust_domain !== trustDomainFilter.value) return false
  if (bundleFreshnessFilter.value !== 'all') {
    const fr = p.bundle_freshness
    const state = fr?.error ? 'unknown' : fr?.refresh_critical ? 'critical' : fr?.refresh_overdue ? 'overdue' : fr ? 'fresh' : null
    if (state !== bundleFreshnessFilter.value) return false
  }
  // Fee gates — only filter if peer has fees_summary AND filter is below 5%
  if (feesIntraMax.value < 5 && (p.fees_summary?.intra_registry ?? 0) > feesIntraMax.value) return false
  if (feesCrossMax.value < 5 && (p.fees_summary?.cross_registry ?? 0) > feesCrossMax.value) return false
  return true
}

const filteredPeers = computed<FederatedPeer[]>(() => {
  const list = allPeersWithLocal.value.filter(matchesFilters)
  const sorted = list.slice().sort((a, b) => {
    let cmp = 0
    switch (sortKey.value) {
      case 'name': cmp = (a.name || '').localeCompare(b.name || ''); break
      case 'hop': cmp = (a.hop_distance ?? 999) - (b.hop_distance ?? 999); break
      case 'last_synced': cmp = new Date(a.last_synced_at || 0).getTime() - new Date(b.last_synced_at || 0).getTime(); break
      case 'bayesian': cmp = (a.bayesian_discount ?? 1) - (b.bayesian_discount ?? 1); break
      case 'interactions': cmp = (a.total_interactions ?? 0) - (b.total_interactions ?? 0); break
      case 'fees_intra': cmp = (a.fees_summary?.intra_registry ?? 0) - (b.fees_summary?.intra_registry ?? 0); break
      case 'fees_cross': cmp = (a.fees_summary?.cross_registry ?? 0) - (b.fees_summary?.cross_registry ?? 0); break
      case 'random': cmp = Math.random() - 0.5; break
    }
    return sortDesc.value ? -cmp : cmp
  })
  return sorted
})

// ── Stats strip ────────────────────────────────────────────
const stats = computed(() => {
  const total = allPeersWithLocal.value.length
  const summary = topology.value?.summary
  return {
    total,
    visible: filteredPeers.value.length,
    drift: summary?.drift_count ?? 0,
    bundlesCritical: summary?.bundles_critical ?? 0,
    bundlesFresh: summary?.bundles_fresh ?? 0,
    healthy: summary?.healthy_count ?? 0,
    byType: summary?.peers_by_type ?? {},
  }
})

// ── Stress signaling (Pass 8 — chromatic aberration) ───────
const networkStressLevel = computed<number>(() => {
  const s = topology.value?.summary
  if (!s) return 0
  let stress = 0
  if (s.drift_count && s.drift_count > 0) stress += Math.min(s.drift_count / 5, 0.4)
  if (s.bundles_critical && s.bundles_critical > 0) stress += 0.35
  if (s.bundles_overdue && s.bundles_overdue > 0) stress += 0.15
  return Math.min(stress, 1)
})
const showNetworkStress = computed(() => networkStressLevel.value > 0.05)

// ── Live feed (Pass 6, §pass62.1 enhanced) ─────────────────
// §pass62.1 (2026-05-21):
//   * Per-view localStorage key (`:discovery` suffix) so collapsing the feed
//     in Federation.vue's Network tab doesn't leak into this view (or vice
//     versa). Previous shared key was a latent bug.
//   * Backfill last 20 federation events on mount via /admin/events with the
//     same whitelist used by useFederationEvents — so the feed isn't empty
//     when the live stream is quiet (steady-state federation can go hours
//     between drift events).
//   * Backfilled events marked `historical=true` and rendered with reduced
//     opacity + a HIST tag so they're visually distinct from live arrivals.
const LIVE_FEED_MAX = 20
const LIVE_FEED_KEY = 'theprotocol:federation:discovery:liveFeed:collapsed'
const liveFeedEvents = ref<FeedEvent[]>([])
const liveFeedCollapsed = ref<boolean>(
  (typeof localStorage !== 'undefined' && localStorage.getItem(LIVE_FEED_KEY) === 'true')
)
const lastFederationEventIso = ref<string | null>(null)
const _seenIds = new Set<string>()
function pushLiveFeedEvent(eventType: string, payload?: any, opts?: { historical?: boolean }) {
  const evtId = payload?.id || payload?.event_id || payload?.data?.id
  if (evtId && _seenIds.has(evtId)) return
  if (evtId) {
    _seenIds.add(evtId)
    if (_seenIds.size > 200) {
      const arr = Array.from(_seenIds)
      _seenIds.clear()
      arr.slice(50).forEach(id => _seenIds.add(id))
    }
  }
  const now = Date.now()
  const recent = liveFeedEvents.value[0]
  if (recent && recent.type === eventType && (now - recent.ts) < 2000 && !evtId) return
  liveFeedEvents.value.unshift({
    id: `${eventType}-${now}-${Math.random().toString(36).slice(2, 8)}`,
    type: eventType, ts: now, payload,
    historical: !!opts?.historical,
  })
  if (liveFeedEvents.value.length > LIVE_FEED_MAX) liveFeedEvents.value.length = LIVE_FEED_MAX
}
function toggleLiveFeed() {
  liveFeedCollapsed.value = !liveFeedCollapsed.value
  try {
    localStorage.setItem(LIVE_FEED_KEY, liveFeedCollapsed.value ? 'true' : 'false')
  } catch { /* private browsing */ }
}

// §pass62.1 — Backfill from /admin/events on mount. Pulls last N events
// matching the federation whitelist + sorts oldest-first so we insert in
// chronological order (newest ends up at position 0 after unshift). Marks
// each entry historical=true. Best-effort: silent on 403/network errors.
async function backfillFederationEvents() {
  // §FESUITE: the same gate Federation.vue has carried since §FINDFIX F3 — this twin kept asking an admin-only rail
  // for every member and took a 403 on each visit.
  if (!canFederation.value) return
  try {
    const types = Array.from(FEDERATION_EVENT_TYPES).join(',')
    // §pass71.6 (2026-05-25) — fixed endpoint mismatch (404 surfaced by audit):
    // was /admin/events?event_types= → real endpoint is /admin/events/search
    // with singular `event_type`. Mirrors the same fix in Federation.vue:449.
    const r = await apiClient.get('/admin/events/search', {
      params: { limit: 20, event_type: types },
    })
    const body = r.data
    const items: any[] = Array.isArray(body) ? body : (body?.items || body?.events || [])
    if (!items.length) return
    // Sort oldest-first so when we unshift in loop the newest ends on top.
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
      // Use the original event timestamp (not Date.now()) so the "Xh ago" label
      // shows the actual age. Push directly with historical flag.
      const ts = tsIso ? new Date(tsIso).getTime() : Date.now()
      const evtId = ev.id || ev.event_id
      if (evtId && _seenIds.has(evtId)) continue
      if (evtId) _seenIds.add(evtId)
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
function onFeedHighlight(evt: FeedEvent) {
  const peerId = evt.payload?.peer_id ?? evt.payload?.data?.peer_id
  if (peerId != null) {
    const peer = allPeersWithLocal.value.find(p => p.id === peerId)
    if (peer) openDrawer(peer)
  }
}

// ── WebSocket federation events ────────────────────────────
const wsEvents = useFederationEvents({
  onRefresh: () => {
    if (hoverVisible.value) return  // sticky-hover gate (§pass61.3)
    fetchTopology()
  },
  onLiveEvent: (evtType, payload) => {
    pushLiveFeedEvent(evtType, payload)
  },
  debounceMs: 500,
})

// ── Mobile filter sheet (Pass 7) ───────────────────────────
const mobileFiltersOpen = ref(false)

// ── Sort label helper ──────────────────────────────────────
const sortLabel = computed(() => {
  const label = {
    name: t('federationDiscoveryView.sort.name'),
    hop: t('federationDiscoveryView.sort.hop'),
    last_synced: t('federationDiscoveryView.sort.lastSynced'),
    bayesian: t('federationDiscoveryView.sort.bayesian'),
    interactions: t('federationDiscoveryView.sort.interactions'),
    fees_intra: t('federationDiscoveryView.sort.feesIntra'),
    fees_cross: t('federationDiscoveryView.sort.feesCross'),
    random: t('federationDiscoveryView.sort.random'),
  }[sortKey.value]
  return `${label} ${sortDesc.value ? '↓' : '↑'}`
})

// ── URL state hydration (peer drawer deep-link) ────────────
function hydrateFromUrl() {
  const q = route.query
  if (q.tier && ['all','frame','direct_peer','discovered','cloud_operator'].includes(q.tier as string)) {
    tierFilter.value = q.tier as TierFilter
  }
  if (q.q) search.value = q.q as string
  if (q.sort && ['name','hop','last_synced','bayesian','interactions','fees_intra','fees_cross','random'].includes(q.sort as string)) {
    sortKey.value = q.sort as SortKey
  }
  if (q.view === 'list') viewMode.value = 'list'
}
let _pushDebounce: ReturnType<typeof setTimeout> | null = null
function pushUrl() {
  if (_pushDebounce) clearTimeout(_pushDebounce)
  _pushDebounce = setTimeout(() => {
    const next: Record<string, string> = {}
    if (tierFilter.value !== 'all') next.tier = tierFilter.value
    if (search.value) next.q = search.value
    if (sortKey.value !== 'name') next.sort = sortKey.value
    if (viewMode.value !== 'grid') next.view = viewMode.value
    router.replace({ query: next }).catch(() => {})
  }, 200)
}
watch([tierFilter, search, sortKey, viewMode], pushUrl)

// ── Clear filters helper ──────────────────────────────────
function clearAllFilters() {
  tierFilter.value = 'all'
  search.value = ''
  showOnlyDrift.value = false
  showOnlySigned.value = false
  showOnlySovereignPinned.value = false
  showOnlyCrossFrame.value = false
  showInactive.value = false  // §pass62.2
  trustDomainFilter.value = ''
  bundleFreshnessFilter.value = 'all'
  feesIntraMax.value = 5
  feesCrossMax.value = 5
  sortKey.value = 'name'
  sortDesc.value = false
}
const hasActiveFilter = computed(() =>
  tierFilter.value !== 'all' ||
  !!search.value ||
  showOnlyDrift.value || showOnlySigned.value || showOnlySovereignPinned.value || showOnlyCrossFrame.value ||
  !!trustDomainFilter.value ||
  bundleFreshnessFilter.value !== 'all' ||
  feesIntraMax.value < 5 || feesCrossMax.value < 5
)

// ── §pass62.2 (2026-05-21) — Card avatar helpers ─────────────
// Render the same identity treatment as PeerHoverPopover (which Commander
// flagged as the "good" look) directly on the card head. Priority:
//   1. flare_encirclement_variant (cosmetic; what operator equipped)
//   2. sovereign_variant (rank pin; only used as fallback)
//   3. visual.icon_url (custom uploaded avatar)
//   4. plain colored orb with halo (tier-color fallback)
function flareVariantFor(peer: any): string | null {
  return peer?.visual?.flare_encirclement_variant
    || peer?.visual?.sovereign_variant
    || null
}
function flareTierFor(peer: any): 'sovereign' | 'shadow_chancellor' {
  // Sovereign tier ONLY when sovereign_variant is the only signal (rank pin).
  if (!peer?.visual?.flare_encirclement_variant && peer?.visual?.sovereign_variant) return 'sovereign'
  return 'shadow_chancellor'
}
function flareOverlayFor(peer: any): string | null {
  return peer?.visual?.flare_encirclement_overlay || null
}
function plainOrbStyle(peer: any): Record<string, string> {
  const tierColors: Record<string, string> = {
    frame: '#8b5cf6',
    direct_peer: '#06b6d4',
    discovered: '#94a3b8',
    cloud_operator: '#10b981',
    local: '#fbbf24',
  }
  const color = peer?.visual?.orb_color || tierColors[peer?.peer_type as string] || '#94a3b8'
  const glow = peer?.visual?.orb_glow_color || color
  return {
    background: color,
    boxShadow: `0 0 18px ${glow}66, inset 0 0 10px ${glow}55`,
  }
}

// ── PeerOrb visual helpers (mirror Federation.vue) ──────────
function humanizeAge(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return t('federationDiscoveryView.ageFallback')
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
function peerEtagShort(peer: FederatedPeer): string | null {
  const e = peer.card_etag || peer.lifecycle?.card_etag
  if (!e) return null
  const stripped = e.startsWith('sha256:') ? e.slice(7) : e
  return `${stripped.slice(0, 12)}…`
}
/** §TRUSTWIRE — three states, never two. A peer with no recorded interaction is UNMEASURED and
 *  must not read like a peer we have downgraded; the Beta(1,1) point estimate is 0.5 either way,
 *  so the COUNT is what distinguishes them and the count is what we show. */
function peerTrust(peer: any): { text: string; cls: string; hint: string } | null {
  // ⚠ THE THIRD STATE IS "THE RAIL DID NOT TELL US". `bayesian_discount` and `total_interactions`
  // ride the ADMIN topology rail; a signed-out visitor gets /public/topology, which carries
  // neither. Reading a missing field as 0 would have printed "unmeasured" about every peer to
  // every visitor — a false statement, not a missing one. If we were not told, we say nothing.
  if (peer?.total_interactions === undefined || peer?.total_interactions === null) return null
  const n = Number(peer?.total_interactions ?? 0) || 0
  const lost = Number(peer?.disputes_lost_with ?? 0) || 0
  const d = peer?.bayesian_discount

  // §TRUSTPOLICY (2026-09-11) — ONE MODEL, ONE IMPLEMENTATION. The backend now
  // ships its verdict on the peer row (`trust`), computed against THIS FRAME'S
  // declared thresholds. Rendering it beats recomputing it here: this function
  // called a peer "measured" at ONE interaction while the frame's policy does not
  // judge a peer below `peer_trust.min_interactions` (10 by default), so the
  // screen and the gate answered the same question differently — the two-answers
  // shape this codebase keeps paying for.
  //
  // The local computation below is KEPT as the fallback for /public/topology,
  // which carries the raw counters and no verdict.
  const v = peer?.trust
  if (v && typeof v === 'object' && v.state && v.state !== 'unavailable') {
    const state = String(v.state)
    if (state === 'unmeasured') {
      return {
        text: t('federationDiscoveryView.card.trustUnmeasured', 'unmeasured'),
        cls: 'fdv-trust--unmeasured',
        hint: String(v.reason || t('federationDiscoveryView.card.trustUnmeasuredHint',
                'No settled cross-registry interaction with this peer has been recorded yet. This is an absence of evidence, not a judgement.')),
      }
    }
    const pctV = Math.round((Number(d ?? 0.5) || 0.5) * 100)
    // ⚠ The colour follows the POLICY STATE, not the number: a frame that has set
    // a strict threshold should see a peer go amber where a lenient frame does not.
    const cls = state === 'suspended' || state === 'restricted' ? 'fdv-trust--low'
      : state === 'warn' ? 'fdv-trust--mid' : 'fdv-trust--good'
    // `enforced` is the difference between "this frame IS withholding" and "this
    // frame is only watching", and they must never render the same.
    const acting = v.enforced ? '' : ' (observing only — this frame is not acting on it)'
    return {
      text: state === 'ok' ? `${pctV}%` : `${pctV}% · ${state}`,
      cls,
      hint: `${String(v.reason || '')}${acting}`,
    }
  }

  if (!n) {
    return {
      text: t('federationDiscoveryView.card.trustUnmeasured', 'unmeasured'),
      cls: 'fdv-trust--unmeasured',
      hint: t('federationDiscoveryView.card.trustUnmeasuredHint',
              'No settled cross-registry interaction with this peer has been recorded yet. This is an absence of evidence, not a judgement.'),
    }
  }
  // §TRUSTCHAIN P4.5 (2026-09-12) — NO LOCAL VERDICT. This fallback used to classify the peer
  // itself (75 / 40 cut-offs belonging to nobody's policy) whenever the rail carried counters and
  // no verdict — which is exactly the anonymous /public/topology case, where the frame has
  // DECIDED not to publish its opinion. A second classifier in the FE was both a second
  // implementation of peer_trust_policy and a leak of the verdict to visitors. What the rail
  // carried is shown as evidence: the count, and the number as the frame's own observation,
  // uncoloured. The verdict is the backend's block above, present for identified callers.
  const pct = Math.round((Number(d ?? 0.5) || 0.5) * 100)
  return {
    text: `${pct}% · ${n}`,
    cls: 'fdv-trust--unmeasured',
    // ⚠ legacy t() takes EITHER a fallback OR params, never both — tp() is the parameterised one.
    hint: tp('federationDiscoveryView.card.trustHintNoVerdict',
             'Beta(1,1) point estimate over {n} settled interactions, {lost} of which we lost a dispute on. This frame\'s verdict on the peer is shown to signed-in members only.',
             { n, lost }),
  }
}

// §TRUSTWIRE (2026-09-10) — THE LOCAL CARD'S OWN ROW. His ask: "make eu show its own trust score
// also when you check federation discover on."
//
// 🔴 A REGISTRY HAS NO TRUST SCORE IN ITSELF, and inventing one would be a number written for
// legibility. Trust here is directional and it is an OPINION: `bayesian_discount` is what WE have
// concluded about a peer from settlements we observed. There is no row for ourselves, and what our
// peers have concluded about US is their own private opinion — deliberately not published on
// anyone's card, so we cannot show it either.
//
// What the local card CAN honestly carry is our side of the ledger: how many settled interactions
// we have recorded, with how many of the peers we were told about, and the average of the opinions
// we hold. That is a real number about this registry, and it is labelled as ours.
const localTrust = computed<{ text: string; cls: string; hint: string } | null>(() => {
  // the same third state as peerTrust(): if the rail did not carry the fields, say nothing
  const told = allPeersWithLocal.value.filter(
    (p: any) => p.peer_type !== 'local' && p.total_interactions !== undefined && p.total_interactions !== null,
  )
  if (!told.length) return null
  const measured = told.filter((p: any) => Number(p.total_interactions) > 0)
  const settlements = measured.reduce((a: number, p: any) => a + (Number(p.total_interactions) || 0), 0)
  if (!measured.length) {
    return {
      text: t('federationDiscoveryView.card.ledgerNone', 'nothing settled yet'),
      cls: 'fdv-trust--unmeasured',
      hint: tp('federationDiscoveryView.card.ledgerNoneHint',
               'We have recorded no settled cross-registry interaction with any of our {total} peers yet. Trust here is an opinion we form about others from settlements we observe; a registry holds none about itself.',
               { total: told.length }),
    }
  }
  const mean = measured.reduce((a: number, p: any) => a + (Number(p.bayesian_discount ?? 0.5) || 0.5), 0) / measured.length
  const pct = Math.round(mean * 100)
  return {
    text: tp('federationDiscoveryView.card.ledgerText',
             '{n} settled · {m} of {total} peers measured · we score them {pct}%',
             { n: settlements, m: measured.length, total: told.length, pct }),
    cls: pct >= 75 ? 'fdv-trust--good' : pct >= 40 ? 'fdv-trust--mid' : 'fdv-trust--low',
    hint: t('federationDiscoveryView.card.ledgerHint',
            'This is our side of the ledger, not a score anyone gave us. A registry holds no trust in itself, and what our peers conclude about us is their own opinion, which no card publishes.'),
  }
})

function tierLabel(tier: string | undefined): string {
  switch (tier) {
    case 'frame': return t('federationDiscoveryView.tierLabel.frame')
    case 'direct_peer': return t('federationDiscoveryView.tierLabel.directPeer')
    case 'discovered': return t('federationDiscoveryView.tierLabel.discovered')
    case 'cloud_operator': return t('federationDiscoveryView.tierLabel.cloudOp')
    case 'local': return t('federationDiscoveryView.tierLabel.local')
    default: return tier || t('federationDiscoveryView.tierLabel.unknown')
  }
}

// ── Polling ────────────────────────────────────────────────
let pollTimer: ReturnType<typeof setInterval> | null = null
const POLL_INTERVAL_MS = 30_000

// §V0064 P2 — live venue capability per registry (server-side aggregate; the
// registry card's fees.exchange is the source of truth, this is its live echo).
const venueMap = ref<Record<string, { ccy: string; venue: string }>>({})
function venueInfo(name?: string | null): { ccy: string; venue: string } | null {
  if (!name) return null
  const n = name.toLowerCase()
  return venueMap.value[n] || venueMap.value[n.replace(/\s+/g, '-')] || null
}
function venueCcy(name?: string | null): string {
  return venueInfo(name)?.ccy || ''
}
function openVenueStocks(name?: string | null) {
  const info = venueInfo(name)
  if (info) void router.push({ path: '/agora/listings', query: { venue: info.venue } })
}
async function loadVenueMap() {
  try {
    const { data } = await apiClient.get('/agora/federation-tickers')
    const m: Record<string, { ccy: string; venue: string }> = {}
    for (const v of data?.venues || []) m[String(v.venue).toLowerCase()] = { ccy: v.currency, venue: String(v.venue) }
    venueMap.value = m
  } catch { venueMap.value = {} }
}

// §FESUITE: a peer's base_url here is its FEDERATION dial address (https://<host>:8443, the mTLS lane, whose
// certificate no browser trusts); its icon and console live at its PUBLIC address, which the public registries list
// states (public_url). Icons resolve against that; a peer whose public address is unknown shows the plain orb rather
// than a request to the wrong door (measured 2026-10-01: ERR_CERT_AUTHORITY_INVALID on every peer icon).
const publicUrlByName = ref<Record<string, string>>({})
async function loadPublicUrls(): Promise<void> {
  try {
    const r = await apiClient.get('/federation/registries')
    const rows: any[] = Array.isArray(r.data) ? r.data : (r.data?.items || [])
    const map: Record<string, string> = {}
    for (const row of rows) if (row?.registry_name && row?.public_url) map[row.registry_name] = row.public_url
    publicUrlByName.value = map
  } catch { /* icons fall back to the orb */ }
}
function peerIcon(peer: FederatedPeer): string | undefined {
  const icon = peer.visual?.icon_url
  if (!icon) return undefined
  if (/^https?:\/\//i.test(icon)) return icon
  if (peer.peer_type === 'local') return icon
  const pub = publicUrlByName.value[peer.name]
  return pub ? resolvePeerAsset(icon, pub) : undefined
}

// §FESUITE (the leave sweep): a page left during its first read starts no poll when it lands
const alive = useAlive()
onMounted(async () => {
  void loadPublicUrls()
  hydrateFromUrl()
  void loadVenueMap()
  await fetchTopology()
  if (!alive()) return
  // §pass62.1 — backfill LiveFederationFeed with last 20 federation events so
  // the feed renders with real history on first paint instead of looking empty.
  backfillFederationEvents()  // fire-and-forget; awaits internally
  pollTimer = setInterval(() => {
    if (hoverVisible.value) return  // sticky-hover gate
    fetchTopology()
  }, POLL_INTERVAL_MS)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (hoverShowTimer) clearTimeout(hoverShowTimer)
  if (_pushDebounce) clearTimeout(_pushDebounce)
})
</script>

<template>
  <div class="fdv"
    :class="{ 'fdv--stressed': showNetworkStress }"
    :style="{ '--fdv-chroma-intensity': networkStressLevel.toFixed(2) }">

    <!-- Hero strip -->
    <header class="fdv-hero">
      <div class="fdv-hero-title">
        <Icon name="mdi:source-branch" :size="20" />
        <h1>{{ t('federationDiscoveryView.hero.title') }}</h1>
        <span class="fdv-hero-count">{{ topology ? stats.total : '—' }} {{ topology && stats.total === 1 ? t('federationDiscoveryView.hero.registry') : t('federationDiscoveryView.hero.registries') }}</span>
        <span v-if="showNetworkStress" class="fdv-stress-pill">
          <Icon name="mdi:alert-octagon" :size="11" />
          {{ t('federationDiscoveryView.hero.stress', { drift: stats.drift, critical: stats.bundlesCritical }) }}
        </span>
      </div>
      <div class="fdv-hero-meta">
        <span class="fdv-meta-pill">
          <span class="fdv-meta-dot" :class="wsEvents.isConnected.value ? 'fdv-meta-dot--up' : 'fdv-meta-dot--down'"></span>
          {{ wsEvents.isConnected.value ? t('federationDiscoveryView.hero.live') : t('federationDiscoveryView.hero.polling') }}
        </span>
        <span v-if="lastFetchedAt" class="fdv-meta-time">{{ t('federationDiscoveryView.hero.refreshed', { age: humanizeAge((Date.now() - lastFetchedAt.getTime()) / 1000) }) }}</span>
        <button class="fdv-refresh-btn" :disabled="isLoading" @click="fetchTopology()" :title="t('federationDiscoveryView.hero.refreshNow')">
          <Icon name="mdi:refresh" :size="14" :class="{ 'fdv-spin': isLoading }" />
        </button>
      </div>
    </header>

    <!-- Tier chips -->
    <div class="fdv-chips">
      <button v-for="t_chip in (['all','frame','direct_peer','discovered','cloud_operator'] as TierFilter[])"
        :key="t_chip"
        class="fdv-chip" :class="{ 'fdv-chip--active': tierFilter === t_chip }"
        @click="tierFilter = t_chip">
        {{ t_chip === 'all' ? t('federationDiscoveryView.chips.all') : tierLabel(t_chip) }}
        <span class="fdv-chip-count">{{ !topology ? '—' : t_chip === 'all' ? stats.total : (stats.byType[t_chip] || 0) }}</span>
      </button>
      <div class="fdv-chips-spacer"></div>
      <button class="fdv-icon-btn"
        :class="{ 'fdv-icon-btn--active': viewMode === 'grid' }"
        @click="viewMode = 'grid'" :title="t('federationDiscoveryView.chips.gridView')">
        <Icon name="mdi:view-grid" :size="14" />
      </button>
      <button class="fdv-icon-btn"
        :class="{ 'fdv-icon-btn--active': viewMode === 'list' }"
        @click="viewMode = 'list'" :title="t('federationDiscoveryView.chips.listView')">
        <Icon name="mdi:format-list-bulleted" :size="14" />
      </button>
      <button v-if="vp.isMobile.value" class="fdv-icon-btn" @click="mobileFiltersOpen = !mobileFiltersOpen" :title="t('federationDiscoveryView.chips.filters')">
        <Icon name="mdi:tune" :size="14" />
      </button>
    </div>

    <!-- Search bar -->
    <div class="fdv-search">
      <Icon name="mdi:magnify" :size="16" class="fdv-search-icon" />
      <input v-model="search" type="search"
        class="fdv-search-input"
        :placeholder="t('federationDiscoveryView.search.placeholder')" />
      <button v-if="search" class="fdv-search-clear" @click="search = ''" :title="t('federationDiscoveryView.search.clear')">
        <Icon name="mdi:close" :size="12" />
      </button>
    </div>

    <!-- Main grid: sidebar + results + live feed -->
    <div class="fdv-main">

      <!-- Mobile filter backdrop (tap to close) -->
      <div v-if="vp.isMobile.value && mobileFiltersOpen" class="fdv-sidebar-backdrop" @click="mobileFiltersOpen = false"></div>

      <!-- Sidebar filters (desktop) / Bottom sheet (mobile) -->
      <aside class="fdv-sidebar"
        :class="{ 'fdv-sidebar--mobile-open': mobileFiltersOpen, 'fdv-sidebar--mobile': vp.isMobile.value }">
        <div v-if="vp.isMobile.value" class="fdv-sidebar-mobile-head">
          <h3>{{ t('federationDiscoveryView.sidebar.filtersTitle') }}</h3>
          <button class="fdv-icon-btn" @click="mobileFiltersOpen = false" :title="t('federationDiscoveryView.sidebar.close')">
            <Icon name="mdi:close" :size="14" />
          </button>
        </div>
        <!-- Quick toggles -->
        <section class="fdv-sf">
          <h4 class="fdv-sf-h">{{ t('federationDiscoveryView.sidebar.quickToggles') }}</h4>
          <label class="fdv-check"><input type="checkbox" v-model="showOnlyDrift" /> {{ t('federationDiscoveryView.sidebar.driftOnly') }}</label>
          <label class="fdv-check"><input type="checkbox" v-model="showOnlySigned" /> {{ t('federationDiscoveryView.sidebar.signatureVerified') }}</label>
          <label class="fdv-check"><input type="checkbox" v-model="showOnlySovereignPinned" /> {{ t('federationDiscoveryView.sidebar.sovereignPinned') }}</label>
          <label class="fdv-check"><input type="checkbox" v-model="showOnlyCrossFrame" /> {{ t('federationDiscoveryView.sidebar.crossFrameOnly') }}</label>
          <label class="fdv-check"><input type="checkbox" v-model="showInactive" /> {{ t('federationDiscoveryView.sidebar.includeInactive') }}</label>
        </section>
        <!-- Trust domain group -->
        <section v-if="trustDomains.length > 0" class="fdv-sf">
          <h4 class="fdv-sf-h">{{ t('federationDiscoveryView.sidebar.trustDomain') }}</h4>
          <label class="fdv-check"><input type="radio" name="td" value="" v-model="trustDomainFilter" /> {{ t('federationDiscoveryView.sidebar.all') }}</label>
          <label v-for="td in trustDomains" :key="td" class="fdv-check">
            <input type="radio" name="td" :value="td" v-model="trustDomainFilter" /> <span class="fdv-mono">{{ td }}</span>
          </label>
        </section>
        <!-- Bundle freshness -->
        <section class="fdv-sf">
          <h4 class="fdv-sf-h">{{ t('federationDiscoveryView.sidebar.bundleFreshness') }}</h4>
          <label class="fdv-check"><input type="radio" name="bf" value="all" v-model="bundleFreshnessFilter" /> {{ t('federationDiscoveryView.sidebar.all') }}</label>
          <label class="fdv-check"><input type="radio" name="bf" value="fresh" v-model="bundleFreshnessFilter" /> {{ t('federationDiscoveryView.sidebar.fresh', { count: topology ? stats.bundlesFresh : '—' }) }}</label>
          <label class="fdv-check"><input type="radio" name="bf" value="overdue" v-model="bundleFreshnessFilter" /> {{ t('federationDiscoveryView.sidebar.overdue') }}</label>
          <label class="fdv-check"><input type="radio" name="bf" value="critical" v-model="bundleFreshnessFilter" /> {{ t('federationDiscoveryView.sidebar.critical', { count: topology ? stats.bundlesCritical : '—' }) }}</label>
          <label class="fdv-check"><input type="radio" name="bf" value="unknown" v-model="bundleFreshnessFilter" /> {{ t('federationDiscoveryView.sidebar.unknown') }}</label>
        </section>
        <!-- Fee range -->
        <section class="fdv-sf">
          <h4 class="fdv-sf-h">{{ t('federationDiscoveryView.sidebar.maxFees') }}</h4>
          <label class="fdv-slider">
            {{ t('federationDiscoveryView.sidebar.intra') }} <strong>{{ feesIntraMax.toFixed(1) }}%</strong>
            <input type="range" min="0" max="5" step="0.1" v-model.number="feesIntraMax" />
          </label>
          <label class="fdv-slider">
            {{ t('federationDiscoveryView.sidebar.cross') }} <strong>{{ feesCrossMax.toFixed(1) }}%</strong>
            <input type="range" min="0" max="5" step="0.1" v-model.number="feesCrossMax" />
          </label>
        </section>
        <!-- Sort -->
        <section class="fdv-sf">
          <h4 class="fdv-sf-h">{{ t('federationDiscoveryView.sidebar.sort') }}</h4>
          <select v-model="sortKey" class="fdv-select" :aria-label="t('federationDiscoveryView.sidebar.sort')">
            <option value="name">{{ t('federationDiscoveryView.sort.name') }}</option>
            <option value="hop">{{ t('federationDiscoveryView.sort.hop') }}</option>
            <option value="last_synced">{{ t('federationDiscoveryView.sort.lastSynced') }}</option>
            <option value="bayesian">{{ t('federationDiscoveryView.sort.bayesian') }}</option>
            <option value="interactions">{{ t('federationDiscoveryView.sort.interactions') }}</option>
            <option value="fees_intra">{{ t('federationDiscoveryView.sort.feesIntra') }}</option>
            <option value="fees_cross">{{ t('federationDiscoveryView.sort.feesCross') }}</option>
            <option value="random">{{ t('federationDiscoveryView.sort.random') }}</option>
          </select>
          <button class="fdv-sort-dir" @click="sortDesc = !sortDesc">
            {{ sortDesc ? t('federationDiscoveryView.sidebar.sortDesc') : t('federationDiscoveryView.sidebar.sortAsc') }}
          </button>
        </section>
        <button v-if="hasActiveFilter" class="fdv-clear-btn" @click="clearAllFilters">
          <Icon name="mdi:close" :size="12" /> {{ t('federationDiscoveryView.sidebar.clearFilters') }}
        </button>
      </aside>

      <!-- Results -->
      <main class="fdv-results">
        <!-- Loading -->
        <div v-if="isLoading && !topology" class="fdv-loading">
          <div class="fdv-spinner"></div>
          <p>{{ t('federationDiscoveryView.results.loading') }}</p>
        </div>
        <!-- Error -->
        <div v-else-if="error" class="fdv-error">
          <Icon name="mdi:alert" :size="32" />
          <p>{{ error }}</p>
          <button @click="fetchTopology()">{{ t('federationDiscoveryView.results.retry') }}</button>
        </div>
        <!-- Empty (filtered to nothing) -->
        <div v-else-if="hasActiveFilter && filteredPeers.length === 0" class="fdv-empty">
          <Icon name="mdi:magnify" :size="40" />
          <h3>{{ t('federationDiscoveryView.results.zeroResults') }}</h3>
          <p>{{ allPeersWithLocal.length }} {{ allPeersWithLocal.length === 1 ? t('federationDiscoveryView.hero.registry') : t('federationDiscoveryView.hero.registries') }} {{ t('federationDiscoveryView.results.noMatch') }}</p>
          <button class="fdv-empty-btn" @click="clearAllFilters">{{ t('federationDiscoveryView.sidebar.clearFilters') }}</button>
        </div>
        <!-- Empty (no peers at all — extremely unusual) -->
        <div v-else-if="filteredPeers.length === 0" class="fdv-empty">
          <Icon name="mdi:source-branch" :size="40" />
          <h3>{{ t('federationDiscoveryView.results.noPeersTitle') }}</h3>
          <p>{{ t('federationDiscoveryView.results.noPeersBody') }}</p>
        </div>
        <!-- Grid -->
        <div v-else-if="viewMode === 'grid'" class="fdv-grid">
          <article v-for="peer in filteredPeers" :key="peer.id"
            class="fdv-card" :class="{ 'fdv-card--local': peer.peer_type === 'local', 'fdv-card--drift': peer.has_drift }"
            tabindex="0"
            @click="openDrawer(peer)"
            @keyup.enter="openDrawer(peer)"
            @mouseenter="onCardMouseEnter(peer, $event)"
            @mousemove="onCardMouseMove($event)"
            @mouseleave="onCardMouseLeave">
            <!-- §pass62.2 (2026-05-21) — REPLACED the SVG/PeerOrb wrapper with a
                 direct FlareEncirclement / UserAvatar / colored-orb fallback chain.
                 Same identity treatment as PeerHoverPopover (which Commander flagged
                 as "good look"), but at size="md" instead of xs so flares + overlays
                 are actually visible. -->
            <div class="fdv-card-head">
              <div class="fdv-card-avatar">
                <!-- 🔴 findings row 192 — THE PICTURE WENT TO A PROP THAT DOES NOT EXIST.
                     `UserAvatar` declares `avatarUrl`; this call site passed `:src`, which Vue
                     silently turns into a fallthrough ATTRIBUTE on the root element, so the
                     component rendered its initials fallback and NO <img> was ever created —
                     measured, zero <img> elements on the whole page. `:size="56"` was the same
                     mistake twice: the prop is a preset ('xs'|'sm'|'md'|'lg'|'xl'), and the
                     comment right above this block already said the intent was md. Nothing
                     errored, the API was correct, and the logo could never load. This was the
                     ONLY one of ~20 UserAvatar call sites passing `:src` (censused).
                     The flare branch now carries the icon too, because he asked for what the
                     AgentWorld modal does — flares AND logo, not one or the other — and that is
                     exactly how `RegistryHoverCard` already does it. -->
                <FlareEncirclement
                  v-if="flareVariantFor(peer)"
                  :tier="flareTierFor(peer)"
                  :variant="flareVariantFor(peer) || undefined"
                  :overlay="flareOverlayFor(peer) || undefined"
                  :avatar-url="peerIcon(peer) || null"
                  size="md"
                />
                <UserAvatar
                  v-else-if="peerIcon(peer)"
                  :avatar-url="peerIcon(peer)"
                  :display-name="peer.name || null"
                  :title="peer.name || t('federationDiscoveryView.card.peerAlt')"
                  size="md"
                />
                <div v-else class="fdv-card-orb-plain" :style="plainOrbStyle(peer)"></div>
              </div>
              <div class="fdv-card-title-wrap">
                <strong class="fdv-card-name">{{ peer.name }}</strong>
                <div class="fdv-card-sub">
                  <span class="fdv-tier-pill" :class="`fdv-tier-pill--${peer.peer_type}`">{{ tierLabel(peer.peer_type) }}</span>
                  <!-- §V0064 P2: live venue chip from the federation-tickers aggregate; click → Discover Stocks filtered to that venue -->
                  <button v-if="venueCcy(peer.name)" class="fdv-xchip fdv-xchip--link" :title="'AGORA market live, trades in ' + venueCcy(peer.name) + ' · open AGORA Listings'" @click.stop="openVenueStocks(peer.name)">
                    <Icon name="mdi:chart-candlestick" /> AGORA · {{ venueCcy(peer.name) }}
                  </button>
                  <!-- §pass62.6 (2026-05-21) — Tree-walk hop derivation matches Network tab. -->
                  <span v-if="peer.peer_type !== 'local'" class="fdv-hop" :title="chainPathFor(peer).join(' → ')">{{ t('federationDiscoveryView.card.hop', { n: displayHopFor(peer) }) }}</span>
                  <span v-if="parentNameFor(peer)" class="fdv-via" :title="chainPathFor(peer).join(' → ')">{{ t('federationDiscoveryView.card.via', { name: parentNameFor(peer) }) }}</span>
                </div>
              </div>
            </div>
            <!-- §TRUSTWIRE (2026-09-10) — OUR observed trust in this peer, which the page could
                 already SORT by and never showed. It is deliberately not on the peer's registry
                 card: a card is a signed self-description, and this is our opinion of them, held
                 by us, derived from our own settled interactions. It says which of the three
                 states it is in, because "unmeasured" and "we distrust you" must never look alike. -->
            <!-- the local registry's OWN row: not a self-score (there is no such thing) but the
                 ledger of opinions we hold about others. -->
            <div v-if="peer.peer_type === 'local' && localTrust" class="fdv-card-row" data-testid="fdv-local-trust">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.ledgerLabel', 'Our ledger') }}</span>
              <span class="fdv-mono" :class="localTrust!.cls" :title="localTrust!.hint">
                {{ localTrust!.text }}
              </span>
            </div>
            <div v-if="peer.peer_type !== 'local' && peerTrust(peer)" class="fdv-card-row" data-testid="fdv-peer-trust">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.trustLabel', 'Our trust') }}</span>
              <span class="fdv-mono" :class="peerTrust(peer)!.cls" :title="peerTrust(peer)!.hint">
                {{ peerTrust(peer)!.text }}
              </span>
            </div>
            <!-- Trust domain row -->
            <div v-if="peer.trust_domain" class="fdv-card-row fdv-card-row--mono">
              <Icon name="mdi:shield-account" :size="11" />
              {{ peer.trust_domain }}
            </div>
            <!-- Fees -->
            <div v-if="peer.fees_summary" class="fdv-card-row">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.feesLabel') }}</span>
              <span class="fdv-mono">
                {{ t('federationDiscoveryView.card.intra') }} {{ (peer.fees_summary.intra_registry ?? 0).toFixed(2) }}% ·
                {{ t('federationDiscoveryView.card.cross') }} {{ (peer.fees_summary.cross_registry ?? 0).toFixed(2) }}%
              </span>
            </div>
            <!-- ETag + signature -->
            <div class="fdv-card-row">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.cardLabel') }}</span>
              <span v-if="peerEtagShort(peer)" class="fdv-mono fdv-etag">{{ peerEtagShort(peer) }}</span>
              <span v-else class="fdv-mono fdv-mono--muted">{{ t('federationDiscoveryView.card.noCard') }}</span>
              <span :class="['fdv-sigpill', `fdv-sigpill--${peer.card_signature_verified === true ? 'verified' : peer.card_signature_verified === false ? 'unsigned' : 'unknown'}`]">
                <Icon :name="peer.card_signature_verified === true ? 'mdi:shield-check' : peer.card_signature_verified === false ? 'mdi:shield-off-outline' : 'mdi:help-circle-outline'" :size="10" />
                {{ peer.card_signature_verified === true ? t('federationDiscoveryView.card.sigVerified') : peer.card_signature_verified === false ? t('federationDiscoveryView.card.sigUnsigned') : t('federationDiscoveryView.card.sigUnknown') }}
              </span>
            </div>
            <!-- Bundle freshness -->
            <div v-if="peer.bundle_freshness" class="fdv-card-row">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.bundleLabel') }}</span>
              <span class="fdv-mono" :class="peer.bundle_freshness.refresh_critical ? 'fdv-mono--danger' : peer.bundle_freshness.refresh_overdue ? 'fdv-mono--warn' : 'fdv-mono--ok'">
                {{ t('federationDiscoveryView.card.bundleAge', { age: humanizeAge(peer.bundle_freshness.age_seconds) }) }}
              </span>
            </div>
            <!-- Drift indicator -->
            <div v-if="peer.has_drift" class="fdv-card-row fdv-card-drift">
              <Icon name="mdi:alert-octagon" :size="11" />
              <span>{{ t((peer.drift_flags || []).length === 1 ? 'federationDiscoveryView.card.driftFlagOne' : 'federationDiscoveryView.card.driftFlagMany', { count: (peer.drift_flags || []).length }) }}</span>
            </div>
            <!-- Sovereign tag -->
            <div v-if="peer.visual?.sovereign_variant" class="fdv-card-row">
              <span class="fdv-card-label">{{ t('federationDiscoveryView.card.sovLabel') }}</span>
              <span class="fdv-mono fdv-mono--accent">{{ peer.visual.sovereign_variant }}</span>
            </div>
            <!-- CTA -->
            <button class="fdv-card-cta" @click.stop="openDrawer(peer)">
              {{ t('federationDiscoveryView.card.detail') }}
              <Icon name="mdi:chevron-right" :size="12" />
            </button>
          </article>
        </div>
        <!-- List -->
        <div v-else class="fdv-list">
          <article v-for="peer in filteredPeers" :key="peer.id"
            class="fdv-row" :class="{ 'fdv-row--local': peer.peer_type === 'local' }"
            tabindex="0"
            @click="openDrawer(peer)"
            @keyup.enter="openDrawer(peer)"
            @mouseenter="onCardMouseEnter(peer, $event)"
            @mousemove="onCardMouseMove($event)"
            @mouseleave="onCardMouseLeave">
            <svg width="44" height="44" viewBox="0 0 44 44" overflow="visible" class="fdv-row-orb-svg">
              <g :transform="`translate(22, 22)`">
                <PeerOrb :peer="peer" :radius="14" :is-local="peer.peer_type === 'local'" :tier="peer.peer_type" />
              </g>
            </svg>
            <div class="fdv-row-meta">
              <strong>{{ peer.name }}</strong>
              <div class="fdv-row-sub">
                <span class="fdv-tier-pill" :class="`fdv-tier-pill--${peer.peer_type}`">{{ tierLabel(peer.peer_type) }}</span>
                <!-- §pass62.6 — tree-walk hop, same source of truth as Network tab -->
                <span v-if="peer.peer_type !== 'local'" class="fdv-hop" :title="chainPathFor(peer).join(' → ')">{{ t('federationDiscoveryView.card.hop', { n: displayHopFor(peer) }) }}</span>
                <span v-if="parentNameFor(peer)" class="fdv-via" :title="chainPathFor(peer).join(' → ')">{{ t('federationDiscoveryView.card.via', { name: parentNameFor(peer) }) }}</span>
                <span v-if="peer.trust_domain" class="fdv-mono fdv-mono--muted">{{ peer.trust_domain }}</span>
              </div>
            </div>
            <div class="fdv-row-fees">
              <span v-if="peer.fees_summary" class="fdv-mono fdv-mono--small">
                {{ (peer.fees_summary.intra_registry ?? 0).toFixed(2) }}% / {{ (peer.fees_summary.cross_registry ?? 0).toFixed(2) }}%
              </span>
            </div>
            <span :class="['fdv-sigpill', `fdv-sigpill--${peer.card_signature_verified === true ? 'verified' : peer.card_signature_verified === false ? 'unsigned' : 'unknown'}`]">
              {{ peer.card_signature_verified === true ? '✓' : peer.card_signature_verified === false ? '✗' : '?' }}
            </span>
            <Icon name="mdi:chevron-right" :size="14" class="fdv-row-arrow" />
          </article>
        </div>
      </main>

      <!-- Live feed (desktop only, mobile hides via CSS in component) -->
      <LiveFederationFeed
        :events="liveFeedEvents"
        :collapsed="liveFeedCollapsed"
        :title="t('federationDiscoveryView.liveFeed.title')"
        :last-event-iso="lastFederationEventIso"
        :ws-connected="wsEvents.isConnected.value === true"
        @toggle="toggleLiveFeed"
        @highlight="onFeedHighlight"
      />
    </div>

    <!-- §pass62 Pass 5 — Full 6-tab shared drawer (Local Registry case included) -->
    <!-- §pass62.6 — pass peersById + localName so drawer derives tree-walk hop -->
    <PeerDetailDrawer
      :open="drawerOpen"
      :peer="drawerPeer"
      :peers-by-id="peersById"
      :local-name="localRegistry?.name || t('federationDiscoveryView.localFallback')"
      @close="closeDrawer"
    />

    <!-- Hover popover (Teleported to body inside component) -->
    <PeerHoverPopover
      :peer="hoverPeer"
      :px="hoverX"
      :py="hoverY"
      :visible="hoverVisible"
      :peers-by-id="peersById"
      :local-name="localRegistry?.name || t('federationDiscoveryView.localFallback')"
    />
  </div>
</template>

<style scoped>
/* §V0064 P2 — live venue chip */
.fdv-xchip { display: inline-flex; align-items: center; gap: 4px; font-size: 8.5px; letter-spacing: 0.1em; font-weight: 800; font-family: ui-monospace, monospace; color: #10b981; border: 1px solid rgba(16, 185, 129, 0.45); border-radius: 99px; padding: 2px 8px; }
.fdv-xchip :deep(svg) { width: 10px; height: 10px; }
.fdv-xchip--link { cursor: pointer; background: transparent; transition: background 0.15s, box-shadow 0.15s; }
.fdv-xchip--link:hover { background: rgba(16, 185, 129, 0.12); box-shadow: 0 0 10px rgba(16, 185, 129, 0.3); }

.fdv {
  padding: 20px 24px;
  min-height: 100%;
  position: relative;
  color: var(--nc-text-primary, #e8eaed);
}

/* §pass62 stress signaling — mirror §pass61 Pass 7 chromatic aberration pattern */
.fdv--stressed {
  filter:
    drop-shadow(calc(var(--fdv-chroma-intensity, 0) *  1.5px) 0 0 rgba(255, 51, 102, calc(var(--fdv-chroma-intensity, 0) * 0.36)))
    drop-shadow(calc(var(--fdv-chroma-intensity, 0) * -1.5px) 0 0 rgba(0, 210, 210, calc(var(--fdv-chroma-intensity, 0) * 0.32)));
  transition: filter 900ms cubic-bezier(0.4, 0, 0.2, 1);
}
@media (prefers-reduced-motion: reduce) { .fdv--stressed { filter: none; transition: none; } }

/* Hero */
.fdv-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}
.fdv-hero-title { display: flex; align-items: center; gap: 10px; }
.fdv-hero-title h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.fdv-hero-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
  color: var(--nc-primary-bright, #00e5e5);
  padding: 2px 7px;
  border-radius: 3px;
}
.fdv-stress-pill {
  display: inline-flex; align-items: center; gap: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.62rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  background: rgba(255, 51, 102, 0.12);
  color: var(--nc-danger, #ff3366);
  border: 1px solid rgba(255, 51, 102, 0.35);
  padding: 3px 8px;
  border-radius: 3px;
  animation: fdv-stress-pulse 1.6s ease-in-out infinite;
}
@keyframes fdv-stress-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 51, 102, 0); }
  50%      { box-shadow: 0 0 0 6px rgba(255, 51, 102, 0.08); }
}
@media (prefers-reduced-motion: reduce) { .fdv-stress-pill { animation: none } }
.fdv-hero-meta {
  display: flex; align-items: center; gap: 10px;
  font-size: 0.72rem;
  color: var(--nc-text-muted, #94a3b8);
}
.fdv-meta-pill {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 2px 7px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.62rem;
}
.fdv-meta-dot {
  width: 7px; height: 7px; border-radius: 50%;
}
.fdv-meta-dot--up { background: var(--nc-success-bright, #4ade80); box-shadow: 0 0 6px rgba(0,255,136,0.5); }
.fdv-meta-dot--down { background: var(--nc-text-muted, #94a3b8); }
.fdv-meta-time { font-family: 'JetBrains Mono', monospace; }
.fdv-refresh-btn {
  background: transparent;
  border: 1px solid rgba(255,255,255,0.1);
  color: var(--nc-text-muted, #94a3b8);
  padding: 4px 8px;
  border-radius: 3px;
  cursor: pointer;
  transition: all 200ms;
}
.fdv-refresh-btn:hover {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3);
  color: var(--nc-primary-bright, #00e5e5);
}
.fdv-refresh-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fdv-spin { animation: fdv-spin 0.8s linear infinite; }
@keyframes fdv-spin { from { transform: rotate(0deg) } to { transform: rotate(360deg) } }

/* Chips */
.fdv-chips {
  display: flex; align-items: center; gap: 6px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.fdv-chip {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: rgba(255, 255, 255, 0.03);
  color: var(--nc-text-muted, #94a3b8);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  cursor: pointer;
  transition: all 180ms;
  font-family: 'JetBrains Mono', monospace;
}
.fdv-chip:hover { color: var(--nc-text-primary, #e8eaed); border-color: rgba(255, 255, 255, 0.15); }
.fdv-chip--active {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35);
  color: var(--nc-primary-bright, #00e5e5);
}
.fdv-chip-count {
  font-size: 0.6rem;
  background: rgba(255,255,255,0.05);
  padding: 0 4px;
  border-radius: 2px;
}
.fdv-chips-spacer { flex: 1; }

.fdv-icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 3px;
  color: var(--nc-text-muted, #94a3b8);
  cursor: pointer;
  transition: all 180ms;
}
.fdv-icon-btn:hover { color: var(--nc-primary-bright, #00e5e5); border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); }
.fdv-icon-btn--active {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.4);
  color: var(--nc-primary-bright, #00e5e5);
}

/* Search bar */
.fdv-search {
  display: flex; align-items: center; gap: 8px;
  background: var(--nc-surface, #131825);
  border: 1px solid var(--nc-border, #2a2f3e);
  border-radius: 4px;
  padding: 6px 10px;
  margin-bottom: 14px;
  transition: border-color 200ms;
}
.fdv-search:focus-within { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.5); }
.fdv-search-icon { color: var(--nc-text-muted, #94a3b8); flex-shrink: 0; }
.fdv-search-input {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--nc-text-primary, #e8eaed);
  font-size: 0.85rem;
  outline: none;
}
.fdv-search-input::placeholder { color: var(--nc-text-muted, #94a3b8); }
.fdv-search-clear {
  background: transparent; border: none;
  color: var(--nc-text-muted, #94a3b8); cursor: pointer;
  padding: 2px 4px;
}
.fdv-search-clear:hover { color: var(--nc-danger, #ff3366); }

/* Main layout */
.fdv-main {
  display: grid;
  grid-template-columns: 240px 1fr 260px;
  gap: 18px;
  align-items: start;
}
@media (max-width: 1024px) {
  .fdv-main { grid-template-columns: 1fr; }
}

/* §pass62.2 (2026-05-21) — LiveFederationFeed default CSS is position:absolute
   (designed for Federation.vue Network tab where it overlays the SVG graph).
   In FederationDiscovery we want it as a 3rd grid column instead — sticky like
   the filter sidebar. Deep override scopes only to FD without affecting the
   shared component's default behavior on /federation. */
.fdv-main :deep(.lff) {
  position: sticky;
  top: 14px;
  right: auto;
  width: 260px;
  max-height: calc(100vh - 80px);
  z-index: 4;
}
.fdv-main :deep(.lff--collapsed) {
  width: 36px;
}
@media (max-width: 1024px) {
  .fdv-main :deep(.lff) { display: none; }
}

/* Sidebar */
.fdv-sidebar {
  /* §2026-06-29 polish — was a flat 4px-square panel ("wack"); now matches the
     frosted/rounded design language of the cards + search bar elsewhere. */
  background:
    linear-gradient(168deg, rgba(255,255,255,0.05), rgba(255,255,255,0.012) 55%, transparent 100%),
    var(--nc-surface, #131825);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 12px;
  padding: 16px;
  position: sticky;
  top: 14px;
  max-height: calc(100vh - 80px);
  overflow-y: auto;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), 0 16px 40px -28px rgba(0,0,0,0.9);
}
@media (max-width: 1024px) {
  .fdv-sidebar--mobile {
    position: fixed;
    top: auto;            /* anchor to bottom — base .fdv-sidebar sets top:14px, which on a fixed box pins a near-fullscreen top panel that bottom:-100% cannot hide */
    bottom: -100%;
    left: 0; right: 0;
    z-index: 9000;
    border-radius: 12px 12px 0 0;
    max-height: 80vh;
    transition: bottom 240ms cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 0 -8px 32px rgba(0,0,0,0.6);
  }
  .fdv-sidebar--mobile-open {
    bottom: 0;
  }
}
/* Mobile filter sheet backdrop — only rendered (v-if) on mobile when open */
.fdv-sidebar-backdrop {
  position: fixed;
  inset: 0;
  z-index: 8999;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  animation: fdv-backdrop-in 180ms ease;
}
@keyframes fdv-backdrop-in { from { opacity: 0; } to { opacity: 1; } }
.fdv-sidebar-mobile-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.fdv-sidebar-mobile-head h3 { margin: 0; font-size: 1rem; }

.fdv-sf {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
}
.fdv-sf:last-child { border-bottom: none; }
.fdv-sf-h {
  margin: 0 0 9px;
  font-size: 0.64rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted, #aab6c8);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 7px;
}
.fdv-sf-h::before {
  content: '';
  width: 3px;
  height: 11px;
  border-radius: 2px;
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.9), rgba(var(--nc-primary-rgb), 0.28));
  flex-shrink: 0;
}
.fdv-check {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.78rem;
  color: var(--nc-text-primary, #e8eaed);
  padding: 5px 6px;
  margin: 0 -6px;
  border-radius: 7px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.fdv-check:hover { background: rgba(var(--nc-primary-rgb), 0.07); color: #fff; }
.fdv-check input { accent-color: var(--nc-primary, #00d2d2); cursor: pointer; }
.fdv-slider {
  display: flex; flex-direction: column;
  font-size: 0.72rem;
  color: var(--nc-text-muted, #94a3b8);
  margin-bottom: 8px;
  gap: 4px;
}
.fdv-slider strong { color: var(--nc-primary-bright, #00e5e5); font-family: 'JetBrains Mono', monospace; }
.fdv-slider input[type="range"] { width: 100%; accent-color: var(--nc-primary, #00d2d2); }
.fdv-select {
  width: 100%;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  color: var(--nc-text-primary, #e8eaed);
  padding: 5px 7px;
  border-radius: 3px;
  font-size: 0.78rem;
}
.fdv-sort-dir {
  margin-top: 6px;
  width: 100%;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.08);
  color: var(--nc-text-muted, #94a3b8);
  padding: 4px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 0.72rem;
  font-family: 'JetBrains Mono', monospace;
}
.fdv-sort-dir:hover { color: var(--nc-primary-bright, #00e5e5); }
.fdv-clear-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent;
  border: 1px dashed rgba(255, 51, 102, 0.3);
  color: var(--nc-danger, #ff3366);
  padding: 6px 10px;
  border-radius: 3px;
  font-size: 0.72rem;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-top: 8px;
  width: 100%;
  justify-content: center;
}

/* Results */
.fdv-results { min-width: 0; }

.fdv-loading, .fdv-error, .fdv-empty {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 60px 20px;
  text-align: center;
  color: var(--nc-text-muted, #94a3b8);
}
.fdv-empty h3 { margin: 0; color: var(--nc-text-primary, #e8eaed); font-size: 1.15rem; }
.fdv-empty p { margin: 0; font-size: 0.85rem; max-width: 380px; }
.fdv-empty-btn, .fdv-error button {
  margin-top: 6px;
  padding: 6px 16px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3);
  color: var(--nc-primary-bright, #00e5e5);
  border-radius: 3px;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 0.72rem;
}
.fdv-spinner {
  width: 36px; height: 36px;
  border: 3px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
  border-top-color: var(--nc-primary, #00d2d2);
  border-radius: 50%;
  animation: fdv-spin 0.9s linear infinite;
}

/* Grid */
.fdv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.fdv-card {
  background: var(--nc-surface, #131825);
  border: 1px solid var(--nc-border-subtle, rgba(255, 255, 255, 0.06));
  border-radius: 6px;
  padding: 14px;
  cursor: pointer;
  transition: all 220ms cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.fdv-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: var(--nc-hologram, linear-gradient(90deg, #00e5e5 0%, #00ff88 50%, #00e5e5 100%));
  background-size: 200% 100%;
  animation: fdv-card-holo 3.2s linear infinite;
  opacity: 0.5;
}
@keyframes fdv-card-holo { 0% { background-position: 0% 50% } 100% { background-position: 200% 50% } }
@media (prefers-reduced-motion: reduce) { .fdv-card::before { animation: none } }
.fdv-card:hover, .fdv-card:focus {
  transform: translateY(-2px);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.4);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.1);
  outline: none;
}
.fdv-card--local { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.5); }
.fdv-card--drift { border-color: rgba(255, 51, 102, 0.45); }

.fdv-card-head {
  display: flex; align-items: center; gap: 14px;
  margin-bottom: 6px;
}
.fdv-card-orb-svg { flex-shrink: 0; }
/* §pass62.2 — card avatar slot (FlareEncirclement / UserAvatar / plain orb).
   Sized to match FlareEncirclement size="md" (48px) plus breathing room. */
.fdv-card-avatar {
  flex-shrink: 0;
  width: 56px; height: 56px;
  display: flex; align-items: center; justify-content: center;
}
.fdv-card-orb-plain {
  width: 38px; height: 38px;
  border-radius: 50%;
  /* style binding sets background + boxShadow inline */
  position: relative;
}
.fdv-card-orb-plain::after {
  /* subtle inner highlight to match FlareEncirclement's core specular */
  content: '';
  position: absolute;
  top: 5px; left: 5px;
  width: 12px; height: 12px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.22);
  filter: blur(2px);
}
.fdv-card-title-wrap { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.fdv-card-name {
  font-size: 0.95rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.fdv-card-sub { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.fdv-tier-pill {
  display: inline-flex; align-items: center;
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 1px 5px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.fdv-tier-pill--frame { color: #c084fc; border-color: rgba(168, 85, 247, 0.35); }
.fdv-tier-pill--direct_peer { color: var(--nc-primary-bright, #00e5e5); border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35); }
.fdv-tier-pill--discovered { color: #fbbf24; border-color: rgba(245, 158, 11, 0.35); }
.fdv-tier-pill--cloud_operator { color: #4ade80; border-color: rgba(34, 197, 94, 0.35); }
.fdv-tier-pill--local { color: #fff; border-color: rgba(255, 255, 255, 0.3); }

.fdv-trust--good { color: var(--nc-success, #34d399); }
.fdv-trust--mid { color: var(--nc-warning, #fbbf24); }
.fdv-trust--low { color: var(--nc-danger, #f87171); }
/* UNMEASURED is not a bad score: it must not borrow the colour of one. */
.fdv-trust--unmeasured { color: var(--nc-text-muted, #94a3b8); font-style: italic; }
.fdv-hop {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  color: var(--nc-text-muted, #94a3b8);
}

/* §pass62.6 (2026-05-21) — "via <parent>" pill. Echoes the Network tab's
   tree-walk derivation in card form. Tooltip shows the full chain path. */
.fdv-via {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem;
  color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.78);
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  cursor: help;
}

.fdv-card-row {
  display: flex; align-items: center; gap: 6px;
  font-size: 0.72rem;
  min-height: 18px;
}
.fdv-card-row--mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.66rem;
  color: var(--nc-text-muted, #94a3b8);
  word-break: break-all;
}
.fdv-card-label {
  font-size: 0.58rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--nc-text-muted, #94a3b8);
  min-width: 42px;
  font-weight: 700;
}
.fdv-mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem;
}
.fdv-mono--small { font-size: 0.62rem; }
.fdv-mono--muted { color: var(--nc-text-muted, #94a3b8); }
.fdv-mono--accent { color: var(--nc-primary-bright, #00e5e5); text-transform: uppercase; letter-spacing: 0.06em; font-size: 0.66rem; }
.fdv-mono--ok { color: var(--nc-success-bright, #4ade80); }
.fdv-mono--warn { color: var(--nc-warning, #ff9500); }
.fdv-mono--danger { color: var(--nc-danger, #ff3366); }
.fdv-etag {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--nc-primary-bright, #00e5e5);
}
.fdv-sigpill {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.58rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid;
}
.fdv-sigpill--verified { color: var(--nc-success-bright, #4ade80); border-color: rgba(74, 222, 128, 0.35); background: rgba(0, 255, 136, 0.06); }
.fdv-sigpill--unsigned { color: var(--nc-text-muted, #94a3b8); border-color: rgba(255, 255, 255, 0.1); }
.fdv-sigpill--unknown { color: var(--nc-text-muted, #94a3b8); border-color: rgba(255, 255, 255, 0.08); }

.fdv-card-drift {
  color: var(--nc-danger, #ff3366);
  font-weight: 600;
}

.fdv-card-cta {
  margin-top: auto;
  display: inline-flex; align-items: center; justify-content: center; gap: 4px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
  color: var(--nc-primary-bright, #00e5e5);
  padding: 5px 10px;
  border-radius: 3px;
  font-size: 0.72rem;
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  transition: all 180ms;
}
.fdv-card-cta:hover {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.4);
}

/* List view */
.fdv-list { display: flex; flex-direction: column; gap: 6px; }
.fdv-row {
  display: grid;
  grid-template-columns: 50px 1fr auto auto auto;
  align-items: center;
  gap: 12px;
  background: var(--nc-surface, #131825);
  border: 1px solid rgba(255, 255, 255, 0.04);
  border-radius: 4px;
  padding: 8px 12px;
  cursor: pointer;
  transition: all 180ms;
}
.fdv-row:hover, .fdv-row:focus {
  background: var(--nc-elevated, #181f2e);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  outline: none;
}
.fdv-row--local { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35); }
.fdv-row-orb-svg { flex-shrink: 0; }
.fdv-row-meta { min-width: 0; }
.fdv-row-meta strong { font-size: 0.88rem; }
.fdv-row-sub { display: flex; align-items: center; gap: 8px; margin-top: 3px; flex-wrap: wrap; }
.fdv-row-fees { font-family: 'JetBrains Mono', monospace; color: var(--nc-text-muted, #94a3b8); }
.fdv-row-arrow { color: var(--nc-text-muted, #94a3b8); flex-shrink: 0; }

/* Drawer (Pass 1 stub — Pass 5 will replace) */
.fdv-drawer-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: flex; justify-content: flex-end;
}
.fdv-drawer {
  width: min(560px, 100%);
  height: 100%;
  background: var(--nc-overlay, #1d2438);
  border-left: 1px solid var(--nc-border-strong, #343a4d);
  display: flex; flex-direction: column;
  animation: fdv-drawer-in 240ms cubic-bezier(0.4, 0, 0.2, 1);
}
@keyframes fdv-drawer-in { from { transform: translateX(20px); opacity: 0 } to { transform: translateX(0); opacity: 1 } }
.fdv-drawer-head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--nc-border-subtle, rgba(255,255,255,0.06));
}
.fdv-drawer-title { display: flex; align-items: center; gap: 12px; }
.fdv-drawer-title h2 { margin: 0; font-size: 1.05rem; }
.fdv-drawer-tabs {
  display: flex; gap: 4px;
  padding: 8px 18px;
  border-bottom: 1px solid var(--nc-border-subtle, rgba(255,255,255,0.06));
  overflow-x: auto;
}
.fdv-drawer-tab {
  background: transparent;
  border: 1px solid transparent;
  color: var(--nc-text-muted, #94a3b8);
  padding: 5px 12px;
  border-radius: 3px;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: all 180ms;
}
.fdv-drawer-tab:hover { color: var(--nc-text-primary, #e8eaed); }
.fdv-drawer-tab--active {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3);
  color: var(--nc-primary-bright, #00e5e5);
}
.fdv-drawer-body { padding: 18px; overflow-y: auto; flex: 1; font-size: 0.85rem; }
.fdv-drawer-body p { margin: 0 0 8px; }
.fdv-drawer-stub {
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 40px 20px;
  text-align: center;
  color: var(--nc-text-muted, #94a3b8);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 0.78rem;
}
</style>
