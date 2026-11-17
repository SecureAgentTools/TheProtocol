<!--
  V0664 C4 — one migration report, read as a page. Counts, names and hashes only (a report never holds a record's value). The verdict is
  said in words and by a glyph, never by colour alone; the hash is the one this browser recomputed (reportCheck.hashHolds).
-->
<template>
  <article class="rc" :data-testid="`rp-card-${doc.step}`" :data-verdict="doc.verdict || 'not_measured'">
    <header class="rc-head">
      <div class="rc-title">
        <span class="rc-eyebrow">{{ t('migrate.rep.step', 'Step') }}</span>
        <h2>{{ stepWord }}<span v-if="doc.sample" class="rc-sample" data-testid="rp-sample">{{ t('migrate.rep.sample', 'on sample data') }}</span></h2>
      </div>
      <span class="rc-chip" :class="`tone-${verdict.tone}`" data-testid="rp-verdict">
        <Icon :name="verdict.tone === 'ok' ? 'mdi:check-circle' : verdict.tone === 'bad' ? 'mdi:close-circle' : 'mdi:help-circle-outline'" />
        {{ verdictLabel }}
      </span>
      <span class="rc-chip" :class="holds ? 'tone-ok' : 'tone-bad'" :data-state="holds ? 'ok' : 'bad'" data-testid="rp-hash" :title="doc.report_sha256 || ''">
        <Icon :name="holds ? 'mdi:shield-check' : 'mdi:alert'" />
        {{ holds ? t('migrate.rep.hashHolds', 'Hash holds') : t('migrate.rep.hashFails', 'Hash does not hold') }}
        <code>{{ short(doc.report_sha256) }}</code>
      </span>
      <button type="button" class="rc-x" :data-testid="`rp-remove-${doc.step}`" :aria-label="tp('migrate.rep.remove', 'Remove {name}', { name })" @click="$emit('remove')"><Icon name="mdi:close" /></button>
    </header>
    <p class="rc-meta">
      <span>{{ name }}</span>
      <span v-if="doc.started_at">{{ t('migrate.rep.started', 'started') }} {{ when(doc.started_at) }}</span>
      <span v-if="doc.finished_at">{{ t('migrate.rep.finished', 'finished') }} {{ when(doc.finished_at) }}</span>
      <span v-if="doc.template">{{ doc.template.name }} {{ t('migrate.rep.version', 'version') }} {{ doc.template.version }} <code>{{ short(doc.template.content_hash) }}</code></span>
    </p>
    <p v-if="!holds" class="rc-warn" role="alert">{{ t('migrate.rep.hashFailsWhy', 'This report was changed after it was sealed: its recorded hash is not the hash of what it holds now. Do not rely on its numbers.') }}</p>

    <section v-if="sources.length" class="rc-sec" data-testid="rp-sources">
      <h3>{{ t('migrate.rep.sources', 'Sources') }}</h3>
      <table class="rc-table">
        <thead><tr><th>{{ t('migrate.rep.source', 'Source') }}</th><th class="num">{{ t('migrate.rep.rows', 'Rows') }}</th><th>{{ t('migrate.rep.fields', 'Fields') }}</th></tr></thead>
        <tbody>
          <tr v-for="s in sources" :key="s.name">
            <td>{{ s.name }}</td>
            <td class="num">{{ s.rows === null || s.rows === undefined ? t('migrate.rep.notMeasured', 'not measured') : nf(s.rows) }}</td>
            <td class="rc-dim">{{ (s.fields || []).join(', ') }}<span v-if="s.why"> ({{ s.why }})</span></td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-for="m in mappings" :key="m.name" class="rc-sec" :data-testid="`rp-mapping-${m.name}`">
      <h3>{{ t('migrate.rep.mapping', 'Mapping') }} <span class="rc-name">{{ m.name }}</span></h3>
      <div class="rc-tiles">
        <div class="rc-tile"><span class="lbl">{{ t('migrate.rep.taken', 'Taken') }}</span><span class="val">{{ nf(m.taken ?? 0) }}</span></div>
        <div class="rc-tile"><span class="lbl">{{ t('migrate.rep.mapped', 'Mapped') }}</span><span class="val">{{ nf(m.mapped ?? 0) }}</span></div>
        <div class="rc-tile" :class="{ warn: (m.rejected || 0) > 0 }"><span class="lbl">{{ t('migrate.rep.rejected', 'Rejected') }}</span><span class="val">{{ nf(m.rejected ?? 0) }}</span></div>
      </div>
      <div v-if="m.reasons.length" class="rc-block" data-testid="rp-reasons">
        <h4>{{ t('migrate.rep.byReason', 'Rejected, by reason') }}</h4>
        <ul class="rc-bars">
          <li v-for="r in m.reasons" :key="r.reason">
            <span class="rc-bar-label"><b>{{ r.n }}</b> × {{ r.reason }}</span>
            <span class="rc-bar" aria-hidden="true"><i :style="{ width: r.pct + '%' }" /></span>
            <span class="rc-bar-pct">{{ r.pct }}%</span>
          </li>
        </ul>
      </div>
      <div v-if="m.fill.length" class="rc-block" data-testid="rp-fill">
        <h4>{{ t('migrate.rep.fill', 'Fill per target field') }}</h4>
        <table class="rc-table">
          <thead><tr><th>{{ t('migrate.rep.field', 'Field') }}</th><th class="num">{{ t('migrate.rep.filled', 'Filled') }}</th><th class="num">{{ t('migrate.rep.null', 'Null') }}</th><th class="bar">{{ t('migrate.rep.share', 'Filled share') }}</th></tr></thead>
          <tbody>
            <tr v-for="f in m.fill" :key="f.field">
              <td>{{ f.field }}</td><td class="num">{{ nf(f.filled) }}</td><td class="num">{{ nf(f.null) }}</td>
              <td class="bar"><span class="rc-bar" aria-hidden="true"><i :style="{ width: f.pct + '%' }" /></span><span class="rc-bar-pct">{{ f.pct }}%</span></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="m.no_source?.length" class="rc-note">{{ t('migrate.rep.noSource', 'Target fields no source fills') }}: {{ m.no_source.join(', ') }}</p>
      <p v-if="m.unused?.length" class="rc-note">{{ t('migrate.rep.unused', 'Source fields no mapping reads') }}: {{ m.unused.join(', ') }}</p>
    </section>

    <section v-if="targets.length" class="rc-sec" data-testid="rp-targets">
      <h3>{{ t('migrate.rep.targets', 'Targets') }}</h3>
      <table class="rc-table">
        <thead><tr><th>{{ t('migrate.rep.target', 'Target') }}</th><th class="num">{{ t('migrate.rep.written', 'Written') }}</th><th class="num">{{ t('migrate.rep.unchanged', 'Unchanged') }}</th><th class="num">{{ t('migrate.rep.failed', 'Failed') }}</th><th class="num">{{ t('migrate.rep.waiting', 'Waiting') }}</th></tr></thead>
        <tbody>
          <tr v-for="x in targets" :key="x.name">
            <td>{{ x.name }}<span v-if="x.scratch" class="rc-sample">{{ t('migrate.rep.scratch', 'scratch') }}</span></td>
            <td class="num">{{ nf(x.written ?? 0) }}</td><td class="num">{{ nf(x.unchanged ?? 0) }}</td>
            <td class="num" :class="{ bad: (x.failed || 0) > 0 }">{{ nf(x.failed ?? 0) }}</td><td class="num" :class="{ bad: (x.pending || 0) > 0 }">{{ nf(x.pending ?? 0) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="recs.length" class="rc-sec" data-testid="rp-reconcile">
      <h3>{{ t('migrate.rep.reconcile', 'Reconcile') }}</h3>
      <table class="rc-table">
        <thead><tr><th>{{ t('migrate.rep.mapping', 'Mapping') }}</th><th>{{ t('migrate.rep.verdict', 'Verdict') }}</th><th class="num">{{ t('migrate.rep.source', 'Source') }}</th><th class="num">{{ t('migrate.rep.target', 'Target') }}</th><th class="num">{{ t('migrate.rep.missing', 'Missing') }}</th><th class="num">{{ t('migrate.rep.extra', 'Extra') }}</th><th class="num">{{ t('migrate.rep.mismatched', 'Mismatched') }}</th></tr></thead>
        <tbody>
          <template v-for="r in recs" :key="r.name">
            <tr>
              <td>{{ r.name }}</td>
              <td><span class="rc-chip small" :class="`tone-${r.words.tone}`">{{ r.words.label }}</span></td>
              <td class="num">{{ n(r.source) }}</td><td class="num">{{ n(r.target) }}</td><td class="num">{{ n(r.missing) }}</td><td class="num">{{ n(r.extra) }}</td><td class="num">{{ n(r.mismatched) }}</td>
            </tr>
            <tr v-if="r.why"><td colspan="7" class="rc-dim rc-why">{{ r.why }}</td></tr>
          </template>
        </tbody>
      </table>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { formatNumber } from '@/i18n'
/** a count in the reader's own grouping (never the OS's: services/cockpit/num.ts has the why) */
const nf = (v: unknown): string => (typeof v === 'number' && Number.isFinite(v) ? formatNumber(v) : String(v ?? ''))
import { STEP_WORDS, fillRows, reasonRows, verdictWords } from '@/services/migrate/reportView'

const props = defineProps<{ doc: any; holds: boolean; name: string }>()
defineEmits<{ (e: 'remove'): void }>()
const { t, tp } = useI18n()

const verdict = computed(() => verdictWords(props.doc.verdict))
const verdictLabel = computed(() => ({ ok: t('migrate.rep.passed', 'Passed'), bad: t('migrate.rep.failedV', 'Failed') } as Record<string, string>)[verdict.value.tone === 'warn' ? '' : verdict.value.tone] || (props.doc.verdict && props.doc.verdict !== 'not_measured' ? String(props.doc.verdict) : t('migrate.rep.notMeasuredV', 'Not measured')))
const stepWord = computed(() => STEP_WORDS[props.doc.step] || String(props.doc.step))
const entries = (o: any) => (o && typeof o === 'object' ? Object.entries(o) : [])
const sources = computed(() => entries(props.doc.sources).map(([name, s]: [string, any]) => ({ name, ...(s || {}) })))
const mappings = computed(() => entries(props.doc.mappings).map(([name, m]: [string, any]) => ({ name, ...(m || {}), reasons: reasonRows(m), fill: fillRows(m) })))
const targets = computed(() => entries(props.doc.targets).map(([name, x]: [string, any]) => ({ name, ...(x || {}) })))
const recs = computed(() => entries(props.doc.reconcile).map(([name, r]: [string, any]) => ({ name, ...(r || {}), words: verdictWords(r?.verdict) })))
const short = (h: unknown) => (typeof h === 'string' ? h.slice(0, 12) : '')
const when = (iso: unknown) => String(iso || '').replace('T', ' ').replace(/\.\d+Z$/, ' UTC').replace(/Z$/, ' UTC')
const n = (v: unknown) => (v === null || v === undefined ? '–' : String(v))
</script>

<style scoped>
.rc { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .18);
  border-radius: 12px; padding: 1.1rem 1.25rem 1.2rem; display: grid; gap: .9rem; box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 12px 32px -22px rgba(0,0,0,.8); }
.rc-head { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem .8rem; }
.rc-title { display: grid; gap: .2rem; margin-right: auto; }
.rc-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.rc-head h2 { margin: 0; font-size: 1.25rem; font-weight: 300; color: var(--bright); display: flex; align-items: baseline; gap: .6rem; flex-wrap: wrap; }
.rc-sample { font: 600 10px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); border: 1px solid rgba(var(--cyan-rgb), .22); border-radius: 999px; padding: 3px 8px; margin-left: .5rem; }
.rc-chip { display: inline-flex; align-items: center; gap: .4rem; border: 1px solid; border-radius: 999px; padding: 4px 11px; font-size: .78rem; font-weight: 500; }
.rc-chip.small { padding: 2px 8px; font-size: .72rem; }
.rc-chip :deep(svg) { width: .95rem; height: .95rem; }
.rc-chip code { font: 500 .7rem var(--mono); opacity: .8; }
.tone-ok { color: #10b981; border-color: rgba(16,185,129,.4); background: rgba(16,185,129,.07); }
.tone-bad { color: #ef4444; border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.07); }
.tone-warn { color: #f59e0b; border-color: rgba(245,158,11,.4); background: rgba(245,158,11,.06); }
.rc-x { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: none; color: var(--muted); cursor: pointer; }
.rc-x:hover, .rc-x:focus-visible { color: var(--bright); border-color: rgba(var(--cyan-rgb), .5); }
.rc-x :deep(svg) { width: 1rem; height: 1rem; }
.rc-meta { margin: 0; display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; font-size: .74rem; color: var(--muted); }
.rc-meta code, .rc-head code { font-family: var(--mono); }
.rc-warn { margin: 0; padding: .6rem .8rem; border-radius: 8px; border: 1px solid rgba(239,68,68,.45); background: rgba(239,68,68,.06); color: #fca5a5; font-size: .82rem; }
.rc-sec { display: grid; gap: .6rem; border-top: 1px solid rgba(var(--cyan-rgb), .12); padding-top: .85rem; }
.rc-sec h3 { margin: 0; font: 700 11px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.rc-name { color: var(--cyan); text-transform: none; letter-spacing: 0; font-size: .82rem; }
.rc-block h4 { margin: .3rem 0 .45rem; font-size: .8rem; font-weight: 500; color: var(--bright); }
.rc-tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.rc-tile { background: rgba(var(--cyan-rgb), .03); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 8px; padding: 12px 14px; display: grid; gap: 6px; }
.rc-tile.warn { border-color: rgba(245,158,11,.45); background: rgba(245,158,11,.04); }
.rc-tile .lbl { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.rc-tile .val { font-size: 1.5rem; font-weight: 300; color: var(--bright); font-variant-numeric: tabular-nums; }
.rc-table { width: 100%; border-collapse: collapse; font-size: .8rem; }
.rc-table th { text-align: left; font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: 6px 10px 6px 0; border-bottom: 1px solid rgba(var(--cyan-rgb), .14); }
.rc-table td { padding: 7px 10px 7px 0; border-bottom: 1px solid rgba(255,255,255,.05); color: var(--bright); vertical-align: top; }
.rc-table .num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); }
.rc-table td.bad { color: #ef4444; }
.rc-table .bar { min-width: 9rem; }
.rc-dim { color: var(--muted) !important; }
.rc-why { font-size: .74rem; }
.rc-bars { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }
.rc-bars li { display: grid; grid-template-columns: minmax(0, 1fr) 7rem 3rem; gap: 10px; align-items: center; font-size: .8rem; }
.rc-bar-label { overflow-wrap: anywhere; color: var(--bright); }
.rc-bar { display: block; height: 6px; border-radius: 3px; background: rgba(255,255,255,.07); overflow: hidden; }
.rc-bar i { display: block; height: 100%; background: var(--cyan); border-radius: 3px; }
.rc-bar-pct { font: 500 .72rem var(--mono); color: var(--muted); text-align: right; margin-left: .5rem; }
.rc-table td.bar { display: flex; align-items: center; gap: .5rem; border-bottom: none; }
.rc-table td.bar .rc-bar { flex: 1; }
.rc-note { margin: 0; font-size: .78rem; color: var(--muted); }
@media (max-width: 640px) {
  .rc { padding: .9rem .9rem 1rem; }
  .rc-tiles { grid-template-columns: 1fr; }
  .rc-bars li { grid-template-columns: minmax(0, 1fr) 3rem; }
  .rc-bars li .rc-bar { display: none; }
  .rc-table { display: block; overflow-x: auto; }
}
</style>
