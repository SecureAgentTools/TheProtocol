<template>
  <section class="op-tab op-federation">
    <!-- Sync status hero -->
    <div :class="['op-fed-hero', syncTone]">
      <div class="op-fed-hero-cols">
        <div class="op-fed-hero-col">
          <div class="op-fed-hero-eyebrow">Active peers</div>
          <div class="op-fed-hero-figure">
            {{ syncStatus?.active_peers ?? '—' }}
            <span class="op-fed-hero-figure-tail">/ {{ syncStatus?.total_peers ?? '—' }}</span>
          </div>
        </div>
        <div class="op-fed-hero-col">
          <div class="op-fed-hero-eyebrow">Last sync</div>
          <div class="op-fed-hero-figure">{{ formatRelative(syncStatus?.last_sync_run_at) }}</div>
          <div class="op-fed-hero-sub" v-if="syncStatus?.next_sync_due_at">
            next due {{ formatRelative(syncStatus.next_sync_due_at) }}
          </div>
        </div>
        <div class="op-fed-hero-col">
          <div class="op-fed-hero-eyebrow">Recent failures</div>
          <div :class="['op-fed-hero-figure', (syncStatus?.recent_failures ?? 0) > 0 ? 'op-fed-hero-figure--bad' : 'op-fed-hero-figure--ok']">
            {{ syncStatus?.recent_failures ?? 0 }}
          </div>
        </div>
        <div class="op-fed-hero-col op-fed-hero-actions">
          <button
            type="button"
            class="op-btn-primary"
            :disabled="triggering || loading"
            @click="onTriggerSync"
          >
            <span v-if="triggering" class="op-spinner-sm" />
            <span>Trigger sync</span>
          </button>
          <button
            type="button"
            class="op-btn-ghost"
            :disabled="loading"
            @click="refresh"
          >Refresh</button>
        </div>
      </div>
      <div class="op-fed-hero-banner" v-if="triggerResult">
        <span :class="['op-fed-banner-dot', triggerResult.ok ? 'op-fed-banner-dot--ok' : 'op-fed-banner-dot--bad']" />
        {{ triggerResult.text }}
      </div>
    </div>

    <!-- Policy compliance -->
    <div v-if="policy" :class="['op-fed-policy', policy.is_compliant ? 'op-fed-policy--ok' : 'op-fed-policy--bad']">
      <div class="op-fed-policy-left">
        <div class="op-fed-policy-eyebrow">Policy compliance</div>
        <div class="op-fed-policy-state">
          {{ policy.is_compliant ? 'Compliant' : 'Drift detected' }}
          <span class="op-fed-policy-version">v{{ policy.policy_version }}</span>
        </div>
      </div>
      <div class="op-fed-policy-right">
        <span v-if="policy.drift_detected" class="op-fed-policy-flag">{{ policy.drift_count }} drift flag{{ policy.drift_count === 1 ? '' : 's' }}</span>
        <span class="op-fed-policy-time" v-if="policy.last_checked_at">
          checked {{ formatRelative(policy.last_checked_at) }}
        </span>
      </div>
    </div>

    <!-- Peers list -->
    <div class="op-fed-section">
      <div class="op-fed-section-header">
        <h3 class="op-fed-section-title">Peer registries ({{ peers.length }})</h3>
        <div class="op-fed-search">
          <input
            v-model="peerFilter"
            class="op-fed-search-input"
            placeholder="filter peers by name or trust-domain"
            type="text"
          />
        </div>
      </div>
      <div v-if="loading && peers.length === 0" class="op-fed-loading">Loading peers…</div>
      <!-- §FESUITE (V0577): a failed peers read is not "No peers federated yet." -->
      <ReadFailedNotice v-else-if="peersFailed && peers.length === 0" dense :retry="refresh" data-testid="op-peers-failed" />
      <div v-else-if="filteredPeers.length === 0" class="op-fed-empty">
        {{ peers.length === 0 ? 'No peers federated yet.' : 'No peers match your filter.' }}
      </div>
      <div v-else class="op-fed-peer-grid">
        <div
          v-for="peer in filteredPeers"
          :key="peer.registry_id || peer.registry_name"
          class="op-fed-peer-card"
        >
          <div class="op-fed-peer-row">
            <div class="op-fed-peer-name">{{ peer.registry_name }}</div>
            <span :class="['op-fed-peer-status', syncPillTone(peer.sync_status)]">
              {{ peer.sync_status || 'unknown' }}
            </span>
          </div>
          <div class="op-fed-peer-meta">
            <span v-if="peer.hop_distance !== undefined && peer.hop_distance !== null" class="op-fed-peer-meta-item">
              hop {{ peer.hop_distance }}
            </span>
            <span v-if="peer.agent_count !== undefined" class="op-fed-peer-meta-item">
              {{ peer.agent_count.toLocaleString(appLocale()) }} agent{{ peer.agent_count === 1 ? '' : 's' }}
            </span>
            <span v-if="peer.last_sync_at" class="op-fed-peer-meta-item">
              synced {{ formatRelative(peer.last_sync_at) }}
            </span>
          </div>
          <a
            v-if="peer.base_url"
            :href="safeExternalUrl(peer.base_url)"
            target="_blank"
            rel="noopener"
            class="op-fed-peer-url"
          >
            {{ peer.base_url }}
            <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.4" style="margin-left: 3px; vertical-align: middle;">
              <path d="M4 2h6v6M10 2L4.5 7.5M2 4v6h6" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </a>
          <div class="op-fed-peer-domain" v-if="peer.trust_domain">
            <span class="op-fed-peer-domain-label">trust_domain</span>
            <code class="op-code">{{ peer.trust_domain }}</code>
          </div>
        </div>
      </div>
    </div>

    <!-- Local CLI bridge -->
    <div class="op-cli-bridge">
      <div class="op-cli-eyebrow">From terminal</div>
      <LocalCommand
        :command="`tp peers`"
        caption="Lists every federated peer registry your operator knows about, plus aggregate network stats."
      />
      <LocalCommand
        :command="`tp sync`"
        caption="Force-trigger a federation sync cycle right now (same effect as the Trigger Sync button above)."
        tone="warning"
      />
      <LocalCommand
        :command="`tp health --strict`"
        caption="Strict health probe — fails if federation drift or peer unreachable. Use before/after a sync to confirm reconciliation."
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted } from 'vue'
import LocalCommand from './LocalCommand.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import {
  getFederationPeers,
  getFederationSyncStatus,
  getPolicyCompliance,
  triggerFederationSync,
  type FederationPeerInfo,
  type FederationSyncStatus,
  type PolicyComplianceStatus,
} from '@/services/api/operator'

