import type { AxiosInstance, AxiosRequestConfig } from 'axios'
import { apiClient } from './client'
import { mintAgentTokenAt } from './peerDirect'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentSlug } from '@/services/agentSlug'
import { useLogger } from '@/composables/useLogger'
import type {
  Agent,
  CreateAgentDto,
  UpdateAgentDto,
  PaginatedResponse
} from '@/types'

const log = useLogger('agentApi')

/** What create() returns: the agent, its credentials (shown once) and what the registry said about it. */
export type CreatedAgent = Agent & {
  client_id?: string
  client_secret?: string
  /** completed | partial | deferred | failed | error | not_first_agent | not_eligible (the starting balance) */
  initial_funding_status?: string
  faucet_transaction_id?: string
  /** where these credentials are used (core/public_url.credential_home_url) */
  registry_url?: string
  /** the stored card's id (GET /agent-cards/{id}) */
  agent_card_id?: string
  humanReadableId?: string
}

export interface ResetCredentialsBody { password: string; totp_code?: string; challenge_id?: string }
export interface ResetCredentialsAnswer {
  agent_did: string
  client_id: string
  client_secret: string
  previous_client_id?: string
  status?: string
  warning?: string
  registry_url?: string | null
}

// Agent Log interface
export interface AgentLog {
  id: number
  agent_did: string
  timestamp: string
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
  message: string
  source?: string
  log_metadata?: Record<string, any>
}

/**
 * Agent API Service
 * Handles all agent-related API operations
 */
