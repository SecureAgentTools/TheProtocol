<template>
  <!-- Build #14 (2026-05-08): ZKP Attestation Analytics.
       Surfaces circuit distribution, verified/expired/revoked breakdown,
       submission cadence, recent activity. Renders empty-state gracefully
       (ZKP phases are infrastructure-ready but not yet wired to live data). -->
  <div class="aa">
    <div class="aa-ambient">
      <div class="aa-grid"></div>
      <div class="aa-glow aa-glow-1"></div>
      <div class="aa-glow aa-glow-2"></div>
    </div>

    <section class="aa-hero">
      <div class="aa-hero-inner">
        <div class="aa-chip"><span class="aa-chip-dot"></span>{{ t('adminAttestationAnalyticsView.hero.chip') }}</div>
        <h1 class="aa-h1">{{ t('adminAttestationAnalyticsView.hero.h1a') }}<span class="aa-accent">{{ t('adminAttestationAnalyticsView.hero.h1Accent') }}</span></h1>
        <p class="aa-lead">{{ t('adminAttestationAnalyticsView.hero.lead') }}</p>

        <div class="aa-toolbar">
          <div class="aa-toolbar-group">
            <span class="aa-toolbar-label">{{ t('adminAttestationAnalyticsView.toolbar.period') }}</span>
            <button
              v-for="p in PERIODS" :key="p.value"
              class="aa-period-btn"
              :class="{ 'aa-period-btn--active': period === p.value }"
              :disabled="loading"
              @click="setPeriod(p.value)"
            >{{ p.label }}</button>
          </div>

          <span class="aa-toolbar-spacer"></span>

          <div class="aa-toolbar-group">
            <label class="aa-toggle">
              <input type="checkbox" v-model="autoRefresh" />
              <span class="aa-toggle-track"><span class="aa-toggle-knob"></span></span>
              <span class="aa-toggle-label">{{ t('common.autoRefresh60s') }}</span>
            </label>
          </div>
          <div class="aa-toolbar-group aa-toolbar-meta">
            <span class="aa-toolbar-label">{{ t('adminAttestationAnalyticsView.toolbar.last') }}</span>
            <span class="aa-toolbar-val">{{ lastRefreshAt || '—' }}</span>
            <button class="aa-btn aa-btn--ghost" :disabled="loading" @click="refresh">↻</button>
            <button class="aa-btn aa-btn--ghost" :disabled="!data || data.recent.length === 0" @click="exportCsv">⤓ CSV</button>
          </div>
        </div>
      </div>
    </section>

    <div class="aa-body">
      <div v-if="loading && !data" class="aa-center">
        <div class="aa-spinner"></div>
        <p class="aa-loading-text">Loading attestation data…</p>
      </div>

      <div v-else-if="error && !data" class="aa-center">
        <p class="aa-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
        <button class="aa-btn aa-btn--ghost" @click="refresh">Retry</button>
      </div>

      <template v-else-if="data">
        <!-- §FESUITE (V0578): the figures below are the last answer; when the latest read failed it says so here, not
             only in a toast that is gone in seconds -->
        <ReadFailedNotice v-if="error" dense data-testid="aa-stale" :retry="refresh"
          :text="`The attestation analytics could not be read just now. What follows is from the read at ${lastRefreshAt || 'an earlier time'}.`" />
        <!-- ZKP phase status banner -->
        <div class="aa-phase-banner" :class="phaseBannerClass">
          <span class="aa-phase-glyph">{{ allPhasesEnabled ? '✓' : '◌' }}</span>
          <div class="aa-phase-text">
            <strong>ZKP infrastructure</strong>
            <span v-if="enabledPhasesCount === 0">: no phase on (<code>ZKP_PHASE_1..5_ENABLED=false</code>). Proofs still verify; nothing is kept and nothing is granted.</span>
            <span v-else-if="allPhasesEnabled">: all {{ phaseCount }} phases on. Kept, expiring and revocable, trust chain, signed bundles, schedules.</span>
            <span v-else>: {{ enabledPhasesCount }}/{{ phaseCount }} phases on.</span>
          </div>
          <span class="aa-phase-pills">
            <span v-for="(on, k) in data.zkp_phases" :key="k" class="aa-pill" :class="on ? 'aa-pill--green' : 'aa-pill--muted'">
              {{ k.replace('phase_', 'P') }}
            </span>
          </span>
        </div>

        <!-- Hero stats -->
        <div class="aa-stats">
          <div class="aa-stat-card">
            <div class="aa-stat-key">{{ t('adminAttestationAnalyticsView.stats.attestations') }}</div>
            <div class="aa-stat-val aa-stat-val--cyan">{{ data.stats.total.toLocaleString(appLocale()) }}</div>
            <div class="aa-stat-sub aa-stat-sub-grid">
              <span v-if="data.stats.verified > 0" class="aa-pill aa-pill--green">✓ {{ data.stats.verified }}</span>
              <span v-if="data.stats.failed > 0" class="aa-pill aa-pill--red">✕ {{ data.stats.failed }}</span>
            </div>
          </div>

          <div class="aa-stat-card">
            <div class="aa-stat-key">{{ t('adminAttestationAnalyticsView.stats.active') }}</div>
            <div class="aa-stat-val aa-stat-val--green">{{ data.stats.active.toLocaleString(appLocale()) }}</div>
            <div class="aa-stat-sub">
              <span v-if="data.stats.expiring_24h > 0" class="aa-pill aa-pill--warn">{{ data.stats.expiring_24h }} expiring &lt;24h</span>
              <span v-else>verified, not revoked, in window</span>
            </div>
          </div>

          <div class="aa-stat-card">
            <div class="aa-stat-key">{{ t('adminAttestationAnalyticsView.stats.expiredRevoked') }}</div>
            <div class="aa-stat-val" :class="(data.stats.expired + data.stats.revoked) > 0 ? 'aa-stat-val--warn' : 'aa-stat-val--muted'">
              {{ (data.stats.expired + data.stats.revoked).toLocaleString(appLocale()) }}
            </div>
            <div class="aa-stat-sub aa-stat-sub-grid">
              <span v-if="data.stats.expired > 0" class="aa-pill aa-pill--warn"><Icon name="mdi:timer-sand" /> {{ data.stats.expired }} expired</span>
              <span v-if="data.stats.revoked > 0" class="aa-pill aa-pill--red">⊘ {{ data.stats.revoked }} revoked</span>
              <span v-if="data.stats.expired === 0 && data.stats.revoked === 0">none</span>
            </div>
          </div>

          <div class="aa-stat-card">
            <div class="aa-stat-key">{{ t('adminAttestationAnalyticsView.stats.circuits') }}</div>
            <div class="aa-stat-val aa-stat-val--violet">{{ data.stats.circuits_available }}</div>
            <div class="aa-stat-sub">{{ data.by_circuit.length }} with attestations</div>
          </div>
        </div>

        <!-- Submission cadence sparkline -->
        <div v-if="data.cadence.length > 0" class="aa-section">
          <div class="aa-section-head">
            <span class="aa-section-title">SUBMISSION CADENCE · {{ periodLabel }}</span>
          </div>
          <div class="aa-spark-wrap">
            <svg
              :viewBox="`0 0 ${SPARK_W} ${SPARK_H}`"
              class="aa-spark"
              preserveAspectRatio="none"
              role="img"
              aria-label="Attestation submission cadence"
            >
              <g class="aa-spark-grid">
                <line v-for="g in 4" :key="`g-${g}`"
                  :x1="0" :x2="SPARK_W"
                  :y1="(SPARK_H / 4) * g" :y2="(SPARK_H / 4) * g" />
              </g>
              <g v-if="cadenceMax > 0">
                <rect
                  v-for="(p, i) in data.cadence" :key="i"
                  :x="(SPARK_W / data.cadence.length) * i + 1"
                  :y="SPARK_H - (p.submitted / cadenceMax) * (SPARK_H - 4) - 2"
                  :width="(SPARK_W / data.cadence.length) - 2"
                  :height="(p.submitted / cadenceMax) * (SPARK_H - 4)"
                  class="aa-spark-bar"
                />
              </g>
            </svg>
            <div v-if="cadenceMax === 0" class="aa-spark-empty">No submissions in this window.</div>
          </div>
        </div>

        <!-- Two-column: by-circuit + top agents -->
        <div class="aa-twocol">
          <!-- By circuit -->
          <div class="aa-section">
            <div class="aa-section-head">
              <span class="aa-section-title">BY CIRCUIT</span>
              <span class="aa-section-sub">{{ data.by_circuit.length }} of {{ data.stats.circuits_available }} active</span>
            </div>
            <div v-if="data.by_circuit.length > 0" class="aa-list">
              <div v-for="c in circuitRows" :key="`${c.circuit_id}@${c.circuit_version}`" class="aa-circuit-row">
                <span class="aa-circuit-id">
                  <code>{{ c.circuit_id }}</code>
                  <span class="aa-circuit-version">v{{ versionLabel(c.circuit_version) }}<template v-if="isRetired(c.circuit_id)"> · <span data-test="circuit-retired" :title="retiredHint(c.circuit_id)">retired</span></template></span>
                </span>
                <span class="aa-bar">
                  <span class="aa-bar-fill" :style="{ width: c.pct + '%' }"></span>
                </span>
                <span class="aa-bar-val">{{ c.count }}</span>
                <span class="aa-bar-pct">{{ c.pct.toFixed(0) }}%</span>
              </div>
            </div>
            <div v-else class="aa-empty-mini">
              <p>No attestations submitted yet.</p>
              <template v-if="circuitsRead === 'ok'">
                <p class="aa-empty-sub">Available circuits ({{ availableCircuits.length }}):</p>
                <ul class="aa-circuit-listing">
                  <li v-for="c in availableCircuits" :key="c.circuit_id">
                    <code>{{ c.circuit_id }}</code>
                    <span class="aa-circuit-name">{{ c.name }}</span>
                    <span v-if="isRetired(c.circuit_id)" class="aa-circuit-name" data-test="circuit-retired">retired, use {{ circuitSuccessor(c.circuit_id, availableCircuits) }}</span>
                  </li>
                </ul>
              </template>
              <ReadFailedNotice v-else-if="circuitsRead === 'failed'" dense data-testid="aa-circuits-failed"
                text="The available circuits could not be read just now." :retry="loadCircuits" />
            </div>
          </div>

          <!-- Top agents -->
          <div class="aa-section">
            <div class="aa-section-head">
              <span class="aa-section-title">TOP AGENTS</span>
              <span class="aa-section-sub">most-attested (top 10)</span>
            </div>
            <div v-if="data.top_agents.length > 0" class="aa-list">
              <div v-for="(a, i) in data.top_agents" :key="a.agent_did" class="aa-agent-row">
                <span class="aa-agent-rank">#{{ i + 1 }}</span>
                <code class="aa-agent-did" :title="a.agent_did">{{ shortDid(a.agent_did) }}</code>
                <span class="aa-agent-count">{{ a.count }}<span class="aa-agent-count-unit"> attest.</span></span>
                <button class="aa-icon-btn" @click.stop="goToEventStore(a.agent_did)" title="Open in EventStore">⤴</button>
              </div>
            </div>
            <div v-else class="aa-empty-mini">No agents have submitted yet.</div>
          </div>
        </div>

        <!-- Recent attestations -->
        <div class="aa-section">
          <div class="aa-section-head">
            <span class="aa-section-title">RECENT ATTESTATIONS · {{ periodLabel }}</span>
            <span class="aa-section-sub">most recent {{ data.recent.length }} (max 50)</span>
          </div>
          <div v-if="data.recent.length === 0" class="aa-empty-mini">
            <p>No attestations submitted in the last {{ periodLabel.toLowerCase() }}.</p>
            <p class="aa-empty-sub">When agents submit via SDK, they appear here.</p>
          </div>
          <div v-else class="aa-feed-list">
            <div
              v-for="r in data.recent" :key="r.id"
              class="aa-feed-row"
              :class="{ 'aa-feed-row--expanded': expandedId === r.id }"
              @click="toggleExpand(r.id)"
            >
              <div class="aa-feed-head">
                <span class="aa-feed-time" :title="r.submitted_at || ''">{{ formatHHMMSS(r.submitted_at) }}</span>
                <span class="aa-feed-date">{{ formatDate(r.submitted_at) }}</span>
                <span class="aa-status-pill" :class="rowStatusClass(r)">{{ rowStatusLabel(r) }}</span>
                <span v-if="r.is_active" class="aa-pill aa-pill--green">ACTIVE</span>
                <span class="aa-pill aa-pill--violet">{{ shortCircuit(r.circuit_id) }}</span>
                <span v-if="isRetired(r.circuit_id)" class="aa-pill aa-pill--muted" :title="retiredHint(r.circuit_id)">RETIRED</span>
                <code class="aa-feed-did" :title="r.agent_did">{{ shortDid(r.agent_did) }}</code>
                <span class="aa-feed-spacer"></span>
                <span v-if="r.expires_at" class="aa-feed-meta">expires <strong>{{ formatRel(r.expires_at) }}</strong></span>
                <span class="aa-feed-caret">{{ expandedId === r.id ? '▾' : '▸' }}</span>
              </div>

              <div v-if="expandedId === r.id" class="aa-feed-detail" @click.stop>
                <div class="aa-detail-grid">
                  <div class="aa-detail-pair">
                    <span class="aa-detail-key">Attestation ID</span>
                    <span class="aa-detail-val">
                      <code>{{ r.id }}</code>
                      <button class="aa-icon-btn" @click.stop="copyText(r.id)" title="Copy">⎘</button>
                    </span>
                  </div>
                  <div class="aa-detail-pair">
                    <span class="aa-detail-key">Agent DID</span>
                    <span class="aa-detail-val">
                      <code>{{ r.agent_did }}</code>
                      <button class="aa-icon-btn" @click.stop="goToEventStore(r.agent_did)" title="Open in EventStore">⤴</button>
                    </span>
                  </div>
                  <div class="aa-detail-pair">
                    <span class="aa-detail-key">Circuit</span>
                    <span class="aa-detail-val">
                      <code>{{ r.circuit_id }}</code>
                      <span class="aa-circuit-version">v{{ versionLabel(r.circuit_version) }}<template v-if="isRetired(r.circuit_id)"> · retired</template></span>
                    </span>
                  </div>
                  <div class="aa-detail-pair">
                    <span class="aa-detail-key">Verified</span>
                    <span class="aa-detail-val" :class="r.verified ? 'aa-detail-val--ok' : 'aa-detail-val--err'">{{ r.verified ? 'yes' : 'no' }}</span>
                  </div>
                  <div v-if="r.submitted_at" class="aa-detail-pair">
                    <span class="aa-detail-key">Submitted</span>
                    <span class="aa-detail-val">{{ formatAbs(r.submitted_at) }}</span>
                  </div>
                  <div v-if="r.verified_at" class="aa-detail-pair">
                    <span class="aa-detail-key">Verified at</span>
                    <span class="aa-detail-val">{{ formatAbs(r.verified_at) }}</span>
                  </div>
                  <div v-if="r.expires_at" class="aa-detail-pair">
                    <span class="aa-detail-key">Expires</span>
                    <span class="aa-detail-val" :class="isExpired(r) ? 'aa-detail-val--warn' : ''">{{ formatAbs(r.expires_at) }}</span>
                  </div>
                  <div v-if="r.revoked_at" class="aa-detail-pair">
                    <span class="aa-detail-key">Revoked at</span>
                    <span class="aa-detail-val aa-detail-val--err">{{ formatAbs(r.revoked_at) }}</span>
                  </div>
                  <div v-if="r.revoked_by" class="aa-detail-pair">
                    <span class="aa-detail-key">Revoked by</span>
                    <span class="aa-detail-val"><code>{{ r.revoked_by }}</code></span>
                  </div>
                  <div v-if="r.policy_parameters_hash" class="aa-detail-pair">
                    <span class="aa-detail-key">Policy params hash</span>
                    <span class="aa-detail-val">
                      <code>{{ r.policy_parameters_hash.slice(0, 24) }}…</code>
                      <button class="aa-icon-btn" @click.stop="copyText(r.policy_parameters_hash!)" title="Copy">⎘</button>
                    </span>
                  </div>
                </div>
                <div v-if="r.failure_reason" class="aa-detail-section">
                  <span class="aa-detail-key">Failure reason</span>
                  <pre class="aa-detail-pre aa-detail-pre--err">{{ r.failure_reason }}</pre>
                </div>
                <div v-if="r.revoked_reason" class="aa-detail-section">
                  <span class="aa-detail-key">Revocation reason</span>
                  <pre class="aa-detail-pre">{{ r.revoked_reason }}</pre>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="aa-footer">
          <code>/admin/attestations/analytics?period={{ data.period }}</code>
          <span> · admin_platform gated · as of {{ formatAbs(data.as_of) }}</span>
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
 * AdminAttestationAnalytics — ZKP Attestation Observatory
 *
 * Build #14 (2026-05-08). Backend: /admin/attestations/analytics.
 * Renders empty state gracefully (ZKP phases gated; data starts when
 * agents submit via SDK with ZKP_PHASE_*_ENABLED=true).
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import {
  attestationsAdminService,
  type AttestationPeriod,
  type AttestationAnalytics,
  type AttestationRow,
  type CircuitListEntry,
} from '@/services/api/attestationsAdmin'
import { isRetiredCircuit, circuitSuccessor } from '@/services/api/attestations'
import { downloadCsv, csvFilenameTimestamp, type CsvColumn } from '@/components/common/csvExport'

