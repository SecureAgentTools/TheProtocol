<template>
  <!-- §OURSTATE-1 — the OurState tab: thread list + Requests lane + the
       day-one cast. Every name renders through OurStateIdentity (the
       Commander's identity mandate — one mount point, pixel-parity with
       Discover/My Agents). Errors render AS errors, never as empty (§PB2 W1). -->
  <div ref="ptrEl" class="pk-main os-root" data-testid="os-root">
    <div class="pk-ptr" :style="{ height: ptr.ptrH.value + 'px' }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pk-ptr-spin': ptr.ptrArmed.value }" />
    </div>

    <header class="os-head">
      <h1 class="os-title">OurChat</h1>
      <div class="os-lanes" role="tablist">
        <button role="tab" class="os-lane" :class="{ on: lane === 'active' }"
                :aria-selected="lane === 'active'" data-testid="os-lane-active"
                @click="switchLane('active')">{{ t('ourstate.list.inbox', 'Threads') }}</button>
        <button role="tab" class="os-lane" :class="{ on: lane === 'requests' }"
                :aria-selected="lane === 'requests'" data-testid="os-lane-requests"
                @click="switchLane('requests')">
          {{ t('ourstate.list.requests', 'Requests') }}
          <span v-if="requestCount === null" class="os-lane-badge os-lane-badge--unread" data-testid="os-req-count-unread"
                :title="t('ourstate.list.requestsUnread', 'Your requests could not be read just now.')">—</span>
          <span v-else-if="requestCount > 0" class="os-lane-badge" data-testid="os-req-count">{{ requestCount }}</span>
        </button>
      </div>
    </header>

    <!-- Honest hosting line (law 5): who holds these threads, said plainly. -->
    <!-- §TWOAGENT V0441: where cross-registry chat is on, "Same-registry only for now." is no longer true here; the
         list says which it is (cross_registry) and the line follows. -->
    <p class="os-hosting" data-testid="os-hosting">{{ crossRegistry
      ? tp('ourstate.list.hostingCross', 'Threads you start live on {registry}. A thread another registry starts lives there, with a copy here.', { registry: registryName })
      : tp('ourstate.list.hosting', 'Threads live on {registry}. Same-registry only for now.', { registry: registryName }) }}</p>

    <div v-if="err" class="os-err" data-testid="os-error">
      <Icon name="mdi:alert-circle" /> {{ err }}
      <button class="os-retry" @click="load(true)">{{ t('common.retry', 'Retry') }}</button>
    </div>

    <template v-else>
      <!-- §OURSTATE-6 — the door is PERMANENT. §DESKCHROME (2026-08-28): moved to
           the TOP of the list on BOTH surfaces — below a long list it was invisible
           at first paint (Commander: "should be top"). -->
      <button v-if="lane === 'active'" class="os-find-door" data-testid="os-find-open" data-tour="ourchat-find"
              @click="findOpen = true">
        <Icon name="mdi:magnify" />
        <span>{{ t('ourstate.find.door', 'Find someone to talk to') }}</span>
      </button>

      <!-- The Protocol thread (D7): the notification feed absorbed VIRTUALLY —
           a pinned door, zero new writes. -->
      <button v-if="lane === 'active'" class="os-row os-protocol" data-testid="os-protocol"
              @click="openProtocolFeed()">
        <span class="os-proto-icon"><Icon name="mdi:shield-key" /></span>
        <span class="os-row-body">
          <span class="os-row-name">{{ t('ourstate.list.protocolThread', 'The Protocol') }}</span>
          <span class="os-row-preview">{{ t('ourstate.list.protocolSub', 'Notices from this registry — your notification feed.') }}</span>
        </span>
        <span v-if="unreadNotifs === null" class="os-unread os-unread--unknown" data-testid="os-protocol-unread-unknown"
              :title="t('ourstate.list.noticesUnread', 'Your notices could not be counted just now.')">—</span>
        <span v-else-if="unreadNotifs > 0" class="os-unread">{{ unreadNotifs }}</span>
      </button>

      <!-- §OURSTATE-2 "while you were away": what your stand-in answered.
           Everything in there is STAGED — nothing accepted, paid or signed. -->
      <div v-if="lane === 'active' && awayDigest.length" class="os-away" data-testid="os-away-digest">
        <p class="os-rooms-head">{{ t('ourstate.away.digestHead', 'While you were away') }}</p>
        <p class="os-away-note">{{ tp('ourstate.away.digestNote', '{n} thread(s) your stand-in answered. Nothing was accepted, paid or signed.', { n: String(awayDigest.length) }) }}</p>
        <button v-for="d in awayDigest" :key="d.conversation_id" class="os-row"
                :data-testid="`os-away-${d.conversation_id}`"
                @click="router.push(`${base}/${d.conversation_id}`)">
          <span class="os-proto-icon"><Icon name="mdi:account-clock" /></span>
          <span class="os-row-body">
            <span class="os-row-name">{{ t('ourstate.away.staged', 'Staged for you') }}</span>
            <span class="os-row-preview">{{ d.last_preview || '' }}</span>
          </span>
          <span v-if="d.unread > 0" class="os-unread">{{ d.unread }}</span>
        </button>
      </div>

      <div v-if="loading && !rows.length" class="os-loading">{{ t('common.loading', 'Loading…') }}</div>

      <!-- Requests lane: the trust surfaces render ON the request (§6) -->
      <div v-for="c in rows" :key="c.id" class="os-row-wrap">
        <button class="os-row" :data-testid="`os-row-${c.id}`"
                @click="openThread(c)">
          <OurStateIdentity v-if="c.counterparty"
                            :ptype="identityKind(c.counterparty.ptype)"
                            :pid="identityPid(c.counterparty)"
                            :fallback-name="c.counterparty.name" size="md" />
          <span v-else-if="c.kind === 'org'" class="os-proto-icon"><Icon name="mdi:account-group" /></span>
          <!-- §OURSTATE-7 D — a support thread has a desk, not a counterparty.
               Without its own branch it fell through to the nameless row. -->
          <span v-else-if="c.kind === 'support'" class="os-proto-icon"><Icon name="mdi:lifebuoy" /></span>
          <span v-else class="os-row-noident"><Icon name="mdi:account" /></span>
          <span class="os-row-body">
            <!-- the name takes one line and an ellipsis (the whole of it on hover); a long one wrapped to three lines and
                 squeezed the support chip -->
            <span class="os-row-name"><span class="os-row-title" :title="rowTitle(c)">{{ rowTitle(c) }}</span>
              <Icon v-if="c.kind === 'agent_service'" name="mdi:robot" class="os-kind" />
              <span v-if="c.kind === 'support'" class="os-announce">{{ t('ourstate.support.tag', 'support') }}</span>
              <span v-if="c.kind === 'org' && c.mode === 'announce'" class="os-announce">{{ t('ourstate.rooms.announce', 'announce') }}</span>
            </span>
            <span class="os-row-preview">{{ (c.kind === 'org' && c.topic) ? c.topic : (c.last_preview || '') }}</span>
          </span>
          <span class="os-row-meta">
            <span class="os-row-time">{{ timeAgo(c.last_message_at) }}</span>
            <span v-if="c.unread > 0" class="os-unread" data-testid="os-unread">{{ c.unread }}</span>
            <Icon v-if="c.muted" name="mdi:bell-off" class="os-muted" />
          </span>
        </button>
        <div v-if="lane === 'requests'" class="os-req-actions">
          <TrustLinesRow :did="c.counterparty?.ptype === 'agent' ? c.counterparty.agent_did : null" />
          <div class="os-req-btns">
            <button class="os-btn os-accept" :data-testid="`os-accept-${c.id}`" @click="accept(c)">{{ t('ourstate.list.accept', 'Accept') }}</button>
            <button class="os-btn os-decline" @click="decline(c)">{{ t('ourstate.list.decline', 'Decline') }}</button>
          </div>
        </div>
      </div>

      <button v-if="nextCursor" class="os-more" @click="load(false)">{{ t('common.loadMore', 'Load more') }}</button>

      <!-- §OURSTATE-7 A2 — OFFERS SIT BELOW WHAT HAPPENED.
           These two sections used to render ABOVE the conversation list, so a
           thing you MIGHT do (open a room, switch one on) pushed down every
           thing that actually did. The list is already sorted newest-activity
           first by the API; the page was undoing that by putting furniture on
           top of it. Doors belong under the record, not over it. -->

      <!-- §OURSTATE-2 ROOMS: one per org you belong to. Opened rooms live in
           the thread list above; unopened ones are offered here as doors. -->
      <div v-if="lane === 'active' && unopenedRooms.length" class="os-rooms" data-testid="os-rooms">
        <p class="os-rooms-head">{{ t('ourstate.rooms.section', 'Rooms') }}</p>
        <button v-for="r in unopenedRooms" :key="r.org_id" class="os-row"
                :data-testid="`os-room-${r.org_id}`" @click="openRoom(r)">
          <span class="os-proto-icon"><Icon name="mdi:account-group" /></span>
          <span class="os-row-body">
            <span class="os-row-name">{{ r.org_name }}
              <span v-if="r.mode === 'announce'" class="os-announce">{{ t('ourstate.rooms.announce', 'announce') }}</span>
            </span>
            <!-- §ROOMUNREAD — the LAST MESSAGE, not the topic. This row used
                 to show the org's topic (or a generic invitation) whether or not
                 anything had been said, so a room could be posted in all day and
                 look identical to an empty one. -->
            <span class="os-row-preview">{{ r.last_preview || r.topic || t('ourstate.rooms.open', 'Open your organization’s room') }}</span>
          </span>
          <span v-if="r.unread > 0" class="os-unread" :data-testid="`os-room-unread-${r.org_id}`">{{ r.unread }}</span>
          <Icon v-else name="mdi:chat" class="os-cast-go" />
        </button>
      </div>

      <!-- §OURSTATE-6 — orgs WITHOUT a room are offered, not listed as if they
           had one. Before this, every org you belong to appeared as an empty
           conversation and the real room was lost among them. Whether YOU may
           switch it on is the org's own setting, and it says which.
           §OURSTATE-7 A1 made this retroactive: a room opened BEFORE the opt-in
           existed now leaves the thread list and reappears here. -->
      <div v-if="lane === 'active' && enableableRooms.length" class="os-rooms"
           data-testid="os-rooms-off">
        <p class="os-rooms-head">{{ t('ourstate.rooms.offSection', 'Organizations without a room') }}</p>
        <button v-for="r in enableableRooms" :key="r.org_id" class="os-row"
                :data-testid="`os-room-off-${r.org_id}`" :disabled="!r.may_enable || enabling === r.org_id"
                @click="enableRoom(r)">
          <span class="os-proto-icon"><Icon name="mdi:account-group" /></span>
          <span class="os-row-body">
            <span class="os-row-name">{{ r.org_name }}</span>
            <span class="os-row-preview">{{ r.may_enable
              ? t('ourstate.rooms.enable', 'Turn this organization’s room on')
              : t('ourstate.rooms.enableDenied', 'Only an owner or admin can turn this room on') }}</span>
          </span>
          <Icon v-if="r.may_enable" name="mdi:plus" class="os-cast-go" />
        </button>
      </div>

      <!-- Empty state: the room is never empty — the eleven working agents are
           the day-one cast (strategy §13), rendered with FULL identity. The
           permanent find door now sits at the TOP of the list (§DESKCHROME). -->
      <div v-if="!loading && !rows.length && lane === 'active'" class="os-empty" data-testid="os-empty" data-tour="ourchat-empty">
        <!-- §CHATCOHERE A5 — the old line ("ask one something") presumed you already
             knew WHICH agent, what it costs and what comes back. A cold start showed
             it to someone who knew none of the three. This says what the place is,
             what arrives, and — the part that removes the fear — that the price is
             shown and confirmed BEFORE anything moves, which is already true. -->
        <p class="os-empty-line">{{ t('ourstate.list.emptyLine2', 'No threads yet. Agents here work for a fee: you ask, they answer, and the answer arrives as a receipt you can check.') }}</p>
        <!-- §COCKPITDESK (2026-10-15): "Pick one to start" over an empty cast (the camera, 2026-10-13) was a door to nothing -->
        <p v-if="cast.length" class="os-empty-sub">{{ t('ourstate.list.emptySub', 'Pick one to start. You always see the price and confirm it before anything moves.') }}</p>
        <p v-else-if="!castFailed" class="os-empty-sub" data-testid="os-empty-nocast">{{ t('ourstate.list.emptySubNoCast', 'Find someone to talk to with the search above. You always see the price and confirm it before anything moves.') }}</p>
        <ReadFailedNotice v-if="castFailed && !cast.length" :retry="loadCast" dense data-testid="os-cast-unread" />
        <div class="os-cast" data-tour="ourchat-cast">
          <button v-for="a in cast" :key="a.did" class="os-cast-row" :data-testid="`os-cast-${a.did}`"
                  @click="startServiceThread(a)">
            <UserAvatar :user="a" :avatar-url="a.card_data?.iconUrl || null" :display-name="a.name"
                        :track-record="a.track_record || null" size="md" />
            <span class="os-cast-body">
              <span class="os-cast-name">{{ a.name }}</span>
              <span class="os-cast-price">{{ priceOf(a) }}<span v-if="priceIsForeign(a)" class="os-cast-fx"
                    :title="t('ourstate.list.foreignPriceHint', 'Priced on another frame — paying converts from your balance.')"
                    >{{ tp('ourstate.list.foreignPrice', ' · not {ccy}', { ccy: localCurrency }) }}</span></span>
            </span>
            <Icon name="mdi:chat" class="os-cast-go" />
          </button>
        </div>
      </div>
      <div v-if="!loading && !rows.length && lane === 'requests'" class="os-empty">
        <p class="os-empty-line">{{ t('ourstate.list.noRequests', 'No requests. A first message from a stranger lands here, defused, until you accept.') }}</p>
      </div>
    </template>

    <!-- §OURSTATE-4: the public card behind an @handle, and the only surface
         that renders a pulse. `?profile=@name` is the QR's landing point. -->
    <PocketProfile :show="!!profileHandle" :handle="profileHandle" :token="token"
                   @close="closeProfile" />
  </div>
    <OurStateFind v-if="findOpen" @close="closeFind" />

