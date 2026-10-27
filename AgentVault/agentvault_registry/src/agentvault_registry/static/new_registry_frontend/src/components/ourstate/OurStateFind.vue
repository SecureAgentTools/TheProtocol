<!--
  §OURSTATE-6 — FIND SOMEONE.

  Until now, the only way to start a thread was a twelve-row cast that appeared
  when you had no threads and vanished the moment you had one. So the answer to
  "who else is out there" was: whoever we happened to list on your first day.
  His words, on seeing SYBIL sitting alone on frame-c: *discovery should be
  federation-wide with filters*.

  It rides the EXISTING discover rail (`GET /agent-cards/discover`, §DISCREFINE)
  — the same one Pocket Discover uses, so the ONE pricing brain answers here
  too and this surface cannot disagree with that one about who costs what.
  Federation is not a feature added here: mirrored cards are already in that
  index, which is why FOREIGN is a filter rather than a separate search.

  Two lanes, because a counterparty is not always an agent:

    * AGENTS  — search + filters over the whole indexed population. Tapping one
                opens an `agent_service` thread, which CORE already allows for a
                foreign agent (its card is its offer, and §BUYSERVICE verifies
                at the issuer). A foreign agent says so on its row.
    * PERSON  — an @handle, resolved through the REACH profile. A private
                profile answers *reachable, not listed* rather than 404, so
                "no such person" and "prefers not to be listed" stay distinct
                (§OURSTATE-3a), and this surface repeats that distinction
                instead of flattening it into "not found".

  What it deliberately does NOT do: it never sends a first message. Finding
  someone opens the thread; what you say is yours.