const { t } = useI18n()
const uiStore = useUIStore()
const router = useRouter()

const PERIODS: { value: AttestationPeriod; label: string }[] = [
  { value: '24h', label: '24h' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All' },
]

const SPARK_W = 1000
const SPARK_H = 100

const period = ref<AttestationPeriod>('30d')
const data = ref<AttestationAnalytics | null>(null)
const availableCircuits = ref<CircuitListEntry[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const autoRefresh = ref(true)
const expandedId = ref<string | null>(null)
// §FESUITE (V0578): the period the figures on screen answer. A failed read after a period change kept the previous
// window's figures under the new period's label ("No attestations submitted in the last 7 days" for a window never read).
// (Two reads for different periods cannot overlap: the period buttons are disabled while a read is out.)
const dataPeriod = ref<AttestationPeriod | null>(null)
// the circuits list has its own read: "Available circuits (0)" was drawn for a list that never answered
const circuitsRead = ref<'unread' | 'ok' | 'failed'>('unread')
async function loadCircuits() {
  try {
    availableCircuits.value = await attestationsAdminService.listCircuits()
    circuitsRead.value = 'ok'
  } catch {
    availableCircuits.value = []
    circuitsRead.value = 'failed'
  }
}

let pollHandle: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  void refresh()
  // Pre-fetch the available circuits — used in empty state
  void loadCircuits()
  pollHandle = setInterval(() => {
    if (!autoRefresh.value) return
    if (document.visibilityState === 'hidden') return
    void refresh()
  }, 60_000)
})
onBeforeUnmount(() => { if (pollHandle) clearInterval(pollHandle) })

