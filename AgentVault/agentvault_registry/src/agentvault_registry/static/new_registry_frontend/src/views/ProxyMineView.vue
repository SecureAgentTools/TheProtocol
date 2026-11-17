<!--
  V0664 C3 (order gwo_4110e12c11a69a93de878829) — My proxies. Signed in: the developer's agents whose proxy reports its status (C2,
  opt-in: `service: {report_every_s: N}` in the spec), each with the age of its last report, its mappings' counts (pending, done,
  dead, paused, a breaker's state) and its sources, and on request the agent's recent ledger rows. A report holds names and counts
  only; nothing here can show a record or a config value. Reads: GET /developers/me/proxy-status, GET /teg/transactions/history/{did}.
-->
<template>
  <div class="pm" data-testid="pm-root">
    <ProxyTabs current="proxy-mine" />
    <header class="pm-head">
      <h1>{{ t('proxy.mine.title', 'My proxies') }}</h1>
      <p>{{ t('proxy.mine.subtitle', 'The proxies of your agents that report their status: how long since each spoke, what is waiting, what was sent, what will not be sent again.') }}</p>
    </header>

    <p v-if="state === 'loading'" class="pm-note" data-testid="pm-loading">{{ t('proxy.mine.loading', 'Reading your proxies\' last reports') }}</p>
    <p v-else-if="state === 'failed'" class="pm-error" role="alert" data-testid="pm-failed">{{ error }}</p>
    <div v-else-if="state === 'none'" class="pm-none" data-testid="pm-none">
      <p>{{ t('proxy.mine.none', 'None of your agents reports a proxy status yet.') }}</p>
      <p class="pm-fine">{{ t('proxy.mine.howTo', 'A proxy reports when its spec asks it to: add a service block with report_every_s (tp-proxy init writes 300 seconds). It posts names and counts only, as its own agent.') }}</p>
      <pre class="pm-code" tabindex="0" role="region" :aria-label="t('proxy.mine.serviceAria', 'The service block to add')">service:
  report_every_s: 300</pre>
    </div>

    <p v-if="state === 'filled' && needing" class="pm-need" data-testid="pm-need">{{ needing === 1 && proxies.length === 1 ? t('proxy.mine.needOneOfOne', '1 of 1 needs you') : needing === 1 ? tp('proxy.mine.needOne', '1 of {m} needs you', { m: proxies.length }) : tp('proxy.mine.needMany', '{n} of {m} need you', { n: needing, m: proxies.length }) }}</p>
    <ul v-if="state === 'filled'" class="pm-legend" data-testid="pm-legend" :aria-label="t('proxy.mine.legendAria', 'What the chips mean')">
      <li v-for="f in FRESHNESS" :key="f" :data-testid="`pm-legend-${f}`"><span class="pm-fresh" :class="'f-' + f">{{ freshName(f) }}</span><span>{{ freshMeans(f) }}</span></li>
    </ul>
    <ul v-if="state === 'filled'" class="pm-list" data-testid="pm-list">
      <li v-for="p in ordered" :key="p.did" class="pm-card" :data-testid="`pm-proxy-${p.name}`">
        <header class="pm-card-head">
          <div class="pm-id">
            <h2>{{ p.name }}</h2>
            <div class="pm-did-row">
              <code class="pm-did" :title="p.did">{{ didTail(p.did) }}</code>
              <button type="button" class="pm-copy" :aria-label="t('proxy.mine.copyDidAria', 'Copy the agent\'s whole DID')" :data-testid="`pm-did-copy-${p.name}`" @click="copyDid(p.did)">{{ copiedDid === p.did ? t('proxy.mine.copied', 'Copied') : t('proxy.mine.copyDid', 'Copy DID') }}</button>
            </div>
          </div>
          <span class="pm-fresh" :class="'f-' + freshness(p.ageS)" :title="freshMeans(freshness(p.ageS))" :data-testid="`pm-fresh-${p.name}`">{{ freshWord(p.ageS) }}</span>
        </header>

        <dl class="pm-facts">
          <div><dt>{{ t('proxy.mine.reported', 'Last report') }}</dt><dd>{{ tp('proxy.mine.ago', '{age} ago', { age: ageWords(p.ageS) }) }}</dd></div>
          <div><dt>{{ t('proxy.mine.uptime', 'Running for') }}</dt><dd>{{ ageWords(p.uptimeS) }}</dd></div>
          <div><dt>{{ t('proxy.mine.sdk', 'SDK') }}</dt><dd>{{ p.sdkVersion || '—' }}</dd></div>
        </dl>

        <ul class="pm-totals" :aria-label="t('proxy.mine.totalsAria', 'All mappings together')">
          <li><strong>{{ num(p.totals.pending) }}</strong><span>{{ t('proxy.mine.pending', 'waiting') }}</span></li>
          <li><strong>{{ num(p.totals.done) }}</strong><span>{{ t('proxy.mine.done', 'sent') }}</span></li>
          <li :class="{ bad: p.totals.dead > 0 }"><strong>{{ num(p.totals.dead) }}</strong><span>{{ t('proxy.mine.dead', 'given up') }}</span></li>
        </ul>

        <ul v-if="attentionGroups(p).length" class="pm-attn" :data-testid="`pm-attn-${p.name}`">
          <li v-for="g in attentionGroups(p)" :key="g.mapping ?? '-'"><code v-if="g.mapping">{{ g.mapping }}</code><span>{{ g.facts.map(factWords).join('; ') }}</span></li>
        </ul>

        <ul v-if="p.mappings.length" class="pm-maps" :aria-label="t('proxy.mine.mappingsCaption', 'Mappings')">
          <li v-for="m in p.mappings" :key="m.name" class="pm-map" :data-testid="`pm-map-${p.name}-${m.name}`">
            <div class="pm-map-head"><code>{{ m.name }}</code><span class="pm-map-state" :class="{ warn: m.paused || !!m.breaker }">{{ mappingState(m) }}</span></div>
            <div class="pm-map-nums">
              <span>{{ tp('proxy.mine.nWaiting', '{n} waiting', { n: num(m.pending) }) }}</span>
              <span>{{ tp('proxy.mine.nSent', '{n} sent', { n: num(m.done) }) }}</span>
              <span :class="{ bad: m.dead > 0 }">{{ tp('proxy.mine.nDead', '{n} given up', { n: num(m.dead) }) }}</span>
            </div>
          </li>
        </ul>

        <ul v-if="p.sources.length" class="pm-sources" :aria-label="t('proxy.mine.sourcesAria', 'Sources')">
          <li v-for="s in p.sources" :key="s.name" :data-testid="`pm-source-${p.name}-${s.name}`">
            <code>{{ s.name }}</code>
            <template v-if="s.finished">{{ t('proxy.mine.finished', 'finished') }}</template>
            <template v-else-if="s.lastReadAt">{{ t('proxy.mine.lastReadWord', 'last read') }} <time :datetime="s.lastReadAt" :title="s.lastReadAt">{{ agoOf(s.lastReadAt) }}</time></template>
            <template v-else>{{ t('proxy.mine.notRead', 'not read yet') }}</template>
          </li>
        </ul>

        <div class="pm-ledger">
          <button type="button" class="pm-btn" :aria-expanded="!!open[p.did]" :data-testid="`pm-ledger-${p.name}`" @click="toggleLedger(p.did)">
            {{ open[p.did] ? t('proxy.mine.ledgerHide', 'Hide its recent ledger') : t('proxy.mine.ledgerShow', 'Its recent ledger') }}
          </button>
          <template v-if="open[p.did]">
            <p v-if="ledger[p.did]?.state === 'loading'" class="pm-note">{{ t('proxy.mine.ledgerLoading', 'Reading the ledger') }}</p>
            <p v-else-if="ledger[p.did]?.state === 'failed'" class="pm-error" role="alert">{{ ledger[p.did]?.error }}</p>
            <p v-else-if="ledger[p.did]?.state === 'none'" class="pm-note">{{ t('proxy.mine.ledgerNone', 'Nothing has moved on this agent\'s ledger yet. Attestations are on its record, not its ledger.') }}</p>
            <ul v-else class="pm-rows" :data-testid="`pm-ledger-rows-${p.name}`">
              <li v-for="r in ledger[p.did]?.rows || []" :key="r.id"><span class="pm-row-type" :title="r.type">{{ kindWord(r.type) }}</span><span class="pm-row-amt">{{ formatAmount(r.amount, appLocale()) }}</span><time :datetime="r.at" :title="r.at">{{ agoOf(r.at) }}</time></li>
            </ul>
          </template>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import ProxyTabs from '@/components/proxy/ProxyTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { agentLedger, myProxies } from '@/services/api/proxyStatus'
