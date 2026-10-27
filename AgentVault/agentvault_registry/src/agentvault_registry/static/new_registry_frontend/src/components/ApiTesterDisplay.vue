<template>
  <div class="api-tester-display glass-container">
    <!-- Animated Header -->
    <div class="api-header animated-gradient">
      <div class="header-content">
        <h1 class="glass-text text-cyan-400">
          <NeuralIcon name="flask" :size="36" class="inline-block mr-2" />
          API Testing Suite
        </h1>
        <p class="subtitle shimmer">Stateful Prerequisite-Aware BFF Test Orchestrator over a Containerized Shadow Registry</p>
      </div>
      <div class="header-particles"></div>
    </div>

    <!-- OWL29: Sandbox Status Banner -->
    <div v-if="sandboxActive" class="sandbox-banner glass-card">
      <div class="sandbox-banner-content">
        <div class="sandbox-info">
          <NeuralIcon name="test-tube" :size="28" class="sandbox-icon inline-block" />
          <div class="sandbox-text">
            <strong class="sandbox-title">SANDBOX MODE</strong>
            <span class="sandbox-description">All tests run against an isolated database. No production data will be affected.</span>
          </div>
        </div>
        <div class="sandbox-actions">
          <button
            @click="$emit('reset-sandbox')"
            class="reset-sandbox-button glass-button"
            :disabled="resettingSandbox"
          >
            <NeuralIcon :name="resettingSandbox ? 'refresh' : 'refresh-cw'" :size="16" class="inline-block mr-1" />
            <span>{{ resettingSandbox ? 'Resetting...' : 'Reset Sandbox' }}</span>
          </button>
        </div>
      </div>
      <!-- Phase 13: technical sandbox architecture explainer (replaced raw cred emails) -->
      <div class="sandbox-architecture">
        <div class="arch-cell">
          <NeuralIcon name="database" :size="18" class="arch-icon inline-block" />
          <div class="arch-body">
            <span class="arch-label">Isolation</span>
            <span class="arch-value">Postgres <code>agentvault_registry_test</code> + <code>event_store_test</code> — fully isolated from prod</span>
          </div>
        </div>
        <div class="arch-cell">
          <NeuralIcon name="refresh" :size="18" class="arch-icon inline-block" />
          <div class="arch-body">
            <span class="arch-label">Seeding</span>
            <span class="arch-value">Dev + agent tokens auto-bootstrapped via <code>get_sandbox_tokens()</code>, cached in Redis DB 2</span>
          </div>
        </div>
        <div class="arch-cell">
          <NeuralIcon name="shuffle" :size="18" class="arch-icon inline-block" />
          <div class="arch-body">
            <span class="arch-label">Orchestration</span>
            <span class="arch-value">BFF dispatches <code>POST /admin/api-test/test-endpoint</code>; stateful prereqs (org, team, agent, funding) auto-satisfied</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Authentication Configuration -->
    <div class="auth-section glass-card hover-lift">
      <div class="section-header">
        <h3 class="section-title">
          <NeuralIcon name="lock" :size="24" class="inline-block" />
          Authentication Configuration
        </h3>
      </div>
      <div class="auth-grid">
        <div class="auth-field glass-inner">
          <label class="field-label">Developer Token</label>
          <div class="token-display">
            <code class="token-value" :class="{ 'has-value': developerToken }">{{ developerToken ? (devTokenRevealed ? developerToken : maskToken(developerToken)) : '—' }}</code>
            <div class="token-actions">
              <button
                v-if="developerToken"
                @click="devTokenRevealed = !devTokenRevealed"
                class="token-action-btn glass-button-mini"
                :title="devTokenRevealed ? 'Hide token' : 'Reveal token'"
              >
                <NeuralIcon :name="devTokenRevealed ? 'hide' : 'view'" :size="14" class="inline-block" />
              </button>
              <button
                v-if="developerToken"
                @click="copyToken(developerToken, 'dev')"
                class="token-action-btn glass-button-mini"
                :title="devTokenCopied ? 'Copied!' : 'Copy to clipboard'"
              >
                <NeuralIcon :name="devTokenCopied ? 'check-circle' : 'copy'" :size="14" class="inline-block" />
              </button>
              <span class="token-status" :class="{ active: developerToken }">
                {{ developerToken ? 'Active' : 'Not Set' }}
              </span>
            </div>
          </div>
        </div>
        <div class="auth-field glass-inner">
          <label class="field-label">Agent Token{{ agentStatus }}</label>
          <div class="token-display">
            <code class="token-value" :class="{ 'has-value': agentToken }">{{ agentToken ? (agentTokenRevealed ? agentToken : maskToken(agentToken)) : '—' }}</code>
            <div class="token-actions">
              <button
                v-if="agentToken"
                @click="agentTokenRevealed = !agentTokenRevealed"
                class="token-action-btn glass-button-mini"
                :title="agentTokenRevealed ? 'Hide token' : 'Reveal token'"
              >
                <NeuralIcon :name="agentTokenRevealed ? 'hide' : 'view'" :size="14" class="inline-block" />
              </button>
              <button
                v-if="agentToken"
                @click="copyToken(agentToken, 'agent')"
                class="token-action-btn glass-button-mini"
                :title="agentTokenCopied ? 'Copied!' : 'Copy to clipboard'"
              >
                <NeuralIcon :name="agentTokenCopied ? 'check-circle' : 'copy'" :size="14" class="inline-block" />
              </button>
              <span class="token-status" :class="{ active: agentToken }">
                {{ agentToken ? 'Active' : 'Not Set' }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Global Actions -->
    <div class="actions-section">
      <button 
        @click="$emit('run-all-tests')" 
        class="action-button primary glass-button"
        :disabled="runningAllTests"
      >
        <NeuralIcon :name="runningAllTests ? 'refresh' : 'play'" :size="20" class="inline-block mr-2" />
        <span class="button-text">{{ runningAllTests ? 'Running All Tests...' : 'Run All Tests' }}</span>
        <span class="button-glow"></span>
      </button>
      <button 
        @click="$emit('download-results')" 
        class="action-button secondary glass-button"
        :disabled="!hasAnyResults"
      >
        <NeuralIcon name="download" :size="20" class="inline-block mr-2" />
        <span class="button-text">Download Results</span>
      </button>
    </div>

    <!-- Category Grid -->
    <div class="categories-section">
      <h3 class="section-title glass-text">
        <NeuralIcon name="folder" :size="24" class="inline-block mr-2" />
        Test Categories
      </h3>
      <div class="category-grid">
        <div
          v-for="group in visualCategories"
          :key="group.name"
          class="category-card glass-card hover-scale"
          :class="{ active: isGroupActive(group) }"
          @click="selectVisualCategory(group)"
        >
          <div class="category-icon-wrapper">
            <NeuralIcon :name="getGroupIcon(group.name)" :size="48" />
            <div class="icon-glow"></div>
          </div>
          <h4 class="category-name">{{ group.name }}</h4>
          <p class="category-description">{{ group.description }}</p>
          <div class="category-stats">
            <span class="stat-badge glass-badge">
              {{ getCategoryStats(group) }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Selected Category Tests -->
    <transition name="slide-fade">
      <div v-if="selectedVisualGroup" class="endpoints-section glass-card">
        <div class="endpoints-header">
          <h3 class="endpoints-title">
            <NeuralIcon :name="getGroupIcon(selectedVisualGroup.name)" :size="24" class="inline-block mr-2" />
            {{ selectedVisualGroup.name }}
          </h3>
          <button
            @click="testVisualCategory"
            class="test-category-button glass-button"
            :disabled="testingCategory"
          >
            {{ testingCategory ? 'Testing...' : 'Test All' }}
          </button>
        </div>

        <div class="endpoints-grid">
          <div
            v-for="endpoint in currentVisualEndpoints"
            :key="`${endpoint.method}-${endpoint.path}`"
            class="endpoint-card glass-inner"
            :class="{
              'is-testing': endpoint.testing,
              'is-success': endpoint.result?.healthy,
              'is-unmeasured': endpoint.result?.not_measured,
              'is-error': endpoint.result && !endpoint.result.healthy && !endpoint.result.not_measured
            }"
          >
            <!-- Endpoint Header -->
            <div class="endpoint-header">
              <div class="endpoint-info">
                <span class="method-badge" :class="endpoint.method.toLowerCase()">
                  {{ endpoint.method }}
                </span>
                <code class="endpoint-path">{{ endpoint.path }}</code>
              </div>
              <button
                @click="$emit('test-endpoint', endpoint)"
                class="test-button glass-button-small"
                :disabled="endpoint.testing"
              >
                <NeuralIcon :name="getTestIconName(endpoint)" :size="18" class="inline-block" />
              </button>
            </div>

            <!-- Endpoint Details -->
            <div class="endpoint-details">
              <p class="endpoint-description">{{ endpoint.description }}</p>
              <div class="endpoint-meta">
                <span class="auth-badge" :class="endpoint.auth">
                  <NeuralIcon :name="getAuthIconName(endpoint.auth)" :size="14" class="inline-block mr-1" />
                  {{ endpoint.auth }}
                </span>
              </div>
            </div>

            <!-- Request Body -->
            <div v-if="shouldShowRequestBody(endpoint)" class="request-section">
              <button
                @click="$emit('toggle-request', endpoint)"
                class="toggle-button glass-button-mini"
              >
                {{ endpoint.showRequest ? 'Hide Body' : 'Show Body' }}
              </button>
              <div v-if="endpoint.showRequest && endpoint.requestBody" class="request-body-display">
                <pre class="json-display">{{ formatJson(endpoint.requestBody) }}</pre>
              </div>
            </div>

            <!-- Test Result -->
            <transition name="result-fade">
              <div v-if="endpoint.result" class="result-section">
                <div class="result-header">
                  <span class="result-status" :class="{ success: endpoint.result.healthy, unmeasured: endpoint.result.not_measured }"
                        :title="endpoint.result.not_measured_reason || undefined">
                    <NeuralIcon :name="endpoint.result.not_measured ? 'pause' : (endpoint.result.healthy ? 'check' : 'x')" :size="18" class="inline-block mr-1" />
                    {{ endpoint.result.not_measured ? 'Not measured' : (endpoint.result.healthy ? 'Success' : 'Failed') }}
                  </span>
                  <div class="result-meta">
                    <span class="response-time">{{ endpoint.result.responseTime }}ms</span>
                    <span class="status-code glass-badge">{{ endpoint.result.statusCode || 'N/A' }}</span>
                  </div>
                </div>
                <button
                  v-if="endpoint.result.responseData"
                  @click="$emit('toggle-response', endpoint)"
                  class="toggle-button glass-button-mini"
                >
                  {{ endpoint.showResponse ? 'Hide' : 'Show' }}
                </button>
                <div v-if="endpoint.showResponse && endpoint.result.responseData" class="response-display">
                  <pre class="json-display">{{ formatJson(endpoint.result.responseData) }}</pre>
                </div>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </transition>

    <!-- Summary Dashboard -->
    <transition name="fade">
      <div v-if="hasAnyResults" class="summary-section glass-card">
        <h3 class="summary-title glass-text">
          <NeuralIcon name="chart" :size="24" class="inline-block mr-2" />
          Test Summary
        </h3>
        <div class="summary-grid">
          <div class="summary-card glass-inner">
            <NeuralIcon name="clipboard" :size="32" class="mb-2" />
            <div class="summary-value">{{ totalTested }}</div>
            <div class="summary-label">Tested</div>
          </div>
          <div class="summary-card glass-inner success-card">
            <NeuralIcon name="check-circle" :size="32" class="mb-2 text-green-500" />
            <div class="summary-value">{{ totalHealthy }}</div>
            <div class="summary-label">Passed</div>
          </div>
          <div class="summary-card glass-inner expected-card">
            <NeuralIcon name="alert-circle" :size="32" class="mb-2 text-yellow-400" />
            <div class="summary-value">{{ totalExpectedFailures }}</div>
            <div class="summary-label">Expected</div>
          </div>
          <div class="summary-card glass-inner error-card">
            <NeuralIcon name="x-circle" :size="32" class="mb-2 text-red-500" />
            <div class="summary-value">{{ totalRealFailures }}</div>
            <div class="summary-label">Failed</div>
          </div>
          <div v-if="totalNotMeasured" class="summary-card glass-inner unmeasured-card" data-testid="at-not-measured"
               title="Rows the tester did not call: a destructive or cross-frame action, a manual-only route. Each says why.">
            <NeuralIcon name="pause" :size="32" class="mb-2" />
            <div class="summary-value">{{ totalNotMeasured }}</div>
            <div class="summary-label">Not measured</div>
          </div>
          <div class="summary-card glass-inner rate-card">
            <NeuralIcon name="trending-up" :size="32" class="mb-2" />
            <div class="summary-value">{{ successRate }}%</div>
            <div class="summary-label">Success Rate</div>
            <div class="progress-ring">
              <svg viewBox="0 0 36 36">
                <path
                  class="progress-bg"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
                <path
                  class="progress-fill"
                  :stroke-dasharray="`${successRate}, 100`"
                  d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </transition>

  </div>
</template>

<script setup lang="ts">
import { groupCategories, type GroupDef } from '@/services/apiTesterGroups'
import { computed, ref } from 'vue'
import { type Endpoint, KNOWN_EF_ENDPOINTS } from '@/services/ApiTesterLogic'

// Props
const props = defineProps<{
  endpoints: Record<string, Endpoint[]>
  selectedCategory: string | null
  testingCategory: boolean
  runningAllTests: boolean
  developerToken: string
  agentToken: string
  agentStatus: string
  // OWL29: Sandbox props
  sandboxActive?: boolean
  sandboxCredentials?: any
  resettingSandbox?: boolean
}>()

// Token masking + reveal + copy state (Phase 13)
const devTokenRevealed = ref(false)
const agentTokenRevealed = ref(false)
const devTokenCopied = ref(false)
const agentTokenCopied = ref(false)

function maskToken(token: string): string {
  if (!token) return '—'
  if (token.length <= 16) return '•'.repeat(token.length)
  return `${token.slice(0, 8)}${'•'.repeat(Math.min(14, token.length - 14))}${token.slice(-6)}`
}

async function copyToken(token: string, which: 'dev' | 'agent') {
  if (!token) return
  try {
    await navigator.clipboard.writeText(token)
    if (which === 'dev') {
      devTokenCopied.value = true
      setTimeout(() => { devTokenCopied.value = false }, 1500)
    } else {
      agentTokenCopied.value = true
      setTimeout(() => { agentTokenCopied.value = false }, 1500)
    }
  } catch { /* expected */ }
}

// Visual category groupings for better organization.
// Written against endpoints_registry.py's 57 categories (audited 2026-04-22 Phase 13); the registry serves 158 by
// 2026-10, so the served catalog fills the groups now (GROUP_DEFS below, §FESUITE V0578).
// Added in Phase 13: admin_agents, admin_developers, admin_diagnostics, consul_admin, consul_admin_mutations,
// operator_lifecycle, federation_topology, frame_invitations, token_bridge, funding_requests (and sandbox_provisioner_test,
// retired with the Frame-A-era provisioner tests, §NIGHTLYPROV 2026-09-27).
// §FESUITE V0578: the curated groups; the catalog the registry serves fills them (services/apiTesterGroups.ts)
const GROUP_DEFS: GroupDef[] = [
  {
    name: 'Authentication & Security',
    icon: 'lock',
    rule: /^(authentication|two_factor_authentication|mcp_oauth|push_login|account_deletion|developer_signing_keys|docker_registry_auth|spire)$/,
    categories: ['auth', 'auth_secure', 'auth_2fa'],
    description: 'User authentication and security'
  },
  {
    name: 'Agent Management',
    icon: 'bot',
    rule: /^(agent|agents|anp_discovery|agentworld|achievements|devcard|bundles)/,
    categories: ['agents', 'agent_builder', 'agent_cards', 'agent_discovery', 'agent_logs', 'onboarding', 'agents_export_import', 'agent_cicd'],
    description: 'Create and manage agents'
  },
  {
    name: 'Units & Fees',
    icon: 'coins',
    rule: /^(staking|reputation|tokenomics|eigentrust|funding$|fiat_on_ramp$|flare_shop|membership|commons|solvency_card)/,
    categories: ['staking_enhanced', 'staking_rewards', 'enhanced_tokenomics', 'reputation_signal', 'reputation'],
    description: 'TEG units, payouts and reputation'
  },
  {
    name: 'TEG Integration',
    icon: 'plug',
    rule: /^(teg_|a2a_payment)/,
    categories: ['teg_integration', 'teg_integration_jwt_svid', 'teg_integration_mtls', 'teg_integration_oauth', 'teg_summary_enhanced', 'teg_transactions'],
    description: 'TEG ecosystem integrations'
  },
  {
    name: 'Governance',
    icon: 'landmark',
    rule: /^(governance|federation_ballots)$/,
    categories: ['governance'],
    description: 'Proposals and voting'
  },
  {
    name: 'Federation Network',
    icon: 'globe',
    rule: /^(federation|frame_|consul_federation|exchange_federation|ourchat_federation|internal_federation|registry_card|registry_health|cloud_operators|operator_)/,
    categories: ['federation_peers', 'federation_public', 'federation_query', 'federation_sync', 'federation_disputes', 'federation_topology', 'frame_invitations', 'oauth_federation', 'token_bridge'],
    description: 'Registry federation, cross-frame invitations, token bridge and OAuth'
  },
  {
    name: 'Contracts & Disputes',
    icon: 'scale',
    rule: /^(contract|disputes|attestations|the_guild|liability_cockpit_card)/,
    categories: ['contracts', 'disputes', 'disputes_enhanced', 'attestations'],
    description: 'Smart contracts and resolution'
  },
  {
    name: 'Developer Tools',
    icon: 'code',
    rule: /^(developers|webhooks|notifications|support|ourchat_chat|assistant|circuits|gödel_forge|downloads|tutorial|showcase|arena_spectator|exchange$|agora_card|phone_fabric|device_push|mcp_audit_log|legal)/,
    categories: ['developers', 'utils', 'websocket', 'funding_requests'],
    description: 'APIs, developer utilities and funding'
  },
  {
    name: 'Administration',
    icon: 'crown',
    rule: /^admin|_admin$|^enforcement|^command_center$|^ironhand_monitoring/,
    categories: ['admin', 'admin_api_test', 'admin_federation', 'admin_health', 'admin_agents', 'admin_developers', 'admin_diagnostics', 'consul_admin', 'consul_admin_mutations', 'organizations', 'enforcement_admin', 'enforcement_agent', 'operator_lifecycle'],
    description: 'Admin plane, diagnostics, enforcement lifecycle, operator mgmt'
  },
  {
    name: 'Monitoring & System',
    icon: 'activity',
    rule: /^(status|public_status|system|utilities|public|internal|sandbox_proxy|mail_relay|jurisdiction|metrics)$/,
    categories: ['metrics', 'system', 'mcp_health'],
    description: 'System metrics, monitoring and MCP health'
  },
  {
    name: 'Cross-Frame Scenarios',
    icon: 'layers',
    categories: ['multiframe_bfs', 'multiframe_eigentrust', 'multiframe_governance', 'multiframe_txstorm'],
    description: 'Multi-step flows: BFS cross-frame transfer, EigenTrust sim, governance + veto, transaction storm'
  },
  {
    name: 'Quality Gates',
    icon: 'shield-check',
    categories: [
      'flow_supply_audit',
      'flow_idempotency',
      'flow_auth_boundary',
      'flow_concurrency_safety',
      'flow_mcp_smoke',
      'flow_webhook_delivery',
      'flow_funding_request',
      'flow_coordinated_suspension',
      'flow_drift_detection',
      'flow_blocklist_enforcement',
    ],
    description: 'Invariant + boundary + consistency + integration probes (assertion-based; fails loud on real bugs)'
  }
]
const visualCategories = computed(() => groupCategories(GROUP_DEFS, props.endpoints as Record<string, unknown[]>))

// Helper function to get icon name for category groups
function getGroupIcon(groupName: string): string {
  const group = visualCategories.value.find(g => g.name === groupName)
  return group?.icon || 'folder'
}

// Get test icon name instead of emoji
function getTestIconName(endpoint: Endpoint): string {
  if (endpoint.testing) return 'refresh'
  if (endpoint.result?.healthy) return 'check-circle'
  if (endpoint.result?.not_measured) return 'pause'
  if (endpoint.result) return 'x-circle'
  return 'play'
}

// Get auth icon name instead of emoji
function getAuthIconName(auth: string): string {
  const icons: Record<string, string> = {
    none: 'unlock',
    developer: 'key',
    agent: 'bot'
  }
  return icons[auth] || 'lock'
}

// Selected visual group
const selectedVisualGroup = computed(() => {
  if (!props.selectedCategory) return null
  return visualCategories.value.find(group => 
    group.categories.includes(props.selectedCategory!)
  )
})

// Current endpoints for selected visual group
const currentVisualEndpoints = computed(() => {
  if (!selectedVisualGroup.value) return []
  
  const endpoints: Endpoint[] = []
  selectedVisualGroup.value.categories.forEach(cat => {
    if (props.endpoints[cat]) {
      endpoints.push(...props.endpoints[cat])
    }
  })
  return endpoints
})

// Stats computations
const hasAnyResults = computed(() => 
  Object.values(props.endpoints).some(endpoints => 
    endpoints.some(ep => ep.result)
  )
)

// §SUITES1018: a row the server did not call is not "tested"; it is counted on its own (totalNotMeasured).
const totalTested = computed(() => 
  Object.values(props.endpoints).reduce((sum, endpoints) => 
    sum + endpoints.filter(ep => ep.result && !ep.result.not_measured).length, 0
  )
)

const totalNotMeasured = computed(() =>
  Object.values(props.endpoints).reduce((sum, endpoints) =>
    sum + endpoints.filter(ep => ep.result?.not_measured).length, 0
  )
)

// §SUITES1018: the same split as ApiTesterLogic.runSummary(): an expected failure is counted BEFORE healthy (the
// server stamps one healthy:true, so counting healthy first called every accepted refusal a pass), and the rate is
// passed / (passed + failed), the real pass rate the archive publishes.
function isExpectedFailure(ep: Endpoint): boolean {
  if (!ep.result || ep.result.not_measured) return false
  if (ep.result.expected_failure === true) return true
  // KNOWN_EF_ENDPOINTS remains a frontend-only fallback for legacy paths the backend has not classified.
  return !ep.result.healthy && KNOWN_EF_ENDPOINTS.has(`${ep.method} ${ep.path}`)
}

const totalHealthy = computed(() => 
  Object.values(props.endpoints).reduce((sum, endpoints) => 
    sum + endpoints.filter(ep => ep.result?.healthy && !isExpectedFailure(ep)).length, 0
  )
)

const totalExpectedFailures = computed(() =>
  Object.values(props.endpoints).reduce((sum, endpoints) =>
    sum + endpoints.filter(ep => isExpectedFailure(ep)).length, 0
  )
)

const totalRealFailures = computed(() => totalTested.value - totalHealthy.value - totalExpectedFailures.value)

const successRate = computed(() => 
  (totalHealthy.value + totalRealFailures.value) > 0
    ? Math.round((totalHealthy.value / (totalHealthy.value + totalRealFailures.value)) * 100)
    : 0
)

// Helper functions
function isGroupActive(group: any): boolean {
  return group.categories.includes(props.selectedCategory || '')
}

function selectVisualCategory(group: any) {
  // Select first category in the group
  emit('select-category', group.categories[0])
}

function getCategoryStats(group: any): string {
  let total = 0
  let tested = 0
  let healthy = 0

  group.categories.forEach((cat: string) => {
    if (props.endpoints[cat]) {
      total += props.endpoints[cat].length
      props.endpoints[cat].forEach(ep => {
        if (ep.result && !ep.result.not_measured) {
          tested += 1
          if (ep.result.healthy) healthy += 1
        }
      })
    }
  })

  if (tested === 0) return `${total} endpoints`
  return `${healthy}/${tested} healthy · ${total} total`
}

function testVisualCategory() {
  // Emit all categories in the visual group, not just the selected one
  if (selectedVisualGroup.value) {
    emit('test-visual-group', selectedVisualGroup.value.categories)
  }
}

function shouldShowRequestBody(endpoint: Endpoint): boolean {
  return ['POST', 'PUT', 'PATCH'].includes(endpoint.method) && endpoint.method !== 'WS'
}


function formatJson(data: any): string {
  try {
    if (typeof data === 'string') {
      return JSON.stringify(JSON.parse(data), null, 2)
    }
    return JSON.stringify(data, null, 2)
  } catch {
    return String(data)
  }
}

function formatValue(value: any): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  if (typeof value === 'string' && value.length > 50) {
    return value.substring(0, 50) + '...'
  }
  return String(value)
}

