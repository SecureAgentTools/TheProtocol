import type { AxiosInstance } from 'axios'
import { apiClient } from './client'

export interface Developer {
  id: string
  email: string
  username: string
  created_at: string
  agent_count: number
}

export interface ApiKey {
  id: string
  key?: string // Only returned on creation
  key_prefix: string
  description?: string
  is_active: boolean
  created_at: string
  last_used_at?: string
}

/** Wire shape of GET /developers/me/teg-summary — mirrors schemas.TEGSummaryResponse.
 *  Do NOT invent fields here: a wrong name type-checks and renders a silent 0. */
export interface TegSummary {
  total_liquid_balance: string
  total_staked_balance: string
  total_balance: string
  aggregate_reputation_score: string
  agent_count: number
  active_agent_count: number
}

export interface AgentBalance {
  agent_did: string
  liquid_balance: string
  staked_balance: string
  total_balance: string
}

/**
 * Developer API Service
 * Handles all developer-related operations
 */
export class DeveloperApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Get developer info
   */
  async getMe(): Promise<Developer> {
    const { data } = await this.client.get('/developers/me')
    return data
  }

  /**
   * Create a new API key — §FEPARITY-1: canonical /auth/api-keys, object form
   * (FLOW 9). Accepts the legacy call shapes already used across the app
   * (bare string, or PocketFrame's {name}) plus optional AL-4 narrowing:
   * scopes omitted = full authority ['*']; expires_in_days omitted = server
   * default (365d); 0 = non-expiring.
   */
  async createApiKey(
    nameOrOpts?: string | { name?: string; description?: string },
    opts?: { scopes?: string[]; expires_in_days?: number },
  ): Promise<ApiKey> {
    const key_name = typeof nameOrOpts === 'string'
      ? nameOrOpts
      : (nameOrOpts?.name || nameOrOpts?.description || 'API key')
    const body: Record<string, unknown> = { key_name }
    if (opts?.scopes?.length) body.scopes = opts.scopes
    if (opts?.expires_in_days !== undefined && opts.expires_in_days !== null) body.expires_in_days = opts.expires_in_days
    const { data } = await this.client.post('/auth/api-keys', body)
    return data
  }

  /**
   * List all API keys (canonical /auth/api-keys — carries scopes + expires_at;
   * the legacy /developers/me/apikeys list predates AL-4 and lacks both).
   */
  async listApiKeys(): Promise<ApiKey[]> {
    const { data } = await this.client.get('/auth/api-keys')
    return data
  }

  /**
   * Delete an API key
   */
  async deleteApiKey(keyId: string): Promise<void> {
    await this.client.delete(`/auth/api-keys/${keyId}`)
  }

  /**
   * List developer's agents (paginated; default 200, max 500).
   *
   * 2026-05-09: backend now hard-caps the result set. Calling without a
   * limit gets the most recent 200 agents — this prevents the cascade
   * storm that hit sandbox A when an admin's full 9613-agent fleet was
   * pulled then per-agent-balance-batched (~190 parallel TEG calls).
   */
  async listMyAgents(opts?: { limit?: number; offset?: number }): Promise<Array<{
    agent_did?: string
    did?: string
    name: string
    type?: string
    status: string
    created_at: string
    /** PB-1 backer flare cosmetic — present on AgentRead schema (2026-05-09). */
    flare_tier?: 'sentinel' | 'architect' | 'founder' | null
    flare_granted_at?: string | null
  }>> {
    const params: Record<string, number> = {}
    if (opts?.limit !== undefined) params.limit = opts.limit
    if (opts?.offset !== undefined) params.offset = opts.offset
    const { data } = await this.client.get('/developers/me/agents', { params })
    return data
  }

  /**
   * Get TEG summary
   */
  async getTegSummary(): Promise<TegSummary> {
    const { data } = await this.client.get('/developers/me/teg-summary')
    return data
  }

  /**
   * Get agent balance
   */
  async getAgentBalance(agentDid: string): Promise<AgentBalance> {
    const { data } = await this.client.get(`/developers/me/agents/${agentDid}/balance`)
    return data
  }

  /**
   * Batch get agent balances
   */
  async batchGetAgentBalances(agentDids: string[]): Promise<{
    balances: AgentBalance[]
  }> {
    const { data } = await this.client.post('/developers/me/agents/balances', {
      agent_dids: agentDids
    })
    return data
  }
}

// Export singleton instance
export const developerApi = new DeveloperApi()
