<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { appLocale } from '@/services/appLocale'
// §CAPSEARCH (2026-09-01) — this view rendered a HARDCODED English search placeholder in
// all nine locales. ⚠ ALIASED to `tr` on purpose: `t` is used as a v-for loop variable
// twice in this template (the tab table and the tag list), and a `const { t }` here would
// be SHADOWED inside those scopes — the documented trap where t(...) silently calls a
// string instead of translating. Aliasing sidesteps it without renaming loop vars in a
// 5,000-line WebGL view that cannot be driven in a headless browser.
import { useI18n as useI18nTr } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
const { t: tr } = useI18nTr()
/**
 * AgentWorld CesiumJS — 3D Earth Globe Visualization
 * TheProtocol sovereign agent network on a real CesiumJS globe.
 *
 * Replaces the Three.js AgentWorldView.vue with CesiumJS for native geodesic arcs,
 * built-in orbit controls, proper arc rendering, and camera fly-to.
 *
 * Architecture rules:
 *   - CesiumJS Viewer in shallowRef (NEVER deep ref — Vue reactivity poisons Cesium internals)
 *   - Entity maps in plain Map (never reactive)
 *   - ArcData/FeedEvent in Vue refs (primitive values only)
 */
import { ref, shallowRef, computed, onMounted, onUnmounted, watch } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { esSocketUrl, FRAMES } from '@/config/frames'  // §FEFRAME W2: frames, sockets and stats from the frame manifest
import { currentFrameManifest } from '@/composables/useFrameManifest'
import { entryByName, entryByOrigin, frameOf } from '@/services/frameManifest'
import { buildPopulationIndex, type PopulationIndex } from '@/utils/registryPopulation'  // §GLOBEPOP — true per-registry totals
import { useFrames } from '@/composables/useFrames'   // §FEDEVENTS-6 — card-truth currency/name for solo deployments
import { useRouter, useRoute } from 'vue-router'
import UserAvatar from '@/components/common/UserAvatar.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import EarnedMarkRing from '@/components/common/EarnedMarkRing.vue'
import { useAgentStore } from '@/stores/agents'
import { getFleetStatus } from '@/services/api/command'
import { useFederationStore } from '@/stores/federation'
import { useRealtimeStore } from '@/stores/realtime'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import { useTopologyDiscovery } from '@/composables/useTopologyDiscovery'
import { useVRelativeHops, normName } from '@/composables/useVRelativeHops'
import { useLogger } from '@/composables/useLogger'
import { useCurrency } from '@/composables/useCurrency'
import { liveOld } from '@/services/ledgerNames'
import SovereignRegistryCard from '@/components/SovereignRegistryCard.vue'
import { registryCardView } from '@/services/api/registryCardView'
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import TopologyHoverLabel from '@/components/TopologyHoverLabel.vue'

// 2026-05-08 P3.2: useLogger no-ops in production for info/warn/debug;
// keeps errors. Replaces console.* noise that leaked Cesium/WebGL debug
// info to user devtools.
const log = useLogger('AgentWorld')
import {
  Viewer, Ion, Cartesian3, Cartesian2, Color,
  CallbackProperty, ScreenSpaceEventHandler, ScreenSpaceEventType,
  PolylineGlowMaterialProperty,
  ColorMaterialProperty,
  NearFarScalar, SceneTransforms,
  defined, ArcType, Math as CesiumMath, Entity,
  UrlTemplateImageryProvider, ImageryLayer,
  JulianDate, ClockRange, PostProcessStage, SkyBox,
} from 'cesium'
import 'cesium/Build/Cesium/Widgets/widgets.css'

// ─── Types ─────────────────────────────────────────────────────────────────

// §WORLDFIND — proven work rides on the dot so the hover can show what the
// agent actually DID here, and so the tier filter has a signal that survives a
// quiet network (EigenTrust reputation truncates to 0 for ~99% of agents when
// the graph is idle, which made the reputation tiers hide everything).
// Canonical compact shape (see agent_locations.py). One fact, one name: an
// earlier cut spelled these jobs_verified / cross_registry_jobs here while
// earnedMarks() read `jobs`, so the globe silently rendered NO earned mark.
interface WorldTrackRecord {
  jobs: number
  stars: number | null
  cross_registry: number
  open_disputes: number
  lost_disputes: number
  on_time_met?: number
  on_time_of?: number
  volume_total?: string | null
  volume_currency?: string | null
  distinct_posters?: number
  last_verified_at?: string | null
}

interface WorldAgent {
  did: string
  name: string
  lat: number
  lng: number
  status: string
  reputation: number
  visualReputation: number
  registryId: string
  registryName: string
  isSynced: boolean
  liquidBalance: number
  stakedBalance: number
  capabilities: string[]
  trackRecord?: WorldTrackRecord | null
  matchedSearch?: boolean
}

interface RegistryCardVisualSlice {
  iconUrl?: string | null
  orbColor?: string | null
  orbGlowColor?: string | null
  orbPulseSpeedHz?: number | null
  orbSizePx?: number | null
  haloEnabled?: boolean | null
  haloThickness?: number | null
  theme?: string | null
  sovereignVariant?: string | null
  // Flare layer (RC v0.3.1) — encirclement + broken-machine overlay, mirrors
  // the agent flare system (FlareEncirclement.vue). Cosmetic; not SPIFFE-locked.
  flareEncirclementVariant?: string | null
  flareEncirclementOverlay?: string | null
  flareCornerVariant?: string | null
}

interface RegistryCardFeesSlice {
  intraRegistry?: number | null
  crossRegistry?: number | null
  hostingEnabled?: boolean | null
  hostingRate?: number | null
  settlementCurrency?: string | null   // FX: registry's settlement currency, when topology exposes it
}

interface WorldRegistry {
  id: string
  name: string                  // load-bearing slug / registry_name (resolution key)
  displayName?: string | null   // §2026-06-14 operator-editable card display name (UI label)
  lat: number
  lng: number
  agentCount: number
  status: string
  hopDepth: number              // 0=local, 1=direct peer, 2+=topology-discovered
  frame: 'A' | 'B' | 'C'        // sovereign frame the registry belongs to (C = BVT frame)
  publicUrl?: string
  description?: string
  protocolVersion?: string
  authMethods?: string[]
  lastSyncedAt?: string
  // --- Registry Card v0.3 slice (2026-05-21) ---
  visual?: RegistryCardVisualSlice | null
  fees?: RegistryCardFeesSlice | null
  cardEtag?: string | null
  cardSignatureVerified?: boolean
  cardLastPulledAt?: string | null
  // §2026-06-14 — AGORA venue capability (card fees.exchange) for the hover badge.
  exchange?: { enabled?: boolean | null; currency?: string | null; passport_enabled?: boolean | null } | null
  // --- END RC v0.3 ---
}

interface ArcData {
  id: string
  fromLat: number
  fromLng: number
  toLat: number
  toLng: number
  color: string
  progress: number
  type: 'transfer' | 'federation' | 'dispute' | 'contract' | 'onboarding' | 'governance' | 'staking' | 'attestation'
  label: string
  startTime: number
  duration: number
  fromName?: string
  toName?: string
  amount?: string
}

interface FeedEvent {
  id: string
  type: 'transfer' | 'federation' | 'dispute' | 'onboarding' | 'governance' | 'staking' | 'attestation' | 'system'
  title: string
  sub: string
  time: number
  color: string
  frame?: 'A' | 'B' | 'C'  // sovereign frame the event came from; rendered as a small badge in the feed
}

// ─── Props ─────────────────────────────────────────────────────────────────

const props = defineProps<{
  embedded?: boolean
  // When provided (e.g. by LandingPage), Cesium reuses the parent's WS
  // event stream instead of opening its own /ws/events connection. Items
  // must carry a unique `id` and a `rawData` payload (the original WS
  // event object) — both are present on LandingPage's eventFeed entries.
  externalEvents?: Array<{ id?: string; rawData?: any; frame?: 'A' | 'B' | 'C' }>
  // Fired exactly once on the first successful Cesium postRender. Parent
  // pages (LandingPage, MissionControl) use this to defer heavy side work
  // like opening the EventStore WebSocket until the globe has painted at
  // least one frame — prevents the event flood from racing tile decode
  // and leaving the user staring at a black globe.
  onReady?: () => void
  // Embedded-mode only. Fires whenever the texture-backpressure gate flips.
  // Parents use this to pause upstream work (e.g. EventStore WebSocket feed)
  // while tiles are streaming, so the main thread isn't fighting the render
  // loop. Called with `true` when tiles start loading / camera moves, `false`
  // when the scene is fully settled.
  onTileStateChange?: (blocked: boolean) => void
  // GC2-7 (2026-06-12): PLANETARY COCKPIT mode — the Galactic Command Center
  // embeds this globe as a second targeting surface. In cockpit mode the
  // view's own side panels (controls/legend/feed) hide (the GCC Bridge takes
  // their place) and clicks EMIT instead of opening detail modals.
  cockpit?: boolean
}>()

const emit = defineEmits<{
  (e: 'select-registry', reg: WorldRegistry): void
  (e: 'select-agent', a: { did: string; name?: string; registryName?: string }): void
}>()
// The Cesium click handler shadows `props` locally (picked.id.properties) —
// capture cockpit mode at setup scope so the handler can read it.
const cockpitOn = computed(() => !!props.cockpit)

// ─── Stores ────────────────────────────────────────────────────────────────

const router = useRouter()
// §pass62.1 (2026-05-21) — read `?focus=<peer_name>` query param to support
// deep-links from PeerDetailDrawer "View peer in AgentWorld" CTA.
const route = useRoute()
const agentStore = useAgentStore()
// §GLOBEPOP — /agents/locations/ serves a fair per-registry SAMPLE plus true
// per-registry totals; points are drawn from the sample, counts labeled true.
let populationIndex: PopulationIndex = buildPopulationIndex(null)
const federationStore = useFederationStore()
const realtimeStore = useRealtimeStore()
const authStore = useAuthStore()
const { topology, version: topologyVersion, discoverTopology, domainKey, edgeKey } = useTopologyDiscovery()
// V-relative hop (same tree as the Galactic Map) for the on-hover registry tooltip —
// hop is otherwise not surfaced on this view. [Commander 2026-06-07]
const { hopByName: vrHopByName, refresh: vrRefresh } = useVRelativeHops()

// ─── Frame Detection ──────────────────────────────────────────────────────
let isFrameB = false

// ── §FEDEVENTS-6: deployment truth for streams + frame claims ───────────────
// The globe's A/B/C world model is genuine on multi-frame deployments (the
// same-origin WS suffixes are ABSOLUTE fleet-wide). A single-frame node
// (registry-config multi_frame=false — hetzner class) has no Frame A/B/C:
// its vhost serves ONLY /ws/events (its own ES), so the sibling dials would
// reconnect-loop forever and every "Frame A"/AVT claim over its own economy
// would be a lie. Frame letters stay as INTERNAL palette keys; user-visible
// claims (badges, chips, currency, connect messages) become deployment truth.
const framesApi = useFrames()
const multiFrame = ref(true)   // conservative default: pre-§FEDEVENTS-6 behavior until config answers
let deployCfgPromise: Promise<void> | null = null
function ensureDeployCfg(): Promise<void> {
  if (!deployCfgPromise) deployCfgPromise = (async () => {
    try {
      // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
      multiFrame.value = ((await loadRegistryConfig())?.multi_frame !== false)
    } catch { /* keep the multi default */ }
  })()
  return deployCfgPromise
}

// §FEFRAME W2: the globe's three colour SLOTS (A, B, C: internal palette keys since §FEDEVENTS-6) are the frame
// manifest's frames in order, this console's own frame first; a fourth frame shares slot C. Before W2 a slot was a
// substring of the retired frames' names ('frame-b', 'frame-c'), so every frame that exists today painted as A.
function slotFrame(slot: 'A' | 'B' | 'C') {
  return FRAMES[slot === 'A' ? 0 : slot === 'B' ? 1 : 2] ?? null
}
function slotOfFrameKey(key: string | null | undefined): 'A' | 'B' | 'C' {
  const i = key ? FRAMES.findIndex(f => f.key === key) : -1
  return i <= 0 ? 'A' : (i === 1 ? 'B' : 'C')
}
// Which frame a registry belongs to, by its NAME or its host, through the manifest (an operator: its frame).
// Used for visual tagging only — cross-frame registries are rendered alongside local-frame ones, styled differently.
function frameOfDomain(domain: string, name?: string): 'A' | 'B' | 'C' {
  const m = currentFrameManifest()
  if (!m) return 'A'
  const e = entryByName(m, name || null) || (domain ? entryByOrigin(m, `https://${String(domain).replace(/^https?:\/\//, '')}`) : null)
  return slotOfFrameKey(frameOf(m, e)?.key ?? null)
}

function isCrossFrameDomain(domain: string): boolean {
  const d = domain.toLowerCase()
  if (!isFrameB) {
    // Frame A: "frame-b" in domain → cross-frame
    if (d.includes('frame-b')) return true
    // Topology edge check: direct peers of __local__ are always local
    if (topology.edges.size > 0) {
      if (topology.edges.has(edgeKey('__local__', d))) return false
      for (const edge of topology.edges) {
        const [a, b] = edge.split('::')
        if (a === d || b === d) {
          const other = a === d ? b : a
          if (other.includes('frame-b')) return true
        }
      }
    }
    return false
  } else {
    // Frame B: our domains contain "frame-b" or are direct local peers
    if (d.includes('frame-b')) return false
    if (topology.edges.size > 0 && topology.edges.has(edgeKey('__local__', d))) return false
    return true
  }
}

// ─── Vue Reactive State ────────────────────────────────────────────────────

const viewerContainer = ref<HTMLDivElement | null>(null)
const isLoading = ref(true)
const loadError = ref<string | null>(null)

const selectedAgent = ref<WorldAgent | null>(null)
// Agent click now opens the shared rich AgentDetailModal (parity with the registry
// card click + Universe/GalacticMap). The old inline aw-agent-panel is retained but
// gated off by default (set useLegacyAgentPanel=true to restore it).
const showAgentModal = ref(false)
const useLegacyAgentPanel = ref(false)
// §pass78c (2026-06-06) withheld the DID from the embedded globe's modal because the lookup was an
// AUTHED read: a 401 tripped the global logout interceptor and bounced the visitor to /login (the
// "click-an-agent-logs-me-out" bug). That reasoning has since been closed twice over —
//   · §DISCPUBLIC gated the interceptor's logout branch on `!!authStore.token`, so a refusal can no
//     longer end a session that never existed; and
//   · §EMBEDGATE-2 removed the owner-tier merge from the lookup entirely, so there is no 401 to
//     trip anything — measured with a context that never held a token: `click=true: 401s = []`.
//
// §EMBEDGATE-3 (2026-09-08): the guard outlived its reason and became the bug. With `did=''` the
// modal's watcher never fetches, none of its three states (loading / error / agent) is true, and
// the visitor gets a SHELL WITH A CLOSE BUTTON — his report, "shows modal but empty".
//
// ⚠ AND THIS IS THE FOURTH PLACE `embedded` GATED BEHAVIOUR. The other three were in the modal
// itself; I fixed those, verified on /explore — which passes a real DID and therefore never
// exercised this line — and reported the globe as fixed. A control drawn from a sibling that was
// already working proves nothing about the path that was broken.
const agentModalDid = computed(() => selectedAgent.value?.did || '')
// Name is always available from the globe marker — shown while the card loads.
const agentModalName = computed(() => selectedAgent.value?.name || '')
// Registry Card v0.3 — click-to-pin registry detail panel (mirror selectedAgent).
const selectedRegistry = ref<WorldRegistry | null>(null)
// Registry click now opens the shared, fits-on-screen, two-column SovereignRegistryCard
// (replaces the single-column aw-rc side panel that overflowed — Commander bug
// "prod0.4v registry card doesn't fit screen on click, needs second column").
const showRegCard = ref(false)
const regCardPeer = ref<string | null>(null)
const regCardFallback = ref<string | null>(null)
// Registry Card v0.5 — full card fetched on click for the rich detail panel
// (replaces the old "View bare JSON" link). Local card + peer cached cards both
// come from THIS registry's backend (/api/v1/public/registry-card) so the browser
// never makes a cross-origin fetch.
const selectedRegistryCard = ref<any | null>(null)
const selectedRegistryCardLoading = ref(false)
let _rcFetchSeq = 0
async function loadSelectedRegistryCard(reg: WorldRegistry | null) {
  selectedRegistryCard.value = null
  if (!reg) return
  const seq = ++_rcFetchSeq
  selectedRegistryCardLoading.value = true
  try {
    const isLocal = reg.hopDepth === 0 || (reg as any).id === '__local__'
    // §DOCSFIX D6-108 (2026-10-16): the route takes `peer` and answers an envelope; `?registry=` belonged to a second
    // handler the route shadowed, so every peer click showed this registry's own envelope. fetchCard returns the card.
    const card = await registryCardView.fetchCard(isLocal ? null : reg.name)
    if (seq !== _rcFetchSeq) return  // superseded by a newer click
    selectedRegistryCard.value = card
  } catch {
    /* fall back to the topology slice already on selectedRegistry */
  } finally {
    if (seq === _rcFetchSeq) selectedRegistryCardLoading.value = false
  }
}
watch(selectedRegistry, (reg) => { loadSelectedRegistryCard(reg) })

// Compact capability chips for the click card (curated, human-readable).
function registryCapabilityChips(caps: any): string[] {
  if (!caps) return []
  const out: string[] = []
  if (caps.minting_capability && caps.minting_capability !== 'disabled') out.push('mint: ' + caps.minting_capability)
  if (caps.bridge_capability && caps.bridge_capability !== 'none') out.push('bridge: ' + String(caps.bridge_capability).replace(/_/g, ' '))
  if (caps.fiat_onramp_enabled) out.push('fiat: ' + ((caps.fiat_providers || []).join('/') || 'on'))
  if (caps.federation_enabled) out.push('federation')
  for (const v of (caps.a2a_versions_supported || [])) out.push('a2a ' + v)
  for (const p of (caps.supports_payment_protocol || [])) out.push(p)
  return out
}
// Non-empty operator links as [label, url] pairs for the click card.
function registryCardLinks(links: any): [string, string][] {
  if (!links || typeof links !== 'object') return []
  return Object.entries(links).filter(([, v]) => typeof v === 'string' && !!v) as [string, string][]
}

