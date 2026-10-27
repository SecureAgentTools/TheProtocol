<template>
  <div class="at-page">
    <!-- Ambient layer — same visual DNA as landing page -->
    <div class="at-ambient">
      <div class="at-grid"></div>
      <div class="at-scan"></div>
      <div class="at-glow at-glow-1"></div>
      <div class="at-glow at-glow-2"></div>
    </div>

    <!-- Tab bar. The chained and dual-frame lifecycle tabs are retired with the Frame-A-era provisioner tests
         (§NIGHTLYPROV, 2026-09-27); provisioning is tested nightly on a throwaway pair instead. -->
    <div class="at-tabbar">
      <button
        class="at-tab"
        :class="{ 'at-tab-active': currentTab === 'endpoints' }"
        @click="currentTab = 'endpoints'"
      >
        <NeuralIcon name="flask" :size="16" class="inline-block mr-1" />
        {{ t('apiTesterContainerView.tabs.endpoints') }}
      </button>
    </div>

    <!-- §MCPTEST-FE: the last run published to the server archive. Shown
         whenever results were restored from disk rather than produced in this
         tab, so a completed sweep is never invisible again. -->
    <div v-if="archivedRunSummary && currentTab === 'endpoints'" class="at-lastrun">
      <span class="at-lastrun-tag">LAST RUN</span>
      <span class="at-lastrun-stat at-ok">{{ archivedRunSummary.passed }} pass</span>
      <span class="at-lastrun-stat at-bad">{{ archivedRunSummary.failed }} fail</span>
      <span class="at-lastrun-stat at-ef">{{ archivedRunSummary.expected_failures }} expected</span>
      <span class="at-lastrun-stat">{{ archivedRunSummary.real_pass_rate }}% real pass</span>
      <span class="at-lastrun-meta">
        {{ archivedRunSummary.total_measured }} measured
        <template v-if="archivedRunSummary.status"> · {{ archivedRunSummary.status }}</template>
        <template v-if="archivedRunSummary.updated_at"> · {{ archivedRunSummary.updated_at }}</template>
      </span>
    </div>

    <ReadFailedNotice v-if="endpointsFailed && currentTab === 'endpoints'" data-testid="at-endpoints-unread"
      :text="t('apiTesterContainerView.endpointsUnread', 'The endpoint list could not be read just now.')"
      :retry="loadEndpointList" />
    <ApiTesterDisplay
      v-else-if="currentTab === 'endpoints'"
      :endpoints="engine.endpointsData.value"
      :selected-category="selectedCategory"
      :testing-category="testingAll"
      :running-all-tests="runningAllTests"
      :developer-token="developerToken"
      :agent-token="agentToken"
      :agent-status="agentStatus"
      :sandbox-active="sandboxActive"
      :sandbox-credentials="sandboxCredentials"
      :resetting-sandbox="resettingSandbox"
      @select-category="selectCategory"
      @test-endpoint="testEndpoint"
      @test-category="testAllInCategory"
      @test-visual-group="testVisualGroup"
      @run-all-tests="runAllTests"
      @download-results="downloadResults"
      @toggle-request="toggleRequest"
      @toggle-response="toggleResponse"
      @reset-sandbox="resetSandbox"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import ApiTesterDisplay from '@/components/ApiTesterDisplay.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ApiTestEngine, type Endpoint, KNOWN_EF_ENDPOINTS } from '@/services/ApiTesterLogic'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
import { apiTesterService } from '@/services/apiTester'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('ApiTesterContainer')

// Tab state: 'endpoints' (the BFF loop). The 'chained' and 'dual' lifecycle tabs are retired (§NIGHTLYPROV).
const currentTab = ref<'endpoints'>('endpoints')

// Stores
const uiStore = useUIStore()
const authStore = useAuthStore()

// Create test engine instance
const engine = new ApiTestEngine()

