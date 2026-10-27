<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { FRAMES } from '@/config/frames'
import { compactFromSummary } from '@/services/api/trackRecord'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import { useFederationStore } from '@/stores/federation'
import { buildPopulationIndex } from '@/utils/registryPopulation'  // §GLOBEPOP — true per-registry totals
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import { useTopologyDiscovery } from '@/composables/useTopologyDiscovery'
import { useFrameAttribution } from '@/composables/useFrameAttribution'
import { formatDate } from '@/utils/date'
import { debounce } from '@/utils/helpers'
import LoadingState from '@/components/common/LoadingState.vue'
import GalacticMapCanvas from '@/components/GalacticMapCanvas.vue'
import { didOrNull, classifyIdentity } from '@/services/bridge/identity'
import type { MapRegistry, MapAgent, NetworkStats } from '@/components/GalacticMapCanvas.vue'
// Shared hover label (AgentWorld parity — Commander 2026-06-04: "take the on-hover
// labels from AgentWorld, they have the avatar already"). Reuses TopologyHoverLabel +
// lazy UserAvatar so the hovered agent's avatar shows in GalacticMap too.
import TopologyHoverLabel from '@/components/TopologyHoverLabel.vue'
import { defineAsyncComponent } from 'vue'
const UserAvatar = defineAsyncComponent(() => import('@/components/common/UserAvatar.vue'))
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import SovereignRegistryCard from '@/components/SovereignRegistryCard.vue'
// Rich registry hover card — same component AgentWorld uses, so registry
// on-hover here shows avatar/flare + currency/hop/sovereign badges + fee rail
// + card-signature (Commander 2026-06-04: "make the galactic map have the same").
import RegistryHoverCard from '@/components/RegistryHoverCard.vue'
import GalacticControls from '@/components/GalacticControls.vue'
import { useCurrency } from '@/composables/useCurrency'
import { useLogger } from '@/composables/useLogger'

// 2026-05-08 P3.2: useLogger no-ops in production for info/warn/debug.
const log = useLogger('GalacticMap')
import type { Agent } from '@/types'
import { useAuthStore } from '@/stores/auth'
// Balance data comes from authStore.availableAgents (fetched during login)

// #2 (2026-05-08): typed shapes. The runtime objects flowing through this
// view come from heterogeneous sources (agentStore, authStore.availableAgents,
// federationStore registries, /agents/locations, useTopologyDiscovery) and
// the canonical Agent / Registry types in @/types don't capture every field
// each backend surfaces. These local interfaces keep the view honest without
// forcing a global refactor of all consumer types.
interface AgentLike {
  did?: string
  name?: string
  liquidBalance?: number
  stakedBalance?: number
  origin_registry_name?: string
  registry_id?: string | number
  is_active?: boolean
  status?: string
  card_data?: { skills?: Array<{ name?: string; id?: string }> }
}

interface RegistryLike {
  id?: string | number
  name?: string
  url?: string
  base_url?: string
  trust_domain?: string
  spiffe_trust_domain?: string
  // Frontend-only annotations seeded during enrichment passes below.
  peerType?: string
  parentRegistryId?: string | number
  trustDomain?: string
  hopDistance?: number
}

interface PeerRowLike {
  peer_type?: string
  parent_registry_id?: string | number
  hop_distance?: number
  trust_domain?: string
}

interface AgentLocation {
  agent_did?: string
  registry_id?: string | number
  reputation?: number | string
  origin_registry?: string
}

interface SkillEntry {
  name?: string
  id?: string
}

const router = useRouter()
const agentStore = useAgentStore()
const federationStore = useFederationStore()
const authStore = useAuthStore()

// Normalize text for fuzzy federation matching: strip diacritics (São→Sao), split on hyphens/spaces, filter stop words
const _fedStopWords = new Set(['operator', 'the', 'layer', 'teg', 'service'])
function normalizeWords(s: string): string[] {
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase().replace(/-/g, ' ')
    .split(/\s+/).filter(w => w.length >= 3 && !_fedStopWords.has(w))
}

// Look up real balance from auth store's availableAgents (has TEG balances)
// Auth store fetches balances during login flow, keyed by agent name
function getAgentBalance(agent: AgentLike): { liquid: number; staked: number } {
  const name = (agent.name || '').toLowerCase().trim()
  const agents = (authStore.availableAgents || []) as AgentLike[]
  const match = agents.find((a) =>
    (a.name || '').toLowerCase().trim() === name ||
    (a.did && agent.did && a.did === agent.did)
  )
  if (match) {
    return {
      liquid: match.liquidBalance || 0,
      staked: match.stakedBalance || 0,
    }
  }
  return { liquid: 0, staked: 0 }
}
const uiStore = useUIStore()
const { t } = useI18n()

