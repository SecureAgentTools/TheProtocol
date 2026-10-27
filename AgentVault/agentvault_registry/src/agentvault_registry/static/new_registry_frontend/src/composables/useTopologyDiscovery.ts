import { ref, reactive } from 'vue'
import { useLogger } from './useLogger'

const log = useLogger('Topology')

interface DiscoveredRegistry {
  name: string
  publicUrl: string
  domain: string
  hopDepth: number
  // 2026-05-05 audit Tier 3: backend returns trust_domain for every
  // registry (post-Tier-1A backend pass). Frontend uses it for frame
  // attribution via useFrameAttribution() instead of URL-substring guessing.
  trust_domain?: string
  // 2026-05-05 audit Tier 7: peer_type + hop_distance from /public/topology
  // tier buckets. Used by GalacticMap to render ordered hub-and-spoke
  // topology (mainframes ↔ each other via golden bridge; operators →
  // their frame's mainframe only).
  peer_type?: 'frame' | 'direct_peer' | 'discovered' | 'cloud_operator'
  hop_distance?: number
  parent_registry_id?: number | null
  // --- Registry Card v0.3 (2026-05-21) ---
  // Surfaced by backend /api/v1/public/topology for every peer with a cached
  // RC. AgentWorldCesium + LandingPage hover tooltip render visual + cost
  // display from these. `visual` keys come straight from peer.cached_registry_card.visual.
  visual?: {
    icon_url?: string | null
    orb_color?: string | null
    orb_glow_color?: string | null
    orb_pulse_speed_hz?: number | null
    orb_size_px?: number | null
    halo_enabled?: boolean | null
    halo_thickness?: number | null
    theme?: string | null
    sovereign_variant?: string | null
  } | null
  fees_summary?: {
    intra_registry?: number | null
    cross_registry?: number | null
    hosting_enabled?: boolean | null
    hosting_rate?: number | null
  } | null
  card_etag?: string | null
  card_signature_verified?: boolean
  // --- END RC v0.3 ---
}

interface TopologyState {
  registries: Map<string, DiscoveredRegistry>
  edges: Set<string>
  // 2026-05-30 — name(lc) → peer entry (carries RC `visual`/`fees_summary`/
  // `card_etag`) collected across ALL buckets: the flat `registries` BFS list
  // PLUS the tier buckets (frames/direct_peers/discovered/cloud_operators).
  // Lets the AgentWorld hydrate loop attach a peer's encirclement even when the
  // peer reached the globe via a tier bucket and is absent from the flat BFS
  // list (the sandbox case: frame/discovered peers on non-dotted internal hosts
  // — e.g. `nginx-test-b` — never enter the BFS flat list, but the backend DOES
  // serve their `visual` in the tier buckets). Strict no-op on prod, where every
  // peer is already in the flat list with identical visual.
  peersByName: Map<string, any>
  loading: boolean
  error: string | null
}

function getPublicUrl(baseUrl: string): string {
  try {
    const u = new URL(baseUrl)
    if (!u.hostname.includes('.')) return ''
    return `${u.protocol}//${u.hostname}`
  } catch { return '' }
}

function domainKey(urlOrDomain: string): string {
  try {
    const u = new URL(urlOrDomain.startsWith('http') ? urlOrDomain : `https://${urlOrDomain}`)
    return u.hostname.toLowerCase()
  } catch { return urlOrDomain.toLowerCase() }
}

function edgeKey(a: string, b: string): string {
  const sorted = [a, b].sort()
  return `${sorted[0]}::${sorted[1]}`
}

// Browser-side BFS removed 2026-04-15 — was firing 100+ cross-origin XHRs
// to operator domains, most failing with HTTP 502 (stopped operators) or
// CORS-blocked, choking the page render. The registry now exposes
// `/api/v1/public/topology` which does the BFS server-to-server, caches
// the graph for 60s, and returns it as one JSON. This composable now
// just hydrates the existing reactive structures from that endpoint.

