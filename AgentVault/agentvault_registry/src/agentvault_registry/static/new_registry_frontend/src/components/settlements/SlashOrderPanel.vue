<template>
  <!-- V0658 (k): the slash order every slash on this registry drains, admin only (the view's route asks the
       enforcement flag, and the registry's section route admin_enforcement). -->
  <section class="so" data-testid="slash-order">
    <header class="so-head">
      <div>
        <h2 class="so-title">{{ t('adminSettlementsView.slashOrder.title', 'How a slash is taken') }}</h2>
        <p class="so-lead">{{ t('adminSettlementsView.slashOrder.lead', 'Every slash on this registry, a ruling here or a peer\'s accepted request, takes these steps in this order. Each step takes at most its share of the amount, and never more than the agent holds on the ledger.') }}</p>
      </div>
      <span v-if="loaded" class="so-pill" :class="{ 'so-pill--own': source === 'policy' }" data-testid="slash-order-source">
        {{ source === 'policy'
          ? tp('adminSettlementsView.slashOrder.own', 'This registry\'s order, policy version {v}', { v: version })
          : t('adminSettlementsView.slashOrder.factory', 'The factory order') }}
      </span>
    </header>

    <p v-if="loading && !loaded" class="so-muted">{{ t('adminSettlementsView.slashOrder.reading', 'Reading the slash order…') }}</p>
    <ReadFailedNotice v-else-if="readError" dense :retry="load" data-testid="slash-order-read-failed"
      :text="t('adminSettlementsView.slashOrder.readFailed', 'The slash order could not be read just now.')" />

    <template v-if="loaded">
      <ol class="so-steps">
        <li v-for="(row, i) in rows" :key="row.source" class="so-step"
            :class="{ 'so-step--off': !row.enabled, 'so-step--cascade': row.source === CASCADE }"
            :data-testid="`slash-order-step-${row.source}`">
          <span class="so-n">{{ i + 1 }}</span>
          <div class="so-what">
            <div class="so-name">{{ label(row.source) }}</div>
            <div class="so-hint">{{ hint(row.source) }}</div>
          </div>
          <label class="so-switch">
            <input type="checkbox" :checked="row.enabled" :disabled="busy" :data-testid="`slash-order-on-${row.source}`"
                   @change="setEnabled(i, ($event.target as HTMLInputElement).checked)" />
            <span>{{ row.enabled ? t('adminSettlementsView.slashOrder.on', 'On') : t('adminSettlementsView.slashOrder.off', 'Off') }}</span>
          </label>
          <label class="so-share">
            <span>{{ t('adminSettlementsView.slashOrder.upTo', 'up to') }}</span>
            <input type="number" min="0" max="100" step="1" :value="row.maxPercent" :disabled="busy || !row.enabled"
                   :data-testid="`slash-order-share-${row.source}`"
                   @change="setPercent(i, ($event.target as HTMLInputElement).value)" />
            <span>{{ t('adminSettlementsView.slashOrder.ofTheAmount', '% of the amount') }}</span>
          </label>
          <div v-if="row.source !== CASCADE" class="so-move">
            <button type="button" class="so-btn" :disabled="busy || i === 0" :data-testid="`slash-order-up-${row.source}`"
                    :aria-label="t('adminSettlementsView.slashOrder.earlier', 'Take earlier')" @click="shift(i, -1)">↑</button>
            <button type="button" class="so-btn" :disabled="busy || i >= ownCount - 1" :data-testid="`slash-order-down-${row.source}`"
                    :aria-label="t('adminSettlementsView.slashOrder.later', 'Take later')" @click="shift(i, 1)">↓</button>
          </div>
          <div v-else class="so-move so-muted">{{ t('adminSettlementsView.slashOrder.last', 'always last') }}</div>
        </li>
      </ol>

      <ul v-if="issues.length" class="so-problems" role="alert" data-testid="slash-order-problems">
        <li v-for="p in issues" :key="p">{{ problemText(p) }}</li>
      </ul>

      <div class="so-actions">
        <button type="button" class="so-btn so-btn--primary" :disabled="!canSave" data-testid="slash-order-save"
                @click="asking = true">{{ t('adminSettlementsView.slashOrder.save', 'Save the order…') }}</button>
        <button type="button" class="so-btn" :disabled="busy || !dirty" data-testid="slash-order-undo" @click="undo">
          {{ t('adminSettlementsView.slashOrder.undo', 'Undo changes') }}</button>
        <span v-if="!dirty && savedVersion === null" class="so-muted">{{ t('adminSettlementsView.slashOrder.unchanged', 'unchanged') }}</span>
      </div>
      <p v-if="saveError" class="so-err" role="alert" data-testid="slash-order-save-failed">{{ saveError }}</p>
      <p v-if="savedVersion !== null" class="so-ok" data-testid="slash-order-saved">
        {{ tp('adminSettlementsView.slashOrder.saved', 'Saved: policy version {v}.', { v: savedVersion }) }}</p>
    </template>

    <ConfirmActionModal
      :show="asking"
      :title="t('adminSettlementsView.slashOrder.confirmTitle', 'Change how a slash is taken')"
      :message="summary"
      tone="warn"
      :confirm-text="t('adminSettlementsView.slashOrder.confirm', 'Save the order')"
      :busy-text="t('adminSettlementsView.slashOrder.saving', 'Saving…')"
      :busy="busy"
      reason-required
      :reason-min-length="5"
      :reason-placeholder="t('adminSettlementsView.slashOrder.reasonPh', 'Why the order changes (kept in the audit log and on the ledger)')"
      @close="asking = false"
      @confirm="save"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { enforcementAdmin } from '@/services/api/enforcementAdmin'
import {
  CASCADE, move, problems, sameOrder, toOrder, toRows,
  type SlashOrderProblem, type SlashRow, type SlashSource,
} from '@/services/slashOrder'

const { t, tp } = useI18n()

const rows = ref<SlashRow[]>([])
const stored = ref<SlashRow[]>([])
const source = ref<'policy' | 'default'>('default')
const version = ref(0)
const loading = ref(false)
const loaded = ref(false)
const readError = ref(false)
const busy = ref(false)
const asking = ref(false)
const saveError = ref('')
const savedVersion = ref<number | null>(null)

const ownCount = computed(() => rows.value.filter((r) => r.source !== CASCADE).length)
const issues = computed(() => problems(rows.value))
const dirty = computed(() => !sameOrder(rows.value, stored.value))
const canSave = computed(() => loaded.value && !busy.value && dirty.value && issues.value.length === 0)

function label(s: SlashSource): string {
  switch (s) {
    case 'bond': return t('adminSettlementsView.slashOrder.bond', 'Bond')
    case 'stake': return t('adminSettlementsView.slashOrder.locks', 'Locked units')
    case 'liquid': return t('adminSettlementsView.slashOrder.liquid', 'Liquid units')
    default: return t('adminSettlementsView.slashOrder.cascade', 'The owner\'s other agents')
  }
}

function hint(s: SlashSource): string {
  switch (s) {
    case 'bond': return t('adminSettlementsView.slashOrder.bondHint', 'The reputation bond the registry holds for the agent. The treasury already holds it, so taking it moves nothing.')
    case 'stake': return t('adminSettlementsView.slashOrder.locksHint', 'The agent\'s locked units, released early and moved to the treasury. The 10% penalty for the early release comes on top of the slash.')
    case 'liquid': return t('adminSettlementsView.slashOrder.liquidHint', 'The agent\'s liquid units, moved to the treasury.')
    default: return t('adminSettlementsView.slashOrder.cascadeHint', 'What the agent cannot cover, from the same developer\'s other agents on this registry: the most held first, at most 25, each through the steps above. Never the agents of a service account or of an administrator.')
  }
}

function problemText(p: SlashOrderProblem): string {
  return p === 'noOwnStep'
    ? t('adminSettlementsView.slashOrder.problemNoOwnStep', 'Keep at least one of the bond, locked units or liquid units on.')
    : t('adminSettlementsView.slashOrder.problemPercent', 'Each share is a number from 0 to 100.')
}

/** The order the confirmation names, step by step. */
const summary = computed(() => rows.value
  .filter((r) => r.enabled)
  .map((r, i) => `${i + 1}. ${label(r.source)} (${tp('adminSettlementsView.slashOrder.upToPercent', 'up to {p}%', { p: r.maxPercent })})`)
  .join(' · '))

function setEnabled(i: number, on: boolean) {
  rows.value = rows.value.map((r, j) => (j === i ? { ...r, enabled: on } : r))
  savedVersion.value = null
}

function setPercent(i: number, raw: string) {
  const n = Number(raw)
  rows.value = rows.value.map((r, j) => (j === i ? { ...r, maxPercent: Number.isFinite(n) ? n : r.maxPercent } : r))
  savedVersion.value = null
}

function shift(i: number, dir: -1 | 1) {
  rows.value = move(rows.value, i, dir)
  savedVersion.value = null
}

function undo() {
  rows.value = stored.value.map((r) => ({ ...r }))
  saveError.value = ''
}

async function load() {
  loading.value = true
  readError.value = false
  try {
    const section = await enforcementAdmin.getSlashOrder()
    stored.value = toRows(section.value ?? section.default)
    rows.value = stored.value.map((r) => ({ ...r }))
    source.value = section.source === 'policy' ? 'policy' : 'default'
    version.value = section.version ?? 0
    loaded.value = true
  } catch {
    readError.value = true
  } finally {
    loading.value = false
  }
}

async function save(reason: string) {
  if (!canSave.value) return
  busy.value = true
  saveError.value = ''
  try {
    const out = await enforcementAdmin.updateSlashOrder(toOrder(rows.value), reason)
    asking.value = false
    await load()
    savedVersion.value = typeof out?.version === 'number' ? out.version : version.value
  } catch (e: any) {
    // the registry's refusal, in its words (a 422 names the rule the order breaks)
    saveError.value = e?.response?.data?.detail || e?.message || t('adminSettlementsView.slashOrder.saveFailed', 'The order was not saved.')
    asking.value = false
  } finally {
    busy.value = false
  }
}

onMounted(load)

defineExpose({ load })
</script>

<style scoped>
.so {
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 10px;
  padding: 1.1rem 1.25rem;
  background: rgba(10, 13, 22, 0.6);
  margin-bottom: 1.25rem;
}
.so-head { display: flex; gap: 1rem; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; }
.so-title { font-size: 1rem; font-weight: 600; color: #e2e8f0; margin: 0 0 0.25rem; }
.so-lead { font-size: 0.82rem; color: #94a3b8; margin: 0; max-width: 62rem; }
.so-pill {
  font-size: 0.72rem; padding: 0.2rem 0.6rem; border-radius: 999px; white-space: nowrap;
  border: 1px solid rgba(148, 163, 184, 0.3); color: #94a3b8;
}
.so-pill--own { border-color: rgba(34, 211, 238, 0.45); color: #67e8f9; }
.so-steps { list-style: none; margin: 0.9rem 0 0; padding: 0; display: grid; gap: 0.5rem; }
.so-step {
  display: grid; grid-template-columns: 1.6rem minmax(0, 1fr) auto auto auto; gap: 0.75rem; align-items: center;
  padding: 0.6rem 0.75rem; border: 1px solid rgba(148, 163, 184, 0.14); border-radius: 8px;
}
/* a step switched off is said by its colour and its border, never by opacity: faded text falls under 4.5:1 */
.so-step--off { border-color: rgba(148, 163, 184, 0.08); }
.so-step--off .so-name { color: #94a3b8; }
.so-step--cascade { border-style: dashed; }
.so-n { font-variant-numeric: tabular-nums; color: #94a3b8; font-size: 0.8rem; text-align: right; }
.so-what { min-width: 0; }
.so-name { color: #e2e8f0; font-size: 0.88rem; font-weight: 500; }
.so-hint { color: #94a3b8; font-size: 0.76rem; margin-top: 0.15rem; }
.so-switch, .so-share { display: inline-flex; align-items: center; gap: 0.35rem; font-size: 0.78rem; color: #cbd5e1; }
.so-share input {
  width: 4.2rem; text-align: right; font-variant-numeric: tabular-nums; background: rgba(15, 23, 42, 0.9);
  border: 1px solid rgba(148, 163, 184, 0.3); border-radius: 4px; color: #e2e8f0; padding: 0.15rem 0.35rem;
}
.so-move { display: inline-flex; gap: 0.25rem; min-width: 4.2rem; justify-content: flex-end; font-size: 0.74rem; }
.so-btn {
  border: 1px solid rgba(148, 163, 184, 0.3); background: transparent; color: #cbd5e1; border-radius: 6px;
  padding: 0.2rem 0.55rem; font-size: 0.8rem; cursor: pointer;
}
.so-btn:disabled { opacity: 0.4; cursor: default; }
.so-btn--primary { border-color: rgba(34, 211, 238, 0.5); color: #67e8f9; }
.so-actions { display: flex; gap: 0.6rem; align-items: center; margin-top: 0.85rem; flex-wrap: wrap; }
.so-problems { margin: 0.6rem 0 0; padding-left: 1.1rem; color: #fbbf24; font-size: 0.8rem; }
.so-err { color: #f87171; font-size: 0.8rem; margin: 0.5rem 0 0; }
.so-ok { color: #4ade80; font-size: 0.8rem; margin: 0.5rem 0 0; }
.so-muted { color: #94a3b8; font-size: 0.78rem; }
@media (max-width: 720px) {
  .so-step { grid-template-columns: 1.6rem minmax(0, 1fr); }
  .so-switch, .so-share, .so-move { grid-column: 2; justify-content: flex-start; }
}
</style>
