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

      <!-- V0658 (v), item 5: laid out for desktop width. One grid: the organizations on the left, the records on the right,
           both on the same line; the firms with open books are picked inside the records panel (the narrow column of
           buttons beside it is gone) and the picked one is marked in the directory too. Below desktop width they stack. -->
      <div class="pfw-layout" data-testid="pf-layout">
        <div class="pfw-dir">
          <!-- V0657 (b), item 6: every listed organization, this registry's first, then the federation's -->
          <OrgDirectory :highlight="marked" />
        </div>

        <section class="pfw-panel" data-testid="pf-records" aria-labelledby="pfw-panel-title">
          <h2 id="pfw-panel-title" class="pfw-panel-title">{{ t('publicFirms.records', 'Work records') }}</h2>
          <p class="pfw-panel-sub">{{ t('publicFirms.recordsSub', 'The records-only feeds of the organizations that opened their books.') }}</p>

          <div v-if="loadingList" class="pfw-skel-row"><div v-for="n in 3" :key="n" class="pfw-skel"></div></div>

          <div v-else-if="listFailed && !firms.length" class="pfw-empty" data-testid="pf-list-failed">
            <ReadFailedNotice :retry="loadList" />
          </div>

          <div v-else-if="!firms.length" class="pfw-empty" data-testid="pf-empty">
            <EmptyReason kind="none-yet" :reason="t('publicFirms.empty', 'No organization has opted into public transparency yet. The switch lives in every org\'s settings.')" />
          </div>

          <template v-else>
            <div class="pfw-picker" role="group" :aria-label="t('publicFirms.pickerAria', 'Organizations with open books')">
              <button v-for="f in firms" :key="f.org_id" type="button" class="pfw-firm" :class="{ on: sel === f.org_id }"
                      :aria-pressed="sel === f.org_id ? 'true' : 'false'" :title="f.topic || f.description || undefined"
                      :data-testid="`pf-firm-${f.slug}`" @click="choose(f.org_id)">
                {{ f.name }}
              </button>
            </div>

            <section class="pfw-feed" data-testid="pf-feed">
              <div v-if="loadingFeed" class="pfw-skel-row"><div v-for="n in 4" :key="n" class="pfw-skel"></div></div>
              <template v-else-if="feed">
                <div class="pfw-feed-head">
                  <!-- V0662 (organizations item 2): the firm's hosted logo; the placeholder when there is none or it does not load -->
                  <span class="pfw-logo" data-testid="pf-logo" aria-hidden="true">
                    <img v-if="logoOf(feed.org_id)" :src="logoOf(feed.org_id) || undefined" alt="" loading="lazy" referrerpolicy="no-referrer"
                         @error="brokenLogo[feed.org_id] = true" />
                    <span v-else class="pfw-logo-mark">◈</span>
                  </span>
                  <h3 class="pfw-feed-name">{{ feed.name }}</h3>
                  <span class="pfw-feed-mode"><Icon name="mdi:earth" /> {{ t('publicFirms.recordsOnly', 'records only') }}</span>
                </div>
                <!-- V0662 (organizations item 2): the firm's own record, its agents' own work beside it (never in it), and
                     what counts. A record that could not be read says nothing (unknown is not zero). -->
                <div v-if="record && record.org_id === feed.org_id" class="pfw-record" data-testid="pf-firm-record">
                  <p class="pfw-record-line">{{ ownLine(record) }}</p>
                  <p v-if="agentsOf(record)" class="pfw-record-line pfw-record-member" data-testid="pf-member-work">
                    {{ agentsLine(record) }}
                  </p>
                  <p class="pfw-record-note" data-testid="pf-counting">{{ t('publicFirms.counting', 'A firm\'s own record counts the work it delivered or commissioned as the firm. Work its agents do as themselves is theirs, shown apart.') }}</p>
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
          </template>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import EmptyReason from '@/components/common/EmptyReason.vue'
import ViewAmbient from '@/components/common/ViewAmbient.vue'
import apiClient from '@/services/api/client'
import OrgDirectory from '@/components/organizations/OrgDirectory.vue'
import { safeLogo } from '@/services/orgMark'
import { agentsWork, agentsWorkIsNone, AGENTS_NONE_WHY } from '@/services/firmCounts'
import { useRoute } from 'vue-router'

