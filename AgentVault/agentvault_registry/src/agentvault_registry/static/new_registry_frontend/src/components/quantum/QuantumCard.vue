<template>
  <section
    v-if="served && visible"
    ref="root"
    class="qc"
    :class="['qc--' + variant, { 'qc--framed': variant !== 'tile' }]"
    data-testid="qc-card"
    :data-variant="variant"
    :data-state="readState"
  >
    <!-- V0660 (e): the quantum card. It exists only where the frame serves quantum workloads (the registry-config's
         quantum_workloads block, V0660 (d)); under off nothing renders and nothing is asked. Every fact on it is the
         card's own (V0660 (a)'s extension, read through GET /api/v1/quantum/agents/{did}), with when it was read. -->
    <div class="qc-in">
      <header class="qc-head">
        <svg class="qc-glyph" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M4 1.5h8L15 6 8 14.5 1 6z M1 6h14 M4 1.5 6 6 8 1.5 10 6 12 1.5 M6 6l2 8.5L10 6" />
        </svg>
        <span class="qc-eyebrow">{{ t('quantumCard.eyebrow', 'Quantum workload') }}</span>
        <span v-if="version" class="qc-ver">v{{ version }}</span>
        <span v-if="checkWord" class="qc-check" :class="'qc-check--' + checkWord.kind" data-testid="qc-check"
              :data-check="checkWord.kind" :title="checkWord.title">{{ checkWord.text }}</span>
      </header>

      <p v-if="roles.length" class="qc-roles" data-testid="qc-roles">{{ roles.join(' · ') }}</p>

      <!-- the facts at a glance: what discovery already knows, before the backend is read -->
      <p v-if="variant !== 'full' && summary.length" class="qc-summary" data-testid="qc-summary">
        <span v-for="(s, i) in summary" :key="i" class="qc-summary-item">{{ s }}</span>
      </p>

      <div v-if="backends.length > 1 && variant === 'full'" class="qc-tabs" role="tablist"
           :aria-label="t('quantumCard.backends', 'Backends')">
        <button
          v-for="(b, i) in backends"
          :key="String(b.id) + i"
          type="button"
          role="tab"
          class="qc-tab"
          :class="{ 'qc-tab--on': i === selected }"
          :aria-selected="i === selected"
          data-testid="qc-backend-tab"
          @click.stop="selected = i"
        >{{ b.name || b.id }}</button>
      </div>

      <div class="qc-body" :class="'qc-body--' + variant">
        <figure v-if="lattice" class="qc-latt">
          <QuantumLattice :lattice="lattice" :label="latticeNote" :size="variant === 'full' ? 'lg' : 'sm'" />
          <figcaption class="qc-note" data-testid="qc-lattice-note" :data-source="lattice.source">
            <span v-if="variant !== 'full' && backend?.name" class="qc-latt-name">{{ backend.name }}. </span>{{ latticeNote }}
            <span v-if="lattice.digest" class="qc-digest" :title="lattice.digest">{{ shortDigest(lattice.digest) }}</span>
            <span v-if="variant !== 'full' && backends.length > 1" class="qc-more">
              {{ tp('quantumCard.moreBackends', '+{n} more on the agent page', { n: backends.length - 1 }) }}</span>
          </figcaption>
        </figure>
        <p v-else-if="readState === 'reading'" class="qc-note" data-testid="qc-reading">
          {{ t('quantumCard.reading', 'Reading the backend\'s facts…') }}</p>
        <p v-else-if="readState === 'failed' && !backends.length" class="qc-note" data-testid="qc-unread">
          {{ t('quantumCard.unread', 'The backend\'s facts could not be read here just now.') }}</p>

        <dl v-if="variant === 'full' && backend" class="qc-facts" data-testid="qc-facts">
          <template v-for="f in facts" :key="f.key">
            <dt class="qc-label">{{ f.label }}</dt>
            <dd class="qc-value" data-testid="qc-fact" :data-fact="f.key">
              {{ f.value }}<span v-if="f.age" class="qc-age"> · {{ f.age }}</span>
            </dd>
          </template>
        </dl>
      </div>

      <section v-if="rungs.length" class="qc-rungs" data-testid="qc-rungs">
        <h4 class="qc-h">{{ t('quantumCard.rungs.title', 'What a buyer can get') }}</h4>
        <div v-for="row in rungs" :key="row.rung" class="qc-rung" data-testid="qc-rung" :data-rung="row.rung" :data-state="row.state"
             :title="variant === 'full' ? undefined : rungName(row.rung) + '. ' + rungState(row)">
          <span class="qc-rung-n">{{ tp('quantumCard.rungs.rung', 'Rung {n}', { n: row.rung }) }}</span>
          <template v-if="variant === 'full'">
            <span class="qc-rung-name">{{ rungName(row.rung) }}</span>
            <span class="qc-rung-state" :class="'qc-rung-state--' + row.state">{{ rungState(row) }}</span>
          </template>
          <span v-else class="qc-rung-state" :class="'qc-rung-state--' + row.state">{{ rungShort(row) }}</span>
          <ul v-if="variant === 'full' && row.tests.length" class="qc-tests">
            <li v-for="tst in row.tests" :key="tst.template" class="qc-test">
              <code class="qc-code">{{ tst.template }}</code>
              <span v-if="tst.falseAccept" class="qc-test-rate">{{ tp('quantumCard.rungs.falseAccept', 'false accept {p}', { p: tst.falseAccept }) }}</span>
              <span v-if="tst.falseReject" class="qc-test-rate">{{ tp('quantumCard.rungs.falseReject', 'false reject {p}', { p: tst.falseReject }) }}</span>
            </li>
          </ul>
        </div>
      </section>

      <section v-if="variant === 'full' && params" class="qc-receipts" data-testid="qc-receipts">
        <h4 class="qc-h">{{ t('quantumCard.receipts.title', 'Receipts and data') }}</h4>
        <p v-if="receipts.signingAlgorithm" class="qc-line" data-testid="qc-receipt">
          {{ tp('quantumCard.receipts.signed', 'Each job receipt is signed with {alg} (receipt schema {v}).',
                { alg: receipts.signingAlgorithm, v: receipts.schemaVersion || '?' }) }}</p>
        <p v-if="receipts.registrySchema" class="qc-line">
          {{ tp('quantumCard.receipts.registry', 'This registry names receipts of schema {v}, signed with {algs}.',
                { v: receipts.registrySchema, algs: receipts.registryAlgorithms.join(', ') || '?' }) }}</p>
        <p v-if="receipts.meteringCircuit" class="qc-line">
          {{ tp('quantumCard.receipts.metering', 'Use is metered against {c}.', { c: receipts.meteringCircuit }) }}</p>
        <p v-if="receipts.pricingModel" class="qc-line">
          {{ tp('quantumCard.receipts.pricing', 'Priced {model}. The amount is in the card\'s payment terms.',
                { model: pricingWord(receipts.pricingModel) }) }}</p>
        <p v-if="receipts.resultsDays !== null || receipts.circuitsDays !== null" class="qc-line">
          {{ tp('quantumCard.receipts.retention', 'Circuits are kept {c} days, results {r} days.',
                { c: receipts.circuitsDays ?? '?', r: receipts.resultsDays ?? '?' }) }}
          <span v-if="receipts.residency.length">{{ tp('quantumCard.receipts.residency', 'Data stays in {r}.', { r: receipts.residency.join(', ') }) }}</span>
        </p>
        <p v-if="receipts.ledgerKeeps.length" class="qc-line">
          {{ tp('quantumCard.receipts.ledger', 'The ledger keeps {k}, never circuits.', { k: receipts.ledgerKeeps.join(' and ') }) }}</p>
        <p v-if="receipts.exportNote" class="qc-line qc-note">{{ receipts.exportNote }}</p>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import QuantumLattice from '@/components/quantum/QuantumLattice.vue'
