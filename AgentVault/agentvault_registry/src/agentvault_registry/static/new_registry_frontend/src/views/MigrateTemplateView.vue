<!--
  V0664 M5 (order gwo_5a4ea8476b97147f3056405e) — one migration template's page. Public, no sign-in. From and to, its steps, the
  connectors it needs, the fields it maps (the mapping itself when it is free or bought), its price, forks, uses and certified runs,
  and "Try it free": three commands, a dry run on the template's own sample data (no account, no system), then against their own system
  read-only. Buy and fork act AS the header's acting agent (the Guild's rule). A paid template's files are not shown until it is
  bought: the page asks the kit route, which answers 402 to anyone else. The README is rendered through the sanitizing renderer.
-->
<template>
  <div class="mgt" data-testid="mgt-root">
    <MigrateTabs current="migrate" />
    <RouterLink :to="{ name: 'migrate' }" class="mgt-back" data-testid="mgt-back">{{ t('migrate.back', 'All templates') }}</RouterLink>

    <p v-if="error" class="mgt-error" role="alert" data-testid="mgt-error">{{ error }}</p>
    <p v-else-if="loading" class="mgt-note" data-testid="mgt-loading">{{ t('migrate.loadingOne', 'Reading the template') }}</p>

    <template v-if="detail">
      <header class="mgt-head">
        <h1 data-testid="mgt-title">{{ detail.listing.title }}</h1>
        <p class="mgt-route" data-testid="mgt-route">{{ kindWords(detail.listing.from_kind) }} <Icon name="mdi:arrow-right" /> {{ kindWords(detail.listing.to_kind) }}</p>
        <p v-if="detail.listing.summary" class="mgt-sum">{{ detail.listing.summary }}</p>
        <p class="mgt-facts">
          <span class="mgt-price" :class="{ free: isFree }" data-testid="mgt-price">{{ isFree ? t('migrate.free', 'Free') : priceWords(detail.listing) }}</span>
          <span v-if="detail.listing.current_version">{{ tp('migrate.version', 'version {n}', { n: detail.listing.current_version }) }}</span>
          <span data-testid="mgt-uses">{{ tp('migrate.uses', '{n} downloads', { n: detail.listing.uses }) }}</span>
          <span data-testid="mgt-usedby">{{ tp('migrate.usedBy', 'used by {n} developers', { n: detail.listing.used_by }) }}</span>
          <span data-testid="mgt-certified">{{ tp('migrate.certified', 'certified by {n} developers', { n: detail.listing.certified }) }}</span>
          <span data-testid="mgt-forks">{{ tp('migrate.forks', '{n} forks', { n: detail.listing.forks }) }}</span>
          <span v-if="hash" class="mgt-hash" :title="hashFull" data-testid="mgt-hash">{{ hash }}</span>
        </p>
        <p v-if="detail.listing.forked_from_template_id" class="mgt-fine" data-testid="mgt-parent">
          {{ t('migrate.forkOf', 'A fork of') }}
          <RouterLink :to="{ name: 'migrate-template', params: { id: detail.listing.forked_from_template_id } }">{{ detail.listing.forked_from_template_id }}</RouterLink>.
          {{ tp('migrate.forkShare', 'Each sale pays the parent\'s author {pct} percent; the platform takes nothing.', { pct: detail.listing.fork_share_bps / 100 }) }}
        </p>
      </header>

      <p v-if="toast" class="mgt-toast" role="status" data-testid="mgt-toast">{{ toast }}</p>

      <section class="mgt-panel" data-testid="mgt-try">
        <h2>{{ t('migrate.tryTitle', 'Try it free') }}</h2>
        <p class="mgt-fine">{{ t('migrate.tryBody', 'No account and no system needed for the first three: the dry run uses the template\'s own sample data and writes nothing anywhere but a scratch folder. The fourth reads your own system, read-only; a secret is always an environment variable, never typed here.') }}</p>
        <div v-for="(c, i) in commands" :key="i" class="mgt-cmd">
          <pre class="mgt-code" :data-testid="'mgt-cmd-' + i" tabindex="0" role="region" :aria-label="tp('migrate.cmdAria', 'Command {n}', { n: i + 1 })">{{ c }}</pre>
          <button type="button" class="mgt-btn small" :data-testid="'mgt-copy-' + i" @click="copy(c, i)">{{ copied === i ? t('migrate.copied', 'Copied') : t('migrate.copy', 'Copy') }}</button>
        </div>
      </section>

      <section class="mgt-panel" data-testid="mgt-structure">
        <h2>{{ t('migrate.structureTitle', 'What it does') }}</h2>
        <h3>{{ t('migrate.connectors', 'Connectors it needs') }}</h3>
        <p class="mgt-fine" data-testid="mgt-connectors">
          {{ t('migrate.reads', 'Reads') }}: {{ detail.structure.connector_kinds.from.map(kindWords).join(', ') || '-' }}.
          {{ t('migrate.writes', 'Writes') }}: {{ detail.structure.connector_kinds.to.map(kindWords).join(', ') || '-' }}.
        </p>
        <h3 v-if="fieldNames.length">{{ t('migrate.fields', 'Fields it maps') }}</h3>
        <ul v-if="fieldNames.length" class="mgt-list" data-testid="mgt-fields">
          <li v-for="n in fieldNames" :key="n">{{ n }}: {{ tp('migrate.fieldCount', '{n} fields', { n: detail.structure.field_counts[n] }) }}</li>
        </ul>
        <h3 v-if="detail.structure.parameter_names.length">{{ t('migrate.parameters', 'Parameters you fill') }}</h3>
        <ul v-if="detail.structure.parameter_names.length" class="mgt-list" data-testid="mgt-params">
          <li v-for="p in detail.structure.parameter_names" :key="p">{{ p }}<span v-if="detail.structure.secret_parameters.includes(p)" class="mgt-fine"> ({{ t('migrate.secretParam', 'a secret: only ever an environment variable') }})</span></li>
        </ul>
        <h3 v-if="detail.structure.steps.length">{{ t('migrate.stepsTitle', 'As a workflow') }}</h3>
        <ol v-if="detail.structure.steps.length" class="mgt-list" data-testid="mgt-steps">
          <li v-for="s in detail.structure.steps" :key="s.key"><strong>{{ s.key }}</strong> ({{ s.role }}){{ s.acceptance ? ': ' + s.acceptance : '' }}</li>
        </ol>
      </section>

      <section class="mgt-panel" data-testid="mgt-mapping">
        <h2>{{ t('migrate.mappingTitle', 'The mapping') }}</h2>
        <p v-if="noVersion" class="mgt-fine" data-testid="mgt-noversion">{{ t('migrate.noVersion', 'This template has no published version yet, so there are no files to show.') }}</p>
        <p v-else-if="locked" class="mgt-fine" data-testid="mgt-locked">{{ t('migrate.locked', 'The mapping and the README of a paid template are shown once you have bought it.') }}</p>
        <template v-else-if="kit">
          <div v-if="readme" class="mgt-readme" data-testid="mgt-readme" v-html="readme"></div>
          <pre v-if="kit.files['proxy.yaml']" class="mgt-code" data-testid="mgt-spec" tabindex="0" role="region" :aria-label="t('migrate.specAria', 'The mapping: proxy.yaml')">{{ kit.files['proxy.yaml'] }}</pre>
        </template>
        <p v-else class="mgt-fine">{{ t('migrate.mappingLoading', 'Reading the files') }}</p>
      </section>

      <section class="mgt-panel" data-testid="mgt-actions">
        <h2>{{ t('migrate.actionsTitle', 'Use it') }}</h2>
        <p v-if="!signedIn" class="mgt-fine" data-testid="mgt-signin">{{ isFree ? t('migrate.signInFork', 'Sign in and pick an agent (top right) to fork it. Trying it needs neither.') : t('migrate.signInBuy', 'Sign in to buy. Pick an agent (top right) after; a purchase belongs to the agent that makes it. Trying it needs neither.') }}</p>
        <p v-else-if="!hasAgent" class="mgt-fine" data-testid="mgt-pick">{{ t('migrate.pickAgent', 'Pick an agent (top right): a purchase and a fork belong to the agent that makes them.') }}</p>
        <div v-else class="mgt-row">
          <template v-if="!isFree && !owns && locked">
            <button v-if="confirming !== 'buy'" type="button" class="mgt-btn primary" data-testid="mgt-buy" @click="confirming = 'buy'">{{ tp('migrate.buy', 'Buy for {price}', { price: priceWords(detail.listing) }) }}</button>
            <span v-else class="mgt-confirm" data-testid="mgt-buy-confirm">
              {{ tp('migrate.buyConfirm', 'Your agent pays {price} to the template\'s author. The platform takes nothing.', { price: priceWords(detail.listing) }) }}
              <button type="button" class="mgt-btn primary small" :disabled="busy" data-testid="mgt-buy-go" @click="buy">{{ t('migrate.confirm', 'Confirm') }}</button>
              <button type="button" class="mgt-btn small" data-testid="mgt-buy-cancel" @click="confirming = ''">{{ t('migrate.cancel', 'Cancel') }}</button>
            </span>
          </template>
          <button v-if="canFork" type="button" class="mgt-btn" :disabled="busy" data-testid="mgt-fork" @click="fork">{{ t('migrate.fork', 'Fork it') }}</button>
          <span v-if="detail.structure.steps.length && canFork" class="mgt-budget">
            <label>{{ t('migrate.budget', 'Budget for the whole workflow') }}
              <input v-model="budget" type="number" min="0" step="any" inputmode="decimal" data-testid="mgt-budget" />
            </label>
            <button type="button" class="mgt-btn" :disabled="busy || !(budgetNum > 0)" data-testid="mgt-instantiate" @click="startWorkflow">{{ t('migrate.instantiate', 'Run it as a workflow') }}</button>
          </span>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { copyText } from '@/services/chat/codeCopy'
