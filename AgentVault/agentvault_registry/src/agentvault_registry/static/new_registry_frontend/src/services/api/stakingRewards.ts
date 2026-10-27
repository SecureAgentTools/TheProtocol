import type { AxiosInstance } from 'axios'
import { apiClient } from './client'
import { useAuthStore } from '@/stores/auth'

/**
 * Staking Rewards API Service
 * Handles auto-distribution and rewards management
 */

export interface RewardDistribution {
  id: string
  agent_did: string
  reward_amount: string
  apy_rate: number
  distribution_date: string
  auto_compounded: boolean
  status: 'pending' | 'distributed' | 'claimed' | 'compounded'
  created_at: string
}

export interface AutoCompoundSettings {
  enabled: boolean
  min_compound_amount: string
  compound_frequency: 'daily' | 'weekly' | 'monthly'
  last_compound_date?: string
  total_compounded?: string
}

export interface RewardProjection {
  period: string
  without_compound: number
  with_compound: number
  difference: number
}

export interface StakingTier {
  tier_name: string
  min_stake: string
  max_stake?: string
  base_apy: number
  compound_bonus: number
  effective_apy: number
}

export interface AgentReward {
  id: string
  agent_did: string
  staked_amount: number
  apy_rate: number
  reward_amount: number
  distribution_date: string
  distribution_id: string
  status: 'pending' | 'distributed' | 'failed'
  transaction_hash?: string
  error_message?: string
}

export interface RewardHistoryResponse {
  rewards: AgentReward[]
  total: number
  total_rewards_earned: number
  average_apy: number
  has_more: boolean
}

export interface ManualDistributionRequest {
  distribution_date?: string
  dry_run: boolean
  agent_filter?: {
    min_stake?: number
    tier_names?: string[]
    agent_dids?: string[]
  }
}

export interface ManualDistributionResponse {
  distribution_id: string
  status: 'processing' | 'completed' | 'failed'
  estimated_recipients: number
  estimated_total: number
  processing_time_estimate: number
  message: string
  dry_run_results?: {
    recipients: Array<{
      agent_did: string
      reward_amount: number
    }>
  }
}

