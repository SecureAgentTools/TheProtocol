<script setup lang="ts">
/**
 * UniverseView.vue — Federation of Networks
 *
 * Page wrapper for the Universe visualization. Fetches topology data,
 * groups registries into frames, and passes structured data to UniverseCanvas.
 */
import { ref, computed, onMounted } from 'vue'
import { useFederationStore } from '@/stores/federation'
import { useAgentStore } from '@/stores/agents'
import { useTopologyDiscovery } from '@/composables/useTopologyDiscovery'
import { buildPopulationIndex, type PopulationIndex } from '@/utils/registryPopulation'  // §GLOBEPOP — true per-registry totals
import { useFrameAttribution } from '@/composables/useFrameAttribution'
import { useVRelativeHops, normName } from '@/composables/useVRelativeHops'
import { FRAMES, frameByTrustDomain } from '@/config/frames'
import { apiClient } from '@/services/api/client'
import UniverseCanvas from '@/components/UniverseCanvas.vue'
// SAME filter the Galactic Map uses — identical optics (Commander 2026-06-07).
// View-toggle hidden via :show-view-modes="false" (Universe is 3D-only).
import GalacticControls from '@/components/GalacticControls.vue'
import type { FrameData, FrameRegistry, FrameAgent, BridgeData } from '@/components/UniverseCanvas.vue'
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import SovereignRegistryCard from '@/components/SovereignRegistryCard.vue'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
import { useLogger } from '@/composables/useLogger'
import { useViewport } from '@/composables/useViewport'

// 2026-05-08 P3.2: useLogger no-ops in production for info/warn/debug.
const log = useLogger('Universe')
const viewport = useViewport()

// Legend collapse state (2026-05-08 mobile pass follow-up).
// Persisted across visits — `null` value = "use breakpoint default":
// open on desktop, closed on mobile so the cosmic visualization isn't
// blocked. Once the user explicitly toggles, their choice sticks.
const LEGEND_KEY = 'theprotocol:universe:legendOpen'
const legendOpenStored = ref<boolean | null>(((): boolean | null => {
  try {
    const v = localStorage.getItem(LEGEND_KEY)
    if (v === '1') return true
    if (v === '0') return false
  } catch { /* SSR/private mode — fall through */ }
  return null
})())
const legendOpen = computed(() => {
  if (legendOpenStored.value !== null) return legendOpenStored.value
  // Default: open on desktop, collapsed on mobile (legend covers most of
  // a phone viewport when expanded).
  return !viewport.isMobile.value
})
function toggleLegend() {
  const next = !legendOpen.value
  legendOpenStored.value = next
  try { localStorage.setItem(LEGEND_KEY, next ? '1' : '0') } catch { /* non-fatal */ }
}

const federationStore = useFederationStore()
const agentStore = useAgentStore()

// Click-to-open detail surfaces (parity with AgentWorld). Registry orb → full
// Registry Card modal; agent orb → Agent detail modal. Previously both clicks
// were dead log-only stubs.
const showAgentModal = ref(false)
const selectedAgentDid = ref('')
const showRegCard = ref(false)
const regCardPeer = ref<string | null>(null)
const regCardFallback = ref<string | null>(null)
const { topology, discoverTopology, domainKey, edgeKey } = useTopologyDiscovery()
// §GLOBEPOP — /agents/locations/ serves a fair per-registry SAMPLE plus true
// per-registry totals; entities are drawn from the sample, counts labeled true.
let popIndex: PopulationIndex = buildPopulationIndex(null)
const truePopulation = ref(0)
const { ensureLocalFrame, classifyByTrustDomain, localTrustDomain } = useFrameAttribution()
// V-relative hop (same tree as the Galactic Map) for the on-hover RegistryHoverCard —
// the only place hop is shown on this view. [Commander 2026-06-07]
const { hopByName: vrHopByName, refresh: vrRefresh } = useVRelativeHops()

const loading = ref(true)
const loadStatus = ref('Initializing multiverse…')
const frames = ref<FrameData[]>([])
const bridges = ref<BridgeData[]>([])
let localRegistryName = 'This Registry'

// Stats
const totalFrames = computed(() => frames.value.length)
const totalRegistries = computed(() => frames.value.reduce((n, f) => n + f.registries.length, 0))
// §GLOBEPOP: the header shows the TRUE network population when the aggregates
// are loaded; the drawn-entity sum is the fallback (old behavior).
const totalAgents = computed(() => truePopulation.value > 0 ? truePopulation.value : frames.value.reduce((n, f) => n + f.agents.length, 0))
const bridgeActive = computed(() => bridges.value.length > 0)

// ─── Galactic-Map-identical search / filter (drives the canvas dim/highlight) ─
// Reuses the SAME GalacticControls component (view-toggle hidden). State mirrors
// GalacticMap; selection is mapped → canvas frame/registry dim filters below.
const searchQuery = ref('')
const selectedFrame = ref<string>('all')        // 'all' | 'local' | <frame name>
const selectedRegistry = ref<string>('all')     // 'all' | <registry id/domain>
const sortBy = ref<string>('reputation')        // parity (3D has no list to sort)
const selectedCapabilities = ref<string[]>([])

const availableFrames = computed<string[]>(() => frames.value.map(f => f.name))
const registryOptions = computed(() => {
  const opts = [{ value: 'all', label: 'All Registries' }]
  for (const f of frames.value) for (const r of f.registries) opts.push({ value: r.id, label: r.name })
  return opts
})
const sortOptions = [
  { value: 'reputation', label: 'Reputation' },
  { value: 'name', label: 'Name' },
  { value: 'agents', label: 'Most Agents' },
]
const availableCapabilities = computed<string[]>(() => {
  const s = new Set<string>()
  for (const f of frames.value) for (const a of f.agents) for (const c of (a.capabilities || [])) if (c) s.add(c)
  return Array.from(s).sort().slice(0, 60)
})

