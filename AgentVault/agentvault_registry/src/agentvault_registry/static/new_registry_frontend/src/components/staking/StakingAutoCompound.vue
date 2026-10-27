<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted } from 'vue'
import { useStakingStore } from '@/stores/staking'
import { useAuthStore } from '@/stores/auth'
import { stakingRewardsApi } from '@/services/api/stakingRewards'
import { useCurrency } from '@/composables/useCurrency'
import '@/components/staking/tp-staking.css'

const stakingStore = useStakingStore()
const authStore = useAuthStore()
// FX multi-currency: compound amounts are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

const isUpdating = ref(false)
const agentRewardHistory = ref<any[]>([])
const loadingHistory = ref(false)

// The real payout rate from the dynamic engine — use flexible tier as current base
const currentAPY = computed(() => {
  const tiers = stakingStore.apyTiers
  if (tiers && tiers.length > 0) {
    const flexTier = tiers.find((t: any) => t.lockPeriod === 0)
    return flexTier?.apy ?? 0  // §FESUITE/§BAFIN: never a rate the frame did not state
  }
  return 0
})

const effectiveAPY = computed(() => {
  const apy = currentAPY.value
  if (!stakingStore.autoCompoundSettings?.enabled) return apy
  const r = apy / 100
  const n = 365
  return parseFloat(((Math.pow(1 + r / n, n) - 1) * 100).toFixed(2))
})

const apyDifference = computed(() =>
  parseFloat((effectiveAPY.value - currentAPY.value).toFixed(2))
)

const autoCompoundEnabled = computed({
  get: () => stakingStore.autoCompoundSettings?.enabled || false,
  set: (value) => updateAutoCompound({ enabled: value })
})

// Projection data using the real payout rate
const projectionData = computed(() => {
  const principal = parseFloat(stakingStore.totalStaked || '0')
  if (isNaN(principal) || principal === 0) return []
  const apy = currentAPY.value
  const data = []
  for (let i = 0; i <= 12; i++) {
    const simpleInterest = principal * (1 + (apy / 100) * (i / 12))
    const dailyRate = apy / 100 / 365
    const days = i * 30
    const compoundInterest = principal * Math.pow(1 + dailyRate, days)
    data.push({
      month: i,
      label: i === 0 ? 'Now' : `Month ${i}`,
      withoutCompound: simpleInterest,
      withCompound: compoundInterest,
      difference: compoundInterest - simpleInterest
    })
  }
  return data
})

const maxProjectionValue = computed(() => {
  if (!projectionData.value.length) return 1
  return Math.max(...projectionData.value.map(d => Math.max(d.withoutCompound, d.withCompound)))
})

async function updateAutoCompound(settings: any) {
  isUpdating.value = true
  try {
    await stakingStore.updateAutoCompound(settings)
  } catch (e) {
    console.error('Auto-compound update failed:', e)
  } finally {
    isUpdating.value = false
  }
}

const formatAmt = (v: string | number | undefined) => {
  if (v === undefined || v === null) return '0.00'
  const n = typeof v === 'string' ? parseFloat(v) : v
  return isNaN(n) ? '0.00' : n.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 })
}

