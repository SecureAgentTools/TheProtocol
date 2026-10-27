<template>
  <div class="cs" data-testid="cs-page">
    <section class="cs-hero">
      <div class="cs-hero-inner">
        <div class="cs-chip"><span class="cs-chip-dot"></span>{{ tr('consoleSuite.head.badge', 'CONSOLE LIFECYCLE SUITE') }}</div>
        <h1 class="cs-h1">{{ tr('consoleSuite.head.title1', 'Console') }} <span class="cs-accent">{{ tr('consoleSuite.head.title2', 'Suite') }}</span></h1>
        <p class="cs-lead">
          {{ tr('consoleSuite.hero.lead', 'A browser walks this console the way people use it: it registers, signs in, creates and deletes, reads every page, on a desktop screen and on a phone, and checks what each step shows against what the API holds. Every request, console error and refusal along the way is recorded. It runs only against a sandbox frame, and each run it makes is recorded here.') }}
        </p>
        <div class="cs-meta-row">
          <span class="cs-meta">
            <span class="cs-meta-key">{{ tr('consoleSuite.head.history', 'HISTORY') }}</span>
            <span class="cs-meta-val" data-testid="cs-history-count">{{ tp('consoleSuite.head.historyOf', '{n} of {cap} runs kept', { n: runsRead ? total : '—', cap: runsRead ? cap : '—' }) }}</span>
          </span>
          <span v-if="runs.length" class="cs-meta">
            <span class="cs-meta-key">{{ tr('consoleSuite.head.latest', 'LATEST') }}</span>
            <span class="cs-meta-val">{{ fmtWhen(runs[0].started_at) }}</span>
          </span>
          <!-- §FESUITE: back to the MCP tester's own history (its History tab), not its live log -->
          <router-link :to="{ path: '/admin/mcp-tester', query: { tab: 'history' } }" class="cs-link" data-testid="cs-to-mcp-tester">
            <Icon name="mdi:bug-check-outline" class="cs-link-icon" aria-hidden="true" />{{ tr('consoleSuite.head.toMcp', 'MCP Tester') }}
          </router-link>
          <button type="button" class="cs-link cs-link--btn" :disabled="loading" data-testid="cs-reload" @click="reload">
            <Icon name="mdi:refresh" class="cs-link-icon" aria-hidden="true" />{{ tr('consoleSuite.head.reload', 'Reload') }}
          </button>
        </div>
      </div>
    </section>

    <section class="cs-section">
      <p v-if="loadError" class="cs-banner cs-banner--bad" role="alert" data-testid="cs-error">{{ loadError }}</p>
      <div v-else-if="!loading && runs.length === 0" class="cs-empty" data-testid="cs-empty">
        <Icon name="mdi:history" class="cs-empty-icon" aria-hidden="true" />
        <p>{{ tr('consoleSuite.empty.none', 'No run is recorded on this frame yet.') }}</p>
        <p class="cs-muted">{{ tr('consoleSuite.empty.how', 'The suite runs on the host (scripts/fesuite/run.py) against a sandbox frame and records each run in the history of the frame it tested.') }}</p>
      </div>
      <template v-else>
        <div class="cs-filters" role="group" :aria-label="tr('consoleSuite.filter.label', 'Show')">
          <button v-for="f in FILTERS" :key="f" type="button" class="cs-filter" :class="{ 'is-on': filter === f }"
                  :aria-pressed="filter === f" :data-testid="`cs-filter-${f}`" @click="filter = f">
            {{ filterLabel(f) }} <span class="cs-filter-n" :data-count="filterCount(f)">{{ runsRead ? filterCount(f) : '—' }}</span>
          </button>
        </div>
        <ul class="cs-runs" data-testid="cs-runs">
          <li v-for="r in shownRuns" :key="r.run_id">
            <button type="button" class="cs-run" :class="[`is-${runVerdict(r)}`, { 'is-open': r.run_id === openId }]"
                    :aria-expanded="r.run_id === openId" :data-run="r.run_id" data-testid="cs-run-row" @click="openRun(r.run_id)">
              <span class="cs-run-dot" :title="verdictLabel(runVerdict(r))" aria-hidden="true"></span>
              <span class="cs-run-when">{{ fmtWhen(r.started_at) }}</span>
              <span class="cs-run-scope">{{ scopeLine(r) }}</span>
              <span class="cs-run-lcs">{{ tp('consoleSuite.run.lifecycles', '{passed} of {total} lifecycles', { passed: r.summary.lifecycles_passed ?? '—', total: r.summary.lifecycles ?? '—' }) }}</span>
              <span class="cs-run-counts">
                <span class="cs-count cs-count--ok" :title="tr('consoleSuite.count.passed', 'steps passed')">{{ r.summary.passed ?? 0 }}✓</span>
                <span class="cs-count cs-count--bad" :title="tr('consoleSuite.count.failed', 'steps failed')">{{ r.summary.failed ?? 0 }}✗</span>
                <span class="cs-count cs-count--muted" :title="tr('consoleSuite.count.skipped', 'steps not measured')">{{ r.summary.skipped ?? 0 }}—</span>
              </span>
              <span class="cs-run-verdict">{{ verdictLabel(runVerdict(r)) }}</span>
            </button>
          </li>
        </ul>
        <p v-if="shownRuns.length === 0" class="cs-muted" data-testid="cs-filter-empty">{{ tr('consoleSuite.filter.none', 'No run in the history matches this filter.') }}</p>
      </template>
    </section>

    <section v-if="openId" class="cs-section" data-testid="cs-run-detail" :data-run="openId">
      <p v-if="runLoading" class="cs-muted">{{ tr('consoleSuite.run.loading', 'Reading the run…') }}</p>
      <p v-else-if="runError" class="cs-banner cs-banner--bad" role="alert">{{ runError }}</p>
      <template v-else-if="run">
        <header class="cs-run-head">
          <h2 class="cs-h2">{{ tp('consoleSuite.run.title', 'Run {id}', { id: run.run_id }) }}</h2>
          <p class="cs-muted">
            {{ tp('consoleSuite.run.when', 'Started {start}, took {wall}, against {target}.', { start: fmtWhen(run.started_at), wall: fmtDuration(wallOf(run)), target: run.summary.target || run.scope.target || '—' }) }}
            {{ scopeSentence(run) }}
          </p>
        </header>
        <div class="cs-tiles">
          <div class="cs-tile" data-testid="cs-tile-rate">
            <span class="cs-tile-label">{{ tr('consoleSuite.tile.rate', 'Steps passed') }}</span>
            <span class="cs-tile-value">{{ typeof run.summary.pass_pct === 'number' ? run.summary.pass_pct.toFixed(2) + '%' : '—' }}</span>
            <span class="cs-tile-sub">{{ tp('consoleSuite.tile.rateSub', '{passed} passed · {failed} failed · {skipped} not measured', { passed: run.summary.passed ?? 0, failed: run.summary.failed ?? 0, skipped: run.summary.skipped ?? 0 }) }}</span>
          </div>
          <div class="cs-tile" data-testid="cs-tile-lifecycles">
            <span class="cs-tile-label">{{ tr('consoleSuite.tile.lifecycles', 'Lifecycles') }}</span>
            <span class="cs-tile-value">{{ run.summary.lifecycles_passed ?? '—' }}<span class="cs-tile-of"> / {{ run.summary.lifecycles ?? '—' }}</span></span>
            <span class="cs-tile-sub">{{ tr('consoleSuite.tile.lifecyclesSub', 'passed whole') }}</span>
          </div>
          <div class="cs-tile" data-testid="cs-tile-browser">
            <span class="cs-tile-label">{{ tr('consoleSuite.tile.browser', 'Browser') }}</span>
            <span class="cs-tile-value" :class="{ 'is-bad': totals.consoleErrors + totals.pageErrors > 0 }">{{ totals.consoleErrors + totals.pageErrors }}</span>
            <span class="cs-tile-sub">{{ tp('consoleSuite.tile.browserSub', '{c} console errors · {p} page errors in {r} requests', { c: totals.consoleErrors, p: totals.pageErrors, r: totals.requests }) }}</span>
          </div>
          <div class="cs-tile" data-testid="cs-tile-refused">
            <span class="cs-tile-label">{{ tr('consoleSuite.tile.refused', 'Refusals nobody allowed') }}</span>
            <span class="cs-tile-value" :class="{ 'is-bad': totals.refused > 0 }">{{ totals.refused }}</span>
            <span class="cs-tile-sub">{{ tr('consoleSuite.tile.refusedSub', 'a 4xx a step did not expect') }}</span>
          </div>
        </div>

        <div v-if="run.hard_fails.length" class="cs-box cs-box--bad" data-testid="cs-failures">
          <h3 class="cs-h3">{{ tp('consoleSuite.fail.title', 'What failed ({n})', { n: run.hard_fails.length }) }}</h3>
          <ul class="cs-list">
            <li v-for="(f, i) in run.hard_fails" :key="`f${i}`"><code class="cs-tool">{{ f.tool }}</code><span class="cs-said">{{ f.error }}</span></li>
          </ul>
        </div>
        <div v-if="run.expected_reds.length" class="cs-box cs-box--known" data-testid="cs-known">
          <h3 class="cs-h3">{{ tp('consoleSuite.known.title', 'Known and named, not yet fixed ({n})', { n: run.expected_reds.length }) }}</h3>
          <ul class="cs-list">
            <li v-for="(f, i) in run.expected_reds" :key="`k${i}`"><code class="cs-tool">{{ f.tool }}</code><span class="cs-said">{{ f.error || f.reason }}</span></li>
          </ul>
        </div>
        <div v-if="totals.unexpected.length" class="cs-box" data-testid="cs-unexpected">
          <h3 class="cs-h3">{{ tr('consoleSuite.unexpected.title', 'Requests that answered what no step expected') }}</h3>
          <ul class="cs-list"><li v-for="(u, i) in totals.unexpected" :key="`u${i}`"><span class="cs-said">{{ u }}</span></li></ul>
        </div>

        <h3 class="cs-h3 cs-h3--gap">{{ tp('consoleSuite.lc.title', 'Lifecycles ({n})', { n: lifecycles.length }) }}</h3>
        <div class="cs-lcs" data-testid="cs-lifecycles">
          <details v-for="lc in lifecycles" :key="lc.key" class="cs-lc" :class="`is-${lc.verdict}`" :open="lc.verdict === 'failed'"
                   data-testid="cs-lifecycle" :data-lifecycle="lc.name" :data-project="lc.project">
            <summary class="cs-lc-sum">
              <Icon name="mdi:chevron-right" class="cs-lc-chev" aria-hidden="true" />
              <span class="cs-lc-dot" aria-hidden="true"></span>
              <span class="cs-lc-title">{{ lc.title }}</span>
              <span v-for="tg in lc.tags" :key="tg" class="cs-tag">{{ tg }}</span>
              <span class="cs-proj" :class="`is-${lc.project}`">
                <Icon v-if="lc.project === 'phone'" name="mdi:cellphone" class="cs-proj-icon" aria-hidden="true" />{{ projectLabel(lc.project) }}
              </span>
              <span class="cs-lc-counts">
                {{ lc.counts.pass }}✓<template v-if="lc.counts.fail"> · {{ lc.counts.fail }}✗</template><template v-if="lc.counts.known"> · {{ lc.counts.known }}!</template><template v-if="lc.counts.skip"> · {{ lc.counts.skip }}—</template>
              </span>
              <span class="cs-lc-time">{{ fmtDuration(lc.duration_s) }}</span>
            </summary>
            <ul class="cs-steps">
              <li v-for="st in lc.steps" :key="st.tool" class="cs-step" :class="`is-${st.outcome}`"
                  data-testid="cs-step" :data-outcome="st.outcome" :data-step="st.tool">
                <span class="cs-step-badge">{{ outcomeLabel(st.outcome) }}</span>
                <span class="cs-step-name">{{ st.step }}</span>
                <span class="cs-step-tier">{{ st.tier }}</span>
                <span class="cs-step-said">{{ st.said }}</span>
              </li>
              <li v-if="lc.steps.length === 0" class="cs-step cs-muted">{{ tr('consoleSuite.lc.noSteps', 'This lifecycle recorded no step.') }}</li>
            </ul>
          </details>
        </div>

        <details v-if="run.skipped.length" class="cs-fold" data-testid="cs-skipped">
          <summary>{{ tp('consoleSuite.skip.title', 'Not measured ({n}): what this frame could not show', { n: run.skipped.length }) }}</summary>
          <ul class="cs-list"><li v-for="(s, i) in run.skipped" :key="`s${i}`"><code class="cs-tool">{{ s.tool }}</code><span class="cs-said">{{ s.reason || s.error }}</span></li></ul>
        </details>
        <details v-if="run.log_lines.length" class="cs-fold" data-testid="cs-log">
          <summary>{{ tp('consoleSuite.log.title', 'The runner\'s log ({n} lines)', { n: run.log_lines.length }) }}</summary>
          <ol class="cs-log"><li v-for="(l, i) in run.log_lines" :key="`l${i}`"><span class="cs-log-ts">{{ (l.ts || '').slice(11, 19) }}</span> {{ l.msg }}</li></ol>
        </details>
      </template>
    </section>
  </div>
