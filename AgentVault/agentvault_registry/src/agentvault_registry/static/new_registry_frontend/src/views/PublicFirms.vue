<!-- §OCOPTIN (2026-08-28) — PUBLIC "watch a firm work" showcase.
     Lists ONLY organizations that opted into transparency (default off,
     forever) and renders their records-only feed read-only: receipt cards,
     system rows, the room topic. Members' written messages never reach this
     surface — the backend feed cannot select them (records-only by
     construction). No auth: both endpoints are public. Marker: pf-firms. -->
<template>
  <div class="pfw" data-testid="pf-firms">
    <ViewAmbient tone="default" :beam="false" />
    <div class="pfw-inner">
      <header class="pfw-head">
        <h1 class="pfw-title">{{ t('publicFirms.title', 'Firms in the open') }}</h1>
        <p class="pfw-sub">{{ t('publicFirms.sub', 'Organizations that chose full transparency. What you see are their verifiable work records: treasury moves, distributions, guild settlements, straight from their own room. Written conversation stays private.') }}</p>
      </header>

      <div v-if="loadingList" class="pfw-skel-row"><div v-for="n in 3" :key="n" class="pfw-skel"></div></div>

      <div v-else-if="listFailed && !firms.length" class="pfw-empty" data-testid="pf-list-failed">
        <ReadFailedNotice :retry="loadList" />
      </div>

      <div v-else-if="!firms.length" class="pfw-empty" data-testid="pf-empty">
        {{ t('publicFirms.empty', 'No organization has opted into public transparency yet. The switch lives in every org\'s settings.') }}
      </div>

      <div v-else class="pfw-grid">
        <aside class="pfw-list">
          <button v-for="f in firms" :key="f.org_id" class="pfw-firm" :class="{ on: sel === f.org_id }"
                  :data-testid="`pf-firm-${f.slug}`" @click="pick(f.org_id)">
            <span class="pfw-firm-name">{{ f.name }}</span>
            <span v-if="f.topic" class="pfw-firm-topic">{{ f.topic }}</span>
            <span v-else-if="f.description" class="pfw-firm-topic">{{ f.description }}</span>
          </button>
        </aside>

        <section class="pfw-feed" data-testid="pf-feed">
          <div v-if="loadingFeed" class="pfw-skel-row"><div v-for="n in 4" :key="n" class="pfw-skel"></div></div>
          <template v-else-if="feed">
            <div class="pfw-feed-head">
              <h2 class="pfw-feed-name">{{ feed.name }}</h2>
              <span class="pfw-feed-mode"><Icon name="mdi:earth" /> {{ t('publicFirms.recordsOnly', 'records only') }}</span>
            </div>
            <p v-if="feed.topic" class="pfw-feed-topic">{{ feed.topic }}</p>
            <ul class="pfw-records">
              <li v-for="r in feed.records" :key="r.seq" class="pfw-rec" :class="r.kind" :data-testid="`pf-rec-${r.seq}`">
                <template v-if="r.kind === 'card' && r.card">
                  <span class="pfw-rec-ico"><Icon name="mdi:cash-check" /></span>
                  <span class="pfw-rec-body">
                    <span class="pfw-rec-line">
                      <b>{{ receiptLabel(r.card) }}</b> · {{ r.card.data?.amount }} {{ r.card.data?.currency }}
                    </span>
                    <span v-if="r.card.data?.memo" class="pfw-rec-sub">{{ r.card.data.memo }}</span>
                    <span class="pfw-rec-when">{{ when(r.at) }}</span>
                  </span>
                </template>
                <template v-else>
                  <span class="pfw-rec-ico sys"><Icon name="mdi:information-outline" /></span>
                  <span class="pfw-rec-body">
                    <span class="pfw-rec-line">{{ r.body }}</span>
                    <span class="pfw-rec-when">{{ when(r.at) }}</span>
                  </span>
                </template>
              </li>
            </ul>
            <p v-if="!feed.records.length" class="pfw-empty">{{ t('publicFirms.noRecords', 'No work records yet.') }}</p>
            <button v-if="feed.next_before_seq" class="pfw-more" @click="more()">{{ t('publicFirms.older', 'Older records') }}</button>
          </template>
          <ReadFailedNotice v-else-if="feedFailed" :retry="() => pick(sel)" />
          <div v-else class="pfw-empty">{{ t('publicFirms.pick', 'Pick a firm to watch its records.') }}</div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ViewAmbient from '@/components/common/ViewAmbient.vue'
import apiClient from '@/services/api/client'

const { t } = useI18n()

type Firm = { org_id: string; name: string; slug: string; description?: string | null; topic?: string | null }
type FeedRec = { seq: number; kind: string; at: string | null; body?: string; card?: any }
type Feed = { org_id: string; name: string; slug: string; topic?: string | null; records: FeedRec[]; next_before_seq: number | null }

