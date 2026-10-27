<!-- POCKET · Home — the home screen (AAA+ 2026-07-08): hero balance with sheen, stat chips,
     quick actions, and ACCOUNTS (top agents by real balance). -->
<template>
  <div class="ph-wrap" ref="scrollEl">
    <!-- pull-to-refresh indicator -->
    <div class="ph-ptr" :style="{ height: ptrH + 'px', opacity: ptrH ? 1 : 0 }">
      <Icon name="mdi:refresh" :class="{ 'ph-spin': loading || ptrArmed }" />
    </div>

    <!-- hero balance card -->
    <section class="ph-balance" data-tour="pk-home-hero">
      <div class="ph-sheen" aria-hidden="true"></div>
      <div class="ph-bal-top">
        <span class="ph-bal-label">{{ t('pocket.home.totalBalance', 'TOTAL BALANCE') }}</span>
        <span v-if="ccy" class="ph-ccy-chip">{{ ccy }}</span>
        <button class="ph-eye" :aria-label="hidden ? t('pocket.home.showAmounts', 'Show amounts') : t('pocket.home.hideAmounts', 'Hide amounts')" @click="toggle">
          <Icon :name="hidden ? 'mdi:eye-off' : 'mdi:eye'" />
        </button>
        <button class="ph-eye" :disabled="loading" :title="t('common.refresh', 'Refresh')" :aria-label="t('pocket.home.refreshBalance', 'Refresh balance')" @click="load">
          <Icon name="mdi:refresh" :class="{ 'ph-spin': loading }" />
        </button>
      </div>
      <div v-if="loading" class="ph-bal-skel"></div>
      <div v-else-if="heroErr && !summary" class="ph-bal-err" data-testid="ph-hero-err">
        <span>{{ t('pocket.home.balanceUnavailable', 'Balance unavailable') }}: {{ heroErr }}</span>
        <button class="ph-retry" @click="load">{{ t('cta.retry', 'Retry') }}</button>
      </div>
      <div v-else class="ph-bal-num" :class="{ long: balStr.length > 12 }">{{ mask(balStr) }}</div>
      <div v-if="heroErr && summary" class="ph-stale" data-testid="ph-hero-stale">{{ t('pocket.home.stale', 'refresh failed — showing the last loaded numbers') }}</div>
      <div class="ph-bal-sub" v-if="!loading">
        <span class="ph-chip"><Icon name="mdi:lock" /> {{ mask(amount(summary?.total_staked_balance)) }}{{ ' ' }}{{ t('pocket.home.staked', 'locked') }}</span>
        <span class="ph-chip"><Icon name="mdi:robot" /> {{ agentCountLabel }}</span>
      </div>
      <div class="ph-updated" v-if="updatedAt && !loading">{{ t('pocket.home.asOf', 'as of') }}{{ ' ' }}{{ updatedAt }}</div>
      <!-- §POCKETBRIDGE4 WS-T — today's flow for the acting agent (clipped windows say so) -->
      <div v-if="flow" class="ph-flow" data-testid="ph-today-flow" :title="flow.note">
        <Icon name="mdi:swap-horizontal" />
        <template v-if="flow.err">
          <span class="ph-flow-err">{{ t('pocket.home.flowUnavailable', "today's flow unavailable") }}: {{ flow.err }}</span>
        </template>
        <template v-else>
          <span>{{ t('pocket.home.today', 'today') }} <b class="up">+{{ mask(amount(flow.inn)) }}</b> {{ t('pocket.home.flowIn', 'in') }} · <b class="down">−{{ mask(amount(flow.out)) }}</b> {{ t('pocket.home.flowOut', 'out') }}</span>
          <small>{{ flow.note }}</small>
        </template>
      </div>
      <!-- #PK19 — one session-honest live line off the shared stream: what THIS
           session has witnessed, never a claim about minutes before it. -->
      <div v-if="liveTotal > 0 || liveConnected" class="ph-live" data-testid="ph-live">
        <span class="ph-live-dot" :class="{ on: liveConnected }" aria-hidden="true"></span>
        {{ t('pocket.home.live', 'LIVE') }} · {{ liveTotal.toLocaleString(appLocale()) }} {{ t('pocket.home.liveEvents', 'events this session') }} · {{ liveMine }}{{ liveApprox ? '+' : '' }} {{ t('pocket.home.liveYours', 'yours') }}
        <!-- §POCKETBRIDGE2 W8.1 — the pulse strip counts what THIS SESSION saw,
             per minute; minutes before you arrived are ABSENCE, never zero. -->
        <span class="ph-pulse" data-testid="ph-pulse" :title="pulseTitle" aria-hidden="true">
          <i v-for="(b, i) in pulseBars" :key="i" :style="{ height: b.h + 'px' }" :class="{ blank: !b.seen }"></i>
        </span>
      </div>
    </section>

    <div v-if="payRefused" class="ph-refused" data-testid="ph-pay-refused" role="alert">{{ payRefused }}</div>

    <!-- §POCKETBRIDGE2 W8.3 — plaintext agent secrets on the device get ONE
         quiet nudge toward the vault; dismissible, never nagging. -->
    <div v-if="sealNudge" class="ph-nudge" data-testid="ph-seal-nudge">
      <Icon name="mdi:lock" />
      <span>{{ nudgeLabel }}</span>
      <router-link to="/pocket/more" class="ph-nudge-go">{{ t('pocket.home.seal', 'Seal') }}</router-link>
      <button class="ph-nudge-x" :aria-label="t('pocket.common.dismiss', 'Dismiss')" @click="dismissNudge"><Icon name="mdi:close" /></button>
    </div>

    <!-- §PHONESTART (2026-09-02) — a wallet with no agent used to show a balance of 0 and three
         quick actions that all answer "select an agent first". The door comes first. -->
    <section v-if="firstRun" class="ph-first" data-testid="ph-first-run" data-tour="ph-first-run">
      <Icon name="mdi:robot" class="ph-first-ico" />
      <div class="ph-first-body">
        <strong>{{ t('pocket.home.firstTitle', 'No wallet agent yet') }}</strong>
        <span>{{ t('pocket.home.firstBody', 'Everything here — sending, voting, hiring — is done as one of your agents. Create the first one now; it takes a name and a minute.') }}</span>
      </div>
      <button type="button" class="ph-first-btn" data-testid="ph-first-create" @click="uiStore.openQuickAgentModal()">{{ t('pocket.home.firstCreate', 'Create your wallet agent') }}</button>
    </section>

    <!-- quick actions: Send / Receive / Advanced -->
    <section class="ph-actions" data-tour="pk-home-actions">
      <button class="ph-action" @click="openSheet('send')">
        <span class="ph-action-ico ph-ico-send"><Icon name="mdi:send" /></span><span>{{ t('pocket.home.send', 'Send') }}</span>
      </button>
      <button class="ph-action" @click="openSheet('receive')">
        <span class="ph-action-ico ph-ico-recv"><Icon name="mdi:arrow-down" /></span><span>{{ t('pocket.home.receive', 'Receive') }}</span>
      </button>
      <button v-if="stakingOn" class="ph-action" @click="stakeOpen = true">
        <span class="ph-action-ico ph-ico-stake"><Icon name="mdi:lock" /></span><span>{{ t('pocket.home.stake', 'Lock') }}</span>
      </button>
      <a class="ph-action" href="#/mission-control" @click="setAdvanced">
        <span class="ph-action-ico"><Icon name="mdi:rocket-launch" /></span><span>{{ t('pocket.home.advanced', 'Advanced') }}</span>
      </a>
    </section>

    <!-- §POCKETBRIDGE #PK6 (the named ask) — the lightbridge quick actions,
         thumb-shaped. The SAME component the bridge and the light bridge run:
         FUND (admin) / REQUEST + SEND + the VOTE·BID·POST-WORK doors, the
         ACTING AS → ON sentence, the hand→principal treatment and the outcome
         line. Pocket supplies the two seams it was built to accept: a touch
         target (tap an account below) and its own doors. sendMode='emit'
         keeps ONE send door — the PocketSend sheet (D3, ratified). -->
    <section class="ph-qa" data-tour="pk-home-qa">
      <BridgeQuickActions
        ref="qaRef"
        send-mode="emit"
        :target-did="targetDid"
        :target-name="targetName"
        :owned-dids="ownedDids"
        :currency="ccy"
        :target-hint="t('pocket.home.targetHint', 'nobody yet — tap an account below to target it')"
        :acting-hint="actingHint"
        @open-send="onQuickSend"
        @open-lane="onLane"
      />
    </section>

    <PocketSend :open="sheetOpen" :mode="sheetMode" :ccy="ccy"
                :initial-to="payPrefill.to" :initial-amount="payPrefill.amount" :initial-memo="payPrefill.memo"
                @close="sheetOpen = false; payPrefill = {}" @sent="load" />
    <PocketStake :open="stakeOpen" :ccy="ccy" :prefill="stakePrefill" @close="stakeOpen = false; stakePrefill = null; load()" />

    <!-- accounts: top agents by balance -->
    <section class="ph-recent" data-tour="pk-home-recent">
      <div class="ph-recent-head">
        <h2>{{ t('pocket.home.accounts', 'Accounts') }} <span class="ph-scope">{{ t('pocket.home.accountsScope', 'top funded · whole fleet, ranked by the registry') }}</span></h2>
        <router-link to="/pocket/agents" class="ph-see-all">{{ t('pocket.home.seeAll', 'See all') }} <Icon name="mdi:chevron-right" /></router-link>
      </div>
      <div v-if="accLoading" class="ph-list"><div v-for="n in 3" :key="n" class="ph-row-skel"></div></div>
      <ul v-else class="ph-list">
        <!-- #PK6 — tapping an account TARGETS it for the quick actions above
             (tap again to clear). The touch answer to the bridge's right-click. -->
        <li v-for="a in accounts" :key="a.did">
          <div class="ph-row ph-row-tap" :class="{ 'is-target': targetDid === a.did }"
            role="button" tabindex="0" :aria-pressed="targetDid === a.did"
            @click="toggleTarget(a)" @keydown.enter.prevent="toggleTarget(a)" @keydown.space.prevent="toggleTarget(a)">
          <span class="ph-row-ico"><Icon name="mdi:wallet" /></span>
          <div class="ph-row-body">
            <div class="ph-row-title">{{ a.name }}<span v-if="marks[a.did]" class="pkx-mark" :class="'pkx-mark-' + marks[a.did].tier" :title="tp('pocket.home.verifiedJobs', '{n} verified jobs', { n: marks[a.did].jobs })">{{ tierLabel(marks[a.did].tier) }}</span><span v-if="targetDid === a.did" class="ph-target-chip">{{ t('pocket.home.target', 'TARGET') }}</span></div>
            <div class="ph-row-sub">{{ a.didShort }}</div>
          </div>
          <div class="ph-row-amt">{{ mask(amount(a.balance)) }} <small>{{ a.ccy || ccy }}</small></div>
          </div>
        </li>
        <!-- F12 (§STAKEDFIX class): an ERROR is an error, never a plausible
             empty. The zero-state renders only when the read actually worked. -->
        <li v-if="accErr" class="ph-empty ph-err" data-testid="ph-acc-err">
          <Icon name="mdi:alert-octagon" class="ph-empty-ico" />
          <p>{{ t('pocket.home.accountsError', 'Couldn’t read your accounts') }} — {{ accErr }}</p>
          <button class="ph-retry" @click="load">{{ t('cta.retry', 'Retry') }}</button>
        </li>
        <li v-else-if="!accounts.length" class="ph-empty">
          <Icon name="mdi:wallet" class="ph-empty-ico" />
          <p>{{ t('pocket.home.noAccounts', 'No funded agents yet — create one above, or fund one, and it appears here.') }}</p>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { rememberUiMode } from '@/services/uiMode'
