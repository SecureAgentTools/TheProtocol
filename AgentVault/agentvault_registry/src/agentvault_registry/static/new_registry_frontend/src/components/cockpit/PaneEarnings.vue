<script setup lang="ts">
import { useFillCount } from '@/composables/useFillCount'
import { fmt as nFmt, fmtCount as nCount, fmtCompact as nCompact, fmtAuto as nAuto, isCompacted as nIsCompact, fmtDateTime as nWhen } from '@/services/cockpit/num'
/**
 * §COCKPITMODULES M2 — INCOME. The income half of the book.
 *
 * `book` answers what this account OWNS; this answers what it is PAID. 705 payout records,
 * 515,473 AVT distributed across 7 agents on this account at build time.
 *
 * 🔴 THE FAILED PAYOUTS SIT BESIDE THE PAID ONES, out of the SAME query. An income pane
 * that summed only successes is precisely how 66,326 AVT went unnoticed for three months —
 * every surface added up what worked and nothing added up what didn't. The two panes read
 * one table, so they cannot disagree about the same fact.
 *
 * ⚠ `staked` is the REGISTRY's cached view (`agents.staked_balance`), not TEG truth, and
 * says so in its title. The two can lag; a number that might be stale must name its source.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import RecordLink from './RecordLink.vue'
import AgentLink from './AgentLink.vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { governanceMode } from '@/services/membership/membership'
import { PANES } from './paneRegistry'
import { usePrivacy } from '@/composables/usePrivacy'

const { t, tp } = useI18n()
// §LANDINGTRUTH (15): the empty state follows the governance this registry runs
const { config: paneCfg } = useRegistryConfig()
const paneMember = computed(() => governanceMode(paneCfg.value) === 'member')
// agentvault2-33: the lock half follows the payouts switch (member mode does not switch payouts off), the membership
// half the mode; nothing is paid for membership in any mode. Fail-closed: unknown payouts read as off.
const paneRewardsOn = computed(() => paneCfg.value.staking_rewards_enabled === true)
const paneEmptyText = computed(() => paneRewardsOn.value
  ? (paneMember.value
    ? t('cockpit.earnings.emptyMemberRewardsOn', 'No payout on locked units has been made on this account yet. Voting weight comes from membership here; nothing is paid for membership.')
    : t('cockpit.earnings.emptyRewardsOn', 'No payout on locked units has been made on this account yet.'))
  : (paneMember.value
    ? t('cockpit.earnings.emptyMember', 'Voting weight comes from membership here. Nothing is paid for a lock or for membership.')
    : t('cockpit.earnings.empty', 'Locks give voting weight only. Nothing is paid for a lock.')))
// §BAFIN (agentvault2-5b, the letter): the empty state is the lock sentence; no door says a lock earns anything
const { money } = usePrivacy()
const def = PANES.earnings

const rows = ref<any[]>([])
/** §COCKPITTILES T1 — a fixed page (a request must not re-fire on every resize), rendered
 *  to whatever the tile holds, with the remainder stated rather than dropped. */
const FETCH_LIMIT = 40
const listEl = ref<HTMLElement | null>(null)
const { count: fitRows } = useFillCount(listEl, { rowPx: 40, min: 3, max: FETCH_LIMIT, reservePx: 96 })
const shown = computed(() => rows.value.slice(0, fitRows.value))
const heldBack = computed(() => Math.max(0, rows.value.length - shown.value.length))
const totals = ref<any>({})
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const { data } = await apiClient.get('/developers/me/earnings', { params: { limit: FETCH_LIMIT } })
    rows.value = Array.isArray(data?.rows) ? data.rows : []
    totals.value = data || {}
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 180) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const empty = computed(() => !loading.value && rows.value.length === 0)

/** 🔴 TWO AGENTS ON THIS ACCOUNT ARE BOTH CARD-NAMED `localhost`, and the pane rendered
 *  them as two identical rows with different money against each. A name that does not
 *  identify is worse here than a DID would be, because it looks like it identifies. When a
 *  name is not unique IN THIS LIST it gets the tail of its DID; unique names are left
 *  alone, so the disambiguator appears only where there is something to disambiguate. */
const dupNames = computed<Set<string>>(() => {
  const seen = new Map<string, number>()
  for (const r of rows.value) {
    const n = String(r.agent_name || '')
    if (n) seen.set(n, (seen.get(n) || 0) + 1)
  }
  return new Set([...seen.entries()].filter(([, c]) => c > 1).map(([n]) => n))
})
function label(r: any): string {
  const n = String(r.agent_name || '')
  if (!n) return String(r.did || '—')
  return dupNames.value.has(n) ? `${n} …${String(r.did || '').slice(-6)}` : n
}

