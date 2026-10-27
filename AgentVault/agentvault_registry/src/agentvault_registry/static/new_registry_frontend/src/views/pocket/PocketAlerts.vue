<!-- POCKET · Alerts sheet (2026-07-08) — the EXISTING broadcast/notification inbox
     (GET /notifications/unread + POST /notifications/{id}/read, dev JWT). No new backend. -->
<template>
  <transition name="pk-sheet">
    <div v-if="open" class="pa2-scrim" @click.self="$emit('close')">
      <div ref="trapEl" class="pa2-sheet" role="dialog" aria-modal="true" :aria-label="t('pocket.alerts.title', 'Alerts')">
        <div class="pa2-grip" aria-hidden="true"></div>
        <h2 class="pa2-title"><Icon name="mdi:bell" /> {{ t('pocket.alerts.title', 'Alerts') }} <span v-if="items.length" class="pa2-count">{{ items.length }}</span></h2>

        <!-- §POCKETBRIDGE4 WS-H — the price-alert RULES live here too (same synced
             pref Trade writes): fired ones show their crossing, X removes a rule. -->
        <div v-if="paRules.length" class="pa2-pa" data-testid="pa2-price-alerts">
          <div class="pa2-pa-lab"><Icon name="mdi:bell-ring" /> {{ t('pocket.alerts.priceAlerts', 'Price alerts') }}</div>
          <div v-for="r in paRules" :key="r.id" class="pa2-pa-row" :class="{ fired: !!r.fired_at }">
            <span class="pa2-pa-txt">
              ${{ r.symbol }} ±{{ r.pct }}% <small>@{{ Number(r.baseline).toFixed(2) }}</small>
              <b v-if="r.fired_at">&nbsp;{{ r.fired_direction === 'up' ? '▲' : '▼' }} {{ t('pocket.alerts.firedAt', 'fired at') }} {{ Number(r.fired_price).toFixed(2) }} · {{ when(r.fired_at) }}</b>
              <small v-else> · {{ t('pocket.alerts.armed', 'armed') }}{{ r.venue ? ' · ' + r.venue + ' ' + t('pocket.alerts.watchedWhileOpen', '(watched while the app is open)') : '' }}</small>
            </span>
            <button class="pa2-read" :disabled="paBusy" @click="removeRule(r)" :aria-label="tp('pocket.alerts.removeAlert', 'Remove alert for {sym}', { sym: r.symbol })"><Icon name="mdi:close" /></button>
          </div>
          <p v-if="paSyncNote" class="pa2-pa-note">{{ paSyncNote }}</p>
        </div>

        <!-- §POCKETBRIDGE5 W-B — the TYPED feed (mig 0139). It has carried
             type_key + click since §NOTIFV2; this is its first consumer. A row
             is a DOOR when its type has a pocket surface — tapping marks it
             read and lands there. Types with no door say nothing false: the
             tap just marks them read. -->
        <div v-if="feedAvailable && feed.length" class="pa2-feed" data-testid="pa2-feed">
          <div class="pa2-pa-lab pa2-feed-lab">
            <Icon name="mdi:bell-ring" /> {{ t('pocket.alerts.forYou', 'For you') }}
            <span v-if="feedUnread" class="pa2-count">{{ feedUnread }}</span>
            <button v-if="feedUnread" class="pa2-readall" :disabled="feedBusy" data-testid="pa2-feed-readall" @click="readAllFeed">{{ t('pocket.alerts.readAll', 'read all') }}</button>
          </div>
          <ul class="pa2-list">
            <li v-for="e in feed" :key="'f' + e.id" class="pa2-row" :class="['sev-' + (e.severity || 'info'), { 'is-read': e.read }]">
              <button class="pa2-frow" :data-testid="'pa2-feed-row-' + e.id" @click="openEntry(e)"
                      :aria-label="doorFor(e) ? tp('pocket.alerts.openEntry', 'Open: {title}', { title: e.title }) : tp('pocket.alerts.markReadEntry', 'Mark read: {title}', { title: e.title })">
                <span class="pa2-head">{{ e.title }}
                  <small class="pa2-type">{{ e.category || e.type_key }}</small>
                </span>
                <span v-if="e.body" class="pa2-text">{{ e.body.slice(0, 200) }}</span>
                <span class="pa2-when">{{ when(e.created_at || undefined) }}
                  <b v-if="doorFor(e)" class="pa2-door-hint">{{ t('pocket.alerts.open', 'open') }} <Icon name="mdi:arrow-right" /></b>
                </span>
              </button>
            </li>
          </ul>
        </div>

        <div v-if="loading" class="pa2-list"><div v-for="n in 3" :key="n" class="pa2-skel"></div></div>
        <ul v-else-if="items.length" class="pa2-list">
          <li v-for="n in items" :key="n.id" class="pa2-row" :class="'sev-' + (n.severity || 'info')">
            <div class="pa2-body">
              <div class="pa2-head">{{ n.title || n.subject || t('pocket.alerts.announcement', 'Announcement') }}</div>
              <div class="pa2-text">{{ (n.message || n.body || '').slice(0, 200) }}</div>
              <div class="pa2-when">{{ when(n.created_at || n.published_at) }}</div>
            </div>
            <button class="pa2-read" :disabled="busyId === n.id" @click="markRead(n)" :aria-label="tp('pocket.alerts.dismissAlert', 'Dismiss {title}', { title: n.title || t('pocket.alerts.alertWord', 'alert') })">
              <Icon name="mdi:check-circle" />
            </button>
          </li>
        </ul>
        <div v-else-if="itemsFailed || (feedFailed && !feed.length)" class="pa2-empty" data-testid="pa2-read-failed">
          <ReadFailedNotice :retry="retryAll" />
        </div>
        <div v-else-if="!feed.length" class="pa2-empty">
          <Icon name="mdi:bell" class="pa2-empty-ico" />
          <p>{{ t('pocket.alerts.empty', 'All caught up. Your notifications and network announcements land here.') }}</p>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, watch, computed } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

