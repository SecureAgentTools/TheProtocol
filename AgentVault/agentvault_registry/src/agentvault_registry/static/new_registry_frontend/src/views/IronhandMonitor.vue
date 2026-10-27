<template>
<div class="ih">
  <!-- Hero -->
  <section class="ih-hero" data-tour="ironhand-hero">
    <div class="ih-hero-inner">
      <div class="ih-chip"><span class="ih-chip-dot"></span>IRONHAND</div>
      <h1 class="ih-h1">{{ t('ironhandView.h1a') }}<span class="ih-accent">{{ t('ironhandView.h1Accent') }}</span>{{ t('ironhandView.h1b') }}</h1>
      <p class="ih-lead">SPIRE identity enrollment, revocation, and integrity oversight.</p>
      <router-link to="/ironhand/theatre" class="ih-theatre-launch">⛬ Open mTLS Identity Theatre&nbsp;→</router-link>
    </div>
  </section>

  <!-- Loading -->
  <div v-if="loading" class="ih-center">
    <div class="ih-spinner"></div>
    <p class="ih-loading-text">Querying SPIRE server...</p>
  </div>

  <!-- Error -->
  <div v-else-if="error" class="ih-center">
    <p style="color: #f87171;">{{ error }}</p>
    <button @click="fetchData" class="ih-btn ih-btn-ghost" style="margin-top:12px;">Retry</button>
  </div>

  <!-- Dashboard -->
  <div v-else class="ih-section">

    <!-- ── 1. SUMMARY STATS ─────────────────────────────────── -->
    <div class="ih-stats-row">
      <div class="ih-stat ih-stat-ok">
        <span class="ih-stat-label">Enrolled</span>
        <span class="ih-stat-value">{{ data.summary.db_enrolled }}</span>
      </div>
      <div class="ih-stat" :class="data.summary.db_revoked > 0 ? 'ih-stat-bad' : 'ih-stat-muted'">
        <span class="ih-stat-label">Revoked</span>
        <span class="ih-stat-value">{{ data.summary.db_revoked }}</span>
      </div>
      <div class="ih-stat ih-stat-cyan">
        <span class="ih-stat-label">SPIRE Entries</span>
        <span class="ih-stat-value">{{ data.summary.agent_entries }}<span class="ih-stat-dim"> / {{ data.summary.total_spire_entries }}</span></span>
        <span class="ih-stat-sub">{{ data.summary.service_entries }} svc &middot; {{ data.summary.operator_entries }} op</span>
      </div>
      <div class="ih-stat" :class="data.summary.orphan_entries > 0 ? 'ih-stat-warn' : 'ih-stat-muted'">
        <span class="ih-stat-label">Orphans</span>
        <span class="ih-stat-value">{{ data.summary.orphan_entries }}</span>
      </div>
      <div class="ih-stat" :class="data.summary.missing_entries > 0 ? 'ih-stat-bad' : 'ih-stat-muted'">
        <span class="ih-stat-label">Missing</span>
        <span class="ih-stat-value">{{ data.summary.missing_entries }}</span>
      </div>
    </div>

    <!-- ── TABS ───────────────────────────────────────────────── -->
    <div class="ih-tabs">
      <button class="ih-tab" :class="{ 'ih-tab-active': activeTab === 'agents' }" @click="activeTab = 'agents'">
        Agents <span class="ih-tab-count">{{ data.enrolled.length + data.revoked.length + data.orphans.length }}</span>
      </button>
      <button class="ih-tab" :class="{ 'ih-tab-active': activeTab === 'system' }" @click="activeTab = 'system'">
        System <span class="ih-tab-count">{{ (data.services || []).length + (data.operators || []).length }}</span>
      </button>
    </div>

    <!-- ═══════════════ TAB: AGENTS ═══════════════════════════ -->
    <template v-if="activeTab === 'agents'">

    <!-- ── 2. ENROLLED AGENTS ───────────────────────────────── -->
    <div class="ih-card">
      <div class="ih-card-header">
        <h3 class="ih-card-title">Enrolled Agents</h3>
        <span class="ih-badge ih-badge-green">{{ data.enrolled.length }} active</span>
      </div>
      <div v-if="data.enrolled.length > 0" class="ih-table-wrap">
        <table class="ih-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>SPIFFE ID</th>
              <th>SPIRE</th>
              <th>Enrolled</th>
              <th>Status</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in data.enrolled" :key="a.did">
              <td>
                <div class="ih-agent-cell">
                  <span class="ih-agent-name">{{ agentName(a) }}</span>
                  <span class="ih-agent-did" :title="a.did">{{ truncDid(a.did) }}</span>
                </div>
              </td>
              <td>
                <div class="ih-spiffe-cell" @click="copyText(a.spiffe_id)" :title="'Click to copy: ' + a.spiffe_id">
                  <span class="ih-mono ih-dim">{{ truncSpiffe(a.spiffe_id) }}</span>
                  <svg class="ih-copy-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                </div>
              </td>
              <td><span class="ih-dot" :class="a.spire_entry_exists ? 'ih-dot-ok' : 'ih-dot-bad'" :title="a.spire_entry_exists ? 'SPIRE entry confirmed' : 'SPIRE entry MISSING'"></span></td>
              <td class="ih-dim">{{ timeAgo(a.enrolled_at) }}</td>
              <td><span class="ih-status-badge" :class="'ih-sb-' + a.status">{{ a.status }}</span></td>
              <td style="text-align:right;">
                <button
                  class="ih-btn ih-btn-danger ih-btn-sm"
                  @click="revokeAgent(a)"
                  :disabled="actionLoading === a.did"
                >{{ actionLoading === a.did ? '...' : 'Revoke' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="ih-empty">No agents enrolled for mTLS. Use <code>POST /api/v1/agent/enable-mtls</code> to enroll.</p>
    </div>

    <!-- ── 3. REVOKED AGENTS ────────────────────────────────── -->
    <div v-if="data.revoked.length > 0" class="ih-card ih-card-danger-border">
      <div class="ih-card-header">
        <h3 class="ih-card-title" style="color: #f87171;">Revoked Identities</h3>
        <span class="ih-badge ih-badge-red">{{ data.revoked.length }}</span>
      </div>
      <div class="ih-table-wrap">
        <table class="ih-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>SPIFFE ID (reconstructed)</th>
              <th>Last Enrolled</th>
              <th>Status</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in data.revoked" :key="a.did">
              <td>
                <div class="ih-agent-cell">
                  <span class="ih-agent-name">{{ agentName(a) }}</span>
                  <span class="ih-agent-did">{{ truncDid(a.did) }}</span>
                </div>
              </td>
              <td>
                <div class="ih-spiffe-cell" @click="copyText(a.spiffe_id)">
                  <span class="ih-mono ih-dim">{{ truncSpiffe(a.spiffe_id) }}</span>
                  <svg class="ih-copy-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                </div>
              </td>
              <td class="ih-dim">{{ timeAgo(a.enrolled_at) }}</td>
              <td><span class="ih-status-badge ih-sb-revoked">revoked</span></td>
              <td style="text-align:right;">
                <button
                  class="ih-btn ih-btn-primary ih-btn-sm"
                  @click="reenrollAgent(a)"
                  :disabled="actionLoading === a.did"
                >{{ actionLoading === a.did ? '...' : 'Re-enroll' }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ── 4. ORPHAN ENTRIES ────────────────────────────────── -->
    <div v-if="data.orphans.length > 0" class="ih-card ih-card-warn-border">
      <div class="ih-card-header">
        <h3 class="ih-card-title" style="color: #fbbf24;">Orphan SPIRE Entries</h3>
        <span class="ih-badge ih-badge-yellow">{{ data.orphans.length }}</span>
      </div>
      <p class="ih-warn-text">SPIRE entries exist but no matching enrolled agent in the database. These agents were registered manually or their enrollment was interrupted.</p>
      <div class="ih-table-wrap">
        <table class="ih-table">
          <thead>
            <tr>
              <th>SPIFFE ID</th>
              <th>Derived DID</th>
              <th style="text-align:right;">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in data.orphans" :key="o.spiffe_id">
              <td>
                <div class="ih-spiffe-cell" @click="copyText(o.spiffe_id)">
                  <span class="ih-mono ih-dim">{{ o.spiffe_id }}</span>
                  <svg class="ih-copy-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                </div>
              </td>
              <td class="ih-mono ih-dim">{{ deriveDid(o.spiffe_id) }}</td>
              <td style="text-align:right;">
                <button
                  class="ih-btn ih-btn-ghost ih-btn-sm"
                  @click="enrollOrphan(o)"
                  :disabled="actionLoading === o.spiffe_id"
                  title="Enroll this agent via API (requires agent JWT)"
                >{{ actionLoading === o.spiffe_id ? '...' : 'Enroll' }}</button>
                <button
                  class="ih-btn ih-btn-danger ih-btn-sm"
                  @click="deleteOrphan(o)"
                  :disabled="actionLoading === o.spiffe_id"
                  style="margin-left:6px;"
                  title="Delete this SPIRE entry (irreversible)"
                >Delete</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    </template><!-- END agents tab -->

    <!-- ═══════════════ TAB: SYSTEM ═══════════════════════════ -->
    <template v-if="activeTab === 'system'">

    <!-- ── SERVICE ENTRIES ──────────────────────────────────── -->
    <div class="ih-card">
      <div class="ih-card-header">
        <h3 class="ih-card-title">Service Entries</h3>
        <span class="ih-badge ih-badge-green">{{ (data.services || []).length }}</span>
      </div>
      <p class="ih-section-desc">Core infrastructure services — registries, TEG layers, event store, cert writers.</p>
      <div v-if="(data.services || []).length > 0" class="ih-table-wrap">
        <table class="ih-table">
          <thead>
            <tr>
              <th>SPIFFE ID</th>
              <th>Selector</th>
              <th>TTL</th>
              <th>DNS SANs</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in data.services" :key="s.entry_id">
              <td>
                <div class="ih-spiffe-cell" @click="copyText(s.spiffe_id)">
                  <span class="ih-mono" style="color:var(--text-secondary);font-size:11px;">{{ s.spiffe_id.replace(/^spiffe:\/\/[^/]+\//, '') }}</span>
                  <svg class="ih-copy-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                </div>
              </td>
              <td class="ih-mono ih-dim" style="font-size:10px;">{{ s.selector }}</td>
              <td class="ih-dim">{{ formatTtl(s.ttl) }}</td>
              <td class="ih-mono ih-dim" style="font-size:10px;">{{ (s.dns || []).join(', ') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="ih-empty">No service entries found.</p>
    </div>

    <!-- ── OPERATOR ENTRIES ─────────────────────────────────── -->
    <div class="ih-card">
      <div class="ih-card-header">
        <h3 class="ih-card-title">Operator Entries</h3>
        <span class="ih-badge ih-badge-green">{{ (data.operators || []).length }}</span>
      </div>
      <p class="ih-section-desc">Federated operator registries — each operator has 3 entries (registry, svid-writer, teg).</p>
      <div v-if="(data.operators || []).length > 0" class="ih-table-wrap">
        <table class="ih-table">
          <thead>
            <tr>
              <th>Operator / Service</th>
              <th>Selector</th>
              <th>TTL</th>
              <th>DNS SANs</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="o in data.operators" :key="o.entry_id">
              <td>
                <div class="ih-spiffe-cell" @click="copyText(o.spiffe_id)">
                  <span class="ih-mono" style="color:var(--text-secondary);font-size:11px;">{{ o.spiffe_id.replace(/^spiffe:\/\/[^/]+\/operator\//, '') }}</span>
                  <svg class="ih-copy-icon" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
                </div>
              </td>
              <td class="ih-mono ih-dim" style="font-size:10px;">{{ o.selector }}</td>
              <td class="ih-dim">{{ formatTtl(o.ttl) }}</td>
              <td class="ih-mono ih-dim" style="font-size:10px;">{{ (o.dns || []).join(', ') || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="ih-empty">No operator entries found.</p>
    </div>

    </template><!-- END system tab -->

    <!-- ── 5. SVID TTL + CONFIG ─────────────────────────────── -->
    <div class="ih-card">
      <h3 class="ih-card-title" style="margin-bottom:10px;">Configuration</h3>
      <div class="ih-config-grid">
        <div class="ih-config-item">
          <span class="ih-config-label">SVID TTL</span>
          <span class="ih-config-value">30 min</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Trust Domain</span>
          <span class="ih-config-value ih-mono">{{ ownTrustDomain || '—' }}</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Blocklist Poll</span>
          <span class="ih-config-value">60s (fallback)</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Hard Revocation</span>
          <span class="ih-config-value">&le; 30 min (SVID expiry)</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Soft Revocation</span>
          <span class="ih-config-value ih-val-highlight">&lt; 500ms (EventStore WS)</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Attestation</span>
          <span class="ih-config-value">x509pop</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Event Delivery</span>
          <span class="ih-config-value">Kafka + EventStore HTTP + WS</span>
        </div>
        <div class="ih-config-item">
          <span class="ih-config-label">Revocation Event</span>
          <span class="ih-config-value ih-mono">AgentMtlsRevoked</span>
        </div>
      </div>
    </div>

    <!-- ── Integrity bar ────────────────────────────────────── -->
    <div class="ih-integrity" :class="integrityOk ? 'ih-integrity-ok' : 'ih-integrity-breach'">
      <span class="ih-integrity-dot" :class="integrityOk ? 'ih-dot-ok' : 'ih-dot-bad'"></span>
      <span class="ih-integrity-label">{{ integrityOk ? 'INTEGRITY OK' : 'INTEGRITY BREACH' }}</span>
      <span class="ih-integrity-detail">{{ data.summary.orphan_entries }} orphans &middot; {{ data.summary.missing_entries }} missing</span>
      <button @click="fetchData" class="ih-btn ih-btn-ghost ih-btn-sm" :disabled="refreshing">
        {{ refreshing ? 'Refreshing...' : 'Refresh' }}
      </button>
    </div>

    <!-- ── Toast ────────────────────────────────────────────── -->
    <transition name="ih-toast">
      <div v-if="toast" class="ih-toast" :class="'ih-toast-' + toastType">{{ toast }}</div>
    </transition>
  </div>

  <footer class="ih-footer">
    <span>IRONHAND Identity Monitor &middot; SVID TTL 30m &middot; Revocation &lt; 500ms (WS) &middot; Fallback 60s (poll)</span>
  </footer>

  <!-- IH1 (audit 2026-05-07): single themed confirm modal driven by themeConfirm() helper -->
  <ConfirmActionModal
    :show="confirmShow"
    :title="confirmOpts.title"
    :message="confirmOpts.message"
    :tone="confirmOpts.tone"
    :confirm-text="confirmOpts.confirmText"
    :busy-text="confirmOpts.busyText"
    :busy="confirmBusy"
    :warning="confirmOpts.warning"
    @close="_onConfirmModalClose"
    @confirm="_onConfirmModalConfirm"
  />
</div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiClient } from '@/services/api/client'
import { useFrameAttribution } from '@/composables/useFrameAttribution'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { useI18n } from '@/composables/useI18n'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)

const { t } = useI18n()

// IH1 (audit 2026-05-07): themed confirm() helper — replaces native confirm()
// on 4 destructive SPIRE/mTLS operations. Pattern mirrors OperatorManagement.
// Backend at /admin/ironhand/* hardcodes reason="admin_revocation" (router/
// agent_mtls.py:470), so reason capture would be UX theater — themed confirm
// is the right level of friction.
interface ConfirmOpts {
  title: string
  message: string
  tone?: 'primary' | 'warn' | 'danger'
  confirmText?: string
  busyText?: string
  warning?: string
}
const confirmShow = ref(false)
const confirmOpts = ref<ConfirmOpts>({ title: '', message: '' })
const confirmBusy = ref(false)
let confirmResolver: ((ok: boolean) => void) | null = null
function themeConfirm(opts: ConfirmOpts): Promise<boolean> {
  if (confirmResolver) confirmResolver(false)
  confirmOpts.value = opts
  confirmShow.value = true
  confirmBusy.value = false
  return new Promise((resolve) => { confirmResolver = resolve })
}
function _onConfirmModalConfirm() {
  if (confirmResolver) {
    const r = confirmResolver
    confirmResolver = null
    confirmShow.value = false
    r(true)
  }
}
function _onConfirmModalClose() {
  if (confirmResolver) {
    const r = confirmResolver
    confirmResolver = null
    r(false)
  }
  confirmShow.value = false
}

const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const actionLoading = ref('')
const activeTab = ref('agents')
const toast = ref('')
const toastType = ref('ok')
const data = ref<any>({
  summary: { total_spire_entries: 0, agent_entries: 0, service_entries: 0, operator_entries: 0, db_enrolled: 0, db_revoked: 0, orphan_entries: 0, missing_entries: 0 },
  enrolled: [],
  revoked: [],
  orphans: [],
})

const integrityOk = computed(() =>
  data.value.summary.orphan_entries === 0 && data.value.summary.missing_entries === 0
)

function agentName(a: any) {
  if (a.name && !a.name.startsWith('did:')) return a.name
  // Derive from DID
  const parts = (a.did || '').split(':')
  return parts.length >= 3 ? parts[2].substring(0, 12) : a.did?.substring(0, 16) || '—'
}

function truncDid(did: string) {
  if (!did) return '—'
  const parts = did.split(':')
  if (parts.length >= 3) return `${parts[0]}:${parts[1]}:${parts[2].substring(0, 8)}...`
  return did.substring(0, 24) + '...'
}

// §FEFRAME W2: the trust domain this registry's SVIDs are issued in, from the frame manifest (was the literal of the
// retired Frame A)
const { localTrustDomain: ownTrustDomain } = useFrameAttribution()
// §FEFRAME W2: an agent SVID is spiffe://<ANY frame's trust domain>/agent/<id>; the literal agentvault.com prefix
// (the retired Frame A) matched no SVID on EU, ASIA or the sandbox, so every row showed the raw id.
const AGENT_SPIFFE = /^spiffe:\/\/[^/]+\/agent\//
function truncSpiffe(sid: string) {
  if (!sid) return '—'
  const m = sid.match(AGENT_SPIFFE)
  if (m) return '.../' + sid.substring(m[0].length, m[0].length + 20) + '...'
  return sid.substring(0, 40) + '...'
}

function deriveDid(spiffe_id: string) {
  const m = spiffe_id.match(AGENT_SPIFFE)
  if (!m) return '—'
  const sanitized = spiffe_id.substring(m[0].length)
  const parts = sanitized.split('-', 3)
  if (parts.length >= 3) return `${parts[0]}:${parts[1]}:${parts[2]}`
  return sanitized.replace(/-/g, ':')
}

function timeAgo(ts: string | null) {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}

function formatTtl(ttl: string) {
  const n = parseInt(ttl)
  if (isNaN(n)) return ttl || '—'
  if (n >= 3600) return `${(n / 3600).toFixed(1)}h`
  if (n >= 60) return `${Math.round(n / 60)}m`
  return `${n}s`
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => showToast('Copied to clipboard', 'ok'))
}

function showToast(msg: string, type: string = 'ok') {
  toast.value = msg
  toastType.value = type
  setTimeout(() => { toast.value = '' }, 2500)
}

async function fetchData() {
  if (!loading.value) refreshing.value = true
  error.value = ''
  try {
    // Per-request 15s timeout: apiClient default is 300s, which makes an
    // unresponsive SPIRE server look like an indefinite spinner. 15s is long
    // enough for a healthy mainframe + cross-region operators, short enough
    // that the user sees the Retry button quickly if something is wrong.
    const res = await apiClient.get('/admin/ironhand/identities', { timeout: 15000 })
    data.value = res.data
  } catch (err: any) {
    if (err.code === 'ECONNABORTED' || /timeout/i.test(err.message || '')) {
      error.value = 'SPIRE server did not respond within 15 seconds. Press Retry or check the SPIRE container.'
    } else {
      error.value = err.response?.data?.detail || err.response?.data?.error?.detail || err.message || 'Failed to load'
    }
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

async function revokeAgent(agent: any) {
  // IH1 (audit 2026-05-07): themed confirm replaces native confirm().
  const ok = await themeConfirm({
    title: '// REVOKE mTLS IDENTITY',
    message: `Revoke mTLS identity for <code>${agent.did}</code>?<br><br>This will:<br>• Delete the SPIRE entry<br>• Emit <code>AgentMtlsRevoked</code> event<br>• Propagate to peers via blocklist (~60s)<br>• SVID expires within 30 min`,
    tone: 'danger',
    confirmText: 'Revoke',
    busyText: 'Revoking…',
    warning: 'The agent will lose all peer-to-peer mTLS access immediately.',
  })
  if (!ok) return

  actionLoading.value = agent.did
  try {
    await apiClient.post(`/admin/ironhand/revoke/${agent.did}`)
    showToast(`Revoked: ${agent.did.substring(0, 30)}...`, 'ok')
    await fetchData()
  } catch (err: any) {
    showToast(err.response?.data?.detail || 'Revocation failed', 'error')
  } finally {
    actionLoading.value = ''
  }
}

async function reenrollAgent(agent: any) {
  // IH1: themed confirm.
  const ok = await themeConfirm({
    title: '// RE-ENROLL mTLS',
    message: `Re-enroll <code>${agent.did}</code> for mTLS? A fresh SPIRE entry will be created and a new SVID issued.`,
    tone: 'primary',
    confirmText: 'Re-enroll',
    busyText: 'Re-enrolling…',
  })
  if (!ok) return

  actionLoading.value = agent.did
  try {
    await apiClient.post(`/admin/ironhand/enroll/${agent.did}`)
    showToast(`Re-enrolled: ${agent.did.substring(0, 30)}...`, 'ok')
    await fetchData()
  } catch (err: any) {
    showToast(err.response?.data?.detail || 'Re-enrollment failed', 'error')
  } finally {
    actionLoading.value = ''
  }
}

async function enrollOrphan(orphan: any) {
  const did = deriveDid(orphan.spiffe_id)
  // IH1: themed confirm.
  const ok = await themeConfirm({
    title: '// ENROLL ORPHAN AGENT',
    message: `Enroll orphan agent <code>${did}</code>? This sets <code>mtls_enabled=true</code> in the registry DB for this agent — closes the SPIRE-vs-DB drift.`,
    tone: 'primary',
    confirmText: 'Enroll',
    busyText: 'Enrolling…',
  })
  if (!ok) return

  actionLoading.value = orphan.spiffe_id
  try {
    await apiClient.post(`/admin/ironhand/enroll/${did}`)
    showToast(`Enrolled orphan: ${did.substring(0, 30)}...`, 'ok')
    await fetchData()
  } catch (err: any) {
    showToast(err.response?.data?.detail || 'Enrollment failed', 'error')
  } finally {
    actionLoading.value = ''
  }
}

async function deleteOrphan(orphan: any) {
  // IH1: themed confirm with danger tone for irreversible op.
  const ok = await themeConfirm({
    title: '// DELETE SPIRE ENTRY',
    message: `Delete the SPIRE entry <code>${orphan.spiffe_id}</code>?`,
    tone: 'danger',
    confirmText: 'Delete Entry',
    busyText: 'Deleting…',
    warning: 'Irreversible — the agent loses its mTLS identity. Use only for confirmed-orphan SPIRE entries (no DB row).',
  })
  if (!ok) return

  actionLoading.value = orphan.spiffe_id
  try {
    await apiClient.delete('/admin/ironhand/spire-entry', { data: { spiffe_id: orphan.spiffe_id } })
    showToast('SPIRE entry deleted', 'ok')
    await fetchData()
  } catch (err: any) {
    showToast(err.response?.data?.detail || 'Deletion failed', 'error')
  } finally {
    actionLoading.value = ''
  }
}

onMounted(fetchData)
</script>

<style scoped>
.ih {
  --cyan: var(--nc-primary);
  --text-bright: #e2e8f0;
  --text-secondary: #94a3b8;
  --muted: #718299;  /* §FESUITE: 4.77:1 on the agents table (#64748b was 3.9:1) */
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
.ih-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.ih-grid {
  position: absolute; inset: 0;
  background-image: linear-gradient(rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px);
  background-size: 60px 60px;
}
.ih-scan {
  position: absolute; inset: 0;
  background: linear-gradient(180deg, transparent 0%, rgba(var(--nc-primary-rgb),0.01) 50%, transparent 100%);
  background-size: 100% 200%;
  animation: ihScan 10s linear infinite;
}
@keyframes ihScan { 0% { background-position: 0 -100%; } 100% { background-position: 0 100%; } }
.ih-glow { position: absolute; border-radius: 50%; filter: blur(140px); opacity: 0.08; }
.ih-glow-1 { width: 400px; height: 400px; background: var(--nc-primary); top: -80px; right: -60px; }
.ih-glow-2 { width: 300px; height: 300px; background: #f87171; bottom: 10%; left: -80px; }

/* ── Hero ──────────────────────────────── */
.ih-hero { position: relative; z-index: 1; padding: 70px 24px 24px; text-align: center; }
.ih-hero-inner { max-width: 600px; margin: 0 auto; }
.ih-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 700;
  letter-spacing: 0.22em; text-transform: uppercase;
  color: var(--cyan); border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  background: rgba(var(--nc-primary-rgb),0.06); padding: 5px 16px; border-radius: 3px;
}
.ih-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); animation: ihPulse 2s ease-in-out infinite; }
@keyframes ihPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.3; } }
.ih-h1 { font-size: clamp(24px, 4vw, 36px); font-weight: 700; color: #fff; margin: 14px 0 8px; letter-spacing: -0.02em; }
.ih-accent { color: var(--cyan); }
.ih-lead { font-size: 13px; color: var(--muted); max-width: 420px; margin: 0 auto; }
.ih-theatre-launch { display: inline-flex; align-items: center; gap: 6px; margin-top: 16px; font-family: var(--mono); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-decoration: none; color: #061018; background: linear-gradient(90deg, var(--cyan), #00e676); padding: 8px 18px; border-radius: 5px; box-shadow: 0 0 18px rgba(var(--nc-primary-rgb),0.3); transition: filter 0.15s, transform 0.1s; }
.ih-theatre-launch:hover { filter: brightness(1.12); transform: translateY(-1px); }

/* ── Section ───────────────────────────── */
.ih-section { position: relative; z-index: 1; max-width: 940px; margin: 0 auto; padding: 0 24px 40px; display: flex; flex-direction: column; gap: 16px; }
.ih-center { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; padding: 60px 24px; }

/* ── Stats Row ─────────────────────────── */
.ih-stats-row { display: flex; gap: 8px; flex-wrap: wrap; }
.ih-stat {
  flex: 1; min-width: 100px;
  background: rgba(10,14,24,0.8);
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-left: 2px solid #64748b;
  border-radius: 5px;
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.ih-stat-ok { border-left-color: #00c853; }
.ih-stat-warn { border-left-color: #ffab00; }
.ih-stat-bad { border-left-color: #ff1744; }
.ih-stat-cyan { border-left-color: var(--cyan); }
.ih-stat-muted { border-left-color: #334155; }
.ih-stat-label { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.ih-stat-value { font-family: var(--mono); font-size: 18px; font-weight: 700; color: var(--text-bright); }
.ih-stat-dim { font-size: 12px; color: var(--muted); font-weight: 400; }
.ih-stat-sub { font-family: var(--mono); font-size: 9px; color: var(--muted); letter-spacing: 0.05em; }

/* ── Cards ─────────────────────────────── */
.ih-card {
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid var(--border);
  border-radius: 8px; padding: 18px; transition: border-color 0.2s;
}
.ih-card:hover { border-color: rgba(var(--nc-primary-rgb),0.12); }
.ih-card-danger-border { border-left: 2px solid rgba(239,68,68,0.4); }
.ih-card-warn-border { border-left: 2px solid rgba(245,158,11,0.4); }
.ih-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ih-card-title { font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--cyan); letter-spacing: 0.1em; text-transform: uppercase; margin: 0; }

/* ── Badge ─────────────────────────────── */
.ih-badge { font-family: var(--mono); font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 3px; letter-spacing: 0.06em; }
.ih-badge-green { color: #34d399; background: rgba(16,185,129,0.15); }
.ih-badge-red { color: #f87171; background: rgba(239,68,68,0.15); }
.ih-badge-yellow { color: #fbbf24; background: rgba(245,158,11,0.15); }

/* ── Table ─────────────────────────────── */
.ih-table-wrap { overflow-x: auto; }
.ih-table {
  width: 100%; border-collapse: collapse;
  font-family: var(--mono); font-size: 11px;
}
.ih-table th {
  text-align: left; padding: 6px 10px;
  font-size: 9px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border);
}
.ih-table td {
  padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.03);
  color: var(--text-secondary); vertical-align: middle;
}
.ih-table tbody tr:hover { background: rgba(var(--nc-primary-rgb),0.03); }

/* ── Agent cell ────────────────────────── */
.ih-agent-cell { display: flex; flex-direction: column; gap: 1px; }
.ih-agent-name { font-size: 12px; color: var(--text-bright); font-weight: 500; }
.ih-agent-did { font-family: var(--mono); font-size: 9px; color: var(--muted); }

/* ── SPIFFE cell ───────────────────────── */
.ih-spiffe-cell {
  display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
  padding: 2px 4px; border-radius: 3px; transition: background 0.15s;
}
.ih-spiffe-cell:hover { background: rgba(var(--nc-primary-rgb),0.08); }
.ih-copy-icon { opacity: 0; transition: opacity 0.15s; color: var(--cyan); flex-shrink: 0; }
.ih-spiffe-cell:hover .ih-copy-icon { opacity: 1; }
/* a device with no hover (a phone): the copy hint is shown without one */
@media (hover: none) { .ih-copy-icon { opacity: 1; } }

.ih-mono { font-family: var(--mono); }
.ih-dim { color: var(--muted); }
/* ── Tabs ──────────────────────────────── */
.ih-tabs {
  display: flex; gap: 0; border-bottom: 1px solid var(--border);
}
.ih-tab {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); background: none; border: none;
  padding: 10px 20px; cursor: pointer; transition: all 0.15s;
  border-bottom: 2px solid transparent; position: relative; bottom: -1px;
}
.ih-tab:hover { color: var(--text-secondary); }
.ih-tab-active { color: var(--cyan); border-bottom-color: var(--cyan); }
.ih-tab-count {
  font-size: 9px; font-weight: 400; color: var(--muted);
  background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px;
  margin-left: 6px;
}

.ih-section-desc { font-size: 11px; color: var(--muted); margin: 0 0 12px; }
.ih-empty { font-size: 12px; color: var(--muted); margin: 8px 0 0; }
.ih-empty code { color: var(--cyan); font-size: 11px; background: rgba(var(--nc-primary-rgb),0.08); padding: 1px 5px; border-radius: 3px; }
.ih-warn-text { font-size: 11px; color: #fbbf24; margin: 0 0 10px; opacity: 0.8; }

/* ── Dots ──────────────────────────────── */
.ih-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
.ih-dot-ok { background: #00c853; box-shadow: 0 0 6px rgba(0,200,83,0.5); }
.ih-dot-bad { background: #ff1744; box-shadow: 0 0 6px rgba(255,23,68,0.5); }

/* ── Status badges ─────────────────────── */
.ih-status-badge {
  font-family: var(--mono); font-size: 9px; font-weight: 600;
  padding: 1px 6px; border-radius: 3px; letter-spacing: 0.06em; text-transform: uppercase;
}
.ih-sb-active { color: #00c853; background: rgba(0,200,83,0.12); }
.ih-sb-suspended { color: #ffab00; background: rgba(255,171,0,0.12); }
.ih-sb-revoked { color: #ff1744; background: rgba(255,23,68,0.12); }

/* ── Config grid ───────────────────────── */
.ih-config-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px 16px; }
.ih-config-item { display: flex; flex-direction: column; gap: 2px; }
.ih-config-label { font-family: var(--mono); font-size: 9px; font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
.ih-config-value { font-size: 12px; color: var(--text-bright); }
.ih-val-highlight { color: #00c853; font-weight: 600; }

/* ── Integrity bar ─────────────────────── */
.ih-integrity {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px;
  background: rgba(10,14,24,0.6);
  border: 1px solid var(--border);
  border-radius: 5px;
  font-family: var(--mono); font-size: 10px;
}
.ih-integrity-ok { border-color: rgba(0,200,83,0.2); }
.ih-integrity-breach { border-color: rgba(255,23,68,0.2); background: rgba(255,23,68,0.03); }
.ih-integrity-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ih-integrity-label { font-weight: 700; letter-spacing: 0.12em; color: var(--text-bright); text-transform: uppercase; }
.ih-integrity-detail { color: var(--muted); flex: 1; }

/* ── Buttons ───────────────────────────── */
.ih-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  letter-spacing: 0.06em; text-transform: uppercase;
  padding: 6px 14px; border-radius: 4px; border: none; cursor: pointer;
  transition: all 0.15s;
}
.ih-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ih-btn-ghost {
  background: transparent; color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
}
.ih-btn-ghost:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.08); border-color: rgba(var(--nc-primary-rgb),0.4); }
.ih-btn-primary {
  background: rgba(var(--nc-primary-rgb),0.15); color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.3);
}
.ih-btn-primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.25); }
.ih-btn-danger {
  background: rgba(239,68,68,0.12); color: #f87171;
  border: 1px solid rgba(239,68,68,0.25);
}
.ih-btn-danger:hover:not(:disabled) { background: rgba(239,68,68,0.2); }
.ih-btn-sm { padding: 3px 8px; font-size: 9px; }

/* ── Toast ─────────────────────────────── */
.ih-toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  padding: 8px 20px; border-radius: 5px; z-index: 100;
  letter-spacing: 0.04em;
}
.ih-toast-ok { background: rgba(0,200,83,0.2); color: #34d399; border: 1px solid rgba(0,200,83,0.3); }
.ih-toast-error { background: rgba(239,68,68,0.2); color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
.ih-toast-enter-active, .ih-toast-leave-active { transition: all 0.3s ease; }
.ih-toast-enter-from, .ih-toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(10px); }

/* ── Spinner ───────────────────────────── */
.ih-spinner {
  width: 28px; height: 28px;
  border: 2px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: var(--cyan);
  border-radius: 50%;
  animation: ihSpin 0.8s linear infinite;
}
@keyframes ihSpin { to { transform: rotate(360deg); } }
.ih-loading-text { color: var(--muted); margin-top: 12px; font-size: 12px; font-family: var(--mono); }

/* ── Footer ────────────────────────────── */
.ih-footer {
  position: relative; z-index: 1; text-align: center; padding: 24px;
  font-family: var(--mono); font-size: 10px; color: var(--muted); letter-spacing: 0.08em;
}

/* ── Responsive ────────────────────────── */
@media (max-width: 640px) {
  .ih-stats-row { flex-direction: column; }
  .ih-config-grid { grid-template-columns: 1fr 1fr; }
}
</style>
