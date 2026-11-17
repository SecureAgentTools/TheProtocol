<!-- V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7): the MCP tester's Coverage tab. Per tool, per target,
     from the latest run the tester holds for that target (GET /admin/mcp-tester/coverage): a success path, a refusal
     only, nothing measured (with the reason the run gives) or failed. The counts are per target and never summed. -->
<template>
  <div class="cov">
    <div class="cov-head">
      <p class="cov-lede">{{ t('mcpTester.coverage.lede', 'Per tool, per target, from the latest completed run the tester holds for each target. Counts are per target and never added up: the same tool can be refusal only on one target and reach its success path on another.') }}</p>
      <button type="button" class="cov-btn" :disabled="loading" data-testid="cov-refresh" @click="load">{{ t('mcpTester.coverage.refresh', 'Refresh') }}</button>
    </div>

    <p v-if="error" class="cov-error" role="alert" data-testid="cov-error">{{ t('mcpTester.coverage.readFailed', 'The coverage could not be read; try again.') }}</p>
    <template v-else-if="answer">
      <p v-if="answer.note" class="cov-note" data-testid="cov-note">{{ answer.note }}</p>

      <div class="cov-targets">
        <section v-for="tg in answer.targets" :key="tg.key" class="cov-target" data-testid="cov-target" :data-key="tg.key">
          <h3 class="cov-target-title">{{ tg.label }}</h3>
          <div class="cov-target-host">{{ tg.target }}</div>
          <div class="cov-target-run">{{ tp('mcpTester.coverage.run', 'run {id}, finished {at}', { id: short(tg.run_id), at: when(tg.finished_at) }) }}</div>
          <ul class="cov-counts">
            <li v-for="c in COUNT_ORDER" :key="c" class="cov-count" :data-class="c" :data-testid="`cov-count-${c}`">
              <span class="cov-count-n">{{ tg.counts[c] }}</span> <span class="cov-count-word">{{ classWord(c) }}</span>
            </li>
          </ul>
          <div class="cov-target-of">{{ tp('mcpTester.coverage.ofTools', 'of {n} tools this target lists', { n: tg.counts.tools }) }}</div>
          <p v-if="tg.newer" class="cov-target-newer" data-testid="cov-newer">
            {{ tp('mcpTester.coverage.newer', 'A newer run {id} is {status}; this reads the last completed one.', { id: short(tg.newer.run_id), status: tg.newer.status }) }}
          </p>
          <p v-if="tg.rows_expired" class="cov-target-newer">
            {{ tp('mcpTester.coverage.rowsExpired', 'The rows of run {id} expired; this reads the run before it.', { id: short(tg.rows_expired) }) }}
          </p>
        </section>
      </div>

      <div v-if="answer.tools.length" class="cov-filters">
        <div class="cov-chips" role="group" :aria-label="t('mcpTester.coverage.showLabel', 'Show')">
          <button v-for="s in SHOWS" :key="s" type="button" class="cov-chip" :class="{ 'cov-chip--on': show === s }"
            :aria-pressed="show === s" :data-testid="`cov-show-${s}`" @click="show = s">{{ showWord(s) }}</button>
        </div>
        <select v-model="tier" class="cov-select" data-testid="cov-tier" :aria-label="t('mcpTester.coverage.tierLabel', 'Tier')">
          <option value="">{{ t('mcpTester.coverage.anyTier', 'Any tier') }}</option>
          <option v-for="tr in tiers" :key="tr" :value="tr">{{ tr }}</option>
        </select>
        <input v-model="query" type="search" class="cov-search" data-testid="cov-search"
          :placeholder="t('mcpTester.coverage.search', 'Search a tool')" :aria-label="t('mcpTester.coverage.search', 'Search a tool')" />
        <span class="cov-shown">{{ tp('mcpTester.coverage.shown', '{n} of {m} tools', { n: shown.length, m: answer.tools.length }) }}</span>
      </div>

      <div v-if="answer.tools.length" class="cov-table-wrap" tabindex="0" role="region" :aria-label="t('mcpTester.coverage.tableLabel', 'Coverage per tool')">
        <table class="cov-table">
          <thead>
            <tr>
              <th>{{ t('mcpTester.coverage.tool', 'Tool') }}</th>
              <th>{{ t('mcpTester.coverage.tier', 'Tier') }}</th>
              <th v-for="tg in answer.targets" :key="tg.key">{{ tg.target }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in shown" :key="row.tool" class="cov-row" data-testid="cov-row" :data-tool="row.tool">
              <td class="cov-tool">{{ row.tool }}</td>
              <td class="cov-tier">{{ row.tier }}</td>
              <td v-for="tg in answer.targets" :key="tg.key" class="cov-cell" data-testid="cov-cell"
                :data-class="cell(row, tg.key).class" :title="cell(row, tg.key).reason || ''">
                <template v-if="cell(row, tg.key).class === 'not_listed'">
                  <span class="cov-dash" :aria-label="t('mcpTester.coverage.notListed', 'not listed on this target')">—</span>
                </template>
                <template v-else>
                  <span class="cov-word" :data-class="cell(row, tg.key).class">{{ classWord(cell(row, tg.key).class) }}</span>
                  <span v-if="cell(row, tg.key).status != null" class="cov-status">{{ cell(row, tg.key).status }}</span>
                  <span v-if="cell(row, tg.key).reason" class="cov-reason">{{ cell(row, tg.key).reason }}</span>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { mcpTesterApi } from '@/services/api/mcpTester'
import { filterTools, type CoverageAnswer, type CoverageCell, type CoverageClass, type CoverageShow, type CoverageTool } from '@/services/mcpTester/coverage'

const { t, tp } = useI18n()

const COUNT_ORDER = ['success', 'refusal_only', 'not_measured', 'failed'] as const
const SHOWS: CoverageShow[] = ['gaps', 'failed', 'refusal_only', 'not_measured', 'success', 'all']

const answer = ref<CoverageAnswer | null>(null)
const error = ref(false)
const loading = ref(false)
const show = ref<CoverageShow>('gaps')
const tier = ref('')
const query = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = false
  try {
    answer.value = await mcpTesterApi.coverage()
  } catch {
    error.value = true
    answer.value = null
  } finally {
    loading.value = false
  }
}

