<!--
  V0664 C4 (order gwo_85a6015257385f6bb010682e) — #/migrate/new, the migration builder. Public, and the sample never leaves the browser: this page makes no request except the two a signed-in
  agent asks for (save a private draft, publish). The model is services/migrate/builder.ts; the checks are the registry's own publish gate (kitCheck) and the mapping is run by the
  TypeScript port of the SDK's value nodes (mapping.ts), both pinned against the Python.
-->
<template>
  <div class="mb" data-testid="mb-root" :style="{ '--mb-top': topOffset + 'px' }">
    <MigrateTabs current="migrate-new" />
    <header class="mb-hero">
      <span class="mb-eyebrow">{{ t('migrate.build.eyebrow', 'Migrate a system · builder') }}</span>
      <h1>{{ t('migrate.build.title', 'Build a migration') }}</h1>
      <p class="mb-lead">{{ t('migrate.build.lead', 'Pick where the data is and where it goes, map the fields, and watch the mapping run on a sample. The kit\'s two files are written as you go and checked by the same rules the library applies when you publish.') }}</p>
      <p class="mb-privacy" data-testid="mb-privacy"><Icon name="mdi:lock" /> {{ t('migrate.build.privacy', 'A sample you paste or choose never leaves your browser, and it is not kept when you leave this page. Nothing is sent anywhere unless you save a draft.') }}</p>
    </header>

    <div class="mb-bar" role="status" data-testid="mb-bar">
      <span class="mb-bar-s" :class="{ ok: kit.check.ok && !pv.fieldProblems.length }">{{ barWords }}</span>
      <a href="#mb-out" class="mb-bar-a" data-testid="mb-bar-go" @click.prevent="goOut">{{ t('migrate.build.barGo', 'Files and checks') }}</a>
    </div>

    <div class="mb-grid">
      <div class="mb-col">
        <section class="mb-card">
          <h2><span class="mb-n">1</span>{{ t('migrate.build.s1', 'What is moving') }}</h2>
          <div class="mb-row2">
            <label class="mb-f"><span>{{ t('migrate.build.name', 'Name') }}</span><input v-model="s.name" data-testid="mb-name" class="mb-in mono" spellcheck="false" autocapitalize="off" placeholder="orders-to-pg" /><small>{{ t('migrate.build.nameHint', 'lowercase letters, digits and dashes') }}</small></label>
            <label class="mb-f"><span>{{ t('migrate.build.titleLbl', 'Title') }}</span><input v-model="s.title" data-testid="mb-title" class="mb-in" placeholder="Orders to PostgreSQL" /></label>
          </div>
          <label class="mb-f"><span>{{ t('migrate.build.summary', 'Summary') }}</span><textarea v-model="s.summary" class="mb-in" rows="2" data-testid="mb-summary" /></label>
          <div class="mb-row2">
            <label class="mb-f"><span>{{ t('migrate.build.from', 'From') }}</span>
              <select v-model="s.from.kind" data-testid="mb-from" class="mb-in" @change="onKinds"><option v-for="k in KINDS" :key="k" :value="k">{{ kindWords(k) }}</option></select></label>
            <label class="mb-f"><span>{{ t('migrate.build.to', 'To') }}</span>
              <select v-model="s.to.kind" data-testid="mb-to" class="mb-in" @change="onKinds"><option v-for="k in KINDS" :key="k" :value="k">{{ kindWords(k) }}</option></select></label>
          </div>
          <div class="mb-row2">
            <label class="mb-f"><span>{{ t('migrate.build.fromWhat', 'What it reads') }}</span><input v-model="s.from.what" class="mb-in" :placeholder="t('migrate.build.fromWhatPh', 'a customers table')" /></label>
            <label class="mb-f"><span>{{ t('migrate.build.toWhat', 'What it writes') }}</span><input v-model="s.to.what" class="mb-in" :placeholder="t('migrate.build.toWhatPh', 'public.customers')" /></label>
          </div>
        </section>

        <section class="mb-card">
          <h2><span class="mb-n">2</span>{{ t('migrate.build.s2', 'Where it reads from') }}</h2>
          <label class="mb-f"><span>{{ t('migrate.build.sourceType', 'Source') }}</span>
            <select v-model="s.source.type" data-testid="mb-source-type" class="mb-in" @change="onSourceType"><option v-for="n in SOURCES_FOR[s.from.kind]" :key="n" :value="n">{{ n }}</option></select></label>
          <p v-if="srcPlugin?.description" class="mb-note">{{ srcPlugin.description }}</p>
          <PluginConfigForm v-if="srcPlugin" :key="'src-' + s.source.type" role="source" :schema="srcPlugin.config_schema" :config="s.source.config" prefix="SOURCE" />
        </section>

        <section class="mb-card">
          <h2><span class="mb-n">3</span>{{ t('migrate.build.s3', 'Where it writes') }}</h2>
          <label class="mb-f"><span>{{ t('migrate.build.sinkType', 'Writer') }}</span>
            <select v-model="s.sink.type" data-testid="mb-sink-type" class="mb-in" @change="onSinkType"><option v-for="n in WRITERS_FOR[s.to.kind]" :key="n" :value="n">{{ n }}</option></select></label>
          <p v-if="snkPlugin?.description" class="mb-note">{{ snkPlugin.description }}</p>
          <PluginConfigForm v-if="snkPlugin" :key="'snk-' + s.sink.type" role="sink" :schema="snkPlugin.config_schema" :config="s.sink.config" prefix="TARGET" />
        </section>

        <section class="mb-card">
          <h2><span class="mb-n">4</span>{{ t('migrate.build.s4', 'A sample, and the mapping') }}</h2>
          <div class="mb-row2">
            <label class="mb-f"><span>{{ t('migrate.build.sampleFormat', 'Sample format') }}</span>
              <select v-model="s.sample.format" data-testid="mb-sample-format" class="mb-in" @change="formatChosen = true"><option value="jsonl">JSON lines (a table)</option><option value="csv">CSV (a file)</option><option value="json">JSON array</option></select></label>
            <label class="mb-f"><span>{{ t('migrate.build.sampleFile', 'or choose a file') }}</span><input type="file" class="mb-in" accept=".csv,.json,.jsonl,.txt,text/*,application/json" data-testid="mb-sample-file" @change="onSampleFile" /></label>
          </div>
          <label class="mb-f"><span>{{ t('migrate.build.sample', 'Paste a few rows') }}</span>
            <textarea v-model="s.sample.text" data-testid="mb-sample" class="mb-in mono" rows="5" spellcheck="false" :placeholder="t('migrate.build.samplePh', 'id,name,email  (a header line, then one row per line)')" /></label>
          <p v-if="pv.sampleError" class="mb-err" role="alert" data-testid="mb-sample-error">{{ pv.sampleError }}</p>
          <p v-else-if="columns.length" class="mb-note">{{ tp('migrate.build.columns', 'Columns read: {cols}', { cols: columns.join(', ') }) }}
            <button type="button" class="mb-link" data-testid="mb-from-columns" @click="fillFromColumns">{{ t('migrate.build.fillColumns', 'Map every column') }}</button></p>

          <h3 class="mb-h3">{{ t('migrate.build.fields', 'Fields') }}</h3>
          <p class="mb-note">{{ tp('migrate.build.fieldsNote', 'A field reads a path in the record ({base}…), or holds a constant, or joins several. Choose “More” for a transform: a type, a format, a zone, a rounding, a map.', { base: base }) }}</p>
          <div v-for="r in s.mapping.fields" :key="r.id" class="mb-fr" data-testid="mb-field-row">
            <div class="mb-fr-main">
              <input v-model="r.target" data-testid="mb-field-target" class="mb-in mono" :placeholder="t('migrate.build.target', 'target field')" :aria-label="t('migrate.build.target', 'target field')" spellcheck="false" />
              <input v-if="r.mode === 'path'" v-model="r.path" data-testid="mb-field-path" class="mb-in mono" :placeholder="base + 'name'" list="mb-paths" :aria-label="t('migrate.build.path', 'source path')" spellcheck="false" />
              <input v-else-if="r.mode === 'constant'" v-model="r.constant" class="mb-in" :placeholder="t('migrate.build.constant', 'a constant')" :aria-label="t('migrate.build.constant', 'a constant')" />
              <input v-else v-model="r.concat" class="mb-in mono" :placeholder="'$.payload.first, $.payload.last'" :aria-label="t('migrate.build.concat', 'paths to join')" spellcheck="false" />
              <button type="button" class="mb-btn small" data-testid="mb-field-more" :aria-expanded="open.has(r.id) ? 'true' : 'false'" @click="toggle(r.id)">{{ t('migrate.build.more', 'More') }}</button>
              <button type="button" class="mb-x" data-testid="mb-field-remove" :aria-label="tp('migrate.build.removeField', 'Remove {f}', { f: r.target || t('migrate.build.thisField', 'this field') })" @click="remove(r.id)"><Icon name="mdi:close" /></button>
            </div>
            <div v-if="open.has(r.id)" class="mb-fr-more">
              <label class="mb-f"><span>{{ t('migrate.build.mode', 'Takes') }}</span>
                <select v-model="r.mode" class="mb-in"><option value="path">a path</option><option value="constant">a constant</option><option value="concat">several paths joined</option></select></label>
              <label v-if="r.mode === 'concat'" class="mb-f"><span>{{ t('migrate.build.sep', 'Separator') }}</span><input v-model="r.sep" class="mb-in" /></label>
              <label class="mb-f"><span>{{ t('migrate.build.as', 'Type') }}</span>
                <select v-model="r.as" data-testid="mb-field-as" class="mb-in"><option value="">as it is</option><option v-for="a in AS_TYPES" :key="a" :value="a">{{ a }}</option></select></label>
              <label v-if="r.as === 'date' || r.as === 'datetime'" class="mb-f"><span>{{ t('migrate.build.format', 'Format') }}</span><input v-model="r.format" class="mb-in mono" placeholder="%d.%m.%Y %H:%M" spellcheck="false" /></label>
              <label v-if="r.as === 'datetime'" class="mb-f"><span>{{ t('migrate.build.tz', 'Zone') }}</span><input v-model="r.tz" class="mb-in mono" placeholder="Europe/Berlin or ${SOURCE_TZ}" spellcheck="false" /></label>
              <label class="mb-f"><span>{{ t('migrate.build.round', 'Round to') }}</span><input v-model="r.round" data-testid="mb-field-round" class="mb-in" inputmode="numeric" placeholder="2" /></label>
              <label class="mb-f"><span>{{ t('migrate.build.case', 'Case') }}</span>
                <select v-model="r.case" class="mb-in"><option value="">as it is</option><option v-for="c in CASES" :key="c" :value="c">{{ c }}</option></select></label>
              <label class="mb-f"><span>{{ t('migrate.build.nullIf', 'Null when it is') }}</span><input v-model="r.nullIf" class="mb-in" placeholder="N/A, -" /></label>
              <label class="mb-f"><span>{{ t('migrate.build.default', 'Default when missing') }}</span><input v-model="r.def" class="mb-in" /></label>
              <label class="mb-check"><input v-model="r.trim" type="checkbox" /> {{ t('migrate.build.trim', 'Trim spaces') }}</label>
              <label class="mb-check"><input v-model="r.optional" type="checkbox" /> {{ t('migrate.build.optional', 'May be missing (null)') }}</label>
              <label class="mb-f wide"><span>{{ t('migrate.build.map', 'Map values (one “from = to” per line)') }}</span>
                <textarea :value="mapText(r)" class="mb-in mono" rows="2" spellcheck="false" @input="setMap(r, ($event.target as HTMLTextAreaElement).value)" /></label>
              <label v-if="r.map.length" class="mb-f"><span>{{ t('migrate.build.mapDefault', 'Otherwise') }}</span><input v-model="r.mapDefault" class="mb-in" /></label>
              <label class="mb-f wide"><span>{{ t('migrate.build.regex', 'Take the part that matches a pattern') }}</span>
                <input v-model="r.regex" data-testid="mb-field-regex" class="mb-in mono" placeholder="ID-(\d+)" spellcheck="false" /></label>
              <label v-if="r.regex" class="mb-f"><span>{{ t('migrate.build.group', 'Group') }}</span><input v-model="r.group" class="mb-in" placeholder="1" /></label>
              <p class="mb-note wide" data-testid="mb-field-regex-note">{{ t('migrate.build.regexNote', 'The preview uses the browser\'s regex and the run uses Python\'s: the same on ordinary patterns.') }}</p>
              <p v-for="w in regexWarn(r.regex)" :key="w" class="mb-warn wide" data-testid="mb-field-regex-warn">{{ w }}</p>
            </div>
          </div>
          <datalist id="mb-paths"><option v-for="c in columns" :key="c" :value="base + c" /></datalist>
          <button type="button" class="mb-btn" data-testid="mb-add-field" @click="add">{{ t('migrate.build.addField', 'Add a field') }}</button>
          <ul v-if="pv.fieldProblems.length" class="mb-problems" role="alert"><li v-for="p in pv.fieldProblems" :key="p">{{ p }}</li></ul>
        </section>

        <section class="mb-card">
          <h2><span class="mb-n">5</span>{{ t('migrate.build.s5', 'Parameters, reconcile, rollback') }}</h2>
          <h3 class="mb-h3">{{ t('migrate.build.parameters', 'Parameters') }}</h3>
          <p class="mb-note">{{ t('migrate.build.paramsNote', 'Every ${NAME} the kit uses is a parameter. A host, url or path may only have a local default (localhost, 127.0.0.1, ::1, or a relative path); a secret has none.') }}</p>
          <div v-for="(p, name) in params" :key="name" class="mb-param" :data-testid="`mb-param-${name}`">
            <div class="mb-param-head"><code>{{ name }}</code><span v-if="p.secret" class="mb-chip" data-testid="mb-param-secret">{{ t('migrate.build.secret', 'secret: given as a reference') }}</span></div>
            <div class="mb-row3">
              <input :value="spec(name).description" class="mb-in" :placeholder="t('migrate.build.paramDesc', 'what it is')" :aria-label="tp('migrate.build.paramDescFor', 'Description of {n}', { n: name })" @input="setSpec(name, 'description', ($event.target as HTMLInputElement).value)" />
              <input v-if="!p.secret" :value="spec(name).default" data-testid="mb-param-default" class="mb-in mono" :placeholder="t('migrate.build.paramDefault', 'default')" :aria-label="tp('migrate.build.paramDefaultFor', 'Default of {n}', { n: name })" spellcheck="false" @input="setSpec(name, 'default', ($event.target as HTMLInputElement).value)" />
              <input v-if="!p.secret" :value="spec(name).enum" class="mb-in mono" :placeholder="t('migrate.build.paramEnum', 'allowed: a, b')" :aria-label="tp('migrate.build.paramEnumFor', 'Allowed values of {n}', { n: name })" spellcheck="false" @input="setSpec(name, 'enum', ($event.target as HTMLInputElement).value)" />
            </div>
          </div>
          <p v-if="!Object.keys(params).length" class="mb-note">{{ t('migrate.build.noParams', 'No parameters yet: a source or a writer field that names a destination adds one.') }}</p>

          <h3 class="mb-h3">{{ t('migrate.build.reconcile', 'Reconcile') }}</h3>
          <label class="mb-f"><span>{{ t('migrate.build.key', 'Key column(s) of the target') }}</span><input v-model="s.key" data-testid="mb-key" class="mb-in mono" placeholder="id" spellcheck="false" /><small>{{ t('migrate.build.keyHint', 'Both sides are read back and compared by this key; every other mapped field is compared too.') }}</small></label>
          <div class="mb-row2">
            <label class="mb-f"><span>{{ t('migrate.build.rollback', 'Rollback') }}</span>
              <select v-model="s.rollback" class="mb-in" data-testid="mb-rollback"><option value="auto">auto: put every changed row back</option><option value="manual">manual</option></select></label>
            <label class="mb-f"><span>{{ t('migrate.build.batch', 'Rows per batch') }}</span><input v-model="s.batchRows" class="mb-in" inputmode="numeric" placeholder="1000" /></label>
          </div>
          <label class="mb-f"><span>{{ t('migrate.build.cutover', 'Cutover checklist (one step per line)') }}</span><textarea v-model="s.cutover" class="mb-in" rows="4" /></label>
        </section>
      </div>

      <Teleport to="body" :disabled="!sheetOpen">
      <aside id="mb-out" class="mb-col mb-out" :class="{ sheet: sheetOpen }" :aria-label="t('migrate.build.outAria', 'The kit')" @keydown.esc="sheetOpen = false">
        <button v-if="sheetOpen" type="button" class="mb-btn mb-sheet-close" data-testid="mb-sheet-close" @click="sheetOpen = false">{{ t('migrate.build.sheetClose', 'Close') }}</button>
        <section class="mb-card mb-sticky">
          <div class="mb-tabs" role="tablist">
            <button v-for="t_ in TABS" :key="t_.id" type="button" role="tab" class="mb-tab" :class="{ on: tab === t_.id }" :aria-selected="tab === t_.id ? 'true' : 'false'" :data-testid="`mb-tab-${t_.id}`" @click="tab = t_.id">{{ t_.label }}</button>
          </div>
          <pre class="mb-yaml" data-testid="mb-yaml" tabindex="0">{{ shown }}</pre>

          <h3 class="mb-h3">{{ t('migrate.build.problems', 'The library\'s checks') }}</h3>
          <div data-testid="mb-problems">
            <p v-if="kit.check.ok" class="mb-ok"><Icon name="mdi:check-circle" /> {{ t('migrate.build.nothing', 'Nothing to fix: the library would take this kit.') }}</p>
            <ul v-else class="mb-problems">
              <li v-for="(p, i) in kit.check.problems" :key="i"><span class="mb-rule">{{ p.rule }}</span> {{ p.sentence }}</li>
            </ul>
          </div>

          <h3 class="mb-h3">{{ t('migrate.build.preview', 'The mapping on your sample') }}</h3>
          <p v-if="!pv.taken" class="mb-note">{{ t('migrate.build.noSample', 'Paste a few rows above and the mapping runs on them here.') }}</p>
          <template v-else>
            <p class="mb-counts" data-testid="mb-preview-counts"><b>{{ pv.taken }}</b> {{ t('migrate.build.taken', 'taken') }} · <b>{{ pv.mapped }}</b> {{ t('migrate.build.mapped', 'mapped') }} · <b :class="{ bad: pv.rejected }">{{ pv.rejected }}</b> {{ t('migrate.build.rejected', 'rejected') }}</p>
            <ul v-if="pv.reasons.length" class="mb-reasons" data-testid="mb-preview-reasons"><li v-for="r in pv.reasons" :key="r.reason"><b>{{ r.n }}</b> × {{ r.reason }}</li></ul>
            <div class="mb-scroll" data-testid="mb-preview-rows">
              <table class="mb-table">
                <thead><tr><th>#</th><th v-for="c in outCols" :key="c">{{ c }}</th></tr></thead>
                <tbody><tr v-for="r in pv.rows.slice(0, 8)" :key="r.index" :class="{ refused: !r.ok }">
                  <td>{{ r.index + 1 }}</td>
                  <template v-if="r.ok"><td v-for="c in outCols" :key="c">{{ cell(r.out![c]) }}</td></template>
                  <td v-else :colspan="outCols.length" class="why">{{ r.refused }}</td>
                </tr></tbody>
              </table>
            </div>
          </template>

          <div class="mb-actions">
            <button type="button" class="mb-btn primary" data-testid="mb-download" :disabled="!kit.check.ok" @click="download">{{ t('migrate.build.download', 'Download the files') }}</button>
            <button type="button" class="mb-btn" data-testid="mb-copy" @click="copy">{{ copied ? t('migrate.build.copied', 'Copied') : t('migrate.build.copy', 'Copy this file') }}</button>
            <button type="button" class="mb-btn ghost" data-testid="mb-reset" @click="reset">{{ t('migrate.build.reset', 'Start over') }}</button>
          </div>
          <p v-if="!kit.check.ok" class="mb-note">{{ t('migrate.build.fixFirst', 'Fix what the checks list, and the files can be downloaded.') }}</p>

          <div class="mb-save">
            <template v-if="canSave">
              <button type="button" class="mb-btn" data-testid="mb-save" :disabled="!kit.check.ok || busy" @click="save">{{ t('migrate.build.save', 'Save as a private draft') }}</button>
              <p v-if="saved" class="mb-ok" data-testid="mb-saved"><Icon name="mdi:check-circle" /> {{ tp('migrate.build.savedAs', 'Saved as a private draft: {id}, version {v}.', { id: saved.template_id, v: saved.version }) }}
                <RouterLink :to="{ name: 'migrate-template', params: { id: saved.template_id } }">{{ t('migrate.build.openDraft', 'Open it') }}</RouterLink></p>
              <button v-if="saved && !published" type="button" class="mb-btn" data-testid="mb-publish" :disabled="busy" @click="publish">{{ t('migrate.build.publish', 'Publish this version') }}</button>
              <p v-if="published" class="mb-ok" data-testid="mb-published"><Icon name="mdi:check-circle" /> {{ t('migrate.build.published', 'Published: a version never changes once it is published.') }}</p>
              <p v-if="saveError" class="mb-err" role="alert" data-testid="mb-save-error">{{ saveError }}</p>
            </template>
            <p v-else class="mb-note" data-testid="mb-save-note">{{ t('migrate.build.signIn', 'Sign in and pick an agent (top right) to save a draft; publishing needs the library\'s bond. Building and downloading need neither.') }}</p>
          </div>
        </section>
      </aside>
      </Teleport>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import PluginConfigForm from '@/components/migrate/PluginConfigForm.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { AS_TYPES, CASES, regexWarnings } from '@/services/proxy/mapping'