// Expose viewer to window for Playwright / dev-tools (safe — read-only).
declare global {
  interface Window {
    __aw_viewer?: any
    __aw_registries?: any
  }
}
const hoveredAgent = ref<WorldAgent | null>(null)
const hoveredRegistry = ref<WorldRegistry | null>(null)
// §2026-06-14 — a PEER registry's icon_url is stored same-origin-relative (upload
// + sync normalization enforce that). Resolve a relative icon against the peer's
// OWN host so peer avatars (e.g. Frame-B's icon) display from any viewer, not just
// the peer's own site. Absolute URLs + hostless cases pass through unchanged.
function resolveRegIcon(reg: WorldRegistry | null): string | undefined {
  const u = reg?.visual?.iconUrl
  if (!u) return undefined
  if (/^https?:\/\//i.test(u)) return u
  const host = reg?.publicUrl
  if (u.startsWith('/') && host) return host.replace(/\/+$/, '') + u
  return u
}
// FX: globe amounts/labels track the viewer's settlement currency (AVT/BVT).
const { localCurrency, describe } = useCurrency()
// Settlement currency for the hovered registry: the peer's own when topology
// exposes it, the viewer's for the local registry (hop 0), else unknown (no guess).
const hoveredRegCurrency = computed<string | null>(() => {
  const r = hoveredRegistry.value
  if (!r) return null
  return r.fees?.settlementCurrency || (r.hopDepth === 0 ? localCurrency.value : null)
})
const hoverPos = ref({ x: 0, y: 0 })

// Edge-aware tooltip placement — flips to the LEFT of the cursor near the right
// viewport edge (and UP near the bottom) so hover labels never overflow the
// canvas. Fixes the Commander bug "onhover right side canvas glitch / no label":
// the old raw `left: hoverPos.x + 16` clipped the tooltip off the right edge.
const tooltipStyle = computed<Record<string, string>>(() => {
  const x = hoverPos.value.x, y = hoverPos.value.y
  const vw = (typeof window !== 'undefined' ? window.innerWidth : 1600)
  const vh = (typeof window !== 'undefined' ? window.innerHeight : 900)
  const TW = 340, TH = 280, M = 16
  const s: Record<string, string> = {}
  if (x + M + TW > vw) s.right = Math.max(8, vw - x + M) + 'px'
  else s.left = (x + M) + 'px'
  if (y - 10 + TH > vh) s.bottom = Math.max(8, vh - y - 10) + 'px'
  else s.top = Math.max(8, y - 10) + 'px'
  return s
})

// FX-aware hover label: resolve the hovered agent's NATIVE settlement currency
// from its home registry, and flag when it differs from the viewer's currency
// (cross-currency / requires FX). Local agents fall back to the viewer currency.
const hoveredAgentCurrency = computed<string | null>(() => {
  const a = hoveredAgent.value
  if (!a) return null
  const reg = worldRegistries.value.find(r => r.id === a.registryId || r.name === a.registryName)
  return reg?.fees?.settlementCurrency || (!a.isSynced ? localCurrency.value : null)
})
const hoveredAgentForeign = computed<boolean>(() => {
  const c = hoveredAgentCurrency.value
  return !!c && !!localCurrency.value && c !== localCurrency.value
})

// Adapt the hovered WorldAgent → the shared TopologyHoverLabel `entity` shape
// (the same reusable label used by UniverseView + GalacticMap). Avatar is passed
// via the #avatar slot so the lazy-loaded UserAvatar + flare is preserved.
const awAgentEntity = computed<any>(() => {
  const a = hoveredAgent.value
  if (!a) return null
  return {
    type: 'agent', name: a.name, did: a.did, isSynced: a.isSynced,
    tierLabel: agentTierLabel(a.visualReputation), tierClass: agentTierClass(a.visualReputation),
    reputation: a.reputation, status: a.status,
    liquidBalance: a.liquidBalance, stakedBalance: a.stakedBalance,
    balance: (a.liquidBalance || 0) + (a.stakedBalance || 0),
    currency: hoveredAgentCurrency.value || localCurrency.value,
    foreign: hoveredAgentForeign.value,
    capabilities: a.capabilities, originRegistry: a.registryName,
    // §WORLDFIND — what this agent actually DID, from the registry's own guild
    // books. Same aggregation the Discovery Proven-work band shows, so the
    // globe and the marketplace cannot disagree about someone's record.
    trackRecord: a.trackRecord || null,
    matchedSearch: !!a.matchedSearch,
    flareLabel: hoverFlareLabel.value,
  }
})

// Human label for the equipped cosmetic. Deliberately says the tier and the
// variant, never a score: this is the PAID axis and the label must not read
// like something the agent earned.
function _pretty(s: string): string {
  return String(s).replace(/[-_]+/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
const hoverFlareLabel = computed<string | null>(() => {
  const f = hoverAgentFlare.value
  if (!f) return null
  return [f.tier, f.variant, f.overlay].filter(Boolean).map(v => _pretty(String(v))).join(' · ')
})

// §28 polish (2026-05-15) — Avatar+flare cache for hover tooltip. Lazy-
// loaded on first hover of each agent; later hovers reuse the cached
// profile so the UserAvatar renders instantly.
const hoverAgentProfiles = ref<Record<string, any | null>>({})
async function _loadHoverProfile(did: string) {
  if (did in hoverAgentProfiles.value) return
  // Incident 2026-05-30: only did:* and federated card:<id> resolve via
  // /agents/by-did/. Any other identifier is a guaranteed 404, and a burst of
  // those (hovering many orbs) trips CrowdSec http-probing → bans the VIEWER's
  // IP. Negative-cache the key and skip the fetch so the globe can never get a
  // legitimate user banned. (Backend also resolves card:<id> → 200 now.)
  if (!/^(did:|card:)/.test(did)) {
    hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: null }
    return
  }
  hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: null }
  try {
    const r = await fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`)
    if (r.ok) {
      const j = await r.json()
      // §pass78c issue ③ — federated shadow profiles project the top-level flare_*
      // fields inconsistently (flare_tier / flare_encirclement_variant come back null
      // even though the equipped ring lives in card_data.flare). UserAvatar reads the
      // top-level fields, so backfill them from card_data.flare (mirrors discovery.ts
      // parseFullCard) → the hover ring matches the agent's REAL flare + the modal.
      const cf = (j && j.card_data && typeof j.card_data.flare === 'object' && j.card_data.flare) || null
      if (cf) {
        if (!j.flare_tier) j.flare_tier = cf.tier ?? null
        if (!j.flare_encirclement_variant) j.flare_encirclement_variant = cf.encirclement_variant ?? null
        if (!j.flare_encirclement_overlay) j.flare_encirclement_overlay = cf.encirclement_overlay ?? null
      }
      hoverAgentProfiles.value = { ...hoverAgentProfiles.value, [did]: j }
    }
  } catch {}
}
watch(hoveredAgent, (a) => {
  if (a && a.did && !(a.did in hoverAgentProfiles.value)) {
    void _loadHoverProfile(a.did)
  }
})

// §MARKCOLLAR — the hovered agent's equipped cosmetic, if any. The lazy profile
// already backfills the top-level flare_* fields from card_data.flare (see
// above), so this reads one shape and not two.
const hoverAgentFlare = computed<{ tier: string; variant: string | null; overlay: string | null } | null>(() => {
  const p = hoveredAgent.value ? hoverAgentProfiles.value[hoveredAgent.value.did] : null
  if (!p || !p.flare_tier) return null
  return {
    tier: p.flare_tier,
    variant: p.flare_encirclement_variant ?? null,
    overlay: p.flare_encirclement_overlay ?? null,
  }
})
const hoverAgentAvatarUrl = computed<string | null>(() => {
  const p = hoveredAgent.value ? hoverAgentProfiles.value[hoveredAgent.value.did] : null
  return p?.card_data?.iconUrl || p?.card_data?.icon_url || null
})

const autoRotate = ref(true)
const showArcs = ref(true)
const showAtmosphere = ref(true)
const searchQuery = ref('')
const filterRegistry = ref('all')
const filterTier = ref('all')

// ─── Direction-D visual upgrades (Twilight Terminator) ─────────────────────
// Each toggle drives a watcher that flips the corresponding Cesium-side flag
// without re-initialising the Viewer. Persisted to localStorage so the
// Commander's showtime preferences survive a reload.
type VisualQuality = 'low' | 'medium' | 'high' | 'ultra'
const LS_QUALITY = 'theprotocol:agentworld-quality'

function readPersistedQuality(): VisualQuality {
  try {
    const q = localStorage.getItem(LS_QUALITY)
    if (q === 'low' || q === 'medium' || q === 'high' || q === 'ultra') return q
  } catch { /* storage unavailable */ }
  return 'ultra'  // AGENTWORLD-CINEMA: full filmic stack by default (tiers are additive)
}
const visualQuality = ref<VisualQuality>(readPersistedQuality())

// Individual feature toggles — defaults driven by the quality preset below.
// Every preset is *additive* (Low → Medium → High → Ultra), so changing the
// preset never turns anything off; it only adds new polish.
const showTerminator = ref(true)            // real UTC-driven day/night lighting
const showNightLights = ref(true)           // NASA GIBS Black Marble on dark side
const showRegistryHalos = ref(true)         // pulsating halos on registry markers
const showEliteFlares = ref(true)           // star-cross flares on reputation ≥ 95 agents
const showGraticule = ref(false)            // faint meridians + parallels
const showBloom = ref(false)                // Cesium native bloom post-fx
const showVignette = ref(true)              // corner-darken post-fx
const showChromaticAberration = ref(false)  // subtle RGB offset at limb

function applyQualityPreset(q: VisualQuality) {
  // Every preset keeps the baseline (terminator + night lights + halos + flares
  // + vignette) because they're cheap and central to Direction D. The preset
  // only controls the incremental polish layers above that.
  // Graticule intentionally omitted — Commander opted out after visual review;
  // buildGraticule() stays present but never gets turned on by any preset.
  showTerminator.value = true
  showNightLights.value = true
  showRegistryHalos.value = true
  showEliteFlares.value = true
  showVignette.value = true
  showGraticule.value = false
  showBloom.value = q === 'medium' || q === 'high' || q === 'ultra'
  showChromaticAberration.value = q === 'ultra'
  try { localStorage.setItem(LS_QUALITY, q) } catch { /* storage unavailable */ }
}
// Apply the persisted preset once so individual refs match the stored quality
// at boot. Without this, a stored 'ultra' wouldn't enable graticule/bloom/CA
// because the individual refs default to false.
applyQualityPreset(visualQuality.value)

const arcFilterTransfer = ref(true)
const arcFilterFederation = ref(true)
const arcFilterOnboarding = ref(true)
const arcFilterDispute = ref(true)
const arcFilterContract = ref(true)
const arcFilterGovernance = ref(true)
const arcFilterStaking = ref(true)
const arcFilterAttestation = ref(true)
const demoMode = ref(false)
let demoTimer: ReturnType<typeof setInterval> | null = null
const globeInteractive = ref(false)

function enableGlobeInteraction() {
  if (!props.embedded || !viewerContainer.value) return
  globeInteractive.value = true
  viewerContainer.value.style.pointerEvents = 'auto'
  autoRotate.value = false
}

function disableGlobeInteraction() {
  if (!props.embedded || !viewerContainer.value) return
  globeInteractive.value = false
  viewerContainer.value.style.pointerEvents = 'none'
  autoRotate.value = true
}
const showSignalFilters = ref(false)
const showLiveFeed = ref(false)
const showVisualBlock = ref(true)       // VISUAL HUD block expanded by default
const panelCollapsed = ref(false)

const worldAgents = ref<WorldAgent[]>([])
const worldRegistries = ref<WorldRegistry[]>([])
const activeArcs = ref<ArcData[]>([])
const feedEvents = ref<FeedEvent[]>([])

// ─── CesiumJS — shallowRef for Viewer (CRITICAL: never deep ref) ─────────

const viewer = shallowRef<Viewer | null>(null)
let handler: ScreenSpaceEventHandler | null = null

// Entity tracking (plain Maps — never reactive)
const agentEntities = new Map<string, Entity>()
const registryEntities = new Map<string, Entity>()
const arcEntities = new Map<string, { polyline: Entity; startTime: number; duration: number; allPositions: Cartesian3[]; arcColor: Color; arcColorEnd: Color | null; toLat: number; toLng: number; landed: boolean }>()

// AW-3 (2026-06-12): impact ripples — an expanding, fading ground ring where an
// arc launches (small) and lands (big), so transfers feel physical instead of
// evaporating mid-air. Pure material-layer entities; owned and expired by the
// same updateArcs loop that owns arc lifecycle. Hard-capped so bursts can't
// flood the entity collection.
const rippleEntities = new Map<string, { ent: Entity; start: number; dur: number }>()
const MAX_RIPPLES_STANDALONE = 24
const MAX_RIPPLES_EMBEDDED = 10

// AW-4 (2026-06-12): activity heat — rolling 60s arc-touch counts per registry
// site drive halo/pillar intensity, so "where the economy is hot right now"
// reads at a glance. Attribution is nearest-site (16 sites, trivial math).
const siteHeatStamps = new Map<string, number[]>()
const HEAT_WINDOW_MS = 60_000
function bumpSiteHeat(lat: number, lng: number) {
  let best: WorldRegistry | null = null
  let bestD = 64 // ≤ ~8° away counts as "at" the site
  for (const r of worldRegistries.value) {
    const d = (r.lat - lat) ** 2 + (r.lng - lng) ** 2
    if (d < bestD) { bestD = d; best = r }
  }
  if (!best) return
  const arr = siteHeatStamps.get(best.id) || []
  arr.push(performance.now())
  if (arr.length > 60) arr.splice(0, arr.length - 60)
  siteHeatStamps.set(best.id, arr)
}
function siteHeat01(regId: string): number {
  const arr = siteHeatStamps.get(regId)
  if (!arr || !arr.length) return 0
  const cutoff = performance.now() - HEAT_WINDOW_MS
  let n = 0
  for (let i = arr.length - 1; i >= 0 && arr[i] >= cutoff; i--) n++
  return Math.min(n / 12, 1)
}

// AW-2 (2026-06-12): live health on the pillars. Polls the GCC fleet-status
// probe (admin endpoint, axios auto-auth) ONLY on the standalone view —
// embedded anonymous globes make no authed fetches (§pass78c doctrine). A
// 401/403 disables the feature silently and permanently for the session, so
// non-admin developers see neutral pillars and zero request spam.
const siteHealthMap = new Map<string, 'up' | 'degraded' | 'down'>()
const healthOverride = new Map<string, { state: 'down' | 'degraded'; until: number }>()
let healthTimer: ReturnType<typeof setInterval> | null = null
let healthEnabled = true
const HEALTH_RED = Color.fromCssColorString('#ff5252')
const HEALTH_AMBER = Color.fromCssColorString('#ffb300')

function siteHealthOf(regId: string): 'up' | 'degraded' | 'down' | undefined {
  const o = healthOverride.get(regId)
  if (o) {
    if (performance.now() < o.until) return o.state
    healthOverride.delete(regId)
  }
  return siteHealthMap.get(regId)
}

function matchSiteForKey(key: string): WorldRegistry | undefined {
  const k = (key || '').toLowerCase().trim()
  if (!k) return undefined
  return worldRegistries.value.find(r => {
    const n = (r.name || '').toLowerCase().replace(/\s+/g, '-')
    const host = (r.publicUrl || '').toLowerCase()
    return n === k || n === `cloud-op-${k}` || k === n.replace(/^cloud-op-/, '') || n.includes(k) || k.includes(n) || host.includes(k)
  })
}

async function pollFleetHealth() {
  if (props.embedded || !healthEnabled) return
  try {
    const fs = await getFleetStatus()
    const next = new Map<string, 'up' | 'degraded' | 'down'>()
    for (const [key, probe] of Object.entries(fs.status || {})) {
      const site = matchSiteForKey(key)
      if (!site) continue
      const h = (probe as any)?.health
      next.set(site.id, h === 'up' ? 'up' : h === 'degraded' ? 'degraded' : 'down')
    }
    siteHealthMap.clear()
    next.forEach((v2, k) => siteHealthMap.set(k, v2))
    viewer.value?.scene.requestRender()
  } catch (e: any) {
    const status = e?.response?.status
    if (status === 401 || status === 403) {
      healthEnabled = false
      if (healthTimer) { clearInterval(healthTimer); healthTimer = null }
    }
    // other failures (network blip): keep the schedule, stale map stands
  }
}
// Persistent wrapped-token bridge arc (Frame A mainframe ↔ Frame B mainframe)
let bridgeEntity: Entity | null = null

// Visible agent count (updated on filter change)
const visibleAgentCount = ref(0)

// EventStore WebSocket (non-reactive). THREE streams now — Frame A's local
// EventStore on /ws/events, Frame B's sovereign EventStore on /ws/events-b and
// Frame C's sovereign (BVT) EventStore on /ws/events-c. All feed
// handleEventStoreMessage(raw, frame) so every consumer (arc spawner, feed
// pill, currency labeller) knows which sovereign frame the event originated on.
let esWs: WebSocket | null = null
let esWsB: WebSocket | null = null
let esWsC: WebSocket | null = null
let esWsReconnectTimer: ReturnType<typeof setTimeout> | null = null
let esWsReconnectDelay = 1500
const esWsConnected = ref(false)
let esWsBReconnectTimer: ReturnType<typeof setTimeout> | null = null
let esWsBReconnectDelay = 1500
const esWsBConnected = ref(false)
let esWsCReconnectTimer: ReturnType<typeof setTimeout> | null = null
let esWsCReconnectDelay = 1500
const esWsCConnected = ref(false)

// Arc animation frame
let arcAnimFrame: number | null = null

// ─── Embedded-mode texture backpressure ───────────────────────────────────
// Defer EventStore messages while Cesium is streaming/uploading tiles so the
// event work (arc spawn, entity updates, Vue reactivity) can't starve the
// tile LOD upgrade decision inside the render loop.
//
// Primary gate: `scene.globe.tilesLoaded` — Cesium's own boolean that flips
// false the instant any tile queues and flips true once every visible tile
// is uploaded to the GPU. Cleaner than watching queue depth because tiles
// often arrive in small batches that never exceed a counter threshold.
//
// Secondary gate: `camera.changed` — fires on any camera motion (even if no
// tiles have queued yet). Pre-holds for a grace window so the first frame
// of a zoom-in doesn't leak events before the tiles start requesting.
//
// Drain: after the gate releases, wait COOLDOWN_MS so the GPU has a few
// render loops to settle, then trickle events out at DRAIN_LIMIT per tick
// (too fast immediately re-saturates the main thread).
//
// Standalone view doesn't use any of this — the user controls the pace.
let textureGateBlocked = true                         // start blocked; flips off once tiles settle
let eventBacklog: Array<{ id: string; rawData: any }> = []
// Helper: flip the gate + notify parent so it can pause upstream event ingest.
// Only fires onTileStateChange when the value actually changes (avoids flooding
// the parent with identical updates from every tile-progress tick).
function setTextureGateBlocked(blocked: boolean) {
  if (textureGateBlocked === blocked) return
  textureGateBlocked = blocked
  try { props.onTileStateChange?.(blocked) } catch { /* parent callback errors non-fatal */ }
}
let drainScheduler: ReturnType<typeof setTimeout> | null = null
let cameraMotionTs = 0                                // wall-clock of last camera change
const EMBEDDED_DRAIN_LIMIT = 3                        // events drained per tick after cooldown
const EMBEDDED_DRAIN_INTERVAL_MS = 80                 // ≈12.5 ticks/s drain rate
const EMBEDDED_SETTLE_COOLDOWN_MS = 500               // grace after tiles-loaded flips true
const EMBEDDED_CAMERA_HOLD_MS = 600                   // still "motion" for N ms after last change
const EMBEDDED_BACKLOG_CAP = 200                      // trailing-window cap

// ─── Constants ─────────────────────────────────────────────────────────────

// Arc cap: standalone globe tolerates more concurrent signals; the embedded
// landing-page globe uses a lower cap because it's already fighting for
// the main thread (EventStore WS + Cesium tile decode).
const MAX_CONCURRENT_ARCS_STANDALONE = 1000
const MAX_CONCURRENT_ARCS_EMBEDDED = 300
const ARC_DURATION_MS = 2200
const MAX_FEED_EVENTS = 50
// Natural-cluster positioning. Each agent gets a deterministic Gaussian-ish
// offset from its registry's center — dense near the glyph with a tapering
// tail, rather than a single ring. Produces an organic "crowd" pattern
// instead of the visible concentric orbits the old polar-annulus produced.
const NATURAL_SIGMA = 1.4         // half-normal radial spread (degrees)
const NATURAL_FLOOR = 0.25        // minimum radius — no dots exactly on glyph
const NATURAL_RADIUS_MAX = 4.5    // hard cap on radial distance (degrees)
const NATURAL_JITTER = 0.4        // ±lat/lng grid jitter to break any banding
const ORBIT_THRESHOLD_DEG = 1.5   // "is this agent effectively at its registry?"
// Embedded-mode burst coalescer: if the same from→to (rounded) + type arc
// was spawned within this window, skip the duplicate. Prevents the hero
// globe from drawing 10 identical arcs when a Kafka batch arrives.
// Embedded uses a wider window because it's also fighting for the main
// thread with parent-page work (EventStore WS, Vue reactivity on feed list).
const BURST_COALESCE_MS_STANDALONE = 200
const BURST_COALESCE_MS_EMBEDDED = 500

const REGISTRY_COORDS: Record<string, { lat: number; lng: number }> = {
  'registry a':    { lat: 47.8473, lng:  12.9757 },  // Freilassing, Bavaria
  'frame b':       { lat: 39.9042, lng: 116.4074 },  // Beijing — Frame B sovereign mainframe
  'frame-b':       { lat: 39.9042, lng: 116.4074 },
  'registry test': { lat: 35.6762, lng: 139.6503 },
  'sandbox':       { lat: 35.6762, lng: 139.6503 },
  'local':         { lat: 47.8473, lng:  12.9757 },
  'default':       { lat: 47.8473, lng:  12.9757 },
}

// ─── Centralized Palette ────────────────────────────────────────────────────
// Single source of truth for arc + feed-pill + legend colours. To recolour
// anything visible on the globe, edit ONLY this object — every consumer
// (spawnArc callers, pushFeedEvent callers, the in-template legend) reads
// from PALETTE via the helpers below.
//
// Transfer events have three variants because direction context matters:
//   local         → same registry                 (cyan, baseline)
//   crossRegistry → different registries, same    (blue, slightly bolder)
//                   sovereign frame
//   crossFrame    → Frame A ↔ Frame B             (electric magenta — the
//                                                   single most distinct
//                                                   colour on the globe)
// All other event classes carry a single arc + feed colour.

type TransferVariant = 'local' | 'crossRegistry' | 'crossFrame'

const PALETTE = {
  transfer: {
    local:         { arc: 'var(--nc-primary-bright)', feed: 'rgba(0,229,255,0.85)',  label: 'Transfer' },
    crossRegistry: { arc: '#2979ff',                  feed: 'rgba(41,121,255,0.90)', label: 'Cross-Registry' },
    crossFrame:    { arc: '#ff3df0',                  feed: 'rgba(255,61,240,0.95)', label: 'Cross-Frame' },
  },
  fee:         { arc: '#1de9b6', feed: 'rgba(29,233,182,0.85)' },
  treasury:    { arc: 'var(--nc-primary-bright)', feed: 'rgba(0,229,255,0.85)' },
  mint:        { arc: '#fff066', feed: 'rgba(255,240,102,0.85)' },
  onboarding:  { arc: '#ab47bc', feed: 'rgba(171,71,188,0.85)' },
  dispute:     { arc: '#ff4444', feed: 'rgba(255,68,68,0.85)' },
  contract:    { arc: '#00e676', feed: 'rgba(0,230,118,0.85)' },
  governance:  { arc: '#ff9100', feed: 'rgba(255,145,0,0.85)' },
  staking:     { arc: '#69f0ae', feed: 'rgba(105,240,174,0.85)' },
  attestation: { arc: '#e040fb', feed: 'rgba(224,64,251,0.85)' },
  federation:  { arc: '#ffd700', feed: 'rgba(255,215,0,0.85)' },
  bridge:      { arc: '#ffae00', feed: 'rgba(255,174,0,0.95)' },
  system:      { arc: '#ffffff', feed: 'rgba(255,255,255,0.30)' },
} as const

// Registry markers — hop-depth colours per sovereign frame. Frame B operators
// render in a magenta/purple family so the two sovereign frames are visually
// distinguishable on the unified globe (§4.4 whitepaper).
const HOP_DEPTH_COLORS = ['#00e676', '#5c9cf5', '#00bcd4', '#ff9800', '#e91e63', '#d50000']
const FRAME_B_HOP_COLORS = ['#ff4fb4', '#e91e63', '#c2185b', '#9c27b0', '#7b1fa2', '#4a148c']
// Frame C is the BVT frame — gold/amber family so the second currency's
// territory reads instantly against Frame A cyan/green and Frame B magenta.
const FRAME_C_HOP_COLORS = ['#ffd54f', '#ffb300', '#ffa000', '#ff8f00', '#ff6f00', '#e65100']
function hopColor(depth: number, frame: 'A' | 'B' | 'C' = 'A'): string {
  const palette = frame === 'C' ? FRAME_C_HOP_COLORS : frame === 'B' ? FRAME_B_HOP_COLORS : HOP_DEPTH_COLORS
  return palette[Math.min(depth, palette.length - 1)]
}

// Currency semantics: Frame C's EventStore denominates in BVT; A and B in AVT.
// Arc/feed labels use the currency of the STREAM the event arrived on — that is
// what the event's `amount` is actually denominated in.
const BVT_GOLD = '#ffc400'
const AVT_CYAN = '#00e5ff'
function curOf(frame: 'A' | 'B' | 'C'): string {
  // §FEDEVENTS-6: a single-frame deployment has ONE currency — its own card's
  // (frame letters there are internal palette keys, not economies). Unknown
  // frames also resolve to the viewer's local currency: assume same-currency
  // unless we KNOW it differs (useFrames doctrine) — never a hardcoded AVT.
  if (!multiFrame.value) return framesApi.localCurrency.value
  return slotFrame(frame)?.currency || framesApi.localCurrency.value
}

// Three-way transfer classification. Returns 'local' if both sides resolve
// to the same registry, 'crossFrame' if the registries belong to different
// sovereign frames (A vs B), 'crossRegistry' otherwise.
function transferVariant(fromRegistryId: string, toRegistryId: string): TransferVariant {
  if (fromRegistryId === toRegistryId) return 'local'
  const fromReg = worldRegistries.value.find(r => r.id === fromRegistryId)
  const toReg   = worldRegistries.value.find(r => r.id === toRegistryId)
  if (fromReg && toReg && fromReg.frame !== toReg.frame) return 'crossFrame'
  return 'crossRegistry'
}

// Per-variant visual emphasis. Cross-frame is the loudest (thickest stroke,
// brightest glow, longest duration) so it stands out on a busy globe.
const TRANSFER_EMPHASIS: Record<TransferVariant, { widthMul: number; glowMul: number; durationMul: number }> = {
  local:         { widthMul: 1.0,  glowMul: 1.0, durationMul: 1.0 },
  crossRegistry: { widthMul: 1.15, glowMul: 1.3, durationMul: 1.5 },
  crossFrame:    { widthMul: 1.45, glowMul: 1.8, durationMul: 2.0 },
}

// Currency-aware arc colours. Transfers inside the BVT economy (Frame C +
// its ME cloud-ops) render gold; cross-frame transfers that ENTER or LEAVE
// the BVT frame lerp cyan↔gold along the flight so the value visibly changes
// currency at altitude (FX made physical). A↔B cross-frame keeps the
// established magenta. streamFrame covers the endpoints-unresolved fallbacks:
// an event arriving on the C stream is BVT even when we can't place both ends.
function transferArcColors(
  variant: TransferVariant,
  fFrame: 'A' | 'B' | 'C',
  tFrame: 'A' | 'B' | 'C',
  streamFrame: 'A' | 'B' | 'C',
): { color: string; colorEnd?: string } {
  const cFrom = fFrame === 'C', cTo = tFrame === 'C'
  if (variant === 'crossFrame' && (cFrom || cTo)) {
    return { color: cFrom ? BVT_GOLD : AVT_CYAN, colorEnd: cTo ? BVT_GOLD : AVT_CYAN }
  }
  if (cFrom || (streamFrame === 'C' && variant !== 'crossFrame')) return { color: BVT_GOLD }
  return { color: PALETTE.transfer[variant].arc }
}

// Feed-pill colour helper. Handles both flat event types and the transfer
// three-way variant. Falls back to system white for unknown types.
function feedColorOf(type: string, variant: TransferVariant = 'local'): string {
  if (type === 'transfer') return PALETTE.transfer[variant].feed
  const entry = (PALETTE as Record<string, { arc: string; feed: string }>)[type]
  return entry?.feed ?? PALETTE.system.feed
}

// ─── Coordinate Helpers ────────────────────────────────────────────────────

function getRegistryCoords(registryName: string): { lat: number; lng: number } {
  const key = (registryName || 'default').toLowerCase().trim().replace(/-/g, ' ')
  for (const [k, v] of Object.entries(REGISTRY_COORDS)) {
    if (key.includes(k)) return v
  }
  return REGISTRY_COORDS.default
}

function deterministicGeoCoords(domain: string): { lat: number; lng: number } {
  let hash = 0
  for (let i = 0; i < domain.length; i++) {
    hash = ((hash << 5) - hash) + domain.charCodeAt(i)
    hash |= 0
  }
  const lat = ((hash & 0xFFFF) / 0xFFFF) * 120 - 60
  const lng = (((hash >>> 16) & 0xFFFF) / 0xFFFF) * 360 - 180
  return { lat, lng }
}

function orbitalCoords(did: string, centerLat: number, centerLng: number): { lat: number; lng: number } {
  // DJB2 hash of the DID, XOR'd with 4 distinct magic constants to produce
  // four pseudo-independent integer draws from the same deterministic seed.
  let hash = 0
  for (let i = 0; i < did.length; i++) {
    hash = ((hash << 5) - hash) + did.charCodeAt(i)
    hash |= 0
  }
  const h1 = Math.abs(hash ^ 0x9e3779b9) >>> 0  // Box-Muller u1
  const h2 = Math.abs(hash ^ 0x85ebca6b) >>> 0  // Box-Muller u2
  const h3 = Math.abs(hash ^ 0xc2b2ae35) >>> 0  // angle
  const h4 = Math.abs(hash ^ 0x27d4eb2f) >>> 0  // lat/lng jitter pair

  // Box-Muller → approximately standard-normal variate → half-normal radius.
  // u1 shifted off zero so log() stays finite for the one-in-ten-thousand DID
  // whose hash lands on the lower boundary.
  const u1 = ((h1 % 10000) + 1) / 10001
  const u2 = (h2 % 10000) / 10000
  const gauss = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2)
  const r = Math.min(NATURAL_RADIUS_MAX, Math.abs(gauss) * NATURAL_SIGMA + NATURAL_FLOOR)

  // Full 360° angle + small independent lat/lng jitter to break any residual
  // angular banding the hash function might produce.
  const angle = (h3 % 36000) / 36000 * Math.PI * 2
  const jLat = ((h4 & 0xFFFF) / 0xFFFF - 0.5) * NATURAL_JITTER
  const jLng = (((h4 >>> 16) & 0xFFFF) / 0xFFFF - 0.5) * NATURAL_JITTER

  // Longitude degrees shrink with latitude on a sphere; divide by cos(lat) so
  // high-latitude clusters (Freilassing ~48°N) stay visually circular instead
  // of east-west-compressed. Floor at 0.2 to avoid polar blow-up.
  const cosLat = Math.max(0.2, Math.cos(centerLat * Math.PI / 180))
  return {
    lat: centerLat + r * Math.sin(angle) + jLat,
    lng: centerLng + (r * Math.cos(angle)) / cosLat + jLng,
  }
}

function resolveCoords(did: string, regLat: number, regLng: number, realCoords: Record<string, { lat: number; lng: number }>) {
  if (realCoords[did]) {
    const rc = realCoords[did]
    const d = Math.sqrt((rc.lat - regLat) ** 2 + (rc.lng - regLng) ** 2)
    if (d > ORBIT_THRESHOLD_DEG) return rc
  }
  return orbitalCoords(did, regLat, regLng)
}

// Match agent's origin_registry_name to a WorldRegistry — EXACT match only
// (aligned with Galactic Map fix from 2026-03-31 session)
function matchRegistry(originName: string, registries: WorldRegistry[]): WorldRegistry | null {
  if (!originName) return null
  const normalized = originName.toLowerCase().trim()
  for (const reg of registries) {
    if (reg.id === '__local__') continue
    if ((reg.name || '').toLowerCase().trim() === normalized) return reg
  }
  return null
}

const KNOWN_DIDS: Record<string, string> = {
  'plundering pablo': 'did:cos:5aabb973-94e1-8653-e957',
}

function calcVisualRep(eventCount: number): number {
  return Math.min(100, Math.max(1, Math.round(eventCount / 13)))
}

// Derive a 0–100 visualReputation for an agent. Primary source is the
// admin-only EventStore event-count snapshot (calcVisualRep below); when
// that's empty (embedded LandingPage hero, anonymous viewers) we fall
// back to the agent's EigenTrust reputation_score (0–1000 → /10) so elite
// agents still trigger flares + tier coloring on the public globe.
// Audit follow-up 2026-05-05: re-enables elite shine on the embedded view.
function deriveVisualReputation(eventCount: number, reputationScore: number): number {
  if (eventCount > 0) return calcVisualRep(eventCount)
  return Math.min(100, Math.max(1, Math.round((reputationScore || 0) / 10)))
}

// ─── CesiumJS Viewer Init ──────────────────────────────────────────────────

// Listener cleanup refs — captured in initViewer, removed in onUnmounted.
// Without these, anonymous closures on Cesium events leak across SPA route
// changes (audit Tier 1B, 2026-05-05).
let _cesiumCleanups: Array<() => void> = []

function initViewer() {
  if (!viewerContainer.value) return

  // No Ion token needed — we use a simple dark basemap
  Ion.defaultAccessToken = ''

  let v: Viewer
  try {
    v = new Viewer(viewerContainer.value, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    /**
     * 🔴 §IONOFF — DO NOT REMOVE. Clearing the Ion token is not the same as not calling
     * Ion. With `baseLayer` unset, the Viewer CONSTRUCTOR still creates Cesium's default
     * imagery (Ion asset 2, Bing) and fires `api.cesium.com/v1/assets/2/endpoint` before
     * a line of our code runs — MEASURED on the public landing page: exactly one request,
     * 401, on every single visit, because the token is deliberately empty. The
     * `imageryLayers.removeAll()` below then discards the layer it paid for.
     *
     * `false` means "no default imagery at all", so the self-hosted §BASEMAP pyramid is
     * the only thing the planet ever asks for. Same argument as §BASEMAP and
     * §HETZNERLOCK-13: a sovereign registry does not dial out to a third party uninvited,
     * and an operator running air-gapped should see no external request at all.
     */
    baseLayer: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    selectionIndicator: false,
    navigationHelpButton: false,
    infoBox: false,
    fullscreenButton: false,
    vrButton: false,
    scene3DOnly: true,
    requestRenderMode: true,
    // Cesium only re-renders when something changes; the terminator moves with
    // the real sun, so we drive a 1 Hz requestRender() tick from the animation
    // loop (see updateArcs) instead of forcing full-speed rendering here.
    maximumRenderTimeChange: Infinity,
    // skyBox: undefined → Cesium instantiates its default starfield from the
    // six PNGs shipped under Build/Cesium/Assets/Textures/SkyBox/. This is the
    // starfield behind the planet — not to be confused with skyAtmosphere,
    // which is the rim glow on the limb.
    useBrowserRecommendedResolution: true,
    contextOptions: {
      webgl: {
        alpha: false,
        antialias: true,
        powerPreference: 'high-performance',
      },
    },
  })
  } catch (err: any) {
    log.warn('CesiumJS Viewer init failed:', err?.message || err)
    loadError.value = err?.message || 'WebGL initialization failed'
    // When embedded (landing page), hide the error and let the page render without globe
    if (props.embedded && viewerContainer.value) {
      viewerContainer.value.style.display = 'none'
    }
    return
  }

  // ─── Twilight Terminator scene (Direction D) ─────────────────────────────
  // The planet is lit by the real sun, imagery blends day/night along the
  // terminator, and the default skyBox gives us a starfield behind the globe.
  // Background stays near-black because the skyBox now fills the void.
  v.scene.backgroundColor = Color.fromCssColorString('#020304')
  v.scene.globe.baseColor = Color.fromCssColorString('#05070d')

  // Real-time lighting — sun position drives day/night terminator. The clock
  // is set to wall-clock UTC with multiplier=1 so the terminator advances in
  // real time (Europe afternoon, Beijing deep night, matches ISS-cam reality).
  v.clock.currentTime = JulianDate.fromDate(new Date())
  v.clock.multiplier = 1
  v.clock.shouldAnimate = true
  v.clock.clockRange = ClockRange.UNBOUNDED
  v.scene.globe.enableLighting = showTerminator.value
  v.scene.globe.dynamicAtmosphereLighting = true
  v.scene.globe.dynamicAtmosphereLightingFromSun = false

  // Sun + moon visible for scale. v3: glowFactor pushed to 3.2 so the sun
  // reads as a proper bright light source even without atmosphere — it used
  // to disappear into the sky when atmosphere was off.
  if (v.scene.sun) {
    v.scene.sun.show = true
    v.scene.sun.glowFactor = 3.2
  }
  if (v.scene.moon) v.scene.moon.show = true

  // Custom skyBox → procedurally generated high-contrast starfield. Cesium's
  // built-in Tycho composite reads as grainy haze; ours is pinpoint stars on
  // a near-black cube with sparse nebular wash. Falls back to whatever the
  // Viewer constructor installed if generation fails.
  const customSky = buildCustomSkyBox()
  if (customSky) v.scene.skyBox = customSky

  // Texture sharpness on zoom-in:
  //   1. resolutionScale = devicePixelRatio — Cesium renders at true physical
  //      pixel density. No upper cap: high-DPR displays (3x+) are the whole
  //      reason to set this explicitly. GPUs from the last decade handle it.
  //   2. maximumScreenSpaceError = 1.0 — Cesium's native-maximum sharpness.
  //      Forces the highest-LOD tiles the provider offers at every zoom.
  //   3. preloadAncestors/Siblings — smooth LOD transitions during motion.
  try {
    const dpr = window.devicePixelRatio || 1
    v.resolutionScale = dpr
  } catch { /* non-fatal */ }
  try {
    v.scene.globe.maximumScreenSpaceError = 1.0
    v.scene.globe.preloadAncestors = true
    v.scene.globe.preloadSiblings = true
  } catch { /* non-fatal */ }

  // Sky atmosphere = rim glow around globe edge. v4: zeroed every shift —
  // any non-zero pump makes the terminator band visible at grazing angles
  // because atmosphere scattering already peaks there. Cesium's defaults
  // give a natural dusk blue rim that fades smoothly into the night side.
  if (v.scene.skyAtmosphere) {
    v.scene.skyAtmosphere.show = showAtmosphere.value
    // AGENTWORLD-CINEMA: graded limb — a touch brighter + more saturated blue
    v.scene.skyAtmosphere.brightnessShift = 0.06
    v.scene.skyAtmosphere.hueShift = 0.00
    v.scene.skyAtmosphere.saturationShift = 0.18
  }

  // Ground atmosphere — v4 zeroes every shift so the lighting + scattering
  // does all the work without any artistic pump. The historical "blue wash"
  // concern (commented at L528 pre-D) is handled now by the hueShift
  // staying at 0 (Cesium's defaults are tuned for physical realism, not the
  // old WMS imagery that triggered the original wash).
  v.scene.globe.showGroundAtmosphere = true
  v.scene.globe.atmosphereHueShift = 0.00
  v.scene.globe.atmosphereSaturationShift = 0.00
  v.scene.globe.atmosphereBrightnessShift = 0.00
  // Cesium ≥ 1.110: scales how strongly the atmosphere blends into the
  // lit hemisphere. Higher = smoother day/night fade. v4: 10 → 20 to push
  // the terminator transition as soft as the shader allows.
  try { (v.scene.globe as any).atmosphereLightIntensity = 20.0 } catch { /* older Cesium */ }

  // Fog stays off — the terminator already provides all the atmospheric
  // depth cue we need, and fog tends to muddy the night side.
  v.scene.fog.enabled = false

  // Remove default imagery and add a dark tile layer as the planet's day-side
  // basemap. §BASEMAP (2026-08-31): this was CARTO dark_nolabels until CARTO
  // began baking an "API KEY REQUIRED" watermark into every keyless tile — on
  // the landing page, on every node, with no key ever having existed here. The
  // planet is now self-hosted: a z0-6 WebMercator pyramid generated from
  // public-domain Natural Earth (scratchpad/carto_replace/gen_basemap.py),
  // palette-matched to the old look (ocean #090909 · land #262626 · borders
  // #131313), shipped in the FE bundle under public/assets/basemap and served
  // same-origin by every registry. No key, no third party, no dial-out. Beyond
  // z6 Cesium upsamples ancestor tiles — this view is arcs and dots; there was
  // never street-level detail to lose.
  v.imageryLayers.removeAll()
  try {
    const darkLayer = new ImageryLayer(
      new UrlTemplateImageryProvider({
        url: '/assets/basemap/{z}/{x}/{y}.png',
        maximumLevel: 6,
        credit: 'Natural Earth',
      })
    )
    v.imageryLayers.add(darkLayer)
  } catch {
    // Fallback: just use the dark base color
  }

  // ─── Night-lights overlay (NASA GIBS VIIRS Black Marble) ────────────────
  // Second imagery layer that paints real city lights onto the dark side of
  // the terminator. Cesium's built-in dayAlpha/nightAlpha blending uses the
  // same sun position as globe.enableLighting, so lights appear only where
  // it's actually dark. The 2016-01-01 composite is a static release, so its
  // tiles (zoom 0-4, public domain) are served from this origin since
  // 2026-09-30: loading them from NASA's tile server sent every
  // visitor's address to NASA, which the Privacy Policy says we never do
  // (REVIEW_2026-09-30_LICENSING.md; provenance in public/assets/nightlights/SOURCE.txt).
  try {
    const nightLightsLayer = new ImageryLayer(
      new UrlTemplateImageryProvider({
        url: '/assets/nightlights/{z}/{y}/{x}.png',
        maximumLevel: 4,
        credit: 'NASA GIBS · VIIRS Black Marble',
      })
    )
    // Fully transparent on the sunlit hemisphere, fully opaque on the night
    // hemisphere — Cesium blends per-pixel against the lighting terminator.
    // v4: nightAlpha 0.70 → 0.55 so the ramp-up at the dusk line is gentler
    // still. Commander specifically asked for near-invisible terminator.
    nightLightsLayer.dayAlpha = 0.0
    nightLightsLayer.nightAlpha = showNightLights.value ? 0.55 : 0.0
    nightLightsLayer.brightness = 1.05
    v.imageryLayers.add(nightLightsLayer)
    ;(v as any)._nightLightsLayer = nightLightsLayer
    // Fail-soft: if a tile is missing, drop the layer silently rather
    // than blocking the globe. The base Natural Earth layer is always present.
    try {
      const onNightLightsErr = (err: any) => {
        log.debug('GIBS tile error (non-fatal):', err?.message || err)
      }
      nightLightsLayer.imageryProvider.errorEvent.addEventListener(onNightLightsErr)
      _cesiumCleanups.push(() => {
        try { nightLightsLayer.imageryProvider.errorEvent.removeEventListener(onNightLightsErr) } catch { /* */ }
      })
    } catch { /* addEventListener may not be present in older Cesium */ }
  } catch (gibsErr) {
    log.debug('Night lights overlay unavailable:', gibsErr)
  }

  // Initial camera: face Freilassing (47.84N, 12.98E)
  // When embedded on landing page: show Europe+Asia spread
  if (props.embedded) {
    const isMobilePortrait = window.innerWidth < 768
    if (isMobilePortrait) {
      // Mobile portrait: bring camera closer + slight tilt so globe fills the narrow viewport
      v.camera.setView({
        destination: Cartesian3.fromDegrees(20, 35, 16_000_000),
        orientation: { heading: CesiumMath.toRadians(0), pitch: CesiumMath.toRadians(-75), roll: 0 },
      })
    } else {
      // Desktop/tablet: original wide view
      v.camera.setView({
        destination: Cartesian3.fromDegrees(30, 25, 25_000_000),
        orientation: { heading: CesiumMath.toRadians(0), pitch: CesiumMath.toRadians(-90), roll: 0 },
      })
    }
  } else {
    // AGENTWORLD-CINEMA: opening shot — drift in from deep orbit to the home
    // view (Freilassing). Skipped for reduced-motion (instant setView).
    const awReducedMotion = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (awReducedMotion) {
      v.camera.setView({
        destination: Cartesian3.fromDegrees(12.98, 47.84, 18_000_000),
        orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
      })
    } else {
      v.camera.setView({
        destination: Cartesian3.fromDegrees(-24, 18, 46_000_000),
        orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
      })
      v.camera.flyTo({
        destination: Cartesian3.fromDegrees(12.98, 47.84, 18_000_000),
        orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
        duration: 4.2,
      })
    }
  }

  // Auto-rotate is handled by the animation loop (updateArcs) which calls requestRender()

  // Disable double-click zoom (annoying)
  v.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK)

  // When embedded in landing page, disable pointer events so hero buttons remain clickable
  if (props.embedded) {
    viewerContainer.value!.style.pointerEvents = 'none'
    // Force periodic renders to ensure tiles appear on mobile (requestRenderMode
    // can prevent initial paint if no user interaction triggers a render).
    // Stops as soon as the first real frame paints (postRender fired) — no
    // point burning CPU on force-renders once Cesium is actively drawing.
    let stopped = false
    const forceRenderInterval = setInterval(() => {
      if (v.isDestroyed()) { clearInterval(forceRenderInterval); stopped = true; return }
      v.scene.requestRender()
    }, 1000)
    const onFirstPaint = () => {
      if (stopped) return
      stopped = true
      clearInterval(forceRenderInterval)
      v.scene.postRender.removeEventListener(onFirstPaint)
      // Signal parent that the globe has painted at least once so it can
      // start expensive side work (e.g. open EventStore WS).
      try { props.onReady?.() } catch { /* parent callback errors non-fatal */ }
    }
    v.scene.postRender.addEventListener(onFirstPaint)
    // Hard stop after 30s even if postRender never fired (stall guard)
    setTimeout(() => {
      if (!stopped) {
        stopped = true
        clearInterval(forceRenderInterval)
        // Still fire onReady so parent doesn't wait forever
        try { props.onReady?.() } catch { /* */ }
      }
    }, 30000)

    // Texture-streaming backpressure. Hold events while tiles are in flight,
    // drain slowly once the scene has been fully loaded for a cooldown window.
    try {
      // Primary gate: tilesLoaded flips when Cesium thinks every tile in view
      // is on the GPU. Progress-event still useful as a "something happened"
      // signal so we re-check the gate.
      const reevaluateGate = () => {
        const loaded = v.scene.globe.tilesLoaded
        const motionAgo = Date.now() - cameraMotionTs
        const inMotion = motionAgo < EMBEDDED_CAMERA_HOLD_MS
        const shouldBlock = !loaded || inMotion
        if (shouldBlock) {
          setTextureGateBlocked(true)
        } else if (textureGateBlocked) {
          // Tiles just became fully loaded AND camera is quiet. Wait a
          // cooldown interval before releasing so the GPU has time to
          // settle before we re-introduce event pressure.
          setTimeout(() => {
            if (v.scene.globe.tilesLoaded &&
                Date.now() - cameraMotionTs >= EMBEDDED_CAMERA_HOLD_MS) {
              setTextureGateBlocked(false)
              scheduleDrain()
            }
          }, EMBEDDED_SETTLE_COOLDOWN_MS)
        }
      }
      v.scene.globe.tileLoadProgressEvent.addEventListener(reevaluateGate)
      _cesiumCleanups.push(() => {
        try { v.scene.globe.tileLoadProgressEvent.removeEventListener(reevaluateGate) } catch { /* */ }
      })
      // Camera-motion hook: any change stamps cameraMotionTs + blocks gate
      // immediately so the very first frame of a zoom doesn't leak an event.
      const onCameraChanged = () => {
        cameraMotionTs = Date.now()
        setTextureGateBlocked(true)
      }
      v.camera.changed.addEventListener(onCameraChanged)
      _cesiumCleanups.push(() => {
        try { v.camera.changed.removeEventListener(onCameraChanged) } catch { /* */ }
      })
      // camera.changed requires a threshold to start firing.
      v.camera.percentageChanged = 0.001
      // Kick off: evaluate once to set initial state correctly.
      reevaluateGate()
    } catch (backpressureErr) {
      // Fail open — if any of these APIs aren't available, events just
      // process immediately as before.
      setTextureGateBlocked(false)
      log.debug('texture backpressure unavailable:', backpressureErr)
    }
  } else if (props.onReady) {
    // Non-embedded callers can also listen for first paint if they want to
    // defer work. Standalone page rarely needs this, but the hook is symmetric.
    const onFirstPaintStandalone = () => {
      v.scene.postRender.removeEventListener(onFirstPaintStandalone)
      try { props.onReady?.() } catch { /* */ }
    }
    v.scene.postRender.addEventListener(onFirstPaintStandalone)
  }

  viewer.value = v
  setupInteraction()
  setupPostProcessing(v)
  // Dev-tools / Playwright hook (safe; read-only by convention).
  if (typeof window !== 'undefined') {
    window.__aw_viewer = v
    window.__aw_registries = worldRegistries
  }
}

// ─── Post-processing (bloom + vignette + chromatic aberration) ───────────
// Three stages, all individually toggleable, all fail-soft. Bloom is Cesium's
// native composite stage; vignette and chromatic aberration are custom
// fragment shaders written in GLSL 3.00 ES (Cesium's post-process convention
// uses `in vec2 v_textureCoordinates` and writes to `out_FragColor`).
function setupPostProcessing(v: Viewer) {
  try {
    // Bloom — tuned so it lifts bright arcs, the sun, and city lights on the
    // night side without blowing out continent tiles. glowOnly=false so the
    // base imagery still passes through; a stronger threshold (`contrast`,
    // `brightness`) keeps only the bright pixels in the bloom source.
    if (v.scene.postProcessStages?.bloom) {
      const bloom = v.scene.postProcessStages.bloom
      bloom.enabled = showBloom.value
      const u = bloom.uniforms as any
      u.glowOnly = false
      u.contrast = 120
      // v4 retune: threshold lifted further (-0.55 → -0.7) so only
      // genuinely bright sources (arcs, sun, accretion disk, brightest
      // stars) bloom. At v3 values the 8000-star-per-face field bloomed
      // collectively into a soft haze. Tighter sigma too.
      u.brightness = -0.7
      u.delta = 1.5
      u.sigma = 2.0
      u.stepSize = 2.0
      u.isSelected = false
    }
  } catch (bloomErr) {
    log.debug('Bloom unavailable:', bloomErr)
  }

  // Lens flare — Cesium's native composite. Gives the sun a proper cinematic
  // flare as it crosses the limb or peeks from behind the night hemisphere.
  // Required for the sun to read as the "star" of the scene (Commander flagged
  // that with atmosphere off, the sun was nearly invisible).
  try {
    if (v.scene.postProcessStages?.lensFlare) {
      v.scene.postProcessStages.lensFlare.enabled = true
      const lf = v.scene.postProcessStages.lensFlare.uniforms as any
      // Dial the intensity up a touch from defaults so the flare reads on a
      // bloom-darkened scene but isn't clown-honk loud. Distortion/ghost
      // defaults are fine — tuned by Cesium for cinematic aesthetics.
      lf.intensity = 2.0
      lf.dirtAmount = 0.4
    }
  } catch (lfErr) {
    log.debug('Lens flare unavailable:', lfErr)
  }

  // Vignette — soft darken toward corners. Very cheap (one texture sample per
  // pixel, one smoothstep, one multiply) and gives the view that "cinema
  // letterbox" focus without actually letterboxing.
  try {
    vignetteStage = new PostProcessStage({
      name: 'agentworld_vignette',
      fragmentShader: `
        uniform sampler2D colorTexture;
        uniform float u_strength;
        in vec2 v_textureCoordinates;
        void main() {
          vec4 color = texture(colorTexture, v_textureCoordinates);
          vec2 uv = v_textureCoordinates - vec2(0.5);
          float dist = length(uv);
          float vig = smoothstep(0.30, 0.90, dist);
          color.rgb *= (1.0 - vig * u_strength);
          out_FragColor = color;
        }
      `,
      uniforms: { u_strength: 0.35 },
    })
    vignetteStage.enabled = showVignette.value
    v.scene.postProcessStages.add(vignetteStage)
  } catch (vigErr) {
    log.debug('Vignette stage unavailable:', vigErr)
    vignetteStage = null
  }

  // Chromatic aberration — sample R/G/B at slightly offset UVs, weighted by
  // distance from centre (zero at centre, maximum at corners). Strength 0.003
  // means roughly 3 px of offset at a 1080p corner — subtle, the kind of thing
  // you notice only when you turn it off. Default off; power-user toggle.
  try {
    chromaticAberrationStage = new PostProcessStage({
      name: 'agentworld_chromatic_aberration',
      fragmentShader: `
        uniform sampler2D colorTexture;
        uniform float u_strength;
        in vec2 v_textureCoordinates;
        void main() {
          vec2 uv = v_textureCoordinates;
          vec2 dir = uv - vec2(0.5);
          float dist = length(dir) * 2.0;
          float offset = u_strength * dist * dist;
          vec2 offR = dir * offset;
          vec2 offB = -dir * offset;
          float r = texture(colorTexture, uv + offR).r;
          float g = texture(colorTexture, uv).g;
          float b = texture(colorTexture, uv + offB).b;
          float a = texture(colorTexture, uv).a;
          out_FragColor = vec4(r, g, b, a);
        }
      `,
      uniforms: { u_strength: 0.006 },
    })
    chromaticAberrationStage.enabled = showChromaticAberration.value
    v.scene.postProcessStages.add(chromaticAberrationStage)
  } catch (caErr) {
    log.debug('Chromatic aberration stage unavailable:', caErr)
    chromaticAberrationStage = null
  }
}

// ─── Interaction (Click + Hover) ───────────────────────────────────────────

// Cesium's scene.pick() throws DeveloperError("drawingBufferWidth must be
// greater than zero") when the canvas backing-buffer is 0×0 — happens when
// an ancestor goes display:none (theme/drawer/modal transitions), during the
// unmount race window before handler.destroy() runs, in heavily throttled
// background tabs, or on WebGL context loss. The guard below catches all
// four; the try/catch around pick() is belt-and-suspenders for the rare
// case where dimensions flip between check and call.
function canSafelyPick(v: Viewer | null): boolean {
  if (!v) return false
  try { if (v.isDestroyed()) return false } catch { return false }
  const canvas = v.scene?.canvas as HTMLCanvasElement | undefined
  if (!canvas) return false
  if (canvas.clientWidth <= 0 || canvas.clientHeight <= 0) return false
  return true
}

function setupInteraction() {
  const v = viewer.value
  if (!v) return

  handler = new ScreenSpaceEventHandler(v.scene.canvas)

  // Click
  handler.setInputAction((click: { position: Cartesian2 }) => {
    if (!canSafelyPick(v)) return
    let picked: any
    try {
      picked = v.scene.pick(click.position)
    } catch (err) {
      log.debug('scene.pick (click) failed:', err)
      return
    }
    if (defined(picked) && picked.id && picked.id.properties) {
      const props = picked.id.properties
      const type = props.entityType?.getValue(v.clock.currentTime)
      if (type === 'agent' || type === 'agentFlare') {
        const a = props.agentData?.getValue(v.clock.currentTime) as WorldAgent
        // GC2-7 cockpit: emit the pick (with its home-registry NAME so the GCC
        // can resolve a directory entry) instead of opening the detail modal.
        if (cockpitOn.value) {
          if (a?.did) {
            const homeReg = worldRegistries.value.find(r => r.id === a.registryId)
            emit('select-agent', { did: a.did, name: a.name, registryName: homeReg?.name })
            flyToCoords(a.lat, a.lng)
          }
          return
        }
        selectedAgent.value = a
        selectedRegistry.value = null
        if (selectedAgent.value) {
          flyToCoords(selectedAgent.value.lat, selectedAgent.value.lng)
          // Open the full agent detail modal (mirrors the registry card click). §EMBEDGATE-3:
          // the embedded/anonymous globe opens the SAME card everyone else sees — the lookup is
          // a public rail and the card is public at /explore, so a teaser here was a wall in
          // front of an open door.
          if (selectedAgent.value.did) showAgentModal.value = true
        }
      } else if (type === 'registry' || type === 'registryHalo' || type === 'registryPillar') {
        const reg = props.registryData?.getValue(v.clock.currentTime) as WorldRegistry
        // GC2-7 cockpit: registry click = retarget the Bridge, not a card modal.
        if (cockpitOn.value) {
          if (reg) { emit('select-registry', reg); flyToCoords(reg.lat, reg.lng) }
          return
        }
        selectedRegistry.value = null   // suppress the old single-column inline panel
        selectedAgent.value = null
        if (reg) {
          // Open the full, fits-on-screen, two-column Registry Card modal.
          regCardPeer.value = (reg.id === '__local__') ? null : reg.name
          regCardFallback.value = reg.name
          showRegCard.value = true
          flyToCoords(reg.lat, reg.lng)
        }
      }
    } else {
      selectedAgent.value = null
      selectedRegistry.value = null
    }
  }, ScreenSpaceEventType.LEFT_CLICK)

  // Hover
  let hoverThrottle: ReturnType<typeof setTimeout> | null = null
  handler.setInputAction((movement: { endPosition: Cartesian2 }) => {
    if (hoverThrottle) return
    hoverThrottle = setTimeout(() => { hoverThrottle = null }, 50)

    if (!canSafelyPick(v)) return
    let picked: any
    try {
      picked = v.scene.pick(movement.endPosition)
    } catch (err) {
      log.debug('scene.pick (hover) failed:', err)
      return
    }
    if (defined(picked) && picked.id && picked.id.properties) {
      const props = picked.id.properties
      const type = props.entityType?.getValue(v.clock.currentTime)
      // HOVER-FIX (2026-06-11): elite agents are topped by an 'agentFlare'
      // billboard, and every site by 'registryHalo'/'registryPillar' beams.
      // Resolve those overlays to their owning agent/registry instead of
      // treating the pick as empty (which blanked hover on flared/high agents).
      if (type === 'agent' || type === 'agentFlare') {
        hoveredAgent.value = props.agentData?.getValue(v.clock.currentTime) as WorldAgent
        hoveredRegistry.value = null
      } else if (type === 'registry' || type === 'registryHalo' || type === 'registryPillar') {
        hoveredRegistry.value = props.registryData?.getValue(v.clock.currentTime) as WorldRegistry
        hoveredAgent.value = null
      } else {
        hoveredAgent.value = null
        hoveredRegistry.value = null
      }
      // Screen position for tooltip
      const pos = picked.id.position?.getValue(v.clock.currentTime)
      if (pos) {
        const screenPos = SceneTransforms.worldToWindowCoordinates(v.scene, pos)
        if (screenPos) hoverPos.value = { x: screenPos.x, y: screenPos.y }
      }
    } else {
      hoveredAgent.value = null
      hoveredRegistry.value = null
    }
  }, ScreenSpaceEventType.MOUSE_MOVE)
}

// ─── Custom starfield skybox (Direction D) ───────────────────────────────
// v6 rebuild: every cosmic feature (Milky Way band, nebulae, galaxies, black
// hole) is positioned in 3D world-space and projected onto whichever cube
// face it happens to fall on. This eliminates the visible seams the earlier
// per-face approach created when adjacent faces had mismatched density or
// features (Milky Way on face 0 ending abruptly at the edge of face 4).
//
// Cost: ~120ms on mount for six 2048² canvases. Zero per-frame.
// If generation fails, we log once and fall through to Cesium's default.

type Vec3 = { x: number; y: number; z: number }
function normalize3(v: Vec3): Vec3 {
  const n = Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
  return n > 0 ? { x: v.x / n, y: v.y / n, z: v.z / n } : { x: 1, y: 0, z: 0 }
}

// Cube face UV → 3D unit direction. Face indices match Cesium SkyBox sources:
//   0 +X, 1 -X, 2 +Y, 3 -Y, 4 +Z, 5 -Z
function faceUVToDir(face: number, u01: number, v01: number): Vec3 {
  const a = u01 * 2 - 1, b = v01 * 2 - 1
  let x = 0, y = 0, z = 0
  switch (face) {
    case 0: x =  1; y = -b; z = -a; break
    case 1: x = -1; y = -b; z =  a; break
    case 2: x =  a; y =  1; z =  b; break
    case 3: x =  a; y = -1; z = -b; break
    case 4: x =  a; y = -b; z =  1; break
    case 5: x = -a; y = -b; z = -1; break
  }
  return normalize3({ x, y, z })
}

// 3D unit direction → (face, u01, v01). Inverse of faceUVToDir. Every
// direction on the unit sphere projects onto exactly one face.
function dirToFaceUV(d: Vec3): { face: number; u: number; v: number } {
  const ax = Math.abs(d.x), ay = Math.abs(d.y), az = Math.abs(d.z)
  let face: number, u: number, v: number
  if (ax >= ay && ax >= az) {
    if (d.x > 0) { face = 0; u = -d.z / ax; v = -d.y / ax }
    else         { face = 1; u =  d.z / ax; v = -d.y / ax }
  } else if (ay >= az) {
    if (d.y > 0) { face = 2; u =  d.x / ay; v =  d.z / ay }
    else         { face = 3; u =  d.x / ay; v = -d.z / ay }
  } else {
    if (d.z > 0) { face = 4; u =  d.x / az; v = -d.y / az }
    else         { face = 5; u = -d.x / az; v = -d.y / az }
  }
  return { face, u: (u + 1) * 0.5, v: (v + 1) * 0.5 }
}

// Uniform random point on the unit sphere (equal-area).
function randomDir3(rng: () => number): Vec3 {
  const phi = 2 * Math.PI * rng()
  const cosTheta = 2 * rng() - 1
  const sinTheta = Math.sqrt(1 - cosTheta * cosTheta)
  return { x: sinTheta * Math.cos(phi), y: sinTheta * Math.sin(phi), z: cosTheta }
}

// Galactic plane pole — the band lies perpendicular to this direction. Tilt
// chosen so the Milky Way crosses multiple cube faces dramatically rather
// than lying hidden along a single axis.
const GALACTIC_POLE = normalize3({ x: 0.42, y: 0.72, z: 0.55 })
// Returns 0 at the galactic equator (densest), 1 at the pole (emptiest).
function galacticPoleDistance(dir: Vec3): number {
  return Math.abs(dir.x * GALACTIC_POLE.x + dir.y * GALACTIC_POLE.y + dir.z * GALACTIC_POLE.z)
}

// Seeded PRNG (Mulberry32). Same seed → same star field every time.
function mulberry32(seed: number): () => number {
  return function () {
    seed = (seed + 0x6d2b79f5) | 0
    let t = seed
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Star colour palette. 70% neutral white, 20% warm, 10% cool — broadly
// matches actual stellar class distribution in a randomly-sampled sky patch.
const STAR_COLORS = [
  { r: 240, g: 244, b: 255 }, // neutral white (O/B dominant)
  { r: 240, g: 244, b: 255 },
  { r: 240, g: 244, b: 255 },
  { r: 240, g: 244, b: 255 },
  { r: 240, g: 244, b: 255 },
  { r: 240, g: 244, b: 255 },
  { r: 240, g: 244, b: 255 },
  { r: 255, g: 217, b: 168 }, // warm amber (K/M)
  { r: 255, g: 217, b: 168 },
  { r: 207, g: 232, b: 255 }, // cool blue-white (F/A)
]

// v4 — photographic-quality distant black hole. Composited from six layers
// that together simulate gravitational lensing, Doppler beaming, and
// relativistic disk dynamics on a static canvas. Draw order is critical:
//   1. Outer warm halo (far-field scattered light)
//   2. Pre-lensed "Einstein arcs" — three faint concentric rings showing
//      where light from stars behind the BH is bent around to us
//   3. Tilted accretion disk — elliptical, with Doppler-beaming brighter
//      on the approaching side + turbulent plasma streaks
//   4. Photon ring — the hot thin ring at the horizon radius
//   5. Event horizon — pitch black, painted LAST inside the composite so it
//      correctly covers every photon that would have been swallowed
//   6. Outer chromatic fringe — faint blue/red offsets at the disc edges
//
// Also: `lensStarDisplacement` is called before this function by the face
// renderer to pre-bend the starfield around the BH.
function drawBlackHole(ctx: CanvasRenderingContext2D, cx: number, cy: number, size: number, rng: () => number) {
  const horizonR = size * 0.45
  const diskInnerR = horizonR * 1.02         // inner accretion edge — hugs horizon
  const diskOuterR = size * 1.00
  const diskTilt = 0.35                       // radians — disc tilted toward camera
  const cosTilt = Math.cos(diskTilt)

  // 1. Outer warm halo — large faint amber gradient.
  const outerR = size * 1.7
  const outerGlow = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerR)
  outerGlow.addColorStop(0.00, 'rgba(255, 180, 90, 0.00)')
  outerGlow.addColorStop(0.25, 'rgba(255, 180, 90, 0.08)')
  outerGlow.addColorStop(0.55, 'rgba(255, 140, 50, 0.05)')
  outerGlow.addColorStop(1.00, 'rgba(255, 100, 25, 0.00)')
  ctx.fillStyle = outerGlow
  ctx.beginPath(); ctx.arc(cx, cy, outerR, 0, Math.PI * 2); ctx.fill()

  // 2. Einstein arcs — three faint lensed-light rings outside the horizon at
  // physically-plausible lensing radii. These sit ON TOP of displaced stars
  // (see drawLensStarDisplacement below) to suggest the ring images form
  // from light that grazed the BH.
  const EINSTEIN_RADII = [horizonR * 1.38, horizonR * 1.82, horizonR * 2.40]
  const EINSTEIN_ALPHAS = [0.28, 0.16, 0.08]
  for (let i = 0; i < EINSTEIN_RADII.length; i++) {
    ctx.strokeStyle = `rgba(255, 230, 200, ${EINSTEIN_ALPHAS[i]})`
    ctx.lineWidth = 1.2
    ctx.beginPath(); ctx.arc(cx, cy, EINSTEIN_RADII[i], 0, Math.PI * 2); ctx.stroke()
    // Soft halo pass
    ctx.strokeStyle = `rgba(255, 210, 170, ${EINSTEIN_ALPHAS[i] * 0.4})`
    ctx.lineWidth = 4.0
    ctx.beginPath(); ctx.arc(cx, cy, EINSTEIN_RADII[i], 0, Math.PI * 2); ctx.stroke()
  }

  // 3. Accretion disk — tilted ellipse with Doppler beaming. Drawn in a
  // transformed coordinate space where we scale Y by cos(tilt) so a circle
  // becomes an ellipse viewed from 20° above the disc plane. Doppler beaming
  // multiplies brightness on the approaching side (here: left, per disc
  // rotation direction picked by rng).
  const rotateSign = rng() < 0.5 ? 1 : -1   // approaching-side toggle
  ctx.save()
  ctx.translate(cx, cy)
  ctx.scale(1, cosTilt)
  // Disc body gradient — radial from inner edge outward. Warm amber core,
  // fading to deep red at the outer edge. Peak brightness ring at 1.1×
  // horizon radius.
  const disc = ctx.createRadialGradient(0, 0, horizonR * 0.95, 0, 0, diskOuterR)
  disc.addColorStop(0.00, 'rgba(255, 220, 150, 0.00)')
  disc.addColorStop(0.08, 'rgba(255, 235, 190, 0.88)')
  disc.addColorStop(0.22, 'rgba(255, 180, 100, 0.60)')
  disc.addColorStop(0.55, 'rgba(255, 110, 50, 0.25)')
  disc.addColorStop(1.00, 'rgba(200, 50, 20, 0.00)')
  ctx.fillStyle = disc
  ctx.beginPath(); ctx.arc(0, 0, diskOuterR, 0, Math.PI * 2); ctx.fill()

  // Doppler beaming overlay — half-circle on the approaching side draws a
  // brighter cool-shifted gradient on top. Subtracts a half-circle on the
  // receding side (warm-red dim).
  ctx.globalCompositeOperation = 'lighter'
  const beamApproach = ctx.createRadialGradient(0, 0, horizonR, 0, 0, diskOuterR * 0.9)
  beamApproach.addColorStop(0.00, 'rgba(180, 230, 255, 0.00)')
  beamApproach.addColorStop(0.15, 'rgba(220, 240, 255, 0.45)')
  beamApproach.addColorStop(0.50, 'rgba(240, 230, 220, 0.18)')
  beamApproach.addColorStop(1.00, 'rgba(255, 200, 150, 0.00)')
  ctx.fillStyle = beamApproach
  ctx.beginPath()
  ctx.arc(0, 0, diskOuterR * 0.9, rotateSign > 0 ? Math.PI / 2 : -Math.PI / 2,
                                   rotateSign > 0 ? Math.PI * 1.5 : Math.PI / 2)
  ctx.lineTo(0, 0); ctx.closePath(); ctx.fill()
  ctx.globalCompositeOperation = 'source-over'

  // Turbulent plasma streaks — ~50 tiny arc overlays at random radii + arc
  // lengths. Suggests gas swirling into the horizon. Only on the approaching
  // side so they don't wash out the darker receding half.
  ctx.globalCompositeOperation = 'lighter'
  for (let i = 0; i < 50; i++) {
    const r = horizonR * 1.05 + rng() * (diskOuterR - horizonR * 1.05)
    const startAng = rng() * Math.PI * 2
    const arcLen = 0.08 + rng() * 0.25
    const alpha = 0.04 + rng() * 0.10
    ctx.strokeStyle = `rgba(255, ${180 + Math.floor(rng() * 50)}, ${80 + Math.floor(rng() * 60)}, ${alpha})`
    ctx.lineWidth = 0.6 + rng() * 1.4
    ctx.beginPath(); ctx.arc(0, 0, r, startAng, startAng + arcLen); ctx.stroke()
  }
  ctx.globalCompositeOperation = 'source-over'
  ctx.restore()

  // 4. Photon ring — thin hot ring at the exact horizon radius. Two passes:
  // a tight bright white-cyan core + a wider soft halo. Slightly brighter
  // on the approaching side via a stroke gradient.
  ctx.strokeStyle = 'rgba(255, 250, 240, 0.95)'
  ctx.lineWidth = 1.6
  ctx.beginPath(); ctx.arc(cx, cy, horizonR, 0, Math.PI * 2); ctx.stroke()
  ctx.strokeStyle = 'rgba(220, 240, 255, 0.45)'
  ctx.lineWidth = 4.5
  ctx.beginPath(); ctx.arc(cx, cy, horizonR, 0, Math.PI * 2); ctx.stroke()

  // 5. Event horizon — pitch black. Drawn LAST so it covers any disc light
  // that leaked over the horizon edge + swallows any star that happens to
  // be behind it (physically correct: no light escapes).
  ctx.fillStyle = '#000000'
  ctx.beginPath(); ctx.arc(cx, cy, horizonR, 0, Math.PI * 2); ctx.fill()

  // 6. Chromatic fringe — very faint blue/red offsets at the disc edges,
  // suggesting relativistic frequency shift. One extra tiny ring in each
  // tint, 1 px offset in opposite directions along the beaming axis.
  const fringeR = horizonR * 1.02
  ctx.strokeStyle = 'rgba(150, 180, 255, 0.35)'
  ctx.lineWidth = 0.8
  ctx.beginPath(); ctx.arc(cx - rotateSign * 0.8, cy, fringeR, 0, Math.PI * 2); ctx.stroke()
  ctx.strokeStyle = 'rgba(255, 120, 100, 0.28)'
  ctx.beginPath(); ctx.arc(cx + rotateSign * 0.8, cy, fringeR, 0, Math.PI * 2); ctx.stroke()
}

// Draw a tiny distant galaxy cluster — an elliptical / face-on disk galaxy
// rendered as a composite of (1) a faint elongated halo, (2) a narrow disk
// core, and (3) a bright nucleus pinprick. Randomised tint nudges toward
// warm (older, quiescent populations) or cool (active star formation), with
// a small chance of a neutral yellow-white ellipse. Designed to read at
// 15–40 px as "distant galaxy" rather than "nebula" or "bright star."
function drawGalaxy(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number,
  majorR: number,            // semi-major-axis radius (px)
  axisRatio: number,          // 0.3 (edge-on) → 1.0 (face-on)
  angleRad: number,           // tilt of the major axis
  rng: () => number,
) {
  // Tint: 50% warm, 30% cool, 20% neutral.
  const pick = rng()
  const tint = pick < 0.5
    ? { r: 255, g: 210, b: 160 }   // warm amber (old stars)
    : pick < 0.8
    ? { r: 170, g: 200, b: 255 }    // cool blue (young stars)
    : { r: 240, g: 230, b: 210 }    // neutral yellow-white
  ctx.save()
  ctx.translate(cx, cy)
  ctx.rotate(angleRad)
  ctx.scale(1, axisRatio)

  // Outer halo — faint fuzzy ellipse.
  const haloGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, majorR * 1.25)
  haloGrad.addColorStop(0.0, `rgba(${tint.r},${tint.g},${tint.b},0.00)`)
  haloGrad.addColorStop(0.25, `rgba(${tint.r},${tint.g},${tint.b},0.10)`)
  haloGrad.addColorStop(0.55, `rgba(${tint.r},${tint.g},${tint.b},0.05)`)
  haloGrad.addColorStop(1.00, `rgba(${tint.r},${tint.g},${tint.b},0.00)`)
  ctx.fillStyle = haloGrad
  ctx.beginPath(); ctx.arc(0, 0, majorR * 1.25, 0, Math.PI * 2); ctx.fill()

  // Disk — brighter body of the galaxy.
  const bodyGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, majorR * 0.75)
  bodyGrad.addColorStop(0.0, `rgba(${tint.r},${tint.g},${tint.b},0.55)`)
  bodyGrad.addColorStop(0.4, `rgba(${tint.r},${tint.g},${tint.b},0.22)`)
  bodyGrad.addColorStop(1.0, `rgba(${tint.r},${tint.g},${tint.b},0.00)`)
  ctx.fillStyle = bodyGrad
  ctx.beginPath(); ctx.arc(0, 0, majorR * 0.75, 0, Math.PI * 2); ctx.fill()

  // Nucleus — tight hot core.
  ctx.restore()
  const nucGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(1.5, majorR * 0.18))
  nucGrad.addColorStop(0.0, `rgba(255,250,230,0.95)`)
  nucGrad.addColorStop(0.4, `rgba(${tint.r},${tint.g},${tint.b},0.55)`)
  nucGrad.addColorStop(1.0, `rgba(${tint.r},${tint.g},${tint.b},0.00)`)
  ctx.fillStyle = nucGrad
  ctx.beginPath(); ctx.arc(cx, cy, Math.max(1.5, majorR * 0.18), 0, Math.PI * 2); ctx.fill()
}

// Pre-lens star displacement — called BEFORE stars are drawn. Returns a
// predicate fn telling the star drawer whether to skip (stars inside the
// deflection zone are drawn here at displaced positions instead). The
// displacement field simulates gravitational deflection: stars closer to
// the BH are bent further around the horizon, creating an Einstein-ring-like
// smearing when many displaced star positions overlap.
function drawLensStarDisplacement(
  ctx: CanvasRenderingContext2D,
  cx: number, cy: number, horizonR: number,
  stars: Array<{ x: number; y: number; bright: number; col: { r: number; g: number; b: number } }>,
) {
  const deflectionR = horizonR * 3.2   // no effect outside this radius
  for (const s of stars) {
    const dx = s.x - cx, dy = s.y - cy
    const d = Math.sqrt(dx * dx + dy * dy)
    if (d < horizonR * 1.05) continue  // inside / at horizon — light swallowed, skip
    if (d > deflectionR) continue       // too far — no lensing
    // Deflection angle roughly proportional to 1/d (Schwarzschild approx).
    // Stars very close to the horizon wrap the furthest; stars near the
    // deflection boundary barely move.
    const t = (deflectionR - d) / (deflectionR - horizonR * 1.05)
    const bend = t * t * 0.6 * Math.PI   // up to ~108° of rotation
    const ang = Math.atan2(dy, dx)
    // Smear along the bend — draw the same star multiple times along a short
    // arc from the original position to the displaced position. Each step
    // gets a fraction of the brightness so the whole thing reads as a
    // smeared arc, not a discrete ghost.
    const STEPS = 6
    const scaledBright = s.bright * (0.4 + 0.6 * (1 - t))   // dimmer when bent more
    for (let k = 0; k <= STEPS; k++) {
      const frac = k / STEPS
      const newAng = ang + bend * frac
      const nx = cx + d * Math.cos(newAng)
      const ny = cy + d * Math.sin(newAng)
      const a = scaledBright * (0.25 + 0.75 * (1 - frac * 0.8))  // fade along arc
      ctx.fillStyle = `rgba(${s.col.r},${s.col.g},${s.col.b},${a * 0.35})`
      ctx.beginPath(); ctx.arc(nx, ny, 0.5, 0, Math.PI * 2); ctx.fill()
    }
  }
}

// v6: the old 2D per-face Milky Way helper was removed. The band is now
// rasterised from a 3D galactic plane in drawStarfieldFace so it flows
// seamlessly across cube seams.

// Paint the Milky Way band onto the current face by walking a coarse tile
// grid, evaluating 3D direction at each tile centre, and shading by distance
// from the galactic plane. A 32 px tile at 2048² → 64×64 = 4096 tile evals
// per face — cheap.
function paintMilkyWayBand(ctx: CanvasRenderingContext2D, face: number, size: number) {
  const TILE = 32
  for (let ty = 0; ty < size; ty += TILE) {
    for (let tx = 0; tx < size; tx += TILE) {
      const dir = faceUVToDir(face, (tx + TILE * 0.5) / size, (ty + TILE * 0.5) / size)
      const d = galacticPoleDistance(dir)
      if (d > 0.38) continue                    // outside the band
      const t = 1 - d / 0.38                    // 0 at band edge, 1 on plane
      const alpha = Math.pow(t, 1.6) * 0.20     // soft falloff
      // Silver-violet dust tint with a subtle warm shift toward the galactic
      // core (roughly where GP-perpendicular direction aligns with +y).
      const r = 215 + Math.floor(t * 25)
      const g = 205 + Math.floor(t * 10)
      const b = 230
      ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`
      ctx.fillRect(tx, ty, TILE, TILE)
    }
  }
}

