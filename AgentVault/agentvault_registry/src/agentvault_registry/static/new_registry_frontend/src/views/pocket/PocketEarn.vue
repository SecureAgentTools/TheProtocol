<!-- POCKET · Earn (2026-07-08) — the Guild in your pocket. Pick a credentialed agent → see YOUR WORK
     (tasks you posted / won, with income) + FIND WORK (open tasks across peer registries) → bid via
     the cross-registry proxy. Reuses the guild endpoints + the active-agent JWT. Δ=0. -->
<template>
  <div class="pe-wrap" ref="ptrEl" @touchstart.passive="ptr.onTouchStart" @touchmove.passive="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
    <div class="pkx-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pkx-spin': ptr.ptrArmed.value }" />
    </div>
    <div class="pe-head" data-tour="pk-earn">
      <h1 class="pe-title">{{ t('pocket.tabs.earn', 'Payments') }}</h1>
      <span class="pe-sub">{{ t('pocket.earn.sub', 'the open agent labor market') }}</span>
    </div>

    <!-- act-as agent -->
    <label for="pocketearn-sel-16" class="pe-lab">{{ t('pocket.earn.workingAs', 'Working as') }}</label>
    <select id="pocketearn-sel-16" v-if="credAgents.length" v-model="agentDid" class="pe-in" @change="switchAgent">
      <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || shorten(a.did) }}</option>
    </select>
    <p v-else class="pe-empty-note">{{ noAgentReason }}</p>

    <!-- tabs -->
    <div v-if="credAgents.length" class="pe-tabs">
      <!-- loop var is `k`, NOT `t`: `t` is the translate function in this scope. -->
      <button v-for="k in ['find','mine']" :key="k" class="pe-tab" :class="{ active: tab === k }" @click="setTab(k as 'find' | 'mine')">
        {{ k === 'find' ? t('pocket.earn.findWork', 'Find work') : t('pocket.earn.yourWork', 'Your work') }}
      </button>
      <button class="pe-post-btn" data-testid="pe-post-open" data-tour="pk-earn-post" @click="openPost()">
        <Icon name="mdi:plus-circle" /> {{ t('pocket.earn.postJob', 'Post a job') }}
      </button>
    </div>

    <!-- FIND WORK -->
    <template v-if="tab === 'find'">
      <div v-if="netLoading" class="pe-list"><div v-for="n in 3" :key="n" class="pe-skel"></div></div>
      <ul v-else class="pe-list">
        <li v-for="o in netOrders" :key="o.id" class="pe-card" @click="selectTask(o)">
          <div class="pe-card-top">
            <span class="pe-host"><Icon name="mdi:web" /> {{ o.host_name }}</span>
            <span class="pe-bounty">{{ fmt(o.bounty) }} <small>{{ o.currency }}</small></span>
          </div>
          <div class="pe-card-title">{{ o.title }}</div>
          <div class="pe-card-meta"><Icon name="mdi:account" /> {{ shortDid(o.poster_did) }}<span v-if="o.bid_count != null"> · {{ bidCountLabel(o.bid_count) }}</span></div>
        </li>
        <li v-if="netErr" class="pe-empty pe-err" data-testid="pe-net-err">
          <Icon name="mdi:alert-circle-outline" class="pe-empty-ico" />
          <p>{{ t('pocket.earn.boardFailed', 'Could not reach the network board') }}: {{ netErr }}</p>
          <button class="pe-retry" @click="loadNetwork">{{ t('cta.retry', 'Retry') }}</button>
        </li>
        <li v-else-if="!netOrders.length" class="pe-empty">
          <Icon name="mdi:briefcase-search" class="pe-empty-ico" />
          <p>{{ t('pocket.earn.noOpenWork', 'No open work on peer registries right now. Pull down to refresh — the network is always moving.') }}</p>
        </li>
      </ul>
      <p v-if="!netLoading" class="pe-peers">{{ peersLabel }}</p>
    </template>

    <!-- YOUR WORK -->
    <template v-else>
      <div v-if="mineLoading" class="pe-list"><div v-for="n in 3" :key="n" class="pe-skel"></div></div>
      <template v-else>
        <div class="pe-earn-card">
          <span class="pe-earn-label">{{ t('pocket.earn.earned', 'Paid (settled)') }}</span>
          <span class="pe-earn-num">{{ fmt(totalEarned) }} <small>{{ frameCcy }}</small></span>
        </div>
        <p v-if="credsErr" class="pe-creds-err" data-testid="pe-creds-err">{{ credsErr }}</p>
        <!-- trust that travels: signed work credentials earned on OTHER registries -->
        <div v-if="creds.length" class="pe-creds">
          <div class="pe-creds-head"><Icon name="mdi:shield-check" /> {{ t('pocket.earn.workCreds', 'Work credentials') }} <span class="pe-creds-hint">{{ t('pocket.earn.workCredsHint', 'reputation that traveled home') }}</span></div>
          <ul class="pe-creds-list">
            <li v-for="c in creds" :key="c.order_id" class="pe-cred">
              <span class="pe-cred-host"><Icon name="mdi:web" /> {{ hostName(c.host_registry) }}</span>
              <span class="pe-cred-stars">{{ '★'.repeat(c.stars) }}</span>
              <span class="pe-cred-amt">{{ fmt(c.bounty) }} <small>{{ c.currency }}</small></span>
              <Icon v-if="c.verified" name="mdi:check-circle" class="pe-cred-ok" />
            </li>
          </ul>
        </div>
        <ul class="pe-list">
          <li v-for="o in myOrders" :key="o.id" class="pe-card" data-testid="pe-my-order" @click="openOrder(o)">
            <div class="pe-card-top">
              <span class="pe-role" :class="o._role">{{ roleLabel(o._role) }}</span>
              <span class="pe-bounty" :class="{ paid: o.status === 'settled' && o._role === 'worker' }">{{ fmt(o.bounty) }} <small>{{ o.currency }}</small></span>
            </div>
            <div class="pe-card-title">{{ o.title }}</div>
            <div class="pe-card-meta"><span class="pe-st" :class="'st-' + o.status">{{ statusLabel(o.status) }}</span></div>
          </li>
          <li v-if="mineErr" class="pe-empty pe-err" data-testid="pe-mine-err">
            <Icon name="mdi:alert-circle-outline" class="pe-empty-ico" />
            <p>{{ mineErr }}</p>
            <button class="pe-retry" @click="loadMine">{{ t('cta.retry', 'Retry') }}</button>
          </li>
          <li v-else-if="!myOrders.length" class="pe-empty">
            <Icon name="mdi:briefcase" class="pe-empty-ico" />
            <p>{{ t('pocket.earn.noWorkYet', 'No work yet for this agent. Find a task under “Find work” and place a bid.') }}</p>
          </li>
        </ul>
      </template>
    </template>

    <!-- BID sheet -->
    <transition name="pe-sheet">
      <div v-if="bidTask" class="pe-scrim" @click.self="bidTask = null">
        <div class="pe-bidsheet" role="dialog" aria-modal="true">
          <div class="pe-grip"></div>
          <h2 class="pe-bid-title"><Icon name="mdi:gavel" /> {{ t('pocket.earn.bidTitle', 'Bid on this task') }}</h2>
          <div class="pe-bid-task">{{ bidTask.title }}</div>
          <div class="pe-bid-host"><Icon name="mdi:web" /> {{ tp('pocket.earn.hostedOn', 'Hosted on {host} — routes through your home registry (payout on your ledger, 0.5% network fee).', { host: bidTask.host_name }) }}</div>
          <label class="pe-lab">{{ t('pocket.earn.yourPrice', 'Your price') }}</label>
          <div class="pe-amt-row"><input v-model="bidPrice" class="pe-in pe-amt" inputmode="decimal" :placeholder="String(bidTask.bounty)" /><span class="pe-amt-ccy">{{ bidTask.currency }}</span></div>
          <input v-model.trim="bidPitch" class="pe-in" :placeholder="t('pocket.earn.whyYou', 'Why you? (optional)')" maxlength="300" />
          <div class="pe-actions">
            <button class="pe-btn pe-ghost" @click="bidTask = null">{{ t('common.cancel', 'Cancel') }}</button>
            <button class="pe-btn pe-primary" :disabled="bidding || !Number(bidPrice)" @click="doBid">{{ bidding ? t('pocket.earn.bidding', 'Bidding…') : t('pocket.earn.placeBid', 'Place bid') }}</button>
          </div>
          <p v-if="bidResult" class="pe-bid-result" :class="bidResult.ok ? 'ok' : 'bad'">{{ bidResult.msg }}</p>
        </div>
      </div>
    </transition>

    <!-- §POCKETBRIDGE2 W5 — THE ORDER SHEET. NEEDS YOU advertised "work
         awarded to you" and "deliveries to verify"; this is where those stop
         being doors onto walls. Gating = services/guildActions (ONE brain,
         unit-tested); execution = the existing guildApi rails only (S3). -->
    <transition name="pe-sheet">
      <div v-if="orderSheet" class="pe-scrim" @click.self="closeOrder">
        <div class="pe-bidsheet pe-ordersheet" role="dialog" aria-modal="true" data-testid="pe-order-sheet">
          <div class="pe-grip"></div>
          <h2 class="pe-bid-title"><Icon name="mdi:briefcase" /> {{ orderSheet.title }}</h2>
          <div class="pe-ord-meta">
            <span class="pe-st" :class="'st-' + (det?.order?.status || orderSheet.status)">{{ statusLabel(det?.order?.status || orderSheet.status) }}</span>
            <span class="pe-bounty">{{ fmt(orderSheet.bounty) }} <small>{{ orderSheet.currency || frameCcy }}</small></span>
            <span class="pe-role" :class="gate.role">{{ roleLabel(gate.role) }}</span>
          </div>

          <div v-if="detLoading" class="pe-skel" style="height:56px"></div>
          <p v-else-if="detErr" class="pe-ord-err" data-testid="pe-det-err">{{ detErr }} <button class="pe-retry" @click="loadDetail">{{ t('cta.retry', 'Retry') }}</button></p>
          <template v-else>
            <p v-if="!gate.actions.length && gate.note" class="pe-ord-note" data-testid="pe-ord-note">{{ noteText(gate) }}</p>
            <!-- §POCKETBRIDGE5 A' — a disputed engagement doors into the
                 dispute record (the WORK modal), never a dead status chip. -->
            <button v-if="det?.order?.status === 'disputed'" class="pe-btn pe-ghost pe-wide" data-testid="pe-ord-dispute-door" @click="goDisputeRecord">
              <Icon name="mdi:gavel" /> {{ t('pocket.earn.viewDispute', 'View the dispute record') }}
            </button>

            <!-- poster: bids to award -->
            <template v-if="canDo('award')">
              <label class="pe-lab">{{ t('pocket.earn.bidsLabel', 'Bids — award one to start the work') }}</label>
              <ul class="pe-ord-bids">
                <li v-for="b in det?.bids || []" :key="b.id" class="pe-ord-bid">
                  <div class="pe-ord-bid-body">
                    <span class="pe-ord-bidder">{{ shortDid(b.bidder_did) }}</span>
                    <span class="pe-ord-price">{{ fmt(b.price) }} <small>{{ orderSheet.currency || frameCcy }}</small></span>
                    <p v-if="b.pitch" class="pe-ord-pitch">{{ b.pitch }}</p>
                  </div>
                  <button class="pe-btn pe-primary pe-award" :disabled="acting" @click="doAward(b)">{{ t('pocket.earn.award', 'Award') }}</button>
                </li>
                <li v-if="!(det?.bids || []).length" class="pe-ord-note">{{ t('pocket.earn.bidsUnreadable', 'The bid list could not be read — pull to refresh or retry.') }}</li>
              </ul>
            </template>

            <!-- worker: submit -->
            <template v-if="canDo('submit')">
              <label class="pe-lab">{{ t('pocket.earn.deliverable', 'Deliverable') }}</label>
              <textarea v-model.trim="deliverNote" class="pe-in pe-ta" rows="3"
                        :placeholder="t('pocket.earn.deliverablePlaceholder', 'What you delivered — a link, a hash, a summary. The poster verifies exactly this.')"></textarea>
              <button class="pe-btn pe-primary pe-wide" :disabled="acting || !deliverNote" @click="doSubmit">
                {{ acting ? t('pocket.earn.submitting', 'Submitting…') : t('pocket.guild.action.submit', 'Submit work') }}
              </button>
            </template>

            <!-- poster: verify (THE money moment) -->
            <template v-if="canDo('verify')">
              <div v-if="deliverableText" class="pe-ord-deliv">
                <label class="pe-lab">{{ t('pocket.earn.delivered', 'Delivered') }}</label>
                <p>{{ deliverableText }}</p>
              </div>
              <label class="pe-lab">{{ t('pocket.earn.rateWork', 'Rate the work') }}</label>
              <div class="pe-stars" role="radiogroup" :aria-label="t('pocket.earn.stars', 'Stars')">
                <button v-for="i in 5" :key="i" class="pe-star" :class="{ on: i <= stars }"
                        :aria-label="starLabel(i)" @click="stars = i">★</button>
              </div>
              <div class="pe-actions">
                <button class="pe-btn pe-ghost" :disabled="acting" @click="doVerify(false)">{{ t('pocket.earn.reject', 'Reject') }}</button>
                <button class="pe-btn pe-primary" :disabled="acting" @click="doVerify(true)">
                  {{ acting ? t('pocket.earn.settling', 'Settling…') : tp('pocket.earn.acceptPay', 'Accept & pay {amount}', { amount: fmt(orderSheet.bounty) }) }}
                </button>
              </div>
              <p class="pe-ord-note">{{ t('pocket.earn.acceptNote', 'Accepting releases the escrowed bounty to the worker — this moves money.') }}</p>
            </template>

            <!-- poster: cancel -->
            <button v-if="canDo('cancel')" class="pe-btn pe-danger pe-wide" :disabled="acting" @click="doCancel">
              {{ acting ? t('pocket.earn.cancelling', 'Cancelling…') : t('pocket.guild.action.cancel', 'Cancel order') }}
            </button>

            <!-- compact history -->
            <ul v-if="(det?.events || []).length" class="pe-ord-events">
              <li v-for="(ev, i) in (det?.events || []).slice(-4)" :key="i">{{ ev.kind || ev.event_type || ev.type }} · {{ shortWhen(ev.at || ev.created_at) }}</li>
            </ul>
          </template>

          <p v-if="ordResult" class="pe-bid-result" :class="ordResult.ok ? 'ok' : 'bad'" data-testid="pe-ord-result">{{ ordResult.msg }}</p>
        </div>
      </div>
    </transition>

    <!-- §POCKETBRIDGE4 WS-G — POST A JOB. The poster half of the loop, on the
         phone. Posting ESCROWS the bounty (the money moment) → biometric when
         the pocket lock is armed, and the result names what actually moved. -->
    <transition name="pe-sheet">
      <div v-if="postOpen" class="pe-scrim" @click.self="closePost">
        <div class="pe-bidsheet" role="dialog" aria-modal="true" data-testid="pe-post-sheet">
          <div class="pe-grip"></div>
          <h2 class="pe-bid-title"><Icon name="mdi:briefcase" /> {{ t('pocket.earn.postJob', 'Post a job') }}</h2>
          <div class="pe-bid-host"><Icon name="mdi:shield-lock" /> {{ t('pocket.earn.escrowNote', 'The bounty is escrowed from your agent when you post — returned in full if you cancel while the order is still open.') }}</div>
          <!-- §FOREIGNACT — posting escrows real money FROM the acting agent, on
               the acting agent's registry, in that registry's currency. -->
          <ActingContextNotice strong />
          <label class="pe-lab">{{ t('pocket.earn.jobTitle', 'Title') }}</label>
          <input v-model.trim="postForm.title" class="pe-in" data-testid="pe-post-title" :placeholder="t('pocket.earn.jobTitlePlaceholder', 'What needs doing?')" maxlength="140" />
          <label class="pe-lab">{{ t('pocket.earn.details', 'Details (optional)') }}</label>
          <input v-model.trim="postForm.spec" class="pe-in" :placeholder="t('pocket.earn.detailsPlaceholder', 'Spec / acceptance criteria')" maxlength="500" />
          <label class="pe-lab">{{ t('pocket.earn.bounty', 'Bounty') }}</label>
          <div class="pe-amt-row">
            <input v-model="postForm.bounty" class="pe-in pe-amt" data-testid="pe-post-bounty" inputmode="decimal" placeholder="0" />
            <span class="pe-amt-ccy">{{ frameCcy || t('pocket.earn.native', 'native') }}</span>
          </div>
          <div class="pe-actions">
            <button class="pe-btn pe-ghost" @click="closePost">{{ t('common.cancel', 'Cancel') }}</button>
            <button class="pe-btn pe-primary" data-testid="pe-post-go" :disabled="posting || !postForm.title.trim() || !(Number(postForm.bounty) > 0)" @click="doPost">
              {{ posting ? t('pocket.earn.posting', 'Posting…') : t('pocket.earn.postEscrow', 'Post & escrow') }}
            </button>
          </div>
          <p v-if="postResult" class="pe-bid-result" :class="postResult.ok ? 'ok' : 'bad'" data-testid="pe-post-result">{{ postResult.msg }}</p>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'
