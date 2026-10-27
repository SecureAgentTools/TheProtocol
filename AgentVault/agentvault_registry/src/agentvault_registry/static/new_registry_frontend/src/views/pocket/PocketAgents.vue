<!-- POCKET · Agents (AAA+ 2026-07-08) — searchable accounts list with REAL balances,
     status dots, and balance-first ordering. Deep management lives in Advanced mode. -->
<template>
  <div class="pg-wrap" ref="ptrEl" @touchstart.passive="ptr.onTouchStart" @touchmove.passive="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
    <div class="pkx-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pkx-spin': ptr.ptrArmed.value }" />
    </div>
    <div class="pg-head" data-tour="pk-agents">
      <h1 class="pg-title">{{ t('pocket.agents.title', 'My agents') }}</h1>
      <!-- §FESUITE (V0578): a count is what the read answered; over a failed read it read "0" (or "0 / 100" for a search) -->
      <span v-if="lane === 'mine' && !loading && !listErr" class="pg-count" data-testid="pg-count">{{ filtered.length }}<template v-if="query"> / {{ agents.length }}</template></span>
    </div>

    <!-- §POCKETDISC — two lanes, his split: your fleet | the network. A visit
         is not a choice: nothing is persisted, MINE is simply where the tab
         has always opened. ?lane=discover is the deep-link door. -->
    <div class="pg-lanes" role="tablist">
      <button class="pg-lane" :class="{ on: lane === 'mine' }" role="tab" :aria-selected="lane === 'mine'"
              data-testid="pg-lane-mine" @click="lane = 'mine'">{{ t('pocket.agents.laneMine', 'Mine') }}</button>
      <button class="pg-lane" :class="{ on: lane === 'discover' }" role="tab" :aria-selected="lane === 'discover'"
              data-testid="pg-lane-discover" @click="lane = 'discover'">{{ t('pocket.agents.laneDiscover', 'Discover') }}</button>
    </div>

    <component :is="PocketDiscover" v-if="lane === 'discover'" :initial-q="discoverQ" :initial-pricing="discoverPricing" />

    <template v-if="lane === 'mine'">

    <label class="pg-search">
      <Icon name="mdi:magnify" />
      <input v-model="query" type="search" :placeholder="t('pocket.agents.searchPlaceholder', 'Search agents…')" :aria-label="t('pocket.agents.searchLabel', 'Search agents')" />
    </label>

    <div v-if="loading" class="pg-list"><div v-for="n in 4" :key="n" class="pg-skel"></div></div>
    <ul v-else class="pg-list">
      <!-- §POCKETBRIDGE #PK21 — tap opens the app's OWN full agent card
           (AgentDetailModal: proven work, earned marks, track record) instead
           of building a second, poorer copy of identity for the phone. -->
      <!-- §FESUITE: the row stays a list item (a role="button" li is not one, and it held the ⋯ button inside a
           button); a tap anywhere still opens it, and the inner element is what a keyboard or screen reader presses -->
      <li v-for="a in filtered" :key="a.did" class="pg-card pg-card-tap"
          @click="hold.guardClick(() => openDetail(a.did))()"
          @pointerdown="startHold(a, $event)" @pointermove="hold.onPointermove"
          @pointerup="hold.onPointerup" @pointercancel="hold.onPointercancel" @pointerleave="hold.onPointerup">
        <div class="pg-open" role="button" tabindex="0"
             @keydown.enter.prevent="openDetail(a.did)" @keydown.space.prevent="openDetail(a.did)">
          <div class="pg-ava" :class="'pg-ava-' + (a.status || 'active')">
            <Icon name="mdi:robot" />
            <span class="pg-ava-dot" :class="'pg-dot-' + (a.status || 'active')" aria-hidden="true"></span>
          </div>
          <div class="pg-body">
            <div class="pg-name">{{ a.name || t('pocket.common.unnamed', '(unnamed)') }}<span v-if="a.wallet" class="pg-wallet" data-testid="pg-wallet-chip">{{ t('wallet.chip', 'WALLET') }}</span><span v-if="marks[a.did]" class="pkx-mark" :class="'pkx-mark-' + marks[a.did].tier" :title="tp('pocket.home.verifiedJobs', '{n} verified jobs', { n: marks[a.did].jobs })">{{ tierLabel(marks[a.did].tier) }} · {{ marks[a.did].jobs }}</span></div>
            <div class="pg-did">{{ shorten(a.did) }}</div>
          </div>
          <div class="pg-right">
            <div v-if="a.balance !== null" class="pg-bal">{{ amount(a.balance) }} <small>{{ a.ccy || ccy }}</small></div>
            <span v-else class="pg-status" :class="'pg-' + (a.status || 'active')">{{ statusLabel(a.status) }}</span>
          </div>
        </div>
        <button class="pg-dots" :aria-label="t('pocket.cosmetics.title', 'Cosmetics')" data-testid="pg-dots"
                @click.stop="openCosmetics(a)"><Icon name="mdi:menu" /></button>
      </li>
      <!-- §FESUITE (V0578): "No agents match" is what an answered search says; a search the registry did not answer is the
           error below, never a "none" -->
      <li v-if="!filtered.length && query && !listErr" class="pg-empty" data-testid="pg-nomatch">
        <Icon name="mdi:magnify" class="pg-empty-ico" />
        <p>{{ tp('pocket.agents.noMatch', 'No agents match “{q}”.', { q: query }) }}</p>
      </li>
      <li v-else-if="listErr" class="pg-empty pg-err" data-testid="pg-err">
        <Icon name="mdi:alert-circle-outline" class="pg-empty-ico" />
        <p>{{ t('pocket.agents.loadFailed', 'Could not load your agents') }}: {{ listErr }}</p>
        <button class="pg-retry" @click="loadList(query || undefined)">{{ t('cta.retry', 'Retry') }}</button>
      </li>
      <li v-else-if="!agents.length" class="pg-empty" data-testid="pg-empty">
        <Icon name="mdi:robot" class="pg-empty-ico" />
        <p>{{ t('pocket.agents.empty', 'No agents yet.') }}</p>
        <!-- §PHONESTART (2026-09-02) — was "Create your first one in Advanced mode → Agent Forge": a
             door to a WebGL desktop view, from a phone. The quick-create modal is mounted in the shell. -->
        <button class="pg-create" data-testid="pg-create" @click="uiStore.openQuickAgentModal()">{{ t('pocket.agents.emptyCreate', 'Create your wallet agent') }}</button>
        <button class="pg-retry" @click="lane = 'discover'">{{ t('pocket.agents.emptyDiscover', 'Browse the network instead') }}</button>
      </li>
    </ul>
    <!-- §LEDGERGATE (V0601): the hint names locking only where the registry says locking is open (registry-config), as the
         Pocket home's own lock doors do; EU and ASIA said "staking" here with locking off -->
    <p class="pg-hint" data-testid="pg-hint">{{ stakingOn ? t('pocket.agents.hint', 'Full agent management (forge, cards, evals, locks) lives in') : t('pocket.agents.hintNoStaking', 'Full agent management (forge, cards, evals) lives in') }}
      <a class="pg-adv" href="#/my-agents" data-testid="pg-adv" @click="setAdvanced">{{ t('pocket.agents.advancedMode', 'Advanced mode') }}</a>.</p>
    </template>

    <component :is="AgentDetailModal" v-if="detailEver" v-model:show="detailOpen" :agent-did="detailDid" />
    <!-- §POCKETDISC — hold a row (or its ⋯) to dress the agent -->
    <component :is="PocketCosmetics" v-if="cosmeticsEver" :open="cosmeticsOpen" :agent="cosmeticsAgent"
               :own-agents="agents" :earned-jobs="cosmeticsAgent && marks[cosmeticsAgent.did]?.jobs || 0"
               @close="cosmeticsOpen = false" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, defineAsyncComponent } from 'vue'