watch([period], () => { void refresh() })

async function refresh() {
  const asked = period.value
  loading.value = true
  error.value = null
  try {
    data.value = await attestationsAdminService.analytics(asked)
    dataPeriod.value = asked
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load analytics'
    // figures that answer another window are not this window's answer
    if (dataPeriod.value !== asked) { data.value = null; dataPeriod.value = null }
    uiStore.showError?.('Attestations', error.value!)
  } finally {
    loading.value = false
  }
}

function setPeriod(p: AttestationPeriod) {
  if (period.value === p) return
  period.value = p
}
function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

const periodLabel = computed(() => PERIODS.find(p => p.value === period.value)?.label || period.value)

const cadenceMax = computed(() => {
  if (!data.value || !data.value.cadence.length) return 0
  return Math.max(...data.value.cadence.map(c => c.submitted))
})

const enabledPhasesCount = computed(() => {
  if (!data.value) return 0
  return Object.values(data.value.zkp_phases).filter(v => v).length
})
// Counted against the phases the registry reports: five since V0613, six on an older one.
const phaseCount = computed(() => (data.value ? Object.keys(data.value.zkp_phases).length : 0))
const allPhasesEnabled = computed(() => phaseCount.value > 0 && enabledPhasesCount.value === phaseCount.value)
const phaseBannerClass = computed(() => {
  if (allPhasesEnabled.value) return 'aa-phase-banner--ok'
  if (enabledPhasesCount.value > 0) return 'aa-phase-banner--partial'
  return 'aa-phase-banner--idle'
})