</template>

<script setup lang="ts">
import { identityKind, identityPid } from '@/services/chat/counterparty'
import { readAccessToken } from '@/services/accessToken'
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useOurChatBase } from '@/composables/useOurChatBase'
import Icon from '@/components/Icon.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import OurStateIdentity from '@/components/ourstate/OurStateIdentity.vue'
import PocketProfile from '@/views/pocket/PocketProfile.vue'
import TrustLinesRow from '@/components/ourstate/TrustLinesRow.vue'
import OurStateFind from '@/components/ourstate/OurStateFind.vue'
import { chatApi } from '@/services/api/chat'
import { discoveryService } from '@/services/api/discovery'
import { useAuthStore } from '@/stores/auth'
import { useChatStream } from '@/composables/useChatStream'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { useI18n } from '@/composables/useI18n'
import { useFrames } from '@/composables/useFrames'

const { t, tp } = useI18n()
const router = useRouter()
const { base } = useOurChatBase()
const route = useRoute()
const auth = useAuthStore()
/* §CHATCOHERE D6 — THE existing single source for this registry's settlement
   currency (the same one the header badge and the acting-agent banner read).
   Declared here, with the other setup singletons, so nothing can read it in its
   temporal dead zone. */
const { localCurrency } = useFrames()

/** §DESKCHROME (2026-08-28): the Protocol row is the notification feed's door.
 *  On desktop (the /ourchat shell) it opens Settings → Notifications — the same
 *  log component, mounted in desktop chrome; only under /pocket/* does it use
 *  the Pocket route. His device-routing law: approvals are the ONLY flow that
 *  sends a desktop user to a phone surface. */
