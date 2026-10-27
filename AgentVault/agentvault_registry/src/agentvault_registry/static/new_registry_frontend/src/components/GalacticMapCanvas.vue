<script setup lang="ts">
import Icon from '@/components/Icon.vue'
/**
 * GalacticMapCanvas.vue — AAA Galactic Map Visualization
 * OWL23 Phase 1: Complete Three.js rewrite
 * 
 * Renders the AgentVault sovereign network as an interactive 3D galaxy:
 * - Registries = large glowing station nodes
 * - Agents = instanced spheres (color=reputation, size=balance)
 * - Federation links = animated beams between registries
 * - Starfield background with depth
 * - OrbitControls for full camera interaction
 * - CSS2D labels for hover/selected nodes
 * - UnrealBloomPass for glow on high-rep agents
 */
import { ref, onMounted, onUnmounted, watch, computed, nextTick } from 'vue'
import { useAlive } from '@/composables/useAlive'
import TopologyHoverLabel from '@/components/TopologyHoverLabel.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import * as THREE from 'three'
import { laneBrightness, LANE_DECAY_MS } from '@/services/bridge/lane'
import { routeAround } from '@/services/bridge/arcRoute'
import { amountGrader } from '@/services/bridge/amountGrade'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'
import { useLogger } from '@/composables/useLogger'
import { useCurrency } from '@/composables/useCurrency'

const log = useLogger('GalacticMap')

// ─── Types ───────────────────────────────────────────────────────
import { FRAMES } from '@/config/frames'

export interface MapRegistry {
  id: string
  name: string                 // load-bearing slug (resolution key)
  displayName?: string | null  // §2026-06-14 operator-editable card display name (UI label)
  url: string
  publicUrl: string           // Public-facing URL (e.g., registry.theprotocol.cloud)
  status: string
  agentCount: number
  health: number
  federationLinks: string[]
  hopDepth?: number
  frame?: string              // Frame cluster ID: 'local' or remote frame name
  // Federation role from /trusted-registries peer rows: 'local' | 'frame'
  // (sovereign mainframe) | 'cloud_operator' | 'direct_peer' | 'discovered'.
  // Only 'local' + 'frame' nodes are mainframes → gate the golden inter-frame bridge.
  peerType?: string
  description?: string
  lastSyncedAt?: string | null
  adminContact?: string
  protocolVersion?: string
  trustDomain?: string
  authMethods?: string[]
  // Registry Card v0.3/0.4 slice (surfaced for the rich hover card — parity
  // with AgentWorld). Hydrated in GalacticMap.vue from /public/topology.
  visual?: {
    iconUrl?: string | null; orbColor?: string | null; orbGlowColor?: string | null
    sovereignVariant?: string | null; flareEncirclementVariant?: string | null
    flareEncirclementOverlay?: string | null
  } | null
  fees?: {
    intraRegistry?: number | null; crossRegistry?: number | null
    hostingEnabled?: boolean | null; hostingRate?: number | null; settlementCurrency?: string | null
  } | null
  cardEtag?: string | null
  cardSignatureVerified?: boolean | null
}

export interface MapAgent {
  did: string
  name: string
  description: string
  status: string
  registryId: string
  reputation: number
  reputationTier: string      // 'standard' | 'trusted' | 'elite' etc.
  totalTransactions: number
  liquidBalance: number
  stakedBalance: number
  capabilities: string[]
  isVerified: boolean
  isSynced: boolean  // OWL24: true if agent card was synced from another registry
  createdAt: string
  originRegistry?: string     // Human-readable origin name
  frame?: string              // Inherited from registry's frame
  /**
   * §BRIDGE R5 — a COUNTERPARTY star: someone the viewer's agents are actually
   * transacting with, drawn dim so an arc lands on a body instead of on a bare
   * registry glyph (the Commander: "maybe unhide the agents that we are
   * interacting with ... the agent could show up with opacity").
   * It is not the viewer's agent and never pretends to be.
   */
  dim?: boolean
}

export interface NetworkStats {
  totalRegistries: number
  activeRegistries: number
  totalAgents: number
  networkHealth: number
  lastGlobalSync: string | null
}

interface Props {
  registries?: MapRegistry[]
  agents?: MapAgent[]
  networkStats?: NetworkStats | null
  selectedAgentDid?: string | null
  highlightCapability?: string | null
  searchQuery?: string
  topologyVersion?: number
  showLabels?: boolean
  embedded?: boolean   // IRONHAND Theatre: agent set is intentionally controlled (hide/solo) → allow empties + react to membership swaps
  // GCC P11+ restart-visibility: registry node ids that are mid-restart. Their orbs
  // pulse translucent (a calm "busy until healthy" blink) — PURELY a material-opacity
  // effect in the animate loop; topology / picking / positions are never touched.
  busyRegistryIds?: string[]
  /**
   * §BRIDGE #B3 — render profile. PURELY ADDITIVE: `'full'` is byte-identical to
   * the pre-BRIDGE behaviour, so `/galactic-map` and `/galactic-command` are
   * untouched. `'mission'` is the Mission Control stage: it trades the
   * postprocessing stack for headroom (a landing page must not run an
   * EffectComposer), clamps DPR, halves the ambient frame rate and turns on the
   * verb layer that draws live ledger events.
   */
  mode?: 'full' | 'mission'
  /**
   * §BRIDGE R1.5 — DID -> registry (display name or slug), for arc endpoints.
   *
   * Real transfer payloads name their parties as DIDs, never as registry slugs,
   * so before this map every arc fell through to the FRAME CENTROID: the stage
   * drew a handful of generic curves between three blobs instead of traffic
   * between actual registries. Sourced from `/agents/locations/`, which the map
   * pipeline already loads — no new fetch, no second source of truth.
   */
  didRegistry?: Record<string, string>
  /**
   * DID -> frame key, from `/agents/locations/`'s `trust_domain`.
   *
   * MEASURED 2026-08-19: of the twelve busiest parties on frame-c, exactly ONE
   * appears in the locations payload with anything usable, and 1,886 of its
   * 6,000 rows carry no `origin_registry` at all — but EVERY row carries
   * `trust_domain`. Registry precision where we have it, frame precision where
   * we do not, and never a fabricated midpoint.
   */
  didFrame?: Record<string, string>
  /**
   * §BRIDGE R7 — THE POPULATION, as density rather than as objects.
   *
   * Strategy §3: "the viewer's agents are the only individually bright, labeled
   * entities; the galaxy is dimmed density." Mission mode draws individual
   * stars only for the viewer's own agents and the counterparties they trade
   * with — that cap exists because one sprite per agent once blocked the
   * renderer for minutes, and making the fleet list complete quietly undid it
   * a second time (R1.6).
   *
   * So the wider population arrives here as POINTS: one BufferGeometry, one
   * draw call, no picking, no labels, no per-agent objects. Ten thousand of
   * them cost what one sprite costs. This is the honest way to make the map
   * populated — the galaxy really is that full, and now it looks it.
   */
  densityAgents?: MapAgent[]
}

const props = withDefaults(defineProps<Props>(), {
  registries: () => [],
  agents: () => [],
  networkStats: null,
  topologyVersion: 0,
  selectedAgentDid: null,
  showLabels: false,
  embedded: false,
  highlightCapability: null,
  searchQuery: '',
  busyRegistryIds: () => [],
  mode: 'full',
  didRegistry: () => ({}),
  didFrame: () => ({}),
  densityAgents: () => [],
})
/** Cheap non-reactive mirror; read inside the animate loop's hot path. */
const IS_MISSION = props.mode === 'mission'
// Plain Set mirror of busyRegistryIds for O(1) lookup inside the hot animate loop
// (avoids reactive reads per-frame). Rebuilt only when the prop actually changes.
let busyIdSet: Set<string> = new Set()
watch(() => props.busyRegistryIds, (ids) => {
  busyIdSet = new Set((ids || []).map(String))
}, { immediate: true, deep: true })
/** Lowercased DID -> registry hint. Mirror, so verb spawn never reads reactively. */
let didRegistryMap: Map<string, string> = new Map()
watch(() => props.didRegistry, (m) => {
  const next = new Map<string, string>()
  for (const k in (m || {})) { const v = (m as any)[k]; if (k && v) next.set(k.toLowerCase(), String(v)) }
  didRegistryMap = next
}, { immediate: true, deep: false })
watch(() => (props.densityAgents || []).length, () => {
  // The population arrives after first paint; rebuild once it does.
  if (IS_MISSION && scene) buildDensity()
})

/** Lowercased DID -> frame key. Same discipline. */
let didFrameMap: Map<string, string> = new Map()
watch(() => props.didFrame, (m) => {
  const next = new Map<string, string>()
  for (const k in (m || {})) { const v = (m as any)[k]; if (k && v) next.set(k.toLowerCase(), String(v)) }
  didFrameMap = next
}, { immediate: true, deep: false })

/** frame key -> trust domain, and currency -> frame key. ONE source: FRAMES, the frame manifest (§FEFRAME W2).
 *  Read at use, never at import: the manifest lands after this module loads. */
function frameDomainMap(): Map<string, string> {
  return new Map(FRAMES.map(f => [f.key.toUpperCase(), (f.trustDomain || '').toLowerCase()]))
}
function currencyFrameMap(): Map<string, string> {
  return new Map(FRAMES.filter(f => f.currency).map(f => [String(f.currency).toLowerCase(), f.key.toUpperCase()]))
}

/** A frame hint (key, or a trust domain) -> frame key. */
function frameKeyOf(hint: string | null): string | null {
  if (!hint) return null
  const h = hint.trim().toLowerCase()
  const bare = h.replace(/^frame[-_]?/, '')
  if (/^[a-z]$/.test(bare)) return bare.toUpperCase()
  for (const [k, dom] of frameDomainMap()) if (dom && (dom === h || k.toLowerCase() === h)) return k
  return null
}

/**
 * SYSTEM ACCOUNTS ARE REAL PLACES.
 *
 * The single busiest endpoint on frame-c is `did:theprotocol:agora-gateway-bvt`
 * (9,135 of 40,000 sampled endpoints), followed by `teg:system:fee_collector`
 * (2,742) and the other two gateways. None of them is an agent, so none of them
 * is in `/agents/locations/`, so every one of them used to fall through to the
 * frame centroid — an averaged point with nothing at it. Roughly a third of all
 * traffic therefore flew out of, or into, empty space. That is exactly what the
 * Commander reported.
 *
 * A gateway belongs to the frame whose CURRENCY it settles (derived from the
 * frame manifest, not hardcoded); a `teg:system:*` account belongs to the frame
 * delivering the event. Both genuinely live at that frame's registry, so
 * anchoring them there is accuracy, not decoration.
 */
function systemAccountFrame(hint: string, deliveringFrame: string | null): string | null {
  const h = hint.toLowerCase()
  const gw = h.match(/agora[-_]gateway[-_]([a-z]+)/)
  if (gw) { const k = currencyFrameMap().get(gw[1]); if (k) return k }
  if (h.startsWith('teg:system') || h.includes('teg_system') || h.includes('fee_collector')) {
    return frameKeyOf(deliveringFrame)
  }
  return null
}

/**
 * A frame's ANCHOR is its mainframe registry node — never the centroid of its
 * systems. "Somewhere in Frame B" was rendered as the average of Frame B's
 * positions, which is a point in the void; the frame's registry is a place that
 * actually exists and is where these accounts actually are.
 */
function frameAnchorPosition(frameHint: string | null): THREE.Vector3 | null {
  const key = frameKeyOf(frameHint)
  if (!key) return null
  const domain = frameDomainMap().get(key)
  // 1) the mainframe node for that trust domain — exact.
  for (const reg of props.registries) {
    const pt = (reg.peerType || '').toLowerCase()
    if (pt !== 'local' && pt !== 'frame') continue
    if (domain && (reg.trustDomain || '').toLowerCase() === domain) {
      const p = registryPositions.get(reg.id)
      if (p) return p
    }
  }
  // 2) any node that declares that trust domain.
  for (const reg of props.registries) {
    if (domain && (reg.trustDomain || '').toLowerCase() === domain) {
      const p = registryPositions.get(reg.id)
      if (p) return p
    }
  }
  // 3) any node tagged with that frame. Still a REAL node, never an average.
  for (const reg of props.registries) {
    if ((reg.frame || '').toUpperCase().includes(key)) {
      const p = registryPositions.get(reg.id)
      if (p) return p
    }
  }
  return null
}
const { localCurrency } = useCurrency()   // FX: tooltip balances in the viewer's currency

// Adapt the canvas tooltipData → the shared TopologyHoverLabel `entity` shape.
const labelEntity = computed<any>(() => {
  const d: any = tooltipData.value
  if (!d) return null
  if (d.type === 'agent') return {
    type: 'agent', name: d.name, did: d.did, description: d.description,
    tierLabel: (d.reputationTier || 'standard').toUpperCase(), tierClass: getTierClass(d.reputationTier || 'standard'),
    reputation: d.reputation, totalTransactions: d.totalTransactions,
    isSynced: d.isSynced, capabilities: d.capabilities, originRegistry: d.originRegistry,
    balance: d.balance, liquidBalance: d.liquidBalance, stakedBalance: d.stakedBalance,
    currency: localCurrency.value,
  }
  return {
    type: 'registry', name: d.name, description: d.registryDescription,
    agentCount: d.agentCount, health: d.health, status: d.status,
    trustDomain: d.trustDomain, authMethods: d.authMethods,
  }
})

const emit = defineEmits<{
  'agent-click': [agent: MapAgent]
  /** §BRIDGE R13 #2 — right-click: target this agent, open nothing. */
  'agent-context': [agent: MapAgent]
  'agent-hover': [agent: MapAgent | null]
  'registry-click': [registry: MapRegistry]
  'registry-hover': [registry: MapRegistry | null]
  /** #B12 — a moving light was clicked. Carries the descriptor that drew it. */
  'verb-click': [descriptor: any]
}>()

// ─── Refs ────────────────────────────────────────────────────────
const containerRef = ref<HTMLDivElement>()
const tooltipRef = ref<HTMLDivElement>()
const tooltipVisible = ref(false)
const tooltipData = ref<{
  name: string; type: string;
  // Agent fields
  did?: string; reputation?: number; reputationTier?: string;
  totalTransactions?: number; balance?: number; liquidBalance?: number;
  stakedBalance?: number; isSynced?: boolean; capabilities?: string[];
  description?: string; originRegistry?: string; createdAt?: string;
  // Registry fields
  url?: string; publicUrl?: string; health?: number; agentCount?: number;
  status?: string; lastSyncedAt?: string; trustDomain?: string;
  authMethods?: string[]; protocolVersion?: string; registryDescription?: string;
} | null>(null)
const tooltipStyle = ref({ left: '0px', top: '0px' })
const webglError = ref(false)
const webglErrorMessage = ref('')

// ─── Three.js State (non-reactive for performance) ──────────────
let scene: THREE.Scene
let camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer
let composer: EffectComposer | null = null
let controls: OrbitControls
let animationId: number
let clock: THREE.Clock

// Node tracking
let agentInstancedMesh: THREE.InstancedMesh | null = null
let agentGlowPoints: THREE.Points | null = null  // Glow halo layer for agents
let baseGlowColors: Float32Array | null = null   // pristine halo colours, for search dim/restore
let glowDimActive = false                        // whether the halo is currently search-dimmed
let searchBeacons: THREE.Sprite[] = []           // pooled pulsing gold rings marking search matches
let searchBeams: THREE.Mesh[] = []               // pooled vertical light pillars rising from each match
let searchBeaconTex: THREE.Texture | null = null // shared ring texture for the beacons

// Search beacon ring texture (Commander 2026-06-04): a crisp gold ring + soft glow,
// drawn once and shared by every beacon sprite.
function getSearchBeaconTexture(): THREE.Texture {
  if (searchBeaconTex) return searchBeaconTex
  const s = 128
  const cv = document.createElement('canvas'); cv.width = s; cv.height = s
  const ctx = cv.getContext('2d')!
  const cx = s / 2, cy = s / 2
  const g = ctx.createRadialGradient(cx, cy, s * 0.20, cx, cy, s * 0.5)
  g.addColorStop(0, 'rgba(255,214,92,0)')
  g.addColorStop(0.62, 'rgba(255,200,70,0.16)')
  g.addColorStop(0.80, 'rgba(255,226,140,0.95)')
  g.addColorStop(0.92, 'rgba(255,200,70,0.28)')
  g.addColorStop(1, 'rgba(255,200,70,0)')
  ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, s * 0.5, 0, Math.PI * 2); ctx.fill()
  ctx.strokeStyle = 'rgba(255,238,175,0.95)'; ctx.lineWidth = 4
  ctx.beginPath(); ctx.arc(cx, cy, s * 0.40, 0, Math.PI * 2); ctx.stroke()
  const tex = new THREE.CanvasTexture(cv); tex.needsUpdate = true
  searchBeaconTex = tex
  return tex
}

// Grow the beacon pool to at least n sprites (sprites are reused/hidden, never destroyed).
function ensureSearchBeacons(n: number) {
  if (!scene) return
  while (searchBeacons.length < n) {
    const mat = new THREE.SpriteMaterial({
      map: getSearchBeaconTexture(), color: 0xffffff, transparent: true,
      blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false,
    })
    const sp = new THREE.Sprite(mat)
    sp.renderOrder = 9999  // always on top of the field + decorations
    sp.visible = false
    scene.add(sp)
    searchBeacons.push(sp)

    // Vertical light pillar — rises out of the galactic plane so the match is
    // findable even when buried in the dense core. Open-ended cylinder, additive.
    // GC3 (Commander 2026-06-12): slimmed 0.5→0.3 — the match should read as a
    // locator, not a floodlight; contrast now comes from the environment dim.
    const beamGeo = new THREE.CylinderGeometry(0.3, 0.3, 64, 10, 1, true)
    const beamMat = new THREE.MeshBasicMaterial({
      color: 0xffd45a, transparent: true, opacity: 0.0,
      blending: THREE.AdditiveBlending, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
    })
    const beam = new THREE.Mesh(beamGeo, beamMat)
    beam.renderOrder = 9998
    beam.visible = false
    scene.add(beam)
    searchBeams.push(beam)
  }
}
// GC3 search-focus (Commander 2026-06-12):
// — agentMatchesSearch is the ONE matching rule shared by the animate loop, the
//   beacon pass and all three pick sites (hover + mouse click + touch click), so
//   "dimmed" and "non-interactive" can never disagree in crowded orbits.
// — envDimmables/envDimFactor fade the DECORATIVE layers (star layers, galaxy
//   band, nebulae, registry dust, ambient glows) toward 35% while a query is
//   active, so the match pops by CONTRAST instead of raw brightness. Material
//   opacity only — base values are captured at creation and restored verbatim
//   when the query clears. Never touches topology, picking or positions.
function agentMatchesSearch(a: MapAgent): boolean {
  const q = (props.searchQuery || '').toLowerCase()
  if (!q) return true
  return (a.name || '').toLowerCase().includes(q) || (a.did || '').toLowerCase().includes(q)
}
let envDimmables: { mat: THREE.Material & { opacity: number }, base: number }[] = []

/*
 * §BRIDGE R14.4 — THE ATMOSPHERE CONTROL.
 *
 * R13 established what the "black sphere" actually is: a broad ADDITIVE wash
 * that RAISES the sky level, so stars stop standing out and the sun and the
 * black hole lose contrast. Measured on his screenshot the sky read 15-33 in the
 * centre against 3-8 at the edges; measured here, after the cut, ~9. That gap is
 * his GPU versus this box's software renderer, and I cannot close it from here.
 *
 * So this stops being a number I guess at and becomes a dial he owns. Three
 * steps, `subtle` (today's authored values) as the default, and `off` as the
 * escape hatch that has effectively been missing.
 *
 * 🔴 THE TRAP THIS CODE EXISTS TO AVOID: nebula alpha is baked into the
 * TEXTURE, the material sits at opacity 1.0, and the GC3 search-focus pass
 * assigns `mat.opacity = base * envDimFactor` wholesale (see the dim block).
 * An atmosphere control that wrote only `mat.opacity` would therefore be
 * REVERTED by the next search or fleet-lens toggle — implemented-looking and
 * silently inert, the same shape as the computed-over-a-non-reactive-object bug
 * and the topology re-survey that wiped the learned lanes. It writes `base`, so
 * the two compose, AND writes `opacity` immediately, because that dim block only
 * runs while a dim is actually active.
 */
export type AtmosphereMode = 'off' | 'subtle' | 'full'
/*
 * REBASED after measuring. The first cut was { off: 0, subtle: 1, full: 2.2 },
 * i.e. `subtle` = today and `full` = more. That is wrong for the layer that
 * matters: the eight nebulae carry their alpha in the TEXTURE and sit at
 * material opacity 1.0, so multiplying by 2.2 CLAMPS to 1.0 and DEEP was
 * byte-identical to HAZE for the dominant wash. Measured: off->subtle changed
 * 39.2% of pixels, subtle->full only 15.9%, against a 7-13% animation floor.
 *
 * So `full` is now today's authored look (1.0) and the two steps below it are
 * real reductions. Every step is distinct for every layer, and the DEFAULT is
 * lighter than what shipped — which is the direction of his complaint, not
 * against it.
 */
const ATMOS_FACTOR: Record<AtmosphereMode, number> = { off: 0, subtle: 0.45, full: 1 }
let atmosphereMode: AtmosphereMode = 'subtle'
/** Wash layers only: the things that sit between the viewer and the sky.
 *  `envEntry` is the SAME object held by envDimmables when there is one. */
let atmosLayers: {
  mat: THREE.Material & { opacity: number }
  authored: number
  envEntry: { mat: THREE.Material & { opacity: number }, base: number } | null
}[] = []

function applyAtmosphere(): void {
  const f = ATMOS_FACTOR[atmosphereMode] ?? 1
  for (const L of atmosLayers) {
    const target = Math.min(1, L.authored * f)
    if (L.envEntry) {
      // The GC3 dim pass owns this material's opacity and recomputes it as
      // `base * envDimFactor`. Move `base` so the two compose, and mirror the
      // product now, because that pass does NOT run while envDimFactor === 1.
      L.envEntry.base = target
      L.mat.opacity = target * envDimFactor
    } else {
      // NOT env-dimmed before R14 and must not become so now: the dim pass
      // iterates envDimmables only, so applying the factor here would darken
      // these once on an atmosphere change and never restore them when the
      // lens came off. Same authored value, no borrowed multiplier.
      L.mat.opacity = target
    }
    L.mat.needsUpdate = true
  }
}

function setAtmosphere(mode: AtmosphereMode): void {
  if (!(mode in ATMOS_FACTOR)) return
  atmosphereMode = mode
  applyAtmosphere()
}
let envDimFactor = 1
let envDimApplied = false
const _gmDbgNdc = new THREE.Vector3()  // scratch for the __gmDbg match-projection
let agentLabelSprites: THREE.Sprite[] = []  // Name labels — LAZY, see ensureAgentLabel
/**
 * §STARCAP — labels used to be built EAGERLY, one per agent, and each one is a
 * 512x80 canvas ≈ 164KB of GPU texture. At 240 agents that is ~39MB of texture
 * for sprites that are `visible = false` until you search, hover or select; at
 * the 1000 cap it would have been ~164MB. They are now created on demand and
 * held in a small LRU, so the steady state is a handful rather than the fleet.
 */
const agentLabelByDid = new Map<string, THREE.Sprite>()
const agentLabelLru: string[] = []          // least-recent first
const agentByDid = new Map<string, MapAgent>()
const AGENT_LABEL_MAX = 48
let agentDataMap: MapAgent[] = []  // Index i → agent data for instance i
let registryMeshes: Map<string, THREE.Group> = new Map()
/**
 * §BRIDGE R13 #7 — "the registries hitbox is too huge on hover. every registry
 * i cant hover over the agents properly."
 *
 * He is right, and the cause is that picking raycast the whole registry GROUP
 * recursively. A group carries far more than the planet: an atmosphere shell, a
 * ring, halo sprites and a name label, several of which are tens of units across
 * and effectively invisible. Agents are checked first, but an agent is a ~1-unit
 * dot in orbit, so anywhere you were not exactly on one, an invisible decoration
 * won the pick and the registry card appeared instead.
 *
 * So picking now targets ONLY the planet bodies: the hit area matches the thing
 * you can see, and the space around a planet belongs to the agents orbiting it.
 */
let registryPickables: THREE.Object3D[] = []
let connectionLines: THREE.Object3D[] = []
let connectionFlowMat: THREE.ShaderMaterial | null = null  // MAP-CINEMA: energy-flow links
// MAP-CINEMA: motion guard + shared shader clocks (one tick drives all layers)
const REDUCED_MOTION = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const twinkleTime = { value: 0 }
let filmPass: ShaderPass | null = null
let federationBeams: THREE.Object3D[] = []
let redStarMesh: THREE.Mesh | null = null  // For rotation in animate loop
let redStarGroup: THREE.Group | null = null  // For corona pulsing in animate loop

// AAA+ Polish state
let flyToTarget: THREE.Vector3 | null = null
let flyToProgress = 0
let selectedOrbitRing: THREE.Mesh | null = null
let lastInteractionTime = Date.now()
let blackHoleGroup: THREE.Group | null = null
let bhAccretionPoints: THREE.Points | null = null
let bhAccretionOffsets: Float32Array | null = null
let bhStreamPoints: THREE.Points | null = null
let bhStreamOffsets: Float32Array | null = null
let bhSpiralPoints: THREE.Points | null = null
let bhSpiralOffsets: Float32Array | null = null
let bhSpiralRadii: Float32Array | null = null
let bhFlashSprites: THREE.Sprite[] = []
let bhFlashTimers: number[] = []
let tidalTailSprite: THREE.Sprite | null = null
const BH_POS = new THREE.Vector3(160, 10, -240)
const RED_DWARF_POS = new THREE.Vector3(110, 55, -160)

// Layout positions (computed once, stable)
let registryPositions: Map<string, THREE.Vector3> = new Map()
/**
 * §BRIDGE R11 #9 — the registries as OBSTACLES, so traffic can route around them.
 *
 * *"the traffic should route around a registry if its in the way and never thru
 *  it. which is currently the case."* It was: the arc control point was the
 * chord midpoint lifted in Y and had never been shown a registry position, so
 * an A -> C payment across a B that sits between them flew straight through B.
 *
 * Rebuilt with the layout (not per frame, not per event). One entry per
 * registry, deduplicated — `registryPositions` deliberately holds two keys per
 * registry (raw id and sanitised id) pointing at the SAME Vector3.
 */
let registryObstacles: { pos: THREE.Vector3; radius: number }[] = []
/** How many arcs have been deflected this session. Gateable from the battery. */
let arcDeflections = 0
/** Agent orbits sit outside the planet, so the clearance is the orbit, not the skin. */
const OBSTACLE_PAD = 6
let agentPositions: Map<string, THREE.Vector3> = new Map()
// Orbital data for agent rotation around registries
interface AgentOrbit {
  center: THREE.Vector3  // Registry center
  radius: number         // Distance from center
  /*
   * §BRIDGE R16.1 — THE ORBIT IS A FUNCTION OF TIME, NOT ACCUMULATED STATE.
   *
   * His report: *"the agents get warp back frequently. instead of keep they
   * orbit. they rewind back or jump forward."*
   *
   * This used to be `angle`, advanced every frame by `angle += speed * delta` — and
   * `buildAgents()` clears `agentOrbits` and re-seeds every entry from its
   * DID-derived start value. So EVERY rebuild snapped EVERY agent back to where
   * it began: the rewind. A rebuild that also moved the registry centre threw
   * them forward instead. Rebuilds fire whenever the agent list refreshes, and
   * R15 added periodic loads, which is why it became noticeable now.
   *
   * `startAngle` + a clock that outlives the rebuild makes position PURE: the
   * same agent at the same instant is in the same place whether the scene was
   * rebuilt a moment ago or has been running for an hour. Nothing to preserve
   * across a rebuild, because nothing accumulates.
   */
  startAngle: number     // Orbital phase at t=0 (deterministic, DID-seeded)
  speed: number          // Radians per second
  yOffset: number        // Vertical offset
  inclination: number    // Orbital tilt
}
let agentOrbits: Map<string, AgentOrbit> = new Map()

// Interaction state
let raycaster = new THREE.Raycaster()
let mouse = new THREE.Vector2(-999, -999)
let hoveredInstanceIdx: number | null = null  // FIX-07: track hovered agent for visual feedback
let isMouseDown = false
let mouseDownPos = { x: 0, y: 0 }  // OWL24: track drag distance for click detection

// 2026-05-05 audit MEDIUM-5: deep material disposal. `material.dispose()`
// alone leaves attached CanvasTextures resident in WebGL state — this
// helper walks every map type and disposes each before the material itself.
// Mirror of `_disposeMaterial` in UniverseCanvas (Tier 1.2 from prior pass).
function _disposeMaterialDeep(m: any) {
  if (!m) return
  if (Array.isArray(m)) { m.forEach(_disposeMaterialDeep); return }
  if (m.map?.dispose) m.map.dispose()
  if (m.alphaMap?.dispose) m.alphaMap.dispose()
  if (m.bumpMap?.dispose) m.bumpMap.dispose()
  if (m.normalMap?.dispose) m.normalMap.dispose()
  if (m.emissiveMap?.dispose) m.emissiveMap.dispose()
  if (m.lightMap?.dispose) m.lightMap.dispose()
  if (m.aoMap?.dispose) m.aoMap.dispose()
  if (typeof m.dispose === 'function') m.dispose()
}

// 2026-05-05 audit BLOCKER-2: named handler refs so dispose() can
// removeEventListener cleanly. Without these, anonymous touch + WebGL
// ctx listeners leaked across every mount/unmount cycle.
let _onTouchStart: ((e: TouchEvent) => void) | null = null
let _onTouchMove: ((e: TouchEvent) => void) | null = null
let _onTouchEnd: ((e: TouchEvent) => void) | null = null
let _onWebGLContextLost: ((e: Event) => void) | null = null
let _onWebGLContextRestored: (() => void) | null = null

// Shared geometries (created once, reused)
let sharedAgentGeometry: THREE.SphereGeometry
let sharedAgentMaterial: THREE.MeshStandardMaterial

// FIX-10: Debug logging behind flag
const DEBUG_GALACTIC = false
function glog(...args: any[]) { if (DEBUG_GALACTIC) import.meta.env.DEV && console.log('[GalacticMap]', ...args) }
function gwarn(...args: any[]) { if (DEBUG_GALACTIC) console.warn('[GalacticMap]', ...args) }

// FIX-06: Raycast throttle
let raycastCounter = 0

// ─── Constants ───────────────────────────────────────────────────
const BASE_REGISTRY_SPREAD = 55   // Base distance between registries (scaled by count)
const AGENT_CLOUD_RADIUS_DEFAULT = 18     // Outer orbit limit (base — scaled by FIX-15)
const AGENT_INNER_RADIUS_DEFAULT = 9      // Well outside planet surface (base)
const CAMERA_INITIAL_Z_DEFAULT = 80
const LABEL_NEAR_DIST = 50     // Labels fully visible within this distance
const LABEL_FAR_DIST_AGENT = 65       // FIX-13: Agents fade earlier than registries
const LABEL_FAR_DIST_REGISTRY = 200   // Registry labels always visible