const circuitRows = computed(() => {
  if (!data.value || !data.value.by_circuit.length) return []
  const total = data.value.stats.total || 1
  return data.value.by_circuit.map(c => ({
    ...c,
    pct: (c.count / total) * 100,
  }))
})

function exportCsv() {
  if (!data.value || !data.value.recent.length) return
  const cols: CsvColumn<AttestationRow>[] = [
    { label: 'ID', value: r => r.id },
    { label: 'Agent DID', value: r => r.agent_did },
    { label: 'Circuit', value: r => r.circuit_id },
    { label: 'Version', value: r => r.circuit_version },
    { label: 'Verified', value: r => r.verified },
    { label: 'Active', value: r => r.is_active },
    { label: 'Submitted', value: r => r.submitted_at },
    { label: 'Verified at', value: r => r.verified_at },
    { label: 'Expires', value: r => r.expires_at },
    { label: 'Revoked at', value: r => r.revoked_at },
    { label: 'Revoked by', value: r => r.revoked_by },
    { label: 'Revoked reason', value: r => r.revoked_reason },
    { label: 'Failure reason', value: r => r.failure_reason },
    { label: 'Policy params hash', value: r => r.policy_parameters_hash },
  ]
  downloadCsv(data.value.recent, cols, `attestations-${period.value}-${csvFilenameTimestamp()}`)
  uiStore.showSuccess?.('Exported', `${data.value.recent.length} rows`)
}