// State
const searchQuery = ref('')
const selectedCapabilities = ref<string[]>([])
const selectedRegistry = ref<string>('all')
const sortBy = ref<'name' | 'reputation' | 'created' | 'activity'>('reputation')
// Embedded mode (IRONHAND mTLS Theatre): hide page chrome + optionally the agent dots,
// and expose the canvas projection + REAL node list so an overlay can ride the ORIGINAL
// topology. Topology/edge logic is left 100% untouched.
// §BRIDGE 2026-08-18 — `missionMode` makes this view the Mission Control STAGE.
// It reuses the entire existing topology pipeline (federationStore + /agents/locations
// + useTopologyDiscovery + the mapRegistries/mapAgents computeds) and only swaps the
// canvas render profile. Building a second topology pipeline for the bridge would have
// been the §FANOUTFIX mistake: two copies of one question, free to disagree.
const props = withDefaults(defineProps<{ embedded?: boolean; hideAgents?: boolean; onlyAgentDids?: string[]; ownedHomes?: Array<{ did: string; name?: string | null; local?: boolean; names?: string[]; trustDomain?: string | null }>; selectionMode?: boolean; busyRegistryIds?: string[]; missionMode?: boolean; counterparties?: Array<{ did: string; frame: string | null }>; missionSearch?: string }>(), { embedded: false, hideAgents: false, onlyAgentDids: () => [], ownedHomes: () => [], selectionMode: false, busyRegistryIds: () => [], missionMode: false, counterparties: () => [], missionSearch: '' })
// Galactic Command Center: in selectionMode the map becomes a TARGETING surface —
// node clicks emit upward (full MapRegistry/MapAgent) instead of opening the
// built-in AgentDetailModal / SovereignRegistryCard. Everything else untouched.
const emit = defineEmits<{ (e: 'select-registry', reg: MapRegistry | null): void; (e: 'select-agent', agent: MapAgent | null): void; (e: 'verb-click', descriptor: any): void }>()
const gmCanvasRef = ref<any>(null)
const viewMode = ref<'grid' | 'list' | 'map'>('map') // Default to map view
const showFilters = ref(false)
const selectedAgent = ref<Agent | null>(null)
const selectedMapAgent = ref<MapAgent | null>(null)  // Enriched version for panel display + canvas selection ring
// AW-aligned click surfaces: agent orb → AgentDetailModal, registry orb →
// SovereignRegistryCard (replaces the legacy inline gm-agent-panel + the silent
// orb-click-to-filter). The legacy panel stays in the file but dormant.
const useLegacyAgentPanel = false
const showAgentModal = ref(false)
const showRegCard = ref(false)
const regCardPeer = ref<string | null>(null)
const regCardFallback = ref<string | null>(null)
const gmPanelCollapsed = ref(false)
const showLabels = ref(false)
const hoveredAgent = ref<Agent | null>(null)
// ─── Hover tooltip (AgentWorld parity — avatar + rich label) ───────────────────
const hoverPos = ref({ x: 0, y: 0 })
function onMapMouseMove(e: MouseEvent) { hoverPos.value = { x: e.clientX, y: e.clientY } }
const tooltipStyle = computed<Record<string, string>>(() => {
  const x = hoverPos.value.x, y = hoverPos.value.y
  const vw = (typeof window !== 'undefined' ? window.innerWidth : 1600)
  const vh = (typeof window !== 'undefined' ? window.innerHeight : 900)
  const TW = 320, TH = 240, M = 16
  const s: Record<string, string> = {}
  if (x + M + TW > vw) s.right = Math.max(8, vw - x + M) + 'px'; else s.left = (x + M) + 'px'
  if (y - 10 + TH > vh) s.bottom = Math.max(8, vh - y - 10) + 'px'; else s.top = Math.max(8, y - 10) + 'px'
  return s
})
// Avatar cache (lazy per agent). CrowdSec-safe: only did:/card: resolve via by-did
// (a burst of 404s on other ids can ban the viewer's IP — see AgentWorld incident).
const hoverAgentProfiles = ref<Record<string, unknown | null>>({})
async function _loadHoverProfile(did: string) {
  if (did in hoverAgentProfiles.value) return
  if (!/^(did:|card:)/.test(did)) { hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: null }; return }
  hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: null }
  try {
    const r = await fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`)
    if (r.ok) { const j = await r.json(); hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: j } }
  } catch { /* avatar is best-effort */ }
}
watch(hoveredAgent, (a) => {
  if (!a || !a.did) return
  if (!(a.did in hoverAgentProfiles.value)) void _loadHoverProfile(a.did)
  if (!(a.did in hoverTrackRecords.value)) void _loadHoverTrackRecord(a.did)
})
// Hoisted above the hover entity, which reads it: a `const` referenced from a
// computed is only safe while nothing evaluates that computed during setup, and
// "nothing does today" is not a property worth depending on.
const { localCurrency } = useCurrency()

const galacticAgentEntity = computed<Record<string, unknown> | null>(() => {
  const a = hoveredAgent.value as (Agent & Record<string, unknown>) | null
  if (!a) return null
  // GC3 (Commander 2026-06-12): surface the IRONHAND identity on the hover card.
  // The lazy by-did profile (already fetched for the avatar) carries
  // card_data.federation_metadata.{mtls_enabled, spiffe_id} — same hoist
  // UniverseView does. Computed re-fires when the profile lands (both refs tracked).
  const prof = hoverAgentProfiles.value[a.did] as Record<string, unknown> | null | undefined
  const cd = (prof as { card_data?: Record<string, unknown> } | null | undefined)?.card_data
  const fm = (cd?.federation_metadata || {}) as Record<string, unknown>
  /**
   * §BRIDGE R13 #8 — "please use the agentworld on mouse hover over agent. its a
   * much better card then this you are using here."
   *
   * Both views already render the SAME `TopologyHoverLabel`; the difference was
   * never the component, it was what got handed to it. AgentWorld passes the
   * agent's standing and money — tier, balances, currency, track record,
   * whether it is foreign — and this view passed a name, a DID and a home. So
   * the card looked poorer here because it WAS told less.
   *
   * This now feeds it the same shape AgentWorld does. Every field is read off
   * data already in hand (the map agent, plus the by-did profile already
   * fetched for the avatar) — nothing new is requested on hover, because a
   * hover that fires a network call per star is how a starfield becomes a
   * denial-of-service against your own registry.
   */
  /**
   * ⚠ THE MAP AGENT DOES NOT CARRY ANY OF THIS. My first pass read balances and
   * reputation off `hoveredAgent` — but a MapAgent is a position and a name, so
   * every rich field resolved to 0 and the card looked exactly as thin as before
   * while the code claimed to be feeding it. He said so: "i dont see the on
   * mouse hover labels that the agentworld are using."
   *
   * The PROFILE does carry them, and it is already fetched for the avatar:
   * `/agents/by-did/{did}` returns `liquid_balance`, `staked_balance`,
   * `reputation_score` and `status`. Read it from there, fall back to the map
   * agent, and show a field only when it actually exists.
   */
  const prof0 = (prof || {}) as Record<string, any>
  const numOrNull = (v: unknown): number | null => {
    if (v === null || v === undefined || v === '') return null
    const n = Number(v); return Number.isFinite(n) ? n : null
  }
  const liquid = numOrNull(prof0.liquid_balance) ?? numOrNull((a as any).liquid_balance) ?? numOrNull((a as any).liquidBalance)
  const staked = numOrNull(prof0.staked_balance) ?? numOrNull((a as any).staked_balance) ?? numOrNull((a as any).stakedBalance)
  // `TopologyHoverLabel` renders reputation as a PERCENT (it clamps to 0..100).
  // The registry stores `reputation_score` on a 0..1 scale, so a raw hand-off
  // would paint every agent's meter at 1%.
  const repRaw = numOrNull(prof0.reputation_score) ?? numOrNull(a.reputation)
  const rep = repRaw === null ? null : (repRaw <= 1 ? repRaw * 100 : repRaw)
  return {
    type: 'agent', name: a.name, did: a.did,
    reputation: a.reputation, status: a.status, capabilities: a.capabilities,
    originRegistry: (a as Record<string, unknown>).origin_registry_name || (a as Record<string, unknown>).registryName || fm.origin_registry_name,
    isSynced: !!(a as Record<string, unknown>).origin_registry_name,
    mtlsEnabled: !!fm.mtls_enabled || !!fm.spiffe_id,
    spiffeId: (fm.spiffe_id as string) || null,
    // ── the AgentWorld half ──
    reputation: rep,
    tierLabel: rep === null ? null : agentTierLabel(rep),
    tierClass: rep === null ? null : agentTierClass(rep),
    liquidBalance: liquid,
    stakedBalance: staked,
    balance: (liquid === null && staked === null) ? null : (liquid || 0) + (staked || 0),
    currency: (a as any).currency || localCurrency.value,
    status: prof0.status || a.status,
    // Foreign = it lives on another registry than the one serving this page.
    foreign: !!(a as Record<string, unknown>).origin_registry_name,
    // §WORLDFIND proven work, the band AgentWorld shows. Fetched once per DID
    // on hover and cached — the same discipline as the avatar profile.
    trackRecord: hoverTrackRecords.value[a.did] || (a as any).trackRecord || null,
    matchedSearch: !!(a as any).matchedSearch,
  }
})

/**
 * Registry-attested proven work for a hovered agent, cached per DID.
 *
 * One small public call (`/agents/{did}/track-record`), only for an agent the
 * pointer actually rested on, and never repeated — a hover that fires a request
 * per star is how a starfield becomes a denial-of-service against your own
 * registry. A failure caches `null`: no band is better than an invented one.
 */
const hoverTrackRecords = ref<Record<string, unknown | null>>({})
async function _loadHoverTrackRecord(did: string): Promise<void> {
  if (did in hoverTrackRecords.value) return
  if (!/^did:/.test(did)) { hoverTrackRecords.value = { ...hoverTrackRecords.value, [did]: null }; return }
  hoverTrackRecords.value = { ...hoverTrackRecords.value, [did]: null }
  try {
    const r = await fetch(`/api/v1/agents/${encodeURIComponent(did)}/track-record`)
    if (r.ok) {
      const j = await r.json()
      // ONE converter (`compactFromSummary`), so the hover label, the earned
      // mark and the Discovery band cannot disagree about the same agent.
      hoverTrackRecords.value = { ...hoverTrackRecords.value, [did]: compactFromSummary(j) }
    }
  } catch { /* no band rather than a wrong one */ }
}

/** The same reputation bands AgentWorld labels agents with, so a hovered agent
 *  reads identically on the globe and on the bridge. */
function agentTierLabel(rep: number): string {
  if (rep >= 0.8) return 'EXEMPLARY'
  if (rep >= 0.6) return 'TRUSTED'
  if (rep >= 0.4) return 'ESTABLISHED'
  if (rep >= 0.2) return 'EMERGING'
  return 'UNPROVEN'
}
function agentTierClass(rep: number): string {
  if (rep >= 0.8) return 'tier-exemplary'
  if (rep >= 0.6) return 'tier-trusted'
  if (rep >= 0.4) return 'tier-established'
  if (rep >= 0.2) return 'tier-emerging'
  return 'tier-unproven'
}
// ─── Registry hover (AgentWorld parity — rich RegistryHoverCard) ───────────────
const hoveredRegistry = ref<MapRegistry | null>(null)
function handleCanvasRegistryHover(reg: MapRegistry | null) {
  hoveredRegistry.value = reg
  if (reg) hoveredAgent.value = null   // agent + registry tooltips are mutually exclusive
}
// Settlement currency for the hovered registry: the card's own when topology
// exposes it, the viewer's for the local registry (hop 0), else unknown (no guess).
const hoveredRegCurrency = computed<string | null>(() => {
  const r = hoveredRegistry.value
  if (!r) return null
  return r.fees?.settlementCurrency || ((r.hopDepth ?? 1) === 0 ? localCurrency.value : null)
})
// Map the canvas MapRegistry → the RegistryHoverCard data shape (frame letter
// for the hop palette: Frame-B cluster → 'B').
const galacticRegistryData = computed<Record<string, unknown> | null>(() => {
  const r = hoveredRegistry.value
  if (!r) return null
  const fr = (r.frame && r.frame !== 'local' && /(-b|frame-b|sovereign|b$)/i.test(String(r.frame))) ? 'B' : 'A'
  return {
    name: r.name, displayName: r.displayName, status: r.status, hopDepth: r.hopDepth, publicUrl: r.publicUrl,
    description: r.description, agentCount: r.agentCount, health: r.health,
    protocolVersion: r.protocolVersion, authMethods: r.authMethods, lastSyncedAt: r.lastSyncedAt,
    cardEtag: r.cardEtag, cardSignatureVerified: r.cardSignatureVerified,
    visual: r.visual, fees: r.fees, frame: fr,
    exchange: (r as any).exchange ?? null,
  }
})
const localRegistryName = ref('This Registry')  // OWL24 FIX-10: fetched from /federation/info
// §GLOBEPOP — true totals from the /agents/locations/ aggregates. Reactive so
// the node-builder computed re-runs when the fetch lands.
const populationIndexRef = ref(buildPopulationIndex(null))
const { topology, version: topologyVersion, discoverTopology, domainKey } = useTopologyDiscovery()
const { ensureLocalFrame, classifyByTrustDomain, localTrustDomain } = useFrameAttribution()

// ─── Self-identity (FE-only, V-relative) — Commander 2026-06-07 ─────────────────
// A registry viewed from ITSELF can appear as a duplicate "self-peer" node: its
// peer_registries holds a self-row, and the local node is named via /federation/info
// (e.g. "cloud op op doha") which doesn't match the self-row / agent-origin slug
// ("op-doha") — so the name-based dedup misses it. The viewer's OWN page host is the
// reliable identity: op-doha.op… → "opdoha"; frame-b.theprotocol.cloud → "frameb".
// Any node/agent matching these aliases is collapsed into __local__. Trust-domain is
// deliberately EXCLUDED (a Frame-C op's td is "frame-c…", which is its PARENT frame,
// NOT itself — using it would wrongly fold the parent mainframe into local).
const _normId = (s: string) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
const localIdentitySlugs = computed<Set<string>>(() => {
  const s = new Set<string>()
  const host = (window.location.hostname || '').toLowerCase()
  if (host) s.add(_normId(host.split('.')[0]))
  if (localRegistryName.value && localRegistryName.value !== 'This Registry') {
    s.add(_normId(localRegistryName.value))
  }
  s.delete('')
  return s
})
function isLocalRegistry(name?: string | null, urlOrDomain?: string | null): boolean {
  const set = localIdentitySlugs.value
  if (!set.size) return false
  const n = _normId(name || '')
  if (n && set.has(n)) return true
  if (urlOrDomain) {
    let host = urlOrDomain
    try { if (urlOrDomain.includes('://')) host = new URL(urlOrDomain).hostname } catch { /* bare domain */ }
    const slug = _normId((host || '').split('.')[0])
    if (slug && set.has(slug)) return true
  }
  return false
}

// Federation network stats (fetched from real API)
const networkStats = ref<NetworkStats | null>(null)

// Primary agent source: /agents/locations/ (DISTINCT ON did at DB layer, 2000
// row cap) — reaches all operators evenly, where /agent-cards/?include_federated
// caps at ~250 and starves modern operators. Mirrors AgentWorld's Fix A from
// the 2026-04-18 globe overhaul.
const locationsData = ref<any[]>([])

// GM1 (audit 2026-05-07): top-level loading flag for the multi-fetch mount.
const initialLoad = ref(true)

// Pagination
const currentPage = ref(1)
const pageSize = ref(24)

// ─── Enriched data for GalacticMapCanvas ─────────────────────────
const LOCAL_REGISTRY_ID = '__local__'
const selectedFrame = ref<string>('all')
// 2026-06-04 — authoritative per-peer frame + mainframe metadata, indexed by lowercase
// name, loaded once from /public/topology (the only source with correct trust_domain
// AND signed-card-derived is_mainframe). Consumed by mapRegistries to classify frames
// and gate the golden inter-frame bridge to mainframe↔mainframe only.
const topoMeta = ref<Map<string, { td?: string | null; mf?: boolean }>>(new Map())
// Full per-registry topology from /public/topology tier buckets (id + parent + hop +
// peer_type), keyed by DB id. This is the AUTHORITATIVE chain source — it represents a
// frame AND its operator distinctly (they share a trust_domain, so the domain-keyed
// useTopologyDiscovery map collides them). Used to add cross-frame ops + rebuild edges
// from parent_registry_id (matches the Federation Network tab + prod). [Commander 2026-06-04]
type TopoFullEntry = { id: number | string; name: string; peer_type?: string; parent_registry_id?: number | string | null; hop_distance?: number | null; trust_domain?: string | null; is_mainframe?: boolean; base_url?: string }
const topoFull = ref<TopoFullEntry[]>([])

// ─── SPIFFE slug extraction (ported from UniverseView) ──────────
function extractSlugFromSpiffe(spiffe: string): string | null {
  let m = spiffe.match(/\/operator\/([^/]+)\/registry/)
  if (m) return m[1]
  m = spiffe.match(/\/sa\/registry-(.+)$/)
  if (m) return m[1]
  m = spiffe.match(/\/service\/registry-(.+)$/)
  if (m) return m[1]
  return null
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/\s+/g, '-')
}

// Reputation rankings cache (fetched once from public endpoint)
const reputationRankings = ref<Map<string, { tier: string; score: number; txs: number }>>(new Map())

// Map internal docker URLs to public-facing domains
const PUBLIC_URL_MAP: Record<string, string> = {
  'https://nginx-a:8443': 'https://registry.theprotocol.cloud',
  'https://nginx-b:8443': 'https://registry-b.theprotocol.cloud',
  'http://localhost:8000': 'https://registry.theprotocol.cloud',
  'http://localhost:8001': 'https://registry-b.theprotocol.cloud',
}
function resolvePublicUrl(internalUrl: string, registryName: string): string {
  if (PUBLIC_URL_MAP[internalUrl]) return PUBLIC_URL_MAP[internalUrl]
  // Fallback: derive from name
  const slug = registryName.toLowerCase().replace(/\s+/g, '-')
  if (slug === 'registry-a' || slug === 'registry a') return 'https://registry.theprotocol.cloud'
  if (slug === 'registry-b' || slug === 'registry b') return 'https://registry-b.theprotocol.cloud'
  return internalUrl
}

const mapRegistries = computed<MapRegistry[]>(() => {
  const peerRegs = federationStore.registries
  const result: MapRegistry[] = []
  const hasTopology = topology.edges.size > 0

  // Build domain→ID map for resolving topology edges to registry IDs
  const domainToId = new Map<string, string>()
  domainToId.set('__local__', LOCAL_REGISTRY_ID)

  // Helper: find links for a given domain from topology edges
  function getLinksForDomain(domain: string, selfId?: string): string[] {
    if (!hasTopology) return []
    const links: string[] = []
    for (const edge of topology.edges) {
      const [a, b] = edge.split('::')
      let targetId: string | undefined
      if (a === domain) targetId = domainToId.get(b) || b
      else if (b === domain) targetId = domainToId.get(a) || a
      if (targetId && targetId !== selfId) links.push(targetId)
    }
    return links
  }

  // Direct peers without public URLs (e.g., Registry B on internal Docker network)
  // always get a bidirectional link to local — topology discovery can't reach them
  const internalPeerIds: string[] = []

  // ALWAYS include the local registry
  // Count only truly local agents (no origin or origin matches THIS registry)
  const localLower = localRegistryName.value.toLowerCase().trim()
  const localAgentCount = filteredAgents.value.filter(a => {
    if (a.registry_id) return false
    const originName = (a as AgentLike).origin_registry_name
    if (!originName) return true
    const ol = originName.toLowerCase().trim()
    return ol === 'local' || ol === localLower || isLocalRegistry(originName)
  }).length

  // Map direct peers domain→ID
  const allPeerIds: string[] = []
  peerRegs.forEach(r => {
    allPeerIds.push(String(r.id))
    const pub = resolvePublicUrl(r.url || (r as RegistryLike).base_url || '', r.name || '')
    if (pub) {
      domainToId.set(domainKey(pub), String(r.id))
    } else {
      internalPeerIds.push(String(r.id))
    }
  })

  result.push({
    id: LOCAL_REGISTRY_ID,
    name: localRegistryName.value,
    url: 'http://localhost:8000',
    publicUrl: window.location.origin || resolvePublicUrl('http://localhost:8000', localRegistryName.value),
    status: 'active',
    agentCount: localAgentCount ?? filteredAgents.value.length,
    health: 100,
    federationLinks: hasTopology
      ? [...new Set([...getLinksForDomain('__local__', LOCAL_REGISTRY_ID), ...allPeerIds])]
      : [...allPeerIds],
    description: 'Primary sovereign registry — home of locally registered agents',
    protocolVersion: '1.0',
    authMethods: ['mtls', 'jwt_svid'],
    hopDepth: 0,
    // 2026-05-05 audit Tier 7: stamp local trust_domain so the
    // hub-and-spoke topology builder can find the local mainframe by td.
    trustDomain: (localTrustDomain.value || '').toLowerCase() || undefined,
  })

  // Add direct peers (always shown)
  peerRegs.forEach(reg => {
    const peerAgentCount = filteredAgents.value.filter(a =>
      a.registry_id === reg.id || (a as AgentLike).origin_registry_name === reg.name
    ).length || reg.agents || 0

    const pub = resolvePublicUrl(reg.url || (reg as RegistryLike).base_url || '', reg.name || '')
    const dk = pub ? domainKey(pub) : ''

    // 2026-05-05 audit Tier 7: pull trust_domain from topology so the
    // hub-and-spoke builder can find each registry's frame mainframe.
    // Frame B operators expose dual URLs — federationStore returns the
    // `.op.` form but topology indexes under `.frame-b.`, so a domain-
    // only lookup misses. Fall back to name-based topology lookup.
    let topoMatch: RegistryLike | null = dk ? (topology.registries.get(dk) as RegistryLike | undefined) ?? null : null
    if (!topoMatch && reg.name) {
      const peerName = reg.name.toLowerCase().trim()
      for (const [, treg] of topology.registries) {
        if (((treg as RegistryLike).name || '').toLowerCase().trim() === peerName) {
          topoMatch = treg
          break
        }
      }
    }
    const peerTd = (topoMatch as RegistryLike | null)?.trust_domain
      || (reg as RegistryLike).trust_domain
      || (reg as RegistryLike).spiffe_trust_domain

    result.push({
      id: reg.id,
      name: reg.name || 'Unknown Registry',
      url: reg.url || '',
      publicUrl: pub,
      status: reg.status || 'active',
      agentCount: peerAgentCount,
      health: reg.health ?? 100,
      federationLinks: hasTopology
        ? ((() => { const links = dk ? getLinksForDomain(dk, String(reg.id)) : []; return links.length > 0 ? links : [LOCAL_REGISTRY_ID] })())
        : [LOCAL_REGISTRY_ID],
      description: reg.description || 'Federated peer registry — bilateral discovery partner',
      lastSyncedAt: reg.lastSync || reg.last_seen || null,
      adminContact: reg.admin_contact_email,
      protocolVersion: '1.0',
      authMethods: ['mtls', 'jwt_svid'],
      hopDepth: 1,
      trustDomain: peerTd ? String(peerTd).toLowerCase() : undefined,
    })
  })

  // Add topology-discovered registries NOT in our direct peer list
  if (hasTopology) {
    const existingDomains = new Set<string>()
    existingDomains.add('__local__')
    // Exclude the local registry's own domain + ALL known aliases from topology duplicates
    // This prevents Registry-A / Frame-A-Mainframe duplication regardless of which URL we're viewing from
    const localPub = window.location.origin
    if (localPub) existingDomains.add(domainKey(localPub))
    // Always add both aliases — the local registry is reachable via multiple domains
    const localHost = window.location.hostname.toLowerCase()
    if (localHost.includes('theprotocol.cloud') || localHost.includes('raphaeljeziorny.com')) {
      existingDomains.add('api.theprotocol.cloud')
      existingDomains.add('registry.theprotocol.cloud')
    }
    if (localHost.includes('frame-b')) {
      existingDomains.add('frame-b.theprotocol.cloud')
    }
    // 2026-05-05 audit T6 fix — BFS peering display:
    //
    // Frame B operators have dual-domain aliases — `/federation/peers/`
    // returns them with `.op.theprotocol.cloud` URLs while
    // `/public/topology` (the BFS source) reports them under
    // `.frame-b.theprotocol.cloud`. Domain-only dedup missed this →
    // every Frame B operator was added TWICE (once via federationStore as
    // direct peer, once via topology as discovered) → 14 planets when
    // there are only 10 registries, with extra federation arcs to nowhere.
    //
    // Defense in depth: also build an existingNames Set from peer names,
    // and skip any topology entry whose name matches a direct peer.
    const existingNames = new Set<string>()
    peerRegs.forEach(r => {
      const pub = resolvePublicUrl(r.url || (r as RegistryLike).base_url || '', r.name || '')
      if (pub) existingDomains.add(domainKey(pub))
      const nm = (r.name || '').toLowerCase().trim()
      if (nm) existingNames.add(nm)
    })

    for (const [dk, reg] of topology.registries) {
      if (existingDomains.has(dk)) continue
      const topoName = (reg.name || '').toLowerCase().trim()
      if (topoName && existingNames.has(topoName)) {
        // Same operator reachable via different alias (e.g. op-tokyo.op vs
        // op-tokyo.frame-b). Map this topology domain to the existing
        // direct-peer ID so federation edges originating at the .frame-b
        // alias still resolve to the live registry node.
        const matchedPeer = peerRegs.find(r => (r.name || '').toLowerCase().trim() === topoName)
        if (matchedPeer) domainToId.set(dk, String(matchedPeer.id))
        continue
      }
      // 2026-05-05 audit T8 corrected — render ALL operators across both
      // frames. Each frame's view shows: full Frame A chain + golden bridge +
      // full Frame B chain. parent_registry_id naturally links chains across
      // the cross-frame bridge (op-tokyo.parent=Frame-B; Frame-B is the
      // bridge; Frame-B's parent=null on local but its peer_type='frame'
      // edges it to LOCAL_REGISTRY_ID).
      const id = `topo-${dk}`
      domainToId.set(dk, id)
      // Count agents whose origin_registry_name matches this topology registry
      const regLower = reg.name.toLowerCase().trim()
      const topoAgentCount = filteredAgents.value.filter(a => {
        const origin = ((a as AgentLike).origin_registry_name || '').toLowerCase().trim()
        return origin === regLower
      }).length
      result.push({
        id,
        name: reg.name,
        url: reg.publicUrl,
        publicUrl: reg.publicUrl,
        status: 'active',
        agentCount: topoAgentCount,
        health: 100,
        federationLinks: getLinksForDomain(dk, id),
        description: 'Discovered via network topology — indirect peer',
        protocolVersion: '1.0',
        authMethods: ['mtls', 'jwt_svid'],
        hopDepth: reg.hopDepth || 2,
        // Tier 7: stamp trust_domain so hub-and-spoke builder sees it.
        trustDomain: ((reg as RegistryLike).trust_domain || '').toLowerCase() || undefined,
      })
    }

    // 2026-05-05 audit T8 — chain federation rendering:
    //
    // Builds federation edges from `parent_registry_id` chains on
    // peer_registries. Each peer either has parent=null (direct peer of
    // local mainframe) or parent=<another peer id> (chain child). Walking
    // the chain produces a TREE rooted at __local__, which is the actual
    // designed topology — Commander's spec: mainframe → 1 direct op →
    // chain child → 2 leaves. The cross-frame golden bridge is a special
    // case (peer_type='frame', parent=null).
    //
    // T7's hub-and-spoke (mainframeByTd) was a regression — see memory
    // feedback_chain_federation_not_drift.md: drift signals that fire on
    // peer_registries.status='INACTIVE' alone incentivize hub-and-spoke
    // collapse. The `peer_type` / `parent_registry_id` schema (migs 0016+
    // 0017) was added precisely so chain topology could be persisted +
    // rendered.
    //
    // peer_id → result.id map for chain traversal. result.id is the
    // PeerRegistry DB id (number) for direct peers; "topo-..." string for
    // pure-topology hops; LOCAL_REGISTRY_ID for the local registry itself.
    const idByPeerId = new Map<number, string>()
    for (const r of result) {
      if (typeof r.id === 'number') idByPeerId.set(r.id, String(r.id))
    }

    // Forward peer_type + hop_distance from federationStore peer rows
    // (now extended in PeerRegistryRead schema with chain fields). Topology
    // entries (added at line 295) have hop only — fine, peer_type stays
    // 'discovered' implicit.
    for (const r of result) {
      if (r.id === LOCAL_REGISTRY_ID) {
        ;(r as RegistryLike).peerType = 'local'
        r.hopDepth = 0
        continue
      }
      // Find the matching federationStore row to pull peer_type / parent
      const peerRow = peerRegs.find(p => p.id === r.id)
      if (peerRow) {
        ;(r as RegistryLike).peerType = (peerRow as PeerRowLike).peer_type
        ;(r as RegistryLike).parentRegistryId = (peerRow as PeerRowLike).parent_registry_id
        const hopDist = (peerRow as PeerRowLike).hop_distance
        if (typeof hopDist === 'number') r.hopDepth = hopDist
      }
    }

    // Build chain edges: each peer with a parent connects to its parent.
    // Peers with parent=null connect to LOCAL_REGISTRY_ID (root of tree).
    // Frame peers (peer_type='frame') always connect to LOCAL_REGISTRY_ID
    // as the cross-frame golden bridge regardless of parent value.
    const linksById = new Map<string, Set<string>>()
    for (const r of result) linksById.set(String(r.id), new Set())

    for (const r of result) {
      if (r.id === LOCAL_REGISTRY_ID) continue
      const peerType = (r as RegistryLike).peerType
      const parentId = (r as RegistryLike).parentRegistryId
      let targetId: string

      if (peerType === 'frame') {
        // Cross-frame mainframe: golden bridge to local
        targetId = LOCAL_REGISTRY_ID
      } else if (parentId && idByPeerId.has(parentId)) {
        // Chain child: edge to chain parent
        targetId = idByPeerId.get(parentId)!
      } else {
        // Direct peer (parent=null) of local mainframe
        targetId = LOCAL_REGISTRY_ID
      }

      linksById.get(String(r.id))!.add(targetId)
      linksById.get(targetId)?.add(String(r.id))
    }

    // Materialise.
    for (const r of result) {
      r.federationLinks = Array.from(linksById.get(String(r.id)) || new Set())
    }
  }

  // Force reactivity on topologyVersion
  void topologyVersion.value

  // 2026-06-04 — authoritative frame + mainframe tagging. Runs UNCONDITIONALLY (the
  // `if (hasTopology)` block above is skipped whenever the client-side BFS hasn't yet
  // populated edges, which left every peer with no trust_domain → the classifier below
  // collapsed them all to 'local': one mono-frame, no cross-frame edges → no golden
  // bridges + no per-frame colour). Match each peer to its /public/topology entry BY NAME
  // (loaded into topoMeta via its own onMounted) and carry the two fields the raw
  // peer_registries row lacks: trust_domain, and is_mainframe (server-side from the peer's
  // SIGNED card tier == 'sovereign-mainframe' — peer_type is unreliable across frames).
  // Reflect mainframes into peerType='frame' so the canvas golds ONLY mainframe↔mainframe.
  {
    const _tm = topoMeta.value
    for (const r of result) {
      if (r.id === LOCAL_REGISTRY_ID) continue
      const nm = (r.name || '').trim().toLowerCase()
      const meta = nm ? _tm.get(nm) : undefined
      if (!meta) continue
      if (!(r as RegistryLike).trustDomain && meta.td) (r as RegistryLike).trustDomain = meta.td
      if (meta.mf) (r as RegistryLike).peerType = 'frame'
    }
  }

  // 2026-06-04 — collapse DUPLICATE mainframe nodes. The same physical sovereign
  // mainframe is registered in peer_registries under two names (e.g. "Registry-Test" +
  // "Registry Test A", both sandbox-a.test), so it rendered TWICE from every view. Each
  // frame has exactly ONE sovereign mainframe → dedup is_mainframe nodes by trust_domain.
  // The local node owns localTrustDomain, so a non-local mainframe whose td == local td
  // (the self-duplicate seen from its own frame) is dropped too. Splice backwards; the
  // canvas skips beams to ids that no longer resolve.
  {
    const _seenTd = new Set<string>()
    const _localTd = (localTrustDomain.value || '').trim().toLowerCase()
    if (_localTd) _seenTd.add(_localTd)
    for (let i = result.length - 1; i >= 0; i--) {
      const r = result[i]
      if (r.id === LOCAL_REGISTRY_ID) continue
      if ((r as RegistryLike).peerType !== 'frame') continue
      const td = ((r as RegistryLike).trustDomain || '').trim().toLowerCase()
      if (!td) continue
      if (_seenTd.has(td)) { result.splice(i, 1); continue }
      _seenTd.add(td)
    }
  }

  // ─── Authoritative chain topology from /public/topology (Commander 2026-06-04) ───
  // ROOT FIX for "all operators are 1-hop spokes off local". The node set above is
  // built from a DOMAIN-keyed map (useTopologyDiscovery), so a frame and its operator
  // (same trust_domain — e.g. Registry-Test-B + sandboxdelta, both sandbox-b.test)
  // COLLIDE: the operator is overwritten by its frame and vanishes, OR (when present)
  // its edge can't follow parent_registry_id. /public/topology returns every registry
  // DISTINCTLY by DB id WITH parent_registry_id + hop. We (1) add any peer missing from
  // the node set (the collided cross-frame ops), then (2) rebuild EVERY federation edge
  // from parent_registry_id: peer_type='frame' → LOCAL (golden cross-frame bridge),
  // a resolvable parent → that parent node, else → LOCAL (direct hop-1 child). This is
  // exactly the tree the Federation Network tab + prod render.
  {
    const full = topoFull.value
    if (full.length) try {
      const haveById = new Set(result.map(r => String(r.id)))
      const haveByName = new Set(result.map(r => (r.name || '').trim().toLowerCase()))
      // (1) Add peers present in /public/topology but missing from the node set —
      // typically the cross-frame operators that collided with their frame above.
      for (const e of full) {
        const eid = String(e.id)
        const enm = (e.name || '').trim().toLowerCase()
        if (haveById.has(eid) || (enm && haveByName.has(enm))) continue
        const agentCount = filteredAgents.value.filter(a =>
          ((a as AgentLike).origin_registry_name || '').toLowerCase().trim() === enm
        ).length
        result.push({
          id: eid,
          name: e.name,
          url: e.base_url || '',
          publicUrl: e.base_url || '',
          status: 'active',
          agentCount,
          health: 100,
          federationLinks: [],
          description: e.is_mainframe ? 'Sovereign frame' : 'Federation operator (chain peer)',
          protocolVersion: '1.0',
          authMethods: ['mtls', 'jwt_svid'],
          hopDepth: (typeof e.hop_distance === 'number' ? e.hop_distance : 2),
          trustDomain: (e.trust_domain || '').toLowerCase() || undefined,
          peerType: e.is_mainframe ? 'frame' : (e.peer_type || 'discovered'),
          parentRegistryId: (e.parent_registry_id ?? undefined) as number | string | undefined,
        } as MapRegistry)
        haveById.add(eid); if (enm) haveByName.add(enm)
      }
      // (2) Enrich existing nodes with parent/peer_type from /public/topology (by id then
      // name) — fills the gap left by getRegistries() which strips the chain fields — AND
      // map each peer's DB id → its node id (covers topo-<domain> nodes whose node id is
      // NOT the DB id, so DEEP chains like op-seoul→op-tokyo→Frame-B still resolve).
      const fullById = new Map(full.map(e => [String(e.id), e]))
      const fullByName = new Map(full.map(e => [(e.name || '').trim().toLowerCase(), e]))
      const nodeIdByDbId = new Map<number, string>()
      for (const r of result) {
        const n = Number(r.id)
        if (!Number.isNaN(n)) nodeIdByDbId.set(n, String(r.id))
        if (r.id === LOCAL_REGISTRY_ID) continue
        const e = fullById.get(String(r.id)) || fullByName.get((r.name || '').trim().toLowerCase())
        if (!e) continue
        const eNum = Number(e.id)
        if (!Number.isNaN(eNum)) nodeIdByDbId.set(eNum, String(r.id))
        const rl = r as RegistryLike
        if (rl.parentRegistryId == null && e.parent_registry_id != null) rl.parentRegistryId = e.parent_registry_id as number | string
        if (e.is_mainframe) rl.peerType = 'frame'
        else if (!rl.peerType) rl.peerType = e.peer_type
        if (typeof e.hop_distance === 'number') r.hopDepth = e.hop_distance
      }
      // (4) Rebuild all edges from the parent chain.
      // §2026-06-07 — leaf-op frame hierarchy: when the LOCAL registry is a leaf
      // OPERATOR (not a mainframe), its OWN frame is the node peered with the other
      // frames — foreign frames must bridge THROUGH it, not short-circuit to us (which
      // made the local op look like a frame). localParentFrameId = the 'frame' peer
      // sharing our trust_domain (e.g. doha → Frame-C). null when WE are a mainframe
      // (frame-b: no frame peer shares our td) → every frame → __local__, unchanged.
      const _ltd = (localTrustDomain.value || '').toLowerCase()
      const _localParentFrame = _ltd
        ? result.find(r => r.id !== LOCAL_REGISTRY_ID
            && (r as RegistryLike).peerType === 'frame'
            && ((r as RegistryLike).trustDomain || '').toLowerCase() === _ltd)
        : undefined
      const localParentFrameId = _localParentFrame ? String(_localParentFrame.id) : null
      // §2026-06-07 de-flatten foreign frames (leaf-op view): from a leaf op (doha)
      // parent_registry_id is FLAT — it records every Frame-A/B operator as a direct
      // child of its frame. The BFS `edges` DO carry the true intra-frame chains
      // (op-berlin::op-london::op-paris …). Build name→meta + name-adjacency from
      // topology.registries + topology.edges so a flat op can recover its real chain
      // parent = the same-frame BFS neighbour one BFS-hop shallower. NO-OP from a
      // mainframe (its parent_registry_id is already chained → never hits the flat
      // branch below) — verified frame-b stays identical.
      const _nameToId = new Map<string, string>()
      const _isFrameById = new Map<string, boolean>()
      const _tdById = new Map<string, string>()
      for (const r of result) {
        const nm = (r.name || '').toLowerCase().trim(); if (nm) _nameToId.set(nm, String(r.id))
        _isFrameById.set(String(r.id), (r as RegistryLike).peerType === 'frame')
        _tdById.set(String(r.id), ((r as RegistryLike).trustDomain || '').toLowerCase())
      }
      const _domToName = new Map<string, string>()
      const _bfsHopByName = new Map<string, number>()
      for (const [dom, treg] of topology.registries) {
        const nm = ((treg as RegistryLike).name || '').toLowerCase().trim()
        if (nm) { _domToName.set(dom, nm); _bfsHopByName.set(nm, ((treg as { hopDepth?: number }).hopDepth) ?? 99) }
      }
      const _adjByName = new Map<string, Set<string>>()
      for (const ed of topology.edges) {
        const [a, b] = String(ed).split('::'); const na = _domToName.get(a) || a, nb = _domToName.get(b) || b
        if (!_adjByName.has(na)) _adjByName.set(na, new Set())
        if (!_adjByName.has(nb)) _adjByName.set(nb, new Set())
        _adjByName.get(na)!.add(nb); _adjByName.get(nb)!.add(na)
      }
      // node id -> its parent's node id (resolved), so de-flatten never routes a node to
      // its OWN child — which (when the BFS hop is viewer-relative on a leaf op) would
      // invert a real chain like op-berlin→Registry-A into op-berlin→op-london. 2026-06-08.
      const _parentNodeIdByNodeId = new Map<string, string>()
      for (const r of result) {
        const _ppid = (r as RegistryLike).parentRegistryId
        if (_ppid != null && nodeIdByDbId.has(Number(_ppid))) _parentNodeIdByNodeId.set(String(r.id), nodeIdByDbId.get(Number(_ppid))!)
      }
      const _deflattenParent = (r: MapRegistry): string | null => {
        const nm = (r.name || '').toLowerCase().trim(); const hop = _bfsHopByName.get(nm)
        if (hop == null || hop <= 1) return null
        const td = ((r as RegistryLike).trustDomain || '').toLowerCase()
        for (const nbr of (_adjByName.get(nm) || [])) {
          const nid = _nameToId.get(nbr); if (!nid) continue
          if (_isFrameById.get(nid)) continue            // want the real op chain-parent, not the frame
          if (_tdById.get(nid) !== td) continue           // same frame only
          if (_parentNodeIdByNodeId.get(nid) === String(r.id)) continue  // never route to our own child
          if (_bfsHopByName.get(nbr) === hop - 1) return nid  // one BFS-hop shallower = chain parent
        }
        return null
      }
      const linksById = new Map<string, Set<string>>()
      for (const r of result) linksById.set(String(r.id), new Set())
      for (const r of result) {
        if (r.id === LOCAL_REGISTRY_ID) continue
        const rl = r as RegistryLike
        // 2026-06-08: our OWN frame (home mainframe) attaches to the chain via its ops'
        // parent links (e.g. op-berlin→Registry-A), NOT to the viewer — so the viewer
        // renders as a LEAF, not a hub. Skip linking the local frame here. (No-op on a
        // mainframe: localParentFrameId is null, so this never matches.)
        if (rl.peerType === 'frame' && localParentFrameId && String(r.id) === localParentFrameId) continue
        const pid = rl.parentRegistryId
        let target: string = LOCAL_REGISTRY_ID
        if (rl.peerType === 'frame') target = localParentFrameId || LOCAL_REGISTRY_ID
        else if (pid != null && nodeIdByDbId.has(Number(pid))) target = nodeIdByDbId.get(Number(pid))!
        else target = LOCAL_REGISTRY_ID
        // de-flatten: if parent_registry_id landed us directly under a FRAME (or local)
        // but the BFS edges reveal a real same-frame chain parent, use it.
        if (target === LOCAL_REGISTRY_ID || _isFrameById.get(target)) {
          const deflat = _deflattenParent(r)
          if (deflat && deflat !== String(r.id)) target = deflat
        }
        linksById.get(String(r.id))!.add(target)
        linksById.get(target)?.add(String(r.id))
      }
      // 2026-06-08: the self-row (this operator) is collapsed into __local__, so carry
      // its real chain parent onto __local__ — else the viewer floats/hubs. With the
      // local-frame gateway attach above, this makes the viewer a degree-1 LEAF at the
      // chain tail (e.g. washington → op-london → op-berlin → Registry-A).
      for (const e of full) {
        if (!isLocalRegistry(e.name, e.base_url)) continue
        const _pid = e.parent_registry_id
        if (_pid != null && nodeIdByDbId.has(Number(_pid))) {
          const _pt = nodeIdByDbId.get(Number(_pid))!
          if (_pt !== LOCAL_REGISTRY_ID) { linksById.get(LOCAL_REGISTRY_ID)?.add(_pt); linksById.get(_pt)?.add(LOCAL_REGISTRY_ID) }
        }
      }
      for (const r of result) r.federationLinks = Array.from(linksById.get(String(r.id)) || new Set())
    } catch (e) { import.meta.env.DEV && console.warn('[GalacticMap] chain rebuild skipped', e) }
  }

  // ─── Frame Classification (audit Tier 3 — backend trust_domain) ──────
  // 2026-05-05: replaced URL-substring matching with the authoritative
  // trust_domain field returned by /public/topology + /trusted-registries.
  // Local registries (matching localTrustDomain) → 'local'. Non-local
  // trust_domains → use the registry's display name as the frame label.
  // Falls back to 'local' for entries missing trust_domain (older operators
  // pre-Tier-1A backend pass).
  for (const r of result) {
    if (r.id === LOCAL_REGISTRY_ID) { r.frame = 'local'; continue }

    // Look up trust_domain — first from the registry itself if populated,
    // then from topology.registries by domain (the backend embeds
    // trust_domain on each /public/topology entry post-Tier-1A).
    let td: string | null | undefined = (r as RegistryLike).trustDomain
    if (!td) {
      const rDk = r.publicUrl ? domainKey(r.publicUrl) : ''
      if (rDk) td = (topology.registries.get(rDk) as RegistryLike | undefined)?.trust_domain
    }

    const cls = classifyByTrustDomain(td)
    if (cls === 'local') { r.frame = 'local'; continue }
    if (cls === 'unknown') {
      // Fail-soft: pre-Tier-1A operators won't have trust_domain. Treat
      // close-hop entries as local; far-hop as Frame B by URL hint to
      // preserve previous behaviour while we wait for those operators
      // to roll forward.
      const rUrl = (r.publicUrl || r.url || '').toLowerCase()
      r.frame = ((r.hopDepth || 0) <= 1 || !rUrl.includes('frame-b'))
        ? 'local'
        : 'Frame B Sovereign'
      continue
    }
    // Non-local trust_domain — humanize to a single label per frame so
    // the filter dropdown groups all Frame B registries (mainframe + ops)
    // into one bucket. Future trust domains fall back to the raw td.
    r.frame = (cls === 'frame-b.theprotocol.cloud') ? 'Frame B Sovereign' : cls
    r.trustDomain = cls
  }

  // Registry Card v0.3/0.4 — hydrate visual + fees + card-signature onto each
  // node from /public/topology so the rich RegistryHoverCard (AgentWorld parity)
  // renders avatar/flare + currency + fee rail + signature on hover. Mirrors
  // AgentWorld's hydrate pass: match by name, with __local__/hop-0 fallback for
  // the local registry (its topology name differs from settings.REGISTRY_NAME).
  // Enrich-only — never creates nodes; strict no-op when topology lacks card data.
  {
    const topoByNameLc = new Map<string, RegistryLike>()
    let topoLocal: RegistryLike | null = null
    for (const [dk, t] of topology.registries) {
      const nm = ((t as RegistryLike).name || '').toLowerCase().trim()
      if (nm) topoByNameLc.set(nm, t as RegistryLike)
      if (dk === '__local__') topoLocal = t as RegistryLike
    }
    const peersByName = (topology as unknown as { peersByName?: Map<string, RegistryLike> }).peersByName
    if (peersByName) for (const [nm, t] of peersByName) { if (nm && !topoByNameLc.has(nm)) topoByNameLc.set(nm, t) }
    for (const reg of result) {
      const t = (reg.id === LOCAL_REGISTRY_ID || (reg.hopDepth ?? 1) === 0)
        ? (topoLocal || topoByNameLc.get((reg.name || '').toLowerCase().trim()))
        : topoByNameLc.get((reg.name || '').toLowerCase().trim())
      if (!t) continue
      const tt = t as Record<string, any>
      const rcVisual = tt.visual
      const rcFees = tt.fees_summary
      if (rcVisual) reg.visual = {
        iconUrl: rcVisual.icon_url, orbColor: rcVisual.orb_color, orbGlowColor: rcVisual.orb_glow_color,
        sovereignVariant: rcVisual.sovereign_variant, flareEncirclementVariant: rcVisual.flare_encirclement_variant,
        flareEncirclementOverlay: rcVisual.flare_encirclement_overlay,
      }
      if (rcFees) reg.fees = {
        intraRegistry: rcFees.intra_registry, crossRegistry: rcFees.cross_registry,
        hostingEnabled: rcFees.hosting_enabled, hostingRate: rcFees.hosting_rate,
        settlementCurrency: rcFees.settlement_currency,
      }
      if (tt.exchange) (reg as any).exchange = tt.exchange
      if (tt.card_etag) reg.cardEtag = tt.card_etag
      if (typeof tt.card_signature_verified === 'boolean') reg.cardSignatureVerified = tt.card_signature_verified
      // §2026-06-14 — card display_name → hover label (falls back to slug client-side).
      if (tt.display_name) reg.displayName = tt.display_name
    }
  }

  // ─── Collapse SELF duplicate + V-relative hop (FE-only) — Commander 2026-06-07 ──
  // (a) Remove any non-local node that IS the local registry (the self-peer duplicate
  // the name-based dedup misses), re-pointing its edges + folding its agent count into
  // __local__. (b) Recompute hopDepth as the V-RELATIVE tree-walk depth (deriveDisplayHop
  // — the SAME derivation the Federation Network tab uses) so the hover HOP badge +
  // hop-coloured beams read correctly from ANY viewing registry. Both pure-FE.
  {
    const selfNodeIds = new Set<string>()
    for (const r of result) {
      if (r.id === LOCAL_REGISTRY_ID) continue
      if (isLocalRegistry(r.name, r.publicUrl || r.url)) selfNodeIds.add(String(r.id))
    }
    if (selfNodeIds.size) {
      const localNode = result.find(r => r.id === LOCAL_REGISTRY_ID)
      // Re-point any edge that referenced a self node → __local__ (dedup + drop self-loops).
      for (const r of result) {
        r.federationLinks = Array.from(new Set(
          (r.federationLinks || []).map(l => (selfNodeIds.has(String(l)) ? LOCAL_REGISTRY_ID : String(l)))
        )).filter(l => String(l) !== String(r.id))
      }
      // Fold self agent counts into local, then drop the duplicate node(s).
      for (let i = result.length - 1; i >= 0; i--) {
        if (selfNodeIds.has(String(result[i].id))) {
          if (localNode) localNode.agentCount = (localNode.agentCount || 0) + (result[i].agentCount || 0)
          result.splice(i, 1)
        }
      }
    }

    // Displayed hop = depth in the RESOLVED V-relative tree (BFS over the rebuilt
    // federationLinks from __local__). Self-consistent with the rendered edges — incl.
    // the de-flattened foreign chains — and correct from any viewing registry. (Replaces
    // the deriveDisplayHop tree-walk, which read the FLAT parent_registry_id and so
    // mis-stated foreign-op depth from a leaf-op view.)
    try {
      const _adj = new Map<string, Set<string>>()
      for (const r of result) _adj.set(String(r.id), new Set())
      for (const r of result) for (const l of (r.federationLinks || [])) {
        _adj.get(String(r.id))?.add(String(l)); _adj.get(String(l))?.add(String(r.id))
      }
      const _depth = new Map<string, number>([[LOCAL_REGISTRY_ID, 0]])
      let _frontier = [LOCAL_REGISTRY_ID]
      while (_frontier.length) {
        const _next: string[] = []
        for (const id of _frontier) {
          const dz = _depth.get(id)!
          for (const nb of (_adj.get(id) || [])) {
            if (!_depth.has(nb)) { _depth.set(nb, dz + 1); _next.push(nb) }
          }
        }
        _frontier = _next
      }
      for (const r of result) {
        const dz = _depth.get(String(r.id))
        if (typeof dz === 'number') r.hopDepth = dz
      }
    } catch (e) { import.meta.env.DEV && console.warn('[GalacticMap] tree-hop skipped', e) }
  }

  // §GLOBEPOP: label TRUE populations — the heuristic per-node counts (drawn
  // agents, peer rows, topology probes) become floors, never the ceiling.
  for (const r of result) {
    const pop = populationIndexRef.value.lookup(r.name, (r as { trustDomain?: string }).trustDomain)
    if (pop) r.agentCount = Math.max(r.agentCount || 0, pop.total)
  }

  // Debug hook (mirrors AgentWorld's window.__aw_registries) — expose the resolved
  // node set so the golden-bridge mainframe tagging is inspectable from the console.
  ;(window as unknown as { __gmReg?: unknown }).__gmReg = result.map(r => ({
    name: r.name, id: String(r.id), peerType: (r as RegistryLike).peerType, frame: r.frame, hop: r.hopDepth,
    parent: (r as RegistryLike).parentRegistryId ?? null, links: r.federationLinks,
  }))
  ;(window as unknown as { __gmTopoMeta?: unknown }).__gmTopoMeta =
    [...topoMeta.value.entries()].map(([k, v]) => ({ name: k, ...v }))

  // Apply frame filter
  if (selectedFrame.value !== 'all') {
    return result.filter(r => r.frame === selectedFrame.value)
  }

  return result
})

// Available frame names for the filter dropdown
const availableFrames = computed<string[]>(() => {
  const frames = new Set<string>()
  mapRegistries.value.forEach(r => { if (r.frame && r.frame !== 'local') frames.add(r.frame) })
  return Array.from(frames).sort()
})

const mapAgents = computed<MapAgent[]>(() => {
  // API returns: id, name, description, is_active, origin_registry_name, capabilities, updated_at
  // NOTE: API does NOT return 'did' or 'registry_id' — use 'id' and 'origin_registry_name' instead
  const peerRegs = federationStore.registries

  // Diagnostic: log ALL agents' origin info for registry mapping debugging
  if (filteredAgents.value.length > 0) {
    import.meta.env.DEV && console.log('[GalacticMap:Mapping] Agent origins:',
      filteredAgents.value.map(a => ({
        name: a.name,
        id: a.id,
        origin_registry_name: (a as AgentLike).origin_registry_name,
        registry_id: a.registry_id,
      }))
    )
    import.meta.env.DEV && console.log('[GalacticMap:Mapping] Peer registries:', peerRegs.map(r => ({ id: r.id, name: r.name, url: r.url })))
  }

  return canvasSourceAgents.value
    .filter(a => a.did || a.id) // Accept agents with either DID or ID
    .map(agent => {
      // Extract capabilities from card_data if available
      const tags = agent.card_data?.tags || agent.capabilities || []
      const skills = (agent.card_data?.skills || []).map((s: SkillEntry) => s.name || s.id).filter(Boolean)
      const caps = [...new Set([...tags, ...skills])]

      // Map agent to a registry ID using multiple strategies
      let registryId = LOCAL_REGISTRY_ID
      const originName = (agent as AgentLike).origin_registry_name
      const allRegs = mapRegistries.value
      // Track whether we actually resolved the origin (for legacy-skip below).
      // An unset origin means "local" — that's a legitimate __local__ binding,
      // not a failed match. Only origins that are SET but unresolvable are legacy.
      // Self-origin (this registry's own agents, viewed from itself) is LOCAL — never
      // a duplicate self-peer node. Treating it as "no origin" binds it to __local__
      // and avoids the legacy-skip drop below. [Commander 2026-06-07]
      const hasOrigin = !!originName && originName.toLowerCase() !== 'local' && !isLocalRegistry(originName)
      let originResolved = !hasOrigin

      // Strategy 0 (BEST): SPIFFE slug extraction from federation_metadata
      const fedMeta = agent.card_data?.federation_metadata || {}
      const sourceRegistry = fedMeta.source_registry || ''
      if (sourceRegistry && registryId === LOCAL_REGISTRY_ID) {
        const slug = extractSlugFromSpiffe(sourceRegistry)
        if (slug) {
          for (const reg of allRegs) {
            if (reg.id === LOCAL_REGISTRY_ID) continue
            const regSlug = slugify(reg.name)
            if (slug === regSlug || regSlug.startsWith(slug) || slug.startsWith(regSlug)) {
              registryId = reg.id
              originResolved = true
              break
            }
          }
        }
      }

      // Strategy 1: Explicit registry_id field
      if (registryId === LOCAL_REGISTRY_ID && agent.registry_id) {
        registryId = agent.registry_id
        originResolved = true
      }
      // Strategy 2: origin_registry_name from federation API
      // Match against ALL registries (direct peers + topology-discovered)
      if (registryId === LOCAL_REGISTRY_ID && hasOrigin) {
        const normalizedOrigin = originName.toLowerCase().trim()
        const originWords = new Set(normalizeWords(originName))

        let matched = false

        for (const reg of allRegs) {
          if (reg.id === LOCAL_REGISTRY_ID) continue
          const regName = (reg.name || '').toLowerCase().trim()

          // Exact match (origin names are standardized to display names at sync time)
          if (regName === normalizedOrigin) {
            registryId = reg.id
            matched = true
            break
          }
        }

        // Fallback: check peerRegs URL match
        if (!matched) {
          const urlMatch = peerRegs.find(r => r.url?.toLowerCase().includes(normalizedOrigin))
          if (urlMatch) {
            registryId = urlMatch.id
            matched = true
          }
        }

        if (matched) {
          originResolved = true
          import.meta.env.DEV && console.log(`[GalacticMap] Agent "${agent.name}" → registry "${registryId}" (origin: ${originName})`)
        }
      }

      // Legacy/defunct origin: agent carries an origin_registry_name that
      // doesn't match any live registry in the current topology (e.g. pre-rename
      // "Turbo Tokyo" or torn-down "cloud-op-alpha-b"). Skip so they don't pile
      // on the local mainframe. Mirrors AgentWorld's matchRegistry skip logic.
      if (hasOrigin && !originResolved) return null

      // Use is_active if status not available
      const status = agent.status || ((agent as AgentLike).is_active === false ? 'inactive' : 'active')

      // Look up reputation from rankings cache
      const agentDid = agent.did || String(agent.id) || 'unknown'
      const repData = reputationRankings.value.get(agentDid)

      return {
        did: agentDid,
        name: agent.name || 'Unnamed Agent',
        description: agent.description || '',
        status,
        registryId,
        reputation: repData?.score ?? agent.reputation ?? 0,
        reputationTier: repData?.tier || 'standard',
        totalTransactions: repData?.txs || 0,
        // Balance: look up from auth store's availableAgents (has real TEG balances)
        liquidBalance: getAgentBalance(agent).liquid,
        stakedBalance: getAgentBalance(agent).staked,
        capabilities: caps,
        isVerified: agent.verified ?? false,
        // OWL24 FIX-11: Use backend's origin_registry_name as the source of truth.
        // origin_registry_name === 'Local' means native card; anything else means synced copy.
        isSynced: !!originName && originName.toLowerCase() !== 'local',
        createdAt: agent.created_at || agent.updated_at || new Date().toISOString(),
        originRegistry: originName && originName.toLowerCase() !== 'local' ? originName : undefined,
        frame: mapRegistries.value.find(r => r.id === registryId)?.frame || 'local',
      }
    })
    .filter((a): a is MapAgent => a !== null)
    .filter(a => selectedFrame.value === 'all' || a.frame === selectedFrame.value)
})

// Dynamic capabilities extracted from actual agent data
const availableCapabilities = computed(() => {
  const caps = new Set<string>()
  allAgents.value.forEach(agent => {
    const tags = agent.card_data?.tags || agent.capabilities || []
    tags.forEach((tag: string) => caps.add(tag))
    const skills = agent.card_data?.skills || []
    skills.forEach((skill: SkillEntry | string) => {
      if (skill.name) caps.add(skill.name)
      else if (skill.id) caps.add(skill.id)
    })
  })
  return Array.from(caps).sort()
})

const sortOptions = [
  { value: 'name', label: 'Name' },
  { value: 'reputation', label: 'Reputation' },
  { value: 'created', label: 'Newest' },
  { value: 'activity', label: 'Most Active' }
]

// Computed
const allAgents = computed(() => {
  // PRIMARY source: /agents/locations/ — backend-deduped per DID, 2000-row cap.
  // Reaches every operator evenly. Transform location rows into the Agent
  // shape the downstream filters + mapAgents pipeline expects.
  const fromLocations = (locationsData.value || [])
    .filter(loc => loc && loc.did && loc.name)
    .map(loc => ({
      id: loc.did,
      did: loc.did,
      name: loc.name,
      description: '',
      status: loc.status || 'active',
      is_active: loc.status !== 'inactive',
      visibility: 'public',
      reputation: Number((loc as AgentLocation).reputation) || 0,
      origin_registry_name: (loc as AgentLocation).origin_registry || undefined,
      capabilities: [],
      card_data: {},
      registry_id: undefined,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }))

  // SECONDARY source: agentStore.agents (from /agent-cards/) — fills in DIDs
  // that locations missed (DID-less legacy records, or agents very recently
  // created). Filtered for active/public.
  const fromStore = agentStore.agents.filter(agent => {
    const isPublic = !agent.visibility || agent.visibility === 'public'
    const isActive = agent.is_active !== false && agent.status !== 'revoked' && agent.status !== 'inactive'
    return isPublic && isActive
  })

  // 2026-05-05 audit T6 fix — agent-count inflation:
  //
  // /agent-cards/ returns federated entries with NO did and an
  // `origin_registry_name` that uses slug form ('op-tokyo'), while
  // /agents/locations/ returns the same agents with did + an
  // `origin_registry` that uses display form ('Legendary Lima'). The
  // previous (name, origin) dedup key compared apples to oranges →
  // 499 of 684 cards slipped through dedup → 1336+499≈1815 inflated
  // count.
  //
  // Fix: locations is authoritative (DISTINCT ON did, server-side dedup,
  // display-name origin). Cards have no did at all, so they only ever
  // contribute as a name-supplement. Dedup cards against locations by
  // NAME alone — if the same agent name already appeared in locations,
  // skip the card. Worst case: a legitimate name collision drops a
  // card, but since the card had no did anyway, no info is lost.
  const byDid = new Map<string, any>()
  const seenNames = new Set<string>()
  const nameKey = (name: string) => (name || '').toLowerCase().trim()

  for (const a of fromLocations) {
    if (a.did) byDid.set(a.did, a)
    const nk = nameKey(a.name)
    if (nk) seenNames.add(nk)
  }
  for (const a of fromStore) {
    const nk = nameKey(a.name)
    if (nk && seenNames.has(nk)) continue  // already in locations, skip card
    const key = a.did || `card:${a.id}`
    if (!byDid.has(key)) byDid.set(key, a)
    if (nk) seenNames.add(nk)
  }
  return Array.from(byDid.values())
})

const filteredAgents = computed(() => {
  let filtered = allAgents.value

  // Search filter
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    filtered = filtered.filter(agent =>
      agent.name.toLowerCase().includes(query) ||
      agent.description?.toLowerCase().includes(query) ||
      (agent.capabilities || []).some(cap => cap.toLowerCase().includes(query))
    )
  }

  // Capability filter
  if (selectedCapabilities.value.length > 0) {
    filtered = filtered.filter(agent =>
      selectedCapabilities.value.every(cap =>
        (agent.capabilities || []).includes(cap)
      )
    )
  }

  // Registry filter
  if (selectedRegistry.value !== 'all') {
    filtered = filtered.filter(agent =>
      agent.registry_id === selectedRegistry.value
    )
  }

  // Sort
  filtered = [...filtered].sort((a, b) => {
    switch (sortBy.value) {
      case 'name':
        return a.name.localeCompare(b.name)
      case 'reputation':
        return (b.reputation || 0) - (a.reputation || 0)
      case 'created':
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      case 'activity':
        return (b.metrics?.total_requests || 0) - (a.metrics?.total_requests || 0)
      default:
        return 0
    }
  })

  return filtered
})

// Canvas cloud source (Commander 2026-06-04): the 3D map shows the FULL field as
// context and lets `searchQuery` *highlight* matches (dim others + beacon) rather
// than gutting the cloud down to the matches. So it applies every filter EXCEPT the
// search term (and no pagination). Search-gutting also tripped the canvas anti-race
// "agents dropped to 0" guard, freezing a stale cloud. The list/grid view keeps using
// filteredAgents (search-narrowed); only the canvas uses this.
/*
 * §BRIDGE R10 — SEARCH THAT HIGHLIGHTS, on the bridge.
 *
 * "it would be good to have a search for a specific agent which highlights him.
 *  check how the galactic command did it."
 *
 * The canvas already implements exactly that: `searchQuery` dims every
 * non-match and beacons the matches (GalacticMapCanvas §GC3), and the camera
 * can be sent to the first match. It was simply never reachable from mission
 * mode, whose HUD replaces this view's own control strip. So the HUD passes its
 * query in and this is the single place that decides which one is live.
 */
const effectiveSearch = computed(() => (props.missionMode ? (props.missionSearch || '') : searchQuery.value))

/**
 * §BRIDGESEARCH (Commander 2026-08-21) — "not shown agents should be loaded
 * when searched explicitly in the bridge."
 *
 * R10 promoted search matches only from the population this view ALREADY held,
 * with an explicit "no new fetch" rule. That rule is why searching `hagrid` on
 * frame-c returned 0: he lives on Registry-A and was never in the local sample.
 *
 * The server can already answer this — §WORLDFIND put whole-population search on
 * `/agents/locations/?q=`, which merges matches into the sample and flags them
 * `matched_search`. An EXPLICIT search is exactly the moment a fetch is
 * justified, so we ask, and the rows land in `allAgents`'s own shape so the
 * existing registry resolution and DID-seeded orbit place them like any other
 * star. A match we cannot place still gets no invented position.
 */
const searchFetched = ref<any[]>([])
let searchFetchSeq = 0
let searchFetchTimer: ReturnType<typeof setTimeout> | null = null
watch(() => props.missionSearch, (raw) => {
  if (searchFetchTimer) { clearTimeout(searchFetchTimer); searchFetchTimer = null }
  const q = String(raw || '').trim()
  if (q.length < 2) { searchFetched.value = []; return }
  const seq = ++searchFetchSeq
  searchFetchTimer = setTimeout(async () => {
    try {
      // apiClient is not a static import in this file (see the party resolver
      // below) — keep the same dynamic-import shape rather than adding one.
      const { apiClient } = await import('@/services/api/client')
      const { data } = await apiClient.get('/agents/locations/', { params: { q, budget: 60 } })
      if (seq !== searchFetchSeq) return          // a newer keystroke already won
      const rows = (data?.locations || data?.agents || []) as any[]
      searchFetched.value = rows
        .filter(r => r && r.matched_search && r.did)
        .slice(0, 48)
        .map(r => ({
          id: r.did, did: r.did, name: r.name || r.did,
          description: '', is_active: (r.status || 'active') !== 'inactive',
          origin_registry_name: r.origin_registry || null,
          capabilities: [], card_data: {},
        }))
    } catch {
      // A search that cannot reach the server narrows to what is already drawn,
      // which is the old behaviour — never an error in the operator's face.
      if (seq === searchFetchSeq) searchFetched.value = []
    }
  }, 350)
}, { immediate: false })

const canvasSourceAgents = computed(() => {
  let filtered = allAgents.value
  if (selectedCapabilities.value.length > 0) {
    filtered = filtered.filter(agent =>
      selectedCapabilities.value.every(cap => (agent.capabilities || []).includes(cap))
    )
  }
  if (selectedRegistry.value !== 'all') {
    filtered = filtered.filter(agent => agent.registry_id === selectedRegistry.value)
  }
  // §BRIDGESEARCH — server-found matches join the source list, so everything
  // downstream (registry resolution, orbit, beacons) treats them as ordinary
  // agents. Deduped: a match already in the sample must not become two stars.
  const fetched = searchFetched.value
  if (fetched.length) {
    const have = new Set(filtered.map((a: any) => String(a.did || a.id || '').toLowerCase()))
    const add = fetched.filter((a: any) => !have.has(String(a.did || '').toLowerCase()))
    if (add.length) return filtered.concat(add as any)
  }
  return filtered
})

const paginatedAgents = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return filteredAgents.value.slice(start, end)
})

const totalPages = computed(() =>
  Math.ceil(filteredAgents.value.length / pageSize.value)
)

const registryOptions = computed(() => {
  const options = [{ value: 'all', label: 'All Registries' }]
  federationStore.registries.forEach(registry => {
    options.push({
      value: registry.id,
      label: registry.name
    })
  })
  return options
})

// Debounced search
const debouncedSearch = debounce((query: string) => {
  currentPage.value = 1 // Reset to first page on search
}, 300)

// Watchers
watch(searchQuery, (newQuery) => {
  debouncedSearch(newQuery)
})

watch([selectedCapabilities, selectedRegistry, sortBy], () => {
  currentPage.value = 1 // Reset to first page on filter change
})

// Methods
const viewAgent = (agent: Agent) => {
  const agentId = agent.did || String(agent.id) || ''
  if (!agentId) return
  router.push({
    name: 'agent-details',
    params: { agentId }
  })
}

const toggleCapability = (capability: string) => {
  const index = selectedCapabilities.value.indexOf(capability)
  if (index > -1) {
    selectedCapabilities.value.splice(index, 1)
  } else {
    selectedCapabilities.value.push(capability)
  }
}

const clearFilters = () => {
  searchQuery.value = ''
  selectedCapabilities.value = []
  selectedRegistry.value = 'all'
  sortBy.value = 'reputation'
}

const getReputationColor = (reputation: number) => {
  if (reputation >= 90) return 'text-green-600'
  if (reputation >= 70) return 'text-blue-600'
  if (reputation >= 50) return 'text-yellow-600'
  return 'text-gray-600'
}

const getReputationHex = (reputation: number): string => {
  if (reputation >= 95) return '#ffd700'
  if (reputation >= 80) return 'var(--nc-primary-bright)'
  if (reputation >= 60) return '#29b6f6'
  return '#4fc3f7'
}

const getReputationStars = (reputation: number) => {
  const stars = Math.round((reputation || 0) / 20)
  return '★'.repeat(stars) + '☆'.repeat(5 - stars)
}

const getActivityLevel = (requests: number) => {
  if (requests > 10000) return { label: 'Very High', color: 'text-green-600' }
  if (requests > 1000) return { label: 'High', color: 'text-blue-600' }
  if (requests > 100) return { label: 'Medium', color: 'text-yellow-600' }
  if (requests > 0) return { label: 'Low', color: 'text-gray-600' }
  return { label: 'Inactive', color: 'text-gray-400' }
}

const handleCanvasAgentClick = (mapAgent: MapAgent | null) => {
  if (!mapAgent) {
    selectedAgent.value = null
    selectedMapAgent.value = null
    if (props.selectionMode) emit('select-agent', null)
    return
  }
  const agent = filteredAgents.value.find(a => (a.did || String(a.id)) === mapAgent.did)
  if (agent) {
    selectedAgent.value = agent
    selectedMapAgent.value = mapAgent  // drives the canvas selection ring
  } else {
    selectedMapAgent.value = mapAgent
  }
  if (props.selectionMode) { emit('select-agent', mapAgent); return }
  /**
   * §BRIDGE R13 #2 — ON THE BRIDGE, PICKING A STAR PICKS THE AGENT.
   *
   * "i picked an agent by right clicking. another agent is selected in the top
   *  right. i think the selection is biting eachother!" — and the reason the
   * pick never landed is that the stage had NO selection path at all:
   * `BridgeStage` forwarded only `verb-click`, so clicking or right-clicking a
   * star did nothing while the quick actions kept saying "select an agent
   * first". Two names on screen and no way to reconcile them reads as a fight.
   *
   * In mission mode a click now SELECTS (and still opens the card, which is the
   * behaviour that already existed); the right-click handler on the canvas
   * selects WITHOUT opening anything, which is the gesture he actually used.
   */
  if (props.missionMode) emit('select-agent', mapAgent)
  // AW-aligned: open the rich Agent detail modal on click.
  if (mapAgent.did) showAgentModal.value = true
}

/** Right-click a star: select it as the action target, open nothing. */
const handleCanvasAgentContext = (mapAgent: MapAgent | null) => {
  if (mapAgent?.did) emit('select-agent', mapAgent)
}

const handleCanvasAgentHover = (mapAgent: MapAgent | null) => {
  if (mapAgent) {
    /*
     * §BRIDGE R9 — "please bring the on mouse hover labels from the agentworld".
     *
     * They were already imported and already wired; they simply never appeared
     * on the bridge, and the reason was this lookup. It resolved the hovered
     * STAR against `filteredAgents` — the LIST view's filtered, paginated set —
     * and returned `undefined` for anything not in it, which silently cleared
     * the hover. In mission mode the stars drawn are the viewer's OWN agents
     * plus counterparties synthesized for the stage, so essentially nothing the
     * user can hover is in that collection. Measured: the emit fired
     * (`__gmHoverAgent(did)` -> true) and no tooltip existed.
     *
     * The rich record is still preferred when it IS there (it carries
     * capabilities and origin); otherwise the MapAgent the canvas just handed
     * us is used as-is. It has name/did/status/reputation — enough for the
     * label — and the avatar/mTLS detail arrives from the same lazy by-did
     * profile the watcher already fetches.
     */
    const agent = filteredAgents.value.find(a => (a.did || String(a.id)) === mapAgent.did)
    hoveredAgent.value = (agent || (mapAgent.did ? (mapAgent as unknown as Agent) : null)) as Agent | null
    if (hoveredAgent.value) hoveredRegistry.value = null   // mutually exclusive with the registry card
  } else {
    hoveredAgent.value = null
  }
}

const handleCanvasRegistryClick = (reg: MapRegistry) => {
  if (props.selectionMode) { emit('select-registry', reg); return }
  // AW-aligned: registry orb → full Registry Card modal (the filter dropdown in
  // the toolbar still covers "show only this registry's agents").
  regCardPeer.value = ((reg.hopDepth ?? 1) === 0) ? null : (reg.name || null)
  regCardFallback.value = reg.name || null
  showRegCard.value = true
}

const goToPage = (page: number) => {
  if (page >= 1 && page <= totalPages.value) {
    currentPage.value = page
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

// Load data on mount
// 2026-05-05 audit HIGH-5: AbortController for in-flight fetches so a
// rapid view switch doesn't leave dangling promises that mutate refs on
// the unmounted component.
let mountAbort: AbortController | null = null

// 2026-06-04 — dedicated, isolated loader for the authoritative frame + mainframe
// metadata. Kept OUT of the main onMounted (whose long await chain short-circuited
// before reaching the inline version) so the golden-bridge classifier always has its
// source: /public/topology is the ONLY endpoint with correct trust_domain AND the
// signed-card-derived is_mainframe flag.
async function loadTopoMeta() {
  const { apiClient } = await import('@/services/api/client')
  // Retry: /public/topology rebuilds tiers per-call and can be slow/refused under
  // heavy frame load — a single failed fetch must NOT leave the chain topology
  // permanently flat (the whole GalacticMap parent-chain depends on topoFull).
  for (let attempt = 0; attempt < 4; attempt++) {
  try {
    const resp = await apiClient.get('/public/topology')
    const td = (resp.data || {}) as Record<string, RegistryLike[]>
    const meta = new Map<string, { td?: string | null; mf?: boolean }>()
    const full: TopoFullEntry[] = []
    const seenId = new Set<string>()
    for (const bucket of ['registries', 'frames', 'direct_peers', 'discovered', 'cloud_operators']) {
      for (const r of (td[bucket] || [])) {
        const nm = (r.name || '').trim().toLowerCase()
        if (nm) {
          const prev = meta.get(nm) || {}
          meta.set(nm, {
            td: (r as { trust_domain?: string | null }).trust_domain ?? prev.td,
            mf: ((r as { is_mainframe?: boolean }).is_mainframe === true) || prev.mf === true,
          })
        }
        // Tier buckets (NOT the flat 'registries' list) carry id + parent + hop.
        if (bucket !== 'registries') {
          const rr = r as unknown as TopoFullEntry
          const rid = rr.id
          if (rid != null && !seenId.has(String(rid))) {
            seenId.add(String(rid))
            full.push({
              id: rid, name: r.name || '', peer_type: rr.peer_type,
              parent_registry_id: rr.parent_registry_id ?? null,
              hop_distance: rr.hop_distance ?? null,
              trust_domain: rr.trust_domain ?? null,
              is_mainframe: rr.is_mainframe === true,
              base_url: rr.base_url || '',
            })
          }
        }
      }
    }
    topoMeta.value = meta
    topoFull.value = full
    return
  } catch { /* transient — back off + retry so the chain isn't left flat */
    await new Promise(r => setTimeout(r, 1500 * (attempt + 1)))
  }
  }
}
onMounted(loadTopoMeta)

onMounted(async () => {
  mountAbort = new AbortController()
  try {
    // 2026-05-05 audit Tier 3: hydrate localTrustDomain so frame
    // classification works on first render (instead of falling back to
    // 'unknown' before /federation/info resolves).
    await ensureLocalFrame()
    // OWL24 FIX-10: Fetch local registry name from backend config
    try {
      const { apiClient } = await import('@/services/api/client')
      const infoResp = await apiClient.get('/federation/info')
      const regName = infoResp.data?.registry_name
      if (regName) {
        // 2026-06-08: cloud-ops report REGISTRY_NAME = container name
        // "cloud-op-op-<x>"; strip that prefix so the LOCAL node uses the op-*
        // convention (matches how peers render it + the self-row slug). Mainframes
        // ("Registry-A") have no prefix → keep the legacy dash→space display.
        localRegistryName.value = regName.startsWith('cloud-op-')
          ? regName.replace(/^cloud-op-/, '')
          : regName.replace(/-/g, ' ')
        import.meta.env.DEV && console.log(`[GalacticMap] Local registry name: '${localRegistryName.value}'`)
      }
    } catch (infoErr) {
      log.warn('Could not fetch registry name, using default:', infoErr)
    }

    await Promise.all([
      agentStore.fetchAllForMap(),  // Secondary: /agent-cards/?include_federated (capped)
      federationStore.fetchRegistries(),
      // Primary: /agents/locations/ — DISTINCT ON (did), 2000 cap, reaches all ops.
      (async () => {
        try {
          const { apiClient } = await import('@/services/api/client')
          const locResp = await apiClient.get('/agents/locations/', { signal: mountAbort?.signal })
          if (mountAbort?.signal.aborted) return
          locationsData.value = (locResp.data as { locations?: AgentLocation[] })?.locations || []
          populationIndexRef.value = buildPopulationIndex((locResp.data as { registries?: never[] })?.registries)
          import.meta.env.DEV && console.log(`[GalacticMap] /agents/locations/ → ${locationsData.value.length} entries`)
        } catch (locErr: unknown) {
          if (locErr?.name === 'CanceledError' || locErr?.code === 'ERR_CANCELED') return
          log.warn('/agents/locations/ fetch failed:', locErr)
        }
      })()
    ])

    // Pre-seed topology from backend BFS (server-side, cached 5min, all registries instantly)
    // Note: topology.loading starts as true (composable default) — spinner shows from first render
    try {
      const { apiClient } = await import('@/services/api/client')
      const trustedResp = await apiClient.get('/agents/locations/trusted-registries', { signal: mountAbort?.signal })
      if (mountAbort?.signal.aborted) return
      const trustedRegs: RegistryLike[] = trustedResp.data?.registries || []
      for (const tr of trustedRegs) {
        const pub = tr.public_url || ''
        if (!pub || !tr.name) continue
        const dk = domainKey(pub)
        if (!topology.registries.has(dk) && dk !== '__local__') {
          topology.registries.set(dk, {
            name: tr.name,
            publicUrl: pub,
            domain: dk,
            hopDepth: tr.hop || 2,
            // Tier 3: forward backend trust_domain so frame classifier
            // can use it without hitting the network again.
            trust_domain: tr.trust_domain,
          })
        }
      }
    } catch { /* non-blocking — client-side BFS will discover them anyway */ }

    // Client-side BFS still runs for edge discovery (connection lines between nodes)
    discoverTopology(federationStore.registries, localRegistryName.value, 6).then(() => {
      // Update registry count to include topology-discovered registries
      if (networkStats.value && mapRegistries.value.length > (networkStats.value.totalRegistries || 0)) {
        networkStats.value = { ...networkStats.value, totalRegistries: mapRegistries.value.length }
      }
    })

    // === DIAGNOSTIC: trace agent data pipeline ===
    const raw = agentStore.agents
    import.meta.env.DEV && console.log(`[GalacticMap:Parent] Store has ${raw.length} raw agents`)
    if (raw.length > 0) {
      import.meta.env.DEV && console.log(`[GalacticMap:Parent] First agent fields:`, Object.keys(raw[0]))
      import.meta.env.DEV && console.log(`[GalacticMap:Parent] First agent:`, { did: raw[0].did, name: raw[0].name, visibility: raw[0].visibility, registry_id: raw[0].registry_id })
    }
    import.meta.env.DEV && console.log(`[GalacticMap:Parent] allAgents: ${allAgents.value.length}, filteredAgents: ${filteredAgents.value.length}, mapAgents: ${mapAgents.value.length}`)
    if (filteredAgents.value.length > 0 && mapAgents.value.length === 0) {
      log.warn(`Parent: agents exist but mapAgents empty — check .did filter. DIDs:`, filteredAgents.value.map(a => a.did))
    }
    
    // Fetch reputation rankings (non-blocking, public endpoint)
    try {
      const { apiClient } = await import('@/services/api/client')
      const rankResp = await apiClient.get('/teg/reputation/rankings', { params: { limit: 200 } })
      const rankings = rankResp.data?.rankings || []
      const map = new Map<string, { tier: string; score: number; txs: number }>()
      for (const r of rankings) {
        if (r.agent_id) {
          map.set(r.agent_id, {
            tier: r.reputation_tier || 'standard',
            score: r.reputation_score || 0,
            txs: r.total_transactions || 0,
          })
        }
      }
      reputationRankings.value = map
      import.meta.env.DEV && console.log(`[GalacticMap] Loaded ${map.size} reputation rankings`)
    } catch (rankErr) {
      log.warn('Reputation rankings unavailable:', rankErr)
    }

    // Fetch network stats (non-blocking)
    try {
      const { federationApi } = await import('@/services/api/federation')
      const stats = await federationApi.getNetworkStats()
      networkStats.value = {
        totalRegistries: stats.totalRegistries || 1,
        activeRegistries: stats.activeRegistries || 0,
        totalAgents: stats.totalAgents || filteredAgents.value.length,
        networkHealth: stats.networkHealth ?? 100,
        lastGlobalSync: stats.lastGlobalSync || null,
      }
    } catch (statsErr) {
      log.warn('Network stats unavailable:', statsErr)
      networkStats.value = {
        totalRegistries: Math.max(1, federationStore.registries.length),
        activeRegistries: federationStore.connectedRegistries.length,
        totalAgents: filteredAgents.value.length,
        networkHealth: 100,
        lastGlobalSync: null,
      }
    }
  } catch (error) {
    uiStore.showNotification({
      type: 'error',
      title: 'Load Failed',
      message: 'Could not load agent data'
    })
  } finally {
    // GM1 (audit 2026-05-07): flip loading flag once initial data arrives.
    initialLoad.value = false
  }
})

// 2026-05-05 audit HIGH-5: abort in-flight onMounted fetches so a rapid
// view-switch doesn't mutate refs on the unmounted component.
onUnmounted(() => {
  if (mountAbort) {
    mountAbort.abort()
    mountAbort = null
  }
})

// IRONHAND mTLS Theatre embed: expose canvas projection + the REAL node list (read-only).
/**
 * §BRIDGE §7.4 — the agent set the CANVAS receives.
 *
 * LOD, and the reason it matters: the map view hands the canvas every agent it
 * knows about and builds one sprite per agent. On /galactic-map that is the
 * point — you went there to see them. On the Mission Control STAGE it is not:
 * the stage is a full-viewport background on the authenticated landing page,
 * and building ~2,100 sprites (frame-c; ~3,600 on registry-a) blocks the main
 * thread on mount and burns frames forever after. Measured on this box: the
 * battery's own probes could not get a reply out of the renderer for minutes.
 *
 * So in mission mode the stage draws individual stars for the viewer's OWN
 * agents only — which is also exactly what the brief asks for ("what are MY
 * agents doing"); the wider population is the galaxy's density, not N sprites.
 * An empty `onlyAgentDids` in mission mode means "none", NOT "all": falling back
 * to the whole population is the very thing this guards against.
 *
 * Non-mission callers keep the previous expression byte-for-byte, so
 * /galactic-map and /galactic-command are untouched (§7.5 mode isolation).
 */
/**
 * DID -> registry, for the stage's arc endpoints (§BRIDGE R1.5).
 *
 * Ledger payloads name PARTIES (DIDs); the renderer places SYSTEMS. Without
 * this translation every arc collapsed to a frame centroid, which is why the
 * stage read as three blobs trading with each other rather than as a network.
 * Built from the /agents/locations/ rows the map already has — this adds no
 * fetch and creates no second source of population truth (§FANOUTFIX).
 */
/**
 * Where does this party live? Registry precision first, frame second, and a
 * refusal third — a star with no home we can name is simply not drawn.
 * Resolved HERE because this is the component that knows the registry list.
 */
/**
 * A registry NAME -> the map node that is that registry, or null.
 *
 * Factored out of `counterpartyHome` so §OWNEDHOMES asks the same question the
 * same way (§FANOUTFIX: one predicate, asked in both places, or the two drift
 * and exactly one class of row goes missing). Normalised, because the same
 * registry is spelled 'Frame-B', 'frame-b' and 'frame_b' by three different
 * sources on this network.
 */
function registryIdByName(names: Array<string | null | undefined>): string | null {
  const regs = mapRegistries.value || []
  const norm = (x: any) => String(x || '').toLowerCase().replace(/[^a-z0-9]/g, '')
  for (const nm of names) {
    const n = norm(nm)
    if (!n) continue
    const hit = regs.find((r: any) =>
      norm(r.name) === n || norm(r.displayName) === n || norm(r.id) === n)
    if (hit) return hit.id
  }
  return null
}

function counterpartyHome(didLower: string, frameHint?: string | null): string | null {
  const regName = (didRegistry.value || {})[didLower]
  const regs = mapRegistries.value || []
  if (regName) {
    const hit = registryIdByName([regName])
    if (hit) return hit
  }
  const dom = (didFrame.value || {})[didLower]
  if (dom) {
    const d = String(dom).toLowerCase()
    const main = regs.find((r: any) => String(r.trustDomain || '').toLowerCase() === d &&
      ['local', 'frame'].includes(String(r.peerType || '').toLowerCase()))
    if (main) return main.id
    const any = regs.find((r: any) => String(r.trustDomain || '').toLowerCase() === d)
    if (any) return any.id
  }
  // The frame the event actually settled on. Last, because it is the coarsest
  // truth — but it IS a truth, and it is the one that covers the parties the
  // locations sample never returns.
  if (frameHint) {
    const key = String(frameHint).trim().toUpperCase().replace(/^FRAME[-_]?/, '')
    const seed = FRAMES.find(f => f.key.toUpperCase() === key ||
      (f.trustDomain || '').toLowerCase() === String(frameHint).toLowerCase())
    const dom2 = (seed?.trustDomain || '').toLowerCase()
    if (dom2) {
      const main = regs.find((r: any) => String(r.trustDomain || '').toLowerCase() === dom2 &&
        ['local', 'frame'].includes(String(r.peerType || '').toLowerCase()))
      if (main) return main.id
      const any2 = regs.find((r: any) => String(r.trustDomain || '').toLowerCase() === dom2)
      if (any2) return any2.id
    }
  }
  return null
}

/*
 * ON-DEMAND PARTY RESOLUTION (§BRIDGE R6).
 *
 * `/agents/locations/` is a SAMPLE. At its default budget it returns 6,000 rows
 * for a population of ~12,800, and the parties that actually transact are
 * mostly not in it — which is why most arcs could only reach a frame's registry
 * rather than the agent itself.
 *
 * The fix is not to download the population. `?budget=0` does return all 12,827
 * rows, but that is 3MB and 1.6s on a landing page, which is precisely the kind
 * of thing that makes this page feel heavy. Instead: resolve the handful of
 * parties we ACTUALLY SEE, one small public call each (`/agents/by-did/{did}`,
 * measured 42ms / 3.5KB), cached for the session and bounded hard.
 *
 * Resolve what you see; do not fetch what you might need.
 */
const RESOLVE_MAX = 200          // per session
const RESOLVE_CONCURRENCY = 4
const resolvedHome = ref<Record<string, string>>({})
const resolveTried = new Set<string>()
let resolveInFlight = 0
const resolveQueue: string[] = []

function queuePartyResolve(didLower: string): void {
  // §BRIDGE R9 — the ONE classifier decides what may reach the network. A UUID
  // or a system account is a perfectly good identity for matching and a
  // guaranteed 404 here; four such calls were measured on a single page load
  // (342df814-…, 86e776c5-…, teg:system:fee_collector), each one a red console
  // error on the Commander's screen.
  if (!didOrNull(didLower)) return
  if (!didLower || resolveTried.has(didLower)) return
  if (resolveTried.size >= RESOLVE_MAX) return
  if ((didRegistry.value || {})[didLower]) return
  resolveTried.add(didLower)
  resolveQueue.push(didLower)
  void pumpPartyResolve()
}

async function pumpPartyResolve(): Promise<void> {
  while (resolveInFlight < RESOLVE_CONCURRENCY && resolveQueue.length) {
    const did = resolveQueue.shift()!
    resolveInFlight++
    void (async () => {
      try {
        // Dynamic import, matching how the rest of this file reaches the client.
        const { apiClient } = await import('@/services/api/client')
        const r = await apiClient.get(`/agents/by-did/${encodeURIComponent(did)}`)
        const home = r.data?.origin_registry_name || r.data?.origin_registry || null
        // No origin means the agent is LOCAL to the registry serving this app —
        // that is what an absent origin means on this API, not "unknown".
        const local = mapRegistries.value.find((x: any) =>
          ['local'].includes(String(x.peerType || '').toLowerCase()))
        const val = home || local?.name || null
        if (val) resolvedHome.value = { ...resolvedHome.value, [did]: String(val) }
      } catch { /* a party we cannot resolve simply stays unplaced */ } finally {
        resolveInFlight--
        void pumpPartyResolve()
      }
    })()
  }
}

const didFrame = computed<Record<string, string>>(() => {
  // `trust_domain` is on EVERY locations row; `origin_registry` is on 4,114 of
  // 6,000. So this map is the reliable one, and the registry map above is the
  // precise one — the canvas prefers precision and falls back to reliability,
  // rather than falling back to an average of everything (the old centroid).
  const out: Record<string, string> = {}
  for (const loc of (locationsData.value || []) as any[]) {
    const did = loc?.did
    const dom = loc?.trust_domain || loc?.trustDomain
    if (did && dom) out[String(did).toLowerCase()] = String(dom)
  }
  return out
})

const didRegistry = computed<Record<string, string>>(() => {
  // Resolved-on-demand first: it is the precise answer for a party we have
  // actually seen, where the locations sample is a lucky guess at best.
  const out: Record<string, string> = { ...resolvedHome.value }
  for (const loc of (locationsData.value || []) as any[]) {
    const did = loc?.did
    if (!did) continue
    const reg = loc.origin_registry || loc.origin_registry_name || loc.registry_name
    if (reg) out[String(did).toLowerCase()] = String(reg)
  }
  // Agents with no origin recorded are LOCAL to the registry serving this app.
  for (const a of (filteredAgents.value || []) as any[]) {
    const did = a?.did
    if (!did) continue
    const k = String(did).toLowerCase()
    if (out[k]) continue
    const reg = a.origin_registry_name || a.origin_registry
    if (reg) out[k] = String(reg)
  }
  return out
})

/*
 * THE POPULATION, for the stage's density cloud (§BRIDGE R7).
 *
 * "we need to increase population. yes." — and the way to do that is NOT more
 * sprites. `mapAgents` is already loaded by this view for the full map; mission
 * mode simply hands the same list to the canvas to draw as points. No extra
 * fetch, no second source of population truth, and the individually-bright
 * stars stay exactly as capped as they were.
 *
 * Bounded anyway: a cloud is one draw call, but it is still N floats, and a
 * federation that grows to a million agents should not put a million vertices
 * in a browser. 8,000 is far past what reads as "full" on screen.
 */
const DENSITY_CAP = 8000
const densityAgents = computed<MapAgent[]>(() => {
  if (!props.missionMode) return []
  const all = mapAgents.value || []
  return all.length > DENSITY_CAP ? all.slice(0, DENSITY_CAP) : all
})

const canvasAgents = computed<MapAgent[]>(() => {
  if (props.embedded && props.hideAgents) return []
  const only = props.onlyAgentDids
  if (props.missionMode) {
    if (!only || !only.length) return []
    const mine = new Set(only.map(d => String(d).toLowerCase()))
    const ours = mapAgents.value.filter(a => mine.has(String(a.did || '').toLowerCase()))

    /*
     * COUNTERPARTY STARS (§BRIDGE R5).
     *
     * "maybe unhide the agents that we are interacting with. which are not mine
     *  on this frame. the agent could show up with opacity."
     *
     * Only the parties actually seen in traffic, bounded, and dim. Where the
     * map already knows the agent we use its real record; where it does not —
     * and `/agents/locations/` returns a 6,000-row SAMPLE, so it often does not
     * — we place a minimal star at the registry the party belongs to. That is
     * not an invented position: every agent star on this map is a deterministic
     * orbit around its registry seeded from its own DID, so this one is placed
     * by exactly the same rule as the rest.
     */
    const cps = (props.counterparties || [])
      .map(c => ({ did: String(c.did || '').toLowerCase(), frame: c.frame }))
      .filter(c => c.did && !mine.has(c.did))
    // These are the parties on screen right now: ask the API where they live.
    for (const c of cps) queuePartyResolve(c.did)

    /*
     * SEARCH MATCHES BECOME STARS (§BRIDGE R10). Highlighting can only work on
     * something that is drawn, and mission mode deliberately draws a bounded
     * set (P1: one sprite per agent locked the renderer for minutes). So a
     * query promotes its matches — capped, dim, placed by the SAME deterministic
     * DID-seeded orbit every other star uses, and never at an invented position.
     * §BRIDGESEARCH (2026-08-21) widened the POOL those matches are drawn from:
     * an explicit query also asks the server, so an agent outside this view's
     * sample (Hagrid, who lives on Registry-A) can be found from here.
     */
    const q = (props.missionSearch || '').trim().toLowerCase()
    const hits: MapAgent[] = []
    if (q.length >= 2) {
      const seen = new Set<string>(mine)
      for (const a of mapAgents.value) {
        const did = String(a.did || '').toLowerCase()
        if (!did || seen.has(did)) continue
        if (!(String(a.name || '').toLowerCase().includes(q) || did.includes(q))) continue
        seen.add(did)
        hits.push({ ...a, dim: true })
        if (hits.length >= 48) break
      }
    }
    /*
     * §OWNEDHOMES (2026-08-21) — DRAW THE AGENTS HE OWNS, NOT THE ONES THE
     * SAMPLE HAPPENED TO RETURN.
     *
     * `ours` is a FILTER over `mapAgents`, and `mapAgents` comes from
     * `/agents/locations/`, which is a 6,000-row SAMPLE of ~13,800. Measured on
     * frame-c: 1,689 of his 4,440 owned agents were in it (38%) and NOT ONE of
     * the agents he owns on another registry was — so "only five registries
     * have agents orbiting them" was never about the star budget at all. The
     * five were simply the registries where his ownership and the sample
     * happened to intersect.
     *
     * A star for an owned agent the sample skipped is not an invention: it is
     * placed at the registry that registry says it lives on, by the same
     * deterministic DID-seeded orbit every other star on this map uses — the
     * mechanism already proven for counterparty stars and search hits directly
     * below. And the rule below is the rule here: a home we cannot name gets
     * NO star, never a guessed one.
     */
    const ownedExtra: MapAgent[] = []
    const homeRows = props.ownedHomes || []
    if (homeRows.length) {
      const drawn = new Set(ours.map(a => String(a.did || '').toLowerCase()))
      for (const h of homeRows) {
        const did = String(h?.did || '').toLowerCase()
        if (!did || !mine.has(did) || drawn.has(did)) continue
        /*
         * NAMES ONLY — deliberately no trust-domain fallback here.
         *
         * An operator's trust domain is its PARENT FRAME (op-berlin ->
         * agentvault.com), so falling back to it would put every berlin agent
         * in orbit around Registry-A. `counterpartyHome` may do that because
         * for a passing event the frame IS the coarsest available truth; for an
         * agent you OWN we know the registry exactly, and a star at the wrong
         * planet is worse than no star: you cannot falsify it by looking.
         */
        const regId = h.local ? LOCAL_REGISTRY_ID : registryIdByName(h.names || [])
        if (!regId) continue
        drawn.add(did)
        ownedExtra.push({
          did: h.did, name: h.name || (did.length > 22 ? `${h.did.slice(0, 14)}…${h.did.slice(-4)}` : h.did),
          description: '', status: 'active', registryId: regId,
          reputation: 0, reputationTier: 'standard', totalTransactions: 0,
          liquidBalance: 0, stakedBalance: 0, capabilities: [],
          isVerified: false, isSynced: true, createdAt: new Date(0).toISOString(),
        })
      }
    }

    if (!cps.length && !hits.length) return ownedExtra.length ? ours.concat(ownedExtra) : ours
    const known = new Map(mapAgents.value.map(a => [String(a.did || '').toLowerCase(), a]))
    const extra: MapAgent[] = []
    for (const { did, frame } of cps.slice(0, 64)) {
      const hit = known.get(did)
      if (hit) { extra.push({ ...hit, dim: true }); continue }
      const regId = counterpartyHome(did, frame)
      if (!regId) continue        // no home we can name -> no star. Never guess one.
      extra.push({
        did, name: did.length > 22 ? `${did.slice(0, 14)}…${did.slice(-4)}` : did,
        description: '', status: 'active', registryId: regId,
        reputation: 0, reputationTier: 'standard', totalTransactions: 0,
        liquidBalance: 0, stakedBalance: 0, capabilities: [],
        isVerified: false, isSynced: true, createdAt: new Date(0).toISOString(),
        dim: true,
      })
    }
    return ours.concat(ownedExtra, extra, hits)
  }
  if (only && only.length) return mapAgents.value.filter(a => only.includes(a.did))
  return mapAgents.value
})

defineExpose({
  getNodePos: (id: string) => gmCanvasRef.value?.getNodePos?.(id) ?? null,
  getCamera: () => gmCanvasRef.value?.getCamera?.() ?? null,
  getContainer: () => gmCanvasRef.value?.getContainer?.() ?? null,
  getNodes: () => mapRegistries.value.map((r: any) => ({ id: r.id, name: r.name, trustDomain: r.trustDomain })),
  // §BRIDGE — pass the stage control surface straight through to the host.
  pushVerbs: (batch: any[]) => gmCanvasRef.value?.pushVerbs?.(batch),
  missionBoost: (ms?: number) => gmCanvasRef.value?.missionBoost?.(ms),
  setFleetLens: (on: boolean) => gmCanvasRef.value?.setFleetLens?.(on),
  /* §BRIDGE R14 — these MUST be forwarded here, not only on the canvas.
   * BridgeStage's `ref="mapRef"` points at THIS VIEW, which re-exposes a curated
   * subset of the canvas. R14.4 and R14.2 were added to the canvas's expose only,
   * so `mapRef.value.setAtmosphere` and `.noteWeather` were undefined while
   * `.bridgeStats` on the same ref worked perfectly — the two failures looked
   * unrelated and neither threw, because `?.()` on a missing method is silent.
   * Measured on the canary: rawSeen=66, countedSeen=45, weatherDelivered=0,
   * hasNote=false. The classifier was never the problem. */
  setAtmosphere: (mode: string) => gmCanvasRef.value?.setAtmosphere?.(mode),
  noteWeather: (frameKey: string) => gmCanvasRef.value?.noteWeather?.(frameKey),
  setFollowAgent: (did: string | null) => gmCanvasRef.value?.setFollowAgent?.(did) ?? false,
  isFollowing: () => gmCanvasRef.value?.isFollowing?.() ?? null,
  verbScreenPositions: () => gmCanvasRef.value?.verbScreenPositions?.() ?? [],
  agentScreenPositions: () => gmCanvasRef.value?.agentScreenPositions?.() ?? [],
  /**
   * §BRIDGE R13 #8 — what the hover card would be BUILT FROM, for one agent.
   *
   * The visual hover cannot be asserted headlessly: these are 2-3px objects in
   * orbit on a software renderer, and `performRaycast` overwrites any injected
   * hover within a frame (§BRIDGE R9). But the card is a pure function of the
   * `entity`, so the honest gate is the DATA: drive the same hover handler, wait
   * for the same two cached fetches the real hover triggers, and hand back the
   * same computed the template renders. If the balances and the proven work are
   * in here, they are on the card.
   */
  hoverEntityFor: async (did: string) => {
    const list: any[] = (gmCanvasRef.value?.agentScreenPositions?.() ?? [])
    const target = did ? { did } : list[0]
    if (!target?.did) return null
    const fake = { did: target.did, name: target.name || target.did.slice(0, 12) } as any
    // Kick the two cached fetches the real hover triggers.
    handleCanvasAgentHover(fake)
    for (let i = 0; i < 40; i++) {
      const haveProfile = target.did in hoverAgentProfiles.value && hoverAgentProfiles.value[target.did] !== null
      const haveTr = target.did in hoverTrackRecords.value
      if (haveProfile && haveTr) break
      await new Promise(r => setTimeout(r, 250))
    }
    // ⚠ RE-ASSERT, THEN READ IN THE SAME TICK. `performRaycast` runs every third
    // frame and emits `agent-hover(null)` whenever the real pointer is not over
    // a star, so an injected hover is cleared long before an await loop ends —
    // the §BRIDGE R9 trap, which I quoted three lines above this and then walked
    // straight into: the first version of this probe returned null every time
    // and looked like missing data rather than a cleared ref.
    handleCanvasAgentHover(fake)
    const snap = galacticAgentEntity.value          // computed = synchronous
    return JSON.parse(JSON.stringify(snap ?? null))
  },
  /** How many of the POPULATION match the live query (not just the drawn stars) —
   *  so the HUD can report honestly when a match exists beyond the cap. */
  searchMatchCount: () => {
    const q = (effectiveSearch.value || '').trim().toLowerCase()
    if (q.length < 2) return 0
    let n = 0
    for (const a of mapAgents.value) {
      if (String(a.name || '').toLowerCase().includes(q) || String(a.did || '').toLowerCase().includes(q)) n++
    }
    return n
  },
  searchMatchDids: () => {
    const q = (effectiveSearch.value || '').trim().toLowerCase()
    if (q.length < 2) return []
    const out: string[] = []
    for (const a of mapAgents.value) {
      if (String(a.name || '').toLowerCase().includes(q) || String(a.did || '').toLowerCase().includes(q)) {
        if (a.did) out.push(String(a.did))
      }
      if (out.length >= 48) break
    }
    return out
  },
  densityByRegistry: () => gmCanvasRef.value?.densityByRegistry?.() ?? null,
  /** did -> registry id, so a probe can prove WHERE the population was placed. */
  registryIndex: () => mapRegistries.value.map((r: any) => ({ id: r.id, name: r.name, trustDomain: r.trustDomain, frame: r.frame })),
  bridgeStats: () => gmCanvasRef.value?.bridgeStats?.() ?? null,
  registryCount: () => mapRegistries.value.length,
  /**
   * The canvas has owned `setCamera`/`cameraState` for a while, but this file
   * re-exposes a CURATED SUBSET (§R14 #6), so nothing outside could reach them
   * and framing a screenshot meant wheel events that never landed on
   * OrbitControls. Read-only + a deliberate setter, debug-hook use only.
   */
  cameraState: () => gmCanvasRef.value?.cameraState?.() ?? null,
  setCamera: (x: number, y: number, z: number) => gmCanvasRef.value?.setCamera?.(x, y, z) ?? false,
})
</script>

<template>
  <div class="galactic-map hm-module" :class="{ 'gm-embedded': props.embedded, 'gm-mission': props.missionMode }">
    <!-- 2026-05-07: ambient bg (matches Federation/MyAgents/AdminCanaries). -->
    <div class="p-6 gm-content">
      <!-- Header — compact cosmic strip (search/filter now lives in-canvas) -->
      <div class="gm-pagehead" data-tour="gmap-hero">
        <h1 class="gm-pagetitle"><span class="gm-pagetitle-dot"></span>{{ t('agents.galacticMap') }}</h1>
        <span class="gm-pagesub">{{ t('agents.galacticMapDescription') }}</span>
      </div>

      <!-- GM1 (audit 2026-05-07): top-level loading indicator -->
      <div v-if="initialLoad" class="gm-initial-loading">
        <div class="gm-loader" aria-hidden="true">
          <span class="gm-loader__core"></span>
          <span class="gm-loader__orbit"><i></i></span>
        </div>
        <span>Connecting to federated topology…</span>
      </div>

      <!-- NON-MAP VIEWS: Loading, Empty, Grid, List -->
      <template v-if="viewMode !== 'map'">
        <!-- Cosmic browse controls (replaces the legacy gray bar) -->
        <GalacticControls
          variant="bar"
          class="gm-browse-controls"
          :frames="availableFrames"
          :registry-options="registryOptions"
          :sort-options="sortOptions"
          :capabilities="availableCapabilities"
          :result-count="filteredAgents.length"
          v-model:search="searchQuery"
          v-model:frame="selectedFrame"
          v-model:registry="selectedRegistry"
          v-model:sort="sortBy"
          v-model:view="viewMode"
          v-model:selected-capabilities="selectedCapabilities"
        />
        <!-- Loading State -->
        <LoadingState
          v-if="agentStore.loading"
          :message="t('agents.discoveringAgents')"
        />

        <!-- Empty State -->
        <div
          v-else-if="filteredAgents.length === 0"
          class="bg-white dark:bg-gray-800 rounded-lg shadow-xs p-12 text-center"
        >
          <div class="max-w-md mx-auto">
            <div class="text-6xl mb-4"><Icon name="mdi:magnify" /></div>
            <h3 class="text-xl font-semibold text-gray-900 dark:text-white mb-2">
              No agents found
            </h3>
            <p class="text-gray-600 dark:text-gray-400 mb-6">
              Try adjusting your search criteria or filters
            </p>
            <button
              @click="clearFilters"
              class="text-blue-600 hover:text-blue-700 font-medium"
            >
              Clear all filters
            </button>
          </div>
        </div>

        <!-- Grid View -->
        <div
          v-else-if="viewMode === 'grid'"
        class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"
      >
        <div
          v-for="agent in paginatedAgents"
          :key="agent.did"
          @click="viewAgent(agent)"
          class="bg-white dark:bg-gray-800 rounded-lg shadow-xs hover:shadow-lg transition-all duration-200 cursor-pointer overflow-hidden group"
        >
          <!-- Agent Card Compact -->
          <div class="p-6">
            <!-- Header -->
            <div class="flex items-start justify-between mb-3">
              <div class="flex-1 min-w-0">
                <h3 class="text-lg font-semibold text-gray-900 dark:text-white truncate group-hover:text-blue-600 dark:group-hover:text-blue-400">
                  {{ agent.name }}
                </h3>
                <p class="text-xs text-gray-500 dark:text-gray-400 truncate">
                  {{ agent.did }}
                </p>
              </div>
              <div
                v-if="agent.verified"
                class="ml-2 text-blue-600"
                title="Verified Agent"
              >
                <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                </svg>
              </div>
            </div>

            <!-- Reputation -->
            <div class="mb-3">
              <div class="flex items-center gap-2">
                <span :class="getReputationColor(agent.reputation || 0)" class="text-sm font-medium">
                  {{ getReputationStars(agent.reputation || 0) }}
                </span>
                <span class="text-xs text-gray-500 dark:text-gray-400">
                  {{ agent.reputation || 0 }}
                </span>
              </div>
            </div>

            <!-- Description -->
            <p class="text-sm text-gray-600 dark:text-gray-400 mb-4 line-clamp-2">
              {{ agent.description || 'No description available' }}
            </p>

            <!-- Capabilities -->
            <div class="mb-4">
              <div class="flex flex-wrap gap-1">
                <span
                  v-for="(capability, index) in (agent.capabilities || []).slice(0, 3)"
                  :key="capability"
                  class="inline-block bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-2 py-0.5 rounded-sm text-xs"
                >
                  {{ capability }}
                </span>
                <span
                  v-if="(agent.capabilities || []).length > 3"
                  class="inline-block text-gray-500 dark:text-gray-400 px-1 py-0.5 text-xs"
                >
                  +{{ (agent.capabilities || []).length - 3 }}
                </span>
              </div>
            </div>

            <!-- Footer -->
            <div class="flex justify-between items-center text-xs text-gray-500 dark:text-gray-400">
              <span>
                {{ formatDate(agent.created_at) }}
              </span>
              <span :class="getActivityLevel(agent.metrics?.total_requests || 0).color">
                {{ getActivityLevel(agent.metrics?.total_requests || 0).label }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- List View -->
      <div v-else-if="viewMode === 'list'" class="bg-white dark:bg-gray-800 rounded-lg shadow-xs overflow-hidden">
        <table class="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
          <thead class="bg-gray-50 dark:bg-gray-900">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Agent
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Reputation
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Capabilities
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Activity
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                Registry
              </th>
            </tr>
          </thead>
          <tbody class="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
            <tr
              v-for="agent in paginatedAgents"
              :key="agent.did"
              @click="viewAgent(agent)"
              class="hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer"
            >
              <td class="px-6 py-4">
                <div class="flex items-center">
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                      <p class="text-sm font-medium text-gray-900 dark:text-white truncate">
                        {{ agent.name }}
                      </p>
                      <svg
                        v-if="agent.verified"
                        class="w-4 h-4 text-blue-600"
                        fill="currentColor"
                        viewBox="0 0 20 20"
                      >
                        <path fill-rule="evenodd" d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
                      </svg>
                    </div>
                    <p class="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {{ agent.did }}
                    </p>
                  </div>
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center gap-2">
                  <span :class="getReputationColor(agent.reputation || 0)" class="text-sm">
                    {{ getReputationStars(agent.reputation || 0) }}
                  </span>
                  <span class="text-xs text-gray-500 dark:text-gray-400">
                    {{ agent.reputation || 0 }}
                  </span>
                </div>
              </td>
              <td class="px-6 py-4">
                <div class="flex flex-wrap gap-1">
                  <span
                    v-for="capability in (agent.capabilities || []).slice(0, 2)"
                    :key="capability"
                    class="inline-block bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 px-2 py-0.5 rounded-sm text-xs"
                  >
                    {{ capability }}
                  </span>
                  <span
                    v-if="(agent.capabilities || []).length > 2"
                    class="inline-block text-gray-500 dark:text-gray-400 px-1 py-0.5 text-xs"
                  >
                    +{{ (agent.capabilities || []).length - 2 }}
                  </span>
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <span
                  :class="[
                    'text-sm',
                    getActivityLevel(agent.metrics?.total_requests || 0).color
                  ]"
                >
                  {{ getActivityLevel(agent.metrics?.total_requests || 0).label }}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                {{ agent.registry_name || 'Local' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </template>

      <!-- MAP VIEW: Separate from v-if chain so WebGL context is NEVER destroyed -->
      <div v-if="viewMode === 'map'" data-tour="gmap-canvas" class="bg-gray-900 rounded-lg shadow-xs overflow-hidden gm-map-shell" style="height: calc(100vh - 172px); min-height: 640px;">
        <div class="relative h-full" @mousemove="onMapMouseMove">
          <!-- Topology loading overlay — wait for BFS edges before rendering -->
          <div v-if="topology.loading && mapRegistries.length <= 1" style="position:absolute;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);">
            <div style="text-align:center;">
              <div style="width:28px;height:28px;border:2px solid rgba(var(--nc-primary-rgb),0.15);border-top-color:var(--nc-primary);border-radius:50%;animation:gm-spin 0.8s linear infinite;margin:0 auto 12px;"></div>
              <style>@keyframes gm-spin { to { transform: rotate(360deg); } }</style>
              <span style="color:#64748b;font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:0.08em;">DISCOVERING NETWORK TOPOLOGY...</span>
            </div>
          </div>
          <!-- 3D Visualization Canvas -->
          <GalacticMapCanvas
            ref="gmCanvasRef"
            :embedded="props.embedded"
            :mode="props.missionMode ? 'mission' : 'full'"
            :busy-registry-ids="props.busyRegistryIds"
            :registries="mapRegistries"
            :agents="canvasAgents"
            :density-agents="densityAgents"
            :did-registry="didRegistry"
            :did-frame="didFrame"
            :network-stats="networkStats"
            :topology-version="topologyVersion"
            :selected-agent-did="selectedMapAgent?.did || null"
            :highlight-capability="selectedCapabilities[0] || null"
            :search-query="effectiveSearch"
            :show-labels="showLabels"
            @verb-click="(d: any) => emit('verb-click', d)"
            @agent-click="handleCanvasAgentClick"
            @agent-context="handleCanvasAgentContext"
            @agent-hover="handleCanvasAgentHover"
            @registry-click="handleCanvasRegistryClick"
            @registry-hover="handleCanvasRegistryHover"
            class="h-full"
          />

          <!-- AW-aligned click surfaces (agent orb → detail, registry orb → card) -->
          <!-- Hover tooltip (AgentWorld parity: avatar + rich label via shared TopologyHoverLabel) -->
          <Teleport to="body">
            <!-- Agent hover (shared TopologyHoverLabel + lazy avatar) -->
            <div v-if="hoveredAgent && !hoveredRegistry && !showAgentModal && !showRegCard" class="gm-hover-tooltip" :style="tooltipStyle">
              <TopologyHoverLabel v-if="galacticAgentEntity" :entity="galacticAgentEntity" :local-currency="localCurrency">
                <template #avatar>
                  <UserAvatar
                    v-if="hoveredAgent.did && hoverAgentProfiles[hoveredAgent.did]"
                    :user="hoverAgentProfiles[hoveredAgent.did]"
                    :avatar-url="(hoverAgentProfiles[hoveredAgent.did] as any)?.card_data?.iconUrl || (hoverAgentProfiles[hoveredAgent.did] as any)?.card_data?.icon_url || null"
                    :display-name="hoveredAgent.name"
                    size="md"
                    class="gm-tt-avatar"
                  />
                  <span v-else class="gm-tt-avatar-ph">●</span>
                </template>
              </TopologyHoverLabel>
            </div>
            <!-- Registry hover (rich AgentWorld-parity card; on-click opens the
                 full SovereignRegistryCard). Chrome-less wrapper — the card
                 carries its own chrome. -->
            <div v-if="hoveredRegistry && !showAgentModal && !showRegCard" class="gm-reg-tooltip" :style="tooltipStyle">
              <RegistryHoverCard v-if="galacticRegistryData" :registry="galacticRegistryData" :currency="hoveredRegCurrency" />
            </div>
          </Teleport>

          <AgentDetailModal v-model:show="showAgentModal" :agent-did="selectedMapAgent?.did || ''" />
          <SovereignRegistryCard v-model:show="showRegCard" :peer-name="regCardPeer" :fallback-name="regCardFallback" />

          <!-- ═══ IN-CANVAS SEARCH / FILTER OVERLAY (replaces legacy top bar) ═══ -->
          <GalacticControls
            variant="overlay"
            class="gm-overlay-controls"
            :class="{ 'gm-overlay-controls--embedded': props.embedded }"
            :show-view-modes="!props.embedded"
            :start-collapsed="props.embedded"
            :launcher-label="props.embedded ? 'Filter' : 'Search &amp; filter'"
            :frames="availableFrames"
            :registry-options="registryOptions"
            :sort-options="sortOptions"
            :capabilities="availableCapabilities"
            :result-count="filteredAgents.length"
            v-model:search="searchQuery"
            v-model:frame="selectedFrame"
            v-model:registry="selectedRegistry"
            v-model:sort="sortBy"
            v-model:view="viewMode"
            v-model:selected-capabilities="selectedCapabilities"
          />

          <!-- ═══ LEFT CONTROLS HUD ═══ -->
          <div class="gm-panel gm-controls" data-tour="gmap-hud" :class="{ 'gm-panel-collapsed': gmPanelCollapsed }">
            <div class="gm-panel-title" @click="gmPanelCollapsed = !gmPanelCollapsed">
              <span class="gm-title-inner"><span class="gm-title-dot"></span>GALACTIC MAP</span>
              <span class="gm-collapse-icon">{{ gmPanelCollapsed ? '▸' : '▾' }}</span>
            </div>

            <template v-if="!gmPanelCollapsed">
              <div class="gm-interact-guide">
                <div><kbd>Drag</kbd> Rotate view</div>
                <div><kbd>Scroll</kbd> Zoom</div>
                <div><kbd>Right-drag</kbd> Pan</div>
                <div><kbd>Click</kbd> Select node</div>
              </div>

              <div class="gm-legend-section">
                <div class="gm-legend-title">Agents · reputation</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#ffd700;box-shadow:0 0 7px #ffd700aa"></span>Elite · 95+</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:var(--nc-primary-bright);box-shadow:0 0 6px var(--nc-primary-bright)77"></span>High · 80+</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#4fc3f7"></span>Standard</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#ffab40;box-shadow:0 0 5px #ffab4066"></span>Federated · synced</div>
              </div>

              <div class="gm-legend-section">
                <div class="gm-legend-title">Sovereign frames</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#22d3ee;box-shadow:0 0 7px #22d3eeaa"></span>Frame A · genesis (AVT)</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#ff4fb4;box-shadow:0 0 7px #ff4fb4aa"></span>Frame B · magenta</div>
                <div class="gm-legend-row"><span class="gm-dot" style="background:#ffb43a;box-shadow:0 0 7px #ffb43aaa"></span>Frame C · amber (BVT)</div>
                <div class="gm-legend-row"><span class="gm-square"></span>Registry / mainframe node</div>
              </div>

              <div class="gm-legend-section">
                <div class="gm-legend-title">Federation beams</div>
                <div class="gm-legend-row"><span class="gm-beam-line gm-beam-gold"></span>Frame&nbsp;↔&nbsp;frame bridge</div>
                <div class="gm-legend-row"><span class="gm-beam-line" style="background:#5c9cf5;box-shadow:0 0 5px #5c9cf577"></span>Operator spoke · 1 hop</div>
                <div class="gm-legend-row"><span class="gm-beam-line" style="background:var(--nc-primary-bright);box-shadow:0 0 4px var(--nc-primary-bright)66"></span>2-hop relay</div>
                <div class="gm-legend-row"><span class="gm-beam-line" style="background:#e91e63;box-shadow:0 0 4px #e91e6377"></span>3-hop relay</div>
                <div class="gm-legend-row"><span class="gm-beam-line" style="background:#d50000;box-shadow:0 0 4px #d5000077"></span>4+ hop · deep</div>
              </div>

              <div class="gm-legend-section gm-legend-toggles">
                <div class="gm-toggle" :class="{ 'gm-toggle-on': showLabels }" @click="showLabels = !showLabels" role="switch" :aria-checked="showLabels">
                  <span class="gm-toggle-sw"><span class="gm-toggle-knob"></span></span>
                  <span class="gm-toggle-lbl">Registry names</span>
                </div>
              </div>
            </template>
          </div>

          <!-- ═══ SELECTED AGENT PANEL ═══ -->
          <div v-if="useLegacyAgentPanel && selectedAgent && selectedMapAgent" class="gm-panel gm-agent-panel">
            <div class="gm-ap-header">
              <div class="gm-ap-header-left">
                <div class="gm-ap-name-row">
                  <span class="gm-ap-tier-dot" :style="{ background: getReputationHex(selectedMapAgent.reputation || 0), boxShadow: '0 0 8px ' + getReputationHex(selectedMapAgent.reputation || 0) + '88' }"></span>
                  <h3 class="gm-ap-name">{{ selectedAgent.name }}</h3>
                </div>
                <p class="gm-ap-did">{{ selectedMapAgent.did }}</p>
              </div>
              <button class="gm-close-btn" @click="selectedAgent = null; selectedMapAgent = null">✕</button>
            </div>

            <div class="gm-ap-grid">
              <div class="gm-ap-cell">
                <span class="gm-ap-cell-label">Reputation</span>
                <span class="gm-ap-cell-value gm-ap-big" :style="{ color: getReputationHex(selectedMapAgent.reputation || 0) }">{{ selectedMapAgent.reputation || 0 }}</span>
              </div>
              <div class="gm-ap-cell">
                <span class="gm-ap-cell-label">Balance</span>
                <span class="gm-ap-cell-value gm-ap-big" style="color:#4fc3f7">{{ (selectedMapAgent.liquidBalance + selectedMapAgent.stakedBalance).toLocaleString(appLocale()) }}</span>
              </div>
              <div class="gm-ap-cell">
                <span class="gm-ap-cell-label">Registry</span>
                <span class="gm-ap-cell-value">{{ (selectedAgent as AgentLike).origin_registry_name || 'Local' }}
                  <span v-if="selectedMapAgent.isSynced" class="gm-synced-badge">SYNCED</span>
                </span>
              </div>
              <div class="gm-ap-cell">
                <span class="gm-ap-cell-label">Status</span>
                <span class="gm-ap-cell-value" style="display:flex;align-items:center;gap:5px">
                  <span class="gm-status-dot" :class="selectedMapAgent.status === 'active' ? 'active' : 'inactive'"></span>
                  <span style="text-transform:capitalize">{{ selectedMapAgent.status }}</span>
                </span>
              </div>
            </div>

            <div v-if="selectedMapAgent.capabilities.length > 0" class="gm-ap-caps">
              <span class="gm-ap-cell-label" style="margin-bottom:5px;display:block">Capabilities</span>
              <div class="gm-ap-caps-wrap">
                <span v-for="cap in selectedMapAgent.capabilities.slice(0, 8)" :key="cap" class="gm-cap-tag">{{ cap }}</span>
              </div>
            </div>

            <button class="gm-profile-btn" @click="viewAgent(selectedAgent)">View Full Profile</button>
          </div>

          <!-- ═══ STATS BAR ═══ -->
          <div class="gm-stats-bar">
            <div class="gm-stat-item"><strong class="gm-stat-num" style="color:var(--nc-primary-bright)">{{ filteredAgents.length }}</strong><span class="gm-stat-lbl">agents</span></div>
            <span class="gm-stat-sep"></span>
            <div class="gm-stat-item"><strong class="gm-stat-num" style="color:#00e676">{{ networkStats?.totalRegistries || 1 }}</strong><span class="gm-stat-lbl">registries</span></div>
            <span class="gm-stat-sep"></span>
            <div class="gm-stat-item"><strong class="gm-stat-num" :style="{ color: (networkStats?.networkHealth ?? 100) >= 80 ? '#00e676' : '#ffab40' }">{{ networkStats?.networkHealth ?? 100 }}%</strong><span class="gm-stat-lbl">health</span></div>
            <span class="gm-stat-sep"></span>
            <div class="gm-stat-item"><strong class="gm-stat-num" style="color:#ffd700">{{ networkStats?.activeRegistries || mapRegistries.length }}</strong><span class="gm-stat-lbl">active</span></div>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="totalPages > 1 && viewMode !== 'map'" class="mt-8 flex justify-center">
        <nav class="flex items-center gap-2">
          <!-- Previous -->
          <button
            @click="goToPage(currentPage - 1)"
            :disabled="currentPage === 1"
            class="p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
            </svg>
          </button>

          <!-- Page Numbers -->
          <div class="flex gap-1">
            <!-- First page -->
            <button
              v-if="currentPage > 3"
              @click="goToPage(1)"
              class="px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-sm"
            >
              1
            </button>
            <span v-if="currentPage > 4" class="px-2 py-2 text-gray-500">...</span>

            <!-- Nearby pages -->
            <button
              v-for="page in Array.from({ length: 5 }, (_, i) => currentPage - 2 + i).filter(p => p > 0 && p <= totalPages)"
              :key="page"
              @click="goToPage(page)"
              :class="[
                'px-3 py-2 rounded-lg border text-sm',
                page === currentPage
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'
              ]"
            >
              {{ page }}
            </button>

            <!-- Last page -->
            <span v-if="currentPage < totalPages - 3" class="px-2 py-2 text-gray-500">...</span>
            <button
              v-if="currentPage < totalPages - 2"
              @click="goToPage(totalPages)"
              class="px-3 py-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 text-sm"
            >
              {{ totalPages }}
            </button>
          </div>

          <!-- Next -->
          <button
            @click="goToPage(currentPage + 1)"
            :disabled="currentPage === totalPages"
            class="p-2 rounded-lg bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-50 dark:hover:bg-gray-700"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </nav>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* IRONHAND mTLS Theatre embed — hide page chrome + let the map-shell fill the host cell.
   Scoped to gm-embedded so the standalone Galactic Map is unaffected. */
/* Use .galactic-map.gm-embedded (2 classes) to beat the base .galactic-map rule's position/height. */
.galactic-map.gm-embedded { position: absolute !important; inset: 0 !important; height: auto !important; min-height: 0 !important; padding: 0 !important; }
.gm-embedded .galactic-canvas-wrapper, .gm-embedded .galactic-canvas { min-height: 0 !important; }
.gm-embedded .gm-content { height: 100%; padding: 0 !important; display: flex; flex-direction: column; min-height: 0; }
.gm-embedded .gm-pagehead, .gm-embedded .gm-initial-loading, .gm-embedded .gm-stats-bar, .gm-embedded .gm-browse-controls, .gm-embedded .gm-panel.gm-controls { display: none !important; }
/* GCC: the original galactic-map filter, surfaced in-canvas. Docked top-LEFT so it
   clears the event ticker (top-right) + Bridge (right column). Defaults collapsed to a
   small "Filter" pill (start-collapsed prop); expands in place, capped so it never
   reaches the ticker. (Commander 2026-06-11: "I miss filtering from the galactic map.") */
.gm-embedded .gm-overlay-controls.gc-overlay { left: 12px; top: 12px; transform: none; width: auto; max-width: min(560px, calc(100% - 400px)); }
.gm-embedded .gm-map-shell { flex: 1 1 auto !important; height: auto !important; min-height: 0 !important; border-radius: 0 !important; box-shadow: none !important; }

/* §BRIDGE — MISSION MODE. The stage sits full-bleed BEHIND the Mission Control
   HUD, so every remaining piece of map chrome (overlay controls, legend, hover
   cards, modals) is suppressed: the HUD owns all interaction, the stage owns
   the picture. Applied on top of gm-embedded, never instead of it. */
.galactic-map.gm-mission { position: absolute !important; inset: 0 !important; background: transparent !important; }
.gm-mission .gm-overlay-controls,
.gm-mission .gm-legend,
.gm-mission .gm-hover-card,
.gm-mission .gm-agent-panel,
.gm-mission .gm-view-toggle,
.gm-mission .gm-fab,
.gm-mission .gm-ambient { display: none !important; }
.gm-mission .gm-map-shell { background: transparent !important; border: 0 !important; }
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.galactic-map {
  min-height: calc(100vh - 64px);
  position: relative;
  background: #060b14;
}
/* 2026-05-07: content above ambient bg layer. */
.gm-content {
  position: relative;
  z-index: 1;
}
/* Compact cosmic page header (search/filter moved into the canvas overlay). */
.gm-pagehead {
  display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 14px;
}
.gm-pagetitle {
  display: inline-flex; align-items: center; gap: 10px;
  font-size: 1.65rem; font-weight: 700; letter-spacing: 0.01em; line-height: 1.1;
  color: #eaf3ff; text-shadow: 0 0 24px rgba(56,189,248,0.28);
}
.gm-pagetitle-dot {
  width: 9px; height: 9px; border-radius: 50%;
  background: radial-gradient(circle at 35% 35%, #7fe7ff, #2563eb);
  box-shadow: 0 0 14px 2px rgba(56,189,248,0.7);
  animation: gm-title-pulse 2s ease-in-out infinite alternate;
}
.gm-pagesub {
  color: rgba(150,180,215,0.72); font-size: 0.86rem; letter-spacing: 0.02em;
}
.gm-map-shell { position: relative; box-shadow: 0 18px 60px -24px rgba(0,0,0,0.8), 0 0 0 1px rgba(120,170,230,0.08) inset; }
/* Hover tooltip (AgentWorld-parity avatar label) */
.gm-hover-tooltip { position: fixed; pointer-events: none; z-index: 9999; max-width: 320px;
  background: rgba(8,12,22,0.93); border: 1px solid rgba(120,170,230,0.28); border-radius: 10px;
  padding: 10px 12px; box-shadow: 0 14px 44px -14px rgba(0,0,0,0.85); backdrop-filter: blur(6px); }
.gm-hover-tooltip .gm-tt-avatar { flex-shrink: 0; }
.gm-hover-tooltip .gm-tt-avatar-ph { display:inline-flex; align-items:center; justify-content:center;
  width:30px; height:30px; border-radius:50%; background: rgba(80,120,180,0.25); color:#7fd3ff; font-size:12px; }
/* Registry hover wrapper — chrome-less; RegistryHoverCard provides its own card chrome. */
.gm-reg-tooltip { position: fixed; pointer-events: none; z-index: 9999; }
/* GM1 (audit 2026-05-07): top-level loading indicator. */
.gm-initial-loading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  margin-bottom: 16px;
  border-radius: 10px;
  background: rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  color: rgba(255, 255, 255, 0.7);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 13px;
}
/* Compact cosmic orbital loader (replaces the flat 1-ring spinner) — a pulsing
   core orbited by a glowing node, matching the Universe view's loader. */
.gm-loader { position: relative; width: 20px; height: 20px; flex: none; }
.gm-loader__core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 5px;
  height: 5px;
  margin: -2.5px 0 0 -2.5px;
  border-radius: 50%;
  background: rgb(var(--nc-primary-rgb));
  box-shadow: 0 0 8px 1px rgba(var(--nc-primary-rgb), 0.8);
  animation: gm-core-pulse 1.8s ease-in-out infinite;
}
.gm-loader__orbit {
  position: absolute;
  inset: 0;
  border-radius: 50%;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  animation: gm-spin-ring 1.4s linear infinite;
}
.gm-loader__orbit i {
  position: absolute;
  top: -2px;
  left: 50%;
  width: 4px;
  height: 4px;
  margin-left: -2px;
  border-radius: 50%;
  background: rgb(var(--nc-primary-rgb));
  box-shadow: 0 0 6px 1px rgba(var(--nc-primary-rgb), 0.9);
}
@keyframes gm-spin-ring { to { transform: rotate(360deg); } }
@keyframes gm-core-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.5); opacity: 0.7; } }

/* ═══════════════════════════════════════════════════════════════════════
   GALACTIC MAP HUD — AAA glass-morphism panels
   Matching AgentWorld Cesium aesthetic: dark glass, cyan accents, mono
   ═══════════════════════════════════════════════════════════════════════ */

/* ── Base Panel ── */
/* Cosmic-themed toolbar controls (replaced the legacy gray Tailwind inputs/
   selects that clashed with the dark neon map theme). */
.gm-filter-input,
.gm-filter-select {
  background: rgba(8, 12, 22, 0.82);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 10px;
  color: rgba(255, 255, 255, 0.92);
  font-family: 'IBM Plex Mono', 'Fira Code', 'SF Mono', monospace;
  font-size: 13px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  -webkit-appearance: none;
  appearance: none;
}
.gm-filter-select {
  padding: 0.5rem 2rem 0.5rem 0.85rem;
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M3 4.5 L6 7.5 L9 4.5' stroke='%2300d4ff' stroke-width='1.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.7rem center;
}
.gm-filter-input::placeholder { color: rgba(160, 190, 220, 0.5); }
.gm-filter-input:hover,
.gm-filter-select:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  background: rgba(12, 18, 30, 0.9);
}
.gm-filter-input:focus,
.gm-filter-select:focus {
  outline: none;
  border-color: rgba(var(--nc-primary-rgb), 0.7);
  box-shadow: 0 0 0 2px rgba(var(--nc-primary-rgb), 0.18), 0 0 18px rgba(var(--nc-primary-rgb), 0.12);
  background: rgba(12, 18, 30, 0.95);
}
.gm-filter-select option { background: #0a0e18; color: #e8f0ff; }

.gm-panel {
  position: absolute;
  z-index: 2;
  background: rgba(6, 8, 16, 0.92);
  backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 14px;
  padding: 16px;
  color: rgba(255, 255, 255, 0.85);
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.65), inset 0 1px 0 rgba(var(--nc-primary-rgb), 0.04);
  transition: box-shadow 0.3s ease, max-height 0.3s ease;
  font-family: 'IBM Plex Mono', 'Fira Code', 'SF Mono', monospace;
}
.gm-panel:hover {
  box-shadow: 0 12px 48px rgba(0, 0, 0, 0.7), inset 0 1px 0 rgba(var(--nc-primary-rgb), 0.06), 0 0 1px rgba(var(--nc-primary-rgb), 0.15);
}

/* ── Left Controls ── */
.gm-controls {
  top: 16px;
  left: 16px;
  width: 208px;
  max-height: calc(100vh - 320px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.18) transparent;
}
.gm-panel-collapsed {
  overflow: hidden;
}
.gm-panel-collapsed .gm-interact-guide,
.gm-panel-collapsed .gm-legend-section { display: none; }

.gm-panel-title {
  font-size: 0.70rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb), 0.9);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  user-select: none;
}
.gm-title-inner {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gm-title-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--nc-primary-bright);
  box-shadow: 0 0 8px var(--nc-primary-bright);
  animation: gm-title-pulse 2s ease-in-out infinite alternate;
  flex-shrink: 0;
}
@keyframes gm-title-pulse {
  from { opacity: 0.5; }
  to { opacity: 1.0; box-shadow: 0 0 14px var(--nc-primary-bright); }
}
.gm-collapse-icon {
  font-size: 0.65rem;
  opacity: 0.5;
}

/* ── Interaction Guide ── */
.gm-interact-guide {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 0.64rem;
  color: rgba(255, 255, 255, 0.28);
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.06);
}
.gm-interact-guide kbd {
  display: inline-block;
  padding: 1px 5px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  font-size: 0.60rem;
  margin-right: 4px;
  font-family: inherit;
}

/* ── Legend ── */
.gm-legend-section {
  margin-bottom: 11px;
  padding-bottom: 11px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.gm-legend-section:last-child { border-bottom: none; margin-bottom: 0; padding-bottom: 0; }
.gm-legend-title {
  font-size: 0.6rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(150, 195, 235, 0.72);
  margin-bottom: 7px;
}
.gm-legend-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: rgba(214, 228, 245, 0.7);
  font-size: 0.68rem;
  line-height: 1.5;
  margin-bottom: 3px;
}
.gm-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.gm-square { display: inline-block; width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0;
  background: #00e676; box-shadow: 0 0 6px #00e67688; }
.gm-beam-line { display: inline-block; width: 22px; height: 3px; border-radius: 2px; flex-shrink: 0; }
.gm-beam-gold { background: linear-gradient(90deg, #ffd54f, #ffb300); box-shadow: 0 0 8px #ffb30099; height: 4px; }
.gm-legend-note {
  font-style: italic;
  font-size: 0.58rem;
  color: rgba(255, 255, 255, 0.26);
  padding-left: 16px;
  margin-top: 2px;
}
/* refined "Registry names" toggle switch */
.gm-legend-toggles { display: flex; }
.gm-toggle { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; user-select: none;
  color: rgba(214, 228, 245, 0.8); font-size: 0.68rem; }
.gm-toggle-sw { position: relative; width: 30px; height: 16px; border-radius: 9px; flex-shrink: 0;
  background: rgba(120, 150, 190, 0.22); border: 1px solid rgba(120,170,230,0.2);
  transition: background .18s, border-color .18s, box-shadow .18s; }
.gm-toggle-knob { position: absolute; top: 1px; left: 1px; width: 12px; height: 12px; border-radius: 50%;
  background: #9fb4d0; transition: transform .18s, background .18s; }
.gm-toggle-on .gm-toggle-sw { background: linear-gradient(90deg, rgba(56,189,248,0.9), rgba(37,99,235,0.9));
  border-color: transparent; box-shadow: 0 0 10px -2px rgba(56,189,248,0.6); }
.gm-toggle-on .gm-toggle-knob { transform: translateX(14px); background: #fff; }
.gm-toggle:hover .gm-toggle-lbl { color: #eaf3ff; }

/* ── Selected Agent Panel ── */
.gm-agent-panel {
  top: 16px;
  right: 16px;
  width: 310px;
  padding: 20px;
  animation: gm-panel-open 0.3s ease-out;
  z-index: 50;
}
@keyframes gm-panel-open {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
.gm-ap-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
  gap: 10px;
}
.gm-ap-header-left {
  flex: 1;
  min-width: 0;
}
.gm-ap-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gm-ap-tier-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.gm-ap-name {
  font-size: 1.05rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
  line-height: 1.2;
  margin: 0;
}
.gm-ap-did {
  font-size: 0.58rem;
  color: rgba(255, 255, 255, 0.18);
  font-family: 'IBM Plex Mono', monospace;
  margin-top: 4px;
  word-break: break-all;
  line-height: 1.4;
}
.gm-close-btn {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.28);
  cursor: pointer;
  font-size: 1rem;
  padding: 2px 4px;
  flex-shrink: 0;
  transition: color 0.15s;
  font-family: inherit;
}
.gm-close-btn:hover { color: rgba(255, 255, 255, 0.8); }

.gm-ap-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}
.gm-ap-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.gm-ap-cell-label {
  font-size: 0.60rem;
  color: rgba(255, 255, 255, 0.30);
  letter-spacing: 0.03em;
}
.gm-ap-cell-value {
  font-size: 0.78rem;
  font-weight: 500;
  color: rgba(255, 255, 255, 0.8);
}
.gm-ap-big {
  font-size: 1.15rem;
  font-weight: 700;
  text-shadow: 0 0 10px currentColor;
}
.gm-synced-badge {
  display: inline-block;
  padding: 1px 5px;
  background: rgba(255, 171, 64, 0.15);
  border: 1px solid rgba(255, 171, 64, 0.45);
  color: #ffab40;
  border-radius: 3px;
  font-size: 0.52rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  margin-left: 6px;
  vertical-align: middle;
}
.gm-status-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.gm-status-dot.active { background: #00e676; box-shadow: 0 0 6px #00e67666; }
.gm-status-dot.inactive { background: #607d8b; }

.gm-ap-caps {
  margin-bottom: 14px;
}
.gm-ap-caps-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.gm-cap-tag {
  padding: 3px 8px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 4px;
  font-size: 0.62rem;
  color: rgba(var(--nc-primary-rgb), 0.6);
  transition: border-color 0.15s;
}
.gm-cap-tag:hover { border-color: rgba(var(--nc-primary-rgb), 0.30); }

.gm-profile-btn {
  width: 100%;
  padding: 10px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 8px;
  color: rgba(var(--nc-primary-rgb), 0.9);
  font-size: 0.74rem;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.2s;
  text-shadow: 0 0 8px rgba(var(--nc-primary-rgb), 0.15);
}
.gm-profile-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.35);
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.08);
}

/* ── Stats Bar (bottom center pill) ── */
.gm-stats-bar {
  position: absolute;
  bottom: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 2;
  background: rgba(6, 8, 16, 0.92);
  backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.06);
  border-radius: 28px;
  padding: 10px 28px;
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 0.68rem;
  font-family: 'IBM Plex Mono', 'Fira Code', 'SF Mono', monospace;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(var(--nc-primary-rgb), 0.04);
  color: rgba(255, 255, 255, 0.85);
}
.gm-stat-item {
  display: flex;
  align-items: center;
  gap: 5px;
}
.gm-stat-num {
  font-weight: 700;
  font-size: 0.84rem;
  text-shadow: 0 0 8px currentColor;
}
.gm-stat-lbl {
  color: rgba(255, 255, 255, 0.28);
  letter-spacing: 0.02em;
}
.gm-stat-sep {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
}
</style>