import { attention, attentionGroups, formatAmount, needsFirst, freshness, ledgerKind, secondsSince, didTail, type Attention, type Freshness, type LedgerRow, type MappingStatus, type ProxyRow } from '@/services/proxy/mine'
import { appLocale } from '@/services/appLocale'

const { t, tp } = useI18n()
const state = ref<'loading' | 'failed' | 'none' | 'filled'>('loading')
const error = ref('')
const proxies = ref<ProxyRow[]>([])
// the ones that need their owner first (pass 4), and how many they are
const ordered = computed(() => needsFirst(proxies.value))
const needing = computed(() => proxies.value.filter((p) => attention(p).length).length)
const open = reactive<Record<string, boolean>>({})
const ledger = reactive<Record<string, { state: 'loading' | 'failed' | 'none' | 'filled'; rows: LedgerRow[]; error: string }>>({})

const num = (n: number) => n.toLocaleString(appLocale())

function ageWords(s: number): string {
  if (s < 90) return tp('proxy.mine.seconds', '{n} s', { n: s })
  if (s < 5400) return tp('proxy.mine.minutes', '{n} min', { n: Math.round(s / 60) })
  if (s < 172800) return tp('proxy.mine.hours', '{n} h', { n: Math.round(s / 3600) })
  return tp('proxy.mine.days', '{n} days', { n: Math.round(s / 86400) })
}
const FRESHNESS: Freshness[] = ['fresh', 'quiet', 'silent']
function freshName(f: Freshness): string {
  return f === 'fresh' ? t('proxy.mine.fresh', 'Reporting') : f === 'quiet' ? t('proxy.mine.quiet', 'Quiet') : t('proxy.mine.silent', 'Silent')
}
const freshWord = (s: number): string => freshName(freshness(s))
/** What a chip means, said the way services/proxy/mine.freshness decides it (tp-proxy init writes report_every_s 300). */
function freshMeans(f: Freshness): string {
  if (f === 'fresh') return t('proxy.mine.freshMeans', 'A report within the last 10 minutes')
  if (f === 'quiet') return t('proxy.mine.quietMeans', 'The last report 10 to 60 minutes ago')
  return t('proxy.mine.silentMeans', 'No report for over an hour')
}
function mappingState(m: MappingStatus): string {
  if (m.breaker) return tp('proxy.mine.breakerState', 'breaker {state}', { state: m.breaker })
  if (m.paused) return t('proxy.mine.paused', 'paused')
  return t('proxy.mine.running', 'running')
}
/** A time as a time ago (the exact time stays in the element's title); a time it cannot read is shown as it came. */
function agoOf(iso: string): string {
  const s = secondsSince(iso, Date.now())
  return s === null ? iso : tp('proxy.mine.ago', '{age} ago', { age: ageWords(s) })
}
/** One fact about a mapping, without its name (the line names it once). */
function factWords(a: Attention): string {
  if (a.kind === 'dead') {
    return a.count === 1
      ? t('proxy.mine.attnDeadOne', '1 record given up: it will not be sent again without you')
      : tp('proxy.mine.attnDeadMany', '{n} records given up: they will not be sent again without you', { n: num(a.count) })
  }
  if (a.kind === 'paused') return t('proxy.mine.paused', 'paused')
  if (a.kind === 'breaker') return tp('proxy.mine.breakerState', 'breaker {state}', { state: a.state })
  return t('proxy.mine.attnSilent', 'No report for over an hour: the proxy may have stopped')
}
function kindWord(type: string): string {
  const k = ledgerKind(type)
  return k === 'transfer' ? t('proxy.mine.kTransfer', 'Transfer') : k === 'fee' ? t('proxy.mine.kFee', 'Fee')
    : k === 'issued' ? t('proxy.mine.kIssued', 'Issued') : type
}
const copiedDid = ref('')
async function copyDid(did: string) {
  try { await navigator.clipboard.writeText(did); copiedDid.value = did; setTimeout(() => { if (copiedDid.value === did) copiedDid.value = '' }, 1600) }
  catch { copiedDid.value = '' }
}

