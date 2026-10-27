<template>
  <!-- Build #9 (2026-05-07): Cross-Frame Bridge Health.
       Tracks BOTH cross-frame transfer paths:
         (1) Async (cross_frame_transfers) — high-volume canary/production
         (2) Sync SF-3 (bridge_transactions) — legacy escrow+mint
       Frame B and Frame A both write into Frame A's tables (sender side). -->
  <div class="ab">
    <div class="ab-ambient">
      <div class="ab-grid"></div>
      <div class="ab-glow ab-glow-1"></div>
      <div class="ab-glow ab-glow-2"></div>
    </div>

    <section class="ab-hero">
      <div class="ab-hero-inner">
        <div class="ab-chip"><span class="ab-chip-dot"></span>{{ t('adminBridgeView.hero.chip') }}</div>
        <h1 class="ab-h1">{{ t('adminBridgeView.hero.h1a') }}<span class="ab-accent">{{ t('adminBridgeView.hero.h1Accent') }}</span></h1>
        <p class="ab-lead">{{ t('adminBridgeView.hero.lead') }}</p>

        <div class="ab-toolbar">
          <div class="ab-toolbar-group">
            <span class="ab-toolbar-label">PERIOD</span>
            <button
              v-for="p in PERIODS" :key="p.value"
              class="ab-period-btn"
              :class="{ 'ab-period-btn--active': period === p.value }"
              :disabled="loading"
              @click="setPeriod(p.value)"
            >{{ p.label }}</button>
          </div>

          <span class="ab-toolbar-spacer"></span>

          <div class="ab-toolbar-group">
            <label class="ab-toggle">
              <input type="checkbox" v-model="autoRefresh" />
              <span class="ab-toggle-track"><span class="ab-toggle-knob"></span></span>
              <span class="ab-toggle-label">Auto-refresh 30s</span>
            </label>
          </div>
          <div class="ab-toolbar-group ab-toolbar-meta">
            <span class="ab-toolbar-label">LAST</span>
            <span class="ab-toolbar-val">{{ lastRefreshAt || '—' }}</span>
            <button class="ab-btn ab-btn--ghost" :disabled="loading" @click="refresh">↻</button>
          </div>
        </div>
      </div>
    </section>

    <div class="ab-body">
      <div v-if="loading && !data" class="ab-center">
        <div class="ab-spinner"></div>
        <p class="ab-loading-text">Querying bridge tables…</p>
      </div>

      <div v-else-if="error && !data" class="ab-center">
        <p class="ab-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="ab-btn ab-btn--ghost" @click="refresh">{{ t('adminBridgeView.error.retry') }}</button>
      </div>

      <template v-else-if="data">
        <!-- §FESUITE (V0578): the figures below are the last answer; when the latest read failed it says so here, not
             only in a toast that is gone in seconds -->
        <ReadFailedNotice v-if="error" dense data-testid="ab-stale" :retry="refresh"
          :text="`The bridge tables could not be read just now. What follows is from the read at ${lastRefreshAt || 'an earlier time'}.`" />
        <!-- Hero stat cards (async — primary) -->
        <div class="ab-stats">
          <div class="ab-stat-card">
            <div class="ab-stat-key">{{ t('adminBridgeView.stats.asyncTransfers') }} · {{ periodLabel }}</div>
            <div class="ab-stat-val ab-stat-val--cyan">{{ data.async.total.toLocaleString(appLocale()) }}</div>
            <div class="ab-stat-sub ab-stat-sub-grid">
              <span class="ab-pill ab-pill--green">✓ {{ data.async.settled.toLocaleString(appLocale()) }}</span>
              <span class="ab-pill ab-pill--warn">↩ {{ data.async.refunded.toLocaleString(appLocale()) }}</span>
              <span v-if="data.async.locked > 0" class="ab-pill ab-pill--cyan"><Icon name="mdi:timer-sand" /> {{ data.async.locked }}</span>
            </div>
          </div>

          <div class="ab-stat-card">
            <div class="ab-stat-key">{{ t('adminBridgeView.stats.settleRate') }}</div>
            <div class="ab-stat-val" :class="settleRateClass">
              {{ data.async.settle_rate_pct !== null ? data.async.settle_rate_pct.toFixed(2) + '%' : '—' }}
            </div>
            <div class="ab-stat-sub">
              {{ data.async.settled.toLocaleString(appLocale()) }} / {{ (data.async.settled + data.async.refunded).toLocaleString(appLocale()) }} resolved
            </div>
          </div>

          <div class="ab-stat-card">
            <div class="ab-stat-key">{{ t('adminBridgeView.stats.settleLatency') }}</div>
            <div class="ab-stat-val ab-stat-val--violet">
              {{ data.async.p50_settled_ms !== null ? data.async.p50_settled_ms + 'ms' : '—' }}
              <span class="ab-stat-unit">P50</span>
            </div>
            <div class="ab-stat-sub">
              <span>P95: {{ data.async.p95_settled_ms !== null ? data.async.p95_settled_ms + 'ms' : '—' }}</span>
              ·
              <span>avg {{ data.async.avg_settled_ms !== null ? data.async.avg_settled_ms + 'ms' : '—' }}</span>
            </div>
          </div>

          <div class="ab-stat-card">
            <div class="ab-stat-key">{{ t('adminBridgeView.stats.inFlight') }}</div>
            <div class="ab-stat-val" :class="data.async.inflight_locked > 0 ? 'ab-stat-val--cyan' : 'ab-stat-val--muted'">
              {{ data.async.inflight_locked.toLocaleString(appLocale()) }}
            </div>
            <div class="ab-stat-sub">
              <span v-if="data.async.expiring_5min > 0" class="ab-pill ab-pill--warn">{{ data.async.expiring_5min }} expiring &lt;5min</span>
              <span v-else>currently locked</span>
            </div>
          </div>
        </div>

        <!-- Inbound + SF-3 secondary panels -->
        <div class="ab-twocol">
          <div class="ab-section">
            <div class="ab-section-head">
              <span class="ab-section-title">INBOUND CREDITS · {{ periodLabel }}</span>
              <span class="ab-section-sub">receiver-side records</span>
            </div>
            <div class="ab-mini-stats">
              <div class="ab-mini">
                <span class="ab-mini-key">Total credited</span>
                <span class="ab-mini-val">{{ data.inbound.total.toLocaleString(appLocale()) }}</span>
              </div>
              <div class="ab-mini" v-for="(c, k) in data.inbound.status_counts" :key="k">
                <span class="ab-mini-key">{{ k }}</span>
                <span class="ab-mini-val" :class="inboundStatusValClass(k)">{{ c.toLocaleString(appLocale()) }}</span>
              </div>
            </div>
          </div>

          <div class="ab-section">
            <div class="ab-section-head">
              <span class="ab-section-title">SYNC SF-3 BRIDGE · {{ periodLabel }}</span>
              <span class="ab-section-sub">legacy escrow + issuance</span>
            </div>
            <div v-if="data.sync_sf3.total > 0" class="ab-mini-stats">
              <div class="ab-mini">
                <span class="ab-mini-key">Total</span>
                <span class="ab-mini-val">{{ data.sync_sf3.total.toLocaleString(appLocale()) }}</span>
              </div>
              <div class="ab-mini" v-for="(c, k) in data.sync_sf3.status_counts" :key="k">
                <span class="ab-mini-key">{{ k }}</span>
                <span class="ab-mini-val" :class="sf3StatusValClass(String(k))">{{ c.toLocaleString(appLocale()) }}</span>
              </div>
            </div>
            <!-- A4 (2026-05-08): empty-state explainer. SF-3 is the legacy
                 escrow+mint cross-frame bridge — rare in production. The
                 modern path is async (top section above). -->
            <div v-else class="ab-empty-mini">
              <div class="ab-empty-mini__title">No SF-3 transfers in this window</div>
              <div class="ab-empty-mini__sub">
                SF-3 is the legacy escrow+issuance bridge. Production cross-frame traffic uses the
                async saga (above) — &lt;1 SF-3 transfer/day is normal cluster state.
              </div>
            </div>
          </div>
        </div>

        <!-- Recent async transfers feed -->
        <div class="ab-section">
          <div class="ab-section-head">
            <span class="ab-section-title">RECENT ASYNC TRANSFERS</span>
            <div class="ab-feed-filters">
              <button
                v-for="s in ASYNC_STATUS_FILTERS" :key="s.value"
                class="ab-chip-btn"
                :class="{ 'ab-chip-btn--active': asyncFilter === s.value }"
                @click="asyncFilter = s.value"
              >{{ s.label }}</button>
            </div>
          </div>
          <div v-if="filteredAsync.length === 0" class="ab-empty-mini">No transfers match this filter.</div>
          <div v-else class="ab-feed-list">
            <div
              v-for="t in filteredAsync" :key="t.id"
              class="ab-feed-row"
              :class="{ 'ab-feed-row--expanded': expandedId === t.id }"
              @click="toggleExpand(t.id)"
            >
              <div class="ab-feed-head">
                <span class="ab-feed-time" :title="t.created_at || ''">{{ formatHHMMSS(t.created_at) }}</span>
                <span class="ab-feed-date">{{ formatDate(t.created_at) }}</span>
                <span class="ab-status-pill" :class="asyncStatusPillClass(t.status)">{{ t.status.toUpperCase() }}</span>
                <span v-if="t.latency_ms !== null" class="ab-status-pill ab-status-pill--muted">{{ t.latency_ms }}ms</span>
                <span class="ab-feed-amount">{{ formatAvt(t.amount) }} <span class="ab-feed-amount-unit">{{ localCurrency }}</span></span>
                <code class="ab-feed-did" :title="t.sender_did">↗ {{ shortDid(t.sender_did) }}</code>
                <code class="ab-feed-did" :title="t.receiver_did">→ {{ shortDid(t.receiver_did) }}</code>
                <span class="ab-feed-frame">{{ t.target_frame }}</span>
                <span class="ab-feed-spacer"></span>
                <span class="ab-feed-caret">{{ expandedId === t.id ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expandedId === t.id" class="ab-feed-detail" @click.stop>
                <div class="ab-detail-grid">
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Transfer ID</span>
                    <span class="ab-detail-val">
                      <code>{{ t.id }}</code>
                      <button class="ab-icon-btn" @click.stop="copyText(t.id)" title="Copy">⎘</button>
                    </span>
                  </div>
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Created</span>
                    <span class="ab-detail-val">{{ formatAbs(t.created_at) }}</span>
                  </div>
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Timeout</span>
                    <span class="ab-detail-val">{{ formatAbs(t.timeout_at) }}</span>
                  </div>
                  <div v-if="t.settled_at" class="ab-detail-pair">
                    <span class="ab-detail-key">Settled</span>
                    <span class="ab-detail-val">{{ formatAbs(t.settled_at) }}</span>
                  </div>
                  <div v-if="t.refunded_at" class="ab-detail-pair">
                    <span class="ab-detail-key">Refunded</span>
                    <span class="ab-detail-val">{{ formatAbs(t.refunded_at) }}</span>
                  </div>
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Sender</span>
                    <span class="ab-detail-val">
                      <code>{{ t.sender_did }}</code>
                      <button class="ab-icon-btn" @click.stop="goToEventStore(t.sender_did)" title="Open in EventStore">⤴</button>
                    </span>
                  </div>
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Receiver</span>
                    <span class="ab-detail-val">
                      <code>{{ t.receiver_did }}</code>
                      <button class="ab-icon-btn" @click.stop="goToEventStore(t.receiver_did)" title="Open in EventStore">⤴</button>
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Recent SF-3 sync transfers (only if any) -->
        <div v-if="data.recent_sync.length > 0" class="ab-section">
          <div class="ab-section-head">
            <span class="ab-section-title">RECENT SF-3 SYNC TRANSFERS</span>
            <span class="ab-section-sub">last {{ data.recent_sync.length }} legacy bridge transactions</span>
          </div>
          <div class="ab-feed-list">
            <div
              v-for="t in data.recent_sync" :key="t.id"
              class="ab-feed-row"
              :class="{ 'ab-feed-row--expanded': expandedSyncId === t.id }"
              @click="toggleSyncExpand(t.id)"
            >
              <div class="ab-feed-head">
                <span class="ab-feed-time">{{ formatHHMMSS(t.created_at) }}</span>
                <span class="ab-feed-date">{{ formatDate(t.created_at) }}</span>
                <span class="ab-status-pill" :class="sf3StatusPillClass(t.status)">{{ t.status }}</span>
                <span v-if="t.latency_ms !== null" class="ab-status-pill ab-status-pill--muted">{{ t.latency_ms }}ms</span>
                <span class="ab-feed-amount">{{ formatAvt(t.amount) }} <span class="ab-feed-amount-unit">{{ localCurrency }}</span></span>
                <span class="ab-pill ab-pill--violet">{{ t.direction }}</span>
                <span class="ab-feed-frame">{{ t.source_frame_id }} → {{ t.target_frame_id }}</span>
                <span class="ab-feed-spacer"></span>
                <span class="ab-feed-caret">{{ expandedSyncId === t.id ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expandedSyncId === t.id" class="ab-feed-detail" @click.stop>
                <div class="ab-detail-grid">
                  <div class="ab-detail-pair">
                    <span class="ab-detail-key">Bridge TX</span>
                    <span class="ab-detail-val"><code>{{ t.id }}</code></span>
                  </div>
                  <div v-if="t.lock_tx_id" class="ab-detail-pair">
                    <span class="ab-detail-key">Lock TX</span>
                    <span class="ab-detail-val"><code>{{ t.lock_tx_id }}</code></span>
                  </div>
                  <div v-if="t.mint_tx_id" class="ab-detail-pair">
                    <span class="ab-detail-key">Issue TX</span>
                    <span class="ab-detail-val"><code>{{ t.mint_tx_id }}</code></span>
                  </div>
                  <div v-if="t.unlock_tx_id" class="ab-detail-pair">
                    <span class="ab-detail-key">Unlock TX</span>
                    <span class="ab-detail-val"><code>{{ t.unlock_tx_id }}</code></span>
                  </div>
                  <div v-if="t.error_message" class="ab-detail-section">
                    <span class="ab-detail-key">Error</span>
                    <pre class="ab-detail-pre ab-detail-pre--err">{{ t.error_message }}</pre>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="ab-footer">
          <code>/admin/bridge/aggregate?period={{ data.period }}</code>
          <span> · as of {{ formatAbs(data.as_of) }}</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
/**
 * AdminBridge — Cross-Frame Bridge Watchtower
 *
 * Build #9 (2026-05-07). Surfaces both cross-frame paths:
 *  - Async (cross_frame_transfers) — high volume, settle/refund + latency stats
 *  - Sync SF-3 (bridge_transactions) — legacy escrow + mint
 *  - Inbound credit feed (cross_frame_transfers_inbound)
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { usePolledData } from '@/composables/usePolledData'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import {
  bridgeAdminService,
  type BridgePeriod,
  type BridgeAggregate,
  type AsyncTransferRow,
} from '@/services/api/bridgeAdmin'

const { t } = useI18n()

const uiStore = useUIStore()
const router = useRouter()
const { localCurrency } = useCurrency()

const PERIODS: { value: BridgePeriod; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All' },
]

const ASYNC_STATUS_FILTERS: { value: string; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'settled', label: 'Settled' },
  { value: 'refunded', label: 'Refunded' },
  { value: 'locked', label: 'Locked' },
]

const period = ref<BridgePeriod>('24h')
const asyncFilter = ref<string>('all')
const data = ref<BridgeAggregate | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const autoRefresh = ref(true)
const expandedId = ref<string | null>(null)
const expandedSyncId = ref<string | null>(null)
// §FESUITE (V0578): the period the figures on screen answer. A failed read after a period change kept the previous
// window's figures under the new period's label ("No SF-3 transfers in this window" for a window never read). (Two reads
// for different periods cannot overlap: the period buttons are disabled while a read is out.)
const dataPeriod = ref<BridgePeriod | null>(null)

// F (2026-05-08): usePolledData composable replaces hand-rolled polling.
const polled = usePolledData(refresh, {
  interval: 30_000,
  immediate: true,
  pauseWhenHidden: true,
  autoStart: true,
})
watch(autoRefresh, (on) => { on ? polled.resume() : polled.pause() })

watch([period], () => { void refresh() })

async function refresh() {
  const asked = period.value
  loading.value = true
  error.value = null
  try {
    data.value = await bridgeAdminService.aggregate(asked)
    dataPeriod.value = asked
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load bridge data'
    // figures that answer another window are not this window's answer
    if (dataPeriod.value !== asked) { data.value = null; dataPeriod.value = null }
    uiStore.showError?.('Bridge', error.value!)
  } finally {
    loading.value = false
  }
}

function setPeriod(p: BridgePeriod) {
  if (period.value === p) return
  period.value = p
}
function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}
function toggleSyncExpand(id: string) {
  expandedSyncId.value = expandedSyncId.value === id ? null : id
}

const periodLabel = computed(() => PERIODS.find(p => p.value === period.value)?.label || period.value)

const filteredAsync = computed<AsyncTransferRow[]>(() => {
  if (!data.value) return []
  if (asyncFilter.value === 'all') return data.value.recent_async
  return data.value.recent_async.filter(t => t.status === asyncFilter.value)
})

const settleRateClass = computed(() => {
  const r = data.value?.async.settle_rate_pct
  if (r === null || r === undefined) return 'ab-stat-val--muted'
  if (r >= 99) return 'ab-stat-val--green'
  if (r >= 90) return 'ab-stat-val--cyan'
  if (r >= 50) return 'ab-stat-val--warn'
  return 'ab-stat-val--red'
})

// ── Helpers ──
function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 26) return s
  return `${s.slice(0, 14)}…${s.slice(-6)}`
}
function formatAvt(v: string | null | undefined): string {
  if (!v) return '—'
  const n = parseFloat(v)
  if (Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1) return n.toLocaleString(appLocale(), { maximumFractionDigits: 2 })
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 6 })
}
function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const dt = typeof iso === 'string' ? new Date(iso) : iso
  return dt.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric' })
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function asyncStatusPillClass(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'settled') return 'ab-status-pill--green'
  if (s === 'refunded') return 'ab-status-pill--warn'
  if (s === 'locked') return 'ab-status-pill--cyan'
  return 'ab-status-pill--muted'
}

function sf3StatusPillClass(status: string): string {
  const s = (status || '').toUpperCase()
  if (s === 'COMPLETED' || s === 'MINTED') return 'ab-status-pill--green'
  if (s === 'INITIATED' || s === 'LOCKED') return 'ab-status-pill--cyan'
  if (s === 'EXPIRED') return 'ab-status-pill--warn'
  if (s === 'FAILED') return 'ab-status-pill--red'
  return 'ab-status-pill--muted'
}

function inboundStatusValClass(status: string | number): string {
  const s = String(status || '').toLowerCase()
  if (s === 'credited') return 'ab-stat-val--green'
  if (s === 'reversed') return 'ab-stat-val--warn'
  return 'ab-stat-val--muted'
}

function sf3StatusValClass(status: string): string {
  const s = (status || '').toUpperCase()
  if (s === 'COMPLETED' || s === 'MINTED') return 'ab-stat-val--green'
  if (s === 'EXPIRED' || s === 'FAILED') return 'ab-stat-val--red'
  return 'ab-stat-val--muted'
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}

function goToEventStore(did: string) {
  void router.push({ path: '/admin/events', query: { aggregate_id: did } })
}
</script>

<style scoped>
.ab {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* ── Ambient ────────── */
.ab-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.ab-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.ab-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.ab-glow-1 { width: 440px; height: 440px; background: rgba(168, 85, 247, 0.55); top: -110px; right: -90px; }
.ab-glow-2 { width: 320px; height: 320px; background: rgba(var(--cyan-rgb), 0.4); bottom: -60px; left: -100px; }

/* Hero */
.ab-hero { position: relative; z-index: 1; padding: 36px 32px 18px; }
.ab-hero-inner { max-width: 1280px; margin: 0 auto; }
.ab-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.ab-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan); box-shadow: 0 0 8px var(--cyan);
}
.ab-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.4rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.ab-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.ab-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.6);
  margin: 0 0 16px;
  line-height: 1.5;
  max-width: 60rem;
}
.ab-lead strong { color: rgba(255, 255, 255, 0.85); font-weight: 700; }