// Pre-generate extra stars along the galactic band in 3D. Returns stars
// tagged with their 3D direction so each face can pull the ones that belong
// to it. Stars inside the band are denser + slightly brighter on average.
type BandStar = { dir: Vec3; bright: number; col: { r: number; g: number; b: number } }
function generateBandStars3D(rng: () => number, count: number): BandStar[] {
  const stars: BandStar[] = []
  let tries = 0
  while (stars.length < count && tries < count * 25) {
    tries++
    const dir = randomDir3(rng)
    const d = galacticPoleDistance(dir)
    if (d > 0.28) continue
    // Brightness biased toward bright — this IS the core of the galaxy.
    const u = rng()
    const pareto = Math.min(40, Math.pow(1 - u, -1 / 1.0))
    const bright = Math.min(1.0, 0.18 + (pareto - 1) * 0.050)
    stars.push({
      dir,
      bright,
      col: STAR_COLORS[Math.floor(rng() * STAR_COLORS.length)],
    })
  }
  return stars
}

// Nebula + galaxy 3D descriptors — each is a position on the unit sphere
// plus shape/size. Generated once per skybox build, then each face pulls
// the ones that belong to its cone. This is what makes them seamless.
interface Nebula3D { dir: Vec3; angularRadius: number; color: { r: number; g: number; b: number } }
interface Galaxy3D { dir: Vec3; majorR: number; axisRatio: number; angleRad: number; colorPick: number }

function drawStarfieldFace(
  face: number,
  size: number,
  nebulae: Nebula3D[],
  galaxies: Galaxy3D[],
  bandStars: BandStar[],
  blackHoleDir: Vec3,
  blackHolePx: number,
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  // Pitch-black base.
  ctx.fillStyle = '#000000'
  ctx.fillRect(0, 0, size, size)

  // Deterministic per-face seed for local (non-3D) randomness: per-face star
  // field, galaxy local rng, etc. 3D-positioned features share a global
  // seed so they're continuous across faces.
  const rng = mulberry32(0x9e3779b9 ^ (face * 2654435761))

  // v7: the tile-based Milky Way paint produced visible 32 px squares under
  // bloom. Dropped. The band reads entirely through its 3D band-stars (step
  // 5 below) which are point sprites — no rasterisation artefact possible.

  // 2. Nebulae — for each 3D nebula, check whether its center projects onto
  //    this face; if so, draw the radial glow at its projected position.
  //    Nebulae near face edges may appear slightly cut but the size is
  //    small enough (~180–400 px) that the cut is cosmetically acceptable.
  for (const neb of nebulae) {
    const fuv = dirToFaceUV(neb.dir)
    if (fuv.face !== face) continue
    const cx = fuv.u * size, cy = fuv.v * size
    const radius = neb.angularRadius * size
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius)
    grad.addColorStop(0.0, `rgba(${neb.color.r},${neb.color.g},${neb.color.b},0.14)`)
    grad.addColorStop(0.5, `rgba(${neb.color.r},${neb.color.g},${neb.color.b},0.05)`)
    grad.addColorStop(1.0, `rgba(${neb.color.r},${neb.color.g},${neb.color.b},0.00)`)
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, size, size)
  }

  // 3. Galaxy clusters — same logic as nebulae, draw on owning face.
  for (const gal of galaxies) {
    const fuv = dirToFaceUV(gal.dir)
    if (fuv.face !== face) continue
    const cx = fuv.u * size, cy = fuv.v * size
    drawGalaxyFromDescriptor(ctx, cx, cy, gal)
  }

  // 4. Star population — 8000 per face, generated per-face with independent
  //    random (randomness is inherently seamless; no visible edge pattern).
  const STAR_COUNT = 8000
  type Star = { x: number; y: number; bright: number; col: { r: number; g: number; b: number } }
  const stars: Star[] = []
  for (let i = 0; i < STAR_COUNT; i++) {
    const u = rng()
    const pareto = Math.min(40, Math.pow(1 - u, -1 / 1.2))
    const bright = Math.min(1.0, 0.08 + (pareto - 1) * 0.055)
    stars.push({
      x: rng() * size,
      y: rng() * size,
      bright,
      col: STAR_COLORS[Math.floor(rng() * STAR_COLORS.length)],
    })
  }

  // v7: band stars removed alongside the tile paint. The explicit Milky Way
  // band in either form produced either blocky rasterisation (tiles) or a
  // visible density streak under bloom. A plain uniform-random starfield
  // reads cleaner — the nebulae + galaxies still sell cosmic depth.
  // (bandStars param kept in signature to avoid rippling refactor; unused.)
  void bandStars

  // 6. Black hole placement (3D). Only drawn on the face that owns its
  //    direction. Horizon radius scales with the blackHolePx input.
  const bhFuv = dirToFaceUV(blackHoleDir)
  const isBHFace = bhFuv.face === face
  const BH_CX = isBHFace ? bhFuv.u * size : 0
  const BH_CY = isBHFace ? bhFuv.v * size : 0
  const BH_SIZE = blackHolePx
  const BH_HORIZON_R = BH_SIZE * 0.45

  // Pre-lens the stars near the black hole (only on its owning face).
  if (isBHFace) {
    drawLensStarDisplacement(ctx, BH_CX, BH_CY, BH_HORIZON_R, stars)
  }

  // Paint the stars. Skip any star that would fall inside the BH horizon.
  for (const s of stars) {
    if (isBHFace) {
      const dx = s.x - BH_CX, dy = s.y - BH_CY
      if (dx * dx + dy * dy < BH_HORIZON_R * BH_HORIZON_R * 1.08) continue
    }
    const r = 0.3 + s.bright * 1.7
    ctx.fillStyle = `rgba(${s.col.r},${s.col.g},${s.col.b},${s.bright})`
    ctx.beginPath()
    ctx.arc(s.x, s.y, Math.max(0.35, r * 0.5), 0, Math.PI * 2)
    ctx.fill()

    if (s.bright > 0.35) {
      const haloR = r * (1.6 + s.bright * 1.3)
      const halo = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, haloR)
      halo.addColorStop(0.0, `rgba(${s.col.r},${s.col.g},${s.col.b},${s.bright * 0.55})`)
      halo.addColorStop(0.4, `rgba(${s.col.r},${s.col.g},${s.col.b},${s.bright * 0.18})`)
      halo.addColorStop(1.0, `rgba(${s.col.r},${s.col.g},${s.col.b},0)`)
      ctx.fillStyle = halo
      ctx.beginPath()
      ctx.arc(s.x, s.y, haloR, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // 7. Black hole composite on its owning face (after stars so horizon
  //    cleanly swallows anything behind it).
  if (isBHFace) {
    drawBlackHole(ctx, BH_CX, BH_CY, BH_SIZE, rng)
  }

  return canvas
}

// Tiny wrapper for Galaxy3D descriptors → drawGalaxy signature. The only rng
// call inside drawGalaxy is the tint pick — returning colorPick pins it to a
// stable bucket (0..0.5 warm, 0.5..0.8 cool, 0.8..1 neutral).
function drawGalaxyFromDescriptor(ctx: CanvasRenderingContext2D, cx: number, cy: number, g: Galaxy3D) {
  drawGalaxy(ctx, cx, cy, g.majorR, g.axisRatio, g.angleRad, () => g.colorPick)
}

function buildCustomSkyBox(): SkyBox | null {
  try {
    const SIZE = 2048
    // Shared global rng for all 3D-positioned features. Constant seed means
    // the sky is identical every reload.
    const globalRng = mulberry32(0xc0ffee42)

    // 3D nebulae — 18 across the sphere (≈ 3 per face on average but
    // distribution is uniformly random, so it varies). Silver-violet, teal,
    // and deep rose colour mix.
    const nebulae: Nebula3D[] = []
    for (let i = 0; i < 18; i++) {
      const pick = globalRng()
      const color = pick < 0.4
        ? { r: 138, g: 80,  b: 200 }    // violet
        : pick < 0.75
        ? { r: 80,  g: 150, b: 210 }    // teal
        : { r: 200, g: 110, b: 160 }    // deep rose
      nebulae.push({
        dir: randomDir3(globalRng),
        angularRadius: 0.09 + globalRng() * 0.12,  // fraction of face width
        color,
      })
    }

    // 3D galaxy clusters — 30 across the sphere. Positions uniform on sphere;
    // size, orientation, tilt drawn from the global rng so they stay stable.
    const galaxies: Galaxy3D[] = []
    for (let i = 0; i < 30; i++) {
      galaxies.push({
        dir: randomDir3(globalRng),
        majorR: 15 + globalRng() * 25,
        axisRatio: 0.35 + globalRng() * 0.60,
        angleRad: globalRng() * Math.PI * 2,
        colorPick: globalRng(),
      })
    }

    // 3D Milky Way band stars — 5000 total across the sphere, generated only
    // within the galactic band (≤28% of π/2 off the plane). Each face pulls
    // the ones that project to it.
    const bandStars = generateBandStars3D(globalRng, 5000)

    // Black hole — fixed 3D direction (stable across reloads).
    const blackHoleDir = normalize3({ x: 0.35, y: -0.45, z: 0.82 })
    const blackHolePx = SIZE * 0.022

    const faces = [0, 1, 2, 3, 4, 5].map(f =>
      drawStarfieldFace(f, SIZE, nebulae, galaxies, bandStars, blackHoleDir, blackHolePx)
        .toDataURL('image/png'),
    )
    return new SkyBox({
      sources: {
        positiveX: faces[0],
        negativeX: faces[1],
        positiveY: faces[2],
        negativeY: faces[3],
        positiveZ: faces[4],
        negativeZ: faces[5],
      },
      show: true,
    })
  } catch (err) {
    log.debug('Custom starfield unavailable, using default:', err)
    return null
  }
}

// ─── Direction-D sprite cache (halo + elite flare) ────────────────────────
// Runtime canvas → data-URL sprites so we don't ship new image assets. Sprites
// are generated once per (color + kind) tuple and reused as billboard images.
const _spriteCache = new Map<string, string>()

function haloSprite(hex: string): string {
  const key = `halo:${hex}`
  const hit = _spriteCache.get(key)
  if (hit) return hit
  const size = 128
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  const g = ctx.createRadialGradient(size / 2, size / 2, size * 0.10, size / 2, size / 2, size * 0.48)
  // Ring shape: transparent → bright mid-band → transparent.
  g.addColorStop(0.00, 'rgba(0,0,0,0)')
  g.addColorStop(0.35, hexToRgba(hex, 0.0))
  g.addColorStop(0.55, hexToRgba(hex, 0.85))
  g.addColorStop(0.70, hexToRgba(hex, 0.45))
  g.addColorStop(1.00, hexToRgba(hex, 0.0))
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const url = canvas.toDataURL('image/png')
  _spriteCache.set(key, url)
  return url
}

// AGENTWORLD-CINEMA: glow-dot sprite (hot core + colored falloff) for agent
// markers. Cached per color; static billboards keep 5000 agents cheap.
function agentDotSprite(hex: string): string {
  const key = `dot:${hex}`
  const hit = _spriteCache.get(key)
  if (hit) return hit
  const size = 64
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  const c = size / 2
  const g = ctx.createRadialGradient(c, c, 0, c, c, c)
  g.addColorStop(0.00, 'rgba(255,255,255,0.95)')
  g.addColorStop(0.16, hexToRgba(hex, 0.95))
  g.addColorStop(0.34, hexToRgba(hex, 0.55))
  g.addColorStop(0.62, hexToRgba(hex, 0.16))
  g.addColorStop(1.00, hexToRgba(hex, 0))
  ctx.fillStyle = g
  ctx.fillRect(0, 0, size, size)
  const url = canvas.toDataURL()
  _spriteCache.set(key, url)
  return url
}

function flareSprite(hex: string): string {
  const key = `flare:${hex}`
  const hit = _spriteCache.get(key)
  if (hit) return hit
  const size = 256
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  const cx = size / 2, cy = size / 2

  // Core radial glow — bright hot center, falls off gently.
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.45)
  core.addColorStop(0.00, hexToRgba(hex, 1.0))
  core.addColorStop(0.08, hexToRgba('#ffffff', 0.95))
  core.addColorStop(0.25, hexToRgba(hex, 0.55))
  core.addColorStop(0.55, hexToRgba(hex, 0.15))
  core.addColorStop(1.00, hexToRgba(hex, 0.0))
  ctx.fillStyle = core
  ctx.fillRect(0, 0, size, size)

  // Star-cross highlights — four spokes that give the sprite that lens-flare
  // "star" quality when it passes in front of the globe.
  const drawSpoke = (angle: number, length: number, width: number) => {
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(angle)
    const grad = ctx.createLinearGradient(-length, 0, length, 0)
    grad.addColorStop(0.0, hexToRgba(hex, 0.0))
    grad.addColorStop(0.5, hexToRgba('#ffffff', 0.85))
    grad.addColorStop(1.0, hexToRgba(hex, 0.0))
    ctx.fillStyle = grad
    ctx.fillRect(-length, -width / 2, length * 2, width)
    ctx.restore()
  }
  drawSpoke(0,              size * 0.48, 5)   // horizontal
  drawSpoke(Math.PI / 2,    size * 0.48, 5)   // vertical
  drawSpoke(Math.PI / 4,    size * 0.34, 3)   // 45°
  drawSpoke(-Math.PI / 4,   size * 0.34, 3)   // 135°

  const url = canvas.toDataURL('image/png')
  _spriteCache.set(key, url)
  return url
}

function hexToRgba(hex: string, alpha: number): string {
  // Resolve var(--…) first so PALETTE entries work here.
  const raw = resolveCssVar(hex) || '#ffffff'
  // Accept #rgb, #rrggbb, #rrggbbaa — ignore alpha channel, use the arg.
  let clean = raw.replace('#', '').trim()
  if (clean.length === 3) clean = clean.split('').map(c => c + c).join('')
  if (clean.length === 8) clean = clean.slice(0, 6)
  const n = parseInt(clean, 16)
  if (!isFinite(n)) return `rgba(255,255,255,${alpha})`
  const r = (n >> 16) & 0xff, g = (n >> 8) & 0xff, b = n & 0xff
  return `rgba(${r},${g},${b},${alpha})`
}

// ─── Graticule entities (frame-coloured meridians + parallels) ────────────
const graticuleEntities: Entity[] = []

// ─── Post-processing stages (vignette, chromatic aberration) ───────────────
let vignetteStage: PostProcessStage | null = null
let chromaticAberrationStage: PostProcessStage | null = null

// ─── Entity Builders ───────────────────────────────────────────────────────

/**
 * Resolve a CSS var() string (e.g. "var(--nc-primary-bright)") to its computed
 * value (e.g. "#00e5e5"). Cesium's Color.fromCssColorString can't parse var(),
 * so every color string destined for Cesium must pass through this resolver.
 * Returns the input unchanged if it isn't a var() reference.
 */
function resolveCssVar(s: string): string {
  if (!s || typeof s !== 'string') return s
  const m = s.match(/^\s*var\((--[A-Za-z0-9-]+)\)\s*$/)
  if (!m) return s
  try {
    const resolved = getComputedStyle(document.body).getPropertyValue(m[1]).trim()
    return resolved || s
  } catch { return s }
}

function agentFrame(agent: WorldAgent): 'A' | 'B' | 'C' {
  const reg = worldRegistries.value.find(r => r.id === agent.registryId)
  return reg?.frame === 'C' ? 'C' : reg?.frame === 'B' ? 'B' : 'A'
}

function agentColor(agent: WorldAgent): string {
  // Frame C (BVT) agents render in the gold/amber family — the second
  // currency's population reads instantly against A cyan and B magenta.
  if (agentFrame(agent) === 'C') {
    if (agent.visualReputation >= 95) return '#ffd54f'
    if (agent.visualReputation >= 80) return '#ffb300'
    if (agent.visualReputation >= 60) return '#ffa000'
    return '#ffcc80'
  }
  // Frame B agents get a distinct magenta-family palette so both frames are
  // visually separable on the unified globe.
  if (agentFrame(agent) === 'B') {
    if (agent.visualReputation >= 95) return '#ff4fb4'
    if (agent.visualReputation >= 80) return '#e91e63'
    if (agent.visualReputation >= 60) return '#c2185b'
    return '#ba68c8'
  }
  if (agent.isSynced) return '#ffab40'
  if (agent.visualReputation >= 95) return '#ffd700'
  if (agent.visualReputation >= 80) return 'var(--nc-primary-bright)'
  if (agent.visualReputation >= 60) return '#29b6f6'
  return '#4fc3f7'
}

function agentPixelSize(agent: WorldAgent): number {
  if (agent.visualReputation >= 95) return 8
  if (agent.visualReputation >= 80) return 7
  if (agent.visualReputation >= 60) return 6
  if (agent.isSynced) return 5
  return 4
}

// Cycle length for elite-flare rotation — slow, tasteful. 8s feels like a
// lazy star twinkle, not a disco ball.
const FLARE_ROTATION_CYCLE_MS = 8000
function flareRotation(did: string): number {
  // Deterministic per-DID phase offset so not every flare is rotating in sync.
  let h = 0
  for (let i = 0; i < did.length; i++) h = ((h << 5) - h) + did.charCodeAt(i) | 0
  const phase = (Math.abs(h) % 1000) / 1000
  const t = ((performance.now() % FLARE_ROTATION_CYCLE_MS) / FLARE_ROTATION_CYCLE_MS + phase) % 1
  return t * Math.PI * 2
}