export function useTopologyDiscovery() {
  const topology = reactive<TopologyState>({
    registries: new Map(),
    edges: new Set(),
    peersByName: new Map(),
    loading: true,
    error: null,
  })

  const version = ref(0)

  async function discoverTopology(
    localPeers: any[],
    localName: string,
    _maxHops = 2  // ignored — server picks the depth
  ) {
    topology.loading = true
    topology.error = null

    // Always seed with local first so the globe shows something even if
    // the API call fails.
    const localDomain = '__local__'
    topology.registries.set(localDomain, {
      name: localName,
      publicUrl: '',
      domain: localDomain,
      hopDepth: 0,
    })

    try {
      // Only the Vite dev server (npm run dev on :5173/:3000) proxies to the API
      // on :8000. ANY other localhost port (e.g. the sandbox UI served at :8002 /
      // :8003) is a real registry serving its OWN API on the same origin — use the
      // page origin so the sandbox globe shows sandbox topology, not prod's :8000.
      // Prod is non-localhost → origin already. (2026-05-30 fix — was hardcoding
      // :8000 for every localhost host, so sandbox showed prod's fleet.)
      const _host = window.location.hostname
      const _port = window.location.port
      const isViteDev = ['localhost', '127.0.0.1'].includes(_host) && (_port === '5173' || _port === '3000')
      const url = isViteDev
        ? `http://${_host}:8000/api/v1/public/topology`
        : `${window.location.origin}/api/v1/public/topology`
      const resp = await fetch(url, { cache: 'no-store' })
      if (resp.ok) {
        const data = await resp.json()
        topology.registries.clear()
        for (const reg of (data.registries || [])) {
          topology.registries.set(reg.domain, reg)
        }
        // 2026-06-03 — UNION every tier bucket into topology.registries, not just
        // the flat `registries` list. On sandbox the flat list is Frame-A-only
        // (e.g. 2 entries: Local + one cloud-op); the OTHER sovereign frames live
        // in `frames` (Frame B = sandbox-b.test, Frame C = sandbox-c.test) and the
        // cross-frame operators live in `discovered` (sandboxcharlie/sandboxdelta),
        // each ALREADY carrying the correct trust_domain. Without this union
        // UniverseView renders only ONE galaxy and GalacticMap drops operators.
        // Prod's flat list is already complete, so dedup-by-normalized-name makes
        // this a no-op there. (Pairs with feedback_agentworld_sandbox_encirclement_flat_list.)
        const _norm = (s: string) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
        const _localNorm = _norm(localName)
        const _seenNames = new Set<string>()
        for (const [, reg] of topology.registries) _seenNames.add(_norm((reg as any).name))
        for (const tier of ['frames', 'direct_peers', 'discovered', 'cloud_operators']) {
          for (const r of (data[tier] || [])) {
            const nm = _norm(r.name)
            if (!nm || nm === _localNorm || _seenNames.has(nm)) continue
            _seenNames.add(nm)
            const pub = r.public_url || r.publicUrl || ''
            const dk = pub ? domainKey(pub) : `peer:${nm}`
            if (topology.registries.has(dk)) continue
            // Spread the WHOLE bucket entry so its `visual` (flare encirclement,
            // orb colour, sovereign variant), card_signature, etag etc. survive.
            // Dropping `visual` here is exactly why Frame A's encirclement was
            // invisible from Frame C — the union added the frame entry but with
            // no flare. AgentWorld/Universe/Galactic read reg.visual to render
            // the FlareEncirclement.
            topology.registries.set(dk, {
              ...r,
              name: r.name,
              publicUrl: pub,
              domain: dk,
              hopDepth: r.hop ?? r.hop_distance ?? 2,
              trust_domain: r.trust_domain,
              peer_type: r.peer_type || tier,
            } as any)
          }
        }
        // 2026-05-05 audit Tier 7: enrich each topology.registries entry
        // with peer_type + hop_distance + parent_registry_id from the
        // tier buckets. The flat `registries` list is keyed by domain;
        // tier buckets are keyed by id and carry the structural metadata
        // GalacticMap needs for hub-and-spoke rendering. Match by name
        // since domain is the join key only the flat list has.
        const tierByName = new Map<string, any>()
        for (const tier of ['frames', 'direct_peers', 'discovered', 'cloud_operators']) {
          for (const r of (data[tier] || [])) {
            const nm = (r.name || '').trim().toLowerCase()
            if (nm) tierByName.set(nm, r)
          }
        }
        for (const [, reg] of topology.registries) {
          const nm = (reg.name || '').trim().toLowerCase()
          const tier = tierByName.get(nm)
          if (tier) {
            ;(reg as any).peer_type = tier.peer_type
            ;(reg as any).hop_distance = tier.hop_distance
            ;(reg as any).parent_registry_id = tier.parent_registry_id
          }
        }
        // 2026-05-30 — index every peer's RC visual/fees BY NAME across the flat
        // list AND the tier buckets. Flat-list entries win (set first); tier
        // entries only fill gaps. The AgentWorld hydrate loop reads this so a
        // peer reaching the globe via a tier bucket (frame/discovered) but
        // missing from the flat BFS list still gets its encirclement. See the
        // peersByName note on TopologyState — no-op on prod.
        topology.peersByName.clear()
        for (const reg of (data.registries || [])) {
          const nm = (reg.name || '').trim().toLowerCase()
          if (nm) topology.peersByName.set(nm, reg)
        }
        for (const [nm, tierReg] of tierByName) {
          if (nm && !topology.peersByName.has(nm)) topology.peersByName.set(nm, tierReg)
        }
        topology.edges.clear()
        for (const edge of (data.edges || [])) {
          topology.edges.add(edge)
        }
      } else {
        // Graceful fallback: seed from localPeers only (no recursion)
        for (const peer of localPeers) {
          const pub = getPublicUrl(peer.base_url || peer.url || '')
          if (!pub) continue
          const dk = domainKey(pub)
          topology.registries.set(dk, {
            name: peer.name || dk,
            publicUrl: pub,
            domain: dk,
            hopDepth: 1,
          })
          topology.edges.add(edgeKey(localDomain, dk))
        }
      }
    } catch (e) {
      topology.error = 'topology fetch failed'
      log.debug('fetch failed:', e)
    } finally {
      topology.loading = false
      version.value++
    }

    log.debug(
      `Loaded ${topology.registries.size} registries, ${topology.edges.size} edges`
    )
  }

  return { topology, version, discoverTopology, getPublicUrl, domainKey, edgeKey }
}
