<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useStakingStore } from '@/stores/staking'
import { useTegStore } from '@/stores/teg'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { reputationBondApi } from '@/services/api/reputationBond'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useAlive } from '@/composables/useAlive'
import { lockOnlyTiers } from '@/services/stakingLocks'
import { stakingRewardsApi } from '@/services/api/stakingRewards'
import LoadingState from '@/components/common/LoadingState.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import StakingAutoCompound from '@/components/staking/StakingAutoCompound.vue'
import AgentRewardHistory from '@/components/staking/AgentRewardHistory.vue'
import CrossRegistryTransfer from '@/components/staking/CrossRegistryTransfer.vue'
import AdminDistributionPanel from '@/components/staking/AdminDistributionPanel.vue'
import StakingAnalytics from '@/components/staking/StakingAnalytics.vue'
import '@/components/staking/tp-staking.css'

// #2 (2026-05-08): typed shapes for lock API responses. Matches what
// services/api/staking.ts:getMyStakingStats normalizes regardless of backend
// envelope variation (list / { positions } / { staking_positions }).
interface StakingPosition {
  id: string
  amount: string
  startDate: string
  lockPeriod: number
  unlockDate?: string | null
  apy: number
  rewards: string
  status?: string
  canUnstake?: boolean
  // 2026-05-08 — backend may also surface agent_did or staked_amount keys.
  agent_did?: string
  staked_amount?: string
}

interface ApyTier {
  lockPeriod: number
  apy: number
  baseApy: number
  lockPremium: number
  minAmount: string
  label: string
  description: string
}

interface LockPeriodOption {
  value: number
  label: string
  apy: number
  description: string
}

interface CrossRegistryTransferResult {
  success?: boolean
  amount?: string
  target_registry?: string
  message?: string
}

type ActiveTab = 'positions' | 'auto-compound' | 'reward-history' | 'analytics' | 'admin'

interface TabDef {
  id: ActiveTab
  icon: string
  label: string
}

const stakingStore = useStakingStore()
const tegStore = useTegStore()
const uiStore = useUIStore()
const authStore = useAuthStore()
const { t, tp } = useI18n()
// FX multi-currency: locking is denominated in THIS registry's settlement
// currency (AVT on Frame A/B, BVT on Frame C). Replaces the wrong "TEG" unit
// (TEG = the service, not the currency). Strategy §17.2 / §18.2.
const { localCurrency } = useCurrency()

// §BAFIN (2026-10-01): where the registry switches payouts on locked units off (core/staking_gate.py) this view shows
// locks and governance weight only: no rate, no projected payout, no payout tabs.
const { config: registryCfg } = useRegistryConfig()
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const ratesOn = computed(() => registryCfg.value.staking_rewards_enabled === true)

const TABS = computed<ReadonlyArray<TabDef>>(() => {
  // labels are read inside the computed so a language switch re-labels the tabs
  const all: TabDef[] = [
    { id: 'positions', icon: '◈', label: t('stakingView.tabs.positions') },
    { id: 'auto-compound', icon: '⟳', label: t('stakingView.tabs.autoCompound') },
    { id: 'reward-history', icon: '⊞', label: t('stakingView.tabs.rewardHistory') },
    { id: 'analytics', icon: '◆', label: t('stakingView.tabs.analytics') },
    { id: 'admin', icon: '⚙', label: t('stakingView.tabs.admin') },
  ]
  return all.filter(tb => ratesOn.value || (tb.id !== 'auto-compound' && tb.id !== 'reward-history'))
})

const isLoading = ref(true)
const showStakeModal = ref(false)
const showUnstakeModal = ref(false)
const showCrossRegistryTransfer = ref(false)
const selectedPosition = ref<StakingPosition | null>(null)

const stakeAmount = ref('')
const stakeLockPeriod = ref(0)
const stakeError = ref('')
const isStaking = ref(false)

const unstakeAmount = ref('')
const unstakeError = ref('')
const isUnstaking = ref(false)

const activeTab = ref<ActiveTab>('positions')

// isAdmin: true if user has is_admin flag
const isAdmin = computed(() => authStore.user?.is_admin === true)

const currentAgentDid = computed(() =>
  authStore.activeAgent?.did || authStore.activeAgent?.agent_died || ''
)

let refreshInterval: ReturnType<typeof setInterval> | null = null

const lockPeriodOptions = ref<LockPeriodOption[]>([])

const availableBalance = computed(() => tegStore.balance || '0')

// §REPBOND — warn before someone locks everything the bond will need.
const bondCfg = ref<any>(null)
reputationBondApi.getConfig().then(c => { bondCfg.value = c }).catch(() => { bondCfg.value = null })
const bondHint = computed(() => {
  const c = bondCfg.value
  if (!c || c.mode === 'off') return ''
  return tp('stakingView.stakeModal.bondHint', 'Keep at least {amt} {ccy} liquid: an agent that provides services needs it for its reputation bond.', { amt: c.amount, ccy: c.currency })
})