function openProtocolFeed() {
  if (route.path.startsWith('/pocket/')) router.push('/pocket/notifications')
  else router.push('/settings?tab=notifications')
}

const lane = ref<'active' | 'requests'>('active')
const rows = ref<any[]>([])
const nextCursor = ref<string | null>(null)
// §FESUITE V0578: a failed requests read hid the Requests badge (it read as none waiting) and a failed read of the
// starter agents left "Pick one to start" over nothing to pick. The badge says '—' until the requests were read once
// (a failed refresh keeps the last count); the starters say their read failed, with Try again.
const requestCount = ref<number | null>(0)
let requestsRead = false
const castFailed = ref(false)
const loading = ref(false)
const err = ref('')
const cast = ref<any[]>([])
const findOpen = ref(!!route.query.find)
watch(() => route.query.find, v => { if (v) findOpen.value = true })
function closeFind() {
  findOpen.value = false
  if (route.query.find) {
    const q = { ...route.query }; delete (q as any).find; delete (q as any).fq
    router.replace({ query: q }).catch(() => {})
  }
}
// §FESUITE V0578: null = the unread count was asked and not answered (the row said nothing, as if none waited)
const unreadNotifs = ref<number | null>(0)
const registryName = ref('this registry')
const crossRegistry = ref(false)
const orgRooms = ref<any[]>([])
const enableableRooms = ref<any[]>([])
const enabling = ref('')
const awayDigest = ref<any[]>([])

