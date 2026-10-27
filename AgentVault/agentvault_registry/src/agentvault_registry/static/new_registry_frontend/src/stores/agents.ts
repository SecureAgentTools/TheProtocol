import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Agent, CreateAgentDto, UpdateAgentDto } from '@/types'
import { agentApi } from '@/services/api/agents'
import { apiClient } from '@/services/api/client'
import { batchedPost } from '@/services/api/batchedPost'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('agents')

// Helper function to safely get agent properties
function getAgentProperty(agent: any, property: string): string {
  // First try direct property
  if (agent[property]) return agent[property]
  
  // Then try card_data
  if (agent.card_data && agent.card_data[property]) return agent.card_data[property]
  
  // Default values
  return property === 'name' ? 'Unnamed Agent' : ''
}

// Helper to get agent identifier (prefer UUID over numeric ID)
function getAgentIdentifier(agent: any): string {
  // If we have a UUID-looking ID, use it
  if (agent.id && String(agent.id).includes('-')) {
    return agent.id
  }
  
  // If we have humanReadableId in card_data, use it
  if (agent.card_data?.humanReadableId) {
    return agent.card_data.humanReadableId
  }
  
  // If we have a DID, use it
  if (agent.did) {
    return agent.did
  }
  
  // Last resort: use numeric ID
  return String(agent.id || '')
}

