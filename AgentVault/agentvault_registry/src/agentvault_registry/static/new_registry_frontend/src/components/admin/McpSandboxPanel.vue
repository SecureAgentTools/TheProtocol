<template>
  <!-- §TESTBED (2026-09-19, his words: "the sandbox provisioning should be also in the frontend mcp-tester view ... options
       to pick and you can see progress. and possible errors"). Shown only where this frame's runner answers: a registry
       with no runner renders nothing; a runner that refuses (a sandbox itself, sandboxes not offered) says why. -->
  <section v-if="visible" class="mcp-section" data-testid="mcp-sandbox">
    <div class="sbx">
      <header class="sbx-head">
        <h2 class="sbx-title">
          <Icon name="mdi:test-tube" class="sbx-title-icon" />
          {{ t('mcpTester.sandbox.title', 'Sandbox') }}
        </h2>
        <p class="sbx-lead">
          {{ t('mcpTester.sandbox.lead', 'A test frame beside this one. The MCP tester runs inside it, so every write a test makes lands there, never on this frame.') }}
        </p>
      </header>

      <!-- §FESUITE V0577: a status read that got no answer says so (it hid the panel as a frame with no runner) -->
      <ReadFailedNotice v-if="statusUnread" dense :retry="loadStatus" data-testid="mcp-sandbox-unread" />
      <p v-else-if="status && !status.available && status.reason === 'is_sandbox'" class="sbx-note" data-testid="mcp-sandbox-is-sandbox">
        {{ tp('mcpTester.sandbox.isSandbox', 'This frame is a sandbox of {parent}. The MCP tester below runs against this frame, so every write a test makes lands here.', { parent: status.parent || '' }) }}
      </p>
      <!-- §MCPTEST30 (V0535): a refusal the page understands is said in its words; the runner's own stay as the tooltip -->
      <p v-else-if="status && !status.available" class="sbx-note" data-testid="mcp-sandbox-unavailable" :title="status.why">{{ unavailableSentence }}</p>

      <template v-else-if="status">
        <!-- the sandboxes that stand -->
        <ul v-if="sandboxes.length" class="sbx-list" data-testid="mcp-sandbox-list">
          <li v-for="(s, i) in sandboxes" :key="s.name" class="sbx-item" :data-testid="`mcp-sandbox-item-${i === 0 ? 'a' : 'b'}`">
            <div class="sbx-item-main">
              <span class="sbx-item-name">{{ s.name }}</span>
              <span class="sbx-item-host">{{ s.public_name }}</span>
            </div>
            <div class="sbx-item-links">
              <a v-if="s.tester" class="sbx-link sbx-link--primary" :href="s.tester" target="_blank" rel="noopener noreferrer"
                 :data-testid="`mcp-sandbox-tester-${i === 0 ? 'a' : 'b'}`">
                {{ t('mcpTester.sandbox.openTester', 'Open its MCP tester') }} <Icon name="mdi:open-in-new" />
              </a>
              <a v-if="s.console" class="sbx-link" :href="s.console" target="_blank" rel="noopener noreferrer">
                {{ t('mcpTester.sandbox.openConsole', 'Console') }} <Icon name="mdi:open-in-new" />
              </a>
              <button type="button" class="sbx-link" :data-testid="`mcp-sandbox-login-${i === 0 ? 'a' : 'b'}`"
                      :disabled="revealing === s.name" @click="toggleLogin(s.name, i === 0 ? 'a' : 'b')">
                <Icon :name="logins[s.name] ? 'mdi:eye-off' : 'mdi:eye'" />
                {{ logins[s.name] ? t('mcpTester.sandbox.hideLogin', 'Hide login') : t('mcpTester.sandbox.showLogin', 'Show login') }}
              </button>
            </div>
            <dl v-if="logins[s.name]" class="sbx-login" :data-testid="`mcp-sandbox-credential-${i === 0 ? 'a' : 'b'}`">
              <div class="sbx-login-row">
                <dt>{{ t('mcpTester.sandbox.email', 'Email') }}</dt>
                <dd><code>{{ logins[s.name].email }}</code></dd>
                <button type="button" class="sbx-copy" @click="copy(logins[s.name].email, s.name + ':email')">
                  <Icon name="mdi:content-copy" />
                  {{ copied === s.name + ':email' ? t('mcpTester.sandbox.copied', 'Copied') : t('mcpTester.sandbox.copy', 'Copy') }}
                </button>
              </div>
              <div class="sbx-login-row">
                <dt>{{ t('mcpTester.sandbox.password', 'Password') }}</dt>
                <dd><code>{{ logins[s.name].password }}</code></dd>
                <button type="button" class="sbx-copy" @click="copy(logins[s.name].password, s.name + ':password')">
                  <Icon name="mdi:content-copy" />
                  {{ copied === s.name + ':password' ? t('mcpTester.sandbox.copied', 'Copied') : t('mcpTester.sandbox.copy', 'Copy') }}
                </button>
              </div>
            </dl>
          </li>
        </ul>

        <!-- the choice: while no sandbox stands and nothing runs -->
        <div v-if="!sandboxes.length && !jobRunning" class="sbx-choose" data-testid="mcp-sandbox-choose">
          <fieldset class="sbx-options">
            <legend class="sbx-legend">{{ t('mcpTester.sandbox.pick', 'What should the sandbox test?') }}</legend>
            <label class="sbx-option" :class="{ 'sbx-option--on': frames === 1 }">
              <input v-model="frames" type="radio" name="sbx-frames" :value="1" data-testid="mcp-sandbox-frames-1" />
              <span class="sbx-option-title">{{ t('mcpTester.sandbox.oneFrame', 'One frame') }}</span>
              <span class="sbx-option-hint">{{ t('mcpTester.sandbox.oneFrameHint', 'The lifecycle sweep') }}</span>
              <span class="sbx-option-cost">{{ tp('mcpTester.sandbox.estimate', 'about {gib} of memory', { gib: gib(1, operators) }) }}</span>
            </label>
            <label class="sbx-option" :class="{ 'sbx-option--on': frames === 2 }">
              <input v-model="frames" type="radio" name="sbx-frames" :value="2" data-testid="mcp-sandbox-frames-2" />
              <span class="sbx-option-title">{{ t('mcpTester.sandbox.twoFrames', 'Two federated frames') }}</span>
              <span class="sbx-option-hint">{{ t('mcpTester.sandbox.twoFramesHint', 'The lifecycle sweep and the federation suite') }}</span>
              <span class="sbx-option-cost">{{ tp('mcpTester.sandbox.estimate', 'about {gib} of memory', { gib: gib(2, operators) }) }}</span>
            </label>
          </fieldset>
          <label class="sbx-check">
            <input v-model="operators" type="checkbox" data-testid="mcp-sandbox-operators" />
            <span>{{ t('mcpTester.sandbox.operators', 'A cloud operator on each frame') }}</span>
          </label>
          <p v-if="frames === 2 && !operators" class="sbx-hint" data-testid="mcp-sandbox-needs-operators">
            {{ t('mcpTester.sandbox.operatorsHint', 'The federation suite needs a cloud operator on each frame; without them only the lifecycle sweep runs.') }}
          </p>
          <p v-if="hostLine" class="sbx-host">{{ hostLine }}</p>
          <ul v-if="hostProblems.length" class="sbx-problems">
            <li v-for="p in hostProblems" :key="p">{{ p }}</li>
          </ul>
          <div class="sbx-actions">
            <button type="button" class="sbx-btn sbx-btn--primary" data-testid="mcp-sandbox-provision"
                    :disabled="acting || hostProblems.length > 0 || !!busyElsewhere" @click="provision()">
              {{ acting ? t('mcpTester.sandbox.starting', 'Starting') : t('mcpTester.sandbox.provision', 'Provision') }}
            </button>
            <span v-if="busyElsewhere" class="sbx-hint">
              {{ tp('mcpTester.sandbox.busy', 'The host is running another job ({op} {name}); provision when it ends.', busyElsewhere) }}
            </span>
          </div>
        </div>

        <!-- the job: its steps, its latest word, its error -->
        <div v-if="job" class="sbx-progress" data-testid="mcp-sandbox-progress" aria-live="polite">
          <div class="sbx-progress-head">
            <span class="sbx-progress-title">{{ job.op === 'sandbox_down' ? t('mcpTester.sandbox.jobDown', 'Removing the sandboxes') : job.request?.frames === 2 ? t('mcpTester.sandbox.jobUpPair', 'Provisioning two federated sandboxes') : t('mcpTester.sandbox.jobUp', 'Provisioning the sandbox') }}</span>
            <span class="sbx-state" :class="`sbx-state--${job.state}`" data-testid="mcp-sandbox-job-state">{{ stateLabel(job.state) }}</span>
            <span class="sbx-elapsed">{{ elapsed }}</span>
          </div>
          <ol class="sbx-steps">
            <li v-for="r in folded.rows" :key="r.step" class="sbx-step" :class="`sbx-step--${r.state}`" :data-testid="`mcp-sandbox-step-${r.step}`">
              <span class="sbx-step-icon"><Icon :name="stepIcon(r.state)" :class="{ 'sbx-spin': r.state === 'running' }" /></span>
              <span class="sbx-step-label">{{ stepLabel(r.step) }}</span>
              <span class="sbx-step-state">{{ stepStateLabel(r.state) }}</span>
              <span v-if="r.sentence && r.state !== 'failed'" class="sbx-step-sentence">{{ r.sentence }}</span>
            </li>
          </ol>
          <div v-if="folded.failure" class="sbx-error" data-testid="mcp-sandbox-error">
            <Icon name="mdi:alert-circle-outline" />
            <div>
              <strong>{{ tp('mcpTester.sandbox.stoppedAt', 'Stopped at: {step}', { step: stepLabel(folded.failure.step) }) }}</strong>
              <p class="sbx-error-text">{{ folded.failure.sentence }}</p>
            </div>
          </div>
          <p v-else-if="job.state === 'succeeded' && job.op === 'sandbox_up'" class="sbx-done" data-testid="mcp-sandbox-ready">
            {{ t('mcpTester.sandbox.ready', 'Ready. Open its MCP tester above and run the sweep there.') }}
          </p>
        </div>

        <!-- after a failure: resume, or remove what stands -->
        <div v-if="!jobRunning && (sandboxes.length || jobFailed)" class="sbx-actions">
          <button v-if="jobFailed && job?.op === 'sandbox_up'" type="button" class="sbx-btn sbx-btn--primary"
                  data-testid="mcp-sandbox-retry" :disabled="acting" :title="t('mcpTester.sandbox.tryAgainHint', 'Picks up where it stopped: steps that already stand are skipped.')"
                  @click="provision(lastRequest)">
            {{ t('mcpTester.sandbox.tryAgain', 'Try again') }}
          </button>
          <template v-if="!confirming">
            <button type="button" class="sbx-btn sbx-btn--danger" data-testid="mcp-sandbox-teardown" :disabled="acting" @click="confirming = true">
              {{ t('mcpTester.sandbox.teardown', 'Tear down') }}
            </button>
          </template>
          <template v-else>
            <button type="button" class="sbx-btn sbx-btn--danger" data-testid="mcp-sandbox-teardown-confirm" :disabled="acting" @click="teardown()">
              {{ t('mcpTester.sandbox.teardownConfirm', 'Remove the sandbox and everything in it') }}
            </button>
            <button type="button" class="sbx-btn" @click="confirming = false">{{ t('mcpTester.sandbox.keep', 'Keep it') }}</button>
          </template>
        </div>
        <p v-if="actionError" class="sbx-error sbx-error--inline" data-testid="mcp-sandbox-action-error">
          <Icon name="mdi:alert-circle-outline" /> {{ actionError }}
        </p>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { foldProgress, type StepState } from '@/services/frameRunnerSteps'
import { formatGib, sandboxStepLabel, sandboxSteps } from '@/services/sandboxSteps'
import {
  mcpTesterSandboxApi,
  type SandboxJob,
  type SandboxLogin,
  type SandboxStatus,
} from '@/services/api/mcpTesterSandbox'
import type { ProgressEvent } from '@/services/api/frameRunner'
import { sandboxRefusalSentence } from '@/services/mcpTester/runReading'

const { t, tp } = useI18n()

/** What this frame is to the tester, for the view around the panel: `parent` (a production frame that provisions its
 *  sandbox here and runs nothing itself), `sandbox` (runs the tester against itself), `none` (no runner offers sandboxes). */
const emit = defineEmits<{ (e: 'role', role: 'parent' | 'sandbox' | 'none'): void }>()

const status = ref<SandboxStatus | null>(null)
// a status read with no answer, or the registry's own failure: only a refusal (401/403) or a registry without the route
// (404) means this frame offers no sandbox; the others hid the panel as "no runner" (§FESUITE V0577)
const statusUnread = ref(false)
// §MCPTEST30 (V0535): "op 'sandbox_status': this runner's policy does not offer sandboxes (...)" read as the panel's sentence
const unavailableSentence = computed(() => {
  const why = status.value?.why || ''
  const known = sandboxRefusalSentence(why)
  return known ? t(known.key, known.fallback) : why
})
const job = ref<SandboxJob | null>(null)
const events = ref<ProgressEvent[]>([])
const next = ref(0)
const frames = ref<1 | 2>(1)
const operators = ref(false)
const acting = ref(false)
const confirming = ref(false)
const actionError = ref('')
const logins = ref<Record<string, SandboxLogin>>({})
const revealing = ref('')
const copied = ref('')
const now = ref(Date.now())
let followTimer: ReturnType<typeof setTimeout> | null = null
let clock: ReturnType<typeof setInterval> | null = null
let alive = true

const ENDED = ['succeeded', 'failed', 'cancelled', 'lost']

const visible = computed(() => statusUnread.value
  || (!!status.value && !(status.value.available === false && status.value.reason === 'no_runner')))
const sandboxes = computed(() => status.value?.sandboxes ?? [])
const jobRunning = computed(() => !!job.value && !ENDED.includes(job.value.state))
const jobFailed = computed(() => !!job.value && ['failed', 'lost', 'cancelled'].includes(job.value.state))
const lastRequest = computed<{ frames: 1 | 2; operators: boolean }>(() => ({
  frames: (job.value?.request?.frames === 2 ? 2 : 1),
  operators: !!job.value?.request?.operators,
}))
const hostProblems = computed(() => status.value?.host?.problems ?? [])
const busyElsewhere = computed(() => {
  const b = status.value?.host?.busy
  if (!b || (job.value && b.id === job.value.id)) return null
  return { op: b.op, name: b.name }
})
const hostLine = computed(() => {
  const g = status.value?.host?.mem_available_gib
  return typeof g === 'number' ? tp('mcpTester.sandbox.hostFree', 'This host has {gib} of memory free.', { gib: `${g.toFixed(1)} GiB` }) : ''
})
const folded = computed(() => foldProgress(events.value, job.value?.state ?? null, sandboxSteps(job.value?.op)))
watch(status, s => emit('role', !s ? 'none' : s.available ? 'parent' : s.reason === 'is_sandbox' ? 'sandbox' : 'none'))
const elapsed = computed(() => {
  const start = job.value?.created ? Date.parse(job.value.created) : NaN
  if (!Number.isFinite(start)) return ''
  const end = job.value?.ended ? Date.parse(job.value.ended) : now.value
  const s = Math.max(0, Math.round((end - start) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

function gib(f: 1 | 2, ops: boolean): string {
  const t = status.value?.topologies?.find(x => x.frames === f && x.operators === ops)
  return formatGib(t?.estimate_mib)
}
function stepLabel(step: string): string {
  const [key, fallback] = sandboxStepLabel(job.value?.op, step)
  return t(`mcpTester.sandbox.steps.${key}`, fallback)
}
function stepStateLabel(state: StepState): string {
  const fallback: Record<StepState, string> = {
    pending: 'waiting', running: 'running', done: 'done', skipped: 'skipped', failed: 'failed', unreached: 'not reached',
  }
  return t(`mcpTester.sandbox.stepState.${state}`, fallback[state])
}
function stateLabel(state: string): string {
  const fallback: Record<string, string> = {
    running: 'running', cancelling: 'stopping', succeeded: 'done', failed: 'failed', cancelled: 'stopped', lost: 'lost contact',
  }
  return t(`mcpTester.sandbox.state.${state}`, fallback[state] ?? state)
}
function stepIcon(state: StepState): string {
  return { done: 'mdi:check', failed: 'mdi:close', running: 'mdi:loading', skipped: 'mdi:dots-horizontal' }[state as string] ?? 'mdi:circle-medium'
}
function errorText(e: unknown): string {
  const r = (e as { response?: { data?: { detail?: unknown } } })?.response
  const d = r?.data?.detail
  if (typeof d === 'string') return d.replace(/^refused: /, '')
  return (e as Error)?.message || String(e)
}

async function loadStatus(): Promise<void> {
  try {
    status.value = await mcpTesterSandboxApi.status()
    statusUnread.value = false
  } catch (e) {
    const code = (e as { response?: { status?: number } })?.response?.status
    if (code === 401 || code === 403 || code === 404) {
      // an admin without the platform flag, or a registry without the route: the panel stays hidden
      status.value = { available: false, frame: '', reason: 'no_runner', why: errorText(e) }
      statusUnread.value = false
    } else {
      statusUnread.value = true
    }
    return
  }
  const j = status.value.job ?? null
  if (j && (!job.value || j.id !== job.value.id)) {
    job.value = j
    events.value = []
    next.value = 0
  } else if (j) {
    job.value = j
  }
  if (job.value) void follow()
}

async function follow(): Promise<void> {
  if (followTimer) clearTimeout(followTimer)
  followTimer = null
  if (!job.value || !alive) return
  let failedCall = false
  try {
    const page = await mcpTesterSandboxApi.events(job.value.id, next.value)
    if (page.events?.length) events.value = [...events.value, ...page.events]
    next.value = page.next ?? next.value
    if (page.job) job.value = page.job
  } catch {
    failedCall = true
  }
  if (!alive || !job.value) return
  if (ENDED.includes(job.value.state)) {
    // the job ended: one more status read (the sandboxes it made, the host's headroom)
    const s = await mcpTesterSandboxApi.status().catch(() => null)
    if (s) status.value = s
    return
  }
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden'
  followTimer = setTimeout(() => { void follow() }, hidden || failedCall ? 5000 : 2000)
}

async function provision(req?: { frames: 1 | 2; operators: boolean }): Promise<void> {
  acting.value = true
  actionError.value = ''
  confirming.value = false
  try {
    const r = await mcpTesterSandboxApi.provision(req?.frames ?? frames.value, req?.operators ?? operators.value)
    if (r.job) {
      job.value = r.job
      events.value = []
      next.value = 0
      void follow()
    }
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    acting.value = false
  }
}

async function teardown(): Promise<void> {
  acting.value = true
  actionError.value = ''
  confirming.value = false
  logins.value = {}
  try {
    const r = await mcpTesterSandboxApi.teardown()
    if (r.job) {
      job.value = r.job
      events.value = []
      next.value = 0
      void follow()
    }
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    acting.value = false
  }
}

async function toggleLogin(name: string, which: 'a' | 'b'): Promise<void> {
  if (logins.value[name]) {
    const { [name]: _drop, ...rest } = logins.value
    logins.value = rest
    return
  }
  revealing.value = name
  actionError.value = ''
  try {
    const login = await mcpTesterSandboxApi.reveal(which)
    logins.value = { ...logins.value, [name]: login }
  } catch (e) {
    actionError.value = errorText(e)
  } finally {
    revealing.value = ''
  }
}

async function copy(text: string, key: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => { if (copied.value === key) copied.value = '' }, 1500)
  } catch {
    copied.value = ''
  }
}

onMounted(() => {
  void loadStatus()
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})
onBeforeUnmount(() => {
  alive = false
  if (followTimer) clearTimeout(followTimer)
  if (clock) clearInterval(clock)
})
</script>

<style scoped>
.sbx {
  border: 1px solid var(--border, rgba(0, 210, 210, 0.18));
  border-radius: 6px;
  padding: 18px 20px;
  background: rgba(var(--cyan-rgb, 0, 210, 210), 0.03);
  color: var(--text-bright, #e8eaed);
}
.sbx-head { margin-bottom: 14px; }
.sbx-title {
  display: flex; align-items: center; gap: 8px; margin: 0 0 4px;
  font-family: var(--mono, monospace); font-size: 15px; font-weight: 600; color: var(--cyan, #00d2d2);
}
.sbx-title-icon { font-size: 17px; }
.sbx-lead { margin: 0; max-width: 72ch; font-size: 13px; line-height: 1.55; color: var(--muted, #6b7785); }
.sbx-note { margin: 0; font-size: 13px; line-height: 1.5; color: var(--muted, #6b7785); }

.sbx-list { list-style: none; margin: 0 0 14px; padding: 0; display: grid; gap: 10px; }
.sbx-item { border: 1px solid var(--border, rgba(0, 210, 210, 0.18)); border-radius: 5px; padding: 12px 14px; }
.sbx-item-main { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.sbx-item-name { font-family: var(--mono, monospace); font-weight: 600; font-size: 13px; }
.sbx-item-host { font-family: var(--mono, monospace); font-size: 12px; color: var(--muted, #6b7785); overflow-wrap: anywhere; }
.sbx-item-links { display: flex; flex-wrap: wrap; gap: 8px; }
.sbx-link {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 4px;
  font-family: var(--mono, monospace); font-size: 12px; color: var(--cyan, #00d2d2); text-decoration: none;
  background: transparent; border: 1px solid var(--border, rgba(0, 210, 210, 0.18)); cursor: pointer;
}
.sbx-link--primary { background: rgba(var(--cyan-rgb, 0, 210, 210), 0.12); border-color: rgba(var(--cyan-rgb, 0, 210, 210), 0.45); }
.sbx-link:hover, .sbx-link:focus-visible { border-color: var(--cyan, #00d2d2); outline: none; }
.sbx-link:focus-visible, .sbx-btn:focus-visible, .sbx-copy:focus-visible { box-shadow: 0 0 0 2px rgba(var(--cyan-rgb, 0, 210, 210), 0.55); }
.sbx-link:disabled { opacity: 0.5; cursor: wait; }

.sbx-login { margin: 10px 0 0; display: grid; gap: 6px; }
.sbx-login-row { display: grid; grid-template-columns: 80px minmax(0, 1fr) auto; align-items: center; gap: 8px; }
.sbx-login dt { font-size: 12px; color: var(--muted, #6b7785); }
.sbx-login dd { margin: 0; min-width: 0; }
.sbx-login code {
  display: block; overflow-wrap: anywhere; font-family: var(--mono, monospace); font-size: 12px;
  background: rgba(0, 0, 0, 0.3); padding: 3px 8px; border-radius: 3px; color: var(--text-bright, #e8eaed);
}
.sbx-copy {
  display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; font-size: 11px; border-radius: 3px;
  background: transparent; color: var(--muted, #6b7785); border: 1px solid var(--border, rgba(0, 210, 210, 0.18)); cursor: pointer;
}

.sbx-choose { display: grid; gap: 10px; }
.sbx-options { border: 0; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.sbx-legend { font-size: 13px; margin-bottom: 8px; color: var(--text-bright, #e8eaed); }
.sbx-option {
  position: relative; display: grid; gap: 3px; padding: 12px 14px 12px 38px; border-radius: 5px; cursor: pointer;
  border: 1px solid var(--border, rgba(0, 210, 210, 0.18)); background: rgba(0, 0, 0, 0.18);
}
.sbx-option input { position: absolute; left: 14px; top: 14px; accent-color: var(--cyan, #00d2d2); }
.sbx-option--on { border-color: rgba(var(--cyan-rgb, 0, 210, 210), 0.6); background: rgba(var(--cyan-rgb, 0, 210, 210), 0.07); }
.sbx-option:focus-within { box-shadow: 0 0 0 2px rgba(var(--cyan-rgb, 0, 210, 210), 0.45); }
.sbx-option-title { font-weight: 600; font-size: 13px; }
.sbx-option-hint { font-size: 12px; color: var(--muted, #6b7785); }
.sbx-option-cost { font-family: var(--mono, monospace); font-size: 11px; color: var(--muted, #6b7785); }
.sbx-check { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; }
.sbx-check input { accent-color: var(--cyan, #00d2d2); }
.sbx-hint, .sbx-host { margin: 0; font-size: 12px; color: var(--muted, #6b7785); }
.sbx-problems { margin: 0; padding-left: 18px; font-size: 12px; color: var(--amber, #ffb84d); }

.sbx-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 12px; }
.sbx-btn {
  font-family: var(--mono, monospace); font-size: 12px; font-weight: 600; letter-spacing: 0.04em;
  padding: 8px 16px; border-radius: 5px; cursor: pointer; border: 1px solid var(--border, rgba(0, 210, 210, 0.18));
  background: transparent; color: var(--text-bright, #e8eaed);
}
.sbx-btn--primary { background: rgba(var(--cyan-rgb, 0, 210, 210), 0.16); border-color: rgba(var(--cyan-rgb, 0, 210, 210), 0.6); color: var(--cyan, #00d2d2); }
.sbx-btn--danger { border-color: rgba(255, 51, 102, 0.5); color: #ff7a99; }
.sbx-btn:disabled { opacity: 0.45; cursor: not-allowed; }

.sbx-progress { margin-top: 14px; border-top: 1px solid var(--border, rgba(0, 210, 210, 0.18)); padding-top: 12px; }
.sbx-progress-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px; margin-bottom: 8px; }
.sbx-progress-title { font-weight: 600; font-size: 13px; }
.sbx-state { font-family: var(--mono, monospace); font-size: 11px; padding: 1px 8px; border-radius: 10px; border: 1px solid currentColor; }
.sbx-state--running, .sbx-state--cancelling { color: var(--cyan, #00d2d2); }
.sbx-state--succeeded { color: var(--green, #00ff88); }
.sbx-state--failed, .sbx-state--lost, .sbx-state--cancelled { color: var(--red, #ff3366); }
.sbx-elapsed { font-family: var(--mono, monospace); font-size: 12px; color: var(--muted, #6b7785); font-variant-numeric: tabular-nums; }
.sbx-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.sbx-step { display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: baseline; column-gap: 8px; font-size: 13px; }
.sbx-step-icon { color: var(--muted, #6b7785); }
.sbx-step--done .sbx-step-icon { color: var(--green, #00ff88); }
.sbx-step--running .sbx-step-icon { color: var(--cyan, #00d2d2); }
.sbx-step--failed .sbx-step-icon, .sbx-step--failed .sbx-step-state { color: var(--red, #ff3366); }
.sbx-step--skipped, .sbx-step--unreached, .sbx-step--pending { color: var(--muted, #6b7785); }
.sbx-step-state { font-family: var(--mono, monospace); font-size: 11px; color: var(--muted, #6b7785); }
.sbx-step-sentence { grid-column: 2 / 4; font-size: 12px; color: var(--muted, #6b7785); overflow-wrap: anywhere; }
.sbx-spin { animation: sbx-spin 1s linear infinite; display: inline-block; }
@keyframes sbx-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .sbx-spin { animation: none; } }

.sbx-error {
  display: flex; align-items: flex-start; gap: 10px; margin-top: 12px; padding: 10px 14px; border-radius: 5px;
  background: rgba(255, 51, 102, 0.08); border: 1px solid rgba(255, 51, 102, 0.4); color: #ffb3c1; font-size: 13px;
}
.sbx-error strong { color: #ff5577; }
.sbx-error-text { margin: 4px 0 0; overflow-wrap: anywhere; font-family: var(--mono, monospace); font-size: 12px; }
.sbx-error--inline { display: flex; align-items: center; }
.sbx-done { margin: 10px 0 0; font-size: 13px; color: var(--green, #00ff88); }

@media (max-width: 560px) {
  .sbx { padding: 14px; }
  .sbx-login-row { grid-template-columns: 1fr auto; }
  .sbx-login dt { grid-column: 1 / -1; }
}
</style>
