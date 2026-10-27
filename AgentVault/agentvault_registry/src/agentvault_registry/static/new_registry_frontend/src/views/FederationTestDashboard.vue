<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { useAlive } from '@/composables/useAlive'
import { registryConfigWithin } from '@/composables/useRegistryConfig'

const { t } = useI18n()

/** §FESUITE (2026-10-10, the operator batch): this page reads the sandbox through /sandbox/a. Where the registry says
 *  its proxy reaches no sandbox registry A (registry-config `sandbox_proxy`, every cloud operator), nothing is asked
 *  there, and neither the production health nor the local sync stands in for it: the page says so. An older registry
 *  (no field) asks as before. */
const noSandbox = ref(false)
async function sandboxHere(): Promise<boolean> {
  const sp = (await registryConfigWithin()).sandbox_proxy
  noSandbox.value = Array.isArray(sp) && !sp.includes('a')
  return !noSandbox.value
}

// ── Types ────────────────────────────────────────────────────
interface Operator {
  name: string
  status: 'healthy' | 'down' | 'pending'
  ms: number
  group: string
}

interface TestResult {
  name: string
  passed: boolean
  duration_ms: number
  details: string
  eventstore_verified: boolean
}

interface TierResult {
  tier: string
  tier_number: number
  passed: number
  failed: number
  total: number
  duration_ms: number
  tests: TestResult[]
}

interface FederationResults {
  tiers: Record<string, TierResult>
  total_passed: number
  total_failed: number
  total_tests: number
  duration_ms: number
  timestamp: string
}

// ── State ────────────────────────────────────────────────────
const operators = ref<Operator[]>([])
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const opsRead = ref(false)
const testResults = ref<FederationResults | null>(null)
const running = ref(false)
const syncing = ref(false)
const expandedTiers = ref<Set<string>>(new Set())
const lastSyncTime = ref<Date | null>(null)
const supplyDelta = ref<string>('—')
const eventCoverage = ref<string>('—')
let healthPoll: ReturnType<typeof setInterval> | null = null

// ── Computed ─────────────────────────────────────────────────
const operatorCount = computed(() => {
  const healthy = operators.value.filter(o => o.status === 'healthy').length
  return { healthy, total: operators.value.length }
})

const testCount = computed(() => {
  if (!testResults.value) return { passed: 0, total: 0 }
  return { passed: testResults.value.total_passed, total: testResults.value.total_tests }
})