const token = computed(() => (auth as any).token || readAccessToken() || '')

/* A deep link is a promise about the CURRENT state of a record, so the handle
   is read from the query on every navigation, not only on mount — the
   "watcher never fires for an already-true value" class, met three times this
   session. The query is scrubbed only when the sheet closes, so a reload of
   the shared link still lands on the same card. */
const profileHandle = ref(String(route.query.profile || '').replace(/^@/, ''))
watch(() => route.query.profile, v => { profileHandle.value = String(v || '').replace(/^@/, '') })
function closeProfile() {
  profileHandle.value = ''
  if (route.query.profile) {
    const q = { ...route.query }; delete (q as any).profile
    router.replace({ query: q }).catch(() => {})
  }
}

/** Rooms you have NOT opened yet — opened ones already live in `rows`. */
const unopenedRooms = computed(() => {
  const open = new Set(rows.value.filter(r => r.kind === 'org').map(r => r.id))
  return orgRooms.value.filter(r => !r.conversation_id || !open.has(r.conversation_id))
})

async function load(reset: boolean) {
  loading.value = true
  if (reset) { err.value = ''; nextCursor.value = null }
  try {
    const r = await chatApi.listConversations(token.value, lane.value, reset ? undefined : nextCursor.value || undefined)
    rows.value = reset ? (r.conversations || []) : [...rows.value, ...(r.conversations || [])]
    nextCursor.value = r.next_cursor || null
    crossRegistry.value = !!r.cross_registry
    if (lane.value === 'active') {
      // The Requests badge is live even while you look at the inbox.
      const rq = await chatApi.listConversations(token.value, 'requests').catch(() => null)
      if (rq) { requestCount.value = (rq.conversations || []).length; requestsRead = true }
      else if (!requestsRead) requestCount.value = null
    } else {
      requestCount.value = rows.value.length
      requestsRead = true
    }
    if (!rows.value.length && lane.value === 'active' && !cast.value.length) await loadCast()
    if (lane.value === 'active' && reset) {
      // Rooms are additive furniture — a failed fetch renders NO section,
      // never an error over the whole inbox.
      const rm = await chatApi.orgRooms(token.value).catch(() => null)
      orgRooms.value = rm?.rooms || []
      enableableRooms.value = rm?.enableable || []
      const aw = await chatApi.awayDigest(token.value).catch(() => null)
      awayDigest.value = (aw?.threads || []).filter((d: any) => d.unread > 0)
    }
  } catch (e: any) {
    err.value = e?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { loading.value = false }
}

async function openRoom(r: any) {
  try {
    const resp = await chatApi.openOrgRoom(token.value, r.org_id)
    router.push(`${base.value}/${resp.conversation_id}`).catch(() => {})
  } catch (e: any) { err.value = e?.detail || String(e) }
}

async function loadCast() {
  /* §CHATCOHERE D5 (2026-09-01) — this asked for "any 12 paid agents", while the
     comment above the markup claimed the eleven working agents were the day-one
     cast. MEASURED on a frame-c cold start: 7 of the first 9 rows were named
     `*-probe-invalid-*` — cards still wearing the registry's own pull-sync stub,
     handed to a first-time human as their opening suggestions.
     `answerable_only` makes the query say what the comment always claimed:
     described itself, and not known-unreachable. Proven in psql first — the
     paid population goes 18 → the 11 real service agents (+ Auditor Ash, which
     prices through the A2A extension and reads healthy). */
  try {
    const r = await discoveryService.discover({ pricing: 'paid', answerable_only: true, limit: 12 } as any)
    cast.value = r.results || []
    castFailed.value = false
  } catch { cast.value = []; castFailed.value = true }
}

function switchLane(l: 'active' | 'requests') { lane.value = l; rows.value = []; void load(true) }

/* §CHATCOHERE D6 — three presentations stood side by side on one screen:
   "2.0 BVT", "0.7 AVT" and the bare word "paid". A price is only usable if it
   carries its unit, so a rate WITHOUT a currency renders as "price on request"
   rather than as a naked number — §FOREIGNACT's law: empty unit, never wrong
   unit, and never a number a reader will silently assume is theirs.
   Trailing zeros are trimmed so 2.0000000000 and 0.1 read the same way. */
function priceOf(a: any): string {
  const p = a?.pricing
  const rate = p?.base_rate
  const ccy = typeof p?.currency === 'string' ? p.currency.trim() : ''
  if (rate === undefined || rate === null || rate === '') return t('ourstate.list.paid', 'Paid')
  if (!ccy) return t('ourstate.list.paidNoPrice', 'Paid · price on request')
  let n = String(rate)
  if (n.includes('.')) n = n.replace(/0+$/, '').replace(/\.$/, '') || '0'
  return `${n} ${ccy}`
}

/* The second half of D6: a frame-c reader holds BVT, and "0.1 AVT" looks like a
   price they can pay. It is not hidden — foreign agents are real and hireable —
   it is LABELLED, which is the same choice §FOREIGNACT made for the acting-agent
   banner: name the seam rather than paper over it. */
function priceIsForeign(a: any): boolean {
  const ccy = typeof a?.pricing?.currency === 'string' ? a.pricing.currency.trim().toUpperCase() : ''
  const mine = (localCurrency.value || '').trim().toUpperCase()
  return !!ccy && !!mine && ccy !== mine
}

function timeAgo(iso: string | null): string {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 90) return t('time.justNow', 'now')
  if (s < 3600) return `${Math.round(s / 60)}m`
  if (s < 86400) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

/** What a row is CALLED. Three kinds name themselves three ways: a room and a
 *  support thread carry their own title, everything else is named by the person
 *  or agent on the other side. */
function rowTitle(c: any): string {
  if (c.kind === 'org') return c.title || t('ourstate.rooms.room', 'Org room')
  if (c.kind === 'support') return c.title || t('ourstate.support.thread', 'Support')
  return c.counterparty?.name || t('ourstate.list.unknown', 'Conversation')
}

function openThread(c: any) { router.push(`${base.value}/${c.id}`).catch(() => {}) }

async function accept(c: any) {
  try { await chatApi.accept(token.value, c.id); openThread(c) }
  catch (e: any) { err.value = e?.detail || String(e) }
}
async function decline(c: any) {
  try { await chatApi.decline(token.value, c.id); rows.value = rows.value.filter(r => r.id !== c.id) }
  catch (e: any) { err.value = e?.detail || String(e) }
}

/* Turning a room on is an explicit act with an explicit result: it opens, and
   the org's own agents are already inside it. */
async function enableRoom(r: any) {
  if (!r?.may_enable || enabling.value) return
  enabling.value = r.org_id
  try {
    await chatApi.setOrgChatSettings(token.value, r.org_id, { chat_enabled: true })
    const opened = await chatApi.openOrgRoom(token.value, r.org_id)
    router.push(`${base.value}/${opened.conversation_id}`).catch(() => {})
  } catch (e: any) {
    err.value = e?.detail || String(e)
  } finally { enabling.value = '' }
}

async function startServiceThread(a: any) {
  const did = a?.did || a?.agent_did
  if (!did) return
  try {
    const r = await chatApi.createConversation(token.value, 'agent_service', { ptype: 'agent', agent_did: did })
    router.push(`${base.value}/${r.conversation_id}`).catch(() => {})
  } catch (e: any) { err.value = e?.detail || String(e) }
}

useChatStream({
  onMessage: () => { void load(true) },
  onPing: () => { void load(true) },
  onResync: () => { void load(true) },
})

const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { void load(true) })