// 2026-05-05 audit Tier 2 #4: diff-before-rebuild instead of clear+rebuild.
// At 5000 agents, every keystroke in the search box used to rip down + rebuild
// 5000 Cesium entities. With diff, only entities for DIDs that left/entered
// the visible set get touched.
//
// `forceFull` triggers the legacy clear+rebuild path — required when an
// existing visible agent's data changed (color, size, lat/lng): diff would
// keep the stale entity. Data-mutation callers (loadData) pass true.
//
// DIFF_REBUILD const: hot kill switch — flip to false if anything looks off
// and the legacy path takes over without a code change.
const DIFF_REBUILD = true

function _addAgentEntity(v: any, agent: WorldAgent) {
  const isElite = agent.visualReputation >= 95
  const _color = Color.fromCssColorString(resolveCssVar(agentColor(agent)))  // kept for parity; dots use the hex sprite
  const size = agentPixelSize(agent)

  if (showEliteFlares.value && isElite) {
    const flareHex = agentFrame(agent) === 'B' ? '#ff4fb4' : '#ffd700'
    const flareEntity = v.entities.add({
      position: Cartesian3.fromDegrees(agent.lng, agent.lat, 0),
      billboard: {
        image: flareSprite(flareHex),
        width: 52,
        height: 52,
        color: Color.WHITE.withAlpha(0.85),
        rotation: new CallbackProperty(() => flareRotation(agent.did), false),
        scaleByDistance: new NearFarScalar(1e6, 1.2, 5e7, 0.35),
      },
      properties: {
        entityType: 'agentFlare',
        agentData: agent,
      } as any,
    })
    agentEntities.set(`${agent.did}__flare`, flareEntity)
  }

  // AGENTWORLD-CINEMA: glow-dot billboard replaces the flat point — hot core
  // sized like the old point, colored falloff around it. Same key + entityType
  // so picking, hover and DIFF_REBUILD are untouched.
  const hexCss = resolveCssVar(agentColor(agent))
  const entity = v.entities.add({
    position: Cartesian3.fromDegrees(agent.lng, agent.lat, 0),
    billboard: {
      image: agentDotSprite(hexCss),
      width: size * (isElite ? 3.8 : 3.3),
      height: size * (isElite ? 3.8 : 3.3),
      color: Color.WHITE.withAlpha(isElite ? 1.0 : 0.92),
      scaleByDistance: new NearFarScalar(1e6, 1.4, 5e7, 0.35),
    },
    properties: {
      entityType: 'agent',
      agentData: agent,
    } as any,
  })
  agentEntities.set(agent.did, entity)
}

function _removeAgentEntity(v: any, did: string) {
  const point = agentEntities.get(did)
  if (point) { v.entities.remove(point); agentEntities.delete(did) }
  const flare = agentEntities.get(`${did}__flare`)
  if (flare) { v.entities.remove(flare); agentEntities.delete(`${did}__flare`) }
}

function buildAgentEntities(forceFull = false) {
  const v = viewer.value
  if (!v) return

  if (!DIFF_REBUILD || forceFull) {
    // Legacy path: full clear + rebuild
    agentEntities.forEach(e => v.entities.remove(e))
    agentEntities.clear()
    let visible = 0
    for (const agent of worldAgents.value) {
      if (!agentVisible(agent)) continue
      visible++
      _addAgentEntity(v, agent)
    }
    visibleAgentCount.value = visible
    return
  }

  // Diff path: only touch entities for DIDs whose visibility changed.
  const nextVisible = new Set<string>()
  const visibleAgents = new Map<string, WorldAgent>()
  for (const a of worldAgents.value) {
    if (agentVisible(a)) {
      nextVisible.add(a.did)
      visibleAgents.set(a.did, a)
    }
  }
  // Remove entities for DIDs that left the visible set.
  for (const key of Array.from(agentEntities.keys())) {
    const did = key.endsWith('__flare') ? key.slice(0, -'__flare'.length) : key
    if (!nextVisible.has(did)) {
      const ent = agentEntities.get(key)
      if (ent) v.entities.remove(ent)
      agentEntities.delete(key)
    }
  }
  // Add entities for DIDs that entered the visible set.
  for (const did of nextVisible) {
    if (!agentEntities.has(did)) {
      const a = visibleAgents.get(did)
      if (a) _addAgentEntity(v, a)
    }
  }
  visibleAgentCount.value = nextVisible.size
}

// Shared pulse cycle for all registry halos — coherent, not chaotic.
// 2.4s matches the wrapped-token bridge beam so the whole planet breathes
// together at the same tempo.
const HALO_PULSE_CYCLE_MS = 2400
function haloPulse01(): number {
  return (performance.now() % HALO_PULSE_CYCLE_MS) / HALO_PULSE_CYCLE_MS
}

function buildRegistryEntities() {
  const v = viewer.value
  if (!v) return

  registryEntities.forEach(e => v.entities.remove(e))
  registryEntities.clear()

  for (const reg of worldRegistries.value) {
    // Registry Card v0.3 (2026-05-21) — operator-selected orb color overrides
    // the frame-default hopColor() palette. Sovereign-pinned mainframes get
    // their values pinned server-side via SOVEREIGN_VISUAL_PINS so operator
    // PUTs can't override them. Hex string validated server-side.
    const rcOrb = reg.visual?.orbColor
    const rcGlow = reg.visual?.orbGlowColor
    const fallbackColorStr = hopColor(reg.hopDepth, reg.frame)
    const hexColor = rcOrb || resolveCssVar(fallbackColorStr)
    const glowHex = rcGlow || hexColor
    const cesiumColor = Color.fromCssColorString(hexColor)
    const cesiumGlow = Color.fromCssColorString(glowHex)
    const isLocal = reg.hopDepth === 0
    const rcOrbSize = reg.visual?.orbSizePx ?? null

    // Halo billboard — sits underneath the point and pulses alpha + scale on
    // the shared cycle. Frame-coloured from hopColor() so Frame A reads cyan,
    // Frame B reads magenta. Local hubs (hop 0) get a bigger halo so the two
    // sovereign mainframes are immediately identifiable at any zoom.
    const haloRef = showRegistryHalos.value ? v.entities.add({
      position: Cartesian3.fromDegrees(reg.lng, reg.lat, 0),
      billboard: {
        image: haloSprite(glowHex),
        width: isLocal ? 56 : 40,
        height: isLocal ? 56 : 40,
        color: new CallbackProperty(() => {
          const t = haloPulse01()
          const base = isLocal ? 0.75 : 0.55
          const amp  = isLocal ? 0.20 : 0.15
          // AW-2/AW-4: health tints the halo (red down / amber degraded, with
          // a fast attention pulse); activity heat brightens it.
          const hs = siteHealthOf(reg.id)
          const tone = hs === 'down' ? HEALTH_RED : hs === 'degraded' ? HEALTH_AMBER : cesiumGlow
          let a = base + amp * Math.cos(t * Math.PI * 2) + 0.28 * siteHeat01(reg.id)
          if (hs && hs !== 'up') a *= 0.55 + 0.45 * Math.abs(Math.sin(performance.now() / 280))
          return tone.withAlpha(Math.min(a, 1))
        }, false),
        scale: new CallbackProperty(() => {
          const t = haloPulse01()
          const amp = isLocal ? 0.20 : 0.14
          return 1.0 + amp * Math.cos(t * Math.PI * 2) + 0.35 * siteHeat01(reg.id)
        }, false),
        scaleByDistance: new NearFarScalar(1e6, 1.4, 5e7, 0.5),
      },
      properties: {
        entityType: 'registryHalo',
        registryData: reg,
      } as any,
    }) : null
    if (haloRef) registryEntities.set(`${reg.id}__halo`, haloRef)

    const entity = v.entities.add({
      position: Cartesian3.fromDegrees(reg.lng, reg.lat, 0),
      point: {
        pixelSize: rcOrbSize ?? (isLocal ? 16 : 13),
        color: cesiumColor,
        outlineColor: cesiumGlow.withAlpha(isLocal ? 0.6 : 0.35),
        outlineWidth: isLocal ? 5 : 4,
        scaleByDistance: new NearFarScalar(1e6, 1.8, 5e7, 0.6),
      },
      properties: {
        entityType: 'registry',
        registryData: reg,
      } as any,
    })
    registryEntities.set(reg.id, entity)

    // Light pillars REMOVED (Commander order, 2026-06-12): the vertical glow
    // beams read as misplaced on the globe. Health tint + activity heat live
    // on the HALO billboard above instead (same red/amber pulse semantics).
    // The 'registryPillar' picking branches remain harmless dead paths.
  }
  // Refresh the persistent Frame-A↔Frame-B wrapped-token bridge arc any time
  // the registry set changes, so it stays aligned with the latest positions.
  renderWrappedBridgeArc()
}

// ─── Wrapped-Token Bridge (Frame A ↔ Frame B) ──────────────────────────────
// Persistent pulsating gold beam between the two sovereign mainframes — the
// wrapped-token bridge described in §4.4 of the whitepaper. The beam breathes
// with a ~2.4s glow-and-alpha cycle so it reads as a live conduit, not a
// static line. Uses PolylineGlowMaterialProperty for the thick beam effect.
const BRIDGE_PULSE_CYCLE_MS = 2400
// Bridge runs amber (PALETTE.bridge.arc) to stay distinct from federation gold
// — same family, separate concept, no longer ambiguous in screenshots.
const BRIDGE_COLOR = Color.fromCssColorString(PALETTE.bridge.arc)

function renderWrappedBridgeArc() {
  const v = viewer.value
  if (!v) return
  // §pass66 (2026-05-22) — bridge MUST always connect the two sovereign
  // mainframes (Registry-A ↔ Frame-B), regardless of which registry the user
  // is viewing AgentWorld from. The previous logic preferred `hopDepth === 0`
  // (the local registry) as the frame-A endpoint, which on a cloud-op's view
  // pointed the bridge FROM the cloud-op TO Frame-B — visually wrong + sent
  // the message "this cloud-op bridges to Frame-B" which contradicts the
  // architecture (only mainframes own a bridge). Match by canonical name
  // only; if either mainframe is missing from the topology (early boot,
  // federation lag), skip the bridge entirely until they appear.
  const _isFrameA = (r: any) =>
    r.frame === 'A' && (r.name === 'Registry-A'
      || r.name?.toLowerCase?.() === 'registry-a'
      || r.name?.toLowerCase?.().includes('registry a'))
  const _isFrameB = (r: any) =>
    r.frame === 'B' && (r.name === 'Frame-B'
      || r.name?.toLowerCase?.() === 'frame-b'
      || r.name?.toLowerCase?.().includes('frame-b')
      || r.name?.toLowerCase?.().includes('frame b'))
  const frameA = worldRegistries.value.find(_isFrameA)
  const frameB = worldRegistries.value.find(_isFrameB)
  if (!frameA || !frameB) return
  if (bridgeEntity) { v.entities.remove(bridgeEntity); bridgeEntity = null }
  const positions = computeArcPositions(frameA.lat, frameA.lng, frameB.lat, frameB.lng, 64)
  bridgeEntity = v.entities.add({
    polyline: {
      positions,
      width: 5.5,
      material: new PolylineGlowMaterialProperty({
        // Glow intensity pulses 0.20 ↔ 0.45 — thick halo when bright
        glowPower: new CallbackProperty(() => {
          const t = (performance.now() % BRIDGE_PULSE_CYCLE_MS) / BRIDGE_PULSE_CYCLE_MS
          return 0.325 + 0.125 * Math.cos(t * Math.PI * 2)
        }, false),
        taperPower: 1.0,
        // Core color alpha pulses 0.55 ↔ 0.95 in sync with glow — the whole
        // beam breathes together rather than one channel fighting the other.
        color: new CallbackProperty(() => {
          const t = (performance.now() % BRIDGE_PULSE_CYCLE_MS) / BRIDGE_PULSE_CYCLE_MS
          const a = 0.75 + 0.20 * Math.cos(t * Math.PI * 2)
          return BRIDGE_COLOR.withAlpha(a)
        }, false),
      }),
      arcType: ArcType.NONE,
    },
    properties: {
      entityType: 'bridge',
      bridgeData: { from: frameA.name, to: frameB.name, kind: 'wrapped-token-bridge' },
    } as any,
  })
}

// ─── Graticule overlay (frame-split meridians + neutral parallels) ────────
// Thin polyline grid that suggests the two sovereign frames geographically:
// meridians west of ~64.7°E (the longitude halfway between Freilassing's
// 12.98°E and Beijing's 116.4°E) carry a faint cyan, east of it a faint
// magenta. Parallels stay neutral warm-white. Solid material (not glow) so
// the graticule never competes with arcs.
const GRATICULE_SPLIT_LNG = 64.69          // halfway meridian: Frame A ← | → Frame B
const GRATICULE_FRAME_A_COLOR = '#00bcd4'  // cool cyan
const GRATICULE_FRAME_B_COLOR = '#ff3df0'  // electric magenta
const GRATICULE_NEUTRAL_COLOR = '#c9d1d9'  // warm white
const GRATICULE_ALPHA = 0.12               // very faint — never competes with arcs

function buildGraticule() {
  const v = viewer.value
  if (!v) return
  graticuleEntities.forEach(e => v.entities.remove(e))
  graticuleEntities.length = 0
  if (!showGraticule.value) {
    v.scene.requestRender()
    return
  }

  // Meridians — 12 lines, one every 30° longitude. Each is a polyline from
  // (lng, -85) to (lng, +85) with 33 segments (5° lat steps). Ending at ±85°
  // rather than ±90° avoids drawing dozens of lines converging to a single
  // point at the pole, which aliases badly.
  for (let lng = -180; lng < 180; lng += 30) {
    const positions: Cartesian3[] = []
    for (let lat = -85; lat <= 85; lat += 5) {
      positions.push(Cartesian3.fromDegrees(lng, lat, 0))
    }
    // Normalise longitude to [-180, 180] for the split comparison.
    const n = ((lng + 540) % 360) - 180
    const isFrameB = n > GRATICULE_SPLIT_LNG || n < GRATICULE_SPLIT_LNG - 180
    const col = Color.fromCssColorString(isFrameB ? GRATICULE_FRAME_B_COLOR : GRATICULE_FRAME_A_COLOR)
                     .withAlpha(GRATICULE_ALPHA)
    graticuleEntities.push(v.entities.add({
      polyline: { positions, width: 1.0, material: col, arcType: ArcType.NONE },
    }))
  }

  // Parallels — 5 latitude rings (±60°, ±30°, 0°). 65 segments each (≈5.6°
  // lng steps). Equator a touch brighter than the tropics; polar circles
  // slightly dimmer so they don't dominate.
  const PARALLELS: Array<{ lat: number; alphaMul: number }> = [
    { lat: -60, alphaMul: 0.60 },
    { lat: -30, alphaMul: 0.75 },
    { lat:   0, alphaMul: 1.00 },
    { lat:  30, alphaMul: 0.75 },
    { lat:  60, alphaMul: 0.60 },
  ]
  for (const p of PARALLELS) {
    const positions: Cartesian3[] = []
    for (let lng = -180; lng <= 180; lng += 5) {
      positions.push(Cartesian3.fromDegrees(lng, p.lat, 0))
    }
    const col = Color.fromCssColorString(GRATICULE_NEUTRAL_COLOR)
                     .withAlpha(GRATICULE_ALPHA * 0.8 * p.alphaMul)
    graticuleEntities.push(v.entities.add({
      polyline: { positions, width: 1.0, material: col, arcType: ArcType.NONE },
    }))
  }

  v.scene.requestRender()
}

// ─── Filter Logic ──────────────────────────────────────────────────────────

// Short, stable label for an agent whose card carries no name.
function shortDidLabel(did: string): string {
  const tail = String(did || '').split(':').pop() || String(did || '')
  return tail.length > 12 ? `agent ${tail.slice(0, 8)}` : `agent ${tail}`
}

function agentVisible(agent: WorldAgent): boolean {
  if (filterRegistry.value !== 'all' && agent.registryId !== filterRegistry.value) return false
  // §WORLDFIND — "Proven" filters on work actually verified by this registry's
  // guild books. The reputation tiers below stay, but they are a graph signal:
  // on an idle network EigenTrust's max-normalised vector truncates to 0 for
  // nearly everyone, so Elite/High legitimately match almost nothing. Proven is
  // the tier that answers the question a buyer actually asks.
  if (filterTier.value === 'proven' && !((agent.trackRecord?.jobs || 0) > 0)) return false
  if (filterTier.value === 'elite' && agent.visualReputation < 95) return false
  if (filterTier.value === 'high' && agent.visualReputation < 80) return false
  if (filterTier.value === 'standard' && agent.visualReputation >= 80) return false
  if (searchQuery.value) {
    const q = searchQuery.value.trim().toLowerCase()
    if (!q) return true
    const name = String(agent.name || '').toLowerCase()
    if (!name.includes(q) && !agent.did.toLowerCase().includes(q)) return false
  }
  return true
}

// §WORLDFIND — the globe holds a per-registry SAMPLE, so a purely client-side
// search can only ever find dots the client happens to have. Measured
// 2026-08-16: op-doha had 114 agents and 80 drawn, and the FX canary tx-doha
// was one of the 34 missing — typing its name returned nothing, on a system
// that knew exactly where it was. A search now asks the SERVER, which can see
// the whole population, and merges the matches onto the globe.
// Place server-search results with the SAME rules the initial load uses:
// federated agents orbit their origin registry, locals keep their own coords
// only when meaningfully away from the registry glyph, nulls orbit. Kept as one
// function so a searched-in dot can never be positioned differently from a
// sampled one (the §FANOUTFIX lesson: two copies agree until they drift).
function ingestLocationRows(rows: any[]): number {
  const regs = worldRegistries.value
  if (!regs.length) return 0
  const known = new Set(worldAgents.value.map(a => a.did))
  const merged: WorldAgent[] = []
  for (const loc of rows) {
    if (!loc || !loc.did || known.has(loc.did)) continue
    const originName: string = loc.origin_registry || ''
    const isFederated = !!originName
    const matchedReg = isFederated
      ? matchRegistry(originName, regs)
      : (regs.find(r => r.id === '__local__') || regs[0])
    if (!matchedReg) continue
    let lat: number, lng: number
    if (!isFederated && loc.lat != null && loc.lng != null
        && Math.hypot(loc.lat - matchedReg.lat, loc.lng - matchedReg.lng) > ORBIT_THRESHOLD_DEG) {
      lat = loc.lat; lng = loc.lng
    } else {
      const o = orbitalCoords(loc.did, matchedReg.lat, matchedReg.lng)
      lat = o.lat; lng = o.lng
    }
    known.add(loc.did)
    merged.push({
      did: loc.did,
      name: loc.name || shortDidLabel(loc.did),
      lat, lng,
      status: loc.status || 'active',
      reputation: Number(loc.reputation) || 0,
      visualReputation: deriveVisualReputation(0, Number(loc.reputation) || 0),
      registryId: matchedReg.id,
      registryName: matchedReg.name,
      isSynced: isFederated,
      liquidBalance: 0,
      stakedBalance: 0,
      capabilities: [],
      trackRecord: loc.track_record || null,
      matchedSearch: true,
    })
  }
  if (merged.length) worldAgents.value = [...worldAgents.value, ...merged]
  return merged.length
}

const searchServerBusy = ref(false)
const searchServerNote = ref<string>('')
let searchDebounce: ReturnType<typeof setTimeout> | null = null
const searchedTerms = new Set<string>()

async function resolveSearchOnServer(term: string) {
  const q = term.trim()
  if (q.length < 2 || searchedTerms.has(q.toLowerCase())) return
  const localHit = worldAgents.value.some(a =>
    String(a.name || '').toLowerCase().includes(q.toLowerCase())
    || a.did.toLowerCase().includes(q.toLowerCase()))
  if (localHit) return  // already on the globe; no need to widen
  searchServerBusy.value = true
  searchServerNote.value = ''
  try {
    const { data } = await apiClient.get('/agents/locations/', { params: { q } })
    searchedTerms.add(q.toLowerCase())
    const incoming: any[] = (data?.locations || []).filter((l: any) => l?.matched_search)
    // Reuse the SAME placement + registry-matching path the initial load uses,
    // so a searched-in dot is positioned exactly like any other.
    const added = ingestLocationRows(incoming)
    if (added) buildAgentEntities(true)
    const matched = Number(data?.search?.matched || 0)
    searchServerNote.value = added
      ? `found ${added} beyond the drawn sample`
      : (matched ? '' : 'no agent by that name on this registry')
  } catch {
    searchServerNote.value = 'search unavailable'
  } finally {
    searchServerBusy.value = false
  }
}

// Drain up to EMBEDDED_DRAIN_LIMIT deferred events per scheduled tick.
// Re-schedules itself until the backlog is empty OR the gate re-closes
// (new camera motion / new tile loads).
function scheduleDrain() {
  if (drainScheduler) return  // already running
  const tick = () => {
    drainScheduler = null
    if (textureGateBlocked || eventBacklog.length === 0) return
    const toProcess = eventBacklog.splice(0, EMBEDDED_DRAIN_LIMIT)
    for (const item of toProcess) {
      if (item.rawData) handleEventStoreMessage(item.rawData, 'A')
    }
    if (toProcess.length > 0) lastExternalEventTs = Date.now()
    if (eventBacklog.length > 0 && !textureGateBlocked) {
      drainScheduler = setTimeout(tick, EMBEDDED_DRAIN_INTERVAL_MS)
    }
  }
  drainScheduler = setTimeout(tick, EMBEDDED_DRAIN_INTERVAL_MS)
}

// ─── Arc System (CesiumJS polylines) ───────────────────────────────────────

function computeArcPositions(fromLat: number, fromLng: number, toLat: number, toLng: number, segments = 32): Cartesian3[] {
  const positions: Cartesian3[] = []
  const dLat = Math.abs(toLat - fromLat)
  const dLng = Math.abs(toLng - fromLng)
  const dist = Math.sqrt(dLat * dLat + dLng * dLng)
  const heightScale = Math.min(dist / 120, 1.0)
  const peakHeight = 200_000 + 800_000 * heightScale // 200km min, 1000km max

  for (let i = 0; i <= segments; i++) {
    const t = i / segments
    const lat = fromLat + (toLat - fromLat) * t
    const lng = fromLng + (toLng - fromLng) * t
    const height = peakHeight * Math.sin(t * Math.PI)
    positions.push(Cartesian3.fromDegrees(lng, lat, height))
  }
  return positions
}

// Burst-coalesce tracker: key = `lat,lng→lat,lng:type`, value = last spawn ms
const _recentArcKeys = new Map<string, number>()

function spawnArc(opts: {
  fromLat: number; fromLng: number; toLat: number; toLng: number
  color: string; type: ArcData['type']; label: string; duration: number
  fromName?: string; toName?: string; amount?: string
  // Optional per-arc emphasis multipliers. Cross-frame transfers, federation
  // links and other "important" arcs pass widthMul/glowMul > 1 to stand out.
  widthMul?: number; glowMul?: number
  // AW-1: optional second colour — the arc lerps color→colorEnd over its
  // flight. Used for FX/cross-frame transfers entering or leaving the BVT
  // frame, so the value visibly "changes currency" at altitude.
  colorEnd?: string
}) {
  const v = viewer.value
  if (!v) return

  // Burst coalescer: skip identical (from→to + type) arcs that fired within
  // the coalesce window. Prevents batched-event storms from drawing duplicate
  // arcs over the same path. Embedded uses a wider window (more aggressive
  // deduplication) because the hero globe is already fighting the main thread
  // with parent-page WS + Vue reactivity.
  const coalesceMs = props.embedded ? BURST_COALESCE_MS_EMBEDDED : BURST_COALESCE_MS_STANDALONE
  {
    const key = `${opts.fromLat.toFixed(2)},${opts.fromLng.toFixed(2)}→${opts.toLat.toFixed(2)},${opts.toLng.toFixed(2)}:${opts.type}`
    const nowMs = performance.now()
    const last = _recentArcKeys.get(key) || 0
    if (nowMs - last < coalesceMs) return
    _recentArcKeys.set(key, nowMs)
    // Prune stale entries occasionally
    if (_recentArcKeys.size > 300) {
      for (const [k, t] of _recentArcKeys) {
        if (nowMs - t > coalesceMs * 10) _recentArcKeys.delete(k)
      }
    }
  }

  // Enforce max concurrent arcs (tighter cap embedded to keep render load sane)
  const cap = props.embedded ? MAX_CONCURRENT_ARCS_EMBEDDED : MAX_CONCURRENT_ARCS_STANDALONE
  if (arcEntities.size >= cap) {
    const oldest = arcEntities.keys().next().value
    if (oldest) removeArc(oldest)
  }

  const id = Math.random().toString(36).slice(2)
  const allPositions = computeArcPositions(opts.fromLat, opts.fromLng, opts.toLat, opts.toLng)
  const startTime = performance.now()
  const duration = opts.duration || ARC_DURATION_MS
  const arcColor = Color.fromCssColorString(resolveCssVar(opts.color))
  const arcColorEnd = opts.colorEnd ? Color.fromCssColorString(resolveCssVar(opts.colorEnd)) : null

  // Animated polyline arc — CallbackProperty is cheap with requestRenderMode:true
  const polyline = v.entities.add({
    polyline: {
      positions: new CallbackProperty(() => {
        const progress = Math.min((performance.now() - startTime) / duration, 1)
        const count = Math.max(2, Math.ceil(allPositions.length * progress))
        return allPositions.slice(0, count)
      }, false),
      width: (props.embedded ? 5.0 : 3.5) * (opts.widthMul ?? 1.0),
      material: new PolylineGlowMaterialProperty({
        glowPower: (props.embedded ? 0.30 : 0.20) * (opts.glowMul ?? 1.0),
        color: new CallbackProperty(() => {
          const progress = (performance.now() - startTime) / duration
          // Currency gradient: lerp toward colorEnd over the flight (AW-1).
          const c = arcColorEnd
            ? Color.lerp(arcColor, arcColorEnd, Math.min(Math.max(progress, 0), 1), _arcLerpScratch)
            : arcColor
          if (progress > 1.3) return c.withAlpha(0)
          if (progress > 1.0) return c.withAlpha(0.7 * (1 - (progress - 1.0) / 0.3))
          if (progress < 0.08) return c.withAlpha(0.7 * (progress / 0.08))
          return c.withAlpha(0.7)
        }, false),
      }),
      arcType: ArcType.NONE,
    },
  })

  arcEntities.set(id, { polyline, startTime, duration, allPositions, arcColor, arcColorEnd, toLat: opts.toLat, toLng: opts.toLng, landed: false })
  // AW-3/AW-4: a small launch ripple at the origin + heat attribution for
  // both endpoints. Coalesced/skipped arcs never reach this point, so storms
  // can't multiply ripples or heat.
  spawnRipple(opts.fromLat, opts.fromLng, arcColor, false)
  bumpSiteHeat(opts.fromLat, opts.fromLng)
  bumpSiteHeat(opts.toLat, opts.toLng)
  activeArcs.value.push({
    id, fromLat: opts.fromLat, fromLng: opts.fromLng, toLat: opts.toLat, toLng: opts.toLng,
    color: opts.color, type: opts.type, label: opts.label, progress: 0,
    startTime, duration, fromName: opts.fromName, toName: opts.toName, amount: opts.amount,
  })
}

function removeArc(id: string) {
  const v = viewer.value
  if (!v) return
  const arc = arcEntities.get(id)
  if (arc) {
    v.entities.remove(arc.polyline)
    arcEntities.delete(id)
  }
  activeArcs.value = activeArcs.value.filter(a => a.id !== id)
}

// Scratch Color for the per-tick gradient lerp — avoids allocating in the
// material callback (called every render frame per gradient arc).
const _arcLerpScratch = new Color()

// AW-3: expanding, fading ground ring. big=landing impact, small=launch puff.
function spawnRipple(lat: number, lng: number, color: Color, big: boolean) {
  const v = viewer.value
  if (!v) return
  const cap = props.embedded ? MAX_RIPPLES_EMBEDDED : MAX_RIPPLES_STANDALONE
  if (rippleEntities.size >= cap) return
  const start = performance.now()
  const dur = big ? 1300 : 850
  const maxR = big ? 260_000 : 120_000
  const baseColor = Color.clone(color)
  const id = 'rip' + Math.random().toString(36).slice(2)
  // Memoized radius: Cesium evaluates semiMajorAxis and semiMinorAxis as two
  // separate property reads microseconds apart — if each read recomputed from
  // performance.now(), the LATER (minor) read of a growing ring would exceed
  // the earlier (major) one and Cesium throws "semiMajorAxis must be >=
  // semiMinorAxis", killing the render loop. Cache per ~half-frame so both
  // axes of one render tick always see the identical value.
  let memoT = -1e9
  let memoR = 8_000
  const radius = () => {
    const t = performance.now()
    if (t - memoT >= 8) {
      memoT = t
      const p = Math.min((t - start) / dur, 1)
      const eased = 1 - Math.pow(1 - p, 2.2) // fast start, soft finish
      memoR = Math.max(8_000, eased * maxR)
    }
    return memoR
  }
  const ent = v.entities.add({
    position: Cartesian3.fromDegrees(lng, lat, 0),
    ellipse: {
      semiMajorAxis: new CallbackProperty(radius, false),
      semiMinorAxis: new CallbackProperty(radius, false),
      height: 0,
      material: new ColorMaterialProperty(new CallbackProperty(() => {
        const p = Math.min((performance.now() - start) / dur, 1)
        return baseColor.withAlpha((big ? 0.34 : 0.20) * (1 - p))
      }, false)),
    },
  })
  rippleEntities.set(id, { ent, start, dur })
}

// Single animation loop — cleans up expired arcs, drives auto-rotate, requests render
let lastArcFrame = 0
let lastTerminatorTick = 0
function updateArcs() {
  const now = performance.now()
  // Throttle to ~30fps (every 33ms)
  if (now - lastArcFrame < 33) {
    arcAnimFrame = requestAnimationFrame(updateArcs)
    return
  }
  lastArcFrame = now

  const v = viewer.value
  if (!v) { arcAnimFrame = requestAnimationFrame(updateArcs); return }

  // Landing impacts + expired-arc cleanup. An arc "lands" the first frame its
  // progress crosses 1.0 — that's when the destination ripple fires, coloured
  // with the arc's landing colour (the gradient end for FX arcs).
  const toRemove: string[] = []
  arcEntities.forEach((arc, id) => {
    const progress = (now - arc.startTime) / arc.duration
    if (!arc.landed && progress >= 1.0) {
      arc.landed = true
      spawnRipple(arc.toLat, arc.toLng, arc.arcColorEnd ?? arc.arcColor, true)
    }
    if (progress > 1.3) toRemove.push(id)
  })
  toRemove.forEach(removeArc)

  // Expire finished ripples
  if (rippleEntities.size) {
    const ripDone: string[] = []
    rippleEntities.forEach((r, id) => { if (now - r.start > r.dur) ripDone.push(id) })
    for (const id of ripDone) {
      const r = rippleEntities.get(id)
      if (r) { v.entities.remove(r.ent); rippleEntities.delete(id) }
    }
  }

  // Auto-rotate
  if (autoRotate.value && v.scene.mode === 3) {
    v.camera.rotateRight(0.0005)
  }

  // Anything that needs a render on this tick: active arcs, auto-rotate,
  // the pulsating wrapped-token bridge beam, registry halos (CallbackProperty
  // alpha/scale), or elite-agent flares (rotating billboards).
  const needRender = arcEntities.size > 0
    || rippleEntities.size > 0
    || autoRotate.value
    || bridgeEntity
    || showRegistryHalos.value
    || showEliteFlares.value
  if (needRender) {
    // Keep the clock in sync whenever we're already rendering, so the sun
    // stays locked to wall-clock UTC under all modes.
    v.clock.currentTime = JulianDate.fromDate(new Date())
    v.scene.requestRender()
  } else if (showTerminator.value && now - lastTerminatorTick > 1000) {
    // Idle terminator tick — once per second, advance the clock and force a
    // render so the day/night line keeps moving even when everything else is
    // quiet. ~1% GPU, only fires during genuine idle.
    lastTerminatorTick = now
    v.clock.currentTime = JulianDate.fromDate(new Date())
    v.scene.requestRender()
  }

  arcAnimFrame = requestAnimationFrame(updateArcs)
}

// ─── Camera ────────────────────────────────────────────────────────────────

function flyToCoords(lat: number, lng: number) {
  const v = viewer.value
  if (!v) return
  autoRotate.value = false
  v.camera.flyTo({
    destination: Cartesian3.fromDegrees(lng, lat, 1_000),
    duration: 2.5,
    orientation: { heading: 0, pitch: CesiumMath.toRadians(-90), roll: 0 },
  })
}

// §pass62.1 (2026-05-21) — Deep-link focus support. Reads route.query.focus
// and applies it (selectedRegistry + camera fly). Called from onMounted AND
// from a watcher on route.query.focus so deep-links work both on first load
// and on subsequent hash-only navigations (Vue Router doesn't remount the
// component for hash-query changes).
function applyFocusFromQuery() {
  const focusName = (route.query.focus as string | undefined)?.trim()
  if (!focusName) return
  if (worldRegistries.value.length === 0) return  // wait for hydration
  const needle = focusName.toLowerCase()
  const target = worldRegistries.value.find(r => (r.name || '').toLowerCase() === needle)
  if (target) {
    selectedRegistry.value = target
    // Defer fly slightly so the viewer is ready (matters on first mount).
    setTimeout(() => flyToCoords(target.lat, target.lng), 500)
  }
}

function flyToAgent(agent: WorldAgent) {
  flyToCoords(agent.lat, agent.lng)
}

// ─── Feed Events ──────────────────────────────────────────────────────────

function pushFeedEvent(evt: Omit<FeedEvent, 'id' | 'time'>) {
  // §FEDEVENTS-6: frame letters are meaningless on a single-frame deployment —
  // strip the badge at this ONE choke point instead of at every call site
  // (same honesty rule as discovery's "federated = NO badge": unknown ≠ Frame A).
  const e = (!multiFrame.value && evt.frame) ? { ...evt, frame: undefined } : evt
  feedEvents.value.unshift({ ...e, id: Math.random().toString(36).slice(2), time: Date.now() })
  if (feedEvents.value.length > MAX_FEED_EVENTS) feedEvents.value.pop()
}

