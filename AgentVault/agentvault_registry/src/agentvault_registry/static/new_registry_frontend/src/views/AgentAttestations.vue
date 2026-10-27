<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useAttestationsStore } from '@/stores/attestations'
import { useAgentStore } from '@/stores/agents'
import { useAuthStore } from '@/stores/auth'
import { useLogger } from '@/composables/useLogger'
import { useI18n } from '@/composables/useI18n'
import { attestationsApi } from '@/services'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { isRetiredCircuit, circuitSuccessor } from '@/services/api/attestations'

const { t } = useI18n()
const log = useLogger('AgentAttestations')
import type {
  AttestationRecord,
  AttestationBundle,
  CircuitInfo,
} from '@/services/api/attestations'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const store = useAttestationsStore()
const auth = useAuthStore()
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const agents = useAgentStore() as unknown as Record<string, any>

// ── State ────────────────────────────────────────────────────────────
const selectedDid = ref<string>('')
const filterStatus = ref<'all' | 'verified' | 'expired' | 'revoked'>('all')
const filterCircuit = ref<string>('')
const circuits = ref<CircuitInfo[]>([])
const initialLoad = ref(true)
const lastRefreshAt = ref<string>('')

// ── Derived ──────────────────────────────────────────────────────────
const myAgentList = computed(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const list = (agents as any).agents?.value ?? (agents as any).agents ?? []
  if (Array.isArray(list) && list.length) return list
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cur = (agents as any).currentAgent?.value ?? (agents as any).currentAgent
  return cur ? [cur] : []
})

const filteredAttestations = computed(() => {
  return store.myAttestations.filter((a) => {
    if (filterCircuit.value && a.circuit_id !== filterCircuit.value) return false
    if (filterStatus.value === 'all') return true
    return store.statusFor(a) === filterStatus.value
  })
})

const stats = computed(() => {
  const r = { total: 0, verified: 0, expired: 0, revoked: 0 }
  for (const a of store.myAttestations) {
    r.total += 1
    const s = store.statusFor(a)
    if (s === 'verified') r.verified += 1
    else if (s === 'expired') r.expired += 1
    else if (s === 'revoked') r.revoked += 1
  }
  return r
})

// v1.0.0 circuits are retired: still listed (old attestations name them), never offered for a new schedule
const isRetired = (circuitId: string): boolean => isRetiredCircuit(circuitId, circuits.value)
const activeCircuits = computed(() => circuits.value.filter((c) => !isRetired(c.circuit_id)))
const retiredHint = (circuitId: string): string =>
  t('agentAttestationsView.attestations.retiredHint', { successor: circuitSuccessor(circuitId, circuits.value) ?? '' })

const agentName = (a: { name?: string; did: string }): string =>
  a?.name || (a?.did ? a.did.slice(0, 16) + '…' : 'unknown')

const truncDid = (did: string): string =>
  did?.length > 28 ? did.slice(0, 14) + '…' + did.slice(-10) : did

// ── Bundle modal ─────────────────────────────────────────────────────
const bundleModalOpen = ref(false)
const bundleLoading = ref(false)
const bundleData = ref<AttestationBundle | null>(null)
const bundleError = ref<string | null>(null)

async function viewBundle(a: AttestationRecord): Promise<void> {
  bundleModalOpen.value = true
  bundleLoading.value = true
  bundleError.value = null
  bundleData.value = null
  try {
    bundleData.value = await store.loadBundle(a.id)
    if (!bundleData.value) bundleError.value = store.lastError ?? 'Bundle load failed'
  } finally {
    bundleLoading.value = false
  }
}

function downloadBundle(a: AttestationRecord): void {
  attestationsApi.getBundle(a.id).then((bundle) => {
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `attestation-bundle-${a.id.slice(0, 8)}.json`
    link.click()
    URL.revokeObjectURL(url)
  }).catch((err) => console.error('Bundle download failed:', err))
}