// Color palette
const COLORS = {
  bgDark: 0x06060f,
  bgMid: 0x0d0d1a,
  starDim: 0x445577,
  starBright: 0xaabbdd,
  // Registry palette (each registry gets a unique color)
  registryPalette: [
    0x26c6da,  // Teal-cyan
    0xef6c00,  // Deep amber/orange
    0x7e57c2,  // Purple
    0xe53935,  // Red
    0x43a047,  // Forest green
    0xf06292,  // Pink
    0x5c6bc0,  // Indigo
    0xfdd835,  // Yellow
  ] as number[],
  // Frame B mirror palette — magenta/purple family, parallels AgentWorld's
  // FRAME_B_HOP_COLORS so both views share the same visual vocabulary.
  registryPaletteFrameB: [
    0xff4fb4,  // Hot magenta
    0xe91e63,  // Pink-red
    0xc2185b,  // Deep crimson-magenta
    0x9c27b0,  // Bright purple
    0x7b1fa2,  // Deep purple
    0x4a148c,  // Near-indigo purple
  ] as number[],
  registryDead: 0x555566,
  registryRing: 0x1a3a5c,
  federationBeam: 0x2979ff,
  connectionLine: 0x1a2744,
  agentDefault: 0x78909c,
  agentLow: 0x9575cd,
  agentMid: 0x7986cb,
  agentGood: 0x4fc3f7,
  agentGreat: 0x00e5ff,
  agentElite: 0xffd700,
  agentSynced: 0xffab40,  // OWL24: warm amber for synced Frame-A agents
  // Frame B synced agents get a magenta family — mirrors AgentWorld's agentColor()
  agentFrameBElite: 0xff4fb4,
  agentFrameBHigh:  0xe91e63,
  agentFrameBMid:   0xc2185b,
  agentFrameBLow:   0xba68c8,
  selected: 0xff4081,
  hover: 0xffffff,
}

// ─── Color & Size Helpers ────────────────────────────────────────
function getAgentColor(reputation: number, status: string, isSynced: boolean = false, frame?: string): THREE.Color {
  if (status !== 'active') return new THREE.Color(0x444455)
  // Frame-B synced agents: magenta-family tier (parallels AgentWorld's Frame-B
  // palette). Frame-A synced agents keep the warm amber from OWL24.
  const isFrameB = !!frame && frame !== 'local'
  if (isSynced && isFrameB) {
    if (reputation >= 95) return new THREE.Color(COLORS.agentFrameBElite)
    if (reputation >= 80) return new THREE.Color(COLORS.agentFrameBHigh)
    if (reputation >= 60) return new THREE.Color(COLORS.agentFrameBMid)
    return new THREE.Color(COLORS.agentFrameBLow)
  }
  if (isSynced) return new THREE.Color(COLORS.agentSynced)
  if (reputation >= 95) return new THREE.Color(COLORS.agentElite)
  if (reputation >= 80) return new THREE.Color(COLORS.agentGreat)
  if (reputation >= 60) return new THREE.Color(COLORS.agentGood)
  if (reputation >= 40) return new THREE.Color(COLORS.agentMid)
  if (reputation >= 20) return new THREE.Color(COLORS.agentLow)
  return new THREE.Color(COLORS.agentDefault)
}

function getAgentSize(liquid: number, staked: number): number {
  const total = (liquid || 0) + (staked || 0)
  const BASE = 0.6     // Small moon — clearly smaller than planet
  const MAX = 1.4      // Largest agent
  if (total <= 0) return BASE
  return Math.min(BASE + Math.log10(total + 1) * 0.15, MAX)
}

function getRegistryColor(health: number, index: number = 0, frame?: string): THREE.Color {
  if (health < 20) return new THREE.Color(COLORS.registryDead)
  // Frame B registries render in the magenta/purple mirror palette so the two
  // sovereign frames stay visually distinct (matches the AgentWorld globe).
  // Anything tagged 'local' uses the default 8-color Frame A palette.
  const isFrameB = !!frame && frame !== 'local'
  const palette = isFrameB ? COLORS.registryPaletteFrameB : COLORS.registryPalette
  return new THREE.Color(palette[index % palette.length])
}

function getRegistrySize(agentCount: number): number {
  return Math.max(5, Math.min(8, 5 + Math.sqrt(agentCount) * 0.6))
}

// ─── Hash function for deterministic pseudo-random positions ─────
function hashDID(did: string): number {
  let hash = 0
  for (let i = 0; i < did.length; i++) {
    const char = did.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash |= 0
  }
  return Math.abs(hash)
}

function seededRandom(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 16807 + 0) % 2147483647
    return (s - 1) / 2147483646
  }
}

// ─── FIX-15: Dynamic Scene Scale ─────────────────────────────────────
let AGENT_CLOUD_RADIUS = AGENT_CLOUD_RADIUS_DEFAULT
let AGENT_INNER_RADIUS = AGENT_INNER_RADIUS_DEFAULT
let CAMERA_INITIAL_Z = CAMERA_INITIAL_Z_DEFAULT

function updateSceneScale(agentCount: number) {
  // INNER radius must stay clear of the planet surface so agents never clip into the globe
  // (and stay hoverable/clickable). Low counts previously tightened inner to 7-9 → clipping;
  // floored to ~11-12 (base "well outside" is 9; +margin since some still clipped at 9).
  if (agentCount <= 3)       { AGENT_CLOUD_RADIUS = 14; AGENT_INNER_RADIUS = 11; CAMERA_INITIAL_Z = 60 }
  else if (agentCount <= 10) { AGENT_CLOUD_RADIUS = 17; AGENT_INNER_RADIUS = 11; CAMERA_INITIAL_Z = 70 }
  else if (agentCount <= 30) { AGENT_CLOUD_RADIUS = 21; AGENT_INNER_RADIUS = 12; CAMERA_INITIAL_Z = 86 }
  else                       { AGENT_CLOUD_RADIUS = 24; AGENT_INNER_RADIUS = 13; CAMERA_INITIAL_Z = 104 }
}

// ─── Layout ──────────────────────────────────────────────────────
function computeLayout() {
  registryPositions.clear()
  registryObstacles = []
  agentPositions.clear()

  const regs = props.registries
  const agents = props.agents

  // FIX-15: Scale scene to agent count
  updateSceneScale(agents.length)

  // Dynamic spread: scale down as registry count grows
  const REGISTRY_SPREAD = BASE_REGISTRY_SPREAD * Math.max(0.5, 1.0 / Math.sqrt(regs.length / 4))

  // Detect frames for cluster separation
  const frames = new Map<string, MapRegistry[]>()
  for (const reg of regs) {
    const frame = reg.frame || 'local'
    if (!frames.has(frame)) frames.set(frame, [])
    frames.get(frame)!.push(reg)
  }
  const hasMultipleFrames = frames.size > 1
  const CLUSTER_OFFSET = hasMultipleFrames ? 50 : 0

  // Compute frame center targets (local=left, remote=right)
  const frameCenters = new Map<string, { x: number; y: number; z: number }>()
  frameCenters.set('local', { x: -CLUSTER_OFFSET, y: 0, z: 0 })
  let remoteIdx = 0
  for (const [frame] of frames) {
    if (frame === 'local') continue
    frameCenters.set(frame, { x: CLUSTER_OFFSET, y: 0, z: 0 })
    remoteIdx++
  }

  // Place registries using force-directed layout (topology-aware)
  // SINGLE simulation for ALL registries — with frame gravity pulling clusters apart
  if (regs.length === 0) {
    registryPositions.set('__local__', new THREE.Vector3(0, 0, 0))
  } else if (regs.length === 1) {
    registryPositions.set(regs[0].id, new THREE.Vector3(0, 0, 0))
  } else {
    const sid = (id: any) => String(id)
    const positions = new Map<string, { x: number; y: number; z: number }>()

    // Seed: Fibonacci sphere with frame offset
    const goldenAngle = Math.PI * (3 - Math.sqrt(5))
    regs.forEach((reg, i) => {
      const fc = frameCenters.get(reg.frame || 'local') || { x: 0, y: 0, z: 0 }
      const y = 1 - (2 * i + 1) / regs.length
      const radiusAtY = Math.sqrt(1 - y * y)
      const theta = goldenAngle * i
      positions.set(sid(reg.id), {
        x: fc.x + Math.cos(theta) * radiusAtY * REGISTRY_SPREAD,
        y: fc.y + y * REGISTRY_SPREAD * 0.4,
        z: fc.z + Math.sin(theta) * radiusAtY * REGISTRY_SPREAD * 0.6,
      })
    })

    // Build adjacency from ALL federationLinks
    const linked = new Set<string>()
    for (const reg of regs) {
      for (const linkId of reg.federationLinks || []) {
        const sa = sid(reg.id), sb = sid(linkId)
        const [a, b] = sa < sb ? [sa, sb] : [sb, sa]
        linked.add(`${a}::${b}`)
      }
    }

    // 3D Force-directed simulation (50 iterations)
    const repulsion = REGISTRY_SPREAD * REGISTRY_SPREAD * 2
    const attraction = 0.05
    const damping = 0.9
    const velocities = new Map<string, { vx: number; vy: number; vz: number }>()
    regs.forEach(r => velocities.set(sid(r.id), { vx: 0, vy: 0, vz: 0 }))

    // Frame gravity strength — pulls registries toward their frame center
    const frameGravity = hasMultipleFrames ? 0.02 : 0.01

    for (let iter = 0; iter < 50; iter++) {
      // Repulsion between all pairs
      for (let i = 0; i < regs.length; i++) {
        for (let j = i + 1; j < regs.length; j++) {
          const a = positions.get(sid(regs[i].id))!
          const b = positions.get(sid(regs[j].id))!
          let dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z
          const dist2 = dx * dx + dy * dy + dz * dz + 0.1
          const force = repulsion / dist2
          const dist = Math.sqrt(dist2)
          dx = (dx / dist) * force; dy = (dy / dist) * force; dz = (dz / dist) * force
          const va = velocities.get(sid(regs[i].id))!
          const vb = velocities.get(sid(regs[j].id))!
          va.vx += dx; va.vy += dy; va.vz += dz
          vb.vx -= dx; vb.vy -= dy; vb.vz -= dz
        }
      }

      // Attraction along edges
      for (const edge of linked) {
        const [aId, bId] = edge.split('::')
        const a = positions.get(aId), b = positions.get(bId)
        if (!a || !b) continue
        const fx = (b.x - a.x) * attraction
        const fy = (b.y - a.y) * attraction
        const fz = (b.z - a.z) * attraction
        const va = velocities.get(aId), vb = velocities.get(bId)
        if (va) { va.vx += fx; va.vy += fy; va.vz += fz }
        if (vb) { vb.vx -= fx; vb.vy -= fy; vb.vz -= fz }
      }

      // Frame gravity + damping — each registry pulled toward its frame center
      for (const reg of regs) {
        const k = sid(reg.id)
        const p = positions.get(k)!, v = velocities.get(k)!
        const fc = frameCenters.get(reg.frame || 'local') || { x: 0, y: 0, z: 0 }
        v.vx -= (p.x - fc.x) * frameGravity
        v.vy -= (p.y - fc.y) * frameGravity
        v.vz -= (p.z - fc.z) * frameGravity
        v.vx *= damping; v.vy *= damping; v.vz *= damping
        p.x += v.vx; p.y += v.vy; p.z += v.vz
      }
    }

    // Enforce minimum distance
    const MIN_DIST = AGENT_CLOUD_RADIUS_DEFAULT * 2
    const finalPositions = new Map<string, THREE.Vector3>()
    for (const reg of regs) {
      const p = positions.get(sid(reg.id))!
      finalPositions.set(sid(reg.id), new THREE.Vector3(p.x, p.y, p.z))
    }
    for (let pass = 0; pass < 15; pass++) {
      let anyOverlap = false
      for (let i = 0; i < regs.length; i++) {
        for (let j = i + 1; j < regs.length; j++) {
          const a = finalPositions.get(sid(regs[i].id))!
          const b = finalPositions.get(sid(regs[j].id))!
          const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z
          const dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
          if (dist < MIN_DIST) {
            const push = (MIN_DIST - dist) / 2 + 0.5
            const nx = dist > 0.01 ? dx / dist : Math.cos(i * 2.618 + pass)
            const ny = dist > 0.01 ? dy / dist : Math.sin(i * 1.618 + pass * 0.7)
            const nz = dist > 0.01 ? dz / dist : Math.sin(i * 2.618 + pass)
            a.x -= nx * push; a.y -= ny * push; a.z -= nz * push
            b.x += nx * push; b.y += ny * push; b.z += nz * push
            anyOverlap = true
          }
        }
      }
      if (!anyOverlap) break
    }

    for (const reg of regs) {
      const pos = finalPositions.get(sid(reg.id))!
      registryPositions.set(reg.id, pos)
      registryPositions.set(sid(reg.id), pos)
    }
  }

  // The obstacle set the verb layer routes around. Built from the SAME sizes the
  // meshes use, so a bigger registry is a bigger thing to fly around — one
  // number, not two that can drift.
  {
    const seen = new Set<THREE.Vector3>()
    for (const reg of regs) {
      const pos = registryPositions.get(reg.id) || registryPositions.get(String(reg.id))
      if (!pos || seen.has(pos)) continue
      seen.add(pos)
      registryObstacles.push({ pos, radius: getRegistrySize(reg.agentCount) + OBSTACLE_PAD })
    }
  }

  // Place agents around their registry with orbital data
  agentOrbits.clear()
  agents.forEach((agent) => {
    const regId = agent.registryId || regs[0]?.id || '__local__'
    const center = registryPositions.get(regId) || new THREE.Vector3(0, 0, 0)

    const h = hashDID(agent.did)
    const rng = seededRandom(h)

    // Box-Muller half-normal radius → natural cluster, no visible ring. Dense
    // near the planet with a tapering tail. Reputation compresses the sigma
    // so high-rep agents cluster tighter against the registry glyph.
    // Mirrors AgentWorld's orbitalCoords pattern (2026-04-18 globe overhaul).
    const u1 = Math.max(rng(), 1e-4)
    const u2 = rng()
    const gauss = Math.abs(Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2))
    const repScale = 0.5 + (1 - (agent.reputation || 0) / 100) * 0.5
    const span = AGENT_CLOUD_RADIUS - AGENT_INNER_RADIUS
    const dist = AGENT_INNER_RADIUS + Math.min(span, gauss * span * 0.45 * repScale)

    // Starting angle and orbital tilt
    const startAngle = rng() * Math.PI * 2
    const inclination = (rng() - 0.5) * 0.6  // Slight tilt from equator
    const orbitSpeed = 0.06 + rng() * 0.12  // Radians per second (varied speeds)
    const yOff = (rng() - 0.5) * 2.0  // Small vertical offset

    // Compute initial position from orbital params
    const x = center.x + dist * Math.cos(startAngle)
    const y = center.y + yOff + dist * Math.sin(inclination) * Math.sin(startAngle)
    const z = center.z + dist * Math.sin(startAngle) * Math.cos(inclination)

    agentPositions.set(agent.did, new THREE.Vector3(x, y, z))
    agentOrbits.set(agent.did, {
      center: center.clone(),
      radius: dist,
      startAngle,
      speed: orbitSpeed,
      yOffset: yOff,
      inclination,
    })
  })
}

// ─── Procedural Texture Generators ──────────────────────────────
let _starTexture: THREE.Texture | null = null
let _glowTexture: THREE.Texture | null = null

function getStarTexture(): THREE.Texture {
  if (_starTexture) return _starTexture
  const canvas = document.createElement('canvas')
  canvas.width = 64
  canvas.height = 64
  const ctx = canvas.getContext('2d')!
  // Soft circular glow
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32)
  grad.addColorStop(0.0, 'rgba(255,255,255,1.0)')
  grad.addColorStop(0.15, 'rgba(220,235,255,0.8)')
  grad.addColorStop(0.4, 'rgba(150,180,255,0.15)')
  grad.addColorStop(1.0, 'rgba(0,0,0,0.0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 64, 64)
  _starTexture = new THREE.CanvasTexture(canvas)
  return _starTexture
}

function getGlowTexture(): THREE.Texture {
  if (_glowTexture) return _glowTexture
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  const ctx = canvas.getContext('2d')!
  const grad = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
  grad.addColorStop(0.0, 'rgba(255,255,255,0.6)')
  grad.addColorStop(0.2, 'rgba(100,180,255,0.3)')
  grad.addColorStop(0.5, 'rgba(50,100,200,0.08)')
  grad.addColorStop(1.0, 'rgba(0,0,0,0.0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 128, 128)
  _glowTexture = new THREE.CanvasTexture(canvas)
  return _glowTexture
}

function createNebulaSprite(color: number, opacity: number, size: number): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = 256
  canvas.height = 256
  const ctx = canvas.getContext('2d')!
  const r = ((color >> 16) & 255)
  const g = ((color >> 8) & 255)
  const b = (color & 255)
  // Asymmetric nebula blob
  const grad = ctx.createRadialGradient(128 + (Math.random() - 0.5) * 40, 128 + (Math.random() - 0.5) * 40, 0, 128, 128, 128)
  grad.addColorStop(0.0, `rgba(${r},${g},${b},${opacity})`)
  grad.addColorStop(0.3, `rgba(${r},${g},${b},${opacity * 0.4})`)
  grad.addColorStop(0.7, `rgba(${r},${g},${b},${opacity * 0.08})`)
  grad.addColorStop(1.0, 'rgba(0,0,0,0)')
  ctx.fillStyle = grad
  ctx.fillRect(0, 0, 256, 256)
  const tex = new THREE.CanvasTexture(canvas)
  const mat = new THREE.SpriteMaterial({
    map: tex,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const sprite = new THREE.Sprite(mat)
  sprite.scale.setScalar(size)
  return sprite
}

// ─── Procedural Planet Texture ─────────────────────────────────
// ─── Planet Texture Cache ────────────────────────────────────────
const planetTextureCache = new Map<string, THREE.CanvasTexture>()

function getCachedPlanetTexture(baseColor: THREE.Color, seed: number, regId?: string): THREE.CanvasTexture {
  // 2026-05-05 audit MEDIUM-3: cache key was `${color}_${seed}` which
  // included regIndex via the color (registry order can shift between
  // rebuilds). Stable key on regId guarantees same registry → same texture
  // across rebuilds, eliminating the per-topology-change regen cost.
  // Falls back to old key when regId not supplied.
  const key = regId ? `reg:${regId}` : `${baseColor.getHexString()}_${seed}`
  const cached = planetTextureCache.get(key)
  if (cached) return cached
  const tex = createPlanetTexture(baseColor, seed)
  planetTextureCache.set(key, tex)
  return tex
}

function createPlanetTexture(baseColor: THREE.Color, seed: number): THREE.CanvasTexture {
  const S = 1024
  const canvas = document.createElement('canvas')
  canvas.width = S
  canvas.height = S
  const ctx = canvas.getContext('2d')!
  const rng = seededRandom(seed)

  // Boost any low channels so every planet has visible features
  // Orange (0xef6c00) has B=0 → ocean is invisible brown without this boost
  const rawR = Math.round(baseColor.r * 255)
  const rawG = Math.round(baseColor.g * 255)
  const rawB = Math.round(baseColor.b * 255)
  const minChannel = 100  // Aggressive floor — every channel visible
  const r = Math.max(minChannel, rawR)
  const g = Math.max(minChannel, rawG)
  const b = Math.max(minChannel, rawB)
  // Ocean — must be dark enough for continent contrast but NOT invisible
  const dr = Math.round(r * 0.28) + 35
  const dg = Math.round(g * 0.28) + 35
  const db = Math.round(b * 0.28) + 40
  // Bright accent for highlights (continents, ice caps, cities)
  const hr = Math.min(255, r + 120)
  const hg = Math.min(255, g + 120)
  const hb = Math.min(255, b + 120)

  // === 1. OCEAN — dark colored base (not black) ===
  ctx.fillStyle = `rgb(${dr},${dg},${db})`
  ctx.fillRect(0, 0, S, S)

  // Ocean depth variation
  for (let i = 0; i < 12; i++) {
    const ox = rng()*S, oy = rng()*S, orad = 40 + rng()*180
    const og = ctx.createRadialGradient(ox, oy, 0, ox, oy, orad)
    const darker = rng() > 0.5
    og.addColorStop(0, `rgba(${darker?0:dr+15},${darker?0:dg+15},${darker?0:db+10},${0.08 + rng()*0.1})`)
    og.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = og; ctx.fillRect(0, 0, S, S)
  }

  // === 2. CONTINENTS — large, dramatic landmasses ===
  const nContinents = 4 + Math.floor(rng()*4)
  for (let i = 0; i < nContinents; i++) {
    const cx = rng()*S, cy = S*0.08 + rng()*S*0.84
    const rx = 80 + rng()*200, ry = 50 + rng()*140  // MUCH bigger than before
    // Core
    const cg = ctx.createRadialGradient(cx+(rng()-0.5)*25, cy+(rng()-0.5)*20, rx*0.05, cx, cy, rx)
    cg.addColorStop(0, `rgba(${hr},${hg},${hb},0.95)`)
    cg.addColorStop(0.25, `rgba(${r},${g},${b},0.85)`)
    cg.addColorStop(0.5, `rgba(${Math.round(r*0.7)},${Math.round(g*0.7)},${Math.round(b*0.7)},0.5)`)
    cg.addColorStop(0.75, `rgba(${Math.round(r*0.4)},${Math.round(g*0.4)},${Math.round(b*0.4)},0.2)`)
    cg.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = cg
    ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, rng()*Math.PI, 0, Math.PI*2); ctx.fill()
    // Islands/coastline irregularity
    for (let j = 0; j < 6 + Math.floor(rng()*6); j++) {
      const sx = cx + (rng()-0.5)*rx*1.8, sy = cy + (rng()-0.5)*ry*1.8
      const sr = 15 + rng()*60  // Bigger islands
      const sg = ctx.createRadialGradient(sx, sy, 0, sx, sy, sr)
      sg.addColorStop(0, `rgba(${r},${g},${b},${0.5+rng()*0.4})`)
      sg.addColorStop(0.6, `rgba(${r},${g},${b},${0.15+rng()*0.15})`)
      sg.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = sg; ctx.beginPath(); ctx.arc(sx, sy, sr, 0, Math.PI*2); ctx.fill()
    }
  }

  // === 3. MOUNTAIN RIDGES — brighter streaks on continents ===
  for (let i = 0; i < 8; i++) {
    ctx.strokeStyle = `rgba(${hr},${hg},${hb},${0.06 + rng()*0.08})`
    ctx.lineWidth = 3 + rng()*5
    ctx.beginPath()
    let px = rng()*S, py = rng()*S
    ctx.moveTo(px, py)
    for (let j = 0; j < 4 + Math.floor(rng()*4); j++) {
      px += (rng()-0.5)*120; py += (rng()-0.5)*80
      ctx.lineTo(px, py)
    }
    ctx.stroke()
  }

  // === 4. POLAR ICE CAPS ===
  const polar = ctx.createLinearGradient(0, 0, 0, S)
  polar.addColorStop(0, `rgba(${hr},${hg},${hb},0.3)`)
  polar.addColorStop(0.05, `rgba(${hr},${hg},${hb},0.08)`)
  polar.addColorStop(0.12, 'rgba(0,0,0,0)')
  polar.addColorStop(0.88, 'rgba(0,0,0,0)')
  polar.addColorStop(0.95, `rgba(${hr},${hg},${hb},0.06)`)
  polar.addColorStop(1, `rgba(${hr},${hg},${hb},0.25)`)
  ctx.fillStyle = polar; ctx.fillRect(0, 0, S, S)

  // === 5. TECH GRID removed — too artificial looking ===

  // === 6. CIRCUIT TRACES on continents (sci-fi detail) ===
  for (let i = 0; i < 12; i++) {
    ctx.strokeStyle = `rgba(${hr},${hg},${hb},${0.1 + rng()*0.15})`
    ctx.lineWidth = 1 + rng()*1.2
    ctx.beginPath()
    let px = rng()*S, py = rng()*S
    ctx.moveTo(px, py)
    for (let j = 0; j < 2 + Math.floor(rng()*4); j++) {
      if (rng()>0.5) px += (rng()>0.5?1:-1)*(15+rng()*60)
      else py += (rng()>0.5?1:-1)*(15+rng()*60)
      ctx.lineTo(px, py)
    }
    ctx.stroke()
    // Tiny junction dot
    ctx.fillStyle = `rgba(${hr},${hg},${hb},${0.3+rng()*0.4})`
    ctx.beginPath(); ctx.arc(px, py, 1.5+rng()*2, 0, Math.PI*2); ctx.fill()
  }

  // === 7. CITY LIGHTS (bright white-core clusters) ===
  for (let i = 0; i < 70 + Math.floor(rng()*40); i++) {
    const cx = rng()*S, cy = S*0.05 + rng()*S*0.9
    const sz = 2 + rng()*4
    const bright = 0.4 + rng()*0.6
    const cg = ctx.createRadialGradient(cx, cy, 0, cx, cy, sz*2.5)
    cg.addColorStop(0, `rgba(255,255,255,${bright})`)
    cg.addColorStop(0.3, `rgba(${hr},${hg},${hb},${bright*0.5})`)
    cg.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(cx, cy, sz*2.5, 0, Math.PI*2); ctx.fill()
  }

  // === 8. THIN CLOUD WISPS ===
  for (let i = 0; i < 5; i++) {
    const wx = rng()*S, wy = S*0.15+rng()*S*0.7, ww = 60+rng()*180, wh = 8+rng()*20
    ctx.fillStyle = `rgba(255,255,255,${0.02 + rng()*0.025})`
    ctx.beginPath(); ctx.ellipse(wx, wy, ww, wh, (rng()-0.5)*0.6, 0, Math.PI*2); ctx.fill()
  }

  const tex = new THREE.CanvasTexture(canvas)
  tex.wrapS = THREE.RepeatWrapping
  tex.wrapT = THREE.ClampToEdgeWrapping
  tex.anisotropy = 4
  return tex
}

// ─── Text Sprite Creator ─────────────────────────────────────────
function createTextSprite(text: string, accentColor: THREE.Color): THREE.Sprite {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  canvas.width = 512
  canvas.height = 96

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  ctx.font = '600 44px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  // Dark outline for readability against any background
  ctx.strokeStyle = 'rgba(0,0,0,0.7)'
  ctx.lineWidth = 5
  ctx.lineJoin = 'round'
  ctx.strokeText(text, canvas.width / 2, canvas.height / 2)

  // FIX-16: Subtle accent color glow behind text
  const ar = Math.round(accentColor.r * 255)
  const ag = Math.round(accentColor.g * 255)
  const ab = Math.round(accentColor.b * 255)
  ctx.shadowColor = `rgba(${ar},${ag},${ab},0.6)`
  ctx.shadowBlur = 18

  // Crisp white fill with colored glow
  ctx.fillStyle = '#f0f4ff'
  ctx.fillText(text, canvas.width / 2, canvas.height / 2)
  ctx.shadowBlur = 0

  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    sizeAttenuation: true,
  })

  return new THREE.Sprite(material)
}

// ─── Agent Label Sprite (compact, colored) ─────────────────────
function createAgentLabel(name: string, accentColor: THREE.Color): THREE.Sprite {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')!
  canvas.width = 512
  canvas.height = 80

  ctx.clearRect(0, 0, canvas.width, canvas.height)

  // Background pill \u2014 crisp glass with accent border (labels now show one-at-a-time
  // for search/hover/select, so legibility matters more than hierarchy fade).
  const pillW = 480, pillH = 56, pillX = 16, pillY = 12
  const accRGB = `${Math.round(accentColor.r*255)},${Math.round(accentColor.g*255)},${Math.round(accentColor.b*255)}`
  ctx.fillStyle = 'rgba(8,12,22,0.86)'
  ctx.beginPath()
  if (ctx.roundRect) ctx.roundRect(pillX, pillY, pillW, pillH, 28)
  else ctx.rect(pillX, pillY, pillW, pillH)
  ctx.fill()
  // Accent border
  ctx.lineWidth = 2
  ctx.strokeStyle = `rgba(${accRGB},0.55)`
  ctx.stroke()

  // Colored left dot + glow
  const dotR = 10
  ctx.fillStyle = `rgb(${accRGB})`
  ctx.shadowColor = `rgb(${accRGB})`
  ctx.shadowBlur = 12
  ctx.beginPath()
  ctx.arc(pillX + 30, canvas.height/2, dotR, 0, Math.PI*2)
  ctx.fill()
  ctx.shadowBlur = 0

  // Name text \u2014 brighter + slightly heavier for the one-up label
  ctx.font = '600 33px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillStyle = '#f2f6ff'
  ctx.fillText(name.length > 22 ? name.slice(0,20) + '\u2026' : name, pillX + 52, canvas.height/2 + 1)

  const texture = new THREE.CanvasTexture(canvas)
  texture.needsUpdate = true

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    sizeAttenuation: true,
  })

  return new THREE.Sprite(material)
}