import { useQuantumWorkloads } from '@/composables/useQuantumWorkloads'
import { useI18n } from '@/composables/useI18n'
import { readQuantumAgent, type QuantumRead } from '@/services/api/quantum'
import {
  ageOf, availabilityWindows, backendTimeKind, backendsOf, latticeFor, percent, receiptFacts, rungRows, secondsSince, shortDigest,
  type QuantumFacets, type RungRow,
} from '@/services/quantum/quantumCard'

const props = withDefaults(defineProps<{
  did: string
  variant?: 'tile' | 'full' | 'chat'
  /** the discover item's facets (shown at once, before the backend is read) */
  facets?: QuantumFacets | null
  /** the card's own extension params, where the caller holds the card (the agent page) */
  params?: Record<string, any> | null
}>(), { variant: 'full', facets: null, params: null })

const emit = defineEmits<{ (e: 'state', s: 'reading' | 'ok' | 'none' | 'failed'): void }>()

const { t, tp } = useI18n()
const { block, served } = useQuantumWorkloads()

const readState = ref<'idle' | 'reading' | 'ok' | 'none' | 'failed'>('idle')
const read = ref<QuantumRead | null>(null)
const selected = ref(0)
const root = ref<HTMLElement | null>(null)
let observer: IntersectionObserver | null = null
let seq = 0

