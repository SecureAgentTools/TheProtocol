<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * AdminEvals.vue — Agent Evals control (Watchtower).
 * Suite list · create/enable · add task · run-now · latest results.
 * Wired to /admin/evals/* (admin_platform). Feature-gated by EVALS_ENABLED on
 * the registry — when off, run-now returns 409 and the list is simply empty.
 */
import { ref, onMounted } from 'vue'
import { apiClient } from '@/services/api/client'
import { useUIStore } from '@/stores/ui'
import { evalsApi, type EvalResult } from '@/services/api/evals'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Icon from '@/components/Icon.vue'

const ui = useUIStore()

interface Suite {
  id: number; key: string; name: string; task_type: string; enabled: boolean
  interval_minutes: number | null; pay_per_task: number; emit_reputation_signal: boolean
  tasks: number; next_run_at: string | null
}

const suites = ref<Suite[]>([])
/** §FESUITE (the loading sweep): 'reading' until the first answer, 'unread' if it failed (could not read is not none) */
const suitesRead = ref<'reading' | 'read' | 'unread'>('reading')
const loading = ref(false)
const busyId = ref<number | null>(null)
const selectedResults = ref<EvalResult[]>([])
const selectedKey = ref<string | null>(null)
// §FESUITE (2026-10-04): the leaderboard read now fails on anything but a 404; a suite whose results could not be
// read says so (it showed nothing before, and the rejection had no catch)
const selectedSuite = ref<Suite | null>(null)
const selectedFailed = ref(false)
function retryResults() { if (selectedSuite.value) return viewResults(selectedSuite.value) }

const form = ref({
  key: '', name: '', task_type: 'http_probe',
  interval_minutes: null as number | null, emit_reputation_signal: true,
  pay_per_task: '0', enabled: true,
})
const taskForm = ref({ name: '', scorer: 'status_ok', path: '', expected: '' })
const taskSuiteId = ref<number | null>(null)

async function load() {
  loading.value = true
  try {
    const { data } = await apiClient.get<{ suites: Suite[] }>('/admin/evals/suites')
    suites.value = data.suites ?? []
    suitesRead.value = 'read'
  } catch (e: any) {
    if (suitesRead.value !== 'read') suitesRead.value = 'unread'
    ui.showError('Evals', e?.response?.data?.detail || 'Failed to load suites')
  } finally {
    loading.value = false
  }
}

async function createSuite() {
  if (!form.value.key || !form.value.name) {
    ui.showWarning('Evals', 'Key and name are required'); return
  }
  try {
    await apiClient.post('/admin/evals/suites', {
      key: form.value.key,
      name: form.value.name,
      task_type: form.value.task_type,
      interval_minutes: form.value.interval_minutes,
      emit_reputation_signal: form.value.emit_reputation_signal,
      pay_per_task: String(form.value.pay_per_task || '0'),
      enabled: form.value.enabled,
    })
    ui.showSuccess('Evals', `Suite “${form.value.key}” saved`)
    form.value.key = ''; form.value.name = ''
    await load()
  } catch (e: any) {
    ui.showError('Evals', e?.response?.data?.detail || 'Create failed')
  }
}

async function addTask() {
  if (taskSuiteId.value == null || !taskForm.value.name) return
  const expected = taskForm.value.expected
    ? { value: taskForm.value.expected } : undefined
  try {
    await apiClient.post(`/admin/evals/suites/${taskSuiteId.value}/tasks`, {
      name: taskForm.value.name,
      scorer: taskForm.value.scorer,
      input: taskForm.value.path ? { path: taskForm.value.path } : undefined,
      expected,
    })
    ui.showSuccess('Evals', 'Task added')
    taskForm.value.name = ''; taskForm.value.path = ''; taskForm.value.expected = ''
    await load()
  } catch (e: any) {
    ui.showError('Evals', e?.response?.data?.detail || 'Add task failed')
  }
}

async function runNow(s: Suite) {
  busyId.value = s.id
  try {
    const { data } = await apiClient.post(`/admin/evals/suites/${s.id}/run`)
    ui.showSuccess('Evals', `Run ${String(data.run_id).slice(0, 8)}… completed`)
    await viewResults(s)
  } catch (e: any) {
    ui.showError('Evals', e?.response?.data?.detail || 'Run failed (is EVALS_ENABLED on?)')
  } finally {
    busyId.value = null
  }
}

async function viewResults(s: Suite) {
  selectedKey.value = s.key
  selectedSuite.value = s
  selectedFailed.value = false
  // The public leaderboard for this suite is the quickest per-suite summary.
  try {
    const entries = await evalsApi.getLeaderboard(s.key, 25)
    if (selectedKey.value !== s.key) return
    selectedResults.value = entries.map(e => ({
      run_id: '', suite: s.key, score: e.mean_score, passed: e.mean_score >= 0.5,
      latency_ms: null, error: null, at: e.last_at,
    })) as any
  } catch {
    if (selectedKey.value !== s.key) return
    selectedResults.value = []
    selectedFailed.value = true
  }
}

