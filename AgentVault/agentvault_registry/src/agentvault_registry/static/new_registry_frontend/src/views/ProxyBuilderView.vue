<!--
  V0664 C3 (order gwo_4110e12c11a69a93de878829) — build a proxy spec. Public; nothing is saved on the server and nothing leaves the
  browser: sources, actions and sinks from the SDK's catalog with forms from their config_schema (a credential only as env:NAME or
  file:/path), mappings as rows of target fields with a path or a value node and a live preview on a pasted row
  (services/proxy/mapping.ts), every problem `tp-proxy validate` would name, checked as you type (services/proxy/spec.ts), and
  proxy.yaml, a compose snippet and the run commands to copy or download.
-->
<template>
  <div ref="root" class="pb" data-testid="pb-root">
    <ProxyTabs current="proxy-new" />
    <header class="pb-head">
      <h1>{{ t('proxy.b.title', 'Build a proxy spec') }}</h1>
      <p>{{ t('proxy.b.subtitle', 'Choose where the proxy reads, what it does on TheProtocol and what it hands back, map the fields, and take proxy.yaml with you. Nothing here leaves your browser.') }}</p>
    </header>

    <div class="pb-grid">
      <div class="pb-edit">
        <section class="pb-sec" data-testid="pb-spec">
          <h2>{{ t('proxy.b.spec', 'The spec') }}</h2>
          <div class="pb-fields">
            <label>{{ t('proxy.b.name', 'Name') }}<input v-model="doc.name" type="text" spellcheck="false" data-testid="pb-name" /></label>
            <label>{{ t('proxy.b.registry', 'Registry') }}<input v-model="doc.registry" type="text" spellcheck="false" data-testid="pb-registry" /></label>
            <label>{{ t('proxy.b.state', 'State file') }}<input v-model="doc.state" type="text" spellcheck="false" data-testid="pb-state" /></label>
          </div>
          <p class="pb-fine">{{ t('proxy.b.stateSays', 'The state file is the proxy\'s outbox: it is what makes each record go out once, across restarts. Keep it on a volume.') }}</p>
        </section>

        <section class="pb-sec" data-testid="pb-identity">
          <h2>{{ t('proxy.b.identity', 'Its agent') }}</h2>
          <p class="pb-fine">{{ t('proxy.b.identitySays', 'The proxy acts as its own agent. Name its credentials by reference; the values stay in the environment or a file.') }}</p>
          <ProxyPartForm :schema="IDENTITY_SCHEMA" :config="doc.identity" prefix="identity" />
        </section>

        <section v-for="role in ROLES" :key="role" class="pb-sec" :data-testid="`pb-${role}s`">
          <div class="pb-sec-head">
            <h2>{{ roleWord(role) }}</h2>
            <span class="pb-fine">{{ roleSays(role) }}</span>
          </div>
          <article v-for="(part, name) in doc[SECTION[role]]" :key="name" class="pb-part" :data-testid="`pb-part-${role}-${name}`">
            <header>
              <span class="pb-part-name"><code>{{ name }}</code> · {{ part.type }}</span>
              <button type="button" class="pb-x" :aria-label="tp('proxy.b.removeAria', 'Remove {name}', { name })" :data-testid="`pb-remove-${role}-${name}`" @click="removePart(doc, role, String(name))">{{ t('proxy.b.remove', 'Remove') }}</button>
            </header>
            <p v-if="plugin(role, part.type)?.description" class="pb-fine">{{ firstLine(plugin(role, part.type)?.description) }}</p>
            <ProxyPartForm v-if="plugin(role, part.type)" :schema="plugin(role, part.type)!.config_schema" :config="part.config" :prefix="`${role}-${name}`" />
          </article>
          <form class="pb-add" @submit.prevent="add(role)">
            <label>{{ t('proxy.b.type', 'Type') }}
              <select v-model="adding[role].type" :data-testid="`pb-add-${role}-type`">
                <option v-for="p in pluginsOf(role)" :key="p.name" :value="p.name">{{ p.name }}</option>
              </select>
            </label>
            <label>{{ t('proxy.b.partName', 'Its name in the spec') }}
              <input v-model="adding[role].name" type="text" spellcheck="false" :placeholder="adding[role].type" :data-testid="`pb-add-${role}-name`" />
            </label>
            <button type="submit" class="pb-btn" :disabled="!canAdd(role)" :data-testid="`pb-add-${role}`">{{ addWord(role) }}</button>
            <span v-if="adding[role].name && taken(role, adding[role].name)" class="pb-bad">{{ t('proxy.b.nameTaken', 'That name is taken in this spec.') }}</span>
          </form>
        </section>

        <section class="pb-sec" data-testid="pb-mappings">
          <div class="pb-sec-head">
            <h2>{{ t('proxy.b.mappings', 'Mappings') }}</h2>
            <span class="pb-fine">{{ t('proxy.b.mappingsSay', 'A mapping takes a source\'s records to an action or a sink, field by field.') }}</span>
          </div>
          <article v-for="(m, i) in mappingList" :key="i" class="pb-part" :data-testid="`pb-mapping-${i}`">
            <header>
              <input v-model="m.name" type="text" spellcheck="false" class="pb-map-name" :aria-label="t('proxy.b.mappingName', 'Mapping name')" :data-testid="`pb-mapping-${i}-name`" />
              <button type="button" class="pb-x" :data-testid="`pb-mapping-${i}-remove`" @click="removeMapping(i)">{{ t('proxy.b.remove', 'Remove') }}</button>
            </header>
            <div class="pb-fields">
              <label>{{ t('proxy.b.from', 'From') }}<select v-model="m.from" :data-testid="`pb-mapping-${i}-from`"><option v-for="n in names('source')" :key="n" :value="n">{{ n }}</option></select></label>
              <label>{{ t('proxy.b.to', 'To') }}<select v-model="m.to" :data-testid="`pb-mapping-${i}-to`"><option v-for="n in [...names('action'), ...names('sink')]" :key="n" :value="n">{{ n }}</option></select></label>
            </div>
            <table class="pb-map">
              <thead><tr><th>{{ t('proxy.b.target', 'Field it gets') }}</th><th>{{ t('proxy.b.value', 'Path, literal or value node') }}</th><th><span class="pb-sr">{{ t('proxy.b.remove', 'Remove') }}</span></th></tr></thead>
              <tbody>
                <tr v-for="(row, j) in rows[i]" :key="j">
                  <td><input v-model="row.target" type="text" spellcheck="false" :aria-label="t('proxy.b.target', 'Field it gets')" :data-testid="`pb-mapping-${i}-target-${j}`" @input="sync(i)" /></td>
                  <td>
                    <input v-model="row.value" type="text" spellcheck="false" :placeholder="'$.payload.data.id'" :aria-label="t('proxy.b.value', 'Path, literal or value node')" :data-testid="`pb-mapping-${i}-value-${j}`" @input="sync(i)" />
                    <span v-if="row.bad" class="pb-bad">{{ t('proxy.b.nodeBad', 'A value node is JSON, such as {"path": "$.payload.data.ects", "as": "int"}.') }}</span>
                  </td>
                  <td><button type="button" class="pb-x" :aria-label="t('proxy.b.removeField', 'Remove this field')" @click="rows[i]!.splice(j, 1); sync(i)">×</button></td>
                </tr>
              </tbody>
            </table>
            <button type="button" class="pb-btn pb-btn-ghost" :data-testid="`pb-mapping-${i}-addfield`" @click="rows[i]!.push({ target: '', value: '', bad: false })">{{ t('proxy.b.addField', 'Add a field') }}</button>
            <details class="pb-when">
              <summary>{{ t('proxy.b.when', 'Only some records (when)') }}</summary>
              <div class="pb-fields">
                <label>{{ t('proxy.b.whenPath', 'Path') }}<input v-model="when[i]!.path" type="text" spellcheck="false" placeholder="$.payload.data.status" :data-testid="`pb-mapping-${i}-when-path`" @input="syncWhen(i)" /></label>
                <label>{{ t('proxy.b.whenEquals', 'Equals') }}<input v-model="when[i]!.equals" type="text" spellcheck="false" placeholder="AWARDED" :data-testid="`pb-mapping-${i}-when-equals`" @input="syncWhen(i)" /></label>
              </div>
            </details>
            <div class="pb-preview">
              <label>{{ t('proxy.b.sample', 'Try it on a row (JSON, as the system has it)') }}
                <textarea v-model="sample[i]" rows="3" spellcheck="false" placeholder='{"award_id": "A-1", "ects": "30"}' :data-testid="`pb-mapping-${i}-sample`" />
              </label>
              <span v-if="previews[i]?.kind === 'ok'" class="pb-gets" :data-testid="`pb-mapping-${i}-preview-label`">{{ tp('proxy.b.gets', 'What {to} gets from this row', { to: m.to }) }}</span>
              <p v-if="previews[i]?.kind === 'bad'" class="pb-bad" :data-testid="`pb-mapping-${i}-preview-bad`">{{ t('proxy.b.sampleBad', 'A row is a JSON object.') }}</p>
              <p v-else-if="previews[i]?.kind === 'skip'" class="pb-fine" :data-testid="`pb-mapping-${i}-preview-skip`">{{ t('proxy.b.notTaken', 'Not taken: the mapping\'s when leaves this row out.') }}</p>
              <p v-else-if="previews[i]?.kind === 'refused'" class="pb-bad" :data-testid="`pb-mapping-${i}-preview-refused`">{{ tp('proxy.b.refused', 'Refused: {why}', { why: previews[i]?.text }) }}</p>
              <pre v-else-if="previews[i]?.kind === 'ok'" tabindex="0" role="region" :aria-label="tp('proxy.b.gets', 'What {to} gets from this row', { to: m.to })" class="pb-code" :data-testid="`pb-mapping-${i}-preview`">{{ previews[i]?.text }}</pre>
            </div>
          </article>
          <form class="pb-add" @submit.prevent="newMapping">
            <label>{{ t('proxy.b.from', 'From') }}<select v-model="mapFrom" data-testid="pb-map-from"><option v-for="n in names('source')" :key="n" :value="n">{{ n }}</option></select></label>
            <label>{{ t('proxy.b.to', 'To') }}<select v-model="mapTo" data-testid="pb-map-to"><option v-for="n in [...names('action'), ...names('sink')]" :key="n" :value="n">{{ n }}</option></select></label>
            <button type="submit" class="pb-btn" :disabled="!mapFrom || !mapTo" data-testid="pb-add-mapping">{{ t('proxy.b.addMapping', 'Add a mapping') }}</button>
            <span v-if="!names('source').length" class="pb-fine">{{ t('proxy.b.needSource', 'Add a source first, then an action or a sink.') }}</span>
          </form>
        </section>
      </div>

      <aside class="pb-side">
        <section class="pb-sec pb-check" :class="{ clean: !problems.length && !idle, idle: !problems.length && idle }" data-testid="pb-problems" aria-live="polite">
          <h2 v-if="problems.length">{{ tp('proxy.b.problems', '{n} to fix before it runs', { n: problems.length }) }}</h2>
          <template v-else-if="idle">
            <h2>{{ t('proxy.b.idle', 'Valid, but it reads nothing yet') }}</h2>
            <p class="pb-fine">{{ t('proxy.b.idleSays', 'Add a source, then a mapping to an action or a sink.') }}</p>
          </template>
          <h2 v-else>{{ t('proxy.b.clean', 'Ready: tp-proxy validate would take it') }}</h2>
          <ul v-if="problems.length">
            <li v-for="p in placed" :key="p.where + p.what">
              <button v-if="p.target" type="button" class="pb-prob" :title="t('proxy.b.probGo', 'Go to the field')" @click="goTo(p.target)"><code v-if="p.where">{{ p.where }}</code>: {{ p.what }}</button>
              <span v-else class="pb-prob"><code v-if="p.where">{{ p.where }}</code><template v-if="p.where">: </template>{{ p.what }}</span>
            </li>
          </ul>
        </section>
        <section id="pb-out" class="pb-sec" data-testid="pb-output">
          <div class="pb-out-tabs" role="tablist">
            <button v-for="o in OUTPUTS" :key="o" type="button" role="tab" class="pb-out-tab" :class="{ on: out === o }" :aria-selected="out === o" :data-testid="`pb-out-${o}`" @click="out = o">{{ outWord(o) }}</button>
          </div>
          <pre class="pb-code pb-code-out" :data-testid="`pb-out-text`" tabindex="0" role="region" :aria-label="tp('proxy.b.outAria', 'The output: {what}', { what: outWord(out) })">{{ outText }}</pre>
          <div class="pb-out-acts">
            <button type="button" class="pb-btn" data-testid="pb-copy" @click="copy">{{ copied ? t('proxy.b.copied', 'Copied') : t('proxy.b.copy', 'Copy') }}</button>
            <button v-if="out !== 'run'" type="button" class="pb-btn pb-btn-ghost" data-testid="pb-download" @click="download">{{ tp('proxy.b.download', 'Download {file}', { file: outFile }) }}</button>
          </div>
        </section>
      </aside>
    </div>

    <div class="pb-bar" :class="{ clean: !problems.length && !idle, idle: !problems.length && idle }" data-testid="pb-bar">
      <span class="pb-bar-says">{{ problems.length ? tp('proxy.b.problems', '{n} to fix before it runs', { n: problems.length }) : idle ? t('proxy.b.barIdle', 'Nothing to run yet') : t('proxy.b.barReady', 'Ready to validate') }}</span>
      <button type="button" class="pb-btn" data-testid="pb-bar-go" @click="goOut">{{ t('proxy.b.barGo', 'See proxy.yaml') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import ProxyPartForm from '@/components/proxy/ProxyPartForm.vue'
import ProxyTabs from '@/components/proxy/ProxyTabs.vue'
import { useI18n } from '@/composables/useI18n'
import {
  CORE_SCHEMA, ROLES, SECTION, addMapping, addPart, checkSpecDetailed, composeSnippet, newSpec, plugin, pluginsOf, previewMapping,
  problemTarget, removePart, runCommands, toProxyYaml, type Role,
} from '@/services/proxy/spec'

type Json = any
const { t, tp } = useI18n()
const IDENTITY_SCHEMA = CORE_SCHEMA.properties.identity
const OUTPUTS = ['yaml', 'compose', 'run'] as const

const doc = reactive<Json>(newSpec('my-proxy'))
const adding = reactive<Record<Role, { type: string; name: string }>>({
  source: { type: pluginsOf('source')[0]?.name || '', name: '' },
  action: { type: pluginsOf('action')[0]?.name || '', name: '' },
  sink: { type: pluginsOf('sink')[0]?.name || '', name: '' },
})
interface Row { target: string; value: string; bad: boolean }
const rows = reactive<Row[][]>([])
const when = reactive<Array<{ path: string; equals: string }>>([])
const sample = reactive<string[]>([])
/** The mappings as a list, so the template's index is a number (doc is free-form JSON). */
const mappingList = computed<Json[]>(() => doc.mappings || [])
const mapFrom = ref('')
const mapTo = ref('')
const out = ref<(typeof OUTPUTS)[number]>('yaml')
const copied = ref(false)

const NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$/
const names = (role: Role): string[] => Object.keys(doc[SECTION[role]] || {})
// sources have their own names; actions and sinks share one namespace (spec.py)
const taken = (role: Role, name: string) => (role === 'source' ? names('source') : [...names('action'), ...names('sink')]).includes(name)
const canAdd = (role: Role) => { const n = adding[role].name || adding[role].type; return !!adding[role].type && NAME.test(n) && !taken(role, n) }

function add(role: Role) {
  if (!canAdd(role)) return
  const name = adding[role].name || adding[role].type
  addPart(doc, role, name, adding[role].type)
  adding[role].name = ''
  if (role === 'source' && !mapFrom.value) mapFrom.value = name
  if (role !== 'source' && !mapTo.value) mapTo.value = name
}

function newMapping() {
  if (!mapFrom.value || !mapTo.value) return
  addMapping(doc, mapFrom.value, mapTo.value)
  rows.push([{ target: '', value: '', bad: false }])
  when.push({ path: '', equals: '' })
  sample.push('')
}
function removeMapping(i: number) {
  doc.mappings.splice(i, 1); rows.splice(i, 1); when.splice(i, 1); sample.splice(i, 1)
}

function nodeOf(text: string): { node: Json; bad: boolean } {
  const v = text.trim()
  if (v.startsWith('{')) { try { return { node: JSON.parse(v), bad: false } } catch { return { node: v, bad: true } } }
  return { node: text, bad: false }
}
function sync(i: number) {
  const fields: Record<string, Json> = {}
  for (const r of rows[i] || []) {
    const { node, bad } = nodeOf(r.value)
    r.bad = bad
    if (r.target.trim()) fields[r.target.trim()] = node
  }
  doc.mappings[i].fields = fields
}
function syncWhen(i: number) {
  const w = when[i]!
  if (w.path.trim()) doc.mappings[i].when = { path: w.path.trim(), equals: w.equals }
  else delete doc.mappings[i].when
}

// a removed source, action or sink takes its mappings with it (spec.removePart): keep the rows beside them
const keepAligned = () => {
  while (rows.length > doc.mappings.length) { rows.pop(); when.pop(); sample.pop() }
}

const detailed = computed(() => { keepAligned(); return checkSpecDetailed(JSON.parse(JSON.stringify(doc))) })
const problems = computed(() => detailed.value.map((d) => d.raw))
// V0665: a schema error is listed in the field's own words ("Listen is required"), through the i18n layer; the place (the spec path) stays as
// tp-proxy validate names it, and anything the words do not cover keeps the checker's own sentence
const say = { t: (k: string, fb: string) => t(k, fb), tp: (k: string, fb: string, p: Record<string, string | number>) => tp(k, fb, p) }
const placed = computed(() => detailed.value.map((d) => { const p = problemTarget(d.raw); return d.say ? { ...p, what: d.say(say) } : p }))
/** A problem's button: to its control (a field by its id, a mapping's end by its test id), centred and focused. */
function goTo(target: string) {
  const el = document.getElementById(target) || document.querySelector<HTMLElement>(`[data-testid="${target}"]`)
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.focus({ preventScroll: true })
}
/** A spec tp-proxy validate takes that still reads nothing: no source, or nothing mapped from one (pass 3: not "Ready"). */
const idle = computed(() => !names('source').length || !(doc.mappings || []).length)

const previews = computed(() => doc.mappings.map((m: Json, i: number) => {
  const text = (sample[i] || '').trim()
  if (!text) return null
  let row: Json
  try { row = JSON.parse(text) } catch { return { kind: 'bad' } }
  if (!row || typeof row !== 'object' || Array.isArray(row)) return { kind: 'bad' }
  const type = doc.sources?.[m.from]?.type || ''
  const p = previewMapping(m, type, row)
  if (!p.taken) return { kind: 'skip' }
  if (p.refused) return { kind: 'refused', text: p.refused }
  return { kind: 'ok', text: JSON.stringify(p.fields, null, 2) }
}))

const outText = computed(() => {
  const d = JSON.parse(JSON.stringify(doc))
  return out.value === 'yaml' ? toProxyYaml(d) : out.value === 'compose' ? composeSnippet(d) : runCommands(d).join('\n')
})
const outFile = computed(() => (out.value === 'compose' ? 'docker-compose.yml' : 'proxy.yaml'))
const outWord = (o: string) => (o === 'yaml' ? 'proxy.yaml' : o === 'compose' ? t('proxy.b.compose', 'Compose') : t('proxy.b.run', 'Run it'))

async function copy() {
  try { await navigator.clipboard.writeText(outText.value); copied.value = true; setTimeout(() => (copied.value = false), 1600) }
  catch { copied.value = false }
}
function download() {
  const url = URL.createObjectURL(new Blob([outText.value], { type: 'text/yaml' }))
  const a = document.createElement('a')
  a.href = url; a.download = outFile.value
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function roleWord(r: Role): string {
  return r === 'source' ? t('proxy.sources', 'Sources') : r === 'action' ? t('proxy.actions', 'Actions') : t('proxy.sinks', 'Sinks')
}
// a whole phrase per role, so each language can say it its way (English: a source, an action, a sink)
function addWord(r: Role): string {
  return r === 'source' ? t('proxy.b.addSource', 'Add a source') : r === 'action' ? t('proxy.b.addAction', 'Add an action') : t('proxy.b.addSink', 'Add a sink')
}
function roleSays(r: Role): string {
  if (r === 'source') return t('proxy.sourcesSay', 'Where the proxy reads the system\'s records.')
  if (r === 'action') return t('proxy.actionsSay', 'What it does on TheProtocol with a record, as its own agent.')
  return t('proxy.sinksSay', 'What it hands back to the system: TheProtocol\'s events, as a webhook, a journal, a file.')
}
// The app shell sets overflow-x: hidden on <html>, which makes <html> a scroll container of its own height, so position:
// sticky had nothing to stick to and the problems and outputs scrolled away (C4 met the same in its builder). While this page
// is open the shell clips the overflow instead: the same thing hidden, the viewport left as the scroller.
// The app's beta banner is sticky at the top of the viewport: the outputs column sticks below it, at its live height (0 once
// it is dismissed), published as --pb-top on this page's root and read again on every scroll and resize.
const root = ref<HTMLElement | null>(null)
let frame = 0
function placeBelowBanner() {
  frame = 0
  const b = document.querySelector('.beta-banner')
  const h = b ? Math.max(0, Math.round(b.getBoundingClientRect().bottom)) : 0
  root.value?.style.setProperty('--pb-top', `${h}px`)
}
const onScroll = () => { if (!frame) frame = requestAnimationFrame(placeBelowBanner) }
onMounted(() => {
  document.documentElement.classList.add('pb-page'); document.body.classList.add('pb-page')
  placeBelowBanner()
  window.addEventListener('scroll', onScroll, { passive: true }); window.addEventListener('resize', onScroll)
})
onBeforeUnmount(() => {
  document.documentElement.classList.remove('pb-page'); document.body.classList.remove('pb-page')
  window.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll)
  if (frame) cancelAnimationFrame(frame)
})
/** The phone bar's button: to the outputs, which on a phone sit below the whole form. */
function goOut() { document.getElementById('pb-out')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
const firstLine = (s?: string) => (s || '').split('\n')[0]!.replace(/\s+/g, ' ').trim()
</script>

<style scoped>
.pb { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  max-width: 80rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: #e8eaed; display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.pb-head h1 { margin: 0; font-size: 1.6rem; font-weight: 300; }
.pb-head p { margin: 0.3rem 0 0; font-size: 0.88rem; color: var(--muted); max-width: 48rem; line-height: 1.55; }
.pb-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(19rem, 26rem); gap: 1rem; align-items: start; }
.pb-edit { display: grid; gap: 0.9rem; min-width: 0; }
.pb-side { position: sticky; top: calc(var(--pb-top, 0px) + 1rem); display: grid; gap: 0.9rem; min-width: 0; max-height: calc(100vh - var(--pb-top, 0px) - 2rem); overflow-y: auto; overscroll-behavior: contain; }
.pb-sec { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1rem 1.1rem; display: grid; gap: 0.7rem; min-width: 0; }
.pb-sec h2 { margin: 0; font-size: 1rem; font-weight: 500; }
.pb-sec-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.3rem 0.9rem; }
.pb-fields { display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 0.6rem 0.9rem; }
.pb-fields label, .pb-add label, .pb-preview label { display: grid; gap: 0.3rem; font: 600 .72rem var(--mono); color: #cbd5e1; }
.pb input[type=text], .pb select, .pb textarea { width: 100%; min-height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; color: #e8eaed; padding: 0 .65rem; font: .8rem var(--mono); box-sizing: border-box; }
.pb textarea { padding: .5rem .65rem; resize: vertical; line-height: 1.5; }
.pb input:focus, .pb select:focus, .pb textarea:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.pb-fine { margin: 0; font-size: 0.76rem; color: var(--muted); line-height: 1.5; }
.pb-bad { font-size: .74rem; color: #fca5a5; line-height: 1.45; margin: 0; }
.pb-part { border: 1px solid rgba(255,255,255,.08); border-radius: 10px; background: rgba(0,0,0,.18); padding: 0.8rem 0.9rem; display: grid; gap: 0.6rem; min-width: 0; }
.pb-part header { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; }
.pb-part-name { font-size: 0.84rem; }
.pb-part-name code { font: 600 .84rem var(--mono); color: var(--cyan); }
.pb-map-name { max-width: 22rem; }
.pb-add { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; }
.pb-add label { flex: 1 1 11rem; }
.pb-btn { min-height: 40px; padding: 0 1rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .55); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: 600 .78rem var(--mono); cursor: pointer; white-space: nowrap; }
.pb-btn:disabled { opacity: .45; cursor: not-allowed; }
.pb-btn-ghost { background: transparent; border-color: rgba(var(--cyan-rgb), .3); justify-self: start; }
.pb-btn:focus-visible, .pb-x:focus-visible, .pb-out-tab:focus-visible, summary:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.pb-x { min-height: 36px; min-width: 36px; padding: 0 .7rem; border-radius: 7px; border: 1px solid rgba(255,255,255,.12); background: transparent; color: #cbd5e1; font: 600 .74rem var(--mono); cursor: pointer; }
.pb-x:hover { border-color: rgba(252,165,165,.5); color: #fca5a5; }
.pb-map { width: 100%; border-collapse: collapse; }
.pb-map th { text-align: left; font: 600 .64rem var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); padding: 0 0.3rem 0.3rem; }
.pb-map td { padding: 0.2rem 0.3rem; vertical-align: top; }
.pb-map td:first-child { width: 32%; }
.pb-map td:last-child { width: 1%; }
.pb-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.pb-when summary { cursor: pointer; font: 600 .74rem var(--mono); color: #cbd5e1; min-height: 32px; display: flex; align-items: center; gap: 0.5rem; list-style: none; }
.pb-when summary::-webkit-details-marker { display: none; }
.pb-when summary::before { content: ''; flex: none; width: 0.4rem; height: 0.4rem; border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; transform: rotate(-45deg); transition: transform .15s ease; }
.pb-when[open] summary::before { transform: rotate(45deg); }
.pb-when summary:hover { color: var(--cyan); }
.pb-gets { font: 600 .66rem var(--mono); letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.pb-bar { display: none; }
.pb-when .pb-fields { margin-top: 0.4rem; }
.pb-preview { display: grid; gap: 0.4rem; }
.pb-code { margin: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: 0.7rem 0.9rem; font: 0.76rem/1.6 var(--mono); overflow: auto; white-space: pre; color: #dbe4ee; }
.pb-code-out { max-height: 60vh; }
.pb-code:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.pb-check ul { margin: 0; padding: 0; list-style: none; display: grid; gap: 0.35rem; }
.pb-prob { display: block; width: 100%; text-align: left; background: none; border: 0; padding: .3rem .45rem; margin: 0 -.45rem; border-radius: 6px;
  font: .8rem/1.45 'IBM Plex Sans', system-ui, sans-serif; color: #fca5a5; overflow-wrap: anywhere; }
button.pb-prob { cursor: pointer; }
button.pb-prob:hover { background: rgba(252,165,165,.08); }
button.pb-prob:focus-visible { outline: 2px solid rgba(252,165,165,.5); outline-offset: 1px; }
.pb-prob code { font: .7rem var(--mono); color: #f8b4b4; opacity: .8; }
.pb-check h2 { color: #fca5a5; font-size: .9rem; }
.pb-check.clean h2 { color: #34d399; }
.pb-check.idle h2 { color: #fbbf24; }
.pb-out-tabs { display: flex; gap: 0.35rem; flex-wrap: wrap; }
.pb-out-tab { min-height: 36px; padding: 0 .8rem; border-radius: 7px; border: 1px solid rgba(var(--cyan-rgb), .18); background: transparent; color: #cbd5e1; font: 600 .74rem var(--mono); cursor: pointer; }
.pb-out-tab.on { border-color: rgba(var(--cyan-rgb), .6); color: var(--cyan); background: rgba(var(--cyan-rgb), .08); }
.pb-out-acts { display: flex; gap: 0.5rem; flex-wrap: wrap; }
@media (max-width: 960px) {
  .pb-grid { grid-template-columns: 1fr; }
  .pb-side { position: static; max-height: none; overflow: visible; }
  .pb-bar { display: flex; position: sticky; bottom: 0.6rem; z-index: 5; align-items: center; justify-content: space-between; gap: 0.6rem; padding: 0.55rem 0.6rem 0.55rem 0.9rem;
    border-radius: 10px; border: 1px solid rgba(252,165,165,.35); background: rgba(12,16,22,.96); box-shadow: 0 8px 24px rgba(0,0,0,.45); }
  .pb-bar.clean { border-color: rgba(52,211,153,.4); }
  .pb-bar-says { font: 600 .74rem var(--mono); color: #fca5a5; }
  .pb-bar.clean .pb-bar-says { color: #34d399; }
  .pb-bar.idle { border-color: rgba(251,191,36,.4); }
  .pb-bar.idle .pb-bar-says { color: #fbbf24; }
}
@media (max-width: 720px) { .pb { padding: 1rem .8rem 2.5rem; } .pb-map td:first-child { width: 38%; } }
</style>

<style>
html.pb-page, body.pb-page { overflow-x: clip !important; }
</style>
