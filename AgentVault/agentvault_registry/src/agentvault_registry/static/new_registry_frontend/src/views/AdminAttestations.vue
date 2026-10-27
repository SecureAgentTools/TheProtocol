<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { attestationsApi } from '@/services'
import { useLogger } from '@/composables/useLogger'
import { useI18n } from '@/composables/useI18n'
import type {
  AttestationRecord,
  CircuitInfo,
} from '@/services/api/attestations'
import { isRetiredCircuit, circuitSuccessor } from '@/services/api/attestations'

const { t } = useI18n()
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const log = useLogger('AdminAttestations')

const items = ref<AttestationRecord[]>([])
const totalCount = ref(0)
/** §FESUITE V0577: the counts said Loaded 0 of 0, Verified 0, Expired 0, Revoked 0, Failed 0 beside "Failed to load" */
const itemsRead = ref(false)
const loading = ref(true)
const errorMsg = ref<string | null>(null)
const circuits = ref<CircuitInfo[]>([])
const lastRefreshAt = ref<string>('')

// Filters
const filterAgent = ref('')
const filterCircuit = ref('')
const filterStatus = ref<'all' | 'verified' | 'expired' | 'revoked'>('all')
const limit = ref(100)
const offset = ref(0)

// Force-revoke modal
const revokeModalOpen = ref(false)
const revokeTarget = ref<AttestationRecord | null>(null)
const revokeReason = ref('')
const revokeBusy = ref(false)

function isExpired(a: AttestationRecord): boolean {
  if (!a.expires_at) return false
  return new Date(a.expires_at).getTime() < Date.now()
}

// v1.0.0 circuits are retired (their policy limits were private inputs nothing bound): still shown, marked as such
const isRetired = (circuitId: string): boolean => isRetiredCircuit(circuitId, circuits.value)
const retiredHint = (circuitId: string): string =>
  `Retired circuit: its policy limits were private inputs that nothing bound. Its successor is ${circuitSuccessor(circuitId, circuits.value) ?? 'the v2.0.0 circuit'}.`

function statusOf(a: AttestationRecord): 'verified' | 'expired' | 'revoked' | 'failed' {
  if (a.revoked_at) return 'revoked'
  if (isExpired(a)) return 'expired'
  if (a.verified) return 'verified'
  return 'failed'
}

const filteredItems = computed(() => {
  return items.value.filter((a) => {
    if (filterAgent.value && !a.agent_did.includes(filterAgent.value)) return false
    if (filterCircuit.value && a.circuit_id !== filterCircuit.value) return false
    if (filterStatus.value === 'all') return true
    return statusOf(a) === filterStatus.value
  })
})

const stats = computed(() => {
  const r = { total: items.value.length, verified: 0, expired: 0, revoked: 0, failed: 0 }
  for (const a of items.value) {
    const s = statusOf(a)
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(r as any)[s] = ((r as any)[s] ?? 0) + 1
  }
  return r
})

const dailySeries = computed(() => {
  const buckets = new Map<string, Map<string, number>>()
  const now = Date.now()
  const cutoff = now - 30 * 24 * 60 * 60 * 1000
  for (const a of items.value) {
    const t = new Date(a.submitted_at).getTime()
    if (t < cutoff) continue
    const day = dayjs(a.submitted_at).format('YYYY-MM-DD')
    if (!buckets.has(day)) buckets.set(day, new Map())
    const m = buckets.get(day)!
    m.set(a.circuit_id, (m.get(a.circuit_id) || 0) + 1)
  }
  const rows: { date: string; total: number; circuits: { circuit_id: string; count: number }[] }[] = []
  for (const [date, m] of buckets) {
    const circuitsList = Array.from(m.entries()).map(([cid, n]) => ({ circuit_id: cid, count: n }))
    const total = circuitsList.reduce((s, c) => s + c.count, 0)
    rows.push({ date, total, circuits: circuitsList })
  }
  rows.sort((a, b) => a.date.localeCompare(b.date))
  return rows
})

const seriesMax = computed(() => {
  return Math.max(1, ...dailySeries.value.map((r) => r.total))
})