// ─── Scene Init ──────────────────────────────────────────────────
function initScene() {
  if (!containerRef.value) return

  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight

  clock = new THREE.Clock()

  // Scene
  scene = new THREE.Scene()
  scene.background = new THREE.Color(COLORS.bgDark)

  // AAA+: Radial vignette (dark edges, draws eye inward)
  const vigC = document.createElement('canvas'); vigC.width = 512; vigC.height = 512
  const vCtx = vigC.getContext('2d')!
  const vGrad = vCtx.createRadialGradient(256, 256, 60, 256, 256, 256)
  vGrad.addColorStop(0, 'rgba(6,6,15,0)')
  vGrad.addColorStop(0.6, 'rgba(6,6,15,0)')
  vGrad.addColorStop(0.85, 'rgba(3,3,8,0.25)')
  vGrad.addColorStop(1, 'rgba(0,0,0,0.6)')
  vCtx.fillStyle = vGrad; vCtx.fillRect(0, 0, 512, 512)
  const vignette = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(vigC), transparent: true, depthWrite: false, depthTest: false,
  }))
  vignette.scale.set(900, 900, 1)
  vignette.position.set(0, 0, -380)
  vignette.renderOrder = -1
  scene.add(vignette)
  scene.fog = new THREE.FogExp2(COLORS.bgDark, 0.004)

  // Camera (FIX-15: dynamic Z based on agent count, wider for multi-frame)
  camera = new THREE.PerspectiveCamera(60, w / h, 0.1, 800)
  const hasMultipleFrames = new Set(props.registries.map(r => r.frame).filter(Boolean)).size > 1
  const cameraZ = hasMultipleFrames ? CAMERA_INITIAL_Z * 1.5 : CAMERA_INITIAL_Z
  camera.position.set(0, 40, cameraZ)

  // Renderer — wrapped in try/catch for WebGL context failures
  try {
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      powerPreference: 'high-performance',
      failIfMajorPerformanceCaveat: false,
    })
  } catch (e: any) {
    console.error('WebGL context creation failed:', e)
    webglError.value = true
    webglErrorMessage.value = e.message || 'WebGL context could not be created'
    return
  }

  // Check if context was actually obtained
  const gl = renderer.getContext()
  if (!gl) {
    webglError.value = true
    webglErrorMessage.value = 'WebGL context is null — GPU may be busy. Try refreshing the page.'
    return
  }

  renderer.setSize(w, h)
  // §BRIDGE §8.3 — the stage clamps DPR to 1.25. On a 2x display that is ~2.6x
  // fewer fragments per frame than the map view's clamp of 2, which is most of
  // the budget for a canvas that must sit behind a landing page forever.
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, IS_MISSION ? 1.25 : 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.5  // CINEMA full-send: punchier exposure (1.4→1.5)
  containerRef.value.appendChild(renderer.domElement)

  if (IS_MISSION) {
    // §BRIDGE §7.3 — NO EffectComposer on the stage. Bloom + film + output is
    // three extra full-screen passes per frame; the landing page pays for glow
    // with pre-baked additive sprite textures instead. `composer` stays null and
    // animate() renders the scene directly.
    buildVerbLayer()
    setupVisibilityPause()
  } else {
  // Post-processing (bloom for glow)
  composer = new EffectComposer(renderer)
  const renderPass = new RenderPass(scene, camera)
  composer.addPass(renderPass)

  // FIX-12: Bloom hierarchy — higher threshold so only registries + elite agents bloom
  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(w, h),
    1.32,   // MAP-CINEMA full-send: hotter bloom (1.15→1.32)
    0.58,   // wider falloff
    0.74    // threshold HELD — planets + links participate, no star haze
  )
  composer.addPass(bloomPass)

  // MAP-CINEMA: film grade — vignette + subtle teal shadow-lift + temporal grain.
  // Sits after bloom, before output (graded pre tone-map; amplitudes kept tiny).
  filmPass = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, uTime: { value: 0 } },
    vertexShader: `varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; varying vec2 vUv;
      void main() {
        vec2 q = vUv - 0.5;
        float r2 = dot(q, q);
        // MAP-CINEMA glorious: radial chromatic aberration (edges only)
        vec2 ca = q * r2 * 0.018;
        vec4 c;
        c.r = texture2D(tDiffuse, vUv + ca).r;
        c.g = texture2D(tDiffuse, vUv).g;
        c.b = texture2D(tDiffuse, vUv - ca).b;
        c.a = 1.0;
        // gentle saturation lift
        float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
        c.rgb = mix(vec3(luma), c.rgb, 1.08);
        // vignette (slightly deeper than stage 2)
        float vig = smoothstep(0.95, 0.32, length(q) * 1.38);
        c.rgb *= mix(0.78, 1.0, vig);
        // teal shadow-lift
        c.rgb += vec3(0.004, 0.010, 0.014) * (1.0 - clamp(luma, 0.0, 1.0));
        // temporal grain
        float g = fract(sin(dot(vUv * (mod(uTime, 7.0) + 1.0), vec2(12.9898, 78.233))) * 43758.5453);
        c.rgb += (g - 0.5) * 0.016;
        gl_FragColor = c;
      }`,
  })
  composer.addPass(filmPass)
  composer.addPass(new OutputPass())
  }

  // Controls
  controls = new OrbitControls(camera, renderer.domElement)
  // #B13 — the human always wins the camera. Touching the orbit ends a follow.
  controls.addEventListener('start', () => { followDid = null })
  controls.enableDamping = true
  controls.dampingFactor = 0.08
  controls.minDistance = 15
  controls.maxDistance = 250
  controls.maxPolarAngle = Math.PI * 0.85
  controls.autoRotate = !REDUCED_MOTION
  controls.autoRotateSpeed = 0.15
  controls.target.set(0, 0, 0)

  // Stop auto-rotate as soon as user interacts (drag, pan, scroll)
  controls.addEventListener('start', () => {
    controls.autoRotate = false
  })

  // Lighting
  const ambient = new THREE.AmbientLight(0x8899bb, 0.7)  // Brighter ambient so dark planets are visible
  scene.add(ambient)

  const keyLight = new THREE.DirectionalLight(0xeef4ff, 0.8)
  keyLight.position.set(50, 80, 40)
  scene.add(keyLight)

  const fillLight = new THREE.DirectionalLight(0x5566aa, 0.3)
  fillLight.position.set(-40, -20, -50)
  scene.add(fillLight)

  const centerGlow = new THREE.PointLight(0x4488ff, 0.5, 120)
  centerGlow.position.set(0, 5, 0)
  scene.add(centerGlow)

  // Build scene contents
  computeLayout()   // Must be FIRST so registry positions are known
  buildStarfield()   // Uses registry positions for star exclusion zones
  applyAtmosphere()  // R14.4: a rebuild must not quietly restore the wash.
  buildRegistries()
  buildAgents()
  buildConnections()
  buildFederationBeams()
  buildFrameOverlays()

  // Mouse events
  renderer.domElement.addEventListener('mousemove', onMouseMove)
  renderer.domElement.addEventListener('click', onMouseClick)
  // §BRIDGE R13 #2 — right-click a star to TARGET it, opening nothing.
  renderer.domElement.addEventListener('contextmenu', onMouseContext)
  renderer.domElement.addEventListener('mousedown', (e) => { isMouseDown = true; mouseDownPos = { x: e.clientX, y: e.clientY }; lastInteractionTime = Date.now() })
  renderer.domElement.addEventListener('mouseup', () => { isMouseDown = false })

  // FIX-17: Touch support for mobile
  // 2026-05-05 audit BLOCKER-2: extracted to named handlers + cleanup refs
  // so removeEventListener in dispose() can detach them. Anonymous closures
  // accumulated on every SPA route cycle (rapid /galactic-map ↔ /universe).
  _onTouchStart = (e: TouchEvent) => {
    if (e.touches.length === 1) {
      const touch = e.touches[0]
      isMouseDown = true
      mouseDownPos = { x: touch.clientX, y: touch.clientY }
      updateMouseFromTouch(touch)
    }
  }
  _onTouchMove = (e: TouchEvent) => {
    if (e.touches.length === 1) {
      updateMouseFromTouch(e.touches[0])
    }
  }
  _onTouchEnd = (e: TouchEvent) => {
    isMouseDown = false
    if (e.changedTouches.length === 1) {
      const touch = e.changedTouches[0]
      const dx = touch.clientX - mouseDownPos.x
      const dy = touch.clientY - mouseDownPos.y
      if (Math.sqrt(dx * dx + dy * dy) < 10) {
        updateMouseFromTouch(touch)
        // Simulate click via raycasting
        performRaycastClick()
      }
    }
  }
  renderer.domElement.addEventListener('touchstart', _onTouchStart, { passive: true })
  renderer.domElement.addEventListener('touchmove', _onTouchMove, { passive: true })
  renderer.domElement.addEventListener('touchend', _onTouchEnd)

  // WebGL context loss recovery — same cleanup pattern as touch handlers.
  _onWebGLContextLost = (e: Event) => {
    e.preventDefault()
    cancelAnimationFrame(animationId)
  }
  _onWebGLContextRestored = () => {
    animate()
  }
  renderer.domElement.addEventListener('webglcontextlost', _onWebGLContextLost)
  renderer.domElement.addEventListener('webglcontextrestored', _onWebGLContextRestored)
}

// ─── Starfield (AAA: circular textures, color variation, nebulae) ────
function buildStarfield() {
  envDimmables = []  // GC3: rebuilt with the starfield — no stale material refs
  atmosLayers = []   // R14.4: same reason, same lifetime.
  const starTex = getStarTexture()
  buildGalaxyBand()  // MAP-CINEMA glorious backdrop
  // MAP-CINEMA: ultra-far parallax dust (depth floor)
  createStarLayer(3500, 620, 0.7, 0.22, 0x66779a, starTex)
  // Dense distant (cool blue)
  createStarLayer(2500, 350, 1.0, 0.35, 0x8899cc, starTex)
  // Mid stars (warmer)
  createStarLayer(600, 200, 1.8, 0.55, 0xbbccee, starTex)
  // Bright nearby (white-blue)
  createStarLayer(120, 120, 3.0, 0.85, 0xddeeff, starTex)
  // Rare warm accent (orange/gold)
  createStarLayer(30, 180, 2.5, 0.6, 0xffcc88, starTex)
  // Nebula clouds for depth
  buildNebulae()

  // === RED DWARF STAR with procedural surface ===
  const _redStarGroup = new THREE.Group()
  _redStarGroup.position.set(110, 55, -160)
  redStarGroup = _redStarGroup  // Store for animate pulsing

  // Procedural star surface texture
  const starTexCanvas = document.createElement('canvas')
  starTexCanvas.width = 512; starTexCanvas.height = 512
  const stCtx = starTexCanvas.getContext('2d')!
  // Base: deep blood red
  stCtx.fillStyle = 'rgb(160,15,5)'
  stCtx.fillRect(0, 0, 512, 512)
  // Convection granules (bright orange-red patches — high contrast)
  const starRng = seededRandom(42)
  for (let i = 0; i < 180; i++) {
    const gx = starRng()*512, gy = starRng()*512, gr = 10+starRng()*35
    const gg = stCtx.createRadialGradient(gx, gy, 0, gx, gy, gr)
    const bright = starRng() > 0.5
    if (bright) {
      gg.addColorStop(0, `rgba(255,${50+Math.floor(starRng()*60)},10,${0.5+starRng()*0.4})`)
      gg.addColorStop(0.4, `rgba(240,30,0,${0.2+starRng()*0.2})`)
    } else {
      gg.addColorStop(0, `rgba(200,${20+Math.floor(starRng()*30)},5,${0.3+starRng()*0.3})`)
      gg.addColorStop(0.5, `rgba(130,10,0,${0.1+starRng()*0.1})`)
    }
    gg.addColorStop(1, 'rgba(0,0,0,0)')
    stCtx.fillStyle = gg; stCtx.fillRect(0,0,512,512)
  }
  // Deep dark sunspots (almost black)
  for (let i = 0; i < 20; i++) {
    const sx = starRng()*512, sy = starRng()*512, sr = 8+starRng()*30
    const sg = stCtx.createRadialGradient(sx, sy, 0, sx, sy, sr)
    sg.addColorStop(0, `rgba(20,0,0,${0.6+starRng()*0.3})`)
    sg.addColorStop(0.4, `rgba(60,2,0,${0.3+starRng()*0.2})`)
    sg.addColorStop(1, 'rgba(0,0,0,0)')
    stCtx.fillStyle = sg; stCtx.fillRect(0,0,512,512)
  }
  // Bright plasma veins / solar flare traces
  for (let i = 0; i < 12; i++) {
    stCtx.strokeStyle = `rgba(255,${80+Math.floor(starRng()*50)},25,${0.12+starRng()*0.15})`
    stCtx.lineWidth = 2+starRng()*5
    stCtx.beginPath()
    let px = starRng()*512, py = starRng()*512
    stCtx.moveTo(px, py)
    for (let j = 0; j < 6; j++) { px += (starRng()-0.5)*120; py += (starRng()-0.5)*90; stCtx.lineTo(px,py) }
    stCtx.stroke()
  }
  // Bright hotspots (white-orange pinpoints)
  for (let i = 0; i < 30; i++) {
    const hx = starRng()*512, hy = starRng()*512, hsz = 2+starRng()*6
    const hg = stCtx.createRadialGradient(hx, hy, 0, hx, hy, hsz)
    hg.addColorStop(0, `rgba(255,180,80,${0.3+starRng()*0.4})`)
    hg.addColorStop(0.5, `rgba(255,60,10,${0.15+starRng()*0.1})`)
    hg.addColorStop(1, 'rgba(0,0,0,0)')
    stCtx.fillStyle = hg; stCtx.fillRect(0,0,512,512)
  }
  const starSurfaceTex = new THREE.CanvasTexture(starTexCanvas)
  starSurfaceTex.wrapS = THREE.RepeatWrapping
  starSurfaceTex.wrapT = THREE.ClampToEdgeWrapping

  // Core sphere with texture
  const rsGeo = new THREE.SphereGeometry(7, 48, 32)
  const rsMat = new THREE.MeshBasicMaterial({
    map: starSurfaceTex,
    color: 0xee2200,  // Bright blood red tint (not brown)
  })
  const rsMesh = new THREE.Mesh(rsGeo, rsMat)
  redStarMesh = rsMesh  // Store ref for animate rotation
  redStarGroup.add(rsMesh)
  // Inner hot glow
  const rsCore = new THREE.Sprite(new THREE.SpriteMaterial({
    map: getGlowTexture(),
    color: 0xdd2200,
    transparent: true,
    opacity: 0.85,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }))
  rsCore.scale.setScalar(25)
  redStarGroup.add(rsCore)
  // Corona — boosted for visible radiation
  const rsGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: getGlowTexture(),
    color: 0xcc2200,
    transparent: true,
    opacity: 0.8,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }))
  rsGlow.scale.setScalar(75)
  redStarGroup.add(rsGlow)
  // Mid haze (warm orange-red wash)
  const rsMidHaze = new THREE.Sprite(new THREE.SpriteMaterial({
    map: getGlowTexture(),
    color: 0xaa1500,
    transparent: true,
    opacity: 0.18,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }))
  // R13 #1: part of the same wash — halved.
  atmosLayers.push({ mat: rsMidHaze.material as THREE.SpriteMaterial, authored: 0.18, envEntry: null })
  rsMidHaze.scale.setScalar(90)
  redStarGroup.add(rsMidHaze)
  // Outer haze (deep red, massive — visible light radiation)
  const rsHaze = new THREE.Sprite(new THREE.SpriteMaterial({
    map: getGlowTexture(),
    color: 0x990800,
    transparent: true,
    opacity: 0.10,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }))
  // R13 #1: the widest red wash over the cluster — pulled in.
  atmosLayers.push({ mat: rsHaze.material as THREE.SpriteMaterial, authored: 0.10, envEntry: null })
  rsHaze.scale.setScalar(150)
  redStarGroup.add(rsHaze)
  // Red point light — BOOSTED for visible radiation
  const rsLight = new THREE.PointLight(0xdd2200, 3.5, 800, 1.5)
  redStarGroup.add(rsLight)
  // Secondary warm fill light — catches nearby dust and stars
  const rsFill = new THREE.PointLight(0x881100, 1.5, 500, 2.0)
  rsFill.position.set(0, 0, 15)  // Slightly offset toward camera
  redStarGroup.add(rsFill)
  scene.add(redStarGroup)

  // === BLACK HOLE near red dwarf — consuming its corona ===
  createBlackHole()
}

function createBlackHole() {
  blackHoleGroup = new THREE.Group()
  blackHoleGroup.position.copy(BH_POS)
  blackHoleGroup.rotation.x = 0.3
  blackHoleGroup.rotation.z = 0.15

  // Event horizon (pure black sphere) — 3x scale
  const ehGeo = new THREE.SphereGeometry(18, 64, 32)
  const ehMat = new THREE.MeshBasicMaterial({ color: 0x000000 })
  blackHoleGroup.add(new THREE.Mesh(ehGeo, ehMat))

  /**
   * Dark anti-glow: a bright ring around a dark centre.
   *
   * §BRIDGE R11 #3 — THIS WAS THE BLACKNESS.
   *
   * The Commander: *"it is like a empty blackness that expands and contracts
   * with zooming. it is anooying because it blocks the vision on the stars in
   * the background and also dims the sun and the blackhole"* — and, correcting
   * my first guess, *"its not the blackhole. its in the middle of the cluster."*
   *
   * He was right both times. It is not the black hole; it is this sprite AROUND
   * the black hole, and it was **150 world units across** — more than eight
   * times the radius of the event horizon it belongs to — carrying 90% opaque
   * BLACK at its centre under NORMAL blending. Every other large sprite in this
   * scene is AdditiveBlending and therefore physically incapable of darkening
   * anything; this one alone paints black over whatever was drawn before it,
   * which is the starfield, the red dwarf's haze and the black hole's own rings.
   * A sprite is sized in WORLD units, so it grows and shrinks with the camera:
   * "expands and contracts with zooming", exactly.
   *
   * What was falsified on the way here, so nobody re-suspects them:
   *   · the FOG (`FogExp2(bgDark, 0.004)`) — switching it off moved mean frame
   *     luminance by 0.09 of 255. Innocent, and it had been my first suspect.
   *   · the eight nebula sprites — AdditiveBlending, so they cannot darken;
   *     measured contribution to mean luminance ~0.
   *   · the vignette — real but tiny (~0.2/255) and only at the far rim.
   *
   * The fix keeps the intent and drops the wall: the event horizon below is
   * already an OPAQUE BLACK SPHERE, so darkness inside it costs nothing and
   * adds nothing. The dark core now fades out by ~0.36 of the sprite radius,
   * which at the reduced scale lands on the horizon itself; everything beyond
   * is the warm ring the anti-glow exists for.
   */
  const antiC = document.createElement('canvas'); antiC.width = 256; antiC.height = 256
  const aCtx = antiC.getContext('2d')!
  const aGrad = aCtx.createRadialGradient(128, 128, 30, 128, 128, 128)
  aGrad.addColorStop(0, 'rgba(0,0,0,0.85)')
  aGrad.addColorStop(0.22, 'rgba(0,0,0,0.45)')
  aGrad.addColorStop(0.36, 'rgba(0,0,0,0.10)')
  aGrad.addColorStop(0.52, 'rgba(0,0,0,0.02)')
  aGrad.addColorStop(0.7, 'rgba(180,100,30,0.15)')
  aGrad.addColorStop(0.85, 'rgba(255,140,40,0.08)')
  aGrad.addColorStop(1, 'rgba(0,0,0,0)')
  aCtx.fillStyle = aGrad; aCtx.fillRect(0, 0, 256, 256)
  const antiGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(antiC), transparent: true, depthWrite: false
  }))
  // 88 units: the dark core now ends at ~16 units, i.e. at the r=18 horizon.
  antiGlow.scale.set(88, 88, 1)
  antiGlow.name = 'bh-antiglow'
  blackHoleGroup.add(antiGlow)

  // Gravitational glow halo
  const gravGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: getGlowTexture(), color: 0xcc6600, transparent: true, opacity: 0.15,
    depthWrite: false, blending: THREE.AdditiveBlending,
  }))
  // R13 #1: 270 units of additive orange over the whole cluster — pulled in.
  // NOTE: `antiGlow` is deliberately NOT here. It is the horizon's dark core,
  // i.e. the object itself, not wash laid over the sky.
  atmosLayers.push({ mat: gravGlow.material as THREE.SpriteMaterial, authored: 0.15, envEntry: null })
  gravGlow.scale.set(190, 190, 1)
  blackHoleGroup.add(gravGlow)

  // Photon ring
  const prGeo = new THREE.TorusGeometry(24, 0.4, 16, 128)
  const prMat = new THREE.MeshBasicMaterial({
    color: 0xffaa44, transparent: true, opacity: 0.85,
    blending: THREE.AdditiveBlending,
  })
  blackHoleGroup.add(new THREE.Mesh(prGeo, prMat))

  // Second photon ring (wider, dimmer)
  const pr2Geo = new THREE.TorusGeometry(28, 0.2, 16, 128)
  const pr2Mat = new THREE.MeshBasicMaterial({
    color: 0xff8833, transparent: true, opacity: 0.35,
    blending: THREE.AdditiveBlending,
  })
  blackHoleGroup.add(new THREE.Mesh(pr2Geo, pr2Mat))

  // Accretion disk (2000 orbiting particles)
  const diskN = 2000
  const diskPos = new Float32Array(diskN * 3)
  const diskColors = new Float32Array(diskN * 3)
  bhAccretionOffsets = new Float32Array(diskN)
  for (let i = 0; i < diskN; i++) {
    const angle = Math.random() * Math.PI * 2
    const r = 30 + Math.random() * 75
    const thickness = (1 - (r - 30) / 75) * 3.5
    const y = (Math.random() - 0.5) * thickness
    diskPos[i * 3] = Math.cos(angle) * r
    diskPos[i * 3 + 1] = y
    diskPos[i * 3 + 2] = Math.sin(angle) * r
    bhAccretionOffsets[i] = angle
    const tNorm = (r - 30) / 75
    if (tNorm < 0.2) {
      diskColors[i*3]=1; diskColors[i*3+1]=0.9; diskColors[i*3+2]=0.7
    } else if (tNorm < 0.5) {
      diskColors[i*3]=1; diskColors[i*3+1]=0.5+(0.5-tNorm)*0.8; diskColors[i*3+2]=0.1
    } else {
      diskColors[i*3]=0.7-tNorm*0.4; diskColors[i*3+1]=0.15; diskColors[i*3+2]=0.05
    }
  }
  const diskGeo = new THREE.BufferGeometry()
  diskGeo.setAttribute('position', new THREE.BufferAttribute(diskPos, 3))
  diskGeo.setAttribute('color', new THREE.BufferAttribute(diskColors, 3))
  const diskMat = new THREE.PointsMaterial({
    size: 1.5, sizeAttenuation: true, transparent: true, opacity: 0.7,
    vertexColors: true, depthWrite: false, blending: THREE.AdditiveBlending,
    map: getStarTexture(),
  })
  bhAccretionPoints = new THREE.Points(diskGeo, diskMat)
  blackHoleGroup.add(bhAccretionPoints)

  scene.add(blackHoleGroup)

  // === CINEMATIC PLASMA STREAM: Red dwarf → Black hole ===
  // 500 particles arcing from the star surface into the accretion disk
  const streamN = 500
  const streamPos = new Float32Array(streamN * 3)
  const streamColors = new Float32Array(streamN * 3)
  const streamSizes = new Float32Array(streamN)
  bhStreamOffsets = new Float32Array(streamN)
  for (let i = 0; i < streamN; i++) {
    bhStreamOffsets[i] = Math.random()
    const t = bhStreamOffsets[i]
    const p = new THREE.CubicBezierCurve3(
      RED_DWARF_POS.clone().add(new THREE.Vector3((Math.random()-0.5)*6, (Math.random()-0.5)*6, (Math.random()-0.5)*4)),
      new THREE.Vector3(125, 55, -180),  // Arc upward (plasma lifted off)
      new THREE.Vector3(150, 25, -220),  // Curve down toward disk plane
      BH_POS.clone().add(new THREE.Vector3(0, 5, 0))
    ).getPointAt(t)
    // Wobble: large near star, tight near BH
    const wobble = (1 - t) * 3.0
    p.x += (Math.random() - 0.5) * wobble
    p.y += (Math.random() - 0.5) * wobble
    p.z += (Math.random() - 0.5) * wobble * 0.5
    streamPos[i*3] = p.x; streamPos[i*3+1] = p.y; streamPos[i*3+2] = p.z
    // Color: deep red → orange → white-hot
    streamColors[i*3] = 1
    streamColors[i*3+1] = 0.1 + t * 0.8
    streamColors[i*3+2] = t * t * 0.6
    // Size: large clumps leaving star → thin stream near BH
    streamSizes[i] = 3.0 * (1 - t * 0.6)
  }
  const streamGeo = new THREE.BufferGeometry()
  streamGeo.setAttribute('position', new THREE.BufferAttribute(streamPos, 3))
  streamGeo.setAttribute('color', new THREE.BufferAttribute(streamColors, 3))
  streamGeo.setAttribute('size', new THREE.BufferAttribute(streamSizes, 1))
  const streamMat = new THREE.PointsMaterial({
    size: 2.8, sizeAttenuation: true, transparent: true, opacity: 0.7,
    vertexColors: true, depthWrite: false, blending: THREE.AdditiveBlending,
    map: getGlowTexture(),
  })
  bhStreamPoints = new THREE.Points(streamGeo, streamMat)
  scene.add(bhStreamPoints)

  // === SPIRAL-IN LAYER: 300 particles decaying into the disk ===
  const spiralN = 300
  const spiralPos = new Float32Array(spiralN * 3)
  const spiralColors = new Float32Array(spiralN * 3)
  bhSpiralOffsets = new Float32Array(spiralN)
  bhSpiralRadii = new Float32Array(spiralN)
  for (let i = 0; i < spiralN; i++) {
    const angle = Math.random() * Math.PI * 2
    const r = 50 + Math.random() * 55  // Outer disk (50-105)
    bhSpiralOffsets[i] = angle
    bhSpiralRadii[i] = r
    spiralPos[i*3] = Math.cos(angle) * r
    spiralPos[i*3+1] = (Math.random() - 0.5) * 2
    spiralPos[i*3+2] = Math.sin(angle) * r
    const tNorm = 1 - (r - 50) / 55  // 0=outer, 1=inner
    spiralColors[i*3] = 1
    spiralColors[i*3+1] = 0.3 + tNorm * 0.6
    spiralColors[i*3+2] = tNorm * 0.5
  }
  const spiralGeo = new THREE.BufferGeometry()
  spiralGeo.setAttribute('position', new THREE.BufferAttribute(spiralPos, 3))
  spiralGeo.setAttribute('color', new THREE.BufferAttribute(spiralColors, 3))
  const spiralMat = new THREE.PointsMaterial({
    size: 2.0, sizeAttenuation: true, transparent: true, opacity: 0.65,
    vertexColors: true, depthWrite: false, blending: THREE.AdditiveBlending,
    map: getGlowTexture(),
  })
  bhSpiralPoints = new THREE.Points(spiralGeo, spiralMat)
  // Match accretion disk tilt
  bhSpiralPoints.position.copy(BH_POS)
  bhSpiralPoints.rotation.x = 0.3
  bhSpiralPoints.rotation.z = 0.15
  scene.add(bhSpiralPoints)

  // === IMPACT FLASHES at disk inner edge ===
  bhFlashSprites = []
  bhFlashTimers = []
  for (let i = 0; i < 5; i++) {
    const angle = (i / 5) * Math.PI * 2
    const flash = new THREE.Sprite(new THREE.SpriteMaterial({
      map: getGlowTexture(), color: 0xffeedd, transparent: true, opacity: 0,
      blending: THREE.AdditiveBlending, depthWrite: false,
    }))
    flash.scale.setScalar(8)
    flash.position.set(
      BH_POS.x + Math.cos(angle) * 32,
      BH_POS.y + (Math.random() - 0.5) * 3,
      BH_POS.z + Math.sin(angle) * 32
    )
    scene.add(flash)
    bhFlashSprites.push(flash)
    bhFlashTimers.push(Math.random() * 3)  // Staggered start
  }

  // === TIDAL TAIL on red dwarf (teardrop toward BH) ===
  const tailC = document.createElement('canvas'); tailC.width = 256; tailC.height = 256
  const tCtx = tailC.getContext('2d')!
  // Asymmetric gradient: tight on left, stretched on right (toward BH)
  const tGrad = tCtx.createRadialGradient(100, 128, 10, 160, 128, 120)
  tGrad.addColorStop(0, 'rgba(255,40,0,0.7)')
  tGrad.addColorStop(0.3, 'rgba(255,80,10,0.4)')
  tGrad.addColorStop(0.6, 'rgba(255,120,30,0.15)')
  tGrad.addColorStop(1, 'rgba(200,60,0,0)')
  tCtx.fillStyle = tGrad; tCtx.fillRect(0, 0, 256, 256)
  tidalTailSprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(tailC), transparent: true, depthWrite: false,
    blending: THREE.AdditiveBlending, opacity: 0.5,
  }))
  // Position between red dwarf and BH, stretched toward BH
  const tailDir = BH_POS.clone().sub(RED_DWARF_POS).normalize()
  tidalTailSprite.position.copy(RED_DWARF_POS).add(tailDir.multiplyScalar(15))
  tidalTailSprite.scale.set(35, 12, 1)
  // Rotate to face BH direction
  const tailAngle = Math.atan2(BH_POS.x - RED_DWARF_POS.x, BH_POS.z - RED_DWARF_POS.z)
  tidalTailSprite.material.rotation = -tailAngle + Math.PI/2
  scene.add(tidalTailSprite)
}

function createStarLayer(count: number, spread: number, size: number, opacity: number, color: number, tex: THREE.Texture) {
  const posArray: number[] = []
  const colArray: number[] = []
  const baseColor = new THREE.Color(color)
  const STAR_EXCLUSION_RADIUS = 25  // No stars within this distance of any registry

  // Collect registry centers for exclusion
  const regCenters: THREE.Vector3[] = []
  registryPositions.forEach(pos => regCenters.push(pos.clone()))

  let placed = 0
  let attempts = 0
  while (placed < count && attempts < count * 3) {
    attempts++
    const x = (Math.random() - 0.5) * spread
    const y = (Math.random() - 0.5) * spread
    const z = (Math.random() - 0.5) * spread

    // Skip if too close to any registry
    let tooClose = false
    for (const rc of regCenters) {
      const dx = x - rc.x, dy = y - rc.y, dz = z - rc.z
      if (dx*dx + dy*dy + dz*dz < STAR_EXCLUSION_RADIUS * STAR_EXCLUSION_RADIUS) {
        tooClose = true; break
      }
    }
    if (tooClose) continue

    posArray.push(x, y, z)
    const v = 0.85 + Math.random() * 0.3
    colArray.push(baseColor.r * v, baseColor.g * v, baseColor.b * v)
    placed++
  }

  const positions = new Float32Array(posArray)
  const colors = new Float32Array(colArray)

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
  // MAP-CINEMA: per-star phase for the twinkle shader
  const phases = new Float32Array(placed)
  for (let i = 0; i < placed; i++) phases[i] = Math.random() * Math.PI * 2
  geo.setAttribute('aPhase', new THREE.BufferAttribute(phases, 1))

  const mat = new THREE.PointsMaterial({
    size,
    map: tex,
    transparent: true,
    opacity,
    vertexColors: true,
    sizeAttenuation: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  // MAP-CINEMA: subtle per-star brightness oscillation (shared clock; off when
  // the user prefers reduced motion — the clock simply never ticks then).
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.uTwinkleTime = twinkleTime
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aPhase;\nvarying float vPhase;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvPhase = aPhase;')
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', '#include <common>\nuniform float uTwinkleTime;\nvarying float vPhase;')
      .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.a *= 0.72 + 0.28 * sin(uTwinkleTime * (1.1 + fract(vPhase) * 0.9) + vPhase);')
  }

  scene.add(new THREE.Points(geo, mat))
  envDimmables.push({ mat, base: opacity })  // GC3: search-focus dim
}

// MAP-CINEMA glorious: procedural galaxy band on an inside-out far sphere —
// fills the void with a milky arc + color clouds without flattening depth.
function buildGalaxyBand() {
  const cw = 2048, ch = 1024
  const cv = document.createElement('canvas'); cv.width = cw; cv.height = ch
  const g = cv.getContext('2d')!
  const bg = g.createLinearGradient(0, 0, 0, ch)
  bg.addColorStop(0, '#05070f'); bg.addColorStop(0.5, '#070b18'); bg.addColorStop(1, '#04060c')
  g.fillStyle = bg; g.fillRect(0, 0, cw, ch)
  const rng = seededRandom(7)
  // soft color clouds hugging the band (teal / violet / rose / amber / blue)
  const hues = ['rgba(20,110,120,', 'rgba(90,40,150,', 'rgba(140,40,90,', 'rgba(150,100,40,', 'rgba(30,70,140,']
  for (let i = 0; i < 26; i++) {
    const cx = rng() * cw
    const cy = ch * 0.5 + (rng() - 0.5) * ch * 0.28 + Math.sin(cx / cw * Math.PI * 2) * ch * 0.07
    const cr = 90 + rng() * 240
    const grad = g.createRadialGradient(cx, cy, 0, cx, cy, cr)
    grad.addColorStop(0, hues[i % hues.length] + (0.05 + rng() * 0.07) + ')')
    grad.addColorStop(1, 'rgba(0,0,0,0)')
    g.fillStyle = grad; g.fillRect(0, 0, cw, ch)
  }
  // dense star dust concentrated along the band
  for (let i = 0; i < 9000; i++) {
    const x = rng() * cw
    const yBias = Math.pow(rng(), 2.2) * (rng() > 0.5 ? 1 : -1)
    const y = ch * 0.5 + yBias * ch * 0.30 + Math.sin(x / cw * Math.PI * 2) * ch * 0.07
    const a = 0.10 + rng() * 0.45
    const sz = rng() < 0.92 ? 1 : 2
    g.fillStyle = 'rgba(' + (200 + Math.floor(rng() * 55)) + ',' + (205 + Math.floor(rng() * 45)) + ',' + (225 + Math.floor(rng() * 30)) + ',' + a + ')'
    g.fillRect(x, y, sz, sz)
  }
  const tex = new THREE.CanvasTexture(cv)
  tex.colorSpace = THREE.SRGBColorSpace
  const bandMat = new THREE.MeshBasicMaterial({ map: tex, side: THREE.BackSide, transparent: true, opacity: 0.85, depthWrite: false, fog: false })
  const bandEntry = { mat: bandMat, base: 0.85 }
  envDimmables.push(bandEntry)  // GC3: search-focus dim
  /* §BRIDGE R14.4 (corrected) — THE BAND IS THE SKY, so the dial must own it.
   * He reported "clear haze deep buttons do nothing for me", and a census
   * settled why: the two largest painted surfaces are this band sphere
   * (extent 720, opacity 0.85) and the vignette (900). The dial governed
   * NEITHER — only the nebulae, whose alpha R13 had already cut to 0.014-0.035,
   * and two red-star hazes. Turning near-nothing off changes nothing, which is
   * exactly what he saw. Measured sky-floor swing before this: ~1 unit on a
   * floor of ~12, i.e. below the scene's own frame-to-frame variation.
   * The vignette is deliberately NOT included: it DARKENS the rim, so removing
   * it would work against "clear". */
  atmosLayers.push({ mat: bandMat, authored: 0.85, envEntry: bandEntry })
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(720, 48, 32),
    bandMat
  )
  sphere.rotation.z = 0.42  // tilt the band off-horizon (composition)
  sphere.raycast = () => {}
  sphere.renderOrder = -10
  scene.add(sphere)
}