async function load() {
  if (!served.value || !props.did) return
  const mine = ++seq
  readState.value = 'reading'
  emit('state', 'reading')
  const r = await readQuantumAgent(props.did)
  if (mine !== seq) return
  read.value = r.state === 'ok' ? r.read : null
  readState.value = r.state
  emit('state', r.state)
}

function start() {
  observer?.disconnect(); observer = null
  if (!served.value) return
  // a grid reads a backend when its card comes into view; the agent page and a chat card read at once
  if (props.variant === 'tile' && typeof IntersectionObserver !== 'undefined' && root.value) {
    observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { observer?.disconnect(); observer = null; void load() }
    }, { rootMargin: '200px' })
    observer.observe(root.value)
  } else {
    void load()
  }
}

onMounted(start)
watch(() => [props.did, served.value], async () => {
  read.value = null; readState.value = 'idle'; selected.value = 0
  await nextTick()   // the section (and its ref) renders once served
  start()
})
onBeforeUnmount(() => { observer?.disconnect(); seq++ })

/** a chat card stays an ordinary agent card until the registry says this agent carries the extension */
const visible = computed(() => props.variant !== 'chat' || readState.value === 'ok')

const params = computed<Record<string, any> | null>(() => read.value?.params || props.params || null)
const backends = computed(() => backendsOf(params.value))
const backend = computed<Record<string, any> | null>(() => backends.value[selected.value] || backends.value[0] || null)
const lattice = computed(() => (backend.value ? latticeFor(backend.value) : null))
const version = computed(() => (typeof params.value?.version === 'string' ? params.value.version : props.facets?.version) || '')
const roles = computed<string[]>(() => {
  const r = Array.isArray(params.value?.roles) ? params.value!.roles : (props.facets?.roles || [])
  return r.filter((x: unknown) => typeof x === 'string').map((x: string) => roleWord(x))
})
const rungs = computed<RungRow[]>(() => {
  if (params.value) return rungRows(params.value, block.value)
  // before the read: the rungs the index states, settled here or not by the registry's block
  const listed = props.facets?.rungs || []
  return rungRows({ evidence: { verification_rungs: listed, acceptance_tests: [] } }, block.value)
})
const receipts = computed(() => receiptFacts(params.value, block.value))

const checkWord = computed<{ kind: string; text: string; title: string } | null>(() => {
  const c = read.value?.check
  if (readState.value === 'ok' && c) {
    const mode = c.mode === 'shadow' ? ` ${t('quantumCard.check.shadow', '(shadow)')}` : ''
    if (c.valid) return { kind: 'ok', text: t('quantumCard.check.valid', 'Checked here') + mode, title: t('quantumCard.check.validTitle', 'This registry checked the extension against the spec and found no problem.') }
    const n = (c.problems || []).length
    return { kind: 'bad', text: tp('quantumCard.check.problems', '{n} problems found here', { n }) + mode, title: (c.problems || []).join('\n') }
  }
  if (readState.value === 'failed') return { kind: 'unread', text: t('quantumCard.check.unread', 'Not checked: no answer'), title: t('quantumCard.unread', 'The backend\'s facts could not be read here just now.') }
  return null
})

