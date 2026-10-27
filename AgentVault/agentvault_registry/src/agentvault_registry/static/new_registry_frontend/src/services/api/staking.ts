import type { AxiosInstance } from 'axios'
import { apiClient } from './client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('stakingApi')

/**
 * Lock API service
 * Handles all locking-related operations
 */
export class StakingApi {
  // the shared client is read when a request is made, never captured at module load: the client module and the stores
  // import each other, and a singleton built inside that cycle held no client (§FEFRAME W3.1, clientCapture.test.ts)
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  /**
   * Get locked balance for the current user
   * Uses the /api/v1/staking/balance endpoint
   */
  async getMyStakingStats(): Promise<{
    totalStaked: string
    availableRewards: string
    stakingPositions: Array<{
      id: string
      amount: string
      startDate: string
      lockPeriod: number
      unlockDate?: string | null
      apy: number
      rewards: string
      status?: string
      canUnstake?: boolean
    }>
    /** §FESUITE: false when the positions could not be read (the locked total still can be); never a made-up row. */
    positionsReadable: boolean
  }> {
    try {
      // Get locked balance first
      const balanceResponse = await this.client.get('/staking/balance')
      const balance = balanceResponse.data
      
      // Try to get positions from the new endpoint
      let positions = []
      let positionsReadable = true
      try {
        const positionsResponse = await this.client.get('/staking/my-positions', {
          params: { limit: 100 }
        })
        const positionsData = positionsResponse.data
        
        // Check multiple possible response structures
        if (positionsData) {
          if (Array.isArray(positionsData)) {
            // Direct array response
            positions = positionsData
          } else if (positionsData.positions && Array.isArray(positionsData.positions)) {
            // Nested positions array
            positions = positionsData.positions
          } else if (positionsData.staking_positions && Array.isArray(positionsData.staking_positions)) {
            // Alternative nested structure
            positions = positionsData.staking_positions
          }
          
          // Map positions to expected format
          positions = positions.map((pos: any) => {
            // Handle payouts: backend returns { earned, claimed, available } object
            let rewardsStr = '0'
            if (typeof pos.rewards === 'object' && pos.rewards !== null) {
              rewardsStr = pos.rewards.available || pos.rewards.earned || '0'
            } else if (pos.rewards_earned) {
              rewardsStr = pos.rewards_earned
            } else if (typeof pos.rewards === 'string') {
              rewardsStr = pos.rewards
            }

            return {
              // §FESUITE: the server's id or nothing; an invented id is an Unlock that can only fail
              id: String(pos.id ?? pos.position_id ?? ''),
              amount: pos.amount || pos.staked_amount || '0',
              startDate: pos.startDate || pos.staked_at || pos.start_date || pos.created_at || new Date().toISOString(),
              lockPeriod: pos.lockPeriod || pos.lock_period || pos.lock_period_days || 0,
              unlockDate: pos.unlockDate || pos.unlock_date || null,
              // §FESUITE/§BAFIN: the server's rate, 0 included (it says 0 where no payout is made); `|| 10` turned
              // that 0 into a 10% the frame never offered, on every position, wherever a view showed it
              apy: Number(pos.apy ?? pos.apy_rate ?? 0),
              rewards: rewardsStr,
              status: pos.status || 'active',
              canUnstake: pos.canUnstake ?? pos.can_unstake ?? false
            }
          })
        }
      } catch (posError) {
        log.warn('Could not fetch positions from my-positions endpoint:', posError)
        positionsReadable = false
      }
      // §FESUITE: no position is made up from the locked total any more (it carried a 10% rate, a flexible lock and
      // an id the server never issued); a view that has a total and no positions says the positions are unreadable.
      return {
        totalStaked: balance?.staked_balance || '0',
        availableRewards: balance?.pending_rewards || '0',
        stakingPositions: positions,
        positionsReadable,
      }
    } catch (error: any) {
      // §FESUITE (2026-10-04): the error is thrown on to the caller, which says the read failed; an error line here as
      // well made every failed read a console error on the page (the leave sweep's page-clean red on V0572)
      log.warn('Failed to fetch staking stats:', error)
      // Propagate error so callers can show user-friendly messages
      throw new Error(error.response?.data?.detail || error.message || 'Failed to load lock data')
    }
  }

  /**
   * Get lock status
   * Uses the /api/v1/staking/status endpoint
   * Note: Backend doesn't provide global stats, so we return placeholder data
   */
  async getGlobalStats(): Promise<{
    totalValueLocked: string
    averageApy: number
    totalStakers: number
    rewardsDistributed: string
  }> {
    try {
      // Get lock status for any available info
      const { data } = await this.client.get('/staking/status')
      
      // Return placeholder data since backend doesn't provide global stats
      return {
        totalValueLocked: '0', // Not available from backend
        averageApy: 10, // Default payout rate
        totalStakers: 0, // Not available from backend
        rewardsDistributed: '0' // Not available from backend
      }
    } catch (error) {
      // Return defaults on error
      return {
        totalValueLocked: '0',
        averageApy: 10,
        totalStakers: 0,
        rewardsDistributed: '0'
      }
    }
  }