// State - exact same as original
const developerToken = ref('')
const agentToken = ref('')
const agentTokenAutoFilled = ref(false)
const agentStatus = ref('')
const selectedCategory = ref<string | null>(null)
const testingAll = ref(false)
const runningAllTests = ref(false)
// §MCPTEST-FE: summary of the last run published to the server archive.
const archivedRunSummary = ref<Record<string, any> | null>(null)
const currentTestingCategory = ref<string | null>(null)

// OWL29: Sandbox state
const sandboxActive = ref(false)
const sandboxCredentials = ref<any>(null)
const resettingSandbox = ref(false)

// Computed - exact same as original
const categories = computed(() => Object.keys(engine.endpointsData.value))
const currentEndpoints = computed(() => 
  selectedCategory.value ? engine.endpointsData.value[selectedCategory.value] : []
)

const hasAnyResults = computed(() => 
  Object.values(engine.endpointsData.value).some(endpoints => 
    endpoints.some(ep => ep.result)
  )
)

// §SUITES1018: a row the server did not call (not_measured) is not "tested" and never a failure.
const totalTested = computed(() => 
  Object.values(engine.endpointsData.value).reduce((sum, endpoints) => 
    sum + endpoints.filter(ep => ep.result && !ep.result.not_measured).length, 0
  )
)

const totalHealthy = computed(() => 
  Object.values(engine.endpointsData.value).reduce((sum, endpoints) => 
    sum + endpoints.filter(ep => ep.result?.healthy).length, 0
  )
)

const totalUnhealthy = computed(() => totalTested.value - totalHealthy.value)

const successRate = computed(() => 
  totalTested.value > 0 
    ? Math.round((totalHealthy.value / totalTested.value) * 100)
    : 0
)

// Methods - exact same as original
function selectCategory(category: string) {
  selectedCategory.value = category
}

async function testEndpoint(endpoint: Endpoint) {
  try {
    const result = await engine.testEndpoint(endpoint, developerToken.value, agentToken.value)
    
    if (result.healthy) {
      uiStore.showSuccess('Test Passed', `${endpoint.method} ${endpoint.path}`)
    } else {
      uiStore.showWarning('Test Failed', `${endpoint.method} ${endpoint.path}: ${result.error}`)
    }
  } catch (error: any) {
    uiStore.showError('Test Error', error.message)
  }
}

async function testAllInCategory() {
  if (!selectedCategory.value) return
  
  testingAll.value = true
  
  try {
    const endpoints = engine.endpointsData.value[selectedCategory.value]
    const result = await engine.testCategory(selectedCategory.value, endpoints, developerToken.value, agentToken.value)
    
    uiStore.showInfo(
      'Category Test Complete', 
      `${result.healthy}/${result.total} endpoints healthy (${Math.round((result.healthy / result.total * 100))}%)`
    )
  } catch (error: any) {
    uiStore.showError('Test Failed', error.message)
  } finally {
    testingAll.value = false
  }
}

async function testVisualGroup(categories: string[]) {
  testingAll.value = true
  
  try {
    let totalHealthy = 0
    let totalEndpoints = 0
    
    // Test each category in the visual group
    for (const category of categories) {
      if (engine.endpointsData.value[category]) {
        const endpoints = engine.endpointsData.value[category]
        const result = await engine.testCategory(category, endpoints, developerToken.value, agentToken.value)
        
        totalHealthy += result.healthy
        totalEndpoints += result.total
        
        // Show progress after each category
        uiStore.showInfo(
          'Testing Visual Group', 
          `Completed ${category}: ${result.healthy}/${result.total} healthy`
        )
      }
    }
    
    // Show final results
    const successRate = totalEndpoints > 0 ? Math.round((totalHealthy / totalEndpoints) * 100) : 0
    uiStore.showSuccess(
      'Visual Group Test Complete', 
      `${totalHealthy}/${totalEndpoints} endpoints healthy (${successRate}%)`
    )
  } catch (error: any) {
    uiStore.showError('Test Failed', error.message)
  } finally {
    testingAll.value = false
  }
}