const summary = computed<string[]>(() => {
  const out: string[] = []
  const f = props.facets
  const mods = f?.modalities?.length ? f.modalities : [...new Set(backends.value.map((b) => b.modality).filter(Boolean))]
  if (mods.length) out.push(mods.map((m: string) => modalityWord(m)).join(', '))
  const q = f?.max_qubits ?? Math.max(0, ...backends.value.map((b) => Number(b.qubits?.physical) || 0))
  if (q) out.push(tp('quantumCard.summary.qubits', 'up to {n} qubits', { n: q }))
  const fm = f?.formats?.length ? f.formats : [...new Set(backends.value.flatMap((b) => (Array.isArray(b.formats) ? b.formats : [])))]
  if (fm.length) out.push(fm.join(' · '))
  const nb = f?.backends || backends.value.length
  if (nb > 1) out.push(tp('quantumCard.summary.backends', '{n} backends', { n: nb }))
  return out
})

function ageText(seconds: number | null | undefined): string {
  const a = ageOf(seconds)
  if (!a) return ''
  const unit = { s: t('quantumCard.age.s', 's'), m: t('quantumCard.age.m', 'min'), h: t('quantumCard.age.h', 'h'), d: t('quantumCard.age.d', 'd') }[a.unit]
  return tp('quantumCard.age.read', 'read {n} {u} ago', { n: a.n, u: unit })
}
function ageFor(block: 'facts' | 'calibration' | 'queue' | 'availability', asOf: unknown): string {
  const fr = read.value?.freshness?.backends?.find((r) => r.id === backend.value?.id)
  const s = fr?.age_seconds?.[block]
  return ageText(typeof s === 'number' ? s : secondsSince(asOf))
}