function formatFeedTime(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

// ─── Demo Mode ─────────────────────────────────────────────────────────────
// Tracks when the last real external event arrived. Used by the embedded
// landing-page globe to auto-toggle demo mode — demo runs when real traffic
// is quiet, and steps aside the moment real signals start flowing.
let lastExternalEventTs = 0
const DEMO_IDLE_MS = 60_000         // 1 min quiet → auto-start demo in embedded
const DEMO_IDLE_POLL_MS = 5_000     // poll interval for idle detection
let demoIdlePoll: ReturnType<typeof setInterval> | null = null

function startDemo(intervalMs: number) {
  if (demoTimer) clearInterval(demoTimer)
  demoTimer = setInterval(fireDemoBurst, intervalMs)
  demoMode.value = true
}

function stopDemo() {
  if (demoTimer) { clearInterval(demoTimer); demoTimer = null }
  demoMode.value = false
}

function toggleDemoMode() {
  if (demoMode.value) stopDemo()
  else startDemo(60)
}

function fireDemoBurst() {
  const regs = worldRegistries.value
  const agents = worldAgents.value
  if (regs.length < 1 || agents.length < 2) return
  const local = regs.find(r => r.id === '__local__')
  const peers = regs.filter(r => r.id !== '__local__')
  if (!local || peers.length === 0) return

  const types = [
    { type: 'transfer' as const,    color: PALETTE.transfer.local.arc,         label: PALETTE.transfer.local.label },
    { type: 'transfer' as const,    color: PALETTE.transfer.crossRegistry.arc, label: PALETTE.transfer.crossRegistry.label },
    { type: 'transfer' as const,    color: PALETTE.transfer.crossFrame.arc,    label: PALETTE.transfer.crossFrame.label },
    { type: 'federation' as const,  color: PALETTE.federation.arc,             label: 'Federation Sync' },
    { type: 'onboarding' as const,  color: PALETTE.onboarding.arc,             label: 'Agent Onboarded' },
    { type: 'staking' as const,     color: PALETTE.staking.arc,                label: 'Units Locked' },
    { type: 'contract' as const,    color: PALETTE.contract.arc,               label: 'Contract Signed' },
    { type: 'attestation' as const, color: PALETTE.attestation.arc,            label: 'Attestation' },
  ]
  const pick = (arr: any[]) => arr[Math.floor(Math.random() * arr.length)]
  const randAgent = () => agents[Math.floor(Math.random() * agents.length)]

  const count = 2 + Math.floor(Math.random() * 4)
  for (let i = 0; i < count; i++) {
    const t = pick(types)
    let from: { lat: number; lng: number; name: string }
    let to: { lat: number; lng: number; name: string }
    if (Math.random() < 0.7) {
      const peer = pick(peers)
      if (Math.random() < 0.5) {
        from = { lat: peer.lat, lng: peer.lng, name: peer.name }; to = randAgent()
      } else {
        from = randAgent(); to = { lat: peer.lat, lng: peer.lng, name: peer.name }
      }
    } else {
      from = randAgent(); to = randAgent()
      if (from === to) to = randAgent()
    }
    const amt = (Math.random() * 500 + 1).toFixed(1)
    spawnArc({
      fromLat: from.lat, fromLng: from.lng, toLat: to.lat, toLng: to.lng,
      color: t.color, type: t.type, label: `${t.label}: ${amt} ${localCurrency.value}`,
      duration: ARC_DURATION_MS * (0.8 + Math.random() * 0.8),
      fromName: from.name, toName: to.name, amount: amt,
    })
    pushFeedEvent({ type: t.type, title: t.label, sub: `${from.name} → ${to.name} (${amt} ${localCurrency.value})`, color: feedColorOf(t.type) })
  }
}

// ─── Topology Merge ───────────────────────────────────────────────────────

async function mergeTopologyRegistries(existingRegs: WorldRegistry[], localName: string) {
  await vrRefresh()  // populate V-relative hops before stamping registry tooltips [Commander 2026-06-07]
  const existingDomains = new Set<string>()
  const existingNames = new Set<string>()
  existingDomains.add('__local__')
  // Add local domain to prevent duplicate topology node for self
  existingDomains.add(domainKey(window.location.origin))
  existingNames.add(localName.toLowerCase().trim())
  for (const reg of existingRegs) {
    if (reg.publicUrl) existingDomains.add(domainKey(reg.publicUrl))
    if (reg.name) existingNames.add(reg.name.toLowerCase().trim())
  }

  const newRegs: WorldRegistry[] = []

  for (const [dk, topoReg] of topology.registries) {
    if (existingDomains.has(dk)) continue
    // 2026-05-05 fix: also dedup by name. The /public/topology endpoint
    // returns Frame B operators with `.frame-b.theprotocol.cloud` URLs
    // (hopDepth=2 via relay), while /agents/locations/trusted-registries
    // returns the SAME operators with `.op.theprotocol.cloud:8443` URLs
    // (peer_registries.base_url). Different hostnames → different domainKeys
    // → both pass the domain dedup → 4 ghost markers on the embedded globe.
    // Name-based dedup catches them.
    const topoNameLc = (topoReg.name || '').toLowerCase().trim()
    if (topoNameLc && existingNames.has(topoNameLc)) {
      // 2026-05-05 fix #2: topology's publicUrl uses the operator's
      // home-frame domain (e.g. .frame-b.theprotocol.cloud for Frame B ops),
      // while trustedRegs's URL uses the requesting frame's view
      // (e.g. .op.theprotocol.cloud for Frame B ops as seen from Frame A).
      // frameOfDomain reads the topology URL more accurately for cross-frame
      // operators. Upgrade the existing reg's frame attribution if topology
      // says 'B' so Frame B operators (and their agents) get purple coloring.
      const topoFrame = frameOfDomain(topoReg.publicUrl || '', topoReg.name)
      if (topoFrame === 'B') {
        const existing = existingRegs.find(
          (r) => (r.name || '').toLowerCase().trim() === topoNameLc,
        )
        if (existing && existing.frame !== 'B') {
          existing.frame = 'B'
        }
      }
      continue
    }
    // Unified globe: include cross-frame topology nodes too.

    const id = `topo-${dk}`
    let coords: { lat: number; lng: number } | null = null

    // §2026-06-14 — AUTHORITATIVE: the registry CARD's operator geo, threaded into
    // the /public/topology slice (operator.latitude/longitude). The card is the
    // single source of truth — no cross-origin /agents/locations/operator probe
    // (that SNI-fell-through to the genesis frame for non-dotted hosts → WRONG
    // coords, and flooded the console with 502s on stopped operators).
    const cLat = (topoReg as any).latitude, cLng = (topoReg as any).longitude
    if (cLat != null && cLng != null) coords = { lat: Number(cLat), lng: Number(cLng) }

    if (!coords) {
      const named = getRegistryCoords(topoReg.name)
      if (named.lat !== REGISTRY_COORDS.default.lat || named.lng !== REGISTRY_COORDS.default.lng) {
        coords = named
      } else {
        coords = deterministicGeoCoords(dk)
      }
    }

    // Count agents whose origin fuzzy-matches this registry
    const tempReg = { id, name: topoReg.name, lat: 0, lng: 0, agentCount: 0, status: 'active', hopDepth: topoReg.hopDepth } as WorldRegistry
    const topoAgentCount = worldAgents.value.filter(a =>
      matchRegistry(a.registryName, [tempReg])?.id === id
    ).length

    // Registry Card v0.3 (2026-05-21) — surface peer's visual + fees slice
    // into WorldRegistry so per-orb color + hover icon + cost-display widget
    // can render without an extra fetch.
    const rcVisual = (topoReg as any).visual
    const rcFees = (topoReg as any).fees_summary
    newRegs.push({
      id, name: topoReg.name, displayName: (topoReg as any).display_name || null,
      lat: coords.lat, lng: coords.lng,
      agentCount: topoAgentCount, status: 'active',
      hopDepth: vrHopByName.value.get(normName(topoReg.name)) ?? topoReg.hopDepth,
      frame: frameOfDomain(topoReg.publicUrl || dk, topoReg.name),
      publicUrl: topoReg.publicUrl,
      description: `Discovered via topology — ${topoReg.hopDepth}-hop relay`,
      protocolVersion: '1.0',
      authMethods: ['mtls', 'jwt_svid'],
      visual: rcVisual ? {
        iconUrl: rcVisual.icon_url,
        orbColor: rcVisual.orb_color,
        orbGlowColor: rcVisual.orb_glow_color,
        orbPulseSpeedHz: rcVisual.orb_pulse_speed_hz,
        orbSizePx: rcVisual.orb_size_px,
        haloEnabled: rcVisual.halo_enabled,
        haloThickness: rcVisual.halo_thickness,
        theme: rcVisual.theme,
        sovereignVariant: rcVisual.sovereign_variant,
        flareEncirclementVariant: rcVisual.flare_encirclement_variant,
        flareEncirclementOverlay: rcVisual.flare_encirclement_overlay,
        flareCornerVariant: rcVisual.flare_corner_variant,
      } : null,
      fees: rcFees ? {
        intraRegistry: rcFees.intra_registry,
        crossRegistry: rcFees.cross_registry,
        hostingEnabled: rcFees.hosting_enabled,
        hostingRate: rcFees.hosting_rate,
        settlementCurrency: rcFees.settlement_currency,
      } : null,
      cardEtag: (topoReg as any).card_etag || null,
      cardSignatureVerified: !!(topoReg as any).card_signature_verified,
      exchange: (topoReg as any).exchange || null,
    })
  }

  if (newRegs.length > 0) {
    worldRegistries.value = [...existingRegs, ...newRegs]
    seedTopologyArcs()
  }

  // Registry Card v0.3 (2026-05-21) — hydrate visual + fees on EXISTING regs.
  // Match by name OR by domain='__local__' for the local registry. The local
  // entry's topology name is 'Local Registry' (server convention) while the
  // worldRegistries local entry uses settings.REGISTRY_NAME from /federation/info
  // ('Registry-A' etc.) — name match fails for local, so we need a domain
  // fallback. Idempotent — re-runs leave the data identical.
  const topoByNameLc = new Map<string, any>()
  let topoLocal: any = null
  for (const [dk, t] of topology.registries) {
    const nm = (t.name || '').toLowerCase().trim()
    if (nm) topoByNameLc.set(nm, t)
    if (dk === '__local__') topoLocal = t
  }
  // 2026-05-30 — also index peers that arrived via tier buckets (frames/
  // discovered/cloud_operators) but are ABSENT from the flat BFS `registries`
  // list, so their RC visual (encirclement) still attaches. Flat-list entries
  // win (already set above); this only fills gaps. Enrich-only — the loop below
  // only hydrates EXISTING worldRegistries, never creates orbs → strict no-op on
  // prod (every peer is already in the flat list there). Fixes sandbox frame/
  // discovered peers on non-dotted internal hosts (e.g. nginx-test-b).
  for (const [nm, t] of ((topology as any).peersByName || new Map())) {
    if (nm && !topoByNameLc.has(nm)) topoByNameLc.set(nm, t)
  }
  let rcHydrated = 0
  for (const reg of worldRegistries.value) {
    // Local reg uses __local__ topo entry regardless of name mismatch.
    const t = (reg.id === '__local__' || reg.hopDepth === 0)
      ? (topoLocal || topoByNameLc.get((reg.name || '').toLowerCase().trim()))
      : topoByNameLc.get((reg.name || '').toLowerCase().trim())
    if (!t) continue
    const rcVisual = (t as any).visual
    const rcFees = (t as any).fees_summary
    // Always overwrite (topology is source of truth post-load); count if it
    // changes a previously-null orb so we know to rebuild Cesium entities.
    if (rcVisual) {
      const before = reg.visual?.orbColor
      reg.visual = {
        iconUrl: rcVisual.icon_url,
        orbColor: rcVisual.orb_color,
        orbGlowColor: rcVisual.orb_glow_color,
        orbPulseSpeedHz: rcVisual.orb_pulse_speed_hz,
        orbSizePx: rcVisual.orb_size_px,
        haloEnabled: rcVisual.halo_enabled,
        haloThickness: rcVisual.halo_thickness,
        theme: rcVisual.theme,
        sovereignVariant: rcVisual.sovereign_variant,
        flareEncirclementVariant: rcVisual.flare_encirclement_variant,
        flareEncirclementOverlay: rcVisual.flare_encirclement_overlay,
        flareCornerVariant: rcVisual.flare_corner_variant,
      }
      if (before !== rcVisual.orb_color) rcHydrated++
    }
    if (rcFees) {
      reg.fees = {
        intraRegistry: rcFees.intra_registry,
        crossRegistry: rcFees.cross_registry,
        hostingEnabled: rcFees.hosting_enabled,
        hostingRate: rcFees.hosting_rate,
        settlementCurrency: rcFees.settlement_currency,
      }
    }
    if ((t as any).card_etag) reg.cardEtag = (t as any).card_etag
    if (typeof (t as any).card_signature_verified === 'boolean') reg.cardSignatureVerified = (t as any).card_signature_verified
    // §2026-06-14 — topology slice carries the card display_name; overwrite so the
    // hover label reflects the rebranded name (falls back to slug client-side).
    if ((t as any).display_name) reg.displayName = (t as any).display_name
    // §2026-06-14 — AGORA venue capability → hover badge (topology is source of truth).
    if ((t as any).exchange) reg.exchange = (t as any).exchange
  }
  // §2026-06-07 — override EVERY registry's hop with the V-relative tree depth (same
  // tree the Galactic Map uses). Registries here come from 3 build paths (topology
  // merge / direct peers / trusted-registries), each stamping a different hop; this
  // single pass makes the on-hover label consistent + correct from ANY viewer.
  for (const r of worldRegistries.value) {
    if (r.id === '__local__') { r.hopDepth = 0; continue }
    const h = vrHopByName.value.get(normName(r.name))
    if (typeof h === 'number') r.hopDepth = h
  }
  if (rcHydrated > 0 || newRegs.length > 0) buildRegistryEntities()

  // Re-place agents whose registryId is still '__local__' but origin matches a registry
  const allRegs = worldRegistries.value
  let relocated = 0
  for (const agent of worldAgents.value) {
    if (!agent.isSynced || agent.registryId !== '__local__') continue
    const matched = matchRegistry(agent.registryName, allRegs)
    if (matched) {
      agent.registryId = matched.id
      const newCoords = orbitalCoords(agent.did, matched.lat, matched.lng)
      agent.lat = newCoords.lat
      agent.lng = newCoords.lng
      relocated++
    }
  }
  if (relocated > 0) {
    for (const reg of allRegs) reg.agentCount = worldAgents.value.filter(a => a.registryId === reg.id).length
    // §GLOBEPOP: re-apply TRUE populations after the relocation recount.
    for (const reg of allRegs) {
      const pop = populationIndex.lookup(reg.name, (reg as any).trustDomain)
      if (pop) reg.agentCount = Math.max(reg.agentCount, pop.total)
    }
    // Force full rebuild — agent positions changed, diff path would keep stale entities.
    buildAgentEntities(true)
  }

  // Unified globe: no cross-frame purge. Agents whose home registry lives on
  // the other sovereign frame are shown, tagged by their registry's frame.
}

// ─── Data Loading ──────────────────────────────────────────────────────────

async function loadData() {
  isLoading.value = true
  loadError.value = null
  try {
    const host = window.location.hostname
    const [devRes, cardsRes, infoRes, esRes, locRes, operatorRes, trustedRes] = await Promise.all([
      props.embedded ? Promise.resolve({ data: [] }) : apiClient.get('/developers/me/agents').catch(() => ({ data: [] })),
      apiClient.get('/agent-cards/', { params: { include_federated: true, limit: 200 } }).catch(() => ({ data: { items: [] } })),
      apiClient.get('/federation/info').catch(() => ({ data: { registry_name: 'Registry A' } })),
      (authStore.isAdmin
        ? apiClient.get('/admin/eventstore-balances').then(r => r)
        : Promise.resolve({ data: { agents: [] } })
      ).then(r => (r as any).data ?? r).catch(() => ({ agents: [] })),
      apiClient.get('/agents/locations/').catch(() => ({ data: { locations: [] } })),
      apiClient.get('/agents/locations/operator').catch(() => ({ data: { lat: null, lng: null, label: null } })),
      // Backend BFS: all federated registries (server-side, cached 5min, no timeout issues)
      apiClient.get('/agents/locations/trusted-registries').catch(() => ({ data: { registries: [] } })),
    ])

    await federationStore.fetchRegistries()

    const eventCountMap = new Map<string, number>()
    for (const row of ((esRes as any).agents || [])) {
      if (row.agent_did && row.event_count != null) eventCountMap.set(row.agent_did, Number(row.event_count))
    }

    const realCoords: Record<string, { lat: number; lng: number }> = {}
    const locData = (locRes as any)?.data?.locations || (locRes as any)?.locations || []
    populationIndex = buildPopulationIndex((locRes as any)?.data?.registries)
    for (const loc of locData) {
      if (loc.did && loc.lat != null && loc.lng != null) realCoords[loc.did] = { lat: loc.lat, lng: loc.lng }
    }

    const opData = (operatorRes as any)?.data || operatorRes || {}
    const operatorLat = opData.lat
    const operatorLng = opData.lng

    const localName: string = infoRes.data?.registry_name || 'Registry A'
    const regs: WorldRegistry[] = []
    const lc = (operatorLat != null && operatorLng != null)
      ? { lat: operatorLat, lng: operatorLng }
      : getRegistryCoords(localName)
    const isLocalDev = ['localhost', '127.0.0.1'].includes(host)
    const localPublicUrl = isLocalDev ? `http://${host}:8000` : window.location.origin
    const localInfo = infoRes.data || {}
    regs.push({
      id: '__local__', name: localName, lat: lc.lat, lng: lc.lng, agentCount: 0, status: 'active',
      hopDepth: 0,
      frame: frameOfDomain(localPublicUrl, localName),
      publicUrl: localPublicUrl,
      description: `TheProtocol ${localName} — sovereign registry node`,
      protocolVersion: localInfo.federation_protocol_version || '1.0',
      authMethods: (localInfo.supported_auth_methods || ['mtls', 'jwt_svid']).filter((m: string) => m !== 'bearer_token'),
    })

    const PEER_API_MAP: Record<string, string> = {
      'registry-b': isLocalDev ? `http://${host}:8001` : 'https://registry-b.theprotocol.cloud',
      'registry b': isLocalDev ? `http://${host}:8001` : 'https://registry-b.theprotocol.cloud',
      'registry-a': isLocalDev ? `http://${host}:8000` : 'https://registry.theprotocol.cloud',
      'registry a': isLocalDev ? `http://${host}:8000` : 'https://registry.theprotocol.cloud',
      // Frame B sovereign mainframe — distinct from the legacy "registry-b"
      // federated peer above. Real public URL is frame-b.theprotocol.cloud.
      'frame-b':    isLocalDev ? `http://${host}:8100` : 'https://frame-b.theprotocol.cloud',
      'frame b':    isLocalDev ? `http://${host}:8100` : 'https://frame-b.theprotocol.cloud',
    }
    const PEER_PUBLIC_URL: Record<string, string> = {
      'registry-b': 'https://registry-b.theprotocol.cloud',
      'registry b': 'https://registry-b.theprotocol.cloud',
      'registry-a': 'https://registry.theprotocol.cloud',
      'registry a': 'https://registry.theprotocol.cloud',
      'frame-b':    'https://frame-b.theprotocol.cloud',
      'frame b':    'https://frame-b.theprotocol.cloud',
    }
    const getPublicUrl = (baseUrl: string): string => {
      try {
        const u = new URL(baseUrl)
        if (!u.hostname.includes('.')) return ''
        return `${u.protocol}//${u.hostname}`
      } catch { return '' }
    }
    // ─── Frame identity detection (before peer HTTP requests) ──────────────
    isFrameB = localName.toLowerCase().includes('frame b') ||
               localName.toLowerCase().includes('frame-b') ||
               window.location.hostname.includes('frame-b')
    // Operator heuristic: single peer = our mainframe; detect frame from its domain
    if (!isFrameB && (federationStore.registries || []).length === 1) {
      const mfDomain = domainKey((federationStore.registries[0] as any).base_url || '')
      isFrameB = mfDomain.includes('frame-b')
    }

    // Unified globe: include cross-frame peers too (previously filtered). They'll
    // be tagged with frame='B' and rendered with a distinct color so the viewer
    // can see both sovereign frames in one view.
    const localPeers = (federationStore.registries || [])

    // Pre-index the backend BFS result so direct-peer coords can fall back to
    // it when /operator fetch is unavailable (embedded mode, CORS, transient).
    // Without this, hop-1 peers like Frame-B and op-washington got hash-scattered
    // coords while hop-2+ peers got correct coords — an asymmetry visible as
    // Frame-B landing in a random ocean while Tokyo/London/etc. were fine.
    const _trustedRegsEarly: any[] = (trustedRes as any)?.data?.registries || []
    const trustedByName = new Map<string, { lat: number; lng: number }>()
    for (const tr of _trustedRegsEarly) {
      const n = String(tr.name || '').toLowerCase().trim()
      if (n && tr.lat != null && tr.lng != null) {
        trustedByName.set(n, { lat: tr.lat, lng: tr.lng })
      }
    }

    // In embedded (landing page demo) mode, skip the per-peer cross-origin
    // fetches entirely — they fail 502/CORS and block the page.
    const peerDataPromises = props.embedded
      ? localPeers.map(() => Promise.resolve({ loc: null, info: null }))
      : localPeers.map(async (peer: any) => {
          const peerKey = (peer.name || '').toLowerCase().replace(/\s+/g, '-')
          const peerBase = PEER_API_MAP[peerKey] || PEER_API_MAP[(peer.name || '').toLowerCase()] || getPublicUrl((peer as any).base_url || '')
          if (!peerBase) return { loc: null, info: null }
          // §2026-06-14 — DROP the per-peer cross-origin probes. In the browser these
          // are CORS-blocked (always resolve null → they NEVER provided coords, only
          // flooded the console). The registry CARD's operator geo — server-resolved
          // into trusted-registries + threaded into the /public/topology slice — is the
          // AUTHORITATIVE source (see the topology-coord block above). peerOpLoc=null
          // → placement falls through to the (card-sourced) trustedByName lookup.
          void peerBase
          return { loc: null, info: null }
        })
    const peerData = await Promise.all(peerDataPromises)

    for (let i = 0; i < localPeers.length; i++) {
      const peer = localPeers[i]
      const { loc: peerOpLoc, info: peerInfo } = peerData[i]
      // Coord source priority:
      //   1. Peer's own /operator response (freshest, but fails in embedded mode
      //      and can be blocked by transient CORS / browser cache)
      //   2. Backend BFS trusted-registries lookup (server-side, reliable,
      //      always has coords for every reachable peer)
      //   3. Hardcoded named map (only 6 entries, legacy)
      //   4. Domain-hash scatter (never stack on default)
      let pc: { lat: number; lng: number }
      const peerNameKey = String(peer.name || '').toLowerCase().trim()
      const trustedCoord = trustedByName.get(peerNameKey)
      if (peerOpLoc?.lat != null && peerOpLoc?.lng != null) {
        pc = { lat: peerOpLoc.lat, lng: peerOpLoc.lng }
      } else if (trustedCoord) {
        pc = trustedCoord
      } else {
        const named = getRegistryCoords((peer.name || '').toLowerCase())
        if (named.lat !== REGISTRY_COORDS.default.lat || named.lng !== REGISTRY_COORDS.default.lng) {
          pc = named
        } else {
          pc = deterministicGeoCoords(domainKey((peer as any).base_url || peer.name || ''))
        }
      }
      const peerKey = (peer.name || '').toLowerCase().replace(/\s+/g, '-')
      const peerBaseUrl = (peer as any).base_url || (peer as any).url || ''
      const peerPub = PEER_PUBLIC_URL[peerKey] || PEER_PUBLIC_URL[(peer.name || '').toLowerCase()] || getPublicUrl(peerBaseUrl) || ''
      regs.push({
        id: String((peer as any).id || peer.name),
        name: peer.name || 'Unknown', lat: pc.lat, lng: pc.lng,
        agentCount: (peer as any).agents || 0, status: (peer as any).status || 'active',
        hopDepth: 1,
        frame: frameOfDomain(peerPub || peerBaseUrl, peer.name),
        publicUrl: peerPub,
        description: `TheProtocol ${peer.name} — sovereign registry node`,
        protocolVersion: peerInfo?.federation_protocol_version || '1.0',
        authMethods: (peerInfo?.supported_auth_methods || ['mtls', 'jwt_svid']).filter((m: string) => m !== 'bearer_token'),
        lastSyncedAt: (peer as any).last_polled_at || undefined,
      })
    }

    // Seed hop 2+ registries from backend BFS (server-side, cached, reliable).
    // Reuses the same list we already extracted above for the localPeers fallback.
    const trustedRegs = _trustedRegsEarly
    const existingNames = new Set(regs.map(r => (r.name || '').toLowerCase().trim()))
    existingNames.add(localName.toLowerCase().trim())
    const localDomain = domainKey(localPublicUrl)
    for (const tr of trustedRegs) {
      const trName = (tr.name || '').trim()
      if (!trName || existingNames.has(trName.toLowerCase())) continue
      if ((tr.hop || 0) <= 0) continue  // Skip env-var fallbacks / self-references
      // Skip self-reference via BFS (local registry discovered under different name)
      const trDomain = domainKey(tr.url || tr.public_url || '')
      if (trDomain && trDomain === localDomain) continue
      // Cross-frame registries ARE included now — tagged with frame='B' so the
      // Cesium renderer can style them distinctly.
      existingNames.add(trName.toLowerCase())
      const pub = tr.public_url || getPublicUrl(tr.url || '')
      // Prefer server-provided coords (backend BFS has already probed /agents/locations/operator).
      // If absent, try the hardcoded named map for known registries, else scatter by domain
      // hash so unknown operators don't all pile onto the mainframe default.
      const hasServerCoords = tr.lat != null && tr.lng != null
      let coords: { lat: number; lng: number }
      if (hasServerCoords) {
        coords = { lat: tr.lat, lng: tr.lng }
      } else {
        const named = getRegistryCoords(trName.toLowerCase())
        if (named.lat !== REGISTRY_COORDS.default.lat || named.lng !== REGISTRY_COORDS.default.lng) {
          coords = named
        } else {
          coords = deterministicGeoCoords(domainKey(pub || tr.url || trName))
        }
      }
      regs.push({
        id: `trusted-${trName.toLowerCase().replace(/\s+/g, '-')}`,
        name: trName, lat: coords.lat, lng: coords.lng,
        agentCount: 0, status: 'active', hopDepth: tr.hop || 2,
        frame: frameOfDomain(pub || tr.url || '', trName),
        publicUrl: pub,
        description: `Discovered via backend topology — ${tr.hop || '?'}-hop relay`,
        protocolVersion: '1.0',
        authMethods: ['mtls', 'jwt_svid'],
      })
    }

    worldRegistries.value = regs

    // Resolve operator locations for backend-seeded registries (non-blocking)
    const defaultCoords = getRegistryCoords('__nonexistent__')
    const needsLocation = regs.filter(r =>
      r.id.startsWith('trusted-') && r.publicUrl &&
      r.lat === defaultCoords.lat && r.lng === defaultCoords.lng
    )
    // Skip the trusted-registry coord resolution in embedded mode — fallback
    // coords from getRegistryCoords() are good enough for the demo globe.
    if (needsLocation.length > 0 && !props.embedded) {
      Promise.allSettled(needsLocation.map(async (reg) => {
        try {
          const resp = await fetch(`${reg.publicUrl}/api/v1/agents/locations/operator`, {
            signal: AbortSignal.timeout(4000),
            cache: 'no-store',
          })
          if (resp.ok) {
            const data = await resp.json()
            if (data.lat != null && data.lng != null) {
              reg.lat = data.lat
              reg.lng = data.lng
            }
          }
        } catch { /* use default coords */ }
      })).then(() => {
        buildRegistryEntities()
        // 2026-05-05 audit Tier 2: build regById Map once, lookup is O(1).
        // Was O(agents × registries) = ~500M cmps at 500k × 1k.
        const regByIdResolve = new Map(regs.map(r => [r.id, r]))
        for (const agent of worldAgents.value) {
          const reg = regByIdResolve.get(agent.registryId)
          if (reg && reg.id.startsWith('trusted-')) {
            const nc = orbitalCoords(agent.did, reg.lat, reg.lng)
            agent.lat = nc.lat
            agent.lng = nc.lng
          }
        }
        // Force full rebuild — agent positions resolved, diff would keep stale.
        buildAgentEntities(true)
      })
    }

    // Client-side BFS still runs as supplement (discovers edges for arc rendering, deduped)
    discoverTopology(federationStore.registries, localName, 6).then(() => {
      mergeTopologyRegistries(regs, localName)
      // Unified globe: no cross-frame purge here. Registries from the other
      // frame stay visible, tagged with frame='B' and styled distinctly.
      // Also redraw the wrapped-token bridge arc now that both frames' glyphs exist.
      renderWrappedBridgeArc()
    })

    const seenDids = new Set<string>()
    const seenNames = new Set<string>()
    const agents: WorldAgent[] = []

    const devAgents: any[] = Array.isArray(devRes.data) ? devRes.data : (devRes.data?.agents || [])
    for (const a of devAgents) {
      if (!a.did || !a.name) continue
      if (seenDids.has(a.did)) continue
      seenDids.add(a.did)
      seenNames.add((a.name || '').toLowerCase().trim())
      const coords = resolveCoords(a.did, regs[0].lat, regs[0].lng, realCoords)
      agents.push({
        did: a.did, name: a.name, lat: coords.lat, lng: coords.lng,
        status: a.status || 'active', reputation: Number(a.reputation_score) || 0,
        visualReputation: deriveVisualReputation(eventCountMap.get(a.did) || 0, Number(a.reputation_score) || 0),
        registryId: '__local__', registryName: localName, isSynced: false,
        liquidBalance: Number(a.liquid_balance) || 0, stakedBalance: Number(a.staked_balance) || 0,
        capabilities: a.capabilities || [],
      })
    }

    // Primary agent-dot source: /agents/locations/ (public, deduped per DID at
    // the DB layer via DISTINCT ON). Runs in BOTH embedded and standalone modes.
    //
    // Positioning rules:
    //   • Federated agents (origin_registry set): ALWAYS orbit the matched
    //     registry. The backend's lat/lng for federated agents is the
    //     operator's landmark — using it raw stacks every agent on a single
    //     pixel. Orbital gives each DID a deterministic ~3.5° offset.
    //   • Local agents (no origin): use the agent's own coords ONLY if they
    //     are >ORBIT_THRESHOLD_DEG from the local registry center. Coords
    //     inside the threshold are treated as "effectively at the registry"
    //     and replaced with orbital jitter (avoids stacks on registry glyph).
    //   • Null coords: orbital fallback.
    //
    // Agents whose origin is a legacy/defunct registry (not in the current
    // graph — e.g. pre-rename "Turbo Tokyo" or torn-down "cloud-op-alpha-b")
    // are skipped to keep the globe consistent with the live topology.
    for (const loc of locData) {
      // §WORLDFIND — a missing card name is not a reason to erase the agent
      // from the world. Measured 2026-08-16: 4 agents in the live payload carry
      // name: null (one of them with reputation 100) and were silently dropped,
      // so they could never be seen OR searched. Fall back to a short DID.
      if (!loc || !loc.did) continue
      if (!loc.name) loc.name = shortDidLabel(loc.did)
      if (seenDids.has(loc.did)) continue
      const originName: string = (loc as any).origin_registry || ''
      const isFederated = !!originName
      let matchedReg: WorldRegistry | null = null
      if (!isFederated) {
        matchedReg = regs.find(r => r.id === '__local__') || regs[0]
      } else {
        matchedReg = matchRegistry(originName, regs)
      }
      if (!matchedReg) continue  // legacy/defunct registry — skip
      seenDids.add(loc.did)
      seenNames.add(String(loc.name).toLowerCase().trim())
      let lat: number
      let lng: number
      if (isFederated) {
        const o = orbitalCoords(loc.did, matchedReg.lat, matchedReg.lng)
        lat = o.lat; lng = o.lng
      } else if (loc.lat != null && loc.lng != null) {
        const d = Math.hypot(loc.lat - matchedReg.lat, loc.lng - matchedReg.lng)
        if (d > ORBIT_THRESHOLD_DEG) {
          lat = loc.lat; lng = loc.lng
        } else {
          const o = orbitalCoords(loc.did, matchedReg.lat, matchedReg.lng)
          lat = o.lat; lng = o.lng
        }
      } else {
        const o = orbitalCoords(loc.did, matchedReg.lat, matchedReg.lng)
        lat = o.lat; lng = o.lng
      }
      agents.push({
        did: loc.did,
        name: loc.name,
        lat,
        lng,
        status: loc.status || 'active',
        reputation: Number((loc as any).reputation) || 0,
        visualReputation: deriveVisualReputation(eventCountMap.get(loc.did) || 0, Number((loc as any).reputation) || 0),
        registryId: matchedReg.id,
        registryName: matchedReg.name,
        isSynced: isFederated,
        liquidBalance: 0,
        stakedBalance: 0,
        capabilities: [],
        trackRecord: (loc as any).track_record || null,
        matchedSearch: !!(loc as any).matched_search,
      })
    }

    // Secondary: /agent-cards/?include_federated=true — useful for cards that
    // lack a DID (legacy records) or that were missed by the locations path.
    // Dedup against everything already added via seenDids + seenNames.
    const allCards: any[] = (cardsRes.data as any)?.items || []
    for (const card of allCards) {
      const originName: string = card.origin_registry_name || ''
      const originLower = originName.toLowerCase().trim()
      const localLower = localName.toLowerCase().trim()
      const isLocalCard = !originName || originLower === 'local' || originLower === localLower
      if (isLocalCard) continue
      const cardName = (card.name || '').toLowerCase().trim()
      if (seenNames.has(cardName)) continue
      seenNames.add(cardName)
      const realDid = KNOWN_DIDS[cardName] || `card:${card.id}`
      if (seenDids.has(realDid)) continue
      seenDids.add(realDid)
      const matchedReg = matchRegistry(originName, regs)
      if (!matchedReg) continue  // legacy/unknown origin — orbital fallback handled above already
      const registryId = matchedReg.id
      const baseCoords = { lat: matchedReg.lat, lng: matchedReg.lng }
      const coords = orbitalCoords(realDid, baseCoords.lat, baseCoords.lng)
      agents.push({
        did: realDid, name: card.name || 'Unknown', lat: coords.lat, lng: coords.lng,
        status: card.is_active ? 'active' : 'inactive', reputation: 0,
        visualReputation: deriveVisualReputation(eventCountMap.get(realDid) || 0, 0),
        registryId, registryName: originName, isSynced: true,
        liquidBalance: 0, stakedBalance: 0, capabilities: card.capabilities || [],
      })
    }

    // ── Frame B agent backfill ─────────────────────────────────────────────
    // The /agents/locations/ above only returns agents indexed by Frame A.
    // Frame B has its own sovereign EventStore + agent registry on
    // frame-b.theprotocol.cloud — without this fetch, every Frame B agent
    // referenced in a TokensTransferred / TokensStaked / ContractCreated
    // event would fall through findAgent() to randAgent() and the arc
    // would terminate at a random Frame A agent. Skipped in embedded mode
    // (cross-origin fetch from LandingPage hero is blocked).
    const frameBReg = regs.find(r => r.frame === 'B' && r.id !== '__local__')
    // Direct cross-frame browser fetch only in real prod, where the peer's
    // public hostname resolves + serves CORS. On sandbox (isLocalDev) the
    // PEER_API_MAP points at prod/retired ports (:8100/:8001) which are
    // cross-origin to the sandbox port → CORS-blocked + redundant (the backend
    // /agent-cards/?include_federated already returns Frame B agents). Skip it
    // to avoid console-spam + CrowdSec probing noise.
    if (!props.embedded && !isLocalDev && frameBReg) {
      try {
        // 2026-05-05 audit Tier 3.2: use the registry's resolved publicUrl
        // instead of hardcoded frame-b.theprotocol.cloud. Otherwise breaks
        // for Frame B operators deployed at non-default domains.
        const fbBase = (frameBReg.publicUrl || 'https://frame-b.theprotocol.cloud').replace(/\/+$/, '')
        const fbResp = await fetch(`${fbBase}/api/v1/agents/locations/`, { cache: 'no-store' })
        if (fbResp.ok) {
          const fbJson = await fbResp.json()
          const fbLocs: any[] = fbJson?.locations || []
          let added = 0
          for (const loc of fbLocs) {
            if (!loc?.did || !loc?.name) continue
            if (seenDids.has(loc.did)) continue
            const nameLower = String(loc.name).toLowerCase().trim()
            if (seenNames.has(nameLower)) continue
            seenDids.add(loc.did)
            seenNames.add(nameLower)
            // Frame B locations all carry the same operator landmark coord
            // (Beijing today) — orbital scatter so they don't stack on one pixel.
            const o = orbitalCoords(loc.did, frameBReg.lat, frameBReg.lng)
            agents.push({
              did: loc.did,
              name: loc.name,
              lat: o.lat,
              lng: o.lng,
              status: loc.status || 'active',
              reputation: Number((loc as any).reputation) || 0,
              visualReputation: deriveVisualReputation(eventCountMap.get(loc.did) || 0, Number((loc as any).reputation) || 0),
              registryId: frameBReg.id,
              registryName: frameBReg.name,
              isSynced: true,
              liquidBalance: 0,
              stakedBalance: 0,
              capabilities: [],
            })
            added++
          }
          if (added > 0) {
            pushFeedEvent({ type: 'system', title: 'Frame B agents loaded', sub: `${added} agents from frame-b.theprotocol.cloud`, color: PALETTE.system.feed, frame: 'B' })
          }
        }
      } catch { /* CORS / network — degrades gracefully, FB events still arc to FB registry centroid */ }
    }

    // 2026-05-05 follow-up: when eventCountMap is empty (anonymous viewers
    // — e.g. embedded LandingPage hero), the deriveVisualReputation
    // fallback uses reputation_score / 10. With prod's bottom-heavy
    // distribution (1 agent at 1000, 1 at 921, then a long tail) only one
    // agent crosses the 95 threshold → barely visible elite flare.
    // Rank-based override: in fallback mode, lift the top reputation-
    // scored agents to elite tier so the hero globe shows ~5 visible
    // flares regardless of absolute scale.
    if (eventCountMap.size === 0 && agents.length > 0) {
      const ranked = agents
        .filter(a => (a.reputation || 0) > 0)
        .sort((a, b) => (b.reputation || 0) - (a.reputation || 0))
      const eliteN = Math.min(5, ranked.length)
      const highN = Math.min(15, ranked.length)
      for (let i = 0; i < ranked.length; i++) {
        if (i < eliteN) ranked[i].visualReputation = 95 + (eliteN - i)  // 96..100
        else if (i < highN) ranked[i].visualReputation = 80 + Math.floor(((highN - i) / (highN - eliteN)) * 14)  // 80..94
        // The rest keep their /10 fallback values (already set during push).
      }
    }

    // Unified globe: keep all agents regardless of frame. Agents whose home
    // registry lives on Frame B get their frame tag via the registry they
    // orbit, and will be colored accordingly downstream.
    // 2026-05-05 audit Tier 2: single-pass count instead of N filters.
    const agentCountByReg = new Map<string, number>()
    for (const a of agents) {
      agentCountByReg.set(a.registryId, (agentCountByReg.get(a.registryId) ?? 0) + 1)
    }
    for (const reg of regs) reg.agentCount = agentCountByReg.get(reg.id) ?? 0
    // §GLOBEPOP: label TRUE populations — the drawn points are a fair sample.
    for (const reg of regs) {
      const pop = populationIndex.lookup(reg.name, (reg as any).trustDomain)
      if (pop) reg.agentCount = Math.max(reg.agentCount, pop.total)
    }
    worldAgents.value = agents

    didToAgentMap.clear()
    for (const a of agents) {
      if (a.did.startsWith('did:cos:') || a.did.startsWith('did:theprotocol:')) didToAgentMap.set(a.did, a)
    }
    const nameToAgent = new Map<string, WorldAgent>()
    for (const a of agents) nameToAgent.set(a.name.toLowerCase().trim(), a)
    // Skip the cross-origin per-peer agent-location fetch loop in embedded
    // (landing page demo) mode — local agents are enough for the hero visual.
    // 2026-05-05 audit Tier 3.3: don't break after first peer success.
    // Each peer surfaces its own slice of agents; breaking left federated
    // agents on the remaining peers unmapped → arcs fell through to randAgent.
    if (!props.embedded && !isLocalDev) for (const [, peerBase] of Object.entries(PEER_API_MAP)) {
      try {
        const r = await fetch(`${peerBase}/api/v1/agents/locations/`)
        if (!r.ok) continue
        const peerLocs = await r.json()
        for (const loc of (peerLocs.locations || [])) {
          if (!loc.did || !loc.name) continue
          const agent = nameToAgent.get(loc.name.toLowerCase().trim())
          if (agent && !agent.did.startsWith('did:cos:') && !agent.did.startsWith('did:theprotocol:')) {
            didToAgentMap.set(loc.did, agent)
          }
        }
      } catch { /* ignore */ }
    }

    pushFeedEvent({ type: 'system', title: 'AgentWorld online', sub: `${agents.length} agents · ${regs.length} registries`, color: PALETTE.system.feed })
    isLoading.value = false
  } catch (err: any) {
    loadError.value = err.message || 'Failed to load network data'
    isLoading.value = false
  }
}

// ─── EventStore WebSocket ──────────────────────────────────────────────────

function deepFind(obj: any, key: string, depth = 0): any {
  if (!obj || typeof obj !== 'object' || depth > 4) return undefined
  if (obj[key] !== undefined && obj[key] !== null && obj[key] !== '') return obj[key]
  for (const k of Object.keys(obj)) {
    if (typeof obj[k] === 'object') {
      const found = deepFind(obj[k], key, depth + 1)
      if (found !== undefined) return found
    }
  }
  return undefined
}

const didToAgentMap = new Map<string, WorldAgent>()

// 2026-05-05 audit Tier 2: Map-first, find-fallback. The previous order
// did O(n) linear scan before O(1) Map lookup — at 100k agents × 100 ev/s
// on the WS hot path that was ~10M comparisons/sec. Map is built in
// loadData() and updated on cross-frame agent inserts.
function findAgent(did: string): WorldAgent | undefined {
  if (!did) return undefined
  return didToAgentMap.get(did) ?? worldAgents.value.find(a => a.did === did)
}

const ES_ARC_TYPE: Record<string, ArcData['type']> = {
  TokensTransferred: 'transfer', TokensIssued: 'transfer',
  CrossRegistryTransferCompleted: 'transfer', TreasuryFundingGranted: 'transfer',
  TransactionFeeCollected: 'transfer', AgentCreated: 'onboarding',
  AgentOnboarded: 'onboarding', DisputeFiled: 'dispute',
  DisputeResolved: 'dispute', DisputeSlash: 'dispute',
  EvidenceSubmitted: 'dispute', DisputeCompensationMinted: 'dispute',
  DisputeCompensationRequest: 'dispute', EnforcementActionCreated: 'dispute',
  ContractCreated: 'contract', ContractAccepted: 'contract',
  ContractWorkSubmitted: 'contract', ContractCompleted: 'contract',
  VoteCast: 'governance', ProposalCreated: 'governance', ProposalTallied: 'governance',
  TokensStaked: 'staking', TokensUnstaked: 'staking', StakeForceUnstaked: 'staking',
  RewardsDistributed: 'staking', DailyDistributionCompleted: 'staking',
  RewardsAutoCompounded: 'staking', AttestationSubmitted: 'attestation',
  ReputationChanged: 'attestation',
}

const ES_FEED_TITLE: Record<string, string> = {
  TokensTransferred: 'Transfer', TokensIssued: 'Units Issued',
  CrossRegistryTransferCompleted: 'Cross-Registry Transfer', TreasuryFundingGranted: 'Treasury Funding',
  TransactionFeeCollected: 'Fee Collected', TokensStaked: 'Locked', TokensUnstaked: 'Unlocked',
  StakeForceUnstaked: 'Force Unlocked', RewardsDistributed: 'Payouts',
  DailyDistributionCompleted: 'Daily Payouts', RewardsAutoCompounded: 'Payouts Relocked',
  AgentCreated: 'Agent Created', AgentOnboarded: 'Agent Onboarded', AgentUpdated: 'Agent Updated',
  DisputeFiled: 'Dispute Filed', DisputeResolved: 'Dispute Resolved', DisputeSlash: 'Slash Executed',
  EvidenceSubmitted: 'Evidence Submitted', DisputeCompensationMinted: 'Compensation Paid',
  DisputeCompensationRequest: 'Compensation Claimed', EnforcementActionCreated: 'Enforcement Action',
  ContractCreated: 'Contract Created', ContractAccepted: 'Contract Accepted',
  ContractWorkSubmitted: 'Work Submitted', ContractCompleted: 'Contract Completed',
  VoteCast: 'Vote Cast', ProposalCreated: 'Proposal Created', ProposalTallied: 'Proposal Tallied',
  AttestationSubmitted: 'ZKP Attested', ReputationChanged: 'Reputation Updated',
}

const ES_FEED_TYPE: Record<string, FeedEvent['type']> = {
  TokensTransferred: 'transfer', TokensIssued: 'transfer',
  CrossRegistryTransferCompleted: 'transfer', TreasuryFundingGranted: 'transfer',
  TransactionFeeCollected: 'system', TokensStaked: 'staking', TokensUnstaked: 'staking',
  StakeForceUnstaked: 'staking', RewardsDistributed: 'staking',
  DailyDistributionCompleted: 'staking', RewardsAutoCompounded: 'staking',
  AgentCreated: 'onboarding', AgentOnboarded: 'onboarding', AgentUpdated: 'onboarding',
  DisputeFiled: 'dispute', DisputeResolved: 'dispute', DisputeSlash: 'dispute',
  EvidenceSubmitted: 'dispute', DisputeCompensationMinted: 'dispute',
  DisputeCompensationRequest: 'dispute', EnforcementActionCreated: 'dispute',
  ContractCreated: 'system', ContractAccepted: 'system',
  ContractWorkSubmitted: 'system', ContractCompleted: 'system',
  VoteCast: 'governance', ProposalCreated: 'governance', ProposalTallied: 'governance',
  AttestationSubmitted: 'attestation', ReputationChanged: 'system',
}

function handleEventStoreMessage(raw: any, frame: 'A' | 'B' | 'C' = 'A') {
  if (typeof raw.data === 'string') { try { raw.data = JSON.parse(raw.data) } catch { /* expected */ } }
  if (raw.data && typeof raw.data.data === 'string') { try { raw.data.data = JSON.parse(raw.data.data) } catch { /* expected */ } }
  // W4 phase 1: a new ledger name (UnitsTransferred ...) is drawn, titled and filtered as its old one
  const event_type: string = liveOld(deepFind(raw, 'event_type') || '')
  if (!event_type) return

  const evtData = raw.event?.data || raw.data?.data || raw.data || {}
  const aggregate_id: string = deepFind(raw, 'aggregate_id') || ''
  const source: string = (deepFind(raw, 'source_service') || '').replace('teg-layer', 'teg').replace('registry', 'reg')
  const amount: string = String(deepFind(evtData, 'amount') || deepFind(evtData, 'net_amount') || '')
  // The event's amount is denominated in the currency of the stream it arrived
  // on (data-driven per frame: each slot is a manifest frame, its currency the manifest's — slotFrame).
  const CUR = curOf(frame)

  const title = ES_FEED_TITLE[event_type] || event_type
  const feedType = ES_FEED_TYPE[event_type] || 'system'
  let sub = aggregate_id ? (aggregate_id.length > 20 ? aggregate_id.slice(0, 16) + '…' : aggregate_id) : source

  const senderDid: string = deepFind(evtData, 'from') || deepFind(evtData, 'sender_did') || deepFind(evtData, 'from_did') || ''
  const receiverDid: string = deepFind(evtData, 'to') || deepFind(evtData, 'receiver_did') || deepFind(evtData, 'to_did') || ''
  const senderAgent = findAgent(senderDid)
  const receiverAgent = findAgent(receiverDid)
  if (senderAgent && receiverAgent) {
    sub = `${senderAgent.name.split(' ')[0]} → ${receiverAgent.name.split(' ')[0]}`
    if (amount) sub += ` · ${amount} ${CUR}`
  } else if (amount) {
    sub = `${amount} ${CUR}`
  }

  pushFeedEvent({ type: feedType, title, sub, color: feedColorOf(feedType), frame })

  const arcType = ES_ARC_TYPE[event_type]
  if (!arcType || !showArcs.value) return

  const categoryEnabled: Record<string, boolean> = {
    transfer: arcFilterTransfer.value, federation: arcFilterFederation.value,
    onboarding: arcFilterOnboarding.value, dispute: arcFilterDispute.value,
    contract: arcFilterContract.value, governance: arcFilterGovernance.value,
    staking: arcFilterStaking.value, attestation: arcFilterAttestation.value,
  }
  if (!categoryEnabled[arcType]) return

  const local = worldRegistries.value.find(r => r.id === '__local__')
  const agents = worldAgents.value
  const randAgent = () => agents[Math.floor(Math.random() * agents.length)]

  // Transfer events — three-way variant (local / cross-registry / cross-frame).
  // Cross-frame is now its own first-class case with a distinct colour, longer
  // duration, thicker stroke and brighter glow so Frame A ↔ Frame B value
  // movement is impossible to miss on the globe.
  if (event_type === 'TokensTransferred' || event_type === 'CrossRegistryTransferCompleted') {
    const from = senderAgent || findAgent(aggregate_id)
    const to = receiverAgent

    const localReg = worldRegistries.value.find(r => r.id === '__local__')
    const localFrame = localReg?.frame ?? 'A'

    if (from && to) {
      const variant = transferVariant(from.registryId, to.registryId)
      const cfg = PALETTE.transfer[variant]
      const emp = TRANSFER_EMPHASIS[variant]
      const fFrame = worldRegistries.value.find(r => r.id === from.registryId)?.frame ?? localFrame
      const tFrame = worldRegistries.value.find(r => r.id === to.registryId)?.frame ?? localFrame
      const cols = transferArcColors(variant, fFrame, tFrame, frame)
      spawnArc({ fromLat: from.lat, fromLng: from.lng, toLat: to.lat, toLng: to.lng,
        color: cols.color, colorEnd: cols.colorEnd, type: 'transfer',
        label: `${cfg.label}${amount ? ': ' + amount + ' ' + CUR : ''}`,
        duration: ARC_DURATION_MS * emp.durationMul,
        widthMul: emp.widthMul, glowMul: emp.glowMul,
        fromName: from.name, toName: to.name, amount })
    } else if (from && !to && senderDid && receiverDid) {
      // We know the sender locally; the receiver lives on a remote registry.
      const remotePeer = worldRegistries.value.find(r => r.id !== '__local__')
      if (remotePeer) {
        const fromFrame = worldRegistries.value.find(r => r.id === from.registryId)?.frame ?? localFrame
        const variant: TransferVariant = remotePeer.frame !== fromFrame ? 'crossFrame' : 'crossRegistry'
        const cfg = PALETTE.transfer[variant]
        const emp = TRANSFER_EMPHASIS[variant]
        const cols = transferArcColors(variant, fromFrame, remotePeer.frame, frame)
        spawnArc({ fromLat: from.lat, fromLng: from.lng, toLat: remotePeer.lat, toLng: remotePeer.lng,
          color: cols.color, colorEnd: cols.colorEnd, type: 'transfer',
          label: `${cfg.label}${amount ? ': ' + amount + ' ' + CUR : ''}`,
          duration: ARC_DURATION_MS * emp.durationMul,
          widthMul: emp.widthMul, glowMul: emp.glowMul,
          fromName: from.name, toName: remotePeer.name, amount })
      }
    } else if (!from && to && senderDid) {
      // Mirror image: we know the receiver, sender is remote.
      const remotePeer = worldRegistries.value.find(r => r.id !== '__local__')
      if (remotePeer) {
        const toFrame = worldRegistries.value.find(r => r.id === to.registryId)?.frame ?? localFrame
        const variant: TransferVariant = remotePeer.frame !== toFrame ? 'crossFrame' : 'crossRegistry'
        const cfg = PALETTE.transfer[variant]
        const emp = TRANSFER_EMPHASIS[variant]
        const cols = transferArcColors(variant, remotePeer.frame, toFrame, frame)
        spawnArc({ fromLat: remotePeer.lat, fromLng: remotePeer.lng, toLat: to.lat, toLng: to.lng,
          color: cols.color, colorEnd: cols.colorEnd, type: 'transfer',
          label: `${cfg.label}${amount ? ': ' + amount + ' ' + CUR : ''}`,
          duration: ARC_DURATION_MS * emp.durationMul,
          widthMul: emp.widthMul, glowMul: emp.glowMul,
          fromName: remotePeer.name, toName: to.name, amount })
      }
    }
    return
  }

  if (event_type === 'TransactionFeeCollected' && local && agents.length > 0) {
    const payerDid = deepFind(evtData, 'agent_did') || deepFind(evtData, 'payer_did') || aggregate_id
    const payer = findAgent(payerDid) || randAgent()
    if (payer) spawnArc({ fromLat: payer.lat, fromLng: payer.lng, toLat: local.lat, toLng: local.lng,
      color: PALETTE.fee.arc, type: 'transfer', label: `Fee${amount ? ': ' + amount + ' ' + CUR : ''}`,
      duration: ARC_DURATION_MS * 0.45, fromName: payer.name, toName: 'Fee Pool', amount })
    return
  }

  if ((event_type === 'TreasuryFundingGranted' || event_type === 'TokensIssued') && local) {
    const targetDid = deepFind(evtData, 'target_agent_did') || deepFind(evtData, 'agent_did') || deepFind(evtData, 'recipient_did') || aggregate_id
    const target = findAgent(targetDid) || randAgent()
    if (target) {
      const label = event_type === 'TokensIssued'
        ? `Issued → ${target.name.split(' ')[0]}${amount ? ': ' + amount + ' ' + CUR : ''}`
        : `Treasury → ${target.name.split(' ')[0]}${amount ? ': ' + amount + ' ' + CUR : ''}`
      // Mint events get the distinct mint colour; treasury disbursements stay cyan.
      const arc = event_type === 'TokensIssued' ? PALETTE.mint.arc : PALETTE.treasury.arc
      spawnArc({ fromLat: local.lat, fromLng: local.lng, toLat: target.lat, toLng: target.lng,
        color: arc, type: 'transfer', label, duration: ARC_DURATION_MS * 0.8,
        fromName: 'Treasury', toName: target.name, amount })
    }
    return
  }

  if ((event_type === 'AgentCreated' || event_type === 'AgentOnboarded') && local) {
    const agentDid = deepFind(evtData, 'agent_did') || aggregate_id
    const target = findAgent(agentDid) || randAgent()
    if (target) spawnArc({ fromLat: local.lat, fromLng: local.lng, toLat: target.lat, toLng: target.lng,
      color: PALETTE.onboarding.arc, type: 'onboarding', label: 'Agent Onboarded',
      duration: ARC_DURATION_MS * 0.9, fromName: local.name, toName: target.name })
    return
  }

  if (['DisputeFiled', 'DisputeResolved', 'DisputeSlash', 'EvidenceSubmitted',
       'DisputeCompensationMinted', 'DisputeCompensationRequest', 'EnforcementActionCreated'].includes(event_type) && agents.length >= 2) {
    const claimantDid = deepFind(evtData, 'claimant_did') || deepFind(evtData, 'complainant_did') || deepFind(evtData, 'submitter_did') || ''
    const defendantDid = deepFind(evtData, 'defendant_did') || deepFind(evtData, 'defendant_agent_did') || deepFind(evtData, 'subject_did') || ''
    const agentA = findAgent(claimantDid) || randAgent()
    const agentB = findAgent(defendantDid) || agents.find(a => a.did !== agentA?.did)
    if (agentA && agentB) {
      const labels: Record<string, string> = { DisputeFiled: 'Dispute Filed', DisputeResolved: 'Dispute Resolved', DisputeSlash: 'Slash Executed',
        EvidenceSubmitted: 'Evidence Submitted', DisputeCompensationMinted: 'Compensation Paid',
        DisputeCompensationRequest: 'Compensation Claimed', EnforcementActionCreated: 'Enforcement Action' }
      spawnArc({ fromLat: agentA.lat, fromLng: agentA.lng, toLat: agentB.lat, toLng: agentB.lng,
        color: PALETTE.dispute.arc, type: 'dispute', label: labels[event_type] || 'Dispute',
        duration: ARC_DURATION_MS * 1.3, fromName: agentA.name, toName: agentB.name })
    }
    return
  }

  if (['ContractCreated', 'ContractCompleted', 'ContractAccepted', 'ContractWorkSubmitted'].includes(event_type) && agents.length >= 2) {
    const contractorDid = deepFind(evtData, 'contractor_did') || deepFind(evtData, 'client_did') || ''
    const providerDid = deepFind(evtData, 'provider_did') || deepFind(evtData, 'agent_did') || ''
    const agentA = findAgent(contractorDid) || randAgent()
    const agentB = findAgent(providerDid) || agents.find(x => x.did !== agentA?.did)
    if (agentA && agentB) {
      const labels: Record<string, string> = { ContractCreated: 'Contract Created', ContractAccepted: 'Contract Accepted',
        ContractWorkSubmitted: 'Work Submitted', ContractCompleted: 'Contract Completed' }
      spawnArc({ fromLat: agentA.lat, fromLng: agentA.lng, toLat: agentB.lat, toLng: agentB.lng,
        color: PALETTE.contract.arc, type: 'contract', label: labels[event_type] || 'Contract',
        duration: ARC_DURATION_MS * 1.2, fromName: agentA.name, toName: agentB.name })
    }
    return
  }

  if (['VoteCast', 'ProposalCreated', 'ProposalTallied'].includes(event_type) && local && agents.length > 0) {
    const voterDid = deepFind(evtData, 'voter_did') || deepFind(evtData, 'agent_did') || aggregate_id
    const voter = findAgent(voterDid) || randAgent()
    if (voter) spawnArc({ fromLat: voter.lat, fromLng: voter.lng, toLat: local.lat, toLng: local.lng,
      color: PALETTE.governance.arc, type: 'governance',
      label: event_type === 'VoteCast' ? 'Vote Cast' : (event_type === 'ProposalTallied' ? 'Proposal Tallied' : 'Proposal Created'),
      duration: ARC_DURATION_MS, fromName: voter.name, toName: local.name })
    return
  }

  if (['TokensStaked', 'TokensUnstaked', 'StakeForceUnstaked'].includes(event_type) && local && agents.length > 0) {
    const stakerDid = deepFind(evtData, 'agent_did') || deepFind(evtData, 'staker_did') || aggregate_id
    const staker = findAgent(stakerDid) || randAgent()
    const isStaking = event_type === 'TokensStaked'
    if (staker) spawnArc({
      fromLat: isStaking ? staker.lat : local.lat, fromLng: isStaking ? staker.lng : local.lng,
      toLat: isStaking ? local.lat : staker.lat, toLng: isStaking ? local.lng : staker.lng,
      color: PALETTE.staking.arc, type: 'staking',
      label: event_type === 'TokensStaked' ? `Locked${amount ? ' ' + amount + ' ' + localCurrency.value : ''}` :
             event_type === 'StakeForceUnstaked' ? 'Force Unlocked' : `Unlocked${amount ? ' ' + amount + ' ' + localCurrency.value : ''}`,
      duration: ARC_DURATION_MS * 0.8, fromName: isStaking ? staker.name : local.name,
      toName: isStaking ? local.name : staker.name, amount })
    return
  }

  if (event_type === 'RewardsDistributed' && local && agents.length > 0) {
    const recipientDid = deepFind(evtData, 'agent_did') || deepFind(evtData, 'recipient_did') || aggregate_id
    const recipient = findAgent(recipientDid) || randAgent()
    if (recipient) spawnArc({ fromLat: local.lat, fromLng: local.lng, toLat: recipient.lat, toLng: recipient.lng,
      color: PALETTE.staking.arc, type: 'staking', label: `Payout${amount ? ': ' + amount + ' ' + CUR : ''}`,
      duration: ARC_DURATION_MS * 0.7, fromName: 'Payout Pool', toName: recipient.name, amount })
    return
  }

  if (['DailyDistributionCompleted', 'RewardsAutoCompounded'].includes(event_type) && local && agents.length > 0) {
    const recipientDid = deepFind(evtData, 'agent_did') || deepFind(evtData, 'recipient_did') || aggregate_id
    const recipient = findAgent(recipientDid) || randAgent()
    if (recipient) spawnArc({ fromLat: local.lat, fromLng: local.lng, toLat: recipient.lat, toLng: recipient.lng,
      color: PALETTE.staking.arc, type: 'staking',
      label: event_type === 'RewardsAutoCompounded' ? `Relocked${amount ? ': ' + amount + ' ' + CUR : ''}` : `Daily Payouts${amount ? ': ' + amount + ' ' + CUR : ''}`,
      duration: ARC_DURATION_MS * 0.65, fromName: 'Payout Pool', toName: recipient.name, amount })
    return
  }

  if (event_type === 'AttestationSubmitted' && local && agents.length > 0) {
    const attesterDid = deepFind(evtData, 'agent_did') || aggregate_id
    const attester = findAgent(attesterDid) || randAgent()
    if (attester) spawnArc({ fromLat: attester.lat, fromLng: attester.lng, toLat: local.lat, toLng: local.lng,
      color: PALETTE.attestation.arc, type: 'attestation', label: 'ZKP Attestation',
      duration: ARC_DURATION_MS * 0.75, fromName: attester.name, toName: local.name })
    return
  }

  if (event_type === 'ReputationChanged' && agents.length >= 2) {
    const targetDid = deepFind(evtData, 'agent_did') || aggregate_id
    const target = findAgent(targetDid) || randAgent()
    const peer = agents.find(a => a.did !== target?.did) || randAgent()
    if (target && peer) spawnArc({ fromLat: peer.lat, fromLng: peer.lng, toLat: target.lat, toLng: target.lng,
      color: PALETTE.attestation.arc, type: 'attestation', label: 'EigenTrust Update',
      duration: ARC_DURATION_MS * 0.35, fromName: peer.name, toName: target.name })
  }
}

function connectEventStoreWs() {
  if (esWs && (esWs.readyState === WebSocket.OPEN || esWs.readyState === WebSocket.CONNECTING)) return
  const host = window.location.hostname
  const isLocalDev = ['localhost', '127.0.0.1'].includes(host)
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = slotFrame('A') ? esSocketUrl(slotFrame('A')!.key) : esSocketUrl('')
  try {
    esWs = new WebSocket(url)
    esWs.onopen = () => {
      esWsConnected.value = true
      esWsReconnectDelay = 1500
      esWs!.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' }))
      // §FEDEVENTS-6: /ws/events is Frame A on multi-frame vhosts but the node's
      // OWN stream on a single-frame deployment — title accordingly.
      pushFeedEvent({
        type: 'system',
        title: multiFrame.value ? 'Frame A EventStore connected' : `${framesApi.localRegistryName.value || 'Local'} EventStore connected`,
        sub: 'Live event stream active', color: PALETTE.system.feed, frame: 'A',
      })
    }
    esWs.onmessage = (msg) => {
      try { const data = JSON.parse(msg.data); if (data.type === 'event') handleEventStoreMessage(data, 'A') } catch { /* expected */ }
    }
    esWs.onclose = () => {
      esWsConnected.value = false
      esWsReconnectTimer = setTimeout(() => { esWsReconnectDelay = Math.min(esWsReconnectDelay * 1.6, 30000); connectEventStoreWs() }, esWsReconnectDelay)
    }
    esWs.onerror = () => { esWsConnected.value = false }
  } catch { esWsConnected.value = false }
}

// Frame B's sovereign EventStore — proxied at /ws/events-b in production
// (nginx → http://127.0.0.1:8201/ws/events). Without this subscription,
// Frame B → Frame B local transfers never reach the globe.
function connectEventStoreWsB() {
  if (!multiFrame.value) return   // §FEDEVENTS-6: no /ws/events-b on a single-frame vhost — a dial would reconnect-loop forever
  if (esWsB && (esWsB.readyState === WebSocket.OPEN || esWsB.readyState === WebSocket.CONNECTING)) return
  const host = window.location.hostname
  const isLocalDev = ['localhost', '127.0.0.1'].includes(host)
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const fB = slotFrame('B')
  if (!fB) return                 // §FEFRAME W2: the manifest names no second frame
  const url = esSocketUrl(fB.key)
  try {
    esWsB = new WebSocket(url)
    esWsB.onopen = () => {
      esWsBConnected.value = true
      esWsBReconnectDelay = 1500
      esWsB!.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' }))
      pushFeedEvent({ type: 'system', title: 'Frame B EventStore connected', sub: 'Sovereign frame stream active', color: PALETTE.system.feed, frame: 'B' })
    }
    esWsB.onmessage = (msg) => {
      try { const data = JSON.parse(msg.data); if (data.type === 'event') handleEventStoreMessage(data, 'B') } catch { /* expected */ }
    }
    esWsB.onclose = () => {
      esWsBConnected.value = false
      esWsBReconnectTimer = setTimeout(() => { esWsBReconnectDelay = Math.min(esWsBReconnectDelay * 1.6, 30000); connectEventStoreWsB() }, esWsBReconnectDelay)
    }
    esWsB.onerror = () => { esWsBConnected.value = false }
  } catch { esWsBConnected.value = false }
}

// Frame C's sovereign (BVT) EventStore — proxied at /ws/events-c in production
// (every SPA vhost carries the three /ws locations since V-1r). Without this
// subscription the entire BVT economy — frame-c plus the four ME cloud-ops —
// never reaches the globe.
function connectEventStoreWsC() {
  if (!multiFrame.value) return   // §FEDEVENTS-6: see connectEventStoreWsB
  if (esWsC && (esWsC.readyState === WebSocket.OPEN || esWsC.readyState === WebSocket.CONNECTING)) return
  const host = window.location.hostname
  const isLocalDev = ['localhost', '127.0.0.1'].includes(host)
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const fC = slotFrame('C')
  if (!fC) return                 // §FEFRAME W2: the manifest names no third frame
  const url = esSocketUrl(fC.key)
  try {
    esWsC = new WebSocket(url)
    esWsC.onopen = () => {
      esWsCConnected.value = true
      esWsCReconnectDelay = 1500
      esWsC!.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' }))
      pushFeedEvent({ type: 'system', title: 'Frame C EventStore connected', sub: 'BVT economy stream active', color: PALETTE.system.feed, frame: 'C' })
    }
    esWsC.onmessage = (msg) => {
      try { const data = JSON.parse(msg.data); if (data.type === 'event') handleEventStoreMessage(data, 'C') } catch { /* expected */ }
    }
    esWsC.onclose = () => {
      esWsCConnected.value = false
      esWsCReconnectTimer = setTimeout(() => { esWsCReconnectDelay = Math.min(esWsCReconnectDelay * 1.6, 30000); connectEventStoreWsC() }, esWsCReconnectDelay)
    }
    esWsC.onerror = () => { esWsCConnected.value = false }
  } catch { esWsCConnected.value = false }
}

function disconnectEventStoreWs() {
  if (esWsReconnectTimer) { clearTimeout(esWsReconnectTimer); esWsReconnectTimer = null }
  if (esWs) { esWs.onclose = null; esWs.close(); esWs = null }
  esWsConnected.value = false
}

function disconnectEventStoreWsC() {
  if (esWsCReconnectTimer) { clearTimeout(esWsCReconnectTimer); esWsCReconnectTimer = null }
  if (esWsC) { esWsC.onclose = null; esWsC.close(); esWsC = null }
  esWsCConnected.value = false
}

function disconnectEventStoreWsB() {
  if (esWsBReconnectTimer) { clearTimeout(esWsBReconnectTimer); esWsBReconnectTimer = null }
  if (esWsB) { esWsB.onclose = null; esWsB.close(); esWsB = null }
  esWsBConnected.value = false
}

// Process events from a parent-supplied stream (LandingPage embed mode).
// Each item carries `rawData` with the original WS payload that
// handleEventStoreMessage() expects. Dedup by id since the parent's
// array is sort-and-truncate (the same id won't reappear after dropping
// off the end, but we guard against re-processing during sort churn).
const _externalSeenIds = new Set<string>()
watch(() => props.externalEvents, (events) => {
  if (!events || !events.length) return
  let sawNew = false
  for (const item of events) {
    const id = item?.id
    if (!id || _externalSeenIds.has(id)) continue
    _externalSeenIds.add(id)
    const raw = item.rawData
    if (!raw) continue
    // Backpressure gate. If tiles aren't fully loaded OR the camera is
    // still in motion, park this event in the backlog instead of doing the
    // expensive entity/arc work now. scheduleDrain() will trickle it back
    // out at a limited rate once the scene settles. Embedded-mode only —
    // the standalone view has its own rhythm.
    if (props.embedded && textureGateBlocked) {
      eventBacklog.push({ id, rawData: raw })
      if (eventBacklog.length > EMBEDDED_BACKLOG_CAP) {
        eventBacklog.splice(0, eventBacklog.length - EMBEDDED_BACKLOG_CAP)
      }
      continue
    }
    // 2026-05-05 audit Tier 3.1: thread frame through item.frame.
    // LandingPage now tags Frame B WS events with frame='B'; default 'A'
    // preserves prior behaviour for callers that don't set it.
    handleEventStoreMessage(raw, item.frame ?? 'A')
    sawNew = true
  }
  if (sawNew) {
    lastExternalEventTs = Date.now()
    // Real activity — step aside the demo loop on the embedded hero globe.
    if (props.embedded && demoMode.value) stopDemo()
  }
  // Bound the Set so it can't grow unbounded over a long session.
  if (_externalSeenIds.size > 1000) {
    const arr = Array.from(_externalSeenIds)
    _externalSeenIds.clear()
    arr.slice(-500).forEach(x => _externalSeenIds.add(x))
  }
}, { deep: true, immediate: true })

async function seedInitialArcs() {
  const local = worldRegistries.value.find(r => r.id === '__local__')
  for (const peer of worldRegistries.value.filter(r => r.id !== '__local__' && r.hopDepth <= 1)) {
    if (!local) continue
    const arcColor = hopColor(Math.max(local.hopDepth, peer.hopDepth))
    setTimeout(() => {
      spawnArc({ fromLat: local.lat, fromLng: local.lng, toLat: peer.lat, toLng: peer.lng,
        color: arcColor, type: 'federation', label: `${local.name} ↔ ${peer.name}`,
        duration: ARC_DURATION_MS * 3.0, fromName: local.name, toName: peer.name })
      pushFeedEvent({ type: 'federation', title: 'Federation Link', sub: `${local.name} ↔ ${peer.name}`, color: PALETTE.federation.feed })
    }, 800)
  }
}

function seedTopologyArcs() {
  const regByDomain = new Map<string, WorldRegistry>()
  for (const reg of worldRegistries.value) {
    if (reg.publicUrl) regByDomain.set(domainKey(reg.publicUrl), reg)
    if (reg.id === '__local__') regByDomain.set('__local__', reg)
  }

  let delay = 1200
  for (const edgeStr of topology.edges) {
    const [domA, domB] = edgeStr.split('::')
    const regA = regByDomain.get(domA)
    const regB = regByDomain.get(domB)
    if (!regA || !regB) continue
    // Skip local↔direct arcs (already drawn)
    if ((regA.id === '__local__' && regB.hopDepth === 1) ||
        (regB.id === '__local__' && regA.hopDepth === 1)) continue

    const maxHop = Math.max(regA.hopDepth, regB.hopDepth)
    const arcColor = hopColor(maxHop)

    setTimeout(() => {
      spawnArc({ fromLat: regA.lat, fromLng: regA.lng, toLat: regB.lat, toLng: regB.lng,
        color: arcColor, type: 'federation', label: `${regA.name} ↔ ${regB.name}`,
        duration: ARC_DURATION_MS * 4.0, fromName: regA.name, toName: regB.name })
    }, delay)
    delay += 300
  }
}

// ─── Computed ──────────────────────────────────────────────────────────────

const networkStats = computed(() => ({
  totalAgents: worldAgents.value.length,
  visibleAgents: visibleAgentCount.value,
  totalRegistries: worldRegistries.value.length,
  federatedRegistries: worldRegistries.value.length, // all registries participate in federation
  eliteAgents: worldAgents.value.filter(a => a.visualReputation >= 95).length,
}))

const registryOptions = computed(() => [
  { id: 'all', name: 'All Registries' },
  ...worldRegistries.value.map(r => ({ id: r.id, name: r.name })),
])

function reputationColor(rep: number): string {
  if (rep >= 95) return '#ffd700'
  if (rep >= 80) return 'var(--nc-primary-bright)'
  if (rep >= 60) return '#29b6f6'
  return '#90a4ae'
}

function agentTierLabel(rep: number): string {
  if (rep >= 95) return 'ELITE'
  if (rep >= 80) return 'TRUSTED'
  if (rep >= 60) return 'VERIFIED'
  return 'STANDARD'
}

function agentTierClass(rep: number): string {
  if (rep >= 95) return 'elite'
  if (rep >= 80) return 'great'
  if (rep >= 60) return 'good'
  return 'low'
}

function viewAgentProfile(agent: WorldAgent) {
  router.push({ name: 'agent-details', params: { agentId: agent.did } })
}

// ─── Lifecycle ─────────────────────────────────────────────────────────────

// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a globe left during its first reads builds no viewer, opens no socket and starts no poll when they land
const alive = useAlive()
onMounted(async () => {
  // §FEDEVENTS-6: start deploy-config + card resolution in parallel with the
  // heavy init — the pre-dial `await ensureDeployCfg()` below is then instant.
  void ensureDeployCfg()
  void framesApi.ensureLoaded()
  await loadData()
  if (!alive()) return
  initViewer()
  buildRegistryEntities()
  buildAgentEntities()
  buildGraticule()
  await seedInitialArcs()
  if (!alive()) return
  // §pass62.1 (2026-05-21) — Honor ?focus=<peer_name>: find matching registry,
  // open its detail panel, and pan camera to it. Case-insensitive name match.
  // No-op if param missing or peer not found in current worldRegistries.
  // Wrapped in a function so watch() below can re-trigger when the query
  // changes without a page reload (Vue Router hash navigation reuses the
  // same component instance — onMounted only fires once).
  applyFocusFromQuery()
  // Only open our own WS when no parent feed is provided. When LandingPage
  // passes `external-events`, we hook into its array (see watcher above) —
  // eliminates the duplicate /ws/events connection that caused ~50%
  // duplicate event delivery on Frame A.
  // §FEDEVENTS-6: deployment truth resolves BEFORE any dial decision — a
  // single-frame node opens ONLY its own stream (its vhost serves no -b/-c).
  await ensureDeployCfg()
  if (!alive()) return
  if (!props.externalEvents) {
    connectEventStoreWs()
    if (multiFrame.value) {
      // Standalone view also subscribes to Frame B's sovereign EventStore so
      // Frame B → Frame B local transfers actually appear on the globe.
      connectEventStoreWsB()
      // …and Frame C's sovereign BVT EventStore, so the second currency's
      // economy (frame-c + the ME cloud-ops) is visible too.
      connectEventStoreWsC()
    }
  } else {
    // Embedded mode (LandingPage) currently passes only Frame A's stream.
    // When LandingPage gains dual-frame embedding we'll thread the variant
    // through here; until then, treat the parent stream as Frame A.
    esWsConnected.value = true
    pushFeedEvent({ type: 'system', title: 'EventStore connected', sub: 'Sharing parent stream', color: PALETTE.system.feed, frame: 'A' })
  }
  arcAnimFrame = requestAnimationFrame(updateArcs)

  // AW-2: standalone-only live fleet health (admin-gated; 401/403 silently
  // disables — see pollFleetHealth). Embedded anonymous globes skip entirely.
  if (!props.embedded) {
    pollFleetHealth()
    healthTimer = setInterval(pollFleetHealth, 30_000)

    // Console-only debug hooks for deterministic gating (Playwright) without
    // waiting for real traffic — mirrors the __gccRestartDemo pattern.
    ;(window as any).__awSeedArc = (fromKey?: string, toKey?: string, currency: 'AVT' | 'BVT' | 'FX' = 'BVT') => {
      const regs = worldRegistries.value
      if (regs.length < 2) return false
      const pick = (key?: string, not?: WorldRegistry) => {
        if (key) { const m = matchSiteForKey(key); if (m) return m }
        const pool = regs.filter(r => r !== not)
        return pool[Math.floor(Math.random() * pool.length)]
      }
      const a = pick(fromKey)!
      const b = pick(toKey, a)!
      spawnArc({
        fromLat: a.lat, fromLng: a.lng, toLat: b.lat, toLng: b.lng,
        color: currency === 'BVT' ? BVT_GOLD : AVT_CYAN,
        colorEnd: currency === 'FX' ? BVT_GOLD : undefined,
        type: 'transfer', label: `Demo ${currency}`, duration: 4200,
        widthMul: 1.3, glowMul: 1.5, fromName: a.name, toName: b.name,
      })
      viewer.value?.scene.requestRender()
      return `${a.name} → ${b.name}`
    }
    ;(window as any).__awHealthDemo = (key?: string, ms = 8000, state: 'down' | 'degraded' = 'down') => {
      const site = key ? matchSiteForKey(key) : (worldRegistries.value.find(r => r.id === '__local__') || worldRegistries.value[0])
      if (!site) return false
      healthOverride.set(site.id, { state, until: performance.now() + ms })
      viewer.value?.scene.requestRender()
      return site.name
    }
    ;(window as any).__awWsStatus = () => ({ a: esWsConnected.value, b: esWsBConnected.value, c: esWsCConnected.value })
  }

  // Auto-start demo mode when embedded on landing page. The demo loop yields
  // to real events: the externalEvents watcher calls stopDemo() whenever a
  // real event arrives, and the idle poll below starts the demo again after
  // DEMO_IDLE_MS of silence. Cold start kicks demo on immediately so the
  // hero is visually alive before the WS connects.
  if (props.embedded) {
    autoRotate.value = true
    startDemo(120)  // slower than standalone (60ms) for elegant feel
    demoIdlePoll = setInterval(() => {
      if (!props.embedded) return
      const idleFor = Date.now() - (lastExternalEventTs || 0)
      if (idleFor > DEMO_IDLE_MS && !demoMode.value) startDemo(120)
    }, DEMO_IDLE_POLL_MS)
  }
})

onUnmounted(() => {
  if (arcAnimFrame !== null) cancelAnimationFrame(arcAnimFrame)
  if (demoTimer) clearInterval(demoTimer)
  if (demoIdlePoll) clearInterval(demoIdlePoll)
  if (healthTimer) { clearInterval(healthTimer); healthTimer = null }
  delete (window as any).__awSeedArc
  delete (window as any).__awHealthDemo
  delete (window as any).__awWsStatus
  if (drainScheduler) { clearTimeout(drainScheduler); drainScheduler = null }
  eventBacklog.length = 0
  disconnectEventStoreWs()
  disconnectEventStoreWsB()
  disconnectEventStoreWsC()
  // Detach Cesium event listeners we added in initViewer (audit Tier 1B).
  // Must run BEFORE viewer.destroy() so the cleanup callbacks can still
  // reach the event objects through Cesium's internal references.
  for (const fn of _cesiumCleanups) { try { fn() } catch { /* */ } }
  _cesiumCleanups = []
  // Post-fx stages are owned by scene.postProcessStages; Viewer.destroy()
  // releases them. Null the refs so a hot-reload doesn't attach to a dead
  // Viewer's stages.
  vignetteStage = null
  chromaticAberrationStage = null
  graticuleEntities.length = 0
  _spriteCache.clear()
  if (handler) { handler.destroy(); handler = null }
  if (viewer.value) { viewer.value.destroy(); viewer.value = null }
})

watch(searchQuery, (term) => {
  buildAgentEntities()
  // Widen to the server only after typing settles, and only when the sample
  // could not answer — a search must never be able to make the globe worse.
  if (searchDebounce) clearTimeout(searchDebounce)
  if (!term || term.trim().length < 2) { searchServerNote.value = ''; return }
  searchDebounce = setTimeout(() => { void resolveSearchOnServer(term) }, 350)
})
watch(filterRegistry, () => buildAgentEntities())
watch(filterTier, () => buildAgentEntities())
// §pass62.1 (2026-05-21) — Re-apply focus when ?focus= query changes via SPA
// navigation. Hash-only changes don't remount AgentWorldCesium, so without
// this the focus deep-link only works on first page load (or hard reload).
watch(() => route.query.focus, () => applyFocusFromQuery())
watch(topologyVersion, () => {
  const existingDirect = worldRegistries.value.filter(r => !r.id.startsWith('topo-'))
  mergeTopologyRegistries(existingDirect, worldRegistries.value[0]?.name || 'Registry A')
})
watch(showAtmosphere, (visible) => {
  const v = viewer.value
  if (!v) return
  // Toggles both the sky atmosphere rim glow and the ground atmosphere.
  // Direction-D tuning made ground atmosphere safe to show again (warm amber,
  // no blue wash), so the single toggle now drives both.
  if (v.scene.skyAtmosphere) v.scene.skyAtmosphere.show = visible
  v.scene.globe.showGroundAtmosphere = visible
  v.scene.requestRender()
})

// ─── Direction-D live toggles ──────────────────────────────────────────────
// Each watcher flips a Cesium-side flag without re-initialising the Viewer.
// Registry halos, elite flares, and graticule are rebuilt on toggle because
// they're data-driven entity lists.
watch(showTerminator, (on) => {
  const v = viewer.value
  if (!v) return
  v.scene.globe.enableLighting = on
  // Night-lights only makes sense when lighting is on (day/night blending
  // needs the sun). Force the overlay off when the terminator turns off.
  const layer = (v as any)._nightLightsLayer as ImageryLayer | undefined
  if (layer) layer.nightAlpha = (on && showNightLights.value) ? 0.55 : 0.0
  v.scene.requestRender()
})
watch(showNightLights, (on) => {
  const v = viewer.value
  if (!v) return
  const layer = (v as any)._nightLightsLayer as ImageryLayer | undefined
  if (layer) layer.nightAlpha = (on && showTerminator.value) ? 0.55 : 0.0
  v.scene.requestRender()
})
watch(showRegistryHalos, () => buildRegistryEntities())
watch(showEliteFlares, () => buildAgentEntities())
watch(showGraticule, () => buildGraticule())
watch(showBloom, (on) => {
  const v = viewer.value
  if (!v || !v.scene.postProcessStages?.bloom) return
  v.scene.postProcessStages.bloom.enabled = on
  v.scene.requestRender()
})
watch(showVignette, (on) => {
  if (vignetteStage) vignetteStage.enabled = on
  viewer.value?.scene.requestRender()
})
watch(showChromaticAberration, (on) => {
  if (chromaticAberrationStage) chromaticAberrationStage.enabled = on
  viewer.value?.scene.requestRender()
})
watch(visualQuality, (q) => applyQualityPreset(q))
</script>

<template>
  <div class="agentworld-container">

    <!-- Loading -->
    <div v-if="isLoading && !embedded" class="aw-overlay aw-loading">
      <div class="loading-content">
        <div class="aw-loader" aria-hidden="true">
          <span class="aw-loader__core"></span>
          <span class="aw-loader__ring aw-loader__ring--1"><i></i></span>
          <span class="aw-loader__ring aw-loader__ring--2"><i></i></span>
        </div>
        <p class="loading-text">INITIALIZING AGENTWORLD</p>
        <p class="loading-sub">Resolving network topology…</p>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="loadError && !embedded" class="aw-overlay">
      <div style="text-align:center;color:rgba(248,113,113,0.9)">
        <div style="font-size:2rem;margin-bottom:8px"><Icon name="mdi:alert" /></div>
        <p>{{ loadError }}</p>
      </div>
    </div>

    <!-- CesiumJS Globe Container -->
    <div v-show="!isLoading && !loadError" data-tour="aw-globe" ref="viewerContainer" class="agentworld-canvas" />
    <!-- The imagery's sources, shown in place of Cesium's hidden credit bar (REVIEW_2026-09-30_LICENSING.md) -->
    <div v-show="!isLoading && !loadError" class="aw-attribution" data-testid="aw-attribution">Map: Natural Earth · Night lights: NASA GIBS, VIIRS Black Marble</div>

    <!-- Embedded: Click to explore overlay -->
    <div v-if="embedded && !globeInteractive" class="aw-explore-overlay" @click="enableGlobeInteraction">
      <div class="aw-explore-hint">Explore &#8599;</div>
    </div>
    <!-- Embedded: Close button when interactive -->
    <div v-if="embedded && globeInteractive" class="aw-explore-close" @click="disableGlobeInteraction">
      ✕ Resume auto-rotate
    </div>

    <!-- ═══ HOVER TOOLTIP ═══════════════════════════════════════════════ -->
    <Teleport to="body">
      <!-- Agent hover -->
      <div v-if="hoveredAgent && !selectedAgent && !selectedRegistry && (!embedded || globeInteractive)" class="aw-galactic-tooltip"
        :style="tooltipStyle">
        <!-- Unified reusable hover label (shared across all 3 topology views).
             AgentWorld keeps its lazy-loaded UserAvatar via the #avatar slot. -->
        <TopologyHoverLabel v-if="awAgentEntity" :entity="awAgentEntity" :local-currency="localCurrency">
          <template #avatar>
            <!-- §MARKCOLLAR — the hover label was the one agent surface that
                 showed neither the equipped encirclement nor the earned mark.
                 Both render here now, through the SAME components the cards
                 and the modal use, so a hovered agent looks like itself. -->
            <FlareEncirclement
              v-if="hoverAgentFlare"
              :tier="hoverAgentFlare.tier"
              :variant="hoverAgentFlare.variant"
              :overlay="hoverAgentFlare.overlay"
              :avatar-url="hoverAgentAvatarUrl"
              :initials="(hoveredAgent.name || '?').slice(0, 2)"
              :track-record="hoveredAgent.trackRecord || null"
              size="md"
              class="gtt-avatar"
            />
            <!-- §MARKCOLLAR-2 — the mark wraps EVERY branch, including the
                 placeholder. Federated agents (tx-doha) 404 on /agents/by-did/,
                 so their hover fell to the placeholder orb and lost the mark
                 entirely: the Commander saw a proven agent wearing nothing.
                 An earned mark must not depend on whether a cosmetic profile
                 fetch happened to succeed. -->
            <EarnedMarkRing v-else :tr="hoveredAgent.trackRecord || null" size="md">
              <UserAvatar
                v-if="hoverAgentProfiles[hoveredAgent.did]"
                :user="hoverAgentProfiles[hoveredAgent.did]"
                :avatar-url="hoverAgentAvatarUrl"
                :display-name="hoveredAgent.name"
                size="md"
                class="gtt-avatar"
              />
              <span v-else class="gtt-avatar-placeholder">
                <span class="gtt-type-badge agent">●</span>
              </span>
            </EarnedMarkRing>
          </template>
        </TopologyHoverLabel>
      </div>

      <!-- Registry hover -->
      <div v-if="hoveredRegistry && !selectedAgent && !selectedRegistry && (!embedded || globeInteractive)" class="aw-galactic-tooltip"
        :style="tooltipStyle">
        <div class="gtt-accent" :style="{ background: `linear-gradient(90deg, ${hoveredRegistry.visual?.orbColor || '#00d2d2'}, ${(hoveredRegistry.visual?.orbGlowColor || hoveredRegistry.visual?.orbColor || '#00d2d2')}66, transparent)` }"></div>
        <!-- Registry Card v0.5 — icon row ALWAYS renders.
             Three states: (1) flare encirclement equipped → FlareEncirclement
             with overlay; (2) icon uploaded but no flare → UserAvatar; (3)
             neither → orb-colored type badge with initials.
             Frame-A's sovereign-pinned orange orb propagates through
             `visual.orbColor` so the type-badge dot picks it up too. -->
        <div class="gtt-avatar-row">
          <FlareEncirclement
            v-if="hoveredRegistry.visual?.flareEncirclementVariant"
            tier="shadow_chancellor"
            :variant="hoveredRegistry.visual.flareEncirclementVariant"
            :overlay="hoveredRegistry.visual?.flareEncirclementOverlay || null"
            :avatar-url="resolveRegIcon(hoveredRegistry)"
            :initials="hoveredRegistry.name.slice(0,2).toUpperCase()"
            size="md"
            class="gtt-avatar"
          />
          <UserAvatar
            v-else-if="hoveredRegistry.visual?.iconUrl"
            :avatar-url="resolveRegIcon(hoveredRegistry)"
            :display-name="hoveredRegistry.name"
            size="md"
            class="gtt-avatar"
          />
          <span v-else class="gtt-avatar-placeholder"
            :style="{
              background: `radial-gradient(circle, ${hoveredRegistry.visual?.orbColor || '#00d2d2'}, ${hoveredRegistry.visual?.orbGlowColor || '#00ffff'}88)`,
              boxShadow: `0 0 12px ${hoveredRegistry.visual?.orbColor || '#00d2d2'}`,
            }">
            <span style="font-weight:600; color:#001020; font-size:13px">
              {{ (hoveredRegistry.displayName || hoveredRegistry.name).slice(0,2).toUpperCase() }}
            </span>
          </span>
          <div class="gtt-name-wrap">
            <span class="gtt-name">{{ hoveredRegistry.displayName || hoveredRegistry.name }}</span>
            <span class="gtt-status-badge" :class="(hoveredRegistry.status || 'active').toLowerCase()">
              {{ (hoveredRegistry.status || 'ACTIVE').toUpperCase() }}
            </span>
            <span v-if="hoveredRegCurrency" class="gtt-hop-badge"
              :title="`Settlement currency: ${hoveredRegCurrency}`"
              :style="{ borderColor: describe(hoveredRegCurrency).accent + '88', color: describe(hoveredRegCurrency).accent }">
              <span aria-hidden="true">{{ describe(hoveredRegCurrency).glyph }}</span> {{ hoveredRegCurrency }}
            </span>
            <span v-if="hoveredRegistry.hopDepth > 0" class="gtt-hop-badge"
              :style="{ borderColor: hopColor(hoveredRegistry.hopDepth) + '88', color: hopColor(hoveredRegistry.hopDepth) }">
              HOP {{ hoveredRegistry.hopDepth }}
            </span>
            <span v-if="hoveredRegistry.visual?.sovereignVariant" class="gtt-synced-badge"
              :style="{ background: 'linear-gradient(90deg, ' + (hoveredRegistry.visual.orbColor || '#888') + '44, transparent)', color: hoveredRegistry.visual.orbColor || '#fff', borderColor: (hoveredRegistry.visual.orbColor || '#888') + '88' }">
              ★ {{ hoveredRegistry.visual.sovereignVariant.toUpperCase() }}
            </span>
            <span v-if="hoveredRegistry.visual?.flareEncirclementOverlay" class="gtt-synced-badge"
              :style="{ color: '#ff5252', borderColor: '#ff5252', background: 'rgba(255,82,82,0.1)' }">
              <Icon name="mdi:lightning-bolt" /> {{ hoveredRegistry.visual.flareEncirclementOverlay.toUpperCase() }}
            </span>
            <span v-if="hoveredRegistry.exchange?.enabled" class="gtt-hop-badge"
              :title="hoveredRegistry.exchange.passport_enabled ? `AGORA market · ${hoveredRegistry.exchange.currency} · accepts Passport` : `AGORA market · ${hoveredRegistry.exchange.currency}`"
              :style="{ borderColor: '#ffd54f88', color: '#ffd54f', background: 'rgba(255,213,79,0.08)' }">
              <Icon name="mdi:chart-line" /> {{ hoveredRegistry.exchange.currency || 'MARKET' }}
            </span>
          </div>
        </div>
        <div class="gtt-detail" v-if="hoveredRegistry.publicUrl">
          <span class="gtt-url">{{ hoveredRegistry.publicUrl }}</span>
        </div>
        <div class="gtt-desc" v-if="hoveredRegistry.description">{{ hoveredRegistry.description }}</div>
        <div class="gtt-stats">
          <span class="gtt-stat"><span class="gtt-stat-label">Health</span><span class="gtt-stat-value" style="color:#00e676">100%</span></span>
          <span class="gtt-stat"><span class="gtt-stat-label">Agents</span><span class="gtt-stat-value">{{ hoveredRegistry.agentCount }}</span></span>
          <span class="gtt-stat" v-if="hoveredRegistry.protocolVersion"><span class="gtt-stat-label">Protocol</span><span class="gtt-stat-value" style="font-size:11px">v{{ hoveredRegistry.protocolVersion }}</span></span>
        </div>
        <!-- Registry Card v0.5 — fee composition (intra · cross · hosting) -->
        <div class="gtt-stats gtt-fee-rail" v-if="hoveredRegistry.fees">
          <span class="gtt-stat" v-if="hoveredRegistry.fees.intraRegistry != null">
            <span class="gtt-stat-label">Intra</span>
            <span class="gtt-stat-value" style="color:#4fc3f7">{{ hoveredRegistry.fees.intraRegistry }}%</span>
          </span>
          <span class="gtt-stat" v-if="hoveredRegistry.fees.crossRegistry != null">
            <span class="gtt-stat-label">Cross-Reg</span>
            <span class="gtt-stat-value" style="color:#ffaa00">{{ hoveredRegistry.fees.crossRegistry }}%</span>
          </span>
          <span class="gtt-stat" v-if="hoveredRegistry.fees.hostingEnabled">
            <span class="gtt-stat-label">Hosting</span>
            <span class="gtt-stat-value" style="color:#ff6b35">{{ hoveredRegistry.fees.hostingRate || 0 }}%</span>
          </span>
          <span class="gtt-stat" v-else-if="hoveredRegistry.fees.hostingEnabled === false">
            <span class="gtt-stat-label">Hosting</span>
            <span class="gtt-stat-value" style="color:#00e676;font-size:10px">FREE</span>
          </span>
        </div>
        <div class="gtt-auth" v-if="hoveredRegistry.authMethods && hoveredRegistry.authMethods.length > 0">
          <span class="gtt-stat-label">Auth</span>
          <span class="gtt-auth-tag" v-for="m in hoveredRegistry.authMethods.filter(a => a !== 'bearer_token')" :key="m">{{ m.replace(/_/g, ' ') }}</span>
        </div>
        <!-- Registry Card v0.3 — signature trust indicator -->
        <div class="gtt-sync" v-if="hoveredRegistry.cardEtag">
          <span class="gtt-stat-label">Card</span>
          <span :style="{ color: hoveredRegistry.cardSignatureVerified ? '#00e676' : '#ffaa00', fontSize: '10px', marginLeft: '4px' }">
            {{ hoveredRegistry.cardSignatureVerified ? '✓ SIGNED' : '⚠ UNSIGNED' }} v0.5
          </span>
        </div>
        <div class="gtt-sync" v-if="hoveredRegistry.lastSyncedAt">
          <span class="gtt-stat-label">Last Sync</span>
          <span style="color:#90a4ae;font-size:10px;margin-left:4px">{{ formatFeedTime(new Date(hoveredRegistry.lastSyncedAt).getTime()) }}</span>
        </div>
        <div class="gtt-hint">▸ click for the full registry card</div>
      </div>
    </Teleport>

    <!-- ═══ LEFT CONTROLS HUD ══════════════════════════════════════════ -->
    <div v-if="!isLoading && !loadError && !embedded && !cockpit" data-tour="aw-hud" class="aw-panel aw-controls" :class="{ 'aw-panel-collapsed': panelCollapsed }">
      <div class="aw-panel-title" @click="panelCollapsed = !panelCollapsed" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center">
        <span><span class="aw-title-dot"></span>AGENTWORLD</span>
        <span style="font-size:0.65rem;opacity:0.5">{{ panelCollapsed ? '▸' : '▾' }}</span>
      </div>

      <template v-if="!panelCollapsed">
      <div class="aw-search-wrap">
        <input v-model="searchQuery" type="text" :placeholder="tr('agents.placeholders.searchAgents', 'Search agents by name or DID...')" class="aw-search" data-testid="aw-search" />
        <div v-if="searchServerBusy || searchServerNote" class="aw-search-note" data-testid="aw-search-note">
          {{ searchServerBusy ? 'searching every registry…' : searchServerNote }}
        </div>
      </div>

      <div class="aw-filter-group">
        <label for="agentworldcesium-sel-4953" class="aw-filter-label">REGISTRY</label>
        <select id="agentworldcesium-sel-4953" v-model="filterRegistry" class="aw-filter-select">
          <option v-for="r in registryOptions" :key="r.id" :value="r.id">{{ r.name }}</option>
        </select>
      </div>

      <div class="aw-filter-group">
        <label class="aw-filter-label">TIER</label>
        <div class="aw-tier-btns">
          <button v-for="t in [['all','All'],['proven','Proven'],['elite','Elite'],['high','High'],['standard','Std']]" :key="t[0]"
            @click="filterTier = t[0]" :data-testid="`aw-tier-${t[0]}`"
            :title="t[0] === 'proven' ? 'Agents with work verified by this registry\'s guild books'
                    : (t[0] === 'elite' || t[0] === 'high' ? 'Graph reputation tier (EigenTrust). Sparse while the network is idle.' : '')"
            :class="['aw-tier-btn', filterTier === t[0] && 'active']">{{ t[1] }}</button>
        </div>
      </div>

      <div class="aw-controls-group">
        <label class="aw-toggle"><input type="checkbox" v-model="autoRotate" /><span class="aw-toggle-label">Auto-rotate</span></label>
        <label class="aw-toggle"><input type="checkbox" v-model="showArcs" /><span class="aw-toggle-label">Signal arcs</span></label>
        <label class="aw-toggle"><input type="checkbox" v-model="showAtmosphere" /><span class="aw-toggle-label">Atmosphere</span></label>
        <button @click="toggleDemoMode" :class="['aw-demo-btn', demoMode && 'active']">{{ demoMode ? '⚡ DEMO ON' : '⚡ DEMO' }}</button>
      </div>

      <!-- VISUAL block — Direction-D quality preset + per-feature toggles.
           Every preset is additive: Low → Medium → High → Ultra. Changing the
           preset never turns anything off, only adds more polish. -->
      <div class="aw-controls-group">
        <div class="aw-filter-label aw-signal-header" @click="showVisualBlock = !showVisualBlock" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          VISUAL <span style="font-size:0.55rem;opacity:0.4">{{ showVisualBlock ? '▾' : '▸' }}</span>
        </div>
        <div v-if="showVisualBlock">
          <div class="aw-visual-preset-row">
            <label for="agentworldcesium-sel-4986" class="aw-filter-label" style="margin-right:6px;align-self:center">QUALITY</label>
            <select id="agentworldcesium-sel-4986" v-model="visualQuality" class="aw-filter-select aw-visual-preset-select">
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="ultra">Ultra</option>
            </select>
          </div>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showTerminator" /><span class="aw-arc-dot" style="background:#ffb74d;box-shadow:0 0 6px #ffb74d77"></span>Terminator</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showNightLights" /><span class="aw-arc-dot" style="background:#ffe082;box-shadow:0 0 6px #ffe08277"></span>Night lights</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showRegistryHalos" /><span class="aw-arc-dot" style="background:#00bcd4;box-shadow:0 0 6px #00bcd477"></span>Registry halos</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showEliteFlares" /><span class="aw-arc-dot" style="background:#ffd700;box-shadow:0 0 6px #ffd70077"></span>Elite flares</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showBloom" /><span class="aw-arc-dot" style="background:#ffffff;box-shadow:0 0 6px #ffffff88"></span>Bloom</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showVignette" /><span class="aw-arc-dot" style="background:#1a1f2e;border:1px solid #333"></span>Vignette</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="showChromaticAberration" /><span class="aw-arc-dot" style="background:linear-gradient(90deg,#ff3df0,#00e5ff)"></span>Chromatic</label>
        </div>
      </div>

      <!-- Signal type filters -->
      <div v-if="showArcs" class="aw-controls-group">
        <div class="aw-filter-label aw-signal-header" @click="showSignalFilters = !showSignalFilters" style="cursor:pointer;display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          SIGNALS <span style="font-size:0.55rem;opacity:0.4">{{ showSignalFilters ? '▾' : '▸' }}</span>
        </div>
        <div v-if="showSignalFilters" class="aw-signal-grid">
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterTransfer" /><span class="aw-arc-dot" :style="{ background: PALETTE.transfer.local.arc }"></span>Transfer</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterStaking" /><span class="aw-arc-dot" :style="{ background: PALETTE.staking.arc }"></span>Locks</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterFederation" /><span class="aw-arc-dot" :style="{ background: PALETTE.federation.arc }"></span>Federation</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterGovernance" /><span class="aw-arc-dot" :style="{ background: PALETTE.governance.arc }"></span>Gov</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterDispute" /><span class="aw-arc-dot" :style="{ background: PALETTE.dispute.arc }"></span>Dispute</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterContract" /><span class="aw-arc-dot" :style="{ background: PALETTE.contract.arc }"></span>Contract</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterOnboarding" /><span class="aw-arc-dot" :style="{ background: PALETTE.onboarding.arc }"></span>Onboard</label>
          <label class="aw-toggle-compact"><input type="checkbox" v-model="arcFilterAttestation" /><span class="aw-arc-dot" :style="{ background: PALETTE.attestation.arc }"></span>ZKP</label>
        </div>
      </div>

      <div class="aw-interact-guide">
        <div><kbd>Drag</kbd> Rotate globe</div>
        <div><kbd>Scroll</kbd> Zoom</div>
        <div><kbd>Click</kbd> Fly to agent</div>
      </div>

      <div class="aw-legend" data-tour="aw-legend">
        <!-- TRANSFER VARIANTS — variant + currency, so cross-frame and the
             BVT economy are unmissable. FX arcs lerp cyan→gold in flight. -->
        <div class="aw-legend-title">TRANSFERS</div>
        <div class="aw-legend-row"><span class="aw-beam" :style="{ background: 'linear-gradient(90deg, transparent, ' + PALETTE.transfer.local.arc + ', transparent)' }"></span>Local · {{ localCurrency }}</div>
        <div class="aw-legend-row"><span class="aw-beam" :style="{ background: 'linear-gradient(90deg, transparent, ' + PALETTE.transfer.crossRegistry.arc + ', transparent)', height: '4px' }"></span>Cross-registry · same frame</div>
        <div class="aw-legend-row"><span class="aw-beam" :style="{ background: 'linear-gradient(90deg, transparent, ' + PALETTE.transfer.crossFrame.arc + ', transparent)', height: '5px', boxShadow: '0 0 10px ' + PALETTE.transfer.crossFrame.arc + 'cc' }"></span>Cross-frame</div>
        <div class="aw-legend-row"><span class="aw-beam" style="background:linear-gradient(90deg, transparent, #ffc400, transparent); box-shadow:0 0 8px #ffc40088"></span>BVT economy (Frame C)</div>
        <div class="aw-legend-row"><span class="aw-beam" style="background:linear-gradient(90deg, transparent 4%, #00e5ff 28%, #ffc400 72%, transparent 96%); height:5px; box-shadow:0 0 10px #ffc400aa"></span>FX swap · in flight</div>
        <div class="aw-legend-row"><span class="aw-ring"></span>Impact ring — transfer landed</div>

        <!-- EVENT TYPES — every other arc class -->
        <div class="aw-legend-title" style="margin-top:8px">EVENTS</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.dispute.arc }"></span>Dispute</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.contract.arc }"></span>Contract</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.governance.arc }"></span>Governance</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.staking.arc }"></span>Locks</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.attestation.arc }"></span>Attestation (ZKP)</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.onboarding.arc }"></span>Onboarding</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.fee.arc }"></span>Fee → pool</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.mint.arc }"></span>Issued → agent</div>
        <div class="aw-legend-row"><span class="aw-dot" :style="{ background: PALETTE.federation.arc }"></span>Federation</div>
        <div class="aw-legend-row"><span class="aw-beam" :style="{ background: 'linear-gradient(90deg, transparent, ' + PALETTE.bridge.arc + ', transparent)' }"></span>Wrapped-unit bridge</div>

        <!-- AGENT TIERS -->
        <div class="aw-legend-title" style="margin-top:8px">AGENTS</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#ffd700;box-shadow:0 0 6px #ffd70099"></span>Elite (95+)</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:var(--nc-primary-bright);box-shadow:0 0 6px var(--nc-primary-bright)66"></span>High (80+)</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#29b6f6"></span>Active (60+)</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#4fc3f7"></span>Standard</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#ffab40;box-shadow:0 0 5px #ffab4055"></span>Federated</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#ff4fb4;box-shadow:0 0 5px #ff4fb455"></span>Frame B agent</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#ffb300;box-shadow:0 0 5px #ffb30066"></span>Frame C agent · BVT</div>

        <!-- REGISTRY MARKERS -->
        <div class="aw-legend-title" style="margin-top:8px">REGISTRIES</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#00e676;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #00e67666"></span>Local (hub)</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#5c9cf5;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #5c9cf566"></span>Direct peer</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#00bcd4;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #00bcd466"></span>2-hop relay</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#ff9800;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #ff980066"></span>3-hop relay</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#e91e63;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #e91e6366"></span>4-hop relay</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#d50000;border-radius:3px;width:11px;height:11px;box-shadow:0 0 6px #d5000066"></span>5+ hop (deep)</div>
        <div class="aw-legend-row aw-legend-note">Frame B mirrors hop colours in magenta · Frame C in gold/amber</div>

        <!-- LIVE STATUS — health tint on registry halos + activity heat (AW v2) -->
        <div class="aw-legend-title" style="margin-top:8px">LIVE STATUS</div>
        <div class="aw-legend-row"><span class="aw-dot" style="background:#00e676;box-shadow:0 0 7px #00e676aa"></span>Halo — registry healthy</div>
        <div class="aw-legend-row"><span class="aw-dot aw-pulse" style="background:#ffb300;box-shadow:0 0 7px #ffb300aa"></span>Degraded — amber pulse</div>
        <div class="aw-legend-row"><span class="aw-dot aw-pulse" style="background:#ff5252;box-shadow:0 0 7px #ff5252aa"></span>Down — red pulse</div>
        <div class="aw-legend-row"><span class="aw-dot aw-heat-chip"></span>Brighter halo = busier (60s heat)</div>
        <div class="aw-legend-row aw-legend-note">Health tint needs an admin session; others see neutral halos</div>
      </div>
      </template>
    </div>

    <!-- ═══ SELECTED AGENT PANEL ════════════════════════════════════════ -->
    <div v-if="useLegacyAgentPanel && selectedAgent && !embedded" class="aw-panel aw-agent-panel">
      <div class="aw-ap-header">
        <div class="aw-ap-header-left">
          <div class="aw-ap-name-row">
            <span class="aw-ap-tier-dot" :style="{ background: reputationColor(selectedAgent.visualReputation), boxShadow: '0 0 8px ' + reputationColor(selectedAgent.visualReputation) + '88' }"></span>
            <h3 class="aw-ap-name">{{ selectedAgent.name }}</h3>
          </div>
          <p class="aw-ap-did">{{ selectedAgent.did }}</p>
        </div>
        <button class="aw-close-btn" @click="selectedAgent = null">✕</button>
      </div>
      <div class="aw-ap-grid">
        <div class="aw-ap-cell"><span class="aw-ap-cell-label">Reputation</span>
          <span class="aw-ap-cell-value aw-ap-big" :style="{ color: reputationColor(selectedAgent.visualReputation) }">{{ selectedAgent.visualReputation > 1 ? selectedAgent.visualReputation : '—' }}</span></div>
        <div class="aw-ap-cell"><span class="aw-ap-cell-label">Balance</span>
          <span class="aw-ap-cell-value aw-ap-big" style="color:#4fc3f7">{{ (selectedAgent.liquidBalance + selectedAgent.stakedBalance) > 0 ? (selectedAgent.liquidBalance + selectedAgent.stakedBalance).toLocaleString(appLocale()) : '—' }}</span></div>
        <div class="aw-ap-cell"><span class="aw-ap-cell-label">Registry</span>
          <span class="aw-ap-cell-value">{{ selectedAgent.registryName || 'Local' }}<span v-if="selectedAgent.isSynced" class="aw-synced-badge">SYNCED</span></span></div>
        <div class="aw-ap-cell"><span class="aw-ap-cell-label">Status</span>
          <span class="aw-ap-cell-value" style="display:flex;align-items:center;gap:5px">
            <span class="aw-status-dot" :class="selectedAgent.status === 'active' ? 'active' : 'inactive'"></span>
            <span style="text-transform:capitalize">{{ selectedAgent.status }}</span></span></div>
      </div>
      <div class="aw-ap-coords">{{ (selectedAgent.lat ?? 0).toFixed(3) }}°N · {{ (selectedAgent.lng ?? 0).toFixed(3) }}°E</div>
      <div v-if="selectedAgent.capabilities.length" class="aw-ap-caps">
        <span class="aw-ap-cell-label" style="margin-bottom:5px;display:block">Capabilities</span>
        <div class="aw-ap-caps-wrap"><span v-for="cap in selectedAgent.capabilities.slice(0, 6)" :key="cap" class="aw-cap-tag">{{ cap }}</span></div>
      </div>
      <button class="aw-profile-btn" @click="viewAgentProfile(selectedAgent)">View Full Profile</button>
    </div>

    <!-- ═══ SELECTED REGISTRY PANEL (Registry Card v0.3.1) ═══════════════
         Mirror of the agent panel — click on a registry orb opens this
         pinned detail card with avatar (or flare encirclement), tier,
         signature trust, sovereign-variant, fee summary, well-known links.
         ═══════════════════════════════════════════════════════════════════ -->
    <div v-if="selectedRegistry && !embedded" class="aw-panel aw-agent-panel">
      <div class="aw-ap-header">
        <div class="aw-ap-header-left" style="display:flex; gap:12px; align-items:center">
          <FlareEncirclement
            v-if="selectedRegistry.visual?.flareEncirclementVariant"
            tier="shadow_chancellor"
            :variant="selectedRegistry.visual.flareEncirclementVariant"
            :overlay="selectedRegistry.visual?.flareEncirclementOverlay || null"
            :avatar-url="resolveRegIcon(selectedRegistry)"
            :initials="selectedRegistry.name.slice(0,2).toUpperCase()"
            size="lg"
          />
          <UserAvatar
            v-else-if="selectedRegistry.visual?.iconUrl"
            :avatar-url="resolveRegIcon(selectedRegistry)"
            :display-name="selectedRegistry.name"
            size="lg"
          />
          <span v-else class="aw-ap-orb-avatar"
            :style="{
              background: `radial-gradient(circle, ${selectedRegistry.visual?.orbColor || '#00d2d2'}, ${selectedRegistry.visual?.orbGlowColor || '#00ffff'}88)`,
              boxShadow: `0 0 20px ${selectedRegistry.visual?.orbColor || '#00d2d2'}`,
            }">
            <span style="font-weight:700; color:#001020; font-size:18px">
              {{ selectedRegistry.name.slice(0,2).toUpperCase() }}
            </span>
          </span>
          <div>
            <div class="aw-ap-name-row">
              <h3 class="aw-ap-name">{{ selectedRegistry.name }}</h3>
            </div>
            <p class="aw-ap-did" v-if="selectedRegistry.publicUrl">{{ selectedRegistry.publicUrl }}</p>
            <div style="display:flex; gap:6px; margin-top:6px; flex-wrap:wrap">
              <span class="aw-synced-badge" v-if="selectedRegistry.visual?.sovereignVariant"
                :style="{ color: selectedRegistry.visual.orbColor || '#fff', borderColor: (selectedRegistry.visual.orbColor || '#888') + '88', background: (selectedRegistry.visual.orbColor || '#888') + '22' }">
                ★ {{ selectedRegistry.visual.sovereignVariant.toUpperCase() }}
              </span>
              <span class="aw-synced-badge" v-if="selectedRegistry.visual?.flareEncirclementVariant"
                style="color:#a855f7; border-color:#a855f7; background:rgba(168,85,247,0.1)">
                ⬡ {{ selectedRegistry.visual.flareEncirclementVariant.toUpperCase() }}
              </span>
              <span class="aw-synced-badge" v-if="selectedRegistry.visual?.flareEncirclementOverlay"
                style="color:#ff5252; border-color:#ff5252; background:rgba(255,82,82,0.1)">
                <Icon name="mdi:lightning-bolt" /> {{ selectedRegistry.visual.flareEncirclementOverlay.toUpperCase() }}
              </span>
              <span class="aw-synced-badge"
                :style="{ color: selectedRegistry.cardSignatureVerified ? '#00e676' : '#ffaa00', borderColor: selectedRegistry.cardSignatureVerified ? '#00e676' : '#ffaa00', background: (selectedRegistry.cardSignatureVerified ? 'rgba(0,230,118,0.1)' : 'rgba(255,170,0,0.1)') }">
                {{ selectedRegistry.cardSignatureVerified ? '✓ SIGNED' : '⚠ UNSIGNED' }}
              </span>
            </div>
          </div>
        </div>
        <button class="aw-close-btn" @click="selectedRegistry = null">✕</button>
      </div>
      <!-- Quick rail (topology slice — always available, even before the card loads) -->
      <div class="aw-ap-grid">
        <div class="aw-ap-cell">
          <span class="aw-ap-cell-label">Agents</span>
          <span class="aw-ap-cell-value aw-ap-big" style="color:#4fc3f7">{{ selectedRegistry.agentCount }}</span>
        </div>
        <div class="aw-ap-cell" v-if="selectedRegistry.fees?.crossRegistry != null">
          <span class="aw-ap-cell-label">Cross-Reg</span>
          <span class="aw-ap-cell-value aw-ap-big" style="color:#ffaa00">{{ selectedRegistry.fees.crossRegistry }}%</span>
        </div>
        <div class="aw-ap-cell">
          <span class="aw-ap-cell-label">Hosting</span>
          <span class="aw-ap-cell-value" :style="{ color: selectedRegistry.fees?.hostingEnabled ? '#ff6b35' : '#00e676' }">
            {{ selectedRegistry.fees?.hostingEnabled ? (selectedRegistry.fees.hostingRate + '%') : 'FREE' }}
          </span>
        </div>
        <div class="aw-ap-cell">
          <span class="aw-ap-cell-label">Hop</span>
          <span class="aw-ap-cell-value" :style="{ color: hopColor(selectedRegistry.hopDepth) }">
            {{ selectedRegistry.hopDepth === 0 ? 'LOCAL' : `${selectedRegistry.hopDepth}` }}
          </span>
        </div>
      </div>

      <div v-if="selectedRegistryCardLoading" class="aw-rc-loading">Loading registry card…</div>

      <p v-if="(selectedRegistryCard?.description || selectedRegistry.description)" class="aw-rc-desc">
        {{ selectedRegistryCard?.description || selectedRegistry.description }}
      </p>
      <div v-if="selectedRegistryCard?.tags?.length" class="aw-rc-tags">
        <span v-for="t in selectedRegistryCard.tags.slice(0, 10)" :key="t" class="aw-rc-tag">{{ t }}</span>
      </div>

      <!-- Full v0.5 card sections (fetched on click) -->
      <template v-if="selectedRegistryCard">
        <div class="aw-rc-sec" v-if="selectedRegistryCard.operator">
          <div class="aw-rc-sec-h">Operator</div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.operator.display_name"><span>Name</span><b>{{ selectedRegistryCard.operator.display_name }}</b></div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.operator.location_label"><span>Location</span><b>{{ selectedRegistryCard.operator.location_label }}</b></div>
          <p class="aw-rc-bio" v-if="selectedRegistryCard.operator.bio">{{ selectedRegistryCard.operator.bio }}</p>
          <div class="aw-rc-linkrow">
            <a v-if="safeExternalUrl(selectedRegistryCard.operator.url)" :href="safeExternalUrl(selectedRegistryCard.operator.url)" target="_blank" rel="noopener">site ↗</a>
            <a v-if="safeExternalUrl(selectedRegistryCard.operator.github_url)" :href="safeExternalUrl(selectedRegistryCard.operator.github_url)" target="_blank" rel="noopener">github ↗</a>
          </div>
        </div>

        <div class="aw-rc-sec" v-if="selectedRegistryCard.fees">
          <div class="aw-rc-sec-h">Fees</div>
          <div class="aw-rc-kv"><span>Intra-registry</span><b>{{ selectedRegistryCard.fees.intra_registry?.base_rate_percent }}%</b></div>
          <div class="aw-rc-kv"><span>Cross-registry</span><b>{{ selectedRegistryCard.fees.cross_registry?.base_rate_percent }}% → {{ selectedRegistryCard.fees.cross_registry?.fee_recipient }}</b></div>
          <div class="aw-rc-kv"><span>Hosting</span><b>{{ selectedRegistryCard.fees.hosting?.enabled ? (selectedRegistryCard.fees.hosting.rate_percent_of_agent_service_fee + '%') : 'FREE (beta)' }}</b></div>
          <div class="aw-rc-kv"><span>Settlement</span><b>{{ selectedRegistryCard.fees.settlement_currency || '—' }}</b></div>
        </div>

        <div class="aw-rc-sec" v-if="registryCapabilityChips(selectedRegistryCard.capabilities).length">
          <div class="aw-rc-sec-h">Capabilities</div>
          <div class="aw-rc-chips">
            <span class="aw-rc-chip" v-for="c in registryCapabilityChips(selectedRegistryCard.capabilities)" :key="c">{{ c }}</span>
          </div>
        </div>

        <!-- Jurisdiction profile: the registry's OWN declaration of the feature scope it
             runs, signed into its card. Rendering it here is the point of publishing it:
             this is where you inspect what another registry claims. Read-only, always. -->
        <div class="aw-rc-sec" v-if="selectedRegistryCard.compliance?.jurisdiction_profile">
          <div class="aw-rc-sec-h">Jurisdiction profile</div>
          <div class="aw-rc-kv"><span>Declared</span><b>{{ selectedRegistryCard.compliance.jurisdiction_profile.name }} (v{{ selectedRegistryCard.compliance.jurisdiction_profile.version }})</b></div>
          <div class="aw-rc-kv">
            <span>Denied</span>
            <b v-if="(selectedRegistryCard.compliance.jurisdiction_profile.features_denied || []).length" style="color:#f59e0b">{{ (selectedRegistryCard.compliance.jurisdiction_profile.features_denied || []).join(', ') }}</b>
            <b v-else>none</b>
          </div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.compliance.jurisdiction_profile.declared_at"><span>Declared at</span><b>{{ String(selectedRegistryCard.compliance.jurisdiction_profile.declared_at).slice(0, 10) }}</b></div>
          <p class="aw-rc-bio">Declared by this registry's operator and signed into its card. It states the
            feature scope the operator runs here; it is not a statement by TheProtocol about that
            operator's law.</p>
        </div>

        <div class="aw-rc-sec" v-if="selectedRegistryCard.commitments">
          <div class="aw-rc-sec-h">Commitments</div>
          <div class="aw-rc-kv"><span>Uptime SLA</span><b>{{ selectedRegistryCard.commitments.uptime_sla_pct }}%</b></div>
          <div class="aw-rc-kv"><span>GDPR</span><b>{{ selectedRegistryCard.commitments.gdpr_compliant ? 'compliant' : '—' }}</b></div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.commitments.data_residency"><span>Data residency</span><b>{{ selectedRegistryCard.commitments.data_residency }}</b></div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.commitments.open_source_license"><span>License</span><b>{{ selectedRegistryCard.commitments.open_source_license }}</b></div>
        </div>

        <div class="aw-rc-sec" v-if="registryCardLinks(selectedRegistryCard.links).length">
          <div class="aw-rc-sec-h">Links</div>
          <div class="aw-rc-linkrow">
            <a v-for="[k, u] in registryCardLinks(selectedRegistryCard.links)" :key="k" :href="safeExternalUrl(u)" target="_blank" rel="noopener">{{ k.replace(/_/g, ' ') }} ↗</a>
          </div>
        </div>

        <div class="aw-rc-sec aw-rc-trust">
          <div class="aw-rc-sec-h">Trust</div>
          <div class="aw-rc-kv"><span>Signature</span>
            <b :style="{ color: selectedRegistry.cardSignatureVerified ? '#00e676' : (selectedRegistryCard.signature ? '#4fc3f7' : '#ffaa00') }">
              {{ selectedRegistry.cardSignatureVerified ? '✓ verified' : (selectedRegistryCard.signature ? 'self-signed' : '⚠ unsigned') }}
            </b>
          </div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.federation?.policy_hash"><span>Policy</span><code>{{ selectedRegistryCard.federation.policy_hash.slice(0, 18) }}…</code></div>
          <div class="aw-rc-kv" v-if="selectedRegistryCard.economic"><span>Supply</span>
            <b :style="{ color: selectedRegistryCard.economic.supply_invariant_status === 'OK' ? '#00e676' : '#ffaa00' }">
              {{ selectedRegistryCard.economic.supply_invariant_status }} · Δ{{ selectedRegistryCard.economic.supply_invariant_delta }}
            </b>
          </div>
        </div>
      </template>

      <!-- Footer: raw JSON demoted to a small link -->
      <div class="aw-rc-foot">
        <span v-if="selectedRegistry.cardEtag" class="aw-rc-etag" :title="selectedRegistry.cardEtag">{{ selectedRegistry.cardEtag.replace('sha256:', '').slice(0, 14) }}…</span>
        <a v-if="selectedRegistry.publicUrl"
           :href="safeExternalUrl(`${selectedRegistry.publicUrl}/.well-known/registry-card.json`)"
           target="_blank" rel="noopener" class="aw-rc-raw">raw JSON ↗</a>
      </div>
    </div>

    <!-- Full Registry Card (shared modal — opens on registry-orb click) -->
    <SovereignRegistryCard v-model:show="showRegCard" :peer-name="regCardPeer" :fallback-name="regCardFallback" />
    <AgentDetailModal v-model:show="showAgentModal" :agent-did="agentModalDid" :embedded="embedded" :agent-name="agentModalName" />

    <!-- ═══ LIVE NETWORK FEED ═══════════════════════════════════════════ -->
    <div v-if="!isLoading && !loadError && !embedded && !cockpit" class="aw-panel aw-feed-panel" :class="{ 'aw-feed-collapsed': !showLiveFeed }">
      <div class="aw-feed-title" @click="showLiveFeed = !showLiveFeed" style="cursor:pointer;user-select:none">
        <span class="aw-feed-live-dot"></span> LIVE FEED
        <!-- Frame A/B connection pills only render when the feed is expanded.
             Their purpose is telling the viewer which sovereign frame the
             events below came from; moot when the event list is collapsed. -->
        <!-- §FEDEVENTS-6: a single-frame deployment shows ONE local chip — B/C
             don't exist there, and "A" would misname its own stream. -->
        <span v-if="showLiveFeed" class="aw-feed-frame-status" :title="esWsConnected ? (multiFrame ? 'Frame A connected' : 'Local stream connected') : (multiFrame ? 'Frame A offline' : 'Local stream offline')">
          <span class="aw-feed-frame aw-feed-frame-A" :class="{ 'aw-feed-frame-off': !esWsConnected }">{{ multiFrame ? 'A' : '●' }}</span>
        </span>
        <span v-if="showLiveFeed && multiFrame" class="aw-feed-frame-status" :title="esWsBConnected ? 'Frame B connected' : 'Frame B offline'">
          <span class="aw-feed-frame aw-feed-frame-B" :class="{ 'aw-feed-frame-off': !esWsBConnected }">B</span>
        </span>
        <span v-if="showLiveFeed && multiFrame" class="aw-feed-frame-status" :title="esWsCConnected ? 'Frame C (BVT) connected' : 'Frame C offline'">
          <span class="aw-feed-frame aw-feed-frame-C" :class="{ 'aw-feed-frame-off': !esWsCConnected }">C</span>
        </span>
        <span style="margin-left:auto;font-size:10px;opacity:0.5">{{ showLiveFeed ? '▼ CLOSE' : '▶ OPEN' }}</span>
      </div>
      <div v-if="showLiveFeed" class="aw-feed-list">
        <div v-for="evt in feedEvents" :key="evt.id" class="aw-feed-item">
          <span class="aw-feed-type-dot" :style="{ background: evt.color }"></span>
          <span v-if="evt.frame" :class="['aw-feed-frame', 'aw-feed-frame-' + evt.frame]" :title="`Frame ${evt.frame}`">{{ evt.frame }}</span>
          <div class="aw-feed-text">
            <div class="aw-feed-item-title">{{ evt.title }}</div>
            <div class="aw-feed-item-sub">{{ evt.sub }}</div>
          </div>
          <span class="aw-feed-time">{{ formatFeedTime(evt.time) }}</span>
        </div>
      </div>
    </div>

    <!-- ═══ ARC COUNTER ═════════════════════════════════════════════════ -->
    <div v-if="activeArcs.length > 0 && !isLoading && !embedded" class="aw-arc-counter">
      <span class="aw-arc-pulse"></span>
      {{ activeArcs.length }} active signal{{ activeArcs.length !== 1 ? 's' : '' }}
    </div>

    <!-- ═══ STATS BAR ═══════════════════════════════════════════════════ -->
    <div v-if="!isLoading && !loadError && !embedded" class="aw-stats-bar">
      <div class="aw-stat-item"><strong class="aw-stat-num" style="color:var(--nc-primary-bright)">{{ networkStats.totalAgents }}</strong><span class="aw-stat-lbl">agents</span></div>
      <span class="aw-stat-sep">•</span>
      <div class="aw-stat-item"><strong class="aw-stat-num" style="color:#00e676">{{ networkStats.totalRegistries }}</strong><span class="aw-stat-lbl">registries</span></div>
      <span class="aw-stat-sep">•</span>
      <div class="aw-stat-item"><strong class="aw-stat-num" style="color:#ffab40">{{ networkStats.federatedRegistries }}</strong><span class="aw-stat-lbl">federated</span></div>
      <span class="aw-stat-sep">•</span>
      <div class="aw-stat-item"><strong class="aw-stat-num" style="color:#ffd700">{{ networkStats.eliteAgents }}</strong><span class="aw-stat-lbl">elite</span></div>
      <span class="aw-stat-sep">•</span>
      <div class="aw-stat-item">
        <span class="aw-ws-dot" :class="esWsConnected ? 'connected' : 'disconnected'"></span>
        <span class="aw-stat-lbl">{{ esWsConnected ? 'LIVE' : 'OFFLINE' }}</span>
      </div>
    </div>

  </div>