import { KINDS, SOURCES_FOR, WRITERS_FOR, buildKit, sniffFormat, mappingFields, newField, parametersFor, parseSample, plugin, preview, skeleton, type BuilderState, type FieldRow, type Kind } from '@/services/migrate/builder'
import { kindWords } from '@/services/migrate/templates'
import { createTemplate, publishVersion } from '@/services/api/workflowTemplates'

const { t, tp } = useI18n()
const auth = useAuthStore()
const canSave = computed(() => !!(auth as any).token && !!(auth as any).agentToken && !!(auth as any).activeAgent)

// the structure is kept on this device so a reload does not lose it; the SAMPLE never is
const KEY = 'migrate-builder-draft'
function restore(): BuilderState {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw) { const d = JSON.parse(raw); if (d && d.v === 1 && d.state) return { ...d.state, sample: { text: '', format: d.state.sample?.format || 'jsonl', name: '' } } }
  } catch { /* none, or unreadable: start fresh */ }
  return skeleton('file', 'sql')
}
const s = reactive<BuilderState>(restore())
watch(() => JSON.stringify({ ...s, sample: { ...s.sample, text: '' } }), (j) => { try { localStorage.setItem(KEY, JSON.stringify({ v: 1, state: JSON.parse(j) })) } catch { /* private mode or full */ } })

