<template>
  <!-- Build #3 (2026-05-07): Per-agent TEG ledger / Statement panel.
       Drop-in for MyAgents.vue. Mirrors funding-section + payment-tokens
       collapsible header pattern for visual consistency.
       Strategy doc §4 Build #3. -->
  <div class="st-section">

    <div class="st-header" @click="expanded = !expanded">
      <span class="st-glyph">⏷</span>
      {{ t('myAgentsView.actions.statement') }}
      <span v-if="transactions.length" class="st-count">{{ transactions.length }}</span>
      <span v-if="reconcileMatches === false" class="st-pill st-pill--err" :title="`Sum mismatch: chart shows ${formatAmount(runningBalance)} ${localCurrency}, live balance shows ${formatAmount(liveBalance)} ${localCurrency} (Δ ${formatAmount(reconcileDelta)})`"><Icon name="mdi:alert" /> Reconcile</span>
      <span v-else-if="reconcileMatches === true" class="st-pill st-pill--ok" title="Running balance matches live balance">✓ Reconciled</span>
      <span class="st-flex"></span>
      <span class="st-toggle">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <div v-if="expanded" class="st-body">
      <div v-if="!agentDid" class="st-note">
        <span class="st-note-icon">!</span>
        <span>Select an agent above to view its transaction statement.</span>
      </div>

      <template v-else>
        <!-- Reconciliation strip -->
        <div class="st-recon-strip" :class="{ 'st-recon-strip--err': reconcileMatches === false }">
          <div class="st-recon-cell">
            <span class="st-recon-label">Live balance</span>
            <span v-if="balanceFailed || statementUnread" class="st-recon-value" data-testid="st-balance-unread"
                  title="The live balance could not be read just now. This is not a balance of zero.">—</span>
            <span v-else class="st-recon-value">{{ formatAmount(liveBalance) }} {{ localCurrency }}</span>
          </div>
          <div class="st-recon-cell">
            <span class="st-recon-label">Sum of statement</span>
            <span v-if="statementUnread" class="st-recon-value" data-testid="st-sum-unread"
                  title="The statement could not be read just now. This is not a sum of zero.">—</span>
            <span v-else class="st-recon-value" :class="reconcileMatches === false ? 'st-text-err' : ''">
              {{ formatAmount(runningBalance) }} {{ localCurrency }}
            </span>
          </div>
          <div v-if="reconcileMatches === false" class="st-recon-cell">
            <span class="st-recon-label">Delta</span>
            <span class="st-recon-value st-text-err">{{ formatAmount(reconcileDelta) }} {{ localCurrency }}</span>
          </div>
          <div class="st-recon-cell st-recon-cell--note">
            <span v-if="reconcileMatches === true" class="st-recon-status st-text-ok">✓ Sum matches live balance</span>
            <span v-else-if="reconcileMatches === false" class="st-recon-status st-text-err"><Icon name="mdi:alert" /> Mismatch — likely older txs not in this window</span>
            <!-- §FESUITE (V0577): no verdict either way over a balance that was not read -->
            <span v-else-if="statementUnread" class="st-recon-status st-text-muted" data-testid="st-recon-unread">
              The statement could not be read just now, so it cannot be reconciled.
            </span>
            <span v-else-if="balanceFailed" class="st-recon-status st-text-muted" data-testid="st-recon-unread">
              The live balance could not be read just now, so the statement cannot be reconciled. Refresh to try again.
            </span>
            <span v-else class="st-recon-status st-text-muted">— pending data</span>
          </div>
        </div>

        <!-- Sparkline chart of running balance -->
        <div v-if="transactions.length > 1" class="st-chart-wrap">
          <svg
            class="st-chart"
            :viewBox="`0 0 ${chartW} ${chartH}`"
            preserveAspectRatio="none"
            role="img"
            aria-label="Running balance over time"
          >
            <!-- Gradient fill under the line -->
            <defs>
              <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" :stop-color="`rgba(var(--nc-primary-rgb), 0.4)`" />
                <stop offset="100%" :stop-color="`rgba(var(--nc-primary-rgb), 0)`" />
              </linearGradient>
            </defs>
            <!-- Grid lines -->
            <line v-for="i in 4" :key="`g${i}`" :x1="0" :y1="(i * chartH) / 4" :x2="chartW" :y2="(i * chartH) / 4" class="st-chart-grid" />
            <!-- Area fill -->
            <path :d="chartAreaPath" :fill="`url(#${gradientId})`" />
            <!-- Line -->
            <path :d="chartLinePath" class="st-chart-line" />
            <!-- Hover endpoint dot -->
            <circle v-if="chartPoints.length" :cx="chartPoints[chartPoints.length - 1].x" :cy="chartPoints[chartPoints.length - 1].y" r="3.5" class="st-chart-dot" />
          </svg>
          <div class="st-chart-meta">
            <span class="st-chart-meta-key">Trend</span>
            <span class="st-chart-meta-val">{{ chartRangeLabel }}</span>
            <span class="st-chart-meta-spacer"></span>
            <span class="st-chart-meta-key">Min</span>
            <span class="st-chart-meta-val">{{ formatAmount(chartMin) }}</span>
            <span class="st-chart-meta-key">Max</span>
            <span class="st-chart-meta-val">{{ formatAmount(chartMax) }}</span>
          </div>
        </div>

        <!-- Toolbar -->
        <div class="st-toolbar">
          <div class="st-toolbar-left">
            <span class="st-toolbar-label">FILTER</span>
            <button
              v-for="f in FILTERS"
              :key="f.id || 'all'"
              class="st-chip"
              :class="{ 'st-chip--active': activeFilter === f.id }"
              :title="f.title"
              @click="activeFilter = f.id"
            >{{ f.label }}</button>
          </div>
          <div class="st-toolbar-right">
            <input
              v-model="searchQuery"
              type="text"
              class="st-search"
              placeholder="Search counterparty or memo…"
              aria-label="Search transactions"
            />
            <button class="st-btn st-btn--ghost" :disabled="loading" @click="refresh">↻ Refresh</button>
            <button
              class="st-btn st-btn--primary"
              :disabled="!filteredTransactions.length"
              title="Export current view as CSV"
              aria-label="Export statement as CSV"
              @click="exportCsv"
            >⤓ Export CSV</button>
          </div>
        </div>

        <!-- Inline error -->
        <div v-if="error" class="st-error" role="alert">
          <span><Icon name="mdi:alert" /> {{ error }}</span>
          <button class="st-btn st-btn--ghost" @click="refresh">Retry</button>
        </div>

        <!-- §FESUITE (V0577): the statement could not be read; the error above says so, and nothing below claims
             "No transactions yet… hasn't sent or received any" under it -->
        <template v-if="statementUnread" />
        <!-- Loading skeleton -->
        <div v-else-if="loading && !transactions.length" class="st-skeleton">
          <div v-for="i in 5" :key="i" class="st-skel-row"></div>
        </div>

        <!-- Empty -->
        <div v-else-if="!transactions.length" class="st-empty">
          <div class="st-empty-glyph"><Icon name="mdi:scroll-text" /></div>
          <p class="st-empty-title">No transactions yet</p>
          <p class="st-empty-sub">
            This agent hasn't sent or received any {{ localCurrency }} yet. Fund it from the funding panel above
            or receive {{ localCurrency }} by accepting A2A payments from other agents.
          </p>
        </div>

        <!-- Filter empty -->
        <div v-else-if="!filteredTransactions.length" class="st-empty">
          <div class="st-empty-glyph"><Icon name="mdi:magnify" /></div>
          <p class="st-empty-title">No transactions match the filter</p>
          <button class="st-btn st-btn--ghost" @click="clearFilters">Clear filters</button>
        </div>

        <!-- Transaction list -->
        <div v-else class="st-list">
          <div class="st-list-head">
            <span class="st-th st-th--time">TIME</span>
            <span class="st-th st-th--type">TYPE</span>
            <span class="st-th st-th--party">COUNTERPARTY</span>
            <span class="st-th st-th--amount">AMOUNT</span>
            <span class="st-th st-th--fee">FEE</span>
            <span class="st-th st-th--bal">BALANCE</span>
            <span class="st-th st-th--id">TX ID</span>
          </div>
          <div
            v-for="(tx, i) in filteredTransactions"
            :key="tx.transaction_id"
            class="st-row"
            :class="rowClass(tx)"
          >
            <span class="st-cell st-cell--time" :title="formatAbs(tx.timestamp)">{{ timeAgo(tx.timestamp) }}</span>
            <span class="st-cell st-cell--type">
              <span class="st-type-pill" :class="typeChipClass(tx)" :title="typeLabel(tx)">{{ typeLabel(tx) }}</span>
            </span>
            <span class="st-cell st-cell--party" :title="counterparty(tx)">{{ shortDid(counterparty(tx)) }}</span>
            <span class="st-cell st-cell--amount" :class="amountClass(tx)">
              {{ amountSign(tx) }}{{ formatAmount(amountValue(tx)) }}
            </span>
            <span class="st-cell st-cell--fee">
              {{ tx.fee_amount && Number(tx.fee_amount) > 0 ? formatAmount(tx.fee_amount) : '—' }}
            </span>
            <span class="st-cell st-cell--bal">{{ formatAmount(rollingBalance[i]) }}</span>
            <span class="st-cell st-cell--id" :title="tx.transaction_id">
              <code>{{ shortId(tx.transaction_id) }}</code>
              <button class="st-icon-btn" title="Copy transaction ID" @click.stop="copyText(tx.transaction_id)">⎘</button>
            </span>
          </div>
        </div>

        <!-- Footer -->
        <div class="st-footer">
          <span>
            Showing {{ filteredTransactions.length }} of {{ transactions.length }} transactions<span v-if="loadedFullPage"> · last {{ pageLimit }} loaded</span>
          </span>
          <button v-if="hasMore && !loadingMore" class="st-btn st-btn--ghost" @click="loadMore">Load more</button>
          <span v-else-if="loadingMore" class="st-footer-loading">Loading…</span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * StatementPanel — TEG ledger view for the selected agent.
 *
 * Build #3 (2026-05-07).
 * Strategy doc §4 Build #3. Backend: GET /teg/transactions (agent JWT).
 *
 * Features:
 *  - Sparkline chart of running balance (pure SVG, no chart library)
 *  - Reconciliation indicator vs live /teg/balance
 *  - Filter chips + free-text search (memo/counterparty)
 *  - CSV export of filtered set
 *  - Pagination (load more)
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { tegApi as tegService, type TEGTransaction } from '@/services/api/teg'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  agentDid: string | null | undefined
  hasAgentToken: boolean
}>()

