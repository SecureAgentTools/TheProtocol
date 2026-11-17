<!--
  V0667 D5 (order gwo_d238dcda72add8e05b6d657b): proposing a content change into an organization's release line, #/contributions/content/new?line=<slug>: the kind (a migration kit, a proxy spec, a
  policy value, a console text, its branding), the target, the content, and why. Our checker reads it before anything is stored, so a refusal here names the rule and the field and wrote nothing. Proposing is
  the selected agent's, the registry decides again; on a registry that does not govern code the page says so and offers nothing (V0666's authority).
-->
<template>
  <div class="cnn" data-testid="cnn-root">
    <RouterLink :to="{ name: 'contributions', query: { line: d.line || undefined } }" class="cnn-back" data-testid="cnn-back">{{ t('contributions.propose.back', 'Back to the release line') }}</RouterLink>
    <header class="cnn-hero">
      <span class="cnn-eyebrow">{{ t('contentChanges.eyebrow', 'The fast lane') }}</span>
      <h1>{{ t('contentChanges.new.title', 'Propose a content change') }}</h1>
      <p class="cnn-lede">{{ t('contentChanges.new.lede', 'The organization’s own content, changed after the line’s ballot and our checker, in hours and not in a release. Never code, never another organization’s space, never anything global.') }}</p>
      <p v-if="q('room')" class="cnn-lede" data-testid="cnn-room">{{ t('contentChanges.new.room', 'The change is announced in the room you came from: its live card follows it there, and each step posts one line.') }}</p>
      <p v-if="!canPropose" class="cnn-warn" data-testid="cnn-signin">{{ t('codeChanges.new.signIn', 'Sign in and pick an agent (top right) to propose. You can walk through the steps without.') }}</p>
    </header>

    <GovernedElsewhere v-if="authorityView_.readOnly" :view="authorityView_" />

    <form v-else class="cnn-card" data-testid="cnn-form" novalidate @submit.prevent="submit">
      <label class="cnn-f"><span>{{ t('contentChanges.form.line', 'Release line') }}</span>
        <input v-model.trim="d.line" class="cnn-in" maxlength="40" data-testid="cnn-line" :aria-invalid="touched && has('line') ? 'true' : 'false'" /></label>
      <label class="cnn-f"><span>{{ t('contentChanges.form.kind', 'What changes') }}</span>
        <select v-model="d.kind" class="cnn-in" data-testid="cnn-kind"><option v-for="k in CONTENT_KINDS" :key="k" :value="k">{{ kindWord(k, tr) }}</option></select></label>
      <label v-if="d.kind !== 'branding'" class="cnn-f"><span>{{ targetLabel(d.kind, tr) }}</span>
        <input v-model.trim="d.target" class="cnn-in" maxlength="200" spellcheck="false" data-testid="cnn-target" :aria-invalid="touched && has('target') ? 'true' : 'false'" /></label>

      <p v-if="d.kind === 'compliance_pack'" class="cnn-lede" data-testid="cnn-pack-note">{{ t('contentChanges.packNote', 'A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.') }}</p>
      <label v-if="d.kind === 'kit'" class="cnn-f"><span>{{ t('contentChanges.form.files', 'The kit’s files (JSON: path to text)') }}</span>
        <textarea v-model="d.filesJson" class="cnn-in mono" rows="10" spellcheck="false" data-testid="cnn-files" :aria-invalid="touched && has('files') ? 'true' : 'false'" /></label>
      <label v-else-if="d.kind === 'proxy_spec'" class="cnn-f"><span>{{ t('contentChanges.form.proxy', 'The new proxy.yaml') }}</span>
        <textarea v-model="d.proxyYaml" class="cnn-in mono" rows="10" spellcheck="false" data-testid="cnn-proxy" :aria-invalid="touched && has('proxy_yaml') ? 'true' : 'false'" /></label>
      <label v-else-if="d.kind === 'policy_value'" class="cnn-f"><span>{{ t('contentChanges.form.value', 'The value (JSON)') }}</span>
        <input v-model="d.valueJson" class="cnn-in mono" spellcheck="false" data-testid="cnn-value" :aria-invalid="touched && has('value') ? 'true' : 'false'" /></label>
      <label v-else-if="d.kind === 'compliance_pack'" class="cnn-f"><span>{{ t('contentChanges.form.rules', 'The rules (JSON: data_residency, retention, approval_thresholds, reporting)') }}</span>
        <textarea v-model="d.rulesJson" class="cnn-in mono" rows="8" spellcheck="false" data-testid="cnn-rules" :aria-invalid="touched && has('rules') ? 'true' : 'false'" /></label>
      <label v-else-if="d.kind === 'console_text'" class="cnn-f"><span>{{ t('contentChanges.form.text', 'The text (up to 600 characters)') }}</span>
        <textarea v-model="d.text" class="cnn-in" rows="4" maxlength="600" data-testid="cnn-text" :aria-invalid="touched && has('text') ? 'true' : 'false'" /></label>
      <template v-else>
        <label class="cnn-f"><span>{{ t('contentChanges.form.tagline', 'Tagline') }}</span><input v-model="d.tagline" class="cnn-in" maxlength="200" data-testid="cnn-tagline" /></label>
        <label class="cnn-f"><span>{{ t('contentChanges.form.accent', 'Accent colour (#rrggbb)') }}</span><input v-model.trim="d.accent" class="cnn-in mono" maxlength="7" data-testid="cnn-accent" /></label>
        <label class="cnn-f"><span>{{ t('contentChanges.form.logo', 'Logo address (https)') }}</span><input v-model.trim="d.logo" class="cnn-in mono" maxlength="500" data-testid="cnn-logo" /></label>
        <p v-if="touched && has('branding')" class="cnn-problem" role="alert">{{ sentenceOf('branding') }}</p>
      </template>

      <label class="cnn-f"><span>{{ t('contentChanges.form.titleLabel', 'Title') }}</span>
        <input v-model="d.title" class="cnn-in" maxlength="160" data-testid="cnn-title" :aria-invalid="touched && has('title') ? 'true' : 'false'" /></label>
      <label class="cnn-f"><span>{{ t('contentChanges.form.why', 'Why') }}</span>
        <textarea v-model="d.problem" class="cnn-in" rows="4" maxlength="6000" data-testid="cnn-problem" :aria-invalid="touched && has('problem') ? 'true' : 'false'" /></label>

      <ul v-if="touched && problems.length" class="cnn-problems" role="alert" data-testid="cnn-problems"><li v-for="p in problems" :key="p.field + p.sentence">{{ p.sentence }}</li></ul>
      <div v-if="refusal" class="cnn-refusal" role="alert" data-testid="cnn-refusal"><p>{{ refusal }}</p><ul v-if="reasons.length"><li v-for="r in reasons" :key="r">{{ r }}</li></ul></div>
      <div class="cnn-actions">
        <button type="submit" class="cnn-btn primary" :disabled="busy || !canPropose" data-testid="cnn-submit">{{ busy ? t('codeChanges.new.sending', 'Proposing…') : t('codeChanges.propose.submit', 'Propose') }}</button>
      </div>
    </form>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GovernedElsewhere from '@/components/codeChanges/GovernedElsewhere.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { refusalWords } from '@/services/api/codeChanges'
