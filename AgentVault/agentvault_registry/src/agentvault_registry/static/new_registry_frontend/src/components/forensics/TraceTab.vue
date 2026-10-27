<template>
  <div class="lft">
    <!-- Search -->
    <div class="lft-search">
      <select v-model="mode" class="lft-mode" title="trace mode">
        <option value="txid">by transaction_id</option>
        <option value="aggregate">by aggregate_id</option>
      </select>
      <input
        v-model="anchor"
        class="lft-input"
        :placeholder="mode === 'txid' ? 'transaction_id — full cross-leg money path (xfer / fee / settle / refund …)' : 'aggregate_id — agent DID or ledger key (e.g. ledger-tx-teg-layer-a-41367402)'"
        @keyup.enter="run"
      />
      <span class="lft-frame-pill">{{ frameLabel }}</span>
      <button class="lft-btn" @click="run" :disabled="store.loadingTrace || !anchor.trim()">
        <Icon name="mdi:map-marker-path" class="lft-btn-ico" /> {{ store.loadingTrace ? 'Tracing…' : 'Trace' }}
      </button>
    </div>
    <div class="lft-hint">
      Reconstructs the money path from EventStore events. <b>by transaction_id</b> stitches every leg of a
      transfer / order / saga (xfer · fee · settle · refund · reverse) via the backend trace proxy.
      <span class="lft-hint-blocked">The cross-DB “is the money home?” verdict (registry + TEG row status, both frames) is the next layer.</span>
    </div>

    <!-- Empty / initial -->
    <div v-if="!store.traceAnchor && !store.loadingTrace" class="lft-blank">
      <Icon name="mdi:crosshairs-gps" class="lft-blank-ico" />
      <div>Enter an aggregate id above to reconstruct its event timeline.</div>
      <div class="lft-blank-ex">
        Try a ledger key from the Stuck Funds findings, an agent DID, or a system account like
        <code>teg:system:exchange_escrow</code>.
      </div>
    </div>

    <!-- Results -->
    <div v-else-if="store.traceEvents.length">
      <div class="lft-summary">
        <div class="lft-sum-item"><span class="lft-sum-k">Events</span><span class="lft-sum-v">{{ store.traceEvents.length }}</span></div>
        <div class="lft-sum-item"><span class="lft-sum-k">Span</span><span class="lft-sum-v">{{ span }}</span></div>
        <div class="lft-sum-item"><span class="lft-sum-k">Types</span><span class="lft-sum-v">{{ Object.keys(typeBreakdown).length }}</span></div>
        <span class="lft-spacer"></span>
        <div class="lft-typechips">
          <span v-for="(n, t) in typeBreakdown" :key="t" class="lft-typechip">{{ t }} <b>{{ n }}</b></span>
        </div>
      </div>

      <!-- §FEDEVENTS: aggregate chains are windowed (~30d hops) so million-event
           aggregates stay responsive — step through history explicitly. -->
      <div v-if="store.traceMode === 'aggregate' && store.traceWindow" class="lft-window">
        <span class="lft-window-lbl" title="Aggregate chains are fetched in bounded ~30-day windows — step older / newer to walk the full history.">window {{ windowLabel }}</span>
        <button class="lft-win-btn" :disabled="store.loadingTrace" @click="step('older')">‹ older</button>
        <button class="lft-win-btn" :disabled="store.loadingTrace || !store.traceWindowEnd" @click="step('newer')">newer ›</button>
        <button v-if="store.traceWindowEnd" class="lft-win-btn" :disabled="store.loadingTrace" @click="step('latest')">latest</button>
        <span v-if="store.traceWalked" class="lft-win-note">⇤ jumped to latest activity</span>
        <span v-if="store.traceTruncated" class="lft-win-note lft-win-note--warn">window capped at 10k rows</span>
      </div>

      <div class="lft-timeline">
        <div v-for="(ev, i) in store.traceEvents" :key="ev.id || i" class="lft-event">
          <div class="lft-ev-time">
            <div class="lft-ev-hms">{{ hms(ev.timestamp) }}</div>
            <div class="lft-ev-date">{{ ymd(ev.timestamp) }}</div>
          </div>
          <div class="lft-ev-body">
            <div class="lft-ev-head" @click="toggle(i)">
              <span class="lft-ev-type" :class="typePillClass(ev.event_type)">{{ ev.event_type }}</span>
              <span v-if="ledgerKind(ev)" class="lft-kind" :class="kindClass(ledgerKind(ev))">{{ ledgerKind(ev) }}</span>
              <span v-if="ev.source_service" class="lft-ev-src">{{ ev.source_service }}</span>
              <span class="lft-spacer"></span>
              <span v-if="ev.idempotency_key" class="lft-idem" :title="ev.idempotency_key">{{ ev.idempotency_key }}</span>
              <Icon :name="expanded.has(i) ? 'arrow-down' : 'chevron-right'" class="lft-ev-caret" />
            </div>

            <!-- Money entries for LedgerBalanceChanged -->
            <div v-if="entriesOf(ev).length" class="lft-entries">
              <div v-for="(en, j) in entriesOf(ev)" :key="j" class="lft-entry">
                <span class="lft-acct">{{ shortDid(en.agent_did) }}</span>
                <span class="lft-delta" :class="num(en.delta_liquid) < 0 ? 'lft-neg' : num(en.delta_liquid) > 0 ? 'lft-pos' : 'lft-zero'">
                  liquid {{ signed(en.delta_liquid) }}
                </span>
                <span v-if="num(en.delta_staked) !== 0" class="lft-delta" :class="num(en.delta_staked) < 0 ? 'lft-neg' : 'lft-pos'">
                  locked {{ signed(en.delta_staked) }}
                </span>
              </div>
              <div v-if="ev.data && ev.data.net != null" class="lft-net">net {{ signed(ev.data.net) }}</div>
            </div>
            <!-- Generic money summary for non-ledger events -->
            <div v-else-if="genericSummary(ev)" class="lft-generic">{{ genericSummary(ev) }}</div>

            <!-- Raw payload -->
            <div v-if="expanded.has(i)" class="lft-json">
              <JsonViewer :data="ev" label="event" :default-collapsed="false" dense max-height="280px" />
            </div>
          </div>
        </div>
      </div>
    </div>

    <ReadFailedNotice v-else-if="store.traceFailed && !store.loadingTrace" :retry="retryTrace" data-testid="lft-unread" />
    <div v-else-if="store.traceAnchor && !store.loadingTrace" class="lft-blank">
      <Icon name="mdi:magnify" class="lft-blank-ico" />
      <div>
        No events for <code>{{ store.traceAnchor }}</code> on {{ frameLabel }}<template
          v-if="store.traceMode === 'aggregate' && store.traceWindow"> in window {{ windowLabel }}</template>.
      </div>
      <div v-if="store.traceMode === 'aggregate' && store.traceWindow" class="lft-blank-ex">
        Aggregate chains are searched in bounded ~30-day windows.
        <button class="lft-win-btn" :disabled="store.loadingTrace" @click="step('older')">‹ search older</button>
      </div>
      <div v-else class="lft-blank-ex">
        Note: aggregate mode queries by exact <code>aggregate_id</code>; txid mode stitches every leg
        sharing <code>data.transaction_id</code>.
      </div>
    </div>

    <div v-if="store.error" class="lft-error">{{ store.error }}</div>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import Icon from '@/components/Icon.vue'