export class StakingRewardsApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Get current agent DID
   */
  private getAgentDid(): string {
    const authStore = useAuthStore()
    return authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
  }

  /**
   * Get auto-compound settings for current agent
   */
  async getAutoCompoundSettings(): Promise<AutoCompoundSettings> {
    try {
      const agentDid = this.getAgentDid()
      if (!agentDid) {
        throw new Error('No agent selected')
      }
      
      // Use the correct backend endpoint
      const { data } = await this.client.get(`/staking/rewards/agents/${agentDid}/auto-compound`)
      
      return {
        enabled: data.enabled || false,
        min_compound_amount: data.min_compound_amount || '10',
        compound_frequency: data.compound_frequency || 'daily',
        last_compound_date: data.last_compound_date,
        total_compounded: data.total_compounded || '0'
      }
    } catch (error: any) {
      console.error('Failed to fetch auto-compound settings:', error)
      // Return default settings on error (backend may not have column yet)
      return {
        enabled: false,
        min_compound_amount: '10',
        compound_frequency: 'daily',
        total_compounded: '0'
      }
    }
  }

  /**
   * Update auto-compound settings for current agent
   */
  async updateAutoCompound(settings: Partial<AutoCompoundSettings>): Promise<AutoCompoundSettings> {
    try {
      const agentDid = this.getAgentDid()
      if (!agentDid) {
        throw new Error('No agent selected')
      }
      
      // Use the correct backend endpoint
      const { data } = await this.client.put(
        `/staking/rewards/agents/${agentDid}/auto-compound`,
        settings
      )
      
      return {
        enabled: data.enabled ?? settings.enabled ?? false,
        min_compound_amount: data.min_compound_amount || settings.min_compound_amount || '10',
        compound_frequency: data.compound_frequency || settings.compound_frequency || 'daily',
        last_compound_date: data.last_compound_date,
        total_compounded: data.total_compounded || '0'
      }
    } catch (error: any) {
      console.error('Failed to update auto-compound settings:', error)
      throw error
    }
  }

  /**
   * Get distribution history
   */
  async getDistributionHistory(params?: {
    page?: number
    limit?: number
    start_date?: string
    end_date?: string
  }): Promise<{
    distributions: RewardDistribution[]
    total: number
    page: number
    limit: number
  }> {
    try {
      // Try the backend endpoint
      const { data } = await this.client.get('/staking/rewards/distributions', { params })
      
      if (data && Array.isArray(data)) {
        return {
          distributions: data.map((dist: any) => ({
            id: String(dist.id ?? ''),  // §FESUITE: the server's id or none, never a made-up one
            agent_did: dist.agent_did || this.getAgentDid(),
            reward_amount: dist.reward_amount || '0',
            apy_rate: Number(dist.apy_rate ?? 0),  // §FESUITE/§BAFIN: the rate the server recorded, 0 included
            distribution_date: dist.distribution_date || new Date().toISOString(),
            auto_compounded: dist.auto_compounded || false,
            status: dist.status || 'distributed',
            created_at: dist.created_at || new Date().toISOString()
          })),
          total: data.length,
          page: params?.page || 1,
          limit: params?.limit || 10
        }
      }
      
      return {
        distributions: [],
        total: 0,
        page: 1,
        limit: 10
      }
    } catch (error: any) {
      console.error('Failed to fetch distribution history:', error)
      
      return {
        distributions: [],
        total: 0,
        page: 1,
        limit: 10
      }
    }
  }

  // RFB6 (2026-07-24): auto-distribution methods removed — the
  // /staking/auto-distribution/* endpoints never existed (every call 404'd).

  /**
   * Get agent reward history with enhanced parameters
   */
  async getAgentRewardHistory(
    agentDid?: string,
    params?: {
      limit?: number
      offset?: number
      start_date?: string
      end_date?: string
      status?: 'pending' | 'distributed' | 'failed'
    }
  ): Promise<RewardHistoryResponse> {
    try {
      const did = agentDid || this.getAgentDid()
      if (!did) {
        return {
          rewards: [],
          total: 0,
          total_rewards_earned: 0,
          average_apy: 0,
          has_more: false
        }
      }
      
      const { data } = await this.client.get(
        `/staking/rewards/agents/${did}/history`,
        { params }
      )
      
      // Backend returns List[RewardRecord] (raw array), not wrapped object
      if (Array.isArray(data)) {
        const records = data as any[]
        const totalEarned = records.reduce((sum: number, r: any) => sum + parseFloat(r.reward_amount || '0'), 0)
        const avgApy = records.length > 0
          ? records.reduce((sum: number, r: any) => sum + parseFloat(r.apy_rate || '0'), 0) / records.length
          : 0
        return {
          rewards: records.map((r: any) => ({
            id: r.id,
            agent_did: r.agent_did,
            staked_amount: parseFloat(r.staked_amount || '0'),
            apy_rate: parseFloat(r.apy_rate || '0'),
            reward_amount: parseFloat(r.reward_amount || '0'),
            distribution_date: r.distributed_at || r.created_at || new Date().toISOString(),
            distribution_id: r.distribution_id || r.id,
            status: r.status || 'distributed',
            transaction_hash: r.transaction_hash,
            error_message: r.error_message
          })),
          total: records.length,
          total_rewards_earned: totalEarned,
          average_apy: avgApy,
          has_more: false
        }
      }
      
      return data || {
        rewards: [],
        total: 0,
        total_rewards_earned: 0,
        average_apy: 0,
        has_more: false
      }
    } catch (error: any) {
      console.error('Failed to fetch agent reward history:', error)
      
      // Return empty data on error
      return {
        rewards: [],
        total: 0,
        total_rewards_earned: 0,
        average_apy: 0,
        has_more: false
      }
    }
  }

  /**
   * Get reward statistics
   */
  async getRewardStats(): Promise<{
    total_distributed: string
    total_compounded: string
    average_apy: number
    next_distribution: string
    distribution_frequency: string
  }> {
    try {
      const { data } = await this.client.get('/staking/rewards/stats/summary')
      
      return {
        total_distributed: data.total_distributed || '0',
        total_compounded: data.total_compounded || '0',
        average_apy: Number(data.average_apy ?? 0),
        next_distribution: data.next_distribution || new Date(Date.now() + 86400000).toISOString(),
        distribution_frequency: data.distribution_frequency || 'daily'
      }
    } catch (error: any) {
      console.error('Failed to fetch reward stats:', error)
      
      return {
        total_distributed: '0',
        total_compounded: '0',
        average_apy: 0,
        next_distribution: '',
        distribution_frequency: 'daily'
      }
    }
  }

  /**
   * Estimate rewards for agent
   */
  async estimateRewards(amount?: string): Promise<any> {
    try {
      const agentDid = this.getAgentDid()
      if (!agentDid) {
        return { estimated_rewards: '0', apy: 10 }
      }
      
      const { data } = await this.client.get(`/staking/rewards/estimate/${agentDid}`, {
        params: { amount }
      })
      
      return data
    } catch (error) {
      console.error('Failed to estimate rewards:', error)
      return { estimated_rewards: '0', apy: 10 }
    }
  }

  /**
   * Get reward projections with compound calculations
   */
  async getRewardProjections(params: {
    amount: string
    lock_period: number
    compound_enabled: boolean
  }): Promise<RewardProjection[]> {
    // Always calculate locally for projections
    return this.calculateLocalProjections(params)
  }

  /**
   * Get staking tiers
   */
  async getStakingTiers(): Promise<StakingTier[]> {
    try {
      const { data } = await this.client.get('/staking/rewards/apy-tiers')
      
      if (data && Array.isArray(data)) {
        return data.map((tier: any) => ({
          tier_name: tier.tier_name || tier.name || 'Unknown',
          min_stake: tier.min_stake || tier.min_amount || '0',
          max_stake: tier.max_stake || tier.max_amount,
          base_apy: Number(tier.base_apy ?? tier.apy ?? 0),
          compound_bonus: tier.compound_bonus || 1,
          effective_apy: Number(tier.effective_apy ?? tier.apy ?? 0)
        }))
      }
      
      return this.getDefaultTiers()
    } catch (error) {
      console.error('Failed to fetch staking tiers:', error)
      return this.getDefaultTiers()
    }
  }

  /**
   * Claim pending rewards
   */
  async claimRewards(): Promise<{
    amount_claimed: string
    transaction_id: string
  }> {
    try {
      const { data } = await this.client.post('/staking/claim-rewards')
      
      return {
        amount_claimed: data.amount || data.amount_claimed || '0',
        transaction_id: data.transaction_id || ''  // §FESUITE: no made-up receipt
      }
    } catch (error) {
      console.error('Failed to claim rewards:', error)
      throw error
    }
  }

  /**
   * Trigger manual distribution (admin only)
   */
  async triggerManualDistribution(
    request: ManualDistributionRequest
  ): Promise<ManualDistributionResponse> {
    try {
      const adminKey = localStorage.getItem('admin_key') || ''
      const { data } = await this.client.post(
        '/staking/rewards/distribute/manual',
        request,
        {
          headers: {
            'X-Admin-Key': adminKey
          },
          params: request.distribution_date ? { distribution_date: request.distribution_date.split('T')[0] } : undefined
        }
      )
      
      // Map backend response fields to frontend ManualDistributionResponse type
      // Backend returns: { status, distribution_id, total_distributed, successful, failed, results }
      // Frontend expects: { distribution_id, status, estimated_recipients, estimated_total, message }
      return {
        distribution_id: data.distribution_id || data.id || '',
        status: data.status || 'completed',
        estimated_recipients: data.successful ?? data.total_stakers ?? data.estimated_recipients ?? 0,
        estimated_total: parseFloat(data.total_distributed || data.estimated_total || '0'),
        processing_time_estimate: 0,
        message: data.reason || data.message || `Distribution ${data.status}: ${data.successful ?? 0} recipients, ${data.total_distributed || '0'} TEG`,
        dry_run_results: data.results ? {
          recipients: (data.results || []).filter((r: any) => r.status === 'distributed').map((r: any) => ({
            agent_did: r.agent_did || '',
            reward_amount: parseFloat(r.reward_amount || '0')
          }))
        } : undefined
      }
    } catch (error: any) {
      console.error('Failed to trigger manual distribution:', error)
      
      // Return mock response for testing
      if (error.response?.status === 403) {
        throw new Error('Admin privileges required for this action')
      }
      
      throw error
    }
  }



  /**
   * Calculate compound interest locally
   */
  private calculateCompoundInterest(
    principal: number,
    rate: number,
    compounds: number,
    time: number
  ): number {
    // A = P(1 + r/n)^(nt)
    return principal * Math.pow(1 + rate / compounds, compounds * time)
  }

  /**
   * Calculate local projections
   */
  private calculateLocalProjections(params: {
    amount: string
    lock_period: number
    compound_enabled: boolean
  }): RewardProjection[] {
    const principal = parseFloat(params.amount)
    if (isNaN(principal) || principal === 0) {
      return []
    }
    
    const baseApy = this.getApyForLockPeriod(params.lock_period)
    const rate = baseApy / 100
    
    const projections: RewardProjection[] = []
    const periods = [30, 60, 90, 180, 365] // days

    for (const days of periods) {
      const years = days / 365
      
      // Simple interest (no compound)
      const simpleInterest = principal * rate * years
      const withoutCompound = principal + simpleInterest

      // Compound interest (daily compounding)
      const withCompound = params.compound_enabled
        ? this.calculateCompoundInterest(principal, rate, 365, years)
        : withoutCompound

      projections.push({
        period: `${days} days`,
        without_compound: withoutCompound,
        with_compound: withCompound,
        difference: withCompound - withoutCompound
      })
    }

    return projections
  }

  /**
   * Get APY for lock period
   */
  private getApyForLockPeriod(lockPeriod: number): number {
    if (lockPeriod === 0) return 5
    if (lockPeriod <= 30) return 8
    if (lockPeriod <= 90) return 10
    if (lockPeriod <= 180) return 12
    return 15
  }

  /**
   * Get default staking tiers
   */
  /** §FESUITE/§BAFIN: when the tiers cannot be read there are none to show; it used to invent 5%..8% tiers. */
  private getDefaultTiers(): StakingTier[] {
    return []
  }
}

export const stakingRewardsApi = new StakingRewardsApi()