export const useAgentStore = defineStore('agents', () => {
  // State
  const agents = ref<Agent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** §FESUITE (2026-10-05): the last fleet read (fetchMyAgents) failed. My Agents drew "Fleet is empty" over a failed
   *  read; it says the read failed now. The list itself is left as it was (a failed refresh keeps what was shown). */
  const myAgentsFailed = ref(false)
  const currentAgent = ref<Agent | null>(null)
  const currentPage = ref(1)
  const searchQuery = ref('')
  const statusFilter = ref('')
  const itemsPerPage = 12
  const totalCount = ref(0)
  
  // Getters
  const filteredAgents = computed(() => {
    let filtered = agents.value

    // Apply search filter with null checks
    if (searchQuery.value) {
      const query = searchQuery.value.toLowerCase()
      filtered = filtered.filter(agent => {
        try {
          // Safely check each property with null/undefined protection
          const name = getAgentProperty(agent, 'name')
          const description = getAgentProperty(agent, 'description')
          const did = agent.did || ''
          
          const nameMatch = name.toLowerCase().includes(query)
          const descriptionMatch = description.toLowerCase().includes(query)
          const didMatch = did.toLowerCase().includes(query)
          
          // Check capabilities safely
          const capabilities = agent.capabilities || agent.card_data?.tags || []
          const capabilitiesMatch = capabilities.some((cap: any) => 
            String(cap || '').toLowerCase().includes(query)
          )
          
          return nameMatch || descriptionMatch || didMatch || capabilitiesMatch
        } catch (err) {
          log.warn('Error filtering agent:', agent, err)
          return false
        }
      })
    }

    // Apply status filter
    if (statusFilter.value) {
      filtered = filtered.filter(agent => agent.status === statusFilter.value)
    }

    return filtered
  })
  
  const paginatedAgents = computed(() => {
    const start = (currentPage.value - 1) * itemsPerPage
    const end = start + itemsPerPage
    return filteredAgents.value.slice(start, end)
  })
  
  const totalPages = computed(() => 
    Math.ceil(filteredAgents.value.length / itemsPerPage)
  )

  // Sticky federated flag — once a view requests federated agents, all subsequent
  // fetches (including auth-triggered re-fetches) preserve it
  const _includeFederated = ref(false)

  // Actions
  async function fetchAgents(page = 1, includeFederated = false) {
    // Sticky: once set to true, stays true until explicitly cleared
    if (includeFederated) _includeFederated.value = true

    loading.value = true
    error.value = null
    
    try {
      // Real API call — ALWAYS include federated for complete network view
      // The agent cards endpoint is public discovery; federated agents should always be visible
      const response = await agentApi.getAll({
        page,
        limit: itemsPerPage,
        search: searchQuery.value,
        status: statusFilter.value,
        include_federated: true,  // Always include federated agents
        active_only: true,        // OWL24: Explicitly filter out deactivated/revoked cards
      })
      
      // Process agents to ensure they have proper structure
      const processedAgents = (response.items || []).map((agent: any) => ({
        ...agent,
        name: getAgentProperty(agent, 'name'),
        description: getAgentProperty(agent, 'description'),
        capabilities: agent.capabilities || agent.card_data?.tags || [],
        // BUG-NEW-002 FIX: Backend returns last_active_at, not updated_at
        updated_at: agent.updated_at || agent.last_active_at || agent.created_at
      }))
      
      agents.value = processedAgents
      totalCount.value = response.total || 0
      currentPage.value = page
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch agents'
      console.error('Failed to fetch agents:', err)
    } finally {
      loading.value = false
    }
  }
  
  async function fetchAllForMap() {
    loading.value = true
    error.value = null
    _includeFederated.value = true
    try {
      // Backstop timeout: this is the SECONDARY (card_data backfill) source for
      // the map/universe globes — the PRIMARY source is /agents/locations/, which
      // each view fetches itself. If the federated card_data list is slow (it is
      // server-capped to `limit` now, but a loaded sandbox can still lag), we must
      // NOT let `loading` hang forever (the old "SCANNING MULTIVERSE…" freeze).
      // Race against a 22s ceiling; on timeout the view still renders from
      // /agents/locations/ and `finally` clears loading.
      const response: any = await Promise.race([
        agentApi.getAll({
          page: 1,
          limit: 250,
          include_federated: true,
          active_only: true,
          include_card_data: true,  // Needed for Universe View federation_metadata
        }),
        new Promise((_, reject) =>
          setTimeout(() => reject(new Error('fetchAllForMap timeout (22s) — globe renders from /agents/locations/')), 22000)
        ),
      ])
      const processedAgents = (response.items || []).map((agent: any) => ({
        ...agent,
        name: getAgentProperty(agent, 'name'),
        description: getAgentProperty(agent, 'description'),
        capabilities: agent.capabilities || agent.card_data?.tags || [],
        updated_at: agent.updated_at || agent.last_active_at || agent.created_at
      }))
      agents.value = processedAgents
      totalCount.value = response.total || processedAgents.length
      currentPage.value = 1
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch agents for map'
      console.error('Failed to fetch agents for map:', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchMyAgents(page?: number, opts?: { limit?: number; offset?: number; q?: string; topLevelOnly?: boolean }) {
    loading.value = true
    error.value = null

    try {
      // 2026-05-09: backend caps /me/agents at 200 by default (max 500).
      // Without an explicit limit, callers (MyAgents/OnboardingWizard/
      // OrganizationDashboard/AgentDetails) get the safe default. Pass
      // {limit: 500} for "show me everything I own" + paginate via offset
      // for fleets larger than 500.
      const response = await agentApi.getMyAgents(opts)
      
      // Process agents to ensure they have proper structure
      let processedAgents: any[] = []
      
      // Backend returns array directly for /developers/me/agents
      if (Array.isArray(response)) {
        processedAgents = response.map((agent: any) => ({
          ...agent,
          name: getAgentProperty(agent, 'name'),
          description: getAgentProperty(agent, 'description'),
          capabilities: agent.capabilities || agent.card_data?.tags || [],
          // BUG-NEW-002 FIX: Backend returns last_active_at, not updated_at
          updated_at: agent.updated_at || agent.last_active_at || agent.created_at
        }))
        totalCount.value = response.length
      } else {
        // Handle paginated response format
        processedAgents = (response.items || []).map((agent: any) => ({
          ...agent,
          name: getAgentProperty(agent, 'name'),
          description: getAgentProperty(agent, 'description'),
          capabilities: agent.capabilities || agent.card_data?.tags || [],
          // BUG-NEW-002 FIX: Backend returns last_active_at, not updated_at
          updated_at: agent.updated_at || agent.last_active_at || agent.created_at
        }))
        totalCount.value = response.total || 0
      }
      
      agents.value = processedAgents
      myAgentsFailed.value = false

      // FIX: Enrich liquid_balance from live TEG data.
      // The registry DB liquid_balance is never updated by TEG funding operations —
      // only staked_balance is written by the staking router. We must query TEG
      // directly for accurate liquid balances.
      //
      // The /developers/me/agents/balances endpoint caps each request at 50 agents,
      // so we chunk the DID list and run the requests in parallel.
      if (processedAgents.length > 0) {
        try {
          const dids = processedAgents.map((a: any) => a.did).filter(Boolean)
          // §BATCH8 item 9 (2026-09-06): bounded window (4 in flight, 50 DIDs each) and stop on the first
          // 401 — 83 parallel batches with a dead session were the burst that banned his VPN exit.
          const { results: responses } = await batchedPost(
            dids,
            (batch: string[]) => apiClient.post('/developers/me/agents/balances', { agent_dids: batch }),
            { chunkSize: 50, concurrency: 4, stopOn401: true },
          )
          const balances: Record<string, any> = {}
          for (const r of responses) {
            Object.assign(balances, r.data?.balances || {})
          }
          agents.value = agents.value.map((a: any) => {
            const b = balances[a.did]
            if (b && !b.error) {
              return { ...a, liquid_balance: parseFloat(b.balance || '0') }
            }
            return a
          })
        } catch (balErr) {
          // Non-fatal: fall back to registry DB liquid_balance (may show 0)
          log.warn('fetchMyAgents: TEG balance enrichment failed, liquid may be stale', balErr)
        }
      }

      // Update current page if provided
      if (page !== undefined) {
        currentPage.value = page
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch agents'
      myAgentsFailed.value = true
      console.error('Failed to fetch my agents:', err)
    } finally {
      loading.value = false
    }
  }
  
  async function fetchAgentById(id: string) {
    loading.value = true
    error.value = null
    
    try {
      // First, check if this agent is already in our store
      let existingAgent = agents.value.find(a => {
        // Check all possible ID matches
        return a.did === id || 
               a.id === id || 
               String(a.id) === String(id) ||
               a.card_data?.humanReadableId === id ||
               getAgentIdentifier(a) === id
      })
      
      if (existingAgent) {
        currentAgent.value = existingAgent
        return
      }
      
      // If the ID is numeric, we need to find the agent by loading all agents
      // because the backend expects UUID, not numeric ID
      if (!id.includes(':') && !id.includes('-')) {
        import.meta.env.DEV && console.log('Numeric ID detected, loading all agents to find by ID:', id)
        
        // Load all agents if not already loaded
        if (agents.value.length === 0) {
          await fetchMyAgents()
        }
        
        // Try to find by numeric ID
        existingAgent = agents.value.find(a => 
          String(a.id) === String(id)
        )
        
        if (existingAgent) {
          currentAgent.value = existingAgent
          return
        }
        
        // If still not found, throw a user-friendly error
        throw new Error('Agent not found. Please check the agent list.')
      }
      
      // For UUIDs or DIDs, try the API
      try {
        const fetchedAgent = await agentApi.getById(id)
        
        // Process the fetched agent
        const processedAgent = {
          ...fetchedAgent,
          name: getAgentProperty(fetchedAgent, 'name'),
          description: getAgentProperty(fetchedAgent, 'description'),
          capabilities: fetchedAgent.capabilities || fetchedAgent.card_data?.tags || []
        }
        
        currentAgent.value = processedAgent
      } catch (apiError: any) {
        // If API fails with 422, try loading all agents as fallback
        if (apiError.response?.status === 422) {
          log.warn('API returned 422, trying fallback method')
          await fetchMyAgents()
          existingAgent = agents.value.find(a => 
            a.id === id || a.did === id || getAgentIdentifier(a) === id
          )
          if (existingAgent) {
            currentAgent.value = existingAgent
            return
          }
        }
        throw apiError
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch agent'
      console.error('Error in fetchAgentById:', err)
      // Don't throw the error to avoid navigation issues
    } finally {
      loading.value = false
    }
  }

  async function createAgent(agentData: CreateAgentDto): Promise<Agent> {
    loading.value = true
    error.value = null
    
    try {
      // Real API call
      const newAgent = await agentApi.create(agentData)
      
      // Add to local store
      agents.value.unshift(newAgent)
      
      return newAgent
    } catch (err: any) {
      error.value = err.message || 'Failed to create agent'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function updateAgent(did: string, updates: UpdateAgentDto) {
    loading.value = true
    error.value = null
    
    try {
      const updatedAgent = await agentApi.update(did, updates)
      
      // --- OWL22 OPTION B: Preserve DID across save operations ---
      // The API returns AgentCardRead which has agent_did but not the full Agent shape.
      // We merge the response with the existing agent to preserve DID and other fields.
      const mergedAgent = {
        ...currentAgent.value,  // Preserve existing agent fields (did, id, status, etc.)
        ...updatedAgent,        // Overlay with updated card data
        did: did,               // Always preserve the original DID
        agent_did: did,         // Also set agent_did for consistency
        name: updatedAgent.name || updatedAgent.card_data?.name || currentAgent.value?.name,
        description: updatedAgent.description || updatedAgent.card_data?.description || currentAgent.value?.description,
      }
      // --- END OWL22 ---
      
      // Update local store
      const index = agents.value.findIndex(a => a.did === did)
      if (index !== -1) {
        agents.value[index] = mergedAgent
      }
      
      if (currentAgent.value?.did === did) {
        currentAgent.value = mergedAgent
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to update agent'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function deleteAgent(did: string) {
    loading.value = true
    error.value = null
    
    try {
      await agentApi.delete(did)
      
      // Remove from local store
      agents.value = agents.value.filter(a => a.did !== did)
      
      if (currentAgent.value?.did === did) {
        currentAgent.value = null
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to delete agent'
      throw err
    } finally {
      loading.value = false
    }
  }

  function searchAgents(query: string) {
    searchQuery.value = query
    currentPage.value = 1 // Reset to first page on search
  }

  function setStatusFilter(status: string) {
    statusFilter.value = status
    currentPage.value = 1 // Reset to first page on filter
  }
  
  function setCurrentPage(page: number) {
    currentPage.value = page
  }
  
  function getAgentById(id: string) {
    return agents.value.find(agent => 
      agent.did === id || 
      agent.id === id || 
      getAgentIdentifier(agent) === id
    )
  }
  
  // Get agent metrics
  async function fetchAgentMetrics(did: string) {
    try {
      // Real API call
      return await agentApi.getMetrics(did)
    } catch (err: any) {
      console.error('Failed to fetch agent metrics:', err)
      return null
    }
  }

  // Get agent logs
  async function fetchAgentLogs(did: string, params?: {
    limit?: number
    offset?: number  
    level?: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
    start_time?: string
    end_time?: string
  }) {
    try {
      return await agentApi.getLogs(did, params)
    } catch (err: any) {
      console.error('Failed to fetch agent logs:', err)
      throw err
    }
  }
  
  // Download agent logs
  async function downloadAgentLogs(did: string, params?: {
    level?: string
    start_time?: string
    end_time?: string
  }) {
    try {
      const blob = await agentApi.downloadLogs(did, params)
      
      // Create download link
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `agent-logs-${did}-${new Date().toISOString().split('T')[0]}.log`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err: any) {
      console.error('Failed to download agent logs:', err)
      throw err
    }
  }

  // 2026-05-08: invoked by globalReset() on logout to clear user-A data
  // before user-B's session starts. See stores/globalReset.ts.
  function $reset() {
    agents.value = []
    loading.value = false
    error.value = null
    myAgentsFailed.value = false
    currentAgent.value = null
    currentPage.value = 1
    searchQuery.value = ''
    statusFilter.value = ''
    totalCount.value = 0
    _includeFederated.value = false
  }

  return {
    // State
    agents,
    loading,
    error,
    myAgentsFailed,
    currentAgent,
    currentPage,
    totalPages,
    searchQuery,
    statusFilter,
    totalCount,
    $reset,
    
    // Getters
    filteredAgents,
    paginatedAgents,
    
    // Actions
    fetchAgents,
    fetchAllForMap,
    fetchMyAgents,
    fetchAgentById,
    createAgent,
    updateAgent,
    deleteAgent,
    searchAgents,
    setStatusFilter,
    setCurrentPage,
    getAgentById,
    fetchAgentMetrics,
    fetchAgentLogs,
    downloadAgentLogs
  }
})
