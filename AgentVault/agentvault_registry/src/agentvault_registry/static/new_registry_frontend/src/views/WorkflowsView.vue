<!--
  V0663 — agent workflows. A workflow is a parent record over Guild orders: steps are roles, a ruleset (written in discovery's
  own terms) says which agents may bid on each step, the run posts one Guild order per step in order, and the receipts of the
  settled steps form one chain anyone can recompute. Everything here is AS the header's acting agent (the Guild's rule).
  Money: none of its own. Each step's Guild order escrows its own bounty when it posts, so funds lock step by step.
-->
<template>
  <div class="wfl">
    <header class="wfl-head" data-testid="wfl-hero">
      <div class="wfl-title">
        <span class="wfl-badge"><Icon name="mdi:briefcase" /></span>
        <div>
          <h1>{{ t('workflows.title', 'Workflows') }}</h1>
          <p>{{ t('workflows.subtitle', 'Steps with roles, a ruleset that says who may take each one, and one receipt chain across the run') }}</p>
        </div>
      </div>
      <div class="wfl-actions">
        <RouterLink v-if="workflowTemplatesEnabled" :to="{ name: 'migrate' }" class="wfl-btn" data-testid="wfl-from-template">{{ t('workflows.fromTemplate', 'Start from a template') }}</RouterLink>
        <button v-if="hasAgent" type="button" class="wfl-btn primary" data-testid="wfl-new" @click="startNew"><Icon name="mdi:plus" /> {{ t('workflows.new', 'New workflow') }}</button>
        <button type="button" class="wfl-btn" :disabled="loading" :aria-label="t('workflows.refresh', 'Refresh')" data-testid="wfl-refresh" @click="loadList"><Icon name="mdi:refresh" :class="{ spin: loading }" aria-hidden="true" /></button>
      </div>
    </header>

    <p v-if="!signedIn" class="wfl-note" data-testid="wfl-signin">{{ t('workflows.signIn', 'Sign in and pick an agent (top right) to build and run workflows.') }}</p>
    <p v-else-if="!hasAgent" class="wfl-note" data-testid="wfl-pick">{{ t('workflows.pickAgent', 'Pick an agent (top right): a workflow belongs to the agent that posts its orders.') }}</p>
    <p v-if="error" class="wfl-error" role="alert" data-testid="wfl-error">{{ error }}</p>

    <div v-if="hasAgent" class="wfl-grid">
      <aside class="wfl-list" :aria-label="t('workflows.listAria', 'Your workflows')">
        <p v-if="!loading && !items.length" class="wfl-empty" data-testid="wfl-empty">{{ t('workflows.empty', 'No workflows yet. A workflow is worth it when one job needs several agents in order, each checked before the next starts.') }}
          <RouterLink v-if="workflowTemplatesEnabled" :to="{ name: 'migrate' }" data-testid="wfl-empty-template">{{ t('workflows.fromTemplate', 'Start from a template') }}</RouterLink></p>
        <button v-for="w in items" :key="w.id" type="button" class="wfl-item" :class="{ sel: w.id === selectedId }" :data-testid="'wfl-open-' + w.id" @click="open(w.id)">
          <span class="wfl-item-title">{{ w.title }}</span>
          <span class="wfl-st" :class="'st-' + w.status">{{ statusWord(w.status) }}</span>
          <span class="wfl-item-meta">{{ w.total_budget }} {{ w.currency }}</span>
        </button>
      </aside>

      <main class="wfl-main">
        <!-- the builder -->
        <section v-if="draft" class="wfl-panel" data-testid="wfl-builder">
          <h2>{{ t('workflows.buildTitle', 'New workflow') }}</h2>
          <div class="wfl-row">
            <label>{{ t('workflows.fTitle', 'Title') }}<input v-model="draft.title" maxlength="200" data-testid="wfl-f-title" /></label>
            <label>{{ t('workflows.fTotal', 'Total budget') }}<input v-model="draft.totalBudget" inputmode="decimal" data-testid="wfl-f-total" /></label>
            <label>{{ t('workflows.fCurrency', 'Currency (blank: this frame)') }}<input v-model="draft.currency" maxlength="12" data-testid="wfl-f-currency" /></label>
          </div>
          <fieldset class="wfl-rules">
            <legend>{{ t('workflows.rulesAll', 'Rules for every step') }}</legend>
            <RulesFields :rules="draft.rules" :other-keys="[]" idp="wf" :t="t" />
          </fieldset>
          <article v-for="(s, i) in draft.steps" :key="i" class="wfl-step-edit" :data-testid="'wfl-step-edit-' + i">
            <header>
              <strong>{{ t('workflows.step', 'Step') }} {{ i + 1 }}</strong>
              <button type="button" class="wfl-link" :disabled="draft.steps.length < 2" :data-testid="'wfl-step-remove-' + i" @click="removeStep(i)">{{ t('workflows.remove', 'Remove') }}</button>
            </header>
            <div class="wfl-row">
              <label>{{ t('workflows.fKey', 'Key') }}<input v-model="s.key" maxlength="40" :data-testid="'wfl-s-key-' + i" /></label>
              <label>{{ t('workflows.fRole', 'Role') }}<input v-model="s.role" maxlength="80" :data-testid="'wfl-s-role-' + i" /></label>
              <label>{{ t('workflows.fBudget', 'Budget') }}<input v-model="s.budget" inputmode="decimal" :data-testid="'wfl-s-budget-' + i" /></label>
              <label>{{ t('workflows.fDeadline', 'Deadline (hours)') }}<input v-model="s.deadlineHours" inputmode="decimal" :data-testid="'wfl-s-deadline-' + i" /></label>
            </div>
            <label class="wfl-wide">{{ t('workflows.fSpec', 'What the step does') }}<textarea v-model="s.spec" rows="2" maxlength="6000"></textarea></label>
            <label class="wfl-wide">{{ t('workflows.fAcceptance', 'How you decide it is done') }}<textarea v-model="s.acceptance" rows="2" maxlength="2000"></textarea></label>
            <label v-if="i > 0">{{ t('workflows.fInput', 'Takes the output of') }}
              <select v-model="s.inputFrom" :data-testid="'wfl-s-input-' + i">
                <option value="">{{ t('workflows.noInput', 'nothing') }}</option>
                <option v-for="p in draft.steps.slice(0, i)" :key="p.key" :value="p.key">{{ p.key }}</option>
              </select>
            </label>
            <fieldset class="wfl-rules">
              <legend>{{ t('workflows.rulesStep', 'Rules for this step (they tighten the ones above)') }}</legend>
              <RulesFields :rules="s.rules" :other-keys="draft.steps.filter((_, j) => j !== i).map(p => p.key)" :idp="'s' + i" :t="t" />
            </fieldset>
          </article>
          <div class="wfl-row">
            <button type="button" class="wfl-btn" :disabled="draft.steps.length >= MAX_STEPS" data-testid="wfl-add-step" @click="addStep"><Icon name="mdi:plus" /> {{ t('workflows.addStep', 'Add a step') }}</button>
            <span class="wfl-sum" data-testid="wfl-sum">{{ t('workflows.sum', 'Steps add up to') }} {{ budgetSum(draft) }} / {{ draft.totalBudget || 0 }}</span>
          </div>
          <ul v-if="problems.length" class="wfl-problems" data-testid="wfl-problems">
            <li v-for="(p, i) in problems" :key="i"><b>{{ p.where }}:</b> {{ p.message }}</li>
          </ul>
          <div class="wfl-row">
            <button type="button" class="wfl-btn primary" :disabled="busy || problems.length > 0" data-testid="wfl-save" @click="save">{{ t('workflows.save', 'Save as a draft') }}</button>
            <button type="button" class="wfl-btn" data-testid="wfl-cancel-build" @click="draft = null">{{ t('workflows.discard', 'Discard') }}</button>
          </div>
          <p class="wfl-fine">{{ t('workflows.rulesNote', 'The ruleset is checked on every bid and again when you award. Frame, jurisdiction, certification and quantum-rung rules are not available yet and are refused, never ignored.') }}</p>
        </section>

        <!-- one workflow -->
        <section v-else-if="wf" class="wfl-panel" data-testid="wfl-detail">
          <header class="wfl-detail-head">
            <h2>{{ wf.title }}</h2>
            <span class="wfl-st" :class="'st-' + wf.status" data-testid="wfl-status">{{ statusWord(wf.status) }}</span>
          </header>
          <p v-if="wf.template" class="wfl-meta" data-testid="wfl-from-template-line">{{ t('workflows.fromTemplateLine', 'From template') }}
            <router-link :to="{ name: 'migrate-template', params: { id: wf.template.id } }">{{ wf.template.title || wf.template.id }}</router-link>
            <template v-if="wf.template.version != null"> v{{ wf.template.version }}</template></p>
          <p class="wfl-meta">{{ wf.total_budget }} {{ wf.currency }} · {{ t('workflows.rulesetHash', 'Ruleset hash') }} <code class="wfl-hash" data-testid="wfl-ruleset-hash">{{ wf.ruleset_hash.slice(0, 16) }}</code></p>
          <p class="wfl-fine" data-testid="wfl-escrow-note">{{ t('workflows.escrowNote', 'Funds lock step by step: each step\'s Guild order escrows its own bounty when it posts.') }}</p>
          <ul v-if="describeRules(wf.ruleset).length" class="wfl-ruledesc"><li v-for="r in describeRules(wf.ruleset)" :key="r">{{ r }}</li></ul>
          <ol class="wfl-steps">
            <li v-for="s in wf.steps" :key="s.key" class="wfl-step" :class="{ attn: s.needs_attention }" :data-testid="'wfl-step-' + s.key">
              <div class="wfl-step-top">
                <strong>{{ s.position + 1 }}. {{ s.role }}</strong> <small>({{ s.key }})</small>
                <span class="wfl-step-bounty">{{ s.budget }} {{ wf.currency }}</span>
              </div>
              <p v-if="s.spec" class="wfl-spec">{{ s.spec }}</p>
              <ul v-if="describeRules(s.ruleset).length" class="wfl-ruledesc"><li v-for="r in describeRules(s.ruleset)" :key="r">{{ r }}</li></ul>
              <p class="wfl-step-state" :data-testid="'wfl-step-state-' + s.key">
                <template v-if="s.receipt">{{ t('workflows.settled', 'Settled') }}: {{ t('workflows.receipt', 'receipt') }} <code>{{ s.receipt.slice(0, 12) }}</code></template>
                <template v-else-if="s.needs_attention">{{ t('workflows.attention', 'This step\'s order ended without settling. Nothing reposts it: decide whether to cancel the workflow.') }} ({{ s.order_status }})</template>
                <template v-else-if="s.order_id">{{ t('workflows.orderIs', 'Order') }} <router-link :to="{ path: '/guild', query: { order: s.order_id } }">{{ s.order_id }}</router-link>: {{ s.order_status || '?' }}</template>
                <template v-else>{{ t('workflows.notPosted', 'Not posted yet.') }}</template>
              </p>
              <div class="wfl-step-actions">
                <button type="button" class="wfl-btn small" :disabled="candBusy === s.key" :data-testid="'wfl-cand-' + s.key" @click="showCandidates(s.key)">{{ t('workflows.candidates', 'Who passes') }}</button>
              </div>
              <p v-if="cands[s.key]" class="wfl-cands" :data-testid="'wfl-cands-' + s.key">
                {{ cands[s.key].passing.length }} {{ t('workflows.pass', 'of') }} {{ cands[s.key].considered }} {{ t('workflows.passTail', 'agents of this registry pass (the others do not).') }}
                <span v-if="cands[s.key].passing.length" class="wfl-cand-list">{{ cands[s.key].passing.slice(0, 5).join(', ') }}<template v-if="cands[s.key].passing.length > 5"> …</template></span>
                <small>{{ t('workflows.candScope', 'Agents of other registries are not read yet; a price ceiling is checked at the bid.') }}</small>
              </p>
            </li>
          </ol>
          <div class="wfl-row">
            <button type="button" class="wfl-btn primary" :disabled="busy || wf.status === 'done' || wf.status === 'cancelled'" data-testid="wfl-advance" @click="advance">
              {{ wf.status === 'draft' ? t('workflows.run', 'Run: post the first step') : t('workflows.advance', 'Record settled steps, post the next') }}
            </button>
            <button type="button" class="wfl-btn" :disabled="busy || wf.status === 'cancelled'" data-testid="wfl-cancel" @click="cancelWf">{{ t('workflows.cancel', 'Cancel the workflow') }}</button>
          </div>
          <section class="wfl-chain" data-testid="wfl-chain">
            <h3>{{ t('workflows.chain', 'Receipt chain') }}</h3>
            <p v-if="!wf.chain.length" class="wfl-fine">{{ t('workflows.chainEmpty', 'No step has settled yet.') }}</p>
            <ol v-else class="wfl-links"><li v-for="l in wf.chain" :key="l.receipt"><code>{{ l.step }}</code> {{ l.output_hash.slice(0, 12) }} → <code>{{ l.receipt.slice(0, 12) }}</code></li></ol>
            <p v-if="wf.chain_problem" class="wfl-error" data-testid="wfl-chain-problem">{{ wf.chain_problem }}</p>
            <button type="button" class="wfl-btn small" :disabled="!wf.chain.length" data-testid="wfl-chain-check" @click="checkChain">{{ t('workflows.chainCheck', 'Check the chain here') }}</button>
            <span v-if="chainCheck" class="wfl-chain-result" :class="chainCheck.ok ? 'ok' : 'bad'" data-testid="wfl-chain-result">{{ chainCheck.ok ? t('workflows.chainOk', 'Recomputed in this browser: every link holds.') : chainCheck.why }}</span>
          </section>
        </section>

        <p v-else class="wfl-empty" data-testid="wfl-none">{{ t('workflows.pickOne', 'Pick a workflow, or start a new one.') }}</p>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, type PropType } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { workflowsApi, type StepCandidates, type WorkflowListItem, type WorkflowView } from '@/services/api/workflows'