// the format follows what is pasted until the person chooses one
const formatChosen = ref(false)
watch(() => s.sample.text, (x) => { if (!formatChosen.value && x.trim()) s.sample.format = sniffFormat(x) })

const srcPlugin = computed(() => plugin('source', s.source.type))
const snkPlugin = computed(() => plugin('sink', s.sink.type))
const kit = computed(() => buildKit(s))
const pv = computed(() => preview(s))
const params = computed(() => parametersFor(s))
const columns = computed(() => { const rows = parseSample(s.sample.text, s.sample.format).rows; return rows.length ? Object.keys(rows[0]) : [] })
const outCols = computed(() => Object.keys(mappingFields(s)))
const base = computed(() => (s.source.type === 'filedrop' || s.source.type === 'sftp' ? '$.payload.data.' : '$.payload.'))

const barWords = computed(() => {
  const n = kit.value.check.problems.length + pv.value.fieldProblems.length
  const checks = n === 0 ? t('migrate.build.barOk', 'Nothing to fix') : n === 1 ? t('migrate.build.barOne', '1 thing to fix') : tp('migrate.build.barMany', '{n} things to fix', { n })
  return pv.value.taken ? `${checks} · ${tp('migrate.build.barRows', '{m} of {n} rows mapped', { m: pv.value.mapped, n: pv.value.taken })}` : checks
})
// The app shell sets overflow-x: hidden on <html>, which makes <html> a scroll container of its own height: position: sticky then has nothing to stick to
// (the files-and-checks column scrolled away with the form). While this page is open the shell clips the overflow instead, which hides the same
// thing and leaves the viewport as the scroller.
// The app's beta banner is sticky at the top of the screen (z 9999, about 61 px while shown): a column stuck at `top: 1rem` slid under it (session-code
// found it on C3's builder, the same rule). The banner's bottom edge is read on mount, scroll and resize and published as --mb-top on the page root.
const topOffset = ref(0)
let raf = 0
const measureTop = () => {
  raf = 0
  const b = document.querySelector('.beta-banner') as HTMLElement | null
  topOffset.value = b ? Math.max(0, Math.round(b.getBoundingClientRect().bottom)) : 0
}
const queueTop = () => { if (!raf) raf = requestAnimationFrame(measureTop) }
onMounted(() => {
  document.documentElement.classList.add('mb-page'); document.body.classList.add('mb-page')
  measureTop()
  window.addEventListener('scroll', queueTop, { passive: true }); window.addEventListener('resize', queueTop)
})
onBeforeUnmount(() => {
  document.documentElement.classList.remove('mb-page'); document.body.classList.remove('mb-page')
  window.removeEventListener('scroll', queueTop); window.removeEventListener('resize', queueTop)
  if (raf) cancelAnimationFrame(raf)
})