import JsonViewer from '@/components/common/JsonViewer.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useForensicsStore } from '@/stores/forensics'
import { useAdminFrames } from '@/composables/useAdminFrames'
import type { EventStoreEvent, FrameId } from '@/services/api/eventStoreAdmin'

const props = defineProps<{ frame: FrameId }>()
const store = useForensicsStore()
const { resolveOption } = useAdminFrames()

const anchor = ref(store.traceAnchor || '')
const mode = ref<'txid' | 'aggregate'>('txid')
const expanded = ref<Set<number>>(new Set())

const frameLabel = computed(() => resolveOption(props.frame).label)
const windowLabel = computed(() => {
  const w = store.traceWindow
  if (!w) return ''
  const f = (iso: string) => dayjs(iso).format('MMM D')
  return `${f(w.start)} → ${f(w.end)}`
})

function run() {
  expanded.value = new Set()
  if (mode.value === 'txid') store.loadTraceTxid(anchor.value, props.frame)
  else store.loadTrace(anchor.value, props.frame)
}
// the trace that failed, again (its anchor and mode, whatever the box holds now)
function retryTrace() {
  if (store.traceMode === 'txid') return store.loadTraceTxid(store.traceAnchor, props.frame)
  return store.loadTrace(store.traceAnchor, props.frame, { keepWindow: true })
}
function step(direction: 'older' | 'newer' | 'latest') {
  expanded.value = new Set()
  void store.traceStep(direction, props.frame)
}
function toggle(i: number) {
  const next = new Set(expanded.value)
  next.has(i) ? next.delete(i) : next.add(i)
  expanded.value = next
}

const typeBreakdown = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {}
  for (const e of store.traceEvents) out[e.event_type] = (out[e.event_type] || 0) + 1
  return out
})