/* Toolbar */
.ab-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.ab-toolbar-group { display: flex; align-items: center; gap: 0.4rem; }
.ab-toolbar-spacer { flex: 1; }
.ab-toolbar-meta { margin-left: 0.3rem; }
.ab-toolbar-label {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.12em; color: rgba(255, 255, 255, 0.45);
  text-transform: uppercase;
}
.ab-toolbar-val {
  font-family: var(--mono); font-size: 0.78rem; font-weight: 700; color: var(--cyan);
}

.ab-period-btn {
  font-family: var(--mono); font-size: 0.65rem; font-weight: 600; letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 4px 10px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.ab-period-btn:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9);
}
.ab-period-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
  box-shadow: 0 0 8px rgba(var(--cyan-rgb), 0.18);
}
.ab-period-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.ab-toggle {
  display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.7);
}
.ab-toggle input { display: none; }
.ab-toggle-track {
  width: 26px; height: 14px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 7px; position: relative;
  transition: background 0.15s;
}
.ab-toggle-knob {
  position: absolute; top: 2px; left: 2px;
  width: 10px; height: 10px;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  transition: transform 0.15s, background 0.15s;
}
.ab-toggle input:checked ~ .ab-toggle-track { background: rgba(var(--cyan-rgb), 0.3); }
.ab-toggle input:checked ~ .ab-toggle-track .ab-toggle-knob {
  transform: translateX(12px); background: var(--cyan);
}