function buildNebulae() {
  /**
   * §BRIDGE R13 #1 — THE "BLACK SPHERE" IS A BRIGHT HAZE, NOT A DARK OBJECT.
   *
   * He reported *"an empty blackness that expands and contracts with zooming"*
   * that *"blocks the vision on the stars in the background and also dims the
   * sun and the blackhole"*, and after my R11 change: *"just got lighter so its
   * more noticeable, didnt get better."*
   *
   * Measuring HIS screenshot settled it. The stage's SKY LEVEL — the background
   * floor with stars and planets excluded — reads **3-8 at the edges and 15-33
   * across a large centre region**. The thing is not dark. It is a big soft
   * ADDITIVE wash that RAISES the floor: stars stop standing out against it, the
   * sun and the black hole lose contrast, and its soft edge is what the eye
   * reads as the rim of a sphere. Being world-space sprites, they grow and
   * shrink with the camera — "expands and contracts with zooming".
   *
   * It also explains his sentence about my last fix exactly: lightening the
   * anti-glow removed darkness that had been partly cancelling the wash, so the
   * wash became MORE visible while the underlying cause went untouched.
   *
   * ⚠ AND THE REASON IT TOOK THREE ROUNDS: every earlier probe sampled pixels
   * with `ctx.drawImage(webglCanvas, …)`. Without `preserveDrawingBuffer` that
   * returns a STALE buffer — it reported the identical 6.667 for every camera,
   * every object, and even with every large sprite hidden. A constant is not a
   * measurement, and "the fog is innocent" rested on it. Real `page.screenshot()`
   * PNGs analysed outside the page do move, and they are what settled this.
   *
   * Opacities cut to roughly a third and the three largest shrunk: the field is
   * still there as depth, but it no longer sits between you and the sky.
   */
  const nebulae = [
    { color: 0x1f3a9c, x: -60, y: 30, z: -80, size: 150, opacity: 0.035 },
    { color: 0x6a1fb8, x: 50, y: -20, z: -60, size: 130, opacity: 0.030 },
    { color: 0x0e7c86, x: 0, y: 10, z: -40, size: 110, opacity: 0.032 },
    { color: 0x8e2466, x: -30, y: -30, z: -100, size: 170, opacity: 0.024 },
    { color: 0x1d4e89, x: 80, y: 20, z: -70, size: 140, opacity: 0.026 },
    { color: 0x9a5b1f, x: -95, y: -8, z: -130, size: 160, opacity: 0.018 },
    { color: 0x2a9d8f, x: 30, y: 45, z: -110, size: 145, opacity: 0.020 },
    { color: 0x0d47a1, x: 0, y: 0, z: -30, size: 80, opacity: 0.014 },
  ]
  nebulae.forEach(n => {
    const sprite = createNebulaSprite(n.color, n.opacity, n.size)
    sprite.position.set(n.x, n.y, n.z)
    scene.add(sprite)
    // GC3: search-focus dim — nebula alpha is baked into the TEXTURE; the
    // sprite material itself sits at opacity 1.0, so that's the base.
    const entry = { mat: sprite.material as THREE.SpriteMaterial, base: 1.0 }
    envDimmables.push(entry)
    // R14.4: authored 1.0 because the alpha lives in the texture, not here.
    atmosLayers.push({ mat: sprite.material as THREE.SpriteMaterial, authored: 1.0, envEntry: entry })
  })
}

// ─── Registries ──────────────────────────────────────────────────
function buildRegistries() {
  // Clear old
  registryMeshes.forEach(g => scene.remove(g))
  registryMeshes.clear()
  registryPickables = []

  const regs = props.registries.length > 0 ? props.registries : [{
    id: '__local__',
    name: 'Local Registry',
    url: '',
    status: 'active',
    agentCount: props.agents.length,
    health: 100,
    federationLinks: [],
  }]

  glog(`Building ${regs.length} registries:`, regs.map(r => `${r.name}(${r.id})`).join(', '))

  regs.forEach((reg, regIndex) => {
    const pos = registryPositions.get(reg.id)
    if (!pos) { gwarn(`No position for registry ${reg.id}`); return }

    const group = new THREE.Group()
    group.position.copy(pos)
    group.userData = { type: 'registry', data: reg }

    const size = getRegistrySize(reg.agentCount)
    const color = getRegistryColor(reg.health, regIndex, reg.frame)

    // Procedural planet texture (cached — survives rebuilds; keyed on
    // reg.id so cache hits even when topology reorder shifts color index)
    const planetSeed = hashDID(reg.id || reg.name)
    const planetTex = getCachedPlanetTexture(color, planetSeed, reg.id || reg.name)

    // Core planet sphere — LOD: fewer segments when many registries
    const segments = regs.length > 10 ? 32 : regs.length > 5 ? 48 : 64
    const coreGeo = new THREE.SphereGeometry(size, segments, Math.round(segments * 0.75))
    // Emissive tinted to match planet color (prevents blue-gray emissive killing warm colors)
    const emissiveBase = color.clone().multiplyScalar(0.25).add(new THREE.Color(0x252530))
    const coreMat = new THREE.MeshStandardMaterial({
      map: planetTex,
      emissive: emissiveBase,
      emissiveIntensity: 2.5,
      roughness: 0.65,
      metalness: 0.25,
      emissiveMap: planetTex,  // Bright areas glow (continents, cities)
    })
    const core = new THREE.Mesh(coreGeo, coreMat)
    core.userData = { isPlanetCore: true }  // For slow rotation
    group.add(core)
    // The ONLY part of a registry that answers the pointer (R13 #7).
    registryPickables.push(core)

    // Atmosphere rim — razor-thin edge glow only (no "flummy ball" effect)
    const atmosSegs = regs.length > 10 ? 16 : 32
    const atmosGeo = new THREE.SphereGeometry(size * 1.04, atmosSegs, Math.round(atmosSegs * 0.75))
    // MAP-CINEMA: true fresnel rim — view-dependent falloff keeps it edge-only
    // (the old flat BackSide wash was capped at 0.06 to avoid the flummy ball;
    // fresnel can afford a stronger rim because the face never fills).
    const atmosMat = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.BackSide,
      uniforms: { uColor: { value: new THREE.Color(color).multiplyScalar(1.6) } },
      vertexShader: `varying vec3 vN; varying vec3 vV;
        void main() {
          vN = normalize(normalMatrix * normal);
          vec4 mv = modelViewMatrix * vec4(position, 1.0);
          vV = normalize(-mv.xyz);
          gl_Position = projectionMatrix * mv;
        }`,
      fragmentShader: `uniform vec3 uColor; varying vec3 vN; varying vec3 vV;
        void main() {
          float rim = pow(1.0 - abs(dot(vN, vV)), 3.0);
          gl_FragColor = vec4(uColor, rim * 0.55);
        }`,
    })
    const atmosMesh = new THREE.Mesh(atmosGeo, atmosMat)
    atmosMesh.raycast = () => {}  // Exclude from hitbox
    group.add(atmosMesh)

    // MAP-CINEMA glorious: ring systems on MAINFRAME-class registries only
    // (peerType 'local' | 'frame') — gorgeous AND informative tier marker.
    if (reg.peerType === 'local' || reg.peerType === 'frame') {
      const ringSpecs = [
        { inner: 1.55, outer: 2.05, opacity: 0.20 },
        { inner: 2.15, outer: 2.40, opacity: 0.11 },
      ]
      for (const rs of ringSpecs) {
        const ringGeo = new THREE.RingGeometry(size * rs.inner, size * rs.outer, 64)
        const ringMat = new THREE.MeshBasicMaterial({
          color: new THREE.Color(color).multiplyScalar(1.3),
          transparent: true,
          opacity: rs.opacity,
          side: THREE.DoubleSide,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        })
        const ring = new THREE.Mesh(ringGeo, ringMat)
        ring.rotation.x = Math.PI / 2.45
        ring.rotation.y = 0.18
        ring.raycast = () => {}
        group.add(ring)
      }
    }

    // NOTE: Removed glow sprite — was causing uniform color wash ("flummy ball" effect)
    // Planet texture and emissive map now provide all the visual interest

    // FIX-01: Registry name label — raised above orbital zone, always on top
    const labelSprite = createTextSprite(reg.name, color)
    labelSprite.position.set(0, size + 7, 0)
    labelSprite.scale.set(14, 3, 1)
    labelSprite.renderOrder = 999
    ;(labelSprite.material as THREE.SpriteMaterial).depthTest = false
    labelSprite.raycast = () => {}  // Exclude from hitbox
    labelSprite.userData.isLabel = true
    labelSprite.visible = props.showLabels
    group.add(labelSprite)

    // FIX-11: Orbital rings REMOVED per Commander feedback — too visually distracting

    // FIX-14: Ambient particle dust around registry
    const dustCount = 40
    const dustPositions = new Float32Array(dustCount * 3)
    const dustVelocities: THREE.Vector3[] = []
    for (let di = 0; di < dustCount; di++) {
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)
      const rd = size * (1.0 + Math.random() * 0.3)
      const dx = rd * Math.sin(phi) * Math.cos(theta)
      const dy = rd * Math.sin(phi) * Math.sin(theta)
      const dz = rd * Math.cos(phi)
      dustPositions[di * 3] = dx
      dustPositions[di * 3 + 1] = dy
      dustPositions[di * 3 + 2] = dz
      dustVelocities.push(new THREE.Vector3(dx * 0.005, dy * 0.005 + 0.01, dz * 0.005))
    }
    const dustGeo = new THREE.BufferGeometry()
    dustGeo.setAttribute('position', new THREE.Float32BufferAttribute(dustPositions, 3))
    const dustMat = new THREE.PointsMaterial({
      size: 0.6,
      map: getGlowTexture(),
      color: color.getHex(),
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const dustPoints = new THREE.Points(dustGeo, dustMat)
    dustPoints.userData = { isDust: true, velocities: dustVelocities, planetSize: size }
    dustPoints.raycast = () => {}  // Exclude from hitbox
    group.add(dustPoints)

    // Soft ambient glow behind planet — visible light radiation
    const ambientGlow = new THREE.Sprite(new THREE.SpriteMaterial({
      map: getGlowTexture(),
      color: color.getHex(),
      transparent: true,
      opacity: 0.12,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    }))
    ambientGlow.scale.setScalar(size * 4)  // Large but subtle — light spill
    ambientGlow.position.set(0, 0, 0)
    ambientGlow.raycast = () => {}  // Exclude from hitbox — was causing 4x oversized hover detection
    ambientGlow.userData.isAmbientGlow = true
    ambientGlow.userData.baseOpacity = 0.12
    group.add(ambientGlow)

    // Point light to illuminate orbiting agents
    const regLight = new THREE.PointLight(color.getHex(), 1.2, AGENT_CLOUD_RADIUS * 3.5)
    regLight.position.set(0, 0, 0)
    group.add(regLight)

    scene.add(group)
    registryMeshes.set(reg.id, group)
  })
  // The ignition can only run once the systems it ignites EXIST. buildVerbLayer
  // runs during renderer init, long before any registry mesh is built, so
  // starting it there would have been a sequence that lights up nothing.
  // Both of these need the systems to EXIST. buildVerbLayer runs during
  // renderer init, before a single registry mesh is built — building territory
  // there produced zero nebulae and zero coronas, silently, and the only reason
  // that was caught is that the stats hook counted them.
  if (IS_MISSION) {
    buildTerritory()
    buildDensity()
    if (!igniteEverRan) { igniteEverRan = true; beginIgnition() }
  }
}

// ─── Agents (InstancedMesh) ──────────────────────────────────────
function buildAgents() {
  // Dispose old
  if (agentInstancedMesh) {
    scene.remove(agentInstancedMesh)
    agentInstancedMesh.dispose()
  }
  // Dispose old agent labels
  agentLabelSprites.forEach(s => { scene.remove(s); (s.material as THREE.SpriteMaterial).map?.dispose(); (s.material as THREE.SpriteMaterial).dispose() })
  agentLabelSprites = []
  agentLabelByDid.clear()
  agentLabelLru.length = 0
  agentByDid.clear()
  agentDataMap = []

  const agents = props.agents
  glog(`Building ${agents.length} agents, ${agentPositions.size} have positions`)
  if (agents.length === 0) return

  // §STARCAP — agent bodies render as 2-6px dots at every camera distance the
  // bridge actually uses. 32x20 spent ~1,216 triangles each on tessellation
  // nobody can resolve; 12x8 spends ~168. That is what pays for the 1000-star
  // cap: 1000 x 168 = 168k triangles, FEWER than the old 240 x 1,216 = 292k.
  if (!sharedAgentGeometry) {
    sharedAgentGeometry = new THREE.SphereGeometry(1, 12, 8)
  }

  // FIX-12: Lowered emissive so standard agents don't bloom (only elite + registries bloom)
  sharedAgentMaterial = new THREE.MeshStandardMaterial({
    roughness: 0.15,
    metalness: 0.6,
    emissive: new THREE.Color(0x88bbff),
    emissiveIntensity: 0.5,  // Subtle self-glow — bloom threshold filters out non-elite
  })

  agentInstancedMesh = new THREE.InstancedMesh(
    sharedAgentGeometry,
    sharedAgentMaterial,
    agents.length
  )
  agentInstancedMesh.userData = { type: 'agentCloud' }

  const dummy = new THREE.Object3D()
  const color = new THREE.Color()

  let placedCount = 0
  agents.forEach((agent, i) => {
    const pos = agentPositions.get(agent.did)
    if (!pos) {
      gwarn(`Agent ${agent.did} has NO position!`)
      return
    }

    const size = getAgentSize(agent.liquidBalance, agent.stakedBalance)
    dummy.position.copy(pos)
    dummy.scale.setScalar(size)
    dummy.updateMatrix()
    agentInstancedMesh!.setMatrixAt(i, dummy.matrix)

    const c = getAgentColor(agent.reputation, agent.status, agent.isSynced, agent.frame)
    // A counterparty is present, not featured: same colour, a third of the
    // brightness. Costs one multiply at build time and nothing per frame.
    if (agent.dim) c.multiplyScalar(0.34)
    agentInstancedMesh!.setColorAt(i, c)

    agentDataMap[i] = agent
    agentByDid.set(agent.did, agent)
    placedCount++
  })
  glog(`Placed ${placedCount}/${agents.length} agents on map`)

  agentInstancedMesh.instanceMatrix.needsUpdate = true
  if (agentInstancedMesh.instanceColor) {
    agentInstancedMesh.instanceColor.needsUpdate = true
  }

  scene.add(agentInstancedMesh)

  // ─── Glow halo layer (one glowing point per agent, makes them visible from afar) ───
  if (agentGlowPoints) {
    scene.remove(agentGlowPoints)
    agentGlowPoints.geometry.dispose()
    ;(agentGlowPoints.material as THREE.PointsMaterial).dispose()
  }

  const glowPositions = new Float32Array(agents.length * 3)
  const glowColors = new Float32Array(agents.length * 3)
  const glowSizes = new Float32Array(agents.length)

  agents.forEach((agent, i) => {
    const pos = agentPositions.get(agent.did)
    if (!pos) return
    glowPositions[i * 3] = pos.x
    glowPositions[i * 3 + 1] = pos.y
    glowPositions[i * 3 + 2] = pos.z
    const c = getAgentColor(agent.reputation, agent.status, agent.isSynced, agent.frame)
    if (agent.dim) c.multiplyScalar(0.30)
    glowColors[i * 3] = c.r
    glowColors[i * 3 + 1] = c.g
    glowColors[i * 3 + 2] = c.b
    const size = getAgentSize(agent.liquidBalance, agent.stakedBalance)
    glowSizes[i] = size * (agent.dim ? 1.4 : 2.5)  // FIX-02: Reduced — bloom does the rest
  })
  baseGlowColors = glowColors.slice()  // pristine halo colours for search dim/restore
  glowDimActive = false

  const glowGeo = new THREE.BufferGeometry()
  glowGeo.setAttribute('position', new THREE.Float32BufferAttribute(glowPositions, 3))
  glowGeo.setAttribute('color', new THREE.Float32BufferAttribute(glowColors, 3))
  // Use first size as uniform since PointsMaterial doesn't support per-point size without custom shader
  const avgSize = glowSizes.length > 0 ? glowSizes.reduce((a, b) => a + b, 0) / glowSizes.length : 5.0

  const glowMat = new THREE.PointsMaterial({
    size: avgSize,
    map: getGlowTexture(),
    transparent: true,
    opacity: 0.3,  // FIX-02: Subtle halo
    vertexColors: true,
    sizeAttenuation: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })

  agentGlowPoints = new THREE.Points(glowGeo, glowMat)
  scene.add(agentGlowPoints)

  // §STARCAP — no eager label pass. Labels are minted by ensureAgentLabel() the
  // first time an agent is actually searched, hovered or selected.
  glog(`Agent labels are lazy (max ${AGENT_LABEL_MAX} live)`)
}

/** Drop one cached label and free its canvas texture. */
function disposeAgentLabel(did: string): void {
  const sp = agentLabelByDid.get(did)
  if (!sp) return
  scene.remove(sp)
  const m = sp.material as THREE.SpriteMaterial
  m.map?.dispose()
  m.dispose()
  agentLabelByDid.delete(did)
  const ix = agentLabelSprites.indexOf(sp)
  if (ix >= 0) agentLabelSprites.splice(ix, 1)
}

/**
 * Mint (or refresh the LRU position of) the label for one agent.
 * Returns null when the agent has no position — an agent we cannot place gets
 * no label rather than a label floating at the origin.
 */
function ensureAgentLabel(did: string): THREE.Sprite | null {
  const existing = agentLabelByDid.get(did)
  if (existing) {
    const at = agentLabelLru.indexOf(did)
    if (at >= 0) agentLabelLru.splice(at, 1)
    agentLabelLru.push(did)
    return existing
  }
  const agent = agentByDid.get(did)
  const pos = agentPositions.get(did)
  if (!agent || !pos) return null

  const agentColor = getAgentColor(agent.reputation, agent.status, agent.isSynced, agent.frame)
  const label = createAgentLabel(agent.name || 'Agent', agentColor)
  const size = getAgentSize(agent.liquidBalance, agent.stakedBalance)
  label.position.set(pos.x, pos.y + size + 1.0, pos.z)
  label.scale.set(5, 0.8, 1)
  label.renderOrder = 998
  ;(label.material as THREE.SpriteMaterial).depthTest = false
  label.userData = { agentDid: did, isLabel: true,
    searchKey: ((agent.name || '') + ' ' + did).toLowerCase() }
  label.visible = false
  scene.add(label)
  agentLabelByDid.set(did, label)
  agentLabelSprites.push(label)
  agentLabelLru.push(did)

  while (agentLabelLru.length > AGENT_LABEL_MAX) {
    const oldest = agentLabelLru.shift()
    if (oldest && oldest !== did) disposeAgentLabel(oldest)
  }
  return label
}

// ─── Connection Lines (Agent → Registry) ─────────────────────────
function buildConnections() {
  // Clear old
  connectionLines.forEach(l => scene.remove(l))
  connectionLines = []

  const linePositions: number[] = []

  const lineTs: number[] = []
  props.agents.forEach((agent) => {
    const agentPos = agentPositions.get(agent.did)
    const regId = agent.registryId || props.registries[0]?.id || '__local__'
    const regPos = registryPositions.get(regId)

    if (agentPos && regPos) {
      linePositions.push(agentPos.x, agentPos.y, agentPos.z)
      linePositions.push(regPos.x, regPos.y, regPos.z)
      lineTs.push(0, 1)
    }
  })

  if (linePositions.length === 0) return

  const geo = new THREE.BufferGeometry()
  geo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3))
  geo.setAttribute('aT', new THREE.Float32BufferAttribute(lineTs, 1))

  // MAP-CINEMA: energy flows agent → registry (animated pulses over a faint base
  // line; uTime ticked in animate()). Same geometry/raycast profile as before.
  connectionFlowMat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uBase: { value: new THREE.Color(COLORS.connectionLine).multiplyScalar(2.6) },
      uPulse: { value: new THREE.Color(0x4df0f0) },
    },
    vertexShader: `attribute float aT; varying float vT;
      void main() { vT = aT; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform float uTime; uniform vec3 uBase; uniform vec3 uPulse; varying float vT;
      void main() {
        float p = fract(vT * 2.0 - uTime * 0.25);
        float pulse = smoothstep(0.0, 0.12, p) * (1.0 - smoothstep(0.12, 0.30, p));
        vec3 col = uBase + uPulse * pulse * 1.6;
        gl_FragColor = vec4(col, 0.12 + pulse * 0.60);
      }`,
  })

  const lines = new THREE.LineSegments(geo, connectionFlowMat)
  scene.add(lines)
  connectionLines.push(lines)
}

// ─── Federation Beams (Registry ↔ Registry) ──────────────────────
// ─── Frame Cluster Visual Polish ─────────────────────────────────
let frameLabels: THREE.Object3D[] = []
let frameRings: THREE.Object3D[] = []

function buildFrameOverlays() {
  // Clean up old overlays
  frameLabels.forEach(l => scene.remove(l))
  frameRings.forEach(r => scene.remove(r))
  frameLabels = []
  frameRings = []

  // Group registries by frame and compute cluster centers
  const frameCenters = new Map<string, { center: THREE.Vector3; count: number; maxDist: number }>()
  for (const reg of props.registries) {
    const frame = reg.frame || 'local'
    const pos = registryPositions.get(reg.id) || registryPositions.get(String(reg.id))
    if (!pos) continue
    if (!frameCenters.has(frame)) {
      frameCenters.set(frame, { center: new THREE.Vector3(), count: 0, maxDist: 0 })
    }
    const fc = frameCenters.get(frame)!
    fc.center.add(pos)
    fc.count++
  }

  // Average centers + compute radii
  for (const [frame, fc] of frameCenters) {
    fc.center.divideScalar(fc.count)
    // Find max distance from center for ring radius
    for (const reg of props.registries) {
      if ((reg.frame || 'local') !== frame) continue
      const pos = registryPositions.get(reg.id) || registryPositions.get(String(reg.id))
      if (pos) fc.maxDist = Math.max(fc.maxDist, fc.center.distanceTo(pos))
    }
  }

  if (frameCenters.size <= 1) return // Single frame — no overlays needed

  for (const [frame, fc] of frameCenters) {
    const isLocal = frame === 'local'
    const labelColor = isLocal ? 0x4488ff : 0xff8844
    const labelText = isLocal ? 'MY FRAME' : frame.toUpperCase()

    // Frame label — canvas texture sprite above the cluster
    const canvas = document.createElement('canvas')
    canvas.width = 512
    canvas.height = 96
    const ctx = canvas.getContext('2d')!
    ctx.clearRect(0, 0, 512, 96)
    ctx.font = '700 32px "Fira Code", monospace'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    // Glow
    ctx.shadowColor = isLocal ? 'rgba(68,136,255,0.6)' : 'rgba(255,136,68,0.6)'
    ctx.shadowBlur = 12
    ctx.fillStyle = isLocal ? 'rgba(100,170,255,0.5)' : 'rgba(255,170,100,0.5)'
    ctx.fillText(labelText, 256, 48)
    // Crisp pass
    ctx.shadowBlur = 0
    ctx.fillStyle = isLocal ? 'rgba(140,200,255,0.35)' : 'rgba(255,200,140,0.35)'
    ctx.fillText(labelText, 256, 48)

    const texture = new THREE.CanvasTexture(canvas)
    const spriteMat = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthTest: false,
    })
    const sprite = new THREE.Sprite(spriteMat)
    sprite.position.copy(fc.center)
    sprite.position.y += fc.maxDist + 22
    sprite.scale.set(30, 6, 1)
    sprite.renderOrder = 998
    sprite.visible = props.showLabels
    scene.add(sprite)
    frameLabels.push(sprite)

    // (Boundary rings removed — frame labels are sufficient)
  }
}