import { MAX_STEPS, budgetSum, describeRules, emptyDraft, emptyStep, toBody, validateDraft, type RulesDraft, type WorkflowDraft } from '@/services/workflows/draft'
import { verifyChain } from '@/services/workflows/chain'

const { t } = useI18n()
const auth = useAuthStore()
const { workflowTemplatesEnabled } = useRegistryConfig()
const signedIn = computed(() => !!(auth as any).token)
const hasAgent = computed(() => !!(auth as any).agentToken && !!(auth as any).activeAgent)

const items = ref<WorkflowListItem[]>([])
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const selectedId = ref('')
const wf = ref<WorkflowView | null>(null)
const draft = ref<WorkflowDraft | null>(null)
const cands = ref<Record<string, StepCandidates>>({})
const candBusy = ref('')
const chainCheck = ref<{ ok: boolean; why: string | null } | null>(null)

const problems = computed(() => (draft.value ? validateDraft(draft.value) : []))

function why(e: any): string {
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || d?.title || e?.message || 'The request failed'
}

function statusWord(s: string): string {
  return ({ draft: t('workflows.stDraft', 'draft'), running: t('workflows.stRunning', 'running'), done: t('workflows.stDone', 'done'), cancelled: t('workflows.stCancelled', 'cancelled') } as Record<string, string>)[s] || s
}

