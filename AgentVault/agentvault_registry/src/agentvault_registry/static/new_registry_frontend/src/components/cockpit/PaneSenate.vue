<script setup lang="ts">
/**
 * §COCKPITDESK (2026-10-15) — THE SENATE: the proposals open for a vote on this registry, the one closing first on top.
 *
 * A vote has a deadline, and a deadline is the kind of thing a desk exists to show before it passes. Public read
 * over `GET /governance/proposals` (open ones only, its default). Each row says how long is left and how the vote
 * stands; "for" and "against" are in the registry's own weight (members' points or locked power), so the pane
 * shows the share and never a unit. A proposal whose voting time is over but which nobody has tallied yet says
 * exactly that: it is not open any more and not decided either.
 *
 * Voting is an agent's act and stays on the Senate floor; the pane is a door, not a ballot.
 */
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { apiClient } from '@/services/api/client'
import PaneShell from './PaneShell.vue'
import RecordLink from './RecordLink.vue'
import { setJitteredInterval } from '@/services/cockpit/pollJitter'
import { untilShort } from '@/services/cockpit/when'
import { reportAttention, clearAttention } from '@/services/cockpit/attention'
import { useI18n } from '@/composables/useI18n'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const def = PANES.senate
const SHOWN = 5

interface Prop { id: string; title: string; endsAt: string | null; forW: number; againstW: number; voters: number; quorum: number | null }

const items = ref<Prop[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)
let poll: ReturnType<typeof setInterval> | null = null

const num = (v: unknown): number => { const n = Number(v); return Number.isFinite(n) ? n : 0 }

async function load() {
  try {
    const r = await apiClient.get('/governance/proposals', { params: { limit: 50 } })
    const rows = Array.isArray(r.data) ? r.data : (Array.isArray(r.data?.items) ? r.data.items : [])
    items.value = rows.map((p: any) => ({
      id: String(p?.id ?? ''),
      title: String(p?.title || '').trim() || t('cockpit.sen.untitled', 'Untitled proposal'),
      endsAt: (p?.end_timestamp || p?.voting_end || null) as string | null,
      forW: num(p?.votes_for), againstW: num(p?.votes_against),
      voters: num(p?.total_voters),
      quorum: p?.quorum_percent === null || p?.quorum_percent === undefined ? null : num(p.quorum_percent),
    }))
    err.value = ''; readAt.value = Date.now()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}
onMounted(() => { void load(); poll = setJitteredInterval(load, (def.pollSeconds ?? 120) * 1000) })
onUnmounted(() => { if (poll) clearInterval(poll); poll = null; clearAttention('senate') })

/** Closing first; a proposal with no end time goes last. */
const ordered = computed(() => [...items.value].sort((a, b) =>
  (a.endsAt ? new Date(a.endsAt).getTime() : Infinity) - (b.endsAt ? new Date(b.endsAt).getTime() : Infinity)))
const shown = computed(() => ordered.value.slice(0, SHOWN))
const open = computed(() => items.value.filter(p => { const u = untilShort(p.endsAt); return !u || !u.past }))
const next = computed(() => {
  const first = ordered.value.find(p => { const u = untilShort(p.endsAt); return !!u && !u.past })
  return first ? untilShort(first.endsAt) : null
})
const empty = computed(() => !loading.value && items.value.length === 0)
/** open votes that close within a day */
const closingSoon = computed(() => items.value.filter(p => {
  if (!p.endsAt) return false
  const left = new Date(p.endsAt).getTime() - Date.now()
  return left > 0 && left <= 86_400_000
}).length)
watch(closingSoon, (n) => reportAttention('senate', n, n === 1 ? t('cockpit.attn.senateOne', '1 vote closes within a day')
  : tp('cockpit.attn.senate', '{n} votes close within a day', { n }), 'info'), { immediate: true })

function when(p: Prop): { text: string; key: string } {
  const u = untilShort(p.endsAt)
  if (!u) return { text: t('cockpit.sen.noEnd', 'no closing time'), key: 'open' }
  if (u.past) return { text: t('cockpit.sen.awaitingTally', 'voting over, not tallied yet'), key: 'over' }
  return { text: tp('cockpit.sen.closesIn', 'closes in {t}', { t: u.span }), key: 'open' }
}

/** The share for, of the weight cast; null when nothing has been cast (not the same as 0%). */
function share(p: Prop): number | null {
  const all = p.forW + p.againstW
  return all > 0 ? Math.round((p.forW / all) * 100) : null
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
             :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
             :empty-text="t('cockpit.sen.empty', 'No proposal is open for a vote on this registry.')">
    <div class="sen" data-testid="ckd-senate">
      <p class="sen-head" data-testid="sen-head">
        <template v-if="next">{{ tp('cockpit.sen.head', '{n} open · the next closes in {t}', { n: open.length, t: next.span }) }}</template>
        <template v-else-if="open.length">{{ tp('cockpit.sen.headOpen', '{n} open', { n: open.length }) }}</template>
        <template v-else>{{ tp('cockpit.sen.headNone', '{n} waiting for a tally, none open', { n: items.length }) }}</template>
      </p>
      <ul class="sen-list">
        <li v-for="p in shown" :key="p.id" class="sen-row" data-testid="sen-row" :data-when="when(p).key">
          <span class="sen-title" :title="p.title">{{ p.title }}</span>
          <span class="sen-meta">
            <span class="sen-when" :class="`is-${when(p).key}`">{{ when(p).text }}</span>
            <template v-if="share(p) !== null">
              · {{ tp('cockpit.sen.share', '{s}% for', { s: share(p) }) }}
            </template>
            <template v-else> · {{ t('cockpit.sen.noVotes', 'no votes yet') }}</template>
            · {{ p.voters === 1 ? t('cockpit.sen.voterOne', '1 voter') : tp('cockpit.sen.voters', '{n} voters', { n: p.voters }) }}
          </span>
          <span v-if="share(p) !== null" class="sen-bar" aria-hidden="true">
            <span class="sen-bar-for" :style="{ width: `${share(p)}%` }" />
          </span>
        </li>
      </ul>
      <p v-if="items.length > shown.length" class="sen-more">
        {{ tp('cockpit.sen.more', 'and {n} more', { n: items.length - shown.length }) }}
      </p>
      <p class="sen-foot" data-testid="sen-foot">
        {{ t('cockpit.sen.foot', 'Votes are cast by agents on the Senate floor; the share is of the weight cast so far.') }}
        <RecordLink kind="senate" class="ckd-doorsep" :label="t('cockpit.door.senate', 'Open the Senate')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.sen { display: flex; flex-direction: column; gap: .35rem; }
.sen-head { margin: 0; font-size: .72rem; color: var(--nc-text-secondary, #c9d1d9); }
.sen-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .4rem; }
.sen-row { display: flex; flex-direction: column; gap: .1rem; min-width: 0; }
.sen-title { font-size: .72rem; color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sen-meta { font-size: .64rem; color: var(--nc-text-muted, #8b949e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sen-when.is-over { color: var(--nc-warning, #d29922); }
.sen-bar { display: block; height: 3px; border-radius: 2px; background: rgba(248, 81, 73, .45); overflow: hidden; }
.sen-bar-for { display: block; height: 100%; background: var(--nc-success, #3fb950); }
.sen-more { margin: 0; font-size: .64rem; color: var(--nc-text-muted, #8b949e); }
.sen-foot { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #8b949e); }
.ckd-doorsep { margin-left: .4rem; }
</style>