const facts = computed(() => {
  const b = backend.value
  if (!b) return []
  const rows: Array<{ key: string; label: string; value: string; age?: string }> = []
  rows.push({ key: 'kind', label: t('quantumCard.fact.kind', 'Kind'), value: `${kindWord(b.kind)} · ${modalityWord(b.modality)}`, age: ageFor('facts', b.as_of) })
  if (b.operator?.name) rows.push({ key: 'operator', label: t('quantumCard.fact.operator', 'Operator'), value: String(b.operator.name) })
  const loc = b.location || {}
  const where = [loc.label, loc.jurisdiction ? tp('quantumCard.fact.jurisdiction', 'jurisdiction {j}', { j: loc.jurisdiction }) : ''].filter(Boolean).join(' · ')
  if (where) rows.push({ key: 'location', label: t('quantumCard.fact.location', 'Location'), value: where })
  const q = b.qubits || {}
  let qv = tp('quantumCard.fact.physical', '{n} physical', { n: q.physical ?? '?' })
  if (q.logical?.count) qv += ` · ${tp('quantumCard.fact.logical', '{n} logical ({code})', { n: q.logical.count, code: q.logical.code || '?' })}`
  rows.push({ key: 'qubits', label: t('quantumCard.fact.qubits', 'Qubits'), value: qv })
  if (b.connectivity?.topology) rows.push({ key: 'topology', label: t('quantumCard.fact.topology', 'Topology'), value: String(b.connectivity.topology) })
  if (Array.isArray(b.native_gates)) rows.push({ key: 'gates', label: t('quantumCard.fact.gates', 'Native gates'), value: b.native_gates.join(' ') })
  if (Array.isArray(b.formats)) rows.push({ key: 'formats', label: t('quantumCard.fact.formats', 'Formats'), value: b.formats.join(' · ') })
  const l = b.limits || {}
  const lim = [
    l.max_shots ? tp('quantumCard.fact.shots', '{n} shots', { n: l.max_shots }) : '',
    l.max_depth ? tp('quantumCard.fact.depth', 'depth {n}', { n: l.max_depth }) : '',
    l.max_width ? tp('quantumCard.fact.width', 'width {n}', { n: l.max_width }) : '',
    l.mid_circuit_measurement ? t('quantumCard.fact.midCircuit', 'mid-circuit measurement') : '',
    l.dynamic_circuits ? t('quantumCard.fact.dynamic', 'dynamic circuits') : '',
  ].filter(Boolean).join(' · ')
  if (lim) rows.push({ key: 'limits', label: t('quantumCard.fact.limits', 'Limits'), value: lim })
  const c = b.calibration
  if (c) {
    const cal = [
      percent(c.median_1q_error) ? tp('quantumCard.fact.err1q', '1q error {p}', { p: percent(c.median_1q_error) }) : '',
      percent(c.median_2q_error) ? tp('quantumCard.fact.err2q', '2q error {p}', { p: percent(c.median_2q_error) }) : '',
      percent(c.median_readout_error) ? tp('quantumCard.fact.readout', 'readout {p}', { p: percent(c.median_readout_error) }) : '',
      c.median_t1_us ? tp('quantumCard.fact.t1', 'T1 {n} µs', { n: c.median_t1_us }) : '',
      c.median_t2_us ? tp('quantumCard.fact.t2', 'T2 {n} µs', { n: c.median_t2_us }) : '',
    ].filter(Boolean).join(' · ')
    rows.push({ key: 'calibration', label: t('quantumCard.fact.calibration', 'Calibration (median)'), value: cal || t('quantumCard.fact.snapshotOnly', 'snapshot only'), age: ageFor('calibration', c.as_of) })
    if (c.snapshot?.digest) rows.push({ key: 'snapshot', label: t('quantumCard.fact.snapshot', 'Signed snapshot'), value: [shortDigest(c.snapshot.digest), c.snapshot.signing_algorithm].filter(Boolean).join(' · ') })
  }
  const qu = b.queue
  if (qu) {
    const wait = typeof qu.estimated_wait_seconds === 'number' ? ` · ${tp('quantumCard.fact.wait', 'about {n} s wait', { n: qu.estimated_wait_seconds })}` : ''
    rows.push({ key: 'queue', label: t('quantumCard.fact.queue', 'Queue'), value: statusWord(qu.status) + wait, age: ageFor('queue', qu.as_of) })
  }
  // V0662 item 6: when the backend takes work, in UTC as the card states it, with when that was read
  const av = availabilityWindows(b)
  if (av.length) {
    const value = av.map((w) => {
      const span = tp('quantumCard.avail.window', '{days} {start}–{end} UTC', { days: daysWord(w.days), start: w.start, end: w.end })
      return w.overnight ? `${span} ${t('quantumCard.avail.overnight', '(into the next day)')}` : span
    }).join('; ')
    rows.push({ key: 'availability', label: t('quantumCard.fact.availability', 'Available'), value, age: ageFor('availability', b.availability?.as_of) })
  }
  return rows
})

const latticeNote = computed(() => {
  const l = lattice.value
  if (!l) return ''
  const n = l.qubits
  let s: string
  if (l.source === 'complete') {
    s = l.edgesDrawn
      ? tp('quantumCard.lattice.complete', '{n} qubits, all-to-all: every pair is coupled.', { n })
      : tp('quantumCard.lattice.completeNotDrawn', '{n} qubits, all-to-all: every pair is coupled ({e} pairs, too many to draw).', { n, e: l.edgeCount ?? '?' })
  } else if (l.source === 'digest') {
    s = l.edgeCount !== null
      ? tp('quantumCard.lattice.digestCount', '{n} qubits, {topo}. The coupling map ({e} couplings) is published only as a digest, so no coupling is drawn.', { n, topo: l.topology || '?', e: l.edgeCount })
      : tp('quantumCard.lattice.digest', '{n} qubits, {topo}. The coupling map is published only as a digest, so no coupling is drawn.', { n, topo: l.topology || '?' })
  } else {
    s = tp('quantumCard.lattice.none', '{n} qubits, {topo}. The card states no coupling map, so no coupling is drawn.', { n, topo: l.topology || '?' })
  }
  if (l.drawn < l.qubits) s += ' ' + tp('quantumCard.lattice.capped', 'The first {d} of {n} qubits are drawn.', { d: l.drawn, n })
  return s
})