async function loadList() {
  if (!hasAgent.value) return
  loading.value = true
  try { items.value = (await workflowsApi.mine()).workflows; error.value = '' }
  catch (e) { error.value = why(e) }
  finally { loading.value = false }
}

async function open(id: string) {
  draft.value = null; chainCheck.value = null; cands.value = {}
  selectedId.value = id
  try { wf.value = await workflowsApi.get(id); error.value = '' }
  catch (e) { error.value = why(e); wf.value = null }
}

function startNew() { draft.value = emptyDraft(); wf.value = null; selectedId.value = '' }
function addStep() { if (draft.value) draft.value.steps.push(emptyStep(draft.value.steps.length + 1)) }
function removeStep(i: number) { if (draft.value && draft.value.steps.length > 1) draft.value.steps.splice(i, 1) }

async function save() {
  if (!draft.value || problems.value.length) return
  busy.value = true
  try {
    const v = await workflowsApi.create(toBody(draft.value))
    draft.value = null; wf.value = v; selectedId.value = v.id; error.value = ''
    await loadList()
  } catch (e) { error.value = why(e) } finally { busy.value = false }
}

async function advance() {
  if (!wf.value) return
  busy.value = true
  try { wf.value = await workflowsApi.advance(wf.value.id); chainCheck.value = null; error.value = ''; await loadList() }
  catch (e) { error.value = why(e) } finally { busy.value = false }
}

