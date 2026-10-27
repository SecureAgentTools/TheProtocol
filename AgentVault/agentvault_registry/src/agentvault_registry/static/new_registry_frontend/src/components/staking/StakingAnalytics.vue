<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted } from 'vue'
import { useStakingStore } from '@/stores/staking'
import { useAuthStore } from '@/stores/auth'
import { stakingRewardsApi } from '@/services/api/stakingRewards'
import { useCurrency } from '@/composables/useCurrency'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import '@/components/staking/tp-staking.css'

const stakingStore = useStakingStore()
// §BAFIN: no payout history and no rate table where this registry pays no payout on locked units (core/staking_gate.py)
const { config: analyticsCfg } = useRegistryConfig()
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No rate or payout figure shows until the registry has
// said payouts are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const ratesOn = computed(() => analyticsCfg.value.staking_rewards_enabled === true)
const authStore = useAuthStore()
// FX multi-currency: locked amounts are this registry's currency (AVT/BVT);
// vote power is currency-neutral (frame-neutral "vote power", locked decision).
const { localCurrency } = useCurrency()

const agentHistory = ref<any[]>([])
const isLoading = ref(true)

const agentDid = computed(() =>
  authStore.activeAgent?.did || authStore.activeAgent?.agent_did || ''
)

const positions = computed(() => stakingStore.activePositions || [])
const tiers = computed(() => stakingStore.apyTiers || [])
const rewardStats = computed(() => stakingStore.rewardStats || null)

// ── Composition chart data ─────────────────────────────────
const compositionData = computed(() => {
  if (!positions.value.length) return []
  const total = positions.value.reduce((s: number, p: any) => s + parseFloat(p.amount || '0'), 0)
  if (total === 0) return []

  const byPeriod: Record<string, number> = {}
  for (const p of positions.value) {
    const label = p.lockPeriod === 0 ? 'Flexible' : p.lockPeriod === 365 ? '1 Year' : `${p.lockPeriod}d`
    byPeriod[label] = (byPeriod[label] || 0) + parseFloat(p.amount || '0')
  }

  const colors = ['var(--nc-primary)', '#10b981', '#f59e0b', '#a855f7', '#3b82f6']
  return Object.entries(byPeriod).map(([label, amount], i) => ({
    label,
    amount,
    pct: (amount / total) * 100,
    color: colors[i % colors.length]
  }))
})

// ── Payouts timeline (last 14 days) ───────────────────────
const rewardTimeline = computed(() => {
  if (!agentHistory.value.length) return []
  return agentHistory.value
    .slice(0, 14)
    .reverse()
    .map(r => ({
      date: new Date(r.distribution_date).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' }),
      amount: parseFloat(r.reward_amount || '0'),
      apy: parseFloat(r.apy_rate || '0')
    }))
})

const maxReward = computed(() =>
  rewardTimeline.value.length ? Math.max(...rewardTimeline.value.map(d => d.amount)) : 1
)

// ── Payout rate table ─────────────────────────────────────────
const apyTableData = computed(() => {
  return tiers.value.map((t: any) => {
    const label = t.lockPeriod === 0 ? 'Flexible' : t.lockPeriod === 365 ? '1 Year' : `${t.lockPeriod} Days`
    const activeAmount = positions.value
      .filter((p: any) => p.lockPeriod === t.lockPeriod)
      .reduce((s: number, p: any) => s + parseFloat(p.amount || '0'), 0)
    return { label, apy: t.apy, activeAmount, hasPosition: activeAmount > 0 }
  })
})

// ── VeToken power — not exposed by lock store, default to 0 safely ─────────
// (veToken power from TEG balance API is not stored in frontend state)
const veTokenPower = computed(() => 0)
const veTokenPct = computed(() => 0)