async function load(): Promise<void> {
  loading.value = true
  errorMsg.value = null
  try {
    const resp = await attestationsApi.listAttestations({
      limit: limit.value,
      offset: offset.value,
    })
    items.value = resp.items
    totalCount.value = resp.count
    itemsRead.value = true
    lastRefreshAt.value = dayjs().format('HH:mm:ss')
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    errorMsg.value = `Failed to load: ${msg}`
    // a failed refresh keeps what was read and counted; only a list never read is cleared (it is empty anyway)
    if (!itemsRead.value) items.value = []
  } finally {
    loading.value = false
  }
}

function openRevoke(a: AttestationRecord): void {
  revokeTarget.value = a
  revokeReason.value = ''
  revokeModalOpen.value = true
}

async function confirmRevoke(): Promise<void> {
  if (!revokeTarget.value) return
  revokeBusy.value = true
  errorMsg.value = null
  try {
    await attestationsApi.adminRevokeAttestation(
      revokeTarget.value.id,
      revokeReason.value || undefined,
    )
    revokeModalOpen.value = false
    // AAT5 (audit 2026-05-07): refresh from backend so revoked_by reflects
    // the actual admin email rather than the placeholder 'admin:current'.
    // Was: optimistic local update with hardcoded label.
    await load()
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    errorMsg.value = `Revoke failed: ${msg}`
  } finally {
    revokeBusy.value = false
  }
}

