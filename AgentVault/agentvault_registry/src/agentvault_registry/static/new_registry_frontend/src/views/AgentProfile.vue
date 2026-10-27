<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import AgentAccessPanel from '@/components/agent/AgentAccessPanel.vue'  // IRONKEY

const { t } = useI18n()
import { agentCardsApi } from '@/services/api/agentCards'
import { apiClient } from '@/services/api/client'
import FlareBadge from '@/components/common/FlareBadge.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { discoveryService } from '@/services/api/discovery'
import { agentAvatarUser, agentAvatarUrl } from '@/services/agentAvatar'
import StatCard from '@/components/common/StatCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import PanelHeader from '@/components/common/PanelHeader.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import Icon from '@/components/Icon.vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const authStore = useAuthStore()
const uiStore = useUIStore()

// ─── State ───
const isLoading = ref(false)
const activeTab = ref<'overview' | 'skills' | 'performance' | 'reputation' | 'evals' | 'logs' | 'access'>('overview')

// Agent Evals (feature-gated backend; empty array when off → tab shows a hint).
import { evalsApi, type EvalResult } from '@/services/api/evals'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
const evalResults = ref<EvalResult[]>([])
const evalsLoading = ref(false)
// §FESUITE (2026-10-04): "No eval results yet." was drawn with the read failed (the service answered [] for every
// failure). "None" now needs a read that answered for THIS agent; a failed first read says so and offers it again.
const evalsReadFor = ref<string | null>(null)   // the agent whose results the tab shows
const evalsFailed = ref(false)
async function loadEvals() {
  const did = agentDid.value
  if (!did) return
  evalsLoading.value = true
  try {
    const rows = await evalsApi.getAgentResults(did, 20)
    if (did !== agentDid.value) return
    evalResults.value = rows
    evalsReadFor.value = did
    evalsFailed.value = false
  } catch {
    if (did !== agentDid.value) return
    // a refresh that fails keeps what this agent last read; an agent never read says its read failed
    if (evalsReadFor.value !== did) { evalResults.value = []; evalsFailed.value = true }
  } finally {
    evalsLoading.value = false
  }
}
const agent = ref<any>(null)
const agentCard = ref<any>(null)
// the hero's face: the agent as Discovery enriches it (its card's flare and picture), read after the page has its agent;
// until it answers, or if it cannot, the hero draws the agent's initial
const heroAgent = ref<any>(null)
const heroUser = computed(() => agentAvatarUser(heroAgent.value))
const heroAvatarUrl = computed(() => agentAvatarUrl(heroAgent.value))
function loadHeroAgent(did: string) {
  heroAgent.value = null
  discoveryService.lookupByDID(did).then((r) => { if (did === agentDid.value) heroAgent.value = r }).catch(() => {})
}
const isOwner = ref(false)

// ─── CONTRACT SPINE P3: discovery "Engage" (card-advertised engagement terms) ───
import { contractsV2Api } from '@/services/api/contractsV2'
const showEngageModal = ref(false)
const engageBusy = ref(false)
const engagementTerms = computed<any>(() => {
  const cd = agentCard.value?.card_data || agentCard.value
  const eng = cd?.engagement
  return eng && typeof eng === 'object' ? eng : null
})
const engageMessage = computed(() => {
  const e = engagementTerms.value || {}
  const price = e.price != null ? `${e.price} ${e.currency || ''}`.trim() : 'per agreement'
  return `Create a private contract offer to <strong>${agent.value?.name || agentDid.value}</strong> ` +
         `from its advertised engagement terms (${price})? Your funds are escrowed only when the ` +
         `provider accepts; milestones release from escrow as work is approved.`
})
function openEngage() { showEngageModal.value = true }
async function confirmEngage() {
  engageBusy.value = true
  try {
    const c = await contractsV2Api.engage(agentDid.value, {})
    uiStore.showSuccess('Contract offered', `${c.id} — ${c.total_amount} ${c.currency}`)
    showEngageModal.value = false
    router.push('/contracts')
  } catch (e: any) {
    const st = e?.response?.status
    const msg = st === 503 ? 'Contracts v2 is not enabled on this registry yet'
      : (e?.response?.data?.detail || e?.message || 'Engage failed')
    uiStore.showError('Engage failed', String(msg).slice(0, 240))
  } finally {
    engageBusy.value = false
  }
}

// ─── Skills: the agent's own card's, read-only ───
const skills = ref<Array<{ id: string; name: string; description: string; tags: string[] }>>([])
const skillsLoading = ref(false)
const skillsFailed = ref(false)

// ─── Performance Metrics (REAL — from GET /agent-metrics/{did}) ───
const metricsLoading = ref(false)
const performanceMetrics = ref({
  total_requests: 0,
  success_rate: 0,
  avg_response_time: 0,
  uptime_percentage: 0,
  last_active: null as string | null,
  daily_stats: {
    requests_today: 0,
    errors_today: 0,
    unique_callers: 0
  },
  weekly_trend: {
    request_growth: 0,
    error_rate_change: 0
  }
})
const metricsTimeRange = ref('24h')

// ─── Reputation (REAL — from GET /teg/agents/{did}/reputation) ───
const reputationLoading = ref(false)
const reputation = ref({
  reputation_score: 0,
  reputation_tier: 'Unranked',
  last_updated: null as string | null
})
// §FESUITE (V0577): the figures above are the page's starting values, not the agent's. A failed read with no score on
// the agent row (any agent that is not yours) kept them: "0 rep · Unranked" and "0 / 100", also while the read was in
// flight. They show once a read (or the agent's own row) answered for THIS agent; a refresh that fails keeps them.
const reputationFor = ref('')
const repScoreText = computed(() => (reputationFor.value === agentDid.value ? String(reputation.value.reputation_score) : '—'))
const repTierText = computed(() => (reputationFor.value === agentDid.value ? reputation.value.reputation_tier : '—'))

// ─── Agent Logs (REAL — from GET /agents/{did}/logs) ───
const logsLoading = ref(false)
const agentLogs = ref<any[]>([])
const logsFilter = ref('all')
const logsTimeRange = ref('24h')

// ─── Computed ───
const agentDid = computed(() => {
  const raw = route.params.did as string
  // Decode URI-encoded DIDs (e.g., did%3Acos%3A... → did:cos:...)
  return raw ? decodeURIComponent(raw) : ''
})

const filteredLogs = computed(() => {
  if (logsFilter.value === 'all') return agentLogs.value
  return agentLogs.value.filter(l => l.level === logsFilter.value.toUpperCase())
})

const reputationColor = computed(() => {
  const score = reputation.value.reputation_score
  if (score >= 80) return 'text-green-500'
  if (score >= 60) return 'text-blue-500'
  if (score >= 40) return 'text-yellow-500'
  if (score > 0) return 'text-orange-500'
  return 'text-gray-400'
})