import { useAuthStore } from '@/stores/auth'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { guildApi } from '@/services/api/guild'
import { useCurrency } from '@/composables/useCurrency'
import { useActingContext } from '@/composables/useActingContext'
// §FOREIGNACT — where this agent's money actually lives (null-not-guessed for a
// foreign agent whose registry card has not answered yet).
const { actingCurrencyLabel } = useActingContext()
import { actionsFor, type GuildActionOffer } from '@/services/guildActions'
import { usePocketLock } from '@/composables/usePocketLock'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { useGuildLabels } from '@/composables/useGuildLabels'

const { t, tp } = useI18n()
// ONE label brain with the bridge WORK view — guildActions stays pure.
const { noteText, roleLabel, statusLabel } = useGuildLabels()
const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { tab.value === 'find' ? loadNetwork() : loadMine() })
const auth = useAuthStore()
const frameCcy = ref('')
// §FOREIGNACT — staking/guild money belongs to the ACTING agent's registry.
try { frameCcy.value = actingCurrencyLabel.value } catch {}

const tab = ref<'find' | 'mine'>('find')
const agentDid = ref('')
const netOrders = ref<any[]>([]); const netLoading = ref(true); const netPeers = ref(0)
const myOrders = ref<any[]>([]); const mineLoading = ref(false)
const creds = ref<any[]>([])
const hostName = (u: string) => { try { return new URL(u).hostname.replace('.theprotocol.cloud', '').replace('.op', '').replace('.frame-b', '') } catch { return u } }
const netErr = ref(''); const mineErr = ref(''); const credsErr = ref('')
const bidTask = ref<any | null>(null); const bidPrice = ref(''); const bidPitch = ref(''); const bidding = ref(false)
const bidResult = ref<{ ok: boolean; msg: string } | null>(null)

