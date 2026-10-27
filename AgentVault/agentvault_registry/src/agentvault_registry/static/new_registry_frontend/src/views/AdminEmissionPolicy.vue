<script setup lang="ts">
// The Emission policy page (agentvault2-69, 2026-10-25; his words: "the event emission policy which needs hardening
// and a fe page to check the exact configuration from the fe. i really need it visualized"). One read, the effective
// configuration agentvault2-d6's W3 builds (services/api/emissionPolicy.ts): for every event type, what the registry's
// gate does with it, what the TEG's gate does, what the projection does, how many this frame's store holds, what the
// shadow mode counted, and what is wrong with it; then the same table as the other frames have it. A count that could
// not be read says so and is never drawn as 0. Reads only: the rows are edited on Ledger Forensics' Policy tab.
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { appLocale } from '@/services/appLocale'
import { emissionPolicyApi, type EffectivePolicy, type FindingCode, type MatrixRow } from '@/services/api/emissionPolicy'
import {
  FINDING_FALLBACK, FINDING_SEVERITY, barPercent, countText, findingCodes, matches, ordered, projectionCell,
  registryCell, severity, severityCounts, tegCell, type Cell, type EmitterFilter, type Severity,
} from '@/services/emissionPolicyView'

const { t, tp } = useI18n()
const view = ref<EffectivePolicy | null>(null)
const loading = ref(false)
const failed = ref(false)
const finding = ref<FindingCode | 'any' | 'balance'>('any')
const query = ref('')
const emitter = ref<EmitterFilter>('any')
const expanded = ref<string | null>(null)

const SEVERITIES: Severity[] = ['bad', 'warn', 'note', 'clean']