const selectedPeriodAPY = computed(() => {
  const period = lockPeriodOptions.value.find(p => p.value === stakeLockPeriod.value)
  return period?.apy ?? lockPeriodOptions.value[0]?.apy ?? 0  // §FESUITE/§BAFIN: never a rate the frame did not state
})

const projectedRewards = computed(() => {
  if (!stakeAmount.value || parseFloat(stakeAmount.value) <= 0) return '0'
  const amount = parseFloat(stakeAmount.value)
  const dailyRate = selectedPeriodAPY.value / 365 / 100
  const period = stakeLockPeriod.value || 30
  return (amount * dailyRate * period).toFixed(2)
})

const canStake = computed(() => {
  if (!stakeAmount.value || parseFloat(stakeAmount.value) <= 0) return false
  if (parseFloat(stakeAmount.value) > parseFloat(availableBalance.value)) return false
  return true
})

const canUnstake = computed(() => {
  if (!selectedPosition.value) return false
  if (!unstakeAmount.value || parseFloat(unstakeAmount.value) <= 0) return false
  if (parseFloat(unstakeAmount.value) > parseFloat(selectedPosition.value.amount)) return false
  if (isPositionLocked(selectedPosition.value)) return false
  return true
})

const totalValueLocked = computed(() => stakingStore.totalPositionValue)

// ── Real per-agent payout for the "Last Payout Received" card ──────────────
// Source: /staking/rewards/agents/{did}/history — per-agent record with real reward_amount
const agentLastReward = ref<any>(null)
const todaysRewardAmount = computed(() => {
  if (!agentLastReward.value) return '0.0000'
  return parseFloat(agentLastReward.value.reward_amount || '0').toFixed(4)
})

const loadAgentLastReward = async () => {
  const did = authStore.activeAgent?.did || authStore.activeAgent?.agent_did
  if (!did) return
  try {
    const response = await stakingRewardsApi.getAgentRewardHistory(did, { limit: 1 })
    if (response.rewards && response.rewards.length > 0) {
      agentLastReward.value = response.rewards[0]
    }
  } catch (e) {
    // non-critical
  }
}

// Daily rate for a position (calculated client-side)
const getDailyRate = (position: StakingPosition): string => {
  const amount = parseFloat(position.amount || '0')
  const apy = typeof position.apy === 'number' ? position.apy : parseFloat(String(position.apy ?? '0'))
  const daily = amount * (apy / 100 / 365)
  return daily.toFixed(4)
}

const formatCurrency = (value: string | number | undefined) => {
  if (value === undefined || value === null) return '0.00'
  const amount = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(amount)) return '0.00'
  return amount.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const formatDate = (dateString: string) =>
  new Date(dateString).toLocaleDateString(appLocale(), { year: 'numeric', month: 'short', day: 'numeric' })

const getUnlockDate = (position: StakingPosition): string => {
  if (!position.lockPeriod || position.lockPeriod === 0) return t('stakingView.flexible')
  const startDate = new Date(position.startDate)
  const unlockDate = new Date(startDate.getTime() + position.lockPeriod * 24 * 60 * 60 * 1000)
  return formatDate(unlockDate.toISOString())
}

const isPositionLocked = (position: StakingPosition | null | undefined): boolean => {
  if (!position || !position.lockPeriod || position.lockPeriod === 0) return false
  const startDate = new Date(position.startDate)
  const unlockDate = new Date(startDate.getTime() + position.lockPeriod * 24 * 60 * 60 * 1000)
  return new Date() < unlockDate
}

const getTimeUntilUnlock = (position: StakingPosition | null | undefined): string | null => {
  if (!position || !position.lockPeriod || position.lockPeriod === 0) return null
  const startDate = new Date(position.startDate)
  const unlockDate = new Date(startDate.getTime() + position.lockPeriod * 24 * 60 * 60 * 1000)
  const now = new Date()
  if (now >= unlockDate) return null
  const diff = unlockDate.getTime() - now.getTime()
  const days = Math.floor(diff / (24 * 60 * 60 * 1000))
  const hours = Math.floor((diff % (24 * 60 * 60 * 1000)) / (60 * 60 * 1000))
  return days > 0 ? `${days}d ${hours}h` : `${hours}h`
}

const activeLockPeriods = computed(() => {
  const positions = (stakingStore.activePositions || []) as StakingPosition[]
  return new Set(positions.map((p) => p.lockPeriod || 0))
})

const isTierActive = (lockPeriod: number): boolean => activeLockPeriods.value.has(lockPeriod)

const getLockPeriodLabel = (days: number): string => {
  if (days === 0) return t('stakingView.flexible')
  if (days === 365) return t('stakingView.oneYear')
  return `${days} ${t('stakingView.days')}`
}