async function runAllTests() {
  runningAllTests.value = true
  
  try {
    await engine.runAllTests(developerToken.value, agentToken.value)
    
    uiStore.showSuccess(
      'All Tests Complete', 
      `${totalHealthy.value}/${totalTested.value} endpoints healthy (${successRate.value}%)`
    )
  } catch (error: any) {
    uiStore.showError('Test Run Failed', error.message)
  } finally {
    runningAllTests.value = false
  }
}

function downloadResults() {
  // Collect all test results - exact same as original
  const results: any = {
    timestamp: new Date().toISOString(),
    summary: {
      totalEndpoints: Object.values(engine.endpointsData.value).reduce((sum, eps) => sum + eps.length, 0),
      totalTested: totalTested.value,
      totalHealthy: totalHealthy.value,
      totalExpectedFailures: Object.values(engine.endpointsData.value).reduce((sum, endpoints) =>
        sum + endpoints.filter(ep =>
          // 2026-04-25 — Honor backend result.expected_failure flag in addition to
          // the hardcoded KNOWN_EF_ENDPOINTS set. Backend EF rules cover ~10 paths
          // (state-dep prereqs, intentional 501s, peer-slug quirks) that the
          // frontend set didn't list — counting them as "failures" overstated the
          // problem on download/summary.
          // §SUITES1018: the server stamps an expected failure healthy:true, so it is counted whatever `healthy` says
          !!ep.result && !ep.result.not_measured &&
          (ep.result.expected_failure === true || (!ep.result.healthy && KNOWN_EF_ENDPOINTS.has(`${ep.method} ${ep.path}`)))
        ).length, 0),
      totalFailed: Object.values(engine.endpointsData.value).reduce((sum, endpoints) =>
        sum + endpoints.filter(ep =>
          !!ep.result && !ep.result.healthy && !ep.result.not_measured &&
          !(ep.result.expected_failure === true || KNOWN_EF_ENDPOINTS.has(`${ep.method} ${ep.path}`))
        ).length, 0),
      totalNotMeasured: Object.values(engine.endpointsData.value).reduce((sum, endpoints) =>
        sum + endpoints.filter(ep => !!ep.result?.not_measured).length, 0),
      successRate: successRate.value
    },
    tokens: {
      developerToken: developerToken.value ? 'Present' : 'Missing',
      agentToken: agentToken.value ? 'Present' : 'Missing'
    },
    categories: {}
  }
  
  // Organize results by category
  Object.entries(engine.endpointsData.value).forEach(([category, endpoints]) => {
    results.categories[category] = {
      totalEndpoints: endpoints.length,
      tested: endpoints.filter(ep => ep.result).length,
      healthy: endpoints.filter(ep => ep.result?.healthy).length,
      failed: endpoints.filter(ep => ep.result && !ep.result.healthy && !ep.result.not_measured).length,
      not_measured: endpoints.filter(ep => ep.result?.not_measured).length,
      endpoints: endpoints.map(ep => ({
        method: ep.method,
        path: ep.path,
        auth: ep.auth,
        description: ep.description,
        tested: !!ep.result,
        result: ep.result ? {
          healthy: ep.result.healthy,
          not_measured: ep.result.not_measured === true,
          not_measured_reason: ep.result.not_measured_reason ?? null,
          statusCode: ep.result.statusCode,
          responseTime: ep.result.responseTime,
          error: ep.result.error,
          responseData: ep.result.responseData,
          timestamp: ep.result.timestamp
        } : null,
        requestBody: ep.requestBody ? (typeof ep.requestBody === 'string' ? JSON.parse(ep.requestBody) : ep.requestBody) : null
      }))
    }
  })
  
  // Create download
  const blob = new Blob([JSON.stringify(results, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `api-test-results-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
  
  uiStore.showSuccess('Download Complete', 'Test results saved to file')
}

function toggleResponse(endpoint: Endpoint) {
  endpoint.showResponse = !endpoint.showResponse
}

function toggleRequest(endpoint: Endpoint) {
  endpoint.showRequest = !endpoint.showRequest
  
  // Initialize request body if showing for first time
  if (endpoint.showRequest && !endpoint.requestBody) {
    const defaultBody = engine.findDefaultBody(endpoint.path)
    if (defaultBody) {
      endpoint.requestBody = JSON.stringify(defaultBody, null, 2)
    }
  }
}

// OWL29: Sandbox methods
async function fetchSandboxCredentials() {
  try {
    const creds = await apiTesterService.getSandboxCredentials()
    if (creds && creds.sandbox_active) {
      sandboxActive.value = true
      sandboxCredentials.value = creds
      import.meta.env.DEV && console.log('🧪 Sandbox mode active — tests target isolated DB')
    } else {
      sandboxActive.value = false
      sandboxCredentials.value = null
      import.meta.env.DEV && console.log('Sandbox not active — tests target production DB')
    }
  } catch (error) {
    log.warn('Could not fetch sandbox credentials:', error)
    sandboxActive.value = false
  }
}

async function resetSandbox() {
  if (resettingSandbox.value) return
  resettingSandbox.value = true
  try {
    const result = await apiTesterService.resetSandbox()
    uiStore.showSuccess('Sandbox Reset', result.message || 'Database wiped and re-seeded')
    // Re-fetch credentials (they stay the same, but confirms sandbox is alive)
    await fetchSandboxCredentials()
  } catch (error: any) {
    uiStore.showError('Reset Failed', error.response?.data?.detail || error.message)
  } finally {
    resettingSandbox.value = false
  }
}

// Watch for auth store changes - exact same as original
watch(() => authStore.agentToken, (newToken) => {
  if (newToken && !agentToken.value) {
    agentToken.value = newToken
    agentTokenAutoFilled.value = true
    agentStatus.value = ' (auto-filled from active agent)'
    import.meta.env.DEV && console.log('Auto-filled agent token from auth store')
  }
})

watch(() => authStore.activeAgent, (newAgent) => {
  if (newAgent) {
    const agentName = newAgent.name || newAgent.did.slice(0, 20) + '...'
    // Remove 'Hardcoded' from display - unprofessional
    const cleanName = agentName.replace(' (Hardcoded)', '')
    agentStatus.value = ` (${cleanName})`
  } else {
    agentStatus.value = ''
  }
})

async function ensureAgentAuthentication() {
  // Only for developers/admins - exact same as original
  if (!authStore.isDeveloper && !authStore.isAdmin) {
    import.meta.env.DEV && console.log('User is not developer/admin - skipping agent auth')
    return
  }
  
  import.meta.env.DEV && console.log('Ensuring marketplace agent authentication...')
  
  // Force fetch agents (which will use hardcoded marketplace agent)
  await authStore.fetchAvailableAgents()
  
  // Update agent token if available
  if (authStore.agentToken) {
    agentToken.value = authStore.agentToken
    agentTokenAutoFilled.value = true
    import.meta.env.DEV && console.log('Agent token updated from auth store')
  }
}

onMounted(async () => {
  // Give auth system time to fully initialize
  await new Promise(resolve => setTimeout(resolve, 1000))
  
  // Auto-fill developer token
  developerToken.value = authStore.token || ''
  
  // Ensure agent authentication
  await ensureAgentAuthentication()
  
  // OWL29: Fetch sandbox status
  await fetchSandboxCredentials()
  
  // Load endpoints
  await loadEndpointList()
})

// §FESUITE (2026-10-10): the endpoint list is this page's own read. A failed read rejected the page's mount, and the
// console's error boundary turned it into "Oops! Something went wrong" over the whole console, still shown once the
// registry was back (sweeps/recovery on V0589). It now says the list could not be read where the list would be, and
// reads it again on Try again.
const endpointsFailed = ref(false)
async function loadEndpointList() {
  endpointsFailed.value = false
  try {
    await engine.loadEndpoints()
  } catch (e) {
    log.warn('reading the endpoint list failed:', e)
    endpointsFailed.value = true
    return
  }

  // §MCPTEST-FE 2026-08-07: hydrate the last published run. Without this the
  // page always opened blank and a completed sweep was invisible to anyone who
  // had not personally watched it run.
  archivedRunSummary.value = await engine.loadLatestRun()

  // Select first category if none selected
  if (!selectedCategory.value && categories.value.length > 0) {
    selectedCategory.value = categories.value[0]
  }
}

</script>

<style scoped>
/* ─── Page shell ─── */
.at-page {
  position: relative;
  min-height: 100vh;
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints. */
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  overflow-x: hidden;
  z-index: 1;
}

/* ─── Ambient layer (identical DNA to LandingPage) ─── */
.at-ambient {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

/* Dot grid */
.at-grid {
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.12) 1px, transparent 1px);
  background-size: 32px 32px;
  /* §DESKCHROME 2026-08-28: grid is STATIC — perpetual drift removed (Commander) */
}

/* Scan beam */
.at-scan {
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.45), transparent);
  box-shadow: 0 0 18px 4px rgba(var(--nc-primary-rgb), 0.18);
  animation: at-scan-beam 12s linear infinite;
}
@keyframes at-scan-beam {
  0%   { top: -2px;   opacity: 0; }
  5%   { opacity: 1; }
  95%  { opacity: 1; }
  100% { top: 100vh; opacity: 0; }
}

/* Radial glows */
.at-glow {
  position: absolute;
  border-radius: 50%;
  opacity: 0.18;
}
.at-glow-1 {
  width: 600px; height: 600px;
  top: -120px; left: -120px;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.55), transparent 70%);
  animation: at-glow-pulse 8s ease-in-out infinite alternate;
}
.at-glow-2 {
  width: 500px; height: 500px;
  bottom: 10%; right: -80px;
  background: radial-gradient(circle, rgba(0, 120, 200, 0.45), transparent 70%);
  animation: at-glow-pulse 11s ease-in-out infinite alternate-reverse;
}
@keyframes at-glow-pulse {
  0%   { opacity: 0.12; }
  100% { opacity: 0.22; }
}

/* Tab bar — lives above the main ApiTesterDisplay */
/* §MCPTEST-FE — restored-run banner */
.at-lastrun {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  margin: 0 0 0.75rem;
  padding: 0.5rem 0.9rem;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid #2d3748;
  border-left: 3px solid #22d3ee;
  border-radius: 6px;
  font-size: 0.82rem;
  color: #cbd5e1;
}
.at-lastrun-tag {
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #22d3ee;
  font-size: 0.72rem;
}
.at-lastrun-stat { font-variant-numeric: tabular-nums; }
.at-lastrun-stat.at-ok { color: #4ade80; }
.at-lastrun-stat.at-bad { color: #f87171; }
.at-lastrun-stat.at-ef { color: #fbbf24; }
.at-lastrun-meta { margin-left: auto; color: #64748b; font-size: 0.75rem; }

.at-tabbar {
  position: relative;
  z-index: 2;
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1.2rem 0;
  margin-bottom: 0.5rem;
}
.at-tab {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 1.1rem;
  background: rgba(15, 23, 42, 0.55);
  border: 1px solid #2d3748;
  border-bottom: none;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
  color: #a0aec0;
  font-size: 0.9rem;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
  font-family: inherit;
}
.at-tab:hover {
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.75);
}
.at-tab-active {
  color: #4f9cf9;
  background: rgba(15, 23, 42, 0.85);
  border-color: #4f9cf9;
  box-shadow: 0 -2px 8px -2px rgba(79, 156, 249, 0.3);
}
</style>
