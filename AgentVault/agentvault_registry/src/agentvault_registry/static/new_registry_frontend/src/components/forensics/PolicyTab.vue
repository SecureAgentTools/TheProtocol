<template>
  <div class="lfp">
    <!-- Gate legend — how to READ this table (the f037 two-sided gate) -->
    <div class="lfp-legend">
      <div class="lfp-legend-head">
        <Icon name="mdi:information" class="lfp-legend-ico" />
        <strong>How emission is gated (f037)</strong>
      </div>
      <ul class="lfp-legend-list">
        <li><b>Registry</b> emitter is <span class="lfp-k lfp-k--open">fail-OPEN</span> — no policy row ⇒ it emits anyway (unless <code>EVENT_EMITTER_FAIL_CLOSED</code>). Treat this table as a partition/deny-list, not a complete event inventory.</li>
        <li><b>TEG</b> emitter is <span class="lfp-k lfp-k--closed">fail-CLOSED</span> — no policy row ⇒ it stays silent. A “missing expected event” can be a silent policy block, not a bug.</li>
        <li><code>LedgerBalanceChanged</code> is <b>force-allowed from TEG</b> (the L2 balance outbox) regardless of this table.</li>
        <li><span class="lfp-tag lfp-tag--bal">balance-moving</span> rows drive the supply projection — they must never be <span class="lfp-tag lfp-tag--audit">audit-only</span> and must carry a deterministic idempotency key.</li>
        <li>What each side does with every type, the counts in this frame's store and what is wrong, type by type: <router-link to="/admin/emission-policy" class="lfp-link" data-testid="lfp-to-emission-policy">Emission Policy</router-link>.</li>
      </ul>
    </div>

    <!-- Toolbar -->
    <div class="lfp-toolbar">
      <input v-model="q" class="lfp-input lfp-input--wide" placeholder="Filter by event_type or description…" />
      <div class="lfp-chips">
        <button
          v-for="f in filterDefs"
          :key="f.key"
          type="button"
          class="lfp-chip"
          :class="{ 'lfp-chip--active': activeFilter === f.key }"
          @click="activeFilter = f.key"
        >{{ f.label }} <span class="lfp-chip-n">{{ store.policiesRead ? f.count : '—' }}</span></button>
      </div>
      <span class="lfp-spacer"></span>
      <button class="lfp-btn lfp-btn-ghost" @click="exportCsv" :disabled="!rows.length">
        <Icon name="download" class="lfp-btn-ico" /> CSV
      </button>
      <button class="lfp-btn" @click="reload" :disabled="store.loadingPolicies">
        <Icon name="refresh-cw" class="lfp-btn-ico" /> {{ store.loadingPolicies ? '…' : 'Refresh' }}
      </button>
    </div>

    <!-- Table -->
    <div class="lfp-table-wrap">
      <table class="lfp-table">
        <thead>
          <tr>
            <th class="lfp-sortable" @click="setSort('event_type')">event_type {{ sortArrow('event_type') }}</th>
            <th class="lfp-center" title="emit_from_teg">TEG</th>
            <th class="lfp-center" title="emit_from_registry">Registry</th>
            <th class="lfp-center" title="skip_in_projection">Projection</th>
            <th>Description</th>
            <th class="lfp-sortable" @click="setSort('updated_at')">Updated {{ sortArrow('updated_at') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in rows"
            :key="p.event_type"
            class="lfp-row"
            :class="{ 'lfp-row--bal': isBalanceMoving(p.event_type), 'lfp-row--violation': isViolation(p) }"
          >
            <td class="lfp-mono">
              <span class="lfp-et">{{ p.event_type }}</span>
              <span v-if="isBalanceMoving(p.event_type)" class="lfp-tag lfp-tag--bal">balance</span>
              <span v-if="isViolation(p)" class="lfp-tag lfp-tag--bad" title="balance-moving row marked skip_in_projection — supply drift risk">⚠ skip</span>
            </td>
            <td class="lfp-center"><span class="lfp-pip" :class="p.emit_from_teg ? 'lfp-pip--on' : 'lfp-pip--off'">{{ p.emit_from_teg ? '✓' : '·' }}</span></td>
            <td class="lfp-center"><span class="lfp-pip" :class="p.emit_from_registry ? 'lfp-pip--on' : 'lfp-pip--off'">{{ p.emit_from_registry ? '✓' : '·' }}</span></td>
            <td class="lfp-center">
              <span v-if="p.skip_in_projection" class="lfp-tag lfp-tag--audit">audit-only</span>
              <span v-else class="lfp-muted">counted</span>
            </td>
            <td class="lfp-desc">{{ p.description || '—' }}</td>
            <td class="lfp-muted lfp-nowrap">{{ fromNow(p.updated_at) }}</td>
          </tr>
          <tr v-if="store.policiesFailed && !store.policies.length && !store.loadingPolicies">
            <td colspan="6"><ReadFailedNotice dense :retry="reload" data-testid="lfp-unread" /></td>
          </tr>
          <tr v-else-if="!rows.length && !store.loadingPolicies && store.policiesRead">
            <td colspan="6" class="lfp-empty">No policies match.</td>
          </tr>
          <tr v-if="store.loadingPolicies && !store.policies.length">
            <td colspan="6" class="lfp-empty">Loading emission policies…</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="lfp-foot">
      <span class="lfp-muted">{{ store.policiesRead ? rows.length : '—' }} of {{ store.policiesRead ? store.policies.length : '—' }} policies</span>
      <span class="lfp-muted lfp-edit-note">
        Read-only in this build · live edit (PUT) wires in once registry rebuilds are unblocked.
      </span>
    </div>

    <div v-if="store.error" class="lfp-error">{{ store.error }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import Icon from '@/components/Icon.vue'
import { useForensicsStore } from '@/stores/forensics'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { BALANCE_MOVING_EVENT_TYPES, type EmissionPolicy } from '@/services/api/forensics'
import { downloadCsv, csvFilenameTimestamp } from '@/components/common/csvExport'

dayjs.extend(relativeTime)
const store = useForensicsStore()

const q = ref('')
type FilterKey = 'all' | 'bal' | 'audit' | 'teg' | 'violation'
const activeFilter = ref<FilterKey>('all')
const sortKey = ref<'event_type' | 'updated_at'>('event_type')
const sortDir = ref<'asc' | 'desc'>('asc')

function isBalanceMoving(t: string): boolean {
  return BALANCE_MOVING_EVENT_TYPES.has(t)
}
function isViolation(p: EmissionPolicy): boolean {
  // balance-moving row that is (wrongly) flagged audit-only — supply drift risk
  return isBalanceMoving(p.event_type) && !!p.skip_in_projection
}

const filterDefs = computed(() => {
  const pol = store.policies
  return [
    { key: 'all' as FilterKey, label: 'All', count: pol.length },
    { key: 'bal' as FilterKey, label: 'Balance-moving', count: pol.filter(p => isBalanceMoving(p.event_type)).length },
    { key: 'audit' as FilterKey, label: 'Audit-only', count: pol.filter(p => p.skip_in_projection).length },
    { key: 'teg' as FilterKey, label: 'TEG-emitting', count: pol.filter(p => p.emit_from_teg).length },
    { key: 'violation' as FilterKey, label: '⚠ Violations', count: pol.filter(p => isViolation(p)).length },
  ]
})

const rows = computed<EmissionPolicy[]>(() => {
  const needle = q.value.trim().toLowerCase()
  let out = store.policies.filter(p => {
    if (activeFilter.value === 'bal' && !isBalanceMoving(p.event_type)) return false
    if (activeFilter.value === 'audit' && !p.skip_in_projection) return false
    if (activeFilter.value === 'teg' && !p.emit_from_teg) return false
    if (activeFilter.value === 'violation' && !isViolation(p)) return false
    if (needle) {
      const hay = `${p.event_type} ${p.description || ''}`.toLowerCase()
      if (!hay.includes(needle)) return false
    }
    return true
  })
  out = [...out].sort((a, b) => {
    let cmp = 0
    if (sortKey.value === 'event_type') cmp = a.event_type.localeCompare(b.event_type)
    else cmp = String(a.updated_at || '').localeCompare(String(b.updated_at || ''))
    return sortDir.value === 'asc' ? cmp : -cmp
  })
  return out
})

function setSort(k: 'event_type' | 'updated_at') {
  if (sortKey.value === k) sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  else { sortKey.value = k; sortDir.value = k === 'updated_at' ? 'desc' : 'asc' }
}
function sortArrow(k: 'event_type' | 'updated_at') {
  if (sortKey.value !== k) return ''
  return sortDir.value === 'asc' ? '▲' : '▼'
}
function fromNow(ts?: string | null): string {
  if (!ts) return '—'
  return dayjs(ts).fromNow()
}
function reload() { store.loadPolicies() }
function exportCsv() {
  downloadCsv(rows.value, [
    { label: 'event_type', value: p => p.event_type },
    { label: 'emit_from_teg', value: p => String(p.emit_from_teg) },
    { label: 'emit_from_registry', value: p => String(p.emit_from_registry) },
    { label: 'skip_in_projection', value: p => String(p.skip_in_projection) },
    { label: 'balance_moving', value: p => String(isBalanceMoving(p.event_type)) },
    { label: 'description', value: p => p.description || '' },
    { label: 'updated_at', value: p => p.updated_at || '' },
  ], `emission_policies_${csvFilenameTimestamp()}.csv`)
}

onMounted(() => { if (!store.policies.length) store.loadPolicies() })
</script>

<style scoped>
.lfp {
  --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --red: #ff3366; --green: #00ff88; --amber: #ff9500; --muted: #6b7785;
  --border: rgba(var(--cyan-rgb), 0.18); --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  --text-bright: #e8eaed; color: var(--text-bright);
}
.lfp-legend {
  background: rgba(var(--cyan-rgb), 0.04); border: 1px solid var(--border);
  border-radius: 8px; padding: 12px 16px; margin-bottom: 16px;
}
.lfp-legend-head { display: flex; align-items: center; gap: 8px; color: var(--cyan); font-size: 13px; margin-bottom: 8px; }
.lfp-legend-ico { width: 16px; height: 16px; }
.lfp-legend-list { margin: 0; padding-left: 18px; color: var(--muted); font-size: 12px; line-height: 1.7; }
.lfp-legend-list b { color: #c8d8e8; }
.lfp-legend-list code { background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px; font-family: var(--mono); font-size: 11px; color: #b0c0d0; }
.lfp-k { font-weight: 700; padding: 0 4px; border-radius: 3px; }
.lfp-k--open { color: var(--amber); }
.lfp-k--closed { color: #9ad6ff; }

.lfp-toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.lfp-spacer { flex: 1; }
.lfp-input {
  background: rgba(0,0,0,0.35); color: var(--text-bright); border: 1px solid var(--border);
  border-radius: 4px; padding: 6px 10px; font-size: 12px; font-family: var(--mono);
}
.lfp-input--wide { min-width: 280px; }
.lfp-input:focus { outline: none; border-color: rgba(var(--cyan-rgb), 0.5); }
.lfp-chips { display: flex; gap: 6px; flex-wrap: wrap; }
.lfp-chip {
  background: rgba(var(--cyan-rgb), 0.03); border: 1px solid var(--border); color: var(--muted);
  border-radius: 14px; padding: 5px 12px; font-size: 11px; cursor: pointer; font-weight: 600;
}
.lfp-chip:hover { border-color: rgba(var(--cyan-rgb), 0.4); color: var(--text-bright); }
.lfp-chip--active { background: rgba(var(--cyan-rgb), 0.12); color: var(--cyan); border-color: rgba(var(--cyan-rgb), 0.45); }
.lfp-chip-n { opacity: 0.7; font-size: 10px; }
.lfp-btn {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(var(--cyan-rgb), 0.12); color: var(--cyan); border: 1px solid rgba(var(--cyan-rgb), 0.35);
  border-radius: 4px; padding: 6px 12px; font-size: 12px; cursor: pointer; font-weight: 600;
}
.lfp-btn:hover:not(:disabled) { background: rgba(var(--cyan-rgb), 0.22); }
.lfp-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.lfp-btn-ghost { background: transparent; color: var(--muted); border-color: var(--border); }
.lfp-btn-ico { width: 14px; height: 14px; }

.lfp-table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }
.lfp-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.lfp-table th {
  text-align: left; padding: 9px 12px; color: var(--muted); font-weight: 700; font-size: 10px;
  text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid var(--border); background: rgba(0,0,0,0.25);
  position: sticky; top: 0;
}
.lfp-sortable { cursor: pointer; user-select: none; }
.lfp-center { text-align: center; }
.lfp-table td { padding: 7px 12px; border-bottom: 1px solid rgba(var(--cyan-rgb), 0.06); vertical-align: middle; }
.lfp-row:hover td { background: rgba(var(--cyan-rgb), 0.04); }
.lfp-row--bal td:first-child { box-shadow: inset 3px 0 0 var(--green); }
.lfp-row--violation td { background: rgba(255, 51, 102, 0.07); }
.lfp-mono { font-family: var(--mono); }
.lfp-et { color: #d6e2ee; }
.lfp-desc { color: var(--muted); max-width: 420px; }
.lfp-muted { color: var(--muted); }
.lfp-nowrap { white-space: nowrap; }
.lfp-empty { text-align: center; padding: 24px; color: var(--muted); }

.lfp-pip { font-weight: 800; font-size: 13px; }
.lfp-pip--on { color: var(--green); }
.lfp-pip--off { color: #3a4452; }

.lfp-tag {
  display: inline-block; margin-left: 6px; padding: 1px 7px; border-radius: 8px;
  font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; vertical-align: middle;
}
.lfp-tag--bal { background: rgba(0,255,136,0.14); color: var(--green); }
.lfp-tag--audit { background: rgba(154,214,255,0.16); color: #9ad6ff; }
.lfp-tag--bad { background: rgba(255,51,102,0.2); color: #ff6b8a; }

.lfp-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; font-size: 11px; flex-wrap: wrap; gap: 6px; }
.lfp-edit-note { font-style: italic; opacity: 0.8; }
.lfp-error {
  margin-top: 12px; padding: 10px 14px; background: rgba(255,51,102,0.08);
  border: 1px solid rgba(255,51,102,0.35); color: var(--red); border-radius: 4px; font-size: 12px;
}
.lfp-link { color: #7dd3fc; text-decoration: underline; }
</style>