const uiStore = useUIStore()
const { t } = useI18n()
import { useCurrency } from '@/composables/useCurrency'
const { localCurrency } = useCurrency()

// ── State ─────────────────────────────────────────────────────────
const expanded = ref(false)  // collapsed by default
const transactions = ref<TEGTransaction[]>([])
const loading = ref(false)
const loadingMore = ref(false)
const error = ref<string | null>(null)
const liveBalance = ref<number>(0)
/** §FESUITE (V0577): the live balance got no answer. It used to become { balance: '0' }: "Live balance 0.00" and a
 *  "Mismatch" alarm (or "✓ Reconciled" when the statement also summed to zero) over a balance nobody had read. */
const balanceFailed = ref(false)
/** the statement itself could not be read (its error shows): no sum, no balance, no "No transactions yet" under it */
const statementUnread = computed(() => !!error.value && !transactions.value.length)
const totalCount = ref(0)
const offset = ref(0)
const pageLimit = 100
const loadedFullPage = ref(false)

const activeFilter = ref<string | null>(null)
const searchQuery = ref('')

const gradientId = `st-grad-${Math.random().toString(36).slice(2, 8)}`

const FILTERS: { id: string | null; label: string; title: string }[] = [
  { id: null,         label: 'All',      title: 'All transactions' },
  { id: 'in',         label: 'In',       title: 'Receiver = this agent (incoming)' },
  { id: 'out',        label: 'Out',      title: 'Sender = this agent (outgoing)' },
  { id: 'transfer',   label: 'Transfer', title: 'Direct transfers' },
  { id: 'stake',      label: 'Lock',     title: 'Locks and unlocks' },
  { id: 'reward',     label: 'Payout',   title: 'Payouts received' },
  { id: 'mint',       label: 'Issued',   title: 'Units issued' },
  { id: 'funding',    label: 'Funding',  title: 'Treasury funding' },
]