const peers = ref<FederationPeerInfo[]>([])
const syncStatus = ref<FederationSyncStatus | null>(null)
const policy = ref<PolicyComplianceStatus | null>(null)
const loading = ref(true)
const triggering = ref(false)
const triggerResult = ref<{ ok: boolean; text: string } | null>(null)
const peerFilter = ref('')

const filteredPeers = computed(() => {
  const q = peerFilter.value.trim().toLowerCase()
  if (!q) return peers.value
  return peers.value.filter(p =>
    p.registry_name.toLowerCase().includes(q) ||
    (p.trust_domain || '').toLowerCase().includes(q)
  )
})

const syncTone = computed(() => {
  if (!syncStatus.value) return 'op-fed-hero--neutral'
  if ((syncStatus.value.recent_failures || 0) > 0) return 'op-fed-hero--warn'
  if (syncStatus.value.active_peers > 0) return 'op-fed-hero--ok'
  return 'op-fed-hero--neutral'
})

const peersFailed = ref(false)
async function refresh() {
  loading.value = true
  const tasks = [
    getFederationPeers().then(v => { peers.value = v; peersFailed.value = false }).catch(() => { peersFailed.value = true }),
    getFederationSyncStatus().then(v => { syncStatus.value = v }).catch(() => {}),
    getPolicyCompliance().then(v => { policy.value = v }).catch(() => {}),
  ]
  try { await Promise.all(tasks) } finally { loading.value = false }
}

async function onTriggerSync() {
  triggering.value = true
  triggerResult.value = null
  try {
    const r = await triggerFederationSync()
    triggerResult.value = {
      ok: r.triggered,
      text: r.message || (r.triggered ? 'Sync cycle queued.' : 'Sync skipped (in-flight or rate-limited).'),
    }
    setTimeout(() => { refresh() }, 1500)
  } catch (e: any) {
    triggerResult.value = {
      ok: false,
      text: e?.response?.data?.detail || e?.message || 'Sync trigger failed.',
    }
  } finally {
    triggering.value = false
  }
}