// on a phone the files, the checks and the preview open as a sheet over the form; on a wide screen the column simply stays in view
const sheetOpen = ref(false)
function goOut() {
  if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 1000px)').matches) sheetOpen.value = true
  else document.getElementById('mb-out')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const TABS = [{ id: 'migration', label: 'migration.yaml' }, { id: 'proxy', label: 'proxy.yaml' }, { id: 'readme', label: 'README.md' }] as const
const tab = ref<'migration' | 'proxy' | 'readme'>('migration')
const shown = computed(() => (tab.value === 'migration' ? kit.value.yaml.manifest : tab.value === 'proxy' ? kit.value.yaml.proxy : kit.value.files['README.md']))
const fileName = computed(() => (tab.value === 'migration' ? 'migration.yaml' : tab.value === 'proxy' ? 'proxy.yaml' : 'README.md'))

const open = reactive(new Set<string>())
const toggle = (id: string) => { if (open.has(id)) open.delete(id); else open.add(id) }
const add = () => { const r = newField('', ''); s.mapping.fields.push(r); open.delete(r.id) }
const remove = (id: string) => { s.mapping.fields = s.mapping.fields.filter((r) => r.id !== id); open.delete(id) }
function fillFromColumns() {
  const have = new Set(s.mapping.fields.map((r) => r.target))
  for (const c of columns.value) if (!have.has(c)) s.mapping.fields.push(newField(c, base.value + c))
}
const regexWarn = (rx: string) => (rx ? regexWarnings(rx) : [])
const mapText = (r: FieldRow) => r.map.map((p) => `${p.from} = ${p.to}`).join('\n')
function setMap(r: FieldRow, text: string) {
  r.map = text.split('\n').map((l) => { const i = l.indexOf('='); return i < 0 ? { from: l.trim(), to: '' } : { from: l.slice(0, i).trim(), to: l.slice(i + 1).trim() } }).filter((p) => p.from !== '')
}
const cell = (v: unknown) => (v === null || v === undefined ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v))

