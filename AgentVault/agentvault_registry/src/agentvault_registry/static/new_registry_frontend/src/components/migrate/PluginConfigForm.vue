<!--
  V0664 C4 — a form for one plugin's config, built from the catalog's own config_schema (the SDK's truth, copied by C1's generator). A destination
  (host, url, database, path, dir) and a secret never take a value here: a kit names no destination of its own and carries no credential, so the
  field takes the NAME of a parameter the user will set (and for a secret, as a reference), and the config holds ${NAME}.
-->
<template>
  <div class="pcf">
    <p v-if="hasParam" :id="`${idp}-rule`" class="pcf-rule" :data-testid="`mb-cfg-${role}-rule`">
      {{ t('migrate.build.whyDestination', 'A published kit names no destination of its own: a host, url, database or path field takes the name of a parameter the user sets.') }}
      <template v-if="hasSecret"> {{ t('migrate.build.whySecret', 'A secret is never written into a kit: it takes a name too, and the user gives it as a reference (env:NAME or file:/path).') }}</template>
    </p>
    <template v-for="(f, i) in ordered" :key="f.key">
    <button v-if="i === firstOptional" type="button" class="pcf-toggle" data-testid="mb-cfg-more" :aria-expanded="showMore ? 'true' : 'false'" @click="showMore = !showMore">
      {{ showMore ? t('migrate.build.fewerOptions', 'Fewer options') : tp('migrate.build.moreOptions', 'More options ({n})', { n: fields.length - firstOptional }) }}
    </button>
    <div v-show="i < firstOptional || showMore" class="pcf-row">
      <label :for="`${idp}-${f.key}`" class="pcf-label"><span class="pcf-words">{{ words(f) }}</span><span v-if="f.required" class="pcf-req" :title="t('migrate.build.required', 'required')">*</span><code class="pcf-key">{{ f.key }}</code></label>
      <template v-if="f.kind === 'param'">
        <div class="pcf-param">
          <span class="pcf-dollar" aria-hidden="true">${</span>
          <input :id="`${idp}-${f.key}`" :data-testid="`mb-cfg-${role}-${f.key}`" :value="paramName(f.key)" class="pcf-input mono" spellcheck="false" autocapitalize="off"
                 :placeholder="f.suggest" :aria-describedby="`${idp}-rule`" @input="onParam(f.key, ($event.target as HTMLInputElement).value)" />
          <span class="pcf-dollar" aria-hidden="true">}</span>
        </div>
        <p v-if="errors[f.key]" class="pcf-err" :data-testid="`mb-cfg-${role}-${f.key}-err`" role="alert">{{ errors[f.key] }}</p>
        <p v-if="f.description && !(f.secret && /env:/.test(f.description))" :id="`${idp}-${f.key}-why`" class="pcf-why" :data-testid="`mb-cfg-${role}-${f.key}-why`">{{ f.description }}</p>
      </template>
      <template v-else>
        <select v-if="f.kind === 'enum'" :id="`${idp}-${f.key}`" :data-testid="`mb-cfg-${role}-${f.key}`" class="pcf-input" :value="valueOf(f.key)" @change="onValue(f, ($event.target as HTMLSelectElement).value)">
          <option value="">{{ t('migrate.build.notSet', 'not set') }}{{ f.default !== undefined ? ` (${f.default})` : '' }}</option>
          <option v-for="o in f.enum" :key="String(o)" :value="String(o)">{{ o }}</option>
        </select>
        <select v-else-if="f.kind === 'boolean'" :id="`${idp}-${f.key}`" :data-testid="`mb-cfg-${role}-${f.key}`" class="pcf-input" :value="valueOf(f.key)" @change="onValue(f, ($event.target as HTMLSelectElement).value)">
          <option value="">{{ t('migrate.build.notSet', 'not set') }}{{ f.default !== undefined ? ` (${f.default})` : '' }}</option>
          <option value="true">true</option><option value="false">false</option>
        </select>
        <textarea v-else-if="f.kind === 'object'" :id="`${idp}-${f.key}`" :data-testid="`mb-cfg-${role}-${f.key}`" class="pcf-input mono" rows="2" spellcheck="false" :value="valueOf(f.key)" @input="onValue(f, ($event.target as HTMLTextAreaElement).value)" />
        <input v-else :id="`${idp}-${f.key}`" :data-testid="`mb-cfg-${role}-${f.key}`" class="pcf-input" :class="{ mono: f.kind === 'list' }" :type="f.kind === 'number' ? 'number' : 'text'"
               :value="valueOf(f.key)" :placeholder="f.default !== undefined ? String(f.default) : f.kind === 'list' ? 'a, b' : ''" spellcheck="false" @input="onValue(f, ($event.target as HTMLInputElement).value)" />
        <p v-if="errors[f.key]" class="pcf-err" :data-testid="`mb-cfg-${role}-${f.key}-err`" role="alert">{{ errors[f.key] }}</p>
        <p v-if="f.description" class="pcf-why">{{ f.description }}</p>
      </template>
    </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'