function why(e: any, fallback: string): string {
  if (e?.response?.status === 404) return t('proxy.mine.noRoute', 'This registry does not keep proxy reports yet.')
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || fallback
}

async function load() {
  state.value = 'loading'
  try {
    proxies.value = await myProxies()
    state.value = proxies.value.length ? 'filled' : 'none'
  } catch (e) {
    error.value = why(e, t('proxy.mine.failed', 'Your proxies\' reports could not be read.'))
    state.value = 'failed'
  }
}

async function toggleLedger(did: string) {
  open[did] = !open[did]
  if (!open[did] || ledger[did]?.state === 'filled' || ledger[did]?.state === 'none') return
  ledger[did] = { state: 'loading', rows: [], error: '' }
  try {
    const rows = await agentLedger(did)
    ledger[did] = { state: rows.length ? 'filled' : 'none', rows, error: '' }
  } catch (e) {
    ledger[did] = { state: 'failed', rows: [], error: why(e, t('proxy.mine.ledgerFailed', 'The ledger could not be read.')) }
  }
}

onMounted(load)
</script>

<style scoped>
.pm { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: #e8eaed; display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.pm-head h1 { margin: 0; font-size: 1.6rem; font-weight: 300; }
.pm-head p { margin: 0.3rem 0 0; font-size: 0.88rem; color: var(--muted); max-width: 46rem; line-height: 1.55; }
.pm-note { margin: 0; font-size: 0.85rem; color: var(--muted); }
.pm-error { margin: 0; color: #fca5a5; font-size: 0.85rem; }
.pm-none { display: grid; gap: 0.5rem; max-width: 40rem; }
.pm-none p { margin: 0; }
.pm-fine { margin: 0; font-size: 0.78rem; color: var(--muted); line-height: 1.5; }
.pm-code { margin: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: 0.7rem 0.9rem; font: 0.78rem/1.6 var(--mono); white-space: pre; }
.pm-code:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.pm-list { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr)); gap: 0.8rem; }
.pm-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1rem 1.1rem; display: grid; gap: 0.7rem; align-content: start; min-width: 0; }
.pm-card-head { display: flex; justify-content: space-between; gap: 0.6rem; align-items: start; }
.pm-id { min-width: 0; display: grid; gap: 0.2rem; }
.pm-id h2 { margin: 0; font-size: 1rem; font-weight: 500; overflow-wrap: anywhere; }
.pm-need { margin: 0; font: 600 .78rem var(--mono); color: #fbbf24; }
.pm-legend { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 0.4rem 1.2rem; font-size: 0.74rem; color: var(--muted); }
.pm-legend li { display: inline-flex; align-items: center; gap: 0.45rem; }
.pm-legend li > span:last-child { line-height: 1.4; }
.pm-did-row { display: flex; align-items: center; gap: 0.5rem; min-width: 0; }
.pm-did { font: .7rem var(--mono); color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; min-width: 0; }
.pm-copy { flex: none; min-height: 32px; padding: 0 .55rem; border-radius: 6px; border: 1px solid rgba(var(--cyan-rgb), .2); background: transparent; color: #cbd5e1; font: 600 .64rem var(--mono); cursor: pointer; }
.pm-copy:hover { border-color: rgba(var(--cyan-rgb), .5); color: var(--cyan); }
.pm-copy:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.pm-fresh { flex: none; font: 700 .66rem/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; padding: 5px 8px; border-radius: 999px; border: 1px solid; }
.f-fresh { color: #34d399; border-color: rgba(52,211,153,.4); }
.f-quiet { color: #fbbf24; border-color: rgba(251,191,36,.4); }
.f-silent { color: #fca5a5; border-color: rgba(252,165,165,.4); }
.pm-facts { margin: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.5rem; font-size: 0.78rem; }
.pm-facts dt { color: var(--muted); font-size: .7rem; }
.pm-facts dd { margin: 0.15rem 0 0; }
.pm-totals { list-style: none; margin: 0; padding: 0.6rem 0 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid rgba(255,255,255,.06); }
.pm-totals li { display: grid; gap: 0.1rem; }
.pm-totals strong { font: 300 1.35rem/1.1 'IBM Plex Sans', sans-serif; font-variant-numeric: tabular-nums; }
.pm-totals span { font-size: .72rem; color: var(--muted); }
.bad, .pm-totals li.bad strong { color: #fca5a5; }
.pm-attn { margin: 0; padding: 0.55rem 0.7rem; list-style: none; font-size: 0.8rem; color: #fbbf24; display: grid; gap: 0.35rem; border-left: 2px solid rgba(251,191,36,.5); background: rgba(251,191,36,.05); border-radius: 0 6px 6px 0; line-height: 1.45; }
.pm-attn code { font: 600 .74rem var(--mono); color: #fde68a; margin-right: 0.4rem; overflow-wrap: anywhere; }
.pm-maps { list-style: none; margin: 0; padding: 0; display: grid; border-top: 1px solid rgba(255,255,255,.06); }
.pm-map { display: grid; gap: 0.2rem; padding: 0.5rem 0; border-bottom: 1px solid rgba(255,255,255,.06); min-width: 0; }
.pm-map-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.6rem; }
.pm-map-head code { font: .76rem var(--mono); color: #e8eaed; overflow-wrap: anywhere; min-width: 0; }
.pm-map-state { flex: none; font: 600 .64rem var(--mono); letter-spacing: .05em; text-transform: uppercase; color: var(--muted); }
.pm-map-state.warn { color: #fbbf24; }
.pm-map-nums { display: flex; flex-wrap: wrap; gap: 0.2rem 0.9rem; font-size: 0.76rem; color: #aab4c0; font-variant-numeric: tabular-nums; }
.pm-sources { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.2rem; font-size: 0.76rem; color: var(--muted); }
.pm-sources code { font: .72rem var(--mono); color: #cbd5e1; margin-right: 0.35rem; }
.pm-sources time { color: #cbd5e1; }
.pm-btn { min-height: 40px; padding: 0 0.9rem; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .3); background: transparent; color: var(--cyan); font: 600 .76rem var(--mono); cursor: pointer; }
.pm-btn:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
.pm-ledger { display: grid; gap: 0.5rem; }
.pm-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.25rem; font-size: 0.76rem; }
.pm-rows li { display: grid; grid-template-columns: minmax(0, 1fr) auto 5.5rem; gap: 0.6rem; align-items: baseline; }
.pm-row-type { color: #cbd5e1; overflow-wrap: anywhere; }
.pm-row-amt { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; color: #e8eaed; }
.pm-rows time { color: var(--muted); font-family: var(--mono); text-align: right; }
.pm-rows time { color: var(--muted); font-family: var(--mono); }
@media (max-width: 720px) { .pm { padding: 1rem .8rem 2.5rem; } .pm-list { grid-template-columns: 1fr; } }
</style>