function spec(name: string) { const p = s.parameters[name]; return p || { description: '', default: '', secret: false, enum: '' } }
function setSpec(name: string, key: 'description' | 'default' | 'enum', v: string) {
  const cur = s.parameters[name] || { description: '', default: '', secret: false, enum: '' }
  s.parameters = { ...s.parameters, [name]: { ...cur, [key]: v } }
}

function onKinds() {
  const keep = { name: s.name, title: s.title, summary: s.summary, fromWhat: s.from.what, toWhat: s.to.what, sample: s.sample, parameters: s.parameters }
  const fresh = skeleton(s.from.kind as Kind, s.to.kind as Kind)
  fresh.name = keep.name; fresh.title = keep.title; fresh.summary = keep.summary; fresh.from.what = keep.fromWhat; fresh.to.what = keep.toWhat; fresh.sample = keep.sample; fresh.parameters = keep.parameters
  fresh.from.kind = s.from.kind; fresh.to.kind = s.to.kind
  Object.assign(s, fresh)
}
function onSourceType() { s.source.config = {}; s.source.name = s.source.name || 'old' }
function onSinkType() { s.sink.config = {} }
async function onSampleFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  if (!f) return
  s.sample.name = f.name
  s.sample.format = /\.csv$/i.test(f.name) ? 'csv' : /\.jsonl$/i.test(f.name) ? 'jsonl' : /\.json$/i.test(f.name) ? 'json' : s.sample.format
  s.sample.text = typeof (f as any).text === 'function' ? await (f as any).text() : await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.readAsText(f) })
}
function reset() {
  Object.assign(s, skeleton('file', 'sql'))
  open.clear(); saved.value = null; published.value = false; saveError.value = ''
}

