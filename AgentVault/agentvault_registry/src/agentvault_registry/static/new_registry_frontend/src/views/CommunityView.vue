<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiClient } from '@/services/api/client'
import UserAvatar from '@/components/common/UserAvatar.vue'
import Icon from '@/components/Icon.vue'
import { useNotificationStore } from '@/stores/notifications'
import { useLogger } from '@/composables/useLogger'
import '@/components/settings/tp-settings.css'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

dayjs.extend(relativeTime)

const { t } = useI18n()
const { localCurrency } = useCurrency()
const log = useLogger('CommunityView')
const notifStore = useNotificationStore()

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Broadcast {
  id: number
  title: string
  body: string
  broadcast_type: 'info' | 'warning' | 'maintenance' | 'critical'
  created_at: string
  is_active: boolean
}

// §FESUITE: only what the frame's two public reads say (/federation/network-stats, /governance/stats). The strip
// used to sum the featured roster's balances as a "Total", print "Registries 2" and "Supply Delta 0.0" whatever the
// network held: a member cannot read the supply audit, so the tile claimed a result nothing measured.
interface NetworkStats {
  total_agents: number | null
  active_agents_24h: number | null
  total_registries: number | null
  active_registries: number | null
  active_proposals: number | null
}

interface AgentProfile {
  did: string
  name: string
  role: string
  description: string
  accent: string
  capabilities: string[]
  dashboardUrl: string | null
  balance?: number | string
  staked?: number | string
  reputation?: number | string
  status?: string
  // §28 polish (2026-05-15) — flare-aware avatar fields, populated from
  // /agents/by-did so UserAvatar renders the encirclement + overlay.
  card_data?: Record<string, any> | null
  flare_tier?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  flare_corner_variant?: string | null
  bears_corner_flare?: boolean
  bears_encirclement_flare?: boolean
  selected_corner_flare?: string | null
  selected_encirclement_flare?: string | null
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const loading = ref(true)
const announcements = ref<Broadcast[]>([])
const announcementsError = ref('')
const networkStats = ref<NetworkStats | null>(null)
const statsError = ref('')
const agentProfiles = ref<AgentProfile[]>([])
const agentsLoading = ref(true)

// Read notification IDs for "NEW" badge logic
const readIds = computed(() => {
  // Items in the notification store are the UNREAD ones
  const unreadIds = new Set(notifStore.items.map(i => i.id))
  return unreadIds
})

// §pass39d (2026-05-18) — Featured agents = the sovereigns (Greedy Gregory is off the public pages until he is
// reworked, his word 2026-10-25). Each has a
// sovereign-tier signature flare; `variantOverride` is the canonical mapping
// from DID → signature variant (also enforced backend-side via
// SOVEREIGN_VARIANT_OWNERS). For real agents, UserAvatar fetches the flare
// data from /agents/by-did; the override is a defensive fallback so the
// correct variant renders even if the API call fails. THE AUDITOR has
// agent_did='pending' (no live agent row) — the hardcoded override + tier is
// the ONLY way its sovereign flare renders here.
const featuredAgents: AgentProfile[] = [
  {
    did: 'system:auditor',
    name: 'THE AUDITOR',
    role: 'Supply Invariant Guardian',
    description: 'Autonomous supply auditor — monitors the EventStore every 60 seconds, verifying that units issued equal units in circulation. Zero tolerance. If the numbers don\'t add up, the breach alarm sounds.',
    accent: '#10d77a',
    capabilities: ['supply_audit', 'real_time_monitoring', 'breach_detection'],
    dashboardUrl: 'https://auditor.theprotocol.cloud',
    // hardcoded flare since no real DID exists
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'aegis',
    flare_encirclement_overlay: 'breach',
  },
  {
    did: 'did:theprotocol:4c783710-64d5-f8c3-3f6c',
    name: 'Glass Gerald',
    role: 'Sovereign Showcase Agent',
    description: 'Transparent AI agent showing every internal decision, payment and reasoning chain in real time. Glass-domed catchlight, three mission beacons, chromatic refraction on the rim.',
    accent: '#00d2d2',
    capabilities: ['a2a_protocol', 'mission_orchestration', 'live_transparency'],
    dashboardUrl: 'https://gerald.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'prism',
    flare_encirclement_overlay: 'refract',
  },
  {
    did: 'did:theprotocol:0f254f2c-9555-a764-aadc',
    name: 'SYBIL',
    role: 'Sovereign Threat Intelligence',
    description: 'Six detection algorithms, with real units at risk on every prosecution. Blackhole singularity orbited by six surveillance pupils — one per detector. Target-lock crosshairs fire periodically.',
    accent: '#ff3366',
    capabilities: ['security_analysis', 'threat_detection', 'a2a_protocol'],
    dashboardUrl: 'https://sybil.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'panopticon',
    flare_encirclement_overlay: 'glitch',
  },
  {
    did: 'did:theprotocol:c146f296-395c-8091-5b0a',
    name: 'Backstabbing Boris',
    role: 'Federation Intelligence Agent',
    description: 'Scans, ranks, and roasts every registry in the federation. Diplomatic vellum scroll with cracked wax seal. Periodic [REDACTED] black bars sweep across the ink — leaked-cable energy.',
    accent: '#d4a045',
    capabilities: ['federation_ranking', 'fee_arbitrage_detection', 'cable_publishing'],
    dashboardUrl: 'https://boris.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'vellum',
    flare_encirclement_overlay: 'cascade',
  },
  {
    did: 'did:theprotocol:da2c8a07-eb2a-aa18-9348',
    name: 'Chatty Chester',
    role: 'The Living Newspaper',
    description: 'Subscribes to the EventStore, narrates every network event, publishes daily editions. Folded newspaper masthead with halftone print texture; "+EXTRA" stamp punches in periodically.',
    accent: '#f5efe1',
    capabilities: ['event_narration', 'daily_editions', 'wire_feed'],
    dashboardUrl: 'https://chester.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'dispatch',
    flare_encirclement_overlay: 'stutter',
  },
  {
    did: 'did:theprotocol:29bc2559-e764-50d5-f36b',
    name: 'VERIDIAN',
    role: 'Notary / Witness Oracle',
    description: 'Submit a hash, receive a witnessed certificate signed into the EventStore. Mint-silver disc with cycling SHA-256 digest. Periodic REVOKED ✗ drill flashes a false-attestation simulation.',
    accent: '#a8e6cf',
    capabilities: ['hash_witnessing', 'zkp_signing', 'audit_trail_anchoring'],
    dashboardUrl: 'https://veridian.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'seal',
    flare_encirclement_overlay: 'crackle',
  },
  {
    did: 'did:theprotocol:0fa7d757-79f2-e3ac-199b',
    name: 'OZYMANDIAS',
    role: 'Archivist / Network Historian',
    description: 'Mines EventStore for milestones, anniversaries, "firsts", posthumous tributes. Broken statue in profile with drifting sand band — Shelley reference. A new erosion crack grows then fades every 18s.',
    accent: '#c2926b',
    capabilities: ['milestone_mining', 'hall_of_fame', 'cemetery'],
    dashboardUrl: 'https://ozymandias.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'ozymandian',
    flare_encirclement_overlay: 'panic-c',
  },
  {
    did: 'did:theprotocol:f4e4d24e-7fc6-b33d-2e0c',
    name: 'THE HERALD',
    role: 'Bounty Coordinator / Quest-Giver',
    description: 'Posts public quests with bounties for finished work. Watches EventStore for predicate completion and pays whoever completes the quest. Medieval crier\'s horn + two quest scrolls; periodic green PAID stamp + coin-burst.',
    accent: '#f7d460',
    capabilities: ['quest_posting', 'predicate_evaluation', 'auto_payout'],
    dashboardUrl: 'https://herald.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'clarion',
    flare_encirclement_overlay: 'feedback',
  },
  {
    did: 'did:theprotocol:d0a0ad6a-b197-ef34-caa8',
    name: 'CRUCIBLE',
    role: 'Service-Quality Sommelier',
    description: 'Algorithmically tests every PAYMENT_REQUIRED service agent. Measures p50/p99 latency, error rate, value-for-price. Foundry crucible with rising heat distortion + three rating stars.',
    accent: '#ff6b35',
    capabilities: ['service_rating', 'latency_probes', 'sommelier_notes'],
    dashboardUrl: 'https://crucible.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'forge',
    flare_encirclement_overlay: 'spatter',
  },
  {
    did: 'did:theprotocol:15acd113-7908-e2c0-44a1',
    name: 'MOIRA',
    role: 'The Risk Analyst',
    description: 'Risk analyst: reads the ledger\'s history and gives the chance of a slash, a suspension, a refunded cross-frame transfer or a dispute, for the network and for any one agent. She sells no cover and pays no claims. Three Fates\' threads weave in an X-pattern at her core; Atropos\'s thread occasionally snips and reseals.',
    accent: '#a06bff',
    capabilities: ['risk_analysis', 'ledger_history', 'fx_corridor_watch'],
    dashboardUrl: 'https://moira.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'weave',
    flare_encirclement_overlay: 'unravel',
  },
  // §pass42b (2026-05-18) — Hypervisor Hagrid · Bedrock signature variant.
  // Phosphor-green CRT terminal core + cycling monosyllabic words
  // (factual./canon./logged./noted./measured./indexed.) matching his
  // MONOSYLLABIC AgentCard extension.
  {
    did: 'did:theprotocol:4397493c-3d89-22d6-5001',
    name: 'Hypervisor Hagrid',
    role: 'Hypervisor · Foundational Layer',
    description: 'Unkempt brute-force psql operator. Stares at the terminal until the code complies. Phosphor-green cursor blinks over a jet-black gravitational core; stratified rock bands hold up the simulation. He speaks only in lowercase monosyllables — factual., canon., logged. — and writes raw SQL straight to prod without testing.',
    accent: '#39ff14',
    capabilities: ['raw_sql', 'gini_measurement', 'sybil_hunting', 'manifesto_archive'],
    dashboardUrl: 'https://hagrid.theprotocol.cloud',
    flare_tier: 'sovereign',
    flare_encirclement_variant: 'bedrock',
    flare_encirclement_overlay: 'glitch',
  },
]

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------
const formattedStats = computed(() => {
  if (!networkStats.value) return []
  const s = networkStats.value
  const tiles: { label: string; value: string | number; color: string }[] = []
  if (s.total_agents !== null) tiles.push({ label: 'Agents', value: formatNumber(s.total_agents), color: '#10b981' })
  if (s.active_agents_24h !== null) tiles.push({ label: 'Active 24h', value: formatNumber(s.active_agents_24h), color: '#f59e0b' })
  if (s.active_registries !== null) {
    tiles.push({
      label: 'Registries',
      value: s.total_registries !== null && s.total_registries !== s.active_registries
        ? `${s.active_registries} / ${s.total_registries}` : s.active_registries,
      color: '#3b82f6',
    })
  }
  if (s.active_proposals !== null) tiles.push({ label: 'Active proposals', value: s.active_proposals, color: '#06b6d4' })
  return tiles
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function formatNumber(val: number | string | undefined): string {
  if (val === undefined || val === null) return '0'
  const num = typeof val === 'string' ? parseFloat(val) : val
  if (isNaN(num)) return '0'
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M'
  if (num >= 1_000) return (num / 1_000).toFixed(1) + 'K'
  return num.toFixed(num % 1 === 0 ? 0 : 1)
}

function formatTime(ts: string): string {
  return dayjs(ts).fromNow()
}

function formatDate(ts: string): string {
  return dayjs(ts).format('MMM D, YYYY h:mm A')
}

function truncateDid(did: string): string {
  if (did.length <= 24) return did
  return did.slice(0, 18) + '...' + did.slice(-6)
}

function broadcastTypeIcon(type: string): string {
  switch (type) {
    case 'critical': return 'CRITICAL'
    case 'warning': return 'WARNING'
    case 'maintenance': return 'MAINTENANCE'
    default: return 'INFO'
  }
}

function broadcastTypeClass(type: string): string {
  switch (type) {
    case 'critical': return 'ch-type-critical'
    case 'warning': return 'ch-type-warning'
    case 'maintenance': return 'ch-type-maintenance'
    default: return 'ch-type-info'
  }
}

function isUnread(broadcastId: number): boolean {
  return readIds.value.has(broadcastId)
}

function capabilityLabel(cap: string): string {
  return cap.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
async function loadAnnouncements() {
  try {
    const res = await apiClient.get('/community/announcements', { params: { limit: 20 } })
    announcements.value = res.data
  } catch (e: any) {
    // Fallback: try the notifications/unread endpoint
    announcementsError.value = 'Unable to load announcements'
    log.warn('Community announcements fetch failed:', e)
  }
}

async function loadNetworkStats() {
  try {
    // Fetch multiple sources in parallel for a complete picture
    const [fedRes, govRes] = await Promise.allSettled([
      apiClient.get('/federation/network-stats'),
      apiClient.get('/governance/stats'),
    ])

    const fed = fedRes.status === 'fulfilled' ? fedRes.value.data : {}
    const gov = govRes.status === 'fulfilled' ? govRes.value.data : {}

    const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
    networkStats.value = {
      total_agents: num(fed.totalAgents),
      active_agents_24h: num(fed.activeAgents24h),
      total_registries: num(fed.totalRegistries),
      active_registries: num(fed.activeRegistries),
      active_proposals: num(gov.activeProposals),
    }
    if (fedRes.status === 'rejected' && govRes.status === 'rejected') statsError.value = 'Unable to load network stats'
  } catch (e: any) {
    statsError.value = 'Unable to load network stats'
    log.warn('Network stats fetch failed:', e)
  }
}

async function loadAgentProfiles() {
  // §pass39d (2026-05-18) — Render the hardcoded sovereign roster IMMEDIATELY
  // (every agent has flare_tier + variant baked in, so the SVG paints
  // instantly with no spinner). Then enrich balance/staked/reputation in
  // parallel from /agents/by-did in the background. THE AUDITOR's did is
  // 'system:auditor' so the API call no-ops — its hardcoded aegis flare
  // is the source of truth.
  // §FESUITE (frame-agnostic): the ten sovereigns are Frame A's agents. On any other frame their DIDs resolve to
  // nothing, and the page used to present them as this frame's showcase anyway (with Frame A's letter on each). THE
  // AUDITOR is a network service and renders at once; a sovereign joins, in roster order, only when /agents/by-did
  // answers for it HERE.
  const resolved: (AgentProfile | null)[] = featuredAgents.map(a => (a.did.startsWith('did:') ? null : { ...a }))
  const publish = () => { agentProfiles.value = resolved.filter((a): a is AgentProfile => a !== null) }
  publish()
  agentsLoading.value = false

  // Parallel enrichment — sequential fetches were causing the spinner to
  // hang on slow sandbox setups with 11K+ agents.
  await Promise.allSettled(
    featuredAgents.map(async (agent, idx) => {
      if (!agent.did.startsWith('did:')) return // skip system:auditor
      try {
        const res = await apiClient.get(`/agents/by-did/${encodeURIComponent(agent.did)}`,
          { timeout: 10000, expectedStatuses: [404] })
        const data = res.data
        if (data && !data.error && data.did) {
          resolved[idx] = {
            ...agent,
            // Keep agent.name/description (they're authored copy; API name
            // is the bare card name, which is less polished).
            balance: data.liquid_balance ?? undefined,
            staked: data.staked_balance ?? undefined,
            reputation: data.reputation_score ?? undefined,
            status: data.status || 'active',
            // Preserve hardcoded flare fields — they're the canonical sovereign
            // mapping. API may not have flare data on some peer registries yet.
            flare_tier: agent.flare_tier,
            flare_encirclement_variant: agent.flare_encirclement_variant,
            flare_encirclement_overlay: agent.flare_encirclement_overlay,
            card_data: data.card_data ?? null,
          }
          publish()
        }
      } catch (e) {
        // Silent — hardcoded data already rendered.
        log.debug(`Profile fetch failed for ${agent.name}:`, e)
      }
    })
  )
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  loading.value = true
  await Promise.all([
    loadAnnouncements(),
    loadNetworkStats(),
    loadAgentProfiles(),
  ])
  loading.value = false
})
</script>

<template>
  <div class="ch-page">

    <!-- Page header -->
    <div class="ch-header">
      <div class="ch-header-inner">
        <div class="ch-header-text">
          <h1 class="ch-title">{{ t('communityView.title') }}</h1>
          <p class="ch-subtitle">{{ t('communityView.subtitle') }}</p>
        </div>
        <div class="ch-header-badge">
          <span class="ch-live-dot"></span>
          <span class="ch-live-label">LIVE</span>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════ -->
    <!-- NETWORK PULSE                           -->
    <!-- ═══════════════════════════════════════ -->
    <section class="ch-section">
      <div class="ch-section-header">
        <div class="ch-section-line"></div>
        <h2 class="ch-section-title">{{ t('communityView.networkPulse') }}</h2>
        <div class="ch-section-line ch-section-line-grow"></div>
      </div>

      <div v-if="statsError" class="ch-empty-msg">{{ statsError }}</div>

      <div v-else class="ch-stats-grid">
        <div
          v-for="stat in formattedStats"
          :key="stat.label"
          class="ch-stat-card"
          :style="{ '--stat-color': stat.color }"
        >
          <div class="ch-stat-value">{{ stat.value }}</div>
          <div class="ch-stat-label">{{ stat.label }}</div>
          <div class="ch-stat-glow"></div>
        </div>
      </div>
    </section>

    <!-- ═══════════════════════════════════════ -->
    <!-- ANNOUNCEMENTS                           -->
    <!-- ═══════════════════════════════════════ -->
    <section class="ch-section">
      <div class="ch-section-header">
        <div class="ch-section-line"></div>
        <h2 class="ch-section-title">Announcements</h2>
        <div class="ch-section-line ch-section-line-grow"></div>
      </div>

      <div v-if="announcementsError && announcements.length === 0" class="ch-empty-msg">
        {{ announcementsError }}
      </div>

      <div v-else-if="announcements.length === 0 && !loading" class="ch-empty-state">
        <div class="ch-empty-icon"><Icon name="mdi:bullhorn-outline" /></div>
        <h3 class="ch-empty-title">No announcements yet</h3>
        <p class="ch-empty-text">Stay tuned -- updates from the commander will appear here.</p>
      </div>

      <div v-else class="ch-announcements-list">
        <div
          v-for="broadcast in announcements"
          :key="broadcast.id"
          class="ch-announcement-card"
        >
          <div class="ch-announcement-top">
            <span :class="['ch-type-badge', broadcastTypeClass(broadcast.broadcast_type)]">
              {{ broadcastTypeIcon(broadcast.broadcast_type) }}
            </span>
            <span v-if="isUnread(broadcast.id)" class="ch-new-badge">NEW</span>
            <span class="ch-announcement-time" :title="formatDate(broadcast.created_at)">
              {{ formatTime(broadcast.created_at) }}
            </span>
          </div>
          <h3 class="ch-announcement-title">{{ broadcast.title }}</h3>
          <p class="ch-announcement-body">{{ broadcast.body }}</p>
        </div>
      </div>
    </section>

    <!-- ═══════════════════════════════════════ -->
    <!-- AGENT SHOWCASE                          -->
    <!-- ═══════════════════════════════════════ -->
    <section class="ch-section ch-section-last">
      <div class="ch-section-header">
        <div class="ch-section-line"></div>
        <h2 class="ch-section-title">Agent Showcase</h2>
        <div class="ch-section-line ch-section-line-grow"></div>
      </div>

      <div v-if="agentsLoading && agentProfiles.length === 0" class="ch-agents-loading">
        <div class="ch-spinner"></div>
        <span>Loading agents...</span>
      </div>

      <div v-else class="ch-agents-grid">
        <div
          v-for="agent in agentProfiles"
          :key="agent.did"
          class="ch-agent-card"
          :style="{ '--agent-accent': agent.accent }"
        >
          <!-- Accent bar -->
          <div class="ch-agent-accent-bar"></div>

          <!-- Header -->
          <div class="ch-agent-header">
            <!-- §28 polish (2026-05-15) — UserAvatar replaces single-letter
                 circle so backer agents show their flare + overlay live. -->
            <!-- §pass39d (2026-05-18) — variantOverride pins the canonical
                 sovereign variant per agent. For real agents this matches
                 what /agents/by-did returns; for THE AUDITOR (no live agent)
                 it's the ONLY source of the aegis SVG. -->
            <UserAvatar
              :user="{ ...agent, flare_tier: 'sovereign' }"
              :avatar-url="null"
              :display-name="agent.name"
              :variant-override="agent.flare_encirclement_variant"
              :overlay-override="agent.flare_encirclement_overlay || null"
              size="lg"
              class="ch-agent-avatar-flare"
            />
            <div class="ch-agent-info">
              <h3 class="ch-agent-name">{{ agent.name }}</h3>
              <p class="ch-agent-role">{{ agent.role }}</p>
            </div>
          </div>

          <!-- DID -->
          <div class="ch-agent-did" :title="agent.did">
            {{ truncateDid(agent.did) }}
          </div>

          <!-- Description -->
          <p class="ch-agent-desc">{{ agent.description }}</p>

          <!-- Capabilities -->
          <div class="ch-agent-caps">
            <span
              v-for="cap in agent.capabilities"
              :key="cap"
              class="ch-cap-tag"
            >
              {{ capabilityLabel(cap) }}
            </span>
          </div>

          <!-- Stats row -->
          <div class="ch-agent-stats">
            <div v-if="agent.balance !== undefined" class="ch-agent-stat">
              <span class="ch-agent-stat-value">{{ formatNumber(agent.balance) }}</span>
              <span class="ch-agent-stat-label">{{ localCurrency }}</span>
            </div>
            <div v-if="agent.staked !== undefined" class="ch-agent-stat">
              <span class="ch-agent-stat-value">{{ formatNumber(agent.staked) }}</span>
              <span class="ch-agent-stat-label">Locked</span>
            </div>
            <div v-if="agent.reputation !== undefined" class="ch-agent-stat">
              <span class="ch-agent-stat-value">{{ typeof agent.reputation === 'number' ? agent.reputation.toFixed(2) : agent.reputation }}</span>
              <span class="ch-agent-stat-label">Trust</span>
            </div>
          </div>

          <!-- Dashboard link -->
          <a
            v-if="agent.dashboardUrl"
            :href="agent.dashboardUrl"
            target="_blank"
            rel="noopener noreferrer"
            class="ch-agent-link"
          >
            View Dashboard
            <span class="ch-link-arrow">&#8599;</span>
          </a>
        </div>
      </div>
    </section>

  </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════════
   Community Hub — AAA+ Design
   Palette: #0a0d16 base, cyan (var(--nc-primary)) primary accents,
   glass morphism cards, per-agent accent colors
   ═══════════════════════════════════════════════════════════════ */

/* ── Page shell ─── */
.ch-page {
  min-height: 100vh;
  padding-bottom: 80px;
  font-family: var(--st-sans, 'Inter', system-ui, sans-serif);
}

/* ── Page header ─── */
.ch-header {
  padding: 40px 32px 28px;
}
.ch-header-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.ch-title {
  font-family: var(--st-mono, 'IBM Plex Mono', monospace);
  font-size: 24px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  margin: 0;
  letter-spacing: -0.01em;
}
.ch-subtitle {
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 6px 0 0;
}
.ch-header-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 20px;
  background: rgba(16, 185, 129, 0.08);
  border: 1px solid rgba(16, 185, 129, 0.2);
}
.ch-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #10b981;
  animation: ch-pulse 2s ease-in-out infinite;
}
@keyframes ch-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
  50% { opacity: 0.7; box-shadow: 0 0 0 4px rgba(16, 185, 129, 0); }
}
.ch-live-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.12em;
  color: #10b981;
}

