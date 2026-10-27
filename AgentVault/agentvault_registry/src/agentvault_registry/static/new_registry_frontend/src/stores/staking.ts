import { appLocale } from '@/services/appLocale'
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { stakingApi } from '@/services'
import { stakingRewardsApi, type RewardDistribution, type AutoCompoundSettings, type RewardProjection, type StakingTier } from '@/services/api/stakingRewards'
import { useAuthStore } from './auth'

export const useStakingStore = defineStore('staking', () => {
  // State
  const positions = ref<any[]>([])
  // §FESUITE (V0576): /staking/balance answered and /staking/my-positions did not (stakingApi: positionsReadable false):
  // the total is the ledger's and the list was never read; a view says so instead of "No positions"
  const positionsReadable = ref(true)
  const totalStaked = ref<string>('0')
  const availableRewards = ref<string>('0')
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  // Global stats
  const totalValueLocked = ref<string>('0')
  const averageApy = ref<number>(0)
  const totalStakers = ref<number>(0)
  const rewardsDistributed = ref<string>('0')
  
  // Lock tiers (from the dynamic payout engine)
  const apyTiers = ref<any[]>([])
  const apyMetadata = ref<any>({})
  
  // History
  const stakingHistory = ref<any[]>([])
  const historyPage = ref(1)
  const historyPageSize = ref(20)
  const totalHistoryItems = ref(0)
  
  // Auto-compound and payouts
  const autoCompoundSettings = ref<AutoCompoundSettings>({
    enabled: false,
    min_compound_amount: '10',
    compound_frequency: 'daily'
  })
  const distributionHistory = ref<RewardDistribution[]>([])
  const rewardProjections = ref<RewardProjection[]>([])
  const stakingTiers = ref<StakingTier[]>([])
  const pendingRewards = ref<string>('0')
  const nextDistribution = ref<string>('')
  const rewardStats = ref({
    total_distributed: '0',
    total_compounded: '0',
    average_apy: 10,
    distributions_count: 0,
    last_distribution: ''
  })
  
  // Computed
  const hasActivePositions = computed(() => (positions.value?.length || 0) > 0)
  
  const totalStakedFormatted = computed(() => {
    const amount = parseFloat(totalStaked.value)
    return amount.toLocaleString(appLocale(), { 
      minimumFractionDigits: 2,
      maximumFractionDigits: 2 
    })
  })
  
  const totalRewardsFormatted = computed(() => {
    const amount = parseFloat(availableRewards.value)
    return amount.toLocaleString(appLocale(), { 
      minimumFractionDigits: 2,
      maximumFractionDigits: 2 
    })
  })
  
  const activePositions = computed(() => 
    (positions.value || []).filter(p => 
      parseFloat(p.amount) > 0 && p.status !== 'unstaked'
    )
  )
  
  const historicalPositions = computed(() => 
    (positions.value || []).filter(p => p.status === 'unstaked')
  )
  
  const totalPositionValue = computed(() => {
    const active = activePositions.value
    if (!active || active.length === 0) return '0'
    return active.reduce((total, position) => {
      return total + parseFloat(position.amount) + parseFloat(position.rewards || '0')
    }, 0).toFixed(2)
  })
  
  const bestApy = computed(() => {
    if (!apyTiers.value || apyTiers.value.length === 0) return 0
    return Math.max(...apyTiers.value.map(tier => tier.apy))
  })
  
  const currentTier = computed(() => {
    const stakedAmount = parseFloat(totalStaked.value)
    if (!stakingTiers.value || stakingTiers.value.length === 0) return null
    
    // Find the highest tier the user qualifies for
    const qualifiedTiers = stakingTiers.value.filter(
      tier => stakedAmount >= parseFloat(tier.min_stake)
    )
    
    return qualifiedTiers.length > 0 
      ? qualifiedTiers[qualifiedTiers.length - 1]
      : stakingTiers.value[0]
  })
  
  const effectiveApy = computed(() => {
    if (!currentTier.value) return 0
    return autoCompoundSettings.value.enabled 
      ? currentTier.value.effective_apy 
      : currentTier.value.base_apy
  })
  
  const projectedEarnings = computed(() => {
    const principal = parseFloat(totalStaked.value)
    if (principal === 0 || !effectiveApy.value) return '0'
    
    // Calculate 1 year projection
    const yearlyEarnings = principal * (effectiveApy.value / 100)
    return yearlyEarnings.toFixed(2)
  })
  
  // Actions
  async function fetchMyStakingStats() {
    loading.value = true
    error.value = null
    
    try {
      // Real API call
      const stats = await stakingApi.getMyStakingStats()
      totalStaked.value = stats.totalStaked
      availableRewards.value = stats.availableRewards
      positions.value = stats.stakingPositions
      positionsReadable.value = stats.positionsReadable !== false
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch lock stats'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchGlobalStats() {
    loading.value = true
    error.value = null
    
    try {
      // Real API call
      const stats = await stakingApi.getGlobalStats()
      totalValueLocked.value = stats.totalValueLocked
      averageApy.value = stats.averageApy
      totalStakers.value = stats.totalStakers
      rewardsDistributed.value = stats.rewardsDistributed
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch global stats'
      // Don't throw, global stats are not critical
    } finally {
      loading.value = false
    }
  }
  
  async function stake(params: { amount: string, lockPeriod: number }) {
    loading.value = true
    error.value = null
    
    try {
      // Real API call - stakingApi.stake already expects the params object
      const result = await stakingApi.stake(params)
      
      // Refresh lock figures (updates StakingView)
      await fetchMyStakingStats()

      // FIX: Refresh Agent Selector so it picks up the updated staked_balance
      // from the registry DB (written by the lock router on lock success).
      // Non-awaited so it doesn't block the UI return.
      const authStore = useAuthStore()
      authStore.fetchAvailableAgents().catch(() => {})
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to lock units'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function unstake(positionId: string, amount?: string) {
    loading.value = true
    error.value = null
    
    try {
      // Find the position to get the amount if not provided
      const position = positions.value.find(p => p.id === positionId)
      if (!position) {
        throw new Error('Position not found')
      }
      
      // Use provided amount or fall back to full position amount
      const unstakeAmount = amount || position.amount
      
      // Pass the amount to unlock
      const result = await stakingApi.unstake(positionId, unstakeAmount)
      
      // Remove position from list
      positions.value = positions.value.filter(p => p.id !== positionId)
      
      // Refresh stats
      await fetchMyStakingStats()
      
      return result
    } catch (err: any) {
      error.value = err?.response?.data?.detail || err.message || 'Failed to unlock units'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function claimRewards(positionId?: string) {
    loading.value = true
    error.value = null
    
    try {
      const result = await stakingApi.claimRewards(positionId)
      
      // Refresh stats after claiming
      await fetchMyStakingStats()
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to claim payouts'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchApyTiers() {
    loading.value = true
    error.value = null
    
    try {
      // The dynamic payout engine returns { tiers: [...], metadata: {...} }
      const response = await stakingApi.getApyTiers()
      apyTiers.value = response.tiers || []
      apyMetadata.value = response.metadata || {}
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch lock tiers'
      // Don't throw, lock tiers are not critical
    } finally {
      loading.value = false
    }
  }
  
  async function fetchStakingHistory(page = 1) {
    loading.value = true
    error.value = null
    
    try {
      const response = await stakingApi.getStakingHistory({
        page,
        limit: historyPageSize.value
      })
      
      stakingHistory.value = response.history
      totalHistoryItems.value = response.total
      historyPage.value = page
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch lock history'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function estimateRewards(amount: string, lockPeriod: number) {
    try {
      // Real API call
      // the tier's own rate for this lock (none: the estimate is 0, never an invented one)
      const tier = (apyTiers.value || []).find((t: any) => Number(t.lockPeriod ?? t.lock_period_days) === Number(lockPeriod))
      const estimate = await stakingApi.estimateRewards({ amount, lockPeriod, currentApy: tier ? Number(tier.apy) : undefined })
      return estimate
    } catch (err: any) {
      error.value = err.message || 'Failed to estimate payouts'
      throw err
    }
  }
  
  // Auto-compound and payouts actions
  async function fetchAutoCompoundSettings() {
    try {
      // Get current agent DID from auth store
      const authStore = useAuthStore()
      const agentDid = authStore.activeAgent?.did
      if (agentDid) {
        autoCompoundSettings.value = await stakingRewardsApi.getAutoCompoundSettings()
      }
    } catch (err: any) {
      console.error('Failed to fetch auto-compound settings:', err)
    }
  }
  
  async function updateAutoCompound(settings: Partial<AutoCompoundSettings>) {
    loading.value = true
    error.value = null
    
    try {
      // Get current agent DID from auth store
      const authStore = useAuthStore()
      const agentDid = authStore.activeAgent?.did
      if (!agentDid) {
        throw new Error('No agent selected')
      }
      
      autoCompoundSettings.value = await stakingRewardsApi.updateAutoCompound(settings)
      
      // Recalculate projections if compound status changed
      if (settings.enabled !== undefined) {
        await calculateProjections()
      }
      
      return autoCompoundSettings.value
    } catch (err: any) {
      error.value = err.message || 'Failed to update automatic relock settings'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchDistributionHistory() {
    try {
      const response = await stakingRewardsApi.getDistributionHistory()
      distributionHistory.value = response.distributions
    } catch (err: any) {
      console.error('Failed to fetch distribution history:', err)
    }
  }
  
  async function calculateProjections(lockPeriod = 30) {
    try {
      const principal = totalStaked.value
      
      if (parseFloat(principal) > 0) {
        rewardProjections.value = await stakingRewardsApi.getRewardProjections({
          amount: principal,
          lock_period: lockPeriod,
          compound_enabled: autoCompoundSettings.value.enabled
        })
      }
    } catch (err: any) {
      console.error('Failed to calculate projections:', err)
    }
  }
  
  async function fetchStakingTiers() {
    try {
      stakingTiers.value = await stakingRewardsApi.getStakingTiers()
    } catch (err: any) {
      console.error('Failed to fetch staking tiers:', err)
    }
  }
  
  async function fetchPendingRewards() {
    try {
      // Use existing available payouts
      pendingRewards.value = availableRewards.value
      const stats = await stakingRewardsApi.getRewardStats()
      nextDistribution.value = stats.next_distribution
    } catch (err: any) {
      console.error('Failed to fetch pending rewards:', err)
    }
  }
  
  async function claimPendingRewards() {
    loading.value = true
    error.value = null
    
    try {
      const result = await stakingRewardsApi.claimRewards()
      
      // Update available payouts and refresh stats
      availableRewards.value = '0'
      pendingRewards.value = '0'
      await fetchMyStakingStats()
      await fetchDistributionHistory()
      
      return result
    } catch (err: any) {
      error.value = err.message || 'Failed to claim payouts'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchRewardStats() {
    try {
      const stats = await stakingRewardsApi.getRewardStats()
      rewardStats.value = {
        total_distributed: stats.total_distributed,
        total_compounded: stats.total_compounded,
        average_apy: stats.average_apy,
        distributions_count: 0,
        last_distribution: ''
      }
    } catch (err: any) {
      console.error('Failed to fetch reward stats:', err)
    }
  }
  
  async function refreshAll() {
    await Promise.all([
      fetchMyStakingStats(),
      fetchGlobalStats(),
      fetchApyTiers(),
      fetchAutoCompoundSettings(),
      fetchDistributionHistory(),
      fetchStakingTiers(),
      fetchPendingRewards(),
      fetchRewardStats(),
      calculateProjections()
    ])
  }
  
  function clearError() {
    error.value = null
  }
  
  function reset() {
    positions.value = []
    totalStaked.value = '0'
    availableRewards.value = '0'
    loading.value = false
    error.value = null
    totalValueLocked.value = '0'
    averageApy.value = 0
    totalStakers.value = 0
    rewardsDistributed.value = '0'
    apyTiers.value = []
    apyMetadata.value = {}
    stakingHistory.value = []
    historyPage.value = 1
    totalHistoryItems.value = 0
    distributionHistory.value = []
    rewardProjections.value = []
    stakingTiers.value = []
  }
  
  return {
    // State
    positions,
    positionsReadable,
    totalStaked,
    availableRewards,
    loading,
    error,
    totalValueLocked,
    averageApy,
    totalStakers,
    rewardsDistributed,
    apyTiers,
    apyMetadata,
    historicalPositions,
    stakingHistory,
    historyPage,
    historyPageSize,
    totalHistoryItems,
    autoCompoundSettings,
    distributionHistory,
    rewardProjections,
    stakingTiers,
    pendingRewards,
    nextDistribution,
    rewardStats,
    
    // Computed
    hasActivePositions,
    totalStakedFormatted,
    totalRewardsFormatted,
    activePositions,
    totalPositionValue,
    bestApy,
    currentTier,
    effectiveApy,
    projectedEarnings,
    
    // Actions
    fetchMyStakingStats,
    fetchGlobalStats,
    stake,
    unstake,
    claimRewards,
    fetchApyTiers,
    fetchStakingHistory,
    estimateRewards,
    refreshAll,
    clearError,
    reset,
    fetchAutoCompoundSettings,
    updateAutoCompound,
    fetchDistributionHistory,
    calculateProjections,
    fetchStakingTiers,
    fetchPendingRewards,
    claimPendingRewards,
    fetchRewardStats
  }
})