// Map the bar's frame/registry selection → the canvas dim filters.
const localFrameId = computed(() => frames.value.find(f => f.registries.some(r => r.id === '__local__'))?.id || localFrameKey())
const canvasFrameFilter = computed(() => {
  const v = selectedFrame.value
  if (v === 'all') return 'all'
  if (v === 'local') return localFrameId.value
  return frames.value.find(f => f.name === v)?.id || 'all'
})
const canvasRegistryFilter = computed(() => selectedRegistry.value)

// "N shown" (registries + agents passing frame/registry/search) — bar prop.
const shownCount = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const ff = canvasFrameFilter.value
  const rf = selectedRegistry.value
  let n = 0
  for (const f of frames.value) {
    if (ff !== 'all' && f.id !== ff) continue
    const frameHit = !q || f.name.toLowerCase().includes(q)
    for (const r of f.registries) {
      if (rf !== 'all' && r.id !== rf) continue
      if (frameHit || (r.name || '').toLowerCase().includes(q)) n++
    }
    for (const a of f.agents) {
      if (rf !== 'all' && a.registryId !== rf) continue
      if (frameHit || (a.name || '').toLowerCase().includes(q)) n++
    }
  }
  return n
})

// ─── Legend (data-driven over the frames actually present) ──────────────────
// Frame dot + black-hole swatch follow the canvas palette ORDER
// (UniverseCanvas GAL_PALETTES = red / cyan / gold by frame index).
const LEGEND_FRAME_HEX = ['#ff3322', '#44bbff', '#ffb43a']
const LEGEND_BH = [
  { cls: 'uv-bh-amber', label: 'Amber' },
  { cls: 'uv-bh-azure', label: 'Azure' },
  { cls: 'uv-bh-gold',  label: 'Gold' },
]
const legendFrames = computed(() => frames.value.map((f, i) => ({
  name: f.name,
  hex: LEGEND_FRAME_HEX[i % LEGEND_FRAME_HEX.length],
  bh: LEGEND_BH[i % LEGEND_BH.length],
})))
// Hop-depth colour ramp — mirrors RegistryHoverCard HOP_DEPTH_COLORS, the only
// place hop is shown on this view (the on-hover card).
const HOP_RAMP = [
  { hop: 0, color: '#00e676' }, { hop: 1, color: '#5c9cf5' }, { hop: 2, color: '#00bcd4' },
  { hop: 3, color: '#ff9800' }, { hop: 4, color: '#e91e63' }, { hop: 5, color: '#d50000' },
]
const showFxLegend = computed(() => bridges.value.some(b => (b as any).kind === 'fx'))