function buildFederationBeams() {
  federationBeams.forEach(b => scene.remove(b))
  federationBeams = []

  const drawn = new Set<string>()

  props.registries.forEach((reg) => {
    reg.federationLinks.forEach((targetId) => {
      const key = [String(reg.id), String(targetId)].sort().join('|')
      if (drawn.has(key)) return
      drawn.add(key)

      const from = registryPositions.get(String(reg.id)) || registryPositions.get(reg.id)
      const to = registryPositions.get(String(targetId)) || registryPositions.get(targetId)
      if (!from || !to) {
        log.warn(`[Beam] SKIP ${reg.name}(${reg.id}) → ${targetId}: from=${!!from} to=${!!to}. posKeys:`, Array.from(registryPositions.keys()))
        return
      }
      log.debug(`[Beam] DRAW ${reg.name} → ${targetId} key=${key}`)

      // Arc curve — height scales with distance to avoid crossing through nodes
      const dist = from.distanceTo(to)
      const baseArcHeight = Math.max(dist * 0.25, 8)
      // Check if any other registry lies roughly between these two endpoints
      let obstacleBoost = 0
      registryPositions.forEach((pos, posKey) => {
        if (posKey === String(reg.id) || posKey === String(targetId) || posKey === reg.id || posKey === targetId) return
        const midX = (from.x + to.x) / 2, midZ = (from.z + to.z) / 2
        const dxM = pos.x - midX, dzM = pos.z - midZ
        const distToMid = Math.sqrt(dxM * dxM + dzM * dzM)
        if (distToMid < dist * 0.4) obstacleBoost = Math.max(obstacleBoost, 6)
      })
      const midY = Math.max(from.y, to.y) + baseArcHeight + obstacleBoost
      const curve = new THREE.QuadraticBezierCurve3(
        from.clone(),
        new THREE.Vector3((from.x + to.x) / 2, midY, (from.z + to.z) / 2),
        to.clone()
      )

      // Bridge beam: gold ONLY between two MAINFRAMES (sovereign frame ↔ sovereign frame).
      // A mainframe node is the local registry (__local__) or a federation peer carrying
      // peer_type='frame'. Cloud operators (peer_type cloud_operator/direct_peer/discovered)
      // NEVER get the gold treatment — even when a cross-frame operator's spoke edge happens
      // to terminate on __local__ (its parent mainframe isn't in the local numbered-peer set,
      // so the chain-edge builder falls the operator back to a __local__ edge). That spoke must
      // stay a normal hop beam, not a golden inter-frame bridge. [Commander 2026-06-04]
      const targetReg = props.registries.find(r => String(r.id) === String(targetId))
      const isCrossFrame = reg.frame && targetReg?.frame && reg.frame !== targetReg.frame
      const _isMainframeNode = (r: MapRegistry | undefined): boolean =>
        !!r && (String(r.id) === '__local__' || r.peerType === 'frame')
      const isMainframeBridge = !!isCrossFrame
        && _isMainframeNode(reg) && _isMainframeNode(targetReg)
      const maxHop = Math.max(reg.hopDepth || 0, targetReg?.hopDepth || 0)

      // Beam visual parameters — only mainframe bridges get gold treatment
      let beamColor: number
      let tubeRadius: number
      let glowRadius: number
      let pulsesPerDir: number
      let pulseRadius: number

      if (isMainframeBridge) {
        beamColor = 0xffb300   // warm amber/gold
        tubeRadius = 0.35      // 2× thicker
        glowRadius = 1.2
        pulsesPerDir = 5
        pulseRadius = 0.4
      } else {
        const beamColors = [0x5c9cf5, 0x5c9cf5, 0x00e5ff, 0xe91e63, 0xd500aa, 0xd50000]
        beamColor = beamColors[Math.min(maxHop, beamColors.length - 1)]
        tubeRadius = 0.18
        glowRadius = 0.6
        pulsesPerDir = 3
        pulseRadius = 0.25
      }

      // Core beam
      const tubeGeo = new THREE.TubeGeometry(curve, 80, tubeRadius, 6, false)
      const tubeMat = new THREE.MeshBasicMaterial({
        color: beamColor,
        transparent: true,
        opacity: isMainframeBridge ? 0.85 : 0.7,
        depthWrite: false,
      })
      const tube = new THREE.Mesh(tubeGeo, tubeMat)
      scene.add(tube)
      federationBeams.push(tube)

      // Soft glow envelope
      const glowGeo = new THREE.TubeGeometry(curve, 80, glowRadius, 6, false)
      const glowMat = new THREE.MeshBasicMaterial({
        color: beamColor,
        transparent: true,
        opacity: isMainframeBridge ? 0.12 : 0.08,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      const glow = new THREE.Mesh(glowGeo, glowMat)
      scene.add(glow)
      federationBeams.push(glow)

      // Bidirectional energy pulses
      for (let dir = 0; dir < 2; dir++) {
        for (let i = 0; i < pulsesPerDir; i++) {
          const pulseGeo = new THREE.SphereGeometry(pulseRadius, 12, 8)
          // Gold pulses ONLY for mainframe bridge, blue/green for everything else
          const pulseColor = isMainframeBridge
            ? (dir === 0 ? 0xffd54f : 0xffab40)
            : (dir === 0 ? 0x90caf9 : 0x80e0a0)
          const pulseMat = new THREE.MeshBasicMaterial({
            color: pulseColor,
            transparent: true,
            opacity: 0.9,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
          })
          const pulse = new THREE.Mesh(pulseGeo, pulseMat)
          const initT = i / pulsesPerDir
          const p = curve.getPointAt(initT)
          pulse.position.copy(p)
          pulse.userData = {
            curve,
            isBeamPulse: true,
            phaseOffset: initT,
            direction: dir === 0 ? 1 : -1,  // 1 = forward, -1 = reverse
            speed: 0.04 + Math.random() * 0.03,  // Slight speed variation
          }
          scene.add(pulse)
          federationBeams.push(pulse)
        }
      }
    })
  })
}

// ═══════════════════════════════════════════════════════════════════════════
// §BRIDGE — THE VERB LAYER (mission mode only)
//
// Every object here is POOLED and allocated exactly once. Nothing is created
// per frame and nothing is created per event: a 900-events-per-second sim burst
// costs the same memory as a quiet network. When the pool is full the extra
// events are COUNTED and not drawn (honesty rule 2) — the stage samples, the
// ledger counts.
//
// Glow comes from a pre-baked additive sprite texture, never from an
// EffectComposer bloom pass (§7.3). One texture, uploaded once.
// ═══════════════════════════════════════════════════════════════════════════

/** Hard ceiling on concurrent verb objects (strategy §8.2). */
const VERB_POOL_CAP = 128
/** Segments per arc. Enough to read as a curve, cheap enough to pool 128 of. */
const ARC_SEGMENTS = 24
/** How much of the path a `mine` photon drags behind it (#B10). */
const COMET_TAIL = 0.22
/**
 * #B15 — the verb layer honours the EXISTING module-level `REDUCED_MOTION`
 * (declared with the camera controls above): a verb still appears, still carries
 * its colour and still fades, it simply does not TRAVEL. The truth is never
 * allowed to depend on motion.
 */
/** Reused every frame by the comet-trail rewrite: zero allocation on the hot path. */
const _scratchVec = new THREE.Vector3()
/** 30fps ambient (strategy §8.3). Interaction lifts to full rate briefly. */
const MISSION_AMBIENT_FRAME_MS = 1000 / 30

let missionPaused = false
let missionLastFrameMs = 0
let missionBoostUntil = 0
let missionObserver: IntersectionObserver | null = null

/**
 * §BRIDGE #B8 — THE FLEET LENS. `F` isolates the viewer's own traffic: the
 * decorative galaxy eases down to 18% (through the SAME `envDimFactor` pass the
 * search focus already uses — one dimming mechanism, not two) and everyone
 * else's photons drop to 8%, so what is left moving is yours. `Esc` restores.
 * Nothing is hidden and nothing is invented: the other traffic is still drawn,
 * still counted, just quiet.
 */
let fleetLensOn = false
/** How far a non-mine verb is pushed back while the lens is on. */
const LENS_OTHER = 0.08
/** How far the decorative layers ease while the lens is on. */
const LENS_ENV = 0.18

interface VerbObj {
  alive: boolean
  /** The descriptor that spawned this object — #B12 photons are receipts. */
  desc: any
  kind: 'arc' | 'spark' | 'bloom' | 'ring' | 'thread'
  head: THREE.Sprite
  line: THREE.Line | null
  curve: THREE.QuadraticBezierCurve3 | null
  from: THREE.Vector3
  to: THREE.Vector3
  colorA: THREE.Color
  colorB: THREE.Color
  t: number
  dur: number
  scale: number
  mine: boolean
  reverted: boolean
  /** #B18 — this leg continues a story that is already in flight. */
  chained: boolean
  /* §BRIDGE R14.1 — TAXONOMY OPTION B (his approval, 2026-08-20).
   * Two channels, not one, because they answer different questions and an
   * amountless event must answer them DIFFERENTLY:
   *   `sizeGrade`  0..1 drives scale + trail. A birth has no magnitude to
   *                inflate it, so a null amount lands at 0 and keeps exactly
   *                the base size it has today.
   *   `brightGrade` 0..1 drives opacity. A birth is not a TINY PAYMENT, so a
   *                null amount lands at 1 and keeps full brightness. Grading it
   *                to 0 would dim every corridor announcement on the stage as
   *                though the network had gone quiet, which is a lie.
   * INVARIANT: grade == 1 reproduces the pre-R14 render EXACTLY. Grading can
   * only ever make small amounts quieter; it can never brighten the stage. He
   * has reported a too-bright stage twice, and a change that raises the ceiling
   * would be the wrong shape even if the grading were right. */
  sizeGrade: number
  brightGrade: number
}

let verbGroup: THREE.Group | null = null
const verbPool: VerbObj[] = []
let glowTexture: THREE.Texture | null = null
/** Verb objects the pool could not serve. Published, never hidden. */
const verbsDroppedForPool = ref(0)
/** Live count for the dev perf overlay. */
const verbsActive = ref(0)

/** Frame accent colours. Gold / silver / emerald — the territory palette (§2.2). */
const FRAME_TINT: Record<string, number> = { A: 0xffc14d, B: 0xc9d4e2, C: 0x36d399 }
/** Per-verb base colour. Only ALARM is red; that is what makes red mean something. */
const VERB_TINT: Record<string, number> = {
  transfer: 0x63d7ff,
  fx: 0xffc14d,
  trade: 0xb388ff,
  guild: 0x64ffda,
  birth: 0xffffff,
  treasury: 0x82b1ff,
  alarm: 0xff5252,
  canary: 0x8a99b5,
  corridor: 0x5c7099,
}

/** Radial additive glow, generated once on the CPU. Cheaper than any bloom pass. */
function makeGlowTexture(): THREE.Texture {
  const size = 64
  const cv = document.createElement('canvas')
  cv.width = cv.height = size
  const g = cv.getContext('2d')!
  const grad = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2)
  grad.addColorStop(0.0, 'rgba(255,255,255,1)')
  grad.addColorStop(0.25, 'rgba(255,255,255,0.55)')
  grad.addColorStop(0.6, 'rgba(255,255,255,0.12)')
  grad.addColorStop(1.0, 'rgba(255,255,255,0)')
  g.fillStyle = grad
  g.fillRect(0, 0, size, size)
  const tex = new THREE.CanvasTexture(cv)
  tex.needsUpdate = true
  return tex
}

function buildVerbLayer(): void {
  if (verbGroup) return
  glowTexture = makeGlowTexture()
  verbGroup = new THREE.Group()
  verbGroup.name = 'bridge-verbs'
  for (let i = 0; i < VERB_POOL_CAP; i++) {
    const mat = new THREE.SpriteMaterial({
      map: glowTexture,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      opacity: 0,
    })
    const head = new THREE.Sprite(mat)
    head.visible = false
    verbGroup.add(head)

    const lineGeom = new THREE.BufferGeometry().setFromPoints(
      new Array(ARC_SEGMENTS + 1).fill(0).map(() => new THREE.Vector3()),
    )
    // Dashed-capable, used solid by default: `dashSize` far larger than any arc
    // renders as a continuous line, and g1 (the canary tracer) sets real dash
    // values so "the system watching the system" is legible as a dotted path.
    const lineMat = new THREE.LineDashedMaterial({
      transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending,
      dashSize: 1e6, gapSize: 0,
    })
    const line = new THREE.Line(lineGeom, lineMat)
    line.visible = false
    verbGroup.add(line)

    verbPool.push({
      alive: false, desc: null, kind: 'spark', head, line, curve: null,
      from: new THREE.Vector3(), to: new THREE.Vector3(),
      colorA: new THREE.Color(), colorB: new THREE.Color(),
      t: 0, dur: 1, scale: 1, mine: false, reverted: false, chained: false,
      sizeGrade: 0, brightGrade: 1,
    })
  }
  scene.add(verbGroup)
}

/*
 * #B15 THE BOOT RITUAL — strategy §5: "systems ignite A->B->C->ops (40ms
 * stagger)".
 *
 * Mission mode only, and deliberately implemented as a MULTIPLIER applied over
 * whatever the shared scene already computed rather than as a second animation
 * system: /galactic-map and /galactic-command must stay byte-identical, and the
 * ignition must be incapable of leaving a node permanently wrong. It runs once,
 * for ~1.4s, then sets every multiplier to 1 and stops touching anything —
 * a reveal cannot become a liability if it cannot outlive itself.
 */
const IGNITE_STAGGER_MS = 40
const IGNITE_RISE_MS = 520
let igniteStart = 0
let igniteOrder: Array<{ obj: THREE.Object3D; base: THREE.Vector3; at: number }> = []
let igniteDone = true
let igniteEverRan = false
/** Proof it happened: how many systems it lit, and when. */
let igniteLit = 0
let igniteAt = 0

function beginIgnition(): void {
  if (!IS_MISSION || !scene) return
  // Frame order first (A, then B, then C, then everything else), name second,
  // so the sequence reads as the federation waking up rather than as noise.
  const order = ['A', 'B', 'C']
  const regs = [...props.registries].sort((a, b) => {
    const fa = order.indexOf(frameKeyOf(a.trustDomain || a.frame || null) || ''),
          fb = order.indexOf(frameKeyOf(b.trustDomain || b.frame || null) || '')
    const ra = fa < 0 ? 99 : fa, rb = fb < 0 ? 99 : fb
    if (ra !== rb) return ra - rb
    return String(a.name || '').localeCompare(String(b.name || ''))
  })
  igniteOrder = []
  let i = 0
  for (const reg of regs) {
    // registryMeshes is the authority — there is no `registry-<id>` NAME on
    // these objects, and looking one up by a name nobody sets is a probe that
    // can only ever return nothing.
    const obj = registryMeshes.get(reg.id) || null
    if (!obj) continue
    igniteOrder.push({ obj, base: obj.scale.clone(), at: i * IGNITE_STAGGER_MS })
    i++
  }
  if (!igniteOrder.length) { igniteDone = true; return }
  igniteStart = performance.now()
  igniteAt = Date.now()
  igniteLit = igniteOrder.length
  igniteDone = false
}

function stepIgnition(nowMs: number): void {
  if (igniteDone) return
  const t = nowMs - igniteStart
  let allDone = true
  for (const it of igniteOrder) {
    const local = t - it.at
    if (local >= IGNITE_RISE_MS) { it.obj.scale.copy(it.base); continue }
    allDone = false
    const k = Math.max(0, local) / IGNITE_RISE_MS
    // easeOutBack: a system snaps into being rather than fading up.
    const e = k <= 0 ? 0 : 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2)
    it.obj.scale.copy(it.base).multiplyScalar(Math.max(0.001, e))
  }
  if (allDone) {
    for (const it of igniteOrder) it.obj.scale.copy(it.base)
    igniteOrder = []
    igniteDone = true
  }
}

/*
 * ─── #B19 THE TERRITORY PASS (strategy §2.2) ────────────────────────────────
 *
 * Depth without spectacle, and — this is the constraint that shaped every
 * choice below — without adding per-frame work that a machine with a real GPU
 * would feel. The Commander already reported lag once.
 *
 * THREE draw calls total, all additive, none of them rebuilt per frame:
 *   nebulae  one sprite per frame that has systems here, sized to the spread
 *            of those systems. Static; rebuilt only with the topology.
 *   coronas  one sprite per AGORA venue, brightness from the trades THIS
 *            SESSION SAW at that venue. Not "24h volume" — we do not have that
 *            number on the stage, and the pulse bar's rule applies: report what
 *            this session observed and never imply more.
 *   lanes    ONE LineSegments for every learned lane together. Traffic that
 *            repeats deposits a lane; lanes decay; the map ends up showing the
 *            economy's real shipping routes, which nobody drew by hand.
 *
 * Everything here is derived from observed events or from the topology already
 * on screen. Nothing is invented, and a quiet network gets a quiet map.
 */
const LANE_MAX = 14
const LANE_MIN_HITS = 4
// LANE_DECAY_MS lives with the fade it belongs to (services/bridge/lane.ts), so
// the filter that DROPS a lane and the curve that DIMS it cannot drift apart.
const LANE_REBUILD_MS = 1000
interface Lane { a: THREE.Vector3; b: THREE.Vector3; hits: number; last: number }
const lanes = new Map<string, Lane>()
let laneMesh: THREE.LineSegments | null = null
let laneLastBuild = 0
let territoryGroup: THREE.Group | null = null
/** Trades observed per frame this session — the corona's only input. */
const venueActivity = new Map<string, number>()
let coronaSprites: Array<{ sprite: THREE.Sprite; frame: string }> = []

/*
 * §BRIDGE R14.2 — TAXONOMY OPTION C: THE 81 COUNTED-ONLY TYPES AS WEATHER.
 *
 * 115 of 196 event types are drawn as motion; 81 are known and deliberately
 * silent, led by `LedgerBalanceChanged` — the double-entry shadow of movements
 * already on the stage. They must never become arcs (that would double-count
 * money on screen), but being completely invisible makes the stage imply the
 * network only does 115 things.
 *
 * So they become DENSITY, not motion: a frame doing a lot of bookkeeping
 * breathes very slightly brighter. Deliberately built on the sprite that is
 * ALREADY in the scene and ALREADY updated once a frame by `stepTerritory` —
 * zero new objects, zero new draw calls, zero new per-frame loops. That is the
 * only shape of C that can pass a render budget, and C was approved on the
 * explicit condition that it is measured against 5.6-6.8 ms.
 */
let frameFieldSprites: Array<{ sprite: THREE.Sprite; frame: string; authored: number }> = []
/** Counted-only events seen per frame, decaying. Never a rate we did not observe. */
const frameWeather = new Map<string, number>()
/** Every counted-only event this session, for the stats seam. Monotonic. */
let weatherSeen = 0
/* R14.1 — verbs spawned, and how many carried a finite amount to grade.
 * Without this pair, an empty grading census cannot distinguish "the wire had
 * no amounts in this window" from "observe() is never called" — and those are a
 * quiet network and a dead feature respectively. */
let verbsSpawned = 0
let verbsWithAmount = 0
/* Decay is expressed PER SECOND and applied against real elapsed time.
 * It was briefly per-STEP, which is per FRAME: at 30fps that is 0.94^30 =
 * 0.15/second, so the weather would have collapsed within a second and looked
 * like flicker. A rate constant only means something next to the clock it is
 * measured against. */
const WEATHER_DECAY_PER_SEC = 0.90   // ~7s to half, ~25s to fade out
const WEATHER_MAX_BOOST = 1.9        // ceiling on the multiplier over authored
let weatherLastStep = 0

/** One counted-only event, attributed to the frame that delivered it. */
function noteWeather(frameKey: string | null | undefined): void {
  const k = (frameKey || '').trim()
  if (!k) return
  weatherSeen++
  frameWeather.set(k, Math.min(60, (frameWeather.get(k) || 0) + 1))
}

/*
 * The density cloud. Rebuilt only when the population or the topology changes —
 * never per frame — and skipped entirely outside mission mode so /galactic-map
 * and /galactic-command are untouched.
 */
let densityPoints: THREE.Points | null = null
let densityCount = 0
/** §BRIDGE R10 — WHERE the population actually landed, per registry. The
 *  Commander reported "i dont see all sim agents orbiting frame-c"; a total
 *  ("5732 drawn") cannot answer that, only a per-registry breakdown can. */
const densityByReg = new Map<string, number>()
let densityUnplaced = 0
function buildDensity(): void {
  if (!IS_MISSION || !scene) return
  if (densityPoints) {
    scene.remove(densityPoints)
    densityPoints.geometry.dispose()
    ;(densityPoints.material as THREE.PointsMaterial).dispose()
    densityPoints = null
  }
  densityCount = 0
  densityByReg.clear()
  densityUnplaced = 0
  const pop = props.densityAgents || []
  if (!pop.length) return

  const pos: number[] = []
  const col: number[] = []
  const c = new THREE.Color()
  for (const a of pop) {
    if (!a?.did) continue
    // Same deterministic DID-seeded orbit every individual star gets — a point
    // in this cloud is in the same place it would be if it were promoted to a
    // star, so nothing jumps when it is.
    const regId = a.registryId || props.registries[0]?.id || '__local__'
    const center = registryPositions.get(regId)
    if (!center) { densityUnplaced++; continue }
    const h = hashDID(a.did)
    const rng = seededRandom(h)
    const u1 = Math.max(rng(), 1e-4)
    const u2 = rng()
    const gauss = Math.abs(Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2))
    const span = AGENT_CLOUD_RADIUS - AGENT_INNER_RADIUS
    const dist = AGENT_INNER_RADIUS + Math.min(span, gauss * span * 0.45)
    const ang = rng() * Math.PI * 2
    const inc = (rng() - 0.5) * 0.6
    const yOff = (rng() - 0.5) * 2.0
    pos.push(
      center.x + dist * Math.cos(ang),
      center.y + yOff + dist * Math.sin(inc) * Math.sin(ang),
      center.z + dist * Math.sin(ang) * Math.cos(inc),
    )
    const tint = FRAME_TINT[frameKeyOf(a.frame || null) || ''] ?? 0x8fa7c8
    c.setHex(tint)
    col.push(c.r, c.g, c.b)
    densityByReg.set(regId, (densityByReg.get(regId) || 0) + 1)
    densityCount++
  }
  if (!densityCount) return

  const geom = new THREE.BufferGeometry()
  geom.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
  geom.setAttribute('color', new THREE.Float32BufferAttribute(col, 3))
  // A textured point, not a bare one. An untextured PointsMaterial draws SQUARES,
  // and 5,700 bright squares read as pixel confetti rather than as a population
  // (seen, screenshot 2026-08-19). Reuse the same pre-baked radial glow the verb
  // layer uses — no new texture, no bloom pass, and it turns the cloud into the
  // haze it is supposed to be.
  // §BRIDGE R10 — LEGIBILITY. The Commander: "i dont see all sim agents
  // displayed orbiting frame-c". Measured, the placement was already right:
  // 5,733 points, 0 unplaced, Frame C 1,881 / Registry-A 1,606 / Frame-B 1,575.
  // What was wrong is that at size 0.55 / opacity 0.22 the cloud reads as film
  // grain rather than as a population. Raised until the orbits are visible and
  // no further — this is still atmosphere behind the stars that matter, and it
  // costs nothing per frame either way (one draw call, no new geometry).
  const mat = new THREE.PointsMaterial({
    map: glowTexture || undefined,
    size: 0.85, sizeAttenuation: true, vertexColors: true,
    transparent: true, opacity: 0.38, depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  densityPoints = new THREE.Points(geom, mat)
  densityPoints.name = 'bridge-density'
  densityPoints.frustumCulled = false
  scene.add(densityPoints)
}

function buildTerritory(): void {
  if (!scene) return
  // Topology changed: re-survey the GEOMETRY, keep what the session LEARNED.
  // Wiping the lanes here would have quietly defeated the whole feature — the
  // topology refreshes on a timer, so every lane and every observed trade was
  // being erased before it could accumulate.
  if (territoryGroup) disposeTerritory({ keepLearned: true })
  territoryGroup = new THREE.Group()
  territoryGroup.name = 'bridge-territory'

  // ── nebulae: one soft field per frame present on this map ────────────────
  const byFrame = new Map<string, THREE.Vector3[]>()
  for (const reg of props.registries) {
    const key = frameKeyOf(reg.trustDomain || reg.frame || null)
    const p = registryPositions.get(reg.id)
    if (!key || !p) continue
    if (!byFrame.has(key)) byFrame.set(key, [])
    byFrame.get(key)!.push(p)
  }
  for (const [key, pts] of byFrame) {
    if (!pts.length) continue
    const c = new THREE.Vector3()
    for (const p of pts) c.add(p)
    c.divideScalar(pts.length)
    let r = 0
    for (const p of pts) r = Math.max(r, p.distanceTo(c))
    const mat = new THREE.SpriteMaterial({
      map: glowTexture, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
      color: new THREE.Color(FRAME_TINT[key] ?? 0x8899aa),
      opacity: 0.055,          // a tint you notice only when it is missing
    })
    const sp = new THREE.Sprite(mat)
    sp.position.copy(c)
    sp.scale.setScalar(Math.max(40, r * 2.6))
    territoryGroup.add(sp)
    // R14.2: this sprite already exists and is already drawn. Option C rides it.
    frameFieldSprites.push({ sprite: sp, frame: key, authored: 0.055 })

    // ── venue corona: the same place, tighter and answerable to real trades ─
    const cmat = new THREE.SpriteMaterial({
      map: glowTexture, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
      color: new THREE.Color(FRAME_TINT[key] ?? 0x8899aa),
      opacity: 0,              // silent until this session actually sees a trade
    })
    const csp = new THREE.Sprite(cmat)
    csp.position.copy(c)
    csp.scale.setScalar(Math.max(14, r * 0.7))
    territoryGroup.add(csp)
    coronaSprites.push({ sprite: csp, frame: key })
  }

  // ── learned lanes: one mesh for all of them ──────────────────────────────
  const geom = new THREE.BufferGeometry()
  geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(LANE_MAX * 6), 3))
  // §BRIDGE R8 — PER-LANE colour, so each lane can carry its OWN age.
  // He reported "traffic trails not all disappearing". Measured: stray verb
  // lines = 0 (the verb pool releases correctly) — what persists is THIS layer,
  // and the reason it read as stuck is that every lane was drawn at one shared
  // opacity for its whole 120s life and then blinked out. A thing that holds
  // steady and vanishes looks broken; a thing that visibly fades looks like
  // weather. Same layer, same one draw call, same cost.
  geom.setAttribute('color', new THREE.BufferAttribute(new Float32Array(LANE_MAX * 6), 3))
  geom.setDrawRange(0, 0)
  const lmat = new THREE.LineBasicMaterial({
    // Faint on purpose. A shipping lane is something you notice on the second
    // look; at 0.16 with 24 of them the map read as a spiderweb rather than as
    // territory (seen, not theorised — screenshot 2026-08-19).
    // With vertexColors the final colour is material.color * vertexColor, so the
    // tint now lives in the attribute and this stays white.
    transparent: true, opacity: 0.16, depthWrite: false,
    blending: THREE.AdditiveBlending, color: new THREE.Color(0xffffff),
    vertexColors: true,
  })
  laneMesh = new THREE.LineSegments(geom, lmat)
  laneMesh.frustumCulled = false
  territoryGroup.add(laneMesh)

  scene.add(territoryGroup)
}

