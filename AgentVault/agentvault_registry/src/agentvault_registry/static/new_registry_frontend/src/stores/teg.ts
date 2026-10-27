import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { tegApi } from '@/services'
import { useAuthStore } from './auth'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('tegStore')

export const useTegStore = defineStore('teg', () => {
  // State
  const balance = ref<string>('0')
  const formattedBalance = ref<string>('0.00')
  const symbol = ref<string>('TEG')
  const transactions = ref<any[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  // Price data
  const priceUSD = ref<number>(0)
  const priceETH = ref<number>(0)
  const change24h = ref<number>(0)
  const marketCap = ref<number>(0)
  
  // Network stats
  const totalSupply = ref<string>('0')
  const circulatingSupply = ref<string>('0')
  const holders = ref<number>(0)
  const transactions24h = ref<number>(0)
  
  // Pagination for transactions
  const currentPage = ref(1)
  const pageSize = ref(20)
  const totalTransactions = ref(0)
  
  // Computed
  const balanceInUSD = computed(() => {
    const balanceNum = parseFloat(formattedBalance.value)
    return (balanceNum * priceUSD.value).toFixed(2)
  })
  
  const totalPages = computed(() => 
    Math.ceil(totalTransactions.value / pageSize.value)
  )
  
  const pendingTransactions = computed(() =>
    transactions.value.filter(tx => tx.status === 'pending')
  )
  
  const hasBalance = computed(() => 
    parseFloat(balance.value) > 0
  )
  
  // Actions
  async function fetchBalance(address?: string) {
    loading.value = true
    error.value = null
    
    try {
      // Real API call - getBalance() no longer needs address parameter
      const data = await tegApi.getBalance()
        
      balance.value = data.balance
      formattedBalance.value = data.formatted ?? formattedBalance.value
      symbol.value = data.symbol ?? symbol.value
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch balance'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function transfer(to: string, amount: string, memo?: string) {
    loading.value = true
    error.value = null
    
    try {
      // Real API call - use receiver_agent_id instead of to
      const result = await tegApi.transfer({ receiver_agent_id: to, amount, message: memo })
      
      // Refresh balance after transfer
      await fetchBalance()
      
      // Add to pending transactions
      const authStore = useAuthStore()
      transactions.value.unshift({
        txHash: result.transaction_id,
        from: authStore.user?.id || '',
        to,
        amount,
        status: 'pending',
        timestamp: new Date().toISOString(),
        memo
      })
      
      return result
    } catch (err: any) {
      error.value = err.message || 'The transfer failed'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchTransactionHistory(page = 1) {
    loading.value = true
    error.value = null
    
    try {
      // Real API call - use getTransactions with offset/limit
      const offset = (page - 1) * pageSize.value
      const response = await tegApi.getTransactions({
        offset,
        limit: pageSize.value
      })
      
      transactions.value = response.transactions
      totalTransactions.value = response.total
      currentPage.value = page
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch transactions'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function fetchTransaction(txHash: string) {
    loading.value = true
    error.value = null
    
    try {
      // No dedicated single-transaction endpoint; search in transaction history
      const response = await tegApi.getTransactions({ limit: 100 })
      const tx = response.transactions.find(t => t.transaction_id === txHash)
      
      // Update in list if exists
      const index = transactions.value.findIndex((t: any) => t.txHash === txHash || t.transaction_id === txHash)
      if (index !== -1 && tx) {
        transactions.value[index] = tx
      }
      
      return tx || null
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch transaction'
      throw err
    } finally {
      loading.value = false
    }
  }
  
  async function estimateFees(to: string, amount: string) {
    try {
      // estimateFees endpoint doesn't exist in new API
      // Return mock data for now
      log.warn('TEG estimateFees endpoint not available, using mock data')
      const transferAmount = parseFloat(amount)
      const baseFee = 0.5
      const percentageFee = transferAmount * 0.001 // 0.1%
      const totalFee = (baseFee + percentageFee).toFixed(2)
      
      return {
        baseFee: baseFee.toString(),
        percentageFee: percentageFee.toFixed(2),
        totalFee,
        estimatedTime: '30 seconds'
      }
    } catch (err: any) {
      error.value = err.message || 'Failed to estimate fees'
      throw err
    }
  }
  
  async function fetchTokenPrice() {
    loading.value = true
    error.value = null
    
    try {
      // getTokenPrice endpoint doesn't exist in new API
      // Use mock data for now
      log.warn('TEG getTokenPrice endpoint not available, using mock data')
      priceUSD.value = 0.85
      priceETH.value = 0.00035
      change24h.value = 5.67
      marketCap.value = 850000000
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch the price'
      // Don't throw, price is not critical
    } finally {
      loading.value = false
    }
  }
  
  async function fetchNetworkStats() {
    loading.value = true
    error.value = null
    
    try {
      // getNetworkStats endpoint doesn't exist in new API
      // Use mock data for now
      log.warn('TEG getNetworkStats endpoint not available, using mock data')
      totalSupply.value = '1000000000'
      circulatingSupply.value = '750000000'
      holders.value = 45678
      transactions24h.value = 12345
    } catch (err: any) {
      error.value = err.message || 'Failed to fetch network stats'
      // Don't throw, stats are not critical
    } finally {
      loading.value = false
    }
  }
  
  async function refreshAll() {
    await Promise.all([
      fetchBalance(),
      fetchTransactionHistory(1),
      fetchTokenPrice(),
      fetchNetworkStats()
    ])
  }
  
  function clearError() {
    error.value = null
  }
  
  function reset() {
    balance.value = '0'
    formattedBalance.value = '0.00'
    symbol.value = 'TEG'
    transactions.value = []
    loading.value = false
    error.value = null
    priceUSD.value = 0
    priceETH.value = 0
    change24h.value = 0
    marketCap.value = 0
    totalSupply.value = '0'
    circulatingSupply.value = '0'
    holders.value = 0
    transactions24h.value = 0
    currentPage.value = 1
    totalTransactions.value = 0
  }
  
  return {
    // State
    balance,
    formattedBalance,
    symbol,
    transactions,
    loading,
    error,
    priceUSD,
    priceETH,
    change24h,
    marketCap,
    totalSupply,
    circulatingSupply,
    holders,
    transactions24h,
    currentPage,
    pageSize,
    totalTransactions,
    
    // Computed
    balanceInUSD,
    totalPages,
    pendingTransactions,
    hasBalance,
    
    // Actions
    fetchBalance,
    transfer,
    fetchTransactionHistory,
    fetchTransaction,
    estimateFees,
    fetchTokenPrice,
    fetchNetworkStats,
    refreshAll,
    clearError,
    reset
  }
})
