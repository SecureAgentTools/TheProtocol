<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, onMounted, watch } from 'vue'
import { stakingRewardsApi } from '@/services/api/stakingRewards'
import { useCurrency } from '@/composables/useCurrency'
import '@/components/staking/tp-staking.css'

interface Props {
  agentDid: string
}
const props = defineProps<Props>()

const rewards = ref<any[]>([])
const isLoading = ref(true)
const error = ref('')
const totalRewards = ref(0)
const totalCount = ref(0)
// FX multi-currency: payout amounts are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

const fetchHistory = async () => {
  if (!props.agentDid) return
  isLoading.value = true
  error.value = ''
  try {
    const response = await stakingRewardsApi.getAgentRewardHistory(props.agentDid, { limit: 100 })
    rewards.value = response.rewards || []
    totalCount.value = response.total || rewards.value.length
    totalRewards.value = rewards.value.reduce((sum: number, r: any) => {
      return sum + parseFloat(r.reward_amount || '0')
    }, 0)
  } catch (e: any) {
    error.value = e.message || 'Failed to load payout history'
    rewards.value = []
  } finally {
    isLoading.value = false
  }
}

const formatDate = (d: string) =>
  new Date(d).toLocaleString(appLocale(), {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })

const formatAmt = (v: string | number) => {
  const n = typeof v === 'string' ? parseFloat(v) : v
  if (isNaN(n)) return '0.0000'
  return n.toFixed(4)
}

watch(() => props.agentDid, fetchHistory)
onMounted(fetchHistory)
</script>

<template>
  <div class="staking-view space-y-4">

    <!-- Summary bar -->
    <div class="grid grid-cols-3 gap-4">
      <div class="sk-stat-card" style="padding: 1rem;">
        <div class="sk-stat-card__label">Total Received</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.15rem; color: var(--sk-green);">
          {{ formatAmt(totalRewards) }}
        </div>
        <div class="sk-stat-card__sub" style="color: var(--sk-green); opacity:0.6; font-family:'IBM Plex Mono',monospace; font-size:0.6rem;">{{ localCurrency }}</div>
      </div>
      <div class="sk-stat-card" style="padding: 1rem;">
        <div class="sk-stat-card__label">Distribution Count</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.15rem;">{{ totalCount }}</div>
      </div>
      <div class="sk-stat-card" style="padding: 1rem;">
        <div class="sk-stat-card__label">Destination</div>
        <div class="text-xs font-mono mt-2" style="color: var(--sk-cyan);">→ Liquid Balance</div>
        <div class="sk-stat-card__sub">Auto-push daily</div>
      </div>
    </div>

    <!-- How payouts work note -->
    <div class="sk-info-box flex gap-3 items-start">
      <span style="font-size:1.1rem; flex-shrink:0;"><Icon name="mdi:radio-tower" /></span>
      <div>
        <div class="font-mono text-xs mb-1" style="color: var(--sk-cyan);">PUSH PAYOUT MODEL</div>
        <div class="text-xs" style="color: var(--sk-text-sec);">
          Payouts on locked units are made to your liquid balance each day at 00:00 UTC by the payout distributor.
          There is nothing to claim: payouts arrive directly in your balance.
        </div>
      </div>
    </div>

    <!-- Table -->
    <div v-if="isLoading" class="text-center py-10 text-sm" style="color: var(--sk-text-muted);">
      Loading payout history...
    </div>

    <div v-else-if="error" class="sk-err-box">{{ error }}</div>

    <div v-else-if="rewards.length === 0" class="sk-empty">
      <div class="sk-empty__icon"><Icon name="mdi:inbox" /></div>
      <div class="sk-empty__title">No Distributions Yet</div>
      <div class="sk-empty__desc">
        Payouts are made daily. The first arrives after 00:00 UTC following your first lock.
      </div>
    </div>

    <div v-else class="sk-table-wrap overflow-x-auto sk-scrollbar">
      <table class="sk-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Locked Basis</th>
            <th>Payout Rate</th>
            <th>Payout Amount</th>
            <th>Destination</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="record in rewards" :key="record.id">
            <td style="color: var(--sk-text-sec); font-size: 0.78rem; white-space: nowrap;">
              {{ formatDate(record.distribution_date) }}
            </td>
            <td>
              <span class="mono text-sm">
                {{ parseFloat(record.staked_amount || '0').toLocaleString(appLocale(), {minimumFractionDigits: 2, maximumFractionDigits: 2}) }}
              </span>
              <span class="ml-1 text-xs" style="color: var(--sk-text-muted);">{{ localCurrency }}</span>
            </td>
            <td>
              <span class="mono" style="color: var(--sk-cyan);">
                {{ parseFloat(record.apy_rate || '0').toFixed(2) }}%
              </span>
            </td>
            <td>
              <span class="mono font-bold" style="color: var(--sk-green); font-size: 0.95rem;">
                +{{ formatAmt(record.reward_amount) }}
              </span>
              <span class="ml-1 text-xs" style="color: var(--sk-green); opacity: 0.7;">{{ localCurrency }}</span>
            </td>
            <td>
              <!-- ST14 fix: transaction_hash is always null (no blockchain) — show → TEG Balance -->
              <span class="text-xs font-mono" style="color: var(--sk-cyan);">→ Balance</span>
            </td>
            <td>
              <span class="sk-badge"
                :class="{
                  'sk-badge--distributed': record.status === 'distributed',
                  'sk-badge--failed': record.status === 'failed',
                  'sk-badge--pending': record.status === 'pending' || !record.status
                }">
                {{ record.status || 'pending' }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Agent DID reference -->
    <div v-if="agentDid" class="text-xs font-mono pt-1" style="color: rgba(var(--nc-primary-rgb),0.3);">
      {{ agentDid }}
    </div>
  </div>
</template>