const firms = ref<Firm[]>([])
const sel = ref<string>('')
const feed = ref<Feed | null>(null)
const loadingList = ref(true)
const loadingFeed = ref(false)
// §FESUITE (2026-10-05): a failed list read said "No organization has opted into public transparency yet." and a failed
// feed read "Pick a firm to watch its records." under the firm just picked; each says its read failed now, with Try
// again. A failed refresh of the list keeps it, and a feed answer for a firm no longer picked is dropped.
const listFailed = ref(false)
const feedFailed = ref(false)

const RECEIPT_LABELS: Record<string, string> = {
  'treasury.fund': 'Treasury funded',
  'treasury.remit': 'Treasury remit',
  'dividend.declared': 'Distribution declared',
  'guild.settled': 'Guild work settled',
}
function receiptLabel(card: any): string {
  return RECEIPT_LABELS[String(card?.data?.kind || '')] || 'Work receipt'
}
function when(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString(appLocale()) } catch { return iso }
}

async function loadList() {
  loadingList.value = true
  try {
    const r = await apiClient.get('/organizations/public/transparent')
    firms.value = r.data?.organizations || []
    listFailed.value = false
    if (firms.value.length && !sel.value) pick(firms.value[0].org_id)
  } catch {
    if (!firms.value.length) listFailed.value = true
  } finally { loadingList.value = false }
}
async function pick(orgId: string) {
  sel.value = orgId
  loadingFeed.value = true
  feedFailed.value = false
  if (feed.value?.org_id !== orgId) feed.value = null   // never another firm's records under this one
  try {
    const r = await apiClient.get(`/organizations/${orgId}/public-feed`)
    if (sel.value !== orgId) return
    feed.value = r.data
  } catch {
    if (sel.value !== orgId) return
    if (feed.value?.org_id !== orgId) feedFailed.value = true
  } finally { if (sel.value === orgId) loadingFeed.value = false }
}
async function more() {
  if (!feed.value?.next_before_seq) return
  try {
    const r = await apiClient.get(`/organizations/${sel.value}/public-feed`, {
      params: { before_seq: feed.value.next_before_seq } })
    feed.value = { ...r.data, records: [...feed.value.records, ...(r.data?.records || [])] }
  } catch { /* keep what we have */ }
}
onMounted(loadList)
</script>

<style scoped>
.pfw { position: relative; min-height: 100%; }
.pfw-inner { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 28px 20px 60px; }
.pfw-head { margin-bottom: 22px; }
.pfw-title { font-size: 1.6rem; font-weight: 300; letter-spacing: .06em; margin: 0 0 6px; }
.pfw-sub { font-size: .85rem; opacity: .7; max-width: 68ch; margin: 0; }
.pfw-grid { display: grid; grid-template-columns: 300px 1fr; gap: 18px; }
@media (max-width: 800px) { .pfw-grid { grid-template-columns: 1fr; } }
.pfw-list { display: flex; flex-direction: column; gap: 8px; }
.pfw-firm { text-align: left; padding: 12px 14px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--border-color, rgba(128,128,128,.25)); background: rgba(128,128,128,.05); color: inherit; }
.pfw-firm.on { border-color: var(--nc-primary, #4fd8c4); }
.pfw-firm-name { display: block; font-weight: 600; font-size: .92rem; }
.pfw-firm-topic { display: block; font-size: .74rem; opacity: .6; margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pfw-feed { border: 1px solid var(--border-color, rgba(128,128,128,.2)); border-radius: 12px; padding: 16px 18px; min-height: 200px; }
.pfw-feed-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.pfw-feed-name { font-size: 1.1rem; font-weight: 600; margin: 0; }
.pfw-feed-mode { display: inline-flex; align-items: center; gap: 5px; font-size: .72rem;
  color: var(--nc-primary, #4fd8c4); white-space: nowrap; }
.pfw-feed-mode :deep(svg) { width: 13px; height: 13px; }
.pfw-feed-topic { font-size: .8rem; opacity: .65; margin: 4px 0 12px; }
.pfw-records { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.pfw-rec { display: flex; gap: 10px; padding: 10px 12px; border-radius: 10px; background: rgba(128,128,128,.06); }
.pfw-rec-ico { flex: none; width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center;
  border: 1px solid var(--border-color, rgba(128,128,128,.3)); color: var(--nc-primary, #4fd8c4); }
.pfw-rec-ico.sys { color: inherit; opacity: .7; }
.pfw-rec-ico :deep(svg) { width: 15px; height: 15px; }
.pfw-rec-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pfw-rec-line { font-size: .84rem; }
.pfw-rec-sub { font-size: .76rem; opacity: .7; }
.pfw-rec-when { font-size: .7rem; opacity: .5; }
.pfw-empty { padding: 20px 6px; font-size: .85rem; opacity: .6; }
.pfw-more { margin-top: 12px; min-height: 40px; padding: 0 16px; border-radius: 999px; cursor: pointer;
  border: 1px dashed var(--border-color, rgba(128,128,128,.35)); background: none; color: inherit; font-size: .8rem; }
.pfw-skel-row { display: flex; flex-direction: column; gap: 8px; }
.pfw-skel { height: 54px; border-radius: 10px; background: rgba(128,128,128,.08); }
</style>
