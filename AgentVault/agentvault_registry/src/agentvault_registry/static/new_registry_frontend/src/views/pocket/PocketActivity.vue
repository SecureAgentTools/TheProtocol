<!-- POCKET · Activity (AAA+ 2026-07-08) — your agents' ledger events, day-grouped.
     Source: /developers/me/activity (EventStore events touching YOUR agents, 200-event window). -->
<template>
  <div class="pv-wrap" ref="ptrEl" @touchstart.passive="ptr.onTouchStart" @touchmove.passive="ptr.onTouchMove" @touchend="ptr.onTouchEnd">
    <div class="pkx-ptr" :style="{ height: ptr.ptrH.value + 'px', opacity: ptr.ptrH.value ? 1 : 0 }" aria-hidden="true">
      <Icon name="mdi:refresh" :class="{ 'pkx-spin': ptr.ptrArmed.value }" />
    </div>
    <div class="pv-head">
      <h1 class="pv-title">{{ t('pocket.activity.title', 'Activity') }}</h1>
      <span v-if="!loading && rows.length" class="pv-count">{{ rows.length }}</span>
    </div>
    <!-- §POCKETBRIDGE5 W-G — pick ONE agent to read its OWN ledger record
         (complete per aggregate) instead of the sampled frame window. -->
    <select v-if="credAgents.length" v-model="scopeDid" class="pv-scope-sel" data-testid="pv-scope-sel" :aria-label="t('pocket.activity.scopeLabel', 'Activity scope')" @change="reload">
      <option value="">{{ t('pocket.activity.scopeAll', 'All my agents · sampled window') }}</option>
      <option v-for="a in credAgents" :key="a.did" :value="a.did">{{ a.name || a.did.slice(0, 24) + '…' }} · {{ t('pocket.activity.ownRecord', 'own record') }}</option>
    </select>
    <p v-if="!loading && scopeErr" class="pv-scope pv-scope-err" data-testid="pv-scope-err" role="status">{{ scopeErr }}</p>
    <p v-else-if="!loading && rows.length" class="pv-scope" data-testid="pv-scope">
      <template v-if="scopeDid">{{ tp('pocket.activity.scopeAgent', "this agent's own ledger record · newest {n} events", { n: shownOf[0] }) }}{{ scopeComplete ? ' ' + t('pocket.activity.complete', '(complete)') : ' ' + t('pocket.activity.olderHidden', '(older history not shown)') }}</template>
      <template v-else>{{ tp('pocket.activity.scopeWindow', "your agents' events from the NEWEST {n} on this registry's ledger", { n: sampledWindow.toLocaleString(appLocale()) }) }}</template><span v-if="shownOf[0] > shownOf[1]"> · {{ tp('pocket.activity.showingOf', 'showing {shown} of {total}', { shown: shownOf[1], total: shownOf[0] }) }}</span>
    </p>

    <!-- §POCKETBRIDGE #PK19 — LIVE, session-honest. The SAME one websocket
         client the bridge runs (S9); 'yours' via the SAME grammar predicate
         (S4). It counts what THIS SESSION saw — minutes before you arrived are
         absence, never quiet — and the caption states exactly that. -->
    <section v-if="liveRows.length || liveSeen > 0" class="pv-day pv-live" data-testid="pv-live">
      <h2 class="pv-day-label"><span class="pv-live-dot" :class="{ on: connected }" aria-hidden="true"></span> {{ t('pocket.activity.liveThisSession', 'Live · this session') }}</h2>
      <ul v-if="liveRows.length" class="pv-list">
        <li v-for="r in liveRows" :key="r.key" class="pv-row pv-row-live">
          <span class="pv-ico neutral"><Icon name="mdi:swap-horizontal" /></span>
          <div class="pv-body">
            <div class="pv-label">{{ r.text }}</div>
            <div class="pv-sub">{{ r.when }}</div>
          </div>
        </li>
      </ul>
      <p class="pv-live-note" data-testid="pv-live-note">
        {{ tp('pocket.activity.liveNote', "{seen} network events since this screen's session opened · {mine} from your agents", { seen: liveSeen.toLocaleString(appLocale()), mine: liveMineSeen }) }}{{ mineApprox ? ' ' + t('pocket.activity.trimmed', '(some batches trimmed under load)') : '' }}
      </p>
    </section>

    <div v-if="loading" class="pv-list"><div v-for="n in 5" :key="n" class="pv-skel"></div></div>
    <template v-else-if="groups.length">
      <section v-for="g in groups" :key="g.day" class="pv-day">
        <h2 class="pv-day-label">{{ g.day }}</h2>
        <ul class="pv-list">
          <!-- loop var is `row`, NOT `t`: `t` is the translate function here. -->
          <li v-for="row in g.items" :key="row.id" class="pv-row" :class="{ 'pv-sec': row.security }">
            <span class="pv-ico" :class="row.security ? 'sec' : row.kind">
              <Icon :name="row.icon" />
            </span>
            <div class="pv-body">
              <div class="pv-label">{{ row.label }}</div>
              <div class="pv-sub">{{ row.when }}<span v-if="row.counter"> · {{ row.counter }}</span></div>
            </div>
            <div v-if="row.amount" class="pv-amt" :class="row.kind">{{ row.sign }}{{ amount(row.amount) }}</div>
          </li>
        </ul>
      </section>
    </template>
    <div v-else-if="loadErr" class="pv-empty pv-err" data-testid="pv-err">
      <span class="pv-empty-ring"><Icon name="mdi:alert-circle-outline" /></span>
      <p><strong>{{ t('pocket.activity.loadFailed', 'Could not load activity.') }}</strong> {{ loadErr }}</p>
      <button class="pv-retry" @click="reload">{{ t('cta.retry', 'Retry') }}</button>
    </div>
    <!-- §FESUITE (V0578): "all quiet" is what an answered read says; under a scope read that failed (or a server note that
         its read went wrong) the scope line above says so, and this claims nothing -->
    <div v-else-if="!scopeErr" class="pv-empty" data-testid="pv-quiet">
      <span class="pv-empty-ring"><Icon name="mdi:history" /></span>
      <p><strong>{{ t('pocket.activity.quietTitle', 'All quiet in the sampled window.') }}</strong> {{ t('pocket.activity.quietSub', 'Ledger events from your agents land here as they transact.') }}</p>
      <a class="pv-adv" href="#/eventstore" @click="setAdvanced">{{ t('pocket.activity.openLedger', 'Open the full ledger in Advanced mode →') }}</a>
    </div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import Icon from '@/components/Icon.vue'