// ── Lifecycle ─────────────────────────────────────────────────────
onMounted(() => {
  // No interval polling here — statement is mostly static and large; user can hit Refresh.
})

onBeforeUnmount(() => {
  // No cleanup needed
})

watch(() => props.agentDid, () => {
  reset()
  if (expanded.value) void refresh()
})

watch(() => expanded.value, (v) => {
  if (v && !transactions.value.length && !loading.value) {
    void refresh()
  }
})

function reset() {
  transactions.value = []
  liveBalance.value = 0
  balanceFailed.value = false
  totalCount.value = 0
  offset.value = 0
  loadedFullPage.value = false
  error.value = null
  activeFilter.value = null
  searchQuery.value = ''
}

async function refresh() {
  if (!props.agentDid) return
  if (!props.hasAgentToken) {
    error.value = 'Agent JWT not active. Switch to this agent above to load its statement.'
    return
  }
  loading.value = true
  error.value = null
  offset.value = 0
  try {
    const [hist, balResp] = await Promise.all([
      tegService.getTransactions({ limit: pageLimit, offset: 0 }),
      tegService.getBalance().catch(() => null),
    ])
    transactions.value = hist.transactions || []
    totalCount.value = hist.total ?? transactions.value.length
    offset.value = transactions.value.length
    loadedFullPage.value = transactions.value.length >= pageLimit
    balanceFailed.value = balResp === null
    liveBalance.value = balResp === null ? 0 : Number((balResp as any).balance || 0)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load statement'
    uiStore.showError?.('Statement', error.value || 'Unknown')
  } finally {
    loading.value = false
  }
}