/** Quantised key for a pair of endpoints — same corridor, same lane. */
function laneKey(a: THREE.Vector3, b: THREE.Vector3): string {
  const q = (v: THREE.Vector3) => `${v.x.toFixed(0)}_${v.y.toFixed(0)}_${v.z.toFixed(0)}`
  const ka = q(a), kb = q(b)
  return ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`
}

/** A crossing was observed. Deposit it; the lane appears once it REPEATS. */
function noteLane(a: THREE.Vector3, b: THREE.Vector3): void {
  const k = laneKey(a, b)
  const now = Date.now()
  const cur = lanes.get(k)
  if (cur) { cur.hits++; cur.last = now; return }
  if (lanes.size >= LANE_MAX * 3) {
    let oldestK: string | null = null, oldestT = Infinity
    for (const [kk, l] of lanes) if (l.last < oldestT) { oldestT = l.last; oldestK = kk }
    if (oldestK) lanes.delete(oldestK)
  }
  lanes.set(k, { a: a.clone(), b: b.clone(), hits: 1, last: now })
}

/** Rebuild the lane geometry at most once a second, never per event. */
function stepTerritory(nowMs: number): void {
  if (!laneMesh) return
  if (densityPoints) {
    // The lens dims the galaxy, and the galaxy now includes the population.
    const m = densityPoints.material as THREE.PointsMaterial
    const target = fleetLensOn ? 0.05 : 0.22
    m.opacity += (target - m.opacity) * 0.08
  }
  /* R14.2 — the counted-only weather, folded into the loop that was already
   * running. log10 so a single bookkeeping event is visible and ten thousand do
   * not blow the frame out; the decay means this reports the RECENT minute
   * rather than the session total, which is the honest claim for a live gauge. */
  const wDt = weatherLastStep ? Math.min(1, (nowMs - weatherLastStep) / 1000) : 0
  weatherLastStep = nowMs
  const wDecay = Math.pow(WEATHER_DECAY_PER_SEC, wDt)
  for (const ff of frameFieldSprites) {
    const w = frameWeather.get(ff.frame) || 0
    const boost = w === 0 ? 0 : Math.min(WEATHER_MAX_BOOST, Math.log10(1 + w) * 1.35)
    const target = ff.authored * (1 + boost)
    const fm = ff.sprite.material as THREE.SpriteMaterial
    // The opacity still eases every frame; only the LEVEL decays on the clock.
    fm.opacity += (target - fm.opacity) * 0.06
    if (w > 0) frameWeather.set(ff.frame, w * wDecay < 0.05 ? 0 : w * wDecay)
  }
  for (const { sprite, frame } of coronaSprites) {
    const n = venueActivity.get(frame) || 0
    // log, so one trade is visible and a thousand does not blow out.
    const target = n === 0 ? 0 : Math.min(0.16, 0.03 + Math.log10(1 + n) * 0.04)
    const m = sprite.material as THREE.SpriteMaterial
    m.opacity += (target - m.opacity) * 0.05
    if (m.opacity > 0.001) {
      sprite.scale.setScalar(sprite.scale.x * (1 + Math.sin(nowMs * 0.0011) * 0.0006))
    }
  }
  if (nowMs - laneLastBuild < LANE_REBUILD_MS) return
  laneLastBuild = nowMs
  const pos = laneMesh.geometry.getAttribute('position') as THREE.BufferAttribute
  const col = laneMesh.geometry.getAttribute('color') as THREE.BufferAttribute
  const arr = pos.array as Float32Array
  const carr = col.array as Float32Array
  const live = Array.from(lanes.values())
    .filter(l => l.hits >= LANE_MIN_HITS && (nowMs - l.last) < LANE_DECAY_MS)
    .sort((x, y) => y.hits - x.hits)
    .slice(0, LANE_MAX)
  let i = 0, c = 0
  for (const l of live) {
    arr[i++] = l.a.x; arr[i++] = l.a.y; arr[i++] = l.a.z
    arr[i++] = l.b.x; arr[i++] = l.b.y; arr[i++] = l.b.z
    // The arithmetic lives in `services/bridge/lane.ts` and is unit-tested there:
    // a fade cannot be proven on a live network, because a corridor in constant
    // use is SUPPOSED to stay bright — the live probe read full strength on every
    // sample and could not tell a working fade from a stuck one.
    const k = laneBrightness(nowMs - l.last, l.hits)
    // The lane tint (0x7fa6d8) now rides the attribute.
    const r = 0.498 * k, g = 0.651 * k, bl = 0.847 * k
    carr[c++] = r; carr[c++] = g; carr[c++] = bl
    carr[c++] = r; carr[c++] = g; carr[c++] = bl
  }
  pos.needsUpdate = true
  col.needsUpdate = true
  laneMesh.geometry.setDrawRange(0, live.length * 2)
}

function disposeDensity(): void {
  if (!densityPoints) return
  densityPoints.geometry.dispose()
  ;(densityPoints.material as THREE.PointsMaterial).dispose()
  if (scene) scene.remove(densityPoints)
  densityPoints = null
  densityCount = 0
}

function disposeTerritory(opts?: { keepLearned?: boolean }): void {
  if (!opts?.keepLearned) {
    lanes.clear()
    venueActivity.clear()
  }
  coronaSprites = []
  frameFieldSprites = []
  if (laneMesh) {
    laneMesh.geometry.dispose()
    ;(laneMesh.material as THREE.LineBasicMaterial).dispose()
    laneMesh = null
  }
  if (territoryGroup) {
    for (const o of territoryGroup.children) {
      const anyO = o as any
      anyO.material?.dispose?.()
      anyO.geometry?.dispose?.()
    }
    if (scene) scene.remove(territoryGroup)
    territoryGroup = null
  }
}

/** Pause the stage whenever it cannot be seen. Zero GPU, zero lost truth. */
function setupVisibilityPause(): void {
  if (typeof document === 'undefined') return
  const onVis = () => { missionPaused = document.hidden }
  document.addEventListener('visibilitychange', onVis)
  missionVisCleanup = () => document.removeEventListener('visibilitychange', onVis)
  if (typeof IntersectionObserver !== 'undefined' && containerRef.value) {
    missionObserver = new IntersectionObserver(
      entries => { for (const e of entries) missionPaused = document.hidden || !e.isIntersecting },
      { threshold: 0.01 },
    )
    missionObserver.observe(containerRef.value)
  }
}
let missionVisCleanup: (() => void) | null = null

/** Lift to full frame rate for a beat after any interaction. */
function missionBoost(ms = 1200): void {
  if (IS_MISSION) missionBoostUntil = performance.now() + ms
}

/**
 * #B8 — turn the fleet lens on or off. Imperative (not a prop) because the HUD
 * owns the keyboard and the canvas owns the frame loop; a reactive prop would
 * add a render tick to something that is read inside the animate loop.
 */
function setFleetLens(on: boolean): void {
  if (!IS_MISSION) return
  fleetLensOn = !!on
  missionBoost(900)   // the transition deserves full frame rate while it eases
}

/*
 * #B13 FOLLOW MODE (strategy §3) — "pins the camera to one agent's activity".
 *
 * The camera EASES toward that agent and holds; it does not snap, and it does
 * not seize control: any orbit interaction ends the follow, because a camera
 * that fights the person holding the mouse is a camera nobody trusts. If the
 * agent has no position on this map — most of the population is outside the
 * locations sample — following it is refused rather than faked.
 */
let followDid: string | null = null
let followMiss = 0
function setFollowAgent(did: string | null): boolean {
  if (!IS_MISSION) return false
  if (!did) { followDid = null; return false }
  const pos = agentPositions.get(did) || agentPositions.get(did.toLowerCase())
  if (!pos) { followDid = null; return false }   // no position -> no pretending
  followDid = did
  followMiss = 0
  missionBoost(1800)
  return true
}
function isFollowing(): string | null { return followDid }

/** Ease the camera toward the followed agent. Called once per frame, cheap. */
function stepFollow(): void {
  if (!followDid || !controls) return
  const pos = agentPositions.get(followDid) || agentPositions.get(followDid.toLowerCase())
  if (!pos) {
    // It left the map (LOD churn, a re-survey). Give it a moment, then stop —
    // silently following nothing would look like the camera had frozen.
    if (++followMiss > 120) followDid = null
    return
  }
  followMiss = 0
  controls.target.lerp(pos, 0.06)
  const want = pos.clone().add(new THREE.Vector3(0, 12, 34))
  camera.position.lerp(want, 0.035)
  controls.update()
}

/**
 * FORENSICS on endpoint resolution (§BRIDGE R5, the Commander 2026-08-19:
 * "the traffic is mostly going from the empty space to the empty space ...
 *  do the math. do the forensics to nail down why").
 *
 * Every endpoint lands in exactly one of these buckets, and the unresolved
 * hints are kept verbatim so the answer is a LIST OF REAL IDENTIFIERS rather
 * than a theory about what might be missing.
 */
const resolveTally = { agentStar: 0, registry: 0, didToRegistry: 0, frameAnchor: 0, unresolved: 0 }
const unresolvedHints = new Map<string, number>()
function noteUnresolved(hint: string | null): void {
  const k = hint || '(null)'
  unresolvedHints.set(k, (unresolvedHints.get(k) || 0) + 1)
  if (unresolvedHints.size > 200) unresolvedHints.delete(unresolvedHints.keys().next().value as string)
}

/** Resolve a descriptor endpoint (registry slug, id or frame key) to a position. */
function resolveNodePosition(hint: string | null, frame: string | null): THREE.Vector3 | null {
  if (hint) {
    let h = hint.toLowerCase()
    // A party is a DID, not a registry. Translate first, then resolve as usual;
    // an unmapped DID falls through to the frame fallback below.
    if (h.startsWith('did:') || h.startsWith('teg:')) {
      // A star of its own beats any registry: if this party is on the map —
      // the viewer's agent OR a counterparty we chose to show — the arc ends on
      // the body itself rather than on the glyph of the system hosting it.
      const own = agentPositions.get(hint) || agentPositions.get(h)
      if (own) { resolveTally.agentStar++; return own }
      const reg = didRegistryMap.get(h)
      if (reg) {
        h = reg.toLowerCase()
        resolveTally.didToRegistry++
      } else {
        // No registry for this party. Descend the ladder of REAL places:
        // its own frame, then the frame it settles in as a system account,
        // then the frame that delivered the event. Never an average.
        const own = didFrameMap.get(h)
        const sys = systemAccountFrame(h, frame)
        const anchor = frameAnchorPosition(own || null)
          || frameAnchorPosition(sys || null)
          || frameAnchorPosition(frame)
        if (anchor) { resolveTally.frameAnchor++; return anchor }
        noteUnresolved(hint)
        resolveTally.unresolved++
        return null
      }
    }
    for (const reg of props.registries) {
      if (reg.name?.toLowerCase() === h || reg.id?.toLowerCase() === h || reg.displayName?.toLowerCase() === h) {
        const p = registryPositions.get(reg.id)
        if (p) { resolveTally.registry++; return p }
      }
    }
    // Slug families: `cloud-op-op-tokyo-registry` should still find `op-tokyo`.
    for (const reg of props.registries) {
      const n = reg.name?.toLowerCase() || ''
      if (n && (h.includes(n) || n.includes(h))) {
        const p = registryPositions.get(reg.id)
        if (p) { resolveTally.registry++; return p }
      }
    }
    if (!h.startsWith('did:')) noteUnresolved(hint)
  }
  if (frame) {
    // THE CENTROID IS GONE (2026-08-19). It averaged a frame's systems into a
    // point with nothing at it, and then drew traffic to and from that point:
    // "the traffic is mostly going from the empty space to the empty space".
    // A frame's anchor is its mainframe registry — somewhere that exists.
    const anchor = frameAnchorPosition(frame)
    if (anchor) { resolveTally.frameAnchor++; return anchor }
  }
  resolveTally.unresolved++
  return null
}

/**
 * Rolling record of how long OUR draw takes. Ring buffer, no allocation per
 * frame, no reactivity — it must not itself cost what it measures.
 */
const RENDER_SAMPLES = 240
const renderMsRing = new Float32Array(RENDER_SAMPLES)
let renderMsCount = 0
function recordRenderMs(ms: number): void {
  renderMsRing[renderMsCount % RENDER_SAMPLES] = ms
  renderMsCount++
}
function renderMsStats(): { n: number; p50: number; p90: number; max: number } | null {
  const n = Math.min(renderMsCount, RENDER_SAMPLES)
  if (!n) return null
  const a = Array.from(renderMsRing.slice(0, n)).sort((x, y) => x - y)
  const q = (p: number) => a[Math.min(n - 1, Math.floor(n * p))]
  return { n, p50: +q(0.5).toFixed(2), p90: +q(0.9).toFixed(2), max: +a[n - 1].toFixed(2) }
}

/** #B18 — the tail of each live story: where its last leg finished. */
const CHAIN_TTL_MS = 30_000
const CHAIN_MAX = 96
const chainTail = new Map<string, { pos: THREE.Vector3; t: number }>()

function acquireVerb(): VerbObj | null {
  for (const v of verbPool) if (!v.alive) return v
  verbsDroppedForPool.value++
  return null
}

/**
 * Feed the stage. Called by Mission Control with one COALESCED batch per frame
 * (never per event). Descriptors in, motion out — the canvas never parses an
 * event and never decides what an event means; that is grammar.ts's job.
 */
function pushVerbs(batch: any[]): void {
  if (!IS_MISSION || !verbGroup || missionPaused) return
  for (const d of batch) {
    const v = acquireVerb()
    if (!v) return                       // pool full: the rest are counted, not drawn

    // DID first: on this network the party fields are populated and the
    // registry fields almost never are, so asking for the slug first meant
    // asking the question that has no answer.
    // BOTH ends fall back to the DELIVERING frame, not just the origin.
    //
    // `toFrame` is null for every event that did not cross frames — which is
    // most of them — so the destination had no fallback at all and resolved to
    // nothing. Measured before this line changed: 60 of 185 endpoints
    // unresolved, including `teg:system:fee_collector` ten times over. A null
    // `toFrame` does not mean "unknown", it means "did not leave this frame",
    // so the delivering frame is the correct answer rather than a guess.
    let fromPos = resolveNodePosition(d.fromDid || d.from, d.fromFrame || d.frame)
    const toPos = resolveNodePosition(d.toDid || d.to, d.toFrame || d.frame)
    const base = VERB_TINT[d.verb] ?? 0x8899aa

    /*
     * #B18 COMPOSED SEQUENCES — strategy §2.4, and the Commander's own reading
     * of what he was looking at: "one is the fx agent anyway, so this is
     * expected to be not a straight registry->registry or even direct
     * agent->agent. its a chain that needs to be correct."
     *
     * He is describing an FX route exactly. A single cross-frame payment is
     * several ledger events — egress, swap, settle, fee — sharing one
     * correlation key (`fxroute:{id}`, `fxswap:{id}`, `guild-{oid}`, `tx:{id}`),
     * and drawing them as independent darts is what makes a coherent journey
     * look like unrelated flashes.
     *
     * So a leg that continues a story STARTS WHERE THE PREVIOUS LEG ENDED. That
     * is not a flourish, it is the truth about a route: leg two begins at the
     * gateway leg one reached. Bounded map, short TTL, pruned on use — a story
     * nobody has added to for half a minute is over.
     */
    const chained = d.correlationKey ? chainTail.get(d.correlationKey) : undefined
    if (chained && (Date.now() - chained.t) < CHAIN_TTL_MS) {
      // Only when it actually moves the start somewhere else; a chain that
      // begins where we already were is not a chain, it is the same point.
      if (!fromPos || !chained.pos.equals(fromPos)) fromPos = chained.pos.clone()
      v.chained = true
    } else {
      v.chained = false
    }

    if (d.verb === 'trade') {
      const fk = frameKeyOf(d.toFrame || d.fromFrame || d.frame)
      if (fk) venueActivity.set(fk, (venueActivity.get(fk) || 0) + 1)
    }

    v.alive = true
    v.desc = d
    v.mine = !!d.mine
    v.reverted = !!d.reverted
    v.t = 0
    /* §BRIDGE R14.1 — grade this amount against its OWN currency.
     * Observe first, then grade: an event is part of the distribution it is
     * measured against, which is what keeps a lone huge payment from grading
     * itself at 1.0 forever on an otherwise quiet frame.
     * The old line was `0.9 + amountClass*0.55`, i.e. a 0..2.2 span on a fixed
     * ladder. The span is UNCHANGED (0..2.2) so the largest photon is exactly
     * the size it was; only the distribution across that span moves. That also
     * means the per-frame cost cannot have changed: same max sprite, same
     * geometry, same draw calls. */
    verbsSpawned++
    if (typeof d.amount === 'number' && Number.isFinite(d.amount) && d.amount !== 0) verbsWithAmount++
    amountGrader.observe(d.currency, d.amount)
    const graded = amountGrader.grade(d.currency, d.amount)
    v.sizeGrade = graded.grade ?? 0
    v.brightGrade = graded.grade ?? 1
    v.scale = 0.9 + v.sizeGrade * 2.2 + (d.mine ? 1.1 : 0)

    if (toPos && fromPos && !toPos.equals(fromPos)) {
      // A real crossing: draw the arc.
      // V4 GUILD THREAD: an engagement is not a payment. It draws as a thin,
      // straight, slow thread from poster to worker that lingers and dissolves,
      // rather than a photon that flies. g1 CANARY: the same path, dashed and
      // faint - the system watching itself, visibly.
      // g2 CORRIDOR GLYPH (#B16). Federation and operator state is SCENERY: it
      // is the network describing its own plumbing, not value moving. It gets
      // the flat, patient thread rather than a photon's arc — so a corridor
      // event can never be mistaken for money at a glance — and it is never
      // red (that discipline belongs to V7 alone).
      const isThread = d.verb === 'guild' || d.verb === 'corridor'
      v.kind = isThread ? 'thread' : 'arc'
      v.from.copy(fromPos)
      v.to.copy(toPos)
      // #B19: value that repeatedly travels the same corridor deposits a lane.
      // Scenery and probes do not — a shipping route is where GOODS go.
      if (d.verb === 'transfer' || d.verb === 'fx' || d.verb === 'trade') noteLane(fromPos, toPos)
      v.dur = isThread ? 3.4 : d.verb === 'fx' ? 2.6 : 1.8
      // V2: an FX arc STARTS in the origin frame's colour and ENDS in the
      // destination frame's. The swap literally recolors the value in flight.
      v.colorA.setHex(d.verb === 'fx' && d.fromFrame ? (FRAME_TINT[d.fromFrame] ?? base) : base)
      v.colorB.setHex(d.verb === 'fx' && d.toFrame ? (FRAME_TINT[d.toFrame] ?? base) : base)
      const mid = v.from.clone().add(v.to).multiplyScalar(0.5)
      // A thread hangs almost flat between the two parties; a photon arcs.
      mid.y += v.from.distanceTo(v.to) * (isThread ? 0.06 : 0.28) + (isThread ? 1 : 4)
      // §BRIDGE R11 #9 — deflect around any registry the arc would otherwise
      // pass through. Pure math in `services/bridge/arcRoute.ts` so the claim
      // "the arc clears the obstacle" is proven by sampling in a unit test,
      // not by looking at a screenshot. A clear path returns the SAME control
      // point object, so traffic that was already fine is untouched, and the
      // geometry stays one quadratic Bezier — same draw call, same segments.
      const routed = routeAround(
        { x: v.from.x, y: v.from.y, z: v.from.z },
        { x: v.to.x, y: v.to.y, z: v.to.z },
        { x: mid.x, y: mid.y, z: mid.z },
        registryObstacles.map((o) => ({ pos: { x: o.pos.x, y: o.pos.y, z: o.pos.z }, radius: o.radius })),
      )
      if (routed.deflectedAround) { mid.set(routed.control.x, routed.control.y, routed.control.z); arcDeflections++ }
      v.curve = new THREE.QuadraticBezierCurve3(v.from.clone(), mid, v.to.clone())
      const pts = v.curve.getPoints(ARC_SEGMENTS)
      ;(v.line!.geometry as THREE.BufferGeometry).setFromPoints(pts)
      const lm0 = v.line!.material as THREE.LineDashedMaterial
      // A canary is the system watching itself: a fine, fast dash. A corridor
      // is the system DESCRIBING itself: a long, slow dash — visibly different
      // from both a payment and a probe, without adding a new material.
      if (d.verb === 'canary') { lm0.dashSize = 1.1; lm0.gapSize = 1.4 }
      else if (d.verb === 'corridor') { lm0.dashSize = 3.2; lm0.gapSize = 2.6 }
      else { lm0.dashSize = 1e6; lm0.gapSize = 0 }
      // LineDashedMaterial renders NOTHING without this, dashed or not.
      v.line!.computeLineDistances()
      v.line!.visible = true
    } else {
      // No second endpoint: a local event. Pulse where it happened.
      const at = fromPos || toPos || resolveNodePosition(null, d.frame)
      if (!at) { v.alive = false; continue }
      v.from.copy(at); v.to.copy(at)
      v.curve = null
      v.line!.visible = false
      v.kind = d.verb === 'birth' ? 'bloom' : d.verb === 'treasury' ? 'ring' : 'spark'
      v.dur = v.kind === 'bloom' ? 2.2 : v.kind === 'ring' ? 1.6 : 1.0
      v.colorA.setHex(base); v.colorB.setHex(base)
    }

    // Remember where this leg ended, so the next one can continue from it.
    if (d.correlationKey) {
      chainTail.set(d.correlationKey, { pos: v.to.clone(), t: Date.now() })
      if (chainTail.size > CHAIN_MAX) {
        const cutoff = Date.now() - CHAIN_TTL_MS
        for (const [k, tail] of chainTail) if (tail.t < cutoff) chainTail.delete(k)
        // Still over cap after expiry: drop the oldest until it fits. Geometry
        // budgets are not negotiable just because a route is chatty.
        if (chainTail.size > CHAIN_MAX) {
          const oldest = Array.from(chainTail.entries()).sort((a, b) => a[1].t - b[1].t)
          for (const [k] of oldest.slice(0, chainTail.size - CHAIN_MAX)) chainTail.delete(k)
        }
      }
    }

    v.head.visible = true
    v.head.position.copy(v.from)
    const hm = v.head.material as THREE.SpriteMaterial
    hm.color.copy(v.colorA)
    hm.opacity = 0
  }
  verbsActive.value = verbPool.reduce((n, v) => n + (v.alive ? 1 : 0), 0)
}

/** Advance every live verb. Pure math on pooled objects; zero allocation. */
function stepVerbLayer(delta: number, _elapsed: number): void {
  if (!verbGroup) return
  let active = 0
  for (const v of verbPool) {
    if (!v.alive) continue
    v.t += delta / v.dur
    if (v.t >= 1) {
      v.alive = false
      v.desc = null            // do not retain finished events
      v.head.visible = false
      if (v.line) { v.line.visible = false; (v.line.material as THREE.LineBasicMaterial).opacity = 0 }
      ;(v.head.material as THREE.SpriteMaterial).opacity = 0
      continue
    }
    active++      // count what is still FLYING, not what retired this frame
    const t = v.t
    // Ease-in-out so a photon accelerates out of its origin and settles at its
    // destination, instead of sliding at a constant, mechanical speed.
    const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
    const fade = Math.sin(Math.PI * t)          // 0 -> 1 -> 0 over the lifetime
    const hm = v.head.material as THREE.SpriteMaterial
    // #B8: with the lens on, everyone else's traffic is still drawn - just quiet.
    const lens = (fleetLensOn && !v.mine) ? LENS_OTHER : 1
    const dim = (v.reverted ? 0.45 : 1) * lens

    if (v.kind === 'arc' && v.curve) {
      // Reduced motion: sit at the destination and let the fade do the telling.
      v.curve.getPoint(REDUCED_MOTION ? 1 : e, v.head.position)
      hm.color.copy(v.colorA).lerp(v.colorB, e)   // the midpoint recolor
      // R14.1: at brightGrade 1 this is `fade * 0.95 * dim` to the byte.
      hm.opacity = fade * (0.62 + 0.33 * v.brightGrade) * dim
      v.head.scale.setScalar(v.scale * (v.mine ? 3.0 : 2.1))
      if (v.line) {
        const lm = v.line.material as THREE.LineDashedMaterial
        lm.color.copy(hm.color)
        lm.opacity = fade * (v.mine ? 0.5 : 0.22) * (0.65 + 0.35 * v.brightGrade) * dim
        // #B10 COMET TRAIL — your own photons drag a tail so they are findable
        // in a busy sky. Rewrites the pooled geometry in place (no allocation),
        // and only for `mine`, which is a handful of objects at a time.
        if (v.mine && !REDUCED_MOTION) {
          const posAttr = (v.line.geometry as THREE.BufferGeometry).getAttribute('position') as THREE.BufferAttribute
          // R14.1: the tail is the third graded channel. At grade 1 the
          // multiplier is 1.0, i.e. COMET_TAIL exactly as before.
          const tail = Math.max(0, e - COMET_TAIL * (0.45 + 0.55 * v.sizeGrade))
          for (let i = 0; i <= ARC_SEGMENTS; i++) {
            v.curve.getPoint(tail + (e - tail) * (i / ARC_SEGMENTS), _scratchVec)
            posAttr.setXYZ(i, _scratchVec.x, _scratchVec.y, _scratchVec.z)
          }
          posAttr.needsUpdate = true
          v.line.computeLineDistances()
        }
      }
    } else if (v.kind === 'thread' && v.curve) {
      // A thread does not travel: it is DRAWN between two parties, holds, then
      // dissolves. The head rides to the worker's end and settles there as the
      // glint the strategy asks for when the engagement lands.
      v.curve.getPoint(REDUCED_MOTION ? 1 : Math.min(1, t * 2.2), v.head.position)
      hm.color.copy(v.colorA)
      hm.opacity = fade * 0.8 * dim
      v.head.scale.setScalar(v.scale * (t > 0.45 ? 2.4 : 1.4))
      if (v.line) {
        const lm = v.line.material as THREE.LineDashedMaterial
        lm.color.copy(v.colorA)
        lm.opacity = fade * (v.mine ? 0.42 : 0.2) * dim
      }
    } else if (v.kind === 'bloom') {
      hm.opacity = fade * 0.9 * lens
      v.head.scale.setScalar(v.scale * (1.2 + e * 5.5))
    } else if (v.kind === 'ring') {
      hm.opacity = fade * 0.7 * dim
      // Inward for a stake, outward for a distribution: read the direction from
      // the sign of the move by drawing the ring collapsing then releasing.
      v.head.scale.setScalar(v.scale * (4.5 - e * 3.0))
    } else {
      hm.opacity = fade * 0.85 * dim
      v.head.scale.setScalar(v.scale * (1.6 + Math.sin(t * Math.PI * 3) * 0.35))
    }
  }
  verbsActive.value = active
}

function disposeVerbLayer(): void {
  disposeDensity()
  disposeTerritory()
  missionVisCleanup?.()
  missionVisCleanup = null
  missionObserver?.disconnect()
  missionObserver = null
  for (const v of verbPool) {
    ;(v.head.material as THREE.SpriteMaterial).dispose()
    if (v.line) {
      v.line.geometry.dispose()
      ;(v.line.material as THREE.LineBasicMaterial).dispose()
    }
  }
  verbPool.length = 0
  glowTexture?.dispose()
  glowTexture = null
  if (verbGroup && scene) scene.remove(verbGroup)
  verbGroup = null
}

// ─── Animation ───────────────────────────────────────────────────
function animate() {
  animationId = requestAnimationFrame(animate)

  // Guard: scene not ready yet. In mission mode there is no composer BY DESIGN,
  // so it must not be part of the readiness test.
  if (!clock || !scene || !camera || !controls) return
  if (!IS_MISSION && !composer) return

  if (IS_MISSION) {
    // §BRIDGE §8.3 — hard pause when the stage cannot be seen. A hidden tab or a
    // scrolled-away canvas costs zero GPU; the stream keeps counting regardless,
    // so nothing is lost, only not drawn.
    if (missionPaused) return
    // 30fps ambient. Interaction lifts to full rate for a beat (see onInteract).
    const nowMs = performance.now()
    const minGap = missionBoostUntil > nowMs ? 0 : MISSION_AMBIENT_FRAME_MS
    if (nowMs - missionLastFrameMs < minGap) return
    missionLastFrameMs = nowMs
  }

  // CRITICAL: getDelta() must be called BEFORE getElapsedTime()
  // Both reset the internal timer — calling elapsed first makes delta ~0
  const delta = clock.getDelta()
  const elapsed = clock.getElapsedTime()
  if (!REDUCED_MOTION) {
    if (connectionFlowMat) connectionFlowMat.uniforms.uTime.value = elapsed  // MAP-CINEMA link flow
    twinkleTime.value = elapsed                                              // MAP-CINEMA star twinkle
    if (filmPass) filmPass.uniforms.uTime.value = elapsed                    // MAP-CINEMA grain
  }

  // Update controls
  controls.update()

  // Animate registry planets
  const bobY = Math.sin(elapsed * 0.5) * 0.3
  registryMeshes.forEach((group, id) => {
    group.children.forEach(child => {
      // Slow planet rotation (like a real globe)
      if (child.userData?.isPlanetCore) {
        child.rotation.y += 0.001
      }
      // FIX-14: Animate dust particles
      if (child.userData?.isDust && child instanceof THREE.Points) {
        const posAttr = child.geometry.getAttribute('position') as THREE.BufferAttribute
        const vels = child.userData.velocities as THREE.Vector3[]
        const pSize = child.userData.planetSize as number
        for (let pi = 0; pi < posAttr.count; pi++) {
          let px = posAttr.getX(pi) + vels[pi].x
          let py = posAttr.getY(pi) + vels[pi].y
          let pz = posAttr.getZ(pi) + vels[pi].z
          const d = Math.sqrt(px * px + py * py + pz * pz)
          if (d > pSize * 3) {
            const theta = Math.random() * Math.PI * 2
            const phi = Math.acos(2 * Math.random() - 1)
            const rd = pSize * (1.0 + Math.random() * 0.2)
            px = rd * Math.sin(phi) * Math.cos(theta)
            py = rd * Math.sin(phi) * Math.sin(theta)
            pz = rd * Math.cos(phi)
          }
          posAttr.setXYZ(pi, px, py, pz)
        }
        posAttr.needsUpdate = true
      }
    })
    // FIX-08: Bob only the visual position offset, not the group origin
    // (orbit centers reference the original group.position which stays at registryPositions)
    // We apply bob as a Y offset on children so orbit.center stays correct
    const baseY = registryPositions.get(
      (group.userData?.data as MapRegistry)?.id || ''
    )?.y || 0
    group.position.y = baseY + bobY

    // GCC P11+ restart-visibility: while this registry id is mid-restart, blink the
    // whole orb translucent so the cockpit reads "busy until healthy" at a glance.
    // Material-opacity only — base opacity (+ transparent flag) is captured once and
    // restored verbatim when the restart clears, so nothing about the orb persists.
    const busy = busyIdSet.has(String(id))
    if (busy || group.userData._rsBusy) {
      const pulse = busy ? (0.32 + 0.46 * (0.5 + 0.5 * Math.sin(elapsed * 5.5))) : 1
      group.traverse((o: any) => {
        const mat = o.material
        if (!mat) return
        const apply = (m: any) => {
          if (!m) return
          if (m.userData._rsBase === undefined) { m.userData._rsBase = (m.opacity ?? 1); m.userData._rsTrans = !!m.transparent }
          if (busy) { m.transparent = true; m.opacity = m.userData._rsBase * pulse }
          else { m.opacity = m.userData._rsBase; m.transparent = m.userData._rsTrans }
        }
        Array.isArray(mat) ? mat.forEach(apply) : apply(mat)
      })
      group.userData._rsBusy = busy
    }
  })

  // Rotate red dwarf star + pulsing corona radiation
  if (redStarMesh) redStarMesh.rotation.y += 0.0005
  if (redStarGroup) {
    const pulse = 1.0 + Math.sin(elapsed * 0.8) * 0.08  // Slow gentle breathe
    redStarGroup.children.forEach(child => {
      if (child instanceof THREE.Sprite) {
        const baseScale = child.userData.baseScale || child.scale.x
        if (!child.userData.baseScale) child.userData.baseScale = baseScale
        child.scale.setScalar(baseScale * pulse)
      }
    })
  }

  // === AAA+ BLACK HOLE ANIMATION ===
  // Accretion disk: Keplerian orbits (inner particles faster)
  if (bhAccretionPoints && bhAccretionOffsets) {
    const pa = bhAccretionPoints.geometry.getAttribute('position') as THREE.BufferAttribute
    for (let i = 0; i < bhAccretionOffsets.length; i++) {
      const nr = Math.sqrt(pa.getX(i) ** 2 + pa.getZ(i) ** 2) || 30
      const speed = 0.3 / Math.pow(Math.max(nr - 25, 2) / 10, 0.8)
      bhAccretionOffsets[i] += speed * delta
      pa.setX(i, Math.cos(bhAccretionOffsets[i]) * nr)
      pa.setZ(i, Math.sin(bhAccretionOffsets[i]) * nr)
    }
    pa.needsUpdate = true
  }
  // === CINEMATIC STREAM: Plasma flowing from red dwarf → black hole ===
  if (bhStreamPoints && bhStreamOffsets) {
    const sp = bhStreamPoints.geometry.getAttribute('position') as THREE.BufferAttribute
    const sc = bhStreamPoints.geometry.getAttribute('color') as THREE.BufferAttribute
    const curve = new THREE.CubicBezierCurve3(
      RED_DWARF_POS,
      new THREE.Vector3(125, 55, -180),
      new THREE.Vector3(150, 25, -220),
      BH_POS.clone().add(new THREE.Vector3(0, 5, 0))
    )
    for (let i = 0; i < bhStreamOffsets.length; i++) {
      // Accelerates quadratically: slow leaving star, fast approaching BH
      const speed = 0.008 + bhStreamOffsets[i] * bhStreamOffsets[i] * 0.025
      bhStreamOffsets[i] += speed * delta * 60
      if (bhStreamOffsets[i] > 1) bhStreamOffsets[i] -= 1
      const t = bhStreamOffsets[i]
      const p = curve.getPointAt(t)
      // Wobble: large turbulent clumps near star, tight stream near BH
      const wobble = (1 - t) * 3.0
      p.x += Math.sin(elapsed * 2.5 + i * 0.3) * wobble
      p.y += Math.cos(elapsed * 1.8 + i * 0.5) * wobble * 0.7
      p.z += Math.sin(elapsed * 1.2 + i * 0.7) * wobble * 0.4
      sp.setXYZ(i, p.x, p.y, p.z)
      sc.setXYZ(i, 1, 0.1 + t * 0.8, t * t * 0.6)
    }
    sp.needsUpdate = true
    sc.needsUpdate = true
  }

  // === SPIRAL-IN: Particles decaying into the accretion disk ===
  if (bhSpiralPoints && bhSpiralOffsets && bhSpiralRadii) {
    const sp = bhSpiralPoints.geometry.getAttribute('position') as THREE.BufferAttribute
    const sc = bhSpiralPoints.geometry.getAttribute('color') as THREE.BufferAttribute
    for (let i = 0; i < bhSpiralOffsets.length; i++) {
      // Orbital decay: radius shrinks, speed increases
      const r = bhSpiralRadii[i]
      const keplerSpeed = 0.15 / Math.pow(Math.max(r - 25, 5) / 10, 0.7)
      bhSpiralOffsets[i] += keplerSpeed * delta
      bhSpiralRadii[i] -= (0.015 + (1 - r / 105) * 0.03) * delta * 60
      if (bhSpiralRadii[i] < 30) {
        bhSpiralRadii[i] = 50 + Math.random() * 55  // Respawn at outer edge
        bhSpiralOffsets[i] = Math.random() * Math.PI * 2
      }
      const nr = bhSpiralRadii[i]
      const turbulence = Math.sin(elapsed * 3 + i) * 0.5 * (nr / 105)
      sp.setXYZ(i, Math.cos(bhSpiralOffsets[i]) * nr, turbulence, Math.sin(bhSpiralOffsets[i]) * nr)
      const tNorm = 1 - (nr - 30) / 75
      sc.setXYZ(i, 1, 0.3 + tNorm * 0.6, tNorm * 0.5)
    }
    sp.needsUpdate = true
    sc.needsUpdate = true
  }

  // === IMPACT FLASHES at disk inner edge ===
  for (let i = 0; i < bhFlashSprites.length; i++) {
    bhFlashTimers[i] += delta
    const duration = 0.8 + (i * 0.4)  // 0.8-2.8s per flash
    const phase = (bhFlashTimers[i] % duration) / duration
    const intensity = Math.sin(phase * Math.PI)  // 0 → 1 → 0
    const mat = bhFlashSprites[i].material as THREE.SpriteMaterial
    mat.opacity = intensity * 0.6
    bhFlashSprites[i].scale.setScalar(5 + intensity * 10)
  }

  // === TIDAL TAIL pulsing ===
  if (tidalTailSprite) {
    const tailPulse = 1.0 + Math.sin(elapsed * 0.6) * 0.15
    tidalTailSprite.scale.set(35 * tailPulse, 12, 1)
    ;(tidalTailSprite.material as THREE.SpriteMaterial).opacity = 0.4 + Math.sin(elapsed * 0.8) * 0.1
  }

  // === RED DWARF TIDAL STRETCH toward BH ===
  if (redStarMesh) {
    const stretch = 1.12 + Math.sin(elapsed * 0.6) * 0.04
    // Stretch along the BH direction (approximate with Z-scale since BH is roughly behind+below)
    redStarMesh.scale.set(1, 1, stretch)
  }

  // === SMOOTH CAMERA FLY-TO ===
  if (flyToTarget && flyToProgress < 1) {
    controls.autoRotate = false              // don't let idle-drift fight the fly-to
    lastInteractionTime = Date.now()         // keep idle drift from re-engaging mid-flight
    flyToProgress += 0.015
    const t = flyToProgress * flyToProgress * (3 - 2 * flyToProgress)  // Smoothstep
    const targetCamPos = flyToTarget.clone().add(new THREE.Vector3(0, 20, 40))
    camera.position.lerp(targetCamPos, t * 0.05)
    controls.target.lerp(flyToTarget, t * 0.05)
    if (flyToProgress >= 1) flyToTarget = null
  }

  // === HOVER PROXIMITY GLOW ===
  if (camera) {
    const rayDir = new THREE.Vector3()
    camera.getWorldDirection(rayDir)
    registryMeshes.forEach((group, id) => {
      group.children.forEach(child => {
        if (!(child instanceof THREE.Sprite) || !child.userData.isAmbientGlow) return
        const pos = registryPositions.get(id)
        if (!pos) return
        const toReg = pos.clone().sub(camera.position)
        const proj = toReg.dot(rayDir)
        const perpDist = toReg.clone().sub(rayDir.clone().multiplyScalar(proj)).length()
        const glowBoost = Math.max(0, 1 - perpDist / 35) * 0.18
        // GC3: ambient glow participates in the search-focus dim (this pass owns
        // its opacity every frame, so the factor multiplies HERE, not in the dim pass).
        ;(child.material as THREE.SpriteMaterial).opacity = ((child.userData.baseOpacity || 0.12) + glowBoost) * envDimFactor
      })
    })
  }

  // === SELECTED AGENT ORBIT RING ===
  if (props.selectedAgentDid) {
    const orbit = agentOrbits.get(props.selectedAgentDid)
    if (orbit && !selectedOrbitRing) {
      const ringGeo = new THREE.TorusGeometry(orbit.radius, 0.06, 8, 64)
      const ringMat = new THREE.MeshBasicMaterial({
        color: 0x00e5ff, transparent: true, opacity: 0.35,
        blending: THREE.AdditiveBlending, depthWrite: false,
      })
      selectedOrbitRing = new THREE.Mesh(ringGeo, ringMat)
      selectedOrbitRing.position.copy(orbit.center)
      selectedOrbitRing.rotation.x = Math.PI / 2 + orbit.inclination
      scene.add(selectedOrbitRing)
    }
  } else if (selectedOrbitRing) {
    scene.remove(selectedOrbitRing)
    selectedOrbitRing.geometry.dispose()
    selectedOrbitRing = null
  }

  // === IDLE CAMERA DRIFT ===
  const idleMs = Date.now() - lastInteractionTime
  if (idleMs > 30000) {
    controls.autoRotate = true
    controls.autoRotateSpeed = 0.15
    camera.position.y += Math.sin(elapsed * 0.2) * 0.015  // Gentle vertical bob
  }

  // Animate agents: gentle float + selection pulse
  if (agentInstancedMesh && agentDataMap.length > 0) {
    const dummy = new THREE.Object3D()
    const color = new THREE.Color()
    let needsMatrixUpdate = false
    let needsColorUpdate = false

    for (let i = 0; i < agentDataMap.length; i++) {
      const agent = agentDataMap[i]
      if (!agent) continue

      const basePos = agentPositions.get(agent.did)
      if (!basePos) continue

      // Selected agent pulse
      const isSelected = props.selectedAgentDid === agent.did
      const isHighlighted = props.highlightCapability
        ? agent.capabilities.includes(props.highlightCapability)
        : false
      const isDimmed = props.highlightCapability && !isHighlighted
      // GC3: same rule the pick sites use — dimmed and non-interactive can't disagree
      const isSearchMatch = !!props.searchQuery && agentMatchesSearch(agent)
      const isSearchDimmed = props.searchQuery && !isSearchMatch

      // ORBITAL ROTATION: move agent around its registry
      const orbit = agentOrbits.get(agent.did)
      if (orbit) {
        // R16.1: derived, never accumulated. `clock` is created once at renderer
        // init and is NOT touched by buildAgents(), so this is continuous across
        // every rebuild — which is precisely what the old `+=` was not.
        const ang = orbit.startAngle + orbit.speed * elapsed
        const nx = orbit.center.x + orbit.radius * Math.cos(ang)
        const ny = orbit.center.y + orbit.yOffset + orbit.radius * Math.sin(orbit.inclination) * Math.sin(ang)
        const nz = orbit.center.z + orbit.radius * Math.sin(ang) * Math.cos(orbit.inclination)
        basePos.set(nx, ny, nz)  // Update stored position (for raycasting + labels)
      }

      // Gentle float on top of orbit
      const phase = (hashDID(agent.did) % 1000) / 1000 * Math.PI * 2
      const floatY = Math.sin(elapsed * 0.4 + phase) * 0.15

      // FIX-07: Hover visual feedback
      const isHovered = i === hoveredInstanceIdx

      const size = getAgentSize(agent.liquidBalance, agent.stakedBalance)
      let scale = size

      if (isSearchMatch) {
        // Search standout (toned GC3): steady presence + slow breath — the
        // environment dim provides the contrast, the agent shouldn't strobe.
        scale = size * (1.45 + Math.sin(elapsed * 1.8) * 0.12)
        needsMatrixUpdate = true
      } else if (isSelected) {
        scale = size * (1.0 + Math.sin(elapsed * 3) * 0.15)
        needsMatrixUpdate = true
      } else if (isHovered) {
        scale = size * 1.3  // FIX-07: Pop up on hover
        needsMatrixUpdate = true
      } else if (isSearchDimmed) {
        scale = size * 0.78  // GC3: filtered-out agents recede in crowded orbits
        needsMatrixUpdate = true
      }

      dummy.position.set(basePos.x, basePos.y + floatY, basePos.z)
      dummy.scale.setScalar(scale)
      dummy.updateMatrix()
      agentInstancedMesh!.setMatrixAt(i, dummy.matrix)

      // Color updates for selection/highlighting/hover
      if (isSearchMatch) {
        // Warm-gold glow, slow breath (toned GC3 — the old 3.5Hz pulse read as blinking).
        const g = 0.74 + Math.abs(Math.sin(elapsed * 1.8)) * 0.12
        color.setRGB(g, g * 0.85, g * 0.34)
        needsColorUpdate = true
      } else if (isSelected) {
        color.setHex(COLORS.selected)
        needsColorUpdate = true
      } else if (isHovered) {
        color.setHex(COLORS.hover)  // FIX-07: White flash on hover
        needsColorUpdate = true
      } else if (isDimmed || isSearchDimmed) {
        color.setRGB(0.09, 0.095, 0.12)  // GC3: deeper grey — real contrast, not a tint
        needsColorUpdate = true
      } else {
        const c = getAgentColor(agent.reputation, agent.status, agent.isSynced, agent.frame)
        // Boost emissive for highlighted agents
        if (isHighlighted) {
          c.multiplyScalar(1.4)
        }
        // Elite agents (95+) get a subtle brightness pulse so they bloom
        if (agent.reputation >= 95 && !isDimmed && !isSearchDimmed) {
          const pulse = 1.0 + Math.sin(elapsed * 2 + i) * 0.15
          c.multiplyScalar(pulse)
        }
        color.copy(c)
        needsColorUpdate = true
      }
      agentInstancedMesh!.setColorAt(i, color)
    }

    // Always update for orbital animation
    agentInstancedMesh!.instanceMatrix.needsUpdate = true
    if (agentInstancedMesh!.instanceColor) {
      agentInstancedMesh!.instanceColor.needsUpdate = true
    }
  }

  // FIX-03: Update glow halo positions to follow orbiting agents
  if (agentGlowPoints && agentDataMap.length > 0) {
    const glowPosAttr = agentGlowPoints.geometry.getAttribute('position') as THREE.BufferAttribute
    for (let i = 0; i < agentDataMap.length; i++) {
      const agent = agentDataMap[i]
      if (!agent) continue
      const pos = agentPositions.get(agent.did)
      if (!pos) continue
      glowPosAttr.setXYZ(i, pos.x, pos.y, pos.z)
    }
    glowPosAttr.needsUpdate = true

    // Search dim (Commander 2026-06-04): when a query is active, darken the WHOLE halo
    // cloud and re-light ONLY the matches (warm-gold, pulsing) so a single result is
    // unmissable. The mesh-colour dim alone was invisible because this additive halo
    // sits on top of every agent. Restores pristine colours in one pass when cleared.
    const gq = (props.searchQuery || '').toLowerCase()
    if ((gq || glowDimActive) && baseGlowColors) {
      const glowColAttr = agentGlowPoints.geometry.getAttribute('color') as THREE.BufferAttribute
      // GC3: 1.4× peak @3.5Hz read as a strobe — calm gold breath instead.
      const gpulse = 0.78 + Math.abs(Math.sin(elapsed * 1.8)) * 0.22
      for (let i = 0; i < agentDataMap.length; i++) {
        const agent = agentDataMap[i]
        if (!agent) continue
        if (gq) {
          const hit = (agent.name || '').toLowerCase().includes(gq) || (agent.did || '').toLowerCase().includes(gq)
          if (hit) glowColAttr.setXYZ(i, 1.0 * gpulse, 0.84 * gpulse, 0.32 * gpulse)
          else glowColAttr.setXYZ(i, 0.03, 0.035, 0.06)
        } else {
          glowColAttr.setXYZ(i, baseGlowColors[i * 3], baseGlowColors[i * 3 + 1], baseGlowColors[i * 3 + 2])
        }
      }
      glowColAttr.needsUpdate = true
      glowDimActive = !!gq
    }
  }

  // ── GC3 environment focus-dim (Commander 2026-06-12): while a query is active,
  // the decorative layers (stars, galaxy band, nebulae, registry dust) ease toward
  // 35% so matches win by CONTRAST, not by brightness. Lerped both ways; writes
  // stop once fully restored. Material-opacity only. ──
  {
    // The fleet lens reuses the SAME focus-dim the search already drives -
    // one dimming mechanism in this file, not two competing ones.
    const dimTarget = fleetLensOn ? LENS_ENV : ((props.searchQuery || '') ? 0.35 : 1.0)
    if (envDimFactor !== dimTarget) {
      envDimFactor += (dimTarget - envDimFactor) * Math.min(1, delta * 4)
      if (Math.abs(envDimFactor - dimTarget) <= 0.004) envDimFactor = dimTarget
    }
    if (envDimFactor !== 1 || envDimApplied) {
      for (const e of envDimmables) e.mat.opacity = e.base * envDimFactor
      registryMeshes.forEach(group => {
        group.children.forEach(ch => {
          if (ch.userData?.isDust) ((ch as THREE.Points).material as THREE.PointsMaterial).opacity = 0.35 * envDimFactor
        })
      })
      envDimApplied = envDimFactor !== 1
    }
  }

  // ── Search beacon (Commander 2026-06-04, toned GC3 2026-06-12): a pulsing gold
  // ring rises on EVERY match — it renders on top of the field, the bloom AND the
  // decorative core (depthTest off, renderOrder 9999). Hidden when there's no
  // query. Pooled sprites, repositioned each frame. The environment dim carries
  // the contrast now, so the ring is a calm locator, not a strobe. ──
  {
    const bq = (props.searchQuery || '').toLowerCase()
    const matchPos: THREE.Vector3[] = []
    if (bq) {
      for (let i = 0; i < agentDataMap.length; i++) {
        const a = agentDataMap[i]
        if (!a) continue
        const hit = (a.name || '').toLowerCase().includes(bq) || (a.did || '').toLowerCase().includes(bq)
        if (hit) {
          const p = agentPositions.get(a.did)
          if (p) matchPos.push(p)
          if (matchPos.length >= 16) break
        }
      }
    }
    ensureSearchBeacons(matchPos.length)
    // GC3: slower, gentler breathing (1.4 vs 3.0) + much lower opacity ceilings —
    // the Commander's screenshot showed the old values blinding the cockpit.
    const bp = Math.abs(Math.sin(elapsed * 1.4))
    for (let i = 0; i < searchBeacons.length; i++) {
      const b = searchBeacons[i]
      const beam = searchBeams[i]
      if (i < matchPos.length) {
        const p = matchPos[i]
        b.position.set(p.x, p.y, p.z)
        const s = 10 + bp * 3           // clear locator ring, no longer a flare
        b.scale.set(s, s, 1)
        ;(b.material as THREE.SpriteMaterial).opacity = 0.30 + bp * 0.14
        b.visible = true
        if (beam) {
          beam.position.set(p.x, p.y + 32, p.z)  // base at the agent, rising +64 up
          ;(beam.material as THREE.MeshBasicMaterial).opacity = 0.10 + bp * 0.08
          beam.visible = true
        }
      } else {
        if (b.visible) b.visible = false
        if (beam && beam.visible) beam.visible = false
      }
    }
    // Lightweight telemetry hook (parallels window.__gmReg / __aw_registries) for
    // headless verification of search highlighting + GC3 focus-dim/pick-gating.
    // m0 = first match's canvas-pixel position (lets a gate hover the REAL dot);
    // hoverMatch = whether the currently hovered agent satisfies the query (the
    // pick-gating invariant: with a query active this must never be false).
    let m0: { x: number, y: number } | null = null
    let d0: { x: number, y: number } | null = null
    let d0did: string | null = null
    if (matchPos.length > 0 && camera && containerRef.value) {
      const r = containerRef.value.getBoundingClientRect()
      _gmDbgNdc.copy(matchPos[0]).project(camera)
      m0 = { x: (_gmDbgNdc.x * 0.5 + 0.5) * r.width, y: (-_gmDbgNdc.y * 0.5 + 0.5) * r.height }
      // d0 = first DIMMED (non-matching) agent — lets a gate prove the
      // not-hoverable invariant positively by aiming at a real dimmed dot.
      for (let i = 0; i < agentDataMap.length; i++) {
        const a = agentDataMap[i]
        if (!a || agentMatchesSearch(a)) continue
        const p = agentPositions.get(a.did)
        if (!p) continue
        _gmDbgNdc.copy(p).project(camera)
        if (_gmDbgNdc.z > 1) continue  // behind the camera
        d0 = { x: (_gmDbgNdc.x * 0.5 + 0.5) * r.width, y: (-_gmDbgNdc.y * 0.5 + 0.5) * r.height }
        d0did = a.did
        break
      }
    }
    const hi = hoveredInstanceIdx
    ;(window as Window & { __gmDbg?: unknown }).__gmDbg = {
      q: props.searchQuery, agents: agentDataMap.length, matches: matchPos.length,
      envDim: envDimFactor, m0, d0, d0did,
      beaconOp: matchPos.length > 0 ? (searchBeacons[0]?.material as THREE.SpriteMaterial)?.opacity ?? null : null,
      hoverIdx: hi,
      hoverMatch: (hi != null && hi >= 0 && agentDataMap[hi]) ? agentMatchesSearch(agentDataMap[hi]) : null,
    }
  }

  // FIX-04: Update connection line positions to follow orbiting agents
  if (connectionLines.length > 0 && connectionLines[0] instanceof THREE.LineSegments) {
    const lineGeo = (connectionLines[0] as THREE.LineSegments).geometry
    const posAttr = lineGeo.getAttribute('position') as THREE.BufferAttribute
    let idx = 0
    for (const agent of agentDataMap) {
      if (!agent) continue
      const agentPos = agentPositions.get(agent.did)
      const regId = agent.registryId || '__local__'
      const regPos = registryPositions.get(regId)
      if (agentPos && regPos) {
        posAttr.setXYZ(idx, agentPos.x, agentPos.y, agentPos.z)
        posAttr.setXYZ(idx + 1, regPos.x, regPos.y, regPos.z)
        idx += 2
      }
    }
    posAttr.needsUpdate = true
  }

  // Move agent labels to follow orbiting agents — LOD: fade by distance from camera
  if (camera) {
    const selectedDid = props.selectedAgentDid
    const q = (props.searchQuery || '').toLowerCase()
    const hoveredDid = hoveredInstanceIdx >= 0 ? (agentDataMap[hoveredInstanceIdx]?.did || null) : null
    // Declutter (Commander 2026-06-04): agent name labels appear ONLY for the searched /
    // hovered / selected agent — never the whole field (the "ugly labels" complaint).
    // §STARCAP — decide WHO needs a label first, mint only those, and cap the
    // search set: at the 1000-star cap a two-letter query would otherwise ask for
    // a thousand 512x80 canvases in one frame. The beacons still mark every match.
    const wantLabel = new Set<string>()
    if (selectedDid) wantLabel.add(selectedDid)
    if (hoveredDid) wantLabel.add(hoveredDid)
    if (q) {
      for (let i = 0; i < agentDataMap.length && wantLabel.size < AGENT_LABEL_MAX; i++) {
        const a = agentDataMap[i]
        if (!a) continue
        if (((a.name || '') + ' ' + (a.did || '')).toLowerCase().includes(q)) wantLabel.add(a.did)
      }
    }
    for (const did of wantLabel) ensureAgentLabel(did)
    for (let i = agentLabelSprites.length - 1; i >= 0; i--) {
      const label = agentLabelSprites[i]
      const did = label.userData?.agentDid
      const pos = did ? agentPositions.get(did) : null
      if (!did || !pos || !wantLabel.has(did)) { label.visible = false; continue }
      label.position.set(pos.x, pos.y + 1.4, pos.z)
      label.visible = true
      ;(label.material as THREE.SpriteMaterial).opacity = 1.0
    }
  }

  // Animate federation beam energy pulses (bidirectional)
  federationBeams.forEach(obj => {
    if (obj.userData?.isBeamPulse && obj.userData?.curve) {
      const curve = obj.userData.curve as THREE.QuadraticBezierCurve3
      const offset = obj.userData.phaseOffset as number
      const dir = obj.userData.direction as number
      const speed = obj.userData.speed as number
      // Forward (dir=1): 0→1, Reverse (dir=-1): 1→0
      let t = (offset + elapsed * speed) % 1.0
      if (dir < 0) t = 1.0 - t
      t = Math.max(0.001, Math.min(0.999, t))  // Clamp to avoid curve endpoint issues
      const p = curve.getPointAt(t)
      obj.position.copy(p)
      // Pulse brightness oscillation
      const mesh = obj as THREE.Mesh
      const mat = mesh.material as THREE.MeshBasicMaterial
      mat.opacity = 0.5 + Math.sin(elapsed * 4 + offset * 10) * 0.4
    }
  })

  // FIX-06: Raycasting for hover (throttled to every 3rd frame)
  if (!isMouseDown) {
    raycastCounter++
    if (raycastCounter % 3 === 0) {
      performRaycast()
    }
  }

  if (IS_MISSION) {
    stepVerbLayer(delta, elapsed)
    const _now = performance.now()
    stepIgnition(_now)
    stepTerritory(_now)
    stepFollow()
    // Direct render: no bloom pass, no film pass, no output pass.
    //
    // §BRIDGE R5 — MEASURE OUR OWN COST. Frame INTERVAL is useless as a signal
    // on this box: swiftshader renders every pixel on a CPU shared with ~295
    // containers, so a baseline read p50=533ms / p90=2767ms, and any before/
    // after comparison would be measuring the machine's mood rather than the
    // stage. Timing the draw itself isolates the work THIS component does, and
    // is the metric the territory pass has to be judged against.
    // (On real GPU hardware render() returns before the GPU finishes, so there
    // it measures submit cost only — stated, not hidden.)
    const _t0 = performance.now()
    renderer.render(scene, camera)
    recordRenderMs(performance.now() - _t0)
  } else {
    // Render with bloom
    composer.render()
  }
}

// ─── Raycasting / Interaction ────────────────────────────────────
function performRaycast() {
  // NOTE: do NOT require agentInstancedMesh here — it is null when agents are
  // hidden/absent (the IRONHAND Theatre embeds the map with :agents="[]"). Gating
  // on it killed REGISTRY hover too. Only camera+scene are mandatory.
  if (!camera || !scene) return

  raycaster.setFromCamera(mouse, camera)

  // Check agents first (instanced) — only when the agent mesh exists.
  if (agentInstancedMesh) {
    const agentHits = raycaster.intersectObject(agentInstancedMesh, false)

    if (agentHits.length > 0 && agentHits[0].instanceId !== undefined) {
      const idx = agentHits[0].instanceId
      const agent = agentDataMap[idx]
      // GC3: while a search is active, dimmed (non-matching) agents are NOT
      // hoverable — no card, no cursor, no white flash. Crowded orbits made
      // mis-hovers on greyed neighbours too easy. Falls through to registry pick.
      if (agent && agentMatchesSearch(agent)) {
        hoveredInstanceIdx = idx  // FIX-07: track for visual feedback
        // Tooltip rendering is owned by the VIEW (GalacticMap.vue renders the
        // shared TopologyHoverLabel + RegistryHoverCard from these emits) — the
        // canvas is emit-only to avoid the double-tooltip the old in-canvas
        // render produced alongside the view's avatar label.
        emit('agent-hover', agent)
        emit('registry-hover', null)
        if (containerRef.value) containerRef.value.style.cursor = 'pointer'
        return
      }
    }
  }

  // Check registries — PLANET BODIES ONLY (R13 #7), not the whole decorated group.
  const regHits = raycaster.intersectObjects(registryPickables, false)
  if (regHits.length > 0) {
    // Walk up to find the group
    let obj: THREE.Object3D | null = regHits[0].object
    while (obj && !obj.userData?.type) obj = obj.parent
    if (obj?.userData?.type === 'registry') {
      const reg = obj.userData.data as MapRegistry
      emit('registry-hover', reg)
      emit('agent-hover', null)
      if (containerRef.value) containerRef.value.style.cursor = 'pointer'
      return
    }
  }

  // Nothing hovered
  hoveredInstanceIdx = null  // FIX-07: clear hover tracking
  emit('agent-hover', null)
  emit('registry-hover', null)
  if (containerRef.value) containerRef.value.style.cursor = 'grab'
}

// Debug/preview hook (console-only, mirrors __gmDbg / __gccRestartDemo): hover an
// agent by DID — default: the first search match — through the SAME gating rule
// performRaycast applies, so a dimmed (non-matching) agent is REFUSED exactly like
// a real mouse. Headless gates can't win the pointer race against orbiting dots at
// ~2fps; this drives the identical emit path deterministically. Returns whether
// the hover engaged. Removed on unmount with the listeners.
function _gmHoverAgentHook(did?: string): boolean {
  let idx = -1
  if (did) idx = agentDataMap.findIndex(a => a && a.did === did)
  else idx = agentDataMap.findIndex(a => a && !!props.searchQuery && agentMatchesSearch(a))
  const agent = idx >= 0 ? agentDataMap[idx] : null
  if (!agent || !agentMatchesSearch(agent)) return false  // GC3 gating — same rule as the raycaster
  hoveredInstanceIdx = idx
  emit('agent-hover', agent)
  emit('registry-hover', null)
  return true
}
;(window as Window & { __gmHoverAgent?: (did?: string) => boolean }).__gmHoverAgent = _gmHoverAgentHook

function updateTooltipAgent(agent: MapAgent) {
  tooltipData.value = {
    name: agent.name, type: 'agent',
    did: agent.did,
    description: agent.description,
    reputation: agent.reputation,
    reputationTier: agent.reputationTier || 'standard',
    totalTransactions: agent.totalTransactions || 0,
    balance: agent.liquidBalance + agent.stakedBalance,
    liquidBalance: agent.liquidBalance,
    stakedBalance: agent.stakedBalance,
    isSynced: agent.isSynced,
    capabilities: agent.capabilities?.slice(0, 4) || [],
    originRegistry: agent.originRegistry,
    createdAt: agent.createdAt,
  }
  tooltipVisible.value = true
}

function updateTooltipRegistry(reg: MapRegistry) {
  tooltipData.value = {
    name: reg.name, type: 'registry',
    publicUrl: reg.publicUrl || reg.url,
    url: reg.url,
    health: reg.health,
    agentCount: reg.agentCount,
    status: reg.status,
    lastSyncedAt: reg.lastSyncedAt || undefined,
    trustDomain: reg.trustDomain,
    authMethods: reg.authMethods,
    protocolVersion: reg.protocolVersion,
    registryDescription: reg.description,
  }
  tooltipVisible.value = true
}

function hideTooltip() {
  tooltipVisible.value = false
}

function onMouseMove(event: MouseEvent) {
  if (!containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1

  // FIX-05: Position tooltip near cursor with edge clamping
  const tooltipW = 330
  const tooltipH = 200
  let tx = event.clientX - rect.left + 16
  let ty = event.clientY - rect.top - 10
  if (tx + tooltipW > rect.width) tx = event.clientX - rect.left - tooltipW - 8
  if (ty + tooltipH > rect.height) ty = rect.height - tooltipH - 8
  if (ty < 4) ty = 4
  tooltipStyle.value = { left: tx + 'px', top: ty + 'px' }
}

// FIX-17: Touch helper — converts touch to normalized device coordinates
function updateMouseFromTouch(touch: Touch) {
  if (!containerRef.value) return
  const rect = containerRef.value.getBoundingClientRect()
  mouse.x = ((touch.clientX - rect.left) / rect.width) * 2 - 1
  mouse.y = -((touch.clientY - rect.top) / rect.height) * 2 + 1
}

// FIX-17: Touch click handler — runs raycast and emits click events
function performRaycastClick() {
  if (!camera) return  // agentInstancedMesh may be null (agents hidden) — still allow registry click
  raycaster.setFromCamera(mouse, camera)

  if (agentInstancedMesh) {
    const agentHits = raycaster.intersectObject(agentInstancedMesh, false)
    if (agentHits.length > 0 && agentHits[0].instanceId !== undefined) {
      const agent = agentDataMap[agentHits[0].instanceId]
      // GC3: dimmed agents are non-interactive (see performRaycast)
      if (agent && agentMatchesSearch(agent)) {
        emit('agent-click', agent)
        controls.autoRotate = false
        return
      }
    }
  }

  const registryObjects = Array.from(registryMeshes.values())
  const regHits = raycaster.intersectObjects(registryObjects, true)
  if (regHits.length > 0) {
    let obj: THREE.Object3D | null = regHits[0].object
    while (obj && !obj.userData?.type) obj = obj.parent
    if (obj?.userData?.type === 'registry') {
      // AAA+: Fly camera to clicked registry
      const regData = obj.userData.data as MapRegistry
      const pos = registryPositions.get(regData.id) || registryPositions.get(String(regData.id))
      if (pos) {
        flyToTarget = pos.clone()
        flyToTarget.y += 10
        flyToProgress = 0
      }
      emit('registry-click', regData)
      return
    }
  }

  emit('agent-click', null as any)
}

/**
 * #B12 — find the live verb nearest a click, in SCREEN space.
 *
 * Not a sprite raycast: these are small, bright, MOVING objects, and demanding a
 * pixel-accurate hit on one would make "click a photon to read its receipt"
 * a dexterity test. Projecting the live heads and taking the nearest within a
 * forgiving radius is both kinder and cheaper (at most 128 projections, and only
 * on a click). Mission mode only, so /galactic-map keeps its exact behaviour.
 */
const VERB_PICK_RADIUS_PX = 26
function pickVerbAt(event: MouseEvent): any | null {
  if (!IS_MISSION || !camera || !containerRef.value) return null
  const rect = containerRef.value.getBoundingClientRect()
  const cx = event.clientX - rect.left
  const cy = event.clientY - rect.top
  let best: any = null
  let bestD = VERB_PICK_RADIUS_PX
  for (const v of verbPool) {
    if (!v.alive || !v.desc || !v.head.visible) continue
    _scratchVec.copy(v.head.position).project(camera)
    if (_scratchVec.z > 1) continue                     // behind the camera
    const sx = (_scratchVec.x * 0.5 + 0.5) * rect.width
    const sy = (-_scratchVec.y * 0.5 + 0.5) * rect.height
    const d = Math.hypot(sx - cx, sy - cy)
    if (d < bestD) { bestD = d; best = v.desc }
  }
  return best
}

/**
 * Right-click: pick the agent under the cursor and emit it as a TARGET.
 *
 * The browser menu is suppressed only when a pick actually lands, so
 * right-clicking empty space still behaves like the rest of the web.
 */
function onMouseContext(event: MouseEvent) {
  if (!camera || !agentInstancedMesh) return
  raycaster.setFromCamera(mouse, camera)
  const hits = raycaster.intersectObject(agentInstancedMesh, false)
  if (hits.length > 0 && hits[0].instanceId !== undefined) {
    const agent = agentDataMap[hits[0].instanceId]
    if (agent && agentMatchesSearch(agent)) {
      event.preventDefault()
      emit('agent-context', agent)
    }
  }
}

function onMouseClick(event: MouseEvent) {
  if (!camera) return  // agentInstancedMesh may be null (agents hidden) — still allow registry click

  // OWL24: Don't process click if user was dragging (moved > 5px)
  const dx = event.clientX - mouseDownPos.x
  const dy = event.clientY - mouseDownPos.y
  if (Math.sqrt(dx * dx + dy * dy) > 5) return

  // A photon takes precedence over what is behind it: you clicked the light.
  const verb = pickVerbAt(event)
  if (verb) { emit('verb-click', verb); return }

  raycaster.setFromCamera(mouse, camera)

  // Check agents (only when the agent mesh exists)
  if (agentInstancedMesh) {
    const agentHits = raycaster.intersectObject(agentInstancedMesh, false)
    if (agentHits.length > 0 && agentHits[0].instanceId !== undefined) {
      const agent = agentDataMap[agentHits[0].instanceId]
      // GC3: dimmed agents are non-interactive (see performRaycast)
      if (agent && agentMatchesSearch(agent)) {
        emit('agent-click', agent)
        // Stop auto-rotate on selection
        controls.autoRotate = false
        return
      }
    }
  }

  // Check registries — PLANET BODIES ONLY (R13 #7).
  const regHits = raycaster.intersectObjects(registryPickables, false)
  if (regHits.length > 0) {
    let obj: THREE.Object3D | null = regHits[0].object
    while (obj && !obj.userData?.type) obj = obj.parent
    if (obj?.userData?.type === 'registry') {
      emit('registry-click', obj.userData.data as MapRegistry)
      return
    }
  }

  // Clicked empty space — deselect (auto-rotate stays off once user has interacted)
  emit('agent-click', null as any)
}

// ─── Resize Handler ──────────────────────────────────────────────
function handleResize() {
  if (!containerRef.value || !camera || !renderer) return
  if (!IS_MISSION && !composer) return
  const w = containerRef.value.clientWidth
  const h = containerRef.value.clientHeight
  camera.aspect = w / h
  camera.updateProjectionMatrix()
  renderer.setSize(w, h)
  composer?.setSize(w, h)
}

// ─── Full Rebuild (on data change) ──────────────────────────────
function rebuildScene() {
  if (!scene) return

  // Belt-and-suspenders: never wipe agents if we had them (auth-race guard).
  // EXCEPTION: embedded Theatre intentionally hides (SHOW ALL off / solo off) → allow the wipe.
  if (props.agents.length === 0 && agentDataMap.length > 0 && !props.embedded) {
    gwarn(`rebuildScene blocked — would wipe ${agentDataMap.length} placed agents`)
    return
  }

  glog(`rebuildScene triggered — agents: ${props.agents.length}, registries: ${props.registries.length}`)
  computeLayout()
  buildRegistries()
  buildAgents()
  buildConnections()
  buildFederationBeams()
  buildFrameOverlays()
}

// ─── Cleanup ─────────────────────────────────────────────────────
function dispose() {
  if (animationId) cancelAnimationFrame(animationId)
  // GC3: drop the console debug hook with the component
  const w = window as Window & { __gmHoverAgent?: unknown }
  if (w.__gmHoverAgent === _gmHoverAgentHook) delete w.__gmHoverAgent

  // Remove event listeners
  if (renderer?.domElement) {
    renderer.domElement.removeEventListener('mousemove', onMouseMove)
    renderer.domElement.removeEventListener('click', onMouseClick)
    renderer.domElement.removeEventListener('contextmenu', onMouseContext)
    // 2026-05-05 audit BLOCKER-2: detach touch + WebGL ctx listeners that
    // accumulated on every mount cycle.
    if (_onTouchStart) renderer.domElement.removeEventListener('touchstart', _onTouchStart)
    if (_onTouchMove) renderer.domElement.removeEventListener('touchmove', _onTouchMove)
    if (_onTouchEnd) renderer.domElement.removeEventListener('touchend', _onTouchEnd)
    if (_onWebGLContextLost) renderer.domElement.removeEventListener('webglcontextlost', _onWebGLContextLost)
    if (_onWebGLContextRestored) renderer.domElement.removeEventListener('webglcontextrestored', _onWebGLContextRestored)
  }
  _onTouchStart = _onTouchMove = _onTouchEnd = null
  _onWebGLContextLost = null
  _onWebGLContextRestored = null
  window.removeEventListener('resize', handleResize)

  // §BRIDGE: pooled verb objects + the generated glow texture
  disposeVerbLayer()

  // Dispose Three.js objects
  if (agentInstancedMesh) {
    agentInstancedMesh.dispose()
    agentInstancedMesh = null
  }
  if (agentGlowPoints) {
    agentGlowPoints.geometry.dispose()
    ;(agentGlowPoints.material as THREE.PointsMaterial).dispose()
    agentGlowPoints = null
  }

  agentLabelSprites.forEach(s => {
    (s.material as THREE.SpriteMaterial).map?.dispose()
    ;(s.material as THREE.SpriteMaterial).dispose()
  })
  agentLabelSprites = []
  agentLabelByDid.clear()
  agentLabelLru.length = 0
  agentByDid.clear()
  agentOrbits.clear()

  // 2026-05-05 audit MEDIUM-5: deep material dispose so attached
  // CanvasTextures (vignette overlay, antialias, comet tail, frame overlays,
  // etc.) get freed instead of stranding GPU VRAM across remount cycles.
  connectionLines.forEach(l => {
    if ((l as any).geometry) (l as any).geometry.dispose()
    _disposeMaterialDeep((l as any).material)
  })
  connectionLines = []

  federationBeams.forEach(b => {
    if ((b as any).geometry) (b as any).geometry.dispose()
    _disposeMaterialDeep((b as any).material)
  })
  federationBeams = []

  registryMeshes.forEach(g => {
    g.traverse(child => {
      if ((child as any).geometry) (child as any).geometry.dispose()
      _disposeMaterialDeep((child as any).material)
    })
  })
  registryMeshes.clear()

  // Dispose cached planet textures (GPU memory)
  planetTextureCache.forEach(tex => tex.dispose())
  planetTextureCache.clear()

  // Dispose scene children — deep walk including all map types
  scene?.traverse(child => {
    if ((child as any).geometry) (child as any).geometry.dispose()
    _disposeMaterialDeep((child as any).material)
  })

  // Dispose cached textures
  if (_starTexture) { _starTexture.dispose(); _starTexture = null }
  if (_glowTexture) { _glowTexture.dispose(); _glowTexture = null }

  controls?.dispose()
  composer?.dispose()
  renderer?.dispose()

  // Remove canvas from DOM
  if (containerRef.value && renderer?.domElement) {
    try { containerRef.value.removeChild(renderer.domElement) } catch { /* expected */ }
  }

  /*
   * §LITEBRIDGE polish 1 — RELEASE THE GL CONTEXT, not just three's caches.
   *
   * `renderer.dispose()` frees three.js's own programs and buffers. It does NOT
   * release the underlying WebGL context: the browser keeps it alive until the
   * renderer is collected, and browsers cap the number of live contexts (~16 in
   * Chrome) before they start dropping the OLDEST one.
   *
   * This never mattered while the stage was the only way to view the bridge,
   * because nothing ever unmounted it. The light bridge unmounts it every time
   * you switch, so it matters now. MEASURED across four FULL/LIGHT round trips
   * with a forced collection before each sample: heap climbed 19 -> 73 MB,
   * about +13 MB per stage boot that never came back.
   *
   * `forceContextLoss()` is the documented way to hand it back, and it is safe
   * here precisely because we are on the unmount path: nothing draws again.
   */
  try { (renderer as any)?.forceContextLoss?.() } catch { /* already gone */ }
  renderer = null as any
  composer = null as any
  controls = null as any
}

// ─── Lifecycle ───────────────────────────────────────────────────
let retryTimers: number[] = []

// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): a canvas unmounted in the same flush makes no WebGL renderer, loop or listener
const stillMounted = useAlive()
onMounted(async () => {
  await nextTick()
  if (!stillMounted()) return
  initScene()
  if (!webglError.value && renderer) {
    animate()
    window.addEventListener('resize', handleResize)
  }

  installProfileHook()

  // Safety-net: retry rebuild at 1s, 3s, 6s in case agents load late
  // This catches race conditions where watchers don't fire
  ;[1000, 3000, 6000].forEach(delay => {
    const t = window.setTimeout(() => {
      if (scene && props.agents.length > 0 && agentDataMap.length === 0) {
        glog(`Safety retry at ${delay}ms — ${props.agents.length} agents available but 0 placed`)
        rebuildScene()
      }
    }, delay)
    retryTimers.push(t)
  })
})

onUnmounted(() => {
  retryTimers.forEach(t => clearTimeout(t))
  if (rebuildTimer) clearTimeout(rebuildTimer)
  removeProfileHook()
  dispose()
})

/**
 * §7.5/§7.7 — dev-only render-profile probe, behind `?bridgedebug=1` ONLY.
 *
 * Mode isolation is a GATE, not a hope: the battery has to be able to assert
 * POSITIVELY that `/galactic-map` still runs the full cinematic profile
 * (composer on, DPR up to 2), not merely that the mission hook is absent —
 * an absence proves nothing until the probe has been shown able to return a
 * present. This publishes the same counters `bridgeStats()` exposes, in BOTH
 * modes, so the two profiles are distinguishable from the outside.
 *
 * Nothing is attached to window without the flag, and the hook removes itself
 * on unmount (a stale global would pin this component's closures forever).
 */
let savedFog: THREE.FogBase | null = null
const PROFILE_TOKEN = Symbol('canvasProfile')
function bridgeDebugOn(): boolean {
  if (typeof window === 'undefined') return false
  try { return new URLSearchParams(window.location.search).has('bridgedebug') } catch { return false }
}
function installProfileHook(): void {
  if (!bridgeDebugOn()) return
  ;(window as any).__canvasProfile = {
    token: PROFILE_TOKEN,
    mode: props.mode,
    usesComposer: !!composer,
    pixelRatio: renderer?.getPixelRatio?.() ?? null,
    webglError: !!webglError.value,
    /**
     * §BRIDGE R11 #3 — a falsifiable handle on the atmosphere.
     *
     * He reported "an empty blackness that expands and contracts with zooming",
     * and my first suspect (the decorative black hole) was WRONG by his own
     * correction. A diagnosis that cannot be falsified is not a diagnosis, so
     * the fog is switchable from the battery: same camera, fog on vs fog off.
     * If the two frames are identical, the fog is innocent and I keep looking.
     */
    fogInfo: () => (scene?.fog
      ? { type: (scene.fog as any).isFogExp2 ? 'FogExp2' : 'Fog',
          density: (scene.fog as any).density ?? null,
          color: '#' + (scene.fog as any).color.getHexString(),
          near: (scene.fog as any).near ?? null, far: (scene.fog as any).far ?? null }
      : null),
    setFog: (on: boolean) => {
      if (!scene) return false
      if (on) { if (!savedFog) return false; scene.fog = savedFog }
      else { if (scene.fog) savedFog = scene.fog; scene.fog = null }
      scene.traverse((o: any) => { if (o.material) {
        const ms = Array.isArray(o.material) ? o.material : [o.material]
        ms.forEach((m: any) => { if (m) m.needsUpdate = true })
      } })
      return true
    },
    cameraState: () => (camera ? {
      pos: [camera.position.x, camera.position.y, camera.position.z].map((n) => Math.round(n)),
      dist: Math.round(camera.position.length()),
    } : null),
    setCamera: (x: number, y: number, z: number) => {
      if (!camera) return false
      camera.position.set(x, y, z); camera.lookAt(0, 0, 0)
      if (controls) { controls.target.set(0, 0, 0); controls.update() }
      return true
    },
    /**
     * §BRIDGE R11 #3 — a scene census, so "what is the blackness?" is a
     * measurement instead of a guess.
     *
     * The fog was my first suspect and the A/B falsified it outright (fog off
     * moved mean luminance by 0.09 of 255). Rather than pick a second suspect
     * and hope, this lists every top-level object with the properties that make
     * something a large dark overlay, and lets the battery switch each one off
     * and diff the pixels.
     */
    objects: () => {
      const out: any[] = []
      if (!scene) return out
      scene.children.forEach((o: any) => {
        const m = Array.isArray(o.material) ? o.material[0] : o.material
        out.push({
          uuid: o.uuid,
          type: o.type,
          name: o.name || '',
          visible: o.visible,
          renderOrder: o.renderOrder,
          scale: o.scale ? [o.scale.x, o.scale.y, o.scale.z].map((n: number) => Math.round(n)) : null,
          pos: o.position ? [o.position.x, o.position.y, o.position.z].map((n: number) => Math.round(n)) : null,
          children: o.children?.length ?? 0,
          mat: m ? { type: m.type, transparent: !!m.transparent, opacity: m.opacity,
                     depthTest: m.depthTest, depthWrite: m.depthWrite, side: m.side,
                     blending: m.blending, color: m.color ? '#' + m.color.getHexString() : null } : null,
        })
      })
      return out
    },
    setVisible: (uuid: string, v: boolean) => {
      if (!scene) return false
      let hit = false
      scene.traverse((o: any) => { if (o.uuid === uuid) { o.visible = v; hit = true } })
      return hit
    },
    /**
     * §BRIDGE R13 — the census had to go DEEPER.
     *
     * The first version listed only `scene.children`, so a defect living inside
     * a Group (the black hole carries six children; a registry carries seven)
     * could only be attributed to the whole group. It also reported no
     * `depthWrite`-aware view, and the hypothesis that actually fits what he
     * sees — an object that PAINTS NOTHING but OCCLUDES the starfield — is
     * invisible to a colour-based search by construction.
     */
    objectsDeep: () => {
      const out: any[] = []
      if (!scene) return out
      const walk = (o: any, path: string, depth: number) => {
        const ms = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []
        const m = ms[0]
        let radius = null
        try {
          o.geometry?.computeBoundingSphere?.()
          radius = o.geometry?.boundingSphere?.radius ?? null
        } catch { radius = null }
        out.push({
          uuid: o.uuid, path, depth, type: o.type, name: o.name || '',
          visible: o.visible, renderOrder: o.renderOrder,
          scale: o.scale ? Math.round(Math.max(o.scale.x, o.scale.y, o.scale.z)) : null,
          geoRadius: radius === null ? null : Math.round(radius * 100) / 100,
          worldSize: radius === null ? null : Math.round(radius * Math.max(o.scale?.x ?? 1, 1)),
          pos: o.position ? [o.position.x, o.position.y, o.position.z].map((n: number) => Math.round(n)) : null,
          mat: m ? { type: m.type, transparent: !!m.transparent, opacity: m.opacity,
                     depthTest: m.depthTest, depthWrite: m.depthWrite, side: m.side,
                     blending: m.blending, visible: m.visible,
                     color: m.color ? '#' + m.color.getHexString() : null } : null,
        })
        if (depth < 3) (o.children || []).forEach((c: any, i: number) => walk(c, `${path}/${i}`, depth + 1))
      }
      scene.children.forEach((c: any, i: number) => walk(c, String(i), 0))
      return out
    },
    /** §BRIDGE R11 #9 — obstacle count + how many arcs were routed around one. */
    arcRouting: () => ({ obstacles: registryObstacles.length, deflections: arcDeflections }),
    /* §BRIDGE R16.1 — force the rebuild that used to warp the agents.
     * "they rewind back or jump forward" is only provable if the rebuild can be
     * triggered on demand: sample positions, rebuild, sample again. With the
     * orbit derived from the clock the two samples must agree to within the
     * fraction of a second that actually elapsed. Dev surface only. */
    forceRebuild: () => { rebuildScene(); return true },
    agentWorldPositions: (limit = 40) => {
      const out: Array<{ did: string; x: number; y: number; z: number }> = []
      for (const a of agentDataMap.slice(0, limit)) {
        const p = agentPositions.get(a.did)
        if (p) out.push({ did: a.did, x: p.x, y: p.y, z: p.z })
      }
      return out
    },
    /** Every material in the scene that has NOT opted out of the fog. */
    fogged: () => {
      const out: Record<string, number> = {}
      if (!scene) return out
      scene.traverse((o: any) => {
        const ms = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : []
        ms.forEach((m: any) => {
          if (!m) return
          const k = `${m.type}:${m.fog === false ? 'nofog' : 'FOG'}`
          out[k] = (out[k] || 0) + 1
        })
      })
      return out
    },
  }
}
function removeProfileHook(): void {
  if (typeof window === 'undefined') return
  const cur = (window as any).__canvasProfile
  // Only clear our own: /galactic-command embeds a second canvas instance.
  if (cur && cur.token === PROFILE_TOKEN) delete (window as any).__canvasProfile
}

// Debounced rebuild to prevent visual flickering
let rebuildTimer: number | null = null
let peakAgentCount = 0  // Guards against agent-auth wipe (0 agents after having N)
let previousAgentCount = 0  // 2026-05-05 audit MEDIUM-4: detect significant drops, not just zero

function debouncedRebuild() {
  if (rebuildTimer) clearTimeout(rebuildTimer)
  rebuildTimer = window.setTimeout(() => {
    if (scene) {
      glog(`Debounced rebuild executing`)
      rebuildScene()
    }
  }, 200)
}

// Watch label visibility toggle
watch(() => props.showLabels, (show) => {
  // Toggle registry labels (children of registry groups with isLabel userData)
  registryMeshes.forEach((group) => {
    group.children.forEach(child => {
      if (child.userData?.isLabel) child.visible = !!show
    })
  })
  // Toggle agent labels
  agentLabelSprites.forEach(label => { label.visible = !!show })
  // Toggle frame labels
  frameLabels.forEach(label => { label.visible = !!show })
})

// Watch for data changes — use length as primary trigger (primitives always fire)
watch([() => props.agents.length, () => props.registries.length, () => props.topologyVersion,
       // Membership signature (first|last did): solo cycling swaps one agent for another
       // (length stays 1) — the length-only key never fired, so the shown agent went stale.
       () => `${props.agents[0]?.did || ''}|${props.agents[props.agents.length - 1]?.did || ''}`],
      ([newAgentLen, newRegLen]) => {
  glog(`Length watcher fired: ${newAgentLen} agents, ${newRegLen} registries, topology v${props.topologyVersion} (peak: ${peakAgentCount})`)

  // Track peak agent count
  if (newAgentLen > peakAgentCount) peakAgentCount = newAgentLen

  // GUARD: If we previously had agents and now get 0, this is likely the agent-auth
  // race condition (store re-fetches with agent JWT that returns empty list).
  // Keep the current scene intact — don't rebuild to empty.
  // EXCEPTION: in the embedded IRONHAND Theatre the agent set is intentionally
  // controlled (SHOW ALL toggle / solo) so an empty is a real "hide" — allow it.
  if (newAgentLen === 0 && peakAgentCount > 0 && !props.embedded) {
    // CRITICAL: Also cancel any pending debounced rebuild from the previous (valid) fire!
    // Without this, the old timer fires 200ms later with props.agents.length=0.
    if (rebuildTimer) { clearTimeout(rebuildTimer); rebuildTimer = null }
    gwarn(`Ignoring rebuild — agents dropped to 0 (was ${peakAgentCount}). Likely agent-auth race condition.`)
    return
  }

  // 2026-05-05 audit MEDIUM-4: also flag large drops (not just zero). Token
  // rotation that tightens permissions can shrink the visible-agents count
  // significantly without hitting zero. Warn but don't block — the rebuild
  // is still useful with reduced data.
  if (previousAgentCount > 100 && newAgentLen > 0 && newAgentLen < previousAgentCount * 0.8) {
    gwarn(`Significant agent count drop ${previousAgentCount} → ${newAgentLen} (>20%). Token rotation or permission change likely.`)
  }
  previousAgentCount = newAgentLen

  debouncedRebuild()
})

// NOTE: Deep watcher removed — was causing excessive rebuilds and visual disappearing
// Content changes (rep updates etc.) will be handled via length watcher or manual trigger

// Watch for selection / highlight / search changes (handled in animate loop, no rebuild needed)

// Auto-frame search matches (Commander 2026-06-04): a found agent is useless if it's
// off-screen — "I almost couldn't fit the one I searched". On a search change, ease the
// camera to the FIRST match so its big gold beacon is always in view. One-shot per query
// change; the per-frame fly-to in animate() suppresses idle auto-rotate while it runs.
watch(() => props.searchQuery, (q) => {
  const query = (q || '').toLowerCase().trim()
  if (query.length < 2 || agentDataMap.length === 0) return
  for (let i = 0; i < agentDataMap.length; i++) {
    const a = agentDataMap[i]
    if (!a) continue
    if ((a.name || '').toLowerCase().includes(query) || (a.did || '').toLowerCase().includes(query)) {
      const p = agentPositions.get(a.did)
      if (p) {
        flyToTarget = p.clone()
        flyToProgress = 0
        if (controls) controls.autoRotate = false
      }
      break
    }
  }
})

// Template helper methods
function getRepClass(rep: number): string {
  if (rep >= 90) return 'elite'
  if (rep >= 70) return 'great'
  if (rep >= 50) return 'good'
  return 'low'
}

function getHealthClass(h: number): string {
  if (h >= 80) return 'healthy'
  if (h >= 40) return 'warn'
  return 'critical'
}

function getTierClass(tier: string): string {
  const t = tier.toLowerCase()
  if (t === 'elite') return 'elite'
  if (t === 'trusted') return 'great'
  if (t === 'verified') return 'good'
  return 'low'
}

function formatSyncTime(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const mins = Math.floor(diffMs / 60000)
    if (mins < 1) return 'just now'
    if (mins < 60) return `${mins}m ago`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}h ago`
    return `${Math.floor(hrs / 24)}d ago`
  } catch { return iso }
}