import { currentOwnCurrency } from '@/composables/useFrameManifest'
import { useRoute, useRouter } from 'vue-router'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { usePressHold } from '@/composables/usePressHold'
import { marksForMany } from '@/services/pocketMarks'
import { EARNED_TIERS, type EarnedMarks } from '@/services/api/trackRecord'
import Icon from '@/components/Icon.vue'
import { agentApi } from '@/services/api/agents'
import { developerApi } from '@/services/api/developers'
import { useCurrency } from '@/composables/useCurrency'
import { useActingContext } from '@/composables/useActingContext'
// §FOREIGNACT — where this agent's money actually lives (null-not-guessed for a
// foreign agent whose registry card has not answered yet).
const { actingCurrencyLabel } = useActingContext()
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useUIStore } from '@/stores/ui'
import { rememberUiMode } from '@/services/uiMode'
import { isWalletAgent } from '@/services/walletAgent'

const { t, tp } = useI18n()
const { config: registryCfg } = useRegistryConfig()
const stakingOn = computed(() => registryCfg.value.staking_enabled === true)
const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { void loadList(query.value || undefined) })
const { amount, localCurrency } = (() => {
  try { const c = useCurrency(); return { amount: c.amount, localCurrency: (c as any).localCurrency } }
  catch { return { amount: (v: any) => String(v ?? '0'), localCurrency: computed(() => currentOwnCurrency()) } }
})()