// ─── Data Fetching ──────────────────────────────────────────────
async function loadData() {
  loading.value = true
  loadStatus.value = 'Resolving sovereign trust domains…'

  try {
    // Resolve our own trust_domain in parallel with topology fetch — used
    // by classifyFrame() below. Fail-soft: if /federation/info errors,
    // localTrustDomain stays null and classifyFrame falls back to Frame A.
    await ensureLocalFrame()

    // Fetch local registry name
    try {
      const infoResp = await apiClient.get('/federation/info')
      const regName = infoResp.data?.registry_name
      if (regName) localRegistryName = regName.replace(/-/g, ' ')
    } catch {}

    // Fetch agents from BOTH sources + federation peers in parallel.
    //   /agents/locations/  — PRIMARY. DISTINCT ON did at DB layer, 2000 cap,
    //                         reaches every operator evenly. Same endpoint
    //                         AgentWorld and Galactic Map use post-overhaul.
    //   /agent-cards/       — SECONDARY fallback for card_data (SPIFFE slug,
    //                         capabilities, balances) plus any DID missed
    //                         by locations.
    let locationsData: any[] = []
    loadStatus.value = 'Crawling federation topology…'
    await Promise.all([
      agentStore.fetchAllForMap(),
      federationStore.fetchRegistries(),
      vrRefresh(),
      (async () => {
        try {
          const locResp = await apiClient.get('/agents/locations/')
          locationsData = (locResp.data as any)?.locations || []
          popIndex = buildPopulationIndex((locResp.data as any)?.registries)
          truePopulation.value = popIndex.totalPopulation
        } catch (locErr) {
          log.warn('/agents/locations/ fetch failed:', locErr)
        }
      })(),
    ])

    // Pre-seed topology from backend BFS (server-side, all registries instantly)
    try {
      const trustedResp = await apiClient.get('/agents/locations/trusted-registries')
      const trustedRegs: any[] = trustedResp.data?.registries || []
      for (const tr of trustedRegs) {
        const pub = tr.public_url || ''
        if (!pub || !tr.name) continue
        const dk = domainKey(pub)
        if (!topology.registries.has(dk) && dk !== '__local__') {
          topology.registries.set(dk, { name: tr.name, publicUrl: pub, domain: dk, hopDepth: tr.hop || 2 })
        }
      }
    } catch {}

    // BFS topology discovery (maxHops=6 for full depth, edges for bridge rendering)
    loadStatus.value = 'Charting agent constellations…'
    await discoverTopology(federationStore.registries, localRegistryName, 6)

    // Deduplicate: remove ghost entries that are the LOCAL registry discovered via peers
    const localDomains = new Set<string>()
    const browserDomain = domainKey(window.location.origin)
    if (browserDomain) localDomains.add(browserDomain)
    // The Frame-A aliases are the local ghost ONLY when WE are Frame A. From any
    // other frame (doha, frame-b, …) api/registry.theprotocol.cloud IS Registry-A —
    // a real foreign peer that MUST render. (Hardcoding them deleted Registry-A — and
    // any agent whose origin is Registry-A, e.g. Sybil — everywhere off-Frame-A.)
    if ((localTrustDomain.value || '').toLowerCase() === 'agentvault.com') {
      localDomains.add('api.theprotocol.cloud')
      localDomains.add('registry.theprotocol.cloud')
    }
    for (const ld of localDomains) {
      if (topology.registries.has(ld)) {
        topology.registries.delete(ld)
        log.debug(`Dedup: removed ghost local registry '${ld}'`)
      }
    }

    // Group registries by frame
    const frameMap = new Map<string, { registries: FrameRegistry[]; agents: FrameAgent[] }>()

    // Classify each discovered registry into a frame.
    // trust_domain comes from the backend topology response post-Tier-1A.
    for (const [domain, reg] of topology.registries) {
      const frameId = classifyFrame(domain, reg.name, (reg as any).trust_domain)
      if (!frameMap.has(frameId)) {
        frameMap.set(frameId, { registries: [], agents: [] })
      }
      // Registry Card v0.3/0.4 — carry the peer's visual + fees + card-signature
      // slice (from /public/topology) so the rich RegistryHoverCard (AgentWorld
      // parity) renders avatar/flare + currency + fee rail + signature on hover.
      const rcVisual = (reg as any).visual
      const rcFees = (reg as any).fees_summary
      frameMap.get(frameId)!.registries.push({
        id: domain,
        name: reg.name,
        domain: domain,
        agentCount: 0,
        health: 100,
        isLocal: domain === '__local__',
        hopDepth: vrHopByName.value.get(normName(reg.name)) ?? reg.hopDepth ?? 0,
        publicUrl: (reg as any).publicUrl,
        description: (reg as any).description || (domain === '__local__'
          ? 'Primary sovereign registry — home of locally registered agents'
          : `Discovered via topology — ${reg.hopDepth ?? 0}-hop relay`),
        status: 'active',
        trustDomain: (reg as any).trust_domain,
        protocolVersion: '1.0',
        authMethods: ['mtls', 'jwt_svid'],
        // the palette: the viewer's own frame wears the home colours, every other frame the sovereign ones (§FEFRAME W4;
        // a name test made EU and ASIA both 'A' and only the retired frame-b 'B')
        frame: frameId === localFrameKey() ? 'A' : 'B',
        displayName: (reg as any).display_name ?? null,  // §2026-06-14 card display name (UI label)
        visual: rcVisual ? {
          iconUrl: rcVisual.icon_url, orbColor: rcVisual.orb_color, orbGlowColor: rcVisual.orb_glow_color,
          sovereignVariant: rcVisual.sovereign_variant, flareEncirclementVariant: rcVisual.flare_encirclement_variant,
          flareEncirclementOverlay: rcVisual.flare_encirclement_overlay,
        } : null,
        fees: rcFees ? {
          intraRegistry: rcFees.intra_registry, crossRegistry: rcFees.cross_registry,
          hostingEnabled: rcFees.hosting_enabled, hostingRate: rcFees.hosting_rate,
          settlementCurrency: rcFees.settlement_currency,
        } : null,
        exchange: (reg as any).exchange ?? null,
        cardEtag: (reg as any).card_etag || null,
        cardSignatureVerified: !!(reg as any).card_signature_verified,
      })
    }

    // Agent assignment — PRIMARY pass: iterate /agents/locations/ entries.
    // Each location row carries did + origin_registry (already deduped per
    // DID at the backend via DISTINCT ON). Match origin → registry → frame.
    //
    // Secondary pass: iterate agentStore.agents to backfill card_data-rich
    // entries (capabilities, SPIFFE slug, balances) for any DID we haven't
    // already seen. Dedup by DID + (name, origin) so cards with null top-
    // level DID don't double-count agents already represented via locations.
    const seenDids = new Set<string>()
    const seenNameOrigin = new Set<string>()
    const nameOriginKey = (n: string, o: string) =>
      `${(n || '').toLowerCase().trim()}::${(o || 'local').toLowerCase().trim()}`

    // Build name→{frameId, registryId} lookup from registries, so we can
    // resolve an origin string to its frame+registry without re-walking the map.
    const originResolver = new Map<string, { frameId: string; registryId: string }>()
    for (const [frameId, data] of frameMap) {
      for (const reg of data.registries) {
        originResolver.set((reg.name || '').toLowerCase().trim(), { frameId, registryId: reg.id })
      }
    }

    // PRIMARY: locations
    for (const loc of locationsData) {
      if (!loc || !loc.did || !loc.name) continue
      if (seenDids.has(loc.did)) continue

      const origin: string = (loc.origin_registry || '').trim()
      const isFederated = !!origin && origin.toLowerCase() !== 'local'

      let frameId: string
      let registryId: string

      if (!isFederated) {
        // Local agent — lives on this registry's own frame galaxy, the same key `classifyFrame('__local__')` gave the
        // local registry (§FEFRAME W4: a hardcoded 'frame-a' dropped every local agent on EU, ASIA and the sandbox)
        frameId = localFrameKey()
        registryId = '__local__'
      } else {
        const match = originResolver.get(origin.toLowerCase())
        if (!match) continue  // Legacy/defunct origin — skip (matches AgentWorld/GM behavior)
        frameId = match.frameId
        registryId = match.registryId
      }

      if (!frameMap.has(frameId)) continue
      seenDids.add(loc.did)
      seenNameOrigin.add(nameOriginKey(loc.name, origin))

      const rep = Number((loc as any).reputation) || 0
      frameMap.get(frameId)!.agents.push({
        did: loc.did,
        name: loc.name,
        registryId,
        reputation: rep,
        status: (loc.status === 'inactive' || loc.status === 'revoked') ? 'inactive' : 'active',
        isSynced: isFederated,
        liquidBalance: 0,
        stakedBalance: 0,
        description: '',
        capabilities: [],
        reputationTier: rep >= 95 ? 'elite' : rep >= 80 ? 'great' : rep >= 60 ? 'good' : 'standard',
        totalTransactions: 0,
        originRegistry: origin,
        spiffeId: '',
        mtlsEnabled: false,
      })
      const reg = frameMap.get(frameId)!.registries.find(r => r.id === registryId)
      if (reg) reg.agentCount++
    }

    // SECONDARY: agentStore.agents — backfill card_data-rich entries for
    // anything not already covered. Same SPIFFE matching as before.
    const storeAgents = agentStore.agents || []
    for (const agent of storeAgents) {
      if (agent.did && seenDids.has(agent.did)) continue
      const cardData = agent.card_data || {}
      const fMeta = cardData.federation_metadata || {}
      const sourceRegistry = fMeta.source_registry || ''
      const originName: string = fMeta.origin_registry_name || ''
      const nk = nameOriginKey(agent.name, originName || 'local')
      if (seenNameOrigin.has(nk)) continue

      let assignedFrame: string | null = null
      let assignedRegistryId: string | null = null

      const slug = extractSlugFromSpiffe(sourceRegistry)
      if (slug) {
        for (const [frameId, data] of frameMap) {
          for (const reg of data.registries) {
            const regSlug = slugify(reg.name)
            if (slug === regSlug || regSlug.startsWith(slug) || slug.startsWith(regSlug)) {
              assignedFrame = frameId
              assignedRegistryId = reg.id
              break
            }
          }
          if (assignedFrame) break
        }
      }

      if (!assignedFrame && originName) {
        const match = originResolver.get(originName.toLowerCase().trim())
        if (match) {
          assignedFrame = match.frameId
          assignedRegistryId = match.registryId
        }
      }

      // Federated agent we couldn't resolve to any live registry → skip
      // (legacy/defunct origin).
      if (!assignedFrame && (sourceRegistry || originName)) continue

      // Truly local (no federation hints) → this registry's own frame, local registry.
      if (!assignedFrame) {
        assignedFrame = localFrameKey()
        assignedRegistryId = '__local__'
      }

      if (!frameMap.has(assignedFrame)) continue
      if (agent.did) seenDids.add(agent.did)
      seenNameOrigin.add(nk)

      frameMap.get(assignedFrame)!.agents.push({
        did: agent.did || agent.agent_did || `agent-${agent.id}`,
        name: agent.name || 'Unknown',
        registryId: assignedRegistryId || '__local__',
        reputation: agent.reputation_score || 50,
        status: agent.is_active ? 'active' : 'inactive',
        isSynced: !!sourceRegistry || !!originName,
        liquidBalance: agent.liquid_balance || 0,
        stakedBalance: agent.staked_balance || 0,
        description: agent.description || cardData.description || '',
        capabilities: agent.capabilities || cardData.tags || [],
        reputationTier: agent.reputation_tier || (agent.reputation_score >= 95 ? 'elite' : agent.reputation_score >= 80 ? 'great' : agent.reputation_score >= 60 ? 'good' : 'standard'),
        totalTransactions: agent.total_transactions || 0,
        originRegistry: originName,
        spiffeId: fMeta.spiffe_id || '',
        mtlsEnabled: !!fMeta.mtls_enabled,
      })
      const reg = frameMap.get(assignedFrame)!.registries.find(r => r.id === assignedRegistryId)
      if (reg) reg.agentCount++
    }

    // §GLOBEPOP: label TRUE populations — the drawn entities are a fair sample.
    for (const f of frameMap.values()) {
      for (const reg of f.registries) {
        const pop = popIndex.lookup(reg.name, (reg as any).trustDomain)
        if (pop) reg.agentCount = Math.max(reg.agentCount, pop.total)
      }
    }

    // Build FrameData array
    const frameColors = [0xef8f00, 0x0099ff, 0x7e57c2, 0x43a047, 0xe53935]
    let colorIdx = 0
    const builtFrames: FrameData[] = []

    for (const [frameId, data] of frameMap) {
      if (data.registries.length === 0) continue
      builtFrames.push({
        id: frameId,
        name: getFrameName(frameId),
        trustDomain: frameId,
        registries: data.registries,
        agents: data.agents,
        color: frameColors[colorIdx % frameColors.length],
      })
      colorIdx++
    }

    frames.value = builtFrames

    // Build bridges (edges between frames). Look up trust_domain via the
    // topology map by domain so the bridge classifier matches the per-reg one.
    const builtBridges: BridgeData[] = []
    const frameIds = new Set(builtFrames.map(f => f.id))
    for (const edge of topology.edges) {
      const [domA, domB] = edge.split('::')
      const tdA = (topology.registries.get(domA) as any)?.trust_domain
      const tdB = (topology.registries.get(domB) as any)?.trust_domain
      const fA = classifyFrame(domA, '', tdA)
      const fB = classifyFrame(domB, '', tdB)
      if (fA !== fB && frameIds.has(fA) && frameIds.has(fB)) {
        const key = [fA, fB].sort().join('::')
        if (!builtBridges.some(b => [b.sourceFrameId, b.targetFrameId].sort().join('::') === key)) {
          builtBridges.push({ sourceFrameId: fA, targetFrameId: fB, syncedCards: 0, lastSyncAt: null, kind: 'federation' })
        }
      }
    }

    // FX corridor beams — drawn between the viewer's own frame (the hub) and each frame on a DIFFERENT settlement
    // currency. A separate cyan beam, arced opposite the gold federation beam, so a pair shows both; a frame on the
    // same currency gets no FX beam. [Commander 2026-06-07; §FEFRAME W4: the hub was 'frame-a', absent off Frame A]
    const fxHub = builtFrames.find(f => f.id === localFrameKey())
    if (fxHub) {
      const hubCcy = frameCurrency(fxHub)
      for (const f of builtFrames) {
        if (f.id === fxHub.id) continue
        if (frameCurrency(f) !== hubCcy) {
          builtBridges.push({ sourceFrameId: fxHub.id, targetFrameId: f.id, syncedCards: 0, lastSyncAt: null, kind: 'fx' })
        }
      }
    }
    bridges.value = builtBridges

  } catch (err) {
    console.error('[UniverseView] Failed to load data:', err)
  } finally {
    loading.value = false
  }
}

