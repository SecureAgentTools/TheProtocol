import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { apiClient } from '@/services/api/client'
import type { Registry } from '@/types'
import type { FederationInfo, FederationHealthCheck, FederationNetworkStats } from '@/services/api/federation'
import { useAuthStore } from './auth'
import { useUIStore } from './ui'

export const useFederationStore = defineStore('federation', () => {
  // State
  const registries = ref<Registry[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  // Cache for latency and health data that persists between refreshes
  const metricsCache = ref<Record<string, { latency?: number; health?: number; lastTest?: string }>>({})
  
  // FIX-16/17/18: Real federation data from backend
  const federationInfo = ref<FederationInfo | null>(null)
  const healthStatus = ref<FederationHealthCheck | null>(null)
  const networkStats = ref<FederationNetworkStats | null>(null)
  const localAgentCount = ref(0)  // BUG-A: Track local-only agents separately from total
  const peerHealthMap = ref<Record<string, FederationHealthCheck>>({})

  // Getters
  const connectedRegistries = computed(() => 
    registries.value.filter(r => r.status === 'active')
  )

  const registryCount = computed(() => registries.value.length)

  // Actions
  async function fetchRegistries() {
    loading.value = true
    error.value = null
    
    try {
      // Import federation API service
      const { federationApi } = await import('@/services/api/federation')
      
      // Use the corrected API method
      const response = await federationApi.getRegistries()
      
      // Update registries with fetched data
      registries.value = response.registries.map((reg: any) => {
        const id = reg.id
        // Get cached metrics if available
        const cachedMetrics = metricsCache.value[id] || {}
        
        return {
          ...reg,
          id,
          // Use cached values for metrics that might not be provided
          health: cachedMetrics.health ?? reg.health ?? 100,
          latency: cachedMetrics.latency ?? reg.latency,
          // Ensure consistent field names
          agents: reg.agents ?? reg.agentCount ?? 0,
          status: reg.status, // Already normalized by API service
          trusted: reg.trusted !== false,
          last_seen: reg.last_seen || reg.lastSync || new Date().toISOString(),
          public_key: reg.publicKey || reg.public_key || ''
        }
      })
      
      import.meta.env.DEV && console.log(`Fetched ${registries.value.length} registries from public endpoint`)
    } catch (err: any) {
      console.error('Failed to fetch federation peers:', err)
      error.value = err.response?.data?.detail || err.message || 'Failed to fetch registries'
      registries.value = [] // Return empty on error
    } finally {
      loading.value = false
    }
  }

  async function addRegistry(registry: Partial<Registry>) {
    loading.value = true
    error.value = null
    
    try {
      // Use real API
      const { federationApi } = await import('@/services/api/federation')
      const result = await federationApi.addRegistry({
        name: registry.name || '',
        url: registry.url || '',
        publicKey: registry.public_key,
        description: registry.description
      })
      
      // Add the new registry to our list
      const newRegistry = {
        ...result.registry,
        status: result.status as any,
        trusted: false,
        last_seen: result.registry.lastSync,
        public_key: result.registry.publicKey || ''
      }
      
      registries.value.push(newRegistry)
      return newRegistry
    } catch (err: any) {
      error.value = err.response?.data?.detail || err.message || 'Failed to add registry'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function removeRegistry(id: string) {
    loading.value = true
    error.value = null
    
    try {
      const { federationApi } = await import('@/services/api/federation')
      await federationApi.removeRegistry(id)
      
      // Remove from local state
      registries.value = registries.value.filter(r => r.id !== id)
    } catch (err: any) {
      error.value = err.response?.data?.detail || err.message || 'Failed to remove registry'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function syncRegistry(id: string) {
    loading.value = true
    error.value = null
    
    try {
      // Use the federation API
      const { federationApi } = await import('@/services/api/federation')
      const result = await federationApi.syncRegistry(id)
      
      // Update the registry's status and sync time
      const registry = registries.value.find(r => r.id === id)
      if (registry) {
        registry.last_seen = new Date().toISOString()
        registry.status = 'active'
        
        // Update agent count if provided
        if (result.syncDetails?.agent_count !== undefined) {
          registry.agents = result.syncDetails.agent_count
        }
        
        // Update health to 100% for active registry
        registry.health = 100
        metricsCache.value[id] = {
          ...metricsCache.value[id],
          health: 100
        }
      }
      
      return result
    } catch (err: any) {
      error.value = err.response?.data?.detail || err.message || 'Failed to sync registry'
      throw err
    } finally {
      loading.value = false
    }
  }

  // Test connection and cache latency
  async function testConnection(url: string) {
    try {
      // Import federation API
      const { federationApi } = await import('@/services/api/federation')
      const result = await federationApi.testConnection(url)
      
      // Cache the latency for this registry
      if (result.reachable && result.latency) {
        const registry = registries.value.find(r => r.url === url)
        if (registry) {
          metricsCache.value[registry.id] = {
            ...metricsCache.value[registry.id],
            latency: result.latency,
            lastTest: new Date().toISOString()
          }
          // Update the registry object too
          registry.latency = result.latency
        }
      }
      
      return result
    } catch (error) {
      console.error('Test connection failed:', error)
      throw error
    }
  }

  // Admin function: Reactivate an inactive registry
  async function reactivateRegistry(id: string) {
    const authStore = useAuthStore()
    const uiStore = useUIStore()
    
    if (!authStore.isAdmin) {
      uiStore.showError('Unauthorized', 'Admin access required to reactivate registries')
      throw new Error('Admin access required')
    }
    
    loading.value = true
    error.value = null
    
    try {
      const { federationApi } = await import('@/services/api/federation')
      const updatedRegistry = await federationApi.reactivateRegistry(id)
      
      // Update local state
      const index = registries.value.findIndex(r => r.id === id)
      if (index !== -1) {
        registries.value[index] = {
          ...registries.value[index],
          ...updatedRegistry,
          status: 'active'
        }
      }
      
      uiStore.showSuccess('Registry Reactivated', `Successfully reactivated registry`)
      return updatedRegistry
    } catch (err: any) {
      error.value = err.message || 'Failed to reactivate registry'
      uiStore.showError('Reactivation Failed', error.value ?? undefined)
      throw err
    } finally {
      loading.value = false
    }
  }

  // Admin function: Approve a pending registry
  async function approveRegistry(id: string) {
    const authStore = useAuthStore()
    const uiStore = useUIStore()
    
    if (!authStore.isAdmin) {
      uiStore.showError('Unauthorized', 'Admin access required to approve registries')
      throw new Error('Admin access required')
    }
    
    loading.value = true
    error.value = null
    
    try {
      const { federationApi } = await import('@/services/api/federation')
      const updatedRegistry = await federationApi.approveRegistry(id)
      
      // Update local state
      const index = registries.value.findIndex(r => r.id === id)
      if (index !== -1) {
        registries.value[index] = {
          ...registries.value[index],
          ...updatedRegistry,
          status: 'active'
        }
      }
      
      uiStore.showSuccess('Registry Approved', `Successfully approved registry`)
      return updatedRegistry
    } catch (err: any) {
      error.value = err.message || 'Failed to approve registry'
      uiStore.showError('Approval Failed', error.value ?? undefined)
      throw err
    } finally {
      loading.value = false
    }
  }

  // Admin function: Reject a pending registry
  async function rejectRegistry(id: string) {
    const authStore = useAuthStore()
    const uiStore = useUIStore()
    
    if (!authStore.isAdmin) {
      uiStore.showError('Unauthorized', 'Admin access required to reject registries')
      throw new Error('Admin access required')
    }
    
    loading.value = true
    error.value = null
    
    try {
      const { federationApi } = await import('@/services/api/federation')
      const updatedRegistry = await federationApi.rejectRegistry(id)
      
      // Update local state
      const index = registries.value.findIndex(r => r.id === id)
      if (index !== -1) {
        registries.value[index] = {
          ...registries.value[index],
          ...updatedRegistry,
          status: 'rejected'
        }
      }
      
      uiStore.showSuccess('Registry Rejected', `Registry has been rejected`)
      return updatedRegistry
    } catch (err: any) {
      error.value = err.message || 'Failed to reject registry'
      uiStore.showError('Rejection Failed', error.value ?? undefined)
      throw err
    } finally {
      loading.value = false
    }
  }

  // Admin function: Fetch all registries including inactive and pending
  async function fetchAllRegistries() {
    const authStore = useAuthStore()
    
    if (!authStore.isAdmin) {
      // Fallback to regular fetch for non-admins
      return fetchRegistries()
    }
    
    loading.value = true
    error.value = null
    
    try {
      const { federationApi } = await import('@/services/api/federation')
      const response = await federationApi.getAllRegistries()
      
      // Update registries with all statuses
      registries.value = response.registries.map((reg: any) => {
        const id = reg.id
        const cachedMetrics = metricsCache.value[id] || {}
        
        return {
          ...reg,
          id,
          // Use cached values for metrics
          health: cachedMetrics.health ?? reg.health ?? 100,
          latency: cachedMetrics.latency ?? reg.latency,
          // Status is already normalized by API service
          status: reg.status,
          // Ensure consistent field names
          agents: reg.agents ?? reg.agentCount ?? 0,
          trusted: reg.trusted !== false,
          last_seen: reg.last_seen || reg.lastSync || new Date().toISOString(),
          public_key: reg.publicKey || reg.public_key || ''
        }
      })
      
      import.meta.env.DEV && console.log(`Fetched ${registries.value.length} registries (admin view with all statuses)`)
    } catch (err: any) {
      console.error('Failed to fetch all registries:', err)
      error.value = err.response?.data?.detail || err.message || 'Failed to fetch all registries'
      // Fallback to regular fetch
      return fetchRegistries()
    } finally {
      loading.value = false
    }
  }

  // FIX-25: Enrich peer registries with real agent counts from federated cards
  async function enrichPeerAgentCounts() {
    try {
      // Hit agent-cards with include_federated=true to see ALL agents + their origin
      // NOTE: active_only causes 422 with auth; limit max is 250
      const { apiClient } = await import('@/services/api/client')
      const response = await apiClient.get('/agent-cards', {
        params: { include_federated: true, limit: 250 }
      })
      const cards = response.data.items || response.data.agent_cards || response.data || []
      
      // Build origin_registry_name -> count map
      const originCounts: Record<string, number> = {}
      for (const card of cards) {
        const origin = card.origin_registry_name || 'Local'
        originCounts[origin] = (originCounts[origin] || 0) + 1
      }
      
      import.meta.env.DEV && console.log('Agent counts by origin:', originCounts)
      
      // BUG-A: Store local agent count separately (for topology local node)
      localAgentCount.value = originCounts['Local'] || 0
      
      // Match peer registries to their origin counts by name
      // e.g. peer named "Registry B" matches origin_registry_name: "Registry B"
      for (const registry of registries.value) {
        const count = originCounts[registry.name] || 0
        if (count > 0) {
          registry.agents = count
          registry.agentCount = count
        }
      }
      
      // Also update networkStats total if available
      const totalFromCards = cards.length
      if (networkStats.value && totalFromCards > networkStats.value.totalAgents) {
        networkStats.value.totalAgents = totalFromCards
      }
    } catch (err: any) {
      console.error('Failed to enrich peer agent counts:', err)
    }
  }

  // FIX-16: Fetch real network stats from backend
  async function fetchNetworkStats() {
    try {
      const { federationApi } = await import('@/services/api/federation')
      const stats = await federationApi.getNetworkStatsReal()
      // FIX-30: Sanitize lastGlobalSync — backend returns double timezone "+00:00Z"
      if (stats.lastGlobalSync) {
        stats.lastGlobalSync = stats.lastGlobalSync.replace(/\+00:00Z$/, 'Z')
      }
      networkStats.value = stats
      import.meta.env.DEV && console.log('Network stats loaded:', networkStats.value)
    } catch (err: any) {
      console.error('Failed to fetch network stats:', err)
    }
  }

  // FIX-17: Fetch federation info (auth methods, SPIFFE trust domain)
  async function fetchFederationInfo() {
    try {
      const { federationApi } = await import('@/services/api/federation')
      federationInfo.value = await federationApi.getFederationInfo()
      import.meta.env.DEV && console.log('Federation info loaded:', federationInfo.value)
    } catch (err: any) {
      console.error('Failed to fetch federation info:', err)
    }
  }

  // FIX-18: Fetch health check (component-level status)
  async function fetchHealthStatus() {
    try {
      const { federationApi } = await import('@/services/api/federation')
      healthStatus.value = await federationApi.getHealthCheck()
      import.meta.env.DEV && console.log('Health status loaded:', healthStatus.value)
    } catch (err: any) {
      console.error('Failed to fetch health status:', err)
    }
  }

  // FIX-24: Real connection test — probe peer's health-check endpoint
  async function testPeerHealth(peerId: string, peerBaseUrl: string) {
    try {
      const { federationApi } = await import('@/services/api/federation')
      const startTime = Date.now()
      const health = await federationApi.getHealthCheck(peerBaseUrl)
      const latency = Date.now() - startTime
      
      peerHealthMap.value[peerId] = health
      metricsCache.value[peerId] = {
        ...metricsCache.value[peerId],
        latency,
        health: health.status === 'healthy' ? 100 : 0,
        lastTest: new Date().toISOString()
      }
      
      // Update registry latency
      const registry = registries.value.find(r => r.id === peerId)
      if (registry) {
        registry.latency = latency
        registry.health = health.status === 'healthy' ? 100 : 0
      }
      
      return { health, latency }
    } catch (err: any) {
      console.error(`Peer health test failed for ${peerBaseUrl}:`, err)
      return { health: null, latency: -1 }
    }
  }

  // Fetch ALL federation data in one shot
  async function fetchAllFederationData() {
    await Promise.all([
      fetchFederationInfo(),
      fetchHealthStatus(),
      fetchNetworkStats()
    ])
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout. See globalReset.ts.
  function $reset() {
    registries.value = []
    loading.value = false
    error.value = null
    metricsCache.value = {}
    federationInfo.value = null
    healthStatus.value = null
    networkStats.value = null
    localAgentCount.value = 0
    peerHealthMap.value = {}
  }

  return {
    // State
    registries,
    loading,
    error,
    metricsCache,
    federationInfo,
    healthStatus,
    networkStats,
    localAgentCount,
    peerHealthMap,
    $reset,
    
    // Getters
    connectedRegistries,
    registryCount,
    
    // Actions
    fetchRegistries,
    fetchAllRegistries,
    addRegistry,
    removeRegistry,
    syncRegistry,
    testConnection,
    testPeerHealth,
    reactivateRegistry,
    approveRegistry,
    rejectRegistry,
    fetchNetworkStats,
    fetchFederationInfo,
    fetchHealthStatus,
    fetchAllFederationData,
    enrichPeerAgentCounts
  }
})