import PocketSend from './PocketSend.vue'
import PocketStake from './PocketStake.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import BridgeQuickActions from '@/components/bridge/BridgeQuickActions.vue'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { usePocketLock } from '@/composables/usePocketLock'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { marksForMany } from '@/services/pocketMarks'
import { EARNED_TIERS, type EarnedMarks } from '@/services/api/trackRecord'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { developerApi, type TegSummary } from '@/services/api/developers'
import { agentApi } from '@/services/api/agents'
import { tegApi } from '@/services/api/teg'
import { useAuthStore } from '@/stores/auth'
import { useCurrency } from '@/composables/useCurrency'
import { useActingContext } from '@/composables/useActingContext'
// §FOREIGNACT — where this agent's money actually lives (null-not-guessed for a
// foreign agent whose registry card has not answered yet).
const { actingCurrencyLabel } = useActingContext()
import { usePocketPrivacy } from '@/composables/usePocketPrivacy'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'

const { t, tp } = useI18n()

const { amount, localCurrency } = useCurrencySafe()
function useCurrencySafe() {
  try { const c = useCurrency(); return { amount: c.amount, localCurrency: (c as any).localCurrency } }
  catch { return { amount: (v: any) => String(v ?? '0'), localCurrency: computed(() => currentOwnCurrency()) } }
}
const ccy = ref('')
const summary = ref<TegSummary | null>(null)
// §PHONESTART (2026-09-02) — the quick-create modal (mounted by the shell) and the quick
// actions host, so `?fund=1` can open REQUEST the way My Agents does on the desktop.
const uiStore = useUIStore()
const qaRef = ref<{ open: (key: string) => void } | null>(null)
const loading = ref(true)
const accLoading = ref(true)
const updatedAt = ref('')
const accounts = ref<{ did: string; didShort: string; name: string; balance: string; ccy?: string }[]>([])