const { t, tp } = useI18n()
// V0657 (b): #/firms?org=<slug> (an organization mark's link) marks that organization, and opens its records when public
const route = useRoute()
const highlight = computed(() => String(route.query.org || '') || null)

type Firm = { org_id: string; name: string; slug: string; description?: string | null; topic?: string | null; logo?: string | null }
/** GET /organizations/{id}/track-record, the fields this page reads (the counting rule is V0658 (v)'s, unchanged) */
type FirmRecord = { org_id: string; verified_jobs?: number; commissioned?: { orders?: number } | null; member_work?: { jobs?: number; commissioned?: number } | null }
type FeedRec = { seq: number; kind: string; at: string | null; body?: string; card?: any }
type Feed = { org_id: string; name: string; slug: string; topic?: string | null; records: FeedRec[]; next_before_seq: number | null }

const firms = ref<Firm[]>([])
const sel = ref<string>('')
// V0658 (v): the organization marked in the directory: on arrival the one the address names (an organization mark's
// link), else the firm whose records are open; once a person picks a firm here, the one they picked
const pickedHere = ref(false)
const pickedSlug = computed(() => firms.value.find((f) => f.org_id === sel.value)?.slug || null)
const marked = computed(() => (pickedHere.value ? pickedSlug.value : highlight.value || pickedSlug.value) || null)
const feed = ref<Feed | null>(null)
const loadingList = ref(true)
const loadingFeed = ref(false)
// §FESUITE (2026-10-05): a failed list read said "No organization has opted into public transparency yet." and a failed
// feed read "Pick a firm to watch its records." under the firm just picked; each says its read failed now, with Try
// again. A failed refresh of the list keeps it, and a feed answer for a firm no longer picked is dropped.
const listFailed = ref(false)
const feedFailed = ref(false)

// V0662 (organizations item 2): the logo this registry hosts (the list is its own, so its address is a path here, the
// rule FirmsLane uses); an image that does not load keeps the placeholder mark
const brokenLogo = reactive<Record<string, boolean>>({})
function logoOf(orgId: string): string | null {
  if (brokenLogo[orgId]) return null
  const f = firms.value.find((x) => x.org_id === orgId)
  return safeLogo({ logo: typeof f?.logo === 'string' ? f.logo : null, home: null })
}
// the picked firm's own record and its agents' own work, read beside the feed; a failed read leaves it out
const record = ref<FirmRecord | null>(null)
async function loadRecord(orgId: string) {
  try {
    const r = await apiClient.get(`/organizations/${orgId}/track-record`)
    if (sel.value !== orgId) return
    record.value = { ...(r.data || {}), org_id: orgId }
  } catch {
    if (sel.value === orgId) record.value = null
  }
}
const count = (n: unknown) => (typeof n === 'number' && Number.isFinite(n) ? n : 0)
function ownLine(r: FirmRecord): string {
  if (count(r.verified_jobs) === 0 && count(r.commissioned?.orders) === 0) {
    return t('publicFirms.ownNone', 'As the firm: none yet. Work counts here when an order is posted through the organization\'s work-order door, or won with a bid made as the firm.')
  }
  return tp('publicFirms.ownRecord', 'As the firm: {d} jobs delivered, {c} commissioned',
    { d: count(r.verified_jobs), c: count(r.commissioned?.orders) })
}
/** the agents' settled work as the registry states it (V0666: by the organization at the award); null when it does not
 *  (an unlisted firm), never a false zero */