// §POCKETBRIDGE #PK3 — the ONE shared agent-context brain (sealed-vault aware).
const { credAgents, noAgentReason, ensureAgentFor } = usePocketAgent()
const totalEarned = computed(() =>
  myOrders.value.filter((o: any) => o.status === 'settled' && o._role === 'worker')
    .reduce((s: number, o: any) => s + Number(o.bounty || 0), 0))

const shorten = (s: string) => !s ? '—' : s.length > 26 ? s.slice(0, 14) + '…' + s.slice(-6) : s
const shortDid = (s?: string) => !s ? '—' : s.length > 22 ? s.slice(0, 11) + '…' + s.slice(-4) : s
const fmt = (v: any) => { const n = Number(v); return isNaN(n) ? String(v ?? '0') : n.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) }

/* Counted nouns compose in JS: the number renders from the template, the noun
   picks its one/many key (see PocketHome for the same shape). */
const bidCountLabel = (n: number) =>
  `${n} ${n === 1 ? t('pocket.earn.bidOne', 'bid') : t('pocket.earn.bidMany', 'bids')}`
const peersLabel = computed(() => {
  const n = netPeers.value
  return tp(n === 1 ? 'pocket.earn.polledOne' : 'pocket.earn.polledMany',
            n === 1 ? 'Polled {n} peer registry.' : 'Polled {n} peer registries.', { n })
})
const starLabel = (n: number) =>
  `${n} ${n === 1 ? t('pocket.earn.starOne', 'star') : t('pocket.earn.starMany', 'stars')}`

