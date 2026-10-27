<template>
  <section class="op-tab op-health">
    <!-- Hero status row -->
    <div :class="['op-hero', overallTone]">
      <div class="op-hero-main">
        <div class="op-hero-eyebrow">Lifecycle state</div>
        <h2 class="op-hero-title">
          <template v-if="loading">Loading…</template>
          <!-- §FESUITE (V0577): a failed lifecycle read is not "no application" (Refresh reads it again) -->
          <template v-else-if="lifecycleFailed && !lifecycle">The operator's lifecycle could not be read just now. Refresh to try again.</template>
          <template v-else-if="!lifecycle">No operator application linked to this account</template>
          <template v-else-if="driftCount === 0">All four layers in sync</template>
          <template v-else>{{ driftCount }} drift flag{{ driftCount === 1 ? '' : 's' }}</template>
        </h2>
        <p class="op-hero-sub" v-if="lifecycle && !loading">
          <template v-if="driftCount === 0">
            application · license · peer registry · cloud — all reconciled
          </template>
          <template v-else>
            {{ lifecycle.application.name }} · {{ formatRelative(latestStateAt) }}
          </template>
        </p>
      </div>
      <div class="op-hero-side">
        <button
          type="button"
          class="op-btn-secondary"
          :disabled="loading"
          @click="refresh"
        >
          <span v-if="loading" class="op-spinner-sm" />
          <span v-else>Refresh</span>
        </button>
      </div>
    </div>

    <!-- §pass66.9 — Self-restart panel + §pass66.10 — Self-logs panel.
         Both for cloud-op admins. Mainframe-side proxy endpoints
         authenticate via the op's own federation license, so no
         mainframe admin credentials required. -->
    <div class="op-self-restart-panel">
      <div class="op-self-restart-eyebrow">Cloud-op stack actions</div>
      <div class="op-self-restart-row">
        <div>
          <div class="op-self-restart-title">Restart my registry</div>
          <p class="op-self-restart-sub">
            Bounce the registry container in your cloud-op stack. Equivalent of
            <code>tp-operator restart registry</code> from a shell (which you
            don't have on the mainframe's host). Briefly unavailable ~5-15s.
            Authenticated via your federation license — no mainframe admin
            credentials required.
          </p>
        </div>
        <button
          type="button"
          class="op-btn-secondary"
          :disabled="restarting"
          @click="onSelfRestart"
        >
          <span v-if="restarting" class="op-spinner-sm" />
          <span v-else>Restart registry</span>
        </button>
      </div>
      <p v-if="restartMsg" :class="['op-self-restart-msg', restartOk ? 'op-self-restart-msg--ok' : 'op-self-restart-msg--err']">
        {{ restartMsg }}
      </p>
      <div class="op-self-restart-row" style="margin-top: 12px;">
        <div>
          <div class="op-self-restart-title">View my logs</div>
          <p class="op-self-restart-sub">
            Tail the last N lines of any service in your stack
            (registry / teg-layer / nginx-federation / redis / db / etc.).
            Same auth as restart — your federation license.
          </p>
        </div>
        <button
          type="button"
          class="op-btn-secondary"
          @click="openSelfLogs"
        >
          View logs
        </button>
      </div>
    </div>

    <!-- §pass66.10 — Self-logs modal -->
    <div v-if="showLogsModal" class="op-logs-overlay" @click.self="showLogsModal = false">
      <div class="op-logs-modal">
        <div class="op-logs-header">
          <div class="op-logs-title">// MY STACK LOGS</div>
          <button class="op-logs-close" @click="showLogsModal = false">✕</button>
        </div>
        <div class="op-logs-controls">
          <label for="ophealthtab-sel-93">Service</label>
          <select id="ophealthtab-sel-93" v-model="logsService" @change="fetchSelfLogs">
            <option value="registry">registry</option>
            <option value="teg-layer">teg-layer</option>
            <option value="nginx-federation">nginx-federation</option>
            <option value="redis">redis</option>
            <option value="db">db</option>
            <option value="teg-db">teg-db</option>
            <option value="pgbouncer">pgbouncer</option>
            <option value="spire-agent">spire-agent</option>
            <option value="cert-writer">cert-writer</option>
            <option value="all">all (interleaved)</option>
          </select>
          <label>Tail</label>
          <input v-model.number="logsTail" type="number" min="10" max="2000" @change="fetchSelfLogs" />
          <button @click="fetchSelfLogs" :disabled="logsLoading" class="op-btn-secondary">
            {{ logsLoading ? '⟳ Loading…' : '↻ Refresh' }}
          </button>
        </div>
        <pre v-if="logsError" class="op-logs-err">{{ logsError }}</pre>
        <pre v-else class="op-logs-output">{{ logsOutput || (logsLoading ? 'Loading…' : '(no output)') }}</pre>
      </div>
    </div>

    <!-- Drift flags strip (always visible if any) -->
    <div v-if="driftCount > 0" class="op-drift-strip">
      <div class="op-drift-eyebrow">Drift flags</div>
      <div class="op-drift-list">
        <span v-for="flag in lifecycle!.drift_flags" :key="flag" class="op-drift-chip">
          <span class="op-drift-chip-dot" />
          {{ flag }}
        </span>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="!loading && !lifecycle" class="op-empty">
      <div class="op-empty-title">No operator application found</div>
      <p class="op-empty-body">
        You haven't provisioned a cloud operator (or applied to host a registry) on this account yet.
        Head to the Account tab → Provision a cloud-op to start.
      </p>
    </div>

    <!-- 4-layer cards -->
    <div v-if="lifecycle" class="op-layers">
      <!-- Application -->
      <div class="op-layer-card">
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 1 · Application</div>
          <span :class="['op-status-pill', statusPillTone(lifecycle.application.status)]">
            {{ lifecycle.application.status }}
          </span>
        </div>
        <dl class="op-layer-dl">
          <div><dt>Name</dt><dd>{{ lifecycle.application.name }}</dd></div>
          <div><dt>Organization</dt><dd>{{ lifecycle.application.organization || '—' }}</dd></div>
          <div><dt>Submitted</dt><dd>{{ formatAbsolute(lifecycle.application.created_at) }}</dd></div>
          <div><dt>Activated</dt><dd>{{ formatAbsolute(lifecycle.application.activated_at) }}</dd></div>
          <div v-if="lifecycle.application.revoked_at">
            <dt>Revoked</dt><dd>{{ formatAbsolute(lifecycle.application.revoked_at) }}</dd>
          </div>
          <div v-if="lifecycle.application.revoked_reason">
            <dt>Reason</dt><dd>{{ lifecycle.application.revoked_reason }}</dd>
          </div>
        </dl>
      </div>

      <!-- License (cloud-op only) -->
      <div class="op-layer-card" v-if="lifecycle.federation_license">
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 2 · Federation License</div>
          <span :class="['op-status-pill', statusPillTone(lifecycle.federation_license.status)]">
            {{ lifecycle.federation_license.status }}
          </span>
        </div>
        <dl class="op-layer-dl">
          <div><dt>Key prefix</dt>
            <dd><code class="op-code">{{ lifecycle.federation_license.license_key_prefix }}…</code></dd>
          </div>
          <div><dt>Tier</dt><dd>{{ lifecycle.federation_license.federation_tier || 'standard' }}</dd></div>
          <div><dt>Operator DID</dt>
            <dd><code class="op-code">{{ truncateDid(lifecycle.federation_license.operator_did) }}</code></dd>
          </div>
          <div><dt>Issued</dt><dd>{{ formatAbsolute(lifecycle.federation_license.issued_at) }}</dd></div>
          <div><dt>Last seen</dt><dd>{{ formatAbsolute(lifecycle.federation_license.last_seen_at) }}</dd></div>
          <div><dt>Event count</dt><dd>{{ lifecycle.federation_license.event_count.toLocaleString(appLocale()) }}</dd></div>
        </dl>
      </div>
      <div class="op-layer-card op-layer-card--empty" v-else>
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 2 · Federation License</div>
          <span class="op-status-pill op-status-pill--muted">n/a (mainframe)</span>
        </div>
        <p class="op-layer-empty">Federation licenses apply to cloud-ops only.</p>
      </div>

      <!-- Peer registry -->
      <div class="op-layer-card" v-if="lifecycle.peer_registry">
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 3 · Peer Registry</div>
          <span :class="['op-status-pill', lifecycle.peer_registry.bfs_reachable ? 'op-status-pill--ok' : 'op-status-pill--warn']">
            {{ lifecycle.peer_registry.bfs_reachable ? 'reachable' : 'stale' }}
          </span>
        </div>
        <dl class="op-layer-dl">
          <div><dt>Peer name</dt><dd>{{ lifecycle.peer_registry.name }}</dd></div>
          <div><dt>Type</dt><dd>{{ lifecycle.peer_registry.peer_type }}</dd></div>
          <div><dt>Hop</dt><dd>{{ lifecycle.peer_registry.hop_distance ?? '—' }}</dd></div>
          <div><dt>Last synced</dt><dd>{{ formatAbsolute(lifecycle.peer_registry.last_synced_at) }}</dd></div>
          <div><dt>Last in topology</dt><dd>{{ formatRelative(lifecycle.peer_registry.last_seen_in_topology_at) }}</dd></div>
          <div><dt>Base URL</dt>
            <dd>
              <a class="op-link" :href="safeExternalUrl(lifecycle.peer_registry.base_url)" target="_blank" rel="noopener">
                {{ lifecycle.peer_registry.base_url }}
              </a>
            </dd>
          </div>
        </dl>
      </div>
      <div class="op-layer-card op-layer-card--empty" v-else>
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 3 · Peer Registry</div>
          <span class="op-status-pill op-status-pill--muted">not yet registered</span>
        </div>
        <p class="op-layer-empty">The mainframe hasn't ingested this operator as a peer yet.</p>
      </div>

      <!-- Cloud -->
      <div class="op-layer-card" v-if="lifecycle.cloud">
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 4 · Cloud Provisioning</div>
          <span :class="['op-status-pill', lifecycle.cloud.cloud_torn_down_at ? 'op-status-pill--down' : 'op-status-pill--ok']">
            {{ lifecycle.cloud.cloud_torn_down_at ? 'torn down' : 'provisioned' }}
          </span>
        </div>
        <dl class="op-layer-dl">
          <div><dt>URL</dt>
            <dd v-if="lifecycle.cloud.cloud_url">
              <a class="op-link" :href="safeExternalUrl(lifecycle.cloud.cloud_url)" target="_blank" rel="noopener">
                {{ lifecycle.cloud.cloud_url }}
              </a>
            </dd>
            <dd v-else>—</dd>
          </div>
          <div><dt>Port base</dt><dd>{{ lifecycle.cloud.cloud_port_base ?? '—' }}</dd></div>
          <div><dt>Provisioned</dt><dd>{{ formatAbsolute(lifecycle.cloud.cloud_provisioned_at) }}</dd></div>
          <div v-if="lifecycle.cloud.cloud_torn_down_at">
            <dt>Torn down</dt><dd>{{ formatAbsolute(lifecycle.cloud.cloud_torn_down_at) }}</dd>
          </div>
          <div v-if="lifecycle.cloud.cloud_stack_dir">
            <dt>Stack dir</dt><dd><code class="op-code">{{ lifecycle.cloud.cloud_stack_dir }}</code></dd>
          </div>
        </dl>
      </div>
      <div class="op-layer-card op-layer-card--empty" v-else>
        <div class="op-layer-header">
          <div class="op-layer-eyebrow">Layer 4 · Cloud Provisioning</div>
          <span class="op-status-pill op-status-pill--muted">self-hosted</span>
        </div>
        <p class="op-layer-empty">Application not marked cloud_hosted — operator runs on their own host.</p>
      </div>
    </div>

    <!-- Local diagnostic command bridge -->
    <div v-if="lifecycle" class="op-cli-bridge">
      <div class="op-cli-eyebrow">Drill deeper via terminal</div>
      <LocalCommand
        :command="`tp doctor`"
        caption="Pulls a host-side diagnostic snapshot (compose state · disk · SPIRE bundle freshness · last 5 errors). Read-only. Paste output into support tickets."
      />
      <LocalCommand
        :command="`tp status`"
        caption="Compact one-line summary across all containers in your operator stack. Aggregate of docker compose ps."
      />
      <LocalCommand
        :command="`tp health --strict`"
        caption="Strict health probe — registry + federation + eventstore. Non-zero exit if any fail."
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import LocalCommand from './LocalCommand.vue'
import { getMyLifecycle, type OperatorLifecycle } from '@/services/api/operator'
import { apiClient } from '@/services/api/client'

