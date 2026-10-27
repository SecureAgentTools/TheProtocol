<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted } from 'vue'
import { useStakingStore } from '@/stores/staking'
import { useUIStore } from '@/stores/ui'
import { stakingRewardsApi } from '@/services/api/stakingRewards'
import { apiClient } from '@/services/api/client'
import { useCurrency } from '@/composables/useCurrency'
import '@/components/staking/tp-staking.css'

const stakingStore = useStakingStore()
const uiStore = useUIStore()
// FX multi-currency: distribution totals are this registry's currency (AVT/BVT).
const { localCurrency } = useCurrency()

const isRunning = ref(false)
const isLoading = ref(true)

// ── Raw distribution run objects from /staking/rewards/distributions ──────────
// Fields: id, distribution_date, distribution_type, total_distributed,
//         total_stakers, status, started_at, completed_at, distribution_metadata
//         {successful, failed, skipped, total_eligible}
// DO NOT go through stakingRewardsApi.getDistributionHistory() — it remaps to
// per-agent shape and destroys these fields.
const globalDistributions = ref<any[]>([])

const totalDistributed = computed(() =>
  globalDistributions.value
    .filter(d => d.status === 'completed')
    .reduce((s, d) => s + parseFloat(d.total_distributed || '0'), 0)
)
const distributionCount = computed(() => globalDistributions.value.length)

const formatDate = (d: string) =>
  new Date(d).toLocaleString(appLocale(), {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })

const formatAmt = (v: string | number | undefined, dp = 4) => {
  if (v === undefined || v === null) return '0.0000'
  const n = typeof v === 'string' ? parseFloat(v) : v
  return isNaN(n) ? '0.0000' : n.toLocaleString(appLocale(), { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

// ── Load directly from raw endpoint — no intermediary mapping ─────────────────
const loadDistributions = async () => {
  try {
    const { data } = await apiClient.get('/staking/rewards/distributions')
    globalDistributions.value = Array.isArray(data) ? data : (data?.distributions || [])
  } catch (e) {
    console.error('Failed to load global distributions:', e)
    globalDistributions.value = []
  }
}

const triggerDistribution = async () => {
  isRunning.value = true
  try {
    await stakingRewardsApi.triggerManualDistribution({ dry_run: false })
    uiStore.showSuccess('Distribution Triggered', 'Payout cycle started')
    await loadDistributions()
  } catch (error: any) {
    uiStore.showError('Distribution Failed', error.message || 'Failed to trigger distribution')
  } finally {
    isRunning.value = false
  }
}

onMounted(async () => {
  try {
    await loadDistributions()
  } finally {
    isLoading.value = false
  }
})
</script>

<template>
  <div class="staking-view space-y-5">

    <!-- Admin badge -->
    <div class="flex items-center gap-2">
      <span class="sk-badge sk-badge--admin"><Icon name="mdi:cog" /> ADMIN CONTROLS</span>
      <span class="text-xs font-mono" style="color: var(--sk-text-muted);">is_admin required</span>
    </div>

    <!-- Stats overview -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="sk-stat-card" style="padding:1rem; border-color: rgba(239,68,68,0.2);">
        <div class="sk-stat-card__label">Total Distributed</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.1rem; color: var(--sk-green);">
          {{ formatAmt(totalDistributed, 2) }}
        </div>
        <div class="sk-stat-card__sub" style="font-family:'IBM Plex Mono',monospace; font-size:0.6rem; color: var(--sk-text-muted);">{{ localCurrency }} (completed runs)</div>
      </div>
      <div class="sk-stat-card" style="padding:1rem; border-color: rgba(239,68,68,0.2);">
        <div class="sk-stat-card__label">Distribution Runs</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.1rem; color: var(--sk-text);">
          {{ distributionCount }}
        </div>
        <div class="sk-stat-card__sub">
          {{ globalDistributions.filter(d => d.status === 'completed').length }} completed ·
          {{ globalDistributions.filter(d => d.status === 'failed').length }} failed
        </div>
      </div>
      <div class="sk-stat-card" style="padding:1rem; border-color: rgba(239,68,68,0.2);">
        <div class="sk-stat-card__label">Agents in the Last Run</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.1rem; color: var(--sk-text);">
          {{ globalDistributions[0]?.total_stakers ?? '—' }}
        </div>
        <div v-if="globalDistributions[0]?.distribution_date" class="sk-stat-card__sub">
          {{ globalDistributions[0].distribution_date }}
        </div>
      </div>
      <div class="sk-stat-card" style="padding:1rem; border-color: rgba(239,68,68,0.2);">
        <div class="sk-stat-card__label">Last Run Amount</div>
        <div class="sk-stat-card__value mono" style="font-size: 1.1rem; color: var(--sk-cyan);">
          {{ globalDistributions[0]?.total_distributed ? formatAmt(globalDistributions[0].total_distributed) : '—' }}
        </div>
        <div class="sk-stat-card__sub" style="font-family:'IBM Plex Mono',monospace; font-size:0.6rem; color: var(--sk-text-muted);">{{ localCurrency }}</div>
      </div>
    </div>

    <!-- Manual trigger -->
    <div class="sk-card" style="border-color: rgba(239,68,68,0.25);">
      <div class="sk-card-header" style="border-color: rgba(239,68,68,0.15);">
        <div class="sk-card-title" style="color: var(--sk-red);"><Icon name="mdi:lightning-bolt" /> Manual Distribution Trigger</div>
        <div class="sk-card-subtitle">
          Starts an out-of-band payout cycle. Normally runs automatically at 00:00 UTC.
        </div>
      </div>
      <div class="p-5 space-y-4">
        <div class="sk-warn-box flex gap-3 items-start">
          <span style="flex-shrink:0;"><Icon name="mdi:alert" /></span>
          <div class="text-xs">
            <strong>Admin-only action.</strong> Manual distribution runs the full payout cycle for all active lock positions.
            This is idempotent within the same UTC day — duplicate distributions for the same day will be skipped by the distributor.
          </div>
        </div>
        <div>
          <button
            @click="triggerDistribution"
            :disabled="isRunning"
            class="sk-btn sk-btn--danger"
          >
            <svg v-if="isRunning" class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {{ isRunning ? 'Running Distribution...' : 'Trigger Distribution Cycle' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Global distribution log -->
    <div class="sk-card" style="border-color: rgba(239,68,68,0.15);">
      <div class="sk-card-header" style="border-color: rgba(239,68,68,0.1);">
        <div class="sk-card-title">Global Distribution Log</div>
        <div class="sk-card-subtitle">All distribution runs · Source: /staking/rewards/distributions</div>
      </div>

      <div v-if="isLoading" class="p-8 text-center text-sm" style="color: var(--sk-text-muted);">Loading...</div>
      <div v-else-if="globalDistributions.length === 0" class="sk-empty">
        <div class="sk-empty__icon"><Icon name="mdi:clipboard" /></div>
        <div class="sk-empty__title">No Distributions Recorded</div>
        <div class="sk-empty__desc">Distribution history will appear here after the first cycle.</div>
      </div>
      <div v-else class="overflow-x-auto sk-scrollbar">
        <table class="sk-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Type</th>
              <th>Agents Paid</th>
              <th>Successful / Failed</th>
              <th>Total Distributed</th>
              <th>Duration</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="dist in globalDistributions" :key="dist.id">
              <td style="color: var(--sk-text-sec); font-size:0.78rem; white-space:nowrap;">
                {{ formatDate(dist.started_at || dist.distribution_date) }}
              </td>
              <td>
                <span class="font-mono text-xs" style="color: var(--sk-text-muted);">{{ dist.distribution_type || 'daily' }}</span>
              </td>
              <td>
                <span class="mono">{{ dist.total_stakers ?? '0' }}</span>
              </td>
              <td>
                <span class="mono text-xs">
                  <span style="color: var(--sk-green);">{{ dist.distribution_metadata?.successful ?? '—' }}</span>
                  <span style="color: var(--sk-text-muted);"> / </span>
                  <span :style="(dist.distribution_metadata?.failed || 0) > 0 ? 'color: var(--sk-red)' : 'color: var(--sk-text-muted)'">
                    {{ dist.distribution_metadata?.failed ?? '—' }}
                  </span>
                </span>
              </td>
              <td>
                <span class="mono font-bold"
                  :style="parseFloat(dist.total_distributed || '0') > 0 ? 'color: var(--sk-green)' : 'color: var(--sk-text-muted)'">
                  {{ parseFloat(dist.total_distributed || '0') > 0
                      ? '+' + formatAmt(dist.total_distributed) + ' ' + localCurrency
                      : '0.00 ' + localCurrency }}
                </span>
              </td>
              <td>
                <span class="mono text-xs" style="color: var(--sk-text-muted);">
                  <template v-if="dist.started_at && dist.completed_at">
                    {{ ((new Date(dist.completed_at).getTime() - new Date(dist.started_at).getTime()) / 1000).toFixed(2) }}s
                  </template>
                  <template v-else>—</template>
                </span>
              </td>
              <td>
                <span class="sk-badge"
                  :class="{
                    'sk-badge--distributed': dist.status === 'completed',
                    'sk-badge--failed': dist.status === 'failed',
                    'sk-badge--pending': dist.status === 'running' || dist.status === 'pending'
                  }">
                  {{ dist.status }}
                </span>
                <div v-if="dist.error_message" class="text-xs mt-1" style="color: var(--sk-red); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
                  :title="dist.error_message">
                  {{ dist.error_message }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>