const formatAmt = (v: string | number | undefined, dp = 2) => {
  if (!v) return '0.' + '0'.repeat(dp)
  const n = typeof v === 'string' ? parseFloat(v) : v
  return isNaN(n) ? '0.00' : n.toLocaleString(appLocale(), { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

onMounted(async () => {
  try {
    await Promise.all([
      stakingStore.fetchMyStakingStats(),
      stakingStore.fetchApyTiers()
    ])
    if (agentDid.value) {
      const response = await stakingRewardsApi.getAgentRewardHistory(agentDid.value, { limit: 30 })
      agentHistory.value = response.rewards || []
    }
  } catch (e) {
    console.error('Analytics load error:', e)
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="staking-view space-y-6">

    <div v-if="isLoading" class="text-center py-10 text-sm" style="color: var(--sk-text-muted);">
      Loading analytics...
    </div>

    <template v-else>

      <!-- ── Row 1: Composition + VeToken ─────────────── -->
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

        <!-- Lock Composition -->
        <div class="sk-card">
          <div class="sk-card-header">
            <div class="sk-card-title">◈ Lock Composition</div>
            <div class="sk-card-subtitle">Portfolio by lock period</div>
          </div>
          <div class="p-5">
            <div v-if="compositionData.length === 0" class="sk-empty" style="padding: 2rem;">
              <div class="sk-empty__icon" style="font-size:2rem;"><Icon name="mdi:creation" /></div>
              <div class="sk-empty__desc">No active positions</div>
            </div>
            <div v-else class="space-y-3">
              <div v-for="item in compositionData" :key="item.label" class="space-y-1">
                <div class="flex justify-between items-center">
                  <span class="font-mono text-xs" :style="`color: ${item.color}`">{{ item.label }}</span>
                  <div class="flex items-center gap-3">
                    <span class="font-mono text-xs" style="color: var(--sk-text);">{{ formatAmt(item.amount) }} {{ localCurrency }}</span>
                    <span class="font-mono text-xs" style="color: var(--sk-text-muted);">{{ item.pct.toFixed(1) }}%</span>
                  </div>
                </div>
                <div class="sk-proj-bar-track">
                  <div :style="`width: ${item.pct}%; background: ${item.color}; height: 100%; border-radius: 9999px;`"></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Governance Power -->
        <div class="sk-card">
          <div class="sk-card-header">
            <div class="sk-card-title"><Icon name="mdi:scale-balance" /> Governance Power</div>
            <div class="sk-card-subtitle">vote influence score</div>
          </div>
          <div class="p-5 space-y-4">
            <!-- Big veToken value -->
            <div class="text-center py-2">
              <div class="font-mono font-bold" style="font-size: 2.5rem; color: var(--sk-cyan);">
                {{ veTokenPower.toFixed(2) }}
              </div>
              <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Vote Power</div>
            </div>
            <!-- Progress bar -->
            <div>
              <div class="flex justify-between text-xs mb-2">
                <span style="color: var(--sk-text-muted);">Your share vs network</span>
                <span class="font-mono" style="color: var(--sk-cyan);">{{ veTokenPct.toFixed(2) }}%</span>
              </div>
              <div class="sk-proj-bar-track" style="height: 0.75rem;">
                <div class="sk-proj-bar-fill--compound" :style="`width: ${veTokenPct}%`"></div>
              </div>
            </div>
            <!-- How it's calculated -->
            <div class="text-xs" style="color: var(--sk-text-muted); line-height: 1.5;">
              vote power = locked {{ localCurrency }} × lock-period multiplier. Longer locks carry quadratic governance weight.
            </div>
            <!-- Stats grid -->
            <div class="grid grid-cols-2 gap-3 pt-2">
              <div style="border-top: 1px solid var(--sk-border-dim); padding-top: 0.75rem;">
                <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Total Locked</div>
                <div class="font-mono font-bold text-sm" style="color: var(--sk-text);">{{ formatAmt(stakingStore.totalStaked) }} {{ localCurrency }}</div>
              </div>
              <div style="border-top: 1px solid var(--sk-border-dim); padding-top: 0.75rem;">
                <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Active Positions</div>
                <div class="font-mono font-bold text-sm" style="color: var(--sk-text);">{{ positions.length }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Row 2: Daily Payouts Chart ──────────────────── -->
      <div v-if="ratesOn" class="sk-card">
        <div class="sk-card-header">
          <div class="sk-card-title"><Icon name="mdi:chart-line" /> Daily Payout History</div>
          <div class="sk-card-subtitle">Last {{ rewardTimeline.length }} distributions · Auto-pushed to balance</div>
        </div>
        <div class="p-5">
          <div v-if="rewardTimeline.length === 0" class="sk-empty" style="padding: 2rem;">
            <div class="sk-empty__icon" style="font-size:2rem;"><Icon name="mdi:inbox" /></div>
            <div class="sk-empty__title">No Payout Data Yet</div>
            <div class="sk-empty__desc">Data appears after first distribution cycle</div>
          </div>
          <div v-else>
            <!-- Bar chart rendered in pure CSS/HTML -->
            <div class="flex items-end gap-1" style="height: 120px; border-bottom: 1px solid var(--sk-border-dim); padding-bottom: 2px;">
              <div
                v-for="(d, i) in rewardTimeline"
                :key="i"
                class="flex-1 rounded-t transition-all"
                :style="{
                  height: `${(d.amount / maxReward) * 100}%`,
                  background: `rgba(var(--nc-primary-rgb), ${0.4 + (d.amount / maxReward) * 0.6})`,
                  minHeight: '2px'
                }"
                :title="`${d.date}: +${d.amount.toFixed(4)} ${localCurrency}`"
              ></div>
            </div>
            <!-- X labels (show every other for space) -->
            <div class="flex items-center gap-1 mt-1">
              <div
                v-for="(d, i) in rewardTimeline"
                :key="i"
                class="flex-1 text-center"
                style="font-size: 0.5rem; color: var(--sk-text-muted); white-space: nowrap; overflow: hidden;"
              >
                {{ i % 2 === 0 ? d.date : '' }}
              </div>
            </div>
            <!-- Summary under chart -->
            <div class="grid grid-cols-3 gap-4 mt-4 pt-4" style="border-top: 1px solid var(--sk-border-dim);">
              <div>
                <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Total (Period)</div>
                <div class="font-mono font-bold text-sm" style="color: var(--sk-green);">
                  +{{ formatAmt(rewardTimeline.reduce((s, d) => s + d.amount, 0), 4) }} {{ localCurrency }}
                </div>
              </div>
              <div>
                <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Daily Avg</div>
                <div class="font-mono font-bold text-sm" style="color: var(--sk-text);">
                  {{ rewardTimeline.length > 0 ? formatAmt(rewardTimeline.reduce((s, d) => s + d.amount, 0) / rewardTimeline.length, 4) : '0.0000' }} {{ localCurrency }}
                </div>
              </div>
              <div>
                <div class="text-xs font-mono" style="color: var(--sk-text-muted);">Best Day</div>
                <div class="font-mono font-bold text-sm" style="color: var(--sk-cyan);">
                  +{{ formatAmt(Math.max(...rewardTimeline.map(d => d.amount)), 4) }} {{ localCurrency }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Row 3: Payout Rate Table ────────────────────────── -->
      <div v-if="ratesOn" class="sk-card">
        <div class="sk-card-header">
          <div class="sk-card-title">◆ Live Payout Rates</div>
          <div class="sk-card-subtitle">Dynamic logistic decay engine · Updated in real time by the locked share</div>
        </div>
        <div class="overflow-x-auto sk-scrollbar">
          <table class="sk-table">
            <thead>
              <tr>
                <th>Lock Period</th>
                <th>Current Rate</th>
                <th>Your Locked</th>
                <th>Daily Rate (on your lock)</th>
                <th>Active</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in apyTableData" :key="row.label" :style="row.hasPosition ? 'opacity: 1;' : 'opacity: 0.6;'">
                <td>
                  <span class="font-mono text-sm" style="color: var(--sk-text);">{{ row.label }}</span>
                </td>
                <td>
                  <span class="font-mono" style="color: var(--sk-cyan);">{{ row.apy }}%</span>
                </td>
                <td>
                  <span class="font-mono text-sm" :style="row.hasPosition ? 'color: var(--sk-text);' : 'color: var(--sk-text-muted);'">
                    {{ row.hasPosition ? formatAmt(row.activeAmount) + ' ' + localCurrency : '—' }}
                  </span>
                </td>
                <td>
                  <span v-if="row.hasPosition" class="font-mono text-sm" style="color: var(--sk-green);">
                    +{{ formatAmt(row.activeAmount * (row.apy / 100 / 365), 4) }} {{ localCurrency }}/day
                  </span>
                  <span v-else class="font-mono text-sm" style="color: var(--sk-text-muted);">—</span>
                </td>
                <td>
                  <span class="sk-badge" :class="row.hasPosition ? 'sk-badge--distributed' : 'sk-badge--pending'">
                    {{ row.hasPosition ? 'Active' : 'Inactive' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- the locked share's circuit breaker -->
        <div v-if="stakingStore.apyMetadata" class="px-5 py-3 flex items-center gap-4 border-t" style="border-color: var(--sk-border-dim);">
          <span class="text-xs font-mono" style="color: var(--sk-text-muted);">Locked share:</span>
          <span class="font-mono text-xs" style="color: var(--sk-text);">{{ stakingStore.apyMetadata.tvl_pct?.toFixed(1) }}%</span>
          <span class="sk-badge" :class="stakingStore.apyMetadata.circuit_breaker ? 'sk-badge--failed' : 'sk-badge--distributed'">
            Circuit Breaker {{ stakingStore.apyMetadata.circuit_breaker ? 'ACTIVE' : 'OK' }}
          </span>
          <span class="text-xs font-mono" style="color: rgba(var(--nc-primary-rgb),0.4);">{{ stakingStore.apyMetadata.engine }}</span>
        </div>
      </div>

    </template>
  </div>
</template>