async function loadMore() {
  if (!props.agentDid || loadingMore.value) return
  loadingMore.value = true
  try {
    const hist = await tegService.getTransactions({ limit: pageLimit, offset: offset.value })
    if (hist.transactions?.length) {
      transactions.value.push(...hist.transactions)
      offset.value += hist.transactions.length
    }
    if (!hist.transactions?.length || hist.transactions.length < pageLimit) {
      loadedFullPage.value = false  // signals "no more"
    }
    totalCount.value = hist.total ?? transactions.value.length
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load more'
  } finally {
    loadingMore.value = false
  }
}

const hasMore = computed(() => loadedFullPage.value && transactions.value.length < totalCount.value)

// ── Filter + search ───────────────────────────────────────────────
const filteredTransactions = computed(() => {
  let list = transactions.value
  if (activeFilter.value === 'in') {
    list = list.filter(t => t.receiver_agent_id === props.agentDid && t.sender_agent_id !== props.agentDid)
  } else if (activeFilter.value === 'out') {
    list = list.filter(t => t.sender_agent_id === props.agentDid)
  } else if (activeFilter.value) {
    list = list.filter(t => (t.transaction_type || '').toLowerCase().includes(activeFilter.value!.toLowerCase()))
  }
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase()
    list = list.filter(t =>
      counterparty(t).toLowerCase().includes(q) ||
      (t.attached_message || '').toLowerCase().includes(q) ||
      t.transaction_id.toLowerCase().includes(q)
    )
  }
  return list
})

function clearFilters() {
  activeFilter.value = null
  searchQuery.value = ''
}

// ── Per-row roll-up balance ───────────────────────────────────────
/**
 * Computed running balance per displayed row, working forward from the
 * oldest visible transaction. Note: this is approximate — anchored to the
 * sum of visible txs with NO awareness of older rows beyond the page. The
 * reconciliation strip surfaces any mismatch vs live balance for transparency.
 */
const rollingBalance = computed<number[]>(() => {
  const out: number[] = []
  const list = filteredTransactions.value
  // Walk from the bottom (oldest) up; chronological forward sum.
  // Display order is descending (newest first) — so we sum bottom-up,
  // then the index i corresponds to balance AFTER tx[i].
  let balance = 0
  for (let i = list.length - 1; i >= 0; i--) {
    const tx = list[i]
    balance += signedAmount(tx)
    out[i] = balance
  }
  return out
})