const lifecycle = ref<OperatorLifecycle | null>(null)
const loading = ref(true)

// §pass66.9 — Self-restart panel state
const restarting = ref(false)
const restartMsg = ref<string>('')
const restartOk = ref<boolean>(false)

async function onSelfRestart() {
  if (!confirm('Restart your registry? It will be briefly unavailable (~5-15s).')) return
  restarting.value = true
  restartMsg.value = ''
  try {
    const r = await apiClient.post('/operator-portal/self-restart', { service: 'registry' })
    restartOk.value = true
    restartMsg.value = `Restarted ${r.data.operator_name} :: registry in ${r.data.duration_ms}ms via ${r.data.auth_mode || 'federation_license'}.`
  } catch (e: any) {
    restartOk.value = false
    restartMsg.value = e.response?.data?.detail || e.message || 'Restart failed'
  } finally {
    restarting.value = false
  }
}

// §pass66.10 — Self-logs modal state + handler
const showLogsModal = ref(false)
const logsService = ref<string>('registry')
const logsTail = ref<number>(200)
const logsLoading = ref(false)
const logsOutput = ref<string>('')
const logsError = ref<string>('')

function openSelfLogs() {
  showLogsModal.value = true
  logsService.value = 'registry'
  logsTail.value = 200
  logsOutput.value = ''
  logsError.value = ''
  fetchSelfLogs()
}