// §POCKETBRIDGE5 W-D — the dialog role was already declared; the trap makes it TRUE:
// focus enters on open, Tab cycles inside, and RETURNS to the opener on close.
const trapEl = ref<HTMLElement | null>(null)
const props = defineProps<{ open: boolean }>()
useFocusTrap(trapEl, { activeWhen: computed(() => props.open) })
const emit = defineEmits<{ (e: 'close'): void; (e: 'count', n: number): void }>()

const items = ref<any[]>([])
const loading = ref(false)
// §FESUITE (2026-10-05): a failed read said "All caught up" (the announcements read) or hid the feed as if it were off;
// each read says it failed now, with Try again, and a failed refresh keeps what was shown (the sheet reads on every open)
const itemsFailed = ref(false)
const feedFailed = ref(false)
const busyId = ref<string | number | null>(null)

const when = (s?: string) => { if (!s) return ''; try { return new Date(s).toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return '' } }

// §POCKETBRIDGE4 WS-H — price-alert rules (the synced pref the Trade tab and
// the server watcher share). Reading fails soft; removing reports a failed sync.
import { getPref, putPref, type PriceAlertsValue, type PriceAlertRule } from '@/services/api/pocketPrefs'
const paRules = ref<PriceAlertRule[]>([])
const paBusy = ref(false)
const paSyncNote = ref('')
async function loadPaRules() {
  const { value } = await getPref<PriceAlertsValue>('pocket.price_alerts')
  paRules.value = value?.rules || []
}
async function removeRule(r: PriceAlertRule) {
  paBusy.value = true
  try {
    paRules.value = paRules.value.filter((x) => x.id !== r.id)
    const okd = await putPref('pocket.price_alerts', { rules: paRules.value })
    paSyncNote.value = okd ? '' : t('pocket.alerts.syncFailed', 'removed on this device only (sync failed)')
  } finally { paBusy.value = false }
}

watch(() => props.open, (o) => { if (o) void loadPaRules() })