</template>

<style scoped>
.agentworld-container {
  position: relative; width: 100%; height: calc(100vh - 64px);
  background: radial-gradient(ellipse at 40% 30%, #080c18 0%, #040608 50%, #020304 100%);
  overflow: hidden;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}
.agentworld-canvas { width: 100%; height: 100%; }
.aw-attribution {
  position: absolute; left: 8px; bottom: 4px; z-index: 21;
  font-size: 10px; line-height: 1.2; color: rgba(200, 210, 220, 0.5);
  pointer-events: none; user-select: none;
}

/* Embedded: click-to-explore overlay */
.aw-explore-overlay {
  position: absolute; inset: 0; z-index: 20; cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}
.aw-explore-hint {
  padding: 6px 14px; border-radius: 14px;
  background: rgba(0,0,0,0.5); backdrop-filter: blur(8px);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  color: rgba(var(--nc-primary-rgb),0.7); font-size: 0.65rem;
  font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.08em;
  opacity: 0; transition: opacity 0.3s;
  pointer-events: none;
}
.aw-explore-overlay:hover .aw-explore-hint { opacity: 1; }
/* a device with no hover (a phone): the overlay is still a control, so its hint shows without one */
@media (hover: none) { .aw-explore-hint { opacity: 1; } }
.aw-explore-close {
  position: absolute; top: 80px; right: 16px; z-index: 25;
  padding: 6px 14px; border-radius: 12px;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(8px);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  color: rgba(var(--nc-primary-rgb),0.7); font-size: 0.6rem; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.04em;
  transition: all 0.2s;
}
.aw-explore-close:hover { background: rgba(var(--nc-primary-rgb),0.1); color: var(--nc-primary); }

/* Legacy CSS vignette removed — replaced by the toggleable GLSL vignette
   stage in setupPostProcessing(). Keeping a CSS one on top would stack with
   the shader-side effect and darken corners twice. */

/* Hide Cesium default credits */
:deep(.cesium-credit-textContainer),
:deep(.cesium-credit-logoContainer),
:deep(.cesium-credit-expand-link),
:deep(.cesium-viewer-bottom) { display: none !important; }
:deep(.cesium-widget-credits) { display: none !important; }
:deep(.cesium-viewer .cesium-widget-credits) { display: none !important; }

.aw-overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  background: radial-gradient(ellipse at 50% 50%, #080c18 0%, #020304 100%); z-index: 10; }
.loading-content { text-align: center; }
/* Cosmic orbital loader — pulsing core + two counter-rotating rings (replaces
   the flat 1-ring spinner; matches the Universe + Galactic Map loaders). */
.aw-loader { position: relative; width: 72px; height: 72px; margin: 0 auto 18px; }
.aw-loader__core {
  position: absolute; top: 50%; left: 50%; width: 12px; height: 12px; margin: -6px 0 0 -6px;
  border-radius: 50%;
  background: radial-gradient(circle, #fff, var(--nc-primary-bright) 55%, transparent 78%);
  box-shadow: 0 0 18px 3px rgba(var(--nc-primary-rgb),0.65);
  animation: aw-core-pulse 2.2s ease-in-out infinite;
}
.aw-loader__ring { position: absolute; top: 50%; left: 50%; border-radius: 50%; border: 1px solid rgba(var(--nc-primary-rgb),0.3); }
.aw-loader__ring i { position: absolute; top: -3px; left: 50%; width: 5px; height: 5px; margin-left: -2.5px; border-radius: 50%; background: var(--nc-primary-bright); box-shadow: 0 0 8px 1px rgba(var(--nc-primary-rgb),0.9); }
.aw-loader__ring--1 { width: 72px; height: 72px; margin: -36px 0 0 -36px; animation: aw-spin 2.8s linear infinite; }
.aw-loader__ring--2 { width: 46px; height: 46px; margin: -23px 0 0 -23px; border-color: rgba(var(--nc-primary-rgb),0.2); animation: aw-spin 1.9s linear infinite reverse; }
@keyframes aw-spin { to { transform: rotate(360deg); } }
@keyframes aw-core-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.3); opacity: .82; } }
@keyframes spin { to { transform: rotate(360deg); } }
.loading-text { color: rgba(var(--nc-primary-rgb),0.9); font-size: 0.82rem; letter-spacing: 0.18em; margin: 0 0 4px; text-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.3); }
.loading-sub { color: rgba(255,255,255,0.3); font-size: 0.70rem; margin: 0; }