onMounted(load)
</script>

<template>
  <div class="ae-wrap">
    <header class="ae-head">
      <div>
        <h1 class="ae-title"><Icon icon="mdi:clipboard-check-multiple-outline" class="ae-title-icon" /> Agent Evals</h1>
        <p class="ae-sub">Scored task batteries for registered agents · results fold into reputation · <code>/admin/evals</code></p>
      </div>
      <button class="ae-btn ae-btn--ghost" :disabled="loading" @click="load">
        <Icon icon="mdi:refresh" :class="{ 'ae-spin': loading }" /> Refresh
      </button>
    </header>

    <div class="ae-grid">
      <!-- Suites -->
      <section class="ae-card ae-span2">
        <h2 class="ae-h2">Suites</h2>
        <table v-if="suites.length" class="ae-table">
          <thead>
            <tr><th>Key</th><th>Type</th><th>Tasks</th><th>Interval</th><th>Rep</th><th>Pays</th><th>Enabled</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="s in suites" :key="s.id">
              <td><strong>{{ s.key }}</strong><br><span class="ae-muted">{{ s.name }}</span></td>
              <td>{{ s.task_type }}</td>
              <td>{{ s.tasks }}</td>
              <td>{{ s.interval_minutes ? s.interval_minutes + 'm' : 'manual' }}</td>
              <td>{{ s.emit_reputation_signal ? '✓' : '—' }}</td>
              <td>{{ Number(s.pay_per_task) > 0 ? s.pay_per_task : '—' }}</td>
              <td><span :class="s.enabled ? 'ae-pill ae-pill--on' : 'ae-pill ae-pill--off'">{{ s.enabled ? 'on' : 'off' }}</span></td>
              <td class="ae-actions">
                <button class="ae-btn ae-btn--sm" :disabled="busyId === s.id" @click="runNow(s)">
                  <Icon icon="mdi:play" /> {{ busyId === s.id ? 'Running…' : 'Run' }}
                </button>
                <button class="ae-btn ae-btn--sm ae-btn--ghost" @click="viewResults(s)"><Icon icon="mdi:chart-bar" /> Results</button>
                <button class="ae-btn ae-btn--sm ae-btn--ghost" @click="taskSuiteId = s.id"><Icon icon="mdi:plus" /> Task</button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else-if="suitesRead !== 'read'" class="ae-empty" role="status">{{ suitesRead === 'unread' ? 'The suites could not be read just now.' : 'Loading…' }}</p>
        <p v-else class="ae-empty">No suites yet. Create one below. (EVALS_ENABLED must be on for runs to execute.)</p>
      </section>

      <!-- Create suite -->
      <section class="ae-card">
        <h2 class="ae-h2">New suite</h2>
        <div class="ae-form">
          <label>Key <input v-model="form.key" placeholder="smoke-http" /></label>
          <label>Name <input v-model="form.name" placeholder="Smoke HTTP probe" /></label>
          <label>Type
            <select v-model="form.task_type">
              <option value="http_probe">http_probe</option>
              <option value="a2a_message">a2a_message</option>
            </select>
          </label>
          <label>Interval (min, blank = manual) <input v-model.number="form.interval_minutes" type="number" min="1" /></label>
          <label>Pay per task <input v-model="form.pay_per_task" placeholder="0" /></label>
          <label class="ae-check"><input v-model="form.emit_reputation_signal" type="checkbox" /> Fold into reputation</label>
          <label class="ae-check"><input v-model="form.enabled" type="checkbox" /> Enabled</label>
          <button class="ae-btn" @click="createSuite"><Icon icon="mdi:content-save" /> Save suite</button>
        </div>
      </section>

      <!-- Add task -->
      <section v-if="taskSuiteId != null" class="ae-card">
        <h2 class="ae-h2">Add task → suite #{{ taskSuiteId }}</h2>
        <div class="ae-form">
          <label>Name <input v-model="taskForm.name" placeholder="probe-root" /></label>
          <label>Scorer
            <select v-model="taskForm.scorer">
              <option value="status_ok">status_ok</option>
              <option value="contains">contains</option>
              <option value="exact">exact</option>
              <option value="regex">regex</option>
              <option value="latency_under_ms">latency_under_ms</option>
            </select>
          </label>
          <label>Path <input v-model="taskForm.path" placeholder="/health" /></label>
          <label>Expected value <input v-model="taskForm.expected" placeholder="(for contains/exact/regex/latency)" /></label>
          <div class="ae-row">
            <button class="ae-btn" @click="addTask"><Icon icon="mdi:plus" /> Add task</button>
            <button class="ae-btn ae-btn--ghost" @click="taskSuiteId = null">Cancel</button>
          </div>
        </div>
      </section>

      <!-- Results -->
      <section v-if="selectedFailed" class="ae-card ae-span3">
        <h2 class="ae-h2">Leaderboard · {{ selectedKey }}</h2>
        <ReadFailedNotice :retry="retryResults" />
      </section>
      <section v-else-if="selectedResults.length" class="ae-card ae-span3">
        <h2 class="ae-h2">Leaderboard · {{ selectedKey }}</h2>
        <table class="ae-table">
          <thead><tr><th>#</th><th>Agent</th><th>Mean score</th><th>Last</th></tr></thead>
          <tbody>
            <tr v-for="(r, i) in selectedResults" :key="i">
              <td>{{ i + 1 }}</td>
              <td class="ae-mono">{{ (r as any).agent_did || '—' }}</td>
              <td>{{ (r.score * 100).toFixed(0) }}%</td>
              <td>{{ r.at ? new Date(r.at).toLocaleString(appLocale()) : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.ae-wrap { padding: 1.5rem; max-width: 1200px; margin: 0 auto; }
.ae-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1.25rem; }
.ae-title { font-size: 1.5rem; font-weight: 700; display: flex; align-items: center; gap: 0.5rem; color: rgb(var(--nc-primary-rgb)); }
.ae-title-icon { width: 1.4rem; height: 1.4rem; }
.ae-sub { color: rgba(var(--nc-primary-rgb), 0.6); font-size: 0.8rem; margin-top: 0.25rem; }
.ae-sub code { font-family: ui-monospace, monospace; }
.ae-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
.ae-span2 { grid-column: span 2; } .ae-span3 { grid-column: span 3; }
/* a column never grows to its table's width (a 1fr column's minimum is its content's): a wide table scrolls in its card */
.ae-card { min-width: 0; overflow-x: auto; border: 1px solid rgba(var(--nc-primary-rgb), 0.15); border-radius: 0.75rem; padding: 1rem; background: rgba(var(--nc-primary-rgb), 0.02); }
.ae-h2 { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.75rem; color: rgba(var(--nc-primary-rgb), 0.9); }
.ae-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.ae-table th { text-align: left; padding: 0.4rem 0.5rem; color: rgba(var(--nc-primary-rgb), 0.5); font-weight: 600; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12); text-transform: uppercase; font-size: 0.66rem; letter-spacing: 0.08em; }
.ae-table td { padding: 0.5rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.06); vertical-align: top; }
.ae-muted { color: rgba(var(--nc-primary-rgb), 0.5); font-size: 0.72rem; }
.ae-mono { font-family: ui-monospace, monospace; font-size: 0.72rem; }
.ae-actions { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.ae-form { display: flex; flex-direction: column; gap: 0.6rem; }
.ae-form label { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.72rem; color: rgba(var(--nc-primary-rgb), 0.7); }
.ae-form input, .ae-form select { background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.2); border-radius: 0.4rem; padding: 0.4rem 0.55rem; color: rgb(var(--nc-primary-rgb)); font-size: 0.8rem; outline: none; }
.ae-form input:focus, .ae-form select:focus { border-color: rgba(var(--nc-primary-rgb), 0.55); }
.ae-check { flex-direction: row !important; align-items: center; gap: 0.5rem !important; }
.ae-row { display: flex; gap: 0.5rem; }
.ae-btn { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.45rem 0.75rem; border-radius: 0.5rem; font-size: 0.78rem; font-weight: 600; background: rgba(var(--nc-primary-rgb), 0.14); color: rgb(var(--nc-primary-rgb)); border: 1px solid rgba(var(--nc-primary-rgb), 0.3); transition: background 0.15s ease; }
.ae-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.24); }
.ae-btn:disabled { opacity: 0.5; }
.ae-btn--ghost { background: transparent; }
.ae-btn--sm { padding: 0.3rem 0.55rem; font-size: 0.72rem; }
.ae-pill { font-size: 0.66rem; padding: 0.1rem 0.4rem; border-radius: 0.3rem; font-weight: 700; text-transform: uppercase; }
.ae-pill--on { color: #34d399; background: rgba(52, 211, 153, 0.12); }
.ae-pill--off { color: rgba(var(--nc-primary-rgb), 0.5); background: rgba(var(--nc-primary-rgb), 0.08); }
.ae-empty { color: rgba(var(--nc-primary-rgb), 0.5); font-size: 0.8rem; padding: 1rem 0; }
.ae-spin { animation: ae-rot 0.8s linear infinite; }
@keyframes ae-rot { to { transform: rotate(360deg); } }
@media (max-width: 900px) { .ae-grid { grid-template-columns: minmax(0, 1fr); } .ae-span2, .ae-span3 { grid-column: span 1; } }
</style>