import { CONTENT_KINDS, checkerReasons, proposeContentChange } from '@/services/api/contentChanges'
import { authorityView, useCodeAuthority } from '@/services/codeChanges/authority'
import { useTr } from '@/services/codeChanges/tr'
import { contentProblems, emptyDraft, isKind, kindWord, proposalOf, targetLabel } from '@/services/contentChanges/words'

const { t } = useI18n()
const tr = useTr()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore() as any
const { authority } = useCodeAuthority()
const authorityView_ = computed(() => authorityView(authority.value))

const q = (k: string) => String(route.query[k] ?? '')
const d = reactive(emptyDraft(q('line'), q('title')))
if (isKind(q('kind'))) d.kind = q('kind') as any

const touched = ref(false)
const busy = ref(false)
const refusal = ref('')
const reasons = ref<string[]>([])
const canPropose = computed(() => !!auth.isAuthenticated && !!auth.activeAgent?.did)
const problems = computed(() => contentProblems(d, tr))
const has = (field: string) => problems.value.some((p) => p.field === field)
const sentenceOf = (field: string) => problems.value.find((p) => p.field === field)?.sentence || ''

async function submit() {
  touched.value = true; refusal.value = ''; reasons.value = []
  const body = proposalOf(d)
  if (!body) return
  busy.value = true
  try {
    await proposeContentChange(q('room') ? { ...body, room_id: q('room') } : body)
    await router.push({ name: 'contributions', query: { line: body.code_distribution } })
  } catch (e) {
    refusal.value = refusalWords(e, t('codeChanges.failed', 'The registry did not take it.'))
    reasons.value = checkerReasons(e).filter((r) => !refusal.value.includes(r))
  } finally { busy.value = false }
}
</script>

<style scoped>
.cnn { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace; max-width: 46rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.cnn-back { color: var(--cyan); font-size: .84rem; text-decoration: none; }
.cnn-hero { display: grid; gap: .6rem; justify-items: start; }
.cnn-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.cnn-hero h1 { margin: 0; font-size: 1.7rem; font-weight: 300; }
.cnn-lede { margin: 0; color: var(--muted); font-size: .9rem; line-height: 1.6; }
.cnn-warn { margin: 0; font-size: .84rem; color: #fcd34d; }
.cnn-card { display: grid; gap: .85rem; background: rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.2rem; }
.cnn-f { display: grid; gap: .3rem; font-size: .82rem; min-width: 0; }
.cnn-f > span { font: 700 10px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.cnn-in { min-height: 40px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .25); background: rgba(0, 0, 0, .3); color: var(--bright); font: inherit; font-size: .86rem; padding: .5rem .7rem; min-width: 0; width: 100%; box-sizing: border-box; }
.cnn-in.mono { font-family: var(--mono); font-size: .8rem; }
.cnn-in[aria-invalid='true'] { border-color: rgba(248, 113, 113, .7); }
.cnn-problem, .cnn-problems { margin: 0; font-size: .8rem; color: #fca5a5; }
.cnn-problems { padding-left: 1.1rem; }
.cnn-refusal { border: 1px solid rgba(248, 113, 113, .35); border-radius: 10px; padding: .7rem .9rem; color: #fca5a5; font-size: .84rem; display: grid; gap: .3rem; overflow-wrap: anywhere; }
.cnn-refusal p { margin: 0; }
.cnn-refusal ul { margin: 0; padding-left: 1.1rem; }
.cnn-actions { display: flex; gap: .5rem; }
.cnn-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .1); color: var(--cyan); font: inherit; font-size: .84rem; cursor: pointer; }
.cnn-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.cnn-btn:disabled { opacity: .5; cursor: not-allowed; }
.cnn-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
</style>