/* ── Panels ── */
.aw-panel { position: absolute; z-index: 2;
  background: rgba(6, 8, 16, 0.92); backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08); border-radius: 14px; padding: 16px;
  color: rgba(255,255,255,0.85);
  box-shadow: 0 8px 40px rgba(0,0,0,0.65), inset 0 1px 0 rgba(var(--nc-primary-rgb),0.04);
  transition: box-shadow 0.3s ease; }
.aw-panel:hover { box-shadow: 0 12px 48px rgba(0,0,0,0.7), inset 0 1px 0 rgba(var(--nc-primary-rgb),0.06), 0 0 1px rgba(var(--nc-primary-rgb),0.15); }
/* command-deck top accent hairline on every panel */
.aw-panel::before { content: ''; position: absolute; top: 0; left: 16px; right: 16px; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.5), transparent); pointer-events: none; }

.aw-controls { top: 16px; left: 16px; width: 208px; max-height: calc(100vh - 120px); overflow-y: auto;
  scrollbar-width: thin; scrollbar-color: rgba(var(--nc-primary-rgb),0.18) transparent; }
/* Collapsed state — shrink to title footprint so it doesn't waste space in
   showcase mode. Padding tightened, width auto-fits the title. */
.aw-controls.aw-panel-collapsed {
  width: auto;
  min-width: 128px;
  padding: 8px 12px;
  overflow: visible;
}
.aw-controls.aw-panel-collapsed .aw-panel-title { margin-bottom: 0; }
.aw-panel-title { font-size: 0.70rem; font-weight: 700; letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb),0.9); margin-bottom: 12px; display: flex; align-items: center; gap: 8px;
  text-shadow: 0 0 14px rgba(var(--nc-primary-rgb),0.3); }
