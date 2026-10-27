import type { AxiosInstance } from 'axios'
import { apiClient } from './client'

// Balance types
export interface AgentBalance {
  agent_did: string
  liquid_balance: string
  staked_balance: string
  total_balance: string
}

export interface BatchBalanceRequest {
  agent_dids: string[]
}

/**
 * One agent's entry in POST /developers/me/agents/balances (routers/developers.py get_agent_balances_batch): the live
 * TEG liquid balance and the frame's currency. EVERY failure (not owned, suspended or revoked, a TEG refusal, a timeout)
 * comes back as balance "0" WITH an `error`, so an entry is a reading only when `error` is absent: read it first, and
 * render a failed entry as unread, never as 0 (§RAT).
 */
export interface BatchBalanceEntry {
  balance: string
  currency?: string
  error?: string
}

/** The wire shape: the entries sit under `balances`, keyed by DID (at most 50 DIDs per request). */
export interface BatchBalanceResponse {
  balances: Record<string, BatchBalanceEntry>
}

export interface DeveloperInfo {
  id: string
  email: string
  username: string
  created_at: string
  agent_count: number
}

export interface ApiKey {
  id: string
  key: string
  name: string
  created_at: string
  last_used?: string
  permissions?: string[]
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

/**
 * Developer API Service
 * Handles all developer-related API operations
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
   * Get current developer info
   * GET /developers/me
   */
  async getMyInfo(): Promise<DeveloperInfo> {
    const { data } = await this.client.get<DeveloperInfo>('/developers/me')
    return data
  }

  /**
   * Get developer's agents
   * GET /developers/me/agents
   */
  async getMyAgents(): Promise<any[]> {
    const { data } = await this.client.get<any[]>('/developers/me/agents')
    return data
  }

  /**
   * Get balance for a specific agent
   * GET /developers/me/agents/{agent_did}/balance
   */
  async getAgentBalance(agentDid: string): Promise<AgentBalance> {
    const encodedDid = encodeURIComponent(agentDid)
    const { data } = await this.client.get<AgentBalance>(
      `/developers/me/agents/${encodedDid}/balance`
    )
    return data
  }

  /**
   * Get balances for multiple agents in batch
   * POST /developers/me/agents/balances
   */
  async getAgentBalancesBatch(agentDids: string[]): Promise<BatchBalanceResponse> {
    const { data } = await this.client.post<BatchBalanceResponse>(
      '/developers/me/agents/balances',
      { agent_dids: agentDids }
    )
    return data
  }

  /**
   * Get TEG summary for developer
   * GET /developers/me/teg-summary
   */
  async getTegSummary(): Promise<TegSummary> {
    const { data } = await this.client.get<TegSummary>('/developers/me/teg-summary')
    return data
  }

  /**
   * Create new API key
   * POST /developers/me/apikeys
   */
  async createApiKey(params: {
    name: string
    permissions?: string[]
  }): Promise<ApiKey> {
    const { data } = await this.client.post<ApiKey>('/developers/me/apikeys', params)
    return data
  }

  /**
   * List API keys
   * GET /developers/me/apikeys
   */
  async listApiKeys(): Promise<ApiKey[]> {
    const { data } = await this.client.get<ApiKey[]>('/developers/me/apikeys')
    return data
  }

  /**
   * Delete API key
   * DELETE /developers/me/apikeys/{key_id}
   */
  async deleteApiKey(keyId: string): Promise<void> {
    await this.client.delete(`/developers/me/apikeys/${keyId}`)
  }

  /**
   * Revoke an agent (delete from developer's agents)
   * DELETE /developers/me/agents/{agent_did}
   */
  async revokeAgent(agentDid: string): Promise<void> {
    const encodedDid = encodeURIComponent(agentDid)
    await this.client.delete(`/developers/me/agents/${encodedDid}`)
  }
}

// Export singleton instance
export const developerApi = new DeveloperApi()
