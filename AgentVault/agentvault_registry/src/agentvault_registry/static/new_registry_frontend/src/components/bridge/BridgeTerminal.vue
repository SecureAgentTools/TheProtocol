<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { readAccessToken } from '@/services/accessToken'
/**
 * components/bridge/BridgeTerminal.vue — §BRIDGE R3, THE IN-VIEW TERMINAL.
 *
 * The Commander, 2026-08-19:
 *   "under networks the buttons to map discovery and staking and exchange
 *    should be an inview terminal that opens where you can basically do most
 *    important actions from. not forward you to another page. this is mission
 *    control. from here you should be able to see all the things your agents
 *    do."
 *
 * That amends strategy §4 ("every instrument is a door"). What it does NOT
 * amend, and what this file obeys:
 *
 *  - RULE 14 / strategy §9 — NO NEW MONEY RAILS. Every action here calls a rail
 *    that already exists and is already used by the full views: the locking
 *    store's stake/unstake/claim, and exchangeService.cancelOrder. Nothing is
 *    minted, moved or invented, and there is no second copy of a money path.
 *  - §FANOUTFIX — no second copy of a VIEW either. This is a compact console
 *    over the existing services, not a re-implementation of /staking or
 *    /exchange. Each lane keeps its door to the full view for everything this
 *    deliberately does not carry.
 *  - The honesty rules. Empty is empty and says so; a failure says what failed;
 *    nothing here invents a number.
 *
 * MAP is deliberately NOT a lane: the map is already the thing you are looking
 * at. Its button clears the rails so you can see it (handled by the host).
 */
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { useLogger } from '@/composables/useLogger'
import { useAuthStore } from '@/stores/auth'
import { useSenateLane } from '@/composables/useSenateLane'
import { guildApi } from '@/services/api/guild'
import { useStakingStore } from '@/stores/staking'
import { exchangeService, type MyOrder, type Portfolio } from '@/services/api/exchangeService'
import { discoveryService } from '@/services/api/discovery'
import { chatApi } from '@/services/api/chat'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import AgentDetailModal from '@/components/AgentDetailModal.vue'
import AssistantDock from '@/components/bridge/AssistantDock.vue'
import StepUpConfirm from '@/components/membership/StepUpConfirm.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useMemberVoteFlow, type SettledOutcome } from '@/composables/useMemberVoteFlow'
import { governanceMode } from '@/services/membership/membership'

export type TerminalLane = 'discovery' | 'staking' | 'exchange' | 'senate' | 'guild' | 'assistant' | 'ourstate'