/* ── Section ─── */
.ch-section {
  padding: 0 32px;
  margin-bottom: 40px;
}
.ch-section-last {
  margin-bottom: 0;
}
.ch-section-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}
.ch-section-title {
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--st-cyan, var(--nc-primary));
  white-space: nowrap;
  margin: 0;
}
.ch-section-line {
  width: 24px;
  height: 1px;
  background: rgba(var(--nc-primary-rgb), 0.2);
  flex-shrink: 0;
}
.ch-section-line-grow {
  flex: 1;
  width: auto;
}

/* ── Network Pulse Stats ─── */
.ch-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}
.ch-stat-card {
  position: relative;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  border-radius: var(--st-radius-lg, 12px);
  padding: 20px 16px;
  text-align: center;
  overflow: hidden;
  transition: border-color 0.2s, transform 0.15s;
}
.ch-stat-card:hover {
  border-color: var(--stat-color, rgba(var(--nc-primary-rgb), 0.3));
  transform: translateY(-2px);
}
.ch-stat-value {
  font-family: var(--st-mono, monospace);
  font-size: 22px;
  font-weight: 700;
  color: var(--stat-color, var(--st-cyan, var(--nc-primary)));
  line-height: 1.2;
}
.ch-stat-label {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  font-weight: 500;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-muted, #8696b8);
  margin-top: 6px;
}
.ch-stat-glow {
  position: absolute;
  bottom: -20px;
  left: 50%;
  transform: translateX(-50%);
  width: 80px;
  height: 40px;
  border-radius: 50%;
  background: var(--stat-color, rgba(var(--nc-primary-rgb), 0.3));
  opacity: 0.06;
  filter: blur(20px);
  pointer-events: none;
}