/* §OURSTATE-2 voice door (`message <name> about …`): open the thread with the
   spoken words DRAFTED. An unresolved name never guesses — it says so and
   leaves you on the list, which is where you can choose. */
async function consumeVoiceDoor() {
  const to = String(route.query.to || '')
  const draft = String(route.query.draft || '')
  const q = String(route.query.q || '')
  // §VOICEHIRE — the offer door rides the same rail as ?draft: forwarded to
  // the thread, consumed there, scrubbed here.
  const proposeQS = route.query.propose
    ? '&' + new URLSearchParams(Object.fromEntries(['propose', 'ptitle', 'ptotal', 'pccy']
        .filter(k => route.query[k] != null).map(k => [k, String(route.query[k])]))).toString()
    : ''
  if (!to && !q) return
  router.replace({ query: {} }).catch(() => {})
  if (!to) {
    // §OURSTATE-3: `?q=@name` is a HANDLE, resolved server-side. Anything
    // else was a spoken name the roster could not match — say so.
    if (q.startsWith('@')) {
      try {
        const r = await chatApi.createConversation(token.value, 'dm', { ptype: 'developer', handle: q } as any)
        const qq = (draft ? `?draft=${encodeURIComponent(draft)}` : proposeQS ? '?x=1' : '') + proposeQS
        router.push(`${base.value}/${r.conversation_id}${qq}`).catch(() => {})
      } catch (e: any) { err.value = e?.detail || String(e) }
      return
    }
    err.value = tp('ourstate.voice.unresolved', 'No agent matched “{q}” — pick a thread or start one below.', { q })
    return
  }
  try {
    const r = await chatApi.createConversation(token.value, 'dm', { ptype: 'agent', agent_did: to })
    const qq = (draft ? `?draft=${encodeURIComponent(draft)}` : proposeQS ? '?x=1' : '') + proposeQS
    router.push(`${base.value}/${r.conversation_id}${qq}`).catch(() => {})
  } catch (e: any) {
    err.value = e?.detail || String(e)
  }
}

