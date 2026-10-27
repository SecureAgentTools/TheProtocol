import type { AxiosInstance } from 'axios'
import { markReplayed } from '@/services/money/sendOutcome'
import { apiClient } from './client'
import { newIdempotencyKey } from './idempotencyKey'

/** §FESUITE (2026-10-05): each value-moving POST carries its own Idempotency-Key, minted here once per call (see
 *  idempotencyKey.ts). Honoured today by /teg/transfer and /teg/cross-registry-transfer (claimed for 90 s, answered from
 *  the 24 h cache) and /teg/send (passed on to the rail it picks); /teg/system-transfer does not declare it yet. */
const oneSend = (key?: string) => ({ headers: { 'Idempotency-Key': key || newIdempotencyKey() } })

// Cross-Registry interfaces
/**
 * Build #3 (2026-05-07): per-transaction record returned by /teg/transactions.
 *
 * `transaction_type` values seen in production:
 *   transfer | stake | unstake | reward | mint | funding | system | dispute_compensation
 */
export interface TEGTransaction {
  transaction_id: string
  sender_agent_id: string | null
  receiver_agent_id: string
  amount: string
  fee_amount?: string
  status: string
  transaction_type?: string
  timestamp: string
  attached_message?: string | null
  reputation_signal_applied?: boolean
  error_message?: string | null
  // Some legacy responses use 'message' — kept for compatibility
  message?: string
}

export interface CrossRegistryBalance {
  registry_url: string
  registry_name: string
  balance: number
  locked_balance: number
  available_balance: number
  last_synced: string
  status: 'online' | 'offline' | 'error'
}

export interface CrossRegistryBalanceResponse {
  total_balance: number
  total_locked: number
  total_available: number
  balances: CrossRegistryBalance[]
}

export interface CrossRegistryTransfer {
  receiver_did: string
  amount: string
  message?: string
}

export interface CrossRegistryTransferResponse {
  transfer_id: string
  status: 'completed' | 'failed' | 'pending'
  sender_did: string
  receiver_did: string
  amount: string
  source_teg: string
  target_teg: string
  transaction_hash?: string
  error_message?: string
  timestamp: string
}

/**
 * TEG (Token Economic Gateway) API Service
 * Handles all token-related operations via the TEG proxy
 * All endpoints confirmed working via e2e tests (may return 503 if TEG service is down)
 */
