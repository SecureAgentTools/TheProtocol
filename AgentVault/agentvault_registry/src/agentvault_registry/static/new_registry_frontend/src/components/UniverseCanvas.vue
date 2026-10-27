<script setup lang="ts">
/**
 * UniverseCanvas.vue — OVERBOARD AAA+ Federation of Networks
 *
 * Every rendering technique from GalacticMapCanvas ported and amplified:
 * - Procedural planet textures (1024px, oceans/continents/cities/ice caps)
 * - Animated agent orbits around registry planets
 * - Agent pill labels with colored dots
 * - Multi-layer starfield + nebula clouds + background red dwarf star
 * - Dual-layer spiral galaxy particle clouds per frame
 * - Atmospheric rim glow on planets + ambient dust particles
 * - PointLight per registry illuminating orbiting agents
 * - Federation beams within galaxies (intra-galaxy topology)
 * - Cross-frame bridge with flowing particles + pulsing
 * - InstancedMesh raycasting for agent hover/click
 * - Distance-based label fade
 * - Auto-rotate camera + damped orbit controls
 * - UnrealBloomPass postprocessing
 * - Planet self-rotation in animate loop
 * - Corona pulsing on registries
 * - Connection lines agent → registry
 *
 * No performance constraints. Commander says: "go overboard".
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useCurrency } from '@/composables/useCurrency'
import TopologyHoverLabel from '@/components/TopologyHoverLabel.vue'
// Rich registry hover card — same component AgentWorld uses (Commander: "UNIVERSE
// view registries should have same on hover and on click card as agentworld").
import RegistryHoverCard from '@/components/RegistryHoverCard.vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js'
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js'

// ─── Types ──────────────────────────────────────────────────────
export interface FrameData {
  id: string; name: string; trustDomain: string
  registries: FrameRegistry[]; agents: FrameAgent[]; color: number
}
export interface FrameRegistry {
  id: string; name: string; displayName?: string | null; domain: string; agentCount: number
  health: number; isLocal: boolean; federationLinks?: string[]
  publicUrl?: string; description?: string; status?: string
  trustDomain?: string; authMethods?: string[]; protocolVersion?: string
  lastSyncedAt?: string | null; hopDepth?: number
  // Registry Card v0.3/0.4 slice — surfaced for the rich hover card (parity
  // with AgentWorld). Hydrated in UniverseView from /public/topology.
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
  frame?: string | null
}
export interface FrameAgent {
  did: string; name: string; registryId: string; reputation: number
  status: string; isSynced: boolean; liquidBalance: number; stakedBalance: number
  description?: string; capabilities?: string[]; reputationTier?: string
  totalTransactions?: number; originRegistry?: string
  spiffeId?: string; mtlsEnabled?: boolean
}
export interface BridgeData {
  sourceFrameId: string; targetFrameId: string; syncedCards: number; lastSyncAt: string | null
  // 'federation' = wrapped-token sync beam (gold, default); 'fx' = cross-frame
  // currency-swap corridor (cyan). [Commander 2026-06-07]
  kind?: 'federation' | 'fx'
}

interface AgentOrbit {
  galaxyId: string; center: THREE.Vector3; radius: number
  angle: number; speed: number; yOffset: number; inclination: number
  agentIdx: number  // index into InstancedMesh
  agentDataIdx: number  // index into allAgentData (audit HIGH-4: avoids O(n) indexOf in animate loop)
}

interface Props { frames: FrameData[]; bridges: BridgeData[]; searchQuery?: string; frameFilter?: string; registryFilter?: string }
const props = withDefaults(defineProps<Props>(), { frames: () => [], bridges: () => [], searchQuery: '', frameFilter: 'all', registryFilter: 'all' })
const { localCurrency } = useCurrency()   // FX: tooltip balances in the viewer's currency

// Adapt the canvas tooltipData → the shared TopologyHoverLabel `entity` shape.
const labelEntity = computed<any>(() => {
  const d: any = tooltipData.value
  if (!d) return null
  if (d.type === 'agent') return {
    type: 'agent', name: d.name, did: d.did, description: d.description,
    tierLabel: (d.reputationTier || 'standard').toUpperCase(), tierClass: 'tier-' + (d.reputationTier || 'standard'),
    reputation: d.reputation, totalTransactions: d.totalTransactions,
    isSynced: d.isSynced, mtlsEnabled: d.mtlsEnabled, capabilities: d.capabilities,
    originRegistry: d.originRegistry, spiffeId: d.spiffeId,
    balance: d.balance, liquidBalance: d.liquidBalance, stakedBalance: d.stakedBalance,
    currency: localCurrency.value, frame: d.frame,
  }
  return {
    type: 'registry', name: d.name, description: d.description,
    agentCount: d.agentCount, health: d.health, status: d.status,
    trustDomain: d.trustDomain, authMethods: d.authMethods, hopDepth: d.hopDepth,
  }
})
const emit = defineEmits<{
  'registry-click': [registry: FrameRegistry, frameId: string]
  'agent-click': [agent: FrameAgent, frameId: string]
}>()

// ─── Refs ───────────────────────────────────────────────────────
const containerRef = ref<HTMLDivElement>()
const tooltipVisible = ref(false)
const tooltipData = ref<any>(null)
const tooltipStyle = ref<Record<string, string>>({ left: '0px', top: '0px' })
// Edge-aware tooltip placement — flips left/up near viewport edges so hover
// labels never overflow the canvas (parity with AgentWorld; fixes right-side glitch).
function clampTip(x: number, y: number): Record<string, string> {
  const vw = window.innerWidth, vh = window.innerHeight
  const TW = 300, TH = 240, M = 14
  const s: Record<string, string> = {}
  if (x + M + TW > vw) s.right = `${Math.max(8, vw - x + M)}px`
  else s.left = `${x + M}px`
  if (y - 24 + TH > vh) s.bottom = `${Math.max(8, vh - y + 24)}px`
  else s.top = `${Math.max(8, y - 24)}px`
  return s
}

// ─── Three.js State ─────────────────────────────────────────────
let scene: THREE.Scene, camera: THREE.PerspectiveCamera
let renderer: THREE.WebGLRenderer, composer: EffectComposer
let controls: OrbitControls, animationId: number, clock: THREE.Clock
// UNIVERSE-CINEMA (2026-06-11) — MAP-CINEMA-parity visual layers: star twinkle,
// true fresnel atmospheres, film-grade post pass. Shared clock + reduced-motion
// guard mirror GalacticMapCanvas. Material/post ONLY — orbits/topology/picking/
// lensing/data untouched. Ported verbatim from the proven map shaders.
const REDUCED_MOTION = typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const twinkleTime = { value: 0 }
let filmPass: ShaderPass | null = null

let galaxyGroups: Map<string, THREE.Group> = new Map()
// Per-frame black holes (centered in each galaxy). Each entry is a handle
// into blackHoles[] that we also need keyed by frame id for the lensing
// shader's screen-projection step.
let frameBlackHoleByFrameId: Map<string, BlackHoleData> = new Map()
let bridgeMeshes: THREE.Object3D[] = []
// src/tgt = the two galaxy frame ids this beam connects (so the N-galaxy dance
// updates each bridge from its OWN endpoints, not a hard-coded 0↔1 axis);
// yArc = per-kind vertical arc so a federation + fx beam on the same pair separate.
let bridgeParticles: { points: THREE.Points; curve: THREE.CatmullRomCurve3; offsets: Float32Array; src: string; tgt: string; yArc: number; dir: number; speed: number }[] = []
let bridgeTubes: THREE.Mesh[] = []
let registryMeshes: Map<string, THREE.Mesh> = new Map()    // id → planet core mesh (world space)
let registryGroups: Map<string, THREE.Group> = new Map()    // id → full registry group (in galaxy local space)
let coronaSprites: THREE.Sprite[] = []
let planetCores: THREE.Mesh[] = []

// Per-galaxy agent data
let allAgentOrbits: AgentOrbit[] = []
let allAgentData: FrameAgent[] = []
let agentInstanceMeshes: Map<string, THREE.InstancedMesh> = new Map()  // galaxyId → mesh
let agentGlowLayers: Map<string, THREE.Points> = new Map()
let agentLabelSprites: THREE.Sprite[] = []
let connectionLines: THREE.Object3D[] = []

let raycaster = new THREE.Raycaster()
let mouse = new THREE.Vector2(-999, -999)

// Galaxy orbital dance state
let galaxyOrbitAngle = 0
let galaxyOrbitRadius = GAL_SEP / 2
let orbitCenter = new THREE.Vector3(0, 0, 0)
let bridgeLines: THREE.Line[] = []

// Filter / search state (set in applyFilter, consumed in animate).
let _userMoved = false                          // user dragged the camera → don't auto-resume rotation
let _bridgeDimFactor = 1                         // composed into the FX beam's live pulse
let _matchedDataIdx = new Set<number>()          // allAgentData indices matching the search → shine + scale
const SEARCH_HL = new THREE.Color(0xffffff)      // search-match highlight colour

// ─── Constants ──────────────────────────────────────────────────
const GAL_SEP = 140, SPIRAL_OUTER = 8000, SPIRAL_INNER = 3000, ARMS = 2
const SPIR_R = 70, SPIR_T = 9, REG_SPREAD = 32
const ORB_IN = 5, ORB_OUT = 13, BRIDGE_N = 60, CAM_Z = 240  // wider agent orbits (was 4/10) — declutter
const BG = 0x020206
const PA = { core: 0xcc1100, glow: 0xff3322, part: 0x772222, acc: 0xff4433, label: 0xff0033, labelHex: '#ff0033' }  // Deep dangerous red
const PB = { core: 0x0099ff, glow: 0x44bbff, part: 0x446688, acc: 0x66ccff, label: 0x00e5ff, labelHex: 'var(--nc-primary-bright)' }  // Ice cyan
const PC = { core: 0xcc7700, glow: 0xffb43a, part: 0x7a5a2a, acc: 0xffcc66, label: 0xffb43a, labelHex: '#ffb43a' }  // Amber gold — Frame C (BVT)
// Per-galaxy palettes indexed by frame order. Frame 0 = red, 1 = cyan, 2 = amber-gold (Frame C / BVT),
// then wraps. The 2-frame (A+B) scene renders byte-identically to the prior `idx===0?PA:PB` form.
const GAL_PALETTES = [PA, PB, PC]
const GAL_ARMS = [3, 2, 4]
const GAL_SUBHEX = ['#ff2244', '#44ccdd', '#ffb43a']
// Two beam types, maximally distinct so an A↔C pair carrying BOTH reads cleanly:
//   federation → GOLD (wrapped-token sync; matches the legend swatch + token semantics)
//   fx         → CYAN (cross-currency swap corridor). [Commander 2026-06-07]
const BRIDGE_PALETTES = {
  federation: { core: 0xffd700, glow: 0xffaa22, yArc: 22 },
  fx:         { core: 0x00e5ff, glow: 0x00aacc, yArc: -16 },
} as const

// ─── Helpers ────────────────────────────────────────────────────
function H(s: string): number { let h = 0; for (let i = 0; i < s.length; i++) { h = ((h << 5) - h) + s.charCodeAt(i); h |= 0 }; return Math.abs(h) }
function R(seed: number) { let s = seed; return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646 } }

// 4-tier + federated palette. Matches AgentWorld / Galactic Map naming so
// the Universe View legend describes exactly what the renderer produces.
function getAgentColor(rep: number, synced: boolean): THREE.Color {
  if (synced) return new THREE.Color(0xffab40)     // Federated — warm amber
  if (rep >= 95) return new THREE.Color(0xffd700)  // Elite     — gold
  if (rep >= 80) return new THREE.Color(0x00e5ff)  // Great     — cyan
  if (rep >= 60) return new THREE.Color(0x4fc3f7)  // Good      — light blue
  return new THREE.Color(0x7986cb)                 // Standard  — cool violet
}
function getAgentSize(liq: number, stk: number): number {
  const t = (liq || 0) + (stk || 0); return Math.min(0.6 + Math.log10(t + 1) * 0.15, 1.4)
}

// ─── Textures ───────────────────────────────────────────────────
let _stTx: THREE.Texture | null = null
function starTex(): THREE.Texture {
  if (_stTx) return _stTx
  const c = document.createElement('canvas'); c.width = 64; c.height = 64; const x = c.getContext('2d')!
  const g = x.createRadialGradient(32,32,0,32,32,32)
  g.addColorStop(0,'rgba(255,255,255,1)'); g.addColorStop(0.12,'rgba(220,235,255,0.85)')
  g.addColorStop(0.35,'rgba(150,180,255,0.2)'); g.addColorStop(1,'rgba(0,0,0,0)')
  x.fillStyle = g; x.fillRect(0,0,64,64); _stTx = new THREE.CanvasTexture(c); return _stTx
}
let _glTx: THREE.Texture | null = null
function glowTex(): THREE.Texture {
  if (_glTx) return _glTx
  const c = document.createElement('canvas'); c.width = 128; c.height = 128; const x = c.getContext('2d')!
  const g = x.createRadialGradient(64,64,0,64,64,64)
  g.addColorStop(0,'rgba(255,255,255,0.6)'); g.addColorStop(0.2,'rgba(100,180,255,0.3)')
  g.addColorStop(0.5,'rgba(50,100,200,0.08)'); g.addColorStop(1,'rgba(0,0,0,0)')
  x.fillStyle = g; x.fillRect(0,0,128,128); _glTx = new THREE.CanvasTexture(c); return _glTx
}

function nebSprite(color: number, op: number, sz: number): THREE.Sprite {
  const c = document.createElement('canvas'); c.width = 256; c.height = 256; const x = c.getContext('2d')!
  const r = (color>>16)&255, g = (color>>8)&255, b = color&255
  const gr = x.createRadialGradient(128+(Math.random()-.5)*50,128+(Math.random()-.5)*50,0,128,128,128)
  gr.addColorStop(0,`rgba(${r},${g},${b},${op})`); gr.addColorStop(0.3,`rgba(${r},${g},${b},${op*0.4})`)
  gr.addColorStop(0.7,`rgba(${r},${g},${b},${op*0.08})`); gr.addColorStop(1,'rgba(0,0,0,0)')
  x.fillStyle = gr; x.fillRect(0,0,256,256)
  const m = new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent:true, depthWrite:false, blending:THREE.AdditiveBlending})
  const s = new THREE.Sprite(m); s.scale.setScalar(sz); return s
}

// ─── Procedural Planet (1024px, full detail) ────────────────────
// 2026-05-05 audit BLOCKER-4: LRU eviction at 50-entry cap. Each
// CanvasTexture is ~4 MB GPU; without a cap, registry rename / new
// operator joins / multi-tab traffic grew the cache without bound.
const _PT_CACHE_CAP = 50
const _ptCache = new Map<string, THREE.CanvasTexture>()
function planetTex(base: THREE.Color, seed: number): THREE.CanvasTexture {
  const k = `${base.getHexString()}_${seed}`
  const hit = _ptCache.get(k)
  if (hit) {
    // LRU touch: re-insert so this key becomes most-recently-used.
    _ptCache.delete(k); _ptCache.set(k, hit)
    return hit
  }
  const S = 1024, c = document.createElement('canvas'); c.width = S; c.height = S; const ctx = c.getContext('2d')!
  const rng = R(seed)
  const rr = Math.max(80, Math.round(base.r*255)), gg = Math.max(80, Math.round(base.g*255)), bb = Math.max(80, Math.round(base.b*255))
  const dr = Math.round(rr*0.3)+30, dg = Math.round(gg*0.3)+30, db = Math.round(bb*0.3)+35
  const hr = Math.min(255,rr+110), hg = Math.min(255,gg+110), hb = Math.min(255,bb+110)
  // Ocean
  ctx.fillStyle = `rgb(${dr},${dg},${db})`; ctx.fillRect(0,0,S,S)
  for (let i=0;i<10;i++){const ox=rng()*S,oy=rng()*S,or=40+rng()*150;const og=ctx.createRadialGradient(ox,oy,0,ox,oy,or);og.addColorStop(0,`rgba(${rng()>.5?0:dr+10},${rng()>.5?0:dg+10},${rng()>.5?0:db+10},${0.06+rng()*0.08})`);og.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=og;ctx.fillRect(0,0,S,S)}
  // Continents
  for (let i=0;i<4+Math.floor(rng()*4);i++){const cx=rng()*S,cy=S*0.08+rng()*S*0.84,rx=80+rng()*180,ry=50+rng()*120;const cg=ctx.createRadialGradient(cx+(rng()-.5)*20,cy+(rng()-.5)*15,rx*0.05,cx,cy,rx);cg.addColorStop(0,`rgba(${hr},${hg},${hb},0.95)`);cg.addColorStop(0.25,`rgba(${rr},${gg},${bb},0.85)`);cg.addColorStop(0.5,`rgba(${Math.round(rr*0.6)},${Math.round(gg*0.6)},${Math.round(bb*0.6)},0.4)`);cg.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=cg;ctx.beginPath();ctx.ellipse(cx,cy,rx,ry,rng()*Math.PI,0,Math.PI*2);ctx.fill();for(let j=0;j<8;j++){const sx=cx+(rng()-.5)*rx*1.6,sy=cy+(rng()-.5)*ry*1.6,sr=15+rng()*50;const sg=ctx.createRadialGradient(sx,sy,0,sx,sy,sr);sg.addColorStop(0,`rgba(${rr},${gg},${bb},${0.4+rng()*0.4})`);sg.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=sg;ctx.beginPath();ctx.arc(sx,sy,sr,0,Math.PI*2);ctx.fill()}}
  // Mountains
  for(let i=0;i<8;i++){ctx.strokeStyle=`rgba(${hr},${hg},${hb},${0.05+rng()*0.07})`;ctx.lineWidth=2+rng()*4;ctx.beginPath();let px=rng()*S,py=rng()*S;ctx.moveTo(px,py);for(let j=0;j<5;j++){px+=(rng()-.5)*100;py+=(rng()-.5)*70;ctx.lineTo(px,py)}ctx.stroke()}
  // City lights
  for(let i=0;i<80+Math.floor(rng()*40);i++){const cx=rng()*S,cy=S*0.05+rng()*S*0.9,sz=2+rng()*4,br=0.4+rng()*0.6;const cg=ctx.createRadialGradient(cx,cy,0,cx,cy,sz*2.5);cg.addColorStop(0,`rgba(255,255,255,${br})`);cg.addColorStop(0.3,`rgba(${hr},${hg},${hb},${br*0.4})`);cg.addColorStop(1,'rgba(0,0,0,0)');ctx.fillStyle=cg;ctx.beginPath();ctx.arc(cx,cy,sz*2.5,0,Math.PI*2);ctx.fill()}
  // Polar caps
  const p=ctx.createLinearGradient(0,0,0,S);p.addColorStop(0,`rgba(${hr},${hg},${hb},0.28)`);p.addColorStop(0.05,'rgba(0,0,0,0)');p.addColorStop(0.95,'rgba(0,0,0,0)');p.addColorStop(1,`rgba(${hr},${hg},${hb},0.22)`);ctx.fillStyle=p;ctx.fillRect(0,0,S,S)
  // Cloud wisps
  for(let i=0;i<6;i++){const wx=rng()*S,wy=S*0.15+rng()*S*0.7,ww=60+rng()*160,wh=8+rng()*18;ctx.fillStyle=`rgba(255,255,255,${0.02+rng()*0.025})`;ctx.beginPath();ctx.ellipse(wx,wy,ww,wh,(rng()-.5)*0.5,0,Math.PI*2);ctx.fill()}
  const t = new THREE.CanvasTexture(c); t.wrapS = THREE.RepeatWrapping; t.anisotropy = 4
  // Evict oldest before insert if at cap (LRU — Map iteration order is insertion).
  if (_ptCache.size >= _PT_CACHE_CAP) {
    const firstKey = _ptCache.keys().next().value
    if (firstKey) {
      _ptCache.get(firstKey)?.dispose()
      _ptCache.delete(firstKey)
    }
  }
  _ptCache.set(k, t); return t
}

// ─── Label Generators ───────────────────────────────────────────
function textSprite(text: string, color: string, fontSize = 28): THREE.Sprite {
  const c = document.createElement('canvas'); c.width = 512; c.height = 96; const ctx = c.getContext('2d')!
  ctx.font = `600 ${fontSize}px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  // Dark outline for readability
  ctx.strokeStyle = 'rgba(0,0,0,0.7)'; ctx.lineWidth = 5; ctx.lineJoin = 'round'
  ctx.strokeText(text, 256, 48)
  // Colored glow shadow behind crisp white text (GalacticMap pattern)
  ctx.shadowColor = color; ctx.shadowBlur = 18
  ctx.fillStyle = '#f0f4ff'; ctx.fillText(text, 256, 48)
  ctx.shadowBlur = 0
  const m = new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent:true, depthWrite:false, sizeAttenuation:true})
  return new THREE.Sprite(m)
}

function agentLabel(name: string, accentColor: THREE.Color): THREE.Sprite {
  const c = document.createElement('canvas'); c.width = 512; c.height = 80; const ctx = c.getContext('2d')!
  // Background pill
  ctx.fillStyle = 'rgba(6,6,15,0.55)'; ctx.beginPath()
  if (ctx.roundRect) ctx.roundRect(16, 12, 480, 56, 28); else ctx.rect(16, 12, 480, 56)
  ctx.fill()
  // Colored dot
  const ar = Math.round(accentColor.r*255), ag = Math.round(accentColor.g*255), ab = Math.round(accentColor.b*255)
  ctx.fillStyle = `rgb(${ar},${ag},${ab})`; ctx.beginPath(); ctx.arc(44, 40, 10, 0, Math.PI*2); ctx.fill()
  ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 8; ctx.fill(); ctx.shadowBlur = 0
  // Name
  ctx.font = '500 30px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#e0e4f0'
  const display = name.length > 20 ? name.slice(0,18) + '\u2026' : name
  ctx.fillText(display, 66, 41)
  const m = new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent:true, depthWrite:false, sizeAttenuation:true})
  const s = new THREE.Sprite(m); s.renderOrder = 998; (s.material as THREE.SpriteMaterial).depthTest = false
  return s
}

function regLabel(name: string, trustDomain: string, glowColor: string): THREE.Sprite {
  const c = document.createElement('canvas'); c.width = 512; c.height = 128; const ctx = c.getContext('2d')!
  // Line 1: Registry name (bold white with colored glow)
  ctx.font = '600 30px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.strokeStyle = 'rgba(0,0,0,0.7)'; ctx.lineWidth = 4; ctx.lineJoin = 'round'
  ctx.strokeText(name.length > 24 ? name.slice(0,22) + '\u2026' : name, 256, 38)
  ctx.shadowColor = glowColor; ctx.shadowBlur = 16
  ctx.fillStyle = '#f0f4ff'; ctx.fillText(name.length > 24 ? name.slice(0,22) + '\u2026' : name, 256, 38)
  ctx.shadowBlur = 0
  // Line 2: mTLS badge + trust domain
  const line2 = trustDomain ? `\u{1F512} mTLS  \u00B7  ${trustDomain}` : '\u{1F512} mTLS  \u00B7  SPIRE/SPIFFE'
  ctx.font = '500 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'
  ctx.strokeStyle = 'rgba(0,0,0,0.6)'; ctx.lineWidth = 3
  ctx.strokeText(line2, 256, 78)
  ctx.shadowColor = glowColor; ctx.shadowBlur = 10
  ctx.fillStyle = '#88ddff'; ctx.fillText(line2, 256, 78)
  ctx.shadowBlur = 0
  const m = new THREE.SpriteMaterial({map: new THREE.CanvasTexture(c), transparent:true, depthWrite:false, sizeAttenuation:true})
  return new THREE.Sprite(m)
}

// ─── Gravitational Lensing Shader ────────────────────────────────
// Post-process pass that approximates Schwarzschild photon deflection in
// screen space. Not a full geodesic integration — that would cost a Kerr
// metric ray-march per fragment and won't hit 60 Hz in-browser. Instead:
//   • Each black hole projects to screen UV (uBhUv) with an apparent
//     Schwarzschild radius (uBhRs) in UV units.
//   • Inside the event horizon (r < rs * 0.82) → pure black.
//   • Outside, we displace UVs radially inward by a factor ~ (rs/r)²,
//     matching the weak-field 1/r² limit of GR photon deflection.
//   • The photon sphere (2.6 * rs) gets a bright halo added — matches
//     the Einstein-ring look without needing a separate geometry pass.
//   • Cap at 3 BHs (backdrop + Frame A + Frame B).
const LensingShader = {
  uniforms: {
    tDiffuse: { value: null },
    uBhUv:    { value: [new THREE.Vector2(), new THREE.Vector2(), new THREE.Vector2()] },
    uBhRs:    { value: [0.0, 0.0, 0.0] },      // apparent radius in UV units
    uBhStrength: { value: [0.0, 0.0, 0.0] },   // deflection multiplier
    uAspect:  { value: 1.0 },
    uBhCount: { value: 0 },
  },
  vertexShader: `
    varying vec2 vUv;
    void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
  `,
  fragmentShader: `
    uniform sampler2D tDiffuse;
    uniform vec2 uBhUv[3];
    uniform float uBhRs[3];
    uniform float uBhStrength[3];
    uniform float uAspect;
    uniform int uBhCount;
    varying vec2 vUv;

    void main() {
      vec2 uv = vUv;
      vec3 col = texture2D(tDiffuse, uv).rgb;
      vec3 einstein = vec3(0.0);

      for (int i = 0; i < 3; i++) {
        if (i >= uBhCount) break;
        // Correct aspect so circles look round.
        vec2 d = (uv - uBhUv[i]) * vec2(uAspect, 1.0);
        float r = length(d);
        float rs = uBhRs[i];
        if (rs <= 0.0001) continue;

        // Skip the cheap path for fragments far from the BH.
        if (r > rs * 6.0) continue;

        // Event-horizon cutoff — pixels inside become the BH shadow.
        if (r < rs * 0.82) {
          col = vec3(0.0);
          continue;
        }

        // Radial deflection ~ (rs/r)², clamped so UV offsets stay sane.
        float deflection = rs * rs / max(r * r, rs * rs * 0.5);
        float strength = uBhStrength[i];
        vec2 dir = normalize(d);
        vec2 offset = -dir * deflection * strength * 0.12;
        // Undo aspect on the offset so we sample in true UV.
        offset.x /= uAspect;

        vec3 sampled = texture2D(tDiffuse, uv + offset).rgb;
        col = mix(col, sampled, clamp(deflection * 2.0, 0.0, 0.85));

        // Einstein ring at ~2.6 * rs (photon sphere). Tight gaussian-ish bump.
        float ringR = rs * 2.6;
        float ringWidth = rs * 0.35;
        float ringMask = exp(-pow((r - ringR) / ringWidth, 2.0));
        einstein += vec3(1.0, 0.75, 0.45) * ringMask * strength * 0.55;
      }

      gl_FragColor = vec4(col + einstein, 1.0);
    }
  `,
}
let lensingPass: ShaderPass | null = null
// Scratch vector for per-frame BH screen projection (avoid GC churn).
const _bhScratch = new THREE.Vector3()
// 2026-05-05 audit HIGH-3 + MEDIUM-6: hoisted hot-path scratch objects.
// Animate loop iterates ~700 agents at 60 fps; allocating Object3D + Vector3
// per agent per frame churned ~42k garbage objects/sec. Reusing single
// instances eliminates the alloc pressure.
const _animDummy = new THREE.Object3D()
const _animTmpVec = new THREE.Vector3()

// ─── Black Holes ─────────────────────────────────────────────────
// Three black holes total:
//   [0] backdrop — supermassive anchor far behind (existing)
//   [1] Frame A center — amber/red accretion, anchors Frame A's galaxy
//   [2] Frame B center — ice-blue accretion, anchors Frame B's galaxy
interface BlackHoleData {
  group: THREE.Group
  diskPoints: THREE.Points
  diskOffsets: Float32Array
  eventHorizonRadius: number  // Used by lensing shader for r_s uniform
}
let blackHoles: BlackHoleData[] = []
// Back-compat alias so the original backdrop-BH references keep working.
let blackHoleGroup: THREE.Group | null = null
let accretionDiskPoints: THREE.Points | null = null
let accretionOffsets: Float32Array | null = null

interface BlackHolePalette {
  glow: number          // Gravitational halo color
  diskInner: [number, number, number]  // RGB 0..1 for white-hot core
  diskMid: [number, number, number]
  diskOuter: [number, number, number]
  ringA: number         // Primary photon-ring color
  ringB: number         // Secondary photon-ring color
}

// Warm amber — matches the Interstellar look for the backdrop and Frame A.
const BH_PALETTE_AMBER: BlackHolePalette = {
  glow: 0xcc6600,
  diskInner: [1.0, 0.90, 0.70],
  diskMid:   [1.0, 0.55, 0.10],
  diskOuter: [0.60, 0.15, 0.05],
  ringA: 0xffaa44, ringB: 0xff8833,
}
// Ice blue — Frame B. Cooler disk tones, blue-white photon rings.
const BH_PALETTE_AZURE: BlackHolePalette = {
  glow: 0x2288dd,
  diskInner: [0.85, 0.95, 1.00],
  diskMid:   [0.30, 0.65, 1.00],
  diskOuter: [0.10, 0.25, 0.65],
  ringA: 0x66ccff, ringB: 0x3399ff,
}
// Amber gold — Frame C (BVT). Warm golden disk, yellow photon rings.
const BH_PALETTE_GOLD: BlackHolePalette = {
  glow: 0xddaa22,
  diskInner: [1.0, 0.96, 0.78],
  diskMid:   [1.0, 0.72, 0.20],
  diskOuter: [0.55, 0.32, 0.05],
  ringA: 0xffcc55, ringB: 0xffb33a,
}
// Indexed by frame order (matches GAL_PALETTES). 2-frame scene unchanged.
const BH_PALETTES = [BH_PALETTE_AMBER, BH_PALETTE_AZURE, BH_PALETTE_GOLD]

function createBlackHole(
  position: THREE.Vector3,
  scale: number,           // 1.0 = backdrop size (event horizon r=8), 0.35 = per-frame
  palette: BlackHolePalette,
  particleCount: number,
): BlackHoleData {
  const group = new THREE.Group()
  group.position.copy(position)
  group.rotation.x = 0.3; group.rotation.z = 0.15  // Tilt ~75°, Interstellar-style

  const rs = 8 * scale    // Event-horizon "Schwarzschild" radius (proxy)

  // Event horizon — pure black sphere
  group.add(new THREE.Mesh(
    new THREE.SphereGeometry(rs, 64, 32),
    new THREE.MeshBasicMaterial({ color: 0x000000 })
  ))

  // Dark anti-glow — radial canvas, bright warm ring, dark center
  const agC = document.createElement('canvas'); agC.width = 256; agC.height = 256
  const agCtx = agC.getContext('2d')!
  const agGrad = agCtx.createRadialGradient(128, 128, 40, 128, 128, 128)
  const g = palette.glow
  const gR = (g >> 16) & 0xff, gG = (g >> 8) & 0xff, gB = g & 0xff
  agGrad.addColorStop(0, 'rgba(0,0,0,0.9)')
  agGrad.addColorStop(0.4, 'rgba(0,0,0,0.6)')
  agGrad.addColorStop(0.7, `rgba(${gR},${gG},${gB},0.15)`)
  agGrad.addColorStop(0.85, `rgba(${gR},${gG},${gB},0.08)`)
  agGrad.addColorStop(1, 'rgba(0,0,0,0)')
  agCtx.fillStyle = agGrad; agCtx.fillRect(0, 0, 256, 256)
  const antiGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(agC), transparent: true, depthWrite: false,
  }))
  antiGlow.scale.set(rs * 7.5, rs * 7.5, 1)
  group.add(antiGlow)

  // Gravitational glow halo (light bending around)
  const gravGlow = new THREE.Sprite(new THREE.SpriteMaterial({
    map: glowTex(), color: palette.glow, transparent: true, opacity: 0.18,
    depthWrite: false, blending: THREE.AdditiveBlending,
  }))
  gravGlow.scale.set(rs * 15, rs * 15, 1)
  group.add(gravGlow)

  // Photon rings
  group.add(new THREE.Mesh(
    new THREE.TorusGeometry(rs * 1.25, 0.2 * scale, 16, 128),
    new THREE.MeshBasicMaterial({ color: palette.ringA, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending })
  ))
  group.add(new THREE.Mesh(
    new THREE.TorusGeometry(rs * 1.44, 0.1 * scale, 16, 128),
    new THREE.MeshBasicMaterial({ color: palette.ringB, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending })
  ))

  // Accretion disk — fast-orbiting particles (Kepler speeds in animate loop)
  const diskPos = new Float32Array(particleCount * 3)
  const diskColors = new Float32Array(particleCount * 3)
  const diskOffsets = new Float32Array(particleCount)

  const diskInnerR = rs * 1.5, diskOuterR = rs * 5.25
  for (let i = 0; i < particleCount; i++) {
    const angle = Math.random() * Math.PI * 2
    const r = diskInnerR + Math.random() * (diskOuterR - diskInnerR)
    const thickness = (1 - (r - diskInnerR) / (diskOuterR - diskInnerR)) * 1.5 * scale
    const y = (Math.random() - 0.5) * thickness

    diskPos[i * 3] = Math.cos(angle) * r
    diskPos[i * 3 + 1] = y
    diskPos[i * 3 + 2] = Math.sin(angle) * r
    diskOffsets[i] = angle

    const tNorm = (r - diskInnerR) / (diskOuterR - diskInnerR)
    let c: [number, number, number]
    if (tNorm < 0.2)      c = palette.diskInner
    else if (tNorm < 0.5) c = palette.diskMid
    else                  c = palette.diskOuter
    diskColors[i * 3] = c[0]; diskColors[i * 3 + 1] = c[1]; diskColors[i * 3 + 2] = c[2]
  }

  const diskGeo = new THREE.BufferGeometry()
  diskGeo.setAttribute('position', new THREE.BufferAttribute(diskPos, 3))
  diskGeo.setAttribute('color', new THREE.BufferAttribute(diskColors, 3))
  const diskMat = new THREE.PointsMaterial({
    size: 0.8 * scale, sizeAttenuation: true, transparent: true, opacity: 0.7,
    vertexColors: true, depthWrite: false, blending: THREE.AdditiveBlending,
    map: starTex(),
  })
  const diskPoints = new THREE.Points(diskGeo, diskMat)
  group.add(diskPoints)

  return { group, diskPoints, diskOffsets, eventHorizonRadius: rs }
}

// Build the backdrop BH plus one per frame. Per-frame BHs are added to their
// galaxy group by the caller so they inherit the waltz motion.
function createBackdropBlackHole() {
  const bh = createBlackHole(
    new THREE.Vector3(0, -30, -250),
    1.0,
    BH_PALETTE_AMBER,
    4000,
  )
  scene.add(bh.group)
  blackHoles.push(bh)
  // Back-compat aliases for the old animate loop & galaxy-waltz drift target.
  blackHoleGroup = bh.group
  accretionDiskPoints = bh.diskPoints
  accretionOffsets = bh.diskOffsets
}

// ─── Scene Init ─────────────────────────────────────────────────
function initScene() {
  if (!containerRef.value) return
  const w = containerRef.value.clientWidth, h = containerRef.value.clientHeight
  scene = new THREE.Scene(); scene.background = new THREE.Color(BG); scene.fog = new THREE.FogExp2(BG, 0.0012)
  camera = new THREE.PerspectiveCamera(55, w/h, 0.1, 2000)
  // Back the camera off as the galaxy ring grows so 3+ frames all fit the frame.
  // (Canvas mounts only after UniverseView finishes loading → frame count known.)
  const _nF = props.frames.length
  const _camZ = _nF >= 3 ? CAM_Z + (_nF - 2) * 80 : CAM_Z
  camera.position.set(0, 90, _camZ)
  try { renderer = new THREE.WebGLRenderer({antialias:true, powerPreference:'high-performance'}) } catch { return }
  renderer.setSize(w,h); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.5  // CINEMA full-send: punchier exposure (1.4→1.5)
  containerRef.value.appendChild(renderer.domElement)
  composer = new EffectComposer(renderer); composer.addPass(new RenderPass(scene, camera))
  // Lensing pass BEFORE bloom so the Einstein ring gets bloomed correctly.
  lensingPass = new ShaderPass(LensingShader)
  lensingPass.uniforms.uAspect.value = w / h
  composer.addPass(lensingPass)
  composer.addPass(new UnrealBloomPass(new THREE.Vector2(w,h), 1.28, 0.45, 0.6))  // CINEMA full-send: hotter bloom (1.0→1.28) + slightly wider radius; threshold HELD at 0.6 (star-haze guard)
  // UNIVERSE-CINEMA: film grade after bloom — radial chromatic aberration (edges only)
  // + gentle saturation + vignette + teal shadow-lift + temporal grain. uTime ticked
  // in animate() (frozen under reduced-motion). Amplitudes kept tiny; legibility first.
  filmPass = new ShaderPass({
    uniforms: { tDiffuse: { value: null }, uTime: { value: 0 } },
    vertexShader: `varying vec2 vUv;
      void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D tDiffuse; uniform float uTime; varying vec2 vUv;
      void main() {
        vec2 q = vUv - 0.5;
        float r2 = dot(q, q);
        vec2 ca = q * r2 * 0.016;
        vec4 c;
        c.r = texture2D(tDiffuse, vUv + ca).r;
        c.g = texture2D(tDiffuse, vUv).g;
        c.b = texture2D(tDiffuse, vUv - ca).b;
        c.a = 1.0;
        float luma = dot(c.rgb, vec3(0.299, 0.587, 0.114));
        c.rgb = mix(vec3(luma), c.rgb, 1.07);
        float vig = smoothstep(0.97, 0.34, length(q) * 1.36);
        c.rgb *= mix(0.80, 1.0, vig);
        c.rgb += vec3(0.004, 0.009, 0.013) * (1.0 - clamp(luma, 0.0, 1.0));
        float g = fract(sin(dot(vUv * (mod(uTime, 7.0) + 1.0), vec2(12.9898, 78.233))) * 43758.5453);
        c.rgb += (g - 0.5) * 0.014;
        gl_FragColor = c;
      }`,
  })
  composer.addPass(filmPass)
  composer.addPass(new OutputPass())
  controls = new OrbitControls(camera, renderer.domElement)
  controls.enableDamping = true; controls.dampingFactor = 0.06; controls.minDistance = 20; controls.maxDistance = 500
  controls.maxPolarAngle = Math.PI * 0.85; controls.autoRotate = !REDUCED_MOTION; controls.autoRotateSpeed = 0.12
  controls.target.set(0, -5, 0); controls.addEventListener('start', () => { controls.autoRotate = false; _userMoved = true })
  // Lighting
  scene.add(new THREE.AmbientLight(0x8899bb, 0.7))
  const k = new THREE.DirectionalLight(0xeef4ff, 0.8); k.position.set(60,100,50); scene.add(k)
  const f = new THREE.DirectionalLight(0x5566aa, 0.3); f.position.set(-40,-20,-60); scene.add(f)
  clock = new THREE.Clock()
  buildStarfield()
  blackHoles = []  // rebuilt below; per-frame BHs pushed via createGalaxy()
  createBackdropBlackHole()
  window.addEventListener('resize', onResize)
  renderer.domElement.addEventListener('mousemove', onMouseMove)
  renderer.domElement.addEventListener('click', onClick)
}

function buildStarfield() {
  const t = starTex()
  addStars(4200,600,0.85,0.34,0x7788aa,t); addStars(1100,350,1.45,0.56,0xaabbdd,t)  // full-send: denser+brighter dim star layers (below bloom threshold → richness, no haze)
  addStars(150,250,2.5,0.8,0xddeeff,t); addStars(40,400,2.0,0.55,0xffcc88,t)
  // UNIVERSE-CINEMA glorious: richer, more chromatic deep-space nebula field (still
  // faint + additive — colours the void between galaxies without flattening depth).
  const _nebCols=[0x3a4ea0,0x5b3a72,0x244a66,0x4a3a26,0x256a55,0x4a2a55,0x26406a,0x356b44,0x6a5236,0x33356e,0x3a2a78,0x205274,0x582a58,0x2a5a66]
  for(let i=0;i<14;i++){const n=nebSprite(_nebCols[i%_nebCols.length],0.06+Math.random()*0.06,90+Math.random()*220);n.position.set((Math.random()-.5)*620,(Math.random()-.5)*260,(Math.random()-.5)*620);scene.add(n)}
  // Background red dwarf star
  const rdGroup = new THREE.Group(); rdGroup.position.set(180, 80, -300)
  const rdCore = new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:0xdd2200,transparent:true,opacity:0.7,blending:THREE.AdditiveBlending,depthWrite:false})); rdCore.scale.setScalar(25); rdGroup.add(rdCore)
  const rdOuter = new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:0x991100,transparent:true,opacity:0.15,blending:THREE.AdditiveBlending,depthWrite:false})); rdOuter.scale.setScalar(100); rdGroup.add(rdOuter)
  const rdLight = new THREE.PointLight(0xdd2200, 1.5, 500); rdGroup.add(rdLight)
  scene.add(rdGroup)
}
function addStars(n:number,sp:number,sz:number,op:number,col:number,tx:THREE.Texture){
  const p=new Float32Array(n*3),ph=new Float32Array(n)
  for(let i=0;i<n;i++){p[i*3]=(Math.random()-.5)*sp*2;p[i*3+1]=(Math.random()-.5)*sp*2;p[i*3+2]=(Math.random()-.5)*sp*2;ph[i]=Math.random()*6.2832}
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(p,3));g.setAttribute('aPhase',new THREE.BufferAttribute(ph,1))
  const m=new THREE.PointsMaterial({map:tx,size:sz,sizeAttenuation:true,transparent:true,opacity:op,color:col,depthWrite:false,blending:THREE.AdditiveBlending})
  // UNIVERSE-CINEMA: per-star brightness twinkle (one shared clock; the clock simply
  // never ticks under prefers-reduced-motion → stars hold steady).
  m.onBeforeCompile=(shader)=>{shader.uniforms.uTwinkleTime=twinkleTime
    shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nattribute float aPhase;\nvarying float vPhase;').replace('#include <begin_vertex>','#include <begin_vertex>\nvPhase = aPhase;')
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nuniform float uTwinkleTime;\nvarying float vPhase;').replace('#include <color_fragment>','#include <color_fragment>\ndiffuseColor.a *= 0.70 + 0.30 * sin(uTwinkleTime * (1.1 + fract(vPhase) * 0.9) + vPhase);')}
  scene.add(new THREE.Points(g,m))
}

// 2026-05-05 audit BLOCKER-3: walk an Object3D and dispose all owned GPU
// resources (geometry + material(s) + their textures). Used at buildScene
// rebuild time so the previous frame's GPU memory doesn't accumulate
// across data updates. scene.remove() only detaches; explicit dispose is
// required to free WebGL state.
function _disposeMaterial(m: any) {
  if (!m) return
  if (Array.isArray(m)) { m.forEach(_disposeMaterial); return }
  // CanvasTexture / Texture maps
  if (m.map?.dispose) m.map.dispose()
  if (m.lightMap?.dispose) m.lightMap.dispose()
  if (m.aoMap?.dispose) m.aoMap.dispose()
  if (m.emissiveMap?.dispose) m.emissiveMap.dispose()
  if (m.bumpMap?.dispose) m.bumpMap.dispose()
  if (m.normalMap?.dispose) m.normalMap.dispose()
  if (m.alphaMap?.dispose) m.alphaMap.dispose()
  if (typeof m.dispose === 'function') m.dispose()
}
function _disposeObject3D(obj: any) {
  if (!obj) return
  if (obj.geometry?.dispose) obj.geometry.dispose()
  _disposeMaterial(obj.material)
}
function _disposeGroupRecursive(g: any) {
  if (!g) return
  g.traverse?.((child: any) => _disposeObject3D(child))
}

// ─── Galaxy Builder ─────────────────────────────────────────────
function buildScene() {
  // BLOCKER-3: dispose GPU resources on rebuild (was: scene.remove() only,
  // which left geometries/materials/textures resident in WebGL state).
  for(const[,g]of galaxyGroups){ _disposeGroupRecursive(g); scene.remove(g) }
  galaxyGroups.clear(); registryMeshes.clear(); registryGroups.clear()
  // Drop any per-frame BHs from previous build. Backdrop BH (index 0) stays.
  frameBlackHoleByFrameId.clear()
  if (blackHoles.length > 1) blackHoles = blackHoles.slice(0, 1)
  coronaSprites=[]; planetCores=[]; allAgentOrbits=[]; allAgentData=[]
  for(const[,m]of agentInstanceMeshes){ _disposeObject3D(m); scene.remove(m) }
  agentInstanceMeshes.clear()
  for(const[,p]of agentGlowLayers){ _disposeObject3D(p); scene.remove(p) }
  agentGlowLayers.clear()
  agentLabelSprites.forEach(s=>{ _disposeObject3D(s); s.parent?.remove(s) }); agentLabelSprites=[]
  connectionLines.forEach(l=>{ _disposeObject3D(l); scene.remove(l) }); connectionLines=[]
  for(const b of bridgeMeshes){ _disposeObject3D(b); scene.remove(b) }
  bridgeMeshes=[]; bridgeParticles=[]; bridgeTubes=[]; bridgeLines=[]
  galaxyOrbitAngle=0; orbitCenter.set(0,0,0); galaxyOrbitRadius=GAL_SEP/2
  if(props.frames.length===0)return

  const tw=(props.frames.length-1)*GAL_SEP, sx=-tw/2
  props.frames.forEach((frame,idx)=>{
    const g=createGalaxy(frame,new THREE.Vector3(sx+idx*GAL_SEP,0,0),idx)
    scene.add(g); galaxyGroups.set(frame.id,g)
  })
  for(const br of props.bridges){const a=galaxyGroups.get(br.sourceFrameId),b=galaxyGroups.get(br.targetFrameId);if(a&&b)createBridge(a.position,b.position,br)}
  // Re-assert any active search/frame filter against the freshly-built materials.
  applyFilter()
}

function createGalaxy(frame: FrameData, pos: THREE.Vector3, idx: number): THREE.Group {
  const g = new THREE.Group(); g.position.copy(pos)
  g.userData = {type:'galaxy',frameId:frame.id,frameName:frame.name}
  const p = GAL_PALETTES[idx % GAL_PALETTES.length]

  // Per-galaxy arms by frame order (3 / 2 / 4 …), wraps for N frames.
  const arms = GAL_ARMS[idx % GAL_ARMS.length]

  // Per-frame black hole at the galaxy's local origin — registries orbit it.
  // Frame 0 amber/red, Frame 1 ice-blue, Frame 2 gold (Frame C) to match palettes.
  const bhPalette = BH_PALETTES[idx % BH_PALETTES.length]
  const frameBh = createBlackHole(new THREE.Vector3(0, 0, 0), 0.35, bhPalette, 1600)
  g.add(frameBh.group)
  blackHoles.push(frameBh)
  frameBlackHoleByFrameId.set(frame.id, frameBh)

  // Spiral layers (fixed radius — don't scale, it looked perfect at SPIR_R)
  addSpiral(g,SPIRAL_OUTER,SPIR_R,SPIR_T,0.45,0.9,p.part,arms)
  addSpiral(g,SPIRAL_INNER,SPIR_R*0.5,SPIR_T*0.5,0.7,1.6,p.acc,arms)

  // Core + halo
  const cs=Math.max(28,18+frame.registries.length*2)
  const core=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:p.glow,transparent:true,opacity:0.4,depthWrite:false,blending:THREE.AdditiveBlending}));core.scale.set(cs,cs,1);g.add(core)
  const halo=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:p.part,transparent:true,opacity:0.12,depthWrite:false,blending:THREE.AdditiveBlending}));halo.scale.set(SPIR_R*2.8,SPIR_R*2.8,1);g.add(halo)

  // Galaxy nebulae
  for(let i=0;i<5;i++){const n=nebSprite(p.part,0.07+Math.random()*0.06,30+Math.random()*50);const a=Math.random()*Math.PI*2,d=10+Math.random()*SPIR_R*0.6;n.position.set(Math.cos(a)*d,(Math.random()-.5)*8,Math.sin(a)*d);g.add(n)}

  // Labels — frame name in bold color, subtitle in matching tint
  const lbl=textSprite(frame.name,p.labelHex,32);lbl.position.set(0,SPIR_R*0.55+14,0);lbl.scale.set(30,4,1);g.add(lbl)
  const subColor = GAL_SUBHEX[idx % GAL_SUBHEX.length]
  const sub=textSprite(`${frame.registries.length} registries  ·  ${frame.agents.length} agents`,subColor,22);sub.position.set(0,SPIR_R*0.55+7,0);sub.scale.set(24,3,1);g.add(sub)

  // ── Registries — Keplerian orbital rings around the frame's black hole ──
  // Scalable to any number of registries. Each gets a deterministic
  // (radius, phase, inclination) triple from its hash. Galaxy rotation
  // (line ~580) gives macro orbital motion; individual registries stay static
  // in galaxy-local frame so agent positions stay stable.
  const regs = frame.registries, baseCol = new THREE.Color(p.core)
  const BH_EH = frameBh.eventHorizonRadius       // ~2.8 at scale 0.35
  // Accretion disk outer edge is ~5.25·rs; give planets real breathing room
  // past it. Orbital rings land in an annulus that's visually decoupled from
  // the black-hole glow and accretion disk.
  const ORBIT_MIN = BH_EH * 9                    // ~25 — well clear of the disk
  const ORBIT_MAX = BH_EH * 18                   // ~50 — far edge, inside galaxy halo
  regs.forEach((reg,i)=>{
    const rng = R(H(reg.id))
    // Distribute radii across shells so planets don't pile into one annulus.
    const shellFrac = regs.length > 1 ? i / (regs.length - 1) : 0.5
    const orbitRadius = ORBIT_MIN + shellFrac * (ORBIT_MAX - ORBIT_MIN) + (rng() - 0.5) * 2
    // 2026-05-05 audit BLOCKER-1: deterministic slot + jitter (was random
    // phase). At 14 regs × adjacent-shell separation 1.94 vs visual-sum 9.1,
    // the previous random phase produced reliable clipping pairs (e.g.
    // op-stockholm ↔ op-zurich). Even slot distribution gives every reg
    // ~70% of its angular slot of clearance from neighbours.
    const slot = (Math.PI * 2) / Math.max(1, regs.length)
    const jitter = (rng() - 0.5) * slot * 0.6
    const phase = i * slot + jitter
    // Mild orbit-plane inclination ±10° so the cluster reads as 3-D.
    const inclination = (rng() - 0.5) * 0.35
    const x = orbitRadius * Math.cos(phase)
    const y = orbitRadius * Math.sin(inclination) * Math.sin(phase) + (rng() - 0.5) * 1.5
    const z = orbitRadius * Math.sin(phase) * Math.cos(inclination)
    const sz=Math.max(2,Math.min(4,2+Math.sqrt(reg.agentCount)*0.3))

    // Faint orbital path (torus line) so the orbital structure reads clearly.
    const orbitGeo = new THREE.TorusGeometry(orbitRadius, 0.06, 4, 96)
    const orbitMat = new THREE.MeshBasicMaterial({
      color: p.glow, transparent: true, opacity: 0.08, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    const orbitLine = new THREE.Mesh(orbitGeo, orbitMat)
    orbitLine.rotation.x = Math.PI / 2 + inclination
    orbitLine.raycast = () => {}
    g.add(orbitLine)

    const rg = new THREE.Group(); rg.position.set(x,y,z)
    rg.userData = {type:'registry',registry:reg,frameId:frame.id}

    // Planet core (1024px procedural texture)
    const geo=new THREE.SphereGeometry(sz,48,32)
    const emBase = baseCol.clone().multiplyScalar(0.25).add(new THREE.Color(0x252530))
    const pt = planetTex(baseCol, H(reg.id))
    const mat=new THREE.MeshStandardMaterial({map:pt,emissive:emBase,emissiveIntensity:2.5,roughness:0.65,metalness:0.25,emissiveMap:pt})
    const mesh=new THREE.Mesh(geo,mat); mesh.userData={isPlanetCore:true}; rg.add(mesh)
    planetCores.push(mesh)

    // Atmosphere rim — UNIVERSE-CINEMA: true fresnel (view-dependent, edge-only) replaces
    // the flat 0.06 BackSide wash. The face never fills (pow-3 falloff) so it can carry a
    // stronger, richer rim without the "flummy ball". raycast-excluded (picking = core mesh).
    const atGeo=new THREE.SphereGeometry(sz*1.05,24,16)
    const atMat=new THREE.ShaderMaterial({transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,side:THREE.BackSide,
      uniforms:{uColor:{value:new THREE.Color(p.core).multiplyScalar(1.7)}},
      vertexShader:`varying vec3 vN;varying vec3 vV;void main(){vN=normalize(normalMatrix*normal);vec4 mv=modelViewMatrix*vec4(position,1.0);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`uniform vec3 uColor;varying vec3 vN;varying vec3 vV;void main(){float rim=pow(1.0-abs(dot(vN,vV)),3.0);gl_FragColor=vec4(uColor,rim*0.6);}`})
    const atMesh=new THREE.Mesh(atGeo,atMat); atMesh.raycast=()=>{}; rg.add(atMesh)

    // Ambient glow (reduced to prevent wash-out)
    const ag=new THREE.Sprite(new THREE.SpriteMaterial({map:glowTex(),color:p.glow,transparent:true,opacity:0.07,blending:THREE.AdditiveBlending,depthWrite:false}));ag.scale.setScalar(sz*3.5);ag.raycast=()=>{};rg.add(ag)
    coronaSprites.push(ag)

    // Point light
    rg.add(new THREE.PointLight(p.core, 1.2, ORB_OUT*3.5))

    // Dust particles
    const dN=30,dP=new Float32Array(dN*3)
    for(let di=0;di<dN;di++){const th=Math.random()*Math.PI*2,ph=Math.acos(2*Math.random()-1),rd=sz*(1+Math.random()*0.3);dP[di*3]=rd*Math.sin(ph)*Math.cos(th);dP[di*3+1]=rd*Math.sin(ph)*Math.sin(th);dP[di*3+2]=rd*Math.cos(ph)}
    const dGeo=new THREE.BufferGeometry();dGeo.setAttribute('position',new THREE.Float32BufferAttribute(dP,3))
    const dMat=new THREE.PointsMaterial({size:0.5,map:glowTex(),color:p.core,transparent:true,opacity:0.3,depthWrite:false,blending:THREE.AdditiveBlending})
    const dust=new THREE.Points(dGeo,dMat);dust.raycast=()=>{};rg.add(dust)

    // Registry label (clean name, hop depth in tooltip)
    const rl=textSprite(reg.name,p.labelHex,28);rl.position.set(0,sz+4,0);rl.scale.set(16,2.5,1);rl.renderOrder=999;(rl.material as THREE.SpriteMaterial).depthTest=false;rl.raycast=()=>{};rg.add(rl)

    g.add(rg); registryGroups.set(reg.id, rg)
    // Store world-space mesh reference for raycasting
    registryMeshes.set(reg.id, mesh)
  })

  // ── Agents (instanced + orbits + labels + glow) ──
  const agents = frame.agents
  if (agents.length > 0) {
    const agGeo = new THREE.SphereGeometry(1, 32, 20)
    const agMat = new THREE.MeshStandardMaterial({roughness:0.15,metalness:0.6,emissive:new THREE.Color(0x88bbff),emissiveIntensity:0.5})
    const im = new THREE.InstancedMesh(agGeo, agMat, agents.length)
    const glowPos = new Float32Array(agents.length * 3)
    const glowCols = new Float32Array(agents.length * 3)
    const dummy = new THREE.Object3D(), color = new THREE.Color()

    // 2026-05-05 audit MEDIUM-7: deterministic per-registry slot+jitter
    // for agent phases (was random). Two-pass: count agents per registry,
    // then assign each agent a slot within its registry's circle.
    const agentSlotPerReg = new Map<string, { idx: number; total: number }>()
    for (const a of agents) {
      const cur = agentSlotPerReg.get(a.registryId)
      if (cur) cur.total++
      else agentSlotPerReg.set(a.registryId, { idx: 0, total: 1 })
    }

    agents.forEach((agent, ai) => {
      const regGrp = registryGroups.get(agent.registryId)
      const center = regGrp ? regGrp.position.clone() : new THREE.Vector3(0,0,0)
      const rng = R(H(agent.did))
      const repFactor = 1 - (agent.reputation||0)/100
      const dist = ORB_IN + repFactor * (ORB_OUT - ORB_IN) * (0.4+rng()*0.6)
      const slotCtx = agentSlotPerReg.get(agent.registryId)!
      const slotN = Math.max(1, slotCtx.total)
      const slot = (Math.PI * 2) / slotN
      const slotJitter = (rng() - 0.5) * slot * 0.5
      const startAngle = slotCtx.idx * slot + slotJitter
      slotCtx.idx++
      const incl = (rng()-.5)*0.95, spd = 0.04 + rng()*0.1, yOff = (rng()-.5)*5  // wider 3-D spread — declutter

      // Initial position
      const px = center.x + dist*Math.cos(startAngle)
      const py = center.y + yOff + dist*Math.sin(incl)*Math.sin(startAngle)
      const pz = center.z + dist*Math.sin(startAngle)*Math.cos(incl)

      const sz = getAgentSize(agent.liquidBalance, agent.stakedBalance)
      dummy.position.set(px,py,pz); dummy.scale.setScalar(sz); dummy.updateMatrix()
      im.setMatrixAt(ai, dummy.matrix)

      const c = getAgentColor(agent.reputation, agent.isSynced)
      im.setColorAt(ai, c)

      glowPos[ai*3]=px; glowPos[ai*3+1]=py; glowPos[ai*3+2]=pz
      glowCols[ai*3]=c.r; glowCols[ai*3+1]=c.g; glowCols[ai*3+2]=c.b

      // Store orbit data — agentDataIdx avoids per-frame O(n) indexOf in animate loop
      const dataIdx = allAgentData.length
      allAgentOrbits.push({galaxyId:frame.id, center, radius:dist, angle:startAngle, speed:spd, yOffset:yOff, inclination:incl, agentIdx:ai, agentDataIdx:dataIdx})
      allAgentData.push(agent)

      // Agent pill label
      const lbl = agentLabel(agent.name || 'Agent', c)
      lbl.position.set(px, py + sz + 1.2, pz); lbl.scale.set(5, 0.8, 1)
      lbl.userData = {agentOrbitIdx: allAgentOrbits.length - 1, galaxyId: frame.id}
      g.add(lbl); agentLabelSprites.push(lbl)
    })

    im.instanceMatrix.needsUpdate = true
    if (im.instanceColor) im.instanceColor.needsUpdate = true
    g.add(im); agentInstanceMeshes.set(frame.id, im)

    // Glow halo layer
    const glGeo=new THREE.BufferGeometry();glGeo.setAttribute('position',new THREE.Float32BufferAttribute(glowPos,3));glGeo.setAttribute('color',new THREE.Float32BufferAttribute(glowCols,3))
    const glMat=new THREE.PointsMaterial({size:3,map:glowTex(),transparent:true,opacity:0.3,vertexColors:true,sizeAttenuation:true,depthWrite:false,blending:THREE.AdditiveBlending})
    const glPts=new THREE.Points(glGeo,glMat);g.add(glPts);agentGlowLayers.set(frame.id, glPts)
  }

  return g
}

function addSpiral(g:THREE.Group,n:number,r:number,t:number,op:number,sz:number,col:number,arms:number=3){const p=new Float32Array(n*3),c=new Float32Array(n*3),b=new THREE.Color(col);for(let i=0;i<n;i++){const arm=i%arms,tt=(i/n)*4,ao=(arm/arms)*Math.PI*2,a=tt*Math.PI*2+ao,rr=tt*r/4,sp=t*(1+tt*0.3);p[i*3]=Math.cos(a)*rr+(Math.random()-.5)*sp;p[i*3+1]=(Math.random()-.5)*t*0.35;p[i*3+2]=Math.sin(a)*rr+(Math.random()-.5)*sp;const br=0.5+0.5*(1-tt/4);c[i*3]=b.r*br+Math.random()*0.08;c[i*3+1]=b.g*br+Math.random()*0.08;c[i*3+2]=b.b*br+Math.random()*0.08};const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.BufferAttribute(p,3));geo.setAttribute('color',new THREE.BufferAttribute(c,3));g.add(new THREE.Points(geo,new THREE.PointsMaterial({size:sz,sizeAttenuation:true,transparent:true,opacity:op,vertexColors:true,depthWrite:false,blending:THREE.AdditiveBlending,map:starTex()})))}

// ─── Bridge ─────────────────────────────────────────────────────
// One flowing-particle stream along a bridge curve. dir = ±1 (flow direction),
// speed = curve-fraction/sec. FX corridors get TWO counter-flowing streams.
function _addBridgeStream(cv:THREE.CatmullRomCurve3,color:number,size:number,dir:number,speed:number,src:string,tgt:string,yArc:number){
  const pp=new Float32Array(BRIDGE_N*3),ofs=new Float32Array(BRIDGE_N)
  for(let i=0;i<BRIDGE_N;i++){ofs[i]=i/BRIDGE_N;const pt=cv.getPointAt(ofs[i]);pp[i*3]=pt.x;pp[i*3+1]=pt.y;pp[i*3+2]=pt.z}
  const pg=new THREE.BufferGeometry();pg.setAttribute('position',new THREE.BufferAttribute(pp,3))
  const pm=new THREE.PointsMaterial({map:starTex(),size,sizeAttenuation:true,transparent:true,opacity:0.9,depthWrite:false,color,blending:THREE.AdditiveBlending})
  const pts=new THREE.Points(pg,pm);scene.add(pts);bridgeMeshes.push(pts)
  bridgeParticles.push({points:pts,curve:cv,offsets:ofs,src,tgt,yArc,dir,speed})
}

function createBridge(pA:THREE.Vector3,pB:THREE.Vector3,b:BridgeData){
  const isFx = b.kind === 'fx'
  const pal = BRIDGE_PALETTES[isFx ? 'fx' : 'federation']
  const yArc = pal.yArc
  const mid=new THREE.Vector3().lerpVectors(pA,pB,0.5);mid.y+=yArc
  const cv=new THREE.CatmullRomCurve3([pA.clone(),mid,pB.clone()])

  // Core line — FX brighter + flagged to PULSE in the animate loop.
  const lg=new THREE.BufferGeometry().setFromPoints(cv.getPoints(120))
  const lm=new THREE.LineBasicMaterial({color:pal.core,transparent:true,opacity:isFx?0.9:0.6,blending:THREE.AdditiveBlending})
  const line=new THREE.Line(lg,lm);line.userData={curve:cv,baseOp:isFx?0.9:0.6,pulse:isFx}
  scene.add(line);bridgeMeshes.push(line);bridgeLines.push(line)

  // Glow line — FX gets a wider, stronger halo (+pulse).
  const glowGeo=new THREE.BufferGeometry().setFromPoints(cv.getPoints(120))  // 120 (not 80) to match the animate-loop setFromPoints(120) — an undersized buffer here spammed "Buffer size too small for points data"
  const glowMat=new THREE.LineBasicMaterial({color:pal.glow,transparent:true,opacity:isFx?0.32:0.15,linewidth:isFx?3:2,blending:THREE.AdditiveBlending})
  const glowLine=new THREE.Line(glowGeo,glowMat);glowLine.userData={curve:cv,baseOp:isFx?0.32:0.15,pulse:isFx}
  scene.add(glowLine);bridgeMeshes.push(glowLine);bridgeLines.push(glowLine)

  if (isFx) {
    // Cross-currency SWAP corridor → two counter-flowing streams in the two
    // currencies' accents (cyan out, warm-gold back), larger + faster = it reads
    // as a live exchange, distinct from the one-way gold federation beam.
    _addBridgeStream(cv, BRIDGE_PALETTES.fx.core, 3.6, +1, 0.20, b.sourceFrameId, b.targetFrameId, yArc)
    _addBridgeStream(cv, 0xffe09a,                2.9, -1, 0.16, b.sourceFrameId, b.targetFrameId, yArc)
  } else {
    _addBridgeStream(cv, pal.core, 2, +1, 0.10, b.sourceFrameId, b.targetFrameId, yArc)
  }
}

// ─── Animate ────────────────────────────────────────────────────
let elapsed = 0
function animate() {
  animationId = requestAnimationFrame(animate)
  const dt = clock.getDelta(); elapsed += dt
  // UNIVERSE-CINEMA: drive the shared shimmer clocks — star twinkle + film grain.
  // Frozen under reduced-motion (clocks simply never advance → no shimmer).
  if (!REDUCED_MOTION) { twinkleTime.value = elapsed; if (filmPass) filmPass.uniforms.uTime.value = elapsed }

  // Galaxy self-rotation
  for(const[,g]of galaxyGroups)g.rotation.y+=0.0006

  // Galaxy orbital dance — N galaxies waltz, equidistant on a shared ring.
  // (Was hard-wired to galaxyArr[0]/[1] only, leaving a 3rd galaxy — Frame C —
  //  stranded at its static build position. Now every galaxy orbits.)
  const galaxyArr = Array.from(galaxyGroups.values())
  const N = galaxyArr.length
  if (N >= 2) {
    galaxyOrbitAngle += 0.00012 * dt * 60  // Slow majestic orbit

    // Ring radius that keeps ADJACENT galaxy centers ~GAL_SEP apart for any N
    // (chord = 2·R·sin(π/N) = GAL_SEP). N=2 → R=70 (byte-identical to the old
    // opposite-sides waltz); N=3 → R≈81 (equilateral triangle, side GAL_SEP).
    galaxyOrbitRadius = GAL_SEP / (2 * Math.sin(Math.PI / N))

    // Orbit center drifts toward the backdrop black hole (glacial, endless).
    if (blackHoleGroup) {
      orbitCenter.lerp(blackHoleGroup.position, 0.000003)
      if (orbitCenter.distanceTo(blackHoleGroup.position) < 30) orbitCenter.set(0, 0, 0)
    }

    // Place every galaxy on the ring, equidistant.
    for (let i = 0; i < N; i++) {
      const a = galaxyOrbitAngle + (i / N) * Math.PI * 2
      galaxyArr[i].position.set(
        orbitCenter.x + Math.cos(a) * galaxyOrbitRadius,
        orbitCenter.y,
        orbitCenter.z + Math.sin(a) * galaxyOrbitRadius
      )
    }

    // Update each bridge curve from its OWN endpoints (keyed by frame id), so
    // multiple beams between distinct pairs (e.g. federation + fx on A↔C) track
    // correctly instead of all collapsing onto the 0↔1 axis.
    for (const bp of bridgeParticles) {
      const a = galaxyGroups.get(bp.src)?.position, b = galaxyGroups.get(bp.tgt)?.position
      if (!a || !b) continue
      bp.curve.points[0].copy(a); bp.curve.points[2].copy(b)
      const mid = new THREE.Vector3().lerpVectors(a, b, 0.5); mid.y += bp.yArc
      bp.curve.points[1].copy(mid); bp.curve.updateArcLengths()
    }
    // Re-extract line geometry from the (shared) curves.
    for (const bl of bridgeLines) {
      const cv = bl.userData.curve as THREE.CatmullRomCurve3
      if (cv) bl.geometry.setFromPoints(cv.getPoints(120))
    }

    // Camera target gently follows orbit center
    controls.target.lerp(orbitCenter, 0.005)
  }

  // Planet self-rotation
  for(const pc of planetCores)pc.rotation.y+=0.002

  // Agent orbital motion
  for(const orb of allAgentOrbits){
    orb.angle += orb.speed * dt
    const px = orb.center.x + orb.radius * Math.cos(orb.angle)
    const py = orb.center.y + orb.yOffset + orb.radius * Math.sin(orb.inclination) * Math.sin(orb.angle)
    const pz = orb.center.z + orb.radius * Math.sin(orb.angle) * Math.cos(orb.inclination)

    // Update InstancedMesh — HIGH-4: O(1) lookup via stamped agentDataIdx
    // (was O(n) indexOf). HIGH-3: reuse hoisted dummy instead of new alloc.
    const im = agentInstanceMeshes.get(orb.galaxyId)
    if(im){
      const agent = allAgentData[orb.agentDataIdx]
      let sz = agent ? getAgentSize(agent.liquidBalance, agent.stakedBalance) : 0.6
      // Search match → swell + pulse so it's instantly spottable (colour set white in applyFilter).
      if (_matchedDataIdx.has(orb.agentDataIdx)) sz *= 2.6 + Math.sin(elapsed * 5) * 0.7
      _animDummy.position.set(px,py,pz); _animDummy.scale.setScalar(sz); _animDummy.updateMatrix()
      im.setMatrixAt(orb.agentIdx, _animDummy.matrix)
      im.instanceMatrix.needsUpdate = true
    }

    // Update glow layer
    const gl = agentGlowLayers.get(orb.galaxyId)
    if(gl){const pa=gl.geometry.getAttribute('position') as THREE.BufferAttribute;pa.setXYZ(orb.agentIdx,px,py,pz);pa.needsUpdate=true}
  }

  // Agent label follow (update position to match orbit)
  for(const lbl of agentLabelSprites){
    const oi = lbl.userData.agentOrbitIdx
    if(oi !== undefined && allAgentOrbits[oi]){
      const orb = allAgentOrbits[oi]
      const px = orb.center.x + orb.radius * Math.cos(orb.angle)
      const py = orb.center.y + orb.yOffset + orb.radius * Math.sin(orb.inclination) * Math.sin(orb.angle)
      const pz = orb.center.z + orb.radius * Math.sin(orb.angle) * Math.cos(orb.inclination)
      const agent = allAgentData[oi]
      const sz = agent ? getAgentSize(agent.liquidBalance, agent.stakedBalance) : 0.6
      lbl.position.set(px, py + sz + 1.2, pz)

      // Distance-based fade — MEDIUM-6: reuse hoisted Vec3 (was per-label alloc)
      const galGroup = galaxyGroups.get(orb.galaxyId)
      if(galGroup){
        lbl.getWorldPosition(_animTmpVec)
        const dist = camera.position.distanceTo(_animTmpVec)
        const fade = Math.max(0, Math.min(1, 1 - (dist - 60) / 40))
        ;(lbl.material as THREE.SpriteMaterial).opacity = fade
      }
    }
  }

  // Bridge particles — per-stream direction + speed (FX counter-flows = swap).
  for(const bp of bridgeParticles){const pa=bp.points.geometry.getAttribute('position') as THREE.BufferAttribute;for(let i=0;i<bp.offsets.length;i++){bp.offsets[i]=(bp.offsets[i]+dt*bp.speed*bp.dir+1)%1;const pt=bp.curve.getPointAt(bp.offsets[i]);pa.setXYZ(i,pt.x,pt.y,pt.z)};pa.needsUpdate=true}

  // FX beam pulse — flagged lines breathe (composed with the active dim factor so
  // search/filter dim still applies). Federation beams (no pulse flag) untouched.
  for(const bl of bridgeLines){const u:any=bl.userData;if(u.pulse){(bl.material as THREE.LineBasicMaterial).opacity=(u.baseOp||0.6)*_bridgeDimFactor*(0.55+0.45*Math.sin(elapsed*2.4))}}

  // Bridge pulsing
  for(const t of bridgeTubes)(t.material as THREE.MeshBasicMaterial).opacity=0.25+Math.sin(elapsed*1.5)*0.08

  // Corona pulsing
  for(const c of coronaSprites){const base=c.scale.x;const pulse=1+Math.sin(elapsed*0.8+c.position.x*0.1)*0.05;c.scale.setScalar(base*pulse/(1+Math.sin((elapsed-0.016)*0.8+c.position.x*0.1)*0.05))}

  // Black hole accretion disk rotation — iterate every BH (backdrop + per-frame).
  // Kepler: inner orbits faster, speed ~ 1/r^0.8 (tuned for readability).
  for (const bh of blackHoles) {
    const pa = bh.diskPoints.geometry.getAttribute('position') as THREE.BufferAttribute
    const rs = bh.eventHorizonRadius  // Schwarzschild radius proxy
    for (let i = 0; i < bh.diskOffsets.length; i++) {
      const nr = Math.sqrt(pa.getX(i) ** 2 + pa.getZ(i) ** 2) || rs * 1.5
      const speed = 0.4 / Math.pow(Math.max(nr - rs, rs * 0.25) / (rs * 1.25), 0.8)
      bh.diskOffsets[i] += speed * dt
      pa.setX(i, Math.cos(bh.diskOffsets[i]) * nr)
      pa.setZ(i, Math.sin(bh.diskOffsets[i]) * nr)
    }
    pa.needsUpdate = true
  }

  // Update lensing uniforms — project each BH to screen UV + apparent radius.
  if (lensingPass) {
    const u = lensingPass.uniforms
    const maxBh = Math.min(blackHoles.length, 3)
    u.uBhCount.value = maxBh
    const viewH = 2 * Math.tan((camera.fov * Math.PI / 180) / 2)  // view height in world units per distance
    for (let i = 0; i < maxBh; i++) {
      const bh = blackHoles[i]
      bh.group.getWorldPosition(_bhScratch)
      const dist = camera.position.distanceTo(_bhScratch)
      const projected = _bhScratch.clone().project(camera)
      const uv = u.uBhUv.value[i] as THREE.Vector2
      uv.set((projected.x + 1) * 0.5, (projected.y + 1) * 0.5)
      // Apparent radius in UV units: event-horizon radius / (view height at that distance).
      const apparentRs = bh.eventHorizonRadius / (dist * viewH * 0.5 + 0.001)
      u.uBhRs.value[i] = Math.max(0.0, Math.min(0.35, apparentRs))
      // Strength scales with apparent size — tiny BHs get subtle lensing, big ones dominate.
      u.uBhStrength.value[i] = Math.min(1.0, apparentRs * 6.0)
      // Kill lensing if the BH is behind the camera (z > 1 in NDC).
      if (projected.z > 1) { u.uBhRs.value[i] = 0; u.uBhStrength.value[i] = 0 }
    }
  }

  controls.update(); composer.render()
}

// ─── Interaction ────────────────────────────────────────────────
function onMouseMove(e: MouseEvent) {
  if(!containerRef.value)return
  const rect=containerRef.value.getBoundingClientRect()
  mouse.x=((e.clientX-rect.left)/rect.width)*2-1; mouse.y=-((e.clientY-rect.top)/rect.height)*2+1
  raycaster.setFromCamera(mouse,camera)

  // Check registries first (higher priority)
  const regMeshArr = Array.from(registryMeshes.values())
  const regHits = raycaster.intersectObjects(regMeshArr, true)
  for(const hit of regHits){
    // Walk up to find registry group
    let obj: THREE.Object3D | null = hit.object
    while(obj && !obj.userData?.registry) obj = obj.parent
    if(obj?.userData?.registry){
      const r = obj.userData.registry as FrameRegistry
      // Stash the FULL registry (carries RC visual/fees/card-sig) so the rich
      // RegistryHoverCard renders the AgentWorld-parity card; resolve settlement
      // currency (card's own, or viewer's for the local registry).
      const regCurrency = r.fees?.settlementCurrency || (r.isLocal || (r.hopDepth ?? 1) === 0 ? localCurrency.value : null)
      tooltipData.value = {type:'registry',name:r.name,frame:obj.userData.frameId,agentCount:r.agentCount,health:r.health,domain:r.domain,publicUrl:r.publicUrl,description:r.description,status:r.status||'ACTIVE',trustDomain:r.trustDomain,authMethods:r.authMethods,protocolVersion:r.protocolVersion,lastSyncedAt:r.lastSyncedAt,hopDepth:r.hopDepth,reg:{...r,displayName:(r as any).displayName??(r as any).display_name??null},currency:regCurrency}
      tooltipStyle.value=clampTip(e.clientX,e.clientY)
      tooltipVisible.value=true; document.body.style.cursor='pointer'; return
    }
  }

  // Check agents (InstancedMesh)
  for(const[gId,im]of agentInstanceMeshes){
    const hits = raycaster.intersectObject(im, false)
    if(hits.length>0){
      const idx = hits[0].instanceId
      if(idx !== undefined){
        // Find the agent data for this instance
        let agentIdx = -1
        for(let i=0;i<allAgentOrbits.length;i++){
          if(allAgentOrbits[i].galaxyId===gId && allAgentOrbits[i].agentIdx===idx){agentIdx=i;break}
        }
        if(agentIdx>=0 && allAgentData[agentIdx]){
          const a=allAgentData[agentIdx]
          tooltipData.value={type:'agent',name:a.name,did:a.did,description:a.description,reputation:a.reputation,reputationTier:a.reputationTier||'standard',totalTransactions:a.totalTransactions,liquidBalance:a.liquidBalance,stakedBalance:a.stakedBalance,capabilities:a.capabilities,isSynced:a.isSynced,originRegistry:a.originRegistry,spiffeId:a.spiffeId,mtlsEnabled:a.mtlsEnabled,frame:gId}
          tooltipStyle.value=clampTip(e.clientX,e.clientY)
          tooltipVisible.value=true; document.body.style.cursor='pointer'; return
        }
      }
    }
  }

  tooltipVisible.value=false; document.body.style.cursor='default'
}

function onClick(){
  raycaster.setFromCamera(mouse,camera)
  const regMeshArr = Array.from(registryMeshes.values())
  const regHits = raycaster.intersectObjects(regMeshArr, true)
  for(const hit of regHits){
    let obj: THREE.Object3D | null = hit.object
    while(obj && !obj.userData?.registry) obj = obj.parent
    if(obj?.userData?.registry){ emit('registry-click',obj.userData.registry,obj.userData.frameId); return }
  }
  for(const[gId,im]of agentInstanceMeshes){
    const hits=raycaster.intersectObject(im,false)
    if(hits.length>0 && hits[0].instanceId!==undefined){
      let ai=-1;for(let i=0;i<allAgentOrbits.length;i++){if(allAgentOrbits[i].galaxyId===gId&&allAgentOrbits[i].agentIdx===hits[0].instanceId){ai=i;break}}
      if(ai>=0&&allAgentData[ai])emit('agent-click',allAgentData[ai],gId)
    }
  }
}

function onResize(){if(!containerRef.value)return;const w=containerRef.value.clientWidth,h=containerRef.value.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);composer.setSize(w,h);if(lensingPass)lensingPass.uniforms.uAspect.value=w/h}

// ─── Search / Frame Filter (dim non-matches, highlight matches) ──────────────
// Reversible: each material's pre-filter opacity is stashed ONCE on userData so
// clearing the filter restores the exact original look. [Commander 2026-06-07]
function _dimObject(obj: THREE.Object3D, factor: number) {
  const dim = factor < 0.999
  obj.traverse((c: any) => {
    const mats = c.material ? (Array.isArray(c.material) ? c.material : [c.material]) : []
    for (const m of mats) {
      if (m.userData._baseOp === undefined) { m.userData._baseOp = (m.opacity ?? 1); m.userData._baseTr = !!m.transparent }
      const wantTr = dim ? true : m.userData._baseTr
      if (m.transparent !== wantTr) { m.transparent = wantTr; m.needsUpdate = true }  // flag flip needs recompile
      m.opacity = m.userData._baseOp * factor
    }
  })
}
function frameMatchesSearch(frameId: string, q: string): boolean {
  if (!q) return true
  const f = props.frames.find(fr => fr.id === frameId)
  if (!f) return false
  if (f.name.toLowerCase().includes(q)) return true
  if (f.registries.some(r => (r.name || '').toLowerCase().includes(q))) return true
  return f.agents.some(a => (a.name || '').toLowerCase().includes(q))
}
function applyFilter() {
  if (!scene) return
  const q = (props.searchQuery || '').trim().toLowerCase()
  const ff = props.frameFilter || 'all'
  const rf = props.registryFilter || 'all'
  // A selected registry focuses ITS galaxy (resolve which frame holds it).
  let rfFrame: string | null = null
  if (rf !== 'all') {
    const owner = props.frames.find(fr => fr.registries.some(r => r.id === rf))
    rfFrame = owner ? owner.id : '__none__'
  }
  const active = ff !== 'all' || rf !== 'all' || !!q
  // Galaxy dim (frame focus / registry focus / search non-match).
  for (const [fid, gg] of galaxyGroups) {
    let factor = 1
    if (ff !== 'all' && fid !== ff) factor = 0.1
    if (rfFrame && fid !== rfFrame) factor = Math.min(factor, 0.1)
    if (q && !frameMatchesSearch(fid, q)) factor = Math.min(factor, 0.1)
    _dimObject(gg, factor)
  }

  // Search-match agents → record indices (animate swells + pulses them) and paint
  // them WHITE so they shine; everyone else keeps their tier colour.
  _matchedDataIdx = new Set<number>()
  if (q) for (let i = 0; i < allAgentData.length; i++) {
    if ((allAgentData[i]?.name || '').toLowerCase().includes(q)) _matchedDataIdx.add(i)
  }
  for (const orb of allAgentOrbits) {
    const im = agentInstanceMeshes.get(orb.galaxyId); if (!im) continue
    const a = allAgentData[orb.agentDataIdx]; if (!a) continue
    im.setColorAt(orb.agentIdx, _matchedDataIdx.has(orb.agentDataIdx) ? SEARCH_HL : getAgentColor(a.reputation, a.isSynced))
  }
  for (const [, im] of agentInstanceMeshes) if (im.instanceColor) im.instanceColor.needsUpdate = true

  // Beams fade while a filter is engaged (FX pulse lines composed in animate via _bridgeDimFactor).
  _bridgeDimFactor = active ? 0.22 : 1
  for (const b of bridgeMeshes) {
    if ((b as any).userData?.pulse) continue
    const m: any = (b as any).material
    if (!m) continue
    if (m.userData._baseOp === undefined) m.userData._baseOp = (m.opacity ?? 1)
    m.transparent = true
    m.opacity = m.userData._baseOp * _bridgeDimFactor
  }

  // Auto-rotate: pause while searching/filtering (Commander: it was dizzying mid-search).
  // Resume ONLY if the user never grabbed the camera.
  if (controls) controls.autoRotate = active ? false : !_userMoved
}
watch(() => [props.searchQuery, props.frameFilter, props.registryFilter], () => applyFilter())

onMounted(()=>{initScene();buildScene();animate()})
onUnmounted(()=>{cancelAnimationFrame(animationId);window.removeEventListener('resize',onResize);renderer?.domElement?.removeEventListener('mousemove',onMouseMove);renderer?.domElement?.removeEventListener('click',onClick);controls?.dispose();renderer?.dispose();document.body.style.cursor='default'})
watch(()=>[props.frames,props.bridges],()=>{if(scene)buildScene()},{deep:true})
</script>

<template>
  <div ref="containerRef" class="universe-canvas">
    <!-- Registry hover → rich AgentWorld-parity card (own chrome; chrome-less wrapper) -->
    <div v-if="tooltipVisible && tooltipData?.type === 'registry' && tooltipData.reg" class="gtt-bare" :style="tooltipStyle">
      <RegistryHoverCard :registry="tooltipData.reg" :currency="tooltipData.currency" />
    </div>
    <!-- Agent hover → shared label -->
    <div v-else-if="tooltipVisible && tooltipData" class="gtt" :style="tooltipStyle">
      <TopologyHoverLabel v-if="labelEntity" :entity="labelEntity" :local-currency="localCurrency" />
    </div>
  </div>
</template>

<style scoped>
.universe-canvas{width:100%;height:100%;position:relative;overflow:hidden;background:#020206;cursor:grab}
.universe-canvas:active{cursor:grabbing}
/* ── AAA Tooltip (ported from GalacticMap) ── */
.gtt{position:fixed;pointer-events:none;z-index:100;background:rgba(8,10,20,0.92);backdrop-filter:blur(12px);border:1px solid rgba(100,140,255,0.2);border-radius:10px;padding:10px 14px;min-width:200px;max-width:340px;box-shadow:0 8px 32px rgba(0,0,0,0.5),0 0 20px rgba(50,100,255,0.08);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
/* Registry hover wrapper — chrome-less; RegistryHoverCard provides its own card chrome. */
.gtt-bare{position:fixed;pointer-events:none;z-index:100}
.gtt-header{display:flex;align-items:center;gap:8px;margin-bottom:4px}
.gtt-dot{font-size:14px}.gtt-dot.agent{color:#4fc3f7}.gtt-dot.registry{color:#00e676}
.gtt-name{font-weight:600;font-size:13px;color:#e8eaf6;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px}
.gtt-badge{display:inline-block;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.5px;margin-left:auto}
.gtt-badge.synced{background:rgba(255,171,64,0.2);border:1px solid rgba(255,171,64,0.5);color:#ffab40}
.gtt-badge.mtls{background:rgba(0,229,255,0.15);border:1px solid rgba(0,229,255,0.4);color:var(--nc-primary-bright)}
.gtt-badge.status.active{background:rgba(0,230,118,0.15);border:1px solid rgba(0,230,118,0.4);color:#00e676}
.gtt-badge.status.inactive{background:rgba(120,144,156,0.15);border:1px solid rgba(120,144,156,0.4);color:#78909c}
.gtt-did{font-size:10px;color:#7986cb;font-family:'SF Mono','Fira Code',monospace;margin-bottom:6px}
.gtt-desc{font-size:11px;color:#90a4ae;margin-bottom:6px;line-height:1.4}
.gtt-stats{display:flex;gap:16px;margin-bottom:4px}
.gtt-stat{display:flex;flex-direction:column;gap:1px}
.gtt-sl{font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#78909c}
.gtt-sv{font-size:13px;font-weight:700;color:#e0e0e0}
.gtt-sv.elite{color:#ffd700}.gtt-sv.great{color:var(--nc-primary-bright)}.gtt-sv.good{color:#4fc3f7}
.gtt-sv.trusted{color:var(--nc-primary-bright)}.gtt-sv.standard{color:#90a4ae}.gtt-sv.low{color:#78909c}
.gtt-sv.healthy{color:#00e676}.gtt-sv.warn{color:#ffb300}.gtt-sv.critical{color:#ff5252}
.gtt-sv.staked{color:#ab47bc}
.gtt-caps{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
.gtt-cap{padding:1px 6px;background:rgba(100,140,255,0.1);border:1px solid rgba(100,140,255,0.2);border-radius:3px;font-size:9px;color:#90caf9}
.gtt-auth{display:flex;align-items:center;gap:6px;margin:4px 0}
.gtt-spiffe{margin-top:4px;padding-top:4px;border-top:1px solid rgba(100,140,255,0.1)}
.gtt-origin{margin-top:2px}
.gtt-mono{font-size:10px;color:#90a4ae;font-family:'SF Mono','Fira Code',monospace;margin-left:4px}
.gtt-hop{margin-top:6px;padding-top:5px;border-top:1px solid rgba(100,140,255,0.1)}
.gtt-hop-badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.5px}
.gtt-hop-badge.hop-0{background:rgba(0,230,118,0.15);border:1px solid rgba(0,230,118,0.4);color:#00e676}
.gtt-hop-badge.hop-1{background:rgba(0,229,255,0.15);border:1px solid rgba(0,229,255,0.4);color:var(--nc-primary-bright)}
.gtt-hop-badge.hop-2{background:rgba(255,193,7,0.15);border:1px solid rgba(255,193,7,0.4);color:#ffc107}
.gtt-hop-badge.hop-3{background:rgba(255,152,0,0.15);border:1px solid rgba(255,152,0,0.4);color:#ff9800}
.gtt-hop-badge.hop-4{background:rgba(244,67,54,0.15);border:1px solid rgba(244,67,54,0.4);color:#f44336}
</style>
