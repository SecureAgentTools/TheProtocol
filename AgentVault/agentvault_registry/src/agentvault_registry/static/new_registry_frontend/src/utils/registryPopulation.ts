// §GLOBEPOP 2026-08-11 — true per-registry populations for the globe views.
//
// /api/v1/agents/locations/ now returns `registries: [{name, trust_domain,
// total, shown}]` alongside a budget-sampled point list (every registry is
// guaranteed min_per_registry points; the remainder is proportional to true
// populations). The views DRAW the sampled points but LABEL the true totals,
// so a registry's displayed count never depends on how many of its agents
// made the sample. Fallback everywhere is the drawn count (old behavior).

export interface RegistryPopulation {
  name: string
  trust_domain: string | null
  total: number
  shown: number
}

const norm = (s: string | null | undefined) => (s || '').toLowerCase().trim()

export interface PopulationIndex {
  lookup(name?: string | null, trustDomain?: string | null): RegistryPopulation | undefined
  totalPopulation: number
  size: number
}

export function buildPopulationIndex(registries?: RegistryPopulation[] | null): PopulationIndex {
  const byName = new Map<string, RegistryPopulation>()
  const byTd = new Map<string, RegistryPopulation>()
  let totalPopulation = 0
  for (const r of registries || []) {
    if (!r || typeof r.total !== 'number') continue
    totalPopulation += r.total
    if (r.name) byName.set(norm(r.name), r)
    if (r.trust_domain) byTd.set(norm(r.trust_domain), r)
  }
  return {
    totalPopulation,
    size: byName.size,
    lookup(name?: string | null, trustDomain?: string | null) {
      if (name) {
        const hit = byName.get(norm(name))
        if (hit) return hit
      }
      if (trustDomain) {
        const hit = byTd.get(norm(trustDomain))
        if (hit) return hit
      }
      return undefined
    },
  }
}