function roleWord(r: string): string {
  const m: Record<string, string> = {
    provider: t('quantumCard.role.provider', 'provider'), compiler: t('quantumCard.role.compiler', 'compiler'),
    mitigator: t('quantumCard.role.mitigator', 'mitigator'), verifier: t('quantumCard.role.verifier', 'verifier'),
    router: t('quantumCard.role.router', 'router'), meter: t('quantumCard.role.meter', 'meter'),
  }
  return m[r] || r
}
function daysWord(d: string): string {
  const m: Record<string, string> = {
    everyday: t('quantumCard.days.everyday', 'every day'), weekdays: t('quantumCard.days.weekdays', 'weekdays'),
    weekend: t('quantumCard.days.weekend', 'weekends'), monday: t('quantumCard.days.monday', 'Monday'),
    tuesday: t('quantumCard.days.tuesday', 'Tuesday'), wednesday: t('quantumCard.days.wednesday', 'Wednesday'),
    thursday: t('quantumCard.days.thursday', 'Thursday'), friday: t('quantumCard.days.friday', 'Friday'),
    saturday: t('quantumCard.days.saturday', 'Saturday'), sunday: t('quantumCard.days.sunday', 'Sunday'),
  }
  return m[d] || d
}
function kindWord(k: unknown): string {
  const m: Record<string, string> = { qpu: t('quantumCard.kind.qpu', 'QPU'), simulator: t('quantumCard.kind.simulator', 'Simulator'), emulator: t('quantumCard.kind.emulator', 'Emulator') }
  return m[String(k)] || String(k ?? '?')
}
function modalityWord(k: unknown): string {
  const m: Record<string, string> = {
    superconducting: t('quantumCard.modality.superconducting', 'superconducting'), 'trapped-ion': t('quantumCard.modality.trappedIon', 'trapped ion'),
    'neutral-atom': t('quantumCard.modality.neutralAtom', 'neutral atom'), photonic: t('quantumCard.modality.photonic', 'photonic'),
    spin: t('quantumCard.modality.spin', 'spin'), annealer: t('quantumCard.modality.annealer', 'annealer'), simulator: t('quantumCard.modality.simulator', 'simulator'),
  }
  return m[String(k)] || String(k ?? '?')
}
function statusWord(s: unknown): string {
  const m: Record<string, string> = {
    online: t('quantumCard.status.online', 'online'), paused: t('quantumCard.status.paused', 'paused'), offline: t('quantumCard.status.offline', 'offline'),
    maintenance: t('quantumCard.status.maintenance', 'maintenance'), retired: t('quantumCard.status.retired', 'retired'),
  }
  return m[String(s)] || String(s ?? '?')
}
function pricingWord(p: string): string {
  const m: Record<string, string> = {
    per_shot: t('quantumCard.pricing.perShot', 'per shot'), per_task: t('quantumCard.pricing.perTask', 'per task'),
    per_second: perSecondWord(), per_gate_shot: t('quantumCard.pricing.perGateShot', 'per gate and shot'),
  }
  return m[p] || p
}
/** a second of what: worded from the backends' kind (every backend on our side is a simulator) */
function perSecondWord(): string {
  const k = backendTimeKind(backends.value)
  if (k === 'qpu') return t('quantumCard.pricing.perQpuSecond', 'per QPU second')
  if (k === 'simulator') return t('quantumCard.pricing.perSimulatorSecond', 'per simulator second')
  return t('quantumCard.pricing.perBackendSecond', 'per second of backend time')
}
function rungName(r: number): string {
  return r === 1 ? t('quantumCard.rungs.name1', 'Check the answer')
    : r === 2 ? t('quantumCard.rungs.name2', 'Hidden test circuits or an independent repeat')
      : t('quantumCard.rungs.name3', 'Signed claims')
}
/** the compact word a grid or a thread shows (the whole sentence is the row's title) */
function rungShort(row: RungRow): string {
  if (row.state === 'claims_only') return t('quantumCard.rungs.shortClaims', 'signed claims only')
  if (row.state === 'offered') return t('quantumCard.rungs.shortOffered', 'offered, not settled here')
  return t('quantumCard.rungs.shortHere', 'settles here')
}
function rungState(row: RungRow): string {
  if (row.state === 'claims_only') return t('quantumCard.rungs.claimsOnly', 'Signed claims only. Nothing here checks them.')
  if (row.state === 'offered') return t('quantumCard.rungs.offered', 'The agent offers it. This registry settles no verdict at this rung.')
  const rails = row.rails.map((r) => (r === 'guild_work_order'
    ? t('quantumCard.rungs.railGuild', 'a Guild work order\'s verify step')
    : r === 'contract_milestone' ? t('quantumCard.rungs.railMilestone', 'a contract milestone') : r))
  return tp('quantumCard.rungs.settlesHere', 'Settles here through {rails}.', { rails: rails.join(t('quantumCard.rungs.or', ' or ')) })
}
</script>