  /**
   * Lock units
   */
  async stake(params: {
    amount: string
    lockPeriod?: number // in days
  }): Promise<{
    positionId: string
    txHash: string
    estimatedApy: number
  }> {
    // Backend expects amount in the request body
    const { data } = await this.client.post('/staking/stake', {
      amount: params.amount,
      lock_period: params.lockPeriod || 0
    })
    return {
      positionId: data.transaction_id || 'stake-' + Date.now(),
      txHash: data.transaction_id || '',
      estimatedApy: 10 // Default payout rate
    }
  }

  /**
   * Unlock units
   */
  async unstake(positionId: string, amount: string = '0'): Promise<{
    txHash: string
    amount: string
    rewards: string
  }> {
    // §FESUITE: the position the person chose is named, so the server releases that one (a locked one is refused with
    // its unlock date). Without position_id the server walks the unlocked positions oldest first.
    const body: Record<string, string> = { amount }
    if (positionId) body.position_id = positionId
    const { data } = await this.client.post('/staking/unstake', body)
    return {
      txHash: data.transaction_id || '',
      amount: data.amount || amount,
      rewards: '0' // Backend doesn't return payouts
    }
  }

  /**
   * Claim payouts without unlocking
   * Note: Backend doesn't have claim payouts endpoints
   * This is a placeholder that returns mock data
   */
  async claimRewards(positionId?: string): Promise<{
    txHash: string
    amount: string
  }> {
    // Backend doesn't support claim payouts separately from unlocking
    // Return mock response for UI compatibility
    return {
      txHash: `claim-${Date.now()}`,
      amount: '0'
    }
  }

  /**
   * Get the lock tiers from the dynamic payout engine (D5 logistic decay).
   * Returns computed tiers based on current TVL ratio.
   */
  async getApyTiers(): Promise<{
    tiers: Array<{
      lockPeriod: number
      apy: number
      baseApy: number
      lockPremium: number
      minAmount: string
      label: string
      description: string
    }>
    metadata: {
      tvl_pct: number
      total_supply: number
      r_max: number
      circuit_breaker: boolean
      engine: string
    }
  }> {
    try {
      const { data } = await this.client.get('/staking/apy-tiers')
      return data
    } catch (error) {
      log.warn('Failed to fetch APY tiers:', error)   // thrown on: the caller says the read failed
      throw error
    }
  }

  /**
   * Get lock history
   */
  async getStakingHistory(params?: {
    page?: number
    limit?: number
  }): Promise<{
    history: Array<{
      id: string
      type: 'stake' | 'unstake' | 'claim'
      amount: string
      timestamp: string
      txHash: string
      status: string
    }>
    total: number
    page: number
    limit: number
  }> {
    try {
      const limit = params?.limit || 20
      const offset = ((params?.page || 1) - 1) * limit
      
      // Call the new backend endpoint
      const { data } = await this.client.get('/staking/history', {
        params: { limit, offset }
      })
      
      return {
        history: data.history,
        total: data.total,
        page: params?.page || 1,
        limit: limit
      }
    } catch (error: any) {
      // §FESUITE (2026-10-04, agentvault2-09's find): an empty history on ANY failure is a false "none". Only a 404 (a
      // registry without the route) is the server's own "none"; any other failure reaches the caller (the store's
      // fetchStakingHistory already sets its error and rethrows).
      if (error?.response?.status === 404) {
        return { history: [], total: 0, page: params?.page || 1, limit: params?.limit || 20 }
      }
      throw error
    }
  }

  /**
   * Estimate payouts for a lock position.
   * Uses the payout rate data already fetched from the dynamic payout engine.
   * Falls back to 10% if no tier data is available.
   */
  async estimateRewards(params: {
    amount: string
    lockPeriod: number
    currentApy?: number  // Pass from tier data if available
  }): Promise<{
    estimatedApy: number
    estimatedDailyRewards: string
    estimatedTotalRewards: string
  }> {
    const amount = parseFloat(params.amount) || 0
    const lockPeriod = params.lockPeriod || 30
    // §FESUITE/§BAFIN: no tier rate, no estimate (it used to project 10% for any lock on any frame)
    const apy = params.currentApy ?? 0
    
    const dailyRate = apy / 365 / 100
    const estimatedDailyRewards = amount * dailyRate
    const estimatedTotalRewards = estimatedDailyRewards * lockPeriod
    
    return {
      estimatedApy: apy,
      estimatedDailyRewards: estimatedDailyRewards.toFixed(6),
      estimatedTotalRewards: estimatedTotalRewards.toFixed(2)
    }
  }
}

// Export singleton instance
export const stakingApi = new StakingApi()