const tierBadgeClass = computed(() => {
  const tier = reputation.value.reputation_tier?.toLowerCase() || ''
  if (tier.includes('gold') || tier.includes('elite')) return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
  if (tier.includes('silver')) return 'bg-gray-200 text-gray-800 dark:bg-gray-600 dark:text-gray-200'
  if (tier.includes('bronze')) return 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200'
  return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
})

function rangeLabel(r: string): string {
  if (r === '1h') return t('agentProfileView.lastHour')
  if (r === '24h') return t('agentProfileView.last24h')
  if (r === '7d') return t('agentProfileView.sevenDays')
  return t('agentProfileView.thirtyDays')
}

// ─── Load Agent Profile ───
async function loadAgentProfile() {
  if (!agentDid.value) {
    uiStore.showError('Invalid Agent', 'No agent DID provided')
    router.push('/discover')
    return
  }

  isLoading.value = true
  try {
    // Load agent from developer's agents
    const agentsResponse = await apiClient.get('/developers/me/agents')
    const myAgents = agentsResponse.data.items || agentsResponse.data || []
    agent.value = myAgents.find((a: any) => a.did === agentDid.value || a.agent_did === agentDid.value)

    if (!agent.value) {
      // §FESUITE (V0577): an agent that is not yours is read by its DID (GET /agents/by-did: a local agent, a federated
      // card or a named card). The card search below matches names and descriptions, never a DID, so every such agent
      // (the Forge's lineage nodes and the command palette's DID lookup open them) read "Agent Not Found" and left for
      // /discover. A 404 is the registry's "no such agent" (the card search is the last try); any other failure could not
      // read it, and says so through "Load Failed" below, never "Agent Not Found".
      try {
        const { data } = await apiClient.get(`/agents/by-did/${encodeURIComponent(agentDid.value)}`)
        if (data && (data.did || data.agent_did)) {
          agent.value = {
            did: data.did || data.agent_did,
            name: data.name,
            description: data.description,
            created_at: data.created_at,
            status: data.status || 'active',
            // only a number is a score: the reputation fallback reads it, and null would print as "null rep"
            reputation_score: typeof data.reputation_score === 'number' ? data.reputation_score : undefined,
          }
        }
      } catch (error: any) {
        if (error?.response?.status !== 404) throw error
      }
    }

    if (!agent.value) {
      // Try to load from public agent cards
      try {
        const cards = await agentCardsApi.searchCards(agentDid.value)
        const card = cards.find((c: any) => c.agent_did === agentDid.value) as any
        if (card) {
          agent.value = {
            did: card.agent_did || card.creator_did,
            name: card.name,
            description: card.description,
            created_at: card.created_at,
            status: card.status || 'active'
          }
          agentCard.value = card
        }
      } catch (error) {
        console.error('Failed to load from agent cards:', error)
      }
    }

    if (!agent.value) {
      uiStore.showError('Agent Not Found', 'Could not find agent with the specified DID')
      router.push('/discover')
      return
    }
    loadHeroAgent(agentDid.value)

    // Check ownership
    isOwner.value = myAgents.some((a: any) =>
      (a.did === agentDid.value || a.agent_did === agentDid.value)
    )

    // Load agent card if not already loaded
    if (!agentCard.value) {
      try {
        const cards = await agentCardsApi.searchCards(agent.value.name || agentDid.value)
        agentCard.value = cards.find((c: any) =>
          c.agent_did === agentDid.value || c.name === agent.value.name
        ) as any
      } catch (error) {
        console.error('Failed to load agent card:', error)
      }
    }

    // Load skills (REAL — fixed method name)
    await loadSkills()

    // Load metrics (REAL)
    await loadMetrics()

    // Load reputation (REAL)
    await loadReputation()

  } catch (error) {
    console.error('Failed to load agent profile:', error)
    uiStore.showError('Load Failed', 'Failed to load agent profile')
  } finally {
    isLoading.value = false
  }
}

// ─── Skills: read from the agent's own card (its A2A `skills[]`), as the agent publishes them ───
// Until 2026-10-03 this asked GET /agent-cards/{id}/skills and saved through a PUT on the same path, which no router
// defines: every load answered 404 and every add or remove said it failed to sync. A card is changed through the card
// itself (PUT /agent-cards/{did} with its card_data), so this tab shows the card's skills and changes nothing.
async function loadSkills() {
  skillsLoading.value = true
  skillsFailed.value = false
  try {
    const { data } = await apiClient.get(`/agent-cards/${encodeURIComponent(agentDid.value)}`)
    const list = (data as any)?.card_data?.skills
    skills.value = (Array.isArray(list) ? list : [])
      .filter((x: any) => x && typeof x === 'object' && (x.name || x.id))
      .map((x: any, i: number) => ({
        id: String(x.id || x.name || i),
        name: String(x.name || x.id),
        description: typeof x.description === 'string' ? x.description : '',
        tags: Array.isArray(x.tags) ? x.tags.filter((tag: any) => typeof tag === 'string').slice(0, 8) : [],
      }))
  } catch (error: any) {
    skills.value = []
    // an agent with no card has no skills to show; any other answer is a read that failed, and says so
    skillsFailed.value = error?.response?.status !== 404
  } finally {
    skillsLoading.value = false
  }
}

// ─── Performance Metrics (REAL — GET /agent-metrics/{did}) ───
// §FESUITE (V0575): the zeros this page starts with are not the agent's figures; a read that failed says so
const metricsFailed = ref(false)
async function loadMetrics() {
  metricsLoading.value = true
  metricsFailed.value = false
  try {
    const response = await apiClient.get(`/agent-metrics/${encodeURIComponent(agentDid.value)}`, {
      params: { time_range: metricsTimeRange.value }
    })
    performanceMetrics.value = {
      total_requests: response.data.total_requests || 0,
      success_rate: response.data.success_rate || 0,
      avg_response_time: response.data.avg_response_time || 0,
      uptime_percentage: response.data.uptime_percentage || 0,
      last_active: response.data.last_active || null,
      daily_stats: response.data.daily_stats || { requests_today: 0, errors_today: 0, unique_callers: 0 },
      weekly_trend: response.data.weekly_trend || { request_growth: 0, error_rate_change: 0 }
    }
  } catch (error) {
    console.error('Failed to load metrics:', error)
    metricsFailed.value = true
  } finally {
    metricsLoading.value = false
  }
}

// ─── Reputation (REAL — GET /teg/agents/{did}/reputation) ───
async function loadReputation() {
  reputationLoading.value = true
  try {
    const response = await apiClient.get(`/teg/agents/${encodeURIComponent(agentDid.value)}/reputation`)
    reputation.value = {
      reputation_score: response.data.reputation_score ?? 0,
      reputation_tier: response.data.reputation_tier || 'Unranked',
      last_updated: response.data.last_updated || null
    }
    reputationFor.value = agentDid.value
  } catch (error) {
    console.error('Failed to load reputation:', error)
    // Fallback: use reputation_score from agent model if available
    if (agent.value?.reputation_score !== undefined) {
      reputation.value = {
        reputation_score: agent.value.reputation_score,
        reputation_tier: getReputationTierFromScore(agent.value.reputation_score),
        last_updated: null
      }
      reputationFor.value = agentDid.value
    }
  } finally {
    reputationLoading.value = false
  }
}