async function fetchSelfLogs() {
  logsLoading.value = true
  logsError.value = ''
  try {
    const r = await apiClient.get('/operator-portal/self-logs', {
      params: { service: logsService.value, tail: logsTail.value },
    })
    logsOutput.value = r.data.output || ''
  } catch (e: any) {
    logsError.value = e.response?.data?.detail || e.message || 'Failed to fetch logs'
    logsOutput.value = ''
  } finally {
    logsLoading.value = false
  }
}

const driftCount = computed(() => lifecycle.value?.drift_flags.length || 0)

const overallTone = computed(() => {
  if (loading.value) return 'op-hero--loading'
  if (!lifecycle.value) return 'op-hero--neutral'
  if (driftCount.value === 0) return 'op-hero--ok'
  if (driftCount.value < 3) return 'op-hero--warn'
  return 'op-hero--critical'
})

const latestStateAt = computed(() => {
  const lc = lifecycle.value
  if (!lc) return null
  const candidates: (string | null | undefined)[] = [
    lc.peer_registry?.last_synced_at,
    lc.peer_registry?.last_seen_in_topology_at,
    lc.federation_license?.last_seen_at,
    lc.application.activated_at,
  ]
  const recent = candidates.filter((s): s is string => Boolean(s)).sort().reverse()
  return recent[0] || null
})