/* Body */
.ab-body {
  position: relative; z-index: 1;
  padding: 0 32px;
  max-width: 1280px;
  margin: 0 auto;
  display: flex; flex-direction: column; gap: 1.25rem;
}

.ab-btn {
  display: inline-flex; align-items: center; gap: 0.35rem;
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.08em; font-weight: 600;
  padding: 4px 10px; border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer; transition: all 0.15s;
}
.ab-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.ab-btn--ghost {
  background: transparent;
  border-color: rgba(var(--cyan-rgb), 0.25);
  color: rgba(var(--cyan-rgb), 0.85);
}
.ab-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--cyan-rgb), 0.08);
  border-color: rgba(var(--cyan-rgb), 0.5);
  color: rgba(var(--cyan-rgb), 1);
}

.ab-center {
  text-align: center;
  padding: 5rem 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.12);
  border-radius: 6px;
}
.ab-spinner {
  width: 36px; height: 36px;
  border: 2.5px solid rgba(var(--cyan-rgb), 0.2);
  border-top-color: rgba(var(--cyan-rgb), 0.95);
  border-radius: 50%;
  animation: ab-spin 0.8s linear infinite;
  margin: 0 auto 0.8rem;
}
@keyframes ab-spin { to { transform: rotate(360deg); } }
.ab-loading-text {
  font-family: var(--mono); font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.1em; text-transform: uppercase;
}
.ab-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger); }