async function load() {
  loading.value = true
  try {
    view.value = await emissionPolicyApi.effective(true)
    failed.value = false
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
onMounted(load)

const num = (n: number) => new Intl.NumberFormat(appLocale()).format(n)
const count = (n: number | null | undefined) => (n === null || n === undefined ? t('emissionPolicy.notRead', 'not read') : countText(n, appLocale()))
const fmtTime = (iso?: string | null) => {
  if (!iso) return ''
  const d = new Date(iso)
  // a time the browser cannot read is shown as it came, never as "Invalid Date"
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(appLocale(), { dateStyle: 'medium', timeStyle: 'medium' })
}

const matrix = computed<MatrixRow[]>(() => view.value?.matrix || [])
const rows = computed(() => ordered(matrix.value.filter((r) => matches(r, { finding: finding.value, query: query.value, emitter: emitter.value }))))
const sev = computed(() => severityCounts(matrix.value))
const codes = computed(() => (view.value ? findingCodes(view.value) : []))
const balanceCount = computed(() => matrix.value.filter((r) => r.balance_moving).length)
const maxStore = computed(() => Math.max(0, ...matrix.value.map((r) => r.store_count ?? 0)))
const emittedBy = (side: 'registry' | 'teg') => matrix.value.filter((r) => r.emitted_by.includes(side)).length

const sevWord = (s: Severity) =>
  s === 'bad' ? t('emissionPolicy.sev.bad', 'an event lost or counted twice')
  : s === 'warn' ? t('emissionPolicy.sev.warn', 'a gap to close')
  : s === 'note' ? t('emissionPolicy.sev.note', 'a row nothing here emits')
  : t('emissionPolicy.sev.clean', 'nothing to say')
const healthLabel = computed(() => SEVERITIES.map((s) => `${sevWord(s)}: ${sev.value[s]}`).join(', '))

const modeWord = (m: string) =>
  m === 'enforce' ? t('emissionPolicy.mode.enforce', 'enforce: a type with no row is refused')
  : m === 'shadow' ? t('emissionPolicy.mode.shadow', 'shadow: a type with no row is allowed and counted')
  : m === 'off' ? t('emissionPolicy.mode.off', 'off: a type with no row is allowed')
  : m === 'fail-closed' ? t('emissionPolicy.mode.failClosed', 'fails closed: a type with no row is refused')
  : m
const cellWord = (c: Cell) => t(`emissionPolicy.cell.${c.key}`, c.word)
const findingText = (f: FindingCode) => view.value?.summary?.finding_text?.[f] || t(`emissionPolicy.finding.${f}`, FINDING_FALLBACK[f] || f)
const cacheNote = computed(() => {
  const pt = view.value?.modes.registry.policy_table
  if (!pt) return ''
  if (pt.this_worker_load_error) return tp('emissionPolicy.cacheError', 'this worker could not load them: {why}', { why: pt.this_worker_load_error })
  if (pt.this_worker_cached === null || pt.this_worker_cached === undefined) return ''
  return tp('emissionPolicy.cached', 'this worker holds {n}, loaded {at}', { n: num(pt.this_worker_cached), at: fmtTime(pt.this_worker_loaded_at) })
})
function toggle(et: string) { expanded.value = expanded.value === et ? null : et }
function flag(v: boolean | undefined) { return v ? t('emissionPolicy.yes', 'yes') : t('emissionPolicy.no', 'no') }
const peerTypeWord = (p?: string | null) =>
  p === 'frame' ? t('emissionPolicy.peer.frame', 'frame') : p === 'cloud_operator' ? t('emissionPolicy.peer.operator', 'cloud operator') : (p || '')
</script>

<template>
  <div class="ep-page" data-testid="ep-root">
    <header class="ep-head">
      <div>
        <h1 class="ep-title"><Icon name="mdi:database-search" /> {{ t('emissionPolicy.title', 'Emission policy') }}</h1>
        <p class="ep-sub">{{ t('emissionPolicy.subtitle', 'Which side may write each event type to the ledger, what the projection counts, and what this frame\'s event store holds: read live from this registry, the rules its TEG applies, and its store.') }}</p>
      </div>
      <div class="ep-head-actions">
        <span v-if="view?.generated_at" class="ep-muted" data-testid="ep-generated">{{ t('emissionPolicy.readAt', 'Read') }} {{ fmtTime(view.generated_at) }}</span>
        <button class="ep-btn" type="button" :disabled="loading" data-testid="ep-refresh" @click="load">
          <Icon name="mdi:refresh" /> {{ loading ? t('emissionPolicy.reading', 'Reading…') : t('emissionPolicy.readAgain', 'Read again') }}
        </button>
      </div>
    </header>

    <ReadFailedNotice v-if="failed && !view" :retry="load" data-testid="ep-unread" />
    <p v-else-if="loading && !view" class="ep-muted" data-testid="ep-loading">{{ t('emissionPolicy.loading', 'Reading the configuration…') }}</p>
    <p v-if="failed && view" class="ep-stale" role="status" data-testid="ep-stale">{{ t('emissionPolicy.stale', 'The last read failed: this is the read before it.') }}</p>

    <template v-if="view">
      <section class="ep-modes" :aria-label="t('emissionPolicy.sides', 'The three sides')">
        <article class="ep-card" data-testid="ep-mode-registry" :data-mode="view.modes.registry.mode">
          <div class="ep-label">{{ t('emissionPolicy.registryGate', 'The registry\'s gate') }}</div>
          <div class="ep-value"><span class="ep-mode" :data-mode="view.modes.registry.mode">{{ modeWord(view.modes.registry.mode) }}</span></div>
          <p class="ep-muted">{{ view.modes.registry.no_row }}</p>
          <p v-if="view.modes.registry.policy_table" class="ep-muted">
            {{ tp('emissionPolicy.tableRows', '{n} rows in the table', { n: num(view.modes.registry.policy_table.rows) }) }}<span v-if="cacheNote"> · {{ cacheNote }}</span>
          </p>
          <p v-if="view.modes.registry.set_by" class="ep-muted ep-small">{{ view.modes.registry.set_by }}</p>
        </article>
        <article class="ep-card" data-testid="ep-mode-teg" :data-mode="view.modes.teg.mode">
          <div class="ep-label">{{ t('emissionPolicy.tegGate', 'The TEG\'s gate') }}</div>
          <div class="ep-value"><span class="ep-mode" :data-mode="view.modes.teg.mode">{{ modeWord(view.modes.teg.mode) }}</span></div>
          <p v-if="view.modes.teg.always_allowed?.length" class="ep-muted">
            {{ t('emissionPolicy.alwaysAllowed', 'Always allowed') }}: <code v-for="a in view.modes.teg.always_allowed" :key="a" class="ep-code">{{ a }}</code>
          </p>
          <p v-if="view.modes.teg.derived" class="ep-muted ep-small">{{ view.modes.teg.derived }}</p>
        </article>
        <article class="ep-card" data-testid="ep-mode-projection">
          <div class="ep-label">{{ t('emissionPolicy.projection', 'The projection') }}</div>
          <div class="ep-value">{{ tp('emissionPolicy.balanceTypes', '{n} types move balances', { n: num(view.modes.projection.balance_types.length) }) }}</div>
          <p class="ep-muted">{{ tp('emissionPolicy.skippedRows', '{n} rows say skip: recorded, never counted', { n: num(view.modes.projection.skipped.length) }) }}</p>
          <p class="ep-muted ep-small"><code v-for="b in view.modes.projection.balance_types" :key="b" class="ep-code">{{ b }}</code></p>
        </article>
      </section>

      <section class="ep-card ep-health" data-testid="ep-summary">
        <div class="ep-bar" role="img" :aria-label="healthLabel">
          <span v-for="s in SEVERITIES" :key="s" class="ep-bar-seg" :data-sev="s" :style="{ flexGrow: sev[s] }" />
        </div>
        <ul class="ep-legend">
          <li v-for="s in SEVERITIES" :key="s" :data-testid="`ep-sev-${s}`"><span class="ep-dot" :data-sev="s" />{{ sevWord(s) }} <b>{{ num(sev[s]) }}</b></li>
        </ul>
        <p class="ep-muted">
          {{ tp('emissionPolicy.totals', '{types} event types · {rows} rows in the table · the registry\'s code emits {reg}, the TEG\'s {teg}', { types: num(view.summary.types), rows: num(view.summary.rows), reg: num(emittedBy('registry')), teg: num(emittedBy('teg')) }) }}
        </p>
        <p class="ep-reads">
          <span class="ep-read" :data-ok="view.store_read === 'ok'" data-testid="ep-store-read">
            <Icon :name="view.store_read === 'ok' ? 'mdi:check' : 'mdi:alert'" />
            {{ view.store_read === 'ok' ? t('emissionPolicy.storeRead', 'This frame\'s event store was read') : tp('emissionPolicy.storeUnread', 'This frame\'s event store was not read: {why}', { why: view.store_read }) }}
          </span>
          <span class="ep-read" :data-ok="view.shadow_read === 'ok'" data-testid="ep-shadow-read">
            <Icon :name="view.shadow_read === 'ok' ? 'mdi:check' : 'mdi:alert'" />
            {{ view.shadow_read === 'ok' ? t('emissionPolicy.shadowRead', 'The shadow counts were read') : tp('emissionPolicy.shadowUnread', 'The shadow counts were not read: {why}', { why: view.shadow_read }) }}
          </span>
        </p>
      </section>

      <section class="ep-filters">
        <div class="ep-chips" role="group" :aria-label="t('emissionPolicy.filterBy', 'Show')">
          <button type="button" class="ep-chip" :aria-pressed="finding === 'any'" data-testid="ep-filter-any" @click="finding = 'any'">
            {{ t('emissionPolicy.all', 'All types') }} <span class="ep-chip-n">{{ num(matrix.length) }}</span>
          </button>
          <button type="button" class="ep-chip" :aria-pressed="finding === 'balance'" data-testid="ep-filter-balance" @click="finding = 'balance'">
            {{ t('emissionPolicy.balance', 'Moves balances') }} <span class="ep-chip-n">{{ num(balanceCount) }}</span>
          </button>
          <button v-for="c in codes" :key="c" type="button" class="ep-chip" :data-sev="FINDING_SEVERITY[c]" :aria-pressed="finding === c"
                  :data-testid="`ep-filter-${c}`" :title="findingText(c)" @click="finding = c">
            {{ t(`emissionPolicy.code.${c}`, c) }} <span class="ep-chip-n">{{ num(view.summary.findings[c] || 0) }}</span>
          </button>
        </div>
        <div class="ep-filter-row">
          <label class="ep-field">
            <span class="ep-sr">{{ t('emissionPolicy.search', 'Event type or description') }}</span>
            <input v-model="query" type="search" :placeholder="t('emissionPolicy.search', 'Event type or description')" data-testid="ep-search" />
          </label>
          <label class="ep-field">
            <span class="ep-sr">{{ t('emissionPolicy.emittedBy', 'Emitted by') }}</span>
            <select v-model="emitter" data-testid="ep-emitter">
              <option value="any">{{ t('emissionPolicy.emitter.any', 'Emitted by anyone') }}</option>
              <option value="registry">{{ t('emissionPolicy.emitter.registry', 'Emitted by the registry') }}</option>
              <option value="teg">{{ t('emissionPolicy.emitter.teg', 'Emitted by the TEG') }}</option>
              <option value="both">{{ t('emissionPolicy.emitter.both', 'Emitted by both') }}</option>
              <option value="none">{{ t('emissionPolicy.emitter.none', 'Emitted by no code here') }}</option>
            </select>
          </label>
          <span class="ep-muted" data-testid="ep-shown">{{ tp('emissionPolicy.shown', '{n} of {total} shown', { n: num(rows.length), total: num(matrix.length) }) }}</span>
        </div>
        <p v-if="finding !== 'any' && finding !== 'balance'" class="ep-finding-text" data-testid="ep-finding-text">{{ findingText(finding) }}</p>
      </section>

      <ul class="ep-key" :aria-label="t('emissionPolicy.keyLabel', 'How to read a cell')">
        <li><span class="ep-cell" data-tone="ok">{{ t('emissionPolicy.cell.mayEmit', 'may emit') }}</span> {{ t('emissionPolicy.key.ok', 'a row lets this side write it') }}</li>
        <li><span class="ep-cell" data-tone="off">{{ t('emissionPolicy.cell.refused', 'refused') }}</span> {{ t('emissionPolicy.key.off', 'not this side\'s to write, as meant') }}</li>
        <li><span class="ep-cell" data-tone="warn">{{ t('emissionPolicy.cell.noRowCounted', 'no row: counted') }}</span> {{ t('emissionPolicy.key.warn', 'no row: the mode decides') }}</li>
        <li><span class="ep-cell" data-tone="bad">{{ t('emissionPolicy.cell.lost', 'refused: lost') }}</span> {{ t('emissionPolicy.key.bad', 'this side writes it and its gate refuses it') }}</li>
        <li><span class="ep-cell" data-tone="info">{{ t('emissionPolicy.cell.movesBalances', 'moves balances') }}</span> {{ t('emissionPolicy.key.info', 'the projection counts it in the supply audit') }}</li>
      </ul>

      <div class="ep-table-wrap" role="region" tabindex="0" :aria-label="t('emissionPolicy.matrixLabel', 'One row per event type')">
        <table class="ep-table" data-testid="ep-matrix">
          <thead>
            <tr>
              <th scope="col">{{ t('emissionPolicy.col.type', 'Event type') }}</th>
              <th scope="col">{{ t('emissionPolicy.col.registry', 'Registry') }}</th>
              <th scope="col">{{ t('emissionPolicy.col.teg', 'TEG') }}</th>
              <th scope="col">{{ t('emissionPolicy.col.projection', 'Projection') }}</th>
              <th scope="col" class="ep-num">{{ t('emissionPolicy.col.store', 'In this store') }}</th>
              <th scope="col" class="ep-num" :title="t('emissionPolicy.col.shadowTitle', 'emits the shadow mode counted as refusals enforce would make')">{{ t('emissionPolicy.col.shadow', 'Shadow') }}</th>
              <th scope="col">{{ t('emissionPolicy.col.findings', 'Findings') }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="r in rows" :key="r.event_type">
              <tr class="ep-row" :data-sev="severity(r)" :data-testid="`ep-row-${r.event_type}`">
                <th scope="row" class="ep-type">
                  <button type="button" class="ep-et" :aria-expanded="expanded === r.event_type" @click="toggle(r.event_type)">
                    <Icon :name="expanded === r.event_type ? 'mdi:chevron-down' : 'mdi:chevron-right'" />
                    <code>{{ r.event_type }}</code>
                  </button>
                  <span v-if="r.balance_moving" class="ep-tag">{{ t('emissionPolicy.balanceTag', 'balance') }}</span>
                  <span v-if="!r.row" class="ep-tag ep-tag--norow">{{ t('emissionPolicy.noRowTag', 'no row') }}</span>
                  <div class="ep-by" data-testid="ep-emitted-by">
                    {{ t('emissionPolicy.col.emittedBy', 'Emitted by') }}:
                    <span v-for="e in r.emitted_by" :key="e" class="ep-emitter" :data-e="e">{{ e === 'teg' ? 'TEG' : t('emissionPolicy.registryWord', 'registry') }}</span>
                    <span v-if="!r.emitted_by.length" class="ep-muted">{{ t('emissionPolicy.noEmitter', 'no code here') }}</span>
                  </div>
                </th>
                <td><span class="ep-cell" :data-tone="registryCell(r).tone" data-testid="ep-cell-registry">{{ cellWord(registryCell(r)) }}</span></td>
                <td><span class="ep-cell" :data-tone="tegCell(r).tone" data-testid="ep-cell-teg">{{ cellWord(tegCell(r)) }}</span></td>
                <td><span class="ep-cell" :data-tone="projectionCell(r).tone" data-testid="ep-cell-projection">{{ cellWord(projectionCell(r)) }}</span></td>
                <td class="ep-num" data-testid="ep-cell-store" :data-read="r.store_count === null ? 'no' : 'yes'">
                  <span class="ep-count">{{ count(r.store_count) }}</span>
                  <span v-if="barPercent(r.store_count, maxStore) !== null" class="ep-mini" aria-hidden="true"><span :style="{ width: barPercent(r.store_count, maxStore) + '%' }" /></span>
                </td>
                <td class="ep-num" data-testid="ep-cell-shadow" :data-hot="(r.shadow_would_refuse || 0) > 0">{{ count(r.shadow_would_refuse) }}</td>
                <td class="ep-findings">
                  <span v-for="f in r.findings" :key="f" class="ep-pill" :data-sev="FINDING_SEVERITY[f] || 'warn'" :title="findingText(f)">{{ t(`emissionPolicy.code.${f}`, f) }}</span>
                </td>
              </tr>
              <tr v-if="expanded === r.event_type" class="ep-detail" :data-testid="`ep-detail-${r.event_type}`">
                <td colspan="7">
                  <dl class="ep-facts">
                    <dt>{{ t('emissionPolicy.detail.row', 'The table\'s row') }}</dt>
                    <dd v-if="r.row">
                      {{ t('emissionPolicy.detail.fromRegistry', 'the registry may emit') }}: <b>{{ flag(r.row.emit_from_registry) }}</b> ·
                      {{ t('emissionPolicy.detail.fromTeg', 'the TEG may emit') }}: <b>{{ flag(r.row.emit_from_teg) }}</b> ·
                      {{ t('emissionPolicy.detail.skip', 'skipped by the projection') }}: <b>{{ flag(r.row.skip_in_projection) }}</b>
                      <span v-if="r.row.updated_at" class="ep-muted"> · {{ t('emissionPolicy.detail.updated', 'changed') }} {{ fmtTime(r.row.updated_at) }}</span>
                    </dd>
                    <dd v-else>{{ t('emissionPolicy.detail.noRow', 'none: each gate decides by its mode') }}</dd>
                    <template v-if="r.row?.description">
                      <dt>{{ t('emissionPolicy.detail.description', 'Description') }}</dt><dd>{{ r.row.description }}</dd>
                    </template>
                    <dt>{{ t('emissionPolicy.detail.findings', 'Findings') }}</dt>
                    <dd v-if="r.findings.length"><ul class="ep-flist"><li v-for="f in r.findings" :key="f" :data-sev="FINDING_SEVERITY[f] || 'warn'">{{ findingText(f) }}</li></ul></dd>
                    <dd v-else>{{ t('emissionPolicy.detail.none', 'none') }}</dd>
                  </dl>
                </td>
              </tr>
            </template>
            <tr v-if="!rows.length"><td colspan="7" class="ep-muted" data-testid="ep-none">{{ t('emissionPolicy.noneMatch', 'No event type matches.') }}</td></tr>
          </tbody>
        </table>
      </div>

      <section v-if="view.drift" class="ep-drift" data-testid="ep-drift">
        <h2 class="ep-h2">{{ t('emissionPolicy.driftTitle', 'The same table on the other frames') }}</h2>
        <p class="ep-muted">{{ t('emissionPolicy.driftSub', 'Each peer\'s rows against this registry\'s: types only one side has, and types whose three switches differ.') }}</p>
        <p v-if="!view.drift.length" class="ep-muted" data-testid="ep-drift-none">{{ t('emissionPolicy.noPeers', 'This registry names no peer to compare with.') }}</p>
        <div class="ep-peers">
          <article v-for="d in view.drift" :key="d.peer" class="ep-card" :data-testid="`ep-drift-${d.peer}`" :data-read="d.read === 'ok' ? 'ok' : 'failed'">
            <div class="ep-peer-head"><b>{{ d.peer }}</b> <span class="ep-muted">{{ peerTypeWord(d.peer_type) }}</span></div>
            <p v-if="d.read !== 'ok'" class="ep-unread"><Icon name="mdi:alert" /> {{ tp('emissionPolicy.peerUnread', 'not read: {why}', { why: d.read }) }}</p>
            <template v-else>
              <p v-if="!d.only_here?.length && !d.only_there?.length && !d.differing?.length" class="ep-ok"><Icon name="mdi:check" /> {{ t('emissionPolicy.same', 'the same rows as here') }}</p>
              <details v-if="d.only_here?.length" class="ep-det">
                <summary>{{ tp('emissionPolicy.onlyHere', '{n} only here', { n: num(d.only_here.length) }) }}</summary>
                <code v-for="x in d.only_here" :key="x" class="ep-code">{{ x }}</code>
              </details>
              <details v-if="d.only_there?.length" class="ep-det">
                <summary>{{ tp('emissionPolicy.onlyThere', '{n} only there', { n: num(d.only_there.length) }) }}</summary>
                <code v-for="x in d.only_there" :key="x" class="ep-code">{{ x }}</code>
              </details>
              <details v-if="d.differing?.length" class="ep-det" open>
                <summary>{{ tp('emissionPolicy.differing', '{n} differ', { n: num(d.differing.length) }) }}</summary>
                <table class="ep-difftable">
                  <thead><tr><th scope="col">{{ t('emissionPolicy.col.type', 'Event type') }}</th><th scope="col">{{ t('emissionPolicy.here', 'here') }}</th><th scope="col">{{ t('emissionPolicy.there', 'there') }}</th></tr></thead>
                  <tbody>
                    <tr v-for="x in d.differing" :key="x.event_type">
                      <th scope="row"><code>{{ x.event_type }}</code></th>
                      <td>R {{ flag(x.here.emit_from_registry) }} · T {{ flag(x.here.emit_from_teg) }} · skip {{ flag(x.here.skip_in_projection) }}</td>
                      <td>R {{ flag(x.there.emit_from_registry) }} · T {{ flag(x.there.emit_from_teg) }} · skip {{ flag(x.there.skip_in_projection) }}</td>
                    </tr>
                  </tbody>
                </table>
              </details>
            </template>
          </article>
        </div>
      </section>

      <p class="ep-muted ep-small">
        {{ t('emissionPolicy.editHint', 'To change a row, use the Policy tab of Ledger Forensics; this page only reads.') }}
        <router-link to="/admin/forensics" class="ep-link">{{ t('emissionPolicy.toForensics', 'Ledger Forensics') }}</router-link>
      </p>
    </template>
  </div>
</template>

<style scoped>
.ep-page { padding: 24px; max-width: 1400px; margin: 0 auto; display: flex; flex-direction: column; gap: 16px; }
.ep-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
.ep-head-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.ep-title { font-size: 1.4rem; font-weight: 600; display: flex; align-items: center; gap: 8px; margin: 0; }
.ep-sub { margin: 4px 0 0; opacity: 0.75; max-width: 80ch; }
.ep-h2 { font-size: 1.1rem; font-weight: 600; margin: 0; }
.ep-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 14px; border-radius: 8px; border: 1px solid rgba(56, 189, 248, 0.5); background: rgba(56, 189, 248, 0.12); color: inherit; cursor: pointer; }
.ep-btn:disabled { opacity: 0.5; cursor: default; }
.ep-muted { font-size: 0.82rem; opacity: 0.72; margin: 4px 0 0; }
.ep-small { font-size: 0.76rem; }
.ep-stale { color: #fbbf24; margin: 0; }
.ep-modes { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.ep-card { border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 10px; padding: 14px 16px; background: rgba(15, 23, 42, 0.35); }
.ep-label { font-size: 0.78rem; opacity: 0.7; margin-bottom: 4px; }
.ep-value { font-size: 1rem; font-weight: 600; }
.ep-mode[data-mode="enforce"], .ep-mode[data-mode="fail-closed"] { color: #34d399; }
.ep-mode[data-mode="shadow"] { color: #fbbf24; }
.ep-mode[data-mode="off"] { color: #f87171; }
.ep-code { display: inline-block; font-size: 0.74rem; padding: 1px 6px; margin: 2px 4px 2px 0; border-radius: 5px; background: rgba(2, 6, 23, 0.55); border: 1px solid rgba(148, 163, 184, 0.2); }
.ep-health { display: flex; flex-direction: column; gap: 8px; }
.ep-bar { display: flex; height: 14px; border-radius: 7px; overflow: hidden; background: rgba(148, 163, 184, 0.15); }
.ep-bar-seg { flex-basis: 0; min-width: 0; }
.ep-bar-seg[data-sev="bad"], .ep-dot[data-sev="bad"] { background: #ef4444; }
.ep-bar-seg[data-sev="warn"], .ep-dot[data-sev="warn"] { background: #f59e0b; }
.ep-bar-seg[data-sev="note"], .ep-dot[data-sev="note"] { background: #64748b; }
.ep-bar-seg[data-sev="clean"], .ep-dot[data-sev="clean"] { background: #10b981; }
.ep-legend { display: flex; flex-wrap: wrap; gap: 6px 18px; list-style: none; margin: 0; padding: 0; font-size: 0.84rem; }
.ep-legend li { display: inline-flex; align-items: center; gap: 6px; }
.ep-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
.ep-reads { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; font-size: 0.84rem; }
.ep-read { display: inline-flex; align-items: center; gap: 6px; }
.ep-read[data-ok="true"] { color: #34d399; }
.ep-read[data-ok="false"] { color: #fbbf24; }
.ep-filters { display: flex; flex-direction: column; gap: 10px; }
.ep-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.ep-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; border: 1px solid rgba(148, 163, 184, 0.35); background: transparent; color: inherit; cursor: pointer; font-size: 0.82rem; }
.ep-chip[aria-pressed="true"] { background: rgba(56, 189, 248, 0.18); border-color: rgba(56, 189, 248, 0.7); }
.ep-chip[data-sev="bad"] { border-color: rgba(239, 68, 68, 0.6); }
.ep-chip[data-sev="warn"] { border-color: rgba(245, 158, 11, 0.6); }
.ep-chip-n { font-variant-numeric: tabular-nums; opacity: 0.8; }
.ep-filter-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.ep-field input, .ep-field select { padding: 6px 8px; border-radius: 6px; border: 1px solid rgba(148, 163, 184, 0.35); background: rgba(2, 6, 23, 0.5); color: inherit; min-width: 220px; }
.ep-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.ep-finding-text { margin: 0; padding: 8px 12px; border-left: 3px solid rgba(56, 189, 248, 0.6); background: rgba(56, 189, 248, 0.06); font-size: 0.88rem; }
.ep-key { display: flex; flex-wrap: wrap; gap: 6px 16px; list-style: none; margin: 0; padding: 0; font-size: 0.8rem; opacity: 0.9; }
.ep-key li { display: inline-flex; align-items: center; gap: 6px; }
.ep-table-wrap { overflow-x: auto; border: 1px solid rgba(148, 163, 184, 0.2); border-radius: 10px; }
.ep-table-wrap:focus-visible { outline: 2px solid rgba(56, 189, 248, 0.8); outline-offset: 2px; }
.ep-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.ep-table thead th { position: sticky; top: 0; background: rgba(15, 23, 42, 0.95); text-align: left; font-weight: 600; padding: 8px 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.25); white-space: nowrap; }
.ep-table td, .ep-table tbody th { padding: 6px 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.1); vertical-align: middle; text-align: left; font-weight: 400; }
.ep-row[data-sev="bad"] { background: rgba(239, 68, 68, 0.07); }
.ep-row[data-sev="warn"] { background: rgba(245, 158, 11, 0.04); }
.ep-type { min-width: 210px; }
.ep-type .ep-tag { display: inline-block; margin-top: 2px; }
.ep-by { font-size: 0.72rem; opacity: 0.85; margin-top: 3px; }
.ep-by .ep-emitter { margin-left: 2px; }
.ep-findings { min-width: 150px; }
.ep-et { display: inline-flex; align-items: center; gap: 4px; background: none; border: 0; color: inherit; cursor: pointer; padding: 0; font: inherit; }
.ep-et code { font-size: 0.82rem; }
.ep-tag { font-size: 0.68rem; padding: 1px 6px; border-radius: 999px; margin-left: 6px; border: 1px solid rgba(34, 211, 238, 0.6); color: #67e8f9; }
.ep-tag--norow { border-color: rgba(245, 158, 11, 0.6); color: #fcd34d; }
.ep-emitter { display: inline-block; font-size: 0.72rem; padding: 1px 7px; margin-right: 4px; border-radius: 5px; border: 1px solid rgba(148, 163, 184, 0.35); }
.ep-emitter[data-e="teg"] { border-color: rgba(167, 139, 250, 0.6); color: #c4b5fd; }
.ep-emitter[data-e="registry"] { border-color: rgba(56, 189, 248, 0.6); color: #7dd3fc; }
.ep-cell { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 0.76rem; white-space: nowrap; border: 1px solid transparent; }
.ep-cell[data-tone="ok"] { background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.45); color: #6ee7b7; }
.ep-cell[data-tone="off"] { background: rgba(100, 116, 139, 0.12); border-color: rgba(100, 116, 139, 0.35); color: #cbd5e1; }
.ep-cell[data-tone="warn"] { background: rgba(245, 158, 11, 0.14); border-color: rgba(245, 158, 11, 0.5); color: #fcd34d; }
.ep-cell[data-tone="bad"] { background: rgba(239, 68, 68, 0.18); border-color: rgba(239, 68, 68, 0.6); color: #fca5a5; font-weight: 600; }
.ep-cell[data-tone="info"] { background: rgba(34, 211, 238, 0.13); border-color: rgba(34, 211, 238, 0.5); color: #67e8f9; }
.ep-num { text-align: right !important; font-variant-numeric: tabular-nums; white-space: nowrap; }
.ep-count { display: inline-block; min-width: 5ch; }
.ep-mini { display: inline-block; width: 44px; height: 6px; margin-left: 8px; border-radius: 3px; background: rgba(148, 163, 184, 0.15); vertical-align: middle; overflow: hidden; }
.ep-mini > span { display: block; height: 100%; background: rgba(56, 189, 248, 0.75); }
.ep-table td[data-read="no"] .ep-count, .ep-num[data-read="no"] { color: #fbbf24; font-style: italic; }
.ep-num[data-hot="true"] { color: #fbbf24; font-weight: 600; }
.ep-pill { display: inline-block; font-size: 0.7rem; padding: 1px 7px; margin: 1px 4px 1px 0; border-radius: 999px; border: 1px solid; white-space: nowrap; }
.ep-pill[data-sev="bad"] { border-color: rgba(239, 68, 68, 0.6); color: #fca5a5; }
.ep-pill[data-sev="warn"] { border-color: rgba(245, 158, 11, 0.6); color: #fcd34d; }
.ep-pill[data-sev="note"] { border-color: rgba(100, 116, 139, 0.6); color: #cbd5e1; }
.ep-detail td { background: rgba(2, 6, 23, 0.45); }
.ep-facts { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 4px 0; font-size: 0.84rem; }
.ep-facts dt { opacity: 0.7; }
.ep-facts dd { margin: 0; }
.ep-flist { margin: 0; padding-left: 18px; }
.ep-flist li[data-sev="bad"] { color: #fca5a5; }
.ep-flist li[data-sev="warn"] { color: #fcd34d; }
.ep-drift { display: flex; flex-direction: column; gap: 10px; }
.ep-peers { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }
.ep-peer-head { display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }
.ep-unread { color: #fbbf24; display: flex; align-items: center; gap: 6px; margin: 0; font-size: 0.86rem; }
.ep-ok { color: #34d399; display: flex; align-items: center; gap: 6px; margin: 0; font-size: 0.86rem; }
.ep-det { margin-top: 6px; font-size: 0.84rem; }
.ep-det summary { cursor: pointer; }
.ep-difftable { width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 0.78rem; }
.ep-difftable th, .ep-difftable td { padding: 3px 6px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); text-align: left; font-weight: 400; }
.ep-link { color: #7dd3fc; margin-left: 4px; }
@media (max-width: 640px) {
  .ep-page { padding: 16px; }
  .ep-field input, .ep-field select { min-width: 0; width: 100%; }
  .ep-filter-row { flex-direction: column; align-items: stretch; }
}
</style>
