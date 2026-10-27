<template>
  <Teleport to="body">
    <div v-if="show" class="gbr-overlay" @click.self="$emit('close')">
      <div class="gbr-panel" role="dialog" aria-modal="true" aria-label="Multi-op balance reconcile">
        <header class="gbr-head">
          <h3 class="gbr-title"><Icon name="mdi:scale-balance" :size="14" /> Multi-op balance reconcile</h3>
          <button class="gbr-x" type="button" aria-label="Close" @click="$emit('close')"><Icon name="mdi:close" :size="14" /></button>
        </header>

        <p class="gbr-lede">
          READ-ONLY. Sums each agent's <code>token_balance</code> across <strong>all family op TEGs</strong>
          of a frame and compares to the EventStore aggregate (<code>materialized_balances</code>).
          <strong>drift = Σ(TEG) − ES&nbsp;liquid.</strong> System accounts excluded. No mutation, Δ untouched.
        </p>

        <div class="gbr-tabs">
          <button
            v-for="f in framesPresent" :key="f"
            class="gbr-tab" :class="{ 'gbr-tab--on': frame === f }"
            type="button" @click="frame = f"
          >Frame {{ f }}</button>
          <button class="gbr-go" type="button" :disabled="busy || !directory" @click="runScan">
            <Icon :name="busy ? 'mdi:refresh' : 'mdi:calculator'" :size="13" :class="busy ? 'gbr-spin' : ''" />
            {{ busy ? 'Scanning…' : 'Run reconcile' }}
          </button>
        </div>

        <div v-if="error" class="gbr-error"><Icon name="mdi:alert-triangle" :size="13" /> {{ error }}</div>

        <div v-if="result" class="gbr-body">
          <!-- per-registry fetch status -->
          <div class="gbr-status">
            <span
              v-for="s in result.status" :key="s.key"
              class="gbr-chip" :class="`gbr-chip--${s.state}`"
              :title="s.detail"
            >
              <Icon :name="s.state === 'ok' ? 'mdi:check-circle' : s.state === 'skipped' ? 'mdi:alert-triangle' : 'mdi:close-circle'" :size="11" />
              {{ shortName(s.name) }}
            </span>
          </div>

          <div v-if="result.partial" class="gbr-warn">
            <Icon name="mdi:alert-triangle" :size="13" />
            PARTIAL — {{ result.fetched }}/{{ result.total }} family registries read.
            Sums exclude unconnected ops and will NOT match the host tool. Connect every Frame&nbsp;{{ result.frame }}
            registry (vault import) for the full picture.
          </div>

          <!-- summary grid -->
          <div class="gbr-grid">
            <div class="gbr-cell"><span class="gbr-k">ES agents</span><span class="gbr-v">{{ result.esAgents }}</span></div>
            <div class="gbr-cell"><span class="gbr-k">TEG-union</span><span class="gbr-v">{{ result.tegUnion }}</span></div>
            <div class="gbr-cell"><span class="gbr-k">multi-op</span><span class="gbr-v">{{ result.multiOp }}</span></div>
            <div class="gbr-cell"><span class="gbr-k">ES-only</span><span class="gbr-v">{{ result.eOnly }}</span></div>
            <div class="gbr-cell"><span class="gbr-k">drifted</span><span class="gbr-v" :class="result.drifted ? 'gbr-v--warn' : 'gbr-v--ok'">{{ result.drifted }}</span></div>
            <div class="gbr-cell"><span class="gbr-k">net Σ(T−E)</span><span class="gbr-v gbr-mono" :class="netClass">{{ fxStr(result.net) }}</span></div>
            <div class="gbr-cell gbr-cell--wide"><span class="gbr-k">Σ|drift|</span><span class="gbr-v gbr-mono">{{ fxStr(result.absum) }}</span></div>
          </div>

          <div class="gbr-buckets">
            magnitude:
            <span v-for="(n, b) in result.buckets" :key="b" class="gbr-bk"><b>{{ b }}</b>&nbsp;{{ n }}</span>
          </div>

          <!-- top drifts -->
          <div v-if="result.drift.length" class="gbr-table-wrap">
            <table class="gbr-table">
              <thead>
                <tr><th class="gbr-r">drift (T−E)</th><th class="gbr-r">ES&nbsp;liquid</th><th class="gbr-r">TEG&nbsp;sum</th><th>m</th><th>agent</th><th>legs (op : token)</th></tr>
              </thead>
              <tbody>
                <tr v-for="x in result.drift.slice(0, top)" :key="x.did">
                  <td class="gbr-r gbr-mono" :class="x.drift < 0n ? 'gbr-neg' : 'gbr-pos'">{{ fxStr(x.drift) }}</td>
                  <td class="gbr-r gbr-mono">{{ fxStr(x.esLiquid) }}</td>
                  <td class="gbr-r gbr-mono">{{ fxStr(x.tegSum) }}</td>
                  <td class="gbr-m">{{ x.multiOp ? 'M' : '' }}</td>
                  <td class="gbr-mono gbr-did" :title="x.did">…{{ x.did.slice(-18) }}</td>
                  <td class="gbr-legs">{{ legStr(x.legs) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="result.drift.length > top" class="gbr-more">… +{{ result.drift.length - top }} more (raise “rows” or use the host CSV export)</div>
          </div>
          <div v-else class="gbr-pristine"><Icon name="mdi:check-circle" :size="14" /> No drift — frame is pristine (ES projection == TEG custody).</div>

          <footer class="gbr-foot">
            ES source: <code>{{ result.esSrc || '—' }}</code> · matches
            <code>scripts/recon/multi_op_balance_reconcile.py --frame frame-{{ result.frame.toLowerCase() }}</code>
            when all ops connected. Resync is a separate, converge-gated Phase-2 action — not here.
          </footer>
        </div>

        <div v-else-if="!busy && !error" class="gbr-empty">
          Pick a frame and run. For Frame B/C, connect at least one family registry first (vault import).
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { useCommandSessions } from '@/stores/commandSessions'
import {
  balanceReconcileEsBalances, balanceReconcileEsBalancesRemote,
  balanceReconcileLocal, balanceReconcileLocalRemote,
} from '@/services/api/command'
import type { EsBalances, RegistryDirectory, TegBalances } from '@/services/api/command'

const props = defineProps<{ show: boolean; directory: RegistryDirectory | null }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const sessions = useCommandSessions()

// ── fixed-point (1e12) BigInt arithmetic — exact match to the host tool's Decimal ──
const SCALE_F = 1_000_000_000_000n          // 1e12
const EPS_FX = 1_000_000n                   // 1e-6 scaled (host EPSILON)
const SYSTEM_RE = /teg_system_treasury|fee_collector|fx_reserve|fx_router|teg:system:|exchange_escrow/i

function toFx(s: string): bigint {
  if (!s) return 0n
  let t = String(s).trim()
  let neg = false
  if (t[0] === '-') { neg = true; t = t.slice(1) } else if (t[0] === '+') t = t.slice(1)
  const dot = t.indexOf('.')
  const intp = dot === -1 ? t : t.slice(0, dot)
  let frac = dot === -1 ? '' : t.slice(dot + 1)
  frac = (frac + '000000000000').slice(0, 12)
  try { const v = BigInt(intp || '0') * SCALE_F + BigInt(frac || '0'); return neg ? -v : v } catch { return 0n }
}
function abs(v: bigint): bigint { return v < 0n ? -v : v }
function fxStr(v: bigint, dp = 4): string {
  const neg = v < 0n
  const a = neg ? -v : v
  const dropF = 10n ** BigInt(12 - dp)
  let q = a / dropF
  if ((a % dropF) * 2n >= dropF) q += 1n     // round half-up
  const dpF = 10n ** BigInt(dp)
  const whole = q / dpF
  const frac = (q % dpF).toString().padStart(dp, '0')
  return (neg && q !== 0n ? '-' : '') + whole.toString() + (dp > 0 ? '.' + frac : '')
}

const top = 25
type RegState = 'ok' | 'skipped' | 'error'
interface RegStatus { key: string; name: string; state: RegState; detail: string }
interface Leg { op: string; bal: bigint }
interface DriftRow { did: string; esLiquid: bigint; tegSum: bigint; drift: bigint; legs: Leg[]; multiOp: boolean }
interface FrameResult {
  frame: 'A' | 'B' | 'C'
  esAgents: number; tegUnion: number; multiOp: number; eOnly: number; drifted: number
  net: bigint; absum: bigint; buckets: Record<string, number>; drift: DriftRow[]
  status: RegStatus[]; esSrc: string; fetched: number; total: number; partial: boolean
}

const framesPresent = computed<Array<'A' | 'B' | 'C'>>(() => {
  const set = new Set<'A' | 'B' | 'C'>()
  for (const e of props.directory?.registries || []) if (e.frame) set.add(e.frame)
  return (['A', 'B', 'C'] as const).filter(f => set.has(f))
})

const frame = ref<'A' | 'B' | 'C'>('A')
const busy = ref(false)
const error = ref('')
const result = ref<FrameResult | null>(null)

watch(() => props.show, (v) => {
  if (v) { result.value = null; error.value = ''; if (!framesPresent.value.includes(frame.value)) frame.value = framesPresent.value[0] || 'A' }
})

function shortName(n: string): string { return (n || '').replace(/^op-/i, '').toLowerCase() }
function legStr(legs: Leg[]): string { return legs.map(l => `${shortName(l.op)}:${fxStr(l.bal, 2)}`).join(' + ') }

const netClass = computed(() => {
  if (!result.value) return ''
  return result.value.net < 0n ? 'gbr-neg' : result.value.net > 0n ? 'gbr-pos' : 'gbr-v--ok'
})

function bucketize(rows: DriftRow[]): Record<string, number> {
  const b: Record<string, number> = { '>10k': 0, '1k-10k': 0, '100-1k': 0, '10-100': 0, '1-10': 0, '<1': 0 }
  const T10k = 10000n * SCALE_F, T1k = 1000n * SCALE_F, T100 = 100n * SCALE_F, T10 = 10n * SCALE_F, T1 = 1n * SCALE_F
  for (const r of rows) {
    const a = abs(r.drift)
    if (a > T10k) b['>10k']++
    else if (a > T1k) b['1k-10k']++
    else if (a > T100) b['100-1k']++
    else if (a > T10) b['10-100']++
    else if (a > T1) b['1-10']++
    else b['<1']++
  }
  return b
}

async function runScan() {
  const dir = props.directory
  if (!dir) return
  busy.value = true; error.value = ''; result.value = null
  const fl = frame.value
  const fam = dir.registries.filter(e => e.frame === fl)
  const status: RegStatus[] = []

  // ── TEG legs: Σ token_balance per agent across every family registry ──
  const tsum = new Map<string, bigint>()
  const legs = new Map<string, Leg[]>()
  for (const e of fam) {
    let data: TegBalances | null = null
    let err = ''
    try {
      if (e.is_local) data = await balanceReconcileLocal()
      else {
        const tok = sessions.adminTokenFor(e.key)
        if (!tok) { status.push({ key: e.key, name: e.name, state: 'skipped', detail: 'not connected (no admin session)' }); continue }
        data = await balanceReconcileLocalRemote(e.key, tok)
      }
    } catch (ex: any) { err = ex?.response?.data?.detail || ex?.message || 'fetch failed' }
    if (!data) { status.push({ key: e.key, name: e.name, state: 'error', detail: err || 'no data' }); continue }
    for (const r of data.balances) {
      const fx = toFx(r.token_balance)
      tsum.set(r.agent_id, (tsum.get(r.agent_id) ?? 0n) + fx)
      const arr = legs.get(r.agent_id) ?? []; arr.push({ op: e.name, bal: fx }); legs.set(r.agent_id, arr)
    }
    status.push({ key: e.key, name: e.name, state: 'ok', detail: `${data.count} agents` })
  }

  // ── ES aggregate (local family reg → apiClient; else first connected family reg) ──
  let es: EsBalances | null = null
  let esSrc = ''
  const localFam = fam.find(e => e.is_local)
  try {
    if (localFam) { es = await balanceReconcileEsBalances(); esSrc = localFam.name }
    else {
      const conn = fam.find(e => sessions.adminTokenFor(e.key))
      if (conn) { es = await balanceReconcileEsBalancesRemote(conn.key, sessions.adminTokenFor(conn.key)!); esSrc = conn.name }
    }
  } catch (ex: any) { error.value = `ES fetch failed: ${ex?.response?.data?.detail || ex?.message || 'error'}` }

  const fetched = status.filter(s => s.state === 'ok').length
  if (!es) {
    error.value = error.value || `No ES source for Frame ${fl}. Connect a Frame ${fl} registry (vault import) first.`
    result.value = { frame: fl, esAgents: 0, tegUnion: tsum.size, multiOp: 0, eOnly: 0, drifted: 0, net: 0n, absum: 0n, buckets: bucketize([]), drift: [], status, esSrc, fetched, total: fam.length, partial: true }
    busy.value = false
    return
  }

  const esMap = new Map<string, bigint>()
  for (const a of es.agents) esMap.set(a.agent_did, toFx(a.liquid_balance))

  // ── compute drift (mirror host tool) ──
  let multiOp = 0
  const drift: DriftRow[] = []
  for (const [did, t] of tsum) {
    if (SYSTEM_RE.test(did)) continue
    const lg = legs.get(did) ?? []
    if (lg.length > 1) multiOp++
    const el = esMap.get(did) ?? 0n
    const d = t - el
    if (abs(d) > EPS_FX) drift.push({ did, esLiquid: el, tegSum: t, drift: d, legs: lg, multiOp: lg.length > 1 })
  }
  drift.sort((a, b) => (abs(a.drift) < abs(b.drift) ? 1 : abs(a.drift) > abs(b.drift) ? -1 : 0))
  let eOnly = 0
  for (const did of esMap.keys()) if (!tsum.has(did) && !SYSTEM_RE.test(did)) eOnly++
  const net = drift.reduce((s, r) => s + r.drift, 0n)
  const absum = drift.reduce((s, r) => s + abs(r.drift), 0n)

  result.value = {
    frame: fl, esAgents: es.agents.length, tegUnion: tsum.size, multiOp, eOnly,
    drifted: drift.length, net, absum, buckets: bucketize(drift), drift,
    status, esSrc, fetched, total: fam.length, partial: fetched < fam.length,
  }
  busy.value = false
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, () => emit('close'))
</script>

<style scoped>
.gbr-overlay {
  position: fixed; inset: 0; z-index: 10300;
  background: rgba(2, 5, 10, 0.72);
  backdrop-filter: blur(3px); -webkit-backdrop-filter: blur(3px);
  display: flex; align-items: center; justify-content: center; padding: 18px;
}
.gbr-panel {
  width: 100%; max-width: 880px; max-height: 88vh; overflow-y: auto;
  background: linear-gradient(168deg, rgba(255,255,255,.025), transparent 60%), rgba(13, 18, 28, 0.97);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), 0.22);
  border-radius: 12px; color: var(--nc-text-primary, #e8eaed);
  box-shadow: 0 18px 60px rgba(0,0,0,.55);
}
.gbr-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px 6px; }
.gbr-title { margin: 0; display: inline-flex; align-items: center; gap: 7px; font-size: .95rem; font-weight: 700; }
.gbr-x { width: 30px; height: 30px; display: grid; place-items: center; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.08); border-radius: 7px; color: var(--nc-text-muted, #94a3b8); cursor: pointer; }
.gbr-lede { margin: 0; padding: 0 16px 8px; font-size: .73rem; line-height: 1.5; color: var(--nc-text-muted, #94a3b8); }
.gbr-lede code { font-size: .9em; color: var(--nc-primary, #00d2d2); }
.gbr-tabs { display: flex; flex-wrap: wrap; gap: 6px; padding: 4px 16px 10px; align-items: center; }
.gbr-tab { padding: 5px 13px; border-radius: 7px; font-size: .72rem; font-weight: 700; cursor: pointer; background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.1); color: var(--nc-text-muted, #94a3b8); }
.gbr-tab--on { color: var(--nc-primary, #00d2d2); border-color: rgba(var(--nc-primary-rgb, 0,210,210), .45); background: rgba(var(--nc-primary-rgb, 0,210,210), .1); }
.gbr-go {
  margin-left: auto; min-height: 34px; padding: 0 15px; border-radius: 8px; cursor: pointer; font-size: .78rem; font-weight: 700;
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(var(--nc-primary-rgb, 0,210,210), .14);
  border: 1px solid rgba(var(--nc-primary-rgb, 0,210,210), .45); color: var(--nc-primary, #00d2d2);
}
.gbr-go:disabled { opacity: .45; cursor: not-allowed; }
.gbr-spin { animation: gbr-rot 1s linear infinite; }
@keyframes gbr-rot { to { transform: rotate(360deg); } }
.gbr-error { margin: 0 16px 10px; padding: 8px 11px; font-size: .74rem; border-radius: 8px; display: flex; align-items: center; gap: 7px; color: #fca5a5; background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3); }
.gbr-body { padding: 0 16px 14px; display: grid; gap: 11px; }
.gbr-status { display: flex; flex-wrap: wrap; gap: 5px; }
.gbr-chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 6px; font-size: .66rem; font-weight: 700; border: 1px solid rgba(255,255,255,.08); }
.gbr-chip--ok { color: #10b981; background: rgba(16,185,129,.08); border-color: rgba(16,185,129,.25); }
.gbr-chip--skipped { color: #fbbf24; background: rgba(251,191,36,.08); border-color: rgba(251,191,36,.25); }
.gbr-chip--error { color: #ef4444; background: rgba(239,68,68,.08); border-color: rgba(239,68,68,.25); }
.gbr-warn { padding: 8px 11px; font-size: .72rem; border-radius: 8px; display: flex; align-items: center; gap: 7px; color: #fcd34d; background: rgba(251,191,36,.09); border: 1px solid rgba(251,191,36,.28); }
.gbr-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; }
.gbr-cell { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border-radius: 8px; background: rgba(255,255,255,.025); border: 1px solid rgba(255,255,255,.06); }
.gbr-cell--wide { grid-column: span 2; }
.gbr-k { font-size: .6rem; text-transform: uppercase; letter-spacing: .08em; color: var(--nc-text-muted, #94a3b8); }
.gbr-v { font-size: .95rem; font-weight: 800; }
.gbr-v--ok { color: #10b981; }
.gbr-v--warn { color: #fbbf24; }
.gbr-mono { font-family: ui-monospace, monospace; }
.gbr-neg { color: #f87171; }
.gbr-pos { color: #34d399; }
.gbr-buckets { font-size: .68rem; color: var(--nc-text-muted, #94a3b8); display: flex; flex-wrap: wrap; gap: 9px; }
.gbr-bk b { color: var(--nc-text-primary, #e8eaed); }
.gbr-table-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid rgba(255,255,255,.06); }
.gbr-table { width: 100%; border-collapse: collapse; font-size: .68rem; }
.gbr-table th { text-align: left; padding: 6px 8px; background: rgba(255,255,255,.03); color: var(--nc-text-muted, #94a3b8); font-weight: 700; position: sticky; top: 0; }
.gbr-table td { padding: 5px 8px; border-top: 1px solid rgba(255,255,255,.04); }
.gbr-r { text-align: right; }
.gbr-m { text-align: center; color: var(--nc-primary, #00d2d2); font-weight: 800; }
.gbr-did { color: var(--nc-text-muted, #cbd5e1); }
.gbr-legs { color: var(--nc-text-muted, #94a3b8); white-space: nowrap; }
.gbr-more { padding: 6px 8px; font-size: .66rem; color: var(--nc-text-muted, #94a3b8); }
.gbr-pristine { display: flex; align-items: center; gap: 8px; padding: 12px; font-size: .8rem; color: #34d399; background: rgba(16,185,129,.06); border: 1px solid rgba(16,185,129,.22); border-radius: 8px; }
.gbr-foot { font-size: .65rem; color: var(--nc-text-muted, #94a3b8); line-height: 1.5; padding-top: 2px; }
.gbr-foot code { color: var(--nc-primary, #00d2d2); }
.gbr-empty { padding: 0 16px 18px; font-size: .76rem; color: var(--nc-text-muted, #94a3b8); }
@media (max-width: 720px) {
  .gbr-overlay { align-items: flex-end; padding: 0; }
  .gbr-panel { max-width: none; border-radius: 14px 14px 0 0; }
  .gbr-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