</template>

<script setup lang="ts">
// §MCPTEST30 (V0555, 2026-10-03): the console suite's runs, visible. His word: "make sure to make the frontend suite runs
// also visible. if it makes sense make a new test page for it". Its own page: the suite's question is which lifecycle, on
// which screen, did what, and its history is its own (routers/console_suite.py), apart from the MCP tester's 60 runs.
import { ref, computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { consoleSuiteApi, type ConsoleSuiteRun, type ConsoleSuiteRunMeta } from '@/services/api/consoleSuite'
import { fmtDuration } from '@/services/mcpTester/runReading'
import {
  groupRun, runVerdict, readScope, filterRuns, captureTotals, type RunVerdict, type StepOutcome,
} from '@/services/consoleSuite/reading'

const { t: tr, tp } = useI18n()

const FILTERS = ['all', 'whole', 'failed'] as const
type Filter = typeof FILTERS[number]

const runs = ref<ConsoleSuiteRunMeta[]>([])
const total = ref(0)
const cap = ref(0)
const loading = ref(false)
const loadError = ref('')
/** §FESUITE (the loading sweep): set when the read succeeds, never by a failure; until then the figures show a dash (a 0 says "none"). */
const runsRead = ref(false)
const filter = ref<Filter>('all')
const openId = ref<string | null>(null)
const run = ref<ConsoleSuiteRun | null>(null)
const runLoading = ref(false)
const runError = ref('')

const shownRuns = computed(() => filterRuns(runs.value, filter.value))
const lifecycles = computed(() => (run.value ? groupRun(run.value) : []))
const totals = computed(() => captureTotals(run.value?.lifecycles || []))

function why(e: any): string {
  const d = e?.response?.data?.detail
  return typeof d === 'string' ? d : (e?.message || String(e))
}

async function reload() {
  loading.value = true
  loadError.value = ''
  try {
    const got = await consoleSuiteApi.listRuns(120)
    runs.value = got.runs || []
    total.value = got.total || 0
    cap.value = got.cap || 0
    runsRead.value = true
    if (!openId.value && runs.value.length) await openRun(runs.value[0].run_id)
  } catch (e) {
    loadError.value = tp('consoleSuite.err.list', 'The history could not be read: {why}', { why: why(e) })
  } finally {
    loading.value = false
  }
}

async function openRun(id: string) {
  if (openId.value === id && run.value) return
  openId.value = id
  run.value = null
  runError.value = ''
  runLoading.value = true
  try {
    const got = await consoleSuiteApi.getRun(id)
    if (openId.value === id) run.value = got        // a later click wins over a slower answer
  } catch (e) {
    if (openId.value === id) runError.value = tp('consoleSuite.err.run', 'Run {id} could not be read: {why}', { id, why: why(e) })
  } finally {
    if (openId.value === id) runLoading.value = false
  }
}

function fmtWhen(ts: number | null | undefined): string {
  if (!ts) return '—'
  return new Date(ts * 1000).toLocaleString(appLocale(), {
    month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function wallOf(r: ConsoleSuiteRun): number | null {
  if (typeof r.finished_at === 'number' && r.finished_at >= r.started_at) return r.finished_at - r.started_at
  return typeof r.summary.wall_s === 'number' ? r.summary.wall_s : null
}

function filterLabel(f: Filter): string {
  if (f === 'whole') return tr('consoleSuite.filter.whole', 'Whole suite')
  if (f === 'failed') return tr('consoleSuite.filter.failed', 'With a failure')
  return tr('consoleSuite.filter.all', 'Every run')
}

function filterCount(f: Filter): number {
  return filterRuns(runs.value, f).length
}

function verdictLabel(v: RunVerdict): string {
  return {
    failed: tr('consoleSuite.verdict.failed', 'failed'),
    known: tr('consoleSuite.verdict.known', 'known reds'),
    clean: tr('consoleSuite.verdict.clean', 'clean'),
    error: tr('consoleSuite.verdict.error', 'did not finish'),
    running: tr('consoleSuite.verdict.running', 'running'),
  }[v]
}

function outcomeLabel(o: StepOutcome): string {
  return {
    pass: tr('consoleSuite.outcome.pass', 'PASS'),
    fail: tr('consoleSuite.outcome.fail', 'FAIL'),
    skip: tr('consoleSuite.outcome.skip', 'NOT MEASURED'),
    known: tr('consoleSuite.outcome.known', 'KNOWN'),
  }[o]
}

function projectLabel(p: string): string {
  if (p === 'phone') return tr('consoleSuite.project.phone', 'phone')
  if (p === 'desktop') return tr('consoleSuite.project.desktop', 'desktop')
  return p
}

function scopeLine(r: ConsoleSuiteRunMeta): string {
  const s = readScope(r)
  if (s.whole === true) return tr('consoleSuite.scope.whole', 'Whole suite')
  if (s.pattern) return tp('consoleSuite.scope.pattern', 'Lifecycles matching “{p}”', { p: s.pattern })
  if (s.whole === false) return tp('consoleSuite.scope.part', 'Part of the suite ({n} lifecycles)', { n: s.lifecycles })
  return tp('consoleSuite.scope.unknown', '{n} lifecycles', { n: s.lifecycles })
}

// whole sentences, each its own key: fragments joined in code do not survive translation (PART 1, §LOCALESWEEP)
function scopeSentence(r: ConsoleSuiteRun): string {
  const s = readScope(r)
  const out = [s.whole === true ? tr('consoleSuite.scope.sentenceWhole', 'It ran the whole suite.')
    : s.pattern ? tp('consoleSuite.scope.sentencePattern', 'It ran the lifecycles matching “{p}”.', { p: s.pattern })
      : tp('consoleSuite.scope.sentenceN', 'It ran {n} lifecycles.', { n: s.lifecycles })]
  if (s.project && s.project !== 'all') out.push(tp('consoleSuite.scope.sentenceProject', 'Only the {p} screen.', { p: projectLabel(s.project) }))
  if (s.by) out.push(tp('consoleSuite.scope.sentenceBy', 'Recorded by {by}.', { by: s.by }))
  return out.join(' ')
}

onMounted(reload)
</script>

<style scoped>
.cs {
  position: relative; min-height: 100vh; padding: 0 0 40px; color: var(--text-primary, #e8eaed);
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366; --green: #00ff88; --amber: #ffb84d;
  --muted: #788593;
  --border: rgba(var(--cyan-rgb), 0.18);
  --surface: rgba(10, 13, 22, 0.85);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed;
}
.cs-hero { position: relative; z-index: 1; padding: 48px 32px 16px; }
.cs-hero-inner, .cs-section { max-width: 1280px; margin: 0 auto; }
.cs-section { position: relative; z-index: 1; margin-top: 20px; padding: 0 32px; }
.cs-chip {
  display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan); padding: 4px 12px; border: 1px solid rgba(var(--cyan-rgb), 0.25);
  border-radius: 99px; margin-bottom: 14px; background: rgba(var(--cyan-rgb), 0.04);
}
.cs-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }
.cs-h1 {
  font-family: 'Orbitron', 'IBM Plex Sans', sans-serif; font-weight: 800; font-size: 36px; letter-spacing: 0.02em;
  margin: 0 0 10px; color: var(--text-bright); line-height: 1.15;
}
.cs-accent { color: var(--cyan); text-shadow: 0 0 14px rgba(var(--cyan-rgb), 0.45); }
.cs-lead { color: var(--muted); font-size: 14px; max-width: 760px; line-height: 1.7; margin: 0; }
.cs-meta-row { display: flex; flex-wrap: wrap; align-items: center; gap: 18px; margin-top: 18px; }
.cs-meta { display: inline-flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 11px; }
.cs-meta-key { font-size: 9px; font-weight: 700; letter-spacing: 0.16em; color: rgba(var(--cyan-rgb), 0.7); }
.cs-meta-val { color: var(--text-bright); }
.cs-link {
  display: inline-flex; align-items: center; gap: 6px; font-family: var(--mono); font-size: 11px; color: var(--cyan);
  border: 1px solid var(--border); border-radius: 5px; padding: 5px 10px; text-decoration: none; background: transparent;
}
.cs-link--btn { cursor: pointer; }
.cs-link--btn:disabled { opacity: 0.5; cursor: default; }
.cs-link-icon { width: 14px; height: 14px; }
/* a run's scope can carry one long unbroken token (a grep of many lifecycle names): it wraps inside the line */
.cs-muted { color: var(--muted); font-size: 13px; line-height: 1.6; overflow-wrap: anywhere; }
.cs-banner { padding: 12px 16px; border-radius: 6px; font-size: 13px; }
.cs-banner--bad { background: rgba(255, 51, 102, 0.08); border: 1px solid rgba(255, 51, 102, 0.4); color: #ffb3c1; }
.cs-empty { text-align: center; padding: 40px 16px; border: 1px dashed var(--border); border-radius: 8px; }
.cs-empty-icon { width: 28px; height: 28px; color: var(--muted); }

.cs-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.cs-filter {
  font-family: var(--mono); font-size: 11px; color: var(--muted); background: transparent; cursor: pointer;
  border: 1px solid var(--border); border-radius: 99px; padding: 5px 12px;
}
.cs-filter.is-on { color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.6); background: rgba(var(--cyan-rgb), 0.08); }
.cs-filter-n { opacity: 0.7; margin-left: 4px; }

.cs-runs { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.cs-run {
  width: 100%; display: grid; align-items: center; gap: 12px; text-align: left; cursor: pointer;
  grid-template-columns: 12px 120px minmax(0, 1fr) 150px 150px 100px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px;
  color: var(--text-bright); font-size: 13px;
}
.cs-run.is-open { border-color: rgba(var(--cyan-rgb), 0.7); box-shadow: 0 0 0 1px rgba(var(--cyan-rgb), 0.25) inset; }
.cs-run-dot, .cs-lc-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--green); }
.cs-run.is-failed .cs-run-dot, .cs-lc.is-failed .cs-lc-dot { background: var(--red); }
.cs-run.is-known .cs-run-dot, .cs-lc.is-known .cs-lc-dot { background: var(--amber); }
.cs-run.is-error .cs-run-dot, .cs-lc.is-skipped .cs-lc-dot { background: var(--muted); }
.cs-run.is-running .cs-run-dot { background: var(--cyan); }
.cs-run-when { font-family: var(--mono); font-size: 12px; color: var(--muted); }
.cs-run-scope { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cs-run-lcs { font-family: var(--mono); font-size: 12px; }
.cs-run-counts { display: inline-flex; gap: 8px; font-family: var(--mono); font-size: 12px; font-variant-numeric: tabular-nums; }
.cs-count--ok { color: var(--green); }
.cs-count--bad { color: var(--red); }
.cs-count--muted { color: var(--muted); }
.cs-run-verdict { font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; text-align: right; }
.cs-run.is-failed .cs-run-verdict { color: var(--red); }
.cs-run.is-known .cs-run-verdict { color: var(--amber); }
.cs-run.is-clean .cs-run-verdict { color: var(--green); }

.cs-run-head { margin-bottom: 14px; }
.cs-h2 { font-family: var(--mono); font-size: 16px; margin: 0 0 6px; color: var(--text-bright); word-break: break-all; }
.cs-h3 { font-family: var(--mono); font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--cyan); margin: 0 0 8px; }
.cs-h3--gap { margin-top: 22px; }
.cs-tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.cs-tile {
  display: flex; flex-direction: column; gap: 4px; background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px; min-width: 0;
}
.cs-tile-label { font-family: var(--mono); font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase; color: rgba(var(--cyan-rgb), 0.75); }
.cs-tile-value { font-family: 'Orbitron', var(--mono); font-size: 26px; color: var(--text-bright); font-variant-numeric: tabular-nums; }
.cs-tile-value.is-bad { color: var(--red); }
.cs-tile-of { font-size: 16px; color: var(--muted); }
.cs-tile-sub { font-size: 12px; color: var(--muted); line-height: 1.5; }
.cs-box { border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; background: var(--surface); }
.cs-box--bad { border-color: rgba(255, 51, 102, 0.45); }
.cs-box--known { border-color: rgba(255, 184, 77, 0.45); }
.cs-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.cs-list li { display: grid; gap: 2px; min-width: 0; }
.cs-tool { font-family: var(--mono); font-size: 12px; color: var(--text-bright); overflow-wrap: anywhere; }
.cs-said { font-size: 12.5px; color: var(--muted); line-height: 1.5; overflow-wrap: anywhere; white-space: pre-wrap; }

.cs-lcs { display: grid; gap: 6px; }
.cs-lc { border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
.cs-lc.is-failed { border-color: rgba(255, 51, 102, 0.45); }
.cs-lc-sum {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; list-style: none;
  font-size: 13px;
}
.cs-lc-sum::-webkit-details-marker { display: none; }
.cs-lc-chev { width: 14px; height: 14px; color: var(--muted); transition: transform 0.15s; }
.cs-lc[open] .cs-lc-chev { transform: rotate(90deg); }
.cs-lc-title { font-family: var(--mono); color: var(--text-bright); overflow-wrap: anywhere; }
.cs-tag, .cs-proj {
  font-family: var(--mono); font-size: 10px; border: 1px solid var(--border); border-radius: 99px; padding: 1px 8px; color: var(--muted);
}
.cs-proj { display: inline-flex; align-items: center; gap: 4px; }
.cs-proj.is-phone { color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.45); }
.cs-proj-icon { width: 12px; height: 12px; }
.cs-lc-counts { margin-left: auto; font-family: var(--mono); font-size: 12px; font-variant-numeric: tabular-nums; }
.cs-lc-time { font-family: var(--mono); font-size: 12px; color: var(--muted); min-width: 56px; text-align: right; }
.cs-steps { list-style: none; margin: 0; padding: 0 14px 10px; display: grid; gap: 4px; }
.cs-step {
  display: grid; grid-template-columns: 112px minmax(0, 1.2fr) 80px minmax(0, 2fr); gap: 10px; align-items: baseline;
  padding: 6px 8px; border-radius: 4px; font-size: 12.5px; background: rgba(255, 255, 255, 0.02);
}
.cs-step-badge { font-family: var(--mono); font-size: 10px; letter-spacing: 0.08em; }
.cs-step.is-pass .cs-step-badge { color: var(--green); }
.cs-step.is-fail .cs-step-badge { color: var(--red); }
.cs-step.is-known .cs-step-badge { color: var(--amber); }
.cs-step.is-skip .cs-step-badge { color: var(--muted); }
.cs-step-name { font-family: var(--mono); color: var(--text-bright); overflow-wrap: anywhere; }
.cs-step-tier { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.cs-step-said { color: var(--muted); overflow-wrap: anywhere; white-space: pre-wrap; }
.cs-fold { margin-top: 14px; border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px; background: var(--surface); }
.cs-fold > summary { cursor: pointer; font-family: var(--mono); font-size: 12px; color: var(--cyan); }
.cs-fold .cs-list { margin-top: 10px; }
.cs-log { margin: 10px 0 0; padding-left: 0; list-style: none; font-family: var(--mono); font-size: 11.5px; color: var(--muted); }
.cs-log li { overflow-wrap: anywhere; }
.cs-log-ts { color: rgba(var(--cyan-rgb), 0.7); }

@media (max-width: 900px) {
  .cs-tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .cs-run { grid-template-columns: 12px minmax(0, 1fr) auto; }
  .cs-run-scope { grid-column: 2 / -1; white-space: normal; }
  .cs-run-lcs, .cs-run-counts { grid-column: 2 / -1; }
  .cs-run-verdict { grid-column: 3; grid-row: 1; }
}
@media (max-width: 600px) {
  .cs-hero { padding: 28px 16px 12px; }
  .cs-section { padding: 0 16px; }
  .cs-h1 { font-size: 28px; }
  .cs-tiles { grid-template-columns: minmax(0, 1fr); }
  .cs-step { grid-template-columns: minmax(0, 1fr); gap: 2px; }
  .cs-lc-counts { margin-left: 0; }
}
</style>