// ── IRONHAND mTLS Theatre (additive, read-only) ──────────────────
// Expose node world-positions + camera + container so an embedded overlay
// (FxRoute/identity-travel marker) can project a moving avatar onto the canvas.
// Does NOT change rendering or topology logic.
defineExpose({
  /**
   * §SHOOT — the camera seam existed only on `window.__canvasProfile`, which
   * nothing up the ref chain could see, so a driver could not aim a shot and
   * wheel events never reached OrbitControls. Same pair, on the component,
   * so GalacticMap -> BridgeStage -> __bridge can forward it.
   */
  cameraState: () => (camera ? {
    pos: [camera.position.x, camera.position.y, camera.position.z].map(n => Math.round(n)),
    dist: Math.round(camera.position.length()),
  } : null),
  setCamera: (x: number, y: number, z: number) => {
    if (!camera) return false
    camera.position.set(x, y, z); camera.lookAt(0, 0, 0)
    if (controls) { controls.target.set(0, 0, 0); controls.update() }
    return true
  },
  getNodePos: (id: string) => registryPositions.get(id)?.clone() ?? null,
  getCamera: () => camera,
  getContainer: () => containerRef.value ?? null,
  // §BRIDGE stage control surface (mission mode). Imperative on purpose: the
  // descriptor feed is a hot path and must not go through Vue reactivity.
  pushVerbs,
  missionBoost,
  setFleetLens,
  setAtmosphere,
  noteWeather,
  /**
   * Screen positions of the live verbs (#B12 test seam, §7.7).
   * "Click a photon" is otherwise untestable: they are small and they move, so a
   * battery would be reduced to clicking blindly and hoping. This publishes
   * where they ARE, so the click can be aimed and the assertion can actually
   * fail. Dev surface only — the debug hook that reads it needs ?bridgedebug=1.
   */
  verbScreenPositions: () => {
    const out: { x: number, y: number, verb: string }[] = []
    if (!IS_MISSION || !camera || !containerRef.value) return out
    const rect = containerRef.value.getBoundingClientRect()
    for (const v of verbPool) {
      if (!v.alive || !v.desc || !v.head.visible) continue
      _scratchVec.copy(v.head.position).project(camera)
      if (_scratchVec.z > 1) continue
      out.push({
        x: Math.round((_scratchVec.x * 0.5 + 0.5) * rect.width),
        y: Math.round((-_scratchVec.y * 0.5 + 0.5) * rect.height),
        verb: v.desc.verb,
      })
    }
    return out
  },
  /**
   * Screen positions of the drawn agent STARS (§BRIDGE R9 test seam).
   * The hover label can only be proven by hovering a star, and a star is a few
   * pixels of an InstancedMesh: without this a battery would hover blindly and
   * report "no label" about its own aim.
   */
  agentScreenPositions: () => {
    const out: { x: number, y: number, did: string }[] = []
    if (!camera || !containerRef.value) return out
    const rect = containerRef.value.getBoundingClientRect()
    // agentPositions is did -> Vector3 (the same map the renderer places from).
    for (const [did, pos] of agentPositions) {
      if (!pos) continue
      _scratchVec.copy(pos).project(camera)
      if (_scratchVec.z > 1) continue
      out.push({
        x: Math.round((_scratchVec.x * 0.5 + 0.5) * rect.width),
        y: Math.round((-_scratchVec.y * 0.5 + 0.5) * rect.height),
        did: String(did || ''),
      })
      if (out.length >= 400) break
    }
    return out
  },
  /** Per-registry population placement — see densityByReg. */
  densityByRegistry: () => ({
    total: densityCount,
    unplaced: densityUnplaced,
    byRegistry: Object.fromEntries(densityByReg),
  }),
  /** Live perf counters for the `?bridgedebug=1` overlay and the battery. */
  setFollowAgent,
  isFollowing,
  bridgeStats: () => ({
    following: followDid,
    poolCap: VERB_POOL_CAP,
    renderMs: renderMsStats(),
    resolve: { ...resolveTally },
    // `done: true` alone cannot tell "finished" from "never started" — the
    // count and the timestamp can.
    ignition: { lit: igniteLit, at: igniteAt, pending: igniteOrder.length, done: igniteDone },
    density: { drawn: densityCount, offered: (props.densityAgents || []).length },
    territory: {
      lanesTracked: lanes.size,
      lanesDrawn: laneMesh ? (laneMesh.geometry.drawRange.count / 2) : 0,
      // The fade is only real if it is measurable: the dimmest drawn lane's
      // brightness, so a battery can prove lanes decay instead of holding.
      laneFadeMin: (() => {
        if (!laneMesh) return null
        const c = laneMesh.geometry.getAttribute('color') as THREE.BufferAttribute | undefined
        const n = laneMesh.geometry.drawRange.count
        if (!c || !n) return null
        let min = 1
        const a = c.array as Float32Array
        for (let i = 0; i < n; i++) min = Math.min(min, a[i * 3 + 2] / 0.847)
        return Math.round(min * 1000) / 1000
      })(),
      nebulae: coronaSprites.length,
      // R14.2: weather is only honest if it is countable.
      weatherSeen,
      weatherByFrame: Array.from(frameWeather.entries()).map(([f, v]) => [f, Math.round(v * 100) / 100]),
      frameFields: frameFieldSprites.length,
      venueActivity: Array.from(venueActivity.entries()),
    },
    // The anchor table, so "no anchor for frame X" is answerable instead of
    // guessable: what the canvas actually knows about each registry node.
    anchors: props.registries.slice(0, 40).map(r => ({
      id: r.id, name: r.name, frame: r.frame ?? null,
      peerType: r.peerType ?? null, trustDomain: r.trustDomain ?? null,
      hasPos: !!registryPositions.get(r.id),
    })),
    frameDomains: Array.from(frameDomainMap().entries()),
    unresolvedTop: Array.from(unresolvedHints.entries()).sort((a, b) => b[1] - a[1]).slice(0, 15),
    // §BRIDGE R1.6 — the star count is now MEASURABLE, because it silently
    // regressed once already. P1 cut mission mode down to the viewer's OWN
    // agents after the stage built a sprite per agent and blocked the renderer
    // for minutes. R1 then handed that same filter the viewer's COMPLETE fleet
    // (200 -> 4,098 DIDs), which quietly walked the cost straight back up. No
    // assertion could see it because nothing counted it.
    agentSprites: props.agents.length,
    /** §STARCAP — live label sprites. Nothing counted is nothing caught: the
     *  eager build was invisible precisely because no counter reported it. */
    agentLabels: agentLabelSprites.length,
    /*
     * §OWNEDHOMES — HOW MANY REGISTRIES ACTUALLY HAVE STARS.
     *
     * "only 5 registries load agents orbiting from start" was true, invisible
     * to every gate, and stayed invisible for two rounds because nothing on
     * this stage counted it. R1.6 cost a round to the same shape: a defect that
     * nothing counts is a defect nothing can catch. One number, so a battery
     * can assert the thing he is actually looking at.
     */
    starRegistries: (() => {
      const seen = new Set<string>()
      for (const a of (props.agents || [])) seen.add(String((a as any)?.registryId || '__local__'))
      return seen.size
    })(),
    starsByRegistry: (() => {
      const m: Record<string, number> = {}
      for (const a of (props.agents || [])) {
        const k = String((a as any)?.registryId || '__local__')
        m[k] = (m[k] || 0) + 1
      }
      return m
    })(),
    agentDataPlaced: agentDataMap.length,
    active: verbsActive.value,
    droppedForPool: verbsDroppedForPool.value,
    // §BRIDGE R8 — he reported "traffic trails not all disappearing", and an
    // impression cannot be debugged. These make the two candidate causes
    // DISTINGUISHABLE from outside: a verb line still drawn for an object the
    // pool has already retired (a leak), versus the #B19 learned lanes, which
    // are scenery and persist for LANE_DECAY_MS by design.
    verbLines: (() => {
      let visible = 0, stray = 0, liveWithLine = 0
      for (const v of verbPool) {
        const vis = !!v.line?.visible
        if (vis) visible++
        if (vis && !v.alive) stray++
        if (v.alive && vis) liveWithLine++
      }
      return { visible, stray, liveWithLine }
    })(),
    paused: missionPaused,
    mode: props.mode,
    usesComposer: !!composer,
    pixelRatio: renderer?.getPixelRatio?.() ?? null,
    fleetLens: fleetLensOn,
    atmosphere: atmosphereMode,
    // R14.1: `observed` vs `fallback` is invisible on screen; count it.
    grading: amountGrader.census(),
    gradedVerbs: { spawned: verbsSpawned, withAmount: verbsWithAmount },
    atmosLayers: atmosLayers.length,
    reducedMotion: REDUCED_MOTION,
  }),
})
</script>