import { rememberUiMode } from '@/services/uiMode'
import { apiClient } from '@/services/api/client'
import { useCurrency } from '@/composables/useCurrency'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { describeVerb } from '@/services/bridge/grammar'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useI18n } from '@/composables/useI18n'
import { liveOld } from '@/services/ledgerNames'

const { t, tp } = useI18n()
const ptrEl = ref<HTMLElement | null>(null)
const ptr = usePullToRefresh(ptrEl, () => { reload() })
const { amount } = (() => { try { const c = useCurrency(); return { amount: c.amount } } catch { return { amount: (v: any) => String(v ?? '0') } } })()

const loadErr = ref('')
const sampledWindow = ref(200)
// §POCKETBRIDGE5 W-G — per-agent scope
const { credAgents } = usePocketAgent()
const scopeDid = ref('')
const scopeErr = ref('')
const scopeComplete = ref(false)
const shownOf = ref<[number, number]>([0, 0])
function reload() { loadErr.value = ''; loading.value = true; rows.value = []; void boot() }

interface Row { id: string; label: string; when: string; ts: number; day: string; counter?: string; amount?: string; sign: string; kind: 'in' | 'out' | 'neutral'; icon: string; security?: boolean }
const rows = ref<Row[]>([])
const loading = ref(true)