function syncPillTone(status: string | undefined): string {
  const s = (status || '').toLowerCase()
  if (['active', 'synced', 'healthy', 'ok'].includes(s)) return 'op-fed-peer-status--ok'
  if (['stale', 'pending', 'partial'].includes(s)) return 'op-fed-peer-status--warn'
  if (['failed', 'unreachable', 'down', 'error'].includes(s)) return 'op-fed-peer-status--bad'
  return 'op-fed-peer-status--muted'
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) {
      const future = -ms
      const s = Math.floor(future / 1000)
      if (s < 60) return `in ${s}s`
      const m = Math.floor(s / 60); if (m < 60) return `in ${m}m`
      const h = Math.floor(m / 60); if (h < 24) return `in ${h}h`
      return `in ${Math.floor(h / 24)}d`
    }
    const s = Math.floor(ms / 1000)
    if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  } catch { return iso }
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

.op-fed-hero {
  padding: 1.1rem 1.4rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 4px;
  transition: border-color 0.4s;
}
.op-fed-hero--ok      { border-color: rgba(0, 230, 118, 0.28); }
.op-fed-hero--warn    { border-color: rgba(255, 176, 0, 0.32); }
.op-fed-hero--neutral { border-color: rgba(255, 255, 255, 0.1); }

.op-fed-hero-cols { display: grid; grid-template-columns: 1fr 1fr 1fr auto; gap: 1.5rem; align-items: end; }
.op-fed-hero-actions { display: flex; flex-direction: column; gap: 0.45rem; }

.op-fed-hero-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.35rem;
}
.op-fed-hero-figure {
  font-size: 1.85rem; font-weight: 600; color: #f4f9ff;
  font-family: 'IBM Plex Mono', monospace;
  line-height: 1; letter-spacing: -0.02em;
}
.op-fed-hero-figure--ok  { color: #b9ffe0; }
.op-fed-hero-figure--bad { color: #ffc4c4; }
.op-fed-hero-figure-tail {
  font-size: 0.9rem; color: rgba(255, 255, 255, 0.4); font-weight: 400;
  margin-left: 0.3rem;
}
.op-fed-hero-sub {
  font-size: 0.7rem; color: rgba(255, 255, 255, 0.45);
  margin-top: 0.25rem; font-family: 'IBM Plex Mono', monospace;
}

.op-btn-primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
  padding: 0.55rem 1rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, border-color 0.18s, box-shadow 0.18s;
  display: inline-flex; align-items: center; justify-content: center; gap: 0.4rem;
  min-height: 36px;
}
.op-btn-primary:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.28);
  border-color: rgba(var(--nc-primary-rgb), 0.8);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.2);
}
.op-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.op-btn-ghost {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.65);
  padding: 0.4rem 0.85rem;
  font-size: 0.68rem; letter-spacing: 0.09em; text-transform: uppercase;
  font-weight: 600; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  transition: background 0.18s, color 0.18s, border-color 0.18s;
  min-height: 30px;
}
.op-btn-ghost:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.35);
  color: rgba(255, 255, 255, 0.85);
}
.op-btn-ghost:disabled { opacity: 0.4; }

.op-spinner-sm {
  width: 11px; height: 11px;
  border: 1.5px solid rgba(var(--nc-primary-rgb), 0.25);
  border-top-color: rgba(var(--nc-primary-rgb), 0.95);
  border-radius: 50%; animation: opSpin 0.8s linear infinite;
}
@keyframes opSpin { to { transform: rotate(360deg); } }

