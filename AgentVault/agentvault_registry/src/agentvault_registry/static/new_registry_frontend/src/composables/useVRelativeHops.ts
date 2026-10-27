// useVRelativeHops — V-relative tree-depth hop per registry NAME, identical to the
// GalacticMap topology (collapse the self-peer duplicate → bridge foreign frames
// through the LOCAL frame → de-flatten foreign operator chains from the BFS edges →
// BFS tree-depth from __local__). The ONLY place a hop is shown on Universe /
// AgentWorld is the on-hover RegistryHoverCard, so it must match the Galactic Map.
// Pure-FE; reads the same /public/topology the Galactic Map uses (tier buckets carry
// id + parent_registry_id + peer_type that the flat list / topology.edges lack).
// [Commander 2026-06-07] See feedback_galacticmap_vrelative_self_collapse.
import { ref } from 'vue'
import { useFrameAttribution } from './useFrameAttribution'

/** Normalise a registry name/slug for stable cross-source matching (strip non-alnum). */
export const normName = (s: string): string => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')

export function useVRelativeHops() {
  const { ensureLocalFrame, localTrustDomain } = useFrameAttribution()
  const hopByName = ref<Map<string, number>>(new Map())

  async function refresh(): Promise<Map<string, number>> {
    try {
      await ensureLocalFrame()
      const host = (window.location.hostname || '').toLowerCase()
      const port = window.location.port
      const isViteDev = ['localhost', '127.0.0.1'].includes(host) && (port === '5173' || port === '3000')
      const url = isViteDev
        ? `http://${host}:8000/api/v1/public/topology`
        : `${window.location.origin}/api/v1/public/topology`
      const resp = await fetch(url, { cache: 'no-store' })
      if (!resp.ok) return hopByName.value
      const d = await resp.json()

      // Local identity: the viewer's OWN page host slug (op-doha.op… → "opdoha";
      // frame-b.theprotocol.cloud → "frameb"). NOT trust_domain (a Frame-C op's td is
      // its PARENT frame). Mirrors GalacticMap.isLocalRegistry.
      const localSlugs = new Set<string>()
      if (host) localSlugs.add(normName(host.split('.')[0]))
      const ltd = (localTrustDomain.value || '').toLowerCase()
      const isLocal = (nm?: string | null): boolean => { const n = normName(nm || ''); return !!n && localSlugs.has(n) }

      // Nodes = /public/topology tier buckets (id-keyed; carry parent + peer_type).
      const full: any[] = []; const seen = new Set<string>()
      for (const b of ['frames', 'direct_peers', 'discovered', 'cloud_operators']) {
        for (const r of (d[b] || [])) {
          const i = r.id
          if (i != null && !seen.has(String(i))) { seen.add(String(i)); full.push(r) }
        }
      }
      const selfIds = new Set(full.filter(e => isLocal(e.name)).map(e => String(e.id)))
      const nodes = new Map<string, { name: string; pt: string; td: string; parent: string | null }>()
      for (const e of full) {
        if (selfIds.has(String(e.id))) continue
        nodes.set(String(e.id), {
          name: e.name, pt: e.peer_type, td: (e.trust_domain || '').toLowerCase(),
          parent: e.parent_registry_id != null ? String(e.parent_registry_id) : null,
        })
      }
      // Flat list → domain→name + BFS hop; topology.edges → name adjacency.
      const domToName = new Map<string, string>(); const bfsHopByName = new Map<string, number>()
      for (const r of (d.registries || [])) {
        const nm = normName(r.name); if (nm && r.domain) { domToName.set(r.domain, nm); bfsHopByName.set(nm, r.hopDepth ?? 99) }
      }
      const adjByName = new Map<string, Set<string>>()
      for (const ed of (d.edges || [])) {
        const [a, b] = String(ed).split('::')
        const na = domToName.get(a) || normName((a || '').split('.')[0])
        const nb = domToName.get(b) || normName((b || '').split('.')[0])
        if (!adjByName.has(na)) adjByName.set(na, new Set())
        if (!adjByName.has(nb)) adjByName.set(nb, new Set())
        adjByName.get(na)!.add(nb); adjByName.get(nb)!.add(na)
      }
      // Lookups
      const nameToId = new Map<string, string>(); const isFrameById = new Map<string, boolean>(); const tdById = new Map<string, string>()
      for (const [id, n] of nodes) { nameToId.set(normName(n.name), id); isFrameById.set(id, n.pt === 'frame'); tdById.set(id, n.td) }
      const resolveParent = (pid: string | null): string | null => pid == null ? null : (selfIds.has(pid) ? '__local__' : (nodes.has(pid) ? pid : null))
      let lpf: string | null = null
      if (ltd) for (const [id, n] of nodes) if (n.pt === 'frame' && n.td === ltd) { lpf = id; break }
      const deflat = (id: string): string | null => {
        const n = nodes.get(id)!; const nm = normName(n.name); const hop = bfsHopByName.get(nm)
        if (hop == null || hop <= 1) return null
        for (const nbr of (adjByName.get(nm) || [])) {
          const bid = nameToId.get(nbr); if (!bid || isFrameById.get(bid) || tdById.get(bid) !== n.td) continue
          if (bfsHopByName.get(nbr) === hop - 1) return bid
        }
        return null
      }
      // Resolve each node's parent (frame-route + parent_registry_id + de-flatten).
      const target = new Map<string, string>()
      for (const [id, n] of nodes) {
        let t = '__local__'
        if (n.pt === 'frame') t = (lpf && id !== lpf) ? lpf : '__local__'
        else t = resolveParent(n.parent) || '__local__'
        if (t === '__local__' || isFrameById.get(t)) { const df = deflat(id); if (df && df !== id) t = df }
        target.set(id, t)
      }
      // Tree-BFS depth from __local__.
      const adj2 = new Map<string, Set<string>>(); adj2.set('__local__', new Set())
      for (const id of nodes.keys()) if (!adj2.has(id)) adj2.set(id, new Set())
      for (const [id, t] of target) { adj2.get(id)!.add(t); if (!adj2.has(t)) adj2.set(t, new Set()); adj2.get(t)!.add(id) }
      const depth = new Map<string, number>([['__local__', 0]]); let frontier = ['__local__']
      while (frontier.length) {
        const next: string[] = []
        for (const id of frontier) { const dz = depth.get(id)!; for (const nb of (adj2.get(id) || [])) { if (!depth.has(nb)) { depth.set(nb, dz + 1); next.push(nb) } } }
        frontier = next
      }
      const m = new Map<string, number>()
      for (const [id, n] of nodes) { const dz = depth.get(id); if (typeof dz === 'number') m.set(normName(n.name), dz) }
      hopByName.value = m
      return m
    } catch { return hopByName.value }
  }

  return { hopByName, refresh }
}