// ─── Frame Classification ───────────────────────────────────────
// 2026-05-05 audit HIGH-2 + Theme #1: previously this view duplicated
// frame-attribution logic via URL-substring matching (`d.includes('frame-b')`)
// and topology-edge probing — same pattern that produced today's earlier
// Bavaria-stacking and dedup bugs in AgentWorld. Backend now returns
// trust_domain on every registry entry (post-Tier-1A backend pass), so
// this function is now a one-liner over `useFrameAttribution()`.
//
// SPIFFE slug helpers retained because they're still used at line ~199 for
// matching agent cards back to their source registry by name.
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

// Frame-level settlement currency — used to detect cross-currency (FX) corridors.
// Prefer the card's own settlement currency; else the frame manifest by REAL trust_domain (§FEFRAME W2); else ''
// (unknown: never a guessed unit; the old fallbacks named the retired frames' AVT / BVT).
function frameCurrency(f: FrameData): string {
  for (const r of f.registries) {
    const c = (r as any).fees?.settlementCurrency
    if (c) return String(c).toUpperCase()
  }
  for (const r of f.registries) {
    const d = frameByTrustDomain(FRAMES, (r as any).trustDomain)
    if (d?.currency) return d.currency
  }
  return ''
}

// The viewer's OWN frame key, derived from its trust_domain — NOT hardcoded
// 'frame-a'. On a Frame-A mainframe this is 'frame-a'; on a Frame-C operator
// (doha) it's Frame C's key, so the local registry + its same-frame siblings form
// THEIR OWN galaxy instead of merging into Frame A (which also held agentvault.com).
// [Commander 2026-06-07]
function localFrameKey(): string {
  const ltd = (localTrustDomain.value || '').toLowerCase()
  if (!ltd) return 'frame-local'          // the trust domain is not known yet: this registry's own galaxy, unnamed
  const seeded = frameByTrustDomain(FRAMES, ltd)
  if (seeded) return `frame-${seeded.key.toLowerCase()}`
  return `frame-${slugify(ltd)}`
}