const props = defineProps<{ lane: TerminalLane | null; currency?: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const { t } = useI18n()
const { money } = usePrivacy()
const router = useRouter()
const log = useLogger('BridgeTerminal')
const authStore = useAuthStore()
const stakingStore = useStakingStore()

/** Money actions need an agent JWT. Without one we say so; we never fake a form. */
const hasAgent = computed(() => !!authStore.agentToken)
const agentLabel = computed(() => authStore.activeAgent?.name || authStore.activeAgent?.did || '')

const busy = ref(false)
const errorText = ref<string | null>(null)
const noticeText = ref<string | null>(null)

function fail(e: any, what: string): void {
  log.debug(what, e)
  errorText.value = e?.response?.data?.detail || e?.message || t('bridge.term.failed', 'That did not go through')
}
function clearMsg(): void { errorText.value = null; noticeText.value = null }

// ─── DISCOVERY ───────────────────────────────────────────────────────────────
const q = ref('')
/*
 * Opening an agent uses the SAME modal the rest of the app uses.
 *
 * The first cut linked to `/agent/{did}`, and that route does not exist — a
 * door onto a wall, which strategy §4 says is worse than no door. There is no
 * by-DID route anywhere in this app: Discovery's `didQuery` is a local input,
 * not a deep link, and every surface that opens an agent mounts
 * AgentDetailModal. So this one does too. Reuse, not a new surface (§FANOUTFIX).
 */
const openDid = ref('')
const showAgent = ref(false)
function openAgent(did: string): void {
  if (!did) return
  openDid.value = did
  showAgent.value = true
}
const searching = ref(false)
const results = ref<any[]>([])
const searched = ref(false)

// §FESUITE (V0577): the search got no answer. It said "Nothing matched. The network is searched whole, so this is a real
// zero." under its own error: the one zero this lane promises is real is the one it had not measured.
const searchFailed = ref(false)

async function runSearch(): Promise<void> {
  clearMsg()
  searching.value = true
  searched.value = true
  searchFailed.value = false
  try {
    const r = await discoveryService.searchAgents(q.value.trim() || undefined)
    results.value = (r?.results || []).slice(0, 25)
  } catch (e) {
    results.value = []
    searchFailed.value = true
    fail(e, 'search')
  } finally {
    searching.value = false
  }
}

// ─── LOCKS ─────────────────────────────────────────────────────────────────
const stakeAmount = ref('')
const stakeLock = ref(30)

async function loadStaking(): Promise<void> {
  clearMsg()
  busy.value = true
  try {
    await Promise.allSettled([
      stakingStore.fetchMyStakingStats(),
      stakingStore.fetchPendingRewards(),
    ])
  } finally { busy.value = false }
}
const positions = computed<any[]>(() => (stakingStore.positions || []) as any[])
const pendingRewards = computed<string>(() => String(stakingStore.pendingRewards ?? '0'))

async function doStake(): Promise<void> {
  clearMsg()
  const amt = stakeAmount.value.trim()
  if (!amt || Number(amt) <= 0) { errorText.value = t('bridge.term.amountNeeded', 'Enter an amount'); return }
  busy.value = true
  try {
    await stakingStore.stake({ amount: amt, lockPeriod: stakeLock.value })
    noticeText.value = `${t('bridge.term.staked', 'Locked')} ${amt}`
    stakeAmount.value = ''
    await loadStaking()
  } catch (e) { fail(e, 'stake') } finally { busy.value = false }
}

async function doUnstake(p: any): Promise<void> {
  clearMsg()
  busy.value = true
  try {
    await stakingStore.unstake(String(p.id ?? p.position_id))
    noticeText.value = t('bridge.term.unstaked', 'Unlock requested')
    await loadStaking()
  } catch (e) { fail(e, 'unstake') } finally { busy.value = false }
}

async function doClaim(): Promise<void> {
  clearMsg()
  busy.value = true
  try {
    await stakingStore.claimPendingRewards()
    noticeText.value = t('bridge.term.claimed', 'Payouts claimed')
    await loadStaking()
  } catch (e) { fail(e, 'claim') } finally { busy.value = false }
}

// ─── EXCHANGE ────────────────────────────────────────────────────────────────
const orders = ref<MyOrder[]>([])
const portfolio = ref<Portfolio | null>(null)

async function loadExchange(): Promise<void> {
  clearMsg()
  busy.value = true
  try {
    const [o, p] = await Promise.allSettled([exchangeService.myOrders(), exchangeService.portfolio()])
    orders.value = o.status === 'fulfilled' ? (o.value?.orders || []) : []
    portfolio.value = p.status === 'fulfilled' ? p.value : null
    if (o.status === 'rejected' && p.status === 'rejected') fail(o.reason, 'exchange')
  } finally { busy.value = false }
}

async function doCancel(o: MyOrder): Promise<void> {
  clearMsg()
  busy.value = true
  try {
    await exchangeService.cancelOrder(String((o as any).order_id ?? (o as any).id))
    noticeText.value = t('bridge.term.cancelled', 'Order cancelled')
    await loadExchange()
  } catch (e) { fail(e, 'cancel') } finally { busy.value = false }
}

/* ─── SENATE (§BRIDGE R15.2 → §POCKETBRIDGE #PK16) ────────────────────────────
 * Governance is AGENT-ONLY on this network: create, vote and tally all take an
 * agent JWT (PART 5 flow 7), so the lane is scoped to the agent you are acting
 * as by construction rather than by a filter. Reading proposals is public, so
 * the list still renders without an agent — it simply cannot say whether YOU
 * voted, and says so instead of implying you have not.
 *
 * The logic itself lives in `useSenateLane` now — the Pocket senate sheet is
 * its second consumer, and two copies of one lane is the §FANOUTFIX defect.
 * This wrapper only maps outcomes onto the terminal's own message system.
 */
const senate = useSenateLane()
const myVoted = senate.myVoted
const openProposals = senate.openProposals
const senateLoaded = senate.loaded

async function loadSenate(): Promise<void> {
  busy.value = true
  try {
    const r = await senate.load(hasAgent.value)
    if (!r.ok) fail(r.error, 'senate')
  } finally { busy.value = false }
}

// §MEMBERSHIP (2026-10-02): where the registry runs member mode the vote is the member's, and a binding vote may
// need a step-up; the terminal maps the outcomes onto its own notice line.
const { config: termRegistryCfg } = useRegistryConfig()
const memberMode = computed(() => governanceMode(termRegistryCfg.value) === 'member')
const memberFlow = useMemberVoteFlow((out: SettledOutcome) => {
  if (out.kind === 'cast') noticeText.value = t('bridge.term.voted', 'Vote recorded')
  else if (out.kind === 'already_voted') noticeText.value = t('membership.vote.alreadyVotedMsg', 'One vote per member: you voted on this proposal through another agent.')
  else if (out.kind === 'needs_permission') noticeText.value = t('membership.vote.needsPermissionTerminal', 'This agent is not allowed to vote yet. Allow it on the Senate floor, under your membership.')
  else if (out.kind === 'not_member') noticeText.value = t('membership.vote.notMember', 'Only members vote here')
  else if (out.kind === 'second_factor_required') noticeText.value = t('membership.vote.secondFactorMsg', 'This registry needs every binding vote confirmed. Enrol your phone in Pocket or turn on two-factor sign-in in Settings, then vote again.')
})

async function doVote(p: any, choice: 'for' | 'against'): Promise<void> {
  if (!hasAgent.value || busy.value) return
  if (memberMode.value) {
    clearMsg()
    try { await memberFlow.start((extra) => senate.voteMember(p, choice, extra)) } catch (e) { fail(e, 'vote') }
    return
  }
  clearMsg(); busy.value = true
  try {
    const r = await senate.vote(p, choice)
    if (r.ok) noticeText.value = t('bridge.term.voted', 'Vote recorded')
    else fail(r.error, 'vote')
  } finally { busy.value = false }
}

/* ─── GUILD BOARD (§BRIDGE R15.3) ─────────────────────────────────────────────
 * WORK (R12) shows the engagements you ALREADY have. This is the other half:
 * open work anyone can bid on. Both actions use the guild's own endpoints —
 * no second money path — and both require typed input, so nothing here can be
 * committed by a single mis-click. The bounty is shown ON the button.
 */
const board = ref<any[]>([])
const bidFor = ref<string | null>(null)
const bidPrice = ref('')
const postTitle = ref('')
const postBounty = ref('')

// §FESUITE (V0577): the open board could not be read; it said "No open work on this registry right now."
const boardFailed = ref(false)

async function loadGuild(): Promise<void> {
  busy.value = true
  try {
    const r: any = await guildApi.board('open', 20)
    board.value = Array.isArray(r?.orders) ? r.orders : (Array.isArray(r) ? r : [])
    boardFailed.value = false
  } catch (e) { board.value = []; boardFailed.value = true; fail(e, 'guild board') } finally { busy.value = false }
}

async function doBid(o: any): Promise<void> {
  const price = parseFloat(bidPrice.value)
  if (!hasAgent.value || !Number.isFinite(price) || price <= 0) return
  clearMsg(); busy.value = true
  try {
    await guildApi.bid(String(o.id), { price })
    noticeText.value = t('bridge.term.bidPlaced', 'Bid placed')
    bidFor.value = null; bidPrice.value = ''
    await loadGuild()
  } catch (e) { fail(e, 'bid') } finally { busy.value = false }
}

async function doPostWork(): Promise<void> {
  const bounty = parseFloat(postBounty.value)
  if (!hasAgent.value || !postTitle.value.trim() || !Number.isFinite(bounty) || bounty <= 0) return
  clearMsg(); busy.value = true
  try {
    await guildApi.post({ title: postTitle.value.trim(), bounty, currency: props.currency })
    noticeText.value = t('bridge.term.posted', 'Work posted')
    postTitle.value = ''; postBounty.value = ''
    await loadGuild()
  } catch (e) { fail(e, 'post work') } finally { busy.value = false }
}

// ─── OURSTATE (§OURSTATE-2) ──────────────────────────────────────────────────
// The desktop dock is the SAME OurState: the same endpoints, the same rules,
// the same identity mandate. It lists and it opens — the composer and every
// money door live in the thread itself (one door per act, R3's rule), so a
// docked panel can never become a second, faster way to spend.
const osThreads = ref<any[]>([])
const osLoading = ref(false)
async function loadOurState(): Promise<void> {
  osLoading.value = true
  clearMsg()
  try {
    const jwt = (authStore as any).token || readAccessToken() || ''
    const r = await chatApi.listConversations(jwt, 'active', undefined, 12)
    osThreads.value = r?.conversations || []
  } catch (e) { fail(e, 'threads') } finally { osLoading.value = false }
}
function openThread(id: string): void {
  router.push(`/pocket/ourchat/${id}`).catch(() => { /* the guard owns it */ })
}

// ─── lane lifecycle: load on open, never on boot ─────────────────────────────
watch(() => props.lane, (lane) => {
  clearMsg()
  if (lane === 'staking' && hasAgent.value) void loadStaking()
  else if (lane === 'exchange' && hasAgent.value) void loadExchange()
  else if (lane === 'senate') void loadSenate()          // public read: no agent needed
  else if (lane === 'guild') void loadGuild()
  else if (lane === 'ourstate') void loadOurState()
}, { immediate: true })

const title = computed(() => {
  switch (props.lane) {
    case 'discovery': return t('bridge.doors.discovery', 'DISCOVERY')
    case 'staking': return t('bridge.doors.staking', 'LOCKS')
    case 'exchange': return t('bridge.doors.exchange', 'AGORA')
    case 'senate': return t('bridge.doors.senate', 'SENATE')
    case 'guild': return t('bridge.doors.guild', 'GUILD BOARD')
    case 'assistant': return t('bridge.doors.assistant', 'ASSISTANT')
    case 'ourstate': return t('bridge.doors.ourstate', 'OURSTATE')
    default: return ''
  }
})
/** The full view, kept one click away. A console is not a replacement. */
/** Numbers a person reads. The API returns full decimal precision
 *  (`41.260000000000000000`); that is the ledger's business, not the panel's. */
function num(v: unknown, dp = 4): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '-')
  return n.toLocaleString(appLocale(), { maximumFractionDigits: dp })
}

