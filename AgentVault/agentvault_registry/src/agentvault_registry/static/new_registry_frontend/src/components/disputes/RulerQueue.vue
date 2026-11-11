<template>
  <!-- V0657 (a), item 3: one ruler's queue. Every open dispute record, and every Guild order and contract in dispute
       with no open record (give it one, and it is ruled from the same screen by the same rules). -->
  <div class="dsp-q" data-testid="ruler-queue" :data-state="state">
    <div class="dsp-q__head">
      <strong>{{ tp('disputesView.v2.queueHead', '{n} waiting for a ruling', { n: items.length }) }}</strong>
      <button type="button" class="tp-btn tp-btn--ghost" @click="load">{{ t('disputesView.v2.refresh', 'Refresh') }}</button>
    </div>
    <p v-if="state === 'loading'" class="dsp-q__muted">{{ t('disputesView.v2.queueLoading', 'Reading the queue…') }}</p>
    <p v-else-if="state === 'failed'" class="dsp-q__err">{{ error }}</p>
    <p v-else-if="!items.length" class="dsp-q__muted">{{ t('disputesView.v2.queueEmpty', 'Nothing waits for a ruling.') }}</p>
    <ul v-else class="dsp-q__list">
      <li v-for="it in items" :key="it.kind + ':' + it.id" class="dsp-q__row" :data-kind="it.kind" data-testid="ruler-queue-row">
        <div class="dsp-q__main">
          <span class="dsp-q__kind">{{ kindWord(it.kind) }}</span>
          <span class="dsp-q__title">{{ it.title || (it.dispute_id ? `#${it.dispute_id}` : it.id) }}</span>
          <span class="dsp-q__why">{{ it.reason_text }}</span>
          <span class="dsp-q__who">
            <span :title="it.complainant_did || ''">{{ it.complainant_name || short(it.complainant_did) }}</span>
            →
            <span :title="it.defendant_did || ''">{{ it.defendant_name || short(it.defendant_did) }}</span>
          </span>
        </div>
        <div class="dsp-q__side">
          <span v-if="it.at_stake" class="dsp-q__stake">{{ amount(it.at_stake.amount) }} {{ it.at_stake.currency || '' }}</span>
          <span class="dsp-q__age">{{ age(it.opened_at) }}</span>
          <button v-if="it.kind === 'dispute'" type="button" class="tp-btn tp-btn--success" data-testid="ruler-queue-open" @click="emit('open', Number(it.dispute_id))">
            {{ t('disputesView.v2.open', 'Open') }}
          </button>
          <button v-else type="button" class="tp-btn tp-btn--ghost" :disabled="filing === it.kind + ':' + it.id" data-testid="ruler-queue-file" @click="file(it)">
            {{ t('disputesView.v2.fileRecord', 'Give it a record') }}
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { appLocale } from '@/services/appLocale'
import { disputesApi, type QueueItem } from '@/services/api/disputes'

dayjs.extend(relativeTime)
const emit = defineEmits<{ (e: 'open', disputeId: number): void }>()
const { t, tp } = useI18n()
const uiStore = useUIStore()

const items = ref<QueueItem[]>([])
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const error = ref('')
const filing = ref('')

function kindWord(k: string): string {
  if (k === 'guild') return t('disputesView.v2.kindGuild', 'Guild order, no record')
  if (k === 'contract') return t('disputesView.v2.kindContract', 'Contract, no record')
  return t('disputesView.v2.kindDispute', 'Dispute')
}
function short(did?: string | null): string {
  if (!did) return '?'
  const core = did.replace(/^did:[a-z0-9]+:/i, '')
  return core.length > 16 ? core.slice(0, 6) + '…' + core.slice(-6) : core
}
function amount(v: any): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : String(v ?? '')
}
function age(v?: string | null): string { return v ? dayjs(v).fromNow() : '' }

async function load() {
  state.value = 'loading'
  try {
    items.value = (await disputesApi.rulerQueue()).items || []
    state.value = 'ready'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || t('disputesView.v2.queueFailed', 'The queue could not be read.')
    state.value = 'failed'
  }
}

async function file(it: QueueItem) {
  filing.value = it.kind + ':' + it.id
  try {
    const out = await disputesApi.fileQueueRecord(it.kind as 'guild' | 'contract', String(it.id))
    await load()
    emit('open', Number(out.dispute_id))
  } catch (e: any) {
    uiStore.showError(t('disputesView.v2.fileFailed', 'No record was filed'), e?.response?.data?.detail || e?.message || '')
  } finally {
    filing.value = ''
  }
}

onMounted(load)
defineExpose({ load })
</script>

<style scoped>
.dsp-q { display: flex; flex-direction: column; gap: 10px; }
.dsp-q__head { display: flex; justify-content: space-between; align-items: center; }
.dsp-q__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.dsp-q__row { display: flex; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid var(--drc-line, rgba(255, 255, 255, .12)); border-radius: 8px; }
.dsp-q__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.dsp-q__kind { font-size: 11px; opacity: .65; text-transform: uppercase; letter-spacing: .04em; }
.dsp-q__title { font-weight: 600; overflow-wrap: anywhere; }
.dsp-q__why, .dsp-q__who { font-size: 13px; opacity: .85; }
.dsp-q__side { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: 0 0 auto; }
.dsp-q__stake { font-variant-numeric: tabular-nums; }
.dsp-q__age { font-size: 12px; opacity: .65; }
.dsp-q__muted { opacity: .7; }
.dsp-q__err { color: var(--drc-red, #f87171); }
</style>