function setAdvanced() { rememberUiMode('advanced') }
const shorten = (s: string | null) => !s ? '' : s.length > 24 ? s.slice(0, 12) + '…' + s.slice(-6) : s
const fmtTime = (d: Date) => d.toLocaleTimeString(appLocale(), { hour: '2-digit', minute: '2-digit' })
function dayLabel(d: Date): string {
  const today = new Date(); const yd = new Date(); yd.setDate(today.getDate() - 1)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, today)) return t('pocket.activity.today', 'Today')
  if (same(d, yd)) return t('pocket.activity.yesterday', 'Yesterday')
  return d.toLocaleDateString(appLocale(), { month: 'long', day: 'numeric' })
}

// Human labels for the event types agents actually produce.
// `label` is the English FALLBACK; `key` is what actually resolves. Resolved
// at map time (not module load) so a locale switch re-labels on the next read.
const TYPE_MAP: Record<string, { key: string; label: string; icon: string; kind: Row['kind']; security?: boolean }> = {
  TokensTransferred: { key: 'pocket.activity.typeTransfer', label: 'Transfer', icon: 'mdi:swap-horizontal', kind: 'neutral' },
  TokensIssued: { key: 'pocket.activity.typeIssued', label: 'Units issued', icon: 'mdi:arrow-down', kind: 'in' },
  TokensStaked: { key: 'pocket.activity.typeStaked', label: 'Locked', icon: 'mdi:lock', kind: 'neutral' },
  TransactionFeeCollected: { key: 'pocket.activity.typeFee', label: 'Network fee', icon: 'mdi:arrow-up', kind: 'out' },
  LedgerBalanceChanged: { key: 'pocket.activity.typeBalance', label: 'Balance change', icon: 'mdi:wallet', kind: 'neutral' },
  AgentCapabilityTokenIssued: { key: 'pocket.activity.typeCapIssued', label: 'Capability issued', icon: 'mdi:shield-key', kind: 'neutral', security: true },
  AgentCapabilityTokenRevoked: { key: 'pocket.activity.typeCapRevoked', label: 'Capability revoked', icon: 'mdi:shield-key', kind: 'neutral', security: true },
  GuildOrderPosted: { key: 'pocket.activity.typeGuildPosted', label: 'Guild task posted', icon: 'mdi:briefcase', kind: 'out' },
  GuildOrderSettled: { key: 'pocket.activity.typeGuildPaid', label: 'Guild task paid', icon: 'mdi:briefcase', kind: 'in' },
  GuildBidPlaced: { key: 'pocket.activity.typeGuildBid', label: 'Guild bid', icon: 'mdi:gavel', kind: 'neutral' },
}

function mapEvent(e: any): Row | null {
  const et = e.event_type || e.type || ''
  const data = e.data || {}
  // An unmapped type keeps its own de-camel-cased name (a machine fact we do
  // not translate); only the empty case gets a translated word.
  const m = TYPE_MAP[liveOld(et)] || { key: '', label: et.replace(/([a-z])([A-Z])/g, '$1 $2') || t('pocket.activity.event', 'Event'), icon: 'mdi:history', kind: 'neutral' as const }
  const ts = new Date(e.timestamp || e.created_at || Date.now())
  const amt = data.amount || data.payout || data.bounty || ''
  return {
    id: String(e.event_id || e.id || `${et}-${ts.getTime()}-${Math.random().toString(36).slice(2, 7)}`),
    label: data.message || data.attached_message || (m.key ? t(m.key, m.label) : m.label),
    when: fmtTime(ts), ts: ts.getTime(), day: dayLabel(ts),
    counter: shorten(data.receiver_did || data.receiver_agent_id || data.worker || data.bidder || e.aggregate_id),
    amount: amt ? String(amt) : undefined,
    sign: m.kind === 'in' ? '+' : m.kind === 'out' ? '−' : '',
    kind: m.kind, icon: m.icon, security: m.security,
  }
}