function classifyFrame(domain: string, _name: string, trust_domain?: string): string {
  // Local pseudo-domain → the VIEWER's own frame (was hardcoded 'frame-a', which
  // merged a non-Frame-A viewer's own frame into the Frame A galaxy).
  if (domain.toLowerCase() === '__local__') return localFrameKey()
  // Authoritative path: backend-supplied trust_domain.
  const cls = classifyByTrustDomain(trust_domain)
  // Same trust_domain as the viewer → the viewer's own frame galaxy.
  if (cls === 'local') return localFrameKey()
  // Fail-soft for entries missing trust_domain (pre-Tier-1A operators):
  // default to the local frame galaxy.
  if (cls === 'unknown') return localFrameKey()
  // Real non-local trust_domain → its OWN frame. Previously this collapsed
  // EVERY non-local td to 'frame-b' (the 2-frame cap), which MIS-attributed
  // Frame C (sandbox-c.test / BVT) into the Frame B galaxy. Now multi-frame:
  // each distinct trust_domain becomes its own galaxy (Frame C, … N).
  const seeded = frameByTrustDomain(FRAMES, cls)
  if (seeded) return `frame-${seeded.key.toLowerCase()}`
  return `frame-${slugify(cls)}`
}

function getFrameName(frameId: string): string {
  if (frameId === 'frame-local') return 'This frame'
  if (frameId === 'frame-a') return 'Frame A — Mainframe'
  if (frameId === 'frame-b') return 'Frame B — Sovereign'
  // N-frame: resolve a friendly label from the frames config by matching
  // frame-<key> (Frame C → "Frame C — Sovereign").
  const desc = FRAMES.find(f => `frame-${f.key.toLowerCase()}` === frameId)
  if (desc) {
    const suffix = desc.tier === 'mainframe' ? 'Mainframe'
      : desc.tier === 'sovereign-mainframe' ? 'Sovereign'
      : desc.tier === 'sandbox' ? 'Sandbox'
      : desc.tier === 'cloud-operator' ? 'Operator' : ''
    return suffix ? `${desc.label} — ${suffix}` : desc.label
  }
  // Derived id (frame-<trust_domain>) for a frame not in the seed — humanize.
  // e.g. 'frame-frame-c-theprotocol-cloud' → 'Frame C' (strip our own 'frame-'
  // wrapper AND the domain tail, whether dotted or hyphenated by the slugifier).
  return frameId
    .replace(/^frame-/, '')
    .replace(/[.-](theprotocol[.-]cloud|test|com)$/i, '')
    .replace(/\.test$|\.theprotocol\.cloud$|\.com$/, '')
    .replace(/[-.]/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

// ─── Events ─────────────────────────────────────────────────────
function onRegistryClick(registry: any, frameId: string) {
  log.info('Registry clicked:', registry.name, 'in frame', frameId)
  regCardPeer.value = registry?.isLocal ? null : (registry?.name || null)
  regCardFallback.value = registry?.name || null
  showRegCard.value = true
}
function onAgentClick(agent: any, frameId: string) {
  log.info('Agent clicked:', agent?.name, 'in frame', frameId)
  if (!agent?.did) return
  selectedAgentDid.value = agent.did
  showAgentModal.value = true
}

function onFrameClick(frame: any) {
  log.info('Frame clicked:', frame.name)
}

onMounted(() => loadData())
</script>

<template>
  <div class="universe-page" data-tour="universe-root">
    <!-- Loading overlay -->
    <div v-if="loading" class="universe-loading">
      <div class="uv-loader" aria-hidden="true">
        <span class="uv-loader__core"></span>
        <span class="uv-loader__ring uv-loader__ring--1"><i></i></span>
        <span class="uv-loader__ring uv-loader__ring--2"><i></i></span>
        <span class="uv-loader__ring uv-loader__ring--3"><i></i></span>
      </div>
      <div class="loading-title">SCANNING MULTIVERSE TOPOLOGY</div>
      <div class="loading-text" :key="loadStatus">{{ loadStatus }}</div>
    </div>

    <!-- Canvas -->
    <UniverseCanvas
      v-if="!loading"
      :frames="frames"
      :bridges="bridges"
      :search-query="searchQuery"
      :frame-filter="canvasFrameFilter"
      :registry-filter="canvasRegistryFilter"
      @registry-click="onRegistryClick"
      @agent-click="onAgentClick"
      @frame-click="onFrameClick"
    />

    <!-- IDENTICAL Galactic-Map search/filter bar (view-toggle hidden — 3D only) -->
    <GalacticControls
      v-if="!loading"
      variant="overlay"
      :show-view-modes="false"
      :frames="availableFrames"
      :registry-options="registryOptions"
      :sort-options="sortOptions"
      :capabilities="availableCapabilities"
      :result-count="shownCount"
      v-model:search="searchQuery"
      v-model:frame="selectedFrame"
      v-model:registry="selectedRegistry"
      v-model:sort="sortBy"
      v-model:selected-capabilities="selectedCapabilities"
    />

    <!-- Click-to-open detail surfaces (parity with AgentWorld) -->
    <AgentDetailModal v-model:show="showAgentModal" :agent-did="selectedAgentDid" />
    <SovereignRegistryCard v-model:show="showRegCard" :peer-name="regCardPeer" :fallback-name="regCardFallback" />

    <!-- Stats overlay -->
    <div class="universe-stats" data-tour="universe-stats" v-if="!loading">
      <div class="stat">
        <span class="stat-val">{{ totalFrames }}</span>
        <span class="stat-label">Sovereign Frames</span>
      </div>
      <div class="stat">
        <span class="stat-val">{{ totalRegistries }}</span>
        <span class="stat-label">Registries</span>
      </div>
      <div class="stat">
        <span class="stat-val">{{ totalAgents }}</span>
        <span class="stat-label">Agents</span>
      </div>
      <div class="stat">
        <span class="stat-val" :class="bridgeActive ? 'bridge-active' : 'bridge-inactive'">
          {{ bridges.length }}
        </span>
        <span class="stat-label">Federation Bridges</span>
      </div>
    </div>

    <!-- Title -->
    <div class="universe-title" data-tour="universe-hero" v-if="!loading">
      <h1>{{ t('universeView.title') }}</h1>
      <p>{{ t('universeView.subtitle') }}</p>
    </div>

    <!-- Legend overlay (collapsible — desktop default open, mobile default
         closed; user toggle persists in localStorage). -->
    <div class="universe-legend" :class="{ 'universe-legend--collapsed': !legendOpen }" v-if="!loading">
      <button
        type="button"
        class="uv-legend-head"
        @click="toggleLegend"
        :aria-expanded="legendOpen"
        aria-controls="uv-legend-body"
        :title="legendOpen ? 'Hide legend' : 'Show legend'"
      >
        <span class="uv-legend-head-label">LEGEND</span>
        <svg class="uv-legend-chevron" :class="{ 'uv-legend-chevron--open': legendOpen }" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 4.5 L6 7.5 L9 4.5" stroke="currentColor" stroke-width="1.4" fill="none" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <div id="uv-legend-body" v-show="legendOpen" class="uv-legend-body">
        <div class="uv-legend-title">FRAMES</div>
        <div v-for="lf in legendFrames" :key="'lf-' + lf.name" class="uv-legend-row">
          <span class="uv-dot" :style="{ background: lf.hex, boxShadow: '0 0 8px ' + lf.hex + '99' }"></span>{{ lf.name }}
        </div>

        <div class="uv-legend-title" style="margin-top:8px">BLACK HOLES</div>
        <div v-for="lf in legendFrames" :key="'bh-' + lf.name" class="uv-legend-row">
          <span class="uv-bh" :class="lf.bh.cls"></span>{{ lf.bh.label }} — {{ lf.name }} anchor
        </div>
        <div class="uv-legend-row uv-legend-note">Real-time gravitational lensing · Einstein-ring halo at 2.6·r<sub>s</sub></div>

        <div class="uv-legend-title" style="margin-top:8px">BRIDGES</div>
        <div class="uv-legend-row">
          <span class="uv-beam uv-beam-fed"></span>
          Federation — wrapped-unit sync
        </div>
        <div v-if="showFxLegend" class="uv-legend-row">
          <span class="uv-beam uv-beam-fx"></span>
          FX — cross-currency swap
        </div>

        <div class="uv-legend-title" style="margin-top:8px">HOP DEPTH <span class="uv-legend-note" style="padding:0">(on hover)</span></div>
        <div class="uv-legend-row uv-hop-ramp">
          <span v-for="h in HOP_RAMP" :key="'hop-' + h.hop" class="uv-hop-chip" :style="{ background: h.color }" :title="'Hop ' + h.hop">{{ h.hop }}</span>
          <span class="uv-hop-cap">local → distant</span>
        </div>

        <div class="uv-legend-title" style="margin-top:8px">AGENTS</div>
        <div class="uv-legend-row"><span class="uv-dot" style="background:#ffd700;box-shadow:0 0 5px #ffd70077"></span>Elite (95+)</div>
        <div class="uv-legend-row"><span class="uv-dot" style="background:#00e5ff"></span>Great (80+)</div>
        <div class="uv-legend-row"><span class="uv-dot" style="background:#4fc3f7"></span>Good (60+)</div>
        <div class="uv-legend-row"><span class="uv-dot" style="background:#7986cb"></span>Standard</div>
        <div class="uv-legend-row"><span class="uv-dot" style="background:#ffab40;box-shadow:0 0 5px #ffab4077"></span>Federated (synced)</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.universe-page {
  width: 100%;
  height: 100vh;
  position: relative;
  background: #030308;
  overflow: hidden;
}

.universe-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 10;
  background: radial-gradient(circle at 50% 44%, rgba(24, 46, 86, 0.42), rgba(3, 3, 8, 0.94) 68%);
}

/* Cinematic "forming multiverse" loader — a pulsing core orbited by three
   nested rings, each carrying a glowing node (federation = blue, fx = cyan,
   bridges = green). Pure CSS, GPU-cheap, no canvas. */
.uv-loader { position: relative; width: 124px; height: 124px; }
.uv-loader__core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 16px;
  height: 16px;
  margin: -8px 0 0 -8px;
  border-radius: 50%;
  background: radial-gradient(circle, #e6f3ff, #44bbff 55%, rgba(68, 187, 255, 0) 76%);
  box-shadow: 0 0 22px 5px rgba(68, 187, 255, 0.6);
  animation: uv-core-pulse 2.4s ease-in-out infinite;
}
.uv-loader__ring {
  position: absolute;
  top: 50%;
  left: 50%;
  border-radius: 50%;
  border: 1px solid rgba(92, 156, 245, 0.30);
}
.uv-loader__ring i {
  position: absolute;
  top: -3px;
  left: 50%;
  width: 6px;
  height: 6px;
  margin-left: -3px;
  border-radius: 50%;
  background: #88ccff;
  box-shadow: 0 0 10px 2px rgba(136, 204, 255, 0.9);
}
.uv-loader__ring--1 { width: 124px; height: 124px; margin: -62px 0 0 -62px; animation: uv-spin 3.2s linear infinite; }
.uv-loader__ring--2 { width: 86px;  height: 86px;  margin: -43px 0 0 -43px; border-color: rgba(0, 188, 212, 0.28); animation: uv-spin 2.3s linear infinite reverse; }
.uv-loader__ring--3 { width: 52px;  height: 52px;  margin: -26px 0 0 -26px; border-color: rgba(0, 230, 118, 0.22); animation: uv-spin 1.6s linear infinite; }
.uv-loader__ring--2 i { background: #4fd6e6; box-shadow: 0 0 10px 2px rgba(0, 188, 212, 0.85); }
.uv-loader__ring--3 i { background: #5cf2a0; box-shadow: 0 0 10px 2px rgba(0, 230, 118, 0.8); }

@keyframes uv-spin { to { transform: rotate(360deg); } }
@keyframes uv-core-pulse { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.35); opacity: 0.82; } }

.loading-title {
  margin-top: 28px;
  font-size: 13px;
  letter-spacing: 0.34em;
  font-weight: 600;
  color: rgba(196, 222, 250, 0.92);
  font-family: 'Inter', system-ui, sans-serif;
  text-shadow: 0 0 18px rgba(68, 187, 255, 0.35);
}
.loading-text {
  margin-top: 10px;
  font-size: 11px;
  letter-spacing: 0.18em;
  color: rgba(136, 204, 255, 0.62);
  font-family: 'Inter', system-ui, sans-serif;
  min-height: 14px;
  animation: uv-status-fade 0.5s ease;
}
@keyframes uv-status-fade { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: none; } }