<style scoped>
@property --qc-a {
  syntax: '<angle>';
  inherits: false;
  initial-value: 210deg;
}

.qc {
  position: relative;
  font-family: 'IBM Plex Sans', 'Inter', system-ui, sans-serif;
  font-weight: 300;
  color: #e8eef6;
  text-align: left;
  --qc-cut: 12px;
}
/* the faceted, light-refracting edge: a 1px prism ring, cut at the corners like a stone */
.qc--framed {
  padding: 1px;
  clip-path: polygon(var(--qc-cut) 0, calc(100% - var(--qc-cut)) 0, 100% var(--qc-cut), 100% calc(100% - var(--qc-cut)),
    calc(100% - var(--qc-cut)) 100%, var(--qc-cut) 100%, 0 calc(100% - var(--qc-cut)), 0 var(--qc-cut));
  background: conic-gradient(from var(--qc-a), #3a4a6c 0deg, #7fd8f0 38deg, #3a4a6c 72deg, #c3b4f7 118deg, #3a4a6c 152deg,
    #f3efe4 198deg, #3a4a6c 232deg, #efc98a 288deg, #3a4a6c 322deg, #7fd8f0 360deg);
  animation: qc-refract 16s linear infinite;
}
.qc--framed > .qc-in {
  clip-path: polygon(calc(var(--qc-cut) - 0.4px) 0, calc(100% - var(--qc-cut) + 0.4px) 0, 100% calc(var(--qc-cut) - 0.4px),
    100% calc(100% - var(--qc-cut) + 0.4px), calc(100% - var(--qc-cut) + 0.4px) 100%, calc(var(--qc-cut) - 0.4px) 100%,
    0 calc(100% - var(--qc-cut) + 0.4px), 0 calc(var(--qc-cut) - 0.4px));
  background-color: #0a0e1a;
  /* the light a cut stone catches: a faint wash from above, and a facet at each upper corner */
  background-image:
    linear-gradient(135deg, rgba(243, 239, 228, 0.08) 0, rgba(243, 239, 228, 0) 34px),
    linear-gradient(225deg, rgba(195, 180, 247, 0.08) 0, rgba(195, 180, 247, 0) 34px),
    radial-gradient(120% 80% at 18% 0%, rgba(127, 216, 240, 0.06), rgba(127, 216, 240, 0) 60%);
  padding: 14px 16px 16px;
}
.qc--tile > .qc-in {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(195, 180, 247, 0.22);
}
@keyframes qc-refract { to { --qc-a: 570deg; } }

.qc-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.qc-glyph { width: 15px; height: 15px; flex: 0 0 auto; fill: none; stroke: #9fdcf0; stroke-width: 0.9; stroke-linejoin: round; }
.qc-eyebrow {
  color: #9fdcf0;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.qc-ver { color: #b4c0d0; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 10.5px; }
.qc-check {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border: 1px solid currentColor;
  border-radius: 2px;
}
.qc-check--ok { color: #9be7c4; }
.qc-check--bad { color: #f5b38a; }
.qc-check--unread { color: #c3cad6; }

.qc-roles { color: #c9d3e0; font-size: 12px; margin: 6px 0 0; letter-spacing: 0.02em; }
.qc-summary { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0 0; }
.qc-summary-item { color: #dfe7f1; font-size: 12px; }

.qc-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin: 12px 0 0; }
.qc-tab {
  color: #c9d3e0;
  background: transparent;
  border: 1px solid rgba(201, 211, 224, 0.28);
  border-radius: 2px;
  font: inherit;
  font-size: 12px;
  padding: 3px 10px;
  cursor: pointer;
}
.qc-tab--on { color: #f3efe4; border-color: #c3b4f7; }
.qc-tab:focus-visible { outline: 1px solid #9fdcf0; outline-offset: 2px; }

.qc-body { display: grid; gap: 14px; margin-top: 12px; }
.qc-body--full { grid-template-columns: minmax(0, 260px) minmax(0, 1fr); align-items: start; }
.qc-body--tile, .qc-body--chat { grid-template-columns: 1fr; }
@media (max-width: 640px) { .qc-body--full { grid-template-columns: 1fr; } }

.qc-latt { margin: 0; display: grid; gap: 6px; }
.qc--tile .qc-latt, .qc--chat .qc-latt { grid-template-columns: 88px minmax(0, 1fr); align-items: center; gap: 12px; }
.qc-note { color: #b4c0d0; font-size: 11.5px; line-height: 1.45; margin: 0; }
.qc-latt-name { color: #dfe7f1; }
.qc-digest { color: #b4c0d0; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 10.5px; margin-left: 4px; }
.qc-more { display: block; color: #b4c0d0; margin-top: 2px; }

.qc-facts { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 5px 14px; margin: 0; font-size: 12.5px; }
.qc-label { color: #a3b1c4; font-weight: 400; }
.qc-value { color: #e8eef6; margin: 0; overflow-wrap: anywhere; }
.qc-age { color: #b4c0d0; font-size: 11px; }

.qc-h {
  color: #9fdcf0;
  font-family: 'IBM Plex Mono', ui-monospace, monospace;
  font-size: 10.5px;
  font-weight: 400;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  margin: 0 0 6px;
}
.qc-rungs, .qc-receipts { margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(201, 211, 224, 0.16); }
.qc--tile .qc-rungs, .qc--chat .qc-rungs { margin-top: 10px; padding-top: 8px; }
.qc-rung { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 1px 10px; font-size: 12px; margin-bottom: 6px; }
.qc-rung-n { color: #dfe7f1; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 11px; }
.qc-rung-name { color: #e8eef6; }
.qc-rung-state { grid-column: 2; font-size: 11.5px; }
.qc-rung-state--settles_here { color: #9be7c4; }
.qc-rung-state--offered { color: #e8d39a; }
.qc-rung-state--claims_only { color: #c3cad6; }
.qc--tile .qc-rungs, .qc--chat .qc-rungs { display: flex; flex-wrap: wrap; gap: 2px 14px; }
.qc--tile .qc-h, .qc--chat .qc-h { flex: 0 0 100%; }
.qc--tile .qc-rung, .qc--chat .qc-rung { display: inline-flex; gap: 6px; margin-bottom: 0; }
.qc--tile .qc-rung-state, .qc--chat .qc-rung-state { font-size: 11px; }
.qc-tests { grid-column: 2; list-style: none; padding: 0; margin: 2px 0 0; }
.qc-test { display: flex; flex-wrap: wrap; gap: 4px 10px; color: #b4c0d0; font-size: 11px; }
.qc-code { color: #dfe7f1; font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 11px; }
.qc-test-rate { color: #b4c0d0; }
.qc-line { color: #dfe7f1; font-size: 12px; line-height: 1.5; margin: 0 0 4px; }

@media (prefers-reduced-motion: reduce) {
  .qc--framed { animation: none; }
}
</style>