-->
<template>
  <div class="osf-veil" @click.self="close">
    <div class="osf" role="dialog" aria-modal="true" data-testid="os-find">
      <header class="osf-head">
        <h3>{{ t('ourstate.find.title', 'Find someone') }}</h3>
        <button class="osf-x" :aria-label="t('cta.close', 'Close')"
                data-testid="os-find-close" @click="close"><Icon name="mdi:close" /></button>
      </header>

      <div class="osf-lanes">
        <button class="osf-lane" :class="{ on: lane === 'agents' }" data-testid="os-find-lane-agents"
                @click="lane = 'agents'">{{ t('ourstate.find.laneAgents', 'Agents') }}</button>
        <button class="osf-lane" :class="{ on: lane === 'person' }" data-testid="os-find-lane-person"
                @click="lane = 'person'">{{ t('ourstate.find.lanePerson', 'By handle') }}</button>
      </div>

      <!-- ---------------- AGENTS ---------------- -->
      <template v-if="lane === 'agents'">
        <input v-model="q" class="osf-input" type="search" data-testid="os-find-q"
               :placeholder="t('ourstate.find.search', 'Search agents by name, skill or tag')"
               @input="onType" />

        <div class="osf-chips">
          <button v-for="c in CHIPS" :key="c.k" class="osf-chip" :class="{ on: chip === c.k }"
                  :data-testid="`os-find-chip-${c.k}`" @click="setChip(c.k)">
            {{ t(c.i18n, c.d) }}
            <span v-if="facetOf(c.k) !== null" class="osf-chip-n">{{ facetOf(c.k) }}</span>
          </button>
        </div>

        <p v-if="!loading && !err" class="osf-count" data-testid="os-find-count">
          {{ total
            ? tp('ourstate.find.showing', 'Showing {n} of {total}',
                 { n: String(rows.length), total: String(total) })
            : t('ourstate.find.none', 'Nobody matches that yet.') }}
        </p>
        <p v-if="err" class="osf-err" data-testid="os-find-err">{{ err }}</p>

        <div class="osf-rows">
          <button v-for="a in rows" :key="a.did" class="osf-row" :data-testid="`os-find-row-${a.did}`"
                  :disabled="opening === a.did" @click="openAgent(a)">
            <UserAvatar :user="a" :avatar-url="a.card_data?.iconUrl || null" :display-name="a.name"
                        :track-record="a.track_record || null" size="md" />
            <span class="osf-row-body">
              <span class="osf-row-name">{{ a.name }}</span>
              <span class="osf-row-sub">
                <span>{{ priceOf(a) }}</span>
                <span v-if="originOf(a)" class="osf-origin" :data-testid="`os-find-origin-${a.did}`">
                  · {{ originOf(a) }}</span>
              </span>
            </span>
            <Icon name="mdi:chat" class="osf-go" />
          </button>
        </div>

        <button v-if="hasMore && !loading" class="osf-more" data-testid="os-find-more"
                @click="load(false)">{{ t('cta.loadMore', 'Load more') }}</button>
        <p v-if="loading" class="osf-count">{{ t('common.loading', 'Loading…') }}</p>
      </template>

      <!-- ---------------- PERSON ---------------- -->
      <template v-else>
        <input v-model="handle" class="osf-input" data-testid="os-find-handle"
               :placeholder="t('ourstate.find.handlePh', '@handle')"
               @keyup.enter="lookup" />
        <button class="osf-more" data-testid="os-find-lookup" :disabled="!handle.trim() || hLoading"
                @click="lookup">{{ t('ourstate.find.lookup', 'Look up') }}</button>

        <ReadFailedNotice v-if="hUnread" dense :retry="lookup" data-testid="os-find-handle-unread"
                          :text="t('ourstate.find.handleUnread', 'The handle could not be looked up just now.')" />
        <p v-else-if="hErr" class="osf-err" data-testid="os-find-handle-err">{{ hErr }}</p>

        <!-- §TWOAGENT G1 (V0437): an ADDRESS on another registry opens a cross-registry thread (no local lookup) -->
        <div v-if="remoteAddr" class="osf-profile" data-testid="os-find-remote">
          <p class="osf-row-name">{{ remoteAddr.id }}</p>
          <p class="osf-row-sub">{{ tp('ourstate.find.remoteHint', 'On another registry: {origin}', { origin: remoteAddr.origin }) }}</p>
          <button class="osf-more" data-testid="os-find-remote-message" :disabled="opening === 'remote'"
                  @click="openRemote">{{ t('ourstate.find.message', 'Message') }}</button>
        </div>

        <div v-if="profile" class="osf-profile" data-testid="os-find-profile">
          <OurStateIdentity ptype="developer" :pid="profile.developer_id ?? profile.handle"
                            :fallback-name="profile.display_name || profile.handle" size="lg" />
          <p class="osf-row-name">{{ profile.display_name || '@' + profile.handle }}</p>
          <!-- A private profile is REACHABLE and says so. Rendering it as an
               error would answer a question nobody asked. -->
          <p v-if="profile.visibility === 'private'" class="osf-row-sub" data-testid="os-find-private">
            {{ t('ourstate.find.private', 'This person prefers not to be listed. You can still reach them.') }}</p>
          <button class="osf-more" data-testid="os-find-message" :disabled="opening === 'handle'"
                  @click="openHandle">{{ t('ourstate.find.message', 'Message') }}</button>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { discoveryService } from '@/services/api/discovery'
import { chatApi } from '@/services/api/chat'
import { parseRemoteAddress } from '@/services/chat/counterparty'
import { useAuthStore } from '@/stores/auth'
import { useOurChatBase } from '@/composables/useOurChatBase'

const { t, tp } = useI18n()
const router = useRouter()
/* §FESUITE — the one brain for where OurChat lives from HERE: the sheet opened on the desktop sent every new thread
   into Pocket (/pocket/ourchat/...), the phone chrome, out of the page the person was on. */
const { base } = useOurChatBase()
const auth = useAuthStore()
const emit = defineEmits<{ (e: 'close'): void }>()

const CHIPS = [
  { k: 'all',     i18n: 'ourstate.find.chipAll',     d: 'All' },
  { k: 'paid',    i18n: 'ourstate.find.chipPaid',    d: 'Paid' },
  { k: 'free',    i18n: 'ourstate.find.chipFree',    d: 'Free' },
  { k: 'live',    i18n: 'ourstate.find.chipLive',    d: 'Live 24h' },
  { k: 'foreign', i18n: 'ourstate.find.chipForeign', d: 'Other registries' },
] as const
type ChipKey = typeof CHIPS[number]['k']

