<!--
  §pass62 (2026-05-21) — Shared Peer Detail Drawer.

  Single source of truth for the 6-tab peer detail surface used by
  Federation.vue (Network tab) and FederationDiscovery.vue. Supports
  Local Registry pseudo-peer (peer.id === 0) by routing data fetches
  to the new /admin/registry-stats + /admin/operator-lifecycle +
  /admin/federation/local-events endpoints instead of the per-peer
  variants.

  Tabs:
    overview      — identity / status / hop / trust domain / operator DID
    trust         — ETag, signature, bayesian discount, total interactions
    economics     — fees (intra/cross/payout) + fee_collector address
    lifecycle     — APPLICATION / LICENSE / PEER / CLOUD / SPIRE
    agents        — count (link out to /admin/agents)
    events        — recent federation events for the peer / self
-->
<template>
  <Teleport to="body">
    <div v-if="open" class="pdd-overlay" @click.self="onClose" role="dialog" aria-modal="true" aria-labelledby="pdd-title">
      <aside class="pdd-drawer">
        <header class="pdd-head">
          <div class="pdd-head-left">
            <div class="pdd-orb-wrap">
              <PeerOrb v-if="peer" :peer="peer" :radius="20" :is-local="isLocal" :tier="peer.peer_type || 'frame'" />
            </div>
            <div>
              <div class="pdd-label">
                {{ peer?.peer_type === 'local' || isLocal ? 'LOCAL REGISTRY' : tierLabel(peer?.peer_type || '') }}
                <span v-if="!isLocal && peer?.id"> · ID {{ peer.id }}</span>
                <span v-else-if="isLocal && stats?.is_central_registry"> · CENTRAL</span>
              </div>
              <h2 class="pdd-title" id="pdd-title">{{ peer?.name }}</h2>
              <div class="pdd-sub">{{ peer?.base_url || (isLocal ? '— this registry —' : '') }}</div>
            </div>
          </div>
          <button class="pdd-close" aria-label="Close peer detail drawer" @click="onClose">
            <Icon name="mdi:close" :size="18" aria-hidden="true" />
          </button>
        </header>

        <nav class="pdd-tabs" aria-label="Peer detail sections" role="tablist">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            class="pdd-tab"
            :class="{ 'pdd-tab--active': activeTab === tab.key }"
            role="tab"
            :aria-selected="activeTab === tab.key"
            @click="activeTab = tab.key"
          >
            <Icon :name="tab.icon" :size="13" aria-hidden="true" />
            <span>{{ tab.label }}</span>
          </button>
        </nav>

        <div class="pdd-body">
          <!-- Loading -->
          <div v-if="!peer" class="pdd-center"><div class="pdd-spinner"></div></div>

          <!-- ── Overview ── -->
          <section v-else-if="activeTab === 'overview'" class="pdd-pane">
            <div class="pdd-overview-grid">
              <div class="pdd-overview-id">
                <h3 class="pdd-section-h">Identity</h3>
                <dl class="pdd-kv">
                  <dt>Name</dt><dd>{{ peer.name }}</dd>
                  <dt>Base URL</dt><dd class="pdd-mono">{{ peer.base_url || '—' }}</dd>
                  <dt v-if="peer.trust_domain">Trust domain</dt>
                  <dd v-if="peer.trust_domain" class="pdd-mono">{{ peer.trust_domain }}</dd>
                  <dt v-if="peer.operator_did">Operator DID</dt>
                  <dd v-if="peer.operator_did" class="pdd-mono">{{ peer.operator_did }}</dd>
                  <dt v-if="peer.federation_tier">Federation tier</dt>
                  <dd v-if="peer.federation_tier">{{ peer.federation_tier }}</dd>
                  <dt>Hop distance</dt>
                  <!-- §pass62.6 — tree-walk derived hop when peersById available -->
                  <dd :title="effectiveChain()">{{ effectiveHop() }}</dd>
                  <dt v-if="peer.parent_name">Parent</dt>
                  <dd v-if="peer.parent_name">{{ peer.parent_name }}</dd>
                </dl>
              </div>
              <div class="pdd-overview-state">
                <h3 class="pdd-section-h">Status</h3>
                <dl class="pdd-kv">
                  <dt>Status</dt>
                  <dd>
                    <span class="pdd-pill" :class="statusClass(peer.status)">{{ peer.status }}</span>
                  </dd>
                  <dt v-if="!isLocal">Last synced</dt>
                  <dd v-if="!isLocal">{{ timeAgo(peer.last_synced_at) }}</dd>
                  <dt v-if="!isLocal">Registered</dt>
                  <dd v-if="!isLocal">{{ timeAgo(peer.registered_at) }}</dd>
                  <dt v-if="!isLocal && peer.approved_at">Approved</dt>
                  <dd v-if="!isLocal && peer.approved_at">{{ timeAgo(peer.approved_at) }}</dd>
                  <dt v-if="!isLocal && peer.discovered_at">First discovered</dt>
                  <dd v-if="!isLocal && peer.discovered_at">{{ timeAgo(peer.discovered_at) }}</dd>
                  <dt v-if="isLocal && stats">Uptime</dt>
                  <dd v-if="isLocal && stats">{{ humanizeUptime(stats.uptime_seconds) }}</dd>
                  <dt v-if="isLocal && stats">Genesis</dt>
                  <dd v-if="isLocal && stats">
                    <span class="pdd-pill" :class="stats.is_genesis ? 'pdd-pill--ok' : 'pdd-pill--muted'">
                      {{ stats.is_genesis ? 'YES (issuing authority)' : 'NO' }}
                    </span>
                  </dd>
                </dl>
              </div>
              <div v-if="isLocal && stats" class="pdd-overview-counts">
                <h3 class="pdd-section-h">Counts</h3>
                <div class="pdd-count-grid">
                  <div class="pdd-count-tile">
                    <div class="pdd-count-num">{{ stats.agent_count.toLocaleString(appLocale()) }}</div>
                    <div class="pdd-count-lbl">Agents</div>
                  </div>
                  <div class="pdd-count-tile">
                    <div class="pdd-count-num">{{ stats.agent_card_count.toLocaleString(appLocale()) }}</div>
                    <div class="pdd-count-lbl">Agent cards</div>
                  </div>
                  <div class="pdd-count-tile">
                    <div class="pdd-count-num">{{ stats.developer_count.toLocaleString(appLocale()) }}</div>
                    <div class="pdd-count-lbl">Developers</div>
                  </div>
                  <div class="pdd-count-tile">
                    <div class="pdd-count-num">{{ stats.peer_count_active }}<span class="pdd-count-sub">/{{ stats.peer_count_total }}</span></div>
                    <div class="pdd-count-lbl">Peers (active/total)</div>
                  </div>
                </div>
              </div>
              <div v-else-if="isLocal && statsFailed" class="pdd-overview-counts">
                <h3 class="pdd-section-h">Counts</h3>
                <ReadFailedNotice dense :retry="loadOverviewLocal" data-testid="pdd-stats-unread" />
              </div>
            </div>
          </section>

          <!-- ── Trust ── -->
          <section v-else-if="activeTab === 'trust'" class="pdd-pane">
            <h3 class="pdd-section-h">Cryptographic trust</h3>
            <dl class="pdd-kv">
              <dt>Card ETag</dt>
              <dd class="pdd-mono">{{ shortEtag(peer.card_etag) }}</dd>
              <dt>Signature verified</dt>
              <dd>
                <span class="pdd-pill" :class="peer.card_signature_verified ? 'pdd-pill--ok' : peer.card_signature_verified === false ? 'pdd-pill--bad' : 'pdd-pill--muted'">
                  {{ peer.card_signature_verified === true ? 'verified' : peer.card_signature_verified === false ? 'FAILED' : 'unknown' }}
                </span>
              </dd>
              <dt v-if="peer.card_signature_kid">Signing key</dt>
              <dd v-if="peer.card_signature_kid" class="pdd-mono">{{ shortEtag(peer.card_signature_kid, 28) }}</dd>
              <dt v-if="peer.card_last_pulled_at">Card last pulled</dt>
              <dd v-if="peer.card_last_pulled_at">{{ timeAgo(peer.card_last_pulled_at) }}</dd>
            </dl>

            <h3 class="pdd-section-h" style="margin-top:1.5rem">Reputation</h3>
            <dl class="pdd-kv">
              <dt>Total interactions</dt><dd>{{ peer.total_interactions ?? 0 }}</dd>
              <dt>Disputes lost</dt><dd>{{ peer.disputes_lost_with ?? 0 }}</dd>
              <dt>Bayesian discount</dt>
              <dd>
                <span class="pdd-trust-bar" :title="`${((peer.bayesian_discount ?? 1) * 100).toFixed(1)}%`">
                  <span class="pdd-trust-bar-fill" :style="{ width: `${Math.round((peer.bayesian_discount ?? 1) * 100)}%` }"></span>
                </span>
                <span class="pdd-trust-pct">{{ ((peer.bayesian_discount ?? 1) * 100).toFixed(1) }}%</span>
              </dd>
              <dt v-if="peer.last_interaction_at">Last interaction</dt>
              <dd v-if="peer.last_interaction_at">{{ timeAgo(peer.last_interaction_at) }}</dd>
            </dl>
            <p class="pdd-hint">Bayesian discount derates trust signals from peers with thin interaction history. 100% = no discount applied.</p>
          </section>

          <!-- ── Economics ── -->
          <section v-else-if="activeTab === 'economics'" class="pdd-pane">
            <h3 class="pdd-section-h">Fees (from Registry Card v0.3)</h3>
            <div v-if="peer.fees_summary || peer.fees" class="pdd-fees-grid">
              <div class="pdd-fee-tile">
                <div class="pdd-fee-lbl">Intra-registry</div>
                <div class="pdd-fee-val">{{ formatFee(getFee('intra')) }}</div>
              </div>
              <div class="pdd-fee-tile">
                <div class="pdd-fee-lbl">Cross-registry</div>
                <div class="pdd-fee-val">{{ formatFee(getFee('cross')) }}</div>
              </div>
              <div class="pdd-fee-tile">
                <div class="pdd-fee-lbl">Hosting</div>
                <div class="pdd-fee-val">{{ formatFee(getFee('hosting')) }}</div>
              </div>
              <div class="pdd-fee-tile">
                <div class="pdd-fee-lbl">Payout cut</div>
                <div class="pdd-fee-val">{{ formatFee(getFee('payout')) }}</div>
              </div>
            </div>
            <div v-else class="pdd-empty pdd-empty--inline">
              <Icon name="mdi:cash-off" :size="20" />
              <p>No fee data published in this peer's Registry Card.</p>
            </div>

            <h3 v-if="getFeeCollector()" class="pdd-section-h" style="margin-top:1.5rem">Fee collector</h3>
            <dl v-if="getFeeCollector()" class="pdd-kv">
              <dt>Address</dt>
              <dd class="pdd-mono">{{ getFeeCollector() }}</dd>
            </dl>

            <p class="pdd-hint" style="margin-top:1rem">
              Fees are sourced from the peer's <code>/.well-known/registry-card.json</code>.
              They drive cost composition at the SDK level for any agent-to-agent settlement
              routed through this registry.
            </p>
          </section>

          <!-- ── Lifecycle ── -->
          <section v-else-if="activeTab === 'lifecycle'" class="pdd-pane">
            <!-- Drift hints (peers only — local doesn't have peer-level drift) -->
            <div v-if="!isLocal && peer.has_drift" class="pdd-drift-pane" role="region" aria-label="Drift flags">
              <Icon name="mdi:alert-circle" :size="16" aria-hidden="true" />
              <div class="pdd-drift-pane-body">
                <div class="pdd-drift-pane-title">{{ (peer.drift_flags || []).length }} drift flag(s) detected</div>
                <div class="pdd-drift-list">
                  <article v-for="flag in (peer.drift_flags || [])" :key="flag" class="pdd-drift-row">
                    <Icon name="mdi:alert-triangle" :size="12" aria-hidden="true" />
                    <span class="pdd-drift-row-lbl">{{ DRIFT_LABELS[flag] || flag }}</span>
                    <code class="pdd-drift-row-flag">{{ flag }}</code>
                  </article>
                </div>
              </div>
            </div>

            <h3 class="pdd-section-h">Lifecycle stack</h3>

            <!-- LOCAL: synthesized layers from /admin/operator-lifecycle -->
            <div v-if="isLocal" class="pdd-lc-stack">
              <ReadFailedNotice v-if="!lifecycle && lifecycleFailed" dense :retry="loadLifecycleLocal" data-testid="pdd-lifecycle-unread" />
              <div v-else-if="!lifecycle" class="pdd-center"><div class="pdd-spinner"></div></div>
              <template v-else>
                <div class="pdd-lc-layer">
                  <header>
                    <span class="pdd-lc-tag">APPLICATION</span>
                    <span class="pdd-lc-status" :class="lifecycle.application?.status === 'self_hosted' ? 'pdd-pill--muted' : statusClass(lifecycle.application?.status)">
                      {{ lifecycle.application?.status }}
                    </span>
                  </header>
                  <div class="pdd-lc-body">
                    <code v-if="lifecycle.application?.id">{{ shortId(lifecycle.application.id, 12) }}</code>
                    <span v-else><em>self-hosted (no operator application record)</em></span>
                  </div>
                </div>
                <div class="pdd-lc-layer">
                  <header>
                    <span class="pdd-lc-tag">LICENSE</span>
                    <span class="pdd-lc-status" :class="lifecycle.license?.status === 'self_hosted' ? 'pdd-pill--muted' : licenseClass(lifecycle.license?.status)">
                      {{ lifecycle.license?.status }}
                    </span>
                  </header>
                  <div class="pdd-lc-body">
                    <code v-if="lifecycle.license?.id">{{ lifecycle.license.key_prefix }} · {{ shortId(lifecycle.license.id, 12) }}</code>
                    <span v-else><em>self-hosted (issuing authority by trust domain)</em></span>
                  </div>
                </div>
                <div class="pdd-lc-layer">
                  <header>
                    <span class="pdd-lc-tag">PEER REGISTRY</span>
                    <span class="pdd-lc-status pdd-pill--ok">SELF</span>
                  </header>
                  <div class="pdd-lc-body">
                    <code>peer:0 (local)</code>
                    <span>hop 0</span>
                  </div>
                </div>
                <div v-if="lifecycle.cloud_stack?.hosted" class="pdd-lc-layer">
                  <header>
                    <span class="pdd-lc-tag">CLOUD STACK</span>
                    <span class="pdd-lc-status pdd-pill--ok">{{ lifecycle.cloud_stack?.status || 'live' }}</span>
                  </header>
                  <div class="pdd-lc-body">
                    <code>{{ lifecycle.cloud_stack?.url || '—' }}</code>
                  </div>
                </div>
                <div v-if="lifecycle.spire_bundle?.active" class="pdd-lc-layer">
                  <header>
                    <span class="pdd-lc-tag">SPIRE TRUST DOMAIN</span>
                    <span class="pdd-lc-status pdd-pill--ok">active</span>
                  </header>
                  <div class="pdd-lc-body">
                    <code>{{ lifecycle.spire_bundle?.spiffe_id || `spiffe://${lifecycle.spire_bundle?.trust_domain}` }}</code>
                  </div>
                </div>
              </template>
            </div>

            <!-- PEER: pre-existing per-peer fields from topology -->
            <div v-else class="pdd-lc-stack">
              <div class="pdd-lc-layer">
                <header>
                  <span class="pdd-lc-tag">APPLICATION</span>
                  <span class="pdd-lc-status" v-if="peer.application_status">{{ peer.application_status }}</span>
                </header>
                <div class="pdd-lc-body" v-if="peer.application_id">
                  <code>{{ shortId(peer.application_id, 12) }}</code>
                  <span v-if="peer.cloud_hosted">cloud-hosted</span>
                </div>
                <div class="pdd-lc-body" v-else><em>no application record</em></div>
              </div>
              <div class="pdd-lc-layer">
                <header>
                  <span class="pdd-lc-tag">LICENSE</span>
                  <span class="pdd-lc-status" v-if="peer.license_status" :class="licenseClass(peer.license_status)">{{ peer.license_status }}</span>
                </header>
                <div class="pdd-lc-body" v-if="peer.license_id">
                  <code>{{ peer.license_key_prefix }} · {{ shortId(peer.license_id, 12) }}</code>
                  <span v-if="peer.license_suspended_reason"><Icon name="mdi:alert" /> {{ peer.license_suspended_reason }}</span>
                  <span v-if="peer.license_revoked_reason"><Icon name="mdi:close-circle" /> {{ peer.license_revoked_reason }}</span>
                </div>
                <div class="pdd-lc-body" v-else><em>no license record</em></div>
              </div>
              <div class="pdd-lc-layer">
                <header>
                  <span class="pdd-lc-tag">PEER REGISTRY</span>
                  <span class="pdd-lc-status" :class="statusClass(peer.status)">{{ peer.status }}</span>
                </header>
                <div class="pdd-lc-body">
                  <code>peer:{{ peer.id }}</code>
                  <!-- §pass62.6 — tree-walk hop -->
                  <span :title="effectiveChain()">hop {{ effectiveHop() }}</span>
                  <span v-if="peer.parent_name">via {{ peer.parent_name }}</span>
                </div>
              </div>
              <div class="pdd-lc-layer" v-if="peer.cloud_hosted">
                <header>
                  <span class="pdd-lc-tag">CLOUD STACK</span>
                  <span v-if="!peer.cloud_torn_down_at" class="pdd-lc-status pdd-pill--ok">live</span>
                  <span v-else class="pdd-lc-status pdd-pill--bad">torn down</span>
                </header>
                <div class="pdd-lc-body">
                  <code>{{ peer.cloud_url }}</code>
                  <span v-if="peer.cloud_provisioned_at">provisioned {{ timeAgo(peer.cloud_provisioned_at) }}</span>
                </div>
              </div>
              <div class="pdd-lc-layer" v-if="peer.peer_type === 'frame'">
                <header>
                  <span class="pdd-lc-tag">SPIRE TRUST BUNDLE</span>
                  <span class="pdd-lc-status" :class="peer.bfs_reachable ? 'pdd-pill--ok' : 'pdd-pill--bad'">
                    {{ peer.bfs_reachable ? 'fresh' : 'stale' }}
                  </span>
                </header>
                <div class="pdd-lc-body">
                  <code v-if="peer.trust_domain">spiffe://{{ peer.trust_domain }}</code>
                  <span v-if="peer.last_seen_in_topology_at">last seen {{ timeAgo(peer.last_seen_in_topology_at) }}</span>
                  <span v-else>never seen in topology</span>
                </div>
              </div>
            </div>
          </section>

          <!-- ── Agents ── -->
          <section v-else-if="activeTab === 'agents'" class="pdd-pane">
            <div v-if="isLocal && stats">
              <div class="pdd-agent-summary">
                <Icon name="mdi:robot" :size="36" />
                <div>
                  <div class="pdd-agent-bignum">{{ stats.agent_count.toLocaleString(appLocale()) }}</div>
                  <div class="pdd-agent-bigsub">{{ stats.agent_card_count.toLocaleString(appLocale()) }} cards · {{ stats.developer_count.toLocaleString(appLocale()) }} developers</div>
                </div>
              </div>
              <!-- §pass62.1 (2026-05-21) — Local-self CTAs use Discovery + AgentWorld,
                   admin agents removed (Admin Agents is admin-self view, semantically
                   irrelevant once we're drilling into federation peers). -->
              <a :href="`/ui#/discover?frames=${encodeURIComponent(stats.registry_name)}`" class="pdd-action-btn pdd-action-btn--primary">
                <Icon name="mdi:radar" :size="14" /> Browse {{ stats.registry_name }}'s agents in Discovery
              </a>
              <a :href="`/ui#/agentworld?focus=${encodeURIComponent(stats.registry_name)}`" class="pdd-action-btn">
                <Icon name="mdi:earth" :size="14" /> View this registry in AgentWorld
              </a>
            </div>
            <div v-else>
              <p class="pdd-hint">Agents originating from this peer registry. Discovery shows the public marketplace view filtered to this peer; AgentWorld zooms the 3D globe to this peer's orb.</p>
              <!-- §pass62.1 (2026-05-21) — link fix per audit:
                   (a) /admin/agents?peer=N removed — destination view ignores param (no peer filter, no peer-FK on Agent model)
                   (b) /discovery?registry=NAME renamed to /discover?frames=NAME — /discovery is GalacticMap, not Agent Discovery
                   (c) /agentworld?focus=NAME is the secondary CTA per Commander's call (AgentWorld preferred over Galactic Map). -->
              <a :href="`/ui#/discover?frames=${encodeURIComponent(peer.name)}`" class="pdd-action-btn pdd-action-btn--primary">
                <Icon name="mdi:radar" :size="14" /> Browse {{ peer.name }}'s agents in Discovery
              </a>
              <a :href="`/ui#/agentworld?focus=${encodeURIComponent(peer.name)}`" class="pdd-action-btn">
                <Icon name="mdi:earth" :size="14" /> View {{ peer.name }} in AgentWorld
              </a>
            </div>
          </section>

          <!-- ── Events ── -->
          <section v-else-if="activeTab === 'events'" class="pdd-pane">
            <header class="pdd-events-head">
              <h3 class="pdd-section-h" style="margin:0">{{ isLocal ? 'Local registry events' : `Events touching peer #${peer.id}` }}</h3>
              <button class="pdd-action-btn pdd-action-btn--sm" :disabled="eventsLoading" @click="loadEvents">
                <Icon :name="eventsLoading ? 'mdi:loading' : 'mdi:refresh'" :size="13" :class="{ 'pdd-spin': eventsLoading }" />
                {{ eventsLoading ? 'Loading…' : 'Refresh' }}
              </button>
            </header>
            <div v-if="eventsLoading && events.length === 0" class="pdd-center"><div class="pdd-spinner"></div></div>
            <ReadFailedNotice v-else-if="eventsFailed" dense :retry="loadEvents" data-testid="pdd-events-unread" />
            <div v-else-if="events.length === 0" class="pdd-empty pdd-empty--inline">
              <Icon name="mdi:history" :size="20" />
              <p>{{ isLocal ? 'No federation events on aggregate registry:self.' : 'No events for this peer.' }}</p>
            </div>
            <ul v-else class="pdd-event-list">
              <li v-for="e in events" :key="(e.id || e.event_id || (e.event_type + e.timestamp))" class="pdd-event">
                <span class="pdd-event-type">{{ e.event_type }}</span>
                <span class="pdd-event-when">{{ timeAgo(e.timestamp) }}</span>
                <span v-if="(e.data as any)?.reason" class="pdd-event-detail">{{ (e.data as any).reason }}</span>
                <span v-else-if="e.aggregate_id" class="pdd-event-detail">{{ e.aggregate_id }}</span>
              </li>
            </ul>
          </section>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import Icon from '@/components/Icon.vue'
import PeerOrb from '@/components/federation/PeerOrb.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { apiClient } from '@/services/api/client'
import {
  fetchRegistryStats,
  fetchOperatorLifecycle,
  fetchLocalFederationEvents,
  type RegistryStats,
  type OperatorLifecycle,
} from '@/services/api/federationLocal'
import type { FederatedPeer } from '@/composables/useFederationTopology'

dayjs.extend(relativeTime)

// ── Props / emits ───────────────────────────────────────────
interface Props {
  open: boolean
  peer: FederatedPeer | null
  // §pass62.6 (2026-05-21) — optional peers-by-id map for tree-walk hop derivation.
  // When provided, drawer renders the same chain-depth hop as the Network tab
  // (matches Commander's source-of-truth display). When omitted, falls back to
  // raw `peer.hop_distance` (preserves drawer's prior behavior).
  peersById?: Map<number, FederatedPeer>
  localName?: string
}
const props = defineProps<Props>()
const emit = defineEmits<{ (e: 'close'): void }>()

// §pass62.6 — derive tree-walk depth + chain path when peersById is provided.
// Imports `deriveDisplayHop` / `deriveChainPath` from the shared composable so
// there's a single source of truth shared with Federation.vue + FederationDiscovery.vue.
import { deriveDisplayHop, deriveChainPath } from '@/composables/useFederationTopology'
function effectiveHop(): number | string {
  if (!props.peer) return '—'
  if (isLocal.value) return '0 (self)'
  if (!props.peersById) return props.peer.hop_distance ?? '—'
  return deriveDisplayHop(props.peer, props.peersById)
}
function effectiveChain(): string {
  if (!props.peer || !props.peersById) return ''
  return deriveChainPath(props.peer, props.peersById, props.localName || 'Local').join(' → ')
}

type TabKey = 'overview' | 'trust' | 'economics' | 'lifecycle' | 'agents' | 'events'

const tabs: { key: TabKey, label: string, icon: string }[] = [
  { key: 'overview', label: 'Overview', icon: 'mdi:information-outline' },
  { key: 'trust', label: 'Trust', icon: 'mdi:shield-key' },
  { key: 'economics', label: 'Economics', icon: 'mdi:cash-multiple' },
  { key: 'lifecycle', label: 'Lifecycle', icon: 'mdi:layers-triple' },
  { key: 'agents', label: 'Agents', icon: 'mdi:robot' },
  { key: 'events', label: 'Events', icon: 'mdi:history' },
]

const activeTab = ref<TabKey>('overview')
const isLocal = computed(() => !!props.peer && (props.peer.id === 0 || props.peer.peer_type === 'local'))

// ── Local-only state (populated from new endpoints) ─────────
const stats = ref<RegistryStats | null>(null)
const lifecycle = ref<OperatorLifecycle | null>(null)

// ── Events state (used for both local + peer) ───────────────
const events = ref<any[]>([])
const eventsLoading = ref(false)
/** §FESUITE V0577: a failed events read said "No events for this peer." (the catch set the list to []) */
const eventsFailed = ref(false)

// ── Lazy load tab data on activeTab change ──────────────────
// §FESUITE V0578: this registry's own Lifecycle stack waited on a spinner for good when its read failed (it shows the
// spinner until a value arrives, and a failed read never brings one), and its Uptime, Genesis and Counts vanished. Each
// says its read failed now (Try again).
const statsFailed = ref(false)
const lifecycleFailed = ref(false)
async function loadOverviewLocal() {
  if (stats.value) return
  try { stats.value = await fetchRegistryStats(); statsFailed.value = false } catch { statsFailed.value = true }
}
async function loadLifecycleLocal() {
  if (lifecycle.value) return
  try { lifecycle.value = await fetchOperatorLifecycle(); lifecycleFailed.value = false } catch { lifecycleFailed.value = true }
}
async function loadEvents() {
  if (!props.peer) return
  eventsLoading.value = true
  try {
    if (isLocal.value) {
      const r = await fetchLocalFederationEvents(50)
      events.value = r.events || []
    } else {
      const r = await apiClient.get(`/admin/federation/topology/peers/${props.peer.id}/events`, { params: { limit: 50 } })
      events.value = r.data?.events || []
    }
    eventsFailed.value = false
  } catch {
    events.value = []
    eventsFailed.value = true
  } finally {
    eventsLoading.value = false
  }
}

watch(() => props.open, (o) => {
  if (o) {
    activeTab.value = 'overview'
    events.value = []
    eventsFailed.value = false
    if (isLocal.value) {
      loadOverviewLocal()
      loadLifecycleLocal()
    }
  }
})

watch(activeTab, async (t) => {
  if (!props.peer) return
  if (t === 'overview' && isLocal.value) await loadOverviewLocal()
  if (t === 'lifecycle' && isLocal.value) await loadLifecycleLocal()
  if (t === 'events') await loadEvents()
})

// ── Helpers ──────────────────────────────────────────────────
function onClose() { emit('close') }

function tierLabel(tier: string): string {
  return ({
    frame: 'Frame',
    direct_peer: 'Direct Peer',
    discovered: 'Discovered',
    cloud_operator: 'Cloud Operator',
    local: 'Local Registry',
  } as Record<string, string>)[tier] || tier
}

function statusClass(status: string | undefined | null): string {
  const s = (status || '').toUpperCase()
  if (s === 'ACTIVE') return 'pdd-pill--ok'
  if (s === 'INACTIVE') return 'pdd-pill--warn'
  if (s === 'PENDING_APPROVAL' || s === 'PENDING') return 'pdd-pill--pending'
  if (s === 'REJECTED' || s === 'REVOKED') return 'pdd-pill--bad'
  return 'pdd-pill--muted'
}

function licenseClass(status: string | undefined | null): string {
  const s = (status || '').toLowerCase()
  if (s === 'active') return 'pdd-pill--ok'
  if (s === 'suspended') return 'pdd-pill--warn'
  if (s === 'revoked') return 'pdd-pill--bad'
  return 'pdd-pill--muted'
}

function timeAgo(ts: string | undefined | null): string {
  if (!ts) return '—'
  try { return dayjs(ts).fromNow() } catch { return ts }
}

function shortId(id: string | number | null | undefined, n = 8): string {
  if (id == null) return '—'
  const s = String(id)
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function shortEtag(etag: string | null | undefined, max = 16): string {
  if (!etag) return '—'
  if (etag.length <= max) return etag
  return `${etag.slice(0, max)}…`
}

function humanizeUptime(s: number): string {
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`
}

function getFee(kind: 'intra' | 'cross' | 'hosting' | 'payout'): number | null {
  const f = (props.peer?.fees_summary || props.peer?.fees) as any
  if (!f) return null
  if (kind === 'intra') return (f.intra_pct ?? f.intra ?? f.fee_intra_pct ?? null)
  if (kind === 'cross') return (f.cross_pct ?? f.cross ?? f.fee_cross_pct ?? null)
  if (kind === 'hosting') return (f.hosting_pct ?? f.hosting ?? f.fee_hosting_pct ?? null)
  if (kind === 'payout') return (f.payout_pct ?? f.payout_cut ?? f.fee_payout_pct ?? null)
  return null
}

function getFeeCollector(): string | null {
  const f = (props.peer?.fees_summary || props.peer?.fees) as any
  return f?.fee_collector_address || f?.fee_collector || null
}

function formatFee(v: number | null): string {
  if (v == null) return '—'
  if (Math.abs(v) < 1) return `${(v * 100).toFixed(2)}%`
  return `${v.toFixed(2)}%`
}

// ── Drift labels (mirror Federation.vue's table) ────────────
const DRIFT_LABELS: Record<string, string> = {
  license_revoked_operator_active: 'License revoked — operator still active',
  operator_revoked_license_active: 'Operator revoked — license still active',
  peer_inactive_license_active: 'Peer unreachable — direct peering INACTIVE and no chain connection',
  frame_bundle_stale: 'Frame trust bundle stale — SPIRE federation relationship or bundle missing',
  frame_bundle_refresh_overdue: 'Frame trust bundle refresh OVERDUE — bundle older than 5 days',
  frame_bundle_refresh_critical: 'Frame trust bundle refresh CRITICAL — bundle older than 6 days OR expires within 24h',
  peer_url_misconfigured: 'Peer URL misconfigured — base_url likely missing the :8443 mTLS federation port',
  operator_network_topology: 'Operator Docker network drift — missing identity_network attachment',
}
</script>

<style scoped>
/* §pass62 — Shared PeerDetailDrawer styles. Self-contained — no global
   class collisions. Mirrors AdminEvents.vue rce-* aesthetic + Federation.vue
   fed-drawer pattern (translucent ambient surface, mono uppercase labels). */

.pdd-overlay {
  position: fixed; inset: 0; z-index: 9999;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex; justify-content: flex-end;
  animation: pdd-overlay-in 200ms ease-out;
}
@keyframes pdd-overlay-in { from { opacity: 0 } to { opacity: 1 } }

.pdd-drawer {
  background: rgba(8, 12, 20, 0.96);
  border-left: 1px solid rgba(0, 255, 255, 0.18);
  box-shadow: -16px 0 48px rgba(0, 0, 0, 0.6);
  width: min(640px, 100vw);
  max-width: 100vw;
  height: 100vh;
  display: flex; flex-direction: column;
  animation: pdd-drawer-in 280ms cubic-bezier(0.4, 0, 0.2, 1);
  color: #d6e2ee;
  font-family: 'Inter', -apple-system, system-ui, sans-serif;
}
@keyframes pdd-drawer-in { from { transform: translateX(40px); opacity: 0 } to { transform: none; opacity: 1 } }

.pdd-head {
  display: flex; align-items: flex-start; justify-content: space-between;
  padding: 1.4rem 1.5rem 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  gap: 1rem;
}
.pdd-head-left {
  display: flex; gap: 0.85rem; align-items: flex-start; min-width: 0;
}
.pdd-orb-wrap {
  flex: 0 0 auto;
  padding-top: 4px;
}
.pdd-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.12em;
  color: rgba(0, 255, 255, 0.75);
  text-transform: uppercase;
  margin-bottom: 0.2rem;
}
.pdd-title {
  font-size: 1.4rem;
  font-weight: 600;
  line-height: 1.15;
  margin: 0 0 0.2rem;
  color: #fff;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pdd-sub {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  color: rgba(214, 226, 238, 0.55);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pdd-close {
  background: transparent; border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px; color: #d6e2ee;
  cursor: pointer;
  width: 36px; height: 36px;
  display: flex; align-items: center; justify-content: center;
  transition: all 160ms;
  flex: 0 0 auto;
}
.pdd-close:hover { background: rgba(255, 255, 255, 0.06); border-color: rgba(0, 255, 255, 0.4); }

.pdd-tabs {
  display: flex; gap: 0.25rem;
  padding: 0.6rem 1.5rem 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  overflow-x: auto;
  scrollbar-width: thin;
}
.pdd-tab {
  background: transparent; border: none;
  color: rgba(214, 226, 238, 0.6);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
  padding: 0.55rem 0.85rem;
  border-bottom: 2px solid transparent;
  cursor: pointer; white-space: nowrap;
  display: flex; align-items: center; gap: 0.35rem;
  transition: all 160ms;
}
.pdd-tab:hover { color: #d6e2ee; }
.pdd-tab--active {
  color: rgba(0, 255, 255, 0.95);
  border-bottom-color: rgba(0, 255, 255, 0.8);
}

.pdd-body {
  flex: 1 1 0; overflow-y: auto;
  padding: 1.4rem 1.5rem 2rem;
  scrollbar-width: thin;
}
.pdd-pane { animation: pdd-pane-in 200ms ease-out; }
@keyframes pdd-pane-in { from { opacity: 0; transform: translateY(4px) } to { opacity: 1; transform: none } }

.pdd-center {
  display: flex; align-items: center; justify-content: center;
  padding: 3rem 0;
}
.pdd-spinner {
  width: 28px; height: 28px;
  border: 2px solid rgba(0, 255, 255, 0.15);
  border-top-color: rgba(0, 255, 255, 0.85);
  border-radius: 50%;
  animation: pdd-spin 1s linear infinite;
}
@keyframes pdd-spin { to { transform: rotate(360deg) } }
.pdd-spin { animation: pdd-spin 1s linear infinite; }

.pdd-section-h {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem; letter-spacing: 0.12em;
  text-transform: uppercase;
  color: rgba(0, 255, 255, 0.85);
  margin: 0 0 0.65rem;
}

.pdd-kv {
  display: grid; grid-template-columns: 9rem 1fr;
  column-gap: 1rem; row-gap: 0.45rem;
  margin: 0;
}
.pdd-kv dt {
  font-size: 0.78rem;
  color: rgba(214, 226, 238, 0.55);
}
.pdd-kv dd {
  margin: 0;
  font-size: 0.85rem;
  color: #e6eef7;
  word-break: break-all;
}
.pdd-mono {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  color: rgba(0, 255, 255, 0.9);
}

.pdd-overview-grid {
  display: grid; grid-template-columns: 1fr; gap: 1.5rem;
}
@media (min-width: 580px) {
  .pdd-overview-grid {
    grid-template-columns: 1fr 1fr;
  }
  .pdd-overview-counts {
    grid-column: 1 / -1;
  }
}

.pdd-count-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.65rem;
}
@media (min-width: 480px) {
  .pdd-count-grid { grid-template-columns: repeat(4, 1fr); }
}
.pdd-count-tile {
  background: rgba(0, 255, 255, 0.04);
  border: 1px solid rgba(0, 255, 255, 0.15);
  border-radius: 8px;
  padding: 0.7rem 0.85rem;
  text-align: center;
}
.pdd-count-num {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.4rem; font-weight: 600;
  color: rgba(0, 255, 255, 0.95);
  line-height: 1;
}
.pdd-count-sub {
  font-size: 0.85rem;
  color: rgba(214, 226, 238, 0.5);
  font-weight: 400;
}
.pdd-count-lbl {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem; letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(214, 226, 238, 0.55);
  margin-top: 0.3rem;
}

.pdd-pill {
  display: inline-flex; align-items: center;
  padding: 0.18rem 0.5rem;
  border-radius: 4px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.06em;
  text-transform: uppercase;
  border: 1px solid;
}
.pdd-pill--ok    { color: #6ee7a7; border-color: rgba(110, 231, 167, 0.4); background: rgba(110, 231, 167, 0.08); }
.pdd-pill--warn  { color: #fde68a; border-color: rgba(253, 230, 138, 0.4); background: rgba(253, 230, 138, 0.08); }
.pdd-pill--bad   { color: #fda4af; border-color: rgba(253, 164, 175, 0.4); background: rgba(253, 164, 175, 0.08); }
.pdd-pill--pending { color: #c4b5fd; border-color: rgba(196, 181, 253, 0.4); background: rgba(196, 181, 253, 0.08); }
.pdd-pill--muted { color: rgba(214, 226, 238, 0.6); border-color: rgba(214, 226, 238, 0.18); background: rgba(214, 226, 238, 0.03); }

.pdd-trust-bar {
  display: inline-block; width: 140px; height: 8px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 4px; overflow: hidden;
  vertical-align: middle;
  margin-right: 0.5rem;
}
.pdd-trust-bar-fill {
  display: block; height: 100%;
  background: linear-gradient(90deg, rgba(0, 255, 255, 0.4), rgba(0, 255, 255, 0.95));
  transition: width 320ms ease-out;
}
.pdd-trust-pct {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  color: rgba(0, 255, 255, 0.85);
}
.pdd-hint {
  font-size: 0.78rem;
  color: rgba(214, 226, 238, 0.55);
  line-height: 1.5;
  margin: 1rem 0 0;
}

.pdd-fees-grid {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.65rem;
}
@media (min-width: 480px) { .pdd-fees-grid { grid-template-columns: repeat(4, 1fr); } }
.pdd-fee-tile {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.7rem 0.85rem;
}
.pdd-fee-lbl {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.6rem; letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(214, 226, 238, 0.55);
  margin-bottom: 0.25rem;
}
.pdd-fee-val {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.1rem; font-weight: 600;
  color: rgba(0, 255, 255, 0.95);
}

.pdd-empty {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 1.25rem;
  border: 1px dashed rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  color: rgba(214, 226, 238, 0.6);
}
.pdd-empty--inline { padding: 0.8rem 1rem; }
.pdd-empty p { margin: 0; font-size: 0.85rem; }

/* Lifecycle */
.pdd-drift-pane {
  display: flex; gap: 0.75rem;
  padding: 0.8rem 1rem;
  background: rgba(253, 230, 138, 0.06);
  border: 1px solid rgba(253, 230, 138, 0.3);
  border-radius: 8px;
  margin-bottom: 1.25rem;
  color: #fde68a;
}
.pdd-drift-pane-body { flex: 1 1 0; }
.pdd-drift-pane-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem; letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.5rem;
}
.pdd-drift-list { display: flex; flex-direction: column; gap: 0.3rem; }
.pdd-drift-row {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.25rem 0; font-size: 0.78rem; color: #fde68a;
}
.pdd-drift-row-lbl { flex: 1; }
.pdd-drift-row-flag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem;
  color: rgba(253, 230, 138, 0.65);
}

.pdd-lc-stack {
  display: flex; flex-direction: column; gap: 0.6rem;
}
.pdd-lc-layer {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 8px;
  padding: 0.75rem 0.85rem;
  background: rgba(255, 255, 255, 0.02);
}
.pdd-lc-layer header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.45rem;
}
.pdd-lc-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.1em;
  text-transform: uppercase;
  color: rgba(214, 226, 238, 0.65);
}
.pdd-lc-status {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
}
.pdd-lc-body {
  display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center;
  font-size: 0.78rem; color: rgba(214, 226, 238, 0.78);
}
.pdd-lc-body code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  color: rgba(0, 255, 255, 0.9);
}
.pdd-lc-body em { color: rgba(214, 226, 238, 0.5); }

/* Agents */
.pdd-agent-summary {
  display: flex; align-items: center; gap: 1rem;
  padding: 1.5rem 1.25rem;
  background: rgba(0, 255, 255, 0.04);
  border: 1px solid rgba(0, 255, 255, 0.18);
  border-radius: 10px;
  color: rgba(0, 255, 255, 0.85);
  margin-bottom: 1rem;
}
.pdd-agent-bignum {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.9rem; font-weight: 600;
  line-height: 1;
  color: #fff;
}
.pdd-agent-bigsub {
  font-size: 0.78rem;
  color: rgba(214, 226, 238, 0.65);
  margin-top: 0.3rem;
}

.pdd-action-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.45rem 0.85rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 6px;
  color: #d6e2ee;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  cursor: pointer;
  margin-right: 0.5rem;
  text-decoration: none;
  transition: all 160ms;
}
.pdd-action-btn:hover {
  background: rgba(0, 255, 255, 0.08);
  border-color: rgba(0, 255, 255, 0.5);
  color: rgba(0, 255, 255, 0.95);
}
.pdd-action-btn--primary {
  background: rgba(0, 255, 255, 0.12);
  border-color: rgba(0, 255, 255, 0.5);
  color: rgba(0, 255, 255, 0.95);
}
.pdd-action-btn--sm { padding: 0.3rem 0.55rem; font-size: 0.72rem; }
.pdd-action-btn[disabled] { opacity: 0.5; cursor: not-allowed; }

/* Events */
.pdd-events-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.75rem;
  gap: 0.5rem;
}
.pdd-event-list {
  list-style: none; padding: 0; margin: 0;
  display: flex; flex-direction: column; gap: 0.25rem;
}
.pdd-event {
  display: grid; grid-template-columns: minmax(120px, auto) auto 1fr;
  gap: 0.6rem; align-items: center;
  padding: 0.4rem 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  font-size: 0.78rem;
}
.pdd-event-type {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  color: rgba(0, 255, 255, 0.85);
  white-space: nowrap;
}
.pdd-event-when {
  font-size: 0.72rem;
  color: rgba(214, 226, 238, 0.55);
  white-space: nowrap;
}
.pdd-event-detail {
  color: rgba(214, 226, 238, 0.8);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* Mobile bottom-sheet */
@media (max-width: 640px) {
  .pdd-drawer {
    width: 100vw; height: 92vh;
    margin-top: auto; border-left: none;
    border-top: 1px solid rgba(0, 255, 255, 0.18);
    border-radius: 16px 16px 0 0;
    animation: pdd-drawer-up 280ms cubic-bezier(0.4, 0, 0.2, 1);
  }
  @keyframes pdd-drawer-up { from { transform: translateY(40px); opacity: 0 } to { transform: none; opacity: 1 } }
  .pdd-overlay { align-items: flex-end; }
  .pdd-kv { grid-template-columns: 1fr; }
  .pdd-kv dt { color: rgba(0, 255, 255, 0.7); margin-top: 0.5rem; }
}
</style>