interface Row { did: string; name?: string; status?: string; balance: string | null; ccy?: string; _n: number
  /** §WALLETAGENT — the card carries `tags: ['wallet']`. */
  wallet?: boolean
}
const agents = ref<Row[]>([])
// §PHONESTART — the create door, and the list notices the agent it just created.
const uiStore = useUIStore()
watch(() => uiStore.agentCreatedTick, () => { void loadList() })
const loading = ref(true)
const listErr = ref('')
// §POCKETBRIDGE2 W6 — earned marks on the visible rows, resolve-what-you-see.
const marks = ref<Record<string, EarnedMarks>>({})
// param is `tier`, NOT `t`: `t` is the translate function in this scope.
const tierLabel = (tier: string | null) => EARNED_TIERS.find(x => x.tier === tier)?.label || ''
/* Agent status arrives as a machine enum; render a translated word for the two
   the roster can actually show, and the raw value for anything unexpected
   (inventing a friendly label for a status we do not know would be a lie). */
const statusLabel = (s?: string) => {
  const v = (s || 'active').toLowerCase()
  if (v === 'active') return t('pocket.agents.statusActive', 'active')
  if (v === 'suspended') return t('pocket.agents.statusSuspended', 'suspended')
  return v
}
const query = ref('')
// §POCKETBRIDGE3 WS-B — the voice find door arrives as /pocket/agents?q=…;
// query-only navigation does not remount, so this is a watcher (§NOTIFLOG).
const _route = useRoute(); const _router = useRouter()
watch(() => _route.query.q, (v) => {
  if (typeof v === 'string' && v) {
    query.value = v
    const qq = { ..._route.query } as Record<string, any>
    delete qq.q
    _router.replace({ query: qq }).catch(() => {})
  }
}, { immediate: true })
const ccy = ref('')
const shorten = (s: string) => !s ? '—' : s.length > 34 ? s.slice(0, 20) + '…' + s.slice(-8) : s

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return agents.value
  return agents.value.filter(a => (a.name || '').toLowerCase().includes(q) || a.did.toLowerCase().includes(q))
})

/* #PK21 — the full card, lazily (88KB SFC: loaded on first tap, never sooner). */
const AgentDetailModal = defineAsyncComponent(() => import('@/components/AgentDetailModal.vue'))
/* §POCKETDISC — the network lane + the cosmetics sheet, both lazy. */
const PocketDiscover = defineAsyncComponent(() => import('./PocketDiscover.vue'))
const PocketCosmetics = defineAsyncComponent(() => import('./PocketCosmetics.vue'))
const lane = ref<'mine' | 'discover'>('mine')
const discoverQ = ref('')
// §BUYSERVICE — ?pricing=paid opens Discover already filtered to the agents you
// can actually buy from (the Services lane).
const discoverPricing = ref<'' | 'paid' | 'free'>('')
watch(() => _route.query.lane, (v) => {
  if (v === 'discover' || v === 'mine') {
    lane.value = v
    if (typeof _route.query.dq === 'string') discoverQ.value = _route.query.dq
    const _p = _route.query.pricing
    if (_p === 'paid' || _p === 'free') discoverPricing.value = _p
    const qq = { ..._route.query } as Record<string, any>
    delete qq.lane; delete qq.dq; delete qq.pricing
    _router.replace({ query: qq }).catch(() => {})
  }
}, { immediate: true })

const cosmeticsEver = ref(false)
const cosmeticsOpen = ref(false)
const cosmeticsAgent = ref<{ did: string; name?: string } | null>(null)
function openCosmetics(a: { did: string; name?: string }) {
  cosmeticsAgent.value = { did: a.did, name: a.name }
  cosmeticsEver.value = true; cosmeticsOpen.value = true
}
let holdTarget: { did: string; name?: string } | null = null
const hold = usePressHold(() => { if (holdTarget) openCosmetics(holdTarget) })
function startHold(a: { did: string; name?: string }, e: PointerEvent) { holdTarget = a; hold.onPointerdown(e) }
const detailEver = ref(false)
const detailOpen = ref(false)
const detailDid = ref('')
function openDetail(did: string) { detailDid.value = did; detailEver.value = true; detailOpen.value = true }