function agentsOf(r: FirmRecord) { return agentsWork(r.member_work) }
function agentsLine(r: FirmRecord): string {
  const w = agentsOf(r)
  if (!w) return ''
  if (agentsWorkIsNone(w)) return `${t('publicFirms.agentsNone', 'By its agents: none yet.')} ${t('publicFirms.agentsWhy', AGENTS_NONE_WHY)}`
  return tp('publicFirms.agentsWork', 'By its agents: {d} jobs delivered, {c} commissioned', { d: w.jobs, c: w.commissioned })
}

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
    const wanted = highlight.value ? firms.value.find((f) => f.slug === highlight.value) : null
    if (wanted) pick(wanted.org_id)
    else if (firms.value.length && !sel.value) pick(firms.value[0].org_id)
  } catch {
    if (!firms.value.length) listFailed.value = true
  } finally { loadingList.value = false }
}
async function pick(orgId: string) {
  sel.value = orgId
  loadingFeed.value = true
  feedFailed.value = false
  if (feed.value?.org_id !== orgId) feed.value = null   // never another firm's records under this one
  if (record.value?.org_id !== orgId) record.value = null
  void loadRecord(orgId)
  try {
    const r = await apiClient.get(`/organizations/${orgId}/public-feed`)
    if (sel.value !== orgId) return
    feed.value = r.data
  } catch {
    if (sel.value !== orgId) return
    if (feed.value?.org_id !== orgId) feedFailed.value = true
  } finally { if (sel.value === orgId) loadingFeed.value = false }
}
function choose(orgId: string) {
  pickedHere.value = true
  void pick(orgId)
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
// the same link followed on this page (vue-router reuses the view): pick the organization's records when it has some
watch(highlight, (slug) => {
  pickedHere.value = false   // a link followed here names the organization to mark again
  const f = slug ? firms.value.find((x) => x.slug === slug) : null
  if (f && sel.value !== f.org_id) pick(f.org_id)
})
</script>

<style scoped>
.pfw { position: relative; min-height: 100%; }
.pfw-inner { position: relative; z-index: 1; max-width: 1360px; margin: 0 auto; padding: 28px 24px 60px; }
.pfw-head { margin-bottom: 22px; }
.pfw-title { font-size: 1.6rem; font-weight: 300; letter-spacing: .06em; margin: 0 0 6px; }
.pfw-sub { font-size: .85rem; opacity: .7; max-width: 68ch; margin: 0; }
/* V0658 (v), item 5: one grid. Stacked (the directory, then the records) until there is room for both side by side;
   from desktop width the records sit on the right, starting on the directory's line, never under a narrow column. */
.pfw-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 28px; align-items: start; }
@media (min-width: 1180px) {
  .pfw-layout { grid-template-columns: minmax(0, 1fr) minmax(380px, 460px); }
}
.pfw-dir { min-width: 0; }
.pfw-dir :deep(.odir) { margin: 0; }
.pfw-panel { min-width: 0; border: 1px solid var(--border-color, rgba(128,128,128,.2)); border-radius: 12px;
  padding: 16px 18px; background: rgba(128,128,128,.03); }
.pfw-panel-title { font-size: 1.1rem; font-weight: 400; letter-spacing: .04em; margin: 0 0 4px; }
.pfw-panel-sub { font-size: .8rem; color: rgba(148, 163, 184, 0.85); margin: 0 0 12px; }
.pfw-picker { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
.pfw-firm { padding: 7px 14px; border-radius: 999px; cursor: pointer; font-size: .82rem; font-weight: 600;
  border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: rgba(128,128,128,.06); color: inherit;
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pfw-firm.on { border-color: var(--nc-primary, #4fd8c4); background: rgba(79, 216, 196, .08); }
.pfw-feed { border-top: 1px solid var(--border-color, rgba(128,128,128,.2)); padding-top: 14px; min-height: 160px; }
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
/* V0662 (organizations item 2): the firm's logo and its record */
.pfw-logo { flex: 0 0 32px; width: 32px; height: 32px; border-radius: 8px; overflow: hidden; display: inline-flex;
  align-items: center; justify-content: center; background: rgba(148, 163, 184, 0.12); border: 1px solid rgba(148, 163, 184, 0.2); }
.pfw-logo img { width: 100%; height: 100%; object-fit: cover; }
.pfw-logo-mark { font-size: 0.85rem; color: rgba(148, 163, 184, 0.85); }
.pfw-feed-head .pfw-feed-name { flex: 1 1 auto; min-width: 0; }
.pfw-record { margin: 0 0 12px; padding: 10px 12px; border-radius: 10px; border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(148, 163, 184, 0.05); }
.pfw-record-line { margin: 0 0 4px; font-size: .84rem; }
.pfw-record-member { opacity: .85; }
.pfw-record-note { margin: 6px 0 0; font-size: .74rem; opacity: .65; max-width: 62ch; }
</style>