const span = computed(() => {
  const ev = store.traceEvents
  if (!ev.length) return '—'
  const ts = ev.map(e => e.timestamp).filter(Boolean).sort()
  if (!ts.length) return '—'
  if (ts.length === 1) return ymd(ts[0]) + ' ' + hms(ts[0])
  return `${dayjs(ts[0]).format('MMM D HH:mm')} → ${dayjs(ts[ts.length - 1]).format('MMM D HH:mm')}`
})

// ── helpers ──────────────────────────────────────────────────────────────
function num(v: any): number {
  if (v == null) return 0
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return isNaN(n) ? 0 : n
}
function signed(v: any): string {
  const n = num(v)
  const s = n.toLocaleString(appLocale(), { maximumFractionDigits: 6 })
  return n > 0 ? `+${s}` : s
}
function shortDid(s?: string): string {
  if (!s) return '—'
  if (s.length <= 30) return s
  return s.slice(0, 22) + '…' + s.slice(-6)
}
function hms(ts?: string): string { return ts ? dayjs(ts).format('HH:mm:ss') : '—' }
function ymd(ts?: string): string { return ts ? dayjs(ts).format('MMM D') : '' }

function entriesOf(ev: EventStoreEvent): Array<{ agent_did?: string; delta_liquid?: any; delta_staked?: any }> {
  const e = ev?.data?.entries
  return Array.isArray(e) ? e : []
}
function ledgerKind(ev: EventStoreEvent): string | null {
  return ev?.data?.kind ?? null
}
function genericSummary(ev: EventStoreEvent): string {
  const d = ev?.data || {}
  const bits: string[] = []
  if (d.amount != null) bits.push(`amount ${signed(d.amount)}`)
  if (d.fee_amount != null) bits.push(`fee ${num(d.fee_amount)}`)
  if (d.from_did || d.from) bits.push(`from ${shortDid(d.from_did || d.from)}`)
  if (d.to_did || d.to) bits.push(`to ${shortDid(d.to_did || d.to)}`)
  if (d.transaction_id) bits.push(`tx ${String(d.transaction_id).slice(0, 12)}`)
  return bits.join('  ·  ')
}

function typePillClass(t: string): string {
  if (/Refund|Reversed|Slash|Breach|Failed|DeadLetter/i.test(t)) return 'lft-t--bad'
  if (/Transferred|Settled|Issued|Minted|Credited/i.test(t)) return 'lft-t--money'
  if (/Fee/i.test(t)) return 'lft-t--fee'
  if (/Exchange|Fx|Order|Trade/i.test(t)) return 'lft-t--exch'
  return 'lft-t--other'
}
function kindClass(k: string | null): string {
  if (!k) return ''
  if (/^(mint|dispute_comp)$/.test(k)) return 'lft-k--mint'
  if (/^(slash|burn)$/.test(k)) return 'lft-k--burn'
  if (/refund|reverse|compensate/i.test(k)) return 'lft-k--refund'
  if (/unknown|mixed/i.test(k)) return 'lft-k--unknown'
  return 'lft-k--transit'
}

onMounted(() => {
  mode.value = store.traceMode
  if (store.traceAnchor && !store.traceEvents.length && !store.loadingTrace) {
    if (store.traceMode === 'txid') store.loadTraceTxid(store.traceAnchor, props.frame)
    else store.loadTrace(store.traceAnchor, props.frame)
  }
})
</script>

<style scoped>
.lft {
  --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366; --green: #00ff88; --amber: #ff9500; --muted: #6b7785;
  --border: rgba(var(--cyan-rgb), 0.18); --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed; color: var(--text-bright);
}
.lft-search { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.lft-input {
  flex: 1; min-width: 320px; background: rgba(0,0,0,0.35); color: var(--text-bright);
  border: 1px solid var(--border); border-radius: 4px; padding: 8px 12px; font-size: 12px; font-family: var(--mono);
}
.lft-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }
.lft-frame-pill { font-size: 10px; font-weight: 700; color: var(--muted); border: 1px solid var(--border); border-radius: 8px; padding: 4px 10px; }
.lft-mode { background: rgba(0,0,0,0.35); color: var(--text-bright); border: 1px solid var(--border); border-radius: 4px; padding: 8px 10px; font-size: 12px; font-family: var(--mono); }
.lft-mode:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }
.lft-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(var(--cyan-rgb), 0.12); color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 4px; padding: 8px 16px; font-size: 12px; cursor: pointer; font-weight: 600;
}
.lft-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); }
.lft-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.lft-btn-ico { width: 15px; height: 15px; }
.lft-hint { font-size: 11.5px; color: var(--muted); margin: 8px 2px 16px; line-height: 1.5; }
.lft-hint code { background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px; font-family: var(--mono); }
.lft-hint-blocked { display: block; margin-top: 3px; opacity: 0.8; font-style: italic; }