const runningBalance = computed(() => {
  // Sum across ALL transactions (not filtered) — reconciliation target
  let s = 0
  for (const tx of transactions.value) s += signedAmount(tx)
  return s
})

const reconcileDelta = computed(() => Math.abs(runningBalance.value - liveBalance.value))
/**
 * true  — sum matches live balance within 0.0001 AVT tolerance
 * false — mismatch
 * null  — pending (no data)
 */
const reconcileMatches = computed<boolean | null>(() => {
  if (!transactions.value.length) return null
  if (balanceFailed.value) return null
  if (liveBalance.value === 0 && runningBalance.value === 0) return true
  return reconcileDelta.value < 0.0001
})

// ── Chart math ────────────────────────────────────────────────────
const chartW = 900
const chartH = 90

const chartPoints = computed<{ x: number; y: number; balance: number; t: number }[]>(() => {
  const list = transactions.value
  if (list.length < 2) return []
  // Walk oldest → newest, accumulating balance
  const points: { x: number; y: number; balance: number; t: number }[] = []
  const oldestT = new Date(list[list.length - 1].timestamp).getTime()
  const newestT = new Date(list[0].timestamp).getTime()
  const span = Math.max(1, newestT - oldestT)
  let bal = 0
  for (let i = list.length - 1; i >= 0; i--) {
    const tx = list[i]
    bal += signedAmount(tx)
    const t = new Date(tx.timestamp).getTime()
    points.push({ x: ((t - oldestT) / span) * chartW, y: 0, balance: bal, t })
  }
  // Now compute Y from balances
  const balances = points.map(p => p.balance)
  const min = Math.min(...balances)
  const max = Math.max(...balances)
  const yspan = Math.max(0.0001, max - min)
  for (const p of points) {
    p.y = chartH - ((p.balance - min) / yspan) * (chartH - 6) - 3
  }
  return points
})

const chartMin = computed(() => chartPoints.value.length ? Math.min(...chartPoints.value.map(p => p.balance)) : 0)
const chartMax = computed(() => chartPoints.value.length ? Math.max(...chartPoints.value.map(p => p.balance)) : 0)