const tiers = computed(() => [...new Set((answer.value?.tools || []).map((r) => r.tier).filter(Boolean))].sort())
const shown = computed(() => filterTools(answer.value?.tools || [], { show: show.value, tier: tier.value, query: query.value }))

function cell(row: CoverageTool, key: string): CoverageCell {
  return row.by_target?.[key] || { class: 'not_listed' }
}

function classWord(c: CoverageClass): string {
  switch (c) {
    case 'success': return t('mcpTester.coverage.success', 'success path')
    case 'refusal_only': return t('mcpTester.coverage.refusalOnly', 'refusal only')
    case 'not_measured': return t('mcpTester.coverage.notMeasured', 'not measured')
    case 'failed': return t('mcpTester.coverage.failed', 'failed')
    default: return t('mcpTester.coverage.notListed', 'not listed on this target')
  }
}

function showWord(s: CoverageShow): string {
  if (s === 'gaps') return t('mcpTester.coverage.showGaps', 'Gaps')
  if (s === 'all') return t('mcpTester.coverage.showAll', 'All')
  return classWord(s)
}

function short(id: string | null | undefined): string {
  return String(id || '').slice(0, 8)
}

function when(epoch: number | null | undefined): string {
  if (!epoch) return '?'
  return `${new Date(epoch * 1000).toISOString().slice(0, 16).replace('T', ' ')}Z`
}

onMounted(load)
</script>