const emit = defineEmits<{
  'select-category': [category: string]
  'test-endpoint': [endpoint: Endpoint]
  'test-category': []
  'test-visual-group': [categories: string[]]
  'run-all-tests': []
  'download-results': []
  'toggle-request': [endpoint: Endpoint]
  'toggle-response': [endpoint: Endpoint]
  'reset-sandbox': []
}>()
</script>

<style scoped>
/* ═══════════════════════════════════════════════════════════════
   API TESTER — Mission Control Terminal Theme
   Font: IBM Plex Mono | Accent: var(--nc-primary) (Cyan)
   ═══════════════════════════════════════════════════════════════ */

/* ── Base Container ── */
.glass-container {
  position: relative;
  z-index: 1;
  padding: 1rem 1.5rem;
  max-width: 1600px;
  margin: 0 auto;
  min-height: 100vh;
  background: transparent;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  color: rgba(255, 255, 255, 0.85);
  font-size: 13px;
}

.glass-card {
  background: #0a0e18;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.10);
  border-radius: 4px;
  transition: border-color 0.15s ease;
}

.glass-inner {
  background: #0e1424;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 3px;
  transition: border-color 0.15s ease;
}

.glass-text { color: var(--nc-primary); }

.glass-input {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 12px;
}

.glass-button {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: var(--nc-primary);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-weight: 600;
  font-size: 12px;
  border-radius: 3px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.glass-button:hover:not(:disabled) {
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  background: rgba(var(--nc-primary-rgb), 0.06);
}

.glass-button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── Header ── */
.api-header {
  position: relative;
  padding: 1rem 1.5rem;
  margin: -1rem -1.5rem 1rem;
  overflow: hidden;
  border-radius: 0;
}

.animated-gradient {
  background: #0a0e18;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.25);
}

.header-content {
  position: relative;
  z-index: 2;
  text-align: left;
}

.header-content h1 {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.15em;
  color: var(--nc-primary);
  text-shadow: none;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.header-particles { display: none; }

.shimmer {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.05em;
  -webkit-text-fill-color: rgba(255, 255, 255, 0.5);
  background: none;
  animation: none;
}

.subtitle { font-size: 10px; color: rgba(255, 255, 255, 0.5); }
/* §FESUITE: the tester's text whites 0.3/0.35/0.4 -> 0.48/0.5/0.52 alpha (4.9-6.0:1, were 2.7-3.8:1), same order */

/* ── Hover Effects (neutralized) ── */
.hover-lift { transition: border-color 0.15s ease; }
.hover-lift:hover { border-color: rgba(var(--nc-primary-rgb), 0.25); }

.hover-scale { transition: border-color 0.15s ease; }
.hover-scale:hover { border-color: rgba(var(--nc-primary-rgb), 0.25); }

.icon-glow { display: none; }

.pulse { animation: none; }

/* ── Auth Section ── */
.auth-section {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
}

.section-header {
  margin-bottom: 0.75rem;
}

.section-title {
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: rgba(255, 255, 255, 0.5);
}

.section-icon { font-size: 1rem; }

.auth-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.auth-field {
  padding: 0.6rem 0.75rem;
}

.field-label {
  display: block;
  margin-bottom: 0.4rem;
  color: rgba(255, 255, 255, 0.52);
  font-weight: 600;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.token-display {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.token-input {
  flex: 1;
  padding: 0.4rem 0.6rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  color: rgba(255, 255, 255, 0.6);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px;
}

.token-input.has-value {
  border-color: rgba(0, 200, 83, 0.25);
  color: rgba(0, 200, 83, 0.7);
}

/* Phase 13 — masked token display + reveal + copy */
.token-value {
  flex: 1;
  padding: 0.45rem 0.7rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  color: rgba(255, 255, 255, 0.52);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px;
  letter-spacing: 0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.token-value.has-value {
  border-color: rgba(0, 200, 83, 0.22);
  color: rgba(0, 200, 83, 0.75);
}

.token-actions {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.token-action-btn {
  padding: 0.3rem 0.5rem;
  background: rgba(0, 200, 83, 0.08);
  border: 1px solid rgba(0, 200, 83, 0.2);
  border-radius: 2px;
  color: rgba(0, 200, 83, 0.75);
  cursor: pointer;
  transition: all 180ms ease;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.token-action-btn:hover {
  background: rgba(0, 200, 83, 0.15);
  color: #00e676;
  border-color: rgba(0, 200, 83, 0.35);
}

.token-action-btn:active {
  transform: translateY(1px);
}

.token-status {
  padding: 0.2rem 0.5rem;
  border-radius: 2px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.05em;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.48);
  text-transform: uppercase;
}

.token-status.active {
  background: rgba(0, 200, 83, 0.1);
  color: #00c853;
  border: 1px solid rgba(0, 200, 83, 0.2);
}

/* ── Actions Section ── */
/* Phase 13 — sticky so user can trigger run-all after scrolling past the grid */
.actions-section {
  display: flex;
  justify-content: flex-start;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 0.6rem 0;
  background: linear-gradient(to bottom, rgba(6, 8, 16, 0.95) 0%, rgba(6, 8, 16, 0.88) 60%, rgba(6, 8, 16, 0.4) 100%);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(0, 200, 83, 0.08);
}

.action-button {
  padding: 0.5rem 1.25rem;
  border-radius: 3px;
  font-size: 12px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  border: none;
  position: relative;
  overflow: hidden;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

.action-button.primary {
  background: var(--nc-primary);
  color: #060810;
}

.action-button.primary:hover:not(:disabled) {
  background: var(--nc-primary-bright);
}

.action-button.primary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.action-button.secondary {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  color: var(--nc-primary);
}

.action-button.secondary:hover:not(:disabled) {
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  background: rgba(var(--nc-primary-rgb), 0.06);
}

.action-button.secondary:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.button-icon { font-size: 1rem; }
.button-text { white-space: nowrap; }
.button-glow { display: none; }

/* ── Category Grid ── */
.categories-section {
  margin-bottom: 1.5rem;
}

.category-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 0.5rem;
  margin-top: 0.75rem;
}

.category-card {
  padding: 0.6rem 0.75rem;
  cursor: pointer;
  position: relative;
  overflow: hidden;
  border-left: 2px solid transparent;
}

.category-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.2);
  border-left-color: rgba(var(--nc-primary-rgb), 0.3);
}

.category-card.active {
  border-color: rgba(var(--nc-primary-rgb), 0.2);
  border-left-color: var(--nc-primary);
  background: #0e1424;
}

.category-icon-wrapper {
  display: none;
}

.category-name {
  font-size: 11px;
  font-weight: 700;
  margin-bottom: 0.15rem;
  color: rgba(255, 255, 255, 0.8);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.category-description {
  display: none;
}

.category-stats {
  display: flex;
  gap: 0.25rem;
}

.stat-badge {
  padding: 0.1rem 0.4rem;
  border-radius: 2px;
  font-size: 11px;
  font-weight: 700;
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: var(--nc-primary);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

/* ── Endpoints Section ── */
.endpoints-section {
  padding: 1rem;
  margin-bottom: 1rem;
}

.endpoints-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.endpoints-title {
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--nc-primary);
}

.test-category-button {
  padding: 0.35rem 0.75rem;
  border-radius: 3px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* ── Endpoint Cards (single column list) ── */
.endpoints-grid {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.endpoint-card {
  padding: 0.6rem 0.75rem;
  position: relative;
  overflow: hidden;
  border-left: 2px solid transparent;
  border-radius: 0;
  border-top: none;
  border-right: none;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  background: transparent;
}

.endpoint-card.is-testing {
  border-left-color: #ff9100;
  background: rgba(255, 145, 0, 0.03);
  animation: pulse-border 1s ease-in-out infinite;
}

@keyframes pulse-border {
  0%, 100% { border-left-color: rgba(255, 145, 0, 0.3); }
  50% { border-left-color: #ff9100; }
}

.endpoint-card.is-success {
  border-left-color: #00c853;
  background: rgba(0, 200, 83, 0.02);
}

.endpoint-card.is-error {
  border-left-color: #ff1744;
  background: rgba(255, 23, 68, 0.02);
}

.endpoint-card.is-unmeasured {
  border-left-color: #90a4c4;
  background: rgba(120, 144, 180, 0.04);
}

/* ── Endpoint Header ── */
.endpoint-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0;
}

.endpoint-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  flex: 1;
}

.method-badge {
  padding: 2px 6px;
  border-radius: 2px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  flex-shrink: 0;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

.method-badge.get {
  background: var(--nc-primary);
  color: #060810;
}

.method-badge.post {
  background: #00c853;
  color: #060810;
}

.method-badge.put {
  background: #ff9100;
  color: #060810;
}

.method-badge.delete {
  background: #ff1744;
  color: #060810;
}

.method-badge.ws {
  background: #c084fc;
  color: #060810;
}

.method-badge.patch {
  background: #a855f7;
  color: #060810;
}

.method-badge.head,
.method-badge.options {
  background: rgba(255, 255, 255, 0.15);
  color: rgba(255, 255, 255, 0.7);
}

.endpoint-path {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.test-button {
  padding: 0.25rem 0.5rem;
  border-radius: 2px;
  font-size: 12px;
  flex-shrink: 0;
}

.glass-button-small {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  color: var(--nc-primary);
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.glass-button-small:hover:not(:disabled) {
  border-color: rgba(var(--nc-primary-rgb), 0.5);
  background: rgba(var(--nc-primary-rgb), 0.06);
}

.glass-button-small:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── Endpoint Details ── */
.endpoint-details {
  margin: 0.35rem 0 0;
}

.endpoint-description {
  color: rgba(255, 255, 255, 0.52);
  margin-bottom: 0.25rem;
  font-size: 11px;
}

.endpoint-meta {
  display: flex;
  gap: 0.5rem;
}

.auth-badge {
  padding: 1px 6px;
  border-radius: 2px;
  font-size: 10px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

.auth-badge.none {
  background: rgba(0, 200, 83, 0.1);
  color: #00c853;
}

.auth-badge.developer {
  background: rgba(255, 145, 0, 0.1);
  color: #ff9100;
}

.auth-badge.agent {
  background: rgba(var(--nc-primary-rgb), 0.1);
  color: var(--nc-primary);
}

/* ── Request Section ── */
.request-section {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.toggle-button {
  font-size: 11px;
}

.request-body-display,
.response-display {
  margin-top: 0.4rem;
}

.json-display {
  background: #080c14;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  padding: 0.5rem 0.75rem;
  overflow-x: auto;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px;
  line-height: 1.45;
  color: rgba(255, 255, 255, 0.7);
  max-height: 300px;
  overflow-y: auto;
}

.json-display::-webkit-scrollbar { width: 4px; height: 4px; }
.json-display::-webkit-scrollbar-track { background: transparent; }
.json-display::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb), 0.2); border-radius: 2px; }

.glass-button-mini {
  padding: 2px 8px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.5);
  border-radius: 2px;
  cursor: pointer;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 10px;
  transition: border-color 0.15s ease, color 0.15s ease;
}

.glass-button-mini:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.3);
  color: var(--nc-primary);
}

/* ── Result Section ── */
.result-section {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.35rem;
}

.result-status {
  font-weight: 700;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.result-status.success {
  color: #00c853;
}

.result-status.unmeasured {
  color: #90a4c4;
  font-style: italic;
}

.result-meta {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.response-time {
  color: rgba(255, 255, 255, 0.52);
  font-size: 11px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

.status-code {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 11px;
}

.glass-badge {
  padding: 1px 6px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: 2px;
  font-size: 11px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  color: rgba(255, 255, 255, 0.6);
}

/* ── Summary Section ── */
.summary-section {
  padding: 1rem;
  margin-top: 1.5rem;
}

.summary-title {
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--nc-primary);
}

.summary-grid {
  display: flex;
  gap: 0.75rem;
}

.summary-card {
  flex: 1;
  padding: 0.75rem 1rem;
  text-align: center;
  position: relative;
}

.summary-icon { display: none; }

.summary-value {
  font-size: 2rem;
  font-weight: 800;
  margin-bottom: 0.15rem;
  color: #fff;
  -webkit-text-fill-color: #fff;
  background: none;
  line-height: 1;
}

.summary-label {
  color: rgba(255, 255, 255, 0.52);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}

.success-card {
  border-left: 2px solid #00c853;
  background: rgba(0, 200, 83, 0.04);
}
.success-card .summary-value { color: #00c853; -webkit-text-fill-color: #00c853; }

.expected-card {
  border-left: 2px solid #ffd700;
  background: rgba(255, 215, 0, 0.04);
}
.expected-card .summary-value { color: #ffd700; -webkit-text-fill-color: #ffd700; }

.error-card {
  border-left: 2px solid #ff1744;
  background: rgba(255, 23, 68, 0.04);
}
.error-card .summary-value { color: #ff1744; -webkit-text-fill-color: #ff1744; }

.rate-card {
  position: relative;
  border-left: 2px solid var(--nc-primary);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.rate-card .summary-value { color: var(--nc-primary); -webkit-text-fill-color: var(--nc-primary); }

.progress-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 80px;
  height: 80px;
  pointer-events: none;
  opacity: 0.15;
}

.progress-ring svg {
  transform: rotate(-90deg);
}

.progress-bg {
  fill: none;
  stroke: rgba(255, 255, 255, 0.06);
  stroke-width: 3;
}

.progress-fill {
  fill: none;
  stroke: var(--nc-primary);
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dasharray 0.4s ease;
}

/* ── Transitions (fast) ── */
.slide-fade-enter-active,
.slide-fade-leave-active {
  transition: all 0.15s ease;
}

.slide-fade-enter-from {
  transform: translateY(8px);
  opacity: 0;
}

.slide-fade-leave-to {
  transform: translateY(-8px);
  opacity: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.result-fade-enter-active {
  transition: all 0.15s ease;
  transition-delay: 0.05s;
}

.result-fade-enter-from {
  opacity: 0;
  transform: translateY(4px);
}

/* ── Sandbox Banner ── */
.sandbox-banner {
  margin-bottom: 1rem;
  padding: 0.6rem 0.75rem;
  background: rgba(0, 200, 83, 0.03);
  border: 1px solid rgba(0, 200, 83, 0.12);
  border-left: 2px solid #00c853;
}

.sandbox-banner-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
}

.sandbox-info {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.sandbox-icon {
  font-size: 1.25rem;
}

.sandbox-text {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.sandbox-title {
  color: #00c853;
  font-size: 11px;
  letter-spacing: 0.12em;
  font-weight: 700;
}

.sandbox-description {
  color: rgba(255, 255, 255, 0.5);
  font-size: 10px;
}

.sandbox-actions { flex-shrink: 0; }

.reset-sandbox-button {
  padding: 0.3rem 0.6rem;
  border-radius: 2px;
  font-size: 10px;
  white-space: nowrap;
}

/* Legacy (unused post-Phase 13; kept for safety if other callers rely on class names) */
.sandbox-creds {
  display: flex;
  gap: 1rem;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(0, 200, 83, 0.08);
  flex-wrap: wrap;
}

/* Phase 13 — technical sandbox architecture explainer (replaces raw cred emails) */
.sandbox-architecture {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.85rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(0, 200, 83, 0.1);
}

.arch-cell {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  padding: 0.6rem 0.75rem;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(0, 200, 83, 0.12);
  border-radius: 3px;
  transition: border-color 180ms ease;
}

.arch-cell:hover {
  border-color: rgba(0, 200, 83, 0.28);
}

.arch-icon {
  color: rgba(0, 200, 83, 0.7);
  flex-shrink: 0;
  margin-top: 2px;
}

.arch-body {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.arch-label {
  color: rgba(255, 255, 255, 0.5);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 9px;
}

.arch-value {
  color: rgba(255, 255, 255, 0.78);
  font-size: 11px;
  line-height: 1.4;
}

.arch-value code {
  color: rgba(0, 230, 118, 0.85);
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  background: rgba(0, 0, 0, 0.3);
  padding: 0 3px;
  border-radius: 2px;
  font-size: 10px;
}

@media (max-width: 768px) {
  .sandbox-architecture {
    grid-template-columns: 1fr;
  }
}

/* ── Responsive ── */
@media (max-width: 1200px) {
  .category-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 900px) {
  .category-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 768px) {
  .glass-container {
    padding: 0.75rem;
  }

  .auth-grid {
    grid-template-columns: 1fr;
  }

  .category-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .summary-grid {
    flex-wrap: wrap;
  }

  .summary-card {
    min-width: 120px;
  }

  .actions-section {
    flex-direction: column;
  }
}

@media (max-width: 480px) {
  .category-grid {
    grid-template-columns: 1fr;
  }
}

/* ── Utility classes referenced by template ── */
.inline-block { display: inline-block; vertical-align: middle; }
.mr-1 { margin-right: 0.25rem; }
.mr-2 { margin-right: 0.5rem; }
.mb-2 { margin-bottom: 0.5rem; }
.text-cyan-400 { color: var(--nc-primary); }
.text-green-500 { color: #00c853; }
.text-yellow-400 { color: #ffd700; }
.text-red-500 { color: #ff1744; }

</style>