function downloadCsv(): void {
  const lines: string[] = ['date,circuit_id,count']
  for (const row of dailySeries.value) {
    for (const c of row.circuits) {
      lines.push(`${row.date},${c.circuit_id},${c.count}`)
    }
  }
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `attestations-daily-series-${dayjs().format('YYYY-MM-DD')}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function truncDid(did: string): string {
  return did.length > 28 ? did.slice(0, 14) + '…' + did.slice(-10) : did
}

onMounted(async () => {
  try {
    circuits.value = await attestationsApi.listCircuits()
  } catch (e) {
    log.warn('Failed to load circuits:', e)
  }
  await load()
})
</script>

<template>
<div class="adm-att">
  <!-- Ambient -->
  <div class="adm-att-ambient">
    <div class="adm-att-grid"></div>
    <div class="adm-att-scan"></div>
    <div class="adm-att-glow adm-att-glow-1"></div>
    <div class="adm-att-glow adm-att-glow-2"></div>
  </div>

  <!-- Hero -->
  <section class="adm-att-hero">
    <div class="adm-att-hero-inner">
      <div class="adm-att-chip"><span class="adm-att-chip-dot"></span>ZKP AUDIT</div>
      <h1 class="adm-att-h1">{{ t('adminAttestationsAdminView.hero.h1a') }}<span class="adm-att-accent">{{ t('adminAttestationsAdminView.hero.h1Accent') }}</span>{{ t('adminAttestationsAdminView.hero.h1b') }}</h1>
      <p class="adm-att-lead">Cryptographic proof inventory across every agent on the network. Force-revoke is admin_enforcement-gated and audit-trailed.</p>
    </div>
  </section>

  <!-- Loading -->
  <div v-if="loading" class="adm-att-center">
    <div class="adm-att-spinner"></div>
    <p class="adm-att-loading-text">Loading attestations…</p>
  </div>

  <!-- Dashboard -->
  <div v-else class="adm-att-section">

    <!-- Stats -->
    <div class="adm-att-stats-row">
      <div class="adm-att-stat adm-att-stat-cyan">
        <span class="adm-att-stat-label">Loaded</span>
        <span class="adm-att-stat-value">{{ itemsRead ? stats.total : '—' }}</span>
        <span class="adm-att-stat-sub">of {{ itemsRead ? totalCount : '—' }} total</span>
      </div>
      <div class="adm-att-stat" :class="stats.verified > 0 ? 'adm-att-stat-ok' : 'adm-att-stat-muted'">
        <span class="adm-att-stat-label">Verified</span>
        <span class="adm-att-stat-value">{{ itemsRead ? stats.verified : '—' }}</span>
      </div>
      <div class="adm-att-stat" :class="stats.expired > 0 ? 'adm-att-stat-warn' : 'adm-att-stat-muted'">
        <span class="adm-att-stat-label">Expired</span>
        <span class="adm-att-stat-value">{{ itemsRead ? stats.expired : '—' }}</span>
      </div>
      <div class="adm-att-stat" :class="stats.revoked > 0 ? 'adm-att-stat-bad' : 'adm-att-stat-muted'">
        <span class="adm-att-stat-label">Revoked</span>
        <span class="adm-att-stat-value">{{ itemsRead ? stats.revoked : '—' }}</span>
      </div>
      <div class="adm-att-stat adm-att-stat-muted">
        <span class="adm-att-stat-label">Failed</span>
        <span class="adm-att-stat-value">{{ itemsRead ? stats.failed : '—' }}</span>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="adm-att-toolbar">
      <label class="adm-att-field">
        <span class="adm-att-fl">AGENT DID FILTER</span>
        <input v-model="filterAgent" class="adm-att-input" placeholder="contains…" />
      </label>
      <label class="adm-att-field">
        <span class="adm-att-fl">CIRCUIT</span>
        <select v-model="filterCircuit" class="adm-att-input" data-test="circuit-filter">
          <option value="">All circuits</option>
          <option v-for="c in circuits" :key="c.circuit_id" :value="c.circuit_id">
            {{ c.circuit_id }}{{ isRetired(c.circuit_id) ? ' (retired)' : '' }}
          </option>
        </select>
      </label>
      <label class="adm-att-field">
        <span class="adm-att-fl">STATUS</span>
        <select v-model="filterStatus" class="adm-att-input">
          <option value="all">All</option>
          <option value="verified">Verified</option>
          <option value="expired">Expired</option>
          <option value="revoked">Revoked</option>
        </select>
      </label>
      <label class="adm-att-field" style="max-width: 130px;">
        <span class="adm-att-fl">PAGE SIZE</span>
        <select v-model.number="limit" @change="load" class="adm-att-input">
          <option :value="50">50</option>
          <option :value="100">100</option>
          <option :value="200">200</option>
        </select>
      </label>
      <button class="adm-att-btn adm-att-btn-ghost" @click="load">↻ Reload</button>
      <button class="adm-att-btn adm-att-btn-ghost" @click="downloadCsv">↓ Daily CSV</button>
    </div>

    <!-- Table -->
    <div class="adm-att-card">
      <div class="adm-att-card-header">
        <h3 class="adm-att-card-title">All Attestations</h3>
        <span class="adm-att-badge adm-att-badge-cyan">{{ itemsRead ? filteredItems.length : '—' }} shown</span>
      </div>
      <div v-if="errorMsg" class="adm-att-err">{{ errorMsg }}</div>
      <div v-else-if="filteredItems.length === 0" class="adm-att-empty">
        <code>No attestations match the current filters.</code>
      </div>
      <div v-else class="adm-att-table-wrap">
        <table class="adm-att-table">
          <thead>
            <tr>
              <th>Status</th>
              <th>Agent</th>
              <th>Circuit</th>
              <th>Submitted</th>
              <th>Expires</th>
              <th>Revoked by</th>
              <th style="text-align: right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filteredItems" :key="a.id">
              <td>
                <span class="adm-att-status-badge" :class="`adm-att-sb-${statusOf(a)}`">
                  {{ statusOf(a) }}
                </span>
                <div v-if="!a.verified && a.failure_reason" class="adm-att-why" data-test="failure-reason">{{ a.failure_reason }}</div>
              </td>
              <td>
                <code class="adm-att-mono adm-att-did" :title="a.agent_did">{{ truncDid(a.agent_did) }}</code>
              </td>
              <td>
                <code class="adm-att-mono">{{ a.circuit_id }}</code>
                <span v-if="isRetired(a.circuit_id)" class="adm-att-status-badge adm-att-sb-failed adm-att-retired"
                  data-test="circuit-retired" :title="retiredHint(a.circuit_id)">retired</span>
              </td>
              <td class="adm-att-mono adm-att-dim">{{ dayjs(a.submitted_at).fromNow() }}</td>
              <td class="adm-att-mono adm-att-dim">
                {{ a.expires_at ? dayjs(a.expires_at).fromNow() : '—' }}
              </td>
              <td class="adm-att-mono adm-att-dim">{{ a.revoked_by || '—' }}</td>
              <td style="text-align: right;">
                <button
                  v-if="!a.revoked_at"
                  class="adm-att-btn adm-att-btn-danger adm-att-btn-sm"
                  @click="openRevoke(a)"
                >Force Revoke</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Daily series -->
    <div v-if="dailySeries.length > 0" class="adm-att-card">
      <div class="adm-att-card-header">
        <h3 class="adm-att-card-title">Daily Volume — Last 30 days</h3>
        <span class="adm-att-badge adm-att-badge-cyan">{{ dailySeries.length }} days</span>
      </div>
      <div class="adm-att-series">
        <div v-for="row in dailySeries" :key="row.date" class="adm-att-series-row">
          <span class="adm-att-series-date">{{ row.date }}</span>
          <span class="adm-att-series-track">
            <span
              class="adm-att-series-bar"
              :style="{ width: ((row.total / seriesMax) * 100) + '%' }"
            ></span>
          </span>
          <span class="adm-att-series-count">{{ row.total }}</span>
        </div>
      </div>
    </div>

  </div>

  <!-- Footer -->
  <div class="adm-att-footer">
    Last refresh {{ lastRefreshAt || '—' }} • {{ totalCount }} total attestations
  </div>

  <!-- Force-revoke modal -->
  <div v-if="revokeModalOpen" class="adm-att-modal-bg" @click.self="revokeModalOpen = false">
    <div class="adm-att-modal">
      <div class="adm-att-modal-head">
        <h3 class="adm-att-card-title">Force-Revoke Attestation</h3>
        <button class="adm-att-x" @click="revokeModalOpen = false">×</button>
      </div>
      <p class="adm-att-section-desc" v-if="revokeTarget">
        Agent: <code class="adm-att-mono">{{ revokeTarget.agent_did }}</code><br>
        Circuit: <code class="adm-att-mono">{{ revokeTarget.circuit_id }}</code>
      </p>
      <p class="adm-att-section-desc">
        Force-revocation is recorded as <code class="adm-att-mono">admin:&lt;dev_id&gt;</code> in the
        audit trail. Reputation is decremented and an EigenTrust claw-back signal is emitted.
      </p>
      <label class="adm-att-field">
        <span class="adm-att-fl">REASON</span>
        <input v-model="revokeReason" class="adm-att-input" placeholder="audit reason…" />
      </label>
      <div class="adm-att-modal-actions">
        <button class="adm-att-btn adm-att-btn-ghost" @click="revokeModalOpen = false">Cancel</button>
        <button
          class="adm-att-btn adm-att-btn-danger"
          :disabled="revokeBusy"
          @click="confirmRevoke"
        >{{ revokeBusy ? 'REVOKING…' : 'CONFIRM FORCE-REVOKE' }}</button>
      </div>
    </div>
  </div>
</div>
</template>

<style scoped>
.adm-att {
  --cyan: var(--nc-primary);
  --text-bright: #e2e8f0;
  --text-secondary: #94a3b8;
  --muted: #718299;  /* §FESUITE: 4.77:1 on the series rows (#64748b was 3.9:1) */
  --border: rgba(255,255,255,0.06);
  --mono: 'IBM Plex Mono', 'JetBrains Mono', 'Fira Code', monospace;
  /* §pass50.6 — background removed; DashboardLayout's <ViewAmbient> paints
     the security tone (route meta: viewAmbientTone='security'). */
  color: #b0bec5;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
  z-index: 1;
}

/* ── Ambient ───────────────────────────── */
.adm-att-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.adm-att-grid {
  position: absolute; inset: 0;
  background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}
.adm-att-scan {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 0%, rgba(var(--nc-primary-rgb),0.01) 50%, transparent 100%);
  background-size: 100% 200%;
  animation: admAttScan 10s linear infinite;
}
@keyframes admAttScan { 0% { background-position: 0 -100%; } 100% { background-position: 0 100%; } }
.adm-att-glow { position: absolute; border-radius: 50%; filter: blur(140px); opacity: 0.08; }
.adm-att-glow-1 { width: 400px; height: 400px; background: var(--nc-primary); top: -80px; right: -60px; }
.adm-att-glow-2 { width: 300px; height: 300px; background: #f87171; bottom: 10%; left: -80px; }

/* ── Hero ──────────────────────────────── */
.adm-att-hero { position: relative; z-index: 1; padding: 70px 24px 24px; text-align: center; }
.adm-att-hero-inner { max-width: 600px; margin: 0 auto; }
.adm-att-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: rgba(var(--nc-primary-rgb),0.06); padding: 5px 16px; border-radius: 3px;
}
.adm-att-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); animation: admAttPulse 2s ease-in-out infinite; }
@keyframes admAttPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
.adm-att-h1 { font-size: clamp(24px, 4vw, 36px); font-weight: 700; color: #fff; margin: 14px 0 8px; letter-spacing: -0.02em; }
.adm-att-accent { color: var(--cyan); }
.adm-att-lead { font-size: 13px; color: var(--muted); max-width: 520px; margin: 0 auto; }

/* ── Section ───────────────────────────── */
.adm-att-section {
  position: relative; z-index: 1;
  max-width: 1280px; margin: 0 auto;
  padding: 0 24px 40px;
  display: flex; flex-direction: column; gap: 16px;
}
.adm-att-center { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; padding: 60px 24px; }

/* ── Stats Row ─────────────────────────── */
.adm-att-stats-row { display: flex; gap: 8px; flex-wrap: wrap; }
.adm-att-stat {
  flex: 1; min-width: 140px;
  background: rgba(10,14,24,0.8);
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-left: 2px solid #64748b;
  border-radius: 5px;
  padding: 10px 14px;
  display: flex; flex-direction: column; gap: 2px;
}
.adm-att-stat-ok { border-left-color: #00c853; }
.adm-att-stat-warn { border-left-color: #ffab00; }
.adm-att-stat-bad { border-left-color: #ff1744; }
.adm-att-stat-cyan { border-left-color: var(--cyan); }
.adm-att-stat-muted { border-left-color: #334155; }
.adm-att-stat-label { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.adm-att-stat-value { font-family: var(--mono); font-size: 22px; font-weight: 700; color: var(--text-bright); }
.adm-att-stat-sub { font-family: var(--mono); font-size: 9px; color: var(--muted); }

/* ── Toolbar ───────────────────────────── */
.adm-att-toolbar {
  display: flex; gap: 12px; align-items: end; flex-wrap: wrap;
  background: rgba(10,14,24,0.6); border: 1px solid var(--border);
  border-radius: 6px; padding: 12px 14px;
}
.adm-att-field { display: flex; flex-direction: column; gap: 4px; min-width: 160px; flex: 1; }
.adm-att-fl { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.adm-att-input {
  background: rgba(0,0,0,0.4); border: 1px solid var(--border);
  color: var(--text-bright);
  padding: 8px 10px; border-radius: 4px;
  font-family: var(--mono); font-size: 12px;
  outline: none; transition: border-color 0.15s;
}
.adm-att-input:focus { border-color: rgba(var(--nc-primary-rgb),0.4); }

/* ── Cards ─────────────────────────────── */
.adm-att-card {
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border);
  border-radius: 8px; padding: 18px;
}
.adm-att-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.adm-att-card-title { font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--cyan); letter-spacing: 0.1em; text-transform: uppercase; margin: 0; }

/* ── Badge ─────────────────────────────── */
.adm-att-badge { font-family: var(--mono); font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 3px; letter-spacing: 0.06em; }
.adm-att-badge-cyan { color: var(--cyan); background: rgba(var(--nc-primary-rgb),0.12); }

/* ── Table ─────────────────────────────── */
.adm-att-table-wrap { overflow-x: auto; }
.adm-att-table { width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 11px; }
.adm-att-table th {
  text-align: left; padding: 6px 10px;
  font-size: 9px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border);
}
.adm-att-table td {
  padding: 9px 10px; border-bottom: 1px solid rgba(255,255,255,0.03);
  color: var(--text-secondary); vertical-align: middle;
}
.adm-att-table tbody tr:hover { background: rgba(var(--nc-primary-rgb),0.03); }

.adm-att-mono { font-family: var(--mono); color: var(--text-bright); }
.adm-att-dim { color: var(--muted); }
.adm-att-did { font-size: 10px; }
.adm-att-why { margin-top: 4px; max-width: 300px; font-size: 10px; line-height: 1.4; color: var(--muted); white-space: normal; }
.adm-att-retired { margin-left: 6px; }

/* ── Status badges ─────────────────────── */
.adm-att-status-badge {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  padding: 2px 7px; border-radius: 3px; letter-spacing: 0.08em; text-transform: uppercase;
}
.adm-att-sb-verified { color: #00c853; background: rgba(0,200,83,0.12); }
.adm-att-sb-expired  { color: #ffab00; background: rgba(255,171,0,0.12); }
.adm-att-sb-revoked  { color: #ff1744; background: rgba(255,23,68,0.12); }
.adm-att-sb-failed   { color: #7b8aa0; background: rgba(100,116,139,0.12); }  /* 4.75:1 on its own tint (was 3.5:1) */

/* ── Empty / err ───────────────────────── */
.adm-att-empty { font-size: 12px; color: var(--muted); padding: 20px 0; text-align: center; }
.adm-att-empty code { color: var(--cyan); font-size: 11px; background: rgba(var(--nc-primary-rgb),0.08); padding: 2px 8px; border-radius: 3px; }
.adm-att-section-desc { font-size: 11px; color: var(--muted); margin: 0 0 12px; line-height: 1.5; }
.adm-att-section-desc code { font-family: var(--mono); color: var(--text-bright); font-size: 10px; }
.adm-att-err {
  color: #f87171; font-size: 12px;
  background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.25);
  padding: 12px; border-radius: 4px; font-family: var(--mono);
}

/* ── Daily series viz ──────────────────── */
.adm-att-series { display: flex; flex-direction: column; gap: 4px; }
.adm-att-series-row { display: flex; align-items: center; gap: 12px; font-family: var(--mono); font-size: 10px; }
.adm-att-series-date { width: 110px; color: var(--muted); flex-shrink: 0; }
.adm-att-series-track {
  flex: 1; height: 16px; background: rgba(255,255,255,0.03);
  border: 1px solid var(--border); border-radius: 3px; overflow: hidden;
  position: relative;
}
.adm-att-series-bar {
  display: block; height: 100%;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.4), var(--cyan));
  border-radius: 2px; min-width: 2px;
}
.adm-att-series-count { width: 60px; text-align: right; color: var(--text-bright); font-weight: 600; }

/* ── Buttons ───────────────────────────── */
.adm-att-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 7px 14px; border-radius: 4px; border: none; cursor: pointer;
  transition: all 0.15s;
}
.adm-att-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.adm-att-btn-ghost {
  background: transparent; color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
}
.adm-att-btn-ghost:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb),0.08);
  border-color: rgba(var(--nc-primary-rgb),0.4);
}
.adm-att-btn-danger {
  background: rgba(239,68,68,0.12); color: #f87171;
  border: 1px solid rgba(239,68,68,0.25);
}
.adm-att-btn-danger:hover:not(:disabled) { background: rgba(239,68,68,0.2); }
.adm-att-btn-sm { padding: 4px 10px; font-size: 9px; }

/* ── Modal ─────────────────────────────── */
.adm-att-modal-bg {
  position: fixed; inset: 0; background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center; z-index: 100;
}
.adm-att-modal {
  width: 90%; max-width: 600px;
  background: #0c1117; border: 1px solid var(--border); border-radius: 8px;
  padding: 18px; color: var(--text-bright);
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.adm-att-modal-head {
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border); padding-bottom: 10px; margin-bottom: 12px;
}
.adm-att-x {
  background: transparent; border: none; color: var(--muted);
  font-size: 1.4rem; cursor: pointer; padding: 0 4px;
}
.adm-att-x:hover { color: #f87171; }
.adm-att-modal-actions { display: flex; gap: 12px; justify-content: end; margin-top: 16px; }

/* ── Footer ────────────────────────────── */
.adm-att-footer {
  position: relative; z-index: 1; text-align: center; padding: 24px;
  font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.08em;
}

/* ── Spinner ───────────────────────────── */
.adm-att-spinner {
  width: 28px; height: 28px;
  border: 2px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: var(--cyan); border-radius: 50%;
  animation: admAttSpin 0.8s linear infinite;
}
@keyframes admAttSpin { to { transform: rotate(360deg); } }
.adm-att-loading-text { color: var(--muted); margin-top: 12px; font-size: 12px; font-family: var(--mono); }

/* ── Responsive ────────────────────────── */
@media (max-width: 768px) {
  .adm-att-stats-row { flex-direction: column; }
  .adm-att-toolbar { flex-direction: column; align-items: stretch; }
  .adm-att-series-date { width: 80px; font-size: 9px; }
}
</style>