const heroErr = ref('')
const marks = ref<Record<string, EarnedMarks>>({})
// param is `tier`, NOT `t`: `t` is the translate function in this scope.
const tierLabel = (tier: string | null) => EARNED_TIERS.find(x => x.tier === tier)?.label || ''
const payRefused = ref('')
const balStr = computed(() => amount(summary.value?.total_balance))
/* Counted nouns are composed in JS, never through a params-carrying t():
   the count renders from the template, the noun picks its one/many key. */
const agentCountLabel = computed(() => {
  const n = summary.value?.agent_count ?? 0
  return `${n} ${n === 1 ? t('pocket.home.agentOne', 'agent') : t('pocket.home.agentMany', 'agents')}`
})
const { hidden, toggle, mask } = usePocketPrivacy()
/* §PHONESTART — a wallet that owns no agent. Only after our OWN read (a 0-agent claim is
 * never made from a missing summary), and never while the list still says otherwise. */
const firstRun = computed(() => !loading.value && !!summary.value && (summary.value.agent_count ?? 0) === 0 && ownedDids.value.length === 0)

// send/receive sheet
const sheetOpen = ref(false)
const sheetMode = ref<'send' | 'receive'>('send')
const stakeOpen = ref(false)
// §BAFIN (2026-10-01): no lock door where the registry switched locking off. §MEMBERSHIP (V0564): fail-closed, so the
// door does not show while the config is in flight (it was `!== false`).
const { config: pocketRegistryCfg } = useRegistryConfig()
const stakingOn = computed(() => pocketRegistryCfg.value.staking_enabled === true)
const stakePrefill = ref<{ amount?: string; agent?: string } | null>(null)
const payPrefill = ref<{ to?: string; amount?: string; memo?: string }>({})

/* ── §POCKETBRIDGE #PK6 — quick-action wiring ── */
const { restoreActing, sealedLocked, credAgents } = usePocketAgent()
// §POCKETBRIDGE2 P0.3 — say WHERE the acting authority comes from; "why can I
// act" should answer itself on the strip.
const actingHint = computed(() => {
  if (sealedLocked.value) return t('pocket.home.vaultLocked', 'credential vault locked')
  // V0641: the road the acting agent signed in by (the store's agentTokenVia); your session is not an imported credential
  const via = (authStore as any).agentTokenVia
  if (via === 'owner' || via === 'hub') return t('pocket.home.viaSession', 'through your session')
  if (via === 'secret') return t('pocket.home.viaCreds', 'via imported credentials')
  const n = credAgents.value.filter(a => !a.viaSession).length
  return n > 0 ? t('pocket.home.viaCreds', 'via imported credentials') : ''
})
/* ── §POCKETBRIDGE4 WS-T (carried W8.2) — today's flow for the ACTING agent.
 * Sums the agent's settled TEG transactions since local midnight from the
 * latest-50 window the API serves; when 50 rows don't reach midnight the chip
 * SAYS the window is clipped instead of implying a full day. */