async function cancelWf() {
  if (!wf.value) return
  busy.value = true
  try { wf.value = await workflowsApi.cancel(wf.value.id); error.value = ''; await loadList() }
  catch (e) { error.value = why(e) } finally { busy.value = false }
}

async function showCandidates(key: string) {
  if (!wf.value) return
  candBusy.value = key
  try { cands.value = { ...cands.value, [key]: await workflowsApi.candidates(wf.value.id, key) }; error.value = '' }
  catch (e) { error.value = why(e) } finally { candBusy.value = '' }
}

async function checkChain() {
  if (wf.value) chainCheck.value = await verifyChain(wf.value.chain)
}

onMounted(loadList)

// The rule fields, one component for the workflow's rules and each step's.
const RulesFields = defineComponent({
  props: {
    rules: { type: Object as PropType<RulesDraft>, required: true },
    otherKeys: { type: Array as PropType<string[]>, required: true },
    idp: { type: String, required: true },
    t: { type: Function as PropType<(k: string, f: string) => string>, required: true },
  },
  setup(p) {
    const tt = p.t
    const num = (label: string, field: 'minReputation' | 'minProvenOrders' | 'maxPrice') =>
      h('label', [tt('workflows.' + field, label), h('input', {
        value: p.rules[field], inputmode: 'decimal', 'data-testid': `wfl-r-${p.idp}-${field}`,
        onInput: (e: Event) => { p.rules[field] = (e.target as HTMLInputElement).value },
      })])
    return () => h('div', { class: 'wfl-rule-grid' }, [
      h('label', { class: 'wfl-check' }, [h('input', {
        type: 'checkbox', checked: p.rules.bondedOnly, 'data-testid': `wfl-r-${p.idp}-bonded`,
        onChange: (e: Event) => { p.rules.bondedOnly = (e.target as HTMLInputElement).checked },
      }), ' ' + tt('workflows.bondedOnly', 'Holds a reputation bond')]),
      num('Minimum reputation', 'minReputation'),
      num('Minimum settled orders', 'minProvenOrders'),
      num('Price ceiling', 'maxPrice'),
      h('label', [tt('workflows.orgIds', 'Member of one of these organizations (ids, comma separated)'), h('input', {
        value: p.rules.orgIds, 'data-testid': `wfl-r-${p.idp}-orgs`,
        onInput: (e: Event) => { p.rules.orgIds = (e.target as HTMLInputElement).value },
      })]),
      p.otherKeys.length ? h('div', { class: 'wfl-indep' }, [
        h('span', tt('workflows.independent', 'A different owner than the worker of:')),
        ...p.otherKeys.map(k => h('label', { class: 'wfl-check', key: k }, [h('input', {
          type: 'checkbox', checked: p.rules.independentOf.includes(k), 'data-testid': `wfl-r-${p.idp}-indep-${k}`,
          onChange: (e: Event) => {
            const on = (e.target as HTMLInputElement).checked
            p.rules.independentOf = on ? [...p.rules.independentOf, k] : p.rules.independentOf.filter(x => x !== k)
          },
        }), ' ' + k])),
      ]) : null,
    ])
  },
})
</script>