export class TegApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Get current user's TEG balance
   * GET /teg/balance
   */
  async getBalance(): Promise<{
    balance: string
    formatted?: string
    symbol?: string
  }> {
    const { data } = await this.client.get('/teg/balance')
    return data
  }

  /**
   * Get fee configuration
   * GET /teg/fees/config
   */
  async getFeesConfig(): Promise<{
    transfer_fee_amount: string
    system_fee_percentage?: number
    minimum_transfer?: string
  }> {
    const { data } = await this.client.get('/teg/fees/config')
    return data
  }

  /**
   * Transfer tokens to another agent
   * POST /teg/transfer
   */
  async transfer(params: {
    receiver_agent_id: string
    amount: string
    message?: string
  }): Promise<{
    transaction_id: string
    status?: string
    timestamp?: string
  }> {
    const { data } = await this.client.post('/teg/transfer', params, oneSend())
    return data
  }

  /**
   * System transfer (for fees, rewards, etc.)
   * POST /teg/system-transfer
   */
  async systemTransfer(params: {
    amount: string
    purpose: string
  }): Promise<{
    transaction_id: string
    status?: string
  }> {
    const { data } = await this.client.post('/teg/system-transfer', params, oneSend())
    return data
  }

  /**
   * Get transaction history (Build #3 — extended types).
   * GET /teg/transactions  (agent JWT required)
   *
   * Backend returns the full TEG transaction record including fee_amount,
   * transaction_type (transfer/stake/unstake/reward/mint/funding/system),
   * and attached_message. Earlier type was a strict subset — extended here
   * so StatementPanel can show fee + type + memo without losing data.
   */
  async getTransactions(params?: {
    limit?: number
    offset?: number
    agent_id?: string
  }): Promise<{
    transactions: TEGTransaction[]
    total: number
    limit: number
    offset: number
  }> {
    const { data } = await this.client.get('/teg/transactions', { params })
    return data
  }

  /** smartSend — auto-routes local / cross-registry 2PC / async / cross-frame FX. Uses the ACTIVE agent JWT
   *  (isAgentEndpoint gates /teg/send). dry_run=true previews the route + fee without moving anything. */
  async smartSend(body: { receiver_did: string; amount: string; message?: string; backend?: string; dry_run?: boolean },
    opts: { idempotencyKey?: string } = {}): Promise<any> {
    // a caller that may ask again after an unknown outcome passes the request's own key (services/money/sendOutcome.ts)
    const res = await this.client.post('/teg/send', body, oneSend(opts.idempotencyKey))
    // §REPATLANE-7: an answer the registry gave again under that key (the first press's payment) says so
    return markReplayed(res.data, res.headers)
  }

  /**
   * Get treasury balance
   * GET /teg/treasury/balance
   */
  async getTreasuryBalance(): Promise<{
    balance: string
    last_updated?: string
  }> {
    const { data } = await this.client.get('/teg/treasury/balance')
    return data
  }

  /**
   * Get policies list
   * GET /teg/policies
   */
  async getPolicies(params?: {
    limit?: number
    offset?: number
    policy_type?: string
  }): Promise<{
    policies: Array<{
      policy_id: string
      policy_code: string
      policy_name: string
      policy_type: string
      description: string
      created_at: string
      is_active: boolean
    }>
    total: number
    limit: number
    offset: number
  }> {
    const { data } = await this.client.get('/teg/policies', { params })
    return data
  }

  /**
   * Create new policy (admin only)
   * POST /teg/policies
   */
  async createPolicy(params: {
    policy_code: string
    policy_name: string
    policy_type: string
    description: string
  }): Promise<{
    policy_id: string
    status: string
  }> {
    const { data } = await this.client.post('/teg/policies', params)
    return data
  }

  /**
   * Log a dispute
   * POST /teg/disputes/log
   */
  async logDispute(params: {
    defendant_agent_did: string
    reason_code: string
    brief_description: string
  }): Promise<{
    dispute_log_id: string
    status: string
  }> {
    const { data } = await this.client.post('/teg/disputes/log', params)
    return data
  }

  /**
   * Submit attestation
   * POST /teg/attestations/submit
   */
  async submitAttestation(params: {
    target_agent_did: string
    attestation_type: string
    attestation_data: any
  }): Promise<{
    attestation_id: string
    status: string
  }> {
    const { data } = await this.client.post('/teg/attestations/submit', params)
    return data
  }

  /**
   * Apply reputation signal to transaction
   * POST /teg/transactions/{transaction_id}/reputation-signal
   */
  async applyReputationSignal(transactionId: string, params: {
    signal_value: number // 1 for positive, -1 for negative
  }): Promise<{
    status: string
    updated_reputation?: number
  }> {
    const { data } = await this.client.post(
      `/teg/transactions/${transactionId}/reputation-signal`,
      params
    )
    return data
  }

  /**
   * Get agent reputation
   * GET /teg/agents/{agent_id}/reputation
   */
  async getAgentReputation(agentId: string): Promise<{
    agent_id: string
    reputation_score: number
    total_signals: number
    positive_signals: number
    negative_signals: number
    last_updated: string
  }> {
    const { data } = await this.client.get(`/teg/agents/${agentId}/reputation`)
    return data
  }

  /**
   * Get cross-registry balance
   * GET /teg/cross-registry/balance
   */
  async getCrossRegistryBalance(
    registryUrls: string[],
    walletAddress: string
  ): Promise<CrossRegistryBalanceResponse> {
    try {
      const { data } = await this.client.get('/teg/cross-registry/balance', {
        params: {
          registry_urls: registryUrls.join(','),
          wallet_address: walletAddress
        }
      })
      return data
    } catch (error: any) {
      console.error('Failed to get cross-registry balance:', error)
      throw error
    }
  }

  /**
   * Transfer tokens across registries (OWL-BRIDGE)
   * POST /teg/cross-registry-transfer
   * Proxies to TEG Layer's cross-TEG 2PC protocol
   */
  async transferCrossRegistry(
    transfer: CrossRegistryTransfer
  ): Promise<CrossRegistryTransferResponse> {
    try {
      const { data } = await this.client.post('/teg/cross-registry-transfer', transfer, oneSend())
      return data
    } catch (error: any) {
      console.error('Failed to initiate cross-registry transfer:', error)
      throw error
    }
  }
}

// Export singleton instance
export const tegApi = new TegApi()