import { forkTemplate, getTemplate, getVersion, instantiateTemplate, purchaseTemplate, type KitFiles } from '@/services/api/workflowTemplates'
import { kindWords, priceWords, readmeHtml, tryItFree, type TemplateDetail } from '@/services/migrate/templates'

const { t, tp } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const signedIn = computed(() => !!(auth as any).token)
const hasAgent = computed(() => !!(auth as any).agentToken && !!(auth as any).activeAgent)

const detail = ref<TemplateDetail | null>(null)
const kit = ref<KitFiles | null>(null)
const locked = ref(false)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const toast = ref('')
const confirming = ref('')
const copied = ref(-1)

const id = computed(() => String(route.params.id || ''))
const isFree = computed(() => detail.value?.listing.pricing_model === 'free')
// who may use the files: anyone for a free template, the owner, a buyer. The answer of the library does not say which; the version
// route does (the files come, or a 402), so a paid template is readable exactly when its files were.
const owns = computed(() => !!detail.value && !!(auth as any).activeAgent?.did && (auth as any).activeAgent.did === detail.value.listing.owner_agent_did)
const canFork = computed(() => !!detail.value && (isFree.value || owns.value || !!kit.value))
const noVersion = ref(false)
const budget = ref('')
const budgetNum = computed(() => Number(budget.value))
const fieldNames = computed(() => Object.keys(detail.value?.structure.field_counts || {}))
const readme = computed(() => (kit.value?.files['README.md'] ? readmeHtml(kit.value.files['README.md']) : ''))
const hashFull = computed(() => detail.value?.versions.find((v) => v.version === detail.value?.listing.current_version)?.content_hash || '')
const hash = computed(() => (hashFull.value ? hashFull.value.slice(0, 12) : ''))
const commands = computed(() => tryItFree({
  ref: detail.value?.listing.id || id.value,
  registry: typeof window !== 'undefined' ? window.location.origin : '',
  parameters: detail.value?.structure.parameter_names || [],
}))

