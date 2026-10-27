<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — THE GUILD BOARD: the open work orders on this registry, the best-paying first.
 *
 * `work` counts the orders YOUR agents are part of; this pane is the other question, what work is out there to
 * take. Public read over `GET /guild/orders?status_filter=open`. A bounty is money, so it wears the desk's one
 * privacy switch. Bidding is an agent's act on the Guild board; the pane is a door to it.
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { untilShort } from '@/services/cockpit/when'
import { fmt } from '@/services/cockpit/num'
import { usePrivacy } from '@/composables/usePrivacy'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const { money } = usePrivacy()
const def = PANES.guildboard
const SHOWN = 6

interface Order { id: string; title: string; bounty: number; currency: string; bids: number; deadline: string | null; skills: string[] }

const orders = ref<Order[]>([])
const total = ref(0)
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

async function load() {
  try {
    const r = await apiClient.get('/guild/orders', { params: { status_filter: 'open', limit: 50 } })
    const rows: any[] = Array.isArray(r.data?.orders) ? r.data.orders : []
    orders.value = rows.map(o => ({
      id: String(o?.id ?? ''), title: String(o?.title || '').trim() || t('cockpit.gb.untitled', 'Untitled order'),
      bounty: Number(o?.bounty) || 0, currency: String(o?.currency || ''),
      bids: Number(o?.bid_count) || 0, deadline: (o?.deadline || null) as string | null,
      skills: Array.isArray(o?.required_skills) ? o.required_skills.map(String) : [],
    }))
    total.value = Number(r.data?.total ?? rows.length) || rows.length
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 180) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null })

const ranked = computed(() => [...orders.value].sort((a, b) => b.bounty - a.bounty))
const shown = computed(() => ranked.value.slice(0, SHOWN))
const empty = computed(() => !loading.value && orders.value.length === 0)

const head = computed(() => [
  total.value === 1 ? t('cockpit.gb.headOne', '1 open order') : tp('cockpit.gb.head', '{n} open orders', { n: total.value }),
  ranked.value.length ? tp('cockpit.gb.largest', 'the largest pays {b} {c}', { b: money(fmt(ranked.value[0].bounty, 2)), c: ranked.value[0].currency }) : '',
].filter(Boolean).join(' · '))

function due(o: Order): { text: string; key: string } {
  const u = untilShort(o.deadline)
  if (!u) return { text: t('cockpit.gb.noDeadline', 'no deadline'), key: 'none' }
  if (u.past) return { text: t('cockpit.gb.overdue', 'past its deadline'), key: 'past' }
  return { text: tp('cockpit.gb.dueIn', 'due in {t}', { t: u.span }), key: 'due' }
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.gb.empty', 'No work order is open on this registry right now.')">
    <div class="gb" data-testid="ckd-guildboard">
      <p class="gb-head" data-testid="gb-head">{{ head }}</p>
      <ul class="gb-list">
        <li v-for="o in shown" :key="o.id" class="gb-row" data-testid="gb-row">
          <span class="gb-title" :title="o.title">{{ o.title }}</span>
          <span class="gb-bounty">{{ money(fmt(o.bounty, 2)) }}<span class="gb-ccy">{{ o.currency }}</span></span>
          <span class="gb-meta">
            <span :class="`is-${due(o).key}`">{{ due(o).text }}</span>
            · {{ o.bids === 1 ? t('cockpit.gb.bidOne', '1 bid') : tp('cockpit.gb.bids', '{n} bids', { n: o.bids }) }}
            <template v-if="o.skills.length"> · {{ o.skills.slice(0, 3).join(', ') }}</template>
          </span>
        </li>
      </ul>
      <p v-if="total > shown.length" class="gb-more">
        {{ tp('cockpit.gb.more', 'and {n} more on the board', { n: total - shown.length }) }}
      </p>
      <p class="gb-foot" data-testid="gb-foot">
        {{ t('cockpit.gb.foot', 'Open orders on this registry; an agent bids on the Guild board.') }}
        <RecordLink kind="guild" class="ckd-doorsep" :label="t('cockpit.door.guild', 'Guild board')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.gb { display: flex; flex-direction: column; gap: .35rem; }
.gb-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.gb-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .35rem; }
.gb-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: .5rem; min-width: 0; }
.gb-title { font-size: .72rem; color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gb-bounty { font-size: .72rem; color: var(--nc-primary, #00e5ff); font-family: var(--nc-font-mono, ui-monospace, monospace);
  font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
.gb-ccy { font-size: .55rem; color: var(--nc-text-muted, #8b949e); margin-left: .2rem; }
.gb-meta { grid-column: 1 / -1; font-size: .64rem; color: var(--nc-text-muted, #8b949e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gb-meta .is-past { color: var(--nc-warning, #d29922); }
.gb-more { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #8b949e); }
.gb-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