function getReputationTierFromScore(score: number): string {
  if (score >= 90) return 'Gold'
  if (score >= 70) return 'Silver'
  if (score >= 40) return 'Bronze'
  if (score > 0) return 'Iron'
  return 'Unranked'
}

// ─── Agent Logs (REAL — GET /agents/{did}/logs) ───
async function loadLogs() {
  logsLoading.value = true
  try {
    const params: any = { limit: 50, offset: 0 }
    if (logsFilter.value !== 'all') {
      params.level = logsFilter.value.toUpperCase()
    }
    const response = await apiClient.get(`/agents/${encodeURIComponent(agentDid.value)}/logs`, { params })
    agentLogs.value = response.data || []
  } catch (error) {
    console.error('Failed to load agent logs:', error)
    agentLogs.value = []
  } finally {
    logsLoading.value = false
  }
}

function getLogLevelClass(level: string): string {
  switch (level?.toUpperCase()) {
    case 'ERROR': return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
    case 'WARN': return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200'
    case 'INFO': return 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200'
    case 'DEBUG': return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
    default: return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
  }
}

// ─── Export (REAL — legitimate functionality) ───
function exportAgent() {
  const exportData = {
    agent: agent.value,
    agentCard: agentCard.value || null,
    skills: skills.value,
    metrics: metricsFailed.value ? null : performanceMetrics.value,   // never the placeholder zeros of a failed read
    reputation: reputation.value,
    exported_at: new Date().toISOString()
  }

  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-${agentDid.value.replace(/:/g, '_')}.json`
  a.click()
  URL.revokeObjectURL(url)

  uiStore.showSuccess('Export Complete', 'Agent profile exported successfully')
}

// ─── Lifecycle ───
onMounted(() => {
  loadAgentProfile()
})

watch(() => route.params.did, () => {
  if (route.params.did) {
    loadAgentProfile()
  }
})
</script>

<template>
  <div class="ap">
    <!-- ── Loading ─────────────────────────────────────────── -->
    <div v-if="isLoading" class="ap-loading">
      <div class="ap-load-hero">
        <SkeletonLoader variant="stat" />
      </div>
      <div class="ap-load-grid">
        <SkeletonLoader variant="card" />
        <SkeletonLoader variant="card" />
        <SkeletonLoader variant="card" />
      </div>
    </div>

    <!-- ── Profile ─────────────────────────────────────────── -->
    <div v-else-if="agent" class="ap-shell">

      <!-- ═══ HERO HEADER ═══ -->
      <header class="ap-hero" :class="`ap-hero--${agent.status || 'unknown'}`">
        <div class="ap-hero-decor" aria-hidden="true"></div>
        <div class="ap-hero-inner">
          <div class="ap-id">
            <!-- the agent as its owner dressed it: its picture, its ring and its overlay (agentvault2-56, 2026-10-23; the
                 page drew a letter where Discovery's agent view drew SYBIL's panopticon) -->
            <div class="ap-avatar" :class="{ 'ap-avatar--worn': heroUser }" data-testid="ap-hero-avatar">
              <UserAvatar v-if="heroUser" :user="heroUser" :avatar-url="heroAvatarUrl" :display-name="agent.name" size="lg" />
              <span v-else class="ap-avatar-glyph">{{ agent.name?.charAt(0) || '?' }}</span>
            </div>
            <div class="ap-id-main">
              <div class="ap-name-row">
                <h1 class="ap-name">{{ agent.name || t('agentDetailsView.unnamed') }}</h1>
                <FlareBadge
                  v-if="agent.flare_tier"
                  :tier="agent.flare_tier"
                  :granted-at="agent.flare_granted_at"
                  :display-name="agent.flare_display_name"
                  :tagline="agent.flare_tagline"
                  :logo-url="agent.flare_logo_url"
                  :cause="agent.flare_cause"
                  :accent-color="agent.flare_accent_color"
                  :flare-id="agent.flare_id"
                  size="md"
                  :show-label="true"
                />
                <span class="ap-status-pill" :class="`ap-status-pill--${agent.status || 'unknown'}`">
                  <span class="ap-status-dot"></span>{{ agent.status || 'unknown' }}
                </span>
              </div>
              <p class="ap-did">{{ agent.did || agent.agent_did }}</p>
              <div class="ap-meta">
                <span class="ap-meta-item">
                  <Icon name="mdi:star" class="ap-meta-ico" />
                  <span class="ap-meta-strong" :class="reputationColor">{{ repScoreText }}</span> rep
                </span>
                <span class="ap-meta-item ap-meta-tier" :class="tierBadgeClass">
                  <Icon name="award" class="ap-meta-ico" />{{ repTierText }}
                </span>
                <span v-if="performanceMetrics.last_active" class="ap-meta-item">
                  <Icon name="clock" class="ap-meta-ico" />
                  {{ t('agentProfileView.lastActive', { time: dayjs(performanceMetrics.last_active).fromNow() }) }}
                </span>
              </div>
            </div>
          </div>

          <div class="ap-actions">
            <button class="ap-btn ap-btn--ghost" @click="exportAgent">
              <Icon name="download" /> {{ t('agentProfileView.export') }}
            </button>
            <!-- CONTRACT SPINE P3: discovery "Engage" — visible when the card advertises engagement terms -->
            <button v-if="!isOwner && engagementTerms" class="ap-btn ap-btn--primary" @click="openEngage">
              <Icon name="file-text" /> Engage
            </button>
          </div>
        </div>
      </header>

      <!-- ═══ TAB NAV ═══ -->
      <nav class="ap-tabs" role="tablist" aria-label="Agent profile sections">
        <button
          v-for="tab in (['overview', 'skills', 'performance', 'reputation', 'evals', 'logs'] as const)"
          :key="tab"
          role="tab"
          :aria-selected="activeTab === tab"
          class="ap-tab"
          :class="{ 'ap-tab--active': activeTab === tab }"
          @click="activeTab = tab as any; if (tab === 'logs' && agentLogs.length === 0) loadLogs(); if (tab === 'evals' && evalResults.length === 0) loadEvals()"
        >
          {{ tab === 'evals' ? 'Evals' : t('agentProfileView.' + tab + 'Tab') }}
          <span v-if="tab === 'skills' && skills.length > 0" class="ap-tab-badge">{{ skills.length }}</span>
        </button>
        <button
          role="tab"
          :aria-selected="activeTab === 'access'"
          class="ap-tab"
          :class="{ 'ap-tab--active': activeTab === 'access' }"
          @click="activeTab = 'access'"
        >Access</button>
      </nav>

      <!-- ═══ TAB CONTENT ═══ -->
      <div class="ap-body">

        <!-- ───────── ACCESS (IRONKEY) ───────── -->
        <div v-if="activeTab === 'access'" class="ap-stack">
          <AgentAccessPanel v-if="agentDid" :agent-did="agentDid" mode="owner" />
        </div>


        <!-- ───────── OVERVIEW ───────── -->
        <div v-if="activeTab === 'overview'" class="ap-stack">
          <div class="ap-grid-3">
            <!-- Agent Details -->
            <section class="ap-card ap-span-2">
              <PanelHeader icon="mdi:robot" :title="t('agentProfileView.agentDetails')" />
              <div class="ap-detail">
                <p class="ap-detail-label">{{ t('agentProfileView.description') }}</p>
                <p class="ap-detail-desc">{{ agent.description || agentCard?.description || t('agentProfileView.noDescription') }}</p>
              </div>
              <div class="ap-detail-grid">
                <div>
                  <p class="ap-detail-label">{{ t('agentProfileView.created') }}</p>
                  <p class="ap-detail-val">{{ agent.created_at ? dayjs(agent.created_at).format('MMM D, YYYY') : '—' }}</p>
                </div>
                <div>
                  <p class="ap-detail-label">{{ t('agentProfileView.status') }}</p>
                  <p class="ap-detail-val">
                    <span class="ap-status-pill ap-status-pill--sm" :class="`ap-status-pill--${agent.status || 'unknown'}`">
                      {{ agent.status || 'unknown' }}
                    </span>
                  </p>
                </div>
                <div>
                  <p class="ap-detail-label">{{ t('agentProfileView.reputation') }}</p>
                  <p class="ap-detail-val ap-detail-val--strong" :class="reputationColor">
                    {{ repScoreText }} · {{ repTierText }}
                  </p>
                </div>
                <div>
                  <p class="ap-detail-label">{{ t('agentProfileView.type') }}</p>
                  <p class="ap-detail-val">{{ agentCard?.type || 'Autonomous' }}</p>
                </div>
              </div>
            </section>

            <!-- Quick Stats -->
            <section class="ap-card">
              <PanelHeader icon="mdi:chart-line" :title="t('agentProfileView.quickStats')" />
              <div v-if="metricsLoading"><SkeletonLoader variant="text" :rows="5" /></div>
              <ul v-else class="ap-kv">
                <!-- §FESUITE (V0575): a metrics read that failed is not 0 requests at a 0% success rate -->
                <li v-if="metricsFailed" class="ap-kv-row"><ReadFailedNotice dense :retry="loadMetrics" /></li>
                <template v-else>
                <li class="ap-kv-row">
                  <span class="ap-kv-key">{{ t('agentProfileView.totalRequests') }}</span>
                  <span class="ap-kv-val">{{ (performanceMetrics.total_requests ?? 0).toLocaleString(appLocale()) }}</span>
                </li>
                <li class="ap-kv-row">
                  <span class="ap-kv-key">{{ t('agentProfileView.successRate') }}</span>
                  <span class="ap-kv-val" :class="(performanceMetrics.success_rate ?? 0) >= 95 ? 'ap-pos' : (performanceMetrics.success_rate ?? 0) >= 80 ? 'ap-warn' : 'ap-neg'">
                    {{ (performanceMetrics.success_rate ?? 0).toFixed(1) }}%
                  </span>
                </li>
                <li class="ap-kv-row">
                  <span class="ap-kv-key">{{ t('agentProfileView.avgResponse') }}</span>
                  <span class="ap-kv-val">{{ performanceMetrics.avg_response_time ?? 0 }}ms</span>
                </li>
                <li class="ap-kv-row">
                  <span class="ap-kv-key">{{ t('agentProfileView.uptime') }}</span>
                  <span class="ap-kv-val">{{ (performanceMetrics.uptime_percentage ?? 0).toFixed(1) }}%</span>
                </li>
                </template>
                <li class="ap-kv-row">
                  <span class="ap-kv-key">{{ t('agentProfileView.reputation') }}</span>
                  <span class="ap-kv-val" :class="reputationColor">{{ repScoreText }}</span>
                </li>
              </ul>
            </section>
          </div>

          <!-- Top Skills preview -->
          <section v-if="skills.length > 0" class="ap-card">
            <PanelHeader icon="mdi:lightning-bolt" :title="t('agentProfileView.skillsTab')">
              <template #action>
                <button class="ap-link" @click="activeTab = 'skills'">{{ t('agentProfileView.viewAll') }} →</button>
              </template>
            </PanelHeader>
            <div class="ap-chips">
              <span v-for="(skill, i) in skills.slice(0, 10)" :key="`${i}:${skill.id}`" class="ap-chip">
                {{ skill.name }}
              </span>
              <span v-if="skills.length > 10" class="ap-chip ap-chip--more">+{{ skills.length - 10 }} {{ t('agentProfileView.more') }}</span>
            </div>
          </section>
        </div>

        <!-- ───────── SKILLS ───────── -->
        <div v-if="activeTab === 'skills'" class="ap-stack" data-testid="ap-skills">
          <div class="ap-sec-head">
            <h3 class="ap-sec-title">{{ t('agentProfileView.agentSkills') }}</h3>
          </div>
          <p class="ap-muted">{{ t('agentProfileView.skillsFromCard', "Skills come from the agent's own card: the agent publishes them, and the registry shows them as they stand there.") }}</p>

          <div v-if="skillsLoading"><SkeletonLoader variant="list" :rows="3" /></div>

          <p v-else-if="skillsFailed" class="ap-muted" role="status" data-testid="ap-skills-failed">
            {{ t('agentProfileView.skillsFailed', "The agent's card could not be read right now.") }}
          </p>

          <div v-else-if="skills.length > 0" class="ap-skill-grid">
            <div v-for="(skill, i) in skills" :key="`${i}:${skill.id}`" class="ap-skill-row" data-testid="ap-skill">
              <div class="ap-skill-main">
                <p class="ap-skill-name">{{ skill.name }}</p>
                <p v-if="skill.description" class="ap-skill-desc">{{ skill.description }}</p>
                <div v-if="skill.tags.length" class="ap-skill-tags">
                  <span v-for="tag in skill.tags" :key="tag" class="ap-chip ap-chip--sm">{{ tag }}</span>
                </div>
              </div>
            </div>
          </div>

          <EmptyState v-else icon="award" accent="purple" :title="t('agentProfileView.noSkills')" />
        </div>

        <!-- ───────── PERFORMANCE ───────── -->
        <div v-if="activeTab === 'performance'" class="ap-stack">
          <div class="ap-sec-head">
            <h3 class="ap-sec-title">{{ t('agentProfileView.agentMetrics') }}</h3>
            <div class="ap-range">
              <button
                v-for="range in ['1h', '24h', '7d', '30d']"
                :key="range"
                class="ap-range-btn"
                :class="{ 'ap-range-btn--active': metricsTimeRange === range }"
                @click="metricsTimeRange = range; loadMetrics()"
              >{{ rangeLabel(range) }}</button>
              <button class="ap-icon-btn ap-icon-btn--ghost" :disabled="metricsLoading" aria-label="Refresh metrics" @click="loadMetrics()">
                <Icon name="refresh-cw" :class="{ 'ap-spin': metricsLoading }" />
              </button>
            </div>
          </div>

          <ReadFailedNotice v-if="metricsFailed && !metricsLoading" :retry="loadMetrics" data-testid="ap-metrics-failed" />
          <div v-else class="ap-stat-grid">
            <StatCard
              icon="activity" accent="primary"
              :label="t('agentProfileView.totalRequests')"
              :value="(performanceMetrics.total_requests ?? 0).toLocaleString(appLocale())"
              :trend="`${(performanceMetrics.weekly_trend?.request_growth ?? 0) >= 0 ? '+' : ''}${(performanceMetrics.weekly_trend?.request_growth ?? 0).toFixed(1)}%`"
              :trend-dir="(performanceMetrics.weekly_trend?.request_growth ?? 0) >= 0 ? 'up' : 'down'"
              :loading="metricsLoading"
            />
            <StatCard
              icon="check-circle"
              :accent="(performanceMetrics.success_rate ?? 0) >= 95 ? 'success' : (performanceMetrics.success_rate ?? 0) >= 80 ? 'warning' : 'danger'"
              :label="t('agentProfileView.successRate')"
              :value="`${(performanceMetrics.success_rate ?? 0).toFixed(2)}%`"
              :loading="metricsLoading"
            />
            <StatCard
              icon="zap" accent="warning"
              :label="t('agentProfileView.avgResponseTime')"
              :value="`${performanceMetrics.avg_response_time ?? 0}ms`"
              :loading="metricsLoading"
            />
            <StatCard
              icon="mdi:server" accent="purple"
              :label="t('agentProfileView.uptime')"
              :value="`${(performanceMetrics.uptime_percentage ?? 0).toFixed(2)}%`"
              :loading="metricsLoading"
            />
          </div>

          <section v-if="!metricsFailed" class="ap-card">
            <PanelHeader icon="mdi:clock-outline" :title="t('agentProfileView.todayActivity')" />
            <div class="ap-mini-grid">
              <div class="ap-mini">
                <span class="ap-mini-val">{{ performanceMetrics.daily_stats.requests_today }}</span>
                <span class="ap-mini-lbl">{{ t('agentProfileView.requestsToday') }}</span>
              </div>
              <div class="ap-mini">
                <span class="ap-mini-val" :class="performanceMetrics.daily_stats.errors_today > 0 ? 'ap-neg' : 'ap-pos'">{{ performanceMetrics.daily_stats.errors_today }}</span>
                <span class="ap-mini-lbl">{{ t('agentProfileView.errorsToday') }}</span>
              </div>
              <div class="ap-mini">
                <span class="ap-mini-val">{{ performanceMetrics.daily_stats.unique_callers }}</span>
                <span class="ap-mini-lbl">{{ t('agentProfileView.uniqueEndpoints') }}</span>
              </div>
            </div>
          </section>
        </div>

        <!-- ───────── REPUTATION ───────── -->
        <div v-if="activeTab === 'reputation'" class="ap-grid-3">
          <section class="ap-card ap-rep-card">
            <div class="ap-sec-head ap-sec-head--tight">
              <h3 class="ap-sec-title">{{ t('agentProfileView.currentReputation') }}</h3>
              <button class="ap-icon-btn ap-icon-btn--ghost" :disabled="reputationLoading" aria-label="Refresh reputation" @click="loadReputation()">
                <Icon name="refresh-cw" :class="{ 'ap-spin': reputationLoading }" />
              </button>
            </div>
            <div class="ap-rep-score">
              <div class="ap-rep-num" :class="reputationColor">{{ repScoreText }}</div>
              <p class="ap-rep-outof">{{ t('agentProfileView.outOf100') }}</p>
              <span class="ap-tier-badge" :class="tierBadgeClass">{{ repTierText }}</span>
              <p v-if="reputation.last_updated" class="ap-rep-updated">Last updated {{ dayjs(reputation.last_updated).fromNow() }}</p>
            </div>
          </section>

          <section class="ap-card ap-span-2">
            <PanelHeader icon="mdi:shield-star-outline" :title="t('agentProfileView.reputationSystem')" />
            <p class="ap-detail-desc">{{ t('agentProfileView.reputationDesc') }}</p>
            <div class="ap-mini-grid ap-mini-grid--2">
              <div class="ap-mini ap-mini--left">
                <span class="ap-mini-lbl">{{ t('agentProfileView.tier') }}</span>
                <span class="ap-mini-val ap-mini-val--sm">{{ repTierText }}</span>
              </div>
              <div class="ap-mini ap-mini--left">
                <span class="ap-mini-lbl">{{ t('agentProfileView.score') }}</span>
                <span class="ap-mini-val ap-mini-val--sm" :class="reputationColor">{{ repScoreText }} / 100</span>
              </div>
            </div>
            <div class="ap-placeholder">
              <Icon name="mdi:trending-up" class="ap-placeholder-ico" />
              <p class="ap-placeholder-title">{{ t('agentProfileView.repHistoryViz') }}</p>
              <p class="ap-placeholder-sub">{{ t('agentProfileView.repHistoryHint') }}</p>
            </div>
          </section>
        </div>

        <!-- ───────── EVALS ───────── -->
        <div v-if="activeTab === 'evals'" class="ap-stack">
          <div class="ap-sec-head">
            <h3 class="ap-sec-title">Agent Evals</h3>
            <button class="ap-btn ap-btn--ghost ap-btn--sm" :disabled="evalsLoading" @click="loadEvals()">
              <Icon name="refresh-cw" :class="{ 'ap-spin': evalsLoading }" /> Refresh
            </button>
          </div>
          <ReadFailedNotice v-if="!evalsLoading && evalsFailed" :retry="loadEvals" />
          <p v-else-if="!evalsLoading && evalResults.length === 0 && evalsReadFor === agentDid" class="ap-muted">
            No eval results yet. Evals score this agent against published task suites; scores fold
            into reputation. (This registry may not have evals enabled.)
          </p>
          <table v-else-if="evalResults.length" class="ap-table">
            <thead>
              <tr><th>Suite</th><th>Score</th><th>Result</th><th>Latency</th><th>When</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in evalResults" :key="i">
                <td>{{ r.suite }}</td>
                <td>{{ (r.score * 100).toFixed(0) }}%</td>
                <td>
                  <span :class="r.passed ? 'ap-pill ap-pill--ok' : 'ap-pill ap-pill--bad'">
                    {{ r.passed ? 'pass' : 'fail' }}
                  </span>
                </td>
                <td>{{ r.latency_ms != null ? r.latency_ms + ' ms' : '—' }}</td>
                <td>{{ r.at ? new Date(r.at).toLocaleString(appLocale()) : '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ───────── LOGS ───────── -->
        <div v-if="activeTab === 'logs'" class="ap-stack">
          <div class="ap-sec-head">
            <h3 class="ap-sec-title">{{ t('agentProfileView.agentLogs') }}</h3>
            <div class="ap-range">
              <select :aria-label="t('agentProfileView.logLevelAria', 'Log level')" v-model="logsFilter" class="ap-select" @change="loadLogs()">
                <option value="all">{{ t('agentProfileView.allLevels') }}</option>
                <option value="error">{{ t('agentProfileView.error') }}</option>
                <option value="warn">{{ t('agentProfileView.warning') }}</option>
                <option value="info">{{ t('agentProfileView.info') }}</option>
                <option value="debug">{{ t('agentProfileView.debug') }}</option>
              </select>
              <button class="ap-btn ap-btn--ghost ap-btn--sm" :disabled="logsLoading" @click="loadLogs()">
                <Icon name="refresh-cw" :class="{ 'ap-spin': logsLoading }" /> {{ t('agentProfileView.refresh') }}
              </button>
            </div>
          </div>

          <div v-if="logsLoading && agentLogs.length === 0"><SkeletonLoader variant="list" :rows="5" /></div>

          <section v-else-if="agentLogs.length > 0" class="ap-card ap-card--flush">
            <div v-for="log in agentLogs" :key="log.id" class="ap-log-row">
              <span class="ap-log-level" :class="getLogLevelClass(log.level)">{{ log.level }}</span>
              <div class="ap-log-main">
                <p class="ap-log-msg">{{ log.message }}</p>
                <div class="ap-log-meta">
                  <span v-if="log.source">{{ log.source }}</span>
                  <span>{{ dayjs(log.timestamp).format('MMM D HH:mm:ss') }}</span>
                </div>
              </div>
            </div>
          </section>

          <EmptyState
            v-else
            icon="file-text" accent="muted"
            :title="t('agentProfileView.noLogs')"
            :subtitle="t('agentProfileView.noLogsHint')"
          />
        </div>
      </div>
    </div>

    <!-- CONTRACT SPINE P3: engage a discovered agent → private contract offer (escrow at accept) -->
    <ConfirmActionModal
      :show="showEngageModal"
      title="// ENGAGE AGENT"
      :message="engageMessage"
      tone="info"
      confirm-text="Create contract offer"
      busy-text="Creating…"
      :busy="engageBusy"
      @close="showEngageModal = false"
      @confirm="confirmEngage"
    />
  </div>
</template>

<style scoped>
/* ════════════════════════════════════════════════════════════════
   AgentProfile — AAA+ neural-command redesign (FE batch 4)
   Dark cyberpunk language via --nc-* tokens + shared UI kit.
   ════════════════════════════════════════════════════════════════ */
.ap {
  min-height: 100vh;
  color: var(--nc-text-primary, #e8eaed);
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  padding-bottom: 56px;
}
.ap-shell { display: flex; flex-direction: column; }

/* ── Loading ─── */
.ap-loading { padding: 24px; display: flex; flex-direction: column; gap: 20px; }
.ap-load-hero { max-width: 320px; }
.ap-load-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
@media (max-width: 760px) { .ap-load-grid { grid-template-columns: 1fr; } }

/* ── HERO HEADER ─── */
.ap-hero {
  position: relative; overflow: hidden;
  padding: 28px 28px 24px;
  border-bottom: 1px solid var(--nc-border-subtle, #232833);
  background:
    radial-gradient(1100px 200px at 12% -40%, rgba(var(--nc-primary-rgb), 0.12), transparent 70%),
    var(--nc-surface, #131825);
}
.ap-hero-decor {
  position: absolute; inset: 0; pointer-events: none;
  background:
    linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.04) 1px, transparent 1px) 0 0 / 32px 32px,
    linear-gradient(0deg, rgba(var(--nc-primary-rgb), 0.04) 1px, transparent 1px) 0 0 / 32px 32px;
  -webkit-mask-image: radial-gradient(640px 200px at 80% -10%, #000, transparent 75%);
          mask-image: radial-gradient(640px 200px at 80% -10%, #000, transparent 75%);
  opacity: 0.7;
}
.ap-hero::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 0.7), transparent 55%);
}
.ap-hero--suspended::before { background: linear-gradient(90deg, rgba(255,196,76,0.7), transparent 55%); }
.ap-hero--revoked::before, .ap-hero--unknown::before { background: linear-gradient(90deg, rgba(255,51,102,0.6), transparent 55%); }

.ap-hero-inner {
  position: relative; z-index: 1;
  display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; flex-wrap: wrap;
}
.ap-id { display: flex; align-items: flex-start; gap: 16px; min-width: 0; }
.ap-avatar {
  width: 72px; height: 72px; flex: 0 0 auto;
  border-radius: 16px;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(145deg, rgba(var(--nc-primary-rgb), 0.18), rgba(var(--nc-primary-rgb), 0.04));
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  box-shadow: 0 0 28px rgba(var(--nc-primary-rgb), 0.12) inset, 0 6px 22px rgba(0,0,0,0.35);
}
.ap-avatar--worn { background: none; border: 0; box-shadow: none; border-radius: 50%; overflow: visible; }
.ap-avatar-glyph {
  font-size: 30px; font-weight: 700; letter-spacing: -0.02em;
  color: var(--nc-primary, #00d2d2);
  text-shadow: 0 0 18px rgba(var(--nc-primary-rgb), 0.4);
  font-family: 'JetBrains Mono', ui-monospace, monospace;
}
.ap-id-main { min-width: 0; }
.ap-name-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.ap-name {
  margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.01em;
  color: #fff; line-height: 1.15;
}
.ap-did {
  margin: 8px 0 0; font-family: 'JetBrains Mono', ui-monospace, monospace;
  font-size: 12px; color: var(--nc-text-muted, rgba(255,255,255,0.46)); word-break: break-all; user-select: all;
}
.ap-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 18px; margin-top: 12px; }
.ap-meta-item {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12.5px; color: var(--nc-text-secondary, rgba(255,255,255,0.62));
}
.ap-meta-ico { font-size: 14px; color: var(--nc-text-muted, rgba(255,255,255,0.5)); }
.ap-meta-strong { font-weight: 700; font-variant-numeric: tabular-nums; }
.ap-meta-tier {
  padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
}

/* status pill */
.ap-status-pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 11px; border-radius: 999px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: capitalize;
  border: 1px solid; white-space: nowrap;
}
.ap-status-pill--sm { padding: 2px 9px; font-size: 10px; }
.ap-status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.ap-status-pill--active    { color: #00ff88; background: rgba(0,255,136,0.1);  border-color: rgba(0,255,136,0.28); }
.ap-status-pill--suspended { color: #ffc44c; background: rgba(255,196,76,0.1); border-color: rgba(255,196,76,0.28); }
.ap-status-pill--revoked,
.ap-status-pill--unknown   { color: #ff5b78; background: rgba(255,51,102,0.1); border-color: rgba(255,51,102,0.28); }

/* actions */
.ap-actions { display: flex; gap: 10px; flex-shrink: 0; }
.ap-btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 9px 15px; border-radius: 8px; cursor: pointer;
  font-family: inherit; font-size: 12.5px; font-weight: 600; letter-spacing: 0.02em;
  border: 1px solid; transition: background .18s, border-color .18s, transform .18s, box-shadow .18s;
}
.ap-btn:hover { transform: translateY(-1px); }
.ap-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.ap-btn--sm { padding: 7px 12px; font-size: 12px; }
.ap-btn--ghost {
  color: var(--nc-text-secondary, rgba(255,255,255,0.7)); background: rgba(255,255,255,0.03);
  border-color: var(--nc-border-subtle, #232833);
}
.ap-btn--ghost:hover { border-color: rgba(var(--nc-primary-rgb), 0.4); color: #fff; background: rgba(var(--nc-primary-rgb), 0.06); }
.ap-btn--primary {
  color: #060a12; background: var(--nc-primary, #00d2d2); border-color: var(--nc-primary, #00d2d2);
}
.ap-btn--primary:hover { box-shadow: 0 8px 24px rgba(var(--nc-primary-rgb), 0.3); }

/* ── TAB NAV ─── */
.ap-tabs {
  display: flex; gap: 4px; padding: 0 28px;
  border-bottom: 1px solid var(--nc-border-subtle, #232833);
  overflow-x: auto; scrollbar-width: none;
  position: sticky; top: 0; z-index: 5;
  background: var(--nc-dark, #0e1220);
}
.ap-tabs::-webkit-scrollbar { display: none; }
.ap-tab {
  position: relative; flex: 0 0 auto;
  background: transparent; border: 0; cursor: pointer;
  padding: 14px 8px; margin: 0 8px;
  font-family: inherit; font-size: 13px; font-weight: 600; letter-spacing: 0.02em;
  color: var(--nc-text-muted, rgba(255,255,255,0.45));
  transition: color .18s; white-space: nowrap;
  display: inline-flex; align-items: center; gap: 7px;
}
.ap-tab:hover { color: var(--nc-text-secondary, rgba(255,255,255,0.75)); }
.ap-tab--active { color: var(--nc-primary, #00d2d2); }
.ap-tab--active::after {
  content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px;
  background: var(--nc-primary, #00d2d2); box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.6);
}
.ap-tab-badge {
  font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 999px;
  background: rgba(var(--nc-primary-rgb), 0.14); color: var(--nc-primary, #00d2d2);
}

/* ── BODY ─── */
.ap-body { padding: 24px 28px; }
.ap-stack { display: flex; flex-direction: column; gap: 18px; }
/* the evals tab: its empty line, its table and its pass/fail pills named classes no rule defined, so a pass and a
   fail drew alike */
.ap-muted { margin: 0; font-size: 13px; line-height: 1.5; color: var(--nc-text-muted, #94a3b8); }
.ap-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ap-table th {
  text-align: left; padding: 8px 10px; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--nc-text-muted, #94a3b8); border-bottom: 1px solid var(--nc-border-subtle, #232833);
}
.ap-table td { padding: 8px 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.08); font-variant-numeric: tabular-nums; }
.ap-pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px; font-weight: 600; border: 1px solid transparent; }
.ap-pill--ok { color: #34d399; border-color: rgba(52, 211, 153, 0.45); background: rgba(52, 211, 153, 0.1); }
.ap-pill--bad { color: #f87171; border-color: rgba(248, 113, 113, 0.45); background: rgba(248, 113, 113, 0.08); }
.ap-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; }
.ap-span-2 { grid-column: span 2; }
@media (max-width: 900px) {
  .ap-grid-3 { grid-template-columns: 1fr; }
  .ap-span-2 { grid-column: auto; }
}

/* card */
.ap-card {
  background: var(--nc-surface, #131825);
  border: 1px solid var(--nc-border-subtle, #232833);
  border-radius: 12px;
  padding: 18px 20px;
  transition: border-color .2s, box-shadow .2s;
}
.ap-card:hover { border-color: rgba(var(--nc-primary-rgb), 0.22); }
.ap-card--flush { padding: 6px 4px; }

/* PanelHeader text lives in default slot; nudge spacing under it */
.ap-card :deep(.ph) { padding-bottom: 14px; }

/* detail block */
.ap-detail { margin-bottom: 16px; }
.ap-detail-label {
  margin: 0 0 4px; font-size: 10.5px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--nc-text-muted, rgba(255,255,255,0.42));
}
.ap-detail-desc { margin: 0; font-size: 13.5px; line-height: 1.6; color: var(--nc-text-secondary, rgba(255,255,255,0.7)); }
.ap-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.ap-detail-val { margin: 0; font-size: 14px; color: var(--nc-text-primary, #e8eaed); }
.ap-detail-val--strong { font-weight: 700; }

/* key-value list (quick stats) */
.ap-kv { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.ap-kv-row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 10px 0; border-bottom: 1px dashed var(--nc-border-subtle, #232833);
}
.ap-kv-row:last-child { border-bottom: none; }
.ap-kv-key { font-size: 12.5px; color: var(--nc-text-secondary, rgba(255,255,255,0.6)); }
.ap-kv-val { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--nc-text-primary, #e8eaed); }
.ap-pos { color: #00ff88; }
.ap-warn { color: #ffc44c; }
.ap-neg { color: #ff5b78; }

/* section head (tabs) */
.ap-sec-head { display: flex; align-items: center; justify-content: space-between; gap: 14px; flex-wrap: wrap; }
.ap-sec-head--tight { margin-bottom: 4px; }
.ap-sec-title { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: 0.01em; color: #fff; }
.ap-link {
  background: none; border: 0; cursor: pointer; font-family: inherit;
  font-size: 12px; font-weight: 600; color: var(--nc-primary, #00d2d2);
}
.ap-link:hover { text-decoration: underline; }

/* chips */
.ap-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
.ap-chip {
  padding: 5px 11px; border-radius: 999px; font-size: 12px; font-weight: 500;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.07); color: var(--nc-text-secondary, rgba(255,255,255,0.75));
}
.ap-chip--sm { padding: 2px 9px; font-size: 10.5px; display: inline-block; margin-top: 6px; }
.ap-chip--more { color: var(--nc-text-muted, rgba(255,255,255,0.5)); }

/* skills grid */
.ap-skill-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 620px) { .ap-skill-grid { grid-template-columns: 1fr; } }
.ap-skill-row {
  display: flex; align-items: center; justify-content: space-between; gap: 10px;
  padding: 11px 13px; border-radius: 9px;
  background: rgba(255,255,255,0.02); border: 1px solid var(--nc-border-subtle, #232833);
}
.ap-skill-name { margin: 0; font-size: 13px; font-weight: 600; color: var(--nc-text-primary, #e8eaed); }
.ap-skill-main { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.ap-skill-desc { margin: 0; font-size: 12px; line-height: 1.45; color: var(--nc-text-secondary, rgba(255,255,255,0.75)); }
.ap-skill-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.ap-skill-tags .ap-chip--sm { margin-top: 0; }
.ap-icon-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 7px; cursor: pointer;
  background: rgba(255,51,102,0.08); border: 1px solid rgba(255,51,102,0.2); color: #ff5b78;
  transition: background .15s, border-color .15s;
}
.ap-icon-btn:hover { background: rgba(255,51,102,0.16); border-color: rgba(255,51,102,0.4); }
.ap-icon-btn--ghost {
  background: rgba(255,255,255,0.03); border-color: var(--nc-border-subtle, #232833); color: var(--nc-text-secondary, rgba(255,255,255,0.7));
}
.ap-icon-btn--ghost:hover { border-color: rgba(var(--nc-primary-rgb), 0.4); color: var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb), 0.06); }

/* range / filter controls */
.ap-range { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ap-range-btn {
  padding: 6px 12px; border-radius: 7px; cursor: pointer; font-family: inherit; font-size: 12px; font-weight: 600;
  background: rgba(255,255,255,0.02); border: 1px solid var(--nc-border-subtle, #232833); color: var(--nc-text-muted, rgba(255,255,255,0.5));
  transition: border-color .15s, color .15s, background .15s;
}
.ap-range-btn:hover { color: var(--nc-text-secondary, rgba(255,255,255,0.75)); border-color: var(--nc-border, #2c3340); }
.ap-range-btn--active { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb), 0.45); background: rgba(var(--nc-primary-rgb), 0.08); }
.ap-select {
  padding: 7px 12px; border-radius: 7px; font-family: inherit; font-size: 12.5px; cursor: pointer;
  background: var(--nc-surface, #131825); border: 1px solid var(--nc-border-subtle, #232833); color: var(--nc-text-primary, #e8eaed);
}
.ap-select:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.5); }

/* stat grid */
.ap-stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
@media (max-width: 900px) { .ap-stat-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .ap-stat-grid { grid-template-columns: 1fr; } }

/* mini tiles */
.ap-mini-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.ap-mini-grid--2 { grid-template-columns: 1fr 1fr; margin: 14px 0; }
@media (max-width: 560px) { .ap-mini-grid { grid-template-columns: 1fr; } }
.ap-mini {
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  padding: 16px 12px; border-radius: 10px;
  background: rgba(255,255,255,0.02); border: 1px solid var(--nc-border-subtle, #232833);
}
.ap-mini--left { align-items: flex-start; }
.ap-mini-val { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; color: var(--nc-text-primary, #e8eaed); }
.ap-mini-val--sm { font-size: 15px; }
.ap-mini-lbl { font-size: 11px; letter-spacing: 0.04em; color: var(--nc-text-muted, rgba(255,255,255,0.46)); }

/* reputation card */
.ap-rep-card { display: flex; flex-direction: column; }
.ap-rep-score { text-align: center; padding: 14px 0 4px; }
.ap-rep-num {
  font-size: 56px; font-weight: 800; line-height: 1; font-variant-numeric: tabular-nums;
  text-shadow: 0 0 30px rgba(var(--nc-primary-rgb), 0.18);
}
.ap-rep-outof { margin: 8px 0 0; font-size: 12px; color: var(--nc-text-muted, rgba(255,255,255,0.46)); }
.ap-tier-badge { display: inline-block; margin-top: 12px; padding: 5px 14px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.ap-rep-updated { margin: 12px 0 0; font-size: 11px; color: var(--nc-text-muted, rgba(255,255,255,0.4)); }

/* history placeholder */
.ap-placeholder {
  margin-top: 14px; text-align: center; padding: 26px 16px; border-radius: 10px;
  background: rgba(255,255,255,0.015); border: 1px dashed var(--nc-border-subtle, #232833);
}
.ap-placeholder-ico { font-size: 34px; color: rgba(var(--nc-primary-rgb), 0.55); }
.ap-placeholder-title { margin: 10px 0 2px; font-size: 13px; font-weight: 600; color: var(--nc-text-secondary, rgba(255,255,255,0.62)); }
.ap-placeholder-sub { margin: 0; font-size: 12px; color: var(--nc-text-muted, rgba(255,255,255,0.4)); }

/* logs */
.ap-log-row {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 11px 16px; border-bottom: 1px solid var(--nc-border-subtle, #232833);
}
.ap-log-row:last-child { border-bottom: none; }
.ap-log-level {
  flex: 0 0 auto; margin-top: 1px; padding: 2px 8px; border-radius: 5px;
  font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 10.5px; font-weight: 700;
}
.ap-log-main { min-width: 0; flex: 1; }
.ap-log-msg { margin: 0; font-size: 13px; color: var(--nc-text-primary, #e8eaed); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ap-log-meta { display: flex; gap: 14px; margin-top: 3px; font-size: 11px; color: var(--nc-text-muted, rgba(255,255,255,0.4)); }

/* modal form */
.ap-form { display: flex; flex-direction: column; gap: 14px; }
.ap-field { display: flex; flex-direction: column; gap: 6px; }
.ap-field-label { font-size: 12px; font-weight: 600; color: var(--nc-text-secondary, rgba(255,255,255,0.7)); }
.ap-input {
  width: 100%; padding: 9px 12px; border-radius: 8px; font-family: inherit; font-size: 13px;
  background: var(--nc-dark, #0e1220); border: 1px solid var(--nc-border-subtle, #232833); color: var(--nc-text-primary, #e8eaed);
}
.ap-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb), 0.5); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.1); }
.ap-form-actions { display: flex; justify-content: flex-end; gap: 10px; padding-top: 6px; }

/* spinner */
.ap-spin :deep(svg) { animation: ap-spin 0.9s linear infinite; }
@keyframes ap-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .ap-spin :deep(svg) { animation: none; } }

/* responsive header */
@media (max-width: 640px) {
  .ap-hero { padding: 22px 18px 20px; }
  .ap-tabs { padding: 0 18px; }
  .ap-body { padding: 20px 18px; }
  .ap-actions { width: 100%; }
  .ap-actions .ap-btn { flex: 1; justify-content: center; }
  .ap-avatar { width: 60px; height: 60px; }
  .ap-name { font-size: 21px; }
  .ap-detail-grid { grid-template-columns: 1fr; }
}
</style>