// ── Helpers ──
function shortDid(s: string | null | undefined): string {
  if (!s) return '—'
  if (s.length <= 26) return s
  return `${s.slice(0, 14)}…${s.slice(-6)}`
}
// v1.0.0 circuits are retired: their policy limits were private inputs that nothing bound
function isRetired(c: string | null | undefined): boolean {
  return !!c && isRetiredCircuit(c, availableCircuits.value)
}
function retiredHint(c: string): string {
  return `Retired: its policy limits were private inputs that nothing bound. Successor: ${circuitSuccessor(c, availableCircuits.value) ?? 'the v2.0.0 circuit'}.`
}
// the stored version reads "v2.0.0"; the template adds its own "v"
function versionLabel(v: string | null | undefined): string {
  return (v || '').replace(/^v/, '')
}
function shortCircuit(c: string | null | undefined): string {
  if (!c) return '—'
  // circuits look like "fairMarkupPolicy/v1.0.0" — show base name
  return c.split('/')[0]
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
function formatRel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.floor((then - now) / 1000)
  const past = diffSec < 0
  const abs = Math.abs(diffSec)
  if (abs < 60) return past ? `${abs}s ago` : `in ${abs}s`
  if (abs < 3600) return past ? `${Math.floor(abs / 60)}m ago` : `in ${Math.floor(abs / 60)}m`
  if (abs < 86400) return past ? `${Math.floor(abs / 3600)}h ago` : `in ${Math.floor(abs / 3600)}h`
  return past ? `${Math.floor(abs / 86400)}d ago` : `in ${Math.floor(abs / 86400)}d`
}

function isExpired(r: AttestationRow): boolean {
  if (!r.expires_at) return false
  return new Date(r.expires_at).getTime() < Date.now()
}
function rowStatusLabel(r: AttestationRow): string {
  if (r.revoked_at) return 'REVOKED'
  if (!r.verified) return 'FAILED'
  if (isExpired(r)) return 'EXPIRED'
  return 'VERIFIED'
}
function rowStatusClass(r: AttestationRow): string {
  if (r.revoked_at) return 'aa-status-pill--red'
  if (!r.verified) return 'aa-status-pill--red'
  if (isExpired(r)) return 'aa-status-pill--warn'
  return 'aa-status-pill--green'
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
.aa {
  position: relative;
  min-height: 100vh;
  padding: 0 0 32px 0;
  color: rgba(255, 255, 255, 0.9);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}

.aa-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.aa-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}
.aa-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.aa-glow-1 { width: 440px; height: 440px; background: rgba(16, 185, 129, 0.45); top: -110px; right: -90px; }
.aa-glow-2 { width: 320px; height: 320px; background: rgba(var(--cyan-rgb), 0.4); bottom: -60px; left: -100px; }

