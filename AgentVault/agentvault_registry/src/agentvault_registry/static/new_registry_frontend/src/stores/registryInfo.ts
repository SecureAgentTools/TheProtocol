/**
 * registryInfo store — cached singleton of /federation/info.
 *
 * §pass66 (2026-05-22) — single source of truth for "what registry is this
 * frontend talking to?" Used by:
 *   - usePermissions().isMainframe (mainframe-only feature gates)
 *   - Header bar (replaces "//SOVEREIGN·NODE" with the real registry name)
 *   - Future surfaces that need tier / registry_name / trust_domain
 *
 * Why a store and not inline fetch in each component:
 *   /federation/info is called 5+ times across views today (GalacticMap,
 *   UniverseView, AgentWorldCesium, …) — each maintains its own cached
 *   copy. Centralizing means:
 *     - one network call at app boot, not 5
 *     - permission decisions stay coherent across views
 *     - tests can patch one store instead of many
 *
 * The tier never changes at runtime for a given registry process, so we
 * fetch once + cache forever. App restart re-fetches naturally.
 */
import { defineStore } from 'pinia'
import { apiClient } from '@/services/api/client'
import { loadFrameManifest } from '@/composables/useFrameManifest'

export interface RegistryInfo {
  registry_name: string
  api_version: string
  federation_protocol_version: string
  supported_auth_methods: string[]
  health_check_endpoint: string
  timestamp: string
  spiffe_trust_domain: string
  /** §pass66 — frontend gating signal. True iff sovereign-mainframe. */
  is_mainframe?: boolean
  /** §pass66 — registry tier. One of:
   *  'sovereign-mainframe' | 'regional-mainframe' | 'cloud-operator' |
   *  'sandbox' | 'standalone' */
  tier?: string
}

interface State {
  info: RegistryInfo | null
  loading: boolean
  lastError: string | null
}

export const useRegistryInfoStore = defineStore('registryInfo', {
  state: (): State => ({
    info: null,
    loading: false,
    lastError: null,
  }),
  getters: {
    /** True iff backend reports `is_mainframe=true`. Fallback to tier check
     *  for older backends that don't expose the flag. */
    isMainframe: (s) => {
      if (!s.info) return false
      if (s.info.is_mainframe === true) return true
      if (s.info.is_mainframe === false) return false
      // Fallback: derive from tier (handles a pre-§pass66 mainframe in the wild)
      return s.info.tier === 'sovereign-mainframe'
    },
    registryName: (s) => s.info?.registry_name ?? '',
    tier: (s) => s.info?.tier ?? 'unknown',
  },
  actions: {
    async load(force: boolean = false): Promise<RegistryInfo | null> {
      // Cached forever — tier doesn't change at runtime. `force` bypasses
      // for tests / explicit refresh.
      if (this.info && !force) return this.info
      if (this.loading) {
        // De-dupe concurrent callers — wait for the in-flight request.
        // Simple polling loop is fine here; load() resolves in ~50ms typically.
        await new Promise<void>((resolve) => {
          const tick = () => (this.loading ? setTimeout(tick, 50) : resolve())
          tick()
        })
        return this.info
      }
      this.loading = true
      this.lastError = null
      try {
        // §FEFRAME W2: the frame manifest names this registry (its display name, trust domain, role and tier) in the
        // one config read every identity reader shares; /federation/info is the fallback for a console whose
        // manifest could not be read (its trust domain defaulted to agentvault.com on a registry without SPIRE).
        const m = await loadFrameManifest()
        if (m?.self) {
          this.info = {
            registry_name: m.self.display_name || m.self.name,
            api_version: '', federation_protocol_version: '', supported_auth_methods: [],
            health_check_endpoint: '', timestamp: new Date().toISOString(),
            spiffe_trust_domain: m.self.trust_domain || '',
            is_mainframe: m.self.role === 'frame',
            tier: m.self.tier || (m.self.role === 'frame' ? 'sovereign-mainframe' : 'cloud-operator'),
          }
          return this.info
        }
        const { data } = await apiClient.get<RegistryInfo>('/federation/info')
        this.info = data
        return data
      } catch (e: any) {
        this.lastError = e?.message || 'failed to load /federation/info'
        return null
      } finally {
        this.loading = false
      }
    },
  },
})