/* §POCKETBRIDGE5 W-B — the typed feed. Deep links: a row with a pocket door
 * navigates (marking itself read on the way); one without simply marks read.
 * The mapping is pure + unit-tested (services/notificationDoors). */
import { useRouter } from 'vue-router'
import { doorForNotification, type NotifDoorInput } from '@/services/notificationDoors'
const router = useRouter()
interface FeedEntry { id: number; type_key: string; category?: string | null; severity?: string | null; title: string; body?: string | null; click?: string | null; created_at?: string | null; read: boolean }
const feed = ref<FeedEntry[]>([])
const feedUnread = ref(0)
const feedAvailable = ref(true)
const feedBusy = ref(false)
const doorFor = (e: NotifDoorInput) => doorForNotification(e)
async function loadFeed() {
  try {
    const { data } = await apiClient.get('/notifications/feed', { params: { limit: 50 } })
    feedAvailable.value = data?.available !== false
    feed.value = data?.entries || []
    feedUnread.value = Number(data?.unread_count || 0)
    feedFailed.value = false
  } catch { feedFailed.value = true }   // the feed is not off: its read failed, and what it showed stays
  emitCount()
}
async function openEntry(e: FeedEntry) {
  if (!e.read) {
    e.read = true
    feedUnread.value = Math.max(0, feedUnread.value - 1)
    emitCount()
    apiClient.post(`/notifications/feed/${e.id}/read`).catch(() => { /* read-state is best effort */ })
  }
  const door = doorForNotification(e)
  if (door) {
    emit('close')
    router.push({ path: door.path, ...(door.query ? { query: door.query } : {}) }).catch(() => {})
  }
  try { (navigator as any).vibrate?.(6) } catch { /* haptics optional */ }
}
async function readAllFeed() {
  feedBusy.value = true
  try {
    await apiClient.post('/notifications/feed/read-all')
    feed.value = feed.value.map((e) => ({ ...e, read: true }))
    feedUnread.value = 0
    emitCount()
  } catch { /* the counts stay honest */ } finally { feedBusy.value = false }
}

function emitCount() { emit('count', items.value.length + feedUnread.value) }
function retryAll() { void load(); void loadFeed() }

async function load() {
  loading.value = true
  try {
    const { data } = await apiClient.get('/notifications/unread')
    items.value = data?.notifications || data?.broadcasts || (Array.isArray(data) ? data : [])
    itemsFailed.value = false
  } catch { itemsFailed.value = true }   // never "All caught up" over a read that failed
  finally { loading.value = false }
  emitCount()
}

async function markRead(n: any) {
  busyId.value = n.id
  try {
    await apiClient.post(`/notifications/${n.id}/read`)
    items.value = items.value.filter((x) => x.id !== n.id)
    emitCount()
    try { (navigator as any).vibrate?.(6) } catch {}
  } catch { /* leave it */ }
  finally { busyId.value = null }
}

watch(() => props.open, (o) => { if (o) { load(); void loadFeed() } })
defineExpose({ load })
</script>