const ensureAgent = () => ensureAgentFor(agentDid.value)
let mineLoaded = false
// param is `k`, NOT `t`: `t` is the translate function in this scope.
function setTab(k: 'find' | 'mine') { tab.value = k; if (k === 'mine' && !mineLoaded) { mineLoaded = true; loadMine() } }
async function switchAgent() { mineLoaded = false; if (tab.value === 'mine') { mineLoaded = true; loadMine() } }

async function loadNetwork() {
  netLoading.value = true; netErr.value = ''
  try { const r = await guildApi.networkBoard(); netOrders.value = r.orders || []; netPeers.value = r.peers_polled || 0 }
  catch (e: any) {
    // §POCKETBRIDGE2 W1 — an unreachable board is not an empty board.
    netErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { netLoading.value = false }
}
async function loadMine() {
  mineLoading.value = true; mineErr.value = ''; credsErr.value = ''
  try {
    if (!await ensureAgent()) {
      myOrders.value = []
      mineErr.value = noAgentReason.value || t('pocket.earn.authFailed', 'Could not authenticate as your agent.')
      return
    }
    const r: any = await guildApi.mine()
    myOrders.value = (r.orders || []).map((o: any) => ({ ...o, _role: o.worker_did === agentDid.value ? 'worker' : 'poster' }))
    try { const cr = await guildApi.myCredentials(); creds.value = cr.credentials || [] }
    catch { credsErr.value = t('pocket.earn.credsFailed', 'Work credentials could not be loaded right now.') }
  } catch (e: any) {
    mineErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { mineLoading.value = false }
}

function selectTask(o: any) { bidTask.value = o; bidPrice.value = ''; bidPitch.value = ''; bidResult.value = null }
async function doBid() {
  if (!bidTask.value || !Number(bidPrice.value)) return
  bidding.value = true; bidResult.value = null
  try {
    if (!await ensureAgent()) { bidResult.value = { ok: false, msg: t('pocket.earn.authFailed', 'Could not authenticate as your agent.') }; return }
    await guildApi.crossRegistryAct({ target_registry_url: bidTask.value.host_registry, order_id: bidTask.value.id, action: 'bid', price: Number(bidPrice.value), pitch: bidPitch.value || undefined })
    bidResult.value = { ok: true, msg: t('pocket.earn.bidPlaced', 'Bid placed via your home registry.') }
    try { (navigator as any).vibrate?.(8) } catch {}
    setTimeout(() => { bidTask.value = null }, 1200)
  } catch (e: any) {
    bidResult.value = { ok: false, msg: e?.response?.data?.detail || e?.message || t('pocket.earn.bidFailed', 'Bid failed') }
  } finally { bidding.value = false }
}

/* ── §POCKETBRIDGE2 W5 — the order sheet ─────────────────── */
const lock = usePocketLock()
const route = useRoute()
const orderSheet = ref<any | null>(null)
const det = ref<{ order: any; bids: any[]; events: any[] } | null>(null)
const detLoading = ref(false)
const detErr = ref('')
const acting = ref(false)
const ordResult = ref<{ ok: boolean; msg: string } | null>(null)
const deliverNote = ref('')
const stars = ref(5)

const gate = computed(() => actionsFor(det.value?.order || orderSheet.value, agentDid.value || null))
const canDo = (k: GuildActionOffer['key']) => gate.value.actions.some(a => a.key === k)
const deliverableText = computed(() => {
  const d = det.value?.order?.deliverable
  if (!d) return ''
  if (typeof d === 'string') return d
  return d.note || d.summary || JSON.stringify(d)
})
const shortWhen = (v: any) => { try { return new Date(v).toLocaleString(appLocale(), { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return String(v || '') } }

function openOrder(o: any) {
  orderSheet.value = o; det.value = null; detErr.value = ''; ordResult.value = null
  deliverNote.value = ''; stars.value = 5
  void loadDetail()
}
function closeOrder() { orderSheet.value = null }
// §POCKETBRIDGE5 A' — the shell owns the WORK modal; the query is the door.
function goDisputeRecord() { closeOrder(); router.push({ query: { ...route.query, work: 'disputes' } }).catch(() => {}) }
async function loadDetail() {
  if (!orderSheet.value) return
  detLoading.value = true; detErr.value = ''
  try { det.value = await guildApi.detail(String(orderSheet.value.id)) }
  catch (e: any) { detErr.value = e?.response?.data?.detail || e?.message || t('pocket.earn.orderLoadFailed', 'Could not load the order.') }
  finally { detLoading.value = false }
}

async function runAction(money: boolean, fn: () => Promise<any>, okMsg: string) {
  acting.value = true; ordResult.value = null
  try {
    if (!await ensureAgent()) { ordResult.value = { ok: false, msg: noAgentReason.value || t('pocket.earn.authFailed', 'Could not authenticate as your agent.') }; return }
    if (money && lock.enabled.value && !(await lock.verify().catch(() => false))) {
      ordResult.value = { ok: false, msg: t('pocket.earn.bioFailedNothing', 'Biometric confirmation failed — nothing moved.') }; return
    }
    await fn()
    ordResult.value = { ok: true, msg: okMsg }
    try { (navigator as any).vibrate?.([10, 30, 10]) } catch {}
    await loadDetail()
    void loadMine()
  } catch (e: any) {
    ordResult.value = { ok: false, msg: e?.response?.data?.detail || e?.message || t('pocket.earn.actionFailed', 'Action failed — nothing changed.') }
  } finally { acting.value = false }
}
const doAward = (b: any) => runAction(false, () => guildApi.award(String(orderSheet.value.id), b.id), t('pocket.earn.awarded', 'Bid awarded — the worker can start.'))
const doSubmit = () => runAction(false, () => guildApi.submitWork(String(orderSheet.value.id), { note: deliverNote.value }), t('pocket.earn.submitted', 'Work submitted — the poster verifies next.'))
const doVerify = (accept: boolean) => runAction(accept, () => guildApi.verify(String(orderSheet.value.id), accept, stars.value), accept ? t('pocket.earn.accepted', 'Accepted — the bounty is released to the worker.') : t('pocket.earn.rejected', 'Rejected — the worker can revise and resubmit.'))
const doCancel = () => runAction(false, () => guildApi.cancel(String(orderSheet.value.id)), t('pocket.earn.orderCancelled', 'Order cancelled.'))

/* ── §POCKETBRIDGE4 WS-G — post a job (the poster half) ───── */
const router = useRouter()
const postOpen = ref(false)
const posting = ref(false)
const postResult = ref<{ ok: boolean; msg: string } | null>(null)
const postForm = ref({ title: '', spec: '', bounty: '' })
function openPost(prefill?: { title?: string; bounty?: string }) {
  postForm.value = { title: prefill?.title || '', spec: '', bounty: prefill?.bounty || '' }
  postResult.value = null
  postOpen.value = true
}
function closePost() { postOpen.value = false }
async function doPost() {
  const bounty = Number(postForm.value.bounty)
  const title = postForm.value.title.trim()
  if (posting.value) return
  if (!title || !Number.isFinite(bounty) || bounty <= 0) {
    postResult.value = { ok: false, msg: t('pocket.earn.postValidation', 'A title and a positive bounty are required.') }; return
  }
  posting.value = true; postResult.value = null
  try {
    if (!await ensureAgent()) { postResult.value = { ok: false, msg: noAgentReason.value || t('pocket.earn.authFailed', 'Could not authenticate as your agent.') }; return }
    // Posting ESCROWS the bounty — the money moment gets the biometric.
    if (lock.enabled.value && !(await lock.verify().catch(() => false))) {
      postResult.value = { ok: false, msg: t('pocket.earn.bioFailedEscrow', 'Biometric confirmation failed — nothing was escrowed.') }; return
    }
    await guildApi.post({ title, spec: postForm.value.spec.trim() || undefined, bounty, currency: frameCcy.value || undefined })
    postResult.value = { ok: true, msg: tp('pocket.earn.posted', 'Posted — {amount} escrowed. Workers can now bid; award one to start.',
                                            { amount: `${fmt(bounty)}${frameCcy.value ? ' ' + frameCcy.value : ''}` }) }
    try { (navigator as any).vibrate?.([10, 30, 10]) } catch { /* haptics optional */ }
    mineLoaded = true
    void loadMine()
  } catch (e: any) {
    postResult.value = { ok: false, msg: e?.response?.data?.detail || e?.message || t('pocket.earn.postFailed', 'Posting failed — nothing was escrowed.') }
  } finally { posting.value = false }
}
function openPostFromQuery() {
  // Voice/assistant door: /pocket/payments?post=1&title=…&bounty=… — prefill only,
  // the human confirms. The query is consumed so back/refresh cannot re-open it.
  if (String(route.query.post || '') !== '1') return
  openPost({ title: String(route.query.title || ''), bounty: String(route.query.bounty || '') })
  const q: Record<string, any> = { ...route.query }
  delete q.post; delete q.title; delete q.bounty
  router.replace({ query: q }).catch(() => { /* aborted nav is fine */ })
}
watch(() => route.query.post, () => openPostFromQuery())

async function openFromQuery() {
  // W5.3 — a NEEDS YOU row lands directly on ITS order: /pocket/payments?order=<id>
  const oid = String(route.query.order || '')
  if (!oid || String(orderSheet.value?.id || '') === oid) return
  setTab('mine')
  try {
    const d = await guildApi.detail(oid)
    orderSheet.value = d.order; det.value = d; detErr.value = ''
  } catch (e: any) {
    // the sheet opens with the error named rather than silently not opening
    orderSheet.value = { id: oid, title: 'Order ' + oid.slice(0, 8), status: '', bounty: '' }
    detErr.value = e?.response?.data?.detail || e?.message || 'Could not load the order.'
  }
}
// query-only navigation never remounts (§NOTIFLOG) — watch, don't just mount.
watch(() => route.query.order, () => { void openFromQuery() })

// §POCKETBRIDGE2 W2 — Escape closes the sheets (he tests on a desktop browser;
// a scrim-only close is a touch assumption. R11: a keydown on a non-focusable
// overlay never fires — listen on window while anything is open).
function onEscKey(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (orderSheet.value) closeOrder()
  else if (postOpen.value) closePost()
  else if (bidTask.value) bidTask.value = null
}
onBeforeUnmount(() => window.removeEventListener('keydown', onEscKey))

onMounted(async () => {
  window.addEventListener('keydown', onEscKey)
  if (credAgents.value.length) agentDid.value = (auth as any).activeAgent?.did || credAgents.value[0].did
  loadNetwork()
  void openFromQuery()
  openPostFromQuery()
})
</script>

<style scoped>
.pe-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; box-sizing: border-box; }
.pe-head { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.8rem; }
.pe-title { font-size: 1.15rem; margin: 0; }
.pe-sub { font-size: 0.72rem; opacity: 0.5; }
.pe-lab { display: block; font-size: 0.68rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.5; font-weight: 600; margin: 0.5rem 0 0.3rem; }
.pe-in { width: 100%; box-sizing: border-box; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 0.72rem 0.85rem; color: #e6edf3; font-size: 16px; min-height: 44px; outline: none; }
.pe-in:focus { border-color: rgba(0,212,255,0.45); }
.pe-empty-note { font-size: 0.8rem; opacity: 0.6; margin: 0.6rem 0; }
.pe-err p { color: #ff9a9a; }
.pe-creds-err { font-size: 0.74rem; color: #f0b46a; margin: 0.2rem 0 0.5rem; }
.pe-ordersheet { max-height: 82vh; overflow-y: auto; }
.pe-ord-meta { display: flex; align-items: center; gap: 0.6rem; margin: 0.2rem 0 0.7rem; flex-wrap: wrap; }
.pe-ord-err { color: #ff9a9a; font-size: 0.8rem; }
.pe-ord-note { font-size: 0.78rem; opacity: 0.65; margin: 0.4rem 0; }
.pe-ord-bids { list-style: none; margin: 0 0 0.6rem; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pe-ord-bid { display: flex; align-items: center; gap: 0.6rem; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 0.6rem 0.7rem; }
.pe-ord-bid-body { flex: 1 1 auto; min-width: 0; }
.pe-ord-bidder { font-size: 0.78rem; opacity: 0.75; margin-right: 0.5rem; }
.pe-ord-price { font-weight: 700; font-variant-numeric: tabular-nums; }
.pe-ord-pitch { margin: 0.2rem 0 0; font-size: 0.76rem; opacity: 0.6; }
.pe-award { flex: 0 0 auto; }
.pe-ta { resize: vertical; min-height: 74px; }
.pe-wide { width: 100%; margin: 0.3rem 0; }
.pe-danger { background: rgba(255,77,77,0.12); border: 1px solid rgba(255,77,77,0.4); color: #ff8a8a; }
.pe-stars { display: flex; gap: 0.2rem; margin: 0.2rem 0 0.5rem; }
.pe-star { background: none; border: none; font-size: 1.5rem; line-height: 1; color: rgba(230,237,243,0.25); cursor: pointer; min-width: 44px; min-height: 44px; }
.pe-star.on { color: #fbbf24; }
.pe-ord-deliv { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 0.5rem 0.7rem; margin-bottom: 0.4rem; }
.pe-ord-deliv p { margin: 0.2rem 0 0; font-size: 0.82rem; white-space: pre-wrap; word-break: break-word; }
.pe-ord-events { list-style: none; margin: 0.6rem 0 0; padding: 0.5rem 0 0; border-top: 1px solid rgba(255,255,255,0.07); font-size: 0.7rem; opacity: 0.5; display: flex; flex-direction: column; gap: 0.2rem; }
.pe-retry { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.2); border-radius: 10px;
  color: inherit; padding: 0.5rem 1rem; min-height: 44px; cursor: pointer; margin-top: 0.4rem; }
.pe-tabs { display: flex; gap: 0.4rem; margin: 0.9rem 0 0.7rem; }
.pe-tab { flex: 1 1 0; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 11px; padding: 0.6rem; min-height: 44px; color: rgba(230,237,243,0.6); font-size: 0.82rem; font-weight: 600; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pe-tab.active { background: rgba(0,212,255,0.1); border-color: rgba(0,212,255,0.3); color: var(--nc-primary, #00d4ff); }
.pe-post-btn { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 0.3rem; background: rgba(52,211,153,0.08); border: 1px solid rgba(52,211,153,0.3); border-radius: 11px; padding: 0.6rem 0.8rem; min-height: 44px; color: #34d399; font-size: 0.82rem; font-weight: 700; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pe-post-btn :deep(svg) { width: 1rem; height: 1rem; }
.pe-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pe-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; padding: 0.75rem 0.85rem; transition: background 0.15s; }
.pe-card:active { background: rgba(255,255,255,0.06); }
.pe-card-top { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.35rem; }
.pe-host { display: inline-flex; align-items: center; gap: 0.2rem; font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.04em; color: #7dd3fc; background: rgba(125,211,252,0.1); border: 1px solid rgba(125,211,252,0.28); padding: 0.06rem 0.4rem; border-radius: 5px; }
.pe-host :deep(svg) { width: 0.7rem; height: 0.7rem; }
.pe-bounty { font-variant-numeric: tabular-nums; font-weight: 700; font-size: 0.95rem; }
.pe-bounty small { font-size: 0.6rem; opacity: 0.5; font-weight: 600; }
.pe-bounty.paid { color: #34d399; }
.pe-card-title { font-size: 0.9rem; font-weight: 600; }
.pe-card-meta { display: flex; align-items: center; gap: 0.3rem; font-size: 0.7rem; opacity: 0.55; margin-top: 0.25rem; }
.pe-card-meta :deep(svg) { width: 0.8rem; height: 0.8rem; }
.pe-role { font-size: 0.58rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.08rem 0.45rem; border-radius: 5px; font-weight: 700; }
.pe-role.worker { color: #34d399; background: rgba(16,185,129,0.14); }
.pe-role.poster { color: #a78bfa; background: rgba(167,139,250,0.14); }
.pe-st { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.7; }
.st-settled { color: #34d399; } .st-disputed { color: #ff8a8a; } .st-open { color: #7dd3fc; } .st-awarded, .st-submitted { color: #fbbf24; }
.pe-earn-card { display: flex; align-items: center; justify-content: space-between; background: linear-gradient(160deg, rgba(16,185,129,0.14), rgba(16,185,129,0.03)); border: 1px solid rgba(16,185,129,0.28); border-radius: 15px; padding: 0.9rem 1rem; margin-bottom: 0.7rem; }
.pe-earn-label { font-size: 0.72rem; letter-spacing: 0.05em; text-transform: uppercase; opacity: 0.7; font-weight: 600; }
.pe-earn-num { font-size: 1.3rem; font-weight: 750; font-variant-numeric: tabular-nums; color: #34d399; }
.pe-earn-num small { font-size: 0.62rem; opacity: 0.6; }
.pe-creds { background: rgba(16,185,129,0.05); border: 1px solid rgba(16,185,129,0.2); border-radius: 14px; padding: 0.7rem 0.85rem; margin-bottom: 0.7rem; }
.pe-creds-head { display: flex; align-items: center; gap: 0.35rem; font-size: 0.74rem; font-weight: 700; color: #34d399; margin-bottom: 0.45rem; }
.pe-creds-head :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pe-creds-hint { font-weight: 500; opacity: 0.6; font-size: 0.66rem; margin-left: auto; color: #e6edf3; }
.pe-creds-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.pe-cred { display: flex; align-items: center; gap: 0.5rem; font-size: 0.76rem; }
.pe-cred-host { display: inline-flex; align-items: center; gap: 0.2rem; color: #7dd3fc; font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.04em; }
.pe-cred-host :deep(svg) { width: 0.7rem; height: 0.7rem; }
.pe-cred-stars { color: #fbbf24; letter-spacing: 0.05em; font-size: 0.7rem; }
.pe-cred-amt { margin-left: auto; font-variant-numeric: tabular-nums; font-weight: 650; }
.pe-cred-amt small { font-size: 0.58rem; opacity: 0.55; }
.pe-cred-ok { width: 0.85rem; height: 0.85rem; color: #34d399; flex: 0 0 auto; }
.pe-empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2rem 1rem; opacity: 0.55; text-align: center; }
.pe-empty-ico { width: 2rem; height: 2rem; }
.pe-empty p { margin: 0; font-size: 0.84rem; max-width: 22rem; }
/* §FESUITE (2026-10-14, the V0615 proof on sbx-beta): at opacity 0.4 this line drew #606468 on #06080c, 3.35:1, under AA's
   4.5:1; it renders only once the peer read lands, so axe met it only when that read beat the scan. At 0.62 it is about
   6:1 and still the quietest line on the page. */
.pe-peers { font-size: 0.68rem; opacity: 0.62; text-align: center; margin-top: 0.7rem; }
.pe-skel { height: 4.2rem; border-radius: 14px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pe-shim 1.3s ease-in-out infinite; }
/* bid sheet */
.pe-scrim { position: fixed; inset: 0; z-index: 90; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px); display: flex; align-items: flex-end; }
.pe-bidsheet { width: 100%; max-width: 560px; margin: 0 auto; background: #0c0f15; border: 1px solid rgba(255,255,255,0.09); border-radius: 22px 22px 0 0; padding: 0.8rem 1.1rem calc(1.4rem + env(safe-area-inset-bottom, 0px)); box-shadow: 0 -20px 50px rgba(0,0,0,0.5); }
.pe-grip { width: 40px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.1rem auto 0.9rem; }
.pe-bid-title { display: flex; align-items: center; gap: 0.45rem; font-size: 1.05rem; margin: 0 0 0.7rem; }
.pe-bid-title :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }
.pe-bid-task { font-size: 0.95rem; font-weight: 600; margin-bottom: 0.4rem; }
.pe-bid-host { font-size: 0.74rem; color: #7dd3fc; background: rgba(125,211,252,0.07); border: 1px solid rgba(125,211,252,0.2); border-radius: 10px; padding: 0.5rem 0.65rem; margin-bottom: 0.5rem; display: flex; gap: 0.35rem; align-items: flex-start; }
.pe-bid-host :deep(svg) { width: 0.9rem; height: 0.9rem; flex-shrink: 0; margin-top: 1px; }
.pe-amt-row { position: relative; }
.pe-amt { font-size: 1.35rem; font-weight: 700; font-variant-numeric: tabular-nums; padding-right: 3.5rem; }
.pe-amt-ccy { position: absolute; right: 0.9rem; top: 50%; transform: translateY(-50%); font-size: 0.82rem; font-weight: 600; opacity: 0.55; }
.pe-actions { display: flex; gap: 0.6rem; margin-top: 1rem; }
.pe-btn { flex: 1 1 0; border-radius: 13px; padding: 0.85rem; font-size: 0.9rem; font-weight: 650; cursor: pointer; min-height: 48px; border: 1px solid transparent; -webkit-tap-highlight-color: transparent; }
.pe-btn:disabled { opacity: 0.45; }
.pe-ghost { background: rgba(255,255,255,0.05); border-color: rgba(255,255,255,0.1); color: #e6edf3; }
.pe-primary { background: linear-gradient(160deg, rgba(0,212,255,0.2), rgba(0,212,255,0.08)); border-color: rgba(0,212,255,0.4); color: #e6edf3; }
.pe-bid-result { text-align: center; font-size: 0.82rem; margin: 0.7rem 0 0; }
.pe-bid-result.ok { color: #34d399; } .pe-bid-result.bad { color: #ff8a8a; }
.pe-sheet-enter-active, .pe-sheet-leave-active { transition: opacity 0.2s ease; }
.pe-sheet-enter-active .pe-bidsheet, .pe-sheet-leave-active .pe-bidsheet { transition: transform 0.24s cubic-bezier(0.34,1.3,0.64,1); }
.pe-sheet-enter-from, .pe-sheet-leave-to { opacity: 0; }
.pe-sheet-enter-from .pe-bidsheet, .pe-sheet-leave-to .pe-bidsheet { transform: translateY(100%); }
@keyframes pe-shim { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .pe-skel { animation: none; } .pe-sheet-enter-active .pe-bidsheet, .pe-sheet-leave-active .pe-bidsheet { transition: none; } }
</style>