// ── Revoke modal ─────────────────────────────────────────────────────
const revokeModalOpen = ref(false)
const revokeTarget = ref<AttestationRecord | null>(null)
const revokeReason = ref('')
const revokeBusy = ref(false)

function openRevoke(a: AttestationRecord): void {
  revokeTarget.value = a
  revokeReason.value = ''
  revokeModalOpen.value = true
}

async function confirmRevoke(): Promise<void> {
  if (!revokeTarget.value) return
  revokeBusy.value = true
  const ok = await store.revoke(revokeTarget.value.id, revokeReason.value || null)
  revokeBusy.value = false
  if (ok) {
    revokeModalOpen.value = false
    revokeTarget.value = null
  }
}

// ── Schedule create form ─────────────────────────────────────────────
const scheduleCircuit = ref('')
const scheduleInterval = ref<number>(24)
const scheduleBusy = ref(false)
const scheduleErr = ref<string | null>(null)
// §FESUITE (the failing-reads census, 2026-10-04): with the schedules' read failed the page said "No active schedules."
const schedulesFailed = ref(false)
// and they answered at least once: only then may the page say "No active schedules." (with no agent it never asks)
const schedulesRead = ref(false)
async function readSchedules() {
  try { await store.loadMySchedules(); schedulesFailed.value = false; schedulesRead.value = true }
  catch (e) { schedulesFailed.value = true; log.warn('loadMySchedules:', e) }
}

async function submitSchedule(): Promise<void> {
  if (!scheduleCircuit.value) {
    scheduleErr.value = 'Pick a circuit first.'
    return
  }
  scheduleBusy.value = true
  scheduleErr.value = null
  const created = await store.createSchedule(scheduleCircuit.value, scheduleInterval.value)
  scheduleBusy.value = false
  if (!created) scheduleErr.value = store.lastError
}

async function disable(scheduleId: string): Promise<void> {
  await store.disableSchedule(scheduleId)
}

// ── Lifecycle ────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    // Pull the user's agent list if not already loaded.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const fetchAgents = (agents as any).fetchMyAgents ?? (agents as any).loadAgents ?? null
    if (typeof fetchAgents === 'function') {
      try { await fetchAgents.call(agents) } catch { /* best-effort */ }
    }
    if (!selectedDid.value && myAgentList.value.length > 0) {
      selectedDid.value = myAgentList.value[0].did
    }
    // Load circuits for the dropdowns. Public endpoint, no auth required.
    try {
      circuits.value = await attestationsApi.listCircuits()
      if (activeCircuits.value.length > 0 && !scheduleCircuit.value) {
        scheduleCircuit.value = activeCircuits.value[0].circuit_id
      }
    } catch (e) { log.warn('listCircuits:', e) }
    if (selectedDid.value) {
      try { await store.loadMyAttestations(selectedDid.value) }
      catch (e) { log.warn('loadMyAttestations:', e) }
    }
    // 2026-05-07: schedules endpoint requires agent JWT. Skipping when there's
    // no active agent prevents the 401 → apiClient logout → CrowdSec ban
    // cascade. Route guard already redirects developers without an active
    // agent to the picker, but this is defense-in-depth for direct URL hits.
    if (auth.activeAgent && auth.agentToken) await readSchedules()
  } catch (e) {
    log.warn('AgentAttestations onMounted:', e)
  } finally {
    // Always flip the spinner off — the dashboard renders even on partial
    // load failure (empty state messages take over for missing data).
    initialLoad.value = false
    lastRefreshAt.value = dayjs().format('HH:mm:ss')
  }
})

async function reload(): Promise<void> {
  if (selectedDid.value) {
    await store.loadMyAttestations(selectedDid.value)
  }
  if (auth.activeAgent && auth.agentToken) {
    await store.loadMySchedules()
  }
  lastRefreshAt.value = dayjs().format('HH:mm:ss')
}