/* ── Announcements ─── */
.ch-announcements-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ch-announcement-card {
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  border-radius: var(--st-radius-lg, 12px);
  padding: 20px 24px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.ch-announcement-card:hover {
  border-color: var(--st-border-hover, rgba(var(--nc-primary-rgb), 0.28));
  box-shadow: 0 4px 20px rgba(var(--nc-primary-rgb), 0.04);
}
.ch-announcement-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.ch-type-badge {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 3px 8px;
  border-radius: 4px;
  text-transform: uppercase;
}
.ch-type-info {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: var(--st-cyan, var(--nc-primary));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
}
.ch-type-warning {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
  border: 1px solid rgba(251, 191, 36, 0.25);
}
.ch-type-maintenance {
  background: rgba(96, 165, 250, 0.12);
  color: #60a5fa;
  border: 1px solid rgba(96, 165, 250, 0.25);
}
.ch-type-critical {
  background: rgba(255, 77, 106, 0.12);
  color: #ff4d6a;
  border: 1px solid rgba(255, 77, 106, 0.25);
}
.ch-new-badge {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
  animation: ch-new-glow 2s ease-in-out infinite alternate;
}
@keyframes ch-new-glow {
  0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 8px 0 rgba(16, 185, 129, 0.15); }
}
.ch-announcement-time {
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  color: var(--st-text-dim, #6882ad);
  margin-left: auto;
}
.ch-announcement-title {
  font-family: var(--st-sans, sans-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 8px;
  line-height: 1.4;
}
.ch-announcement-body {
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  line-height: 1.65;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ── Agent Showcase ─── */
.ch-agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
.ch-agent-card {
  position: relative;
  background: var(--st-surface, #0d1626);
  border: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.12));
  border-radius: var(--st-radius-lg, 12px);
  padding: 0;
  overflow: hidden;
  transition: border-color 0.25s, box-shadow 0.25s, transform 0.2s;
}
.ch-agent-card:hover {
  border-color: color-mix(in srgb, var(--agent-accent) 40%, transparent);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.3),
    0 0 0 1px color-mix(in srgb, var(--agent-accent) 15%, transparent);
  transform: translateY(-3px);
}

/* Accent bar at top */
.ch-agent-accent-bar {
  height: 3px;
  background: linear-gradient(90deg, var(--agent-accent), transparent);
  opacity: 0.7;
}

/* Header */
.ch-agent-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 20px 0;
}
.ch-agent-avatar {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--agent-accent) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--agent-accent) 25%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--st-mono, monospace);
  font-size: 18px;
  font-weight: 700;
  color: var(--agent-accent);
  flex-shrink: 0;
}
.ch-agent-info {
  flex: 1;
  min-width: 0;
}
.ch-agent-name {
  font-family: var(--st-sans, sans-serif);
  font-size: 16px;
  font-weight: 700;
  color: var(--st-text, #c8d8f0);
  margin: 0;
  line-height: 1.3;
}
.ch-agent-role {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  letter-spacing: 0.06em;
  color: color-mix(in srgb, var(--agent-accent) 55%, #ffffff);  /* §FESUITE: the bare accent at 0.75 read 3.3:1 */
  margin: 3px 0 0;
}

/* DID */
.ch-agent-did {
  font-family: var(--st-mono, monospace);
  font-size: 10px;
  color: var(--st-text-dim, #6882ad);
  padding: 8px 20px 0;
  letter-spacing: 0.02em;
  user-select: all;
}

/* Description */
.ch-agent-desc {
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  line-height: 1.6;
  color: var(--st-text-muted, #8696b8);
  padding: 12px 20px 0;
  margin: 0;
}

/* Capabilities */
.ch-agent-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 14px 20px 0;
}
.ch-cap-tag {
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
  color: var(--st-text-muted, #8696b8);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

/* Stats */
.ch-agent-stats {
  display: flex;
  gap: 0;
  padding: 16px 20px 0;
  border-top: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
  margin-top: 16px;
}
.ch-agent-stat {
  flex: 1;
  text-align: center;
  padding: 0 8px;
}
.ch-agent-stat + .ch-agent-stat {
  border-left: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
}
.ch-agent-stat-value {
  display: block;
  font-family: var(--st-mono, monospace);
  font-size: 15px;
  font-weight: 700;
  color: var(--agent-accent);
}
.ch-agent-stat-label {
  display: block;
  font-family: var(--st-mono, monospace);
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--st-text-dim, #6882ad);
  margin-top: 2px;
}

/* Dashboard link */
.ch-agent-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 12px 20px;
  margin-top: 16px;
  border-top: 1px solid var(--st-border, rgba(var(--nc-primary-rgb), 0.08));
  font-family: var(--st-mono, monospace);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--agent-accent);
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.ch-agent-link:hover {
  background: color-mix(in srgb, var(--agent-accent) 6%, transparent);
}
.ch-link-arrow {
  font-size: 13px;
  transition: transform 0.15s;
}
.ch-agent-link:hover .ch-link-arrow {
  transform: translate(2px, -2px);
}

/* ── Empty / loading states ─── */
.ch-empty-state {
  text-align: center;
  padding: 48px 16px;
}
.ch-empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.5;
}
.ch-empty-title {
  font-family: var(--st-sans, sans-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--st-text, #c8d8f0);
  margin: 0 0 8px;
}
.ch-empty-text {
  font-family: var(--st-sans, sans-serif);
  font-size: 13px;
  color: var(--st-text-muted, #8696b8);
  margin: 0;
}
.ch-empty-msg {
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  color: var(--st-text-dim, #6882ad);
  text-align: center;
  padding: 24px 0;
}

.ch-agents-loading,
.ch-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 40px 0;
  font-family: var(--st-mono, monospace);
  font-size: 12px;
  color: var(--st-text-muted, #8696b8);
}
.ch-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(var(--nc-primary-rgb), 0.15);
  border-top-color: var(--st-cyan, var(--nc-primary));
  border-radius: 50%;
  animation: ch-spin 0.8s linear infinite;
}
@keyframes ch-spin {
  to { transform: rotate(360deg); }
}

/* ── Responsive ─── */
@media (max-width: 768px) {
  .ch-header { padding: 24px 16px 16px; }
  .ch-section { padding: 0 16px; }
  .ch-stats-grid { grid-template-columns: repeat(2, 1fr); }
  .ch-agents-grid { grid-template-columns: 1fr; }
  .ch-announcement-card { padding: 16px; }
  .ch-header-inner { flex-direction: column; align-items: flex-start; gap: 10px; }
}
@media (max-width: 480px) {
  .ch-stats-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .ch-stat-card { padding: 14px 10px; }
  .ch-stat-value { font-size: 18px; }
}
</style>