<style scoped>
.cov { display: flex; flex-direction: column; gap: 0.8rem; }
.cov-head { display: flex; align-items: flex-start; gap: 0.8rem; flex-wrap: wrap; }
.cov-lede { margin: 0; flex: 1 1 32rem; font-size: 0.8rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-btn, .cov-chip { padding: 4px 11px; border-radius: 3px; cursor: pointer; font-size: 0.76rem; background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.28); color: var(--nc-text-primary, #e8eaed); }
.cov-btn:disabled { opacity: 0.5; cursor: default; }
.cov-chip--on { border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.75); background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08); }
.cov-error { color: var(--nc-danger, #ef4444); font-size: 0.82rem; }
.cov-note { font-size: 0.8rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-targets { display: grid; grid-template-columns: repeat(auto-fill, minmax(17rem, 1fr)); gap: 0.7rem; }
.cov-target { padding: 0.7rem 0.8rem; border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.14); border-radius: 4px; }
.cov-target-title { margin: 0; font-size: 0.86rem; font-weight: 500; color: var(--nc-text-primary, #e8eaed); }
.cov-target-host, .cov-target-run { font-family: ui-monospace, monospace; font-size: 0.7rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-counts { list-style: none; margin: 0.5rem 0 0.2rem; padding: 0; display: flex; flex-wrap: wrap; gap: 0.35rem 0.9rem; }
.cov-count { font-size: 0.76rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-count-n { font-variant-numeric: tabular-nums; font-size: 0.95rem; color: var(--nc-text-primary, #e8eaed); }
.cov-count-word { letter-spacing: 0.01em; }
.cov-count[data-class='failed'] .cov-count-n { color: var(--nc-danger, #ef4444); }
.cov-target-of { font-size: 0.7rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-target-newer { margin: 0.4rem 0 0; font-size: 0.72rem; color: var(--nc-warning, #f59e0b); }
.cov-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem; }
.cov-chips { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.cov-select, .cov-search { font-size: 0.76rem; padding: 4px 8px; border-radius: 3px; background: rgba(6, 8, 16, 0.5);
  color: var(--nc-text-primary, #e8eaed); border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2); }
.cov-search { flex: 0 1 14rem; }
.cov-shown { font-size: 0.72rem; color: var(--nc-text-muted, #9aa0a6); }
.cov-table-wrap { overflow-x: auto; }
.cov-table { width: 100%; border-collapse: collapse; font-size: 0.74rem; }
.cov-table th { text-align: left; font-weight: 500; color: var(--nc-text-muted, #9aa0a6); padding: 0.3rem 0.4rem; white-space: nowrap; }
.cov-row td { padding: 0.35rem 0.4rem; border-top: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.07); vertical-align: top; }
.cov-tool { font-family: ui-monospace, monospace; color: var(--nc-text-primary, #e8eaed); white-space: nowrap; }
.cov-tier { color: var(--nc-text-muted, #9aa0a6); }
.cov-cell { min-width: 12rem; max-width: 26rem; }
.cov-word { display: inline-block; padding: 0 5px; border-radius: 2px; border: 1px solid currentColor; font-size: 0.68rem; }
.cov-word[data-class='success'] { color: var(--nc-success-bright, #34d399); border-style: solid; }
.cov-word[data-class='refusal_only'] { color: var(--nc-warning, #f59e0b); border-style: dashed; }
.cov-word[data-class='not_measured'] { color: var(--nc-text-muted, #9aa0a6); border-style: dotted; }
.cov-word[data-class='failed'] { color: var(--nc-danger, #ef4444); border-width: 2px; }
.cov-status { margin-left: 0.35rem; font-variant-numeric: tabular-nums; color: var(--nc-text-muted, #9aa0a6); }
.cov-reason { display: block; margin-top: 0.15rem; color: var(--nc-text-muted, #9aa0a6); overflow-wrap: anywhere; }
.cov-dash { color: var(--nc-text-muted, #9aa0a6); }
</style>