function fmt(v: any): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '—')
  return nAuto(n)
}
function ageOf(iso?: string | null): string {
  if (!iso) return '—'
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="paneEmptyText"
             data-testid="ckd-earnings">
    <p class="ckd-e-head" data-testid="ckd-e-head">
      {{ tp('cockpit.earnings.head', '{amt} {ccy} paid to {n} agents over {r} payouts.',
            { amt: money(fmt(totals.paid_total)), ccy: totals.currency || '',
              n: totals.agents ?? 0, r: totals.records ?? 0 }) }}
    </p>
    <!-- Undelivered is stated in the same breath as delivered, never omitted. -->
    <p v-if="Number(totals.undelivered_total || 0) > 0" class="ckd-e-warn" data-testid="ckd-e-warn">
      {{ tp('cockpit.earnings.undelivered', '{amt} {ccy} was owed and never delivered — see What didn\'t happen.',
            { amt: money(fmt(totals.undelivered_total)), ccy: totals.currency || '' }) }}
    </p>
    <p v-else class="ckd-e-ok" data-testid="ckd-e-ok">
      {{ t('cockpit.earnings.allDelivered', 'Every computed payout on this account has been delivered.') }}
    </p>

    <ul class="ckd-e-list" ref="listEl" :data-fit="fitRows">
      <!-- 🔴 STACKED, and for the reason §COCKPITPOLISH found in STOP: four right-aligned
           fixed columns in a ~280px pane left the NAME about three characters wide. It
           rendered `Iron…`, `Glas…`, `Hype…` — and TWO different agents both came out as
           `loca…`, which is not an abbreviation, it is an ambiguity. The identity gets its
           own line and the numbers get theirs.
           ⚠ `tier` left the row entirely: it read "dynamic" on all seven, spending 3.4rem
           of a narrow pane to say the same word every time. It lives in the title now. -->
      <li v-for="r in shown" :key="r.did" class="ckd-e-row" data-testid="ckd-e-row">
        <div class="ckd-e-l1">
          <!-- §COCKPITFRAME F5 — the identity opens the agent card that already existed (`AgentDetailModal`); the desk owns the one dialog. -->
          <AgentLink class="ckd-e-name" :did="r.did" :label="label(r)" />
          <span class="ckd-e-age" :title="r.last_paid_at || ''">{{ ageOf(r.last_paid_at) }}</span>
        </div>
        <div class="ckd-e-l2">
          <span class="ckd-e-staked"
                :title="tp('cockpit.earnings.stakedTitle', 'Locked, as the registry has it cached: {v}', { v: String(r.staked) })">
            {{ t('cockpit.earnings.stakedLbl', 'locked') }} {{ money(fmt(r.staked)) }}
          </span>
          <span class="ckd-e-paid" :title="String(r.paid)">
            {{ tp('cockpit.earnings.paidLbl', 'paid {v} over {n}', { v: money(fmt(r.paid)), n: r.paid_n }) }}
          </span>
        </div>
      </li>
    </ul>
    <!-- Filling is not slicing: what did not fit is named. -->
    <p v-if="heldBack" class="ckd-e-more" data-testid="ckd-e-more">
      {{ tp('cockpit.earnings.more', '+{n} more agents were paid — make the tile taller in Arrange.', { n: heldBack }) }}
    </p>
    <p class="ckd-e-foot" data-testid="ckd-e-foot">
      {{ t('cockpit.earnings.foot', 'locked is the registry cache · paid is what was delivered · age is the last payment') }}
      <!-- a door opens only where the room is there: the Locks page only where staking_enabled is true -->
      <RecordLink v-if="paneCfg?.staking_enabled === true" kind="staking" class="ckd-doorsep"
                  :label="t('cockpit.door.staking', 'Locks')" />
    </p>
  </PaneShell>
</template>

<style scoped>
.ckd-e-head { margin: 0 0 .25rem; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-e-warn { margin: 0 0 .4rem; font-size: .66rem; color: var(--nc-warning, #d29922); }
.ckd-e-ok   { margin: 0 0 .4rem; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.ckd-e-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .2rem; }
.ckd-e-row  { font-size: .72rem; padding: .1rem 0; }
.ckd-e-l1 { display: flex; align-items: baseline; gap: .35rem; }
.ckd-e-l2 { display: flex; align-items: baseline; gap: .5rem; margin-left: .1rem; }
.ckd-e-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--nc-text-secondary, #c9d1d9); }
/* Tabular figures so the two number runs line up down the list even though they are not
   in fixed columns — `min-width` is a floor and would leave the edge ragged. */
.ckd-e-staked, .ckd-e-paid {
  font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .64rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-e-staked { color: var(--nc-text-muted, #6e7681); flex: 0 0 auto; }
.ckd-e-paid { color: var(--nc-success, #3fb950); flex: 1; }
.ckd-e-age { font-family: var(--nc-font-mono, ui-monospace, monospace); font-variant-numeric: tabular-nums;
  font-size: .62rem; color: var(--nc-text-muted, #6e7681); flex: 0 0 auto; text-align: right; }
.ckd-e-more { margin: .3rem 0 0; font-size: .62rem; color: var(--nc-text-dim, #8b949e); }
.ckd-e-foot { margin: .4rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
.ckd-doorsep { margin-left: .4rem; }
</style>