.lft-blank {
  text-align: center; padding: 44px 20px; color: var(--muted);
  border: 1px dashed var(--border); border-radius: 8px; display: flex; flex-direction: column; gap: 8px; align-items: center;
}
.lft-blank-ico { width: 30px; height: 30px; opacity: 0.5; }
.lft-blank-ex { font-size: 11.5px; max-width: 520px; line-height: 1.5; }
.lft-blank code { background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px; font-family: var(--mono); }

.lft-summary {
  display: flex; gap: 18px; align-items: center; flex-wrap: wrap;
  padding: 10px 14px; background: rgba(var(--cyan-rgb), 0.04); border: 1px solid var(--border);
  border-radius: 8px; margin-bottom: 12px;
}
.lft-sum-item { display: flex; flex-direction: column; }
.lft-sum-k { font-size: 9px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); font-weight: 700; }
.lft-sum-v { font-size: 16px; font-weight: 800; font-family: var(--mono); }
.lft-spacer { flex: 1; }
.lft-typechips { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
.lft-typechip { font-size: 10px; color: var(--muted); font-family: var(--mono); background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 8px; padding: 2px 8px; }
.lft-typechip b { color: #c8d8e8; }

.lft-timeline { display: flex; flex-direction: column; }
.lft-event { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.06); }
.lft-ev-time { width: 70px; flex-shrink: 0; text-align: right; }
.lft-ev-hms { font-family: var(--mono); font-size: 12px; color: #c8d8e8; }
.lft-ev-date { font-size: 10px; color: var(--muted); }
.lft-ev-body { flex: 1; min-width: 0; }
.lft-ev-head { display: flex; align-items: center; gap: 8px; cursor: pointer; flex-wrap: wrap; }
.lft-ev-type { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; font-family: var(--mono); }
.lft-t--money { background: rgba(0,255,136,0.14); color: var(--green); }
.lft-t--bad { background: rgba(255,51,102,0.18); color: #ff6b8a; }
.lft-t--fee { background: rgba(255,149,0,0.16); color: var(--amber); }
.lft-t--exch { background: rgba(154,214,255,0.14); color: #9ad6ff; }
.lft-t--other { background: rgba(255,255,255,0.05); color: #b0c0d0; }
.lft-kind { font-size: 9.5px; font-weight: 700; padding: 2px 7px; border-radius: 6px; font-family: var(--mono); text-transform: lowercase; }
.lft-k--mint { background: rgba(0,255,136,0.12); color: var(--green); }
.lft-k--burn { background: rgba(255,51,102,0.18); color: #ff6b8a; }
.lft-k--refund { background: rgba(255,149,0,0.14); color: var(--amber); }
.lft-k--unknown { background: rgba(255,255,255,0.04); color: var(--muted); }
.lft-k--transit { background: rgba(154,214,255,0.1); color: #9ab0c4; }
.lft-ev-src { font-size: 10px; color: var(--muted); font-family: var(--mono); }
.lft-idem { font-size: 10px; color: #7e8a99; font-family: var(--mono); max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lft-ev-caret { width: 14px; height: 14px; color: var(--muted); }

.lft-entries { margin-top: 7px; display: flex; flex-direction: column; gap: 3px; }
.lft-entry { display: flex; gap: 14px; align-items: baseline; font-size: 11.5px; font-family: var(--mono); }
.lft-acct { color: #9ab0c4; min-width: 220px; }
.lft-delta { font-weight: 600; }
.lft-pos { color: var(--green); }
.lft-neg { color: #ff6b8a; }
.lft-zero { color: var(--muted); }
.lft-net { font-size: 11px; font-family: var(--mono); color: var(--muted); margin-top: 2px; }
.lft-generic { margin-top: 6px; font-size: 11.5px; font-family: var(--mono); color: #9ab0c4; }
.lft-json { margin-top: 8px; }

.lft-error {
  margin-top: 14px; padding: 10px 14px; background: rgba(255,51,102,0.08);
  border: 1px solid rgba(255,51,102,0.35); color: var(--red); border-radius: 4px; font-size: 12px;
}

/* §FEDEVENTS — windowed aggregate-chain stepper */
.lft-window {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
  margin: -4px 0 12px; padding: 6px 14px;
  background: rgba(255,255,255,0.02); border: 1px dashed var(--border); border-radius: 8px;
}
.lft-window-lbl { font-size: 10.5px; font-family: var(--mono); color: var(--muted); }
.lft-win-btn {
  background: transparent; color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb),0.3);
  border-radius: 4px; padding: 3px 10px; font-size: 10.5px; cursor: pointer; font-family: var(--mono);
}
.lft-win-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb),0.1); }
.lft-win-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.lft-win-note { font-size: 10px; color: var(--muted); font-family: var(--mono); }
.lft-win-note--warn { color: var(--amber); }
</style>