<style scoped>
/* §POCKETBRIDGE4 — price-alert rules block */
.pa2-pa { margin: 0.2rem 0 0.6rem; border: 1px solid rgba(251,191,36,0.25); border-radius: 12px; padding: 0.45rem 0.6rem; }
.pa2-pa-lab { display: flex; align-items: center; gap: 0.3rem; font-size: 0.66rem; font-weight: 800; letter-spacing: 0.05em; text-transform: uppercase; color: #fbbf24; margin-bottom: 0.3rem; }
.pa2-pa-lab :deep(svg) { width: 0.85rem; height: 0.85rem; }
.pa2-pa-row { display: flex; align-items: center; gap: 0.4rem; padding: 0.22rem 0; font-size: 0.76rem; font-variant-numeric: tabular-nums; }
.pa2-pa-row.fired .pa2-pa-txt b { color: #34d399; }
.pa2-pa-txt { flex: 1 1 auto; min-width: 0; }
.pa2-pa-txt small { opacity: 0.55; }
.pa2-pa-note { font-size: 0.64rem; color: #fbbf24; margin: 0.2rem 0 0; }
/* §POCKETBRIDGE5 W-B — typed feed rows are DOORS */
.pa2-feed { margin: 0 0 0.6rem; }
.pa2-feed-lab { color: var(--nc-primary, #00d4ff); }
.pa2-readall { margin-left: auto; background: rgba(0,212,255,0.08); border: 1px solid rgba(0,212,255,0.25); border-radius: 8px; padding: 0.25rem 0.55rem; min-height: 32px; color: var(--nc-primary, #00d4ff); font-size: 0.64rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pa2-frow { display: flex; flex-direction: column; gap: 0.15rem; align-items: flex-start; width: 100%; min-height: 44px; background: none; border: none; padding: 0; margin: 0; color: inherit; font: inherit; text-align: left; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pa2-row.is-read { opacity: 0.55; }
.pa2-type { margin-left: 0.35rem; font-size: 0.58rem; font-weight: 600; opacity: 0.5; text-transform: lowercase; }
.pa2-door-hint { display: inline-flex; align-items: center; gap: 0.15rem; margin-left: 0.4rem; color: var(--nc-primary, #00d4ff); font-weight: 700; }
.pa2-door-hint :deep(svg) { width: 0.7rem; height: 0.7rem; }
.pa2-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px); display: flex; align-items: flex-end; }
.pa2-sheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09);
  border-radius: 22px 22px 0 0; padding: 0.8rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom, 0px));
  box-shadow: 0 -20px 50px rgba(0,0,0,0.5); max-height: 85dvh; overflow-y: auto; }
.pa2-grip { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.1rem auto 0.9rem; }
.pa2-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.1rem; margin: 0 0 0.9rem; }
.pa2-title :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }
.pa2-count { font-size: 0.68rem; font-weight: 700; color: var(--nc-primary, #00d4ff); background: rgba(0,212,255,0.09);
  border: 1px solid rgba(0,212,255,0.24); border-radius: 7px; padding: 0.1rem 0.45rem; }
.pa2-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.pa2-row { display: flex; align-items: flex-start; gap: 0.6rem; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07); border-left-width: 3px; border-radius: 13px; padding: 0.7rem 0.8rem; }
.sev-critical, .sev-warning { border-left-color: rgba(251,191,36,0.6); }
.sev-info { border-left-color: rgba(0,212,255,0.4); }
.pa2-body { flex: 1 1 auto; min-width: 0; }
.pa2-head { font-size: 0.88rem; font-weight: 650; }
.pa2-text { font-size: 0.78rem; opacity: 0.7; margin-top: 0.15rem; line-height: 1.4; }
.pa2-when { font-size: 0.66rem; opacity: 0.45; margin-top: 0.25rem; font-variant-numeric: tabular-nums; }
.pa2-read { flex: 0 0 auto; background: rgba(16,185,129,0.08); border: 1px solid rgba(16,185,129,0.25); border-radius: 10px;
  padding: 0.4rem; color: #34d399; cursor: pointer; min-width: 38px; min-height: 38px; display: grid; place-items: center; -webkit-tap-highlight-color: transparent; }
.pa2-read :deep(svg) { width: 1rem; height: 1rem; }
.pa2-empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2rem 1rem; opacity: 0.55; text-align: center; }
.pa2-empty-ico { width: 2rem; height: 2rem; }
.pa2-empty p { margin: 0; font-size: 0.84rem; }
.pa2-skel { height: 3.4rem; border-radius: 13px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pa2-shim 1.3s ease-in-out infinite; }
@keyframes pa2-shim { to { background-position: -200% 0; } }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-active .pa2-sheet, .pk-sheet-leave-active .pa2-sheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
.pk-sheet-enter-from .pa2-sheet, .pk-sheet-leave-to .pa2-sheet { transform: translateY(100%); }
@media (prefers-reduced-motion: reduce) { .pa2-skel { animation: none; } .pk-sheet-enter-active .pa2-sheet, .pk-sheet-leave-active .pa2-sheet { transition: none; } }
</style>
