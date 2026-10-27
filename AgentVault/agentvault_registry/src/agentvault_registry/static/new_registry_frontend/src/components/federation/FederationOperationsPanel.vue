<template>
  <!-- 2026-05-08 polish round 3: Federation Operations panel.
       Used as an admin-gated tab inside Federation.vue (mounts as the
       3rd tab next to Tiers + Network). NO outer hero/ambient — those
       are owned by Federation.vue's wrapper. Body-only component. -->
  <div class="fop" data-tour="fed-ops">
    <div v-if="loading && !data" class="fop-center">
      <div class="fop-spinner"></div>
      <p class="fop-loading-text">Loading topology…</p>
    </div>

    <div v-else-if="error && !data" class="fop-center">
      <p class="fop-error-text"><Icon name="mdi:alert" /> {{ error }}</p>
      <button class="fop-btn fop-btn--ghost" @click="refresh">Retry</button>
    </div>

    <template v-else-if="data">
      <!-- Toolbar -->
      <div class="fop-toolbar">
        <div class="fop-toolbar-group">
          <span class="fop-toolbar-label">TIER</span>
          <button
            v-for="t in TIER_FILTERS" :key="t.value"
            class="fop-chip-btn"
            :class="{ 'fop-chip-btn--active': tierFilter === t.value }"
            :disabled="loading"
            @click="setTier(t.value)"
          >
            {{ t.label }}
            <span v-if="t.value !== 'all' && tierCount(t.value) > 0" class="fop-chip-count">{{ tierCount(t.value) }}</span>
          </button>
        </div>

        <input
          v-model="search"
          type="text"
          placeholder="Search by name, URL, trust domain…"
          class="fop-search"
        />

        <span class="fop-toolbar-spacer"></span>

        <div class="fop-toolbar-group">
          <label class="fop-toggle">
            <input type="checkbox" v-model="autoRefresh" />
            <span class="fop-toggle-track"><span class="fop-toggle-knob"></span></span>
            <span class="fop-toggle-label">Auto-refresh 60s</span>
          </label>
        </div>
        <div class="fop-toolbar-group fop-toolbar-meta">
          <span class="fop-toolbar-label">LAST</span>
          <span class="fop-toolbar-val">{{ lastRefreshAt || '—' }}</span>
          <button class="fop-btn fop-btn--ghost" :disabled="loading" @click="refresh">↻</button>
          <button class="fop-btn fop-btn--ghost" :disabled="!filteredPeers.length" @click="exportCsv">⤓ CSV</button>
        </div>
      </div>

      <!-- Hero stats from canonical summary block -->
      <div class="fop-stats">
        <div class="fop-stat-card">
          <div class="fop-stat-key">PEERS</div>
          <div class="fop-stat-val fop-stat-val--cyan">{{ summary.total_peers }}</div>
          <div class="fop-stat-sub fop-stat-sub-grid">
            <span v-for="(c, k) in summary.peers_by_type" :key="k" class="fop-pill fop-pill--violet">{{ k }}: {{ c }}</span>
          </div>
        </div>

        <div class="fop-stat-card">
          <div class="fop-stat-key">HEALTHY</div>
          <div class="fop-stat-val" :class="summary.healthy_count === summary.total_peers ? 'fop-stat-val--green' : 'fop-stat-val--warn'">
            {{ summary.healthy_count }}/{{ summary.total_peers }}
          </div>
          <div class="fop-stat-sub">
            {{ unhealthyCount }} unhealthy ·
            {{ bfsUnreachableCount }} BFS-unreachable
          </div>
        </div>

        <div class="fop-stat-card">
          <div class="fop-stat-key">LICENSE STATE</div>
          <div class="fop-stat-val fop-stat-val--cyan">{{ summary.license_status_breakdown.active || 0 }}</div>
          <div class="fop-stat-sub fop-stat-sub-grid">
            <span v-if="summary.license_status_breakdown.active" class="fop-pill fop-pill--green">{{ summary.license_status_breakdown.active }} active</span>
            <span v-if="summary.license_status_breakdown.suspended" class="fop-pill fop-pill--warn">{{ summary.license_status_breakdown.suspended }} suspended</span>
            <span v-if="summary.license_status_breakdown.revoked" class="fop-pill fop-pill--red">{{ summary.license_status_breakdown.revoked }} revoked</span>
            <span v-if="summary.license_status_breakdown.none" class="fop-pill fop-pill--muted">{{ summary.license_status_breakdown.none }} no-license</span>
          </div>
        </div>

        <div class="fop-stat-card">
          <div class="fop-stat-key">DRIFT</div>
          <div class="fop-stat-val" :class="summary.drift_count > 0 ? 'fop-stat-val--red' : 'fop-stat-val--green'">
            {{ summary.drift_count }}
          </div>
          <div class="fop-stat-sub">
            <span v-if="summary.drift_count === 0">all peers in steady state</span>
            <span v-else class="fop-pill fop-pill--red">attention required</span>
          </div>
        </div>
      </div>

      <!-- Drift banner -->
      <div v-if="driftedPeers.length > 0" class="fop-drift-banner">
        <div class="fop-drift-head">
          <span class="fop-drift-icon"><Icon name="mdi:alert" /></span>
          <span class="fop-drift-title">{{ driftedPeers.length }} peer{{ driftedPeers.length === 1 ? '' : 's' }} flagged for drift remediation</span>
        </div>
        <div class="fop-drift-list">
          <button
            v-for="p in driftedPeers" :key="p.id"
            class="fop-drift-item"
            @click="expandedId = p.id; scrollToPeer(p.id)"
          >
            <code>{{ p.name }}</code>
            <span class="fop-drift-flags">
              <span v-for="f in (p.drift_flags || [])" :key="f" class="fop-pill fop-pill--red">{{ f }}</span>
            </span>
          </button>
        </div>
      </div>

      <!-- Peer list -->
      <div v-if="filteredPeers.length === 0" class="fop-empty">
        <div class="fop-empty-glyph">∅</div>
        <p class="fop-empty-title">No peers match this filter.</p>
        <button v-if="search || tierFilter !== 'all'" class="fop-btn fop-btn--ghost" @click="resetFilters">Reset</button>
      </div>

      <div v-else class="fop-feed-list">
        <div
          v-for="p in filteredPeers" :key="p.id"
          :ref="el => registerPeerRef(p.id, el as HTMLElement | null)"
          class="fop-feed-row"
          :class="{
            'fop-feed-row--expanded': expandedId === p.id,
            'fop-feed-row--unhealthy': p.healthy === false || (p.health_check_failure_count || 0) > 0,
            'fop-feed-row--drifted': p.has_drift === true,
          }"
          @click="toggleExpand(p.id)"
        >
          <div class="fop-feed-head">
            <span class="fop-feed-id">#{{ p.id }}</span>
            <span class="fop-status-pill" :class="statusPillClass(p.status)">{{ p.status }}</span>
            <span class="fop-pill" :class="tierPillClass(p.peer_type)">{{ tierLabel(p.peer_type) }}</span>
            <span v-if="p.hop_distance !== null && p.hop_distance !== undefined && p.hop_distance > 0" class="fop-pill fop-pill--cyan">hop {{ p.hop_distance }}</span>
            <span v-if="p.bfs_reachable === false" class="fop-pill fop-pill--red">BFS-unreachable</span>
            <span v-if="p.has_drift" class="fop-pill fop-pill--red">DRIFT × {{ (p.drift_flags || []).length }}</span>
            <span v-if="p.license_status === 'suspended'" class="fop-pill fop-pill--warn">LICENSE SUSPENDED</span>
            <span v-if="p.license_status === 'revoked'" class="fop-pill fop-pill--red">LICENSE REVOKED</span>
            <span v-if="p.cloud_hosted" class="fop-pill fop-pill--violet">CLOUD-HOSTED</span>
            <span v-if="p.spire_bundle_active === false && p.peer_type === 'frame'" class="fop-pill fop-pill--warn">SPIRE BUNDLE INACTIVE</span>

            <span class="fop-feed-name">{{ p.name }}</span>
            <span v-if="p.trust_domain" class="fop-feed-domain">{{ p.trust_domain }}</span>

            <span class="fop-feed-spacer"></span>

            <span class="fop-feed-meta">last sync: <strong>{{ formatRel(p.last_synced_at) }}</strong></span>
            <span v-if="p.bayesian_discount !== null && p.bayesian_discount !== undefined" class="fop-pill" :class="trustPillClass(p.bayesian_discount)">trust {{ p.bayesian_discount.toFixed(3) }}</span>
            <span class="fop-feed-caret">{{ expandedId === p.id ? '▾' : '▸' }}</span>
          </div>

          <div v-if="expandedId === p.id" class="fop-feed-detail" @click.stop>
            <!-- Drift hints -->
            <div v-if="p.drift_flags && p.drift_flags.length > 0" class="fop-drift-hints">
              <div v-for="f in p.drift_flags" :key="f" class="fop-drift-hint">
                <div class="fop-drift-hint-head">
                  <span class="fop-pill fop-pill--red">{{ f }}</span>
                  <span class="fop-drift-hint-label">{{ DRIFT_LABELS[f] || f }}</span>
                </div>
                <template v-if="DRIFT_HINTS[f]">
                  <div class="fop-drift-hint-row">
                    <span class="fop-drift-hint-key">Cause</span>
                    <span class="fop-drift-hint-val">{{ DRIFT_HINTS[f].cause }}</span>
                  </div>
                  <div class="fop-drift-hint-row">
                    <span class="fop-drift-hint-key">Remediation</span>
                    <span class="fop-drift-hint-val">{{ DRIFT_HINTS[f].remediation }}</span>
                  </div>
                  <div v-if="DRIFT_HINTS[f].cli" class="fop-drift-hint-row">
                    <span class="fop-drift-hint-key">CLI</span>
                    <span class="fop-drift-hint-val">
                      <code>{{ DRIFT_HINTS[f].cli }}</code>
                      <button class="fop-icon-btn" @click.stop="copyText(DRIFT_HINTS[f].cli!)" title="Copy">⎘</button>
                    </span>
                  </div>
                  <div v-if="DRIFT_HINTS[f].autoHeal" class="fop-drift-hint-row">
                    <span class="fop-drift-hint-key">Auto-heal</span>
                    <span class="fop-drift-hint-val">{{ DRIFT_HINTS[f].autoHeal }}</span>
                  </div>
                </template>
              </div>
            </div>

            <!-- Identity / connectivity -->
            <div class="fop-detail-section-head">Identity &amp; Connectivity</div>
            <div class="fop-detail-grid">
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Base URL</span>
                <span class="fop-detail-val">
                  <code>{{ p.base_url }}</code>
                  <button class="fop-icon-btn" @click.stop="copyText(p.base_url)" title="Copy">⎘</button>
                </span>
              </div>
              <div v-if="p.trust_domain" class="fop-detail-pair">
                <span class="fop-detail-key">Trust domain</span>
                <span class="fop-detail-val"><code>{{ p.trust_domain }}</code></span>
              </div>
              <div v-if="p.operator_did" class="fop-detail-pair">
                <span class="fop-detail-key">Operator DID</span>
                <span class="fop-detail-val">
                  <code>{{ p.operator_did }}</code>
                  <button class="fop-icon-btn" @click.stop="goToEventStore(p.operator_did!)" title="Open in EventStore">⤴</button>
                </span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Hop distance</span>
                <span class="fop-detail-val">{{ p.hop_distance ?? '—' }} {{ p.hop_distance === 0 ? '(direct)' : '' }}</span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">BFS-reachable</span>
                <span class="fop-detail-val" :class="p.bfs_reachable === false ? 'fop-detail-val--warn' : ''">{{ p.bfs_reachable === false ? 'NO' : 'yes' }}</span>
              </div>
              <div v-if="p.parent_registry_id" class="fop-detail-pair">
                <span class="fop-detail-key">Parent registry</span>
                <span class="fop-detail-val">id={{ p.parent_registry_id }}</span>
              </div>
              <div v-if="p.peer_type === 'frame'" class="fop-detail-pair">
                <span class="fop-detail-key">SPIRE bundle</span>
                <span class="fop-detail-val" :class="p.spire_bundle_active === false ? 'fop-detail-val--warn' : ''">{{ p.spire_bundle_active === false ? 'INACTIVE' : 'active' }}</span>
              </div>
            </div>

            <!-- Lifecycle -->
            <div class="fop-detail-section-head">Lifecycle</div>
            <div class="fop-detail-grid">
              <div v-if="p.registered_at" class="fop-detail-pair">
                <span class="fop-detail-key">Registered</span>
                <span class="fop-detail-val">{{ formatAbs(p.registered_at) }}</span>
              </div>
              <div v-if="p.approved_at" class="fop-detail-pair">
                <span class="fop-detail-key">Approved</span>
                <span class="fop-detail-val">{{ formatAbs(p.approved_at) }}</span>
              </div>
              <div v-if="p.discovered_at" class="fop-detail-pair">
                <span class="fop-detail-key">Discovered</span>
                <span class="fop-detail-val">{{ formatAbs(p.discovered_at) }}</span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Last sync</span>
                <span class="fop-detail-val">{{ formatAbs(p.last_synced_at) }}</span>
              </div>
              <div v-if="p.last_seen_in_topology_at" class="fop-detail-pair">
                <span class="fop-detail-key">Last seen in topology</span>
                <span class="fop-detail-val">{{ formatAbs(p.last_seen_in_topology_at) }}</span>
              </div>
              <div v-if="p.last_health_check_attempt_at" class="fop-detail-pair">
                <span class="fop-detail-key">Last health check</span>
                <span class="fop-detail-val">{{ formatAbs(p.last_health_check_attempt_at) }}</span>
              </div>
              <div v-if="p.last_interaction_at" class="fop-detail-pair">
                <span class="fop-detail-key">Last interaction</span>
                <span class="fop-detail-val">{{ formatAbs(p.last_interaction_at) }}</span>
              </div>
            </div>

            <!-- License -->
            <div v-if="p.license_id || p.license_status" class="fop-detail-section-head">License</div>
            <div v-if="p.license_id || p.license_status" class="fop-detail-grid">
              <div v-if="p.license_status" class="fop-detail-pair">
                <span class="fop-detail-key">Status</span>
                <span class="fop-detail-val" :class="licenseValClass(p.license_status)">{{ p.license_status }}</span>
              </div>
              <div v-if="p.license_id" class="fop-detail-pair">
                <span class="fop-detail-key">License ID</span>
                <span class="fop-detail-val">
                  <code>{{ p.license_id }}</code>
                  <button class="fop-icon-btn" @click.stop="copyText(p.license_id!)" title="Copy">⎘</button>
                </span>
              </div>
              <div v-if="p.license_key_prefix" class="fop-detail-pair">
                <span class="fop-detail-key">Key prefix</span>
                <span class="fop-detail-val"><code>{{ p.license_key_prefix }}…</code></span>
              </div>
              <div v-if="p.federation_tier" class="fop-detail-pair">
                <span class="fop-detail-key">Federation tier</span>
                <span class="fop-detail-val">{{ p.federation_tier }}</span>
              </div>
              <div v-if="p.license_suspended_at" class="fop-detail-pair">
                <span class="fop-detail-key">Suspended at</span>
                <span class="fop-detail-val fop-detail-val--warn">{{ formatAbs(p.license_suspended_at) }}</span>
              </div>
              <div v-if="p.license_suspended_reason" class="fop-detail-pair">
                <span class="fop-detail-key">Suspended reason</span>
                <span class="fop-detail-val">{{ p.license_suspended_reason }}</span>
              </div>
              <div v-if="p.license_revoked_at" class="fop-detail-pair">
                <span class="fop-detail-key">Revoked at</span>
                <span class="fop-detail-val fop-detail-val--err">{{ formatAbs(p.license_revoked_at) }}</span>
              </div>
              <div v-if="p.license_revoked_reason" class="fop-detail-pair">
                <span class="fop-detail-key">Revoked reason</span>
                <span class="fop-detail-val">{{ p.license_revoked_reason }}</span>
              </div>
            </div>

            <!-- Cloud hosting -->
            <div v-if="p.cloud_hosted" class="fop-detail-section-head">Cloud Hosting</div>
            <div v-if="p.cloud_hosted" class="fop-detail-grid">
              <div v-if="p.cloud_url" class="fop-detail-pair">
                <span class="fop-detail-key">Cloud URL</span>
                <span class="fop-detail-val"><code>{{ p.cloud_url }}</code></span>
              </div>
              <div v-if="p.cloud_provisioned_at" class="fop-detail-pair">
                <span class="fop-detail-key">Provisioned</span>
                <span class="fop-detail-val">{{ formatAbs(p.cloud_provisioned_at) }}</span>
              </div>
              <div v-if="p.cloud_torn_down_at" class="fop-detail-pair">
                <span class="fop-detail-key">Torn down</span>
                <span class="fop-detail-val fop-detail-val--warn">{{ formatAbs(p.cloud_torn_down_at) }}</span>
              </div>
            </div>

            <!-- Trust + interactions -->
            <div class="fop-detail-section-head">Trust &amp; Interactions</div>
            <div class="fop-detail-grid">
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Healthy</span>
                <span class="fop-detail-val" :class="p.healthy === false ? 'fop-detail-val--warn' : ''">{{ p.healthy === false ? 'NO' : 'yes' }}</span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Health failures</span>
                <span class="fop-detail-val" :class="(p.health_check_failure_count || 0) > 0 ? 'fop-detail-val--warn' : ''">{{ p.health_check_failure_count || 0 }}</span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Total interactions</span>
                <span class="fop-detail-val">{{ (p.total_interactions || 0).toLocaleString(appLocale()) }}</span>
              </div>
              <div class="fop-detail-pair">
                <span class="fop-detail-key">Disputes lost</span>
                <span class="fop-detail-val" :class="(p.disputes_lost_with || 0) > 0 ? 'fop-detail-val--warn' : ''">{{ p.disputes_lost_with || 0 }}</span>
              </div>
              <div v-if="p.bayesian_discount !== null && p.bayesian_discount !== undefined" class="fop-detail-pair">
                <span class="fop-detail-key">Bayesian discount</span>
                <span class="fop-detail-val">{{ p.bayesian_discount.toFixed(4) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="fop-footer">
        <code>/admin/federation/topology-overview</code>
        <span> · admin_federation gated · {{ allPeers.length }} peers across 4 tiers</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
/**
 * FederationOperationsPanel — body-only operations panel for Federation.vue.
 *
 * 2026-05-08 polish round 3 (commander): merged the standalone
 * AdminPeers.vue body content into a panel component so it can mount
 * inside Federation.vue as the third tab (Operations) without duplicating
 * the hero/ambient. Existing Tiers + Network tabs untouched.
 *
 * Pulls from the same /admin/federation/topology-overview endpoint that
 * the Tiers tab uses, but presents it through an admin-operational lens
 * (drift remediation hints, license state breakdown, BFS reachability,
 * SPIRE bundle status, sort-by-attention-required).
 */
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import {
  peersAdminService,
  DRIFT_LABELS,
  DRIFT_HINTS,
  type TopologyOverview,
  type FederationPeerRow,
  type TopologySummary,
} from '@/services/api/peersAdmin'
import { downloadCsv, csvFilenameTimestamp, type CsvColumn } from '@/components/common/csvExport'

const uiStore = useUIStore()
const router = useRouter()

type TierKey = 'all' | 'frame' | 'direct_peer' | 'discovered' | 'cloud_operator'

const TIER_FILTERS: { value: TierKey; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'frame', label: 'Frames' },
  { value: 'direct_peer', label: 'Direct' },
  { value: 'cloud_operator', label: 'Cloud ops' },
  { value: 'discovered', label: 'Discovered' },
]

const data = ref<TopologyOverview | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const lastRefreshAt = ref('')
const tierFilter = ref<TierKey>('all')
const search = ref('')
const autoRefresh = ref(true)
const expandedId = ref<number | null>(null)

const peerRefs = new Map<number, HTMLElement>()
function registerPeerRef(id: number, el: HTMLElement | null) {
  if (el) peerRefs.set(id, el)
  else peerRefs.delete(id)
}

let pollHandle: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  void refresh()
  pollHandle = setInterval(() => {
    if (!autoRefresh.value) return
    if (document.visibilityState === 'hidden') return
    void refresh()
  }, 60_000)
})
onBeforeUnmount(() => { if (pollHandle) clearInterval(pollHandle) })