// §FESUITE (V0575): a failed read of the person's own positions is not "No Active Positions · Stake Now" and 0 locked
const statsFailed = ref(false)
// §FESUITE (V0576): the ledger's total answered and the positions did not: the list is unread, not empty (a zero
// total has no positions); the count and the portfolio value, both derived from the list, read "—"
const positionsUnread = computed(() => !stakingStore.positionsReadable && Number(stakingStore.totalStaked) > 0)
const loadData = async () => {
  try {
    isLoading.value = true
    await Promise.all([
      // §FESUITE (V0575): whether THIS read failed decides what the positions and totals may say
      stakingStore.fetchMyStakingStats().then(() => { statsFailed.value = false }, (e) => { statsFailed.value = true; throw e }),
      stakingStore.fetchGlobalStats(),
      stakingStore.fetchApyTiers(),
      tegStore.fetchBalance()
    ])
    if (stakingStore.apyTiers && stakingStore.apyTiers.length > 0) {
      lockPeriodOptions.value = (stakingStore.apyTiers as ApyTier[]).map((tier) => ({
        value: tier.lockPeriod,
        label: getLockPeriodLabel(tier.lockPeriod),
        apy: tier.apy,
        description: tier.description
      }))
    } else {
      // §BAFIN: payouts off ⇒ no tiers; a lock still buys governance weight, so offer the periods without a rate
      lockPeriodOptions.value = lockOnlyTiers().map((tier) => ({
        value: tier.lockPeriod,
        label: getLockPeriodLabel(tier.lockPeriod),
        apy: 0,
        description: ''
      }))
    }
  } catch (error) {
    console.error('Failed to load staking data:', error)
    uiStore.showError('Error', 'Failed to load lock information')
  } finally {
    isLoading.value = false
  }
}

const openStakeModal = () => {
  stakeAmount.value = ''
  stakeLockPeriod.value = lockPeriodOptions.value[0]?.value ?? 0
  stakeError.value = ''
  showStakeModal.value = true
}

const openUnstakeModal = (position: StakingPosition) => {
  selectedPosition.value = position
  unstakeAmount.value = position.amount
  unstakeError.value = ''
  showUnstakeModal.value = true
}

const handleStake = async () => {
  if (!canStake.value) return
  isStaking.value = true
  stakeError.value = ''
  try {
    await stakingStore.stake({ amount: stakeAmount.value, lockPeriod: stakeLockPeriod.value })
    uiStore.showSuccess('Locked', ratesOn.value
      ? `${stakeAmount.value} ${localCurrency.value} locked, at a ${selectedPeriodAPY.value}% payout rate`
      : `${stakeAmount.value} ${localCurrency.value} locked`)
    showStakeModal.value = false
    await loadData()
  } catch (error: unknown) {
    stakeError.value = error instanceof Error ? error.message : 'Lock failed'
    uiStore.showError('Lock Failed', stakeError.value)
  } finally {
    isStaking.value = false
  }
}

const handleUnstake = async () => {
  if (!canUnstake.value) return
  isUnstaking.value = true
  unstakeError.value = ''
  try {
    if (!selectedPosition.value) throw new Error('No position selected')
    await stakingStore.unstake(selectedPosition.value.id, unstakeAmount.value)
    uiStore.showSuccess('Unlocked', `${unstakeAmount.value} ${localCurrency.value} returned to liquid balance`)
    showUnstakeModal.value = false
    await loadData()
  } catch (error: unknown) {
    unstakeError.value = error instanceof Error ? error.message : 'Unlock failed'
    uiStore.showError('Unlock Failed', unstakeError.value)
  } finally {
    isUnstaking.value = false
  }
}

const handleCrossRegistryComplete = (result: CrossRegistryTransferResult) => {
  tegStore.fetchBalance()
  stakingStore.fetchMyStakingStats()
}

// §FESUITE (the leave sweep): a page left during its first reads starts nothing when they land
const alive = useAlive()
onMounted(async () => {
  await loadData()
  if (!alive()) return
  // Fire secondary fetches — non-critical, guard against missing store methods
  try { stakingStore.fetchAutoCompoundSettings() } catch (e) {}
  try { stakingStore.fetchDistributionHistory() } catch (e) {}
  try { stakingStore.fetchStakingTiers() } catch (e) {}
  try { stakingStore.fetchRewardStats() } catch (e) {}
  // Load per-agent last payout for stat card
  await loadAgentLastReward()
  if (!alive()) return
  refreshInterval = setInterval(loadData, 30000)
})

onUnmounted(() => {
  if (refreshInterval) clearInterval(refreshInterval)
})
</script>