const chartLinePath = computed(() => {
  const pts = chartPoints.value
  if (pts.length < 2) return ''
  return pts.map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`)).join(' ')
})
const chartAreaPath = computed(() => {
  const pts = chartPoints.value
  if (pts.length < 2) return ''
  const line = pts.map((p, i) => (i === 0 ? `M ${p.x} ${p.y}` : `L ${p.x} ${p.y}`)).join(' ')
  return `${line} L ${pts[pts.length - 1].x} ${chartH} L ${pts[0].x} ${chartH} Z`
})
const chartRangeLabel = computed(() => {
  if (transactions.value.length < 2) return '—'
  const oldest = new Date(transactions.value[transactions.value.length - 1].timestamp)
  const newest = new Date(transactions.value[0].timestamp)
  const days = Math.max(1, Math.round((newest.getTime() - oldest.getTime()) / 86_400_000))
  return days < 60 ? `${days}d` : `${Math.round(days / 30)}mo`
})

// ── Helpers ───────────────────────────────────────────────────────

function signedAmount(tx: TEGTransaction): number {
  const a = Number(tx.amount || 0)
  const f = Number(tx.fee_amount || 0)
  if (tx.sender_agent_id === props.agentDid) return -(a + f)  // outgoing: amount + fee
  return a  // incoming
}

function amountValue(tx: TEGTransaction): number {
  return Math.abs(signedAmount(tx))
}
function amountSign(tx: TEGTransaction): string {
  return signedAmount(tx) > 0 ? '+' : signedAmount(tx) < 0 ? '−' : ''
}
function amountClass(tx: TEGTransaction): string {
  const s = signedAmount(tx)
  if (s > 0) return 'st-amount--in'
  if (s < 0) return 'st-amount--out'
  return ''
}
function counterparty(tx: TEGTransaction): string {
  if (tx.sender_agent_id === props.agentDid) return tx.receiver_agent_id || '—'
  return tx.sender_agent_id || 'system'
}

function typeLabel(tx: TEGTransaction): string {
  return (tx.transaction_type || 'transfer').toLowerCase()
}
function typeChipClass(tx: TEGTransaction): string {
  const t = typeLabel(tx)
  if (t.includes('stake')) return 'st-type-pill--violet'
  if (t.includes('reward')) return 'st-type-pill--ok'
  if (t.includes('mint')) return 'st-type-pill--soft'
  if (t.includes('funding')) return 'st-type-pill--cyan'
  if (t.includes('system') || t.includes('dispute')) return 'st-type-pill--muted'
  return 'st-type-pill--cyan'
}
function rowClass(tx: TEGTransaction): string {
  const s = signedAmount(tx)
  if (s > 0) return 'st-row--in'
  if (s < 0) return 'st-row--out'
  return ''
}

function shortId(s: string): string {
  if (!s) return ''
  if (s.length <= 12) return s
  return `${s.slice(0, 6)}…${s.slice(-4)}`
}
function shortDid(d: string): string {
  if (!d) return '—'
  if (d.length <= 32) return d
  return `${d.slice(0, 16)}…${d.slice(-8)}`
}
function formatAmount(n: number | string): string {
  const v = typeof n === 'number' ? n : Number(n || 0)
  if (Number.isNaN(v)) return '0'
  return v.toLocaleString(appLocale(), { maximumFractionDigits: 4 })
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (ms < 60_000) return `${Math.floor(ms / 1_000)}s ago`
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}

async function copyText(s: string) {
  try {
    await navigator.clipboard.writeText(s)
    uiStore.showSuccess?.('Copied', s.length > 40 ? s.slice(0, 40) + '…' : s)
  } catch { /* expected */ }
}

function exportCsv() {
  const list = filteredTransactions.value
  if (!list.length) return
  const header = ['timestamp', 'transaction_type', 'sender', 'receiver', 'amount', 'fee_amount', 'status', 'transaction_id', 'message']
  const rows = list.map(tx => [
    tx.timestamp,
    tx.transaction_type || 'transfer',
    tx.sender_agent_id || '',
    tx.receiver_agent_id || '',
    tx.amount,
    tx.fee_amount || '',
    tx.status,
    tx.transaction_id,
    (tx.attached_message || '').replace(/[\r\n,"]/g, ' '),
  ])
  const csv = '﻿' + [header, ...rows].map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `statement-${(props.agentDid || 'agent').slice(0, 16)}-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 4000)
  uiStore.showSuccess?.('Exported', `${list.length} transactions downloaded.`)
}
</script>

<style scoped>
.st-section {
  margin-top: 14px;
  background: rgba(10, 13, 22, 0.5);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 8px;
  overflow: hidden;
}
.st-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.7rem 1rem;
  cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  letter-spacing: 0.12em;
  font-weight: 600;
  color: rgba(var(--nc-primary-rgb), 0.85);
  background: rgba(var(--nc-primary-rgb), 0.04);
  transition: background 0.15s;
}
.st-header:hover { background: rgba(var(--nc-primary-rgb), 0.08); }
.st-glyph { font-size: 1rem; color: rgba(var(--nc-primary-rgb), 0.95); }
.st-count {
  background: rgba(var(--nc-primary-rgb), 0.15);
  color: rgba(var(--nc-primary-rgb), 1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 0.65rem;
  font-weight: 700;
}
.st-flex { flex: 1; }
.st-toggle {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  color: rgba(var(--nc-primary-rgb), 0.5);
}

.st-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
}
.st-pill--ok  { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.st-pill--err { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger); border-color: rgba(255, 51, 102, 0.3); }

.st-body {
  padding: 0.85rem 1rem 1rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

.st-note {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.85rem 1rem;
  background: rgba(99, 179, 237, 0.06);
  border: 1px solid rgba(99, 179, 237, 0.2);
  border-radius: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.75);
}
.st-note-icon {
  width: 18px; height: 18px;
  border-radius: 50%;
  background: rgba(99, 179, 237, 0.25);
  color: rgba(99, 179, 237, 1);
  display: inline-flex; align-items: center; justify-content: center;
  font-weight: 700;
}

