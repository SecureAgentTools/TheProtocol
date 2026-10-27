/**
 * Settlements Pinia store — extracted from Settlements.vue (SF7, 2026-05-06).
 *
 * State + getters + actions for cross-registry dispute settlements.
 * Mirrors the shape of stores/disputes.ts so the two views feel cohesive.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  settlementsApi,
  type Settlement,
  type SettlementStats,
  type PeerSlashConfig,
} from '@/services/api/settlements'

export const useSettlementsStore = defineStore('settlements', () => {
  // -- state --
  const settlements = ref<Settlement[]>([])
  const stats = ref<SettlementStats | null>(null)
  const peerConfigs = ref<PeerSlashConfig[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** §FESUITE (2026-10-05): the last list read failed. The page drew "no settlements" above an error box; it says the read
   *  failed in the list's place now. The list itself is left as it was (a failed refresh keeps what was shown). */
  const listFailed = ref(false)
  const peerConfigError = ref<string | null>(null)
  const filter = ref<'all' | 'pending' | 'settled' | 'failed'>('all')

  // -- getters --
  const filteredSettlements = computed<Settlement[]>(() => {
    const f = filter.value
    if (f === 'all') return settlements.value
    if (f === 'pending') {
      return settlements.value.filter(s =>
        ['PENDING_SLASH', 'SLASHING', 'PENDING_ADMIN_APPROVAL'].includes(s.status)
      )
    }
    if (f === 'settled') {
      return settlements.value.filter(s => ['SETTLED', 'SLASHED'].includes(s.status))
    }
    if (f === 'failed') {
      return settlements.value.filter(s => ['FAILED', 'EXPIRED', 'REJECTED'].includes(s.status))
    }
    return settlements.value
  })

  const stuckSagas = computed<Settlement[]>(() => {
    // Sagas that have exceeded their timeout but haven't terminated.
    const now = Date.now()
    return settlements.value.filter(s => {
      if (!s.saga_timeout_at) return false
      const terminal = ['SETTLED', 'FINALIZED', 'ROLLED_BACK', 'REJECTED', 'EXPIRED'].includes(
        s.saga_state || ''
      ) || ['SETTLED', 'EXPIRED', 'REJECTED'].includes(s.status)
      if (terminal) return false
      return new Date(s.saga_timeout_at).getTime() < now
    })
  })

  // -- actions --
  async function fetchSettlements() {
    loading.value = true
    error.value = null
    try {
      const data = await settlementsApi.list()
      settlements.value = data.settlements || []
      stats.value = data.stats || null
      listFailed.value = false
    } catch (e: any) {
      error.value = e?.message || 'Failed to load settlements'
      listFailed.value = true
      console.error('settlements.fetchSettlements:', e)
    } finally {
      loading.value = false
    }
  }

  async function fetchPeerConfigs() {
    peerConfigError.value = null
    try {
      const data = await settlementsApi.listPeerConfigs()
      peerConfigs.value = data.peers || []
    } catch (e: any) {
      // SF11: surface error instead of console.error-only
      peerConfigError.value = e?.message || 'Failed to load peer configs'
      console.error('settlements.fetchPeerConfigs:', e)
    }
  }

  async function approve(id: string, reason?: string) {
    error.value = null
    try {
      await settlementsApi.approve(id, reason)
      await fetchSettlements()
    } catch (e: any) {
      error.value = e?.message || 'Failed to approve settlement'
      throw e
    }
  }

  async function reject(id: string, reason?: string) {
    error.value = null
    try {
      await settlementsApi.reject(id, reason)
      await fetchSettlements()
    } catch (e: any) {
      error.value = e?.message || 'Failed to reject settlement'
      throw e
    }
  }

  /** true when the registry took the switch; on a refusal the peer keeps its value and `error` says why */
  async function togglePeerAutoSlash(peer: PeerSlashConfig): Promise<boolean> {
    const newEnabled = !peer.auto_slash_enabled
    try {
      await settlementsApi.updatePeerConfig(peer.id, {
        auto_slash_enabled: newEnabled,
        auto_slash_max_avt: peer.auto_slash_max_avt,
      })
      peer.auto_slash_enabled = newEnabled
      return true
    } catch (e: any) {
      error.value = e?.message || 'Failed to update peer config'
      return false
    }
  }

  /** true when the registry took the ceiling; on a refusal the peer keeps its value and `error` says why */
  async function updatePeerThreshold(peer: PeerSlashConfig, value: string): Promise<boolean> {
    const newMax = Math.max(parseInt(value, 10) || 0, 0)
    try {
      await settlementsApi.updatePeerConfig(peer.id, {
        auto_slash_enabled: peer.auto_slash_enabled,
        auto_slash_max_avt: newMax,
      })
      peer.auto_slash_max_avt = newMax
      return true
    } catch (e: any) {
      error.value = e?.message || 'Failed to update threshold'
      return false
    }
  }

  function setFilter(f: 'all' | 'pending' | 'settled' | 'failed') {
    filter.value = f
  }

  // 2026-05-08 P2.2: invoked by globalReset() on logout. See globalReset.ts.
  function $reset() {
    settlements.value = []
    stats.value = null
    peerConfigs.value = []
    loading.value = false
    error.value = null
    listFailed.value = false
    peerConfigError.value = null
    filter.value = 'all'
  }

  return {
    settlements,
    stats,
    peerConfigs,
    loading,
    error,
    listFailed,
    peerConfigError,
    filter,
    $reset,
    filteredSettlements,
    stuckSagas,
    fetchSettlements,
    fetchPeerConfigs,
    approve,
    reject,
    togglePeerAutoSlash,
    updatePeerThreshold,
    setFilter,
  }
})