function why(e: any): string {
  const d = e?.response?.data
  // the library's own sentence for every refusal ({code, detail}); a declined purchase is the one worth saying in our words
  if (d?.code === 'payment_declined') return t('migrate.err402', 'The agent\'s balance does not cover this. Nothing was charged.')
  return (typeof d?.detail === 'string' && d.detail) || e?.message || t('migrate.failed', 'The request failed.')
}

async function loadKit() {
  kit.value = null; locked.value = false; noVersion.value = false
  const d = detail.value
  if (!d) return
  if (!d.listing.current_version) { noVersion.value = true; return }
  try { kit.value = await getVersion(d.listing.id || id.value, d.listing.current_version) }
  catch (e: any) { if (e?.response?.status === 402) locked.value = true; else error.value = why(e) }
}

async function load() {
  loading.value = true; error.value = ''
  try { detail.value = await getTemplate(id.value); await loadKit() }
  catch (e) { error.value = why(e); detail.value = null }
  finally { loading.value = false }
}

async function copy(text: string, i: number) {
  if (await copyText(text)) { copied.value = i; setTimeout(() => { if (copied.value === i) copied.value = -1 }, 1500) }
}

async function buy() {
  busy.value = true; toast.value = ''
  try { await purchaseTemplate(id.value); confirming.value = ''; toast.value = t('migrate.bought', 'Bought. The mapping is shown below.'); await load() }
  catch (e) { error.value = why(e) }
  finally { busy.value = false }
}