const lastSyncAgo = computed(() => {
  if (!lastSyncTime.value) return '—'
  const s = Math.round((Date.now() - lastSyncTime.value.getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  return `${Math.floor(s / 60)}m ago`
})

const tierList = computed((): TierResult[] => {
  if (!testResults.value) return []
  return Object.values(testResults.value.tiers).sort((a, b) => a.tier_number - b.tier_number)
})

// ── API ──────────────────────────────────────────────────────
async function fetchHealth() {
  if (!(await sandboxHere())) return
  try {
    // Fetch from sandbox registry (via proxy) — shows sandbox operators only
    const res = await apiClient.get('/sandbox/a/api/v1/stack-health')
    const allOps = (res.data.services || []).filter((s: any) => s.group === 'operator')
    // Filter to sandbox operators only (exclude production operators that leak via BFS)
    const sandboxOps = allOps.filter((o: any) => {
      const n = (o.name || '').toLowerCase()
      return n.includes('sandbox') || n.includes('registry-test') || n.includes('registry test')
    })
    operators.value = (sandboxOps.length > 0 ? sandboxOps : allOps.slice(0, 10)).map((o: any) => ({
      name: o.name,
      status: o.status === 'healthy' ? 'healthy' : 'down',
      ms: o.ms || 0,
      group: o.group,
    }))
    opsRead.value = true
  } catch {
    // Fallback to production health if sandbox proxy unavailable
    try {
      const res = await apiClient.get('/stack-health')
      const ops = (res.data.services || []).filter((s: any) => s.group === 'operator')
      operators.value = ops.map((o: any) => ({
        name: o.name,
        status: o.status === 'healthy' ? 'healthy' : 'down',
        ms: o.ms || 0,
        group: o.group,
      }))
      opsRead.value = true
    } catch { /* silent */ }
  }
}

async function runAllTiers() {
  running.value = true
  testResults.value = null
  expandedTiers.value.clear()
  try {
    const res = await apiClient.post('/admin/api-test/test-federation', { tier: 'all' })
    testResults.value = res.data
    // Auto-expand tiers with failures
    for (const [key, tier] of Object.entries(res.data.tiers || {})) {
      if ((tier as TierResult).failed > 0) expandedTiers.value.add(key)
    }
  } catch (e: any) {
    console.error('Federation test failed:', e)
  }
  running.value = false
}

async function runSingleTier(tier: string) {
  running.value = true
  try {
    const res = await apiClient.post('/admin/api-test/test-federation', { tier })
    if (!testResults.value) testResults.value = res.data
    else {
      testResults.value.tiers = { ...testResults.value.tiers, ...res.data.tiers }
      testResults.value.total_passed = Object.values(testResults.value.tiers).reduce((s, t) => s + t.passed, 0)
      testResults.value.total_failed = Object.values(testResults.value.tiers).reduce((s, t) => s + t.failed, 0)
      testResults.value.total_tests = testResults.value.total_passed + testResults.value.total_failed
    }
    expandedTiers.value.add(tier)
  } catch { /* silent */ }
  running.value = false
}

async function triggerSync() {
  if (!(await sandboxHere())) return
  syncing.value = true
  try {
    await apiClient.post('/sandbox/a/api/v1/federation/sync/trigger', { cascade: true })
    lastSyncTime.value = new Date()
    await fetchHealth()
  } catch {
    // Fallback to production sync if sandbox proxy unavailable
    try {
      await apiClient.post('/federation/sync/trigger', { cascade: true })
      lastSyncTime.value = new Date()
    } catch { /* silent */ }
  }
  syncing.value = false
}

function toggleTier(key: string) {
  if (expandedTiers.value.has(key)) expandedTiers.value.delete(key)
  else expandedTiers.value.add(key)
}

function tierIcon(tier: string): string {
  const map: Record<string, string> = {
    sync: '🔄', transfers: '💸', disputes: '⚖️',
    governance: '🏛️', a2a: '🤝', supply_integrity: '📊',
  }
  return map[tier] || '🧪'
}

function downloadResults() {
  if (!testResults.value) return
  const blob = new Blob([JSON.stringify(testResults.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = `federation-test-${new Date().toISOString().slice(0, 10)}.json`
  a.click(); URL.revokeObjectURL(url)
}

// ── Lifecycle ────────────────────────────────────────────────
// §FESUITE (the leave sweep): a page left during its first read starts no poll when it lands
const alive = useAlive()
onMounted(async () => {
  await fetchHealth()
  if (!alive() || noSandbox.value) return
  healthPoll = setInterval(fetchHealth, 30000)
})
onUnmounted(() => { if (healthPoll) clearInterval(healthPoll) })
</script>

<template>
  <div class="ft-page">
    <!-- ═══ HEADER ═══ -->
    <div class="ft-header">
      <div class="ft-header-icon"><Icon name="mdi:web" /></div>
      <div>
        <h1 class="ft-title">{{ t('federationTestView.title') }}</h1>
        <p class="ft-subtitle">{{ t('federationTestView.subtitle') }}</p>
      </div>
    </div>

    <!-- ═══ SUMMARY STATS ═══ -->
    <div class="ft-stats">
      <div class="ft-stat" :class="operatorCount.healthy === operatorCount.total && operatorCount.total > 0 ? 'ft-stat-ok' : 'ft-stat-warn'">
        <div class="ft-stat-val">{{ opsRead ? `${operatorCount.healthy}/${operatorCount.total}` : '—' }}</div>
        <div class="ft-stat-label">{{ t('federationTestView.stats.operatorsOnline') }}</div>
      </div>
      <div class="ft-stat" :class="testCount.total > 0 && testCount.passed === testCount.total ? 'ft-stat-ok' : testCount.total > 0 ? 'ft-stat-warn' : ''">
        <div class="ft-stat-val">{{ testCount.passed }}/{{ testCount.total || '—' }}</div>
        <div class="ft-stat-label">{{ t('federationTestView.stats.testsPassing') }}</div>
      </div>
      <div class="ft-stat">
        <div class="ft-stat-val">{{ lastSyncAgo }}</div>
        <div class="ft-stat-label">{{ t('federationTestView.stats.lastSync') }}</div>
      </div>
      <div class="ft-stat">
        <div class="ft-stat-val">{{ supplyDelta }}</div>
        <div class="ft-stat-label">{{ t('federationTestView.stats.supplyDelta') }}</div>
      </div>
      <div class="ft-stat">
        <div class="ft-stat-val">{{ eventCoverage }}</div>
        <div class="ft-stat-label">{{ t('federationTestView.stats.eventCoverage') }}</div>
      </div>
    </div>

    <!-- ═══ OPERATORS GRID ═══ -->
    <div class="ft-section">
      <div class="ft-section-head">
        <span class="ft-section-title">{{ t('federationTestView.sections.operators') }}</span>
        <span class="ft-section-count">{{ opsRead ? operators.length : '—' }} {{ t('federationTestView.sections.peers') }}</span>
      </div>
      <p v-if="noSandbox" class="ft-no-sandbox" data-testid="ft-no-sandbox">
        {{ t('federationTestView.noSandbox', 'No sandbox registry is connected to this registry, so there are no sandbox operators to show and no sandbox to sync.') }}
      </p>
      <div v-else class="ft-ops-grid">
        <div v-for="op in operators" :key="op.name" class="ft-op-card"
             :class="op.status === 'healthy' ? 'ft-op-up' : 'ft-op-down'">
          <div class="ft-op-dot" :class="op.status === 'healthy' ? 'ft-dot-up' : 'ft-dot-down'"></div>
          <span class="ft-op-name">{{ op.name }}</span>
          <span class="ft-op-ms">{{ op.ms }}ms</span>
        </div>
        <div v-if="!operators.length" class="ft-op-empty">{{ t('federationTestView.sections.loadingOps') }}</div>
      </div>
    </div>

    <!-- ═══ TEST ACTIONS ═══ -->
    <div class="ft-actions">
      <button class="ft-btn ft-btn-primary" @click="runAllTiers" :disabled="running">
        <span v-if="running" class="ft-spin">⟳</span>
        <span v-else>▶</span>
        {{ running ? t('federationTestView.actions.running') : t('federationTestView.actions.runAll') }}
      </button>
      <button class="ft-btn ft-btn-sync" @click="triggerSync" :disabled="syncing || noSandbox">
        <span :class="syncing ? 'ft-spin' : ''">↻</span>
        {{ syncing ? t('federationTestView.actions.syncing') : t('federationTestView.actions.triggerSync') }}
      </button>
      <button class="ft-btn ft-btn-secondary" @click="downloadResults" :disabled="!testResults">
        {{ t('federationTestView.actions.download') }}
      </button>
    </div>

    <!-- ═══ TIER RESULTS ═══ -->
    <div class="ft-section" v-if="tierList.length || running">
      <div class="ft-section-head">
        <span class="ft-section-title">{{ t('federationTestView.sections.results') }}</span>
        <span class="ft-section-count" v-if="testResults">
          {{ testResults.total_passed }}/{{ testResults.total_tests }} in {{ (testResults.duration_ms / 1000).toFixed(1) }}s
        </span>
      </div>

      <div v-if="running && !tierList.length" class="ft-running-msg">
        {{ t('federationTestView.runningMsg') }}
      </div>

      <div class="ft-tiers">
        <div v-for="tier in tierList" :key="tier.tier" class="ft-tier"
             :class="tier.failed === 0 ? 'ft-tier-ok' : 'ft-tier-fail'">
          <div class="ft-tier-head" @click="toggleTier(tier.tier)">
            <span class="ft-tier-icon">{{ tierIcon(tier.tier) }}</span>
            <span class="ft-tier-name">Tier {{ tier.tier_number }}: {{ tier.tier }}</span>
            <span class="ft-tier-badge" :class="tier.failed === 0 ? 'ft-badge-ok' : 'ft-badge-fail'">
              {{ tier.passed }}/{{ tier.total }}
              <template v-if="tier.failed === 0"> {{ t('federationTestView.perfect') }}</template>
            </span>
            <span class="ft-tier-ms">{{ tier.duration_ms < 1000 ? tier.duration_ms + 'ms' : (tier.duration_ms / 1000).toFixed(1) + 's' }}</span>
            <span class="ft-tier-chevron" :class="expandedTiers.has(tier.tier) ? 'ft-chevron-open' : ''">▸</span>
          </div>

          <Transition name="ft-expand">
            <div v-if="expandedTiers.has(tier.tier)" class="ft-tier-tests">
              <div v-for="test in tier.tests" :key="test.name" class="ft-test"
                   :class="test.passed ? 'ft-test-pass' : 'ft-test-fail'">
                <span class="ft-test-dot" :class="test.passed ? 'ft-dot-up' : 'ft-dot-down'"></span>
                <span class="ft-test-name">{{ test.name }}</span>
                <span v-if="test.eventstore_verified" class="ft-es-badge">ES</span>
                <span class="ft-test-ms">{{ test.duration_ms }}ms</span>
              </div>
            </div>
          </Transition>
        </div>
      </div>
    </div>

    <!-- ═══ INDIVIDUAL TIER BUTTONS ═══ -->
    <div class="ft-section">
      <div class="ft-section-head">
        <span class="ft-section-title">{{ t('federationTestView.sections.individualTier') }}</span>
      </div>
      <div class="ft-tier-btns">
        <button v-for="key in ['sync', 'transfers', 'disputes', 'governance', 'a2a', 'supply_integrity']"
                :key="key" class="ft-btn ft-btn-tier" @click="runSingleTier(key)" :disabled="running">
          {{ t('federationTestView.tiers.' + key) }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ft-no-sandbox { margin: 0.4rem 0 0; color: var(--nc-text-secondary, #94a3b8); font-size: 0.85rem; }
/* ── Page ──────────────────────────────────────────────────── */
.ft-page {
  padding: 1.5rem 2rem;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  color: rgba(255,255,255,0.85);
  min-height: 100vh;
}

/* ── Header ───────────────────────────────────────────────── */
.ft-header {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
}
.ft-header-icon { font-size: 2rem; }
.ft-title {
  font-size: 0.85rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.8);
  margin: 0;
}
.ft-subtitle {
  font-size: 0.7rem;
  color: rgba(255,255,255,0.5);
  margin: 0.25rem 0 0;
  letter-spacing: 0.05em;
}

/* ── Summary Stats ────────────────────────────────────────── */
.ft-stats {
  display: flex;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}
.ft-stat {
  flex: 1;
  background: #0a0e18;
  border: 1px solid rgba(var(--nc-primary-rgb),0.08);
  border-radius: 6px;
  padding: 0.75rem;
  text-align: center;
  transition: border-color 0.2s;
}
.ft-stat-ok { border-left: 2px solid #00c853; }
.ft-stat-warn { border-left: 2px solid #ff9100; }
.ft-stat-val {
  font-size: 1.1rem;
  font-weight: 700;
  color: #e0ecf4;
}
/* §FESUITE: the page's text whites 0.15-0.3 -> 0.47-0.5 alpha (4.8-5.3:1, were 2.6:1 at best) and its primary
   text 0.4-0.5 -> 0.65-0.7 (4.9-5.5:1 in the neural theme, were 2.5:1); the tier chevron is a glyph and keeps its tone. */
.ft-stat-label {
  font-size: 0.5rem;
  letter-spacing: 0.15em;
  color: rgba(255,255,255,0.5);
  margin-top: 0.3rem;
}

/* ── Section ──────────────────────────────────────────────── */
.ft-section {
  margin-bottom: 1.5rem;
}
.ft-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.75rem;
}
.ft-section-title {
  font-size: 0.55rem;
  font-weight: 600;
  letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.7);
}
.ft-section-count {
  font-size: 0.65rem;
  color: rgba(255,255,255,0.5);
}

/* ── Operators Grid ───────────────────────────────────────── */
.ft-ops-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 0.5rem;
}
.ft-op-card {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: #0a0e18;
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-radius: 5px;
  padding: 0.5rem 0.75rem;
  transition: all 0.15s;
}
.ft-op-card:hover { border-color: rgba(var(--nc-primary-rgb),0.15); }
.ft-op-up { border-left: 2px solid #00c853; }
.ft-op-down { border-left: 2px solid #ff1744; }
.ft-op-dot {
  width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}
.ft-dot-up { background: #00c853; box-shadow: 0 0 6px rgba(0,200,83,0.4); }
.ft-dot-down { background: #ff1744; box-shadow: 0 0 6px rgba(255,23,68,0.4); }
.ft-op-name {
  font-size: 0.65rem;
  font-weight: 600;
  color: #c8d8e8;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ft-op-ms {
  font-size: 0.6rem;
  color: rgba(var(--nc-primary-rgb),0.65);
}
.ft-op-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 1.5rem;
  font-size: 0.7rem;
  color: rgba(255,255,255,0.47);
}

/* ── Actions ──────────────────────────────────────────────── */
.ft-actions {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}
.ft-btn {
  font-family: inherit;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  border-radius: 5px;
  padding: 0.5rem 1rem;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.ft-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ft-btn-primary {
  background: rgba(var(--nc-primary-rgb),0.1);
  color: var(--nc-primary);
  border-color: rgba(var(--nc-primary-rgb),0.3);
}
.ft-btn-primary:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.15); border-color: var(--nc-primary); }
.ft-btn-sync {
  background: transparent;
  color: rgba(var(--nc-primary-rgb),0.6);
}
.ft-btn-sync:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb),0.06); }
.ft-btn-secondary {
  background: transparent;
  color: rgba(255,255,255,0.52);
  border-color: rgba(255,255,255,0.1);
}
.ft-btn-secondary:hover:not(:disabled) { color: rgba(255,255,255,0.6); border-color: rgba(255,255,255,0.2); }
.ft-btn-tier {
  background: #0a0e18;
  color: rgba(255,255,255,0.5);
  border-color: rgba(var(--nc-primary-rgb),0.08);
  font-size: 0.6rem;
}
.ft-btn-tier:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb),0.2); color: rgba(255,255,255,0.7); }
.ft-tier-btns { display: flex; flex-wrap: wrap; gap: 0.4rem; }

.ft-spin { display: inline-block; animation: ft-spin 1s linear infinite; }
@keyframes ft-spin { to { transform: rotate(360deg); } }

/* ── Running Message ──────────────────────────────────────── */
.ft-running-msg {
  text-align: center;
  padding: 2rem;
  font-size: 0.75rem;
  color: rgba(var(--nc-primary-rgb),0.7);
  animation: ft-pulse 2s ease-in-out infinite;
}
@keyframes ft-pulse { 0%,100% { opacity: 0.5; } 50% { opacity: 1; } }

/* ── Tiers ────────────────────────────────────────────────── */
.ft-tiers { display: flex; flex-direction: column; gap: 2px; }
.ft-tier {
  background: #0a0e18;
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-radius: 5px;
  overflow: hidden;
  transition: border-color 0.15s;
}
.ft-tier:hover { border-color: rgba(var(--nc-primary-rgb),0.12); }
.ft-tier-ok { border-left: 2px solid #00c853; }
.ft-tier-fail { border-left: 2px solid #ff9100; }

.ft-tier-head {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.75rem;
  cursor: pointer;
  user-select: none;
}
.ft-tier-head:hover { background: rgba(var(--nc-primary-rgb),0.02); }
.ft-tier-icon { font-size: 0.85rem; }
.ft-tier-name {
  font-size: 0.7rem;
  font-weight: 600;
  color: #c8d8e8;
  text-transform: capitalize;
  flex: 1;
}
.ft-tier-badge {
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 0.15rem 0.5rem;
  border-radius: 3px;
}
.ft-badge-ok { background: rgba(0,200,83,0.1); color: #00c853; }
.ft-badge-fail { background: rgba(255,145,0,0.1); color: #ff9100; }
.ft-tier-ms {
  font-size: 0.6rem;
  color: rgba(255,255,255,0.47);
}
.ft-tier-chevron {
  font-size: 0.7rem;
  color: rgba(255,255,255,0.2);
  transition: transform 0.15s;
}
.ft-chevron-open { transform: rotate(90deg); }

/* ── Tests ────────────────────────────────────────────────── */
.ft-tier-tests {
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.04);
  padding: 0.25rem 0;
}
.ft-test {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.75rem 0.35rem 2rem;
  font-size: 0.65rem;
  transition: background 0.1s;
}
.ft-test:hover { background: rgba(var(--nc-primary-rgb),0.02); }
.ft-test-pass { }
.ft-test-fail { background: rgba(255,23,68,0.02); }
.ft-test-dot {
  width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0;
}
.ft-test-name {
  color: rgba(255,255,255,0.6);
  flex: 1;
}
.ft-es-badge {
  font-size: 0.45rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  padding: 0.1rem 0.3rem;
  border-radius: 2px;
  background: rgba(var(--nc-primary-rgb),0.1);
  color: rgba(var(--nc-primary-rgb),0.6);
}
.ft-test-ms {
  font-size: 0.6rem;
  color: rgba(255,255,255,0.47);
  min-width: 50px;
  text-align: right;
}

/* ── Transitions ──────────────────────────────────────────── */
.ft-expand-enter-active { transition: all 0.2s ease; }
.ft-expand-leave-active { transition: all 0.15s ease; }
.ft-expand-enter-from, .ft-expand-leave-to { opacity: 0; max-height: 0; }
.ft-expand-enter-to, .ft-expand-leave-from { opacity: 1; max-height: 500px; }

/* ── Responsive ───────────────────────────────────────────── */
@media (max-width: 768px) {
  .ft-stats { flex-wrap: wrap; }
  .ft-stat { min-width: calc(50% - 0.5rem); }
  .ft-ops-grid { grid-template-columns: repeat(2, 1fr); }
  .ft-actions { flex-wrap: wrap; }
}
</style>