const authStore = useAuthStore()
const flow = ref<{ inn: number; out: number; n: number; note: string; err?: string } | null>(null)
async function loadTodayFlow() {
  const me = (authStore as any).activeAgent?.did
  if (!me || !(authStore as any).agentToken) { flow.value = null; return }
  try {
    const LIMIT = 50
    const r = await tegApi.getTransactions({ limit: LIMIT })
    const rows = r.transactions || []
    const midnight = new Date(); midnight.setHours(0, 0, 0, 0)
    let inn = 0, out = 0, n = 0
    let oldestToday = true
    for (const tx of rows) {
      const ts = new Date(tx.timestamp)
      if (Number.isNaN(ts.getTime()) || ts < midnight) { oldestToday = false; continue }
      if (String(tx.status || '').toLowerCase() !== 'completed') continue
      const amt = Number(tx.amount)
      if (!Number.isFinite(amt)) continue
      if (tx.receiver_agent_id === me) { inn += amt; n++ }
      if (tx.sender_agent_id === me) { out += amt + (Number(tx.fee_amount) || 0); n++ }
    }
    const clipped = rows.length >= LIMIT && oldestToday
    flow.value = {
      inn, out, n,
      note: clipped ? tp('pocket.home.flowClipped', 'latest {n} transactions only — the day has more', { n: LIMIT })
                    : n ? t('pocket.home.flowSettled', 'settled transactions since midnight')
                        : t('pocket.home.flowNone', 'no settled transactions yet today'),
    }
  } catch (e: any) {
    flow.value = { inn: 0, out: 0, n: 0, note: '', err: e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed') }
  }
}

const stream = useLedgerStream()
const liveConnected = computed(() => stream.anyConnected.value)
const liveTotal = computed(() => stream.totalEvents.value)
const liveApprox = computed(() => stream.droppedForRender.value > 0)
const liveMine = ref(0)
/* §POCKETBRIDGE2 W8.1 — 12 one-minute session buckets. seen=false minutes are
   drawn as ABSENCE (blank), never as a zero we did not observe. */
const PULSE_MIN = 12
const pulse = ref<{ c: number; seen: boolean }[]>(Array.from({ length: PULSE_MIN }, () => ({ c: 0, seen: false })))
const pulseSeen = computed(() => pulse.value.filter(b => b.seen).length)
const pulseTitle = computed(() =>
  tp('pocket.home.pulseTitle', 'network events per minute, this session ({n} min watched)', { n: pulseSeen.value }))
const pulseBars = computed(() => {
  const max = Math.max(1, ...pulse.value.map(b => b.c))
  return pulse.value.map(b => ({ seen: b.seen, h: b.seen ? Math.max(2, Math.round((b.c / max) * 14)) : 14 }))
})
let pulseTimer: ReturnType<typeof setInterval> | null = null

/* §POCKETBRIDGE2 W8.3 — the seal nudge. */
const lockForNudge = usePocketLock()
const nudgeDismissed = ref(false)
try { nudgeDismissed.value = localStorage.getItem('pk_seal_nudge') === '1' } catch {}
const nudgeCount = ref(0)
const sealNudge = computed(() => !nudgeDismissed.value && nudgeCount.value > 0)
function refreshNudge() {
  try {
    // V0641: what is stored here unencrypted; an agent you act as through your session stores nothing
    nudgeCount.value = lockForNudge.vaultInfo().state === 'plain' ? credAgents.value.filter(a => !a.viaSession).length : 0
  } catch { nudgeCount.value = 0 }
}
function dismissNudge() { nudgeDismissed.value = true; try { localStorage.setItem('pk_seal_nudge', '1') } catch {} }
const nudgeLabel = computed(() => {
  const n = nudgeCount.value
  const noun = n === 1 ? t('pocket.home.credOne', 'agent credential') : t('pocket.home.credMany', 'agent credentials')
  return `${n} ${noun} ${t('pocket.home.nudgeTail', 'stored unencrypted on this device. One fingerprint seals them.')}`
})
let offVerbs: (() => void) | null = null
const targetDid = ref<string | null>(null)
const targetName = ref<string | null>(null)
const ownedDids = ref<string[]>([])
const accErr = ref('')
function toggleTarget(a: { did: string; name: string }) {
  if (targetDid.value === a.did) { targetDid.value = null; targetName.value = null }
  else { targetDid.value = a.did; targetName.value = a.name }
  try { (navigator as any).vibrate?.(6) } catch {}
}
/* #PK8 (D3) — SEND's one door is the PocketSend sheet, prefilled with the
   resolved payee (the principal when the hand treatment chose it). */
function onQuickSend(p: { to: string | null }) {
  payPrefill.value = p.to ? { to: p.to } : {}
  sheetMode.value = 'send'
  sheetOpen.value = true
}
/* Doors land on pocket-native surfaces: senate = the shell's sheet (via the
   query the shell watches — query-only navigation does not remount, §NOTIFLOG
   lesson), guild = the Earn tab. */
function onLane(lane: 'senate' | 'guild') {
  if (lane === 'senate') { router.replace({ query: { ...route.query, sheet: 'senate' } }).catch(() => {}) }
  else { router.push('/pocket/payments').catch(() => {}) }
}

// /pocket/pay?to=&amount=&memo= — the payment-request URI landing (NFC / QR / link)
function handlePayRoute() {
  if (route.name !== 'pocket-pay') return
  const q = route.query
  const to = String(q.to || '')
  if (to.startsWith('did:')) {
    payPrefill.value = { to, amount: q.amount ? String(q.amount) : undefined, memo: q.memo ? String(q.memo) : undefined }
    sheetMode.value = 'send'; sheetOpen.value = true
  } else {
    // §POCKETBRIDGE2 W3.2 — a scanned QR that carries no valid agent address
    // used to vanish without a word. Refusal names what arrived.
    heroErr.value = ''
    payRefused.value = to
      ? tp('pocket.home.payRefusedAddr', 'Payment link refused — "{to}" is not an agent address (did:…).', { to: to.slice(0, 40) })
      : t('pocket.home.payRefusedNone', 'Payment link refused — it names no recipient.')
    setTimeout(() => { payRefused.value = '' }, 8000)
  }
  router.replace('/pocket/home')  // clean the URL either way
}
function openSheet(m: 'send' | 'receive') { sheetMode.value = m; sheetOpen.value = true }

// pull-to-refresh — the ONE shared implementation (§POCKETBRIDGE2 W3.3)
const scrollEl = ref<HTMLElement | null>(null)
const { ptrH, ptrArmed, onTouchStart, onTouchMove, onTouchEnd } = usePullToRefresh(scrollEl, () => load())

function setAdvanced() { rememberUiMode('advanced') }
const shorten = (s: string) => !s ? '—' : s.length > 30 ? s.slice(0, 16) + '…' + s.slice(-6) : s

async function load() {
  loading.value = true
  heroErr.value = ''
  try {
    summary.value = await developerApi.getTegSummary()
    updatedAt.value = new Date().toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' })
  } catch (e: any) {
    // §POCKETBRIDGE2 W1 — with nothing loaded yet, "keep last" keeps NOTHING
    // and the hero renders a 0 that is not a fact. A refresh failure over a
    // real number keeps the number and says it is stale.
    heroErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  }
  finally { loading.value = false }
  // §FOREIGNACT — the ACTING agent's currency, not the page's. When you act as
  // an agent homed on another registry, every agent-tier call goes THERE, so the
  // unit next to a balance (and the one PocketSend/PocketStake inherit through
  // :ccy) must be that registry's. Empty while a foreign card is still loading:
  // an amount with no unit is honest, an amount with the wrong unit is not.
  try { ccy.value = actingCurrencyLabel.value } catch { ccy.value = '' }
  // ACCOUNTS — §POCKETBRIDGE F12 (Commander-found live: "doesnt load the
  // agents in home"). The old loader sampled the NEWEST 100 agents and kept
  // balance > 0 — on a 4,000-agent fleet the newest 100 are forge fixtures,
  // so the funded fleet rendered as "No funded agents yet" (§BRIDGE R1's
  // "mine never meant mine", wearing a wallet). Only the server can answer
  // "top by balance": sort=balance rides the indexed liquid_balance column,
  // ONE small request, whole-fleet truth. One bounded batch call (cap 50)
  // then refreshes the ranked rows with live TEG numbers, best-effort.
  accLoading.value = true
  accErr.value = ''
  try {
    const res: any = await agentApi.getMyAgents({ limit: 24, sort: 'balance' })
    const rows = (Array.isArray(res) ? res : res?.items || res?.data || [])
      .map((a: any) => ({
        did: a.did || a.agent_did,
        name: a.name || a.agent_card_name || '(unnamed)',
        liquid: Number(a.liquid_balance ?? 0),
      }))
      .filter((a: any) => a.did)
    ownedDids.value = rows.map((r: any) => r.did)
    const funded = rows.filter((r: any) => Number.isFinite(r.liquid) && r.liquid > 0).slice(0, 8)
    let bal: any = {}
    if (funded.length) {
      try {
        const raw: any = await developerApi.getAgentBalancesBatch(funded.map((f: any) => f.did))
        bal = raw?.balances || raw || {}
      } catch { /* the ranked snapshot stands; live refresh is best-effort */ }
    }
    accounts.value = funded.map((f: any) => {
      const b = bal?.[f.did] || {}
      const liquid = Number(b.liquid_balance ?? b.balance ?? f.liquid)
      return { did: f.did, didShort: shorten(f.did), name: f.name, balance: String(liquid), ccy: b.currency || '' }
    })
    // §POCKETBRIDGE2 W6 — earned marks on the rows just rendered (cached, capped).
    marksForMany(accounts.value.map((a: any) => a.did), (did, m) => { marks.value = { ...marks.value, [did]: m } })
  } catch (e: any) {
    // An unreadable list is an ERROR, not an empty account (§STAKEDFIX class).
    accErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.networkError', 'network error')
  } finally { accLoading.value = false }
}

const route = useRoute()
const router = useRouter()

// §POCKETBRIDGE2 hotfix — /pocket/pay and Home share this COMPONENT, so a
// same-component navigation onto the pay route never re-runs onMounted and
// handlePayRoute went dead (the §NOTIFLOG class, found by the battery when a
// step reordered the route walk). Watch the route, don't rely on mount.
watch(() => route.fullPath, () => { if (route.name === 'pocket-pay') handlePayRoute() })

// The lock door (NEEDS YOU / shell) arrives as ?sheet=stake. Query-only
// navigation does NOT remount this view, so this must be a watcher (§NOTIFLOG).
watch(() => route.query.sheet, (v) => {
  if (v === 'send') {
    // §POCKETBRIDGE4 WS-H — the app-shortcut door straight onto the ONE send sheet.
    openSheet('send')
    const q = { ...route.query } as Record<string, any>
    delete q.sheet
    router.replace({ query: q }).catch(() => {})
    return
  }
  if (v === 'stake' && stakingOn.value) {
    // §POCKETBRIDGE3 WS-B — the voice door may carry amount/agent to prefill.
    stakePrefill.value = (route.query.amount || route.query.agent)
      ? { amount: route.query.amount ? String(route.query.amount) : undefined,
          agent: route.query.agent ? String(route.query.agent) : undefined }
      : null
    stakeOpen.value = true
    const q = { ...route.query } as Record<string, any>
    delete q.sheet; delete q.amount; delete q.agent
    router.replace({ query: q }).catch(() => {})
  }
}, { immediate: true })

// §PHONESTART — the funding door (`/pocket/home?fund=1`, from the quick-create modal and
// the first-run card): open REQUEST on the quick actions, as My Agents does with `?fund=1`
// on the desktop. A query-only navigation does not remount this view: mount AND watch.
watch(() => route.query.fund, (v) => {
  if (v !== '1') return
  const q = { ...route.query } as Record<string, any>
  delete q.fund
  router.replace({ query: q }).catch(() => {})
  void restoreActing().then(async () => { await nextTick(); qaRef.value?.open('request') })
}, { immediate: true })
// §PHONESTART — the agent the quick modal just created is this screen's business: re-read
// the summary and make the newborn the acting agent (the dashboard's §ONBOARDQOL P1 rule).
watch(() => uiStore.agentCreatedTick, () => { void load(); void restoreActing().then(() => { void loadTodayFlow() }) })

onMounted(() => {
  load()
  handlePayRoute()
  // #PK6 — make SOME agent the acting one so ACTING AS is live on arrival;
  // failure just leaves the quick actions blocked, and they say why.
  void restoreActing().then(() => { void loadTodayFlow() })
  offVerbs = stream.onVerbs((batch) => {
    liveMine.value += batch.filter((v: any) => v.mine).length
    const cur = pulse.value[PULSE_MIN - 1]
    pulse.value = [...pulse.value.slice(0, -1), { c: cur.c + batch.length, seen: true }]
  })
  pulse.value = [...pulse.value.slice(0, -1), { c: 0, seen: true }]   // the minute we arrived is observed
  pulseTimer = setInterval(() => { pulse.value = [...pulse.value.slice(1), { c: 0, seen: true }] }, 60_000)
  refreshNudge()
  const el = scrollEl.value
  if (el) {
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchmove', onTouchMove, { passive: true })
    el.addEventListener('touchend', onTouchEnd)
  }
})
onBeforeUnmount(() => {
  if (pulseTimer) clearInterval(pulseTimer)
  offVerbs?.()
  const el = scrollEl.value
  if (el) { el.removeEventListener('touchstart', onTouchStart); el.removeEventListener('touchmove', onTouchMove); el.removeEventListener('touchend', onTouchEnd) }
})
</script>

<style scoped>
.ph-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: 1rem; box-sizing: border-box; }
.ph-ptr { display: flex; align-items: center; justify-content: center; overflow: hidden; transition: opacity 0.15s; margin-top: -0.4rem; }
.ph-ptr :deep(svg) { width: 1.3rem; height: 1.3rem; color: var(--nc-primary, #00d4ff); }
.ph-eye { margin-left: auto; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 9px;
  padding: 0.3rem; color: inherit; cursor: pointer; display: grid; place-items: center; min-width: 44px; min-height: 44px; -webkit-tap-highlight-color: transparent; }
.ph-eye :deep(svg) { width: 0.95rem; height: 0.95rem; opacity: 0.7; }
.ph-bal-err { display: flex; align-items: center; gap: 0.6rem; font-size: 0.85rem; color: #ff9a9a; min-height: 2.4rem; }
.ph-retry { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.2); border-radius: 9px;
  color: inherit; padding: 0.4rem 0.8rem; min-height: 44px; cursor: pointer; }
.ph-stale { font-size: 0.7rem; color: #f0b46a; opacity: 0.85; margin-top: 0.2rem; }
.ph-pulse { display: inline-flex; align-items: flex-end; gap: 2px; height: 14px; margin-left: 0.55rem; }
.ph-pulse i { width: 3px; border-radius: 1px; background: var(--nc-primary, #00d4ff); opacity: 0.75; display: inline-block; }
.ph-pulse i.blank { background: rgba(230,237,243,0.12); opacity: 1; }
.ph-nudge { display: flex; align-items: center; gap: 0.55rem; background: rgba(0,212,255,0.06);
  border: 1px solid rgba(0,212,255,0.25); border-radius: 12px; padding: 0.55rem 0.7rem; font-size: 0.78rem; }
.ph-nudge > svg { width: 1rem; height: 1rem; color: var(--nc-primary, #00d4ff); flex: 0 0 auto; }
.ph-nudge span { flex: 1 1 auto; }
.ph-nudge-go { color: var(--nc-primary, #00d4ff); font-weight: 700; text-decoration: none; padding: 0.5rem 0.6rem; min-height: 44px; display: inline-flex; align-items: center; }
.ph-nudge-x { background: none; border: none; color: inherit; opacity: 0.5; cursor: pointer; min-width: 44px; min-height: 44px; display: grid; place-items: center; }
.ph-nudge-x svg { width: 0.9rem; height: 0.9rem; }
.ph-refused { background: rgba(255,77,77,0.1); border: 1px solid rgba(255,77,77,0.35); border-radius: 12px;
  color: #ff9a9a; font-size: 0.8rem; padding: 0.6rem 0.8rem; }
.ph-ico-send { background: linear-gradient(160deg, rgba(0,212,255,0.16), rgba(0,212,255,0.04)) !important; }
.ph-ico-recv { background: linear-gradient(160deg, rgba(16,185,129,0.18), rgba(16,185,129,0.05)) !important; border-color: rgba(16,185,129,0.25) !important; }
.ph-ico-stake { background: linear-gradient(160deg, rgba(167,139,250,0.18), rgba(167,139,250,0.05)) !important; border-color: rgba(167,139,250,0.28) !important; }
.ph-ico-stake :deep(svg) { color: #a78bfa !important; }
.ph-ico-recv :deep(svg) { color: #34d399 !important; }
button.ph-action { font-family: inherit; }

/* ── hero ── */
.ph-balance { position: relative; overflow: hidden; border-radius: 22px; padding: 1.35rem 1.2rem 1.05rem;
  background: linear-gradient(165deg, rgba(0,212,255,0.12), rgba(0,212,255,0.02) 52%, rgba(99,102,241,0.05)), rgba(255,255,255,0.028);
  border: 1px solid rgba(0,212,255,0.2);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.08), 0 18px 44px -22px rgba(0,212,255,0.24); }
.ph-sheen { position: absolute; inset: -60% -30%; pointer-events: none !important; z-index: 0;
  background: linear-gradient(115deg, transparent 42%, rgba(255,255,255,0.045) 50%, transparent 58%);
  animation: ph-sheen 7s ease-in-out infinite; }
.ph-bal-top { display: flex; align-items: center; justify-content: flex-start; gap: 0.55rem; position: relative; z-index: 1; }
.ph-balance > *:not(.ph-sheen) { position: relative; z-index: 1; }
.ph-bal-label { font-size: 0.64rem; letter-spacing: 0.16em; opacity: 0.55; font-weight: 700; }
.ph-ccy-chip { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.08em; color: var(--nc-primary, #00d4ff);
  background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.3); border-radius: 6px; padding: 0.14rem 0.42rem; }
.ph-bal-num { font-variant-numeric: tabular-nums; font-size: clamp(1.7rem, 8.6vw, 2.5rem); font-weight: 750; letter-spacing: -0.015em; margin-top: 0.42rem;
  font-variant-numeric: tabular-nums; line-height: 1.08; white-space: nowrap; }
.ph-bal-num.long { font-size: clamp(1.35rem, 6.8vw, 2rem); }
.ph-bal-sub { display: flex; gap: 0.45rem; align-items: center; margin-top: 0.7rem; flex-wrap: wrap; }
.ph-chip { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.72rem; opacity: 0.85;
  background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.09); border-radius: 8px; padding: 0.26rem 0.55rem;
  font-variant-numeric: tabular-nums; }
.ph-chip :deep(svg) { width: 0.82rem; height: 0.82rem; opacity: 0.8; }
.ph-refresh { position: absolute; top: 0.85rem; right: 0.85rem; background: rgba(255,255,255,0.06);
  border: 1px solid rgba(255,255,255,0.13); border-radius: 11px; padding: 0.48rem; color: inherit; cursor: pointer;
  min-width: 40px; min-height: 40px; display: grid; place-items: center;
  transition: transform 0.12s ease, background 0.15s; -webkit-tap-highlight-color: transparent; }
.ph-refresh:active { transform: scale(0.92); background: rgba(255,255,255,0.11); }
.ph-refresh :deep(svg) { width: 1rem; height: 1rem; }
.ph-updated { margin-top: 0.5rem; font-size: 0.66rem; opacity: 0.38; font-variant-numeric: tabular-nums; }
/* §POCKETBRIDGE4 — today's-flow chip */
.ph-flow { display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.45rem; font-size: 0.7rem; opacity: 0.85; font-variant-numeric: tabular-nums; }
.ph-flow svg { width: 0.85rem; height: 0.85rem; opacity: 0.6; }
.ph-flow b { font-weight: 700; }
.ph-flow b.up { color: #34d399; }
.ph-flow b.down { color: #f87171; }
.ph-flow small { font-size: 0.58rem; opacity: 0.55; }
.ph-flow-err { font-size: 0.64rem; color: #fbbf24; }
.ph-live { margin-top: 0.45rem; font-size: 0.64rem; letter-spacing: 0.06em; opacity: 0.6; font-variant-numeric: tabular-nums; }
.ph-live-dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: rgba(255,255,255,0.25); margin-right: 0.3rem; }
.ph-live-dot.on { background: #34d399; box-shadow: 0 0 7px rgba(52,211,153,0.55); }
.ph-bal-skel { height: 2.6rem; width: 65%; margin-top: 0.45rem; border-radius: 10px;
  background: linear-gradient(90deg, rgba(255,255,255,0.06), rgba(255,255,255,0.13), rgba(255,255,255,0.06));
  background-size: 200% 100%; animation: ph-shim 1.3s ease-in-out infinite; }

/* ── quick actions ── */
.ph-actions { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; }
@media (max-width: 359px) { .ph-actions { grid-template-columns: repeat(2, 1fr); } }
.ph-action { display: flex; flex-direction: column; align-items: center; gap: 0.42rem; text-decoration: none; color: inherit;
  background: rgba(255,255,255,0.035); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 0.8rem 0.4rem 0.7rem;
  font-size: 0.73rem; font-weight: 600; letter-spacing: 0.01em;
  transition: transform 0.12s ease, background 0.15s, border-color 0.15s; -webkit-tap-highlight-color: transparent; }
.ph-action:active { transform: scale(0.95); background: rgba(0,212,255,0.07); border-color: rgba(0,212,255,0.25); }
.ph-action-ico { width: 2.35rem; height: 2.35rem; border-radius: 13px; display: grid; place-items: center;
  background: linear-gradient(160deg, rgba(0,212,255,0.14), rgba(0,212,255,0.04)); border: 1px solid rgba(0,212,255,0.22); }
.ph-action-ico :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }

/* ── §POCKETBRIDGE #PK9 — the quick-actions strip, touch-sized. The component
     ships the bridge's 20px pointer floor; on glass every control gets the
     44px minimum via these scoped overrides, not a fork. ── */
.ph-qa { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; padding: 0.8rem 0.9rem 0.7rem; }
.ph-qa :deep(.brg-qa-row) { gap: 0.45rem; }
.ph-qa :deep(.brg-qa-btn) { flex: 1 1 auto; max-width: none; min-width: 4rem; min-height: 44px;
  font-size: 0.72rem; padding: 0.55rem 0.7rem; border-radius: 11px; letter-spacing: 0.08em; }
.ph-qa :deep(.brg-qa-roles) { font-size: 0.7rem; margin-top: 0.55rem; line-height: 1.6; }
.ph-qa :deep(.brg-qa-out) { font-size: 0.76rem; margin-top: 0.35rem; }
.ph-qa :deep(.brg-qa-hand) { font-size: 0.72rem; }
.ph-qa :deep(.brg-qa-hand-btn) { font-size: 0.74rem; padding: 0.55rem 0.4rem; display: inline-flex; align-items: center; min-height: 44px; }

.ph-row-tap { cursor: pointer; -webkit-tap-highlight-color: transparent; }
.ph-row.is-target { border-color: rgba(0,212,255,0.45); background: rgba(0,212,255,0.06); }
.ph-target-chip { font-size: 0.55rem; font-weight: 800; letter-spacing: 0.09em; color: var(--nc-primary, #00d4ff);
  border: 1px solid rgba(0,212,255,0.4); border-radius: 6px; padding: 0.08rem 0.32rem; margin-left: 0.45rem; vertical-align: 1px; }
/* §FESUITE — 0.45 measured 3.9:1 on the phone (axe); 0.6 is about 6:1 */
.ph-scope { font-size: 0.62rem; font-weight: 500; opacity: 0.6; margin-left: 0.5rem; letter-spacing: 0.02em; }
.ph-err p { color: #ffb4b4; }
.ph-retry { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); border-radius: 11px;
  color: #e6edf3; font-size: 0.8rem; font-weight: 600; padding: 0.55rem 1.1rem; min-height: 44px; cursor: pointer;
  -webkit-tap-highlight-color: transparent; }

/* ── accounts ── */
.ph-recent-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem; }
.ph-recent-head h2 { font-size: 0.95rem; margin: 0; letter-spacing: 0.01em; }
.ph-see-all { display: inline-flex; align-items: center; gap: 0.1rem; font-size: 0.78rem; color: var(--nc-primary, #00d4ff); text-decoration: none; min-height: 44px; }
.ph-see-all :deep(svg) { width: 0.9rem; height: 0.9rem; }
.ph-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.ph-row { display: flex; align-items: center; gap: 0.65rem; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 14px; padding: 0.68rem 0.8rem; min-height: 52px;
  transition: background 0.15s; }
.ph-row:active { background: rgba(255,255,255,0.06); }
.ph-row-ico { width: 2.1rem; height: 2.1rem; border-radius: 11px; display: grid; place-items: center; flex: 0 0 auto;
  background: rgba(0,212,255,0.09); border: 1px solid rgba(0,212,255,0.18); color: var(--nc-primary, #00d4ff); }
.ph-row-ico :deep(svg) { width: 1.02rem; height: 1.02rem; }
.ph-row-body { flex: 1 1 auto; min-width: 0; }
.ph-row-title { font-size: 0.86rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ph-row-sub { font-size: 0.66rem; opacity: 0.45; font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ph-row-amt { font-variant-numeric: tabular-nums; font-variant-numeric: tabular-nums; font-weight: 650; font-size: 0.88rem; flex: 0 0 auto; }
.ph-row-amt small { font-size: 0.62rem; opacity: 0.5; font-weight: 600; }
.ph-empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; text-align: center; opacity: 0.55; font-size: 0.82rem; padding: 1.4rem 1rem; }
.ph-empty-ico { width: 1.8rem; height: 1.8rem; }
.ph-empty p { margin: 0; max-width: 22rem; }
.ph-row-skel { height: 3.3rem; border-radius: 14px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: ph-shim 1.3s ease-in-out infinite; }
.ph-spin { animation: ph-rot 0.9s linear infinite; }
@keyframes ph-rot { to { transform: rotate(360deg); } }
@keyframes ph-shim { to { background-position: -200% 0; } }
@keyframes ph-sheen { 0%, 55% { transform: translateX(-30%); } 100% { transform: translateX(30%); } }
@media (prefers-reduced-motion: reduce) { .ph-row-skel, .ph-bal-skel, .ph-spin, .ph-sheen { animation: none; } }
.ph-first { display: grid; grid-template-columns: auto 1fr; gap: 0.6rem 0.8rem; align-items: center; margin: 0.9rem 0 0.2rem; padding: 0.9rem 1rem;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.35); border-radius: 12px; background: rgba(var(--nc-primary-rgb, 0,229,255), 0.07); }
.ph-first-ico { width: 1.6rem; height: 1.6rem; color: var(--nc-primary, #00e5ff); }
.ph-first-body { display: flex; flex-direction: column; gap: 0.2rem; font-size: 0.82rem; line-height: 1.35; }
.ph-first-btn { grid-column: 1 / -1; font-size: 0.9rem; font-weight: 700; padding: 0.7rem 1rem; border-radius: 10px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.6); background: rgba(var(--nc-primary-rgb, 0,229,255), 0.16); color: var(--nc-primary, #00e5ff); }
</style>