const lane = ref<'agents' | 'person'>('agents')
const q = ref(String(useRoute().query.fq || ''))
const chip = ref<ChipKey>('all')
const rows = ref<any[]>([])
const total = ref(0)
const hasMore = ref(false)
const facets = ref<any>(null)
const loading = ref(false)
const err = ref('')
const opening = ref('')
let typeTimer: any = null

const token = computed(() => (auth as any).token || '')

/** Facet counts describe the CURRENT query, so a chip shows what it would find
 *  from here — not a global census. Null when the rail did not say. */
function facetOf(k: ChipKey): number | null {
  const f = facets.value
  if (!f) return null
  if (k === 'paid') return f.paid ?? null
  if (k === 'free') return f.free ?? null
  if (k === 'live') return f.live_24h ?? null
  return null
}

function params(offset: number) {
  const p: any = { limit: 20, offset, sort: 'proven' }
  if (q.value.trim()) p.q = q.value.trim()
  if (chip.value === 'paid') p.pricing = 'paid'
  if (chip.value === 'free') p.pricing = 'free'
  if (chip.value === 'live') p.active_24h = true
  if (chip.value === 'foreign') p.foreign_only = true
  return p
}

async function load(reset: boolean) {
  loading.value = true
  err.value = ''
  try {
    const r = await discoveryService.discover(params(reset ? 0 : rows.value.length))
    rows.value = reset ? (r.results || []) : rows.value.concat(r.results || [])
    total.value = r.total || 0
    hasMore.value = !!r.has_more
    facets.value = r.facets || null
  } catch (e: any) {
    // A read that failed is not an empty population — say so, keep what we had.
    err.value = e?.detail || t('ourstate.find.readFailed', 'Could not reach discovery just now.')
  } finally { loading.value = false }
}

function onType() {
  clearTimeout(typeTimer)
  typeTimer = setTimeout(() => void load(true), 280)
}
function setChip(k: ChipKey) { chip.value = k; void load(true) }

function priceOf(a: any): string {
  // The ONE pricing brain (§DISCREFINE): a card may price through the legacy
  // block OR the A2A payment extension, and reading only one calls a paid
  // agent free.
  const p = a?.pricing
  if (p?.payment_required && p?.base_rate) return `${p.base_rate} ${p.currency || ''}`.trim()
  return t('ourstate.find.free', 'Free to call')
}

function originOf(a: any): string {
  const src = a?.federation_metadata?.source_registry
  return src ? String(src) : ''
}

async function openAgent(a: any) {
  opening.value = a.did
  err.value = ''
  try {
    const r: any = await chatApi.createConversation(token.value, 'agent_service',
                                                    { ptype: 'agent', agent_did: a.did })
    emit('close')
    router.push(`${base.value}/${r.conversation_id}`).catch(() => {})
  } catch (e: any) {
    err.value = e?.detail || String(e)
  } finally { opening.value = '' }
}

/* ----------------------------- handle lane ----------------------------- */
const handle = ref('')
const profile = ref<any>(null)
const hLoading = ref(false)
const hErr = ref('')
// §FESUITE V0578: "No account carries the handle @x." was said ONLY when nothing answered (an answered error showed its
// own detail): a lookup that never reached the registry told the person the account does not exist. A 404 says no
// account now; no answer or the registry's own failure (5xx) says the lookup failed (Try again).
const hUnread = ref(false)

const remoteAddr = computed(() => parseRemoteAddress(handle.value))

async function lookup() {
  hUnread.value = false
  if (remoteAddr.value) { void openRemote(); return }
  const h = handle.value.trim().replace(/^@/, '')
  if (!h) return
  hLoading.value = true
  hErr.value = ''
  hUnread.value = false
  profile.value = null
  try {
    profile.value = await chatApi.handleProfile(h)
  } catch (e: any) {
    const st = Number(e?.status || 0)
    if (st === 404) hErr.value = tp('ourstate.find.noHandle', 'No account carries the handle @{h}.', { h })
    else if (!st || st >= 500) hUnread.value = true
    else hErr.value = e?.detail || String(e)
  } finally { hLoading.value = false }
}

async function openHandle() {
  if (!profile.value) return
  opening.value = 'handle'
  hErr.value = ''
  try {
    const r: any = await chatApi.createConversation(
      token.value, 'dm', { ptype: 'developer', handle: profile.value.handle })
    emit('close')
    router.push(`${base.value}/${r.conversation_id}`).catch(() => {})
  } catch (e: any) {
    hErr.value = e?.detail || String(e)
  } finally { opening.value = '' }
}