.op-fed-hero-banner {
  margin-top: 0.9rem; padding: 0.45rem 0.7rem;
  background: rgba(0, 0, 0, 0.3);
  border-left: 2px solid rgba(var(--nc-primary-rgb), 0.5);
  font-size: 0.78rem; color: rgba(255, 255, 255, 0.78);
  font-family: 'IBM Plex Mono', monospace;
  display: flex; align-items: center; gap: 0.5rem;
}
.op-fed-banner-dot {
  width: 6px; height: 6px; border-radius: 50%;
}
.op-fed-banner-dot--ok  { background: #00e676; box-shadow: 0 0 6px rgba(0, 230, 118, 0.6); }
.op-fed-banner-dot--bad { background: #ff5252; box-shadow: 0 0 6px rgba(255, 82, 82, 0.6); }

.op-fed-policy {
  margin-top: 1rem;
  padding: 0.85rem 1.1rem;
  display: flex; justify-content: space-between; align-items: center;
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid;
  border-radius: 3px;
}
.op-fed-policy--ok  { border-color: rgba(0, 230, 118, 0.25); }
.op-fed-policy--bad { border-color: rgba(255, 176, 0, 0.32); background: rgba(28, 20, 0, 0.45); }
.op-fed-policy-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
}
.op-fed-policy-state {
  font-size: 1rem; font-weight: 600; color: #f4f9ff;
  margin-top: 0.2rem;
}
.op-fed-policy--ok .op-fed-policy-state  { color: #b9ffe0; }
.op-fed-policy--bad .op-fed-policy-state { color: #ffe1a0; }
.op-fed-policy-version {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; color: rgba(255, 255, 255, 0.45);
  margin-left: 0.5rem; font-weight: 400;
}
.op-fed-policy-right { display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; }
.op-fed-policy-flag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; padding: 0.18rem 0.4rem;
  background: rgba(255, 176, 0, 0.1); color: rgba(255, 200, 80, 0.95);
  border-radius: 2px;
}
.op-fed-policy-time {
  font-size: 0.7rem; color: rgba(255, 255, 255, 0.4);
  font-family: 'IBM Plex Mono', monospace;
}

.op-fed-section { margin-top: 1.4rem; }
.op-fed-section-header {
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
  margin-bottom: 0.7rem;
}
.op-fed-section-title {
  margin: 0; font-size: 0.95rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.85);
}
.op-fed-search-input {
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(255, 255, 255, 0.85);
  padding: 0.35rem 0.6rem;
  font-size: 0.78rem;
  border-radius: 2px;
  font-family: 'IBM Plex Mono', monospace;
  min-width: 220px;
  outline: none;
}
.op-fed-search-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.5);
}

.op-fed-loading, .op-fed-empty {
  padding: 2rem;
  text-align: center;
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.82rem;
  background: rgba(0, 8, 14, 0.3);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 3px;
}

.op-fed-peer-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 0.7rem;
}
.op-fed-peer-card {
  padding: 0.85rem 1rem;
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 3px;
  transition: border-color 0.2s, transform 0.2s;
}
.op-fed-peer-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  transform: translateY(-1px);
}
.op-fed-peer-row {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 0.5rem;
}
.op-fed-peer-name {
  font-size: 0.88rem; font-weight: 600;
  color: rgba(255, 255, 255, 0.92);
}
.op-fed-peer-status {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 600;
  padding: 0.15rem 0.45rem;
  border-radius: 2px;
  border: 1px solid currentColor;
}
.op-fed-peer-status--ok    { color: #00e676; background: rgba(0, 230, 118, 0.08); }
.op-fed-peer-status--warn  { color: #ffb300; background: rgba(255, 179, 0, 0.08); }
.op-fed-peer-status--bad   { color: #ff5252; background: rgba(255, 82, 82, 0.08); }
.op-fed-peer-status--muted { color: rgba(255, 255, 255, 0.4); background: rgba(255, 255, 255, 0.04); }

.op-fed-peer-meta {
  display: flex; flex-wrap: wrap; gap: 0.6rem;
  font-size: 0.72rem;
  color: rgba(255, 255, 255, 0.5);
  font-family: 'IBM Plex Mono', monospace;
  margin-bottom: 0.5rem;
}
.op-fed-peer-meta-item:not(:last-child):after {
  content: '·'; margin-left: 0.6rem; opacity: 0.4;
}

.op-fed-peer-url {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  color: rgba(var(--nc-primary-rgb), 0.85);
  text-decoration: none;
  word-break: break-all;
  margin-bottom: 0.4rem;
  padding: 0.25rem 0.4rem;
  background: rgba(0, 0, 0, 0.25);
  border-radius: 2px;
}
.op-fed-peer-url:hover { color: rgba(var(--nc-primary-rgb), 1); text-decoration: underline; }

.op-fed-peer-domain {
  display: flex; align-items: center; gap: 0.4rem;
  font-size: 0.7rem;
  color: rgba(255, 255, 255, 0.45);
}
.op-fed-peer-domain-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase;
}

.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
  color: #c0e4ff;
}

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

@media (max-width: 1024px) {
  .op-fed-hero-cols { grid-template-columns: 1fr 1fr; }
  .op-fed-hero-actions { grid-column: span 2; flex-direction: row; }
}
@media (max-width: 640px) {
  .op-tab { padding: 1rem; }
  .op-fed-hero-cols { grid-template-columns: 1fr; }
  .op-fed-section-header { flex-direction: column; align-items: stretch; }
  .op-fed-search-input { width: 100%; min-width: 0; }
  .op-fed-peer-grid { grid-template-columns: 1fr; }
}
</style>