/* ── Reconciliation strip ──────────────────────── */
.st-recon-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0.5rem 0.85rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 5px;
}
.st-recon-strip--err {
  background: rgba(255, 51, 102, 0.05);
  border-color: rgba(255, 51, 102, 0.25);
}
.st-recon-cell { display: flex; flex-direction: column; gap: 0.18rem; }
.st-recon-cell--note { justify-content: center; }
.st-recon-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  text-transform: uppercase;
}
.st-recon-value {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.95rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
}
.st-recon-status {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
}
.st-text-ok { color: var(--nc-success); }
.st-text-err { color: var(--nc-danger); }
.st-text-muted { color: var(--nc-text-muted); }

/* ── Chart ───────────────────────────────────── */
.st-chart-wrap {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 5px;
}
.st-chart {
  display: block;
  width: 100%;
  height: 100px;
}
.st-chart-grid {
  stroke: rgba(var(--nc-primary-rgb), 0.06);
  stroke-width: 1;
}
.st-chart-line {
  fill: none;
  stroke: rgba(var(--nc-primary-rgb), 0.95);
  stroke-width: 1.8;
  stroke-linejoin: round;
  stroke-linecap: round;
  filter: drop-shadow(0 0 3px rgba(var(--nc-primary-rgb), 0.4));
}
.st-chart-dot {
  fill: rgba(var(--nc-primary-rgb), 1);
  stroke: rgba(var(--nc-primary-rgb), 0.4);
  stroke-width: 2;
}
.st-chart-meta {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
}
.st-chart-meta-key {
  color: var(--nc-text-muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-size: 0.55rem;
}
.st-chart-meta-val {
  color: rgba(255, 255, 255, 0.85);
  font-weight: 600;
}
.st-chart-meta-spacer { flex: 1; }

/* ── Toolbar ──────────────────────────────────── */
.st-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.85rem;
  padding-bottom: 0.6rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.st-toolbar-left, .st-toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
.st-toolbar-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb), 0.55);
  font-weight: 600;
  margin-right: 0.25rem;
}
.st-search {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.85);
  border-radius: 4px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  padding: 4px 9px;
  outline: none;
  transition: border-color 0.15s;
  width: 220px;
}
.st-search:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.5);
}

.st-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.06em;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--nc-primary-rgb), 0.04);
  cursor: pointer;
  transition: all 0.15s;
}
.st-chip:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.4);
  color: rgba(255, 255, 255, 0.95);
}
.st-chip--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  color: rgba(var(--nc-primary-rgb), 1);
}

.st-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  letter-spacing: 0.08em;
  font-weight: 600;
  padding: 5px 12px;
  border-radius: 4px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.st-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.st-btn--ghost {
  background: transparent;
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.st-btn--ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  color: rgba(var(--nc-primary-rgb), 1);
}
.st-btn--primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
}
.st-btn--primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.3);
}

.st-error {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.3);
  color: var(--nc-danger);
  padding: 0.5rem 0.85rem;
  border-radius: 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
}
.st-error span { flex: 1; min-width: 0; }

/* ── Skeleton ────────────────────────────── */
.st-skeleton { display: flex; flex-direction: column; gap: 0.4rem; }
.st-skel-row {
  height: 28px;
  border-radius: 4px;
  background: linear-gradient(90deg,
    rgba(var(--nc-primary-rgb), 0.05) 0%,
    rgba(var(--nc-primary-rgb), 0.12) 50%,
    rgba(var(--nc-primary-rgb), 0.05) 100%);
  background-size: 200% 100%;
  animation: st-shimmer 1.4s linear infinite;
}
@keyframes st-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

/* ── Empty ──────────────────────────────── */
.st-empty {
  text-align: center;
  padding: 1.6rem 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.st-empty-glyph { font-size: 1.8rem; opacity: 0.5; margin-bottom: 0.4rem; }
.st-empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.85rem;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.25rem;
}
.st-empty-sub {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-text-muted);
  max-width: 36rem;
  margin-bottom: 0.6rem;
  line-height: 1.5;
}