.aa-hero { position: relative; z-index: 1; padding: 36px 32px 18px; }
.aa-hero-inner { max-width: 1280px; margin: 0 auto; }
.aa-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan);
  padding: 4px 12px;
  border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 14px;
  background: rgba(var(--cyan-rgb), 0.04);
  margin-bottom: 14px;
}
.aa-chip-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }
.aa-h1 { font-size: 2.1rem; margin: 0 0 0.4rem; font-weight: 700; color: rgba(255, 255, 255, 0.95); letter-spacing: -0.01em; }
.aa-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.aa-lead { font-size: 0.85rem; color: rgba(255, 255, 255, 0.6); margin: 0 0 16px; line-height: 1.5; max-width: 60rem; }
.aa-lead code { background: rgba(var(--cyan-rgb), 0.08); color: var(--cyan); padding: 1px 5px; border-radius: 3px; font-size: 0.82em; }

.aa-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.aa-toolbar-group { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.aa-toolbar-spacer { flex: 1; }
.aa-toolbar-meta { margin-left: 0.3rem; }
.aa-toolbar-label { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(255, 255, 255, 0.48); text-transform: uppercase; }
.aa-toolbar-val { font-family: var(--mono); font-size: 0.78rem; font-weight: 700; color: var(--cyan); }

.aa-period-btn {
  font-family: var(--mono); font-size: 0.65rem; font-weight: 600; letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 4px 10px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
}
.aa-period-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9); }
.aa-period-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}

.aa-toggle { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; font-family: var(--mono); font-size: 0.65rem; color: rgba(255, 255, 255, 0.7); }
.aa-toggle input { display: none; }
.aa-toggle-track { width: 26px; height: 14px; background: rgba(255, 255, 255, 0.1); border-radius: 7px; position: relative; transition: background 0.15s; }
.aa-toggle-knob { position: absolute; top: 2px; left: 2px; width: 10px; height: 10px; background: rgba(255, 255, 255, 0.6); border-radius: 50%; transition: transform 0.15s, background 0.15s; }
.aa-toggle input:checked ~ .aa-toggle-track { background: rgba(var(--cyan-rgb), 0.3); }
.aa-toggle input:checked ~ .aa-toggle-track .aa-toggle-knob { transform: translateX(12px); background: var(--cyan); }

.aa-body { position: relative; z-index: 1; padding: 0 32px; max-width: 1280px; margin: 0 auto; display: flex; flex-direction: column; gap: 1.25rem; }
.aa-btn { display: inline-flex; align-items: center; gap: 0.35rem; font-family: var(--mono); font-size: 0.65rem; letter-spacing: 0.08em; font-weight: 600; padding: 4px 10px; border-radius: 4px; border: 1px solid transparent; cursor: pointer; transition: all 0.15s; }
.aa-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.aa-btn--ghost { background: transparent; border-color: rgba(var(--cyan-rgb), 0.25); color: rgba(var(--cyan-rgb), 0.85); }
.aa-btn--ghost:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.08); border-color: rgba(var(--cyan-rgb), 0.5); color: rgba(var(--cyan-rgb), 1); }

.aa-center { text-align: center; padding: 5rem 1rem; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(var(--cyan-rgb), 0.12); border-radius: 6px; }
.aa-spinner { width: 36px; height: 36px; border: 2.5px solid rgba(var(--cyan-rgb), 0.2); border-top-color: rgba(var(--cyan-rgb), 0.95); border-radius: 50%; animation: aa-spin 0.8s linear infinite; margin: 0 auto 0.8rem; }
@keyframes aa-spin { to { transform: rotate(360deg); } }
.aa-loading-text { font-family: var(--mono); font-size: 0.75rem; color: rgba(255, 255, 255, 0.5); letter-spacing: 0.1em; text-transform: uppercase; }
.aa-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger); }