function saveBlob(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const a = document.createElement('a')
  a.href = url; a.download = name.replace(/\//g, '_'); document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function download() { for (const [name, text] of Object.entries(kit.value.files)) saveBlob(name, text) }
const copied = ref(false)
async function copy() {
  try { await navigator.clipboard.writeText(shown.value); copied.value = true; setTimeout(() => { copied.value = false }, 1500) } catch { /* no clipboard */ }
}

const busy = ref(false)
const saved = ref<{ template_id: string; version: number } | null>(null)
const published = ref(false)
const saveError = ref('')
function why(e: any): string {
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || e?.message || t('migrate.build.failed', 'The request failed.')
}
async function save() {
  busy.value = true; saveError.value = ''; published.value = false
  try {
    const r = await createTemplate({ slug: s.name, title: s.title, summary: s.summary.slice(0, 500), files: kit.value.files })
    saved.value = { template_id: r.template_id, version: r.version }
  } catch (e) { saveError.value = why(e) } finally { busy.value = false }
}
async function publish() {
  if (!saved.value) return
  busy.value = true; saveError.value = ''
  try { await publishVersion(saved.value.template_id, saved.value.version); published.value = true }
  catch (e) { saveError.value = why(e) } finally { busy.value = false }
}
</script>

<style scoped>
.mb { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  max-width: 84rem; margin: 0 auto; padding: 1.6rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.2rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mb-hero { display: grid; gap: .6rem; }
.mb-eyebrow { justify-self: start; font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.mb-hero h1 { margin: 0; font-size: 1.9rem; font-weight: 300; letter-spacing: -.01em; }
.mb-lead { margin: 0; color: var(--muted); font-size: .92rem; max-width: 50rem; line-height: 1.55; }
.mb-privacy { margin: 0; display: flex; gap: .55rem; align-items: flex-start; font-size: .82rem; color: #86efac; border: 1px solid rgba(16,185,129,.3); background: rgba(16,185,129,.05); border-radius: 8px; padding: .55rem .8rem; max-width: 50rem; }
.mb-privacy :deep(svg) { width: 1rem; height: 1rem; flex: none; margin-top: 2px; }
.mb-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 28rem); gap: 1.2rem; align-items: start; }
.mb-col { display: grid; gap: 1rem; min-width: 0; }
.mb-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 12px; padding: 1.1rem 1.25rem 1.2rem; display: grid; gap: .85rem; box-shadow: inset 0 1px 0 rgba(255,255,255,.03), 0 12px 32px -22px rgba(0,0,0,.8); min-width: 0; }
.mb-sticky { position: sticky; top: calc(var(--mb-top, 0px) + 1rem); max-height: calc(100vh - var(--mb-top, 0px) - 2rem); overflow: auto; }
.mb-card h2 { margin: 0; font-size: 1.05rem; font-weight: 500; display: flex; align-items: center; gap: .6rem; }
.mb-n { width: 1.5rem; height: 1.5rem; border-radius: 50%; display: inline-grid; place-items: center; font: 600 .72rem var(--mono); color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb), .4); }
.mb-h3 { margin: .4rem 0 0; font: 700 11px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.mb-row2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem; align-items: start; }
.mb-row3 { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) minmax(0, 1fr); gap: .6rem; }
.mb-f { display: grid; gap: .3rem; font-size: .8rem; min-width: 0; }
.mb-f > span { font: 600 .74rem var(--mono); color: #cbd5e1; }
.mb-f small { color: var(--muted); font-size: .7rem; }
.mb-in { min-height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; padding: 8px 11px; color: var(--bright); font: inherit; font-size: .85rem; width: 100%; min-width: 0; }
.mb-in:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.mb-in.mono { font-family: var(--mono); font-size: .8rem; }
.mb-note { margin: 0; font-size: .76rem; color: var(--muted); line-height: 1.5; }
.mb-note.wide, .mb-warn.wide, .mb-f.wide { grid-column: 1 / -1; }
.mb-warn { margin: 0; font-size: .76rem; color: #fcd34d; }
.mb-err { margin: 0; font-size: .8rem; color: #fca5a5; }
.mb-ok { margin: 0; display: flex; flex-wrap: wrap; align-items: center; gap: .45rem; font-size: .82rem; color: #34d399; }
.mb-ok :deep(svg) { width: 1rem; height: 1rem; }
.mb-link { background: none; border: none; color: var(--cyan); cursor: pointer; font: inherit; font-size: .78rem; text-decoration: underline; padding: 0 6px; min-height: 32px; }
.mb-fr { display: grid; gap: .5rem; border: 1px solid rgba(var(--cyan-rgb), .12); border-radius: 9px; padding: .55rem; }
.mb-fr-main { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.6fr) auto auto; gap: .5rem; align-items: center; }
.mb-fr-more { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .6rem; padding-top: .3rem; border-top: 1px solid rgba(255,255,255,.06); }
.mb-check { display: flex; align-items: center; gap: .55rem; min-height: 36px; font-size: .8rem; color: #cbd5e1; }
.mb-check input { width: 18px; height: 18px; accent-color: var(--cyan); }
.mb-btn { display: inline-flex; align-items: center; justify-content: center; gap: .4rem; min-height: 38px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .84rem; cursor: pointer; }
.mb-btn.small { min-height: 32px; padding: 0 11px; font-size: .76rem; }
.mb-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.mb-btn.ghost { background: none; color: var(--muted); border-color: rgba(var(--cyan-rgb), .18); }
.mb-btn:disabled { opacity: .45; cursor: default; }
.mb-btn:active:not(:disabled) { transform: translateY(1px); }
.mb-x { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: none; color: var(--muted); cursor: pointer; }
.mb-x:hover, .mb-x:focus-visible { color: var(--bright); border-color: rgba(var(--cyan-rgb), .5); }
.mb-x :deep(svg) { width: 1rem; height: 1rem; }
.mb-param { display: grid; gap: .4rem; border-top: 1px solid rgba(255,255,255,.06); padding-top: .55rem; }
.mb-param-head { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; }
.mb-param-head code { font: 600 .8rem var(--mono); color: var(--cyan); }
.mb-chip { font: 600 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #fcd34d; border: 1px solid rgba(245,158,11,.4); border-radius: 999px; padding: 3px 8px; }
.mb-tabs { display: flex; gap: 2px; border-bottom: 1px solid rgba(var(--cyan-rgb), .18); }
.mb-tab { background: none; border: none; border-bottom: 2px solid transparent; color: var(--muted); font: 700 11px/1 var(--mono); letter-spacing: .04em; padding: 10px 12px; cursor: pointer; }
.mb-tab.on { color: var(--cyan); border-bottom-color: var(--cyan); }
.mb-yaml { margin: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: .8rem .9rem; font: .74rem/1.55 var(--mono); max-height: 22rem; overflow: auto; white-space: pre; color: #dbe4ee; }
.mb-yaml:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .5); }
.mb-problems { margin: 0; padding-left: 1.1rem; display: grid; gap: .4rem; font-size: .78rem; color: #fca5a5; }
.mb-rule { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: #fcd34d; margin-right: .3rem; }
.mb-counts { margin: 0; font-size: .84rem; color: var(--muted); }
.mb-counts b { color: var(--bright); font-variant-numeric: tabular-nums; }
.mb-counts b.bad { color: #f87171; }
.mb-reasons { margin: 0; padding-left: 1.1rem; font-size: .78rem; color: #fca5a5; display: grid; gap: .25rem; }
.mb-scroll { overflow: auto; border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; }
.mb-table { width: 100%; border-collapse: collapse; font-size: .76rem; }
.mb-table th { text-align: left; font: 700 10px/1.2 var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 7px 9px; border-bottom: 1px solid rgba(var(--cyan-rgb), .14); white-space: nowrap; }
.mb-table td { padding: 6px 9px; border-bottom: 1px solid rgba(255,255,255,.05); font-family: var(--mono); white-space: nowrap; }
.mb-table tr.refused td { color: #fca5a5; }
.mb-table td.why { white-space: normal; }
.mb-actions { display: flex; flex-wrap: wrap; gap: .5rem; }
.mb-save { display: grid; gap: .6rem; border-top: 1px solid rgba(var(--cyan-rgb), .12); padding-top: .8rem; }
.mb-bar { display: none; }
.mb-out { align-self: stretch; --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', 'Fira Code', monospace; color: var(--bright); font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mb-sheet-close { display: none; }
@media (max-width: 1000px) {
  .mb-grid { grid-template-columns: 1fr; } .mb-sticky { position: static; max-height: none; }
  .mb-out { display: none; }
  .mb-out.sheet { display: grid; align-content: start; position: fixed; inset: 0; z-index: 10000; overflow: auto; padding: 0 .8rem 4rem; background: #05080c; }
  .mb-out.sheet .mb-sheet-close { display: inline-flex; position: sticky; top: 0; z-index: 1; justify-self: stretch; margin: 0 -.8rem .8rem; border-radius: 0; min-height: 48px; background: #0a1218; border-width: 0 0 1px; }
  .mb-bar { display: flex; position: sticky; bottom: 0; z-index: 5; justify-content: space-between; align-items: center; gap: .8rem; margin: 0 -.8rem; padding: .6rem .8rem calc(.6rem + env(safe-area-inset-bottom)); background: rgba(6,12,18,.94); border-top: 1px solid rgba(var(--cyan-rgb), .3); backdrop-filter: blur(6px); }
  .mb-bar-s { font-size: .8rem; color: #fca5a5; } .mb-bar-s.ok { color: #34d399; }
  .mb-bar-a { color: var(--cyan); font: 700 11px/1 var(--mono); letter-spacing: .05em; text-transform: uppercase; text-decoration: none; min-height: 32px; display: inline-flex; align-items: center; }
}
@media (max-width: 640px) {
  .mb { padding: 1rem .8rem 2.5rem; } .mb-hero h1 { font-size: 1.5rem; } .mb-row2, .mb-row3, .mb-fr-more { grid-template-columns: 1fr; }
  .mb-fr-main { grid-template-columns: minmax(0, 1fr) auto auto; } .mb-fr-main .mb-in:nth-child(2) { grid-column: 1 / -1; grid-row: 2; }
  .mb-card { padding: .9rem; }
}
</style>

<style>
html.mb-page, body.mb-page { overflow-x: clip !important; }
</style>
