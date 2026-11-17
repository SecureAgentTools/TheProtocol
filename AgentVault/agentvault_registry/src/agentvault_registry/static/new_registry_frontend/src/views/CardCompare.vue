<!-- V0663 (order gwo_f8251964b96cb1759350b69d, his suggestion 9): two agent cards side by side, read-only, as served
     (#/cards/compare?a=<did>&b=<did>). "As exported" is each card as the world reads it (GET /agents/{did}/card-export,
     the agent's own slice); "as stored here" is this registry's whole copy (GET /agents/by-did/{did}, card_data, with
     the registry's own fields). The differences are marked path by path (services/cards/cardDiff). A card this registry
     does not hold says so, and names its home when the federated index knows it. -->
<template>
  <div class="cmp">
    <header class="cmp-head">
      <h1 class="cmp-title">{{ t('cardCompare.title', 'Compare two agent cards') }}</h1>
      <p class="cmp-lede">{{ t('cardCompare.lede', 'Two cards side by side, as served, with every difference marked. Read-only.') }}</p>
    </header>

    <form class="cmp-pick" data-testid="cmp-pick" @submit.prevent="pick">
      <label class="cmp-label">A <input v-model="inputA" class="cmp-input" maxlength="200" data-testid="cmp-input-a" :placeholder="t('cardCompare.didHint', 'An agent DID')" /></label>
      <label class="cmp-label">B <input v-model="inputB" class="cmp-input" maxlength="200" data-testid="cmp-input-b" :placeholder="t('cardCompare.didHint', 'An agent DID')" /></label>
      <button type="submit" class="cmp-btn">{{ t('cardCompare.compare', 'Compare') }}</button>
    </form>

    <div class="cmp-source" role="group" :aria-label="t('cardCompare.sourceLabel', 'Which copy of each card')">
      <button type="button" class="cmp-btn" :class="{ 'cmp-btn--on': source === 'export' }" data-testid="cmp-source-export" @click="source = 'export'">
        {{ t('cardCompare.asExported', 'As exported') }}
      </button>
      <button type="button" class="cmp-btn" :class="{ 'cmp-btn--on': source === 'stored' }" data-testid="cmp-source-stored" @click="source = 'stored'">
        {{ t('cardCompare.asStored', 'As stored here') }}
      </button>
    </div>

    <p v-if="!qa" class="cmp-note" data-testid="cmp-ask-a">{{ t('cardCompare.askA', 'Name card A.') }}</p>
    <p v-if="!qb" class="cmp-note" data-testid="cmp-ask-b">{{ t('cardCompare.askB', 'Name card B to compare it with.') }}</p>
    <template v-for="side in (['a', 'b'] as const)" :key="side">
      <p v-if="sides[side].missing" class="cmp-note" :data-testid="`cmp-missing-${side}`">
        {{ tp('cardCompare.notHeld', 'This registry does not hold card {side}.', { side: side.toUpperCase() }) }}
        <template v-if="sides[side].home">
          {{ t('cardCompare.itsHome', 'Its home:') }}
          <a :href="safeExternalUrl(sides[side].home!.publicUrl)" target="_blank" rel="noopener noreferrer" class="cmp-link">{{ sides[side].home!.name }}</a>
        </template>
      </p>
      <p v-else-if="sides[side].error" class="cmp-error" :data-testid="`cmp-error-${side}`">{{ sides[side].error }}</p>
    </template>

    <template v-if="rows">
      <p class="cmp-summary" data-testid="cmp-summary">
        {{ tp('cardCompare.summary', '{changed} changed, {onlyA} only in A, {onlyB} only in B, {same} the same', summary) }}
      </p>
      <label class="cmp-toggle"><input v-model="onlyDiff" type="checkbox" data-testid="cmp-only-diff" /> {{ t('cardCompare.onlyDiff', 'Differences only') }}</label>
      <table class="cmp-table">
        <thead><tr><th>{{ t('cardCompare.path', 'Path') }}</th><th>A</th><th>B</th></tr></thead>
        <tbody>
          <tr v-for="r in shownRows" :key="r.path" class="cmp-row" :data-status="r.status" :data-path="r.path" data-testid="cmp-diff-row">
            <td class="cmp-mono">{{ r.path || t('cardCompare.root', '(the whole card)') }}</td>
            <td class="cmp-mono cmp-val">{{ show(r.a) }}</td>
            <td class="cmp-mono cmp-val">{{ show(r.b) }}</td>
          </tr>
        </tbody>
      </table>
      <div class="cmp-panes">
        <pre v-for="side in (['a', 'b'] as const)" :key="side" class="cmp-pane" :data-testid="`cmp-pane-${side}`"><span
          v-for="(l, i) in lines[side]" :key="i" class="cmp-line" :data-mark="l.mark">{{ l.text }}
</span></pre>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { safeExternalUrl } from '@/utils/safeUrl'
import { cardLines, diffCards, diffSummary, type DiffRow } from '@/services/cards/cardDiff'

type Side = 'a' | 'b'
interface SideState { card: unknown; loaded: boolean; missing: boolean; error: string; home: { name: string; publicUrl: string } | null }

const { t, tp } = useI18n()
const route = useRoute()
const router = useRouter()

const qa = computed(() => (typeof route.query.a === 'string' ? route.query.a : ''))
const qb = computed(() => (typeof route.query.b === 'string' ? route.query.b : ''))
const inputA = ref(qa.value)
const inputB = ref(qb.value)
const source = ref<'export' | 'stored'>('export')
const onlyDiff = ref(true)
const blank = (): SideState => ({ card: null, loaded: false, missing: false, error: '', home: null })
const sides = reactive<Record<Side, SideState>>({ a: blank(), b: blank() })

const rows = computed<DiffRow[] | null>(() =>
  (sides.a.loaded && sides.b.loaded ? diffCards(sides.a.card, sides.b.card) : null))
const summary = computed(() => {
  const s = diffSummary(rows.value || [])
  return { changed: s.changed, onlyA: s.only_a, onlyB: s.only_b, same: s.same }
})
const shownRows = computed(() => (rows.value || []).filter((r) => !onlyDiff.value || r.status !== 'same'))
const lines = computed(() => ({
  a: rows.value ? cardLines(sides.a.card, rows.value, 'a') : [],
  b: rows.value ? cardLines(sides.b.card, rows.value, 'b') : [],
}))

function show(v: unknown): string {
  if (v === undefined) return t('cardCompare.absent', '(absent)')
  const s = JSON.stringify(v)
  return s.length > 160 ? `${s.slice(0, 157)}...` : s
}

async function homeOf(did: string): Promise<SideState['home']> {
  try {
    const { data } = await apiClient.post('/public/directory/graphql', {
      query: 'query($did: String!) { agent(did: $did) { home { name publicUrl } } }', variables: { did } })
    const home = data?.data?.agent?.home
    return home?.name && home?.publicUrl ? { name: String(home.name), publicUrl: String(home.publicUrl) } : null
  } catch {
    return null
  }
}

async function load(side: Side, did: string): Promise<void> {
  Object.assign(sides[side], blank())
  if (!did) return
  const enc = encodeURIComponent(did)
  try {
    if (source.value === 'export') {
      const { data } = await apiClient.get(`/agents/${enc}/card-export`)
      sides[side].card = data
    } else {
      const { data } = await apiClient.get(`/agents/by-did/${enc}`)
      sides[side].card = data?.card_data ?? null
    }
    sides[side].loaded = true
  } catch (e: any) {
    if (e?.response?.status === 404) {
      sides[side].missing = true
      sides[side].home = await homeOf(did)
    } else {
      sides[side].error = tp('cardCompare.readFailed', 'Card {side} could not be read; try again.', { side: side.toUpperCase() })
    }
  }
}

function reload(): void {
  void load('a', qa.value)
  void load('b', qb.value)
}

function pick(): void {
  const query: Record<string, string> = {}
  if (inputA.value.trim()) query.a = inputA.value.trim()
  if (inputB.value.trim()) query.b = inputB.value.trim()
  router.replace({ query })
}

onMounted(reload)
watch([qa, qb], ([a, b]) => { inputA.value = a; inputB.value = b; reload() })
watch(source, reload)
</script>

<style scoped>
.cmp { padding: 1.25rem; }
.cmp-head { margin-bottom: 0.8rem; }
.cmp-title { margin: 0; font-size: 1.25rem; font-weight: 500; }
.cmp-lede { margin: 0.3rem 0 0; font-size: 0.82rem; color: var(--nc-text-muted, #9aa0a6); }
.cmp-pick { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: flex-end; margin-bottom: 0.6rem; }
.cmp-label { display: flex; gap: 0.4rem; align-items: center; font-size: 0.78rem; flex: 1 1 18rem; }
.cmp-input { flex: 1 1 auto; font: inherit; font-size: 0.8rem; padding: 0.35rem 0.5rem; border-radius: 3px; color: var(--nc-text-primary, #e8eaed);
  background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18); }
.cmp-btn { padding: 4px 12px; border-radius: 3px; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.3); cursor: pointer;
  background: transparent; color: var(--nc-text-primary, #e8eaed); font-size: 0.78rem; }
.cmp-btn--on { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12); color: var(--nc-primary-bright, #00e5e5); }
.cmp-source { display: flex; gap: 0.4rem; margin-bottom: 0.8rem; }
.cmp-note { margin: 0.3rem 0; font-size: 0.8rem; color: var(--nc-text-muted, #9aa0a6); }
.cmp-error { margin: 0.3rem 0; font-size: 0.8rem; color: var(--nc-danger, #ef4444); }
.cmp-link { color: var(--nc-primary-bright, #00e5e5); text-decoration: underline; }
.cmp-summary { margin: 0.6rem 0 0.3rem; font-size: 0.84rem; }
.cmp-toggle { display: inline-flex; gap: 0.35rem; align-items: center; font-size: 0.78rem; margin-bottom: 0.5rem; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 0.74rem; margin-bottom: 1rem; table-layout: fixed; }
.cmp-table th { text-align: left; font-weight: 500; color: var(--nc-text-muted, #9aa0a6); padding: 0.3rem; }
.cmp-row td { padding: 0.3rem; border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08); vertical-align: top; }
.cmp-row[data-status='changed'] td:first-child { color: var(--nc-warning, #f59e0b); }
.cmp-row[data-status='only_a'] td:first-child, .cmp-row[data-status='only_b'] td:first-child { color: var(--nc-primary-bright, #00e5e5); }
.cmp-mono { font-family: ui-monospace, monospace; overflow-wrap: anywhere; }
.cmp-val { color: var(--nc-text-primary, #e8eaed); }
.cmp-panes { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0.8rem; }
.cmp-pane { margin: 0; padding: 0.6rem; overflow: auto; max-height: 70vh; font-size: 0.72rem; line-height: 1.45;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14); border-radius: 4px; background: rgba(0, 0, 0, 0.2); }
.cmp-line { white-space: pre; }
.cmp-line[data-mark='changed'] { background: rgba(245, 158, 11, 0.14); }
.cmp-line[data-mark='only'] { background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14); }
@media (max-width: 860px) { .cmp-panes { grid-template-columns: minmax(0, 1fr); } }
</style>