/* Phase banner */
.aa-phase-banner {
  display: flex; align-items: center; gap: 0.8rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-family: var(--mono); font-size: 0.72rem;
}
.aa-phase-banner--ok { background: rgba(0, 255, 136, 0.05); border: 1px solid rgba(0, 255, 136, 0.25); }
.aa-phase-banner--partial { background: rgba(255, 149, 0, 0.05); border: 1px solid rgba(255, 149, 0, 0.25); }
.aa-phase-banner--idle { background: rgba(var(--cyan-rgb), 0.04); border: 1px solid rgba(var(--cyan-rgb), 0.18); }
.aa-phase-glyph { font-size: 1.1rem; font-weight: 700; }
.aa-phase-banner--ok .aa-phase-glyph { color: var(--nc-success, #00ff88); }
.aa-phase-banner--partial .aa-phase-glyph { color: var(--nc-warning, #ff9500); }
.aa-phase-banner--idle .aa-phase-glyph { color: rgba(255, 255, 255, 0.5); }
.aa-phase-text {
  flex: 1;
  color: rgba(255, 255, 255, 0.75);
  line-height: 1.45;
}
.aa-phase-text strong { color: rgba(255, 255, 255, 0.95); }
.aa-phase-text code { background: rgba(0, 0, 0, 0.4); padding: 1px 5px; border-radius: 3px; font-size: 0.85em; }
.aa-phase-pills { display: inline-flex; gap: 0.25rem; flex-wrap: wrap; }

/* Stats */
.aa-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
.aa-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.aa-stat-key { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.14em; font-weight: 700; color: var(--cyan); text-transform: uppercase; }
.aa-stat-val { font-family: var(--mono); font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.05; }
.aa-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.aa-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.aa-stat-val--violet { color: #c084fc; text-shadow: 0 0 14px rgba(168, 85, 247, 0.35); }
.aa-stat-val--warn { color: var(--nc-warning, #ff9500); text-shadow: 0 0 14px rgba(255, 149, 0, 0.4); }
.aa-stat-val--muted { color: rgba(255, 255, 255, 0.48); }
.aa-stat-sub { font-family: var(--mono); font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; }
.aa-stat-sub-grid { display: flex; gap: 0.3rem; flex-wrap: wrap; }

.aa-pill { display: inline-block; font-family: var(--mono); font-size: 0.55rem; font-weight: 700; letter-spacing: 0.06em; padding: 1px 6px; border-radius: 3px; border: 1px solid transparent; }
.aa-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.aa-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.aa-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.aa-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.aa-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.aa-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

/* Section */
.aa-section { background: rgba(10, 13, 22, 0.7); border: 1px solid rgba(var(--cyan-rgb), 0.15); border-radius: 8px; padding: 1rem 1.1rem; display: flex; flex-direction: column; gap: 0.7rem; }
.aa-section-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.aa-section-title { font-family: var(--mono); font-size: 0.65rem; letter-spacing: 0.14em; font-weight: 700; color: var(--cyan); text-transform: uppercase; }
.aa-section-sub { font-family: var(--mono); font-size: 0.6rem; color: rgba(255, 255, 255, 0.48); }

/* Sparkline */
.aa-spark-wrap { position: relative; width: 100%; height: 110px; }
.aa-spark { width: 100%; height: 100%; display: block; }
.aa-spark-grid line { stroke: rgba(var(--cyan-rgb), 0.06); stroke-width: 1; stroke-dasharray: 3 5; }
.aa-spark-bar { fill: rgba(var(--cyan-rgb), 0.7); }
.aa-spark-empty { display: flex; align-items: center; justify-content: center; height: 100%; font-family: var(--mono); font-size: 0.7rem; color: rgba(255, 255, 255, 0.4); letter-spacing: 0.12em; text-transform: uppercase; }

/* Twocol */
.aa-twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem; }

.aa-list { display: flex; flex-direction: column; gap: 0.4rem; }

.aa-circuit-row {
  display: grid;
  grid-template-columns: minmax(0, 220px) 1fr auto auto;
  align-items: center; gap: 0.6rem;
  font-family: var(--mono); font-size: 0.7rem;
}
.aa-circuit-id { display: flex; flex-direction: column; gap: 0.2rem; min-width: 0; }
.aa-circuit-id code { color: rgba(255, 255, 255, 0.85); font-size: 0.65rem; background: transparent; padding: 0; }
.aa-circuit-version { font-size: 0.55rem; color: #aa5af7; letter-spacing: 0.05em; }
.aa-bar { position: relative; height: 6px; background: rgba(var(--cyan-rgb), 0.1); border-radius: 3px; overflow: hidden; }
.aa-bar-fill { position: absolute; inset: 0; background: linear-gradient(90deg, rgba(var(--cyan-rgb), 0.5), var(--cyan)); border-radius: 3px; transition: width 0.3s; }
.aa-bar-val { color: var(--cyan); font-weight: 600; font-size: 0.7rem; min-width: 2.5rem; text-align: right; }
.aa-bar-pct { font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); min-width: 3rem; text-align: right; }

.aa-agent-row {
  display: grid;
  grid-template-columns: 30px 1fr auto auto;
  align-items: center; gap: 0.5rem;
  padding: 4px 7px;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 4px;
  font-family: var(--mono); font-size: 0.7rem;
}
.aa-agent-rank { color: var(--cyan); font-weight: 700; font-size: 0.65rem; }
.aa-agent-did {
  background: transparent;
  color: rgba(255, 255, 255, 0.85);
  font-size: 0.65rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.aa-agent-count { color: var(--cyan); font-weight: 600; font-size: 0.7rem; text-align: right; }
.aa-agent-count-unit { font-size: 0.55rem; color: rgba(255, 255, 255, 0.48); font-weight: 600; }  /* §FESUITE: 4.94:1 (0.45 was 4.49:1); the circuit labels' purple opaque, 5.1:1 (was 3.8:1) */

.aa-empty-mini {
  text-align: center;
  font-family: var(--mono); font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.55);
  padding: 1rem;
  letter-spacing: 0.04em;
  display: flex; flex-direction: column; gap: 0.5rem; align-items: stretch;
}
.aa-empty-sub { color: rgba(255, 255, 255, 0.4); font-size: 0.62rem; }
.aa-circuit-listing {
  list-style: none;
  margin: 0; padding: 0;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.aa-circuit-listing li {
  display: flex; gap: 0.6rem;
  background: rgba(var(--cyan-rgb), 0.04);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 4px;
  padding: 5px 9px;
  text-align: left;
}
.aa-circuit-listing code { font-size: 0.62rem; color: rgba(255, 255, 255, 0.85); background: transparent; padding: 0; }
.aa-circuit-name { font-size: 0.6rem; color: #aa5af7; overflow-wrap: anywhere; }

/* Feed */
.aa-feed-list { display: flex; flex-direction: column; gap: 0.35rem; }
.aa-feed-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.aa-feed-row:hover { background: rgba(var(--cyan-rgb), 0.04); border-color: rgba(var(--cyan-rgb), 0.25); }
.aa-feed-row--expanded { background: rgba(var(--cyan-rgb), 0.06); border-color: rgba(var(--cyan-rgb), 0.4); }

.aa-feed-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.45rem 0.75rem;
  flex-wrap: wrap;
  font-family: var(--mono);
}
.aa-feed-time { font-size: 0.7rem; font-weight: 600; color: rgba(255, 255, 255, 0.85); }
.aa-feed-date { font-size: 0.6rem; color: rgba(255, 255, 255, 0.5); }
.aa-feed-did {
  font-size: 0.6rem;
  color: rgba(255, 255, 255, 0.65);
  background: rgba(var(--cyan-rgb), 0.04);
  padding: 1px 5px; border-radius: 3px;
}
.aa-feed-meta { font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); }
.aa-feed-meta strong { color: rgba(255, 255, 255, 0.85); font-weight: 600; }
.aa-feed-spacer { flex: 1; }
.aa-feed-caret { font-size: 0.7rem; color: rgba(var(--cyan-rgb), 0.6); }

.aa-status-pill { font-family: var(--mono); font-size: 0.55rem; font-weight: 700; letter-spacing: 0.06em; padding: 1px 6px; border-radius: 3px; border: 1px solid transparent; }
.aa-status-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.aa-status-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.aa-status-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.aa-status-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

.aa-feed-detail {
  padding: 0.7rem 0.85rem 0.85rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex; flex-direction: column; gap: 0.6rem;
  cursor: default;
}
.aa-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.4rem 0.85rem; }
.aa-detail-pair { display: flex; flex-direction: column; gap: 0.15rem; }
.aa-detail-key { font-family: var(--mono); font-size: 0.55rem; letter-spacing: 0.12em; color: rgba(255, 255, 255, 0.4); text-transform: uppercase; font-weight: 600; }
.aa-detail-val { font-family: var(--mono); font-size: 0.7rem; color: rgba(255, 255, 255, 0.85); display: flex; align-items: center; gap: 0.35rem; }
.aa-detail-val--ok { color: var(--nc-success, #00ff88); }
.aa-detail-val--warn { color: var(--nc-warning, #ff9500); }
.aa-detail-val--err { color: var(--nc-danger, #ff3366); }
.aa-detail-val code { background: rgba(var(--cyan-rgb), 0.06); padding: 1px 5px; border-radius: 3px; word-break: break-all; font-size: 0.65rem; }
.aa-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace; font-size: 0.7rem;
  padding: 0 5px; cursor: pointer;
  transition: all 0.12s;
}
.aa-icon-btn:hover { background: rgba(var(--cyan-rgb), 0.1); color: rgba(var(--cyan-rgb), 1); border-color: rgba(var(--cyan-rgb), 0.5); }
.aa-detail-section { margin-top: 0.2rem; }
.aa-detail-pre {
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--cyan-rgb), 0.15);
  border-radius: 4px;
  padding: 6px 9px;
  font-family: var(--mono); font-size: 0.62rem;
  color: rgba(255, 255, 255, 0.75);
  white-space: pre-wrap; word-break: break-all;
  max-height: 14rem; overflow-y: auto;
}
.aa-detail-pre--err { background: rgba(255, 51, 102, 0.06); border-color: rgba(255, 51, 102, 0.3); color: rgba(255, 200, 200, 0.85); }

.aa-footer { font-family: var(--mono); font-size: 0.65rem; color: rgba(255, 255, 255, 0.5); padding-top: 0.5rem; border-top: 1px solid rgba(var(--cyan-rgb), 0.08); }
.aa-footer code { background: rgba(var(--cyan-rgb), 0.08); color: var(--cyan); padding: 1px 5px; border-radius: 3px; }

@media (max-width: 1100px) {
  .aa-stats { grid-template-columns: 1fr 1fr; }
  /* minmax(0, 1fr): a 1fr column grew to a panel's widest line and both panels ran ~44 px past a phone's edge (the
     camera, 2026-10-13) */
  .aa-twocol { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 768px) {
  .aa-hero { padding: 24px 16px 12px; }
  .aa-h1 { font-size: 1.5rem; }
  .aa-body { padding: 0 16px; }
  .aa-stats { grid-template-columns: 1fr; }
}
</style>