const lifecycleFailed = ref(false)
async function refresh() {
  loading.value = true
  lifecycleFailed.value = false
  try { lifecycle.value = await getMyLifecycle() }
  catch { lifecycleFailed.value = true }   // a lifecycle read before stays on screen
  finally { loading.value = false }
}

function statusPillTone(s: string): string {
  const lower = (s || '').toLowerCase()
  if (['active', 'approved', 'activated', 'healthy'].includes(lower)) return 'op-status-pill--ok'
  if (['suspended', 'pending'].includes(lower)) return 'op-status-pill--warn'
  if (['revoked', 'rejected', 'down', 'unhealthy'].includes(lower)) return 'op-status-pill--down'
  return 'op-status-pill--muted'
}

function formatAbsolute(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString(appLocale(), { dateStyle: 'medium', timeStyle: 'short' })
  } catch { return iso }
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) return 'in the future'
    const s = Math.floor(ms / 1000)
    if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h}h ago`
    const d = Math.floor(h / 24)
    return `${d}d ago`
  } catch { return iso }
}

function truncateDid(did: string): string {
  if (!did) return '—'
  if (did.length <= 40) return did
  return did.slice(0, 22) + '…' + did.slice(-10)
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

.op-hero {
  display: flex; align-items: center; gap: 1.5rem;
  padding: 1.2rem 1.4rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 4px;
  transition: border-color 0.4s, background 0.4s;
}
.op-hero--loading  { border-color: rgba(var(--nc-primary-rgb), 0.12); }
.op-hero--neutral  { border-color: rgba(255, 255, 255, 0.08); }
.op-hero--ok       { border-color: rgba(0, 230, 118, 0.28); background: rgba(0, 24, 12, 0.45); }
.op-hero--warn     { border-color: rgba(255, 176, 0, 0.32); background: rgba(28, 20, 0, 0.5); }
.op-hero--critical { border-color: rgba(255, 82, 82, 0.4); background: rgba(28, 0, 0, 0.5); }

.op-hero-main { flex: 1 1 auto; min-width: 0; }
.op-hero-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.4rem;
}
.op-hero-title {
  margin: 0 0 0.3rem; font-size: 1.45rem; font-weight: 600;
  color: #f4f9ff; letter-spacing: -0.01em;
}
.op-hero--ok .op-hero-title       { color: #b9ffe0; }
.op-hero--warn .op-hero-title     { color: #ffe1a0; }
.op-hero--critical .op-hero-title { color: #ffc4c4; }
.op-hero-sub {
  margin: 0; font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55); font-family: 'IBM Plex Mono', monospace;
}

.op-btn-secondary {
  background: rgba(var(--nc-primary-rgb), 0.06);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.95);
  padding: 0.5rem 1rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 600; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s;
  display: inline-flex; align-items: center; gap: 0.4rem;
  min-height: 36px;
}
.op-btn-secondary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
}
.op-btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
.op-spinner-sm {
  width: 12px; height: 12px;
  border: 1.5px solid rgba(var(--nc-primary-rgb), 0.25);
  border-top-color: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 50%; animation: opSpin 0.8s linear infinite;
}
@keyframes opSpin { to { transform: rotate(360deg); } }

/* §pass66.9 — self-restart panel */
.op-self-restart-panel {
  background: rgba(0, 210, 210, 0.04);
  border: 1px solid rgba(0, 210, 210, 0.18);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.op-self-restart-eyebrow {
  font-size: 0.65rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(0, 210, 210, 0.85);
  margin-bottom: 8px;
}
.op-self-restart-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}
.op-self-restart-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
  margin-bottom: 4px;
}
.op-self-restart-sub {
  font-size: 0.75rem;
  color: var(--text-secondary, #94a3b8);
  margin: 0;
  max-width: 600px;
}
.op-self-restart-msg {
  margin-top: 10px;
  font-size: 0.75rem;
  padding: 6px 10px;
  border-radius: 4px;
}
.op-self-restart-msg--ok {
  color: #6ee7b7;
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.25);
}
.op-self-restart-msg--err {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.25);
}

/* §pass66.10 — self-logs modal */
.op-logs-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex; align-items: center; justify-content: center;
  z-index: 9999;
  padding: 20px;
}
.op-logs-modal {
  background: #0a0e18;
  border: 1px solid rgba(0, 210, 210, 0.3);
  border-radius: 8px;
  width: 900px; max-width: 95vw;
  max-height: 85vh;
  display: flex; flex-direction: column;
  font-family: 'IBM Plex Mono', monospace;
}
.op-logs-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
.op-logs-title {
  font-size: 0.85rem; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(0, 210, 210, 0.95);
}
.op-logs-close {
  background: none; border: none; color: #94a3b8;
  font-size: 1.1rem; cursor: pointer;
}
.op-logs-close:hover { color: #e2e8f0; }
.op-logs-controls {
  display: flex; gap: 8px; align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 0.75rem;
}
.op-logs-controls label { color: #94a3b8; }
.op-logs-controls select, .op-logs-controls input {
  background: #0a0e18; color: #e2e8f0;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px; padding: 4px 8px; font-size: 0.75rem;
  font-family: inherit;
}
.op-logs-controls select { min-width: 180px; }
.op-logs-controls input { width: 80px; }
.op-logs-controls button:last-child { margin-left: auto; }
.op-logs-output, .op-logs-err {
  flex: 1; overflow-y: auto;
  background: #000; color: #d1fae5;
  padding: 12px 16px;
  font-size: 0.7rem; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  margin: 0;
}
.op-logs-err { color: #fca5a5; background: rgba(239, 68, 68, 0.08); }

.op-drift-strip {
  margin-top: 1rem;
  padding: 0.8rem 1rem;
  background: rgba(28, 16, 0, 0.6);
  border: 1px solid rgba(255, 176, 0, 0.32);
  border-radius: 3px;
}
.op-drift-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 200, 80, 0.85); font-weight: 600; margin-bottom: 0.4rem;
}
.op-drift-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.op-drift-chip {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.25rem 0.55rem;
  background: rgba(255, 176, 0, 0.1);
  border: 1px solid rgba(255, 176, 0, 0.32);
  border-radius: 2px;
  font-size: 0.72rem; letter-spacing: 0.04em;
  font-family: 'IBM Plex Mono', monospace;
  color: rgba(255, 220, 160, 0.95);
}
.op-drift-chip-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(255, 176, 0, 0.85);
  box-shadow: 0 0 6px rgba(255, 176, 0, 0.6);
}

.op-empty {
  margin-top: 1.5rem;
  padding: 2rem;
  background: rgba(0, 8, 14, 0.4);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 4px;
  text-align: center;
}
.op-empty-title {
  font-size: 1.05rem; font-weight: 600; color: rgba(255, 255, 255, 0.85);
  margin-bottom: 0.5rem;
}
.op-empty-body {
  margin: 0; font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.55); line-height: 1.55;
}

.op-layers {
  margin-top: 1.4rem;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 1rem;
}
.op-layer-card {
  padding: 1rem 1.1rem;
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 3px;
  transition: border-color 0.25s, background 0.25s;
}
.op-layer-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.28); }
.op-layer-card--empty { border-style: dashed; opacity: 0.6; }
.op-layer-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 0.8rem;
  padding-bottom: 0.55rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}
.op-layer-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 600;
}
.op-layer-empty {
  margin: 0; font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.45); font-style: italic;
}

.op-status-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 600;
  padding: 0.2rem 0.55rem;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.op-status-pill--ok     { color: #00e676; background: rgba(0, 230, 118, 0.08); }
.op-status-pill--warn   { color: #ffb300; background: rgba(255, 179, 0, 0.08); }
.op-status-pill--down   { color: #ff5252; background: rgba(255, 82, 82, 0.08); }
.op-status-pill--muted  { color: rgba(255, 255, 255, 0.45); background: rgba(255, 255, 255, 0.04); }

.op-layer-dl { margin: 0; }
.op-layer-dl > div {
  display: grid; grid-template-columns: 120px 1fr; gap: 0.6rem;
  padding: 0.32rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
  font-size: 0.78rem;
}
.op-layer-dl > div:last-child { border-bottom: none; }
.op-layer-dl dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.45); text-transform: uppercase;
}
.op-layer-dl dd {
  margin: 0;
  color: rgba(255, 255, 255, 0.85);
  word-break: break-all;
  min-width: 0;
}
.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
  color: #c0e4ff;
}
.op-link {
  color: rgba(var(--nc-primary-rgb), 0.95);
  text-decoration: none;
  border-bottom: 1px dotted rgba(var(--nc-primary-rgb), 0.35);
}
.op-link:hover { border-bottom-style: solid; }

.op-cli-bridge {
  margin-top: 1.8rem;
  padding-top: 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.op-cli-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45); font-weight: 600;
  margin-bottom: 0.6rem;
}

@media (max-width: 768px) {
  .op-tab { padding: 1rem; }
  .op-hero { flex-direction: column; align-items: stretch; gap: 0.8rem; }
  .op-layers { grid-template-columns: 1fr; }
  .op-layer-dl > div { grid-template-columns: 1fr; gap: 0.15rem; }
}
</style>
