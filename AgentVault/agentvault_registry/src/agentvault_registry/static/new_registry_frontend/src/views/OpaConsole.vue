<!--
  OPA POLICY CONSOLE (§29, 2026-07-28)

  The view exists to answer ONE question that kept OPA in shadow since 2026-05-23:
  "what breaks if I enforce this?" Everything else is supporting evidence.

  Design notes: Icon.vue LOCAL inline SVG only (never Iconify — unknown names blank-render),
  no emoji, ViewAmbient comes from the DashboardLayout so this view stays transparent.
-->
<template>
  <div class="opa-page">
    <header class="opa-head">
      <div class="opa-head-l">
        <h1 class="opa-title">OPA POLICY CONSOLE</h1>
        <p class="opa-sub">Open Policy Agent · decision evidence and enforce-impact analysis</p>
      </div>
      <div class="opa-head-r">
        <!-- A failed read must NEVER render as a definite state. Showing "OFF" when /status did
             not answer tells an operator OPA is disabled when it may be enforcing. Unknown is
             its own visual state (§EXTRAHOSTS: unreadable reads "—", never a confident zero). -->
        <!-- Three distinct states, never conflated:
             LOADING  = first fetch still in flight / retrying (neutral, not a warning)
             UNKNOWN  = retries exhausted, we genuinely could not read it (amber warning)
             off/shadow/enforce = an actual answer from the backend.
             Rendering a failed or in-flight read as a definite "OFF" would tell an operator OPA
             is disabled when it may be enforcing. -->
        <span class="opa-mode" :class="'opa-mode--' + modeClass" data-testid="opa-mode">
          {{ modeLabel }}
        </span>
        <button class="opa-btn" :disabled="loading" @click="refresh()" data-testid="opa-refresh">
          <Icon name="mdi:refresh" :class="{ 'opa-spin': loading }" /> REFRESH
        </button>
      </div>
    </header>

    <p v-if="error" class="opa-err" data-testid="opa-error">{{ error }}</p>

    <!-- ── divergence: the number that decides whether enforce is safe ── -->
    <section class="opa-grid" data-testid="opa-stats">
      <div class="opa-stat">
        <span class="opa-stat-k">AGREEMENT</span>
        <span class="opa-stat-v">{{ fmtPct(status?.divergence?.agreement_pct) }}</span>
        <span class="opa-stat-n">python vs OPA, retained window</span>
      </div>
      <div class="opa-stat" :class="{ 'opa-stat--warn': (status?.divergence?.mismatches || 0) > 0 }">
        <span class="opa-stat-k">MISMATCHES</span>
        <span class="opa-stat-v">{{ status?.divergence?.mismatches ?? '—' }}</span>
        <span class="opa-stat-n">OPA disagreed with Python</span>
      </div>
      <div class="opa-stat">
        <span class="opa-stat-k">RETAINED</span>
        <span class="opa-stat-v">{{ status?.divergence?.retained ?? '—' }}<small>/{{ status?.divergence?.capacity ?? '—' }}</small></span>
        <span class="opa-stat-n">decisions held with input</span>
      </div>
      <div class="opa-stat">
        <span class="opa-stat-k">LATENCY</span>
        <span class="opa-stat-v">{{ status?.divergence?.latency_ms_avg ?? '—' }}<small>ms avg</small></span>
        <span class="opa-stat-n">max {{ status?.divergence?.latency_ms_max ?? '—' }}ms</span>
      </div>
    </section>

    <!-- Honest framing: the mirrors CANNOT disagree, so 100% agreement is not reassurance. -->
    <div class="opa-note" data-testid="opa-tautology-note">
      <Icon name="mdi:information-outline" />
      <span>
        A policy that restates the check it mirrors can never disagree. Sustained 100% agreement on
        <code>mirror</code> policies is expected, not evidence of safety. Look for
        <code>invariant</code> policies below, which decide things Python does not.
      </span>
    </div>

    <nav class="opa-tabs" role="tablist">
      <button v-for="t in tabs" :key="t.id" class="opa-tab" :class="{ 'opa-tab--on': tab === t.id }"
              role="tab" :aria-selected="tab === t.id" :data-testid="'opa-tab-' + t.id" @click="tab = t.id">
        {{ t.label }}
      </button>
    </nav>

    <!-- ── policies ── -->
    <section v-show="tab === 'policies'" class="opa-panel" data-testid="opa-panel-policies">
      <!-- invariant first: the policies that can actually disagree are the point of this page;
           mirrors sort last because they are structurally incapable of disagreeing. -->
      <div v-for="p in sortedPolicies" :key="p.id" class="opa-pol">
        <div class="opa-pol-h" @click="openPolicy = openPolicy === p.id ? '' : p.id">
          <span class="opa-kind" :class="'opa-kind--' + p.kind">{{ p.kind }}</span>
          <span class="opa-pol-pkg">{{ p.package || p.id }}</span>
          <span class="opa-pol-meta">{{ p.rules.length }} {{ p.rules.length === 1 ? 'rule' : 'rules' }} · {{ p.lines }} lines</span>
          <Icon :name="openPolicy === p.id ? 'mdi:chevron-up' : 'mdi:chevron-down'" />
        </div>
        <!-- The RULES are the content of a policy console. Showing only a count meant adding five
             rules to an existing file looked like nothing had changed. Always visible, no expand. -->
        <div v-if="p.rules.length" class="opa-rules">
          <code v-for="r in p.rules" :key="r" class="opa-rule">{{ r }}</code>
        </div>
        <pre v-if="openPolicy === p.id" class="opa-src">{{ p.source }}</pre>
      </div>
      <p v-if="policiesRead && !policies.length" class="opa-empty">No policies loaded.</p>
    </section>

    <!-- ── decisions ── -->
    <section v-show="tab === 'decisions'" class="opa-panel" data-testid="opa-panel-decisions">
      <label class="opa-check">
        <input type="checkbox" v-model="onlyMismatch" @change="loadDecisions" />
        <span>only disagreements</span>
      </label>
      <div class="opa-tblwrap">
        <table class="opa-tbl">
          <thead><tr><th>TIME</th><th>POLICY</th><th>PYTHON</th><th>OPA</th><th>INPUT</th></tr></thead>
          <tbody>
            <tr v-for="(d, i) in decisions" :key="i" :class="{ 'opa-row--bad': d.match === false }">
              <td class="opa-mono">{{ (d.ts || '').slice(11, 19) }}</td>
              <td class="opa-mono">{{ shortPolicy(d.policy) }}</td>
              <td><span class="opa-b" :class="boolCls(d.python)">{{ fmtBool(d.python) }}</span></td>
              <td><span class="opa-b" :class="boolCls(d.opa)">{{ fmtBool(d.opa) }}</span></td>
              <td class="opa-mono opa-in">{{ compact(d.input) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <!-- §FESUITE (V0578): "none retained" is what the decisions read answers; a failed read says so instead (the
           status and policies reads above can answer while this one does not, and then nothing else on the page said it) -->
      <ReadFailedNotice v-if="decisionsFailed" :retry="loadDecisions" data-testid="opa-decisions-failed"
                        text="The decisions could not be read just now." />
      <p v-else-if="decisionsRead && !decisions.length" class="opa-empty" data-testid="opa-decisions-empty">
        <template v-if="decisionsMismatchOnly">No disagreements among the decisions retained on this worker.</template>
        <template v-else>No decisions retained yet on this worker. Drive traffic through an authenticated endpoint.</template>
      </p>
    </section>

    <!-- ── simulator: the reason this console exists ── -->
    <section v-show="tab === 'simulate'" class="opa-panel" data-testid="opa-panel-simulate">
      <p class="opa-simhelp">
        Replays the retained real decision inputs against a candidate policy and reports which
        requests would flip allow to deny. The candidate is loaded under a scratch id and always
        deleted; enforcement is never changed from here.
      </p>
      <div class="opa-simrow">
        <input v-model="rulePath" class="opa-inp" placeholder="agentvault/invariants/flag_pairing_ok"
               data-testid="opa-sim-rule" />
        <button class="opa-btn opa-btn--go" :disabled="simRunning || !rego.trim()" @click="runSim"
                data-testid="opa-sim-run">
          <Icon name="mdi:play-circle" /> {{ simRunning ? 'SIMULATING…' : 'SIMULATE' }}
        </button>
      </div>
      <textarea v-model="rego" class="opa-ta" spellcheck="false" rows="12"
                placeholder="package … candidate policy source" data-testid="opa-sim-rego"></textarea>

      <div v-if="sim" class="opa-simout" data-testid="opa-sim-out">
        <div class="opa-verdict" :class="sim.safe_to_enforce ? 'opa-verdict--ok' : 'opa-verdict--bad'">
          <Icon :name="sim.safe_to_enforce ? 'mdi:shield-check' : 'mdi:alert-octagon'" />
          <span>{{ sim.verdict }}</span>
        </div>
        <!-- 100% flip almost always means the rule reads fields the replayed inputs do not carry,
             not that enforcement is catastrophic. Say so rather than let the number mislead. -->
        <p v-if="sim.evaluated > 0 && sim.would_break === sim.evaluated" class="opa-simwarn">
          Every replayed decision flipped. That usually means this rule reads input fields the
          filtered traffic does not contain, so the result says little about enforcement. Filter to
          the policy this rule belongs to, or drive traffic that exercises it first.
        </p>
        <div class="opa-simstats">
          <span>evaluated <b>{{ sim.evaluated }}</b></span>
          <span :class="{ 'opa-bad': sim.would_break > 0 }">would break <b>{{ sim.would_break }}</b></span>
          <span :class="{ 'opa-bad': sim.undecided > 0 }">undecided <b>{{ sim.undecided }}</b></span>
        </div>
        <div class="opa-tblwrap" v-if="breaking.length">
          <table class="opa-tbl">
            <thead><tr><th>TIME</th><th>POLICY</th><th>NOW</th><th>CANDIDATE</th><th>INPUT</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in breaking" :key="i" class="opa-row--bad">
                <td class="opa-mono">{{ (r.ts || '').slice(11, 19) }}</td>
                <td class="opa-mono">{{ shortPolicy(r.policy) }}</td>
                <td><span class="opa-b opa-b--y">allow</span></td>
                <td><span class="opa-b opa-b--n">deny</span></td>
                <td class="opa-mono opa-in">{{ compact(r.input) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import opaAdminApi, { type OpaStatus, type OpaDecision, type OpaPolicy, type OpaSimulation } from '@/services/api/opaAdmin'

const tabs = [
  { id: 'policies', label: 'POLICIES' },
  { id: 'decisions', label: 'DECISIONS' },
  { id: 'simulate', label: 'ENFORCE SIMULATOR' },
]
const tab = ref('policies')
const loading = ref(false)
const error = ref('')
const status = ref<OpaStatus | null>(null)
const policies = ref<OpaPolicy[]>([])
// §FESUITE (the failing-reads census, 2026-10-04): "No policies loaded." is an answer the policies' read gives; with the
// read failed the error above says so and the panel claims nothing
const policiesRead = ref(false)
const decisions = ref<OpaDecision[]>([])
// §FESUITE (V0578): the decisions read has its own state. It used to swallow its failure ("surfaced by refresh", which it
// never was: refresh awaits it and it cannot throw), so a failed read said "No decisions retained yet", and a failed
// re-read after "only disagreements" kept the previous unfiltered rows under the filter.
const decisionsRead = ref(false)
const decisionsFailed = ref(false)
// what the rows on screen answer: all decisions, or only the disagreements (the box can change before its read lands)
const decisionsMismatchOnly = ref(false)
let decisionsSeq = 0
const onlyMismatch = ref(false)
const openPolicy = ref('')

const rego = ref('')
const rulePath = ref('agentvault/agent_candidate/allow')
// Replaying decisions from policy A against a rule from policy B is meaningless — the inputs do
// not carry the fields the rule reads. Filtering to the matching policy keeps the answer truthful.
const policyFilter = ref('')
const sim = ref<OpaSimulation | null>(null)
const simRunning = ref(false)

const breaking = computed(() => (sim.value?.results || []).filter(r => r.would_break))

// `settled` flips only when refresh() reaches a terminal outcome (success OR retries exhausted),
// so the badge can distinguish "still trying" from "gave up". Without it the console flashes an
// amber UNKNOWN on every load, which trains operators to ignore the one badge that matters.
const settled = ref(false)
const modeLabel = computed(() => (status.value ? status.value.mode.toUpperCase() : (settled.value ? 'UNKNOWN' : 'LOADING')))
const modeClass = computed(() => (status.value ? status.value.mode : (settled.value ? 'unknown' : 'loading')))

const KIND_ORDER: Record<string, number> = { invariant: 0, domain: 1, mirror: 2 }
const sortedPolicies = computed(() =>
  [...policies.value].sort(
    (a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.package.localeCompare(b.package)
  )
)

function fmtBool(v: boolean | null) { return v === null || v === undefined ? 'n/a' : (v ? 'allow' : 'deny') }
function boolCls(v: boolean | null) { return v === null ? 'opa-b--u' : (v ? 'opa-b--y' : 'opa-b--n') }
function fmtPct(v: number | null | undefined) { return v === null || v === undefined ? '—' : v + '%' }
function shortPolicy(p: string) { return (p || '').replace('agentvault/', '').replace('/allow', '') }
function compact(o: Record<string, unknown>) {
  try {
    const s = JSON.stringify(o)
    return s.length > 90 ? s.slice(0, 90) + '…' : s
  } catch { return '' }
}

async function loadDecisions() {
  const seq = ++decisionsSeq
  const mismatchOnly = onlyMismatch.value
  try {
    const r = await opaAdminApi.decisions(200, mismatchOnly)
    if (seq !== decisionsSeq) return   // an older read landing after a newer one never replaces it
    decisions.value = r.decisions || []
    decisionsMismatchOnly.value = mismatchOnly
    decisionsFailed.value = false
    decisionsRead.value = true
  } catch {
    if (seq !== decisionsSeq) return
    decisions.value = []
    decisionsFailed.value = true
  }
}

// On a hard reload, onMounted fires before the Pinia auth store has rehydrated its token, so the
// first request 401s through no fault of the backend and the console would render UNKNOWN at an
// operator. Retry a bounded number of times with linear backoff for auth-shaped and network-shaped
// failures ONLY — a genuine 500 or a real permission denial must still surface immediately rather
// than being masked by retries.
async function refresh(attempt = 0) {
  loading.value = true; error.value = ''
  try {
    const [s, p] = await Promise.all([opaAdminApi.status(), opaAdminApi.policies()])
    status.value = s
    settled.value = true
    policies.value = p.policies || []
    policiesRead.value = true
    await loadDecisions()
    // Seed the simulator with the invariants policy so the flagship feature is one click away
    // rather than requiring the operator to paste rego from disk.
    // Seed with the live invariants policy, but REWRITTEN INTO A CANDIDATE PACKAGE.
    // Loading the source verbatim collides with the already-loaded package and OPA rejects it
    // ("multiple default rules data.agentvault.invariants.X found"), so the default state would
    // error on the very first click. A candidate package is also the honest workflow: you
    // simulate a PROPOSED policy, not the one already running.
    // Seed with a policy that ACTUALLY HAS captured traffic, rewritten into a candidate package.
    // Seeding the invariants policy looked smarter but was misleading: no live call site feeds it
    // yet, so replaying agent/admin inputs (which carry no rbac_mode) made every decision "flip",
    // and the UI reported "21 of 21 would break" when the truth is "this rule does not apply to
    // this traffic". A simulator's default must produce a TRUE answer, not a dramatic one.
    if (!rego.value) {
      const seed = policies.value.find(x => x.package === 'agentvault.agent')
        || policies.value.find(x => x.kind === 'mirror')
      if (seed) {
        rego.value = seed.source.replace(/^package\s+([\w.]+)/m, 'package $1_candidate')
        const m = seed.package.replace(/\./g, '/')
        rulePath.value = `${m}_candidate/allow`
        policyFilter.value = `${seed.package.replace(/\./g, '/')}/allow`
      }
    }
  } catch (e: any) {
    const st = e?.response?.status
    // 401/403 = token not rehydrated yet; undefined = network/abort mid-reload. Both are
    // transient on mount. Anything else is real and shown at once.
    //
    // 2026-07-29 — the residual UNKNOWN-on-load flake root-caused: this refresh does
    // Promise.all([status(), policies()]), and GET /admin/opa/policies answers
    // `502 "OPA unreachable: <exc>"` whenever the sidecar is momentarily unreachable
    // (worker start, or the DNS-saturation class). 502 was NOT in the transient set, so
    // ONE blip skipped the retry entirely and painted the amber UNKNOWN badge at an
    // operator while OPA was in fact healthy. 502/503/504 are infrastructure answers,
    // never a policy answer — retry them. A genuine 500 (a real backend fault) is still
    // surfaced immediately, which is the distinction that matters.
    const transient = st === 401 || st === 403 || st === undefined
      || st === 502 || st === 503 || st === 504
    if (transient && attempt < 4) {
      await new Promise(r => setTimeout(r, 400 * (attempt + 1)))
      return refresh(attempt + 1)   // still trying -> `settled` deliberately stays false
    }
    error.value = e?.response?.data?.detail || e?.message || 'Failed to load OPA state'
    settled.value = true            // gave up: UNKNOWN is now the honest answer
  } finally { loading.value = false }
}

async function runSim() {
  simRunning.value = true; sim.value = null; error.value = ''
  try {
    sim.value = await opaAdminApi.simulate(rego.value, rulePath.value, policyFilter.value || undefined)
  } catch (e: any) {
    // OPA compile errors arrive as a nested structure. Render the first rego error readably
    // (message + line) instead of dumping raw JSON at the operator; keep the rest available.
    const d = e?.response?.data?.detail ?? e?.response?.data?.error?.detail
    let msg = typeof d === 'string' ? d : ''
    try {
      const parsed = typeof d === 'string' ? JSON.parse(d) : d
      const first = parsed?.errors?.[0]
      if (first) {
        const row = first?.location?.row
        msg = `Policy did not compile: ${first.message}${row ? ` (line ${row})` : ''}`
      }
    } catch { /* keep msg as-is */ }
    error.value = msg || (d ? JSON.stringify(d) : 'Simulation failed')
  } finally { simRunning.value = false }
}

// Wrapped, NOT `onMounted(refresh)`: that would pass the hook's argument straight into `attempt`
// and silently start the retry counter at a non-zero value.
onMounted(() => refresh())
</script>

<style scoped>
.opa-page { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
.opa-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.25rem; }
.opa-title { font-size: 1.5rem; font-weight: 700; letter-spacing: .06em; margin: 0; color: var(--text-primary, #e6edf3); }
.opa-sub { margin: .25rem 0 0; font-size: .85rem; opacity: .65; }
.opa-head-r { display: flex; align-items: center; gap: .6rem; }
.opa-mode { font-size: .7rem; font-weight: 700; letter-spacing: .1em; padding: .3rem .6rem; border-radius: 4px; border: 1px solid; }
.opa-mode--off { color: #8b949e; border-color: #8b949e55; background: #8b949e14; }
/* Deliberately amber, not grey: "we could not read this" is a warning, not a calm off-state. */
.opa-mode--unknown { color: #d29922; border-color: #d2992255; background: #d2992214; }
/* Neutral + subdued: an in-flight read is not news and must not look like a fault. */
.opa-mode--loading { color: #8b949e; border-color: #8b949e33; background: #8b949e0d; opacity: .75; }
.opa-mode--shadow { color: #58a6ff; border-color: #58a6ff55; background: #58a6ff14; }
.opa-mode--enforce { color: #3fb950; border-color: #3fb95055; background: #3fb95014; }
.opa-btn { display: inline-flex; align-items: center; gap: .4rem; background: transparent; color: var(--text-primary, #e6edf3);
  border: 1px solid var(--border-color, #30363d); border-radius: 6px; padding: .4rem .8rem; font-size: .75rem; letter-spacing: .08em; cursor: pointer; }
.opa-btn:hover:not(:disabled) { border-color: #58a6ff; color: #58a6ff; }
.opa-btn:disabled { opacity: .5; cursor: not-allowed; }
.opa-btn:focus-visible, .opa-tab:focus-visible, .opa-inp:focus-visible, .opa-ta:focus-visible { outline: 2px solid #58a6ff; outline-offset: 2px; }
.opa-btn--go { border-color: #3fb95055; color: #3fb950; }
.opa-spin { animation: opaspin 1s linear infinite; }
@keyframes opaspin { to { transform: rotate(360deg); } }
.opa-err { color: #f85149; font-size: .85rem; margin: .5rem 0; }
.opa-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .75rem; margin-bottom: 1rem; }
.opa-stat { border: 1px solid var(--border-color, #30363d); border-radius: 8px; padding: .8rem 1rem; display: flex; flex-direction: column; gap: .2rem; }
.opa-stat--warn { border-color: #d2992255; }
.opa-stat-k { font-size: .65rem; letter-spacing: .12em; opacity: .6; }
.opa-stat-v { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.opa-stat-v small { font-size: .7rem; opacity: .5; margin-left: .15rem; }
.opa-stat-n { font-size: .68rem; opacity: .5; }
.opa-note { display: flex; gap: .6rem; align-items: flex-start; border: 1px solid #58a6ff33; background: #58a6ff0d;
  border-radius: 8px; padding: .7rem .9rem; font-size: .78rem; line-height: 1.5; opacity: .9; margin-bottom: 1.1rem; }
.opa-note code { font-size: .72rem; padding: .05rem .3rem; border-radius: 3px; background: #ffffff12; }
.opa-tabs { display: flex; gap: .4rem; border-bottom: 1px solid var(--border-color, #30363d); margin-bottom: 1rem; flex-wrap: wrap; }
.opa-tab { background: transparent; border: none; border-bottom: 2px solid transparent; color: inherit; opacity: .6;
  padding: .5rem .9rem; font-size: .75rem; letter-spacing: .09em; cursor: pointer; }
.opa-tab--on { opacity: 1; border-bottom-color: #58a6ff; color: #58a6ff; }
.opa-panel { min-height: 200px; }
.opa-pol { border: 1px solid var(--border-color, #30363d); border-radius: 8px; margin-bottom: .55rem; overflow: hidden; }
.opa-pol-h { display: flex; align-items: center; gap: .7rem; padding: .7rem .9rem; cursor: pointer; }
.opa-pol-h:hover { background: #ffffff08; }
.opa-pol-pkg { font-family: ui-monospace, monospace; font-size: .82rem; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.opa-pol-meta { font-size: .7rem; opacity: .55; white-space: nowrap; }
.opa-kind { font-size: .6rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; padding: .18rem .45rem; border-radius: 3px; border: 1px solid; }
.opa-kind--mirror { color: #8b949e; border-color: #8b949e55; }
.opa-kind--invariant { color: #3fb950; border-color: #3fb95055; }
.opa-kind--domain { color: #a371f7; border-color: #a371f755; }
.opa-rules { display: flex; flex-wrap: wrap; gap: .35rem; padding: 0 .9rem .75rem; }
.opa-rule { font-family: ui-monospace, monospace; font-size: .68rem; padding: .18rem .45rem; border-radius: 3px;
  border: 1px solid var(--border-color, #30363d); background: #ffffff08; opacity: .8; }
.opa-src { margin: 0; padding: .9rem; background: #0d1117; border-top: 1px solid var(--border-color, #30363d);
  font-size: .72rem; line-height: 1.55; overflow-x: auto; white-space: pre; }
.opa-check { display: inline-flex; align-items: center; gap: .4rem; font-size: .75rem; opacity: .8; margin-bottom: .6rem; cursor: pointer; }
.opa-tblwrap { overflow-x: auto; border: 1px solid var(--border-color, #30363d); border-radius: 8px; }
.opa-tbl { width: 100%; border-collapse: collapse; font-size: .76rem; }
.opa-tbl th { text-align: left; font-size: .63rem; letter-spacing: .1em; opacity: .55; padding: .55rem .7rem; border-bottom: 1px solid var(--border-color, #30363d); white-space: nowrap; }
.opa-tbl td { padding: .45rem .7rem; border-bottom: 1px solid #ffffff0a; }
.opa-row--bad { background: #f8514912; }
.opa-mono { font-family: ui-monospace, monospace; }
.opa-in { max-width: 460px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; opacity: .75; }
.opa-b { font-size: .66rem; font-weight: 700; letter-spacing: .06em; padding: .12rem .4rem; border-radius: 3px; border: 1px solid; }
.opa-b--y { color: #3fb950; border-color: #3fb95055; }
.opa-b--n { color: #f85149; border-color: #f8514955; }
.opa-b--u { color: #8b949e; border-color: #8b949e55; }
.opa-empty { opacity: .5; font-size: .8rem; padding: 1.4rem 0; }
.opa-simhelp { font-size: .78rem; opacity: .7; line-height: 1.55; margin: 0 0 .8rem; max-width: 74ch; }
.opa-simrow { display: flex; gap: .5rem; margin-bottom: .6rem; flex-wrap: wrap; }
.opa-inp { flex: 1; min-width: 240px; background: #0d1117; border: 1px solid var(--border-color, #30363d); border-radius: 6px;
  color: inherit; padding: .45rem .7rem; font-family: ui-monospace, monospace; font-size: .78rem; }
.opa-ta { width: 100%; background: #0d1117; border: 1px solid var(--border-color, #30363d); border-radius: 8px; color: inherit;
  padding: .8rem; font-family: ui-monospace, monospace; font-size: .72rem; line-height: 1.55; resize: vertical; }
.opa-simout { margin-top: 1rem; }
.opa-verdict { display: flex; align-items: center; gap: .55rem; padding: .7rem .9rem; border-radius: 8px; border: 1px solid; font-size: .82rem; }
.opa-verdict--ok { color: #3fb950; border-color: #3fb95055; background: #3fb9500d; }
.opa-verdict--bad { color: #d29922; border-color: #d2992255; background: #d299220d; }
.opa-simwarn { font-size: .76rem; line-height: 1.55; opacity: .8; border-left: 2px solid #d29922; padding: .4rem .7rem; margin: .6rem 0; max-width: 78ch; }
.opa-simstats { display: flex; gap: 1.2rem; font-size: .76rem; opacity: .8; margin: .7rem 0; flex-wrap: wrap; }
.opa-bad { color: #f85149; }
@media (max-width: 640px) {
  .opa-page { padding: 1rem .75rem; }
  .opa-head { flex-direction: column; align-items: stretch; }
  .opa-in { max-width: 160px; }
  .opa-title { font-size: 1.2rem; }
}
</style>