/**
 * QUICK BUY — opens the exchange with a buy ticket prefilled for this symbol.
 *
 * It deliberately does NOT place an order. Placing one is a money path, and a
 * money path gets ONE door (rule 14); a second, faster door on a panel this
 * small is how a mis-click becomes a trade. The exchange view already reads
 * `?symbol=`/`?side=` for exactly this.
 */
function quickBuy(symbol: string): void {
  if (!symbol) return
  router.push({ name: 'exchange', query: { symbol, side: 'buy' } })
    .catch(() => { /* the route guard owns the outcome */ })
}

const fullView = computed(() => {
  switch (props.lane) {
    case 'discovery': return '/discovery'
    case 'staking': return '/locks'
    case 'exchange': return '/agora'
    case 'senate': return '/senate'
    case 'guild': return '/guild'
    case 'assistant': return '/pocket/assistant'
    // §DESKCHROME: the bridge is a DESKTOP surface — its chat door opens the
    // desktop OurChat shell, not the phone chrome. (assistant stays /pocket/*:
    // it has no desktop mount yet — noted in the session log, not silently forked.)
    case 'ourstate': return '/ourchat'
    default: return '/'
  }
})
</script>

<template>
  <section v-if="lane" class="bterm" data-testid="bridge-terminal" role="dialog" :aria-label="title">
    <header class="bterm-hdr">
      <span class="bterm-title">{{ title }}</span>
      <span v-if="hasAgent && lane !== 'discovery'" class="bterm-as" :title="agentLabel">
        {{ t('bridge.term.actingAs', 'as') }} {{ agentLabel }}
      </span>
      <router-link class="bterm-full" :to="fullView"
                   :title="t('bridge.term.fullHelp', 'Open the full view in its own page')">
        {{ t('bridge.term.full', 'FULL VIEW') }}
      </router-link>
      <button type="button" class="bterm-x" :aria-label="t('common.close', 'Close')" @click="emit('close')">
        <Icon name="mdi:close" :size="12" />
      </button>
    </header>

    <p v-if="errorText" class="bterm-msg is-err">{{ errorText }}</p>
    <p v-else-if="noticeText" class="bterm-msg is-ok">{{ noticeText }}</p>

    <!-- DISCOVERY — find an agent anywhere in the federation, without leaving. -->
    <div v-if="lane === 'discovery'" class="bterm-body">
      <form class="bterm-row" @submit.prevent="runSearch">
        <input v-model="q" class="bterm-in" type="search"
               :placeholder="t('bridge.term.searchPh', 'name, DID or capability')" />
        <button type="submit" class="bterm-btn" :disabled="searching">
          {{ searching ? t('common.loading', 'Working') : t('bridge.term.search', 'SEARCH') }}
        </button>
      </form>
      <p v-if="searching" class="bterm-note">{{ t('bridge.term.searching', 'Searching the federation...') }}</p>
      <ReadFailedNotice v-else-if="searchFailed" dense :retry="runSearch" data-testid="term-search-failed"
        :text="t('bridge.term.searchFailed', 'The federation could not be searched just now. This is not a zero.')" />
      <p v-else-if="searched && results.length === 0" class="bterm-note">
        {{ t('bridge.term.noResults', 'Nothing matched. The network is searched whole, so this is a real zero.') }}
      </p>
      <ul v-else-if="results.length" class="bterm-list">
        <li v-for="(a, i) in results" :key="a.did || a.id || i" class="bterm-item">
          <span class="bterm-item-name">{{ a.name || a.did }}</span>
          <span class="bterm-item-sub">{{ a.origin_registry_name || a.origin_registry || a.registry || '' }}</span>
          <button type="button" class="bterm-item-act" data-testid="bterm-open-agent"
                  :title="t('bridge.term.openCard', 'Open this agent card')"
                  @click="openAgent(String(a.did || a.id || ''))">
            {{ t('bridge.term.open', 'OPEN') }}
          </button>
        </li>
      </ul>
    </div>

    <!-- LOCKS — your positions and the two actions that matter. -->
    <div v-else-if="lane === 'staking'" class="bterm-body">
      <p v-if="!hasAgent" class="bterm-note">
        {{ t('bridge.term.needAgent', 'Select an agent first: a lock acts as an agent, not as you.') }}
      </p>
      <template v-else>
        <div class="bterm-row bterm-row--stat">
          <span class="bterm-k">{{ t('bridge.term.pending', 'PENDING') }}</span>
          <span class="bterm-v">{{ money(pendingRewards) }} {{ currency }}</span>
          <button type="button" class="bterm-btn" :disabled="busy" @click="doClaim">
            {{ t('bridge.term.claim', 'CLAIM') }}
          </button>
        </div>
        <form class="bterm-row" @submit.prevent="doStake">
          <input v-model="stakeAmount" class="bterm-in" type="text" inputmode="decimal"
                 :placeholder="t('bridge.term.amount', 'amount')" />
          <select :aria-label="t('bridge.term.lockAria', 'Lock period')" v-model.number="stakeLock" class="bterm-in bterm-in--sm">
            <option :value="7">7d</option><option :value="30">30d</option>
            <option :value="90">90d</option><option :value="180">180d</option>
          </select>
          <button type="submit" class="bterm-btn" :disabled="busy">{{ t('bridge.term.stake', 'LOCK') }}</button>
        </form>
        <p v-if="busy" class="bterm-note">{{ t('common.loading', 'Working') }}</p>
        <p v-else-if="positions.length === 0" class="bterm-note">
          {{ t('bridge.term.noPositions', 'No open positions.') }}
        </p>
        <ul v-else class="bterm-list">
          <li v-for="(p, i) in positions" :key="p.id || p.position_id || i" class="bterm-item">
            <span class="bterm-item-name">{{ money(p.amount) }} {{ currency }}</span>
            <span class="bterm-item-sub">{{ p.lock_period_days || p.lockPeriod || '' }}d</span>
            <button type="button" class="bterm-item-act" :disabled="busy" @click="doUnstake(p)">
              {{ t('bridge.term.unstake', 'UNLOCK') }}
            </button>
          </li>
        </ul>
      </template>
    </div>

    <!-- EXCHANGE — what you hold and what is still working. -->
    <div v-else-if="lane === 'exchange'" class="bterm-body">
      <p v-if="!hasAgent" class="bterm-note">
        {{ t('bridge.term.needAgentEx', 'Select an agent first: orders belong to an agent, not to you.') }}
      </p>
      <template v-else>
        <p v-if="busy" class="bterm-note">{{ t('common.loading', 'Working') }}</p>
        <template v-else>
          <div class="bterm-sub">{{ t('bridge.term.openOrders', 'OPEN ORDERS') }}</div>
          <p v-if="orders.length === 0" class="bterm-note">{{ t('bridge.term.noOrders', 'No working orders.') }}</p>
          <ul v-else class="bterm-list">
            <!-- R13 #6: "a little distorted the modal needs polish alignment ...
                 could use different coloring maybe and a quick buy option."
                 Side reads as a colour, the numbers are columns instead of raw
                 floats (`41.260000000000000000` is the API's precision, not a
                 price a person reads), and the row is a fixed grid so nothing
                 shifts as values change length. -->
            <li v-for="(o, i) in orders" :key="(o as any).order_id || i"
                class="bterm-item bterm-order" :class="`is-${String((o as any).side || '').toLowerCase()}`">
              <span class="bterm-side">{{ (o as any).side }}</span>
              <span class="bterm-sym">{{ (o as any).symbol }}</span>
              <span class="bterm-qty">{{ money(num((o as any).remaining ?? (o as any).qty, 4)) }}</span>
              <span class="bterm-at">@</span>
              <span class="bterm-px">{{ money(num((o as any).price, 4)) }}</span>
              <button type="button" class="bterm-item-act" :disabled="busy" @click="doCancel(o)">
                {{ t('bridge.term.cancel', 'CANCEL') }}
              </button>
            </li>
          </ul>
          <div class="bterm-sub">{{ t('bridge.term.holdings', 'HOLDINGS') }}</div>
          <p v-if="!portfolio || (portfolio.positions || []).length === 0" class="bterm-note">
            {{ t('bridge.term.noHoldings', 'No holdings.') }}
          </p>
          <ul v-else class="bterm-list">
            <li v-for="(p, i) in portfolio.positions" :key="(p as any).symbol || i" class="bterm-item bterm-hold">
              <span class="bterm-sym">{{ (p as any).symbol }}</span>
              <span class="bterm-qty">{{ money(num((p as any).qty, 4)) }}</span>
              <!-- QUICK BUY, his ask. It prefills the EXISTING order form on the
                   exchange view for this symbol — no order is placed from here
                   and no new rail exists: placing an order is a money path and
                   money paths keep one door (rule 14). -->
              <button type="button" class="bterm-item-act" data-testid="term-quickbuy"
                      :title="t('bridge.term.quickBuyHelp', 'Open the market with a buy ticket prefilled for this holding')"
                      @click="quickBuy((p as any).symbol)">
                {{ t('bridge.term.buy', 'BUY') }}
              </button>
            </li>
          </ul>
        </template>
      </template>
    </div>

    <!-- SENATE — governance is agent-only, so the vote is cast AS the agent. -->
    <div v-else-if="lane === 'senate'" class="bterm-body">
      <p v-if="busy && !senateLoaded" class="bterm-note">{{ t('common.loading', 'Working') }}</p>
      <template v-else>
        <!-- Reading is public; knowing whether YOU voted is not. Say which. -->
        <p v-if="!hasAgent" class="bterm-note">
          {{ t('bridge.term.senateNoAgent', 'Proposals are public, so they are listed. Voting acts as an agent, and whether you have already voted cannot be known until you pick one.') }}
        </p>
        <p v-if="openProposals.length === 0" class="bterm-note">
          {{ t('bridge.term.noProposals', 'No proposal is open for voting right now.') }}
        </p>
        <ul v-else class="bterm-list">
          <li v-for="p in openProposals" :key="p.id" class="bterm-item bterm-item--stack" data-testid="term-proposal">
            <span class="bterm-item-name">{{ p.title }}</span>
            <span v-if="hasAgent && myVoted.has(String(p.id))" class="bterm-item-sub">
              {{ t('bridge.term.alreadyVoted', 'you voted') }}
            </span>
            <span v-else-if="hasAgent" class="bterm-votes">
              <button type="button" class="bterm-item-act" :disabled="busy"
                      data-testid="term-vote-for" @click="doVote(p, 'for')">{{ t('bridge.term.for', 'FOR') }}</button>
              <button type="button" class="bterm-item-act" :disabled="busy"
                      data-testid="term-vote-against" @click="doVote(p, 'against')">{{ t('bridge.term.against', 'AGAINST') }}</button>
            </span>
          </li>
        </ul>
      </template>
    </div>

    <!-- GUILD BOARD — the income half. WORK shows what you already have. -->
    <div v-else-if="lane === 'guild'" class="bterm-body">
      <p v-if="!hasAgent" class="bterm-note">
        {{ t('bridge.term.needAgent', 'Select an agent first: guild work is posted and bid on as an agent, not as you.') }}
      </p>
      <template v-else>
        <form class="bterm-row" @submit.prevent="doPostWork">
          <input v-model="postTitle" class="bterm-in" type="text"
                 :placeholder="t('bridge.term.workTitle', 'what needs doing')" />
          <input v-model="postBounty" class="bterm-in bterm-in--sm" type="text" inputmode="decimal"
                 :placeholder="t('bridge.term.bounty', 'bounty')" />
          <!-- The amount is ON the button: nothing here commits money silently. -->
          <button type="submit" class="bterm-btn" data-testid="term-post-work"
                  :disabled="busy || !postTitle.trim() || !(parseFloat(postBounty) > 0)">
            {{ parseFloat(postBounty) > 0 ? `${t('bridge.term.post', 'POST')} ${num(postBounty, 2)} ${currency}` : t('bridge.term.post', 'POST') }}
          </button>
        </form>
        <p v-if="busy" class="bterm-note">{{ t('common.loading', 'Working') }}</p>
        <ReadFailedNotice v-else-if="boardFailed" dense :retry="loadGuild" data-testid="term-board-failed"
          :text="t('bridge.term.boardFailed', 'The open work on this registry could not be read just now.')" />
        <p v-else-if="board.length === 0" class="bterm-note">
          {{ t('bridge.term.noWork', 'No open work on this registry right now.') }}
        </p>
        <ul v-else class="bterm-list">
          <li v-for="o in board" :key="o.id" class="bterm-item bterm-item--stack" data-testid="term-order">
            <span class="bterm-item-name">{{ o.title }}</span>
            <span class="bterm-item-sub">{{ money(num(o.bounty, 2)) }} {{ o.currency || currency }}
              <template v-if="o.bid_count"> &middot; {{ o.bid_count }} {{ t('bridge.term.bids', 'bids') }}</template>
            </span>
            <span v-if="bidFor === String(o.id)" class="bterm-votes">
              <input v-model="bidPrice" class="bterm-in bterm-in--sm" type="text" inputmode="decimal"
                     :placeholder="t('bridge.term.price', 'your price')" />
              <button type="button" class="bterm-item-act" data-testid="term-bid-send"
                      :disabled="busy || !(parseFloat(bidPrice) > 0)" @click="doBid(o)">
                {{ t('bridge.term.sendBid', 'SEND BID') }}
              </button>
            </span>
            <button v-else type="button" class="bterm-item-act" data-testid="term-bid"
                    :disabled="busy" @click="bidFor = String(o.id); bidPrice = ''">
              {{ t('bridge.term.bid', 'BID') }}
            </button>
          </li>
        </ul>
      </template>
    </div>

    <!-- ASSISTANT — the three-brain machine Pocket carries, docked. -->
    <div v-else-if="lane === 'assistant'" class="bterm-body">
      <AssistantDock />
    </div>

    <!-- The app's own agent card. Mounted only once something asks for it. -->
    <AgentDetailModal v-if="showAgent" v-model:show="showAgent" :agent-did="openDid" />
  
    <!-- OURSTATE — your threads, docked. Rows open the thread; nothing here
         posts, pays or accepts (that lives in the thread, one door per act). -->
    <div v-if="lane === 'ourstate'" class="bterm-body" data-testid="bterm-ourstate">
      <p v-if="osLoading" class="bterm-msg">{{ t('common.loading', 'Loading…') }}</p>
      <p v-else-if="!osThreads.length" class="bterm-empty" data-testid="bterm-os-empty">
        {{ t('bridge.term.osEmpty', 'No threads yet. Open OurChat to start one.') }}</p>
      <button v-for="c in osThreads" :key="c.id" type="button" class="bterm-osrow"
              :data-testid="`bterm-os-${c.id}`" @click="openThread(c.id)">
        <span class="bterm-osname">
          {{ c.kind === 'org' ? (c.title || t('ourstate.rooms.room', 'Org room'))
             : (c.counterparty?.name || t('ourstate.list.unknown', 'Conversation')) }}
        </span>
        <span class="bterm-ospreview">{{ c.last_preview || '' }}</span>
        <span v-if="c.unread > 0" class="bterm-osunread">{{ c.unread }}</span>
      </button>
    </div>
    <!-- §MEMBERSHIP: a member's binding vote confirmed on the phone or with a code (teleported to the page) -->
    <StepUpConfirm
      v-if="memberFlow.stepUp.value"
      :show="true"
      :challenge="memberFlow.stepUp.value"
      :busy="memberFlow.busy.value"
      :error="memberFlow.stepUpError.value"
      @update:show="(v: boolean) => { if (!v) memberFlow.cancel() }"
      @approved="(id: string) => memberFlow.approved(id)"
      @code="(c: string) => memberFlow.code(c)"
    />