async function refresh() {
  loading.value = true
  error.value = null
  try {
    data.value = await peersAdminService.topologyOverview()
    lastRefreshAt.value = formatHHMMSS(new Date())
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load topology'
    uiStore.showError?.('Operations', error.value!)
  } finally {
    loading.value = false
  }
}

function setTier(t: TierKey) {
  if (tierFilter.value === t) return
  tierFilter.value = t
}
function resetFilters() {
  tierFilter.value = 'all'
  search.value = ''
}
function toggleExpand(id: number) {
  expandedId.value = expandedId.value === id ? null : id
}
function scrollToPeer(id: number) {
  setTimeout(() => {
    const el = peerRefs.get(id)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, 100)
}

const summary = computed<TopologySummary>(() => data.value?.summary ?? {
  total_peers: 0,
  peers_by_type: {},
  license_status_breakdown: {},
  drift_count: 0,
  oldest_discovered_at: null,
  healthy_count: 0,
})

const allPeers = computed<FederationPeerRow[]>(() => {
  if (!data.value) return []
  const byId = new Map<number, FederationPeerRow>()
  ;[
    ...(data.value.frames || []),
    ...(data.value.direct_peers || []),
    ...(data.value.cloud_operators || []),
    ...(data.value.discovered || []),
  ].forEach(p => {
    if (!byId.has(p.id)) byId.set(p.id, p)
  })
  return Array.from(byId.values())
})

function tierCount(t: TierKey): number {
  if (!data.value) return 0
  if (t === 'frame') return (data.value.frames || []).length
  if (t === 'direct_peer') return (data.value.direct_peers || []).length
  if (t === 'cloud_operator') return (data.value.cloud_operators || []).length
  if (t === 'discovered') return (data.value.discovered || []).length
  return allPeers.value.length
}

const filteredPeers = computed<FederationPeerRow[]>(() => {
  let pool: FederationPeerRow[]
  if (!data.value) return []
  if (tierFilter.value === 'frame') pool = data.value.frames || []
  else if (tierFilter.value === 'direct_peer') pool = data.value.direct_peers || []
  else if (tierFilter.value === 'cloud_operator') pool = data.value.cloud_operators || []
  else if (tierFilter.value === 'discovered') pool = data.value.discovered || []
  else pool = allPeers.value

  const sorted = [...pool].sort((a, b) => {
    const aDrift = a.has_drift ? 1 : 0
    const bDrift = b.has_drift ? 1 : 0
    if (aDrift !== bDrift) return bDrift - aDrift
    const aHealthy = a.healthy === false ? 1 : 0
    const bHealthy = b.healthy === false ? 1 : 0
    if (aHealthy !== bHealthy) return bHealthy - aHealthy
    return (a.name || '').localeCompare(b.name || '')
  })

  const q = search.value.trim().toLowerCase()
  if (!q) return sorted
  return sorted.filter(p => {
    if (p.name.toLowerCase().includes(q)) return true
    if (p.base_url.toLowerCase().includes(q)) return true
    if ((p.trust_domain || '').toLowerCase().includes(q)) return true
    if ((p.operator_did || '').toLowerCase().includes(q)) return true
    return false
  })
})

const driftedPeers = computed(() => allPeers.value.filter(p => p.has_drift))
const unhealthyCount = computed(() => allPeers.value.filter(p => p.healthy === false || (p.health_check_failure_count || 0) > 0).length)
const bfsUnreachableCount = computed(() => allPeers.value.filter(p => p.bfs_reachable === false).length)

function exportCsv() {
  if (!filteredPeers.value.length) return
  const cols: CsvColumn<FederationPeerRow>[] = [
    { label: 'ID', value: r => r.id },
    { label: 'Name', value: r => r.name },
    { label: 'Status', value: r => r.status },
    { label: 'Peer type', value: r => r.peer_type },
    { label: 'Hop distance', value: r => r.hop_distance },
    { label: 'BFS-reachable', value: r => r.bfs_reachable === false ? 'no' : 'yes' },
    { label: 'Trust domain', value: r => r.trust_domain },
    { label: 'Base URL', value: r => r.base_url },
    { label: 'Operator DID', value: r => r.operator_did },
    { label: 'License status', value: r => r.license_status },
    { label: 'Federation tier', value: r => r.federation_tier },
    { label: 'Cloud hosted', value: r => r.cloud_hosted },
    { label: 'Healthy', value: r => r.healthy === false ? 'no' : 'yes' },
    { label: 'Health failures', value: r => r.health_check_failure_count },
    { label: 'Total interactions', value: r => r.total_interactions },
    { label: 'Disputes lost', value: r => r.disputes_lost_with },
    { label: 'Bayesian discount', value: r => r.bayesian_discount },
    { label: 'Has drift', value: r => r.has_drift },
    { label: 'Drift flags', value: r => (r.drift_flags || []).join(';') },
    { label: 'Last sync', value: r => r.last_synced_at },
    { label: 'Last seen in topology', value: r => r.last_seen_in_topology_at },
  ]
  downloadCsv(filteredPeers.value, cols, `federation-operations-${csvFilenameTimestamp()}`)
  uiStore.showSuccess?.('Exported', `${filteredPeers.value.length} rows`)
}

// ── Helpers ──
function formatHHMMSS(iso: string | Date | null | undefined): string {
  if (!iso) return '—'
  const dt = typeof iso === 'string' ? new Date(iso) : iso
  return dt.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
function formatAbs(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}
function formatRel(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const now = Date.now()
  const diffSec = Math.floor((now - then) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

function tierLabel(peerType: string): string {
  const t = (peerType || '').toLowerCase()
  if (t === 'frame') return 'frame'
  if (t === 'direct_peer') return 'direct'
  if (t === 'cloud_operator') return 'cloud-op'
  if (t === 'discovered') return 'discovered'
  return peerType || 'unknown'
}
function tierPillClass(peerType: string): string {
  const t = (peerType || '').toLowerCase()
  if (t === 'frame') return 'fop-pill--violet'
  if (t === 'direct_peer') return 'fop-pill--green'
  if (t === 'cloud_operator') return 'fop-pill--cyan'
  if (t === 'discovered') return 'fop-pill--muted'
  return 'fop-pill--muted'
}
function statusPillClass(status: string): string {
  const s = (status || '').toUpperCase()
  if (s === 'ACTIVE') return 'fop-status-pill--green'
  if (s === 'PENDING_APPROVAL') return 'fop-status-pill--warn'
  if (s === 'INACTIVE' || s === 'REJECTED') return 'fop-status-pill--red'
  return 'fop-status-pill--muted'
}
function trustPillClass(discount: number): string {
  if (discount >= 0.9) return 'fop-pill--green'
  if (discount >= 0.5) return 'fop-pill--warn'
  return 'fop-pill--red'
}
function licenseValClass(status: string): string {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'fop-detail-val--ok'
  if (s === 'suspended') return 'fop-detail-val--warn'
  if (s === 'revoked') return 'fop-detail-val--err'
  return ''
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
.fop {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  display: flex; flex-direction: column; gap: 1.25rem;
  margin-top: 1rem;
}

.fop-toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 0.8rem;
  padding: 0.6rem 0.85rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 6px;
}
.fop-toolbar-group { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.fop-toolbar-spacer { flex: 1; }
.fop-toolbar-meta { margin-left: 0.3rem; }
.fop-toolbar-label { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(255, 255, 255, 0.45); text-transform: uppercase; }
.fop-toolbar-val { font-family: var(--mono); font-size: 0.78rem; font-weight: 700; color: var(--cyan); }

.fop-search {
  flex: 0 1 260px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: rgba(255, 255, 255, 0.9);
  border-radius: 4px;
  font-family: var(--mono); font-size: 0.7rem;
  padding: 5px 10px; outline: none;
}
.fop-search:focus { border-color: rgba(var(--cyan-rgb), 0.55); }

.fop-chip-btn {
  font-family: var(--mono); font-size: 0.6rem; font-weight: 600;
  letter-spacing: 0.06em;
  background: transparent; color: rgba(255, 255, 255, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 4px; padding: 3px 9px; cursor: pointer;
  transition: all 0.15s; text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 0.4rem;
}
.fop-chip-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.06); color: rgba(255, 255, 255, 0.9); }
.fop-chip-btn--active {
  background: rgba(var(--cyan-rgb), 0.18);
  color: rgba(var(--cyan-rgb), 1);
  border-color: rgba(var(--cyan-rgb), 0.5);
}
.fop-chip-count {
  background: rgba(var(--cyan-rgb), 0.15);
  border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 8px;
  padding: 0 5px;
  font-size: 0.55rem;
  color: var(--cyan);
  font-weight: 700;
}

.fop-toggle { display: inline-flex; align-items: center; gap: 0.4rem; cursor: pointer; font-family: var(--mono); font-size: 0.65rem; color: rgba(255, 255, 255, 0.7); }
.fop-toggle input { display: none; }
.fop-toggle-track { width: 26px; height: 14px; background: rgba(255, 255, 255, 0.1); border-radius: 7px; position: relative; transition: background 0.15s; }
.fop-toggle-knob { position: absolute; top: 2px; left: 2px; width: 10px; height: 10px; background: rgba(255, 255, 255, 0.6); border-radius: 50%; transition: transform 0.15s, background 0.15s; }
.fop-toggle input:checked ~ .fop-toggle-track { background: rgba(var(--cyan-rgb), 0.3); }
.fop-toggle input:checked ~ .fop-toggle-track .fop-toggle-knob { transform: translateX(12px); background: var(--cyan); }

.fop-btn { display: inline-flex; align-items: center; gap: 0.35rem; font-family: var(--mono); font-size: 0.65rem; letter-spacing: 0.08em; font-weight: 600; padding: 4px 10px; border-radius: 4px; border: 1px solid transparent; cursor: pointer; transition: all 0.15s; }
.fop-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.fop-btn--ghost { background: transparent; border-color: rgba(var(--cyan-rgb), 0.25); color: rgba(var(--cyan-rgb), 0.85); }
.fop-btn--ghost:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.08); border-color: rgba(var(--cyan-rgb), 0.5); color: rgba(var(--cyan-rgb), 1); }

.fop-center { text-align: center; padding: 5rem 1rem; background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(var(--cyan-rgb), 0.12); border-radius: 6px; }
.fop-spinner { width: 36px; height: 36px; border: 2.5px solid rgba(var(--cyan-rgb), 0.2); border-top-color: rgba(var(--cyan-rgb), 0.95); border-radius: 50%; animation: fop-spin 0.8s linear infinite; margin: 0 auto 0.8rem; }
@keyframes fop-spin { to { transform: rotate(360deg); } }
.fop-loading-text { font-family: var(--mono); font-size: 0.75rem; color: rgba(255, 255, 255, 0.5); letter-spacing: 0.1em; text-transform: uppercase; }
.fop-error-text { font-family: var(--mono); font-size: 0.85rem; color: var(--nc-danger); }

.fop-stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
.fop-stat-card {
  background: linear-gradient(180deg, rgba(10, 13, 22, 0.85), rgba(6, 8, 16, 0.85));
  border: 1px solid rgba(var(--cyan-rgb), 0.18);
  border-radius: 8px;
  padding: 1.05rem 1.1rem;
  display: flex; flex-direction: column; gap: 0.4rem;
}
.fop-stat-key { font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.14em; font-weight: 700; color: var(--cyan); text-transform: uppercase; }
.fop-stat-val { font-family: var(--mono); font-size: 1.7rem; font-weight: 700; letter-spacing: -0.02em; line-height: 1.05; }
.fop-stat-val--cyan { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.4); }
.fop-stat-val--green { color: var(--nc-success, #00ff88); text-shadow: 0 0 14px rgba(0, 255, 136, 0.35); }
.fop-stat-val--red { color: var(--nc-danger, #ff3366); text-shadow: 0 0 14px rgba(255, 51, 102, 0.45); }
.fop-stat-val--warn { color: var(--nc-warning, #ff9500); text-shadow: 0 0 14px rgba(255, 149, 0, 0.4); }
.fop-stat-sub { font-family: var(--mono); font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; }
.fop-stat-sub-grid { display: flex; gap: 0.3rem; flex-wrap: wrap; }

.fop-pill { display: inline-block; font-family: var(--mono); font-size: 0.55rem; font-weight: 700; letter-spacing: 0.06em; padding: 1px 6px; border-radius: 3px; border: 1px solid transparent; }
.fop-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.fop-pill--cyan { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.3); }
.fop-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.fop-pill--violet { background: rgba(168, 85, 247, 0.1); color: #c084fc; border-color: rgba(168, 85, 247, 0.3); }
.fop-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.fop-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

.fop-drift-banner {
  background: rgba(255, 51, 102, 0.08);
  border: 1px solid rgba(255, 51, 102, 0.35);
  border-radius: 8px;
  padding: 0.75rem 1rem;
  display: flex; flex-direction: column; gap: 0.5rem;
}
.fop-drift-head { display: flex; align-items: center; gap: 0.5rem; font-family: var(--mono); font-size: 0.75rem; font-weight: 700; color: var(--nc-danger, #ff3366); }
.fop-drift-icon { font-size: 1rem; }
.fop-drift-list { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.fop-drift-item {
  display: inline-flex; align-items: center; gap: 0.4rem;
  background: rgba(255, 51, 102, 0.06);
  border: 1px solid rgba(255, 51, 102, 0.25);
  border-radius: 4px;
  padding: 4px 9px;
  cursor: pointer;
  font-family: var(--mono); font-size: 0.65rem;
  color: rgba(255, 255, 255, 0.85);
  transition: all 0.15s;
}
.fop-drift-item:hover { background: rgba(255, 51, 102, 0.12); border-color: rgba(255, 51, 102, 0.45); }
.fop-drift-flags { display: inline-flex; gap: 0.25rem; flex-wrap: wrap; }

.fop-empty {
  text-align: center;
  padding: 3rem 1rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 6px;
  display: flex; flex-direction: column;
  align-items: center; gap: 0.6rem;
}
.fop-empty-glyph { font-size: 2rem; color: rgba(var(--cyan-rgb), 0.4); font-family: var(--mono); }
.fop-empty-title { font-family: var(--mono); font-size: 0.85rem; color: rgba(255, 255, 255, 0.7); margin: 0; }

.fop-feed-list { display: flex; flex-direction: column; gap: 0.35rem; }
.fop-feed-row {
  background: rgba(10, 13, 22, 0.7);
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
  overflow: hidden;
}
.fop-feed-row:hover { background: rgba(var(--cyan-rgb), 0.04); border-color: rgba(var(--cyan-rgb), 0.25); }
.fop-feed-row--expanded { background: rgba(var(--cyan-rgb), 0.06); border-color: rgba(var(--cyan-rgb), 0.4); }
.fop-feed-row--unhealthy { border-left: 3px solid rgba(255, 149, 0, 0.6); }
.fop-feed-row--drifted { border-left: 3px solid rgba(255, 51, 102, 0.7); background: rgba(255, 51, 102, 0.03); }

.fop-feed-head {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 0.85rem;
  flex-wrap: wrap;
  font-family: var(--mono);
}
.fop-feed-id { font-size: 0.65rem; color: rgba(255, 255, 255, 0.5); font-weight: 700; }
.fop-feed-name { font-size: 0.8rem; font-weight: 700; color: rgba(255, 255, 255, 0.9); }
.fop-feed-domain { font-size: 0.62rem; color: rgba(99, 102, 241, 0.85); background: rgba(99, 102, 241, 0.06); padding: 1px 5px; border-radius: 3px; border: 1px solid rgba(99, 102, 241, 0.2); }
.fop-feed-meta { font-size: 0.6rem; color: rgba(255, 255, 255, 0.55); }
.fop-feed-meta strong { color: rgba(255, 255, 255, 0.85); font-weight: 600; }
.fop-feed-spacer { flex: 1; }
.fop-feed-caret { font-size: 0.7rem; color: rgba(var(--cyan-rgb), 0.6); }

.fop-status-pill { font-family: var(--mono); font-size: 0.55rem; font-weight: 700; letter-spacing: 0.06em; padding: 1px 6px; border-radius: 3px; border: 1px solid transparent; }
.fop-status-pill--green { background: rgba(0, 255, 136, 0.1); color: var(--nc-success, #00ff88); border-color: rgba(0, 255, 136, 0.3); }
.fop-status-pill--warn { background: rgba(255, 149, 0, 0.1); color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.3); }
.fop-status-pill--red { background: rgba(255, 51, 102, 0.1); color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.3); }
.fop-status-pill--muted { background: rgba(255, 255, 255, 0.05); color: rgba(255, 255, 255, 0.55); border-color: rgba(255, 255, 255, 0.15); }

.fop-feed-detail {
  padding: 0.8rem 0.85rem 0.9rem;
  border-top: 1px solid rgba(var(--cyan-rgb), 0.12);
  display: flex; flex-direction: column; gap: 0.85rem;
  cursor: default;
}

.fop-drift-hints {
  display: flex; flex-direction: column; gap: 0.6rem;
  padding: 0.75rem 0.85rem;
  background: rgba(255, 51, 102, 0.05);
  border: 1px solid rgba(255, 51, 102, 0.25);
  border-radius: 6px;
}
.fop-drift-hint { display: flex; flex-direction: column; gap: 0.35rem; }
.fop-drift-hint-head { display: flex; align-items: center; gap: 0.5rem; }
.fop-drift-hint-label { font-family: var(--mono); font-size: 0.7rem; color: rgba(255, 255, 255, 0.85); font-weight: 600; }
.fop-drift-hint-row { display: flex; gap: 0.5rem; align-items: flex-start; padding-left: 0.4rem; }
.fop-drift-hint-key { font-family: var(--mono); font-size: 0.55rem; letter-spacing: 0.1em; color: rgba(255, 255, 255, 0.45); text-transform: uppercase; font-weight: 600; min-width: 6rem; }
.fop-drift-hint-val { font-family: var(--mono); font-size: 0.7rem; color: rgba(255, 255, 255, 0.85); flex: 1; display: flex; align-items: center; gap: 0.35rem; }
.fop-drift-hint-val code { background: rgba(0, 0, 0, 0.4); padding: 1px 5px; border-radius: 3px; font-size: 0.65rem; color: rgba(255, 255, 255, 0.9); }

.fop-detail-section-head {
  font-family: var(--mono); font-size: 0.6rem;
  letter-spacing: 0.16em; font-weight: 700;
  color: rgba(var(--cyan-rgb), 0.85);
  text-transform: uppercase;
  padding-bottom: 0.2rem;
  border-bottom: 1px solid rgba(var(--cyan-rgb), 0.15);
  margin-top: 0.4rem;
}
.fop-detail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.5rem 0.85rem; }
.fop-detail-pair { display: flex; flex-direction: column; gap: 0.15rem; }
.fop-detail-key { font-family: var(--mono); font-size: 0.55rem; letter-spacing: 0.12em; color: rgba(255, 255, 255, 0.4); text-transform: uppercase; font-weight: 600; }
.fop-detail-val { font-family: var(--mono); font-size: 0.7rem; color: rgba(255, 255, 255, 0.85); display: flex; align-items: center; gap: 0.35rem; }
.fop-detail-val--ok { color: var(--nc-success, #00ff88); }
.fop-detail-val--warn { color: var(--nc-warning, #ff9500); }
.fop-detail-val--err { color: var(--nc-danger, #ff3366); }
.fop-detail-val code { background: rgba(var(--cyan-rgb), 0.06); padding: 1px 5px; border-radius: 3px; word-break: break-all; font-size: 0.65rem; }
.fop-icon-btn {
  background: transparent;
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  border-radius: 3px;
  color: rgba(var(--cyan-rgb), 0.7);
  font-family: monospace; font-size: 0.7rem;
  padding: 0 5px; cursor: pointer;
  transition: all 0.12s;
}
.fop-icon-btn:hover { background: rgba(var(--cyan-rgb), 0.1); color: rgba(var(--cyan-rgb), 1); border-color: rgba(var(--cyan-rgb), 0.5); }

.fop-footer { font-family: var(--mono); font-size: 0.65rem; color: rgba(255, 255, 255, 0.5); padding-top: 0.5rem; border-top: 1px solid rgba(var(--cyan-rgb), 0.08); }
.fop-footer code { background: rgba(var(--cyan-rgb), 0.08); color: var(--cyan); padding: 1px 5px; border-radius: 3px; }

@media (max-width: 1100px) { .fop-stats { grid-template-columns: 1fr 1fr; } }
@media (max-width: 768px) {
  .fop-stats { grid-template-columns: 1fr; }
  .fop-search { flex: 1 1 100%; }
}
</style>