type Json = any
const props = defineProps<{ role: 'source' | 'sink'; schema: Json; config: Record<string, Json>; prefix: string }>()
const emit = defineEmits<{ (e: 'change'): void }>()
const { t, tp } = useI18n()
const idp = computed(() => `pcf-${props.role}`)
const errors = reactive<Record<string, string>>({})

const DEST = ['url', 'host', 'database', 'path', 'dir']
const SECRET = /(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$/i
const NAME = /^[A-Za-z_][A-Za-z0-9_]{0,62}$/
const PLACEHOLDER = /^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$/

interface Field { key: string; title?: string; kind: 'param' | 'enum' | 'boolean' | 'number' | 'list' | 'object' | 'text'; required: boolean; description?: string; enum?: Json[]; default?: Json; secret?: boolean; suggest?: string }
const fields = computed<Field[]>(() => {
  const props_: Record<string, Json> = props.schema?.properties || {}
  const required: string[] = props.schema?.required || []
  const out: Field[] = Object.entries(props_).map(([key, s]) => {
    const secret = s['x-secret'] === true || (s.type === 'string' && SECRET.test(key))
    const base = { key, title: s.title as string | undefined, required: required.includes(key), description: s.description as string | undefined, default: s.default }
    if (secret) return { ...base, kind: 'param' as const, secret: true, suggest: `${props.prefix}_${key.toUpperCase()}` }
    if (DEST.includes(key)) return { ...base, kind: 'param' as const, suggest: `${props.prefix}_${key.toUpperCase()}` }
    if (Array.isArray(s.enum)) return { ...base, kind: 'enum' as const, enum: s.enum }
    if (s.type === 'boolean') return { ...base, kind: 'boolean' as const }
    if (s.type === 'integer' || s.type === 'number') return { ...base, kind: 'number' as const }
    if (s.type === 'array') return { ...base, kind: 'list' as const }
    if (s.type === 'object') return { ...base, kind: 'object' as const }
    return { ...base, kind: 'text' as const }
  })
  return out.sort((a, b) => Number(b.required) - Number(a.required))
})

// what a person fills in first: the required fields and every destination or secret (each is a parameter); the rest sits under "More options"
// (unless one of them is already set, which keeps it in view)
// (a snapshot at mount, so a field does not jump up the form while it is being typed into)
const setAtMount = new Set(Object.keys(props.config).filter((k) => props.config[k] !== undefined && props.config[k] !== ''))
const isSet = (key: string) => setAtMount.has(key)
const ordered = computed<Field[]>(() => [...fields.value.filter((f) => f.required || f.kind === 'param' || isSet(f.key)), ...fields.value.filter((f) => !(f.required || f.kind === 'param' || isSet(f.key)))])
const firstOptional = computed(() => { const n = ordered.value.findIndex((f) => !(f.required || f.kind === 'param' || isSet(f.key))); return n < 0 ? fields.value.length : n })
const showMore = ref(false)
const hasParam = computed(() => fields.value.some((f) => f.kind === 'param'))
const hasSecret = computed(() => fields.value.some((f) => f.secret))
/** a key in words (the schema's title when it has one): on_conflict -> On conflict; the key itself stays beside it, small, in mono */
const words = (f: Field): string => { const w = String(f.title || f.key).replace(/[_-]+/g, ' ').trim(); return w.charAt(0).toUpperCase() + w.slice(1) }
const paramName = (key: string) => { const m = PLACEHOLDER.exec(String(props.config[key] ?? '')); return m ? m[1] : '' }
function valueOf(key: string): string {
  const v = props.config[key]
  if (v === undefined || v === null) return ''
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
function onParam(key: string, raw: string) {
  const v = raw.trim()
  if (!v) { delete props.config[key]; delete errors[key]; emit('change'); return }
  if (!NAME.test(v)) { errors[key] = t('migrate.build.badParam', 'A parameter name is letters, digits and underscores, and does not start with a digit.'); return }
  delete errors[key]
  props.config[key] = '${' + v + '}'
  emit('change')
}
function onValue(f: Field, raw: string) {
  const key = f.key
  delete errors[key]
  if (raw === '') delete props.config[key]
  else if (f.kind === 'number') props.config[key] = Number(raw)
  else if (f.kind === 'boolean') props.config[key] = raw === 'true'
  else if (f.kind === 'list') props.config[key] = raw.split(',').map((x) => x.trim()).filter(Boolean)
  else if (f.kind === 'object') {
    try { const o = JSON.parse(raw); if (!o || typeof o !== 'object' || Array.isArray(o)) throw new Error('x'); props.config[key] = o } catch { errors[key] = t('migrate.build.badJson', 'A JSON object, like {"sslmode": "require"}.'); return }
  } else if (f.kind === 'enum') props.config[key] = (f.enum || []).find((o) => String(o) === raw) ?? raw
  else props.config[key] = raw
  emit('change')
}
</script>

<style scoped>
.pcf { display: grid; gap: .9rem; }
.pcf-row { display: grid; gap: .3rem; }
.pcf-label { display: flex; flex-wrap: wrap; align-items: baseline; gap: .15rem .5rem; font: 600 .84rem 'IBM Plex Sans', system-ui, sans-serif; color: #dbe4ee; }
.pcf-words { font-weight: 600; }
.pcf-key { font: .68rem 'IBM Plex Mono', monospace; color: #8b97a6; background: none; padding: 0; }
.pcf-rule { margin: 0 0 .2rem; padding: .6rem .8rem; border-left: 2px solid var(--nc-primary, #00d2d2); background: rgba(var(--nc-primary-rgb, 0,210,210), .05); border-radius: 0 8px 8px 0; font-size: .78rem; line-height: 1.55; color: #aab4c0; }
.pcf-req { color: var(--nc-primary, #00d2d2); margin-left: 3px; }
.pcf-input { min-height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .18); border-radius: 7px; padding: 8px 11px; color: #e8eaed; font: inherit; font-size: .85rem; width: 100%; }
.pcf-input:focus { outline: none; border-color: rgba(var(--nc-primary-rgb, 0,210,210), .5); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb, 0,210,210), .12); }
.pcf-input.mono { font-family: 'IBM Plex Mono', monospace; font-size: .8rem; }
.pcf-param { display: flex; align-items: center; gap: 4px; }
.pcf-dollar { font: 600 .85rem 'IBM Plex Mono', monospace; color: var(--nc-primary, #00d2d2); }
.pcf-why { margin: 0; font-size: .72rem; color: #8b97a6; line-height: 1.5; }
.pcf-desc { color: #94a3b8; }
.pcf-err { margin: 0; font-size: .74rem; color: #fca5a5; }
.pcf-toggle { justify-self: start; min-height: 34px; padding: 0 14px; border-radius: 8px; border: 1px dashed rgba(var(--nc-primary-rgb, 0,210,210), .35); background: none; color: var(--nc-primary, #00d2d2); font: inherit; font-size: .8rem; cursor: pointer; }
.pcf-toggle:hover, .pcf-toggle:focus-visible { background: rgba(var(--nc-primary-rgb, 0,210,210), .08); }
</style>