<template>
  <div class="galactic-canvas-wrapper">
    <!-- WebGL Fallback -->
    <div v-if="webglError" class="webgl-fallback">
      <div class="fallback-content">
        <div class="fallback-icon"><Icon name="mdi:creation" /></div>
        <h3>WebGL Unavailable</h3>
        <p>{{ webglErrorMessage || 'Could not initialize 3D rendering.' }}</p>
        <p class="fallback-hint">This usually happens when too many WebGL contexts are open.<br/>Try <strong>closing this tab</strong> and opening a fresh one.</p>
        <button class="fallback-btn" @click="$emit('agent-click', null as any)">Switch to Grid View</button>
      </div>
    </div>

    <div v-show="!webglError" ref="containerRef" class="galactic-canvas" />

    <!-- Hover tooltip is rendered by the parent view (GalacticMap.vue) from the
         agent-hover / registry-hover emits — it owns the shared TopologyHoverLabel
         (agent, with avatar) + RegistryHoverCard (registry, AgentWorld parity).
         The canvas stays emit-only so there is exactly one tooltip. -->
  </div>
</template>



<style scoped>
.galactic-canvas-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 600px;
  overflow: hidden;
}

/* ── WebGL Fallback ── */
.webgl-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  min-height: 600px;
  background: radial-gradient(ellipse at center, #111827 0%, #06060f 100%);
}
.fallback-content {
  text-align: center;
  color: #94a3b8;
  max-width: 400px;
  padding: 2rem;
}
.fallback-icon { font-size: 64px; margin-bottom: 16px; }
.fallback-content h3 { font-size: 20px; font-weight: 600; color: #e2e8f0; margin-bottom: 8px; }
.fallback-content p { font-size: 13px; line-height: 1.5; margin-bottom: 8px; }
.fallback-hint { font-size: 12px; color: #64748b; margin-top: 12px; }
.fallback-btn {
  margin-top: 20px;
  padding: 10px 24px;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}
.fallback-btn:hover { background: #1d4ed8; }

.galactic-canvas {
  width: 100%;
  height: 100%;
  cursor: grab;
}

.galactic-canvas:active {
  cursor: grabbing;
}

/* ── Tooltip ── */
.galactic-tooltip {
  position: absolute;
  pointer-events: none;
  z-index: 100;
  background: rgba(8, 10, 20, 0.92);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(100, 140, 255, 0.2);
  border-radius: 10px;
  padding: 10px 14px;
  min-width: 200px;
  max-width: 320px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 20px rgba(50, 100, 255, 0.08);
}

.tooltip-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tooltip-type-badge {
  font-size: 14px;
}
.tooltip-type-badge.agent { color: #4fc3f7; }
.tooltip-type-badge.registry { color: #00e676; }

.tooltip-name {
  font-weight: 600;
  font-size: 13px;
  color: #e8eaf6;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

.tooltip-detail {
  margin-bottom: 6px;
}

.tooltip-did {
  font-size: 10px;
  color: #7986cb;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.tooltip-stats {
  display: flex;
  gap: 16px;
}

.stat {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.stat-label {
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #78909c;
}

.stat-value {
  font-size: 13px;
  font-weight: 700;
  color: #e0e0e0;
}

.stat-value.elite { color: #ffd700; }
.stat-value.great { color: var(--nc-primary-bright); }
.stat-value.good { color: #4fc3f7; }
.stat-value.low { color: #78909c; }
.stat-value.healthy { color: #00e676; }
.stat-value.warn { color: #ffb300; }
.stat-value.critical { color: #ff5252; }

/* OWL24: Synced badge */
.tooltip-synced-badge {
  display: inline-block;
  padding: 1px 6px;
  background: rgba(255, 171, 64, 0.2);
  border: 1px solid rgba(255, 171, 64, 0.5);
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: #ffab40;
  margin-left: auto;
}

/* Registry status badge */
.tooltip-status-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.5px;
  margin-left: auto;
}
.tooltip-status-badge.active { background: rgba(0, 230, 118, 0.2); border: 1px solid rgba(0, 230, 118, 0.5); color: #00e676; }
.tooltip-status-badge.pending { background: rgba(255, 179, 0, 0.2); border: 1px solid rgba(255, 179, 0, 0.5); color: #ffb300; }
.tooltip-status-badge.inactive { background: rgba(255, 82, 82, 0.2); border: 1px solid rgba(255, 82, 82, 0.5); color: #ff5252; }

/* Description line */
.tooltip-desc {
  font-size: 11px;
  color: #90a4ae;
  line-height: 1.4;
  margin-bottom: 6px;
  max-width: 280px;
}

/* Public URL */
.tooltip-url {
  font-size: 11px;
  color: #4fc3f7;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

/* Capability tags */
.tooltip-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.cap-tag {
  font-size: 9px;
  padding: 1px 6px;
  background: rgba(79, 195, 247, 0.12);
  border: 1px solid rgba(79, 195, 247, 0.3);
  border-radius: 3px;
  color: #4fc3f7;
}

/* Auth method tags */
.tooltip-auth-methods {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.auth-tag {
  font-size: 9px;
  padding: 1px 5px;
  background: rgba(171, 71, 188, 0.15);
  border: 1px solid rgba(171, 71, 188, 0.35);
  border-radius: 3px;
  color: #ce93d8;
  text-transform: capitalize;
}

/* Origin + sync time rows */
.tooltip-origin, .tooltip-sync-time {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
}
</style>