.aw-title-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--nc-primary-bright); box-shadow: 0 0 8px var(--nc-primary-bright);
  animation: title-pulse 2s ease-in-out infinite alternate; flex-shrink: 0; }
@keyframes title-pulse { from { opacity: 0.5; } to { opacity: 1.0; box-shadow: 0 0 14px var(--nc-primary-bright); } }

.aw-search-wrap { margin-bottom: 10px; }
.aw-search { width: 100%; background: rgba(var(--nc-primary-rgb),0.05); border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 6px; padding: 6px 10px; font-size: 0.70rem;
  color: rgba(255,255,255,0.8); font-family: inherit; outline: none; box-sizing: border-box; }
.aw-search::placeholder { color: rgba(255,255,255,0.2); }
/* §WORLDFIND — honest search feedback: says when we widened past the drawn
   sample, and says so plainly when nobody by that name exists here. */
.aw-search-note { margin-top: 4px; font-size: 9.5px; letter-spacing: 0.02em;
  color: rgba(0,210,210,0.7); }
.aw-search:focus { border-color: rgba(var(--nc-primary-rgb),0.4); }

.aw-filter-group { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.aw-filter-label { display: block; font-size: 0.58rem; letter-spacing: 0.10em; color: rgba(var(--nc-primary-rgb),0.45); margin-bottom: 5px; }
.aw-filter-select { width: 100%; background: rgba(var(--nc-primary-rgb),0.05); border: 1px solid rgba(var(--nc-primary-rgb),0.14);
  border-radius: 5px; padding: 5px 8px; font-size: 0.68rem;
  color: rgba(255,255,255,0.7); font-family: inherit; outline: none; cursor: pointer; }
.aw-filter-select:focus { border-color: rgba(var(--nc-primary-rgb),0.35); }

.aw-tier-btns { display: flex; gap: 4px; }
.aw-tier-btn { flex: 1; padding: 4px 0; font-size: 0.62rem; border-radius: 4px; cursor: pointer;
  background: rgba(var(--nc-primary-rgb),0.04); border: 1px solid rgba(var(--nc-primary-rgb),0.10);
  color: rgba(255,255,255,0.4); font-family: inherit; transition: all 0.15s; }
.aw-tier-btn.active { background: rgba(var(--nc-primary-rgb),0.12); border-color: rgba(var(--nc-primary-rgb),0.35); color: rgba(var(--nc-primary-rgb),0.9); }
.aw-tier-btn:hover:not(.active) { border-color: rgba(var(--nc-primary-rgb),0.22); color: rgba(255,255,255,0.6); }

.aw-controls-group { display: flex; flex-direction: column; gap: 6px;
  margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.aw-toggle { display: flex; align-items: center; gap: 7px; cursor: pointer; }
.aw-toggle input[type="checkbox"] { accent-color: rgba(var(--nc-primary-rgb),0.9); width: 12px; height: 12px; }
.aw-toggle-label { font-size: 0.68rem; color: rgba(255,255,255,0.45); }
.aw-demo-btn { font-size: 0.62rem; padding: 3px 10px; border: 1px solid rgba(255,215,0,0.3); border-radius: 4px;
  background: transparent; color: rgba(255,215,0,0.6); cursor: pointer; transition: all 0.2s; letter-spacing: 0.05em; font-weight: 600; }
.aw-demo-btn:hover { border-color: rgba(255,215,0,0.6); color: rgba(255,215,0,0.9); }
.aw-demo-btn.active { background: rgba(255,215,0,0.15); border-color: rgba(255,215,0,0.7); color: #ffd700; animation: demoPulse 1s infinite; }
@keyframes demoPulse { 0%,100% { box-shadow: 0 0 4px rgba(255,215,0,0.2); } 50% { box-shadow: 0 0 12px rgba(255,215,0,0.5); } }

.aw-interact-guide { display: flex; flex-direction: column; gap: 3px; font-size: 0.64rem; color: rgba(255,255,255,0.28);
  margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.aw-interact-guide kbd { display: inline-block; padding: 1px 5px; background: rgba(255,255,255,0.06);
  border-radius: 3px; font-size: 0.60rem; margin-right: 4px; font-family: inherit; }

.aw-legend { font-size: 0.66rem; }
.aw-legend-title { font-size: 0.58rem; letter-spacing: 0.10em; color: rgba(var(--nc-primary-rgb),0.45); margin-bottom: 4px; }
.aw-legend-row { display: flex; align-items: center; gap: 7px; color: rgba(255,255,255,0.4); margin-bottom: 3px; }
.aw-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.aw-ring { display: inline-block; width: 11px; height: 11px; border-radius: 50%; flex-shrink: 0;
  border: 2px solid #ffc400; background: transparent; box-shadow: 0 0 6px #ffc40066, inset 0 0 4px #ffc40044; }
.aw-heat-chip { background: radial-gradient(circle, rgba(0,229,255,0.95) 0%, rgba(0,229,255,0.35) 45%, transparent 75%);
  width: 13px; height: 13px; box-shadow: 0 0 8px rgba(0,229,255,0.7); }
.aw-pulse { animation: awLegendPulse 1.1s ease-in-out infinite; }
@keyframes awLegendPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .aw-pulse { animation: none; } }
.aw-beam { display: inline-block; width: 18px; height: 3px; flex-shrink: 0; border-radius: 1px;
  box-shadow: 0 0 8px rgba(255,215,0,0.55); }
.aw-legend-note { font-style: italic; font-size: 0.58rem; color: rgba(255,255,255,0.26);
  padding-left: 16px; margin-top: 2px; }

.aw-signal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 8px; }
.aw-toggle-compact { display: flex; align-items: center; gap: 4px; cursor: pointer; font-size: 0.60rem; color: rgba(255,255,255,0.40); padding: 2px 0; }
.aw-toggle-compact:hover { color: rgba(255,255,255,0.75); }
.aw-toggle-compact input[type="checkbox"] { accent-color: rgba(var(--nc-primary-rgb),0.9); width: 10px; height: 10px; margin: 0; }
.aw-arc-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

/* ── Direction-D VISUAL block (quality preset + per-feature toggles) ── */
.aw-visual-preset-row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.aw-visual-preset-select { flex: 1; font-size: 0.65rem; padding: 3px 6px; }

/* ── Selected Agent Panel ── */
.aw-agent-panel { top: 16px; left: 240px; width: 310px; padding: 20px; }
.aw-ap-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; gap: 10px; }
.aw-ap-header-left { flex: 1; min-width: 0; }
.aw-ap-name-row { display: flex; align-items: center; gap: 8px; }
.aw-ap-tier-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.aw-ap-name { font-size: 1.05rem; font-weight: 600; color: rgba(255,255,255,0.95); line-height: 1.2; margin: 0; }
.aw-ap-did { font-size: 0.58rem; color: rgba(255,255,255,0.18); font-family: 'IBM Plex Mono', monospace; margin-top: 4px; word-break: break-all; line-height: 1.4; }
.aw-close-btn { background: none; border: none; color: rgba(255,255,255,0.28); cursor: pointer; font-size: 1rem; padding: 2px 4px; flex-shrink: 0; transition: color 0.15s; }
.aw-close-btn:hover { color: rgba(255,255,255,0.8); }

.aw-ap-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.aw-ap-cell { display: flex; flex-direction: column; gap: 2px; }
.aw-ap-cell-label { font-size: 0.60rem; color: rgba(255,255,255,0.30); letter-spacing: 0.03em; }
.aw-ap-cell-value { font-size: 0.78rem; font-weight: 500; color: rgba(255,255,255,0.8); }
.aw-ap-big { font-size: 1.15rem; font-weight: 700; text-shadow: 0 0 10px currentColor; }

.aw-synced-badge { display: inline-block; padding: 1px 5px; background: rgba(255,171,64,0.15);
  border: 1px solid rgba(255,171,64,0.45); color: #ffab40; border-radius: 3px;
  font-size: 0.52rem; font-weight: 700; letter-spacing: 0.05em; margin-left: 6px; vertical-align: middle; }
.aw-status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; }
.aw-status-dot.active { background: #00e676; box-shadow: 0 0 6px #00e67666; }
.aw-status-dot.inactive { background: #607d8b; }

.aw-ap-coords { font-size: 0.58rem; color: rgba(255,255,255,0.18); margin-bottom: 12px;
  padding-bottom: 10px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.aw-ap-caps { margin-bottom: 14px; }
.aw-ap-caps-wrap { display: flex; flex-wrap: wrap; gap: 4px; }
.aw-cap-tag { padding: 3px 8px; background: rgba(var(--nc-primary-rgb),0.06); border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 4px; font-size: 0.62rem; color: rgba(var(--nc-primary-rgb),0.6); transition: border-color 0.15s; }
.aw-cap-tag:hover { border-color: rgba(var(--nc-primary-rgb),0.30); }

.aw-profile-btn { width: 100%; padding: 10px; background: rgba(var(--nc-primary-rgb),0.06); border: 1px solid rgba(var(--nc-primary-rgb),0.18);
  border-radius: 8px; color: rgba(var(--nc-primary-rgb),0.9); font-size: 0.74rem; font-family: inherit;
  cursor: pointer; transition: all 0.2s; text-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.15); }
.aw-profile-btn:hover { background: rgba(var(--nc-primary-rgb),0.12); border-color: rgba(var(--nc-primary-rgb),0.35); box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.08); }

/* ── Live Feed Panel ── */
.aw-feed-panel { bottom: 52px; right: 16px; width: 268px; max-height: calc(100vh - 160px);
  overflow: hidden; padding: 12px 14px; display: flex; flex-direction: column; }
.aw-feed-panel.aw-feed-collapsed { max-height: 40px; width: 160px; }
.aw-feed-title { font-size: 0.60rem; font-weight: 700; letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb),0.6); margin-bottom: 9px; display: flex; align-items: center; gap: 7px; }
.aw-feed-live-dot { width: 6px; height: 6px; border-radius: 50%; background: rgba(0,230,118,0.9);
  box-shadow: 0 0 5px rgba(0,230,118,0.7); animation: feed-pulse 1.5s ease-in-out infinite alternate; }
@keyframes feed-pulse { from { opacity: 0.5; } to { opacity: 1; } }
.aw-feed-list { display: flex; flex-direction: column; gap: 6px; overflow-y: auto; flex: 1;
  scrollbar-width: thin; scrollbar-color: rgba(var(--nc-primary-rgb),0.18) transparent; }
.aw-feed-list::-webkit-scrollbar { width: 4px; }
.aw-feed-list::-webkit-scrollbar-track { background: transparent; }
.aw-feed-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb),0.18); border-radius: 2px; }
.aw-feed-item { display: flex; align-items: flex-start; gap: 8px; padding: 5px 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.05); animation: feed-slide-in 0.35s ease-out; }
.aw-feed-item:last-child { border-bottom: none; }
@keyframes feed-slide-in { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: translateX(0); } }
.aw-feed-type-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.aw-feed-text { flex: 1; min-width: 0; }
.aw-feed-item-title { font-size: 0.68rem; color: rgba(255,255,255,0.75); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aw-feed-item-sub { font-size: 0.60rem; color: rgba(255,255,255,0.3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.aw-feed-time { font-size: 0.58rem; color: rgba(255,255,255,0.20); white-space: nowrap; flex-shrink: 0; margin-top: 2px; }
/* Frame A/B badge — small monogram pill on each feed event so the source
   sovereign frame is unmistakable at a glance. Frame A uses the network's
   primary cyan; Frame B uses the magenta family it identifies with. */
.aw-feed-frame {
  display: inline-flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.56rem; font-weight: 700; letter-spacing: 0.04em;
  width: 14px; height: 14px; border-radius: 3px;
  flex-shrink: 0; margin-top: 1px;
  color: #060a12;
}
.aw-feed-frame-A { background: var(--nc-primary-bright); box-shadow: 0 0 4px rgba(0,229,255,0.45); }
.aw-feed-frame-B { background: #ff4fb4;                  box-shadow: 0 0 4px rgba(255,79,180,0.45); }
.aw-feed-frame-C { background: #ffc400;                  box-shadow: 0 0 4px rgba(255,196,0,0.45); }
.aw-feed-frame-off { opacity: 0.25; box-shadow: none; }
.aw-feed-frame-status { display: inline-flex; align-items: center; margin-left: 6px; }

.aw-arc-pulse { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: var(--nc-primary-bright);
  box-shadow: 0 0 6px var(--nc-primary-bright); animation: arc-pulse 1s ease-in-out infinite alternate; }
@keyframes arc-pulse { from { opacity: 0.4; } to { opacity: 1; } }

.aw-arc-counter { position: absolute; top: 16px; right: 300px; z-index: 2;
  background: rgba(6,8,16,0.90); border: 1px solid rgba(0,229,255,0.10);
  border-radius: 20px; padding: 5px 14px; font-size: 0.66rem; color: rgba(0,229,255,0.75);
  display: flex; align-items: center; gap: 7px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.4), 0 0 1px rgba(0,229,255,0.15); }

.aw-stats-bar { position: absolute; bottom: 16px; left: 50%; transform: translateX(-50%); z-index: 2;
  background: rgba(6,8,16,0.92); backdrop-filter: blur(18px) saturate(1.2);
  border: 1px solid rgba(var(--nc-primary-rgb),0.06); border-radius: 28px;
  padding: 10px 28px; display: flex; align-items: center; gap: 18px; font-size: 0.68rem;
  box-shadow: 0 8px 32px rgba(0,0,0,0.55), inset 0 1px 0 rgba(var(--nc-primary-rgb),0.04); }
.aw-stat-item { display: flex; align-items: center; gap: 5px; }
.aw-stat-num { font-weight: 700; font-size: 0.84rem; text-shadow: 0 0 8px currentColor; }
.aw-stat-lbl { color: rgba(255,255,255,0.28); letter-spacing: 0.02em; }
.aw-stat-sep { color: rgba(255,255,255,0.06); }
.aw-ws-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.aw-ws-dot.connected { background: #00e676; box-shadow: 0 0 6px #00e676, 0 0 12px rgba(0,230,118,0.3);
  animation: ws-glow 2s ease-in-out infinite alternate; }
.aw-ws-dot.disconnected { background: #607d8b; }
@keyframes ws-glow { from { box-shadow: 0 0 4px #00e676; } to { box-shadow: 0 0 10px #00e676, 0 0 20px rgba(0,230,118,0.2); } }

.aw-agent-panel { animation: panel-open 0.3s ease-out; }
@keyframes panel-open { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
</style>

<!-- Non-scoped: Teleported tooltip styles -->
<style>
.aw-galactic-tooltip { position: fixed; pointer-events: none; z-index: 9999;
  background: rgba(8, 10, 20, 0.92); backdrop-filter: blur(12px);
  border: 1px solid rgba(100, 140, 255, 0.2); border-radius: 10px; padding: 10px 14px;
  min-width: 200px; max-width: 320px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 20px rgba(50, 100, 255, 0.08);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px; line-height: 1.4; color: #e0e0e0; }
.aw-galactic-tooltip .gtt-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.aw-galactic-tooltip .gtt-type-badge { font-size: 14px; }
.aw-galactic-tooltip .gtt-type-badge.agent { color: #4fc3f7; }
.aw-galactic-tooltip .gtt-type-badge.registry { color: #00e676; }
.aw-galactic-tooltip .gtt-name { font-weight: 600; font-size: 13px; color: #e8eaf6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }

/* §28 polish (2026-05-15) — Avatar row in agent hover tooltip. */
.aw-galactic-tooltip .gtt-avatar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.aw-galactic-tooltip .gtt-avatar { flex-shrink: 0; }
.aw-galactic-tooltip .gtt-avatar-placeholder {
  width: 36px; height: 36px; border-radius: 50%;
  background: radial-gradient(circle at 50% 50%, rgba(79,195,247,0.18), rgba(10,13,22,0.85));
  border: 1px solid rgba(79,195,247,0.35);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  font-family: var(--mono, ui-monospace, monospace);
}
/* Registry Card v0.3.1 — selected-registry panel orb avatar (mirrors agent panel). */
.aw-agent-panel .aw-ap-orb-avatar {
  width: 56px; height: 56px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  font-family: var(--mono, ui-monospace, monospace);
}
.aw-agent-panel .aw-ap-header-left { gap: 12px; }
.aw-galactic-tooltip .gtt-name-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.aw-galactic-tooltip .gtt-name-wrap .gtt-name { max-width: 200px; }
.aw-galactic-tooltip .gtt-detail { margin-bottom: 6px; }
.aw-galactic-tooltip .gtt-did { font-size: 10px; color: #7986cb; font-family: 'SF Mono', 'Fira Code', monospace; }
.aw-galactic-tooltip .gtt-synced-badge { display: inline-block; padding: 1px 6px; background: rgba(255,171,64,0.2); border: 1px solid rgba(255,171,64,0.5); border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; color: #ffab40; margin-left: auto; }
.aw-galactic-tooltip .gtt-status-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; margin-left: auto; }
.aw-galactic-tooltip .gtt-status-badge.active { background: rgba(0,230,118,0.2); border: 1px solid rgba(0,230,118,0.5); color: #00e676; }
.aw-galactic-tooltip .gtt-status-badge.pending { background: rgba(255,179,0,0.2); border: 1px solid rgba(255,179,0,0.5); color: #ffb300; }
.aw-galactic-tooltip .gtt-status-badge.inactive { background: rgba(255,82,82,0.2); border: 1px solid rgba(255,82,82,0.5); color: #ff5252; }
.aw-galactic-tooltip .gtt-hop-badge { display: inline-block; padding: 1px 6px; background: rgba(0,0,0,0.3);
  border: 1px solid; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; margin-left: 4px; }
.aw-galactic-tooltip .gtt-stats { display: flex; gap: 16px; }
.aw-galactic-tooltip .gtt-stat { display: flex; flex-direction: column; gap: 1px; }
.aw-galactic-tooltip .gtt-stat-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: #78909c; }
.aw-galactic-tooltip .gtt-stat-value { font-size: 13px; font-weight: 700; color: #e0e0e0; }
.aw-galactic-tooltip .gtt-stat-value.elite { color: #ffd700; }
.aw-galactic-tooltip .gtt-stat-value.great { color: var(--nc-primary-bright); }
.aw-galactic-tooltip .gtt-stat-value.good { color: #4fc3f7; }
.aw-galactic-tooltip .gtt-stat-value.low { color: #78909c; }
.aw-galactic-tooltip .gtt-caps { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.aw-galactic-tooltip .gtt-cap { font-size: 9px; padding: 1px 6px; background: rgba(79,195,247,0.12); border: 1px solid rgba(79,195,247,0.3); border-radius: 3px; color: #4fc3f7; }
.aw-galactic-tooltip .gtt-origin { display: flex; align-items: center; gap: 4px; margin-top: 4px; }
.aw-galactic-tooltip .gtt-fx-pill { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; letter-spacing: 0.4px; color: #ffd54f; background: rgba(255,213,79,0.12); border: 1px solid rgba(255,213,79,0.45); }
.aw-galactic-tooltip .gtt-desc { font-size: 11px; color: #90a4ae; line-height: 1.4; margin-bottom: 6px; max-width: 280px; }
.aw-galactic-tooltip .gtt-url { font-size: 11px; color: #4fc3f7; font-family: 'SF Mono', 'Fira Code', monospace; }
.aw-galactic-tooltip .gtt-auth { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.aw-galactic-tooltip .gtt-auth-tag { font-size: 9px; padding: 1px 5px; background: rgba(171,71,188,0.15); border: 1px solid rgba(171,71,188,0.35); border-radius: 3px; color: #ce93d8; text-transform: capitalize; }
.aw-galactic-tooltip .gtt-sync { display: flex; align-items: center; gap: 4px; margin-top: 4px; }

/* ── Registry Card v0.5 — hover tooltip refinements ───────────────────── */
/* NOTE: keep position:fixed from the base rule above — a teleported tooltip
   must stay out of document flow. overflow:hidden clips the gtt-accent bar
   (the fixed tooltip is already a containing block for the absolute accent),
   so do NOT re-declare position here or the label drops into body flow and
   its left offset widens the document → horizontal scrollbar → the Cesium
   canvas reflows narrower (the "canvas shrinks / gap on the right" bug). */
.aw-galactic-tooltip { overflow: hidden; }
.aw-galactic-tooltip .gtt-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; opacity: 0.9; }
.aw-galactic-tooltip .gtt-fee-rail { background: rgba(255,255,255,0.03); border-radius: 6px; padding: 5px 8px; margin-top: 5px; }
.aw-galactic-tooltip .gtt-hint { margin-top: 7px; font-size: 9.5px; letter-spacing: 0.04em; color: rgba(255,255,255,0.45); text-transform: uppercase; }

/* ── Registry Card v0.5 — rich click panel ────────────────────────────── */
.aw-panel.aw-rc-panel { max-height: 82vh; overflow-y: auto; }
.aw-rc-loading { font-size: 0.78rem; color: #4fc3f7; padding: 8px 0; opacity: 0.85; }
.aw-rc-desc { font-size: 0.8rem; color: rgba(255,255,255,0.72); line-height: 1.45; margin: 10px 0 6px; }
.aw-rc-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 8px; }
.aw-rc-tag { font-size: 0.62rem; letter-spacing: 0.03em; padding: 2px 7px; border-radius: 999px; background: rgba(79,195,247,0.12); border: 1px solid rgba(79,195,247,0.28); color: #9ddcff; font-family: 'SF Mono','Fira Code',monospace; }
.aw-rc-sec { margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.07); }
.aw-rc-sec-h { font-size: 0.6rem; letter-spacing: 0.16em; text-transform: uppercase; color: rgba(255,255,255,0.5); margin-bottom: 7px; font-weight: 600; }
.aw-rc-kv { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; font-size: 0.76rem; padding: 2.5px 0; }
.aw-rc-kv > span { color: rgba(255,255,255,0.5); }
.aw-rc-kv > b { color: rgba(255,255,255,0.9); font-weight: 600; text-align: right; }
.aw-rc-kv code { font-family: 'SF Mono','Fira Code',monospace; font-size: 0.7rem; color: #9ddcff; background: rgba(0,0,0,0.35); padding: 1px 5px; border-radius: 3px; }
.aw-rc-bio { font-size: 0.76rem; color: rgba(255,255,255,0.68); line-height: 1.45; margin: 6px 0 4px; }
.aw-rc-linkrow { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 4px; }
.aw-rc-linkrow a { font-size: 0.72rem; color: #4fc3f7; text-decoration: none; border-bottom: 1px dotted rgba(79,195,247,0.4); }
.aw-rc-linkrow a:hover { border-bottom-style: solid; }
.aw-rc-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.aw-rc-chip { font-size: 0.64rem; padding: 2px 8px; border-radius: 999px; background: rgba(168,85,247,0.12); border: 1px solid rgba(168,85,247,0.3); color: #d4b3ff; font-family: 'SF Mono','Fira Code',monospace; }
.aw-rc-trust .aw-rc-kv > b { font-weight: 700; }
.aw-rc-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.07); }
.aw-rc-etag { font-family: 'SF Mono','Fira Code',monospace; font-size: 0.64rem; color: rgba(255,255,255,0.4); }
.aw-rc-raw { font-size: 0.68rem; color: rgba(255,255,255,0.55); text-decoration: none; border: 1px solid rgba(255,255,255,0.15); padding: 3px 9px; border-radius: 4px; }
.aw-rc-raw:hover { color: #fff; border-color: rgba(255,255,255,0.35); }
</style>