function statusOf(a: AttestationRecord): 'verified' | 'expired' | 'revoked' | 'failed' {
  return store.statusFor(a) as 'verified' | 'expired' | 'revoked' | 'failed'
}
</script>

<template>
<div class="aa">
  <!-- Ambient -->
  <div class="aa-ambient">
    <div class="aa-grid"></div>
    <div class="aa-scan"></div>
    <div class="aa-glow aa-glow-1"></div>
    <div class="aa-glow aa-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="aa-hero">
    <div class="aa-hero-inner">
      <div class="aa-chip"><span class="aa-chip-dot"></span>{{ t('agentAttestationsView.hero.chip') }}</div>
      <h1 class="aa-h1" data-tour="att-hero">{{ t('agentAttestationsView.hero.h1a') }}<span class="aa-accent">{{ t('agentAttestationsView.hero.h1Accent') }}</span>{{ t('agentAttestationsView.hero.h1b') }}</h1>
      <p class="aa-lead">{{ t('agentAttestationsView.lead') }}</p>
    </div>
  </section>

  <!-- Dashboard (always renders; per-section loading state) -->
  <div class="aa-section">

    <!-- Summary stats -->
    <div class="aa-stats-row">
      <div class="aa-stat aa-stat-cyan">
        <span class="aa-stat-label">{{ t('agentAttestationsView.stats.total') }}</span>
        <span class="aa-stat-value">{{ stats.total }}</span>
      </div>
      <div class="aa-stat" :class="stats.verified > 0 ? 'aa-stat-ok' : 'aa-stat-muted'">
        <span class="aa-stat-label">{{ t('agentAttestationsView.stats.verified') }}</span>
        <span class="aa-stat-value">{{ stats.verified }}</span>
      </div>
      <div class="aa-stat" :class="stats.expired > 0 ? 'aa-stat-warn' : 'aa-stat-muted'">
        <span class="aa-stat-label">{{ t('agentAttestationsView.stats.expired') }}</span>
        <span class="aa-stat-value">{{ stats.expired }}</span>
      </div>
      <div class="aa-stat" :class="stats.revoked > 0 ? 'aa-stat-bad' : 'aa-stat-muted'">
        <span class="aa-stat-label">{{ t('agentAttestationsView.stats.revoked') }}</span>
        <span class="aa-stat-value">{{ stats.revoked }}</span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="aa-toolbar">
      <label class="aa-field">
        <span class="aa-fl">{{ t('agentAttestationsView.toolbar.agentLabel') }}</span>
        <select v-model="selectedDid" @change="reload" class="aa-input">
          <option value="" disabled>{{ t('agentAttestationsView.toolbar.selectAgent') }}</option>
          <option v-for="a in myAgentList" :key="a.did" :value="a.did">
            {{ agentName(a) }} — {{ truncDid(a.did) }}
          </option>
        </select>
      </label>
      <label class="aa-field">
        <span class="aa-fl">{{ t('agentAttestationsView.toolbar.statusLabel') }}</span>
        <select v-model="filterStatus" class="aa-input">
          <option value="all">{{ t('agentAttestationsView.toolbar.statusAll') }}</option>
          <option value="verified">{{ t('agentAttestationsView.toolbar.statusVerified') }}</option>
          <option value="expired">{{ t('agentAttestationsView.toolbar.statusExpired') }}</option>
          <option value="revoked">{{ t('agentAttestationsView.toolbar.statusRevoked') }}</option>
        </select>
      </label>
      <label class="aa-field">
        <span class="aa-fl">{{ t('agentAttestationsView.toolbar.circuitLabel') }}</span>
        <select v-model="filterCircuit" class="aa-input" data-test="circuit-filter">
          <option value="">{{ t('agentAttestationsView.toolbar.allCircuits') }}</option>
          <option v-for="c in circuits" :key="c.circuit_id" :value="c.circuit_id">
            {{ isRetired(c.circuit_id) ? t('agentAttestationsView.toolbar.retiredOption', { id: c.circuit_id }) : c.circuit_id }}
          </option>
        </select>
      </label>
      <button class="aa-btn aa-btn-ghost" @click="reload">{{ t('agentAttestationsView.toolbar.reload') }}</button>
    </div>

    <!-- Attestations table -->
    <div class="aa-card" data-tour="att-list">
      <div class="aa-card-header">
        <h3 class="aa-card-title">{{ t('agentAttestationsView.attestations.title') }}</h3>
        <span class="aa-badge aa-badge-cyan">{{ t('agentAttestationsView.attestations.shown', { count: filteredAttestations.length }) }}</span>
      </div>

      <div v-if="initialLoad" class="aa-empty">
        <span class="aa-spinner aa-spinner-inline"></span>
        <code>{{ t('agentAttestationsView.attestations.loadingInitial') }}</code>
      </div>
      <div v-else-if="!selectedDid" class="aa-empty">
        <code>{{ t('agentAttestationsView.attestations.selectAgent') }}</code>
      </div>
      <div v-else-if="store.loading" class="aa-empty">
        <code>{{ t('agentAttestationsView.attestations.loading') }}</code>
      </div>
      <ReadFailedNotice v-else-if="store.myAttestationsFailed" :retry="reload" />
      <div v-else-if="filteredAttestations.length === 0" class="aa-empty">
        <code>{{ t('agentAttestationsView.attestations.noMatch') }}</code>
      </div>
      <div v-else class="aa-table-wrap">
        <table class="aa-table" aria-label="ZKP attestations">
          <caption class="sr-only">ZKP attestations submitted by this agent, with verification status.</caption>
          <thead>
            <tr>
              <th>{{ t('agentAttestationsView.attestations.thStatus') }}</th>
              <th>{{ t('agentAttestationsView.attestations.thCircuit') }}</th>
              <th>{{ t('agentAttestationsView.attestations.thSubmitted') }}</th>
              <th>{{ t('agentAttestationsView.attestations.thExpires') }}</th>
              <th style="text-align: right;">{{ t('agentAttestationsView.attestations.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filteredAttestations" :key="a.id">
              <td>
                <span class="aa-status-badge" :class="`aa-sb-${statusOf(a)}`">
                  {{ statusOf(a) }}
                </span>
                <div v-if="!a.verified && a.failure_reason" class="aa-why" data-test="failure-reason">
                  {{ t('agentAttestationsView.attestations.failedReason', { reason: a.failure_reason }) }}
                </div>
              </td>
              <td>
                <code class="aa-mono">{{ a.circuit_id }}</code>
                <span v-if="isRetired(a.circuit_id)" class="aa-status-badge aa-sb-muted aa-retired"
                  data-test="circuit-retired" :title="retiredHint(a.circuit_id)">{{ t('agentAttestationsView.attestations.retired') }}</span>
              </td>
              <td class="aa-mono aa-dim">{{ dayjs(a.submitted_at).fromNow() }}</td>
              <td class="aa-mono aa-dim">
                {{ a.expires_at ? dayjs(a.expires_at).fromNow() : '—' }}
              </td>
              <td style="text-align: right;">
                <button class="aa-btn aa-btn-ghost aa-btn-sm" data-tour="att-bundle" @click="viewBundle(a)">{{ t('agentAttestationsView.attestations.bundleBtn') }}</button>
                <button class="aa-btn aa-btn-ghost aa-btn-sm" @click="downloadBundle(a)">{{ t('agentAttestationsView.attestations.downloadBtn') }}</button>
                <button
                  v-if="!a.revoked_at"
                  class="aa-btn aa-btn-danger aa-btn-sm"
                  data-tour="att-revoke"
                  @click="openRevoke(a)"
                >{{ t('agentAttestationsView.attestations.revokeBtn') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Schedules -->
    <div class="aa-card" data-tour="att-schedules">
      <div class="aa-card-header">
        <h3 class="aa-card-title">{{ t('agentAttestationsView.schedules.title') }}</h3>
        <span class="aa-badge aa-badge-cyan">{{ t('agentAttestationsView.schedules.entries', { count: store.mySchedules.length }) }}</span>
      </div>
      <p class="aa-section-desc">{{ t('agentAttestationsView.schedules.desc') }}</p>

      <form class="aa-form" @submit.prevent="submitSchedule">
        <label class="aa-field">
          <span class="aa-fl">{{ t('agentAttestationsView.schedules.circuitLabel') }}</span>
          <select v-model="scheduleCircuit" class="aa-input" data-test="schedule-circuit">
            <option value="" disabled>{{ t('agentAttestationsView.schedules.selectCircuit') }}</option>
            <option v-for="c in activeCircuits" :key="c.circuit_id" :value="c.circuit_id">
              {{ c.circuit_id }}
            </option>
          </select>
        </label>
        <label class="aa-field">
          <span class="aa-fl">{{ t('agentAttestationsView.schedules.intervalLabel') }}</span>
          <input
            v-model.number="scheduleInterval"
            type="number"
            min="1"
            max="720"
            class="aa-input"
          />
        </label>
        <button class="aa-btn aa-btn-primary" type="submit" data-tour="att-create" :disabled="scheduleBusy">
          {{ scheduleBusy ? t('agentAttestationsView.schedules.saving') : t('agentAttestationsView.schedules.addBtn') }}
        </button>
      </form>
      <div v-if="scheduleErr" class="aa-err">{{ scheduleErr }}</div>

      <ReadFailedNotice v-if="schedulesFailed && store.mySchedules.length === 0" dense :retry="readSchedules" />
      <div v-else-if="schedulesRead && store.mySchedules.length === 0" class="aa-empty">
        <code>{{ t('agentAttestationsView.schedules.empty') }}</code>
      </div>
      <div v-else class="aa-table-wrap">
        <table class="aa-table" aria-label="Attestation schedules">
          <caption class="sr-only">Active attestation schedules with circuit and frequency.</caption>
          <thead>
            <tr>
              <th>{{ t('agentAttestationsView.schedules.thStatus') }}</th>
              <th>{{ t('agentAttestationsView.schedules.thCircuit') }}</th>
              <th>{{ t('agentAttestationsView.schedules.thInterval') }}</th>
              <th>{{ t('agentAttestationsView.schedules.thNextDue') }}</th>
              <th>{{ t('agentAttestationsView.schedules.thLastAttested') }}</th>
              <th style="text-align: right;">{{ t('agentAttestationsView.schedules.thActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in store.mySchedules" :key="s.id">
              <td>
                <span class="aa-status-badge" :class="s.enabled ? 'aa-sb-verified' : 'aa-sb-muted'">
                  {{ s.enabled ? t('agentAttestationsView.schedules.enabled') : t('agentAttestationsView.schedules.disabled') }}
                </span>
              </td>
              <td><code class="aa-mono">{{ s.circuit_id }}</code></td>
              <td class="aa-mono">{{ s.interval_hours }}h</td>
              <td class="aa-mono aa-dim">{{ dayjs(s.next_due_at).fromNow() }}</td>
              <td class="aa-mono aa-dim">
                {{ s.last_attestation_at ? dayjs(s.last_attestation_at).fromNow() : t('agentAttestationsView.schedules.never') }}
              </td>
              <td style="text-align: right;">
                <button
                  v-if="s.enabled"
                  class="aa-btn aa-btn-danger aa-btn-sm"
                  @click="disable(s.id)"
                >{{ t('agentAttestationsView.schedules.disableBtn') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

  </div>

  <!-- Footer -->
  <div class="aa-footer">
    {{ t('agentAttestationsView.footer', { time: lastRefreshAt || '—', count: filteredAttestations.length }) }}
  </div>

  <!-- Bundle modal -->
  <div v-if="bundleModalOpen" class="aa-modal-bg" @click.self="bundleModalOpen = false">
    <div class="aa-modal">
      <div class="aa-modal-head">
        <h3 class="aa-card-title">{{ t('agentAttestationsView.bundleModal.title') }}</h3>
        <button class="aa-x" @click="bundleModalOpen = false">×</button>
      </div>
      <div v-if="bundleLoading" class="aa-empty"><code>{{ t('agentAttestationsView.bundleModal.loading') }}</code></div>
      <div v-else-if="bundleError" class="aa-err">{{ bundleError }}</div>
      <pre v-else-if="bundleData" class="aa-bundle">{{ JSON.stringify(bundleData, null, 2) }}</pre>
    </div>
  </div>

  <!-- Revoke modal -->
  <div v-if="revokeModalOpen" class="aa-modal-bg" @click.self="revokeModalOpen = false">
    <div class="aa-modal">
      <div class="aa-modal-head">
        <h3 class="aa-card-title">{{ t('agentAttestationsView.revokeModal.title') }}</h3>
        <button class="aa-x" @click="revokeModalOpen = false">×</button>
      </div>
      <p class="aa-section-desc">{{ t('agentAttestationsView.revokeModal.desc') }}</p>
      <label class="aa-field">
        <span class="aa-fl">{{ t('agentAttestationsView.revokeModal.reasonLabel') }}</span>
        <input
          v-model="revokeReason"
          class="aa-input"
          :placeholder="t('agentAttestationsView.revokeModal.reasonPlaceholder')"
        />
      </label>
      <div class="aa-modal-actions">
        <button class="aa-btn aa-btn-ghost" @click="revokeModalOpen = false">{{ t('agentAttestationsView.revokeModal.cancel') }}</button>
        <button
          class="aa-btn aa-btn-danger"
          :disabled="revokeBusy"
          @click="confirmRevoke"
        >{{ revokeBusy ? t('agentAttestationsView.revokeModal.revoking') : t('agentAttestationsView.revokeModal.confirm') }}</button>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
.aa {
  --cyan: var(--nc-primary);
  --text-bright: #e2e8f0;
  --text-secondary: #94a3b8;
  --muted: #718299;  /* §FESUITE: 4.77-4.95:1 (#64748b was 4.07:1 under the footer) */
  --border: rgba(255,255,255,0.06);
  --mono: 'IBM Plex Mono', 'JetBrains Mono', 'Fira Code', monospace;
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints. */
  color: #b0bec5;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
  z-index: 1;
}

/* ── Ambient ───────────────────────────── */
.aa-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.aa-grid {
  position: absolute; inset: 0;
  background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}
.aa-scan {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 0%, rgba(var(--nc-primary-rgb),0.01) 50%, transparent 100%);
  background-size: 100% 200%;
  animation: aaScan 10s linear infinite;
}
@keyframes aaScan { 0% { background-position: 0 -100%; } 100% { background-position: 0 100%; } }
.aa-glow { position: absolute; border-radius: 50%; filter: blur(140px); opacity: 0.08; }
.aa-glow-1 { width: 400px; height: 400px; background: var(--nc-primary); top: -80px; right: -60px; }
.aa-glow-2 { width: 300px; height: 300px; background: #10b981; bottom: 10%; left: -80px; }

/* ── Hero ──────────────────────────────── */
.aa-hero { position: relative; z-index: 1; padding: 70px 24px 24px; text-align: center; }
.aa-hero-inner { max-width: 600px; margin: 0 auto; }
.aa-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: rgba(var(--nc-primary-rgb),0.06); padding: 5px 16px; border-radius: 3px;
}
.aa-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); animation: aaPulse 2s ease-in-out infinite; }
@keyframes aaPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
.aa-h1 { font-size: clamp(24px, 4vw, 36px); font-weight: 700; color: #fff; margin: 14px 0 8px; letter-spacing: -0.02em; }
.aa-accent { color: var(--cyan); }
.aa-lead { font-size: 13px; color: var(--muted); max-width: 480px; margin: 0 auto; }

/* ── Section ───────────────────────────── */
.aa-section {
  position: relative; z-index: 1;
  max-width: 1100px; margin: 0 auto;
  padding: 0 24px 40px;
  display: flex; flex-direction: column; gap: 16px;
}
.aa-center { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; padding: 60px 24px; }

/* ── Stats Row ─────────────────────────── */
.aa-stats-row { display: flex; gap: 8px; flex-wrap: wrap; }
.aa-stat {
  flex: 1; min-width: 120px;
  background: rgba(10,14,24,0.8);
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-left: 2px solid #64748b;
  border-radius: 5px;
  padding: 10px 14px;
  display: flex; flex-direction: column; gap: 2px;
}
.aa-stat-ok { border-left-color: #00c853; }
.aa-stat-warn { border-left-color: #ffab00; }
.aa-stat-bad { border-left-color: #ff1744; }
.aa-stat-cyan { border-left-color: var(--cyan); }
.aa-stat-muted { border-left-color: #334155; }
.aa-stat-label { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.aa-stat-value { font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--text-bright); }

/* ── Toolbar ───────────────────────────── */
.aa-toolbar {
  display: flex; gap: 12px; align-items: end; flex-wrap: wrap;
  background: rgba(10,14,24,0.6); border: 1px solid var(--border);
  border-radius: 6px; padding: 12px 14px;
}
.aa-field { display: flex; flex-direction: column; gap: 4px; min-width: 200px; flex: 1; }
.aa-fl { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.aa-input {
  background: rgba(0,0,0,0.4); border: 1px solid var(--border);
  color: var(--text-bright);
  padding: 8px 10px; border-radius: 4px;
  font-family: var(--mono); font-size: 12px;
  outline: none; transition: border-color 0.15s;
}
.aa-input:focus { border-color: rgba(var(--nc-primary-rgb),0.4); }
.aa-input:disabled { opacity: 0.5; }

/* ── Cards ─────────────────────────────── */
.aa-card {
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border);
  border-radius: 8px; padding: 18px;
}
.aa-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.aa-card-title { font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--cyan); letter-spacing: 0.1em; text-transform: uppercase; margin: 0; }

/* ── Badge ─────────────────────────────── */
.aa-badge { font-family: var(--mono); font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 3px; letter-spacing: 0.06em; }
.aa-badge-cyan { color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.12); }

/* ── Table ─────────────────────────────── */
.aa-table-wrap { overflow-x: auto; }
.aa-table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 11px; }
.aa-table th {
  text-align: left; padding: 6px 10px;
  font-size: 9px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border);
}
.aa-table td {
  padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,0.03);
  color: var(--text-secondary); vertical-align: middle;
}
.aa-table tbody tr:hover { background: rgba(var(--nc-primary-rgb),0.03); }

.aa-mono { font-family: var(--mono); color: var(--text-bright); }
.aa-dim { color: var(--muted); }
.aa-why { margin-top: 4px; max-width: 280px; font-size: 10px; line-height: 1.4; color: var(--muted); white-space: normal; }
.aa-retired { margin-left: 6px; }

/* ── Status badges ─────────────────────── */
.aa-status-badge {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  padding: 2px 7px; border-radius: 3px; letter-spacing: 0.08em; text-transform: uppercase;
}
.aa-sb-verified { color: #00c853; background: rgba(0,200,83,0.12); }
.aa-sb-expired  { color: #ffab00; background: rgba(255,171,0,0.12); }
.aa-sb-revoked  { color: #ff1744; background: rgba(255,23,68,0.12); }
.aa-sb-failed   { color: #7b8aa0; background: rgba(100,116,139,0.12); }  /* 4.75:1 on its own tint (was 3.5:1) */
.aa-sb-muted    { color: #7b8aa0; background: rgba(100,116,139,0.12); }

/* ── Empty / err / form ────────────────── */
.aa-empty { font-size: 12px; color: var(--muted); padding: 20px 0; text-align: center; }
.aa-empty code { color: var(--cyan); font-size: 11px; background: rgba(var(--nc-primary-rgb),0.08); padding: 2px 8px; border-radius: 3px; }
.aa-section-desc { font-size: 11px; color: var(--muted); margin: 0 0 12px; line-height: 1.5; }
.aa-form { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin-bottom: 12px; }
.aa-err { color: #f87171; font-size: 11px; padding: 6px 0; font-family: var(--mono); }

/* ── Buttons ───────────────────────────── */
.aa-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 7px 14px; border-radius: 4px; border: none; cursor: pointer;
  transition: all 0.15s;
}
.aa-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.aa-btn-ghost {
  background: transparent; color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
}
.aa-btn-ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb),0.08);
  border-color: rgba(var(--nc-primary-rgb),0.4);
}
.aa-btn-primary {
  background: rgba(var(--nc-primary-rgb),0.15); color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.3);
}
.aa-btn-primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.25); }
.aa-btn-danger {
  background: rgba(239,68,68,0.12); color: #f87171;
  border: 1px solid rgba(239,68,68,0.25);
}
.aa-btn-danger:hover:not(:disabled) { background: rgba(239,68,68,0.2); }
.aa-btn-sm { padding: 4px 10px; font-size: 9px; margin-left: 4px; }

/* ── Modal ─────────────────────────────── */
.aa-modal-bg {
  position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.aa-modal {
  width: 90%; max-width: 720px; max-height: 80vh; overflow: auto;
  background: #0c1117; border: 1px solid var(--border); border-radius: 8px;
  padding: 18px; color: var(--text-bright);
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.aa-modal-head {
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 12px;
}
.aa-x {
  background: transparent; border: none; color: var(--muted);
  font-size: 1.4rem; cursor: pointer; padding: 0 4px;
  transition: color 0.15s;
}
.aa-x:hover { color: #f87171; }
.aa-modal-actions { display: flex; gap: 12px; justify-content: end; margin-top: 16px; }
.aa-bundle {
  background: #050810; padding: 12px; border-radius: 4px;
  font-family: var(--mono); font-size: 11px; color: #cbd5e1;
  overflow: auto; max-height: 60vh;
  border: 1px solid var(--border);
}

/* ── Footer ────────────────────────────── */
.aa-footer {
  position: relative; z-index: 1; text-align: center; padding: 24px;
  font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.08em;
}

/* ── Spinner ───────────────────────────── */
.aa-spinner {
  width: 28px; height: 28px;
  border: 2px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: var(--cyan); border-radius: 50%;
  animation: aaSpin 0.8s linear infinite;
}
.aa-spinner-inline {
  display: inline-block; width: 12px; height: 12px;
  border-width: 1.5px; vertical-align: middle; margin-right: 8px;
}
@keyframes aaSpin { to { transform: rotate(360deg); } }
.aa-loading-text { color: var(--muted); margin-top: 12px; font-size: 12px; font-family: var(--mono); }

/* ── Responsive ────────────────────────── */
@media (max-width: 640px) {
  .aa-stats-row { flex-direction: column; }
  .aa-toolbar { flex-direction: column; align-items: stretch; }
  .aa-form { flex-direction: column; align-items: stretch; }
  /* a select is as wide as its longest option (an agent's name and its whole DID): it takes the column's width instead of
     running past the screen (the camera, 2026-10-13, Pixel 7) */
  .aa-field { min-width: 0; }
  .aa-input { width: 100%; max-width: 100%; min-width: 0; }
}
</style>