/* Stats */
.ab-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
.ab-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.ab-stat-key {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
}
.ab-stat-val {
  font-family: var(--mono);
  font-size: 1.7rem; font-weight: 700;
  letter-spacing: -0.02em; line-height: 1.05;
}
.ab-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.ab-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.ab-stat-val--violet { color: #c084fc; text-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
.ab-stat-val--red { color: var(--nc-danger, #ff3366); text-shadow: 0 0 14px rgba(255, 51, 102, 0.45); }
.ab-stat-val--warn { color: var(--nc-warning, #ff9500); text-shadow: 0 0 14px rgba(255, 149, 0, 0.4); }
.ab-stat-val--muted { color: rgba(255, 255, 255, 0.45); }
.ab-stat-unit { font-size: 0.7rem; margin-left: 0.3rem; font-weight: 600; color: rgba(255, 255, 255, 0.55); letter-spacing: 0.06em; }
.ab-stat-sub {
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.04em;
  display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap;
}
.ab-stat-sub-grid { display: flex; gap: 0.3rem; flex-wrap: wrap; }

.ab-pill {
  display: inline-block;
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.ab-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.ab-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.ab-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.ab-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }

/* Two-col */
.ab-twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }

/* Section */
.ab-section {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.7rem;
}
.ab-section-head {
  display: flex; justify-content: space-between; align-items: center;
  gap: 1rem; flex-wrap: wrap;
}
.ab-section-title {
  font-family: var(--mono); font-size: 0.65rem;
  letter-spacing: 0.14em; font-weight: 700;
  color: var(--cyan); text-transform: uppercase;
}
.ab-section-sub {
  font-family: var(--mono); font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.06em;
}

/* Mini stats */
.ab-mini-stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.6rem;
}
.ab-mini {
  display: flex; flex-direction: column; gap: 0.2rem;
  padding: 0.45rem 0.7rem;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 4px;
}
.ab-mini-key {
  font-family: var(--mono); font-size: 0.55rem;
  letter-spacing: 0.1em; color: rgba(255, 255, 255, 0.5);
  text-transform: uppercase; font-weight: 600;
}
.ab-mini-val { font-family: var(--mono); font-size: 1rem; font-weight: 700; }

/* Feed filters */
.ab-feed-filters { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
.ab-chip-btn {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 600;
  letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px;
  padding: 3px 9px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.ab-chip-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9); }
.ab-chip-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}

/* Feed list */
.ab-feed-list { display: flex; flex-direction: column; gap: 0.35rem; }
.ab-feed-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.ab-feed-row:hover {
  background: rgba(var(--cyan-rgb), 0.04);
  border-color: rgba(var(--cyan-rgb), 0.25);
}
.ab-feed-row--expanded {
  background: rgba(var(--cyan-rgb), 0.06);
  border-color: rgba(var(--cyan-rgb), 0.4);
}
.ab-feed-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  flex-wrap: wrap;
  font-family: var(--mono);
}
.ab-feed-time { font-size: 0.7rem; font-weight: 600; color: rgba(255, 255, 255, 0.85); }
.ab-feed-date { font-size: 0.6rem; color: rgba(255, 255, 255, 0.5); }
.ab-feed-amount { font-size: 0.72rem; font-weight: 700; color: var(--cyan); }
.ab-feed-amount-unit { font-size: 0.55rem; color: rgba(255, 255, 255, 0.45); font-weight: 600; letter-spacing: 0.06em; }
.ab-feed-did {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--cyan-rgb), 0.04);
  padding: 1px 5px; border-radius: 3px;
}
.ab-feed-frame {
  font-size: 0.6rem; color: rgba(168, 85, 247, 0.85);
  background: rgba(168, 85, 247, 0.06);
  padding: 1px 5px; border-radius: 3px;
  border: 1px solid rgba(168, 85, 247, 0.2);
}
.ab-feed-spacer { flex: 1; }
.ab-feed-caret { font-size: 0.7rem; color: rgba(var(--cyan-rgb), 0.6); }

