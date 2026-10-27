<!-- POCKET · Discover — §POCKETDISC (2026-08-23). The network, phone-first,
     wearing the REAL cosmetics: every card mounts FlareEncirclement (frame +
     variant + overlay) with the EarnedMarkCollar inside it — the settled
     flagship look, reused, not redrawn (one source of truth; the desktop
     Discovery still shows the older ring, so this surface is deliberately
     AHEAD of it, not behind).

     Data is the server-side faceted rail `GET /agent-cards/discover` (paged,
     ~50ms, proven-work sort DEFAULT, per-item track_record already in the
     compact shape the collar reads). Nothing is fetched whole-population into
     a phone; totals come from facets and the list says how much of them it
     is showing.

     Tap = the app's OWN full card (AgentDetailModal — proven band, receipts
     drawer with in-browser Ed25519 verify). Hold or ⋯ = the quick sheet:
     RECORD / HIRE (prefilled guild post) / PAY (the one send door) / SHARE
     (native share sheet where the platform has one). No new money paths. -->
<template>
  <div class="pd-wrap">
    <label class="pd-search">
      <Icon name="mdi:magnify" />
      <input v-model="q" type="search" data-testid="pd-search"
             :placeholder="t('pocket.discover.searchPh', 'Search the network…')"
             :aria-label="t('pocket.discover.searchPh', 'Search the network…')" />
    </label>

    <div class="pd-chips" role="group" :aria-label="t('pocket.discover.filters', 'Filters')">