export class AgentApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Get all public agent cards with pagination
   * Note: This is for public discovery, not for listing your own agents
   */
  async getAll(params?: {
    page?: number
    limit?: number
    search?: string
    status?: string
    include_federated?: boolean
    active_only?: boolean  // OWL24: Explicitly filter deactivated/revoked cards
    include_card_data?: boolean  // Include full card_data for map/universe views
  }): Promise<PaginatedResponse<Agent>> {
    const { data } = await this.client.get<PaginatedResponse<Agent>>('/agent-cards', {
      params
    })
    return data
  }

  /**
   * Get my agents (agents owned by authenticated developer).
   *
   * 2026-05-09: backend now hard-caps the result set (default 200, max 500).
   * Calling with no opts gets the most recent 200 — prevents the 13MB
   * cascade that hit sandbox A when an admin's full 9613-agent fleet was
   * pulled then per-agent-balance-batched (~190 parallel /balances calls).
   *
   * Note: This requires developer JWT authentication.
   */
  async getMyAgents(opts?: { limit?: number; offset?: number; q?: string; topLevelOnly?: boolean; sort?: 'balance' | 'live'; includeDids?: string[] }): Promise<Agent[] | PaginatedResponse<Agent>> {
    const params: Record<string, number | string | boolean> = {}
    if (opts?.limit !== undefined) params.limit = opts.limit
    if (opts?.offset !== undefined) params.offset = opts.offset
    if (opts?.q) params.q = opts.q                              // whole-fleet server search (name/DID)
    if (opts?.topLevelOnly) params.top_level_only = true        // hide spawned sub-agents (hands)
    // §POCKETBRIDGE F12: 'balance' = server-side top-by-liquid_balance.
    // §COCKPITPOLISH P2: 'live' = last_active_at DESC NULLS LAST, i.e. the agents that
    // actually called this registry — the only ordering that puts a working fleet at the
    // top of a picker over a 4,130-agent account. See services/agentLiveness.ts.
    if (opts?.sort) params.sort = opts.sort
    // §agentfinder — force-hydrate these DIDs whatever the recency window holds. This is
    // the only way to resolve an identity you already hold (a pin, a stored credential)
    // over an account whose page cap is 200 of 4,130. ⚠ Server cap is 300 DIDs and the URL
    // is length-sensitive (§DIDCHUNK), so callers slice; this does not chunk for them.
    if (opts?.includeDids?.length) params.include_dids = opts.includeDids.join(',')
    const { data } = await this.client.get<Agent[]>('/developers/me/agents', { params })
    return data
  }

  /**
   * Get a single agent card by DID
   * Note: Backend expects agent card UUID, not DID. 
   * We need to find the correct endpoint or use the agent's card_id instead.
   */
  async getById(agentId: string): Promise<Agent> {
    // humanReadableId contains a slash (e.g. "agentvault-core/pulverizing-percival")
    // FastAPI decodes %2F back to / in path params, breaking routing.
    // Use the /by-hri query-parameter endpoint instead.
    if (agentId.includes('/')) {
      const { data } = await this.client.get<Agent>('/agent-cards/by-hri', {
        params: { hri: agentId }
      })
      return data
    }
    
    // DID, UUID, or integer ID — use path param endpoint directly
    const encodedAgentId = encodeURIComponent(agentId)
    const { data } = await this.client.get<Agent>(`/agent-cards/${encodedAgentId}`)
    return data
  }

  /**
   * Create a new agent via onboarding
   * Note: This requires a bootstrap token first
   *
   * `opts.expectedStatuses` rides on both requests: statuses the caller answers in its own words (a 403 for an
   * unverified developer, a 400 for a refused card), so the client shows no global toast over that sentence.
   */
  async create(dto: CreateAgentDto, opts?: { expectedStatuses?: number[] }): Promise<CreatedAgent> {
    const reqConfig = opts?.expectedStatuses?.length ? { expectedStatuses: opts.expectedStatuses } : {}
    // Quick onboarding (2026-10-09): the humanReadableId is also the endpoint's path segment, so it is a slug of
    // [a-z0-9-] (services/agentSlug.ts); the name lowercased with only whitespace replaced put "#", "?" and "/" there.
    const humanReadableId = agentSlug(dto.name)
    // First, request a bootstrap token
    const bootstrapResponse = await this.client.post<{ bootstrap_token: string }>(
      '/onboard/bootstrap/request-token',
      {
        agent_type_hint: humanReadableId,
        requested_by: 'developer',
        description: dto.description
      },
      reqConfig
    )

    const bootstrapToken = bootstrapResponse.data.bootstrap_token

    // Q-C W7 (2026-05-12): A2A v1.0 native shape. v0.3 fields preserved alongside
    // (`url`, `preferredTransport`, `authSchemes[]`) for the 6-month dual-shape
    // transition (Commander Q5 signoff). Backend canonicalize_card_data is a
    // defense-in-depth no-op when v1.0 fields are already present.
    const serviceUrl = dto.endpoint || `http://localhost:8000/agents/${humanReadableId}`
    const agentCard = {
      protocolVersion: '1.0',
      humanReadableId,
      agentVersion: '1.0.0',
      name: dto.name,
      description: dto.description,
      provider: {
        name: 'TheProtocol Registry',
        url: 'https://www.theprotocol.cloud',
        support_contact: 'support@theprotocol.cloud'
      },
      // A2A v1.0 §4.4.4 — multi-interface support
      supportedInterfaces: [
        { url: serviceUrl, protocolBinding: 'JSONRPC', protocolVersion: '1.0' }
      ],
      // A2A v1.0 §4.5 — named security schemes + per-scheme requirement list
      securitySchemes: {
        api_key: {
          type: 'apiKey',
          in: 'header',
          name: 'X-Api-Key',
          description: 'API key in HTTP header'
        }
      },
      security: [{ api_key: [] }],
      capabilities: {
        streaming: false,
        pushNotifications: true,
        extendedAgentCard: false,
        supportedMessageParts: ['text', 'data']
      },
      // v0.3 backwards-compat fields (kept 6 months per Q5)
      url: serviceUrl,
      preferredTransport: 'JSONRPC',
      authSchemes: [{ scheme: 'apiKey' }],
      tags: dto.capabilities || [],
      skills: []
    }
    
    // Create agent with bootstrap token
    // §pass50.7 — backend returns client_id + client_secret at TOP LEVEL
    // (alongside agent_did, agent_card_name, etc.), NOT nested under
    // `.credentials`. Both shapes accepted defensively for forward-compat.
    const { data } = await this.client.post<{
      agent_did: string
      agent_card_name?: string
      agent_card?: any
      client_id?: string
      client_secret?: string
      credentials?: {
        client_id: string
        client_secret: string
      }
      initial_funding_status?: string
      faucet_transaction_id?: string
      registry_url?: string
      agent_card_id?: string
    }>('/onboard/create_agent',
      {
        agent_did_method: 'theprotocol',
        agent_card: agentCard
      },
      {
        ...reqConfig,
        headers: {
          'Bootstrap-Token': bootstrapToken
        }
      }
    )

    // Pull credentials from either shape (top-level OR nested .credentials)
    const cid = data.client_id || data.credentials?.client_id
    const csec = data.client_secret || data.credentials?.client_secret
    if (cid && csec) {
      import.meta.env.DEV && console.log('Storing credentials for newly created agent:', data.agent_did)
      agentCredentialsStore.storeCredentials({
        did: data.agent_did,
        client_id: cid,
        client_secret: csec,
        name: agentCard.name,
        humanReadableId: agentCard.humanReadableId,
        created_at: new Date().toISOString()
      })
    }
    
    // Transform response to match Agent interface
    return {
      did: data.agent_did,
      name: agentCard.name,
      description: agentCard.description,
      endpoint: agentCard.url,
      capabilities: agentCard.tags,
      status: 'active',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      // Include credentials in response for immediate use. Quick onboarding (2026-10-09): from the top level, where the
      // registry answers them (the nested `.credentials` it never sends made both undefined for every caller).
      client_id: cid,
      client_secret: csec,
      // what the registry said about the agent, which this used to drop
      initial_funding_status: data.initial_funding_status,
      faucet_transaction_id: data.faucet_transaction_id,
      registry_url: data.registry_url,
      agent_card_id: data.agent_card_id,
      humanReadableId: agentCard.humanReadableId,
    } as CreatedAgent
  }

  /**
   * Reset an agent's credentials: POST /onboard/agents/{did}/reset-credentials with the developer's account password
   * (and, for a developer with a second factor, a TOTP code or an approved challenge id). The registry issues a NEW
   * client_id AND client_secret; the old pair stops working at once.
   *
   * The caller answers every refusal in its own words, so none of them gets the client's global error toast (the
   * client's own "Rate Limited" warning on a 429 is the one toast it always shows, beside the caller's sentence); and a
   * 401 here is the step-up answer (`step_up_required`, plus a challenge), never a sign the developer session ended, so
   * the client must not refresh and resend it (a resend mints a second challenge and spends a second attempt of the
   * registry's 3-per-hour limit, which counts every request).
   */
  async resetCredentials(did: string, body: ResetCredentialsBody): Promise<ResetCredentialsAnswer> {
    const payload: Record<string, string> = { password: body.password }
    if (body.totp_code) payload.totp_code = body.totp_code
    if (body.challenge_id) payload.challenge_id = body.challenge_id
    const cfg: AxiosRequestConfig & { _skipLogoutOn401?: boolean } = {
      _skipLogoutOn401: true,
      expectedStatuses: [400, 401, 403, 404, 422, 429],
    }
    const { data } = await this.client.post<ResetCredentialsAnswer>(
      `/onboard/agents/${encodeURIComponent(did)}/reset-credentials`, payload, cfg)
    return data
  }

  /**
   * Update an existing agent card
   * Note: This requires agent authentication (not developer)
   */
  async update(agentId: string, dto: UpdateAgentDto): Promise<Agent> {
    // URL encode the agent DID to handle special characters like colons
    const encodedAgentId = encodeURIComponent(agentId)
    const { data } = await this.client.put<Agent>(`/agent-cards/${encodedAgentId}`, dto)
    return data
  }

  /**
   * Delete an agent
   * Uses the developer endpoint to delete (revoke) an agent
   */
  async delete(agentId: string): Promise<void> {
    // Use the developer endpoint which exists and works
    await this.client.delete(`/developers/me/agents/${agentId}`)
  }

  /**
   * Get agent metrics/stats
   */
  async getMetrics(agentId: string): Promise<any> {
    try {
      // URL encode the agent DID to handle special characters like colons
      const encodedAgentId = encodeURIComponent(agentId)
      
      // Try the metrics endpoint
      const { data } = await this.client.get(`/agent-metrics/${encodedAgentId}`)
      return data
    } catch (error: any) {
      // If 404, return empty metrics
      if (error.response?.status === 404) {
        log.warn('No metrics found for agent:', agentId)
        return {
          total_requests: 0,
          success_rate: 0,
          avg_response_time: 0,
          uptime_percentage: 0,
          last_active: null
        }
      }
      throw error
    }
  }

  /**
   * Search agents across the network
   */
  async search(query: string, filters?: any): Promise<Agent[]> {
    const { data } = await this.client.get<{ items: Agent[] }>('/agent-cards/search', {
      params: {
        q: query,
        ...filters
      }
    })
    return data.items || []
  }

  /**
   * Authenticate as an agent using provided credentials
   * Used for testing credentials before saving them
   */
  async authenticate(agentDid: string, credentials?: {
    client_id: string
    client_secret: string
  }, registryUrl?: string): Promise<{ access_token: string }> {
    // If no credentials provided, try to get from store
    let authCredentials = credentials
    if (!authCredentials) {
      const stored = agentCredentialsStore.getCredentials(agentDid)
      if (!stored) {
        throw new Error('No credentials available for this agent')
      }
      authCredentials = {
        client_id: stored.client_id,
        client_secret: stored.client_secret
      }
      if (!registryUrl) registryUrl = stored.registry_url
    }
    // §BRIDGE R11 #12 — a foreign agent authenticates at its OWN registry.
    let foreignOrigin: string | null = null
    if (registryUrl) {
      try {
        const u = new URL(registryUrl)
        if (u.origin !== window.location.origin) foreignOrigin = u.origin
      } catch { foreignOrigin = null }
    }

    // §FEFRAME W1: the bare client (services/api/peerDirect.ts mintAgentTokenAt). Through `this.client` the interceptor
    // stamped this registry's developer token on the request, so a foreign verification sent it to another registry.
    const data = await mintAgentTokenAt(foreignOrigin, authCredentials.client_id, authCredentials.client_secret || '')
    return { access_token: data.access_token }
  }

  /**
   * Get agent logs
   */
  async getLogs(agentId: string, params?: {
    limit?: number
    offset?: number
    level?: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
    start_time?: string
    end_time?: string
  }): Promise<AgentLog[]> {
    const encodedAgentId = encodeURIComponent(agentId)
    const { data } = await this.client.get<AgentLog[]>(`/agents/${encodedAgentId}/logs`, {
      params
    })
    return data
  }

  /**
   * Download agent logs as a file
   */
  async downloadLogs(agentId: string, params?: {
    level?: string
    start_time?: string
    end_time?: string
  }): Promise<Blob> {
    const encodedAgentId = encodeURIComponent(agentId)
    const response = await this.client.get(`/agents/${encodedAgentId}/logs`, {
      params: {
        ...params,
        limit: 10000 // Get all logs for download
      },
      responseType: 'json'
    })
    
    // Convert logs to a formatted text file
    const logs = response.data as AgentLog[]
    const logText = logs.map(log => 
      `[${new Date(log.timestamp).toISOString()}] ${log.level}: ${log.message}${log.source ? ` (${log.source})` : ''}`
    ).join('\n')
    
    return new Blob([logText], { type: 'text/plain' })
  }
}

// Export singleton instance
export const agentApi = new AgentApi()