/* F12's sibling on the roster: the loaded window is newest-first, so on a big
   fleet a searched name outside it "did not exist". The server's whole-fleet
   `q` search (the §agentfinder rail) answers instead — debounced, and the
   instant client filter still narrows what is already on screen. */
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(query, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  const term = q.trim()
  searchTimer = setTimeout(() => { void loadList(term.length >= 2 ? term : undefined) }, 350)
})

async function loadList(q?: string) {
  loading.value = true
  listErr.value = ''
  try {
    // Default listing is server-ranked by balance (#PK6's F12 rail) — the
    // "balance-first ordering" this screen always claimed, now actually true
    // for the whole fleet instead of the newest-100 window.
    const res: any = await agentApi.getMyAgents(q ? { limit: 100, q } : { limit: 100, sort: 'balance' })
    const list = (Array.isArray(res) ? res : res?.items || res?.data || [])
      .map((a: any) => ({ did: a.did || a.agent_did, name: a.name || a.agent_card_name, wallet: isWalletAgent(a), status: (a.status || '').toLowerCase(),
        balance: Number.isFinite(Number(a.liquid_balance)) ? String(Number(a.liquid_balance)) : null, ccy: '', _n: Number(a.liquid_balance ?? 0) || 0 }))
      .filter((a: any) => a.did && a.status !== 'revoked' && a.status !== 'deleted')
    agents.value = list
    loading.value = false // list is usable immediately; live balances stream in below
    // Live balances — batch in chunks of 25 (best-effort; the server-ranked
    // snapshot stays where a chunk fails).
    for (let i = 0; i < list.length; i += 25) {
      const chunk = list.slice(i, i + 25).map((a: any) => a.did)
      try {
        const raw: any = await developerApi.getAgentBalancesBatch(chunk)
        const bal: any = raw?.balances || raw || {}
        for (const a of agents.value) {
          const b = bal?.[a.did]
          if (b) { const n = Number(b.liquid_balance ?? b.balance ?? 0); a.balance = String(n); a.ccy = b.currency || ''; a._n = n }
        }
      } catch { /* keep the snapshot for this chunk */ }
    }
    agents.value = [...agents.value].sort((x, y) => y._n - x._n)
    marksForMany(agents.value.map((a: any) => a.did), (did, m) => { marks.value = { ...marks.value, [did]: m } })
  } catch (e: any) {
    // §POCKETBRIDGE2 W1 — an error is an error; "No agents yet. Create your
    // first one" over a failed read is the F12 lie on a different tab.
    listErr.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  }
  finally { loading.value = false }
}

onMounted(async () => {
  // §FOREIGNACT — acting agent's currency, never the viewing page's.
  try { ccy.value = actingCurrencyLabel.value } catch { ccy.value = '' }
  await loadList()
})
/* §FIRSTHOUR (2026-09-03) — the footer door was #/onboarding (the WebGL forge) and remembered nothing;
   every other Pocket 'Advanced mode' door lands on a desktop view AND records the preference. */
function setAdvanced() { rememberUiMode('advanced') }
</script>

<style scoped>
.pg-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; box-sizing: border-box; }
.pg-head { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.7rem; }
.pg-title { font-size: 1.15rem; margin: 0; }
.pg-count { font-size: 0.72rem; font-weight: 700; color: var(--nc-primary, #00d4ff);
  background: rgba(0,212,255,0.09); border: 1px solid rgba(0,212,255,0.24); border-radius: 7px; padding: 0.12rem 0.45rem;
  font-variant-numeric: tabular-nums; }
.pg-search { display: flex; align-items: center; gap: 0.5rem; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.09); border-radius: 13px; padding: 0.55rem 0.8rem; margin-bottom: 0.7rem;
  transition: border-color 0.15s; }
