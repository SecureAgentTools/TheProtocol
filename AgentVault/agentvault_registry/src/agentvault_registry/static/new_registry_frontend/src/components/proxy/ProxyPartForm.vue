<!--
  V0664 C3 (order gwo_4110e12c11a69a93de878829): one source, action or sink's settings, built from its plugin's config_schema in
  the generated catalog. A field the schema marks x-secret, or one named like a credential, takes only a reference (env:NAME or
  file:/path) and says why when it holds anything else. A setting is labelled in words, its key beside it. An object whose
  fields are known is a sub-form (one with an enabled switch shows the rest once it is on); a list of text is one item a
  line; a map of text one Name: value a line; only a setting with no fixed shape is JSON, and the form says so.
  It edits the config object it is given, in place. Required fields and credentials are always shown; the other settings
  fold behind one button that counts them, and a setting that held a value when the form opened (or when it was last
  folded) stays in view, so nothing set is ever hidden.
-->
<template>
  <div class="ppf" :class="{ nested }" :data-testid="`ppf-${prefix}`">
    <div v-for="f in shown" :key="f.key" class="ppf-row" :class="{ wide: !!f.shape }">
      <!-- a setting with fields of its own: a sub-form under its name (mtls: a switch, then its folder) -->
      <fieldset v-if="f.shape === 'form'" class="ppf-sub">
        <legend class="ppf-label"><span class="ppf-words">{{ fieldWords(f.key) }}</span><code class="ppf-key">{{ f.key }}</code></legend>
        <span v-if="f.description" class="ppf-says">{{ f.description }}</span>
        <ProxyPartForm :schema="f.schema" :config="child(f.key)" :prefix="`${prefix}-${f.key}`" nested @changed="sync(f.key)" />
      </fieldset>
      <template v-else>
        <label :for="id(f.key)" class="ppf-label">
          <span class="ppf-words">{{ fieldWords(f.key) }}</span>
          <code class="ppf-key">{{ f.key }}</code>
          <span v-if="f.required" class="ppf-tag">{{ t('proxy.required', 'required') }}</span>
          <span v-if="isSecret(f)" class="ppf-tag ppf-tag-secret">{{ t('proxy.secret', 'a reference') }}</span>
        </label>
        <select v-if="f.enumValues" :id="id(f.key)" :value="config[f.key] ?? ''" :data-testid="`ppf-${prefix}-${f.key}`" @change="setEnum(f, ($event.target as HTMLSelectElement).selectedIndex)">
          <option value="">{{ t('proxy.b.unset', 'not set') }}</option>
          <option v-for="v in f.enumValues" :key="String(v)" :value="v">{{ v }}</option>
        </select>
        <label v-else-if="f.type === 'boolean'" class="ppf-switch">
          <input :id="id(f.key)" type="checkbox" class="ppf-check" :checked="config[f.key] === true"
                 :data-testid="`ppf-${prefix}-${f.key}`" @change="setBool(f.key, ($event.target as HTMLInputElement).checked)" />
          <span>{{ config[f.key] === true ? t('proxy.b.on', 'On') : t('proxy.b.off', 'Off') }}</span>
        </label>
        <input v-else-if="f.type === 'number' || f.type === 'integer'" :id="id(f.key)" type="number" :step="f.type === 'integer' ? 1 : 'any'"
               :value="config[f.key] ?? ''" :placeholder="f.default !== undefined ? String(f.default) : ''" :data-testid="`ppf-${prefix}-${f.key}`"
               @input="setNum(f.key, ($event.target as HTMLInputElement).value, f.type)" />
        <template v-else-if="f.shape === 'lines'">
          <textarea :id="id(f.key)" rows="3" spellcheck="false" :value="lineText[f.key] ?? (Array.isArray(config[f.key]) ? config[f.key].join('\n') : '')"
                    :placeholder="Array.isArray(f.default) ? f.default.join('\n') : ''" :data-testid="`ppf-${prefix}-${f.key}`"
                    @input="setLines(f.key, ($event.target as HTMLTextAreaElement).value)" />
          <span class="ppf-hint">{{ t('proxy.b.oneALine', 'One a line.') }}</span>
        </template>
        <template v-else-if="f.shape === 'pairs'">
          <textarea :id="id(f.key)" rows="3" spellcheck="false" :value="lineText[f.key] ?? pairsText(config[f.key])"
                    placeholder="Name: value" :data-testid="`ppf-${prefix}-${f.key}`"
                    @input="setPairs(f.key, ($event.target as HTMLTextAreaElement).value)" />
          <span v-if="lineError[f.key]" class="ppf-bad" role="alert" :data-testid="`ppf-${prefix}-${f.key}-bad`">{{ lineError[f.key] }}</span>
          <span v-else class="ppf-hint">{{ t('proxy.b.pairsHint', 'One Name: value a line.') }}</span>
        </template>
        <template v-else-if="f.shape === 'json'">
          <textarea :id="id(f.key)" rows="3" spellcheck="false" :value="jsonText[f.key] ?? asJson(config[f.key])"
                    :placeholder="f.type === 'array' ? '[]' : '{}'" :data-testid="`ppf-${prefix}-${f.key}`"
                    @input="setJson(f.key, ($event.target as HTMLTextAreaElement).value)" />
          <span v-if="jsonError[f.key]" class="ppf-bad" role="alert">{{ jsonError[f.key] }}</span>
          <span v-else class="ppf-hint" :data-testid="`ppf-${prefix}-${f.key}-json`">{{ t('proxy.b.jsonSays', 'Written as JSON: this setting has no fixed shape.') }}</span>
        </template>
        <input v-else :id="id(f.key)" type="text" spellcheck="false" autocomplete="off" :value="config[f.key] ?? ''"
               :placeholder="isSecret(f) ? 'env:NAME' : (f.default !== undefined ? String(f.default) : '')"
               :aria-invalid="isSecret(f) && !!secretProblem(config[f.key])" :data-testid="`ppf-${prefix}-${f.key}`"
               @input="setText(f.key, ($event.target as HTMLInputElement).value)" />
        <span v-if="isSecret(f) && secretProblem(config[f.key])" class="ppf-bad" role="alert" :data-testid="`ppf-${prefix}-${f.key}-secret`">{{ secretProblem(config[f.key]) }}</span>
        <span v-else-if="f.description" class="ppf-says">{{ f.description }}</span>
        <span v-else-if="isSecret(f)" class="ppf-says">{{ t('proxy.secretSays', 'A credential, given as env:NAME or file:/path.') }}</span>
      </template>
    </div>
    <button v-if="foldable" type="button" class="ppf-more" :aria-expanded="all" :data-testid="`ppf-${prefix}-more`" @click="toggle">
      {{ all ? t('proxy.b.fewerSettings', 'Fewer settings') : folded === 1 ? t('proxy.b.oneMoreSetting', '1 more setting') : tp('proxy.b.moreSettings', '{n} more settings', { n: folded }) }}
    </button>
    <p v-if="!fields.length" class="ppf-says">{{ t('proxy.noFields', 'No settings.') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { SECRET_KEY, fieldWords, fieldsOf, secretProblem, type FieldDesc } from '@/services/proxy/spec'

type Json = any
const props = defineProps<{ schema: Json; config: Record<string, Json>; prefix: string; nested?: boolean }>()
const emit = defineEmits<{ changed: [] }>()
const { t, tp } = useI18n()
const fields = computed(() => fieldsOf(props.schema))
const isSet = (v: Json) => v !== undefined && v !== null && v !== ''
// the optional settings that stay in view while folded: those that held a value when the form opened or was last folded
const kept = ref<Set<string>>(new Set(Object.keys(props.config).filter((k) => isSet(props.config[k]))))
const all = ref(false)
const isSecret = (f: FieldDesc) => f.secret || SECRET_KEY.test(f.key)
const always = (f: FieldDesc) => !!f.required || isSecret(f) || kept.value.has(f.key)
// a sub-form shows all its fields; one with an enabled switch shows the switch first and the rest once it is on
const toggleField = computed(() => fields.value.find((f) => f.key === 'enabled' && f.type === 'boolean'))
const shown = computed(() => {
  if (props.nested) {
    const tog = toggleField.value
    return tog ? [tog, ...(props.config.enabled === true ? fields.value.filter((f) => f !== tog) : [])] : fields.value
  }
  return all.value ? fields.value : fields.value.filter(always)
})
const foldable = computed(() => !props.nested && fields.value.some((f) => !always(f)))
const folded = computed(() => fields.value.length - fields.value.filter(always).length)
function toggle() {
  if (all.value) kept.value = new Set(Object.keys(props.config).filter((k) => isSet(props.config[k])))
  all.value = !all.value
}
const jsonText = reactive<Record<string, string>>({})
const jsonError = reactive<Record<string, string>>({})
const lineText = reactive<Record<string, string>>({})
const lineError = reactive<Record<string, string>>({})

const id = (key: string) => `ppf-${props.prefix}-${key}`
const asJson = (v: Json) => (v === undefined ? '' : JSON.stringify(v))
const pairsText = (v: Json) => (v && typeof v === 'object' && !Array.isArray(v) ? Object.entries(v).map(([k, x]) => `${k}: ${x}`).join('\n') : '')

// every change is reported up, so a parent form can put a sub-form's object in place or take an empty one away
function changed() { emit('changed') }
function setText(key: string, v: string) {
  if (v === '') delete props.config[key]
  else props.config[key] = v
  changed()
}
function setEnum(f: FieldDesc, index: number) {
  if (index <= 0) delete props.config[f.key]
  else props.config[f.key] = f.enumValues![index - 1]
  changed()
}
function setNum(key: string, v: string, type: string) {
  if (v === '') delete props.config[key]
  else { const n = Number(v); props.config[key] = Number.isFinite(n) ? (type === 'integer' ? Math.trunc(n) : n) : v }
  changed()
}
function setBool(key: string, on: boolean) {
  if (on) props.config[key] = true
  else delete props.config[key]
  changed()
}
function setLines(key: string, v: string) {
  lineText[key] = v
  const items = v.split('\n').map((x) => x.trim()).filter(Boolean)
  if (items.length) props.config[key] = items
  else delete props.config[key]
  changed()
}
function setPairs(key: string, v: string) {
  lineText[key] = v
  const out: Record<string, string> = {}
  let bad = ''
  for (const raw of v.split('\n')) {
    const line = raw.trim()
    if (!line) continue
    const at = line.indexOf(':')
    if (at <= 0) { bad = t('proxy.b.pairBad', 'Each line is Name: value; the spec leaves this one out.'); continue }
    out[line.slice(0, at).trim()] = line.slice(at + 1).trim()
  }
  lineError[key] = bad
  if (Object.keys(out).length) props.config[key] = out
  else delete props.config[key]
  changed()
}
function setJson(key: string, v: string) {
  jsonText[key] = v
  if (!v.trim()) { delete props.config[key]; jsonError[key] = '' }
  else {
    try { props.config[key] = JSON.parse(v); jsonError[key] = '' }
    catch { jsonError[key] = t('proxy.b.jsonBad', 'Not JSON yet: the spec keeps its last good value.') }
  }
  changed()
}
// a sub-form edits its own object; it is in the config while it holds something, and gone when it is empty
const children: Record<string, Record<string, Json>> = {}
function child(key: string): Record<string, Json> {
  const v = props.config[key]
  return (children[key] ??= v && typeof v === 'object' && !Array.isArray(v) ? v : reactive({}))
}
function sync(key: string) {
  const c = children[key]
  if (c && Object.keys(c).length) props.config[key] = c
  else delete props.config[key]
  changed()
}
</script>

<style scoped>
.ppf { --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace; display: grid; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); gap: 0.7rem 0.9rem; }
.ppf-row { display: grid; gap: 0.3rem; align-content: start; min-width: 0; }
.ppf-row.wide { grid-column: 1 / -1; }
.ppf-label { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; font-size: 0.78rem; }

.ppf-tag { font: 600 .6rem var(--mono); text-transform: uppercase; letter-spacing: .05em; color: var(--muted); border: 1px solid rgba(255,255,255,.12); border-radius: 4px; padding: 1px 4px; }
.ppf-tag-secret { color: #fbbf24; border-color: rgba(251,191,36,.35); }
.ppf input[type=text], .ppf input[type=number], .ppf select, .ppf textarea { width: 100%; min-height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; color: #e8eaed; padding: 0 .65rem; font: .8rem var(--mono); box-sizing: border-box; }
.ppf textarea { padding: .5rem .65rem; resize: vertical; line-height: 1.5; }
.ppf input:focus, .ppf select:focus, .ppf textarea:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.ppf input[aria-invalid=true] { border-color: rgba(252,165,165,.6); }
.ppf-check { width: 20px; height: 20px; accent-color: var(--nc-primary, #00d2d2); }
.ppf-says { font-size: .72rem; color: var(--muted); line-height: 1.45; }
.ppf-bad { font-size: .74rem; color: #fca5a5; line-height: 1.45; }
.ppf-words { font: 600 .8rem 'IBM Plex Sans', system-ui, sans-serif; color: #e8eaed; }
.ppf-label .ppf-key { font: .66rem var(--mono); color: var(--muted); font-weight: 400; }
.ppf-hint { font-size: .7rem; color: var(--muted); }
.ppf-switch { display: inline-flex; align-items: center; gap: .5rem; min-height: 40px; font-size: .78rem; color: #cbd5e1; cursor: pointer; }
.ppf-sub { margin: 0; padding: .7rem .8rem .8rem; border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 9px; display: grid; gap: .5rem; min-width: 0; }
.ppf-sub legend { padding: 0 .35rem; }
.ppf.nested { grid-template-columns: repeat(auto-fill, minmax(13rem, 1fr)); }
.ppf-more { grid-column: 1 / -1; justify-self: start; min-height: 36px; padding: 0 .8rem; border-radius: 7px; border: 1px dashed rgba(var(--cyan-rgb), .3); background: transparent; color: #cbd5e1; font: 600 .72rem var(--mono); cursor: pointer; }
.ppf-more:hover { border-color: rgba(var(--cyan-rgb), .6); color: var(--nc-primary, #00d2d2); }
.ppf-more:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
</style>