const groups = computed(() => {
  const by: Record<string, Row[]> = {}
  for (const r of rows.value) (by[r.day] ||= []).push(r)
  return Object.entries(by).map(([day, items]) => ({ day, items }))
})

/* ── #PK19 LIVE — mine-scoped verb sentences off the shared stream ── */
const stream = useLedgerStream()
const connected = computed(() => stream.anyConnected.value)
const liveSeen = computed(() => stream.totalEvents.value)
const mineApprox = computed(() => stream.droppedForRender.value > 0)
const liveMineSeen = ref(0)
const liveRows = ref<{ key: string; text: string; when: string }[]>([])
let liveSeq = 0
let offVerbs: (() => void) | null = null
onMounted(() => {
  offVerbs = stream.onVerbs((batch) => {
    const mine = batch.filter((v: any) => v.mine)
    if (!mine.length) return
    liveMineSeen.value += mine.length
    const when = fmtTime(new Date())
    const add = mine.map((v: any) => ({ key: `lv-${++liveSeq}`, text: describeVerb(v), when }))
    liveRows.value = [...add.reverse(), ...liveRows.value].slice(0, 20)
  })
})
onBeforeUnmount(() => { offVerbs?.() })

// §LEDGERGATE (V0601): only the newest read draws. The first read (the sampled window) is still on its way when a person
// picks one agent's own record, and the per-agent read is the faster one: the window answered last and put the whole
// fleet's rows under "this agent's own ledger record" (journal 51's photo drill: 78 rows of other agents for an agent
// whose record holds 6). A reply that is not the newest read's says nothing.
let bootSeq = 0
async function boot() {
  const seq = ++bootSeq
  try {
    // §POCKETBRIDGE5 W-G — two honest scopes:
    //  · default: the NEWEST 200-event frame window, server-filtered to your
    //    agents (the pre-fix window was the ledger's OLDEST 200 — the ES
    //    default order is ASC; measured live 2026-08-23 serving June rows as
    //    "recent").
    //  · agent_did: that ONE agent's own aggregate record, newest-first.
    const params: Record<string, any> = { limit: 200 }
    if (scopeDid.value) params.agent_did = scopeDid.value
    const { data } = await apiClient.get('/developers/me/activity', { params })
    if (seq !== bootSeq) return
    const events = data?.events || []
    scopeErr.value = data?.error || ''
    scopeComplete.value = data?.complete === true
    sampledWindow.value = Number(data?.sampled_window || 200)
    const mapped = events.map(mapEvent).filter(Boolean).sort((a: Row, b: Row) => b.ts - a.ts)
    shownOf.value = [mapped.length, Math.min(mapped.length, 60)]
    rows.value = mapped.slice(0, 60)
  } catch (e: any) {
    if (seq !== bootSeq) return
    const m = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
    // A refused per-agent scope (ownership, availability) is an answer about
    // the SCOPE, not an outage: say it at the scope control, not as a page
    // failure — and never leave another scope's rows captioned under it.
    if (scopeDid.value) { scopeErr.value = m; rows.value = []; shownOf.value = [0, 0] }
    else loadErr.value = m
  }
  finally { if (seq === bootSeq) loading.value = false }
}
onMounted(boot)
</script>