.pg-search:focus-within { border-color: rgba(0,212,255,0.4); }
.pg-search :deep(svg) { width: 1rem; height: 1rem; opacity: 0.5; flex: 0 0 auto; }
.pg-search input { flex: 1 1 auto; background: none; border: none; outline: none; color: inherit; font-size: 16px; min-width: 0; }
.pg-search input::placeholder { color: rgba(230,237,243,0.35); }
.pg-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pg-lanes { display: flex; gap: 0.4rem; margin-bottom: 0.7rem; }
.pg-lane { flex: 1 1 0; min-height: 44px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.1);
  background: rgba(255,255,255,0.04); color: rgba(230,237,243,0.7); font-size: 0.82rem; font-weight: 650;
  cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pg-lane.on { color: var(--nc-primary, #00d4ff); border-color: rgba(0,212,255,0.35); background: rgba(0,212,255,0.08); }
.pg-dots { flex: 0 0 auto; min-width: 44px; min-height: 44px; display: grid; place-items: center;
  background: none; border: none; color: rgba(230,237,243,0.45); cursor: pointer; -webkit-tap-highlight-color: transparent;
  margin-right: -0.5rem; }
.pg-dots :deep(svg) { width: 1.05rem; height: 1.05rem; }
.pg-card { display: flex; align-items: center; gap: 0.7rem; touch-action: pan-y; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07); border-radius: 15px; padding: 0.72rem 0.85rem; min-height: 56px;
  transition: background 0.15s; }
.pg-card:active { background: rgba(255,255,255,0.06); }
.pg-card-tap { cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pg-open { display: flex; align-items: center; gap: 0.7rem; flex: 1 1 auto; min-width: 0; border-radius: 11px; outline: none; }
.pg-open:focus-visible { box-shadow: 0 0 0 2px var(--nc-primary, #00d4ff); }
.pg-ava { position: relative; width: 2.5rem; height: 2.5rem; border-radius: 13px; display: grid; place-items: center; flex: 0 0 auto;
  background: rgba(0,212,255,0.1); border: 1px solid rgba(0,212,255,0.2); }
.pg-ava :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }
.pg-ava-suspended { background: rgba(245,158,11,0.09); border-color: rgba(245,158,11,0.25); }
.pg-ava-suspended :deep(svg) { color: #fbbf24; }
.pg-ava-dot { position: absolute; right: -3px; bottom: -3px; width: 11px; height: 11px; border-radius: 50%;
  border: 2px solid #0a0d12; }
.pg-dot-active { background: #34d399; }
.pg-dot-suspended { background: #fbbf24; }
.pg-body { flex: 1 1 auto; min-width: 0; }
.pg-name { font-size: 0.9rem; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg-wallet { font-size: 0.55rem; letter-spacing: 0.12em; font-weight: 700; padding: 0.05rem 0.35rem; border-radius: 999px; margin-left: 0.35rem; vertical-align: middle;
  color: var(--nc-primary, #00e5ff); border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.5); }
.pg-did { font-size: 0.68rem; opacity: 0.45; font-family: ui-monospace, monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pg-right { flex: 0 0 auto; text-align: right; }
.pg-bal { font-variant-numeric: tabular-nums; font-variant-numeric: tabular-nums; font-weight: 650; font-size: 0.86rem; }
.pg-bal small { font-size: 0.6rem; opacity: 0.5; font-weight: 600; }
.pg-status { font-size: 0.6rem; text-transform: uppercase; letter-spacing: 0.05em; padding: 0.16rem 0.5rem; border-radius: 6px; background: rgba(255,255,255,0.08); }
.pg-active { background: rgba(16,185,129,0.15); color: #34d399; }
.pg-suspended { background: rgba(245,158,11,0.15); color: #fbbf24; }
.pg-err p { color: #ff9a9a; }
.pg-retry { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.2); border-radius: 10px;
  color: inherit; padding: 0.5rem 1rem; min-height: 44px; cursor: pointer; margin-top: 0.4rem; }
.pg-empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2.2rem 1rem; opacity: 0.6; text-align: center; }
.pg-empty-ico { width: 2rem; height: 2rem; }
.pg-empty p { margin: 0; font-size: 0.85rem; max-width: 24rem; }
.pg-create { font-size: 0.85rem; font-weight: 600; padding: 0.55rem 1.1rem; border-radius: 10px; cursor: pointer; opacity: 1;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.55); background: rgba(var(--nc-primary-rgb, 0,229,255), 0.12); color: var(--nc-primary, #00e5ff); }
.pg-hint { margin-top: 1rem; font-size: 0.74rem; opacity: 0.5; text-align: center; }
.pg-adv { color: var(--nc-primary, #00d4ff); }
.pg-skel { height: 3.6rem; border-radius: 15px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pg-shim 1.3s ease-in-out infinite; }
@keyframes pg-shim { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .pg-skel { animation: none; } }
</style>