async function fork() {
  busy.value = true; toast.value = ''
  try { const f = await forkTemplate(id.value); toast.value = t('migrate.forked', 'Forked. It is yours to change and publish.'); if (f.id) await router.push({ name: 'migrate-template', params: { id: f.id } }) }
  catch (e) { error.value = why(e) }
  finally { busy.value = false }
}

async function startWorkflow() {
  busy.value = true; toast.value = ''
  try { await instantiateTemplate(id.value, { total_budget: budgetNum.value }); await router.push({ name: 'workflows' }) }
  catch (e) { error.value = why(e) }
  finally { busy.value = false }
}

onMounted(load)
watch(id, load)
</script>

<style scoped>
.mgt { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: #e8eaed; display: grid; gap: 1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mgt > * { min-width: 0; }
.mgt-back { justify-self: start; font: 600 .74rem var(--mono); color: var(--cyan); text-decoration: none; }
.mgt-back:hover, .mgt-back:focus-visible { text-decoration: underline; }
.mgt-error { margin: 0; color: #fca5a5; font-size: 0.85rem; }
.mgt-note, .mgt-fine { font-size: 0.82rem; color: var(--muted); margin: 0; line-height: 1.5; }
.mgt-head { display: grid; gap: .4rem; }
.mgt-head h1 { margin: 0; font-size: 1.8rem; font-weight: 300; letter-spacing: -.01em; overflow-wrap: anywhere; }
.mgt-route { margin: 0; font: 600 .78rem var(--mono); color: var(--muted); display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
.mgt-route :deep(svg) { width: 0.95rem; height: 0.95rem; color: var(--cyan); }
.mgt-sum { margin: 0; font-size: 0.92rem; color: #aab4c0; line-height: 1.55; max-width: 46rem; }
.mgt-facts { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem 1rem; font-size: 0.78rem; color: var(--muted); margin: .3rem 0 0; }
.mgt-price { font: 700 .82rem var(--mono); color: #fbbf24; }
.mgt-price.free { color: #34d399; }
.mgt-hash { font-family: var(--mono); font-size: .72rem; }
.mgt-toast { margin: 0; background: rgba(52,211,153,.1); border: 1px solid rgba(52,211,153,.4); border-radius: 8px; padding: 0.55rem 0.8rem; font-size: 0.84rem; }
.mgt-panel { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.25rem; display: grid; gap: 0.6rem; min-width: 0; }
.mgt-panel h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.mgt-panel h3 { margin: 0.4rem 0 0; font: 700 11px/1.2 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.mgt-cmd { display: flex; gap: 0.5rem; align-items: stretch; min-width: 0; }
.mgt-code { margin: 0; flex: 1; min-width: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: 0.6rem 0.8rem; font: 0.78rem/1.6 var(--mono); overflow-x: auto; white-space: pre; }
.mgt-code:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.mgt-list { margin: 0; padding-left: 1.1rem; font-size: 0.84rem; display: grid; gap: 0.25rem; overflow-wrap: anywhere; }
.mgt-readme { font-size: 0.88rem; line-height: 1.6; overflow-wrap: anywhere; }
/* a README is a section of this card, not a page: its headings are card-scale, its code scrolls sideways instead of wrapping */
.mgt-readme :deep(h1), .mgt-readme :deep(h2), .mgt-readme :deep(h3), .mgt-readme :deep(h4) { margin: 1rem 0 .4rem; font-weight: 500; line-height: 1.3; letter-spacing: 0; }
.mgt-readme :deep(h1) { font-size: 1.02rem; } .mgt-readme :deep(h2) { font-size: .95rem; }
.mgt-readme :deep(h3), .mgt-readme :deep(h4) { font: 700 11px/1.3 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.mgt-readme :deep(:first-child) { margin-top: 0; }
.mgt-readme :deep(p), .mgt-readme :deep(ul), .mgt-readme :deep(ol) { margin: .4rem 0; }
.mgt-readme :deep(pre) { margin: .6rem 0; max-width: 100%; overflow-x: auto; white-space: pre; word-break: normal; overflow-wrap: normal; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: .65rem .8rem; font: .78rem/1.6 var(--mono); }
.mgt-readme :deep(code) { font-family: var(--mono); font-size: .8em; overflow-wrap: anywhere; }
.mgt-readme :deep(pre code) { overflow-wrap: normal; font-size: inherit; }
.mgt-readme :deep(table) { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; font-size: .8rem; }
.mgt-readme :deep(th), .mgt-readme :deep(td) { border: 1px solid rgba(255,255,255,.1); padding: .3rem .5rem; }
.mgt-row { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; }
.mgt-budget { display: inline-flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; font-size: 0.8rem; }
.mgt-budget label { display: grid; gap: 0.3rem; font: 600 .74rem var(--mono); color: #cbd5e1; }
.mgt-budget input { width: 9rem; height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; color: inherit; padding: 0 .7rem; font: inherit; font-size: .85rem; }
.mgt-budget input:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.mgt-confirm { display: inline-flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; font-size: 0.82rem; }
.mgt-btn { min-height: 38px; background: rgba(var(--cyan-rgb), .12); border: 1px solid rgba(var(--cyan-rgb), .35); border-radius: 8px; padding: 0 1rem; color: var(--cyan); cursor: pointer; font: inherit; font-size: 0.84rem; }
.mgt-btn.primary { background: var(--cyan); color: #04141a; border-color: transparent; font-weight: 600; }
.mgt-btn.small { min-height: 32px; padding: 0 .75rem; font-size: 0.76rem; }
.mgt-btn:disabled { opacity: 0.45; cursor: default; }
.mgt-btn:active:not(:disabled) { transform: translateY(1px); }
@media (max-width: 640px) { .mgt { padding: 1rem .8rem 2.5rem; } .mgt-head h1 { font-size: 1.5rem; } .mgt-cmd { flex-wrap: wrap; } .mgt-cmd .mgt-btn { width: 100%; } }
</style>