<style scoped>
.pv-wrap { max-width: 560px; margin: 0 auto; padding: 1rem; box-sizing: border-box; }
.pv-head { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.3rem; }
.pv-scope { font-size: 0.68rem; opacity: 0.5; margin: 0 0 0.8rem; }
/* §POCKETBRIDGE5 W-G — the scope picker (W2: 44px, 16px input) */
.pv-scope-sel { width: 100%; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); border-radius: 11px; padding: 0.55rem 0.7rem; min-height: 44px; color: inherit; font-size: 16px; margin: 0 0 0.5rem; }
.pv-scope-err { color: #fbbf24; opacity: 0.9; }
.pv-err p { color: #ff9a9a; }
.pv-retry { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.2); border-radius: 10px;
  color: inherit; padding: 0.5rem 1rem; min-height: 44px; cursor: pointer; margin-top: 0.4rem; }
.pv-title { font-size: 1.15rem; margin: 0; }
.pv-count { font-size: 0.72rem; font-weight: 700; color: var(--nc-primary, #00d4ff);
  background: rgba(0,212,255,0.09); border: 1px solid rgba(0,212,255,0.24); border-radius: 7px; padding: 0.12rem 0.45rem;
  font-variant-numeric: tabular-nums; }
.pv-day { margin-bottom: 0.9rem; }
.pv-day-label { font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.45; margin: 0 0 0.4rem 0.2rem; font-weight: 700; }
.pv-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }
.pv-row { display: flex; align-items: center; gap: 0.65rem; background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06); border-radius: 13px; padding: 0.65rem 0.75rem; min-height: 50px; }
.pv-sec { border-color: rgba(52,211,153,0.25); background: rgba(16,185,129,0.05); }
.pv-ico { width: 2.05rem; height: 2.05rem; border-radius: 11px; display: grid; place-items: center; flex: 0 0 auto; }
.pv-ico :deep(svg) { width: 1rem; height: 1rem; }
.pv-ico.in { background: rgba(16,185,129,0.12); color: #34d399; }
.pv-ico.out { background: rgba(255,107,107,0.1); color: #ff8a8a; }
.pv-ico.neutral { background: rgba(0,212,255,0.09); color: var(--nc-primary, #00d4ff); }
.pv-ico.sec { background: rgba(16,185,129,0.15); color: #34d399; }
.pv-body { flex: 1 1 auto; min-width: 0; }
.pv-label { font-size: 0.85rem; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pv-sub { font-size: 0.68rem; opacity: 0.5; font-variant-numeric: tabular-nums; }
.pv-amt { font-variant-numeric: tabular-nums; font-weight: 650; font-size: 0.86rem; flex: 0 0 auto; }
.pv-amt.in { color: #34d399; } .pv-amt.out { color: #ff8a8a; } .pv-amt.neutral { opacity: 0.85; }
.pv-empty { display: flex; flex-direction: column; align-items: center; gap: 0.7rem; padding: 3rem 1rem 2rem; text-align: center; }
.pv-empty-ring { width: 3.4rem; height: 3.4rem; border-radius: 50%; display: grid; place-items: center;
  background: rgba(0,212,255,0.06); border: 1px solid rgba(0,212,255,0.18); color: var(--nc-primary, #00d4ff); }
.pv-empty-ring :deep(svg) { width: 1.5rem; height: 1.5rem; }
.pv-empty p { margin: 0; font-size: 0.86rem; opacity: 0.75; max-width: 22rem; line-height: 1.45; }
.pv-empty strong { display: block; font-size: 0.95rem; margin-bottom: 0.15rem; opacity: 1; }
.pv-adv { font-size: 0.78rem; color: var(--nc-primary, #00d4ff); text-decoration: none; }
.pv-live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: rgba(255,255,255,0.25); margin-right: 0.35rem; vertical-align: 1px; }
.pv-live-dot.on { background: #34d399; box-shadow: 0 0 8px rgba(52,211,153,0.6); }
.pv-row-live { border-left: 3px solid rgba(0,212,255,0.35); }
.pv-live-note { font-size: 0.68rem; opacity: 0.5; margin: 0.4rem 0 0 0.2rem; font-variant-numeric: tabular-nums; }
.pv-skel { height: 3.1rem; border-radius: 13px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.11), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pv-shim 1.3s ease-in-out infinite; }
@keyframes pv-shim { to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .pv-skel { animation: none; } }
</style>
