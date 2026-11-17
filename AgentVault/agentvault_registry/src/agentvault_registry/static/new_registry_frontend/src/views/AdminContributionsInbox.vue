<!--
  V0666 D2 (order gwo_f565ebd0575703f199dd9200; design section 5: one admin view where every line's change arrives): the Contributions inbox,
  #/admin/contributions (platform admins, admin_platform). Every release line's changes (an organization's code distribution, never an AGORA payout)
  across all organizations in one queue, newest first; filters by organization, line, state and sensitive; the signed checker's record per change; a line
  paused with a reason and resumed; the platform maintainer's veto and go on a line's change (the registry takes them from his account only). Room is left
  for what comes later and nothing is shown for it yet: upstream proposals (D4), the fast lane's content changes (D5), the line's builds (D6).
-->
<template>
  <div class="cti" data-testid="cti-root">
    <header class="cti-hero">
      <span class="cti-eyebrow">{{ t('contributions.admin.eyebrow', 'Administration') }}</span>
      <h1>{{ t('contributions.admin.title', 'Contributions inbox') }}</h1>
      <p class="cti-lede">{{ t('contributions.admin.intro', 'Every organization’s release lines and their changes arrive here: our checker’s record on each, the pause of a line, and the platform’s veto.') }}</p>
    </header>

    <p v-if="cfgOff" class="cti-note cti-off" role="status" data-testid="cti-off">{{ t('contributions.off', 'Code distributions are off on this registry.') }}</p>
    <div v-else-if="readFailed" class="cti-error" role="alert"><p>{{ t('contributions.cfgError', 'This registry’s settings could not be read; try again.') }}</p>
      <button type="button" class="cti-btn" @click="reload">{{ t('contributions.retry', 'Try again') }}</button></div>
    <p v-else-if="!cfgOn" class="cti-note" role="status">{{ t('contributions.reading', 'Reading this registry’s settings') }}</p>

    <template v-else>
      <p v-if="loading && !lines.length" class="cti-note" role="status">{{ t('contributions.lines.loading', 'Reading the release lines') }}</p>
      <div v-else-if="loadError" class="cti-error" role="alert" data-testid="cti-error"><p>{{ loadError }}</p>
        <button type="button" class="cti-btn" @click="load">{{ t('contributions.retry', 'Try again') }}</button></div>
      <p v-else-if="!lines.length" class="cti-note" data-testid="cti-no-lines">{{ t('contributions.admin.noLines', 'No organization has a release line on this registry yet.') }}</p>
      <section v-if="lines.length" class="cti-queue" data-testid="cti-queue">
        <div class="cti-bar">
          <h2>{{ tp('contributions.admin.queue', 'Changes ({n})', { n: shown.length }) }}</h2>
          <div class="cti-filters" role="group" :aria-label="t('contributions.admin.filters', 'Filter the changes')">
            <label><span>{{ t('contributions.admin.fOrg', 'Organization') }}</span>
              <select v-model="f.organization" data-testid="cti-f-org"><option value="">{{ t('contributions.admin.all', 'All') }}</option>
                <option v-for="o in orgIds" :key="o" :value="o" :title="o">{{ orgName(o) }}</option></select></label>
            <label><span>{{ t('contributions.admin.fLine', 'Line') }}</span>
              <select v-model="f.line" data-testid="cti-f-line"><option value="">{{ t('contributions.admin.all', 'All') }}</option>
                <option v-for="l in lines" :key="l.slug" :value="l.slug">{{ l.title }}</option></select></label>
            <label><span>{{ t('contributions.admin.fState', 'State') }}</span>
              <select v-model="f.lane" data-testid="cti-f-state"><option value="">{{ t('contributions.admin.all', 'All') }}</option>
                <option v-for="l in LANES" :key="l" :value="l">{{ laneWord(l, tr) }}</option></select></label>
            <label><span>{{ t('contributions.admin.fSensitive', 'Sensitive') }}</span>
              <select v-model="f.sensitive" data-testid="cti-f-sensitive"><option value="any">{{ t('contributions.admin.all', 'All') }}</option>
                <option value="yes">{{ t('contributions.admin.sensitiveYes', 'Sensitive only') }}</option><option value="no">{{ t('contributions.admin.sensitiveNo', 'Not sensitive') }}</option></select></label>
          </div>
        </div>
        <p v-if="partial" class="cti-small cti-warn" role="status" data-testid="cti-partial">{{ tp('contributions.admin.partial', 'The changes of {n} of {all} release lines could not be read: the queue is incomplete.', { n: partial, all: lines.length }) }}</p>
        <p v-if="!loading && !rows.length && lines.length" class="cti-note" data-testid="cti-empty">{{ t('contributions.admin.none', 'No change has been proposed to any line yet.') }}</p>
        <p v-else-if="rows.length && !shown.length" class="cti-note" data-testid="cti-none-here">{{ t('contributions.admin.noneHere', 'No change matches these filters.') }}</p>
        <ul v-else class="cti-rows">
          <li v-for="r in shown" :key="r.change.id" class="cti-card cti-row" :data-testid="`cti-row-${r.change.id}`" :data-lane="r.lane">
            <div class="cti-row-h">
              <RouterLink :to="{ name: 'code-change', params: { id: r.change.id } }" class="cti-row-t">{{ r.change.title }}</RouterLink>
              <span class="cti-tag" :data-state="r.change.state">{{ r.lane === 'balloting' ? lineStateWord('balloting', String, tr) : laneWord(r.lane, tr) }}</span>
              <span v-if="r.change.sensitive" class="cti-tag warn">{{ t('codeChanges.sensitive', 'Sensitive path') }}</span>
              <span v-if="r.line.state === 'paused'" class="cti-tag warn" data-testid="cti-line-paused-tag" :title="String(r.line.paused_reason || '')">{{ t('contributions.admin.linePaused', 'Line paused') }}</span>
            </div>
            <p class="cti-small cti-muted"><code>{{ r.line.release_name }}</code> · <span :title="String(r.line.organization_id || '')">{{ orgName(r.line.organization_id) }}</span> · <time :datetime="String(r.change.created_at || '')">{{ day(r.change.created_at) }}</time></p>
            <p class="cti-small" :data-checker="checkerWords(r.change, tr).state" data-testid="cti-checker">{{ checkerWords(r.change, tr).text }}</p>
            <p class="cti-small">{{ reviewWords(r.change, tr) }}</p>
            <p v-if="ballotWords(r.change, tr)" class="cti-small" data-testid="cti-ballot">{{ ballotWords(r.change, tr) }}</p>
            <div v-if="maintainerOffer(r.change)" class="cti-actions" data-testid="cti-maintainer">
              <template v-if="vetoing === r.change.id">
                <label class="cti-field"><span>{{ t('contributions.owner.why', 'Why the veto (the proposer reads it)') }}</span>
                  <textarea v-model="vetoReason" rows="2" maxlength="1000" data-testid="cti-veto-reason"></textarea></label>
                <button type="button" class="cti-btn danger" :disabled="acting || !vetoReason.trim()" data-testid="cti-veto-confirm" @click="veto(r.change)">{{ t('contributions.owner.vetoConfirm', 'Veto the change') }}</button>
                <button type="button" class="cti-btn" :disabled="acting" @click="vetoing = ''">{{ t('contributions.form.cancel', 'Cancel') }}</button>
              </template>
              <template v-else>
                <button type="button" class="cti-btn" :disabled="acting" data-testid="cti-go" @click="go(r.change)">{{ t('contributions.admin.go', 'Go: end the veto window') }}</button>
                <button type="button" class="cti-btn danger" data-testid="cti-veto" @click="vetoing = r.change.id; vetoReason = ''">{{ t('contributions.owner.veto', 'Veto') }}</button>
              </template>
            </div>
            <p v-if="rowRefusal[r.change.id]" class="cti-refusal" role="alert" :data-testid="`cti-refusal-${r.change.id}`">{{ rowRefusal[r.change.id] }}</p>
          </li>
        </ul>
      </section>
      <section class="cti-card cti-upstream" data-testid="cti-upstream" :aria-label="t('contributions.upstream.title', 'Upstream proposals')">
        <h2>{{ tp('contributions.upstream.head', 'Upstream proposals ({n})', { n: upstream.length }) }}</h2>
        <p class="cti-small cti-muted">{{ t('contributions.upstream.intro', 'Changes merged in an organization\'s release line that its deciders proposed to the main code, and where each stands there.') }}</p>
        <p v-if="upstreamError" class="cti-error" role="alert" data-testid="cti-upstream-error">{{ t('contributions.upstream.error', 'The upstream proposals could not be read; try again.') }}
          <button type="button" class="cti-btn" @click="loadUpstream">{{ t('contributions.retry', 'Try again') }}</button></p>
        <p v-else-if="!upstream.length" class="cti-note" data-testid="cti-upstream-none">{{ t('contributions.upstream.none', 'No change of a release line has been proposed to the main code yet.') }}</p>
        <ul v-else class="cti-rows">
          <li v-for="u in upstream" :key="u.id" class="cti-row" :data-testid="`cti-up-${u.id}`" :data-fate="fateOf(u)">
            <div class="cti-row-h">
              <RouterLink :to="{ name: 'code-change', params: { id: u.id } }" class="cti-row-t">{{ u.title }}</RouterLink>
              <span class="cti-tag" :data-state="u.state">{{ stateWord(String(u.state), tr) }}</span>
            </div>
            <p class="cti-small cti-muted">{{ tp('contributions.upstream.from', 'From {line} ({org}), proposed {day}', { line: u.provenance?.line?.title ?? u.provenance?.line?.slug ?? '—', org: u.provenance?.line?.organization_name ?? '—', day: day(u.created_at) }) }}</p>
          </li>
        </ul>
      </section>
      <details v-if="lines.length" class="cti-card cti-lines" data-testid="cti-lines" :open="wide || pausedCount > 0">
        <summary class="cti-sum"><h2>{{ tp('contributions.admin.lines', 'Release lines ({n})', { n: lines.length }) }}</h2>
          <span v-if="pausedCount" class="cti-tag warn">{{ tp('contributions.admin.pausedCount', '{n} paused', { n: pausedCount }) }}</span></summary>
        <ul class="cti-line-list">
          <li v-for="l in lines" :key="l.slug" class="cti-line" :data-testid="`cti-line-${l.slug}`" :data-state="l.state">
            <div class="cti-line-t"><b>{{ l.title }}</b> <code>{{ l.release_name }}</code> <span class="cti-muted" :title="String(l.organization_id || '')">{{ orgName(l.organization_id) }}</span>
              <span v-if="l.state === 'paused'" class="cti-tag warn" data-testid="cti-paused">{{ t('contributions.line.paused', 'Paused') }}</span></div>
            <p v-if="l.state === 'paused'" class="cti-small cti-warn">{{ l.paused_reason }}</p>
            <template v-if="pausing === l.slug">
              <label class="cti-field"><span>{{ t('contributions.admin.reason', 'Why the line is paused (its members read it)') }}</span>
                <textarea v-model="pauseReason" rows="2" maxlength="500" data-testid="cti-pause-reason"></textarea></label>
              <p v-if="pauseTouched && pauseProblem(pauseReason, tr)" class="cti-refusal" role="alert" data-testid="cti-pause-problem">{{ pauseProblem(pauseReason, tr) }}</p>
              <div class="cti-actions">
                <button type="button" class="cti-btn danger" :disabled="acting" data-testid="cti-pause-confirm" @click="pause(l)">{{ t('contributions.admin.pauseConfirm', 'Pause the line') }}</button>
                <button type="button" class="cti-btn" :disabled="acting" @click="pausing = ''">{{ t('contributions.form.cancel', 'Cancel') }}</button>
              </div>
            </template>
            <div v-else class="cti-actions">
              <button v-if="l.state !== 'paused'" type="button" class="cti-btn" data-testid="cti-pause" @click="pausing = l.slug; pauseReason = ''; pauseTouched = false">{{ t('contributions.admin.pause', 'Pause') }}</button>
              <button v-else type="button" class="cti-btn" :disabled="acting" data-testid="cti-resume" @click="resume(l)">{{ t('contributions.admin.resume', 'Resume') }}</button>
            </div>
            <p v-if="lineRefusal[l.slug]" class="cti-refusal" role="alert">{{ lineRefusal[l.slug] }}</p>
          </li>
        </ul>
      </details>
      <AdminContentQueue data-testid="cti-content" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import AdminContentQueue from '@/components/codeChanges/AdminContentQueue.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { listUpstream, refusalWords, type ChangeRecord } from '@/services/api/codeChanges'
import { stateWord } from '@/services/codeChanges/codeChangeView'
import { adminListLines, adminPauseLine, adminResumeLine, listLineChanges, maintainerGo, maintainerVeto, type LineRecord } from '@/services/api/codeDistributions'
import { useTr } from '@/services/codeChanges/tr'
import { LANES, lineStateWord, ballotWords, checkerWords, filterInbox, inboxRows, laneWord, maintainerOffer, noFilter, pauseProblem, reviewWords } from '@/services/codeDistributions/lines'

const { t, tp } = useI18n()
const tr = useTr()
const { codeDistributionsEnabled, loaded, readFailed, reload, load: loadCfg } = useRegistryConfig() as any
const cfgOn = computed(() => codeDistributionsEnabled.value === true)
const cfgOff = computed(() => loaded.value && !readFailed.value && !cfgOn.value)

const lines = ref<LineRecord[]>([])
const bySlug = ref<Record<string, ChangeRecord[]>>({})
const loading = ref(false)
const loadError = ref('')
const partial = ref(0)
const f = reactive(noFilter())
const acting = ref(false)
const pausing = ref('')
const pauseReason = ref('')
const pauseTouched = ref(false)
const vetoing = ref('')
const vetoReason = ref('')
const lineRefusal = reactive<Record<string, string>>({})
const rowRefusal = reactive<Record<string, string>>({})

const rows = computed(() => inboxRows(lines.value, bySlug.value))
const shown = computed(() => filterInbox(rows.value, f))
const pausedCount = computed(() => lines.value.filter((l) => l.state === 'paused').length)
// the list of lines is open on a wide screen and folded on a phone (the queue is what arrives); a paused line opens it on any screen
const wide = typeof window === 'undefined' || typeof window.matchMedia !== 'function' ? true : window.matchMedia('(min-width: 900px)').matches
const orgIds = computed(() => [...new Set(lines.value.map((l) => String(l.organization_id)))].sort())
// the organization by the name the registry gives with each line (an admin is often no member and could not read it); never a bare id on
// screen: a name the registry could not read is said as such, the id only in the title
const orgNames = computed(() => Object.fromEntries(lines.value.map((l) => [String(l.organization_id), l.organization_name ? String(l.organization_name) : ''])))
const orgName = (id: unknown) => orgNames.value[String(id || '')] || t('contributions.admin.unnamedOrg', 'An organization whose name could not be read')
const day = (iso: unknown): string => { const d = new Date(String(iso || '')); return Number.isNaN(d.getTime()) ? String(iso || '') : d.toISOString().slice(0, 16).replace('T', ' ') }

// V0667 D4: the changes that carry a line's change upstream, and their fate on the main code (open, landed, or ended without landing)
const upstream = ref<ChangeRecord[]>([])
const upstreamError = ref(false)
const fateOf = (u: ChangeRecord) => (u.state === 'merged' ? 'landed' : ['withdrawn', 'failed', 'vetoed'].includes(String(u.state)) ? 'ended' : 'open')
async function loadUpstream() {
  upstreamError.value = false
  try { upstream.value = await listUpstream() } catch { upstreamError.value = true }
}

async function load() {
  void loadUpstream()
  loading.value = true; loadError.value = ''; partial.value = 0
  try {
    lines.value = await adminListLines()
    const next: Record<string, ChangeRecord[]> = {}
    let missed = 0
    await Promise.all(lines.value.map(async (l) => {
      try { next[l.slug] = await listLineChanges(String(l.slug)) } catch { missed += 1 }
    }))
    bySlug.value = next
    partial.value = missed
  } catch (e) {
    loadError.value = refusalWords(e, t('contributions.lines.error', 'The release lines could not be read; try again.'))
  } finally { loading.value = false }
}
function putLine(rec: LineRecord) { if (rec?.slug) lines.value = lines.value.map((l) => (l.slug === rec.slug ? { ...l, ...rec } : l)) }
function putChange(rec: ChangeRecord) {
  if (!rec?.id) return
  const slug = (rec.code_distribution as any)?.slug
  if (slug && bySlug.value[slug]) bySlug.value = { ...bySlug.value, [slug]: bySlug.value[slug].map((c) => (c.id === rec.id ? rec : c)) }
}
async function pause(l: LineRecord) {
  pauseTouched.value = true
  if (pauseProblem(pauseReason.value, tr)) return
  acting.value = true; delete lineRefusal[l.slug]
  try { putLine(await adminPauseLine(String(l.slug), pauseReason.value.trim())); pausing.value = '' } catch (e) { lineRefusal[l.slug] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
async function resume(l: LineRecord) {
  acting.value = true; delete lineRefusal[l.slug]
  try { putLine(await adminResumeLine(String(l.slug))) } catch (e) { lineRefusal[l.slug] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
async function rowStep(c: ChangeRecord, step: () => Promise<ChangeRecord>) {
  acting.value = true; delete rowRefusal[String(c.id)]
  try { putChange(await step()); vetoing.value = '' } catch (e) { rowRefusal[String(c.id)] = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.')) } finally { acting.value = false }
}
const go = (c: ChangeRecord) => rowStep(c, () => maintainerGo(String(c.id)))
const veto = (c: ChangeRecord) => rowStep(c, () => maintainerVeto(String(c.id), vetoReason.value.trim()))

let started = false
const start = () => { if (!started && cfgOn.value) { started = true; void load() } }
watch(cfgOn, start)
onMounted(async () => { await loadCfg?.(); start() })
</script>

<style scoped>
.cti { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 80rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.cti > * { min-width: 0; }
.cti-hero { display: grid; gap: .6rem; justify-items: start; }
.cti-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.cti-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; }
.cti-lede { margin: 0; color: var(--muted); font-size: .9rem; max-width: 50rem; line-height: 1.6; }
.cti h2 { margin: 0; font-size: 1.02rem; font-weight: 500; }
.cti-note { margin: 0; color: var(--muted); font-size: .88rem; }
.cti-off { border: 1px dashed rgba(var(--cyan-rgb), .3); border-radius: 12px; padding: 1rem 1.2rem; color: var(--bright); }
.cti-error { border: 1px solid rgba(248, 113, 113, .35); border-radius: 12px; padding: .9rem 1.1rem; display: flex; flex-wrap: wrap; gap: .8rem; align-items: center; color: #fca5a5; }
.cti-error p { margin: 0; }
.cti-card { background: rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1rem 1.15rem; min-width: 0; }
.cti-lines { display: grid; gap: .7rem; }
.cti-lines:not([open]) { gap: 0; }
.cti-sum { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; cursor: pointer; list-style: none; min-height: 32px; }
.cti-sum::-webkit-details-marker { display: none; }
.cti-sum::after { content: '+'; margin-left: auto; font: 600 1rem var(--mono); color: var(--cyan); }
.cti-lines[open] > .cti-sum::after { content: '−'; }
.cti-sum:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 4px; border-radius: 6px; }
.cti-line-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
.cti-line { display: grid; gap: .4rem; border-top: 1px solid rgba(255,255,255,.06); padding-top: .6rem; }
.cti-line:first-child { border-top: 0; padding-top: 0; }
.cti-line-t { display: flex; flex-wrap: wrap; gap: .5rem; align-items: baseline; overflow-wrap: anywhere; }
.cti-line-t .cti-muted { font: .74rem var(--mono); }
.cti code { font: .72rem var(--mono); color: var(--cyan); overflow-wrap: anywhere; }
.cti-muted { color: var(--muted); }
.cti-warn { color: #fcd34d; }
.cti-tag { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 8px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); white-space: nowrap; }
.cti-tag.warn { color: #fcd34d; border-color: rgba(245, 158, 11, .4); }
.cti-tag[data-state='merged'], .cti-tag[data-state='passed'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.cti-tag[data-state='failed'], .cti-tag[data-state='vetoed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.cti-actions { display: flex; flex-wrap: wrap; gap: .5rem; align-items: flex-end; }
.cti-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .82rem; cursor: pointer; }
.cti-btn.danger { color: #fca5a5; border-color: rgba(248, 113, 113, .45); background: rgba(248, 113, 113, .08); }
.cti-btn:disabled { opacity: .5; cursor: not-allowed; }
.cti-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.cti-queue { display: grid; gap: .8rem; }
.cti-bar { display: flex; flex-wrap: wrap; gap: .8rem; align-items: flex-end; justify-content: space-between; }
.cti-filters { display: flex; flex-wrap: wrap; gap: .6rem; }
.cti-filters label, .cti-field { display: grid; gap: .25rem; font-size: .8rem; min-width: 0; }
.cti-filters span, .cti-field span { font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.cti-filters select, .cti-field textarea { min-height: 40px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0,0,0,.3); color: var(--bright); font: inherit; font-size: .84rem; padding: 0 .6rem; max-width: 100%; }
.cti-field textarea { padding: .5rem .6rem; width: 100%; box-sizing: border-box; }
.cti-field { flex: 1 1 18rem; }
.cti-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
.cti-row { display: grid; gap: .4rem; }
.cti-row[data-lane='ended'] { border-color: rgba(248, 113, 113, .25); }
.cti-row-h { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.cti-row-t { color: var(--bright); text-decoration: none; font-weight: 500; overflow-wrap: anywhere; }
.cti-row-t:hover, .cti-row-t:focus-visible { color: var(--cyan); }
.cti-small { margin: 0; font-size: .78rem; line-height: 1.5; color: #aab4c0; overflow-wrap: anywhere; }
.cti-small[data-checker='failed'] { color: #fca5a5; }
.cti-small[data-checker='ok'] { color: #86efac; }
.cti-refusal { margin: 0; font-size: .8rem; color: #fca5a5; overflow-wrap: anywhere; }
@media (max-width: 640px) { .cti { padding: 1rem .8rem 2.5rem; } .cti-hero h1 { font-size: 1.45rem; } .cti-filters { display: grid; grid-template-columns: 1fr 1fr; width: 100%; } .cti-filters select { width: 100%; } }
</style>