.ab-status-pill {
  font-family: var(--mono); font-size: 0.55rem; font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px; border-radius: 3px;
  border: 1px solid transparent;
}
.ab-status-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.ab-status-pill--warn  { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.ab-status-pill--cyan  { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.ab-status-pill--red   { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.ab-status-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

/* Detail */
.ab-feed-detail {
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex; flex-direction: column; gap: 0.6rem;
  cursor: default;
}
.ab-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0.4rem 0.85rem;
}
.ab-detail-pair { display: flex; flex-direction: column; gap: 0.15rem; }
.ab-detail-key {
  font-family: var(--mono); font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: rgba(255, 255, 255, 0.4);
  text-transform: uppercase; font-weight: 600;
}
.ab-detail-val {
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 0.35rem;
}
.ab-detail-val code {
  background: rgba(var(--cyan-rgb), 0.06);
  padding: 1px 5px; border-radius: 3px;
  word-break: break-all; font-size: 0.65rem;
}
.ab-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace; font-size: 0.7rem;
  padding: 0 5px; cursor: pointer;
  transition: all 0.12s;
}
.ab-icon-btn:hover {
  background: rgba(var(--cyan-rgb), 0.1);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.ab-detail-section { margin-top: 0.2rem; }
.ab-detail-pre {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 4px;
  padding: 6px 9px;
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.75);
  white-space: pre-wrap; word-break: break-all;
  max-height: 14rem; overflow-y: auto;
}
.ab-detail-pre--err {
  background: rgba(255, 51, 102, 0.06);
  border-color: rgba(255, 51, 102, 0.3);
  color: rgba(255, 200, 200, 0.85);
}

/* Empty */
.ab-empty-mini {
  text-align: center;
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.4);
  padding: 1.4rem;
  letter-spacing: 0.06em;
}
.ab-empty-mini__title {
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.6);
  margin-bottom: 0.5rem;
}
.ab-empty-mini__sub {
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0;
  text-transform: none;
  line-height: 1.5;
  max-width: 440px;
  margin: 0 auto;
}

/* Footer */
.ab-footer {
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.5);
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.08);
}
.ab-footer code {
  background: rgba(var(--cyan-rgb), 0.08);
  color: var(--cyan);
  padding: 1px 5px; border-radius: 3px;
}

/* Responsive */
@media (max-width: 1100px) {
  .ab-stats { grid-template-columns: 1fr 1fr; }
  .ab-twocol { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  .ab-hero { padding: 24px 16px 12px; }
  .ab-h1 { font-size: 1.5rem; }
  .ab-body { padding: 0 16px; }
  .ab-stats { grid-template-columns: 1fr; }
}
</style>