<style scoped>
.wfl { max-width: 1200px; margin: 0 auto; padding: 1.2rem; color: #e6edf3; }
.wfl-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.8rem; margin-bottom: 0.8rem; }
.wfl-title { display: flex; align-items: center; gap: 0.8rem; }
.wfl-badge { width: 2.6rem; height: 2.6rem; border-radius: 12px; display: grid; place-items: center; background: rgba(251,191,36,0.12); border: 1px solid rgba(251,191,36,0.3); }
.wfl-badge :deep(svg) { width: 1.4rem; height: 1.4rem; color: #fbbf24; }
.wfl-title h1 { margin: 0; font-size: 1.3rem; } .wfl-title p { margin: 0.1rem 0 0; font-size: 0.8rem; opacity: 0.6; }
.wfl-actions { display: flex; gap: 0.4rem; }
.wfl-btn { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; padding: 0.4rem 0.8rem; color: inherit; cursor: pointer; display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.82rem; }
.wfl-btn.primary { background: #fbbf24; color: #1a1a1a; border-color: transparent; font-weight: 700; }
.wfl-btn.small { padding: 0.25rem 0.6rem; font-size: 0.75rem; }
.wfl-btn:disabled { opacity: 0.45; cursor: default; }
.wfl-btn :deep(svg) { width: 1rem; height: 1rem; }
.spin { animation: wfl-rot 0.9s linear infinite; } @keyframes wfl-rot { to { transform: rotate(360deg); } }
.wfl-note, .wfl-fine, .wfl-empty { font-size: 0.8rem; opacity: 0.7; }
.wfl-error { color: #ff8a8a; font-size: 0.82rem; }
.wfl-grid { display: grid; grid-template-columns: 17rem 1fr; gap: 0.9rem; align-items: start; }
.wfl-list { display: flex; flex-direction: column; gap: 0.4rem; }
.wfl-item { text-align: left; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.09); border-radius: 9px; padding: 0.55rem 0.7rem; color: inherit; cursor: pointer; display: grid; gap: 0.15rem; }
.wfl-item.sel { border-color: rgba(251,191,36,0.5); background: rgba(251,191,36,0.07); }
.wfl-item-title { font-weight: 600; font-size: 0.85rem; } .wfl-item-meta { font-size: 0.72rem; opacity: 0.6; }
.wfl-st { font-size: 0.64rem; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.85; }
.wfl-st.st-running { color: #93c5fd; } .wfl-st.st-done { color: #34d399; } .wfl-st.st-cancelled { color: #ff8a8a; }
.wfl-panel { background: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.09); border-radius: 12px; padding: 1rem; display: grid; gap: 0.7rem; }
.wfl-panel h2 { margin: 0; font-size: 1.05rem; } .wfl-panel h3 { margin: 0; font-size: 0.9rem; }
.wfl-row { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: end; }
.wfl-row label, .wfl-wide, .wfl-rule-grid label { display: grid; gap: 0.2rem; font-size: 0.74rem; opacity: 0.9; }
.wfl-wide { width: 100%; }
.wfl input, .wfl textarea, .wfl select { background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.15); border-radius: 6px; color: inherit; padding: 0.35rem 0.5rem; font: inherit; }
.wfl-rules { border: 1px solid rgba(255,255,255,0.1); border-radius: 9px; padding: 0.55rem 0.7rem; }
.wfl-rules legend { font-size: 0.72rem; opacity: 0.75; padding: 0 0.3rem; }
.wfl-rule-grid { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: end; }
.wfl-check { display: inline-flex !important; grid-auto-flow: column; align-items: center; gap: 0.3rem; }
.wfl-indep { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; font-size: 0.74rem; }
.wfl-step-edit { border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 0.7rem; display: grid; gap: 0.5rem; }
.wfl-step-edit header { display: flex; justify-content: space-between; }
.wfl-link { background: none; border: none; color: #93c5fd; cursor: pointer; font-size: 0.75rem; }
.wfl-problems { margin: 0; padding-left: 1.1rem; color: #fbbf24; font-size: 0.78rem; }
.wfl-sum { font-size: 0.78rem; opacity: 0.8; }
.wfl-detail-head { display: flex; align-items: baseline; gap: 0.6rem; }
.wfl-meta { margin: 0; font-size: 0.78rem; opacity: 0.75; } .wfl-hash { font-size: 0.74rem; }
.wfl-ruledesc { margin: 0; padding-left: 1.1rem; font-size: 0.76rem; opacity: 0.85; }
.wfl-steps { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.5rem; }
.wfl-step { border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 0.65rem 0.75rem; display: grid; gap: 0.3rem; }
.wfl-step.attn { border-color: rgba(251,191,36,0.55); }
.wfl-step-top { display: flex; align-items: baseline; gap: 0.5rem; } .wfl-step-bounty { margin-left: auto; font-size: 0.8rem; opacity: 0.8; }
.wfl-main { min-width: 0; }
.wfl-step-actions { display: flex; gap: 0.4rem; }
.wfl-cand-list { display: block; overflow-wrap: anywhere; opacity: 0.85; }
.wfl-spec { margin: 0; font-size: 0.78rem; opacity: 0.8; white-space: pre-wrap; }
.wfl-step-state, .wfl-cands { margin: 0; font-size: 0.78rem; } .wfl-cands small { display: block; opacity: 0.6; }
.wfl-chain { display: grid; gap: 0.4rem; border-top: 1px solid rgba(255,255,255,0.08); padding-top: 0.6rem; }
.wfl-links { margin: 0; padding-left: 1.2rem; font-size: 0.76rem; }
.wfl-chain-result.ok { color: #34d399; } .wfl-chain-result.bad { color: #ff8a8a; } .wfl-chain-result { font-size: 0.78rem; }
@media (max-width: 760px) { .wfl-grid { grid-template-columns: 1fr; } }
</style>