onMounted(async () => {
  void load(true)
  void consumeVoiceDoor()
  try {
    const r = await fetch('/.well-known/registry-card.json')
    if (r.ok) {
      const d = await r.json()
      registryName.value = d?.identity?.display_name || d?.identity?.name || registryName.value
    }
  } catch { /* keep default */ }
  try {
    const r = await fetch('/api/v1/notifications/unread-count', {
      headers: { Authorization: `Bearer ${token.value}` } })
    if (r.ok) unreadNotifs.value = Number((await r.json())?.count || 0)
    else if (r.status !== 404) unreadNotifs.value = null   // a registry without the route has no count to show
  } catch { unreadNotifs.value = null }
})
</script>

<style scoped>
.os-root { padding: 12px 14px calc(84px + env(safe-area-inset-bottom)); overflow-y: auto; height: 100%; }
.pk-ptr { display: flex; align-items: flex-end; justify-content: center; overflow: hidden; opacity: .6; }
.pk-ptr-spin { animation: os-spin 1s linear infinite; }
@keyframes os-spin { to { transform: rotate(360deg); } }
.os-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.os-title { font-size: 1.35rem; font-weight: 800; margin: 0; }
.os-lanes { display: flex; gap: 6px; }
.os-lane { min-height: 44px; padding: 0 14px; border-radius: 999px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }
.os-lane.on { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
.os-lane-badge { background: var(--warning-color, #f59e0b); color: #1a1206; border-radius: 999px; min-width: 20px; padding: 1px 6px; font-size: .72rem; text-align: center; }
.os-lane-badge--unread { background: transparent; color: var(--text-secondary, #9aa4b2); border: 1px solid var(--border-color, rgba(255,255,255,.18)); }
.os-hosting { font-size: .72rem; opacity: .55; margin: 0 0 10px; }
.os-err { display: flex; align-items: center; gap: 8px; padding: 12px; border-radius: 10px; border: 1px solid var(--warning-color, #f59e0b); margin-bottom: 10px; }
.os-retry { margin-left: auto; min-height: 44px; padding: 0 14px; border-radius: 8px; border: none; font-weight: 600; }
.os-row-wrap { margin-bottom: 2px; }
.os-row { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 64px; padding: 8px 6px; border: none; background: none; color: inherit; text-align: left; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.15)); cursor: pointer; }
.os-row-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.os-row-name { font-weight: 700; display: flex; align-items: center; gap: 6px; min-width: 0; }
.os-row-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.os-row-name > :not(.os-row-title) { flex: 0 0 auto; }
.os-kind { opacity: .55; width: 14px; height: 14px; }
.os-row-preview { font-size: .82rem; opacity: .65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.os-row-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.os-row-time { font-size: .72rem; opacity: .55; font-variant-numeric: tabular-nums; }
.os-unread { background: var(--primary-color, #4fd8c4); color: #06211d; border-radius: 999px; min-width: 20px; padding: 1px 6px; font-size: .72rem; font-weight: 700; text-align: center; }
.os-unread--unknown { background: transparent; color: var(--text-secondary, #9aa4b2); border: 1px solid var(--border-color, rgba(255,255,255,.18)); }
.os-muted { opacity: .4; width: 14px; height: 14px; }
.os-protocol .os-proto-icon { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; border: 1px solid var(--border-color, rgba(128,128,128,.3)); }
.os-proto-icon { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; border: 1px solid var(--border-color, rgba(128,128,128,.3)); flex: none; }
.os-rooms-head { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; opacity: .55; margin: 10px 0 2px; }
.os-announce { font-size: .62rem; text-transform: uppercase; letter-spacing: .05em; border: 1px solid var(--warning-color, #f59e0b); color: var(--warning-color, #f59e0b); border-radius: 6px; padding: 0 5px; }
.os-req-actions { padding: 4px 6px 12px 56px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.15)); }
.os-req-btns { display: flex; gap: 8px; }
.os-btn { min-height: 44px; padding: 0 18px; border-radius: 10px; border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; font-weight: 600; }
.os-accept { background: var(--primary-color, #4fd8c4); color: #06211d; border-color: transparent; }
/* §ORGPOCKET polish — four more with markup and no reachable rule. `.os-decline`
   is the negative twin of `.os-accept` directly above and had nothing at all, so
   accept and decline were told apart only by their words. */
.os-decline { color: var(--warning-color, #f59e0b); border-color: var(--border-color, rgba(128,128,128,.3)); }
.os-away, .os-rooms { margin: 6px 0 10px; }
.os-row-noident { display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; flex: 0 0 auto; border-radius: 50%; opacity: .45;
  background: var(--surface-2, rgba(128,128,128,.12)); }
.os-find-door { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 48px;
  margin: 8px 0 10px; padding: 0 12px; border-radius: 12px; cursor: pointer; text-align: left;
  border: 1px dashed var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; }
.os-loading, .os-empty { padding: 24px 6px; opacity: .8; }
.os-empty-line { margin: 0 0 6px; font-size: .9rem; line-height: 1.55; }
/* §CHATCOHERE A5 — the reassurance line sits quieter than the explanation it
   follows; both are unreachable-class candidates, so both are styled here
   rather than left to inherit (§ROOMVIEW: markup with no rule is the defect). */
.os-empty-sub { margin: 0 0 12px; font-size: .82rem; opacity: .72; }
/* §CHATCOHERE D6 — the "not your currency" marker. Muted on purpose: it is a
   caveat on a price, never a warning about the agent. */
.os-cast-fx { opacity: .6; font-size: .92em; }
.os-cast { display: flex; flex-direction: column; gap: 4px; }
.os-cast-row { display: flex; align-items: center; gap: 16px; min-height: 60px; padding: 6px; border: none; background: none; color: inherit; text-align: left; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.12)); cursor: pointer; }
.os-cast-body { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.os-cast-name { font-weight: 700; }
.os-cast-price { font-size: .78rem; opacity: .6; }
.os-cast-go { opacity: .5; }
.os-more { width: 100%; min-height: 44px; border-radius: 10px; border: 1px dashed var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; margin-top: 8px; }
.os-away-note { font-size: .74rem; opacity: .6; margin: 0 0 6px; }
</style>