<template>
  <div class="staking-view px-6 py-6">

    <!-- ── Header ─────────────────────────────────────────── -->
    <div class="sk-header mb-8">
      <!-- the buttons wrap under the title on a phone (they ran 50 px past a 412 px screen, fes-20261013T163344Z-71aa) -->
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div class="sk-header__eyebrow">// {{ t('stakingView.header.eyebrow') }}</div>
          <h1 class="sk-header__title" data-tour="stk-hero">
            {{ localCurrency }} <span class="sk-header__title-accent">{{ t('stakingView.header.titleAccent') }}</span>
          </h1>
          <p class="sk-header__subtitle">
            {{ t('stakingView.header.subtitle') }}
          </p>
        </div>
        <div class="flex flex-wrap gap-3 shrink-0">
          <button
            class="sk-btn sk-btn--outline"
            data-tour="stk-xfer"
            @click="showCrossRegistryTransfer = true"
            :disabled="isLoading"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
            {{ t('stakingView.header.crossRegistry') }}
          </button>
          <button
            class="sk-btn sk-btn--primary"
            data-tour="stk-stake-btn"
            @click="openStakeModal"
            :disabled="isLoading"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            {{ t('stakingView.header.stakeTeg') }}
          </button>
        </div>
      </div>
    </div>

    <!-- ── Loading ────────────────────────────────────────── -->
    <LoadingState v-if="isLoading" :message="t('stakingView.loading')" />

    <div v-else class="space-y-6">

      <!-- ── Stat Cards ──────────────────────────────────── -->
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4" data-tour="stk-stats">
        <!-- Total Locked -->
        <div class="sk-stat-card">
          <div class="sk-stat-card__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
          </div>
          <div class="sk-stat-card__label">{{ t('stakingView.stats.totalStaked') }}</div>
          <div class="sk-stat-card__value sk-stat-card__value--cyan mono">
            {{ statsFailed ? '—' : formatCurrency(stakingStore.totalStaked) }}
          </div>
          <div class="sk-stat-card__sub" style="color: var(--nc-primary); opacity:0.6; font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;">{{ localCurrency }}</div>
          <div class="sk-stat-card__sub">{{ statsFailed || !stakingStore.positionsReadable ? '—' : (stakingStore.activePositions?.length || 0) }} {{ t('stakingView.stats.activePositions') }}</div>
        </div>

        <!-- Last Payout Received (per-agent, from real API) -->
        <div v-if="ratesOn" class="sk-stat-card">
          <div class="sk-stat-card__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12.55a11 11 0 0114.08 0M1.42 9a16 16 0 0121.16 0M8.53 16.11a6 6 0 016.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/></svg>
          </div>
          <div class="sk-stat-card__label">{{ t('stakingView.stats.lastReward') }}</div>
          <div class="sk-stat-card__value sk-stat-card__value--green mono">
            {{ todaysRewardAmount }}
          </div>
          <div class="sk-stat-card__sub" style="color: #10b981; opacity:0.6; font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;">{{ localCurrency }}</div>
          <div v-if="agentLastReward" class="sk-stat-card__sub">
            {{ new Date(agentLastReward.distribution_date).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' }) }}
            · {{ parseFloat(agentLastReward.apy_rate || '0').toFixed(2) }}% payout rate
          </div>
          <div v-else class="sk-stat-card__sub">{{ t('stakingView.stats.autoPushDaily') }}</div>
          <button
            class="mt-2 text-xs font-mono"
            style="color: rgba(var(--nc-primary-rgb),0.7); background:none; border:none; cursor:pointer; padding:0;"
            @click="activeTab = 'reward-history'"
          >→ {{ t('stakingView.stats.viewHistory') }}</button>
        </div>

        <!-- Average payout rate -->
        <div v-if="ratesOn" class="sk-stat-card">
          <div class="sk-stat-card__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
          </div>
          <div class="sk-stat-card__label">{{ t('stakingView.stats.baseApy') }}</div>
          <div class="sk-stat-card__value mono" style="color: #e2e8f0;">
            {{ lockPeriodOptions[0]?.apy ?? 0 }}%
          </div>
          <div class="sk-stat-card__sub">
            {{ t('stakingView.stats.upTo') }} <span style="color:var(--nc-primary);">{{ stakingStore.bestApy }}%</span> {{ t('stakingView.stats.withLockBonus') }}
          </div>
          <div v-if="stakingStore.apyMetadata?.tvl_pct !== undefined" class="mt-1">
            <span class="sk-badge" :class="stakingStore.apyMetadata.circuit_breaker ? 'sk-badge--failed' : 'sk-badge--distributed'">
              {{ t('stakingView.stats.lockedShare', 'Locked share') }} {{ stakingStore.apyMetadata.tvl_pct?.toFixed(1) }}%
            </span>
          </div>
        </div>

        <!-- Portfolio Value -->
        <div class="sk-stat-card">
          <div class="sk-stat-card__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          </div>
          <div class="sk-stat-card__label">{{ t('stakingView.stats.portfolioValue') }}</div>
          <div class="sk-stat-card__value mono" style="color: #e2e8f0;">
            {{ statsFailed || !stakingStore.positionsReadable ? '—' : formatCurrency(totalValueLocked) }}
          </div>
          <div class="sk-stat-card__sub" style="color: var(--nc-primary); opacity:0.6; font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;">{{ localCurrency }}</div>
          <div class="sk-stat-card__sub">{{ t('stakingView.stats.stakedPrincipal') }}</div>
        </div>
      </div>

      <!-- ── Lock Tiers ───────────────────────────────────── -->
      <div v-if="ratesOn" class="sk-card" data-tour="stk-tiers">
        <div class="sk-card-header flex items-center justify-between">
          <div>
            <div class="sk-card-title">{{ t('stakingView.tiers.title') }}</div>
            <div class="sk-card-subtitle">{{ t('stakingView.tiers.subtitle') }}</div>
          </div>
          <span v-if="stakingStore.apyMetadata?.engine" class="text-xs font-mono" style="color: rgba(var(--nc-primary-rgb),0.5);">
            dynamic_logistic_decay_v1
          </span>
        </div>
        <div class="p-5">
          <div v-if="lockPeriodOptions.length > 0" class="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div
              v-for="tier in lockPeriodOptions"
              :key="tier.value"
              class="sk-tier-card"
              :class="{ 'sk-tier-card--active': isTierActive(tier.value) }"
            >
              <div class="sk-tier-card__label">{{ tier.label }}</div>
              <div class="sk-tier-card__apy">{{ tier.apy }}%</div>
              <div class="sk-tier-card__desc">{{ tier.description }}</div>
            </div>
          </div>
          <div v-else class="text-center py-4 text-sm" style="color: var(--sk-text-muted);">{{ t('stakingView.tiers.loading') }}</div>
        </div>
      </div>

      <!-- ── Tabs ────────────────────────────────────────── -->
      <div class="sk-card" style="padding: 0; overflow: visible;">
        <div class="sk-tabs px-2" data-tour="stk-tabs">
          <button
            v-for="tab in TABS"
            :key="tab.id"
            class="sk-tab"
            :class="[
              `sk-tab--${tab.id}`,
              activeTab === tab.id ? 'sk-tab--active' : '',
              tab.id === 'admin' ? 'sk-tab--admin' : ''
            ]"
            @click="activeTab = tab.id"
          >
            <span>{{ tab.icon }}</span>
            <span>{{ tab.label }}</span>
            <span
              v-if="tab.id === 'auto-compound' && stakingStore.autoCompoundSettings?.enabled"
              class="sk-badge sk-badge--distributed"
              style="padding: 0.1rem 0.4rem; font-size: 0.55rem;"
            >ON</span>
            <svg
              v-if="tab.id === 'admin' && !isAdmin"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
              style="width:0.85rem;height:0.85rem;opacity:0.5"
              aria-label="Admin access required"
            ><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
          </button>
        </div>

        <!-- Tab body -->
        <div class="p-0">

          <!-- ── POSITIONS TAB ──────────────────────────── -->
          <div v-if="activeTab === 'positions'" data-tour="stk-positions">
            <ReadFailedNotice v-if="(statsFailed || positionsUnread) && !isLoading" :retry="loadData" data-testid="stk-positions-failed" />
            <div v-else-if="!stakingStore.activePositions || stakingStore.activePositions.length === 0">
              <div class="sk-empty">
                <div class="sk-empty__icon"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="24" cy="13" rx="13" ry="5"/><path d="M11 13v10c0 2.8 5.8 5 13 5s13-2.2 13-5V13"/><path d="M11 23v10c0 2.8 5.8 5 13 5s13-2.2 13-5V23"/></svg></div>
                <div class="sk-empty__title">{{ t('stakingView.positions.empty.title') }}</div>
                <div class="sk-empty__desc">{{ t('stakingView.positions.empty.desc') }}</div>
                <button class="sk-btn sk-btn--primary mt-4" @click="openStakeModal">{{ t('stakingView.positions.empty.cta') }}</button>
              </div>
            </div>
            <div v-else class="overflow-x-auto sk-scrollbar">
              <table class="sk-table" aria-label="Active lock positions">
                <caption class="sr-only">{{ t('stakingView.positions.captionActive') }}</caption>
                <thead>
                  <tr>
                    <th>{{ t('stakingView.positions.colAmount') }}</th>
                    <th v-if="ratesOn">{{ t('stakingView.positions.colApy') }}</th>
                    <th v-if="ratesOn">{{ t('stakingView.positions.colDailyRate') }}</th>
                    <th>{{ t('stakingView.positions.colStartDate') }}</th>
                    <th>{{ t('stakingView.positions.colUnlockDate') }}</th>
                    <th>{{ t('stakingView.positions.colStatus') }}</th>
                    <th style="text-align:right;">{{ t('stakingView.positions.colActions') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="position in stakingStore.activePositions" :key="position.id">
                    <td>
                      <span class="mono font-bold" style="color: var(--sk-text);">
                        {{ formatCurrency(position.amount) }}
                      </span>
                      <span class="ml-1 text-xs" style="color: var(--sk-text-muted);">{{ localCurrency }}</span>
                    </td>
                    <td v-if="ratesOn">
                      <span class="mono" style="color: var(--sk-cyan);">{{ position.apy }}%</span>
                    </td>
                    <td v-if="ratesOn">
                      <span class="mono" style="color: var(--sk-green);">+{{ getDailyRate(position) }}/day</span>
                    </td>
                    <td style="color: var(--sk-text-sec); font-size: 0.78rem;">{{ formatDate(position.startDate) }}</td>
                    <td style="color: var(--sk-text-sec); font-size: 0.78rem;">{{ getUnlockDate(position) }}</td>
                    <td>
                      <span class="sk-badge" :class="isPositionLocked(position) ? 'sk-badge--locked' : 'sk-badge--unlocked'">
                        <template v-if="isPositionLocked(position)">
                          {{ t('stakingView.positions.locked') }} ({{ getTimeUntilUnlock(position) }})
                        </template>
                        <template v-else>{{ t('stakingView.positions.unlocked') }}</template>
                      </span>
                    </td>
                    <td style="text-align:right;">
                      <button
                        @click="openUnstakeModal(position)"
                        :disabled="isPositionLocked(position)"
                        class="text-xs font-mono transition-colors"
                        :style="isPositionLocked(position)
                          ? 'color: rgba(239,68,68,0.25); cursor: not-allowed; background:none; border:none;'
                          : 'color: #ef4444; cursor:pointer; background:none; border:none;'"
                      >{{ t('stakingView.positions.unstakeBtn') }}</button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Historical positions -->
            <div v-if="stakingStore.historicalPositions && stakingStore.historicalPositions.length > 0"
                 class="border-t overflow-x-auto" style="border-color: var(--sk-border-dim);">
              <div class="px-5 py-3" style="color: var(--sk-text-muted); font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em;">
                {{ t('stakingView.history.title') }} — {{ stakingStore.historicalPositions.length }} {{ t('stakingView.history.completed') }}
              </div>
              <table class="sk-table" :aria-label="t('stakingView.history.tableLabel')">
                <caption class="sr-only">{{ t('stakingView.history.captionDone') }}</caption>
                <thead>
                  <tr>
                    <th>{{ t('stakingView.positions.colAmount') }}</th>
                    <th v-if="ratesOn">{{ t('stakingView.positions.colApy') }}</th>
                    <th>{{ t('stakingView.history.colLockPeriod') }}</th>
                    <th>{{ t('stakingView.history.colStaked') }}</th>
                    <th>{{ t('stakingView.positions.colStatus') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="position in stakingStore.historicalPositions" :key="position.id" style="opacity: 0.5;">
                    <td><span class="mono">{{ formatCurrency(position.amount) }} {{ localCurrency }}</span></td>
                    <td v-if="ratesOn"><span class="mono" style="color: var(--sk-text-sec);">{{ position.apy }}%</span></td>
                    <td style="color: var(--sk-text-muted);">{{ position.lockPeriod === 0 ? t('stakingView.flexible') : position.lockPeriod + ' ' + t('stakingView.daysShort') }}</td>
                    <td style="color: var(--sk-text-muted); font-size: 0.78rem;">{{ formatDate(position.startDate) }}</td>
                    <td><span class="sk-badge sk-badge--pending">{{ t('stakingView.history.unstaked') }}</span></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- ── AUTO-COMPOUND TAB ───────────────────────── -->
          <div v-else-if="activeTab === 'auto-compound'" class="p-5">
            <StakingAutoCompound />
          </div>

          <!-- ── PAYOUT HISTORY TAB ─────────────────────── -->
          <div v-else-if="activeTab === 'reward-history'" class="p-5">
            <AgentRewardHistory v-if="currentAgentDid" :agent-did="currentAgentDid" />
            <div v-else class="sk-empty">
              <div class="sk-empty__icon"><svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="21" cy="21" r="11"/><path d="M29 29l8 8"/></svg></div>
              <div class="sk-empty__title">{{ t('stakingView.rewardHistory.noAgent') }}</div>
              <div class="sk-empty__desc">{{ t('stakingView.rewardHistory.selectAgent') }}</div>
            </div>
          </div>

          <!-- ── ANALYTICS TAB ──────────────────────────── -->
          <div v-else-if="activeTab === 'analytics'" class="p-5">
            <StakingAnalytics />
          </div>

          <!-- ── ADMIN TAB ───────────────────────────────── -->
          <div v-else-if="activeTab === 'admin'" class="p-5">
            <div class="sk-admin-locked" :style="!isAdmin ? '' : ''">
              <AdminDistributionPanel />
              <!-- Overlay if not admin -->
              <div v-if="!isAdmin" class="sk-admin-locked__overlay">
                <div class="sk-admin-locked__icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:48px;height:48px"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
                </div>
                <div class="sk-admin-locked__msg">
                  {{ t('stakingView.admin.locked') }}<br>
                  <span style="opacity:0.5; font-size: 0.65rem;">{{ t('stakingView.admin.lockedSub') }}</span>
                </div>
              </div>
            </div>
          </div>

        </div><!-- /tab body -->
      </div><!-- /sk-card tabs -->

    </div><!-- /v-else (not loading) -->

    <!-- ── Cross-Registry Transfer Modal ───────────────── -->
    <CrossRegistryTransfer
      v-if="showCrossRegistryTransfer"
      :show="showCrossRegistryTransfer"
      :max-amount="availableBalance"
      @update:show="showCrossRegistryTransfer = $event"
      @transfer-complete="(r) => { handleCrossRegistryComplete(r); showCrossRegistryTransfer = false }"
    />

    <!-- ── Lock Modal ──────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="showStakeModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        style="background: rgba(0,0,0,0.7);"
        @click.self="showStakeModal = false"
      >
        <div class="sk-modal">
          <div class="sk-modal-header">
            <span class="sk-modal-title">{{ t('stakingView.stakeModal.title') }}</span>
            <button @click="showStakeModal = false" style="color: var(--sk-text-muted); background:none; border:none; cursor:pointer;">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
          <div class="sk-modal-body space-y-4">
            <!-- Amount -->
            <div>
              <label class="sk-label">{{ t('stakingView.stakeModal.amountLabel') }}</label>
              <div class="relative">
                <input v-model="stakeAmount" type="number" step="0.01" min="0"
                  :max="availableBalance" placeholder="0.00" class="sk-input sk-input--mono"
                  style="padding-right: 4rem;" />
                <button
                  @click="stakeAmount = availableBalance"
                  class="sk-btn sk-btn--max absolute right-2"
                  style="top: 50%; transform: translateY(-50%);"
                >MAX</button>
              </div>
              <div class="sk-input-hint">{{ t('stakingView.stakeModal.available') }}: {{ formatCurrency(availableBalance) }} {{ localCurrency }}</div>
              <!-- §REPBOND — do not lock the whole grant: the reputation bond needs liquidity -->
              <div v-if="bondHint" class="sk-input-hint" data-testid="sk-bond-hint">{{ bondHint }}</div>
            </div>
            <!-- Lock Period -->
            <div>
              <label for="stakingview-sel-713" class="sk-label">{{ t('stakingView.stakeModal.lockPeriod') }}</label>
              <select id="stakingview-sel-713" v-model="stakeLockPeriod" class="sk-select">
                <option v-for="p in lockPeriodOptions" :key="p.value" :value="p.value">
                  {{ p.label }}<template v-if="ratesOn && p.apy"> — {{ p.apy }}% payout rate</template>
                </option>
              </select>
            </div>
            <!-- Projected -->
            <div v-if="ratesOn" class="sk-info-box">
              <div class="text-xs font-mono mb-1" style="color: var(--sk-text-muted);">{{ t('stakingView.stakeModal.projected') }}</div>
              <div class="font-mono font-bold" style="color: var(--sk-cyan); font-size: 1.1rem;">
                +{{ formatCurrency(projectedRewards) }} {{ localCurrency }}
              </div>
              <div class="text-xs mt-1" style="color: var(--sk-text-muted);">
                {{ selectedPeriodAPY }}% payout rate {{ t('stakingView.stakeModal.for') }} {{ stakeLockPeriod === 0 ? t('stakingView.flexibleLower') : stakeLockPeriod + ' ' + t('stakingView.daysShort') }}
              </div>
            </div>
            <!-- Error -->
            <div v-if="stakeError" class="sk-err-box">{{ stakeError }}</div>
          </div>
          <div class="sk-modal-footer">
            <button class="sk-btn sk-btn--ghost flex-1" @click="showStakeModal = false">{{ t('stakingView.common.cancel') }}</button>
            <button class="sk-btn sk-btn--primary flex-1" @click="handleStake" :disabled="!canStake || isStaking">
              {{ isStaking ? t('stakingView.stakeModal.staking') : t('stakingView.stakeModal.confirmBtn') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Unlock Modal ────────────────────────────────── -->
    <Teleport to="body">
      <div
        v-if="showUnstakeModal"
        class="fixed inset-0 z-50 flex items-center justify-center p-4"
        style="background: rgba(0,0,0,0.7);"
        @click.self="showUnstakeModal = false"
      >
        <div class="sk-modal">
          <div class="sk-modal-header">
            <span class="sk-modal-title">{{ t('stakingView.unstakeModal.title') }}</span>
            <button @click="showUnstakeModal = false" style="color: var(--sk-text-muted); background:none; border:none; cursor:pointer;">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
              </svg>
            </button>
          </div>
          <div class="sk-modal-body space-y-4">
            <!-- Position info -->
            <div class="sk-info-box">
              <div class="flex justify-between items-center mb-1">
                <span class="text-xs font-mono" style="color: var(--sk-text-muted);">{{ t('stakingView.unstakeModal.stakedAmount') }}</span>
                <span class="font-mono font-bold" style="color: var(--sk-text);">
                  {{ formatCurrency(selectedPosition?.amount || '0') }} {{ localCurrency }}
                </span>
              </div>
              <div v-if="ratesOn" class="flex justify-between items-center">
                <span class="text-xs font-mono" style="color: var(--sk-text-muted);">Payout rate</span>
                <span class="font-mono" style="color: var(--sk-cyan);">{{ selectedPosition?.apy }}%</span>
              </div>
            </div>
            <!-- Amount -->
            <div>
              <label class="sk-label">{{ t('stakingView.unstakeModal.amountLabel') }}</label>
              <div class="relative">
                <input v-model="unstakeAmount" type="number" step="0.01" min="0"
                  :max="selectedPosition?.amount" placeholder="0.00" class="sk-input sk-input--mono"
                  style="padding-right: 4rem;" />
                <button
                  @click="unstakeAmount = selectedPosition?.amount"
                  class="sk-btn sk-btn--max absolute right-2"
                  style="top: 50%; transform: translateY(-50%);"
                >MAX</button>
              </div>
            </div>
            <!-- Warning if locked -->
            <div v-if="isPositionLocked(selectedPosition)" class="sk-warn-box">
              <Icon name="mdi:alert" /> {{ t('stakingView.unstakeModal.lockedWarn') }} {{ getTimeUntilUnlock(selectedPosition) }}
            </div>
            <!-- Error -->
            <div v-if="unstakeError" class="sk-err-box">{{ unstakeError }}</div>
          </div>
          <div class="sk-modal-footer">
            <button class="sk-btn sk-btn--ghost flex-1" @click="showUnstakeModal = false">{{ t('stakingView.common.cancel') }}</button>
            <button class="sk-btn sk-btn--danger flex-1" @click="handleUnstake" :disabled="!canUnstake || isUnstaking">
              {{ isUnstaking ? t('stakingView.unstakeModal.unstaking') : t('stakingView.unstakeModal.confirmBtn') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<style scoped>
.staking-view {
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints.
     (Replaces §pass41 defensive bg which blocked the unified ambient.) */
  min-height: 100vh;
  padding-bottom: 4rem;
  position: relative;
  z-index: 1;
}

/* ════════ AAA+ polish — 2026-06-07 (additive; scoped to this view) ════════ */
/* P1 layout/hierarchy — stat & section cards lift / brighten on hover */
.sk-stat-card { transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; position: relative; overflow: hidden; }
.sk-stat-card:hover { transform: translateY(-2px); box-shadow: 0 14px 34px -22px rgba(var(--nc-primary-rgb), 0.55); }
.sk-card { transition: border-color .18s ease, box-shadow .18s ease; }
.sk-card:hover { border-color: var(--sk-border-bright); }
.sk-stat-card::before { content:''; position:absolute; top:0; left:12px; right:12px; height:1px; opacity:0; transition: opacity .2s ease;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb),0.45), transparent); }
.sk-stat-card:hover::before { opacity:1; }
/* P2 motion/states — gentle card entry */
.sk-stat-card { animation: sk-rise .28s ease both; }
@keyframes sk-rise { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform:none; } }
/* P3 data feedback — table rows respond */
.sk-table tbody tr { transition: background .14s ease; }
.sk-table tbody tr:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
/* P4 a11y — visible focus ring everywhere */
.staking-view :is(button, input, select, [tabindex]):focus-visible { outline: 2px solid rgba(var(--nc-primary-rgb), 0.6); outline-offset: 2px; border-radius: 6px; }
/* P5 micro-interactions & cohesion — tabular numerals, tab + button press */
.sk-stat-card, .sk-table td { font-variant-numeric: tabular-nums; }
.sk-tab { transition: all .15s ease; }
.sk-btn--primary, .sk-btn--danger, .sk-btn--outline { transition: transform .12s ease, background .15s ease; }
.sk-btn--primary:not(:disabled):active, .sk-btn--danger:not(:disabled):active, .sk-btn--outline:not(:disabled):active { transform: translateY(1px); }
@media (prefers-reduced-motion: reduce) {
  .sk-stat-card { animation: none !important; }
  .sk-stat-card:hover { transform: none; }
}
</style>