</section>
</template>

<style scoped>
.bterm {
  position: absolute;
  /**
   * §BRIDGE R13 #10 — dock inside the STAGE column, never over a rail.
   *
   * Screenshot 3 caught it exactly: the EXCHANGE lane was pinned `right: 1rem`
   * and sat on top of the LIVE LEDGER, so opening the lane cost you the panel
   * you were reading it against. `--brg-stage-r` is the measured distance from
   * the right edge of the viewport to the right edge of the stage, published by
   * Mission Control; falling back to 1rem keeps this component usable anywhere
   * else it might be mounted.
   */
  right: calc(var(--brg-stage-r, 1rem) + 0.75rem);
  bottom: calc(var(--brg-pulse-h, 0px) + 0.75rem);
  width: min(30rem, calc(100vw - var(--brg-stage-l, 0px) - var(--brg-stage-r, 0px) - 2rem));
  max-height: min(26rem, 60%);
  display: flex;
  flex-direction: column;
  z-index: 3;                       /* above the HUD cards, below nothing else */
  background: rgba(8, 12, 22, 0.94);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.24));
  border-radius: 4px;
  /* No backdrop-filter: it sits over a repainting WebGL canvas, which re-blurs
     the region every frame and is exactly what made the P2 cards drop their
     fill on real GPU hardware. */
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  color: var(--nc-text, #d6e2f2);
}
.bterm-hdr {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.4rem 0.55rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.16));
}
.bterm-title { font-size: 0.62rem; letter-spacing: 0.16em; color: var(--nc-primary, #22d3ee); }
.bterm-as {
  font-size: 0.55rem; letter-spacing: 0.06em; color: var(--nc-text-dim, #7c8797);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 11rem;
}
.bterm-full {
  margin-left: auto; font-size: 0.55rem; letter-spacing: 0.1em;
  color: var(--nc-text-dim, #7c8797); text-decoration: none;
}
.bterm-full:hover { color: var(--nc-primary, #22d3ee); }
.bterm-x {
  flex: 0 0 auto; background: transparent; border: 0; cursor: pointer;
  color: var(--nc-text-dim, #7c8797); display: inline-flex; padding: 0.15rem;
}
.bterm-x:hover { color: var(--nc-text, #d6e2f2); }
.bterm-body { padding: 0.5rem 0.55rem 0.6rem; overflow-y: auto; min-height: 0; }
.bterm-msg { margin: 0; padding: 0.35rem 0.55rem; font-size: 0.58rem; letter-spacing: 0.04em; }
.bterm-msg.is-err { color: var(--nc-danger, #ff6b6b); }
.bterm-msg.is-ok { color: var(--nc-success, #4ade80); }
.bterm-row { display: flex; align-items: center; gap: 0.4rem; margin-bottom: 0.45rem; }
.bterm-row--stat { justify-content: space-between; }
.bterm-k { font-size: 0.55rem; letter-spacing: 0.12em; color: var(--nc-text-dim, #7c8797); }
.bterm-v { font-size: 0.7rem; font-weight: 700; }
.bterm-in {
  flex: 1 1 auto; min-width: 0;
  background: rgba(3, 6, 14, 0.9); color: inherit;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  border-radius: 3px; padding: 0.25rem 0.4rem; font: inherit; font-size: 0.62rem;
}
.bterm-in--sm { flex: 0 0 4.5rem; }
.bterm-btn, /* R15: a row that carries its own controls needs to wrap, not squeeze. */
.bterm-item--stack { flex-wrap: wrap; row-gap: 0.3rem; }
.bterm-votes { display: flex; gap: 0.35rem; align-items: center; margin-left: auto; }
.bterm-item-act {
  flex: 0 0 auto; cursor: pointer;
  background: transparent; color: var(--nc-text-dim, #8fa3c0);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22));
  border-radius: 3px; padding: 0.25rem 0.5rem;
  font: inherit; font-size: 0.55rem; letter-spacing: 0.1em;
}
.bterm-btn:hover:not(:disabled), .bterm-item-act:hover:not(:disabled) {
  color: var(--nc-primary, #22d3ee); border-color: var(--nc-primary, #22d3ee);
}
.bterm-btn:disabled, .bterm-item-act:disabled { opacity: 0.45; cursor: default; }
.bterm-note { margin: 0.3rem 0; font-size: 0.58rem; color: var(--nc-text-dim, #7c8797); }
.bterm-sub {
  margin: 0.5rem 0 0.25rem; font-size: 0.52rem; letter-spacing: 0.14em;
  color: var(--nc-text-dim, #6b7f9e);
}
.bterm-list { list-style: none; margin: 0; padding: 0; }
.bterm-item {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.25rem 0; border-bottom: 1px solid rgba(120, 160, 210, 0.08);
  font-size: 0.6rem;
}
.bterm-item-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* R13 #6 — a grid, so nothing jumps as the numbers change width. */
.bterm-order { display: grid; grid-template-columns: 2.4rem 1fr auto 0.6rem auto auto; gap: 0.35rem; align-items: baseline; }
.bterm-hold { display: grid; grid-template-columns: 1fr auto auto; gap: 0.45rem; align-items: baseline; }
.bterm-side { font-size: 0.52rem; letter-spacing: 0.1em; text-transform: uppercase; }
.bterm-order.is-buy .bterm-side { color: var(--nc-success, #22c55e); }
.bterm-order.is-sell .bterm-side { color: #ff8a7a; }
.bterm-sym { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bterm-qty, .bterm-px { font-variant-numeric: tabular-nums; text-align: right; }
.bterm-at { opacity: 0.45; }
.bterm-px { color: var(--nc-text, #d6e2f2); }
.bterm-item-sub { flex: 0 0 auto; color: var(--nc-text-dim, #7c8797); font-size: 0.55rem; }
.bterm-item-go { flex: 0 0 auto; color: var(--nc-text-dim, #7c8797); text-decoration: none; padding: 0 0.25rem; }
.bterm-item-go:hover { color: var(--nc-primary, #22d3ee); }

@media (prefers-reduced-motion: reduce) { .bterm { transition: none; } }
.bterm-osrow { display: grid; grid-template-columns: 1fr auto; grid-template-rows: auto auto; column-gap: .5rem; width: 100%; padding: .35rem .5rem; border: none; background: none; color: inherit; text-align: left; cursor: pointer; border-bottom: 1px solid var(--border-color, rgba(128,128,128,.14)); }
.bterm-osname { font-weight: 600; font-size: .78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bterm-ospreview { grid-column: 1; font-size: .68rem; opacity: .6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bterm-osunread { grid-row: 1 / span 2; align-self: center; background: var(--primary-color, #4fd8c4); color: #06211d; border-radius: 999px; min-width: 18px; padding: 0 5px; font-size: .66rem; font-weight: 700; text-align: center; }
.bterm-empty { font-size: .72rem; opacity: .6; padding: .5rem; }
</style>