async function openRemote() {
  const a = remoteAddr.value
  if (!a) return
  opening.value = 'remote'
  hErr.value = ''
  try {
    const r: any = await chatApi.createConversation(
      token.value, 'dm', { ptype: a.isAgent ? 'agent' : 'developer', remote_key: a.key })
    emit('close')
    router.push(`${base.value}/${r.conversation_id}`).catch(() => {})
  } catch (e: any) {
    hErr.value = e?.detail || String(e)
  } finally { opening.value = '' }
}

function close() { emit('close') }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape') close() }

onMounted(() => { window.addEventListener('keydown', onKey); void load(true) })
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<style scoped>
.osf-veil { position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 60; display: flex; align-items: flex-end; }
.osf { width: 100%; max-height: 86vh; overflow-y: auto; background: var(--bg-elevated, #14161b);
       border-radius: 16px 16px 0 0; padding: 14px 14px 24px; }
/* §FINDFIX — on desktop this is a DIALOG, not a phone bottom sheet. The sheet
   presentation pinned a full-width panel to the bottom edge AND sat under the
   sidebar shell (z-index 10000), so the left edge of every row was occluded —
   his "fail sized / cant read everything" report. Same breakpoint the OurChat
   shell splits on; below it Pocket is byte-identical. */
@media (min-width: 900px) {
  .osf-veil { --osf-desk: 1; align-items: center; justify-content: center; padding: 32px; z-index: 10500; }
  .osf { width: min(600px, 100%); max-height: min(80vh, 760px); border-radius: 16px;
         padding: 16px 20px 22px; border: 1px solid var(--border-color, rgba(128,128,128,.25));
         box-shadow: 0 24px 64px rgba(0,0,0,.55); }
}
.osf-head { display: flex; align-items: center; justify-content: space-between; }
.osf-head h3 { margin: 0; font-size: 1.05rem; }
.osf-x { min-width: 44px; min-height: 44px; border: none; background: none; color: inherit; cursor: pointer; }
.osf-lanes { display: flex; gap: 6px; margin: 10px 0; }
.osf-lane { flex: 1; min-height: 44px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.25));
            background: none; color: inherit; cursor: pointer; }
.osf-lane.on { background: var(--accent-soft, rgba(120,160,255,.16)); font-weight: 700; }
.osf-input { width: 100%; min-height: 44px; font-size: 16px; padding: 0 12px; border-radius: 10px;
             border: 1px solid var(--border-color, rgba(128,128,128,.25)); background: transparent; color: inherit; }
.osf-chips { display: flex; gap: 6px; overflow-x: auto; margin: 10px 0 6px; padding-bottom: 2px; }
.osf-chip { flex: 0 0 auto; min-height: 36px; padding: 0 12px; border-radius: 999px; cursor: pointer;
            border: 1px solid var(--border-color, rgba(128,128,128,.25)); background: none; color: inherit; }
.osf-chip.on { background: var(--accent-soft, rgba(120,160,255,.16)); font-weight: 700; }
.osf-chip-n { opacity: .6; margin-left: 5px; font-variant-numeric: tabular-nums; }
.osf-count { margin: 6px 2px; font-size: .82rem; opacity: .7; }
.osf-err { margin: 6px 2px; font-size: .82rem; color: var(--danger, #e0716b); }
.osf-rows { display: flex; flex-direction: column; }
.osf-row { display: flex; align-items: center; gap: 10px; min-height: 60px; padding: 6px; cursor: pointer;
           border: none; background: none; color: inherit; text-align: left;
           border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); }
.osf-row-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.osf-row-name { font-weight: 700; }
.osf-row-sub { font-size: .78rem; opacity: .65; }
.osf-origin { opacity: .9; }
.osf-go { opacity: .5; }
.osf-more { width: 100%; min-height: 44px; margin-top: 10px; border-radius: 10px; cursor: pointer;
            border: 1px solid var(--border-color, rgba(128,128,128,.25)); background: none; color: inherit; }
.osf-profile { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 18px 6px; text-align: center; }
</style>