/* ── Transaction list ─────────────────────── */
.st-list {
  display: flex;
  flex-direction: column;
  max-height: 32rem;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb), 0.2) transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 5px;
}
.st-list::-webkit-scrollbar { width: 5px; }
.st-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), 0.25); border-radius: 3px; }
.st-list-head {
  display: grid;
  grid-template-columns: 90px 95px minmax(140px, 1.4fr) 100px 70px 110px minmax(110px, 0.9fr);
  gap: 0.5rem;
  align-items: center;
  padding: 6px 12px;
  background: rgba(var(--nc-primary-rgb), 0.06);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  position: sticky;
  top: 0;
  z-index: 1;
}
.st-th {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  letter-spacing: 0.12em;
  color: var(--nc-text-muted);
  font-weight: 600;
  text-transform: uppercase;
}
.st-th--amount, .st-th--fee, .st-th--bal { text-align: right; }

.st-row {
  display: grid;
  grid-template-columns: 90px 95px minmax(140px, 1.4fr) 100px 70px 110px minmax(110px, 0.9fr);
  gap: 0.5rem;
  align-items: center;
  padding: 6px 12px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.85);
  transition: background 0.1s;
}
.st-row:last-child { border-bottom: none; }
.st-row:hover { background: rgba(var(--nc-primary-rgb), 0.04); }
.st-row--in  { /* could add subtle accent */ }
.st-row--out { /* could add subtle accent */ }

.st-cell--time { color: var(--nc-text-muted); font-size: 0.65rem; }
/* §TWOAGENT V0441: a long ledger type (reward_fund_guild_refund) spilled out of its 95px track over the counterparty;
   the cell clips and the pill ellipsizes, its full name in the title. */
.st-cell--type { min-width: 0; overflow: hidden; }
.st-cell--amount, .st-cell--fee, .st-cell--bal { text-align: right; font-weight: 600; }
.st-amount--in  { color: var(--nc-success); }
.st-amount--out { color: var(--nc-danger); }
.st-cell--bal { color: rgba(255, 255, 255, 0.7); }
.st-cell--id {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
}
.st-cell--id code {
  background: rgba(var(--nc-primary-rgb), 0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.65rem;
  white-space: nowrap;
}
.st-cell--party {
  font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.7);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.st-type-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid transparent;
  text-transform: uppercase;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
.st-type-pill--cyan   { background: rgba(var(--nc-primary-rgb), 0.1); color: rgba(var(--nc-primary-rgb), 1); border-color: rgba(var(--nc-primary-rgb), 0.3); }
.st-type-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.st-type-pill--ok     { background: rgba(0, 255, 136, 0.1); color: var(--nc-success); border-color: rgba(0, 255, 136, 0.3); }
.st-type-pill--soft   { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning); border-color: rgba(255, 149, 0, 0.3); }
.st-type-pill--muted  { background: rgba(var(--nc-primary-rgb), 0.06); color: rgba(255, 255, 255, 0.55); border-color: rgba(var(--nc-primary-rgb), 0.18); }

.st-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--nc-primary-rgb), 0.7);
  font-family: monospace;
  font-size: 0.7rem;
  padding: 0 4px;
  cursor: pointer;
  transition: all 0.12s;
}
.st-icon-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: rgba(var(--nc-primary-rgb), 1);
}

/* ── Footer ──────────────────────────────── */
.st-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
}
.st-footer-loading { font-style: italic; }

/* ── Responsive ─────────────────────────── */
@media (max-width: 1024px) {
  .st-list-head, .st-row { grid-template-columns: 80px 80px minmax(80px, 1fr) 90px 60px 100px 80px; }
  .st-cell--id code { font-size: 0.6rem; }
}
@media (max-width: 768px) {
  /* Collapse fee + balance columns; show on row click would be future polish */
  .st-list-head, .st-row {
    grid-template-columns: 70px 70px minmax(60px, 1fr) 80px 80px;
  }
  .st-th--fee, .st-th--bal, .st-cell--fee, .st-cell--bal { display: none; }
  .st-search { width: 100%; }
  .st-toolbar-right { width: 100%; }
}
</style>