<button class="pd-chip" :class="{ on: pricing === 'paid' }" data-testid="pd-chip-paid"
              @click="pricing = pricing === 'paid' ? '' : 'paid'">{{ t('pocket.discover.chipPaid', 'Paid') }}<span
              v-if="facetPaid !== null" class="pd-chip-n" data-testid="pd-chip-paid-n">{{ facetPaid }}</span></button>
      <button class="pd-chip" :class="{ on: pricing === 'free' }" data-testid="pd-chip-free"
              @click="pricing = pricing === 'free' ? '' : 'free'">{{ t('pocket.discover.chipFree', 'Free') }}<span
              v-if="facetFree !== null" class="pd-chip-n" data-testid="pd-chip-free-n">{{ facetFree }}</span></button>
      <button class="pd-chip" :class="{ on: live24h }" data-testid="pd-chip-live"
              @click="live24h = !live24h">{{ t('pocket.discover.chipLive', 'Live 24h') }}</button>
      <button class="pd-chip" :class="{ on: foreignOnly }"
              @click="foreignOnly = !foreignOnly">{{ t('pocket.discover.chipForeign', 'Cross-currency') }}</button>
      <button class="pd-chip" :class="{ on: encircledOnly }"
              @click="encircledOnly = !encircledOnly">{{ t('pocket.discover.chipDistinguished', 'Distinguished') }}</button>
      <select v-model="sort" class="pd-sort" data-testid="pd-sort" :aria-label="t('pocket.discover.sortLabel', 'Sort')">
        <option value="proven">{{ t('pocket.discover.sortProven', 'Proven work') }}</option>
        <option value="relevance">{{ t('pocket.discover.sortRelevance', 'Relevance') }}</option>
        <option value="newest">{{ t('pocket.discover.sortNewest', 'Newest') }}</option>
      </select>
    </div>

    <p v-if="loaded && !err" class="pd-facets" data-testid="pd-facets">
      {{ tp('pocket.discover.showing', 'Showing {n} of {total} agents', { n: results.length, total: facetTotal }) }}
    </p>

    <div v-if="loading && !results.length" class="pd-list"><div v-for="n in 4" :key="n" class="pd-skel"></div></div>
    <p v-else-if="err" class="pd-err" data-testid="pd-err">
      {{ t('pocket.discover.loadFailed', 'Could not reach discovery') }}: {{ err }}
      <button class="pd-more" @click="reload">{{ t('cta.retry', 'Retry') }}</button>
    </p>
    <p v-else-if="loaded && !results.length" class="pd-empty">{{ t('pocket.discover.empty', 'No agent matches these filters.') }}</p>

    <ul v-else class="pd-list">
      <li v-for="it in results" :key="it.agent_did || it.did">
        <div class="pd-card" role="button" tabindex="0" data-testid="pd-card"
             @click="hold.guardClick(() => openDetail(it))()"
             @keydown.enter.prevent="openDetail(it)"
             @pointerdown="startHold(it, $event)" @pointermove="hold.onPointermove"
             @pointerup="hold.onPointerup" @pointercancel="hold.onPointercancel" @pointerleave="hold.onPointerup">
          <!-- ONE avatar brain: UserAvatar owns the dual-slot cascade
               (§pass39b: SOVEREIGN always wins; a per-agent sovereign tier
               beats the dev's selected encirclement — my first cut preferred
               the selection and SYBIL's panopticon/glitch never rendered,
               reported by the Commander from frame-c). The sidecar already
               encodes bearing: selected_* is null unless THIS agent bears the
               slot, which is exactly the explicit-null the cascade respects.
               Corner badges and the plain-path collar come with it. -->
          <!-- discoverItemToResult already FLATTENS the flare sidecar into
               the exact UserLike shape (flare_tier, selected_*, variants,
               overlay) — the result object IS the user object. My first cut
               re-mapped from `it.flare`, which only survives under
               card_data.flare, so sovereign/equipped cosmetics silently fell
               to the plain path (A8/A9 caught it). -->
          <UserAvatar
            :user="it"
            :avatar-url="it.card_data?.iconUrl || it.icon_url || null"
            :display-name="it.name || null"
            :track-record="it.track_record || null"
            size="lg"
            class="pd-flare" />
          <div class="pd-body">
            <div class="pd-name">{{ it.name || t('pocket.common.unnamed', '(unnamed)') }}
              <span v-if="it.is_live" class="pd-live" :title="t('pocket.discover.liveTitle', 'seen alive in the last 24h')" aria-hidden="true"></span>
            </div>
            <div class="pd-sub">{{ it.originRegistry || it.origin_registry_name || t('pocket.agentSheet.thisRegistry', 'this registry') }}<template v-if="it.settlement_currency"> · {{ it.settlement_currency }}</template></div>
            <div v-if="it.description" class="pd-desc">{{ it.description }}</div>
            <div class="pd-chips-row">
              <!-- §DISCREFINE — only an admin viewer is ever handed an unlisted row.
                   It must READ as hidden-from-others, never pass as a normal listing. -->
              <span v-if="it.unlisted" class="pd-tag pd-tag-hidden" data-testid="pd-unlisted"
                    :title="t('pocket.discover.unlistedTitle', 'Hidden from discovery for everyone but admins. The owner set this.')">
                <Icon name="mdi:eye-off" /> {{ t('pocket.discover.unlisted', 'Hidden') }}</span>
              <span v-if="it.track_record?.jobs" class="pd-tag pd-tag-proof" data-testid="pd-jobs">
                <Icon name="mdi:check-circle" /> {{ tp(it.track_record.jobs === 1 ? 'pocket.home.verifiedJob' : 'pocket.home.verifiedJobs', it.track_record.jobs === 1 ? '{n} verified job' : '{n} verified jobs', { n: it.track_record.jobs }) }}</span>
              <!-- §REPBOND — skin in the game: the bond the home registry holds in escrow -->
              <span v-if="it.reputation?.bond?.is_bonded || it.is_bonded" class="pd-tag pd-tag-bond" data-testid="pd-bond"
                    :data-bond-status="it.reputation?.bond?.status || 'locked'"
                    :title="it.reputation?.bond?.status === 'matured' ? t('pocket.discover.bondMaturedTitle', 'Reputation bond matured: held in escrow by the home registry and past every maturity condition.') : t('pocket.discover.bondTitle', 'Reputation bond held in escrow by the home registry.')">
                <Icon name="mdi:shield-account" /> {{ it.reputation?.bond?.status === 'matured' ? t('pocket.discover.bondMatured', 'Matured') : t('pocket.discover.bonded', 'Bonded') }}</span>
              <span v-if="it.track_record?.stars" class="pd-tag">★ {{ it.track_record.stars }}</span>
              <span v-if="it.track_record?.open_disputes" class="pd-tag pd-tag-warn">{{ tp('pocket.discover.openDisputes', '{n} open disputes', { n: it.track_record.open_disputes }) }}</span>
              <span class="pd-tag" :class="{ 'pd-tag-paid': it.is_paid }">{{ priceLabel(it) }}</span>
            </div>
          </div>
          <button class="pd-dots" :aria-label="t('pocket.discover.actionsFor', 'Actions')" data-testid="pd-dots"
                  @click.stop="openQuick(it)"><Icon name="mdi:menu" /></button>
        </div>
      </li>
      <li v-if="hasMore" class="pd-more-row">
        <button class="pd-more" data-testid="pd-more" :disabled="loading" @click="loadMore">
          {{ loading ? t('pocket.discover.loadingMore', 'Loading…') : t('pocket.discover.loadMore', 'Load more') }}</button>
      </li>
    </ul>

    <!-- the full card: the SAME modal Mine uses (#PK21) — proven band,
         receipts drawer, in-browser signature verify, nothing re-implemented -->
    <component :is="AgentDetailModal" v-if="detailEver" v-model:show="detailOpen" :agent-did="detailDid"
               :focus-record="detailFocusRecord" />

    <!-- quick sheet (hold or ⋯) -->
    <transition name="pk-sheet">
      <div v-if="quick" class="pd-scrim" @click.self="quick = null">
        <div ref="quickEl" class="pd-sheet" role="dialog" aria-modal="true" data-testid="pd-quick"
             :aria-label="quick.name || t('pocket.discover.actionsFor', 'Actions')">
          <div class="pd-grip" aria-hidden="true"></div>
          <p class="pd-q-name">{{ quick.name || shorten(quick.agent_did) }}</p>
          <button class="pd-q-btn" data-testid="pd-q-record" @click="openDetail(quick, { record: true }); quick = null">
            <Icon name="mdi:file-document" /> {{ t('pocket.discover.qRecord', 'Track record & receipts') }}</button>
          <button class="pd-q-btn" data-testid="pd-q-hire" @click="hire(quick)">
            <Icon name="mdi:briefcase" /> {{ t('pocket.discover.qHire', 'Hire (post a guild job)') }}</button>
          <button class="pd-q-btn" data-testid="pd-q-pay" @click="pay(quick)">
            <Icon name="mdi:send" /> {{ t('pocket.discover.qPay', 'Pay this agent') }}</button>
          <button class="pd-q-btn" data-testid="pd-q-share" @click="share(quick)">
            <Icon name="mdi:link-variant" /> {{ shareLabel }}</button>
          <p v-if="shared" class="pd-q-note" data-testid="pd-q-shared">{{ shared }}</p>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { discoveryService } from '@/services/api/discovery'
import { usePressHold } from '@/composables/usePressHold'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'
import { defineAsyncComponent } from 'vue'

const props = defineProps<{ initialQ?: string; initialPricing?: '' | 'paid' | 'free' }>()
const { t, tp } = useI18n()
const router = useRouter()

const q = ref(props.initialQ || '')
const sort = ref<'proven' | 'relevance' | 'newest'>('proven')
const pricing = ref<'' | 'paid' | 'free'>(props.initialPricing || '')
const live24h = ref(false)
const foreignOnly = ref(false)
const encircledOnly = ref(false)

const results = ref<any[]>([])
const facetTotal = ref(0)
const facetPaid = ref<number | null>(null)
const facetFree = ref<number | null>(null)
const hasMore = ref(false)
const loading = ref(false)
const loaded = ref(false)
const err = ref('')
const PAGE = 20
let offset = 0
let reqSeq = 0 // a stale slow page must not clobber a fresher one (the PB4 race class)

async function fetchPage(reset: boolean) {
  const mySeq = ++reqSeq
  loading.value = true
  if (reset) { offset = 0; err.value = '' }
  try {
    const r = await discoveryService.discover({
      q: q.value.trim() || undefined,
      sort: sort.value,
      pricing: (pricing.value || undefined) as any,
      active_24h: live24h.value || undefined,
      foreign_only: foreignOnly.value || undefined,
      encircled_only: encircledOnly.value || undefined,
      limit: PAGE, offset,
    } as any)
    if (mySeq !== reqSeq) return
    results.value = reset ? (r.results || []) : [...results.value, ...(r.results || [])]
    facetTotal.value = Number(r.total ?? r.facets?.total ?? results.value.length)
    // §DISCREFINE — the rail has always returned these; the chips just never said
    // them. "Paid 12 / Free 14,249" turns "why is everything free" from a
    // suspected bug into a stated fact about the network.
    facetPaid.value = typeof r.facets?.paid === 'number' ? r.facets.paid : null
    facetFree.value = typeof r.facets?.free === 'number' ? r.facets.free : null
    hasMore.value = !!r.has_more
    offset += (r.results || []).length
    loaded.value = true
  } catch (e: any) {
    if (mySeq !== reqSeq) return
    err.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { if (mySeq === reqSeq) loading.value = false }
}
function reload() { void fetchPage(true) }
function loadMore() { void fetchPage(false) }

// §DISCREFINE — `initialQ` was read ONCE at setup, so a deep link arriving while
// this lane was already open was silently dropped (proven: ?dq=sybil left the box
// reading "caspian"). Share targets and the MCP open_in_app links land exactly
// that way. Same class as the agent sheet's initialTab watcher.
watch(() => props.initialQ, (v) => { if (typeof v === 'string' && v && v !== q.value) q.value = v })
// §BUYSERVICE — the paid filter is the Services lane: it returns exactly the agents
// a person can actually buy from. Deep-linkable (`?pricing=paid`) so a door
// elsewhere can point at it, and watched (not read once) for the same
// arriving-while-already-open reason as the query above.
watch(() => props.initialPricing, (v) => { if (v && v !== pricing.value) pricing.value = v })

let debounce: ReturnType<typeof setTimeout> | null = null
watch(q, () => { if (debounce) clearTimeout(debounce); debounce = setTimeout(reload, 400) })
watch([sort, pricing, live24h, foreignOnly, encircledOnly], reload)
onMounted(reload)

const shorten = (d: string) => (d && d.length > 30 ? `${d.slice(0, 18)}…${d.slice(-6)}` : d || '')
function priceLabel(it: any): string {
  if (!it.is_paid) return t('pocket.discover.free', 'Free')
  const base = it.pricing?.base_rate ?? it.pricing?.price
  const ccy = it.pricing?.currency || it.settlement_currency || ''
  return base ? `${base} ${ccy}`.trim() : t('pocket.discover.paid', 'Paid')
}
/* detail — the existing full card, lazily */
const AgentDetailModal = defineAsyncComponent(() => import('@/components/AgentDetailModal.vue'))
const detailEver = ref(false)
const detailOpen = ref(false)
const detailDid = ref('')
/** Set when the human opened the card via "Track record & receipts" — the panel
 *  then shows its honest empty line instead of auto-hiding into a blank space. */
const detailFocusRecord = ref(false)
function openDetail(it: any, opts?: { record?: boolean }) {
  detailDid.value = it.agent_did || it.did
  detailFocusRecord.value = !!opts?.record
  detailEver.value = true; detailOpen.value = true
}

/* quick sheet */
const quick = ref<any | null>(null)
const quickEl = ref<HTMLElement | null>(null)
useFocusTrap(quickEl, { activeWhen: computed(() => !!quick.value) })
const shared = ref('')
function openQuick(it: any) { shared.value = ''; quick.value = it }
let holdTarget: any = null
const hold = usePressHold(() => { if (holdTarget) openQuick(holdTarget) })
function startHold(it: any, e: PointerEvent) { holdTarget = it; hold.onPointerdown(e) }
function onEscKey(e: KeyboardEvent) { if (e.key === 'Escape' && quick.value) quick.value = null }
watch(quick, (v) => {
  if (v) window.addEventListener('keydown', onEscKey)
  else window.removeEventListener('keydown', onEscKey)
})

function hire(it: any) {
  quick.value = null
  const title = tp('pocket.discover.hireTitle', 'Hire {name}', { name: it.name || shorten(it.agent_did) })
  router.push({ path: '/pocket/payments', query: { post: '1', title } }).catch(() => {})
}
function pay(it: any) {
  quick.value = null
  router.push({ path: '/pocket/pay', query: { to: it.agent_did || it.did } }).catch(() => {})
}
const canNativeShare = typeof navigator !== 'undefined' && typeof (navigator as any).share === 'function'
const shareLabel = computed(() => canNativeShare
  ? t('pocket.discover.qShare', 'Share')
  : t('pocket.discover.qCopy', 'Copy agent address'))
async function share(it: any) {
  const did = it.agent_did || it.did
  const text = `${it.name || did} · ${did}`
  const url = `${location.origin}/ui#/discovery`
  try {
    if (canNativeShare) { await (navigator as any).share({ title: it.name || 'Agent', text, url }); quick.value = null; return }
  } catch { /* user cancelled the native sheet — fall through to nothing */ return }
  try {
    await navigator.clipboard.writeText(`${text} — ${url}`)
    shared.value = t('pocket.discover.copied', 'Copied to clipboard.')
  } catch { shared.value = t('pocket.discover.copyFailed', 'Could not copy on this device.') }
}
</script>

<style scoped>
.pd-wrap { display: flex; flex-direction: column; gap: 0.6rem; }
.pd-search { display: flex; align-items: center; gap: 0.5rem; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.09); border-radius: 13px; padding: 0.55rem 0.8rem; }
.pd-search:focus-within { border-color: rgba(0,212,255,0.4); }
.pd-search :deep(svg) { width: 1rem; height: 1rem; opacity: 0.5; flex: 0 0 auto; }
.pd-search input { flex: 1 1 auto; background: none; border: none; outline: none; color: inherit; font-size: 16px; min-width: 0; }
.pd-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; align-items: center; }
.pd-tag-hidden { border-color: rgba(255,180,80,0.45); color: #ffb450; }
.pd-chip-n { margin-left: 0.35rem; opacity: 0.55; font-variant-numeric: tabular-nums; font-size: 0.72em; }
.pd-chip { min-height: 36px; border-radius: 999px; border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.04); color: rgba(230,237,243,0.75); font-size: 0.72rem; font-weight: 600;
  padding: 0 0.75rem; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pd-chip.on { color: var(--nc-primary, #00d4ff); border-color: rgba(0,212,255,0.4); background: rgba(0,212,255,0.09); }
.pd-sort { margin-left: auto; min-height: 36px; font-size: 0.74rem; color: inherit;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: 10px; padding: 0 0.5rem; }
.pd-facets { margin: 0; font-size: 0.7rem; opacity: 0.55; font-variant-numeric: tabular-nums; }
.pd-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.pd-card { position: relative; display: flex; align-items: flex-start; gap: 0.75rem;
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px;
  padding: 0.8rem; cursor: pointer; -webkit-tap-highlight-color: transparent; touch-action: pan-y; }
.pd-card:active { background: rgba(255,255,255,0.06); }
.pd-flare { flex: 0 0 auto; margin-top: 0.1rem; }

.pd-body { flex: 1 1 auto; min-width: 0; }
.pd-name { font-size: 0.92rem; font-weight: 650; display: flex; align-items: center; gap: 0.4rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pd-live { width: 7px; height: 7px; border-radius: 50%; background: #34d399; box-shadow: 0 0 6px rgba(52,211,153,0.7); flex: 0 0 auto; }
.pd-sub { font-size: 0.68rem; opacity: 0.5; margin-top: 0.05rem; }
.pd-desc { font-size: 0.76rem; opacity: 0.75; margin-top: 0.3rem; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.pd-chips-row { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.45rem; }
.pd-tag { display: inline-flex; align-items: center; gap: 0.25rem; font-size: 0.64rem; font-weight: 650;
  border-radius: 7px; padding: 0.18rem 0.45rem; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); }
.pd-tag :deep(svg) { width: 0.75rem; height: 0.75rem; }
.pd-tag-proof { color: #34d399; border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.1); }
.pd-tag-warn { color: #ff8a8a; border-color: rgba(255,107,107,0.35); background: rgba(255,107,107,0.08); }
.pd-tag-paid { color: #f6c453; border-color: rgba(246,196,83,0.35); background: rgba(246,196,83,0.08); }
.pd-dots { position: absolute; top: 0.4rem; right: 0.4rem; min-width: 44px; min-height: 44px;
  display: grid; place-items: center; background: none; border: none; color: rgba(230,237,243,0.5);
  cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pd-dots :deep(svg) { width: 1.1rem; height: 1.1rem; }
.pd-more-row { display: flex; justify-content: center; padding: 0.4rem 0 0.8rem; }
.pd-more { min-height: 44px; border-radius: 12px; border: 1px solid rgba(0,212,255,0.3);
  background: rgba(0,212,255,0.08); color: #e6edf3; font-size: 0.8rem; font-weight: 600; padding: 0 1.2rem;
  cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pd-err, .pd-empty { font-size: 0.8rem; opacity: 0.75; margin: 0.6rem 0; text-align: center; }
.pd-err { color: #ff9a9a; display: flex; flex-direction: column; gap: 0.5rem; align-items: center; }
.pd-skel { height: 5.4rem; border-radius: 16px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pd-shim 1.3s ease-in-out infinite; }
@keyframes pd-shim { to { background-position: -200% 0; } }
/* quick sheet */
.pd-scrim { position: fixed; inset: 0; z-index: 92; background: rgba(2,4,8,0.6); backdrop-filter: blur(2px);
  display: flex; align-items: flex-end; justify-content: center; }
.pd-sheet { width: 100%; max-width: 560px; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09);
  border-bottom: none; border-radius: 22px 22px 0 0; padding: 0.5rem 1rem calc(1rem + env(safe-area-inset-bottom, 0px));
  display: flex; flex-direction: column; gap: 0.45rem; box-sizing: border-box; }
.pd-grip { width: 38px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.25rem auto 0.4rem; }
.pd-q-name { margin: 0 0 0.2rem; font-size: 0.9rem; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pd-q-btn { display: flex; align-items: center; gap: 0.6rem; width: 100%; text-align: left; min-height: 50px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px;
  color: inherit; padding: 0.6rem 0.8rem; font-size: 0.86rem; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pd-q-btn:active { background: rgba(255,255,255,0.08); }
.pd-q-btn :deep(svg) { width: 1.05rem; height: 1.05rem; color: var(--nc-primary, #00d4ff); }
.pd-q-note { margin: 0; font-size: 0.74rem; color: #34d399; }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .pd-skel { animation: none; }
  .pk-sheet-enter-active, .pk-sheet-leave-active { transition: none; } }

/* §REPBOND */
.pd-tag-bond { border-color: rgba(var(--nc-primary-rgb), 0.45); color: rgb(var(--nc-primary-rgb)); }
.pd-tag-bond[data-bond-status="matured"] { border-color: rgba(52,211,153,0.5); color: #34d399; }
</style>