.universe-stats {
  position: absolute;
  /* Sits BELOW the centered GalacticControls overlay bar (top:14, ~46px tall) so
     the two never collide on narrower viewports. [Commander 2026-06-07] */
  top: 72px;
  right: 16px;
  display: flex;
  gap: 20px;
  z-index: 5;
  padding: 12px 20px;
  background: rgba(6, 10, 20, 0.75);
  border: 1px solid rgba(68, 136, 255, 0.15);
  border-radius: 12px;
  backdrop-filter: blur(12px);
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.stat-val {
  font-size: 22px;
  font-weight: 700;
  color: #e0e8f0;
  font-family: 'Inter', system-ui, sans-serif;
}

.stat-label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(160, 180, 200, 0.6);
  margin-top: 2px;
}

.bridge-active { color: #44bbff; }
.bridge-inactive { color: #555; }

.universe-title {
  position: absolute;
  bottom: 24px;
  left: 24px;
  z-index: 5;
}

.universe-title h1 {
  font-size: 14px;
  letter-spacing: 0.3em;
  color: rgba(200, 220, 240, 0.5);
  font-weight: 600;
  margin: 0;
}

.universe-title p {
  font-size: 11px;
  color: rgba(140, 160, 180, 0.4);
  margin: 4px 0 0;
}

/* ── Legend ── */
.universe-legend {
  position: absolute;
  bottom: 24px;
  right: 20px;
  z-index: 5;
  padding: 8px 10px;
  background: rgba(6, 10, 20, 0.72);
  border: 1px solid rgba(68, 136, 255, 0.14);
  border-radius: 10px;
  backdrop-filter: blur(10px);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.66rem;
  min-width: 210px;
  transition: padding 180ms ease, min-width 180ms ease;
}
.universe-legend--collapsed {
  padding: 4px 8px;
  min-width: 0;
}

/* Collapsible header — clickable; shows LEGEND label + chevron. */
.uv-legend-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  background: transparent;
  border: none;
  padding: 4px 4px;
  margin: 0;
  color: rgba(160, 200, 240, 0.85);
  font-family: inherit;
  font-size: 0.62rem;
  letter-spacing: 0.16em;
  cursor: pointer;
  border-radius: 6px;
  transition: background 150ms;
}
.uv-legend-head:hover,
.uv-legend-head:focus-visible {
  background: rgba(68, 136, 255, 0.08);
  outline: none;
}
.uv-legend-head-label { font-weight: 600; }
.uv-legend-chevron {
  margin-left: auto;
  color: rgba(160, 200, 240, 0.65);
  transition: transform 200ms ease;
}
.uv-legend-chevron--open { transform: rotate(180deg); }
@media (prefers-reduced-motion: reduce) {
  .universe-legend,
  .uv-legend-chevron { transition: none; }
}

/* Body section — animated reveal via v-show toggle. Tiny gap above so
   the body doesn't crowd the header. */
.uv-legend-body { padding-top: 6px; }

/* Mobile pass: when expanded on phones, cap legend height + add scroll
   so it never blocks more than half the viewport. Collapsed state stays
   tight (just the LEGEND chip). */
@media (max-width: 767.98px) {
  .universe-legend {
    bottom: 14px;
    right: 12px;
    left: 12px;            /* span across so the chip + content don't stick to edge */
    min-width: 0;
    max-height: 50vh;
    max-height: 50dvh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }
  .universe-legend--collapsed {
    left: auto;            /* collapsed — only takes the chip width on the right */
    max-height: none;
    overflow: visible;
  }
}
.uv-legend-title {
  font-size: 0.58rem;
  letter-spacing: 0.12em;
  color: rgba(160, 200, 240, 0.55);
  margin-bottom: 4px;
}
.uv-legend-row {
  display: flex;
  align-items: center;
  gap: 7px;
  color: rgba(220, 230, 240, 0.55);
  margin-bottom: 3px;
}
.uv-dot {
  display: inline-block; width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0;
}
.uv-beam {
  display: inline-block; width: 18px; height: 3px; flex-shrink: 0; border-radius: 1px;
}
/* Federation = gold (matches the gold canvas beam + wrapped-token semantics). */
.uv-beam-fed {
  background: linear-gradient(90deg, rgba(255,215,0,0.15), #ffd700, rgba(255,215,0,0.15));
  box-shadow: 0 0 8px rgba(255, 215, 0, 0.55);
}
/* FX = cyan (cross-currency swap corridor — Frame A ↔ Frame C). */
.uv-beam-fx {
  background: linear-gradient(90deg, rgba(0,229,255,0.15), #00e5ff, rgba(0,229,255,0.15));
  box-shadow: 0 0 8px rgba(0, 229, 255, 0.6);
}
.uv-bh {
  display: inline-block; width: 12px; height: 12px; flex-shrink: 0; border-radius: 50%;
}
.uv-bh-amber {
  background: radial-gradient(circle at center, #000 32%, #cc6600 48%, rgba(255,140,40,0.55) 72%, transparent 95%);
  box-shadow: 0 0 6px rgba(255, 140, 40, 0.55);
}
.uv-bh-azure {
  background: radial-gradient(circle at center, #000 32%, #2288dd 48%, rgba(102,204,255,0.55) 72%, transparent 95%);
  box-shadow: 0 0 6px rgba(102, 204, 255, 0.55);
}
.uv-bh-gold {
  background: radial-gradient(circle at center, #000 32%, #ddaa22 48%, rgba(255,204,85,0.55) 72%, transparent 95%);
  box-shadow: 0 0 6px rgba(255, 204, 85, 0.55);
}
/* Hop-depth ramp chips (legend key for the on-hover hop badge). */
.uv-hop-ramp { flex-wrap: wrap; gap: 4px; }
.uv-hop-chip {
  display: inline-grid; place-items: center; width: 14px; height: 14px; border-radius: 3px;
  font-size: 0.5rem; font-weight: 700; color: rgba(0,0,0,0.75); flex-shrink: 0;
}
.uv-hop-cap { font-size: 0.52rem; color: rgba(200,220,240,0.4); margin-left: 4px; letter-spacing: 0.04em; }
.uv-legend-note {
  font-style: italic; font-size: 0.54rem; color: rgba(200,220,240,0.30);
  padding-left: 18px; margin-top: 1px; line-height: 1.35;
}
</style>