const formatDate = (d: string | undefined) => {
  if (!d) return 'Never'
  return new Date(d).toLocaleString(appLocale(), { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

// Load per-agent payout history (for distribution history display)
const loadAgentHistory = async () => {
  const did = authStore.activeAgent?.did || authStore.activeAgent?.agent_did
  if (!did) return
  loadingHistory.value = true
  try {
    const response = await stakingRewardsApi.getAgentRewardHistory(did, { limit: 10 })
    agentRewardHistory.value = response.rewards
  } catch (e) {
    console.error('Failed to load agent reward history:', e)
    agentRewardHistory.value = []
  } finally {
    loadingHistory.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    stakingStore.fetchAutoCompoundSettings(),
    stakingStore.fetchRewardStats(),
    loadAgentHistory()
  ])
})
</script>

<template>
  <div class="staking-view space-y-6">

    <!-- ── Payout Rate Overview ────────────────────────────────── -->
    <div class="sk-card" style="background: rgba(var(--nc-primary-rgb),0.03); border-color: rgba(var(--nc-primary-rgb),0.2);">
      <div class="sk-card-header flex items-center justify-between">
        <div>
          <div class="sk-card-title">⟳ Automatic Relock Settings</div>
          <div class="sk-card-subtitle">Lock each day's payout again, automatically</div>
        </div>
        <label class="sk-toggle">
          <input type="checkbox" v-model="autoCompoundEnabled" :disabled="isUpdating" />
          <div class="sk-toggle__track"></div>
          <span class="ml-3 text-sm font-mono"
            :style="autoCompoundEnabled ? 'color: var(--sk-cyan);' : 'color: var(--sk-text-muted);'"
          >{{ autoCompoundEnabled ? 'Enabled' : 'Disabled' }}</span>
        </label>
      </div>
      <!-- payout rate figures -->
      <div class="p-5 grid grid-cols-3 gap-4">
        <div class="sk-stat-card" style="padding: 1rem;">
          <div class="sk-stat-card__label">Current Rate</div>
          <div class="sk-stat-card__value mono" style="font-size: 1.25rem; color: var(--sk-text);">{{ currentAPY }}%</div>
        </div>
        <div class="sk-stat-card" style="padding: 1rem;">
          <div class="sk-stat-card__label">Rate with Relock</div>
          <div class="sk-stat-card__value mono" style="font-size: 1.25rem; color: var(--sk-cyan);">{{ effectiveAPY }}%</div>
        </div>
        <div class="sk-stat-card" style="padding: 1rem;">
          <div class="sk-stat-card__label">Relock Difference</div>
          <div class="sk-stat-card__value mono" style="font-size: 1.25rem; color: var(--sk-green);">
            +{{ apyDifference }}%
          </div>
        </div>
      </div>
    </div>

    <!-- ── Compound Config (if enabled) ──────────────────── -->
    <div v-if="autoCompoundEnabled" class="sk-card">
      <div class="sk-card-header">
        <div class="sk-card-title">Relock Configuration</div>
      </div>
      <div class="p-5 space-y-3">
        <div class="flex justify-between py-2 border-b" style="border-color: var(--sk-border-dim);">
          <span class="text-sm" style="color: var(--sk-text-muted);">Frequency</span>
          <span class="font-mono text-sm" style="color: var(--sk-text);">{{ stakingStore.autoCompoundSettings?.compound_frequency || 'daily' }}</span>
        </div>
        <div class="flex justify-between py-2 border-b" style="border-color: var(--sk-border-dim);">
          <span class="text-sm" style="color: var(--sk-text-muted);">Min Amount</span>
          <span class="font-mono text-sm" style="color: var(--sk-text);">{{ formatAmt(stakingStore.autoCompoundSettings?.min_compound_amount || '10') }} {{ localCurrency }}</span>
        </div>
        <div class="flex justify-between py-2 border-b" style="border-color: var(--sk-border-dim);">
          <span class="text-sm" style="color: var(--sk-text-muted);">Last Relock</span>
          <span class="font-mono text-sm" style="color: var(--sk-text);">{{ formatDate(stakingStore.autoCompoundSettings?.last_compound_date) }}</span>
        </div>
        <div class="flex justify-between py-2">
          <span class="text-sm" style="color: var(--sk-text-muted);">Total Relocked</span>
          <span class="font-mono text-sm" style="color: var(--sk-green);">{{ formatAmt(stakingStore.autoCompoundSettings?.total_compounded || '0') }} {{ localCurrency }}</span>
        </div>
      </div>
    </div>

    <!-- ── Payout Projection ──────────────────────────── -->
    <div v-if="parseFloat(stakingStore.totalStaked || '0') > 0" class="sk-card">
      <div class="sk-card-header">
        <div class="sk-card-title"><Icon name="mdi:chart-line" /> Payout Projection at Today's Rate</div>
        <div class="sk-card-subtitle">Based on a {{ currentAPY }}% payout rate, which can change and is not promised · {{ parseFloat(stakingStore.totalStaked || '0').toLocaleString(appLocale()) }} {{ localCurrency }} principal</div>
      </div>
      <div class="p-5 space-y-6">
        <!-- 3 / 6 / 12 month grid -->
        <div class="grid grid-cols-3 gap-4">
          <div
            v-for="item in [projectionData[3], projectionData[6], projectionData[12]].filter(Boolean)"
            :key="item.month"
            class="sk-stat-card"
            style="padding: 1rem;"
          >
            <div class="sk-stat-card__label">{{ item.label }}</div>
            <div class="space-y-2 mt-2">
              <div class="flex justify-between items-center">
                <span class="text-xs" style="color: var(--sk-text-muted);">Without Relock</span>
                <span class="font-mono text-xs" style="color: var(--sk-text);">{{ formatAmt(item.withoutCompound) }} {{ localCurrency }}</span>
              </div>
              <div class="flex justify-between items-center">
                <span class="text-xs" style="color: var(--sk-text-muted);">With Relock</span>
                <span class="font-mono text-xs font-bold" style="color: var(--sk-cyan);">{{ formatAmt(item.withCompound) }} {{ localCurrency }}</span>
              </div>
              <div class="flex justify-between items-center pt-1" style="border-top: 1px solid var(--sk-border-dim);">
                <span class="text-xs" style="color: var(--sk-text-muted);">Difference</span>
                <span class="font-mono text-xs" style="color: var(--sk-green);">+{{ formatAmt(item.difference) }} {{ localCurrency }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Bar comparison -->
        <div class="space-y-3">
          <div class="text-xs font-mono" style="color: var(--sk-text-muted);">12-Month Comparison</div>
          <div class="space-y-2">
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span style="color: var(--sk-text-sec);">Without Relock</span>
                <span class="font-mono" style="color: var(--sk-text);">{{ formatAmt(projectionData[12]?.withoutCompound || 0) }} {{ localCurrency }}</span>
              </div>
              <div class="sk-proj-bar-track">
                <div class="sk-proj-bar-fill--base"
                  :style="{ width: ((projectionData[12]?.withoutCompound || 0) / maxProjectionValue * 100) + '%' }">
                </div>
              </div>
            </div>
            <div>
              <div class="flex justify-between text-xs mb-1">
                <span style="color: var(--sk-cyan);">With Relock</span>
                <span class="font-mono" style="color: var(--sk-cyan);">{{ formatAmt(projectionData[12]?.withCompound || 0) }} {{ localCurrency }}</span>
              </div>
              <div class="sk-proj-bar-track">
                <div class="sk-proj-bar-fill--compound"
                  :style="{ width: ((projectionData[12]?.withCompound || 0) / maxProjectionValue * 100) + '%' }">
                </div>
              </div>
            </div>
          </div>
          <div class="text-center pt-2">
            <span class="text-sm font-mono" style="color: var(--sk-green);">
              <Icon name="mdi:flag" /> Difference with Relock: +{{ formatAmt(projectionData[12]?.difference || 0) }} {{ localCurrency }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Distribution History (per-agent) ──────────────── -->
    <div class="sk-card">
      <div class="sk-card-header">
        <div class="sk-card-title"><Icon name="mdi:calendar" /> Distribution History</div>
        <div class="sk-card-subtitle">Daily payouts made to your liquid balance</div>
      </div>

      <div v-if="loadingHistory" class="p-8 text-center text-sm" style="color: var(--sk-text-muted);">
        Loading...
      </div>
      <div v-else-if="agentRewardHistory.length === 0" class="sk-empty">
        <div class="sk-empty__icon"><Icon name="mdi:inbox" /></div>
        <div class="sk-empty__title">No Distributions Yet</div>
        <div class="sk-empty__desc">Payouts are made daily at 00:00 UTC</div>
      </div>
      <div v-else class="overflow-x-auto sk-scrollbar">
        <table class="sk-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Locked Basis</th>
              <th>Payout Rate</th>
              <th>Payout</th>
              <th>Status</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in agentRewardHistory" :key="record.id">
              <td style="color: var(--sk-text-sec); font-size: 0.78rem;">
                {{ formatDate(record.distribution_date) }}
              </td>
              <td>
                <span class="mono text-sm" style="color: var(--sk-text);">
                  {{ parseFloat(record.staked_amount || '0').toLocaleString(appLocale(), {minimumFractionDigits: 2, maximumFractionDigits: 2}) }}
                </span>
                <span class="ml-1 text-xs" style="color: var(--sk-text-muted);">{{ localCurrency }}</span>
              </td>
              <td>
                <span class="mono" style="color: var(--sk-cyan);">{{ parseFloat(record.apy_rate || '0').toFixed(2) }}%</span>
              </td>
              <td>
                <span class="mono font-bold" style="color: var(--sk-green);">
                  +{{ parseFloat(record.reward_amount || '0').toFixed(4) }} {{ localCurrency }}
                </span>
              </td>
              <td>
                <span class="sk-badge"
                  :class="record.status === 'distributed' ? 'sk-badge--distributed' : record.status === 'failed' ? 'sk-badge--failed' : 'sk-badge--pending'">
                  {{ record.status }}
                </span>
              </td>
              <td>
                <span class="text-xs font-mono" style="color: var(--sk-text-muted);">Daily Payout</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── Payout Statistics ──────────────────────────────── -->
    <div class="sk-card" style="background: rgba(168,85,247,0.03); border-color: rgba(168,85,247,0.2);">
      <div class="sk-card-header">
        <div class="sk-card-title">◆ Payout Statistics</div>
      </div>
      <div class="p-5 grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <div class="sk-stat-card__label">Total Distributed</div>
          <div class="mono font-bold" style="color: var(--sk-text); font-size: 1rem;">
            {{ formatAmt(stakingStore.rewardStats?.total_distributed || '0') }} {{ localCurrency }}
          </div>
        </div>
        <div>
          <div class="sk-stat-card__label">Total Relocked</div>
          <div class="mono font-bold" style="color: var(--sk-cyan); font-size: 1rem;">
            {{ formatAmt(stakingStore.rewardStats?.total_compounded || '0') }} {{ localCurrency }}
          </div>
        </div>
        <div>
          <div class="sk-stat-card__label">Average Rate</div>
          <div class="mono font-bold" style="color: var(--sk-text); font-size: 1rem;">
            {{ stakingStore.rewardStats?.average_apy || currentAPY }}%
          </div>
        </div>
        <div>
          <div class="sk-stat-card__label">Next Distribution</div>
          <div class="mono font-bold" style="color: var(--sk-green); font-size: 1rem;">
            00:00 UTC Daily
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
